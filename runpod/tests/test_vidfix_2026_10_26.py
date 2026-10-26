"""The Hoover Dam video fixes (2026-10-26, docs/vidfix-2026-10-26.md): clips, stills, names, text."""
import unittest
from unittest import mock

from src import config, media


class SlopChannelMemory(unittest.TestCase):
    def setUp(self):
        media.reset_cache()

    def test_ai_upload_strikes_the_channel_at_once(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            self.assertEqual(media.note_slop_channel("Disaster Daily AI", "an AI-generated or painted picture (art 0.81)"), 2)
            self.assertTrue(media.slop_channel("disaster daily ai "))
            self.assertEqual(media.SLOP_CHANNEL_STATS["struck"], 1)

    def test_a_slideshow_needs_two(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            media.note_slop_channel("Flood Slides", "a slideshow of stills")
            self.assertFalse(media.slop_channel("Flood Slides"))
            media.note_slop_channel("Flood Slides", "a still with a slow pan or zoom")
            self.assertTrue(media.slop_channel("Flood Slides"))

    def test_the_judge_saying_ai_counts(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            media.note_slop_channel("X", "", {"ai_generated": True})
            self.assertTrue(media.slop_channel("X"))

    def test_other_reasons_and_news_channels_never_strike(self):
        with mock.patch.object(media, "_story_channels", lambda: ["KTNV Channel 13 Las Vegas"]):
            for _ in range(3):
                media.note_slop_channel("KTNV Channel 13 Las Vegas", "a slideshow of stills")
                media.note_slop_channel("Some Vlogger", "burned-in text or UI")
                media.note_slop_channel("Other", "", {"has_text_or_watermark": True})
            self.assertFalse(media.slop_channel("KTNV Channel 13 Las Vegas"))
            self.assertFalse(media.slop_channel("Some Vlogger"))
            self.assertFalse(media.slop_channel("Other"))

    def test_off_switch_and_job_reset(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            media.note_slop_channel("A", "an AI-generated or painted picture")
            media.reset_cache()
            self.assertFalse(media.slop_channel("A"))
            with mock.patch.object(config, "SLOP_CHANNEL_MEMORY", False):
                media.note_slop_channel("A", "an AI-generated or painted picture")
                self.assertFalse(media.slop_channel("A"))


if __name__ == "__main__":
    unittest.main()
