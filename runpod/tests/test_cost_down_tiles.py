"""Cheaper storyboard calls (VISION_TILE_MODEL; the cost plan, 2026-10-05).

The storyboard calls whose answer the judge checks afterwards (the scout's pick,
the fine pass) ask a cheaper model first; the judge, and a subject pool's rating
whose moments reach the timeline unjudged, stay on VISION_MODEL. Unset, every
call is asked exactly as before.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import handler
from src import config, media, moments, pools, vision

OPENROUTER = "https://openrouter.ai/api/v1"
MAIN, CHEAP = "google/gemini-2.5-flash", "google/gemini-2.5-flash-lite"


class _Vision(unittest.TestCase):
    def setUp(self):
        vision.reset()
        self.p = mock.patch.multiple(config, VISION_API_BASE=OPENROUTER, VISION_API_KEY="k", VISION_MODEL=MAIN,
                                     VISION_FALLBACK_MODELS=[], AI_FALLBACK_API_BASE="", AI_FALLBACK_API_KEY="",
                                     VISION_ENABLED=True, VISION_TILE_MODEL="")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        vision.reset()


class TileModelRoutes(_Vision):
    def test_unset_the_routes_are_the_ones_they_always_were(self):
        with mock.patch.object(config, "VISION_FALLBACK_MODELS", ["gpt-5-2", MAIN]):
            self.assertEqual([r[0] for r in vision._routes()], [MAIN, "gpt-5-2", MAIN])   # not even de-duplicated

    def test_the_cheap_model_goes_first_and_the_usual_ones_back_it_up(self):
        with mock.patch.object(config, "VISION_FALLBACK_MODELS", ["gpt-5-2"]):
            self.assertEqual([r[0] for r in vision._routes(CHEAP)], [CHEAP, MAIN, "gpt-5-2"])
            self.assertEqual([r[0] for r in vision._routes(MAIN)], [MAIN, "gpt-5-2"])     # never asked twice

    def _calls(self, fn):
        seen = []

        def ask(messages, max_tokens, accept=None, **kw):
            seen.append(kw)
            return None, ""
        with mock.patch.object(vision, "_ask", side_effect=ask), \
                mock.patch("src.localvision.rate_sheet", return_value=None):
            fn()
        return seen

    def test_unset_a_checked_call_is_asked_exactly_as_before(self):
        seen = self._calls(lambda: (vision.pick_tile("s", 20, "Lake Powell", checked=True),
                                    vision.rate_tiles("s", 20, "", intent="Lake Powell", checked=True)))
        self.assertEqual(seen, [{}, {}])

    def test_set_the_checked_storyboard_calls_ask_the_cheap_model_first(self):
        with mock.patch.object(config, "VISION_TILE_MODEL", CHEAP):
            seen = self._calls(lambda: (vision.pick_tile("s", 20, "Lake Powell", checked=True),
                                        vision.rate_tiles("s", 20, "", intent="Lake Powell", checked=True)))
        self.assertEqual(seen, [{"first": CHEAP}, {"first": CHEAP}])

    def test_an_unchecked_rating_and_the_judge_stay_on_the_main_model(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        clip = os.path.join(d, "a.mp4")
        with open(clip, "wb") as fh:
            fh.write(b"clip" * 100)
        with mock.patch.object(config, "VISION_TILE_MODEL", CHEAP), \
                mock.patch.object(vision, "sample_frames", return_value=["eA=="]):
            seen = self._calls(lambda: (vision.pick_tile("s", 20, "Lake Powell"),
                                        vision.rate_tiles("s", 20, "Lake Powell"),
                                        vision.judge(clip, "Lake Powell", "")))
        self.assertEqual(seen, [{}, {}, {}])

    def test_the_callers_say_which_calls_are_checked(self):
        got = {}

        def pick(sheet, n, intent, context="", **kw):
            got["pick"] = kw
            return {"tile": 1, "score": 0.9, "description": "x"}

        def rate(sheet, n, subject="", context="", intent="", **kw):
            got.setdefault("rate", []).append(kw)
            return [{"tile": 1, "score": 0.9, "description": "x"}]
        times = [10.0 * k for k in range(1, 21)]
        with mock.patch.object(config, "MOMENT_SELECTION", True), \
                mock.patch.object(config, "MOMENT_FINE_PASS", True), \
                mock.patch.object(moments, "contact_sheet", return_value=("sheet", times)), \
                mock.patch.object(vision, "pick_tile", side_effect=pick), \
                mock.patch.object(vision, "rate_tiles", side_effect=rate), \
                mock.patch.object(media, "_yt_info", return_value=({"id": "v", "duration": 600.0}, "")):
            moments.pick({"id": "v", "duration": 600}, "Lake Powell", "", 7.0)          # the scout
            moments.refine({"id": "v", "duration": 600}, {"start": 50.0, "score": 0.8}, "Lake Powell", "", 7.0)
            with mock.patch.object(config, "POOL_JUDGE_CLIPS", False):
                pools.rate_video({"id": "v"}, "Lake Powell", "", 7.0)                  # unjudged moments
            with mock.patch.object(config, "POOL_JUDGE_CLIPS", True):
                pools.rate_video({"id": "v"}, "Lake Powell", "", 7.0)                  # judged afterwards
        self.assertEqual(got["pick"], {"checked": True})
        self.assertEqual([r.get("checked") for r in got["rate"]], [True, False, True])


class TileModelFallsBack(_Vision):
    def test_when_the_cheap_model_fails_the_main_one_answers(self):
        asked = []

        class R:
            def __init__(self, status, body):
                self.status_code, self._b = status, body

            def json(self):
                return self._b

        def post(url, headers=None, json=None, timeout=None):
            asked.append((json["model"], json.get("reasoning")))
            if json["model"] == CHEAP:
                return R(503, {"error": {"message": "overloaded"}})
            return R(200, {"choices": [{"message": {"content": '{"tile": 3, "score": 0.82, "description": "dam"}'}}]})
        with mock.patch.object(config, "VISION_TILE_MODEL", CHEAP), \
                mock.patch.object(config, "VISION_RETRIES", 0), \
                mock.patch.object(config, "VISION_HEDGE_SECONDS", 0), \
                mock.patch.object(vision.requests, "post", side_effect=post):
            got = vision.pick_tile("s", 20, "Glen Canyon Dam", checked=True)
        self.assertEqual(got["tile"], 3)
        self.assertEqual(got["model"], MAIN)
        self.assertEqual(asked, [(CHEAP, {"max_tokens": 0}), (MAIN, {"max_tokens": 0})])   # no thinking on either
        self.assertEqual(vision.stats()["tileModel"], {"model": CHEAP, "asked": 1, "answered": 0})

    def test_the_job_result_says_how_often_the_cheap_model_answered(self):
        self.assertNotIn("tileModel", vision.stats())
        with mock.patch.object(config, "VISION_TILE_MODEL", CHEAP), \
                mock.patch.object(vision, "_ask", return_value=('{"tile": 2, "score": 0.9, "description": "x"}', CHEAP)):
            vision.pick_tile("s", 20, "Lake Powell", checked=True)
            vision.pick_tile("s", 20, "Lake Powell", checked=True)
        self.assertEqual(vision.stats()["tileModel"], {"model": CHEAP, "asked": 2, "answered": 2})
        vision.reset()
        self.assertNotIn("tileModel", vision.stats())

    def test_a_job_can_try_it(self):
        self.assertIn("VISION_TILE_MODEL", handler.CONFIG_OVERRIDABLE)


if __name__ == "__main__":
    unittest.main()
