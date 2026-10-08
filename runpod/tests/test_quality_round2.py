"""Quality round 2 (2026-10-09), from the 2026-10-08 bench's measured findings.

1. Opening lines starved: a long build gave a hook line 1.5 x its 192 s share while it needed 150-500 s, and one by
   one each candidate cost ~15 s of download and ~9 s of checks and judging. A hook line now gets HOOK_TIME_FACTOR x
   its share, looks at HOOK_PARALLEL_JUDGE candidates side by side, and makes its second look only when there is
   something to gain (HOOK_SECOND_LOOK "auto"). Every other line is unchanged.
2. Text leaks: the news rule (banners, subtitles and logos welcome) applied to every story kind. It is now the rule of
   news stories only; a non-news line about a real event keeps a broadcaster's own marks; every other line is held to
   the strict rule with added text spelt out (vision.text_mode), the free subtitle-band and corner-mark checks on for
   it (filters.STRICT_TEXT), and a focused second look at text (vision.text_check) on the clips the judge kept.
3. People from before video existed: a line about a story person in an era nobody filmed them looks for real photos
   of that person then first (src/personera.py).
"""
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from src import config, filters, media, personera, vision, ytdlp
from src.media import MediaAsset


def _clip(vid: str, score: float, alts=None, review="") -> MediaAsset:
    a = MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t=5",
                   relevance_score=score, quality=0.8, judged_by="frames", review_reason=review)
    a.alternatives = list(alts or [])
    return a


# --------------------------------------------------------------------------- 1. the hook's own time and looks
def _cands(n=3):
    return [{"id": f"vid{i}00000000"[:11], "title": f"Lake Mead aerial {i}", "duration": 300.0,
             "aspect": 1.78, "channel": "c", "url": f"https://www.youtube.com/watch?v=vid{i}00000000"[:43]}
            for i in range(1, n + 1)]


class HookLooksSideBySide(unittest.TestCase):
    def _run(self, scores, hook: bool, width: int, candidates: int = 3, sleep: float = 0.25):
        d = tempfile.mkdtemp()
        lock = threading.Lock()
        live, peak, fetched = [0], [0], []
        verdicts = {f"vid{i}00000000"[:11]: s for i, s in enumerate(scores, 1)}

        def fetch(vid, out_dir, point, grab, title):
            with lock:
                fetched.append(vid)
            p = os.path.join(d, f"yt_{vid}_{int(point)}_7.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x" * 10)
            return p

        def gate(path, intent, context, label):
            vid = os.path.basename(path).split("_")[1]
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(sleep)
            with lock:
                live[0] -= 1
            s = verdicts[vid]
            return s >= 0.7, {"score": s, "quality": 0.8, "description": f"clip {s}",
                              "has_text_or_watermark": False, "is_talking_head": False, "model": "m"}

        with mock.patch.object(config, "JUDGE_BEST_OF", 3), \
                mock.patch.object(config, "HOOK_JUDGE_BEST_OF", 3), \
                mock.patch.object(config, "EXCELLENT_SCORE", 0.99), \
                mock.patch.object(config, "POOL_SCOUT", candidates), \
                mock.patch.object(config, "HOOK_POOL_SCOUT", candidates), \
                mock.patch.object(config, "VISION_MAX_CANDIDATES", candidates), \
                mock.patch.object(config, "HOOK_PARALLEL_JUDGE", width), \
                mock.patch.object(config, "PICK_A_SHOT", False), \
                mock.patch.object(media, "_story_channels", return_value=[]), \
                mock.patch.object(media, "_yt_candidates_cached", return_value=_cands(len(scores))), \
                mock.patch.object(media, "_plan_grabs",
                                  side_effect=lambda el, grab, start, intent, ctx: [(c, 30.0, None) for c in el]), \
                mock.patch.object(media, "_yt_fetch_retry", fetch), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_vision_gate", gate):
            tokens = [(media._SCENE_JUDGED, media._SCENE_JUDGED.set([0])), (media._IN_HOOK, media._IN_HOOK.set(hook))]
            try:
                asset = media.youtube_clip("Lake Mead aerial", d, seconds=6.0, require_cc=False,
                                           intent="Lake Mead low water", context="x")
            finally:
                for var, tok in reversed(tokens):
                    var.reset(tok)
        return asset, peak[0], fetched

    def test_a_hook_line_judges_its_candidates_side_by_side(self):
        asset, peak, fetched = self._run([0.72, 0.88, 0.8], hook=True, width=3)
        self.assertGreaterEqual(peak, 2)
        self.assertEqual(len(fetched), 3)
        self.assertAlmostEqual(asset.relevance_score, 0.88)
        self.assertEqual(sorted(a["score"] for a in asset.alternatives), [0.72, 0.8])

    def test_any_other_line_judges_one_after_another(self):
        _asset, peak, _ = self._run([0.72, 0.88, 0.8], hook=False, width=3)
        self.assertEqual(peak, 1)

    def test_one_by_one_and_side_by_side_choose_the_same_clip(self):
        a1, peak1, _ = self._run([0.5, 0.91, 0.75], hook=True, width=1, sleep=0.01)
        a3, peak3, _ = self._run([0.5, 0.91, 0.75], hook=True, width=3, sleep=0.01)
        self.assertEqual(peak1, 1)
        self.assertEqual(a1.identity, a3.identity)
        self.assertEqual([a["score"] for a in a1.alternatives], [a["score"] for a in a3.alternatives])

    def test_a_batch_stays_inside_the_search_cap(self):
        with mock.patch.object(config, "HOOK_JUDGE_BEST_OF", 3):
            asset, _peak, fetched = self._run([0.4, 0.5, 0.6, 0.65], hook=True, width=3, candidates=2, sleep=0.01)
        self.assertLessEqual(len(fetched), 2)

    def test_a_batch_never_spends_past_the_line_s_vision_budget(self):
        # A budget of 6: three scouts, the fine pass - two verdicts left, so two candidates side by side, not three.
        with mock.patch.object(config, "JUDGE_MAX_PER_SCENE", 6), \
                mock.patch.object(config, "HOOK_JUDGE_MAX_PER_SCENE", 6), \
                mock.patch.object(config, "MOMENT_SELECTION", True), \
                mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media, "_refine_moment", side_effect=lambda row, m, *a: m):
            _asset, _peak, fetched = self._run([0.4, 0.5, 0.6], hook=True, width=3, sleep=0.01)
        self.assertEqual(len(fetched), 2)


class HookTime(unittest.TestCase):
    def test_the_factor(self):
        with mock.patch.object(config, "HOOK_TIME_FACTOR", 2.5):
            self.assertEqual(media.hook_factor(), 2.5)
        with mock.patch.object(config, "HOOK_TIME_FACTOR", 0.5):
            self.assertEqual(media.hook_factor(), 1.0)              # never under the line's own share

    def test_a_hook_line_gets_its_share_times_the_factor_and_the_others_their_share(self):
        seen = {}

        def fake(query, seconds, work_dir, **kw):
            box, own = ytdlp.STOP.get()
            seen[query] = own - time.time()
            return None

        jobs = [{"index": i, "query": f"line{i}", "seconds": 4.0, "context": "c", "start": 10.0 * i,
                 "hook": i == 0} for i in range(4)]
        with mock.patch.object(ytdlp, "DEADLINE", [0.0]), \
                mock.patch.object(config, "HOOK_TIME_FACTOR", 2.5), \
                mock.patch.object(config, "SCENE_SECONDS_MIN", 10.0), \
                mock.patch.object(config, "SCENE_SECONDS_MAX", 10.0), \
                mock.patch.object(config, "PASS1_BUDGET_SECONDS", 60.0), \
                mock.patch.object(config, "REPLACE_BUDGET_SECONDS", 0), \
                mock.patch.object(config, "FRESH_MOMENTS", False), \
                mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "generate_image", return_value=None):
            media.reset_cache()
            media.source_many(jobs, "/tmp", workers=1, refill=False, pass1_per_scene=1.0)
        self.assertAlmostEqual(seen["line0"], 25.0, delta=1.5)
        for q in ("line1", "line2", "line3"):
            self.assertAlmostEqual(seen[q], 10.0, delta=1.5)


class SecondLook(unittest.TestCase):
    def test_auto(self):
        with mock.patch.object(config, "HOOK_SECOND_LOOK", "auto"), \
                mock.patch.object(config, "HOOK_SECOND_LOOK_SECONDS", 150.0), \
                mock.patch.object(config, "EXCELLENT_SCORE", 0.85):
            self.assertEqual(media.second_look_seconds(_clip("aaaaaaaaaaa", 0.75)), 150.0)
            self.assertIsNone(media.second_look_seconds(_clip("aaaaaaaaaaa", 0.75, alts=[{"score": 0.72}])))
            self.assertIsNone(media.second_look_seconds(_clip("aaaaaaaaaaa", 0.9)))
            near = _clip("aaaaaaaaaaa", 0.6, review="Best available: the vision check scored it 0.60")
            self.assertEqual(media.second_look_seconds(near), 150.0)
        with mock.patch.object(config, "HOOK_SECOND_LOOK", "always"):
            self.assertEqual(media.second_look_seconds(_clip("aaaaaaaaaaa", 0.9)), 0.0)
        with mock.patch.object(config, "HOOK_SECOND_LOOK", "off"):
            self.assertIsNone(media.second_look_seconds(_clip("aaaaaaaaaaa", 0.6)))

    def _run(self, first: MediaAsset, mode: str):
        calls = []

        def fake(query, seconds, work_dir, **kw):
            nth = kw.get("nth", 0)
            got = ytdlp.STOP.get()
            calls.append((nth, (got[1] - time.time()) if got and got[1] else None))
            return first if nth == 0 else None

        jobs = [{"index": 0, "query": "opening", "seconds": 4.0, "context": "c", "start": 0.0, "hook": True}]
        with mock.patch.object(ytdlp, "DEADLINE", [0.0]), \
                mock.patch.object(config, "HOOK_SECOND_LOOK", mode), \
                mock.patch.object(config, "HOOK_SECOND_LOOK_SECONDS", 30.0), \
                mock.patch.object(config, "EXCELLENT_SCORE", 0.85), \
                mock.patch.object(config, "PASS1_BUDGET_SECONDS", 120.0), \
                mock.patch.object(config, "REPLACE_BUDGET_SECONDS", 0), \
                mock.patch.object(config, "FRESH_MOMENTS", False), \
                mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", return_value=None):
            media.reset_cache()
            out = media.source_many(jobs, "/tmp", workers=2, refill=False)
        return out, calls

    def test_the_second_look_runs_in_its_own_short_time(self):
        out, calls = self._run(_clip("abcdefghijk", 0.75), "auto")
        self.assertEqual([n for n, _ in calls], [0, 1])
        self.assertAlmostEqual(calls[1][1], 30.0, delta=1.5)
        self.assertEqual(out[0].identity, "yt:abcdefghijk")

    def test_a_clip_that_already_beat_others_gets_no_second_look(self):
        _out, calls = self._run(_clip("abcdefghijk", 0.75, alts=[{"score": 0.71}]), "auto")
        self.assertEqual([n for n, _ in calls], [0])

    def test_always_is_the_old_rule(self):
        _out, calls = self._run(_clip("abcdefghijk", 0.95, alts=[{"score": 0.71}]), "always")
        self.assertEqual([n for n, _ in calls], [0, 1])


# --------------------------------------------------------------------------- 2. the text rule by story
HISTORY_1942 = {"kind": "history", "year": 1942, "people": ["Chester W. Nimitz"]}
HISTORY_2007 = {"kind": "history", "year": 2007, "people": ["Steve Jobs"]}
EXPLAINER = {"kind": "explainer", "year": None}
BIOGRAPHY = {"kind": "biography", "year": None, "people": ["Barack Obama"]}
DISASTER = {"kind": "disaster", "year": 2025, "recent": True}


class TextRuleByStory(unittest.TestCase):
    def setUp(self):
        p = mock.patch.multiple(config, NEWS_FOOTAGE=True, VISION_TEXT_BY_STORY=True, VISION_BROADCAST_ERA=1950)
        p.start()
        self.addCleanup(p.stop)

    def test_which_rule_each_line_gets(self):
        ev = {"specificity": "event", "time_context": "historical"}
        self.assertEqual(vision.text_mode(ev, HISTORY_1942), "strict")          # a 1942 battle: no broadcaster
        self.assertEqual(vision.text_mode({"specificity": "event", "time_context": "january 9, 2007"},
                                          HISTORY_2007), "event")                # the keynote, as it was filmed
        self.assertEqual(vision.text_mode({"specificity": "location", "time_context": "2007-2010"},
                                          HISTORY_2007), "strict")
        self.assertEqual(vision.text_mode({"specificity": "location", "time_context": "current"}, EXPLAINER),
                         "event")                                                # a current situation
        self.assertEqual(vision.text_mode({"specificity": "generic", "time_context": "current"}, EXPLAINER),
                         "strict")
        self.assertEqual(vision.text_mode({"specificity": "location", "time_context": "1979-1983"}, BIOGRAPHY),
                         "strict")
        self.assertEqual(vision.text_mode({"specificity": "event", "time_context": "july 8, 2025"}, DISASTER),
                         "news")
        self.assertEqual(vision.text_mode(None, {"kind": "history", "year": 2026}), "news")   # a story about now
        self.assertEqual(vision.text_mode(None, {}), "news")                     # no story known: as before

    def test_the_switches(self):
        with mock.patch.object(config, "VISION_TEXT_BY_STORY", False):
            self.assertEqual(vision.text_mode({"specificity": "generic"}, BIOGRAPHY), "news")
        with mock.patch.object(config, "NEWS_FOOTAGE", False):
            self.assertEqual(vision.text_mode({"specificity": "event"}, DISASTER), "strict")

    def test_the_rule_texts(self):
        strict, event, news = vision._system("strict"), vision._system("event"), vision._system("news")
        self.assertIn("ADDED on top of the footage", strict)
        self.assertNotIn("TV NEWS FOOTAGE IS WELCOME", strict)
        self.assertIn("EXCEPTION for this line", event)
        self.assertIn("ADDED on top of the footage", event)
        self.assertIn("TV NEWS FOOTAGE IS WELCOME", news)
        self.assertNotIn("ADDED on top of the footage", news)
        with mock.patch.object(config, "VISION_TEXT_BY_STORY", False):
            self.assertEqual(vision._system("strict"), vision._SYSTEM)       # the old strict rule, unchanged

    def test_the_judge_asks_under_the_line_s_rule(self):
        seen = []

        def ask(messages, max_tokens, accept=None, first=""):
            seen.append(messages[0]["content"])
            return ('{"description": "d", "score": 0.8, "quality": 0.8, "has_text_or_watermark": false, '
                    '"is_talking_head": false, "ai_generated": false, "studio": false, "music_or_vice": false, '
                    '"vice": "none", "specificity": "generic"}', "m")
        path = os.path.join(tempfile.mkdtemp(), "c.jpg")
        with open(path, "wb") as fh:
            fh.write(b"x" * 64)
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "_ask", side_effect=ask), \
                mock.patch.object(vision, "sample_frames", return_value=["AAAA"]):
            vision.reset()
            vision.set_story(HISTORY_1942)
            v1 = vision.judge(path, "Midway carriers", "x", scene={"specificity": "event",
                                                                   "time_context": "historical"})
            vision.set_story(DISASTER)
            v2 = vision.judge(path, "Midway carriers", "x", scene={"specificity": "event",
                                                                   "time_context": "historical"})
            vision.set_story({})
        self.assertEqual((v1["text_mode"], v2["text_mode"]), ("strict", "news"))
        self.assertIn("ADDED on top of the footage", seen[0])
        self.assertIn("TV NEWS FOOTAGE IS WELCOME", seen[1])

    def test_a_storyboard_pick_is_told_about_banners_only_under_the_news_or_event_rule(self):
        for mode, told in (("strict", False), ("event", True), ("news", True)):
            tok = vision.TEXT_MODE.set(mode)
            try:
                self.assertEqual(vision._tile_news(), told)
            finally:
                vision.TEXT_MODE.reset(tok)

    def test_the_line_s_rule_is_set_while_it_is_sourced_and_reset_after(self):
        seen = {}

        def one(*a, **kw):
            seen["mode"], seen["strict"] = vision.TEXT_MODE.get(), filters.STRICT_TEXT.get()
            return None
        vision.set_story(HISTORY_1942)
        try:
            with mock.patch.object(media, "_source_one", side_effect=one):
                media.source_for_segment("Midway carriers", 4.0, "/tmp",
                                         scene_intent={"specificity": "event", "time_context": "historical"})
        finally:
            vision.set_story({})
        self.assertEqual(seen, {"mode": "strict", "strict": True})
        self.assertEqual(vision.TEXT_MODE.get(), "")
        self.assertIsNone(filters.STRICT_TEXT.get())


def _frames_with(band=False, corner=False, n=4, seed=3):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        f = rng.integers(60, 120, size=(180, 320)).astype("uint8")
        f = np.roll(f, 9 * k, axis=1)                       # the picture moves
        if band:
            for x in range(80, 240, 4):                      # a line of letters near the bottom
                f[150:156, x:x + 2] = 250
                f[150:156, x + 2:x + 4] = 10
        if corner:
            f[6:24, 260:310] = 0
            f[10:20, 264:306:3] = 255                        # a mark that holds still
        out.append(f)
    return out


class FreePixelChecks(unittest.TestCase):
    def test_the_subtitle_band_goes_only_on_a_strict_line(self):
        with mock.patch.object(filters, "_gray_frames", return_value=_frames_with(band=True)):
            tok = filters.STRICT_TEXT.set(True)
            try:
                self.assertTrue(filters.has_burned_captions("x.mp4"))
            finally:
                filters.STRICT_TEXT.reset(tok)
            tok = filters.STRICT_TEXT.set(False)
            try:
                self.assertFalse(filters.has_burned_captions("x.mp4"))
            finally:
                filters.STRICT_TEXT.reset(tok)

    def test_unset_follows_news_footage(self):
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            self.assertFalse(filters.strict_text())
        with mock.patch.object(config, "NEWS_FOOTAGE", False):
            self.assertTrue(filters.strict_text())

    def test_the_text_signal(self):
        big = lambda frames: [np.kron(f, np.ones((2, 2), dtype="uint8")) for f in frames]  # noqa: E731
        self.assertTrue(filters.text_signal_frames(big(_frames_with(corner=True, n=3)))["likely"])
        self.assertTrue(filters.text_signal_frames(big(_frames_with(band=True, n=3)))["likely"])
        self.assertFalse(filters.text_signal_frames(big(_frames_with(n=3)))["likely"])
        self.assertFalse(filters.text_signal_frames([])["likely"])


# --------------------------------------------------------------------------- 2b. the second look at text
def _tc_answer(added, items):
    import json
    return json.dumps({"added": added, "items": items})


class TextCheck(unittest.TestCase):
    def test_what_each_rule_turns_down(self):
        subs = {"added": True, "items": [{"kind": "subtitles", "where": "bottom", "text": "the United States"}]}
        bug = {"added": True, "items": [{"kind": "logo", "where": "top-right", "text": "CNBC"}]}
        none = {"added": False, "items": []}
        self.assertTrue(vision.text_check_decision(subs, "strict").startswith("added text: subtitles"))
        self.assertTrue(vision.text_check_decision(bug, "strict"))
        self.assertEqual(vision.text_check_decision(bug, "event"), "")
        self.assertTrue(vision.text_check_decision(subs, "event"))
        self.assertEqual(vision.text_check_decision(subs, "news"), "")
        self.assertEqual(vision.text_check_decision(none, "strict"), "")
        credit = {"added": True, "items": [{"kind": "typed_text", "where": "top-left",
                                            "text": "Courtesy Southern Nevada Water Authority"}]}
        self.assertEqual(vision.text_check_decision(credit, "event"), "")      # who filmed it, on a current line
        self.assertTrue(vision.text_check_decision(credit, "strict"))

    def _clip_file(self):
        path = os.path.join(tempfile.mkdtemp(), "yt_abc_1_2.mp4")
        with open(path, "wb") as fh:
            fh.write(os.urandom(256))
        return path

    def test_one_call_cached_and_budgeted(self):
        calls = []

        def ask(messages, max_tokens, accept=None, first=""):
            calls.append(messages)
            return _tc_answer(True, [{"kind": "timecode", "where": "bottom", "text": "TCR 01:14:24:01"}]), "m"
        a, b = self._clip_file(), self._clip_file()
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "_ask", side_effect=ask), \
                mock.patch.object(vision, "sample_frames", return_value=["AAAA", "BBBB"]), \
                mock.patch.object(config, "TEXT_SECOND_LOOK_MAX", 1):
            vision.reset()
            got = vision.text_check(a, "strict")
            again = vision.text_check(a, "strict")
            other = vision.text_check(b, "strict")
        self.assertEqual(len(calls), 1)
        self.assertIs(again, got)
        self.assertIsNone(other)                              # the video's second looks are spent
        self.assertEqual(got["reject"], "added text: timecode (TCR 01:14:24:01)")
        self.assertEqual(len([p for p in calls[0][1]["content"] if p.get("type") == "image_url"]), 2)
        self.assertEqual(vision.text_check_stats()["flagged"], 1)

    def test_a_still_is_never_looked_at_again(self):
        path = os.path.join(tempfile.mkdtemp(), "p.jpg")
        with open(path, "wb") as fh:
            fh.write(b"x" * 64)
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "_ask") as ask:
            self.assertIsNone(vision.text_check(path, "strict"))
        ask.assert_not_called()


class SecondLookInTheGate(unittest.TestCase):
    VERDICT = {"description": "Black and white archival footage of a carrier at sea", "score": 0.85,
               "quality": 0.8, "has_text_or_watermark": False, "is_talking_head": False, "ai_generated": False,
               "studio": False, "music_or_vice": False, "vice": "none", "specificity": "event", "opening": None,
               "model": "m", "text_mode": "strict"}

    def _gate(self, verdict, hook=False, signal=False, check=None, on=True):
        path = os.path.join(tempfile.mkdtemp(), "yt_abc_1_2.mp4")
        with open(path, "wb") as fh:
            fh.write(b"x" * 64)
        check = check if check is not None else {"added": True, "items": [{"kind": "subtitles"}],
                                                 "reject": "added text: subtitles"}
        with mock.patch.object(config, "VISION_TEXT_SECOND_LOOK", on), \
                mock.patch.object(config, "TEXT_SECOND_LOOK_MAX", 10), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "_local_check", return_value=None), \
                mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media.vision, "judge", return_value=dict(verdict)), \
                mock.patch.object(media.vision, "text_check", return_value=check) as tc, \
                mock.patch.object(filters, "text_signal", return_value={"likely": signal}), \
                mock.patch.object(media, "_opening_span", return_value=None):
            vision.reset()
            tok = media._IN_HOOK.set(hook)
            try:
                keep, v = media._judge_gate(path, "carriers at Midway", "line", "YouTube: Midway")
            finally:
                media._IN_HOOK.reset(tok)
        return keep, v, tc

    def test_a_hook_clip_on_a_strict_line_is_looked_at_and_turned_down(self):
        keep, v, tc = self._gate(self.VERDICT, hook=True)
        tc.assert_called_once()
        self.assertFalse(keep)
        self.assertTrue(v["has_text_or_watermark"])
        self.assertEqual(v["text_check"]["why"], "hook")
        self.assertTrue(media.judged_line_free(v))             # remembered for every line, like the judge's flag

    def test_another_clip_only_when_something_says_text_may_be_there(self):
        keep, _v, tc = self._gate(self.VERDICT)
        tc.assert_not_called()
        self.assertTrue(keep)
        keep, v, tc = self._gate(self.VERDICT, signal=True)
        tc.assert_called_once()
        self.assertEqual(v["text_check"]["why"], "pixels")
        said = dict(self.VERDICT, description="Underwater cameras with text overlays and a date stamp")
        keep, v, tc = self._gate(said)
        self.assertEqual(v["text_check"]["why"], "description")

    def test_never_under_the_news_rule_nor_switched_off(self):
        keep, _v, tc = self._gate(dict(self.VERDICT, text_mode="news"), hook=True)
        tc.assert_not_called()
        self.assertTrue(keep)
        keep, _v, tc = self._gate(self.VERDICT, hook=True, on=False)
        tc.assert_not_called()

    def test_a_clean_answer_keeps_the_clip(self):
        keep, v, tc = self._gate(self.VERDICT, hook=True, check={"added": False, "items": [], "reject": ""})
        self.assertTrue(keep)
        self.assertFalse(v["has_text_or_watermark"])


# --------------------------------------------------------------------------- 3. people from before video existed
OBAMA = {"kind": "biography", "year": None, "people": ["Barack Obama", "Ann Dunham", "Barack Obama Sr.",
                                                       "Michelle Robinson"]}
MIDWAY = {"kind": "history", "year": 1942, "people": ["Isoroku Yamamoto", "Chester W. Nimitz"]}
IPHONE = {"kind": "history", "year": 2007, "people": ["Steve Jobs"]}


class PersonEraDetect(unittest.TestCase):
    def setUp(self):
        p = mock.patch.multiple(config, PERSON_ERA_PHOTOS=True, PERSON_ERA_YEARS=8, PERSON_ERA_FILM_YEAR=1950)
        p.start()
        self.addCleanup(p.stop)

    def test_a_biography_s_early_life(self):
        pe = personera.detect("Barack Obama was born in Honolulu in August 1961,",
                              {"sceneIntent": {"entities": ["Honolulu, Hawaii"], "time_context": "1961-1963"}}, OBAMA)
        self.assertEqual((pe["person"], pe["year"], pe["stage"], pe["early"]), ("Barack Obama", 1961, "baby", True))
        pe = personera.detect("He studied at Occidental College in Los Angeles",
                              {"sceneIntent": {"entities": ["Occidental College"], "time_context": "1979-1985"}},
                              OBAMA)
        self.assertEqual((pe["person"], pe["year"], pe["stage"]), ("Barack Obama", 1979, "student"))
        self.assertEqual(personera.queries(pe, {"entities": ["Occidental College", "Los Angeles, California"]}),
                         ["Barack Obama as a student photo", "Barack Obama Occidental College 1979 photo",
                          "Barack Obama 1970s photograph"])

    def test_the_biography_s_subject_told_by_a_pronoun(self):
        pe = personera.detect("Back in Chicago he taught constitutional law, married Michelle Robinson in 1992",
                              {}, OBAMA)
        self.assertEqual((pe["person"], pe["stage"]), ("Barack Obama", "wedding"))

    def test_an_age_makes_it_a_childhood(self):
        pe = personera.detect("a student from Kenya. His parents separated when he was two,", {}, OBAMA,
                              prev={"year": 1961})
        self.assertEqual((pe["year"], pe["stage"]), (1961, "child"))

    def test_before_film_was_common(self):
        pe = personera.detect("carriers. Admiral Yamamoto intended to draw out and destroy the American fleet.",
                              {"sceneIntent": {"time_context": "historical"}}, MIDWAY)
        self.assertEqual((pe["person"], pe["year"], pe["early"]), ("Isoroku Yamamoto", 1942, False))
        self.assertEqual(personera.clip_query(pe), "Isoroku Yamamoto 1942 archival footage")

    def test_a_filmed_public_life_keeps_its_footage(self):
        self.assertIsNone(personera.detect("Steve Jobs walked onto the stage at Macworld in San Francisco",
                                           {"sceneIntent": {"time_context": "january 9, 2007"}}, IPHONE))
        self.assertIsNone(personera.detect("where a crew led by Ed Dickens spent five years rebuilding it",
                                           {"sceneIntent": {"time_context": "recent"}},
                                           {"kind": "history", "people": ["Ed Dickens"]}))

    def test_no_person_no_story_or_switched_off(self):
        self.assertIsNone(personera.detect("In June 1942, six months after Pearl Harbor,", {}, MIDWAY))
        self.assertIsNone(personera.detect("Barack Obama was born in 1961", {}, {"kind": "biography"}))
        with mock.patch.object(config, "PERSON_ERA_PHOTOS", False):
            self.assertIsNone(personera.detect("Barack Obama was born in 1961", {}, OBAMA))

    def test_the_full_name_wins_and_a_surname_goes_to_the_lead(self):
        self.assertEqual(personera.named_person("Barack Obama Sr. was a Kenyan economist", OBAMA["people"]),
                         "Barack Obama Sr.")
        self.assertEqual(personera.named_person("where Obama attended local schools", OBAMA["people"]),
                         "Barack Obama")

    def test_the_build_marks_its_lines(self):
        import handler

        class Seg:
            def __init__(self, text):
                self.text = text
        segs = [Seg("Barack Obama was born in Honolulu in August 1961,"),
                Seg("a student from Kenya. His parents separated when he was two,"),
                Seg("In 2008 he won the presidency.")]
        shots = [{}, {}, {}]
        jobs = [{"index": i} for i in range(3)]
        self.assertEqual(handler._mark_person_era(jobs, segs, shots, OBAMA), 2)
        self.assertEqual(jobs[1]["person_era"]["year"], 1961)          # the year goes on from the line before
        self.assertEqual(shots[0]["personEra"]["person"], "Barack Obama")
        self.assertNotIn("person_era", jobs[2])


class PersonEraSourcing(unittest.TestCase):
    PE = {"person": "Barack Obama", "year": 1961, "era": "1960s", "early": True, "stage": "baby"}

    def setUp(self):
        p = mock.patch.multiple(config, PERSON_ERA_PHOTOS=True, PERSON_ERA_IN_HOOK=True, PERSON_ERA_CLIP=True,
                                HOOK_NO_STILL_SECONDS=10.0)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, answers, pe=None, hook=False, start=None):
        calls = []

        def one(query, seconds, work_dir, **kw):
            calls.append({"query": query, "stage": kw.get("stage"), "subject": kw.get("subject"),
                          "subject_type": media._SUBJECT_TYPE.get(), "rung": media._RUNG.get(),
                          "person": media._PERSON_PHOTO.get()})
            return answers(query, kw)
        with mock.patch.object(media, "_source_one", side_effect=one):
            got = media.source_for_segment("Honolulu 1960s street archival footage", 4.0, "/tmp",
                                           scene_intent={"entities": ["Honolulu, Hawaii"], "time_context": "1961"},
                                           person_era=pe if pe is not None else self.PE, hook=hook, start=start)
        return got, calls

    def test_a_photo_of_the_person_then_comes_first(self):
        photo = MediaAsset(kind="image", source="web_image", url="https://x.org/obama-baby.jpg", relevance_score=0.8)
        got, calls = self._run(lambda q, kw: photo if kw.get("stage") == "pictures" else None)
        self.assertIs(got, photo)
        self.assertEqual(got.score_parts.get("personEra"), "Barack Obama")
        self.assertEqual(calls[0], {"query": "Barack Obama as a baby photo", "stage": "pictures",
                                    "subject": "Barack Obama", "subject_type": "person", "rung": None,
                                    "person": "Barack Obama"})
        self.assertEqual(len(calls), 1)

    def test_an_early_life_without_photos_goes_on_to_the_line_s_own_plan_never_archive_film(self):
        got, calls = self._run(lambda q, kw: None)
        stages = [c["stage"] for c in calls]
        self.assertEqual(stages[:2], ["pictures", "pictures"])
        self.assertFalse(any(c["rung"] and c["rung"].get("label") == "Barack Obama" for c in calls))
        self.assertIn("Honolulu 1960s street archival footage", [c["query"] for c in calls])   # the line's own plan

    def test_a_person_before_film_gets_one_archive_film_search_after_the_photos(self):
        pe = {"person": "Chester W. Nimitz", "year": 1942, "era": "1940s", "early": False, "stage": ""}
        film = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=nimitz00000&t=3",
                          relevance_score=0.8)
        got, calls = self._run(lambda q, kw: film if kw.get("stage") == "youtube" and "archival" in q else None,
                               pe=pe)
        self.assertIs(got, film)
        clip_calls = [c for c in calls if c["stage"] == "youtube"]
        self.assertEqual(clip_calls[0]["query"], "Chester W. Nimitz 1942 archival footage")
        self.assertEqual(clip_calls[0]["rung"]["label"], "Chester W. Nimitz")

    def test_its_photos_are_held_to_the_looser_limit_of_an_archive_print(self):
        from src import sharpness
        seen = []

        def one(query, seconds, work_dir, **kw):
            seen.append(sharpness.limit())
            return None
        with mock.patch.object(config, "PERSON_ERA_MAX_MAGNIFICATION", 3.0), \
                mock.patch.object(config, "MAX_PICTURE_MAGNIFICATION", 1.86), \
                mock.patch.object(media, "_source_one", side_effect=one):
            media._person_era_first(self.PE, 4.0, "/tmp", context="Barack Obama was born in Honolulu")
        self.assertEqual(set(seen), {3.0})
        self.assertAlmostEqual(sharpness.limit(), 1.86)                  # only while its photos are searched

    def test_its_photo_search_spends_at_most_its_own_verdicts(self):
        d = tempfile.mkdtemp()
        judged = []

        def cands(n):
            out = []
            for k in range(n):
                p = os.path.join(d, f"p{k}.jpg")
                with open(p, "wb") as fh:
                    fh.write(b"x" * 64)
                out.append((MediaAsset(kind="image", source="web_image", url=f"https://x.org/{k}.jpg"),
                            MediaAsset(kind="image", source="web_image", url=f"https://x.org/{k}.jpg",
                                       local_path=p)))
            return out

        def gate(path, intent, context, label, source_url=""):
            judged.append(path)
            return False, {"score": 0.3}
        with mock.patch.object(config, "PERSON_ERA_MAX_JUDGES", 4), \
                mock.patch.object(config, "VISION_MAX_CANDIDATES", 3), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "_vision_gate", side_effect=gate):
            tok = media._PERSON_JUDGES.set([4])
            try:
                for _source in range(3):                     # three sources asked in turn, three verdicts each
                    media._first_that_passes(iter(cands(3)), set(), "Barack Obama as a baby", "x")
            finally:
                media._PERSON_JUDGES.reset(tok)
            self.assertEqual(len(judged), 4)
            judged.clear()
            media._first_that_passes(iter(cands(3)), set(), "Honolulu", "x")     # any other line: as before
            self.assertEqual(len(judged), 3)

    def test_the_hook_s_first_seconds(self):
        photo = MediaAsset(kind="image", source="web_image", url="https://x.org/obama-baby.jpg", relevance_score=0.8)
        got, _ = self._run(lambda q, kw: photo if kw.get("stage") == "pictures" else None, hook=True, start=0.0)
        self.assertIs(got, photo)
        with mock.patch.object(config, "PERSON_ERA_IN_HOOK", False):
            got, calls = self._run(lambda q, kw: photo if kw.get("stage") == "pictures" else None,
                                   hook=True, start=0.0)
        self.assertIsNone(got)
        self.assertFalse(any(c["person"] for c in calls))

    def test_the_judge_reads_the_photo_s_page(self):
        path = os.path.join(tempfile.mkdtemp(), "p.jpg")
        with open(path, "wb") as fh:
            fh.write(b"x" * 64)
        seen = {}

        def judge(p, intent, context="", **kw):
            seen["intent"] = intent
            return None
        with mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "_local_check", return_value=None), \
                mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media.vision, "judge", side_effect=judge):
            tok = media._PERSON_PHOTO.set("Barack Obama")
            try:
                media._judge_gate(path, "A real period photograph of Barack Obama as a baby", "line",
                                  "Barack Obama with his mother Ann Dunham, 1962 - obamalibrary.gov")
            finally:
                media._PERSON_PHOTO.reset(tok)
        self.assertIn("[The picture's own page: Barack Obama with his mother Ann Dunham, 1962", seen["intent"])

    def test_the_photo_stays_where_the_hook_would_look_for_footage(self):
        jobs = [{"index": 0, "hook": True, "start": 0.0, "seconds": 4.0},
                {"index": 1, "hook": True, "start": 4.0, "seconds": 4.0}]
        era = MediaAsset(kind="image", source="web_image", url="https://x.org/a.jpg")
        era.score_parts = {"personEra": "Barack Obama"}
        plain = MediaAsset(kind="image", source="web_image", url="https://x.org/b.jpg")
        out = media.variety_violations(jobs, [era, plain])
        self.assertNotIn(0, out)
        self.assertEqual(out[1][1], "upgrade")

    def test_never_generated_and_no_living_layers_and_no_re_clip(self):
        self.assertFalse(media._may_generate_for({"person_era": self.PE, "hook": False}))
        from src import living, reclip
        scene = {"startFrame": 0, "durationInFrames": 300, "motion": "push-in",
                 "media": {"type": "image", "url": "x.jpg"},
                 "semanticMetadata": {"scoreParts": {"personEra": "Barack Obama"}}}
        self.assertTrue(reclip._person_era_photo(scene["semanticMetadata"]))
        self.assertEqual(living.scene_reason(scene, 30, []), "a period photo of a person")
        doc = {"fps": 30, "scenes": [scene]}
        self.assertEqual(reclip.plan_targets(doc, hook_seconds=60.0), [])


class PersonEraPhotoAtTheGate(unittest.TestCase):
    def test_the_check_before_the_render_holds_it_to_the_limit_it_was_chosen_under(self):
        from src import quality, sharpness
        from tests import test_sharpness as ts
        ts.TMP = tempfile.mkdtemp(prefix="pe_gate_")
        soft = ts.picture("pe_soft.jpg", real=0.5, seed=41)            # an archive print: about 2x blown up
        doc = ts._doc([("image", soft, "zoom-in"), ("image", soft, "zoom-in")])
        doc["scenes"][0]["semanticMetadata"]["scoreParts"] = {"personEra": "Barack Obama"}
        sharpness.reset()
        with mock.patch.multiple(config, **ts.ON), mock.patch.object(config, "PERSON_ERA_MAX_MAGNIFICATION", 3.0):
            found = quality.Gate(doc, ts.TMP)._soft_scenes(ts._checks(doc))
        self.assertEqual(list(found), [1])                               # only the other picture is too soft


class NewMexicoIsAState(unittest.TestCase):
    def test_the_state_never_reads_as_the_country(self):
        self.assertEqual(media._regions_in("Flash flooding in Ruidoso, New Mexico"), {"new mexico"})
        self.assertEqual(media._regions_in("Floods in Mexico City"), {"mexico"})


if __name__ == "__main__":
    unittest.main()
