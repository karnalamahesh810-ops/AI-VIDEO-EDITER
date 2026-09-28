import os
import re
import shutil
import subprocess
import tempfile
import unittest

from src import render


def _lufs(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", p.stderr)
    return float(m[-1]) if m else None


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class Loudness(unittest.TestCase):
    def _clip(self, volume_db):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "v.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=6",
                        "-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:a=0.5", "-af", f"volume={volume_db}dB",
                        "-shortest", "-c:v", "libx264", "-c:a", "aac", path], check=True)
        return path

    def test_a_quiet_render_is_brought_to_youtube_loudness(self):
        path = self._clip(-24)
        self.assertLess(_lufs(path), -24)
        self.assertTrue(render.normalize_loudness(path, -14.0))
        self.assertAlmostEqual(_lufs(path), -14.0, delta=1.0)
        streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                  path], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(streams), ["audio", "video"])

    def test_off_when_the_target_is_zero(self):
        path = self._clip(-24)
        before = os.path.getsize(path)
        self.assertFalse(render.normalize_loudness(path, 0))
        self.assertEqual(os.path.getsize(path), before)


if __name__ == "__main__":
    unittest.main()
