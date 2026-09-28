import unittest
from unittest import mock

from src import config, media, vision


class NewsFootage(unittest.TestCase):
    """News reports are used as they are, GoMotion-style; junk still is not."""

    def test_the_judge_welcomes_news_banners_and_logos(self):
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            s = vision._system()
        self.assertIn("TV NEWS FOOTAGE IS WELCOME", s)
        self.assertNotIn("a channel logo in a corner", s)
        self.assertIn("news anchor at a studio desk", s)
        self.assertIn("QR code", s)
        with mock.patch.object(config, "NEWS_FOOTAGE", False):
            self.assertIn("a channel logo in a corner", vision._system())

    def test_titles_of_news_reports_pass_but_podcasts_do_not(self):
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            self.assertFalse(media._talking_head("Lake Powell drops below 3,500 feet | ABC7 News"))
            self.assertFalse(media._talking_head("Gov. Hobbs press conference on the Colorado River"))
            self.assertTrue(media._talking_head("Colorado River podcast episode 12"))
            self.assertTrue(media._talking_head("Lake Mead gameplay speedrun"))
        with mock.patch.object(config, "NEWS_FOOTAGE", False), mock.patch.object(media, "_EVENT_WINDOW") as ev:
            ev.get.return_value = ""
            self.assertTrue(media._talking_head("Lake Powell drops below 3,500 feet | ABC7 News"))


if __name__ == "__main__":
    unittest.main()
