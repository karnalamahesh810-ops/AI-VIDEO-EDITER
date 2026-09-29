"""
Cut transitions and their sounds: how often a style cuts with a transition,
which transitions it reaches for, where the sound lands, and the renderer
contract (every planned name drawn, every sound file shipped with its meta).
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import config, templates, timeline  # noqa: E402
from src.media import MediaAsset  # noqa: E402
from src.transcribe import Segment, Word  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion", "src")
SFX_DIR = os.path.join(ROOT, "remotion", "public", "sfx")

CALM = {"documentary", "history", "story"}
ENERGETIC = {"news", "compilation", "trending"}
SOFT_SET = {"light-leak", "blur-dissolve", "luma-fade", "film-burn"}
ENERGETIC_SET = {"flash", "glitch", "whip-pan", "zoom-punch", "chromatic-flash", "shake-cut", "vhs-glitch"}
CONTRACT_SFX = ["whoosh-soft", "swipe", "click", "keys", "shutter", "boom-soft", "ding", "tick",
                "glitch-short", "riser-short", "flash-hit", "marker", "count-tick", "paper-slide"]


def _new_subject_every_shot(n):
    return [{"subject": f"place {i}"} for i in range(n)]


def _placed(plan):
    return [i for i, t in enumerate(plan) if t != "none"]


def _seg(i, seconds=3.0):
    words = [Word(text=w, start=i * seconds + j * 0.3, end=i * seconds + j * 0.3 + 0.25)
             for j, w in enumerate(f"Beat {i} of the story".split())]
    return Segment(text=f"Beat {i} of the story.", start=i * seconds, end=(i + 1) * seconds, words=words)


def _asset(kind="video", url="file:///tmp/a.mp4"):
    return MediaAsset(kind=kind, source="youtube", url=url, local_path=url)


def _build(n=24, style="news", kinds=None, subjects=None, sfx=True):
    segments = [_seg(i) for i in range(n)]
    shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None,
              "subject": (subjects[i] if subjects else f"subject {i}")} for i in range(n)]
    kinds = kinds or ["video"] * n
    assets = [_asset(k, f"file:///tmp/{i}.{'jpg' if k == 'image' else 'mp4'}") for i, k in enumerate(kinds)]
    with mock.patch.object(config, "TREATMENTS", False):
        return timeline.build(segments, shots, assets, audio_url="file:///tmp/vo.mp3",
                              audio_duration=n * 3.0, inp={"style": style, "sfx": sfx})


class Density(unittest.TestCase):
    def test_calm_styles_mostly_hard_cut(self):
        for style in CALM:
            plan = timeline.plan_transitions(_new_subject_every_shot(60), style)
            placed = _placed(plan)
            self.assertGreater(len(placed), 0, style)
            # ~1 cut in 6 at most.
            self.assertLessEqual(len(placed), 60 // 6 + 1, style)
            self.assertTrue(all(b - a >= 6 for a, b in zip(placed, placed[1:])), style)

    def test_calm_styles_only_mark_section_changes(self):
        shots = [{"subject": "Lake Mead"}] * 30
        for style in CALM:
            self.assertEqual(_placed(timeline.plan_transitions(shots, style)), [], style)

    def test_energetic_styles_punctuate_one_cut_in_three_or_four(self):
        for style in ENERGETIC:
            plan = timeline.plan_transitions(_new_subject_every_shot(60), style)
            placed = _placed(plan)
            self.assertGreaterEqual(len(placed), 60 // 4 - 1, style)
            self.assertLessEqual(len(placed), 60 // 3 + 1, style)

    def test_energetic_styles_punctuate_even_a_single_subject(self):
        shots = [{"subject": "Lake Mead"}] * 40
        for style in ENERGETIC:
            placed = _placed(timeline.plan_transitions(shots, style))
            self.assertGreaterEqual(len(placed), 40 // 4 - 1, style)
            self.assertTrue(all(b - a <= 4 for a, b in zip(placed, placed[1:])), style)

    def test_news_cuts_with_more_transitions_than_a_documentary(self):
        shots = _new_subject_every_shot(48)
        news = len(_placed(timeline.plan_transitions(shots, "news")))
        documentary = len(_placed(timeline.plan_transitions(shots, "documentary")))
        self.assertGreater(news, 1.5 * documentary)


class Rhythm(unittest.TestCase):
    def test_never_on_consecutive_cuts_and_never_the_same_twice_in_a_row(self):
        shots = [{"subject": f"s{i // 2}", "overlay": {"type": "chapter"} if i % 9 == 0 else None}
                 for i in range(80)]
        for style in timeline.STYLES:
            if style == "crossfade":
                continue            # dissolves most cuts on purpose (CrossfadeRhythm below)
            plan = timeline.plan_transitions(shots, style)
            placed = _placed(plan)
            self.assertEqual(plan[0], "none")
            self.assertTrue(all(b - a >= 3 for a, b in zip(placed, placed[1:])), style)
            names = [plan[i] for i in placed]
            self.assertTrue(all(a != b for a, b in zip(names, names[1:])), (style, names))

    def test_each_style_speaks_its_own_vocabulary(self):
        shots = _new_subject_every_shot(90)
        for style in CALM:
            used = set(timeline.plan_transitions(shots, style)) - {"none"}
            self.assertTrue(used <= SOFT_SET, (style, used))
        for style in ENERGETIC:
            used = set(timeline.plan_transitions(shots, style)) - {"none"}
            self.assertTrue(used <= ENERGETIC_SET, (style, used))
            self.assertGreaterEqual(len(used), 4, style)

    def test_a_chapter_opens_with_the_styles_chapter_transition(self):
        shots = [{"subject": "a"}] * 8 + [{"subject": "a", "overlay": {"type": "chapter"}}] + [{"subject": "a"}] * 4
        self.assertEqual(timeline.plan_transitions(shots, "history")[8], "film-burn")
        self.assertEqual(timeline.plan_transitions(shots, "news")[8], "flash")

    def test_short_cuts_carry_no_transition(self):
        shots = _new_subject_every_shot(30)
        durations = [5] * 30        # every scene shorter than a transition needs
        plan = timeline.plan_transitions(shots, "news", durations=durations)
        self.assertEqual(_placed(plan), [])

    def test_every_planned_name_is_in_the_contract(self):
        for style in timeline.STYLES:
            for t in timeline.plan_transitions(_new_subject_every_shot(50), style):
                self.assertIn(t, timeline.TRANSITIONS)


class Style(unittest.TestCase):
    def test_the_jobs_style_wins(self):
        self.assertEqual(timeline.transition_style({"style": "compilation"}, {"id": "documentary"}), "compilation")
        self.assertEqual(timeline.transition_style({"style": "History"}), "history")

    def test_the_pack_then_the_story_kind(self):
        self.assertEqual(timeline.transition_style({}, {"id": "news"}), "news")
        self.assertEqual(timeline.transition_style({}, {"id": "youtube_modern"}), "trending")
        self.assertEqual(timeline.transition_style({}, None, {"kind": "disaster"}), "weather")
        self.assertEqual(timeline.transition_style({}, None, {"kind": "other"}), "documentary")
        self.assertEqual(timeline.transition_style({"style": "nonsense"}), "documentary")


class Sounds(unittest.TestCase):
    def _scenes(self, transitions, length=90):
        return [{"startFrame": i * length, "durationInFrames": length, "transition": t}
                for i, t in enumerate(transitions)]

    def test_the_sounds_loudest_point_lands_on_the_cut(self):
        meta = timeline.sfx_meta()
        scenes = self._scenes(["none", "glitch", "none", "none", "flash", "none", "none", "whip-pan",
                               "none", "none", "shake-cut", "none", "none", "film-burn"])
        picks = timeline.plan_transition_sfx(scenes, 30, [])
        self.assertEqual([p["name"] for p in picks], ["glitch-short", "flash-hit", "swipe", "boom-soft", "whoosh-soft"])
        cuts = [s["startFrame"] for s in scenes if s["transition"] != "none"]
        for p, cut in zip(picks, cuts):
            self.assertLessEqual(abs(p["startFrame"] + meta[p["name"]]["peak"] * 30 - cut), 1.0, p)
            self.assertEqual(p["kind"], "transition")
            self.assertGreater(p["durationFrames"], 0)
            self.assertLessEqual(p["volume"], 0.2)
        # the soft whoosh is quieter than the hits
        self.assertLess(picks[-1]["volume"], picks[0]["volume"])

    def test_a_nearby_sound_silences_the_transition(self):
        scenes = self._scenes(["none", "glitch", "none", "none", "flash"])
        others = [{"name": "pop", "startFrame": 90 + 20, "volume": 0.3}]      # 0.67 s after the first cut
        picks = timeline.plan_transition_sfx(scenes, 30, others)
        self.assertEqual([p["name"] for p in picks], ["flash-hit"])
        far = [{"name": "pop", "startFrame": 90 + 40, "volume": 0.3}]         # 1.3 s after it
        self.assertEqual(len(timeline.plan_transition_sfx(scenes, 30, far)), 2)

    def test_a_luma_fade_is_silent(self):
        picks = timeline.plan_transition_sfx(self._scenes(["none", "luma-fade", "none", "none", "fade"]), 30, [])
        self.assertEqual(picks, [])

    def test_build_adds_transition_sounds_in_time_order(self):
        doc = _build(style="news")
        fx = doc["sfx"]
        self.assertTrue(any(s.get("kind") == "transition" for s in fx))
        starts = [s["startFrame"] for s in fx]
        self.assertEqual(starts, sorted(starts))
        for s in fx:
            self.assertIn(s["name"], templates.sfx_files())

    def test_sounds_off_means_no_transition_sounds(self):
        self.assertEqual(_build(style="news", sfx=False)["sfx"], [])


class Stills(unittest.TestCase):
    def test_consecutive_stills_never_share_a_move_and_clips_never_move(self):
        kinds = ["image", "image", "video", "image", "image", "image", "video", "image"] * 3
        doc = _build(n=len(kinds), style="documentary", kinds=kinds)
        moves = [s["motion"] for s in doc["scenes"] if s["media"]["type"] == "image"]
        self.assertTrue(all(a != b for a, b in zip(moves, moves[1:])), moves)
        self.assertEqual({s["motion"] for s in doc["scenes"] if s["media"]["type"] == "video"}, {"none"})
        self.assertGreaterEqual(len(set(moves)), 8)

    def test_every_move_is_drawn_by_the_renderer(self):
        with open(os.path.join(REMOTION, "transitions", "stillMotion.tsx"), encoding="utf-8") as fh:
            src = fh.read()
        with open(os.path.join(REMOTION, "types.ts"), encoding="utf-8") as fh:
            types = fh.read()
        for m in timeline._IMAGE_MOTIONS:
            self.assertIn(f'case "{m}"', src, m)
            self.assertIn(f'"{m}"', types, m)


class RendererContract(unittest.TestCase):
    def test_every_style_transition_has_a_renderer(self):
        with open(os.path.join(REMOTION, "transitions", "timing.ts"), encoding="utf-8") as fh:
            timing = fh.read()
        with open(os.path.join(REMOTION, "transitions", "TransitionFrame.tsx"), encoding="utf-8") as fh:
            frame = fh.read()
        drawn = set(re.findall(r'^\s*"?([a-z-]+)"?:\s*\{\s*out:', timing, re.M))
        for spec in timeline._STYLE_TRANSITIONS.values():
            for t in spec["cycle"] + [spec["chapter"]]:
                self.assertIn(t, drawn, t)
                self.assertIn(f'case "{t}"', frame, t)

    def test_every_transition_sound_ships(self):
        files = templates.sfx_files()
        for name, vol in timeline._TRANSITION_SFX.values():
            self.assertIn(name, files)
            self.assertTrue(0 < vol <= 0.2, name)

    def test_contract_sounds_and_meta(self):
        files = templates.sfx_files()
        for name in CONTRACT_SFX:
            self.assertIn(name, files)
        with open(os.path.join(SFX_DIR, "sfx_meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertEqual(set(meta), files)
        for name, m in meta.items():
            self.assertGreater(m["duration"], 0, name)
            self.assertTrue(0 <= m["peak"] <= m["duration"], name)
        # a riser ends on its peak; a count-tick run lands on its last tick
        self.assertGreater(meta["riser-short"]["peak"], meta["riser-short"]["duration"] - 0.2)
        self.assertGreater(meta["count-tick"]["peak"], meta["count-tick"]["duration"] * 0.6)
        self.assertGreaterEqual(meta["keys"]["duration"], 4.5)


if __name__ == "__main__":
    unittest.main()


class CrossfadeRhythm(unittest.TestCase):
    """The news-compilation cut: most changes dissolve, the rest are hard cuts."""

    def test_about_four_in_five_cuts_dissolve_and_nothing_else_is_used(self):
        shots = [{"subject": f"s{i}"} for i in range(200)]
        plan = timeline.plan_transitions(shots, "crossfade")
        self.assertEqual(plan[0], "none")
        self.assertEqual(set(plan), {"none", "crossfade"})
        share = plan.count("crossfade") / (len(plan) - 1)
        self.assertTrue(0.65 <= share <= 0.92, share)
        self.assertEqual(plan, timeline.plan_transitions(shots, "crossfade"))     # stable re-plans

    def test_short_shots_hard_cut(self):
        shots = [{"subject": f"s{i}"} for i in range(20)]
        durations = [20] * 20                       # 0.66 s each: too short to dissolve
        self.assertEqual(set(timeline.plan_transitions(shots, "crossfade", durations)), {"none"})

    def test_crossfades_make_no_sound(self):
        scenes = [{"startFrame": 30 * i, "transition": "crossfade"} for i in range(1, 6)]
        self.assertEqual(timeline.plan_transition_sfx(scenes, 30, []), [])

    def test_the_style_reaches_the_planner(self):
        from src import styles
        inp = {"video_style": "news_compilation"}
        styles.apply(inp)
        self.assertEqual(timeline.transition_style(inp, {"id": "news"}, {"kind": "weather"}), "crossfade")

    def test_the_renderer_knows_crossfade(self):
        types = open("remotion/src/types.ts", encoding="utf-8").read()
        main = open("remotion/src/Main.tsx", encoding="utf-8").read()
        self.assertIn('"crossfade"', types)
        self.assertIn("CROSSFADE_FRAMES = 15", main)
        self.assertEqual(timeline.CROSSFADE_FRAMES, 15)


class SfxMetaCopy(unittest.TestCase):
    def test_the_renderer_copy_matches_the_sound_folder(self):
        # Main.tsx imports src/data/sfx_meta.json so the Lovable preview copy of
        # src/ works too; it must stay equal to public/sfx/sfx_meta.json.
        import json
        a = json.load(open("remotion/public/sfx/sfx_meta.json", encoding="utf-8"))
        b = json.load(open("remotion/src/data/sfx_meta.json", encoding="utf-8"))
        self.assertEqual(a, b)
