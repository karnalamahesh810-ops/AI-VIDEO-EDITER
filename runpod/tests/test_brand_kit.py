"""
The brand kit (src/brandkit.py): read safely, its picks honoured by every
planning path, an empty or odd pick list never breaking a video, the intro
and outro timed around the narration (and the split render cutting cleanly
around them), the watermark's props, and the renderer's half of the contract.
"""
import json
import os
import re
import unittest
from unittest import mock

from src import brandkit, config, fanout, templates, timeline, treatments
from src.media import MediaAsset
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion", "src")
FPS = 30


def _words(text, start, wps=2.6):
    out, t = [], start
    for token in text.split():
        out.append(Word(text=token, start=round(t, 3), end=round(t + 1.0 / wps, 3)))
        t += 1.0 / wps + (0.35 if token[-1:] in ".!?" else 0.02)
    return out


def _seg(i, text, dur=6.0):
    return Segment(text=text, start=i * dur, end=(i + 1) * dur, words=_words(text, i * dur))


LINES = ["On September 12, 2026, Lake Mead fell to 26 percent of capacity.",
         "The dam holds back 9.3 trillion gallons when it is full.",
         "Officials said the drop cost the region $1.4 billion.",
         "In 2020 the lake stood at 40 percent; by 2026 it was 26 percent.",
         "Boat ramps at Boulder Harbor now end in dry gravel.",
         "About 25 million people depend on this water every day.",
         "Hoover Dam was finished in 1936 after five years of work.",
         "Plain words about the water here, nothing more."]


def _build(inp, assets=None, lines=LINES):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None, "subject": f"place {i}"}
             for i in range(len(segs))]
    if assets is None:
        assets = [MediaAsset(kind="video", source="youtube", url=f"file:///tmp/{i}.mp4", local_path=f"file:///tmp/{i}.mp4")
                  for i in range(len(segs))]
    with mock.patch.object(config, "TREATMENTS", True):
        return timeline.build(segs, shots, assets, audio_url="file:///tmp/vo.mp3",
                              audio_duration=len(segs) * 6.0, inp=dict(inp))


def _kit(**over):
    raw = {"id": "k1", "name": "Weather Alert", "accent": "#f4a100", "accent2": "#2EC4B6", "font": "oswald",
           "caption_style": "news",
           "watermark": {"url": "https://example.supabase.co/storage/v1/object/public/brand-assets/u/logo.png",
                         "position": "bottom-right", "size": 0.12, "opacity": 0.9},
           "picks": {"looks": "all", "transitions": "all", "music": "all", "sfx": True, "density": "auto"}}
    raw.update(over)
    return raw


def _templates_of(doc):
    ids = [o.get("template") for o in doc["overlays"] if o.get("template")]
    ids += [s["animation"].get("template") for s in doc["scenes"] if isinstance(s.get("animation"), dict)]
    return [i for i in ids if i]


# --------------------------------------------------------------------------- #
# Reading a kit
# --------------------------------------------------------------------------- #

class Parse(unittest.TestCase):
    def test_no_kit_is_none(self):
        for raw in (None, {}, "kit", 3, []):
            self.assertIsNone(brandkit.parse(raw))

    def test_identity_is_normalised(self):
        k = brandkit.parse(_kit(accent="f40", accent2="#F4A100"))
        self.assertEqual(k["accent"], "#FF4400")
        self.assertEqual(k["accent2"], "#F4A100")
        self.assertEqual(k["font"], "Oswald")
        self.assertEqual(k["caption_style"], "news_bold")      # an older style id: its closest new style
        self.assertEqual(k["watermark"]["position"], "bottom-right")

    def test_odd_values_are_dropped_not_fatal(self):
        k = brandkit.parse(_kit(accent="blue-ish", font="Comic Sans", caption_style="disco",
                                watermark={"url": "file:///etc/passwd", "size": 99}))
        self.assertIsNone(k["accent"])
        self.assertIsNone(k["font"])
        self.assertIsNone(k["caption_style"])
        self.assertIsNone(k["watermark"])
        self.assertTrue(k["warnings"])

    def test_the_same_second_colour_is_no_second_colour(self):
        self.assertIsNone(brandkit.parse(_kit(accent="#112233", accent2="#112233"))["accent2"])

    def test_numbers_are_clamped(self):
        wm = brandkit.parse(_kit(watermark={"url": "https://x.co/l.png", "size": 5, "opacity": -1,
                                            "position": "middle"}))["watermark"]
        self.assertEqual((wm["size"], wm["opacity"], wm["position"]),
                         (brandkit.LOGO_SIZE_MAX, brandkit.LOGO_OPACITY_MIN, brandkit.DEFAULT_POSITION))
        card = brandkit.parse(_kit(outro={"kind": "card", "seconds": 999}))["outro"]
        self.assertEqual(card["seconds"], brandkit.CARD_MAX_SECONDS)
        self.assertEqual(card["text"], "Subscribe for more")      # never a blank card

    def test_links_must_be_public_web_links(self):
        for bad in ("file:///tmp/a.png", "/tmp/a.png", "http://127.0.0.1/a.png", "http://10.0.0.5/a.png",
                    "http://169.254.169.254/latest", "http://localhost:8080/a.png", "ftp://x.co/a.png", ""):
            self.assertEqual(brandkit.safe_url(bad), "", bad)
        self.assertTrue(brandkit.safe_url("https://wrc.supabase.co/storage/v1/object/public/brand-assets/u/a.png"))

    def test_picks_default_to_everything(self):
        p = brandkit.parse({"name": "x"})["picks"]
        self.assertEqual(p, {"looks": "all", "transitions": "all", "music": "all", "sfx": True, "density": "auto"})

    def test_unknown_picks_are_ignored_and_none_known_means_all(self):
        k = brandkit.parse(_kit(picks={"looks": ["NUM_PERCENT_V1", "NOT_A_LOOK"], "transitions": ["fade", "warp"],
                                       "music": ["tense", "polka"]}))
        self.assertEqual(k["picks"]["looks"], ["NUM_PERCENT_V1"])
        self.assertEqual(k["picks"]["transitions"], ["fade"])
        self.assertEqual(k["picks"]["music"], ["suspense"])        # a mood word stands for its genre
        k = brandkit.parse(_kit(picks={"looks": ["RENAMED_1", "RENAMED_2"], "transitions": 7}))
        self.assertEqual(k["picks"]["looks"], "all")
        self.assertEqual(k["picks"]["transitions"], "all")

    def test_an_empty_list_means_none(self):
        k = brandkit.parse(_kit(picks={"looks": [], "transitions": [], "music": [], "sfx": "no",
                                       "density": "less"}))
        self.assertEqual(k["picks"], {"looks": [], "transitions": [], "music": "none", "sfx": False,
                                      "density": "minimal"})


# --------------------------------------------------------------------------- #
# The picks in force
# --------------------------------------------------------------------------- #

class Scope(unittest.TestCase):
    def test_banned_answers_for_looks_outside_the_kit_only_inside_the_scope(self):
        kit = brandkit.parse(_kit(picks={"looks": ["NUM_PERCENT_V1"]}))
        self.assertFalse(templates.banned("MAP_LOCATION_ZOOM_V1"))
        with brandkit.scope(kit):
            self.assertTrue(templates.banned("MAP_LOCATION_ZOOM_V1"))
            self.assertFalse(templates.banned("NUM_PERCENT_V1"))
            self.assertEqual([t["id"] for t in templates.for_cue("percent")], ["NUM_PERCENT_V1"])
            # The owner's bans stand whatever a kit says.
            with templates.only({"HEADLINE_TITLE_V1"}):
                self.assertTrue(templates.banned("HEADLINE_TITLE_V1"))
        self.assertFalse(templates.banned("MAP_LOCATION_ZOOM_V1"))
        self.assertIsNone(templates.allowed())

    def test_the_watermark_corner_is_kept_clear_of_compact_figures(self):
        kit = brandkit.parse(_kit())
        with brandkit.scope(kit):
            self.assertEqual(treatments._corners(), ["bottom-left"])
        self.assertEqual(treatments._corners(), list(treatments._CORNERS))


class PicksHonoured(unittest.TestCase):
    def test_without_a_kit_nothing_changes(self):
        doc = _build({})
        self.assertNotIn("brand", doc)
        self.assertNotIn("brandKit", doc["meta"])
        self.assertEqual(brandkit.layout(doc), (0, doc["durationInFrames"], 0, doc["durationInFrames"]))

    def test_only_allowed_looks_are_planned(self):
        every = _templates_of(_build({}))
        self.assertTrue(every)
        allowed = sorted(set(every))[: max(1, len(set(every)) // 2)]
        doc = _build({"brand_kit": _kit(picks={"looks": allowed})})
        used = _templates_of(doc)
        self.assertTrue(set(used) <= set(allowed), set(used) - set(allowed))
        self.assertEqual(doc["meta"]["brandKit"]["picks"]["looks"], allowed)

    def test_a_cue_whose_looks_are_off_takes_another_allowed_look(self):
        # Only number looks other than the ones the planner first picks: the figures still show.
        number_looks = [t["id"] for t in templates.for_cue("big-number") + templates.for_cue("percent")
                        if treatments.auto_ok(t["id"])]
        first = set(_templates_of(_build({})))
        others = [t for t in number_looks if t not in first]
        self.assertTrue(others)
        doc = _build({"brand_kit": _kit(picks={"looks": others})})
        used = _templates_of(doc)
        self.assertTrue(used, "the figures must still get a graphic from the allowed looks")
        self.assertTrue(set(used) <= set(others))

    def test_empty_looks_never_break_a_video(self):
        doc = _build({"brand_kit": _kit(picks={"looks": []})})
        self.assertEqual(_templates_of(doc), [])
        timeline.validate(doc, require_media=True)
        for sc in doc["scenes"]:
            self.assertNotEqual(sc["media"]["type"], "animation")

    def test_a_beat_with_no_footage_and_no_allowed_look_is_never_empty(self):
        assets = [MediaAsset(kind="video", source="youtube", url=f"file:///tmp/{i}.mp4", local_path=f"file:///tmp/{i}.mp4")
                  for i in range(len(LINES))]
        assets[0] = None                    # the 26 percent line: a full-screen figure without a kit
        plain = _build({}, assets=list(assets))
        self.assertEqual(plain["scenes"][0]["media"]["type"], "animation")
        kit = brandkit.parse(_kit(picks={"looks": []}))
        doc = _build({"brand_kit": _kit(picks={"looks": []})}, assets=list(assets))
        self.assertNotEqual(doc["scenes"][0]["media"]["type"], "animation")
        # The plan's last resort (handler.do_plan: gapfill then enforce): a
        # neighbour held over it, else the line as a text card - never an
        # empty frame - and at render the quality check's text scene.
        from src import gapfill, quality
        with brandkit.scope(kit):
            gapfill.hold_or_animate(doc)
        brandkit.enforce(doc, kit)
        for sc in doc["scenes"]:
            if sc["media"]["type"] == "color":
                self.assertTrue([o for o in doc["overlays"] if o.get("type") == "highlight"
                                 and o["startFrame"] == sc["startFrame"]], sc["id"])
                with brandkit.scope(kit):
                    quality.text_scene(doc, sc)
                self.assertEqual(sc["media"]["type"], "animation")
        timeline.validate(doc, require_media=True)

    def test_enforce_swaps_a_stray_look_for_the_closest_allowed_one_or_drops_it(self):
        kit = brandkit.parse(_kit(picks={"looks": ["NUM_BIG_COUNTER_V1"]}))
        doc = {"fps": 30, "durationInFrames": 300, "scenes": [], "sfx": [{"name": "x", "startFrame": 60,
                                                                            "kind": "overlay"}],
               "overlays": [
                   {"template": "NUM_PERCENT_V1", "type": "stat", "value": 26.0, "suffix": "%", "text": "CAPACITY",
                    "startFrame": 10, "durationInFrames": 60},
                   {"template": "MAP_LOCATION_ZOOM_V1", "type": "map", "startFrame": 60, "durationInFrames": 60,
                    "locations": [{"label": "Nevada", "lat": 38.0, "lon": -117.0}]},
                   {"type": "title", "text": "Job title card", "startFrame": 0, "durationInFrames": 30}]}
        out = brandkit.enforce(doc, kit)
        self.assertEqual(out["swapped"], 1)
        self.assertEqual(out["dropped"], 1)
        swapped = doc["overlays"][0]
        self.assertEqual(swapped["template"], "NUM_BIG_COUNTER_V1")
        self.assertEqual((swapped["value"], swapped["startFrame"], swapped["durationInFrames"]), (26.0, 10, 60))
        self.assertEqual(doc["overlays"][1]["type"], "title")    # not a library look: kept
        self.assertEqual(doc["sfx"], [])                          # the dropped map's own sound went with it

    def test_a_side_paths_graphic_takes_the_brand_colours(self):
        # The last resort resolves a graphic with the style pack's colour (gold): the kit's accent wins.
        kit = brandkit.parse(_kit())
        doc = {"fps": 30, "durationInFrames": 300, "meta": {"stylePack": "documentary"}, "overlays": [
            {"template": "TEXT_QUESTION_V1", "type": "typewriter", "theme": "gold", "startFrame": 0, "durationInFrames": 60}],
            "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 300, "media": {"type": "animation"},
                        "animation": {"template": "NUM_PERCENT_V1", "type": "stat", "value": 26.0, "theme": "gold"}}]}
        out = brandkit.enforce(doc, kit)
        self.assertEqual(doc["scenes"][0]["animation"]["theme"], "accent2")     # a figure: the second colour
        self.assertEqual(doc["overlays"][0]["theme"], "gold")    # a look with a colour of its own keeps it (white question)
        self.assertGreaterEqual(out["recoloured"], 1)

    def test_closest_look_needs_a_shared_cue_and_the_overlays_data(self):
        self.assertIsNone(brandkit.closest_look("MAP_LOCATION_ZOOM_V1", {"NUM_PERCENT_V1"},
                                                needs=("locations",)))
        self.assertEqual(brandkit.closest_look("NUM_PERCENT_V1", None), "NUM_PERCENT_V1")

    def test_the_kit_colour_replaces_the_packs_and_charts_take_the_second(self):
        doc = _build({"brand_kit": _kit()})
        self.assertEqual(doc["captions"]["accent"], "#F4A100")
        self.assertEqual(doc["captions"]["fontFamily"], "Oswald")
        self.assertEqual(doc["captions"]["style"], "news_bold")
        themed = {o.get("theme") for o in doc["overlays"]}
        self.assertFalse(themed & set(templates.load()["stylePacks"]["documentary"]["theme"].split()))
        seconds = 0
        for o in doc["overlays"]:
            cat = (templates.get(o.get("template") or "") or {}).get("category")
            if cat in brandkit.SECOND_COLOUR_CATEGORIES and o.get("template") not in treatments.VR_LOOKS:
                # (The date looks keep their own lettering theme.)
                self.assertEqual(o.get("theme"), "accent2", o.get("template"))
                seconds += 1
        self.assertTrue(seconds)

    def test_the_document_carries_the_brand_block_without_frames(self):
        doc = _build({"brand_kit": _kit(intro={"url": "https://x.co/i.mp4", "seconds": 4},
                                        outro={"kind": "card", "title": "Thanks"})})
        self.assertEqual(doc["brand"]["accent"], "#F4A100")
        self.assertEqual(doc["brand"]["watermark"]["size"], 0.12)
        self.assertNotIn("frames", doc["brand"]["intro"])
        self.assertNotIn("frames", doc["brand"]["outro"])
        # A saved plan never shifts in the editor: no frames, no intro or outro drawn.
        self.assertEqual(brandkit.layout(doc), (0, doc["durationInFrames"], 0, doc["durationInFrames"]))


class Transitions(unittest.TestCase):
    def test_the_nearest_allowed_transition_or_a_hard_cut(self):
        self.assertEqual(brandkit.nearest_transition("light-leak", {"film-burn", "glitch"}), "film-burn")
        self.assertEqual(brandkit.nearest_transition("whip-pan", {"fade"}), "none")
        self.assertEqual(brandkit.nearest_transition("fade", None), "fade")
        self.assertEqual(brandkit.nearest_transition("none", {"fade"}), "none")

    def test_only_the_kits_transitions_are_planned(self):
        doc = _build({"brand_kit": _kit(picks={"transitions": ["fade"]}), "style": "news"})
        used = {s["transition"] for s in doc["scenes"]}
        self.assertTrue(used <= {"none", "fade"}, used)

    def test_no_transitions_means_hard_cuts_and_no_pack_clips(self):
        doc = _build({"brand_kit": _kit(picks={"transitions": []}), "style": "news"})
        self.assertEqual({s["transition"] for s in doc["scenes"]}, {"none"})
        self.assertEqual(brandkit.pack_clips(brandkit.parse(_kit(picks={"transitions": []}))), frozenset())

    def test_pack_clips_are_limited(self):
        kit = brandkit.parse(_kit(picks={"transitions": ["pack:mlt3", "fade"]}))
        self.assertEqual(brandkit.pack_clips(kit), frozenset({"mlt3"}))
        self.assertEqual(brandkit.pack_clips(brandkit.parse(_kit(picks={"transitions": ["pack"]}))),
                         frozenset(timeline.pack_meta()))
        self.assertIsNone(brandkit.pack_clips(None))


class Music(unittest.TestCase):
    def _bgm(self, inp, story="the lake"):
        brandkit.prepare_input(inp)
        return timeline._bgm_for(inp, None, {"kind": "news"}, 600.0, story_text=story)

    def test_the_kits_genres_only(self):
        bgm = self._bgm({"brand_kit": _kit(picks={"music": ["investigative"]})})
        self.assertEqual(bgm["genre"], "investigative")         # a news story's mood is suspense: not liked

    def test_a_liked_track(self):
        bgm = self._bgm({"brand_kit": _kit(picks={"music": ["crime-v1"]})})
        self.assertEqual(bgm["track"], "crime-v1")

    def test_no_music(self):
        self.assertIsNone(self._bgm({"brand_kit": _kit(picks={"music": "none"})}))

    def test_the_editors_own_choice_wins(self):
        bgm = self._bgm({"brand_kit": _kit(picks={"music": ["investigative"]}), "bgm_genre": "suspense"})
        self.assertEqual(bgm["genre"], "suspense")

    def test_nearest_genre(self):
        genre, track = brandkit.pick_music("suspense", "suspense-v2", 600.0, {"crime-v1", "investigative-v5"})
        self.assertEqual((genre, track), ("crime", "crime-v1"))


class PrepareInput(unittest.TestCase):
    def test_the_kit_fills_what_the_job_left_open(self):
        inp = {"brand_kit": _kit(picks={"sfx": False, "density": "minimal"}), "brand": {"accent": "#000000"}}
        brandkit.prepare_input(inp)
        self.assertEqual((inp["graphics_density"], inp["sfx"], inp["caption_style"]), ("minimal", False, "news_bold"))
        self.assertEqual(inp["brand"], {"accent": "#F4A100", "fontFamily": "Oswald"})
        self.assertTrue(inp["_brand_music"])

    def test_the_jobs_own_choices_win(self):
        inp = {"brand_kit": _kit(picks={"sfx": False, "density": "minimal"}), "graphics_density": "rich",
               "sfx": True, "caption_style": "modern", "bgm_url": "https://x.co/m.mp3"}
        brandkit.prepare_input(inp)
        self.assertEqual((inp["graphics_density"], inp["sfx"], inp["caption_style"]), ("rich", True, "modern"))
        self.assertNotIn("_brand_music", inp)

    def test_no_kit_no_change(self):
        inp = {"style": "news"}
        self.assertIsNone(brandkit.prepare_input(inp))
        self.assertEqual(set(inp), {"style", "_brand_kit"})


# --------------------------------------------------------------------------- #
# The intro, the outro and the watermark at render time
# --------------------------------------------------------------------------- #

def _render_doc(body=900):
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": body,
            "audio": {"url": "https://x.co/vo.mp3"}, "captions": {"accent": "#FFD400", "fontFamily": "Inter"},
            "meta": {"voiceLufs": -20.0},
            "scenes": [{"id": f"s{i}", "startFrame": i * 90, "durationInFrames": 90, "transition": "none",
                        "media": {"type": "video", "url": f"https://x.co/{i}.mp4"}} for i in range(body // 90)],
            "overlays": [], "sfx": []}


class PrepareRender(unittest.TestCase):
    def _prepare(self, kit, doc=None, image=True, video=True):
        doc = doc or _render_doc()

        def fetch(url, path, most):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64 if image else b"<html>nope</html>")
            return path

        def probe(path):
            return {"video": video, "audio": True, "duration": 4.5 if "intro" in path else 30.0}

        import tempfile
        with tempfile.TemporaryDirectory() as work:
            rep = brandkit.prepare_render(doc, {"brand_kit": kit}, work, fetch=fetch, probe=probe,
                                          measure=lambda p: -14.0)
        return doc, rep

    def test_intro_and_outro_frames_and_levels(self):
        doc, rep = self._prepare(_kit(intro={"url": "https://x.co/intro.mp4"},
                                      outro={"kind": "video", "url": "https://x.co/outro.mp4"}))
        self.assertEqual(doc["brand"]["intro"]["frames"], 135)          # 4.5 s
        self.assertEqual(doc["brand"]["outro"]["frames"], 600)          # 30 s capped at 20 s
        self.assertAlmostEqual(doc["brand"]["intro"]["volume"], round(10 ** (-6 / 20), 3))   # -14 brought to -20
        self.assertEqual(brandkit.layout(doc), (135, 900, 600, 1635))
        self.assertEqual(brandkit.total_frames(doc), 1635)
        self.assertEqual(rep["intro"], 4.5)
        self.assertEqual(doc["captions"]["accent"], "#F4A100")         # the kit as it is now

    def test_an_end_card(self):
        doc, _ = self._prepare(_kit(outro={"kind": "card", "title": "Thanks for watching", "seconds": 7}))
        self.assertEqual(doc["brand"]["outro"]["frames"], 210)
        self.assertEqual(brandkit.layout(doc)[2], 210)

    def test_watermark_props(self):
        doc, rep = self._prepare(_kit())
        self.assertEqual(doc["brand"]["watermark"], {
            "url": "https://example.supabase.co/storage/v1/object/public/brand-assets/u/logo.png",
            "position": "bottom-right", "size": 0.12, "opacity": 0.9})
        self.assertTrue(rep["watermark"])
        self.assertEqual(brandkit.layout(doc), (0, 900, 0, 900))       # a logo alone adds no frames

    def test_a_file_that_cannot_be_read_is_left_out_never_fatal(self):
        doc, rep = self._prepare(_kit(intro={"url": "https://x.co/intro.mp4"}), image=False, video=False)
        self.assertNotIn("watermark", doc["brand"])
        self.assertNotIn("intro", doc["brand"])
        self.assertEqual(len(rep["dropped"]), 2)
        self.assertTrue(any("Brand kit" in w for w in doc["meta"]["warnings"]))
        self.assertEqual(brandkit.layout(doc), (0, 900, 0, 900))

    def test_no_kit_anywhere_no_brand(self):
        doc = _render_doc()
        self.assertEqual(brandkit.prepare_render(doc, {}, "."), {})
        self.assertNotIn("brand", doc)

    def test_the_plans_own_block_is_used_without_a_job_kit(self):
        doc = _render_doc()
        doc["brand"] = brandkit.doc_brand(brandkit.parse(_kit(outro={"kind": "card", "title": "Bye"})))
        _doc, rep = self._prepare(None, doc=doc)
        self.assertEqual(doc["brand"]["outro"]["frames"], 180)
        self.assertEqual(rep["kit"], "Weather Alert")


class SplitRender(unittest.TestCase):
    def _doc(self):
        doc = _render_doc(1800)
        doc["brand"] = {"intro": {"url": "https://x.co/i.mp4", "frames": 150},
                        "outro": {"kind": "card", "frames": 180, "text": "Subscribe"}}
        return doc

    def test_cuts_are_the_seams_and_shifted_scene_starts(self):
        clean, visual, every = fanout.chunk_cuts(self._doc())
        self.assertIn(150, clean)              # the end of the intro
        self.assertIn(150 + 1800, clean)       # the start of the outro
        self.assertIn(150 + 90, clean)         # scene 1 starts 90 frames into the narration
        self.assertNotIn(90, every)

    def test_chunks_cover_every_frame_and_never_cut_inside_a_brand_clip(self):
        doc = self._doc()
        for n in (2, 3, 5, 8, 13):
            ranges = fanout.plan_chunks(doc, n, 30)
            self.assertEqual(ranges[0][0], 0)
            self.assertEqual(ranges[-1][1], 150 + 1800 + 180 - 1)
            for (a0, b0), (a1, _b1) in zip(ranges, ranges[1:]):
                self.assertEqual(b0 + 1, a1)
                self.assertFalse(0 < a1 < 150 or 1950 < a1 < 2130, (n, a1))

    def test_chunk_hash_reads_the_narration_after_the_intro(self):
        doc = self._doc()
        plain = _render_doc(1800)
        # The intro's frames hash apart from the narration's first frames.
        self.assertNotEqual(fanout.chunk_hash(doc, 0, 149), fanout.chunk_hash(doc, 150, 299))
        # Without a brand block the hash is what it always was (old manifests still match).
        self.assertEqual(fanout.chunk_hash(plain, 0, 299),
                         fanout.chunk_hash(json.loads(json.dumps(plain)), 0, 299))

    def test_layout_counts_what_the_renderer_draws(self):
        # A local copy (a chunk's prefetch) plays like its link; a clip with no file or link does not.
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            local = fh.name
        try:
            doc = _render_doc(300)
            doc["brand"] = {"intro": {"url": local, "frames": 60}, "outro": {"kind": "video", "url": "/no/such.mp4",
                                                                          "frames": 90}}
            self.assertEqual(brandkit.layout(doc), (60, 300, 0, 360))
            doc["brand"]["intro"]["frames"] = 10_000          # never past the limit
            self.assertEqual(brandkit.layout(doc)[0], int(brandkit.INTRO_MAX_SECONDS * FPS))
        finally:
            os.remove(local)

    def test_the_scan_is_read_in_the_narrations_seconds(self):
        doc = self._doc()
        res = {"ok": True, "duration": 71.0, "black": [(0.0, 4.0), (10.0, 12.0), (65.5, 71.0)],
               "frozen": [], "silent": [(66.0, 71.0)], "audio": True}
        body = brandkit.body_scan(doc, res)
        self.assertEqual(body["black"], [(5.0, 7.0)])
        self.assertEqual(body["silent"], [])
        self.assertEqual(body["duration"], 60.0)


# --------------------------------------------------------------------------- #
# The renderer's half
# --------------------------------------------------------------------------- #

class RendererContract(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(REMOTION, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_limits_match(self):
        src = self._read("components", "brand", "brandLayout.ts")

        def num(name):
            return float(re.search(rf"\b{name}:\s*([\d.]+)", src).group(1))
        self.assertEqual(num("logoSizeMin"), brandkit.LOGO_SIZE_MIN)
        self.assertEqual(num("logoSizeMax"), brandkit.LOGO_SIZE_MAX)
        self.assertEqual(num("logoSizeDefault"), brandkit.LOGO_SIZE_DEFAULT)
        self.assertEqual(num("logoOpacityMin"), brandkit.LOGO_OPACITY_MIN)
        self.assertEqual(num("logoOpacityMax"), brandkit.LOGO_OPACITY_MAX)
        self.assertEqual(num("logoOpacityDefault"), brandkit.LOGO_OPACITY_DEFAULT)
        self.assertEqual(num("introMaxSeconds"), brandkit.INTRO_MAX_SECONDS)
        self.assertEqual(num("outroMaxSeconds"), brandkit.OUTRO_MAX_SECONDS)
        self.assertEqual(num("cardMaxSeconds"), brandkit.CARD_MAX_SECONDS)
        positions = re.search(r"positions:\s*\[([^\]]+)\]", src).group(1)
        self.assertEqual(tuple(re.findall(r'"([a-z-]+)"', positions)), brandkit.POSITIONS)
        self.assertIn(f'defaultPosition: "{brandkit.DEFAULT_POSITION}"', src)

    def test_the_editor_only_list_is_current(self):
        # The app's picks grid leaves these out (a pick of one could never show).
        import importlib.util
        spec = importlib.util.spec_from_file_location("weo", os.path.join(ROOT, "scripts", "write_editor_only.py"))
        weo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(weo)
        with open(weo.PATH, encoding="utf-8") as fh:
            saved = json.load(fh)["ids"]
        self.assertEqual(saved, weo.editor_only(), "stale: run python scripts/write_editor_only.py")

    def test_fonts_match(self):
        src = self._read("components", "brand", "brandFonts.ts")
        self.assertEqual(tuple(re.findall(r'^\s*"([^"]+)":', src, re.M)), brandkit.FONTS)

    def test_the_composition_is_intro_body_outro_long(self):
        self.assertIn("brandFrames(props).total", self._read("Root.tsx"))
        main = self._read("Main.tsx")
        self.assertIn('<Sequence from={intro} durationInFrames={body} name="Video">', main)
        self.assertIn("accentFor(ov, accent, accent2)", main)
        self.assertIn('ov.theme === "accent2"', self._read("overlays.tsx"))
        self.assertIn("brand?: BrandBlock | null;", self._read("types.ts"))
