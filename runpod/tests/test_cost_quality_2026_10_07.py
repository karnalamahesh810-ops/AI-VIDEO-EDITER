"""
The cost and quality pass of 2026-10-07: storyboard sheets as several images, compact tile answers, the hedge's
clock from the request's send, OpenRouter's out-of-credit answer, the money by call kind, Kie off for good, one
machine per build, the two-strike video memory and the OpenRouter credit floor.
"""
import base64
import io
import json
import threading
import time
import unittest
from unittest import mock

from src import config, costs, director, fanout, media, vision

OPENROUTER = "https://openrouter.ai/api/v1"
KIE = "https://api.kie.ai/v1"


def _sheet(count=20):
    """A storyboard sheet laid out as src/moments.py draws it: 5 tiles a row, 240x135 each."""
    from PIL import Image
    rows = (count + 4) // 5
    im = Image.new("RGB", (5 * 240, rows * 135), "black")
    for i in range(count):
        x, y = (i % 5) * 240, (i // 5) * 135
        im.paste(Image.new("RGB", (240, 135), (i * 12 % 255, 80, 200 - i * 9)), (x, y))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def _size(b64):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


class SheetImages(unittest.TestCase):
    def test_a_sheet_splits_into_near_square_grids_in_order(self):
        parts = vision._sheet_images(_sheet(20), 20, 2)
        self.assertEqual(len(parts), 2)
        for p in parts:
            w, h = _size(p)
            self.assertEqual((w, h), (3 * 240, 4 * 135))     # 10 tiles: 3 columns, 4 rows
        self.assertEqual(len(vision._sheet_images(_sheet(20), 20, 3)), 3)

    def test_one_part_or_too_few_tiles_send_the_sheet_as_it_came(self):
        s = _sheet(20)
        self.assertEqual(vision._sheet_images(s, 20, 1), [s])
        self.assertEqual(vision._sheet_images(_sheet(3), 3, 2), [_sheet(3)])
        self.assertEqual(vision._sheet_images("not a picture", 20, 2), ["not a picture"])

    def test_only_a_checked_call_is_split(self):
        s = _sheet(20)
        with mock.patch.object(config, "VISION_SHEET_IMAGES", 2):
            parts, text = vision._sheet_content(s, 20, checked=True)
            self.assertEqual(len(parts), 2)
            self.assertIn("shown across 2 images (tiles 1-10, 11-20, in order)", text)
            parts, text = vision._sheet_content(s, 20, checked=False)     # a subject pool's rating
            self.assertEqual(len(parts), 1)
            self.assertEqual(text, "There are 20 tiles, numbered 1-20.")


class _Asked(unittest.TestCase):
    def setUp(self):
        vision.reset()
        costs.reset()
        self.asked = []
        self.patches = [mock.patch.object(config, "VISION_API_KEY", "k"),
                        mock.patch.object(config, "VISION_ENABLED", True),
                        mock.patch.object(config, "VISION_MODEL", "main"),
                        mock.patch.object(config, "VISION_FALLBACK_MODELS", []),
                        mock.patch.object(config, "VISION_HEDGE_SECONDS", 0)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        vision.reset()

    def answer(self, text):
        def ask(messages, max_tokens, accept=None, first=""):
            self.asked.append((messages, max_tokens, vision._KIND.get()))
            return text, "main"
        return mock.patch.object(vision, "_ask", side_effect=ask)


class TileCalls(_Asked):
    def test_a_pick_sends_two_images_and_says_so(self):
        with mock.patch.object(config, "VISION_SHEET_IMAGES", 2), \
                self.answer('{"tile": 12, "score": 0.8, "description": "a geyser"}'):
            got = vision.pick_tile(_sheet(20), 20, "a geyser", "the line", checked=True)
        self.assertEqual(got["tile"], 12)
        messages, _n, kind = self.asked[0]
        images = [p for p in messages[1]["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(images), 2)
        self.assertIn("shown across 2 images", messages[1]["content"][0]["text"])
        self.assertEqual(kind, "pick")

    def test_off_a_pick_is_asked_exactly_as_before(self):
        with mock.patch.object(config, "VISION_SHEET_IMAGES", 1), \
                mock.patch.object(config, "VISION_COMPACT_TILES", False), \
                self.answer('{"tile": 3, "score": 0.9, "description": "x"}'):
            vision.pick_tile(_sheet(20), 20, "a geyser", "the line", checked=True)
        messages = self.asked[0][0]
        self.assertIn('Reply with JSON only: {"tile": int, "score": number, "description": str}',
                      messages[0]["content"])
        self.assertNotIn("at most 8 words", messages[0]["content"])
        self.assertEqual(len([p for p in messages[1]["content"] if p.get("type") == "image_url"]), 1)
        self.assertTrue(messages[1]["content"][0]["text"].endswith("There are 20 tiles, numbered 1-20."))

    def test_a_compact_fine_pass_asks_scores_only_and_reads_them(self):
        with mock.patch.object(config, "VISION_COMPACT_TILES", True), \
                self.answer('{"tiles": [{"tile": 4, "score": 0.8}, {"tile": 5, "score": 0.75}]}'):
            got = vision.rate_tiles(_sheet(20), 20, subject="", intent="a geyser", checked=True)
        self.assertEqual([(r["tile"], r["score"], r["description"]) for r in got], [(4, 0.8, ""), (5, 0.75, "")])
        system = self.asked[0][0][0]["content"]
        self.assertIn("no descriptions", system)
        self.assertEqual(self.asked[0][2], "rate")

    def test_a_cut_off_compact_answer_keeps_its_complete_tiles(self):
        with mock.patch.object(config, "VISION_COMPACT_TILES", True), \
                self.answer('{"tiles": [{"tile": 4, "score": 0.8}, {"tile": 5, "sco'):
            got = vision.rate_tiles(_sheet(20), 20, subject="", intent="a geyser", checked=True)
        self.assertEqual([(r["tile"], r["score"]) for r in got], [(4, 0.8)])

    def test_by_default_a_pick_is_split_and_short(self):
        with self.answer('{"tile": 3, "score": 0.9, "description": "x"}'):
            vision.pick_tile(_sheet(20), 20, "a geyser", "the line", checked=True)
        messages = self.asked[0][0]
        self.assertEqual(len([p for p in messages[1]["content"] if p.get("type") == "image_url"]), 2)
        self.assertIn("at most 8 words", messages[0]["content"])

    def test_a_pool_rating_keeps_its_descriptions_and_one_sheet(self):
        with mock.patch.object(config, "VISION_COMPACT_TILES", True), \
                mock.patch.object(config, "VISION_SHEET_IMAGES", 2), \
                self.answer('{"tiles": [{"tile": 4, "score": 0.8, "description": "steam"}]}'):
            got = vision.rate_tiles(_sheet(20), 20, subject="Yellowstone", intent="")
        self.assertEqual(got[0]["description"], "steam")
        messages, _n, kind = self.asked[0]
        self.assertNotIn("no descriptions", messages[0]["content"])
        self.assertEqual(len([p for p in messages[1]["content"] if p.get("type") == "image_url"]), 1)
        self.assertEqual(kind, "pool_rate")


def _post_answer(body, status=200):
    r = mock.Mock(status_code=status)
    r.json.return_value = body
    r.text = json.dumps(body)
    return r


class LedgerByKind(unittest.TestCase):
    def setUp(self):
        vision.reset()
        costs.reset()

    def test_each_kind_has_its_own_line(self):
        body = {"choices": [{"message": {"content": '{"ok": 1}'}}], "usage": {"cost": 0.0008, "prompt_tokens": 900}}
        with mock.patch.object(vision.requests, "post", return_value=_post_answer(body)):
            token = vision._KIND.set("pick")
            try:
                vision._ask_once_slot("google/gemini-2.5-flash", [], 400, OPENROUTER + "/chat/completions", "k", True)
            finally:
                vision._KIND.reset(token)
        s = costs.summary()
        self.assertEqual(s["breakdown"]["vision"]["pick"], {"usd": 0.0008, "calls": 1})
        self.assertAlmostEqual(s["vision"], 0.0008, places=6)
        self.assertEqual(s["other"], 0.0)            # the kind's lines are counts, never priced again

    def test_a_planning_call_is_billed_to_its_kind(self):
        reply = _post_answer({"choices": [{"message": {"content": '{"shots": []}'}}], "usage": {"cost": 0.05}})
        with mock.patch.multiple(config, DIRECTOR_API_BASE=OPENROUTER, DIRECTOR_API_KEY="k",
                                 DIRECTOR_MODEL="openai/gpt-5.2", DIRECTOR_FALLBACK_MODELS=[],
                                 AI_FALLBACK_API_BASE="", DIRECTOR_HEDGE_SECONDS=0), \
                mock.patch.object(director.requests, "post", return_value=reply):
            director._chat_json(director._BRIEF_PROMPT, {})
            director._chat_json(director._SYSTEM_PROMPT, {}, routine=True)
        split = costs.summary()["breakdown"]["llm"]
        self.assertEqual(split["brief"]["usd"], 0.05)
        self.assertEqual(split["plan"]["usd"], 0.05)


class OpenRouterOutOfCredit(unittest.TestCase):
    def setUp(self):
        vision.reset()

    def tearDown(self):
        vision.reset()

    def test_a_402_stops_the_main_provider_for_the_job(self):
        body = {"error": {"code": 402, "message": "This request requires more credits"}}
        with mock.patch.object(vision.requests, "post", return_value=_post_answer(body, 402)):
            text, retry = vision._ask_once_slot("google/gemini-2.5-flash", [], 400, OPENROUTER + "/chat/completions",
                                                "k", True)
        self.assertEqual((text, retry), (None, False))
        self.assertTrue(vision.out_of_credits())

    def test_a_429_is_worth_another_try(self):
        body = {"error": {"code": 429, "message": "slow down"}}
        with mock.patch.object(vision.requests, "post", return_value=_post_answer(body, 429)):
            text, retry = vision._ask_once_slot("google/gemini-2.5-flash", [], 400, OPENROUTER + "/chat/completions",
                                                "k", True)
        self.assertEqual((text, retry), (None, True))
        self.assertFalse(vision.out_of_credits())


class HedgeFromSend(unittest.TestCase):
    """A request still waiting for one of this worker's slots has not gone out: no billed second request yet."""

    def setUp(self):
        vision.reset()
        costs.reset()
        self.patches = [mock.patch.object(config, "VISION_API_KEY", "k"),
                        mock.patch.object(config, "VISION_ENABLED", True),
                        mock.patch.object(config, "VISION_MODEL", "main"),
                        mock.patch.object(config, "VISION_FALLBACK_MODELS", ["backup"]),
                        mock.patch.object(config, "VISION_HEDGE_SECONDS", 0.3),
                        mock.patch.object(config, "VISION_CALL_BUDGET_SECONDS", 10)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        vision.reset()

    def test_queue_time_never_sets_off_a_hedge(self):
        gate = threading.BoundedSemaphore(1)
        gate.acquire()                                  # every slot busy for the first second
        threading.Timer(1.0, gate.release).start()
        seen = []

        def slot(model, messages, max_tokens, url="", key="", main=True):
            seen.append(model)
            return '{"ok": 1}', False

        with mock.patch.object(vision, "_SLOTS", gate), \
                mock.patch.object(vision, "_ask_once_slot", side_effect=slot):
            self.assertEqual(vision._ask([], 100), ('{"ok": 1}', "main"))
        self.assertEqual(seen, ["main"])               # no backup while it waited 1 s for its slot
        self.assertEqual(costs.summary()["units"].get("vision.hedge", 0), 0)

    def test_a_slow_answer_after_sending_is_still_hedged_and_billed_as_one(self):
        def slot(model, messages, max_tokens, url="", key="", main=True):
            if model == "main":
                time.sleep(1.5)
                return '{"from": "main"}', False
            vision._note_usage({"usage": {"cost": 0.001}})
            return '{"from": "backup"}', False

        with mock.patch.object(vision, "_ask_once_slot", side_effect=slot):
            self.assertEqual(vision._ask([], 100), ('{"from": "backup"}', "backup"))
        units = costs.summary()["units"]
        self.assertEqual(units.get("vision.hedge"), 1)
        self.assertAlmostEqual(units.get("vision.hedge.usd"), 0.001)


class KieOff(unittest.TestCase):
    def setUp(self):
        vision.reset()

    def test_kie_is_off_by_default(self):
        self.assertFalse(config.KIE_ENABLED)
        self.assertTrue(config.kie_blocked("https://api.kie.ai/gpt-5-2/v1"))
        self.assertFalse(config.kie_blocked(OPENROUTER))

    def test_a_kie_backup_is_never_asked(self):
        with mock.patch.multiple(config, AI_FALLBACK_API_BASE="https://api.kie.ai/gpt-5-2/v1",
                                 AI_FALLBACK_API_KEY="kie", AI_FALLBACK_VISION_MODEL="gpt-5-2",
                                 AI_FALLBACK_MODEL="gpt-5-2", VISION_API_BASE=OPENROUTER, VISION_API_KEY="k",
                                 VISION_MODEL="google/gemini-2.5-flash", VISION_FALLBACK_MODELS=["openai/gpt-5-mini"],
                                 DIRECTOR_API_BASE=OPENROUTER, DIRECTOR_API_KEY="k", DIRECTOR_MODEL="openai/gpt-5.2",
                                 DIRECTOR_FALLBACK_MODELS=[]):
            self.assertFalse(vision.fallback_configured())
            self.assertNotIn("gpt-5-2", [r[0] for r in vision._routes()])
            self.assertEqual([r[2] for r in director._routes()], ["openai/gpt-5.2"])
            with mock.patch.object(config, "KIE_ENABLED", True):
                self.assertTrue(vision.fallback_configured())
                self.assertEqual([r[2] for r in director._routes()], ["openai/gpt-5.2", "gpt-5-2"])

    def test_a_kie_main_base_is_not_asked_either(self):
        with mock.patch.multiple(config, VISION_API_BASE=KIE, VISION_API_KEY="kie", AI_FALLBACK_API_BASE="",
                                 DIRECTOR_API_BASE=KIE, DIRECTOR_API_KEY="kie", DIRECTOR_MODEL="gpt-5-2"):
            self.assertFalse(vision.enabled())
            self.assertEqual(vision._routes(), [])
            self.assertEqual(director._routes(), [])
            self.assertFalse(director.is_configured())

    def test_no_kie_balance_is_read(self):
        with mock.patch.multiple(config, VISION_API_BASE=KIE, VISION_API_KEY="kie"), \
                mock.patch.object(costs.requests, "get") as get:
            self.assertIsNone(costs.kie_balance())
        get.assert_not_called()


class OneMachinePerBuild(unittest.TestCase):
    def test_a_build_never_fans_out_unless_asked(self):
        ready = {"enabled": True, "workerSlots": 10, "remoteWorkers": 9, "missing": []}
        with mock.patch.object(fanout, "readiness", return_value=ready):
            self.assertFalse(fanout.enabled_for(253, "p"))
            with mock.patch.object(config, "BUILD_FANOUT", True):
                self.assertTrue(fanout.enabled_for(253, "p"))

    def test_one_machine_gets_pass_one_time_by_its_lines(self):
        with mock.patch.multiple(config, SINGLE_PASS1_PER_SCENE=9.0, SINGLE_TAIL_SECONDS=600.0):
            self.assertEqual(fanout.single_machine_deadline(180), max(fanout.source_budget(180), 9.0 * 180 + 600))
            self.assertGreaterEqual(fanout.single_machine_deadline(10), fanout.source_budget(10))

    def test_renders_still_spread(self):
        doc = {"durationInFrames": 30 * 900, "fps": 30, "scenes": [{}] * 200}
        with mock.patch.object(fanout, "readiness", return_value={"enabled": True}), \
                mock.patch.object(config, "FANOUT_RENDER", True), \
                mock.patch.object(config, "FANOUT_RENDER_MIN_SECONDS", 0):
            self.assertTrue(fanout.render_enabled(doc, "p"))


class TwoStrikes(unittest.TestCase):
    def setUp(self):
        media.reset_cache()

    def tearDown(self):
        media.reset_cache()

    def test_two_moments_with_a_watermark_leave_the_video_alone(self):
        why = "judged unusable for any line: text or watermark"
        media._mark_bad("yt:abc", "yt:abc@3", why)
        self.assertEqual(media._is_bad("yt:abc"), "")
        self.assertTrue(media._is_bad("yt:abc@3"))
        media._mark_bad("yt:abc", "yt:abc@3", why)      # the same moment again: still one
        self.assertEqual(media._is_bad("yt:abc"), "")
        media._mark_bad("yt:abc", "yt:abc@9", why)
        self.assertTrue(media._is_bad("yt:abc"))

    def test_off_it_remembers_moments_only(self):
        why = "judged unusable for any line: text or watermark"
        with mock.patch.object(config, "JUDGE_MEMORY_VIDEO_STRIKES", 0):
            media._mark_bad("yt:abc", "yt:abc@3", why)
            media._mark_bad("yt:abc", "yt:abc@9", why)
        self.assertEqual(media._is_bad("yt:abc"), "")

    def test_a_low_score_is_never_a_strike(self):
        media._mark_bad("yt:abc", "yt:abc@3", "")
        media._mark_bad("yt:abc", "yt:abc@9", "")
        self.assertEqual(media._is_bad("yt:abc"), "")


class OpenRouterFloor(unittest.TestCase):
    def setUp(self):
        import handler
        self.handler = handler

    def test_a_build_is_refused_under_the_floor(self):
        from src import credit
        with mock.patch.object(credit, "uses_openrouter", return_value=True), \
                mock.patch.object(credit, "openrouter_left", return_value=0.8), \
                mock.patch.object(config, "OPENROUTER_MIN_CREDIT", 2.0):
            with self.assertRaises(RuntimeError) as e:
                self.handler._require_openrouter_credit()
        self.assertIn("$0.80 left", str(e.exception))

    def test_unknown_balance_or_a_small_job_goes_on(self):
        from src import credit
        with mock.patch.object(credit, "uses_openrouter", return_value=True), \
                mock.patch.object(config, "OPENROUTER_MIN_CREDIT", 2.0):
            with mock.patch.object(credit, "openrouter_left", return_value=None):
                self.handler._require_openrouter_credit()
            with mock.patch.object(credit, "openrouter_left", return_value=0.8),                     mock.patch.object(config, "OPENROUTER_MIN_CREDIT_SMALL", 0.2):
                self.handler._require_openrouter_credit(config.OPENROUTER_MIN_CREDIT_SMALL)

    def test_a_refused_balance_read_is_unknown_not_zero(self):
        from src import credit
        credit.reset()
        refused = mock.Mock(status_code=401)
        refused.json.return_value = {"error": {"code": 401, "message": "No auth credentials found"}}
        with mock.patch.multiple(config, VISION_API_BASE=OPENROUTER, VISION_API_KEY="bad"),                 mock.patch.object(credit.requests, "get", return_value=refused):
            self.assertIsNone(credit.openrouter_left(max_age=0))
        credit.reset()


if __name__ == "__main__":
    unittest.main()


class NewsOverlayRule(unittest.TestCase):
    """The news style's judge is told that station logos, agency marks, webcam stamps and credits are not text."""

    def test_only_the_news_rule_is_spelt_out(self):
        with mock.patch.object(config, "NEWS_FOOTAGE", True), \
                mock.patch.object(config, "VISION_NEWS_OVERLAYS_OK", True):
            self.assertIn("a camera's ID and timestamp (USGS, NOAA, a park webcam)", vision._system())
        with mock.patch.object(config, "NEWS_FOOTAGE", True), \
                mock.patch.object(config, "VISION_NEWS_OVERLAYS_OK", False):
            self.assertNotIn("a park webcam", vision._system())
            self.assertIn(vision._NEWS_TEXT_RULE, vision._system())
        with mock.patch.object(config, "NEWS_FOOTAGE", False), \
                mock.patch.object(config, "VISION_NEWS_OVERLAYS_OK", True):
            self.assertEqual(vision._system(), vision._SYSTEM)       # the strict rule is untouched
