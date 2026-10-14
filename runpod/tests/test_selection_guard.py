"""
The selection guard (feature/selection-guard, 2026-10-09).

The Yellowstone build of 2026-10-07 (2a2200b3) ran the OpenRouter account dry and kept going for 40 minutes:
lines planned by the rules from the video's TITLE ("Yellowstone Just EXPLODED Again..." as every line's subject),
clips placed with no verdict ("JJ is LEFT FOREVER in Minecraft! (Maizen)" on a line about ground uplift). The next
build (fd58f969, 2026-10-08) took one 402 22 s into its footage search: 176 of its 181 clips and all 86 pictures
reached the timeline unjudged - a Roblox showcase, the Yellowstone TV show's theme, a FIFA highlights reel - and
creator subtitles passed on news lines, and ten YouTube thumbnails were placed as pictures.

Each rule here answers one of those, offline (network and models mocked; the titles are the real ones):

  1. AI outage: the failure kinds (aiguard.classify, on the providers' real messages), the preflight and its
     estimate, the planner's stop on a 402 (never a rule-planned line), the job's stop mid-search with the work
     kept on R2, and the Retry that takes it back instead of paying again.
  2. Nothing unjudged reaches the timeline while vision is meant to judge (media._judge_gate).
  3. Off-topic candidates turned down by title and channel before any download (src/offtopic.py), with each
     class's story exception - and real Yellowstone footage kept.
  4. Video thumbnails turned down by their address before any download (src/stockblock.py).
  5. Subtitles never welcome, a broadcaster's chyrons and logos kept on news lines (vision.text_check_decision,
     media.second_look).
  6. Vision answers read tolerantly (no second, paid call for a fixable answer).
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import handler
from src import aiguard, config, credit, director, media, offtopic, pools, r2, resume, stockblock, topics, vision
from src.media import MediaAsset
from src.transcribe import Segment, Word

OPENROUTER = "https://openrouter.ai/api/v1"
YS_TITLE = "Yellowstone Just EXPLODED Again - Boiling Water Shoots 100 FEET Into the Air"
YS_STORY = (YS_TITLE + " | disaster | Yellowstone National Park hydrothermal explosion Biscuit Basin geysers "
            "supervolcano")
UPLIFT = "The ground rose about three inches a year at its peak, then sank again after 2010."


def or_reply(status=200, body=None):
    r = mock.Mock(status_code=status)
    r.json.return_value = body
    r.text = json.dumps(body)
    return r


def or_error(status, message):
    return or_reply(status, {"error": {"code": status, "message": message}})


# --------------------------------------------------------------------------- #
# 1a. The failure kinds, on the messages the Yellowstone and California builds logged
# --------------------------------------------------------------------------- #

class FailureKinds(unittest.TestCase):
    def test_every_way_the_account_says_it_cannot_pay_is_a_credit_stop(self):
        for status, msg in [
                (402, "This request requires more credits, or fewer max_tokens. You requested up to 16000 tokens, "
                      "but can only afford 5133."),
                (402, "This request would exceed your available credits given your current in-flight requests"),
                (402, "Credits insufficient : top up"),                       # Kie, carried in a 200's body
                (403, "Key limit exceeded (total limit). Manage it using https://openrouter.ai/settings/keys"),
                (400, "Prompt tokens limit exceeded: 2847 > 1650. To increase, visit "
                      "https://openrouter.ai/settings/credits and add more credits")]:
            self.assertEqual(aiguard.classify(status, msg), aiguard.CREDIT, msg)

    def test_a_rate_limit_is_waited_out_never_a_stop(self):
        for status, msg in [(429, "Your call frequency is too high. Please try again later."),
                            (429, "Rate limit exceeded: free-models-per-min."),
                            (200, "Too many requests")]:
            self.assertEqual(aiguard.classify(status, msg), aiguard.RATE, msg)
        self.assertFalse(aiguard.is_fatal(aiguard.RATE))

    def test_a_server_error_is_asked_again_and_anything_else_goes_to_the_next_model(self):
        self.assertEqual(aiguard.classify(503, "upstream overloaded"), aiguard.RETRY)
        self.assertEqual(aiguard.classify(408, "timeout"), aiguard.RETRY)
        self.assertEqual(aiguard.classify(401, "No auth credentials found"), aiguard.AUTH)
        self.assertEqual(aiguard.classify(400, "image could not be decoded"), aiguard.OTHER)


# --------------------------------------------------------------------------- #
# 1b. The preflight: the balance the key may spend against what the video needs
# --------------------------------------------------------------------------- #

class Preflight(unittest.TestCase):
    def setUp(self):
        credit.reset()

    def tearDown(self):
        credit.reset()

    def test_the_estimate_follows_the_video_length(self):
        # 20 minutes: 260 lines; planning $0.90 and checks $1.30, plus a fifth - about $2.5 (fd58f969 spent $0.87
        # planning a 20.8-minute video; Lake Mead's checks ran $0.0066 a line before the 2026-10-07 cuts).
        est = aiguard.estimate_usd(20.0)
        self.assertGreater(est, 2.0)
        self.assertLess(est, 3.5)
        self.assertEqual(aiguard.need_for(1.0, floor=2.0), 2.0)        # a short video still needs the floor
        self.assertEqual(aiguard.need_for(20.0, floor=2.0), est)
        self.assertAlmostEqual(aiguard.minutes_from_script("word " * 300), 2.0)

    def test_the_key_limit_counts_when_it_is_lower_than_the_account(self):
        # Read on 2026-10-09: the account had $19.02 and the worker's key $9.02 left under its own limit.
        def get(url, **kw):
            if url.endswith("/credits"):
                return or_reply(200, {"data": {"total_credits": 120.0, "total_usage": 100.98}})
            return or_reply(200, {"data": {"limit": 100.0, "limit_remaining": 9.02, "usage": 90.98}})
        with mock.patch.multiple(config, VISION_API_BASE=OPENROUTER, VISION_API_KEY="k"), \
                mock.patch.object(credit.requests, "get", side_effect=get):
            self.assertAlmostEqual(credit.openrouter_left(max_age=0), 9.02)
            self.assertAlmostEqual(credit.last_detail()["account"], 19.02)

    def test_too_little_stops_before_anything_is_spent_with_the_plain_message(self):
        with mock.patch.object(credit, "uses_openrouter", return_value=True), \
                mock.patch.object(credit, "openrouter_left", return_value=1.37), \
                mock.patch.object(config, "REQUIRE_AI_CREDIT", True):
            with self.assertRaises(aiguard.AIStopped) as e:
                aiguard.preflight(2.84, "this video")
        self.assertEqual(str(e.exception),
                         "Your AI balance is too low for this video: about $1.37 left, it needs about $2.84. "
                         "Top up OpenRouter, then press Retry. Nothing was spent.")

    def test_a_negative_balance_stops_before_the_plan(self):
        # Today's account (2026-10-14): below zero. The job never starts a paid call.
        with mock.patch.object(credit, "uses_openrouter", return_value=True), \
                mock.patch.object(credit, "openrouter_left", return_value=-0.53), \
                mock.patch.object(config, "REQUIRE_AI_CREDIT", True):
            with self.assertRaises(aiguard.AIStopped) as e:
                aiguard.preflight(aiguard.need_for(12.0), "this video")
        self.assertTrue(str(e.exception).startswith("Your AI balance is too low for this video: nothing left "
                                                    "($-0.53), it needs about $"), str(e.exception))

    def test_an_unknown_balance_never_blocks_a_job(self):
        with mock.patch.object(credit, "uses_openrouter", return_value=True), \
                mock.patch.object(credit, "openrouter_left", return_value=None):
            self.assertIsNone(aiguard.preflight(2.84))
        with mock.patch.object(config, "REQUIRE_AI_CREDIT", False), \
                mock.patch.object(credit, "openrouter_left", side_effect=AssertionError("not read")):
            self.assertIsNone(aiguard.preflight(2.84))

    def test_the_message_never_trips_the_apps_generic_failure_rules(self):
        # C:\\ThumGenius-app\\src\\lib\\plainFailure.ts swaps a message naming audio, storage, media, "not found"...
        # for its own generic line; these must reach the user as they are.
        aiguard.reset()
        aiguard.trip(aiguard.CREDIT, "openai/gpt-5.2", "This request requires more credits, or fewer max_tokens")
        aiguard.mark_kept(True)
        texts = [aiguard.message(), aiguard.low_balance_message(1.0, 2.0)]
        aiguard.reset()
        for t in texts:
            for word in ("audio", "narration", "transcri", "align", "storage", "upload", "404", "not found",
                         "media", "cancel", "timed out", "time limit", "took too long"):
                self.assertNotIn(word, t.lower(), t)
        self.assertIn("a Retry does not pay for it again", texts[0])


# --------------------------------------------------------------------------- #
# 1c. The planner: a 402 stops the plan - never a line planned by the rules from the title
# --------------------------------------------------------------------------- #

class _AI(unittest.TestCase):
    def setUp(self):
        vision.reset()
        self.p = mock.patch.multiple(config, DIRECTOR_API_BASE=OPENROUTER, DIRECTOR_API_KEY="k",
                                     DIRECTOR_MODEL="openai/gpt-5.2", DIRECTOR_FALLBACK_MODELS=["openai/gpt-5.1"],
                                     DIRECTOR_ROUTINE_MODEL="", DIRECTOR_HEDGE_SECONDS=0, DIRECTOR_RETRIES=1,
                                     DIRECTOR_RETRY_WAIT=0.0, VISION_API_BASE=OPENROUTER, VISION_API_KEY="k",
                                     VISION_ENABLED=True, AI_FALLBACK_API_BASE="", AI_FALLBACK_API_KEY="",
                                     AI_FALLBACK_MODEL="", AI_FALLBACK_VISION_MODEL="", REQUIRE_AI=True)
        self.p.start()
        self.sleep = mock.patch.object(director.time, "sleep")
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.p.stop()
        vision.reset()
        topics.set_story({}, "")
        resume.reset()
        offtopic.reset()


class PlannerOutage(_AI):
    SEGS = [Segment("At 10.19 on a Tuesday morning, the ground at Biscuit Basin blew open.", 0.0, 4.0),
            Segment(UPLIFT, 4.0, 8.0),
            Segment("Rangers closed the boardwalk within the hour.", 8.0, 12.0)]
    BRIEF = {"kind": "disaster", "summary": "", "event": "Biscuit Basin hydrothermal explosion", "year": 2024,
             "places": ["Biscuit Basin", "Yellowstone National Park"], "people": [], "hookBeats": [0], "cast": [],
             "sections": []}

    def test_a_402_mid_plan_stops_the_job_with_no_line_planned_by_the_rules(self):
        refused = or_error(402, "This request requires more credits, or fewer max_tokens. You requested up to "
                                "16000 tokens, but can only afford 5133.")
        with mock.patch.object(director.requests, "post", return_value=refused) as post:
            with self.assertRaises(aiguard.AIStopped) as e:
                director.plan(self.SEGS, title=YS_TITLE, allow_maps=False, brief=dict(self.BRIEF))
        self.assertIn("Your AI balance ran out", str(e.exception))
        self.assertIn("Top up OpenRouter, then press Retry", str(e.exception))
        self.assertEqual(aiguard.tripped(), aiguard.CREDIT)
        # One refusal is enough: the dry account is never asked again (the Yellowstone build asked it 4,158 times).
        self.assertLessEqual(post.call_count, 2)
        self.assertFalse(vision.enabled())

    def test_with_the_stop_off_the_rules_never_take_the_title_as_the_subject(self):
        # REQUIRE_AI=0 (the old behaviour): the plan goes on by the rules - from the line's own words now.
        refused = or_error(402, "Credits insufficient")
        with mock.patch.object(config, "REQUIRE_AI", False), \
                mock.patch.object(director.requests, "post", return_value=refused):
            shots, kind, _w = director.plan(self.SEGS, title=YS_TITLE, allow_maps=False, brief=dict(self.BRIEF))
        self.assertEqual(kind, "rules")
        for shot in shots:
            for field in ("query", "subject", "intent"):
                self.assertNotIn("EXPLODED", str(shot.get(field) or ""), (field, shot.get(field)))
            self.assertNotIn("EXPLODED", " ".join(shot.get("fallbacks") or []))
            self.assertNotEqual(shot.get("subjectType"), "person")      # "Yellowstone Just" is no one's name
        self.assertIn("Biscuit Basin", shots[0]["query"])


# --------------------------------------------------------------------------- #
# 1d. The job: a 402 mid-search stops it, keeps the judged work, and the Retry takes it back
# --------------------------------------------------------------------------- #

class _Built(Exception):
    pass


class FakeR2:
    def __init__(self):
        self.store = {}

    def patches(self):
        return [mock.patch.object(r2, "enabled", return_value=True),
                mock.patch.object(r2, "upload", side_effect=self.upload),
                mock.patch.object(r2, "upload_bytes", side_effect=self.upload_bytes),
                mock.patch.object(r2, "get_bytes", side_effect=lambda key, *a, **kw: self.store.get(key)),
                mock.patch.object(r2, "list_keys", side_effect=lambda prefix="", *a, **kw: [
                    {"key": k} for k in list(self.store) if k.startswith(prefix)]),
                mock.patch.object(r2, "delete", side_effect=lambda key, *a, **kw: self.store.pop(key, None) is not None)]

    def upload(self, path, key, content_type="video/mp4", **kw):
        with open(path, "rb") as fh:
            self.store[key] = fh.read()
        return key

    def upload_bytes(self, data, key, content_type="application/json", **kw):
        self.store[key] = bytes(data)
        return key

    def record(self):
        rows = [json.loads(v) for k, v in self.store.items() if k.endswith(".json") and "/resume/" in k]
        return rows[0] if len(rows) == 1 else None


class JobOutage(_AI):
    """do_plan end to end with the network mocked, as tests/test_shot_cap.py runs it."""

    LINES = ["At 10.19 on a Tuesday morning, the ground at Biscuit Basin blew open.",
             "Boiling water and rock shot a hundred feet into the air.",
             "Tourists on the boardwalk ran for the parking lot.",
             UPLIFT,
             "Rangers closed the basin within the hour.",
             "Scientists at the observatory began to look for a cause."]
    BRIEF = PlannerOutage.BRIEF

    def setUp(self):
        super().setUp()
        self.r2 = FakeR2()
        self.work = tempfile.mkdtemp()
        self.segs = [Segment(t, 4.0 * i, 4.0 * i + 4.0) for i, t in enumerate(self.LINES)]
        self.words = [Word(w, 4.0 * i, 4.0 * i + 0.5) for i, t in enumerate(self.LINES) for w in t.split()[:3]]
        self.calls = {"transcribe": 0, "brief": 0, "plan": [], "search": [], "rescue": 0, "ladder": 0, "build": 0}

    def clip(self, i, judged=True):
        path = os.path.join(self.work, f"clip{i}.mp4")
        with open(path, "wb") as fh:
            fh.write(b"mp4 " + str(i).encode())
        return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=BISCUIT{i:04d}",
                          local_path=path, duration=8.0, moment={"start": 12.0},
                          relevance_score=0.82 if judged else None, attribution=f"YouTube: Biscuit Basin explosion {i}")

    def run_plan(self, on_search, planner=None):
        shots = [{"query": f"Biscuit Basin hydrothermal explosion {i}", "visualType": "footage",
                  "subject": "Biscuit Basin", "subjectType": "place", "intent": t, "fallbacks": [], "overlay": None}
                 for i, t in enumerate(self.LINES)]

        def transcribe_words(*a, **kw):
            self.calls["transcribe"] += 1
            return list(self.words)

        def story_brief(*a, **kw):
            self.calls["brief"] += 1
            return json.loads(json.dumps(self.BRIEF))

        def plan(segments, **kw):
            self.calls["plan"].append(kw.get("planned"))
            with director._AI_SHOTS_LOCK:          # what the AI pass records for a Retry
                director.LAST_AI_SHOTS.update({i: dict(s) for i, s in enumerate(shots)})
            return [dict(s) for s in shots[:len(segments)]], "ai", []

        def source_many(jobs, work, **kw):
            self.calls["search"].append([j["context"] if "context" in j else j.get("intent") for j in jobs])
            return on_search(jobs)

        def rescue(*a, **kw):
            self.calls["rescue"] += 1
            return {}

        def ladder(*a, **kw):
            self.calls["ladder"] += 1
            return {}

        def build(segments, shots_, assets, **kw):
            self.calls["build"] += 1
            self.built = list(assets)
            raise _Built()
        patches = self.r2.patches() + [
            mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"),
            mock.patch.object(handler.storage, "download", return_value="/w/vo.mp3"),
            mock.patch.object(handler.renderer, "probe_duration", return_value=24.0),
            mock.patch.object(handler.transcribe, "transcribe_words", side_effect=transcribe_words),
            mock.patch.object(handler.transcribe, "segment_words", return_value=self.segs),
            mock.patch.object(handler.director, "story_brief", side_effect=story_brief),
            mock.patch.object(handler.director, "plan", side_effect=planner or plan),
            mock.patch.object(handler.library.Library, "load", return_value=None),
            mock.patch.object(handler.fanout, "enabled_for", return_value=False),
            mock.patch.object(pools, "source_by_subject", return_value={}),
            mock.patch.object(pools, "fill_from_reserve", return_value={}),
            mock.patch.object(media, "source_many", side_effect=source_many),
            mock.patch.object(media, "rescue_fill", side_effect=rescue),
            mock.patch.object(handler.gapfill, "fill_empty", side_effect=ladder),
            mock.patch.object(handler.timeline, "build", side_effect=build),
            mock.patch.object(credit, "uses_openrouter", return_value=True),
            mock.patch.object(credit, "openrouter_left", return_value=25.0),
            mock.patch.multiple(config, UPSCALE_ENABLED=False, ALLOW_VERTICAL=False, SUBJECT_POOLS=True,
                                MENTION_CUTS=False, HOOK_BOOST=False, SHOT_MAX_SECONDS=0.0, AI_RESUME=True,
                                DATA_GRAPHICS=False, PACKS_FIRST=False)]
        for p in patches:
            p.start()
        try:
            return handler.do_plan({"audio_url": "vo.mp3", "project_id": "proj-1", "title": YS_TITLE}, self.work,
                                   handler.Reporter(""))
        finally:
            for p in reversed(patches):
                p.stop()
            media.set_youtube_only(False)
            vision.set_story({})
            media.set_story_kind("")

    def test_a_402_mid_search_stops_the_job_keeps_the_judged_clips_and_the_retry_takes_them_back(self):
        def first_run(jobs):
            # Lines 1 and 2 found judged clips; then the account ran dry (fd58f969: 22 s into its search). A clip
            # found with no verdict is in flight too (line 4) - it must never be kept or placed.
            out = [self.clip(0), self.clip(1)]
            vision.note_out_of_credits("openai/gpt-5.2", "This request requires more credits, or fewer max_tokens")
            out += [None, self.clip(3, judged=False), None, None]
            return out

        with self.assertRaises(aiguard.AIStopped) as e:
            self.run_plan(first_run)
        msg = str(e.exception)
        self.assertIn("Your AI balance ran out while this video was being made", msg)
        self.assertIn("The work done so far is kept, so a Retry does not pay for it again.", msg)
        # Nothing after the stop: no last pass, no fallback ladder, no timeline of unjudged clips.
        self.assertEqual((self.calls["rescue"], self.calls["ladder"], self.calls["build"]), (0, 0, 0))
        saved = self.r2.record()
        self.assertIsNotNone(saved)
        self.assertEqual(sorted(saved["assets"]), ["0", "1"])           # the judged clips only
        self.assertEqual(len(saved["shots"]), len(self.LINES))          # the planner's own shots
        self.assertTrue(saved["words"] and saved["brief"])

        # The Retry: the same job again, the account topped up.
        vision.reset()
        self.calls.update(transcribe=0, brief=0, plan=[], search=[])

        def retry(jobs):
            return [self.clip(10 + j["index"]) for j in jobs]
        with self.assertRaises(_Built):
            self.run_plan(retry)
        self.assertEqual(self.calls["transcribe"], 0)                     # word timings kept
        self.assertEqual(self.calls["brief"], 0)                          # the brief kept
        self.assertEqual(len(self.calls["plan"][0] or {}), len(self.LINES))  # the planned shots handed back
        self.assertEqual(len(self.calls["search"][0]), len(self.LINES) - 2)  # lines 1-2 never searched again
        self.assertEqual([a.relevance_score for a in self.built[:2]], [0.82, 0.82])
        self.assertTrue(all(os.path.basename(a.local_path).startswith("resume_") for a in self.built[:2]))
        self.assertTrue(all(a is not None and a.relevance_score for a in self.built))



# --------------------------------------------------------------------------- #
# 3. Off-topic candidates, on the Yellowstone build's own placed clips (2a2200b3, read from its scene_data)
# --------------------------------------------------------------------------- #

# (title, channel) of uploads that reached that video's timeline and are not footage of the real world.
YS_OFF_TOPIC = [
    ("JJ is LEFT FOREVER in Minecraft! (Maizen)", "Maizen"),
    ("Best of Teeter \U0001f40e Yellowstone | Paramount Network", "Paramount Network"),
    ("Yellowstone | Beth Makes a Bold Deal with Rip's Old Friend | Season 5", "Paramount Network"),
    ("Yellowstone | Red Bear Asks James Dutton If He Can Bury His Father On His Land", "Paramount Network"),
    ("What If Mosasaurus Were Still Alive? | Giant Sea Dinosaur | The Dr Binocs Show | Peekaboo Kidz", "Peekaboo Kidz"),
    ("What If You Jumped Into Lake Natron? | Deadliest Lake On Earth | The Dr Binocs Show | Peekaboo Kidz", ""),
    ("Blippi Goes Inside a Volcano! Educational Videos for Kids", "Blippi"),
    ("Intros On Repeat | CHIP N DALE: Rescue Rangers | Theme song on REPEAT | (1989)", ""),
    ("Volcanoes for Kids | A fun and engaging introduction to volcanoes for children", ""),
    ("Family dogs boiled alive in tragic hot spring accident, owner dives in to save them - TomoNews", ""),
    # fd58f969's (2026-10-08), the same story
    ("Simon & Garfunkel - Bridge Over Troubled Water (Audio)", "Simon & Garfunkel"),
    ("Magma Full Showcase | Haze Seas", ""),
    ("Yellowstone Theme | Paramount Network", "Paramount Network"),
]
# Real footage from the same timeline: kept.
YS_REAL = [
    ("Massive EXPLOSION! @ Yellowstone | Biscuit Basin Hydrothermal Blast!", ""),
    ("Tourist touches hot spring with hand at Yellowstone | GMA", "Good Morning America"),
    ("Video shows tourists flee as Yellowstone geyser erupts", "CBS News"),
    ("Drone Video Shows Bubbling Lava Inside Iceland's Fiery Volcano | NBC News NOW", "NBC News"),
    ("DRONE footage shows damages to US Yellowstone Park after unprecedented flooding", ""),
    ("Yellowstone Drone 4K Flying over Yellowstone National Park - Areal View with Relaxing Piano Music", ""),
    ("Windy Biscuit Basin With Live Narration: Virtual Yellowstone Tour!", ""),
]


class OffTopic(unittest.TestCase):
    def setUp(self):
        offtopic.reset()
        self._p = [mock.patch.object(topics, "story_text", return_value=YS_STORY),
                   mock.patch.multiple(config, OFFTOPIC_FILTER=True, ALLOW_VERTICAL=False)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def test_the_yellowstone_builds_off_topic_clips_are_dropped_before_any_download(self):
        # media._usable_title is the check every source runs on a search result's title and channel, before the
        # metadata read, the storyboard, the download and the judge.
        for title, channel in YS_OFF_TOPIC:
            self.assertFalse(media._usable_title(title, channel, context=UPLIFT), title)
        self.assertGreaterEqual(offtopic.stats().get("byStage", {}).get("search", 0), len(YS_OFF_TOPIC) - 1)

    def test_real_yellowstone_footage_is_kept(self):
        for title, channel in YS_REAL:
            self.assertEqual(offtopic.reason(title, channel, line=UPLIFT), "", title)

    def test_a_story_about_that_thing_keeps_it(self):
        show = "Yellowstone season 5 finale: how the Paramount TV show ended for the Dutton family"
        self.assertEqual(offtopic.reason(*YS_OFF_TOPIC[2], story=show), "")
        self.assertEqual(offtopic.reason("Minecraft 1.21 update gameplay", "Mojang",
                                         story="Why Minecraft is still the best-selling video game"), "")
        self.assertNotEqual(offtopic.reason("Minecraft 1.21 update gameplay", "Mojang", story=YS_STORY), "")

    def test_a_kids_word_on_a_real_news_line_is_not_a_kids_channel(self):
        self.assertEqual(offtopic.reason("Measles vaccine for children: what parents need to know", "CBS News",
                                         story="A measles outbreak in Texas"), "")


# --------------------------------------------------------------------------- #
# 4-5. Video thumbnails never as stills; subtitles never, a broadcaster's chyron fine on news
# --------------------------------------------------------------------------- #

class ThumbnailsAndSubtitles(unittest.TestCase):
    def test_youtube_thumbnails_are_never_stills(self):
        for url in ("https://i.ytimg.com/vi/wkJS4lkMzWc/maxresdefault.jpg",
                    "https://img.youtube.com/vi/GKrq3psVKLc/hqdefault.jpg",
                    "https://i0.wp.com/i.ytimg.com/vi/GKrq3psVKLc/hqdefault.jpg"):
            self.assertTrue(stockblock.video_thumbnail(url), url)
        self.assertFalse(stockblock.video_thumbnail("https://www.nps.gov/yell/planyourvisit/images/biscuit.jpg"))

    def test_subtitles_are_turned_down_on_news_lines_and_a_chyron_is_not(self):
        with mock.patch.object(config, "VISION_NEWS_SUBTITLES", True):
            subs = {"added": True, "items": [{"kind": "subtitles", "where": "bottom",
                                              "text": "and then the whole pool just went up"}]}
            self.assertTrue(vision.text_check_decision(subs, "news"))
            chyron = {"added": True, "items": [{"kind": "banner", "where": "bottom",
                                                "text": "BREAKING: HYDROTHERMAL EXPLOSION AT BISCUIT BASIN"}]}
            self.assertEqual(vision.text_check_decision(chyron, "news"), "")
