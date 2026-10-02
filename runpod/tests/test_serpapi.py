"""SerpApi as the quota-limited backup picture search (media._serpapi_images)."""
import unittest
from unittest import mock

from src import config, media


def _resp(results):
    r = mock.Mock(status_code=200)
    r.raise_for_status = mock.Mock()
    r.json = mock.Mock(return_value={"images_results": results})
    return r


class SerpApi(unittest.TestCase):
    def setUp(self):
        media._SERPAPI_USED["n"] = 0
        self.p = mock.patch.multiple(config, SERPAPI_API_KEY="k", SERPAPI_MAX_PER_JOB=2)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        media._SERPAPI_USED["n"] = 0

    def test_rows_skip_social_crawler_links(self):
        res = [{"original": "https://lookaside.fbsbx.com/x", "original_width": 2000, "original_height": 1500},
               {"original": "https://pix11.com/a.jpg", "original_width": 1920, "original_height": 1080,
                "title": "Flooding", "link": "https://pix11.com/story"}]
        with mock.patch.object(media.requests, "get", return_value=_resp(res)) as get:
            rows = media._serpapi_images("google_images", "Long Beach Island flooding")
        self.assertEqual(rows, [("https://pix11.com/a.jpg", 1920, 1080, "Flooding", "https://pix11.com/story", "")])
        self.assertEqual(get.call_args.kwargs["params"]["engine"], "google_images")

    def test_the_per_job_budget_is_kept(self):
        with mock.patch.object(media.requests, "get", return_value=_resp([])) as get:
            for _ in range(5):
                media._serpapi_images("google_images", "x")
        self.assertEqual(get.call_count, 2)

    def test_unconfigured_does_nothing(self):
        with mock.patch.object(config, "SERPAPI_API_KEY", ""), mock.patch.object(media.requests, "get") as get:
            self.assertEqual(media._serpapi_images("google_images", "x"), [])
        get.assert_not_called()

    def test_yandex_captcha_falls_back_to_serpapi(self):
        captcha = mock.Mock(url="https://yandex.com/showcaptcha?x", text="")
        with mock.patch.object(media.requests, "get", side_effect=[captcha, _resp([
                {"original": "https://static.independent.co.uk/p.jpg"}])]), \
                mock.patch.object(media, "_next_proxy", return_value=None):
            got = media.search_yandex_images("nor'easter flooding")
        self.assertEqual([a.url for a in got], ["https://static.independent.co.uk/p.jpg"])


if __name__ == "__main__":
    unittest.main()
