"""The GPU tools client (src/gputools.py) without the endpoint: which clips go, what comes back in place, the
fallbacks, the AI music request and how the timeline plays the bed; nothing reaches RunPod or R2."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, gputools, media, timeline, upscale


def _clip(path, size, rate=30, seconds=1.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}",
                    "-t", f"{seconds}", "-pix_fmt", "yuv420p", path], check=True)
    return path


def _asset(path, source="youtube"):
    return media.MediaAsset(kind="video", source=source, url="u-" + os.path.basename(path), local_path=path)


class FakeClient:
    """Answers like the endpoint: an upscale or a retime comes back as a file made here."""

    def __init__(self, work, fail=()):
        self.work, self.fail, self.calls = work, set(fail), []

    def run(self, payload, deadline):
        self.calls.append(payload)
        name = os.path.basename(payload["url"])
        if name in self.fail:
            raise gputools.GpuToolsError("boom")
        if payload["action"] == "upscale":
            out = _clip(os.path.join(self.work, "out_" + name), "1920x1080", rate=int(payload.get("fps") or 30))
        else:
            out = _clip(os.path.join(self.work, "out_" + name), "1920x1080", rate=int(payload["fps"]))
        return {"ok": True, "url": "https://r2.example/" + os.path.basename(out), "_execution_ms": 1234,
                "_local": out}


class GpuToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        gputools.reset()
        self.fake = FakeClient(self.dir)
        self.patches = [
            mock.patch.object(gputools, "client", lambda: self.fake),
            mock.patch.object(gputools, "_stage", lambda path: "https://r2.example/in/" + os.path.basename(path)),
            mock.patch.object(gputools, "_fetch", self._fetch),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _fetch(self, url, dst, min_bytes=4000):
        shutil.copyfile(os.path.join(self.dir, os.path.basename(url)), dst)
        return dst


class LowresClips(GpuToolsTestCase):
    def test_only_landscape_clips_under_720_lines_and_not_too_long(self):
        d = self.dir
        low = _clip(os.path.join(d, "low.mp4"), "854x480")
        hd = _clip(os.path.join(d, "hd.mp4"), "1280x720")
        vert = _clip(os.path.join(d, "vert.mp4"), "480x854")
        tiny = _clip(os.path.join(d, "tiny.mp4"), "320x180")
        long_ = _clip(os.path.join(d, "long.mp4"), "640x360", seconds=3.0)
        arch = _clip(os.path.join(d, "arch.mp4"), "640x480")
        with mock.patch.object(config, "UPSCALE_LOWRES_MAX_SECONDS", 2.0):
            got = gputools.lowres_candidates([_asset(low), _asset(hd), _asset(vert), _asset(tiny), _asset(long_),
                                              _asset(arch, "archive_org"), None])
        self.assertEqual([p for _a, p, _l in got], [low])
        self.assertEqual(got[0][2], 480)

    def test_sharpened_in_place_and_marked_and_failures_left_alone(self):
        d = self.dir
        a = _clip(os.path.join(d, "a.mp4"), "854x480")
        b = _clip(os.path.join(d, "b.mp4"), "640x480")
        self.fake.fail = {"b.mp4"}
        with mock.patch.object(config, "UPSCALE_LOWRES_CLIPS", True):
            rep = gputools.upscale_lowres([_asset(a), _asset(b)], deadline=1e12)
        self.assertEqual(rep["done"], [a])
        self.assertEqual(rep["failed"], 1)
        self.assertEqual(gputools._probe(a)["h"], 1080)
        self.assertEqual(gputools._probe(b)["h"], 480)                       # the CPU path will take it
        self.assertEqual(upscale.original_lines(a), 480)
        self.assertEqual(self.fake.calls[0]["lines"], 1080)
        self.assertNotIn("fps", self.fake.calls[0])

    def test_sixty_fps_render_asks_for_the_retime_in_the_same_job(self):
        a = _clip(os.path.join(self.dir, "a.mp4"), "854x480")
        with mock.patch.object(config, "UPSCALE_LOWRES_CLIPS", True), \
                mock.patch.object(config, "INTERPOLATE_60FPS", True):
            gputools.upscale_lowres([_asset(a)], deadline=1e12, fps=60)
        self.assertEqual(self.fake.calls[0]["fps"], 60)
        self.assertIn(os.path.abspath(a), gputools.RETIMED)

    def test_flag_off_or_no_endpoint_does_nothing(self):
        a = _clip(os.path.join(self.dir, "a.mp4"), "854x480")
        with mock.patch.object(config, "UPSCALE_LOWRES_CLIPS", False):
            self.assertEqual(gputools.upscale_lowres([_asset(a)], deadline=1e12)["queued"], 0)
        with mock.patch.object(config, "UPSCALE_LOWRES_CLIPS", True), \
                mock.patch.object(gputools, "client", lambda: None):
            self.assertEqual(gputools.upscale_lowres([_asset(a)], deadline=1e12)["queued"], 0)
        self.assertEqual(self.fake.calls, [])

    def test_upscale_assets_skips_the_lanczos_pass_for_what_the_gpu_did(self):
        a = _clip(os.path.join(self.dir, "a.mp4"), "854x480")
        b = _clip(os.path.join(self.dir, "b.mp4"), "640x480")
        self.fake.fail = {"b.mp4"}
        seen = []
        with mock.patch.object(config, "UPSCALE_LOWRES_CLIPS", True), \
                mock.patch.object(config, "UPSCALE_ENABLED", True), \
                mock.patch.object(config, "ARCHIVE_RESTORE", False), \
                mock.patch.object(upscale, "upscale_clip", lambda path, lines=0: seen.append(path) or True):
            out = upscale.upscale_assets([_asset(a), _asset(b)], fps=30)
        self.assertEqual(seen, [b])                                           # only the one the GPU did not do
        self.assertEqual(out["gpu"]["done"], 1)
        self.assertEqual(out["gpu"]["failed"], 1)


class SixtyFps(GpuToolsTestCase):
    def test_clips_under_50_fps_retimed_others_left(self):
        d = self.dir
        c24 = _clip(os.path.join(d, "c24.mp4"), "1920x1080", rate=24)
        c60 = _clip(os.path.join(d, "c60.mp4"), "1920x1080", rate=60)
        with mock.patch.object(config, "INTERPOLATE_60FPS", True):
            rep = gputools.interpolate_clips([_asset(c24), _asset(c60)], 60, deadline=1e12)
        self.assertEqual((rep["queued"], rep["done"]), (1, 1))
        self.assertAlmostEqual(gputools._probe(c24)["fps"], 60.0, places=1)
        self.assertEqual(self.fake.calls[0]["fps"], 60)

    def test_off_for_a_30_fps_render_or_without_the_flag(self):
        c24 = _clip(os.path.join(self.dir, "c24.mp4"), "1920x1080", rate=24)
        with mock.patch.object(config, "INTERPOLATE_60FPS", True):
            self.assertEqual(gputools.interpolate_clips([_asset(c24)], 30, deadline=1e12)["queued"], 0)
        with mock.patch.object(config, "INTERPOLATE_60FPS", False):
            self.assertEqual(gputools.interpolate_clips([_asset(c24)], 60, deadline=1e12)["queued"], 0)
        self.assertEqual(self.fake.calls, [])

    def test_a_clip_already_retimed_by_its_upscale_is_not_sent_again(self):
        c24 = _clip(os.path.join(self.dir, "c24.mp4"), "1920x1080", rate=24)
        gputools.RETIMED.add(os.path.abspath(c24))
        with mock.patch.object(config, "INTERPOLATE_60FPS", True):
            self.assertEqual(gputools.interpolate_clips([_asset(c24)], 60, deadline=1e12)["queued"], 0)


class AiMusic(unittest.TestCase):
    def setUp(self):
        gputools._MUSIC.clear()
        gputools.reset()

    def test_who_asks(self):
        with mock.patch.object(config, "AI_MUSIC", False):
            self.assertFalse(gputools.music_wanted({}))
            self.assertTrue(gputools.music_wanted({"ai_music": True}))
            self.assertTrue(gputools.music_wanted({"ai_music": {"mood": "tense"}}))
            self.assertTrue(gputools.music_wanted({"bgm_track": "ai"}))
            self.assertTrue(gputools.music_wanted({"bgm_genre": "AI"}))
            self.assertFalse(gputools.music_wanted({"ai_music": True, "bgm_url": "https://x/own.mp3"}))
            self.assertFalse(gputools.music_wanted({"ai_music": True, "bgm": False}))
        with mock.patch.object(config, "AI_MUSIC", True):
            self.assertTrue(gputools.music_wanted({}))
            self.assertFalse(gputools.music_wanted({"ai_music": False}))
            self.assertFalse(gputools.music_wanted({"ai_music": "off"}))

    def test_request(self):
        r = gputools.music_request({"project_id": "p1"}, "suspense", 62.4)
        self.assertEqual(r["action"], "music")
        self.assertEqual(r["caption"], gputools.MOODS["suspense"])
        self.assertEqual(r["seconds"], round(62.4 + config.AI_MUSIC_TAIL_SECONDS, 1))
        self.assertEqual(r["seed"], gputools.music_request({"project_id": "p1"}, "suspense", 10)["seed"])
        self.assertNotEqual(r["seed"], gputools.music_request({"project_id": "p2"}, "suspense", 10)["seed"])
        self.assertEqual(r["lufs"], config.AI_MUSIC_LUFS)
        own = gputools.music_request({"ai_music": {"mood": "hopeful", "prompt": " soft  harp ", "seed": 5}},
                                     "suspense", 3000)
        self.assertEqual((own["_mood"], own["caption"], own["seed"]), ("uplifting", "soft harp", 5))
        self.assertEqual(own["seconds"], config.AI_MUSIC_MAX_SECONDS)
        self.assertEqual(gputools.music_request({}, "nonsense", 30)["_mood"], "investigative")

    def test_bed_as_the_timeline_plays_it_and_the_fallbacks(self):
        inp = {"ai_music": True}
        gputools._MUSIC["result"] = {"ok": True, "url": "https://r2.example/gputools/out/j.mp3", "seconds": 68.55,
                                     "lufs": -27.2, "seed": 7, "caption": "c", "mood": "suspense", "_execution_ms": 9}
        bgm = gputools.music_for(inp)
        self.assertEqual(bgm["url"], "https://r2.example/gputools/out/j.mp3")
        self.assertEqual((bgm["trackSeconds"], bgm["lufs"], bgm["genre"]), (68.55, -27.2, "suspense"))
        self.assertNotIn("track", bgm)                          # the renderer then uses trackSeconds for its passes
        self.assertTrue(gputools.STATS["music"]["ok"])
        gputools._MUSIC["result"] = {"ok": False, "error": "not back in time"}
        self.assertIsNone(gputools.music_for(inp))
        self.assertEqual(gputools.STATS["music"]["why"], "not back in time")
        self.assertIsNone(gputools.music_for({"bgm_url": "https://x/own.mp3"}))

    def test_another_jobs_bed_is_never_played(self):
        gputools._MUSIC.update({"key": gputools._job_key({"project_id": "p1"}),
                                "result": {"ok": True, "url": "https://r2.example/gputools/music/j.mp3",
                                           "seconds": 60, "mood": "suspense"}})
        self.assertIsNotNone(gputools.music_for({"project_id": "p1", "ai_music": True}))
        self.assertIsNone(gputools.music_for({"project_id": "p2", "ai_music": True}))
        gputools.reset()
        self.assertIsNone(gputools.music_for({"project_id": "p1", "ai_music": True}))

    def test_start_without_endpoint_plays_the_library(self):
        with mock.patch.object(gputools, "client", lambda: None):
            self.assertFalse(gputools.start_music({"ai_music": True}, "suspense", 60))
        self.assertIsNone(gputools.music_for({"ai_music": True}))

    def test_timeline_bgm_and_levels(self):
        ai = {"url": "https://r2.example/gputools/out/j.mp3", "genre": "suspense", "trackSeconds": 68.5,
              "loop": True, "lufs": -27.2, "ai": {"model": "ace-step-1.5"}}
        with mock.patch.object(gputools, "music_for", lambda inp, wait=0.0: ai):
            bgm = timeline._bgm_for({"ai_music": True}, None, {"kind": "news"}, 60.0)
        self.assertEqual(bgm["url"], ai["url"])
        self.assertEqual(bgm["volume"], 0.12)
        self.assertEqual(timeline.track_lufs_of(bgm), -27.2)
        music = timeline.music_flat({}, bgm, 30, 1800, -20.0, config.MUSIC_LEVEL)
        self.assertEqual(music["levels"]["trackLufs"], -27.2)
        self.assertEqual(music["levels"]["speech"], config.MUSIC_LEVEL)
        self.assertEqual(music["duck"], round(config.MUSIC_DUCK, 3))
        # not ready: the library track the job would have had
        with mock.patch.object(gputools, "music_for", lambda inp, wait=0.0: None):
            lib = timeline._bgm_for({"ai_music": True}, None, {"kind": "news"}, 60.0)
        self.assertTrue(lib["url"].startswith("bgm://"))
        self.assertEqual(timeline.track_lufs_of(lib), timeline.BGM_LUFS[lib["track"]])
        # a job's own track always wins
        own = timeline._bgm_for({"ai_music": True, "bgm_url": "https://x/own.mp3"}, None, {}, 60.0)
        self.assertEqual(own["url"], "https://x/own.mp3")


if __name__ == "__main__":
    unittest.main()
