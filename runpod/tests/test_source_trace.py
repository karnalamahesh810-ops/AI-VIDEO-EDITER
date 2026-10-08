"""Per-line sourcing traces for a build (config.SOURCE_TRACE, 2026-10-08).

The benchmark asked "did the one-machine time budget starve lines?" and a build kept no record of any line:
only the reclip action traced its targets (media._TRACE). With SOURCE_TRACE on, every pass a line goes through
- pass 1, the hook's second look, pass 2's tries, the AI recheck - is kept in meta.sourcing.traces with when
it started, how long it took, whether its time ran out, what it ended with, and its trace rows. Off (the
default), nothing is kept.
"""
import unittest
from unittest import mock

from src import config, media
from src.media import MediaAsset


def _fake(query, seconds, work_dir, **kw):
    media._trace(step="search", query=query, candidates=3)
    if "dam" in query.lower():
        media._trace(step="judge", video="abc", keep=True, score=0.82)
        return MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=abcdefghijk&t=5",
                          attribution="YouTube: Hoover Dam", relevance_score=0.82, judged_by="frames")
    media._trace(step="judge", video="xyz", keep=False, score=0.4)
    return None


class SourceTrace(unittest.TestCase):
    JOBS = [{"index": 0, "query": "Hoover Dam turbines", "seconds": 4.0, "context": "At Hoover Dam, turbines",
             "start": 0.0},
            {"index": 1, "query": "Imperial Valley lettuce", "seconds": 4.0, "context": "farms in the valley",
             "start": 4.0}]

    def _run(self, on: bool):
        with mock.patch.object(config, "SOURCE_TRACE", on), \
                mock.patch.object(media, "source_for_segment", side_effect=_fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", return_value=None), \
                mock.patch.object(config, "FRESH_MOMENTS", False):
            media.reset_cache()
            out = media.source_many([dict(j) for j in self.JOBS], "/tmp", workers=2)
        return out, dict(media.LAST_STATS)

    def test_each_line_keeps_its_passes_and_rows(self):
        out, stats = self._run(True)
        self.assertIsNotNone(out[0])
        traces = stats["traces"]
        self.assertEqual(set(traces), {"0", "1"})
        found = traces["0"]
        self.assertEqual(found["query"], "Hoover Dam turbines")
        self.assertEqual(found["line"], "At Hoover Dam, turbines")
        first = found["passes"][0]
        self.assertEqual(first["pass"], "pass1")
        self.assertEqual(first["got"], "video:youtube")
        self.assertEqual(first["judged"], "frames")
        self.assertAlmostEqual(first["score"], 0.82)
        self.assertGreaterEqual(first["seconds"], 0.0)
        self.assertIn("stopped", first)
        self.assertEqual([r["step"] for r in first["rows"]], ["search", "judge"])
        # The empty line went on to pass 2's tries: each its own entry, none found.
        missing = traces["1"]["passes"]
        self.assertEqual(missing[0]["pass"], "pass1")
        self.assertEqual(missing[0]["got"], "")
        self.assertTrue(any(p["pass"].startswith("pass2.") for p in missing[1:]))

    def test_off_keeps_nothing(self):
        out, stats = self._run(False)
        self.assertIsNotNone(out[0])
        self.assertNotIn("traces", stats)
        self.assertEqual(media.LINE_TRACES, {})

    def test_a_job_can_turn_it_on(self):
        import handler
        self.assertIn("SOURCE_TRACE", handler.CONFIG_OVERRIDABLE)
        before = handler._apply_config({"SOURCE_TRACE": "1"})
        try:
            self.assertTrue(config.SOURCE_TRACE)
        finally:
            handler._restore_config(before)
        self.assertFalse(config.SOURCE_TRACE)


if __name__ == "__main__":
    unittest.main()
