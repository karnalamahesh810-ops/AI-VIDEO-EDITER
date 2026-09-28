import unittest
from unittest import mock

from src import config, media, vision


def _refused(*a, **k):
    r = mock.Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"code": 402, "msg": "Credits insufficient"}
    return r


class ImageAccountAlone(unittest.TestCase):
    def setUp(self):
        media.reset_cache()

    def tearDown(self):
        media.reset_cache()

    def _generate(self, vision_base, director_base):
        with mock.patch.object(config, "IMAGE_API_BASE", "https://api.kie.ai/api/v1"), \
                mock.patch.object(config, "IMAGE_API_KEY", "k"), \
                mock.patch.object(config, "VISION_API_BASE", vision_base), \
                mock.patch.object(config, "DIRECTOR_API_BASE", director_base), \
                mock.patch.object(media.requests, "post", side_effect=_refused) as post:
            self.assertIsNone(media.generate_image("Lake Powell at dawn", "/tmp/imgcredit"))
            self.assertIsNone(media.generate_image("Glen Canyon Dam", "/tmp/imgcredit"))
            return post.call_count

    def test_an_empty_image_account_does_not_stop_vision_on_another_provider(self):
        google = "https://generativelanguage.googleapis.com/v1beta/openai"
        calls = self._generate(google, google)
        self.assertFalse(vision.out_of_credits())
        self.assertEqual(calls, 1, "the second image must not ask the empty account again")

    def test_the_same_empty_account_behind_vision_stops_it(self):
        self._generate("https://api.kie.ai/v1", "https://api.kie.ai/v1")
        self.assertTrue(vision.out_of_credits())


if __name__ == "__main__":
    unittest.main()
