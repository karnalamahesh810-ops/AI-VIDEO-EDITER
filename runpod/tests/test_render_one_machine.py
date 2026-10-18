"""
A long video never renders whole on one worker by accident.

2026-10-03, the Yellowstone video (29 minutes, 201 scenes, ~52,000 frames): the
quality check repaired six scenes before the render; one repair left a local
file in the document, the chunk render refused any document with a local file,
and the whole video rendered on one 16-vCPU serverless worker until its flat
5400 s limit killed it at 55%.

Now: the spread render (fanout.render_pod) runs from a serverless parent too,
publishes whatever is local first, cuts one chunk a machine, stops with a
plain reason when storage says files the video draws are gone (instead of
handing hours of work to one machine), still falls back to the whole video
when the machines fail (a chunk that failed everywhere, no worker free), and
the whole-video render that remains as the last resort says it is on one
machine and is refused when it could not finish in time. RunPod, R2, storage
and Remotion are faked.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, events, fanout, gapfill, quality, render  # noqa: E402
from tests.test_render_chunks import FakeWorkers, _doc, _fake_count, _frames_file, _pod_env  # noqa: E402


def _file(folder, name, data=b"x" * 64):
    path = os.path.join(folder, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.headers = {"Content-Range": "bytes 0-4095/5000000", "Content-Type": "video/mp4"}
        self.content = b""

    def iter_content(self, n):
        yield b"\x00\x00\x00\x18ftypisom" + bytes(200)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _spread(doc, workers, pod_fails=(), fetch=None, **env):
    """fanout.render_pod end to end with fakes (as tests/test_render_chunks.Spread._run); returns (ok, calls)."""
    work = tempfile.mkdtemp()
    calls = {"render": [], "uploads": {}, "deleted": [], "timeline": None, "concurrency": set(), "localize": []}

    def fake_render(d, path, frames=None, audio_to=None, cancel=None, concurrency=None, **kw):
        calls["render"].append(tuple(frames))
        calls["concurrency"].add(concurrency)
        if frames[0] in pod_fails:
            raise render.RenderError("remotion render failed (exit 1): the compositor crashed")
        _frames_file(path, frames[1] - frames[0] + 1)
        with open(audio_to, "wb") as fh:
            fh.write(b"RIFF" + b"\0" * 100)
        return path

    def fake_fetch(url, path, key="", bucket="", tries=4):
        if fetch is not None:
            fetch(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if key.endswith(".mp4"):
            _frames_file(path, workers.frames_for_key(key))
        else:
            with open(path, "wb") as fh:
                fh.write(b"RIFF" + b"\0" * 100)
        return path

    def fake_join_videos(paths, out, frames):
        _frames_file(out, frames)
        return out

    def fake_join_wavs(parts, fps, out):
        with open(out, "wb") as fh:
            fh.write(b"RIFF")
        return out

    def fake_finalize(video, audio, out, **kw):
        with open(out, "wb") as fh:
            fh.write(b"final")
        return {}

    def fake_upload(path, key, **kw):
        calls["uploads"][key] = path
        return f"https://pub.example/{key}"

    def fake_upload_bytes(data, key, **kw):
        if key.endswith("timeline.json"):
            calls["timeline"] = json.loads(data.decode("utf-8"))
        calls["uploads"][key] = None
        return f"https://pub.example/{key}"
    out = {}
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
            mock.patch.object(fanout.r2, "upload_bytes", side_effect=fake_upload_bytes), \
            mock.patch.object(fanout.renderer, "render", side_effect=fake_render), \
            mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp1"), \
            mock.patch.object(fanout.renderer, "finalize", side_effect=fake_finalize):
        try:
            out["ok"] = fanout.render_pod(doc, os.path.join(work, "final.mp4"), job_id="rp-serverless-e1", work=work,
                                          report=lambda *a, **k: calls.setdefault("report", []).append(a),
                                          concurrency=12)
        except Exception as e:  # noqa: BLE001 - the test looks at it
            out["error"] = e
        fanout.finish_cleanup(5)
    calls["stats"] = dict(fanout.media.LAST_STATS.get("pod_render") or {})
    return out, calls


def _serverless(endpoint="ep"):
    """This machine is one of endpoint "ep"'s own workers (RunPod sets RUNPOD_ENDPOINT_ID there)."""
    env = {"RUNPOD_ENDPOINT_ID": endpoint}
    return mock.patch.dict(os.environ, env, clear=False)


class ServerlessParent(unittest.TestCase):
    def setUp(self):
        for name in ("JOB_URL", "JOB_B64"):
            patcher = mock.patch.dict(os.environ, {}, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)
            os.environ.pop(name, None)

    def test_a_serverless_parent_is_told_apart_from_a_pod(self):
        with mock.patch.object(config, "POD_RENDER_ENDPOINT_ID", "ep"):
            with _serverless("ep"):
                self.assertTrue(fanout.parent_is_worker())
            with _serverless("another-endpoint"):
                self.assertFalse(fanout.parent_is_worker())
            with _serverless("ep"), mock.patch.dict(os.environ, {"JOB_URL": "https://sb/job.json"}):
                self.assertFalse(fanout.parent_is_worker())      # a pod (scripts/pod_job.py)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RUNPOD_ENDPOINT_ID", None)
                self.assertFalse(fanout.parent_is_worker())

    def test_one_chunk_a_machine_when_the_parent_holds_one_of_the_workers(self):
        with mock.patch.object(config, "POD_RENDER_ENDPOINT_ID", "ep"), \
                mock.patch.object(config, "POD_RENDER_CHUNKS", 12), mock.patch.object(config, "FANOUT_PARTS", 10):
            with _serverless("ep"):
                self.assertEqual(fanout.spread_chunks(), 10)     # 9 workers + the parent's own machine
            with _serverless("ep"), mock.patch.dict(os.environ, {"JOB_B64": "e30="}):
                self.assertEqual(fanout.spread_chunks(), 12)     # a pod is extra to the endpoint's workers

    def test_a_very_long_video_gets_more_chunks_so_none_outruns_a_workers_time(self):
        with mock.patch.multiple(config, POD_RENDER_ENDPOINT_ID="ep", POD_RENDER_CHUNKS=12, FANOUT_PARTS=10,
                                 POD_RENDER_CHUNK_TIMEOUT_SECONDS=1800, RENDER_CPUS=16, RENDER_FPS_PER_TAB=0.45), \
                _serverless("ep"):
            self.assertEqual(fanout.spread_chunks(52000, 12), 10)        # 29 minutes: one chunk a machine
            n = fanout.spread_chunks(108000, 12)                         # an hour
            self.assertGreater(n, 10)
            # No chunk is expected to take a worker more than 60% of the time it is given.
            self.assertLessEqual(render.estimate_seconds(108000 / n, 12), 0.6 * 1800 + 1)
            self.assertEqual(fanout.spread_chunks(0, 12), 10)

    def test_the_yellowstone_render_is_spread_with_its_repaired_local_files_published(self):
        d = tempfile.mkdtemp()
        doc = _doc([260] * 200)                                  # ~29 minutes, 52,000 frames
        repaired = _file(d, "gap_0042.jpg")                      # a picture the quality check just downloaded
        still = _file(d, "still_s077.jpg")                       # a frame it cut from a clip for the looks
        narration = _file(d, "narration.polished.flac")          # voicepolish.for_render
        photo = _file(d, "overlay photo.jpg")
        logo = _file(d, "logo.png")
        doc["scenes"][42]["media"] = {"type": "image", "url": repaired, "source": "web_image"}
        doc["scenes"][77]["media"]["thumbnail"] = still
        doc["audio"]["url"] = narration
        doc["overlays"] = [{"type": "photo-card", "startFrame": 900, "durationInFrames": 90,
                            "media": [{"type": "image", "url": "file:///" + photo.replace("\\", "/").lstrip("/")}]}]
        doc["brand"] = {"watermark": {"url": logo}}
        # Not drawn: an editor's other choice keeps its local path on this machine.
        doc["scenes"][3]["semanticMetadata"] = {"alternatives": [{"localPath": repaired, "url": repaired}]}
        workers = FakeWorkers()
        with _serverless("ep"), mock.patch.object(config, "FANOUT_PARTS", 10):
            out, calls = _spread(doc, workers, POD_RENDER_CHUNKS=12, POD_RENDER_MIN_CHUNK_FRAMES=900,
                                 POD_RENDER_CHUNK_SECONDS=90)
        self.assertTrue(out.get("ok"), out)
        # Chunks follow the timeline, ~90 s each (src/rendercache.py stable_chunks: the same cut on every
        # render, so a re-render reuses what did not change): the parent draws the first, the workers the rest.
        with _pod_env(POD_RENDER_CHUNK_SECONDS=90, POD_RENDER_MIN_CHUNK_FRAMES=900):
            from src import rendercache
            ranges = rendercache.stable_chunks(doc, rendercache.chunk_frames(doc), 900)
        self.assertTrue(18 <= len(ranges) <= 21, len(ranges))    # 52,000 frames in ~2,700-frame chunks
        self.assertEqual(len(workers.payloads), len(ranges) - 1)
        self.assertEqual(len(calls["render"]), 1)
        self.assertEqual(calls["render"][0][0], 0)
        self.assertEqual(calls["concurrency"], {12})             # at the job's own concurrency
        self.assertEqual(calls["stats"]["onWorkers"], len(ranges) - 1)
        self.assertEqual(calls["stats"]["onPod"], 1)
        # Every local file went up under the job's chunk folder, and the workers' document has links only.
        assets = {os.path.basename(p or "") for k, p in calls["uploads"].items() if "/assets/" in k}
        self.assertEqual(assets, {"gap_0042.jpg", "still_s077.jpg", "narration.polished.flac", "overlay photo.jpg",
                                  "logo.png"})
        tl = calls["timeline"]
        self.assertEqual(fanout.local_refs(tl), [])
        for value in (tl["scenes"][42]["media"]["url"], tl["scenes"][77]["media"]["thumbnail"], tl["audio"]["url"],
                      tl["overlays"][0]["media"][0]["url"], tl["brand"]["watermark"]["url"]):
            self.assertTrue(value.startswith("https://pub.example/chunks/rp-serverless-e1-"), value)
        self.assertEqual(doc["scenes"][42]["media"]["url"], repaired)       # this machine keeps its own files
        self.assertEqual(tl["scenes"][3]["semanticMetadata"]["alternatives"][0]["url"], repaired)
        # The job's chunk folder is emptied afterwards (assets, timeline, chunks).
        self.assertTrue(any(k.endswith("timeline.json") for k in calls["deleted"]))
        self.assertEqual(sum(1 for k in calls["deleted"] if "/assets/" in k), 5)
        self.assertEqual(fanout.finish_cleanup(1), 0)
        self.assertFalse(fanout._LIVE)
        self.assertTrue(any("on 10 machines" in a[0] for a in calls["report"]))

    def test_failed_chunks_are_drawn_again_alone_never_the_whole_video(self):
        # Two worker chunks fail and the parent's own first chunk fails: each is
        # drawn again on another machine; the chunks that finished are kept.
        doc = _doc([150] * 16)
        workers = FakeWorkers({1: "fail", 2: "fail"})
        with _serverless("ep"):
            out, calls = _spread(doc, workers, pod_fails=(0,))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(calls["stats"]["handedOver"], 1)        # the parent's chunk went to a worker
        self.assertEqual(calls["stats"]["onPod"], 2)             # the workers' two were drawn here
        self.assertEqual(calls["stats"]["onWorkers"], 2)
        self.assertEqual(sorted(calls["render"]), [(0, 599), (600, 1199), (1200, 1799)])


class StopsWithTheReason(unittest.TestCase):
    def test_files_gone_from_storage_stop_the_spread_at_once_with_their_names(self):
        doc = _doc([150] * 16)

        class Workers(FakeWorkers):
            def status(self, jid):
                j = self.jobs[jid]
                if j["inp"]["chunk"] == 2 and jid not in self.cancelled:
                    return {"status": "COMPLETED", "output": {
                        "ok": False, "chunk": 2, "missing": ["https://pub.example/media/s8.mp4"],
                        "error": "1 file this part of the video draws is not in storage (HTTP 404): "
                                 "pub.example/.../s8.mp4"}}
                return super().status(jid)
        workers = Workers({1: "slow", 3: "slow"})
        out, calls = _spread(doc, workers)
        err = out.get("error")
        self.assertIsInstance(err, fanout.SpreadFailed)
        self.assertEqual(err.missing, ["https://pub.example/media/s8.mp4"])
        text = str(err)
        self.assertIn("1 file it needs is not in storage any more", text)
        self.assertIn("deleted from storage?", text)
        self.assertIn("pub.example/.../s8.mp4", text)
        self.assertGreaterEqual(len(workers.cancelled), 2)       # the other machines are not left drawing
        self.assertFalse(fanout._LIVE)
        self.assertTrue(any(k.endswith("timeline.json") for k in calls["deleted"]))

    def test_the_parents_own_chunk_with_files_gone_is_not_drawn(self):
        doc = _doc([150] * 16)

        def fetch(url):
            if url.endswith("/media/s1.mp4"):
                raise fanout.Gone("download failed (HTTP 404): " + url, 404)
        workers = FakeWorkers({1: "slow", 2: "slow", 3: "slow"})
        out, calls = _spread(doc, workers, fetch=fetch)
        self.assertIsInstance(out.get("error"), fanout.SpreadFailed)
        self.assertEqual(out["error"].missing, ["https://pub.example/media/s1.mp4"])
        self.assertEqual(calls["render"], [])                    # no frame drawn for a chunk that cannot finish

    def _long(self):
        """The Yellowstone size (~29 minutes, 52,000 frames) and its chunk ranges in _spread's settings."""
        doc = _doc([260] * 200)
        with _pod_env():
            from src import rendercache
            ranges = rendercache.stable_chunks(doc, rendercache.chunk_frames(doc), config.POD_RENDER_MIN_CHUNK_FRAMES)
        return doc, ranges

    def test_a_chunk_that_failed_on_every_machine_still_falls_back_to_the_whole_video(self):
        # A chunk that failed on its worker and again here is a break of the
        # machines (a crash, a full disk), not proof the video cannot be drawn:
        # however long the video, render_pod returns False and the caller
        # renders the whole video with its scaled limit, as before. Only
        # storage's own "no" may end the render with SpreadFailed.
        doc, ranges = self._long()
        a, b = ranges[1]
        out, calls = _spread(doc, FakeWorkers({1: "fail"}), pod_fails=(a,))
        self.assertNotIn("error", out)                           # never SpreadFailed for a machine failure
        self.assertIs(out.get("ok"), False)
        self.assertIn(f"chunk 1 (frames {a}-{b}) could not be rendered", calls["stats"]["error"])
        self.assertIn("the compositor crashed", calls["stats"]["error"])    # the chunk's own error
        self.assertFalse(fanout._LIVE)

    def test_the_parents_chunk_no_worker_takes_still_falls_back_to_the_whole_video(self):
        # The parent's own chunk fails and no worker can be given it (the
        # endpoint refuses the job): a break of the machines - the whole video
        # renders on this machine, however long, never SpreadFailed.
        doc, _ranges = self._long()
        out, calls = _spread(doc, FakeWorkers({0: "submit_fail"}), pod_fails=(0,))
        self.assertNotIn("error", out)
        self.assertIs(out.get("ok"), False)
        self.assertIn("no worker took it", calls["stats"]["error"])
        self.assertFalse(fanout._LIVE)

    def test_a_long_video_whose_files_are_gone_still_stops_at_once(self):
        # The one fail-fast: storage said no for a file a chunk draws.
        doc, _ranges = self._long()

        def fetch(url):
            if url.endswith("/media/s1.mp4"):
                raise fanout.Gone("download failed (HTTP 404): " + url, 404)
        out, calls = _spread(doc, FakeWorkers({i: "slow" for i in range(1, 40)}), fetch=fetch)
        self.assertIsInstance(out.get("error"), fanout.SpreadFailed)
        self.assertEqual(out["error"].missing, ["https://pub.example/media/s1.mp4"])
        self.assertEqual(calls["render"], [])

    def test_a_break_of_the_machines_not_the_video_still_falls_back(self):
        # The timeline cannot go up, a join fails: nothing says the video cannot be drawn.
        with _pod_env(), \
                mock.patch.object(fanout.r2, "upload_bytes", side_effect=RuntimeError("R2 down")), \
                mock.patch.object(fanout, "_delete_keys"):
            ok = fanout.render_pod(_doc([150] * 16), os.path.join(tempfile.mkdtemp(), "f.mp4"), job_id="j",
                                   work=tempfile.mkdtemp(), report=lambda *a, **k: None)
        self.assertIs(ok, False)

    def test_a_worker_error_never_carries_a_web_page(self):
        page = ("remotion render failed (exit 1): Received a status code of 429 while downloading file "
                "https://pub.example/media/s9.mp4.\nThe response body was:\n---\n<!DOCTYPE html><html><body>"
                "<svg><path d='M0' stroke=#0055DC /></svg></body></html>\n---")
        text = fanout._plain(page, 300)
        self.assertNotIn("<", text)
        self.assertIn("refused for too many requests (429)", text)


class WorkerSide(unittest.TestCase):
    def test_storage_saying_no_is_gone_and_a_stall_is_not(self):
        with mock.patch.object(fanout.r2, "enabled", return_value=False), \
                mock.patch.object(fanout.requests, "get", return_value=_Resp(404)), \
                mock.patch.object(fanout.time, "sleep"):
            with self.assertRaises(fanout.Gone) as cm:
                fanout._fetch("https://cdn.example/a.mp4", os.path.join(tempfile.mkdtemp(), "a.mp4"))
        self.assertEqual(cm.exception.status, 404)
        with mock.patch.object(fanout.r2, "enabled", return_value=False), \
                mock.patch.object(fanout.requests, "get", return_value=_Resp(503)), \
                mock.patch.object(fanout.time, "sleep"):
            with self.assertRaises(RuntimeError) as cm:
                fanout._fetch("https://cdn.example/a.mp4", os.path.join(tempfile.mkdtemp(), "a.mp4"))
        self.assertNotIsInstance(cm.exception, fanout.Gone)

    def test_a_chunk_whose_scene_files_are_gone_is_refused_before_a_frame_is_drawn(self):
        doc = _doc([300] * 6)

        def fake_fetch(url, path, key="", bucket="", tries=4):
            if url.endswith(("/media/s2.mp4", "/thumbs/s3.jpg")):
                raise fanout.Gone(f"download failed (HTTP 404): {url}", 404)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"x")
            return path
        work = tempfile.mkdtemp()
        with mock.patch.object(fanout, "_fetch", side_effect=fake_fetch):
            stats = fanout._localize(_doc([300] * 6), 600, 1199, work)
        self.assertEqual(stats["missing"], ["https://pub.example/media/s2.mp4"])    # a still only dresses a frame
        self.assertEqual(stats["status"], 404)
        inp = {"action": "render_chunk", "upload": "r2", "chunk": 2, "frames": [600, 1199],
               "prefix": "chunks/job-1234567890/", "renderer": "fp1", "deadline_at": time.time() + 600}
        with mock.patch.object(fanout.r2, "enabled", return_value=True), \
                mock.patch.object(config, "POD_RENDER_PREFIX", "chunks/"), \
                mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp1"), \
                mock.patch.object(fanout, "_load_timeline", return_value=doc), \
                mock.patch.object(fanout, "_fetch", side_effect=fake_fetch), \
                mock.patch.object(fanout.renderer, "render", side_effect=AssertionError("must not render")):
            out = fanout.run_pod_chunk(inp, tempfile.mkdtemp())
        self.assertFalse(out["ok"])
        self.assertEqual(out["missing"], ["https://pub.example/media/s2.mp4"])
        self.assertIn("not in storage (HTTP 404)", out["error"])
        self.assertIn("pub.example/.../s2.mp4", out["error"])


class Cleanup(unittest.TestCase):
    def test_the_job_waits_a_moment_for_its_chunk_files_to_be_deleted(self):
        gate = threading.Event()
        done = []

        def slow_delete(prefix, keys):
            gate.wait(5)
            done.append(prefix)
        t = threading.Thread(target=slow_delete, args=("chunks/j-1/", []), daemon=True)
        t.start()
        with fanout._CLEANUP_LOCK:
            fanout._CLEANUP.append(t)
        self.assertEqual(fanout.finish_cleanup(0.05), 1)         # bounded: a slow clean-up never holds the job
        gate.set()
        self.assertEqual(fanout.finish_cleanup(5), 0)
        self.assertEqual(done, ["chunks/j-1/"])

    def test_the_handler_waits_for_it_when_a_job_ends(self):
        with mock.patch.object(handler.fanout, "finish_cleanup", return_value=0) as wait, \
                mock.patch.object(handler.selftest, "run", return_value={"ok": True}):
            handler.handler({"id": "j1", "input": {"action": "selftest"}})
        wait.assert_called_once()


class LocalFiles(unittest.TestCase):
    def test_every_local_file_the_renderer_would_load_is_found(self):
        d = tempfile.mkdtemp()
        a, b, c = _file(d, "a.mp4"), _file(d, "b.jpg"), _file(d, "c.png")
        doc = _doc([150] * 4)
        doc["scenes"][0]["media"]["url"] = a
        doc["scenes"][1]["animation"] = {"type": "stat", "media": [{"type": "image", "url": b}]}
        doc["overlays"] = [{"type": "motion", "props": {"picture": {"url": c}}, "startFrame": 0,
                            "durationInFrames": 30}]            # a field no list names: still found
        doc["scenes"][2]["media"]["url"] = os.path.join(d, "not-here.mp4")
        doc["meta"] = {"notes": {"url": a}}
        found = sorted(os.path.basename(p) for _m, _f, p in fanout.local_refs(doc))
        self.assertEqual(found, ["a.mp4", "b.jpg", "c.png"])
        self.assertEqual(fanout.local_refs(_doc([150] * 4)), [])


class OldChunkRender(unittest.TestCase):
    """Without R2 the chunk render sends the document itself: a local file is published, not a reason to give up."""

    def _doc(self):
        d = tempfile.mkdtemp()
        doc = _doc([150] * 16)
        doc["scenes"][5]["media"] = {"type": "image", "url": _file(d, "gap_0005.jpg"), "source": "web_image",
                                     "thumbnail": _file(d, "still_5.jpg")}
        doc["audio"]["url"] = _file(d, "narration.polished.flac")
        return doc

    def test_a_repaired_scenes_local_file_is_published_for_the_chunk_workers(self):
        doc = self._doc()
        remote = json.loads(json.dumps(doc))
        puts = []

        def upload(path, bucket, obj, project_id, job_id, **kw):
            puts.append((os.path.basename(path), obj))
            return f"https://signed.example/{obj}"
        with mock.patch.object(handler.storage, "broker_upload", side_effect=upload):
            ok = handler._links_for_chunks(remote, {"project_id": "p1", "_job_id": "job-9"})
        self.assertTrue(ok)
        self.assertTrue(handler._all_remote(remote))
        self.assertEqual(sorted(n for n, _o in puts), ["gap_0005.jpg", "still_5.jpg"])    # never the narration
        self.assertTrue(all(o.startswith("projects/p1/parts/job-9/local_") for _n, o in puts))
        self.assertTrue(remote["scenes"][5]["media"]["thumbnail"].startswith("https://signed.example/"))
        self.assertEqual(remote["audio"]["url"], doc["audio"]["url"])

    def test_an_upload_that_fails_keeps_the_old_answer(self):
        remote = self._doc()
        with mock.patch.object(handler.storage, "broker_upload", side_effect=RuntimeError("broker down")):
            self.assertFalse(handler._links_for_chunks(remote, {"project_id": "p1", "_job_id": "job-9"}))
        self.assertFalse(handler._links_for_chunks(self._doc(), {}))             # no project to upload to
        self.assertTrue(handler._links_for_chunks(_doc([150] * 4), {}))          # nothing local: as before

    def test_do_render_splits_a_document_with_a_local_repair(self):
        doc = self._doc()
        doc["meta"] = {"sceneCount": 16}
        seen = {}

        def fake_split(remote_doc, out, **kw):
            seen["doc"] = remote_doc
            with open(out, "wb") as fh:
                fh.write(b"final")
            return out
        work = tempfile.mkdtemp()
        with mock.patch.object(handler.fanout, "pod_render_enabled", return_value=False), \
                mock.patch.object(handler.fanout, "render", side_effect=fake_split), \
                mock.patch.object(handler.storage, "broker_upload",
                                  side_effect=lambda path, bucket, obj, *a, **k: f"https://signed.example/{obj}"), \
                mock.patch.object(handler.timeline, "drop_invalid_overlays"), \
                mock.patch.object(handler.timeline, "validate"), \
                mock.patch.object(handler, "_preflight_media", return_value=1), \
                mock.patch.object(handler, "_sanitize_stills"), \
                mock.patch.object(handler, "_sign_supabase_urls"), \
                mock.patch.object(handler.voicepolish, "for_render", return_value={}), \
                mock.patch.object(handler.grade, "prepare", return_value={}), \
                mock.patch.object(handler.renderer, "render", side_effect=AssertionError("not on one machine")), \
                mock.patch.object(handler.r2, "enabled", return_value=False), \
                mock.patch.object(config, "QUALITY_SCAN", False), \
                mock.patch.object(handler, "_keep_render"), mock.patch.object(handler.renderer, "fit_size"):
            report = mock.Mock()
            report.job = {"id": "job-9"}
            handler.do_render(doc, {"return_video": True, "project_id": "p1", "_job_id": "job-9"}, work, report,
                              split=True)
        self.assertTrue(seen["doc"]["scenes"][5]["media"]["url"].startswith("https://signed.example/projects/p1/"))


class TheLastResort(unittest.TestCase):
    def setUp(self):
        events.start_job("one-machine", "")

    def _long(self, frames=52000):
        doc = _doc([260] * (frames // 260))
        doc["meta"] = {"sceneCount": len(doc["scenes"])}
        return doc

    def test_a_long_video_on_one_machine_says_so_and_why(self):
        with mock.patch.object(config, "RENDER_CPUS", 16), \
                mock.patch.object(handler.fanout, "pod_render_ready",
                                  return_value={"enabled": False, "missing": ["Cloudflare R2 is not configured"]}):
            handler._on_one_machine(self._long(), 12, spread=False)
        row = next(e for e in events._EVENTS if e["event"] == "whole_render")
        self.assertIn("29-minute video on this one machine (16 CPUs", row["message"])
        self.assertIn("Cloudflare R2 is not configured", row["message"])
        self.assertEqual(row["level"], "warning")

    def test_a_video_that_could_not_finish_in_time_is_refused_before_it_starts(self):
        with mock.patch.object(config, "RENDER_CPUS", 16), mock.patch.object(config, "RENDER_TIMEOUT_MAX_SECONDS", 3600), \
                mock.patch.object(handler.fanout, "pod_render_ready",
                                  return_value={"enabled": False, "missing": ["RunPod API key missing"]}):
            with self.assertRaises(render.RenderError) as cm:
                handler._on_one_machine(self._long(), 12, spread=False)
            handler._on_one_machine(self._long(9000), 12, spread=False)       # a 5-minute video fits: allowed
            handler._on_one_machine(_doc([150] * 4), 12, spread=False)        # a short one: not even a warning
        text = str(cm.exception)
        self.assertIn("This 29-minute video cannot be rendered on one machine", text)
        self.assertIn("RunPod API key missing", text)
        self.assertIn("Nothing was rendered", text)

    def _do_render(self, doc, spread, render_side_effect=None, reach=None):
        work = tempfile.mkdtemp()
        said = []

        def fake_render(d, path, on_progress=None, **kw):
            if on_progress:
                on_progress(0.4)
            with open(path, "wb") as fh:
                fh.write(b"v")
            if kw.get("audio_to"):
                with open(kw["audio_to"], "wb") as fh:
                    fh.write(b"RIFF")
            return path

        def fake_finalize(video, audio, out, **kw):
            with open(out, "wb") as fh:
                fh.write(b"final")
            return {}

        def report(step, pct=None, **kw):
            said.append(step)
        report.job = {"id": "rp-1"}
        with mock.patch.object(handler.fanout, "pod_render_enabled", return_value=bool(spread)), \
                mock.patch.object(handler.fanout, "render_pod", side_effect=spread or None) as pod, \
                mock.patch.object(handler.timeline, "drop_invalid_overlays"), \
                mock.patch.object(handler.timeline, "validate"), \
                mock.patch.object(handler, "_sanitize_stills"), \
                mock.patch.object(handler, "_sign_supabase_urls"), \
                mock.patch.object(handler.voicepolish, "for_render", return_value={}), \
                mock.patch.object(handler.grade, "prepare", return_value={}), \
                mock.patch.object(handler.renderer, "render", side_effect=render_side_effect or fake_render), \
                mock.patch.object(handler.renderer, "finalize", side_effect=fake_finalize), \
                mock.patch.object(handler.renderer, "normalize_loudness"), \
                mock.patch.object(handler.r2, "enabled", return_value=True), \
                mock.patch.object(quality.requests, "get", side_effect=reach or (lambda url, **kw: _Resp(206))), \
                mock.patch.object(quality.time, "sleep"), \
                mock.patch.multiple(config, QUALITY_SCAN=False, QUALITY_HTTP_TIMEOUT=2, ANIMATION_FILL=False,
                                    RENDER_CPUS=16), \
                mock.patch.object(handler, "_keep_render"):
            try:
                out = handler.do_render(doc, {"return_video": True, "_job_id": "rp-1"}, work, report, split=True)
            finally:
                quality.reset()
                gapfill.reset()
        return out, said, pod

    def _short(self):
        doc = _doc([150] * 16)
        doc["meta"] = {"sceneCount": 16}
        for s in doc["scenes"]:
            s["media"]["clipSeconds"] = 6.0
            s["media"].pop("thumbnail", None)
            s["words"] = []
        doc["audio"] = None
        return doc

    def test_the_whole_video_render_says_it_is_on_one_machine(self):
        _out, said, _pod = self._do_render(self._short(), spread=None)
        self.assertIn("Rendering video 40% on one machine", said)

    def test_files_gone_mid_spread_are_repaired_and_the_video_is_spread_again(self):
        doc = self._short()
        gone = "https://pub.example/media/s3.mp4"
        state = {"n": 0}

        def spread(d, out, **kw):
            state["n"] += 1
            if state["n"] == 1:
                raise fanout.SpreadFailed("The video could not be rendered: 1 file it needs is not in storage "
                                          "any more - deleted from storage? (pub.example/.../s3.mp4)", missing=[gone])
            with open(out, "wb") as fh:
                fh.write(b"final")
            return True
        out, _said, _pod = self._do_render(
            doc, spread, render_side_effect=AssertionError("never the whole video on one machine"),
            reach=lambda url, **kw: _Resp(404 if url == gone and state["n"] else 206))
        self.assertEqual(state["n"], 2)
        self.assertNotIn(gone, [s["media"].get("url") for s in doc["scenes"]])
        self.assertTrue(out["quality"]["render"]["afterFailure"])

    def test_a_spread_that_cannot_be_repaired_fails_with_its_reason_not_a_whole_render(self):
        doc = self._short()
        why = ("The video could not be rendered: 1 file it needs is not in storage any more - deleted from "
               "storage? (pub.example/.../s3.mp4)")
        with self.assertRaises(fanout.SpreadFailed) as cm:
            self._do_render(doc, lambda d, out, **kw: (_ for _ in ()).throw(fanout.SpreadFailed(why)),
                            render_side_effect=AssertionError("never the whole video on one machine"))
        self.assertEqual(str(cm.exception), why)


if __name__ == "__main__":
    unittest.main()
