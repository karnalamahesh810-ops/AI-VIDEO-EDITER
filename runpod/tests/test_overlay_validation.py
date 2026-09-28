import unittest

from src import timeline
from tests.test_pipeline import build_doc


class OverlayValidation(unittest.TestCase):
    """A finished plan never fails on one graphic."""

    def _doc(self, overlays):
        doc = build_doc(n=4, seconds=6.0)
        doc["overlays"] = overlays
        return doc

    def test_the_intro_collage_borrows_the_story_pictures(self):
        doc = self._doc([{"type": "photo-card", "variant": "collage", "template": "PHOTO_COLLAGE_V1",
                          "startFrame": 0, "durationInFrames": 60}])
        timeline.validate(doc, require_media=False)                 # no ValueError
        self.assertEqual(timeline.drop_invalid_overlays(doc), 0)

    def test_a_photo_card_without_a_picture_is_dropped_not_fatal(self):
        doc = self._doc([{"type": "photo-card", "variant": "frame", "startFrame": 0, "durationInFrames": 60},
                         {"type": "title", "text": "Glen Canyon", "startFrame": 0, "durationInFrames": 60}])
        with self.assertRaises(ValueError):
            timeline.validate(doc, require_media=False)
        self.assertEqual(timeline.drop_invalid_overlays(doc), 1)
        self.assertEqual([o["type"] for o in doc["overlays"]], ["title"])
        self.assertTrue(any("graphic" in w for w in doc["meta"]["warnings"]))
        timeline.validate(doc, require_media=False)

    def test_stock_clips_follow_the_jobs_own_setting(self):
        doc = self._doc([])
        doc["scenes"][0]["media"]["source"] = "pexels"
        with self.assertRaises(ValueError):
            timeline.validate(doc, require_media=False, allow_stock=False)
        timeline.validate(doc, require_media=False, allow_stock=True)


if __name__ == "__main__":
    unittest.main()
