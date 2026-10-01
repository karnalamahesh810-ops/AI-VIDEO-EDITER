"""
Every scene filled, nothing shown twice (src/gapfill.py).

The owner's 159-scene Lake Powell video (2026-10-01, a pod job) ran out of
its 40-minute sourcing budget: 47 scenes were filled by reusing clips already
shown and the last 23 scenes in story order were left empty. His rules: never
reuse a clip within a video, never leave a scene empty, every clip must fit
its own line. Offline: every source, download and judge is mocked.
"""
import os
import tempfile
import unittest
from unittest import mock

from src import config, fanout, gapfill, ledger, media, pools, slop, timeline
from src.media import MediaAsset
from src.transcribe import Segment, Word


def yt(vid: str, start: float, path: str = "") -> MediaAsset:
    """One moment of YouTube video `vid` (11 characters), as the pools cut it."""
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                      local_path=path or f"/w/{vid}_{int(start)}.mp4", moment_key=f"yt:{vid}@{int(start // 8)}",
                      moment={"start": float(start)})


def scene(i: int, media_: dict, fps: int = 30, seconds: float = 3.0, **sem) -> dict:
    return {"id": f"s{i:04d}", "startFrame": int(i * seconds * fps), "durationInFrames": int(seconds * fps),
            "text": f"line {i}", "media": media_, "semanticMetadata": dict(sem)}


def clip(url: str) -> dict:
    return {"type": "video", "url": url, "source": "youtube", "clipSeconds": 6.0}


class CoverageOrder(unittest.TestCase):
    def test_the_hook_first_then_the_whole_video_spread(self):
        jobs = [{"index": i, "hook": i < 4} for i in range(40)]
        order = [j["index"] for j in gapfill.coverage_order(jobs)]
        self.assertEqual(order[:4], [0, 1, 2, 3])                     # the hook keeps its priority
        self.assertEqual(sorted(order), list(range(40)))              # every line once
        first_quarter = order[4:13]
        self.assertTrue(any(i >= 36 for i in first_quarter))          # the ending is reached early
        self.assertTrue(any(15 <= i <= 25 for i in first_quarter))    # and the middle

    def test_a_pass_cut_off_by_the_budget_leaves_scattered_gaps_not_the_ending(self):
        # Per-scene pass 1 on one worker; the "budget" runs out after 12 of 30 scenes.
        calls = []

        def fake(query, seconds, work_dir, *, nth=0, **kw):
            calls.append(query)
            if len(calls) > 12:
                return None                                           # past the deadline: nothing more found
            return MediaAsset(kind="image", source="wikimedia", url=f"https://x/{query}.jpg")

        jobs = [{"index": i, "query": f"line{i}", "seconds": 3.0, "hook": i < 2} for i in range(30)]
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 0), \
                mock.patch.object(config, "FRESH_MOMENTS", False):
            media.reset_cache()
            out = media.source_many(jobs, "/tmp", workers=1, refill=False)
        found = [i for i, a in enumerate(out) if a is not None]
        self.assertEqual(calls[:2], ["line0", "line1"])               # the hook first
        self.assertTrue(any(i >= 25 for i in found))                  # the ending is covered
        empty = [i for i, a in enumerate(out) if a is None]
        longest = max(len(r) for r in _runs(empty))
        self.assertLessEqual(longest, 3)                              # gaps are scattered, never the tail


def _runs(idx):
    runs, cur = [], []
    for i in idx:
        if cur and i != cur[-1] + 1:
            runs.append(cur)
            cur = []
        cur.append(i)
    return runs + ([cur] if cur else []) or [[]]


class RepeatFinder(unittest.TestCase):
    def test_the_repeat_finder_catches_a_file_used_twice(self):
        doc = {"fps": 30, "scenes": [
            scene(0, clip("/w/a.mp4")),
            scene(1, {"type": "image", "url": "/w/p.jpg", "source": "web_image"}),
            scene(2, clip("/w/b.mp4")),
            scene(3, clip("/w/a.mp4"))]}
        got = gapfill.find_repeats(doc)
        self.assertEqual([i for i, _ in got], [3])
        self.assertIn("same file", got[0][1])

    def test_the_same_moment_or_its_video_on_the_next_scene_is_a_repeat_a_far_moment_is_not(self):
        def at(i, vid, start):
            return scene(i, clip(f"/w/{vid}_{start}.mp4"), assetId=f"yt:{vid}@{int(start // 8)}",
                         sourceUrl=f"https://www.youtube.com/watch?v={vid}&t={start}", moment={"start": float(start)})
        doc = {"fps": 30, "scenes": [
            at(0, "AAAAAAAAAAA", 40),
            at(1, "BBBBBBBBBBB", 10),
            at(2, "AAAAAAAAAAA", 55),       # 15 s from scene 0's moment
            at(3, "AAAAAAAAAAA", 200),      # 160 s on, two scenes away: a different moment
            at(4, "AAAAAAAAAAA", 400),      # its video on the very next scene
            {**at(5, "CCCCCCCCCCC", 30)},
            {**at(6, "CCCCCCCCCCC", 36.8), "semanticMetadata": {"assetId": "yt:CCCCCCCCCCC@4",
                                                               "moment": {"start": 36.8, "chain": True}}}]}
        got = dict(gapfill.find_repeats(doc))
        self.assertEqual(sorted(got), [2, 4])
        self.assertIn("same moment", got[2])
        self.assertIn("next scene", got[4])                         # a planned chain (6) is not a repeat

    def test_the_check_before_publishing_replaces_a_repeat_through_the_ladder(self):
        work = tempfile.mkdtemp()
        lib = _FakeLibrary([{"id": "yt:LIBRARY0001@4", "url": "https://www.youtube.com/watch?v=LIBRARY0001&t=35",
                             "read_url": "https://r2/lib1.mp4", "subject_key": "lake powell"}], work)
        doc = {"fps": 30, "meta": {}, "overlays": [], "scenes": [
            scene(0, clip("/w/a.mp4"), subject="Lake Powell"),
            scene(1, clip("/w/b.mp4"), subject="Lake Powell"),
            scene(2, clip("/w/a.mp4"), subject="Lake Powell")]}       # scene 0's file again
        gapfill.reset()
        gapfill.remember([{"index": i, "subject": "Lake Powell", "seconds": 3.0} for i in range(3)], work,
                         library=lib)
        try:
            with _offline():
                got = gapfill.final_check(doc)
        finally:
            gapfill.reset()
        self.assertEqual((got["repeats"], got["replaced"]), (1, 1))
        self.assertEqual(doc["scenes"][2]["media"]["url"], os.path.join(work, "lib_0.mp4"))
        self.assertEqual(gapfill.find_repeats(doc), [])


class _FakeLibrary:
    """library.Library's find/fetch over a few entries (each fetch is a new local file)."""

    def __init__(self, entries, work):
        self.entries = [dict(e, kind="video", saved=True, relevance=0.9) for e in entries]
        self.used = set()
        self.work = work

    def find(self, subject, exclude=None, n=1, kind="video", **kw):
        key = " ".join(subject.lower().split())
        return [e for e in self.entries if e["subject_key"] == key and e["id"] not in (exclude or set())][:n]

    def fetch(self, entry, work, seconds, job):
        k = self.entries.index(entry)
        self.used.add(entry["id"])
        return MediaAsset(kind="video", source="youtube", url=entry["url"], local_path=os.path.join(work, f"lib_{k}.mp4"),
                          moment_key=entry["id"], relevance_score=0.9)


def _offline():
    """Every network step of the ladder mocked: picture search, download, gates, generation."""
    stack = mock.patch.multiple(media, _photo_seen_before=mock.DEFAULT, _asset_ok=mock.DEFAULT,
                                judge_clip=mock.DEFAULT, generate_image=mock.DEFAULT, _cached_search=mock.DEFAULT,
                                _download=mock.DEFAULT)

    class Ctx:
        def __enter__(self):
            self.m = stack.__enter__()
            self.m["_photo_seen_before"].return_value = False
            self.m["_asset_ok"].return_value = (True, "")
            self.m["judge_clip"].return_value = (True, None)
            self.m["generate_image"].side_effect = AssertionError("no AI image unless the job allows one")
            self.m["_cached_search"].return_value = []
            self.m["_download"].side_effect = lambda c, q, w: c
            self.others = [mock.patch.object(ledger, "photo_used", return_value=False),
                           mock.patch.object(slop, "enabled", return_value=False),
                           mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 0)]
            for p in self.others:
                p.start()
            return self.m

        def __exit__(self, *exc):
            for p in reversed(self.others):
                p.stop()
            return stack.__exit__(*exc)
    return Ctx()


class BudgetRunsOut(unittest.TestCase):
    """The sourcing budget is spent with the last six lines unsourced."""

    def tearDown(self):
        gapfill.reset()                 # the plan do_plan remembered must not reach another test

    def _plan(self):
        segs, shots, jobs = [], [], []
        for i in range(12):
            words = [Word(text=w, start=i * 3.0 + k * 0.4, end=i * 3.0 + k * 0.4 + 0.3)
                     for k, w in enumerate(f"Lake Powell line number {i}".split())]
            segs.append(Segment(text=f"Lake Powell line number {i}", start=i * 3.0, end=(i + 1) * 3.0, words=words))
            shots.append({"query": "lake powell", "visualType": "footage", "subject": "Lake Powell",
                          "subjectType": "place", "overlay": None})
            jobs.append({"index": i, "query": "lake powell", "seconds": 3.0, "start": i * 3.0,
                         "visual_type": "footage", "subject": "Lake Powell", "subject_type": "place",
                         "intent": "Lake Powell water level", "context": segs[-1].text, "hook": i < 2})
        return segs, shots, jobs

    def test_n_unsourced_scenes_end_with_zero_empty_scenes_and_zero_repeated_files(self):
        work = tempfile.mkdtemp()
        segs, shots, jobs = self._plan()
        vids = ["VIDEO000001", "VIDEO000002", "VIDEO000003", "VIDEO000004", "VIDEO000005", "VIDEO000006"]
        results = [yt(v, 10.0 + 10 * k) for k, v in enumerate(vids)] + [None] * 6
        lib = _FakeLibrary([
            # Scene 0's video, 2 s from the moment it shows: never taken.
            {"id": "yt:VIDEO000001@1", "url": "https://www.youtube.com/watch?v=VIDEO000001&t=12",
             "read_url": "https://r2/l0.mp4", "subject_key": "lake powell"},
            {"id": "yt:LIBRARY0001@4", "url": "https://www.youtube.com/watch?v=LIBRARY0001&t=35",
             "read_url": "https://r2/l1.mp4", "subject_key": "lake powell"}], work)
        spares = [("lake powell", {"id": "VIDEO000002", "title": "Lake Powell"}, {"start": 25.0, "score": 0.9}),
                  ("lake powell", {"id": "SPARE000001", "title": "Lake Powell"}, {"start": 60.0, "score": 0.9})]
        pics = [MediaAsset(kind="image", source="web_image", url=f"https://x/powell{k}.jpg",
                           local_path=os.path.join(work, f"p{k}.jpg")) for k in range(2)]

        def fetch(job, cand, m, work_, require_cc, subject, library=None):
            return yt(cand["id"], m["start"], path=os.path.join(work_, f"spare_{cand['id']}.mp4"))
        with pools._RESERVE_LOCK:
            pools._RESERVE[:] = spares
        try:
            with _offline() as m, mock.patch.object(pools, "_fetch", side_effect=fetch), \
                    mock.patch.object(config, "HOOK_SECONDS", 6.0), mock.patch.object(config, "FALLBACK_PARALLEL", 1):
                m["_cached_search"].return_value = pics
                got = gapfill.fill_empty(jobs, results, work, library=lib)
        finally:
            with pools._RESERVE_LOCK:
                pools._RESERVE.clear()
        self.assertEqual((got["library"], got["reserve"], got["still"]), (1, 1, 2))
        self.assertEqual(got["left"], 2)
        self.assertNotIn("VIDEO000001&t=12", " ".join(a.url for a in results if a))   # a near moment: never
        self.assertNotIn("VIDEO000002&t=25", " ".join(a.url for a in results if a))
        # The timeline, then the last resort for the two the ladder could not fill.
        with mock.patch.object(timeline, "_clip_seconds", return_value=6.0), \
                mock.patch.object(config, "HOOK_SECONDS", 6.0), mock.patch.object(config, "TREATMENTS", False), \
                mock.patch.object(config, "ANIMATION_FILL", False):
            doc = timeline.build(segs, shots, results, audio_url="file:///tmp/vo.mp3", audio_duration=36.0, inp={})
            last = gapfill.hold_or_animate(doc)
        self.assertEqual(last["held"], 2)
        self.assertEqual([s for s in doc["scenes"] if s["media"].get("type") == "color"], [])   # zero empty
        self.assertEqual(gapfill.find_repeats(doc), [])                                         # zero repeats
        urls = [s["media"]["url"] for s in doc["scenes"]]
        self.assertEqual(len(urls), len(set(urls)))
        timeline.validate(doc, require_media=True)
        self.assertIn("filled 6 scenes from library/spare moments/stills/hold", gapfill.summary(got, last))

    def test_do_plan_never_reuses_a_shot_and_hands_the_empties_to_the_ladder(self):
        import handler
        segs, shots, jobs = self._plan()
        sourced = [yt(f"VIDEO00000{k}", 10.0) for k in range(6)] + [None] * 6
        seen = {}

        def source_many(jobs_, work, **kw):
            return [sourced[j["index"]] for j in sorted(jobs_, key=lambda j: j["index"])]

        def ladder(jobs_, results, work, **kw):
            seen["empty"] = [i for i, a in enumerate(results) if a is None]
            for i in seen["empty"]:
                results[i] = yt(f"FALLBACK{i:03d}", 40.0)
            return {"asked": len(seen["empty"]), "library": 6, "reserve": 0, "still": 0, "generated": 0, "left": 0}

        def build(segments, shots_, assets, **kw):
            seen["assets"] = list(assets)
            raise _Built()
        with mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"), \
                mock.patch.object(handler.storage, "download", return_value="/w/vo.mp3"), \
                mock.patch.object(handler.renderer, "probe_duration", return_value=36.0), \
                mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]), \
                mock.patch.object(handler.transcribe, "segment_words", return_value=segs), \
                mock.patch.object(handler.director, "story_brief", return_value=dict(BRIEF)), \
                mock.patch.object(handler.director, "plan", return_value=(shots, "ai", [])), \
                mock.patch.object(handler.library.Library, "load", return_value=None), \
                mock.patch.object(handler.fanout, "enabled_for", return_value=False), \
                mock.patch.object(pools, "source_by_subject", return_value={}), \
                mock.patch.object(media, "source_many", side_effect=source_many), \
                mock.patch.object(media, "rescue_fill", return_value={}), \
                mock.patch.object(media, "fill_from_story", side_effect=AssertionError("a reused shot")), \
                mock.patch.object(handler.gapfill, "fill_empty", side_effect=ladder), \
                mock.patch.object(handler.timeline, "build", side_effect=build), \
                mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False), \
                mock.patch.object(config, "SUBJECT_POOLS", True):
            with self.assertRaises(_Built):
                handler.do_plan({"audio_url": "vo.mp3", "project_id": ""}, tempfile.mkdtemp(), handler.Reporter(""))
        handler.vision.set_story({})
        self.assertEqual(seen["empty"], [6, 7, 8, 9, 10, 11])
        self.assertTrue(all(a is not None for a in seen["assets"]))
        self.assertEqual(len({a.identity for a in seen["assets"]}), 12)
        self.assertTrue(gapfill.CONTEXT.get("jobs"))                    # the check before publishing has the plan


class _Built(Exception):
    pass


BRIEF = {"kind": "explainer", "summary": "", "event": "Lake Powell drops", "year": 2026, "recent": False,
         "places": ["Lake Powell"], "people": [], "hookBeats": [0], "cast": [], "sections": []}


class LastResort(unittest.TestCase):
    def test_an_empty_line_is_held_by_its_neighbours_never_given_a_copy(self):
        doc = {"fps": 30, "overlays": [], "scenes": [
            scene(0, clip("/w/a.mp4")), scene(1, {"type": "color", "url": "", "source": "none"}),
            scene(2, clip("/w/b.mp4"))]}
        doc["scenes"][1]["words"] = [{"text": "early", "start": 3.1, "end": 3.4},
                                     {"text": "late", "start": 5.5, "end": 5.9}]
        with mock.patch.object(config, "ANIMATION_FILL", False), mock.patch.object(config, "HOOK_SECONDS", 0.0):
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["held"], 1)
        a, b = doc["scenes"]
        self.assertEqual((a["durationInFrames"], b["startFrame"], b["durationInFrames"]), (135, 135, 135))
        self.assertEqual([w["text"] for w in a["words"]], ["early"])    # the words go with the frames
        self.assertEqual([w["text"] for w in b["words"]], ["late"])
        self.assertEqual([s["media"]["url"] for s in doc["scenes"]], ["/w/a.mp4", "/w/b.mp4"])

    def test_a_held_twin_is_never_restored_as_the_same_moment(self):
        jobs = [{"index": 0, "start": 0.0}, {"index": 1, "start": 300.0}]
        results = [yt("AAAAAAAAAAA", 10), yt("AAAAAAAAAAA", 12, path="/w/other.mp4")]
        held = media.hold_violations(jobs, results)
        self.assertEqual(sorted(held), [1])
        self.assertEqual(media.restore_held(jobs, results, held)["dropped"], 1)
        self.assertIsNone(results[1])


class Budget(unittest.TestCase):
    def test_the_cap_grows_with_the_scene_count(self):
        # The pod's settings (app video-v2): 20 s a scene, 2400 s cap.
        with mock.patch.object(config, "SOURCE_BUDGET_BASE_SECONDS", 180), \
                mock.patch.object(config, "SOURCE_BUDGET_PER_SCENE", 20), \
                mock.patch.object(config, "SOURCE_BUDGET_MAX_SECONDS", 2400), \
                mock.patch.object(config, "SOURCE_BUDGET_MAX_PER_SCENE", 18), \
                mock.patch.object(config, "SOURCE_BUDGET_CEILING_SECONDS", 5400):
            self.assertEqual(fanout.source_budget(60), 1380)        # under the cap: unchanged
            self.assertEqual(fanout.source_budget(100), 2180)
            self.assertEqual(fanout.source_budget(159), 2862)       # Lake Powell: was 2400
            self.assertEqual(fanout.source_budget(400), 5400)       # never past the ceiling


if __name__ == "__main__":
    unittest.main()
