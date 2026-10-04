"""Planning calls read OpenRouter's errors and wait out the transient ones (2026-10-05).

Only Kie's failure shape (an HTTP 200 carrying {"code": 5xx}) used to be read. An
OpenRouter error ({"error": {...}} with HTTP 429 or 5xx) became a KeyError on
body["choices"]: no retry, no circuit breaker, no out-of-credits flag - the batch
went straight to the next model or, with none left, to rule shots. Now 408/409/
425/429, any 5xx, a timeout and a gateway's HTML error page are asked again on
the same model after DIRECTOR_RETRY_WAIT seconds, doubling, DIRECTOR_RETRIES times;
then the next model takes the call, as designed.
"""
import unittest
from unittest import mock

from src import config, director, vision

OPENROUTER = "https://openrouter.ai/api/v1"


def reply(status=200, body=None, text=None):
    r = mock.Mock(status_code=status)
    if text is not None:
        r.json.side_effect = ValueError("not JSON")
        r.text = text
    else:
        r.json.return_value = body
    return r


OK = reply(body={"choices": [{"message": {"content": '{"ok": 1}'}}]})


def or_error(status, message="busy", code=None):
    return reply(status, {"error": {"code": status if code is None else code, "message": message}})


class _Planner(unittest.TestCase):
    def setUp(self):
        vision.reset()
        self.p = mock.patch.multiple(config, DIRECTOR_API_BASE=OPENROUTER, DIRECTOR_API_KEY="k",
                                     DIRECTOR_MODEL="openai/gpt-5.2", DIRECTOR_FALLBACK_MODELS=["openai/gpt-5.1"],
                                     DIRECTOR_ROUTINE_MODEL="", DIRECTOR_HEDGE_SECONDS=0,
                                     DIRECTOR_RETRIES=2, DIRECTOR_RETRY_WAIT=3.0,
                                     AI_FALLBACK_API_BASE="", AI_FALLBACK_API_KEY="", AI_FALLBACK_MODEL="")
        self.p.start()
        self.sleep = mock.patch.object(director.time, "sleep")
        self.slept = self.sleep.start()
        self.asked = []

    def tearDown(self):
        self.sleep.stop()
        self.p.stop()
        vision.reset()

    def run_with(self, answers):
        """answers: model -> list of replies, one per request (the last one repeats)."""
        def post(url, json=None, **kw):
            self.asked.append(json["model"])
            got = answers[json["model"]]
            r = got.pop(0) if len(got) > 1 else got[0]
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(director.requests, "post", side_effect=post):
            return director._chat_json("system", {"lines": []})

    def pauses(self):
        return [c.args[0] for c in self.slept.call_args_list]


class OpenRouterErrors(_Planner):
    def test_a_429_is_waited_out_on_the_same_model(self):
        self.assertEqual(self.run_with({"openai/gpt-5.2": [or_error(429, "rate limited"), OK]}), {"ok": 1})
        self.assertEqual(self.asked, ["openai/gpt-5.2", "openai/gpt-5.2"])
        self.assertEqual(self.pauses(), [3.0])
        self.assertTrue(vision.model_available("openai/gpt-5.2"))

    def test_5xx_retried_with_backoff_then_the_next_model_takes_the_call(self):
        got = self.run_with({"openai/gpt-5.2": [or_error(503, "upstream overloaded")], "openai/gpt-5.1": [OK]})
        self.assertEqual(got, {"ok": 1})
        self.assertEqual(self.asked, ["openai/gpt-5.2"] * 3 + ["openai/gpt-5.1"])
        self.assertEqual(self.pauses(), [3.0, 6.0])                       # doubling

    def test_a_failed_call_counts_once_on_the_breaker(self):
        self.run_with({"openai/gpt-5.2": [or_error(502)], "openai/gpt-5.1": [OK]})
        self.assertTrue(vision.model_available("openai/gpt-5.2"))         # one failed call: still in rotation
        self.run_with({"openai/gpt-5.2": [or_error(502)], "openai/gpt-5.1": [OK]})
        self.assertFalse(vision.model_available("openai/gpt-5.2"))        # two in a row: benched

    def test_a_rate_limit_named_in_words_reads_the_http_status(self):
        got = self.run_with({"openai/gpt-5.2": [or_error(429, code="rate_limit_exceeded"), OK]})
        self.assertEqual(got, {"ok": 1})
        self.assertEqual(len(self.asked), 2)

    def test_an_error_on_the_choice_is_read_too(self):
        bad = reply(200, {"choices": [{"error": {"code": 502, "message": "provider returned error"},
                                       "finish_reason": "error"}]})
        self.assertEqual(self.run_with({"openai/gpt-5.2": [bad, OK]}), {"ok": 1})
        self.assertEqual(len(self.asked), 2)

    def test_a_gateways_html_error_page_is_transient(self):
        page = reply(502, text="<html>502 Bad Gateway</html>")
        self.assertEqual(self.run_with({"openai/gpt-5.2": [page, OK]}), {"ok": 1})
        self.assertEqual(len(self.asked), 2)

    def test_a_timeout_is_retried_with_backoff(self):
        got = self.run_with({"openai/gpt-5.2": [director.requests.Timeout("read timed out"), OK]})
        self.assertEqual(got, {"ok": 1})
        self.assertEqual(self.pauses(), [3.0])

    def test_a_bad_request_or_key_goes_to_the_next_model_at_once(self):
        for status in (400, 401, 403, 404):
            self.asked.clear()
            vision.reset()
            got = self.run_with({"openai/gpt-5.2": [or_error(status, "nope")], "openai/gpt-5.1": [OK]})
            self.assertEqual(got, {"ok": 1})
            self.assertEqual(self.asked, ["openai/gpt-5.2", "openai/gpt-5.1"], status)
            self.assertTrue(vision.model_available("openai/gpt-5.2"))     # not the model's fault

    def test_out_of_credits_stops_the_account_and_the_backup_provider_answers(self):
        with mock.patch.multiple(config, AI_FALLBACK_API_BASE="https://gen.example/openai", AI_FALLBACK_API_KEY="g",
                                 AI_FALLBACK_MODEL="gemini-2.5-flash"):
            got = self.run_with({"openai/gpt-5.2": [or_error(402, "Insufficient credits")],
                                 "openai/gpt-5.1": [OK], "gemini-2.5-flash": [OK]})
        self.assertEqual(got, {"ok": 1})
        self.assertTrue(vision.out_of_credits())
        self.assertEqual(self.asked, ["openai/gpt-5.2", "gemini-2.5-flash"])   # no retry; the account is spent

    def test_the_retries_stop_at_the_calls_deadline(self):
        with mock.patch.object(config, "DIRECTOR_RETRY_WAIT", 1000.0):
            got = self.run_with({"openai/gpt-5.2": [or_error(503)], "openai/gpt-5.1": [OK]})
        self.assertEqual(got, {"ok": 1})
        self.assertEqual(self.asked, ["openai/gpt-5.2", "openai/gpt-5.1"])   # no 1000 s wait inside the budget
        self.assertEqual(self.pauses(), [])

    def test_no_retries_when_switched_off(self):
        with mock.patch.object(config, "DIRECTOR_RETRIES", 0):
            self.run_with({"openai/gpt-5.2": [or_error(503)], "openai/gpt-5.1": [OK]})
        self.assertEqual(self.asked, ["openai/gpt-5.2", "openai/gpt-5.1"])


class KieUnchanged(_Planner):
    def test_kies_wrapped_failures_are_still_read(self):
        with mock.patch.object(config, "DIRECTOR_API_BASE", "https://api.kie.ai/v1"):
            got = self.run_with({"openai/gpt-5.2": [reply(200, {"code": 500, "msg": "Server exception"}), OK]})
            self.assertEqual(got, {"ok": 1})
            self.assertEqual(len(self.asked), 2)
            self.asked.clear()
            got = self.run_with({"openai/gpt-5.2": [reply(200, {"code": 422, "msg": "bad input"})],
                                 "openai/gpt-5.1": [OK]})
        self.assertEqual(got, {"ok": 1})
        self.assertEqual(self.asked, ["openai/gpt-5.2", "openai/gpt-5.1"])   # a 4xx is not retried


class Classification(unittest.TestCase):
    def test_what_is_worth_waiting_out(self):
        for status in (408, 409, 425, 429, 500, 502, 503, 504, 529):
            self.assertTrue(director._retryable(status), status)
        for status in (400, 401, 402, 403, 404, 413, 422):
            self.assertFalse(director._retryable(status), status)

    def test_failure_shapes(self):
        self.assertEqual(director._failure(reply(200, {}), {"choices": []}), (0, ""))
        self.assertEqual(director._failure(reply(429, None), {"error": {"code": 429, "message": "slow down"}}),
                         (429, "slow down"))
        self.assertEqual(director._failure(reply(503, None), None), (503, ""))
        self.assertEqual(director._failure(reply(200, None), {"code": 402, "msg": "Credits insufficient"}),
                         (402, "Credits insufficient"))
        self.assertEqual(director._failure(reply(200, None), {"error": "boom"}), (500, "boom"))


if __name__ == "__main__":
    unittest.main()
