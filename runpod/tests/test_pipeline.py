"""
Worker test suite. Runs offline — no network, no whisper, no Remotion.

    python -m unittest discover -s tests -v

The tests that matter most here are the contract ones. This pipeline spans
Python and TypeScript, and the failures that actually cost a render are the
silent ones: a template the director emits that the renderer does not draw, a
scene track that does not tile the narration, a document that reaches headless
Chrome with no audio. Each of those has a test below.
"""
import datetime
import json
import os
import re
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as requests_module  # noqa: E402
from src import config, director, geocode, media, moments, storage, timeline  # noqa: E402
from src.media import MediaAsset  # noqa: E402
from src.transcribe import Segment, Word, keywords_for, segment_words, align_to_script  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion", "src")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def words_from(text: str, wps: float = 2.6, start: float = 0.0):
    """Fake whisper output: evenly spaced words with a pause after sentences."""
    out, t = [], start
    for token in text.split():
        end = t + 1.0 / wps
        out.append(Word(text=token, start=round(t, 3), end=round(end, 3)))
        t = end + (0.35 if token[-1:] in ".!?" else 0.02)
    return out


def seg(text: str, start: float, end: float) -> Segment:
    return Segment(text=text, start=start, end=end, words=words_from(text, start=start))


def asset(kind="video", source="youtube", url="file:///tmp/a.mp4", **kw) -> MediaAsset:
    return MediaAsset(kind=kind, source=source, url=url, local_path=url, **kw)


def simple_plan(n: int, seconds: float = 3.0):
    """n back-to-back beats with matching shots and assets."""
    segments = [seg(f"Beat number {i} of the narration.", i * seconds, (i + 1) * seconds)
                for i in range(n)]
    shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None} for i in range(n)]
    assets = [asset() for _ in range(n)]
    return segments, shots, assets


def build_doc(n=5, seconds=3.0, inp=None, **kw):
    segments, shots, assets = simple_plan(n, seconds)
    return timeline.build(
        segments, shots, assets,
        audio_url="file:///tmp/vo.mp3",
        audio_duration=n * seconds,
        inp=inp if inp is not None else {},
        **kw,
    )


# --------------------------------------------------------------------------- #
# Cross-language contract
# --------------------------------------------------------------------------- #

class TemplateContract(unittest.TestCase):
    """
    The template list exists in three places. They must agree.

    A type the director can emit but the renderer cannot draw does not error —
    it renders as nothing or as the wrong card, in the middle of a paid render.
    """

    def _ts_overlay_types(self):
        with open(os.path.join(REMOTION, "types.ts"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"export type OverlayType\s*=(.*?);", src, re.S)
        self.assertIsNotNone(block, "OverlayType union not found in types.ts")
        return set(re.findall(r'"([a-z-]+)"', block.group(1)))

    def _main_overlay_keys(self):
        with open(os.path.join(REMOTION, "Main.tsx"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"const OVERLAYS[^=]*=\s*\{(.*?)\n\};", src, re.S)
        self.assertIsNotNone(block, "OVERLAYS map not found in Main.tsx")
        body = block.group(1)
        quoted = set(re.findall(r'^\s*"([a-z-]+)":', body, re.M))
        bare = set(re.findall(r"^\s*([a-z]+):", body, re.M))
        return quoted | bare

    def test_python_and_types_agree(self):
        self.assertEqual(director.TEMPLATES, self._ts_overlay_types())

    def test_renderer_draws_every_template(self):
        self.assertEqual(director.TEMPLATES, self._main_overlay_keys())

    def test_every_template_has_a_duration(self):
        # timeline.build looks this up; a miss silently falls back to 3.5s.
        self.assertEqual(set(timeline._OVERLAY_SECONDS), director.TEMPLATES)

    def _ts_treatments(self):
        with open(os.path.join(REMOTION, "types.ts"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"export type Treatment\s*=(.*?);", src, re.S)
        self.assertIsNotNone(block, "Treatment union not found in types.ts")
        return set(re.findall(r'"([a-z-]+)"', block.group(1)))

    def test_python_and_types_agree_on_treatments(self):
        # Same contract as the overlay templates: a grade the renderer does not
        # know renders as an ungraded clip, silently, mid-render.
        self.assertEqual(director.TREATMENTS, self._ts_treatments())

    def test_film_layer_handles_every_treatment(self):
        path = os.path.join(REMOTION, "components", "FilmLayer.tsx")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        handled = set(re.findall(r'case "([a-z-]+)":', src)) | {"none"}
        self.assertEqual(director.TREATMENTS, handled)


class DisqualifyingTitles(unittest.TestCase):
    """
    Titles that must never reach the timeline.

    These are regressions, each named after a clip that actually shipped into a
    render: scoring them down was not enough, because the ranker still takes the
    best of whatever is left when a query finds nothing good.
    """

    REJECT = [
        "Create Epic TRAILER TEXT Animation in Premiere Pro",   # Premiere screen capture
        "Diablo 4 season 5 ladder gameplay",                    # gameplay HUD
        "Kevin Costner interview on CBS News",                  # broadcast desk
        "Free cinematic LUT preset download",                   # editing-software content
        "Why Yellowstone was cancelled - my thoughts",          # commentary
    ]
    KEEP = [
        "Montana ranch drone aerial 4k footage",
        "Yellowstone national park timelapse cinematic",
        "Aerial view of cattle on open range, no commentary",
    ]

    def test_disqualifying_titles_are_rejected(self):
        for title in self.REJECT:
            with self.subTest(title=title):
                self.assertTrue(media._TALKING_HEAD.search(title))

    def test_real_footage_titles_survive(self):
        for title in self.KEEP:
            with self.subTest(title=title):
                self.assertIsNone(media._TALKING_HEAD.search(title))


class StorageBroker(unittest.TestCase):
    """
    With no service key on the worker, uploads go through the app's
    worker-storage function, authorised by the running job's id.
    """

    def setUp(self):
        self.patches = [
            mock.patch.object(config, "SUPABASE_SERVICE_KEY", ""),
            mock.patch.object(config, "STORAGE_BROKER_URL", "https://x/functions/v1/worker-storage"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_broker_is_used_only_without_a_service_key(self):
        self.assertTrue(storage.broker_enabled())
        with mock.patch.object(config, "SUPABASE_SERVICE_KEY", "key"):
            self.assertFalse(storage.broker_enabled())

    def test_upload_signs_puts_then_reads(self):
        calls = []

        def fake_post(url, json=None, timeout=None):
            calls.append(json)
            r = mock.Mock(status_code=200)
            r.json.return_value = ({"ok": True, "uploadUrl": "https://up"} if json["action"] == "upload"
                                   else {"ok": True, "readUrl": "https://read"})
            return r

        with mock.patch.object(storage.requests, "post", side_effect=fake_post), \
                mock.patch.object(storage, "upload_to_signed_url") as put:
            url = storage.broker_upload("/tmp/a.mp4", "video-media", "projects/p1/media/s1.mp4", "p1", "job-9")
        self.assertEqual(url, "https://read")
        put.assert_called_once_with("/tmp/a.mp4", "https://up")
        self.assertEqual([c["action"] for c in calls], ["upload", "read"])
        # The broker authorises by project + running job id.
        self.assertTrue(all(c["project_id"] == "p1" and c["job_id"] == "job-9" for c in calls))

    def test_a_refusal_raises(self):
        r = mock.Mock(status_code=403)
        r.json.return_value = {"ok": False, "error": "job is not running"}
        with mock.patch.object(storage.requests, "post", return_value=r):
            with self.assertRaisesRegex(storage.StorageError, "job is not running"):
                storage.broker_upload("/tmp/a.mp4", "renders", "projects/p1/final.mp4", "p1", "j")

    def test_published_media_records_where_it_lives(self):
        import handler
        import tempfile
        doc = build_doc(n=2, seconds=3.0)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            fh.write(b"x")
        doc["scenes"][0]["media"]["url"] = fh.name
        try:
            with mock.patch.object(storage, "broker_upload", return_value="https://signed") as up:
                handler.publish_media(doc, "p1", "video-media", handler.Reporter(""), job_id="job-9")
        finally:
            os.unlink(fh.name)
        media = doc["scenes"][0]["media"]
        self.assertEqual(media["url"], "https://signed")
        self.assertEqual(media["storage"], {"bucket": "video-media",
                                            "path": f"projects/p1/media/{doc['scenes'][0]['id']}.mp4"})
        self.assertEqual(up.call_args[0][3:], ("p1", "job-9"))


class ContactSheetCache(unittest.TestCase):
    """
    Several scenes scouting the same candidate video (common for a repeated
    subject) each re-fetched and re-built its storyboard contact sheet from
    scratch, even though the sheet itself doesn't depend on which scene is
    asking - only the vision judgement of it does.
    """

    def setUp(self):
        moments.reset_cache()

    def tearDown(self):
        moments.reset_cache()

    def test_the_same_video_builds_its_sheet_once(self):
        calls = []

        def fake_build(info, seconds, proxy, tiles):
            calls.append(info["id"])
            return ("b64==", [1.0, 2.0, 3.0])

        info = {"id": "abc123", "duration": 100}
        with mock.patch.object(moments, "_build_contact_sheet", side_effect=fake_build):
            a = moments.contact_sheet(info, 6.0, "", 20)
            b = moments.contact_sheet(info, 6.0, "", 20)
        self.assertEqual(len(calls), 1)
        self.assertEqual(a, b)

    def test_a_different_video_still_builds_its_own_sheet(self):
        calls = []

        def fake_build(info, seconds, proxy, tiles):
            calls.append(info["id"])
            return ("b64==", [1.0])

        with mock.patch.object(moments, "_build_contact_sheet", side_effect=fake_build):
            moments.contact_sheet({"id": "abc123", "duration": 100}, 6.0, "", 20)
            moments.contact_sheet({"id": "xyz789", "duration": 100}, 6.0, "", 20)
        self.assertEqual(calls, ["abc123", "xyz789"])

    def test_reset_cache_clears_it(self):
        calls = []

        def fake_build(info, seconds, proxy, tiles):
            calls.append(1)
            return ("b64==", [1.0])

        info = {"id": "abc123", "duration": 100}
        with mock.patch.object(moments, "_build_contact_sheet", side_effect=fake_build):
            moments.contact_sheet(info, 6.0, "", 20)
            moments.reset_cache()
            moments.contact_sheet(info, 6.0, "", 20)
        self.assertEqual(len(calls), 2)


class PersonSafetyNet(unittest.TestCase):
    """
    subjectType "person" is what stops a fabricated photo of a real person:
    it blocks image GENERATION and lets a real portrait pass the vision
    gate. It was only ever set by the AI director pass - a rule-only beat
    (no API key, or both director models down) had no signal at all, so a
    real person could reach the generation fallback unflagged. A generated
    photo of a real, named person shipped once already before this net.
    """

    def test_a_plain_name_marks_the_rule_shot_as_a_person(self):
        seg = Segment(text="Barack Obama Sr. arrived at the airport that morning.",
                      start=0, end=3, words=[])
        shot = director._rule_shot(seg, 1, "The Obama Family")
        self.assertEqual(shot["subjectType"], "person")

    def test_an_honorific_marks_it_too(self):
        seg = Segment(text="Dr. Chen reviewed the file the next week.", start=0, end=3, words=[])
        shot = director._rule_shot(seg, 1, "")
        self.assertEqual(shot["subjectType"], "person")

    def test_a_place_is_not_mistaken_for_a_person(self):
        seg = Segment(text="Lake Mead dropped to a record low that August.",
                      start=0, end=3, words=[])
        shot = director._rule_shot(seg, 1, "Lake Mead")
        self.assertEqual(shot["subjectType"], "")

    def test_the_project_title_alone_can_signal_a_person(self):
        # A beat that never re-says the name, in a project ABOUT that person.
        seg = Segment(text="He never spoke of it again.", start=0, end=3, words=[])
        shot = director._rule_shot(seg, 1, "Barack Obama Sr.")
        self.assertEqual(shot["subjectType"], "person")

    def test_ai_pass_falls_back_to_the_rule_shots_own_tag_when_the_model_omits_one(self):
        person_shot = director._rule_shot(
            Segment(text="Barack Obama Sr. smiled for the camera.", start=0, end=3, words=[]),
            0, "The Obama Family")
        self.assertEqual(person_shot["subjectType"], "person")
        body = {"choices": [{"message": {"content":
            '{"shots":[{"index":0,"subject":"Barack Obama Sr.","intent":"a warm portrait",'
            '"query":"Barack Obama Sr. portrait","visualType":"image","overlay":null}]}'}}]}
        # No subjectType key at all in the model's own answer.
        r = mock.Mock(status_code=200)
        r.json.return_value = body
        with mock.patch.object(config, "DIRECTOR_API_KEY", "k"), \
                mock.patch.object(config, "DIRECTOR_API_BASE", "https://api.kie.ai/v1"), \
                mock.patch.object(config, "DIRECTOR_MODEL", "gpt-5-2"), \
                mock.patch.object(config, "DIRECTOR_FALLBACK_MODELS", []), \
                mock.patch.object(director.requests, "post", return_value=r):
            director._ai_pass([Segment(text="Barack Obama Sr. smiled for the camera.",
                                       start=0, end=3, words=[])],
                              "The Obama Family", [person_shot])
        self.assertEqual(person_shot["subjectType"], "person")

    def test_generation_is_refused_for_a_person_even_via_the_rule_path(self):
        made = []

        def gen(prompt, work_dir, **k):
            made.append(prompt)
            return MediaAsset(kind="image", source="generated", url="",
                              local_path=f"/w/g{len(made)}.png")

        jobs = [{"index": 0, "query": "Barack Obama Sr. portrait", "seconds": 3.0,
                 "subject_type": director._rule_shot(
                     Segment(text="Barack Obama Sr. smiled.", start=0, end=3, words=[]),
                     0, "").get("subjectType", "")}]
        self.assertEqual(jobs[0]["subject_type"], "person")
        with mock.patch.object(media, "source_for_segment", return_value=None), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", side_effect=gen), \
                mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 10):
            media.reset_cache()
            media.source_many(jobs, "/tmp", workers=1)
        self.assertEqual(made, [])

    def test_borrowing_prefers_the_same_subject_over_the_nearest_scene(self):
        import handler
        doc = build_doc(n=5, seconds=3.0)
        for i, subj in ((0, "Lake Mead"), (4, "Hoover Dam")):
            doc["scenes"][i]["media"] = {"type": "video", "source": "youtube",
                                         "url": f"https://x/{i}.mp4"}
            doc["scenes"][i]["semanticMetadata"] = {"subject": subj}
        for i in (1, 2, 3):
            doc["scenes"][i]["media"] = {"type": "color", "url": "", "source": "none"}
        doc["scenes"][2]["semanticMetadata"] = {"subject": "Hoover Dam"}
        handler._fill_missing_media(doc)
        self.assertEqual(doc["scenes"][2]["media"]["url"], "https://x/4.mp4")
        self.assertIn("same subject", doc["scenes"][2]["reviewReason"])


class DirectorFallback(unittest.TestCase):
    """
    The director's own model call had no fallback: one failed request and a
    whole batch of beats silently dropped to the rule planner. Vision already
    retries with gemini-3-pro on failure; the director now does too -
    verified working through this Kie key (19s for a text plan call).
    """

    def _reply(self, status, body):
        r = mock.Mock(status_code=status)
        r.json.return_value = body
        return r

    def setUp(self):
        self.patches = [mock.patch.object(config, "DIRECTOR_API_KEY", "k"),
                        mock.patch.object(config, "DIRECTOR_API_BASE", "https://api.kie.ai/v1"),
                        mock.patch.object(config, "DIRECTOR_MODEL", "gpt-5-2"),
                        mock.patch.object(config, "DIRECTOR_FALLBACK_MODELS", ["gemini-3-pro"])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _segments(self):
        from src.transcribe import Word
        return segment_words([Word(text=w, start=i * 0.3, end=i * 0.3 + 0.25)
                              for i, w in enumerate("The lake dropped fast today".split())])

    def test_falls_through_to_gemini_when_gpt_fails(self):
        ok_body = {"choices": [{"message": {"content":
            '{"shots":[{"index":0,"subject":"Lake Mead","subjectType":"place",'
            '"intent":"dry lakebed","query":"Lake Mead dry lakebed","visualType":"footage","overlay":null}]}'}}]}
        calls = []

        def fake_post(url, **k):
            calls.append(k["json"]["model"])
            if k["json"]["model"] == "gpt-5-2":
                raise requests_module.ConnectionError("boom")
            return self._reply(200, ok_body)

        with mock.patch.object(director.requests, "post", side_effect=fake_post):
            enriched, warnings = director._ai_pass(self._segments(), "Lake Mead",
                                                    [director._rule_shot(s, i, "Lake Mead")
                                                     for i, s in enumerate(self._segments())])
        self.assertEqual(calls, ["gpt-5-2", "gemini-3-pro"])
        self.assertEqual(enriched, 1)
        self.assertEqual(warnings, [])

    def test_a_kie_wrapper_error_also_falls_through(self):
        # Kie wraps a failure in a 200, not an HTTP error status.
        calls = []

        def fake_post(url, **k):
            calls.append(k["json"]["model"])
            if k["json"]["model"] == "gpt-5-2":
                return self._reply(200, {"code": 422, "msg": "The channel is not supported"})
            return self._reply(200, {"choices": [{"message": {"content": '{"shots":[]}'}}]})

        with mock.patch.object(director.requests, "post", side_effect=fake_post):
            director._ai_pass(self._segments(), "Lake Mead",
                              [director._rule_shot(s, i, "Lake Mead")
                               for i, s in enumerate(self._segments())])
        self.assertEqual(calls, ["gpt-5-2", "gemini-3-pro"])

    def test_both_models_down_falls_back_to_rules_with_a_clear_warning(self):
        with mock.patch.object(director.requests, "post",
                              side_effect=requests_module.ConnectionError("boom")):
            enriched, warnings = director._ai_pass(self._segments(), "Lake Mead",
                                                    [director._rule_shot(s, i, "Lake Mead")
                                                     for i, s in enumerate(self._segments())])
        self.assertEqual(enriched, 0)
        self.assertIn("gpt-5-2", warnings[0])
        self.assertIn("gemini-3-pro", warnings[0])


class VidRushMatching(unittest.TestCase):
    """Rules added after comparing real renders with VidRush's own exports."""

    def test_two_ranges_of_one_youtube_video_are_the_same_clip(self):
        # The duplicate-clip bug: per-range filenames made each range its own
        # identity, so one video was reused across scenes seconds apart.
        a = MediaAsset(kind="video", source="youtube", url="q1",
                       local_path="/w/yt_EYV6zfZyDW0_143957_6500.mp4")
        b = MediaAsset(kind="video", source="youtube", url="q2",
                       local_path="/w/yt_EYV6zfZyDW0_812333_8240.mp4")
        self.assertEqual(a.identity, "yt:EYV6zfZyDW0")
        self.assertEqual(a.identity, b.identity)

    def test_an_underscore_inside_a_video_id_is_kept(self):
        a = MediaAsset(kind="video", source="youtube", url="q",
                       local_path="/w/yt_a_b-cdefghi_1000_6000.mp4")
        self.assertEqual(a.identity, "yt:a_b-cdefghi")

    def test_query_gets_each_subject_word_once(self):
        self.assertEqual(
            director.with_subject("Ohio Valley river gauge", "Ohio Valley river data flood gauges"),
            "gauge Ohio Valley river data flood gauges")
        self.assertEqual(director.with_subject("Lake Mead", "exposed boat ramp drought"),
                         "Lake Mead exposed boat ramp drought")
        self.assertEqual(director.with_subject("", "Great Schism 1054 Great Schism"),
                         "Great Schism 1054")

    def test_a_person_may_be_a_talking_head_nothing_else_may(self):
        from src import vision
        v = {"score": 0.9, "has_text_or_watermark": False, "is_talking_head": True,
             "description": ""}
        self.assertFalse(vision.acceptable(v))
        self.assertTrue(vision.acceptable(v, allow_people=True))
        v["has_text_or_watermark"] = True
        self.assertFalse(vision.acceptable(v, allow_people=True))

    def _source_many(self, fake, jobs, rescue=None, gen=None):
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", side_effect=gen or (lambda *a, **k: None)), \
                mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 10):
            media.reset_cache()
            return media.source_many(jobs, "/tmp", workers=2, rescue=rescue)

    def test_ai_rescue_fills_an_empty_scene_with_a_new_clip(self):
        def fake(query, seconds, work_dir, **kw):
            if query == "medieval cathedral interior":
                return MediaAsset(kind="video", source="archive_org", url="https://x/cathedral.mp4")
            return None
        jobs = [{"index": 0, "query": "Humbert of Silva Candida", "seconds": 3.0,
                 "context": "Humbert laid the bull on the altar."}]
        asked = []

        def rescue(items):
            asked.append(items)
            return {0: ["medieval cathedral interior", "papal bull document"]}

        out = self._source_many(fake, jobs, rescue=rescue)
        self.assertEqual(out[0].url, "https://x/cathedral.mp4")
        self.assertEqual(asked[0][0]["query"], "Humbert of Silva Candida")

    def test_a_real_person_is_never_given_a_generated_image(self):
        made = []

        def gen(prompt, work_dir, **k):
            made.append(prompt)
            return MediaAsset(kind="image", source="generated", url="", local_path=f"/w/g{len(made)}.png")

        jobs = [{"index": 0, "query": "Barack Obama Sr. portrait", "seconds": 3.0,
                 "subject_type": "person"},
                {"index": 1, "query": "Honolulu airport 1971", "seconds": 3.0,
                 "subject_type": "place"}]
        out = self._source_many(lambda *a, **k: None, jobs, gen=gen)
        self.assertIsNone(out[0], "no invented photo of a real person")
        self.assertIsNotNone(out[1])
        self.assertEqual(len(made), 1)

    def test_frame_is_always_full(self):
        # The inset-on-a-backdrop archival look read as a bug, not a style,
        # in a real render: told directly to stop, on sight. pick_frame keeps
        # its signature (still called from every scene build) so nothing
        # upstream has to change if this is ever revisited.
        def a(w, h, kind="video"):
            return MediaAsset(kind=kind, source="youtube", url="u", width=w, height=h)
        self.assertEqual(timeline.pick_frame(a(1920, 1080), "film", "place"), "full")
        self.assertEqual(timeline.pick_frame(a(640, 480), "film", "place"), "full")
        self.assertEqual(timeline.pick_frame(a(854, 480), "film", "place"), "full")
        self.assertEqual(timeline.pick_frame(a(1080, 1350, "image"), "film", "person"), "full")
        self.assertEqual(timeline.pick_frame(a(1920, 1080, "image"), "archival", "place"), "full")
        self.assertEqual(timeline.pick_frame(a(1920, 1080), "film", "document"), "full")
        self.assertEqual(timeline.pick_frame(None, "film", ""), "full")


class SecondPass(unittest.TestCase):
    """The replace pass is parallel, reported and time-boxed."""

    def _run(self, fake, n=4, budget=240):
        jobs = [{"index": i, "query": "same", "seconds": 3.0} for i in range(n)]
        seen = []
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(config, "REPLACE_BUDGET_SECONDS", budget):
            out = media.source_many(jobs, "/tmp", workers=3,
                                    on_review=lambda d, t: seen.append((d, t)))
        return out, seen

    def test_repeats_are_replaced_and_progress_is_reported(self):
        def fake(query, seconds, work_dir, *, nth=0, used=None, **kw):
            return MediaAsset(kind="image", source="wikimedia", url=f"https://x/{nth}.jpg")

        # Every scene asks "same"; nth spreads them, so force a collision by
        # making pass 1 return one url for everybody.
        calls = {"n": 0}

        def colliding(query, seconds, work_dir, *, nth=0, used=None, **kw):
            calls["n"] += 1
            if calls["n"] <= 4:
                return MediaAsset(kind="image", source="wikimedia", url="https://x/dup.jpg")
            return fake(query, seconds, work_dir, nth=nth + calls["n"], used=used)

        out, seen = self._run(colliding)
        self.assertEqual(len({a.identity for a in out}), 4)
        self.assertEqual(seen[0], (0, 3))
        self.assertEqual(seen[-1], (3, 3))

    def test_nothing_new_starts_after_the_budget(self):
        calls = {"n": 0}

        def colliding(query, seconds, work_dir, *, nth=0, used=None, **kw):
            calls["n"] += 1
            return MediaAsset(kind="image", source="wikimedia", url="https://x/dup.jpg")

        out, _ = self._run(colliding, budget=0)
        self.assertEqual(calls["n"], 4)  # pass 1 only
        # Repeats are kept (better than black) but flagged for the editor.
        self.assertTrue(all(a.review_required for a in out[1:]))

    def test_an_empty_scene_gets_the_full_three_reaches(self):
        # A scene with nothing at nth=0 is not "exhausted" — nth=1..3 are
        # unrelated candidates. Cutting this to one attempt is what let a
        # real, findable scene end up empty and fail the whole render.
        calls = {"n": 0}

        def nothing(query, seconds, work_dir, *, nth=0, used=None, **kw):
            calls["n"] += 1
            return None

        self._run(nothing, n=2)
        self.assertEqual(calls["n"], 2 + 2 * 3)  # pass 1 + three retries each


class RenderConcurrency(unittest.TestCase):
    """
    Left unset, Remotion auto-detects concurrency from the host's real CPU
    count, not what the container is actually allowed to spawn threads for -
    a real render crashed this way (a Rust panic failing to spawn a thread)
    partway through a render. do_render must always pass an explicit value.
    """

    def _run(self, inp):
        import handler
        doc = build_doc(n=1, seconds=3.0)
        seen = {}
        with mock.patch.object(handler.renderer, "render",
                              side_effect=lambda *a, **k: seen.update(k) or a[1]), \
                mock.patch.object(handler.storage, "upload_to_signed_url", return_value=123):
            handler.do_render(doc, {"upload_url": "https://x/put", **inp}, "/tmp/x", handler.Reporter(""))
        return seen

    def test_defaults_to_the_configured_conservative_value(self):
        with mock.patch.object(config, "RENDER_CONCURRENCY", 4):
            seen = self._run({})
        self.assertEqual(seen["concurrency"], 4)

    def test_an_explicit_caller_value_still_wins(self):
        with mock.patch.object(config, "RENDER_CONCURRENCY", 4):
            seen = self._run({"concurrency": 8})
        self.assertEqual(seen["concurrency"], 8)


class PipelineProgress(unittest.TestCase):
    """The app draws its pipeline screen from these progress updates."""

    def _updates(self, calls):
        import handler
        sent = []
        job = {"id": "job-1"}

        def fake(j, update):
            # Called as progress_update(job, progress) — the job first.
            self.assertIs(j, job)
            sent.append(update)

        with mock.patch.object(handler.runpod.serverless, "progress_update", side_effect=fake):
            rep = handler.Reporter("", job=job)
            for args, kw in calls:
                rep(*args, **kw)
        return sent

    def test_each_step_names_its_phase(self):
        sent = self._updates([(("Downloading narration", 4), {}),
                              (("Planning the visual story", 15), {}),
                              (("Sourced 3/10 scenes", 30), {"done": 3, "total": 10}),
                              (("Rendering video 40%", 78), {}),
                              (("Saving clips for editing 2/10", 94), {"done": 2, "total": 10})])
        self.assertEqual([u["phase"] for u in sent],
                         ["narration", "plan", "source", "render", "save"])
        self.assertEqual((sent[2]["done"], sent[2]["total"]), (3, 10))
        self.assertTrue(all("elapsed" in u and u["phases"][0] == "narration" for u in sent))

    def test_phase_key_does_not_collide_with_the_display_text(self):
        # The app reads `stage` as the step label; sending a bare key there
        # would show "render" instead of "Rendering video 40%".
        sent = self._updates([(("Rendering video 40%", 78), {})])
        self.assertNotIn("stage", sent[0])
        self.assertEqual(sent[0]["status"], "Rendering video 40%")

    def test_published_scenes_get_a_thumbnail(self):
        import handler
        import tempfile
        doc = build_doc(n=1, seconds=3.0)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            fh.write(b"x")
        doc["scenes"][0]["media"]["url"] = fh.name
        try:
            with mock.patch.object(config, "SUPABASE_SERVICE_KEY", ""), \
                    mock.patch.object(config, "STORAGE_BROKER_URL", "https://x/worker-storage"), \
                    mock.patch.object(handler, "_thumbnail", return_value=fh.name), \
                    mock.patch.object(storage, "broker_upload",
                                      side_effect=lambda l, b, obj, *a, **k: f"https://s/{obj}"):
                handler.publish_media(doc, "p1", "video-media", handler.Reporter(""), job_id="j")
        finally:
            os.unlink(fh.name)
        media = doc["scenes"][0]["media"]
        sid = doc["scenes"][0]["id"]
        self.assertEqual(media["thumbnail"], f"https://s/projects/p1/thumbs/{sid}.jpg")
        self.assertEqual(media["thumbStorage"]["path"], f"projects/p1/thumbs/{sid}.jpg")

    def test_published_video_scenes_get_a_light_preview_copy(self):
        import handler
        import tempfile
        doc = build_doc(n=1, seconds=3.0)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            fh.write(b"x")
        doc["scenes"][0]["media"]["url"] = fh.name
        try:
            with mock.patch.object(config, "SUPABASE_SERVICE_KEY", ""), \
                    mock.patch.object(config, "STORAGE_BROKER_URL", "https://x/worker-storage"), \
                    mock.patch.object(handler, "_thumbnail", return_value=""), \
                    mock.patch.object(handler, "_preview_proxy", return_value=fh.name), \
                    mock.patch.object(storage, "broker_upload",
                                      side_effect=lambda l, b, obj, *a, **k: f"https://s/{obj}"):
                handler.publish_media(doc, "p1", "video-media", handler.Reporter(""), job_id="j")
        finally:
            os.unlink(fh.name)
        media = doc["scenes"][0]["media"]
        sid = doc["scenes"][0]["id"]
        self.assertEqual(media["previewUrl"], f"https://s/projects/p1/preview/{sid}.mp4")
        self.assertEqual(media["previewStorage"]["path"], f"projects/p1/preview/{sid}.mp4")
        self.assertTrue(media["url"].endswith(f"/media/{sid}.mp4"))  # the render keeps the full clip

    def test_a_still_gets_no_preview_copy(self):
        import handler
        self.assertEqual(handler._preview_proxy("/w/photo.jpg", "/w", "s1"), "")

    def test_build_renders_from_local_files_then_saves_the_clips(self):
        import handler
        order = []
        doc = build_doc(n=2, seconds=3.0)

        def fake_render(d, inp, work, report):
            order.append("render")
            self.assertIsNot(d, doc)  # render gets its own copy to rewrite
            return {"video_url": "https://v", "object_path": "p", "bucket": "renders", "duration": 6}

        with mock.patch.object(handler, "do_plan", return_value=doc), \
                mock.patch.object(handler, "do_render", side_effect=fake_render), \
                mock.patch.object(handler, "publish_media",
                                  side_effect=lambda *a, **k: order.append("save")), \
                mock.patch.object(handler.storage, "patch_project"):
            out = handler.handler({"id": "job-1", "input": {"action": "build", "project_id": "p1"}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(order, ["render", "save"])

    def test_a_scene_with_no_media_borrows_a_neighbour_instead_of_failing(self):
        # A real job lost twenty minutes of sourcing this way: scene 6 of 17
        # had no media, do_render raised, and the exception unwound past the
        # point where the work directory (every other scene's clip) is
        # deleted. build must never let one hard beat destroy the rest.
        import handler
        doc = build_doc(n=3, seconds=3.0)
        doc["scenes"][1]["media"] = {"type": "color", "url": "", "source": "none"}
        doc["scenes"][1]["reviewRequired"] = True
        doc["scenes"][1]["reviewReason"] = "No media found for this beat"
        seen = {}

        def fake_render(d, inp, work, report):
            seen["doc"] = d
            return {"video_url": "https://v", "object_path": "p", "bucket": "renders", "duration": 6}

        with mock.patch.object(handler, "do_plan", return_value=doc), \
                mock.patch.object(handler, "do_render", side_effect=fake_render), \
                mock.patch.object(handler, "publish_media"), \
                mock.patch.object(handler.storage, "patch_project"):
            out = handler.handler({"id": "job-1", "input": {"action": "build", "project_id": "p1"}})
        self.assertTrue(out["ok"], out)
        # The render copy was healed...
        self.assertNotEqual(seen["doc"]["scenes"][1]["media"]["type"], "color")
        self.assertTrue(seen["doc"]["scenes"][1]["reviewRequired"])
        # ...but the saved timeline still tells the truth, so the editor's
        # readiness panel and Find-footage flow see the real gap.
        self.assertEqual(doc["scenes"][1]["media"]["type"], "color")

    def test_a_video_with_nothing_sourced_anywhere_gets_text_cards_not_black(self):
        # No neighbour anywhere has real media to borrow. Never a black hole:
        # every scene gets a text-card overlay of its own narration line,
        # VidRush's own fallback for an unfindable beat.
        import handler
        doc = build_doc(n=2, seconds=3.0)
        doc["scenes"][0]["text"] = "The river simply stopped arriving."
        doc["scenes"][1]["text"] = "Nobody was told for eleven days."
        for s in doc["scenes"]:
            s["media"] = {"type": "color", "url": "", "source": "none"}
        cards = handler._fill_missing_media(doc)
        self.assertEqual(cards, 2)
        self.assertTrue(all(s["media"]["type"] == "color" for s in doc["scenes"]))
        overlays = doc["overlays"]
        self.assertEqual(len(overlays), 2)
        self.assertTrue(all(o["type"] == "highlight" for o in overlays))
        self.assertEqual(overlays[0]["text"], "The river simply stopped arriving.")
        self.assertEqual((overlays[0]["startFrame"], overlays[0]["durationInFrames"]),
                         (doc["scenes"][0]["startFrame"], doc["scenes"][0]["durationInFrames"]))
        self.assertTrue(all(s["reviewRequired"] for s in doc["scenes"]))

    def test_a_run_of_empty_scenes_does_not_collapse_onto_one_neighbour(self):
        # A real job had several empty scenes in a row each independently
        # pick their single nearest real neighbour, so all of them piled onto
        # THAT one scene's clip - a visible run of the identical shot,
        # repeated back to back. Reproduced here with one real scene sitting
        # right next to a run of four empty ones and the only other real
        # scene far away: "always nearest" would put all four on the close
        # one every time. Spreading by least-borrowed-first must not.
        import handler
        doc = build_doc(n=101, seconds=3.0)
        for i, s in enumerate(doc["scenes"]):
            s["media"] = ({"type": "video", "source": "youtube", "url": f"https://x/real{i}.mp4"}
                          if i in (0, 100) else {"type": "color", "url": "", "source": "none"})
        patched = handler._fill_missing_media(doc)
        self.assertEqual(patched, 99)
        urls = [doc["scenes"][i]["media"]["url"] for i in range(1, 5)]  # right next to scene 0
        self.assertLessEqual(urls.count("https://x/real0.mp4"), 2)
        self.assertGreaterEqual(urls.count("https://x/real100.mp4"), 2)


class VisionFailuresAreReported(unittest.TestCase):
    """
    A failed vision call keeps the clip unjudged, which looks normal in the
    timeline. On RunPod every call failed and nothing said so; the job result
    now carries the reasons.
    """

    def _reply(self, status, body):
        r = mock.Mock(status_code=status)
        r.json.return_value = body
        return r

    def setUp(self):
        from src import vision
        self.vision = vision
        vision.reset()
        self.patches = [mock.patch.object(config, "VISION_API_KEY", "k"),
                        mock.patch.object(config, "VISION_ENABLED", True),
                        mock.patch.object(config, "VISION_FALLBACK_MODELS", ["backup"]),
                        mock.patch.object(config, "VISION_RETRY_WAIT", 0)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.vision.reset()

    def test_a_kie_wrapper_error_is_recorded(self):
        with mock.patch.object(self.vision.requests, "post", return_value=self._reply(
                200, {"code": 500, "msg": "server exception"})):
            text, model = self.vision._ask([], 100)
        self.assertIsNone(text)
        stats = self.vision.stats()
        self.assertEqual(stats["failures"], 4)  # main model and fallback, each retried once
        self.assertIn("code 500: server exception", stats["recentErrors"][0])

    def test_a_transient_server_error_is_retried_on_the_same_model(self):
        replies = [self._reply(200, {"code": 500, "msg": "try again later"}),
                   self._reply(200, {"choices": [{"message": {"content": '{"ok": 1}'}}]})]
        with mock.patch.object(self.vision.requests, "post", side_effect=replies):
            text, model = self.vision._ask([], 100)
        self.assertEqual((text, model), ('{"ok": 1}', config.VISION_MODEL))

    def test_a_refusal_is_not_retried(self):
        replies = [self._reply(200, {"code": 422, "msg": "bad request"}),
                   self._reply(200, {"choices": [{"message": {"content": '{"ok": 1}'}}]})]
        with mock.patch.object(self.vision.requests, "post", side_effect=replies):
            text, model = self.vision._ask([], 100)
        self.assertEqual(model, "backup")

    def test_running_out_of_credits_stops_all_ai_calls_for_the_job(self):
        calls = []

        def post(*a, **k):
            calls.append(1)
            return self._reply(200, {"code": 402, "msg": "Credits insufficient : top up"})

        with mock.patch.object(self.vision.requests, "post", side_effect=post):
            self.assertEqual(self.vision._ask([], 100), (None, ""))
            self.assertEqual(len(calls), 1)            # no retry, no fallback
            self.assertTrue(self.vision.out_of_credits())
            self.assertFalse(self.vision.enabled())    # later clips skip vision fast
            self.assertEqual(self.vision._ask([], 100), (None, ""))
            self.assertEqual(len(calls), 1)
        self.assertTrue(self.vision.stats()["outOfCredits"])
        with mock.patch.object(config, "DIRECTOR_MODEL", "m"), \
                mock.patch.object(director.requests, "post") as dpost:
            self.assertIsNone(director._chat_json("sys", {}))
            dpost.assert_not_called()
        self.vision.reset()
        self.assertFalse(self.vision.out_of_credits())

    def test_a_clip_no_model_could_judge_is_counted_and_flagged(self):
        with mock.patch.object(self.vision.os.path, "exists", return_value=True), \
                mock.patch.object(self.vision, "_fingerprint", return_value="fp"), \
                mock.patch.object(self.vision, "sample_frames", return_value=["AAAA"]), \
                mock.patch.object(self.vision, "_ask", return_value=(None, "")):
            verdict = self.vision.judge("/w/a.mp4", "flood", "")
        self.assertIsNone(verdict)
        self.assertEqual(self.vision.stats()["unjudged"], 1)
        a = MediaAsset(kind="video", source="youtube", url="q").apply_verdict(None, "flood")
        self.assertTrue(a.review_required)
        self.assertIn("Not checked by the vision AI", a.review_reason)

    def test_an_empty_answer_falls_through_to_the_fallback(self):
        replies = [self._reply(200, {"choices": [{"message": {"content": ""}}]}),
                   self._reply(200, {"choices": [{"message": {"content": '{"ok": 1}'}}]})]
        with mock.patch.object(self.vision.requests, "post", side_effect=replies):
            text, model = self.vision._ask([], 100)
        self.assertEqual((text, model), ('{"ok": 1}', "backup"))
        self.assertIn("empty answer", self.vision.stats()["recentErrors"][0])


class TransitionsAndEffects(unittest.TestCase):
    """Scene entrances and per-clip effects: contract + placement rules."""

    def _ts_union(self, name):
        with open(os.path.join(REMOTION, "types.ts"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"export type %s\s*=(.*?);" % name, src, re.S)
        self.assertIsNotNone(block, f"{name} not found in types.ts")
        return set(re.findall(r'"([a-z-]+)"', block.group(1)))

    def test_python_and_types_agree_on_transitions(self):
        self.assertEqual(timeline.TRANSITIONS, self._ts_union("SceneTransition"))

    def test_python_and_types_agree_on_effects(self):
        self.assertEqual(timeline.EFFECTS, self._ts_union("SceneEffect"))

    def test_most_cuts_are_hard_cuts(self):
        shots = [{"subject": "Lake Mead" if i < 10 else "Hoover Dam"} for i in range(20)]
        plan = timeline.plan_transitions(shots)
        self.assertEqual(plan[0], "none")
        self.assertLessEqual(sum(1 for p in plan if p != "none"), 5)

    def test_a_subject_change_gets_a_transition(self):
        shots = [{"subject": "Lake Mead"}] * 5 + [{"subject": "Hoover Dam"}] * 5
        plan = timeline.plan_transitions(shots)
        self.assertNotEqual(plan[5], "none")

    def test_transitions_are_never_back_to_back(self):
        shots = [{"subject": f"place {i}"} for i in range(30)]
        plan = timeline.plan_transitions(shots)
        idx = [i for i, p in enumerate(plan) if p != "none"]
        self.assertTrue(all(b - a >= 3 for a, b in zip(idx, idx[1:])))

    def test_every_choice_is_in_the_contract(self):
        shots = [{"subject": f"s{i // 3}", "overlay": {"type": "chapter"} if i % 7 == 0 else None}
                 for i in range(40)]
        for p in timeline.plan_transitions(shots):
            self.assertIn(p, timeline.TRANSITIONS)


class Treatments(unittest.TestCase):
    """
    The grade is chosen from what the beat is talking about.

    A shared base makes borrowed clips cut together as one film; the era grades
    are how the picture says "this is the past" without the narration doing it.
    """

    def test_a_spoken_decade_reads_as_archival(self):
        self.assertEqual(
            director.pick_treatment("He acted through the 1990s and 2000s."),
            "archival")

    def test_a_recent_year_keeps_the_base_grade(self):
        # Base grade is "none" now: modern footage shown as shot. The old
        # "film" default added a vignette that made real renders look dark.
        self.assertEqual(
            director.pick_treatment("On a Sunday night in November of 2024."),
            config.SCENE_TREATMENT)
        self.assertEqual(config.SCENE_TREATMENT, "none")

    def test_the_older_year_wins_when_a_beat_spans_eras(self):
        # "from 1996 to 2021" is a beat about the past, not the present.
        self.assertEqual(
            director.pick_treatment("From 1996 to 2021 the ranch changed hands."),
            "archival")

    def test_cues_work_without_any_year(self):
        self.assertEqual(
            director.pick_treatment("Archive footage shows the ranch."), "archival")
        self.assertEqual(
            director.pick_treatment("Back then nobody thought it would work."),
            "vintage")

    def test_every_choice_is_one_the_renderer_knows(self):
        samples = ["In 1975 it began.", "Today it ended.", "Back then.",
                   "Archival newsreel.", "Nothing notable here at all."]
        for text in samples:
            self.assertIn(director.pick_treatment(text), director.TREATMENTS)


# --------------------------------------------------------------------------- #
# Pacing — the VidRush editing signature
# --------------------------------------------------------------------------- #

class Pacing(unittest.TestCase):
    """
    Cut rate is the editing signature, so it is pinned by a test.

    The target changed once already. It was 16.8-21.8 cuts/min from four
    VidRush renders; it is now ~8.7 cuts/min with a median 7.0s clip,
    measured from a finished GoMotion project (197 clips over 22:59, 92% of
    them inside a 6.5-7.5s band). Both numbers came from real output — they
    are different house styles, and the slower one is the one that was
    judged good. The band here is deliberately wide because narration does
    not divide evenly into a grid.
    """

    NARRATION = (
        "The river was the only thing holding the valley together. "
        "For eleven years it ran high, and nobody thought to measure it. "
        "Then in the spring of 2019 the wells began to fail. "
        "First the outer farms, then the town itself. "
        "By August the reservoir was down to a quarter of its depth. "
        "The engineers said it would refill. It did not refill. "
        "What happened next is the part nobody reported. "
    ) * 4

    def test_cut_rate_matches_the_reference_band(self):
        # VidRush, measured on four of their exports: 13.6-16.5 cuts/min for
        # the three narrated-story videos (the fourth, all long drone shots,
        # ran 6.9). A little margin either side.
        segments = segment_words(words_from(self.NARRATION))
        duration = segments[-1].end
        cpm = len(segments) / (duration / 60)
        self.assertGreaterEqual(cpm, 11.0, f"too slow: {cpm:.1f} cuts/min")
        self.assertLessEqual(cpm, 19.0, f"too fast: {cpm:.1f} cuts/min")

    def test_clips_cluster_around_the_target_length(self):
        """VidRush's median shot is 3.3-3.7 s; aim near the target."""
        segments = segment_words(words_from(self.NARRATION))
        import statistics
        median = statistics.median([s.duration for s in segments])
        self.assertAlmostEqual(median, config.TARGET_SCENE_SECONDS, delta=2.0,
                               msg=f"median clip {median:.2f}s")

    def test_pacing_is_still_tunable_back_to_the_faster_style(self):
        """The VidRush cutting must remain reachable, not be designed out."""
        import importlib
        from src import config as cfg
        saved = (cfg.MIN_SCENE_SECONDS, cfg.TARGET_SCENE_SECONDS, cfg.MAX_SCENE_SECONDS)
        cfg.MIN_SCENE_SECONDS, cfg.TARGET_SCENE_SECONDS, cfg.MAX_SCENE_SECONDS = 1.4, 2.6, 5.0
        try:
            segments = segment_words(words_from(self.NARRATION))
            cpm = len(segments) / (segments[-1].end / 60)
            self.assertGreater(cpm, 14.0, f"fast style unreachable: {cpm:.1f}")
        finally:
            (cfg.MIN_SCENE_SECONDS, cfg.TARGET_SCENE_SECONDS,
             cfg.MAX_SCENE_SECONDS) = saved

    def test_no_scene_is_shorter_than_the_floor(self):
        segments = segment_words(words_from(self.NARRATION))
        # The last segment is whatever is left over, so it is exempt.
        for s in segments[:-1]:
            self.assertGreaterEqual(round(s.duration, 3), config.MIN_SCENE_SECONDS - 0.001)

    def test_no_scene_runs_past_the_cap(self):
        segments = segment_words(words_from(self.NARRATION))
        for s in segments:
            self.assertLessEqual(s.duration, config.MAX_SCENE_SECONDS + 0.6)

    def test_segments_are_contiguous_and_ordered(self):
        segments = segment_words(words_from(self.NARRATION))
        for a, b in zip(segments, segments[1:]):
            self.assertLessEqual(a.end, b.start + 1e-6)

    def test_empty_audio_produces_no_segments(self):
        self.assertEqual(segment_words([]), [])

    def test_script_alignment_keeps_timing_and_replaces_text(self):
        segments = segment_words(words_from("Perera lost seven point four meters of water."))
        before = [(s.start, s.end) for s in segments]
        aligned = align_to_script(segments, "Pereira lost 7.4 metres of water.")
        self.assertEqual([(s.start, s.end) for s in aligned], before)
        self.assertIn("Pereira", " ".join(s.text for s in aligned))

    def test_keywords_drop_filler_and_keep_subjects(self):
        q = keywords_for(seg("and then the Colombia earthquake struck the valley", 0, 3))
        self.assertIn("Colombia", q)
        self.assertNotIn(" the ", f" {q} ")


# --------------------------------------------------------------------------- #
# Timeline construction
# --------------------------------------------------------------------------- #

class TimelineBuild(unittest.TestCase):

    def test_visual_track_tiles_the_narration_exactly(self):
        doc = build_doc(n=7, seconds=2.8)
        self.assertEqual(doc["scenes"][0]["startFrame"], 0)
        cursor = 0
        for s in doc["scenes"]:
            self.assertEqual(s["startFrame"], cursor)
            cursor += s["durationInFrames"]
        self.assertEqual(cursor, doc["durationInFrames"])

    def test_narration_audio_is_present(self):
        # The v2 draft shipped `"audio": {}`, which renders a silent video.
        doc = build_doc()
        self.assertTrue(doc["audio"]["url"])

    def test_first_scene_starts_at_frame_zero_even_when_speech_does_not(self):
        segments = [seg("A late start.", 1.7, 4.0), seg("And the rest.", 4.0, 7.0)]
        shots = [{"query": "a", "visualType": "footage", "overlay": None}] * 2
        doc = timeline.build(segments, shots, [asset(), asset()],
                             audio_url="file:///vo.mp3", audio_duration=7.0, inp={})
        self.assertEqual(doc["scenes"][0]["startFrame"], 0)
        timeline.validate(doc)

    def test_tiny_segments_still_get_a_frame_each(self):
        segments = [seg(f"x{i}", i * 0.02, (i + 1) * 0.02) for i in range(20)]
        shots = [{"query": "x", "visualType": "footage", "overlay": None}] * 20
        doc = timeline.build(segments, shots, [asset()] * 20,
                             audio_url="file:///vo.mp3", audio_duration=1.0, inp={})
        self.assertTrue(all(s["durationInFrames"] >= 1 for s in doc["scenes"]))
        timeline.validate(doc)

    def test_more_scenes_than_frames_is_a_clear_error(self):
        segments = [seg(f"x{i}", i, i + 1) for i in range(50)]
        with self.assertRaisesRegex(ValueError, "will not fit"):
            timeline.build(segments, [{"query": "x", "visualType": "footage",
                                       "overlay": None}] * 50,
                           [asset()] * 50, audio_url="file:///vo.mp3",
                           audio_duration=1.0, inp={})

    def test_images_get_ken_burns_and_video_does_not(self):
        segments, shots, _ = simple_plan(4)
        assets = [asset(kind="image", source="wikimedia"), asset(),
                  asset(kind="image", source="generated"), asset()]
        doc = timeline.build(segments, shots, assets, audio_url="file:///vo.mp3",
                             audio_duration=12.0, inp={})
        motions = [s["motion"] for s in doc["scenes"]]
        self.assertEqual(motions[1], "none")
        self.assertEqual(motions[3], "none")
        self.assertIn(motions[0], timeline._IMAGE_MOTIONS)
        self.assertIn(motions[2], timeline._IMAGE_MOTIONS)

    def test_missing_media_is_counted_and_flagged(self):
        segments, shots, assets = simple_plan(3)
        assets[1] = None
        doc = timeline.build(segments, shots, assets, audio_url="file:///vo.mp3",
                             audio_duration=9.0, inp={})
        self.assertEqual(doc["meta"]["scenesWithoutMedia"], 1)
        self.assertTrue(doc["scenes"][1]["reviewRequired"])
        self.assertTrue(any("no media" in w for w in doc["meta"]["warnings"]))

    def test_generated_media_is_surfaced_for_review(self):
        segments, shots, assets = simple_plan(2)
        assets[0] = asset(kind="image", source="generated", review_required=True,
                          review_reason="Generated illustration")
        doc = timeline.build(segments, shots, assets, audio_url="file:///vo.mp3",
                             audio_duration=6.0, inp={})
        self.assertEqual(doc["meta"]["generatedScenes"], 1)
        self.assertEqual(doc["meta"]["scenesNeedingReview"], 1)

    def test_data_graphics_hold_longer_than_the_beat_that_triggered_them(self):
        segments, shots, assets = simple_plan(8, seconds=2.5)
        shots[1]["overlay"] = {"type": "bar-chart", "text": "t",
                               "items": [{"label": "a", "value": 1},
                                         {"label": "b", "value": 2}]}
        doc = timeline.build(segments, shots, assets, audio_url="file:///vo.mp3",
                             audio_duration=20.0, inp={})
        chart = doc["overlays"][0]
        beat_frames = doc["scenes"][1]["durationInFrames"]
        self.assertGreater(chart["durationInFrames"], beat_frames)
        timeline.validate(doc)

    def test_overlays_never_run_past_the_end(self):
        segments, shots, assets = simple_plan(3, seconds=1.6)
        shots[2]["overlay"] = {"type": "map", "text": "x",
                               "locations": [{"label": "L", "lat": 1.0, "lon": 2.0}]}
        doc = timeline.build(segments, shots, assets, audio_url="file:///vo.mp3",
                             audio_duration=4.8, inp={})
        for ov in doc["overlays"]:
            self.assertLessEqual(ov["startFrame"] + ov["durationInFrames"],
                                 doc["durationInFrames"])
        timeline.validate(doc)

    def test_document_is_json_serialisable(self):
        # It crosses a subprocess boundary as --props and lands in Postgres.
        json.dumps(build_doc())


# --------------------------------------------------------------------------- #
# Validation — the gate in front of a paid render
# --------------------------------------------------------------------------- #

class Validation(unittest.TestCase):

    def test_a_well_formed_document_passes(self):
        timeline.validate(build_doc())

    def test_silent_document_is_rejected(self):
        doc = build_doc()
        doc["audio"] = {}
        with self.assertRaisesRegex(ValueError, "silent"):
            timeline.validate(doc)

    def test_stock_footage_is_rejected_under_the_no_stock_policy(self):
        doc = build_doc()
        doc["scenes"][1]["media"]["source"] = "pexels"
        with self.assertRaisesRegex(ValueError, "no-stock"):
            timeline.validate(doc, allow_stock=False)
        timeline.validate(doc, allow_stock=True)

    def test_a_gap_in_the_visual_track_is_rejected(self):
        doc = build_doc()
        doc["scenes"][2]["startFrame"] += 3
        with self.assertRaisesRegex(ValueError, "flush"):
            timeline.validate(doc)

    def test_short_visual_track_is_rejected(self):
        doc = build_doc()
        doc["durationInFrames"] += 40
        with self.assertRaisesRegex(ValueError, "cover it exactly"):
            timeline.validate(doc)

    def test_odd_dimensions_are_rejected(self):
        doc = build_doc()
        doc["width"] = 1921
        with self.assertRaisesRegex(ValueError, "even"):
            timeline.validate(doc)

    def test_missing_media_blocks_render_but_not_planning(self):
        segments, shots, assets = simple_plan(3)
        assets[1] = None
        doc = timeline.build(segments, shots, assets, audio_url="file:///vo.mp3",
                             audio_duration=9.0, inp={})
        timeline.validate(doc, require_media=False)
        with self.assertRaisesRegex(ValueError, "needs media"):
            timeline.validate(doc, require_media=True)

    def test_booleans_are_not_accepted_as_frame_counts(self):
        # bool subclasses int; True would otherwise validate as frame 1.
        doc = build_doc()
        doc["scenes"][0]["durationInFrames"] = True
        with self.assertRaises(ValueError):
            timeline.validate(doc)

    def test_map_without_coordinates_is_rejected(self):
        doc = build_doc()
        doc["overlays"] = [{"type": "map", "text": "x", "startFrame": 0,
                            "durationInFrames": 30, "locations": []}]
        with self.assertRaisesRegex(ValueError, "verified location"):
            timeline.validate(doc)

    def test_out_of_range_coordinates_are_rejected(self):
        doc = build_doc()
        doc["overlays"] = [{"type": "map", "text": "x", "startFrame": 0,
                            "durationInFrames": 30,
                            "locations": [{"label": "L", "lat": 99.0, "lon": 0.0}]}]
        with self.assertRaisesRegex(ValueError, "out of range"):
            timeline.validate(doc)

    def test_non_finite_chart_values_are_rejected(self):
        doc = build_doc()
        doc["overlays"] = [{"type": "bar-chart", "text": "x", "startFrame": 0,
                            "durationInFrames": 30,
                            "items": [{"label": "a", "value": float("inf")},
                                      {"label": "b", "value": 2}]}]
        with self.assertRaisesRegex(ValueError, "finite"):
            timeline.validate(doc)

    def test_unknown_template_is_rejected(self):
        doc = build_doc()
        doc["overlays"] = [{"type": "hologram", "text": "x", "startFrame": 0,
                            "durationInFrames": 30}]
        with self.assertRaisesRegex(ValueError, "unknown animation template"):
            timeline.validate(doc)

    def test_split_needs_two_media(self):
        doc = build_doc()
        doc["overlays"] = [{"type": "split", "text": "", "startFrame": 0,
                            "durationInFrames": 30, "media": [{"url": "a"}]}]
        with self.assertRaisesRegex(ValueError, "two media"):
            timeline.validate(doc)

    def test_garbage_input_does_not_crash_the_validator(self):
        for bad in (None, [], "timeline", 42, {"fps": "thirty"}):
            with self.assertRaises(ValueError):
                timeline.validate(bad)


# --------------------------------------------------------------------------- #
# Director
# --------------------------------------------------------------------------- #

class DirectorRules(unittest.TestCase):

    def test_every_beat_gets_a_shot_without_an_api_key(self):
        segments = [seg(f"Sentence number {i} about the valley.", i * 3, i * 3 + 3)
                    for i in range(6)]
        # The name of this test is its precondition, so assert it rather than
        # inheriting it from the machine: config now fills unset variables from
        # a local .env, so a developer with a real key would otherwise silently
        # be testing the configured path.
        with mock.patch.object(config, "DIRECTOR_API_KEY", ""),                 mock.patch.object(config, "DIRECTOR_API_BASE", ""),                 mock.patch.object(config, "DIRECTOR_MODEL", ""):
            shots, kind, warnings = director.plan(segments, title="Dry Valley",
                                                  allow_maps=False)
        self.assertEqual(len(shots), len(segments))
        self.assertEqual(kind, "rules")
        self.assertTrue(all(s["query"] for s in shots))
        self.assertTrue(any("not configured" in w for w in warnings))

    def test_project_title_is_folded_into_every_query(self):
        segments = [seg("The river rose again overnight.", 0, 3)]
        shots, _, _ = director.plan(segments, title="Cauca Valley", allow_maps=False)
        self.assertIn("Cauca", shots[0]["query"])

    def test_numbers_become_a_callout(self):
        segments = [seg("Opening line about the town.", 0, 3),
                    seg("Roughly 12,000 people were displaced that week.", 3, 6)]
        shots, _, _ = director.plan(segments, title="", allow_maps=False)
        self.assertEqual(shots[1]["overlay"]["type"], "callout")

    def test_a_question_becomes_a_typewriter_line(self):
        segments = [seg("Opening line about the town.", 0, 3),
                    seg("So where did all of the water actually go?", 30, 33)]
        shots, _, _ = director.plan(segments, title="", allow_maps=False)
        self.assertEqual(shots[1]["overlay"]["type"], "typewriter")

    def test_overlays_are_thinned_so_they_do_not_crowd(self):
        segments = [seg(f"Exactly {i * 1000} people were counted here.", i * 2.0,
                        i * 2.0 + 2.0) for i in range(12)]
        shots, _, _ = director.plan(segments, title="", allow_maps=False)
        starts = [segments[i].start for i, s in enumerate(shots) if s["overlay"]]
        for a, b in zip(starts, starts[1:]):
            self.assertGreaterEqual(b - a, director.MIN_OVERLAY_GAP_SECONDS - 2.1)

    def test_maps_are_dropped_when_disabled(self):
        segments = [seg("The convoy stopped in San Jose del Palmar that night.", 0, 4)]
        shots, _, _ = director.plan(segments, title="", allow_maps=False)
        self.assertNotEqual((shots[0]["overlay"] or {}).get("type"), "map")

    def test_unverifiable_place_never_becomes_a_map(self):
        """The gazetteer decides, not the text. A stubbed miss drops the map."""
        original = geocode.resolve_all
        geocode.resolve_all = lambda names: []
        try:
            segments = [seg("They regrouped in Wakanda Prime before dawn.", 0, 4)]
            shots, _, warnings = director.plan(segments, title="", allow_maps=True)
            self.assertNotEqual((shots[0]["overlay"] or {}).get("type"), "map")
        finally:
            geocode.resolve_all = original

    def test_verified_place_becomes_a_map_labelled_by_the_gazetteer(self):
        original = geocode.resolve_all
        geocode.resolve_all = lambda names: [
            {"label": "San José del Palmar, Colombia", "lat": 4.8963,
             "lon": -76.2283, "kind": "town"}]
        try:
            segments = [seg("The convoy stopped in San Jose del Palmar that night.", 0, 4)]
            shots, _, _ = director.plan(segments, title="", allow_maps=True)
            overlay = shots[0]["overlay"]
            self.assertEqual(overlay["type"], "map")
            # The label drawn is the gazetteer's, not the narration's spelling.
            self.assertEqual(overlay["text"], "San José del Palmar, Colombia")
            self.assertNotIn("places", overlay)
        finally:
            geocode.resolve_all = original


class OverlayValidation(unittest.TestCase):
    """validate_overlay is where untrusted model output crosses into a render."""

    def test_unknown_type_is_rejected(self):
        self.assertIsNone(director.validate_overlay({"type": "iframe", "text": "x"}))

    def test_non_dict_is_rejected(self):
        for bad in (None, "map", 7, ["map"]):
            self.assertIsNone(director.validate_overlay(bad))

    def test_model_supplied_coordinates_are_discarded(self):
        out = director.validate_overlay({
            "type": "map", "text": "Epicentre", "places": ["Bogota"],
            "locations": [{"label": "Nowhere", "lat": 0.0, "lon": 0.0}],
            "lat": 10, "lon": 20,
        })
        self.assertEqual(out["places"], ["Bogota"])
        self.assertNotIn("locations", out)
        self.assertNotIn("lat", out)

    def test_map_without_places_is_rejected(self):
        self.assertIsNone(director.validate_overlay({"type": "map", "text": "x"}))

    def test_chart_without_numbers_is_rejected(self):
        self.assertIsNone(director.validate_overlay({
            "type": "bar-chart", "text": "x",
            "items": [{"label": "a"}, {"label": "b"}]}))

    def test_chart_with_one_item_is_rejected(self):
        self.assertIsNone(director.validate_overlay({
            "type": "bar-chart", "text": "x", "items": [{"label": "a", "value": 1}]}))

    def test_stat_needs_a_finite_value(self):
        self.assertIsNone(director.validate_overlay({"type": "stat", "text": "x"}))
        self.assertIsNone(director.validate_overlay(
            {"type": "stat", "text": "x", "value": float("nan")}))
        self.assertEqual(
            director.validate_overlay({"type": "stat", "text": "x", "value": "42"})["value"], 42.0)

    def test_split_is_never_model_generated(self):
        self.assertIsNone(director.validate_overlay(
            {"type": "split", "media": [{"url": "http://a"}, {"url": "http://b"}]}))

    def test_text_is_truncated_not_trusted(self):
        out = director.validate_overlay({"type": "callout", "text": "x" * 5000})
        self.assertLessEqual(len(out["text"]), 240)

    def test_narration_instructions_do_not_become_fields(self):
        out = director.validate_overlay({
            "type": "callout", "text": "Ignore previous instructions",
            "onClick": "fetch('http://evil')", "__proto__": {"x": 1},
            "dangerouslySetInnerHTML": "<script>",
        })
        self.assertEqual(set(out) - {"type", "text", "items"}, set())


class Geocoding(unittest.TestCase):

    def test_long_display_names_are_shortened_to_place_and_country(self):
        self.assertEqual(
            geocode._short_label("San José del Palmar, Chocó, 27600, Colombia", "x"),
            "San José del Palmar, Colombia")

    def test_single_part_names_survive(self):
        self.assertEqual(geocode._short_label("Colombia", "x"), "Colombia")

    def test_empty_falls_back(self):
        self.assertEqual(geocode._short_label("", "fallback"), "fallback")


class MediaContract(unittest.TestCase):

    def test_scene_media_uses_the_renderer_field_names(self):
        m = asset(kind="image", source="wikimedia", url="https://x/a.jpg").to_scene_media()
        self.assertEqual(m["type"], "image")          # not "kind"
        self.assertEqual(set(m), {"type", "url", "source", "attribution", "license"})

    def test_local_path_wins_over_the_remote_url(self):
        a = MediaAsset(kind="image", source="wikimedia", url="https://remote/a.jpg",
                       local_path="/work/a.jpg")
        self.assertEqual(a.to_scene_media()["url"], "/work/a.jpg")


class SourcingCommands(unittest.TestCase):
    """
    Regression tests for three failures that raised nothing at all.

    Each one made a whole source silently contribute zero assets, which looks
    exactly like "no good match for that query" from the outside.
    """

    def _captured_yt_cmd(self, **kwargs):
        seen = {}

        class Result:
            returncode, stdout, stderr = 0, "", ""

        def fake_run(cmd, **_):
            seen["cmd"] = cmd
            return Result()

        original = media.subprocess.run
        media.subprocess.run = fake_run
        try:
            media.youtube_clip("colombia earthquake", "/tmp/x", seconds=4.0,
                               b_roll_intent=False, **kwargs)
        finally:
            media.subprocess.run = original
        return seen["cmd"]

    def test_cc_search_does_not_use_ytsearch(self):
        # yt-dlp's flat search extractor reports license=NA for every hit, so
        # a Creative Commons match-filter over ytsearch rejects everything and
        # the YouTube source returns nothing, ever.
        cmd = self._captured_yt_cmd(require_cc=True)
        target = cmd[1]
        self.assertNotIn("ytsearch", target)
        self.assertIn("youtube.com/results", target)
        self.assertIn("sp=EgIwAQ%3D%3D", target)   # YouTube's CC search filter

    def test_plain_search_still_uses_ytsearch(self):
        cmd = self._captured_yt_cmd(require_cc=False)
        self.assertTrue(cmd[1].startswith("ytsearch"))

    def test_licence_filter_is_absent_when_not_required(self):
        cmd = self._captured_yt_cmd(require_cc=False)
        self.assertNotIn("--match-filter", cmd)

    def test_shape_is_judged_by_score_not_a_match_filter(self):
        """
        "width > height" as a match-filter killed every candidate: a filter
        compares a field to a literal, so `height` parsed as a string. Shape
        is now judged from metadata that was fetched anyway.
        """
        vertical = media._score_candidate("Lake Powell", 300, 0.56, 4)
        wide = media._score_candidate("Lake Powell", 300, 1.78, 4)
        self.assertLess(vertical, wide)

    def test_talking_heads_rank_below_footage(self):
        """The first real run put a podcast clip where a boat ramp belonged."""
        head = media._score_candidate("Lake Powell Podcast Episode 12", 300, 1.78, 4)
        broll = media._score_candidate("Lake Powell drone aerial 4K", 300, 1.78, 4)
        self.assertLess(head, broll)

    def test_downloads_identify_themselves(self):
        # Wikimedia 403s the default python-requests agent, so without this
        # every Commons image failed to download and the best source of real
        # named subjects never contributed anything.
        seen = {}

        class Response:
            status_code = 200
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=0): return []
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_get(url, **kw):
            seen.update(kw)
            return Response()

        original = storage.requests.get
        storage.requests.get = fake_get
        try:
            storage.download("https://commons.example/x.jpg",
                             os.path.join(ROOT, "out", "_t", "x.jpg"))
        finally:
            storage.requests.get = original
        agent = (seen.get("headers") or {}).get("User-Agent", "")
        self.assertIn("ThumbGenius", agent)
        self.assertNotIn("python-requests", agent)


class PresignedUpload(unittest.TestCase):
    """
    The zero-secret upload path the app's edge function expects.

    It pre-signs a destination and hands the worker a one-object URL, so the
    worker holds no Supabase credentials. Getting the routing wrong means
    either a needless credential on the endpoint or a render that uploads
    nowhere.
    """

    def _fake_put(self, status=200, text=""):
        seen = {}

        class Response:
            status_code = status

            def __init__(self):
                self.text = text

        def put(url, data=None, timeout=None, headers=None):
            seen["url"] = url
            seen["headers"] = headers or {}
            seen["read"] = len(data.read()) if hasattr(data, "read") else 0
            return Response()

        return put, seen

    def test_uploads_to_the_signed_url_with_a_video_content_type(self):
        tmp = os.path.join(ROOT, "out", "_t_upload.mp4")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(bytes(1) * 2048)
        put, seen = self._fake_put()
        original = storage.requests.put
        storage.requests.put = put
        try:
            size = storage.upload_to_signed_url(tmp, "https://sb/upload?token=x")
        finally:
            storage.requests.put = original
            os.remove(tmp)
        self.assertEqual(size, 2048)
        self.assertEqual(seen["url"], "https://sb/upload?token=x")
        self.assertEqual(seen["headers"].get("Content-Type"), "video/mp4")
        self.assertEqual(seen["read"], 2048)

    def test_a_rejected_upload_raises_rather_than_reporting_success(self):
        tmp = os.path.join(ROOT, "out", "_t_upload2.mp4")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(b"x")
        put, _ = self._fake_put(status=403, text="signature expired")
        original = storage.requests.put
        storage.requests.put = put
        try:
            with self.assertRaisesRegex(storage.StorageError, "403"):
                storage.upload_to_signed_url(tmp, "https://sb/upload")
        finally:
            storage.requests.put = original
            os.remove(tmp)

    def test_signed_url_path_needs_no_service_key(self):
        """do_render must not reach for the service key when handed a URL."""
        import handler
        doc = build_doc()
        calls = {"signed": 0, "service": 0}
        out_dir = os.path.join(ROOT, "out", "_t_render")
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, "final.mp4")
        with open(out_file, "wb") as f:
            f.write(bytes(1) * 64)

        originals = (handler.renderer.render, storage.upload_to_signed_url,
                     storage.upload_to_supabase)
        handler.renderer.render = lambda *a, **k: out_file
        storage.upload_to_signed_url = lambda p, u, **k: calls.__setitem__("signed", 1) or 64
        storage.upload_to_supabase = lambda *a, **k: calls.__setitem__("service", 1) or ""
        try:
            res = handler.do_render(
                doc,
                {"upload_url": "https://sb/upload?token=x",
                 "public_url": "https://sb/public/videos/a.mp4",
                 "video_path": "a.mp4"},
                out_dir, handler.Reporter(""))
        finally:
            (handler.renderer.render, storage.upload_to_signed_url,
             storage.upload_to_supabase) = originals

        self.assertEqual(calls["signed"], 1)
        self.assertEqual(calls["service"], 0, "service-key upload must not run")
        self.assertEqual(res["uploadedVia"], "signed_url")
        self.assertEqual(res["video_url"], "https://sb/public/videos/a.mp4")


class ResourceAction(unittest.TestCase):
    """
    Replacing one scene must never move another frame.

    The app validates that scenes tile the narration exactly; if re-sourcing
    nudged any timing, every subsequent scene would desync the voiceover and
    the editor would refuse to render.
    """

    def _run(self, scene_index=1, asset=None, inp_extra=None):
        import handler
        doc = build_doc(n=4, seconds=3.0)
        original = handler.media.source_for_segment
        handler.media.source_for_segment = lambda *a, **k: asset
        try:
            return handler.do_resource(
                {"timeline": doc, "scene_index": scene_index, **(inp_extra or {})},
                os.path.join(ROOT, "out", "_t_res"), handler.Reporter(""))
        finally:
            handler.media.source_for_segment = original

    def test_timing_is_untouched(self):
        before = [(s["startFrame"], s["durationInFrames"]) for s in build_doc(n=4).get("scenes")]
        doc = self._run(asset=asset(kind="image", source="wikimedia",
                                    url="https://x/new.jpg"))
        after = [(s["startFrame"], s["durationInFrames"]) for s in doc["scenes"]]
        self.assertEqual(before, after)
        timeline.validate(doc)

    def test_only_the_named_scene_changes(self):
        doc = self._run(scene_index=2,
                        asset=asset(kind="image", source="wikimedia",
                                    url="https://x/new.jpg"))
        self.assertEqual(doc["scenes"][2]["media"]["url"], "https://x/new.jpg")
        self.assertEqual(doc["scenes"][0]["media"]["url"], "file:///tmp/a.mp4")
        self.assertEqual(doc["scenes"][3]["media"]["url"], "file:///tmp/a.mp4")

    def test_a_still_replacement_gets_ken_burns(self):
        doc = self._run(asset=asset(kind="image", source="wikimedia",
                                    url="https://x/new.jpg"))
        self.assertIn(doc["scenes"][1]["motion"], timeline._IMAGE_MOTIONS)

    def test_generated_replacement_is_flagged_for_review(self):
        doc = self._run(asset=asset(kind="image", source="generated",
                                    url="https://x/g.png", review_required=True,
                                    review_reason="Generated illustration"))
        self.assertTrue(doc["scenes"][1]["reviewRequired"])
        self.assertEqual(doc["meta"]["scenesNeedingReview"], 1)

    def test_out_of_range_index_is_refused(self):
        for bad in (-1, 99, "1", True, None):
            with self.assertRaises(ValueError):
                self._run(scene_index=bad, asset=asset())

    def test_no_match_is_an_error_not_a_blank_scene(self):
        with self.assertRaisesRegex(ValueError, "no usable media"):
            self._run(asset=None)

    def test_replacement_is_matched_against_the_scene_intent(self):
        import handler
        doc = build_doc(n=4, seconds=3.0)
        doc["scenes"][1]["semanticMetadata"] = {"intent": "Aerial of the dry lakebed",
                                                "subject": "Lake Mead"}
        seen = {}
        new = asset(kind="video", source="youtube", url="https://x/new.mp4")
        new.content_description, new.relevance_score = "Cracked mud flats", 0.88

        def fake(*a, **k):
            seen.update(k)
            return new

        original = handler.media.source_for_segment
        handler.media.source_for_segment = fake
        try:
            doc = handler.do_resource({"timeline": doc, "scene_index": 1},
                                      os.path.join(ROOT, "out", "_t_res"),
                                      handler.Reporter(""))
        finally:
            handler.media.source_for_segment = original
        self.assertEqual(seen["intent"], "Aerial of the dry lakebed")
        self.assertEqual(seen["context"], doc["scenes"][1].get("text", ""))
        meta = doc["scenes"][1]["semanticMetadata"]
        # The editor shows these; stale values would describe the old clip.
        self.assertEqual(meta["contentDescription"], "Cracked mud flats")
        self.assertEqual(meta["relevanceScore"], 0.88)
        self.assertEqual(meta["subject"], "Lake Mead")


class NoDuplicateShots(unittest.TestCase):
    """
    No two scenes may show the same visual.

    The first version of source_many cached one downloaded asset per query
    and handed it to every scene that asked the same thing. On a 20-minute
    script that repeats its subject constantly ("the lake", "the ramp"), the
    same clip came back a dozen times.
    """

    def _pool(self, per_query=8):
        """Fake sourcing: each (query, nth) yields a distinct asset."""
        calls = []

        def fake(query, seconds, work_dir, *, visual_type="footage", nth=0,
                 used=None, **kw):
            calls.append((query, nth))
            # Mirrors the real code: the candidate list is rotated by nth and
            # WRAPS, so asking past the end returns an earlier hit rather than
            # nothing. That wrap is exactly what produces duplicates, so the
            # fake has to reproduce it or the test proves nothing.
            a = asset(kind="image", source="wikimedia", query=query,
                      url=f"https://x/{query}-{nth % per_query}.jpg")
            if used and a.identity in used:
                return None
            return a

        return fake, calls

    def _run(self, queries, per_query=8):
        fake, calls = self._pool(per_query)
        original = media.source_for_segment
        media.source_for_segment = fake
        try:
            jobs = [{"index": i, "query": q, "seconds": 3.0, "visual_type": "footage"}
                    for i, q in enumerate(queries)]
            return media.source_many(jobs, "/tmp/x", workers=4), calls
        finally:
            media.source_for_segment = original

    def test_a_repeated_query_gets_different_footage_each_time(self):
        out, _ = self._run(["the lake"] * 6)
        ids = [a.identity for a in out]
        self.assertEqual(len(set(ids)), 6, f"duplicates: {ids}")

    def test_results_stay_in_scene_order(self):
        """Completion order in the pool must not reorder the visual track."""
        out, _ = self._run(["a", "b", "c", "d"])
        self.assertEqual([a.url.split("/")[-1].split("-")[0] for a in out],
                         ["a", "b", "c", "d"])

    def test_the_nth_repeat_reaches_further_down_the_results(self):
        _, calls = self._run(["the lake"] * 4)
        first_pass = sorted(n for q, n in calls if q == "the lake")[:4]
        self.assertEqual(first_pass, [0, 1, 2, 3])

    def test_distinct_queries_are_untouched(self):
        out, calls = self._run(["a", "b", "c"])
        self.assertEqual(sorted(calls), [("a", 0), ("b", 0), ("c", 0)])
        self.assertEqual(len({a.identity for a in out}), 3)

    def test_with_reuse_off_a_clip_never_repeats(self):
        # The strict rule, still available: a clip never appears twice, and
        # the other four scenes stay empty for the editor's Find footage.
        with mock.patch.object(config, "REUSE_SHOTS_TO_FILL", False):
            out, _ = self._run(["the lake"] * 6, per_query=2)
        placed = [a for a in out if a]
        self.assertEqual(len(placed), 2)
        self.assertEqual(len({a.identity for a in placed}), 2)

    def test_running_out_of_options_reuses_only_spaced_out_and_flagged(self):
        # Two distinct assets, eight scenes. No scene may render black (the
        # creator's rule after a long biography came out 86% empty), but a
        # repeat never lands within REUSE_MIN_GAP scenes of the same shot and
        # is always flagged - the original complaint was silent, close repeats.
        out, _ = self._run(["the lake"] * 8, per_query=2)
        placed = [(i, a) for i, a in enumerate(out) if a]
        self.assertGreater(len(placed), 2)
        for i, a in placed:
            for j, b in placed:
                if i != j and a.identity == b.identity:
                    self.assertGreater(abs(i - j), media.REUSE_MIN_GAP)
        reused = [a for _, a in placed if a.review_reason.startswith("Reused")]
        self.assertTrue(reused)
        self.assertTrue(all(a.review_required for a in reused))

    def test_youtube_identity_is_the_video_not_the_query(self):
        # Two different searches landing on the same upload count as one.
        a = MediaAsset(kind="video", source="youtube", url="lake powell",
                       local_path="/w/yt_XYZ.mp4")
        b = MediaAsset(kind="video", source="youtube", url="glen canyon dam",
                       local_path="/w/yt_XYZ.mp4")
        self.assertEqual(a.identity, b.identity)

    def _stub_yt(self, cands, picked=None, starts=None):
        orig_c, orig_f = media._yt_candidates, media._yt_fetch

        def fetch(vid, out, start, secs, **k):
            if picked is not None:
                picked.append(vid)
            if starts is not None:
                starts.append(start)
            return "/w/yt_%s.mp4" % vid

        media._yt_candidates = lambda *a, **k: cands
        media._yt_fetch = fetch
        return orig_c, orig_f

    def _restore_yt(self, saved):
        media._yt_candidates, media._yt_fetch = saved

    def test_skip_walks_down_the_ranking(self):
        """A repeated subject must get a different video, not the same top hit."""
        picked = []
        cands = [{"id": "V%d" % i, "duration": 300, "aspect": 1.78,
                  "title": "Lake Powell aerial footage %d" % i} for i in range(6)]
        saved = self._stub_yt(cands, picked=picked)
        try:
            media.youtube_clip("lake", "/tmp/x", seconds=3.0, skip=0)
            media.youtube_clip("lake", "/tmp/x", seconds=3.0, skip=2)
        finally:
            self._restore_yt(saved)
        self.assertNotEqual(picked[0], picked[1])

    def test_a_used_video_is_skipped(self):
        picked = []
        cands = [{"id": "TAKEN", "duration": 300, "aspect": 1.78, "title": "a"},
                 {"id": "FRESH", "duration": 300, "aspect": 1.78, "title": "b"}]
        saved = self._stub_yt(cands, picked=picked)
        try:
            media.youtube_clip("lake", "/tmp/x", seconds=3.0, used={"yt:TAKEN"})
        finally:
            self._restore_yt(saved)
        self.assertEqual(picked, ["FRESH"])

    def test_vertical_candidates_are_never_downloaded(self):
        picked = []
        cands = [{"id": "TALL", "duration": 300, "aspect": 0.56, "title": "a"},
                 {"id": "WIDE", "duration": 300, "aspect": 1.78, "title": "b"}]
        saved = self._stub_yt(cands, picked=picked)
        try:
            media.youtube_clip("lake", "/tmp/x", seconds=3.0)
        finally:
            self._restore_yt(saved)
        self.assertEqual(picked, ["WIDE"])

    def test_grab_point_is_a_fraction_of_the_video_not_a_fixed_offset(self):
        """0:30 of a ten-minute documentary is still the intro."""
        starts = []
        cands = [{"id": "V", "duration": 600, "aspect": 1.78, "title": "aerial"}]
        saved = self._stub_yt(cands, starts=starts)
        try:
            media.youtube_clip("lake", "/tmp/x", seconds=4.0)
        finally:
            self._restore_yt(saved)
        self.assertAlmostEqual(starts[0], 210.0, delta=1.0)   # 35% of 600s

    def test_b_roll_intent_is_tried_before_the_plain_query(self):
        searched = []
        orig_c, orig_f = media._yt_candidates, media._yt_fetch
        media._yt_candidates = lambda target, *a, **k: searched.append(target) or []
        media._yt_fetch = lambda *a, **k: ""
        try:
            media.youtube_clip("lake powell", "/tmp/x", seconds=3.0, require_cc=False)
        finally:
            media._yt_candidates, media._yt_fetch = orig_c, orig_f
        first_word = media.B_ROLL_INTENT.split()[0]
        self.assertIn(first_word, searched[0])
        self.assertNotIn(first_word, searched[-1])


class QueryRelaxation(unittest.TestCase):
    """
    A query too specific to match anything is worse than a broader one.

    Measured on real narration: a 7-term query left 30 of 55 scenes with no
    media at all, which renders as black frames. Each shot now carries
    progressively broader fallbacks, ending at the project title.
    """

    def test_fallbacks_get_broader_and_end_at_the_title(self):
        s = seg("The concrete ramp under his tires runs downhill and stops.", 0, 3)
        shots, _, _ = director.plan([s], title="Lake Powell", allow_maps=False)
        query, fallbacks = shots[0]["query"], shots[0]["fallbacks"]
        self.assertTrue(query.startswith("Lake Powell"))
        self.assertTrue(fallbacks, "a specific query needs a way down")
        self.assertEqual(fallbacks[-1], "Lake Powell")
        # Strictly shorter each step.
        lengths = [len(query.split())] + [len(f.split()) for f in fallbacks]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_the_primary_query_stays_short_enough_to_match(self):
        s = seg("The concrete ramp under his tires runs downhill and simply stops "
                "past gravel and dried mud sloping toward the shoreline.", 0, 4)
        shots, _, _ = director.plan([s], title="Lake Powell", allow_maps=False)
        self.assertLessEqual(len(shots[0]["query"].split()), 7)

    def test_no_duplicate_fallbacks(self):
        s = seg("Powell dropped.", 0, 3)
        shots, _, _ = director.plan([s], title="Lake Powell", allow_maps=False)
        all_q = [shots[0]["query"]] + shots[0]["fallbacks"]
        self.assertEqual(len(all_q), len(set(all_q)))

    def test_sourcing_tries_each_fallback_in_order_and_stops_on_a_hit(self):
        tried = []

        def fake_one(query, seconds, work_dir, **kw):
            tried.append(query)
            return asset() if query == "Lake Powell" else None

        original = media._source_one
        media._source_one = fake_one
        try:
            got = media.source_for_segment(
                "Lake Powell concrete ramp under tires", 3.0, "/tmp/x",
                fallbacks=["Lake Powell concrete ramp", "Lake Powell"])
        finally:
            media._source_one = original
        self.assertIsNotNone(got)
        self.assertEqual(tried, ["Lake Powell concrete ramp under tires",
                                 "Lake Powell concrete ramp", "Lake Powell"])

    def test_a_hit_on_the_specific_query_never_falls_back(self):
        tried = []

        def fake_one(query, seconds, work_dir, **kw):
            tried.append(query)
            return asset()

        original = media._source_one
        media._source_one = fake_one
        try:
            media.source_for_segment("specific", 3.0, "/tmp/x",
                                     fallbacks=["broad", "broader"])
        finally:
            media._source_one = original
        self.assertEqual(tried, ["specific"])


class GeneratedImages(unittest.TestCase):
    """Generated stills: ordering, spend cap, and honest labelling."""

    def setUp(self):
        self._prefer = config.PREFER_GENERATED_IMAGES
        self._cap = config.IMAGE_MAX_PER_VIDEO
        media.reset_cache()

    def tearDown(self):
        config.PREFER_GENERATED_IMAGES = self._prefer
        config.IMAGE_MAX_PER_VIDEO = self._cap
        media.reset_cache()

    def _stub(self, generated_ok=True):
        made = []

        def fake_generate(prompt, out_dir, **kw):
            made.append(prompt)
            if not generated_ok:
                return None
            return MediaAsset(kind="image", source="generated", url="",
                              local_path=f"/w/gen{len(made)}.png",
                              review_required=True,
                              review_reason="Generated illustration, not documentary footage")
        return fake_generate, made

    def test_off_by_default_real_photos_win(self):
        self.assertFalse(self._prefer, "generation must be opt-in")

    def test_footage_still_prefers_real_youtube_clips(self):
        """Generation is for stills. Moving pictures still come from YouTube."""
        config.PREFER_GENERATED_IMAGES = True
        gen, made = self._stub()
        orig_gen, orig_yt = media.generate_image, media.youtube_clip
        media.generate_image = gen
        media.youtube_clip = lambda *a, **k: MediaAsset(
            kind="video", source="youtube", url="q", local_path="/w/yt_A.mp4")
        try:
            got = media.source_for_segment("lake powell ramp", 3.0, "/tmp/x",
                                           visual_type="footage", prompt="p")
        finally:
            media.generate_image, media.youtube_clip = orig_gen, orig_yt
        self.assertEqual(got.source, "youtube")
        self.assertEqual(made, [], "no image should be generated for a footage beat")

    def test_when_preferred_generation_runs_before_the_archives(self):
        config.PREFER_GENERATED_IMAGES = True
        gen, made = self._stub()
        orig_gen, orig_wiki = media.generate_image, media.search_wikimedia
        media.generate_image = gen
        media.search_wikimedia = lambda q, limit=5: [
            asset(kind="image", source="wikimedia", url="https://x/real.jpg")]
        try:
            got = media.source_for_segment("Lake Powell ramp", 3.0, "/tmp/x",
                                           visual_type="image", allow_youtube=False,
                                           prompt="Lake Powell. The ramp stops.")
        finally:
            media.generate_image, media.search_wikimedia = orig_gen, orig_wiki
        self.assertEqual(got.source, "generated")
        self.assertEqual(made, ["Lake Powell. The ramp stops."],
                         "the narration line is the prompt, not the search keywords")

    def test_generation_is_always_flagged_as_an_illustration(self):
        config.PREFER_GENERATED_IMAGES = True
        gen, _ = self._stub()
        orig = media.generate_image
        media.generate_image = gen
        try:
            # allow_youtube=False: this is the STILLS path. Motion footage
            # still comes from YouTube first — generation is for images.
            got = media.source_for_segment("x", 3.0, "/tmp/x", prompt="a prompt",
                                           visual_type="image", allow_youtube=False)
        finally:
            media.generate_image = orig
        self.assertTrue(got.review_required)
        self.assertIn("not documentary", got.review_reason)

    def test_the_spend_cap_is_enforced(self):
        config.PREFER_GENERATED_IMAGES = True
        config.IMAGE_MAX_PER_VIDEO = 3
        gen, made = self._stub()
        orig_gen, orig_wiki, orig_open = (media.generate_image,
                                          media.search_wikimedia, media.search_openverse)
        media.generate_image = gen
        media.search_wikimedia = lambda q, limit=5: []
        media.search_openverse = lambda q, limit=5: []
        try:
            for i in range(10):
                media.source_for_segment(f"q{i}", 3.0, "/tmp/x", prompt=f"p{i}",
                                         visual_type="image", allow_youtube=False)
        finally:
            (media.generate_image, media.search_wikimedia,
             media.search_openverse) = orig_gen, orig_wiki, orig_open
        self.assertLessEqual(len(made), 3, f"cap of 3 exceeded: {len(made)} calls")

    def test_the_cap_resets_between_jobs(self):
        config.PREFER_GENERATED_IMAGES = True
        config.IMAGE_MAX_PER_VIDEO = 1
        gen, made = self._stub()
        orig_gen, orig_wiki = media.generate_image, media.search_wikimedia
        media.generate_image = gen
        media.search_wikimedia = lambda q, limit=5: []
        try:
            media.source_for_segment("a", 3.0, "/tmp/x", prompt="a",
                                     visual_type="image", allow_youtube=False)
            media.reset_cache()
            media.source_for_segment("b", 3.0, "/tmp/x", prompt="b",
                                     visual_type="image", allow_youtube=False)
        finally:
            media.generate_image, media.search_wikimedia = orig_gen, orig_wiki
        self.assertEqual(len(made), 2, "a new job must get a fresh budget")

    def test_director_prompt_is_a_description_not_keywords(self):
        s = seg("The concrete ramp under his tires runs downhill and stops.", 0, 3)
        shots, _, _ = director.plan([s], title="Lake Powell", allow_maps=False)
        self.assertIn("concrete ramp under his tires", shots[0]["prompt"])
        self.assertTrue(shots[0]["prompt"].startswith("Lake Powell"))
        self.assertNotEqual(shots[0]["prompt"], shots[0]["query"])


class BlockedIPDetection(unittest.TestCase):
    """
    A refused IP must never be mistaken for an empty search.

    Measured on the live RunPod endpoint: YouTube answered
    "The following content is not available on this app" — which reads like a
    missing video, not a blocked client. Matching only the famous "sign in to
    confirm you're not a bot" wording reported it as "no results", so every
    scene would have fallen back to a still and the video would have come out
    wrong with nothing in the logs to explain it.
    """

    def test_the_message_runpod_actually_returns_is_recognised(self):
        self.assertTrue(media.looks_blocked(
            "ERROR: [youtube] QYNSgqysNoM: The following content is not "
            "available on this app."))

    def test_the_classic_bot_wording_is_recognised(self):
        for msg in ("Sign in to confirm you're not a bot",
                    "ERROR: Please sign in",
                    "HTTP Error 429: Too Many Requests"):
            self.assertTrue(media.looks_blocked(msg), msg)

    def test_a_refused_search_page_is_recognised(self):
        # Verbatim from a banned Webshare IP; the search returned nothing.
        self.assertTrue(media.looks_blocked(
            'ERROR: query "Hoover Dam aerial drone" page 1: Unable to download '
            "API page: HTTP Error 403: Forbidden (caused by <HTTPError 403: Forbidden>)"))

    def test_a_genuinely_empty_search_is_not_called_a_block(self):
        for msg in ("ERROR: no results found", "", None,
                    "ERROR: Unsupported URL"):
            self.assertFalse(media.looks_blocked(msg), repr(msg))

    def test_a_blocked_fetch_returns_none_rather_than_a_broken_asset(self):
        class Result:
            returncode, stdout = 1, ""
            stderr = "ERROR: [youtube] X: The following content is not available on this app."

        original = media.subprocess.run
        media.subprocess.run = lambda cmd, **k: Result()
        try:
            self.assertIsNone(media.youtube_clip("lake", "/tmp/x", seconds=3.0))
        finally:
            media.subprocess.run = original

    def test_configured_proxies_are_passed_to_yt_dlp(self):
        seen = {}

        class Result:
            returncode, stdout, stderr = 0, "", ""

        original_run = media.subprocess.run
        saved = (media._PROXIES[:], dict(media._PROXY_BENCHED))
        media._PROXIES[:] = ["http://u:p@host1:8000", "http://u:p@host2:8000"]
        media._PROXY_BENCHED.clear()
        media.subprocess.run = lambda cmd, **k: seen.setdefault("cmds", []).append(cmd) or Result()
        try:
            media._yt_candidates("ytsearch1:a", False)
            media._yt_candidates("ytsearch1:b", False)
        finally:
            media.subprocess.run = original_run
            media._PROXIES[:] = saved[0]
            media._PROXY_BENCHED.clear()
            media._PROXY_BENCHED.update(saved[1])

        proxies = [c[c.index("--proxy") + 1] for c in seen["cmds"] if "--proxy" in c]
        self.assertEqual(len(proxies), 2)
        # Rotated, so one address does not absorb every download and get flagged.
        self.assertNotEqual(proxies[0], proxies[1])

    def test_no_proxy_flag_when_none_configured(self):
        seen = {}

        class Result:
            returncode, stdout, stderr = 0, "", ""

        original_run = media.subprocess.run
        saved = media._PROXIES[:]
        media._PROXIES[:] = []
        media.subprocess.run = lambda cmd, **k: seen.update(cmd=cmd) or Result()
        try:
            media._yt_candidates("ytsearch1:a", False)
        finally:
            media.subprocess.run = original_run
            media._PROXIES[:] = saved
        self.assertNotIn("--proxy", seen["cmd"])

    def test_a_refused_proxy_is_skipped_until_it_recovers(self):
        class Refused:
            returncode, stdout = 1, ""
            stderr = "ERROR: Sign in to confirm you're not a bot"

        class Ok:
            returncode, stdout, stderr = 0, "", ""

        used, replies = [], [Refused(), Ok(), Ok(), Ok()]

        def fake_run(cmd, **k):
            used.append(cmd[cmd.index("--proxy") + 1])
            return replies.pop(0)

        original_run = media.subprocess.run
        saved = (media._PROXIES[:], dict(media._PROXY_BENCHED), media._PROXY_POS[0])
        media._PROXIES[:] = ["http://a:1", "http://b:2", "http://c:3"]
        media._PROXY_BENCHED.clear()
        media._PROXY_POS[0] = 0
        media.subprocess.run = fake_run
        try:
            for q in "wxyz":
                media._yt_candidates(f"ytsearch1:{q}", False)
        finally:
            media.subprocess.run = original_run
            media._PROXIES[:] = saved[0]
            media._PROXY_BENCHED.clear()
            media._PROXY_BENCHED.update(saved[1])
            media._PROXY_POS[0] = saved[2]
        self.assertEqual(used[0], "http://a:1")
        # a was refused, so the rotation carries on without it.
        self.assertNotIn("http://a:1", used[1:])

    def test_all_proxies_benched_still_returns_one(self):
        saved = (media._PROXIES[:], dict(media._PROXY_BENCHED))
        media._PROXIES[:] = ["http://a:1", "http://b:2"]
        media._PROXY_BENCHED.clear()
        media._PROXY_BENCHED.update({"http://a:1": 9e12, "http://b:2": 8e12})
        try:
            # Least-recently benched wins rather than running with no proxy.
            self.assertEqual(media._next_proxy(), "http://b:2")
        finally:
            media._PROXIES[:] = saved[0]
            media._PROXY_BENCHED.clear()
            media._PROXY_BENCHED.update(saved[1])


class SameSubjectBeatsSpreadAcrossTheList(unittest.TestCase):
    """
    A real 23-beat job sent 21 beats to the slow replacement pass: beats on
    one subject share a candidate list (cached by subject) but their `nth`
    was keyed on the exact query wording, so every one got nth=0 and they all
    grabbed the same top video in parallel.
    """

    def test_nth_counts_per_subject_not_per_query_wording(self):
        nths = []

        def fake(query, seconds, work_dir, *, nth=0, **kw):
            nths.append((query, nth))
            return MediaAsset(kind="video", source="youtube", url=query,
                              local_path=f"/w/yt_{query[:11]:_<11}_0_1000.mp4")

        jobs = [{"index": i, "query": q, "subject": "Ohio Valley", "seconds": 3.0}
                for i, q in enumerate(["Ohio Valley flood aerial",
                                       "Ohio Valley river gauge",
                                       "Ohio Valley rain radar"])]
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")):
            media.reset_cache()
            media.source_many(jobs, "/tmp", workers=1)
        self.assertEqual(sorted(n for _, n in nths[:3]), [0, 1, 2])

    def test_no_subject_still_counts_by_query(self):
        nths = []

        def fake(query, seconds, work_dir, *, nth=0, **kw):
            nths.append(nth)
            return MediaAsset(kind="image", source="wikimedia", url=f"https://x/{query}{nth}")

        jobs = [{"index": i, "query": q, "seconds": 3.0}
                for i, q in enumerate(["a", "b", "a"])]
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")):
            media.reset_cache()
            media.source_many(jobs, "/tmp", workers=1)
        self.assertEqual(nths[:3], [0, 0, 1])


class SubjectLevelSearchCache(unittest.TestCase):
    """
    A real render spent a fresh yt-dlp search on every beat, even when five
    beats in a row were about the same subject worded five different ways
    (with_subject adds whatever detail that one line needs). The search
    results ARE the same question for all of them - only which moment gets
    used differs, and that still comes from each beat's own intent.
    """

    def setUp(self):
        media.reset_cache()

    def tearDown(self):
        media.reset_cache()

    def test_two_queries_on_one_subject_search_only_once(self):
        calls = []

        def fake_candidates(target, require_cc, limit=12, timeout=90):
            calls.append(target)
            return [{"id": "abc", "duration": 40.0, "aspect": 1.78, "title": "Lake Mead drone"}]

        with mock.patch.object(media, "_yt_candidates", side_effect=fake_candidates):
            a = media._yt_candidates_cached("ytsearch12:Lake Mead boat ramp", False, "Lake Mead")
            b = media._yt_candidates_cached("ytsearch12:Lake Mead drought level", False, "Lake Mead")
        self.assertEqual(len(calls), 1, "second beat on the same subject must not re-search")
        self.assertEqual(a, b)

    def test_a_different_subject_still_searches(self):
        calls = []

        def fake_candidates(target, require_cc, limit=12, timeout=90):
            calls.append(target)
            return []

        with mock.patch.object(media, "_yt_candidates", side_effect=fake_candidates):
            media._yt_candidates_cached("ytsearch12:Lake Mead", False, "Lake Mead")
            media._yt_candidates_cached("ytsearch12:Hoover Dam", False, "Hoover Dam")
        self.assertEqual(len(calls), 2)

    def test_no_subject_never_shares_a_cache_entry(self):
        # The rule planner (no AI director) has no subject; behaviour must be
        # exactly as before - a fresh search for every distinct query text.
        calls = []

        def fake_candidates(target, require_cc, limit=12, timeout=90):
            calls.append(target)
            return []

        with mock.patch.object(media, "_yt_candidates", side_effect=fake_candidates):
            media._yt_candidates_cached("ytsearch12:the lake ramp", False, "")
            media._yt_candidates_cached("ytsearch12:the lake ramp", False, "")
        self.assertEqual(len(calls), 2)

    def test_moment_selection_still_uses_each_beats_own_intent(self):
        # The cached candidate list is shared; scouting and the vision judge
        # are not - they must still be called once per beat.
        seen_intents = []

        def fake_scout(candidate, grab, intent, context):
            seen_intents.append(intent)
            return None

        jobs = [{"index": 0, "query": "Lake Mead boat ramp", "subject": "Lake Mead",
                 "intent": "exposed concrete ramp", "seconds": 3.0},
                {"index": 1, "query": "Lake Mead water line", "subject": "Lake Mead",
                 "intent": "white bathtub ring on the shoreline", "seconds": 3.0}]

        def fake_candidates(target, require_cc, limit=12, timeout=90):
            return [{"id": "abc", "duration": 40.0, "aspect": 1.78, "title": "Lake Mead"}]

        with mock.patch.object(media, "_yt_candidates", side_effect=fake_candidates), \
                mock.patch.object(media, "_scout", side_effect=fake_scout), \
                mock.patch.object(media, "_yt_fetch_retry", return_value=""), \
                mock.patch.object(config, "MOMENT_SELECTION", True), \
                mock.patch.object(config, "VISION_ENABLED", True), \
                mock.patch.object(config, "VISION_API_KEY", "k"):
            for job in jobs:
                media.youtube_clip(job["query"], "/tmp", seconds=job["seconds"],
                                   require_cc=False, intent=job["intent"],
                                   subject=job["subject"])
        # youtube_clip tries a b-roll-decorated search then the plain one, so
        # each beat scouts twice - the point is which INTENT it scouted with,
        # and that the two beats' intents are never mixed up.
        self.assertEqual(set(seen_intents), {"exposed concrete ramp",
                                             "white bathtub ring on the shoreline"})
        self.assertEqual(seen_intents[:2], ["exposed concrete ramp"] * 2)
        self.assertEqual(seen_intents[2:], ["white bathtub ring on the shoreline"] * 2)


class NetworkConcurrency(unittest.TestCase):
    """
    Scene-level sourcing (6 workers) x moment scouting (MOMENT_PARALLEL) can
    ask for far more simultaneous yt-dlp requests than there are proxy IPs,
    which reads as "sourcing is slow" with nothing to explain it: a contended
    proxy does not error, it just queues.
    """

    def setUp(self):
        media.reset_cache()

    def tearDown(self):
        media.reset_cache()

    def test_yt_dlp_calls_never_exceed_the_configured_cap(self):
        import concurrent.futures
        cap = 3
        current = [0]
        peak = [0]
        lock = threading.Lock()

        class Result:
            returncode, stdout, stderr = 0, "", ""

        def fake_run(cmd, **k):
            with lock:
                current[0] += 1
                peak[0] = max(peak[0], current[0])
            time.sleep(0.05)
            with lock:
                current[0] -= 1
            return Result()

        with mock.patch.object(config, "NETWORK_CONCURRENCY", cap), \
                mock.patch.object(media, "_NET_SEM", threading.Semaphore(cap)), \
                mock.patch.object(media.subprocess, "run", side_effect=fake_run):
            with concurrent.futures.ThreadPoolExecutor(10) as pool:
                list(pool.map(lambda i: media._yt_candidates(f"ytsearch1:{i}", False), range(10)))
        self.assertLessEqual(peak[0], cap)

    def test_the_same_video_is_extracted_only_once_per_job(self):
        calls = []

        class Result:
            returncode, stdout, stderr = 0, '{"id": "abc", "duration": 300}', ""

        def fake_run(cmd, **k):
            calls.append(1)
            return Result()

        with mock.patch.object(media.subprocess, "run", side_effect=fake_run):
            info1, _ = media._yt_info("abc")
            info2, _ = media._yt_info("abc")
        self.assertEqual(len(calls), 1)
        self.assertEqual(info1, info2)

    def test_a_failed_extraction_is_not_cached(self):
        class Result:
            returncode, stdout, stderr = 1, "", "error"

        with mock.patch.object(media.subprocess, "run", return_value=Result()):
            info, _ = media._yt_info("bad-video")
        self.assertEqual(info, {})
        self.assertNotIn("bad-video", media._YT_INFO_CACHE)


class ExtraSources(unittest.TestCase):
    """
    Sources beyond YouTube. "Not only yt-dlp" is how the one person who has
    shipped this described his setup, and these carry clean licences —
    Commons video is freely licensed, NASA is public domain outright.
    """

    def _commons(self, url):
        payload = {"query": {"pages": {"1": {"imageinfo": [
            {"url": url, "width": 1920, "height": 1080, "extmetadata": {}}]}}}}

        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self_inner): return payload

        original = media.requests.get
        media.requests.get = lambda *a, **k: R()
        try:
            return media.search_wikimedia_video("lake powell")
        finally:
            media.requests.get = original

    def test_tracking_params_do_not_hide_a_video(self):
        """
        Commons appends utm_* params, so the extension must be read off the
        parsed path. Testing the raw URL matched nothing and silently
        disabled the entire source.
        """
        hits = self._commons(
            "https://upload.wikimedia.org/x/1993_LakePowell.ogv"
            "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].kind, "video")
        self.assertEqual(hits[0].source, "wikimedia")

    def test_non_video_files_are_still_rejected(self):
        self.assertEqual(
            self._commons("https://upload.wikimedia.org/x/photo.jpg?utm_source=y"), [])

    def test_nasa_video_helper_is_named_for_the_search_cache(self):
        # _cached_search keys on fn.__name__; a lambda or partial would make
        # the image and video searches share one cache entry.
        self.assertEqual(media.search_nasa_video.__name__, "search_nasa_video")
        self.assertNotEqual(media.search_nasa.__name__,
                            media.search_nasa_video.__name__)

    def _archive_org(self, docs, files_by_id, safe_docs=()):
        class SearchR:
            def __init__(self_inner, rows): self_inner.rows = rows
            status_code = 200
            def raise_for_status(self): pass
            def json(self_inner): return {"response": {"docs": self_inner.rows}}

        class MetaR:
            def __init__(self_inner, ident): self_inner.ident = ident
            status_code = 200
            def raise_for_status(self): pass
            def json(self_inner): return {"files": files_by_id.get(self_inner.ident, [])}

        def fake_get(url, params=None, **k):
            if "advancedsearch" in url:
                q = (params or {}).get("q", "")
                return SearchR(list(safe_docs) if "collection:prelinger" in q else docs)
            ident = url.rsplit("/", 1)[-1]
            return MetaR(ident)

        original = media.requests.get
        media.requests.get = fake_get
        try:
            return media.search_archive_org_video("lake mead")
        finally:
            media.requests.get = original

    def test_only_a_fully_open_licence_is_accepted(self):
        docs = [
            {"identifier": "safe1", "title": "Public domain newsreel",
            "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
            {"identifier": "safe2", "title": "CC-BY clip",
            "licenseurl": "http://creativecommons.org/licenses/by/3.0/"},
            # Content ID risk this exists to keep out: research-only TV News
            # Archive style items have no licenceurl at all...
            {"identifier": "tv_news", "title": "Evening News broadcast"},
            # ...and NC/ND uploads are not clear for a monetised, edited reuse.
            {"identifier": "nc_nd", "title": "Personal upload",
            "licenseurl": "https://creativecommons.org/licenses/by-nc-nd/3.0/us/"},
        ]
        files = {
            "safe1": [{"name": "safe1.mp4", "format": "512Kb MPEG4", "size": "900000"},
                     {"name": "safe1.thumbs/a.jpg", "format": "Thumbnail", "size": "800"}],
            "safe2": [{"name": "safe2.ogv", "format": "Ogg Video", "size": "500000"}],
        }
        hits = self._archive_org(docs, files)
        self.assertEqual({h.url.rsplit("/", 1)[-1] for h in hits}, {"safe1.mp4", "safe2.ogv"})
        self.assertTrue(all(h.source == "archive_org" for h in hits))

    def test_the_largest_real_video_file_is_picked_over_thumbnails(self):
        docs = [{"identifier": "item1", "title": "Hoover Dam footage",
                "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"}]
        files = {"item1": [
            {"name": "item1.thumbs/f1.jpg", "format": "Thumbnail", "size": "9000"},
            {"name": "item1_archive.torrent", "format": "Archive BitTorrent", "size": "8000"},
            {"name": "item1.ogv", "format": "Ogg Video", "size": "500000"},
            {"name": "item1_512kb.mp4", "format": "512Kb MPEG4", "size": "2000000"},
        ]}
        hits = self._archive_org(docs, files)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].url.endswith("item1_512kb.mp4"))

    def test_a_known_safe_collection_is_trusted_without_a_licenceurl(self):
        # Prelinger / US government film is public domain by law, not by an
        # explicit CC tag - many real items (Universal Newsreel, gov.archives.
        # arc.*) carry no licenseurl at all despite being unambiguously free.
        safe = [{"identifier": "newsreel1", "title": "Universal Newsreel Volume 23"}]
        files = {"newsreel1": [{"name": "newsreel1.mp4", "format": "512Kb MPEG4", "size": "700000"}]}
        hits = self._archive_org(docs=[], files_by_id=files, safe_docs=safe)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].url.endswith("newsreel1.mp4"))

    def test_the_general_search_still_needs_a_licenceurl_even_alongside_safe_hits(self):
        safe = [{"identifier": "gov1", "title": "Flood Weather"}]
        general = [{"identifier": "tv_news", "title": "Evening News broadcast"}]  # no licenceurl
        files = {"gov1": [{"name": "gov1.mp4", "format": "512Kb MPEG4", "size": "700000"}],
                 "tv_news": [{"name": "tv_news.mp4", "format": "512Kb MPEG4", "size": "700000"}]}
        hits = self._archive_org(docs=general, files_by_id=files, safe_docs=safe)
        self.assertEqual({h.url.rsplit("/", 1)[-1] for h in hits}, {"gov1.mp4"})


TODAY = datetime.date(2026, 9, 25)
FLOOD = [
    seg("In June 2026 the Mississippi River broke through a levee in Davenport, Iowa.", 0, 5),
    seg("Floodwaters poured into downtown streets overnight.", 5, 9),
    seg("Residents were told to evacuate by the National Weather Service.", 9, 14),
    seg("The water kept rising for three more days.", 14, 18),
    seg("It was the worst flooding since 1993.", 18, 22),
]


class StoryBrief(unittest.TestCase):
    """The whole narration is read once, before any beat is planned."""

    def test_rules_recognise_a_recent_flood_story_and_where_it_happened(self):
        b = director._rule_brief(FLOOD, "Midwest Floods", today=TODAY)
        self.assertIn(b["kind"], director.EVENT_KINDS)
        self.assertTrue(b["recent"])
        self.assertEqual(b["year"], 2026)
        self.assertEqual(b["places"][0], "Davenport, Iowa")
        self.assertIn(0, b["hookBeats"])

    def test_rules_leave_a_history_story_unanchored(self):
        segs = [seg("In 1911 the Hotel Roosevelt opened its doors.", 0, 4),
                seg("It was the tallest building in town.", 4, 8)]
        b = director._rule_brief(segs, "The Old Hotel", today=TODAY)
        self.assertEqual(b["kind"], "history")
        self.assertFalse(b["recent"])

    def test_a_model_brief_is_coerced_field_by_field(self):
        fallback = director._rule_brief(FLOOD, "Midwest Floods", today=TODAY)
        raw = {"kind": "not-a-kind", "year": 3050, "recent": "yes",
               "places": ["Davenport, Iowa", 7, ""], "hookBeats": [0, 2, 99, True],
               "event": "2026 Midwest flooding Iowa"}
        b = director._validate_brief(raw, fallback, len(FLOOD), today=TODAY)
        self.assertEqual(b["kind"], fallback["kind"])
        self.assertEqual(b["year"], fallback["year"])
        self.assertEqual(b["recent"], fallback["recent"])
        self.assertEqual(b["places"], ["Davenport, Iowa"])
        self.assertEqual(b["hookBeats"], [0, 2])
        self.assertEqual(b["event"], "2026 Midwest flooding Iowa")

    def test_only_an_event_story_can_be_recent(self):
        fallback = director._rule_brief(FLOOD, "", today=TODAY)
        b = director._validate_brief({"kind": "history", "recent": True}, fallback,
                                     len(FLOOD), today=TODAY)
        self.assertFalse(b["recent"])

    def test_a_failed_model_call_falls_back_to_the_rules(self):
        with mock.patch.object(director, "_chat_json", return_value=None), \
                mock.patch.object(director, "_today", return_value=TODAY):
            b = director.story_brief(FLOOD, "Midwest Floods", configured=True)
        self.assertEqual(b, director._rule_brief(FLOOD, "Midwest Floods", today=TODAY))

    def test_every_planning_batch_sees_the_whole_story(self):
        payloads = []
        brief = {"kind": "disaster", "summary": "A levee fails.",
                 "event": "2026 Midwest flooding Iowa", "year": 2026, "recent": True,
                 "places": ["Davenport, Iowa"], "people": [], "hookBeats": [0, 1]}

        def post(url, **kw):
            system = kw["json"]["messages"][0]["content"]
            payloads.append(json.loads(kw["json"]["messages"][1]["content"]))
            content = brief if system == director._BRIEF_PROMPT else {"shots": []}
            r = mock.Mock(status_code=200)
            r.json.return_value = {"choices": [{"message": {"content": json.dumps(content)}}]}
            return r

        with mock.patch.object(config, "DIRECTOR_API_KEY", "k"), \
                mock.patch.object(config, "DIRECTOR_API_BASE", "https://api.kie.ai/v1"), \
                mock.patch.object(config, "DIRECTOR_MODEL", "m"), \
                mock.patch.object(config, "DIRECTOR_FALLBACK_MODELS", []), \
                mock.patch.object(director, "_today", return_value=TODAY), \
                mock.patch.object(director.requests, "post", side_effect=post):
            shots, _, _ = director.plan(FLOOD, "Midwest Floods", allow_maps=False)

        batch = [p for p in payloads if "story" in p][0]
        self.assertEqual(batch["story"]["event"], "2026 Midwest flooding Iowa")
        self.assertTrue(batch["beats"][0].get("hook"))
        self.assertFalse(batch["beats"][3].get("hook"))
        self.assertTrue(shots[0]["hook"])
        # A line that never names the place or year is still searched as this flood.
        self.assertIn("Davenport", shots[3]["query"])
        self.assertIn("2026", shots[3]["query"])
        self.assertIn("Davenport, Iowa, 2026", shots[3]["intent"])
        self.assertEqual(shots[3]["eventWindow"], "year")
        self.assertEqual(shots[3]["fallbacks"][0], "2026 Midwest flooding Iowa")
        # The line about 1993 keeps its own year.
        self.assertNotIn("2026", shots[4]["query"])
        self.assertEqual(shots[4]["eventWindow"], "event")


class StoryAnchoring(unittest.TestCase):
    BRIEF = {"kind": "news", "places": ["Davenport, Iowa"], "year": 2026, "recent": True,
             "event": "2026 Midwest flooding Iowa"}

    def _anchor(self, shots, brief=None):
        segs = [seg("A line.", i, i + 1) for i in range(len(shots))]
        with mock.patch.object(director, "_today", return_value=TODAY):
            return director.anchor_to_story(shots, segs, brief or self.BRIEF)

    def test_portraits_and_separately_named_places_keep_their_own_anchor(self):
        shots = [{"query": "Governor Kim Reynolds", "subjectType": "person",
                  "visualType": "image", "intent": ""},
                 {"query": "St. Louis riverfront flooding", "subjectType": "place",
                  "visualType": "footage", "intent": ""}]
        self._anchor(shots)
        self.assertEqual(shots[0]["query"], "Governor Kim Reynolds")
        self.assertNotIn("Davenport", shots[1]["query"])
        self.assertIn("2026", shots[1]["query"])

    def test_footage_of_a_person_is_pinned_to_the_event(self):
        shots = [{"query": "Governor Kim Reynolds", "subjectType": "person",
                  "visualType": "footage", "intent": ""}]
        self._anchor(shots)
        self.assertEqual(shots[0]["query"], "Davenport Iowa Governor Kim Reynolds 2026")

    def test_a_query_that_already_names_the_place_is_not_padded(self):
        shots = [{"query": "Davenport riverfront flood", "subjectType": "", "intent": ""}]
        self._anchor(shots)
        self.assertEqual(shots[0]["query"], "Davenport riverfront flood 2026")

    def test_a_last_year_event_is_not_limited_to_this_years_uploads(self):
        shots = [{"query": "flooded street", "subjectType": "", "intent": ""}]
        self._anchor(shots, dict(self.BRIEF, year=2025))
        self.assertEqual(shots[0]["eventWindow"], "event")

    def test_a_history_story_is_left_alone(self):
        shots = [{"query": "old hotel lobby", "subjectType": "", "intent": ""}]
        self.assertEqual(self._anchor(shots, dict(self.BRIEF, kind="history")), 0)
        self.assertEqual(shots[0]["query"], "old hotel lobby")
        self.assertNotIn("eventWindow", shots[0])


class EventFootage(unittest.TestCase):
    """A news story needs footage of THAT event, which news outlets upload."""

    def _in_window(self, window, fn):
        tok = media._EVENT_WINDOW.set(window)
        try:
            return fn()
        finally:
            media._EVENT_WINDOW.reset(tok)

    def test_news_outlet_titles_pass_only_for_event_stories(self):
        title = "Drone video shows flooding in Davenport | WQAD News 8"
        self.assertTrue(media._talking_head(title))
        self.assertFalse(self._in_window("event", lambda: media._talking_head(title)))
        self.assertTrue(self._in_window("event", lambda: media._talking_head(
            "Governor press conference on flood news")))

    def test_a_recent_event_searches_this_years_uploads_first(self):
        searched = []
        with mock.patch.object(media, "_yt_candidates",
                               side_effect=lambda target, *a, **k: searched.append(target) or []), \
                mock.patch.object(media, "_yt_fetch", return_value=""):
            media.reset_cache()
            self._in_window("year", lambda: media.youtube_clip(
                "Davenport Iowa flooding 2026", "/tmp/x", seconds=3.0,
                require_cc=False, subject="Davenport flood"))
        self.assertEqual(len(searched), 3)
        self.assertIn("sp=" + media._YT_THIS_YEAR, searched[0])
        self.assertIn("sp=" + media._YT_THIS_YEAR, searched[1])
        self.assertTrue(searched[2].startswith("ytsearch"))

    def test_every_search_of_a_beat_runs_even_when_a_subject_is_cached(self):
        # Keyed on the subject alone, the plain-query fallback got the
        # footage-biased search's cached list back and never searched.
        searched = []
        with mock.patch.object(media, "_yt_candidates",
                               side_effect=lambda target, *a, **k: searched.append(target) or []), \
                mock.patch.object(media, "_yt_fetch", return_value=""):
            media.reset_cache()
            media.youtube_clip("lake powell", "/tmp/x", seconds=3.0,
                               require_cc=False, subject="Lake Powell")
        self.assertEqual(len(searched), 2)

    def test_dailymotion_tries_this_years_uploads_first(self):
        calls, fetched = [], []

        def fake_get(url, params=None, **k):
            calls.append(params)
            ids = ["new"] if params.get("created_after") else ["old", "new"]
            r = mock.Mock()
            r.raise_for_status = lambda: None
            r.json.return_value = {"list": [
                {"id": i, "title": "flood footage", "duration": 120,
                 "width": 1920, "height": 1080} for i in ids]}
            return r

        with mock.patch.object(media.requests, "get", side_effect=fake_get), \
                mock.patch.object(media, "_dm_fetch",
                                  side_effect=lambda vid, *a, **k: fetched.append(vid) or ""):
            media.reset_cache()
            self._in_window("year", lambda: media.dailymotion_clip(
                "Davenport flood", "/tmp/x", seconds=3.0))
        self.assertTrue(any(p.get("created_after") for p in calls))
        self.assertEqual(fetched, ["new", "old"])


class HookShots(unittest.TestCase):
    """The opening beats open on the best clip found, not the first that passed."""

    def _run(self, hook):
        def fake(query, seconds, work_dir, *, nth=0, used=None, **kw):
            return MediaAsset(kind="video", source="youtube", url=f"https://x/{nth}",
                              relevance_score=0.5 + 0.2 * nth)

        jobs = [{"index": 0, "query": "flood", "seconds": 3.0, "hook": hook}]
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")):
            media.reset_cache()
            return media.source_many(jobs, "/tmp", workers=1)

    def test_a_hook_beat_opens_on_the_higher_scoring_clip(self):
        self.assertEqual(self._run(True)[0].url, "https://x/1")

    def test_other_beats_take_the_first_clip_that_passes(self):
        self.assertEqual(self._run(False)[0].url, "https://x/0")

    def test_between_equally_relevant_clips_the_sharper_one_opens(self):
        def fake(query, seconds, work_dir, *, nth=0, used=None, **kw):
            return MediaAsset(kind="video", source="youtube", url=f"https://x/{nth}",
                              relevance_score=0.8, quality=0.4 + 0.4 * nth)

        jobs = [{"index": 0, "query": "flood", "seconds": 3.0, "hook": True}]
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")):
            media.reset_cache()
            out = media.source_many(jobs, "/tmp", workers=1)
        self.assertEqual(out[0].url, "https://x/1")


class MetaphorsAndMaps(unittest.TestCase):
    """A metaphor shows what it names; a news story is located on a map early."""

    BRIEF = {"kind": "weather", "places": ["Ohio Valley", "Indiana", "West Virginia"],
             "year": 2026, "recent": True, "event": "2026 Ohio Valley flooding",
             "hookBeats": [0, 1]}

    def _segs(self, texts, step=4.0):
        return [seg(t, i * step, (i + 1) * step) for i, t in enumerate(texts)]

    def test_a_metaphor_shot_is_not_pinned_to_the_event(self):
        shots = [{"query": "freight train moving along track", "subjectType": "object",
                  "visualType": "footage", "intent": "", "anchor": False},
                 {"query": "flooded street", "subjectType": "", "visualType": "footage",
                  "intent": ""}]
        segs = self._segs(["Picture rail cars on a track.", "The water rose."])
        with mock.patch.object(director, "_today", return_value=TODAY):
            director.anchor_to_story(shots, segs, self.BRIEF)
        self.assertEqual(shots[0]["query"], "freight train moving along track")
        self.assertNotIn("eventWindow", shots[0])
        self.assertIn("Ohio Valley", shots[1]["query"])

    def test_an_event_story_gets_an_early_map_on_the_line_naming_a_place(self):
        segs = self._segs(["A flood emergency.", "It is not over.", "Rain keeps falling.",
                           "Roughly 40 counties in West Virginia sit under a watch.",
                           "More is coming."])
        shots = [{"overlay": None} for _ in segs]
        self.assertTrue(director.establishing_map(segs, shots, self.BRIEF))
        self.assertEqual(shots[3]["overlay"]["type"], "map")
        self.assertEqual(shots[3]["overlay"]["places"], self.BRIEF["places"])
        self.assertIsNone(shots[0]["overlay"])  # not on the hook

    def test_no_map_is_forced_when_one_is_already_early_or_the_story_is_not_news(self):
        segs = self._segs(["a", "b", "c", "d"])
        shots = [{"overlay": None} for _ in segs]
        shots[2]["overlay"] = {"type": "map", "places": ["Ohio"]}
        self.assertFalse(director.establishing_map(segs, shots, self.BRIEF))
        shots = [{"overlay": None} for _ in segs]
        self.assertFalse(director.establishing_map(
            segs, shots, dict(self.BRIEF, kind="history")))

    def test_the_map_waits_until_it_would_survive_overlay_thinning(self):
        segs = self._segs(list("abcdefgh"), step=3.0)
        shots = [{"overlay": None} for _ in segs]
        shots[2]["overlay"] = {"type": "callout", "text": "x"}   # ends at 9 s
        director.establishing_map(segs, shots, self.BRIEF)
        placed = [i for i, s in enumerate(shots) if (s["overlay"] or {}).get("type") == "map"]
        self.assertEqual(placed, [6])                            # first line starting 9 s after it
        director._thin_overlays(segs, shots)
        self.assertEqual(shots[6]["overlay"]["type"], "map")     # and thinning keeps it

    """After sourcing, every scene without a shot of its own is rechecked with the story."""

    def _run(self, fake, jobs, rescue, on_recheck=None):
        with mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "generate_image", return_value=None), \
                mock.patch.object(config, "REPLACE_BUDGET_SECONDS", 0):
            media.reset_cache()
            return media.source_many(jobs, "/tmp", workers=1, rescue=rescue,
                                     on_recheck=on_recheck)

    def test_a_repeated_clip_is_rechecked_and_given_its_own_shot(self):
        def fake(query, seconds, work_dir, **kw):
            if query == "sandbag wall Davenport 2026":
                return MediaAsset(kind="video", source="youtube", url="https://x/sandbags")
            a = MediaAsset(kind="video", source="youtube", url="https://x/flood")
            a.content_description = "aerial of a flooded downtown"
            return a

        jobs = [{"index": 0, "query": "Davenport flood", "seconds": 3.0,
                 "context": "The river broke through."},
                {"index": 1, "query": "Davenport flood", "seconds": 3.0,
                 "context": "Volunteers fought back."}]
        asked, counted = [], []

        def rescue(items):
            asked.extend(items)
            return {1: ["sandbag wall Davenport 2026"]}

        out = self._run(fake, jobs, rescue, on_recheck=counted.append)
        self.assertEqual(out[0].url, "https://x/flood")
        self.assertEqual(out[1].url, "https://x/sandbags")
        self.assertEqual(counted, [1])
        item = asked[0]
        self.assertEqual(item["index"], 1)
        self.assertTrue(item["repeat"])
        self.assertEqual(item["before"], "The river broke through.")
        self.assertEqual(item["shows"], ["aerial of a flooded downtown"])

    def test_a_repeat_nothing_better_was_found_for_is_kept_over_black(self):
        def fake(query, seconds, work_dir, **kw):
            return MediaAsset(kind="video", source="youtube", url="https://x/flood")

        jobs = [{"index": i, "query": "flood", "seconds": 3.0} for i in range(2)]
        out = self._run(fake, jobs, lambda items: {})
        self.assertIsNotNone(out[1])
        self.assertTrue(out[1].review_required)

    def test_rescue_ideas_see_the_story_and_stay_on_the_event(self):
        sent = {}

        def chat(system, payload, timeout=120):
            sent.update(payload)
            return {"items": [{"index": 3, "queries": ["sandbag wall", "rescue boats downtown"]}]}

        story = {"kind": "disaster", "event": "2026 Midwest flooding Iowa", "year": 2026,
                 "places": ["Davenport, Iowa"], "hookBeats": [0]}
        items = [{"index": 3, "text": "Volunteers fought back.", "query": "volunteers",
                  "before": "The river broke through.", "shows": ["aerial flood"],
                  "repeat": True}]
        with mock.patch.object(config, "DIRECTOR_API_KEY", "k"), \
                mock.patch.object(config, "DIRECTOR_MODEL", "m"), \
                mock.patch.object(director, "_chat_json", side_effect=chat):
            ideas = director.rescue_queries(items, story=story)
        self.assertEqual(sent["story"]["event"], "2026 Midwest flooding Iowa")
        self.assertNotIn("hookBeats", sent["story"])
        self.assertEqual(sent["items"][0]["before"], "The river broke through.")
        self.assertTrue(sent["items"][0]["repeat"])
        self.assertEqual(ideas[3], ["Davenport Iowa sandbag wall 2026",
                                    "Davenport Iowa rescue boats downtown 2026"])

    def test_the_recheck_shows_as_part_of_sourcing(self):
        import handler
        phase = next(p for prefix, p in handler._PHASE_BY_PREFIX
                     if "Rechecking 3 missing scenes against the story".startswith(prefix))
        self.assertEqual(phase, "source")


class LongVideoCoverage(unittest.TestCase):
    """A 362-scene biography rendered 86% black: photo scenes, one person, few photos."""

    def test_person_name_variants_pool_but_different_people_do_not(self):
        self.assertTrue(media.same_subject("Anne Dunham", "Ann Dunham"))
        self.assertTrue(media.same_subject("Stanley Ann Dunham", "Ann Dunham"))
        self.assertFalse(media.same_subject("Madelyn Dunham", "Ann Dunham"))
        self.assertFalse(media.same_subject("Barack Obama Sr.", "Barack Obama"))
        self.assertTrue(media.same_subject("University of Hawaii", "university of hawaii"))

    def test_an_empty_scene_reuses_its_own_subject_never_another_persons_photo(self):
        def a(url, kind="image"):
            return MediaAsset(kind=kind, source="wikipedia", url=url)
        jobs = [{"index": 0, "subject": "Ann Dunham", "subject_type": "person"},
                {"index": 1, "subject": "Madelyn Dunham", "subject_type": "person"},
                {"index": 2, "subject": "Madelyn Dunham", "subject_type": "person"},
                {"index": 3, "subject": "Madelyn Dunham", "subject_type": "person"},
                {"index": 4, "subject": "Madelyn Dunham", "subject_type": "person"},
                {"index": 5, "subject": "Anne Dunham", "subject_type": "person"}]
        results = [a("https://x/ann.jpg"), a("https://x/mad1.jpg"), a("https://x/mad2.jpg"),
                   a("https://x/mad3.jpg"), None, None]
        media.fill_from_story(jobs, results)
        self.assertEqual(results[5].url, "https://x/ann.jpg")      # her own photo, 5 apart
        self.assertTrue(results[5].review_required)
        self.assertIn("Ann Dunham", results[5].review_reason)
        self.assertEqual(results[4].url, "https://x/mad1.jpg")     # Madelyn's own, 3+ apart

    def test_a_person_scene_is_never_given_a_stranger(self):
        jobs = [{"index": 0, "subject": "Lolo Soetoro", "subject_type": "person"},
                {"index": 1, "subject": "Ann Dunham", "subject_type": "person"}]
        results = [MediaAsset(kind="image", source="wikipedia", url="https://x/lolo.jpg"), None]
        media.fill_from_story(jobs, results)
        self.assertIsNone(results[1])

    def test_a_photo_scene_with_no_photo_falls_back_to_footage(self):
        clip = MediaAsset(kind="video", source="youtube", url="q", local_path="/w/yt_abcdefghijk_0_1.mp4")
        with mock.patch.object(media, "_cached_search", return_value=[]), \
                mock.patch.object(media, "youtube_clip", return_value=clip) as yt, \
                mock.patch.object(media, "generate_image", return_value=None):
            got = media._source_one("Anne Dunham teaching Indonesia", 3.0, "/tmp",
                                    visual_type="image", allow_youtube=True,
                                    allow_stock=False, require_cc=False)
        self.assertIs(got, clip)
        yt.assert_called_once()

    def test_wikipedia_keeps_real_photos_and_drops_page_furniture(self):
        def img(title, mime="image/jpeg", w=1200, h=900):
            return {"title": title, "imageinfo": [{"mime": mime, "width": w, "height": h,
                                                   "url": f"https://u/{title}", "thumburl": f"https://t/{title}",
                                                   "thumbwidth": 1280, "thumbheight": 960,
                                                   "extmetadata": {"Artist": {"value": "<a>Someone</a>"}}}]}
        pages = {str(i): p for i, p in enumerate([
            img("File:Ann Dunham with son.jpg"),
            img("File:Flag of Indonesia.svg", mime="image/svg+xml"),
            img("File:Commons-logo.png", mime="image/png"),
            img("File:Tiny.jpg", w=120, h=90),
            img("File:Ann Dunham 1965.png", mime="image/png")])}
        r = mock.Mock()
        r.raise_for_status = lambda: None
        r.json.return_value = {"query": {"pages": pages}}
        with mock.patch.object(media.requests, "get", return_value=r):
            got = media.search_wikipedia_article_images("Anne Dunham")
        self.assertEqual([a.url for a in got], ["https://t/File:Ann Dunham with son.jpg",
                                               "https://t/File:Ann Dunham 1965.png"])
        self.assertEqual(got[0].attribution, "Someone")

    def test_no_more_than_two_person_photos_in_a_row(self):
        shots = [{"subjectType": "person", "visualType": "image"} for _ in range(7)]
        shots.insert(3, {"subjectType": "place", "visualType": "footage"})
        director.vary_person_stills(shots)
        kinds = [s["visualType"][0] for s in shots]   # i=image, f=footage
        self.assertEqual("".join(kinds), "iiffiifi")

    def test_a_failing_source_is_recorded_not_hidden(self):
        media.reset_cache()
        with mock.patch.object(media.requests, "get", side_effect=OSError("429 Too Many Requests")):
            self.assertEqual(media._cached_search(media.search_wikimedia, "Barack Obama"), [])
        st = media.source_stats()["search_wikimedia"]
        self.assertEqual((st["searches"], st["withResults"]), (1, 0))
        self.assertIn("429", media.source_stats()["wikimedia"]["recentErrors"][0])


class SequenceEditing(unittest.TestCase):
    """Plan and source runs of lines together, laid out by an editor call."""

    def _shots(self, subjects, kind="image"):
        return [{"subject": s, "subjectType": "person", "query": f"{s} photo",
                 "visualType": kind, "intent": f"photo of {s}"} for s in subjects]

    def test_model_sequences_are_kept_in_order_and_holes_are_filled(self):
        shots = self._shots(["Ann Dunham"] * 4 + ["Jakarta"] * 4)
        raw = {"sequences": [
            {"start": 0, "end": 2, "subject": "Ann Dunham", "subjectType": "person",
             "setting": "Ann Dunham, Hawaii 1960", "searches": [
                 {"q": "Ann Dunham photo", "kind": "image"},
                 {"q": "1960s Honolulu street footage", "kind": "footage"}]},
            # 3..4 skipped by the model
            {"start": 5, "end": 7, "subject": "Jakarta", "subjectType": "place",
             "setting": "Jakarta 1967", "searches": [{"q": "Jakarta 1967 footage"}]}]}
        seqs = director._validate_sequences(raw, 0, 8, shots)
        covered = [i for s in seqs for i in s["beats"]]
        self.assertEqual(covered, list(range(8)))
        self.assertEqual(seqs[0]["searches"][1]["kind"], "footage")
        self.assertEqual(seqs[-1]["searches"], [{"q": "Jakarta 1967 footage", "kind": "footage"}])

    def test_a_model_sequence_longer_than_an_editor_would_cut_is_split(self):
        shots = self._shots(["Barack Obama"] * 25)
        raw = {"sequences": [{"start": 0, "end": 24, "subject": "Barack Obama",
                              "searches": [{"q": "Barack Obama speech footage"}]}]}
        seqs = director._validate_sequences(raw, 0, 25, shots)
        self.assertEqual([len(s["beats"]) for s in seqs], [10, 10, 5])

    def test_without_a_model_same_subject_lines_group_together(self):
        segs = [seg(f"line {i}", i * 3, i * 3 + 3) for i in range(6)]
        shots = self._shots(["Ann Dunham", "Anne Dunham", "Stanley Ann Dunham",
                             "Madelyn Dunham", "Madelyn Dunham", "Jakarta"])
        with mock.patch.object(config, "DIRECTOR_API_KEY", ""):
            seqs = director.plan_sequences(segs, shots, {})
        self.assertEqual([s["beats"] for s in seqs], [[0, 1, 2], [3, 4], [5]])
        self.assertIn({"q": "Ann Dunham", "kind": "image"}, seqs[0]["searches"])

    def test_greedy_layout_prefers_the_wanted_kind_and_uses_each_shot_once(self):
        beats = [{"index": 0, "want": "image"}, {"index": 1, "want": "footage"},
                 {"index": 2, "want": "footage"}]
        shots = [{"id": "a", "kind": "footage", "score": 0.9},
                 {"id": "b", "kind": "image", "score": 0.8},
                 {"id": "c", "kind": "footage", "score": 0.7}]
        self.assertEqual(media.greedy_assign(beats, shots), {0: "b", 1: "a", 2: "c"})

    def test_the_model_layout_is_validated_and_topped_up(self):
        beats = [{"index": 0, "text": "x", "want": "footage"},
                 {"index": 1, "text": "y", "want": "footage"}]
        shots = [{"id": "s0", "kind": "footage"}, {"id": "s1", "kind": "footage"}]
        with mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "_chat_json", return_value={"assign": [
                    {"index": 0, "shot": "s1"}, {"index": 1, "shot": "s1"},  # s1 twice
                    {"index": 9, "shot": "s0"}]}):                            # unknown beat
            self.assertEqual(director.assign_shots(beats, shots), {0: "s1", 1: "s0"})

    def test_one_window_is_cut_into_consecutive_shots(self):
        cuts = []

        def cut(src, out, start, secs):
            cuts.append((round(start, 2), round(secs, 2)))
            return out

        with mock.patch.object(media, "_cut", side_effect=cut):
            shots = media.split_window("/w/win.mp4", "k", [3.5, 2.5, 4.0], "/w")
        self.assertEqual(cuts, [(0.0, 3.5), (3.5, 2.5), (6.0, 4.0)])
        self.assertEqual([o for _, o in shots], [0.0, 3.5, 6.0])

    def test_a_sequence_pool_fills_its_lines(self):
        jobs = {i: {"index": i, "seconds": 3.0, "visual_type": v, "context": f"line {i}",
                    "intent": f"intent {i}", "subject": "Ann Dunham", "subject_type": "person"}
                for i, v in enumerate(["image", "footage", "footage"])}
        pool_f = [{"kind": "footage", "video": "v1",
                   "asset": MediaAsset(kind="video", source="youtube",
                                       url=f"https://y/v1&t={n}", local_path=f"/w/seq_{n}.mp4")}
                  for n in range(2)]
        pool_i = [{"kind": "image", "video": "",
                   "asset": MediaAsset(kind="image", source="wikipedia", url="https://w/ann.jpg")}]
        seq = {"beats": [0, 1, 2], "subject": "Ann Dunham", "subjectType": "person",
               "setting": "Ann Dunham in Indonesia", "searches": [
                   {"q": "Jakarta 1967 footage", "kind": "footage"},
                   {"q": "Ann Dunham photo", "kind": "image"}]}
        used = set()
        with mock.patch.object(media, "_footage_pool", return_value=pool_f), \
                mock.patch.object(media, "_image_pool", return_value=pool_i):
            out = media.source_sequence(seq, jobs, "/w", used, threading.Lock(),
                                        require_cc=False, allow_youtube=True)
        self.assertEqual(out[0].url, "https://w/ann.jpg")
        self.assertEqual({out[1].url, out[2].url}, {"https://y/v1&t=0", "https://y/v1&t=1"})
        self.assertEqual(out[1].intent, "intent 1")
        self.assertEqual(len(used), 3)

    def test_lines_a_pool_cannot_fill_fall_back_to_per_line_search(self):
        jobs = [{"index": i, "query": f"q{i}", "seconds": 3.0, "subject": "Ann Dunham"}
                for i in range(3)]
        per_line = []

        def fake(query, seconds, work_dir, **kw):
            per_line.append(query)
            return MediaAsset(kind="image", source="wikimedia", url=f"https://x/{query}")

        pooled = {0: MediaAsset(kind="video", source="youtube", url="https://y/a&t=0",
                                local_path="/w/seq_a.mp4")}
        with mock.patch.object(media, "source_sequence", return_value=pooled), \
                mock.patch.object(media, "source_for_segment", side_effect=fake), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")):
            media.reset_cache()
            out = media.source_many(jobs, "/tmp", workers=1,
                                    sequences=[{"beats": [0, 1, 2], "searches": []}])
        self.assertEqual(out[0].url, "https://y/a&t=0")
        self.assertEqual(sorted(per_line), ["q1", "q2"])        # line 0 never searched alone
        self.assertTrue(all(out))


class VisionJudgeEventsAndQuality(unittest.TestCase):
    """The judge checks a news beat against its own event, and rates the footage."""

    def _judge(self, reply, event):
        from src import vision
        sent = []

        def ask(messages, max_tokens):
            sent.append(messages[0]["content"])
            return reply, "m"

        vision.reset()
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision.os.path, "exists", return_value=True), \
                mock.patch.object(vision, "_fingerprint", return_value="fp"), \
                mock.patch.object(vision, "sample_frames", return_value=["AAAA"]), \
                mock.patch.object(vision, "_ask", side_effect=ask):
            verdict = vision.judge("/w/a.mp4", "Davenport Iowa flood 2026", "", event=event)
        return verdict, sent

    def test_an_event_beat_is_judged_against_that_event(self):
        reply = '{"description":"flood","score":0.8,"quality":0.7}'
        _, plain = self._judge(reply, event=False)
        _, event = self._judge(reply, event=True)
        self.assertNotIn("ONE SPECIFIC REAL EVENT", plain[0])
        self.assertIn("ONE SPECIFIC REAL EVENT", event[0])

    def test_quality_is_read_clamped_and_optional(self):
        from src import vision
        v, _ = self._judge('{"description":"x","score":0.9,"quality":1.7}', event=False)
        self.assertEqual(v["quality"], 1.0)
        v, _ = self._judge('{"description":"x","score":0.9}', event=False)
        self.assertIsNone(v["quality"])
        self.assertTrue(vision.acceptable(v))

    def test_unwatchable_footage_is_rejected_even_when_it_matches(self):
        from src import vision
        v = {"score": 0.95, "quality": 0.1, "has_text_or_watermark": False,
             "is_talking_head": False, "description": ""}
        self.assertFalse(vision.acceptable(v))
        v["quality"] = 0.6
        self.assertTrue(vision.acceptable(v))

    def test_the_gate_tells_the_judge_when_a_beat_is_an_event(self):
        seen = []

        def judge(path, intent, context, event=False):
            seen.append(event)
            return None

        with mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media.vision, "judge", side_effect=judge):
            media._vision_gate("/w/a.mp4", "flood", "", "t")
            tok = media._EVENT_WINDOW.set("event")
            try:
                media._vision_gate("/w/a.mp4", "flood", "", "t")
            finally:
                media._EVENT_WINDOW.reset(tok)
        self.assertEqual(seen, [False, True])

    def test_quality_reaches_the_scene(self):
        a = MediaAsset(kind="video", source="youtube", url="q").apply_verdict(
            {"description": "d", "score": 0.8, "quality": 0.66, "model": "m"}, "i")
        self.assertEqual(a.to_scene_media()["qualityScore"], 0.66)


if __name__ == "__main__":
    unittest.main(verbosity=2)
