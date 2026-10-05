"""
The subtitles (2026-10-05): phrase cues set like professional subtitles
(remotion/src/components/captionCues.ts), placed clear of the graphics
(captionPlace.ts, captionPlan.ts, data/caption_footprints.json), seven clean
styles as registry data, and every older style id drawing as its closest new
one. Offline: the renderer's TypeScript runs under node (esbuild), no network.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from src import brandkit, fanout, templates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
COMPONENTS = os.path.join(REMOTION, "src", "components")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
FOOTPRINTS = os.path.join(REMOTION, "src", "data", "caption_footprints.json")

NEW_STYLES = {"netflix", "cinema_box", "doc_serif", "minimal", "clean_highlight", "news_bold", "letterbox"}
OLD_TO_NEW = {"documentary": "netflix", "news": "news_bold", "modern": "clean_highlight", "case": "cinema_box"}
ARTICLES = {"a", "an", "the"}
PHRASE_STARTS = {"and", "but", "or", "so", "because", "which", "who", "that", "when", "where", "while", "if", "as",
                 "to", "of", "in", "on", "at", "for", "with", "from", "by", "into", "through", "after", "before",
                 "i", "we", "they", "he", "she", "it", "you"}


def _narration(name):
    with open(os.path.join(FIXTURES, f"words_{name}.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    return [{"text": w, "start": s, "end": e} for w, s, e in d["words"]]


def _words(text, start=0.0, step=0.3, pauses=None):
    """Evenly spoken words; `pauses` {index: seconds} adds silence after a word."""
    out, t = [], start
    for i, w in enumerate(text.split()):
        out.append({"text": w, "start": round(t, 3), "end": round(t + step * 0.85, 3)})
        t += step + (pauses or {}).get(i, 0.0)
    return out


# --------------------------------------------------------------------------- the styles (Python side)
class Styles(unittest.TestCase):
    def test_seven_clean_styles_with_every_field_and_netflix_the_default(self):
        reg = templates.load()
        self.assertEqual(set(reg["captionStyles"]), NEW_STYLES)
        self.assertEqual(reg["captionStyleDefault"], "netflix")
        self.assertEqual(templates.check(), [])
        for sid, st in reg["captionStyles"].items():
            self.assertFalse(templates.CAPTION_STYLE_KEYS - set(st), sid)
            self.assertTrue(st["name"] and st["description"], sid)
            self.assertLessEqual(st["lineChars"], 42, sid)
            self.assertTrue(36 <= st["size"] <= 64, sid)                 # px at 1080 lines: not a shouting size
            self.assertTrue(300 <= st["weight"] <= 700, sid)             # no black/heavy weights
            self.assertIn(st["background"], ("none", "box", "band"), sid)
            self.assertIn(st["highlight"], ("none", "word"), sid)
            # Nothing animates: a style is type, colour, shadow and a box - no motion fields at all.
            self.assertFalse({"pop", "scale", "bounce", "zoom", "emphasis", "animation"} & set(st), sid)

    def test_every_style_names_a_font_the_renderer_loads(self):
        with open(os.path.join(COMPONENTS, "captionStyle.ts"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"CAPTION_FONTS[^=]*=\s*\{(.*?)\n\};", src, re.S).group(1)
        fonts = set(re.findall(r'^\s*"?([a-z-]+)"?\s*:', block, re.M))
        for sid, st in templates.caption_styles().items():
            self.assertIn(st["font"], fonts, sid)
        # Loaded the same way as the renderer's other type, from packages it already has.
        for pkg in re.findall(r'from "(@remotion/google-fonts/[A-Za-z0-9]+)"', src):
            self.assertTrue(os.path.isdir(os.path.join(REMOTION, "node_modules", *pkg.split("/")[:2]))
                            or not os.path.isdir(os.path.join(REMOTION, "node_modules")), pkg)

    def test_the_registry_is_built_from_the_script(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_registry", os.path.join(ROOT, "scripts", "build_registry.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        reg = templates.load()
        self.assertEqual(reg["captionStyles"], json.loads(json.dumps(mod.CAPTION_STYLES)))
        self.assertEqual(reg["captionStyleAliases"], mod.CAPTION_STYLE_ALIASES)


class OldIds(unittest.TestCase):
    def test_every_older_id_draws_as_its_closest_new_style(self):
        for old, new in OLD_TO_NEW.items():
            self.assertEqual(templates.caption_style_id(old), new)
            self.assertEqual(templates.caption_style_id(old.upper()), new)
            self.assertEqual(templates.caption_style_id(old, default=False), new)
        for sid in NEW_STYLES:
            self.assertEqual(templates.caption_style_id(sid), sid)
        self.assertEqual(templates.caption_style_id("Cinema box"), "cinema_box")
        self.assertEqual(templates.caption_style_id("doc-serif"), "doc_serif")
        for odd in ("disco", "", None, 3):
            self.assertEqual(templates.caption_style_id(odd), "netflix")
            self.assertEqual(templates.caption_style_id(odd, default=False), "")

    def test_the_style_packs_still_validate(self):
        for name, pack in templates.style_packs().items():
            self.assertTrue(templates.caption_style_id(pack["caption"], default=False), name)

    def test_a_brand_kit_with_an_older_style_keeps_it_as_the_new_one(self):
        kit = brandkit.parse({"name": "Weather Alert", "accent": "#f4a100", "caption_style": "case"})
        self.assertEqual(kit["caption_style"], "cinema_box")
        kit = brandkit.parse({"name": "x", "caption_style": "letterbox"})
        self.assertEqual(kit["caption_style"], "letterbox")
        kit = brandkit.parse({"name": "x", "caption_style": "karaoke"})
        self.assertIsNone(kit["caption_style"])
        self.assertTrue(kit["warnings"])


class Planner(unittest.TestCase):
    def test_captions_stay_off_and_the_style_is_netflix_unless_chosen(self):
        from tests.test_pipeline import build_doc
        doc = build_doc(n=3, seconds=4.0)
        self.assertFalse(doc["captions"]["enabled"])
        self.assertEqual(doc["captions"]["style"], "netflix")
        doc = build_doc(n=3, seconds=4.0, inp={"captions": True, "caption_style": "news"})
        self.assertTrue(doc["captions"]["enabled"])
        self.assertEqual(doc["captions"]["style"], "news_bold")
        doc = build_doc(n=3, seconds=4.0, inp={"caption_style": "letterbox"})
        self.assertEqual(doc["captions"]["style"], "letterbox")


class ChunkHash(unittest.TestCase):
    def _doc(self, enabled):
        scenes = []
        for i in range(12):
            scenes.append({"id": f"s{i}", "startFrame": i * 90, "durationInFrames": 90, "text": f"line {i}",
                           "media": {"type": "image", "url": f"https://x/{i}.jpg"},
                           "words": [{"text": f"w{i}", "start": i * 3.0, "end": i * 3.0 + 0.4}]})
        return {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 1080, "scenes": scenes,
                "overlays": [{"template": "LIB_LT_ACCENT_LINE", "type": "motion", "startFrame": 400,
                              "durationInFrames": 90}],
                "captions": {"enabled": enabled, "style": "netflix"}}

    def test_with_captions_on_a_word_anywhere_or_a_graphic_within_a_cues_reach_changes_the_chunk(self):
        doc = self._doc(True)
        base = fanout.chunk_hash(doc, 0, 299)
        far = copy.deepcopy(doc)
        far["scenes"][11]["words"][0]["text"] = "changed"
        self.assertNotEqual(fanout.chunk_hash(far, 0, 299), base)
        near = copy.deepcopy(doc)
        near["overlays"][0]["position"] = "top"            # frames 400-490: within 8 s of frames 0-299
        self.assertNotEqual(fanout.chunk_hash(near, 0, 299), base)
        off = self._doc(False)
        off_far = copy.deepcopy(off)
        off_far["scenes"][11]["words"][0]["text"] = "changed"
        self.assertEqual(fanout.chunk_hash(off_far, 0, 299), fanout.chunk_hash(off, 0, 299))


class Footprints(unittest.TestCase):
    def test_the_data_is_well_formed_and_names_real_looks(self):
        with open(FOOTPRINTS, encoding="utf-8") as fh:
            data = json.load(fh)
        cols, rows = data["grid"]
        self.assertEqual((cols, rows), (32, 18))
        ids = {t["id"] for t in templates.all_templates()}
        for key, mask in data["looks"].items():
            self.assertIn(key, ids)
            self.assertRegex(mask, r"^[0-9a-f]{%d}$" % (8 * rows), key)
            self.assertTrue(mask.strip("0"), key)                    # a look that drew nothing is left out
            # A full-screen card is measured by its words, labels and edges, not as one solid block.
            cells = sum(bin(int(mask[r * 8:(r + 1) * 8], 16)).count("1") for r in range(rows))
            self.assertLess(cells, 0.85 * cols * rows, key)
        # Most looks are measured (a few added since are guessed from their position until the script runs).
        drawn = [t for t in templates.all_templates() if t["component"] not in ("map", "split") and t["category"] != "MAPS"]
        self.assertGreaterEqual(sum(1 for t in drawn if t["id"] in data["looks"]) / len(drawn), 0.85)

    def test_lower_thirds_sit_low_and_the_dated_caption_bottom_left(self):
        with open(FOOTPRINTS, encoding="utf-8") as fh:
            data = json.load(fh)

        def rows_of(key):
            m = data["looks"][key]
            return [r for r in range(18) if int(m[r * 8:(r + 1) * 8], 16)]

        lower = [k for k in data["looks"] if k.startswith("LIB_LT_")]
        low = [k for k in lower if max(rows_of(k)) >= 9]               # reaches the lower half
        self.assertGreaterEqual(len(low), len(lower) - 2, sorted(set(lower) - set(low)))
        self.assertGreaterEqual(min(rows_of("LIB_VR_CAPTION_TYPED")), 12)   # the typed "Place, Year" sits bottom left
        self.assertEqual(max(rows_of("LIB_VR_CAPTION_TYPED")), 17)

    def test_the_split_labels_and_the_data_looks_are_measured(self):
        # 2026-10-05 review: the split was measured without its label pills (low in each half, where a
        # subtitle goes) and ten data looks drew nothing from empty samples, so nothing kept clear of them.
        with open(FOOTPRINTS, encoding="utf-8") as fh:
            data = json.load(fh)
        split = data["looks"]["CMP_SPLIT_V1"]
        rows = {r: int(split[r * 8:(r + 1) * 8], 16) for r in range(18)}
        self.assertTrue(any(rows[r] for r in range(13, 17)))                 # the pills
        self.assertFalse(any(v & (0b11 << 15) for v in rows.values()))      # not the divider between the pictures
        for key in ("NUM_TREND_V1", "NUM_DONUT_V1", "CHART_LINE_V1", "CHART_RANKING_V1", "TL_PROGRESS_STEPS_V1"):
            self.assertIn(key, data["looks"])


# --------------------------------------------------------------------------- the renderer's code under node
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import * as cues from "%(c)s/captionCues";
import * as place from "%(c)s/captionPlace";
import * as plan from "%(c)s/captionPlan";
import { captionStyleId } from "%(c)s/../templates";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = input.map((c: any) => {
  switch (c.op) {
    case "cues": return cues.buildCues(c.words, c.options || {});
    case "frames": return cues.cueFrames(cues.buildCues(c.words, c.options || {}), c.fps || 30);
    case "clean": return cues.cleanWords(c.words);
    case "break": return cues.breakCost(c.words, c.i);
    case "place": return place.placeCue(c.box, c.rects);
    case "rects": return place.footprintRects(c.mask, c.grid);
    case "placeRects": return place.placeRects(c.rects, c.position, c.scale);
    case "plan": {
      const p = plan.planCaptions(c.doc, c.doc.fps, c.doc.width, c.doc.height);
      return { style: p.style, cues: p.cues, places: p.places, bands: p.bands };
    }
    case "styleId": return captionStyleId(c.name);
    default: return null;
  }
});
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Renderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"c": COMPONENTS.replace("\\", "/")})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=180)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_calls(self, *calls):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(list(calls)), capture_output=True, text=True,
                             encoding="utf-8", timeout=120, check=True)
        return json.loads(run.stdout)

    def cues(self, words, **options):
        return self.run_calls({"op": "cues", "words": words, "options": options})[0]

    # ------------------------------------------------------------------ the rules every cue keeps
    def assert_professional(self, words, cues, fps=30, max_chars=42):
        texts = [w["text"] for w in words]
        flat = [w["text"] for c in cues for line in c["lines"] for w in line]
        self.assertEqual(" ".join(flat).replace(" -", "-"), " ".join(texts).replace(" -", "-"))  # every word once, in order
        gap = 2 / fps
        for i, c in enumerate(cues):
            self.assertLessEqual(len(c["lines"]), 2, c["text"])
            for line in c["lines"]:
                text = " ".join(w["text"] for w in line)
                self.assertLessEqual(len(text), max_chars, text)
                if sum(len(l) for l in c["lines"]) >= 4:
                    self.assertGreaterEqual(len(line), 2, f"orphan word: {c['text']!r}")
            first = c["lines"][0][0]
            last = c["lines"][-1][-1]
            self.assertAlmostEqual(c["start"], first["start"], places=6)          # appears with its first word
            self.assertLessEqual(c["end"] - c["start"], 7.0 + 1e-6, c["text"])
            self.assertGreaterEqual(c["end"], last["end"] - gap - 1e-6, c["text"])  # stays while its words are spoken
            nxt = cues[i + 1] if i + 1 < len(cues) else None
            chained = nxt is not None and abs(nxt["start"] - c["end"] - gap) < 1e-6
            if not chained:                                                       # leaves shortly after its last word
                self.assertLessEqual(c["end"], max(last["end"] + 0.45, c["start"] + max(1.0, len(c["text"]) / 20)) + 1e-6)
            if nxt:
                space = nxt["start"] - c["end"]
                self.assertGreaterEqual(space, gap - 1e-6, c["text"])              # never two cues at once
                if space < 0.5 - 1e-6:
                    self.assertAlmostEqual(space, gap, places=5, msg=c["text"])   # a short gap is closed to 2 frames
                    self.assertFalse(c["fadeOut"])
                    self.assertFalse(nxt["fadeIn"])
                else:
                    self.assertTrue(c["fadeOut"])
                    self.assertTrue(nxt["fadeIn"])
                if c["end"] - c["start"] < 1.0 - 1e-6:                            # under a second only when the next cue came
                    self.assertAlmostEqual(space, gap, places=5, msg=c["text"])

    def test_real_narrations_keep_every_rule(self):
        for name in ("lake_mead", "new_mexico_flash_flood"):
            words = _narration(name)
            cues = self.cues(words)
            self.assert_professional(words, cues)
            # Lines and cues end where the phrase does: never after an article.
            for c in cues:
                for line in c["lines"]:
                    self.assertNotIn(line[-1]["text"].lower(), ARTICLES, c["text"])
            # Most cues end at a sentence, a clause, a pause in the voice or before a conjunction or preposition.
            ends = 0
            for i, c in enumerate(cues[:-1]):
                last = c["lines"][-1][-1]
                nxt = cues[i + 1]["lines"][0][0]
                if re.search(r"[.!?,;:]['\")]*$", last["text"]) or nxt["start"] - last["end"] >= 0.3                         or nxt["text"].lower() in PHRASE_STARTS:
                    ends += 1
            self.assertGreaterEqual(ends / max(1, len(cues) - 1), 0.8, name)
            self.assertTrue(10 <= len(cues) <= 40, (name, len(cues)))

    def test_a_short_line_is_one_line_and_a_long_one_two_balanced_lines(self):
        cues = self.cues(_words("Lake Mead is falling again."))
        self.assertEqual([len(c["lines"]) for c in cues], [1])
        sentence = "The water was tearing through the concrete lining of the tunnel and into the rock behind it."
        cues = self.cues(_words(sentence, step=0.28))
        self.assert_professional(_words(sentence, step=0.28), cues)
        for c in cues:
            if len(c["lines"]) == 2:
                a, b = (len(" ".join(w["text"] for w in l)) for l in c["lines"])
                self.assertLessEqual(abs(a - b), 22, c["text"])

    def test_no_orphans_even_when_a_two_line_cue_is_unavoidable(self):
        words = _words("Reclamation engineers measured extraordinary sedimentation everywhere downstream", step=0.4)
        cues = self.cues(words)
        self.assert_professional(words, cues)

    def test_a_long_pause_always_ends_a_cue_and_fades(self):
        words = _words("It was quiet. Then the gates opened.", pauses={2: 1.5})
        cues = self.cues(words)
        self.assertEqual([c["text"] for c in cues], ["It was quiet.", "Then the gates opened."])
        self.assertTrue(cues[0]["fadeOut"] and cues[1]["fadeIn"])
        self.assertTrue(cues[0]["fadeIn"] and cues[1]["fadeOut"])

    def test_sentences_in_a_row_chain_without_a_blink(self):
        words = _words("The dam held. The town slept. Nobody knew.", step=0.32)
        cues = self.cues(words)
        self.assert_professional(words, cues)
        for a, b in zip(cues, cues[1:]):
            self.assertAlmostEqual(b["start"] - a["end"], 2 / 30, places=5)

    def test_long_unbroken_speech_never_exceeds_seven_seconds(self):
        words = _words(" ".join(["water"] * 60), step=0.3)
        cues = self.cues(words)
        self.assert_professional(words, cues)
        self.assertGreater(len(cues), 4)

    def test_a_short_cue_lingers_to_a_second_when_there_is_room(self):
        cues = self.cues(_words("Gone.", step=0.3))
        self.assertAlmostEqual(cues[0]["end"] - cues[0]["start"], 1.0, places=5)

    def test_fast_speech_stays_aligned_to_the_voice(self):
        words = _words("This is a very fast talker who never stops for breath at all today friends", step=0.12)
        cues = self.cues(words)
        self.assert_professional(words, cues)
        for c in cues:
            self.assertAlmostEqual(c["start"], c["lines"][0][0]["start"], places=6)

    def test_split_words_and_lone_marks_join_their_word(self):
        got = self.run_calls({"op": "clean", "words": [
            {"text": "Four", "start": 0, "end": 0.3}, {"text": "-foot", "start": 0.3, "end": 0.6},
            {"text": "sheets", "start": 0.6, "end": 0.9}, {"text": "—", "start": 0.9, "end": 0.95},
            {"text": "plywood", "start": 1.0, "end": 1.4}, {"text": "  ", "start": 1.4, "end": 1.5},
            {"text": "it", "start": 1.5, "end": 1.6}, {"text": "'s", "start": 1.6, "end": 1.7}]})[0]
        self.assertEqual([w["text"] for w in got], ["Four-foot", "sheets —", "plywood", "it's"])

    def test_breaks_prefer_phrase_boundaries(self):
        words = _words("engineers at Glen Canyon Dam heard the rumble, and then the sound of water")
        costs = self.run_calls(*({"op": "break", "words": words, "i": i} for i in range(len(words) - 1)))
        by = {words[i]["text"]: c for i, c in enumerate(costs)}
        self.assertEqual(by["rumble,"], 3)                   # a comma
        self.assertLess(by["sound"], by["the"])              # before "of" vs. after an article
        self.assertGreater(by["Glen"], by["Dam"])            # a name stays together
        self.assertGreater(by["the"], 15)                    # never after an article

    def test_shot_changes_and_cue_frames(self):
        words = _words("One two three four five six seven eight nine ten eleven twelve thirteen", step=0.3)
        frames = self.run_calls({"op": "frames", "words": words, "fps": 30})[0]
        for a, b in zip(frames, frames[1:]):
            self.assertGreaterEqual(b["from"] - a["to"], 2)
            self.assertGreater(a["to"], a["from"])

    # ------------------------------------------------------------------ keeping clear of graphics
    def test_a_cue_rises_above_a_lower_third_and_stays_put_otherwise(self):
        box = {"x0": 0.3, "x1": 0.7, "h": 0.1, "y1": 0.91}
        lower_third = [{"x0": 0.05, "x1": 0.55, "y0": 0.74, "y1": 0.88}]
        corner = [{"x0": 0.8, "x1": 0.97, "y0": 0.8, "y1": 0.95}]
        full = [{"x0": 0, "x1": 1, "y0": 0, "y1": 1}]
        top_banner = [{"x0": 0.0, "x1": 1.0, "y0": 0.05, "y1": 0.2}]
        got = self.run_calls({"op": "place", "box": box, "rects": []}, {"op": "place", "box": box, "rects": corner},
                             {"op": "place", "box": box, "rects": lower_third},
                             {"op": "place", "box": box, "rects": full},
                             {"op": "place", "box": box, "rects": [{"x0": 0.1, "x1": 0.9, "y0": 0.45, "y1": 0.95}]},
                             {"op": "place", "box": box, "rects": [{"x0": 0.1, "x1": 0.9, "y0": 0.45, "y1": 0.95}] + top_banner})
        self.assertEqual(got[0], {"y1": 0.91, "mode": "default"})
        self.assertEqual(got[1]["mode"], "default")
        self.assertEqual(got[2]["mode"], "lifted")
        self.assertLessEqual(got[2]["y1"], 0.74 - 0.018 + 1e-9)       # its bottom clear of the graphic's top
        self.assertEqual(got[3]["mode"], "default")                   # nowhere clear: where it belongs
        self.assertEqual(got[4]["mode"], "top")                       # too tall to clear below: the top
        self.assertIn(got[5]["mode"], ("default", "top", "lifted"))

    def test_footprints_decode_and_move_with_the_overlay(self):
        mask = "00000000" * 15 + "0000000f" + "00000000" * 2       # row 15, columns 0-3
        rects, placed = self.run_calls({"op": "rects", "mask": mask, "grid": [32, 18]},
                                       {"op": "placeRects", "rects": [{"x0": 0.5, "x1": 0.75, "y0": 0.5, "y1": 0.75}],
                                        "position": "bottom-left", "scale": 0.5})
        self.assertEqual(len(rects), 1)
        self.assertAlmostEqual(rects[0]["x0"], 0.0)
        self.assertAlmostEqual(rects[0]["x1"], 4 / 32)
        self.assertAlmostEqual(rects[0]["y0"], 15 / 18)
        self.assertAlmostEqual(placed[0]["x0"], 0.5 - 0.22)
        self.assertAlmostEqual(placed[0]["x1"], 0.5 + 0.125 - 0.22)
        self.assertAlmostEqual(placed[0]["y0"], 0.5 + 0.22)

    def _doc(self, style, overlays=(), words_text=None):
        words = _words(words_text or "Engineers at the dam heard a rumble. Deep inside the mountain, "
                                     "the spillway was failing. Nobody knew how long it would hold.", step=0.33)
        return {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 900,
                "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 450, "text": "", "words": words[:9]},
                           {"id": "s1", "startFrame": 450, "durationInFrames": 450, "text": "", "words": words[9:]}],
                "overlays": list(overlays), "captions": {"enabled": True, "style": style, "accent": "#FFD400"}}

    def test_the_whole_plan_lifts_cues_over_a_bottom_graphic_and_keeps_the_rest_low(self):
        # The typed "Place, Year" sits in the bottom-left corner, where a centred subtitle reaches.
        lt = {"template": "LIB_VR_CAPTION_TYPED", "type": "motion", "text": "Glen Canyon Dam, 1983", "startFrame": 0,
              "durationInFrames": 120}
        plan = self.run_calls({"op": "plan", "doc": self._doc("netflix", [lt])})[0]
        self.assertEqual(plan["style"]["name"], "Streaming")
        modes = [(c["from"], p["mode"]) for c, p in zip(plan["cues"], plan["places"])]
        self.assertEqual(modes[0][1], "lifted")                          # on screen with the lower third
        self.assertTrue(all(m == "default" for f, m in modes if f >= 150), modes)
        # Hidden graphics hide nothing: the track toggle off leaves every cue where it belongs.
        doc = self._doc("netflix", [lt])
        doc["overlaysEnabled"] = False
        plan = self.run_calls({"op": "plan", "doc": doc})[0]
        self.assertTrue(all(p["mode"] == "default" for p in plan["places"]))

    def test_an_older_style_id_plans_as_its_new_style_and_letterbox_bands_hold_through_short_pauses(self):
        got = self.run_calls(*({"op": "styleId", "name": old} for old in OLD_TO_NEW),
                             {"op": "styleId", "name": "nonsense"}, {"op": "styleId", "name": None})
        self.assertEqual(got, list(OLD_TO_NEW.values()) + ["netflix", "netflix"])
        plan = self.run_calls({"op": "plan", "doc": self._doc("case")})[0]
        self.assertEqual(plan["style"]["name"], "Cinema box")
        plan = self.run_calls({"op": "plan", "doc": self._doc("letterbox")})[0]
        self.assertEqual(len(plan["bands"]), 1)                         # one band through the whole run of speech
        self.assertEqual(plan["bands"][0][0], plan["cues"][0]["from"])

    def test_missing_or_empty_words_never_fail_the_plan(self):
        base = {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 300,
                "captions": {"enabled": True, "style": "netflix"}}
        docs = [
            {**base, "scenes": []},
            {**base, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 300, "text": ""}]},
            {**base, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 300, "text": "", "words": []}]},
            {**base, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 90, "text": "Old pasted script."}]},
            {**base, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 300, "text": "x", "words": [
                {"text": "", "start": 0.1, "end": 0.2}, {"text": "ok", "start": None, "end": 0.3},
                {"text": "water", "start": 0.5, "end": None}, {"text": "  ", "start": 0.6, "end": 0.7}]}]},
        ]
        plans = self.run_calls(*({"op": "plan", "doc": d} for d in docs))
        self.assertEqual([len(p["cues"]) for p in plans[:3]], [0, 0, 0])
        self.assertEqual([c["text"] for c in plans[3]["cues"]], ["Old pasted script."])   # text without timings
        self.assertEqual([c["text"] for c in plans[4]["cues"]], ["water"])
        for p in plans:
            self.assertEqual(len(p["cues"]), len(p["places"]))
            for c in p["cues"]:
                self.assertGreater(c["to"], c["from"])

    def test_a_sentence_ends_a_line_never_runs_on_inside_one(self):
        # 2026-10-05 review: "The engineers did the only thing / they could. They closed that spillway down".
        text = ("The engineers did the only thing they could. They closed that spillway down as far as they "
                "dared. Then the water coming out the bottom changed color. It had been white.")
        words = _words(text, step=0.3)
        cues = self.cues(words)
        self.assert_professional(words, cues)
        for c in cues:
            if len(c["lines"]) < 2:
                continue
            for line in c["lines"]:
                inner = [w["text"] for w in line[:-1]]
                self.assertFalse(any(re.search(r"[.!?]$", t) for t in inner), c["text"])

    def test_of_stays_with_the_noun_before_it(self):
        words = _words("boulders the size of cars and the rule of geology")
        costs = self.run_calls(*({"op": "break", "words": words, "i": i} for i in range(len(words) - 1)))
        by = {words[i]["text"]: c for i, c in enumerate(costs)}
        self.assertGreater(by["size"], by["cars"])           # "size / of" dearer than "cars / and"
        self.assertGreater(by["rule"], by["cars"])

    def test_letterbox_band_leaves_room_for_a_bottom_corner_graphic_and_never_bridges_it(self):
        # A graphic low in the left corner, clear of the centred text but inside the band's strip:
        # the band would cover it (the subtitles draw above the graphics), so that cue is drawn on
        # its own line boxes and the band stops for it - before and after, the band is back.
        corner = {"template": "LIB_VR_CAPTION_TYPED", "type": "motion", "text": "1983", "startFrame": 60,
                  "durationInFrames": 40, "position": "bottom-left", "scale": 0.5}
        words = "It was quiet. The gates opened. Water poured out. Nobody knew. Then the rumble came back."
        doc = self._doc("letterbox", [corner], words_text=words)
        plan = self.run_calls({"op": "plan", "doc": doc})[0]
        modes = [p["mode"] for p in plan["places"]]
        hit = [i for i, c in enumerate(plan["cues"]) if c["from"] < 100 and c["to"] > 60]
        self.assertTrue(hit)
        for i in hit:
            self.assertNotEqual(modes[i], "default")
        for a, b in plan["bands"]:
            self.assertFalse(a < 100 and b > 60, plan["bands"])       # no band while the graphic is up
        self.assertGreaterEqual(len(plan["bands"]), 2)
        # A centred position never moves the letterbox band off the bottom.
        doc = self._doc("letterbox")
        doc["captions"]["position"] = "center"
        plan = self.run_calls({"op": "plan", "doc": doc})[0]
        self.assertTrue(all(p["y1"] > 0.9 for p in plan["places"]))

    def test_the_subtitles_draw_above_the_graphics(self):
        # Placed clear of every graphic, the track is drawn last (as a player draws subtitles): a cue that
        # cannot clear a full-screen card stays readable instead of vanishing under it.
        with open(os.path.join(REMOTION, "src", "Main.tsx"), encoding="utf-8") as fh:
            body = fh.read().split("const Body", 1)[1]
        self.assertLess(body.index("overlayNodes[i]"), body.index("<CaptionTrack"))

    def test_a_vertical_frame_sets_shorter_lines(self):
        doc = self._doc("netflix")
        doc.update(width=1080, height=1920)
        plan = self.run_calls({"op": "plan", "doc": doc})[0]
        for c in plan["cues"]:
            for line in c["lines"]:
                self.assertLessEqual(len(" ".join(w["text"] for w in line)), 32)


if __name__ == "__main__":
    unittest.main()
