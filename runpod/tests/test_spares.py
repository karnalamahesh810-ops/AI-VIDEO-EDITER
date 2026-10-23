"""
The empty-spots fix (2026-10-23): the spare bank (src/spares.py) and its ladder rung (gapfill._from_spare), the
ladder's own per-video cap and moment time, the soft photo cap, and the gate's one-decode grey frames.

The measured case: the Mount Rainier news compilation (b6cef117) judged ~310 downloaded clips, showed 50 and left
155 of 235 lines empty after sourcing; the ladder's moment rung filled 1. Offline: every judgement is a stub.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, filters, gapfill, media, spares

CLEAN = {"score": 0.55, "quality": 0.8, "description": "An aerial shot of Mount Rainier above the town of Orting "
                                                        "and the Puyallup River valley.",
         "has_text_or_watermark": False, "ai_generated": False, "is_talking_head": False}


def _ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


class Bank(unittest.TestCase):
    def setUp(self):
        spares.reset()
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        spares.reset()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _file(self, name, data=b"x" * 2048):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_a_clean_section_turned_down_for_its_line_is_kept_after_the_caller_deletes_it(self):
        p = self._file("yt_AAAAAAAAAAA_120000_6500_abc123.mp4")
        self.assertTrue(spares.record(p, dict(CLEAN), "YouTube: Drone over Orting"))
        os.remove(p)                                # the gate's caller removes its own name, as before
        got = spares.candidates({"index": 7, "intent": "the valley below Mount Rainier", "subject": "Orting"})
        self.assertEqual(len(got), 1)
        self.assertTrue(os.path.isfile(got[0]["path"]))
        self.assertEqual(got[0]["vid"], "AAAAAAAAAAA")
        self.assertAlmostEqual(got[0]["start"], 120.0)

    def test_a_tidied_cut_keeps_its_offset(self):
        self.assertEqual(spares.youtube_origin("yt_AAAAAAAAAAA_120000_6500_abc123_c00035.mp4"),
                         ("AAAAAAAAAAA", 123.5))
        self.assertEqual(spares.youtube_origin("seq_x_AAAAAAAAAAA_3.mp4"), ("", None))

    def test_what_rules_a_clip_out_for_every_line_is_never_banked(self):
        for i, flaw in enumerate(({"has_text_or_watermark": True}, {"ai_generated": True},
                                  {"is_talking_head": True}, {"quality": 0.2}, {"music_or_vice": True})):
            p = self._file(f"yt_AAAAAAAAAA{i}_1000_6500_abc.mp4")
            self.assertFalse(spares.record(p, dict(CLEAN, **flaw), "t"))
        self.assertFalse(spares.record(self._file("yt_BBBBBBBBBBB_1000_6500_abc.mp4"), None, "t"))
        self.assertFalse(spares.record(self._file("seq_tag_BBBBBBBBBBB_1.mp4"), dict(CLEAN), "t"))
        self.assertFalse(spares.record(self._file("photo.jpg"), dict(CLEAN), "t", source_url=""))
        self.assertTrue(spares.record(self._file("photo2.jpg"), dict(CLEAN), "t",
                                      source_url="https://example.org/rainier.jpg"))
        self.assertEqual(spares.stats()["banked"], 1)

    def test_off_with_the_flag(self):
        with mock.patch.object(config, "SPARE_BANK", False):
            self.assertFalse(spares.record(self._file("yt_AAAAAAAAAAA_1000_6500_abc.mp4"), dict(CLEAN), "t"))

    def test_matching_needs_the_lines_words_and_never_offers_a_turned_down_spare_twice(self):
        spares.record(self._file("yt_AAAAAAAAAAA_1000_6500_a.mp4"), dict(CLEAN), "Drone over Orting")
        spares.record(self._file("yt_CCCCCCCCCCC_1000_6500_c.mp4"),
                      dict(CLEAN, description="A busy shopping mall food court in Tokyo."), "Tokyo mall")
        job = {"index": 3, "intent": "the town of Orting below the volcano", "subject": "Orting, Washington"}
        got = spares.candidates(job)
        self.assertEqual([e["vid"] for e in got], ["AAAAAAAAAAA"])        # the mall shares nothing
        self.assertTrue(spares.take(got[0]))
        self.assertEqual(spares.candidates(job), [])                          # taken
        spares.give_back(got[0], 3)
        self.assertEqual(spares.candidates(job), [])                          # turned down for line 3
        self.assertEqual(len(spares.candidates(dict(job, index=4))), 1)       # still offered to line 4

    def test_a_banked_file_is_not_banked_again_from_its_own_rejudge(self):
        p = self._file("yt_AAAAAAAAAAA_1000_6500_a.mp4")
        spares.record(p, dict(CLEAN), "t")
        e = spares.candidates({"index": 1, "intent": "Mount Rainier Orting valley"})[0]
        self.assertFalse(spares.record(e["path"], dict(CLEAN), "t"))


class SpareRung(unittest.TestCase):
    def setUp(self):
        spares.reset()
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        spares.reset()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _bank(self, vid, start_ms=120000, desc=CLEAN["description"]):
        p = os.path.join(self.dir, f"yt_{vid}_{start_ms}_6500_abc.mp4")
        with open(p, "wb") as f:
            f.write(b"x" * 2048)
        self.assertTrue(spares.record(p, dict(CLEAN, description=desc), f"YouTube: {vid}"))
        os.remove(p)

    def _run(self, job, judge, used=None, kind="video"):
        seen = []

        def j(path, jb, label="", source_url=""):
            seen.append((source_url, media._RUNG.get()))
            return judge(source_url)
        with mock.patch.object(media, "_asset_ok_for", return_value=(True, "")), \
                mock.patch.object(gapfill, "_too_short", return_value=False), \
                mock.patch.object(media, "judge_clip", side_effect=j):
            got = gapfill._from_spare(job, used or gapfill.Used(), self.dir, 1e12, kind)
        return got, seen

    JOB = {"index": 10, "start": 300.0, "seconds": 5.0, "subject": "Orting, Washington", "query": "Orting lahar",
           "intent": "the town of Orting under Mount Rainier", "context": "Orting sits on old mudflows"}

    def test_a_spare_is_judged_for_this_line_as_shows_its_subject_and_placed(self):
        self._bank("AAAAAAAAAAA")
        got, seen = self._run(dict(self.JOB), lambda u: (True, {"score": 0.8, "description": "Orting from above"}))
        self.assertEqual(got.source, "youtube")
        self.assertTrue(got.url.startswith("https://www.youtube.com/watch?v=AAAAAAAAAAA"))
        self.assertEqual(got.moment["start"], 120.0)
        self.assertEqual(got.relevance_score, 0.8)
        self.assertTrue(got.review_required)
        self.assertEqual(seen[0][1], {"label": "Orting, Washington"})
        self.assertEqual(spares.stats()["filled"], 1)

    def test_turned_down_tries_the_next_within_the_judge_cap(self):
        for v in ("AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC", "DDDDDDDDDDD"):
            self._bank(v)
        with mock.patch.object(config, "SPARE_JUDGES", 2):
            got, seen = self._run(dict(self.JOB), lambda u: (False, {"score": 0.2}))
        self.assertIsNone(got)
        self.assertEqual(len(seen), 2)
        self.assertEqual(spares.stats()["turnedDown"], 2)

    def test_the_variety_rules_hold(self):
        self._bank("AAAAAAAAAAA")
        used = gapfill.Used()
        used.add(11, gapfill.Shot(video="yt:AAAAAAAAAAA", start=400.0, at=305.0))     # its video on the next scene
        got, seen = self._run(dict(self.JOB), lambda u: (True, {"score": 0.8}), used=used)
        self.assertIsNone(got)
        self.assertEqual(seen, [])
        with mock.patch.multiple(config, SAME_VIDEO_GAP_SECONDS=120.0):
            used = gapfill.Used()
            used.add(3, gapfill.Shot(video="yt:AAAAAAAAAAA", start=400.0, at=250.0))  # 50 s before this line
            got, _ = self._run(dict(self.JOB), lambda u: (True, {"score": 0.8}), used=used)
            self.assertIsNone(got)
            used = gapfill.Used()
            used.add(3, gapfill.Shot(video="yt:AAAAAAAAAAA", start=125.0, at=-100.0))  # the same moment
            got, _ = self._run(dict(self.JOB), lambda u: (True, {"score": 0.8}), used=used)
            self.assertIsNone(got)
            used = gapfill.Used()
            used.add(3, gapfill.Shot(video="yt:AAAAAAAAAAA", start=400.0, at=-100.0))  # far away, another moment
            got, _ = self._run(dict(self.JOB), lambda u: (True, {"score": 0.8}), used=used)
            self.assertIsNotNone(got)

    def test_a_near_duplicate_of_a_neighbour_is_skipped(self):
        self._bank("AAAAAAAAAAA")
        with mock.patch.object(gapfill, "_looks_like_neighbour", return_value=True):
            got, seen = self._run(dict(self.JOB), lambda u: (True, {"score": 0.8}))
        self.assertIsNone(got)
        self.assertEqual(seen, [])

    def test_a_spare_picture(self):
        p = os.path.join(self.dir, "pic.jpg")
        with open(p, "wb") as f:
            f.write(b"x" * 2048)
        spares.record(p, dict(CLEAN), "Orting siren tower", source_url="https://example.org/orting.jpg")
        got, seen = self._run(dict(self.JOB), lambda u: (True, {"score": 0.7}), kind="image")
        self.assertEqual(got.kind, "image")
        self.assertEqual(got.url, "https://example.org/orting.jpg")
        self.assertIsNone(seen[0][1])               # a picture is judged against the line itself

    def test_the_ladder_asks_the_bank_before_any_download(self):
        self._bank("AAAAAAAAAAA")
        job = dict(self.JOB, index=0, visual_type="footage")
        results = [None]
        with mock.patch.object(media, "_asset_ok_for", return_value=(True, "")), \
                mock.patch.object(gapfill, "_too_short", return_value=False), \
                mock.patch.object(media, "judge_clip", return_value=(True, {"score": 0.8})), \
                mock.patch.object(gapfill, "_from_moment", side_effect=AssertionError("no download")), \
                mock.patch.object(gapfill, "_from_still", side_effect=AssertionError("no picture search")), \
                mock.patch("src.packs.usable", return_value=False):
            out = gapfill.fill_empty([job], results, self.dir, label="test")
        self.assertEqual(out["spare"], 1)
        self.assertEqual(out["left"], 0)
        self.assertEqual(results[0].moment["start"], 120.0)


class LadderCap(unittest.TestCase):
    def test_may_place_takes_the_ladders_cap(self):
        with mock.patch.multiple(config, MAX_MOMENTS_PER_VIDEO=2, SAME_VIDEO_GAP_SECONDS=120.0):
            self.assertFalse(media.may_place([0.0, 300.0], 600.0))
            self.assertTrue(media.may_place([0.0, 300.0], 600.0, cap=3))
            self.assertFalse(media.may_place([0.0, 300.0], 350.0, cap=3))     # the gap still holds
        with mock.patch.multiple(config, MAX_MOMENTS_PER_VIDEO=2, FILL_MAX_MOMENTS_PER_VIDEO=1):
            self.assertEqual(gapfill._fill_cap(), 2)                          # never below the search's own
        with mock.patch.multiple(config, MAX_MOMENTS_PER_VIDEO=0, FILL_MAX_MOMENTS_PER_VIDEO=4):
            self.assertEqual(gapfill._fill_cap(), 0)                          # no cap at all stays none

    def test_the_moment_rung_gets_time_for_a_download(self):
        # FALLBACK_SCENE_SECONDS 45 used to give the moment ~25 s: a proxied download alone takes 10-45 s.
        stops = []

        def moment(job, used, work, stop, donors, judged=True):
            stops.append(stop)
            return None
        job = {"index": 0, "start": 0.0, "seconds": 5.0, "subject": "x", "query": "x", "visual_type": "footage"}
        import time
        t0 = time.time()
        with mock.patch.multiple(config, FALLBACK_SCENE_SECONDS=45.0, FALLBACK_MOMENT_MIN_SECONDS=90.0,
                                 FALLBACK_STILLS=False, FALLBACK_MAX_SECONDS=900.0), \
                mock.patch.object(gapfill, "_from_moment", side_effect=moment), \
                mock.patch.object(gapfill, "_from_spare", return_value=None), \
                mock.patch.object(gapfill, "_from_library", return_value=None), \
                mock.patch.object(gapfill, "_from_reserve", return_value=None), \
                mock.patch("src.packs.usable", return_value=False):
            gapfill.fill_empty([job], [None], tempfile.gettempdir(), donors=[{"index": 5, "vid": "AAAAAAAAAAA"}])
        self.assertTrue(stops and stops[0] - t0 >= 89.0)


@unittest.skipUnless(_ffmpeg(), "ffmpeg not installed")
class OneDecode(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.clip = os.path.join(self.dir, "clip.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                        "-t", "6", "-pix_fmt", "yuv420p", self.clip], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        filters._GRAY_CACHE.clear()

    def test_the_shared_decode_gives_the_same_frames_as_one_run_per_look(self):
        import numpy as np
        secs = filters._video_seconds(self.clip)
        specs = list(filters._SHARED_SPECS) + [(filters._still_count(secs), 128, 72)]
        with mock.patch.object(config, "GRAY_SHARED_DECODE", False):
            old = {sp: filters._gray_frames(self.clip, *sp) for sp in specs}
        filters._GRAY_CACHE.clear()
        with mock.patch.object(config, "GRAY_SHARED_DECODE", True):
            new = {sp: filters._gray_frames(self.clip, *sp) for sp in specs}
            again = filters._gray_frames(self.clip, 6, 320, 180)        # from the cache
        for sp in specs:
            self.assertEqual(len(old[sp]), len(new[sp]), sp)
            for a, b in zip(old[sp], new[sp]):
                self.assertTrue(np.array_equal(a, b), sp)
        self.assertEqual(len(again), len(old[(6, 320, 180)]))

    def test_a_hard_link_is_the_same_file(self):
        link = os.path.join(self.dir, "_spare_link.mp4")
        try:
            os.link(self.clip, link)
        except OSError:
            self.skipTest("no hard links here")
        self.assertEqual(filters._file_key(self.clip), filters._file_key(link))

    def test_near_duplicate(self):
        other = os.path.join(self.dir, "other.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=25",
                        "-t", "6", "-pix_fmt", "yuv420p", other], check=True, capture_output=True)
        copy = os.path.join(self.dir, "copy.mp4")
        shutil.copy2(self.clip, copy)
        spares.reset()
        self.assertTrue(spares.near_duplicate(self.clip, [copy]))
        self.assertFalse(spares.near_duplicate(self.clip, [other]))


if __name__ == "__main__":
    unittest.main()
