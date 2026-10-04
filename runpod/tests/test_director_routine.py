"""The routine planning calls on a cheaper model; the story brief stays on the director's own (2026-10-05)."""
import unittest
from unittest import mock

import handler
from src import config, director


class RoutineModel(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(config, DIRECTOR_API_BASE="https://or.example/api/v1", DIRECTOR_API_KEY="k",
                                     DIRECTOR_MODEL="openai/gpt-5.2", DIRECTOR_FALLBACK_MODELS=["gpt-5-2"],
                                     AI_FALLBACK_API_BASE="", AI_FALLBACK_API_KEY="", AI_FALLBACK_MODEL="")
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def models(self, routine):
        return [r[2] for r in director._routes(routine)]

    def test_unset_changes_nothing(self):
        with mock.patch.object(config, "DIRECTOR_ROUTINE_MODEL", ""):
            self.assertEqual(self.models(True), ["openai/gpt-5.2", "gpt-5-2"])
            self.assertEqual(self.models(False), ["openai/gpt-5.2", "gpt-5-2"])

    def test_routine_calls_ask_the_cheap_model_first_and_the_director_backs_it_up(self):
        with mock.patch.object(config, "DIRECTOR_ROUTINE_MODEL", "openai/gpt-5-mini"):
            self.assertEqual(self.models(True), ["openai/gpt-5-mini", "openai/gpt-5.2", "gpt-5-2"])
            self.assertEqual(self.models(False), ["openai/gpt-5.2", "gpt-5-2"])     # the brief

    def test_the_same_model_is_not_asked_twice(self):
        with mock.patch.object(config, "DIRECTOR_ROUTINE_MODEL", "openai/gpt-5.2"):
            self.assertEqual(self.models(True), ["openai/gpt-5.2", "gpt-5-2"])

    def test_a_job_can_try_it(self):
        self.assertIn("DIRECTOR_ROUTINE_MODEL", handler.CONFIG_OVERRIDABLE)

    def test_the_batch_plans_are_routine_and_the_brief_is_not(self):
        src = open(director.__file__, encoding="utf-8").read()
        self.assertEqual(src.count("_chat_json(_SYSTEM_PROMPT, payload, timeout="), 2)
        self.assertEqual(src.count("errors=tried, routine=True)"), 2)
        for name in ("_RESCUE_PROMPT", "_SEQUENCE_PROMPT", "_ASSIGN_PROMPT"):
            self.assertIn(f"_chat_json({name}, routine=True,", src)
        self.assertIn("_chat_json(_BRIEF_PROMPT, {", src)                         # strong model only


if __name__ == "__main__":
    unittest.main()
