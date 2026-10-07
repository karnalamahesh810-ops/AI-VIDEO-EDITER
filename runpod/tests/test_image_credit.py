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
        # How a Kie image account behaves when Kie is on (it is off by default since 2026-10-07: KieOff below).
        with mock.patch.object(config, "KIE_ENABLED", True),                 mock.patch.object(config, "IMAGE_API_BASE", "https://api.kie.ai/api/v1"), \
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


class KieOff(unittest.TestCase):
    """The owner, 2026-10-07: Kie is off for good. A template still carrying Kie's image base (and its key) never
    calls it, nothing is counted, and no line plans on a generated picture."""

    def setUp(self):
        media.reset_cache()

    def tearDown(self):
        media.reset_cache()

    def test_a_kie_image_base_is_never_called(self):
        with mock.patch.object(config, "IMAGE_API_BASE", "https://api.kie.ai/api/v1"),                 mock.patch.object(config, "IMAGE_API_KEY", "k"),                 mock.patch.object(media.requests, "post", side_effect=_refused) as post:
            self.assertFalse(media.image_generation_available())
            from src import costs
            costs.reset()
            media._generation_budget_left()             # an attempt is allowed, but nothing can draw it:
            self.assertIsNone(media.generate_image("Lake Powell at dawn", "/tmp/imgcredit"))
            self.assertNotIn("image.generate", costs.summary()["units"])     # no Kie-credit estimate either
        self.assertEqual(post.call_count, 0)

    def test_openrouter_draws_the_picture(self):
        import base64
        png = base64.b64encode(b"PNG-fake").decode()

        def answer(url, json=None, **kw):
            self.assertTrue(url.startswith("https://openrouter.ai/api/v1/chat/completions"))
            self.assertEqual(json["modalities"], ["image", "text"])
            r = mock.Mock(status_code=200)
            r.json.return_value = {"choices": [{"message": {"content": "", "images": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}}]}}],
                "usage": {"cost": 0.039}}
            return r

        import tempfile
        out = tempfile.mkdtemp()
        with mock.patch.object(config, "IMAGE_API_BASE", "https://openrouter.ai/api/v1"),                 mock.patch.object(config, "IMAGE_API_KEY", "k"),                 mock.patch.object(config, "IMAGE_MODEL", "google/gemini-2.5-flash-image"),                 mock.patch.object(media.requests, "post", side_effect=answer):
            self.assertTrue(media.image_generation_available())
            got = media.generate_image("Lake Powell at dawn", out)
        self.assertIsNotNone(got)
        self.assertEqual(open(got.local_path, "rb").read(), b"PNG-fake")
        self.assertTrue(got.review_required)


if __name__ == "__main__":
    unittest.main()
