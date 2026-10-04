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


if __name__ == "__main__":
    unittest.main()
