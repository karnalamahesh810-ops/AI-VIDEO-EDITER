"""
Lines planned without the model get a real plan before a re-clip searches them (src/replan.py).

2026-10-07, the California video: built while OpenRouter was out of credit, 113 of its 167 lines carried the
video's TITLE as their subject (typed a person) and searched "Phillips Station <the title> 2022"; the editor's
"find choices" found nothing in 6.4 minutes and a re-clip would have searched the same words. A re-clip now
plans those lines again with the build's own planner (director.plan), or from their own words when the model
cannot, and saves the new search fields with the timeline.

Offline: the planner is a stub; the re-clip runs on the re-cut bench (tests/test_reclip.Rig).
"""
import copy
import unittest
from unittest import mock

import handler
from src import director, recut, replan
from tests.test_recut import JOB, PID, clip_scene, doc_of, lay_out, photo_scene
from tests.test_reclip import Rig

TITLE = "California's Water Clock Is Running Faster — These Cities Could Feel It First"
FPS = 30


def broken_doc() -> dict:
    doc = doc_of(lay_out([
        (clip_scene, 4.0, {"text": "On April 1, 2015, a man walked into a meadow near Echo Summit."}),
        (photo_scene, 4.0, {"text": "He carried a long aluminum tube, the kind the state uses to measure snow."}),
        (clip_scene, 4.0, {"text": "That meadow is called Phillips Station, and it isn't just a meadow."}),
        (photo_scene, 4.0, {"text": "The grass was brown and dry where the snow should have been."}),
    ], FPS), FPS)
    doc["meta"]["planner"] = "rules"
    doc["meta"]["story"] = {"kind": "news", "event": TITLE, "places": ["Phillips Station", "Echo Summit"]}
    s = doc["scenes"]
    s[0]["query"] = s[0]["semanticMetadata"]["searchQuery"] = f"Echo Summit {TITLE}"
    s[0]["semanticMetadata"].update(subject="Echo Summit", subjectType="place")
    for k in (1, 3):
        s[k]["query"] = s[k]["semanticMetadata"]["searchQuery"] = f"Phillips Station {TITLE} 2022"
        s[k]["semanticMetadata"].update(subject=TITLE, subjectType="person")
    s[2]["query"] = s[2]["semanticMetadata"]["searchQuery"] = "Phillips Station news 2022"
    s[2]["semanticMetadata"].update(subject="Phillips Station", subjectType="place")
    return doc


def model_shot(i: int) -> dict:
    return {"query": f"California snow survey tube {i}", "subject": "California snow survey", "subjectType": "event",
            "intent": f"a surveyor pushing a snow tube, line {i}", "sceneIntent": {"entities": ["snow survey"]},
            "eventWindow": ""}


class FindingThem(unittest.TestCase):
    def test_the_title_as_a_subject_or_inside_the_search_is_found_and_a_real_subject_is_not(self):
        doc = broken_doc()
        self.assertIn(TITLE.lower(), replan.titles_of(doc))
        self.assertEqual(replan.broken(doc), {0: "its search carries the video's whole title",
                                              1: "its subject is the video's title",
                                              3: "its subject is the video's title"})

    def test_a_long_subject_on_many_lines_is_a_title_even_without_the_rule_brief(self):
        doc = broken_doc()
        doc["meta"].pop("planner")
        for s in doc["scenes"]:
            s["semanticMetadata"]["subject"] = "Why the river towns of the valley ran dry"
        titles = replan.titles_of(doc)
        self.assertEqual(titles, ["why the river towns of the valley ran dry"])
        self.assertEqual(sorted(replan.broken(doc, titles)), [0, 1, 2, 3])

    def test_a_short_story_name_is_never_taken_for_a_title(self):
        doc = broken_doc()
        doc["meta"]["story"]["event"] = "Lake Mead"
        for s in doc["scenes"]:
            s["semanticMetadata"]["subject"] = "Lake Mead"
            s["query"] = s["semanticMetadata"]["searchQuery"] = "Lake Mead boats"
        self.assertEqual(replan.titles_of(doc), [])
        self.assertEqual(replan.broken(doc), {})

    def test_a_line_the_build_planned_by_rules_is_found_by_its_mark(self):
        doc = broken_doc()
        doc["scenes"][2]["semanticMetadata"]["plannedBy"] = "rules"
        self.assertEqual(replan.broken(doc)[2], "planned without the model")
        with open(replan.__file__.replace("replan.py", "timeline.py"), encoding="utf-8") as fh:
            self.assertIn('**({"plannedBy": "rules"} if shot.get("rule") else {})', fh.read())


class Repairing(unittest.TestCase):
    def test_the_builds_planner_replans_them_and_only_their_search_fields_change(self):
        doc = broken_doc()
        before = copy.deepcopy(doc)
        shots = [model_shot(i) for i in range(4)]
        shots[3] = {"query": f"{TITLE} brown grass", "subject": TITLE, "subjectType": "person", "rule": True}
        with mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "plan", return_value=(shots, "mixed", [])) as plan:
            out = replan.repair(doc, title=TITLE)
        self.assertEqual(plan.call_count, 1)
        self.assertEqual(plan.call_args.kwargs.get("allow_maps"), False)
        self.assertEqual([seg.text for seg in plan.call_args.args[0]], [s["text"] for s in before["scenes"]])
        self.assertEqual({k: out[k] for k in ("found", "replanned", "byModel", "byRules")},
                         {"found": 3, "replanned": 3, "byModel": 2, "byRules": 1})
        s = doc["scenes"]
        for k in (0, 1):
            sem = s[k]["semanticMetadata"]
            self.assertEqual((s[k]["query"], sem["searchQuery"], sem["subject"], sem["subjectType"]),
                             (f"California snow survey tube {k}",) * 2 + ("California snow survey", "event"))
            self.assertEqual(sem["sceneIntent"], {"entities": ["snow survey"]})
            self.assertEqual(sem["replanned"]["by"], "model")
        # The model left line 3 to the rules: rebuilt from its own words and the place the lines before it
        # were about - never the title.
        sem3 = s[3]["semanticMetadata"]
        self.assertEqual((sem3["subject"], sem3["subjectType"], sem3["replanned"]["by"]), ("Phillips Station", "place",
                                                                                         "rules"))
        self.assertEqual(sem3["replanned"]["was"], TITLE)
        for sc in s:
            self.assertNotIn(TITLE.lower(), sc["query"].lower())
            self.assertNotEqual(sc["semanticMetadata"]["subject"], TITLE)
        self.assertEqual(s[2], before["scenes"][2])                         # a real subject is left alone
        for new, old in zip(s, before["scenes"]):
            for key in ("media", "text", "startFrame", "durationInFrames", "words", "motion"):
                self.assertEqual(new[key], old[key])
        self.assertEqual(replan.real_subjects(doc), 4)
        self.assertEqual(replan.real_subjects(before), 2)

    def test_without_the_model_every_line_is_rebuilt_from_its_own_words(self):
        doc = broken_doc()
        with mock.patch.object(director, "is_configured", return_value=False), \
                mock.patch.object(director, "plan", side_effect=AssertionError("no model")):
            out = replan.repair(doc, title=TITLE)
        self.assertEqual((out["replanned"], out["byRules"]), (3, 3))
        s = doc["scenes"]
        self.assertEqual(s[0]["semanticMetadata"]["subject"], "Echo Summit")     # the place the line names
        self.assertEqual(s[1]["semanticMetadata"]["subject"], "Echo Summit")     # the place the line before named
        for sc in s:
            self.assertNotIn(TITLE.lower(), sc["query"].lower())
        self.assertIn("Echo Summit", s[0]["query"])                          # the place, and the line's words

    def test_a_planner_that_breaks_leaves_the_rule_rebuild(self):
        doc = broken_doc()
        with mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "plan", side_effect=RuntimeError("402 Payment Required")):
            out = replan.repair(doc, title=TITLE)
        self.assertEqual((out["replanned"], out["byModel"], out["byRules"]), (3, 0, 3))

    def test_nothing_to_repair_costs_nothing(self):
        doc = broken_doc()
        doc["meta"]["story"]["event"] = "Snow"
        doc["meta"]["planner"] = "ai"
        for k in (0, 1, 3):
            doc["scenes"][k]["semanticMetadata"]["subject"] = "Phillips Station"
            doc["scenes"][k]["query"] = doc["scenes"][k]["semanticMetadata"]["searchQuery"] = "Phillips Station snow"
        with mock.patch.object(director, "plan", side_effect=AssertionError("planned for nothing")):
            self.assertEqual(replan.repair(doc)["found"], 0)


class InTheReclip(Rig):
    def doc(self):
        doc = broken_doc()
        for s in doc["scenes"]:
            s["semanticMetadata"]["sourceUrl"] = ""
        return doc

    def test_a_dry_run_plans_them_again_and_says_how_many_lines_have_a_subject_now(self):
        doc = self.doc()
        with mock.patch.object(director, "is_configured", return_value=False):
            out = handler.handler(self.job(timeline=doc))
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["replanned"]["found"], out["replanned"]["replanned"]), (3, 3))
        self.assertEqual(out["realSubjects"], 4)
        self.assertEqual(len(out["replannedLines"]), 3)

    def test_an_apply_saves_the_new_search_fields_of_every_line_replanned(self):
        doc = self.doc()
        with mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "plan", return_value=([model_shot(i) for i in range(4)], "ai", [])):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["written"], out)
        new = self.written[0][1]["scene_data"]
        for k in (0, 1, 3):
            sem = new["scenes"][k]["semanticMetadata"]
            self.assertEqual(sem["subject"], "California snow survey")
            self.assertEqual(sem["replanned"]["by"], "model")
            self.assertEqual(new["scenes"][k]["query"], f"California snow survey tube {k}")
        self.assertEqual(new["scenes"][2]["semanticMetadata"]["subject"], "Phillips Station")
        self.assertEqual(out["fingerprint"], recut.fingerprint(doc))       # the guard still reads the saved one


if __name__ == "__main__":
    unittest.main()
