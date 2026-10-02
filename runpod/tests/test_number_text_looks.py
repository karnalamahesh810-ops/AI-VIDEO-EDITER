"""
The pro number and text looks (families "nx" and "tx": remotion/src/components/lib/LibNumbersPro.tsx and
LibTextPro.tsx; the owner, 2026-10-02: "build more number ones based on the references ... and the text
section as well"):

  * the registry carries all 25 (LIB_NX_* 13, LIB_TX_* 12) from their own lists (scripts/library_looks_nx.json,
    library_looks_tx.json): ids unique, every variant drawn and picked in the library index, the editor's props,
    one place each (the single-figure looks place themselves: never shrunk into a corner);
  * every one is "autoPick": false: the planner never picks them on its own, on any path, and while they wait
    a planned video is exactly what it was without them;
  * switched on, a line chooses them by what it says (a record, a rate, a share of a whole, a sentence that
    frames the figure, an official statement, a line that turns on itself) with only its own words on screen;
  * figures are written in digits with their unit as said (nxFormat.ts, run in node);
  * each plays its own soft sound from its frames: a number only ticks and clicks, words swoosh, never a punch.
"""
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import sfxplan, templates, timeline, treatments
from src.transcribe import Segment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
LIB = os.path.join(REMOTION, "src", "components", "lib")
FPS = 30
PUNCHES = {"impact", "impact-punch", "date-slam", "hit-deep", "boom-sub", "boom-soft", "flash-hit", "glitch", "stamp"}
NEW = ("LIB_NX_", "LIB_TX_")


def _build_registry():
    spec = importlib.util.spec_from_file_location("build_registry", os.path.join(ROOT, "scripts", "build_registry.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def family(prefix):
    return [t for t in templates.all_templates() if t["id"].startswith(prefix)]


def ts_looks(name, fam):
    with open(os.path.join(LIB, name), encoding="utf-8") as fh:
        src = fh.read()
    block = src[src.index("export const LOOKS"):]
    return set(re.findall(r'"(%s-[a-z-]+)":' % fam, block))


def index_picks(fam):
    with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
        return set(re.findall(r'"(%s-[a-z-]+)"' % fam, fh.read()))


def on(real):
    """auto_ok with the new looks switched on (the owner's approval, simulated)."""
    return lambda tid: real(tid) or str(tid).startswith(NEW)


PLACE = {"subject": "Lake Powell", "subjectType": "place"}
PLAIN = "The marina crews worked through the night."
RECORD = "Lake Powell fell to 3,519 feet, the lowest level since the dam was filled."
RATE = "Las Vegas residents use 110 gallons per person every day."
SHARE = "Today Lake Powell is just 22 percent full."
CONTEXT = "About 40 million people depend on this one river."
OFFICIAL = "Reclamation officials said in a statement that they will protect Glen Canyon Dam."
QUOTED = "\"We have never seen the reservoir this low,\" a Bureau of Reclamation official said."
TURN = "This is not a drought - it's the new normal."
QUESTION = "So where did all the water go?"
WARNING = "Officials warned of a dead pool emergency at the dam."
MONEY = "The repairs will cost $4.2 billion over the next decade."
THEN_NOW = "In 1980 the lake stood at 3,700 feet; in 2023 it was 3,519 feet."


def small(texts, kinds=None, gap=12.0, pack="documentary"):
    kinds = kinds or ["video"] * len(texts)
    segs = [Segment(text=t, start=i * gap, end=(i + 1) * gap) for i, t in enumerate(texts)]
    frames = int(gap * FPS)
    scenes = [{"id": f"s{i}", "startFrame": i * frames, "durationInFrames": frames,
               "media": {"type": k, "url": f"https://x/{i}.{'jpg' if k == 'image' else 'mp4'}"},
               "transition": "none", "motion": "none", "effect": "none"} for i, k in enumerate(kinds)]
    brief = {"kind": "explainer", "hookBeats": [], "sections": []}
    return treatments.plan(segs, [dict(PLACE) for _ in texts], scenes, FPS, len(texts) * frames, brief,
                           treatments.pack_for(brief, pack), timeline._OVERLAY_SECONDS)


EVERY_CUE = [RECORD, PLAIN, RATE, PLAIN, SHARE, PLAIN, CONTEXT, PLAIN, OFFICIAL, PLAIN, QUOTED, PLAIN, TURN, PLAIN,
             QUESTION, PLAIN, WARNING, PLAIN, MONEY, PLAIN, THEN_NOW, PLAIN,
             "California 4.4 million, Arizona 2.8 million, Nevada 300,000 acre-feet.", PLAIN,
             "Lake Powell is now 3,519 feet above sea level.", PLAIN, "Lake Mead Is Dying Fast", PLAIN]


class Registry(unittest.TestCase):
    def test_twenty_five_looks_with_unique_ids(self):
        ids = [t["id"] for t in templates.all_templates()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(family("LIB_NX_")), 13)
        self.assertEqual(len(family("LIB_TX_")), 12)
        for t in family("LIB_NX_") + family("LIB_TX_"):
            self.assertEqual(t["component"], "motion", t["id"])
            self.assertEqual(t["id"], "LIB_" + t["defaults"]["variant"].upper().replace("-", "_"))
            self.assertTrue(t["description"].strip() and t["name"].strip(), t["id"])
            self.assertEqual(t["defaults"]["exit"], "none", t["id"])          # each look leaves on its own
            self.assertNotIn("own-backdrop", t["tags"], t["id"])              # they ride on the picture
        for t in family("LIB_NX_"):
            self.assertEqual(t["category"], "NUMBERS", t["id"])
        for t in family("LIB_TX_"):
            self.assertIn(t["category"], ("TEXT", "HEADLINES", "QUOTES", "LOWER_THIRDS"), t["id"])
        self.assertEqual(templates.check(), [])

    def test_every_variant_is_drawn_and_picked_in_the_library_index(self):
        for prefix, fam, src in (("LIB_NX_", "nx", "LibNumbersPro.tsx"), ("LIB_TX_", "tx", "LibTextPro.tsx")):
            variants = {t["defaults"]["variant"] for t in family(prefix)}
            self.assertEqual(variants, ts_looks(src, fam))
            self.assertEqual(variants, index_picks(fam))
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        self.assertIn('from "./LibNumbersPro"', index)
        self.assertIn('from "./LibTextPro"', index)

    def test_props_are_the_editors_and_figures_place_themselves(self):
        known = set(_build_registry().P)
        for t in family("LIB_NX_") + family("LIB_TX_"):
            self.assertTrue(set(t["props"]) <= known, t["id"])
            self.assertIn("text", t["props"], t["id"])
            self.assertEqual(treatments.look_slots(t), (0, 0), t["id"])
        for t in family("LIB_NX_"):
            for cue in templates.cues_of(t):
                if cue in treatments.SINGLE_FIGURE_CUES:
                    # One figure on the clip: the look places itself, never shrunk into a corner.
                    self.assertEqual(t["kind"], "tag", (t["id"], cue))
                    ov = {}
                    treatments.apply_layout(ov, t, treatments.layout_class(t, cue))
                    self.assertEqual(ov, {}, (t["id"], cue))

    def test_the_family_lists_are_the_registrys(self):
        br = _build_registry()
        files = br.library_files()
        for fam in ("nx", "tx"):
            path = os.path.join(ROOT, "scripts", f"library_looks_{fam}.json")
            self.assertIn(os.path.normpath(path), [os.path.normpath(p) for p in files])
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
            listed = {"LIB_" + e["id"].upper().replace("-", "_") for e in rows}
            self.assertEqual(listed, {t["id"] for t in family(f"LIB_{fam.upper()}_")})
            for e in rows:
                self.assertIs(e.get("auto_pick"), False, e["id"])
                self.assertTrue(e.get("sample"), e["id"])
        # Rebuilding the registry from the lists changes nothing (the committed registry is the built one).
        with open(templates.PATH, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual([t["id"] for t in br.build()["templates"]], [t["id"] for t in committed["templates"]])


class NeverOnItsOwn(unittest.TestCase):
    def test_every_new_look_waits_for_the_owner(self):
        for t in family("LIB_NX_") + family("LIB_TX_"):
            self.assertIs(t.get("autoPick"), False, t["id"])
            self.assertFalse(treatments.auto_ok(t["id"]), t["id"])
        self.assertTrue(treatments.auto_ok("LIB_BT_COUNT"))
        self.assertTrue(treatments.auto_ok("LIB_CT_RING_PRO"))

    def test_no_planned_video_shows_them(self):
        out = small(EVERY_CUE)
        picked = [o["template"] for o in out["overlays"]]
        self.assertTrue(picked)
        self.assertFalse([t for t in picked if t.startswith(NEW)], picked)
        for line in EVERY_CUE:
            seg = Segment(text=line, start=0.0, end=6.0)
            got = treatments.animation_for(seg, dict(PLACE), treatments.pack_for({}, "documentary"), {})
            self.assertFalse(got and str(got.get("template", "")).startswith(NEW), (line, got))

    def test_while_they_wait_a_video_is_what_it_was(self):
        # The same script planned as if the new looks and the new contrast cue did not exist: the same overlays.
        real_for_cue = templates.for_cue

        def without(cue, style="", exclude=None):
            return [t for t in real_for_cue(cue, style, exclude) if not t["id"].startswith(NEW)]
        got = small(EVERY_CUE)
        treatments._reset_rotation()
        with mock.patch.object(templates, "for_cue", side_effect=without), \
                mock.patch.object(treatments, "contrast_line", return_value=None):
            before = small(EVERY_CUE)
        strip = lambda ovs: [{k: v for k, v in o.items() if k != "media"} for o in ovs]  # noqa: E731
        self.assertEqual(strip(got["overlays"]), strip(before["overlays"]))

    def test_the_other_automatic_paths_skip_them_too(self):
        for cue in ("percent", "money", "quote", "headline", "question", "warning", "person", "figure-record"):
            self.assertFalse([x for x in treatments._lib_looks(cue, still=False) if x.startswith(NEW)], cue)


class Hooks(unittest.TestCase):
    def test_the_line_says_what_the_figure_is(self):
        self.assertEqual(treatments.figure_line_cues(RECORD, "change-length", {"value": 3519.0})[0], "figure-record")
        self.assertEqual(treatments.figure_line_cues(RATE, "big-number", {"value": 110.0})[0], "figure-rate")
        self.assertEqual(treatments.figure_line_cues(SHARE, "percent", {"value": 22.0}), ["figure-share"])
        self.assertEqual(treatments.figure_line_cues(CONTEXT, "big-number", {"value": 40.0}), ["figure-context"])
        self.assertEqual(treatments.figure_line_cues("Water levels dropped another 12 feet this year.", "change-length",
                                                     {"value": 12.0}), [])
        self.assertEqual(treatments.figure_line_cues(QUESTION, "question", {}), [])

    def test_only_the_lines_own_words_reach_the_look(self):
        self.assertEqual(treatments.figure_line_props(RECORD, {"value": 3519.0}, "figure-record"),
                         {"label": "LOWEST LEVEL SINCE THE DAM WAS FILLED"})
        self.assertEqual(treatments.figure_line_props(RATE, {"value": 110.0}, "figure-rate"),
                         {"label": "PER PERSON", "subtitle": "EVERY DAY"})
        got = treatments.figure_line_props("Twenty-two percent of the lake is gone.", {"value": 22.0}, "figure-context")
        self.assertEqual(got, {"subtitle": "of the lake is gone", "highlight": "22% of the lake is gone"})
        self.assertEqual(treatments.figure_line_props("Twenty-two percent of the lake is gone.", {"value": 22.0},
                                                      "figure-share"), {"text": "OF THE LAKE IS GONE"})
        self.assertEqual(treatments.quote_line_props(OFFICIAL), {"label": "Reclamation officials", "subtitle": "In a statement"})
        self.assertEqual(treatments.quote_line_props(QUOTED), {"label": "Bureau of Reclamation official"})
        self.assertEqual(treatments.quote_line_props("The water simply stopped arriving."), {})
        self.assertEqual(treatments.contrast_line(TURN), ("This is not a drought", "It's the new normal"))
        self.assertEqual(treatments.contrast_line("It wasn't a mistake, but it was a choice."),
                         ("It wasn't a mistake", "It was a choice"))
        self.assertIsNone(treatments.contrast_line(PLAIN))
        for text, cue in ((RECORD, "figure-record"), (RATE, "figure-rate"), (CONTEXT, "figure-context")):
            said = treatments.numwords.normalize(text).upper()
            for v in treatments.figure_line_props(text, {"value": 3519.0 if text == RECORD else 110.0 if text == RATE else 40.0},
                                                  cue).values():
                self.assertIn(str(v).upper(), said, (cue, v))

    def test_switched_on_the_line_chooses_the_look(self):
        lines = [RECORD, PLAIN, RATE, PLAIN, SHARE, PLAIN, OFFICIAL, PLAIN, TURN, PLAIN]
        with mock.patch.object(treatments, "auto_ok", side_effect=on(treatments.auto_ok)):
            out = small(lines)
        by_beat = {}
        for o in out["overlays"]:
            by_beat.setdefault(o["startFrame"] // (12 * FPS), o)
        self.assertEqual(by_beat[0]["template"], "LIB_NX_RECORD_FLOOR")
        self.assertEqual(by_beat[0]["label"], "LOWEST LEVEL SINCE THE DAM WAS FILLED")
        self.assertEqual(by_beat[2]["template"], "LIB_NX_RATE_FRACTION")
        self.assertEqual(by_beat[2]["label"], "PER PERSON")
        self.assertEqual(by_beat[4]["template"], "LIB_NX_FRAME_SHARE")
        self.assertEqual(by_beat[4]["value"], 22.0)
        self.assertEqual(by_beat[6]["template"], "LIB_TX_STATEMENT_CARD")
        self.assertEqual(by_beat[6]["label"], "Reclamation officials")                 # who the line says spoke
        self.assertEqual(by_beat[8]["template"], "LIB_TX_CONTRAST")
        self.assertEqual([i["label"] for i in by_beat[8]["items"]], ["This is not a drought", "It's the new normal"])
        for o in out["overlays"]:
            if o["template"].startswith("LIB_NX_"):
                self.assertNotIn("compact", o)                                          # never shrunk into a corner

    def test_switched_on_a_quote_never_names_the_subject_as_its_speaker(self):
        with mock.patch.object(treatments, "auto_ok", side_effect=on(treatments.auto_ok)):
            out = small([QUOTED, PLAIN, "\"It is the end of an era,\" he said.", PLAIN])
        for o in out["overlays"]:
            if o["template"].startswith("LIB_TX_"):
                self.assertNotEqual(o.get("label"), "Lake Powell", o)


# --------------------------------------------------------------------------- digits (nxFormat.ts in node)
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { drawnOf, figureOf, plainOf, fmt } from "%(fmt)s";
import * as fs from "fs";
const cases = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = cases.map((c: any) => {
  const f = figureOf(c.ov, Boolean(c.money));
  return { drawn: f.value === null ? null : plainOf(drawnOf(f, Boolean(c.money))), label: f.label, value: f.value };
});
process.stdout.write(JSON.stringify({ out, fmt: [fmt(1963, 0, true), fmt(3517, 0), fmt(1.2, 2), fmt(-12.5, 1), fmt(26.10, 2)] }));
"""
DIGIT_CASES = [
    ({"value": 4200000000, "prefix": "$"}, True, "$4.2 BILLION"),
    ({"value": 4.2, "prefix": "$", "suffix": "B"}, True, "$4.2 BILLION"),
    ({"value": 1.2, "prefix": "$", "suffix": "BILLION"}, True, "$1.2 BILLION"),
    ({"value": 3517, "suffix": "FT"}, False, "3,517 FT"),
    ({"value": 22, "suffix": "%"}, False, "22%"),
    ({"value": 110, "suffix": "GAL"}, False, "110 GALLONS"),
    ({"value": 186, "suffix": "MI"}, False, "186 MILES"),
    ({"value": 40, "suffix": "MILLION"}, False, "40 MILLION"),
    ({"value": 1963}, False, "1963"),
    ({"value": 26.1}, False, "26.1"),
    ({"value": 75000000, "suffix": "ACRE-FT"}, False, "75,000,000 ACRE-FEET"),
    ({"text": "forty million people"}, False, "40 MILLION"),
    ({"text": "two point five inches of rain"}, False, "2.5 INCHES"),
    ({"text": "twenty-two percent of the lake"}, False, "22%"),
    ({"text": "No number here"}, False, None),
]


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Digits(unittest.TestCase):
    """Every figure in digits with its unit as said (remotion/src/components/lib/nxFormat.ts)."""

    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "digits.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"fmt": os.path.join(LIB, "nxFormat").replace("\\", "/")})
        cls.bundle = os.path.join(cls.dir, "digits.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_figures_are_digits_with_their_unit_as_said(self):
        run = subprocess.run([self.node, self.bundle], input=json.dumps([{"ov": ov, "money": m} for ov, m, _ in DIGIT_CASES]),
                             capture_output=True, text=True, timeout=60, check=True)
        got = json.loads(run.stdout)
        for (ov, _m, want), res in zip(DIGIT_CASES, got["out"]):
            self.assertEqual(res["drawn"], want, ov)
            if res["drawn"]:
                self.assertFalse(re.search(r"[a-z]", res["drawn"]), res)                 # never a spelled-out number
        self.assertEqual(got["out"][11]["label"], "PEOPLE")                              # what it counts, the number out
        self.assertEqual(got["fmt"], ["1963", "3,517", "1.2", "-12.5", "26.1"])


# --------------------------------------------------------------------------- sounds
SOUND_NAME = re.compile(r'name:\s*"([a-z0-9-]+)"')


class Sounds(unittest.TestCase):
    def test_each_sounds_from_its_own_frames(self):
        for t in family("LIB_NX_") + family("LIB_TX_"):
            d = t["defaults"]
            self.assertEqual(d.get("soundTiming"), "look", t["id"])      # the component schedules them (useLookSound)
            self.assertFalse(d.get("ownSound"), t["id"])
            self.assertTrue(d["sounds"], t["id"])
            for c in d["sounds"]:
                self.assertIsNotNone(sfxplan.resolve_sound(c["name"], c.get("alt")), (t["id"], c))
                self.assertNotIn(c["name"], PUNCHES, t["id"])
                self.assertFalse(set(c.get("alt") or []) & PUNCHES, t["id"])
                self.assertLessEqual(c.get("gain_db", 0), 0, t["id"])

    def test_a_number_only_ticks(self):
        for t in family("LIB_NX_"):
            d = t["defaults"]
            with_value = [c for c in d["sounds"] if c.get("when") != "no-value"]
            self.assertTrue(with_value, t["id"])
            for c in with_value:
                self.assertIn(c["name"], ("ui-tick", "count-final"), t["id"])
            final = [c for c in with_value if c["name"] == "count-final"]
            self.assertEqual([c["at"] for c in final], [d["sfxAt"]], t["id"])          # the click on the landing

    def test_the_components_play_only_soft_shipped_sounds(self):
        for name in ("LibNumbersPro.tsx", "LibTextPro.tsx", "nxKit.tsx"):
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                names = set(SOUND_NAME.findall(fh.read()))
            self.assertTrue(names, name)
            for n in names:
                self.assertIsNotNone(sfxplan.resolve_sound(n, []), (name, n))
                self.assertNotIn(n, PUNCHES, (name, n))

    def test_scheduled_under_the_voice_and_inside_the_look(self):
        for t in family("LIB_NX_") + family("LIB_TX_"):
            d = t["defaults"]
            default = int(round(d["duration"] * FPS))
            for frames in (default, 75):
                got = sfxplan.look_sounds(d["sounds"], fps=FPS, frames=frames, default_frames=default, text="x" * 20,
                                          value=22.0 if t["id"].startswith("LIB_NX_") else None)
                self.assertTrue(got, (t["id"], frames))
                for s in got:
                    self.assertGreaterEqual(s["from"], 0, t["id"])
                    self.assertLessEqual(s["from"] + s["frames"], frames, t["id"])
                    cap = min(1.0, 10 ** (-sfxplan.ceiling_db(s["name"]) / 20.0))
                    self.assertLessEqual(s["volume"], cap + 1e-6, (t["id"], s))
                    self.assertGreater(s["volume"], 0.0, t["id"])

    def test_the_typed_lower_third_keeps_the_typing_contract(self):
        t = templates.get("LIB_TX_TYPEWRITER_LOWER")
        self.assertTrue(templates.types(t))
        self.assertEqual(t["defaults"]["sfxAt"], treatments.TYPE_START)
        self.assertIn(t, templates.for_cue("typewriter"))


if __name__ == "__main__":
    unittest.main()
