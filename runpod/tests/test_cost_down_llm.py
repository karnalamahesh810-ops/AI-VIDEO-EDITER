"""The planning calls' real price, and how hard they think (the cost plan, 2026-10-05).

Before: every planning call was priced at one flat Kie credit ($0.005) whatever
answered it, while openai/gpt-5.2 on OpenRouter cost ~$0.04 a call (a 5-minute
test: 7 calls, ~$0.26 of its $0.56 OpenRouter bill), and no call ever said how
hard to think, so the provider's default reasoning was billed as output.
Now OpenRouter's own price comes back with each call (llm.usd), and
DIRECTOR_REASONING_EFFORT / DIRECTOR_ROUTINE_REASONING_EFFORT can lower the
effort - unset, the request is the one it always was.
"""
import unittest
from unittest import mock

import handler
from src import config, costs, director, vision

OPENROUTER = "https://openrouter.ai/api/v1"
KIE = "https://api.kie.ai/v1"


def _reply(text='{"ok": 1}', usage=None):
    r = mock.Mock(status_code=200)
    body = {"choices": [{"message": {"content": text}}]}
    if usage is not None:
        body["usage"] = usage
    r.json.return_value = body
    return r


USAGE = {"prompt_tokens": 5600, "completion_tokens": 3100, "cost": 0.0412,
         "prompt_tokens_details": {"cached_tokens": 4096},
         "completion_tokens_details": {"reasoning_tokens": 1800}}


class _Director(unittest.TestCase):
    base = OPENROUTER

    def setUp(self):
        vision.reset()
        costs.reset()
        self.p = mock.patch.multiple(config, DIRECTOR_API_BASE=self.base, DIRECTOR_API_KEY="k",
                                     DIRECTOR_MODEL="openai/gpt-5.2", DIRECTOR_FALLBACK_MODELS=[],
                                     DIRECTOR_ROUTINE_MODEL="", DIRECTOR_REASONING_EFFORT="",
                                     DIRECTOR_ROUTINE_REASONING_EFFORT="", DIRECTOR_HEDGE_SECONDS=0,
                                     AI_FALLBACK_API_BASE="", AI_FALLBACK_API_KEY="", AI_FALLBACK_MODEL="")
        self.p.start()
        self.sent = []

    def tearDown(self):
        self.p.stop()
        costs.reset()
        vision.reset()

    def ask(self, routine=False, usage=None):
        def post(url, json=None, **kw):
            self.sent.append((url, dict(json)))
            return _reply(usage=usage)
        with mock.patch.object(director.requests, "post", side_effect=post):
            return director._chat_json("system", {"lines": []}, routine=routine)


class PlanningCallsMeasured(_Director):
    def test_openrouter_is_asked_for_the_price_and_it_replaces_the_flat_estimate(self):
        self.assertEqual(self.ask(usage=USAGE), {"ok": 1})
        self.assertEqual(self.sent[0][1]["usage"], {"include": True})
        s = costs.summary(1.0)
        self.assertAlmostEqual(s["llm"], 0.0412)                       # not 1 call x $0.005
        self.assertTrue(s["llm_measured"])
        self.assertEqual((s["units"]["llm.prompt_tokens"], s["units"]["llm.cached_tokens"],
                          s["units"]["llm.completion_tokens"], s["units"]["llm.reasoning_tokens"]),
                         (5600, 4096, 3100, 1800))
        self.assertEqual(s["other"], 0.0)                              # token counts are counts, not money
        self.assertEqual(s["units"]["llm.director_call"], 1)           # the call count stays

    def test_without_a_price_the_estimate_stands(self):
        self.ask(usage=None)
        s = costs.summary(1.0)
        self.assertAlmostEqual(s["llm"], 1.0 * 0.005)
        self.assertFalse(s["llm_measured"])

    def test_a_failed_answer_is_still_billed(self):
        def post(url, json=None, **kw):
            return _reply(text="not json at all", usage=USAGE)
        with mock.patch.object(director.requests, "post", side_effect=post):
            self.assertIsNone(director._chat_json("system", {}))
        self.assertAlmostEqual(costs.summary(1.0)["units"]["llm.usd"], 0.0412)

    def test_vision_and_planning_are_measured_apart(self):
        costs.record("vision.usd", 0.30)
        costs.record("vision.judge", 10)
        self.ask(usage=USAGE)
        s = costs.summary(1.0)
        self.assertAlmostEqual(s["vision"], 0.30)
        self.assertAlmostEqual(s["llm"], 0.0412)


class KieUnchanged(_Director):
    base = KIE

    def test_another_provider_gets_the_request_it_always_got(self):
        with mock.patch.object(config, "DIRECTOR_MODEL", "gemini-3-pro"):
            self.ask()
        url, body = self.sent[0]
        self.assertEqual(set(body), {"model", "messages", "response_format"})


class ReasoningEffort(_Director):
    def test_unset_sends_no_effort(self):
        self.ask()
        self.ask(routine=True)
        for _url, body in self.sent:
            self.assertNotIn("reasoning", body)
            self.assertNotIn("reasoning_effort", body)
            self.assertEqual(set(body), {"model", "messages", "response_format", "usage"})

    def test_one_effort_for_every_call(self):
        with mock.patch.object(config, "DIRECTOR_REASONING_EFFORT", "low"):
            self.ask()
            self.ask(routine=True)
        self.assertEqual([b["reasoning"] for _u, b in self.sent], [{"effort": "low"}] * 2)

    def test_the_routine_calls_may_think_less_than_the_brief(self):
        with mock.patch.object(config, "DIRECTOR_ROUTINE_REASONING_EFFORT", "minimal"):
            self.ask()                                 # the story brief: the provider's default
            self.ask(routine=True)
        self.assertNotIn("reasoning", self.sent[0][1])
        self.assertEqual(self.sent[1][1]["reasoning"], {"effort": "minimal"})

    def test_the_routine_effort_follows_the_call_to_its_backup_model(self):
        models = []

        def post(url, json=None, **kw):
            models.append((json["model"], json.get("reasoning")))
            if json["model"] == "openai/gpt-5-mini":
                return _reply(text="nope")             # the cheap model answers nonsense
            return _reply()
        with mock.patch.object(config, "DIRECTOR_ROUTINE_MODEL", "openai/gpt-5-mini"), \
                mock.patch.object(config, "DIRECTOR_ROUTINE_REASONING_EFFORT", "low"), \
                mock.patch.object(director.requests, "post", side_effect=post):
            self.assertEqual(director._chat_json("system", {}, routine=True), {"ok": 1})
        self.assertEqual(models, [("openai/gpt-5-mini", {"effort": "low"}), ("openai/gpt-5.2", {"effort": "low"})])

    def test_an_unknown_effort_is_ignored(self):
        with mock.patch.object(config, "DIRECTOR_REASONING_EFFORT", "turbo"):
            self.ask()
        self.assertNotIn("reasoning", self.sent[0][1])

    def test_kie_gpt_models_get_their_own_field_and_nothing_else_does(self):
        self.assertEqual(director._request_extra("gpt-5-2", "https://api.kie.ai/v1/chat/completions"), {})
        with mock.patch.object(config, "DIRECTOR_REASONING_EFFORT", "low"):
            self.assertEqual(director._request_extra("gpt-5-2", "https://api.kie.ai/v1/chat/completions"),
                             {"reasoning_effort": "low"})
            self.assertEqual(director._request_extra(
                "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"), {})
            self.assertEqual(director._request_extra("gemini-3-pro", "https://api.kie.ai/v1/chat/completions"), {})

    def test_a_job_can_try_each_lever(self):
        for key in ("DIRECTOR_REASONING_EFFORT", "DIRECTOR_ROUTINE_REASONING_EFFORT", "DIRECTOR_ROUTINE_MODEL"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
        before = config.DIRECTOR_ROUTINE_REASONING_EFFORT
        previous = handler._apply_config({"DIRECTOR_ROUTINE_REASONING_EFFORT": "low"})
        try:
            self.assertEqual(config.DIRECTOR_ROUTINE_REASONING_EFFORT, "low")
        finally:
            handler._restore_config(previous)
        self.assertEqual(config.DIRECTOR_ROUTINE_REASONING_EFFORT, before)


if __name__ == "__main__":
    unittest.main()
