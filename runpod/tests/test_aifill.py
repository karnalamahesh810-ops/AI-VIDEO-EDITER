"""
AI fill (src/aifill.py), offline: the ai_fill block, the prompts (the line in
the story's world, no text, never a real person), the build's gaps filled with
AI pictures before any hold or text card, the last resort's AI pictures, the
key lines' AI clips, the caps and the budget, the models' fallbacks, the
marks every other pass reads - and that a job WITHOUT the block is built
byte-for-byte as before (golden documents made with the base commit 536a8a3:
tests/fixtures/aifill_fixture.py). No network: the provider, the storage and
the checks' model are fakes (tests/test_presenter.py).
"""
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

import handler
from src import aifill, config, gapfill, hookcheck, ledger, library, quality, reclip, restore, stockblock, timeline
from src.media import MediaAsset
from src.presenter import PRESENTER_SOURCE
from src.presenter.providers import ProviderError
from src.transcribe import Segment, Word
from tests.test_presenter import FakeProvider, FakeStore

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("aifill_fixture", os.path.join(HERE, "fixtures", "aifill_fixture.py"))
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)
GOLDEN = {name: os.path.join(HERE, "fixtures", f"aifill_golden_{name}.json")
          for name in ("last_resort", "last_resort_capped", "plan")}


def dumps(doc, work=""):
    text = json.dumps(doc, sort_keys=True, indent=1, default=str)
    if work:
        text = text.replace(work.replace("\\", "\\\\"), "<work>").replace(work, "<work>")
    return text


def golden(name):
    with open(GOLDEN[name], encoding="utf-8") as fh:
        return fh.read()


def ai_scenes(doc):
    return [s for s in doc.get("scenes") or [] if aifill.is_ai_scene(s)]


class _Fresh(unittest.TestCase):
    """Every test starts and ends with no AI fill job."""

    def setUp(self):
        aifill.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name

    def tearDown(self):
        aifill.reset()
        gapfill.reset()
        self.tmp.cleanup()

    def start(self, block=None, provider=None, doc=None, **inp):
        self.provider = provider or FakeProvider()
        self.store = FakeStore()
        inp = dict(inp, ai_fill={"enabled": True, **(block or {})})
        return aifill.start(inp, work=self.work, project_id="proj", job_id="job", doc=doc,
                            provider=self.provider, store=self.store)


# ------------------------------------------------------------------ the block
class Block(unittest.TestCase):
    def test_no_block_nothing(self):
        for inp in ({}, {"ai_fill": None}, {"ai_fill": {}}, {"ai_fill": {"enabled": False}},
                    {"ai_fill": {"enabled": "off"}}, {"ai_fill": "yes"}, {"ai_fill": {"max_images": 0}}):
            self.assertIsNone(aifill.block(inp), inp)
        self.assertFalse(aifill.start({}, work=tempfile.gettempdir()))
        self.assertFalse(aifill.enabled())

    def test_defaults_and_clamps(self):
        self.assertEqual(aifill.block({"ai_fill": {"enabled": True}}),
                         {"enabled": True, "max_images": 20, "max_clips": 3, "budget_usd": 2.13})
        b = aifill.block({"ai_fill": {"enabled": True, "max_images": 500, "max_clips": 99, "budget_usd": "50"}})
        self.assertEqual((b["max_images"], b["max_clips"], b["budget_usd"]),
                         (aifill.MAX_IMAGES_LIMIT, aifill.MAX_CLIPS_LIMIT, config.AI_FILL_MAX_BUDGET))
        b = aifill.block({"ai_fill": {"enabled": True, "max_images": 2, "max_clips": 5}})
        self.assertEqual((b["max_images"], b["max_clips"]), (2, 2))         # a clip starts from a picture
        self.assertEqual(aifill.block({"ai_fill": True})["max_images"], 20)
        self.assertEqual(aifill.default_budget(20, 3), 2.13)                 # the app's formula

    def test_never_for_the_ai_presenter_style(self):
        self.assertIsNone(aifill.block({"video_style": "ai_presenter", "ai_fill": {"enabled": True}}))
        # The AI presenter's "Real footage & photos" (a footage style with a presenter block) takes it.
        self.assertIsNotNone(aifill.block({"video_style": "documentary", "presenter": {"presenter_id": "ruth"},
                                           "ai_fill": {"enabled": True}}))

    def test_models_from_the_environment(self):
        with mock.patch.object(config, "AI_FILL_IMAGE_MODELS", '[["a/b", "1K"], "c/d"]'):
            self.assertEqual(aifill.image_models(), [("a/b", "1K"), ("c/d", "")])
        with mock.patch.object(config, "AI_FILL_IMAGE_MODELS", "a/b, c/d-1.5"):
            self.assertEqual(aifill.image_models(), [("a/b", ""), ("c/d-1.5", "")])
        for bad in ("[not json", "not a model", "[]", ""):
            with mock.patch.object(config, "AI_FILL_IMAGE_MODELS", bad):
                self.assertEqual(aifill.image_models()[0], ("google/gemini-nano-banana-2.1", "2K"), bad)
        self.assertEqual([m for m, _ in aifill.video_models()], ["bytedance/seedance-1-5-pro", "google/veo-3.1-lite"])


# ------------------------------------------------------------------ the prompts
class Prompts(unittest.TestCase):
    STORY = {"kind": "history", "year": 1962, "places": ["Honolulu, Hawaii"],
             "people": ["Barack Obama Sr."], "cast": [{"name": "Barack Obama Sr.", "aliases": ["his father"]}],
             "sections": [{"from": 0, "to": 5, "when": "1962", "where": "Honolulu, Hawaii"}]}

    def test_the_line_in_the_storys_world_without_text(self):
        job = {"intent": "Lake Mead exposed shoreline drone footage (Nevada, 2026)", "context": "The lake keeps falling.",
               "scene_intent": {"desired_shots": ["aerial"], "locations": ["Lake Mead"], "time_context": "current"}}
        prompt, what, person = aifill.still_prompt(job, {"kind": "news", "sections": []}, 0)
        self.assertFalse(person)
        self.assertIn("aerial photograph", prompt)
        self.assertIn("Lake Mead exposed shoreline aerial view, Nevada, 2026", prompt)
        self.assertNotIn("footage", what.lower())
        self.assertIn("Setting: Lake Mead", prompt)
        self.assertIn("time: the present day", prompt)
        self.assertIn("No text anywhere", prompt)
        self.assertIn("logos", prompt)
        self.assertIn("The lake keeps falling.", prompt)

    def test_an_old_era_looks_its_age(self):
        job = {"intent": "a downtown street with cars", "context": "The city grew fast."}
        prompt, _w, _p = aifill.still_prompt(job, self.STORY, 2)
        self.assertIn("time: 1962", prompt)
        self.assertIn("colour film of that time", prompt)
        prompt, _w, _p = aifill.still_prompt(job, dict(self.STORY, sections=[{"from": 0, "to": 9, "when": "1931"}]), 2)
        self.assertIn("black-and-white", prompt)

    def test_a_person_line_never_draws_or_names_the_person(self):
        job = {"intent": "Barack Obama Sr. at the University of Hawaii campus", "subject_type": "person",
               "subject": "Barack Obama Sr.", "context": "Barack Obama Sr. arrived in Honolulu in 1959."}
        prompt, what, person = aifill.still_prompt(job, self.STORY, 1)
        self.assertTrue(person)
        self.assertNotIn("Obama", prompt)
        self.assertNotIn("narration", prompt)                      # the line names him: it is left out
        self.assertIn("University of Hawaii campus", prompt)
        self.assertIn("No recognisable face", prompt)

    def test_light_follows_the_line(self):
        self.assertIn("night", aifill.bible_for({"context": "At night the river rose."}, {}, 0)["light"])
        self.assertIn("storm", aifill.bible_for({"context": "The hurricane hit the coast."}, {}, 0)["light"])
        self.assertEqual(aifill.bible_for({"context": "The farms waited."}, {}, 0)["light"], "natural daylight")


# ------------------------------------------------------------------ without a block, nothing changes
class Unchanged(_Fresh):
    def test_last_resort_without_a_block_is_the_base_commits_byte_for_byte(self):
        for name, cap in (("last_resort_capped", 7.0), ("last_resort", 0.0)):
            doc = fixture.last_resort(timeline, gapfill, quality, config, mock, Segment, Word, MediaAsset,
                                      self.work, shot_max=cap)
            self.assertEqual(dumps(doc, self.work), golden(name), name)

    def test_the_plan_without_a_block_is_the_base_commits_byte_for_byte(self):
        def boom(*a, **kw):
            raise AssertionError("AI fill ran without a block")
        with mock.patch.object(aifill, "fill_doc", side_effect=boom), \
                mock.patch.object(aifill, "make_still", side_effect=boom):
            doc, work = fixture.plan_doc(handler, config, mock, tempfile, Segment, Word, MediaAsset)
        self.assertEqual(dumps(doc, work), golden("plan"))
        self.assertNotIn("aiFill", doc["meta"])

    def test_a_render_chunk_never_makes_one(self):
        self.start()
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        gapfill.hold_or_animate(doc, label="chunk", laddered=True, fresh=False)
        self.assertEqual(ai_scenes(doc), [])
        self.assertEqual(self.provider.images, [])


# ------------------------------------------------------------------ the build's gaps
class Plan(_Fresh):
    def plan(self, block=None, provider=None):
        """do_plan with a block (the handler starts the job's AI fill before do_plan: done here by hand)."""
        provider = provider or FakeProvider(clip_seconds=6.0)
        blk = {"enabled": True, **(block or {})}
        aifill.start({"ai_fill": blk}, work=self.work, provider=provider, store=FakeStore())
        doc, work = fixture.plan_doc(handler, config, mock, tempfile, Segment, Word, MediaAsset,
                                     extra_input={"ai_fill": blk})
        aifill.annotate(doc)            # (do_plan's own call comes after the colour grade the fixture stops at)
        return doc, provider

    def test_every_empty_line_gets_an_ai_picture_before_any_hold_or_text_card(self):
        doc, prov = self.plan({"max_clips": 0})
        base = json.loads(golden("plan"))
        self.assertEqual(base["meta"]["fallbackFill"]["lastResort"]["card"], 2)
        made = ai_scenes(doc)
        # The six lines nothing real was found for and the cut line's empty second piece; the figure's line
        # (a data look) is a graphic, not a gap.
        self.assertEqual(len(made), 6)
        self.assertEqual(doc["meta"]["fallbackFill"]["lastResort"].get("card", 0), 0)
        self.assertEqual(doc["meta"]["fallbackFill"]["lastResort"].get("held", 0), 0)
        for s in made:
            m = s["media"]
            self.assertEqual((m["type"], m["source"], m["generated"]), ("image", aifill.AI_SOURCE, True))
            self.assertTrue(os.path.isfile(m["url"]))
            self.assertTrue(s["reviewRequired"])
            self.assertIn("AI picture", s["reviewReason"])
            self.assertNotEqual(s["motion"], "none")
            self.assertEqual(s["semanticMetadata"]["aiFill"]["kind"], "still")
            self.assertEqual(s["semanticMetadata"]["provider"], aifill.AI_SOURCE)
        motions = [s["motion"] for s in made]
        self.assertGreater(len(set(motions)), 1)                        # free camera moves, not one move
        animation = [s for s in doc["scenes"] if (s.get("media") or {}).get("type") == "animation"]
        self.assertEqual(len(animation), 1)                              # the figure's data look is kept
        self.assertFalse([o for o in doc.get("overlays") or [] if o.get("type") == "highlight"])
        self.assertEqual(len(prov.images), 6)
        self.assertEqual(prov.images[0].model, "google/gemini-nano-banana-2.1")
        self.assertEqual((prov.images[0].size, prov.images[0].aspect_ratio), ("2K", "16:9"))
        rep = doc["meta"]["aiFill"]
        self.assertEqual((rep["images"], rep["clips"], rep["inTimeline"]["images"]), (6, 0, 6))
        self.assertGreater(rep["spentUsd"], 0)
        self.assertEqual(doc["meta"]["warnings"][0], aifill.DISCLOSURE)

    def test_the_opening_first_under_the_cap(self):
        doc, prov = self.plan({"max_images": 2, "max_clips": 0})
        made = ai_scenes(doc)
        self.assertEqual(len(made), 2)
        fps = doc["fps"]
        self.assertTrue(all(s["startFrame"] / fps < config.HOOK_SECONDS for s in made))
        self.assertEqual(len(prov.images), 2)
        self.assertEqual(doc["meta"]["aiFill"]["images"], 2)
        self.assertGreaterEqual(doc["meta"]["aiFill"]["skipped"].get("max_images, the budget or a stop", 0), 1)

    def test_key_lines_become_ai_clips(self):
        doc, prov = self.plan({"max_images": 20, "max_clips": 1})
        clips = [s for s in ai_scenes(doc) if s["media"]["type"] == "video"]
        self.assertEqual(len(clips), 1)
        s = clips[0]
        self.assertLess(s["startFrame"] / doc["fps"], config.HOOK_SECONDS)       # the opening first
        self.assertEqual(s["semanticMetadata"]["aiFill"]["kind"], "clip")
        self.assertGreater(s["media"]["clipSeconds"], s["durationInFrames"] / doc["fps"] - 0.05)
        self.assertEqual(len(prov.videos), 1)
        req = prov.videos[0]
        self.assertEqual((req.model, req.resolution, req.generate_audio), ("bytedance/seedance-1-5-pro", "720p", False))
        self.assertIn(req.duration, (4, 5, 6))
        self.assertTrue(req.first_frame.startswith("https://") or req.first_frame.startswith("data:image"))
        self.assertEqual(doc["meta"]["aiFill"]["clips"], 1)

    def test_the_budget_is_a_hard_cap(self):
        doc, prov = self.plan({"max_images": 20, "max_clips": 0, "budget_usd": 0.15})
        # $0.053 a picture reserved at 1.25x plus its check: two fit, the third does not.
        self.assertLessEqual(len(ai_scenes(doc)), 2)
        self.assertLessEqual(doc["meta"]["aiFill"]["spentUsd"], 0.15)


# ------------------------------------------------------------------ the last resort's AI pictures
class LastResort(_Fresh):
    def test_text_cards_and_long_holds_become_ai_pictures(self):
        self.start({"max_clips": 0})
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        with mock.patch.object(config, "SHOT_MAX_SECONDS", 7.0):
            got = gapfill.hold_or_animate(doc, label="t", laddered=True, search=False)
        self.assertGreater(got.get("ai", 0), 0)
        self.assertEqual(got.get("card", 0), 0)
        for s in ai_scenes(doc):
            self.assertEqual(s["semanticMetadata"]["aiFill"]["why"],
                             "it would otherwise be a text card or a held picture")

    def test_presenter_teaser_and_document_lines_are_never_filled(self):
        self.start({"max_clips": 0})
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        empties = [s for s in doc["scenes"] if gapfill._empty(s)]
        empties[0]["media"] = {"type": "video", "url": "https://r2.example/p.mp4", "source": PRESENTER_SOURCE}
        empties[1]["teaser"] = True
        empties[2]["semanticMetadata"]["subjectType"] = "document"
        aifill.fill_doc(doc, work=self.work, label="t")
        filled = {s["id"] for s in ai_scenes(doc)}
        self.assertNotIn(empties[1]["id"], filled)
        self.assertNotIn(empties[2]["id"], filled)
        self.assertEqual(len(filled), len(empties) - 3)
        self.assertEqual(aifill.report()["skipped"].get("a document line (never a made-up record)"), 1)

    def test_a_line_tried_once_is_not_paid_for_again(self):
        prov = FakeProvider(fail_models={m for m, _ in aifill.image_models()})
        self.start({"max_clips": 0}, provider=prov)
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc, work=self.work, label="first")
        asked = len(prov.images)
        self.assertGreater(asked, 0)
        aifill.fill_doc(doc, work=self.work, label="again")
        self.assertEqual(len(prov.images), asked)
        self.assertEqual(ai_scenes(doc), [])


# ------------------------------------------------------------------ the models, the checks, the stops
class Models(_Fresh):
    def doc_with_one_gap(self):
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        keep = next(s for s in doc["scenes"] if gapfill._empty(s))
        for s in doc["scenes"]:
            if s is not keep and gapfill._empty(s):
                s["media"] = {"type": "image", "url": "https://x/real.jpg", "source": "wikimedia"}
        return doc, keep

    def test_a_model_openrouter_does_not_have_is_skipped_unpaid(self):
        class Gone(FakeProvider):
            def image(self, req):
                if req.model == "google/gemini-nano-banana-2.1":
                    self.images.append(req)
                    raise ProviderError("image: HTTP 400: google/gemini-nano-banana-2.1 is not a valid model ID",
                                        status=400)
                return super().image(req)
        prov = Gone()
        self.start({"max_clips": 0}, provider=prov)
        doc, gap = self.doc_with_one_gap()
        aifill.fill_doc(doc, work=self.work)
        self.assertTrue(aifill.is_ai_scene(gap))
        self.assertEqual(gap["semanticMetadata"]["aiFill"]["model"], "google/gemini-3.1-flash-image")
        self.assertEqual(prov.images[-1].size, "1K")

    def test_a_turned_down_picture_is_asked_again_with_the_fix(self):
        calls = {"n": 0}

        def verdict(text):
            if "picture editor" not in text:
                return {}                       # the descriptions call: no answer, the rule-built prompts stand
            calls["n"] += 1
            if calls["n"] == 1:
                return {"real": 0.9, "match": 0.9, "issues": ["garbled_text"]}
            return {"real": 0.9, "match": 0.9, "issues": []}
        prov = FakeProvider(verdict=verdict)
        self.start({"max_clips": 0}, provider=prov)
        doc, gap = self.doc_with_one_gap()
        aifill.fill_doc(doc, work=self.work)
        self.assertTrue(aifill.is_ai_scene(gap))
        self.assertEqual(len(prov.images), 2)
        self.assertEqual(prov.images[1].model, prov.images[0].model)            # the same model, once more
        self.assertIn("no legible letters", prov.images[1].prompt)

    def test_out_of_credit_stops_ai_fill_for_the_job(self):
        class Broke(FakeProvider):
            def image(self, req):
                self.images.append(req)
                raise ProviderError("image: HTTP 402: Insufficient credits", status=402)
        prov = Broke()
        self.start({"max_clips": 0}, provider=prov)
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc, work=self.work)
        self.assertEqual(ai_scenes(doc), [])
        self.assertLessEqual(len(prov.images), config.AI_FILL_PARALLEL)
        self.assertEqual(aifill.report()["stopped"], "OpenRouter is out of credit")
        self.assertFalse(aifill.can_make())

    def test_no_key_no_calls(self):
        class NoKey(FakeProvider):
            def available(self):
                return False
        self.start(provider=NoKey())
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc, work=self.work)
        self.assertEqual(ai_scenes(doc), [])
        self.assertIn("key", aifill.report()["stopped"])

    def test_a_clip_that_fails_leaves_the_picture(self):
        prov = FakeProvider(fail_models={m for m, _ in aifill.video_models()}, clip_seconds=6.0)
        self.start({"max_clips": 3}, provider=prov)
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc, work=self.work)
        made = ai_scenes(doc)
        self.assertTrue(made)
        self.assertTrue(all(s["media"]["type"] == "image" for s in made))
        self.assertGreaterEqual(len(prov.videos), 1)


class Describing(FakeProvider):
    """Answers the descriptions call like the prompt model: a bible and one picture per line."""

    def __init__(self, still="a dry irrigation well beside a cotton field, its pump hanging above the water, wide "
                             "shot in hard afternoon light", **kw):
        super().__init__(**kw)
        self.still = still
        self.described = []

    def chat(self, model, messages, **kw):
        text = messages[-1]["content"]
        if "ONE photograph that shows what this line is about" not in str(text):
            return super().chat(model, messages, **kw)
        self.chats.append(messages)
        rows = json.loads(text[text.rindex("\n\n") + 2:])["lines"]
        self.described.append(rows)
        from src.presenter.providers import ChatResult
        body = {"bible": {"place": "the Texas Panhandle", "era": "the present day", "light": "hard afternoon sun",
                          "palette": "dusty browns"},
                "lines": [{"i": r["i"], "still": f"{self.still} ({r['i']})",
                           "motion": "A slow push in; dust drifts across the field"} for r in rows]}
        return ChatResult(text=json.dumps(body), cost=0.001, model=model, seconds=0.1)


class Descriptions(_Fresh):
    def test_the_prompt_model_describes_each_picture(self):
        prov = Describing()
        self.start({"max_clips": 0}, provider=prov)
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc, work=self.work, story=fixture.STORY)
        made = ai_scenes(doc)
        self.assertTrue(made)
        self.assertEqual(len(prov.described), 1)                         # one call for every line of the pass
        rows = prov.described[0]
        self.assertTrue(all(set(r) >= {"i", "text", "before", "after"} for r in rows))
        for req in prov.images:
            self.assertIn("a dry irrigation well beside a cotton field", req.prompt)
            self.assertIn("Setting: Texas Panhandle", req.prompt)              # the line's own section wins
            self.assertIn("colours: dusty browns", req.prompt)
            self.assertIn("No text anywhere", req.prompt)
            self.assertNotIn("The narration at this moment says", req.prompt)
        self.assertEqual(made[0]["semanticMetadata"]["aiFill"]["describedBy"], "google/gemini-2.5-flash")
        # A re-run asks for the same pictures: the descriptions and the pictures come from the cache, unpaid.
        aifill.reset()
        prov2 = Describing(still="something else entirely")
        self.start({"max_clips": 0}, provider=prov2)
        doc2 = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc2, work=self.work, story=fixture.STORY)
        self.assertEqual((prov2.described, prov2.images), ([], []))
        again = ai_scenes(doc2)
        self.assertEqual(len(again), len(made))
        self.assertIn("a dry irrigation well", again[0]["semanticMetadata"]["aiFill"]["prompt"])
        self.assertEqual(again[0]["semanticMetadata"]["aiFill"]["cached"], "disk")

    def test_a_named_person_never_reaches_the_image_model(self):
        prov = Describing(still="Barack Obama Sr. walking across the University of Hawaii campus, seen from behind")
        self.start({"max_clips": 0}, provider=prov)
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        story = dict(fixture.STORY, people=["Barack Obama Sr."])
        aifill.fill_doc(doc, work=self.work, story=story)
        self.assertTrue(prov.images)
        for req in prov.images:
            self.assertNotIn("Obama", req.prompt)
            self.assertIn("University of Hawaii campus", req.prompt)

    def test_without_an_answer_the_rule_built_prompt_stands(self):
        self.start({"max_clips": 0})                      # FakeProvider: its chat is no descriptions answer
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        aifill.fill_doc(doc, work=self.work, story=fixture.STORY)
        self.assertTrue(ai_scenes(doc))
        self.assertTrue(all("The narration at this moment says" in r.prompt for r in self.provider.images))


# ------------------------------------------------------------------ a render counts what its timeline shows
class Render(_Fresh):
    def test_the_caps_count_the_timelines_own_ai_pictures(self):
        doc = fixture.gap_doc(timeline, Segment, Word, MediaAsset)
        for s in doc["scenes"][:3]:
            s["media"] = {"type": "image", "url": "https://r2.example/a.jpg", "source": aifill.AI_SOURCE,
                          "generated": True}
        doc["meta"]["aiFill"] = {"spentUsd": 0.2}
        self.start({"max_images": 4, "budget_usd": 1.0}, doc=doc)
        rep = aifill.report(doc)
        self.assertEqual(rep["before"], {"images": 3, "clips": 0, "usd": 0.2})
        self.assertEqual(aifill._images_left(), 1)
        self.assertAlmostEqual(aifill._STATE["budget"].cap, 0.8)


# ------------------------------------------------------------------ every other pass reads the mark
class Marks(unittest.TestCase):
    def scene(self, kind="image"):
        return {"id": "s0003", "startFrame": 0, "durationInFrames": 90, "text": "x",
                "media": {"type": kind, "url": "/tmp/aifill_s0003.jpg", "source": aifill.AI_SOURCE, "generated": True},
                "semanticMetadata": {"provider": aifill.AI_SOURCE}}

    def test_the_footage_passes_leave_ai_scenes_alone(self):
        s = self.scene()
        self.assertTrue(aifill.is_ai_scene(s))
        self.assertEqual(hookcheck._hook_shot(s), "")
        self.assertEqual(library.shown_rows({"scenes": [s]}, "proj"), [])
        self.assertIn(aifill.AI_SOURCE, library._NEVER_SOURCES)
        self.assertIn(aifill.AI_SOURCE, ledger._NEVER)
        self.assertEqual(ledger.items_from_doc({"fps": 30, "scenes": [s]}), [])
        self.assertEqual(stockblock.asset_reason({"source": aifill.AI_SOURCE, "url": "https://shutterstock.com/x"}), "")
        self.assertEqual(reclip.weakness(s), 1.0)
        self.assertIn(aifill.AI_SOURCE, restore.NO_ORIGIN)
        self.assertEqual(quality._how(MediaAsset(kind="image", source=aifill.AI_SOURCE, url="")), "an AI picture")


# ------------------------------------------------------------------ the handler
class Handler(unittest.TestCase):
    def tearDown(self):
        aifill.reset()

    def test_the_job_starts_and_ends_ai_fill(self):
        seen = {}

        def plan_document(inp, work, report):
            seen["enabled"] = aifill.enabled()
            raise RuntimeError("stop here")
        with mock.patch.object(handler, "_plan_document", side_effect=plan_document), \
                mock.patch.object(handler, "_require_youtube"):
            out = handler.handler({"id": "t-aifill", "input": {"action": "plan", "audio_url": "x",
                                                               "allow_youtube": False,
                                                               "ai_fill": {"enabled": True, "max_images": 4}}})
        self.assertFalse(out["ok"])
        self.assertTrue(seen["enabled"])
        self.assertFalse(aifill.enabled())                       # reset when the job ends

    def test_health_says_whether_openrouter_is_reachable(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}):
            out = aifill.health()                     # (the health action's own "aiFill"; no call is made)
        self.assertEqual(out["key"], True)
        self.assertEqual(out["pictures"][0], "google/gemini-nano-banana-2.1")
        self.assertIn("bytedance/seedance-1-5-pro", out["clips"])
        self.assertIn("aifill.health()", open(handler.__file__, encoding="utf-8").read())

    def test_the_presenters_real_footage_mix_keeps_its_ai_fill(self):
        from src.presenter import hybrid
        inp = {"action": "build", "video_style": "documentary", "presenter": {"presenter_id": "ruth"},
               "ai_fill": {"enabled": True, "max_images": 10}}
        hybrid.force_config(inp)                      # what the handler does for a presenter block
        self.assertEqual(aifill.block(inp)["max_images"], 10)

    def test_a_job_without_the_block_has_none(self):
        seen = {}

        def plan_document(inp, work, report):
            seen["enabled"] = aifill.enabled()
            raise RuntimeError("stop here")
        with mock.patch.object(handler, "_plan_document", side_effect=plan_document):
            handler.handler({"id": "t-aifill2", "input": {"action": "plan", "audio_url": "x", "allow_youtube": False}})
        self.assertFalse(seen["enabled"])


if __name__ == "__main__":
    unittest.main()
