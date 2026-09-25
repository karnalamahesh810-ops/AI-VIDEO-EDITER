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
        self.assertLessEqual(stills, int(0.55 * 10))      # history: photo-led
        news = [_shot(f"Person Number{i}") for i in range(10)]
        director._balance_visuals(news, dict(STORY, kind="news"))
        self.assertLessEqual(sum(1 for s in news if s["visualType"] == "image"),
                             int(director.MAX_STILL_SHARE * 10))

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


class FootageTags(unittest.TestCase):
    def test_stat_tag_needs_a_number_and_short_unit(self):
        ok = director.validate_overlay({"type": "stat-tag", "value": 107, "text": "DEGREES",
                                        "variant": "top-right"})
        self.assertEqual((ok["value"], ok["variant"]), (107, "top-right"))
        self.assertIsNone(director.validate_overlay({"type": "stat-tag", "text": "DEGREES"}))
        odd = director.validate_overlay({"type": "stat-tag", "value": 5, "text": "X", "variant": "middle"})
        self.assertEqual(odd["variant"], "bottom-left")

    def test_ring_stat_is_a_percentage(self):
        self.assertIsNotNone(director.validate_overlay({"type": "ring-stat", "value": 75, "text": "BURIED"}))
        self.assertIsNone(director.validate_overlay({"type": "ring-stat", "value": 180, "text": "x"}))

    def test_label_boxes_take_one_or_two_short_labels(self):
        ok = director.validate_overlay({"type": "label-boxes", "variant": "linked", "items": [
            {"label": "CONSTANT WATER LEVEL"}, {"label": "SUBMERGED PUMP INTAKE"}, {"label": "EXTRA"}]})
        self.assertEqual((len(ok["items"]), ok["variant"]), (2, "linked"))
        self.assertIsNone(director.validate_overlay({"type": "label-boxes", "items": [
            {"label": "a label that is far too long to fit inside a box"}]}))

    def test_bullets_need_two_points(self):
        self.assertIsNone(director.validate_overlay({"type": "bullets", "items": [{"text": "one"}]}))
        ok = director.validate_overlay({"type": "bullets", "items": [{"text": f"p{i}"} for i in range(6)]})
        self.assertEqual(len(ok["items"]), 4)


class Variety(unittest.TestCase):
    def test_a_look_repeated_within_a_minute_moves_to_a_sibling(self):
        from src.transcribe import Segment
        segs = [Segment(text="x", start=i * 10.0, end=i * 10.0 + 3) for i in range(4)]
        shots = [{"overlay": {"type": "sentence-highlight", "text": "a"}} for _ in range(4)]
        changed = director.diversify_overlays(segs, shots)
        kinds = [s["overlay"]["type"] for s in shots]
        self.assertEqual(changed, 3)
        self.assertEqual(kinds[:3], ["sentence-highlight", "red-strip", "underline-title"])

    def test_far_apart_repeats_are_left_alone(self):
        from src.transcribe import Segment
        segs = [Segment(text="x", start=i * 90.0, end=i * 90.0 + 3) for i in range(3)]
        shots = [{"overlay": {"type": "lower-third", "text": "A"}} for _ in range(3)]
        self.assertEqual(director.diversify_overlays(segs, shots), 0)

    def test_every_template_is_renderable(self):
        import re
        main = open("remotion/src/Main.tsx", encoding="utf-8").read()
        for kind in director.TEMPLATES:
            self.assertTrue(re.search(r'(^|\s)"?%s"?\s*:' % re.escape(kind), main, re.M), kind)


class EntityQueries(unittest.TestCase):
    def test_entity_adds_where_its_footage_lives(self):
        volcano = {"query": "Kilauea eruption", "visualType": "footage", "entity": "natural-feature"}
        director.shape_query(volcano)
        self.assertEqual(volcano["query"], "Kilauea eruption aerial drone footage")
        pres = {"query": "Barack Obama 2008", "visualType": "footage", "entity": "public-figure"}
        director.shape_query(pres)
        self.assertTrue(pres["query"].endswith("speech footage"))
        house = {"query": "Obama childhood home Honolulu", "visualType": "image", "entity": "building"}
        director.shape_query(house)
        self.assertTrue(house["query"].endswith("exterior photo"))

    def test_existing_media_words_are_left_alone(self):
        q = {"query": "Mount St Helens archival footage", "visualType": "footage",
             "entity": "natural-feature"}
        director.shape_query(q)
        self.assertEqual(q["query"], "Mount St Helens archival footage")
