"""
Looks pack 3 (2026-10-08, the owner: "more animations, better animations ... extra ones that are perfectly quality
ones"): ten looks in the kinetic-type system (remotion/src/components/lib/LibKtPack3.tsx, LibKtMaps3.tsx;
scripts/library_looks_ktpack3.json) and two cut transitions (remotion/src/transitions/TransitionFrame.tsx).

  - registered (family "ktp3", template ids KT_*), the planner may pick each, with its least time, its built-in
    sound, its editor sample and its motion class; the transitions in the registry, the renderer and the styles;
  - drawn by the renderer, sized from the one type scale (nothing a viewer reads under 24 px at 1080p), never the
    retired style;
  - picked only where the narration says what they show (src/lookpack3.py), on their words, each part on its own
    word: a ranking, a lake's levels, a scale, a change, a streak (never a span of time), an alert, a list of
    states; an older map look upgraded to the storm track, the totals map or the route where its line fits;
  - spaced (24 s apart, two a minute, each its own gap), never over a premium look that says the same, in place of
    an older one that does, on the relook action too.
Offline: no network, no paid calls.
"""
import json
import os
import re
import unittest

from src import datalooks as dl
from src import lookpack3 as p3
from src import lookplace, relook, templates, timeline, treatments

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion", "src")
LIB = os.path.join(REMOTION, "components", "lib")
FPS = 30
PACK = ["KT_RANKING", "KT_WATERLINE", "KT_SEVERITY", "KT_DELTA", "KT_STREAK", "KT_ALERT", "KT_ROUTE", "KT_STORM",
        "KT_TOTALS", "KT_REGIONS"]
FILES = {"LibKtPack3.tsx": ["kt-ranking", "kt-waterline", "kt-severity", "kt-delta", "kt-streak", "kt-alert"],
         "LibKtMaps3.tsx": ["kt-route", "kt-storm", "kt-totals", "kt-regions"]}
PHOENIX = {"label": "Phoenix, Arizona, United States", "lat": 33.448, "lon": -112.074}
TUCSON = {"label": "Tucson, Arizona, United States", "lat": 32.222, "lon": -110.975}
FLAGSTAFF = {"label": "Flagstaff, Arizona, United States", "lat": 35.198, "lon": -111.651}
HAVASU = {"label": "Lake Havasu, Arizona, United States", "lat": 34.483, "lon": -114.322}
MATAGORDA = {"label": "Matagorda, Texas, United States", "lat": 28.69, "lon": -95.97}
HOUSTON = {"label": "Houston, Texas, United States", "lat": 29.76, "lon": -95.37}
SHREVEPORT = {"label": "Shreveport, Louisiana, United States", "lat": 32.52, "lon": -93.75}


def words_for(lines, per_word=0.32):
    out = []
    for t, line in lines:
        for tok in line.split(" "):
            if tok:
                out.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.02, 3)})
                t += per_word
    return out


def found(line):
    got, _log = p3.find(dl.Narration(words_for([(0.0, line)])), ok=lambda tid: True)
    return got


def one(line, tid):
    got = [c for c in found(line) if c["tid"] == tid]
    return got[0] if got else None


def doc_for(lines, overlays=(), seconds=None):
    words = words_for(lines)
    total = int((seconds or (max(w["end"] for w in words) + 12.0)) * FPS)
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": total, "overlays": list(overlays), "sfx": [],
            "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": total, "text": "", "words": words,
                        "media": {"type": "video", "url": "https://x/0.mp4"}}]}


def said_at(words, token):
    return next(w["start"] for w in words if w["text"].strip(",.") == token)


class Registered(unittest.TestCase):
    def test_ten_looks_the_planner_may_pick_with_their_least_time_sound_and_sample(self):
        for tid in PACK:
            t = templates.get(tid)
            self.assertTrue(t, tid)
            self.assertTrue(treatments.auto_ok(tid), tid)
            self.assertEqual(templates.family(t), "ktp3", tid)
            self.assertEqual(t["defaults"]["variant"], p3.variant_of(tid), tid)
            least = float(t["defaults"].get("leastSeconds") or 0)
            self.assertGreaterEqual(least, 3.0, tid)
            self.assertGreaterEqual(float(t["defaults"]["duration"]), least, tid)
            self.assertGreaterEqual(treatments.animation_seconds(t), least, tid)
            self.assertTrue(t["defaults"]["sounds"], tid)
            self.assertIsInstance(t["defaults"].get("sample"), dict, tid)
        self.assertEqual(set(PACK), set(p3.IDS))
        self.assertEqual(templates.check(), [])

    def test_the_renderer_draws_each_one_and_the_index_lists_it(self):
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        for name, variants in FILES.items():
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            drawn = set(re.findall(r'"(kt-[a-z-]+)": guard\(', src[src.index("export const LOOKS"):]))
            self.assertEqual(drawn, set(variants), name)
            for v in variants:
                self.assertIn(f'"{v}"', index, v)

    def test_the_maps_cover_the_frame_and_the_cards_ride_on_the_footage(self):
        with open(os.path.join(REMOTION, "components", "motion", "lookClasses.json"), encoding="utf-8") as fh:
            classes = json.load(fh)["looks"]
        self.assertEqual({t for t in PACK if classes.get(t) == "full"}, {"KT_ROUTE", "KT_STORM", "KT_TOTALS", "KT_REGIONS"})
        self.assertEqual((classes["KT_RANKING"], classes["KT_WATERLINE"], classes["KT_ALERT"]), ("panel", "panel", "tag"))
        for tid in ("KT_ROUTE", "KT_STORM", "KT_TOTALS", "KT_REGIONS"):
            self.assertIn("own-backdrop", templates.get(tid)["tags"], tid)

    def test_sizes_from_the_one_scale_readable_on_a_phone(self):
        with open(os.path.join(LIB, "typeScale.json"), encoding="utf-8") as fh:
            pack = json.load(fh)["pack3"]
        cap = 0.727
        for role, v in pack.items():
            if "share" in v and role != "dayCell":
                self.assertGreaterEqual(v["share"] / cap * 1080, 24.0, role)
        self.assertLessEqual(pack["rankCard"]["w"], 0.4)
        self.assertLessEqual(pack["waterCard"]["w"], 0.4)
        self.assertLessEqual(pack["streakNumber"]["share"], 0.1)       # a figure, not a poster

    def test_never_the_retired_style_and_never_a_raw_picture(self):
        for name in FILES:
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            for bad in ("WebkitTextStroke", "-webkit-text-stroke", "#FFD400", "ANTON", "Bebas", "Anton", "<Img", "<img"):
                self.assertNotIn(bad, src, (name, bad))

    def test_the_two_transitions_are_registered_drawn_and_in_the_styles_turns(self):
        reg = templates.load()
        values = {t["value"]: t for t in reg["transitions"]}
        for v in p3.TRANSITIONS:
            self.assertIn(v, values, v)
            self.assertIn(v, timeline.TRANSITIONS, v)
            self.assertIn(v, timeline._TRANSITION_SFX, v)
        with open(os.path.join(REMOTION, "types.ts"), encoding="utf-8") as fh:
            types = fh.read()
        with open(os.path.join(REMOTION, "transitions", "TransitionFrame.tsx"), encoding="utf-8") as fh:
            frame = fh.read()
        for v in p3.TRANSITIONS:
            self.assertIn(f'"{v}"', types, v)
            self.assertIn(f'case "{v}"', frame, v)
        cycles = {s: spec["cycle"] for s, spec in timeline._STYLE_TRANSITIONS.items()}
        self.assertIn("light-sweep", cycles["documentary"])
        self.assertIn("soft-whip", cycles["weather"])
        # each one once in a turn: never more often than the others
        for s, cyc in cycles.items():
            for v in p3.TRANSITIONS:
                self.assertLessEqual(cyc.count(v), 1, (s, v))


class Rules(unittest.TestCase):
    def test_names_with_their_values_fill_their_rank_slots_on_their_words(self):
        c = one("Over the weekend Phoenix got 2.1 inches of rain, Tucson 1.8, Flagstaff 3.4 and Yuma just 0.4.", p3.RANKING)
        self.assertIsNotNone(c)
        items = c["props"]["items"]
        self.assertEqual([it["label"] for it in items], ["Flagstaff", "Phoenix", "Tucson", "Yuma"])  # rank order
        self.assertEqual([it["value"] for it in items], [3.4, 2.1, 1.8, 0.4])
        self.assertEqual(c["props"]["suffix"], "IN")
        self.assertEqual(c["props"]["subtitle"], "Inches of rain")
        # each row on its own word: Flagstaff (said third) after Phoenix (said first)
        at = {it["label"]: it["at"] for it in items}
        self.assertLess(at["Phoenix"], at["Tucson"])
        self.assertLess(at["Tucson"], at["Flagstaff"])
        self.assertLess(at["Flagstaff"], at["Yuma"])

    def test_the_driest_ranks_from_the_lowest_and_a_list_of_names_ranks_as_said(self):
        c = one("The driest places this year were Yuma with 0.4 inches, Las Vegas with 1.1 and Phoenix with 2.9.", p3.RANKING)
        self.assertEqual([it["label"] for it in c["props"]["items"]], ["Yuma", "Las Vegas", "Phoenix"])
        c = one("The five driest cities in America are Yuma, Las Vegas, Phoenix, El Paso and Tucson.", p3.RANKING)
        self.assertEqual([it["label"] for it in c["props"]["items"]], ["Yuma", "Las Vegas", "Phoenix", "El Paso", "Tucson"])
        self.assertEqual(c["props"]["text"], "Driest cities in America")
        self.assertIsNone(one("Phoenix and Tucson both got about 2 inches.", p3.RANKING))     # two: a comparison

    def test_a_lakes_levels_with_their_years_and_a_drop_since_a_year(self):
        c = one("In 1983 Lake Mead stood at 1,225 feet above sea level. By 2022 it had fallen to 1,040 feet.", p3.WATERLINE)
        self.assertEqual(c["props"]["text"], "Lake Mead")
        self.assertEqual([(it["label"], it["value"]) for it in c["props"]["items"]], [("1983", 1225), ("2022", 1040)])
        self.assertEqual(c["props"]["subtitle"], "Feet above sea level")
        c = one("Lake Powell has dropped 170 feet since 2000.", p3.WATERLINE)
        self.assertEqual((c["props"]["value"], [it["label"] for it in c["props"]["items"]]), (170, ["2000", "Now"]))
        # feet with years but no lake: not a waterline
        self.assertIsNone(one("The tower grew from 300 feet in 1990 to 450 feet in 2020.", p3.WATERLINE))

    def test_a_change_from_one_figure_to_another_and_one_since_a_year(self):
        c = one("The river's flow fell from 18 million acre-feet to just 12 million.", p3.DELTA)
        self.assertEqual(([it["value"] for it in c["props"]["items"]], c["props"]["suffix"]), ([18, 12], "M"))
        self.assertEqual(c["props"]["subtitle"], "Million acre-feet")
        self.assertGreater(c["props"]["items"][1]["at"], 0.5)               # the new figure waits for its word
        c = one("Snowpack across the basin is down 38 percent since 2000.", p3.DELTA)
        self.assertEqual((c["props"]["value"], c["props"]["suffix"], c["props"]["label"]), (-38, "%", "Since 2000"))
        # a lake's level in feet is its waterline, not a change
        self.assertIsNone(one("Lake Mead fell from 1,225 feet to 1,040 feet.", p3.DELTA))

    def test_a_streak_of_days_and_never_a_span_of_time(self):
        c = one("Phoenix just endured 31 straight days above 110 degrees.", p3.STREAK)
        self.assertEqual((c["props"]["value"], c["props"]["text"], c["props"]["subtitle"]), (31, "In a row", "Above 110 degrees"))
        self.assertEqual(one("Las Vegas has now gone 143 days without rain.", p3.STREAK)["props"]["text"], "Without rain")
        self.assertEqual(one("It rained for nine days in a row.", p3.STREAK)["props"]["value"], 9)
        for line in ["Three days later, the water was gone.", "Within 48 hours the river crested.",
                     "It rained for three days.", "In two days the cuts begin."]:
            self.assertIsNone(one(line, p3.STREAK), line)

    def test_a_level_on_its_scale(self):
        c = one("By then it had become a Category 4 hurricane with winds of 140 mph.", p3.SEVERITY)
        self.assertEqual((c["props"]["text"], c["props"]["value"], c["props"]["total"]), ("Category 4", 4, 5))
        self.assertEqual(c["props"]["subtitle"], "Winds of 140 mph")
        self.assertEqual(one("An EF-3 tornado tore through the town.", p3.SEVERITY)["props"]["text"], "EF3")
        c = one("Most of Arizona is now in exceptional drought.", p3.SEVERITY)
        self.assertEqual((c["props"]["text"], c["props"]["value"]), ("Exceptional drought", 5))
        c = one("The government declared a Tier 2 shortage on the river.", p3.SEVERITY)
        self.assertEqual((c["props"]["text"], c["props"]["value"]), ("Tier 2", 3))
        c = one("Forecasters put the region at a level 4 out of 5 risk of flash flooding.", p3.SEVERITY)
        self.assertEqual((c["props"]["text"], c["props"]["subtitle"]), ("Level 4 of 5", "Risk of flash flooding"))
        # a category of something else is no storm scale
        self.assertIsNone(one("It fell in category 3 of the budget.", p3.SEVERITY))

    def test_an_official_alert_with_what_was_said_of_it(self):
        c = one("The National Weather Service issued a flash flood warning until 9 p.m. for Clark County.", p3.ALERT)
        self.assertEqual((c["props"]["text"], c["props"]["subtitle"], c["props"]["label"]),
                         ("Flash Flood Warning", "Until 9 PM · Clark County", "National Weather Service"))
        self.assertEqual(one("Evacuation orders went out across the valley.", p3.ALERT)["props"]["text"], "Evacuation Orders")
        self.assertIsNone(one("Experts warn the lake could keep falling.", p3.ALERT))

    def test_a_list_of_states_and_never_a_states_name_inside_another(self):
        c = one("Seven states share the Colorado River: Wyoming, Colorado, Utah, New Mexico, Nevada, Arizona and California.",
                p3.REGIONS)
        self.assertEqual(len(c["props"]["items"]), 7)
        self.assertEqual(c["props"]["text"], "Colorado River")
        ats = [it["at"] for it in c["props"]["items"]]
        self.assertEqual(ats, sorted(ats))
        self.assertIsNone(one("Arizona and Nevada signed it.", p3.REGIONS))                  # two: no map of states
        self.assertIsNone(one("George Washington, the Arizona Republic and New York Times ran it.", p3.REGIONS))

    def test_spaced_and_never_crowded(self):
        p = p3.Pace()
        self.assertTrue(p.allows(p3.RANKING, 10.0))
        p.note(p3.RANKING, 10.0)
        self.assertFalse(p.allows(p3.ALERT, 30.0))                          # within PACK3_GAP of another
        self.assertTrue(p.allows(p3.ALERT, 40.0))
        p.note(p3.ALERT, 40.0)
        self.assertFalse(p.allows(p3.STREAK, 65.0))                         # a third in one minute
        self.assertFalse(p.allows(p3.RANKING, 80.0))                        # the same look within its EVERY
        self.assertTrue(p.allows(p3.RANKING, 120.0))
        self.assertTrue(p.allows("KT_NUMBER", 11.0))


class Planned(unittest.TestCase):
    def test_on_their_words_each_part_landing_on_its_own_and_their_figures_not_shown_twice(self):
        line = "Over the weekend Phoenix got 2.1 inches of rain, Tucson 1.8, Flagstaff 3.4 and Yuma just 0.4."
        doc = doc_for([(2.0, line)])
        rep = dl.finish(doc)
        got = [o for o in doc["overlays"] if o["template"] == p3.RANKING]
        self.assertEqual(len(got), 1, rep["added"])
        o = got[0]
        words = doc["scenes"][0]["words"]
        self.assertLessEqual(abs(o["startFrame"] / FPS - (said_at(words, "Phoenix") - dl.MAX_LEAD_S)), 0.1)
        start = o["startFrame"] / FPS
        for it in o["items"]:
            self.assertAlmostEqual(start + it["at"], said_at(words, it["label"]), delta=0.12)
        self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS))
        self.assertGreaterEqual(dl.min_seconds(o), max(it["at"] for it in o["items"]) + p3.HOLD[p3.RANKING])
        self.assertEqual([x["template"] for x in doc["overlays"]], [p3.RANKING])      # no chip for 2.1 or 3.4

    def test_an_older_look_saying_the_same_gives_way_and_a_premium_one_keeps_the_moment(self):
        line = "Over the weekend Phoenix got 2.1 inches of rain, Tucson 1.8, Flagstaff 3.4 and Yuma just 0.4."
        old = {"type": "ranking", "template": "CHART_RANKING_V1", "startFrame": int(3.0 * FPS), "durationInFrames": 150,
               "text": "RAIN"}
        doc = doc_for([(2.0, line)], [old])
        rep = dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]], [p3.RANKING])
        self.assertIn("CHART_RANKING_V1", [r["template"] for r in rep["removed"]])
        lake = "In 1983 Lake Mead stood at 1,225 feet above sea level. By 2022 it had fallen to 1,040 feet."
        trend = {"type": "motion", "template": "KT_TREND", "variant": "kt-trend", "startFrame": int(2.2 * FPS),
                 "durationInFrames": 200, "items": [{"label": "1983", "value": 1225}, {"label": "2022", "value": 1040}]}
        doc = doc_for([(2.0, lake)], [trend])
        dl.finish(doc)
        self.assertIn("KT_TREND", [o["template"] for o in doc["overlays"]])
        self.assertNotIn(p3.WATERLINE, [o["template"] for o in doc["overlays"]])

    def test_a_brand_kit_without_them_keeps_the_figures_as_kt_looks(self):
        line = "Phoenix just endured 31 straight days above 110 degrees."
        doc = doc_for([(2.0, line)])
        with templates.only({"KT_NUMBER", "KT_CHIP", "KT_PERCENT"}):
            dl.finish(doc)
        ids = [o["template"] for o in doc["overlays"]]
        self.assertNotIn(p3.STREAK, ids)
        self.assertTrue(set(ids) & {"KT_NUMBER", "KT_CHIP"}, ids)

    def test_the_planners_own_are_planned_again_and_one_made_in_the_editor_stays(self):
        line = "Phoenix just endured 31 straight days above 110 degrees."
        doc = doc_for([(2.0, line)])
        dl.finish(doc)
        dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]].count(p3.STREAK), 1)
        mine = {"type": "motion", "template": p3.ALERT, "variant": "kt-alert", "text": "Heat Warning", "startFrame": 300,
                "durationInFrames": 150}
        doc["overlays"].append(mine)
        dl.finish(doc)
        self.assertIn(p3.ALERT, [o["template"] for o in doc["overlays"]])


class Maps(unittest.TestCase):
    def _map(self, tid, locs, at=3.0, frames=180):
        return {"type": "map", "template": tid, "variant": "spread", "startFrame": int(at * FPS),
                "durationInFrames": frames, "text": "", "locations": [dict(x) for x in locs]}

    def test_a_storms_line_turns_its_map_into_the_storm_track_with_its_times(self):
        line = ("The storm made landfall near Matagorda early Monday, moved over Houston by 10 a.m. "
                "and reached Shreveport Tuesday morning.")
        doc = doc_for([(2.0, line)], [self._map("MAP_SPREAD_V1", [MATAGORDA, HOUSTON, SHREVEPORT])])
        rep = dl.finish(doc)
        storm = [o for o in doc["overlays"] if o["template"] == p3.STORM]
        self.assertEqual(len(storm), 1, rep.get("upgraded"))
        o = storm[0]
        self.assertEqual([x["label"].split(",")[0] for x in o["locations"]], ["Matagorda", "Houston", "Shreveport"])
        self.assertEqual([it["label"] for it in o["items"]], ["Early Monday", "10 AM", "Tuesday Morning"])
        self.assertEqual(o["upgraded"], "MAP_SPREAD_V1")
        self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS))

    def test_values_for_its_places_make_the_totals_map_and_the_ranking_stands_down(self):
        line = "Over the weekend Phoenix got 2.1 inches of rain, Tucson 1.8, and Flagstaff 3.4."
        doc = doc_for([(2.0, line)], [self._map("MAP_SPREAD_V1", [PHOENIX, TUCSON, FLAGSTAFF], at=2.5)])
        dl.finish(doc)
        ids = [o["template"] for o in doc["overlays"]]
        self.assertIn(p3.TOTALS, ids)
        self.assertNotIn(p3.RANKING, ids)
        o = [x for x in doc["overlays"] if x["template"] == p3.TOTALS][0]
        self.assertEqual([(it["label"], it["value"]) for it in o["items"]], [("Phoenix", 2.1), ("Tucson", 1.8), ("Flagstaff", 3.4)])
        self.assertEqual(o["suffix"], "IN")

    def test_a_route_through_its_places_in_the_order_said(self):
        line = "The canal carries water 336 miles from Lake Havasu past Phoenix to Tucson."
        doc = doc_for([(2.0, line)], [self._map("MAP_SPREAD_V1", [TUCSON, HAVASU, PHOENIX], at=3.0)])
        dl.finish(doc)
        o = [x for x in doc["overlays"] if x["template"] == p3.ROUTE][0]
        self.assertEqual([x["label"].split(",")[0] for x in o["locations"]], ["Lake Havasu", "Phoenix", "Tucson"])
        self.assertEqual((o["value"], o["suffix"]), (336, "MI"))

    def test_a_two_place_route_takes_the_pack_route_every_other_time_and_a_plain_line_keeps_its_map(self):
        line = "From Phoenix the water runs on to Tucson."
        a, b = 2.0, 150.0
        doc = doc_for([(a, line), (b, line)], [self._map("MAP_ROUTE_SAT_V1", [PHOENIX, TUCSON], at=a + 0.3),
                                                self._map("MAP_ROUTE_SAT_V1", [PHOENIX, TUCSON], at=b + 0.3)])
        dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"] if o.get("locations")], [p3.ROUTE, "MAP_ROUTE_SAT_V1"])
        doc = doc_for([(2.0, "Phoenix and Tucson are both growing fast.")],
                      [self._map("MAP_SPREAD_V1", [PHOENIX, TUCSON, FLAGSTAFF])])
        dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"] if o.get("locations")], ["MAP_SPREAD_V1"])

    def test_the_relook_re_resolves_their_places_and_counts_them(self):
        self.assertTrue(relook._is_map({"template": p3.ROUTE, "locations": [PHOENIX, TUCSON]}))
        self.assertFalse(relook._is_map({"template": p3.REGIONS, "items": [{"label": "Utah"}]}))
        line = "Phoenix just endured 31 straight days above 110 degrees."
        doc = doc_for([(2.0, line)])
        diff = relook.replan(doc, resolve=lambda *a, **k: [], check_images=False)
        self.assertEqual(relook._summary(diff)["addedPack3"], 1)


class Placed(unittest.TestCase):
    def test_the_cards_take_the_calm_side_the_glass_ones_never_the_panel_the_maps_left_alone(self):
        self.assertEqual(lookplace.KT_PACK3_MAPS, {"KT_ROUTE", "KT_STORM", "KT_TOTALS", "KT_REGIONS"})
        ovs = [{"template": t, "startFrame": 0, "durationInFrames": 90} for t in PACK]
        scenes = [{"startFrame": 0, "durationInFrames": 300, "media": {"type": "image", "url": "x", "focus": {"busy": 0.9}}}]
        lookplace.place(ovs, scenes, fetch=lambda url: None)
        panels = {o["template"] for o in ovs if o.get("backing") == "panel"}
        self.assertEqual(panels, {"KT_DELTA", "KT_STREAK"})
        self.assertFalse(any(o.get("zone") or o.get("backing") for o in ovs if o["template"] in lookplace.KT_PACK3_MAPS))
        self.assertEqual(lookplace._home("KT_RANKING", False), "right-panel")
        self.assertEqual(lookplace.MIRROR["right-panel"], "left-panel")


if __name__ == "__main__":
    unittest.main()
