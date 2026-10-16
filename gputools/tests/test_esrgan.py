"""Real-ESRGAN engine checks on the CPU (the image build has torch and the weights but no GPU): the net loads the
official weights strictly and upscales a smooth picture close to bicubic (a wrong layer order or weight mix makes
noise), the light / strong mixes differ, the steadiness mask and the BT.709 YUV conversion. Skipped without torch
or the weights (a laptop)."""
import os
import unittest

import numpy as np

try:
    import torch
    import torch.nn.functional as F
except ImportError:  # pragma: no cover - laptop
    torch = None

W_DIR = os.environ.get("ESRGAN_DIR", "/models/realesrgan")
HAVE_W = os.path.isfile(os.path.join(W_DIR, "realesr-general-x4v3.pth"))


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse < 1e-12 else 10 * np.log10(1.0 / mse)


@unittest.skipIf(torch is None, "no torch")
class Pictures(unittest.TestCase):
    def test_steady_mask(self):
        import esrgan
        a = torch.rand(1, 3, 200, 400)
        self.assertEqual(float(esrgan.steady_mask(a, a.clone()).mean()), 1.0)
        b = a.clone()
        b[:, :, 10:150, 250:380] += 0.5                      # a big change in the second tile of the first row
        m = esrgan.steady_mask(b, a)
        self.assertEqual(m.shape, (1, 1, 200, 400))
        self.assertEqual(float(m[0, 0, 0:192, 192:384].mean()), 0.0)
        self.assertEqual(float(m[0, 0, 0:192, 0:192].mean()), 1.0)
        self.assertEqual(float(m[0, 0, 192:, :].mean()), 1.0)     # the short last row
        c = a + 0.5 / 255.0                                  # half a level everywhere: still
        self.assertEqual(float(esrgan.steady_mask(c, a).mean()), 1.0)

    def test_yuv(self):
        import esrgan
        for rgb, y, u, v in (((1, 1, 1), 235, 128, 128), ((0, 0, 0), 16, 128, 128), ((1, 0, 0), 63, 102, 240),
                             ((0, 0, 1), 32, 240, 118)):
            x = torch.tensor(rgb, dtype=torch.float32)[:, None, None].expand(3, 4, 6)
            out = esrgan.rgb_to_yuv420(x).numpy()
            self.assertEqual(out.size, 4 * 6 * 3 // 2)
            self.assertTrue(abs(int(out[0]) - y) <= 1 and abs(int(out[24]) - u) <= 1 and abs(int(out[30]) - v) <= 1,
                            (rgb, out[0], out[24], out[30]))


@unittest.skipIf(torch is None or not HAVE_W, "no torch or no weights")
class Net(unittest.TestCase):
    def test_smooth_picture_close_to_bicubic(self):
        import esrgan
        yy, xx = np.mgrid[0:48, 0:64].astype(np.float32)
        img = np.stack([0.2 + 0.6 * xx / 64, 0.3 + 0.4 * yy / 48, 0.5 + 0.2 * np.sin(xx / 9.0)])
        x = torch.from_numpy(img)[None]
        ref = F.interpolate(x, scale_factor=4, mode="bicubic", align_corners=False).clamp(0, 1)
        outs = {}
        for name in ("light", "strong"):
            net = esrgan.build(esrgan.plan.ESRGAN_STRENGTH[name], "cpu", weights_dir=W_DIR)
            with torch.inference_mode():
                y = net(x.contiguous(memory_format=torch.channels_last)).clamp(0, 1)
            self.assertEqual(tuple(y.shape), (1, 3, 192, 256))
            inner = (slice(None), slice(None), slice(16, -16), slice(16, -16))
            self.assertGreater(psnr(y[inner].numpy(), ref[inner].numpy()), 30.0, name)
            outs[name] = y
        self.assertGreater(float((outs["light"] - outs["strong"]).abs().max()), 1e-4)


if __name__ == "__main__":
    unittest.main()
