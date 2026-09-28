import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, render


def _clip(seconds=4):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=d={seconds}", "-shortest", "-c:v", "libx264", "-crf", "0",
                    "-c:a", "aac", path], check=True)
    return path


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class FitSize(unittest.TestCase):
    def test_a_render_over_the_cap_is_reencoded_under_it(self):
        path = _clip()
        before = os.path.getsize(path)
        cap_mb = before / 1024 / 1024 / 4
        self.assertTrue(render.fit_size(path, cap_mb))
        self.assertLess(os.path.getsize(path), cap_mb * 1024 * 1024)
        streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                  path], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(streams), ["audio", "video"])
        self.assertAlmostEqual(render.probe_duration(path), 4.0, delta=0.3)

    def test_a_render_under_the_cap_is_left_alone(self):
        path = _clip()
        before = os.path.getsize(path)
        self.assertFalse(render.fit_size(path, before / 1024 / 1024 * 2))
        self.assertEqual(os.path.getsize(path), before)
        self.assertFalse(render.fit_size(path, 0))


class RenderQuality(unittest.TestCase):
    def _argv(self, **kw):
        seen = {}

        def fake_run(cmd, **k):
            seen["cmd"] = cmd
            raise RuntimeError("stop")

        d = tempfile.mkdtemp()
        with mock.patch.object(render.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(render, "_run_streaming", side_effect=fake_run, create=True), \
                mock.patch.object(render.templates, "sfx_files", return_value=set()):
            try:
                render.render({"scenes": [], "sfx": []}, os.path.join(d, "out.mp4"), **kw)
            except Exception:  # noqa: BLE001
                pass
        return seen.get("cmd") or []

    def test_video_renders_ask_for_the_configured_crf_and_audio_renders_do_not(self):
        with mock.patch.object(config, "RENDER_CRF", 21):
            self.assertIn("--crf=21", self._argv())
            self.assertNotIn("--crf=21", self._argv(codec="aac"))
        with mock.patch.object(config, "RENDER_CRF", 0):
            self.assertFalse([a for a in self._argv() if str(a).startswith("--crf")])


if __name__ == "__main__":
    unittest.main()
