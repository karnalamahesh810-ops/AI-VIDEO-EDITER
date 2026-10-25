"""
Smooth cuts (TRANSITIONS_SMOOTH, on by default; the owner, 2026-10-18 and after: no white flash + whoosh between
shots, "smooth jump / zoom transitions").

A planned 15-minute video in every cutting style has no flash, film burn, light leak, glitch or overlay-pack cut,
no whoosh on a smooth cut, and still varies its transitions; a jump inside one clip zooms or punches in. The flag
off (or a job's "transitions_smooth": false) plans exactly as before.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import brandkit, config, smart_editor, styles, timeline  # noqa: E402
from src.media import MediaAsset  # noqa: E402
from src.transcribe import Segment, Word  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion", "src")
# The editor's sets (app src/lib/transitionSets.ts, editor round 2): the worker mirrors them exactly.
APP_SMOOTH = ["zoom-punch", "punch", "crossfade", "blur-dissolve", "soft-whip", "whip-pan", "slide", "card-zoom"]
APP_FLASHY = {"flash", "chromatic-flash", "light-leak", "film-burn", "glitch", "vhs-glitch", "color-wash", "mosaic",
              "shake-cut"}

SECONDS = 3.0
N = int(15 * 60 / SECONDS)          # a 15-minute narration, one beat every 3 s
CUT_STYLES = ("documentary", "history", "story", "explainer", "weather", "news", "compilation", "trending")
VIDEO_STYLES = ("documentary", "trending_news", "story", "history", "explainer", "compilation", "news_compilation",
                "nature_weather", "gaming_essay")


def _seg(i):
    words = [Word(text=w, start=i * SECONDS + j * 0.3, end=i * SECONDS + j * 0.3 + 0.25)
             for j, w in enumerate(f"Beat {i} of the story".split())]
    return Segment(text=f"Beat {i} of the story.", start=i * SECONDS, end=(i + 1) * SECONDS, words=words)


def _subject(i):
    # A new subject every 3-5 beats; a chapter card now and then.
    return f"subject {i // 4}" if i % 13 else f"subject {i // 4} b"


def _url(i):
    # Every 6th beat plays on the clip of the beat before (a chained shot: a jump cut inside one clip).
    k = i - 1 if i % 6 == 5 else i
    return f"file:///tmp/clip{k}.mp4"


def _plan(inp, n=N):
    segments = [_seg(i) for i in range(n)]
    shots = [{"query": f"q{i}", "visualType": "footage", "subject": _subject(i),
              "overlay": {"type": "chapter", "text": f"Part {i // 60 + 1}"} if i and i % 60 == 0 else None}
             for i in range(n)]
    assets = [MediaAsset(kind="video", source="youtube", url=_url(i), local_path=_url(i)) for i in range(n)]
    inp = dict({"sfx": True}, **inp)
    with mock.patch.object(config, "TREATMENTS", False):
        return timeline.build(segments, shots, assets, audio_url="file:///tmp/vo.mp3",
                              audio_duration=n * SECONDS, inp=inp)


def _cuts(doc):
    return [str(s.get("transition") or "none") for s in doc["scenes"][1:]]


def _placed(doc):
    return [t for t in _cuts(doc) if t not in ("none", "cut")]


def _sounds_on_smooth_cuts(doc):
    fps = doc["fps"]
    smooth_at = [s["startFrame"] for s in doc["scenes"][1:] if timeline.is_smooth(s.get("transition"))]
    return [fx for fx in doc.get("sfx") or [] if fx.get("kind") == "transition"
            and any(abs(fx["startFrame"] - c) <= fps for c in smooth_at)]


class MirrorsTheEditor(unittest.TestCase):
    def test_the_sets_are_the_editors(self):
        self.assertEqual(list(timeline.SMOOTH_TRANSITIONS), APP_SMOOTH)
        self.assertEqual(set(timeline.FLASHY_TRANSITIONS), APP_FLASHY)
        self.assertTrue(timeline.is_flashy("pack:mlt3"))
        self.assertFalse(timeline.is_flashy("none") or timeline.is_flashy(None) or timeline.is_flashy("crossfade"))
        self.assertTrue(all(timeline.is_smooth(t) for t in APP_SMOOTH))

    def test_every_smooth_transition_is_drawn(self):
        self.assertTrue(set(APP_SMOOTH) <= timeline.TRANSITIONS)
        with open(os.path.join(REMOTION, "transitions", "timing.ts"), encoding="utf-8") as fh:
            timing = fh.read()
        with open(os.path.join(REMOTION, "components", "SceneEffects.tsx"), encoding="utf-8") as fh:
            entrances = fh.read()
        for spec in timeline._SMOOTH_STYLE_TRANSITIONS.values():
            for t in spec["cycle"] + [spec["chapter"]] + list(timeline.JUMP_TRANSITIONS):
                self.assertTrue(t in APP_SMOOTH, t)
                if t == "crossfade":
                    continue                                    # Main.tsx draws the dissolve (CROSSFADE_FRAMES)
                self.assertTrue(f'"{t}"' in timing or f"{t}:" in timing or f'case "{t}"' in entrances, t)


class FifteenMinutePlans(unittest.TestCase):
    """The default: smooth cuts in every style."""

    @classmethod
    def setUpClass(cls):
        cls.docs = {}
        with mock.patch.object(config, "TRANSITIONS_SMOOTH", True), mock.patch.object(config, "TRANSITION_PACK", True):
            for style in CUT_STYLES:
                cls.docs[style] = _plan({"style": style})
            for vs in VIDEO_STYLES:
                inp = {"video_style": vs}
                styles.apply(inp)
                cls.docs["video:" + vs] = _plan(inp)

    def test_no_flash_burn_leak_glitch_or_pack_cut(self):
        for key, doc in self.docs.items():
            flashy = [t for t in _cuts(doc) if timeline.is_flashy(t)]
            self.assertEqual(flashy, [], key)
            self.assertEqual(doc["meta"]["cuts"]["flashy"], 0, key)
            self.assertTrue(doc["meta"]["smoothCuts"], key)

    def test_only_the_smooth_set(self):
        for key, doc in self.docs.items():
            self.assertTrue(set(_placed(doc)) <= set(APP_SMOOTH), (key, set(_placed(doc))))

    def test_no_whoosh_on_a_smooth_cut(self):
        for key, doc in self.docs.items():
            self.assertEqual(_sounds_on_smooth_cuts(doc), [], key)
            self.assertEqual([fx for fx in doc.get("sfx") or [] if fx.get("kind") == "transition"], [], key)

    def test_every_style_still_uses_transitions_and_varies_them(self):
        for key, doc in self.docs.items():
            if key in ("video:news_compilation", "video:nature_weather"):
                continue                # the measured crossfade cut (below)
            placed = _placed(doc)
            self.assertGreater(len(placed), 10, key)
            self.assertGreaterEqual(len(set(placed)), 3, (key, set(placed)))
            self.assertTrue(all(a != b for a, b in zip(placed, placed[1:])), (key, placed))
        for style in ("news", "compilation", "trending", "explainer"):
            self.assertGreaterEqual(len(set(_placed(self.docs[style]))), 5, style)

    def test_transitions_stay_rare_and_never_on_consecutive_cuts(self):
        for style in CUT_STYLES:
            cuts = _cuts(self.docs[style])
            idx = [i for i, t in enumerate(cuts) if t != "none"]
            self.assertTrue(all(b - a >= 3 for a, b in zip(idx, idx[1:])), style)
            self.assertLessEqual(len(idx), len(cuts) // 3 + 1, style)

    def test_a_jump_inside_one_clip_zooms_or_punches_in(self):
        for style in CUT_STYLES:
            doc = self.docs[style]
            jumps = [doc["scenes"][i].get("transition") for i in range(1, len(doc["scenes"]))
                     if i % 6 == 5 and doc["scenes"][i].get("transition") not in (None, "none")]
            self.assertGreater(len(jumps), 0, style)
            self.assertTrue(set(jumps) <= set(timeline.JUMP_TRANSITIONS), (style, set(jumps)))

    def test_the_news_compilation_keeps_its_measured_crossfades(self):
        for vs in ("news_compilation", "nature_weather"):
            placed = _placed(self.docs["video:" + vs])
            self.assertEqual(set(placed), {"crossfade"}, vs)
            self.assertGreater(len(placed), N // 2, vs)


class OldBehaviourBehindTheFlag(unittest.TestCase):
    def test_flag_off_plans_the_old_cycles_pack_and_sounds(self):
        with mock.patch.object(config, "TRANSITIONS_SMOOTH", False), mock.patch.object(config, "TRANSITION_PACK", True):
            doc = _plan({"style": "news"}, n=200)
        self.assertGreater(sum(timeline.is_flashy(t) for t in _cuts(doc)), 0)
        self.assertGreater(sum(1 for fx in doc["sfx"] if fx.get("kind") == "transition"), 0)
        self.assertFalse(doc["meta"]["smoothCuts"])

    def test_flag_off_is_the_exact_old_plan(self):
        shots = [{"subject": f"s{i // 3}", "overlay": {"type": "chapter"} if i % 25 == 0 else None}
                 for i in range(90)]
        for style in CUT_STYLES:
            with mock.patch.object(config, "TRANSITIONS_SMOOTH", False):
                old = timeline.plan_transitions(shots, style)
            self.assertEqual(timeline.plan_transitions(shots, style, smooth=False), old, style)
            spec = timeline._STYLE_TRANSITIONS[style]
            self.assertTrue(set(old) - {"none"} <= set(spec["cycle"]) | {spec["chapter"]}, style)

    def test_a_job_can_ask_for_the_old_cuts(self):
        with mock.patch.object(config, "TRANSITIONS_SMOOTH", True):
            self.assertTrue(timeline.smooth_cuts({}))
            self.assertFalse(timeline.smooth_cuts({"transitions_smooth": False}))
            self.assertFalse(timeline.smooth_cuts({"transitions_smooth": "0"}))
            doc = _plan({"style": "trending", "transitions_smooth": False}, n=200)
        self.assertGreater(sum(timeline.is_flashy(t) for t in _cuts(doc)), 0)
        with mock.patch.object(config, "TRANSITIONS_SMOOTH", False):
            self.assertTrue(timeline.smooth_cuts({"transitions_smooth": True}))

    def test_a_job_that_asks_for_the_pack_still_gets_it(self):
        with mock.patch.object(config, "TRANSITIONS_SMOOTH", True):
            doc = _plan({"style": "news", "transition_pack": True}, n=200)
        self.assertGreater(sum(1 for t in _cuts(doc) if t.startswith("pack:")), 0)


class SmoothSounds(unittest.TestCase):
    def _scenes(self, transitions, length=90):
        return [{"startFrame": i * length, "durationInFrames": length, "transition": t}
                for i, t in enumerate(transitions)]

    def test_smooth_cuts_are_silent_flashy_ones_keep_their_sound_when_pinned(self):
        scenes = self._scenes(["none", "whip-pan", "none", "none", "zoom-punch", "none", "none", "glitch"])
        self.assertEqual([p["name"] for p in timeline.plan_transition_sfx(scenes, 30, [], smooth=True)],
                         ["glitch-pro"])
        self.assertEqual(len(timeline.plan_transition_sfx(scenes, 30, [], smooth=False)), 3)

    def test_the_hook_boosters_soft_cut_sounds_stay_on_hard_cuts(self):
        scenes = self._scenes(["none", "none", "none", "none", "blur-dissolve"])
        picks = timeline.plan_transition_sfx(scenes, 30, [], soft={1: "zoom", 4: "zoom"}, smooth=True)
        self.assertEqual([p["startFrame"] < 90 + 30 for p in picks], [True])     # the hard cut only


class SmartEditorAndBrandKit(unittest.TestCase):
    def test_the_director_picks_from_the_smooth_set(self):
        allowed = smart_editor.transition_list({"meta": {"smoothCuts": True}})
        self.assertTrue(allowed and all(timeline.is_smooth(t) for t in allowed))
        self.assertNotIn("flash", allowed)
        self.assertIn("flash", smart_editor.transition_list({"meta": {"smoothCuts": False}}))

    def test_a_kit_stand_in_is_never_flashy_when_smooth(self):
        # zoom-punch's nearest list ends in "flash": with smooth cuts it becomes a hard cut instead.
        self.assertEqual(brandkit.nearest_transition("zoom-punch", {"flash", "fade"}), "flash")
        self.assertEqual(brandkit.nearest_transition("zoom-punch", {"flash", "fade"}, smooth=True), "none")
        # A kit that allows only flashy transitions chose them on purpose.
        self.assertEqual(brandkit.nearest_transition("zoom-punch", {"flash"}, smooth=True), "flash")


if __name__ == "__main__":
    unittest.main()
