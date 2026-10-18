"""The Smart Editor: design compiler, timing on the word, freshness, fail-safe (offline; no paid call)."""
import itertools
import json
import os
import re
import unittest
from unittest import mock

from src import motionspec, smart_editor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scene(i, start, text, fps=30, media=None):
    words, t = [], start
    for w in text.split():
        words.append({"text": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
        t += 0.35
    return {"id": f"s{i}", "startFrame": int(start * fps), "durationInFrames": int((t - start + 0.5) * fps),
            "text": text, "words": words, "media": media or {"type": "video", "url": "", "contentDescription": "a tower"}}


def _doc(fps=30):
    scenes, t = [], 0.0
    lines = ["It rises 867 feet above the pine forest of Wyoming.",
             "On the summit a small sensor sits bolted to the rock.",
             "The trace never goes flat, it hums back and forth.",
             "Go back to September 24th 1906 when Roosevelt signed it.",
             "Nobody could explain why the layers tilt the wrong way.",
             "So what is this thing really and how did it get here?"]
    for i, ln in enumerate(lines):
        s = _scene(i, t, ln, fps)
        scenes.append(s)
        t = (s["startFrame"] + s["durationInFrames"]) / fps
    total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
    return {"fps": fps, "width": 1920, "height": 1080, "durationInFrames": total, "scenes": scenes,
            "overlays": [{"type": "motion", "variant": "kt-keyword", "template": "KT_KEYWORD", "text": "flat",
                          "startFrame": scenes[2]["startFrame"], "durationInFrames": 90},
                         {"type": "map", "variant": "satellite", "text": "Wyoming", "locations": [{"label": "W"}],
                          "startFrame": scenes[5]["startFrame"] + 30, "durationInFrames": 60}],
            "sfx": [], "captions": {"enabled": False, "accent": "#EF4444"}, "meta": {"voiceLufs": -20}}


class CompileTests(unittest.TestCase):
    def test_every_move_unit_layout_compiles_clean_and_safe(self):
        ctx = {"accentRole": "gold", "aspect": 16 / 9}
        n = 0
        for move, unit, layout, kind in itertools.product(motionspec.MOVES, motionspec.UNITS, motionspec.LAYOUTS,
                                                          ("statement", "number", "date", "list", "quote")):
            d = {"kind": kind, "text": "The trace never goes flat", "sub": "logging since 2004", "value": 867,
                 "layout": layout, "anim": {"move": move, "unit": unit, "speed": "snappy"},
                 "accent": ["underline-draw", "bar-left", "kicker-tag"], "depth": {"tilt": 8, "parallax": 0.6},
                 "camera": "drift"}
            spec = motionspec.clean_spec(motionspec.compile_design(d, {"dur": 3.0}, ctx), 3.0)
            self.assertIsNotNone(spec, (move, unit, layout, kind))
            for L in spec["layers"]:
                if L["kind"] in ("text", "counter"):
                    self.assertGreaterEqual(L["size"], motionspec.MIN_SUB - 1e-9)
                    self.assertTrue(0.05 <= L["x"] <= 0.95 and 0.08 <= L["y"] <= 0.9, L)
                    self.assertNotIn("stroke", L)                      # never an outlined poster word
            json.dumps(spec)
            n += 1
        self.assertGreaterEqual(n, 1800)

    def test_mark_and_push_keep_the_point_still(self):
        d = {"kind": "spot", "text": "SENSOR", "highlight": {"thing": "sensor", "mark": "circle"},
             "camera": "push-to-point"}
        spec = motionspec.compile_design(d, {"dur": 3.0, "point": (0.7, 0.3, 0.05, 0.1, 0.12)}, {"aspect": 16 / 9})
        cam = spec["camera"]["keys"]
        s = cam["scale"][1][1]
        self.assertAlmostEqual(cam["x"][1][1], round((s - 1) * 0.2, 4))
        self.assertTrue(any(L["kind"] == "ellipse" and L["x"] == 0.7 for L in spec["layers"]))
        text = [L for L in spec["layers"] if L["kind"] == "text"][0]
        self.assertLess(text["x"], 0.5)                                # words away from the point

    def test_spoken_sync_feeds_word_times(self):
        d = {"text": "never goes flat", "anim": {"move": "rise", "unit": "word", "sync": "spoken"}}
        spec = motionspec.compile_design(d, {"dur": 3, "at": [0.0, 0.4]}, {})
        a = spec["layers"][0]["animator"]
        self.assertEqual(len(a["at"]), 3)
        self.assertEqual(a["at"][:2], [0.0, 0.4])

    def test_year_counts_without_commas(self):
        spec = motionspec.compile_design({"kind": "date", "text": "ANTIQUITIES ACT", "value": 1906}, {"dur": 3}, {})
        c = [L for L in spec["layers"] if L["kind"] == "counter"][0]
        self.assertFalse(c["group"])
        self.assertLess(c["valueFrom"], 1906)

    def test_bad_specs_drop(self):
        self.assertIsNone(motionspec.clean_spec({"layers": [{"kind": "bogus"}]}, 2))
        self.assertIsNone(motionspec.clean_spec("x", 2))
        self.assertIsNone(motionspec.clean_spec({"layers": [{"kind": "image", "src": "file:///etc/passwd"}]}, 2))


class TimingTests(unittest.TestCase):
    def test_trigger_on_word_and_next_beats_only(self):
        doc = _doc()
        hit = smart_editor.find_trigger(doc["scenes"], 0, "867 feet")
        self.assertEqual(hit[0], doc["scenes"][0]["words"][2]["start"])
        self.assertIsNotNone(smart_editor.find_trigger(doc["scenes"], 0, "sensor"))     # next beat
        self.assertIsNone(smart_editor.find_trigger(doc["scenes"], 0, "Roosevelt"))     # 3 beats on
        self.assertIsNone(smart_editor.find_trigger(doc["scenes"], 0, "volcano"))


def _director_answer(*_a, **_k):
    return {"_model": "test", "graphics": [
        {"beat": 0, "at": "867 feet", "kind": "number", "text": "FEET ABOVE THE FOREST", "value": 867,
         "layout": "left-third", "anim": {"move": "flip-x", "unit": "char"}, "sfx": "whoosh-soft",
         "highlight": {"thing": "the tower", "mark": "circle"}, "camera": "push-to-point"},
        {"beat": 1, "at": "sensor", "kind": "statement", "text": "A sensor on the summit",
         "layout": "left-third", "anim": {"move": "flip-x", "unit": "char"}},      # same anim + layout: varied
        {"beat": 2, "at": "never goes flat", "kind": "statement", "text": "never goes flat",
         "anim": {"move": "rise", "unit": "word", "sync": "spoken"}, "layout": "center"},
        {"beat": 3, "at": "1906", "kind": "date", "value": 1906, "text": "Roosevelt signed it", "layout": "right-third"},
        {"beat": 5, "at": "thing", "kind": "statement", "text": "Proclamation 658 signed into law"},
        {"beat": 4, "at": "elephant", "text": "explain the layers"},                              # not spoken: out
    ], "keep": [], "transitions": [{"beat": 3, "t": "light-sweep"}, {"beat": 4, "t": "nonsense"}]}


class EditTests(unittest.TestCase):
    def test_edit_end_to_end_offline(self):
        doc = _doc()
        with mock.patch.object(smart_editor, "_direct_chunk", side_effect=_director_answer), \
                mock.patch.object(smart_editor, "_anchor", return_value={"x": 0.6, "y": 0.4, "r": 0.1, "w": 0.2, "h": 0.3}):
            rep = smart_editor.edit(doc, {"title": "t"}, critic=False)
        self.assertNotIn("error", rep)
        smart = [o for o in doc["overlays"] if o.get("variant") == "smart-spec"]
        self.assertEqual(len(smart), 4)
        self.assertEqual(rep["rejected"].get("word not said nearby"), 1)
        self.assertEqual(rep["rejected"].get("words or figures the narration does not say"), 1)
        # the words-only planner look is replaced, the map (facts) stays
        self.assertFalse(any(o.get("variant") == "kt-keyword" for o in doc["overlays"]))
        self.assertTrue(any(o.get("type") == "map" for o in doc["overlays"]))
        # never early: each starts on its word
        w = doc["scenes"][0]["words"][2]
        self.assertEqual(smart[0]["startFrame"], round(w["start"] * doc["fps"]))
        # one at a time
        ends = [(o["startFrame"], o["startFrame"] + o["durationInFrames"]) for o in doc["overlays"]]
        for (a0, a1), (b0, b1) in zip(ends, ends[1:]):
            self.assertLessEqual(a1, b0)
        # the repeated text animation was varied
        anims = [o["smart"]["sig"]["anim"] for o in smart]
        self.assertEqual(len(anims), len(set(anims)))
        self.assertEqual(doc["scenes"][3]["transition"], "light-sweep")
        self.assertTrue(any(r["kind"] == "smart" and r["name"] == "whoosh-soft" for r in doc["sfx"]))
        self.assertIn("camera", smart[0]["spec"])

    def test_failure_keeps_the_plan(self):
        doc = _doc()
        before = json.dumps(doc["overlays"])
        with mock.patch.object(smart_editor, "_direct_chunk", side_effect=RuntimeError("boom")):
            rep = smart_editor.edit(doc, {}, critic=False)
        self.assertIn("error", rep)
        self.assertEqual(json.dumps(doc["overlays"]), before)

    def test_flag_default_off(self):
        self.assertFalse(smart_editor.enabled({}) and not os.getenv("SMART_EDITOR"))
        self.assertTrue(smart_editor.enabled({"smart_editor": True}))


class RendererParityTests(unittest.TestCase):
    def test_python_vocabulary_matches_the_renderer(self):
        with open(os.path.join(ROOT, "remotion", "src", "components", "smart", "specMath.ts"), encoding="utf-8") as fh:
            ts = fh.read()
        for kind in motionspec._LAYER_KINDS:
            self.assertIn(f'"{kind}"', ts)
        for e in motionspec.EASES:
            self.assertRegex(ts, rf"\b{e}\b")
        for f in motionspec.FONTS:
            self.assertIn(f'"{f}"', ts)
        with open(os.path.join(ROOT, "remotion", "src", "Main.tsx"), encoding="utf-8") as fh:
            main = fh.read()
        self.assertIn('raw.variant === "smart-spec"', main)
        self.assertIn("<CameraFx", main)


if __name__ == "__main__":
    unittest.main()


class BrandKitTests(unittest.TestCase):
    def test_kits_match_the_renderer(self):
        from src import brandkits
        with open(os.path.join(ROOT, "remotion", "src", "components", "smart", "brandKits.ts"), encoding="utf-8") as fh:
            ts = fh.read()
        for kid, kit in brandkits.KITS.items():
            self.assertIn(f"  {kid}: {{", ts)
            for name, hexv in kit["colors"].items():
                self.assertRegex(ts, rf"{name}: \"{hexv}\"", (kid, name))
            for name, font in kit["fonts"].items():
                self.assertIn(f'{name}: "{font}"', ts)

    def test_kit_specs_use_tokens_and_compile(self):
        ctx = {"kit": "royal", "aspect": 16 / 9}
        tower = {"shapes": [{"t": "rect", "x": 0.1, "y": 0.9, "w": 0.8, "h": 0.1, "c": "$secondary"},
                            {"t": "poly", "p": [[0.3, 0.9], [0.4, 0.2], [0.6, 0.2], [0.7, 0.9]], "c": "$muted"}]}
        for d, pt in (({"kind": "card", "text": "Devils Tower", "value": 867, "unit": "feet", "measure": True,
                        "illustration": tower}, None),
                      ({"kind": "waffle", "value": 37, "text": "of climbs"}, None),
                      ({"kind": "tiles", "items": ["USGS", "NPS"], "text": "who"}, None),
                      ({"kind": "measure", "value": 867, "unit": "ft"}, (0.5, 0.5, 0.2, 0.2, 0.5)),
                      ({"kind": "statement", "text": "never goes flat", "accent": ["kicker-tag"], "sub": "x"}, None)):
            spec = motionspec.clean_spec(motionspec.compile_design(d, {"dur": 3, "point": pt}, ctx), 3)
            self.assertIsNotNone(spec, d["kind"])
            self.assertEqual(spec["kit"], "royal")
            blob = json.dumps(spec)
            self.assertIn("$", blob)
            self.assertNotIn("#f2c14e", blob)                         # no off-kit accent
        spec = motionspec.compile_design({"kind": "card", "text": "T", "illustration": tower}, {"dur": 3}, ctx)
        shape = [L for L in spec["layers"] if L["kind"] == "shape"][0]
        xs = [p[0] for q in shape["shapes"] if q["t"] == "poly" for p in q["p"]]
        self.assertAlmostEqual(min(xs), 0.0 + 0.25, places=2)          # fitted to the drawing's own extent

    def test_choose(self):
        from src import brandkits
        self.assertEqual(brandkits.choose({"smart_kit": "royal"}), "royal")
        self.assertEqual(brandkits.choose({}, None, "news"), "bulletin")
        self.assertEqual(brandkits.choose({}, None, ""), "noir")

    def test_invented_words_are_refused(self):
        doc = _doc()
        self.assertIsNone(smart_editor.ground_design({"text": "Seismic sensor"}, doc["scenes"], 1))
        self.assertIsNotNone(smart_editor.ground_design({"text": "summit sensor"}, doc["scenes"], 1))
        g = smart_editor.ground_design({"kind": "number", "text": "feet tall", "value": 867}, doc["scenes"], 0)
        self.assertEqual(g["value"], 867)
        self.assertIsNone(smart_editor.ground_design({"kind": "number", "text": "feet", "value": 900}, doc["scenes"], 0))


class RestoreTests(unittest.TestCase):
    def test_figures_and_pictures_come_back_trimmed_where_free(self):
        doc = _doc()
        s3 = doc["scenes"][3]                                         # "Go back to September 24th 1906 when ..."
        yr = {"type": "motion", "variant": "kt-year", "template": "KT_YEAR", "text": "1906",
              "startFrame": s3["startFrame"], "durationInFrames": 150}
        dossier = {"type": "motion", "variant": "pf-dossier", "template": "LIB_PF_DOSSIER", "text": "Roosevelt",
                   "startFrame": doc["scenes"][1]["startFrame"] + 3, "durationInFrames": 120}
        word = {"type": "motion", "variant": "kt-keyword", "template": "KT_KEYWORD", "text": "layers",
                "startFrame": doc["scenes"][4]["startFrame"], "durationInFrames": 90}
        doc["overlays"] = [yr, dossier, word]
        late = doc["scenes"][3]["words"][-2]                          # "signed": 2.1 s after the year look starts

        def answer(rows, looks, story, recent, hook, budget):
            return {"graphics": [{"beat": 3, "at": "signed", "kind": "statement", "text": "Roosevelt signed it"},
                                 {"beat": 1, "at": "summit", "kind": "label", "text": "summit sensor"}],
                    "keep": [], "transitions": []}
        with mock.patch.object(smart_editor, "_direct_chunk", side_effect=answer):
            rep = smart_editor.edit(doc, {"title": "t"}, critic=False)
        self.assertNotIn("error", rep)
        ovs = doc["overlays"]
        back = [o for o in ovs if o.get("variant") == "kt-year"]
        self.assertEqual(len(back), 1)                                # the year came back, cut before "signed"
        self.assertLessEqual(back[0]["startFrame"] + back[0]["durationInFrames"],
                             round((late["start"] - smart_editor.MIN_GAP) * doc["fps"]) + 1)
        self.assertGreaterEqual(back[0]["durationInFrames"], smart_editor.RESTORE_MIN_S * doc["fps"] - 1)
        self.assertFalse(any(o.get("variant") == "pf-dossier" for o in ovs))   # its start sits under a design
        self.assertFalse(any(o.get("variant") == "kt-keyword" for o in ovs))   # words only: replaced
        self.assertEqual(rep["restoredLooks"], 1)
        self.assertEqual(rep["trimmedLooks"], 1)
        ends = sorted((o["startFrame"], o["startFrame"] + o["durationInFrames"]) for o in ovs)
        for (a0, a1), (b0, b1) in zip(ends, ends[1:]):
            self.assertLessEqual(a1, b0)                              # still one at a time


class PersonMarkTests(unittest.TestCase):
    """2026-10-18 proof: a circle on "one man carrying tires" in a slum photo was labelled GEORGE OBAMA."""
    STORY = {"cast": [{"name": "Barack Obama"}, {"name": "George Obama"}, {"name": "Malik Obama"},
                      {"name": "Barack Obama Sr."}]}

    def _d(self, label, text="GEORGE OBAMA"):
        return {"kind": "spot", "text": text, "highlight": {"thing": "one man carrying tires", "mark": "circle",
                                                            "label": label}}

    def test_stranger_is_not_named(self):
        slum = {"media": {"type": "image", "contentDescription": "A crowd of men walks on a dirt road in a slum, "
                                                                 "with one man carrying tires and pointing.",
                          "attribution": "The New Humanitarian"}}
        self.assertFalse(smart_editor.person_mark_ok(self._d("GEORGE"), slum, self.STORY))

    def test_named_shot_and_things_pass(self):
        shot = {"media": {"type": "image", "contentDescription": "George Obama stands outside his home in Nairobi"}}
        self.assertTrue(smart_editor.person_mark_ok(self._d("GEORGE"), shot, self.STORY))
        thing = {"kind": "spot", "text": "TAX EXEMPT STATUS", "highlight": {"thing": "the letter", "label": "IRS"}}
        self.assertTrue(smart_editor.person_mark_ok(thing, {"media": {"contentDescription": "a typed letter"}},
                                                    self.STORY))
        self.assertTrue(smart_editor.person_mark_ok(self._d("GEORGE"), shot, {}))   # no cast: nothing to check

    def test_edit_drops_the_mark_keeps_the_graphic(self):
        doc = _doc()
        doc["scenes"][1]["media"] = {"type": "image", "url": "", "contentDescription": "a man on a dirt road"}
        doc["scenes"][1]["text"] = "On the summit George sits bolted to the rock."
        for w, new in zip(doc["scenes"][1]["words"], doc["scenes"][1]["text"].split()):
            w["text"] = new
        story = {"title": "t", "cast": [{"name": "George Obama"}, {"name": "Malik Obama"}]}

        def answer(rows, looks, story_, recent, hook, budget):
            return {"graphics": [{"beat": 1, "at": "George", "kind": "spot", "text": "George",
                                  "highlight": {"thing": "a man", "mark": "circle", "label": "George"},
                                  "camera": "push-to-point"}], "keep": [], "transitions": []}
        anchor = mock.Mock(return_value={"x": 0.5, "y": 0.5, "r": 0.1})
        with mock.patch.object(smart_editor, "_direct_chunk", side_effect=answer), \
                mock.patch.object(smart_editor, "_anchor", anchor):
            rep = smart_editor.edit(doc, story, critic=False)
        self.assertNotIn("error", rep)
        self.assertEqual(rep["marks"], 0)
        anchor.assert_not_called()                                    # no vision call spent on it either
        self.assertEqual(rep["rejected"].get("mark names a person the shot is not known to show"), 1)
        smart = [o for o in doc["overlays"] if o.get("variant") == "smart-spec"]
        self.assertEqual(len(smart), 1)
        self.assertNotIn("highlight", smart[0]["smart"]["design"])
        self.assertNotEqual(smart[0]["smart"]["design"].get("camera"), "push-to-point")
