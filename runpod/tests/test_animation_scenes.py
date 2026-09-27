import unittest
from unittest import mock

import handler
from src import config, timeline, treatments, templates
from src.transcribe import Segment
from tests.test_pipeline import simple_plan


def seg(text, i=0, dur=6.0):
    return Segment(text=text, start=i * dur, end=(i + 1) * dur)


class AnimationFor(unittest.TestCase):
    """What fills a beat with no footage is decided by the line."""

    def setUp(self):
        self.pack = treatments.pack_for({"kind": "explainer"}, "documentary")

    def test_a_figure_gets_a_number_card(self):
        a = treatments.animation_for(seg("Lake Mead is now at 26% capacity."), {"subject": "Lake Mead"}, self.pack, None)
        self.assertEqual((a["template"], a["type"], a["value"], a["suffix"]), ("NUM_PERCENT_V1", "stat", 26.0, "%"))
        self.assertNotIn("seconds", a)
        self.assertNotIn("sfx", a)

    def test_a_mapped_place_gets_the_packs_map(self):
        shot = {"subject": "Nevada", "overlay": {"type": "map", "text": "Nevada",
                                                 "locations": [{"label": "Nevada", "lat": 38.0, "lon": -117.0}]}}
        a = treatments.animation_for(seg("It sits in Nevada."), shot, self.pack, None)
        self.assertEqual(a["template"], self.pack["map"])
        self.assertEqual(a["locations"][0]["label"], "Nevada")

    def test_a_plain_line_gets_no_full_screen_card(self):
        # The full-screen layout is for figures, money and comparisons only.
        a = treatments.animation_for(seg("Boat ramps at Boulder Harbor end in dry gravel."), {"subject": "Boulder Harbor"},
                                     self.pack, None)
        self.assertIsNone(a)

    def test_money_gets_a_number_graphic_with_a_dollar_sign(self):
        a = treatments.animation_for(seg("The new intake cost $1.4 billion to build."), {"subject": "Lake Mead"},
                                     self.pack, None)
        self.assertEqual((a["prefix"], a["value"], a["suffix"]), ("$", 1.4, "B"))

    def test_only_cards_and_maps_fill_a_frame(self):
        a = treatments.animation_for(seg("Lake Mead is now at 26% capacity."), {"subject": "Lake Mead"}, self.pack, None)
        self.assertIn(templates.get(a["template"])["kind"], treatments.CARD_KINDS)


class WantsAnimation(unittest.TestCase):
    def _asset(self, score, reason="Licence unverified — confirm you hold the rights"):
        from src.media import MediaAsset
        return MediaAsset(kind="video", source="youtube", url="u", relevance_score=score,
                          review_required=True, review_reason=reason)

    def test_good_footage_with_a_licence_flag_stays_footage(self):
        with mock.patch.object(config, "ANIMATION_FILL", True):
            self.assertFalse(treatments.wants_animation(seg("Lake Mead is now at 26% capacity."), {"subject": "Lake Mead"},
                                                        self._asset(0.92), None))

    def test_weak_or_borrowed_footage_on_a_strong_beat_becomes_a_graphic(self):
        with mock.patch.object(config, "ANIMATION_FILL", True):
            self.assertTrue(treatments.wants_animation(seg("Lake Mead is now at 26% capacity."), {"subject": "Lake Mead"},
                                                       self._asset(0.5), None))
            self.assertTrue(treatments.wants_animation(seg("Lake Mead is now at 26% capacity."), {"subject": "Lake Mead"},
                                                       self._asset(0.9, "Reused shot of Lake Mead - no other footage"), None))

    def test_a_chart_moment_is_full_screen_even_over_good_footage(self):
        with mock.patch.object(config, "ANIMATION_FILL", True):
            self.assertTrue(treatments.wants_animation(
                seg("In 2020 the lake stood at 40 percent; by 2026 it was 26 percent."), {"subject": "Lake Mead"},
                self._asset(0.95), None))

    def test_a_plain_line_over_good_footage_stays_footage(self):
        with mock.patch.object(config, "ANIMATION_FILL", True):
            self.assertFalse(treatments.wants_animation(seg("Boat ramps end in dry gravel."), {"subject": "Boulder Harbor"},
                                                        self._asset(0.5), None))


class BuildFillsGaps(unittest.TestCase):
    def _doc(self, fill=True, text=None):
        segments, shots, assets = simple_plan(4, 6.0)
        if text is not None:
            segments[1].text = text
        assets[1] = None
        with mock.patch.object(config, "TREATMENTS", True), mock.patch.object(config, "ANIMATION_FILL", fill):
            return timeline.build(segments, shots, assets, audio_url="file:///tmp/vo.mp3",
                                  audio_duration=24.0, inp={"style_pack": "documentary"})

    def test_a_plain_empty_beat_stays_empty_for_the_borrow_step(self):
        doc = self._doc()
        self.assertEqual(doc["scenes"][1]["media"]["type"], "color")

    def test_the_empty_beat_becomes_an_animation_scene(self):
        doc = self._doc(text="Lake Mead is now at 26% capacity.")
        sc = doc["scenes"][1]
        self.assertEqual(sc["media"], {"type": "animation", "url": "", "source": "template"})
        self.assertEqual(sc["visualType"], "animation")
        self.assertTrue(sc["animation"]["template"])
        self.assertTrue(sc["reviewRequired"])
        self.assertIn("motion graphic", sc["reviewReason"])
        # It renders: an animation scene needs no url.
        timeline.validate(doc, require_media=True)
        # The planner puts nothing on top of it, and counts it.
        self.assertFalse([o for o in doc["overlays"] if o["startFrame"] == sc["startFrame"]
                          and o.get("template") and o.get("type") != "title"])
        self.assertEqual(doc["scenes"][1]["visualTreatment"]["primaryType"], "animation")
        self.assertEqual(doc["meta"]["treatments"]["animation_scenes"], 1)

    def test_switched_off_it_stays_an_empty_beat(self):
        doc = self._doc(fill=False, text="Lake Mead is now at 26% capacity.")
        self.assertEqual(doc["scenes"][1]["media"]["type"], "color")
        with self.assertRaises(ValueError):
            timeline.validate(doc, require_media=True)


class FillMissingMedia(unittest.TestCase):
    def test_an_empty_scene_gets_a_graphic_not_a_borrowed_clip(self):
        doc = {"fps": 30, "meta": {"stylePack": "documentary"}, "scenes": [
            {"id": "s0", "startFrame": 0, "durationInFrames": 90, "text": "Hoover Dam holds it back.",
             "media": {"type": "video", "url": "/tmp/a.mp4", "source": "youtube"}, "semanticMetadata": {"subject": "Hoover Dam"}},
            {"id": "s1", "startFrame": 90, "durationInFrames": 90, "text": "The lake is at 26% capacity.",
             "media": {"type": "color", "url": "", "source": "none"}, "semanticMetadata": {"subject": "Lake Mead"}},
        ]}
        with mock.patch.object(config, "TREATMENTS", True), mock.patch.object(config, "ANIMATION_FILL", True):
            self.assertEqual(handler._fill_missing_media(doc), 1)
        sc = doc["scenes"][1]
        self.assertEqual(sc["media"]["type"], "animation")
        self.assertEqual(sc["animation"]["template"], "NUM_PERCENT_V1")

    def test_an_animation_scene_is_never_borrowed_as_footage(self):
        doc = {"fps": 30, "meta": {}, "scenes": [
            {"id": "s0", "startFrame": 0, "durationInFrames": 90, "text": "one",
             "media": {"type": "animation", "url": "", "source": "template"}, "animation": {"template": "TEXT_TYPEWRITER_V1"}},
            {"id": "s1", "startFrame": 90, "durationInFrames": 90, "text": "two",
             "media": {"type": "color", "url": "", "source": "none"}},
        ]}
        with mock.patch.object(config, "ANIMATION_FILL", False):
            handler._fill_missing_media(doc)
        self.assertNotEqual(doc["scenes"][1]["media"]["type"], "animation")


if __name__ == "__main__":
    unittest.main()
