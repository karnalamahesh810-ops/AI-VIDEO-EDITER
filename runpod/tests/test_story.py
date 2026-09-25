import os
import subprocess
import tempfile
import unittest

from src import director, media


def _shot(subject, stype="person", vtype="image", query="q"):
    return {"query": query, "fallbacks": [], "visualType": vtype,
            "subject": subject, "subjectType": stype}


STORY = {"kind": "history", "year": 1971, "places": ["Honolulu"],
         "sections": [{"from": 0, "to": 9, "summary": "",
                       "footage": ["Honolulu 1960s archival footage",
                                   "Honolulu airport 1970s film"]}]}


class BalanceVisuals(unittest.TestCase):
    def test_unnamed_person_still_becomes_section_footage(self):
        shots = [_shot("father and son")]
        self.assertEqual(director._balance_visuals(shots, STORY), 1)
        self.assertEqual(shots[0]["visualType"], "footage")
        self.assertEqual(shots[0]["query"], "Honolulu 1960s archival footage")
        # Not a person beat any more: no portrait exemption at the vision gate.
        self.assertEqual(shots[0]["subjectType"], "place")

    def test_named_person_keeps_the_introduction_only(self):
        shots = [_shot("Barack Obama Sr."), _shot("Barack Obama Sr."),
                 _shot("Honolulu", "place", "footage")] + \
                [_shot("x", "place", "footage") for _ in range(5)]
        director._balance_visuals(shots, STORY)
        self.assertEqual(shots[0]["visualType"], "image")
        self.assertEqual(shots[1]["visualType"], "footage")

    def test_documents_are_never_demoted(self):
        shots = [_shot("divorce filing", "document") for _ in range(4)]
        director._balance_visuals(shots, STORY)
        self.assertTrue(all(s["visualType"] == "image" for s in shots))

    def test_still_share_is_capped(self):
        shots = [_shot(f"Person Number{i}") for i in range(10)]
        director._balance_visuals(shots, STORY)
        stills = sum(1 for s in shots if s["visualType"] == "image")
        self.assertLessEqual(stills, int(director.MAX_STILL_SHARE * 10))

    def test_no_story_changes_nothing(self):
        shots = [_shot("a man")]
        self.assertEqual(director._balance_visuals(shots, {}), 0)

    def test_looks_named(self):
        self.assertTrue(director._looks_named("Barack Obama Sr."))
        self.assertTrue(director._looks_named("Ann Dunham"))
        self.assertFalse(director._looks_named("father and son"))
        self.assertFalse(director._looks_named("a man in a dark suit"))


class StillQuality(unittest.TestCase):
    """A web photo used to be judged "unreadable" and dropped after vision passed it."""

    def test_a_still_image_is_readable(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "photo.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=640x360", "-frames:v", "1", path], check=True)
            self.assertEqual(len(media._gray_frames(path)), 1)
            self.assertEqual(media.clip_quality(path), (True, ""))

    def test_a_black_still_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "black.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=black:size=640x360", "-frames:v", "1", path], check=True)
            self.assertEqual(media.clip_quality(path), (False, "near-black"))




class BriefCast(unittest.TestCase):
    def test_cast_names_join_people_and_sections_are_clamped(self):
        fallback = {"kind": "other", "summary": "", "event": "", "year": None,
                    "recent": False, "places": [], "people": [], "hookBeats": [0],
                    "cast": [], "sections": []}
        raw = {"kind": "biography",
               "cast": [{"name": "Barack Obama Sr.", "aliases": ["his father", "the man"]},
                        {"name": "", "aliases": ["a stranger"]}, "junk"],
               "sections": [{"from": 0, "to": 99, "footage": ["Honolulu 1960s archival footage"]},
                            {"from": "x", "to": 3, "footage": ["bad"]},
                            {"from": 2, "to": 3, "footage": []}]}
        out = director._validate_brief(raw, fallback, 10)
        self.assertIn("Barack Obama Sr.", out["people"])
        self.assertEqual(out["cast"][0]["aliases"], ["his father", "the man"])
        self.assertEqual(out["sections"], [{"from": 0, "to": 9,
                                            "footage": ["Honolulu 1960s archival footage"]}])
