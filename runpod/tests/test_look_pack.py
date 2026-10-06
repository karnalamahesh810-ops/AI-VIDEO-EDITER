"""
The look pack (2026-10-07, the owner: "build more interesting animations and overlays - best quality ones,
Premiere Pro / After Effects kind, perfect size"): twelve looks in the kinetic-type system
(remotion/src/components/lib/LibKtPack.tsx, LibKtPictures.tsx, LibKtMaps.tsx; scripts/library_looks_ktpack.json).

  - registered (family "ktp", template ids KT_*), the planner may pick each, each with its least time, its
    built-in sound, its editor sample, its motion class (the full-frame ones grow out of the footage);
  - drawn by the renderer, sized from the one type scale (nothing a viewer reads under 24 px at 1080p, the
    cards never a takeover), never the retired style (no outlined or yellow-filled words, no poster faces);
  - picked where the narration fits, with the line's own words: a pull quote for a quote with its speaker, a
    term card for a term the line defines, the trend line in turn with the premium graph, the chapter card in
    turn with the pack's own, the locator as the second map, a place tag for a place named again on footage of
    it, two places on their own pictures, then / now on a still, the evidence card over a weak clip, the arrow
    callout where vision found the thing, the level gauge for a reservoir's share after the first ring, and the
    milestones for three to five years said one after another - each spaced (src/lookpack.py Pace).
Offline: no network, no paid calls.
"""
import json
import os
import re
import unittest

from src import datalooks as dl
from src import lookpack, marks, templates, timeline, treatments
from src.transcribe import Segment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "remotion", "src", "components", "lib")
FPS = 30
PACK = ["KT_QUOTE", "KT_TERM", "KT_LEVEL", "KT_TREND", "KT_MILESTONES", "KT_POINTER", "KT_CHAPTER", "KT_EVIDENCE",
        "KT_THEN_NOW", "KT_TWO_PLACES", "KT_LOCATOR", "KT_PLACE"]
FILES = {"LibKtPack.tsx": ["kt-quote", "kt-term", "kt-level", "kt-trend", "kt-milestones", "kt-pointer", "kt-chapter"],
         "LibKtPictures.tsx": ["kt-evidence", "kt-then-now", "kt-two-places"],
         "LibKtMaps.tsx": ["kt-locator", "kt-place"]}
PLAIN = "Plain words about the river and the town continue here."
LAKE_MEAD = {"label": "Lake Mead, Nevada, United States", "lat": 36.145, "lon": -114.414}
LAS_VEGAS = {"label": "Las Vegas, Nevada, United States", "lat": 36.17, "lon": -115.14}
PHOENIX = {"label": "Phoenix, Arizona, United States", "lat": 33.448, "lon": -112.074}


def plan(texts, shots=None, kinds=None, seconds=6.0, sections=None):
    kinds = kinds or ["video"] * len(texts)
    shots = shots or [{"subject": ""} for _ in texts]
    segs = [Segment(text=t, start=i * seconds, end=(i + 1) * seconds) for i, t in enumerate(texts)]
    scenes = [{"id": f"s{i}", "startFrame": int(i * seconds * FPS), "durationInFrames": int(seconds * FPS),
               "media": {"type": k, "url": f"https://x/{i}.{'jpg' if k == 'image' else 'mp4'}"},
               "semanticMetadata": {"subject": (shots[i] or {}).get("subject", ""), **((shots[i] or {}).get("_meta") or {})},
               "transition": "none", "motion": "none", "effect": "none"} for i, k in enumerate(kinds)]
    brief = {"kind": "explainer", "hookBeats": [], "sections": sections or []}
    return treatments.plan(segs, shots, scenes, FPS, int(len(texts) * seconds * FPS), brief,
                           treatments.pack_for(brief, "documentary"), timeline._OVERLAY_SECONDS)


def used(out, tid):
    return [o for o in out["overlays"] if o.get("template") == tid]


def words_for(lines, per_word=0.32):
    out = []
    for t, line in lines:
        for tok in line.split(" "):
            if tok:
                out.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.02, 3)})
                t += per_word
    return out


class Registered(unittest.TestCase):
    def test_twelve_looks_the_planner_may_pick_with_their_least_time_sound_and_sample(self):
        for tid in PACK:
            t = templates.get(tid)
            self.assertTrue(t, tid)
            self.assertTrue(treatments.auto_ok(tid), tid)
            self.assertEqual(templates.family(t), "ktp", tid)
            self.assertEqual(t["defaults"]["variant"], lookpack.variant_of(tid), tid)
            least = float(t["defaults"].get("leastSeconds") or 0)
            self.assertGreaterEqual(least, 3.0, tid)
            self.assertGreaterEqual(float(t["defaults"]["duration"]), least, tid)
            self.assertGreaterEqual(treatments.animation_seconds(t), least, tid)
            self.assertTrue(t["defaults"]["sounds"], tid)                      # the sound is built in
            self.assertIsInstance(t["defaults"].get("sample"), dict, tid)      # the editor's preview content
        self.assertEqual(set(PACK), set(lookpack.IDS))

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

    def test_a_two_picture_look_left_with_one_picture_still_fills_its_moment(self):
        # a picture that does not load is dropped (motion/pictureGuard.tsx): the full-frame two-picture looks then
        # play the one left full frame with their words - never an empty moment over the dimmed footage
        with open(os.path.join(LIB, "LibKtPictures.tsx"), encoding="utf-8") as fh:
            src = fh.read()
        for look in ("const ThenNow: Look", "const TwoPlaces: Look"):
            body = src[src.index(look):]
            body = body[:body.index("\n};\n")]
            self.assertIn("pics.length === 1", body, look)
            self.assertIn("if (!pics.length) return null;", body, look)
            self.assertNotIn("pics.length < 2", body, look)

    def test_the_full_frame_ones_grow_out_of_the_footage(self):
        with open(os.path.join(ROOT, "remotion", "src", "components", "motion", "lookClasses.json"), encoding="utf-8") as fh:
            classes = json.load(fh)["looks"]
        self.assertEqual({t for t in PACK if classes.get(t) == "full"}, {"KT_LOCATOR", "KT_THEN_NOW", "KT_TWO_PLACES", "KT_CHAPTER"})
        self.assertEqual(classes["KT_POINTER"], "mark")
        self.assertEqual(classes["KT_PLACE"], "tag")
        self.assertTrue(all(t in classes for t in PACK))

    def test_sizes_from_the_one_scale_readable_on_a_phone_never_a_takeover(self):
        with open(os.path.join(LIB, "typeScale.json"), encoding="utf-8") as fh:
            pack = json.load(fh)["pack"]
        cap = 0.727                                            # Inter Tight's capitals (em)
        for role, v in pack.items():
            if "share" in v and role not in ("gauge", "miniMap"):
                self.assertGreaterEqual(v["share"] / cap * 1080, 24.0, role)     # never under 24 px at 1080p
        self.assertTrue(0.035 <= pack["quote"]["share"] <= 0.042)              # a quote at the statement size
        self.assertTrue(0.045 <= pack["chapterTitle"]["share"] <= 0.055)        # a chapter title, not a poster
        self.assertLessEqual(pack["gauge"]["share"], 0.32)
        self.assertLessEqual(pack["trendCard"]["w"], 0.4)
        self.assertLessEqual(pack["evidenceCard"]["w"], 0.4)

    def test_the_pack_places_itself_but_its_pull_quote_takes_the_calm_side_and_the_panel(self):
        from src import lookplace
        self.assertEqual(lookplace.KT_PACK_OWN_PLACE | {"KT_QUOTE"}, set(PACK))
        ovs = [{"template": t, "startFrame": 0, "durationInFrames": 90} for t in PACK]
        scenes = [{"startFrame": 0, "durationInFrames": 300, "media": {"type": "image", "url": "x", "focus": {"busy": 0.9}}}]
        lookplace.place(ovs, scenes, fetch=lambda url: None)
        self.assertEqual([o["template"] for o in ovs if o.get("backing") or o.get("zone")], ["KT_QUOTE"])

    def test_never_the_retired_style(self):
        for name in FILES:
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            for bad in ("WebkitTextStroke", "-webkit-text-stroke", "#FFD400", "ANTON", "Bebas", "Anton"):
                self.assertNotIn(bad, src, (name, bad))


class Picked(unittest.TestCase):
    def test_a_quote_with_its_speaker_is_a_pull_quote_with_its_words_underlined(self):
        out = plan(['"We have never seen the lake this low," said Maria Ortiz, a park ranger at Glen Canyon.', PLAIN, PLAIN])
        got = used(out, "KT_QUOTE")
        self.assertTrue(got, [o["template"] for o in out["overlays"]])
        self.assertEqual(got[0]["text"], "We have never seen the lake this low")
        self.assertEqual(got[0]["label"], "Maria Ortiz")
        self.assertIn(got[0]["highlight"].lower(), got[0]["text"].lower())
        # reported speech, or a quote nobody is named for: never a pull quote
        for line in ["Officials said the lake could drop another twenty feet by spring.",
                     '"It will not come back," the sign by the marina read.']:
            self.assertFalse(used(plan([line, PLAIN, PLAIN]), "KT_QUOTE"), line)

    def test_a_term_the_line_defines_gets_its_card_with_the_meaning_as_said(self):
        for line, meaning in [
            ("Engineers have a name for it: what they call dead pool - the level where water can no longer pass the dam.",
             "The level where water can no longer pass the dam"),
            ("The point where no water can pass the dam is what engineers call dead pool.",
             "The point where no water can pass the dam")]:
            got = used(plan([line, PLAIN, PLAIN]), "KT_TERM")
            self.assertTrue(got, line)
            self.assertEqual((got[0]["text"], got[0]["subtitle"]), ("Dead pool", meaning))
        self.assertIsNone(lookpack.term_props("They called it the Compact.", "the Compact"))

    def test_series_take_the_premium_graph_and_the_trend_line_in_turn(self):
        s1 = "Lake Powell stood at 3,700 feet in 1980, 3,555 feet in 2005 and 3,522 feet in 2022."
        s2 = "Lake Mead held 1,200 feet in 1983, 1,080 feet in 2010 and 1,040 feet in 2022."
        out = plan([s1] + [PLAIN] * 9 + [s2] + [PLAIN] * 2)
        ids = [o["template"] for o in out["overlays"]]
        self.assertEqual([x for x in ids if x in ("LIB_PR_GRAPH_BUILD", "KT_TREND")], ["LIB_PR_GRAPH_BUILD", "KT_TREND"])
        trend = used(out, "KT_TREND")[0]
        self.assertEqual([it["label"] for it in trend["items"]], ["1983", "2010", "2022"])
        self.assertGreaterEqual(trend["durationInFrames"] / FPS, 5.0 - 1 / FPS)
        self.assertFalse(lookpack.trend_fits([{"label": "Nevada", "value": 1}, {"label": "Utah", "value": 2},
                                              {"label": "Arizona", "value": 3}]))

    def test_chapters_take_the_packs_card_and_the_new_card_in_turn_numbered(self):
        shots = [{"subject": "Lake Mead", "overlay": {"type": "chapter", "text": "The Bathtub Ring"}}] + [{"subject": "x"}] * 4 \
            + [{"subject": "Lake Mead", "overlay": {"type": "chapter", "text": "The Long Drought"}}] + [{"subject": "x"}] * 4
        out = plan(["A new chapter begins."] + [PLAIN] * 4 + ["Another chapter begins."] + [PLAIN] * 4, shots,
                   seconds=8.0, sections=[{"from": 0, "to": 4}, {"from": 5, "to": 9}])
        chapters = [o for o in out["overlays"] if (templates.get(o["template"]) or {}).get("category") == "HEADLINES"]
        self.assertEqual([o["template"] for o in chapters], [treatments.pack_for({}, "documentary")["chapter"], "KT_CHAPTER"])
        self.assertEqual((chapters[1]["text"], int(chapters[1]["value"]), chapters[1]["label"]), ("The Long Drought", 2, "Chapter"))

    def test_the_second_map_is_the_locator_and_a_place_named_again_soon_is_its_tag(self):
        pack = treatments.pack_for({"kind": "explainer"})
        one = {"type": "map", "locations": [LAKE_MEAD]}
        self.assertNotIn("KT_LOCATOR", treatments._map_ids(one, pack, n_maps=0)[0])
        self.assertIn("KT_LOCATOR", treatments._map_ids(one, pack, n_maps=1)[0])
        self.assertNotIn("KT_LOCATOR", treatments._map_ids(one, pack, n_maps=2)[0])
        shots = [{"subject": "Lake Mead", "overlay": {"type": "map", "locations": [LAKE_MEAD]}}, {"subject": "x"},
                 {"subject": "Las Vegas Strip", "overlay": {"type": "map", "locations": [LAS_VEGAS]}}] \
            + [{"subject": "x"}] * 17 + [{"subject": "Lake Mead", "overlay": {"type": "map", "locations": [LAKE_MEAD]}}]
        out = plan(["Lake Mead sits behind Hoover Dam.", PLAIN, "Las Vegas takes its water from the lake."] + [PLAIN] * 17
                   + ["Back at Lake Mead the water keeps falling."], shots, seconds=8.0)
        ids = [o["template"] for o in out["overlays"] if o.get("locations")]
        self.assertEqual(ids[1:], ["KT_PLACE", "KT_LOCATOR"], ids)
        tag = used(out, "KT_PLACE")[0]
        self.assertEqual((tag["text"], tag["locations"][0]["label"]), ("Las Vegas", LAS_VEGAS["label"]))
        # a place named on footage that does not show it: never its tag
        self.assertFalse(lookpack.shows_place("Las Vegas", "Hoover Dam spillway"))

    def test_two_places_named_together_on_their_own_pictures(self):
        shots = [{"subject": "Las Vegas", "overlay": {"type": "map", "locations": [LAS_VEGAS, PHOENIX]}},
                 {"subject": "Phoenix"}, {"subject": "x"}]
        out = plan(["Las Vegas and Phoenix both drink from the same river.", "Phoenix keeps growing too.", PLAIN], shots,
                   kinds=["image", "image", "video"])
        got = used(out, "KT_TWO_PLACES")
        self.assertTrue(got, [o["template"] for o in out["overlays"]])
        self.assertEqual(got[0]["mediaFrom"], ["s0", "s1"])
        self.assertEqual([x["label"] for x in got[0]["locations"]], [LAS_VEGAS["label"], PHOENIX["label"]])
        # the pictures in the other order follow the places
        shots[0]["subject"], shots[1]["subject"] = "Phoenix", "Las Vegas"
        got = used(plan(["Las Vegas and Phoenix both drink from the same river.", "And grow.", PLAIN], shots,
                        kinds=["image", "image", "video"]), "KT_TWO_PLACES")
        self.assertEqual([x["label"] for x in got[0]["locations"]], [PHOENIX["label"], LAS_VEGAS["label"]])

    def test_then_and_now_said_over_a_still_and_the_evidence_card_over_a_weak_clip(self):
        out = plan(["The marina used to sit right here; today it is dry ground.", PLAIN, PLAIN],
                   [{"subject": "Lake Mead marina", "subjectType": "place"}, {"subject": "x"}, {"subject": "x"}],
                   kinds=["image", "video", "video"])
        self.assertTrue(used(out, "KT_THEN_NOW"), [o["template"] for o in out["overlays"]])
        self.assertEqual(treatments.look_slots(templates.get("KT_THEN_NOW")), (2, 2))
        # a weak clip of a place named: the photo window, then the evidence card the next time
        weak = {"subjectType": "landmark", "_meta": {"relevanceScore": 0.2}}
        out = plan(["The spillway at Glen Canyon Dam was carved straight through the rock.", PLAIN, PLAIN, PLAIN,
                    "The intake towers at Hoover Dam stand in the lake.", PLAIN],
                   [{"subject": "Glen Canyon Dam", **weak}, {"subject": "x"}, {"subject": "x"}, {"subject": "x"},
                    {"subject": "Hoover Dam", **weak}, {"subject": "x"}])
        self.assertEqual([o["template"] for o in out["overlays"]], ["PHOTO_PIP_V1", "KT_EVIDENCE"])
        got = used(out, "KT_EVIDENCE")
        self.assertEqual(got[0]["text"], "Hoover Dam")
        self.assertTrue(treatments._web_photo_look(got[0], templates.get("KT_EVIDENCE")))   # a photo searched for it

    def test_the_arrow_callout_takes_the_arrows_turn_where_vision_found_the_thing(self):
        self.assertEqual(marks._pick_mark({"x": 0.5, "y": 0.5, "r": 0.2}, 0), "KT_POINTER")
        self.assertEqual(marks._pick_mark({"x": 0.5, "y": 0.5, "r": 0.2}, 1), "LIB_VM_CIRCLE")
        self.assertEqual(marks._pick_mark({"x": 0.5, "y": 0.5, "w": 0.6, "h": 0.1}, 0), "LIB_VM_BOX")
        with templates.only({"LIB_VM_ARROW", "LIB_VM_CIRCLE", "LIB_VM_BOX"}):
            self.assertEqual(marks._pick_mark({"x": 0.5, "y": 0.5, "r": 0.2}, 0), "LIB_VM_ARROW")


class DataLooks(unittest.TestCase):
    def test_a_reservoirs_share_fills_the_gauge_after_the_first_ring(self):
        words = words_for([(0.0, "Lake Mead is 27 percent full."), (80.0, "Lake Powell sits at 22 percent of its capacity."),
                           (160.0, "Farms use 70 percent of the river's water."),
                           (200.0, "By spring the lake could be 20 percent full.")])
        out, _log = dl.plan(words, FPS)
        got = [(o["template"], o["value"]) for o in out]
        self.assertEqual(got, [(dl.KT_PERCENT, 27), (dl.KT_LEVEL, 22), (dl.KT_PERCENT, 70), (dl.KT_LEVEL, 20)])
        self.assertIn(dl.KT_LEVEL, dl.KT_DATA)
        self.assertEqual(dl.family_of({"template": dl.KT_LEVEL}), "ring")

    def test_the_gauge_at_most_once_a_minute(self):
        words = words_for([(0.0, "Lake Mead is 27 percent full."), (30.0, "Lake Powell is 22 percent full."),
                           (60.0, "Flaming Gorge is 80 percent full.")])
        out, _log = dl.plan(words, FPS)
        self.assertEqual([o["template"] for o in out].count(dl.KT_LEVEL), 1)

    def test_three_to_five_years_one_after_another_are_one_strip_each_lighting_on_its_year(self):
        line = ("In 1963, Glen Canyon Dam closed its gates. By 1980 the lake was full. "
                "In 2002 the long drought began, and in 2022 it hit a record low.")
        words = words_for([(0.0, line)])
        out, log = dl.plan(words, FPS)
        self.assertEqual([o["template"] for o in out], [dl.KT_MILESTONES])
        ms = out[0]
        self.assertEqual([it["label"] for it in ms["items"]], ["1963", "1980", "2002", "2022"])
        self.assertEqual(ms["items"][0]["text"], "Glen Canyon Dam closed")
        self.assertEqual(ms["items"][1]["text"], "The lake was full")
        ats = [it.get("at", 0.0) for it in ms["items"]]
        self.assertEqual(ats, sorted(ats))
        # its least time covers the last year's landing and a hold after it
        self.assertGreaterEqual(dl.min_seconds(ms), ats[-1] + dl.DATE_LEG[dl.KT_MILESTONES] + dl.MIN_HOLD["date"])
        self.assertEqual(log[0]["kind"], "milestones")
        # two years are the date family's timeline, never the strip
        out, _ = dl.plan(words_for([(0.0, "In 1963 the gates closed. By 1980 the lake was full.")]), FPS)
        self.assertNotIn(dl.KT_MILESTONES, [o["template"] for o in out])

    def test_the_lane_keeps_the_strip_whole_and_lights_its_years_from_where_it_starts(self):
        line = ("In 1963, Glen Canyon Dam closed its gates. By 1980 the lake was full. "
                "In 2002 the long drought began, and in 2022 it hit a record low.")
        words = words_for([(1.0, line)])
        total = int(30 * FPS)
        doc = {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": total, "overlays": [], "sfx": [],
               "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": total, "text": "", "words": words,
                           "media": {"type": "video", "url": "https://x/0.mp4"}}]}
        report = dl.finish(doc)
        ms = [o for o in doc["overlays"] if o["template"] == dl.KT_MILESTONES]
        self.assertEqual(len(ms), 1, report["added"])
        o = ms[0]
        self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS))
        start = o["startFrame"] / FPS
        said = [w["start"] for w in words if w["text"].strip(",.") in ("1980", "2002", "2022")]
        for it, at in zip(o["items"][1:], said):
            self.assertAlmostEqual(start + it["at"], at, delta=0.12)

    def test_a_brand_kit_without_them_gets_the_ring_and_the_timeline(self):
        self.assertEqual(dl._alternate({"template": dl.KT_LEVEL, "value": 27, "suffix": "%"})["template"], dl.KT_PERCENT)
        alt = dl._alternate({"template": dl.KT_MILESTONES, "items": [{"label": "1963"}, {"label": "1980"},
                                                                       {"label": "2002"}, {"label": "2022"}]})
        self.assertEqual((alt["template"], alt["value"], [it["value"] for it in alt["items"]]),
                         (dl.KT_DATE_LINE, 2022, [1980, 2002, 2022]))


class Pace(unittest.TestCase):
    def test_spaced_and_never_crowded(self):
        p = lookpack.Pace()
        self.assertTrue(p.allows(lookpack.QUOTE, 10.0))
        p.note(lookpack.QUOTE, 10.0)
        self.assertFalse(p.allows(lookpack.TERM, 25.0))                     # within PACK_GAP of another
        self.assertTrue(p.allows(lookpack.TERM, 31.0))
        p.note(lookpack.TERM, 31.0)
        self.assertFalse(p.allows(lookpack.LOCATOR, 55.0))                  # a third in one minute
        self.assertFalse(p.allows(lookpack.QUOTE, 50.0))                    # the same look within its EVERY
        self.assertTrue(p.allows(lookpack.QUOTE, 95.0))
        self.assertTrue(p.allows("KT_NUMBER", 11.0))                         # nothing else is held back

    def test_a_long_video_of_quotes_never_shows_the_pull_quote_back_to_back(self):
        line = '"We have never seen the lake this low," said Maria Ortiz.'
        out = plan([line, PLAIN] * 20, seconds=8.0)
        starts = [o["startFrame"] / FPS for o in used(out, "KT_QUOTE")]
        self.assertTrue(starts)
        for a, b in zip(starts, starts[1:]):
            self.assertGreaterEqual(b - a, treatments.LOOK_GAP - 0.01)


if __name__ == "__main__":
    unittest.main()
