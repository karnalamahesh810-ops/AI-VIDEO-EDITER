import datetime
import unittest
from unittest import mock

from src import config, director, intent
from src.intent import SceneIntent
from src.transcribe import Segment

STORY = {"kind": "weather", "event": "New Mexico flash flooding", "year": 2026,
         "recent": True, "places": ["Albuquerque, New Mexico", "Ruidoso"], "people": []}


class Parse(unittest.TestCase):
    def test_model_scene_object_is_kept_and_anchored_beats_stay_event_specific(self):
        shot = {"subject": "Albuquerque", "entity": "city-region", "anchor": True, "query": "x"}
        raw = {"entities": ["Albuquerque", "Rio Grande"], "locations": ["New Mexico"],
               "eventType": "flash flood", "visualSubjects": ["flooded streets", "rescue boats"],
               "desiredShots": ["aerial", "human"], "timeContext": "current",
               "specificity": "generic", "genericOk": True}
        si = SceneIntent.parse(raw, shot, STORY)
        self.assertEqual(si.entities, ["Albuquerque", "Rio Grande"])
        self.assertEqual(si.locations, ["New Mexico"])
        self.assertEqual(si.event_type, "flash flood")
        self.assertEqual(si.specificity, "event")          # the story anchors it
        self.assertFalse(si.generic_ok)

    def test_gaps_are_filled_from_the_shot_and_story(self):
        shot = {"subject": "Lake Mead", "entity": "natural-feature", "subjectType": "place"}
        si = SceneIntent.parse({"visualSubjects": ["bathtub ring"]}, shot, {"kind": "explainer"})
        self.assertEqual(si.entities, ["Lake Mead"])
        self.assertEqual(si.specificity, "location")
        self.assertEqual(si.desired_shots, ["aerial"])
        self.assertTrue(si.generic_ok is False or si.specificity != "generic")

    def test_a_metaphor_beat_is_not_pinned_to_the_event(self):
        shot = {"subject": "freight train", "entity": "object", "anchor": False}
        si = SceneIntent.from_shot(shot, STORY)
        self.assertEqual(si.specificity, "generic")
        self.assertEqual(si.locations, [])
        self.assertEqual(si.event_type, "")


class Queries(unittest.TestCase):
    def test_five_to_fifteen_specific_searches_entity_first(self):
        si = SceneIntent(entities=["Lake Mead", "Hoover Dam"], locations=["Nevada"],
                         event_type="drought / reservoir decline",
                         visual_subjects=["exposed shoreline", "low water", "bathtub ring"],
                         desired_shots=["aerial", "wide"], time_context="current",
                         specificity="location", generic_ok=False)
        with mock.patch.object(intent, "_today", return_value=datetime.date(2026, 9, 27)):
            qs = si.queries("Lake Mead drought aerial footage", max_n=15)
        self.assertEqual(qs[0], "Lake Mead drought aerial footage")
        self.assertTrue(5 <= len(qs) <= 15, qs)
        self.assertIn("Lake Mead exposed shoreline", qs)
        self.assertIn("Lake Mead aerial drone footage", qs)
        self.assertIn("Lake Mead 2026 footage", qs)
        self.assertIn("Nevada drought / reservoir decline 2026", qs)
        self.assertEqual(len(qs), len({q.lower() for q in qs}))       # no duplicates
        self.assertTrue(all("Lake Mead" in q or "Nevada" in q or "Hoover" in q for q in qs))

    def test_historical_beats_search_archival_footage_of_their_year(self):
        si = SceneIntent(entities=["Barack Obama Sr."], locations=["Honolulu"],
                         time_context="1964", specificity="generic")
        with mock.patch.object(intent, "_today", return_value=datetime.date(2026, 9, 27)):
            qs = si.queries("Obama Sr 1964 Honolulu")
        self.assertIn("Barack Obama Sr. 1964 archival footage", qs)
        self.assertLessEqual(len(qs), config.INTENT_QUERIES_MAX)


class TitleMatch(unittest.TestCase):
    def test_distinctive_word_counts_generic_word_does_not(self):
        si = SceneIntent(entities=["Barack Obama Sr.", "New Mexico"], locations=["Albuquerque"],
                         visual_subjects=["flooded streets"])
        self.assertEqual(si.title_match("Obama's father: the Kenya years"), (1, 0, 0))
        self.assertEqual(si.title_match("New York flooding aerial"), (0, 0, 0))   # "New" alone is nothing
        self.assertEqual(si.title_match("Albuquerque flooded streets after storm"), (0, 1, 1))
        self.assertEqual(si.title_match("Mexico City traffic"), (1, 0, 0))         # "Mexico" carries New Mexico

    def test_vision_lines_name_the_check(self):
        si = SceneIntent(entities=["Lake Mead"], locations=["Nevada"], specificity="event",
                         event_type="drought", time_context="2026")
        text = si.vision_lines()
        self.assertIn("ENTITIES: Lake Mead", text)
        self.assertIn("LOCATIONS: Nevada", text)
        self.assertIn("SPECIFICITY: event", text)


class PlannerCarriesIntent(unittest.TestCase):
    def test_ai_pass_stores_the_scene_object(self):
        segments = [Segment(text="Lake Mead has fallen near Hoover Dam.", start=0.0, end=6.0)]
        shots = [director._rule_shot(segments[0], 0, "Lake Mead")]

        def fake_chat(system, payload, timeout=120, errors=None, **kw):
            return {"shots": [{"index": 0, "query": "Lake Mead Hoover Dam low water aerial",
                               "subject": "Lake Mead", "subjectType": "place", "entity": "natural-feature",
                               "intent": "Lake Mead 2026 low water aerial footage",
                               "scene": {"entities": ["Lake Mead", "Hoover Dam"], "locations": ["Nevada"],
                                         "eventType": "drought", "visualSubjects": ["low water"],
                                         "desiredShots": ["aerial"], "timeContext": "current",
                                         "specificity": "location", "genericOk": False}}]}
        with mock.patch.object(director, "_chat_json", fake_chat), \
                mock.patch.object(director.vision, "out_of_credits", return_value=False):
            director._ai_pass(segments, "Lake Mead", shots, brief={"kind": "explainer"})
        si = shots[0]["sceneIntent"]
        self.assertEqual(si["entities"], ["Lake Mead", "Hoover Dam"])
        self.assertEqual(si["specificity"], "location")

    def test_rule_plan_still_gets_an_intent_and_expanded_fallbacks(self):
        segments = [Segment(text="Lake Mead has fallen dramatically near Hoover Dam this year.",
                            start=0.0, end=6.0)]
        with mock.patch.object(director, "is_configured", return_value=False):
            shots, kind, _ = director.plan(segments, "Lake Mead", allow_maps=False)
        self.assertEqual(kind, "rules")
        self.assertEqual(shots[0]["sceneIntent"]["entities"], ["Lake Mead"])
        self.assertGreaterEqual(len(shots[0]["fallbacks"]), 2)
        self.assertTrue(any(f.startswith("Lake Mead") for f in shots[0]["fallbacks"]))


if __name__ == "__main__":
    unittest.main()
