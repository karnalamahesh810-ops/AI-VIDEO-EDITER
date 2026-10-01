"""AI slop and not-footage (src/slop.py, src/vision.py; the owner's Texas test, 2026-09-30).

"This is AI slop clip" (0:18: an AI scene from another channel) and an AI
oil-painting street beside a YouTuber with a SUBSCRIBE bell and karaoke
captions (0:37). Each layer rejects on its own; the judge and CLIP are mocked
(the real-CLIP test runs only where the model is installed).
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from src import config, libstore, localvision, media, slop, vision

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = bool(shutil.which("ffmpeg"))


class Metadata(unittest.TestCase):
    def test_ai_generators_and_ai_stories_are_named_out(self):
        for title in ("The Flood That Destroyed Everything | AI Generated Story", "Texas floods #ai #sora",
                      "Made with Midjourney and Kling AI", "Runway Gen-3 storm short film", "Veo 3 hurricane",
                      "AI video: the dam breaks", "BeamNG flood simulation", "GTA 5 tsunami"):
            self.assertTrue(slop.metadata_reason(title), title)
        for title in ("Flooding in Atlantic City this morning", "Runway flooded at Newark airport",
                      "Storm surge floods Long Beach Island | NBC News", "Kerrville flood rescue video",
                      "Aid arrives in Texas flood zone"):
            self.assertFalse(slop.metadata_reason(title), title)

    def test_titles_and_channels_gate_every_search_result(self):
        self.assertFalse(media._usable_title("Hurricane Helene AI generated movie", "Storm Stories"))
        self.assertFalse(media._usable_title("Dallas flood", "Sora 2 Creations #sora"))
        self.assertTrue(media._usable_title("Dallas flooding video", "WFAA"))
        with mock.patch.object(config, "AI_SLOP_FILTER", False):
            self.assertTrue(media._usable_title("Hurricane Helene AI generated movie", "Storm Stories"))

    def test_ai_picture_sites_and_url_paths(self):
        self.assertTrue(slop.ai_host("https://lexica.art/prompt/abc"))
        self.assertEqual(slop.metadata_reason("https://example.com/cgi-bin/img.jpg"), "")


def frames_shift(n=6, step=2, zoom=0.0):
    """A textured still, shifted (and zoomed) a little every frame: a photo with a Ken Burns move."""
    rng = np.random.default_rng(1)
    base = (rng.random((96, 160)) * 255).astype(np.float32)
    base = (base + np.roll(base, 1, 0) + np.roll(base, 1, 1)) / 3.0            # a smooth-ish picture
    out = []
    for k in range(n):
        img = slop._zoom(base, 1.0 + zoom * k) if zoom else base
        out.append(np.roll(img, k * step, axis=1)[10:82, 16:144].copy())
    return out


class Stills(unittest.TestCase):
    def test_a_held_photo_is_frozen(self):
        f = frames_shift(5, step=0)
        m = slop.still_measure(f)
        self.assertTrue(m["still"])
        self.assertLess(m["raw"], slop.FROZEN_RAW)

    def test_a_photo_with_a_slow_pan_or_zoom_is_still(self):
        self.assertTrue(slop.still_measure(frames_shift(5, step=2))["still"])
        self.assertTrue(slop.still_measure(frames_shift(5, step=1, zoom=0.01))["still"])

    def test_something_moving_inside_the_picture_is_footage(self):
        rng = np.random.default_rng(2)
        frames = frames_shift(5, step=1)
        for k, f in enumerate(frames):
            y = 10 + 8 * k
            f[y:y + 20, 30:90] = rng.random((20, 60)) * 255            # a car driving through the water
        self.assertFalse(slop.still_measure(frames)["still"])

    def test_fast_real_motion_is_never_a_slideshow(self):
        rng = np.random.default_rng(3)
        frames = [(rng.random((72, 128)) * 255).astype(np.float32) for _ in range(5)]
        m = slop.still_measure(frames)
        self.assertFalse(m["still"])

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_real_files(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        still = os.path.join(d, "still.png")
        zoom = os.path.join(d, "zoom.mp4")
        moving = os.path.join(d, "moving.mp4")
        # One picture with a slow Ken Burns zoom, the way AI-story slideshows move.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=s=640x360", "-frames:v", "1",
                        still], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", still, "-t", "4", "-vf",
                        "scale=2560:1440,zoompan=z='1+0.0008*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=120"
                        ":s=640x360:fps=30", "-pix_fmt", "yuv420p", zoom], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=s=640x360:rate=15", "-t", "4",
                        "-vf", "hue=H=2*PI*t:s=1", "-pix_fmt", "yuv420p", moving], check=True, capture_output=True)
        self.assertEqual(slop.still_verdict(zoom), "a still with a slow pan or zoom")
        self.assertEqual(slop.still_verdict(moving), "")


def caption_frames(changing=True, centre=0.8, tall=12, left=None):
    """Grey frames of a moving picture with a white text band (stroke pattern) at `centre` of the height."""
    rng = np.random.default_rng(4)
    out = []
    for k in range(6):
        g = (rng.random((180, 320)) * 40 + 60).astype(np.float32)
        y = int(centre * 180)
        width = 140 + (40 if (changing and k % 2) else 0)
        x0 = left if left is not None else (160 - width // 2)
        band = np.zeros((tall, width), dtype=np.float32)
        band[:, ::3] = 255                                      # letter strokes
        g[y:y + tall, x0:x0 + width] = band
        out.append(g)
    return out


class Captions(unittest.TestCase):
    def test_karaoke_captions_that_change_are_found(self):
        c = slop.caption_bands(caption_frames(changing=True))
        self.assertGreaterEqual(c["frames"], 3)
        self.assertGreaterEqual(c["changing"], 1)

    def test_a_fixed_chyron_hugging_the_left_is_not(self):
        c = slop.caption_bands(caption_frames(changing=False, centre=0.86, tall=9, left=12))
        self.assertEqual((c["frames"], c["changing"]), (0, 0))

    def test_a_big_title_caption_mid_frame_is(self):
        c = slop.caption_bands(caption_frames(changing=False, centre=0.5, tall=14))
        self.assertGreaterEqual(c["big"], 3)


class Clip(unittest.TestCase):
    """The local CLIP layer with the model's embeddings mocked: shares decide."""

    def verdict(self, art, layout, **kw):
        def two_class(emb, pos, neg):
            return np.full(len(emb), art)

        def layout_shares(emb):
            return {k: np.full(len(emb), layout.get(k, 0.0)) for k in slop.LAYOUT}
        with mock.patch.object(localvision, "available", return_value=True), \
                mock.patch.object(localvision, "embed_images", side_effect=lambda ims: np.ones((len(ims), 4))), \
                mock.patch.object(slop, "_softmax_share", side_effect=two_class), \
                mock.patch.object(slop, "_layout_shares", side_effect=layout_shares):
            from PIL import Image
            ims = [Image.new("RGB", (64, 36)) for _ in range(3)]
            return slop.clip_verdict(ims, **kw)

    def test_painted_or_generated(self):
        self.assertEqual(self.verdict(0.8, {"footage": 0.9})["reject"], "an AI-generated or painted picture")
        self.assertEqual(self.verdict(0.2, {"footage": 0.9})["reject"], "")

    def test_studio_presenter_and_tv_maps(self):
        self.assertEqual(self.verdict(0.1, {"studio": 0.8, "footage": 0.02})["reject"],
                         "a TV studio, presenter or talking head")
        self.assertEqual(self.verdict(0.1, {"tvmap": 0.85, "studio": 0.1, "footage": 0.0})["reject"],
                         "a TV weather map or live-stream screen")
        # A line about a named person: their press conference is the shot.
        self.assertEqual(self.verdict(0.1, {"studio": 0.8, "footage": 0.02}, allow_people=True)["reject"], "")
        self.assertEqual(self.verdict(0.1, {"tvmap": 0.9, "footage": 0.0}, allow_maps=True)["reject"], "")
        # Real footage with a little map-like texture is kept.
        self.assertEqual(self.verdict(0.1, {"tvmap": 0.5, "footage": 0.3})["reject"], "")

    def test_no_model_no_finding(self):
        with mock.patch.object(localvision, "available", return_value=False):
            self.assertIsNone(slop.clip_verdict([object()]))

    @unittest.skipUnless(os.path.isdir(config.LOCAL_VISION_DIR), "the CLIP model is not installed here")
    def test_the_owners_two_examples_with_the_real_model(self):
        from PIL import Image
        if not localvision.available():
            self.skipTest("CLIP runtime not available")
        for name in ("ai_courthouse_0018.jpg", "creator_painting_0037.jpg"):
            im = Image.open(os.path.join(HERE, "fixtures", "slop", name)).convert("RGB")
            self.assertEqual(slop.clip_verdict([im, im, im])["reject"], "an AI-generated or painted picture", name)


class Judge(unittest.TestCase):
    def test_the_prompt_asks_both_questions(self):
        system = vision._system()
        self.assertIn("ai_generated", system)
        self.assertIn("studio", system)
        self.assertIn("RUIDOSO, NM", vision._EVENT_RULE)

    def test_the_answers_are_hard_rejects(self):
        base = ('{"description": "x", "score": 0.95, "quality": 0.9, "has_text_or_watermark": false, '
                '"is_talking_head": false, "specificity": "event", ')
        ai = vision._parse(base + '"ai_generated": true, "studio": false}')
        studio = vision._parse(base + '"ai_generated": "false", "studio": "true"}')
        fine = vision._parse(base + '"ai_generated": false, "studio": false}')
        self.assertTrue(ai["ai_generated"])
        self.assertFalse(studio["ai_generated"])
        self.assertFalse(vision.acceptable(ai))
        self.assertFalse(vision.acceptable(ai, allow_people=True))      # AI slop never passes
        self.assertFalse(vision.acceptable(studio))
        self.assertTrue(vision.acceptable(studio, allow_people=True))   # the person's own appearance
        self.assertTrue(vision.acceptable(fine))


class TheGate(unittest.TestCase):
    def test_a_slop_finding_rejects_before_any_model_call(self):
        with mock.patch.object(slop, "check_file", return_value="an AI-generated or painted picture"), \
                mock.patch.object(vision, "judge", side_effect=AssertionError("no judge for slop")):
            keep, verdict = media._vision_gate(__file__, "flooded street in Dallas", "", "Texas flood")
        self.assertFalse(keep)
        self.assertIsNone(verdict)
        self.assertEqual(media.SLOP_REJECTED.get("an AI-generated or painted picture"), 1)
        media.SLOP_REJECTED.clear()

    def test_a_named_ai_story_is_rejected_on_its_label(self):
        with mock.patch.object(slop, "check_file", return_value=""), \
                mock.patch.object(vision, "judge", side_effect=AssertionError("no judge")):
            keep, _v = media._vision_gate(__file__, "", "", "Texas Flood | AI Generated Short Film")
        self.assertFalse(keep)
        media.SLOP_REJECTED.clear()

    def test_the_library_gate_turns_ai_down_too(self):
        with mock.patch.object(libstore, "tools", return_value=True), \
                mock.patch.object(libstore, "probe", return_value={"width": 1920, "height": 1080, "seconds": 6.0,
                                                                   "codec": "h264", "ok": True}), \
                mock.patch.object(libstore, "frames", return_value=[
                    np.full((224, 400, 3), 100 + 20 * k, dtype=np.uint8) for k in range(8)]), \
                mock.patch.object(libstore, "clip_facts", return_value=None), \
                mock.patch.object(slop, "still_measure", return_value={"still": False}), \
                mock.patch.object(slop, "clip_verdict", return_value={"art": 0.8, "studio": 0.0, "creator": 0.0,
                                                                      "tvmap": 0.0, "footage": 0.9,
                                                                      "reject": "an AI-generated or painted picture"}):
            v = libstore.check("x.mp4", kind="video", clip=True)
        self.assertIn("an AI-generated or painted picture", v.reasons)


# What OpenAI's image models write (seen in all 19 gpt-image pictures, 2026-10-01).
_XMP_AI = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
           b'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/'
           b'trainedAlgorithmicMedia"/></rdf:RDF></x:xmpmeta>')


class Provenance(unittest.TestCase):
    """Layer 0: the picture's own content credentials (2026-10-01, the Lake Powell review)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def png(self, name, **text):
        from PIL import Image, PngImagePlugin
        info = PngImagePlugin.PngInfo()
        for k, v in text.items():
            info.add_text(k, v)
        p = os.path.join(self.d, name)
        Image.new("RGB", (64, 36), (120, 90, 60)).save(p, "PNG", pnginfo=info)
        return p

    def test_content_credentials_mark_a_generated_picture(self):
        p = self.png("gen.png", **{"XML:com.adobe.xmp": _XMP_AI.decode()})
        with mock.patch.object(localvision, "available", return_value=False):
            self.assertTrue(slop.check_file(p, "image").startswith("an AI-generated picture (content credentials"))

    def test_stable_diffusion_parameters_and_comfyui_workflows(self):
        sd = self.png("sd.png", parameters="a dam at dusk\nNegative prompt: blurry\nSteps: 30, Sampler: Euler a")
        comfy = self.png("comfy.png", prompt='{"3": {"class_type": "KSampler", "inputs": {}}}')
        self.assertTrue(slop.provenance_reason(sd))
        self.assertTrue(slop.provenance_reason(comfy))

    def test_a_camera_photo_is_not_marked(self):
        from PIL import Image
        p = os.path.join(self.d, "camera.jpg")
        exif = Image.Exif()
        exif[0x010F] = "Canon"                               # Make
        exif[0x0110] = "Canon EOS 5D Mark III"               # Model
        exif[0x0131] = "Adobe Photoshop CS6 (Macintosh)"     # Software
        Image.new("RGB", (64, 36), (30, 60, 90)).save(p, "JPEG", exif=exif)
        self.assertEqual(slop.provenance_reason(p), "")
        self.assertEqual(slop.provenance_reason(os.path.join(self.d, "missing.jpg")), "")

    def test_the_mark_survives_imagefix_rewriting_the_picture(self):
        # A WebP is rewritten as a clean JPEG, and its credentials go with the old bytes.
        from PIL import Image
        from src import imagefix
        def data(path):
            with open(path, "rb") as fh:
                return fh.read()
        p = os.path.join(self.d, "gen.webp")
        Image.new("RGB", (64, 36), (120, 90, 60)).save(p, "WEBP", xmp=_XMP_AI)
        if b"trainedAlgorithmicMedia" not in data(p):
            self.skipTest("this Pillow does not write XMP into WebP")
        out = imagefix.fetch(p, os.path.join(self.d, "unused.jpg"))
        self.assertNotIn(b"trainedAlgorithmicMedia", data(out))
        self.assertTrue(slop.provenance_reason(out))

    def test_a_photo_desk_never_waives_content_credentials(self):
        p = self.png("gen.png", **{"XML:com.adobe.xmp": _XMP_AI.decode()})
        with mock.patch.object(slop, "enabled", return_value=True), \
                mock.patch.object(localvision, "available", return_value=False):
            self.assertTrue(media.slop_reason(p, "Lake Powell shrinks | AP News",
                                              source_url="https://apnews.com/x.png"))
        media.SLOP_REJECTED.clear()


class PaintedOrPhoto(unittest.TestCase):
    """Layer 3's floors after the Lake Powell measurement (2026-10-01): CLIP read
    34% of the real web photos and 4% of the real clips the owner approved as
    painted; the landscape / press / drone photo labels fix that."""

    def verdict(self, art, kind):
        with mock.patch.object(localvision, "available", return_value=True), \
                mock.patch.object(localvision, "embed_images", side_effect=lambda ims: np.ones((len(ims), 4))), \
                mock.patch.object(slop, "_softmax_share", side_effect=lambda emb, pos, neg: np.full(len(emb), art)), \
                mock.patch.object(slop, "_layout_shares",
                                  side_effect=lambda emb: {k: np.full(len(emb), 0.9 if k == "footage" else 0.0)
                                                           for k in slop.LAYOUT}):
            from PIL import Image
            return slop.clip_verdict([Image.new("RGB", (64, 36)) for _ in range(3)], kind=kind)

    def test_a_photo_needs_a_clearer_painted_look_than_a_clip(self):
        self.assertEqual(self.verdict(0.52, "image")["reject"], "")
        self.assertEqual(self.verdict(0.52, "video")["reject"], "an AI-generated or painted picture")
        self.assertEqual(self.verdict(0.6, "image")["reject"], "an AI-generated or painted picture")

    def test_documentary_photographs_are_photo_labels(self):
        for label in ("a landscape photograph", "an aerial photograph of a landscape", "a press photograph",
                      "a drone photograph"):
            self.assertIn(label, slop.PHOTO)
        self.assertNotIn("a landscape photograph", slop.ART)

    def test_check_file_judges_a_photo_as_a_photo(self):
        seen = {}

        def verdict(images, allow_people=False, allow_maps=False, kind="video"):
            seen["kind"] = kind
            return {"reject": ""}
        with mock.patch.object(slop, "enabled", return_value=True), \
                mock.patch.object(slop, "_rgb_frames", return_value=[object()]), \
                mock.patch.object(slop, "clip_verdict", side_effect=verdict):
            slop.check_file(os.path.join(HERE, "fixtures", "slop", "ai_courthouse_0018.jpg"), "image")
        self.assertEqual(seen["kind"], "image")

    def test_a_photo_desk_host_waives_the_colour_reading(self):
        with mock.patch.object(slop, "enabled", return_value=True), \
                mock.patch.object(slop, "metadata_reason", return_value=""), \
                mock.patch.object(slop, "check_file", return_value="an AI-generated or painted picture"):
            for url in ("https://assets.science.nasa.gov/content/lakepowell_oli_20260910_lrg.jpg",
                        "https://npr.brightspotcdn.com/dims4/x.jpg", "https://upload.wikimedia.org/a/b/x.jpg",
                        "https://www.usbr.gov/uc/water/x.jpg"):
                self.assertEqual(media.slop_reason("x.jpg", "Lake Powell from above", source_url=url), "", url)
            self.assertTrue(media.slop_reason("x.jpg", "Lake Powell from above",
                                              source_url="https://wallpapercave.com/x.jpg"))
            self.assertTrue(media.slop_reason("x.mp4", "Lake Powell | NASA"))       # footage keeps the check
        media.SLOP_REJECTED.clear()

    @unittest.skipUnless(os.path.isdir(config.LOCAL_VISION_DIR), "the CLIP model is not installed here")
    def test_the_owners_examples_as_photos_with_the_real_model(self):
        from PIL import Image
        if not localvision.available():
            self.skipTest("CLIP runtime not available")
        for name in ("ai_courthouse_0018.jpg", "creator_painting_0037.jpg"):
            im = Image.open(os.path.join(HERE, "fixtures", "slop", name)).convert("RGB")
            self.assertEqual(slop.clip_verdict([im], kind="image")["reject"], "an AI-generated or painted picture",
                             name)


if __name__ == "__main__":
    unittest.main()
