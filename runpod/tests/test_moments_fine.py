import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, media, moments, pools


class CleanWindow(unittest.TestCase):
    def test_no_cuts_keeps_the_intended_moment(self):
        self.assertEqual(media.clean_window(11.0, [], 7.0, 2.0), (2.0, True, 0))

    def test_the_stretch_holding_the_moment_wins_when_long_enough(self):
        # cuts at 1.0 and 9.5 in an 11 s file; the middle stretch holds 2.0 and 7 s fit
        off, clean, n = media.clean_window(11.0, [1.0, 9.5], 7.0, 2.0)
        self.assertEqual((off, clean, n), (2.0, True, 2))
        # the moment sits near the end of its stretch: slide back so the clip fits
        off, clean, n = media.clean_window(11.0, [1.0, 9.5], 7.0, 4.0)
        self.assertEqual((off, clean, n), (2.5, True, 2))

    def test_falls_back_to_the_longest_stretch_then_flags_rapid_cutting(self):
        off, clean, n = media.clean_window(11.0, [3.5], 7.0, 2.0)   # first stretch too short
        # A stretch that opens on a cut starts CUT_SNAP_PAD past it: no frame of the shot before shows.
        self.assertEqual((round(off, 3), clean, n), (round(3.5 + config.CUT_SNAP_PAD, 3), True, 1))
        off, clean, n = media.clean_window(11.0, [2.0, 4.0, 6.0, 8.0, 10.0], 7.0, 2.0)
        self.assertFalse(clean)
        self.assertEqual(n, 5)


class FinePass(unittest.TestCase):
    def test_longest_strong_run_beats_one_brilliant_tile(self):
        times = [100.0 + i for i in range(20)]
        rated = [{"tile": t, "score": 0.8, "description": f"shore {t}"} for t in range(5, 13)]
        rated.append({"tile": 15, "score": 0.97, "description": "one frame"})
        with mock.patch.object(config, "MOMENT_FINE_PASS", True), \
                mock.patch.object(moments, "contact_sheet", return_value=("sheet", times)), \
                mock.patch.object(moments.vision, "enabled", return_value=True), \
                mock.patch.object(moments.vision, "rate_tiles", return_value=rated) as rt:
            fine = moments.refine({"id": "v", "duration": 600}, {"start": 110.0, "score": 0.75},
                                  "Lake Mead shoreline", "narration", 7.0)
        self.assertTrue(fine["fine"])
        self.assertAlmostEqual(fine["start"], times[4] - 0.3)
        self.assertEqual(fine["tiles"], 8)
        self.assertAlmostEqual(fine["score"], 0.8)
        self.assertEqual(rt.call_args.kwargs.get("intent"), "Lake Mead shoreline")

    def test_nothing_above_the_floor_keeps_the_coarse_pick(self):
        times = [100.0 + i for i in range(20)]
        with mock.patch.object(config, "MOMENT_FINE_PASS", True), \
                mock.patch.object(moments, "contact_sheet", return_value=("sheet", times)), \
                mock.patch.object(moments.vision, "enabled", return_value=True), \
                mock.patch.object(moments.vision, "rate_tiles", return_value=[]):
            self.assertIsNone(moments.refine({"id": "v"}, {"start": 110.0, "score": 0.75}, "x", "", 7.0))
        self.assertEqual(media._refine_moment({"id": "v"}, {"start": 1.0, "score": 0.7}, 7.0, "", ""),
                         {"start": 1.0, "score": 0.7})

    def test_moment_score_halves_when_no_clean_stretch(self):
        self.assertAlmostEqual(media._moment_score({"score": 0.8}, True), 0.8)
        self.assertAlmostEqual(media._moment_score({"score": 0.8}, False), 0.4)
        self.assertIsNone(media._moment_score(None, True))


class MomentKeys(unittest.TestCase):
    def test_key_bucket_matches_the_pool_spacing(self):
        with mock.patch.object(config, "POOL_MIN_GAP_SECONDS", 8.0):
            self.assertEqual(pools.moment_key("X", 9.0), "yt:X@1")
            self.assertEqual(pools.moment_key("X", 15.9), "yt:X@1")
            self.assertEqual(pools.moment_key("X", 16.0), "yt:X@2")
            spaced = pools.spaced([{"start": 10.0, "score": 0.8}, {"start": 18.0, "score": 0.8}], 8.0)
            keys = {pools.moment_key("X", m["start"]) for m in spaced}
            self.assertEqual(len(keys), 2)          # 10 s buckets would have merged these


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg needed")
class RealCuts(unittest.TestCase):
    def test_a_hard_cut_is_found_and_the_clip_is_cut_from_the_clean_side(self):
        d = tempfile.mkdtemp()
        src = os.path.join(d, "yt_abc_0_11.mp4")
        # 3 s of one moving pattern, then 8 s of another: one hard cut at 3.0 s.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=3",
                        "-f", "lavfi", "-i", "mandelbrot=size=320x180:rate=25",
                        "-filter_complex", "[1:v]trim=duration=8,setpts=PTS-STARTPTS[b];[0:v][b]concat=n=2:v=1:a=0[v]",
                        "-map", "[v]", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", src],
                       check=True, timeout=120)
        cuts = media.scene_cuts(src)
        self.assertTrue(any(2.7 <= c <= 3.3 for c in cuts), cuts)
        with mock.patch.object(config, "CLEAN_CUTS", True):
            out, clean, n = media.tidy_clip(src, 6.0, prefer=2.0)
        self.assertTrue(clean)
        self.assertGreaterEqual(n, 1)
        self.assertTrue(out.endswith(".mp4") and os.path.exists(out) and not os.path.exists(src))
        self.assertGreaterEqual(media._video_seconds(out), 5.5)
        self.assertLessEqual(len(media.scene_cuts(out)), 0)      # no cut inside the clip


if __name__ == "__main__":
    unittest.main()
