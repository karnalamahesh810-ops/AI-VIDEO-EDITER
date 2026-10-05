"""
The opening's first second (the owner's 5-minute Glen Canyon test, 2026-10-05: "the first second or
two didn't match").

What the job's own output showed: scene s0000 (0.0-3.0 s, "On the 6th of June, 1983,") was another
moment of the clip beside it, taken by arithmetic (shotcap.find_moment: 30 s before that clip) with
no vision call, and s0001 (3.0-8.0 s) the rescue pass's best-titled search result cut 35 % into its
video, with no vision call either (media.rescue_fill). Neither had a relevanceScore or a description.
The frames of the published video: 0.00-1.43 s is the end of the source's previous shot - another
creator's "CAVITATION" explainer graphic - and the hard cut to the 1983 flashboard footage comes at
1.467 s. ffmpeg scored that cut 0.36, under the 0.4 the clean-cut trimming looked for, so its window
never saw it (the job recorded "cuts": 0).

  C. the judge's opening check (vision.judge `span`, acceptable)
  D. hook scenes are judged that way wherever they are sourced (media._judge_gate)
  E. the hook check on the finished timeline (src/hookcheck.py)
  F. the passes that used to place hook clips unseen (rescue, the shot cap's other moments)
  G. every pick's verdict on record (judgedBy, the tile's verdict for pool moments)

(A and B - finding the cut and opening after it, every clip of the video - are tests/test_clean_cuts.py.)
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import handler
from src import config, filters, gapfill, hookcheck, media, pools, shotcap, timeline, vision
from src.media import MediaAsset
from src.transcribe import Segment, Word

FPS = 30
VERDICT = {"description": "Plywood flashboards on top of the spillway gates, 1983", "score": 0.85,
           "quality": 0.7, "has_text_or_watermark": False, "is_talking_head": False, "ai_generated": False,
           "studio": False, "specificity": "event", "opening": True, "model": "test"}


# --------------------------------------------------------------------------- C. the opening check
class OpeningCheck(unittest.TestCase):
    def setUp(self):
        vision.reset()
        self.addCleanup(vision.reset)
        fd, self.path = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, b"a clip")
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def test_where_it_looks(self):
        self.assertEqual(vision.opening_times(3.0), [0.3, 1.5, 2.7])
        self.assertEqual(vision.opening_times(1.0), [0.25, 0.5, 0.7])
        self.assertEqual(vision.opening_times(5.0, duration=4.0), [0.3, 2.0, 3.7])   # never past the file

    def _judge(self, answer, **kw):
        seen = {}

        def frames(path, count=3, width=512, span=None):
            seen.setdefault("spans", []).append(span)
            return ["f1", "f2", "f3"]

        def ask(messages, max_tokens, accept=None):
            seen["text"] = messages[1]["content"][0]["text"]
            return answer, "test-model"
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "sample_frames", side_effect=frames), \
                mock.patch.object(vision, "_ask", side_effect=ask):
            return vision.judge(self.path, "June 6 1983 Glen Canyon Dam spillway", "On the 6th of June, 1983,",
                                **kw), seen

    def test_a_hook_clip_is_judged_on_its_first_moment_and_the_answer_decides(self):
        answer = ('{"description": "an explainer graphic, then flashboards", "score": 0.8, "quality": 0.7, '
                  '"has_text_or_watermark": false, "is_talking_head": false, "ai_generated": false, '
                  '"studio": false, "specificity": "event", "opening": false}')
        verdict, seen = self._judge(answer, span=3.0)
        self.assertEqual(seen["spans"], [3.0])
        self.assertIn("OPENING CHECK", seen["text"])
        self.assertIs(verdict["opening"], False)
        self.assertEqual(verdict["span"], 3.0)
        self.assertEqual(len(verdict["frames"]), 3)
        self.assertFalse(vision.acceptable(verdict))                  # 0.8, but its first frame is something else
        self.assertTrue(vision.acceptable(dict(verdict, opening=True)))

    def test_without_a_span_nothing_changes(self):
        answer = ('{"description": "flashboards", "score": 0.8, "quality": 0.7, "has_text_or_watermark": false, '
                  '"is_talking_head": false, "ai_generated": false, "studio": false, "opening": false}')
        verdict, seen = self._judge(answer)
        self.assertEqual(seen["spans"], [None])
        self.assertNotIn("OPENING CHECK", seen["text"])
        self.assertIsNone(verdict["opening"])                         # not asked: never read as an answer
        self.assertNotIn("frames", verdict)
        self.assertTrue(vision.acceptable(verdict))

    def test_the_answer_is_read_in_any_spelling(self):
        base = '{"description": "x", "score": 0.8%s}'
        self.assertIs(vision._parse(base % ', "opening": "false"')["opening"], False)
        self.assertIs(vision._parse(base % ', "opening": "yes"')["opening"], True)
        self.assertIsNone(vision._parse(base % "")["opening"])

    def test_what_it_said_is_kept_with_the_cut(self):
        verdict = dict(VERDICT, frames=[0.3, 1.5, 2.7], span=3.0, accepted=True)
        rec = vision.cut_record(verdict)
        self.assertEqual((rec["frames"], rec["span"], rec["opening"], rec["ok"]), ([0.3, 1.5, 2.7], 3.0, True, True))
        self.assertEqual(vision.cut_record(dict(VERDICT)), {})
        a = MediaAsset(kind="video", source="youtube", url="u").apply_verdict(verdict, "intent")
        self.assertEqual((a.judged_by, a.cut_check["ok"], a.relevance_score), ("opening", True, 0.85))
        b = MediaAsset(kind="video", source="youtube", url="u").apply_verdict(dict(VERDICT, opening=None), "intent")
        self.assertEqual((b.judged_by, b.cut_check), ("frames", {}))


# --------------------------------------------------------------------------- D. wherever a hook clip is judged
class HookScenesGetTheOpeningCheck(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, b"a clip")
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def _spans(self, job, path=None, **conf):
        got = []

        def judge(path, intent, context="", **kw):
            got.append(kw.get("span"))
            return dict(VERDICT, frames=[0.3, 1.5, 2.7], span=kw.get("span")) if kw.get("span") else dict(VERDICT)
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "judge", side_effect=judge), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(config, "LOCAL_VISION_ENABLED", False), \
                mock.patch.multiple(config, **({"HOOK_CUT_CHECK": True} | conf)):
            keep, verdict = media.judge_clip(path or self.path, job, "a title")
        return got, keep, verdict

    def test_a_hook_line_is_judged_on_what_its_scene_shows(self):
        spans, keep, verdict = self._spans({"intent": "Glen Canyon Dam 1983", "seconds": 3.0, "hook": True})
        self.assertEqual(spans, [3.0])
        self.assertTrue(keep)
        self.assertTrue(verdict["accepted"])                           # the gate's own decision goes with it

    def test_other_lines_stills_and_the_switch_keep_the_old_judge(self):
        self.assertEqual(self._spans({"intent": "x", "seconds": 3.0, "hook": False})[0], [None])
        self.assertEqual(self._spans({"intent": "x", "seconds": 3.0, "hook": True}, HOOK_CUT_CHECK=False)[0], [None])
        fd, still = tempfile.mkstemp(suffix=".jpg")
        os.write(fd, b"a picture")
        os.close(fd)
        self.addCleanup(os.remove, still)
        with mock.patch.object(media, "watermark_reason", return_value=""):
            self.assertEqual(self._spans({"intent": "x", "seconds": 3.0, "hook": True}, path=still)[0], [None])

    def test_the_hook_search_judges_with_the_lines_seconds(self):
        seen = []
        with mock.patch.object(media, "_source_one",
                               side_effect=lambda *a, **k: seen.append(media._opening_span(self.path)) or None), \
                mock.patch.object(config, "HOOK_CUT_CHECK", True):
            media.source_for_segment("glen canyon dam", 4.2, tempfile.gettempdir(), hook=True, fallbacks=[])
            media.source_for_segment("glen canyon dam", 4.2, tempfile.gettempdir(), hook=False, fallbacks=[])
        self.assertEqual(seen[0], 4.2)
        self.assertIsNone(seen[-1])


# --------------------------------------------------------------------------- E. the hook check
def scene(i, media_, start, seconds, **sem):
    return {"id": f"s{i:04d}", "startFrame": int(round(start * FPS)), "durationInFrames": int(round(seconds * FPS)),
            "text": f"line {i}", "query": f"query {i}", "media": dict(media_), "visualType": "footage",
            "semanticMetadata": {"intent": f"what line {i} shows", **sem}, "words": [], "reviewRequired": False,
            "reviewReason": ""}


class TheHookCheck(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, True)
        gapfill.reset()
        hookcheck.reset()
        self.addCleanup(gapfill.reset)
        self.addCleanup(hookcheck.reset)
        for p in (mock.patch.object(vision, "enabled", return_value=True),
                  mock.patch.multiple(config, HOOK_CUT_CHECK=True, HOOK_SECONDS=45.0, HOOK_CUT_TRIES=2,
                                      HOOK_CUT_MAX_CALLS=30),
                  # Never a real download (a test that wants one patches it again).
                  mock.patch.object(media, "fetch_clean_clip", return_value=("", True, 0))):
            p.start()
            self.addCleanup(p.stop)

    def file(self, name):
        path = os.path.join(self.work, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        return path

    def glen_canyon(self):
        """The test video's opening as the job left it: two clips nothing had looked at."""
        first = self.file("yt_R_z4cbZu3Ok_184600_7500_5537c29777_c00020.mp4")
        second = self.file("yt_R_z4cbZu3Ok_218150_9040_26e2cb57a0_c00020.mp4")
        later = self.file("yt_iWFGATBYefY_134000_7080_b8e11280c0_c00020.mp4")
        doc = {"fps": FPS, "overlays": [], "meta": {}, "scenes": [
            scene(0, {"type": "video", "url": first, "source": "youtube", "clipSeconds": 4.0}, 0.0, 3.0,
                  assetId="yt:R_z4cbZu3Ok@23", moment={"chain": True, "start": 186.6},
                  sourceUrl="https://www.youtube.com/watch?v=R_z4cbZu3Ok&t=186", relevanceScore=None,
                  contentDescription="", shotCap={"from": "s0001", "how": "moment"}),
            scene(1, {"type": "video", "url": second, "source": "youtube", "clipSeconds": 5.57}, 3.0, 5.03,
                  assetId="yt:R_z4cbZu3Ok@22", moment={"rescue": True, "start": 220.1},
                  sourceUrl="https://www.youtube.com/watch?v=R_z4cbZu3Ok&t=220", relevanceScore=None),
            scene(2, {"type": "video", "url": later, "source": "youtube", "clipSeconds": 7.08}, 86.8, 2.6,
                  assetId="yt:iWFGATBYefY@17", relevanceScore=0.8, judgedBy="tile")]}
        return doc, first, second

    def test_the_glen_canyon_opening_is_judged_and_its_first_clip_starts_after_the_cut(self):
        doc, first, second = self.glen_canyon()
        doc["scenes"][0]["media"]["clipSeconds"] = 5.0
        moved = os.path.join(self.work, "moved.mp4")
        verdicts = {first: dict(VERDICT, opening=False, score=0.8, description="a CAVITATION graphic, then plywood"),
                    moved: dict(VERDICT), second: dict(VERDICT, score=0.8, description="An engineer at a blackboard")}
        calls = []

        def judge(path, intent, context="", **kw):
            calls.append((os.path.basename(path), kw.get("span")))
            return dict(verdicts[path], frames=vision.opening_times(kw["span"]), span=kw["span"])

        def trim(path, offset, seconds, timeout=180):
            with open(moved, "wb") as fh:
                fh.write(b"y")
            return moved
        # A file that runs on 2 s past what its scene shows: room to start after the cut at 1.467 s.
        with mock.patch.object(vision, "judge", side_effect=judge), \
                mock.patch.object(filters, "_video_seconds", side_effect=lambda p: 5.0 if p == first else 3.4), \
                mock.patch.object(filters, "scene_cuts", side_effect=lambda p, *a, **k: [1.467] if p == first else []), \
                mock.patch.object(filters, "trim_clip", side_effect=trim):
            out = hookcheck.check(doc, work=self.work)
        # Two clips in the hook, each judged on its own cut - side by side - and the first once more, moved.
        span1 = doc["scenes"][1]["durationInFrames"] / FPS
        self.assertEqual(sorted(calls[:2]), sorted([(os.path.basename(first), 3.0), (os.path.basename(second), span1)]))
        self.assertEqual(calls[2:], [("moved.mp4", 3.0)])
        self.assertEqual((out["checked"], out["kept"], out["moved"], out["cleared"]), (2, 1, 1, 0))
        s0, s1 = doc["scenes"][0], doc["scenes"][1]
        self.assertEqual(s0["media"]["url"], moved)
        self.assertEqual(s0["media"]["clipSeconds"], 3.4)
        sem = s0["semanticMetadata"]
        self.assertAlmostEqual(sem["cutCheck"]["moved"], 1.467 + config.CUT_SNAP_PAD, places=2)
        self.assertAlmostEqual(sem["moment"]["start"], round(186.6 + 1.467 + config.CUT_SNAP_PAD, 1))
        self.assertEqual((sem["judgedBy"], sem["relevanceScore"], sem["cutCheck"]["opening"]), ("opening", 0.85, True))
        # The verdict is on record for the editor and the later checks (the job had none).
        self.assertEqual(s1["semanticMetadata"]["relevanceScore"], 0.8)
        self.assertEqual(s1["semanticMetadata"]["contentDescription"], "An engineer at a blackboard")
        self.assertEqual(s1["media"]["relevanceScore"], 0.8)
        self.assertEqual(doc["scenes"][2]["semanticMetadata"]["judgedBy"], "tile")     # after the hook: untouched

    def test_the_job_s_own_clip_is_cut_again_from_the_moment_the_judge_saw_fit(self):
        # The job's real geometry: a 4.0 s file for a 3.0 s scene, the cut 1.467 s in - starting
        # after it inside the file would leave 2.4 s (it would be slowed), so it is cut again.
        doc, first, second = self.glen_canyon()
        refetched = self.file("yt_R_z4cbZu3Ok_186100_7500_0123456789_c00020.mp4")
        fetches = []

        def judge(path, intent, context="", **kw):
            v = dict(VERDICT, opening=False, score=0.8) if path == first else dict(VERDICT)
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])

        def fetch(vid, work, at, need, title=""):
            fetches.append((vid, round(at, 2), round(need, 2)))
            return refetched, True, 0
        with mock.patch.object(vision, "judge", side_effect=judge), \
                mock.patch.object(filters, "_video_seconds", side_effect=lambda p: 4.0 if p == first else 3.5), \
                mock.patch.object(filters, "scene_cuts", side_effect=lambda p, *a, **k: [1.467] if p == first else []), \
                mock.patch.object(filters, "trim_clip", side_effect=AssertionError("too short to move inside")), \
                mock.patch.object(media, "fetch_clean_clip", side_effect=fetch):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual(out["moved"], 1)
        # From 186.6 s (its file's own name) + the middle frame (1.5 s): the moment the judge saw fit.
        self.assertEqual(fetches, [("R_z4cbZu3Ok", 188.1, round(3.0 + media.SEQ_SHOT_PAD, 2))])
        self.assertEqual(doc["scenes"][0]["media"]["url"], refetched)
        self.assertIn("t=188", doc["scenes"][0]["semanticMetadata"]["sourceUrl"])

    def test_a_title_card_on_the_first_frame_scored_0_is_still_cut_again(self):
        # The defect this check exists for: the judge is told to score a title card 0 with text, so the
        # verdict's score says nothing about the middle - the re-cut from it is judged on its own.
        doc, first, second = self.glen_canyon()
        refetched = self.file("yt_R_z4cbZu3Ok_186100_7500_0123456789_c00020.mp4")
        fetches = []

        def judge(path, intent, context="", **kw):
            v = (dict(VERDICT, opening=False, score=0.0, has_text_or_watermark=True) if path == first
                 else dict(VERDICT))
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])

        def fetch(vid, work, at, need, title="", **kw):
            fetches.append(round(at, 2))
            return refetched, True, 0
        with mock.patch.object(vision, "judge", side_effect=judge),                 mock.patch.object(filters, "_video_seconds", side_effect=lambda p: 3.5 if p == first else 3.5),                 mock.patch.object(filters, "scene_cuts", return_value=[]),                 mock.patch.object(filters, "trim_clip", return_value=""),                 mock.patch.object(media, "fetch_clean_clip", side_effect=fetch),                 mock.patch.object(gapfill, "hold_or_animate", return_value={}):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual(fetches, [188.1])
        self.assertEqual((out["moved"], out["cleared"]), (1, 0))
        self.assertEqual(doc["scenes"][0]["media"]["url"], refetched)

    def _recut_case(self):
        """The Glen Canyon clip turned down for its first frame, no room to move inside its file."""
        doc, first, second = self.glen_canyon()
        seen = []

        def judge(path, intent, context="", **kw):
            vision._counted()
            v = dict(VERDICT, opening=False, score=0.8) if path == first else dict(VERDICT)
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])

        def fetch(vid, work, at, need, title="", **kw):
            from src import ytdlp
            seen.append({"stop": ytdlp.STOP.get(), "stopped": ytdlp.stopped(), "spent": hookcheck.spent(),
                         "vision": vision.enabled()})
            return "", True, 0
        return doc, first, judge, fetch, seen

    def test_a_re_cut_is_never_downloaded_when_no_verdict_could_follow(self):
        doc, first, judge, fetch, seen = self._recut_case()
        # Its own check took the last call: nothing to judge a new cut with.
        with mock.patch.object(config, "HOOK_CUT_MAX_CALLS", 1),                 mock.patch.object(vision, "judge", side_effect=judge),                 mock.patch.object(filters, "_video_seconds", return_value=3.2),                 mock.patch.object(filters, "scene_cuts", return_value=[]),                 mock.patch.object(media, "fetch_clean_clip", side_effect=fetch),                 mock.patch.object(gapfill, "hold_or_animate", return_value={}):
            hookcheck.check(doc, work=self.work)
        self.assertEqual(seen, [])
        # Vision gone (out of credits) after the verdict: the same.
        doc, first, judge, fetch, seen = self._recut_case()
        verdict = dict(VERDICT, opening=False, score=0.8, frames=[0.3, 1.5, 2.7], span=3.0)
        with mock.patch.object(vision, "enabled", return_value=False),                 mock.patch.object(filters, "_video_seconds", return_value=3.2),                 mock.patch.object(filters, "scene_cuts", return_value=[]),                 mock.patch.object(media, "fetch_clean_clip", side_effect=fetch):
            self.assertFalse(hookcheck.move_start(doc["scenes"][0], first, {"intent": "x"}, 3.0, verdict,
                                                  self.work, cover=3.0))
        self.assertEqual(seen, [])

    def test_a_re_cut_keeps_to_a_time_box(self):
        import time as _time
        doc, first, judge, fetch, seen = self._recut_case()
        with mock.patch.object(vision, "judge", side_effect=judge),                 mock.patch.object(filters, "_video_seconds", return_value=3.2),                 mock.patch.object(filters, "scene_cuts", return_value=[]),                 mock.patch.object(media, "fetch_clean_clip", side_effect=fetch),                 mock.patch.object(gapfill, "hold_or_animate", return_value={}):
            hookcheck.check(doc, work=self.work)
        self.assertEqual(len(seen), 1)
        box, own = seen[0]["stop"]
        self.assertIsNone(box)
        self.assertLessEqual(own, _time.time() + config.FALLBACK_SCENE_SECONDS)   # retries stop there
        self.assertFalse(seen[0]["stopped"])
        # The whole check's box already closed: not fetched.
        doc, first, judge, fetch, seen = self._recut_case()
        verdict = dict(VERDICT, opening=False, score=0.8, frames=[0.3, 1.5, 2.7], span=3.0)
        with mock.patch.object(filters, "_video_seconds", return_value=3.2),                 mock.patch.object(filters, "scene_cuts", return_value=[]),                 mock.patch.object(media, "fetch_clean_clip", side_effect=fetch):
            self.assertFalse(hookcheck.move_start(doc["scenes"][0], first, {"intent": "x"}, 3.0, verdict,
                                                  self.work, cover=3.0, until=_time.time() - 1))
        self.assertEqual(seen, [])

    def test_a_moved_start_never_leaves_a_clip_the_renderer_would_slow(self):
        # A crossfade into the next scene plays this clip 0.5 s longer (quality.scene_need): a 4.0 s file
        # past its cut at 0.6 s would cover 3.3 s of the 3.5 s it must.
        doc, first, second = self.glen_canyon()
        doc["scenes"][1]["transition"] = "crossfade"
        with mock.patch.object(vision, "judge", side_effect=lambda p, *a, **k: dict(
                    VERDICT, opening=p != first, score=0.6 if p == first else 0.85, frames=[0.3, 1.5, 2.7],
                    span=k["span"])), \
                mock.patch.object(filters, "_video_seconds", return_value=4.0), \
                mock.patch.object(filters, "scene_cuts", return_value=[0.6]), \
                mock.patch.object(filters, "trim_clip", side_effect=AssertionError("would be slowed")), \
                mock.patch.object(gapfill, "hold_or_animate", return_value={}):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual((out["moved"], out["cleared"]), (0, 1))      # (its re-cut comes back empty here)

    def test_a_clip_turned_down_takes_a_runner_up_that_passes(self):
        doc, first, second = self.glen_canyon()
        good = self.file("alt_good.mp4")
        bad = self.file("alt_bad.mp4")
        doc["scenes"][0]["semanticMetadata"]["alternatives"] = [
            {"assetId": "yt:ALTBAD00001@3", "url": "https://www.youtube.com/watch?v=ALTBAD00001&t=30",
             "score": 0.9, "localPath": bad, "seconds": 4.0, "moment": {"start": 30.0}, "source": "youtube"},
            {"assetId": "yt:ALTGOOD0001@5", "url": "https://www.youtube.com/watch?v=ALTGOOD0001&t=50",
             "score": 0.8, "localPath": good, "seconds": 4.0, "moment": {"start": 50.0}, "source": "youtube"}]

        def judge(path, intent, context="", **kw):
            if path in (first, bad):
                v = dict(VERDICT, has_text_or_watermark=True, score=0.0)
            else:
                v = dict(VERDICT)
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])
        with mock.patch.object(vision, "judge", side_effect=judge), \
                mock.patch.object(filters, "_video_seconds", return_value=4.0), \
                mock.patch.object(filters, "scene_cuts", return_value=[]), \
                mock.patch.object(shotcap, "_probe", return_value=4.0):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual((out["swapped"], out["cleared"]), (1, 0))
        s0 = doc["scenes"][0]
        self.assertEqual(s0["media"]["url"], good)
        self.assertEqual(s0["semanticMetadata"]["cutCheck"]["ok"], True)
        self.assertIn("hook check", s0["reviewReason"])

    def test_nothing_that_passes_leaves_the_line_to_the_last_resort(self):
        doc, first, second = self.glen_canyon()
        # A mark vision placed on the clip that goes (src/marks.py) goes with it; one on another scene stays.
        doc["overlays"] = [{"type": "LIB_VM_ARROW", "startFrame": 30, "durationInFrames": 45, "anchor": {"x": 0.4}},
                           {"type": "LIB_VM_ARROW", "startFrame": 120, "durationInFrames": 45, "anchor": {"x": 0.5}},
                           {"type": "LIB_VR_DATE_HERO", "startFrame": 0, "durationInFrames": 66}]
        calls = []

        def last_resort(d, **kw):
            calls.append(kw)
            return {"graphic": 0, "held": 1, "card": 0, "hook": 1}

        def judge(path, intent, context="", **kw):
            v = dict(VERDICT, studio=True, score=0.2) if path == first else dict(VERDICT)
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])
        with mock.patch.object(vision, "judge", side_effect=judge), \
                mock.patch.object(filters, "_video_seconds", return_value=4.0), \
                mock.patch.object(filters, "scene_cuts", return_value=[]), \
                mock.patch.object(gapfill, "hold_or_animate", side_effect=last_resort):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual(out["cleared"], 1)
        self.assertEqual(doc["scenes"][0]["media"]["type"], "color")
        sem = doc["scenes"][0]["semanticMetadata"]
        self.assertEqual(sem["hookCheck"]["turnedDown"]["why"], "a studio, presenter or screen")
        self.assertNotIn("relevanceScore", sem)                       # the clip that went takes its verdict along
        self.assertEqual([o["startFrame"] for o in doc["overlays"]], [120, 0])
        # Fresh shots first (each then checked the same way), and nothing is left to a second round.
        self.assertEqual(calls[0]["fresh"], True)
        self.assertEqual(calls[0]["search"], True)
        self.assertEqual(out["lastResort"]["held"], 1)

    def test_a_near_miss_whose_opening_fits_stays_flagged_when_nothing_beats_it(self):
        doc, first, second = self.glen_canyon()

        def judge(path, intent, context="", **kw):
            v = dict(VERDICT, score=0.6) if path == first else dict(VERDICT)
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])
        with mock.patch.object(vision, "judge", side_effect=judge), \
                mock.patch.object(filters, "_video_seconds", return_value=4.0), \
                mock.patch.object(filters, "scene_cuts", return_value=[]), \
                mock.patch.object(gapfill, "hold_or_animate") as last:
            out = hookcheck.check(doc, work=self.work)
        last.assert_not_called()
        self.assertEqual((out["keptUnderFloor"], out["cleared"]), (1, 0))
        s0 = doc["scenes"][0]
        self.assertEqual(s0["media"]["url"], first)
        self.assertTrue(s0["reviewRequired"])
        self.assertIn("Best available", s0["reviewReason"])
        self.assertEqual(s0["semanticMetadata"]["relevanceScore"], 0.6)

    def test_no_verdict_never_empties_the_opening(self):
        doc, first, second = self.glen_canyon()
        with mock.patch.object(vision, "judge", return_value=None):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual((out["unjudged"], out["cleared"]), (2, 0))
        self.assertEqual(doc["scenes"][0]["media"]["url"], first)
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["cutCheck"], {"ok": None, "unjudged": True})

    def test_a_cut_already_checked_costs_nothing_and_the_calls_are_capped(self):
        doc, first, second = self.glen_canyon()
        doc["scenes"][1]["semanticMetadata"]["cutCheck"] = {"frames": [0.3, 2.5, 4.7], "span": 5.03,
                                                            "opening": True, "score": 0.8, "ok": True}
        with mock.patch.object(vision, "judge", return_value=dict(VERDICT, frames=[0.3, 1.5, 2.7], span=3.0)) as j:
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual(j.call_count, 1)                              # only the clip nothing had checked
        self.assertEqual(out["checked"], 1)
        doc, first, second = self.glen_canyon()
        hookcheck.reset()

        def a_call(*a, **k):
            vision._counted()                                          # what a real model call counts
            return dict(VERDICT, frames=[0.3, 1.5, 2.7], span=3.0)
        with mock.patch.object(config, "HOOK_CUT_MAX_CALLS", 1), \
                mock.patch.object(vision, "judge", side_effect=a_call) as j:
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual(j.call_count, 1)
        self.assertTrue(out.get("budgetSpent"))
        self.assertEqual(out["calls"], 1)

    def many_clips(self, n):
        """A hook of n 3-second clips nothing had checked."""
        doc = {"fps": FPS, "overlays": [], "meta": {}, "scenes": []}
        for k in range(n):
            path = self.file(f"yt_CLIP{k:07d}_{10000 * (k + 1)}_7500_abcdef0123_c00020.mp4")
            doc["scenes"].append(scene(k, {"type": "video", "url": path, "source": "youtube", "clipSeconds": 3.5},
                                       3.0 * k, 3.0, assetId=f"yt:CLIP{k:07d}@1"))
        return doc

    def test_judges_side_by_side_count_only_their_own_calls(self):
        # Each judge read its spend off the shared count of model calls, so four judging at once each
        # counted the others' calls too: 12 clips, 12 calls, counted as ~40 - the cap of 30 "spent".
        import time as _time
        doc = self.many_clips(12)

        def a_call(*a, **k):
            _time.sleep(0.05)
            vision._counted()
            return dict(VERDICT, frames=[0.3, 1.5, 2.7], span=k.get("span"))
        with mock.patch.object(vision, "judge", side_effect=a_call):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual((out["checked"], out["kept"]), (12, 12))
        self.assertNotIn("budgetSpent", out)
        self.assertEqual(hookcheck.left(), 30 - 12)
        # A remembered verdict (no model call) costs nothing.
        with mock.patch.object(vision, "judge", return_value=dict(VERDICT, frames=[0.3, 1.5, 2.7], span=3.0)):
            hookcheck.judge(self.file("again.mp4"), {"intent": "x", "seconds": 3.0}, 3.0)
        self.assertEqual(hookcheck.left(), 30 - 12)

    def test_the_last_calls_are_never_handed_out_twice(self):
        import threading
        import time as _time
        started = []

        def a_call(*a, **k):
            started.append(1)
            _time.sleep(0.05)
            vision._counted()
            return dict(VERDICT, frames=[0.3, 1.5, 2.7], span=3.0)
        path = self.file("one.mp4")
        with mock.patch.object(config, "HOOK_CUT_MAX_CALLS", 3), mock.patch.object(vision, "judge", side_effect=a_call):
            threads = [threading.Thread(target=hookcheck.judge, args=(path, {"intent": "x", "seconds": 3.0}, 3.0))
                       for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(started), 3)
            self.assertTrue(hookcheck.spent())

    def test_a_runner_up_nobody_could_judge_never_takes_the_opening(self):
        doc, first, second = self.glen_canyon()
        alt = self.file("alt_unjudged.mp4")
        runner = {"assetId": "yt:ALTNONE0001@3", "url": "https://www.youtube.com/watch?v=ALTNONE0001&t=30",
                  "score": 0.9, "localPath": alt, "seconds": 4.0, "moment": {"start": 30.0}, "source": "youtube"}
        doc["scenes"][0]["semanticMetadata"]["alternatives"] = [runner]

        def judge(path, intent, context="", **kw):
            if path == alt:
                return None                                            # no verdict (every model failing)
            v = dict(VERDICT, has_text_or_watermark=True, score=0.0) if path == first else dict(VERDICT)
            return dict(v, frames=vision.opening_times(kw["span"]), span=kw["span"])
        with mock.patch.object(vision, "judge", side_effect=judge),                 mock.patch.object(filters, "_video_seconds", return_value=4.0),                 mock.patch.object(filters, "scene_cuts", return_value=[]),                 mock.patch.object(shotcap, "_probe", return_value=4.0),                 mock.patch.object(gapfill, "hold_or_animate", return_value={}):
            out = hookcheck.check(doc, work=self.work)
        self.assertEqual((out["swapped"], out["cleared"]), (0, 1))
        s0 = doc["scenes"][0]
        self.assertEqual(s0["media"]["type"], "color")                # not the unjudged runner-up
        self.assertEqual(s0["semanticMetadata"]["hookCheck"]["turnedDown"]["assetId"], "yt:R_z4cbZu3Ok@23")
        self.assertEqual([a["assetId"] for a in s0["semanticMetadata"]["alternatives"]], ["yt:ALTNONE0001@3"])

    def test_off_changes_nothing(self):
        doc, first, second = self.glen_canyon()
        with mock.patch.object(config, "HOOK_CUT_CHECK", False), mock.patch.object(vision, "judge") as j:
            self.assertEqual(handler._hook_check(doc, self.work), {})
        j.assert_not_called()

    def test_the_handler_keeps_the_report(self):
        doc, first, second = self.glen_canyon()
        with mock.patch.object(vision, "judge", return_value=dict(VERDICT, frames=[0.3, 1.5, 2.7], span=3.0)):
            got = handler._hook_check(doc, self.work)
        self.assertEqual(doc["meta"]["hookCheck"], got)
        self.assertEqual(got["kept"], 2)


# --------------------------------------------------------------------------- F. the passes that placed them
class RescueAndMomentsInTheHook(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, True)
        hookcheck.reset()
        self.addCleanup(hookcheck.reset)

    def _rescue(self, hook):
        files = {}

        def fetch(vid, work, point, need, title=""):
            files[vid] = os.path.join(work, f"yt_{vid}_0_9000_abcdef0123_c00020.mp4")
            with open(files[vid], "wb") as fh:
                fh.write(b"x")
            return files[vid], True, 0

        judged = []

        def judge(path, intent, context="", **kw):
            judged.append((os.path.basename(path), kw.get("span")))
            opening = len(judged) > 1                                   # the best-ranked opens on another shot
            return dict(VERDICT, opening=opening, frames=[0.3, 1.5, 2.7], span=kw.get("span"))
        jobs = [{"index": 0, "query": "Glen Canyon Dam spillway 1983", "seconds": 3.0, "visual_type": "footage",
                 "intent": "Glen Canyon Dam spillway June 1983", "subject": "Glen Canyon Dam", "hook": hook}]
        cands = [{"id": "aaaaaaaaaaa", "title": "Glen Canyon Dam spillway 1983 crisis", "duration": 600.0},
                 {"id": "bbbbbbbbbbb", "title": "Glen Canyon Dam spillway 1983 footage", "duration": 500.0}]
        results = [None]
        with mock.patch.multiple(config, FRESH_MOMENTS=False, HOOK_CUT_CHECK=True), \
                mock.patch.object(media, "_yt_candidates", return_value=cands), \
                mock.patch.object(media, "fetch_clean_clip", side_effect=fetch), \
                mock.patch.object(media._filters, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "motion_rejects", return_value=""), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_rescue_local_ok", return_value=True), \
                mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "judge", side_effect=judge):
            media.rescue_fill(jobs, results, self.work, footage_only={0} if hook else ())
        return results[0], judged

    def test_a_hook_line_never_takes_a_rescue_clip_unseen(self):
        unseen, _ = self._rescue(hook=False)
        got, judged = self._rescue(hook=True)
        self.assertEqual([j[1] for j in judged], [3.0, 3.0])          # the first turned down, the next judged
        self.assertNotIn(unseen.url.split("&")[0], got.url)           # not the clip it used to take unseen
        self.assertEqual((got.judged_by, got.relevance_score), ("opening", 0.85))
        self.assertTrue(got.cut_check["ok"])
        self.assertIn("opening check passed", got.review_reason)

    def test_other_lines_cost_no_vision_call(self):
        got, judged = self._rescue(hook=False)
        self.assertEqual(judged, [])
        self.assertIsNotNone(got)
        self.assertIn(got.judged_by, ("local", "none"))

    def _moment(self, start, verdict):
        """Scene 1 empty beside a YouTube clip: shotcap's other moment of it, with this verdict."""
        a = os.path.join(self.work, "a.mp4")
        with open(a, "wb") as fh:
            fh.write(b"x")
        doc = {"fps": FPS, "overlays": [], "meta": {}, "scenes": [
            scene(0, {"type": "video", "url": a, "source": "youtube", "clipSeconds": 6.5}, start, 6.0,
                  assetId="yt:LEFT0000001@5", moment={"start": 40.0},
                  sourceUrl="https://www.youtube.com/watch?v=LEFT0000001&t=40"),
            scene(1, {"type": "color", "url": "", "source": "none"}, start + 6.0, 5.0)]}
        gapfill.remember([{"index": i, "query": f"q{i}", "start": start + 6.0 * i} for i in range(2)], self.work)
        self.addCleanup(gapfill.reset)

        def fetch(vid, work, at, need, title=""):
            p = os.path.join(work, f"yt_{vid}_{int(at * 1000)}_9000_abcdef0123_c00020.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p, True, 0
        from src import ledger
        judged = []
        used = gapfill.Used()
        with mock.patch.object(media, "fetch_clean_clip", side_effect=fetch), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "motion_rejects", return_value=""), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(ledger, "moment_used", return_value=False), \
                mock.patch.object(timeline, "_clip_seconds", side_effect=lambda x: float(x.duration or 0)), \
                mock.patch.multiple(config, HOOK_CUT_CHECK=True, HOOK_SECONDS=45.0, SHOT_MAX_SECONDS=7.0), \
                mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "judge",
                                  side_effect=lambda p, *a, **k: judged.append(k.get("span")) or verdict):
            shotcap.FAILED_MOMENTS.clear()
            got = shotcap.other_moments(doc, [1], used, self.work, __import__("time").time() + 30)
        return doc, got, judged

    def test_another_moment_for_a_hook_line_is_judged_before_it_goes_on(self):
        ok = dict(VERDICT, frames=[0.3, 2.5, 4.7], span=5.0)
        doc, got, judged = self._moment(0.0, ok)
        self.assertEqual(list(got), [1])
        self.assertEqual(judged, [5.0])
        sem = doc["scenes"][1]["semanticMetadata"]
        self.assertEqual((sem["judgedBy"], sem["relevanceScore"], sem["cutCheck"]["ok"]), ("opening", 0.85, True))
        doc, got, judged = self._moment(0.0, dict(ok, opening=False))
        self.assertEqual(got, {})                                     # turned down: never on the line
        self.assertEqual(len(judged), 2)                              # 30 s after the clip, then before it

    def test_a_moment_after_the_hook_costs_no_vision_call(self):
        doc, got, judged = self._moment(120.0, dict(VERDICT))
        self.assertEqual(list(got), [1])
        self.assertEqual(judged, [])
        self.assertEqual(doc["scenes"][1]["semanticMetadata"]["judgedBy"], "none")


# --------------------------------------------------------------------------- G. verdicts on record
class VerdictsOnRecord(unittest.TestCase):
    def test_a_pool_moment_keeps_its_tiles_verdict_marked_as_a_tiles(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "yt_POOL0000001_10000_9000_abcdef0123_c00020.mp4")
        with open(path, "wb") as fh:
            fh.write(b"x")
        with mock.patch.object(media, "fetch_clean_clip", return_value=(path, True, 0)), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "motion_rejects", return_value=""), \
                mock.patch.object(media, "clip_detail_reason", return_value=""), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(config, "POOL_JUDGE_CLIPS", False):
            a = pools._fetch({"index": 3, "seconds": 4.0, "intent": "Lake Powell"},
                             {"id": "POOL0000001", "title": "Lake Powell 4K"},
                             {"start": 12.0, "score": 0.8, "description": "Lake Powell from the water"},
                             d, False, "Lake Powell")
        self.assertEqual((a.judged_by, a.relevance_score, a.content_description),
                         ("tile", 0.8, "Lake Powell from the water"))

    def test_the_timeline_and_the_fallbacks_write_how_a_verdict_was_reached(self):
        words = [Word(text="Lake", start=0.0, end=0.3), Word(text="Powell", start=0.3, end=0.6)]
        segs = [Segment(text="Lake Powell", start=0.0, end=4.0, words=words),
                Segment(text="Lake Powell again", start=4.0, end=8.0, words=words)]
        shots = [{"query": "lake powell", "visualType": "footage", "subject": "Lake Powell", "overlay": None}] * 2
        tile = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=POOL0000001&t=12",
                          local_path="/w/a.mp4", relevance_score=0.8, content_description="from the water",
                          judged_by="tile")
        hook = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=HOOK0000001&t=5",
                          local_path="/w/b.mp4").apply_verdict(dict(VERDICT, frames=[0.3, 2.0, 3.7], span=4.0,
                                                                    accepted=True), "Lake Powell")
        with mock.patch.object(timeline, "_clip_seconds", return_value=6.0), \
                mock.patch.multiple(config, TREATMENTS=False, ANIMATION_FILL=False):
            doc = timeline.build(segs, shots, [tile, hook], audio_url="file:///tmp/vo.mp3", audio_duration=8.0,
                                 inp={})
        a, b = (s["semanticMetadata"] for s in doc["scenes"])
        self.assertEqual((a["judgedBy"], a["relevanceScore"], a["contentDescription"]), ("tile", 0.8, "from the water"))
        self.assertNotIn("cutCheck", a)
        self.assertEqual((b["judgedBy"], b["cutCheck"]["ok"], b["cutCheck"]["frames"]), ("opening", True, [0.3, 2.0, 3.7]))
        # A fallback replacing a shot takes the old shot's check off with it.
        gapfill.apply_asset(doc["scenes"][1], tile)
        self.assertEqual(doc["scenes"][1]["semanticMetadata"]["judgedBy"], "tile")
        self.assertNotIn("cutCheck", doc["scenes"][1]["semanticMetadata"])

    def test_a_chain_is_marked_as_the_clip_befores_verdict(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "chain.mp4")
        with open(path, "wb") as fh:
            fh.write(b"x")
        prev = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=PREV0000001&t=40",
                          local_path=os.path.join(d, "prev.mp4"), relevance_score=0.9, judged_by="opening",
                          cut_check={"ok": True, "frames": [0.3, 1.5, 2.7]}, moment={"start": 40.0})
        jobs = [{"index": 0, "seconds": 3.0}, {"index": 1, "seconds": 3.0, "scene_intent": {"role": "chain"}}]
        results = [prev, None]
        with mock.patch.object(media, "fetch_clean_clip", return_value=(path, True, 0)), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "motion_rejects", return_value=""), \
                mock.patch.object(media, "slop_reason", return_value=""):
            self.assertEqual(media.fill_chains(jobs, results, d), 1)
        self.assertEqual((results[1].judged_by, results[1].cut_check), ("chain", {}))


if __name__ == "__main__":
    unittest.main()
