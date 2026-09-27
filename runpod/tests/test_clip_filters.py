import unittest
from unittest import mock

import numpy as np

from src import media


def _moving(seed, h=180, w=320):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (h, w), dtype=np.uint8)


class CornerWatermark(unittest.TestCase):
    def test_static_logo_in_a_corner_of_a_moving_clip_is_caught(self):
        frames = []
        logo = _moving(99)[:28, :70]          # busy, edge-dense block
        for k in range(4):
            f = _moving(k)
            f[:28, -70:] = logo                # same pixels every frame, top-right
            frames.append(f)
        self.assertTrue(media._corner_watermark(frames, np))

    def test_plain_moving_clip_and_static_landscape_pass(self):
        self.assertFalse(media._corner_watermark([_moving(k) for k in range(4)], np))
        still = _moving(5)
        self.assertFalse(media._corner_watermark([still.copy() for _ in range(4)], np))


class Blurry(unittest.TestCase):
    def test_smooth_frames_are_blurry_and_detailed_ones_are_not(self):
        y, x = np.mgrid[0:180, 0:320]
        smooth = [((x + y) / 4 % 255).astype(np.uint8) for _ in range(3)]
        self.assertTrue(media._blurry(smooth, np))
        self.assertFalse(media._blurry([_moving(k) for k in range(3)], np))


class VerticalVideo(unittest.TestCase):
    def test_portrait_clip_is_rejected_by_clip_quality(self):
        frames = [_moving(k) for k in range(4)]
        with mock.patch.object(media.os.path, "exists", return_value=True), \
                mock.patch.object(media, "_gray_frames", return_value=frames), \
                mock.patch.object(media, "_is_still", return_value=False), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_video_dims", return_value=(720, 1280)):
            ok, why = media.clip_quality("/w/vertical.mp4")
        self.assertFalse(ok)
        self.assertEqual(why, "vertical or square video")


if __name__ == "__main__":
    unittest.main()
