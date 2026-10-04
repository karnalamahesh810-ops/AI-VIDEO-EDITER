import os
import pathlib
import tempfile
import unittest
from unittest import mock

from src import config, media
from src.media import MediaAsset


def clip(vid, start_ms, work):
    path = os.path.join(work, f"yt_{vid}_{start_ms}_5000_abcdef0123.mp4")
    pathlib.Path(path).write_bytes(b"x")
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}", local_path=path,
                      relevance_score=0.9)


class FreshMoments(unittest.TestCase):
    def test_an_empty_scene_gets_another_moment_of_a_same_subject_video(self):
        work = tempfile.mkdtemp()
        jobs = [{"index": 0, "subject": "Lake Mead", "query": "lake mead", "seconds": 5},
                {"index": 1, "subject": "Lake Mead", "query": "lake mead drone", "seconds": 5},
                {"index": 2, "subject": "Jane Doe", "subject_type": "person", "query": "jane doe", "seconds": 5}]
        results = [clip("EWQT3VwOgvA", 40000, work), None, None]
        fetched = []

        def fake_fetch(vid, out, at, need, title=""):
            fetched.append((vid, at))
            p = os.path.join(out, f"yt_{vid}_{int(at * 1000)}_{int(need * 1000)}_fresh.mp4")
            pathlib.Path(p).write_bytes(b"x")
            return p
        with mock.patch.object(media, "_yt_fetch_retry", side_effect=fake_fetch), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media.vision, "enabled", return_value=False):
            n = media.fresh_moments(jobs, results, work)
        self.assertEqual(n, 1)
        self.assertIsNone(results[2])                       # never a person
        got = results[1]
        # 40 s + 30 s (never under FALLBACK_MOMENT_GAP_SECONDS from the donor) -> bucket 7, not the donor's 4
        self.assertEqual(got.moment_key, "yt:EWQT3VwOgvA@7")
        self.assertNotEqual(got.identity, results[0].identity)
        self.assertTrue(got.review_required)
        # The section comes with a margin and is cut clean (filters.tidy_clip: never opening on the end
        # of the shot before - the owner's Glen Canyon test, 2026-10-05); the moment is still 70 s.
        self.assertEqual(fetched, [("EWQT3VwOgvA", 70.0 - config.CUT_MARGIN_SECONDS)])
        self.assertEqual(got.moment["start"], 70.0)

    def test_a_failed_or_rejected_moment_tries_the_next_offset(self):
        work = tempfile.mkdtemp()
        jobs = [{"index": 0, "subject": "Hoover Dam", "seconds": 4}, {"index": 1, "subject": "Hoover Dam", "seconds": 4}]
        results = [clip("abcdefghijk", 100000, work), None]
        calls = {"n": 0}

        def fake_fetch(vid, out, at, need, title=""):
            calls["n"] += 1
            if calls["n"] == 1:
                return ""                                   # 125 s failed to download
            p = os.path.join(out, f"yt_{vid}_{int(at * 1000)}_4000_x.mp4")
            pathlib.Path(p).write_bytes(b"x")
            return p
        with mock.patch.object(media, "_yt_fetch_retry", side_effect=fake_fetch), \
                mock.patch.object(media, "_asset_ok", side_effect=[(False, "blurry"), (True, "")]), \
                mock.patch.object(media.vision, "enabled", return_value=False):
            self.assertEqual(media.fresh_moments(jobs, results, work), 1)
        self.assertEqual(results[1].moment["start"], 145.0)  # +25 failed, -25 blurry, +45 kept

    def test_off_or_nothing_to_draw_from_does_nothing(self):
        jobs = [{"index": 0, "subject": "Lake Mead", "seconds": 5}]
        self.assertEqual(media.fresh_moments(jobs, [None], ""), 0)
        self.assertEqual(media.fresh_moments(jobs, [None], tempfile.mkdtemp()), 0)


if __name__ == "__main__":
    unittest.main()
