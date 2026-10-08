"""Pass 1 keeps what a line still running at its close already holds (2026-10-08).

The benchmark of 2026-10-08 (seven one-minute openings, f5c17ee): 6, 7 and 12 of 14, 13 and 15 lines were
still running when pass 1 closed at 540 s - many of them hook lines whose first passing clip was in hand
while the second look (stronger_hook) ran on. Pass 1 stopped waiting at its close and every one of those
lines came back empty, to the slower, unjudged passes after it. Now the box closes, the lines stop at their
next network call, and their answers are taken for PASS1_COLLECT_SECONDS.
"""
import time
import unittest
from unittest import mock

from src import config, media, ytdlp
from src.media import MediaAsset

FOUND = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=abcdefghijk&t=5",
                   relevance_score=0.85, judged_by="frames")


def _fake(query, seconds, work_dir, **kw):
    if query == "quick":
        return MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=quickquick1&t=1",
                          relevance_score=0.8, judged_by="frames")
    # A slow line: it holds a clip already and searches on until its time is up - it sees the close at its
    # next network call, a moment after the close (an in-flight download or verdict) - then hands the clip back.
    t0 = time.time()
    while not ytdlp.stopped() and time.time() - t0 < 20:
        time.sleep(0.05)
    time.sleep(0.4)
    return FOUND


class CollectAtTheClose(unittest.TestCase):
    JOBS = [{"index": 0, "query": "quick", "seconds": 4.0, "context": "a"},
            {"index": 1, "query": "slow", "seconds": 4.0, "context": "b"}]

    def _run(self, collect: float):
        # (No job deadline left over from another test: past it, every line would stop - and answer - at once.)
        with mock.patch.object(ytdlp, "DEADLINE", [0.0]), \
                mock.patch.object(config, "PASS1_COLLECT_SECONDS", collect), \
                mock.patch.object(config, "PASS1_BUDGET_SECONDS", 0.5), \
                mock.patch.object(config, "REPLACE_BUDGET_SECONDS", 0), \
                mock.patch.object(config, "FRESH_MOMENTS", False), \
                mock.patch.object(media, "source_for_segment", side_effect=_fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", return_value=None):
            media.reset_cache()
            out = media.source_many([dict(j) for j in self.JOBS], "/tmp", workers=2, pass1_per_scene=0.1)
        return out, dict(media.LAST_STATS)

    def test_a_line_running_at_the_close_hands_back_its_clip(self):
        out, stats = self._run(5.0)
        self.assertIsNotNone(out[0])
        self.assertIs(out[1], FOUND)
        self.assertEqual(stats.get("pass1_collected"), 1)
        self.assertEqual(stats.get("pass1_collected_kept"), 1)
        self.assertNotIn("pass1_stragglers", stats)

    def test_off_the_line_is_given_up_on_as_before(self):
        out, stats = self._run(0.0)
        self.assertIsNotNone(out[0])
        self.assertIsNone(out[1])
        self.assertEqual(stats.get("pass1_stragglers"), 1)
        self.assertNotIn("pass1_collected", stats)


if __name__ == "__main__":
    unittest.main()
