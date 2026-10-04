"""Fan-out parts say where their time went (2026-10-05).

A source_part child returned its clips and its cost units, never where its time went:
whether a video needs ten machines or five (the cost plan's machine-size lever) could
not be read from a real job. A part now returns its sourcing threads' seconds per stage
and its wall seconds finding and handing over; the parent sums them over every part
into meta.sourcing.fanout.children, with the rest of each part's billed seconds
(start-up: the YouTube pre-check, the ledger) as otherSeconds.
"""
import tempfile
import unittest
from unittest import mock

from src import config, fanout, media


class PartsSayWhereTheirTimeWent(unittest.TestCase):
    def setUp(self):
        media.reset_cache()
        self.addCleanup(media.reset_cache)

    def test_a_part_returns_its_stage_seconds_and_wall_seconds(self):
        def source_many(jobs, work, seqs, exclude):
            media._stage("download:youtube", 12.5)
            media._stage("gate:clip", 3.0)
            return [None] * len(jobs)
        out = fanout.run_part({"project_id": "p", "parent_job_id": "j", "jobs": [{"index": 7, "query": "q"}]},
                              tempfile.gettempdir(), source_many, lambda brief: None)
        self.assertEqual(out["stageSeconds"]["download:youtube"], {"n": 1, "seconds": 12.5, "mean": 12.5})
        self.assertIn("gate:clip", out["stageSeconds"])
        self.assertEqual(set(out["partSeconds"]), {"finding", "uploading"})
        self.assertEqual(out["asked"], 1)

    def test_the_parent_sums_its_parts(self):
        kids = fanout.ChildTimes()
        self.assertIsNone(kids.summary())
        kids.note({"elapsed": 600.0, "partSeconds": {"finding": 480.0, "uploading": 40.0},
                   "stageSeconds": {"download:youtube": {"n": 10, "seconds": 120.0},
                                    "gate:clip": {"n": 8, "seconds": 40.0}}})
        kids.note({"elapsed": 500.0, "partSeconds": {"finding": 430.0, "uploading": 30.0},
                   "stageSeconds": {"download:youtube": {"n": 6, "seconds": 60.0}}})
        kids.note({"elapsed": "n/a", "stageSeconds": {"bad": "row"}})          # an old image's answer
        kids.note(None)
        s = kids.summary()
        self.assertEqual((s["parts"], s["seconds"], s["longestSeconds"]), (3, 1100.0, 600.0))
        self.assertEqual((s["findingSeconds"], s["uploadingSeconds"], s["otherSeconds"]), (910.0, 70.0, 120.0))
        self.assertEqual(s["stageSeconds"]["download:youtube"], {"n": 16, "seconds": 180.0, "mean": 11.25})
        self.assertNotIn("bad", s["stageSeconds"])

    def test_the_summary_reaches_meta_sourcing_fanout(self):
        from src import ytdlp
        self.addCleanup(ytdlp.set_deadline, ytdlp.DEADLINE[0])   # source() sets the job's deadline
        jobs = [{"index": i, "query": f"line {i}", "seconds": 4.0} for i in range(4)]
        child_out = {"assets": {}, "elapsed": 300.0, "partSeconds": {"finding": 250.0, "uploading": 10.0},
                     "stageSeconds": {"search:ytsearch": {"n": 4, "seconds": 20.0}}}

        class Units:
            def __init__(self, units, *, payload, local, accept, progress, report, deadline):
                self.units, self.local, self.accept = units, local, accept
                self.stolen = 0

            def run(self, label):
                self.accept(self.units[0], self.local(self.units[0]), False)
                for u in self.units[1:]:
                    self.accept(u, dict(child_out), True)
                return []
        with mock.patch.object(fanout, "_Units", Units), \
                mock.patch.object(config, "FANOUT_PARTS", 2), \
                mock.patch.object(config, "FANOUT_REFILL_MIN", 99):
            fanout.source(jobs, [], {}, parent_job_id="j", project_id="p", bucket="b", work=tempfile.gettempdir(),
                          flags={}, report=lambda *a, **k: None,
                          local=lambda js, ex: [None] * len(js))
        kids = media.LAST_STATS["fanout"]["children"]
        self.assertEqual(kids["parts"], 1)
        self.assertEqual(kids["stageSeconds"]["search:ytsearch"]["seconds"], 20.0)
        self.assertEqual(kids["otherSeconds"], 40.0)


if __name__ == "__main__":
    unittest.main()
