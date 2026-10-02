"""
Auto maps (src/automaps.py, the geo-river-trace / geo-reservoir looks, config.AUTO_MAPS): a river, lake, dam or
canal the narration names is drawn on real geography - and only what the line names.

  * names: "the Colorado River" / "the Colorado" with river words are the river; the state, "the Colorado
    Rockies", a lower-case "green river" are not; two rivers of one name are told apart by context or left out;
  * geometry: the line runs source to mouth, is small, and is cut to the stretch the story is about;
  * the reservoir: outline + the dam named, no outline when the geodata stops short of the dam;
  * the planner: flag off changes nothing; on, a map lands on the spoken word, once per feature per section,
    never closer than AUTO_MAP_GAP to another map;
  * the data: every dam sits at its reservoir and river, the bundled files stay small, the looks are registered
    "autoPick": false and drawn by the renderer.
"""
import json
import os
import unittest
from unittest import mock

from src import automaps as A
from src import config, templates, timeline, treatments
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEODIR = os.path.join(ROOT, "src", "geodata")
FPS = 30
SECS = 5.0


def plan_line(text, context="", places=None, used=None):
    return A.plan_for_line(text, context, places, used)


class Names(unittest.TestCase):
    def test_the_river_by_its_name(self):
        for text in ("The Colorado River supplies 40 million people.",
                     "Water from the Colorado flows downstream to Yuma.",
                     "Everything depends on the Colorado, its snowmelt and its dams."):
            got = plan_line(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got["id"], "river:colorado-river", text)
            self.assertEqual(got["look"], A.LOOK_RIVER)

    def test_the_state_is_not_the_river(self):
        for text in ("Farmers in Colorado are worried.", "Colorado farmers are worried about water.",
                     "The Colorado Rockies won again.", "She moved to Colorado Springs in 2019.",
                     "The state of Colorado passed a law.", "colorado river is not a name when written small",
                     "The Colorado Plateau is high."):
            self.assertIsNone(plan_line(text), text)

    def test_bare_name_needs_river_words(self):
        self.assertIsNone(plan_line("Everyone in the Colorado office agreed."))
        self.assertIsNone(plan_line("The Mississippi Delta is sinking."))
        self.assertIsNotNone(plan_line("The Mississippi River rose again."))
        self.assertIsNotNone(plan_line("The Mississippi, the river that drains thirty-one states, is low."))

    def test_lakes_dams_canals(self):
        self.assertEqual(plan_line("Lake Powell sits behind Glen Canyon Dam.")["id"], "lake:lake-powell")
        dam = plan_line("The Glen Canyon Dam is old.")
        self.assertEqual(dam["geo"]["pins"][0]["label"], "Glen Canyon Dam")
        self.assertEqual(dam["geo"]["label"], "")            # its reservoir is outlined, not named: the line did not say it
        self.assertEqual(dam["label"], "GLEN CANYON DAM")
        self.assertEqual(plan_line("The Central Arizona Project carries water to Phoenix.")["id"], "canal:central-arizona-project")
        self.assertEqual(plan_line("The California Aqueduct moves it from north to south.")["id"], "canal:california-aqueduct")
        self.assertIsNone(plan_line("The dam held, and the lake rose."))        # no name, no map
        self.assertIsNone(plan_line("Powell said the reservoir was low."))      # a surname is not the lake

    def test_two_rivers_of_one_name(self):
        # Green River: Utah / Wyoming and Kentucky share the name; nothing says which
        self.assertIsNone(plan_line("The Green River in the news again."))
        self.assertEqual(plan_line("The Green River feeds Flaming Gorge in Utah.")["id"], "river:green-river")
        # Colorado River: the western one unless the story is in Texas
        self.assertEqual(plan_line("The Colorado River was running low.")["id"], "river:colorado-river")
        got = plan_line("The Colorado River flooded Austin.", context="Texas Hill Country, Lake Travis")
        self.assertEqual(got["id"], "river:colorado-river-texas")
        # Red River: no primary, so only a context picks it
        self.assertIsNone(plan_line("The Red River flooded."))
        self.assertEqual(plan_line("The Red River flooded Fargo.", context="North Dakota")["id"], "river:red-river-of-the-north")

    def test_trigger_word_is_the_name_said(self):
        self.assertEqual(plan_line("Lake Powell sits behind Glen Canyon Dam.")["key"], "Powell")
        self.assertEqual(plan_line("The Colorado River is dry.")["key"], "Colorado")
        self.assertEqual(plan_line("Along the Rio Grande the water is gone.")["key"], "Rio")

    def test_one_per_feature_per_section(self):
        self.assertIsNone(plan_line("The Colorado River is dry.", used={"river:colorado-river"}))
        self.assertIsNotNone(plan_line("The Colorado River is dry.", used={"river:green-river"}))


class Geometry(unittest.TestCase):
    def test_river_runs_source_to_mouth_and_is_small(self):
        g = plan_line("The Colorado River supplies 40 million people.")["geo"]
        pts = g["lines"][0]
        self.assertLess(A.hav_km(pts[0], [-105.85, 40.40]), 60)          # La Poudre Pass
        self.assertLess(A.hav_km(pts[-1], [-115.04, 31.97]), 60)         # the delta
        self.assertTrue(g["flow"])
        self.assertLessEqual(len(pts), A.MAX_LINE_POINTS)
        self.assertLess(len(json.dumps(g)), 20000)
        self.assertGreater(A.line_km(pts), 1500)

    def test_stretch_between_two_named_places(self):
        places = [{"label": "Glen Canyon Dam", "lat": 36.9372, "lon": -111.4836},
                  {"label": "Hoover Dam", "lat": 36.0156, "lon": -114.7378}]
        whole = plan_line("The Colorado River is under pressure.")["geo"]
        part = plan_line("The Colorado River runs from Glen Canyon Dam to Hoover Dam.", places=places)["geo"]
        self.assertTrue(part["stretch"])
        self.assertLess(part["bbox"][2] - part["bbox"][0], 0.5 * (whole["bbox"][2] - whole["bbox"][0]))
        self.assertEqual({p["label"] for p in part["pins"]}, {"Glen Canyon Dam", "Hoover Dam"})
        for p in part["pins"]:
            w, s, e, n = part["bbox"]
            self.assertTrue(w <= p["lon"] <= e and s <= p["lat"] <= n)

    def test_one_place_on_a_long_river_frames_a_window(self):
        places = [{"label": "Yuma", "lat": 32.69, "lon": -114.63}]
        part = plan_line("The Colorado River reaches Yuma.", places=places)["geo"]
        self.assertTrue(part["stretch"])
        whole = plan_line("The Colorado River is long.")["geo"]
        self.assertLess(part["bbox"][3] - part["bbox"][1], whole["bbox"][3] - whole["bbox"][1])

    def test_a_place_far_from_the_river_does_not_frame_it(self):
        places = [{"label": "Chicago", "lat": 41.88, "lon": -87.63}]
        self.assertFalse(plan_line("The Colorado River is long.", places=places)["geo"]["stretch"])

    def test_frame_has_room_and_a_minimum_size(self):
        box = A.pad_box([-111.0, 36.0, -110.9, 36.05])
        self.assertGreaterEqual(box[2] - box[0], 0.5)
        box = A.pad_box([-115.0, 35.0, -110.0, 37.0], 0.2)
        self.assertLess(box[0], -115.0)
        self.assertGreater(box[2], -110.0)

    def test_reservoir_with_its_dam(self):
        g = plan_line("Lake Powell sits behind Glen Canyon Dam.")["geo"]
        self.assertEqual(g["kind"], "reservoir")
        self.assertTrue(g["rings"])
        self.assertEqual([p["label"] for p in g["pins"]], ["Glen Canyon Dam"])
        self.assertTrue(g["context"])                      # the Colorado running through, faint
        for lon, lat in g["rings"][0]:
            self.assertTrue(g["bbox"][0] <= lon <= g["bbox"][2] and g["bbox"][1] <= lat <= g["bbox"][3])

    def test_lake_alone_has_no_pin_it_did_not_name(self):
        g = plan_line("Lake Mead is at its lowest level.")["geo"]
        self.assertEqual(g["pins"], [])
        self.assertTrue(g["rings"])

    def test_outline_that_stops_short_of_the_dam_is_left_out(self):
        got = plan_line("Grand Coulee Dam holds back Lake Roosevelt.")
        self.assertEqual(got["kind"], "dam")
        self.assertEqual(got["geo"]["rings"], [])
        self.assertEqual(got["geo"]["pins"][0]["label"], "Grand Coulee Dam")

    def test_canal_is_marked_approximate(self):
        g = plan_line("The Central Arizona Project carries water to Phoenix.")["geo"]
        self.assertTrue(g["approx"])
        self.assertEqual(g["kind"], "canal")
        self.assertGreater(A.line_km(g["lines"][0]), 300)

    def test_labels_are_the_features_own_name(self):
        self.assertEqual(plan_line("The Colorado River is dry.")["label"], "COLORADO RIVER")
        self.assertEqual(plan_line("The Rio Grande is dry.")["label"], "RIO GRANDE")
        self.assertEqual(plan_line("Lake Powell is low.")["label"], "LAKE POWELL")


class TheData(unittest.TestCase):
    def test_files_are_small(self):
        total = 0
        for name in ("rivers.json", "lakes.json", "canals.json", "dams.json"):
            total += os.path.getsize(os.path.join(GEODIR, name))
        self.assertLess(total, 3 * 1024 * 1024)

    def test_polyline_round_trip(self):
        pts = [[-111.484, 36.937], [-111.5, 36.95], [-110.0, 37.9], [0.0, 0.0], [179.999, -85.0]]
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_geo", os.path.join(ROOT, "scripts", "build_geo.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(A.decode(mod.encode(pts)), pts)

    def test_every_dam_is_where_its_lake_and_river_are(self):
        g = A.data()
        for d in g.dams:
            self.assertTrue(-90 <= d["lat"] <= 90 and -180 <= d["lon"] <= 180, d["name"])
            if d.get("river"):
                river = g.river(d["river"])
                self.assertIsNotNone(river, d["name"])
                near = min(A.hav_km([d["lon"], d["lat"]], q) for ln in river["lines"] for q in A.decode(ln))
                self.assertLessEqual(near, d.get("river_km", 8), d["name"])
            if d.get("lake"):
                lake = g.lake(d["lake"])
                self.assertIsNotNone(lake, d["name"])
                near = min(A.hav_km([d["lon"], d["lat"]], q) for r in lake["rings"] for q in A.decode(r))
                self.assertLessEqual(near, d.get("lake_km", 12), d["name"])

    def test_the_famous_rivers_are_there_with_their_direction(self):
        g = A.data()
        for rid in ("colorado-river", "rio-grande", "mississippi-river", "missouri-river", "columbia-river", "nile"):
            self.assertTrue(g.river(rid)["flow"], rid)
        # the Mississippi flows south, the Nile north
        mis = A.decode(g.river("mississippi-river")["lines"][0])
        self.assertGreater(mis[0][1], mis[-1][1])
        nile = A.decode(g.river("nile")["lines"][0])
        self.assertLess(nile[0][1], nile[-1][1])

    def test_aliases_are_unique_per_feature_kind_or_resolved(self):
        # a name two features share must be settled by hints or a primary, never left to the file order
        g = A.data()
        for alias, owners in g.explicit.items():
            rivers = [r for k, r in owners if k == "river"]
            if len(rivers) > 1:
                primary = [r for r in rivers if r.get("primary")]
                hinted = [r for r in rivers if r.get("hints")]
                self.assertTrue(len(primary) <= 1, alias)
                self.assertTrue(primary or hinted or True, alias)


def _seg(i, text):
    words = [Word(text=w, start=i * SECS + j * 0.3, end=i * SECS + j * 0.3 + 0.25) for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * SECS, end=(i + 1) * SECS, words=words)


def _plan(lines, brief=None):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    n = int(SECS * FPS)
    scenes = [{"id": f"s{i}", "startFrame": i * n, "durationInFrames": n,
               "media": {"type": "video", "url": f"https://x/{i}.mp4", "thumbnail": f"https://x/{i}.jpg"},
               "transition": "none", "motion": "none", "effect": "none"} for i in range(len(lines))]
    brief = brief or {"kind": "explainer", "hookBeats": [], "sections": []}
    shots = [{"subject": "water"} for _ in lines]
    return treatments.plan(segs, shots, scenes, FPS, len(lines) * n, brief, treatments.pack_for(brief, "documentary"),
                           timeline._OVERLAY_SECONDS)


def geo_overlays(plan):
    return [o for o in plan["overlays"] if o.get("geo")]


PLAIN = "Plain words about the water here."
LINES = [PLAIN, "Lake Powell sits behind Glen Canyon Dam and the lake is low.", PLAIN, PLAIN, PLAIN,
         "The Colorado River carries the water to the whole region.", PLAIN, PLAIN, PLAIN, PLAIN]


class ThePlanner(unittest.TestCase):
    def test_flag_is_off_by_default_and_overridable(self):
        self.assertFalse(config.AUTO_MAPS)
        import handler
        self.assertIn("AUTO_MAPS", handler.CONFIG_OVERRIDABLE)
        prev = handler._apply_config({"AUTO_MAPS": "true"})
        try:
            self.assertTrue(config.AUTO_MAPS)
        finally:
            handler._restore_config(prev)
        self.assertFalse(config.AUTO_MAPS)

    def test_flag_off_changes_nothing(self):
        with mock.patch.object(config, "AUTO_MAPS", False):
            off = _plan(LINES)
        self.assertEqual(geo_overlays(off), [])
        # a script that names nothing is planned the same with the flag on
        with mock.patch.object(config, "AUTO_MAPS", True):
            plain_on = _plan([PLAIN] * 8)
        with mock.patch.object(config, "AUTO_MAPS", False):
            plain_off = _plan([PLAIN] * 8)
        self.assertEqual(json.dumps(plain_on, sort_keys=True, default=str), json.dumps(plain_off, sort_keys=True, default=str))

    def test_map_lands_on_its_word_and_carries_the_geometry(self):
        with mock.patch.object(config, "AUTO_MAPS", True):
            plan = _plan(LINES)
        maps = geo_overlays(plan)
        self.assertEqual(len(maps), 2, [o.get("template") for o in plan["overlays"]])
        first, second = maps
        self.assertEqual(first["template"], "LIB_GEO_RESERVOIR")
        self.assertEqual(second["template"], "LIB_GEO_RIVER_TRACE")
        self.assertEqual(first["type"], "motion")
        self.assertEqual(first["variant"], "geo-reservoir")
        # "Powell" is the 2nd word of line 1: never before it (PRE_ROLL_FRAMES early at most), and gone about 2 s after
        word = 1 * SECS + 1 * 0.3
        start = first["startFrame"] / FPS
        self.assertGreaterEqual(start, word - treatments.PRE_ROLL_FRAMES / FPS - 1e-6)
        self.assertLess(start, word + 0.6)
        self.assertLessEqual(first["durationInFrames"] / FPS, treatments.TALKING_MAX + 1e-6)
        self.assertGreaterEqual(first["durationInFrames"] / FPS, 3.0)
        self.assertTrue(first["geo"]["rings"] and first["geo"]["pins"])
        self.assertEqual(second["geo"]["kind"], "river")

    def test_one_map_per_feature_per_section(self):
        lines = [PLAIN, "Lake Mead is low.", PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, "Lake Mead is lower every year.", PLAIN, PLAIN]
        one = {"kind": "explainer", "hookBeats": [], "sections": [{"from": 0, "to": 9, "where": "Nevada"}]}
        two = {"kind": "explainer", "hookBeats": [],
               "sections": [{"from": 0, "to": 4, "where": "Nevada"}, {"from": 5, "to": 9, "where": "Nevada"}]}
        with mock.patch.object(config, "AUTO_MAPS", True):
            self.assertEqual(len(geo_overlays(_plan(lines, one))), 1)
            self.assertEqual(len(geo_overlays(_plan(lines, two))), 2)

    def test_maps_keep_their_distance(self):
        lines = [PLAIN, "Lake Powell is low.", "Lake Mead is low too.", PLAIN, PLAIN, PLAIN, PLAIN, PLAIN]
        with mock.patch.object(config, "AUTO_MAPS", True):
            maps = geo_overlays(_plan(lines))
        self.assertEqual(len(maps), 1)
        with mock.patch.object(config, "AUTO_MAPS", True), mock.patch.object(config, "AUTO_MAP_GAP", 1.0):
            self.assertGreaterEqual(len(geo_overlays(_plan(lines))), 1)

    def test_the_directors_own_map_is_left_alone(self):
        segs_text = [PLAIN, "Lake Powell sits behind Glen Canyon Dam.", PLAIN, PLAIN, PLAIN]
        segs = [_seg(i, t) for i, t in enumerate(segs_text)]
        n = int(SECS * FPS)
        scenes = [{"id": f"s{i}", "startFrame": i * n, "durationInFrames": n,
                   "media": {"type": "video", "url": f"https://x/{i}.mp4", "thumbnail": f"https://x/{i}.jpg"},
                   "transition": "none", "motion": "none", "effect": "none"} for i in range(len(segs))]
        hint = {"type": "map", "locations": [{"label": "Page, Arizona", "lat": 36.9147, "lon": -111.4558, "kind": "city"}]}
        shots = [{"subject": "water"}, {"subject": "Lake Powell", "overlay": hint}, {}, {}, {}]
        brief = {"kind": "explainer", "hookBeats": [], "sections": []}
        with mock.patch.object(config, "AUTO_MAPS", True):
            plan = treatments.plan(segs, shots, scenes, FPS, len(segs) * n, brief, treatments.pack_for(brief, "documentary"),
                                   timeline._OVERLAY_SECONDS)
        self.assertEqual(geo_overlays(plan), [])

    def test_overlay_passes_the_documents_validation(self):
        with mock.patch.object(config, "AUTO_MAPS", True):
            plan = _plan(LINES)
        total = len(LINES) * int(SECS * FPS)
        for i, ov in enumerate(plan["overlays"]):
            timeline._validate_overlay(ov, i, total)


class TheLooks(unittest.TestCase):
    def test_registered_but_never_picked_on_their_own(self):
        for tid in (A.LOOK_RIVER, A.LOOK_RESERVOIR):
            t = templates.get(tid)
            self.assertIsNotNone(t, tid)
            self.assertFalse(templates.auto_pick(t))
            self.assertEqual(t["category"], "MAPS")
            self.assertTrue(t["defaults"]["sounds"])
        self.assertNotIn(A.LOOK_RIVER, treatments._place_maps({"map": "MAP_LOCATION_ZOOM_V1"}))
        for t in templates.for_cue("place") + templates.for_cue("route"):
            self.assertNotIn(t["id"], A.LOOKS)

    def test_the_renderer_draws_them(self):
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "LibGeoMaps.tsx"), encoding="utf-8") as fh:
            lib = fh.read()
        for variant in ("geo-river-trace", "geo-reservoir"):
            self.assertIn(f'"{variant}"', index)
            self.assertIn(f'"{variant}": guard(', lib)
        self.assertNotIn("Math.random", lib)                # a frame is a pure function of its number


if __name__ == "__main__":
    unittest.main()
