"""The storm desk style (src/stormdesk.py, src/styles.py storm_desk): offline, no network, small ffmpeg files only."""
import datetime
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, media, stormdesk, styles, vision
from src.transcribe import Word

FPS = 30
HAVE_FFMPEG = bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


def words_of(text_blocks, wps=3.0, start=0.0):
    """Word timings for sentences spoken at `wps` words a second, 0.25 s between sentences."""
    out, t = [], start
    for sent in text_blocks:
        for w in sent.split():
            out.append(Word(text=w, start=round(t, 3), end=round(t + 1.0 / wps - 0.04, 3)))
            t += 1.0 / wps
        t += 0.25
    return out


def scene(i, a, b, vid="", ch="", t0=0.0, kind="video", clip=None, words=None, extra=None):
    s = {"id": f"s{i}", "startFrame": int(a * FPS), "durationInFrames": int(round((b - a) * FPS)), "text": "",
         "transition": "crossfade", "effect": "film", "motion": "zoom-in",
         "media": {"type": kind, "url": f"https://x/{i}.mp4", "source": "youtube",
                   "attribution": "YouTube: some title"},
         "semanticMetadata": {}, "words": words or []}
    if clip is not None:
        s["media"]["clipSeconds"] = clip
    if vid:
        s["semanticMetadata"].update({"sourceUrl": f"https://www.youtube.com/watch?v={vid}&t={int(t0)}",
                                      "moment": {"start": t0}, "assetId": f"yt:{vid}@{int(t0)}"})
    if ch:
        s["semanticMetadata"]["channel"] = ch
    s.update(extra or {})
    return s


def doc_of(scenes):
    total = max(x["startFrame"] + x["durationInFrames"] for x in scenes)
    return {"fps": FPS, "durationInFrames": total, "width": 1920, "height": 1080, "scenes": scenes,
            "overlays": [{"type": "lib", "startFrame": 0, "durationInFrames": 30}], "sfx": [{"name": "w"}],
            "captions": {"enabled": True}, "audio": {"url": "x", "volume": 1}, "meta": {}}


SENTS = ["Friday night a wall of water tore through Henderson and three people were rescued.",
         "So stay with us, because the forecast missed this one by hours.",
         "The wash below Lake Mead Parkway rose four feet in ten minutes.",
         "Crews pulled two drivers from their cars near Boulder Highway.",
         "Officials say one person is dead after the flooding.",
         "Lake Mead rose one foot eight inches in nine days.",
         "The Hoover Dam opened its outlets on Sunday morning.",
         "More rain is due on Tuesday and Wednesday across the valley.",
         "Never drive into moving water, turn around don't drown.",
         "We will keep following this story as it develops tonight."]


def make_clip(path, seconds=8.0, audio=True, size="320x180"):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run(cmd + [path], check=True)
    return path


class StyleTests(unittest.TestCase):
    def test_style_resolves_and_keeps_the_owner_rules(self):
        self.assertEqual(styles.resolve("storm_desk"), "storm_desk")
        cfg = styles.STYLES["storm_desk"]["config"]
        self.assertLessEqual(cfg["SHOT_MAX_SECONDS"], 5.0)
        self.assertLessEqual(cfg["MAX_SCENE_SECONDS"], 5.0)
        self.assertEqual(cfg["IMAGE_MAX_PER_VIDEO"], 0)
        self.assertFalse(cfg["CHAIN_SHOTS"])                    # never the same source twice in a row
        self.assertTrue(cfg["FIELD_FOOTAGE_ONLY"])
        self.assertAlmostEqual(1080 * cfg["VERTICAL_BAND_ASPECT"], 1135, delta=1)

    def test_every_style_setting_is_overridable_per_job(self):
        import handler
        missing = [k for k in styles.STYLES["storm_desk"]["config"] if k not in handler.CONFIG_OVERRIDABLE]
        self.assertEqual(missing, [])
        self.assertTrue(all(hasattr(config, k) for k in styles.STYLES["storm_desk"]["config"]))

    def test_apply_turns_off_sfx_music_captions_and_editing(self):
        inp = {"video_style": "storm_desk"}
        self.assertEqual(styles.apply(inp), "storm_desk")
        self.assertIs(inp["sfx"], False)
        self.assertIs(inp["bgm"], False)
        self.assertIs(inp["captions"], False)
        self.assertIs(inp["editing_v3"], False)
        own = {"video_style": "storm_desk", "bgm_url": "https://x/m.mp3"}
        styles.apply(own)
        self.assertEqual(own["bgm_url"], "https://x/m.mp3")      # the user's own track still plays

    def test_other_styles_unchanged(self):
        self.assertFalse(config.FIELD_FOOTAGE_ONLY)
        self.assertNotIn("storm", json.dumps(styles.STYLES["news_compilation"]))
        self.assertEqual(stormdesk.blocklist({"video_style": "documentary"}), [])


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.words = words_of(SENTS * 3, wps=2.6)     # ~3.5 minutes

    def test_auto_pauses_spaced_and_at_sentence_ends(self):
        end = self.words[-1].end
        ps = stormdesk.plan_pauses(self.words, end + 0.5)
        self.assertGreaterEqual(len(ps), 1)
        self.assertTrue(all(p["secs"] == 7.0 for p in ps))
        self.assertGreaterEqual(ps[0]["at"], stormdesk.PAUSE_FIRST_MIN)
        self.assertLessEqual(ps[-1]["at"], end - stormdesk.PAUSE_TAIL)
        for a, b in zip(ps, ps[1:]):
            self.assertGreaterEqual(b["at"] - a["at"], stormdesk.PAUSE_MIN_GAP)
        # Each cut sits in the silence after a sentence's last word, before the next word.
        ends = {round(w.end, 3) for w in self.words if w.text.endswith(".")}
        for p in ps:
            before = max(w.end for w in self.words if w.end <= p["at"])
            self.assertIn(round(before, 3), ends)
            self.assertFalse(any(w.start < p["at"] < w.end for w in self.words))

    def test_count_off_and_by_hand(self):
        end = self.words[-1].end
        self.assertEqual(stormdesk.plan_pauses(self.words, end, {"pauses": 0}), [])
        self.assertEqual(stormdesk.plan_pauses(self.words, end, {"pauses": "off"}), [])
        two = stormdesk.plan_pauses(self.words, end, {"pauses": 2, "pause_seconds": 6})
        self.assertEqual(len(two), 2)
        self.assertEqual(two[0]["secs"], 6.0)
        hand = stormdesk.plan_pauses(self.words, end, {"pauses": [30, 120]})
        self.assertEqual(len(hand), 2)
        self.assertLess(abs(hand[0]["at"] - 30), 8)

    def test_first_pause_prefers_the_hook_line(self):
        ps = stormdesk.plan_pauses(self.words, self.words[-1].end, {"pauses": 1})
        self.assertIn("stay with us", ps[0]["sentence"].lower())

    def test_shift_and_out_pauses(self):
        ps = [{"at": 20.0, "secs": 7.0}, {"at": 60.0, "secs": 7.0}]
        self.assertEqual(stormdesk.shift(10.0, ps), 10.0)
        self.assertEqual(stormdesk.shift(25.0, ps), 32.0)
        self.assertEqual(stormdesk.shift(61.0, ps), 75.0)
        out = stormdesk.out_pauses(ps)
        self.assertEqual([(o["t0"], o["t1"]) for o in out], [(20.0, 27.0), (67.0, 74.0)])
        ws = stormdesk.shift_words([Word("a", 19.0, 19.5), Word("b", 21.0, 21.4)], ps)
        self.assertIsInstance(ws[0], Word)
        self.assertEqual((ws[0].start, ws[1].start), (19.0, 28.0))

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_pad_narration_inserts_the_silences(self):
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "n.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=300:sample_rate=48000:duration=6", src], check=True)
            out = stormdesk.pad_narration(src, [{"at": 2.0, "secs": 3.0}, {"at": 4.0, "secs": 2.0}],
                                          os.path.join(d, "p.wav"))
            self.assertAlmostEqual(stormdesk._duration(out, "a") or stormdesk._probe(out)["duration"], 11.0,
                                   delta=0.05)
            # Silence where the first pause sits, tone right after it.
            gap = stormdesk._read_audio(out, 2.3, 2.4, 48000)
            after = stormdesk._read_audio(out, 5.2, 0.5, 48000)
            self.assertLess(float(abs(gap).max()), 1e-3)
            self.assertGreater(float(abs(after).max()), 0.05)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PauseSceneTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_window_becomes_one_clip_with_sound_from_another_source(self):
        d = tempfile.mkdtemp()
        try:
            clip = make_clip(os.path.join(d, "pause.mp4"), 8.0, audio=True)
            sc = [scene(0, 0, 4, "AAAAAAAAAAA", "Chan A", 10),
                  scene(1, 4, 9, "BBBBBBBBBBB", "Chan B", 50),
                  scene(2, 9, 14, "CCCCCCCCCCC", "Chan C", 5, clip=6.0),
                  scene(3, 14, 18, "DDDDDDDDDDD", "Chan D", 70),
                  scene(4, 18, 22, "EEEEEEEEEEE", "Chan E", 20)]
            doc = doc_of(sc)
            asked = []

            def fetch(video, start, seconds):
                asked.append((video, start, seconds))
                return clip
            rows = stormdesk.make_pauses(doc, [{"t0": 8.0, "t1": 15.0}], d, fetch=fetch, check=lambda p: "")
            self.assertTrue(rows[0]["clip"])
            got = doc["scenes"]
            pause = [s for s in got if s.get("natSound")]
            self.assertEqual(len(pause), 1)
            p = pause[0]
            self.assertEqual((p["startFrame"], p["durationInFrames"]), (240, 210))
            # Contiguous, nothing overlapping.
            for a, b in zip(got, got[1:]):
                self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
            # Not from the source just before (B) or just after (D).
            self.assertNotIn(asked[0][0], ("yt:BBBBBBBBBBB", "yt:DDDDDDDDDDD"))
            # The shot after the window starts later in its own clip.
            after = next(s for s in got if s["startFrame"] == 450)
            self.assertAlmostEqual(after["media"]["trimStart"], 1.0, places=2)
            # The pause moment keeps the repeat check's distance from the video's other moment.
            vid, start, _ = asked[0]
            other = {"yt:CCCCCCCCCCC": 5}.get(vid)
            if other is not None:
                self.assertGreaterEqual(abs(start - other), config.FALLBACK_MOMENT_GAP_SECONDS)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_clip_keeps_the_plan(self):
        sc = [scene(0, 0, 5, "AAAAAAAAAAA", "A", 10), scene(1, 5, 10, "BBBBBBBBBBB", "B", 10)]
        doc = doc_of(sc)
        rows = stormdesk.make_pauses(doc, [{"t0": 3.0, "t1": 8.0}], ".", fetch=lambda *a: "", check=lambda p: "")
        self.assertIsNone(rows[0]["clip"])
        self.assertEqual(len(doc["scenes"]), 2)

    def test_pause_start_rules(self):
        self.assertEqual(stormdesk.pause_start([(10.0, 14.0)], 8.0, 0.0, 30.0), 40.5)
        self.assertIsNone(stormdesk.pause_start([(10.0, 14.0)], 8.0, 45.0, 30.0))     # no room
        self.assertEqual(stormdesk.pause_start([(80.0, 84.0)], 8.0, 100.0, 30.0), 49.5)
        self.assertEqual(stormdesk.pause_start([], 8.0, 0.0, 30.0), 0.5)


class RuleTests(unittest.TestCase):
    def test_long_shots_are_cut_to_five_seconds(self):
        doc = doc_of([scene(0, 0, 12, "AAAAAAAAAAA", "A", 0), scene(1, 12, 15, "BBBBBBBBBBB", "B", 0),
                      scene(2, 15, 25, extra={"natSound": True})])
        n = stormdesk.cap_shots(doc)
        self.assertEqual(n, 1)
        lens = [s["durationInFrames"] / FPS for s in doc["scenes"] if not s.get("natSound")]
        self.assertLessEqual(max(lens), 5.0 + 1 / FPS)
        self.assertEqual(sum(s["durationInFrames"] for s in doc["scenes"]), 25 * FPS)
        parts = [s for s in doc["scenes"] if s.get("splitFrom") == "s0"]
        self.assertTrue(parts and all(s["media"]["trimStart"] > 0 for s in parts))

    def test_same_source_in_a_row_is_swapped(self):
        doc = doc_of([scene(0, 0, 4, "AAAAAAAAAAA", "A", 0), scene(1, 4, 8, "AAAAAAAAAAB", "A", 0),
                      scene(2, 8, 12, "BBBBBBBBBBB", "B", 0), scene(3, 12, 16, "CCCCCCCCCCC", "C", 0),
                      scene(4, 16, 20, "DDDDDDDDDDD", "D", 0)])
        fixed, left = stormdesk.fix_neighbours(doc)
        self.assertEqual((fixed, left), (1, 0))
        keys = [stormdesk.source_key(s) for s in doc["scenes"]]
        self.assertTrue(all(a != b for a, b in zip(keys, keys[1:])))

    def test_ai_moves_out_of_the_first_minute(self):
        sc = [scene(i, i * 4, i * 4 + 4, f"V{i:010d}", f"C{i}", 0) for i in range(25)]
        sc[2]["media"]["source"] = "generated"
        doc = doc_of(sc)
        moved, left = stormdesk.keep_ai_out_of_opening(doc)
        self.assertEqual((moved, left), (1, 0))
        ai_at = [s["startFrame"] / FPS for s in doc["scenes"] if stormdesk.is_ai(s)]
        self.assertTrue(ai_at and ai_at[0] >= 60)

    def test_repeats_and_shares(self):
        doc = doc_of([scene(0, 0, 4, "AAAAAAAAAAA", "A", 10), scene(1, 4, 8, "BBBBBBBBBBB", "B", 0),
                      scene(2, 8, 12, "AAAAAAAAAAA", "A", 11)])
        self.assertEqual(len(stormdesk.repeats(doc)), 1)
        sh = stormdesk.shares(doc)
        self.assertEqual(sh[0]["source"], "A")
        self.assertAlmostEqual(sh[0]["share"], 8 / 12, places=3)

    def test_credits_archive_and_dates(self):
        s = scene(0, 0, 4, "AAAAAAAAAAA", "News 3 Las Vegas", 10)
        self.assertEqual(stormdesk.credit_name(s), "News 3 Las Vegas")
        s["semanticMetadata"]["uploadDate"] = "20250815"
        day = stormdesk.event_date("Friday night October 30th the storm hit", {},
                                   today=datetime.date(2026, 11, 2))
        self.assertEqual(day, datetime.date(2026, 10, 30))
        self.assertTrue(stormdesk.archive(s, day, None))
        s["semanticMetadata"]["uploadDate"] = "20261030"
        self.assertFalse(stormdesk.archive(s, day, None))
        self.assertEqual(stormdesk.place_chip("Henderson, Nevada"), "Henderson, NV")
        self.assertEqual(stormdesk.date_chip(datetime.date(2026, 11, 1)), "NOV 1, 2026")

    def test_blocklist(self):
        names = stormdesk.blocklist({"video_style": "storm_desk", "blocked_sources": "Some Channel, Other"})
        self.assertIn("Desert Rat Explorations", names)
        self.assertIn("Some Channel", names)
        self.assertTrue(stormdesk.blocked("Desert Rat Explorations", "x", names))
        self.assertTrue(stormdesk.blocked("", "Lake Mead flood | Desert Rat Explorations", names))
        self.assertFalse(stormdesk.blocked("KTNV", "Henderson flood", names))
        try:
            media.set_blocked_channels(names)
            self.assertFalse(media._usable_title("Henderson flooding today", "Desert Rat Explorations", 1.78))
            self.assertEqual(media.meta_reject({"title": "x", "channel": "Desert Rat Explorations"}),
                             "a blocked source (Desert Rat Explorations)")
        finally:
            media.set_blocked_channels([])
        self.assertEqual(media.blocked_channel("x", "Desert Rat Explorations"), "")

    def test_field_footage_rule_only_when_on(self):
        self.assertNotIn("FIELD FOOTAGE ONLY", vision._system("news"))
        with mock.patch.object(config, "FIELD_FOOTAGE_ONLY", True):
            self.assertIn("FIELD FOOTAGE ONLY", vision._system("news"))
            self.assertIn("hands", vision._system("strict"))


class HeadlineTests(unittest.TestCase):
    def test_wrap_two_lines(self):
        lines = stormdesk.wrap2("Sedona orders three zones out as Oak Creek rises twelve feet tonight")
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(all(len(x) <= stormdesk.HEADLINE_LINE + 6 for x in lines))
        self.assertEqual(lines[0], lines[0].upper())
        self.assertEqual(stormdesk.wrap2("Flood in Vegas"), ["FLOOD IN VEGAS"])

    def test_rule_headline_takes_the_fact(self):
        h = stormdesk.rule_headline("And so here we are. Lake Mead rose one foot eight inches in nine days, "
                                    "the fastest rise in years.")
        self.assertIn("LAKE MEAD", h)
        self.assertLessEqual(len(h), 2 * stormdesk.HEADLINE_LINE + 1)

    def test_model_then_rules(self):
        blocks = [{"i": 0, "text": SENTS[0]}, {"i": 1, "text": SENTS[5]}]
        how = stormdesk.write_headlines(blocks, "t", ask=lambda sys, pay: {"blocks": [
            {"i": 0, "headline": "3 rescued as wall of water hits Henderson", "tab": "Breaking news"}]})
        self.assertEqual(how, "model")
        self.assertEqual(blocks[0]["headline"], "3 RESCUED AS WALL OF WATER HITS HENDERSON")
        self.assertTrue(blocks[1]["headline"])                   # the rules filled the one the model skipped
        blocks2 = [{"i": 0, "text": SENTS[0]}]
        self.assertEqual(stormdesk.write_headlines(blocks2, "t", ask=None), "rules")
        self.assertTrue(blocks2[0]["lines"])


class FinishTests(unittest.TestCase):
    def _doc(self):
        ws = words_of(SENTS * 2, wps=2.5)
        sc, t, i = [], 0.0, 0
        end = ws[-1].end + 0.5
        while t < end:
            b = min(end, t + 4.0)
            sc.append(scene(i, t, b, f"V{i:010d}", f"Chan {i % 7}", 10 * i,
                            words=[{"text": w.text, "start": w.start, "end": w.end} for w in ws
                                   if t <= w.start < b]))
            t, i = b, i + 1
        doc = doc_of(sc)
        doc["durationInFrames"] = sc[-1]["startFrame"] + sc[-1]["durationInFrames"]
        return doc

    def test_finish_on_a_planned_document(self):
        doc = self._doc()
        inp = {"video_style": "storm_desk", "title": "Henderson floods",
               "brand_kit": {"name": "US Weather Alert", "accent": "#1B4CA0", "accent2": "#E4302A",
                             "watermark": {"url": "https://x/logo.png", "position": "top-left", "size": 0.1,
                                           "opacity": 1}},
               "_storm_pauses": [], "storm_desk": {"location": "Henderson, Nevada", "event_date": "2026-10-30"}}
        rep = stormdesk.finish(doc, inp, {"places": ["Henderson, Nevada"]}, ".", fetch=lambda *a: "",
                               check=lambda p: "")
        self.assertEqual(rep["errors"], [])
        self.assertEqual(doc["overlays"], [])
        self.assertEqual(doc["sfx"], [])
        self.assertFalse(doc["captions"]["enabled"])
        self.assertTrue(all(s["transition"] == "none" for s in doc["scenes"]))
        self.assertTrue(all(s["credit"]["text"].startswith("VIDEO: Chan") for s in doc["scenes"]))
        sd = doc["stormDesk"]
        self.assertEqual(sd["logo"]["url"], "https://x/logo.png")
        self.assertEqual(sd["colors"]["bar"], "#1B4CA0")
        self.assertEqual(sd["location"]["place"], "Henderson, NV")
        self.assertEqual(sd["location"]["date"], "OCT 30, 2026")
        self.assertEqual(sd["location"]["startFrame"], 30)
        self.assertEqual(sd["subscribe"][0]["startFrame"], 50 * FPS)
        if len(sd["subscribe"]) > 1:
            self.assertEqual(sd["subscribe"][1]["startFrame"], 170 * FPS)
        self.assertTrue(sd["lowerThirds"])
        lt = sd["lowerThirds"][0]
        first_word = min(w["start"] for s in doc["scenes"] for w in s["words"])
        self.assertEqual(lt["startFrame"], int(round((first_word + 0.8) * FPS)))
        self.assertLessEqual(lt["durationInFrames"], 11 * FPS)
        self.assertEqual(lt["tab"], "BREAKING NEWS")
        self.assertTrue(all(len(lt2["lines"]) <= 2 for lt2 in sd["lowerThirds"]))
        for a, b in zip(sd["lowerThirds"], sd["lowerThirds"][1:]):
            self.assertLessEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
        self.assertEqual(rep["headlinesBy"], "rules")
        self.assertIn("Desert Rat Explorations", rep["blocklist"])
        self.assertLessEqual(rep["longestShot"], 5.0)
        self.assertEqual(rep["sameSourceInARow"], 0)
        self.assertIn("summary", rep)
        json.dumps(rep)                                          # the report is plain JSON

    def test_job_headlines_win(self):
        doc = self._doc()
        inp = {"video_style": "storm_desk", "_storm_pauses": [],
               "storm_desk": {"headlines": ["One dead after Henderson floods"] * 20, "subscribe": False}}
        rep = stormdesk.finish(doc, inp, {}, ".", fetch=lambda *a: "", check=lambda p: "")
        self.assertEqual(rep["headlinesBy"], "job")
        self.assertEqual(doc["stormDesk"]["lowerThirds"][0]["lines"], ["ONE DEAD AFTER", "HENDERSON FLOODS"])
        self.assertEqual(doc["stormDesk"]["subscribe"], [])


class MarkTests(unittest.TestCase):
    def test_static_corner_logo_is_found_and_still_shots_are_left(self):
        import numpy as np
        rng = np.random.default_rng(1)
        fr = []
        for k in range(6):
            a = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
            a[10:30, 260:300] = 0
            a[14:26, 264:296] = 255                         # a steady white logo with hard edges, top-right
            fr.append(a)
        boxes = stormdesk.static_marks(fr)
        self.assertEqual(len(boxes), 1)
        x, y, w, h = boxes[0]
        self.assertGreater(x, 0.7)
        self.assertLess(y, 0.2)
        still = [fr[0].copy() for _ in range(6)]
        self.assertEqual(stormdesk.static_marks(still), [])

    def test_lookalikes(self):
        import numpy as np
        v = {0: np.array([1.0, 0, 0]), 1: np.array([0.99, 0.141, 0]), 2: np.array([0, 1.0, 0])}
        v = {k: x / np.linalg.norm(x) for k, x in v.items()}
        self.assertEqual([(i, j) for i, j, _c in stormdesk.lookalikes(v)], [(0, 1)])


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
class AfterRenderTests(unittest.TestCase):
    def test_pause_sound_loudness_clean_file_and_sync(self):
        d = tempfile.mkdtemp()
        try:
            rendered = os.path.join(d, "final.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=320x180:rate=30:duration=6", "-f", "lavfi", "-i",
                            "sine=frequency=200:sample_rate=48000:duration=6", "-c:v", "libx264", "-preset",
                            "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-metadata", "encoder=Lavf-test",
                            "-shortest", rendered], check=True)
            clip = make_clip(os.path.join(d, "nat.mp4"), 4.0, audio=True)
            doc = {"fps": FPS, "durationInFrames": 6 * FPS, "scenes": [
                {"id": "a", "startFrame": 0, "durationInFrames": 60, "media": {"type": "video", "url": "x"}},
                {"id": "p", "startFrame": 60, "durationInFrames": 90, "natSound": True,
                 "media": {"type": "video", "url": clip}},
                {"id": "b", "startFrame": 150, "durationInFrames": 30, "media": {"type": "video", "url": "x"}}],
                "meta": {"stormDesk": {"pauses": [{"t0": 2.0, "t1": 5.0}]}}}
            rep = stormdesk.after_render(doc, rendered, d)
            self.assertTrue(rep["pauseSound"] and rep["pauseSound"][0]["ok"])
            self.assertLess(abs(rep["final"]["picture"] - 6.0), 0.1)
            self.assertLess(abs(rep["final"]["offset"]), 0.1)
            tags = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags",
                                   "-of", "json", rendered], capture_output=True, text=True).stdout
            self.assertNotIn("Lavf", tags)
            self.assertNotIn("Lavc", tags)
            # A timeline the picture does not match fails loudly.
            doc["durationInFrames"] = 9 * FPS
            with self.assertRaises(stormdesk.SyncError):
                stormdesk.after_render(doc, rendered, d)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class RendererContractTests(unittest.TestCase):
    def test_types_and_main_know_the_layer(self):
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remotion", "src")
        types = _read(os.path.join(root, "types.ts"))
        main = _read(os.path.join(root, "Main.tsx"))
        self.assertIn("stormDesk?: StormDeskDoc", types)
        self.assertIn("natSound?: boolean", types)
        self.assertIn("<StormDesk desk={props.stormDesk}", main)
        comp = _read(os.path.join(root, "components", "brand", "StormDesk.tsx"))
        for k in stormdesk.COLORS:
            self.assertIn(k, comp)


if __name__ == "__main__":
    unittest.main()
