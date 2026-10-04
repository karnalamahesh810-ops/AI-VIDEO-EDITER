"""No answer paid for twice (JUDGE_MEMORY; the cost plan, 2026-10-05).

A paid verdict that rejects a candidate for every line (text or a watermark,
AI-made, too poor to show) is remembered like the free filters' rejections, for
that moment of a clip or that picture; a fine pass already paid for is not paid
again; a moment known bad is not refined first. Off by default: exactly as before.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import handler
from src import config, media, moments, vision
from src.media import MediaAsset


def _verdict(**kw):
    v = {"description": "a shot", "score": 0.85, "quality": 0.8, "has_text_or_watermark": False,
         "is_talking_head": False, "ai_generated": False, "studio": False, "specificity": "location"}
    v.update(kw)
    return v


class LineFreeVerdicts(unittest.TestCase):
    def test_a_job_can_try_it(self):
        self.assertIn("JUDGE_MEMORY", handler.CONFIG_OVERRIDABLE)

    def test_what_holds_for_every_line(self):
        self.assertTrue(media.judged_line_free(_verdict(has_text_or_watermark=True, score=0.0)))
        self.assertTrue(media.judged_line_free(_verdict(ai_generated=True)))
        self.assertTrue(media.judged_line_free(_verdict(quality=0.1)))
        # A named person's line may use a studio or a talking head; a low score is about this line.
        self.assertEqual(media.judged_line_free(_verdict(studio=True)), "")
        self.assertEqual(media.judged_line_free(_verdict(is_talking_head=True)), "")
        self.assertEqual(media.judged_line_free(_verdict(score=0.3)), "")
        self.assertEqual(media.judged_line_free(_verdict(quality=None, score=0.2)), "")
        self.assertEqual(media.judged_line_free(None), "")

    def test_remembered_for_the_moment_not_the_whole_video(self):
        with mock.patch.dict(media._BAD, clear=True):
            media._mark_bad("yt:VIDEO000001", "yt:VIDEO000001@3", media.judged_line_free(_verdict(ai_generated=True)))
            self.assertTrue(media._is_bad("yt:VIDEO000001@3"))
            self.assertFalse(media._is_bad("yt:VIDEO000001"))
            self.assertFalse(media._is_bad("yt:VIDEO000001@4"))


class _Gate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        bad = mock.patch.dict(media._BAD, clear=True)
        bad.start()
        self.addCleanup(bad.stop)
        self.p = [mock.patch.object(media, "slop_reason", return_value=""),
                  mock.patch.object(media, "watermark_reason", return_value=""),
                  mock.patch.object(media, "_local_check", return_value=None),
                  mock.patch.object(vision, "enabled", return_value=True)]
        for p in self.p:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.p])

    def gate(self, verdict, subject_type="place"):
        path = os.path.join(self.d, "c.mp4")
        with open(path, "wb") as fh:
            fh.write(b"x" * 100)
        token = media._SUBJECT_TYPE.set(subject_type)
        try:
            media._GATE_SLOP.set("")
            with mock.patch.object(vision, "judge", return_value=verdict):
                keep, _v = media._vision_gate(path, "Lake Powell boat ramp", "", "label")
            return keep, media._GATE_SLOP.get()
        finally:
            media._SUBJECT_TYPE.reset(token)


class GateMemory(_Gate):
    def test_off_a_paid_rejection_is_forgotten_as_before(self):
        with mock.patch.object(config, "JUDGE_MEMORY", False):
            self.assertEqual(self.gate(_verdict(has_text_or_watermark=True, score=0.0)), (False, ""))

    def test_on_a_rejection_for_every_line_is_handed_to_the_callers(self):
        with mock.patch.object(config, "JUDGE_MEMORY", True):
            keep, why = self.gate(_verdict(has_text_or_watermark=True, score=0.0))
            self.assertFalse(keep)
            self.assertTrue(why.startswith(media._LINE_FREE))
            self.assertEqual(self.gate(_verdict(ai_generated=True))[1], "judged unusable for any line: AI-made")
            # Not for every line: nothing is remembered.
            self.assertEqual(self.gate(_verdict(score=0.4)), (False, ""))
            self.assertEqual(self.gate(_verdict(studio=True)), (False, ""))
            self.assertEqual(self.gate(_verdict(studio=True), subject_type="person"), (True, ""))
            self.assertEqual(self.gate(_verdict()), (True, ""))


class PicturesJudgedOnce(_Gate):
    def _pick_twice(self, memory: bool):
        pic = os.path.join(self.d, "agency.jpg")
        with open(pic, "wb") as fh:
            fh.write(b"jpeg" * 500)
        downloads, judged = [], []

        def download(candidate, query, work_dir):
            downloads.append(candidate.url)
            candidate.local_path = pic
            return candidate

        def judge(path, intent, context="", event=False, scene=None):
            judged.append(intent)
            return _verdict(has_text_or_watermark=True, score=0.0)
        cand = lambda: MediaAsset(kind="image", source="web_image", url="https://img.example/lake.jpg",  # noqa: E731
                                  attribution="Lake Powell | alamy")
        with mock.patch.object(config, "JUDGE_MEMORY", memory), \
                mock.patch.object(config, "PICTURE_PREFETCH", 0), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(vision, "judge", side_effect=judge):
            first = media._pick_unused([cand()], set(), "Lake Powell", self.d, "Lake Powell boat ramp")
            second = media._pick_unused([cand()], set(), "Lake Powell", self.d, "Lake Powell houseboats")
        return first, second, downloads, judged

    def test_off_every_scene_downloads_and_judges_it_again(self):
        first, second, downloads, judged = self._pick_twice(False)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(downloads), 2)
        self.assertEqual(judged, ["Lake Powell boat ramp", "Lake Powell houseboats"])

    def test_on_the_second_scene_never_pays_for_it(self):
        first, second, downloads, judged = self._pick_twice(True)
        self.assertIsNone(first)
        self.assertIsNone(second)                         # the same outcome
        self.assertEqual(len(downloads), 1)
        self.assertEqual(judged, ["Lake Powell boat ramp"])


class FinePassOnce(unittest.TestCase):
    def setUp(self):
        media.reset_cache()
        self.addCleanup(media.reset_cache)

    def _refine_twice(self, memory: bool, answer):
        calls = []

        def refine(info, coarse, intent, context, grab, proxy=""):
            calls.append(intent)
            return dict(answer) if answer else None
        with mock.patch.object(config, "JUDGE_MEMORY", memory), \
                mock.patch.object(config, "MOMENT_FINE_PASS", True), \
                mock.patch.object(media, "_yt_info", return_value=({"id": "v"}, "")), \
                mock.patch.object(moments, "refine", side_effect=refine):
            coarse = {"start": 120.0, "score": 0.8}
            a = media._refine_moment({"id": "VIDEO000001"}, coarse, 8.5, "Glen Canyon Dam spillway", "")
            b = media._refine_moment({"id": "VIDEO000001"}, coarse, 8.5, "Glen Canyon Dam spillway", "")
            c = media._refine_moment({"id": "VIDEO000001"}, coarse, 8.5, "Lake Powell houseboats", "")
        return a, b, c, calls

    def test_off_a_scene_searched_again_pays_the_fine_pass_again(self):
        fine = {"start": 118.4, "score": 0.86, "span": 9.0, "description": "spillway", "tiles": 9, "fine": True}
        a, b, c, calls = self._refine_twice(False, fine)
        self.assertEqual(a, b)
        self.assertEqual(len(calls), 3)

    def test_on_the_same_question_is_answered_from_memory(self):
        fine = {"start": 118.4, "score": 0.86, "span": 9.0, "description": "spillway", "tiles": 9, "fine": True}
        a, b, c, calls = self._refine_twice(True, fine)
        self.assertEqual(a, b)                            # the same refined moment
        self.assertEqual(calls, ["Glen Canyon Dam spillway", "Lake Powell houseboats"])   # another intent asks

    def test_a_pass_that_found_nothing_is_asked_again(self):
        a, b, c, calls = self._refine_twice(True, None)
        self.assertEqual(a, {"start": 120.0, "score": 0.8})                               # the coarse pick stands
        self.assertEqual(len(calls), 3)

    def test_a_new_job_starts_from_nothing(self):
        media._FINE_MEMO["k"] = {"start": 1.0}
        media.reset_cache()
        self.assertEqual(media._FINE_MEMO, {})


if __name__ == "__main__":
    unittest.main()
