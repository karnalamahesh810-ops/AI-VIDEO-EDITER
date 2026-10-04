import time
import unittest
from unittest import mock

from src import config, director, vision


class HedgedDirectorCalls(unittest.TestCase):
    """A silent planning model must not hold the video: the next one is asked in parallel."""

    def setUp(self):
        vision.reset()
        self.patches = [mock.patch.object(config, "DIRECTOR_API_BASE", "https://api.kie.ai/v1"),
                        mock.patch.object(config, "DIRECTOR_API_KEY", "k"),
                        mock.patch.object(config, "DIRECTOR_MODEL", "slow"),
                        mock.patch.object(config, "DIRECTOR_FALLBACK_MODELS", ["fast"]),
                        mock.patch.object(config, "AI_FALLBACK_API_BASE", ""),
                        mock.patch.object(config, "DIRECTOR_HEDGE_SECONDS", 0.2)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        vision.reset()

    def _reply(self, text):
        r = mock.Mock(status_code=200)
        r.json.return_value = {"choices": [{"message": {"content": text}}]}
        return r

    def test_a_slow_model_is_overtaken_by_the_next(self):
        def post(url, json=None, **kw):
            if json["model"] == "slow":
                time.sleep(2.0)
                return self._reply('{"from": "slow"}')
            return self._reply('{"from": "fast"}')

        t = time.time()
        with mock.patch.object(director.requests, "post", side_effect=post):
            self.assertEqual(director._chat_json("sys", {}), {"from": "fast"})
        self.assertLess(time.time() - t, 1.5)

    def test_a_timeout_is_retried_with_backoff_then_the_next_model_answers(self):
        seen = []

        def post(url, json=None, **kw):
            seen.append(json["model"])
            if json["model"] == "slow":
                raise director.requests.Timeout("read timed out")
            return self._reply('{"ok": 1}')

        # DIRECTOR_RETRIES (2, since 2026-10-05; it was one retry): three tries on the slow model.
        with mock.patch.object(config, "DIRECTOR_HEDGE_SECONDS", 30), \
                mock.patch.object(config, "DIRECTOR_RETRIES", 2), \
                mock.patch.object(director.time, "sleep"), \
                mock.patch.object(director.requests, "post", side_effect=post):
            self.assertEqual(director._chat_json("sys", {}), {"ok": 1})
        self.assertEqual(seen, ["slow", "slow", "slow", "fast"])

    def test_the_story_brief_gets_the_long_timeout(self):
        timeouts = []

        def post(url, json=None, timeout=None, **kw):
            timeouts.append(timeout)
            return self._reply('{"kind": "news", "summary": "x"}')

        segs = [director.Segment(text="The gauge at Glen Canyon Dam fell again.", start=0.0, end=4.0)]
        with mock.patch.object(config, "BRIEF_TIMEOUT", 240), \
                mock.patch.object(director.requests, "post", side_effect=post):
            director.story_brief(segs, "Glen Canyon")
        self.assertEqual(timeouts[0], 240)


if __name__ == "__main__":
    unittest.main()
