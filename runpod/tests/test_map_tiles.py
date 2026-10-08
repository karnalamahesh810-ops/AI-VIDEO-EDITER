"""
Satellite map tiles (remotion/src/components/motion/tiles.ts, satelliteTiles.tsx), 2026-10-08: the Obama video's
Honolulu map (satellite-tilt, 1:47) showed pale cream slabs on the sea. The cause, measured on the free tiles the
map draws: the USGS cache's Hawaii mosaic paints no-data as flat opaque slabs - cream (255,255,205), orange
(255,188,120), periwinkle (128,127,254) and white - and the renderer's filter dropped only black no-data. Hawaii
also has no USGS zoom 9 at all (404), so mid-zoom the island fell back to the blurred Blue Marble underlay.

Now each USGS tile is cleaned once per page on a canvas (tiles.dropNoData: black as before, the fill slabs and
strips by colour and run length, white only on Hawaii's tiles), and a tile the cache lacks draws its children.

Offline: recorded USGS tiles (tests/fixtures/map_tiles, basemap.nationalmap.gov, public domain, fetched
2026-10-08; names end in z_y_x); the renderer's TypeScript runs under node (esbuild), no network.
"""
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
COMPONENTS = os.path.join(REMOTION, "src", "components")
MOTION = os.path.join(COMPONENTS, "motion")
TILES = os.path.join(ROOT, "tests", "fixtures", "map_tiles")

FILLS = {"cream": (255, 255, 205), "orange": (255, 188, 120), "periwinkle": (128, 127, 254)}
MAPS = [os.path.join(COMPONENTS, "MapLooks.tsx"), os.path.join(COMPONENTS, "lib", "LibGeoMaps.tsx"),
        os.path.join(COMPONENTS, "lib", "LibMapsPro.tsx")]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _tile(name):
    """A recorded tile as a canvas gives it back: RGBA, a transparent pixel without colour; and its z, y, x."""
    path = next(p for p in glob.glob(os.path.join(TILES, f"{name}_*")))
    a = np.asarray(Image.open(path).convert("RGBA")).copy()
    a[a[..., 3] == 0, :3] = 0
    z, y, x = (int(v) for v in os.path.splitext(os.path.basename(path))[0].split("_")[-3:])
    return a, (z, x, y)


def _near(colour, a, tol=6):
    return (a[..., 3] > 0) & (np.abs(a[..., :3].astype(int) - np.array(colour)).max(-1) <= tol)


def _dilate(m, r):
    p = np.pad(m, r)
    out = np.zeros_like(m)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= p[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return out


class Wiring(unittest.TestCase):
    """Every satellite map draws its tiles the one way (motion/satelliteTiles), with no per-frame filter."""

    def test_the_maps_use_the_shared_tiles(self):
        for path in MAPS:
            src = _read(path)
            self.assertIn("ImageryTile", src, path)
            self.assertIn("TileFilters", src, path)
            self.assertNotIn("basemap.nationalmap.gov", src, path)
            self.assertNotIn("gibs.earthdata.nasa.gov", src, path)
            self.assertNotIn("9 9 9 0 -0.1", src, path)              # the old black-only filter of its own

    def test_only_tiles_ts_knows_the_tile_servers(self):
        holders = [p for p in glob.glob(os.path.join(REMOTION, "src", "**", "*.ts*"), recursive=True)
                   if "basemap.nationalmap.gov" in _read(p)]
        self.assertEqual([os.path.basename(p) for p in holders], ["tiles.ts"])

    def test_no_morphology_runs_on_every_frame(self):
        # An SVG filter doing the fill key (feMorphology on every tile, every frame) made a 40-frame map
        # render take 214-316 s instead of 10 s: the key runs once per tile on a canvas instead.
        src = _read(os.path.join(MOTION, "satelliteTiles.tsx"))
        self.assertNotIn("feMorphology", src)
        self.assertIn("dropNoData(", src)
        self.assertIn("childTiles(", src)                             # a missing USGS level draws its children
        self.assertIn("res.status === 404", src)


# --------------------------------------------------------------------------- the renderer's code under node
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import * as T from "%(m)s/tiles";
import * as fs from "fs";
const calls = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = calls.map((c: any) => {
  switch (c.op) {
    case "drop": {
      const px = new Uint8ClampedArray(Buffer.from(c.rgba, "base64"));
      const got = T.dropNoData(px, c.w, c.h, c.white);
      const alpha = Buffer.alloc(c.w * c.h);
      for (let i = 0; i < c.w * c.h; i++) alpha[i] = px[i * 4 + 3];
      return { ...got, alpha: alpha.toString("base64") };
    }
    case "runs": return Array.from(T.runs(Uint8Array.from(c.m), c.w, c.h, c.len));
    case "grow": return Array.from(T.grow(Uint8Array.from(c.m), c.w, c.h, c.r));
    case "hawaii": return T.hawaiiTile(c.z, c.x, c.y);
    case "children": return T.childTiles(c.z, c.x, c.y);
    case "url": return T.tileUrl(c.z, c.x, c.y, c.us);
    default: return null;
  }
});
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Cleaning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"m": MOTION.replace("\\", "/")})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=180)
        cls.node = node
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_calls(self, *calls):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(list(calls)), capture_output=True, text=True,
                             encoding="utf-8", timeout=180, check=True)
        return json.loads(run.stdout)

    def clean(self, name):
        """(tile before, alpha after, fills dropped) - Hawaii's white key on when the tile is in Hawaii."""
        if name not in self.cache:
            a, (z, x, y) = _tile(name)
            white = self.run_calls({"op": "hawaii", "z": z, "x": x, "y": y})[0]
            got = self.run_calls({"op": "drop", "rgba": base64.b64encode(a.tobytes()).decode(), "w": a.shape[1],
                                  "h": a.shape[0], "white": white})[0]
            alpha = np.frombuffer(base64.b64decode(got["alpha"]), np.uint8).reshape(a.shape[:2])
            self.cache[name] = (a, alpha, got["fills"], white)
        return self.cache[name]

    def assert_fill_gone(self, name, colour):
        a, alpha, fills, _ = self.clean(name)
        slab = _near(colour, a)
        self.assertGreater(slab.sum(), 500, name)
        self.assertGreater(fills, 0, name)
        left = int((slab & (alpha > 0)).sum())
        self.assertEqual(left, 0, f"{name}: {left} of {int(slab.sum())} fill pixels still drawn")
        return a, alpha, slab

    def assert_imagery_kept(self, name, a, alpha, away_from=None):
        """Real imagery (not near-black, not within 6 px of a slab) keeps its alpha exactly as the black key gives."""
        rgb = a[..., :3].astype(int)
        black_key = np.clip(9 * rgb.sum(-1) / 255 - 0.1, 0, 1) * a[..., 3]
        real = (a[..., 3] > 0) & (rgb.sum(-1) > 60)
        if away_from is not None:
            real &= ~_dilate(away_from, 6)
        self.assertGreater(real.sum(), 0, name)
        moved = np.abs(alpha.astype(int) - np.round(black_key).astype(int))[real]
        self.assertEqual(int((moved > 1).sum()), 0, f"{name}: {int((moved > 1).sum())} imagery pixels lost")

    # ------------------------------------------------------------------ the slabs go
    def test_the_honolulu_maps_cream_slab_goes(self):
        # The very tile behind the pale quad east of Makapuu Point in the 1:47 frame (z11, x127, y899).
        a, alpha, slab = self.assert_fill_gone("honolulu_cream_slab", FILLS["cream"])
        self.assert_imagery_kept("honolulu_cream_slab", a, alpha, slab)
        self.assert_fill_gone("oahu_cream_slab", FILLS["cream"])

    def test_the_orange_and_periwinkle_slabs_go(self):
        a, alpha, slab = self.assert_fill_gone("molokai_orange_slab", FILLS["orange"])
        self.assert_imagery_kept("molokai_orange_slab", a, alpha, slab)          # Molokai itself stays
        a, alpha, slab = self.assert_fill_gone("maui_periwinkle_slab", FILLS["periwinkle"])
        orange = _near(FILLS["orange"], a)                    # its 3 px orange strip along the top goes too
        self.assertGreater(orange.sum(), 150)
        self.assertLessEqual(int((orange & (alpha > 0)).sum()), 2)                # (but a speck of its tail)
        self.assert_imagery_kept("maui_periwinkle_slab", a, alpha, slab | orange)

    def test_a_white_slab_goes_on_hawaiis_tiles(self):
        a, alpha, fills, white = self.clean("big_island_white_slab")
        self.assertTrue(white)
        slab = _near((255, 255, 255), a, 3)
        self.assertGreater(slab.sum(), 5000)
        self.assertEqual(int((slab & (alpha > 0)).sum()), 0)
        self.assert_imagery_kept("big_island_white_slab", a, alpha, slab)          # the coast beside it stays

    def test_the_slab_beside_red_soil(self):
        # Kahoolawe: its red soil is close to the orange fill, pixel for pixel - it stays; the cream slab goes.
        a, alpha, slab = self.assert_fill_gone("kahoolawe_red_soil", FILLS["cream"])
        soil = _near(FILLS["orange"], a, 12) & ~_dilate(slab, 6)
        self.assertGreater(soil.sum(), 0)
        self.assertEqual(int((soil & (alpha == 0)).sum()), 0)

    # ------------------------------------------------------------------ real imagery stays
    def test_white_snow_and_cloud_stay(self):
        for name in ("alaska_glacier", "maui_clouds"):
            a, alpha, fills, white = self.clean(name)
            self.assertEqual(fills, 0, name)
            bright = (a[..., 3] > 0) & (a[..., :3].min(-1) >= 240)
            self.assertGreater(bright.sum(), 2000, name)
            self.assertTrue((alpha[bright] == 255).all(), name)
            self.assert_imagery_kept(name, a, alpha)
        self.assertFalse(self.clean("alaska_glacier")[3])          # Alaska is not Hawaii: no white key at all

    def test_a_few_pixels_in_a_fills_colour_are_not_a_fill(self):
        # Yellowish cloud tops on the Big Island hold pixels within the cream fill's tolerance.
        a, alpha, fills, _ = self.clean("big_island_yellow_clouds")
        creamy = _near(FILLS["cream"], a, 10)
        self.assertGreater(creamy.sum(), 0)
        self.assertEqual(fills, 0)
        self.assertEqual(int((creamy & (alpha == 0)).sum()), 0)
        self.assert_imagery_kept("big_island_yellow_clouds", a, alpha)

    def test_a_mainland_tile_is_untouched(self):
        a, alpha, fills, white = self.clean("denver")
        self.assertFalse(white)
        self.assertEqual(fills, 0)
        self.assert_imagery_kept("denver", a, alpha)

    # ------------------------------------------------------------------ the parts
    def test_runs_keep_strips_and_drop_specks(self):
        w = h = 16
        m = np.zeros((h, w), np.uint8)
        m[2, 1:8] = 1                      # a strip one pixel thick, 7 long: a fill's edge
        m[5, 1:7] = 1                      # 6 long: too short
        m[10:13, 10:13] = 1                # a 3 x 3 speck
        m[1:9, 14] = 1                     # 8 down
        got = np.array(self.run_calls({"op": "runs", "m": m.ravel().tolist(), "w": w, "h": h, "len": 7})[0]
                       ).reshape(h, w)
        self.assertTrue(got[2, 1:8].all())
        self.assertFalse(got[5, 1:7].any())
        self.assertFalse(got[10:13, 10:13].any())
        self.assertTrue(got[1:9, 14].all())
        dot = np.zeros((h, w), np.uint8)
        dot[8, 8] = 1
        grown = np.array(self.run_calls({"op": "grow", "m": dot.ravel().tolist(), "w": w, "h": h, "r": 3})[0]
                         ).reshape(h, w)
        self.assertEqual(int(grown.sum()), 49)                           # a 7 x 7 square round it
        self.assertTrue(grown[5:12, 5:12].all())

    def test_where_and_which(self):
        hawaii, denver, anchorage, children, usgs9, usgs7, gibs6 = self.run_calls(
            {"op": "hawaii", "z": 11, "x": 127, "y": 899}, {"op": "hawaii", "z": 11, "x": 426, "y": 777},
            {"op": "hawaii", "z": 11, "x": 170, "y": 594}, {"op": "children", "z": 9, "x": 31, "y": 224},
            {"op": "url", "z": 9, "x": 31, "y": 224, "us": True}, {"op": "url", "z": 7, "x": 7, "y": 56, "us": True},
            {"op": "url", "z": 6, "x": 3, "y": 28, "us": True})
        self.assertEqual((hawaii, denver, anchorage), (True, False, False))
        self.assertEqual([c[:3] for c in children], [[10, 62, 448], [10, 63, 448], [10, 62, 449], [10, 63, 449]])
        self.assertIn("USGSImageryOnly/MapServer/tile/9/224/31", usgs9)
        self.assertIn("USGSImageryOnly/MapServer/tile/7/56/7", usgs7)
        self.assertIn("BlueMarble_NextGeneration", gibs6)


if __name__ == "__main__":
    unittest.main()
