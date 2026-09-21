"""
Worker test suite. Runs offline — no network, no whisper, no Remotion.

    python -m unittest discover -s tests -v

The tests that matter most here are the contract ones. This pipeline spans
Python and TypeScript, and the failures that actually cost a render are the
silent ones: a template the director emits that the renderer does not draw, a
scene track that does not tile the narration, a document that reaches headless
Chrome with no audio. Each of those has a test below.
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, director, geocode, media, storage, timeline  # noqa: E402
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


# --------------------------------------------------------------------------- #
# Pacing — the VidRush editing signature
# --------------------------------------------------------------------------- #

class Pacing(unittest.TestCase):
    """
    Cut rate is the thing being reproduced: 16.8-21.8 cuts/min, median ~3s,
    measured from four reference renders. Drifting out of that band means the
    output stops looking like the reference, so it is pinned by a test.
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
        segments = segment_words(words_from(self.NARRATION))
        duration = segments[-1].end
        cpm = len(segments) / (duration / 60)
        self.assertGreaterEqual(cpm, 15.0, f"too slow: {cpm:.1f} cuts/min")
        self.assertLessEqual(cpm, 24.0, f"too fast: {cpm:.1f} cuts/min")

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
        shots, kind, warnings = director.plan(segments, title="Dry Valley", allow_maps=False)
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
            media.youtube_clip("colombia earthquake", "/tmp/x", seconds=4.0, **kwargs)
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

    def test_aspect_filter_compares_against_a_literal(self):
        # A match-filter compares a field to a constant. "width > height"
        # parses `height` as a string and every candidate dies on int > str.
        cmd = self._captured_yt_cmd(require_cc=True)
        flt = cmd[cmd.index("--match-filter") + 1]
        self.assertIn("aspect_ratio", flt)
        self.assertNotIn("width > height", flt)
        self.assertIn("Creative Commons", flt)

    def test_licence_filter_is_absent_when_not_required(self):
        cmd = self._captured_yt_cmd(require_cc=False)
        flt = cmd[cmd.index("--match-filter") + 1]
        self.assertNotIn("Creative Commons", flt)

    def test_success_is_read_from_the_printed_path_not_the_exit_code(self):
        # --max-downloads makes yt-dlp exit 101 on success.
        class Result:
            returncode, stderr = 101, ""
            stdout = __file__          # a path that exists

        original = media.subprocess.run
        media.subprocess.run = lambda cmd, **_: Result()
        try:
            asset = media.youtube_clip("x", "/tmp/x", seconds=2.0)
        finally:
            media.subprocess.run = original
        self.assertIsNotNone(asset)
        self.assertEqual(asset.source, "youtube")

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

    def test_running_out_of_options_keeps_the_repeat_but_flags_it(self):
        # Only two distinct assets exist for six scenes asking the same thing.
        out, _ = self._run(["the lake"] * 6, per_query=2)
        placed = [a for a in out if a]
        self.assertEqual(len(placed), 6, "must not render black rather than repeat")
        repeats = [a for a in placed if a.review_required]
        self.assertTrue(repeats, "an unavoidable repeat must be flagged for review")
        self.assertIn("Repeat", repeats[0].review_reason)

    def test_youtube_identity_is_the_video_not_the_query(self):
        # Two different searches landing on the same upload count as one.
        a = MediaAsset(kind="video", source="youtube", url="lake powell",
                       local_path="/w/yt_XYZ.mp4")
        b = MediaAsset(kind="video", source="youtube", url="glen canyon dam",
                       local_path="/w/yt_XYZ.mp4")
        self.assertEqual(a.identity, b.identity)

    def test_youtube_rejects_an_already_used_upload(self):
        seen = {}

        class Result:
            returncode, stderr = 0, ""
            stdout = ""

        tmp = os.path.join(ROOT, "out", "_t_yt", "yt_TAKEN.mp4")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        open(tmp, "wb").close()
        Result.stdout = tmp

        original = media.subprocess.run
        media.subprocess.run = lambda cmd, **k: seen.update(cmd=cmd) or Result()
        try:
            got = media.youtube_clip("lake", os.path.dirname(tmp), seconds=3.0,
                                     used={"yt:TAKEN"})
        finally:
            media.subprocess.run = original
        self.assertIsNone(got, "an already-used upload must be rejected")
        self.assertFalse(os.path.exists(tmp), "the redundant download is cleaned up")

    def test_skip_moves_the_playlist_window(self):
        seen = {}

        class Result:
            returncode, stdout, stderr = 0, "", ""

        original = media.subprocess.run
        media.subprocess.run = lambda cmd, **k: seen.update(cmd=cmd) or Result()
        try:
            media.youtube_clip("lake", "/tmp/x", seconds=3.0, skip=3)
        finally:
            media.subprocess.run = original
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--playlist-items") + 1], "4-15")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
