import unittest
from unittest import mock

from src import config, media


class BrightDataOutOfCredit(unittest.TestCase):
    def setUp(self):
        media.reset_cache()
        self.patches = [mock.patch.object(config, "BRIGHTDATA_API_KEY", "k"),
                        mock.patch.object(config, "BRIGHTDATA_SERP_ZONE", "z"),
                        mock.patch.object(config, "ALLOW_WEB_IMAGES", True),
                        mock.patch.object(config, "SERPER_API_KEY", "")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        media.reset_cache()

    def test_a_refused_account_is_asked_once_then_images_come_from_duckduckgo(self):
        refused = mock.Mock(status_code=402, text='{"error":"insufficient balance"}')
        calls = []

        def post(url, **kw):
            calls.append(url)
            return refused

        ddg_rows = [{"image": "https://example.org/dam.jpg", "width": 1600, "height": 900,
                     "title": "Glen Canyon Dam", "url": "https://example.org"}]
        fake_ddgs = mock.MagicMock()
        fake_ddgs.return_value.__enter__.return_value.images.return_value = ddg_rows
        with mock.patch.object(media.requests, "post", side_effect=post), \
                mock.patch.dict("sys.modules", {"ddgs": mock.Mock(DDGS=fake_ddgs)}), \
                mock.patch.object(media, "_next_proxy", return_value=None):
            first = media.search_web_images("glen canyon dam", limit=2)
            second = media.search_web_images("lake powell", limit=2)
            self.assertEqual(media.search_google_videos("lake powell drone"), [])
        self.assertEqual(len(calls), 1)                  # asked once, never again this job
        self.assertEqual([a.url for a in first], ["https://example.org/dam.jpg"])
        self.assertEqual(len(second), 1)
        self.assertFalse(media.brightdata_available())
        media.reset_cache()
        self.assertTrue(media.brightdata_available())    # the next job tries again


if __name__ == "__main__":
    unittest.main()
