"""What one vision check costs (src/vision.py, src/costs.py; measured 2026-10-01 on
OpenRouter google/gemini-2.5-flash): the fixed instructions cached, photos at
384 px, short descriptions, one verdict per picture however often it is
downloaded, and the provider's own price in the cost ledger."""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from src import config, costs, vision

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def msgs():
    return [{"role": "system", "content": "fixed instructions " * 50},
            {"role": "user", "content": [{"type": "text", "text": "INTENT: Lake Powell"}]}]


class PromptCache(unittest.TestCase):
    def test_openrouter_gemini_gets_a_cached_system_block(self):
        out = vision._cached("google/gemini-2.5-flash", OPENROUTER, msgs())
        part = out[0]["content"][0]
        self.assertEqual(part["cache_control"], {"type": "ephemeral"})
        self.assertEqual(part["text"], msgs()[0]["content"])           # the same words
        self.assertEqual(out[1], msgs()[1])

    def test_other_routes_and_models_are_left_alone(self):
        self.assertEqual(vision._cached("gpt-5-2", "https://api.kie.ai/gpt-5-2/v1/chat/completions", msgs()), msgs())
        self.assertEqual(vision._cached("openai/gpt-5-mini", OPENROUTER, msgs()), msgs())
        with mock.patch.object(config, "VISION_PROMPT_CACHE", False):
            self.assertEqual(vision._cached("google/gemini-2.5-flash", OPENROUTER, msgs()), msgs())

    def test_the_request_carries_it_and_asks_for_the_price(self):
        sent = {}

        class R:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": '{"ok": true}'}}],
                        "usage": {"prompt_tokens": 2415, "completion_tokens": 101, "cost": 0.00069,
                                  "prompt_tokens_details": {"cached_tokens": 1502}}}

        def post(url, headers=None, json=None, timeout=None):
            sent.update(json)
            return R()
        costs.reset()
        with mock.patch.object(vision.requests, "post", side_effect=post):
            text, _retry = vision._ask_once_slot("google/gemini-2.5-flash", msgs(), 400, OPENROUTER, "k", True)
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(sent["messages"][0]["content"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(sent["usage"], {"include": True})
        units = costs.summary(1.0)["units"]
        self.assertAlmostEqual(units["vision.usd"], 0.00069)
        self.assertEqual((units["vision.prompt_tokens"], units["vision.cached_tokens"],
                          units["vision.completion_tokens"]), (2415, 1502, 101))


class CostLedger(unittest.TestCase):
    def tearDown(self):
        costs.reset()

    def test_the_providers_own_price_replaces_the_credit_estimate(self):
        costs.reset({"kie.credit": 0.01, "vision.judge": 1.0})
        costs.record("vision.judge", 10)                 # estimate: 10 x 1 credit x $0.01 = $0.10
        self.assertAlmostEqual(costs.summary(1.0)["vision"], 0.10)
        costs.record("vision.usd", 0.0069)
        costs.record("vision.prompt_tokens", 24000)
        s = costs.summary(1.0)
        self.assertAlmostEqual(s["vision"], 0.0069)
        self.assertTrue(s["vision_measured"])
        self.assertEqual(s["other"], 0.0)                # token counts are counts, not money


class Frames(unittest.TestCase):
    def test_a_photo_goes_at_384_and_clip_frames_at_512(self):
        self.assertEqual(vision.judge_width("x.jpg"), config.VISION_STILL_WIDTH)
        self.assertEqual(vision.judge_width("x.png"), 384)
        self.assertEqual(vision.judge_width("x.mp4"), config.VISION_FRAME_WIDTH)
        self.assertEqual(vision.judge_width("x.mp4"), 512)

    def test_the_judge_asks_for_those_widths(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        seen = []
        for name in ("a.jpg", "b.mp4"):
            p = os.path.join(d, name)
            with open(p, "wb") as fh:
                fh.write(name.encode() * 100)
            with mock.patch.object(vision, "enabled", return_value=True), \
                    mock.patch.object(vision, "sample_frames",
                                      side_effect=lambda path, count=3, width=512: seen.append(width) or ["eA=="]), \
                    mock.patch.object(vision, "_ask", return_value=(None, "")):
                vision.judge(p, "Lake Powell", "")
        self.assertEqual(seen, [384, 512])


class ShortAnswers(unittest.TestCase):
    def test_the_descriptions_are_short(self):
        self.assertIn("at most 25 words", vision._system())
        self.assertIn("at most 25 words", vision._SYSTEM)
        self.assertIn("at most 10 words", vision._RATE_SYSTEM)

    def test_news_mode_still_swaps_the_text_rule(self):
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            self.assertIn("TV NEWS FOOTAGE IS WELCOME", vision._system())
            self.assertNotIn(vision._STRICT_TEXT_RULE, vision._system())


class OneVerdictPerPicture(unittest.TestCase):
    def test_a_picture_downloaded_again_is_the_same_picture(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        a, b, c = (os.path.join(d, n) for n in ("a.mp4", "b.mp4", "c.mp4"))
        for p, data in ((a, b"clip" * 50000), (b, b"clip" * 50000), (c, b"clip" * 49999 + b"CLIP")):
            with open(p, "wb") as fh:
                fh.write(data)
        os.utime(b, (time.time() - 3600, time.time() - 3600))           # downloaded an hour apart
        self.assertEqual(vision._fingerprint(a), vision._fingerprint(b))
        self.assertNotEqual(vision._fingerprint(a), vision._fingerprint(c))   # same size, other ending

    def test_the_second_download_reuses_the_verdict(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        first, again = os.path.join(d, "dm_1.mp4"), os.path.join(d, "dm_2.mp4")
        for p in (first, again):
            with open(p, "wb") as fh:
                fh.write(b"same section" * 1000)
        verdict = '{"description": "x", "score": 0.8, "quality": 0.8, "has_text_or_watermark": false, ' \
                  '"is_talking_head": false, "ai_generated": false, "studio": false, "specificity": "location"}'
        vision.reset()
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "sample_frames", return_value=["eA=="]), \
                mock.patch.object(vision, "_ask", return_value=(verdict, "m")) as ask:
            self.assertEqual(vision.judge(first, "Lake Powell", "")["score"], 0.8)
            self.assertEqual(vision.judge(again, "Lake Powell", "")["score"], 0.8)
        self.assertEqual(ask.call_count, 1)
        vision.reset()


if __name__ == "__main__":
    unittest.main()
