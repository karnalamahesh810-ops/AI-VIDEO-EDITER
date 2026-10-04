"""The second graphics pass: more charts, numbers and comparisons, and the case-file looks."""
import io
import tempfile
import unittest
from unittest import mock

from PIL import Image

import handler
from src import config, media, templates, treatments
from src.media import MediaAsset
from src.transcribe import Segment


def seg(text, i=0, dur=6.0):
    return Segment(text=text, start=i * dur, end=(i + 1) * dur)


def cues(text, shot=None):
    return treatments.cues_for(seg(text), shot or {"subject": "Lake Mead"}, None)


def scene(i, kind="video", dur=6.0, fps=30, **extra):
    return {"id": f"s{i}", "startFrame": int(i * dur * fps), "durationInFrames": int(dur * fps),
            "media": {"type": kind, "url": "x", **extra.pop("media", {})}, "transition": "none", "motion": "none",
            "effect": "none", **extra}


class DataCues(unittest.TestCase):
    def test_three_years_make_a_series_not_a_then_now(self):
        c = cues("In 2000 the lake was 95 percent full, in 2010 it held 60 percent, and today it is at 26 percent.")
        self.assertEqual(c[0]["cue"], "series")
        self.assertEqual([(i["label"], i["value"]) for i in c[0]["props"]["items"]],
                         [("2000", 95.0), ("2010", 60.0), ("TODAY", 26.0)])
        self.assertEqual(c[0]["props"]["suffix"], "%")
        self.assertNotIn("then-now", [x["cue"] for x in c])

    def test_shares_of_a_whole(self):
        c = cues("About 70 percent goes to agriculture, 20 percent to cities and 10 percent to industry.")
        self.assertEqual(c[0]["cue"], "shares")
        self.assertEqual([i["label"] for i in c[0]["props"]["items"]], ["AGRICULTURE", "CITIES", "INDUSTRY"])
        self.assertNotIn("percent", [x["cue"] for x in c])

    def test_one_in_four(self):
        c = cues("One in four residents now relies on trucked water.")
        self.assertEqual(c[0]["cue"], "ratio")
        self.assertEqual((c[0]["props"]["value"], c[0]["props"]["total"], c[0]["props"]["text"]), (1, 4, "RESIDENTS"))
        self.assertEqual(cues("It happened in 2020.")[:1], [])

    def test_a_fall_in_feet_is_a_length_change_and_a_height_is_a_measurement(self):
        c = cues("The water level dropped 170 feet since 2000.")
        self.assertEqual(c[0]["cue"], "change-length")
        self.assertEqual((c[0]["props"]["value"], c[0]["props"]["suffix"], c[0]["props"]["label"]), (170.0, "FT", "down"))
        c = cues("Hoover Dam stands 726 feet tall.", {"subject": "Hoover Dam"})
        self.assertEqual(c[0]["cue"], "measurement")
        self.assertEqual((c[0]["props"]["text"], c[0]["props"]["subtitle"]), ("HOOVER DAM", "TALL"))

    def test_named_values_are_compared_on_one_scale(self):
        c = cues("California gets 4.4 million acre-feet, Arizona 2.8 million and Nevada just 300,000.")
        self.assertEqual(c[0]["cue"], "compare-values")
        items = c[0]["props"]["items"]
        self.assertEqual([(i["label"], i["value"], i["suffix"]) for i in items],
                         [("CALIFORNIA", 4.4, "M"), ("ARIZONA", 2.8, "M"), ("NEVADA", 0.3, "M")])

    def test_a_report_becomes_a_document_ahead_of_a_loose_quote(self):
        c = cues("According to a new federal report, the reservoir could reach dead pool by 2027.")
        self.assertEqual(c[0]["cue"], "document")
        self.assertEqual(c[0]["props"]["text"], "the reservoir could reach dead pool by 2027")
        self.assertEqual(c[0]["props"]["label"], "REPORT")

    def test_a_recording_before_the_quote(self):
        c = cues("In a 911 call, the caller said the water was rising fast.")
        self.assertEqual([x["cue"] for x in c][:2], ["recording", "quote"])

    def test_every_new_cue_has_templates(self):
        for cue in ("series", "shares", "ratio", "measurement", "change-length", "compare-values", "document",
                    "recording", "subject-photo", "intro", "archive"):
            self.assertTrue(templates.for_cue(cue), cue)


class CaseFilePlanner(unittest.TestCase):
    def _plan(self, texts, scenes, shots=None):
        segments = [seg(t, i) for i, t in enumerate(texts)]
        shots = shots or [{"subject": "Lake Mead"} for _ in texts]
        brief = {"kind": "explainer", "sections": [], "hookBeats": []}
        return treatments.plan(segments, shots, scenes, 30, len(texts) * 180, brief,
                               treatments.pack_for(brief))

    def test_footage_named_as_footage_plays_in_a_player_window_rationed(self):
        texts = ["Plain words about water here.", "Footage shows the marina sitting on dry ground.",
                 "Footage shows the same marina a second time."]
        scenes = [scene(i) for i in range(3)]
        self._plan(texts, scenes)
        self.assertEqual([s.get("frame") for s in scenes], [None, "window", None])

    def test_archive_film_gets_its_tag_once_per_run(self):
        texts = ["The dam rose in the desert.", "Crews poured concrete day and night.", "Then the lake filled."]
        scenes = [scene(i, treatment="archival", media={"attribution": "YouTube: HOOVER DAM CONSTRUCTION 1934 NEWSREEL"})
                  for i in range(3)]
        out = self._plan(texts, scenes)
        tags = [o for o in out["overlays"] if o.get("template") == "TAG_SOURCE_V1"]
        self.assertEqual(len(tags), 1)
        self.assertEqual((tags[0]["text"], tags[0].get("subtitle")), ("Archive footage", "1934"))

    def test_modern_footage_graded_old_gets_no_archive_tag(self):
        scenes = [scene(0, treatment="archival", media={"attribution": "YouTube: Lake Mead drone 4K"})]
        out = self._plan(["The dam rose in the desert."], scenes)
        self.assertFalse([o for o in out["overlays"] if o.get("template") == "TAG_SOURCE_V1"])

    def test_a_weak_clip_of_a_named_place_gets_a_photo_window(self):
        scenes = [scene(0, semanticMetadata={"relevanceScore": 0.3})]
        out = self._plan(["Plain words about the old intake tower."], scenes,
                         [{"subject": "Intake Tower No. 3", "subjectType": "structure"}])
        self.assertEqual([o.get("template") for o in out["overlays"]], ["PHOTO_PIP_V1"])
        # People are never given a searched photo.
        scenes = [scene(0, semanticMetadata={"relevanceScore": 0.3})]
        out = self._plan(["Plain words about the manager."], scenes, [{"subject": "John Smith", "subjectType": "person"}])
        self.assertFalse([o for o in out["overlays"] if o.get("template") == "PHOTO_PIP_V1"])

    def test_the_intro_collage_once(self):
        texts = ["This is the story of a lake that vanished.", "In this video we look at why."] + ["More words."] * 6
        out = self._plan(texts, [scene(i) for i in range(len(texts))])
        self.assertEqual([o.get("template") for o in out["overlays"]].count("PHOTO_COLLAGE_V1"), 1)


class Rotation(unittest.TestCase):
    def test_full_screen_numbers_rotate_across_a_video(self):
        pack = treatments.pack_for({"kind": "explainer"})
        counts = {}
        picks = [treatments.animation_for(seg(f"The lake is at {v} percent capacity."), {"subject": "Lake Mead"}, pack, None,
                                          counts=counts)["template"] for v in (26, 31, 40, 55)]
        self.assertEqual(len(set(picks)), 4, picks)

    def test_place_maps_rotate_starting_with_the_pack_map(self):
        pack = treatments.pack_for({"kind": "explainer"})
        counts = {}
        picks = []
        for _ in range(3):
            tid = treatments._template_for_cue("place", pack, set(), counts)
            counts[tid] = counts.get(tid, 0) + 1
            picks.append(tid)
        self.assertEqual(picks[0], pack["map"])
        self.assertEqual(len(set(picks)), 3)


def jpeg(w=800, h=600):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (90, 120, 150)).save(buf, "JPEG")
    return buf.getvalue()


class OverlayPhotos(unittest.TestCase):
    def test_photo_window_and_map_pin_get_a_photo_and_an_empty_window_is_dropped(self):
        doc = {"overlays": [
            {"template": "PHOTO_PIP_V1", "type": "photo-card", "variant": "pip", "text": "Intake Tower No. 3"},
            {"template": "MAP_PHOTO_PIN_V1", "type": "map", "variant": "satellite-photo",
             "locations": [{"label": "Hoover Dam, Nevada", "lat": 36.0, "lon": -114.7}]},
            {"template": "PHOTO_PIP_V1", "type": "photo-card", "variant": "pip", "text": "Nothing Findable"},
            {"type": "stat", "value": 26},
        ]}
        queries = []

        def search(q, limit=6, full_screen=True):
            self.assertFalse(full_screen)           # a photo window: the plain search
            queries.append(q)
            return [] if "Nothing" in q else [MediaAsset(kind="image", source="web", url=f"https://img/{len(queries)}.jpg")]
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", side_effect=search), \
                mock.patch("requests.get", return_value=mock.Mock(status_code=200, content=jpeg())):
            n = handler._bind_overlay_photos(doc, tempfile.mkdtemp(), lambda local, name: f"https://store/{name}")
        self.assertEqual(n, 2)
        self.assertEqual(sorted(queries), ["Hoover Dam", "Intake Tower No. 3", "Nothing Findable"])
        kinds = [(o.get("template") or o["type"], bool(o.get("media"))) for o in doc["overlays"]]
        self.assertEqual(kinds, [("PHOTO_PIP_V1", True), ("MAP_PHOTO_PIN_V1", True), ("stat", False)])

    def test_a_map_without_a_photo_stays(self):
        doc = {"overlays": [{"template": "MAP_PHOTO_PIN_V1", "type": "map", "variant": "satellite-photo",
                             "locations": [{"label": "Nowhere", "lat": 1, "lon": 1}]}]}
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", return_value=[]):
            self.assertEqual(handler._bind_overlay_photos(doc, tempfile.mkdtemp(), lambda l, n: "u"), 0)
        self.assertEqual(len(doc["overlays"]), 1)



class OverlayPolicy(unittest.TestCase):
    """The owner (2026-09-28): the clip keeps its slot; one figure is a compact overlay on it,
    several values are full screen for their moment only, nothing stays up 7 seconds."""

    def _plan(self, texts):
        segments = [seg(t, i) for i, t in enumerate(texts)]
        shots = [{"subject": "Lake Mead"} for _ in texts]
        scenes = [scene(i) for i in range(len(texts))]
        brief = {"kind": "explainer", "sections": [], "hookBeats": []}
        return treatments.plan(segments, shots, scenes, 30, len(texts) * 180, brief, treatments.pack_for(brief))["overlays"]

    def test_a_single_figure_rides_on_the_clip(self):
        figures = ["Lake Mead is now at 26 percent capacity.", "The lake held 31 percent of its water in 2019.",
                   "Only 44 percent of the valley is irrigated now.", "Cuts reach 18 percent of the allocation."]
        texts = []
        for f in figures:
            texts += [f, "Plain words about water here.", "More plain words about the valley."]
        ovs = [o for o in self._plan(texts) if o.get("value") is not None]
        self.assertTrue(ovs)
        for o in ovs:
            t = templates.get(o["template"])
            self.assertNotIn("own-backdrop", t.get("tags") or [], o["template"])
            self.assertNotEqual(o.get("backdrop"), "blur")
            if t["kind"] != "tag":
                self.assertTrue(o.get("compact"), o["template"])
                self.assertIn(o.get("position"), ("bottom-left", "bottom-right"))
                self.assertAlmostEqual(o.get("scale"), treatments.COMPACT_SCALE)
            self.assertLessEqual(o["durationInFrames"] / 30, 4.0 + 1e-6)
        # The bold count leads (the owner, 2026-09-30: numbers as bold text with a
        # digit count sound); after two of them in a row another look comes in.
        looks = [o["template"] for o in sorted(ovs, key=lambda o: o["startFrame"])]
        self.assertEqual(looks[0], treatments.BOLD_COUNT_LOOK)
        self.assertFalse(any(looks[i:i + 3] == [treatments.BOLD_COUNT_LOOK] * 3 for i in range(len(looks))), looks)
        self.assertGreaterEqual(len(set(looks)), 2, looks)

    def test_several_values_are_full_screen_for_their_moment_only(self):
        ovs = self._plan(["In 2000 the lake was 95 percent full, in 2010 it held 60 percent, and today it is at 26 percent."])
        self.assertEqual(len(ovs), 1)
        o = ovs[0]
        t = templates.get(o["template"])
        self.assertNotEqual(t["kind"], "tag")
        if "own-backdrop" not in (t.get("tags") or []):
            self.assertEqual(o.get("backdrop"), "blur")
        self.assertLessEqual(o["durationInFrames"] / 30, 5.0 + 1e-6)

    def test_text_rides_on_the_clip(self):
        ovs = self._plan(["So what happens when the lake runs dry?"])
        for o in ovs:
            self.assertNotIn("own-backdrop", templates.get(o["template"]).get("tags") or [])
            self.assertLessEqual(o["durationInFrames"] / 30, 4.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
