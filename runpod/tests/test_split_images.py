import io
import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

import handler
from src import config, media
from src.media import MediaAsset


def jpeg_bytes(w=800, h=600):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


def doc_with(items):
    return {"fps": 30, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 150, "text": "x",
                                   "media": {"type": "video", "url": "u"}, "semanticMetadata": {"subject": "Lake Mead"}}],
            "overlays": [{"type": "label-boxes", "items": items, "startFrame": 10, "durationInFrames": 90}]}


class SplitImages(unittest.TestCase):
    def test_a_two_label_contrast_becomes_a_split_of_two_photos(self):
        doc = doc_with([{"label": "Solid ground"}, {"label": "Submerged mud"}])
        queries = []

        def search(q, limit=6):
            queries.append(q)
            return [MediaAsset(kind="image", source="web", url=f"https://img/{len(queries)}.jpg")]
        resp = mock.Mock(status_code=200, content=jpeg_bytes())
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", side_effect=search), \
                mock.patch("requests.get", return_value=resp):
            n = handler._bind_split_images(doc, tempfile.mkdtemp(), lambda local, name: f"https://store/{name}")
        self.assertEqual(n, 1)
        ov = doc["overlays"][0]
        self.assertEqual(ov["type"], "split")
        self.assertEqual([m["url"] for m in ov["media"]], ["https://store/split/000_0.jpg", "https://store/split/000_1.jpg"])
        self.assertEqual([it["label"] for it in ov["items"]], ["Solid ground", "Submerged mud"])
        self.assertEqual(sorted(queries), ["Lake Mead Solid ground", "Lake Mead Submerged mud"])

    def test_one_photo_missing_keeps_the_labels(self):
        doc = doc_with([{"label": "Solid ground"}, {"label": "Submerged mud"}])

        def search(q, limit=6):
            return [MediaAsset(kind="image", source="web", url="https://img/a.jpg")] if "Solid" in q else []
        resp = mock.Mock(status_code=200, content=jpeg_bytes())
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", side_effect=search), \
                mock.patch("requests.get", return_value=resp):
            self.assertEqual(handler._bind_split_images(doc, tempfile.mkdtemp(), lambda l, n: "u"), 0)
        self.assertEqual(doc["overlays"][0]["type"], "label-boxes")

    def test_small_or_broken_images_are_skipped(self):
        doc = doc_with([{"label": "A"}, {"label": "B"}])
        resp_small = mock.Mock(status_code=200, content=jpeg_bytes(200, 150))
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images",
                                  return_value=[MediaAsset(kind="image", source="web", url="https://img/x.jpg")]), \
                mock.patch("requests.get", return_value=resp_small):
            self.assertEqual(handler._bind_split_images(doc, tempfile.mkdtemp(), lambda l, n: "u"), 0)

    def test_single_labels_and_other_overlays_are_left_alone(self):
        doc = doc_with([{"label": "Only one"}])
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", side_effect=AssertionError("no search")):
            self.assertEqual(handler._bind_split_images(doc, tempfile.mkdtemp(), lambda l, n: "u"), 0)


if __name__ == "__main__":
    unittest.main()
