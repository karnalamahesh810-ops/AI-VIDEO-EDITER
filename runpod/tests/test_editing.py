"""Editing v3 (src/editing.py): the finishing pass. Offline, synthetic documents."""
import copy
import json
import unittest

from src import config, editing


def _words(text, start, end):
    toks = text.split()
    step = (end - start) / max(1, len(toks))
    out = []
    for i, t in enumerate(toks):
        a = start + i * step
        out.append({"text": t, "start": round(a, 3), "end": round(a + step * 0.8, 3)})
    return out


def _scene(i, start, dur, text, mtype="image", fps=30, **kw):
    s = {"id": f"s{i:04d}", "startFrame": int(start * fps), "durationInFrames": int(dur * fps), "text": text,
         "media": {"type": mtype, "url": f"https://x/{i}.{'mp4' if mtype == 'video' else 'jpg'}", "source": "web",
                   # a sharp picture (src/stillframe.py maxZoom, 2026-10-26): room for its detail framings and punches
                   **({"maxZoom": 1.8} if mtype == "image" else {})},
         "motion": "push-offcenter" if mtype == "image" else "none", "transition": "none",
         "effect": "ken-burns" if mtype == "image" else "none", "frame": "full",
         "words": _words(text, start, start + dur - 0.3)}
    s.update(kw)
    return s


def _doc(scenes, overlays=None, fps=30):
    total = max(s["startFrame"] + s["durationInFrames"] for s in scenes)
    return {"fps": fps, "durationInFrames": total, "scenes": scenes, "overlays": overlays or [], "sfx": [],
            "meta": {"voiceLufs": -20.0}}


LONG = ("The valley floor stretches for miles. Nobody expected the biggest change in forty years. "
        "But the river kept rising, and the town had only one road out.")


class SplitHolds(unittest.TestCase):
    def test_long_still_becomes_detail_shots_on_word_boundaries(self):
        doc = _doc([_scene(0, 0, 4, "Opening line here now."), _scene(1, 4, 15, LONG), _scene(2, 19, 5, "End.")])
        editing.apply(doc, {"editing_v3": True})
        ids = [s["id"] for s in doc["scenes"]]
        self.assertIn("s0001-e1", ids)
        pieces = [s for s in doc["scenes"] if s["id"].startswith("s0001")]
        self.assertGreaterEqual(len(pieces), 2)
        # contiguous, same total, every piece >= the minimum, words kept in order and complete
        fps = doc["fps"]
        self.assertEqual(pieces[0]["startFrame"], 4 * fps)
        self.assertEqual(sum(p["durationInFrames"] for p in pieces), 15 * fps)
        for a, b in zip(pieces, pieces[1:]):
            self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
            self.assertEqual(b["splitFrom"], a["id"])
            self.assertEqual(b["transition"], "none")
        self.assertTrue(all(p["durationInFrames"] >= int(editing.PIECE_MIN * fps * 0.9) for p in pieces))
        words = [w["text"] for p in pieces for w in p["words"]]
        self.assertEqual(words, LONG.split())
        # each cut lands just before a word
        for p in pieces[1:]:
            first = p["words"][0]["start"]
            self.assertAlmostEqual(p["startFrame"] / fps, first - 0.06, delta=0.05)
        # later pieces are detail framings with another hand move
        for p in pieces[1:]:
            self.assertGreater(p["keyframes"]["scale"][0]["v"], 1.0)
            self.assertNotEqual(p["motion"], pieces[0]["motion"])
        rep = doc["meta"]["editingV3"]
        self.assertGreater(rep["holds"]["split"], 0)
        self.assertLess(rep["after"]["max"], rep["before"]["max"])

    def test_clip_chains_forward_only_when_the_file_holds_it(self):
        short = _scene(1, 4, 12, LONG, mtype="video")
        short["media"]["clipSeconds"] = 12.2
        long_ = _scene(1, 4, 12, LONG, mtype="video")
        long_["media"]["clipSeconds"] = 20.0
        d1 = _doc([_scene(0, 0, 4, "a b c d e f."), short])
        d2 = _doc([_scene(0, 0, 4, "a b c d e f."), long_])
        editing.apply(d1, {"editing_v3": True})
        editing.apply(d2, {"editing_v3": True})
        self.assertFalse(any(s["id"].startswith("s0001-e") for s in d1["scenes"]))
        pieces = [s for s in d2["scenes"] if s["id"].startswith("s0001")]
        self.assertGreaterEqual(len(pieces), 2)
        self.assertNotIn("keyframes", pieces[1]) if not pieces[1].get("semanticMetadata", {}).get("punch") else None
        self.assertGreater(pieces[1]["media"]["trimStart"], pieces[0]["durationInFrames"] / 30)
        self.assertLessEqual(pieces[-1]["media"]["trimStart"] + pieces[-1]["durationInFrames"] / 30, 20.0 + 0.05)

    def test_hook_cuts_faster(self):
        doc = _doc([_scene(0, 0, 6.5, "Nobody saw this coming at all, not one person."), _scene(1, 6.5, 6.5, LONG[:60])])
        editing.apply(doc, {"editing_v3": True})
        self.assertGreater(len(doc["scenes"]), 2)

    def test_style_that_holds_stills_still_is_left_alone(self):
        old = config.STILL_MOTION
        try:
            config.STILL_MOTION = "none"
            doc = _doc([_scene(0, 0, 4, "a b c."), _scene(1, 4, 15, LONG)])
            editing.apply(doc, {"editing_v3": True})
            self.assertFalse(any("-e" in s["id"] for s in doc["scenes"]))
        finally:
            config.STILL_MOTION = old


class Punches(unittest.TestCase):
    def test_punch_lands_on_the_emphasis_word_and_holds(self):
        doc = _doc([_scene(0, 0, 7, "Back then the lake held forty million acre feet of water."),
                    _scene(1, 7, 7, "It was the largest reservoir in the country by far."),
                    _scene(2, 14, 7, "Engineers came from everywhere to see it work.")])
        editing.apply(doc, {"editing_v3": True, "config": {"EDIT_V3_SPLIT_HOLDS": False, "EDIT_V3_HOOK_PACE": False}})
        punched = [s for s in doc["scenes"] if (s.get("semanticMetadata") or {}).get("punch")]
        self.assertTrue(punched)
        for s in punched:
            p = s["semanticMetadata"]["punch"]
            keys = s["keyframes"]["scale"]
            self.assertEqual(keys[0]["v"], 1.0)
            self.assertGreater(keys[-1]["v"], 1.0)
            self.assertEqual(keys[-1]["e"], "expoOut")
            word = next(w for w in s["words"] if w["text"] == p["word"])
            self.assertAlmostEqual(s["startFrame"] / 30 + p["at"], word["start"] - editing.PUNCH_LEAD, delta=0.01)
            self.assertIn(editing._norm(p["word"]), {"forty", "largest", "million"})
        # a soft sound under each, under the owner's level
        rows = [r for r in doc["sfx"] if r["kind"] == "punch"]
        self.assertTrue(rows)
        self.assertTrue(all(0 < r["volume"] <= 1 for r in rows))

    def test_no_punch_near_a_graphic_or_on_an_uncropped_clip(self):
        sc = [_scene(0, 0, 7, "Back then the lake held forty million acre feet of water.")]
        word = next(w for w in sc[0]["words"] if w["text"] == "forty")
        ov = {"type": "motion", "template": "KT_NUMBER", "value": 40, "startFrame": int(word["start"] * 30),
              "durationInFrames": 90}
        doc = _doc(sc, [ov])
        editing.apply(doc, {"editing_v3": True, "config": {"EDIT_V3_SPLIT_HOLDS": False, "EDIT_V3_HOOK_PACE": False}})
        p = (doc["scenes"][0].get("semanticMetadata") or {}).get("punch")
        self.assertTrue(p is None or editing._norm(p["word"]) not in ("forty",))
        old = config.REFRAME_CLIPS
        try:
            config.REFRAME_CLIPS = False
            v = _doc([_scene(0, 0, 7, "It was the largest reservoir in the country by far.", mtype="video")])
            editing.apply(v, {"editing_v3": True})
            self.assertNotIn("keyframes", v["scenes"][0])
        finally:
            config.REFRAME_CLIPS = old

    def test_quiet_stretch_gets_an_interrupt(self):
        # 60 s of 6 s shots, plain words with one weak emphasis word per minute half
        scenes = []
        for i in range(10):
            text = "The road winds past the old farms and quiet hills toward the town."
            if i == 5:
                text = "The road winds past the old farms and then suddenly the hills open up."
            scenes.append(_scene(i, i * 6, 6, text))
        doc = _doc(scenes)
        editing.apply(doc, {"editing_v3": True, "config": {"EDIT_V3_SPLIT_HOLDS": False, "EDIT_V3_HOOK_PACE": False,
                                                            "EDIT_V3_PUNCHES": False}})
        rep = doc["meta"]["editingV3"]
        self.assertGreaterEqual(rep["interrupts"], 1)
        self.assertLessEqual(rep["after"]["longestQuiet"], rep["before"]["longestQuiet"])


class Hygiene(unittest.TestCase):
    def test_graphic_over_a_full_screen_graphic_and_repeats_go(self):
        scenes = [_scene(0, 0, 10, "a b c d e f g h."), _scene(1, 10, 5, "nine thousand people", mtype="animation"),
                  _scene(2, 15, 200, "x y z.")]
        ovs = [{"type": "motion", "template": "KT_NUMBER", "value": 9000, "startFrame": 10 * 30 + 15,
                "durationInFrames": 120},
               {"type": "motion", "template": "SMART_SPEC", "text": "ALERT: NORMAL", "startFrame": 20 * 30,
                "durationInFrames": 90},
               {"type": "motion", "template": "SMART_SPEC", "text": "ALERT LEVEL: NORMAL", "startFrame": 120 * 30,
                "durationInFrames": 90},
               {"type": "motion", "template": "LIB_SRC_TAG", "text": "USGS", "startFrame": 10 * 30 + 15,
                "durationInFrames": 90}]
        doc = _doc(scenes, ovs)
        doc["sfx"] = [{"kind": "smart", "name": "stamp", "startFrame": 120 * 30, "volume": 0.3}]
        editing.apply(doc, {"editing_v3": True, "config": {"EDIT_V3_SPLIT_HOLDS": False, "EDIT_V3_HOOK_PACE": False,
                                                            "EDIT_V3_PUNCHES": False, "EDIT_V3_INTERRUPTS": False}})
        kept = [o["template"] + ":" + str(o.get("text", o.get("value"))) for o in doc["overlays"]]
        self.assertEqual(kept, ["SMART_SPEC:ALERT: NORMAL", "LIB_SRC_TAG:USGS"])
        self.assertFalse([r for r in doc["sfx"] if r["kind"] == "smart"])
        self.assertEqual(doc["meta"]["editingV3"]["hygiene"], {"overScene": 1, "repeated": 1, "sounds": 1})

    def test_texture_effects_only_on_film_scenes(self):
        doc = _doc([_scene(0, 0, 5, "a b c.", mtype="video", effect="color-shift"),
                    _scene(1, 5, 5, "a b c.", mtype="video", effect="dust", treatment="archival"),
                    _scene(2, 10, 5, "a b c.", effect="light-leaks")])
        editing.apply(doc, {"editing_v3": True})
        self.assertEqual([s["effect"] for s in doc["scenes"]], ["none", "dust", "ken-burns"])


class Switches(unittest.TestCase):
    def test_off_leaves_the_document_exactly_as_it_was(self):
        doc = _doc([_scene(0, 0, 4, "Opening line."), _scene(1, 4, 15, LONG, effect="color-shift")])
        before = json.dumps(doc, sort_keys=True)
        editing.apply(doc, {"editing_v3": False})
        self.assertEqual(json.dumps(doc, sort_keys=True), before)
        old = config.EDITING_V3
        try:
            config.EDITING_V3 = False
            editing.apply(doc, {})
            self.assertEqual(json.dumps(doc, sort_keys=True), before)
        finally:
            config.EDITING_V3 = old

    def test_an_error_restores_the_document(self):
        doc = _doc([_scene(0, 0, 4, "Opening line."), _scene(1, 4, 15, LONG)])
        doc["scenes"][1]["words"] = "broken"
        before = copy.deepcopy(doc)
        rep = editing.apply(doc, {"editing_v3": True})
        if "error" in rep:
            self.assertEqual(doc["scenes"], before["scenes"])

    def test_deterministic(self):
        a = _doc([_scene(0, 0, 4, "Opening line."), _scene(1, 4, 15, LONG), _scene(2, 19, 12, LONG)])
        b = copy.deepcopy(a)
        editing.apply(a, {"editing_v3": True})
        editing.apply(b, {"editing_v3": True})
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_output_passes_the_clip_fx_cleaner_unchanged(self):
        from src import clipfx
        doc = _doc([_scene(0, 0, 4, "Opening line."), _scene(1, 4, 15, LONG), _scene(2, 19, 7, "the largest ever.")])
        editing.apply(doc, {"editing_v3": True})
        cleaned = copy.deepcopy(doc)
        clipfx.clean(cleaned)
        for s, c in zip(doc["scenes"], cleaned["scenes"]):
            self.assertEqual(s.get("keyframes"), c.get("keyframes"))


if __name__ == "__main__":
    unittest.main()
