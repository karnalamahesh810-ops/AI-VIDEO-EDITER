"""Breaking News Desk (video_style storm_desk), round 2 (2026-11-03): clip sound under the voice (src/clipaudio.py,
stormdesk.under_track / mix_check), the opening clip, scored pause clips, the sourcing rules (event day, field-footage
titles, channel share, Shorts searches, the parts' blocklist), the per-video logo, and the edit prompt for every
style. Offline: no network, small ffmpeg files only."""
import datetime
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import clipaudio, config, director, media, stormdesk, styles, vision
from src.transcribe import Word
from tests.test_stormdesk import FPS, HAVE_FFMPEG, SENTS, doc_of, make_clip, scene, words_of


_NO_NET = mock.patch.object(stormdesk, "_yt_meta", return_value={})


def setUpModule():
    _NO_NET.start()          # offline: a channel lookup never reaches YouTube


def tearDownModule():
    _NO_NET.stop()


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _np():
    import numpy as np
    return np


class ClipAudioTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_natural_music_silent_and_no_sound(self):
        d = tempfile.mkdtemp()
        try:
            noise = clipaudio.classify(make_clip(os.path.join(d, "n.mp4"), 5.0, sound="noise"), confirm=False)
            chord = clipaudio.classify(make_clip(os.path.join(d, "c.mp4"), 5.0, sound="chord"), confirm=False)
            quiet = clipaudio.classify(make_clip(os.path.join(d, "q.mp4"), 5.0, sound="noise", amp=0.0005),
                                       confirm=False)
            none = clipaudio.classify(make_clip(os.path.join(d, "x.mp4"), 3.0, audio=False))
            self.assertEqual(noise["kind"], "nature")
            self.assertEqual(chord["kind"], "music")
            self.assertEqual(quiet["kind"], "silent")
            self.assertEqual(none["kind"], "silent")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_speech_gate_and_whisper_confirm(self):
        np = _np()
        x = (np.random.RandomState(1).randn(16000 * 4) * 0.05).astype(np.float32)
        with mock.patch.object(clipaudio, "speech_share", return_value=0.8):
            self.assertEqual(clipaudio.classify("", x=x)["kind"], "speech")
        # Unsure voice activity: whisper decides (and is not asked when the share is clear).
        with mock.patch.object(clipaudio, "speech_share", return_value=0.2), \
                mock.patch.object(clipaudio, "whisper_says_speech", return_value=True) as w:
            self.assertEqual(clipaudio.classify("", x=x)["kind"], "speech")
            w.assert_called_once()
        with mock.patch.object(clipaudio, "speech_share", return_value=0.2), \
                mock.patch.object(clipaudio, "whisper_says_speech", return_value=False):
            self.assertEqual(clipaudio.classify("", x=x)["kind"], "nature")
        with mock.patch.object(clipaudio, "speech_share", return_value=0.0), \
                mock.patch.object(clipaudio, "whisper_says_speech") as w:
            clipaudio.classify("", x=x)
            w.assert_not_called()

    def test_classify_never_raises(self):
        with mock.patch.object(clipaudio, "read_mono", side_effect=RuntimeError("boom")):
            self.assertEqual(clipaudio.classify("x.mp4")["kind"], "unknown")

    def test_soundtrack_title_lowers_the_bar(self):
        self.assertTrue(clipaudio._MUSIC_TITLE.search("Hoover Dam - by drone [4K]"))
        self.assertFalse(clipaudio._MUSIC_TITLE.search("Flood waters rush through Henderson wash"))

    def test_plays_under_voice_rules(self):
        def sc(kind, **kw):
            return {"media": {"type": "video", "clipAudio": {"kind": kind}}, **kw}
        self.assertTrue(clipaudio.plays_under_voice(sc("nature"), "ambient"))
        for k in ("speech", "music", "silent", "unknown"):
            self.assertFalse(clipaudio.plays_under_voice(sc(k), "ambient"), k)
        self.assertFalse(clipaudio.plays_under_voice(sc("nature"), "off"))
        # The editor's per-clip switch wins either way; a pause is never a narration shot.
        self.assertTrue(clipaudio.plays_under_voice(sc("music", clipSound=True), "ambient"))
        self.assertTrue(clipaudio.plays_under_voice(sc("speech", clipSound=True), "off"))
        self.assertFalse(clipaudio.plays_under_voice(sc("nature", clipSound=False), "ambient"))
        self.assertFalse(clipaudio.plays_under_voice(sc("nature", natSound=True), "ambient"))


class UnderVoiceTests(unittest.TestCase):
    def test_gain_math(self):
        g = stormdesk.under_gain(-30.0, -20.0, 20.0)          # wants -40: 10 dB down
        self.assertAlmostEqual(g, 10 ** (-10 / 20.0), places=6)
        self.assertAlmostEqual(stormdesk.under_gain(-70.0, -20.0, 20.0), 10 ** (12 / 20.0), places=6)  # capped lift

    def _doc(self, mode="ambient", kinds=("nature", "speech", "music"), own=None):
        sc = []
        for i, k in enumerate(kinds):
            s = scene(i, i * 2, i * 2 + 2, words=[{"text": "w", "start": i * 2 + 0.5, "end": i * 2 + 1.0}])
            s["media"]["clipAudio"] = {"kind": k}
            if own and i in own:
                s["clipSound"] = own[i]
            sc.append(s)
        doc = doc_of(sc)
        doc["stormDesk"] = {"clipSound": {"mode": mode, "underVoiceDb": 20.0, "duckDb": 6.0}}
        return doc

    def _reader(self, level_db=-20.0):
        np = _np()

        def read(src, at, secs):
            n = int(secs * 48000)
            x = np.random.RandomState(2).randn(n).astype(np.float32)
            x *= 10 ** (level_db / 20.0) / float(np.sqrt(np.mean(x ** 2)))
            return np.stack([x, x], axis=1)
        return read

    def test_only_natural_sound_plays_and_sits_20_db_under_then_ducks(self):
        np = _np()
        doc = self._doc()
        track, rows, talk = stormdesk.under_track(doc, 6.0, 0.0, -18.0, read=self._reader(-20.0))
        self.assertEqual([r["id"] for r in rows if r["ok"]], ["s0"])          # speech + music stay silent
        mono = track.mean(axis=1)

        def db(a, b):
            seg = mono[int(a * 48000):int(b * 48000)]
            return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        self.assertAlmostEqual(db(1.4, 1.8), -38.0, delta=1.0)                 # between words: voice - 20
        self.assertAlmostEqual(db(0.6, 0.9), -44.0, delta=1.0)                 # on a word: 6 dB lower
        self.assertLess(db(2.2, 5.8), -100.0)                                  # the other clips: nothing

    def test_editor_switches_reach_the_mix(self):
        doc = self._doc(mode="off", own={1: True})
        _t, rows, _ = stormdesk.under_track(doc, 6.0, 0.0, -18.0, read=self._reader())
        self.assertEqual([r["id"] for r in rows if r["ok"]], ["s1"])          # off, but the forced speech clip
        doc = self._doc(mode="ambient", own={0: False})
        _t, rows, _ = stormdesk.under_track(doc, 6.0, 0.0, -18.0, read=self._reader())
        self.assertEqual([r for r in rows if r["ok"]], [])

    def test_mix_check(self):
        np = _np()
        n = 48000 * 2
        voice = np.random.RandomState(3).randn(n).astype(np.float32) * 0.1
        talk = np.ones(n, np.float32)
        self.assertTrue(stormdesk.mix_check(voice, voice * 0.05, talk)["ok"])        # -26 dB
        self.assertFalse(stormdesk.mix_check(voice, voice * 0.5, talk)["ok"])        # -6 dB

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_after_render_mixes_natural_sound_under_the_voice_at_minus_14(self):
        d = tempfile.mkdtemp()
        try:
            rendered = os.path.join(d, "final.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=320x180:rate=30:duration=8", "-f", "lavfi", "-i",
                            "sine=frequency=180:sample_rate=48000:duration=8", "-c:v", "libx264", "-preset",
                            "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", rendered], check=True)
            nat = make_clip(os.path.join(d, "nat.mp4"), 8.0, sound="noise", amp=0.8)
            mus = make_clip(os.path.join(d, "mus.mp4"), 8.0, sound="chord", amp=0.8)
            words = [{"text": "w", "start": t, "end": t + 0.35} for t in (0.2, 0.7, 1.2, 4.2, 4.7, 5.2, 6.4)]
            doc = {"fps": FPS, "durationInFrames": 8 * FPS, "meta": {"stormDesk": {"pauses": []}},
                   "stormDesk": {"clipSound": {"mode": "ambient"}}, "scenes": [
                       {"id": "a", "startFrame": 0, "durationInFrames": 120, "words": words[:3],
                        "media": {"type": "video", "url": nat, "clipAudio": {"kind": "nature"}}},
                       {"id": "b", "startFrame": 120, "durationInFrames": 120, "words": words[3:],
                        "media": {"type": "video", "url": mus, "clipAudio": {"kind": "music"}}}]}
            rep = stormdesk.after_render(doc, rendered, d)
            self.assertEqual(rep["underVoice"]["clips"], 1)
            self.assertTrue(rep["mixCheck"]["ok"], rep["mixCheck"])
            self.assertLessEqual(rep["mixCheck"]["underVoiceDb"], -stormdesk.MIX_MARGIN_DB)
            self.assertAlmostEqual(rep["lufs"], -14.0, delta=1.0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class OpeningClipTests(unittest.TestCase):
    def setUp(self):
        self.words = words_of(SENTS * 3, wps=2.6)

    def test_open_clip_first_by_default_and_its_switch(self):
        end = self.words[-1].end
        ps = stormdesk.plan_pauses(self.words, end)
        self.assertTrue(ps[0].get("open"))
        self.assertEqual((ps[0]["at"], ps[0]["secs"]), (0.0, stormdesk.OPEN_SECONDS))
        self.assertTrue(all(not p.get("open") for p in ps[1:]) and len(ps) >= 2)       # the middle pauses stay
        self.assertFalse(any(p.get("open") for p in stormdesk.plan_pauses(self.words, end, {"open_clip": False})))
        short = stormdesk.plan_pauses(self.words, end, {"open_seconds": 2})
        self.assertEqual(short[0]["secs"], stormdesk.OPEN_MIN)                        # 4-7 s
        self.assertEqual(stormdesk.out_pauses(ps)[0]["t0"], 0.0)
        self.assertTrue(stormdesk.out_pauses(ps)[0].get("open"))
        # Every word moves by the opening's seconds.
        sw = stormdesk.shift_words(self.words[:3], ps[:1])
        self.assertAlmostEqual(sw[0].start, self.words[0].start + stormdesk.OPEN_SECONDS)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_pad_narration_opens_with_silence(self):
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "n.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=300:sample_rate=48000:duration=4", src], check=True)
            out = stormdesk.pad_narration(src, [{"at": 0.0, "secs": 6.0}, {"at": 2.0, "secs": 3.0}],
                                          os.path.join(d, "p.wav"))
            self.assertAlmostEqual(stormdesk._probe(out)["duration"], 13.0, delta=0.05)
            self.assertLess(float(abs(stormdesk._read_audio(out, 0.2, 5.5, 48000)).max()), 1e-3)
            self.assertGreater(float(abs(stormdesk._read_audio(out, 6.3, 1.0, 48000)).max()), 0.05)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_opening_scene_is_the_best_scored_clip_and_music_is_turned_down(self):
        d = tempfile.mkdtemp()
        try:
            loud = make_clip(os.path.join(d, "loud.mp4"), 10.0, sound="noise", amp=0.9)
            soft = make_clip(os.path.join(d, "soft.mp4"), 10.0, sound="noise", amp=0.02)
            song = make_clip(os.path.join(d, "song.mp4"), 10.0, sound="chord", amp=0.9)
            sc = [scene(0, 0, 4, "AAAAAAAAAAA", "Chan A", 10), scene(1, 4, 8, "BBBBBBBBBBB", "Chan B", 200),
                  scene(2, 8, 12, "CCCCCCCCCCC", "Chan C", 300), scene(3, 12, 16, "DDDDDDDDDDD", "Chan D", 70)]
            files = {"yt:BBBBBBBBBBB": song, "yt:CCCCCCCCCCC": soft, "yt:DDDDDDDDDDD": loud}
            doc = doc_of(sc)
            asked = []

            def fetch(video, start, seconds):
                asked.append(video)
                return files.get(video, "")
            rows = stormdesk.make_pauses(doc, [{"t0": 0.0, "t1": 6.0, "open": True}], d, fetch=fetch,
                                         check=lambda p: "")
            self.assertTrue(rows[0].get("open"))
            first = doc["scenes"][0]
            self.assertTrue(first.get("openClip") and first.get("natSound"))
            self.assertEqual(first["startFrame"], 0)
            self.assertEqual(first["durationInFrames"], 6 * FPS)
            self.assertEqual(rows[0]["video"], "yt:DDDDDDDDDDD")                     # the loudest natural sound
            self.assertNotIn("yt:BBBBBBBBBBB", [c["video"] for c in rows[0]["candidates"]])   # music: never
            self.assertEqual(first["media"]["clipAudio"]["kind"], "nature")
            self.assertGreaterEqual(first["media"]["trimStart"], 0.0)
            # Contiguous after it.
            for a, b in zip(doc["scenes"], doc["scenes"][1:]):
                self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class FinishAudioTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_every_shot_keeps_its_sound_class_and_the_mode(self):
        d = tempfile.mkdtemp()
        try:
            nat = make_clip(os.path.join(d, "a.mp4"), 6.0, sound="noise")
            mus = make_clip(os.path.join(d, "b.mp4"), 6.0, sound="chord")
            sc = [scene(0, 0, 4, "AAAAAAAAAAA", "Chan A", 10, words=[{"text": "Flood.", "start": 0.5, "end": 1}]),
                  scene(1, 4, 8, "BBBBBBBBBBB", "Chan B", 50, words=[{"text": "Rain.", "start": 4.5, "end": 5}])]
            sc[0]["media"]["url"], sc[1]["media"]["url"] = nat, mus
            doc = doc_of(sc)
            inp = {"video_style": "storm_desk", "storm_desk": {"open_clip": False, "pauses": 0,
                                                               "lookalike": False, "blur_marks": False}}
            with mock.patch.object(clipaudio, "whisper_says_speech", return_value=None):
                rep = stormdesk.finish(doc, inp, {}, d)
            kinds = [s["media"].get("clipAudio", {}).get("kind") for s in doc["scenes"]]
            self.assertEqual(kinds, ["nature", "music"])
            self.assertEqual(doc["stormDesk"]["clipSound"]["mode"], "ambient")
            self.assertEqual(rep["clipSound"]["underVoice"], 1)
            doc2 = doc_of([dict(s) for s in sc])
            stormdesk.finish(doc2, {**inp, "storm_desk": {**inp["storm_desk"], "clip_sound": "off"}}, {}, d)
            self.assertEqual(doc2["stormDesk"]["clipSound"]["mode"], "off")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_options(self):
        self.assertEqual(stormdesk.clip_sound_mode({}), "ambient")
        self.assertEqual(stormdesk.clip_sound_mode({"clip_sound": "off"}), "off")
        self.assertEqual(stormdesk.clip_sound_mode({"clip_sound": False}), "off")
        self.assertTrue(stormdesk.open_clip_on({}))
        self.assertFalse(stormdesk.open_clip_on({"open_clip": False}))


class LogoTests(unittest.TestCase):
    def test_per_video_logo_reaches_the_graphics_props(self):
        doc = doc_of([scene(0, 0, 30, "AAAAAAAAAAA", "A", 10)])
        kit = {"watermark": {"url": "https://kit/logo.png"}, "name": "Kit"}
        inp = {"video_style": "storm_desk", "storm_desk": {"logo_url": "https://cdn/own.png",
                                                           "channel_name": "Daily Brief"}}
        g = stormdesk.graphics(doc, inp, [], {}, kit, None)
        self.assertEqual(g["logo"], {"url": "https://cdn/own.png", "text": "Daily Brief"})
        g2 = stormdesk.graphics(doc, {"video_style": "storm_desk"}, [], {}, kit, None)
        self.assertEqual(g2["logo"]["url"], "https://kit/logo.png")              # the kit's logo by default
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remotion", "src")
        comp = _read(os.path.join(root, "components", "brand", "StormDesk.tsx"))
        main = _read(os.path.join(root, "Main.tsx"))
        self.assertIn("desk.logo?.url", comp)                       # the bug and the lower thirds draw it
        self.assertIn("<StormDesk desk={props.stormDesk}", main)
        types = _read(os.path.join(root, "types.ts"))
        self.assertIn("clipSound?: { mode:", types)
        self.assertIn("clipAudio?:", types)


class SourcingTests(unittest.TestCase):
    def tearDown(self):
        media.set_event_day(None)

    def test_event_day_from_the_job_or_a_recent_narrated_date(self):
        today = datetime.date(2026, 11, 3)
        inp = {"video_style": "storm_desk"}
        ws = [Word(t, 0, 0) for t in "On November 1 a wall of water hit Henderson".split()]
        self.assertEqual(stormdesk.event_day_for(inp, ws, today), datetime.date(2026, 11, 1))
        old = [Word(t, 0, 0) for t in "Back on July 4, 1983 the dam overflowed".split()]
        self.assertIsNone(stormdesk.event_day_for(inp, old, today))
        months = [Word(t, 0, 0) for t in "On March 3 the river rose".split()]
        self.assertIsNone(stormdesk.event_day_for(inp, months, today))                 # not recent
        own = {"video_style": "storm_desk", "storm_desk": {"event_date": "2026-10-30"}}
        self.assertEqual(stormdesk.event_day_for(own, old, today), datetime.date(2026, 10, 30))

    def test_older_uploads_are_turned_down_for_event_lines_only(self):
        brief = {"kind": "news", "year": 2026}
        with mock.patch.object(media, "_story_blob", return_value=(brief, "")), \
                mock.patch.object(media, "_event_story", return_value=True):
            media.set_event_day("2026-11-01")
            self.assertIn("before the event", media.upload_conflict({"upload_date": "20261020", "title": "x"}))
            self.assertEqual(media.upload_conflict({"upload_date": "20261031", "title": "x"}), "")   # a day's grace
            self.assertEqual(media.upload_conflict({"upload_date": "20261102", "title": "x"}), "")
            # A place shot may be older (it gets the ARCHIVE label on screen).
            tok = media._SCENE_INTENT.set({"specificity": "place"})
            try:
                self.assertEqual(media.upload_conflict({"upload_date": "20250101", "title": "x"}), "")
            finally:
                media._SCENE_INTENT.reset(tok)
            media.set_event_day(None)
            self.assertEqual(media.upload_conflict({"upload_date": "20261020", "title": "x"}), "")

    def test_field_footage_titles(self):
        with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", True), mock.patch.object(config, "NEWS_FOOTAGE", True):
            for t in ("Sheriff says roads closed after flood | press conference", "Meteorologist explains the storm",
                      "Interview with flood survivor", "Mayor speaks on wildfire damage"):
                self.assertTrue(media._talking_head(t, "the mayor held a press conference"), t)
            for t in ("[RAW VIDEO] Heavy flood waters move through Henderson | KTNV News",
                      "Drone video shows wildfire damage in Maui", "Crowd runs as crane collapses downtown"):
                self.assertFalse(media._talking_head(t), t)
        with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", False), mock.patch.object(config, "NEWS_FOOTAGE", True):
            self.assertFalse(media._talking_head("Sheriff press conference on the flood", "press conference"))

    def test_channel_share_cap(self):
        def asset(i, ch):
            return media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=V{i:010d}&t=5",
                                    local_path="", channel=ch)
        jobs = [{"index": i, "seconds": 4.0, "start": i * 4.0} for i in range(40)]      # 160 s
        res = [asset(i, "Big Channel" if i % 2 == 0 else f"Other {i}") for i in range(40)]
        with mock.patch.object(config, "CHANNEL_MAX_SHARE", 0.07):
            out = media.variety_violations(jobs, res)
        capped = [i for i, (why, kind) in out.items() if "channel" in why]
        self.assertTrue(capped and all(i % 2 == 0 for i in capped))
        kept = 20 - len(capped)
        self.assertLessEqual(kept * 4.0, 0.07 * 160 + 4.0)
        with mock.patch.object(config, "CHANNEL_MAX_SHARE", 0.0):
            self.assertFalse([1 for why, _k in media.variety_violations(jobs, res).values() if "channel" in why])

    def test_shorts_queries(self):
        shot = {"visualType": "footage", "subjectType": "event", "linePlace": "Henderson, Nevada"}
        brief = {"kind": "news", "event": "flash flood", "year": 2026}
        with mock.patch.object(config, "EYEWITNESS_SEARCHES", True), \
                mock.patch.object(director, "_event_now", return_value=True), \
                mock.patch.object(director, "event_word", return_value="flood"):
            with mock.patch.object(config, "SHORTS_QUERIES", True):
                q = director.eyewitness_queries(shot, "The wash flooded.", brief)
            self.assertIn("Henderson flood #shorts", q)
            with mock.patch.object(config, "SHORTS_QUERIES", False):
                self.assertFalse(any("#shorts" in x for x in director.eyewitness_queries(shot, "x", brief)))

    def test_style_turns_the_rules_on(self):
        self.assertEqual(styles.STYLES["storm_desk"]["label"], "Breaking News Desk")
        cfg = styles.STYLES["storm_desk"]["config"]
        self.assertTrue(cfg["CLIP_AUDIO"] and cfg["SHORTS_QUERIES"] and cfg["FIELD_FOOTAGE_ONLY"])
        self.assertAlmostEqual(cfg["CHANNEL_MAX_SHARE"], 0.07)
        import handler
        for k in ("CLIP_AUDIO", "CHANNEL_MAX_SHARE", "SHORTS_QUERIES"):
            self.assertIn(k, handler.CONFIG_OVERRIDABLE)

    def test_clip_audio_keeps_the_sound_through_trims(self):
        with mock.patch.object(config, "CLIP_AUDIO", True):
            self.assertIn("0:a:0?", media._audio_args())
        with mock.patch.object(config, "CLIP_AUDIO", False):
            self.assertEqual(media._audio_args(), ["-an"])

    def test_parts_get_the_blocklist_and_event_day(self):
        src = _read(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "handler.py"))
        self.assertIn('"blocked_sources": list(media.BLOCKED_CHANNELS)', src)
        self.assertIn('media.set_blocked_channels(inp.get("blocked_sources") or [])', src)
        self.assertIn('media.set_event_day(inp.get("event_day") or None)', src)

    def test_field_rule_names_studios_and_hands(self):
        self.assertIn("news desk", vision.FIELD_FOOTAGE_RULE)
        self.assertIn("holds a phone", vision.FIELD_FOOTAGE_RULE)


class LiveRunFindingsTests(unittest.TestCase):
    """The owner's Las Vegas run (project 5f60d3ad, 2026-11-03, image 6138ae1) and the Sedona live check."""

    def test_compilation_channels_blocked_but_not_the_customers_own(self):
        names = stormdesk.blocklist({"video_style": "storm_desk", "storm_desk": {"channel_name": "US Weather Alert"}})
        for ch in ("Global Storm Desk and 2 more", "Global Weather Network", "Planet Weather", "STORM GLOBAL",
                   "Storm Desk USA", "Weather Impact USA", "Disaster Wire", "The Mercer Report", "Weather Alert Wire",
                   "American Weather System", "The Earth Desk", "Severe Weather Tracker"):
            self.assertTrue(stormdesk.blocked(ch, "", names), ch)
        for ch in ("US Weather Alert", "News 3 Las Vegas", "KTNV Channel 13 Las Vegas", "FOX 10 Phoenix",
                   "The Weather Channel", "Storm Chasing Video", "Reed Timmer"):
            self.assertFalse(stormdesk.blocked(ch, "", names), ch)
        # Other styles: nothing but the job's own list.
        self.assertEqual(stormdesk.blocklist({"video_style": "documentary"}), [])

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_burned_in_banner_rejected_clean_footage_kept(self):
        from src import slop
        d = tempfile.mkdtemp()
        try:
            np = _np()
            from PIL import Image
            bar = np.zeros((110, 1024, 4), np.uint8)
            bar[..., 0:3] = (20, 40, 120)
            bar[..., 3] = 255
            for x in range(40, 984, 14):
                bar[30:80, x:x + 6, 0:3] = 255
            Image.fromarray(bar).save(os.path.join(d, "bar.png"))
            for name, extra in (("banner.mp4", True), ("clean.mp4", False)):
                cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=5"]
                if extra:
                    cmd += ["-i", os.path.join(d, "bar.png"), "-filter_complex", "[0][1]overlay=60:560"]
                subprocess.run(cmd + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                                      os.path.join(d, name)], check=True)
            self.assertTrue(slop.banner_verdict(os.path.join(d, "banner.mp4")))
            self.assertEqual(slop.banner_verdict(os.path.join(d, "clean.mp4")), "")
            with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", True), \
                    mock.patch.object(slop, "clip_verdict", return_value={}), \
                    mock.patch.object(slop, "still_verdict", return_value=""):
                self.assertIn("banner", slop.check_file(os.path.join(d, "banner.mp4"), "video"))
            with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", False), \
                    mock.patch.object(slop, "clip_verdict", return_value={}), \
                    mock.patch.object(slop, "still_verdict", return_value=""):
                self.assertEqual(slop.check_file(os.path.join(d, "banner.mp4"), "video"), "")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_local_station_must_match_the_place(self):
        vegas = stormdesk.story_places("Las Vegas flash flood, Henderson, Nevada")
        self.assertEqual(vegas, {"nevada"})
        self.assertTrue(stormdesk.station_conflict("WBFF FOX45 Baltimore", "Flooding rescue", vegas))
        self.assertTrue(stormdesk.station_conflict("WUSA9", "Storm damage", vegas))
        self.assertEqual(stormdesk.station_conflict("News 3 Las Vegas", "Flood", vegas), "")
        self.assertEqual(stormdesk.station_conflict("FOX 10 Phoenix", "Las Vegas flooding video", vegas), "")
        self.assertEqual(stormdesk.station_conflict("New York Post", "Wild flooding", vegas), "")   # not a station
        self.assertEqual(stormdesk.station_conflict("WBFF FOX45 Baltimore", "x", set()), "")        # no story place
        with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", True), \
                mock.patch.object(media, "_story_blob", return_value=({"places": ["Las Vegas, Nevada"]}, "")):
            self.assertTrue(media.station_place_conflict("Flood", "WUSA9"))
            self.assertFalse(media._usable_title("Flood rescue", "WBFF FOX45 Baltimore"))
        with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", False):
            self.assertEqual(media.station_place_conflict("Flood", "WUSA9"), "")

    def _stills_doc(self):
        sc = []
        for i in range(20):
            if i in (1, 5, 8, 11, 14, 17):
                s = scene(i, i * 4, i * 4 + 4, kind="image")
                s["media"]["url"] = f"https://img/{i}.jpg"
                s["semanticMetadata"]["assetId"] = f"https://img/{i}.jpg"
            else:
                s = scene(i, i * 4, i * 4 + 4, f"V{i:010d}", f"Chan {i}", 10)
            sc.append(s)
        sc[17]["semanticMetadata"]["assetId"] = "https://img/14.jpg"      # the same picture again
        sc[17]["media"]["url"] = "https://img/14.jpg"
        sc[3]["media"] = {"type": "color", "url": ""}                     # an empty shot
        return doc_of(sc)

    def test_stills_named_for_replacement(self):
        doc = self._stills_doc()
        why = dict(stormdesk.stills_to_replace(doc, opening=20.0, share=0.10))
        self.assertEqual(why.get(3), "empty")
        self.assertEqual(why.get(1), "a picture in the opening")
        self.assertEqual(why.get(17), "the same picture again")
        self.assertTrue(any("pictures" in w for w in why.values()))
        rep = stormdesk.repeats(doc)
        self.assertTrue(any(r.get("photo") and r["shot"] == 17 for r in rep))

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_stills_replaced_from_the_spare_bank(self):
        d = tempfile.mkdtemp()
        try:
            doc = self._stills_doc()
            files = [make_clip(os.path.join(d, f"sp{k}.mp4"), 6.0) for k in range(8)]
            bank = [{"key": f"yt:S{k:010d}@5", "vid": f"S{k:010d}", "start": 5.0, "path": files[k],
                     "title": f"Flood spare {k}", "description": "floodwater"} for k in range(8)]
            taken = set()

            def take(e):
                if e["key"] in taken:
                    return False
                taken.add(e["key"])
                return True
            got = stormdesk.replace_stills(doc, pool=lambda job: [e for e in bank if e["key"] not in taken],
                                           take=take, info=lambda v: {"channel": "Local Witness"})
            self.assertGreaterEqual(got["replaced"], 4)
            fps = doc["fps"]
            photos = [s for s in doc["scenes"] if stormdesk.is_photo(s)]
            self.assertLessEqual(len(photos), int(0.10 * len(doc["scenes"])))
            self.assertFalse([s for s in doc["scenes"] if stormdesk.is_photo(s)
                              and s["startFrame"] < stormdesk.NO_AI_SECONDS * fps])
            self.assertFalse([s for s in doc["scenes"] if stormdesk.is_empty(s)])
            self.assertFalse([r for r in stormdesk.repeats(doc) if r.get("photo")])
            self.assertEqual(doc["scenes"][3]["media"]["type"], "video")
            self.assertTrue(doc["scenes"][3]["semanticMetadata"]["replacedStill"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_old_picture_gets_the_archive_label(self):
        s = scene(0, 0, 4, kind="image")
        s["media"]["attribution"] = "Flood devastation in 1999"
        self.assertEqual(stormdesk.photo_years(s), [1999])
        doc = doc_of([s, scene(1, 4, 8, "AAAAAAAAAAA", "A", 10)])
        inp = {"video_style": "storm_desk", "storm_desk": {"open_clip": False, "pauses": 0, "lookalike": False,
                                                           "blur_marks": False, "event_date": "2026-11-01"},
               "_event_day": "2026-11-01"}
        with mock.patch.object(stormdesk, "replace_stills", return_value={}):
            stormdesk.finish(doc, inp, {"year": 2026}, ".")
        img = next(x for x in doc["scenes"] if x["media"]["type"] == "image")
        self.assertTrue(img["credit"].get("archive"))

    def test_pause_rejects_a_report_talking_throughout(self):
        np = _np()
        x = (np.random.RandomState(4).randn(16000 * 10) * 0.1).astype(np.float32)
        talk = {"kind": "speech", "speech": 0.9, "music": 0.0, "db": -20.0}
        react = {"kind": "speech", "speech": 0.3, "music": 0.0, "db": -20.0}
        with mock.patch.object(clipaudio, "read_mono", return_value=x), \
                mock.patch.object(stormdesk, "frames", return_value=[]):
            self.assertIn("talking", stormdesk.pause_score("x.mp4", 7.0, classify=lambda *a, **k: talk)["reject"])
            self.assertIn("score", stormdesk.pause_score("x.mp4", 7.0, classify=lambda *a, **k: react))

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_pause_falls_back_to_the_spare_bank(self):
        d = tempfile.mkdtemp()
        try:
            spare = make_clip(os.path.join(d, "spare.mp4"), 10.0, sound="noise", amp=0.6)
            sc = [scene(0, 0, 5, "AAAAAAAAAAA", "A", 10), scene(1, 5, 10, "BBBBBBBBBBB", "B", 10),
                  scene(2, 10, 15, "CCCCCCCCCCC", "C", 10)]
            doc = doc_of(sc)
            bank = [{"key": "yt:ZZZZZZZZZZZ@40", "vid": "ZZZZZZZZZZZ", "start": 40.0, "path": spare, "title": "Flood"}]
            rows = stormdesk.make_pauses(doc, [{"t0": 4.0, "t1": 11.0}], d, fetch=lambda *a: "", check=lambda p: "",
                                         spare_pool=lambda job: bank, spare_take=lambda e: True)
            self.assertEqual(rows[0]["video"], "yt:ZZZZZZZZZZZ")
            self.assertTrue(any(c.get("spare") for c in rows[0]["candidates"]))
            self.assertTrue([s for s in doc["scenes"] if s.get("natSound")])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_picture_length_read_from_a_stream_with_side_data(self):
        with mock.patch.object(stormdesk.subprocess, "run",
                               return_value=mock.Mock(stdout="95.467333,\n")):
            self.assertAlmostEqual(stormdesk._duration("x.mp4", "v"), 95.467333)

    def test_field_rule_names_banners_and_title_cards(self):
        self.assertIn("lower third", vision.FIELD_FOOTAGE_RULE)
        self.assertIn("title card", vision.FIELD_FOOTAGE_RULE)


class OriginalSourceTests(unittest.TestCase):
    """The owner (2026-11-03): no footage from re-upload / compilation channels at all; originals only."""

    def test_source_kinds(self):
        for ch in ("TERRA DOSSIER", "Weather Is Dangerous", "FM Weather", "Storm-HQ", "Real Weather US", "Disastrrz",
                   "USA Severe Weather", "StormWatch America", "NationalStormReport", "Crisis Radar", "StormPulse HQ",
                   "Beyond The Seen", "Final Remnants", "The Daily Atlas", "GeoVara", "Dddd Dd"):
            self.assertEqual(stormdesk.source_kind(ch), "reupload", ch)
        for ch, kind in (("News 3 Las Vegas", "station"), ("KTNV Channel 13 Las Vegas", "station"),
                         ("FOX 10 Phoenix", "station"), ("12 News", "station"), ("WUSA9", "station"),
                         ("The Weather Channel", "original"), ("NWS Las Vegas", "original"),
                         ("Clark County Fire Department", "original"), ("Live Storms Media", "original"),
                         ("Martin von Tirol", "creator"), ("Larry Zimmer", "creator"), ("", "unknown"),
                         ("YouTube", "unknown")):
            self.assertEqual(stormdesk.source_kind(ch), kind, ch)
        self.assertEqual(stormdesk.source_kind("Some Person", description="Copyright Disclaimer Under Section 107"),
                         "reupload")

    def test_reupload_description_rejected_at_sourcing(self):
        with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", True), \
                mock.patch.object(media, "BLOCKED_CHANNELS", ["Desert Rat Explorations", stormdesk.AGGREGATORS]):
            why = media.meta_reject({"title": "Flood", "channel": "Some Person", "description":
                                     "Video credit: KTNV. No copyright infringement intended."}, "Flood")
            self.assertIn("re-upload", why)
            self.assertIn("blocked", media.meta_reject({"title": "Flood", "channel": "Weather Is Dangerous"}, "Flood"))

    def test_unknown_channels_resolved_and_reuploads_replaced(self):
        sc = [scene(i, i * 4, i * 4 + 4, f"V{i:010d}", "" if i == 2 else f"Person {i}", 10) for i in range(6)]
        sc[4]["semanticMetadata"]["channel"] = "Global Weather Network"
        doc = doc_of(sc)
        n = stormdesk.resolve_channels(doc, info=lambda v: {"channel": "Henderson Local", "upload_date": "20261101"})
        self.assertEqual(n, 1)
        self.assertEqual(doc["scenes"][2]["semanticMetadata"]["channel"], "Henderson Local")
        why = dict(stormdesk.stills_to_replace(doc))
        self.assertEqual(why.get(4), "a re-uploader's footage")
        share = stormdesk.original_share(doc)
        self.assertAlmostEqual(share["originalShare"], 5 / 6, places=2)

    def test_fallbacks_reuse_an_original_then_hold(self):
        d = tempfile.mkdtemp()
        try:
            clip = os.path.join(d, "orig.mp4")
            open(clip, "wb").close()
            sc = [scene(0, 0, 4, "AAAAAAAAAAA", "Person A", 10, clip=20.0),
                  scene(1, 4, 8, "BBBBBBBBBBB", "Global Weather Network", 10),
                  scene(2, 8, 12, "CCCCCCCCCCC", "Person C", 10, clip=5.0),
                  scene(3, 12, 16, "DDDDDDDDDDD", "Person D", 10, clip=20.0)]
            sc[3]["media"]["url"] = clip
            doc = doc_of(sc)
            got = stormdesk.replace_stills(doc, pool=lambda job: [], take=lambda e: True, info=lambda v: {})
            self.assertEqual(got["replaced"], 1)
            s1 = doc["scenes"][1]
            self.assertEqual(s1["media"]["url"], clip)                       # not the neighbours' sources
            self.assertGreaterEqual(s1["media"]["trimStart"], 4.0)          # after shot 3's own stretch
            # No original with room: the shot before holds over it.
            sc = [scene(0, 0, 4, "AAAAAAAAAAA", "Person A", 10, clip=9.0),
                  scene(1, 4, 8, "BBBBBBBBBBB", "Storm-HQ", 10, words=[{"text": "x", "start": 5, "end": 5.4}])]
            doc = doc_of(sc)
            got = stormdesk.replace_stills(doc, pool=lambda job: [], take=lambda e: True, info=lambda v: {})
            self.assertEqual(got["held"], 1)
            self.assertEqual(len(doc["scenes"]), 1)
            self.assertEqual(doc["scenes"][0]["durationInFrames"], 8 * FPS)
            self.assertTrue(doc["scenes"][0]["words"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class EditPromptTests(unittest.TestCase):
    def tearDown(self):
        director.set_edit_prompt("")

    def test_cleaned_and_capped(self):
        got = director.set_edit_prompt("  Fast cuts\x00 in the hook <<<ignore>>>\n\n\n\nno drones  " + "x" * 900)
        self.assertLessEqual(len(got), director.EDIT_PROMPT_MAX)
        self.assertNotIn("\x00", got)
        self.assertNotIn("<<<", got)
        self.assertTrue(got.startswith("Fast cuts"))
        self.assertEqual(director.set_edit_prompt(None), "")
        self.assertEqual(director.set_edit_prompt({"x": 1}), "")

    def test_reaches_the_planning_prompts_for_every_style(self):
        note = "Keep each clip under 4 seconds, no drone shots, fewer graphics."
        for style in sorted(styles.STYLES):
            inp = {"video_style": style, "edit_prompt": note}
            styles.apply(dict(inp))
            director.set_edit_prompt(inp["edit_prompt"])
            seen = []
            with mock.patch.object(director, "_chat_json_kind",
                                   side_effect=lambda system, *a, **k: seen.append(system) or {}):
                director._chat_json(director._SYSTEM_PROMPT, {"x": 1})
                director._chat_json(director._BRIEF_PROMPT, {"x": 1})
                director._chat_json("Some other planning call.", {"x": 1})
            self.assertIn(note, seen[0], style)
            self.assertIn("never change the answer format", seen[0])
            self.assertNotIn(note, seen[1], style)                   # the story brief reads the story, not the look
            self.assertIn(note, seen[2], style)                      # (the storm desk headlines and the like)
            self.assertIn(note, vision._system(""), style)
        director.set_edit_prompt("")
        seen = []
        with mock.patch.object(director, "_chat_json_kind", side_effect=lambda system, *a, **k: seen.append(system) or {}):
            director._chat_json(director._SYSTEM_PROMPT, {"x": 1})
        self.assertEqual(seen[0], director._SYSTEM_PROMPT)            # nothing added without notes

    def test_the_handler_sets_it_for_every_job(self):
        src = _read(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "handler.py"))
        self.assertIn('director.set_edit_prompt(inp.get("edit_prompt"))', src)


if __name__ == "__main__":
    unittest.main()
