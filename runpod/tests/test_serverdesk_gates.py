"""The Breaking News Desk's shot gates, wrong-place guard, empty-shot ladder and bot-check rule (src/stormgate.py, src/stormdesk.py,
src/ytdlp.py). Offline: no network, no paid call. OCR and the face detector run for real where a test says so."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from src import batch, config, gapfill, srcbank, stormdesk, stormgate, stormledger, stormlib, stormpieces, ytdlp
from src.errors import FailureClass

FPS = 30


def vid(name):
    return (name + "___________")[:11]


def scene(i, start=None, n=90, src="abc", at=10.0, ch="KSL News", title="Lake Mead level", **extra):
    v = vid(src)
    start = i * n if start is None else start
    return {"id": f"s{i}", "startFrame": start, "durationInFrames": n, "text": f"line {i}", "visualType": "footage",
            "media": {"type": "video", "url": f"/tmp/{v}.mp4", "source": "youtube", "trimStart": 0.0, "clipSeconds": 60.0,
                      "attribution": f"YouTube: {title}"},
            "semanticMetadata": {"channel": ch, "sourceUrl": f"https://www.youtube.com/watch?v={v}&t={int(at)}", "moment": {"start": at},
                                 "assetId": f"yt:{v}@{int(at)}"}, **extra}


def doc_of(scenes):
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": sum(s["durationInFrames"] for s in scenes), "scenes": scenes,
            "meta": {}, "stormDesk": {"engine": "pieces"}}


def frame(color=(90, 120, 80)):
    return np.full((180, 320, 3), color, np.uint8)


class TextRule(unittest.TestCase):
    def box(self, x0, y0, x1, y1):
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    def test_area_over_the_limit_flags(self):
        flagged, area, _t = stormgate.text_verdict([(self.box(0, 0, 100, 20), "ABC", 0.9)], 320, 180)
        self.assertTrue(flagged)
        self.assertGreater(area, stormgate.OCR_AREA)

    def test_a_long_line_flags_however_small(self):
        flagged, _a, _t = stormgate.text_verdict([(self.box(0, 0, 10, 2), "CHANNEL", 0.9)], 320, 180)
        self.assertTrue(flagged)

    def test_small_short_or_unsure_text_passes(self):
        self.assertFalse(stormgate.text_verdict([(self.box(0, 0, 10, 4), "STOP", 0.9)], 320, 180)[0])
        self.assertFalse(stormgate.text_verdict([(self.box(0, 0, 300, 100), "CHANNEL", 0.3)], 320, 180)[0])
        self.assertFalse(stormgate.text_verdict([(self.box(0, 0, 300, 100), ".", 0.99)], 320, 180)[0])

    def test_check_frames_face_first_then_text(self):
        fr = [frame()]
        self.assertIn("person", stormgate.check_frames(fr, ocr=lambda _f: [], face=lambda _f: 0.01))
        self.assertEqual(stormgate.check_frames(fr, ocr=lambda _f: [], face=lambda _f: 0.004), "")     # at the threshold: passes
        self.assertIn("text", stormgate.check_frames(fr, ocr=lambda _f: [(self.box(0, 0, 100, 60), "BREAKING", 0.9)], face=lambda _f: 0.0))


class RealDetectors(unittest.TestCase):
    """The detectors themselves, where this machine has them (the pods' image installs both)."""

    def test_yunet_loads_from_the_repo_and_sees_no_face_on_a_plain_frame(self):
        self.assertTrue(os.path.isfile(stormgate.MODEL))
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("no opencv")
        self.assertEqual(stormgate.face_share(frame()), 0.0)

    def test_ocr_reads_big_text(self):
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("no rapidocr here")
        from PIL import Image, ImageDraw
        from src.sdkit import gfx
        im = Image.new("RGB", (320, 180), (20, 20, 20))
        ImageDraw.Draw(im).text((10, 60), "BREAKING NEWS", font=gfx.font(30, "Bold"), fill=(255, 255, 255))
        rows = stormgate.read_text(np.asarray(im)[..., ::-1].copy())
        self.assertTrue(stormgate.text_verdict(rows, 320, 180)[0], rows)


class Autofix(unittest.TestCase):
    def test_a_failed_shot_is_rejected_and_placed_again_until_clean(self):
        d = doc_of([scene(0, src="good"), scene(1, src="bad"), scene(2, src="nat", natSound=True), scene(3, src="ok2")])
        rejected = []
        spare = iter(["worse", "clean"])

        def fill():
            for s in d["scenes"]:
                if not stormgate.has_picture(s):
                    s["media"] = {"type": "video", "url": f"/tmp/{vid(next(spare))}.mp4", "clipSeconds": 9.0}
                    s["semanticMetadata"] = {}
                    s.pop("_wasMedia", None)

        def frames(s):
            return [s["media"]["url"]]

        def check(fr):
            return "a person on camera" if vid("bad") in fr[0] or vid("worse") in fr[0] else ""
        rep = stormgate.autofix(d, {}, "", frames=frames, check=check, fill=fill, reject=lambda v, a, b, w: rejected.append((v, a)))
        self.assertEqual(rep["rejected"], 2)
        self.assertEqual(rep["rounds"], 3)
        self.assertIn(vid("clean"), d["scenes"][1]["media"]["url"])
        self.assertEqual(rejected, [("yt:" + vid("bad"), 10.0)])            # (the spare with no known moment had nothing to reject)
        self.assertNotIn("stillFlagged", rep)

    def test_pause_hook_and_ai_shots_are_exempt(self):
        d = doc_of([scene(0, natSound=True), scene(1, openClip=True), scene(2, aiFill=True), scene(3, src="b")])
        seen = []
        stormgate.scan_shots(d, {}, frames=lambda s: seen.append(s["id"]) or [1], check=lambda _f: "")
        self.assertEqual(seen, ["s3"])

    def test_a_shot_nothing_can_replace_keeps_its_picture_and_says_so(self):
        d = doc_of([scene(0, src="only")])
        with mock.patch.object(stormgate, "_rung_hold", return_value=0):
            rep = stormgate.autofix(d, {}, "", rounds=1, frames=lambda s: [1], check=lambda _f: "text in the frame", fill=lambda: None,
                                    reject=lambda *a: None)
        self.assertTrue(d["scenes"][0]["media"]["url"])
        self.assertTrue(d["scenes"][0]["reviewRequired"])
        self.assertEqual(len(rep["stillFlagged"]), 1)


class FaceScan(unittest.TestCase):
    def test_a_drawn_narrated_shot_with_a_face_is_replaced_pause_clips_left(self):
        d = doc_of([scene(0, src="a"), scene(1, src="b"), scene(2, src="c", natSound=True)])
        paths = ["a.mp4", "b.mp4", "c.mp4"]
        filled = []

        def fill():
            filled.append(1)
            d["scenes"][1]["media"] = {"type": "video", "url": "/tmp/new.mp4"}
        rows = stormgate.facescan(d, {}, paths, "", scan=lambda p: 0.02 if p == "b.mp4" else (0.5 if p == "c.mp4" else 0.0), fill=fill, reject=lambda *a: None)
        self.assertEqual([r.get("at") for r in rows], [3.0])
        self.assertEqual(filled, [1])
        self.assertEqual(d["scenes"][1]["media"]["url"], "/tmp/new.mp4")

    def test_report_only_changes_nothing(self):
        d = doc_of([scene(0, src="a")])
        before = json.dumps(d)
        rows = stormgate.facescan(d, {}, ["a.mp4"], "", scan=lambda p: 0.5, change=False, reject=lambda *a: self.fail("rejected"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.dumps(d), before)

    def test_piece_faces_reads_two_frames_a_second(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        p = os.path.join(t, "x.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=3", "-pix_fmt", "yuv420p", p], check=True)
        seen = []
        stormgate.piece_faces(p, face=lambda f: seen.append(f.shape) or 0.0)
        self.assertIn(len(seen), (6, 7))
        self.assertEqual(seen[0], (360, 640, 3))


class HookPicture(unittest.TestCase):
    def doc(self):
        d = doc_of([scene(0, n=150, src="hook", openClip=True, natSound=True)])
        d["scenes"][0]["media"].update(trimStart=2.0, clipSeconds=19.0)
        return d

    def test_a_promo_picture_moves_and_the_voice_stays(self):
        d = self.doc()
        rows = stormgate.hook_pictures(d, frames_at=lambda s, at: at, reason=lambda at: "a QR code" if at < 3.5 else "")
        m = d["scenes"][0]["media"]
        self.assertEqual(rows[0]["why"], "a QR code")
        self.assertEqual(m["audioIn"], 2.0)
        self.assertGreaterEqual(m["trimStart"], 3.5)
        self.assertEqual(stormdesk.moment(d["scenes"][0], FPS)[1], 10.0 + m["trimStart"])     # the ledger records the picture shown

    def test_a_clean_picture_is_left_alone(self):
        d = self.doc()
        self.assertEqual(stormgate.hook_pictures(d, frames_at=lambda s, at: at, reason=lambda at: ""), [])
        self.assertNotIn("audioIn", d["scenes"][0]["media"])

    def test_no_clean_stretch_marks_it_for_review(self):
        d = self.doc()
        rows = stormgate.hook_pictures(d, frames_at=lambda s, at: at, reason=lambda at: "big text")
        self.assertFalse(rows[0]["clean"])
        self.assertTrue(d["scenes"][0]["reviewRequired"])
        self.assertNotIn("audioIn", d["scenes"][0]["media"])

    def test_promo_reason(self):
        f = [frame()]
        none = {"ocr": lambda _f: [], "qr": lambda _f: False, "logo": lambda _f: False}
        self.assertEqual(stormgate.promo_reason(f, **none), "")
        self.assertEqual(stormgate.promo_reason(f, **{**none, "qr": lambda _f: True}), "a QR code")
        self.assertIn("logo", stormgate.promo_reason(f, **{**none, "logo": lambda _f: True}))
        self.assertIn("big text", stormgate.promo_reason(f, **{**none, "ocr": lambda _f: [([[0, 0], [100, 0], [100, 40], [0, 40]], "SUBSCRIBE", 0.9)]}))

    def test_a_flat_card_counts_as_a_logo(self):
        fr = frame((10, 10, 10))
        fr[80:100, 150:170] = (255, 255, 255)
        with mock.patch("src.localvision.available", return_value=False):
            self.assertTrue(stormgate._logo_card(fr))
            noisy = np.random.default_rng(3).integers(0, 255, (180, 320, 3), np.uint8)
            self.assertFalse(stormgate._logo_card(noisy))


class PlaceGuard(unittest.TestCase):
    def test_the_storys_places(self):
        rx = stormdesk.place_regex({}, {"places": ["Lake Mead, NV", "Hoover Dam"]})
        for t in ("Lake Mead water level drops", "Boaters at Mead", "HOOVER DAM report"):
            self.assertTrue(stormdesk.place_ok(t, rx), t)
        for t in ("Lake Powell houseboats", "Grand Canyon rafting", "Boat ramp at Meadview? no: Meadows"):
            self.assertFalse(stormdesk.place_ok(t, rx), t)

    def test_no_place_nothing_to_guard_and_an_unknown_title_is_not_refused(self):
        self.assertIsNone(stormdesk.place_regex({}, {}))
        self.assertTrue(stormdesk.place_ok("anything", None))
        rx = stormdesk.place_regex({}, {"places": ["Montana"]})
        self.assertTrue(stormdesk.place_ok("", rx))

    def test_the_jobs_regex_wins(self):
        rx = stormdesk.place_regex({"storm_desk": {"place_regex": "mead|boulder"}}, {"places": ["Nowhere"]})
        self.assertTrue(rx.search("Boulder City"))
        self.assertFalse(rx.search("Nowhere"))
        self.assertTrue(stormdesk.place_regex({"storm_desk": {"place_regex": "("}}, {"places": ["Nowhere"]}).search("Nowhere"))


class ChannelRule(unittest.TestCase):
    def test_personality_banned_creator_two_station_cap_place_and_first_seconds(self):
        banned = sorted(stormlib.bad_sources())[0]
        sc = [scene(0, src="p", ch="Fuel For Travel"),                                # personality
              scene(1, src="c1", ch="Drone Dan"), scene(2, src="c2", ch="Drone Dan"),
              scene(3, src="c3", ch="Drone Dan"),                                     # creator's third
              scene(4, src="s1", ch="KSL News"), scene(5, src="s2", ch="KSL News"),
              scene(6, src="s3", ch="KSL News"),                                      # station cap 2
              scene(7, src="w", ch="KTNV News", title="Lake Powell"),                 # wrong place
              scene(8, src="h", ch="KTNV News", at=1.0),                              # a station's first seconds
              scene(9, src=banned, ch="KTNV News")]
        rows = stormdesk.mark_channels(doc_of(sc), place=stormdesk.place_regex({}, {"places": ["Lake Mead"]}), station_cap=2, strict=True)
        got = {r["shot"]: r["why"] for r in rows}
        self.assertIn("personality", got[0])
        self.assertIn("creator", got[3])
        self.assertNotIn(1, got)
        self.assertNotIn(2, got)
        self.assertIn("station", got[6])
        self.assertIn("another place", got[7])
        self.assertIn("first seconds", got[8])
        self.assertIn("banned", got[9])

    def test_a_shot_rejected_on_the_laptop_stays_rejected(self):
        bad = sorted(stormlib.bad_shots())[0]
        v, _, t = bad.partition("@")
        d = doc_of([scene(0, src=v, at=float(t))])
        self.assertIn("rejected", stormdesk.mark_channels(d, strict=True)[0]["why"])

    def test_station_cap_is_configurable(self):
        self.assertEqual(stormdesk.station_shots({}), config.STORM_STATION_SHOTS)
        self.assertEqual(stormdesk.station_shots({"station_shots": 9}), 9)
        self.assertEqual(stormdesk.station_shots({"station_shots": "x"}), config.STORM_STATION_SHOTS)


class TheEmptyShotLadder(unittest.TestCase):
    def doc(self):
        sc = [scene(0, src="a"), scene(1, src="b"), scene(2, src="c")]
        sc[1]["media"] = {}
        return doc_of(sc)

    def rungs(self, log, fills):
        d = {}

        def rung(name):
            def run():
                log.append(name)
                return fills.get(name, lambda: 0)()
            return run
        for name in ("spare", "library", "originals", "ai", "hold"):
            d[name] = rung(name)
        return d

    def test_the_order_and_a_hold_only_last(self):
        d, log = self.doc(), []
        stormgate.ensure_media(d, {}, "", rungs=self.rungs(log, {}))
        self.assertEqual(log, ["spare", "library", "originals", "ai", "hold"])

    def test_it_stops_at_the_first_rung_that_fills(self):
        d, log = self.doc(), []

        def lib():
            d["scenes"][1]["media"] = {"type": "video", "url": "/x.mp4"}
            return 1
        rep = stormgate.ensure_media(d, {}, "", rungs=self.rungs(log, {"library": lib}))
        self.assertEqual(log, ["spare", "library"])
        self.assertEqual((rep["library"], rep["left"]), (1, 0))

    def test_no_hold_when_not_allowed(self):
        d, log = self.doc(), []
        stormgate.ensure_media(d, {}, "", allow_hold=False, rungs=self.rungs(log, {}))
        self.assertNotIn("hold", log)

    def test_a_rung_that_breaks_never_stops_the_next(self):
        d, log = self.doc(), []

        def boom():
            raise RuntimeError("no")
        rep = stormgate.ensure_media(d, {}, "", rungs=self.rungs(log, {"spare": boom}))
        self.assertIn("library", log)
        self.assertTrue(rep["errors"])

    def test_nothing_to_do_runs_nothing(self):
        d = doc_of([scene(0)])
        self.assertEqual(stormgate.ensure_media(d, {}, "", rungs={"spare": lambda: self.fail("ran")}), {"before": 0, "left": 0})

    def test_a_build_with_an_empty_shot_fails_clearly(self):
        d = self.doc()
        with self.assertRaises(stormgate.EmptyShots) as e:
            stormgate.assert_no_empty(d, "plan")
        self.assertEqual(e.exception.code, "empty_shots")
        self.assertEqual(e.exception.shots[0]["at"], 3.0)
        self.assertTrue(str(e.exception).startswith("empty_shots: 1 shot(s)"))

    def test_a_text_card_and_a_colour_count_as_empty(self):
        for media in ({"type": "animation", "url": ""}, {"type": "animation", "url": "x", "animation": "text"},
                      {"type": "color", "url": ""}, {"type": "video", "url": " "}, {}, None):
            d = doc_of([scene(0)])
            d["scenes"][0]["media"] = media
            with self.assertRaises(stormgate.EmptyShots):
                stormgate.assert_no_empty(d)
        stormgate.assert_no_empty(doc_of([scene(0)]))           # real media: fine

    def test_the_real_rungs_hold_the_previous_shot_last(self):
        """No spare, no library, no originals, no AI: the shot before holds over the empty one; nothing is left empty."""
        d = self.doc()
        d["scenes"][0]["media"]["clipSeconds"] = 60.0
        inp = {"storm_desk": {"ai_fill_empty": False}}
        with mock.patch.object(stormdesk, "_spare_pool", return_value=[]), mock.patch.object(stormlib, "load", return_value=None):
            rep = stormgate.ensure_media(d, inp, tempfile.gettempdir())
        self.assertEqual(rep["left"], 0)
        self.assertEqual(rep["hold"], 1)
        self.assertEqual(len(d["scenes"]), 2)
        self.assertTrue(d["scenes"][0]["heldOver"])

    def test_with_nothing_at_all_it_stays_empty_and_the_assert_fails(self):
        d = doc_of([scene(0)])
        d["scenes"][0]["media"] = {}
        inp = {"storm_desk": {"ai_fill_empty": False}}
        with mock.patch.object(stormdesk, "_spare_pool", return_value=[]), mock.patch.object(stormlib, "load", return_value=None):
            rep = stormgate.ensure_media(d, inp, tempfile.gettempdir())
        self.assertEqual(rep["left"], 1)
        with self.assertRaises(stormgate.EmptyShots):
            stormgate.assert_no_empty(d, "plan")

    def test_ai_rung_makes_the_styles_own_block_only_when_the_job_has_none(self):
        d = self.doc()
        started = []

        def fill_doc(doc, **kw):
            for s in kw["only"]:
                s["media"] = {"type": "image", "url": "/ai.jpg"}
                s["aiFill"] = True
            return {}
        with mock.patch("src.aifill.enabled", side_effect=[False, True]), mock.patch("src.aifill.start", side_effect=lambda inp, **k: started.append(inp["ai_fill"])), \
                mock.patch("src.aifill.set_story"), mock.patch("src.aifill.fill_doc", side_effect=fill_doc):
            n = stormgate._rung_ai(d, {"project_id": "p"}, "")
        self.assertEqual(n, 1)
        self.assertEqual(started[0]["provider"], "avatarity")
        self.assertTrue(started[0]["openrouter_fallback"])
        self.assertEqual(started[0]["max_clips"], 0)

    def test_the_old_paths_never_hold_or_card_on_this_engine(self):
        d = doc_of([scene(0, src="a"), scene(1, src="b")])
        d["scenes"][1]["media"] = {}
        self.assertEqual(gapfill.hold_or_animate(d)["held"], 0)
        self.assertEqual(d["scenes"][1]["media"], {})
        from src import quality
        g = quality.Gate.__new__(quality.Gate)
        g.doc, g.fixed = d, {"held": 0}
        self.assertEqual(g.no_empty_scenes(), [])
        self.assertEqual(d["scenes"][1]["media"], {})

    def test_no_card_in_a_pieces_spec_path(self):
        # What supported() would have drawn as a card now never reaches it: the ladder or the failure comes first.
        d = doc_of([scene(0)])
        d["scenes"][0]["media"] = {"type": "animation"}
        self.assertTrue(stormgate.empty_scenes(d))


class BotCheck(unittest.TestCase):
    def setUp(self):
        ytdlp.set_bot_fast(True)
        self.addCleanup(ytdlp.set_bot_fast, False)

    def test_a_bot_check_is_final_and_three_in_a_row_stop_downloads(self):
        self.assertTrue(ytdlp.note_bot_result("a", True))
        self.assertFalse(ytdlp.bot_stopped())
        self.assertFalse(ytdlp.note_bot_result("b", False))      # a success resets the streak
        for v in ("c", "d"):
            ytdlp.note_bot_result(v, True)
        self.assertFalse(ytdlp.bot_stopped())
        ytdlp.note_bot_result("e", True)
        self.assertTrue(ytdlp.bot_stopped())
        self.assertEqual(ytdlp.bot_report(), {"botChecks": 4, "skipped": 4, "stopped": True})

    def test_another_style_keeps_its_retries(self):
        ytdlp.set_bot_fast(False)
        self.assertFalse(ytdlp.note_bot_result("a", True))
        self.assertFalse(ytdlp.bot_stopped())

    def _refusing(self, argv, **kw):
        self.calls += 1
        return subprocess.CompletedProcess(argv, 1, "", "ERROR: [youtube] xx: Sign in to confirm you're not a bot")

    def test_the_bank_tries_a_bot_checked_source_once(self):
        from src import config as cfg
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        self.calls = 0
        src = srcbank.Source(id="AAAAAAAAAAA", duration=100.0)
        with mock.patch("subprocess.run", side_effect=self._refusing), mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                mock.patch.object(ytdlp, "_release_proxy"), mock.patch.object(ytdlp, "_client_args", return_value=[]):
            self.assertEqual(srcbank.download(src, t), "")
        self.assertEqual(self.calls, 1)
        self.assertEqual(ytdlp.bot_report()["botChecks"], 1)

    def test_the_section_fetch_is_not_retried_by_the_ladder(self):
        self.calls = 0
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        with mock.patch("subprocess.run", side_effect=self._refusing), mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                mock.patch.object(ytdlp, "_release_proxy"), mock.patch.object(ytdlp, "_client_args", return_value=[]):
            self.assertEqual(stormdesk._default_fetch("yt:BBBBBBBBBBB", 0.0, 5.0, t), "")
        self.assertEqual(self.calls, 1)

    def test_no_search_or_metadata_call_once_stopped(self):
        for v in ("a", "b", "c"):
            ytdlp.note_bot_result(v, True)
        with mock.patch("subprocess.run", side_effect=AssertionError("called YouTube")):
            self.assertEqual(ytdlp._yt_candidates("ytsearch5:flood", False), [])
            self.assertEqual(ytdlp._yt_info("EEEEEEEEEEE"), ({}, None))

    def test_no_download_starts_once_stopped(self):
        for v in ("a", "b", "c"):
            ytdlp.note_bot_result(v, True)
        self.calls = 0
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        with mock.patch("subprocess.run", side_effect=self._refusing):
            self.assertEqual(ytdlp._yt_fetch("CCCCCCCCCCC", t, 0.0, 5.0), "")
            self.assertEqual(srcbank.download(srcbank.Source(id="DDDDDDDDDDD", duration=9.0), t), "")
        self.assertEqual(self.calls, 0)


class FakeR2:
    """The ledger's and the library's objects in a dict."""

    def __init__(self):
        self.objects = {}

    def enabled(self):
        return True

    def get_bytes(self, key, bucket="", timeout=60):
        return self.objects.get(key)

    def upload_bytes(self, data, key, content_type="", deadline=0.0, bucket="", base="", cache_control=""):
        self.objects[key] = data
        return "https://x/" + key

    def list_keys(self, prefix="", bucket="", limit=10000):
        return [{"key": k, "size": len(v)} for k, v in self.objects.items() if k.startswith(prefix)]

    def delete(self, key, bucket=""):
        self.objects.pop(key, None)
        return True


class LedgerHolds(unittest.TestCase):
    def setUp(self):
        self.r2 = FakeR2()
        p = mock.patch.dict("sys.modules", {})
        p.start()
        self.addCleanup(p.stop)
        patcher = mock.patch("src.r2.enabled", self.r2.enabled), mock.patch("src.r2.get_bytes", self.r2.get_bytes), \
            mock.patch("src.r2.upload_bytes", self.r2.upload_bytes), mock.patch("src.r2.list_keys", self.r2.list_keys), mock.patch("src.r2.delete", self.r2.delete)
        for x in patcher:
            x.start()
            self.addCleanup(x.stop)
        self.inp = {"project_id": "p1", "storm_desk": {"ledger_owner": "owner"}}

    def test_a_video_being_made_blocks_its_moments_for_the_others(self):
        self.assertTrue(stormledger.hold(self.inp, [("yt:AAAAAAAAAAA", 10.0, 15.0, 0)]))
        other = stormledger.load({"project_id": "p2", "storm_desk": {"ledger_owner": "owner"}})
        self.assertTrue(other.used("AAAAAAAAAAA", 11.0, 14.0))
        self.assertFalse(other.moments)                     # blocked, never written back as used
        self.assertFalse(stormledger.load(self.inp).used("AAAAAAAAAAA", 11.0, 14.0))     # its own moments are not a reuse
        other.add([("BBBBBBBBBBB", 1.0, 2.0)])
        self.assertTrue(stormledger.save({"project_id": "p2", "storm_desk": {"ledger_owner": "owner"}}, other))
        saved = json.loads(self.r2.objects[stormledger.key_for("owner")])["moments"]
        self.assertEqual([m[0] for m in saved], ["BBBBBBBBBBB"])

    def test_an_old_hold_lets_go(self):
        stormledger.hold(self.inp, [("yt:AAAAAAAAAAA", 10.0, 15.0, 0)])
        key = next(k for k in self.r2.objects if ".holds/" in k)
        data = json.loads(self.r2.objects[key])
        data["at"] = 1
        self.r2.objects[key] = json.dumps(data).encode()
        self.assertFalse(stormledger.load({"project_id": "p2", "storm_desk": {"ledger_owner": "owner"}}).used("AAAAAAAAAAA", 11.0, 14.0))
        self.assertNotIn(key, self.r2.objects)

    def test_two_pods_finishing_together_keep_both(self):
        a = stormledger.load({"project_id": "a", "storm_desk": {"ledger_owner": "owner"}})
        b = stormledger.load({"project_id": "b", "storm_desk": {"ledger_owner": "owner"}})
        a.add([("AAAAAAAAAAA", 1.0, 2.0)])
        b.add([("BBBBBBBBBBB", 1.0, 2.0)])
        stormledger.save({"project_id": "a", "storm_desk": {"ledger_owner": "owner"}}, a)
        stormledger.save({"project_id": "b", "storm_desk": {"ledger_owner": "owner"}}, b)
        saved = json.loads(self.r2.objects[stormledger.key_for("owner")])["moments"]
        self.assertEqual(sorted(m[0] for m in saved), ["AAAAAAAAAAA", "BBBBBBBBBBB"])

    def test_a_rerender_replaces_only_its_own_moments(self):
        inp = {"project_id": "a", "storm_desk": {"ledger_owner": "owner"}}
        led = stormledger.load(inp)
        led.add([("AAAAAAAAAAA", 1.0, 2.0)])
        stormledger.save(inp, led)
        led = stormledger.load(inp)
        led.add([("CCCCCCCCCCC", 1.0, 2.0)])
        stormledger.save(inp, led)
        saved = json.loads(self.r2.objects[stormledger.key_for("owner")])["moments"]
        self.assertEqual([m[0] for m in saved], ["CCCCCCCCCCC"])


class TheBatch(unittest.TestCase):
    def run_batch(self, jobs, build, **extra):
        with mock.patch.object(batch, "record", return_value=True), mock.patch.object(storage_mod(), "patch_project", return_value=True):
            return batch.run({"id": "b1", "input": {"action": "batch", "jobs": jobs, **extra}}, build)

    def test_one_failed_video_never_stops_the_others_and_each_has_its_status(self):
        def build(job):
            pid = job["input"]["project_id"]
            if pid == "p2":
                return {"ok": False, "error": "empty_shots: 2 shot(s)", "error_code": "empty_shots", "empty_shots": [{"at": 3.0}, {"at": 9.0}]}
            if pid == "p3":
                raise RuntimeError("the machine fell over")
            return {"ok": True, "video_url": f"https://v/{pid}.mp4", "duration": 600.0, "costs": {"total": 1.25}}
        out = self.run_batch([{"project_id": f"p{k}", "video_style": "storm_desk", "title": f"T{k}"} for k in range(1, 5)], build)
        self.assertFalse(out["ok"])
        self.assertEqual([v["status"] for v in out["videos"]], ["done", "failed", "failed", "done"])
        self.assertEqual(out["videos"][1]["error_code"], "empty_shots")
        self.assertEqual(out["videos"][0]["video_url"], "https://v/p1.mp4")
        self.assertEqual(out["videos"][3]["title"], "T4")
        self.assertEqual(out["failed"][0]["empty_shots"][0]["at"], 3.0)
        self.assertEqual(batch.UNFINISHED, [])

    def test_videos_left_by_the_clock_say_not_started(self):
        def build(job):
            return {"ok": True, "video_url": "u", "duration": 1.0}
        with mock.patch.object(batch, "_give_up", return_value={}):
            out = self.run_batch([{"project_id": "p1"}, {"project_id": "p2"}], build, time_limit_seconds=100)
        self.assertEqual([v["status"] for v in out["videos"]], ["done", "not_started"])

    def _broker_says(self, refused):
        from src import storage
        asked = []

        def broker(payload, timeout=60):
            asked.append(payload["project_id"])
            if payload["project_id"] in refused:
                raise storage.StorageError("storage broker refused (403): job is not running for this project")
            return {"ok": True}
        return mock.patch.object(storage, "broker_enabled", return_value=True), mock.patch.object(storage, "_broker", side_effect=broker), asked

    def test_a_video_taken_out_of_the_batch_is_skipped_the_rest_go_on(self):
        built = []

        def build(job):
            built.append(job["input"]["project_id"])
            return {"ok": True, "video_url": "u", "duration": 1.0}
        on, br, _asked = self._broker_says({"p2"})
        with on, br:
            out = self.run_batch([{"project_id": "p1"}, {"project_id": "p2"}, {"project_id": "p3"}], build)
        self.assertEqual(built, ["p1", "p3"])
        self.assertTrue(out["ok"])
        self.assertEqual([v["status"] for v in out["videos"]], ["done", "skipped", "done"])
        self.assertEqual(out["skipped"][0]["project"], "p2")
        self.assertNotIn("unconfirmed", out["skipped"][0])

    def test_a_refusal_for_every_row_is_asked_again_before_skipping(self):
        # The broker answers the same while the app's database is down: nothing is skipped at once.
        on, br, asked = self._broker_says({"p1", "p2"})
        waits = []
        with on, br, mock.patch.object(batch, "CANCEL_CONFIRM_SECONDS", 0.0):
            self.assertEqual(batch.cancelled("p1", "job", ["p2"], "x", sleep=waits.append), (True, False))
        on, br, asked = self._broker_says({"p1"})
        with on, br:
            self.assertEqual(batch.cancelled("p1", "job", ["p2"], "x"), (True, True))

    def test_a_database_back_during_the_wait_builds_it(self):
        from src import storage
        answers = iter([storage.StorageError("storage broker refused (403): job is not running for this project"), {"ok": True}])

        def broker(payload, timeout=60):
            got = next(answers)
            if isinstance(got, Exception):
                raise got
            return got
        with mock.patch.object(storage, "broker_enabled", return_value=True), mock.patch.object(storage, "_broker", side_effect=broker):
            self.assertEqual(batch.cancelled("p1", "job", [], "x", sleep=lambda _s: None), (False, False))

    def test_a_network_failure_never_skips(self):
        from src import storage
        with mock.patch.object(storage, "broker_enabled", return_value=True), mock.patch.object(storage, "_broker", side_effect=OSError("net")):
            self.assertEqual(batch.cancelled("p1", "job", [], "x"), (False, False))

    def test_a_pods_limit_is_its_own(self):
        with mock.patch.dict(os.environ, {"POD_MAX_SECONDS": "18000"}):
            self.assertEqual(batch.time_limit({}), 17400.0)
            self.assertEqual(batch.time_limit({"time_limit_seconds": 500}), 500.0)
        with mock.patch.dict(os.environ, {"POD_MAX_SECONDS": "", "POD_EXIT": ""}):
            self.assertEqual(batch.time_limit({}), float(config.BATCH_TIME_LIMIT_SECONDS))

    def test_what_a_hung_pod_must_still_write(self):
        seen = []

        def build(job):
            seen.append(list(batch.UNFINISHED))
            return {"ok": True, "video_url": "u", "duration": 1.0}
        self.run_batch([{"project_id": "p1"}, {"project_id": "p2"}, {"project_id": "p3"}], build)
        self.assertEqual(seen[0], ["p1", "p2", "p3"])
        self.assertEqual(seen[2], ["p3"])


class ThroughTheHandler(unittest.TestCase):
    """The real dispatch (handler.handler, batch.run), plan and render stubbed."""

    def _run(self, inp, render):
        import handler
        doc = {"fps": 30, "scenes": [], "overlays": [], "meta": {"warnings": []}}
        with mock.patch.object(handler, "_require_ai_credit"), mock.patch.object(handler, "do_plan", side_effect=lambda *a, **k: dict(doc, meta={"warnings": []})), \
                mock.patch.object(handler, "do_render", side_effect=render), mock.patch.object(handler, "_keep_in_library"), \
                mock.patch.object(handler, "_storm_desk"), \
                mock.patch.object(handler.library, "record_shown"), mock.patch.object(handler.library, "start_maintenance"), \
                mock.patch.object(handler.storage, "patch_project", return_value=True), mock.patch.object(handler.ledger, "start_loading"), \
                mock.patch.object(handler.ledger, "save"), mock.patch.object(batch, "record", return_value=True):
            return handler.handler({"id": "rp-1", "input": inp})

    def test_an_empty_shot_fails_the_job_with_its_code_and_no_video(self):
        def render(*a, **k):
            raise stormgate.EmptyShots([{"id": "s1", "at": 3.0, "seconds": 4.0, "text": "x"}], "render")
        out = self._run({"action": "build", "project_id": "p1", "video_style": "storm_desk", "allow_youtube": False, "publish_media": False,
                         "_caller_writes_result": True}, render)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "empty_shots")
        self.assertEqual(out["empty_shots"][0]["at"], 3.0)
        self.assertNotIn("video_url", out)

    def test_a_batch_of_this_style_goes_on_after_a_failed_video_with_the_bot_rule_on_for_each(self):
        seen = []

        def render(doc, inp, *a, **k):
            seen.append((inp["project_id"], ytdlp.bot_fast()))
            if inp["project_id"] == "p1":
                raise stormgate.EmptyShots([{"at": 1.0}], "plan")
            return {"video_url": f"https://r2/{inp['project_id']}.mp4", "duration": 10.0, "object_path": "x"}
        entry = {"video_style": "storm_desk", "allow_youtube": False, "publish_media": False, "storm_desk": {"stat_style": "center"}}
        out = self._run({"action": "batch", "jobs": [{**entry, "project_id": "p1"}, {**entry, "project_id": "p2"}, {**entry, "project_id": "p3"}]}, render)
        self.assertEqual([v["status"] for v in out["videos"]], ["failed", "done", "done"])
        self.assertEqual(out["videos"][0]["error_code"], "empty_shots")
        self.assertEqual(seen, [("p1", True), ("p2", True), ("p3", True)])


def storage_mod():
    from src import storage
    return storage


if __name__ == "__main__":
    unittest.main()
