"""
No plain text-card scenes when real visuals are possible (2026-10-14; Mount St. Helens 38f630df: 17 lines left
as text cards at the build, then the render's quality gate filled them - and the same red card stayed over
those and 10 other shots).

- the rescue before a text card (NO_EMPTY_RESCUE): the ladder once more for just the lines about to become
  cards, the cross-video ledger relaxed (LEDGER_RELAX_LAST_RESORT);
- a line's card leaves the timeline once anything real shows on its frames (STALE_CARD_SWEEP);
- the very last resort's text looks take turns (TEXT_LOOK_VARY).

Offline: the ladder is a stub.
"""
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from src import config, gapfill, ledger, quality, templates

FPS = 30
EMPTY = {"type": "color", "url": "", "source": "none"}


def scene(n, start, secs, media_dict, text=None):
    return {"id": f"s{n:04d}", "startFrame": int(start * FPS), "durationInFrames": int(secs * FPS),
            "text": text or f"line {n} about the slope above the road", "media": dict(media_dict),
            "motion": "none", "semanticMetadata": {"subject": "SR 504 slope", "subjectType": "place"},
            "visualType": "footage"}


def card(s):
    return {"type": "highlight", "text": s["text"][:180], "startFrame": s["startFrame"],
            "durationInFrames": s["durationInFrames"]}


def clip(url):
    return {"type": "video", "url": url, "source": "youtube", "clipSeconds": 3.0}


class StaleCards(unittest.TestCase):
    def test_a_card_over_a_line_that_now_shows_a_clip_goes(self):
        a, b = scene(1, 0, 3, clip("https://r2/a.mp4")), scene(2, 3, 3, EMPTY)
        doc = {"fps": FPS, "scenes": [a, b], "overlays": [card(a), card(b), {"type": "chapter", "text": "x"}]}
        with mock.patch.multiple(config, STALE_CARD_SWEEP=True):
            self.assertEqual(gapfill.drop_stale_cards(doc), 1)
        self.assertEqual([o.get("text") for o in doc["overlays"]], [b["text"], "x"])   # the empty line keeps its card

    def test_a_card_of_a_line_held_over_by_the_shot_beside_it_goes(self):
        held = scene(1, 0, 6, clip("https://r2/a.mp4"), text="First line. Second line about the gate.")
        doc = {"fps": FPS, "scenes": [held], "overlays": [
            {"type": "highlight", "text": "Second line about the gate.", "startFrame": 90, "durationInFrames": 90}]}
        with mock.patch.multiple(config, STALE_CARD_SWEEP=True):
            self.assertEqual(gapfill.drop_stale_cards(doc), 1)

    def test_a_planned_highlight_of_other_words_or_with_a_template_stays(self):
        a = scene(1, 0, 3, clip("https://r2/a.mp4"))
        doc = {"fps": FPS, "scenes": [a], "overlays": [
            {"type": "highlight", "text": "300,000 yards", "startFrame": 0, "durationInFrames": 90},
            dict(card(a), template="SOME_LOOK")]}
        with mock.patch.multiple(config, STALE_CARD_SWEEP=True):
            self.assertEqual(gapfill.drop_stale_cards(doc), 0)

    def test_off_nothing_is_touched(self):
        a = scene(1, 0, 3, clip("https://r2/a.mp4"))
        doc = {"fps": FPS, "scenes": [a], "overlays": [card(a)]}
        with mock.patch.multiple(config, STALE_CARD_SWEEP=False):
            self.assertEqual(gapfill.drop_stale_cards(doc), 0)


class LedgerRelaxed(unittest.TestCase):
    def test_relaxed_only_inside(self):
        with mock.patch.multiple(config, CROSS_VIDEO_REUSE_DAYS=120, LEDGER_RELAX_LAST_RESORT=True):
            self.assertTrue(ledger.on())
            with ledger.relaxed():
                self.assertFalse(ledger.on())
                self.assertFalse(ledger.moment_used("AAAAAAAAAAA", 10, 20))
            self.assertTrue(ledger.on())

    def test_flag_off_keeps_the_rule(self):
        with mock.patch.multiple(config, CROSS_VIDEO_REUSE_DAYS=120, LEDGER_RELAX_LAST_RESORT=False):
            with ledger.relaxed():
                self.assertTrue(ledger.on())


class Rescue(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        gapfill.CONTEXT.clear()

    def tearDown(self):
        gapfill.CONTEXT.clear()

    def _doc(self):
        # Clips that cannot be held over the long empty line (each just covers its own scene).
        return {"fps": FPS, "overlays": [], "meta": {}, "scenes": [
            scene(0, 0, 3, clip("https://r2/a.mp4")), scene(1, 3, 12, EMPTY), scene(2, 15, 3, clip("https://r2/c.mp4"))]}

    def _flags(self, **more):
        base = dict(NO_EMPTY_RESCUE=True, NO_EMPTY_RESCUE_SECONDS=150.0, LEDGER_RELAX_LAST_RESORT=True,
                    CROSS_VIDEO_REUSE_DAYS=120, STALE_CARD_SWEEP=True, ANIMATION_FILL=False, HOOK_SECONDS=0.0,
                    NO_TEXT_FILL=True, NO_TEXT_HOLD_MAX=18.0, SHOT_MAX_SECONDS=7.0, FALLBACK_MOMENTS=False,
                    FALLBACK_FILL=True)
        base.update(more)
        return mock.patch.multiple(config, **base)

    def test_a_line_about_to_be_a_card_gets_the_ladder_with_the_ledger_relaxed(self):
        doc, seen = self._doc(), {}

        def ladder(jobs, results, work, **kw):
            seen.update(kw, relaxed=not ledger.on(), place=jobs[1].get("place"))
            for i in kw["indices"]:
                results[i] = SimpleNamespace(kind="image", source="web_image", url="/w/slope.jpg", identity="p1",
                                             content_description="", relevance_score=0.7, quality=0.7, moment={},
                                             review_reason="", judged_by="", cut_check=None,
                                             to_scene_media=lambda: {"type": "image", "url": "/w/slope.jpg",
                                                                     "source": "web_image"})
            return {"asked": len(kw["indices"])}
        with self._flags(), mock.patch.object(gapfill, "fill_empty", side_effect=ladder), \
                mock.patch.object(gapfill, "_living"):
            got = gapfill.hold_or_animate(doc, laddered=True, search=True, work=self.work)
        self.assertEqual(got["card"], 0)
        self.assertEqual(got.get("rescue"), 1)
        self.assertTrue(seen["relaxed"])
        self.assertEqual(seen["place"], "")
        self.assertTrue(seen["keep_order"])
        self.assertLessEqual(seen["seconds"], 150.0)
        self.assertEqual(doc["scenes"][1]["media"]["url"], "/w/slope.jpg")
        self.assertEqual(doc["overlays"], [])

    def test_no_rescue_without_a_fetch_or_with_the_flag_off(self):
        for flags, kw in ((dict(NO_EMPTY_RESCUE=False), dict(search=True, work=self.work)),
                          ({}, dict(search=True, work=self.work, fresh=False)),
                          ({}, dict(search=True, work=self.work, rescue=False))):
            doc = self._doc()
            with self._flags(**flags), mock.patch.object(gapfill, "fill_empty",
                                                         side_effect=AssertionError("no rescue")):
                got = gapfill.hold_or_animate(doc, laddered=True, **kw)
            self.assertEqual(got["card"], 1, (flags, kw))


class VariedTextLooks(unittest.TestCase):
    def test_the_last_resort_text_looks_take_turns(self):
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(k, 3 * k, 3, EMPTY) for k in range(3)]}
        looks = [x for x in quality.TEXT_LOOKS if templates.get(x)]
        if len(looks) < 2:
            self.skipTest("fewer than two text looks in the registry")
        with mock.patch.multiple(config, TEXT_LOOK_VARY=True), mock.patch.object(templates, "allowed",
                                                                                return_value=None):
            for s in doc["scenes"]:
                quality.text_scene(doc, s)
        names = {str(s["animation"].get("template") or s["animation"].get("id") or s["animation"].get("type"))
                 for s in doc["scenes"]}
        self.assertGreater(len(names), 1, names)


if __name__ == "__main__":
    unittest.main()
