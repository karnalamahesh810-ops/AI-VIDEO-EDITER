"""
The premium looks (remotion/src/components/lib/LibPremium.tsx, family "pr-", 2026-10-05): a document
spotlight, a photo focus, a graph that draws in, a map path between two places and a number reveal.

  - registered (scripts/library_looks_pr.json -> registry.json), the planner may pick them, each with
    its least time on screen; the renderer draws every one of them;
  - the planner picks each where its line asks for it (a cited document, a named or pointed-at still,
    a series of figures, a route between two places, a figure with words after it), with the line's
    own words, and never two of them within PREMIUM_GAP seconds.
"""
import importlib.util
import json
import os
import re
import unittest

from src import marks, templates, timeline, treatments
from src.transcribe import Segment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "remotion", "src", "components", "lib")
FPS = 30
PR = ["LIB_PR_DOC_SPOTLIGHT", "LIB_PR_PHOTO_FOCUS", "LIB_PR_GRAPH_BUILD", "LIB_PR_MAP_PATH", "LIB_PR_NUMBER_REVEAL"]
PLAIN = "Plain words about the river and the town continue here."


def plan(texts, shots=None, kinds=None, seconds=6.0):
    kinds = kinds or ["video"] * len(texts)
    shots = shots or [{"subject": ""} for _ in texts]
    segs = [Segment(text=t, start=i * seconds, end=(i + 1) * seconds) for i, t in enumerate(texts)]
    scenes = [{"id": f"s{i}", "startFrame": int(i * seconds * FPS), "durationInFrames": int(seconds * FPS),
               "media": {"type": k, "url": f"https://x/{i}.{'jpg' if k == 'image' else 'mp4'}"},
               "transition": "none", "motion": "none", "effect": "none"} for i, k in enumerate(kinds)]
    brief = {"kind": "explainer", "hookBeats": [], "sections": []}
    return treatments.plan(segs, shots, scenes, FPS, int(len(texts) * seconds * FPS), brief,
                           treatments.pack_for(brief, "documentary"), timeline._OVERLAY_SECONDS)


def used(out, tid):
    return [o for o in out["overlays"] if o.get("template") == tid]


class Registered(unittest.TestCase):
    def test_five_looks_the_planner_may_pick_with_their_least_time(self):
        for tid in PR:
            t = templates.get(tid)
            self.assertTrue(t, tid)
            self.assertTrue(treatments.auto_ok(tid), tid)
            self.assertEqual(templates.family(t), "pr", tid)
            least = float((t.get("defaults") or {}).get("leastSeconds") or 0)
            self.assertGreater(least, 3.0, tid)
            self.assertGreaterEqual(treatments.animation_seconds(t), least, tid)
            fam = treatments.look_family(t)
            if fam in treatments.FAMILY_LEAST:
                self.assertGreaterEqual(treatments.animation_seconds(t), treatments.FAMILY_LEAST[fam], tid)

    def test_the_renderer_draws_each_one(self):
        with open(os.path.join(LIB, "LibPremium.tsx"), encoding="utf-8") as fh:
            src = fh.read()
        block = src[src.index("export const LOOKS"):]
        drawn = set(re.findall(r'"(pr-[a-z-]+)":', block))
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            picked = set(re.findall(r'"(pr-[a-z-]+)"', fh.read()))
        want = {(templates.get(t).get("defaults") or {}).get("variant") for t in PR}
        self.assertEqual(drawn, want)
        self.assertEqual(picked, want)

    def test_the_registry_on_disk_is_the_build(self):
        spec = importlib.util.spec_from_file_location("build_registry", os.path.join(ROOT, "scripts", "build_registry.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        built = json.loads(json.dumps(mod.build(), ensure_ascii=False))
        with open(mod.OUT, encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertEqual({t["id"]: t for t in built["templates"]}, {t["id"]: t for t in disk["templates"]})

    def test_the_photo_focus_gets_its_spot_from_vision(self):
        self.assertIn("LIB_PR_PHOTO_FOCUS", marks.DETAIL_PHOTO)


class Picked(unittest.TestCase):
    def test_a_cited_document_is_spotlit_with_its_claim_circled(self):
        line = "A new report found that Lake Powell fell to its lowest level since it first filled."
        out = plan([line, PLAIN, PLAIN])
        got = used(out, "LIB_PR_DOC_SPOTLIGHT")
        self.assertTrue(got, [o["template"] for o in out["overlays"]])
        ov = got[0]
        self.assertEqual(ov.get("highlight"), "lowest level since it first filled")
        self.assertIn(ov["text"].lower(), line.lower())
        self.assertGreaterEqual(ov["durationInFrames"] / FPS, 5.0 - 1 / FPS)

    def test_a_named_still_gets_the_photo_focus_with_its_name(self):
        texts = ["The spillway tunnels of Glen Canyon Dam were carved through the canyon wall.", PLAIN, PLAIN]
        out = plan(texts, shots=[{"subject": "Glen Canyon Dam spillway (1983)", "subjectType": "place"},
                                 {"subject": "x"}, {"subject": "x"}], kinds=["image", "video", "video"])
        got = used(out, "LIB_PR_PHOTO_FOCUS")
        self.assertTrue(got, [o["template"] for o in out["overlays"]])
        self.assertEqual(got[0].get("text"), "Glen Canyon Dam")
        self.assertGreaterEqual(got[0]["durationInFrames"] / FPS, 4.5 - 1 / FPS)

    def test_a_still_the_line_does_not_name_or_point_at_gets_no_photo_look(self):
        texts = ["Plain words about the river here.", PLAIN, PLAIN]
        out = plan(texts, shots=[{"subject": "Hoover Dam", "subjectType": "place"}, {"subject": "x"}, {"subject": "x"}],
                   kinds=["image", "video", "video"])
        cats = [(templates.get(o["template"]) or {}).get("category") for o in out["overlays"]]
        self.assertNotIn("IMAGES", cats)

    def test_a_series_draws_as_a_graph(self):
        line = "Lake Powell stood at 3,700 feet in 1980, 3,555 feet in 2005 and 3,522 feet in 2022."
        out = plan([line, PLAIN, PLAIN])
        got = used(out, "LIB_PR_GRAPH_BUILD")
        self.assertTrue(got, [o["template"] for o in out["overlays"]])
        self.assertEqual([it["label"] for it in got[0]["items"]], ["1980", "2005", "2022"])

    def test_a_route_between_two_places_may_take_the_map_path(self):
        pack = treatments.pack_for({"kind": "explainer"})
        hint = {"type": "map", "variant": "route-dark", "locations": [
            {"label": "Page, Arizona", "lat": 36.91, "lon": -111.46}, {"label": "Las Vegas, Nevada", "lat": 36.17, "lon": -115.14}]}
        ids, _ = treatments._map_ids(hint, pack)
        self.assertIn("LIB_PR_MAP_PATH", ids)
        ids, _ = treatments._map_ids({**hint, "variant": ""}, pack)
        self.assertIn("LIB_PR_MAP_PATH", ids)

    def test_a_figure_with_words_after_it_is_revealed_with_them(self):
        props = {"value": 3516.0, "suffix": "FT", "text": "LAKE POWELL"}
        got = treatments._premium_props({"cue": "big-number"}, "Lake Powell dropped to 3516 feet above sea level.", props)
        self.assertEqual(got, ("LIB_PR_NUMBER_REVEAL", {"subtitle": "above sea level"}))
        # a clause the line does not finish, or the label said again: no line under the number
        self.assertIsNone(treatments._premium_props(
            {"cue": "big-number"}, "And it now sits less than 30 feet above the point where Glen Canyon Dam",
            {"value": 30.0, "suffix": "FT"}))
        self.assertIsNone(treatments._premium_props(
            {"cue": "count"}, "28 people died.", {"value": 28.0, "text": "PEOPLE DIED"}))

    def test_two_premium_looks_never_come_close_together(self):
        doc = "A new report found that Lake Powell fell to its lowest level since it first filled."
        texts = [doc, "The spillway tunnels of Glen Canyon Dam were carved through the canyon wall.",
                 "Records show the dam's operators cut the releases to protect the turbines."] + [PLAIN] * 8
        shots = [{"subject": "x"}, {"subject": "Glen Canyon Dam", "subjectType": "place"}] + [{"subject": "x"}] * 9
        kinds = ["video", "image"] + ["video"] * 9
        out = plan(texts, shots, kinds, seconds=8.0)
        starts = sorted(o["startFrame"] / FPS for o in out["overlays"] if o.get("template") in PR)
        self.assertTrue(starts)
        for a, b in zip(starts, starts[1:]):
            self.assertGreaterEqual(b - a, treatments.PREMIUM_GAP - 0.01, starts)


if __name__ == "__main__":
    unittest.main()
