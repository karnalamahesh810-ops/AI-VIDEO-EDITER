"""Editor v2's clip keyframes, effects stack, mask and motion blur: the worker's cleaning (src/clipfx.py) is the
renderer's (remotion edit/keyframes.ts + edit/effects.ts), the render path cleans before drawing, and the quality
check leaves an intentional blur or fade alone. Offline: no network, no paid calls."""
import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest

from src import clipfx, quality

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
EDIT = os.path.join(REMOTION, "src", "edit")


def _read(*parts):
    with open(os.path.join(REMOTION, "src", *parts), encoding="utf-8") as fh:
        return fh.read()


class Cleaning(unittest.TestCase):
    def test_keys_are_ordered_held_to_range_and_bad_ones_dropped(self):
        kf = clipfx.clean_keyframes({
            "scale": [{"t": 2, "v": 1.2, "e": "easeOut"}, {"t": 0, "v": 1}, {"t": "1", "v": 3}, {"t": 1, "v": True},
                      {"t": -3, "v": 99, "e": "wobble"}],
            "opacity": [{"t": 0, "v": 2}],
            "rotation": "spin",
            "nope": [{"t": 0, "v": 1}],
        })
        self.assertEqual(kf["scale"], [{"t": 0.0, "v": 1.0}, {"t": 0.0, "v": 20.0}, {"t": 2.0, "v": 1.2, "e": "easeOut"}])
        self.assertEqual(kf["opacity"], [{"t": 0.0, "v": 1.0}])
        self.assertNotIn("rotation", kf)
        self.assertNotIn("nope", kf)
        self.assertIsNone(clipfx.clean_keyframes({"x": []}))
        self.assertIsNone(clipfx.clean_keyframes([1, 2]))

    def test_eases(self):
        for good in ("hold", "easeIn", "easeOut", "easeInOut", "expoOut", "backOut", "bezier:0.25,0.1,0.25,1",
                     "bezier: .5, -0.6, .5, 1.6"):
            self.assertTrue(clipfx.is_ease(good), good)
        for bad in ("bezier:1.2,0,0,1", "bezier:0,0,0", "bezier:a,b,c,d", "bounce", 3, None):
            self.assertFalse(clipfx.is_ease(bad), bad)
        # linear is the default: not stored.
        self.assertEqual(clipfx.clean_keys([{"t": 0, "v": 0, "e": "linear"}], "x"), [{"t": 0.0, "v": 0.0}])

    def test_effects_mask_and_motion_blur(self):
        fx = clipfx.clean_effects([{"type": "blur", "value": 3}, {"type": "exposure", "value": -9, "on": False},
                                   {"type": "sparkle", "value": 1}, {"type": "bw", "value": "1"},
                                   {"type": "grain", "value": 0.3, "on": "yes"}])
        self.assertEqual(fx, [{"type": "blur", "value": 1.0}, {"type": "exposure", "value": -3.0, "on": False},
                              {"type": "grain", "value": 0.3}])
        self.assertIsNone(clipfx.clean_effects([]))
        self.assertEqual(clipfx.clean_mask({"shape": "ellipse", "x": -5, "y": 0.1, "w": 9, "h": 0.5, "invert": True}),
                         {"shape": "ellipse", "x": -1.0, "y": 0.1, "w": 3.0, "h": 0.5, "feather": 0.0, "invert": True})
        self.assertIsNone(clipfx.clean_mask({"shape": "star", "x": 0, "y": 0, "w": 1, "h": 1}))
        self.assertIsNone(clipfx.clean_mask({"shape": "rect", "x": 0, "y": 0, "w": 0, "h": 1}))
        self.assertEqual(clipfx.clean_motion_blur(True), 0.5)
        self.assertEqual(clipfx.clean_motion_blur(3), 1.0)
        self.assertIsNone(clipfx.clean_motion_blur(False))
        self.assertIsNone(clipfx.clean_motion_blur(0))
        self.assertIsNone(clipfx.clean_motion_blur("on"))

    def test_clean_touches_only_the_new_fields_and_never_raises(self):
        doc = {"scenes": [
            {"id": "a", "media": {"type": "video"}, "speed": 2, "effects": [{"type": "nope", "value": 1}],
             "keyframes": {"x": [{"t": 0, "v": 0.1}]}, "motionBlur": "x", "mask": None},
            {"id": "b", "media": {}},
            "not a scene",
        ]}
        changed = clipfx.clean(doc)
        a = doc["scenes"][0]
        self.assertEqual(changed, 3)
        self.assertNotIn("effects", a)
        self.assertNotIn("motionBlur", a)
        self.assertNotIn("mask", a)
        self.assertEqual(a["keyframes"], {"x": [{"t": 0.0, "v": 0.1}]})
        self.assertEqual(a["speed"], 2)
        self.assertEqual(doc["scenes"][1], {"id": "b", "media": {}})
        self.assertEqual(clipfx.clean(None), 0)
        self.assertEqual(clipfx.clean({"scenes": "x"}), 0)


class QualityLeavesTheEditAlone(unittest.TestCase):
    def test_an_intentional_blur_is_not_blurry(self):
        s = {"effects": [{"type": "blur", "value": 0.4}]}
        self.assertTrue(clipfx.blurs_on_purpose(s))
        self.assertFalse(clipfx.blurs_on_purpose({"effects": [{"type": "blur", "value": 0.4, "on": False}]}))
        self.assertFalse(clipfx.blurs_on_purpose({"effects": [{"type": "sharpen", "value": 0.4}]}))
        self.assertFalse(clipfx.blurs_on_purpose({}))

    def test_the_sharpness_check_skips_a_clip_blurred_on_purpose(self):
        import inspect
        src = inspect.getsource(quality.Gate._soft_scenes)
        self.assertIn("clipfx.blurs_on_purpose(s)", src)

    def test_a_fade_or_crush_is_not_black_over_a_clip(self):
        self.assertTrue(clipfx.dark_on_purpose({"keyframes": {"opacity": [{"t": 0, "v": 1}, {"t": 2, "v": 0}]}}))
        self.assertTrue(clipfx.dark_on_purpose({"effects": [{"type": "exposure", "value": -3}]}))
        self.assertTrue(clipfx.dark_on_purpose({"mask": {"shape": "rect", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}}))
        self.assertFalse(clipfx.dark_on_purpose({"mask": {"shape": "rect", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2,
                                                          "invert": True}}))
        self.assertFalse(clipfx.dark_on_purpose({"keyframes": {"opacity": [{"t": 0, "v": 0.8}]}}))
        self.assertFalse(clipfx.dark_on_purpose({}))
        # The scan reads it: 3 s of black over a clip the editor faded out is intended.
        doc = {"fps": 30, "durationInFrames": 600, "scenes": [
            {"id": "a", "startFrame": 0, "durationInFrames": 300, "transition": "none",
             "media": {"type": "video", "url": "https://x/a.mp4"}},
            {"id": "b", "startFrame": 300, "durationInFrames": 300, "transition": "none",
             "media": {"type": "video", "url": "https://x/b.mp4"},
             "keyframes": {"opacity": [{"t": 0, "v": 1}, {"t": 1, "v": 0}]}},
        ]}
        res = {"duration": 20.0, "black": [(11.0, 14.0)], "frozen": [], "silent": [], "audio": True}
        defects, intended = quality.classify(doc, res)
        self.assertEqual([d for d in defects if d["kind"] == "black"], [])
        doc["scenes"][1].pop("keyframes")
        defects, _ = quality.classify(doc, res)
        self.assertEqual(len([d for d in defects if d["kind"] == "black"]), 1)


class RendererWiring(unittest.TestCase):
    def test_scene_clip_draws_the_stack_after_the_look(self):
        clip = _read("components", "SceneClip.tsx")
        self.assertIn('import { ClipFx } from "../edit/ClipFx"', clip)
        self.assertGreaterEqual(clip.count("<ClipFx fx={scene}"), 3)
        fx = _read("edit", "ClipFx.tsx")
        self.assertNotIn("Math.random", fx)
        self.assertNotIn("setTimeout", fx)
        self.assertNotIn("<Img", fx)
        # A scene with none of it draws its children untouched (an old document renders as before).
        self.assertIn("if (!spec) return <>{children}{over}</>;", fx)

    def test_the_render_path_cleans_first(self):
        with open(os.path.join(ROOT, "handler.py"), encoding="utf-8") as fh:
            handler = fh.read()
        at = handler.index("def do_render(")
        self.assertLess(handler.index("clipfx.clean(doc)", at), handler.index("quality.Gate(doc", at))


# --------------------------------------------------------------------------- the renderer's cleaning under node
def _node():
    node = shutil.which("node")
    for esbuild in (os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild"), os.environ.get("ESBUILD", "")):
        if node and esbuild and os.path.isfile(esbuild):
            return node, esbuild
    return None, None


HARNESS = """
import { cleanClipFx } from "%(edit)s/effects";
import { valueAt, ease, motionBlurAt } from "%(edit)s/keyframes";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = {
  cleaned: input.scenes.map((s: any) => cleanClipFx(s)),
  values: input.values.map((c: any) => valueAt(c.keys, c.t, 0)),
  eases: input.eases.map((c: any) => ease(c.e, c.p)),
  blur: input.blur.map((c: any) => motionBlurAt(c.kf, c.t, 30, 1920, 1080, 0.5)),
};
process.stdout.write(JSON.stringify(out));
"""


def _rand_value(rnd):
    return rnd.choice([rnd.uniform(-30, 30), rnd.uniform(-1, 1), 0, 1, True, None, "1", float("nan") if False else -0.5,
                       rnd.randint(-5, 5)])


def _rand_scene(rnd):
    s = {}
    if rnd.random() < 0.7:
        kf = {}
        for prop in rnd.sample(list(clipfx.KEY_PROPS) + ["bogus"], rnd.randint(0, 4)):
            kf[prop] = [{"t": rnd.choice([rnd.uniform(-2, 8), "2", None, 1]), "v": _rand_value(rnd),
                         **({"e": rnd.choice(list(clipfx.EASE_NAMES) + ["bezier:0.3,0,0.2,1", "bezier:2,0,0,1",
                                                                       "bezier:.4,1.6,.6,-.2", "nope"])}
                            if rnd.random() < 0.6 else {})}
                        for _ in range(rnd.randint(0, 5))]
        s["keyframes"] = kf if rnd.random() < 0.95 else "junk"
    if rnd.random() < 0.6:
        s["effects"] = [{"type": rnd.choice(list(clipfx.EFFECTS) + ["sparkle"]), "value": _rand_value(rnd),
                         **({"on": rnd.choice([True, False, "no"])} if rnd.random() < 0.4 else {})}
                        for _ in range(rnd.randint(0, 5))]
    if rnd.random() < 0.5:
        s["mask"] = {"shape": rnd.choice(list(clipfx.MASK_SHAPES) + ["star"]), "x": _rand_value(rnd),
                     "y": rnd.uniform(-2, 3), "w": rnd.choice([rnd.uniform(-1, 5), 0.5]), "h": rnd.uniform(0, 2),
                     "feather": _rand_value(rnd), **({"invert": rnd.choice([True, False, 1])} if rnd.random() < 0.5 else {}),
                     **({"radius": _rand_value(rnd)} if rnd.random() < 0.5 else {})}
    if rnd.random() < 0.5:
        s["motionBlur"] = rnd.choice([True, False, 0, 0.3, 4, -1, "on", None])
    return s


@unittest.skipUnless(all(_node()), "needs node and esbuild (remotion's, or ESBUILD=<path>)")
class RendererTwins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"edit": EDIT.replace("\\", "/")})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, scenes=(), values=(), eases=(), blur=()):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(
            {"scenes": list(scenes), "values": list(values), "eases": list(eases), "blur": list(blur)}),
            capture_output=True, text=True, timeout=60, check=True)
        return json.loads(run.stdout)

    def test_the_cleaning_agrees(self):
        rnd = random.Random(7)
        scenes = [_rand_scene(rnd) for _ in range(300)]
        got = self._run(scenes=scenes)["cleaned"]
        for s, ts in zip(scenes, got):
            self.assertEqual(ts or {}, clipfx.clean_scene(s), s)

    def test_the_reading_is_sane(self):
        keys = [{"t": 0, "v": 0}, {"t": 1, "v": 10, "e": "easeOut"}, {"t": 2, "v": 10, "e": "hold"}, {"t": 3, "v": 0, "e": "hold"}]
        out = self._run(values=[{"keys": keys, "t": t} for t in (-1, 0, 0.5, 1, 1.5, 2.5, 2.999, 3, 9)],
                        eases=[{"e": "bezier:0.42,0,0.58,1", "p": 0.5}, {"e": "bezier:0,0,1,1", "p": 0.3},
                               {"e": "backOut", "p": 0.6}, {"e": "nope", "p": 0.25}],
                        blur=[{"kf": {"x": [{"t": 0, "v": 0}, {"t": 1, "v": 0.5}]}, "t": 0.5},
                              {"kf": {"x": [{"t": 0, "v": 0}, {"t": 1, "v": 0.5}]}, "t": 2},
                              {"kf": {"scale": [{"t": 0, "v": 1}, {"t": 0.2, "v": 1.2}]}, "t": 0.1}])
        v = out["values"]
        self.assertEqual(v[0], 0)
        self.assertAlmostEqual(v[2], 10 * (1 - 0.5 ** 3))       # easeOut half way
        self.assertEqual(v[3], 10)
        self.assertEqual(v[5], 10)                              # held until the hold key
        self.assertEqual(v[6], 10)
        self.assertEqual(v[7], 0)
        self.assertEqual(v[8], 0)
        e = out["eases"]
        self.assertAlmostEqual(e[0], 0.5, places=5)             # a symmetric curve
        self.assertAlmostEqual(e[1], 0.3, places=5)             # the straight line
        self.assertGreater(e[2], 1.0)                           # overshoot
        self.assertEqual(e[3], 0.25)                            # unknown = linear
        b = out["blur"]
        self.assertGreater(b[0]["sx"], 1)                       # moving across: a horizontal streak
        self.assertEqual(b[0]["sy"], 0)
        self.assertEqual(b[1], {"sx": 0, "sy": 0})              # still: no blur
        self.assertGreater(b[2]["sx"], 0)
        self.assertEqual(b[2]["sx"], b[2]["sy"])                # a zoom blurs both ways


if __name__ == "__main__":
    unittest.main()
