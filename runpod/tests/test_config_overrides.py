import unittest

import handler
from src import config


class PerJobConfig(unittest.TestCase):
    def test_whitelisted_keys_are_coerced_applied_and_restored(self):
        before = (config.CANDIDATE_POOL, config.JUDGE_BEST_OF, config.EXCELLENT_SCORE, config.META_WEIGHTS)
        prev = handler._apply_config({"CANDIDATE_POOL": "0", "JUDGE_BEST_OF": "3", "EXCELLENT_SCORE": "0.95",
                                      "META_WEIGHTS": '{"entity": 1}', "SUPABASE_SERVICE_KEY": "nope",
                                      "JUDGE_MAX_PER_SCENE": "not a number"})
        try:
            self.assertFalse(config.CANDIDATE_POOL)
            self.assertEqual(config.JUDGE_BEST_OF, 3)
            self.assertEqual(config.EXCELLENT_SCORE, 0.95)
            self.assertEqual(config.META_WEIGHTS, {"entity": 1})
            self.assertNotIn("SUPABASE_SERVICE_KEY", prev)
            self.assertNotIn("JUDGE_MAX_PER_SCENE", prev)
        finally:
            handler._restore_config(prev)
        self.assertEqual((config.CANDIDATE_POOL, config.JUDGE_BEST_OF, config.EXCELLENT_SCORE,
                          config.META_WEIGHTS), before)

    def test_nothing_happens_without_overrides(self):
        self.assertEqual(handler._apply_config(None), {})
        self.assertEqual(handler._apply_config("CANDIDATE_POOL=0"), {})


if __name__ == "__main__":
    unittest.main()
