"""The video's grade: settings and tones (src/grade.py), the renderer's math (gradeMath.ts), chunk reuse."""
import copy
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, fanout, grade

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
MATH_TS = os.path.join(REMOTION, "src", "components", "gradeMath.ts")


def _tone(l=0.45, s=0.18, rg=1.05, bg=0.95, lo=0.05, hi=0.92):
    return {"l": l, "lo": lo, "hi": hi, "s": s, "rg": rg, "bg": bg, "v": grade.TONE_VERSION}


def _doc(tones, treatments=None):
    scenes = []
    for i, t in enumerate(tones):
        m = {"type": "video" if i % 2 else "image", "url": f"https://x/{i}.mp4",
             "storage": {"bucket": "b", "path": f"p/{i}"}}
        if t is not None:
            m["tone"] = t
        scenes.append({"id": f"s{i:04d}", "startFrame": 100 * i, "durationInFrames": 100, "text": str(i),
                       "treatment": (treatments or {}).get(i, "none"), "transition": "none", "media": m})
    return {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 100 * len(scenes), "scenes": scenes,
            "overlays": [], "captions": {"enabled": False}}


class Settings(unittest.TestCase):
    def test_the_presets_match_the_renderer(self):
        with open(MATH_TS, encoding="utf-8") as fh:
            src = fh.read()
        listed = re.search(r"GRADE_PRESETS = \[([^\]]*)\]", src).group(1)
        self.assertEqual(tuple(re.findall(r'"([a-z-]+)"', listed)), grade.PRESETS)
        for p in grade.PRESETS:
            self.assertRegex(src, rf'\n  "?{re.escape(p)}"?: ')

    def test_a_plan_without_a_grade_gets_the_default_and_an_editors_grade_is_kept(self):
        doc = _doc([_tone()])
        with mock.patch.object(config, "GRADE", True):
            self.assertTrue(grade.ensure(doc))
        self.assertEqual(doc["grade"], {"preset": "documentary", "strength": 1.0, "normalize": True})
        doc["grade"] = {"preset": "cool-news", "strength": 0.5}
        with mock.patch.object(config, "GRADE", True):
            self.assertFalse(grade.ensure(doc))
        self.assertEqual(doc["grade"], {"preset": "cool-news", "strength": 0.5, "normalize": True})

    def test_off_switch_none_and_bad_values(self):
        doc = _doc([_tone()])
        with mock.patch.object(config, "GRADE", False):
            self.assertFalse(grade.ensure(doc))
        self.assertNotIn("grade", doc)
        doc["grade"] = None                         # the editor turned it off: stays off
        with mock.patch.object(config, "GRADE", True):
            grade.ensure(doc)
        self.assertIsNone(doc["grade"])
        doc["grade"] = {"preset": "teal-orange", "strength": 7}
        grade.ensure(doc)
        self.assertEqual(doc["grade"]["preset"], "documentary")
        self.assertEqual(doc["grade"]["strength"], 1.0)

    def test_frozen_medians_survive_the_cleaning(self):
        doc = _doc([_tone()])
        doc["grade"] = {"preset": "documentary", "medians": {"l": 0.41, "s": 0.2, "rg": 1.1, "bg": 0.9, "n": 40}}
        grade.ensure(doc)
        self.assertEqual(doc["grade"]["medians"]["l"], 0.41)


class Tone(unittest.TestCase):
    def test_tone_of_a_grey_and_a_warm_frame(self):
        grey = bytes([128, 128, 128]) * (grade.SAMPLE_W * grade.SAMPLE_H)
        t = grade.tone_of([grey])
        self.assertAlmostEqual(t["l"], 128 / 255, places=2)
        self.assertEqual(t["s"], 0.0)
        self.assertEqual((t["rg"], t["bg"]), (1.0, 1.0))
        warm = bytes([180, 120, 80]) * (grade.SAMPLE_W * grade.SAMPLE_H)
        t = grade.tone_of([warm])
        self.assertGreater(t["rg"], 1.4)
        self.assertLess(t["bg"], 0.7)
        self.assertAlmostEqual(t["s"], 100 / 255, places=2)

    def test_medians_skip_archival_grey_and_unmeasured_scenes(self):
        tones = [_tone(l=0.3), _tone(l=0.5), _tone(l=0.6), _tone(l=0.9, s=0.01), None, _tone(l=0.1)]
        doc = _doc(tones, treatments={5: "archival"})
        m = grade.medians(doc)
        self.assertEqual(m["n"], 3)
        self.assertEqual(m["l"], 0.5)
        self.assertIsNone(grade.medians(_doc([_tone(), _tone()])))


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class Measure(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _file(self, name, lavfi, *extra):
        path = os.path.join(self.dir, name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", lavfi, *extra, path], check=True)
        return path

    def test_a_dark_clip_and_a_bright_photo(self):
        clip = self._file("dark.mp4", "color=c=0x202830:s=320x180:d=2", "-pix_fmt", "yuv420p")
        photo = self._file("bright.jpg", "color=c=0xE0D8C8:s=320x180", "-frames:v", "1")
        dark = grade.measure({"type": "video", "url": clip, "clipSeconds": 2.0})
        bright = grade.measure({"type": "image", "url": photo})
        self.assertLess(dark["l"], 0.2)
        self.assertGreater(bright["l"], 0.75)
        self.assertGreater(dark["bg"], 1.0)          # a blue-ish night
        self.assertGreater(bright["rg"], 1.0)        # a warm paper
        self.assertIsNone(grade.measure({"type": "video", "url": os.path.join(self.dir, "missing.mp4")}))

    def test_prepare_measures_freezes_the_medians_and_a_later_replace_keeps_them(self):
        files = [self._file(f"c{i}.jpg", f"color=c={c}:s=160x90", "-frames:v", "1")
                 for i, c in enumerate(("0x806040", "0x705848", "0x907050", "0x404858"))]
        doc = _doc([None] * 4)
        for sc, f in zip(doc["scenes"], files):
            sc["media"] = {"type": "image", "url": f}
        with mock.patch.object(config, "GRADE", True):
            rep = grade.prepare(doc, remote=False, budget=30)
        self.assertEqual(rep["measured"], 4)
        frozen = dict(doc["grade"]["medians"])
        self.assertEqual(frozen["n"], 4)
        doc["scenes"][0]["media"] = {"type": "image", "url": self._file("new.jpg", "color=c=0x2040A0:s=160x90",
                                                                         "-frames:v", "1")}
        grade.prepare(doc, remote=False, budget=30)
        self.assertIn("tone", doc["scenes"][0]["media"])
        self.assertEqual(doc["grade"]["medians"], frozen)


class ChunkReuse(unittest.TestCase):
    def test_the_grade_and_a_scenes_tone_change_its_chunks(self):
        doc = _doc([_tone(), _tone(), _tone()])
        doc["grade"] = {"preset": "documentary", "strength": 1.0, "normalize": True}
        same = fanout.chunk_hash(copy.deepcopy(doc), 0, 299)
        self.assertEqual(fanout.chunk_hash(doc, 0, 299), same)
        stronger = copy.deepcopy(doc)
        stronger["grade"]["strength"] = 0.5
        self.assertNotEqual(fanout.chunk_hash(stronger, 0, 299), same)
        retoned = copy.deepcopy(doc)
        retoned["scenes"][2]["media"]["tone"] = _tone(l=0.2)
        self.assertNotEqual(fanout.chunk_hash(retoned, 200, 299), fanout.chunk_hash(doc, 200, 299))
        self.assertEqual(fanout.chunk_hash(retoned, 0, 99), fanout.chunk_hash(doc, 0, 99))
        with mock.patch.object(fanout, "_renderer_id", return_value="older-code"):
            self.assertNotEqual(fanout.chunk_hash(doc, 0, 299), same)


# --------------------------------------------------------------------------- the renderer's math under node
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { sceneGrade, gradeMedians, LOOKS, lookCurve, TABLE_SIZE } from "%(math)s";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = {
  medians: input.docs.map((d: any) => gradeMedians(d.scenes)),
  grades: input.cases.map((c: any) => sceneGrade(c.scene, c.settings, c.medians)),
  curves: Object.fromEntries(Object.entries(LOOKS).filter(([, l]) => l)
    .map(([k, l]) => [k, Array.from({ length: 101 }, (_, i) => lookCurve(i / 100, l as any, 1))])),
  size: TABLE_SIZE,
};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class RendererMath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"math": MATH_TS.replace("\\", "/")[:-3]})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, docs=(), cases=()):
        run = subprocess.run([self.node, self.bundle], input=json.dumps({"docs": list(docs), "cases": list(cases)}),
                             capture_output=True, text=True, timeout=60, check=True)
        return json.loads(run.stdout)

    def test_the_medians_twins_agree(self):
        rnd = random.Random(7)
        docs = []
        for n in (2, 3, 4, 9, 40):
            tones = [_tone(l=rnd.uniform(0.05, 0.9), s=rnd.uniform(0.0, 0.4), rg=rnd.uniform(0.8, 1.3),
                           bg=rnd.uniform(0.7, 1.2)) for _ in range(n)]
            docs.append(_doc(tones, treatments={0: "vintage"}))
        got = self._run(docs=docs)["medians"]
        for d, m in zip(docs, got):
            self.assertEqual(m, grade.medians(d))

    def test_the_looks_never_crush_the_blacks_or_clip_the_whites(self):
        curves = self._run()["curves"]
        self.assertEqual(curves["neutral"], [i / 100 for i in range(101)])
        for name, ys in curves.items():
            self.assertTrue(all(b >= a for a, b in zip(ys, ys[1:])), name)          # monotonic
            self.assertGreaterEqual(ys[0], 0.0, name)
            self.assertLessEqual(ys[-1], 1.0, name)
            if name != "neutral":
                self.assertGreater(ys[0], 0.005, name)                            # black lifted, not crushed
                self.assertLess(ys[-1], 0.995, name)                              # white rolled off
            for i in range(31):                                                   # no shadow pulled down
                self.assertGreaterEqual(ys[i], i / 100 - 0.012, (name, i))

    def test_none_and_zero_strength_draw_nothing_and_the_default_is_gentle(self):
        scene = {"media": {"type": "video", "tone": _tone()}}
        none, zero, doc = self._run(cases=[{"scene": scene, "settings": {"preset": "none"}, "medians": None},
                                           {"scene": scene, "settings": {"strength": 0}, "medians": None},
                                           {"scene": scene, "settings": {}, "medians": None}])["grades"]
        self.assertIsNone(none)
        self.assertIsNone(zero)
        size = self._run()["size"]
        for c in ("r", "g", "b"):
            for i, v in enumerate(doc[c]):
                self.assertLess(abs(v - i / (size - 1)), 0.03, (c, i))           # a touch, not a look
        self.assertAlmostEqual(doc["sat"], 0.97)
        graphic = self._run(cases=[{"scene": {"media": {"type": "animation"}}, "settings": {}, "medians": None}])
        self.assertIsNone(graphic["grades"][0])

    def test_a_scene_is_pulled_toward_the_videos_median(self):
        med = {"l": 0.42, "s": 0.2, "rg": 1.05, "bg": 0.95, "n": 50}
        dark = {"media": {"type": "video", "tone": _tone(l=0.2, s=0.1, rg=0.95, bg=1.1)}}
        bright = {"media": {"type": "image", "tone": _tone(l=0.7, s=0.3)}}
        typical = {"media": {"type": "video", "tone": _tone(l=0.42, s=0.2)}}
        old = {"treatment": "archival", "media": {"type": "video", "tone": _tone(l=0.42, s=0.2, rg=0.8, bg=1.3)}}
        settings = {"preset": "neutral"}
        g_dark, g_bright, g_typ, g_old = self._run(cases=[{"scene": s, "settings": settings, "medians": med}
                                                          for s in (dark, bright, typical, old)])["grades"]
        mid = len(g_dark["g"]) // 2
        self.assertGreater(g_dark["g"][mid], 0.5)          # lifted
        self.assertLess(g_bright["g"][mid], 0.5)           # brought down
        self.assertGreater(g_dark["sat"], 1.0)             # dull clip: more colour
        self.assertLess(g_bright["sat"], 1.0)              # loud clip: less
        self.assertGreater(g_dark["r"][mid], g_dark["b"][mid])   # its blue cast: blue lowered against red
        self.assertIsNone(g_typ)                           # nothing to correct, no look: no filter
        self.assertEqual(g_old["sat"], 1.0)                # an archival scene keeps its colour
        self.assertEqual(g_old["r"], g_old["b"])
        for g in (g_dark, g_bright):
            self.assertGreaterEqual(g["g"][0], 0.0)
            self.assertLessEqual(max(g["r"] + g["g"] + g["b"]), 1.0)


if __name__ == "__main__":
    unittest.main()
