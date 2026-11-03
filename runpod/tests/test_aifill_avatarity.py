"""
AI fill on the Avatarity plan + the owner's own numbers (2026-11-03), offline: a fake HTTP session for the
Avatarity client, the presenter's FakeProvider for AI fill (tests/test_presenter.py). Nothing is paid.

  Client        the Avatarity client: the frame rule on every prompt, 720p forced, typed errors, 429 retries
  Routed        the provider AI fill speaks to: one render slot held per clip from submit to the end of its wait
  Block         pictures 0-300 and clips 0-200 apart (clips may outnumber pictures), fill_all, the backup switch,
                the OpenRouter cap and need on the plan
  Chains        Avatarity first with a key, the backup behind it, no backup when switched off
  Numbers       on a timeline with many gaps the owner's numbers are reached: N pictures + M clips exactly,
                every gap with fill_all; Avatarity's 8 s Veo animates lines the old 2.5-5.5 s window left out
  Fallback      Avatarity failing -> the backup (or nothing with it off); its allowance gone -> the rest on the
                backup; OpenRouter out of credit -> Avatarity goes on (no checks, no prompt writing)
  Units         plan units on each scene and in meta.aiFill.usage; $0 in the USD budget
"""
import os
import tempfile
import threading
import unittest
from unittest import mock

import tests  # noqa: F401 - SKIP_DOTENV and the offline switches
from src import aifill, avatarity, config, gapfill, timeline
from src.media import MediaAsset
from src.presenter.providers import ProviderError, VideoRequest
from src.transcribe import Segment, Word
from tests.test_aifill import ai_scenes, fixture
from tests.test_presenter import FakeProvider, FakeStore


class _Resp:
    def __init__(self, status, body=None, headers=None, content=b""):
        self.status_code, self._body, self.headers, self.content = status, body or {}, headers or {}, content
        self.text = str(body)

    def json(self):
        return self._body


class _Session:
    """Scripted answers per (method, url part); records every call."""

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


def _client(script, concurrency=4):
    return avatarity.Avatarity(api_key="test-key", session=_Session(script), sleep=lambda s: None,
                               concurrency=concurrency)


PLAN = {"AVATARITY_API_KEY": "test-key"}


# ------------------------------------------------------------------ the client
class Client(unittest.TestCase):
    def test_every_prompt_asks_for_the_whole_frame_and_no_text(self):
        p = avatarity.with_rules("x" * 2000)
        self.assertLessEqual(len(p), 1200)
        self.assertTrue(p.endswith(avatarity.NO_TEXT))
        for words in ("edge to edge", "no frame border", "no rounded corners", "No text", "no logos"):
            self.assertIn(words, avatarity.NO_TEXT)
        self.assertEqual(avatarity.with_rules("A dam. " + avatarity.NO_TEXT).count("edge to edge"), 1)

    def test_image_sync_and_ledger(self):
        c = _client({("POST", "/images/generations"): [_Resp(200, {"data": [{"url": "https://cdn/x.png"}]},
                                                             {"X-Avatarity-Remaining-Images": "4999"})],
                     ("GET", "https://cdn/x.png"): [_Resp(200, content=b"\x89PNG....")]})
        out = c.image("a dam at dawn", model="avatarity/nano-banana-pro", seed=5)
        self.assertEqual((out.url, out.ext), ("https://cdn/x.png", ".png"))
        body = c.http.last_body
        self.assertEqual((body["model"], body["size"]), ("nano-banana-pro", "1376x768"))
        self.assertIn("edge to edge", body["prompt"])
        self.assertIn("Idempotency-Key", c.http.last_headers)
        self.assertNotIn("test-key", str(out))
        self.assertEqual((c.ledger.images, c.remaining["images"]), (1, 4999))

    def test_a_429_waits_then_succeeds(self):
        c = _client({("POST", "/video/generations"): [
            _Resp(429, {"error": {"code": "CONCURRENCY_LIMIT"}}), _Resp(202, {"task_id": "t1"})],
            ("GET", "/tasks/t1"): [_Resp(200, {"status": "processing"}),
                                   _Resp(200, {"status": "succeeded", "video_url": "https://cdn/v.mp4"})],
            ("GET", "https://cdn/v.mp4"): [_Resp(200, content=b"mp4")]})
        out = c.video("drone over a dam", os.path.join(tempfile.mkdtemp(), "c.mp4"), image="https://cdn/s.png")
        self.assertEqual((out.task_id, out.units, c.ledger.video_units, c.ledger.retried), ("t1", 1, 1, 1))
        self.assertEqual((c.http.last_body["image"], c.http.last_body["resolution"]), ("https://cdn/s.png", "720p"))

    def test_an_idempotency_conflict_asks_again_with_a_fresh_key(self):
        # The live proof of 2026-11-03 waited 10 minutes on this 409 with the same key.
        c = _client({("POST", "/images/generations"): [_Resp(409, {"error": {"code": "IDEMPOTENCY_CONFLICT"}}),
                                                       _Resp(200, {"data": [{"url": "https://cdn/y.png"}]})],
                     ("GET", "https://cdn/y.png"): [_Resp(200, content=b"\x89PNG....")]})
        keys = []
        post = c.http.post

        def spy(url, headers=None, json=None, timeout=None):
            keys.append(headers["Idempotency-Key"])
            return post(url, headers=headers, json=json, timeout=timeout)
        c.http.post = spy
        out = c.image("a dry riverbed")
        self.assertEqual(out.url, "https://cdn/y.png")
        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])
        self.assertTrue(keys[1].startswith(keys[0]))
        # Never forever: a third conflict is an error, not a wait.
        c = _client({("POST", "/images/generations"): [_Resp(409, {"error": {"code": "IDEMPOTENCY_CONFLICT"}})] * 3})
        with self.assertRaises(avatarity.AvatarityError):
            c.image("a dry riverbed")

    def test_1080p_is_asked_as_720p_unless_allowed(self):
        # Their "1080p" came back 1280x720 for 2 units (2026-11-01).
        def run():
            c = _client({("POST", "/video/generations"): [_Resp(202, {"task_id": "t2"})],
                         ("GET", "/tasks/t2"): [_Resp(200, {"status": "succeeded", "video_url": "https://cdn/v.mp4"})],
                         ("GET", "https://cdn/v.mp4"): [_Resp(200, content=b"mp4")]})
            return c, c.video("x y z", os.path.join(tempfile.mkdtemp(), "c.mp4"), resolution="1080p")
        with mock.patch.dict(os.environ, {"AVATARITY_ALLOW_1080P": ""}):
            c, out = run()
            self.assertEqual((c.http.last_body["resolution"], out.units), ("720p", 1))
        with mock.patch.dict(os.environ, {"AVATARITY_ALLOW_1080P": "1"}):
            c, out = run()
            self.assertEqual((c.http.last_body["resolution"], out.units), ("1080p", 2))

    def test_allowance_and_policy_errors_are_typed(self):
        c = _client({("POST", "/images/generations"): [_Resp(402, {"error": {"code": "ALLOWANCE_EXHAUSTED"}}),
                                                       _Resp(400, {"error": {"code": "CONTENT_POLICY_VIOLATION"}})]})
        with self.assertRaises(avatarity.AllowanceError):
            c.image("abc")
        with self.assertRaises(avatarity.PolicyError):
            c.image("abd")


# ------------------------------------------------------------------ the routed provider
class Routed(unittest.TestCase):
    def setUp(self):
        avatarity._CLIENT.clear()

    def tearDown(self):
        avatarity._CLIENT.clear()

    def _routed(self, script, concurrency=1):
        c = _client(script, concurrency=concurrency)
        avatarity._CLIENT["test-key"] = c
        fb = FakeProvider()
        with mock.patch.dict(os.environ, PLAN):
            prov = avatarity.provider(fallback=fb)
        return prov, c, fb

    def test_a_clip_holds_a_render_slot_until_its_wait_ends(self):
        prov, c, _fb = self._routed({
            ("POST", "/video/generations"): [_Resp(202, {"task_id": "v1"})],
            ("GET", "/tasks/v1"): [_Resp(200, {"status": "succeeded", "video_url": "https://cdn/v.mp4"})]})
        job = prov.submit_video(VideoRequest(model="avatarity/veo-3.1-lite", prompt="a river", resolution="1080p",
                                             aspect_ratio="16:9", duration=8, first_frame="https://cdn/s.png"))
        self.assertEqual(c.http.last_body["resolution"], "720p")
        self.assertFalse(c.slots.acquire(blocking=False))          # the only slot is held by the clip
        got = prov.wait_video(job, timeout=5, poll=0.0, sleep=lambda s: None)
        self.assertEqual(got.status, "completed")
        self.assertTrue(c.slots.acquire(blocking=False))           # given back at the end of the wait
        c.slots.release()
        self.assertEqual(c.ledger.video_units, 1)

    def test_a_refused_submit_gives_the_slot_back_and_reads_as_model_gone(self):
        prov, c, _fb = self._routed({("POST", "/video/generations"): [
            _Resp(402, {"error": {"code": "ALLOWANCE_EXHAUSTED"}})]})
        with self.assertRaises(ProviderError) as ctx:
            prov.submit_video(VideoRequest(model="avatarity/veo-3.1-lite", prompt="a river"))
        self.assertEqual(ctx.exception.status, 404)
        self.assertTrue(aifill._model_gone(ctx.exception))
        self.assertTrue(c.slots.acquire(blocking=False))
        c.slots.release()

    def test_other_models_and_chat_go_to_openrouter(self):
        prov, _c, fb = self._routed({})
        prov.image(type("R", (), {"model": "google/gemini-nano-banana-2.1", "prompt": "x", "size": "1K",
                                  "aspect_ratio": "16:9", "references": []})())
        self.assertEqual(len(fb.images), 1)
        prov.chat("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
        self.assertEqual(len(fb.chats), 1)


# ------------------------------------------------------------------ the block
class Block(unittest.TestCase):
    def tearDown(self):
        aifill.reset()

    def test_pictures_and_clips_apart_with_the_new_limits(self):
        b = aifill.block({"ai_fill": {"enabled": True, "max_pictures": 120, "max_clips": 150}})
        self.assertEqual((b["max_pictures"], b["max_clips"], b["max_images"]), (120, 150, 270))   # clips > pictures
        b = aifill.block({"ai_fill": {"enabled": True, "max_pictures": 999, "max_clips": 999}})
        self.assertEqual((b["max_pictures"], b["max_clips"], b["max_images"]), (300, 200, 500))
        b = aifill.block({"ai_fill": {"enabled": True, "max_pictures": 0, "max_clips": 12}})
        self.assertEqual((b["max_pictures"], b["max_clips"], b["max_images"]), (0, 12, 12))       # clips only
        self.assertIsNone(aifill.block({"ai_fill": {"enabled": True, "max_pictures": 0, "max_clips": 0}}))

    def test_an_older_apps_block_keeps_its_meaning(self):
        b = aifill.block({"ai_fill": {"enabled": True, "max_images": 20, "max_clips": 3}})
        self.assertEqual((b["max_images"], b["max_clips"]), (20, 3))
        self.assertNotIn("max_pictures", b)
        b = aifill.block({"ai_fill": {"enabled": True, "max_images": 2, "max_clips": 5}})
        self.assertEqual((b["max_images"], b["max_clips"]), (2, 2))         # its clips are among its pictures

    def test_fill_all(self):
        b = aifill.block({"ai_fill": {"enabled": True, "fill_all": True, "max_clips": 40}})
        self.assertTrue(b["fill_all"])
        self.assertEqual((b["max_pictures"], b["max_clips"], b["max_images"]), (300, 40, 340))

    def test_the_backup_switch_and_the_openrouter_cap(self):
        with mock.patch.dict(os.environ, PLAN):
            b = aifill.block({"ai_fill": {"enabled": True, "max_pictures": 100, "max_clips": 50,
                                          "openrouter_fallback": False}})
            self.assertFalse(b["openrouter_fallback"])
            self.assertEqual(b["budget_usd"], aifill.checks_budget(150))       # only the checks and prompts
            self.assertEqual(aifill.checks_budget(150), 0.65)
            # A zero budget on the plan still makes pictures (only the checks stop).
            self.assertIsNotNone(aifill.block({"ai_fill": {"enabled": True, "budget_usd": 0}}))
            # The credit a job needs on OpenRouter before it starts: the checks' share, not the backup's $10.
            b = aifill.block({"ai_fill": {"enabled": True, "max_pictures": 300, "max_clips": 200, "budget_usd": 10}})
            self.assertTrue(b["openrouter_fallback"])
            self.assertEqual(aifill.openrouter_need(b), aifill.checks_budget(500))
        with mock.patch.dict(os.environ, {"AVATARITY_API_KEY": ""}):
            self.assertIsNone(aifill.block({"ai_fill": {"enabled": True, "budget_usd": 0}}))
            b = aifill.block({"ai_fill": {"enabled": True, "budget_usd": 3}})
            self.assertEqual(aifill.openrouter_need(b), 3.0)

    def test_resolution_is_720p(self):
        self.assertEqual(aifill.block({"ai_fill": {"enabled": True, "resolution": "1080p"}})["resolution"], "720p")


# ------------------------------------------------------------------ the chains
class Chains(unittest.TestCase):
    def tearDown(self):
        aifill.reset()

    def start(self, **blk):
        aifill.start({"ai_fill": {"enabled": True, **blk}}, work=tempfile.mkdtemp(), provider=FakeProvider(),
                     store=FakeStore())

    def test_no_key_keeps_the_openrouter_chains(self):
        with mock.patch.dict(os.environ, {"AVATARITY_API_KEY": ""}):
            self.start()
            self.assertFalse(any(aifill.is_plan_model(m) for m, _ in aifill.image_models() + aifill.video_models()))

    def test_avatarity_first_then_the_backup(self):
        with mock.patch.dict(os.environ, PLAN):
            self.start()
            self.assertEqual(aifill.image_models()[0], ("avatarity/nano-banana-pro", "2K"))
            self.assertEqual(aifill.video_models()[0], ("avatarity/veo-3.1-lite", "720p"))
            self.assertEqual(aifill.image_models()[1][0], "google/gemini-nano-banana-2.1")
            self.assertEqual(aifill.image_usd("avatarity/nano-banana-pro", "2K"), 0.0)
            self.assertEqual(aifill.clip_usd_per_second("avatarity/veo-3.1-lite", "720p"), 0.0)
            self.assertEqual(aifill._clip_len("avatarity/veo-3.1-lite", 7.0), 8)
            self.assertIsNone(aifill._clip_len("avatarity/veo-3.1-lite", 9.0))
            self.assertEqual(aifill.report()["provider"], "avatarity")

    def test_backup_off_is_avatarity_only(self):
        with mock.patch.dict(os.environ, PLAN):
            self.start(openrouter_fallback=False)
            self.assertEqual(aifill.image_models(), [("avatarity/nano-banana-pro", "2K")])
            self.assertEqual(aifill.video_models(), [("avatarity/veo-3.1-lite", "720p")])

    def test_openrouter_picked_in_the_app(self):
        with mock.patch.dict(os.environ, PLAN):
            self.start(provider="openrouter")
            self.assertFalse(any(aifill.is_plan_model(m) for m, _ in aifill.image_models()))


# ------------------------------------------------------------------ the numbers reached
def _all_gaps_doc():
    """The fixture's 18-line timeline with every line but the data look empty (17 gaps, 3.4-7.1 s each)."""
    doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
    for s in doc["scenes"]:
        if (s.get("media") or {}).get("type") != "animation":
            s["media"] = {"type": "color", "url": "", "source": ""}
    return doc


class _PlanJob(unittest.TestCase):
    def setUp(self):
        aifill.reset()
        gapfill.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.env = mock.patch.dict(os.environ, PLAN)
        self.env.start()
        self.hd = mock.patch.object(avatarity, "hd_upscale", return_value="cpu")
        self.hd.start()

    def tearDown(self):
        self.hd.stop()
        self.env.stop()
        aifill.reset()
        gapfill.reset()
        self.tmp.cleanup()

    def start(self, block=None, provider=None):
        self.provider = provider or FakeProvider(clip_seconds=8.0)
        return aifill.start({"ai_fill": {"enabled": True, **(block or {})}}, work=self.work, project_id="proj",
                            job_id="job", provider=self.provider, store=FakeStore())

    @staticmethod
    def kinds(doc):
        made = ai_scenes(doc)
        return (sum(1 for s in made if s["media"]["type"] == "image"),
                sum(1 for s in made if s["media"]["type"] == "video"))


class Numbers(_PlanJob):
    def test_the_owners_two_numbers_are_both_reached(self):
        doc = _all_gaps_doc()
        empty = [s for s in doc["scenes"] if gapfill._empty(s)]
        self.assertEqual(len(empty), 17)
        self.start({"max_pictures": 5, "max_clips": 10})
        got = aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(self.kinds(doc), (5, 10))
        self.assertEqual((got["toMake"], got["clipLines"]), (15, 10))
        self.assertEqual(aifill.report()["skipped"].get("max_pictures"), 2)
        # Every picture and clip on the plan: Nano Banana Pro, then Veo from that line's own picture.
        self.assertTrue(all(r.model == "avatarity/nano-banana-pro" for r in self.provider.images))
        self.assertTrue(all(v.model == "avatarity/veo-3.1-lite" and v.resolution == "720p"
                            for v in self.provider.videos))
        self.assertEqual(len(self.provider.videos), 10)
        self.assertEqual(len(self.provider.images), 15)             # each clip had its own picture first

    def test_more_clips_than_pictures(self):
        doc = _all_gaps_doc()
        self.start({"max_pictures": 0, "max_clips": 12})
        aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(self.kinds(doc), (0, 12))

    def test_fill_all_fills_every_gap(self):
        doc = _all_gaps_doc()
        self.start({"fill_all": True, "max_clips": 4})
        aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(self.kinds(doc), (13, 4))
        self.assertFalse([s for s in doc["scenes"] if gapfill._empty(s)])

    def test_the_plans_8_s_veo_animates_lines_the_old_window_left_out(self):
        # The old OpenRouter window (2.5-5.5 s lines) left the 5.6-7.1 s lines as pictures.
        doc = _all_gaps_doc()
        fps = doc["fps"]
        long_lines = [s["id"] for s in doc["scenes"] if gapfill._empty(s) and s["durationInFrames"] / fps > 5.5]
        self.assertGreaterEqual(len(long_lines), 4)
        self.start({"max_pictures": 0, "max_clips": 17})
        aifill.fill_doc(doc, work=self.work, label="t")
        clips = {s["id"] for s in ai_scenes(doc) if s["media"]["type"] == "video"}
        self.assertEqual(len(clips), 17)
        self.assertTrue(set(long_lines) <= clips)

    def test_real_footage_is_never_replaced(self):
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        real = {s["id"]: dict(s["media"]) for s in doc["scenes"] if not gapfill._empty(s)}
        self.start({"max_pictures": 300, "max_clips": 200})
        aifill.fill_doc(doc, work=self.work, label="t")
        for s in doc["scenes"]:
            if s["id"] in real:
                self.assertEqual(s["media"], real[s["id"]])
        self.assertEqual(len(ai_scenes(doc)), 5)          # only the five gaps (the sixth is the data look)

    def test_a_big_pass_gets_a_bigger_time_box(self):
        self.start({"max_pictures": 300, "max_clips": 200})
        self.assertEqual(aifill.time_box(3, 1), float(config.AI_FILL_SECONDS))
        self.assertEqual(aifill.time_box(300, 200), float(config.AI_FILL_MAX_SECONDS))
        mid = aifill.time_box(40, 20)
        self.assertTrue(float(config.AI_FILL_SECONDS) < mid < float(config.AI_FILL_MAX_SECONDS), mid)


# ------------------------------------------------------------------ the backup
class Fallback(_PlanJob):
    def test_a_failed_avatarity_picture_goes_to_the_backup(self):
        prov = FakeProvider(fail_models={"avatarity/nano-banana-pro"}, clip_seconds=8.0)
        doc = _all_gaps_doc()
        self.start({"max_pictures": 2, "max_clips": 0}, provider=prov)
        aifill.fill_doc(doc, work=self.work, label="t")
        made = ai_scenes(doc)
        self.assertEqual(len(made), 2)
        self.assertTrue(all(s["semanticMetadata"]["aiFill"]["provider"] == "openrouter" for s in made))
        self.assertEqual(made[0]["semanticMetadata"]["aiFill"]["model"], "google/gemini-nano-banana-2.1")

    def test_backup_off_never_asks_openrouter(self):
        prov = FakeProvider(fail_models={"avatarity/nano-banana-pro"}, clip_seconds=8.0)
        doc = _all_gaps_doc()
        self.start({"max_pictures": 2, "max_clips": 0, "openrouter_fallback": False}, provider=prov)
        aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(ai_scenes(doc), [])
        self.assertTrue(all(aifill.is_plan_model(r.model) for r in prov.images))

    def test_allowance_gone_the_rest_on_the_backup(self):
        class OutOfUnits(FakeProvider):
            def image(self, req):
                if aifill.is_plan_model(req.model):
                    self.images.append(req)
                    raise ProviderError("Avatarity allowance is not available (ALLOWANCE_EXHAUSTED): model is not "
                                        "available", status=404)
                return super().image(req)
        prov = OutOfUnits(clip_seconds=8.0)
        doc = _all_gaps_doc()
        self.start({"max_pictures": 6, "max_clips": 0}, provider=prov)
        aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(len(ai_scenes(doc)), 6)
        rep = aifill.report()
        self.assertTrue(any("Avatarity" in f for f in rep["fallbacks"]))
        # The plan was asked once per picture already running at most, then never again.
        self.assertLessEqual(sum(1 for r in prov.images if aifill.is_plan_model(r.model)), config.AI_FILL_PARALLEL)

    def test_allowance_gone_with_the_backup_off_stops(self):
        class OutOfUnits(FakeProvider):
            def image(self, req):
                self.images.append(req)
                raise ProviderError("Avatarity allowance is not available: model is not available", status=404)
        doc = _all_gaps_doc()
        self.start({"max_pictures": 6, "max_clips": 0, "openrouter_fallback": False},
                   provider=OutOfUnits(clip_seconds=8.0))
        aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(ai_scenes(doc), [])
        self.assertIn("backup is off", aifill.report()["stopped"])

    def test_openrouter_out_of_credit_does_not_stop_the_plans_pictures(self):
        class BrokeOpenRouter(FakeProvider):
            def chat(self, model, messages, **kw):
                self.chats.append(messages)
                raise ProviderError("chat: HTTP 402: Insufficient credits", status=402)
        prov = BrokeOpenRouter(clip_seconds=8.0)
        doc = _all_gaps_doc()
        self.start({"max_pictures": 4, "max_clips": 2}, provider=prov)
        aifill.fill_doc(doc, work=self.work, label="t")
        self.assertEqual(self.kinds(doc), (4, 2))
        rep = aifill.report()
        self.assertNotIn("stopped", rep)
        self.assertTrue(any("OpenRouter is out of credit" in f for f in rep["fallbacks"]))
        self.assertEqual(len(prov.chats), 1)            # the first prompt-writing call; no checks after it

    def test_openrouter_out_of_credit_still_stops_an_openrouter_job(self):
        class Broke(FakeProvider):
            def image(self, req):
                self.images.append(req)
                raise ProviderError("image: HTTP 402: Insufficient credits", status=402)
        doc = _all_gaps_doc()
        with mock.patch.dict(os.environ, {"AVATARITY_API_KEY": ""}):
            self.start({"max_pictures": 3, "max_clips": 0}, provider=Broke())
            aifill.fill_doc(doc, work=self.work, label="t")
            self.assertEqual(aifill.report()["stopped"], "OpenRouter is out of credit")


# ------------------------------------------------------------------ units
class Units(_PlanJob):
    def test_units_on_each_scene_and_dollars_zero(self):
        doc = _all_gaps_doc()
        self.start({"max_pictures": 3, "max_clips": 2})
        aifill.fill_doc(doc, work=self.work, label="t")
        made = ai_scenes(doc)
        self.assertEqual(len(made), 5)
        for s in made:
            fill = s["semanticMetadata"]["aiFill"]
            self.assertEqual(fill["provider"], "avatarity")
            self.assertEqual(fill["units"]["images"], 1)
            self.assertEqual(fill["units"]["video"], 1 if s["media"]["type"] == "video" else 0)
            self.assertEqual(fill["usd"], 0.0)
        # Only the look checks were paid on OpenRouter (FakeProvider: $0.0005 a call).
        self.assertLess(aifill.report()["spentUsd"], 0.02)

    def test_usage_report_from_the_ledger(self):
        c = _client({("GET", "/usage"): [_Resp(200, {"plan": {"name": "Starter", "concurrency": 4},
                                                     "allowances": {"veo": {"granted": 2000, "remaining": 1850},
                                                                    "images": {"granted": 5000, "remaining": 4700}}})]})
        avatarity._CLIENT["test-key"] = c
        try:
            self.start({"max_pictures": 3, "max_clips": 2})
            c.ledger.images, c.ledger.video_units, c.ledger.clips = 5, 2, 2
            doc = {"scenes": [], "meta": {}}
            aifill.annotate(doc)
            u = doc["meta"]["aiFill"]["usage"]["avatarity"]
            self.assertEqual((u["pictureUnits"], u["clipUnits"]), (5, 2))
            self.assertEqual((u["remainingClips"], u["remainingPictures"], u["plan"]), (1850, 4700, "Starter"))
            # A render adds its own units to its timeline's.
            self.start({"max_pictures": 3, "max_clips": 2}, provider=FakeProvider())
            c.ledger.images, c.ledger.video_units = 1, 0
            self.assertEqual(aifill.usage(remote=False)["pictureUnits"], 1)
            aifill.reset()
            aifill.start({"ai_fill": {"enabled": True, "max_pictures": 3}}, work=self.work, doc=doc,
                         provider=FakeProvider(), store=FakeStore())
            c.ledger.images = 2
            self.assertEqual(aifill.usage(remote=False)["pictureUnits"], 7)
        finally:
            avatarity._CLIENT.clear()


class Concurrency(unittest.TestCase):
    def test_pictures_and_clips_share_the_slots(self):
        # The image call holds a slot through its own wait: with one slot a second caller waits.
        c = _client({}, concurrency=1)
        c.slots.acquire()
        took = []
        t = threading.Thread(target=lambda: took.append(c.slots.acquire(timeout=0.05)))
        t.start()
        t.join()
        self.assertEqual(took, [False])
        c.slots.release()


if __name__ == "__main__":
    unittest.main()
