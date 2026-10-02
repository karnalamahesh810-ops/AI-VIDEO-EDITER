"""
Smart reframing (src/reframe.py, remotion/src/components/reframe.ts).

The owner (2026-10-01): "auto-zoom/crop onto the subject (faces, landmarks,
the action) instead of static wide shots - it feels hand-edited". The rules
that make it safe are what is tested here: the subject is inside every frame
of a move, no move on a moving camera, a cut, burned-in text or a logo, a
soft picture, a short shot or news footage, never past the scale caps, not
every shot, and the document stays pure JSON the renderer draws the same way
on every machine.
"""
import copy
import json
import math
import os
import re
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

from src import config, reframe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FA = 16 / 9


def focus(kind="object", box=None, confidence=0.9, lines=900, src=1080, moving=False, **extra):
    f = {"kind": kind, "box": box or {"x": 0.55, "y": 0.3, "w": 0.2, "h": 0.3}, "confidence": confidence,
         "lines": lines, "srcLines": src, "aspect": FA, "overlay": False,
         "bars": {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0},
         "motion": {"moving": moving, "cut": False, "pan": 0.0, "zoom": 0.0, "shake": 0.0}}
    f.update(extra)
    return f


def inside(outer, inner, eps=1e-3):
    return reframe.contains(outer, inner, eps)


class Planner(unittest.TestCase):
    def test_a_push_keeps_the_subject_in_every_frame(self):
        plan = reframe.plan_clip(focus(), 6.0, FA, "push")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["kind"], "push")
        self.assertEqual(plan["from"], reframe.FULL)
        for p in np.linspace(0, 1, 21):
            view = reframe.box_at(plan, float(p))
            self.assertTrue(inside(view, plan["subject"]), (p, view))
            # Never outside the frame: no edge of black.
            self.assertGreaterEqual(view["x"], -1e-6)
            self.assertGreaterEqual(view["y"], -1e-6)
            self.assertLessEqual(view["x"] + view["w"], 1 + 1e-6)
            self.assertLessEqual(view["y"] + view["h"], 1 + 1e-6)
        # The frame's own shape: a viewport is as tall as it is wide (in frame shares).
        self.assertAlmostEqual(plan["to"]["w"], plan["to"]["h"], places=3)
        self.assertGreaterEqual(plan["zoom"], reframe.MIN_SCALE)

    def test_a_pull_starts_on_the_subject_and_ends_on_the_whole_frame(self):
        plan = reframe.plan_clip(focus(), 6.0, FA, "pull")
        self.assertEqual(plan["kind"], "pull")
        self.assertEqual(plan["to"], reframe.FULL)
        self.assertTrue(inside(plan["from"], plan["subject"]))

    def test_a_drift_is_a_lateral_reframe_at_one_scale(self):
        plan = reframe.plan_clip(focus(box={"x": 0.6, "y": 0.35, "w": 0.12, "h": 0.2}), 7.0, FA, "drift")
        self.assertEqual(plan["kind"], "drift")
        self.assertAlmostEqual(plan["from"]["w"], plan["to"]["w"], places=4)
        self.assertGreater(abs(plan["from"]["x"] - plan["to"]["x"]), 0.035)
        for p in np.linspace(0, 1, 11):
            self.assertTrue(inside(reframe.box_at(plan, float(p)), plan["subject"]))
        self.assertLessEqual(abs(plan["from"]["x"] - plan["to"]["x"]) / 7.0, reframe.PAN_RATE + 1e-6)

    def test_a_pull_after_a_zoom_entrance_becomes_a_push(self):
        plan = reframe.plan_clip(focus(), 6.0, FA, "pull", transition="zoom-punch")
        self.assertEqual(plan["kind"], "push")

    def test_a_face_is_framed_with_its_eyes_high(self):
        f = focus("face", box={"x": 0.3, "y": 0.2, "w": 0.16, "h": 0.42}, eye=0.32)
        plan = reframe.plan_clip(f, 6.0, FA, "push")
        self.assertIsNotNone(plan)
        to = plan["to"]
        eye_share = (0.32 - to["y"]) / to["h"]
        self.assertLess(eye_share, 0.5)        # above the middle of the frame, toward the upper third

    def test_no_move_when_it_is_not_safe(self):
        cases = {
            "camera moves": focus(moving=True),
            "a cut inside": dict(focus(), motion={"moving": False, "cut": True}),
            "burned-in text": focus(overlay=True),
            "letterbox": focus(bars={"left": 0.1, "right": 0.1, "top": 0, "bottom": 0}),
            "unsure": focus(confidence=0.3),
            "soft picture": focus(lines=420),
            "SD file": focus(src=360, lines=360),
            "no subject": focus(kind="none"),
            "subject fills the frame": focus(box={"x": 0.02, "y": 0.02, "w": 0.95, "h": 0.95}),
        }
        for why, f in cases.items():
            with self.subTest(why):
                self.assertIsNone(reframe.plan_clip(f, 6.0, FA, "push"))

    def test_no_move_on_a_short_shot(self):
        self.assertIsNone(reframe.plan_clip(focus(), config.REFRAME_MIN_SECONDS - 0.2, FA, "push"))

    def test_scale_caps(self):
        # About 1.15x at most on a 720p-class picture, more only on real 1080p detail.
        self.assertLessEqual(reframe.scale_cap({"lines": 700, "srcLines": 720}), 1.15)
        with mock.patch.object(config, "REFRAME_MAX_SCALE", 1.3):
            self.assertLessEqual(reframe.scale_cap({"lines": 700, "srcLines": 1080}), 1.15)
            self.assertAlmostEqual(reframe.scale_cap({"lines": 900, "srcLines": 1080}), 1.2)
            self.assertLessEqual(reframe.scale_cap({"lines": 560, "srcLines": 1080}), 1.1)
        self.assertEqual(reframe.scale_cap({"lines": 400, "srcLines": 1080}), 0.0)
        # A 540p clip sharpened up to 1080 (upscale_clip) is SD whatever its file says.
        self.assertLessEqual(reframe.scale_cap({"lines": 900, "srcLines": 540}), 1.1)
        tiny = {"x": 0.45, "y": 0.45, "w": 0.04, "h": 0.06}
        for lines, src in ((700, 720), (900, 1080), (2000, 2160)):
            plan = reframe.plan_clip(focus(box=tiny, lines=lines, src=src), 30.0, FA, "push")
            self.assertLessEqual(plan["zoom"], config.REFRAME_MAX_SCALE + 1e-9)
            self.assertLessEqual(plan["zoom"], reframe.scale_cap({"lines": lines, "srcLines": src}) + 1e-9)

    def test_the_push_is_slow(self):
        tiny = {"x": 0.45, "y": 0.45, "w": 0.04, "h": 0.06}
        plan = reframe.plan_clip(focus(box=tiny), 3.2, FA, "push")
        self.assertLessEqual(plan["zoom"] - 1, reframe.ZOOM_RATE * 3.2 + 1e-6)
        corner = {"x": 0.88, "y": 0.05, "w": 0.08, "h": 0.1}
        plan = reframe.plan_clip(focus(box=corner), 3.5, FA, "push")
        if plan:
            to = plan["to"]
            travel = math.hypot(to["x"] + to["w"] / 2 - 0.5, to["y"] + to["h"] / 2 - 0.5)
            self.assertLessEqual(travel / 3.5, reframe.PAN_RATE + 1e-6)

    def test_a_corner_logo_stays_whole(self):
        logo = {"x": 0.78, "y": 0.0, "w": 0.22, "h": 0.3}
        near = reframe.plan_clip(focus(box={"x": 0.6, "y": 0.1, "w": 0.15, "h": 0.2}, logos=[logo]), 6.0, FA)
        if near:
            self.assertTrue(inside(near["to"], logo))
        across = reframe.plan_clip(focus(box={"x": 0.02, "y": 0.6, "w": 0.2, "h": 0.3}, logos=[logo]), 6.0, FA)
        self.assertIsNone(across)

    def test_cover_box_follows_the_cover_fit(self):
        # A 4:3 picture in a 16:9 frame loses its top and bottom eighths.
        b = reframe.cover_box({"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.25}, 4 / 3, FA)
        self.assertAlmostEqual(b["x"], 0.25)
        self.assertAlmostEqual(b["y"], (0.5 - 0.125) / 0.75)
        self.assertAlmostEqual(b["h"], 0.25 / 0.75)
        # Mostly off screen: no box.
        self.assertIsNone(reframe.cover_box({"x": 0.4, "y": 0.0, "w": 0.2, "h": 0.1}, 4 / 3, FA))

    def test_the_ease_matches_the_renderer(self):
        ts = open(os.path.join(ROOT, "remotion", "src", "components", "reframe.ts"), encoding="utf-8").read()
        m = re.search(r"REFRAME_EASE = Easing\.bezier\(([^)]*)\)", ts)
        self.assertIsNotNone(m)
        self.assertEqual([float(v) for v in m.group(1).split(",")], [0.45, 0.05, 0.55, 0.95])
        self.assertAlmostEqual(reframe.bezier(0.0), 0.0)
        self.assertAlmostEqual(reframe.bezier(1.0), 1.0)
        self.assertAlmostEqual(reframe.bezier(0.5), 0.5, places=3)
        self.assertLess(reframe.bezier(0.1), 0.05)             # gentle start
        self.assertGreater(reframe.bezier(0.9), 0.95)          # gentle landing


def scene(i, seconds, kind="video", url="", **kw):
    m = {"type": kind, "url": url, "source": kw.pop("source", "youtube"),
         "attribution": kw.pop("attribution", "YouTube: Lake Powell from the shore")}
    return {"id": f"s{i:04d}", "startFrame": int(i * 1000), "durationInFrames": int(seconds * 30),
            "frame": kw.pop("frame", "full"), "motion": kw.pop("motion", "none"), "effect": "none",
            "transition": kw.pop("transition", "none"), "media": m, **kw}


class Pass(unittest.TestCase):
    def setUp(self):
        self.files = []
        for ext in (".mp4", ".jpg"):
            fd, p = tempfile.mkstemp(suffix=ext)
            os.write(fd, b"x")
            os.close(fd)
            self.files.append(p)
            self.addCleanup(os.remove, p)
        self.clip, self.photo = self.files
        patches = [mock.patch.object(config, "REFRAME_ENABLED", True),
                   mock.patch.object(config, "REFRAME_CLIPS", True),
                   mock.patch.object(config, "REFRAME_STILLS", True),
                   mock.patch.object(config, "REFRAME_SHARE", 1.0)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def doc(self, scenes, overlays=None):
        return {"fps": 30, "width": 1920, "height": 1080, "scenes": scenes, "overlays": list(overlays or []),
                "meta": {}}

    def detect(self, f=None):
        return mock.Mock(side_effect=lambda path, secs: copy.deepcopy(f or focus()))

    def test_off_by_default_writes_nothing(self):
        with mock.patch.object(config, "REFRAME_ENABLED", False):
            d = self.doc([scene(0, 6, url=self.clip)])
            self.assertEqual(reframe.place(d, detect_clip_fn=self.detect()), {})
            self.assertNotIn("reframe", d["scenes"][0]["media"])
            self.assertNotIn("focus", d["scenes"][0]["media"])

    def test_a_static_clip_gets_a_bound_move_and_a_focus(self):
        d = self.doc([scene(0, 6, url=self.clip)])
        stats = reframe.place(d, detect_clip_fn=self.detect())
        m = d["scenes"][0]["media"]
        self.assertEqual(stats["moved"], 1)
        self.assertEqual(m["focus"]["kind"], "object")
        r = m["reframe"]
        self.assertEqual(r["source"], "youtube")            # bound to this picture (the renderer checks it)
        self.assertAlmostEqual(r["aspect"], round(FA, 4))
        self.assertAlmostEqual(r["seconds"], 6.0)
        self.assertEqual(r["by"], "auto")
        self.assertIn(r["kind"], ("push", "pull", "drift"))
        json.dumps(d)                                        # pure JSON: saved with the timeline

    def test_what_is_never_moved(self):
        d = self.doc([
            scene(0, 6, url=self.clip, attribution="YouTube: FOX 10 News - Lake Powell"),
            scene(1, 2.0, url=self.clip),
            scene(2, 6, url=self.clip, frame="inset"),
            scene(3, 6, url=self.clip, reframe="off"),
            scene(4, 6, url="https://cdn.example/clip.mp4"),
            scene(5, 6, url=self.clip),
        ], overlays=[{"type": "motion", "template": "LIB_VM_ARROW", "startFrame": 5000, "durationInFrames": 90,
                      "anchor": {"x": 0.5, "y": 0.5}}])
        detect = self.detect()
        stats = reframe.place(d, detect_clip_fn=detect)
        self.assertEqual(stats["moved"], 0)
        self.assertEqual(detect.call_count, 0)
        why = stats["why"]
        self.assertEqual(why.get("news footage"), 1)
        self.assertEqual(why.get("short shot"), 1)
        self.assertEqual(why.get("a graphic points into it"), 1)
        for s in d["scenes"]:
            self.assertNotIn("reframe", s["media"])

    def test_a_vertical_clip_framed_on_its_blur_is_left_alone(self):
        d = self.doc([scene(0, 6, url=self.clip)])
        with mock.patch("src.upscale.is_framed", return_value=True):
            stats = reframe.place(d, detect_clip_fn=self.detect())
        self.assertEqual(stats["moved"], 0)
        self.assertEqual(stats["why"].get("vertical clip framed on its blur"), 1)

    def test_the_news_styles_keep_clips_as_shot(self):
        from src import styles
        for name in ("news_compilation", "nature_weather", "trending_news"):
            self.assertIs(styles.STYLES[name]["config"].get("REFRAME_CLIPS"), False, name)
        d = self.doc([scene(0, 6, url=self.clip)])
        with mock.patch.object(config, "REFRAME_CLIPS", False):
            stats = reframe.place(d, detect_clip_fn=self.detect())
        self.assertEqual(stats["moved"], 0)
        import handler
        for key in ("REFRAME_ENABLED", "REFRAME_CLIPS", "REFRAME_STILLS", "REFRAME_MAX_SCALE"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)

    def test_not_every_shot_moves_and_never_two_in_a_row(self):
        d = self.doc([scene(i, 6, url=self.clip) for i in range(10)])
        with mock.patch.object(config, "REFRAME_SHARE", 0.6):
            stats = reframe.place(d, detect_clip_fn=self.detect())
        moved = [i for i, s in enumerate(d["scenes"]) if s["media"].get("reframe")]
        self.assertTrue(moved)
        self.assertLessEqual(len(moved), math.ceil(0.6 * 10))
        self.assertTrue(all(b - a > 1 for a, b in zip(moved, moved[1:])), moved)
        self.assertEqual(stats["moved"], len(moved))
        # Neighbouring moves differ: the kinds turn.
        kinds = [d["scenes"][i]["media"]["reframe"]["kind"] for i in moved]
        self.assertGreater(len(set(kinds)), 1)

    def test_the_same_document_gives_the_same_moves(self):
        a = self.doc([scene(i, 6, url=self.clip) for i in range(6)])
        b = copy.deepcopy(a)
        reframe.place(a, detect_clip_fn=self.detect())
        reframe.place(b, detect_clip_fn=self.detect())
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_a_planned_document_is_not_planned_again(self):
        d = self.doc([scene(0, 6, url=self.clip)])
        reframe.place(d, detect_clip_fn=self.detect())
        first = copy.deepcopy(d)
        detect = self.detect()
        reframe.place(d, detect_clip_fn=detect)
        self.assertEqual(detect.call_count, 0)
        self.assertEqual(d, first)

    def test_the_time_box_holds(self):
        def slow(path, secs):
            time.sleep(0.4)
            return focus()
        d = self.doc([scene(i, 6, url=self.clip) for i in range(12)])
        with mock.patch.object(config, "REFRAME_PARALLEL", 2):
            t0 = time.time()
            stats = reframe.place(d, deadline_seconds=0.5, detect_clip_fn=slow)
        self.assertLess(time.time() - t0, 8.0)
        self.assertGreater(stats["skippedTime"], 0)

    def test_a_failing_detector_never_fails_the_job(self):
        d = self.doc([scene(0, 6, url=self.clip)])
        stats = reframe.place(d, detect_clip_fn=mock.Mock(side_effect=RuntimeError("ffmpeg died")))
        self.assertEqual(stats["moved"], 0)
        self.assertNotIn("reframe", d["scenes"][0]["media"])

    def test_stills_keep_their_motion_and_get_a_subject(self):
        d = self.doc([scene(0, 5, kind="image", url=self.photo, motion="push-offcenter", source="web_image"),
                      scene(1, 5, kind="image", url=self.photo, motion="parallax", source="web_image"),
                      scene(2, 5, kind="image", url=self.photo, motion="none", source="web_image")])
        still = mock.Mock(return_value=focus())
        stats = reframe.place(d, detect_still_fn=still)
        self.assertEqual(stats["aimed"], 1)
        s0 = d["scenes"][0]
        self.assertEqual(s0["motion"], "push-offcenter")
        r = s0["media"]["reframe"]
        self.assertEqual(set(r), {"subject", "aspect", "source", "by"})
        self.assertEqual(r["source"], "web_image")
        self.assertEqual(still.call_count, 1)               # parallax shows the whole print; "none" holds still

    def test_a_still_whose_subject_fills_it_is_not_aimed(self):
        d = self.doc([scene(0, 5, kind="image", url=self.photo, motion="zoom-in", source="web_image")])
        big = focus(box={"x": 0.0, "y": 0.0, "w": 0.95, "h": 0.9})
        reframe.place(d, detect_still_fn=mock.Mock(return_value=big))
        self.assertNotIn("reframe", d["scenes"][0]["media"])


class Detection(unittest.TestCase):
    """The pixel measures on synthetic frames (no model, no ffmpeg)."""

    @staticmethod
    def texture(seed=1, h=180, w=320):
        rng = np.random.default_rng(seed)
        base = rng.random((h // 4 + 8, w // 4 + 8)).astype(np.float32)
        big = np.kron(base, np.ones((4, 4), np.float32))
        return (reframe._blur(big, 1.0) * 255).astype(np.float32)

    def test_a_locked_off_shot_is_still(self):
        g = self.texture()
        rng = np.random.default_rng(2)
        frames = [np.clip(g[:180, :320] + rng.normal(0, 1.5, (180, 320)), 0, 255).astype(np.float32)
                  for _ in range(12)]
        m = reframe.camera_motion(frames, 0.25)
        self.assertFalse(m["moving"], m)

    def test_a_pan_is_movement(self):
        g = self.texture(h=180, w=420)
        frames = [g[:180, 4 * k:4 * k + 320].copy() for k in range(12)]
        m = reframe.camera_motion(frames, 0.25)
        self.assertTrue(m["moving"])
        self.assertGreater(m["pan"], reframe.STATIC_PAN)

    def test_a_zoom_is_movement(self):
        from PIL import Image
        g = self.texture(h=260, w=460)
        frames = []
        for k in range(12):
            s = 1.0 + 0.02 * k
            w, h = int(round(400 / s)), int(round(225 / s))
            x0, y0 = (460 - w) // 2, (260 - h) // 2
            crop = Image.fromarray(g[y0:y0 + h, x0:x0 + w].astype(np.uint8)).resize((320, 180), Image.BILINEAR)
            frames.append(np.asarray(crop, np.float32))
        m = reframe.camera_motion(frames, 0.25)
        self.assertTrue(m["moving"])
        self.assertGreater(abs(m["zoom"]), reframe.STATIC_ZOOM)

    def test_lettering_is_found_and_texture_is_not(self):
        frame = np.full((180, 320, 3), 90, np.uint8)
        for x in range(40, 280, 6):                          # a line of letters: strokes 2 px wide
            frame[140:152, x:x + 2] = 250
        self.assertTrue(reframe.text_bands(frame))
        rng = np.random.default_rng(3)
        noise = (rng.random((180, 320, 3)) * 255).astype(np.uint8)
        self.assertEqual(reframe.text_bands(noise), [])

    def test_bars_and_blurred_side_panels(self):
        frame = (np.random.default_rng(4).random((360, 640, 3)) * 255).astype(np.uint8)
        boxed = frame.copy()
        boxed[:, :80] = 0
        boxed[:, -80:] = 0
        bars = reframe.black_bars([boxed])
        self.assertGreater(bars["left"], 0.1)
        self.assertGreater(bars["right"], 0.1)
        soft = frame.copy()
        soft[:, :100] = 120
        soft[:, -100:] = 125
        self.assertGreater(reframe.black_bars([soft])["left"], 0.0)
        self.assertEqual(reframe.black_bars([frame])["left"], 0.0)

    def test_sharpness_in_lines(self):
        from PIL import Image
        # A natural picture's spectrum (power ~ 1/f^2 to the file's limit),
        # and the same picture blown up from fewer lines: an upscaled clip.
        rng = np.random.default_rng(5)
        fy = np.fft.fftfreq(1080)[:, None]
        fx = np.fft.fftfreq(1920)[None, :]
        f = np.hypot(fy, fx)
        f[0, 0] = 1
        img = np.real(np.fft.ifft2((1.0 / f) * np.exp(2j * np.pi * rng.random((1080, 1920)))))
        sharp = (255 * (img - img.min()) / (img.max() - img.min())).astype(np.uint8)

        def blown_up(lines):
            small = Image.fromarray(sharp).resize((int(lines * 16 / 9), lines), Image.LANCZOS)
            return np.asarray(small.resize((1920, 1080), Image.BICUBIC))
        self.assertEqual(reframe.effective_lines(sharp), 1080)
        measured = [reframe.effective_lines(blown_up(n)) for n in (360, 540, 720)]
        self.assertEqual(measured, sorted(measured))                # less detail, fewer lines
        self.assertLess(measured[0], 500)                            # SD blown up: never pushed
        self.assertLess(measured[1], 800)
        # Blurry everywhere (a soft old upload): far under its file's lines.
        blurry = np.asarray(Image.fromarray(sharp).resize((240, 135), Image.BILINEAR).resize((1920, 1080),
                                                                                             Image.BILINEAR))
        self.assertLess(reframe.effective_lines(blurry), 500)
        self.assertEqual(reframe.effective_lines(None), 0)
        self.assertEqual(reframe.effective_lines(np.full((1080, 1920), 128, np.uint8)), 0)

    def test_the_main_object_from_a_map(self):
        p = np.zeros((45, 80), np.float32)
        p[10:25, 50:65] = 0.95
        got = reframe.subject_from_objects(p)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got["box"][0], 50 / 80, delta=0.03)
        self.assertGreater(got["confidence"], 0.7)
        self.assertIsNone(reframe.subject_from_objects(np.full((45, 80), 0.3, np.float32)))

    def test_an_upscaled_clip_keeps_its_original_lines(self):
        from src import upscale
        fd, p = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.addCleanup(os.remove, p)
        with upscale._LOCK:
            upscale.UPSCALED[os.path.abspath(p)] = 720
        self.addCleanup(upscale.UPSCALED.pop, os.path.abspath(p), None)
        self.assertEqual(upscale.original_lines(p), 720)
        self.assertEqual(upscale.original_lines(""), 0)

    def test_numpy_values_become_plain_json(self):
        f = reframe._compact({"kind": "face", "confidence": np.float32(0.8), "lines": np.int64(900),
                              "box": {"x": np.float32(0.1), "y": 0.2, "w": 0.3, "h": 0.4},
                              "motion": {"moving": np.bool_(False), "pan": np.float64(0.01)}})
        json.dumps(f)
        self.assertIsInstance(f["confidence"], float)


class Wiring(unittest.TestCase):
    def test_the_renderer_draws_the_plan(self):
        clip = open(os.path.join(ROOT, "remotion", "src", "components", "SceneClip.tsx"), encoding="utf-8").read()
        self.assertIn("resolveMove(scene", clip)
        self.assertIn("reframeStyle(move, frame, scene.durationInFrames, fps)", clip)
        self.assertIn("subject={aim}", clip)
        types = open(os.path.join(ROOT, "remotion", "src", "types.ts"), encoding="utf-8").read()
        self.assertIn("reframe?: SceneReframe", types)
        for field in ("from?: Box", "to?: Box", "subject?: Box", "aspect?: number", "seconds?: number",
                      "source?: string"):
            self.assertIn(field, types)

    def test_the_plan_runs_while_the_files_are_local(self):
        import inspect
        import handler
        src = inspect.getsource(handler.do_plan)
        self.assertIn("reframe.place(doc)", src)
        self.assertLess(src.index("hold_or_animate"), src.index("reframe.place(doc)"))

    def test_the_models_are_baked_in_with_checksums(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("fetch_models", os.path.join(ROOT, "scripts", "fetch_models.py"))
        fm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fm)
        names = set(fm.REFRAME_FILES)
        self.assertIn(os.path.basename(config.FACE_MODEL), names)
        self.assertIn(os.path.basename(config.SALIENCY_MODEL), names)
        for url, sha in fm.REFRAME_FILES.values():
            self.assertTrue(url.startswith("https://"))
            self.assertRegex(sha, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
