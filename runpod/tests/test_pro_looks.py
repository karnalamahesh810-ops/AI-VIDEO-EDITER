"""
The 25 pro looks (the owner, 2026-10-01: "add 50 new extra animations ... make better ones and great
quality"): LIB_DX_ data, LIB_MX_ maps and LIB_KX_ documents and kinetic text, drawn by remotion's
LibDataPro / LibMapsPro / LibDocsPro.

  * the registry: 25 unique ids, every variant drawn by a component (index.ts and the file's LOOKS), props
    the editor knows, a hit frame that lands before the exit, the sounds scheduled on the look's own frames;
  * autoPick: registered "autoPick": false, no path of the planner chooses one on its own (the editor still
    offers them); switched on, the right lines get them with the words pro_props gives them;
  * formatting (proFormat.ts through node + esbuild): numbers in digits and grouped, a year never grouped,
    units, changes, ratios, distances, coordinates, place names, stacked words;
  * sounds: every file ships, a number only ticks, nothing rings past the look, never over the voice.
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import sfxplan, templates, timeline, treatments
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
LIB = os.path.join(REMOTION, "src", "components", "lib")
FORMAT_TS = os.path.join(LIB, "proFormat.ts")
FILES = {"dx": "LibDataPro.tsx", "mx": "LibMapsPro.tsx", "kx": "LibDocsPro.tsx"}
PRO = treatments.PRO_PREFIXES
FPS = 30
SECS = 5.0
PLAIN = "Plain words about the water here."
DAM = {"label": "Glen Canyon Dam, Arizona", "lat": 36.9375, "lon": -111.4844, "kind": "dam"}
MEAD = {"label": "Hoover Dam, Nevada", "lat": 36.0161, "lon": -114.7377, "kind": "dam"}
HITE = {"label": "Hite, Utah", "lat": 37.878, "lon": -110.3917, "kind": "hamlet"}
PAGE = {"label": "Page, Arizona", "lat": 36.9147, "lon": -111.4558, "kind": "city"}


def pro_looks():
    return [t for t in templates.all_templates() if t["id"].startswith(PRO)]


def _seg(i, text):
    words = [Word(text=w, start=i * SECS + j * 0.3, end=i * SECS + j * 0.3 + 0.25) for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * SECS, end=(i + 1) * SECS, words=words)


def _plan(lines, shots=None, brief=None, pack="documentary"):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    n = int(SECS * FPS)
    scenes = [{"id": f"s{i}", "startFrame": i * n, "durationInFrames": n,
               "media": {"type": "video", "url": f"https://x/{i}.mp4", "thumbnail": f"https://x/{i}.jpg"},
               "transition": "none", "motion": "none", "effect": "none"} for i in range(len(lines))]
    brief = brief or {"kind": "explainer", "hookBeats": [], "sections": []}
    shots = shots or [{"subject": "Lake Powell"} for _ in lines]
    return treatments.plan(segs, shots, scenes, FPS, len(lines) * n, brief, treatments.pack_for(brief, pack),
                           timeline._OVERLAY_SECONDS)


def _used(out):
    return [o.get("template") for o in out["overlays"]]


@contextlib.contextmanager
def switched_on(only=None):
    """
    The pro looks switched on (as if their registry "autoPick" were true). With `only`, just that one, and
    every other look sharing a cue with it (every map, for a map) switched off - so the planner's choice for
    that cue can only be it.
    """
    real = templates.auto_pick
    rivals = set()
    if only:
        me = templates.get(only)
        mine = set(templates.cues_of(me))
        for t in templates.all_templates():
            if t["id"] != only and (set(templates.cues_of(t)) & mine
                                    or (me["category"] == "MAPS" and t["category"] == "MAPS")):
                rivals.add(t["id"])

    def fake(t):
        tt = templates.get(t) if isinstance(t, str) else t
        if not isinstance(tt, dict):
            return False
        tid = tt.get("id", "")
        if only:
            if tid == only:
                return True
            if tid in rivals or tid.startswith(PRO):
                return False
        elif tid.startswith(PRO):
            return True
        return real(tt)

    with mock.patch.object(templates, "auto_pick", fake):
        yield


# --------------------------------------------------------------------------- the registry
class Registry(unittest.TestCase):
    def test_twenty_five_unique_looks_in_three_families(self):
        looks = pro_looks()
        ids = [t["id"] for t in looks]
        self.assertEqual(len(ids), 25)
        self.assertEqual(len(set(ids)), 25)
        all_ids = [t["id"] for t in templates.all_templates()]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        fams = {templates.family(t) for t in looks}
        self.assertEqual(fams, {"dx", "mx", "kx"})
        self.assertEqual(sum(1 for t in looks if t["id"].startswith("LIB_DX_")), 8)
        self.assertEqual(sum(1 for t in looks if t["id"].startswith("LIB_MX_")), 7)
        self.assertEqual(sum(1 for t in looks if t["id"].startswith("LIB_KX_")), 10)

    def test_every_variant_is_drawn_by_a_component(self):
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        for fam, name in FILES.items():
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            drawn = set(re.findall(r'"(%s-[a-z-]+)":\s*guard\(' % fam, src))
            picked = set(re.findall(r'"(%s-[a-z-]+)"' % fam, index))
            want = {(t["defaults"] or {}).get("variant") for t in pro_looks() if templates.family(t) == fam}
            self.assertEqual(drawn, want, name)
            self.assertEqual(picked, want, "index.ts")
            self.assertIn(f'from "./{name[:-4]}"', index)

    def test_every_look_is_offered_to_the_editor_and_off_for_the_planner(self):
        reg = templates.load()
        for t in pro_looks():
            self.assertIs(t.get("autoPick"), False, t["id"])
            self.assertFalse(templates.auto_pick(t), t["id"])
            self.assertFalse(templates.auto_pick(t["id"]), t["id"])
            self.assertEqual(t["component"], "motion", t["id"])
            self.assertIn(t["category"], reg["categories"], t["id"])
            self.assertIn(t["kind"], ("card", "tag"), t["id"])
            self.assertGreater(len(t["description"]), 120, t["id"])
            self.assertTrue(t["cues"], t["id"])
        # Older looks keep their behaviour: no flag, picked as before.
        self.assertTrue(templates.auto_pick("LIB_CA_BAR_RACE"))
        self.assertFalse(templates.auto_pick("NO_SUCH_LOOK"))

    def test_props_are_the_editors_and_the_timing_fits_the_look(self):
        known = set(templates.get("LIB_CA_BAR_RACE")["props"]) | {"value", "total", "items", "locations", "highlight",
                                                                    "body", "label", "subtitle", "prefix", "suffix",
                                                                    "text"}
        for t in pro_looks():
            d = t["defaults"]
            self.assertTrue(set(t["props"]) <= known | set(t["props"]), t["id"])
            for p in ("position", "scale", "opacity", "duration", "speed", "theme", "sfx", "soundGain"):
                self.assertIn(p, t["props"], (t["id"], p))
            self.assertEqual(d["exit"], "none", t["id"])          # the look leaves in its own last frames
            self.assertEqual(d["entrance"], "fade", t["id"])      # MotionWrap adds no move of its own
            frames = int(round(d["duration"] * FPS))
            # The hit lands, is seen, and the look leaves after it (sfxAt + EXIT_FRAMES + SETTLE).
            self.assertLess(d["sfxAt"] + treatments.EXIT_FRAMES + treatments.SETTLE * FPS, frames, t["id"])
            self.assertLessEqual(treatments.animation_seconds(t), d["duration"], t["id"])
        # The map looks bring their own frame; the full-data charts sit on the clip's blurred still.
        for t in pro_looks():
            if t["category"] == "MAPS":
                self.assertIn("own-backdrop", t["tags"], t["id"])
                self.assertIn("locations", t["props"], t["id"])
        self.assertEqual(templates.check(), [])

    def test_the_layout_class_suits_each_look(self):
        L = treatments.layout_class
        self.assertEqual(L(templates.get("LIB_DX_LINE_ENDPOINT"), "series"), "full")
        self.assertEqual(L(templates.get("LIB_DX_GHOST_BARS"), "then-now"), "full")
        self.assertEqual(L(templates.get("LIB_MX_GLOBE_DIVE"), ""), "cutaway")
        # A single figure that draws its own full stage is a tag: never shrunk into a corner.
        for tid in ("LIB_DX_UNIT_SPLIT", "LIB_DX_FILLED_FIGURE", "LIB_DX_CAPACITY_GAUGE", "LIB_DX_DRUM_COUNTER",
                    "LIB_DX_RESERVOIR_SECTION"):
            t = templates.get(tid)
            self.assertEqual(t["kind"], "tag", tid)
            ov = {}
            treatments.apply_layout(ov, t, "figure")
            self.assertNotIn("compact", ov, tid)


# --------------------------------------------------------------------------- the planner, switched off
LINES = {
    "series": "Lake Powell stood at 3,700 feet in 1980, 3,555 feet in 2005 and 3,522 feet in 2022.",
    "then-now": "In 2000 the lake was 95 percent full; by 2026 it was 22 percent.",
    "percent": "Lake Powell is now at 22 percent of its capacity.",
    "level": "Lake Powell now sits at an elevation of 3,517 feet above sea level.",
    "fell-to": "The lake fell to 3,517 feet, down from 3,700 feet at full pool, near the minimum power pool of 3,490 feet.",
    "count": "More than 4,500 homes lost their water supply that summer.",
    "values": "California takes 4.4 million, Arizona 2.8 million and Nevada 0.3 million acre-feet.",
    "article": "The front page of the Arizona Republic said the lake had reached its lowest level since it first filled.",
    "memo": "Records show the dam's operators cut the releases to protect the turbines.",
    "report": "A new report found that the lake could keep falling for years.",
    "term": "Hydrologists call it the bathtub ring, the pale band of minerals left on the canyon walls.",
    "warning": "Officials issued an emergency warning for every marina on the lake.",
    "letter": "\"We are building a reservoir the river cannot fill,\" Floyd Dominy wrote in a letter.",
    "post": "\"The ramp at Bullfrog is closed until further notice,\" the National Park Service posted.",
    "place": "Glen Canyon Dam holds back the river.",
}
MAP_SHOTS = {
    "place": {"subject": "Glen Canyon Dam", "overlay": {"type": "map", "locations": [DAM]}},
    "pair": {"subject": "the river", "overlay": {"type": "map", "locations": [DAM, MEAD]}},
    "many": {"subject": "Lake Powell", "overlay": {"type": "map", "locations": [HITE, PAGE, DAM]}},
    "region": {"subject": "Arizona", "overlay": {"type": "map", "variant": "region", "locations": [PAGE]}},
}


class SwitchedOff(unittest.TestCase):
    def test_no_line_gets_a_pro_look_while_they_wait_for_approval(self):
        lines = list(LINES.values())
        shots = [{"subject": "Lake Powell"} for _ in lines]
        out = _plan(lines + [PLAIN, PLAIN], shots=shots + [{"subject": "x"}, {"subject": "x"}])
        self.assertTrue(out["overlays"])
        self.assertFalse([tid for tid in _used(out) if str(tid).startswith(PRO)], _used(out))
        for key, shot in MAP_SHOTS.items():
            out = _plan([LINES["place"], PLAIN], shots=[shot, {"subject": "x"}])
            self.assertFalse([tid for tid in _used(out) if str(tid).startswith(PRO)], (key, _used(out)))

    def test_no_selection_path_offers_one(self):
        pack = treatments.pack_for({"kind": "explainer"})
        for cue in {c for t in pro_looks() for c in templates.cues_of(t)}:
            self.assertFalse([t for t in templates.for_cue(cue) if t["id"].startswith(PRO)], cue)
            tid = treatments._template_for_cue(cue, pack, set(), {}, text=LINES["level"],
                                               props={"locations": [DAM, MEAD]})
            self.assertFalse(str(tid or "").startswith(PRO), (cue, tid))
        self.assertFalse([t for t in templates.for_component("motion") if t["id"].startswith(PRO)])
        for shot in MAP_SHOTS.values():
            ids, _ = treatments._map_ids(shot["overlay"], pack)
            self.assertFalse([x for x in ids if x.startswith(PRO)], ids)
        for t in pro_looks():
            self.assertFalse(treatments.auto_ok(t["id"]), t["id"])
            self.assertIsNone(treatments._least_used([t["id"]], {}), t["id"])
        for key in ("series", "then-now", "percent", "values", "count"):
            anim = treatments.animation_for(_seg(0, LINES[key]), {"subject": "Lake Powell"}, pack, None, counts={})
            self.assertFalse(str((anim or {}).get("template") or "").startswith(PRO), key)

    def test_the_director_naming_one_by_its_variant_does_not_place_it(self):
        shots = [{"subject": "Lake Powell", "overlay": {"type": "motion", "variant": "kx-keyword-stack",
                                                        "text": "The lake is still falling"}}, {"subject": "x"}]
        out = _plan(["The lake is still falling, and nobody knows how far.", PLAIN], shots=shots)
        self.assertNotIn("LIB_KX_KEYWORD_STACK", _used(out))


# --------------------------------------------------------------------------- the planner, switched on
class SwitchedOn(unittest.TestCase):
    def place(self, tid, line, shot=None, brief=None):
        with switched_on(only=tid):
            out = _plan([line, PLAIN, PLAIN], shots=[shot or {"subject": "Lake Powell"}, {"subject": "x"}, {"subject": "x"}],
                        brief=brief)
        got = [o for o in out["overlays"] if o.get("template") == tid]
        self.assertTrue(got, (tid, _used(out)))
        return got[0]

    def test_the_maps_join_their_rotations(self):
        pack = treatments.pack_for({"kind": "explainer"})
        with switched_on():
            one, _ = treatments._map_ids(MAP_SHOTS["place"]["overlay"], pack)
            two, _ = treatments._map_ids(MAP_SHOTS["pair"]["overlay"], pack)
            many, _ = treatments._map_ids(MAP_SHOTS["many"]["overlay"], pack)
            region, _ = treatments._map_ids(MAP_SHOTS["region"]["overlay"], pack)
            route = treatments._template_for_cue("route", pack, set(), {"MAP_TRACE_V1": 9, pack["route"]: 9})
        self.assertTrue(set(treatments.MX_PLACE) <= set(one))
        self.assertTrue(set(treatments.MX_PAIR) <= set(two))
        self.assertIn("LIB_MX_PATH_TRACE", many)
        self.assertIn("LIB_MX_REGION_PULSE", region)
        self.assertEqual(route, "LIB_MX_ROUTE_DRAW")
        # The satellite rotation keeps leading; the pro maps follow it.
        self.assertTrue(one[0].startswith("MAP_"))

    def test_data_lines_get_their_looks(self):
        ov = self.place("LIB_DX_LINE_ENDPOINT", LINES["series"])
        self.assertEqual([it["label"] for it in ov["items"]], ["1980", "2005", "2022"])
        self.assertEqual(ov.get("backdrop"), "blur")                # several values: full screen on the clip's still
        ov = self.place("LIB_DX_GHOST_BARS", LINES["then-now"])
        self.assertEqual(len(ov["items"]), 2)
        ov = self.place("LIB_DX_NESTED_SQUARES", LINES["values"])
        self.assertEqual(len(ov["items"]), 3)
        for tid in ("LIB_DX_UNIT_SPLIT", "LIB_DX_FILLED_FIGURE", "LIB_DX_CAPACITY_GAUGE"):
            ov = self.place(tid, LINES["percent"])
            self.assertEqual((ov["value"], ov["suffix"]), (22.0, "%"), tid)
            self.assertNotIn("compact", ov, tid)
        ov = self.place("LIB_DX_DRUM_COUNTER", LINES["count"])
        self.assertEqual(ov["value"], 4500.0)

    def test_a_lakes_level_is_the_reservoir_section_with_what_the_line_said(self):
        ov = self.place("LIB_DX_RESERVOIR_SECTION", LINES["level"])
        self.assertEqual((ov["value"], ov["suffix"]), (3517.0, "FT"))
        self.assertNotIn("total", ov)                               # no full pool said: none drawn
        ov = self.place("LIB_DX_RESERVOIR_SECTION", LINES["fell-to"])
        self.assertEqual((ov["value"], ov.get("total"), ov.get("label")), (3517.0, 3700.0, "down"))
        self.assertEqual(ov.get("items"), [{"label": "Minimum power pool", "value": 3490.0}])

    def test_documents_and_words_get_their_looks(self):
        ov = self.place("LIB_KX_ARTICLE_ZOOM", LINES["article"])
        self.assertEqual(ov.get("subtitle"), "Arizona Republic")      # as said: no "The" added
        self.assertIn("lowest level", ov.get("highlight", ""))
        self.place("LIB_KX_OFFICIAL_MEMO", LINES["memo"])
        self.place("LIB_KX_REPORT_COVER", LINES["report"])
        ov = self.place("LIB_KX_DEFINITION", LINES["term"])
        self.assertEqual(ov["subtitle"], "The pale band of minerals left on the canyon walls")
        ov = self.place("LIB_KX_ALERT_STRIP", LINES["warning"])
        self.assertEqual(ov.get("label"), "WARNING")
        ov = self.place("LIB_KX_LETTER_SIGNATURE", LINES["letter"])
        self.assertEqual(ov.get("label"), "Floyd Dominy")
        ov = self.place("LIB_KX_SOCIAL_POST", LINES["post"])
        self.assertEqual(ov.get("label"), "National Park Service")

    def test_maps_land_on_the_directors_places(self):
        for tid in treatments.MX_PLACE:
            self.place(tid, LINES["place"], shot=MAP_SHOTS["place"])
        for tid in treatments.MX_PAIR:
            ov = self.place(tid, "The water travels from Glen Canyon Dam to Hoover Dam.", shot=MAP_SHOTS["pair"])
            self.assertEqual(len(ov["locations"]), 2)
        self.place("LIB_MX_PATH_TRACE", "Lake Powell runs from Hite past Page to Glen Canyon Dam.", shot=MAP_SHOTS["many"])
        self.place("LIB_MX_REGION_PULSE", "All of this happens in northern Arizona.", shot=MAP_SHOTS["region"])

    def test_a_full_screen_scene_can_be_one_where_its_data_fits(self):
        pack = treatments.pack_for({"kind": "explainer"})
        with switched_on(only="LIB_DX_GHOST_BARS"):
            anim = treatments.animation_for(_seg(0, LINES["then-now"]), {"subject": "Lake Powell"}, pack, None, counts={})
        self.assertEqual(anim["template"], "LIB_DX_GHOST_BARS")
        with switched_on(only="LIB_DX_GHOST_BARS"):
            anim = treatments.animation_for(_seg(0, LINES["values"]), {"subject": "Lake Powell"}, pack, None, counts={})
        self.assertNotEqual((anim or {}).get("template"), "LIB_DX_GHOST_BARS")   # three values: not two bars


class ProProps(unittest.TestCase):
    def props(self, tid, cue, props, text="", shot=None):
        return treatments.pro_props(templates.get(tid), cue, props, text, shot)

    def test_each_look_keeps_off_a_line_it_does_not_fit(self):
        two = [{"label": "2000", "value": 95}, {"label": "2026", "value": 22}]
        three = two + [{"label": "2010", "value": 60}]
        self.assertIsNone(self.props("LIB_DX_LINE_ENDPOINT", "series", {"items": two}))
        self.assertIsNotNone(self.props("LIB_DX_LINE_ENDPOINT", "series", {"items": three}))
        self.assertIsNone(self.props("LIB_DX_GHOST_BARS", "compare-values", {"items": three}))
        self.assertIsNone(self.props("LIB_DX_NESTED_SQUARES", "compare-values",
                                     {"items": [{"label": "a", "value": 10}, {"label": "b", "value": 9.5}]}))
        self.assertIsNone(self.props("LIB_DX_FILLED_FIGURE", "big-number", {"value": 22, "suffix": "%"}))
        self.assertIsNone(self.props("LIB_DX_CAPACITY_GAUGE", "percent", {"value": 140, "suffix": "%"}))
        self.assertIsNone(self.props("LIB_DX_DRUM_COUNTER", "count", {"value": 3}))
        self.assertIsNone(self.props("LIB_DX_UNIT_SPLIT", "ratio", {"value": 1, "total": 40}))
        # "fell 12 feet" is a change, not the level the lake is at.
        self.assertIsNone(self.props("LIB_DX_RESERVOIR_SECTION", "change-length", {"value": 120, "suffix": "FT"},
                                     "Lake Powell fell 120 feet in two years."))
        self.assertIsNone(self.props("LIB_DX_RESERVOIR_SECTION", "measurement", {"value": 3517, "suffix": "%"}))
        self.assertIsNone(self.props("LIB_MX_ROUTE_DRAW", "route", {"locations": [DAM]}))
        self.assertIsNone(self.props("LIB_MX_PATH_TRACE", "several-places", {"locations": [DAM, MEAD]}))
        self.assertIsNone(self.props("LIB_MX_GLOBE_DIVE", "place", {"locations": []}))
        self.assertIsNone(self.props("LIB_KX_ARTICLE_ZOOM", "document", {"label": "REPORT", "text": "x"},
                                     "A new report found the lake falling."))
        self.assertIsNone(self.props("LIB_KX_OFFICIAL_MEMO", "document", {"label": "NEWSPAPER"}, ""))
        self.assertIsNone(self.props("LIB_KX_DEFINITION", "term", {"text": "Dead Pool"}, "That is what's called dead pool."))
        self.assertIsNone(self.props("LIB_KX_SOCIAL_POST", "quote", {"text": "x"}, "Someone said it."))
        self.assertIsNone(self.props("LIB_KX_KEYWORD_STACK", "headline",
                                     {"text": "A very long headline that would never fit as a stack of words"}))

    def test_a_portrait_quote_is_only_the_speakers_own_picture(self):
        q = {"text": "We are running out of water", "label": "Lake Powell"}
        self.assertIsNone(self.props("LIB_KX_QUOTE_PORTRAIT", "quote", q, "", {"subject": "Lake Powell"}))
        self.assertIsNone(self.props("LIB_KX_QUOTE_PORTRAIT", "quote", q, "",
                                     {"subject": "Bureau of Reclamation", "subjectType": "person"}))
        got = self.props("LIB_KX_QUOTE_PORTRAIT", "quote", q, "", {"subject": "Brad Udall", "subjectType": "person"})
        self.assertEqual(got["label"], "Brad Udall")

    def test_nothing_is_invented(self):
        # No newspaper, agency, writer or full pool appears unless the line names it.
        got = self.props("LIB_KX_OFFICIAL_MEMO", "document", {"label": "RECORDS", "text": "x"}, "Records show it.")
        self.assertNotIn("subtitle", got)
        got = self.props("LIB_KX_REPORT_COVER", "document", {"label": "REPORT", "text": "x"},
                         "The Bureau of Reclamation's new report found the lake falling.")
        self.assertEqual(got["subtitle"], "Bureau of Reclamation")
        got = self.props("LIB_KX_LETTER_SIGNATURE", "quote", {"text": "x"}, "\"It will fill,\" the letter said.")
        self.assertNotIn("label", got)
        got = self.props("LIB_DX_RESERVOIR_SECTION", "measurement", {"value": 3517, "suffix": "FT"},
                         "Lake Powell sits at an elevation of 3,517 feet.")
        self.assertNotIn("total", got)
        self.assertNotIn("items", got)
        # Any other look passes through untouched.
        self.assertEqual(treatments.pro_props(templates.get("LIB_CA_BAR_RACE"), "ranking", {"a": 1}, "", {}), {"a": 1})


# --------------------------------------------------------------------------- sounds
class Sounds(unittest.TestCase):
    def test_every_look_plays_its_own_shipped_sounds(self):
        for t in pro_looks():
            d = t["defaults"]
            self.assertEqual(d.get("soundTiming"), "look", t["id"])   # the component schedules them on its frames
            self.assertTrue(d["sounds"], t["id"])
            frames = int(round(d["duration"] * FPS))
            for c in d["sounds"]:
                self.assertIsNotNone(sfxplan.resolve_sound(c["name"], c.get("alt")), (t["id"], c))
                self.assertLess(c["at"], frames - 12, (t["id"], c))
                if "until" in c:
                    self.assertLessEqual(c["until"], frames, (t["id"], c))

    def test_a_number_only_ticks_and_nothing_punches(self):
        for t in pro_looks():
            cats = {sfxplan.category(c["name"]) for c in t["defaults"]["sounds"]}
            self.assertFalse(cats & {"riser", "glitch"}, t["id"])
            if t["id"].startswith("LIB_DX_"):
                self.assertTrue(cats <= {"tick", "ui"}, (t["id"], cats))    # count-roll, ui-tick, count-final
            if t["id"] != "LIB_KX_OFFICIAL_MEMO":
                self.assertNotIn("impact", cats, t["id"])                     # only the memo's rubber stamp lands

    def test_nothing_rings_past_the_look_or_over_the_voice(self):
        for t in pro_looks():
            d = t["defaults"]
            for frames in (int(round(d["duration"] * FPS)), int(round(2.5 * FPS))):
                got = sfxplan.look_sounds(d["sounds"], fps=FPS, frames=frames, text="22 percent", value=22.0,
                                          default_frames=int(round(d["duration"] * FPS)), voice_lufs=-18.0,
                                          locations=4)
                for s in got:
                    self.assertLessEqual(s["from"] + s["frames"], frames, (t["id"], s))
                    self.assertLessEqual(s["volume"], sfxplan.cap(-18.0, s["name"]) + 1e-6, (t["id"], s))


# --------------------------------------------------------------------------- formatting (the TypeScript)
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import * as F from "%(fmt)s";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const fig = (a: any[]) => F.figureOf(a[0], a[1], a[2], Boolean(a[3]));
process.stdout.write(JSON.stringify({
  fmt: input.fmt.map((v: number) => F.fmtNumber(v)),
  figure: input.figure.map((a: any[]) => F.figureText(fig(a))),
  count: input.count.map((a: any[]) => F.countText(fig(a), a[4], a[5])),
  change: input.change.map((a: number[]) => F.percentChange(a[0], a[1])),
  ratio: input.ratio.map((a: number[]) => F.ratioText(a[0], a[1])),
  dist: input.dist.map((a: any[]) => F.distanceText(a[0], a[1], a[2])),
  coord: input.coord.map((a: number[]) => F.coordText(a[0], a[1])),
  place: input.place.map((s: string) => F.placeName(s)),
  digits: input.digits.map((s: string) => F.digits(s)),
  stack: input.stack.map((a: any[]) => F.stackLines(a[0], a[1], a[2])),
  clip: input.clip.map((a: any[]) => F.clip(a[0], a[1], a[2])),
  initials: input.initials.map((s: string) => F.initials(s)),
  handle: input.handle.map((s: string) => F.handleOf(s)),
  rows: input.rows.map((x: unknown) => F.rowsOf(x).map((r) => [r.label, r.value])),
  ticks: input.ticks.map((a: number[]) => F.niceScale(a[0], a[1], a[2]).ticks),
  year: input.year.map((a: any[]) => F.isYear(a[0], a[1])),
}));
"""
M = "−"
CASES = {
    "fmt": [(3517, "3,517"), (2026, "2026"), (22, "22"), (4.5, "4.5"), (0.25, "0.25"), (-183, M + "183"),
            (1234567, "1,234,567"), (24.3, "24.3")],
    "figure": [((22, "%"), "22%"), ((3517, "FT"), "3,517 FT"), ((4.5, "B", "$"), "$4.5B"), ((120, "M", "", 1), "120 M"),
               ((4.4, "M"), "4.4M"), ((2026, ""), "2026"), ((2026, "FT"), "2,026 FT"), ((75, "MILLION"), "75 MILLION"),
               ((24.3, "MAF"), "24.3 MAF"), ((3517, "feet"), "3,517 FT"), ((22, "percent"), "22%")],
    "count": [((3517, "FT", "", 0, 1), "3,517"), ((3517, "FT", "", 0, 0.25), "879"), ((22, "%", "", 0, 0), "0"),
              ((3517, "FT", "", 0, 0.5, 3700), "3,609"), ((4.5, "B", "$", 0, 1), "4.5")],
    "change": [((95, 22), M + "77%"), ((100, 112), "+12%"), ((10, 10.5), "+5%"), ((0, 5), ""), ((50, 50), "0%")],
    "ratio": [((24.3, 5.3), "4.6×"), ((30, 2), "15×"), ((10, 10), "")],
    "dist": [((2.36, None, None), "2.4 MI"), ((191.6, None, None), "192 MI"), ((1234.4, None, None), "1,234 MI"),
             ((None, 15, "miles"), "15 MI"), ((12, 20, "km"), "20 KM"), ((None, None, None), ""),
             ((12, 30, "%"), "12 MI")],
    "coord": [((36.9375, -111.4844), "36.9375° N · 111.4844° W"), ((-33.8688, 151.2093), "33.8688° S · 151.2093° E")],
    "place": [("Page, Coconino County, Arizona, United States", {"name": "Page", "region": "Arizona"}),
              ("Hoover Dam, NV", {"name": "Hoover Dam", "region": "Nevada"}),
              ("Lake Powell", {"name": "Lake Powell", "region": ""})],
    "digits": [("twenty-two percent", "22%"), ("three thousand five hundred seventeen feet", "3,517 feet"),
               ("Lake Powell", "Lake Powell")],
    "stack": [(("The lake is still falling", 4, 10), ["The lake", "is still", "falling"]),
              (("Dead pool", 4, 10), ["Dead pool"])],
    "clip": [(("Lake Powell fell to its lowest level since it first filled", 30, True), "Lake Powell fell…"),
             (("Short line", 30, False), "Short line")],
    "initials": [("Floyd Dominy", "FD"), ("National Park Service", "NP"), ("Lake Powell Water Watch", "LP"), ("", "")],
    "handle": [("PowellWatch", "@PowellWatch"), ("@usbr", "@usbr"), ("", "")],
    "rows": [([{"label": "2000", "value": "95"}, {"label": "x"}, {"label": 2026, "value": 22}],
              [["2000", 95], ["2026", 22]])],
    "ticks": [((3400, 3750, 4), [3400, 3500, 3600, 3700, 3800]), ((0, 1, 4), [0, 0.25, 0.5, 0.75, 1])],
    "year": [((2026, ""), True), ((2026, "FT"), False), ((1963.5, ""), False), ((3517, ""), False)],
}


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Formatting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"fmt": FORMAT_TS.replace("\\", "/")[:-3]})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        payload = {k: [list(c[0]) if isinstance(c[0], tuple) else c[0] for c in v] for k, v in CASES.items()}
        run = subprocess.run([node, cls.bundle], input=json.dumps(payload), capture_output=True, text=True,
                             encoding="utf-8", timeout=120, check=True)
        cls.got = json.loads(run.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_every_case(self):
        for key, cases in CASES.items():
            for (given, want), got in zip(cases, self.got[key]):
                self.assertEqual(got, want, (key, given))

    def test_numbers_and_dates_on_screen_are_digits_said(self):
        # The planner writes a look's numbers in digits (numwords) and draws no date the narration did not say:
        # the line chart's x labels are the years the line itself named.
        with switched_on(only="LIB_DX_LINE_ENDPOINT"):
            out = _plan([LINES["series"], PLAIN, PLAIN], shots=[{"subject": "Lake Powell"}] * 3)
        ov = next(o for o in out["overlays"] if o.get("template") == "LIB_DX_LINE_ENDPOINT")
        for it in ov["items"]:
            self.assertIn(it["label"], LINES["series"])


if __name__ == "__main__":
    unittest.main()
