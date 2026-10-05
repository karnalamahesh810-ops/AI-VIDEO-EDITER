"""
Old footage restore (src/archive_restore.py): which clips are restored, the
chain they get, that a failure or a timeout keeps the original, the cache,
the record in meta.sourcing - and that nothing changes while ARCHIVE_RESTORE
is off. A few tests run the real ffmpeg chain on small synthetic clips.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import archive_restore as ar
from src import config, media, upscale
from src.media import MediaAsset


def _clip(path, seconds=1.0, size="320x240", rate="30000/1001", extra="", bw=False):
    """A small test clip encoded like a YouTube section (h264, yuv420p); `extra` filters
    after the picture (borders, interlacing...). A zooming fractal, not testsrc2: idet
    reads testsrc2's one-line stripes as combing in every frame."""
    vf = ["hue=s=0" if bw else "null"] + ([extra] if extra else [])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"mandelbrot=size={size}:rate={rate}",
                    "-t", f"{seconds}", "-vf", ",".join(vf), "-pix_fmt", "yuv420p", "-c:v", "libx264",
                    "-preset", "ultrafast", "-crf", "20", path], check=True)
    return path


def _asset(path, title="Boulder Dam newsreel 1936", source="youtube", url=""):
    return MediaAsset(kind="video", source=source, url=url or "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                      local_path=path, attribution=title, query="boulder dam construction")


def _info(**kw):
    base = {"archive": True, "w": 640, "h": 480, "fps": 29.97, "seconds": 7.0, "sar": 1.0, "tagged": False,
            "real_lines": 280, "interlaced": False, "parity": "", "crop": None, "unique": 1.0, "mono": False}
    base.update(kw)
    return base


def _ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


class Decide(unittest.TestCase):
    def test_modern_footage_is_never_touched(self):
        self.assertEqual(ar.decide(_info(archive=False)), (False, "modern"))

    def test_sub_hd_archive_film_is_restored(self):
        self.assertEqual(ar.decide(_info()), (True, "480 lines"))
        self.assertTrue(ar.decide(_info(w=320, h=240, real_lines=186))[0])

    def test_a_full_hd_archive_file_is_restored_only_when_its_picture_is_small(self):
        upscaled = _info(w=1440, h=1080, real_lines=172)             # a VHS uploaded at 1080p
        self.assertEqual(ar.decide(upscaled), (True, "172 real lines of 1080"))
        remaster = _info(w=1920, h=1080, real_lines=860)              # a sharp HD scan
        self.assertEqual(ar.decide(remaster), (False, "sharp"))
        self.assertEqual(ar.decide(dict(remaster, interlaced=True)), (True, "interlaced"))

    def test_what_is_never_restored(self):
        self.assertEqual(ar.decide(_info(tagged=True))[1], "already restored")
        self.assertEqual(ar.decide(_info(w=480, h=640))[1], "vertical")
        self.assertEqual(ar.decide(_info(seconds=600.0))[1], "too long")          # a whole archive.org film
        self.assertEqual(ar.decide(_info(w=0, h=0))[1], "unreadable")

    def test_archive_film_is_known_by_its_title_or_source(self):
        self.assertTrue(ar.archive_marked(_asset("x", "Mt. St. Helens eruption (1980 KIRO 7 program)")))
        self.assertTrue(ar.archive_marked(_asset("x", "British Pathe newsreel")))
        self.assertTrue(ar.archive_marked(_asset("x", "Lake Mead", source="archive_org")))
        self.assertFalse(ar.archive_marked(_asset("x", "Lake Mead drone 4K 2024")))


class Plan(unittest.TestCase):
    def test_a_4_3_clip_keeps_the_middle_16_9_and_comes_out_as_the_frame(self):
        p = ar.plan(_info())
        self.assertEqual(p["size"], [1920, 1080])
        self.assertIn("crop=640:360:0:60", p["vf"])                    # all a cover fit shows of 4:3
        self.assertIn("scale=1920:1080", p["vf"])
        self.assertLess(p["vf"].index("deblock"), p["vf"].index("crop="))   # the block grid is the source's own
        self.assertIn("cas=strength=", p["vf"])
        self.assertNotIn("minterpolate", p["vf"])
        self.assertEqual(p["seconds"], 0.0)                              # no cut: the length cannot change

    def test_film_gate_borders_are_cropped_before_the_middle_is_taken(self):
        p = ar.plan(_info(crop=(578, 476, 30, 4)))
        self.assertIn("borders", p["steps"])
        box, trimmed = ar.visible_box(640, 480, 1.0, (578, 476, 30, 4))
        self.assertTrue(trimmed)
        cw, ch, x, y = box
        self.assertGreaterEqual(x, 32)                                   # 2 px inside the gate
        self.assertLessEqual(x + cw, 640 - 32)
        self.assertAlmostEqual(cw / ch, 16 / 9, delta=0.02)

    def test_borders_that_are_not_borders_are_kept(self):
        self.assertIsNone(ar._crop_box(640, 480, (640, 480, 0, 0)))      # nothing to trim
        self.assertIsNone(ar._crop_box(640, 480, (300, 200, 170, 140)))  # most of the frame would go
        self.assertIsNone(ar._crop_box(640, 480, (700, 480, 0, 0)))      # outside the frame

    def test_wide_and_anamorphic_pictures(self):
        (cw, ch, x, _y), _ = ar.visible_box(1920, 816, 1.0, None)       # 2.35:1 scope: the middle columns
        self.assertEqual((ch, round(cw / ch, 2)), (816, 1.78))
        self.assertGreater(x, 0)
        (cw, ch, _x, _y), _ = ar.visible_box(720, 480, 8 / 9.0, None)   # NTSC DV 4:3
        self.assertAlmostEqual(cw * (8 / 9.0) / ch, 16 / 9, delta=0.02)

    def test_steps_follow_what_was_measured(self):
        p = ar.plan(_info(interlaced=True, parity="bff", mono=True))
        self.assertTrue(p["vf"].startswith("bwdif=mode=send_frame:parity=bff:deint=all,deblock"))
        self.assertIn("lutyuv=u=128:v=128", p["vf"])
        self.assertEqual(p["steps"][:2], ["deinterlace", "deblock"])
        self.assertIn("black-and-white", p["steps"])
        hd = ar.plan(_info(w=1440, h=1080, fps=59.94, real_lines=172))
        self.assertIn("fps=30000/1001", hd["vf"])                         # a 60p capture halved exactly
        self.assertIn("work at 360 lines", hd["steps"])                   # worked near its real detail

    def test_smoothing_is_optional_and_keeps_the_clip_length(self):
        self.assertNotIn("minterpolate", ar.plan(_info(unique=0.8))["vf"])
        with mock.patch.object(config, "ARCHIVE_RESTORE_SMOOTH", True):
            p = ar.plan(_info(unique=0.8))
            self.assertNotIn("minterpolate", ar.plan(_info(unique=0.98))["vf"])   # no repeated frames
        self.assertIn("minterpolate=fps=30000/1001", p["vf"])
        self.assertIn("tpad=stop_mode=clone", p["vf"])
        self.assertEqual(p["seconds"], 7.0)
        cmd = ar.command("in.mp4", "out.mp4", _info(), p, 4)
        self.assertEqual(cmd[cmd.index("-t") + 1], "7.000")

    def test_colour_tags_keep_the_source_matrix(self):
        self.assertEqual(ar._color_args(_info()), ["-colorspace", "smpte170m", "-color_primaries", "smpte170m",
                                                   "-color_trc", "smpte170m"])
        tagged = _info(color_space="bt709", color_primaries="bt709", color_transfer="unknown")
        self.assertEqual(ar._color_args(tagged), ["-colorspace", "bt709", "-color_primaries", "bt709"])
        self.assertEqual(ar._color_args(_info(w=1440, h=1080))[1], "bt709")
        self.assertEqual(ar._rate(29.97), "30000/1001")
        self.assertEqual(ar._rate(25.0), "25")


class Keys(unittest.TestCase):
    def test_a_youtube_section_is_known_by_its_video_start_and_length(self):
        key, where = ar.source_key(_asset("/w/yt_fjaKaQb6dZY_98000_7000_ab12cd34ef.mp4"),
                                   "/w/yt_fjaKaQb6dZY_98000_7000_ab12cd34ef.mp4")
        self.assertEqual(key, "yt-fjaKaQb6dZY-98000-7000")
        self.assertEqual(where, {"video": "fjaKaQb6dZY", "start": 98.0, "length": 7.0})
        pool = _asset("/w/seq_x_1.mp4", url="https://www.youtube.com/watch?v=BBBBBBBBBBB&t=40")
        pool.moment = {"start": 40.0}
        self.assertEqual(ar.source_key(pool, "/w/seq_x_1.mp4", 6.0)[0], "yt-BBBBBBBBBBB-40000-6000")

    def test_anything_else_is_known_by_its_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.mp4"), os.path.join(d, "b.mp4")
            for p, body in ((a, b"1" * 5000), (b, b"2" * 5000)):
                with open(p, "wb") as fh:
                    fh.write(body)
            ka = ar.source_key(_asset(a, source="archive_org"), a)[0]
            self.assertTrue(ka.startswith("file-"))
            self.assertNotEqual(ka, ar.source_key(_asset(b, source="archive_org"), b)[0])


class Fallbacks(unittest.TestCase):
    """A clip that cannot be restored keeps its file, whatever went wrong."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "yt_AAAAAAAAAAA_1000_7000_x.mp4")
        with open(self.path, "wb") as fh:
            fh.write(b"original" * 2000)
        ar.reset()
        self.addCleanup(ar.reset)
        patches = [mock.patch.object(ar, "_measure", return_value=_info()),
                   mock.patch.object(config, "ARCHIVE_RESTORE_CACHE_DIR", os.path.join(self.dir, "cache"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _unchanged(self):
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), b"original" * 2000)
        self.assertFalse(ar.is_restored(self.path))
        self.assertEqual(sorted(os.listdir(self.dir)), ["yt_AAAAAAAAAAA_1000_7000_x.mp4"])   # no leftovers

    def test_a_timeout_keeps_the_original(self):
        with mock.patch.object(ar.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
            rec = ar.restore_clip(_asset(self.path), self.path)
        self.assertEqual((rec["restored"], rec["why"]), (False, "timeout"))
        self._unchanged()

    def test_a_failed_ffmpeg_keeps_the_original(self):
        done = subprocess.CompletedProcess([], 1, "", "Error while filtering: Invalid argument\nbench: maxrss=1KiB")
        with mock.patch.object(ar.subprocess, "run", return_value=done):
            rec = ar.restore_clip(_asset(self.path), self.path)
        self.assertFalse(rec["restored"])
        self.assertEqual(rec["why"], "failed: Error while filtering: Invalid argument")
        self._unchanged()

    def test_a_shorter_output_is_refused(self):
        def fake(cmd, **kw):
            with open(cmd[-1], "wb") as fh:                       # ffmpeg "succeeds" with a shorter clip
                fh.write(b"x" * 20_000)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(ar.subprocess, "run", side_effect=fake), \
                mock.patch.object(ar, "probe", return_value={"w": 1920, "h": 1080, "seconds": 6.5}):
            rec = ar.restore_clip(_asset(self.path), self.path)
        self.assertFalse(rec["restored"])                         # it would play slowed down in its scene
        self._unchanged()

    def test_no_time_left_in_the_box_restores_nothing(self):
        with mock.patch.object(ar.subprocess, "run", side_effect=AssertionError("must not run")):
            rec = ar.restore_clip(_asset(self.path), self.path, deadline=1.0)     # long gone
        self.assertEqual(rec["why"], "time box")
        self._unchanged()

    def test_a_broken_check_restores_nothing(self):
        with mock.patch.object(ar, "_measure", side_effect=ValueError("bad")):
            rec = ar.restore_clip(_asset(self.path), self.path)
        self.assertFalse(rec["restored"])
        self._unchanged()

    def test_the_job_box_is_shared_by_every_clip(self):
        with mock.patch.object(ar, "restore_clip", side_effect=AssertionError("must not start")), \
                mock.patch.object(config, "ARCHIVE_RESTORE_PARALLEL", 1):
            report = ar.restore_assets([_asset(self.path)], box_seconds=1.0)
        self.assertEqual(report["restored"], 0)
        self.assertEqual(report["skipped"], {"time box": 1})


class OffChangesNothing(unittest.TestCase):
    def test_upscale_assets_is_the_same_with_the_flag_off(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "yt_AAAAAAAAAAA_1000_7000_x.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x" * 100)
            film = _asset(p, "Boulder Dam newsreel 1936")
            org = _asset(os.path.join(d, "film.mp4"), source="archive_org")
            with open(org.local_path, "wb") as fh:
                fh.write(b"y" * 100)
            with mock.patch.object(config, "ARCHIVE_RESTORE", False), \
                    mock.patch.object(config, "UPSCALE_ENABLED", True), \
                    mock.patch.object(config, "ALLOW_VERTICAL", False), \
                    mock.patch.object(ar, "restore_assets", side_effect=AssertionError("restore while off")), \
                    mock.patch.object(upscale, "upscale_clip", return_value=False) as uc:
                out = upscale.upscale_assets([film, org, None])
        self.assertEqual(out, {"image": 0, "clip": 0, "framed": 0, "skipped_time": 0, "queued": 1})
        uc.assert_called_once_with(p, config.MIN_CLIP_HEIGHT)         # the archive.org film still kept as it was
        self.assertFalse(upscale.is_restored(p))

    def test_the_flag_is_on_by_default_and_a_job_can_turn_it_off(self):
        # On since the owner switched it on (2026-10-05).
        import handler
        self.assertTrue(config.ARCHIVE_RESTORE)
        for key in ("ARCHIVE_RESTORE", "ARCHIVE_RESTORE_SECONDS", "ARCHIVE_RESTORE_SMOOTH"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
        before = (config.ARCHIVE_RESTORE, config.ARCHIVE_RESTORE_SECONDS)
        prev = handler._apply_config({"ARCHIVE_RESTORE": "0", "ARCHIVE_RESTORE_SECONDS": "90"})
        try:
            self.assertIs(config.ARCHIVE_RESTORE, False)
            self.assertEqual(config.ARCHIVE_RESTORE_SECONDS, 90.0)
        finally:
            handler._restore_config(prev)
        self.assertEqual((config.ARCHIVE_RESTORE, config.ARCHIVE_RESTORE_SECONDS), before)

    def test_restored_clips_stay_out_of_the_library_while_the_owner_tries_the_look(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "clip.mp4")
            ar.reset()
            self.addCleanup(ar.reset)
            with ar._LOCK:
                ar.RESTORED[os.path.abspath(p)] = {"restored": True}
            with mock.patch.object(config, "ARCHIVE_RESTORE", True):
                self.assertTrue(upscale.is_restored(p))
            with mock.patch.object(config, "ARCHIVE_RESTORE", False):
                self.assertFalse(upscale.is_restored(p))             # off: nothing reads the registry


class UpscaleIntegration(unittest.TestCase):
    def test_restored_clips_skip_the_lanczos_pass_and_the_report_comes_back(self):
        with tempfile.TemporaryDirectory() as d:
            film = os.path.join(d, "yt_AAAAAAAAAAA_1000_7000_x.mp4")
            modern = os.path.join(d, "yt_BBBBBBBBBBB_1000_7000_x.mp4")
            for p in (film, modern):
                with open(p, "wb") as fh:
                    fh.write(b"x" * 100)

            def fake_restore(assets, box):
                with ar._LOCK:
                    ar.RESTORED[os.path.abspath(film)] = {"restored": True}
                return {"on": True, "restored": 1, "box": box}

            with mock.patch.object(config, "ARCHIVE_RESTORE", True), \
                    mock.patch.object(config, "ARCHIVE_RESTORE_SECONDS", 120.0), \
                    mock.patch.object(config, "UPSCALE_ENABLED", True), \
                    mock.patch.object(config, "ALLOW_VERTICAL", False), \
                    mock.patch.object(ar, "restore_assets", side_effect=fake_restore) as ra, \
                    mock.patch.object(upscale, "upscale_clip", return_value=False) as uc:
                out = upscale.upscale_assets([_asset(film), _asset(modern, "Lake Mead drone 2024")])
                recut = upscale.upscale_assets([_asset(film)], deadline_seconds=30.0)
        self.assertEqual(out["archiveRestore"], {"on": True, "restored": 1, "box": 120.0})
        uc.assert_called_once_with(modern, config.MIN_CLIP_HEIGHT)    # the restored film is not sharpened again
        self.assertEqual(ra.call_args_list[1][0][1], 30.0)            # a re-cut's own box bounds the restore
        self.assertEqual(recut["queued"], 0)
        ar.reset()

    def test_a_broken_restore_never_breaks_the_polish(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "yt_AAAAAAAAAAA_1000_7000_x.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x" * 100)
            with mock.patch.object(config, "ARCHIVE_RESTORE", True), \
                    mock.patch.object(config, "UPSCALE_ENABLED", True), \
                    mock.patch.object(config, "ALLOW_VERTICAL", False), \
                    mock.patch.object(ar, "restore_assets", side_effect=RuntimeError("boom")), \
                    mock.patch.object(upscale, "upscale_clip", return_value=True) as uc:
                out = upscale.upscale_assets([_asset(p)])
        self.assertEqual(out["clip"], 1)                                # the normal polish ran
        self.assertEqual(out["archiveRestore"]["error"], "RuntimeError")
        uc.assert_called_once()


class PlanRecordsIt(unittest.TestCase):
    """do_plan: the restore runs where downloads are polished and lands in meta.sourcing."""

    def _run(self, on):
        import handler
        from src import gapfill, pools
        from src.transcribe import Segment, Word
        segs, shots = [], []
        for i in range(4):
            words = [Word(text=w, start=i * 3.0 + k * 0.4, end=i * 3.0 + k * 0.4 + 0.3)
                     for k, w in enumerate(f"Boulder Dam line number {i}".split())]
            segs.append(Segment(text=f"Boulder Dam line number {i}", start=i * 3.0, end=(i + 1) * 3.0, words=words))
            shots.append({"query": "boulder dam 1936", "visualType": "footage", "subject": "Boulder Dam",
                          "subjectType": "place", "overlay": None})
        sourced = [MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=VIDEO00000{k}",
                              local_path=f"/w/yt_VIDEO00000{k}_1000_3000_x.mp4", attribution="Boulder Dam 1936",
                              moment_key=f"yt:VIDEO00000{k}@0", moment={"start": 1.0}) for k in range(4)]
        seen = {}

        class Built(Exception):
            pass

        def build(*a, **kw):
            seen["stats"] = dict(media.LAST_STATS)
            raise Built()
        brief = {"kind": "explainer", "summary": "", "event": "Boulder Dam", "year": 1936, "recent": False,
                 "places": ["Boulder Dam"], "people": [], "hookBeats": [0], "cast": [], "sections": []}
        report = {"on": True, "restored": 2, "seconds": 9.1}
        with mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"), \
                mock.patch.object(handler.storage, "download", return_value="/w/vo.mp3"), \
                mock.patch.object(handler.renderer, "probe_duration", return_value=12.0), \
                mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]), \
                mock.patch.object(handler.transcribe, "segment_words", return_value=segs), \
                mock.patch.object(handler.director, "story_brief", return_value=brief), \
                mock.patch.object(handler.director, "plan", return_value=(shots, "ai", [])), \
                mock.patch.object(handler.library.Library, "load", return_value=None), \
                mock.patch.object(handler.fanout, "enabled_for", return_value=False), \
                mock.patch.object(pools, "source_by_subject", return_value={}), \
                mock.patch.object(media, "source_many",
                                  side_effect=lambda jobs_, work, **kw: [
                                      sourced[j["index"]] for j in sorted(jobs_, key=lambda j: j["index"])]), \
                mock.patch.object(media, "rescue_fill", return_value={}), \
                mock.patch.object(handler.timeline, "build", side_effect=build), \
                mock.patch.object(handler.upscale, "upscale_assets",
                                  return_value={"queued": 0, "archiveRestore": report}) as ua, \
                mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False), \
                mock.patch.object(config, "ARCHIVE_RESTORE", on):
            with self.assertRaises(Built):
                handler.do_plan({"audio_url": "vo.mp3", "project_id": ""}, tempfile.mkdtemp(), handler.Reporter(""))
        handler.vision.set_story({})
        gapfill.reset()
        return seen, ua, report

    def test_on_it_runs_and_is_recorded(self):
        seen, ua, report = self._run(True)
        ua.assert_called_once()
        self.assertEqual(seen["stats"]["archiveRestore"], report)
        self.assertNotIn("archiveRestore", seen["stats"]["pools"].get("upscale", {}))

    def test_off_nothing_runs_and_nothing_is_recorded(self):
        seen, ua, _report = self._run(False)
        ua.assert_not_called()                                        # UPSCALE_ENABLED and ALLOW_VERTICAL off too
        self.assertNotIn("archiveRestore", seen["stats"])


@unittest.skipUnless(_ffmpeg(), "ffmpeg not installed")
class RealChain(unittest.TestCase):
    """The chain itself on small synthetic clips (about a second each)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        ar.reset()
        self.addCleanup(ar.reset)
        for name, value in (("ARCHIVE_RESTORE", True), ("ARCHIVE_RESTORE_CACHE_DIR", os.path.join(self.dir, "c"))):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_an_old_tv_clip_with_borders_and_combing_comes_out_as_a_clean_1080p_frame(self):
        path = _clip(os.path.join(self.dir, "yt_KKKKKKKKKKK_98000_1000_x.mp4"), seconds=1.0, size="480x360",
                     rate="60000/1001", extra="interlace=scan=tff,crop=440:360:20:0,pad=480:360:20:0:black")
        info = ar._measure(_asset(path, "KIRO-TV 1980 eruption coverage"), path)
        self.assertTrue(info["interlaced"])
        rec = ar.restore_clip(_asset(path, "KIRO-TV 1980 eruption coverage"), path)
        self.assertTrue(rec["restored"], rec)
        self.assertIn("deinterlace", rec["steps"])
        self.assertIn("borders", rec["steps"])
        got = ar.probe(path)
        self.assertEqual((got["w"], got["h"]), (1920, 1080))
        self.assertTrue(got["tagged"])                                 # never restored twice
        self.assertGreaterEqual(got["seconds"], info["seconds"] - 0.07)
        self.assertTrue(ar.is_restored(path))
        self.assertEqual(upscale.original_lines(path), info["real_lines"] or 480)   # reframe keeps off it
        again = ar.restore_clip(_asset(path, "KIRO-TV 1980 eruption coverage"), path)
        self.assertEqual(again["why"], "already restored")

    def test_black_and_white_film_loses_its_colour_fringes(self):
        # A grey picture with a thin magenta fringe, as 240-line newsreel uploads carry them.
        path = _clip(os.path.join(self.dir, "yt_BWBWBWBWBWB_1000_1000_x.mp4"), size="320x240", bw=True,
                     extra="drawbox=x=150:y=0:w=2:h=ih:color=magenta@0.5:t=fill")
        self.assertTrue(ar.monochrome(path, 1.0))
        rec = ar.restore_clip(_asset(path, "Reclamation and the Arid West (1936)"), path)
        self.assertTrue(rec["restored"], rec)
        self.assertIn("black-and-white", rec["steps"])
        self.assertNotIn("deinterlace", rec["steps"])                    # progressive stays progressive
        import numpy as np
        q = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", path, "-frames:v", "1", "-vf",
                            "scale=160:90,format=yuv444p", "-f", "rawvideo", "-"], capture_output=True)
        a = np.frombuffer(q.stdout, np.uint8)[:160 * 90 * 3].reshape(3, 90, 160).astype(int)
        self.assertLessEqual(int(np.abs(a[1:] - 128).max()), 1)          # chroma neutral everywhere

    def test_a_modern_clip_is_left_byte_for_byte(self):
        path = _clip(os.path.join(self.dir, "yt_MMMMMMMMMMM_1000_1000_x.mp4"), size="320x240")
        with open(path, "rb") as fh:
            before = fh.read()
        report = ar.restore_assets([_asset(path, "Lake Mead drone 4K 2024")])
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual((report["restored"], report["archive"]), (0, 0))

    def test_the_same_moment_comes_from_the_cache_the_second_time(self):
        src = _clip(os.path.join(self.dir, "src.mp4"), size="320x240")
        first = os.path.join(self.dir, "a", "yt_CCCCCCCCCCC_5000_1000_one.mp4")
        second = os.path.join(self.dir, "b", "yt_CCCCCCCCCCC_5000_1000_two.mp4")
        for p in (first, second):
            os.makedirs(os.path.dirname(p))
            shutil.copyfile(src, p)
        one = ar.restore_clip(_asset(first), first)
        self.assertTrue(one["restored"] and not one["cached"], one)
        real_run = subprocess.run

        def no_encode(cmd, **kw):
            if "-benchmark" in cmd:
                raise AssertionError("encoded again")
            return real_run(cmd, **kw)
        with mock.patch.object(ar.subprocess, "run", side_effect=no_encode):
            two = ar.restore_clip(_asset(second), second)
        self.assertTrue(two["restored"] and two["cached"], two)
        with open(first, "rb") as a, open(second, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_smoothing_keeps_the_clip_length(self):
        # Film at 24 fps telecined to 30 by repeating frames: the case smoothing is for.
        path = _clip(os.path.join(self.dir, "yt_SSSSSSSSSSS_1000_2000_x.mp4"), seconds=2.0, size="320x240",
                     rate="24000/1001", extra="fps=30000/1001")
        before = ar.probe(path)["seconds"]
        with mock.patch.object(config, "ARCHIVE_RESTORE_SMOOTH", True):
            rec = ar.restore_clip(_asset(path), path)
        self.assertTrue(rec["restored"], rec)
        self.assertIn("smooth motion", rec["steps"])
        self.assertGreaterEqual(ar.probe(path)["seconds"], before - 0.07)    # never slowed in its scene


if __name__ == "__main__":
    unittest.main()
