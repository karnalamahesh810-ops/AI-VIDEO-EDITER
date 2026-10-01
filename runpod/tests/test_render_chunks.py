"""
One pod's render spread over the serverless workers (src/fanout.py render_pod,
POD_RENDER_FANOUT): chunk planning at clean cuts, the worker side, the pod's
scheduler (failures, queued chunks taken back, slow chunks raced), the joins,
cancellation, and the handler/pod wiring. RunPod, R2 and Remotion are faked;
the joins run real ffmpeg.
"""
import array
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import handler  # noqa: E402
from src import config, fanout, render  # noqa: E402


def _doc(lengths, transitions=None, fps=30, sfx=None, overlays=None):
    scenes, f = [], 0
    for i, n in enumerate(lengths):
        t = (transitions or {}).get(i, "none")
        scenes.append({"id": f"s{i:03d}", "startFrame": f, "durationInFrames": n, "text": f"line {i}",
                       "transition": t, "media": {"type": "video", "url": f"https://pub.example/media/s{i}.mp4",
                                                  "thumbnail": f"https://pub.example/thumbs/s{i}.jpg"}})
        f += n
    return {"fps": fps, "width": 1920, "height": 1080, "durationInFrames": f, "scenes": scenes,
            "overlays": overlays or [], "sfx": sfx or [], "audio": {"url": "https://sb.example/narration.mp3"},
            "bgm": {"url": "bgm://suspense-v2", "volume": 0.02}, "meta": {}}


def _check_cover(test, ranges, total, min_frames=1):
    test.assertEqual(ranges[0][0], 0)
    test.assertEqual(ranges[-1][1], total - 1)
    for (a, b), (c, _d) in zip(ranges, ranges[1:]):
        test.assertEqual(c, b + 1, "a gap or an overlap between chunks")
    for a, b in ranges:
        test.assertGreaterEqual(b - a + 1, min_frames)


class Planning(unittest.TestCase):
    def test_chunks_cover_the_video_without_gaps_or_overlaps(self):
        rnd = random.Random(7)
        for seed in range(60):
            rnd.seed(seed)
            lengths = [rnd.randint(90, 280) for _ in range(rnd.randint(1, 180))]
            names = ["none", "none", "none", "crossfade", "flash", "fade", "glitch", "zoom"]
            doc = _doc(lengths, {i: rnd.choice(names) for i in range(len(lengths))})
            for n in (1, 2, 5, 12, 40):
                ranges = fanout.plan_chunks(doc, n, 60)
                _check_cover(self, ranges, doc["durationInFrames"], min(60, doc["durationInFrames"]))
                self.assertLessEqual(len(ranges), n)

    def test_cuts_never_fall_inside_a_crossfade_or_a_cut_transition(self):
        lengths = [200] * 60
        # Every third scene enters with a crossfade, every third with a flash.
        trans = {i: ("crossfade" if i % 3 == 1 else "flash" if i % 3 == 2 else "none") for i in range(60)}
        doc = _doc(lengths, trans)
        starts = {s["startFrame"]: s["transition"] for s in doc["scenes"]}
        ranges = fanout.plan_chunks(doc, 10, 300)
        self.assertEqual(len(ranges), 10)
        for a, _b in ranges[1:]:
            self.assertIn(a, starts, "a chunk starts on a scene cut")
            self.assertNotIn(starts[a], ("crossfade", "flash"), f"chunk start {a} is inside a transition")

    def test_cuts_never_fall_under_a_pack_transition(self):
        # The owner's overlay clips (and their own sound) play across their cut.
        doc = _doc([200] * 60, {i: ("pack:mlt5" if i % 2 else "none") for i in range(60)})
        clean, visual, _every = fanout.chunk_cuts(doc)
        packs = {s["startFrame"] for s in doc["scenes"] if s["transition"].startswith("pack:")}
        self.assertTrue(packs)
        self.assertFalse(packs & set(visual))
        self.assertFalse(packs & set(clean))
        for a, _b in fanout.plan_chunks(doc, 10, 300)[1:]:
            self.assertNotIn(a, packs)

    def test_cuts_avoid_a_sound_effect_or_an_overlay_entrance_across_them(self):
        lengths = [150] * 40                     # scene cuts every 150 frames
        doc = _doc(lengths, sfx=[{"name": "whoosh", "startFrame": 1490, "durationFrames": 30}],
                   overlays=[{"type": "stat", "startFrame": 2990, "durationInFrames": 120}])
        ranges = fanout.plan_chunks(doc, 4, 300)
        starts = [a for a, _ in ranges[1:]]
        self.assertNotIn(1500, starts)           # the whoosh plays across frame 1500
        self.assertNotIn(3000, starts)           # the overlay enters across frame 3000
        clean, visual, every = fanout.chunk_cuts(doc)
        self.assertNotIn(1500, clean)
        self.assertIn(1500, visual)
        self.assertIn(3000, every)

    def test_one_long_scene_still_splits_on_exact_frames(self):
        doc = _doc([9000])
        ranges = fanout.plan_chunks(doc, 3, 300)
        self.assertEqual(ranges, [(0, 2999), (3000, 5999), (6000, 8999)])

    def test_chunks_stay_about_equal(self):
        rnd = random.Random(3)
        doc = _doc([rnd.randint(150, 270) for _ in range(190)])     # ~22 minutes
        ranges = fanout.plan_chunks(doc, 12, 900)
        size = doc["durationInFrames"] / 12
        self.assertEqual(len(ranges), 12)
        for a, b in ranges:
            self.assertLess(abs((b - a + 1) - size), size * 0.75)

    def test_short_videos_get_fewer_chunks(self):
        self.assertEqual(fanout.plan_chunks(_doc([150] * 6), 12, 900), [(0, 899)])
        self.assertEqual(len(fanout.plan_chunks(_doc([150] * 30), 12, 900)), 5)
        self.assertEqual(fanout.plan_chunks({"durationInFrames": 0}, 4), [])

    def test_the_cut_transition_list_matches_the_renderer(self):
        with open(os.path.join(ROOT, "remotion", "src", "transitions", "timing.ts"), encoding="utf-8") as fh:
            ts = fh.read()
        block = ts[ts.index("export const CUT_TRANSITIONS"):]
        block = block[:block.index("};")]
        names = set(re.findall(r'^\s*"?([a-z-]+)"?\s*:\s*\{', block, re.M))
        self.assertEqual(names, set(fanout.CUT_TRANSITIONS))


class Readiness(unittest.TestCase):
    def test_off_by_default_and_every_prerequisite_is_named(self):
        with mock.patch.object(config, "POD_RENDER_FANOUT", False), \
                mock.patch.object(fanout.r2, "enabled", return_value=False), \
                mock.patch.object(config, "FANOUT_API_KEY", ""), mock.patch.object(config, "POD_RENDER_ENDPOINT_ID", ""):
            r = fanout.pod_render_ready(_doc([150] * 10))
        self.assertFalse(r["enabled"])
        text = " | ".join(r["missing"])
        for need in ("POD_RENDER_FANOUT", "API key", "endpoint", "R2"):
            self.assertIn(need, text)
        if "POD_RENDER_FANOUT" not in os.environ:
            with mock.patch.object(config, "POD_RENDER_FANOUT", config._flag("POD_RENDER_FANOUT", False)):
                self.assertFalse(config.POD_RENDER_FANOUT)                     # off until verified

    def test_on_it_splits_a_long_render_and_publishes_media_first(self):
        with _pod_env():
            self.assertTrue(fanout.pod_render_enabled(_doc([150] * 40)))
            self.assertTrue(fanout.render_enabled(_doc([150] * 40), "p1"))       # build publishes first
            with mock.patch.object(config, "POD_RENDER_MIN_SECONDS", 600):
                self.assertFalse(fanout.pod_render_enabled(_doc([150] * 40)))    # 200 s: stays whole


class _pod_env:
    """POD_RENDER_FANOUT on with fake credentials, quick polling."""

    def __init__(self, **over):
        self.over = over

    def __enter__(self):
        vals = {"POD_RENDER_FANOUT": True, "FANOUT_API_KEY": "k", "POD_RENDER_ENDPOINT_ID": "ep",
                "POD_RENDER_CHUNKS": 4, "POD_RENDER_MIN_CHUNK_FRAMES": 30, "POD_RENDER_MIN_SECONDS": 0,
                "POD_RENDER_QUEUE_GRACE_SECONDS": 600, "POD_RENDER_SPECULATE": False,
                "POD_RENDER_CHUNK_TIMEOUT_SECONDS": 1800, "POD_RENDER_TIMEOUT_SECONDS": 3600,
                "POD_RENDER_KEEP_CHUNKS": False, "POD_RENDER_PREFIX": "chunks/"}
        vals.update(self.over)
        self.patches = [mock.patch.object(config, k, v) for k, v in vals.items()]
        self.patches += [mock.patch.object(fanout.r2, "enabled", return_value=True),
                         mock.patch.object(fanout.r2, "list_keys", return_value=[]),
                         mock.patch.object(fanout, "POD_POLL_SECONDS", 0.01),
                         mock.patch.object(fanout, "POD_IDLE_SECONDS", 0.01)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        fanout._LIVE.clear()
        return False


def _frames_file(path, n):
    with open(path, "w") as fh:
        fh.write(f"FRAMES={n}\n" + "x" * 64)


def _fake_count(path):
    try:
        with open(path) as fh:
            m = re.match(r"FRAMES=(-?\d+)", fh.read())
        return int(m.group(1)) if m else -1
    except OSError:
        return -1


class FakeWorkers:
    """The serverless endpoint as the pod sees it: one behaviour per chunk index."""

    def __init__(self, modes=None):
        self.modes = modes or {}
        self.jobs, self.cancelled, self.payloads = {}, [], []
        self.lock = threading.Lock()

    def submit(self, payload):
        inp = payload["input"]
        mode = self.modes.get(inp["chunk"], "ok")
        if mode == "submit_fail":
            return "", "HTTP 500: boom"
        with self.lock:
            jid = f"job-{inp['chunk']}-{len(self.payloads)}"
            self.payloads.append(payload)
            self.jobs[jid] = {"inp": inp, "mode": mode, "polls": 0}
        return jid, ""

    def status(self, jid):
        with self.lock:
            j = self.jobs[jid]
            j["polls"] += 1
            polls = j["polls"]
        inp, mode = j["inp"], j["mode"]
        if jid in self.cancelled:
            return {"status": "CANCELLED"}
        if mode == "queued":
            return {"status": "IN_QUEUE"}
        if mode == "fail":
            return {"status": "FAILED", "error": "worker died"}
        if mode == "slow":
            return {"status": "IN_PROGRESS", "output": {"frac": 0.01}}
        if mode == "refuse":
            return {"status": "COMPLETED", "output": {"ok": False, "error": "renderer differs"}}
        if polls < 2:
            return {"status": "IN_PROGRESS", "output": {"frac": 0.5}}
        i = inp["chunk"]
        return {"status": "COMPLETED", "output": {
            "ok": True, "chunk": i, "frames": inp["frames"],
            "video_key": f"{inp['prefix']}{i:03d}-t.mp4", "video_url": f"https://pub.example/{i}.mp4",
            "audio_key": f"{inp['prefix']}{i:03d}-t.wav", "audio_url": f"https://pub.example/{i}.wav"}}

    def cancel(self, jid):
        with self.lock:
            self.cancelled.append(jid)

    def frames_for_key(self, key):
        for j in self.jobs.values():
            inp = j["inp"]
            if key.startswith(f"{inp['prefix']}{inp['chunk']:03d}-"):
                a, b = inp["frames"]
                return b - a + 1 - (1 if j["mode"] == "incomplete" else 0)
        return 0


class Spread(unittest.TestCase):
    """The pod's scheduler, end to end with fakes."""

    def _run(self, doc, workers, pod_fails=(), finalize_ok=True, **env):
        work = tempfile.mkdtemp()
        calls = {"render": [], "finalize": [], "deleted": [], "uploads": []}

        def fake_render(d, path, frames=None, audio_to=None, cancel=None, **kw):
            calls["render"].append(tuple(frames))
            if frames and frames[0] in pod_fails:
                raise render.RenderError("pod render broke")
            _frames_file(path, frames[1] - frames[0] + 1)
            with open(audio_to, "wb") as fh:
                fh.write(b"RIFF" + b"\0" * 100)
            return path

        def fake_fetch(url, path, key="", bucket="", tries=4):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if key.endswith(".mp4"):
                _frames_file(path, workers.frames_for_key(key))
            else:
                with open(path, "wb") as fh:
                    fh.write(b"RIFF" + b"\0" * 100)
            return path

        def fake_finalize(video, audio, out, **kw):
            if not finalize_ok:
                raise render.RenderError("mux failed")
            calls["finalize"].append((video, audio, out))
            with open(out, "wb") as fh:
                fh.write(b"final")
            return {}

        def fake_join_videos(paths, out, frames):
            first_lines = []
            for p in paths:
                with open(p) as fh:
                    first_lines.append(fh.read().split("\n")[0])
            calls["joined"] = first_lines
            _frames_file(out, frames)
            return out

        def fake_join_wavs(parts, fps, out):
            calls["wavs"] = [(os.path.basename(p), n) for p, n in parts]
            with open(out, "wb") as fh:
                fh.write(b"RIFF")
            return out

        def fake_upload(path, key, **kw):
            calls["uploads"].append(key)
            return f"https://pub.example/{key}"
        with _pod_env(**env), \
                mock.patch.object(fanout, "_pod_submit", side_effect=workers.submit), \
                mock.patch.object(fanout, "_pod_status", side_effect=workers.status), \
                mock.patch.object(fanout, "_pod_cancel", side_effect=workers.cancel), \
                mock.patch.object(fanout, "_fetch", side_effect=fake_fetch), \
                mock.patch.object(fanout, "_count_frames", side_effect=_fake_count), \
                mock.patch.object(fanout, "join_videos", side_effect=fake_join_videos), \
                mock.patch.object(fanout, "join_wavs", side_effect=fake_join_wavs), \
                mock.patch.object(fanout, "_delete_keys", side_effect=lambda keys: calls["deleted"].extend(keys)), \
                mock.patch.object(fanout.r2, "upload", side_effect=fake_upload), \
                mock.patch.object(fanout.r2, "upload_bytes",
                                  side_effect=lambda data, key, **kw: calls["uploads"].append(key) or f"https://pub.example/{key}"), \
                mock.patch.object(fanout.renderer, "render", side_effect=fake_render), \
                mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp1"), \
                mock.patch.object(fanout.renderer, "finalize", side_effect=fake_finalize):
            ok = fanout.render_pod(doc, os.path.join(work, "final.mp4"), job_id="pod-abc", work=work,
                                   report=lambda *a, **k: None, concurrency=8)
            for _ in range(100):                     # the R2 clean-up runs in the background
                if calls["deleted"] or not ok:
                    break
                time.sleep(0.01)
        calls["stats"] = dict(fanout.media.LAST_STATS.get("pod_render") or {})
        return ok, calls, work

    def test_workers_render_their_chunks_and_the_pod_joins_them(self):
        doc = _doc([150] * 16)                                   # 2400 frames -> 4 chunks
        workers = FakeWorkers()
        ok, calls, work = self._run(doc, workers)
        self.assertTrue(ok)
        self.assertEqual(calls["render"], [(0, 599)])            # the pod's own first chunk
        self.assertEqual(len(workers.payloads), 3)
        inp = workers.payloads[0]["input"]
        self.assertEqual(inp["action"], "render_chunk")
        self.assertEqual(inp["upload"], "r2")
        self.assertEqual(inp["renderer"], "fp1")
        self.assertTrue(inp["prefix"].startswith("chunks/pod-abc-") and inp["prefix"].endswith("/"))
        self.assertTrue(fanout._prefix_ok(inp["prefix"]))
        self.assertEqual(inp["crf"], config.RENDER_CRF)
        self.assertIn("policy", workers.payloads[0])
        self.assertEqual(calls["joined"], ["FRAMES=600"] * 4)     # in order, all complete
        self.assertEqual([n for _p, n in calls["wavs"]], [600] * 4)
        self.assertEqual(len(calls["finalize"]), 1)
        self.assertEqual(calls["stats"]["onWorkers"], 3)
        self.assertEqual(calls["stats"]["onPod"], 1)
        # The timeline, and every chunk file, is cleaned out of R2 afterwards.
        self.assertTrue(any(k.endswith("timeline.json") for k in calls["deleted"]))
        self.assertEqual(sum(1 for k in calls["deleted"] if k.endswith((".mp4", ".wav"))), 6)
        self.assertFalse(fanout._LIVE)

    def test_a_failed_or_refusing_worker_chunk_is_rendered_on_the_pod(self):
        doc = _doc([150] * 16)
        workers = FakeWorkers({1: "fail", 3: "refuse"})
        ok, calls, _ = self._run(doc, workers)
        self.assertTrue(ok)
        self.assertEqual(sorted(calls["render"]), [(0, 599), (600, 1199), (1800, 2399)])
        self.assertEqual(calls["stats"]["onPod"], 3)
        self.assertEqual(calls["stats"]["workerFailed"], 2)

    def test_an_incomplete_worker_chunk_is_rendered_again_on_the_pod(self):
        doc = _doc([150] * 16)
        workers = FakeWorkers({2: "incomplete"})
        ok, calls, _ = self._run(doc, workers)
        self.assertTrue(ok)
        self.assertIn((1200, 1799), calls["render"])
        self.assertEqual(calls["joined"], ["FRAMES=600"] * 4)

    def test_a_chunk_no_worker_picks_up_is_taken_back(self):
        doc = _doc([150] * 16)
        workers = FakeWorkers({2: "queued"})
        ok, calls, _ = self._run(doc, workers, POD_RENDER_QUEUE_GRACE_SECONDS=0)
        self.assertTrue(ok)
        self.assertIn((1200, 1799), calls["render"])
        self.assertEqual(len(workers.cancelled), 1)              # its queued job was cancelled
        self.assertEqual(calls["stats"]["takenBack"], 1)

    def test_a_chunk_that_could_not_be_queued_is_rendered_on_the_pod(self):
        doc = _doc([150] * 16)
        workers = FakeWorkers({1: "submit_fail"})
        ok, calls, _ = self._run(doc, workers)
        self.assertTrue(ok)
        self.assertIn((600, 1199), calls["render"])
        self.assertEqual(calls["stats"]["submitFailed"], 1)

    def test_the_pod_races_a_slow_worker_and_cancels_it(self):
        doc = _doc([150] * 16)
        workers = FakeWorkers({1: "slow"})
        ok, calls, _ = self._run(doc, workers, POD_RENDER_SPECULATE=True)
        self.assertTrue(ok)
        self.assertIn((600, 1199), calls["render"])
        self.assertEqual(calls["stats"]["raced"], 1)
        self.assertTrue(any(j.startswith("job-1-") for j in workers.cancelled))

    def test_a_chunk_nobody_can_render_gives_up_the_spread_render(self):
        doc = _doc([150] * 16)
        workers = FakeWorkers({1: "fail"})
        ok, calls, _ = self._run(doc, workers, pod_fails=(600,))
        self.assertFalse(ok)                                     # the caller renders the whole video
        self.assertFalse(calls["finalize"])
        self.assertFalse(fanout._LIVE)

    def test_a_failed_join_gives_up_the_spread_render(self):
        ok, calls, _ = self._run(_doc([150] * 16), FakeWorkers(), finalize_ok=False)
        self.assertFalse(ok)

    def test_nothing_is_queued_when_the_timeline_cannot_go_up(self):
        workers = FakeWorkers()
        with _pod_env(), mock.patch.object(fanout.r2, "upload_bytes", side_effect=RuntimeError("R2 down")), \
                mock.patch.object(fanout, "_pod_submit", side_effect=workers.submit) as sub, \
                mock.patch.object(fanout, "_delete_keys"):
            ok = fanout.render_pod(_doc([150] * 16), os.path.join(tempfile.mkdtemp(), "f.mp4"), job_id="pod-x",
                                   work=tempfile.mkdtemp(), report=lambda *a, **k: None)
        self.assertFalse(ok)
        sub.assert_not_called()

    def test_off_means_the_pod_renders_alone(self):
        with mock.patch.object(config, "POD_RENDER_FANOUT", False):
            self.assertFalse(fanout.render_pod(_doc([150] * 16), "x.mp4", job_id="j", work=tempfile.mkdtemp(),
                                               report=lambda *a, **k: None))


class Cancel(unittest.TestCase):
    def test_live_chunk_jobs_are_cancelled_when_the_pod_job_ends(self):
        fanout._LIVE.clear()
        with mock.patch.object(config, "POD_RENDER_ENDPOINT_ID", "ep"), \
                mock.patch.object(config, "FANOUT_API_KEY", "k"):
            fanout._register("j1")
            fanout._register("j2")
            with mock.patch.object(fanout.requests, "post") as post:
                self.assertEqual(fanout.cancel_live_jobs(), 2)
        urls = sorted(c.args[0] for c in post.call_args_list)
        self.assertEqual(urls, ["https://api.runpod.ai/v2/ep/cancel/j1", "https://api.runpod.ai/v2/ep/cancel/j2"])
        self.assertFalse(fanout._LIVE)

    def test_clean_up_takes_the_whole_prefix_even_files_the_pod_never_heard_of(self):
        listed = [{"key": "chunks/pod-a-1/004-late.mp4"}, {"key": "chunks/pod-a-1/004-late.wav"},
                  {"key": "chunks/pod-a-10/other.mp4"}]
        with mock.patch.object(fanout.r2, "list_keys", return_value=listed), \
                mock.patch.object(fanout.r2, "delete") as delete:
            fanout._delete_prefix("chunks/pod-a-1/", ["chunks/pod-a-1/timeline.json"])
        gone = sorted(c.args[0] for c in delete.call_args_list)
        self.assertEqual(gone, ["chunks/pod-a-1/004-late.mp4", "chunks/pod-a-1/004-late.wav",
                                "chunks/pod-a-1/timeline.json"])

    def test_pod_job_cancels_chunks_after_the_handler(self):
        import pod_job
        with mock.patch.object(pod_job, "load_job", return_value={"id": "pod-x", "input": {}}), \
                mock.patch.object(pod_job.handler, "handler", return_value={"ok": True, "video_url": "u"}), \
                mock.patch.object(fanout, "cancel_live_jobs", return_value=0) as cancel, \
                mock.patch.object(pod_job, "save_adhoc_result", return_value="", create=True), \
                mock.patch.object(pod_job, "stop_this_pod"), \
                mock.patch.dict(os.environ, {"POD_MAX_SECONDS": "0", "POD_FETCH_TOKEN": ""}, clear=False):
            pod_job.main()
        cancel.assert_called()

    def test_a_render_can_be_cancelled(self):
        d = tempfile.mkdtemp()
        ev = threading.Event()
        threading.Timer(0.3, ev.set).start()
        started = time.time()
        with mock.patch.object(config, "REMOTION_DIR", d):
            p = render._run_streaming([sys.executable, "-c", "import time; time.sleep(30)"], 60, None, ev)
        self.assertLess(time.time() - started, 10)
        self.assertNotEqual(p.returncode, 0)


class WorkerSide(unittest.TestCase):
    def _inp(self, **kw):
        inp = {"action": "render_chunk", "upload": "r2", "chunk": 2, "frames": [600, 899],
               "prefix": "chunks/pod-abc-1234567890/", "renderer": "fp1", "timeline_key": "chunks/pod-abc/timeline.json",
               "timeline_url": "https://pub.example/timeline.json", "crf": 23, "x264": "faster",
               "deadline_at": time.time() + 600}
        inp.update(kw)
        return inp

    def _run(self, inp, frames=300):
        work = tempfile.mkdtemp()
        seen = {"uploads": []}

        def fake_render(doc, path, frames=None, audio_to=None, **kw):
            seen["frames"] = frames
            seen["settings"] = (config.RENDER_CRF, config.RENDER_X264_PRESET)
            seen["doc"] = doc
            _frames_file(path, frames_n[0])
            with open(audio_to, "wb") as fh:
                fh.write(b"RIFF")
            return path
        frames_n = [frames]
        doc = _doc([300] * 4)
        with mock.patch.object(fanout.r2, "enabled", return_value=True), \
                mock.patch.object(config, "POD_RENDER_PREFIX", "chunks/"), \
                mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp1"), \
                mock.patch.object(fanout, "_load_timeline", return_value=doc), \
                mock.patch.object(fanout, "_localize", return_value={"files": 3}), \
                mock.patch.object(fanout, "_count_frames", side_effect=_fake_count), \
                mock.patch.object(fanout.renderer, "render", side_effect=fake_render), \
                mock.patch.object(fanout.r2, "upload",
                                  side_effect=lambda p, k, **kw: seen["uploads"].append(k) or f"https://pub/{k}"):
            before = (config.RENDER_CRF, config.RENDER_X264_PRESET)
            out = fanout.run_pod_chunk(inp, work)
            after = (config.RENDER_CRF, config.RENDER_X264_PRESET)
        return out, seen, before, after

    def test_a_chunk_renders_picture_and_sound_and_puts_both_in_r2(self):
        out, seen, before, after = self._run(self._inp())
        self.assertTrue(out["ok"], out)
        self.assertEqual(seen["frames"], (600, 899))
        self.assertEqual(seen["settings"], (23, "faster"))       # the pod's encoder settings
        self.assertEqual(before, after)                          # and the worker's own restored
        self.assertEqual(len(seen["uploads"]), 2)
        self.assertTrue(all(k.startswith("chunks/pod-abc-1234567890/002-") for k in seen["uploads"]))
        self.assertTrue(out["video_key"].endswith(".mp4") and out["audio_key"].endswith(".wav"))

    def test_refusals(self):
        self.assertIn("renderer", self._run(self._inp(renderer="other"))[0]["error"])
        self.assertIn("deadline", self._run(self._inp(deadline_at=time.time() - 1))[0]["error"])
        for bad in ("../x/", "chunks/", "videos/pod/", "chunks/a/b/", "chunks/a b/"):
            self.assertEqual(self._run(self._inp(prefix=bad))[0]["error"], "bad chunk prefix", bad)
        out = self._run(self._inp(), frames=299)[0]
        self.assertFalse(out["ok"])
        self.assertIn("299", out["error"])

    def test_the_handler_routes_pod_chunks_and_leaves_the_project_alone(self):
        with mock.patch.object(handler.fanout, "run_pod_chunk", return_value={"ok": True, "chunk": 1}) as run, \
                mock.patch.object(handler.storage, "patch_project") as patch:
            out = handler.handler({"id": "rp-1", "input": self._inp()})
        run.assert_called_once()
        patch.assert_not_called()
        self.assertTrue(out["ok"])
        self.assertEqual(out["action"], "render_chunk")


class Localize(unittest.TestCase):
    def test_only_what_the_range_draws_is_fetched_and_links_are_rewritten(self):
        doc = _doc([300] * 20)
        doc["overlays"] = [{"type": "photo-card", "startFrame": 650, "durationInFrames": 90,
                            "media": [{"type": "image", "url": "https://pub.example/photo.jpg"}]},
                           {"type": "photo-card", "startFrame": 5000, "durationInFrames": 90,
                            "media": [{"type": "image", "url": "https://pub.example/far.jpg"}]}]
        fetched = []

        def fake_fetch(url, path, key="", bucket="", tries=4):
            fetched.append(url)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"x")
            if "s5.mp4" in url:
                raise RuntimeError("404")
            return path
        work = tempfile.mkdtemp()
        with mock.patch.object(fanout, "_fetch", side_effect=fake_fetch):
            stats = fanout._localize(doc, 600, 1199, work)
        urls = set(fetched)
        self.assertIn("https://pub.example/media/s2.mp4", urls)          # on screen
        self.assertIn("https://pub.example/media/s3.mp4", urls)
        self.assertNotIn("https://pub.example/media/s9.mp4", urls)       # far away
        self.assertIn("https://pub.example/thumbs/s8.jpg", urls)         # a neighbour's still
        self.assertIn("https://pub.example/photo.jpg", urls)
        self.assertNotIn("https://pub.example/far.jpg", urls)
        self.assertIn("https://sb.example/narration.mp3", urls)
        self.assertTrue(os.path.isfile(doc["scenes"][2]["media"]["url"]))
        self.assertEqual(doc["scenes"][9]["media"]["url"], "https://pub.example/media/s9.mp4")
        self.assertEqual(doc["bgm"]["url"], "bgm://suspense-v2")
        self.assertGreaterEqual(stats["files"], 5)
        # A second chunk on the same machine reuses what is already here.
        again = []
        with mock.patch.object(fanout, "_fetch", side_effect=lambda u, p, **k: again.append(u) or p):
            fanout._localize(_doc([300] * 20), 600, 1199, work)
        self.assertNotIn("https://pub.example/media/s2.mp4", again)

    def test_the_pods_local_files_go_up_and_links_stay(self):
        d = tempfile.mkdtemp()
        still = os.path.join(d, "still_3.jpg")
        with open(still, "wb") as fh:
            fh.write(b"jpg")
        doc = _doc([300] * 5)
        doc["scenes"][3]["media"] = {"type": "image", "url": still}
        uploads = []
        with mock.patch.object(fanout.r2, "upload",
                               side_effect=lambda p, k, **kw: uploads.append((p, k)) or f"https://pub.example/{k}"):
            remote, keys = fanout._publish_files(doc, "chunks/j-1/", time.time() + 60)
        self.assertEqual([p for p, _k in uploads], [still])
        self.assertTrue(remote["scenes"][3]["media"]["url"].startswith("https://pub.example/chunks/j-1/assets/"))
        self.assertEqual(doc["scenes"][3]["media"]["url"], still)        # the pod's own copy untouched
        self.assertEqual(remote["scenes"][0]["media"]["url"], "https://pub.example/media/s0.mp4")
        self.assertEqual(remote["bgm"]["url"], "bgm://suspense-v2")
        self.assertEqual(len(keys), 1)

    def test_our_r2_links_map_to_bucket_keys(self):
        with mock.patch.object(config, "R2_PUBLIC_BASE", "https://pub-v.r2.dev"), \
                mock.patch.object(config, "R2_BUCKET", "videos"):
            self.assertEqual(fanout._r2_location("https://pub-v.r2.dev/projects/p/media/a%20b.mp4?x=1"),
                             ("videos", "projects/p/media/a b.mp4"))
            self.assertIsNone(fanout._r2_location("https://elsewhere.example/a.mp4"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class Joins(unittest.TestCase):
    def test_sound_slices_join_sample_exactly(self):
        d = tempfile.mkdtemp()
        parts = []
        # Three slices of 30, 45 and 30 frames; the renderer made them a few
        # samples short or long. A beep starts exactly on the second slice's frame 15.
        for k, (frames, err) in enumerate(((30, -100), (45, 57), (30, 0))):
            n = frames * 1600 + err
            beep = "if(between(t,0.5,0.55),0.9*sin(2*PI*1000*t),0)" if k == 1 else "0"
            path = os.path.join(d, f"s{k}.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"aevalsrc='{beep}':s=48000:d={n / 48000:.6f}", "-ac", "2", "-c:a", "pcm_s16le", path],
                           check=True)
            parts.append((path, frames))
        out = fanout.join_wavs(parts, 30, os.path.join(d, "all.wav"))
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-ac", "1", "-f", "s16le", "-"], capture_output=True)
        pcm = array.array("h")
        pcm.frombytes(p.stdout)
        self.assertEqual(len(pcm), 105 * 1600)                           # exactly 105 frames long
        first = next(i for i, v in enumerate(pcm) if abs(v) > 3000)
        self.assertAlmostEqual(first, (30 + 15) * 1600, delta=48)        # the beep did not move

    def test_pictures_join_without_reencoding_and_keep_every_frame(self):
        d = tempfile.mkdtemp()
        paths = []
        for k, frames in enumerate((30, 45, 30)):
            path = os.path.join(d, f"c{k}.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=s=320x180:r=30:d={frames / 30:.4f}", "-frames:v", str(frames),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", path],
                           check=True)
            paths.append(path)
        out = fanout.join_videos(paths, os.path.join(d, "all.mp4"), 105)
        self.assertEqual(fanout._count_frames(out), 105)
        # Decodes cleanly across both joins.
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "null", "-"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stderr.strip(), "")
        with self.assertRaises(RuntimeError):
            fanout.join_videos(paths, os.path.join(d, "bad.mp4"), 106)


class DoRenderSpread(unittest.TestCase):
    def _doc(self):
        d = _doc([150] * 16)
        d["meta"] = {"sceneCount": 16}
        return d

    def _run(self, spread_result):
        work = tempfile.mkdtemp()
        calls = {}

        def fake_spread(doc, out, **kw):
            calls["spread"] = kw
            if spread_result:
                with open(out, "wb") as fh:
                    fh.write(b"final")
            return spread_result

        def fake_render(doc, path, **kw):
            calls["render"] = path
            with open(path, "wb") as fh:
                fh.write(b"v")
            if kw.get("audio_to"):
                with open(kw["audio_to"], "wb") as fh:
                    fh.write(b"RIFF")
            return path

        def fake_finalize(video, audio, out, **kw):
            calls["finalize"] = out
            with open(out, "wb") as fh:
                fh.write(b"final")
            return {}
        with mock.patch.object(handler.fanout, "pod_render_enabled", return_value=True), \
                mock.patch.object(handler.fanout, "render_pod", side_effect=fake_spread), \
                mock.patch.object(handler.fanout, "render") as old_split, \
                mock.patch.object(handler.timeline, "drop_invalid_overlays"), \
                mock.patch.object(handler.timeline, "validate"), \
                mock.patch.object(handler, "_preflight_media", return_value=0), \
                mock.patch.object(handler, "_sanitize_stills"), \
                mock.patch.object(handler, "_sign_supabase_urls"), \
                mock.patch.object(handler.renderer, "render", side_effect=fake_render), \
                mock.patch.object(handler.renderer, "finalize", side_effect=fake_finalize), \
                mock.patch.object(handler.renderer, "normalize_loudness") as loud, \
                mock.patch.object(handler.r2, "enabled", return_value=True), \
                mock.patch.object(handler, "_keep_render"):
            out = handler.do_render(self._doc(), {"return_video": True, "_job_id": "pod-1"}, work,
                                    lambda *a, **k: None, split=True)
        return calls, out, old_split, loud

    def test_a_spread_render_is_used_when_on(self):
        calls, out, old_split, loud = self._run(True)
        self.assertEqual(calls["spread"]["job_id"], "pod-1")
        self.assertNotIn("render", calls)
        old_split.assert_not_called()
        loud.assert_not_called()
        self.assertEqual(out["uploadedVia"], "inline")

    def test_when_it_cannot_run_the_pod_renders_the_whole_video(self):
        calls, _out, old_split, _loud = self._run(False)
        self.assertIn("render", calls)                       # the single-machine render
        self.assertIn("finalize", calls)
        old_split.assert_not_called()                        # never the old serverless split


if __name__ == "__main__":
    unittest.main()
