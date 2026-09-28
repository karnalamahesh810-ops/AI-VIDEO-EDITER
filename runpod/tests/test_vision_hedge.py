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


if __name__ == "__main__":
    unittest.main()
