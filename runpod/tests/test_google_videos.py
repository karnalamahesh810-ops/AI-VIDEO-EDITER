import unittest
from unittest import mock

from src import config, media


class GoogleVideos(unittest.TestCase):
    def test_youtube_hits_from_google_join_the_candidate_list(self):
        results = [{"link": "https://www.youtube.com/watch?v=EWQT3VwOgvA", "title": "Lake Mead Time Lapse", "duration": "1:33"},
                   {"link": "https://www.tiktok.com/@x/video/1", "title": "tiktok", "duration": "1:01"},
                   {"link": "https://www.youtube.com/watch?v=AAAAAAAAAAA&vl=pt", "title": "dup", "duration": "1:30"}]
        resp = mock.Mock(status_code=200); resp.json.return_value = {"video_results": results}; resp.raise_for_status = lambda: None
        media.reset_cache()
        with mock.patch.object(config, "SERPAPI_API_KEY", "k"), mock.patch.object(config, "SERPAPI_VIDEO_MAX_PER_JOB", 3), \
                mock.patch.object(media.requests, "get", return_value=resp) as get, \
                mock.patch.object(media, "_yt_candidates", return_value=[{"id": "AAAAAAAAAAA", "duration": 90, "aspect": 1.78, "title": "direct", "channel": "c"}]):
            found = media._yt_candidates_cached("ytsearch20:Lake Mead drought aerial footage", False, "Lake Mead", variant="v")
            again = media.search_google_videos("Lake Mead drought aerial footage")
        self.assertEqual([c["id"] for c in found], ["AAAAAAAAAAA", "EWQT3VwOgvA"])   # Google adds, never duplicates
        self.assertEqual(found[1]["duration"], 93.0)
        self.assertEqual(found[1]["via"], "google")
        self.assertEqual(get.call_count, 1)                                         # cached per query
        self.assertEqual([r["site"] for r in again], ["youtube.com", "tiktok.com", "youtube.com"])

    def test_creative_commons_searches_skip_google(self):
        with mock.patch.object(config, "SERPAPI_API_KEY", "k"), \
                mock.patch.object(media, "_yt_candidates", return_value=[]), \
                mock.patch.object(media, "search_google_videos", side_effect=AssertionError("must not be called")):
            self.assertEqual(media._yt_candidates_cached("https://www.youtube.com/results?search_query=x&sp=EgIwAQ%3D%3D", True), [])

    def test_without_a_search_key_nothing_is_asked(self):
        # Bright Data is gone (2026-10-04): without SerpApi there is no Google Videos search at all.
        media.reset_cache()
        with mock.patch.object(config, "SERPAPI_API_KEY", ""), \
                mock.patch.object(media.requests, "get") as get, mock.patch.object(media.requests, "post") as post:
            self.assertEqual(media.search_google_videos("Lake Mead drought aerial footage"), [])
        get.assert_not_called()
        post.assert_not_called()

    def test_a_used_up_month_stops_the_calls_for_the_job(self):
        import requests
        resp = mock.Mock(status_code=429)
        resp.raise_for_status.side_effect = requests.HTTPError("429 Client Error: Too Many Requests for url: x")
        media.reset_cache()
        with mock.patch.object(config, "SERPAPI_API_KEY", "k"), mock.patch.object(config, "SERPAPI_VIDEO_MAX_PER_JOB", 5), \
                mock.patch.object(media.requests, "get", return_value=resp) as get:
            for q in ("a b", "c d", "e f"):
                self.assertEqual(media.search_google_videos(q), [])
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
