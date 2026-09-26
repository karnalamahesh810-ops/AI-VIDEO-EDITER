import unittest
from unittest import mock

from src import media


class YouTubeOnly(unittest.TestCase):
    def tearDown(self):
        media.set_youtube_only(False)

    def test_nothing_but_youtube_is_tried_and_stills_become_footage(self):
        calls = []

        def yt(query, work_dir, **kw):
            calls.append(("youtube", query))
            return None

        def never(*a, **k):
            calls.append(("other", a[0] if a else ""))
            return None
        media.set_youtube_only(True)
        with mock.patch.object(media, "youtube_clip", yt), \
                mock.patch.object(media, "dailymotion_clip", never), \
                mock.patch.object(media, "search_wikimedia_video", never), \
                mock.patch.object(media, "search_nasa_video", never), \
                mock.patch.object(media, "search_web_images", never), \
                mock.patch.object(media, "search_wikimedia", never), \
                mock.patch.object(media, "generate_image", never), \
                mock.patch.object(media.config, "REQUIRE_AI", False):
            got = media._source_one("Lake Mead", 6.0, "/w", visual_type="image", allow_youtube=False)
        self.assertIsNone(got)
        self.assertEqual(calls, [("youtube", "Lake Mead")])   # an "image" scene became a footage search

    def test_off_by_default(self):
        self.assertFalse(media.youtube_only())


if __name__ == "__main__":
    unittest.main()
