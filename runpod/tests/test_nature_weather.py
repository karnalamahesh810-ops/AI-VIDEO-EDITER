"""The Nature & Weather style (src/styles.py nature_weather; the owner, 2026-09-30).

"Most clips are realistic flood/storm footage of the exact place, few images,
and the editing keeps people watching to the end, like something is coming."
Measured against the reference channel (scratchpad ref_noreaster): regional
place matching, one strong clip cut into several shots, the hook held longer,
real photos a minority, never TV studios or AI.
"""
import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

import handler
from src import config, director, media, pools, styles
from src.transcribe import Segment, Word

YEAR = datetime.date.today().year
BRIEF = {"kind": "weather", "year": YEAR, "recent": True, "event": f"{YEAR} Jersey Shore nor'easter flooding",
         "summary": "A nor'easter floods the Jersey Shore and the Outer Banks.",
         "places": ["Atlantic City, New Jersey", "Outer Banks, North Carolina", "Virginia"],
         "people": [], "hookBeats": [0], "sections": [], "cast": []}


def seg(text, start, end):
    words, n = [], text.split()
    step = (end - start) / max(1, len(n))
    for k, w in enumerate(n):
        words.append(Word(w, round(start + k * step, 3), round(start + (k + 1) * step - 0.02, 3)))
    return Segment(text=text, start=start, end=end, words=words)


def style_patches(style="nature_weather"):
    inp = {"video_style": style}
    styles.apply(inp)
    out = []
    for k, v in inp["config"].items():
        if hasattr(config, k):
            cur = getattr(config, k)
            if isinstance(cur, bool):
                v = bool(v)
            elif isinstance(cur, (int, float)) and not isinstance(v, bool):
                v = type(cur)(v)
            out.append(mock.patch.object(config, k, v))
    return out


class Styled(unittest.TestCase):
    def setUp(self):
        for p in style_patches():
            p.start()
            self.addCleanup(p.stop)
        saved = dict(director.LAST_STORY)
        director.LAST_STORY.clear()
        director.LAST_STORY.update(BRIEF)
        self.addCleanup(lambda: (director.LAST_STORY.clear(), director.LAST_STORY.update(saved)))


class TheStyle(unittest.TestCase):
    def test_named_nature_and_weather(self):
        for name in ("nature_weather", "Nature & Weather", "nature / weather", "weather", "nature"):
            inp = {"video_style": name}
            self.assertEqual(styles.apply(inp), "nature_weather", name)
        inp = {"video_style": "Nature & Weather"}
        styles.apply(inp)
        cfg = inp["config"]
        self.assertEqual(styles.STYLES["nature_weather"]["label"], "Nature & Weather")
        self.assertEqual(cfg["MAX_SCENE_SECONDS"], 7.0)                 # the owner's rule
        self.assertEqual((cfg["IMAGE_MAX_PER_VIDEO"], cfg["PREFER_GENERATED_IMAGES"], cfg["GENERATED_IMAGES_IN_HOOK"]),
                         (0, False, False))
        self.assertTrue(cfg["ALLOW_VERTICAL"] and cfg["NEWS_FOOTAGE"] and cfg["RECENT_FOOTAGE_FIRST"])
        self.assertTrue(cfg["EYEWITNESS_SEARCHES"] and cfg["REGION_BLOCKS"] and cfg["CHAIN_SHOTS"])
        self.assertGreater(cfg["PHOTO_MAX_PER_10MIN"], 0)
        self.assertGreater(cfg["MOTION_PREFERENCE"], 0)
        self.assertEqual((inp["style"], inp["graphics_density"]), ("crossfade", "minimal"))
        self.assertEqual(inp["bgm_genre"], "suspense")                  # music on, ducked by the timeline
        self.assertNotIn("bgm", inp)
        # A job's own choice of track still wins.
        own = {"video_style": "nature_weather", "bgm_genre": "investigative"}
        styles.apply(own)
        self.assertEqual(own["bgm_genre"], "investigative")

    def test_every_new_setting_is_allowed_per_job(self):
        for style in ("nature_weather", "news_compilation"):
            for key in styles.STYLES[style]["config"]:
                self.assertIn(key, handler.CONFIG_OVERRIDABLE, (style, key))
        prev = handler._apply_config({"CROSS_VIDEO_REUSE_DAYS": "0", "MOTION_PREFERENCE": "0.2",
                                      "CHAIN_SHOTS": "true", "AI_SLOP_FILTER": "0"})
        try:
            self.assertEqual((config.CROSS_VIDEO_REUSE_DAYS, config.MOTION_PREFERENCE, config.CHAIN_SHOTS,
                              config.AI_SLOP_FILTER), (0, 0.2, True, False))
        finally:
            handler._restore_config(prev)


class Regions(Styled):
    LINES = [("Atlantic City saw the worst flooding since Sandy.", 0, 4),
             ("Water poured over the seawall all morning.", 4, 8),
             ("Down in North Carolina, the Outer Banks took a serious punch.", 8, 13),
             ("Highway 12 is closed in both directions.", 13, 17),
             ("Moving north into Virginia, Norfolk has been flooded repeatedly.", 17, 22),
             ("Roads are under water across the city.", 22, 26)]

    def shots_for(self, segs):
        return [{"query": "coastal flooding", "visualType": "footage", "subject": "flooding", "intent": "flooding"}
                for _ in segs]

    def test_lines_follow_the_region_the_narration_is_in(self):
        segs = [seg(*x) for x in self.LINES]
        shots = self.shots_for(segs)
        director.pin_line_places(segs, shots, BRIEF)
        director.region_blocks(segs, shots, BRIEF)
        self.assertEqual([s["region"] for s in shots],
                         ["Atlantic City", "Atlantic City", "North Carolina", "North Carolina", "Virginia", "Virginia"])
        # A line that names no place of its own is searched in its region...
        self.assertTrue(shots[3]["query"].startswith("North Carolina"), shots[3]["query"])
        self.assertEqual(shots[5]["linePlace"], "Virginia")
        # ...a line naming its own town keeps the town, the region as a fallback.
        self.assertEqual(shots[4]["linePlace"], "Norfolk")
        self.assertTrue(any(f.startswith("Virginia") for f in shots[4]["fallbacks"]), shots[4]["fallbacks"])

    def test_off_without_the_switch(self):
        with mock.patch.object(config, "REGION_BLOCKS", False):
            segs = [seg(*x) for x in self.LINES]
            shots = self.shots_for(segs)
            self.assertEqual(director.region_blocks(segs, shots, BRIEF), 0)
            self.assertNotIn("region", shots[0])


class Searches(Styled):
    def test_eyewitness_searches_name_the_place_and_the_event(self):
        shot = {"visualType": "footage", "linePlace": "Long Beach Island", "subjectType": "place"}
        q = director.eyewitness_queries(shot, "Storm surge poured over Long Beach Island.", BRIEF)
        # The line's own event word first ("storm"), then its phenomenon.
        self.assertEqual(q[:2], ["Long Beach Island storm video", "Long Beach Island storm surge footage"])
        q2 = director.eyewitness_queries(shot, "Water poured into the streets of Long Beach Island.", BRIEF)
        self.assertEqual(q2[0], "Long Beach Island flooding video")
        self.assertEqual(director.eyewitness_queries(dict(shot, subjectType="person"), "x", BRIEF), [])

    def test_the_recent_pass_carries_them(self):
        seen = []

        def pool(query, out_dir, seconds, start_at, require_cc, skip, used, intent_text, context, subject,
                 searches, expand=True):
            seen.append(list(searches))
            return None
        token = media._SCENE_INTENT.set({"eyewitness": ["Atlantic City flooding video", "Atlantic City waves footage"]})
        rec = media._RECENCY.set("month")
        win = media._EVENT_WINDOW.set("year")
        try:
            with mock.patch.object(media, "_youtube_pool", side_effect=pool):
                media.youtube_clip("Atlantic City flooding", tempfile.gettempdir(), require_cc=False, intent="x")
        finally:
            media._EVENT_WINDOW.reset(win)
            media._RECENCY.reset(rec)
            media._SCENE_INTENT.reset(token)
        first = seen[0]
        self.assertIn(("Atlantic City flooding video", "month-eyewitness0", "month"), first)
        self.assertTrue(all(r == "month" for _q, _v, r in first))       # recent uploads only, first

    def test_the_pools_search_eyewitness_titles_too(self):
        story = {"is_event": True, "year": YEAR, "word": "flooding", "recency": "month", "event": "", "window": "year"}
        got = pools._searches("Atlantic City", story)
        self.assertIn(("Atlantic City flooding video", "eyewitness-now", "month"), got)

    def test_eyewitness_titles_rank_ahead_and_compilations_behind(self):
        self.assertGreater(media._score_candidate("Storm chaser video: Atlantic City flooding", 300, 1.78, 6),
                           media._score_candidate("Atlantic City flooding", 300, 1.78, 6))
        self.assertLess(media._score_candidate("Top 10 worst floods ever compilation", 300, 1.78, 6),
                        media._score_candidate("Atlantic City flooding", 300, 1.78, 6))


class WrongPlaceEventYear(Styled):
    def test_titles_naming_another_state_storm_weather_or_year(self):
        director.LAST_STORY.update({"places": ["Dallas, Texas", "Fort Worth, Texas"],
                                    "event": f"{YEAR} North Texas flooding",
                                    "summary": "Heavy rain is forecast across Texas."})
        ok = ["Dallas flooding video", "Heavy rain in Fort Worth today", "Kerr County TX flood"]
        bad = {"RUIDOSO, NM flash flood rescue": "another place", "Cameron, Louisiana storm surge": "another place",
               "Tropical Storm Edouard makes landfall": "another", "Fort Worth I-35 pileup ice storm": "another kind",
               f"Texas floods {YEAR - 1} aftermath": "another year", "Flooding in Mexico City": "another place"}
        for t in ok:
            self.assertEqual(media.title_conflict(t, "Dallas could see five inches of rain"), "", t)
        for t, why in bad.items():
            self.assertTrue(media.title_conflict(t, "Dallas could see five inches of rain").startswith(why), t)

    def test_uploads_before_this_storys_year_and_ai_uploads(self):
        old = {"title": "Dallas flooding", "upload_date": f"{YEAR - 2}0512"}
        new = {"title": "Dallas flooding", "upload_date": f"{YEAR}0901"}
        ai = {"title": "Dallas flood", "upload_date": f"{YEAR}0901", "tags": ["ai", "sora"], "description": "#sora"}
        self.assertTrue(media.upload_conflict(old).startswith("uploaded in"))
        self.assertEqual(media.upload_conflict(new), "")
        self.assertTrue(media.upload_conflict(ai))
        token = media._SCENE_INTENT.set({"specificity": "location"})
        try:
            self.assertEqual(media.upload_conflict(old), "")           # a place shot may be older
        finally:
            media._SCENE_INTENT.reset(token)

    def test_a_named_place_pool_takes_the_last_few_years(self):
        # 2026-10-01 Lake Powell: every landmark clip was "uploaded in 2022, before this 2026 story".
        from src import pools
        director.LAST_STORY.update({"event": f"Lake Powell drops to 22% {YEAR}", "title": "Lake Powell DROPS"})
        old = {"title": "Cathedral in the Desert re-emerges", "upload_date": f"{YEAR - 4}0601"}
        older = {"title": "Cathedral in the Desert", "upload_date": f"{YEAR - 9}0601"}
        self.assertTrue(media.upload_conflict(old).startswith("uploaded in"))
        self.assertEqual(media.upload_conflict(old, older_ok_years=4), "")
        self.assertTrue(media.upload_conflict(older, older_ok_years=4).startswith("uploaded in"))
        jobs = [{"subject_type": "place"}, {"subject_type": ""}]
        self.assertTrue(pools.place_subject("Cathedral in the Desert", jobs))
        self.assertTrue(pools.place_subject("Cataract Canyon", [{"subject_type": ""}]))
        self.assertFalse(pools.place_subject("Lake Powell", jobs))          # the event's own subject
        self.assertFalse(pools.place_subject("Bureau of Reclamation", [{"subject_type": ""}]))

    def test_a_real_photo_desk_picture_is_not_called_painted(self):
        # 2026-10-01: CLIP called an AP News Lake Powell photo "painted"; the label names the photo desk.
        from unittest import mock
        from src import slop
        with mock.patch.object(slop, "enabled", return_value=True),                 mock.patch.object(slop, "metadata_reason", return_value=""),                 mock.patch.object(slop, "check_file", return_value="an AI-generated or painted picture"),                 mock.patch.object(media, "_is_still", return_value=True):
            self.assertEqual(media.slop_reason("x.jpg", "Lake Powell shrinks | AP News"), "")
            self.assertEqual(media.slop_reason("x.jpg", "Glen Canyon Dam | Bureau of Reclamation"), "")
            self.assertTrue(media.slop_reason("x.jpg", "lake powell 4k wallpaper | pinterest"))
        with mock.patch.object(slop, "enabled", return_value=True),                 mock.patch.object(slop, "metadata_reason", return_value=""),                 mock.patch.object(slop, "check_file", return_value="an AI-generated or painted picture"),                 mock.patch.object(media, "_is_still", return_value=False):
            self.assertTrue(media.slop_reason("x.mp4", "Lake Powell | AP News"))   # footage keeps the check

    def test_not_an_event_story_no_title_rules(self):
        director.LAST_STORY.clear()
        director.LAST_STORY.update({"kind": "history", "year": 1942, "places": ["Midway"]})
        self.assertEqual(media.title_conflict("Battle of Midway 1942 footage Hawaii"), "")


class ComingAndHook(Styled):
    def test_a_forward_line_without_a_place_shows_what_is_coming(self):
        segs = [seg("Atlantic City is under water.", 0, 3), seg("The seawall failed at dawn.", 3, 6),
                seg("And tonight, the worst is still to come.", 6, 9),
                seg("More rain is on the way tomorrow.", 9, 12),
                seg("Tonight Atlantic City braces again.", 60, 63)]
        shots = [{"query": "q", "visualType": "footage", "subject": "flooding", "intent": "i"} for _ in segs]
        director.coming_shots(segs, shots, BRIEF)
        self.assertTrue(shots[2].get("coming"))
        self.assertIn("storm clouds rolling in", shots[2]["query"])
        self.assertIn("never a TV studio", shots[2]["intent"])
        self.assertFalse(shots[3].get("coming"))              # within COMING_GAP_SECONDS of the last one
        self.assertFalse(shots[4].get("coming"))              # names its own place: its own footage
        self.assertFalse(shots[0].get("coming") or shots[1].get("coming"))

    def test_the_hook_asks_for_the_most_dramatic_footage(self):
        segs = [seg("Atlantic City woke up under water.", 0, 4), seg("Late in the story.", 70, 74)]
        shots = [{"query": "q", "visualType": "footage", "subject": "Atlantic City", "intent": "flooded streets"}
                 for _ in segs]
        director.hook_intensity(segs, shots, BRIEF)
        self.assertIn("most dramatic real footage", shots[0]["intent"])
        self.assertIn("water over roads", shots[0]["intent"])
        self.assertNotIn("most dramatic", shots[1]["intent"])


class Chains(Styled):
    def test_a_beat_that_carries_on_the_sentence_continues_the_clip(self):
        segs = [seg("Water poured over the seawall and into the streets", 0, 6),
                seg("where cars sat stranded in the flood.", 6, 10),
                seg("Crews worked all night.", 10, 13)]
        shots = [{"visualType": "footage", "subject": "Atlantic City", "linePlace": "Atlantic City"} for _ in segs]
        director.chain_shots(segs, shots)
        self.assertEqual([bool(s.get("chain")) for s in shots], [False, True, False])
        director.attach_roles([dict(s, sceneIntent={}) for s in shots], segs, BRIEF)

    def test_fill_chains_plays_the_next_moment_and_counts_as_one_source(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        first = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=abcdefghijk&t=40",
                                 local_path=os.path.join(d, "a.mp4"), duration=6.5, attribution="YouTube: storm",
                                 moment={"start": 40.0}, relevance_score=0.9)
        jobs = [{"index": 0, "seconds": 6.0, "start": 0.0, "scene_intent": {}},
                {"index": 1, "seconds": 4.0, "start": 6.0, "scene_intent": {"role": "chain"}},
                {"index": 2, "seconds": 4.0, "start": 10.0, "scene_intent": {"role": "chain"}}]
        results = [first, None, None]
        calls = []

        def fetch(vid, work, at, need, title=""):
            calls.append((vid, round(at, 1)))
            p = os.path.join(d, f"c{len(calls)}.mp4")
            open(p, "wb").close()
            return p, True, 0
        with mock.patch.object(media, "fetch_clean_clip", side_effect=fetch), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "motion_rejects", return_value=""):
            self.assertEqual(media.fill_chains(jobs, results, d), 2)
        self.assertEqual(calls, [("abcdefghijk", 46.8), ("abcdefghijk", 51.6)])
        self.assertTrue(all(r.moment.get("chain") for r in results[1:]))
        # One source: no variety rule fires for the chain, and it takes no slot.
        with mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 1), mock.patch.object(config, "SAME_VIDEO_GAP_SECONDS", 120):
            self.assertEqual(media.variety_violations(jobs, results), {})
            self.assertEqual(media.placements(results, media.scene_starts(jobs)), {"yt:abcdefghijk": [0.0]})

    def test_chain_lines_are_not_searched_or_pooled(self):
        jobs = [{"index": 0, "query": "a", "seconds": 5, "visual_type": "footage", "subject": "X",
                 "scene_intent": {"role": "chain"}},
                {"index": 1, "query": "b", "seconds": 5, "visual_type": "footage", "subject": "X",
                 "scene_intent": {"role": "coming"}},
                {"index": 2, "query": "c", "seconds": 5, "visual_type": "footage", "subject": "X"},
                {"index": 3, "query": "d", "seconds": 5, "visual_type": "footage", "subject": "X"}]
        self.assertEqual([j["index"] for j in pools.groups(jobs)["x"]], [2, 3])
        searched = []
        with mock.patch.object(media, "source_for_segment",
                               side_effect=lambda q, *a, **k: searched.append(q) or None), \
                mock.patch.object(media, "fresh_moments", return_value=0):
            media.source_many(jobs, tempfile.gettempdir(), workers=2)
        self.assertNotIn("a", searched)
        self.assertIn("b", searched)


class Photos(Styled):
    def test_planned_photo_beats_are_capped(self):
        segs = [seg(f"Line {i} about the flood.", i * 6.0, i * 6.0 + 6.0) for i in range(100)]      # 10 min
        shots = [{"visualType": "image" if i % 3 == 0 else "footage",
                  "query": f"q{i} photo" if i % 3 == 0 else f"q{i}", "subject": "flood"} for i in range(100)]
        director.limit_stills(segs, shots)
        kept = sum(1 for s in shots if s["visualType"] == "image")
        self.assertEqual(kept, int(round(config.PHOTO_MAX_PER_10MIN)))
        self.assertTrue(all("photo" not in s["query"] for s in shots if s["visualType"] == "footage"))

    def test_a_footage_beat_stops_falling_back_to_photos_past_the_cap(self):
        seen = []

        def source_one(ctx):
            seen.append(ctx.enabled_names)
            return None
        media._PHOTOS.update(cap=1, used=1)
        self.addCleanup(lambda: media._PHOTOS.update(cap=None, used=0))
        with mock.patch.object(media.providers, "source_one", side_effect=source_one):
            media.source_for_segment("flood", 5, tempfile.gettempdir(), visual_type="footage")
        self.assertTrue(seen and seen[0] is not None)
        self.assertNotIn("web_images", seen[0])
        self.assertIn("youtube", seen[0])

    def test_photos_past_the_videos_cap_look_for_footage(self):
        jobs = [{"index": i, "seconds": 6.0, "start": i * 6.0} for i in range(20)]      # 2 minutes
        results = [media.MediaAsset(kind="image", source="web_image", url=f"https://x/{i}.jpg") for i in range(20)]
        got = media.variety_violations(jobs, results)
        cap = media.photo_cap(120.0)
        self.assertEqual(sum(1 for r, k in got.values() if k == "upgrade"), 20 - cap)


class Motion(Styled):
    def test_moving_footage_wins_and_a_frozen_shot_loses(self):
        a = media.MediaAsset(kind="video", source="youtube", url="u", local_path="a.mp4", final_score=0.7)
        b = media.MediaAsset(kind="video", source="youtube", url="u", local_path="b.mp4", final_score=0.7)
        media.apply_motion(a, {"motion": 0.9, "raw": 12, "static": False, "slideshow": False})
        media.apply_motion(b, {"motion": 0.0, "raw": 0.2, "static": True, "slideshow": False})
        self.assertGreater(a.final_score, 0.7)
        self.assertLess(b.final_score, 0.7)
        self.assertIn("motion", a.score_parts)

    def test_a_slideshow_is_turned_down_with_the_preference_on(self):
        with mock.patch.object(media, "motion_of", return_value={"motion": 0.1, "raw": 0.3, "static": False,
                                                                 "slideshow": True}):
            self.assertEqual(media.motion_rejects("x.mp4"), "a slideshow of stills")
        with mock.patch.object(config, "MOTION_PREFERENCE", 0.0):
            self.assertEqual(media.motion_rejects("x.mp4"), "")


class NewsCompilationToo(unittest.TestCase):
    def test_the_news_style_gets_the_same_work_where_it_applies(self):
        cfg = styles.STYLES["news_compilation"]["config"]
        self.assertEqual(cfg["MAX_SCENE_SECONDS"], 7.0)
        self.assertTrue(cfg["EYEWITNESS_SEARCHES"] and cfg["REGION_BLOCKS"] and cfg["CHAIN_SHOTS"])
        self.assertEqual(cfg["IMAGE_MAX_PER_VIDEO"], 0)


if __name__ == "__main__":
    unittest.main()
