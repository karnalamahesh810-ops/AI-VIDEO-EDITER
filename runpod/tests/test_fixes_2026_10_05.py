"""Two fixes verified on 2026-10-05 (each reproduced first, then fixed):

- A document line's scan was dropped in pass 2: the check of every scene's asset ran
  outside the line's context, so the scan - the right shot for a line about a file or
  a letter - read as "a page of text, not a photo"; three paid searches then brought
  scans turned down the same way and the line ended empty.
- The subject pools' spare moments outlived their job: on a reused serverless worker the
  next job (a render's quality gate, a fan-out parent whose parts pool for it) could put
  another video's footage on a line naming no place, unjudged.

And JUDGE_MEMORY is on by default (the owner, after the cost plan's simulation).
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import handler
from src import config, gapfill, media, pools
from src.media import MediaAsset
from tests.test_sourcing_speed import slide


class DocumentScansKept(unittest.TestCase):
    def setUp(self):
        media.reset_cache()
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.scan = slide(os.path.join(self.d, "scan.jpg"))
        self.calls = []

    def _source(self, jobs, found):
        def sfs(query, seconds, work_dir, **kw):
            self.calls.append(kw.get("subject_type"))
            return MediaAsset(kind="image", source="web_image", url=f"https://img.example/{len(self.calls)}.jpg",
                              local_path=found, query=query)
        with mock.patch.object(media, "source_for_segment", side_effect=sfs), \
                mock.patch.object(config, "FRESH_MOMENTS", False):
            return media.source_many(jobs, self.d, workers=2, rescue=None)

    def _job(self, i, subject_type):
        return {"index": i, "query": f"line {i}", "seconds": 4.0, "visual_type": "image",
                "subject_type": subject_type, "intent": f"line {i}", "context": ""}

    def test_a_document_lines_scan_survives_pass_2(self):
        out = self._source([self._job(0, "document")], self.scan)
        self.assertIsNotNone(out[0])
        self.assertEqual(len(self.calls), 1)               # no paid re-search for a shot it already had

    def test_also_when_several_scenes_are_checked_at_once(self):
        out = self._source([self._job(0, "document"), self._job(1, "document")], self.scan)
        self.assertTrue(all(out))
        self.assertEqual(len(self.calls), 2)

    def test_a_page_of_text_is_still_turned_down_for_a_photo_line(self):
        out = self._source([self._job(0, "place")], self.scan)
        self.assertIsNone(out[0])                          # 1 find + 3 replacements, all turned down
        self.assertEqual(len(self.calls), 4)

    def test_the_lines_context_is_put_back(self):
        token = media._SUBJECT_TYPE.set("person")
        try:
            pic = MediaAsset(kind="image", source="web_image", url="u", local_path=self.scan)
            self.assertEqual(media._asset_ok_for({"subject_type": "document"}, pic), (True, ""))
            self.assertEqual(media._SUBJECT_TYPE.get(), "person")
            self.assertFalse(media._asset_ok_for({"subject_type": "place"}, pic)[0])
            self.assertFalse(media._asset_ok_for(None, pic)[0])
        finally:
            media._SUBJECT_TYPE.reset(token)

    def test_the_fallback_ladders_picture_keeps_a_scan_for_a_document_line(self):
        import time
        from src import imagefix, ledger, slop

        def ladder(subject_type):
            cand = MediaAsset(kind="image", source="web_image", url=f"https://img.example/{subject_type}.jpg",
                              attribution="the 1962 memo")
            job = {"index": 0, "query": "1962 memo", "intent": "the 1962 memo", "subject_type": subject_type,
                   "visual_type": "image", "start": 0.0, "context": ""}

            def download(c, query, work):
                c.local_path = self.scan
                return c
            with mock.patch.object(media, "_cached_search", return_value=[cand]), \
                    mock.patch.object(media, "_download", side_effect=download), \
                    mock.patch.object(media, "_photo_seen_before", return_value=False), \
                    mock.patch.object(media, "judge_clip", return_value=(True, None)) as judged:
                got = gapfill._still_for(job, 0, "1962 memo", "the 1962 memo", gapfill.Used(), self.d,
                                         time.time() + 30, imagefix, ledger, media, slop)
            return got, judged.call_count
        got, judged = ladder("document")
        self.assertIsNotNone(got)
        self.assertEqual(judged, 1)
        got, judged = ladder("place")                      # a photo line still never gets a page of text
        self.assertIsNone(got)
        self.assertEqual(judged, 0)


class ReserveIsPerJob(unittest.TestCase):
    def tearDown(self):
        pools.reset()

    def test_the_next_job_never_draws_the_last_jobs_spare_moments(self):
        pools._RESERVE[:] = [("lake powell", {"id": "LPspare0001", "title": "Lake Powell drone"},
                              {"start": 42.0, "score": 0.9, "description": "houseboats"})]
        pools._RESERVE_META["lake powell"] = {"name": "Lake Powell", "seconds": 7.0}
        out = handler.handler({"id": "next-job", "input": {"action": "no_such_action"}})
        self.assertFalse(out["ok"])
        self.assertIsNone(pools.take_spare({"index": 0, "subject": "Mount Rainier glaciers"}, ok=lambda c, m: True))
        self.assertEqual(pools.spare_moments(), [])

    def test_within_a_job_the_spares_stay_for_its_own_lines(self):
        pools.reset()
        pools.put_back(("lake powell", {"id": "LPspare0001", "title": "Lake Powell drone"},
                        {"start": 42.0, "score": 0.9, "description": "houseboats"}))
        got = pools.take_spare({"index": 3, "subject": "Lake Powell"}, ok=lambda c, m: True)
        self.assertEqual(got[1]["id"], "LPspare0001")


class JudgeMemoryIsOn(unittest.TestCase):
    def test_on_by_default(self):
        self.assertTrue(config.JUDGE_MEMORY or "JUDGE_MEMORY" in os.environ)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JUDGE_MEMORY", None)
            self.assertTrue(config._flag("JUDGE_MEMORY", True))


if __name__ == "__main__":
    unittest.main()
