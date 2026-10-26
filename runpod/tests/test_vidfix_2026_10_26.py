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


def _job(i, subject_type="event", loc="Lake Mead", start=None, visual="footage", tc="oct 2026"):
    return {"index": i, "seconds": 5.0, "visual_type": visual, "subject_type": subject_type,
            "subject": f"{loc} flooding", "start": i * 5.0 if start is None else start,
            "scene_intent": {"locations": [loc], "entities": [], "time_context": tc}}


def _clip(vid, start=60.0):
    return media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                            local_path=f"/w/{vid}.mp4", duration=5.5, attribution="YouTube: x",
                            moment={"start": start})


def _still(n):
    return media.MediaAsset(kind="image", source="web_image", url=f"https://e.com/{n}.jpg", local_path=f"/w/{n}.jpg")


class StillsToChains(unittest.TestCase):
    ON = dict(CLIPS_FIRST=True, CLIPS_FIRST_STILLS=True, PREFER_GENERATED_IMAGES=False, STILLS_TO_CLIPS=True,
              PERSON_CLIPS_FIRST=True, FILL_MAX_MOMENTS_PER_VIDEO=4, MAX_MOMENTS_PER_VIDEO=3)

    def _run(self, jobs, results, spare=None):
        fetched = []

        def fake_fetch(vid, out_dir, at, need, title="", least=None):
            fetched.append((vid, round(at, 1)))
            return f"/w/{vid}_{int(at)}.mp4", True, 0
        with mock.patch.multiple(config, **self.ON), \
                mock.patch.object(media, "fetch_clean_clip", fake_fetch), \
                mock.patch.object(media, "_asset_ok", lambda a: (True, "")), \
                mock.patch.object(media, "motion_rejects", lambda p: ""), \
                mock.patch.object(media, "slop_reason", lambda p, l="": ""), \
                mock.patch.object(media, "youtube_only", lambda: False), \
                mock.patch.object(media.ledger, "moment_used", lambda *a: False), \
                mock.patch("src.gapfill._from_spare", spare or (lambda *a, **k: None)):
            out = media.stills_to_chains(jobs, results, work_dir="/w", seconds=60)
        return out, fetched

    def test_a_run_of_stills_gets_clips_at_both_ends_and_no_still_follows_a_still(self):
        jobs = [_job(i) for i in range(5)]
        results = [_clip("AAAAAAAAAAA"), _still(1), _still(2), _still(3), _clip("BBBBBBBBBBB", 100.0)]
        out, fetched = self._run(jobs, results)
        self.assertEqual((out["forward"], out["backward"]), (1, 1))
        self.assertEqual([r.kind for r in results], ["video", "video", "image", "video", "video"])
        self.assertEqual(fetched[0], ("AAAAAAAAAAA", round(60 + 5.5 + media.CHAIN_SKIP_SECONDS, 1)))
        self.assertLess(fetched[1][1], 100.0)                        # the moment before the next clip
        self.assertTrue(results[1].moment["chain"] and results[1].judged_by == "chain")

    def test_people_documents_the_past_and_unrelated_lines_keep_their_picture(self):
        jobs = [_job(0), _job(1, "person"), _job(2), _job(3, "document"), _job(4),
                _job(5, tc="1936"), _job(6)]
        jobs[2]["scene_intent"]["locations"] = ["Flaming Gorge"]     # names nothing the clip's line names
        jobs[2]["subject"] = "Flaming Gorge releases"
        results = [_clip("AAAAAAAAAAA"), _still(1), _still(2), _still(3), _clip("CCCCCCCCCCC"), _still(5),
                   _clip("DDDDDDDDDDD")]
        out, _f = self._run(jobs, results)
        self.assertEqual([r.kind for r in results][1:4], ["image", "image", "image"])
        self.assertEqual(results[5].kind, "image")                  # 1936: not a modern clip
        self.assertEqual(out["eligible"], 1)

    def test_a_still_after_a_still_takes_a_spare_clip(self):
        jobs = [_job(i) for i in range(4)]
        results = [_still(0), _still(1), _still(2), _still(3)]
        spare = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=SSSSSSSSSSS",
                                 local_path="/w/s.mp4")
        calls = []

        def fake_spare(job, used, work, stop, kind="video"):
            calls.append(job["index"])
            return spare if job["index"] == 1 else None
        out, _f = self._run(jobs, results, fake_spare)
        self.assertEqual(out["spare"], 1)
        self.assertEqual(results[1].kind, "video")
        self.assertIn(1, calls)

    def test_off_switch(self):
        jobs = [_job(0), _job(1)]
        results = [_clip("AAAAAAAAAAA"), _still(1)]
        with mock.patch.object(config, "STILLS_TO_CLIPS", False):
            out = media.stills_to_chains(jobs, results, work_dir="/w")
        self.assertEqual(results[1].kind, "image")
        self.assertEqual(out["eligible"], 0)


if __name__ == "__main__":
    unittest.main()
