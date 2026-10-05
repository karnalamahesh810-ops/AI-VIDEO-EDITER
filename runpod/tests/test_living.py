"""
Living photos (src/living.py; remotion/src/transitions/livingPhoto.tsx): stills
cut into depth layers that the renderer moves against each other.

Offline: the depth model is replaced by synthetic depth maps (a test that runs
the real model is skipped unless it is installed), R2 by fakes.
"""
import importlib.util
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, fanout, living, quality  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion", "src")


def _picture(path, w=800, h=500, square=(320, 220, 520, 420)):
    """A sky-to-sand gradient with a red block in front: the block is the near object."""
    yy = np.linspace(0, 1, h)[:, None, None]
    sky = np.array([90, 140, 210], np.float32)
    sand = np.array([200, 170, 120], np.float32)
    a = (sky * (1 - yy) + sand * yy) * np.ones((h, w, 3), np.float32)
    rng = np.random.default_rng(0)
    a += rng.normal(0, 6, a.shape)                  # a little texture for the encoders and the guide
    x0, y0, x1, y1 = square
    a[y0:y1, x0:x1] = (190, 40, 30)
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB").save(path, quality=95)
    return path


def _depth(w=200, h=125, square=(80, 55, 130, 105), back=0.1, front=0.9):
    d = np.full((h, w), back, np.float32)
    x0, y0, x1, y1 = square
    d[y0:y1, x0:x1] = front
    return d


def _still_scene(i, url, seconds=4.0, motion="zoom-in", **extra):
    s = {"id": f"s{i:04d}", "startFrame": int(i * seconds * 30), "durationInFrames": int(seconds * 30), "text": "",
         "media": {"type": "image", "url": url, "source": "web_image"}, "motion": motion, "frame": "full",
         "effect": "none", "transition": "none", "words": [],
         "semanticMetadata": {"subject": "Lake Powell", "subjectType": "place"}}
    s.update(extra)
    return s


def _doc(scenes):
    return {"fps": 30, "width": 1920, "height": 1080, "scenes": scenes, "overlays": [], "meta": {"warnings": []},
            "durationInFrames": sum(s["durationInFrames"] for s in scenes), "audio": {"url": "", "volume": 1}}


def _fake_build(tmp):
    """build() as the model would answer it: two layers written next to the picture."""
    def build(path, motion, fw, fh, known_magnification=None):
        stem = os.path.splitext(path)[0]
        back, front = f"{stem}.living0.jpg", f"{stem}.living1.webp"
        for p in (back, front):
            with open(p, "wb") as fh_:
                fh_.write(b"x" * 100)
        return {"layers": [{"path": back, "depth": 0.1}, {"path": front, "depth": 0.85, "box": [0.4, 0.4, 0.7, 0.9]}],
                "plan": {"cuts": [0.5], "quality": 0.8, "depths": [0.1, 0.85], "focus": {"x": 0.55, "y": 0.65}},
                "aspect": 1.6, "cpu": 0.7, "seconds": 0.8, "zoom": 1.2}
    return build


class Flags(unittest.TestCase):
    def test_on_by_default_and_overridable_per_job(self):
        # On since the owner switched it on (2026-10-05), at the recommended strength.
        self.assertTrue(config.LIVING_PHOTOS)
        self.assertEqual(config.LIVING_PHOTOS_STRENGTH, 0.06)
        for key in ("LIVING_PHOTOS", "LIVING_PHOTOS_SECONDS", "LIVING_PHOTOS_STRENGTH", "LIVING_PHOTOS_MIN_SECONDS",
                    "LIVING_PHOTOS_MAX_LAYERS"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE, key)
            self.assertTrue(hasattr(config, key), key)
        self.assertGreater(config.LIVING_PHOTOS_SECONDS, 0)
        self.assertTrue(0.03 <= config.LIVING_PHOTOS_STRENGTH <= living.MAX_STRENGTH)

    def test_off_means_nothing_happens(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "LIVING_PHOTOS", False):
            doc = _doc([_still_scene(0, _picture(os.path.join(d, "a.jpg")))])
            called = []
            self.assertEqual(living.place(doc, build_fn=lambda *a, **k: called.append(1)), {})
            self.assertFalse(called)
            self.assertNotIn("living", doc["scenes"][0]["media"])
            self.assertFalse(living.place_one(doc, 0))

    def test_the_overrides_apply_and_restore(self):
        before = handler._apply_config({"LIVING_PHOTOS": "0", "LIVING_PHOTOS_STRENGTH": "0.02"})
        try:
            self.assertFalse(config.LIVING_PHOTOS)
            self.assertEqual(config.LIVING_PHOTOS_STRENGTH, 0.02)
        finally:
            handler._restore_config(before)
        self.assertTrue(config.LIVING_PHOTOS)
        self.assertEqual(config.LIVING_PHOTOS_STRENGTH, 0.06)

    def test_the_model_is_the_commercially_licensed_small_one(self):
        spec = importlib.util.spec_from_file_location("fetch_models", os.path.join(ROOT, "scripts", "fetch_models.py"))
        fm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fm)
        repo = fm.DEPTH_REPO.lower()
        self.assertIn("small", repo)
        self.assertNotIn("base", repo)
        self.assertNotIn("large", repo)                                # CC-BY-NC: never
        self.assertRegex(fm.DEPTH_REV, r"^[0-9a-f]{40}$")              # pinned
        self.assertRegex(fm.DEPTH_FILE[1], r"^[0-9a-f]{64}$")          # checksummed
        self.assertTrue(config.LIVING_DEPTH_MODEL.replace("\\", "/").endswith(fm.DEPTH_DEST.replace("\\", "/")))
        with open(os.path.join(ROOT, "scripts", "fetch_models.py"), encoding="utf-8") as fh:
            self.assertIn("Apache-2.0", fh.read())


class Cuts(unittest.TestCase):
    def test_an_object_in_front_is_one_clean_cut(self):
        plan = living.plan_cuts(_depth())
        self.assertEqual(len(plan["cuts"]), 1)
        self.assertGreaterEqual(plan["quality"], living.MIN_EDGE_SHARE)
        self.assertTrue(0.1 < plan["cuts"][0] < 0.9)
        self.assertEqual(len(plan["depths"]), 2)
        self.assertLess(plan["depths"][0], plan["depths"][1])
        # The camera turns about the near block's middle (picture shares).
        self.assertAlmostEqual(plan["focus"]["x"], 105 / 200, delta=0.03)
        self.assertAlmostEqual(plan["focus"]["y"], 80 / 125, delta=0.03)

    def test_a_smooth_slope_is_never_cut(self):
        d = np.tile(np.linspace(0, 1, 125, dtype=np.float32)[:, None], (1, 200))
        plan = living.plan_cuts(d)
        self.assertEqual(plan["cuts"], [])
        self.assertEqual(plan["why"], "no clear depth edge")

    def test_three_planes_make_three_layers(self):
        d = np.full((125, 200), 0.05, np.float32)
        d[50:125, 20:180] = 0.5                     # the middle ground
        d[70:115, 70:120] = 0.95                    # the near object
        plan = living.plan_cuts(d, max_layers=3)
        self.assertEqual(len(plan["cuts"]), 2)
        self.assertEqual(len(plan["depths"]), 3)
        self.assertEqual(plan["depths"], sorted(plan["depths"]))
        self.assertEqual(len(living.plan_cuts(d, max_layers=2)["cuts"]), 1)

    def test_a_flat_or_tiny_map_has_no_cut(self):
        self.assertEqual(living.plan_cuts(np.full((100, 160), 0.4, np.float32))["cuts"], [])
        self.assertEqual(living.plan_cuts(None)["cuts"], [])
        self.assertEqual(living.plan_cuts(np.zeros((8, 8), np.float32))["cuts"], [])

    def test_strength_is_subtle_and_follows_the_cut(self):
        clean = living.strength_for({"quality": 0.9, "depths": [0.05, 0.9]})
        weak = living.strength_for({"quality": 0.56, "depths": [0.3, 0.6]})
        self.assertAlmostEqual(clean, config.LIVING_PHOTOS_STRENGTH, places=4)
        self.assertLess(weak, clean)
        self.assertGreater(weak, 0.2 * clean)
        # A flaw it would show scales the move down instead.
        busy = living.strength_for({"quality": 0.9, "depths": [0.05, 0.9], "intricate": 13.5})
        filled = living.strength_for({"quality": 0.9, "depths": [0.05, 0.9]}, {"fallback": 0.5})
        self.assertLess(busy, clean)
        self.assertLess(filled, clean)
        self.assertEqual(set(living.safety({"quality": 0.9})), {"edges", "outline", "fill", "front"})
        self.assertLessEqual(clean, living.MAX_STRENGTH)


class Fills(unittest.TestCase):
    def test_push_pull_keeps_what_is_known_and_fills_the_rest_from_it(self):
        rgb = np.zeros((40, 60, 3), np.float32)
        rgb[:, :30] = (200, 0, 0)
        rgb[:, 30:] = (0, 0, 200)
        w = np.ones((40, 60), np.float32)
        w[10:30, 25:35] = 0                           # a hole across the colour edge
        out = living.push_pull(rgb, w)
        self.assertTrue(np.allclose(out[w > 0], rgb[w > 0], atol=1.0))
        self.assertGreater(out[20, 26, 0], out[20, 26, 2])           # red side stays reddish
        self.assertGreater(out[20, 34, 2], out[20, 34, 0])           # blue side bluish
        self.assertTrue(np.isfinite(out).all())

    def test_mirror_fill_continues_the_rows_own_background(self):
        rgb = np.zeros((4, 20, 3), np.float32)
        rgb[..., 0] = np.arange(20)[None, :] * 10     # a ramp along the row: its texture
        known = np.ones((4, 20), bool)
        known[:, 10:14] = False                       # a hole in the middle of each row
        fallback = np.full((4, 20, 3), -1.0, np.float32)
        out = living.mirror_fill(rgb, known, fallback)
        self.assertTrue(np.array_equal(out[known], rgb[known]))
        # Beside the left edge: mostly the left side's own pixels mirrored (9, 8, ...), blended
        # toward the right side's (14, 15, ...) by distance.
        left_only = living.mirror_fill(rgb, np.concatenate([known[:, :14], np.zeros((4, 6), bool)], axis=1), fallback)
        self.assertEqual(left_only[0, 10, 0], rgb[0, 9, 0])
        self.assertEqual(left_only[0, 11, 0], rgb[0, 8, 0])
        self.assertTrue(rgb[0, 9, 0] < out[0, 10, 0] < out[0, 13, 0] <= rgb[0, 16, 0])
        self.assertTrue((out[..., 0] >= 0).all())      # never the fallback where a row has background
        # A row with nothing known: the fallback.
        known[2] = False
        out = living.mirror_fill(rgb, known, fallback)
        self.assertTrue((out[2] == -1.0).all())

    def test_filters_match_plain_numpy(self):
        a = np.random.default_rng(1).random((30, 40)).astype(np.float32)
        p = np.pad(a, 2, mode="edge")
        want_max = np.max(np.stack([p[i:i + 30, j:j + 40] for i in range(5) for j in range(5)]), axis=0)
        want_box = np.mean(np.stack([p[i:i + 30, j:j + 40] for i in range(5) for j in range(5)]), axis=0)
        self.assertTrue(np.allclose(living._maxf(a, 2), want_max))
        self.assertTrue(np.allclose(living._box(a, 2), want_box, atol=1e-5))


class Layers(unittest.TestCase):
    def test_layers_are_written_back_to_front_with_the_hidden_part_filled(self):
        with tempfile.TemporaryDirectory() as d:
            path = _picture(os.path.join(d, "s0001.jpg"))
            im = Image.open(path).convert("RGB")
            dmap = _depth()
            plan = living.plan_cuts(dmap)
            out = living.make_layers(im, plan, os.path.join(d, "s0001"), 1920, 1080, 1.2, d=dmap)
            self.assertEqual(len(out), 2)
            back, front = out
            self.assertTrue(back["path"].endswith(".living0.jpg"))
            self.assertTrue(front["path"].endswith(".living1.webp"))
            self.assertNotIn("box", back)
            with Image.open(back["path"]) as b:
                self.assertEqual(b.size, im.size)       # never bigger than the picture, same shape
                bb = np.asarray(b.convert("RGB"), np.float32)
            # Behind the block: background, not the block's red.
            self.assertLess(bb[320, 420, 0] - bb[320, 420, 2], 60)
            with Image.open(front["path"]) as f:
                self.assertEqual(f.mode, "RGBA")
                alpha = np.asarray(f.getchannel("A"))
            x0, y0, x1, y1 = front["box"]
            self.assertTrue(0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0)
            # The cut follows the block (320..520 x 220..420 of 800 x 500), a few px of room.
            self.assertAlmostEqual(x0, 320 / 800, delta=0.03)
            self.assertAlmostEqual(x1, 520 / 800, delta=0.03)
            self.assertAlmostEqual(y1, 420 / 500, delta=0.04)
            self.assertGreater(alpha[alpha.shape[0] // 2, alpha.shape[1] // 2], 240)     # the block: solid
            self.assertLess(back["depth"], front["depth"])

    def test_at_rest_the_stack_draws_exactly_the_picture(self):
        # Regression: a soft edge over a filled background drew a stripe of the fill (a bluish band
        # along a rock over a lake) even while nothing moved. The edge colours are solved (a matte).
        with tempfile.TemporaryDirectory() as d:
            path = _picture(os.path.join(d, "s0002.jpg"))
            im = Image.open(path).convert("RGB")
            dmap = _depth()
            soft = living._box(np.asarray(dmap), 2)              # a soft, wide depth edge
            plan = living.plan_cuts(soft)
            with mock.patch.object(living, "DOF_RADIUS", 0):     # (the depth of field blurs the far part on purpose)
                layers = living.make_layers(im, plan, os.path.join(d, "s0002"), 1920, 1080, 1.2, d=soft)
            stack = Image.open(layers[0]["path"]).convert("RGBA")
            for x in layers[1:]:
                part = Image.open(x["path"]).convert("RGBA")
                at = (int(round(x["box"][0] * stack.width)), int(round(x["box"][1] * stack.height)))
                stack.alpha_composite(part, at)
            diff = np.abs(np.asarray(stack.convert("RGB"), np.float32) - np.asarray(im, np.float32))
            self.assertLess(float(diff.mean()), 3.0)
            self.assertLess(float(np.percentile(diff, 99.5)), 20.0)        # JPEG / WebP, not a stripe

    def test_a_close_subject_gets_a_soft_background(self):
        # Depth of field: the far part of the back layer softly blurred, the near block sharp.
        with tempfile.TemporaryDirectory() as d:
            im = Image.open(_picture(os.path.join(d, "s0003.jpg"))).convert("RGB")
            dmap = _depth()
            plan = living.plan_cuts(dmap)
            info = {}
            layers = living.make_layers(im, plan, os.path.join(d, "s0003"), 1920, 1080, 1.2, d=dmap, info=info)
            self.assertGreater(info["dof"], 0)
            back = np.asarray(Image.open(layers[0]["path"]).convert("L"), np.float32)
            orig = np.asarray(im.convert("L"), np.float32)

            def detail(a, y0, y1, x0, x1):
                return float(np.abs(np.diff(a[y0:y1, x0:x1], axis=1)).mean())
            self.assertLess(detail(back, 20, 120, 20, 300), 0.8 * detail(orig, 20, 120, 20, 300))   # far: softer
            front = np.asarray(Image.open(layers[1]["path"]).convert("RGB"))
            self.assertGreater(front.shape[0], 10)
            # No depth of field without a close subject.
            self.assertEqual(living.dof_radius({"depths": [0.4, 0.6], "front": 0.3}, 800, 500, 1920, 1080), 0.0)
            self.assertEqual(living.dof_radius({"depths": [0.1, 0.9], "front": 0.01}, 800, 500, 1920, 1080), 0.0)

    def test_layer_size_never_exceeds_the_picture_or_what_the_frame_shows(self):
        self.assertEqual(living.layer_size(1920, 1280, 1920, 1080, 1.2), (1920, 1280))
        w, h = living.layer_size(3840, 2560, 1920, 1080, 1.2)
        self.assertEqual((w, h), (2304, 1536))       # the cover fit x the zoom, the picture's shape
        self.assertEqual(living.layer_size(1000, 600, 1920, 1080, 1.2), (1000, 600))

    def test_a_soft_picture_or_a_wrong_kind_gets_no_layers(self):
        with tempfile.TemporaryDirectory() as d:
            path = _picture(os.path.join(d, "x.jpg"))
            with mock.patch.object(living, "picture_reason", return_value="a map"):
                got = living.build(path, "zoom-in")
            self.assertEqual(got["why"], "a map")
            self.assertIn("cpu", got)
            with mock.patch.object(living, "picture_reason", return_value=""), \
                    mock.patch.object(living, "depth_map", return_value=_depth()), \
                    mock.patch.object(living, "sharp_enough", return_value=False):
                got = living.build(path, "zoom-in")
            self.assertEqual(got["why"], "too soft for the move")
            self.assertFalse([f for f in os.listdir(d) if ".living" in f])
            with mock.patch.object(living, "picture_reason", return_value=""), \
                    mock.patch.object(living, "depth_map", return_value=_depth()), \
                    mock.patch.object(living, "sharp_enough", return_value=True):
                got = living.build(path, "zoom-in")
            self.assertEqual(len(got["layers"]), 2)
            self.assertGreater(got["zoom"], 1.15)          # the push, a little closer for the near layer

    def test_a_broken_file_is_never_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.jpg")
            with open(p, "wb") as fh:
                fh.write(b"<html>not a picture</html>")
            got = living.build(p, "zoom-in")
            self.assertTrue(got["why"].startswith("failed"))
            self.assertTrue(got.get("error"))

    def test_the_known_magnification_spares_a_measure(self):
        with mock.patch.multiple(config, PICTURE_SHARPNESS_CHECK=True, MAX_PICTURE_MAGNIFICATION=1.86), \
                mock.patch("src.sharpness.picture_check", return_value={"ok": False}) as measured:
            self.assertTrue(living.sharp_enough("x.jpg", 1.2, known=1.4))       # 1.4 x 1.2/1.16 < 1.86
            measured.assert_not_called()
            self.assertFalse(living.sharp_enough("x.jpg", 1.2, known=1.85))     # over: measured now
            measured.assert_called_once()

    @unittest.skipUnless(os.path.isfile(config.LIVING_DEPTH_MODEL), "depth model not installed")
    def test_the_model_runs(self):
        with tempfile.TemporaryDirectory() as d:
            im = Image.open(_picture(os.path.join(d, "m.jpg"))).convert("RGB")
            dm = living.depth_map(im)
            self.assertEqual(dm.ndim, 2)
            self.assertTrue(0.0 <= float(dm.min()) and float(dm.max()) <= 1.0)
            self.assertEqual(dm.shape[0] % 14, 0)


class Pictures(unittest.TestCase):
    def setUp(self):
        self.fps = 30.0

    def test_only_full_frame_moving_local_stills_of_scenes(self):
        with tempfile.TemporaryDirectory() as d:
            p = _picture(os.path.join(d, "a.jpg"))
            ok = _still_scene(0, p)
            self.assertEqual(living.scene_reason(ok, self.fps), "")
            cases = {
                "not a still": _still_scene(0, p, media={"type": "video", "url": p, "source": "youtube"}),
                "inset or window frame": _still_scene(0, p, frame="inset"),
                "held still": _still_scene(0, p, motion="none"),
                "short shot": _still_scene(0, p, seconds=1.0),
                "a document": _still_scene(0, p, semanticMetadata={"subjectType": "document"}),
                "the editor's own framing": _still_scene(0, p, reframe="off"),
                "off for this scene": _still_scene(0, p, living="off"),
                "not on this disk": _still_scene(0, "https://pub.example/a.jpg"),
            }
            for why, s in cases.items():
                self.assertEqual(living.scene_reason(s, self.fps), why, why)
            # A ken-burns still with no motion of its own moves (SceneClip draws it as a push).
            self.assertEqual(living.scene_reason(_still_scene(0, p, motion="none", effect="ken-burns"), self.fps), "")

    def test_close_up_faces_and_lettering_found_by_the_reframe_pass(self):
        with tempfile.TemporaryDirectory() as d:
            p = _picture(os.path.join(d, "a.jpg"))
            face = _still_scene(0, p)
            face["media"]["focus"] = {"kind": "face", "faceBoxes": [[0.3, 0.2, 0.2, 0.3]]}
            self.assertEqual(living.scene_reason(face, self.fps), "a face in close-up")
            far = _still_scene(0, p)
            far["media"]["focus"] = {"kind": "face", "faceBoxes": [[0.3, 0.2, 0.03, 0.05]]}
            self.assertEqual(living.scene_reason(far, self.fps), "")       # people in a landscape: fine
            text = _still_scene(0, p)
            text["media"]["focus"] = {"kind": "text"}
            self.assertEqual(living.scene_reason(text, self.fps), "lettering on the picture")

    def test_a_graphic_pointing_into_the_picture_keeps_it_still(self):
        with tempfile.TemporaryDirectory() as d:
            s = _still_scene(0, _picture(os.path.join(d, "a.jpg")))
            doc = _doc([s])
            doc["overlays"] = [{"type": "arrow", "startFrame": 30, "durationInFrames": 60, "anchor": {"x": 0.5, "y": 0.5}}]
            self.assertEqual(living.scene_reason(s, self.fps, living._anchored(doc)), "a graphic points into it")

    def test_documents_maps_and_illustrations_by_their_classes(self):
        im = Image.new("RGB", (800, 500), (120, 130, 140))

        def classes(**kw):
            base = {"photo": 0.5, "person": 0.0, "slide": 0.1, "text": 0.15, "map": 0.05, "chart": 0.0,
                    "logo": 0.0, "render": 0.05}
            base.update(kw)
            return base
        with mock.patch("src.reframe.faces_available", return_value=False), \
                mock.patch("src.localvision.available", return_value=True), \
                mock.patch("src.localvision.embed_images", return_value=np.zeros((1, 4))):
            for got, want in ((classes(), ""),
                              (classes(text=0.34, photo=0.48), ""),            # a landscape reads like this
                              (classes(text=0.86, photo=0.02), "a page of text"),
                              (classes(map=0.4, photo=0.3), "a map"),
                              (classes(render=0.47, photo=0.33), "an illustration or render")):
                with mock.patch("src.localvision.classify", return_value=got):
                    self.assertEqual(living.picture_reason(im), want, got)

    def test_only_a_sure_or_confirmed_face_is_a_close_up(self):
        im = Image.new("RGB", (800, 500), (120, 130, 140))
        unsure = [[0.4, 0.2, 0.1, 0.3, 0.7, 0.3]]            # YuNet on rock texture: big, 0.6-0.75
        sure = [[0.4, 0.2, 0.1, 0.3, 0.93, 0.3]]
        with mock.patch("src.reframe.faces_available", return_value=True), \
                mock.patch("src.localvision.available", return_value=False):
            with mock.patch("src.reframe._yunet", return_value=unsure):
                self.assertEqual(living.picture_reason(im), "")
            with mock.patch("src.reframe._yunet", return_value=sure):
                self.assertEqual(living.picture_reason(im), "a face in close-up")


class Place(unittest.TestCase):
    def test_eligible_stills_get_layers_bound_to_their_picture(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "LIVING_PHOTOS", True):
            a = _picture(os.path.join(d, "a.jpg"))
            b = _picture(os.path.join(d, "b.jpg"))
            doc = _doc([_still_scene(0, a), _still_scene(1, b, frame="inset"),
                        _still_scene(2, a.replace("a.jpg", "c.jpg"))])
            stats = living.place(doc, build_fn=_fake_build(d))
            liv = doc["scenes"][0]["media"]["living"]
            self.assertEqual([x["url"] for x in liv["layers"]],
                             [os.path.join(d, "a.living0.jpg"), os.path.join(d, "a.living1.webp")])
            self.assertNotIn("box", liv["layers"][0])
            self.assertEqual(liv["layers"][1]["box"], [0.4, 0.4, 0.7, 0.9])
            self.assertEqual(liv["source"], "web_image")
            self.assertEqual(liv["by"], living.MODEL)
            self.assertEqual(liv["focus"], {"x": 0.55, "y": 0.65})
            self.assertTrue(0 < liv["strength"] <= living.MAX_STRENGTH)
            self.assertEqual(set(liv["safety"]), {"edges", "outline", "fill", "front"})
            self.assertNotIn("living", doc["scenes"][1]["media"])
            self.assertNotIn("living", doc["scenes"][2]["media"])      # no file on this disk
            self.assertEqual(stats["layered"], 1)
            self.assertEqual(stats["why"]["inset or window frame"], 1)
            self.assertEqual(stats["cpuPerPicture"], 0.7)

    def test_the_time_box_leaves_the_rest_flat(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "LIVING_PHOTOS", True):
            doc = _doc([_still_scene(i, _picture(os.path.join(d, f"p{i}.jpg"))) for i in range(3)])
            stats = living.place(doc, deadline_seconds=-1, build_fn=_fake_build(d))
            self.assertEqual(stats["skippedTime"], 3)
            self.assertFalse(any("living" in s["media"] for s in doc["scenes"]))

    def test_a_failing_picture_never_fails_the_rest(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "LIVING_PHOTOS", True):
            doc = _doc([_still_scene(i, _picture(os.path.join(d, f"p{i}.jpg"))) for i in range(2)])
            good = _fake_build(d)

            def flaky(path, *a, **k):
                if path.endswith("p0.jpg"):
                    raise RuntimeError("boom")
                return good(path, *a, **k)
            stats = living.place(doc, build_fn=flaky)
            self.assertEqual(stats["layered"], 1)            # the other picture still got its layers
            self.assertNotIn("living", doc["scenes"][0]["media"])
            self.assertIn("living", doc["scenes"][1]["media"])
            self.assertTrue(any(k.startswith("failed") for k in stats["why"]))
            doc = _doc([_still_scene(i, _picture(os.path.join(d, f"q{i}.jpg"))) for i in range(2)])
            stats = living.place(doc, build_fn=lambda *a, **k: {"why": "no clear depth edge", "cpu": 0.5})
            self.assertEqual(stats["why"].get("no clear depth edge"), 2)

    def test_without_the_model_it_says_so(self):
        with mock.patch.object(config, "LIVING_PHOTOS", True), mock.patch.object(living, "available",
                                                                                  return_value=False):
            stats = living.place(_doc([]))
            self.assertIn("error", stats)

    def test_a_replaced_still_gets_its_layers(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "LIVING_PHOTOS", True), \
                mock.patch.object(living, "available", return_value=True), \
                mock.patch.object(living, "build", side_effect=_fake_build(d)):
            doc = _doc([_still_scene(0, _picture(os.path.join(d, "r.jpg")))])
            self.assertTrue(living.place_one(doc, 0))
            self.assertEqual(len(doc["scenes"][0]["media"]["living"]["layers"]), 2)


class Publish(unittest.TestCase):
    def _layered(self, d):
        doc = _doc([_still_scene(0, _picture(os.path.join(d, "a.jpg")))])
        doc["scenes"][0]["media"]["living"] = living.block(doc["scenes"][0]["media"], _fake_build(d)(
            os.path.join(d, "a.jpg"), "zoom-in", 1920, 1080))
        doc["meta"]["living"] = {"layered": 1}
        return doc

    def test_layers_go_up_with_the_scene_and_point_at_their_links(self):
        with tempfile.TemporaryDirectory() as d:
            doc = self._layered(d)
            got = living.publish(doc, lambda local, obj: f"https://r2.example/{obj}", "projects/p1/media")
            self.assertEqual(got, {"uploaded": 2, "dropped": 0})
            urls = [x["url"] for x in doc["scenes"][0]["media"]["living"]["layers"]]
            self.assertEqual(urls, ["https://r2.example/projects/p1/media/s0000-living0.jpg",
                                    "https://r2.example/projects/p1/media/s0000-living1.webp"])
            self.assertEqual(living.strip_local(doc), 0)

    def test_no_r2_or_a_failed_upload_leaves_the_still_flat(self):
        with tempfile.TemporaryDirectory() as d:
            doc = self._layered(d)
            self.assertEqual(living.publish(doc, None, "p")["dropped"], 1)
            self.assertNotIn("living", doc["scenes"][0]["media"])
            doc = self._layered(d)

            def boom(local, obj):
                raise RuntimeError("R2 down")
            self.assertEqual(living.publish(doc, boom, "p")["dropped"], 1)
            self.assertNotIn("living", doc["scenes"][0]["media"])

    def test_no_work_directory_path_is_ever_saved(self):
        with tempfile.TemporaryDirectory() as d:
            doc = self._layered(d)
            self.assertEqual(living.strip_local(doc), 1)
            self.assertNotIn("living", doc["scenes"][0]["media"])

    def test_the_handler_saves_layers_on_r2_only(self):
        with tempfile.TemporaryDirectory() as d:
            doc = self._layered(d)
            keys = []

            def upload(local, key, **kw):
                keys.append(key)
                return f"https://pub.r2.dev/{key}"
            with mock.patch.object(handler, "_scene_media_on_r2", return_value=True), \
                    mock.patch.object(handler.r2, "upload", side_effect=upload):
                got = handler._publish_living(doc, "proj1", "job1")
            self.assertEqual(got["uploaded"], 2)
            self.assertTrue(all(k.startswith("projects/proj1/media/s0000-living") for k in keys))
            self.assertTrue(all(re.search(r"-[0-9a-f]{12}\.(jpg|webp)$", k) for k in keys))   # link-only names
            self.assertEqual(doc["meta"]["living"]["published"]["uploaded"], 2)
            doc = self._layered(d)
            with mock.patch.object(handler, "_scene_media_on_r2", return_value=False):
                handler._publish_living(doc, "proj1", "job1")
            self.assertNotIn("living", doc["scenes"][0]["media"])           # a signed link would die


class Gate(unittest.TestCase):
    def test_layers_that_cannot_be_read_are_dropped_before_the_render(self):
        with tempfile.TemporaryDirectory() as d:
            vo = os.path.join(d, "vo.wav")
            with open(vo, "wb") as fh:
                fh.write(b"RIFF" + bytes(2000))
            scenes = []
            for i in range(2):
                p = _picture(os.path.join(d, f"s{i}.jpg"), w=640, h=400, square=(200, 150, 400, 350))
                s = _still_scene(i, p)
                s["media"]["living"] = living.block(s["media"], _fake_build(d)(p, "zoom-in", 1920, 1080))
                scenes.append(s)
            os.remove(scenes[1]["media"]["living"]["layers"][1]["url"])       # one layer is gone
            doc = _doc(scenes)
            doc["audio"] = {"url": vo, "volume": 1}
            doc["captions"] = {"enabled": False}
            with mock.patch.multiple(config, QUALITY_HTTP_TIMEOUT=2, QUALITY_AUDIT_SECONDS=60, ANIMATION_FILL=False,
                                     QUALITY_REPAIR_GENERATED=False):
                gate = quality.Gate(doc, d)
                gate.before_render()
                quality.reset()
            self.assertIn("living", doc["scenes"][0]["media"])
            self.assertNotIn("living", doc["scenes"][1]["media"])            # drawn flat, scene kept
            self.assertEqual(doc["scenes"][1]["media"]["url"], scenes[1]["media"]["url"])
            self.assertEqual(gate.fixed["layers"], 1)
            self.assertIn("1 living photo drawn flat", gate.summary())
            # Not a scene change the editor has to look at.
            saved = _doc([dict(s) for s in scenes])
            self.assertEqual(quality.mark_for_review(saved, {"repairs": gate.repairs}), 0)

    def test_a_render_that_failed_on_a_layer_draws_that_still_flat(self):
        with tempfile.TemporaryDirectory() as d:
            p = _picture(os.path.join(d, "s0.jpg"), w=640, h=400, square=(200, 150, 400, 350))
            s = _still_scene(0, p)
            s["media"]["living"] = living.block(s["media"], _fake_build(d)(p, "zoom-in", 1920, 1080))
            layer = s["media"]["living"]["layers"][1]["url"]
            served = "http://127.0.0.1:53111/" + os.path.relpath(layer, d).replace(os.sep, "/")
            doc = _doc([s])
            gate = quality.Gate(doc, d)
            with mock.patch.object(gate, "_gone_now", return_value={}):
                self.assertTrue(gate.recover(RuntimeError(f"Error loading image with src: {served}")))
            quality.reset()
            self.assertNotIn("living", doc["scenes"][0]["media"])
            self.assertEqual(doc["scenes"][0]["media"]["url"], p)


class Chunks(unittest.TestCase):
    def test_a_chunk_fetches_the_layers_and_draws_a_gone_one_flat(self):
        scenes = []
        for i in range(2):
            s = _still_scene(i, f"https://pub.example/media/s{i}.jpg", seconds=10.0)
            s["media"]["living"] = {"layers": [{"url": f"https://pub.example/media/s{i}-living0.jpg", "depth": 0.1},
                                               {"url": f"https://pub.example/media/s{i}-living1.webp", "depth": 0.9,
                                                "box": [0.2, 0.2, 0.6, 0.8]}], "source": "web_image"}
            scenes.append(s)
        doc = _doc(scenes)
        fetched = []

        def fake_fetch(url, path, key="", bucket="", tries=4):
            fetched.append(url)
            if url.endswith("s1-living1.webp"):
                raise fanout.Gone("404", 404)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"x")
            return path
        with tempfile.TemporaryDirectory() as work, mock.patch.object(fanout, "_fetch", side_effect=fake_fetch):
            stats = fanout._localize(doc, 0, 599, work)
            self.assertIn("https://pub.example/media/s0-living1.webp", fetched)
            self.assertTrue(os.path.isfile(doc["scenes"][0]["media"]["living"]["layers"][1]["url"]))
        self.assertNotIn("living", doc["scenes"][1]["media"])                 # gone: flat on every machine
        self.assertNotIn("missing", stats)                                    # a layer never fails the chunk


class Renderer(unittest.TestCase):
    """The renderer's half (remotion/src): read as text, the way the other contracts are checked."""

    def _src(self, *parts):
        with open(os.path.join(REMOTION, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_scene_draws_layers_and_falls_back_to_the_flat_still(self):
        clip = self._src("components", "SceneClip.tsx")
        self.assertIn("resolveLiving(scene)", clip)
        self.assertIn("<LivingPicture", clip)
        tsx = self._src("transitions", "livingPhoto.tsx")
        self.assertIn("onError={fail}", tsx)
        self.assertIn("<StillPicture", tsx)                     # what a failed layer falls back to
        self.assertIn("stillTransform(move", tsx)               # the scene's own move on the stack
        self.assertEqual(float(re.search(r"LIVING_MAX_STRENGTH = ([0-9.]+)", tsx).group(1)), living.MAX_STRENGTH)
        types = self._src("types.ts")
        self.assertIn("living?: MediaLiving", types)
        self.assertIn("export interface LivingLayer", types)

    def test_the_dolly_never_enlarges_the_subject(self):
        # livingPhoto.tsx: in a push or pull only the far layers change scale (they zoom less);
        # the subject keeps the move's own zoom - so the sharpness check needs only the
        # overscan's small allowance (ZOOM_GAIN) on top of the move.
        tsx = self._src("transitions", "livingPhoto.tsx")
        self.assertIn("s: 1 - far * amp * DOLLY_GAIN * e", tsx)
        self.assertIn("s: 1 - far * amp * DOLLY_GAIN * (1 - e)", tsx)
        self.assertLessEqual(living.ZOOM_GAIN, 0.5)
        with mock.patch.object(config, "LIVING_PHOTOS_STRENGTH", 0.06):
            self.assertAlmostEqual(living.move_zoom("zoom-in"), 1.15 * (1 + living.ZOOM_GAIN * 0.06), places=3)
            self.assertAlmostEqual(living.move_zoom("parallax"), living.move_zoom("pan-left"))

    def test_the_fill_reaches_past_the_widest_reveal(self):
        # livingPhoto.tsx parts the layers by at most about half the strength either side.
        for s in (0.035, 0.06, 0.085, 0.1):
            self.assertGreaterEqual(living.reveal_share(s), 0.5 * s + 0.01)
