"""
The owner's review of a news-compilation video (2026-09-30): a Texas flood
story, 138 scenes, 858 s.

  * 4 of its first 5 scenes were AI-generated illustrations, in the hook;
  * 97 YouTube scenes came from only 55 videos, and "Drone's eye view of Texas
    flood damage" played 4 times in the first minute (four different 10 s
    moments of one video - still one shot on screen);
  * 28 photo scenes showed 15 photos, 7 generated scenes 4 images;
  * the line "Dallas and Fort Worth. And folks in North Texas..." got a
    Houston photo instead of Dallas footage of the flood.

Each rule that answers one of these has its tests here. Network and models
are mocked throughout, as in tests/test_pipeline.py and tests/test_glen_fixes.py.
"""
import base64
import datetime
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from src import config, director, media, pools
from src.media import MediaAsset
from src.transcribe import Segment

TODAY = datetime.date(2026, 9, 30)
BRIEF = {"kind": "weather", "summary": "", "event": "July 2026 Central Texas floods", "year": 2026,
         "recent": True, "places": ["Kerr County, Texas", "Guadalupe River", "Houston, Texas"],
         "people": ["Greg Abbott"], "hookBeats": [0], "cast": [], "sections": []}
DALLAS = "Dallas and Fort Worth. And folks in North Texas are bracing for more rain."


def yt(vid: str, start: float) -> MediaAsset:
    """One moment of YouTube video `vid` (11 characters) cut at `start` s, as the pools make it."""
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                      local_path=f"/w/{vid}_{int(start)}.mp4", moment_key=f"yt:{vid}@{int(start // 8)}",
                      moment={"start": float(start)})


def photo(url: str) -> MediaAsset:
    return MediaAsset(kind="image", source="web_image", url=url, local_path="/w/photo.jpg")


def generated(path: str) -> MediaAsset:
    return MediaAsset(kind="image", source="generated", url="", local_path=path)


def job(i: int, start: float, subject: str = "Kerrville", **kw) -> dict:
    """A sourcing job as handler.do_plan builds it, with the line's start on the timeline."""
    return dict({"index": i, "query": f"{subject} flooding", "seconds": 5.0, "start": float(start),
                 "visual_type": "footage", "subject": subject, "subject_type": "place",
                 "intent": f"{subject} flood", "context": f"line {i}"}, **kw)


RULES = {"MAX_MOMENTS_PER_VIDEO": 2, "SAME_VIDEO_GAP_SECONDS": 120.0, "REUSE_MIN_GAP_SECONDS": 60.0,
         "IMAGE_MAX_USES": 1, "HOOK_SECONDS": 45.0, "GENERATED_IMAGES_IN_HOOK": False}


class _Rules(unittest.TestCase):
    """Every test runs on the documented defaults, whatever the environment says."""

    def setUp(self):
        self._patches = [mock.patch.object(config, k, v) for k, v in RULES.items()]
        for p in self._patches:
            p.start()
        media.reset_cache()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        media.reset_cache()
        media.set_story_kind("")
        with pools._RESERVE_LOCK:             # spare moments a pool test left behind
            pools._RESERVE.clear()


# --------------------------------------------------------------------------- #
# 1. Generated images: never in the hook, each shown once
# --------------------------------------------------------------------------- #

class GeneratedImages(_Rules):
    def _source(self, hook: bool, allow_in_hook: bool = False):
        made = []

        def gen(prompt, out_dir, **kw):
            made.append(prompt)
            return generated(f"/w/gen{len(made)}.png")
        with mock.patch.object(config, "PREFER_GENERATED_IMAGES", True), \
                mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 5), \
                mock.patch.object(config, "OFFICIAL_IMAGERY", False), \
                mock.patch.object(config, "GENERATED_IMAGES_IN_HOOK", allow_in_hook), \
                mock.patch.object(media, "_cached_search", return_value=[]), \
                mock.patch.object(media, "generate_image", side_effect=gen):
            got = media.source_for_segment("Kerrville flooding", 3.0, tempfile.mkdtemp(), visual_type="image",
                                           allow_youtube=False, prompt="Kerrville under water", hook=hook)
        return got, made

    def test_a_hook_scene_is_never_given_a_generated_image(self):
        got, made = self._source(hook=True)
        self.assertIsNone(got)
        self.assertEqual(made, [])
        got, made = self._source(hook=False)             # the same beat later in the video
        self.assertEqual(got.source, "generated")
        self.assertEqual(made, ["Kerrville under water"])

    def test_a_style_may_allow_generated_images_in_the_hook(self):
        _got, made = self._source(hook=True, allow_in_hook=True)
        self.assertEqual(len(made), 1)

    def test_the_last_resort_stills_skip_the_hook(self):
        made = []

        def gen(prompt, out_dir, **kw):
            made.append(prompt)
            return generated(f"/w/g{len(made)}.png")
        jobs = [{"index": 0, "query": "opening", "seconds": 3.0, "hook": True, "prompt": "opening"},
                {"index": 1, "query": "later", "seconds": 3.0, "prompt": "later"}]
        with mock.patch.object(media, "source_for_segment", return_value=None), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", side_effect=gen), \
                mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 10), \
                mock.patch.object(config, "FRESH_MOMENTS", False):
            out = media.source_many(jobs, "/tmp", workers=1)
        self.assertIsNone(out[0])
        self.assertEqual(made, ["later"])

    def test_every_generation_is_its_own_file(self):
        # Named after the prompt alone, two scenes with one prompt showed one image.
        with mock.patch.object(config, "IMAGE_API_KEY", "k"), \
                mock.patch.object(config, "IMAGE_API_BASE", "https://api.openai.com/v1"), \
                mock.patch.object(media, "_openai_generate",
                                  return_value={"b64_json": base64.b64encode(b"png").decode()}):
            d = tempfile.mkdtemp()
            a = media.generate_image("Kerrville under water", d)
            b = media.generate_image("Kerrville under water", d)
        self.assertNotEqual(a.local_path, b.local_path)
        self.assertNotEqual(a.identity, b.identity)
        self.assertTrue(os.path.isfile(a.local_path) and os.path.isfile(b.local_path))

    def test_the_final_pass_drops_a_generated_image_in_the_hook_or_shown_twice(self):
        jobs = [job(0, 0, hook=True), job(1, 60), job(2, 200)]
        g = generated("/w/gen_a.png")
        found = media.variety_violations(jobs, [generated("/w/gen_h.png"), g, g])
        self.assertEqual(found[0][1], "hard")
        self.assertNotIn(1, found)
        self.assertEqual(found[2], ("a generated image already shown", "hard"))

    def test_a_generated_image_is_never_reused_to_fill(self):
        jobs = [job(0, 0), job(1, 200)]
        results = [generated("/w/gen_a.png"), None]
        self.assertEqual(media.fill_from_story(jobs, results, max_uses=2), 0)
        self.assertIsNone(results[1])


# --------------------------------------------------------------------------- #
# 2. The hook is footage, and the strongest footage
# --------------------------------------------------------------------------- #

class HookIsFootage(_Rules):
    def test_opening_stills_become_footage_but_a_document_keeps_its_scan(self):
        segs = [Segment("Governor Greg Abbott spoke.", 0, 5), Segment("The disaster declaration.", 5, 10),
                Segment("A photo of the river.", 50, 55)]
        shots = [{"query": "Greg Abbott photo", "visualType": "image", "subjectType": "person",
                  "entity": "public-figure"},
                 {"query": "disaster declaration document scan", "visualType": "image", "subjectType": "document"},
                 {"query": "Guadalupe River photo", "visualType": "image", "subjectType": "place"}]
        self.assertEqual(director.hook_footage(segs, shots), 1)
        self.assertEqual(shots[0]["visualType"], "footage")
        self.assertNotIn("photo", shots[0]["query"])
        self.assertIn("speech footage", shots[0]["query"])
        self.assertEqual(shots[1]["visualType"], "image")         # a document
        self.assertEqual(shots[2]["visualType"], "image")         # after the hook

    def test_plan_makes_every_opening_beat_footage(self):
        segs = [Segment("Governor Greg Abbott said the water came at night.", 0, 5),
                Segment("Crews searched the Guadalupe River.", 5, 10),
                Segment("Officials said it was the worst in a century.", 60, 65)]
        with mock.patch.object(director, "is_configured", return_value=False), \
                mock.patch.object(director, "_today", return_value=TODAY), \
                mock.patch.object(director.geocode, "resolve_all", return_value=[]):
            shots, _kind, _warn = director.plan(segs, title="", allow_maps=False, brief=dict(BRIEF))
        self.assertEqual(shots[0]["visualType"], "footage")       # a quote line in the hook
        self.assertEqual(shots[2]["visualType"], "image")         # the same kind of line after it

    def test_a_hook_scene_is_sourced_as_footage_with_a_wider_best_of(self):
        seen = []

        def one(ctx):
            seen.append((ctx.visual_type, media._judge_limits()))
            return None
        with mock.patch.object(media.providers, "source_one", side_effect=one), \
                mock.patch.object(config, "JUDGE_BEST_OF", 2), mock.patch.object(config, "HOOK_JUDGE_BEST_OF", 3), \
                mock.patch.object(config, "POOL_SCOUT", 2), mock.patch.object(config, "HOOK_POOL_SCOUT", 4), \
                mock.patch.object(config, "JUDGE_MAX_PER_SCENE", 12), \
                mock.patch.object(config, "HOOK_JUDGE_MAX_PER_SCENE", 16), \
                mock.patch.object(config, "CLIPS_FIRST", False):
            media.source_for_segment("Kerrville flood", 3.0, "/tmp", visual_type="image", hook=True)
            hook = seen[0]
            seen.clear()
            media.source_for_segment("Kerrville flood", 3.0, "/tmp", visual_type="image")
            later = seen[0]
        self.assertEqual(hook[0], "footage")
        self.assertEqual((hook[1]["best_of"], hook[1]["scouts"], hook[1]["per_scene"]), (3, 4, 16))
        self.assertEqual(later[0], "image")
        self.assertEqual((later[1]["best_of"], later[1]["scouts"], later[1]["per_scene"]), (2, 2, 12))
        self.assertFalse(media._IN_HOOK.get())                    # reset after the scene

    def test_with_clips_first_the_hook_and_a_place_still_line_look_further_for_a_clip(self):
        seen = []

        def one(ctx):
            seen.append((ctx.visual_type, ctx.stage, media._judge_limits()))
            return None
        with mock.patch.object(media.providers, "source_one", side_effect=one), \
                mock.patch.object(config, "JUDGE_BEST_OF", 2), mock.patch.object(config, "HOOK_JUDGE_BEST_OF", 3), \
                mock.patch.object(config, "POOL_SCOUT", 2), mock.patch.object(config, "HOOK_POOL_SCOUT", 4), \
                mock.patch.object(config, "JUDGE_MAX_PER_SCENE", 12), \
                mock.patch.object(config, "HOOK_JUDGE_MAX_PER_SCENE", 16), \
                mock.patch.object(config, "CLIPS_FIRST", True), mock.patch.object(config, "CLIPS_FIRST_STILLS", True), \
                mock.patch.object(config, "CLIPS_FIRST_JUDGE_MAX_PER_SCENE", 20), \
                mock.patch.object(config, "CLIPS_FIRST_POOL_SCOUT", 3):
            media.source_for_segment("Kerrville flood", 3.0, "/tmp", visual_type="image", hook=True)
            hook = seen[0]
            seen.clear()
            media.source_for_segment("Kerrville flood", 3.0, "/tmp", visual_type="image", subject_type="place")
            later = seen[0]
            seen.clear()
            media.source_for_segment("The 1922 Compact", 3.0, "/tmp", visual_type="image", subject_type="document")
            document = seen[0]
        self.assertEqual(hook[:2], ("footage", "youtube"))
        self.assertEqual((hook[2]["best_of"], hook[2]["scouts"], hook[2]["per_scene"]), (3, 4, 24))
        self.assertEqual(later[:2], ("footage", "youtube"))       # a place still asks for a clip first
        self.assertEqual((later[2]["best_of"], later[2]["scouts"], later[2]["per_scene"]), (2, 3, 20))
        self.assertEqual(document[:2], ("image", "pictures"))     # a document keeps its scan first
        self.assertEqual(document[2]["per_scene"], 12)
        self.assertFalse(media._CLIP_FIRST.get())                 # reset after the scene

    def test_best_of_waits_for_more_passing_clips_in_the_hook(self):
        passed = [MediaAsset(kind="video", source="youtube", url="u", relevance_score=0.75) for _ in range(2)]
        with mock.patch.object(config, "JUDGE_BEST_OF", 2), mock.patch.object(config, "HOOK_JUDGE_BEST_OF", 3):
            self.assertTrue(media._good_enough(passed))
            tok = media._IN_HOOK.set(True)
            try:
                self.assertFalse(media._good_enough(passed))
            finally:
                media._IN_HOOK.reset(tok)

    def test_opening_lines_go_to_the_per_scene_path_not_a_pool(self):
        jobs = [job(0, 0, hook=True), job(1, 60), job(2, 200)]
        self.assertEqual([j["index"] for j in pools.groups(jobs)["kerrville"]], [1, 2])

    def test_the_hook_retry_takes_no_pictures(self):
        jobs = [job(0, 0, hook=True), job(1, 100)]
        results = [None, None]
        pics = [photo("https://x/a.jpg"), photo("https://x/b.jpg")]
        with mock.patch.object(config, "FRESH_MOMENTS", False), \
                mock.patch.object(config, "ALLOW_WEB_IMAGES", True), \
                mock.patch.object(media, "_yt_candidates", return_value=[]), \
                mock.patch.object(media, "_cached_search", return_value=pics), \
                mock.patch.object(media, "_download", side_effect=lambda c, q, w: c), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_rescue_local_ok", return_value=True):
            media.rescue_fill(jobs, results, tempfile.mkdtemp(), footage_only={0})
        self.assertIsNone(results[0])               # the opening waits for footage
        self.assertEqual(results[1].kind, "image")  # a later line may still take a picture

    def test_an_opening_still_is_retried_for_footage_and_kept_if_none(self):
        jobs = [job(0, 0, hook=True), job(1, 100)]
        still = photo("https://x/kerrville.jpg")
        results = [still, yt("AAAAAAAAAAA", 5)]
        held = media.hold_violations(jobs, results)
        self.assertEqual(held[0][2], "upgrade")
        self.assertIsNone(results[0])
        self.assertEqual(media.restore_held(jobs, results, held), {"replaced": 0, "restored": 1, "dropped": 0})
        self.assertIs(results[0], still)


# --------------------------------------------------------------------------- #
# 3. Reuse caps: two scenes per video, far apart; a photo once
# --------------------------------------------------------------------------- #

class ReuseCaps(_Rules):
    def test_one_video_supplies_two_scenes_far_apart(self):
        jobs = [job(i, s) for i, s in enumerate([0, 10, 20, 150, 300, 450])]
        results = [yt("AAAAAAAAAAA", 20), yt("AAAAAAAAAAA", 60), yt("BBBBBBBBBBB", 5),
                   yt("AAAAAAAAAAA", 100), yt("AAAAAAAAAAA", 140), yt("BBBBBBBBBBB", 5)]
        found = media.variety_violations(jobs, results)
        self.assertEqual(sorted(found), [1, 4, 5])
        self.assertTrue(all(kind == "soft" for _why, kind in found.values()))
        self.assertIn("120", found[1][0])                       # a different moment 10 s later
        self.assertIn("2 scenes", found[4][0])                  # a third scene from one video
        self.assertEqual(found[5][0], "the same shot again")

    def test_without_starts_only_the_count_is_judged(self):
        jobs = [{"index": i, "query": "q", "seconds": 5.0} for i in range(3)]
        results = [yt("AAAAAAAAAAA", 20), yt("AAAAAAAAAAA", 60), yt("AAAAAAAAAAA", 100)]
        self.assertEqual(sorted(media.variety_violations(jobs, results)), [2])

    def test_a_photo_is_shown_once(self):
        jobs = [job(0, 0), job(1, 100), job(2, 300)]
        p = photo("https://x/houston.jpg")
        self.assertEqual(media.variety_violations(jobs, [p, yt("AAAAAAAAAAA", 5), p]),
                         {2: ("a photo already shown", "hard")})

    def test_consecutive_pool_lines_never_share_a_video(self):
        # "Drone's eye view of Texas flood damage" played 4 times in the first minute.
        jobs = [job(i, 50 + 5 * i) for i in range(4)] + [job(4, 300)]
        cands = [{"id": "DRONEEYE000", "title": "Drone's eye view of Texas flood damage"},
                 {"id": "KSAT1200000", "title": "Kerrville flooding | KSAT 12"}]
        rated = [{"start": 10.0 * k, "score": 0.9, "description": ""} for k in range(1, 8)]
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: [dict(c) for c in cands]), \
                mock.patch.object(pools, "rate_video", lambda c, s, ctx, sec, **kw: [dict(m) for m in rated]), \
                mock.patch.dict(director.LAST_STORY, {}, clear=True):
            plan, spare = pools.plan_subject("Kerrville", jobs, False, set(), claim=lambda k: True)
        by_line = {j["index"]: c["id"] for j, c, _m in plan}
        self.assertEqual(sorted(by_line), [0, 1, 4])            # lines 2 and 3 go to per-scene sourcing
        self.assertNotEqual(by_line[0], by_line[1])
        used = list(by_line.values())
        self.assertTrue(all(used.count(v) <= 2 for v in used))
        self.assertEqual(len(spare), 1)                         # KSAT's second moment, for the reserve

    def test_the_subjects_share_one_ledger(self):
        # The Kerrville and the Hunt searches both find one report: it may not
        # play again 10 s later under the other subject's name.
        jobs = [job(0, 0, subject="Kerrville"), job(1, 10, subject="Hunt"),
                job(2, 20, subject="Kerrville"), job(3, 30, subject="Hunt")]
        cands = [{"id": "SAMEREPORT0", "title": "Hill Country flooding report"}]
        rounds = iter([[10.0, 20.0], [30.0, 40.0]])

        def rate(c, s, ctx, sec, **kw):
            return [{"start": t, "score": 0.9, "description": ""} for t in next(rounds)]

        def fetch(job_, cand, m, work, require_cc, subject, library=None):
            return yt(cand["id"], m["start"])
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: [dict(c) for c in cands]), \
                mock.patch.object(pools, "rate_video", rate), mock.patch.object(pools, "_fetch", fetch), \
                mock.patch.object(config, "POOL_MIN_SCENES", 2), mock.patch.object(config, "POOL_PARALLEL_SUBJECTS", 1), \
                mock.patch.dict(director.LAST_STORY, {}, clear=True):
            got = pools.source_by_subject(jobs, "/w")
        self.assertEqual(sorted(got), [0])
        self.assertIn("SAMEREPORT0", got[0].url)

    def test_another_moment_of_a_video_respects_the_caps(self):
        work = tempfile.mkdtemp()
        jobs = [job(0, 0), job(1, 30), job(2, 400)]
        results = [yt("AAAAAAAAAAA", 40), None, None]

        def fetch(vid, out, at, need, title=""):
            p = os.path.join(out, f"yt_{vid}_{int(at * 1000)}_5000_x.mp4")
            pathlib.Path(p).write_bytes(b"x")
            return p
        with mock.patch.object(media, "_yt_fetch_retry", side_effect=fetch), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(config, "LOCAL_VISION_ENABLED", False), \
                mock.patch.object(media.vision, "enabled", return_value=False):
            self.assertEqual(media.fresh_moments(jobs, results, work), 1)
        self.assertIsNone(results[1])                           # 30 s after its twin
        self.assertIn("AAAAAAAAAAA", results[2].url)            # 400 s later: the video's second scene
        # Two scenes already: no third, however far away.
        jobs.append(job(3, 900))
        results.append(None)
        with mock.patch.object(media, "_yt_fetch_retry", side_effect=AssertionError("capped")):
            self.assertEqual(media.fresh_moments(jobs, results, work), 0)

    def test_a_repeat_nothing_replaced_comes_back_only_far_from_its_twin(self):
        jobs = [job(0, 0), job(1, 20), job(2, 90)]
        results = [yt("AAAAAAAAAAA", 10), yt("AAAAAAAAAAA", 50), yt("AAAAAAAAAAA", 90)]
        held = media.hold_violations(jobs, results)
        self.assertEqual(sorted(held), [1, 2])                  # both within 120 s of the first scene
        stats = media.restore_held(jobs, results, held)
        self.assertEqual(stats, {"replaced": 0, "restored": 1, "dropped": 1})
        self.assertIsNone(results[1])                           # 20 s from its twin: never
        self.assertTrue(results[2].review_required)             # 90 s away: kept, flagged
        self.assertIn("Same source video", results[2].review_reason)

    def test_reuse_is_footage_never_a_photo_and_never_near_its_twin(self):
        jobs = [job(0, 0), job(1, 30), job(2, 60), job(3, 400)]
        clip = yt("AAAAAAAAAAA", 20)
        results = [photo("https://x/houston.jpg"), clip, None, None]
        self.assertEqual(media.fill_from_story(jobs, results, max_uses=2), 1)
        self.assertIsNone(results[2])                           # the photo is spent, the clip 30 s away
        self.assertEqual(results[3].identity, clip.identity)    # 370 s away
        self.assertTrue(results[3].review_required)

    def test_the_reserve_never_places_a_spare_near_its_video(self):
        jobs = [job(0, 0), job(1, 30), job(2, 300)]
        with pools._RESERVE_LOCK:
            pools._RESERVE[:] = [("kerrville", {"id": "AAAAAAAAAAA", "title": "Kerrville flood"},
                                  {"start": 90.0, "score": 0.9, "description": ""})]

        def fetch(job_, cand, m, work, require_cc, subject, library=None):
            return yt(cand["id"], m["start"])
        try:
            with mock.patch.object(pools, "_fetch", fetch):
                got = pools.fill_from_reserve(jobs, [1, 2], "/w", assets=[yt("AAAAAAAAAAA", 10), None, None])
        finally:
            with pools._RESERVE_LOCK:
                pools._RESERVE.clear()
        self.assertEqual(sorted(got), [2])                      # 30 s after video A: no; 300 s: yes


# --------------------------------------------------------------------------- #
# 4. The place the line names, the event, and recent uploads
# --------------------------------------------------------------------------- #

class PlaceAndEvent(_Rules):
    def test_the_event_word_comes_from_the_line_then_the_story(self):
        self.assertEqual(director.event_word(BRIEF, DALLAS), "flooding")
        self.assertEqual(director.event_word(BRIEF, "A flash flood emergency for San Antonio."), "flash flooding")
        self.assertEqual(director.event_word({"event": "Park Fire 2026"}, "The wildfire jumped the ridge."),
                         "wildfire")
        self.assertEqual(director.event_word({"event": "2026 Colorado River water cuts"}), "")

    def test_the_places_a_line_names(self):
        self.assertEqual(director.line_places(DALLAS, BRIEF),
                         [("Dallas", 0), ("Fort Worth", 0), ("North Texas", 1)])
        got = director.line_places("In Kerrville, Texas, the Guadalupe River rose 26 feet.", BRIEF)
        self.assertIn(("Kerrville", 0), got)
        self.assertEqual(got[-1], ("Texas", 2))                 # a whole state last
        self.assertEqual(director.line_places(
            "Governor Greg Abbott thanked FEMA and the National Weather Service.", BRIEF), [])
        self.assertEqual(director.line_places("Hurricane Beryl hit Houston last year.", BRIEF), [("Houston", 0)])
        self.assertEqual(director.line_places("Dallas-Fort Worth got four inches overnight.", BRIEF),
                         [("Dallas-Fort Worth", 0)])
        self.assertEqual(director.line_places("Crews worked at Camp Mystic all night.", BRIEF),
                         [("Camp Mystic", 0)])
        self.assertEqual(director.line_places("A statement from John Walker came later.", BRIEF), [])

    def test_the_dallas_line_searches_dallas_not_the_story_s_first_place(self):
        segs = [Segment(DALLAS, 60, 66)]
        shots = [{"query": "Texas flooding aerial", "visualType": "footage", "subject": "Texas",
                  "subjectType": "place", "intent": "Flooding across Texas", "fallbacks": []}]
        with mock.patch.object(director, "_today", return_value=TODAY):
            self.assertEqual(director.pin_line_places(segs, shots, BRIEF), 1)
            director.anchor_to_story(shots, segs, BRIEF)
        s = shots[0]
        self.assertEqual(s["linePlace"], "Dallas")
        self.assertTrue(s["query"].startswith("Dallas"))
        self.assertIn("flooding", s["query"])
        self.assertNotIn("Kerr", s["query"])
        self.assertEqual(s["subject"], "Dallas")                # its own pool, its own search cache
        self.assertIn("Dallas", s["intent"])
        self.assertNotIn("Kerr County", s["intent"])            # the judge checks Dallas
        self.assertEqual(s["fallbacks"][0], "Dallas flooding 2026")
        self.assertEqual((s["eventWindow"], s["recency"]), ("year", "month"))

    def test_a_query_about_another_of_the_story_s_places_is_rebuilt(self):
        shots = [{"query": "Houston flooded freeway", "visualType": "footage", "subject": "Houston",
                  "subjectType": "place", "intent": "", "fallbacks": []}]
        director.pin_line_places([Segment(DALLAS, 60, 66)], shots, BRIEF)
        self.assertEqual(shots[0]["query"], "Dallas flooding 2026")
        self.assertEqual(shots[0]["fallbacks"][0], "Houston flooded freeway")

    def test_a_line_about_the_whole_state_or_a_past_story_is_left_alone(self):
        shot = {"query": "Texas flood warnings", "visualType": "footage", "subject": "Texas",
                "subjectType": "place", "intent": "", "fallbacks": []}
        whole = [dict(shot)]
        self.assertEqual(director.pin_line_places(
            [Segment("Flood warnings stretch across Texas tonight.", 0, 5)], whole, BRIEF), 0)
        self.assertNotIn("linePlace", whole[0])
        past = dict(BRIEF, kind="history", year=1921, recent=False)
        with mock.patch.object(director, "_today", return_value=TODAY):
            self.assertEqual(director.pin_line_places([Segment(DALLAS, 0, 5)], [dict(shot)], past), 0)

    def test_plan_gives_the_judge_the_line_s_places_and_searches_them_first(self):
        segs = [Segment("Floodwaters rose again overnight.", 0, 5), Segment(DALLAS, 60, 66)]
        with mock.patch.object(director, "is_configured", return_value=False), \
                mock.patch.object(director, "_today", return_value=TODAY), \
                mock.patch.object(director.geocode, "resolve_all", return_value=[]), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            shots, _kind, _warn = director.plan(segs, title="Texas Floods", allow_maps=False, brief=dict(BRIEF))
        s = shots[1]
        self.assertEqual(s["sceneIntent"]["locations"], ["Dallas", "Fort Worth", "North Texas"])
        self.assertEqual(s["newsQueries"][0], "Dallas flooding 2026")
        self.assertNotEqual(s["subjectType"], "person")          # "Dallas and Fort Worth" is no interviewee
        self.assertNotIn("interview", s["query"])
        self.assertEqual(s["recency"], "month")

    def test_pools_group_a_line_by_the_place_it_names(self):
        jobs = [job(0, 60, subject="Texas", place="Dallas"), job(1, 200, subject="Texas", place="Dallas"),
                job(2, 300, subject="Texas"), job(3, 420, subject="Texas")]
        g = pools.groups(jobs)
        self.assertEqual({k: [j["index"] for j in v] for k, v in g.items()}, {"dallas": [0, 1], "texas": [2, 3]})
        self.assertEqual(pools.display_name(g["dallas"]), "Dallas")

    def test_a_story_about_now_pools_the_last_month_first(self):
        story = {"kind": "weather", "is_event": True, "event": "July 2026 Central Texas floods", "year": 2026,
                 "window": "year", "recency": "month", "word": "flooding"}
        got = pools._searches("Dallas", story)
        self.assertEqual(got[0], ("Dallas flooding 2026", "event-now", "month"))
        self.assertIn(("Dallas flooding 2026", "event", ""), got)      # older uploads, ranked after
        self.assertLessEqual(len(got), pools.POOL_SEARCHES_MAX)
        self.assertIn("sp=EgIIBA%3D%3D", pools._target(got[0][0], False, "month"))
        self.assertIn("sp=EgIIAw%3D%3D", pools._target("Dallas flooding", False, "week"))
        old = {"id": "OLDFLOOD000", "title": "Dallas flooding 2026 aerial", "duration": 300, "aspect": 1.78,
               "channel": ""}
        new = {"id": "NEWFLOOD000", "title": "Dallas flooding news", "duration": 120, "aspect": 1.78,
               "channel": ""}

        def flat(target, cc, subject="", variant=""):
            return [dict(new)] if "EgIIBA" in target else [dict(old)]
        with mock.patch.object(media, "_yt_candidates_cached", flat), \
                mock.patch.object(media, "_channel_candidates", lambda *a, **k: []), \
                mock.patch.object(config, "NEWS_FOOTAGE", True), mock.patch.object(config, "NEWS_CHANNELS", []):
            ranked = pools.candidates("Dallas", False, set(), story=story)
        self.assertEqual([c["id"] for c in ranked], ["NEWFLOOD000", "OLDFLOOD000"])
        self.assertTrue(ranked[0]["_recent"])

    def test_subject_story_reads_the_recency_and_the_event_word(self):
        with mock.patch.dict(director.LAST_STORY, BRIEF, clear=True), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            story = pools.subject_story([job(0, 60, recency="month", event_window="year")])
        self.assertEqual((story["recency"], story["word"]), ("month", "flooding"))


class RecentUploadsFirst(_Rules):
    def _clip(self, fake_pool):
        with mock.patch.object(media, "_youtube_pool", side_effect=fake_pool), \
                mock.patch.object(config, "CANDIDATE_POOL", True), \
                mock.patch.object(config, "RECENT_FOOTAGE_FIRST", True), \
                mock.patch.object(media, "_story_channels", return_value=[]):
            w, r = media._EVENT_WINDOW.set("year"), media._RECENCY.set("month")
            try:
                return media.youtube_clip("Dallas flooding 2026", "/tmp/x", seconds=3.0,
                                          require_cc=False, subject="Dallas")
            finally:
                media._RECENCY.reset(r)
                media._EVENT_WINDOW.reset(w)

    def test_a_passing_clip_from_the_last_month_ends_the_search(self):
        calls = []
        good = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=NEWFLOOD000",
                          relevance_score=0.8)

        def fake(query, out_dir, seconds, start_at, cc, skip, used, intent, context, subject, searches,
                 expand=True):
            calls.append(([s[2] for s in searches], expand))
            return good
        self.assertIs(self._clip(fake), good)
        self.assertEqual(calls, [(["month", "month"], False)])

    def test_older_uploads_only_when_nothing_recent_passes(self):
        calls = []
        near = MediaAsset(kind="video", source="youtube", url="u1", relevance_score=0.6, review_required=True,
                          review_reason="Best available: the vision check scored it 0.60")
        old = MediaAsset(kind="video", source="youtube", url="u2", relevance_score=0.8)

        def fake(query, out_dir, seconds, start_at, cc, skip, used, intent, context, subject, searches,
                 expand=True):
            calls.append([s[2] for s in searches])
            return near if len(calls) == 1 else old
        self.assertIs(self._clip(fake), old)
        self.assertEqual(calls, [["month", "month"], [True, True, False]])

    def test_the_upload_date_filters(self):
        self.assertIn("sp=EgIIBA%3D%3D", media._search_target("Dallas flooding", False, "month"))
        self.assertIn("sp=EgIIAw%3D%3D", media._search_target("Dallas flooding", False, "week"))
        self.assertIn("sp=" + media._YT_THIS_YEAR, media._search_target("Dallas flooding", False, True))
        self.assertTrue(media._search_target("Dallas flooding", False, "").startswith("ytsearch"))
        self.assertIn("sp=EgIwAQ%3D%3D", media._search_target("Dallas flooding", True, "month"))

    def test_dailymotion_takes_the_last_month_first(self):
        tried = []
        now = time.time()

        def search(query, limit=12, created_after=0):
            row = {"title": "Dallas flooding", "duration": 120.0, "aspect": 1.78}
            if not created_after:
                return [dict(row, id="old")]
            return [dict(row, id="month" if created_after > now - 40 * 86400 else "year")]
        with mock.patch.object(media, "search_dailymotion", search), \
                mock.patch.object(media, "_dm_fetch", side_effect=lambda vid, *a, **k: tried.append(vid) or ""), \
                mock.patch.object(config, "RECENT_FOOTAGE_FIRST", True):
            w, r = media._EVENT_WINDOW.set("year"), media._RECENCY.set("month")
            try:
                media.dailymotion_clip("Dallas flooding", "/tmp/x", seconds=3.0, subject="Dallas")
            finally:
                media._RECENCY.reset(r)
                media._EVENT_WINDOW.reset(w)
        self.assertEqual(tried, ["month", "year", "old"])

    def test_the_recent_pass_leaves_the_intent_s_own_searches_for_later(self):
        seen = []

        def cached(target, cc, subject="", variant=""):
            seen.append(variant)
            return []
        si = {"entities": ["Kerrville"], "locations": ["Kerrville"], "event_type": "flood",
              "time_context": "current", "specificity": "event"}
        with mock.patch.object(media, "_yt_candidates_cached", cached), \
                mock.patch.object(config, "POOL_EXTRA_QUERIES", 2):
            tok, tried = media._SCENE_INTENT.set(si), media._SCENE_TRIED.set(set())
            try:
                media._youtube_pool("Kerrville flooding", "/tmp/x", 3.0, 30.0, False, 0, set(), "Kerrville flood",
                                    "", "Kerrville", [("Kerrville flooding", "month", "month")], expand=False)
                recent = list(seen)
                seen.clear()
                media._youtube_pool("Kerrville flooding", "/tmp/x", 3.0, 30.0, False, 0, set(), "Kerrville flood",
                                    "", "Kerrville", [("Kerrville flooding", "plain", False)])
            finally:
                media._SCENE_TRIED.reset(tried)
                media._SCENE_INTENT.reset(tok)
        self.assertEqual(recent, ["month"])
        self.assertIn("intent", seen)

    def test_the_rescue_takes_a_recent_upload_before_a_better_titled_old_one(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "r.mp4")
        pathlib.Path(path).write_bytes(b"x")

        def cands(target, cc, limit=8, timeout=40):
            if "EgIIBA" in target:
                return [{"id": "NEWFLOOD000", "title": "Kerrville flooding today", "duration": 240.0}]
            return [{"id": "OLDFLOOD000", "title": "Kerrville flood aerial drone footage 4k", "duration": 240.0}]
        results = [None]
        # The unjudged title search (the judged clip-first search before it is its own test).
        with mock.patch.object(config, "CLIPS_FIRST", False), \
                mock.patch.object(config, "FRESH_MOMENTS", False), mock.patch.object(config, "ALLOW_WEB_IMAGES", False), \
                mock.patch.object(media, "_yt_candidates", side_effect=cands), \
                mock.patch.object(media, "fetch_clean_clip", return_value=(path, True, 0)), \
                mock.patch.object(media._filters, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_rescue_local_ok", return_value=True):
            media.rescue_fill([job(0, 100, recency="month")], results, d)
        self.assertIn("NEWFLOOD000", results[0].url)

    def test_the_rescue_search_asks_for_the_last_month_first(self):
        targets = []

        def cands(target, cc, limit=8, timeout=40):
            targets.append(target)
            return []
        with mock.patch.object(config, "CLIPS_FIRST", False), \
                mock.patch.object(config, "FRESH_MOMENTS", False), mock.patch.object(config, "ALLOW_WEB_IMAGES", False), \
                mock.patch.object(media, "_yt_candidates", side_effect=cands):
            media.rescue_fill([job(0, 100, recency="month")], [None], tempfile.mkdtemp())
        self.assertIn("EgIIBA", targets[0])
        self.assertTrue(targets[1].startswith("ytsearch8:"))


# --------------------------------------------------------------------------- #
# 5. The handler: style keys, the part's reserve, the render copy, the final pass
# --------------------------------------------------------------------------- #

class HandlerWiring(_Rules):
    def test_the_news_styles_can_turn_ai_images_off_per_job(self):
        import handler
        for key in ("IMAGE_MAX_PER_VIDEO", "PREFER_GENERATED_IMAGES", "GENERATED_IMAGES_IN_HOOK", "HOOK_SECONDS",
                    "MAX_MOMENTS_PER_VIDEO", "SAME_VIDEO_GAP_SECONDS", "REUSE_MIN_GAP_SECONDS", "IMAGE_MAX_USES"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
        prev = handler._apply_config({"IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False,
                                      "MAX_MOMENTS_PER_VIDEO": "3"})
        try:
            self.assertEqual(config.IMAGE_MAX_PER_VIDEO, 0)
            self.assertFalse(config.PREFER_GENERATED_IMAGES)
            self.assertEqual(config.MAX_MOMENTS_PER_VIDEO, 3)
            media.reset_cache()
            self.assertFalse(media._generation_budget_left())
        finally:
            handler._restore_config(prev)

    def test_a_part_hands_its_repeated_video_to_its_pool_reserve(self):
        import handler
        jobs = [job(0, 0), job(1, 10), job(2, 400)]
        pooled = {0: yt("AAAAAAAAAAA", 20)}

        def rest(lines, taken):                 # another worker's pick: video A again, 10 s later
            return [yt("AAAAAAAAAAA", 60), yt("CCCCCCCCCCC", 5)]
        with mock.patch.object(config, "SUBJECT_POOLS", True), \
                mock.patch.object(pools, "source_by_subject", return_value=pooled), \
                mock.patch.object(pools, "fill_from_reserve", return_value={1: yt("BBBBBBBBBBB", 30)}) as ffr:
            got, _pooled = handler._source_with_pools(jobs, "/w", require_cc=False, exclude=set(), source_rest=rest)
        self.assertEqual(ffr.call_args.args[1], [1])
        self.assertIn("BBBBBBBBBBB", got[1].url)

    def test_the_render_copy_never_borrows_a_shot_it_holds_the_neighbour(self):
        # Was: the render copy borrowed footage from elsewhere (a far twin
        # first). The owner's rules (2026-10-01) - never reuse a clip within a
        # video, never an empty scene - make it hold the neighbouring shot over
        # the empty line instead (the scenes merge); no url appears twice.
        # (3 s lines since 2026-10-04: a hold never makes a shot longer than
        # SHOT_MAX_SECONDS, 7 s - tests/test_shot_cap.py covers what happens then.)
        import handler
        fps = 30

        def scene(sec, media_, subject="Texas", asset=""):
            return {"id": f"s{sec:04d}", "startFrame": sec * fps, "durationInFrames": 3 * fps,
                    "text": f"line at {sec}", "media": media_,
                    "semanticMetadata": {"subject": subject, "assetId": asset}}

        def empty():
            return {"type": "color", "url": "", "source": "none"}
        only_a_photo = {"fps": fps, "meta": {}, "overlays": [], "scenes": [
            scene(0, {"type": "image", "url": "https://x/houston.jpg", "source": "web_image"}),
            scene(3, empty())]}
        clips = {"fps": fps, "meta": {}, "overlays": [], "scenes": [
            scene(100, {"type": "video", "url": "https://x/a.mp4", "source": "youtube", "clipSeconds": 9.0},
                  asset="yt:AAAAAAAAAAA@2"),
            scene(103, empty()),
            scene(106, {"type": "video", "url": "https://x/b.mp4", "source": "youtube", "clipSeconds": 9.0},
                  asset="yt:BBBBBBBBBBB@0")]}
        with mock.patch.object(config, "ANIMATION_FILL", False):
            self.assertEqual(handler._fill_missing_media(only_a_photo), 1)
            self.assertEqual(handler._fill_missing_media(clips), 1)
        self.assertEqual(len(only_a_photo["scenes"]), 1)                           # the photo holds over the line
        self.assertEqual(only_a_photo["scenes"][0]["durationInFrames"], 6 * fps)
        self.assertEqual([s["media"]["url"] for s in clips["scenes"]], ["https://x/a.mp4", "https://x/b.mp4"])
        self.assertEqual(sum(s["durationInFrames"] for s in clips["scenes"]), 9 * fps)    # nothing lost
        self.assertEqual(clips["scenes"][1]["startFrame"], clips["scenes"][0]["durationInFrames"] + 100 * fps)
        self.assertIn("line at 103", " ".join(s["text"] for s in clips["scenes"]))

    def test_do_plan_clears_and_re_sources_what_breaks_a_rule(self):
        """do_plan end to end up to the timeline build, with the network mocked."""
        import handler

        class Built(Exception):
            pass

        starts = [0, 5, 10, 200, 205, 400]
        segs = [Segment(f"line {i}", s, s + 5) for i, s in enumerate(starts)]
        shots = [{"query": f"Kerrville flood {i}", "visualType": "footage", "subject": "Kerrville",
                  "subjectType": "place", "intent": "Kerrville flood", "fallbacks": [], "eventWindow": "year",
                  "recency": "month"} for i in range(len(segs))]
        shots[3].update(linePlace="Dallas", subject="Dallas")
        sourced = [generated("/w/gen0.png"),      # 0 s: an AI image in the opening
                   photo("https://x/k.jpg"),       # 5 s: a still in the opening
                   yt("DRONEEYE000", 10),          # 10 s
                   yt("DRONEEYE000", 30),          # 200 s: the video's second scene, far enough
                   yt("DRONEEYE000", 50),          # 205 s: a third scene, 5 s after the second
                   yt("KSAT1200000", 5)]           # 400 s
        seen = {}

        def source_many(jobs, work, **kw):
            seen["jobs"] = [dict(j) for j in jobs]
            return [sourced[j["index"]] for j in sorted(jobs, key=lambda j: j["index"])]

        def rescue(jobs, results, work, youtube_only=False, footage_only=()):
            seen["footage_only"] = set(footage_only)
            seen["empty"] = [i for i, a in enumerate(results) if a is None]
            results[0] = yt("RESCUE00000", 30)     # footage found for the opening scene only
            return {"fresh": 0, "search": 1, "image": 0, "asked": len(seen["empty"])}

        def build(segments, shots_, assets, **kw):
            seen["assets"] = list(assets)
            raise Built()
        with mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"), \
                mock.patch.object(handler.storage, "download", return_value="/w/vo.mp3"), \
                mock.patch.object(handler.renderer, "probe_duration", return_value=420.0), \
                mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]), \
                mock.patch.object(handler.transcribe, "segment_words", return_value=segs), \
                mock.patch.object(handler.director, "story_brief", return_value=dict(BRIEF)), \
                mock.patch.object(handler.director, "plan", return_value=(shots, "ai", [])), \
                mock.patch.object(handler.library.Library, "load", return_value=None), \
                mock.patch.object(handler.fanout, "enabled_for", return_value=False), \
                mock.patch.object(pools, "source_by_subject", return_value={}), \
                mock.patch.object(pools, "fill_from_reserve", return_value={}) as reserve, \
                mock.patch.object(media, "source_many", side_effect=source_many), \
                mock.patch.object(media, "rescue_fill", side_effect=rescue), \
                mock.patch.object(handler.timeline, "build", side_effect=build), \
                mock.patch.object(handler.gapfill, "fill_empty", return_value={}) as ladder, \
                mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False), \
                mock.patch.object(config, "SUBJECT_POOLS", True), mock.patch.object(config, "REUSE_SHOTS_TO_FILL", False):
            try:
                with self.assertRaises(Built):
                    handler.do_plan({"audio_url": "vo.mp3", "project_id": ""}, tempfile.mkdtemp(),
                                    handler.Reporter(""))
            finally:
                media.set_youtube_only(False)
                handler.vision.set_story({})
        self.assertEqual(reserve.call_args.args[1], [0, 1, 4])        # the pools' spares are asked first
        jobs = seen["jobs"]
        self.assertEqual([j["start"] for j in jobs], [float(s) for s in starts])
        self.assertEqual([j["hook"] for j in jobs], [True, True, True, False, False, False])
        self.assertEqual(jobs[3]["place"], "Dallas")
        self.assertTrue(all(j["recency"] == "month" for j in jobs))
        self.assertEqual(seen["footage_only"], {0, 1, 2})              # the opening: footage only
        self.assertEqual(seen["empty"], [0, 1, 4])                     # the three rule-breakers, cleared
        got = seen["assets"]
        self.assertIn("RESCUE00000", got[0].url)                      # the AI image replaced by footage
        self.assertEqual(got[1].url, "https://x/k.jpg")               # no footage found: the still stays
        self.assertIsNone(got[4])                                     # 5 s from its twin: never kept...
        ladder.assert_called_once()                                   # ...it goes to the fallback ladder
        self.assertIsNone(ladder.call_args.args[1][4])                # (src/gapfill.py, mocked here)
        self.assertEqual([a.url for a in (got[2], got[3], got[5])],
                         [sourced[2].url, sourced[3].url, sourced[5].url])
        variety = media.LAST_STATS["pools"]["variety"]
        self.assertEqual((variety["replaced"], variety["restored"], variety["dropped"], variety["held"]),
                         (1, 1, 1, 3))


if __name__ == "__main__":
    unittest.main()
