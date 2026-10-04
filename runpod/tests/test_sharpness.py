"""
Real detail, not file size (src/sharpness.py; the owner, 2026-10-04: "fix
blur image issues", "images needed HD to 4K level and video clips also").

The Lake Powell video showed 40 of its 141 pictures blown up past 1.6x though
most were stored 1920 px wide. These tests build the same thing on purpose -
a picture with detail at every scale, and the same picture shrunk and blown
back up to the same file size - and check that the measure tells them apart,
that sourcing never spends a vision call on the soft one or offers it again,
that searches ask for big pictures first, that the quality gate replaces a
soft shot from the ladder or keeps it (never an empty scene, a text card or
an inset), that the library and the packs keep only sharp files, and that
with the checks off nothing changes.

The suite runs with both checks off (tests/__init__.py: its synthetic media
are thumbnails); each test here switches them on itself.
"""
import os
import shutil
import subprocess
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
from src import config, gapfill, libstore, media, packs, quality, sharpness  # noqa: E402
from src.media import MediaAsset  # noqa: E402

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
ON = dict(PICTURE_SHARPNESS_CHECK=True, CLIP_SHARPNESS_CHECK=True, MAX_PICTURE_MAGNIFICATION=1.45,
          MIN_CLIP_REAL_HEIGHT=720, STILL_MOTION="")
OFF = dict(PICTURE_SHARPNESS_CHECK=False, CLIP_SHARPNESS_CHECK=False)
TMP = ""


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="sharp_")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def _texture(w: int, h: int, seed: int = 1) -> np.ndarray:
    """Grey detail at every scale, like a photo of rock or foliage (1/f-ish), 0..255."""
    rng = np.random.RandomState(seed)
    acc = np.zeros((h, w), np.float32)
    for k in range(8):
        cell = 2 ** k
        small = rng.rand(h // cell + 2, w // cell + 2).astype(np.float32)
        layer = np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize(
            ((w // cell + 2) * cell, (h // cell + 2) * cell), Image.BICUBIC), np.float32)[:h, :w]
        acc += layer * (0.35 + 0.1 * k)
    lo, hi = np.percentile(acc, 1), np.percentile(acc, 99)
    return np.clip((acc - lo) / max(1e-6, hi - lo), 0.0, 1.0) * 255.0


def picture(name: str, w: int = 1920, h: int = 1080, real: float = 1.0, contrast: float = 1.0,
            seed: int = 1) -> str:
    """A w x h JPEG holding `real` of its size in detail (shrunk to real x size, blown back up)."""
    path = os.path.join(TMP, name)
    if os.path.isfile(path):
        return path
    g = _texture(w, h, seed) * contrast + (1.0 - contrast) * 110.0
    im = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert("RGB")
    if real < 1.0:
        im = im.resize((max(8, int(w * real)), max(8, int(h * real))), Image.LANCZOS).resize((w, h), Image.LANCZOS)
    im.save(path, "JPEG", quality=90)
    return path


def clip(name: str, lines: int, out_lines: int = 1080, seconds: float = 2.0) -> str:
    """A 16:9 clip drawn at `lines` lines (ffmpeg's test pattern) and stored at `out_lines`."""
    path = os.path.join(TMP, name)
    if not os.path.isfile(path):
        w = int(round(lines * 16 / 9 / 2)) * 2
        ow = int(round(out_lines * 16 / 9 / 2)) * 2
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={w}x{lines}:r=30:d={seconds}",
                        "-vf", f"scale={ow}:{out_lines}:flags=lanczos", "-c:v", "libx264", "-preset", "ultrafast",
                        "-crf", "16", "-pix_fmt", "yuv420p", path], check=True, capture_output=True)
    return path


class Measure(unittest.TestCase):
    """The round trip reads back how much of a picture's size is real."""

    def setUp(self):
        sharpness.reset()

    def test_a_sharp_picture_reads_its_own_size_and_an_upscaled_one_its_source(self):
        with mock.patch.multiple(config, **ON):
            sharp = sharpness.real_detail(picture("sharp.jpg"))
            soft = sharpness.real_detail(picture("from640.jpg", real=1 / 3))
            half = sharpness.real_detail(picture("from960.jpg", real=0.5))
        self.assertGreaterEqual(sharp[0], 1700)
        self.assertLess(soft[0], 900)                       # a 640 px picture in a 1920 px file
        self.assertTrue(800 <= half[0] <= 1250, half)       # a 960 px one
        self.assertEqual(sharp, (sharp[0], round(sharp[0] * 1080 / 1920)))   # the stored proportions

    def test_a_dark_flat_copy_of_a_sharp_picture_still_reads_sharp(self):
        # A dusk photo loses little in any round trip; the measure reads it as if it filled the range.
        with mock.patch.multiple(config, **ON):
            self.assertGreaterEqual(sharpness.real_detail(picture("dusk.jpg", contrast=0.4, seed=4))[0], 1600)
            # ... and a dark copy of an upscaled one still reads soft.
            self.assertLess(sharpness.real_detail(picture("dusk_soft.jpg", contrast=0.4, real=0.4, seed=4))[0], 1000)

    def test_a_big_photo_counts_only_what_the_screen_can_show(self):
        with mock.patch.multiple(config, **ON):
            w, h = sharpness.real_detail(picture("big.jpg", 3840, 2560))
        self.assertGreaterEqual(w, 1700)                    # its detail at the screen's size at least
        self.assertAlmostEqual(w / h, 1.5, places=1)

    def test_it_is_quick(self):
        p = picture("timed.jpg", real=0.6, seed=7)
        with mock.patch.multiple(config, **ON):
            t0 = time.time()
            sharpness.real_detail(p)
            first = time.time() - t0
            t0 = time.time()
            sharpness.real_detail(p)                        # the same file again: from memory
            again = time.time() - t0
        self.assertLess(first, 2.0)
        self.assertLess(again, 0.05)

    def test_magnification_is_a_cover_fit_times_the_moves_zoom(self):
        self.assertAlmostEqual(sharpness.screen_magnification(1920, 1080), 1.0)
        self.assertAlmostEqual(sharpness.screen_magnification(960, 540), 2.0)
        self.assertAlmostEqual(sharpness.screen_magnification(1920, 1080, zoom=1.15), 1.15)
        # A portrait picture is cropped to fill the width: 1080 px wide is blown up 1.78x.
        self.assertAlmostEqual(sharpness.screen_magnification(1080, 1920), 1920 / 1080, places=3)
        self.assertAlmostEqual(sharpness.screen_magnification(2160, 3840), 1920 / 2160, places=3)
        # A panorama is cropped to a band: its height decides.
        self.assertAlmostEqual(sharpness.screen_magnification(4000, 900), 1.2, places=3)
        self.assertEqual(sharpness.screen_magnification(0, 0), float("inf"))

    def test_the_moves_zoom_comes_from_the_renderers_still_motions(self):
        from src.timeline import _IMAGE_MOTIONS
        self.assertTrue(set(_IMAGE_MOTIONS) <= set(sharpness.MOTION_ZOOM))
        self.assertEqual(sharpness.motion_zoom("push-offcenter"), 1.22)
        self.assertEqual(sharpness.motion_zoom(None), sharpness.DEFAULT_ZOOM)
        with mock.patch.multiple(config, **ON):
            self.assertAlmostEqual(sharpness.planned_zoom(), 1.16)
            with mock.patch.object(config, "STILL_MOTION", "none"):
                self.assertEqual(sharpness.planned_zoom(), sharpness.DEFAULT_ZOOM)
            # The default limit is 1.25 at rest for the planner's typical move: 1536 px across.
            self.assertEqual(sharpness.min_size(), (1536, 864))

    def test_a_portrait_needs_the_width_to_fill_the_frame(self):
        with mock.patch.multiple(config, **ON):
            self.assertFalse(sharpness.possible(1200, 1800))      # every pixel real, still 1.86x
            self.assertTrue(sharpness.possible(2000, 3000))
            self.assertTrue(sharpness.possible(1536, 864))
            self.assertFalse(sharpness.possible(1500, 1000))
            self.assertTrue(sharpness.possible(0, 0))             # size unknown: try it
            port = picture("portrait.jpg", 1200, 1800, seed=5)
            got = sharpness.picture_check(port)
        self.assertFalse(got["ok"])
        self.assertIn("a blurry picture", got["why"])

    def test_a_search_engine_thumbnail_never_passes(self):
        thumb = picture("thumb.jpg", 400, 250, seed=6)
        with mock.patch.multiple(config, **ON):
            self.assertFalse(sharpness.possible(400, 250))
            got = sharpness.picture_check(thumb)
        self.assertFalse(got["ok"])
        self.assertGreater(got["magnification"], 4.0)

    def test_magnification_does_not_depend_on_the_frame_rate(self):
        # A still has no frames of its own: the same picture, the same move, any fps.
        p = picture("fps.jpg", real=0.5, seed=8)
        docs = [_doc([("image", p, "zoom-in")], fps) for fps in (30, 60)]
        with mock.patch.multiple(config, **ON):
            found = [quality.Gate(d, TMP)._soft_scenes(_checks(d)) for d in docs]
        self.assertEqual(set(found[0]), {0})
        self.assertEqual(found[0][0]["before"], found[1][0]["before"])

    def test_checks_off_measure_nothing(self):
        with mock.patch.multiple(config, **OFF), mock.patch.object(sharpness, "real_detail") as rd:
            self.assertTrue(sharpness.picture_check(picture("off.jpg", real=0.3))["ok"])
            self.assertTrue(sharpness.possible(100, 100))
        rd.assert_not_called()


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class Clips(unittest.TestCase):
    """A clip's best frame decides; an upscaled upload is soft in all of them."""

    def setUp(self):
        sharpness.reset()

    def test_an_upscaled_upload_is_low_detail_and_a_real_one_is_not(self):
        with mock.patch.multiple(config, **ON):
            real = sharpness.clip_check(clip("real1080.mp4", 1080))
            fake = sharpness.clip_check(clip("from360.mp4", 360))
            hd = sharpness.clip_check(clip("real720.mp4", 720, out_lines=720))
        self.assertTrue(real["ok"], real)
        self.assertTrue(hd["ok"], hd)
        self.assertFalse(fake["ok"])
        self.assertIn("low detail", fake["why"])
        self.assertLess(fake["lines"], 576)

    def test_archive_film_is_exempt_and_the_check_can_be_off(self):
        p = clip("from360b.mp4", 360)
        with mock.patch.multiple(config, **ON):
            self.assertTrue(sharpness.clip_check(p, archive=True)["ok"])
            self.assertTrue(media.clip_detail_reason(p, "1936 Pathe newsreel of the dam") == "")
        with mock.patch.multiple(config, **OFF):
            self.assertTrue(sharpness.clip_check(p)["ok"])

    def test_the_first_frame_that_holds_enough_ends_the_check(self):
        p = clip("real1080b.mp4", 1080, seconds=3.0)
        with mock.patch.multiple(config, **ON), \
                mock.patch.object(sharpness, "_frame", wraps=sharpness._frame) as frame:
            self.assertTrue(sharpness.clip_check(p)["ok"])
        self.assertEqual(frame.call_count, 1)

    def test_a_sequences_shots_carry_their_windows_measure(self):
        p = clip("window.mp4", 1080)
        shot = os.path.join(TMP, "window_shot.mp4")
        shutil.copyfile(p, shot)
        with mock.patch.multiple(config, **ON):
            sharpness.clip_detail(p)
            sharpness.same_detail(p, [shot])
            with mock.patch.object(sharpness, "_frame", side_effect=AssertionError("measured again")):
                self.assertTrue(sharpness.clip_check(shot)["ok"])

    def test_a_low_detail_upload_is_skipped_for_the_whole_video(self):
        with mock.patch.dict(media._BAD, clear=True):
            media._mark_bad("yt:abcdefghijk", "yt:abcdefghijk@3", "low detail: about 600x338 real of 1920x1080")
            self.assertTrue(media._is_bad("yt:abcdefghijk"))
            media._mark_bad("web:x", "", "a blurry picture: real detail about 400x250")
            self.assertTrue(media._is_bad("web:x"))

    def test_the_floor_for_modern_clips_is_720_lines(self):
        self.assertEqual(config.MIN_CLIP_HEIGHT, int(os.getenv("MIN_CLIP_HEIGHT", "720")))
        self.assertEqual(config.MIN_ARCHIVE_HEIGHT, int(os.getenv("MIN_ARCHIVE_HEIGHT", "240")))

    def test_downloads_take_the_best_bitrate_up_to_1080p(self):
        from src import ytdlp
        with mock.patch.multiple(config, **ON):
            self.assertEqual(ytdlp.best_bitrate(), ["-S", "res:1080,br"])
            with mock.patch.object(ytdlp, "_video_unavailable", return_value=False), \
                    mock.patch.object(ytdlp, "stopped", return_value=False), \
                    mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                    mock.patch.object(ytdlp, "_release_proxy"), \
                    mock.patch.object(ytdlp.subprocess, "run",
                                      return_value=mock.Mock(returncode=1, stdout="", stderr="x")) as run:
                ytdlp._yt_fetch("abcdefghijk", TMP, 10.0, 5.0)
            cmd = run.call_args.args[0]
            self.assertIn("res:1080,br", cmd)
            self.assertIn("bv*[height<=1080][ext=mp4][protocol^=https]", cmd[cmd.index("-f") + 1])
        with mock.patch.multiple(config, **OFF):
            self.assertEqual(ytdlp.best_bitrate(), [])


class Sourcing(unittest.TestCase):
    """A soft picture is turned down right after its download: no vision call, never again."""

    def setUp(self):
        sharpness.reset()
        self.bad = mock.patch.dict(media._BAD, clear=True)
        self.bad.start()

    def tearDown(self):
        self.bad.stop()

    def _cands(self, *names):
        return [MediaAsset(kind="image", source="web_image", url=f"https://img.example/{n}.jpg", query="q")
                for n in names]

    def _download(self, files):
        def fake(c, query, work):
            c.local_path = files[c.url.rsplit("/", 1)[-1][:-4]]
            return c
        return fake

    def test_a_blurry_download_never_costs_a_vision_call(self):
        files = {"soft": picture("p_soft.jpg", real=0.35, seed=11), "sharp": picture("p_sharp.jpg", seed=12)}
        judged = []

        def gate(path, *a, **k):
            judged.append(os.path.basename(path))
            return True, None
        with mock.patch.multiple(config, **ON), \
                mock.patch.object(media, "_download", side_effect=self._download(files)), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_vision_gate", side_effect=gate):
            got = media._pick_unused(self._cands("soft", "sharp"), set(), "q", TMP, "a lake")
            again = media._pick_unused(self._cands("soft"), set(), "q", TMP, "a lake")
        self.assertEqual(got.url, "https://img.example/sharp.jpg")
        self.assertEqual(judged, ["p_sharp.jpg"])
        self.assertIsNone(again)                            # another scene skips it without a download
        self.assertTrue(media._is_bad("web_image:https://img.example/soft.jpg"))
        self.assertIn("magnification", got.score_parts)

    def test_a_result_too_small_to_be_sharp_is_never_downloaded(self):
        small, big = self._cands("small", "big")
        small.width, small.height = 1200, 800
        big.width, big.height = 2400, 1600
        files = {"big": picture("p_big.jpg", 2400, 1600, seed=13)}
        with mock.patch.multiple(config, **ON), \
                mock.patch.object(media, "_download", side_effect=self._download(files)) as dl, \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_vision_gate", return_value=(True, None)):
            got = media._pick_unused([small, big], set(), "q", TMP, "a dam")
        self.assertEqual(got.url, big.url)
        self.assertEqual(dl.call_count, 1)

    def test_among_neighbours_the_bigger_picture_is_tried_first(self):
        a, b, c, d = self._cands("a", "b", "c", "d")
        a.width, a.height = 0, 0                 # unknown: keeps its turn
        b.width, b.height = 1600, 900            # can pass
        c.width, c.height = 900, 600             # never could: left out
        d.width, d.height = 3000, 2000
        with mock.patch.multiple(config, **ON):
            order = [x.url[-5] for x in media._bigger_first([a, b, c, d])]
        with mock.patch.multiple(config, **OFF):
            plain = [x.url[-5] for x in media._bigger_first([a, b, c, d])]
        self.assertEqual(order, ["b", "a", "d"])
        self.assertEqual(plain, ["a", "b", "c", "d"])

    def test_the_search_engines_thumbnail_is_not_fetched_while_pictures_must_be_sharp(self):
        cand = MediaAsset(kind="image", source="web_image", url="https://img.example/x.jpg",
                          thumbnail="https://tse.example/th.jpg")
        for flags, want in ((ON, ""), (OFF, "https://tse.example/th.jpg")):
            with mock.patch.multiple(config, **flags), \
                    mock.patch.object(media._imagefix, "fetch", return_value=os.path.join(TMP, "x.jpg")) as f:
                media._download(cand, "q", TMP)
            self.assertEqual(f.call_args.kwargs["thumbnail"], want)

    def test_asset_ok_turns_down_a_blurry_picture_and_keeps_a_sharp_one(self):
        soft = MediaAsset(kind="image", source="web_image", url="u1", local_path=picture("ok_soft.jpg", real=0.4))
        sharp = MediaAsset(kind="image", source="web_image", url="u2", local_path=picture("ok_sharp.jpg", seed=2))
        gen = MediaAsset(kind="image", source="generated", url="", local_path=picture("ok_gen.jpg", real=0.4))
        with mock.patch.multiple(config, **ON), mock.patch("src.filters.text_page_still", return_value=False):
            self.assertFalse(media._asset_ok(soft)[0])
            self.assertIn("a blurry picture", media._asset_ok(soft)[1])
            self.assertEqual(media._asset_ok(sharp), (True, ""))
            self.assertEqual(media._asset_ok(gen), (True, ""))  # an AI picture is made at its size
        with mock.patch.multiple(config, **OFF), mock.patch("src.filters.text_page_still", return_value=False):
            self.assertEqual(media._asset_ok(soft), (True, ""))

    def test_the_second_pass_checks_side_by_side_with_the_same_verdicts(self):
        assets = {i: MediaAsset(kind="image", source="web_image", url=f"u{i}",
                                local_path=picture(f"v{i}.jpg", real=(0.4 if i % 2 else 1.0), seed=20 + i))
                  for i in range(6)}
        with mock.patch.multiple(config, **ON), mock.patch("src.filters.text_page_still", return_value=False):
            together = media._verdicts(assets, 4)
            alone = {i: media._asset_ok(a) for i, a in assets.items()}
        self.assertEqual(together, alone)
        self.assertEqual([i for i, v in sorted(together.items()) if not v[0]], [1, 3, 5])

    def test_a_near_tie_goes_to_the_sharper_clip(self):
        def asset(name, lines):
            a = MediaAsset(kind="video", source="youtube", url=name, local_path="", relevance_score=0.8)
            a.final_score = 0.7
            a.score_parts = {"lines": lines}
            return a
        with mock.patch.multiple(config, **ON):
            self.assertEqual(media._best_of([asset("soft", 600), asset("sharp", 980)]).url, "sharp")
        with mock.patch.multiple(config, **OFF):
            self.assertEqual(media._best_of([asset("soft", 600), asset("sharp", 980)]).url, "soft")
        with mock.patch.multiple(config, **ON):                     # relevance still leads
            better = asset("relevant", 600)
            better.final_score = 0.8
            self.assertEqual(media._best_of([asset("sharp", 980), better]).url, "relevant")


class Searches(unittest.TestCase):
    """Big pictures are asked for first; the plain search only adds to too few."""

    def setUp(self):
        media.reset_cache()

    def _rows(self, n, w=2400, h=1600, tag="big"):
        return [(f"https://site.example/{tag}{k}.jpg", w, h, f"{tag} {k}", f"https://site.example/p{k}", "")
                for k in range(n)]

    def _ddgs(self, rows):
        inst = mock.MagicMock()
        inst.__enter__.return_value.images.return_value = [
            {"image": u, "width": w, "height": h, "title": t, "url": p, "thumbnail": th} for u, w, h, t, p, th in rows]
        return mock.patch("ddgs.DDGS", return_value=inst), inst

    def test_web_images_ask_the_sized_search_first(self):
        patch, inst = self._ddgs(self._rows(10, tag="plain"))
        with mock.patch.multiple(config, **ON), mock.patch.object(config, "SERPER_API_KEY", ""), \
                mock.patch.object(media, "_sized_image_rows", return_value=self._rows(10)) as sized, patch:
            got = media.search_web_images("Glen Canyon Dam")
        sized.assert_called_once()
        inst.__enter__.return_value.images.assert_not_called()
        self.assertEqual(len(got), 6)
        self.assertTrue(all("/big" in a.url for a in got))

    def test_too_few_big_pictures_add_the_plain_search_without_its_small_ones(self):
        plain = self._rows(3, 2400, 1600, tag="plainbig") + self._rows(5, 1000, 700, tag="plainsmall")
        patch, inst = self._ddgs(plain)
        with mock.patch.multiple(config, **ON), mock.patch.object(config, "SERPER_API_KEY", ""), \
                mock.patch.object(media, "_sized_image_rows", return_value=self._rows(2)), patch:
            got = media.search_web_images("a niche subject")
        urls = [a.url for a in got]
        self.assertEqual(urls[:2], ["https://site.example/big0.jpg", "https://site.example/big1.jpg"])
        self.assertTrue(any("plainbig" in u for u in urls))
        self.assertFalse(any("plainsmall" in u for u in urls))

    def test_a_graphics_photo_window_and_the_check_off_use_the_plain_search(self):
        for flags, kw in ((ON, {"full_screen": False}), (OFF, {})):
            patch, inst = self._ddgs(self._rows(8, 1000, 700, tag="plain"))
            media.reset_cache()
            with mock.patch.multiple(config, **flags), mock.patch.object(config, "SERPER_API_KEY", ""), \
                    mock.patch.object(media, "_sized_image_rows", side_effect=AssertionError("sized")), patch:
                got = media.search_web_images("Lake Mead", **kw)
            self.assertEqual(len(got), 6)                   # small ones kept, as before

    def test_yandex_asks_bigger_than_the_frame_needs_first(self):
        page = mock.Mock(url="https://yandex.com/images/search", text="".join(
            f'img_url=https%3A%2F%2Fsite.example%2F{k}.jpg&' for k in range(10)))
        with mock.patch.multiple(config, **ON), mock.patch.object(config, "ALLOW_YANDEX_IMAGES", True), \
                mock.patch.object(media, "_next_proxy", return_value=""), \
                mock.patch.object(media.requests, "get", return_value=page) as get:
            got = media.search_yandex_images("Glen Canyon Dam")
        self.assertEqual(len(got), 8)
        self.assertEqual(get.call_count, 1)
        self.assertEqual({k: v for k, v in get.call_args.kwargs["params"].items() if k != "text"},
                         {"isize": "gt", "iw": "1536", "ih": "864"})
        with mock.patch.multiple(config, **OFF), mock.patch.object(config, "ALLOW_YANDEX_IMAGES", True), \
                mock.patch.object(media, "_next_proxy", return_value=""), \
                mock.patch.object(media.requests, "get", return_value=page) as get:
            media.search_yandex_images("Glen Canyon Dam")
        self.assertEqual(get.call_args.kwargs["params"]["isize"], "large")

    def test_wikimedia_files_come_at_the_size_the_frame_needs(self):
        def info(ow, oh, tw=1920, name="F.jpg"):
            return {"width": ow, "height": oh, "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{name}",
                    "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{name}/{tw}px-{name}",
                    "thumbwidth": min(tw, ow), "thumbheight": round(oh * min(tw, ow) / ow)}
        with mock.patch.multiple(config, **ON):
            self.assertTrue(media._commons_full_screen(info(4000, 3000))[0].endswith("/1920px-F.jpg"))
            pano = media._commons_full_screen(info(8000, 2400))           # a band of it fills the frame
            self.assertTrue(pano[0].endswith("/3840px-F.jpg"))
            self.assertEqual(pano[1:], (3840, 1152))
            wide = media._commons_full_screen(info(8000, 1500))           # even 3840 px is too short: the original
            self.assertEqual(wide, ("https://upload.wikimedia.org/wikipedia/commons/a/ab/F.jpg", 8000, 1500))
            orig = media._commons_full_screen(info(3000, 900))            # under 3840: the original itself
            self.assertEqual(orig[0], "https://upload.wikimedia.org/wikipedia/commons/a/ab/F.jpg")
            self.assertIsNone(media._commons_full_screen(info(1200, 900)))  # even the original would be soft
            self.assertIsNone(media._commons_full_screen(info(1400, 2100)))  # a portrait 1400 px wide

    def test_a_wikipedia_article_asks_for_copies_that_fill_the_frame(self):
        def page(title, w, h):
            return {"title": title, "imageinfo": [{"mime": "image/jpeg", "width": w, "height": h,
                                                   "url": f"https://u/{title}", "thumburl": f"https://t/1920px-{title}",
                                                   "thumbwidth": min(1920, w), "thumbheight": round(h * min(1920, w) / w),
                                                   "extmetadata": {}}]}
        r = mock.Mock()
        r.raise_for_status = lambda: None
        r.json.return_value = {"query": {"pages": {"1": page("File:Dam.jpg", 4000, 3000),
                                                   "2": page("File:Small.jpg", 1200, 900)}}}
        with mock.patch.multiple(config, **ON), mock.patch.object(media.requests, "get", return_value=r) as get:
            got = media.search_wikipedia_article_images("Glen Canyon Dam")
        self.assertEqual(get.call_args.kwargs["params"]["iiurlwidth"], 1920)
        self.assertEqual([a.url for a in got], ["https://t/1920px-File:Dam.jpg"])
        with mock.patch.multiple(config, **OFF), mock.patch.object(media.requests, "get", return_value=r) as get:
            got = media.search_wikipedia_article_images("Glen Canyon Dam")
        self.assertEqual(get.call_args.kwargs["params"]["iiurlwidth"], 1280)
        self.assertEqual(len(got), 2)


def _doc(shots, fps=30):
    """A timeline of full-screen shots: [(kind, local file, motion)], 4 s each."""
    scenes = []
    for n, (kind, path, motion) in enumerate(shots):
        scenes.append({"id": f"s{n:04d}", "startFrame": n * 4 * fps, "durationInFrames": 4 * fps,
                       "text": f"line {n}", "frame": "full", "motion": motion,
                       "media": {"type": kind, "url": path, "source": "web_image" if kind == "image" else "youtube",
                                 **({"clipSeconds": 4.5} if kind == "video" else {})},
                       "semanticMetadata": {"subject": "Lake Powell", "searchQuery": f"lake powell {n}"}})
    return {"fps": fps, "width": 1920, "height": 1080, "durationInFrames": len(shots) * 4 * fps,
            "scenes": scenes, "overlays": [], "meta": {}}


def _checks(doc):
    return {s["media"]["url"]: quality.Check(ok=True, local=s["media"]["url"]) for s in doc["scenes"]}


class Gate(unittest.TestCase):
    """The quality gate replaces a soft shot from the ladder, or keeps it - never empties a scene."""

    def setUp(self):
        sharpness.reset()
        quality.set_context(ladder=True)

    def tearDown(self):
        quality.reset()

    def test_a_blurry_picture_is_replaced_and_one_with_nothing_sharper_is_kept(self):
        sharp, soft_a, soft_b = (picture("g_sharp.jpg", seed=30), picture("g_soft_a.jpg", real=0.4, seed=31),
                                 picture("g_soft_b.jpg", real=0.4, seed=32))
        better = picture("g_better.jpg", 2400, 1600, seed=33)
        doc = _doc([("image", sharp, "zoom-in"), ("image", soft_a, "pan-left"), ("image", soft_b, "push-offcenter")])
        calls = {}

        def fill(jobs, results, work, **kw):
            calls.update(kw)
            results[1] = MediaAsset(kind="image", source="web_image", url="https://site.example/better.jpg",
                                    local_path=better, review_reason="A picture found when ...")
            return {"asked": 2}
        gate = quality.Gate(doc, TMP)
        with mock.patch.multiple(config, **ON), mock.patch.object(config, "FALLBACK_FILL", True), \
                mock.patch.object(gapfill, "fill_empty", side_effect=fill), \
                mock.patch.object(handler.renderer, "render", side_effect=AssertionError("no render here")):
            fixed = gate._sharpen(_checks(doc), spent=0.0)
        self.assertEqual(fixed, 1)
        # The softest first (the push-offcenter move zooms in further), in that order.
        self.assertEqual(calls["indices"], [2, 1])
        self.assertTrue(calls["keep_order"])
        self.assertGreaterEqual(calls["seconds"], config.QUALITY_SHARPEN_MIN_SECONDS)
        scenes = doc["scenes"]
        self.assertEqual(scenes[0]["media"]["url"], sharp)               # sharp: untouched
        self.assertEqual(scenes[1]["media"]["url"], better)              # replaced from the ladder
        self.assertEqual(scenes[2]["media"]["url"], soft_b)              # nothing sharper: kept as it was
        self.assertEqual(scenes[2]["media"]["type"], "image")
        self.assertFalse(any(o.get("type") == "highlight" for o in doc["overlays"]))   # never a text card
        rep = [r for r in gate.repairs if r["problem"] == "blurry"]
        self.assertEqual(len(rep), 1)
        self.assertGreater(rep[0]["before"], config.MAX_PICTURE_MAGNIFICATION)
        self.assertLessEqual(rep[0]["after"], config.MAX_PICTURE_MAGNIFICATION)
        self.assertEqual(gate.found["blurry"], 2)
        self.assertEqual(gate.fixed["sharper"], 1)
        self.assertEqual(len(gate.sharp["kept"]), 1)
        self.assertFalse(gate.rerendered)
        report = gate.finish()
        self.assertIn("1 soft shot replaced with a sharper one", report["summary"])
        self.assertIn("1 soft shot kept", report["summary"])
        self.assertEqual(report["sharpness"]["replaced"], 1)

    def test_a_scene_the_ladder_leaves_empty_gets_its_own_shot_back(self):
        soft = picture("g_soft_c.jpg", real=0.4, seed=34)
        doc = _doc([("image", soft, "zoom-in")])
        before = dict(doc["scenes"][0]["media"])

        def blank(self_, order, banned, problems, seconds=None, keep_order=False):
            for i in order:
                self_.doc["scenes"][i]["media"] = {"type": "color", "url": "", "source": "none"}
            return {}
        gate = quality.Gate(doc, TMP)
        with mock.patch.multiple(config, **ON), mock.patch.object(config, "FALLBACK_FILL", True), \
                mock.patch.object(quality.Gate, "_ladder", blank):
            self.assertEqual(gate._sharpen(_checks(doc)), 0)
        self.assertEqual(doc["scenes"][0]["media"], before)
        self.assertFalse(gapfill._empty(doc["scenes"][0]))

    def test_without_the_ladder_a_soft_shot_is_reported_and_kept(self):
        soft = picture("g_soft_d.jpg", real=0.4, seed=35)
        doc = _doc([("image", soft, "zoom-in")])
        quality.set_context(ladder=False)
        gate = quality.Gate(doc, TMP)
        with mock.patch.multiple(config, **ON), \
                mock.patch.object(gapfill, "fill_empty", side_effect=AssertionError("no ladder")):
            self.assertEqual(gate._sharpen(_checks(doc)), 0)
        self.assertEqual(doc["scenes"][0]["media"]["url"], soft)
        self.assertEqual(gate.found["blurry"], 1)

    def test_the_whole_check_before_the_render_runs_it(self):
        soft = picture("g_soft_e.jpg", real=0.4, seed=36)
        doc = _doc([("image", picture("g_sharp_e.jpg", seed=37), "zoom-in"), ("image", soft, "zoom-out")])
        with mock.patch.multiple(config, **ON), mock.patch.object(config, "FALLBACK_FILL", True), \
                mock.patch.object(gapfill, "fill_empty", return_value={}):
            quality.Gate(doc, TMP).before_render()
        self.assertEqual(doc["meta"].get("quality"), None)              # the report is written by finish()
        self.assertEqual([s["media"]["url"] for s in doc["scenes"]][1], soft)

    def test_generated_pictures_insets_and_archive_film_are_left_alone(self):
        soft = picture("g_soft_f.jpg", real=0.4, seed=38)
        doc = _doc([("image", soft, "zoom-in"), ("image", soft, "zoom-in")])
        doc["scenes"][0]["media"]["source"] = "generated"
        doc["scenes"][1]["frame"] = "inset"
        with mock.patch.multiple(config, **ON):
            self.assertEqual(quality.Gate(doc, TMP)._soft_scenes(_checks(doc)), {})

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_a_low_detail_clip_is_found_and_archive_film_is_not(self):
        fake = clip("g_from360.mp4", 360)
        doc = _doc([("video", fake, "none"), ("video", fake, "none")])
        doc["scenes"][1]["media"]["attribution"] = "YouTube: 1936 newsreel"
        with mock.patch.multiple(config, **ON):
            found = quality.Gate(doc, TMP)._soft_scenes(_checks(doc))
        self.assertEqual(list(found), [0])
        self.assertEqual(found[0]["kind"], "video")

    def test_with_the_checks_off_the_gate_measures_nothing(self):
        doc = _doc([("image", picture("g_soft_g.jpg", real=0.3, seed=39), "zoom-in")])
        with mock.patch.multiple(config, **OFF), mock.patch.object(sharpness, "real_detail") as rd:
            self.assertEqual(quality.Gate(doc, TMP)._sharpen(_checks(doc)), 0)
        rd.assert_not_called()


class KeptForLater(unittest.TestCase):
    """The library and the packs keep only what is sharp enough to fill a frame."""

    def setUp(self):
        sharpness.reset()

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_the_library_check_turns_down_a_blurry_picture(self):
        soft = picture("lib_soft.jpg", real=0.4, seed=40)
        sharp = picture("lib_sharp.jpg", seed=41)
        with mock.patch.multiple(config, **ON):
            bad = libstore.check(soft, kind="image", clip=False)
            good = libstore.check(sharp, kind="image", clip=False)
        self.assertFalse(bad.ok)
        self.assertTrue(any(r.startswith("a blurry picture") for r in bad.reasons))
        self.assertTrue(good.ok, good.reasons)
        self.assertIn("magnification", good.measures)

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_a_pack_clip_with_little_detail_is_left_out_and_not_fetched_again(self):
        src = clip("pack_from360.mp4", 360, seconds=4.0)
        entry = mock.Mock(id="water:nasa:1@0", url=src, seconds=4.0, title="flood", attribution="NASA",
                          source="nasa", license_class="pd", license="PD", width=1920, height=1080,
                          topics=["flood"], niche="water", moment_url="https://x/1", asset_id="pack:water:nasa:1@0",
                          start=0.0)
        packs.reset()
        with mock.patch.multiple(config, **ON):
            self.assertIsNone(packs.fetch(entry, TMP, {"intent": "a flood"}))
        self.assertIn(entry.id, packs._SOFT)

    def test_a_library_row_too_soft_for_the_frame_is_taken_out_reversibly(self):
        from src import library
        soft = picture("lib_row_soft.jpg", real=0.4, seed=42)
        lib = library.Library.__new__(library.Library)
        lib.bucket, lib.project_id, lib.job_id = "b", "p", "j"
        lib.pending, lib.used, lib.entries = {}, set(), []
        import threading
        lib._lock = threading.Lock()
        entry = {"id": "img:1", "kind": "image", "path": "x.jpg", "read_url": "https://lib/x.jpg", "saved": True,
                 "attribution": "web", "source": "web_image", "bucket": "r2:lib"}

        def dl(url, path, **kw):
            shutil.copyfile(soft, path)
        with mock.patch.multiple(config, **ON), mock.patch.object(library.storage, "download", side_effect=dl), \
                mock.patch.object(library.media, "slop_reason", return_value=""), \
                mock.patch("src.slop.metadata_reason", return_value=""):
            self.assertIsNone(lib.fetch(entry, TMP, 5.0, {}))
        self.assertFalse(entry["saved"])
        self.assertIn("img:1", lib.pending)


class Flags(unittest.TestCase):
    def test_a_job_may_set_them(self):
        for key in ("PICTURE_SHARPNESS_CHECK", "MAX_PICTURE_MAGNIFICATION", "CLIP_SHARPNESS_CHECK",
                    "MIN_CLIP_REAL_HEIGHT", "MIN_CLIP_HEIGHT"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
            self.assertTrue(hasattr(config, key))
        prev = handler._apply_config({"MAX_PICTURE_MAGNIFICATION": "1.6", "PICTURE_SHARPNESS_CHECK": "0",
                                      "MIN_CLIP_REAL_HEIGHT": "540"})
        try:
            self.assertEqual(config.MAX_PICTURE_MAGNIFICATION, 1.6)
            self.assertFalse(config.PICTURE_SHARPNESS_CHECK)
            self.assertEqual(config.MIN_CLIP_REAL_HEIGHT, 540)
        finally:
            handler._restore_config(prev)

    def test_with_the_checks_off_sourcing_is_what_it_was(self):
        """Plans identical to base: the same candidates in the same order, nothing measured or skipped."""
        files = {"soft": picture("f_soft.jpg", real=0.3, seed=50), "sharp": picture("f_sharp.jpg", seed=51)}
        cands = [MediaAsset(kind="image", source="web_image", url=f"https://img.example/{n}.jpg", query="q",
                            width=w, height=h) for n, w, h in (("soft", 1000, 700), ("sharp", 2400, 1600))]

        def fake(c, query, work):
            c.local_path = files[c.url.rsplit("/", 1)[-1][:-4]]
            return c
        with mock.patch.multiple(config, **OFF), mock.patch.dict(media._BAD, clear=True), \
                mock.patch.object(media, "_download", side_effect=fake), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_vision_gate", return_value=(True, None)), \
                mock.patch.object(sharpness, "real_detail", side_effect=AssertionError("measured")):
            got = media._pick_unused(list(cands), set(), "q", TMP, "a lake")
            ok = media._asset_ok(got)
        self.assertEqual(got.url, "https://img.example/soft.jpg")      # the first, as before
        self.assertEqual(ok, (True, ""))
        self.assertNotIn("magnification", got.score_parts)


if __name__ == "__main__":
    unittest.main()
