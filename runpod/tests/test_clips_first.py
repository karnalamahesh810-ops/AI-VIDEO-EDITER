"""
Clips first (config.CLIPS_FIRST; the owner, 2026-10-06: "video clips are the main part of what we make ...
the amount of video right now is super low").

Measured on his six latest videos (clips 43% -> 11-15% of scenes): a footage line took a web picture as soon
as its FIRST wording's YouTube search found nothing, because the provider registry walks the picture
sources right after the clip sources for each wording; the broader wordings were only ever asked for
pictures. Now a clip-first line asks YouTube on its own wordings and wider rungs, then the other clip
sources, and only then pictures; the first HOOK_NO_STILL_SECONDS take no picture at all; candidates under
720 lines never take a scout or a download; the opening prefers footage that moves.

Offline: every search, download and judgement is a stub.
"""
import os
import tempfile
import unittest
from unittest import mock

from src import config, media, providers, storage, vision, ytdlp
from src.media import MediaAsset
from src.providers import SourceContext


def clip(vid="AAAAAAAAAAA", **kw):
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t=10", **kw)


def picture(url="https://img.example/a.jpg"):
    return MediaAsset(kind="image", source="web_image", url=url)


ON = dict(CLIPS_FIRST=True, CLIPS_FIRST_STILLS=True, CLIP_WORDINGS=3, CLIP_RUNGS=3, CLIP_OTHER_WORDINGS=2,
          PREFER_GENERATED_IMAGES=False, HOOK_NO_STILL_SECONDS=10.0)


class WhichLines(unittest.TestCase):
    def test_footage_lines_and_place_stills_go_clip_first_documents_portraits_and_maps_keep_pictures(self):
        with mock.patch.multiple(config, **ON):
            self.assertTrue(media.clips_first_for("footage", "event"))
            self.assertTrue(media.clips_first_for("image", "place"))
            self.assertTrue(media.clips_first_for("image", "object"))
            self.assertFalse(media.clips_first_for("image", "document"))
            self.assertFalse(media.clips_first_for("image", "person"))
            self.assertFalse(media.clips_first_for("image", "place", {"desired_shots": ["map of the basin"]}))
            self.assertFalse(media.clips_first_for("animation", "event"))
        with mock.patch.multiple(config, **dict(ON, PREFER_GENERATED_IMAGES=True)):
            self.assertFalse(media.clips_first_for("image", "place"))      # an illustrated style
            self.assertTrue(media.clips_first_for("footage", "place"))
        with mock.patch.multiple(config, **dict(ON, CLIPS_FIRST_STILLS=False)):
            self.assertFalse(media.clips_first_for("image", "place"))
        with mock.patch.multiple(config, **dict(ON, CLIPS_FIRST=False)):
            self.assertFalse(media.clips_first_for("footage", "event"))
        with mock.patch.multiple(config, **ON), mock.patch.object(media, "youtube_only", return_value=True):
            self.assertFalse(media.clips_first_for("footage", "event"))   # YouTube-only keeps its own order


class TheOrder(unittest.TestCase):
    def _run(self, found=None, subject_type="person", **kw):
        calls = []

        def one(query, seconds, work_dir, stage=None, **k):
            calls.append((stage, query, media._RUNG.get()))
            return found(stage, query) if found else None
        with mock.patch.multiple(config, **ON), mock.patch.object(media, "_source_one", side_effect=one), \
                mock.patch.object(media, "_count_photo"):
            got = media.source_for_segment(
                "Barack Obama Michelle Robinson wedding 1992 groom footage", 4.0, "/w", visual_type="footage",
                fallbacks=["Barack Obama wedding", "Trinity United Church Chicago"],
                subject="Barack Obama", subject_type=subject_type,
                scene_intent={"entities": ["Barack Obama", "Michelle Robinson"], "locations": ["Chicago"],
                              "event_type": "wedding", "specificity": "event"}, **kw)
        return got, calls

    def test_youtube_on_every_own_wording_and_the_wider_rungs_before_any_picture(self):
        _got, calls = self._run(subject_type="event")
        stages = [s for s, _q, _r in calls]
        self.assertEqual(stages[:3], ["youtube"] * 3)
        rungs = [(q, r["label"]) for s, q, r in calls if r]
        self.assertTrue(rungs and all(s == "youtube" for s, _q, r in calls if r))
        self.assertIn(("Chicago wedding footage", "Chicago wedding"), rungs)       # the event where it happened
        self.assertIn(("Barack Obama footage", "Barack Obama"), rungs)              # then the subject
        # A line about a named person: the person's own rung only (a place or event rung shows other people,
        # and on that line any face reads as the person's).
        _got, calls = self._run()
        self.assertEqual([(q, r["label"]) for s, q, r in calls if r], [("Barack Obama footage", "Barack Obama")])
        first_picture = stages.index("pictures")
        self.assertTrue(all(s in ("youtube", "other_footage") for s in stages[:first_picture]))
        self.assertIn("other_footage", stages[:first_picture])
        self.assertEqual(stages[-1], "generated")
        self.assertFalse(media._RUNG.get())                                          # reset after the line

    def test_a_clip_on_a_wider_rung_ends_the_search_and_says_so(self):
        got, calls = self._run(found=lambda stage, q: clip() if q == "Barack Obama footage" else None)
        self.assertEqual(got.kind, "video")
        self.assertEqual(got.score_parts.get("rung"), "Barack Obama")
        self.assertNotIn("pictures", [s for s, _q, _r in calls])

    def test_a_near_miss_waits_for_the_rungs_and_still_comes_before_any_picture(self):
        near = clip("NEARMISS000", relevance_score=0.6, review_required=True,
                    review_reason="Best available: the vision check scored it 0.60, under the 0.70 floor")
        good = clip("PASSINGCLIP", relevance_score=0.8)

        def found(stage, q):
            if stage == "youtube" and q.startswith("Barack Obama Michelle"):
                return near
            if q == "Barack Obama footage":
                return good
            return picture() if stage == "pictures" else None
        got, calls = self._run(found=found)
        self.assertIs(got, good)                                   # the rung's passing clip wins
        got, calls = self._run(found=lambda stage, q: near if q.startswith("Barack Obama Michelle")
                               else (picture() if stage == "pictures" else None))
        self.assertIs(got, near)                                   # no passing clip: the near-miss, no picture
        self.assertNotIn("pictures", [s for s, _q, _r in calls])

    def test_the_first_seconds_of_the_opening_take_no_picture_later_hook_lines_may(self):
        _got, calls = self._run(hook=True, start=3.0)
        self.assertNotIn("pictures", [s for s, _q, _r in calls])
        self.assertNotIn("generated", [s for s, _q, _r in calls])
        _got, calls = self._run(hook=True, start=30.0)
        self.assertIn("pictures", [s for s, _q, _r in calls])

    def test_clips_only_never_asks_for_a_picture(self):
        _got, calls = self._run(clips_only=True)
        self.assertEqual({s for s, _q, _r in calls} - {"youtube", "other_footage"}, set())

    def test_a_clip_stage_never_hands_back_a_picture(self):
        got, _calls = self._run(found=lambda stage, q: picture() if stage == "other_footage" else None)
        self.assertIsNone(got)                                    # the pictures stage found nothing either

    def test_off_the_old_walk_is_back(self):
        calls = []

        def one(query, seconds, work_dir, stage=None, **k):
            calls.append(stage)
            return None
        with mock.patch.multiple(config, **dict(ON, CLIPS_FIRST=False)), \
                mock.patch.object(media, "_source_one", side_effect=one):
            media.source_for_segment("q", 4.0, "/w", visual_type="footage", fallbacks=["r"])
        self.assertEqual(set(calls), {None})


class Rungs(unittest.TestCase):
    def test_rungs_name_the_event_place_the_subject_the_entities_and_the_places(self):
        si = {"entities": ["Portland Harbor", "NOAA tide gauge"], "locations": ["Portland", "Harbour", "Maine"],
              "event_type": "2026 Nor'easter coastal flooding / storm surge", "specificity": "event"}
        got = media.clip_rungs("NOAA tide gauge Portland Harbor Maine Oct 2026 flooding close up footage",
                               subject="Portland Harbor", scene_intent=si, limit=5)
        labels = [r["label"] for r in got]
        self.assertEqual(labels[0], "Portland Harbour Maine Nor'easter coastal flooding")
        self.assertIn("Portland Harbor", labels)
        self.assertIn("NOAA tide gauge", labels)
        self.assertTrue(all(r["query"] == f"{r['label']} footage" for r in got))
        self.assertTrue(all("2026" not in r["query"] for r in got))                 # never a year in a rung

    def test_a_rung_the_line_already_asked_is_not_asked_again_and_the_limit_holds(self):
        got = media.clip_rungs("q", subject="Lake Mead", scene_intent={"entities": ["Hoover Dam"]},
                               taken=["Lake Mead footage"], limit=1)
        self.assertEqual(got, [{"query": "Hoover Dam footage", "label": "Hoover Dam"}])
        self.assertEqual(media.clip_rungs("q", subject="Lake Mead", limit=0), [])

    def test_a_rung_is_judged_as_shows_its_subject_not_the_exact_moment(self):
        si = {"entities": ["Barack Obama"], "specificity": "event", "generic_ok": False, "time_context": "1992"}
        intent, scene, event = media.rung_judging("the groom at his 1992 wedding", si, {"label": "Barack Obama"})
        self.assertIn("Clear real footage of Barack Obama", intent)
        self.assertIn("the groom at his 1992 wedding", intent)
        # A line of a past era keeps its era (never today's footage for 1992); a present one lets it go.
        self.assertEqual((scene["specificity"], scene["generic_ok"], scene["time_context"]),
                         ("generic", True, "1992"))
        self.assertFalse(event)
        self.assertEqual(si["specificity"], "event")                                 # the line's own is untouched
        _i, scene, _e = media.rung_judging("the lake today", dict(si, time_context="current"), {"label": "Lake Mead"})
        self.assertEqual(scene["time_context"], "unknown")

    def test_the_gate_judges_a_rung_clip_with_the_relaxed_intent(self):
        seen = {}

        def judge(path, intent, context, event=False, scene=None, wants="", span=None):
            seen.update(intent=intent, event=event, scene=scene)
            return {"score": 0.8, "has_text_or_watermark": False, "is_talking_head": False, "description": "x",
                    "quality": 0.7}
        d = tempfile.mkdtemp()
        path = os.path.join(d, "c.mp4")
        open(path, "wb").write(b"x")
        toks = [(media._EVENT_WINDOW, media._EVENT_WINDOW.set("year")),
                (media._SCENE_INTENT, media._SCENE_INTENT.set({"specificity": "event", "entities": ["Kerrville"]})),
                (media._RUNG, media._RUNG.set({"label": "Kerrville"}))]
        try:
            with mock.patch.object(media, "slop_reason", return_value=""), \
                    mock.patch.object(media, "_local_check", return_value=None), \
                    mock.patch.object(media.vision, "enabled", return_value=True), \
                    mock.patch.object(media.vision, "judge", side_effect=judge):
                keep, _v = media._judge_gate(path, "the flood at Kerrville on the 4th", "ctx", "label")
        finally:
            for var, tok in reversed(toks):
                var.reset(tok)
        self.assertTrue(keep)
        self.assertFalse(seen["event"])
        self.assertIn("Clear real footage of Kerrville", seen["intent"])
        self.assertEqual(seen["scene"]["specificity"], "generic")

    def test_a_rungs_storyboard_moment_is_picked_for_what_the_rung_names(self):
        rows = [{"id": "AAAAAAAAAAA", "duration": 300.0, "aspect": 1.78, "title": "Barack Obama speech 4k",
                 "channel": "news"}]
        seen = []

        def plan(eligible, grab, start_at, intent, context):
            seen.append(intent)
            return []
        toks = [(media._SCENE_TRIED, media._SCENE_TRIED.set(set())), (media._SCENE_JUDGED, media._SCENE_JUDGED.set([0])),
                (media._SCENE_INTENT, media._SCENE_INTENT.set({"entities": ["Barack Obama"], "specificity": "event"}))]
        try:
            with mock.patch.object(media, "_yt_candidates_cached", return_value=rows), \
                    mock.patch.object(media, "_plan_grabs", side_effect=plan), \
                    mock.patch.object(media.vision, "enabled", return_value=True), \
                    mock.patch.multiple(config, MOMENT_SELECTION=True, CLIP_PREQUALIFY=0):
                media.reset_cache()
                media._youtube_pool("q", "/tmp/x", 4.0, 30.0, False, 0, set(), "the groom at his 1992 wedding", "",
                                    "Barack Obama", [("q", "plain", False)], expand=False)
                media._SCENE_TRIED.set(set())
                tok = media._RUNG.set({"label": "Barack Obama"})
                try:
                    media._youtube_pool("q", "/tmp/x", 4.0, 30.0, False, 0, set(), "the groom at his 1992 wedding",
                                        "", "Barack Obama", [("q", "plain", False)], expand=False)
                finally:
                    media._RUNG.reset(tok)
        finally:
            for var, tok in reversed(toks):
                var.reset(tok)
        self.assertEqual(seen[0], "the groom at his 1992 wedding")
        self.assertIn("Clear real footage of Barack Obama", seen[1])

    def test_a_rung_search_is_its_own_not_the_subjects_cached_list(self):
        asked = []

        def flat(target, cc, limit=20, timeout=90):
            asked.append(target)
            return [{"id": f"V{len(asked):010d}", "duration": 300.0, "aspect": 1.78, "title": "t", "channel": ""}]
        with mock.patch.object(media, "_yt_candidates", side_effect=flat), \
                mock.patch.object(media, "_google_youtube_candidates", return_value=[]):
            media.reset_cache()
            media._yt_candidates_cached("ytsearch20:Lake Mead boats", False, "Lake Mead", "plain")
            media._yt_candidates_cached("ytsearch20:Lake Mead aerial", False, "Lake Mead", "plain")   # cached
            tok = media._RUNG.set({"label": "Hoover Dam"})
            try:
                media._yt_candidates_cached("ytsearch20:Hoover Dam footage", False, "Lake Mead", "plain")
                media._yt_candidates_cached("ytsearch20:Hoover Dam footage", False, "Lake Mead", "plain")  # cached
                media._yt_candidates_cached("ytsearch20:Lake Mead footage", False, "Lake Mead", "plain")
            finally:
                media._RUNG.reset(tok)
        self.assertEqual(asked, ["ytsearch20:Lake Mead boats", "ytsearch20:Hoover Dam footage",
                                 "ytsearch20:Lake Mead footage"])


class Budgets(unittest.TestCase):
    def test_a_clip_first_line_scouts_more_and_may_spend_more_the_hook_most(self):
        with mock.patch.multiple(config, JUDGE_MAX_PER_SCENE=12, CLIPS_FIRST_JUDGE_MAX_PER_SCENE=20, POOL_SCOUT=2,
                                 CLIPS_FIRST_POOL_SCOUT=3, HOOK_JUDGE_MAX_PER_SCENE=16, HOOK_POOL_SCOUT=4):
            self.assertEqual((media._judge_limits()["per_scene"], media._judge_limits()["scouts"]), (12, 2))
            tok = media._CLIP_FIRST.set(True)
            try:
                self.assertEqual((media._judge_limits()["per_scene"], media._judge_limits()["scouts"]), (20, 3))
                hook = media._IN_HOOK.set(True)
                try:
                    self.assertEqual((media._judge_limits()["per_scene"], media._judge_limits()["scouts"]), (24, 4))
                finally:
                    media._IN_HOOK.reset(hook)
            finally:
                media._CLIP_FIRST.reset(tok)

    def test_the_opening_prefers_footage_that_moves_even_with_no_motion_preference(self):
        with mock.patch.multiple(config, MOTION_PREFERENCE=0.0, HOOK_MOTION_WEIGHT=0.04, HOOK_BOOST=False):
            self.assertEqual(media._motion_weight(hook=False), 0.0)
            self.assertAlmostEqual(media._motion_weight(hook=True), 0.08)


class Prequalify(unittest.TestCase):
    def test_metadata_turns_down_what_could_never_be_the_clip(self):
        with mock.patch.multiple(config, MIN_CLIP_HEIGHT=720, ALLOW_VERTICAL=False):
            self.assertTrue(media.meta_reject({"width": 854, "height": 480}, "Lake Mead tour").startswith("low detail"))
            self.assertEqual(media.meta_reject({"width": 640, "height": 480}, "1962 newsreel Hoover Dam"), "")
            self.assertEqual(media.meta_reject({"width": 1080, "height": 1920}), "vertical video")
            self.assertEqual(media.meta_reject({"width": 1920, "height": 1080, "duration": 4.0}, need=6.5),
                             "shorter than the shot")
            self.assertEqual(media.meta_reject({"width": 1920, "height": 1080, "duration": 600}), "")
            self.assertEqual(media.meta_reject({}), "")                             # unknown never rejects
        with mock.patch.multiple(config, MIN_CLIP_HEIGHT=720, ALLOW_VERTICAL=True):
            self.assertEqual(media.meta_reject({"width": 1080, "height": 1920, "duration": 60}), "")

    def test_only_qualified_candidates_reach_the_scouts_in_rank_order(self):
        class C:
            def __init__(self, vid):
                self.id, self.title = vid, f"title {vid}"
        ranked = [C(f"V{n:010d}") for n in range(6)]
        heights = {"V0000000000": 360, "V0000000001": 1080, "V0000000002": 480, "V0000000003": 720,
                   "V0000000004": 1080, "V0000000005": 1080}
        read = []

        def info(vid):
            read.append(vid)
            return {"width": 1920, "height": heights[vid], "duration": 300}, ""
        with mock.patch.multiple(config, CLIP_PREQUALIFY=8, MIN_CLIP_HEIGHT=720, ALLOW_VERTICAL=False), \
                mock.patch.object(media, "_yt_info", side_effect=info):
            media.reset_cache()
            got = media._prequalified(ranked, 2, "", 5.0)          # not a clip-first line: as it was
            self.assertEqual([c.id for c in got], [c.id for c in ranked])
            self.assertEqual(read, [])
            tok = media._CLIP_FIRST.set(True)
            try:
                got = media._prequalified(ranked, 2, "", 5.0)
            finally:
                media._CLIP_FIRST.reset(tok)
        ids = [c.id for c in got]
        self.assertEqual(ids[:2], ["V0000000001", "V0000000003"])             # the first two that qualify
        self.assertNotIn("V0000000000", ids)
        self.assertNotIn("V0000000002", ids)
        self.assertEqual(ids[2:], ["V0000000004", "V0000000005"])            # the rest unread, in their place
        self.assertEqual(sorted(read), sorted(["V0000000000", "V0000000001", "V0000000002", "V0000000003"]))
        # Not remembered for the job: a line of an old era may take a small upload (its metadata is cached).
        self.assertFalse(media._is_bad("yt:V0000000000"))
        with mock.patch.multiple(config, CLIP_PREQUALIFY=8, MIN_CLIP_HEIGHT=720, ALLOW_VERTICAL=False), \
                mock.patch.object(media, "_yt_info", side_effect=info):
            tok = media._CLIP_FIRST.set(True)
            try:
                got = media._prequalified(ranked, 2, "", 5.0, query="Kenya 1962 newsreel")
            finally:
                media._CLIP_FIRST.reset(tok)
        self.assertEqual([c.id for c in got][:2], ["V0000000000", "V0000000001"])   # archive film may be small


class Sources(unittest.TestCase):
    def test_archive_org_is_not_asked_for_a_line_about_now(self):
        with mock.patch.multiple(config, ALLOW_ARCHIVE_ORG=True, CLIPS_FIRST=True):
            names = lambda ctx: [p.name for p in providers.ordered(ctx)]
            self.assertIn("archive_org_video", names(SourceContext("q", 6.0, "/w", stage="other_footage")))
            self.assertNotIn("archive_org_video",
                             names(SourceContext("q", 6.0, "/w", stage="other_footage", current=True)))
            self.assertEqual(names(SourceContext("q", 6.0, "/w", stage="youtube", allow_youtube=True)), ["youtube"])
        with mock.patch.multiple(config, ALLOW_ARCHIVE_ORG=True, CLIPS_FIRST=False):
            self.assertIn("archive_org_video",
                          [p.name for p in providers.ordered(SourceContext("q", 6.0, "/w", current=True))])

    def test_the_two_halves_of_the_clip_sources(self):
        by = {p.name: providers.clip_stage(p) for p in providers.REGISTRY}
        self.assertEqual(by["youtube"], "youtube")
        self.assertEqual(by["youtube_for_stills"], "youtube")
        self.assertEqual(by["dailymotion"], "other_footage")
        self.assertEqual(by["wikimedia_video"], "other_footage")
        self.assertEqual(by["web_images"], "pictures")
        self.assertEqual(by["generated_last"], "generated")
        p = next(p for p in providers.REGISTRY if p.name == "dailymotion")
        self.assertTrue(providers.in_stage(p, "footage"))
        self.assertTrue(providers.in_stage(p, None))
        self.assertFalse(providers.in_stage(p, "youtube"))


class WholeFiles(unittest.TestCase):
    """An archive's whole film is bounded (WHOLE_FILE_MAX_MB): it used to download hundreds of MB a try."""

    class _Resp:
        def __init__(self, length, chunks):
            self.headers = {"Content-Length": str(length), "Content-Type": "video/mp4"}
            self.status_code = 200
            self._chunks = chunks

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=1):
            yield from self._chunks

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_a_file_bigger_than_the_cap_is_not_fetched(self):
        dest = os.path.join(tempfile.mkdtemp(), "f.mp4")
        with mock.patch.object(storage.requests, "get", return_value=self._Resp(500 << 20, [b"x" * 10])):
            with self.assertRaises(storage.StorageError) as e:
                storage.download("https://archive.example/f.mp4", dest, max_bytes=250 << 20)
        self.assertIn("too big", str(e.exception))
        self.assertFalse(os.path.exists(dest))

    def test_a_stream_that_runs_past_the_cap_is_cut(self):
        dest = os.path.join(tempfile.mkdtemp(), "f.mp4")
        with mock.patch.object(storage.requests, "get", return_value=self._Resp(0, [b"x" * 1024] * 5)):
            with self.assertRaises(storage.StorageError):
                storage.download("https://archive.example/f.mp4", dest, max_bytes=2048)
        with mock.patch.object(storage.requests, "get", return_value=self._Resp(0, [b"x" * 1024] * 2)):
            self.assertEqual(storage.download("https://archive.example/f.mp4", dest, max_bytes=4096), dest)

    def test_an_archive_clip_download_carries_the_bounds(self):
        seen = {}

        def dl(url, dest, **kw):
            seen.update(kw)
            open(dest, "wb").write(b"x")
            return dest
        cand = MediaAsset(kind="video", source="archive_org", url="https://archive.org/download/x/x.mp4")
        with mock.patch.multiple(config, WHOLE_FILE_MAX_MB=250, WHOLE_FILE_SECONDS=75), \
                mock.patch.object(media, "download", side_effect=dl):
            got = media._download(cand, "q", tempfile.mkdtemp())
        self.assertIsNotNone(got)
        self.assertEqual((seen["max_bytes"], seen["max_seconds"]), (250 << 20, 75))
        self.assertIs(seen["stop"], ytdlp.stopped)


class Rescue(unittest.TestCase):
    """The rescue pass asks the judged clip-first search first - for a line about a person too."""

    def _job(self, i, **kw):
        j = {"index": i, "query": "Malik Obama interview", "seconds": 4.0, "start": 120.0 + i, "hook": False,
             "visual_type": "footage", "subject": "Malik Obama", "subject_type": "person", "intent": "Malik speaking",
             "context": "his brother Malik", "fallbacks": []}
        j.update(kw)
        return j

    def test_a_person_line_gets_a_judged_clip_and_never_an_unjudged_search(self):
        asked = []

        def find(query, seconds, work, **kw):
            asked.append(kw.get("clips_only"))
            return clip("MALIKOBAMA1", local_path="")
        results = [None]
        with mock.patch.multiple(config, CLIPS_FIRST=True, FRESH_MOMENTS=False, RESCUE_SECONDS=60,
                                 RESCUE_SCENE_SECONDS=30), \
                mock.patch.object(media, "source_for_segment", side_effect=find), \
                mock.patch.object(media, "_yt_candidates", side_effect=AssertionError("no unjudged search")):
            out = media.rescue_fill([self._job(0)], results, tempfile.mkdtemp())
        self.assertEqual(asked, [True])
        self.assertEqual(results[0].kind, "video")
        self.assertIn("judged", results[0].review_reason)
        self.assertEqual(out["search"], 1)

    def test_a_line_whose_whole_clip_search_already_ran_is_not_searched_again(self):
        asked = []
        with mock.patch.multiple(config, CLIPS_FIRST=True, FRESH_MOMENTS=False, RESCUE_SECONDS=60,
                                 ALLOW_WEB_IMAGES=False), \
                mock.patch.object(media, "_yt_candidates", return_value=[]), \
                mock.patch.object(media, "_source_one", side_effect=lambda *a, **k: asked.append(k.get("stage"))):
            media.reset_cache()
            media.source_for_segment("Malik Obama interview", 4.0, "/w", visual_type="footage", subject="Malik Obama",
                                     clips_only=True)                                  # pass 1: ran to its end
            n = len(asked)
            with mock.patch.object(media, "source_for_segment", wraps=media.source_for_segment) as again:
                media.rescue_fill([self._job(0, subject_type="place")], [None], tempfile.mkdtemp())
        self.assertGreater(n, 0)
        again.assert_not_called()
        media.reset_cache()
        self.assertEqual(media._CLIP_SEARCHED, set())

    def test_a_person_line_the_judged_search_misses_stays_for_the_ladder(self):
        results = [None]
        with mock.patch.multiple(config, CLIPS_FIRST=True, FRESH_MOMENTS=False, RESCUE_SECONDS=60,
                                 ALLOW_WEB_IMAGES=True), \
                mock.patch.object(media, "source_for_segment", return_value=None), \
                mock.patch.object(media, "_yt_candidates", side_effect=AssertionError("no unjudged search")), \
                mock.patch.object(media, "_cached_search", side_effect=AssertionError("no unjudged picture")):
            media.rescue_fill([self._job(0)], results, tempfile.mkdtemp())
        self.assertIsNone(results[0])



class FreshSearches(unittest.TestCase):
    """A later wording and a wider rung are new searches - also on the pool's own threads (the review of
    2026-10-06: a pool thread starts with no context, so they read as the line's first search)."""

    def test_a_later_wording_and_a_rung_search_anew_on_the_pool_threads(self):
        searched = []

        def yc(target, require_cc, limit=20, timeout=90):
            searched.append(target)
            return []
        with mock.patch.object(media, "_yt_candidates", side_effect=yc), \
                mock.patch.object(media, "_google_youtube_candidates", return_value=[]), \
                mock.patch.multiple(config, **dict(ON, POOL_EXTRA_QUERIES=0)):
            media.reset_cache()
            tok = media._CLIP_FIRST.set(True)
            try:
                def pool(q, ctx=()):
                    toks = [(var, var.set(val)) for var, val in ctx]
                    try:
                        media._youtube_pool(q, "/w", 4.0, 30.0, False, 0, set(), "the dam", "", "Lake Mead",
                                            [(q, "plain", False)])
                    finally:
                        for var, t in reversed(toks):
                            var.reset(t)
                pool("Lake Mead drought")
                pool("Lake Mead water level", [(media._WORDING, 1)])
                pool("Hoover Dam footage", [(media._RUNG, {"label": "Hoover Dam"})])
                pool("Lake Mead bathtub ring")                       # the first wording of another line: shared
            finally:
                media._CLIP_FIRST.reset(tok)
        self.assertEqual(searched, ["ytsearch20:Lake Mead drought", "ytsearch20:Lake Mead water level",
                                    "ytsearch20:Hoover Dam footage"])


class PicturesKeepTheirTime(unittest.TestCase):
    def test_the_clip_stages_stop_at_their_share_and_the_pictures_get_the_rest(self):
        import time
        calls = []

        def one(query, seconds, work_dir, stage=None, **k):
            calls.append((stage, round(time.time(), 2)))
            if stage in ("youtube", "other_footage"):
                while not ytdlp.stopped():
                    time.sleep(0.01)
                return None
            return picture()
        own = time.time() + 1.0
        tok = ytdlp.STOP.set((None, own))
        try:
            with mock.patch.multiple(config, **dict(ON, CLIPS_FIRST_CLIP_SHARE=0.6)), \
                    mock.patch.object(media, "_source_one", side_effect=one), \
                    mock.patch.object(media, "_count_photo"), \
                    mock.patch("src.director.relaxed_queries", return_value=[]):
                got = media.source_for_segment("Lake Mead drought", 4.0, "/w", visual_type="footage",
                                               subject="Lake Mead", subject_type="place")
        finally:
            ytdlp.STOP.reset(tok)
        self.assertEqual(got.kind, "image")                       # the line got its picture, not an empty scene
        stages = [s for s, _t in calls]
        self.assertEqual(stages[-1], "pictures")
        self.assertEqual(stages.count("youtube"), 1)              # the rest of the clip stages were let go
        self.assertLess(calls[-1][1], own)                        # inside the line's own time
        with media._CACHE_LOCK:
            self.assertNotIn(media._searched_key("Lake Mead drought", "Lake Mead"), media._CLIP_SEARCHED)

    def test_no_reserve_without_a_picture_stage(self):
        with mock.patch.multiple(config, **dict(ON, CLIPS_FIRST_CLIP_SHARE=0.6)):
            tok = ytdlp.STOP.set((None, 10 ** 12))
            try:
                self.assertIsNone(media._clip_stage_stop([("youtube", "q", None), ("other_footage", "q", None)]))
                got = media._clip_stage_stop([("youtube", "q", None), ("pictures", "q", None)])
                self.assertIsNotNone(got)
                ytdlp.STOP.reset(got)
            finally:
                ytdlp.STOP.reset(tok)


class Places(unittest.TestCase):
    def test_two_places_are_never_joined_into_one(self):
        got = media.clip_rungs("Obama Sr. Kenya Hawaii 1960s", subject="Barack Obama Sr.",
                               scene_intent={"locations": ["Kenya", "Hawaii"]}, limit=5)
        self.assertIn("Kenya", [r["label"] for r in got])
        self.assertNotIn("Kenya Hawaii", [r["label"] for r in got])
        got = media.clip_rungs("q", subject="x", scene_intent={"locations": ["Lake", "Mead"]}, limit=5)
        self.assertIn("Lake Mead", [r["label"] for r in got])



class PeriodFootage(unittest.TestCase):
    """PERIOD_FOOTAGE_YEARS (off by default): a line about a year long past may take the era's broadcast video."""

    def _scene(self, year):
        return media._SCENE_INTENT.set({"time_context": year, "specificity": "event"})

    def test_off_by_default_and_only_for_a_past_year(self):
        tok = self._scene("2008")
        try:
            self.assertFalse(media._period_line())
            with mock.patch.multiple(config, PERIOD_FOOTAGE_YEARS=8):
                self.assertTrue(media._period_line())
                self.assertEqual(media._period_lines(), float(config.PERIOD_REAL_LINES))
        finally:
            media._SCENE_INTENT.reset(tok)
        tok = self._scene("2025")
        try:
            with mock.patch.multiple(config, PERIOD_FOOTAGE_YEARS=8):
                self.assertFalse(media._period_line())                    # a recent line keeps the modern floor
        finally:
            media._SCENE_INTENT.reset(tok)

    def test_a_480p_upload_of_a_2008_report_is_read_on(self):
        info = {"width": 854, "height": 480, "duration": 300, "title": "Obama's brother in Huruma"}
        tok = self._scene("2008")
        try:
            with mock.patch.multiple(config, MIN_CLIP_HEIGHT=720, ALLOW_VERTICAL=False):
                self.assertIn("low detail", media.meta_reject(info))
                with mock.patch.multiple(config, PERIOD_FOOTAGE_YEARS=8, PERIOD_MIN_HEIGHT=480):
                    self.assertEqual(media.meta_reject(info), "")
                    self.assertIn("low detail", media.meta_reject(dict(info, width=576, height=324)))
        finally:
            media._SCENE_INTENT.reset(tok)

    def test_a_past_events_rung_asks_for_its_year(self):
        si = {"locations": ["Las Vegas, Nevada"], "event_type": "presidential debate", "specificity": "event",
              "time_context": "2016"}
        got = media.clip_rungs("q", subject="Las Vegas debate hall", scene_intent=si, limit=3)
        self.assertEqual(got[0]["query"], "Las Vegas Nevada presidential debate 2016 footage")
        self.assertEqual(got[0]["label"], "Las Vegas Nevada presidential debate")     # judged without it
        si["time_context"] = str(__import__("datetime").date.today().year)
        self.assertEqual(media.clip_rungs("q", subject="x", scene_intent=si, limit=1)[0]["query"],
                         "Las Vegas Nevada presidential debate footage")


class PeriodQuality(unittest.TestCase):
    """The Obama apply (2026-10-07): the debate's own broadcast clips scored 0.8 and were still turned down,
    with no reason in the trace - the judge's quality floor. A period line has its own, softer floor, and the
    trace says when the floor turned a clip down."""

    def test_a_period_line_has_its_own_quality_floor(self):
        v = {"score": 0.8, "quality": 0.2, "has_text_or_watermark": False, "is_talking_head": False}
        self.assertFalse(vision.acceptable(v))
        self.assertTrue(vision.acceptable(v, min_quality=0.15))
        tok = media._SCENE_INTENT.set({"time_context": "2016"})
        try:
            self.assertEqual(media._quality_floor(), config.VISION_MIN_QUALITY)          # off by default
            with mock.patch.multiple(config, PERIOD_FOOTAGE_YEARS=8, PERIOD_MIN_QUALITY=0.15):
                self.assertEqual(media._quality_floor(), 0.15)
                self.assertEqual(media._flags_of(dict(v, quality=0.1)), "quality 0.10")
                self.assertEqual(media._flags_of(v), "")
        finally:
            media._SCENE_INTENT.reset(tok)
        self.assertEqual(media._flags_of(v), "quality 0.20")


class PeriodClipsBeforeTheRender(unittest.TestCase):
    """The check before the render holds a clip taken as its era's own video to that era's floor (the Obama
    render of 2026-10-07 swapped two of them for pictures as "low detail")."""

    def test_the_floor_follows_the_scene(self):
        self.assertEqual(media.period_need({"scoreParts": {"period": True}}), float(config.PERIOD_REAL_LINES))
        sem = {"sceneIntent": {"time_context": "2016"}}
        self.assertIsNone(media.period_need(sem))                                  # off by default
        with mock.patch.multiple(config, PERIOD_FOOTAGE_YEARS=8):
            self.assertEqual(media.period_need(sem), float(config.PERIOD_REAL_LINES))
            self.assertIsNone(media.period_need({"sceneIntent": {"time_context": "unknown"}}))
        self.assertIsNone(media.period_need({}))


if __name__ == "__main__":
    unittest.main()
