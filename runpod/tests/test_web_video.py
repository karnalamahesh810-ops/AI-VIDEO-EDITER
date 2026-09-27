import os
import tempfile
import unittest
from unittest import mock

from src import config, media


class WebVideo(unittest.TestCase):
    def test_non_youtube_google_results_are_fetched_and_gated(self):
        rows = [{"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "title": "yt", "site": "youtube.com", "seconds": 90},
                {"url": "https://www.tiktok.com/@x/video/1", "title": "vertical", "site": "tiktok.com", "seconds": 61},
                {"url": "https://www.facebook.com/EDF/videos/2", "title": "Satellite view of Lake Mead", "site": "facebook.com", "seconds": 22}]
        d = tempfile.mkdtemp()
        fetched = []

        def fetch(url, out_dir, start, seconds, timeout=240):
            fetched.append(url); p = os.path.join(d, f"c{len(fetched)}.mp4"); open(p, "wb").write(b"x"); return p
        dims = {1: (720, 1280), 2: (1280, 720)}
        with mock.patch.object(config, "ALLOW_WEB_VIDEO", True), \
                mock.patch.object(media, "search_google_videos", return_value=rows), \
                mock.patch.object(media, "_web_fetch", fetch), \
                mock.patch.object(media, "_video_dims", side_effect=lambda p: dims[len(fetched)]), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_vision_gate", return_value=(True, {"score": 0.85, "description": "lake", "model": "m"})):
            asset = media.web_video_clip("Lake Mead satellite", d, seconds=6.0, intent="Lake Mead from space", context="x")
        self.assertEqual(fetched, ["https://www.tiktok.com/@x/video/1", "https://www.facebook.com/EDF/videos/2"])  # YouTube skipped
        self.assertIsNotNone(asset)
        self.assertEqual(asset.source, "web_video")                       # the vertical TikTok was dropped
        self.assertEqual(asset.url, "https://www.facebook.com/EDF/videos/2")
        self.assertEqual(asset.identity, "web_video:https://www.facebook.com/EDF/videos/2")

    def test_youtube_only_never_reaches_it(self):
        media.set_youtube_only(True)
        try:
            with mock.patch.object(media, "youtube_clip", return_value=None), \
                    mock.patch.object(media, "web_video_clip", side_effect=AssertionError("must not run")), \
                    mock.patch.object(media.config, "REQUIRE_AI", False):
                self.assertIsNone(media._source_one("x", 6.0, "/w", allow_youtube=True))
        finally:
            media.set_youtube_only(False)


if __name__ == "__main__":
    unittest.main()
