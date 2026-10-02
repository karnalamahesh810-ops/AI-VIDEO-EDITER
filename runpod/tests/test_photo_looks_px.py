"""
The pro photo looks (family "px", remotion/src/components/lib/LibPhotosPro.tsx and
LibPhotosPro2.tsx; the owner, 2026-10-01: "add new extra animations ... great quality"):

  * the registry carries all 25 (LIB_PX_*), from their own list (scripts/library_looks_px.json):
    ids unique, each variant drawn by a component and picked in the library index, its props the
    editor's own, its picture slots counted;
  * all 25 were approved by the owner from their contact sheet (2026-10-02) and are switched on
    (autoPick false keeps a look out of the planner on every path until it is approved);
  * switched on, a still's line chooses among them by what it says (a waterline, then and now,
    something coming back, an old photograph), with only the line's own words on screen;
  * each plays its own sound on its visual hit, under the voice, never past the look.
"""
import importlib.util
import json
import os
import re
import unittest
from unittest import mock

from src import sfxplan, templates, timeline, treatments
from src.transcribe import Segment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "remotion", "src", "components", "lib")
FPS = 30
PUNCHES = {"impact", "impact-punch", "date-slam", "hit-deep", "boom-sub", "boom-soft", "flash-hit"}


def _build_registry():
    spec = importlib.util.spec_from_file_location("build_registry", os.path.join(ROOT, "scripts", "build_registry.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def px_templates():
    return [t for t in templates.all_templates() if t["id"].startswith("LIB_PX_")]


def ts_looks(name):
    """The variant names a component file's LOOKS map draws."""
    with open(os.path.join(LIB, name), encoding="utf-8") as fh:
        src = fh.read()
    block = src[src.index("export const LOOKS"):]
    return set(re.findall(r'"(px-[a-z-]+)":', block))


def index_picks():
    with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
        src = fh.read()
    return set(re.findall(r'"(px-[a-z-]+)"', src))


def small(texts, shots, kinds, pack="documentary"):
    segs = [Segment(text=t, start=i * 6.0, end=(i + 1) * 6.0) for i, t in enumerate(texts)]
    scenes = [{"id": f"s{i}", "startFrame": int(i * 180), "durationInFrames": 180,
               "media": {"type": k, "url": f"https://x/{i}.{'jpg' if k == 'image' else 'mp4'}"},
               "transition": "none", "motion": "none", "effect": "none"} for i, k in enumerate(kinds)]
    brief = {"kind": "explainer", "hookBeats": [], "sections": []}
    return treatments.plan(segs, shots, scenes, FPS, len(texts) * 180, brief, treatments.pack_for(brief, pack),
                           timeline._OVERLAY_SECONDS)


PLACE = {"subject": "Lake Powell", "subjectType": "place"}
WATERLINE = "Lake Powell used to reach all the way up there, at 3,700 feet."
ARCHIVAL = "Survey crews photographed this canyon in 1958."
PLAIN = "The marina crews worked through the night."


class Registry(unittest.TestCase):
    def test_twenty_five_looks_with_unique_ids(self):
        ids = [t["id"] for t in templates.all_templates()]
        self.assertEqual(len(ids), len(set(ids)))
        px = px_templates()
        self.assertEqual(len(px), 25)
        for t in px:
            self.assertEqual(t["category"], "IMAGES", t["id"])
            self.assertEqual(t["component"], "motion", t["id"])
            self.assertEqual(t["id"], "LIB_" + t["defaults"]["variant"].upper().replace("-", "_"))
            self.assertTrue(t["description"].strip() and t["name"].strip(), t["id"])
        self.assertEqual(templates.check(), [])

    def test_every_variant_is_drawn_and_picked_in_the_library_index(self):
        variants = {t["defaults"]["variant"] for t in px_templates()}
        drawn = ts_looks("LibPhotosPro.tsx") | ts_looks("LibPhotosPro2.tsx")
        self.assertEqual(variants, drawn)
        self.assertEqual(variants, index_picks())
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        self.assertIn('from "./LibPhotosPro"', index)
        self.assertIn('from "./LibPhotosPro2"', index)

    def test_props_are_the_editors_and_the_pictures_are_counted(self):
        known = set(_build_registry().P)
        for t in px_templates():
            props = set(t["props"])
            self.assertTrue(props <= known, t["id"])
            self.assertIn("text", props, t["id"])
            tags = set(t["tags"])
            self.assertIn("own-backdrop", tags, t["id"])
            self.assertEqual(treatments.layout_class(t), "cutaway", t["id"])
            if t["defaults"]["variant"] in ("px-dated-cascade", "px-then-now"):
                self.assertIn("stills", tags, t["id"])
                self.assertIn("items", props, t["id"])
                self.assertEqual(treatments.look_slots(t)[0], 2, t["id"])
            else:
                self.assertIn("still", tags, t["id"])
                self.assertEqual(treatments.look_slots(t), (1, 1), t["id"])
            self.assertIn(t["defaults"]["exit"], ("fade", "none"), t["id"])

    def test_the_family_list_is_the_registrys(self):
        br = _build_registry()
        self.assertTrue(any(p.endswith("library_looks_px.json") for p in br.library_files()))
        with open(os.path.join(ROOT, "scripts", "library_looks_px.json"), encoding="utf-8") as fh:
            listed = {"LIB_" + e["id"].upper().replace("-", "_") for e in json.load(fh)}
        self.assertEqual(listed, {t["id"] for t in px_templates()})


class SwitchedOn(unittest.TestCase):
    """The owner approved all 25 from their contact sheet (2026-10-02: "these 25 look good")."""

    def test_every_new_look_is_switched_on(self):
        for t in px_templates():
            self.assertIsNot(t.get("autoPick"), False, t["id"])
            self.assertTrue(treatments.auto_ok(t["id"]), t["id"])
        # Looks without the flag are as before.
        self.assertTrue(treatments.auto_ok("LIB_PE_SPLIT_PANELS"))
        self.assertTrue(treatments.auto_ok("PHOTO_CARD_V1"))
        self.assertFalse(treatments.auto_ok("TEXT_KEY_PHRASE_V1"))

    def test_a_look_still_waiting_for_approval_is_never_chosen(self):
        # The flag keeps working for the next family that waits for the owner.
        real = treatments.templates.get
        with mock.patch.object(treatments.templates, "get",
                               side_effect=lambda tid, *a, **k: ({**(real(tid) or {}), "autoPick": False}
                                                                 if str(tid) == "LIB_PX_APERTURE_IRIS" else real(tid, *a, **k))):
            self.assertFalse(treatments.auto_ok("LIB_PX_APERTURE_IRIS"))

    def test_the_automatic_paths_can_choose_them(self):
        found = set()
        for cue, still in (("photo", True), ("photo-place", True), ("photo-archival", False), ("photo-archival", True)):
            try:
                found.update(x for x in treatments._lib_looks(cue, still=still) if x.startswith("LIB_PX_"))
            except TypeError:
                found.update(x for x in treatments._lib_looks(cue) if x.startswith("LIB_PX_"))
        self.assertTrue(found)


class Hooks(unittest.TestCase):
    def test_the_line_says_what_the_picture_is_for(self):
        self.assertEqual(treatments.photo_line_cues(WATERLINE)[0], "photo-level")
        self.assertIn("photo-archival", treatments.photo_line_cues(ARCHIVAL))
        self.assertIn("photo-then-now", treatments.photo_line_cues("In 1964 the gates closed; today the ramp ends in sand."))
        self.assertIn("photo-then-now", treatments.photo_line_cues("The lake held 24 million acre-feet in 1999 and 5 million in 2022."))
        self.assertEqual(treatments.photo_line_cues("It started to come back in 2021."), ["photo-return"])
        self.assertEqual(treatments.photo_line_cues("Look closely at the canyon wall."), ["photo-detail"])
        self.assertEqual(treatments.photo_line_cues(PLAIN), [])
        self.assertEqual(treatments.photo_line_cues("Boat ramps now end in dry gravel."), [])

    def test_only_the_lines_own_words_reach_the_look(self):
        self.assertEqual(treatments.photo_line_props(ARCHIVAL), {"label": "1958"})
        self.assertEqual(treatments.photo_line_props(WATERLINE), {"subtitle": "3,700 FT"})
        self.assertEqual(treatments.photo_line_props("In 1964 the gates closed; today the ramp ends in sand."),
                         {"label": "1964", "items": [{"label": "1964"}, {"label": "TODAY"}]})
        self.assertEqual(treatments.photo_line_props("People photographed it in the 1950s.")["label"], "1950s")
        self.assertEqual(treatments.photo_line_props(PLAIN), {})

    def test_switched_on_the_line_chooses_the_look(self):
        real = treatments.auto_ok
        on = lambda tid: real(tid) or str(tid).startswith("LIB_PX_")  # noqa: E731
        # (A line with a figure or a year in it shows that first - a must-show graphic, as before.)
        # (About one still in two gets a photo look - the still between the two rests - and two graphics in a
        # row never share a family: a figure comes between the two photo looks.)
        texts = ["Lake Powell used to reach all the way up there.", PLAIN, PLAIN, "Lake Mead is at 26 percent of capacity.",
                 "Survey crews photographed this canyon before the dam.", PLAIN]
        with mock.patch.object(treatments, "auto_ok", side_effect=on):
            out = small(texts, [dict(PLACE) for _ in texts], ["image", "video", "image", "video", "image", "video"])
        ovs = sorted(out["overlays"], key=lambda o: o["startFrame"])
        first = next(o for o in ovs if o["startFrame"] < 180)
        self.assertEqual(first["template"], "LIB_PX_LEVEL_LINE")
        self.assertEqual(first.get("text"), "Lake Powell")
        self.assertNotIn("subtitle", first)                           # no height said, none shown
        third = next(o for o in ovs if 720 <= o["startFrame"] < 900)
        self.assertTrue(third["template"].startswith("LIB_PX_"), third["template"])
        self.assertIn("photo-archival", templates.cues_of(templates.get(third["template"])))
        self.assertNotIn("label", third)                              # no year said, none shown

    def test_switched_on_a_person_keeps_the_person_looks(self):
        real = treatments.auto_ok
        on = lambda tid: real(tid) or str(tid).startswith("LIB_PX_")  # noqa: E731
        with mock.patch.object(treatments, "auto_ok", side_effect=on):
            out = small(["Photographed in 1958, Floyd Dominy stands on the dam.", PLAIN],
                        [{"subject": "Floyd Dominy", "subjectType": "person"}, dict(PLACE)], ["image", "video"])
        self.assertFalse([o["template"] for o in out["overlays"]
                          if o["template"].startswith("LIB_PX_") and o["startFrame"] < 180])


class Sounds(unittest.TestCase):
    def test_each_sounds_on_its_own_hit(self):
        for t in px_templates():
            d = t["defaults"]
            cues = d["sounds"]
            self.assertTrue(cues, t["id"])
            self.assertFalse(d.get("ownSound"), t["id"])
            self.assertNotIn("soundTiming", d, t["id"])         # the registry design plays (LookSounds)
            for c in cues:
                self.assertIsNotNone(sfxplan.resolve_sound(c["name"], c.get("alt")), (t["id"], c))
                self.assertNotIn(c["name"], PUNCHES, t["id"])
                self.assertFalse(set(c.get("alt") or []) & PUNCHES, t["id"])
                self.assertLessEqual(c.get("gain_db", 0), 0, t["id"])
            # One cue lands on the look's visual hit (the frame the planner times to the word).
            hits = [c for c in cues if c.get("align", "peak") == "peak"]
            self.assertTrue(any(c["at"] == d["sfxAt"] for c in hits) or any(c["at"] <= d["sfxAt"] for c in cues), t["id"])
            self.assertEqual(d["sfx"]["name"], cues[0]["name"], t["id"])

    def test_scheduled_under_the_voice_and_inside_the_look(self):
        for t in px_templates():
            d = t["defaults"]
            for frames in (int(round(d["duration"] * FPS)), 75):          # its default, and the planner's shortest
                got = sfxplan.look_sounds(d["sounds"], fps=FPS, frames=frames, default_frames=int(round(d["duration"] * FPS)))
                self.assertTrue(got, (t["id"], frames))
                for s in got:
                    self.assertGreaterEqual(s["from"], 0, t["id"])
                    self.assertLessEqual(s["from"] + s["frames"], frames, t["id"])
                    cap = min(1.0, 10 ** (-sfxplan.ceiling_db(s["name"]) / 20.0))
                    self.assertLessEqual(s["volume"], cap + 1e-6, (t["id"], s))
                    self.assertGreater(s["volume"], 0.0, t["id"])

    def test_the_hit_lands_where_the_look_says(self):
        # The sound's loudest moment on the hit frame: a one-shot starts its peak's length before it.
        t = templates.get("LIB_PX_APERTURE_IRIS")
        got = sfxplan.look_sounds(t["defaults"]["sounds"], fps=FPS, frames=135, default_frames=135)
        peak = sfxplan._meta()["camera-shutter"]["peak"]
        self.assertEqual(got[0]["from"] + round(peak * FPS) - got[0]["trim"], 6)
        t = templates.get("LIB_PX_CONTACT_SHEET")
        got = sfxplan.look_sounds(t["defaults"]["sounds"], fps=FPS, frames=150, default_frames=150)
        self.assertEqual([s["name"] for s in got], ["marker-draw", "whoosh-soft-v2"])
        self.assertEqual(got[0]["from"], 6)                               # the pencil starts with the stroke


if __name__ == "__main__":
    unittest.main()
