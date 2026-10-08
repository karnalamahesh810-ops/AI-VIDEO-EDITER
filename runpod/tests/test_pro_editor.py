"""The pro editor's renderer contract: clip in-points and speeds (src/cliptime.py = remotion edit/clipTime.ts),
the narration after ripple deletes (edit/narration.ts), and the quality check reading both."""
import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest

from src import cliptime, gapfill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
EDIT = os.path.join(REMOTION, "src", "edit")


def _read(*parts):
    with open(os.path.join(REMOTION, "src", *parts), encoding="utf-8") as fh:
        return fh.read()


class ClipPlanPython(unittest.TestCase):
    def test_an_unedited_clip_plays_as_before(self):
        # From its first frame, slowed to fill a scene it is shorter than, never under 0.6x.
        self.assertEqual(cliptime.clip_plan({"clipSeconds": 6.0}, 150, 30),
                         [{"from": 0, "frames": 150, "rate": 1.0, "trimBefore": 0}])
        plan = cliptime.clip_plan({"clipSeconds": 4.0}, 150, 30)
        self.assertAlmostEqual(plan[0]["rate"], 0.8)
        self.assertEqual(cliptime.clip_plan({"clipSeconds": 1.0}, 150, 30)[0]["rate"], cliptime.MIN_FILL_RATE)
        self.assertEqual(cliptime.clip_plan({"clipSeconds": 6.0, "trimStart": 0}, 150, 30)[0]["trimBefore"], 0)

    def test_a_slipped_clip_starts_part_way_in(self):
        plan = cliptime.clip_plan({"clipSeconds": 8.0, "trimStart": 1.5}, 150, 30)
        self.assertEqual(plan, [{"from": 0, "frames": 150, "rate": 1.0, "trimBefore": 45}])
        # Too little left: slowed just enough to reach the scene's end (no 0.6x floor, never frozen).
        plan = cliptime.clip_plan({"clipSeconds": 6.0, "trimStart": 3.0}, 150, 30)
        self.assertAlmostEqual(plan[0]["rate"], 3.0 / 5.0)
        self.assertAlmostEqual(cliptime.plan_source_seconds(plan, 30), 3.0)
        # An in-point past the end is held on the last frame.
        plan = cliptime.clip_plan({"clipSeconds": 2.0, "trimStart": 9.0}, 60, 30)
        self.assertEqual(plan[0]["trimBefore"], 59)

    def test_a_constant_speed(self):
        plan = cliptime.clip_plan({"clipSeconds": 20.0, "speed": 2}, 90, 30)
        self.assertEqual(plan, [{"from": 0, "frames": 90, "rate": 2.0, "trimBefore": 0}])
        plan = cliptime.clip_plan({"clipSeconds": 20.0, "speed": 0.5}, 90, 30)
        self.assertEqual(plan[0]["rate"], 0.5)
        # 2x of a 4 s clip over a 3 s scene would run out: 4/3x.
        self.assertAlmostEqual(cliptime.clip_plan({"clipSeconds": 4.0, "speed": 2}, 90, 30)[0]["rate"], 4 / 3)

    def test_a_ramp_tiles_the_scene_and_never_jumps(self):
        plan = cliptime.clip_plan({"clipSeconds": 30.0, "speedRamp": [{"t": 0, "v": 1}, {"t": 1, "v": 0.25},
                                                                     {"t": 2, "v": 0.25}, {"t": 3, "v": 1}]}, 120, 30)
        self.assertGreater(len(plan), 2)
        self.assertEqual(plan[0]["from"], 0)
        self.assertEqual(sum(p["frames"] for p in plan), 120)
        for a, b in zip(plan, plan[1:]):
            self.assertEqual(a["from"] + a["frames"], b["from"])
            # Each stretch starts within a frame of where the one before ended.
            self.assertLessEqual(abs(a["trimBefore"] + a["rate"] * a["frames"] - b["trimBefore"]), 1.0)
        rates = [p["rate"] for p in plan]
        self.assertLess(min(rates), 0.3)
        self.assertAlmostEqual(max(rates), 1.0, delta=0.15)


class QualityReadsThePlan(unittest.TestCase):
    def _scene(self, **kw):
        s = {"id": "s1", "startFrame": 0, "durationInFrames": 150,
             "media": {"type": "video", "url": "https://x/a.mp4", "clipSeconds": 8.0}}
        s["media"].update(kw.pop("media", {}))
        s.update(kw)
        return s

    def test_an_edited_clip_covers_its_scene_unless_nothing_is_left(self):
        self.assertTrue(cliptime.covers(self._scene(media={"trimStart": 2.0}), 8.0, 5.0, 30))
        self.assertTrue(cliptime.covers(self._scene(media={"trimStart": 6.0}), 8.0, 5.0, 30))      # slowed
        self.assertFalse(cliptime.covers(self._scene(media={"trimStart": 7.9}), 8.0, 5.0, 30))     # under 1/16x
        self.assertTrue(cliptime.covers(self._scene(speed=0.5), 8.0, 5.0, 30))

    def test_a_split_shot_is_not_a_repeat(self):
        a = self._scene()
        b = self._scene(id="s1-b1", splitFrom="s1", startFrame=150, media={"trimStart": 5.0})
        c = self._scene(id="s3", startFrame=300)
        doc = {"fps": 30, "scenes": [a, b, c]}
        found = dict(gapfill.find_repeats(doc))
        self.assertNotIn(1, found)                      # the split's second part continues the shot
        self.assertIn(2, found)                         # the same file again, not split: a repeat
        # A splitFrom that names a scene with another file is not trusted.
        b2 = dict(b, splitFrom="nope")
        self.assertIn(1, dict(gapfill.find_repeats({"fps": 30, "scenes": [a, b2]})))


class RendererWiring(unittest.TestCase):
    def test_scene_clip_and_main_read_the_plans(self):
        clip = _read("components", "SceneClip.tsx")
        self.assertIn("clipPlan(", clip)
        self.assertNotIn("playbackRate={rate}", clip)
        main = _read("Main.tsx")
        self.assertIn("narrationPieces(keepRanges(audio)", main)


# --------------------------------------------------------------------------- the renderer's math under node
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { clipPlan } from "%(edit)s/clipTime";
import { cutProgram, narrationPieces, programToSource, sourceToProgram, keepRanges } from "%(edit)s/narration";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = {
  plans: input.plans.map((c: any) => clipPlan(c.timing, c.frames, c.fps)),
  cuts: input.cuts.map((c: any) => cutProgram(c.keep, c.from, c.to, c.total)),
  pieces: input.pieces.map((c: any) => narrationPieces(keepRanges({ keep: c.keep }), c.fps, c.total)),
  maps: input.maps.map((c: any) => [programToSource(c.keep, c.t), sourceToProgram(c.keep, c.t)]),
};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
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

    def _run(self, plans=(), cuts=(), pieces=(), maps=()):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(
            {"plans": list(plans), "cuts": list(cuts), "pieces": list(pieces), "maps": list(maps)}),
            capture_output=True, text=True, timeout=60, check=True)
        return json.loads(run.stdout)

    def test_the_clip_plans_agree(self):
        rnd = random.Random(11)
        cases = []
        for _ in range(160):
            timing = {"clipSeconds": rnd.choice([0, 0, rnd.uniform(0.5, 30)])}
            if rnd.random() < 0.6:
                timing["trimStart"] = rnd.choice([0, rnd.uniform(0, 12)])
            if rnd.random() < 0.4:
                timing["speed"] = rnd.choice([0.25, 0.5, 1.5, 2, 4, rnd.uniform(0.05, 9)])
            if rnd.random() < 0.3:
                timing["speedRamp"] = [{"t": round(rnd.uniform(0, 4), 3), "v": round(rnd.uniform(0.1, 3), 3)}
                                       for _ in range(rnd.randint(1, 5))]
            cases.append({"timing": timing, "frames": rnd.randint(1, 400), "fps": rnd.choice([24, 25, 30, 60])})
        got = self._run(plans=cases)["plans"]
        for c, ts in zip(cases, got):
            py = cliptime.clip_plan(c["timing"], c["frames"], c["fps"])
            self.assertEqual(len(ts), len(py), c)
            for a, b in zip(ts, py):
                self.assertEqual(a["from"], b["from"], c)
                self.assertEqual(a["frames"], b["frames"], c)
                self.assertEqual(a["trimBefore"], b["trimBefore"], c)
                self.assertAlmostEqual(a["rate"], b["rate"], places=9, msg=c)

    def test_ripple_deletes_keep_the_rest_of_the_narration_in_order(self):
        got = self._run(cuts=[
            {"keep": None, "from": 10, "to": 12.5, "total": 60},
            {"keep": [[0, 10], [12.5, 60]], "from": 5, "to": 15, "total": 57.5},
            {"keep": [[0, 10], [12.5, 60]], "from": 0, "to": 1, "total": 57.5},
            {"keep": [[0, 10], [12.5, 60]], "from": 56, "to": 57.5, "total": 57.5},
        ], pieces=[{"keep": [[0, 10], [12.5, 60]], "fps": 30, "total": 1725}],
            maps=[{"keep": [[0, 10], [12.5, 60]], "t": 11}, {"keep": [[0, 10], [12.5, 60]], "t": 9}])
        self.assertEqual(got["cuts"][0], [[0, 10], [12.5, 60]])
        self.assertEqual(got["cuts"][1], [[0, 5], [17.5, 60]])
        self.assertEqual(got["cuts"][2], [[1, 10], [12.5, 60]])
        self.assertEqual(got["cuts"][3], [[0, 10], [12.5, 58.5]])
        self.assertEqual(got["pieces"][0], [{"from": 0, "frames": 300, "trimBefore": 0},
                                            {"from": 300, "frames": 1425, "trimBefore": 375}])
        self.assertEqual(got["maps"][0], [13.5, None])
        self.assertEqual(got["maps"][1], [9, 9])


if __name__ == "__main__":
    unittest.main()
