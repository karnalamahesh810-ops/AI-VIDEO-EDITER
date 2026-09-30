"""
The worker searches for the news reports and interviews GoMotion used.

Pools: an event story's subject pool adds news searches, the NEWS_CHANNELS
lookup, lets short news reports in, ranks a report of the exact event with
a drone video, tells rate_tiles the shots come from news reports, and draws
a few moments from several reports. Director: person beats get their
interview first, place beats the news report and drone of this year.
Network and models are mocked throughout.
"""
import datetime
import unittest
from unittest import mock

from src import config, director, media, moments, pools, vision
from src.transcribe import Segment

BRIEF = {"kind": "news", "event": "2026 Colorado River water cuts", "year": 2026, "recent": True,
         "places": ["Lake Powell", "Arizona"], "people": ["Brad Udall", "Katie Hobbs"]}
STORY = {"kind": "news", "is_event": True, "event": "2026 Colorado River water cuts",
         "year": 2026, "window": "year"}
TODAY = datetime.date(2026, 9, 29)

ROWS = [
    {"id": "DRONE000000", "title": "Lake Powell aerial drone footage 4k", "duration": 300, "aspect": 1.78,
     "channel": "Scenic Flights"},
    {"id": "ABC70000000", "title": "Lake Powell drops below 3,500 feet | ABC7", "duration": 95, "aspect": 0,
     "channel": "ABC7"},
    {"id": "KUTV0000000", "title": "Basin states at odds over water sharing", "duration": 140, "aspect": 0,
     "channel": "KUTV"},
    {"id": "OLD00000000", "title": "Lake Powell 2021 drone", "duration": 300, "aspect": 0, "channel": ""},
    {"id": "POD00000000", "title": "Colorado River podcast episode 12", "duration": 3000, "aspect": 0,
     "channel": ""},
    {"id": "CAT00000000", "title": "Cute cats compilation", "duration": 300, "aspect": 0, "channel": ""},
]


def job(i, subject, seconds=7.0, **kw):
    return {"index": i, "query": subject, "seconds": seconds, "visual_type": "footage",
            "subject": subject, "subject_type": kw.get("subject_type", "place"),
            "context": f"line {i} about {subject}", "intent": subject,
            "event_window": kw.get("event_window", ""), "scene_intent": kw.get("scene_intent")}


def rows(*a, **k):
    return [dict(r) for r in ROWS]


class PoolSearches(unittest.TestCase):
    def test_event_story_adds_news_searches_after_the_generic_ones(self):
        got = pools._searches("Lake Powell", STORY)
        self.assertEqual(got[:2], [("Lake Powell aerial drone footage 4k", "drone", ""),
                                   ("Lake Powell documentary footage", "doc", "")])
        self.assertEqual(got[2:], [("Lake Powell news 2026", "news", "year"),
                                   ("Lake Powell Colorado River water cuts news report", "news-event", "year")])
        self.assertLessEqual(len(got), pools.POOL_SEARCHES_MAX)
        self.assertEqual(len({q.lower() for q, _, _ in got}), len(got))
        # Room for one more when the channel lookup is not running.
        self.assertEqual(pools._searches("Lake Powell", STORY, limit=3)[2],
                         ("Lake Powell news 2026", "news", "year"))
        # An older event puts the year in the words, not YouTube's this-year filter.
        old = pools._searches("Lake Powell", dict(STORY, year=2021, window="event"))
        self.assertEqual(old[2], ("Lake Powell news 2021", "news", ""))

    def test_non_event_and_explainer_without_event_keep_generic_searches(self):
        generic = [("Lake Powell aerial drone footage 4k", "drone", ""),
                   ("Lake Powell documentary footage", "doc", "")]
        self.assertEqual(pools._searches("Lake Powell"), generic)
        self.assertEqual(pools._searches("Lake Powell", {"is_event": False}), generic)
        with mock.patch.dict(director.LAST_STORY, {}, clear=True), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            media.set_story_kind("explainer")
            self.assertFalse(pools.subject_story([job(0, "Lake Powell")])["is_event"])
            si = {"event_type": "drought / reservoir decline", "time_context": "current"}
            self.assertTrue(pools.subject_story([job(0, "Lake Powell", scene_intent=si)])["is_event"])
            media.set_story_kind("history")
            self.assertFalse(pools.subject_story([job(0, "Lake Powell")])["is_event"])
            media.set_story_kind("")

    def test_subject_story_reads_the_jobs_not_only_the_parent_brief(self):
        si = {"event_type": "drought / reservoir decline", "time_context": "current"}
        jobs = [job(i, "Lake Powell", event_window="year", scene_intent=si) for i in range(3)]
        with mock.patch.dict(director.LAST_STORY, {}, clear=True), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            media.set_story_kind("")
            got = pools.subject_story(jobs)
        self.assertEqual(got["window"], "year")
        self.assertEqual(got["year"], datetime.date.today().year)
        self.assertEqual(got["event"], "drought reservoir decline")
        self.assertTrue(got["is_event"])

    def test_news_searches_only_with_news_footage_on(self):
        jobs = [job(i, "Lake Powell", event_window="year") for i in range(3)]
        with mock.patch.dict(director.LAST_STORY, BRIEF, clear=True), \
                mock.patch.object(config, "NEWS_FOOTAGE", False):
            media.set_story_kind("news")
            story = pools.subject_story(jobs)
            media.set_story_kind("")
        self.assertFalse(story["is_event"])
        self.assertEqual(len(pools._searches("Lake Powell", story)), 2)

    def test_recent_story_searches_this_years_uploads(self):
        t = pools._target("Lake Powell news 2026", False, "year")
        self.assertIn("results?search_query=", t)
        self.assertIn("sp=EgIIBQ%3D%3D", t)
        self.assertEqual(pools._target("Lake Powell news 2026", False, ""), "ytsearch15:Lake Powell news 2026")
        cc = pools._target("Lake Powell news 2026", True, "year")
        self.assertIn("sp=EgIwAQ%3D%3D", cc)
        self.assertNotIn("EgIIBQ", cc)


class PoolRanking(unittest.TestCase):
    def _cands(self, story, channels=None, cc=False):
        with mock.patch.object(media, "_yt_candidates_cached", rows), \
                mock.patch.object(media, "_channel_candidates", channels or (lambda *a, **k: [])), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            return pools.candidates("Lake Powell", cc, set(), story=story)

    def test_news_report_of_the_event_ranks_with_a_drone_video(self):
        got = self._cands(STORY)
        by_id = {c["id"]: c for c in got}
        self.assertIn("ABC70000000", by_id)
        self.assertIn("KUTV0000000", by_id)          # the event words and the call sign, no "Lake Powell"
        self.assertGreaterEqual(by_id["ABC70000000"]["_rank"], by_id["DRONE000000"]["_rank"] - 0.5)
        self.assertLess(by_id["OLD00000000"]["_rank"], by_id["ABC70000000"]["_rank"])
        self.assertLess(by_id["OLD00000000"]["_rank"], by_id["KUTV0000000"]["_rank"])
        self.assertNotIn("POD00000000", by_id)
        self.assertNotIn("CAT00000000", by_id)
        self.assertTrue(by_id["ABC70000000"]["_news"])
        self.assertFalse(by_id["DRONE000000"]["_news"])
        plain = self._cands(None)
        self.assertEqual(plain[0]["id"], "DRONE000000")
        self.assertNotIn("KUTV0000000", {c["id"] for c in plain})

    def test_a_drone_video_of_the_subject_this_year_still_ranks_first(self):
        now = {"id": "NOW00000000", "title": "Lake Powell drone 2026", "duration": 300, "aspect": 1.78, "channel": ""}
        with mock.patch.object(media, "_yt_candidates_cached", lambda *a, **k: [dict(now)] + rows()), \
                mock.patch.object(media, "_channel_candidates", lambda *a, **k: []), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            got = pools.candidates("Lake Powell", False, set(), story=STORY)
        self.assertEqual(got[0]["id"], "NOW00000000")

    def test_short_news_reports_are_allowed_only_for_event_stories(self):
        short = {"id": "8NN00000000", "title": "Nevada sues feds over Colorado River plan | 8 News Now",
                 "duration": 45, "aspect": 0, "channel": "8 News Now"}
        plain = {"id": "SHRT0000000", "title": "Lake Powell in 45 seconds", "duration": 45, "aspect": 0, "channel": ""}
        with mock.patch.object(media, "_yt_candidates_cached", lambda *a, **k: [dict(short), dict(plain)]), \
                mock.patch.object(media, "_channel_candidates", lambda *a, **k: []), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            event = {c["id"] for c in pools.candidates("Lake Powell", False, set(), story=STORY)}
            none = {c["id"] for c in pools.candidates("Lake Powell", False, set())}
        self.assertIn("8NN00000000", event)
        self.assertNotIn("8NN00000000", none)
        self.assertNotIn("SHRT0000000", event)
        self.assertNotIn("SHRT0000000", none)

    def test_news_channels_are_searched_for_event_subjects(self):
        calls = []
        twin = {"id": "TWIN0000000", "title": "Lake Powell drops below 3,500 feet | ABC7", "duration": 95,
                "aspect": 0, "channel": "ABC7"}

        def channels(query, chans, subject=""):
            calls.append((query, chans, subject))
            return [dict(twin)]
        with mock.patch.object(config, "NEWS_CHANNELS", ["@Reuters", "@8NewsNow"]):
            got = self._cands(STORY, channels)
            self.assertEqual(calls, [("Lake Powell", ["@Reuters", "@8NewsNow"], "Lake Powell")])
            by_id = {c["id"]: c for c in got}
            self.assertEqual(by_id["TWIN0000000"]["_via"], "channel")
            self.assertEqual(by_id["ABC70000000"]["_via"], "search")
            self.assertGreater(by_id["TWIN0000000"]["_rank"], by_id["ABC70000000"]["_rank"])
            calls.clear()
            self._cands(STORY, channels, cc=True)
            self.assertEqual(calls, [])
            self._cands(None, channels)
            self.assertEqual(calls, [])

    def test_never_more_than_four_lookups_per_subject(self):
        targets = []

        def flat(target, cc, subject="", variant=""):
            targets.append(target)
            return []
        with mock.patch.object(media, "_yt_candidates_cached", flat), \
                mock.patch.object(media, "_channel_candidates", lambda *a, **k: []), \
                mock.patch.object(config, "NEWS_FOOTAGE", True), \
                mock.patch.object(config, "NEWS_CHANNELS", ["@Reuters"]):
            pools.candidates("Lake Powell", False, set(), story=STORY)
            self.assertEqual(len(targets), pools.POOL_SEARCHES_MAX - 1)      # + the channel lookup
            targets.clear()
            with mock.patch.object(config, "NEWS_CHANNELS", []):
                pools.candidates("Lake Powell", False, set(), story=STORY)
            self.assertEqual(len(targets), pools.POOL_SEARCHES_MAX)
            targets.clear()
            pools.candidates("Lake Powell", False, set())
            self.assertEqual(len(targets), 2)
        self.assertTrue(targets[0].endswith("Lake Powell aerial drone footage 4k"))

    def test_searches_are_cached_per_subject_and_variant(self):
        seen = []
        with mock.patch.object(media, "_yt_candidates_cached",
                               lambda t, cc, subject="", variant="": seen.append((subject, variant)) or []), \
                mock.patch.object(media, "_channel_candidates", lambda *a, **k: []), \
                mock.patch.object(config, "NEWS_FOOTAGE", True), \
                mock.patch.object(config, "NEWS_CHANNELS", []):
            pools.candidates("Lake Powell", False, set(), story=STORY)
        self.assertTrue(all(s == "lake powell" for s, _ in seen))
        self.assertEqual(len({v for _, v in seen}), len(seen))
        self.assertIn(("lake powell", "pool:news:year"), seen)


class PoolRating(unittest.TestCase):
    def test_rate_video_passes_a_news_intent_and_clamps_the_last_moment(self):
        kwargs = {}

        def rate(sheet, n, subject, context, **kw):
            kwargs.update(kw)
            return [{"tile": k + 1, "score": 0.9, "description": f"tile {k + 1}"} for k in range(20)]
        with mock.patch.object(media, "_yt_info", return_value=({"duration": 100.0}, None)), \
                mock.patch.object(moments, "contact_sheet", return_value=("sheet", [5.0 * k for k in range(20)])), \
                mock.patch.object(vision, "rate_tiles", rate):
            got = pools.rate_video({"id": "ABC70000000"}, "Lake Powell", "ctx", 8.0,
                                   intent=pools.pool_intent("Lake Powell", STORY))
        self.assertIn("NEWS REPORTS", kwargs["intent"])
        self.assertIn("interviews", kwargs["intent"])
        self.assertEqual(len(got), 20)
        self.assertTrue(all(m["start"] + 8.0 <= 100.0 for m in got))
        self.assertEqual(got[0]["start"], 0.0)

    def test_pool_intent_is_empty_outside_event_stories(self):
        self.assertEqual(pools.pool_intent("Lake Powell", {"is_event": False}), "")
        self.assertEqual(pools.pool_intent("Lake Powell", None), "")
        self.assertIn("Lake Powell", pools.pool_intent("Lake Powell", STORY))


class PoolPlanning(unittest.TestCase):
    def _plan(self, jobs, brief, kind, cands, rated):
        calls = []

        def fake_rate(cand, subject, context, seconds, **kw):
            calls.append(cand["id"])
            return rated(cand)
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: [dict(c) for c in cands]), \
                mock.patch.object(pools, "rate_video", fake_rate), \
                mock.patch.dict(director.LAST_STORY, brief, clear=True), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            media.set_story_kind(kind)
            try:
                plan, spare = pools.plan_subject("Lake Powell", jobs, False, set(), claim=lambda k: True)
            finally:
                media.set_story_kind("")
        return plan, spare, calls

    # Updated for the owner's review (2026-09-30): these two tests encoded the
    # old reuse - NEWS_MAX_MOMENTS_PER_VIDEO (4) lines per news report, and a
    # nature story drawing all 8 lines from one documentary. Every story now
    # takes at most config.MAX_MOMENTS_PER_VIDEO (2) lines from one video; the
    # lines no rated video may take go to per-scene sourcing.
    def test_an_event_subject_draws_a_few_moments_from_several_reports(self):
        cands = [{"id": "AAAAAAAAAAA", "title": "A"}, {"id": "BBBBBBBBBBB", "title": "B"},
                 {"id": "CCCCCCCCCCC", "title": "C"}]
        ten = lambda c: [{"start": 10.0 * k, "score": 0.9, "description": f"{c['id'][0]}{k}"} for k in range(10)]
        jobs = [job(i, "Lake Powell", event_window="year") for i in range(8)]
        with mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2):
            plan, spare, calls = self._plan(jobs, BRIEF, "news", cands, ten)
            self.assertEqual(len(plan), 6)
            used = [c["id"] for _, c, _ in plan]
            for vid in ("AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"):
                self.assertEqual(used.count(vid), config.MAX_MOMENTS_PER_VIDEO)
            self.assertEqual(calls, ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"])
            self.assertEqual(spare, [])
            # A nature story is held to the same cap now.
            jobs = [job(i, "Lake Powell") for i in range(8)]
            plan, spare, calls = self._plan(jobs, {}, "nature", cands, ten)
            used = [c["id"] for _, c, _ in plan]
            self.assertEqual(max(used.count(v) for v in set(used)), 2)
            self.assertEqual(calls, ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"])

    def test_cap_keeps_the_best_scored_moments_in_time_order(self):
        scores = [0.7, 0.95, 0.72, 0.9, 0.88, 0.71]
        six = lambda c: [{"start": 10.0 * k, "score": s, "description": ""} for k, s in enumerate(scores)]
        jobs = [job(i, "Lake Powell", event_window="year") for i in range(4)]
        with mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2):
            plan, _, _ = self._plan(jobs, BRIEF, "news", [{"id": "AAAAAAAAAAA", "title": "A"}], six)
        self.assertEqual([(m["start"], m["score"]) for _, _, m in plan],
                         [(10.0, 0.95), (30.0, 0.9)])

    def test_people_still_go_to_per_scene_sourcing(self):
        g = pools.groups([job(0, "Brad Udall", subject_type="person"),
                          job(1, "Brad Udall", subject_type="person"), job(2, "Lake Powell")])
        self.assertEqual(sorted(g), ["lake powell"])
        self.assertIn("per-scene path", pools.groups.__doc__)

    def test_stats_count_news_reports(self):
        jobs = [job(i, "Lake Powell", event_window="year") for i in range(2)]
        cand = {"id": "ABC70000000", "title": "Lake Powell drops | ABC7", "_news": True}

        def fake_fetch(job_, cand, m, work, require_cc, subject, library=None):
            return media.MediaAsset(kind="video", source="youtube",
                                    url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(m['start'])}",
                                    local_path="/w/x.mp4", moment_key=f"yt:{cand['id']}@{int(m['start'] // 10)}")
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: [dict(cand)]), \
                mock.patch.object(pools, "rate_video", lambda c, s, ctx, sec, **kw: [
                    {"start": 10.0, "score": 0.9, "description": ""}, {"start": 30.0, "score": 0.9, "description": ""}]), \
                mock.patch.object(pools, "_fetch", fake_fetch), \
                mock.patch.dict(director.LAST_STORY, BRIEF, clear=True), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            media.set_story_kind("news")
            try:
                got = pools.source_by_subject(jobs, "/w")
            finally:
                media.set_story_kind("")
        self.assertEqual(sorted(got), [0, 1])
        self.assertEqual(media.LAST_STATS["pools"]["news_videos"], 1)


class DirectorNewsQueries(unittest.TestCase):
    def setUp(self):
        self._flag = mock.patch.object(config, "NEWS_FOOTAGE", True)
        self._flag.start()

    def tearDown(self):
        self._flag.stop()

    def test_person_beats_get_interview_then_news_then_press_conference(self):
        want = ["Brad Udall interview Colorado River water cuts",
                "Brad Udall Colorado River water cuts news 2026",
                "Brad Udall press conference 2026"]
        shot = {"subject": "Brad Udall", "subjectType": "person", "visualType": "footage"}
        self.assertEqual(director.news_queries(shot, "Brad Udall warned the cuts are coming.", BRIEF), want)
        shot = {"subject": "Brad Udall", "entity": "public-figure", "visualType": "footage"}
        self.assertEqual(director.news_queries(shot, "Brad Udall warned the cuts are coming.", BRIEF), want)

    def test_place_beats_get_news_report_and_drone_of_this_year(self):
        shot = {"subject": "Lake Powell", "subjectType": "place", "entity": "natural-feature",
                "visualType": "footage"}
        self.assertEqual(director.news_queries(shot, "The lake is at 3,491 feet.", BRIEF),
                         ["Lake Powell news 2026", "Lake Powell Colorado River water cuts news report",
                          "Lake Powell drone 2026"])
        shot = {"subject": "Colorado River water cuts", "subjectType": "event", "visualType": "footage"}
        self.assertEqual(director.news_queries(shot, "The cuts begin in January.", BRIEF),
                         ["Colorado River water cuts news 2026"])

    def test_a_line_about_another_year_searches_that_year(self):
        shot = {"subject": "Lake Powell", "subjectType": "place", "visualType": "footage"}
        got = director.news_queries(shot, "In 2021 the first shortage was declared.", BRIEF)
        self.assertIn("Lake Powell news 2021", got)
        self.assertIn("Lake Powell drone 2021", got)
        self.assertFalse(any("2026" in q for q in got))

    def test_left_alone(self):
        shot = {"subject": "Lake Powell", "subjectType": "place", "visualType": "footage"}
        text = "Lake Powell dropped."
        # A story long past gets no news searches (a story about now does,
        # whatever its kind: see test_glen_fixes).
        self.assertEqual(director.news_queries(shot, text, dict(BRIEF, kind="history", year=1922)), [])
        self.assertEqual(director.news_queries(shot, text, dict(BRIEF, kind="explainer", event="", year=1963)), [])
        self.assertEqual(director.news_queries(dict(shot, anchor=False), text, BRIEF), [])
        self.assertEqual(director.news_queries(dict(shot, visualType="image"), text, BRIEF), [])
        self.assertEqual(director.news_queries(dict(shot, subject=""), text, BRIEF), [])
        self.assertEqual(director.news_queries(shot, text, dict(BRIEF, kind="explainer")),
                         director.news_queries(shot, text, BRIEF))
        with mock.patch.object(config, "NEWS_FOOTAGE", False):
            self.assertEqual(director.news_queries(shot, text, BRIEF), [])


class DirectorPlan(unittest.TestCase):
    SEGS = [Segment("Lake Powell has dropped to 3,491 feet.", 0, 6),
            Segment("Brad Udall says the cuts are only the start.", 6, 12)]

    def _plan(self, brief=BRIEF):
        with mock.patch.object(director, "is_configured", return_value=False), \
                mock.patch.object(director.geocode, "resolve_all", return_value=[]), \
                mock.patch.object(director, "_today", return_value=TODAY), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            shots, kind, _ = director.plan(self.SEGS, title="Lake Powell", allow_maps=False, brief=brief)
        return shots, kind

    def test_plan_puts_news_queries_behind_the_event_and_ahead_of_expansions(self):
        shots, kind = self._plan()
        self.assertEqual(kind, "rules")
        self.assertEqual(shots[0]["query"], "Lake Powell news 2026")
        self.assertEqual(shots[0]["fallbacks"][0], BRIEF["event"])
        self.assertEqual(shots[0]["fallbacks"][1], "Lake Powell Colorado River water cuts news report")
        self.assertEqual(shots[0]["newsQueries"][0], "Lake Powell news 2026")
        self.assertNotIn("Lake Powell news 2026", shots[0]["fallbacks"])      # the query itself, not repeated
        self.assertEqual(shots[0]["eventWindow"], "year")
        self.assertEqual(shots[1]["query"], "Brad Udall interview Colorado River water cuts")
        self.assertIn("Brad Udall press conference 2026", shots[1]["fallbacks"])
        self.assertEqual(len(shots[1]["fallbacks"]), len(set(shots[1]["fallbacks"])))

    def test_named_person_footage_beats_search_the_interview_first(self):
        shots = [{"query": "Katie Hobbs speech footage", "subject": "Katie Hobbs", "subjectType": "person",
                  "entity": "public-figure", "visualType": "footage", "fallbacks": ["Katie Hobbs"]},
                 {"query": "Lake Powell exposed shoreline aerial", "subject": "Lake Powell",
                  "subjectType": "place", "visualType": "footage", "fallbacks": []},
                 {"query": "a rancher photo", "subject": "a rancher", "subjectType": "person",
                  "visualType": "footage", "fallbacks": []}]
        segs = [Segment("x", i, i + 1) for i in range(3)]
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            self.assertEqual(director.prefer_interviews(shots, segs, BRIEF), 1)
        self.assertEqual(shots[0]["query"], "Katie Hobbs interview Colorado River water cuts")
        self.assertEqual(shots[0]["fallbacks"], ["Katie Hobbs speech footage", "Katie Hobbs"])
        self.assertEqual(shots[1]["query"], "Lake Powell exposed shoreline aerial")
        self.assertEqual(shots[2]["query"], "a rancher photo")
        again = [dict(s, fallbacks=list(s["fallbacks"])) for s in shots]
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            self.assertEqual(director.prefer_interviews(again, segs, BRIEF), 0)     # idempotent
            self.assertEqual(director.prefer_interviews(
                [{"query": "Katie Hobbs speech footage", "subject": "Katie Hobbs", "subjectType": "person",
                  "visualType": "footage", "fallbacks": []}], segs[:1], dict(BRIEF, kind="history", year=1922)), 0)

    def test_rule_queries_carry_interview_or_news_for_event_stories(self):
        def rule_shots():
            return [director._rule_shot(seg, i, "Lake Powell") for i, seg in enumerate(self.SEGS)]
        with mock.patch.object(config, "NEWS_FOOTAGE", True):
            shots = rule_shots()
            director.story_rule_queries(self.SEGS, shots, BRIEF, "Lake Powell")
            self.assertIn("interview", shots[1]["query"])
            self.assertIn("Brad Udall", shots[1]["query"])
            self.assertIn("news", shots[0]["query"])
            self.assertTrue(shots[0]["query"].startswith("Lake Powell"))
            history = rule_shots()
            director.story_rule_queries(self.SEGS, history, dict(BRIEF, kind="history"), "Lake Powell")
            self.assertNotIn("interview", history[1]["query"])
            self.assertNotIn("news", history[0]["query"])


if __name__ == "__main__":
    unittest.main()
