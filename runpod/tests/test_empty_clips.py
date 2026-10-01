import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import handler
from src import config, media


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


class HlsConnectionReuse(unittest.TestCase):
    def test_an_hls_reuse_failure_is_fetched_again_without_reuse(self):
        d = tempfile.mkdtemp()
        stub = os.path.join(d, "yt_abc_1_2_x.mp4"); _stub_mp4(stub)
        good = os.path.join(d, "yt_abc_1_2_y.mp4"); _stub_mp4(good)
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                return SimpleNamespace(returncode=0, stdout=stub + "\n",
                                       stderr="Cannot reuse HTTP connection for different host: a != b")
            return SimpleNamespace(returncode=0, stdout=good + "\n", stderr="")

        from src import ytdlp
        with mock.patch.object(media.subprocess, "run", side_effect=run), \
                mock.patch.object(ytdlp, "_acquire_proxy", return_value="http://u:p@h:1"), \
                mock.patch.object(ytdlp, "_release_proxy") as release, \
                mock.patch.object(ytdlp, "playable_video", side_effect=lambda p: p == good):
            self.assertEqual(ytdlp._yt_fetch("abc", d, 1.0, 2.0), good)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("-http_persistent 0", " ".join(calls[0]))
        self.assertIn("ffmpeg_i:-loglevel error -http_persistent 0 -http_proxy http://u:p@h:1", calls[1])
        self.assertTrue(all(c.args[1] for c in release.call_args_list))   # never the proxy's fault
        self.assertFalse(os.path.exists(stub))


class SanitizeVideos(unittest.TestCase):
    def test_stub_scene_is_blanked_then_covered(self):
        d = tempfile.mkdtemp()
        stub = os.path.join(d, "s0.mp4"); _stub_mp4(stub)
        good = os.path.join(d, "s1.mp4"); _stub_mp4(good)
        doc = {"fps": 30, "scenes": [
            {"id": "s0000", "startFrame": 0, "durationInFrames": 90, "text": "first",
             "media": {"type": "video", "url": stub, "source": "youtube"}, "semanticMetadata": {"subject": "Lake Mead"}},
            {"id": "s0001", "startFrame": 90, "durationInFrames": 90, "text": "second",
             "media": {"type": "video", "url": good, "source": "youtube", "clipSeconds": 6.0},
             "semanticMetadata": {"subject": "Lake Mead"}},
        ], "overlays": []}
        with mock.patch.object(media, "playable_video", side_effect=lambda p: p == good):
            with mock.patch.object(config, "ANIMATION_FILL", False):      # the hold, not a graphic
                dropped = handler._sanitize_videos(doc)
        self.assertEqual(dropped, 1)
        # Covered without a repeat (the owner, 2026-10-01): the good clip is
        # held over the stub's line - one scene, never the same clip twice.
        self.assertEqual([s["media"]["url"] for s in doc["scenes"]], [good])
        self.assertEqual((doc["scenes"][0]["startFrame"], doc["scenes"][0]["durationInFrames"]), (0, 180))
        self.assertTrue(doc["scenes"][0]["reviewRequired"])
        self.assertEqual(doc["scenes"][0]["text"], "first second")


if __name__ == "__main__":
    unittest.main()
