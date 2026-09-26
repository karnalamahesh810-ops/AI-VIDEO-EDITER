import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import handler
from src import media


def _stub_mp4(path: str) -> None:
    """A 262-byte MP4 shell: header, no frames (what a dropped stream leaves)."""
    with open(path, "wb") as fh:
        fh.write(b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 234)


def _real_mp4(path: str) -> bool:
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1",
                        "-pix_fmt", "yuv420p", path], capture_output=True)
    return p.returncode == 0 and os.path.getsize(path) > 0


class PlayableVideo(unittest.TestCase):
    def test_stub_is_rejected_and_real_clip_accepted(self):
        d = tempfile.mkdtemp()
        stub = os.path.join(d, "stub.mp4"); _stub_mp4(stub)
        self.assertFalse(media.playable_video(stub))
        real = os.path.join(d, "real.mp4")
        if _real_mp4(real):
            self.assertTrue(media.playable_video(real))

    def test_fetch_drops_a_frameless_download_so_the_retry_runs(self):
        d = tempfile.mkdtemp()
        stub = os.path.join(d, "yt_abc_1_2_x.mp4"); _stub_mp4(stub)
        result = SimpleNamespace(returncode=0, stdout=stub + "\n", stderr="")
        with mock.patch.object(media.subprocess, "run", return_value=result), \
                mock.patch.object(media, "_next_proxy", return_value=""), \
                mock.patch.object(media, "playable_video", return_value=False):
            self.assertEqual(media._yt_fetch("abc", d, 1.0, 2.0), "")
        self.assertFalse(os.path.exists(stub))


class SanitizeVideos(unittest.TestCase):
    def test_stub_scene_is_blanked_then_covered(self):
        d = tempfile.mkdtemp()
        stub = os.path.join(d, "s0.mp4"); _stub_mp4(stub)
        good = os.path.join(d, "s1.mp4"); _stub_mp4(good)
        doc = {"scenes": [
            {"id": "s0000", "media": {"type": "video", "url": stub, "source": "youtube"}, "semanticMetadata": {"subject": "Lake Mead"}},
            {"id": "s0001", "media": {"type": "video", "url": good, "source": "youtube"}, "semanticMetadata": {"subject": "Lake Mead"}},
        ], "overlays": []}
        with mock.patch.object(media, "playable_video", side_effect=lambda p: p == good):
            dropped = handler._sanitize_videos(doc)
        self.assertEqual(dropped, 1)
        self.assertEqual(doc["scenes"][0]["media"]["url"], good)        # covered by the good clip
        self.assertTrue(doc["scenes"][0]["reviewRequired"])
        self.assertEqual(doc["scenes"][1]["media"]["url"], good)


if __name__ == "__main__":
    unittest.main()
