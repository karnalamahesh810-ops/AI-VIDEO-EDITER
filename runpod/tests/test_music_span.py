"""
The music runs under the whole narration (the owner, 2026-10-04: "the music
didn't match the full length of the narration, it is only going 30 seconds, it
is not even stretching out"): the worker's rule (timeline.music_fit), the
check before a render (quality.Gate._music_span) and the renderer's own
arithmetic (remotion/src/components/musicMix.ts, run in node).
"""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, quality, timeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
MIX_TS = os.path.join(REMOTION, "src", "components", "musicMix.ts")
AMB_TS = os.path.join(REMOTION, "src", "components", "ambienceMix.ts")
BGM = os.path.join(REMOTION, "public", "bgm")


def flat(total: int, fps: int, level: float = 0.5) -> dict:
    """The worker's flat mix for a video of `total` frames."""
    with mock.patch.multiple(config, MUSIC_DUCK=0.8):
        return timeline.music_flat({}, {"genre": "suspense", "track": "suspense-v2"}, fps, total, -20.0, level)


def exported_at_60(music: dict) -> dict:
    """What the editor's 60 fps export left before 2026-10-04: the music's frame numbers untouched."""
    return copy.deepcopy(music)


class Fit(unittest.TestCase):
    def test_a_plan_that_spans_the_video_is_left_alone(self):
        for fps, total in ((30, 52810), (60, 105620), (30, 300)):
            music = flat(total, fps)
            got, why = timeline.music_fit(music, total, fps)
            self.assertIs(got, music)
            self.assertEqual(why, "")
            self.assertEqual(music["sections"][-1]["endFrame"], total)       # planned to the last frame
            self.assertEqual(music["sections"][-1]["volume"], 0.0)           # ... and faded out there
        self.assertEqual(timeline.music_fit(None, 900, 30), (None, ""))
        self.assertEqual(timeline.music_fit({"sections": []}, 900, 30), ({"sections": []}, ""))

    def test_yellowstone_the_60_fps_export_left_the_music_at_30_fps_frames(self):
        # 2026-10-03: a 29:20 video planned at 30 fps (52,810 frames), exported at 60 (105,620):
        # its fade-out stayed at frame 52,720 - 14:39 into the video - and the rest was silent.
        stale = exported_at_60(flat(52810, 30))
        self.assertEqual(stale["sections"][2]["startFrame"], 52720)
        got, why = timeline.music_fit(stale, 105620, 60)
        # The plan made at 60 fps (but for the fade-in's first frame, 1/30 s now).
        self.assertEqual(got["sections"][1:], [{**s, "startFrame": max(2, s["startFrame"])}
                                                for s in flat(105620, 60)["sections"][1:]])
        self.assertEqual(got["sections"][0], {"startFrame": 0, "volume": 0.0, "mood": "suspense", "kind": "fade-in",
                                              "endFrame": 2})
        self.assertEqual(got["sections"][2]["startFrame"], 105620 - 180)       # the fade-out, 3 s before the end
        self.assertEqual(got["sections"][-1]["endFrame"], 105620)
        self.assertEqual(got["duck"], 0.8)
        self.assertEqual(got["levels"], stale["levels"])
        self.assertIn("faded out at 14:40 of 29:20", why)
        self.assertEqual(stale["sections"][2]["startFrame"], 52720)            # the input is not changed

    def test_the_trim_moves_with_the_sections(self):
        stale = {**exported_at_60(flat(9000, 30)), "from": 300, "to": 4500, "gain": 1.1}
        got, _why = timeline.music_fit(stale, 18000, 60)
        self.assertEqual((got["from"], got["to"], got["gain"]), (600, 9000, 1.1))
        back, why = timeline.music_fit({**flat(18000, 60), "from": 600, "to": 9000}, 9000, 30)
        self.assertEqual((back["from"], back["to"]), (300, 4500))
        self.assertEqual(back["sections"][-1]["endFrame"], 9000)
        self.assertIn("ran past the video's end", why)

    def test_a_video_made_longer_or_shorter_keeps_its_levels_and_fades_out_at_its_end(self):
        plan = flat(9000, 30)
        plan["sections"].insert(2, {"startFrame": 4000, "volume": 0.7, "mood": "suspense", "kind": "pause",
                                    "endFrame": 4200})
        plan["sections"].insert(3, {"startFrame": 4200, "volume": 0.5, "mood": "suspense", "kind": "voice",
                                    "endFrame": 8910})
        for total in (9600, 8000, 4100):
            got, why = timeline.music_fit(copy.deepcopy(plan), total, 30)
            starts = [(s["startFrame"], s["kind"]) for s in got["sections"]]
            self.assertEqual(starts[-2:], [(total - 90, "fade-out"), (total - 45, "fade-out")], total)
            self.assertEqual(got["sections"][-1]["endFrame"], total)
            self.assertEqual(got["sections"][-2]["volume"], 0.25)
            self.assertEqual(sum(1 for s in got["sections"] if s["kind"] == "fade-out"), 2)
            self.assertEqual((4000, "pause") in starts, total > 4090)             # a rise past the new end is gone
            self.assertIn("timed for a 5:00 video", why)

    def test_a_lone_level_set_in_the_editor_covers_the_whole_video(self):
        # Lake Mead, 2026-10-03: one section 0 - 52,720 on a 105,440-frame video. The renderer never
        # read a lone section's range (it played the whole video), so nothing was wrong to report.
        lone = {"sections": [{"startFrame": 0, "endFrame": 52720, "mood": "crime-v1", "volume": 0.69}], "duck": 0.65}
        got, why = timeline.music_fit(lone, 105440, 60)
        self.assertEqual(got["sections"], [{"startFrame": 0, "endFrame": 105440, "mood": "crime-v1", "volume": 0.69}])
        self.assertEqual((got["duck"], why), (0.65, ""))
        self.assertIs(timeline.music_fit(got, 105440, 60)[0], got)


class Check(unittest.TestCase):
    def _doc(self, music, total, fps, bgm=None):
        return {"fps": fps, "width": 640, "height": 360, "durationInFrames": total, "scenes": [], "overlays": [],
                "bgm": bgm or {"url": "bgm://suspense-v2", "volume": 0.5}, "music": music, "meta": {}}

    def tearDown(self):
        quality.reset()

    def test_the_check_before_a_render_stretches_the_music_and_says_so(self):
        doc = self._doc(exported_at_60(flat(52810, 30)), 105620, 60)
        gate = quality.Gate(doc, tempfile.mkdtemp())
        gate._music_span({})
        self.assertEqual(doc["music"]["sections"][-1]["endFrame"], 105620)
        self.assertEqual(doc["music"]["sections"][2]["startFrame"], 105620 - 180)
        self.assertEqual((gate.found["music-length"], gate.fixed["music-length"]), (1, 1))
        self.assertIn("music stretched to the end", gate.summary())
        self.assertIn("it now plays to the end of the video", gate.repairs[0]["how"])
        # Nothing to say about a document whose music already spans it, or one with the music off.
        for doc in (self._doc(flat(9000, 30), 9000, 30), {**self._doc(flat(900, 30), 9000, 30), "bgm": None}):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate._music_span({})
            self.assertEqual(gate.fixed["music-length"], 0)
            self.assertNotIn("music", gate.summary())

    def test_an_own_tracks_length_is_measured_so_the_renderer_can_repeat_it(self):
        url = "https://cdn.example/my-track.mp3"
        doc = self._doc(flat(9000, 30), 9000, 30, {"url": url, "volume": 0.5, "track": "crime-v1", "trackSeconds": 1800})
        with mock.patch.object(quality, "track_seconds", return_value=212.3456) as probe, \
                mock.patch.object(quality.r2, "_creds", return_value=None):
            quality.Gate(doc, tempfile.mkdtemp())._music_span({url: quality.Check(ok=True)})
            self.assertEqual(doc["bgm"], {"url": url, "volume": 0.5, "trackSeconds": 212.35})   # not the bed's 1800
            quality.Gate(doc, tempfile.mkdtemp())._music_span({url: quality.Check(ok=True)})
            self.assertEqual(probe.call_count, 1)                                # measured once
            # A link that could not be checked is not probed; a bundled track never is.
            other = self._doc(flat(9000, 30), 9000, 30, {"url": url, "volume": 0.5})
            quality.Gate(other, tempfile.mkdtemp())._music_span({url: quality.Check(ok=True, unverified=True)})
            quality.Gate(self._doc(flat(9000, 30), 9000, 30), tempfile.mkdtemp())._music_span({})
            self.assertEqual(probe.call_count, 1)
            self.assertNotIn("trackSeconds", other["bgm"])

    @unittest.skipUnless(shutil.which("ffprobe"), "needs ffprobe")
    def test_track_seconds_reads_a_real_file(self):
        self.assertAlmostEqual(quality.track_seconds(os.path.join(BGM, "investigative-20m.mp3")), 1199.12, places=1)
        self.assertEqual(quality.track_seconds(os.path.join(BGM, "no-such-track.mp3")), 0.0)


def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { BGM_META, MUSIC_DUCK, MUSIC_LEVEL, MUSIC_LOOP_CROSSFADE, fitMusic, flatMusic, musicPasses, musicSpan,
  musicVolume, trackSeconds } from "%(mix)s";
import { passGain } from "%(amb)s";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out: any = { consts: { BGM_META, MUSIC_DUCK, MUSIC_LEVEL, MUSIC_LOOP_CROSSFADE } };
out.fit = (input.fit || []).map((c: any) => fitMusic(c.music, c.total, c.fps));
out.same = (input.fit || []).map((c: any) => fitMusic(c.music, c.total, c.fps) === c.music);
out.flat = (input.flat || []).map((c: any) => flatMusic(c.total, c.fps, c.level, c.duck, c.mood));
out.span = (input.span || []).map((c: any) => musicSpan(c.music, c.total, c.fps));
out.volume = (input.volume || []).map((c: any) => {
  const v = musicVolume(c.doc);
  return c.frames.map((f: number) => v(f));
});
out.passes = (input.passes || []).map((c: any) => {
  const seconds = trackSeconds(c.name, c.bgm);
  const ps = musicPasses(c.total, c.fps, seconds);
  // the summed power of every pass at each asked frame of the video
  const power = (c.power || []).map((f: number) => ps.reduce((s: number, p: any) =>
    s + (f >= p.from && f < p.from + p.frames ? passGain(p, f - p.from) ** 2 : 0), 0));
  return { seconds, ps, power };
});
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Renderer(unittest.TestCase):
    """musicMix.ts: what the export, the editor's preview and the editor's music bar all compute."""

    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"mix": MIX_TS.replace("\\", "/")[:-3], "amb": AMB_TS.replace("\\", "/")[:-3]})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_ts(self, **payload):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(payload), capture_output=True, text=True,
                             timeout=120, check=True)
        return json.loads(run.stdout)

    def test_the_owners_mix_and_the_tracks_are_the_workers(self):
        consts = self.run_ts()["consts"]
        self.assertEqual(consts["MUSIC_LEVEL"], float(os.getenv("MUSIC_LEVEL", "0.5")))
        self.assertEqual(consts["MUSIC_DUCK"], float(os.getenv("MUSIC_DUCK", "0.8")))
        self.assertEqual((consts["MUSIC_LEVEL"], consts["MUSIC_DUCK"]), (0.5, 0.8))          # the owner, 2026-10-02
        known = {name: seconds for tracks in timeline.BGM_TRACKS.values() for name, seconds in tracks}
        self.assertEqual(set(consts["BGM_META"]), set(known))
        for name, meta in consts["BGM_META"].items():
            self.assertLess(abs(meta["seconds"] - known[name]), 1.0, name)
            self.assertTrue(os.path.isfile(os.path.join(BGM, name + ".mp3")), name)
            if shutil.which("ffprobe"):
                real = quality.track_seconds(os.path.join(BGM, name + ".mp3"))
                self.assertLessEqual(meta["seconds"], real, name)                  # never past the file's end
                self.assertLess(real - meta["seconds"], 0.05, name)

    def test_the_renderer_and_the_worker_fit_the_music_the_same_way(self):
        ripple = flat(9000, 30)
        ripple["sections"].insert(2, {"startFrame": 4000, "volume": 0.7, "mood": "suspense", "kind": "pause",
                                      "endFrame": 8910})
        cases = [
            {"music": exported_at_60(flat(52810, 30)), "total": 105620, "fps": 60},
            {"music": {**exported_at_60(flat(9000, 30)), "from": 300, "to": 4500, "gain": 1.1}, "total": 18000, "fps": 60},
            {"music": {**flat(18001, 60), "from": 601, "to": 9001}, "total": 9001, "fps": 30},
            {"music": ripple, "total": 9600, "fps": 30},
            {"music": ripple, "total": 4100, "fps": 30},
            {"music": {"sections": [{"startFrame": 0, "endFrame": 52720, "mood": "crime-v1", "volume": 0.69}],
                       "duck": 0.65}, "total": 105440, "fps": 60},
            {"music": {"sections": [{"startFrame": 0, "endFrame": 400, "mood": "A", "volume": 0.1},
                                    {"startFrame": 400, "endFrame": 900, "mood": "B", "volume": 0.2}]},
             "total": 1800, "fps": 60},
            {"music": flat(9000, 30), "total": 9000, "fps": 30},
            {"music": None, "total": 9000, "fps": 30},
        ]
        got = self.run_ts(fit=cases)
        for case, ts, same in zip(cases, got["fit"], got["same"]):
            py, _why = timeline.music_fit(copy.deepcopy(case["music"]), case["total"], case["fps"])
            self.assertEqual(ts, py, case)
            self.assertEqual(same, py == case["music"], case)                       # untouched when nothing is wrong

    def test_the_editors_default_mix_is_the_workers_flat_mix(self):
        cases = [{"total": t, "fps": f, "level": 0.5, "duck": 0.8, "mood": "suspense"}
                 for t, f in ((52810, 30), (105620, 60), (300, 30), (40, 30))]
        for case, ts in zip(cases, self.run_ts(flat=cases)["flat"]):
            py = flat(case["total"], case["fps"])
            self.assertEqual(ts["sections"], py["sections"], case)
            self.assertEqual(ts["duck"], py["duck"])
            self.assertEqual(ts["levels"], {"mode": "flat", "speech": 0.5})

    def _doc(self, music, total, fps, **extra):
        return {"fps": fps, "durationInFrames": total, "bgm": {"url": "bgm://suspense-v2", "volume": 0.5},
                "music": music, "scenes": [{"words": [{"start": 100.0, "end": 101.0}]}], **extra}

    def test_a_new_videos_music_runs_from_the_first_frame_to_the_last(self):
        for fps, total in ((30, 52810), (60, 105620)):
            sec = lambda s: int(s * fps)                                            # noqa: E731
            frames = [0, sec(0.75), sec(5), sec(100.5), total // 2, sec(880), total - sec(4), total - sec(2.25),
                      total - 1]
            v = dict(zip(frames, self.run_ts(volume=[{"doc": self._doc(flat(total, fps), total, fps),
                                                      "frames": frames}])["volume"][0]))
            self.assertEqual(v[0], 0.0)                                             # in from silence
            self.assertAlmostEqual(v[sec(0.75)], 0.5 * (sec(0.75) - 1) / sec(1.5), places=4)   # halfway up
            self.assertAlmostEqual(v[sec(5)], 0.5, places=4)                        # the owner's 50%
            self.assertAlmostEqual(v[sec(100.5)], 0.4, places=4)                    # x 0.8 while a word is spoken
            self.assertAlmostEqual(v[total // 2], 0.5, places=4)
            self.assertAlmostEqual(v[sec(880)], 0.5, places=4)
            self.assertAlmostEqual(v[total - sec(4)], 0.5, places=4)                # still there 4 s before the end
            self.assertAlmostEqual(v[total - sec(2.25)], 0.375, places=2)           # fading out
            self.assertLess(v[total - 1], 0.01)

    def test_yellowstone_plays_to_the_end_in_the_preview_and_the_export(self):
        # The document as it sits in the database: 60 fps, the music at 30 fps frame numbers.
        total, fps = 105620, 60
        frames = [fps * 5, fps * 870, 52720 + 45, 52720 + 200, fps * 1000, fps * 1500, total - fps * 4, total - 1]
        stale, good = self.run_ts(volume=[
            {"doc": self._doc(exported_at_60(flat(52810, 30)), total, fps), "frames": frames},
            {"doc": self._doc(flat(total, fps), total, fps), "frames": frames}])["volume"]
        self.assertEqual(stale, good)                              # exactly the mix planned at 60 fps
        self.assertTrue(all(x == 0.5 for x in stale[:-1]), stale)  # 14:39 on was silent before
        self.assertLess(stale[-1], 0.01)

    def test_the_trim_is_what_plays_and_absent_means_the_whole_video(self):
        total, fps = 9000, 30
        plan = flat(total, fps)
        lone = {"sections": [{"startFrame": 300, "endFrame": 900, "mood": "x", "volume": 0.6}], "duck": 1.0}
        spans = self.run_ts(span=[
            {"music": plan, "total": total, "fps": fps}, {"music": None, "total": total, "fps": fps},
            {"music": {**plan, "from": 900, "to": 4500}, "total": total, "fps": fps},
            {"music": {**plan, "from": -5, "to": 99999}, "total": total, "fps": fps},
            {"music": {**plan, "from": 8999.6, "to": 3}, "total": total, "fps": fps},
            {"music": lone, "total": total, "fps": fps},                 # a lone section's range was never played
            {"music": {**exported_at_60(plan), "from": 900, "to": 4500}, "total": total * 2, "fps": 60},
        ])["span"]
        self.assertEqual(spans, [{"from": 0, "to": 9000}, {"from": 0, "to": 9000}, {"from": 900, "to": 4500},
                                 {"from": 0, "to": 9000}, {"from": 8999, "to": 9000}, {"from": 0, "to": 9000},
                                 {"from": 1800, "to": 9000}])
        frames = [0, 600, 899, 900, 922, 945, 2000, 4477, 4500, 4501, 8000]
        trimmed, whole, level = self.run_ts(volume=[
            {"doc": self._doc({**plan, "from": 900, "to": 4500, "gain": 1.2}, total, fps), "frames": frames},
            {"doc": self._doc({**plan, "gain": 1.2}, total, fps), "frames": frames},
            {"doc": self._doc({**lone, "from": 900, "to": 4500}, total, fps), "frames": frames}])["volume"]
        t = dict(zip(frames, trimmed))
        self.assertEqual([t[0], t[600], t[899], t[900], t[4501], t[8000]], [0, 0, 0, 0, 0, 0])   # silent outside
        self.assertAlmostEqual(t[922], 0.6 * 22 / 45, places=4)          # in over 1.5 s
        self.assertAlmostEqual(t[945], 0.6, places=4)                    # 50% x the editor's 120%
        self.assertAlmostEqual(t[2000], 0.6, places=4)
        self.assertAlmostEqual(t[4477], 0.6 * 23 / 45, places=4)         # out over 1.5 s
        self.assertAlmostEqual(dict(zip(frames, whole))[8000], 0.6, places=4)
        self.assertEqual([round(x, 4) for x in level], [round(x, 4) for x in trimmed])   # a lone level: the same trim

    def test_a_level_set_in_the_editor_fades_in_and_out_like_the_workers_mix(self):
        total, fps = 9000, 30
        lone = {"sections": [{"startFrame": 0, "endFrame": 4500, "mood": "x", "volume": 0.6}], "duck": 0.5}
        frames = [0, 22, 45, 3015, 5000, total - 90, total - 45, total]
        v = dict(zip(frames, self.run_ts(volume=[{"doc": self._doc(lone, total, fps), "frames": frames}])["volume"][0]))
        self.assertEqual(v[0], 0.0)
        self.assertAlmostEqual(v[22], 0.6 * 22 / 45, places=4)
        self.assertAlmostEqual(v[45], 0.6, places=4)
        self.assertAlmostEqual(v[3015], 0.3, places=4)                   # ducked to its own 50% under a word
        self.assertAlmostEqual(v[5000], 0.6, places=4)                   # past its old "end": it always played here
        self.assertAlmostEqual(v[total - 90], 0.6, places=4)
        self.assertAlmostEqual(v[total - 45], 0.3, places=4)             # out over the last 3 s
        self.assertEqual(v[total], 0.0)

    def test_a_track_shorter_than_the_video_repeats_with_a_crossfade(self):
        fps = 30
        forty = 40 * 60 * fps
        probe = list(range(0, forty, 997)) + list(range(1800 * fps - 400, 1800 * fps + 100, 7))
        cases = [
            {"name": "suspense-v2", "total": forty, "fps": fps, "power": probe},            # 30 min under 40
            {"name": "crime-v1", "total": forty, "fps": fps, "power": probe},               # its last 12 s are its own fade
            {"name": "investigative-20m", "total": 70 * 60 * fps, "fps": fps, "power": []},  # three and a half passes
            {"name": "suspense-v2", "total": 29 * 60 * fps, "fps": fps, "power": []},        # long enough: one pass
            {"name": "", "bgm": {"url": "https://x/own.mp3", "trackSeconds": 200.5}, "total": 9000, "fps": fps,
             "power": list(range(0, 9000, 13))},
            {"name": "", "bgm": {"url": "https://x/own.mp3"}, "total": 9000, "fps": fps, "power": []},
            {"name": "", "bgm": {"url": "https://x/own.mp3", "track": "crime-v1", "trackSeconds": 1800},
             "total": 9000, "fps": fps, "power": []},
        ]
        got = self.run_ts(passes=cases)["passes"]
        cross = 3 * fps
        for case, res in zip(cases[:5], got[:5]):
            ps, file = res["ps"], round(res["seconds"] * fps)
            self.assertEqual(ps[0]["from"], 0)
            self.assertEqual(ps[-1]["from"] + ps[-1]["frames"], case["total"])      # music to the last frame
            self.assertFalse(any(p["loop"] for p in ps))
            for p in ps:
                self.assertLessEqual(p["frames"], file)                                # never past the usable end
            for a, b in zip(ps, ps[1:]):
                self.assertEqual(a["from"] + a["frames"] - b["from"], cross)           # 3 s of both
                self.assertEqual((a["fadeOut"], b["fadeIn"]), (cross, cross))
            for f, pw in zip(case["power"], res["power"]):
                self.assertAlmostEqual(pw, 1.0, places=6, msg=(case["name"], f))    # no dip, no bump, no gap
        self.assertEqual([len(r["ps"]) for r in got[:5]], [2, 2, 4, 1, 2])
        self.assertAlmostEqual(got[0]["seconds"], 1800.04)
        self.assertAlmostEqual(got[1]["seconds"], 1788.04)                              # before the bed's own fade-out
        self.assertEqual(got[1]["ps"][1]["from"], round(1788.04 * fps) - cross)
        # A file nobody measured (or one carrying the replaced bed's length): Remotion's own loop.
        for res in got[5:]:
            self.assertEqual(res["seconds"], 0)
            self.assertEqual(res["ps"], [{"from": 0, "frames": 9000, "fadeIn": 0, "fadeOut": 0, "loop": True}])

    def test_the_renderer_plays_the_music_through_the_shared_mix(self):
        with open(os.path.join(REMOTION, "src", "Main.tsx"), encoding="utf-8") as fh:
            main = fh.read()
        self.assertIn('from "./components/musicMix"', main)
        self.assertIn("musicPasses(total, fps, trackSeconds(track, bgm))", main)
        self.assertIn("volume(p.from + f) * passGain(p, f)", main)
        self.assertNotIn("props.music?.from", main)                # one reading of the trim: musicMix.ts


class Tracks(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_the_crime_bed_ends_in_its_own_fade_and_the_others_do_not(self):
        def tail_db(name: str, back: float, seconds: float) -> float:
            p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-sseof", f"-{back}", "-t", str(seconds), "-i",
                                os.path.join(BGM, name + ".mp3"), "-af", "volumedetect", "-f", "null", "-"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            line = next(x for x in p.stderr.splitlines() if "mean_volume" in x)
            return float(line.split("mean_volume:")[1].split("dB")[0])
        self.assertLess(tail_db("crime-v1", 6, 6), -55.0)                      # silence at the file's end
        self.assertGreater(tail_db("crime-v1", 15, 3), -35.0)                  # full level before the last 12 s
        for name in ("investigative-v5", "investigative-20m", "suspense-v2"):
            self.assertGreater(tail_db(name, 3, 3), -35.0, name)               # these end at full level


if __name__ == "__main__":
    unittest.main()
