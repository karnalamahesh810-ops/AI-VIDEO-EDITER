"""The GPU tools worker's pure helpers (plan.py): no torch, no GPU - run in the image build and anywhere."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plan  # noqa: E402


class Inputs(unittest.TestCase):
    def test_action(self):
        self.assertEqual(plan.action_of({"action": "Upscale"}), "upscale")
        for bad in ({"action": "render"}, {}, None, "upscale"):
            with self.assertRaises(plan.InputError):
                plan.action_of(bad)

    def test_upscale_defaults_and_clamps(self):
        got = plan.check_upscale({"url": "https://r2.example/c.mp4"})
        self.assertEqual((got["lines"], got["start"], got["seconds"], got["fps"], got["sparse"], got["local_range"]),
                         (1080, 0.0, 0.0, 0.0, 2.0, 11))
        got = plan.check_upscale({"url": "https://r2.example/c.mp4", "lines": 5000, "seconds": 99, "fps": 12,
                                  "sparse": 9, "local_range": 9, "start": "nan"})
        self.assertEqual((got["lines"], got["seconds"], got["fps"], got["sparse"], got["local_range"], got["start"]),
                         (2160, plan.UPSCALE_MAX_SECONDS, 0.0, 2.5, 9, 0.0))
        self.assertEqual(plan.check_upscale({"url": "https://x/c.mp4", "fps": 60})["fps"], 60.0)
        self.assertTrue(plan.check_upscale({"url": "https://x/c.mp4"})["text_guard"])
        self.assertFalse(plan.check_upscale({"url": "https://x/c.mp4", "text_guard": False})["text_guard"])
        for bad in ({"url": "http://x/c.mp4"}, {"url": "file:///c.mp4"}, {}):
            with self.assertRaises(plan.InputError):
                plan.check_upscale(bad)

    def test_interpolate(self):
        got = plan.check_interpolate({"url": "https://x/c.mp4"})
        self.assertEqual((got["fps"], got["scene"], got["seconds"]), (60.0, plan.SCENE_SSIM, 0.0))
        self.assertEqual(plan.check_interpolate({"url": "https://x/c.mp4", "fps": 500, "seconds": 900})["fps"], 120.0)
        self.assertEqual(plan.check_interpolate({"url": "https://x/c.mp4", "seconds": 900})["seconds"],
                         plan.INTERP_MAX_SECONDS)
        with self.assertRaises(plan.InputError):
            plan.check_interpolate({"url": ""})

    def test_music(self):
        got = plan.check_music({"seconds": 75})
        self.assertEqual(got["caption"], plan.MUSIC_DEFAULT_CAPTION)
        self.assertEqual((got["seconds"], got["lufs"], got["steps"], got["lm"], got["bpm"]), (75.0, -27.0, 8, True, 0))
        got = plan.check_music({"seconds": 3600, "caption": "  tense   strings ", "lm": False, "bpm": 20, "lufs": -5})
        self.assertEqual((got["seconds"], got["asked_seconds"], got["caption"], got["lm"], got["bpm"], got["lufs"]),
                         (600.0, 3600.0, "tense strings", False, 0, -10.0))
        self.assertEqual(plan.check_music({"seconds": 4})["seconds"], 10.0)
        self.assertFalse(plan.check_music({"seconds": 30, "lm": "false"})["lm"])
        with self.assertRaises(plan.InputError):
            plan.check_music({"caption": "x"})


class Sizes(unittest.TestCase):
    def test_target_size(self):
        self.assertEqual(plan.target_size(854, 480, 1080), (1920, 1080))     # 16:9 lands exactly
        self.assertEqual(plan.target_size(640, 360, 1080), (1920, 1080))
        self.assertEqual(plan.target_size(640, 480, 1080), (1440, 1080))     # 4:3 keeps its shape
        self.assertEqual(plan.target_size(646, 480, 1080), (1454, 1080))
        self.assertEqual(plan.target_size(480, 854, 1080), (1080, 1920))     # vertical: the width is the short side
        self.assertEqual(plan.target_size(480, 360, 1080), (1440, 1080))
        with self.assertRaises(plan.InputError):
            plan.target_size(0, 480, 1080)

    def test_padded(self):
        self.assertEqual(plan.padded(1080), 1152)
        self.assertEqual(plan.padded(1920), 1920)
        self.assertEqual(plan.padded(1454), 1536)
        self.assertEqual(plan.padded(1080, 64), 1088)

    def test_vsr_frames_returns_every_frame(self):
        for n in range(2, 400):
            f = plan.vsr_frames(n)
            self.assertEqual((f - 1) % 8, 0)
            self.assertGreaterEqual(f - plan.VSR_TAIL, n)
            self.assertLess(f - plan.VSR_TAIL - n, 8 + 21)        # never more than one extra block (min 25)
        self.assertEqual(plan.vsr_frames(180), 185)
        with self.assertRaises(plan.InputError):
            plan.vsr_frames(0)


class Retime(unittest.TestCase):
    def test_30_to_60_interpolates_every_other_frame(self):
        s = plan.retime(150, 30.0, 60.0)
        self.assertEqual(len(s), 300)
        self.assertEqual(s[:4], [(0, 0.0), (0, 0.5), (1, 0.0), (1, 0.5)])
        self.assertEqual(s[-1], (149, 0.0))                     # the last frame is held, never past the end
        self.assertAlmostEqual(plan.interpolated_share(s), 149 / 300, places=3)

    def test_24_and_25_to_60(self):
        s = plan.retime(24, 24.0, 60.0)
        self.assertEqual(len(s), 60)
        self.assertEqual([t for _, t in s[:5]], [0.0, 0.4, 0.8, 0.2, 0.6])
        self.assertEqual([i for i, _ in s[:6]], [0, 0, 0, 1, 1, 2])
        s25 = plan.retime(125, 25.0, 60.0)
        self.assertEqual(len(s25), 300)
        zero = [k for k, (_, t) in enumerate(s25) if t == 0.0]
        self.assertEqual(zero[:3], [0, 12, 24])                 # 25 -> 60: one source frame in every 12

    def test_ntsc_and_same_rate(self):
        s = plan.retime(300, 30000 / 1001, 60.0)
        self.assertEqual(len(s), 600)
        self.assertTrue(all(0 <= i < 300 and 0.0 <= t < 1.0 for i, t in s))
        same = plan.retime(60, 60.0, 60.0)
        self.assertEqual(same, [(k, 0.0) for k in range(60)])
        with self.assertRaises(plan.InputError):
            plan.retime(0, 30.0, 60.0)

    def test_out_key(self):
        self.assertEqual(plan.out_key("abc-123_x", "mp4"), "gputools/out/abc-123_x.mp4")
        self.assertEqual(plan.out_key("../../etc", "mp3"), "gputools/music/etc.mp3")
        self.assertEqual(plan.gpu_dollars(3600, 0.69), 0.69)


if __name__ == "__main__":
    unittest.main()
