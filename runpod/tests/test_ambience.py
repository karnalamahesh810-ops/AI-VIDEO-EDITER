"""Ambience beds and risers (src/ambience.py), their files, and the renderer's mix (ambienceMix.ts)."""
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src import ambience, config, sfxplan, timeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
SFX = os.path.join(REMOTION, "public", "sfx")
MIX_TS = os.path.join(REMOTION, "src", "components", "ambienceMix.ts")
FPS = 30


def _scene(i, start, seconds, desc="", text="", media="video", query="", words=None):
    return {"id": f"s{i:04d}", "startFrame": start, "durationInFrames": int(seconds * FPS), "text": text, "query": query,
            "media": {"type": media, "url": f"https://x/{i}"}, "semanticMetadata": {"contentDescription": desc},
            "words": words or []}


def _doc(specs, overlays=None, sfx=None, story=None):
    scenes, f = [], 0
    for i, spec in enumerate(specs):
        sc = _scene(i, f, *spec)
        scenes.append(sc)
        f += sc["durationInFrames"]
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": f, "scenes": scenes,
            "overlays": overlays or [], "sfx": sfx or [], "meta": {"voiceLufs": -20.0, **({"story": story} if story else {})}}


class Files(unittest.TestCase):
    def test_every_bed_ships_as_a_seamless_minute_with_its_levels(self):
        with open(os.path.join(SFX, "sfx_meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        for bed in ambience.BEDS:
            name = ambience.FILE_PREFIX + bed
            self.assertTrue(os.path.isfile(os.path.join(SFX, name + ".mp3")), name)
            m = meta[name]
            self.assertEqual((m["category"], m["loop"]), ("ambience", True), name)
            self.assertAlmostEqual(m["duration"], 60.0, delta=0.01)
            self.assertAlmostEqual(m["lufsIntegrated"], -24.0, delta=0.5)
            self.assertLess(m["peakDb"], -3.0)
        r = meta[ambience.RISER]
        self.assertEqual((r["category"], r["loop"]), ("riser", False))
        self.assertAlmostEqual(r["peak"], 1.6)
        self.assertTrue(sfxplan.exists(ambience.RISER))

    def test_the_synthesiser_makes_exactly_the_planners_beds(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        try:
            import build_ambience
        finally:
            sys.path.pop(0)
        self.assertEqual(tuple(build_ambience.BEDS), ambience.BEDS)
        self.assertEqual(build_ambience.RISER, ambience.RISER)


class Places(unittest.TestCase):
    def test_what_the_frames_show_decides_the_bed(self):
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Aerial view of a lake winding through red canyons")), "wind")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Houseboats tied up at a marina dock on the lake")), "water")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Brown water rushing through a spillway, a river in flood")),
                         "river")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Lightning over a town during a thunderstorm, heavy rain")),
                         "storm")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Traffic on a downtown street at night")), "city")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "A crowd of protesters at a rally")), "crowd")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Firefighters in front of a burning hillside, flames")), "fire")
        self.assertEqual(ambience.scene_bed(_scene(0, 0, 5, "Turbines inside the dam's powerhouse")), "machinery")

    def test_no_bed_for_graphics_documents_maps_or_nowhere(self):
        self.assertIsNone(ambience.scene_bed(_scene(0, 0, 5, "A National Park Service notice, text reads closed")))
        self.assertIsNone(ambience.scene_bed(_scene(0, 0, 5, "A satellite image of the reservoir with labels")))
        self.assertIsNone(ambience.scene_bed(_scene(0, 0, 5, "", "the lake is falling", media="animation")))
        self.assertIsNone(ambience.scene_bed(_scene(0, 0, 5, "Two men shaking hands in an office")))


def _overlap(beds):
    spans = sorted((b["startFrame"], b["startFrame"] + b["durationInFrames"]) for b in beds)
    return any(a1 < b0 for (_a0, b0), (a1, _b1) in zip(spans, spans[1:]))


class Beds(unittest.TestCase):
    def test_one_bed_at_a_time_long_enough_faded_and_under_the_voice(self):
        doc = _doc([(6, "Aerial view of canyon cliffs")] * 4 + [(4, "A satellite map of the basin")]
                   + [(6, "Aerial of desert mesas")] * 2 + [(7, "Boats at the marina, waves on the shore")] * 3
                   + [(3, "A river in a canyon")] + [(7, "Waves lapping on the beach")] * 2)
        beds = ambience.plan_beds(doc, -20.0)
        self.assertFalse(_overlap(beds))
        self.assertEqual([b["name"] for b in beds], ["amb-wind", "amb-water"])
        for b in beds:
            self.assertGreaterEqual(b["durationInFrames"], ambience.MIN_BED_SECONDS * FPS)
            self.assertEqual(b["fadeIn"], FPS)
            self.assertEqual(b["fadeOut"], int(round(1.2 * FPS)))
        # The map between the canyon shots did not break the wind; the river shot did not interrupt the shore.
        self.assertEqual(beds[0]["durationInFrames"], (6 * 4 + 4 + 12) * FPS)
        loud = sfxplan._meta()["amb-wind"]["lufsIntegrated"]
        self.assertAlmostEqual(20 * __import__("math").log10(beds[0]["volume"]), -20.0 - 26.0 - loud, delta=0.05)
        self.assertGreater(beds[0]["ceiling"], beds[0]["volume"])

    def test_a_crowd_sits_further_under_the_voice(self):
        doc = _doc([(8, "A crowd of protesters at a rally")] * 3)
        crowd = ambience.plan_beds(doc, -20.0)[0]
        expect = 10 ** ((-20.0 - 26.0 - ambience.EXTRA_UNDER_DB["crowd"]
                         - sfxplan._meta()["amb-crowd"]["lufsIntegrated"]) / 20.0)
        self.assertAlmostEqual(crowd["volume"], round(expect, 4), places=4)

    def test_a_full_screen_graphic_is_a_hole_in_the_bed(self):
        doc = _doc([(6, "Aerial of canyon cliffs")] * 2 + [(5, "", "", "animation")] + [(6, "Aerial of mesas")] * 2)
        doc["overlays"] = [{"type": "chapter", "text": "PART TWO", "startFrame": 2 * 6 * FPS + 5 * FPS + 30,
                            "durationInFrames": 60}]
        bed = ambience.plan_beds(doc, -20.0)[0]
        self.assertEqual(bed["durationInFrames"], 29 * FPS)
        self.assertIn([12 * FPS, 17 * FPS], bed["holes"])
        self.assertIn([17 * FPS + 30, 17 * FPS + 90], bed["holes"])

    def test_settling_always_ends_with_long_single_beds(self):
        rnd = random.Random(3)
        names = [None, "wind", "water", "city"]
        for _ in range(200):
            n = rnd.randint(1, 40)
            labels = [rnd.choice(names) for _ in range(n)]
            lengths = [rnd.randint(30, 300) for _ in range(n)]
            kept = ambience._settle(labels, lengths, FPS)
            for lab, a, b in kept:
                self.assertIsNotNone(lab)
                self.assertGreaterEqual(sum(lengths[a:b + 1]), ambience.MIN_BED_SECONDS * FPS)
            for (_l, _a, b0), (_m, a1, _b) in zip(kept, kept[1:]):
                self.assertLess(b0, a1)


def _figure(start, emph="high", template="LIB_BT_COUNT"):
    return {"type": "motion", "template": template, "text": "3,490 FT", "value": 3490, "emphasis": emph,
            "startFrame": start, "durationInFrames": 90}


class Risers(unittest.TestCase):
    def _doc(self, overlays=(), sfx=(), seconds=180):
        doc = _doc([(10, "Aerial of canyon cliffs")] * (seconds // 10), overlays=list(overlays), sfx=list(sfx))
        return doc

    def test_a_big_figure_gets_a_swell_peaking_on_its_hit(self):
        doc = self._doc([_figure(60 * FPS)])
        rows = ambience.plan_risers(doc, -20.0)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        hit = 60 * FPS + int(round(40 * FPS / 30))          # LIB_BT_COUNT's sfxAt
        self.assertEqual(r["startFrame"] + sfxplan.peak_frames(ambience.RISER, FPS), hit)
        self.assertEqual((r["name"], r["kind"]), (ambience.RISER, "riser"))
        self.assertAlmostEqual(r["volume"], round(sfxplan.level(ambience.RISER, -20.0) * 10 ** (-3 / 20), 3))

    def test_no_swell_over_another_sound_or_on_a_quiet_figure(self):
        busy = self._doc([_figure(60 * FPS)], sfx=[{"name": "whoosh-soft", "startFrame": 60 * FPS + 10, "volume": 0.3}])
        self.assertEqual(ambience.plan_risers(busy, -20.0), [])
        low = self._doc([_figure(60 * FPS, emph="medium")])
        self.assertEqual(ambience.plan_risers(low, -20.0), [])

    def test_swells_are_rare(self):
        doc = self._doc([_figure(s * FPS) for s in range(20, 170, 15)])
        rows = ambience.plan_risers(doc, -20.0)
        peaks = sorted(r["startFrame"] for r in rows)
        self.assertLessEqual(len(rows), max(1, int(ambience.RISERS_PER_MINUTE * 3)))
        self.assertTrue(all(b - a >= ambience.RISER_GAP_SECONDS * FPS for a, b in zip(peaks, peaks[1:])))

    def test_a_new_section_peaks_on_its_first_word(self):
        doc = self._doc()
        doc["scenes"][9]["words"] = [{"text": "But", "start": 91.2, "end": 91.5}]
        doc["meta"]["story"] = {"sections": [{"from": 0, "to": 8}, {"from": 9, "to": 17}]}
        rows = ambience.plan_risers(doc, -20.0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["startFrame"] + sfxplan.peak_frames(ambience.RISER, FPS), int(round(91.2 * FPS)))


class Document(unittest.TestCase):
    def test_switches(self):
        doc = _doc([(8, "Aerial of canyon cliffs")] * 3, overlays=[_figure(10 * FPS)])
        with mock.patch.object(config, "AMBIENCE", False), mock.patch.object(config, "RISERS", False):
            self.assertEqual(ambience.apply(doc), {"beds": 0, "risers": 0})
        self.assertNotIn("ambience", doc)
        with mock.patch.object(config, "AMBIENCE", True), mock.patch.object(config, "RISERS", True):
            got = ambience.apply(doc)
        self.assertEqual(got["beds"], 1)
        self.assertEqual(doc["ambience"]["enabled"], True)
        self.assertEqual(doc["ambience"]["level"], 1.0)

    def test_a_quieter_voice_at_render_brings_beds_and_swells_down(self):
        doc = _doc([(8, "Aerial of canyon cliffs")] * 3)
        doc["audio"] = {"url": "https://x/n.mp3"}
        doc["meta"].update(voiceLufs=-16.0, voiceLufsSource="assumed")
        doc["ambience"] = {"enabled": True, "level": 1.0, "beds": [{"name": "amb-wind", "startFrame": 0,
                                                                    "durationInFrames": 600, "volume": 0.2,
                                                                    "ceiling": 0.5}]}
        doc["sfx"] = [{"name": ambience.RISER, "startFrame": 100, "volume": 0.4, "kind": "riser"}]
        self.assertTrue(timeline.relevel_to_voice(doc, measure=lambda url: -22.0))
        self.assertAlmostEqual(doc["ambience"]["beds"][0]["volume"], 0.1002, places=3)
        self.assertAlmostEqual(doc["sfx"][0]["volume"], 0.2, places=2)

    def test_beds_the_renderer_cannot_play_are_dropped(self):
        doc = _doc([(8, "x")] * 3)
        doc["ambience"] = {"beds": [{"name": "amb-wind", "startFrame": 0, "durationInFrames": 300, "volume": 0.1},
                                    {"name": "amb-nowhere", "startFrame": 0, "durationInFrames": 300, "volume": 0.1},
                                    {"name": "amb-rain", "startFrame": 0, "durationInFrames": 300, "volume": 7},
                                    {"name": "whoosh", "startFrame": 0, "durationInFrames": 300, "volume": 0.1}]}
        self.assertEqual(ambience.clean(doc), 3)
        self.assertEqual([b["name"] for b in doc["ambience"]["beds"]], ["amb-wind"])

    def test_the_renderer_plays_the_beds(self):
        with open(os.path.join(REMOTION, "src", "Main.tsx"), encoding="utf-8") as fh:
            main = fh.read()
        self.assertIn("props.ambience", main)
        self.assertIn("sfx/${b.name}.mp3", main)
        self.assertIn("loopVolumeCurveBehavior=\"extend\"", main)


def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { ambienceSettings, bedPasses, bedVolume, passGain, speechCurve } from "%(mix)s";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const speech = speechCurve(input.doc);
const on = ambienceSettings(input.doc.ambience, input.doc.sfxEnabled);
const curves = input.doc.ambience.beds.map((b: any) => {
  const v = bedVolume(b, input.doc.fps, on ? on.master : 0, on ? on.duck : 1, speech);
  return v ? input.frames.map((f: number) => v(f)) : null;
});
const off = input.offs.map((o: any) => ambienceSettings(o.ambience, o.sfxEnabled));
const passes = (input.passes || []).map((c: any) => {
  const ps = bedPasses(c.bed, c.file, c.overlap);
  // the summed power of every pass at each frame of the bed
  const power = Array.from({ length: c.bed }, (_, f) => ps.reduce((s, p) =>
    s + (f >= p.from && f < p.from + p.frames ? passGain(p, f - p.from) ** 2 : 0), 0));
  return { ps, power };
});
process.stdout.write(JSON.stringify({ on, curves, off, passes, speech: input.frames.map((f: number) => speech[f]) }));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class RendererMix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"mix": MIX_TS.replace("\\", "/")[:-3]})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_fades_holes_ducking_and_the_ceiling(self):
        doc = {"fps": 30, "durationInFrames": 900, "scenes": [{"words": [{"start": 10.0, "end": 12.0}]}],
               "ambience": {"enabled": True, "level": 1.0, "duck": 0.7,
                            "beds": [{"name": "amb-wind", "startFrame": 0, "durationInFrames": 900, "volume": 0.1,
                                      "ceiling": 0.25, "fadeIn": 30, "fadeOut": 36, "holes": [[600, 660]]},
                                     {"name": "amb-wind", "startFrame": 0, "durationInFrames": 900, "volume": 0.4,
                                      "ceiling": 0.25}]}}
        frames = [0, 15, 30, 150, 330, 600, 630, 660, 700, 864, 882, 899]
        offs = [{"ambience": {"enabled": False, "beds": [{}]}}, {"ambience": doc["ambience"], "sfxEnabled": False},
                {"ambience": {"level": 0, "beds": [{}]}}, {"ambience": None}]
        run = subprocess.run([self.node, self.bundle], input=json.dumps({"doc": doc, "frames": frames, "offs": offs}),
                             capture_output=True, text=True, timeout=60, check=True)
        got = json.loads(run.stdout)
        v = dict(zip(frames, got["curves"][0]))
        self.assertEqual(v[0], 0.0)                               # faded in from silence
        self.assertAlmostEqual(v[15], 0.05, places=3)
        self.assertAlmostEqual(v[150], 0.1, places=4)             # its planned level
        self.assertAlmostEqual(v[330], 0.07, places=3)            # a word: ducked to 70%
        self.assertEqual(v[630], 0.0)                             # a full-screen graphic: silent
        self.assertEqual(v[600], 0.0)
        self.assertAlmostEqual(v[700], 0.1, places=4)             # back after the ramp
        self.assertAlmostEqual(v[882], 0.05, places=3)            # fading out
        self.assertEqual(v[899] < 0.01, True)
        self.assertAlmostEqual(max(got["curves"][1]), 0.25, places=4)   # never over its ceiling
        self.assertEqual(got["off"], [None, None, None, None])

    def test_a_long_bed_plays_its_file_pass_after_pass_crossfaded_at_equal_power(self):
        cases = [{"bed": 5000, "file": 1800, "overlap": 8}, {"bed": 1200, "file": 1800, "overlap": 8},
                 {"bed": 3592, "file": 1800, "overlap": 8}, {"bed": 900, "file": 0, "overlap": 8}]
        doc = {"fps": 30, "durationInFrames": 10, "scenes": [], "ambience": {"beds": []}}
        run = subprocess.run([self.node, self.bundle], input=json.dumps({"doc": doc, "frames": [], "offs": [],
                                                                         "passes": cases}),
                             capture_output=True, text=True, timeout=60, check=True)
        got = json.loads(run.stdout)["passes"]
        for case, res in zip(cases, got):
            ps = res["ps"]
            if case["file"] == 0:                       # no file length known: Remotion's loop
                self.assertEqual(ps, [{"from": 0, "frames": 900, "fadeIn": 0, "fadeOut": 0, "loop": True}])
                continue
            self.assertEqual(ps[0]["from"], 0)
            self.assertEqual(ps[-1]["from"] + ps[-1]["frames"], case["bed"])     # to the bed's last frame
            for p in ps:
                self.assertLessEqual(p["frames"], case["file"])                     # never past the file's end
            for a, b in zip(ps, ps[1:]):
                self.assertEqual(a["from"] + a["frames"] - b["from"], case["overlap"])
            for f, pw in enumerate(res["power"]):
                self.assertAlmostEqual(pw, 1.0, places=6, msg=(case, f))          # no dip, no bump
        self.assertEqual(len(got[1]["ps"]), 1)


if __name__ == "__main__":
    unittest.main()
