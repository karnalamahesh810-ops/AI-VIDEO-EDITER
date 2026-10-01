"""
The owner's overlay transition pack (remotion/public/transitions, 2026-10-01):
the measured meta, where the planner puts the clips (spacing, density per
style, never in the first / last seconds or mid-sentence, never the same clip
within the last three, the look matched to the line), how a build applies
them, and the renderer contract.
"""
import os
import sys
import unittest
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import config, styles, timeline  # noqa: E402
from src.media import MediaAsset  # noqa: E402
from src.transcribe import Segment, Word  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion")
FPS = 30
LINES = ["The water kept rising through the night.", "Residents said they had never seen anything like it.",
         "Now let's head to the coast, where the damage is worse.", "Crews worked in the dark to clear the roads.",
         "Suddenly the levee collapsed.", "Officials issued a new warning on the radar.",
         "Back in 1927, the same river flooded the valley.", "Meanwhile, the town waited quietly for morning.",
         "Nobody knew how long it would last,", "and the rain kept falling."]


def _script(n=150, seconds=4.0, lines=None, region_every=0):
    """n one-line beats of `seconds`, a long pause before every fifth, a chapter every 23, the hook the first 4."""
    lines = lines or LINES
    segs, shots, t = [], [], 0.0
    for i in range(n):
        text = lines[zlib.crc32(str(i).encode()) % len(lines)] if len(lines) > 1 else lines[0]
        pause = 0.8 if zlib.crc32(f"p{i}".encode()) % 5 == 0 else 0.15
        words = [Word(text=w, start=t + pause + j * 0.3, end=t + pause + j * 0.3 + 0.25)
                 for j, w in enumerate(text.split())]
        segs.append(Segment(text=text, start=t, end=t + seconds, words=words))
        shot = {"subject": f"subject {i // 3}", "overlay": {"type": "chapter"} if i % 23 == 11 else None,
                "hook": i < 4}
        if region_every:
            shot["region"] = f"region {i // region_every}"
        shots.append(shot)
        t += seconds
    bounds = [int(round(s.start * FPS)) for s in segs] + [int(round(t * FPS))]
    return segs, shots, bounds


def _plan(style, **kw):
    segs, shots, bounds = _script(**kw)
    picks = timeline.plan_pack_transitions(segs, shots, bounds, FPS, styles.pack_rhythm(style), {}, [])
    return segs, shots, bounds, picks


class Meta(unittest.TestCase):
    def test_every_clip_is_measured_and_ships(self):
        meta = timeline.pack_meta()
        self.assertEqual(len(meta), 18)
        for name, m in meta.items():
            self.assertTrue(os.path.isfile(os.path.join(REMOTION, "public", m["file"])), name)
            self.assertEqual(m["file"], f"transitions/{name}.mp4")
            self.assertGreater(m["duration"], 0.4, name)
            self.assertTrue(0 < m["peakFrame"] < m["frames"], name)
            self.assertAlmostEqual(m["peak"], m["peakFrame"] / m["fps"], places=3)
            self.assertTrue(0 <= m["audioPeak"] <= m["duration"], name)
            self.assertIn(m["character"], timeline.PACK_CHARACTERS)
        # Every look the planner can ask for is in the pack.
        self.assertEqual({m["character"] for m in meta.values()}, set(timeline.PACK_CHARACTERS))

    def test_the_image_ships_the_clips(self):
        # .dockerignore drops remotion/public/* except what it lets back in: a
        # pack clip missing from the image would fail every render that uses it.
        with open(os.path.join(ROOT, ".dockerignore"), encoding="utf-8") as fh:
            rules = [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertIn("remotion/public/*", rules)
        self.assertIn("!remotion/public/transitions/", rules)

    def test_pack_names(self):
        self.assertEqual(timeline.pack_name("pack:mlt5"), "mlt5")
        self.assertEqual(timeline.pack_name("pack:nope"), "")
        self.assertEqual(timeline.pack_name("flash"), "")
        # Pack transitions are their own namespace: the named list is unchanged.
        self.assertFalse(any(t.startswith("pack") for t in timeline.TRANSITIONS))


class Placement(unittest.TestCase):
    def test_spacing_and_density_per_style(self):
        for style, spec in styles.PACK_TRANSITIONS.items():
            segs, shots, bounds, picks = _plan(style)
            times = [bounds[i] / FPS for i in sorted(picks)]
            self.assertGreater(len(times), 2, style)
            self.assertTrue(all(b - a >= spec["gap"] for a, b in zip(times, times[1:])), (style, times))
            average = bounds[-1] / FPS / len(times)
            # about one per `every` seconds, never more than that budget
            self.assertGreaterEqual(average, spec["every"] * 0.95, (style, average))
            if not spec.get("only"):
                self.assertLessEqual(average, spec["every"] * 1.6, (style, average))

    def test_calm_styles_are_rarer_than_energetic_ones_and_weather_rarest(self):
        n = {s: len(_plan(s)[3]) for s in ("documentary", "trending_news", "nature_weather")}
        self.assertGreater(n["trending_news"], n["documentary"])
        self.assertGreater(n["documentary"], n["nature_weather"])

    def test_never_the_same_clip_within_the_last_three(self):
        for style in styles.PACK_TRANSITIONS:
            picks = _plan(style)[3]
            names = [picks[i] for i in sorted(picks)]
            for k, name in enumerate(names):
                self.assertNotIn(name, names[max(0, k - timeline.PACK_RECENT):k], (style, names))

    def test_never_in_the_first_or_last_seconds(self):
        # Every beat a chapter with a pause: every cut is a strong candidate.
        segs, shots, bounds = _script(n=20, seconds=1.0)
        for s in shots:
            s["overlay"] = {"type": "chapter"}
        picks = timeline.plan_pack_transitions(segs, shots, bounds, FPS, styles.pack_rhythm("trending_news"), {}, [])
        self.assertTrue(picks)
        total = bounds[-1] / FPS
        for i in picks:
            t = bounds[i] / FPS
            self.assertTrue(timeline.PACK_EDGE_START <= t <= total - timeline.PACK_EDGE_END, t)

    def test_never_mid_sentence(self):
        segs, shots, bounds, picks = _plan("trending_news")
        for i in picks:
            self.assertRegex(segs[i - 1].text.strip(), r"[.!?]$")
        # A punctuated script whose cuts all fall mid-sentence: no pack transition at all.
        segs, shots, bounds = _script(lines=["and the rain kept falling,"])
        last = segs[-1]
        segs[-1] = Segment(text="and then it stopped.", start=last.start, end=last.end, words=last.words)
        self.assertEqual(timeline.plan_pack_transitions(segs, shots, bounds, FPS,
                                                        styles.pack_rhythm("trending_news"), {}, []), {})

    def test_the_hook_end_and_chapters_take_one(self):
        segs, shots, bounds, picks = _plan("documentary")
        self.assertIn(4, picks)                     # the first beat after the hook
        chapters = [i for i, s in enumerate(shots) if (s.get("overlay") or {}).get("type") == "chapter"]
        self.assertGreaterEqual(len(set(chapters) & set(picks)), len(chapters) // 2)

    def test_nature_weather_only_at_region_changes_and_the_hook(self):
        segs, shots, bounds = _script(lines=["The water kept rising through the night."], region_every=20)
        picks = timeline.plan_pack_transitions(segs, shots, bounds, FPS, styles.pack_rhythm("nature_weather"), {}, [])
        self.assertIn(4, picks)
        for i in picks:
            self.assertTrue(i == 4 or shots[i]["region"] != shots[i - 1]["region"], i)
        looks = {timeline.pack_meta()[n]["character"] for n in picks.values()}
        self.assertTrue(looks <= {"flash", "leak", "streak"}, looks)

    def test_the_look_follows_the_line_and_the_style(self):
        meta = timeline.pack_meta()

        def looks(style, line):
            segs, shots, bounds = _script(n=60, lines=[line])
            for s in shots:
                s["overlay"] = {"type": "chapter"}
            picks = timeline.plan_pack_transitions(segs, shots, bounds, FPS, styles.pack_rhythm(style), {}, [])
            return [meta[picks[i]]["character"] for i in sorted(picks)]

        tech = looks("trending_news", "Breaking: hackers took the system offline.")
        self.assertGreaterEqual(tech.count("glitch"), len(tech) // 3, tech)
        past = looks("history", "In 1863 the war reached the valley.")
        self.assertGreaterEqual(sum(1 for c in past if c in ("burn", "film")), len(past) * 0.6, past)
        calm = looks("documentary", "The river runs on through the valley.")
        self.assertTrue(set(calm) <= {"leak", "burn", "film"}, calm)
        news = looks("trending_news", "The river runs on through the valley.")
        self.assertGreaterEqual(sum(1 for c in news if c in ("flash", "glitch", "streak")), len(news) * 0.6, news)
        self.assertEqual(looks("documentary", "Suddenly the dam exploded.")[0], "flash")

    def test_another_sound_on_the_beat_keeps_it_off(self):
        segs, shots, bounds, picks = _plan("documentary")
        first = min(picks)
        busy = [{"name": "whoosh-soft", "startFrame": bounds[first] - 5, "durationFrames": 30}]
        again = timeline.plan_pack_transitions(segs, shots, bounds, FPS, styles.pack_rhythm("documentary"), {}, busy)
        self.assertNotIn(first, again)

    def test_a_clip_never_overruns_its_scenes(self):
        segs, shots, bounds, picks = _plan("trending_news", seconds=2.2)
        room = round(timeline.PACK_ROOM * FPS)
        for i, name in picks.items():
            lead, tail = timeline._pack_span(timeline.pack_meta()[name], FPS)
            self.assertGreaterEqual(bounds[i] - bounds[i - 1], lead + room)
            self.assertGreaterEqual(bounds[i + 1] - bounds[i], tail + room)


def _build(n=40, style="news", video_style="", sfx=True, pack=True):
    segments, shots, _ = _script(n=n, seconds=3.0)
    assets = [MediaAsset(kind="video", source="youtube", url=f"file:///tmp/{i}.mp4", local_path=f"file:///tmp/{i}.mp4")
              for i in range(n)]
    inp = {"style": style, "sfx": sfx, **({"video_style": video_style} if video_style else {})}
    with mock.patch.object(config, "TREATMENTS", False), mock.patch.object(config, "TRANSITION_PACK", pack):
        return timeline.build(segments, shots, assets, audio_url="file:///tmp/vo.mp3", audio_duration=n * 3.0, inp=inp)


class Build(unittest.TestCase):
    def test_a_build_lays_pack_transitions_without_their_own_timeline_sound(self):
        doc = _build()
        packs = [s for s in doc["scenes"] if timeline.pack_name(s["transition"])]
        self.assertTrue(packs)
        cuts = {s["startFrame"] for s in packs}
        near = int(styles.PACK_TRANSITIONS["trending_news"]["clear"] * FPS)
        for s in doc["scenes"]:
            t = s["transition"]
            if t not in ("none", "crossfade") and not timeline.pack_name(t):
                self.assertTrue(all(abs(s["startFrame"] - c) > near for c in cuts), s["startFrame"])
        for fx in doc["sfx"]:
            if fx.get("kind") == "transition":
                peak = fx["startFrame"] + timeline.sfx_meta()[fx["name"]]["peak"] * FPS
                self.assertTrue(all(abs(peak - c) > 2 for c in cuts), fx)

    def test_a_crossfade_cut_becomes_the_hard_cut_the_clip_covers(self):
        doc = _build(style="crossfade", video_style="news_compilation")
        self.assertTrue(any(timeline.pack_name(s["transition"]) for s in doc["scenes"]))
        self.assertTrue(any(s["transition"] == "crossfade" for s in doc["scenes"]))

    def test_the_switch_turns_it_off(self):
        doc = _build(pack=False)
        self.assertFalse(any(timeline.pack_name(s["transition"]) for s in doc["scenes"]))


class Renderer(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(REMOTION, "src", *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_renderer_lays_the_clip_over_the_cut(self):
        comp = self._read("transitions", "PackTransition.tsx")
        self.assertIn('mixBlendMode: "screen"', comp)
        self.assertIn("OffthreadVideo", comp)
        self.assertIn("peakFrame", comp)
        self.assertIn('PACK_PREFIX = "pack:"', comp)
        self.assertIn("pack:${string}", self._read("types.ts"))
        main = self._read("Main.tsx")
        self.assertIn("<PackTransitions", main)
        # Its own sound: never above the original level, muted only by the editor's switch.
        self.assertIn("props.sfxEnabled === false ? 0 : Math.min(1,", main)


if __name__ == "__main__":
    unittest.main()
