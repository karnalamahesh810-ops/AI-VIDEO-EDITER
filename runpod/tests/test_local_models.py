"""Local vision (CLIP), the upscaler and picture normalization."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image

from src import config, filters, imagefix, localvision, media, storage, upscale


def _photo(path, size=(640, 360), fmt="JPEG", mode="RGB"):
    im = Image.new("RGB", size, (90, 120, 160))
    for x in range(0, size[0], 16):             # some detail so encoders keep it
        for y in range(0, size[1], 16):
            im.putpixel((x, y), (250, 240, 200))
    im.convert(mode).save(path, fmt)
    return path


class Normalize(unittest.TestCase):
    def test_every_web_format_becomes_a_jpeg(self):
        with tempfile.TemporaryDirectory() as d:
            for fmt in ("WEBP", "GIF", "BMP", "TIFF", "AVIF"):
                p = _photo(os.path.join(d, f"x_{fmt}.jpg"), fmt=fmt)
                imagefix.normalize(p)
                self.assertEqual(imagefix.sniff(p), "jpeg", fmt)
                with Image.open(p) as im:
                    self.assertEqual(im.mode, "RGB")

    def test_cmyk_and_rotated_phone_photos_are_fixed(self):
        with tempfile.TemporaryDirectory() as d:
            p = _photo(os.path.join(d, "cmyk.jpg"), mode="CMYK")
            imagefix.normalize(p)
            with Image.open(p) as im:
                self.assertEqual(im.mode, "RGB")
            q = os.path.join(d, "rot.jpg")
            im = Image.new("RGB", (400, 200), (10, 20, 30))
            exif = im.getexif()
            exif[0x0112] = 6                       # "rotate 90 CW to display"
            im.save(q, "JPEG", exif=exif.tobytes())
            imagefix.normalize(q)
            with Image.open(q) as im:
                self.assertEqual(im.size, (200, 400))

    def test_a_clean_jpeg_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            p = _photo(os.path.join(d, "ok.jpg"))
            before = os.path.getmtime(p), os.path.getsize(p)
            imagefix.normalize(p)
            self.assertEqual((os.path.getmtime(p), os.path.getsize(p)), before)

    def test_svg_and_html_are_not_photos(self):
        with tempfile.TemporaryDirectory() as d:
            for body, kind in ((b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "svg"),
                               (b"<!DOCTYPE html><html></html>", "html")):
                p = os.path.join(d, f"{kind}.jpg")
                with open(p, "wb") as fh:
                    fh.write(body)
                with self.assertRaises(storage.StorageError):
                    imagefix.normalize(p)


class Fetch(unittest.TestCase):
    def test_a_hotlink_block_is_retried_as_a_browser(self):
        calls = []

        def fake_download(url, dest, timeout=180, headers=None):
            calls.append(headers)
            if headers is None:
                raise storage.StorageError("download failed after 1 attempt(s): 403 Forbidden")
            return _photo(dest)

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(imagefix, "download", side_effect=fake_download):
            out = imagefix.fetch("https://news.example.com/a/photo.jpg", os.path.join(d, "p.jpg"))
        self.assertTrue(out.endswith("p.jpg"))
        self.assertIsNone(calls[0])
        self.assertIn("Mozilla", calls[1]["User-Agent"])
        self.assertEqual(calls[1]["Referer"], "https://news.example.com/")

    def test_media_downloads_pictures_through_the_fixer(self):
        asset = media.MediaAsset(kind="image", source="web", url="https://x.example/a.webp")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(media._imagefix, "fetch", return_value=os.path.join(d, "a.jpg")) as f:
            got = media._download(asset, "q", d)
        self.assertIs(got, asset)
        f.assert_called_once()


class Upscale(unittest.TestCase):
    def test_a_mid_size_photo_is_resized_and_sharpened_without_the_model(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(upscale, "available", return_value=False):
            p = _photo(os.path.join(d, "a.jpg"), size=(1200, 800))
            self.assertTrue(upscale.upscale_image(p))
            with Image.open(p) as im:
                self.assertEqual(max(im.size), config.UPSCALE_TARGET)

    def test_a_big_photo_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            p = _photo(os.path.join(d, "a.jpg"), size=(1920, 1080))
            self.assertFalse(upscale.upscale_image(p))

    def test_a_soft_clip_is_brought_to_1080_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=854x480:rate=30",
                            "-t", "1", "-pix_fmt", "yuv420p", p], check=True)
            self.assertTrue(upscale.upscale_clip(p, 240))
            self.assertEqual(upscale._probe_height(p), 1080)
            self.assertFalse(upscale.upscale_clip(p, 240))       # already 1080: untouched

    def test_archive_film_and_generated_images_are_skipped(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(upscale, "upscale_image", return_value=True) as ui, \
                mock.patch.object(upscale, "upscale_clip", return_value=True) as uc:
            a = media.MediaAsset(kind="image", source="generated", url="", local_path=_photo(os.path.join(d, "g.jpg")))
            b = media.MediaAsset(kind="video", source="archive_org", url="", local_path=_photo(os.path.join(d, "v.mp4")))
            c = media.MediaAsset(kind="image", source="web", url="u", local_path=_photo(os.path.join(d, "w.jpg")))
            out = upscale.upscale_assets([a, b, c, None])
        self.assertEqual(out["queued"], 1)
        ui.assert_called_once()
        uc.assert_not_called()

    def test_the_photo_floor_drops_when_the_upscaler_is_installed(self):
        with mock.patch.object(upscale, "available", return_value=True):
            self.assertEqual(filters.min_image_long_side(),
                             min(config.MIN_IMAGE_LONG_SIDE, config.MIN_IMAGE_LONG_SIDE_UPSCALED))
        with mock.patch.object(upscale, "available", return_value=False):
            self.assertEqual(filters.min_image_long_side(), config.MIN_IMAGE_LONG_SIDE)

    @unittest.skipUnless(os.path.isfile(config.UPSCALE_MODEL), "Real-ESRGAN model not installed")
    def test_the_model_upscales_a_small_photo(self):
        with tempfile.TemporaryDirectory() as d:
            p = _photo(os.path.join(d, "s.jpg"), size=(300, 200))
            self.assertTrue(upscale.upscale_image(p))
            with Image.open(p) as im:
                self.assertEqual(max(im.size), config.UPSCALE_TARGET)


class LocalRules(unittest.TestCase):
    def _classes(self, **kw):
        base = {k: 0.0 for k in localvision.CLASSES}
        base.update(kw)
        return base

    def test_hard_rejects(self):
        r = localvision._reject_reason
        self.assertEqual(r(self._classes(slide=0.9, photo=0.1), "place", ""), "a presentation slide")
        self.assertEqual(r(self._classes(render=0.85), "", ""), "a cartoon, game or 3D render")
        self.assertEqual(r(self._classes(person=0.95), "place", ""), "a portrait on a line about a place")
        self.assertEqual(r(self._classes(slide=0.5, text=0.4), "event", ""), "a slide or text screenshot")

    def test_what_the_line_asks_for_is_allowed(self):
        r = localvision._reject_reason
        self.assertEqual(r(self._classes(text=0.95), "document", ""), "")
        self.assertEqual(r(self._classes(slide=0.9), "", "chart"), "")
        self.assertEqual(r(self._classes(person=0.95), "person", ""), "")
        self.assertEqual(r(self._classes(photo=0.9), "place", ""), "")


class Gate(unittest.TestCase):
    def setUp(self):
        self.tok = media._SUBJECT_TYPE.set("place")

    def tearDown(self):
        media._SUBJECT_TYPE.reset(self.tok)

    def test_a_local_reject_never_reaches_gemini(self):
        local = {"reject": "a presentation slide", "relevance": 0.3, "kind": "slide"}
        with mock.patch.object(media, "_local_check", return_value=local), \
                mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media.vision, "judge") as judge:
            keep, verdict = media._vision_gate("x.jpg", "Lake Powell", "", "Lake Powell.jpg")
        self.assertFalse(keep)
        judge.assert_not_called()

    def test_the_local_model_decides_when_gemini_is_busy(self):
        near = {"reject": "", "relevance": 0.26, "kind": "photo"}
        far = {"reject": "", "relevance": 0.15, "kind": "photo"}
        with mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media.vision, "judge", return_value=None), \
                mock.patch.object(config, "ACCEPT_UNJUDGED", False):
            with mock.patch.object(media, "_local_check", return_value=near):
                self.assertTrue(media._vision_gate("x.mp4", "Lake Powell low water", "", "random title")[0])
            with mock.patch.object(media, "_local_check", return_value=far):
                self.assertFalse(media._vision_gate("x.mp4", "Lake Powell low water", "", "Lake Powell low water")[0])

    def test_without_the_model_the_title_still_decides(self):
        with mock.patch.object(media, "_local_check", return_value=None), \
                mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media.vision, "judge", return_value=None), \
                mock.patch.object(config, "ACCEPT_UNJUDGED", False):
            self.assertTrue(media._vision_gate("x.mp4", "Lake Powell low water", "", "Lake Powell water level 2026")[0])

    @unittest.skipUnless(os.path.isdir(config.LOCAL_VISION_DIR), "CLIP model not installed")
    def test_the_model_runs(self):
        with tempfile.TemporaryDirectory() as d:
            p = _photo(os.path.join(d, "a.jpg"))
            r = localvision.check(p, "a blue sky", subject_type="place")
        self.assertIn(r["kind"], localvision.CLASSES)
        self.assertGreater(r["relevance"], 0.0)


class TileFallback(unittest.TestCase):
    def test_busy_models_fall_back_to_local_tile_ratings(self):
        from src import vision
        rated = [{"tile": 1, "score": 0.4, "description": "a"}, {"tile": 2, "score": 0.83, "description": "b"}]
        with mock.patch.object(vision, "enabled", return_value=True),                 mock.patch.object(vision, "_ask", return_value=(None, "")),                 mock.patch.object(localvision, "rate_sheet", return_value=rated):
            self.assertEqual(vision.rate_tiles("x", 2, "Lake Mead"), rated)
            self.assertEqual(vision.pick_tile("x", 2, "Lake Mead")["tile"], 2)
        with mock.patch.object(vision, "enabled", return_value=True),                 mock.patch.object(vision, "_ask", return_value=(None, "")),                 mock.patch.object(localvision, "rate_sheet", return_value=None):
            self.assertIsNone(vision.pick_tile("x", 2, "Lake Mead"))

    @unittest.skipUnless(os.path.isdir(config.LOCAL_VISION_DIR), "CLIP model not installed")
    def test_the_model_rates_a_sheet(self):
        import base64, io
        sheet = Image.new("RGB", (1200, 270), (40, 90, 160))
        buf = io.BytesIO()
        sheet.save(buf, "JPEG")
        out = localvision.rate_sheet(base64.b64encode(buf.getvalue()).decode(), 10, "blue water")
        self.assertEqual([r["tile"] for r in out], list(range(1, 11)))


class VideoStyles(unittest.TestCase):
    def test_news_compilation_becomes_config_overrides(self):
        from src import styles
        inp = {"video_style": "news_compilation", "config": {"MAX_SCENE_SECONDS": 10}}
        self.assertEqual(styles.apply(inp), "news_compilation")
        self.assertTrue(inp["config"]["ALLOW_VERTICAL"])
        self.assertEqual(inp["config"]["MAX_SCENE_SECONDS"], 10)          # the job's own override wins
        self.assertEqual(inp["style"], "crossfade")
        # Music plays in every style since 2026-09-30 (the owner: "use the music").
        self.assertNotIn("bgm", inp)

    def test_auto_and_unknown_styles_change_nothing(self):
        from src import styles
        for v in ("", "auto", "nonsense"):
            inp = {"video_style": v}
            self.assertEqual(styles.apply(inp), "")
            self.assertNotIn("config", inp)

    def test_a_chosen_track_keeps_its_music(self):
        from src import styles
        inp = {"video_style": "news_compilation", "bgm_genre": "suspense"}
        styles.apply(inp)
        self.assertNotIn("bgm", inp)

    def test_every_style_override_is_allowed_per_job(self):
        import handler
        from src import styles
        for spec in styles.STYLES.values():
            for key in list(spec["config"]) + ["GRAPHICS_DENSITY", "TRANSITION_STYLE"]:
                self.assertIn(key, handler.CONFIG_OVERRIDABLE, key)


class Vertical(unittest.TestCase):
    def test_vertical_video_is_framed_on_a_blurred_fill(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "ALLOW_VERTICAL", True):
            p = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30",
                            "-t", "1", "-pix_fmt", "yuv420p", p], check=True)
            self.assertEqual(filters.clip_quality(p, 480)[0], True)
            self.assertTrue(upscale.frame_vertical(p))
            self.assertEqual(upscale._dims(p), (1920, 1080))
            self.assertFalse(upscale.frame_vertical(p))                  # landscape now: untouched

    def test_vertical_video_is_still_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30",
                            "-t", "1", "-pix_fmt", "yuv420p", p], check=True)
            self.assertEqual(filters.clip_quality(p, 480), (False, "vertical or square video"))
        self.assertFalse(media._usable_title("Flooding in Avalon", "", 9 / 16))
        with mock.patch.object(config, "ALLOW_VERTICAL", True):
            self.assertTrue(media._usable_title("Flooding in Avalon", "", 9 / 16))


class OfficialImagery(unittest.TestCase):
    def test_regions_map_to_satellite_sectors(self):
        from src import official
        self.assertEqual(official.sector_for(["Long Beach Island, NJ"]), ("GOES19", "ne"))
        self.assertEqual(official.sector_for(["the Outer Banks"]), ("GOES19", "se"))
        self.assertEqual(official.sector_for(["Los Angeles, California"]), ("GOES18", "psw"))
        self.assertIsNone(official.sector_for(["Paris"]))

    def test_only_todays_weather_gets_a_live_loop(self):
        from src import official
        self.assertTrue(official.is_now({"kind": "weather", "year": 2026}, 2026))
        self.assertFalse(official.is_now({"kind": "disaster", "year": 2005}, 2026))   # Katrina
        self.assertFalse(official.is_now({"kind": "history", "year": 2026}, 2026))
        self.assertTrue(official.is_now({"kind": "news", "recent": True}, 2026))

    def test_the_provider_only_answers_storm_lines(self):
        from src import director, providers
        ctx = providers.SourceContext(query="nor'easter satellite view", seconds=6, work_dir=".",
                                      intent="the storm system from space")
        story = {"kind": "weather", "year": __import__("datetime").date.today().year, "places": ["New Jersey"]}
        with mock.patch.dict(director.LAST_STORY, story, clear=True):
            self.assertTrue(providers._wants_satellite(ctx))
            ctx.query, ctx.intent = "flooded street in Avalon", "a flooded street"
            self.assertFalse(providers._wants_satellite(ctx))


class Yandex(unittest.TestCase):
    def test_results_page_originals_are_parsed_and_stock_is_dropped(self):
        page = ('<a href="/images/search?img_url=https%3A%2F%2Fpix11.com%2Fa.jpg%3Fw%3D1280&amp;pos=1">'
                '<a href="/images/search?img_url=https%3A%2F%2Fc8.alamy.com%2Fx.jpg&amp;pos=2">'
                '{"origUrl":"https:\u002F\u002Fs.w-x.co\u002Fstorm.png?a=1&amp;b=2"}')
        resp = mock.Mock(url="https://yandex.com/images/search?text=x", text=page)
        with mock.patch.object(media.requests, "get", return_value=resp),                 mock.patch.object(media, "_next_proxy", return_value=None):
            got = media.search_yandex_images("Long Beach Island flooding")
        self.assertEqual([a.url for a in got], ["https://pix11.com/a.jpg?w=1280", "https://s.w-x.co/storm.png?a=1&b=2"])
        self.assertTrue(all(a.review_required for a in got))

    def test_a_captcha_goes_through_the_proxy(self):
        captcha = mock.Mock(url="https://yandex.com/showcaptcha?x", text="")
        ok = mock.Mock(url="https://yandex.com/images/search", text='img_url=https%3A%2F%2Fa.com%2Fb.jpg&')
        with mock.patch.object(media.requests, "get", side_effect=[captcha, ok]) as get,                 mock.patch.object(media, "_next_proxy", return_value="http://proxy:1"):
            got = media.search_yandex_images("x")
        self.assertEqual([a.url for a in got], ["https://a.com/b.jpg"])
        self.assertEqual(get.call_args_list[1].kwargs["proxies"]["https"], "http://proxy:1")


if __name__ == "__main__":
    unittest.main()
