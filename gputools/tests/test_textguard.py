"""The text guard's masks and blend (textguard.py) with a stand-in detector: no model, no GPU."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import textguard  # noqa: E402


def fake_map(rgb):
    """A 'detector' that marks the red pixels of a frame (as its own 736-short-side map)."""
    h, w = rgb.shape[:2]
    s = textguard.DET_SHORT / float(min(h, w))
    nh, nw = int(round(h * s / 32.0)) * 32, int(round(w * s / 32.0)) * 32
    red = (rgb[..., 0] > 200) & (rgb[..., 1] < 50)
    return textguard._resize_nearest(red.astype(np.float32), nh, nw)


class Guard(unittest.TestCase):
    def setUp(self):
        self._real = textguard.text_map
        textguard.text_map = fake_map

    def tearDown(self):
        textguard.text_map = self._real

    def frames(self, n=30, text_until=15):
        out = []
        for k in range(n):
            f = np.zeros((48, 64, 3), np.uint8)
            if k < text_until:
                f[4:8, 4:30] = (255, 0, 0)          # a "caption" at the top left until a cut
            out.append(f)
        return out

    def test_masks_follow_the_text_and_the_cut(self):
        g = textguard.Guard(self.frames(), fps=10.0, out_hw=(96, 128), feather=2)
        self.assertEqual(g.samples[0], 0)
        self.assertEqual(g.samples[-1], 29)
        m0 = g.mask(0)
        self.assertIsNotNone(m0)
        self.assertEqual(m0.shape, (96, 128))
        self.assertGreater(m0[12, 30], 0.99)                   # inside the caption (scaled x2)
        self.assertLess(m0[80, 110], 0.01)                     # far from it
        self.assertIsNone(g.mask(28))                          # after the cut: no text, no mask
        self.assertTrue(g.any())
        self.assertGreater(g.share, 0.0)

    def test_no_text_no_mask(self):
        g = textguard.Guard(self.frames(text_until=0), fps=30.0, out_hw=(96, 128))
        self.assertFalse(g.any())
        self.assertTrue(all(g.mask(k) is None for k in range(30)))

    def test_blend(self):
        sharp = np.full((4, 4, 3), 200, np.uint8)
        safe = np.full((4, 4, 3), 100, np.uint8)
        m = np.zeros((4, 4), np.float32)
        m[0, 0], m[1, 1] = 1.0, 0.5
        out = textguard.blend(sharp, safe, m)
        self.assertEqual(int(out[0, 0, 0]), 100)
        self.assertEqual(int(out[1, 1, 0]), 150)
        self.assertEqual(int(out[3, 3, 0]), 200)
        self.assertIs(textguard.blend(sharp, safe, None), sharp)

    def test_grow_and_feather(self):
        b = np.zeros((9, 9), bool)
        b[4, 4] = True
        g = textguard._grow(b, 2)
        self.assertEqual(int(g.sum()), 25)
        f = textguard._feather(g.astype(np.float32), 1)
        self.assertEqual(f.shape, (9, 9))
        self.assertGreater(f[4, 4], f[0, 0])
        self.assertLessEqual(float(f.max()), 1.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
