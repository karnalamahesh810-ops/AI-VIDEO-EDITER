import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from src import config, fanout, library, media, ytdlp


class Deadline(unittest.TestCase):
    def tearDown(self):
        ytdlp.set_deadline(0.0)

    def test_budget_scales_with_scenes_and_is_capped(self):
        with mock.patch.object(config, "SOURCE_BUDGET_BASE_SECONDS", 180), \
                mock.patch.object(config, "SOURCE_BUDGET_PER_SCENE", 2), \
                mock.patch.object(config, "SOURCE_BUDGET_MAX_SECONDS", 900):
            self.assertEqual(fanout.source_budget(54), 288)       # a 3-minute narration: under 5 minutes
            self.assertEqual(fanout.source_budget(1000), 900)

    def test_past_the_deadline_nothing_downloads_or_searches(self):
        ytdlp.set_deadline(time.time() - 1)
        self.assertTrue(ytdlp.past_deadline())
        with mock.patch.object(ytdlp.subprocess, "run", side_effect=AssertionError("must not run yt-dlp")):
            self.assertEqual(ytdlp._yt_fetch("abcdefghijk", tempfile.mkdtemp(), 10, 5), "")
            self.assertEqual(media._yt_fetch_retry("abcdefghijk", tempfile.mkdtemp(), 10, 5), "")
            self.assertEqual(ytdlp._yt_info("abcdefghijk")[0], {})
        with mock.patch.object(media, "youtube_clip", side_effect=AssertionError("must not search")):
            self.assertIsNone(media.source_for_segment("Lake Mead", 5.0, tempfile.mkdtemp()))

    def test_no_deadline_means_no_limit(self):
        ytdlp.set_deadline(0.0)
        self.assertFalse(ytdlp.past_deadline())

    def test_a_part_keeps_twenty_seconds_to_upload(self):
        seen = {}

        def source_many(jobs, work, seqs, exclude):
            seen["deadline"] = ytdlp.DEADLINE[0]
            return [None for _ in jobs]
        at = time.time() + 300
        fanout.run_part({"jobs": [{"index": 3}], "project_id": "p", "parent_job_id": "j", "deadline_at": at},
                        tempfile.mkdtemp(), source_many, lambda b: None)
        self.assertAlmostEqual(seen["deadline"], at - 20.0, places=3)

    def test_ffmpeg_errors_reach_stderr(self):
        args = ytdlp._yt_network_args("http://u:p@h:1")
        self.assertIn("ffmpeg_i:-loglevel error -http_proxy http://u:p@h:1", args)


class LibrarySaveIsTimeBoxed(unittest.TestCase):
    def test_slow_uploads_are_skipped_after_the_box(self):
        d = tempfile.mkdtemp()
        scenes = []
        for i in range(3):
            p = os.path.join(d, f"{i}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            scenes.append({"id": f"s{i}", "durationInFrames": 150,
                           "media": {"type": "video", "source": "youtube", "url": p},
                           "semanticMetadata": {"assetId": f"yt:vid{i}@1", "subject": "Lake Mead", "relevanceScore": 0.9}})
        release = threading.Event()

        def upload(local, bucket, obj, pid, jid, read_ttl=60):
            if "vid1" in obj:
                release.wait(5)                 # one upload hangs past the box
            return "u"
        lib = library.Library("p", "j")
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(config, "LIBRARY_SAVE_SECONDS", 0.5), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_upload", side_effect=upload):
            t0 = time.time()
            added = lib.record_from_doc({"fps": 30, "scenes": scenes})
            took = time.time() - t0
        release.set()
        self.assertLess(took, 3.0)
        self.assertEqual(added, 2)
        self.assertEqual(sorted(e["id"] for e in lib.entries), ["yt:vid0@1", "yt:vid2@1"])


if __name__ == "__main__":
    unittest.main()
