"""Avatarity provider + whole-video AI mode (2026-10-28): offline, a fake HTTP session, nothing paid."""
import os
import tempfile
import unittest
from unittest import mock

from src import aifill, aivisuals, avatarity, config


class _Resp:
    def __init__(self, status, body=None, headers=None, content=b""):
        self.status_code, self._body, self.headers, self.content = status, body or {}, headers or {}, content
        self.text = str(body)

    def json(self):
        return self._body


class _Session:
    """Scripted answers per (method, path prefix); records every call."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def _next(self, method, url):
        self.calls.append((method, url))
        for key, answers in self.script.items():
            if key[0] == method and key[1] in url and answers:
                return answers.pop(0)
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, headers=None, json=None, timeout=None):
        self.last_headers, self.last_body = headers, json
        return self._next("POST", url)

    def get(self, url, headers=None, timeout=None):
        return self._next("GET", url)


def _client(script):
    return avatarity.Avatarity(api_key="test-key", session=_Session(script), sleep=lambda s: None)


class Client(unittest.TestCase):
    def test_rules_always_appended_and_limited(self):
        p = avatarity.with_rules("x" * 2000)
        self.assertLessEqual(len(p), 1200)
        self.assertTrue(p.endswith(avatarity.NO_TEXT))
        self.assertEqual(avatarity.with_rules("A dam. " + avatarity.NO_TEXT).count("No text, captions"), 1)

    def test_image_sync_and_ledger(self):
        c = _client({("POST", "/images/generations"): [_Resp(200, {"data": [{"url": "https://cdn/x.png"}]},
                                                             {"X-Avatarity-Remaining-Images": "4999"})],
                     ("GET", "https://cdn/x.png"): [_Resp(200, content=b"\x89PNG....")]})
        out = c.image("a dam at dawn", model="avatarity/nano-banana-pro", seed=5)
        self.assertEqual(out.url, "https://cdn/x.png")
        self.assertEqual(out.ext, ".png")
        body = c.http.last_body
        self.assertEqual(body["model"], "nano-banana-pro")
        self.assertEqual(body["size"], "1376x768")
        self.assertIn("No text", body["prompt"])
        self.assertIn("Idempotency-Key", c.http.last_headers)
        self.assertNotIn("test-key", str(out))
        self.assertEqual(c.ledger.images, 1)
        self.assertEqual(c.remaining["images"], 4999)

    def test_concurrency_429_waits_then_succeeds(self):
        c = _client({("POST", "/video/generations"): [
            _Resp(429, {"error": {"code": "CONCURRENCY_LIMIT"}}), _Resp(202, {"task_id": "t1"})],
            ("GET", "/tasks/t1"): [_Resp(200, {"status": "processing"}),
                                   _Resp(200, {"status": "succeeded", "video_url": "https://cdn/v.mp4"})],
            ("GET", "https://cdn/v.mp4"): [_Resp(200, content=b"mp4")]})
        path = os.path.join(tempfile.mkdtemp(), "c.mp4")
        out = c.video("drone over a dam", path, image="https://cdn/still.png", seed=3)
        self.assertEqual((out.task_id, out.units), ("t1", 1))
        self.assertEqual(c.ledger.video_units, 1)
        self.assertEqual(c.ledger.retried, 1)
        self.assertEqual(c.http.last_body["image"], "https://cdn/still.png")
        self.assertEqual(c.http.last_body["resolution"], "720p")

    def test_1080p_counts_two_units(self):
        c = _client({("POST", "/video/generations"): [_Resp(202, {"task_id": "t2"})],
                     ("GET", "/tasks/t2"): [_Resp(200, {"status": "succeeded", "video_url": "https://cdn/v.mp4"})],
                     ("GET", "https://cdn/v.mp4"): [_Resp(200, content=b"mp4")]})
        out = c.video("x y z", os.path.join(tempfile.mkdtemp(), "c.mp4"), resolution="1080p")
        self.assertEqual(out.units, 2)
        self.assertEqual(c.ledger.video_units, 2)

    def test_allowance_and_policy_errors_are_typed(self):
        c = _client({("POST", "/images/generations"): [_Resp(402, {"error": {"code": "ALLOWANCE_EXHAUSTED"}}),
                                                       _Resp(400, {"error": {"code": "CONTENT_POLICY_VIOLATION"}})]})
        with self.assertRaises(avatarity.AllowanceError):
            c.image("abc")
        with self.assertRaises(avatarity.PolicyError):
            c.image("abd")

    def test_failed_render_task_is_retried_once(self):
        c = _client({("POST", "/video/generations"): [_Resp(202, {"task_id": "a"}), _Resp(202, {"task_id": "b"})],
                     ("GET", "/tasks/a"): [_Resp(200, {"status": "failed", "error": {"code": "RENDER_TIMEOUT"}})],
                     ("GET", "/tasks/b"): [_Resp(200, {"status": "succeeded", "video_url": "https://cdn/v.mp4"})],
                     ("GET", "https://cdn/v.mp4"): [_Resp(200, content=b"mp4")]})
        out = c.video("abc", os.path.join(tempfile.mkdtemp(), "c.mp4"))
        self.assertEqual(out.task_id, "b")
        self.assertEqual(c.ledger.failed, 1)


class Chains(unittest.TestCase):
    def tearDown(self):
        aifill.reset()

    def test_no_key_keeps_the_openrouter_chains(self):
        with mock.patch.dict(os.environ, {"AVATARITY_API_KEY": ""}):
            aifill.start({"ai_fill": {"enabled": True}}, work=tempfile.mkdtemp())
            self.assertFalse(any(m.startswith("avatarity/") for m, _ in aifill.image_models()))

    def test_avatarity_first_with_a_key(self):
        with mock.patch.dict(os.environ, {"AVATARITY_API_KEY": "k"}):
            aifill.start({"ai_fill": {"enabled": True, "image_model": "nano-banana-2.1"}}, work=tempfile.mkdtemp())
            self.assertEqual(aifill.image_models()[0], ("avatarity/nano-banana-2.1", "2K"))
            self.assertEqual(aifill.video_models()[0], ("avatarity/veo-3.1-lite", "720p"))
            self.assertEqual(aifill.image_usd("avatarity/nano-banana-pro", "2K"), 0.0)
            self.assertEqual(aifill._clip_len("avatarity/veo-3.1-lite", 7.0), 8)
            self.assertIsNone(aifill._clip_len("avatarity/veo-3.1-lite", 9.0))
            # OpenRouter picked in the app: its own chain only.
            aifill.start({"ai_fill": {"enabled": True, "provider": "openrouter"}}, work=tempfile.mkdtemp())
            self.assertFalse(any(m.startswith("avatarity/") for m, _ in aifill.image_models()))


class WholeVideo(unittest.TestCase):
    def tearDown(self):
        aifill.reset()

    def test_prepare_input(self):
        inp = {"visual_source": "ai", "ai_visuals": {"clip_pct": 70, "look": "cinematic", "style_notes": "warm"},
               "ai_prompts": {"s001": {"still": "a dam"}}, "allow_youtube": True}
        self.assertTrue(aivisuals.wanted(inp))
        aivisuals.prepare_input(inp)
        self.assertFalse(inp["allow_youtube"])
        b = aifill.block(inp)
        self.assertTrue(b["full"])
        self.assertEqual((b["clip_pct"], b["look"]), (70.0, "cinematic"))
        self.assertGreater(b["max_images"], aifill.MAX_IMAGES_LIMIT)
        self.assertEqual(inp["config"]["SHOT_MAX_SECONDS"], 7.0)
        self.assertFalse(inp["config"]["AI_FILL_LABEL"])
        self.assertEqual(b["prompts"], {"s001": {"still": "a dam"}})
        self.assertFalse(aivisuals.wanted({"visual_source": "footage"}))

    def test_clip_share_spread_over_time(self):
        with mock.patch.dict(os.environ, {"AVATARITY_API_KEY": "k"}):
            aifill.start({"ai_fill": {"enabled": True, "full": True, "clip_pct": 70, "max_images": 100,
                                      "max_clips": 100}}, work=tempfile.mkdtemp())
            lines = [aifill.Line(scene={"id": f"s{i}"}, index=i, key=f"k{i}", start=10.0 + 5 * i, seconds=5.0,
                                 hook=False, beat=i, opens_section=False, run=1, what="", prompt="", motion="",
                                 person=(i == 7)) for i in range(40)]
            keys = aifill._key_lines(lines)
            self.assertNotIn("k7", keys)                         # a real person's line is never animated
            share = len(keys) / 40
            self.assertTrue(0.6 <= share <= 0.75, share)
            first_half = sum(1 for k in keys if int(k[1:]) < 20)
            self.assertTrue(abs(first_half - len(keys) / 2) <= 2)  # spread, not front-loaded

    def test_user_prompt_wins(self):
        aifill.start({"ai_fill": {"enabled": True, "prompts": {"s3": {"still": "my own picture", "motion": "pan"}}}},
                     work=tempfile.mkdtemp())
        self.assertEqual(aifill.user_prompt({"id": "s3"}, 3), {"still": "my own picture", "motion": "pan"})
        self.assertEqual(aifill.user_prompt({"id": "s4", "semanticMetadata": {"aiPrompt": "x", "aiPromptEdited": True}},
                                            4), {"still": "x"})
        self.assertEqual(aifill.user_prompt({"id": "s5", "semanticMetadata": {"aiPrompt": "auto"}}, 5), {})

    def test_look_preset_in_the_prompt(self):
        aifill.start({"ai_fill": {"enabled": True, "look": "anime", "style_notes": "soft pastel"}},
                     work=tempfile.mkdtemp())
        p = aifill.compose("a quiet harbour at dawn", {"place": "a harbour"})
        self.assertTrue(p.startswith("A hand-painted anime film frame"))
        self.assertIn("soft pastel", p)
        self.assertIn("polaroid", p)


if __name__ == "__main__":
    unittest.main()
