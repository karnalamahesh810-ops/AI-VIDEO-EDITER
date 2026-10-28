"""Clean cut (2026-10-28): the Hoover Dam video's own plan (63 graphics, 56 sounds, 165 crossfades; the compact copy
tests/fixtures/hoover_plan_2026-10-26.json) through the mode news_compilation now runs by default."""
import copy
import json
import os
import unittest
from unittest import mock

from src import cleancut, config, editing, styles

HERE = os.path.dirname(os.path.abspath(__file__))


def _plan():
    with open(os.path.join(HERE, "fixtures", "hoover_plan_2026-10-26.json"), encoding="utf-8") as fh:
        return json.load(fh)


class TheMode(unittest.TestCase):
    def test_news_compilation_is_clean_cut_by_default_and_a_job_can_switch_it(self):
        inp = {"video_style": "news_compilation"}
        styles.apply(inp)
        self.assertTrue(cleancut.fold_job(inp))
        cfg = inp["config"]
        self.assertTrue(cfg["CLEAN_CUT"])
        for k in ("DATA_GRAPHICS", "MARKS_ENABLED", "ANIMATION_FILL", "EDIT_V3_PUNCHES", "EDIT_V3_PUNCH_SOUND"):
            self.assertIs(cfg[k], False, k)
        self.assertEqual(cfg["STILL_MOTION_MAX_ZOOM"], 1.06)
        off = {"video_style": "news_compilation", "clean_cut": False}
        styles.apply(off)
        self.assertFalse(cleancut.fold_job(off))
        self.assertNotIn("EDIT_V3_PUNCHES", off["config"])

    def test_other_styles_keep_their_graphics_unless_the_job_asks(self):
        doc = {"video_style": "documentary"}
        styles.apply(doc)
        self.assertFalse(cleancut.fold_job(doc))
        on = {"video_style": "documentary", "clean_cut": True}
        styles.apply(on)
        self.assertTrue(cleancut.fold_job(on))
        self.assertIs(on["config"]["EDIT_V3_PUNCHES"], False)
        mine = {"video_style": "documentary", "clean_cut": True, "config": {"EDIT_V3_PUNCHES": True}}
        styles.apply(mine)
        cleancut.fold_job(mine)
        self.assertIs(mine["config"]["EDIT_V3_PUNCHES"], True)      # the job's own explicit choice wins

    def test_punch_whooshes_are_off_everywhere_by_default(self):
        self.assertFalse(config.EDIT_V3_PUNCH_SOUND)


class TheHooverPlan(unittest.TestCase):
    def setUp(self):
        self.doc = _plan()
        self.before = copy.deepcopy(self.doc)
        with mock.patch.multiple(config, CLEAN_CUT=True, CLEAN_CUT_NAMES=True, CLEAN_CUT_MAPS=True):
            self.rep = cleancut.apply(self.doc)

    def test_no_text_number_data_look_or_motion_card_is_left(self):
        kinds = [cleancut.kind_of(o) for o in self.doc["overlays"]]
        self.assertNotIn("graphic", kinds)
        self.assertFalse([o for o in self.doc["overlays"] if str(o.get("template") or "").startswith(
            ("KT_NUMBER", "KT_PERCENT", "KT_DATE", "KT_YEAR", "KT_MULTIPLIER", "KT_COMPARE", "LIB_RD_", "KT_POINTER",
             "LIB_VM_"))])
        self.assertFalse([s for s in self.doc["scenes"] if s["media"]["type"] == "animation"])
        self.assertEqual(self.rep["cards"], 1)
        self.assertGreaterEqual(self.rep["dropped"], 55)

    def test_names_and_place_maps_stay(self):
        names = [o for o in self.doc["overlays"] if cleancut.kind_of(o) == "name"]
        self.assertEqual([o.get("text") for o in names], ["JACK SCHMIDT"])
        self.assertTrue([o for o in self.doc["overlays"] if o["template"] == "KT_REGIONS"])

    def test_no_punch_look_or_transition_sound(self):
        self.assertFalse([s for s in self.doc["sfx"] if s.get("kind") in ("punch", "smart", "transition")])
        self.assertEqual(self.rep["sounds"], 56)

    def test_the_cuts_stay_straight_with_a_rare_short_crossfade(self):
        scenes = self.doc["scenes"]
        self.assertEqual(len(scenes), len(self.before["scenes"]) - 1)            # only the motion card went
        self.assertEqual(sum(s["durationInFrames"] for s in scenes),
                         sum(s["durationInFrames"] for s in self.before["scenes"]))
        for a, b in zip(scenes, scenes[1:]):
            self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
        trans = [s["transition"] for s in scenes[1:]]
        self.assertTrue(set(trans) <= {"none", "crossfade"})
        self.assertLessEqual(trans.count("crossfade"), len(trans) // cleancut.CROSSFADE_EVERY)
        self.assertGreater(trans.count("crossfade"), 0)

    def test_sub_flags_take_names_and_maps_away(self):
        doc = _plan()
        with mock.patch.multiple(config, CLEAN_CUT=True, CLEAN_CUT_NAMES=False, CLEAN_CUT_MAPS=False):
            cleancut.apply(doc)
        self.assertEqual([cleancut.kind_of(o) for o in doc["overlays"]], [])

    def test_ai_and_source_tags_always_stay(self):
        doc = _plan()
        doc["overlays"].append({"template": "LIB_SRC_TAG", "label": "AI", "text": "AI ILLUSTRATION", "startFrame": 0,
                                "durationInFrames": 60, "aiLabel": True})
        with mock.patch.multiple(config, CLEAN_CUT=True, CLEAN_CUT_NAMES=False, CLEAN_CUT_MAPS=False):
            cleancut.apply(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]], ["LIB_SRC_TAG"])


class EditingV3InCleanCut(unittest.TestCase):
    def test_no_punch_in_and_no_whoosh_with_the_clean_cut_config(self):
        from tests.test_editing import _doc, _scene
        doc = _doc([_scene(0, 0, 12, "The record flood broke every gauge on the river that week in October."),
                    _scene(1, 12, 12, "It was the biggest surge in ninety years of records.")])
        cfg = {k: v for k, v in cleancut.OVERRIDES.items() if k.startswith("EDIT_V3")}
        rep = editing.apply(doc, {"config": cfg})
        self.assertEqual(rep.get("punches", 0), 0)
        self.assertFalse([s for s in doc.get("sfx") or [] if s.get("kind") == "punch"])


if __name__ == "__main__":
    unittest.main()
