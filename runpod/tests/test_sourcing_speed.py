"""
Where a picture search's time goes (the Yellowstone re-cut, 9c467873, 2026-10-04:
136 pieces then 52, most of them ending on "the time box ran out").

A candidate picture gets every check its caller asks of it afterwards
(media._asset_ok: not a page of text, big enough, sharp enough) BEFORE the
vision judge: six of the re-cut's 39 empty pieces ended on "a page of text,
not a photo" - a picture the judge had passed, thrown out by the caller,
and the whole search then run again.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw  # noqa: E402

from src import media  # noqa: E402
from src.media import MediaAsset  # noqa: E402


def slide(path: str) -> str:
    """A page of text: white, rows of letter-like strokes (as tests/test_glen_fixes.py draws one)."""
    im = Image.new("RGB", (1280, 720), "white")
    d = ImageDraw.Draw(im)
    for row in range(8):
        y = 60 + row * 80
        for x in range(40, 1240, 14):
            d.rectangle([x, y, x + 5, y + 30], fill="black")
    im.save(path, "JPEG", quality=90)
    return path


def photo(path: str) -> str:
    Image.effect_noise((1280, 720), 50).convert("RGB").save(path, "JPEG", quality=85)
    return path


class ChecksBeforeTheJudge(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="speed_")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.files = {"slide": slide(os.path.join(self.work, "slide.jpg")),
                      "photo": photo(os.path.join(self.work, "photo.jpg"))}
        self.judged = []
        bad = mock.patch.dict(media._BAD, clear=True)
        bad.start()
        self.addCleanup(bad.stop)

    def _cands(self):
        return [MediaAsset(kind="image", source="web_image", url=f"https://img.example/{n}.jpg", query="q")
                for n in ("slide", "photo")]

    def _pick(self, subject_type: str):
        def download(c, query, work):
            c.local_path = self.files[c.url.rsplit("/", 1)[-1][:-4]]
            return c

        def gate(path, *a, **k):
            self.judged.append(os.path.basename(path))
            return True, {"score": 0.8, "description": "", "quality": 0.7}
        token = media._SUBJECT_TYPE.set(subject_type)
        try:
            with mock.patch.object(media, "_download", side_effect=download), \
                    mock.patch.object(media, "_photo_seen_before", return_value=False), \
                    mock.patch.object(media, "_vision_gate", side_effect=gate):
                return media._pick_unused(self._cands(), set(), "q", self.work, "the lake shore")
        finally:
            media._SUBJECT_TYPE.reset(token)

    def test_a_page_of_text_never_costs_a_vision_call(self):
        got = self._pick("place")
        self.assertEqual(got.url, "https://img.example/photo.jpg")
        self.assertEqual(self.judged, ["photo.jpg"])
        self.assertEqual(media._asset_ok(got), (True, ""))            # what the caller asks next

    def test_a_line_about_a_document_still_gets_its_page(self):
        got = self._pick("document")
        self.assertEqual(got.url, "https://img.example/slide.jpg")
        self.assertEqual(self.judged, ["slide.jpg"])


class DownloadsAhead(unittest.TestCase):
    """The next candidates download while one is checked and judged; the order and the checks stay the same."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="ahead_")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.file = photo(os.path.join(self.work, "p.jpg"))
        self.started, self.judged = [], []
        bad = mock.patch.dict(media._BAD, clear=True)
        bad.start()
        self.addCleanup(bad.stop)

    def _cands(self, *names):
        return [MediaAsset(kind="image", source="web_image", url=f"https://img.example/{n}.jpg", query="q")
                for n in names]

    def _run(self, names, delays, keep, ahead):
        import threading
        import time
        lock = threading.Lock()

        def download(c, query, work):
            name = c.url.rsplit("/", 1)[-1][:-4]
            with lock:
                self.started.append(name)
            time.sleep(delays.get(name, 0.0))
            c.local_path = self.file
            return c

        def gate(path, intent, context, label, source_url=""):
            name = source_url.rsplit("/", 1)[-1][:-4]
            self.judged.append(name)
            time.sleep(0.05)
            return name in keep, ({"score": 0.8, "description": "", "quality": 0.7} if name in keep else None)
        with mock.patch.object(media.config, "PICTURE_PREFETCH", ahead), \
                mock.patch.object(media.config, "VISION_MAX_CANDIDATES", 10), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_vision_gate", side_effect=gate):
            t0 = time.time()
            got = media._pick_unused(self._cands(*names), set(), "q", self.work, "the lake shore")
            return got, time.time() - t0

    def test_the_next_pictures_download_while_one_is_judged(self):
        names, delays = ("a", "b", "c"), {"a": 0.3, "b": 0.3, "c": 0.3}
        got, together = self._run(names, delays, keep={"c"}, ahead=3)
        self.assertEqual(got.url, "https://img.example/c.jpg")
        self.assertEqual(self.judged, ["a", "b", "c"])                # judged in order, as before
        self.started.clear()
        self.judged.clear()
        got, one_by_one = self._run(names, delays, keep={"c"}, ahead=1)
        self.assertEqual(got.url, "https://img.example/c.jpg")
        self.assertEqual(self.judged, ["a", "b", "c"])
        self.assertGreaterEqual(one_by_one, 0.9)
        self.assertLess(together, 0.75)

    def test_the_first_in_order_wins_even_when_a_later_one_arrives_first(self):
        got, _ = self._run(("slow", "fast"), {"slow": 0.4, "fast": 0.0}, keep={"slow", "fast"}, ahead=3)
        self.assertEqual(got.url, "https://img.example/slow.jpg")
        self.assertEqual(self.judged, ["slow"])

    def test_a_search_that_keeps_its_first_picture_leaves_few_downloads_behind(self):
        names = ("a", "b", "c", "d", "e", "f")
        got, _ = self._run(names, {n: 0.1 for n in names}, keep={"a"}, ahead=3)
        self.assertEqual(got.url, "https://img.example/a.jpg")
        media.drain_pools(5.0)
        self.assertLessEqual(len(self.started), 3)                    # a, and at most PICTURE_PREFETCH - 1 more
        self.assertEqual(self.started[0], "a")

    def test_one_at_a_time_when_switched_off(self):
        names = ("a", "b", "c")
        got, _ = self._run(names, {n: 0.0 for n in names}, keep={"a"}, ahead=0)
        self.assertEqual(got.url, "https://img.example/a.jpg")
        self.assertEqual(self.started, ["a"])

    def test_a_picture_another_scene_took_while_it_downloaded_is_passed_over(self):
        used = set()
        cands = self._cands("a", "b")

        def download(c, query, work):
            if c.url.endswith("/a.jpg"):
                used.add(c.identity)                                     # another scene placed it meanwhile
            c.local_path = self.file
            return c
        with mock.patch.object(media.config, "PICTURE_PREFETCH", 3), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_vision_gate", return_value=(True, None)):
            got = media._pick_unused(cands, used, "q", self.work, "the lake shore")
        self.assertEqual(got.url, "https://img.example/b.jpg")


class WhereTheTimeGoes(unittest.TestCase):
    """media.stage_seconds(): thread-seconds per stage, in the job result (meta.sourcing, a re-cut's result)."""

    def setUp(self):
        with media._CACHE_LOCK:
            media._STAGES.clear()
        self.work = tempfile.mkdtemp(prefix="stages_")
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_searches_downloads_checks_and_gates_are_timed(self):
        from src.storage import StorageError
        cands = [MediaAsset(kind="image", source="web_image", url=f"https://img.example/{n}.jpg", query="q")
                 for n in ("gone", "photo")]
        good = photo(os.path.join(self.work, "p.jpg"))

        def fetch(url, dest, page_url="", thumbnail=""):
            if "gone" in url:
                raise StorageError("picture download failed: 404 Client Error")
            return good
        with mock.patch.object(media, "search_web_images", return_value=cands), \
                mock.patch.object(media._imagefix, "fetch", side_effect=fetch), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_judge_gate", return_value=(True, None)), \
                mock.patch.object(media, "watermark_reason", return_value=""):
            found = media._cached_search(media.search_web_images, "lake shore q1", key="search_web_images")
            got = media._pick_unused(found, set(), "q", self.work, "the lake shore")
        self.assertEqual(got.url, "https://img.example/photo.jpg")
        stages = media.stage_seconds()
        for name in ("search:search_web_images", "download:picture_failed", "download:picture",
                     "checks:picture", "gate:picture"):
            self.assertEqual(stages[name]["n"], 1, (name, stages))
            self.assertGreaterEqual(stages[name]["seconds"], 0.0)

    def test_a_new_job_starts_from_nothing(self):
        media._stage("download:picture", 1.5)
        media._stage("download:picture", 0.5)
        self.assertEqual(media.stage_seconds()["download:picture"], {"n": 2, "seconds": 2.0, "mean": 1.0})
        media.reset_cache()
        self.assertEqual(media.stage_seconds(), {})


if __name__ == "__main__":
    unittest.main()
