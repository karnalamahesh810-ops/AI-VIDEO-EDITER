"""The Breaking News Desk's free checks (2026-11-11): src/shotcheck.py (the kit's clean(), shared verdicts, framing by the
source's shape), the library's screen before a cut, the source bank's local review and CLIP matching, the style's switch
off of every paid judge, the new render modes, per-pause ambience beds and no music by default."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from src import config, shotcheck, srcbank, stormdesk, stormlib, stormpieces, styles


def _gray(v, w=640, h=360):
    return np.full((h, w, 3), v, np.uint8)


def _textured(w=640, h=360, seed=1):
    rng = np.random.default_rng(seed)
    return (rng.integers(40, 220, (h, w, 3))).astype(np.uint8)


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True, timeout=120)


NOFACE = dict(face=lambda im: 0.0, person=lambda im: 0.0, text=lambda im: "")


class FrameReasons(unittest.TestCase):
    def test_dark_frame(self):
        self.assertEqual(shotcheck.frame_reason(_gray(10), **NOFACE), "dark")

    def test_letterbox_bars(self):
        im = _textured()
        im[:30] = 0
        im[-30:] = 0
        self.assertEqual(shotcheck.frame_reason(im, **NOFACE), "bars")

    def test_blurred_pillarbox(self):
        im = _textured()
        im[:, :90] = 120                    # flat (soft) sides, sharp middle
        im[:, -90:] = 120
        self.assertEqual(shotcheck.frame_reason(im, **NOFACE), "pillar")

    def test_clean_frame_then_face_person_text_in_that_order(self):
        im = _textured()
        self.assertEqual(shotcheck.frame_reason(im, **NOFACE), "")
        self.assertEqual(shotcheck.frame_reason(im, face=lambda _i: 0.002, person=lambda _i: 0.5, text=lambda _i: "text"), "face")
        self.assertEqual(shotcheck.frame_reason(im, face=lambda _i: 0.001, person=lambda _i: 0.05, text=lambda _i: "x"), "person")
        self.assertEqual(shotcheck.frame_reason(im, face=lambda _i: 0.0, person=lambda _i: 0.0, text=lambda _i: "text (KTNV)"),
                         "text (KTNV)")

    def test_person_detector_runs_on_this_machine(self):
        if shotcheck._person_session() is None:
            self.skipTest("onnxruntime missing")
        self.assertEqual(shotcheck.person_share(_gray(128)), 0.0)


class SharedVerdicts(unittest.TestCase):
    def setUp(self):
        shotcheck.reset()

    def tearDown(self):
        shotcheck.reset()

    def test_a_stretch_is_screened_once_and_the_shared_file_merges(self):
        store = {"raw": json.dumps({"v": {shotcheck.key("other", 1, 2, "full"): "face"}}).encode()}
        shotcheck.load(get=lambda: store["raw"])
        runs = []
        why = shotcheck.screen("yt:abc", "x.mp4", 10.0, 14.0, "full", run=lambda: runs.append(1) or "")
        again = shotcheck.screen("abc", "x.mp4", 10.0, 14.0, "full", run=lambda: runs.append(1) or "text")
        self.assertEqual((why, again, len(runs)), ("", "", 1))
        self.assertEqual(shotcheck.screen("other", "y.mp4", 1, 2, "full", run=lambda: "never"), "face")
        n = shotcheck.flush(put=lambda data: store.update(raw=data), get=lambda: store["raw"])
        self.assertEqual(n, 1)
        v = json.loads(store["raw"])["v"]
        self.assertEqual(v[shotcheck.key("abc", 10, 14, "full")], "")
        self.assertEqual(v[shotcheck.key("other", 1, 2, "full")], "face")
        self.assertEqual(shotcheck.report().get("cacheHits"), 2)

    def test_the_key_names_the_mode_and_version(self):
        self.assertEqual(shotcheck.key("yt:a", 1.04, 2.0, "news0.76@0.0"), "a@1.0-2.0@news0.76@0.0@v1")


class Framing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.square = os.path.join(cls.d, "sq.mp4")
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=480x360:rate=10:duration=12", "-pix_fmt", "yuv420p", cls.square)
        cls.boxed = os.path.join(cls.d, "box.mp4")
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x270:rate=10:duration=12", "-vf", "pad=640:480:0:105:black",
                 "-pix_fmt", "yuv420p", cls.boxed)
        cls.wide = os.path.join(cls.d, "wide.mp4")
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=10:duration=12", "-pix_fmt", "yuv420p", cls.wide)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_auto_frame_by_shape(self):
        self.assertEqual(shotcheck.auto_frame(self.square), "fit")
        self.assertTrue(shotcheck.auto_frame(self.boxed).startswith("rect:0.000,0.21"), shotcheck.auto_frame(self.boxed))
        self.assertEqual(shotcheck.auto_frame(self.wide), "")

    def test_new_modes_draw_a_full_frame(self):
        for mode, path in (("fit", self.square), ("rect:0,0.219,1,0.563", self.boxed), ("pillar1.0", self.wide)):
            w, h = stormpieces._probe_wh(path)
            out = os.path.join(self.d, "o.png")
            _ffmpeg("-ss", "1", "-i", path, "-frames:v", "1", "-vf", stormpieces.vf_for(mode, w, h), out)
            self.assertEqual(stormpieces._image_wh(out), (1920, 1080), mode)

    def test_rect_crop_removes_the_bars_the_check_would_refuse(self):
        w, h = stormpieces._probe_wh(self.boxed)
        raw = shotcheck.frames(self.boxed, 1.0, 1.0, stormpieces.vf_for("full", w, h), spots=(0.5,))[0]
        fixed = shotcheck.frames(self.boxed, 1.0, 1.0, stormpieces.vf_for(shotcheck.auto_frame(self.boxed), w, h), spots=(0.5,))[0]
        self.assertEqual(shotcheck.frame_reason(raw, **NOFACE), "bars")
        self.assertEqual(shotcheck.frame_reason(fixed, **NOFACE), "")

    def test_side_logo_on_fit_shots(self):
        doc = {"fps": 30, "scenes": [{"startFrame": 0, "durationInFrames": 30, "media": {"type": "video", "url": "a.mp4"},
                                      "stormDesk": {"mode": "fit"}}], "stormDesk": {"logo": {"text": "US"}}}
        layers = [tuple(x) for _n, key in stormpieces.scene_spec(doc, 0)["layers"] for x in key]
        self.assertIn(("side",), layers)
        doc["scenes"][0]["stormDesk"]["mode"] = "news0.76@0.0"
        layers = [tuple(x) for _n, key in stormpieces.scene_spec(doc, 0)["layers"] for x in key]
        self.assertNotIn(("side",), layers)


class LibraryPrescreen(unittest.TestCase):
    def test_a_refused_stretch_is_remembered_and_its_line_placed_again(self):
        p_bad = srcbank.Piece(src=0, n=1, start=10.0, end=16.0, take=1, ok=True)
        p_ok = srcbank.Piece(src=1, n=2, start=20.0, end=26.0, take=2, ok=True)
        srcs = [srcbank.Source(id="bad", channel="Someone", path="b.mp4"), srcbank.Source(id="good", channel="FOX 10 Phoenix", path="g.mp4")]
        plan = {3: (p_bad, 10.0, 14.0, 0.6), 4: (p_ok, 20.0, 24.0, 0.6)}
        seen = []

        def fake(vid, path, a, b, mode, run=None):
            seen.append((vid, mode))
            return "person" if vid == "bad" else ""
        with mock.patch.object(shotcheck, "screen", side_effect=fake), \
                mock.patch.object(stormlib, "remember_bad") as rb, mock.patch.object(stormlib, "station_modes", return_value={}):
            out = stormlib.prescreen(plan, srcs, None)
        self.assertEqual(out, [3])
        self.assertTrue(p_bad.bad)
        rb.assert_called_once_with("bad", 10.0, 16.0)
        self.assertEqual(dict(seen)["good"], "news0.76@0.0")       # a station is screened as its crop shows it


class BankWithoutAModel(unittest.TestCase):
    def test_local_review_screens_each_shot(self):
        src = srcbank.Source(id="v1", channel="Storm Chaser", path="v.mp4")
        src.pieces = [srcbank.Piece(src=0, n=k, start=k * 5.0, end=k * 5.0 + 4, take=k) for k in range(3)]
        verdicts = {0.0: "", 5.0: "text (BREAKING)", 10.0: "person"}
        with mock.patch.object(shotcheck, "screen", side_effect=lambda vid, path, a, b, mode: verdicts[a]), \
                mock.patch.object(srcbank, "_clip_reject"), mock.patch.object(stormlib, "station_modes", return_value={}), \
                mock.patch.object(stormlib, "AUTO_FRAME", False):
            self.assertTrue(srcbank.review_local(src))
        self.assertEqual([(p.ok, p.why) for p in src.pieces], [(True, ""), (False, "text"), (False, "people")])

    def test_clip_matching_ranks_by_cosine(self):
        from src import localvision
        a = np.array([1.0, 0.0], np.float32)
        b = np.array([0.0, 1.0], np.float32)
        pieces = [srcbank.Piece(src=0, n=1, start=0, end=4, take=1), srcbank.Piece(src=0, n=2, start=5, end=9, take=2)]
        pieces[0].vec, pieces[1].vec = a, b
        lines = [{"index": 7, "context": "flood", "place": "", "subject": ""}]
        with mock.patch.object(localvision, "available", return_value=True), \
                mock.patch.object(localvision, "embed_texts", return_value=np.array([[0.3, 0.1]], np.float32)):
            got = srcbank.match_local(lines, pieces)
        self.assertEqual([pid for pid, _f in got[7]], ["0.1", "0.2"])
        self.assertEqual(got[7][0][1], 1.0)
        self.assertEqual(got[7][1][1], 0.0)


class StyleSwitch(unittest.TestCase):
    def test_free_by_default_and_a_job_may_turn_it_off(self):
        with mock.patch.object(config, "STORM_FREE", True):
            inp = {"video_style": "storm_desk"}
            styles.apply(inp)
            self.assertEqual({k: inp["config"][k] for k in styles.FREE_CONFIG}, styles.FREE_CONFIG)
            inp = {"video_style": "storm_desk", "config": {"STORM_FREE": False}}
            styles.apply(inp)
            self.assertNotIn("VISION_ENABLED", inp["config"])
            inp = {"video_style": "storm_desk", "config": {"HOOK_CUT_CHECK": True}}
            styles.apply(inp)
            self.assertTrue(inp["config"]["HOOK_CUT_CHECK"])
            self.assertFalse(inp["config"]["VISION_ENABLED"])
            inp = {"video_style": "news"}
            styles.apply(inp)
            self.assertNotIn("VISION_ENABLED", inp.get("config") or {})

    def test_free_mode_turns_off_ai_pictures_for_empty_shots(self):
        from src import stormgate
        with mock.patch.object(config, "STORM_FREE", True), mock.patch.object(stormgate, "empty_scenes") as es:
            self.assertEqual(stormgate._rung_ai({"scenes": []}, {"storm_desk": {}}, "."), 0)
            es.assert_not_called()


class StretchRung(unittest.TestCase):
    def _doc(self):
        def shot(i, f0, start=None, **x):
            sc = {"id": f"s{i}", "startFrame": f0, "durationInFrames": 120, **x}
            if start is not None:
                sc["media"] = {"type": "video", "url": f"c{i}.mp4"}
                sc["semanticMetadata"] = {"sourceUrl": f"https://www.youtube.com/watch?v=AAAAAAAAAAA&t={start}",
                                          "moment": {"start": start}, "channel": "FOX 10 Phoenix"}
                sc["stormDesk"] = {"mode": "news0.76@0.0"}
            else:
                sc["media"] = {}
            return sc
        return {"fps": 30, "scenes": [shot(0, 0, 100.0), shot(1, 120), shot(2, 240, 300.0, natSound=True), shot(3, 360)]}

    def test_the_shot_before_runs_on_when_its_frames_pass(self):
        from src import stormgate
        doc = self._doc()
        checked = []
        with mock.patch.object(stormdesk, "_source_file", return_value="src.mp4"), mock.patch.object(stormdesk, "JOB_LEDGER", None):
            n = stormgate._rung_stretch(doc, check=lambda p, a, d, m: checked.append((a, d, m)) or "",
                                        cut=lambda p, a, d: f"cut_{a:.0f}.mp4")
        self.assertEqual(n, 1)                                       # shot 3 sits beside a pause clip only: left alone
        self.assertEqual(checked, [(104.0, 4.0, "news0.76@0.0")])
        s1 = doc["scenes"][1]
        self.assertEqual(s1["media"]["url"], "cut_104.mp4")
        self.assertEqual(s1["semanticMetadata"]["moment"]["start"], 104.0)
        self.assertEqual(s1["stormDesk"]["mode"], "news0.76@0.0")
        self.assertFalse(doc["scenes"][3]["media"])

    def test_refused_frames_or_a_used_moment_leave_it_empty(self):
        from src import stormgate, stormledger
        doc = self._doc()
        with mock.patch.object(stormdesk, "_source_file", return_value="src.mp4"), mock.patch.object(stormdesk, "JOB_LEDGER", None):
            self.assertEqual(stormgate._rung_stretch(doc, check=lambda *a: "person", cut=lambda *a: "x.mp4"), 0)
        led = stormledger.Ledger([["yt:AAAAAAAAAAA", 103.0, 109.0]])
        with mock.patch.object(stormdesk, "_source_file", return_value="src.mp4"), mock.patch.object(stormdesk, "JOB_LEDGER", led):
            self.assertEqual(stormgate._rung_stretch(doc, check=lambda *a: "", cut=lambda *a: "x.mp4"), 0)


class Sound(unittest.TestCase):
    def test_no_music_unless_asked(self):
        with mock.patch.object(stormdesk, "MUSIC_DEFAULT", False):
            self.assertFalse(stormdesk.music_wanted({}))
            self.assertFalse(stormdesk.music_wanted({"music": "auto"}))
            self.assertTrue(stormdesk.music_wanted({"music": True}))
        doc = {"stormDesk": {"noMusic": True, "music": [{"url": "https://x/a.mp3"}]}, "bgm": {"url": "https://x/b.mp3"}}
        self.assertEqual(stormpieces.music_sections(doc), [])
        doc["stormDesk"]["noMusic"] = False
        self.assertEqual(len(stormpieces.music_sections(doc)), 1)

    def test_amb_beds_on_pauses_whose_sound_is_not_nature(self):
        def pause(f0, kind, talk=False):
            return {"startFrame": f0, "durationInFrames": 180, "natSound": True, "talk": talk,
                    "media": {"type": "video", "url": "x.mp4", "clipAudio": {"kind": kind}}}
        doc = {"fps": 30, "scenes": [pause(0, "nature"), pause(900, "speech"), pause(1800, "speech", talk=True),
                                     pause(2700, "nature"), {"startFrame": 3000, "durationInFrames": 90}]}
        n = stormdesk.set_amb_beds(doc, {"amb_bed": "ocean_surf", "amb_beds": {"90": "volcano_rumble"}})
        beds = [(s.get("stormDesk") or {}).get("ambBed") for s in doc["scenes"]]
        self.assertEqual(n, 2)
        self.assertEqual(beds, [None, "ocean_surf", None, "volcano_rumble", None])

    def test_bed_files(self):
        self.assertEqual(stormdesk.amb_bed_file({}), "")
        self.assertEqual(stormdesk.amb_bed_file({"stormDesk": {"ambBed": True}}), stormdesk.WATER_FILE)
        self.assertEqual(stormdesk.amb_bed_file({"stormDesk": {"ambBed": "rushing_water"}}), stormdesk.WATER_FILE)
        self.assertEqual(stormdesk.amb_bed_file({"stormDesk": {"ambBed": "not_bundled"}}), stormdesk.WATER_FILE)
        self.assertEqual(stormdesk.amb_bed_file({"stormDesk": {"ambBed": "https://x/bed.mp3"}}, resolve=lambda u: "/tmp/bed.mp3"),
                         "/tmp/bed.mp3")


if __name__ == "__main__":
    unittest.main()
