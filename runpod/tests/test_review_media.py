"""Review fixes: framed clips and the library, the photo floor after the time
box, satellite sectors, local tile ratings, picture downloads, video style
on Replace Clip."""
import base64
import io
import os
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import requests
from PIL import Image

from src import config, imagefix, library, localvision, media, official, storage, upscale


def _photo(path, size=(700, 467), fmt="JPEG", mode="RGB", alpha=None):
    im = Image.new("RGB", size, (90, 120, 160))
    for x in range(0, size[0], 16):
        for y in range(0, size[1], 16):
            im.putpixel((x, y), (250, 240, 200))
    im = im.convert(mode)
    if alpha is not None:
        im.putalpha(alpha)
    im.save(path, fmt)
    return path


def _clip(path, size):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30",
                    "-t", "1", "-pix_fmt", "yuv420p", path], check=True)
    return path


class FramedClipsStayOutOfTheLibrary(unittest.TestCase):
    def test_a_framed_vertical_clip_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(config, "ALLOW_VERTICAL", True), \
                mock.patch.object(config, "UPSCALE_ENABLED", False):
            vert = _clip(os.path.join(d, "yt_vert.mp4"), "720x1280")
            flat = _clip(os.path.join(d, "yt_flat.mp4"), "1920x1080")
            assets = [media.MediaAsset(kind="video", source="youtube", url="u1", local_path=vert),
                      media.MediaAsset(kind="video", source="youtube", url="u2", local_path=flat)]
            out = upscale.upscale_assets(assets)
            self.assertEqual(out["framed"], 1)
            self.assertTrue(upscale.is_framed(vert))
            self.assertFalse(upscale.is_framed(flat))

            def scene(ident, url):
                return {"durationInFrames": 150,
                        "media": {"type": "video", "source": "youtube", "url": url},
                        "semanticMetadata": {"assetId": ident, "relevanceScore": 0.95, "subject": "Lake Mead"}}
            doc = {"fps": 30, "scenes": [scene("yt:VERT", vert), scene("yt:FLAT", flat)]}
            lib = library.Library("p1", "j1")
            with mock.patch.object(library.Library, "enabled", new_callable=mock.PropertyMock,
                                   return_value=True), \
                    mock.patch.object(storage, "broker_upload", return_value="obj") as up:
                added = lib.record_from_doc(doc)
        self.assertEqual(added, 1)
        self.assertEqual([e["id"] for e in lib.entries], ["yt:FLAT"])
        self.assertEqual(up.call_count, 1)

    def test_each_job_starts_with_no_framed_clips(self):
        with upscale._LOCK:
            upscale.FRAMED.add(os.path.abspath("old_job/clip.mp4"))
        upscale.upscale_assets([])
        self.assertFalse(upscale.is_framed("old_job/clip.mp4"))


class SmallPhotosAreAlwaysUpscaled(unittest.TestCase):
    def test_photos_under_the_floor_are_upscaled_after_the_time_box(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(upscale, "available", return_value=False), \
                mock.patch.object(config, "UPSCALE_ENABLED", True), \
                mock.patch.object(config, "MIN_IMAGE_LONG_SIDE", 900):
            mid = _photo(os.path.join(d, "mid.jpg"), size=(1200, 800))    # above the floor
            small = _photo(os.path.join(d, "small.jpg"), size=(700, 467))  # only allowed with the upscaler
            assets = [media.MediaAsset(kind="image", source="web", url="a", local_path=mid),
                      media.MediaAsset(kind="image", source="web", url="b", local_path=small)]
            out = upscale.upscale_assets(assets, deadline_seconds=-1)      # the box is already spent
            self.assertEqual(out["image"], 1)
            self.assertEqual(out["skipped_time"], 1)
            with Image.open(small) as im:
                self.assertEqual(max(im.size), config.UPSCALE_TARGET)
            with Image.open(mid) as im:
                self.assertEqual(max(im.size), 1200)

    def test_must_upscale_photos_go_first(self):
        order = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(config, "UPSCALE_ENABLED", True), \
                mock.patch.object(config, "UPSCALE_PARALLEL", 1), \
                mock.patch.object(config, "MIN_IMAGE_LONG_SIDE", 900), \
                mock.patch.object(upscale, "upscale_image", side_effect=lambda p: order.append(p) or True):
            mid = _photo(os.path.join(d, "mid.jpg"), size=(1200, 800))
            small = _photo(os.path.join(d, "small.jpg"), size=(700, 467))
            upscale.upscale_assets([media.MediaAsset(kind="image", source="web", url="a", local_path=mid),
                                    media.MediaAsset(kind="image", source="web", url="b", local_path=small)])
        self.assertEqual(order, [small, mid])

    def test_an_opaque_rgba_png_is_converted_and_upscaled(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(upscale, "available", return_value=False):
            p = _photo(os.path.join(d, "a.jpg"), fmt="PNG", mode="RGBA")
            self.assertTrue(upscale.upscale_image(p))
            with Image.open(p) as im:
                self.assertEqual(im.format, "JPEG")
                self.assertEqual(im.mode, "RGB")
                self.assertEqual(max(im.size), config.UPSCALE_TARGET)

    def test_a_palette_photo_is_converted_and_upscaled(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(upscale, "available", return_value=False):
            p = _photo(os.path.join(d, "p.jpg"), fmt="PNG", mode="P")
            self.assertTrue(upscale.upscale_image(p))
            with Image.open(p) as im:
                self.assertEqual(max(im.size), config.UPSCALE_TARGET)

    def test_real_transparency_is_kept(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(upscale, "available", return_value=False):
            mask = Image.new("L", (700, 467), 255)
            mask.paste(0, (0, 0, 200, 200))
            p = _photo(os.path.join(d, "t.jpg"), fmt="PNG", mode="RGB", alpha=mask)
            self.assertTrue(upscale.upscale_image(p))
            with Image.open(p) as im:
                self.assertEqual(im.format, "PNG")
                self.assertEqual(im.mode, "RGBA")
                self.assertEqual(max(im.size), config.UPSCALE_TARGET)
                self.assertEqual(im.getpixel((5, 5))[3], 0)
                self.assertEqual(im.getpixel((im.width - 5, im.height - 5))[3], 255)


class SatelliteSectors(unittest.TestCase):
    def test_washington_dc_is_the_northeast(self):
        for place in ("Washington, D.C.", "Washington D.C.", "Washington DC", "Washington, DC",
                      "District of Columbia", "D.C."):
            self.assertEqual(official.sector_for([place]), ("GOES19", "ne"), place)
        self.assertEqual(official.sector_for(["Seattle, Washington"]), ("GOES18", "pnw"))

    def test_los_angeles_is_not_louisiana(self):
        for place in ("LA", "L.A.", "Los Angeles", "downtown Los Angeles"):
            self.assertEqual(official.sector_for([place]), ("GOES18", "psw"), place)
        self.assertEqual(official.sector_for(["Lake Charles, LA"]), ("GOES19", "smv"))

    def test_postal_codes_only_after_a_comma(self):
        self.assertEqual(official.sector_for(["Denver, CO"]), ("GOES19", "sr"))
        self.assertEqual(official.sector_for(["Portland,OR"]), ("GOES18", "pnw"))
        self.assertIsNone(official.sector_for(["ME AND MY TOWN"]))
        self.assertIsNone(official.sector_for(["storm hits IN the morning OR later"]))


class LocalTileRatings(unittest.TestCase):
    COLORS = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30), (30, 200, 200)]

    def _rate(self, sheet, count):
        buf = io.BytesIO()
        sheet.save(buf, "PNG")
        crops = []

        def fake_images(tiles):
            crops.extend(tiles)
            return localvision.np.ones((len(tiles), 4)) / 2.0

        with mock.patch.object(localvision, "available", return_value=True), \
                mock.patch.object(localvision, "embed_images", side_effect=fake_images), \
                mock.patch.object(localvision, "embed_texts",
                                  side_effect=lambda t: localvision.np.ones((len(t), 4)) / 2.0):
            out = localvision.rate_sheet(base64.b64encode(buf.getvalue()).decode(), count, "blue water")
        self.assertEqual([r["tile"] for r in out], list(range(1, count + 1)))
        return crops

    @staticmethod
    def _mean(im):
        from PIL import ImageStat
        return tuple(round(v) for v in ImageStat.Stat(im.convert("RGB")).mean)

    def _sheet(self, cells, rows):
        from src.moments import _TILE_H, _TILE_W
        sheet = Image.new("RGB", (5 * _TILE_W, rows * _TILE_H), "black")
        for n, color in enumerate(cells):
            r, c = divmod(n, 5)
            sheet.paste(Image.new("RGB", (_TILE_W, _TILE_H), color), (c * _TILE_W, r * _TILE_H))
        return sheet

    def test_a_short_sheet_keeps_the_five_column_grid(self):
        cells = self.COLORS[:3]
        crops = self._rate(self._sheet(cells, 1), 3)
        for crop, color in zip(crops, cells):
            self.assertEqual(crop.size, (240 - 30, 135 - 22))
            for got, want in zip(self._mean(crop), color):
                self.assertAlmostEqual(got, want, delta=4)

    def test_a_sheet_with_lost_fragments_keeps_the_tile_height(self):
        # 20 tiles chosen (4 rows drawn), 15 made it: rows 3 and 4 are partly black.
        cells = [self.COLORS[(n + n // 5) % 5] for n in range(15)]
        crops = self._rate(self._sheet(cells, 4), 15)
        for crop, color in zip(crops, cells):
            self.assertEqual(crop.size, (240 - 30, 135 - 22))
            for got, want in zip(self._mean(crop), color):
                self.assertAlmostEqual(got, want, delta=4)


def _webp(dest):
    tmp = f"{dest}.{threading.get_ident()}.src"
    _photo(tmp, size=(400, 300), fmt="WEBP")
    os.replace(tmp, dest)
    return dest


class PictureDownloads(unittest.TestCase):
    def test_normalize_uses_a_unique_temp_and_cleans_up(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(src)
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.jpg")
            for _ in range(2):
                _webp(p)
                with mock.patch.object(imagefix.os, "replace", side_effect=spy):
                    imagefix.normalize(p)
            self.assertEqual(len(seen), 2)
            self.assertNotEqual(seen[0], seen[1])
            self.assertNotIn(p + ".norm.part", seen)
            _webp(p)
            with mock.patch.object(imagefix.os, "replace", side_effect=OSError("disk")):
                with self.assertRaises(storage.StorageError):
                    imagefix.normalize(p)
            self.assertEqual([f for f in os.listdir(d) if f.endswith(".part")], [])

    def test_two_scenes_fetching_one_picture_download_it_once(self):
        calls = []

        def slow_download(url, dest, timeout=180, headers=None, proxy="", attempts=3):
            calls.append(dest)
            time.sleep(0.3)
            return _webp(dest)

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(imagefix, "download", side_effect=slow_download):
            dest = os.path.join(d, "web_LakeMead_123.jpg")
            got, errors = [], []

            def run():
                try:
                    got.append(imagefix.fetch("https://news.example.com/a.webp", dest))
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
            threads = [threading.Thread(target=run) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(got, [dest, dest])
            self.assertEqual(len(calls), 1)
            self.assertEqual(imagefix.sniff(dest), "jpeg")

    def test_a_host_that_never_answers_gets_one_browser_try_and_one_residential_route(self):
        calls = []

        def timeout_download(url, dest, timeout=180, headers=None, proxy="", attempts=3):
            calls.append(headers)
            try:
                raise requests.ConnectTimeout("connect timed out")
            except requests.ConnectTimeout as e:
                raise storage.StorageError(f"download failed after 3 attempt(s): {e}") from e

        # 2026-10-02: a host that never answers gets the browser try and one residential route too
        # (each a single 20 s attempt now, not 3 x 60 s) - a slow home route sometimes answers.
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(imagefix, "download", side_effect=timeout_download), \
                mock.patch.object(imagefix, "_residential_route", return_value="http://proxy.example:1"), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=RuntimeError("refused")):
            with self.assertRaises(storage.StorageError):
                imagefix.fetch("https://dead.example.com/a.jpg", os.path.join(d, "p.jpg"))
        self.assertEqual(len(calls), 3)
        self.assertIsNone(calls[0])
        self.assertIn("Mozilla", calls[2]["User-Agent"])

    def test_a_tls_block_still_reaches_curl_cffi(self):
        def ssl_download(url, dest, timeout=180, headers=None, proxy="", attempts=3):
            try:
                raise requests.exceptions.SSLError("handshake")
            except requests.exceptions.SSLError as e:
                raise storage.StorageError(f"download failed after 1 attempt(s): {e}") from e

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(imagefix, "download", side_effect=ssl_download), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=lambda u, dest, p="": _webp(dest)) as cffi:
            out = imagefix.fetch("https://cdn.example.com/a.jpg", os.path.join(d, "p.jpg"))
            self.assertEqual(imagefix.sniff(out), "jpeg")
        cffi.assert_called_once()


class StyleOnReplaceClip(unittest.TestCase):
    def test_resource_uses_the_style_saved_in_the_timeline(self):
        import handler
        seen = {}

        def fake_resource(inp, work, report):
            seen["vertical"] = config.ALLOW_VERTICAL
            seen["style"] = inp.get("video_style")
            return inp["timeline"], []

        doc = {"meta": {"videoStyle": "news_compilation"}, "scenes": []}
        before = config.ALLOW_VERTICAL
        with mock.patch.object(config, "ALLOW_VERTICAL", False), \
                mock.patch.object(handler, "_require_ai_credit"), \
                mock.patch.object(handler, "do_resource", side_effect=fake_resource):
            out = handler.handler({"id": "job-r", "input": {"action": "resource", "timeline": doc,
                                                            "scene_index": 0, "allow_youtube": False}})
            self.assertFalse(config.ALLOW_VERTICAL)                         # restored after the job
        self.assertTrue(out["ok"], out)
        self.assertTrue(seen["vertical"])
        self.assertEqual(seen["style"], "news_compilation")
        self.assertEqual(config.ALLOW_VERTICAL, before)

    def test_an_unstyled_timeline_changes_nothing(self):
        import handler
        seen = {}

        def fake_resource(inp, work, report):
            seen["vertical"] = config.ALLOW_VERTICAL
            return inp["timeline"], []

        with mock.patch.object(config, "ALLOW_VERTICAL", False), \
                mock.patch.object(handler, "_require_ai_credit"), \
                mock.patch.object(handler, "do_resource", side_effect=fake_resource):
            out = handler.handler({"id": "job-r2", "input": {"action": "resource", "allow_youtube": False,
                                                             "timeline": {"meta": {}, "scenes": []}}})
        self.assertTrue(out["ok"], out)
        self.assertFalse(seen["vertical"])

    def test_a_vertical_replacement_and_its_choices_are_framed(self):
        import handler
        with tempfile.TemporaryDirectory() as d:
            win = os.path.join(d, "yt_WIN.mp4")
            alt = os.path.join(d, "yt_ALT.mp4")
            for p in (win, alt):
                with open(p, "wb") as fh:
                    fh.write(b"x" * 10)
            asset = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=WIN",
                                     local_path=win, duration=6.0, relevance_score=0.9, quality=0.8)
            asset.alternatives.append({"assetId": "yt:ALT", "url": "https://www.youtube.com/watch?v=ALT",
                                       "source": "youtube", "localPath": alt, "moment": {}})
            doc = {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 180, "audio": {"url": "a"},
                   "meta": {"story": {}},
                   "scenes": [{"id": "s0000", "startFrame": 0, "durationInFrames": 180, "text": "Flooding in Avalon.",
                               "media": {"type": "color"}, "semanticMetadata": {}}]}
            with mock.patch.object(config, "ALLOW_VERTICAL", True), \
                    mock.patch.object(media, "source_for_segment", return_value=asset), \
                    mock.patch.object(media, "reset_cache"), \
                    mock.patch.object(handler.vision, "set_story"), \
                    mock.patch.object(handler.upscale, "upscale_assets") as ua, \
                    mock.patch.object(handler.upscale, "frame_vertical", return_value=True) as fv:
                handler.do_resource({"timeline": doc, "scene_index": 0, "count": 2, "publish_media": False},
                                    d, lambda *a, **k: None)
        ua.assert_called_once_with([asset])
        fv.assert_called_once_with(alt)


if __name__ == "__main__":
    unittest.main()
