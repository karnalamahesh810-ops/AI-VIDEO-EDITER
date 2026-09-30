"""Human-like cuts (src/transcribe.py human_cuts, the owner 2026-09-30).

"The 7-second rule: 7 s max, but clips don't all need to be 7 s - cut based on
the narration like a human editor." A beat ends where an editor would cut, its
time on screen follows what it says, and MIN/MAX_SCENE_SECONDS bound the time
ON SCREEN (the pause after its last word included). The fixtures are real
whisper word timings of two benchmark narrations (bench/audio).
"""
import json
import os
import statistics
import unittest
from unittest import mock

from src import config, mentions, styles, transcribe
from src.transcribe import Segment, Word, human_cuts, screen_lengths, segment_words

HERE = os.path.dirname(os.path.abspath(__file__))


def fixture(name):
    with open(os.path.join(HERE, "fixtures", f"words_{name}.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    return [Word(t, s, e) for t, s, e in d["words"]], float(d["duration"])


def words_from(text: str, wps: float = 2.75, start: float = 0.0, pause: float = 0.35):
    out, t = [], start
    for token in text.split():
        end = t + 1.0 / wps
        out.append(Word(text=token, start=round(t, 3), end=round(end, 3)))
        t = end + (pause if token[-1:] in ".!?" else 0.02)
    return out


def style_config(style):
    """The config a video style sets, as mock patches (handler._apply_config's coercion)."""
    inp = {"video_style": style}
    styles.apply(inp)
    patches = []
    for k, v in (inp.get("config") or {}).items():
        if hasattr(config, k):
            cur = getattr(config, k)
            if isinstance(cur, bool):
                v = bool(v)
            elif isinstance(cur, (int, float)) and not isinstance(v, bool):
                v = type(cur)(v)
            patches.append(mock.patch.object(config, k, v))
    return patches


class StyleCase(unittest.TestCase):
    STYLE = "nature_weather"

    def setUp(self):
        for p in style_config(self.STYLE):
            p.start()
            self.addCleanup(p.stop)


class TheOwnersSevenSecondRule(StyleCase):
    def test_no_shot_is_on_screen_longer_than_seven_seconds(self):
        self.assertEqual(config.MAX_SCENE_SECONDS, 7.0)
        for name in ("new_mexico_flash_flood", "lake_mead"):
            words, dur = fixture(name)
            segs = segment_words(words, origin=0.0, until=dur)
            lengths = screen_lengths(segs, 0.0, dur)
            self.assertLessEqual(max(lengths), 7.0 + 1e-6, (name, lengths))
            # ...and nothing flashes by: only the very last beat may run short.
            self.assertTrue(all(x >= config.MIN_SCENE_SECONDS - 1e-6 for x in lengths[:-1]), (name, lengths))

    def test_lengths_vary_with_the_narration_not_a_grid(self):
        words, dur = fixture("new_mexico_flash_flood")
        lengths = screen_lengths(segment_words(words, origin=0.0, until=dur), 0.0, dur)
        self.assertGreater(statistics.pstdev(lengths) / statistics.mean(lengths), 0.1, lengths)
        self.assertGreater(len({round(x, 1) for x in lengths}), len(lengths) // 2)

    def test_the_median_lands_near_the_reference_channel(self):
        # The reference Nor'easter channel: footage shots median 5.3 s.
        stats = []
        for name in ("new_mexico_flash_flood", "lake_mead"):
            words, dur = fixture(name)
            stats.append(transcribe.cut_stats(segment_words(words, origin=0.0, until=dur), 0.0, dur)["median"])
        self.assertTrue(all(4.3 <= m <= 6.3 for m in stats), stats)

    def test_the_segments_tile_the_words_in_order(self):
        words, dur = fixture("lake_mead")
        segs = segment_words(words, origin=0.0, until=dur)
        self.assertEqual([w for s in segs for w in s.words], words)
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a.end, b.start + 1e-6)


class WhereTheCutsLand(StyleCase):
    def test_most_cuts_close_a_sentence_or_a_clause(self):
        for name in ("new_mexico_flash_flood", "lake_mead"):
            words, dur = fixture(name)
            segs = segment_words(words, origin=0.0, until=dur)
            ends = [s.words[-1].text for s in segs[:-1]]
            good = sum(1 for t in ends if t.rstrip("\"')").endswith((".", "!", "?", ",", ";", ":")))
            self.assertGreaterEqual(good / len(ends), 0.7, (name, ends))

    def test_never_inside_a_name_after_the_or_between_a_figure_and_its_unit(self):
        q = transcribe._cut_features(words_from(
            "The storm hit Long Beach Island hard. The water rose eleven feet in the storm. "
            "A powerful Northeaster hit the coast south of Atlantic City."))["quality"]
        toks = "The storm hit Long Beach Island hard. The water rose eleven feet in the storm. " \
               "A powerful Northeaster hit the coast south of Atlantic City.".split()

        def at(word, nth=0):
            idx = [k for k, t in enumerate(toks) if t == word][nth]
            return q[idx]
        self.assertLess(at("Beach"), 0.1)            # Long | Beach
        self.assertLess(at("storm", 0), 0.1)         # The | storm
        self.assertLess(at("feet"), 0.1)             # eleven | feet
        self.assertLess(at("Northeaster"), 0.1)      # A powerful | Northeaster
        self.assertLess(at("of"), 0.1)               # south | of
        self.assertEqual(at("The", 1), 1.0)          # a sentence start

    def test_a_town_and_its_state_stay_together(self):
        text = "At Duck, North Carolina, tides hit six feet this morning."
        q = transcribe._cut_features(words_from(text))["quality"]
        self.assertLess(q[text.split().index("North")], 0.2)

    def test_a_new_sentence_is_cut_in_the_breath_before_its_first_word(self):
        with mock.patch.object(config, "CUT_LEAD_SECONDS", 0.14):
            words = words_from("The river rose all night and kept on rising. " * 4, pause=0.5)
            segs = segment_words(words)
            for prev, seg in zip(segs, segs[1:]):
                if prev.words[-1].text.endswith("."):
                    self.assertAlmostEqual(seg.start, seg.words[0].start - 0.14, places=3)
                self.assertGreaterEqual(seg.start, prev.end - 1e-9)

    def test_the_opening_is_held_longer_than_the_body(self):
        # The reference's hook runs a median 7.0 s against 5.5 s in the body.
        self.assertGreater(config.CUT_HOOK_FACTOR, 1.0)
        text = ("The water came up over the seawall and into the streets of the town, and it kept on coming. "
                "Cars were stranded on the causeway as the tide rose through the evening hours. ") * 6
        words = words_from(text)
        segs = segment_words(words, origin=0.0)
        lengths = screen_lengths(segs, 0.0)
        hook = [x for s, x in zip(segs, lengths) if s.start < config.HOOK_SECONDS]
        body = [x for s, x in zip(segs, lengths) if s.start >= config.HOOK_SECONDS][:-1]
        self.assertGreaterEqual(statistics.median(hook), statistics.median(body))


class LengthFollowsContent(unittest.TestCase):
    def test_action_lines_are_cut_shorter_when_the_style_asks(self):
        # Documentary defaults: an intense passage aims at CUT_FAST_SECONDS.
        with mock.patch.object(config, "MIN_SCENE_SECONDS", 2.0), \
                mock.patch.object(config, "TARGET_SCENE_SECONDS", 6.0), \
                mock.patch.object(config, "MAX_SCENE_SECONDS", 9.0), \
                mock.patch.object(config, "CUT_FAST_SECONDS", 3.0), \
                mock.patch.object(config, "CUT_SLOW_SECONDS", 8.0), \
                mock.patch.object(config, "HOOK_SECONDS", 0.0):
            calm = words_from("The quiet village sits on the coastline where families have lived for generations. " * 6)
            wild = words_from("Floodwater swept cars away. Crews rescued stranded drivers. Homes collapsed. "
                              "The surge destroyed the pier. " * 6)
            m_calm = statistics.median(screen_lengths(segment_words(calm), None))
            m_wild = statistics.median(screen_lengths(segment_words(wild), None))
            self.assertLess(m_wild, m_calm)

    def test_the_nature_style_does_not_speed_up_for_intense_lines(self):
        # The reference: intensity does not speed up the cutting (fast = target).
        for p in style_config("nature_weather"):
            p.start()
            self.addCleanup(p.stop)
        lo, fast, target, slow, hi = transcribe.cut_lengths()
        self.assertEqual(fast, target)
        self.assertGreater(slow, target)
        self.assertEqual(hi, 7.0)


class TheOldRhythmStaysReachable(unittest.TestCase):
    def test_human_cuts_off_is_the_clause_rhythm(self):
        words = words_from("The river was the only thing holding the valley together. " * 8)
        with mock.patch.object(config, "HUMAN_CUTS", False):
            old = segment_words(words)
        self.assertEqual([(s.start, s.end) for s in old],
                         [(s.start, s.end) for s in transcribe._rhythm_cuts(words)])
        with mock.patch.object(config, "HUMAN_CUTS", True):
            new = segment_words(words)
        self.assertEqual([w for s in new for w in s.words], words)


class NamesOpenTheirBeat(StyleCase):
    NARRATION = ("The wells outside Willcox started to fail in the spring of this year. "
                 "Farmers watched the water table drop by several feet in a matter of weeks, and then "
                 "Governor Katie Hobbs ordered a stop to every new well in the basin. "
                 "The order landed hard on the families who had farmed that valley for generations.")

    def test_the_person_is_on_screen_while_the_name_is_said(self):
        segs = segment_words(words_from(self.NARRATION))
        brief = {"kind": "news", "people": ["Katie Hobbs"], "places": [], "hookBeats": [0], "sections": [],
                 "cast": [{"name": "Katie Hobbs", "role": "Governor of Arizona", "aliases": []}]}
        with mock.patch.object(config, "MENTION_CUTS", True):
            out, focus = mentions.prepare(segs, brief)
        i = next(k for k, s in enumerate(out) if "Hobbs" in s.text)
        # The beat that says her name opens on it (within the first two words) and shows her.
        self.assertLessEqual(out[i].text.split().index("Governor"), 2, out[i].text)
        self.assertEqual(focus[i]["subject"], "Katie Hobbs")
        self.assertTrue(all(isinstance(s, Segment) for s in out))


if __name__ == "__main__":
    unittest.main()
