import unittest
from unittest import mock

from src import config, media


class GoogleVideos(unittest.TestCase):
    def test_youtube_hits_from_google_join_the_candidate_list(self):
        organic = [{"link": "https://www.youtube.com/watch?v=EWQT3VwOgvA", "title": "Lake Mead Time Lapse", "duration": "1:33"},
                   {"link": "https://www.tiktok.com/@x/video/1", "title": "tiktok", "duration": "1:01"},
                   {"link": "https://www.youtube.com/watch?v=AAAAAAAAAAA&vl=pt", "title": "dup", "duration_sec": 90}]
        resp = mock.Mock(status_code=200); resp.json.return_value = {"organic": organic}; resp.raise_for_status = lambda: None
        media.reset_cache()
        with mock.patch.object(config, "BRIGHTDATA_API_KEY", "k"), mock.patch.object(config, "BRIGHTDATA_SERP_ZONE", "z"), \
                mock.patch.object(media.requests, "post", return_value=resp) as post, \
                mock.patch.object(media, "_yt_candidates", return_value=[{"id": "AAAAAAAAAAA", "duration": 90, "aspect": 1.78, "title": "direct", "channel": "c"}]):
            found = media._yt_candidates_cached("ytsearch20:Lake Mead drought aerial footage", False, "Lake Mead", variant="v")
            again = media.search_google_videos("Lake Mead drought aerial footage")
        self.assertEqual([c["id"] for c in found], ["AAAAAAAAAAA", "EWQT3VwOgvA"])   # Google adds, never duplicates
        self.assertEqual(found[1]["duration"], 93.0)
        self.assertEqual(found[1]["via"], "google")
        self.assertEqual(post.call_count, 1)                                        # cached per query
        self.assertEqual([r["site"] for r in again], ["youtube.com", "tiktok.com", "youtube.com"])

    def test_creative_commons_searches_skip_google(self):
        with mock.patch.object(config, "BRIGHTDATA_API_KEY", "k"), \
                mock.patch.object(media, "_yt_candidates", return_value=[]), \
                mock.patch.object(media, "search_google_videos", side_effect=AssertionError("must not be called")):
            self.assertEqual(media._yt_candidates_cached("https://www.youtube.com/results?search_query=x&sp=EgIwAQ%3D%3D", True), [])


if __name__ == "__main__":
    unittest.main()
