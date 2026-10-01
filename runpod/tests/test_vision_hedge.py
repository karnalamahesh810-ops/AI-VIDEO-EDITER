import time
import unittest
from unittest import mock

from src import config, costs, vision


class HedgedVisionCalls(unittest.TestCase):
    """A stalled model must not hold a scene: the backup is asked in parallel."""

    def setUp(self):
        vision.reset()
        self.patches = [mock.patch.object(config, "VISION_API_KEY", "k"),
                        mock.patch.object(config, "VISION_ENABLED", True),
                        mock.patch.object(config, "VISION_MODEL", "main"),
                        mock.patch.object(config, "VISION_FALLBACK_MODELS", ["backup"]),
                        mock.patch.object(config, "VISION_RETRY_WAIT", 0),
                        mock.patch.object(config, "VISION_HEDGE_SECONDS", 0.2),
                        mock.patch.object(config, "VISION_CALL_BUDGET_SECONDS", 5)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        vision.reset()

    def test_a_slow_model_is_overtaken_by_the_backup(self):
        def ask_once(model, messages, max_tokens, url="", key="", main=True):
            if model == "main":
                time.sleep(2.0)
                return '{"from": "main"}', False
            return '{"from": "backup"}', False

        before = costs.summary()["units"].get("vision.hedge", 0)
        t = time.time()
        with mock.patch.object(vision, "_ask_once", side_effect=ask_once):
            text, model = vision._ask([], 100)
        self.assertEqual((text, model), ('{"from": "backup"}', "backup"))
        self.assertLess(time.time() - t, 1.5)
        self.assertEqual(costs.summary()["units"].get("vision.hedge", 0), before + 1)

    def test_a_fast_answer_asks_no_backup(self):
        seen = []

        def ask_once(model, messages, max_tokens, url="", key="", main=True):
            seen.append(model)
            return '{"ok": 1}', False

        with mock.patch.object(vision, "_ask_once", side_effect=ask_once):
            self.assertEqual(vision._ask([], 100), ('{"ok": 1}', "main"))
        self.assertEqual(seen, ["main"])

    def test_the_call_gives_up_at_its_budget(self):
        def ask_once(model, messages, max_tokens, url="", key="", main=True):
            time.sleep(3.0)
            return '{"late": 1}', False

        t = time.time()
        with mock.patch.object(config, "VISION_CALL_BUDGET_SECONDS", 0.6), \
                mock.patch.object(vision, "_ask_once", side_effect=ask_once):
            self.assertEqual(vision._ask([], 100), (None, ""))
        self.assertLess(time.time() - t, 1.5)

    def test_a_failed_model_hands_over_at_once(self):
        def ask_once(model, messages, max_tokens, url="", key="", main=True):
            if model == "main":
                return None, False
            return '{"ok": 2}', False

        t = time.time()
        with mock.patch.object(config, "VISION_HEDGE_SECONDS", 10), \
                mock.patch.object(vision, "_ask_once", side_effect=ask_once):
            self.assertEqual(vision._ask([], 100), ('{"ok": 2}', "backup"))
        self.assertLess(time.time() - t, 1.0)

    def test_an_unusable_answer_hands_over_to_the_next_model(self):
        # 2026-10-01: Kie answered in prose ("daylight street scene showing...")
        # 278 times on one job; each left its clip unjudged. Now the next model
        # is asked, in both the hedged and the one-at-a-time loop.
        def ask_once(model, messages, max_tokens, url="", key="", main=True):
            if model == "main":
                return " daylight street scene showing several cars", False
            return '{"score": 0.9}', False

        for hedge in (10, 0):
            with mock.patch.object(config, "VISION_HEDGE_SECONDS", hedge), \
                    mock.patch.object(vision, "_ask_once", side_effect=ask_once):
                self.assertEqual(vision._ask([], 100, accept=lambda t: t.startswith("{")),
                                 ('{"score": 0.9}', "backup"))
                # Without a check the first answer is still taken as it was.
                self.assertEqual(vision._ask([], 100)[1], "main")

    def test_the_judge_asks_for_json_only_and_rejects_prose(self):
        with mock.patch.object(vision, "sample_frames", return_value=["AAAA"]), \
                mock.patch.object(vision.os.path, "exists", return_value=True), \
                mock.patch.object(vision, "_fingerprint", return_value="fp"), \
                mock.patch.object(vision, "_ask", return_value=(None, "")) as ask:
            self.assertIsNone(vision.judge("clip.mp4", "flooding in Texas"))
        messages, _tokens = ask.call_args[0][:2]
        text = messages[1]["content"][0]["text"]
        self.assertIn("ONLY the JSON object", text)
        accept = ask.call_args[1]["accept"]
        self.assertFalse(accept(" frames show large hippopotamuses"))
        self.assertTrue(accept('{"description": "flooded street", "score": 0.8}'))



class OpenRouterSettings(unittest.TestCase):
    """OpenRouter's own reasoning switch: Gemini 2.5 Flash without thinking, 3.x at minimal, GPT-5 minimal."""

    URL = "https://openrouter.ai/api/v1/chat/completions"

    def test_gemini_25_flash_does_not_think(self):
        self.assertEqual(vision._extra("google/gemini-2.5-flash", self.URL, 400), (400, {"reasoning": {"max_tokens": 0}}))

    def test_gemini_3_flash_gets_room_to_think(self):
        budget, extra = vision._extra("google/gemini-3.8-flash", self.URL, 400)
        self.assertEqual((budget, extra), (800, {"reasoning": {"effort": "minimal"}}))

    def test_gpt5_mini_reasons_minimally(self):
        self.assertEqual(vision._extra("openai/gpt-5-mini", self.URL, 300), (300, {"reasoning": {"effort": "minimal"}}))

    def test_the_endpoint_is_the_base_path(self):
        with mock.patch.object(config, "VISION_API_BASE", "https://openrouter.ai/api/v1"):
            self.assertEqual(vision._endpoint("google/gemini-2.5-flash"), self.URL)


if __name__ == "__main__":
    unittest.main()
