"""Style Match (src/style_match): measurement on a synthetic video, the kit's clean-up, the triggers and the
motion specs it compiles to. Offline: no model call, no download (fonts come from STYLE_FONT_DIR when present)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

try:
    import cv2  # noqa: F401
    import numpy as np
    HAVE_CV = True
except Exception:  # noqa: BLE001
    HAVE_CV = False

from src.style_match import apply as sm_apply
from src.style_match import fonts, kit as sm_kit

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.dirname(HERE)


def _words(text: str, t0: float = 0.0, step: float = 0.35):
    out, t = [], t0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + step - 0.05, 2)})
        t += step
    return out


def _el(**over):
    e = {"id": "label-0", "role": "label", "name": "Label",
         "text": {"font": {"family": "Bangers", "weight": 400, "stretch": 1.3, "slant": 0}, "case": "upper", "size": 0.06,
                  "fill": "#FFFF00", "stroke": {"width": 0.003, "color": "#000000"}, "glow": {"width": 0.015, "color": "#7D7608"},
                  "shadow": None, "box": None},
         "position": {"x": 0.5, "y": 0.8, "anchor": "fixed"}, "tilt": {"median": 3.0, "range": 0.0},
         "enter": {"kind": "per-letter", "seconds": 0.36, "overshoot": 1.15, "stagger": 0.033, "unitDur": 0.1},
         "exit": {"kind": "cut", "seconds": 0}, "hold": {"median": 1.5, "grow": 1.1},
         "trigger": {"kind": "date_number"}, "frequency": {"perMin": 6}, "confidence": {"overall": 0.8}}
    e.update(over)
    return e


class LibraryParity(unittest.TestCase):
    def test_renderer_loads_the_same_fonts(self):
        ts = open(os.path.join(WORKER, "remotion", "src", "components", "smart", "styleFonts.ts"), encoding="utf-8").read()
        fams = set(re.findall(r'^  "([^"]+)": \{ load:', ts, re.M))
        self.assertEqual(fams, {f for f, _, _, _ in fonts.LIBRARY})

    def test_all_free_licences(self):
        self.assertTrue(all(lic in ("OFL", "Apache-2.0") for _, _, _, lic in fonts.LIBRARY))


class KitClean(unittest.TestCase):
    def test_clamps_and_falls_back(self):
        k = sm_kit.clean({"elements": [{"text": {"font": {"family": "Comic Sans MS"}, "size": 9, "fill": "red"},
                                        "position": {"x": 3}, "enter": {"kind": "explode"}, "hold": {"median": 99}}],
                          "audio": {"musicUnderVoiceDb": 200}})
        e = k["elements"][0]
        self.assertEqual(e["text"]["font"]["family"], fonts.DEFAULT[0])
        self.assertEqual(e["text"]["size"], 0.3)
        self.assertEqual(e["text"]["fill"], "#FFFFFF")
        self.assertEqual(e["position"]["x"], 0.96)
        self.assertEqual(e["enter"]["kind"], "cut")
        self.assertEqual(e["hold"]["median"], 12)
        self.assertEqual(k["audio"]["musicUnderVoiceDb"], 40)

    def test_card_reads(self):
        k = sm_kit.clean({"name": "Test", "elements": [_el(examples=[{"t": 1.0, "text": "480 BC"}])], "marks": []})
        c = sm_kit.card(k)
        self.assertIn("Bangers", c)
        self.assertIn("per-letter", c)


class Triggers(unittest.TestCase):
    def test_numbers_and_dates(self):
        ev = sm_apply.number_events([{"t": w["text"], "s": w["start"], "e": w["end"]} for w in
                                     _words("In 480 BC only 300 Spartans held the pass and 120,000 men waited")])
        self.assertEqual([e["text"] for e in ev], ["480 BC", "300 SPARTANS", "120,000 MEN"])

    def test_names_first_mention_only(self):
        ws = [{"t": w["text"], "s": w["start"], "e": w["end"]} for w in
              _words("Then Tom Holland met Jake Gyllenhaal and Tom Holland laughed")]
        names = [e["text"] for e in sm_apply.name_events(ws)]
        self.assertEqual(names, ["TOM HOLLAND", "JAKE GYLLENHAAL"])

    def test_captions_chunk_at_pauses_and_cuts(self):
        ws = [{"t": w["text"], "s": w["start"], "e": w["end"], "clip": False} for w in _words("one two three four five six seven eight")]
        scenes = [{"startFrame": 0}, {"startFrame": int(1.4 * 30)}]
        ev = sm_apply.caption_events(ws, scenes, 30, 2, 4)
        self.assertTrue(all(1 <= len(e["text"].split()) <= 4 for e in ev))
        self.assertEqual(" ".join(e["text"] for e in ev), "one two three four five six seven eight")


class Compile(unittest.TestCase):
    def test_text_spec_carries_the_measured_look(self):
        s = sm_apply.text_spec(_el(), "480 BC", 1.5)
        L = s["layers"][0]
        self.assertEqual(L["font"], "lib:Bangers")
        self.assertEqual(L["stretch"], 1.3)
        self.assertEqual(L["outline"]["color"], "#000000")
        self.assertEqual(L["band"]["color"], "#7D7608")
        self.assertEqual(L["animator"]["unit"], "char")
        self.assertEqual(L["animator"]["ease"], "backOut")
        self.assertEqual(L["keys"]["scale"][-1][1], 1.1)
        self.assertEqual(L["keys"]["rot"][0][1], -3.0)
        self.assertEqual(s["exit"], {"kind": "fade", "dur": 0.0})

    def test_boxed_caption(self):
        e = _el(role="caption", text={"font": {"family": "Luckiest Guy", "weight": 400}, "size": 0.04, "fill": "#FCFF04",
                                      "box": {"color": "#000000", "opacity": 1, "padX": 0.036, "padY": 0.03, "radius": 0.017}},
                enter={"kind": "cut", "seconds": 0})
        L = sm_apply.text_spec(e, "OH YOU'RE GOOD", 1.0)["layers"][0]
        self.assertEqual(L["panel"]["color"], "#000000")
        self.assertNotIn("animator", L)

    def test_apply_places_elements_on_their_words(self):
        fps = 30
        words = _words("In 480 BC the king marched north with 300 Spartans and Tom Holland watched", 0.5, 0.4)
        doc = {"fps": fps, "width": 1280, "height": 720, "durationInFrames": 8 * fps,
               "scenes": [{"startFrame": 0, "durationInFrames": 4 * fps, "media": {"type": "image"}, "words": words[:7]},
                          {"startFrame": 4 * fps, "durationInFrames": 4 * fps, "media": {"type": "image"}, "words": words[7:]}],
               "overlays": [{"template": "KT_CHIP", "variant": "kt-chip", "startFrame": 10}], "sfx": [], "captions": {}}
        kit = {"name": "t", "elements": [_el(frequency={"perMin": 30})], "marks": [],
               "transitions": {"shares": {"cut": 1.0}}, "camera": {"pushInShare": 0}, "audio": {"musicUnderVoiceDb": 18}}
        rep = sm_apply.apply(doc, kit)
        self.assertNotIn("error", rep)
        texts = [o["text"] for o in doc["overlays"] if o.get("variant") == "smart-spec"]
        self.assertEqual(texts, ["480 BC", "300 SPARTANS"])
        first = next(o for o in doc["overlays"] if o["text"] == "480 BC")
        self.assertEqual(first["startFrame"], int(round(words[1]["start"] * fps)))
        self.assertFalse(any(o.get("template") == "KT_CHIP" for o in doc["overlays"]))   # the kit replaces word looks

    def test_pace_overrides(self):
        cfg = sm_apply.config_overrides({"pacing": {"shot": {"median": 1.7, "p10": 0.7, "p90": 5.2}, "hookCutsPerMin": 32,
                                                    "bodyCutsPerMin": 22}, "structure": {"hookEnds": 14}})
        self.assertEqual(cfg["TARGET_SCENE_SECONDS"], 2.0)
        self.assertLessEqual(cfg["MIN_SCENE_SECONDS"], cfg["TARGET_SCENE_SECONDS"])
        self.assertEqual(cfg["HOOK_SECONDS"], 14.0)


@unittest.skipUnless(HAVE_CV and shutil.which("ffmpeg"), "needs OpenCV and ffmpeg")
class Measure(unittest.TestCase):
    def test_cut_and_outlined_text_on_a_synthetic_video(self):
        from PIL import Image, ImageDraw, ImageFont
        from src.style_match import measure
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "v.mp4")
            W, H, fps = 640, 360, 30
            p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                  "-r", str(fps), "-i", "-", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
            rng = np.random.default_rng(1)
            bg1 = (rng.random((H, W, 3)) * 60 + 40).astype(np.uint8)
            bg2 = (rng.random((H, W, 3)) * 60 + 150).astype(np.uint8)
            bg2[..., 2] = 40
            try:
                font = ImageFont.truetype(fonts.path("Montserrat", 800, fetch=False) or "DejaVuSans-Bold.ttf", 40)
            except OSError:
                font = ImageFont.load_default()
            for i in range(6 * fps):
                t = i / fps
                im = Image.fromarray(bg1 if t < 3 else bg2)
                if 1.0 <= t < 2.6:
                    ImageDraw.Draw(im).text((180, 270), "480 BC HERE", font=font, fill=(255, 255, 255), stroke_width=3,
                                            stroke_fill=(0, 0, 0))
                p.stdin.write(np.asarray(im).tobytes())
            p.stdin.close()
            p.wait()
            p1 = measure.pass1(path, 6, 6)
            cuts = measure.detect_cuts(p1)["cuts"]
            self.assertTrue(any(abs(c - 3.0) < 0.25 for c in cuts), cuts)
            p2 = measure.pass2(path, 6)
            hit = [t for t in p2["texts"] if t["colour"] == "white" and t["outlined"] >= 0.45]
            self.assertTrue(hit, p2["texts"])
            self.assertAlmostEqual(hit[0]["t0"], 1.0, delta=0.25)
            self.assertAlmostEqual(hit[0]["t1"], 2.6, delta=0.3)
            mo = measure.motion(path, hit[0], fps, "in")
            self.assertEqual(mo.get("kind"), "cut")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
