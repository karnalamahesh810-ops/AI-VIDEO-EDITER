import unittest
from unittest import mock

from src import config, media


class GoogleVideosRetry(unittest.TestCase):
    def test_a_non_json_serp_page_is_retried_once(self):
        bad = mock.Mock(status_code=200, text="<html>busy</html>"); bad.raise_for_status = lambda: None
        bad.json.side_effect = ValueError("Expecting value")
        good = mock.Mock(status_code=200); good.raise_for_status = lambda: None
        good.json.return_value = {"organic": [{"link": "https://www.youtube.com/watch?v=EWQT3VwOgvA", "title": "t", "duration": "1:33"}]}
        media.reset_cache()
        with mock.patch.object(config, "BRIGHTDATA_API_KEY", "k"), mock.patch.object(config, "BRIGHTDATA_SERP_ZONE", "z"), \
                mock.patch.object(media.requests, "post", side_effect=[bad, good]) as post, \
                mock.patch.object(media.time, "sleep"):
            rows = media.search_google_videos("Lake Mead bathtub ring")
        self.assertEqual([r["site"] for r in rows], ["youtube.com"])
        self.assertEqual(post.call_count, 2)

    def test_two_bad_pages_give_up_quietly(self):
        bad = mock.Mock(status_code=200, text="<html>busy</html>"); bad.raise_for_status = lambda: None
        bad.json.side_effect = ValueError("Expecting value")
        media.reset_cache()
        with mock.patch.object(config, "BRIGHTDATA_API_KEY", "k"), mock.patch.object(config, "BRIGHTDATA_SERP_ZONE", "z"), \
                mock.patch.object(media.requests, "post", side_effect=[bad, bad, bad]) as post, \
                mock.patch.object(media.time, "sleep"):
            self.assertEqual(media.search_google_videos("Lake Mead bathtub ring"), [])
        # Three tries with a pause between (ten fan-out parts at once got 212 bad pages in one job).
        self.assertEqual(post.call_count, 3)

    def test_flat_searches_ask_for_twenty_results(self):
        self.assertGreaterEqual(config.YT_SEARCH_RESULTS, 20)


if __name__ == "__main__":
    unittest.main()
