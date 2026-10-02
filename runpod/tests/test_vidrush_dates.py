"""
Dates and times the VidRush way (the owner, 2026-10-01, after comparing four
VidRush exports with ours): about one date or time graphic every two to three
minutes, never on every mention; a big centred date, a time card top-left, a
typed "Place, Year" bottom-left, a year on a line for a jump in years; one
theme per video; nothing the narration did not say. And the long-text looks
with a bar, rule or underline beside or under the words are never picked.
"""
import unittest

from src import templates, timeline, treatments
from src.transcribe import Segment, Word

FPS = 30
SECS = 5.0
PLAIN = "Plain words about the water here."
# (A jump in years may take any of the year looks the date pass rotates: tests/test_year_looks.py.)
VR = set(treatments.VR_LOOKS) | set(treatments.YEAR_LOOKS)


def _seg(i, text):
    words = [Word(text=w, start=i * SECS + j * 0.3, end=i * SECS + j * 0.3 + 0.25) for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * SECS, end=(i + 1) * SECS, words=words)


def _plan(lines, pack="documentary", brief=None, shots=None, video_style="", kinds=None):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    n = int(SECS * FPS)
    scenes = [{"id": f"s{i}", "startFrame": i * n, "durationInFrames": n,
               "media": {"type": (kinds or {}).get(i, "video"), "url": f"https://x/{i}.mp4"},
               "transition": "none", "motion": "none", "effect": "none"} for i in range(len(lines))]
    brief = brief or {"kind": "explainer", "hookBeats": [], "sections": []}
    shots = shots or [{"subject": "Lake Mead"} for _ in lines]
    return treatments.plan(segs, shots, scenes, FPS, len(lines) * n, brief, treatments.pack_for(brief, pack),
                           timeline._OVERLAY_SECONDS, video_style=video_style)


def _story(at: dict, n: int):
    """n lines of plain words with the given lines at their indexes."""
    return [at.get(i, PLAIN) for i in range(n)]


def _dates(out):
    return [o for o in sorted(out["overlays"], key=lambda o: o["startFrame"]) if o["template"] in VR]


def _shown(out):
    return [(o["template"], o.get("text"), o.get("subtitle")) for o in _dates(out)]


class TheRegistryHasTheLooks(unittest.TestCase):
    def test_the_four_looks_are_registered(self):
        # (Added by the look builder; the planner never fakes them.)
        for tid in treatments.VR_LOOKS:
            self.assertIsNotNone(templates.get(tid), tid)
            self.assertFalse(templates.banned(tid), tid)


class WhatEachLineGets(unittest.TestCase):
    def moment(self, text, year=None, shot=None, brief=None, region=""):
        return treatments.vr_moment(text, shot or {}, brief or {}, year, region)[0]

    def test_a_full_date_is_the_centred_date_with_its_year_only_when_said(self):
        m = self.moment("On September 23, 2026, the river crested.")
        self.assertEqual((m["look"], m["props"]), (treatments.VR_HERO, {"text": "SEPTEMBER 23", "subtitle": "2026"}))
        m = self.moment("On Wednesday, September 23, the river crested.")
        self.assertEqual(m["props"], {"text": "SEPTEMBER 23", "subtitle": ""})       # no year, no weekday
        m = self.moment("In July 2025 the river crested.", year=2026)
        self.assertEqual((m["look"], m["props"]), (treatments.VR_HERO, {"text": "JULY", "subtitle": "2025"}))

    def test_a_clock_time_is_the_time_card_with_the_date_or_the_place_said(self):
        m = self.moment("At 9:08 a.m. on September 23, 2026, the warning went out.")
        self.assertEqual((m["look"], m["props"]), (treatments.VR_TIME, {"text": "9:08 AM",
                                                                        "subtitle": "SEPTEMBER 23, 2026"}))
        m = self.moment("At 9:08 a.m. the sirens sounded in Ruidoso.")
        self.assertEqual(m["props"], {"text": "9:08 AM", "subtitle": "RUIDOSO"})
        # No place in the line: its section's region tag, else nothing - never an invented one.
        m = self.moment("At 9:08 a.m. the sirens sounded.", region="Decatur, Indiana")
        self.assertEqual(m["props"], {"text": "9:08 AM", "subtitle": "DECATUR, INDIANA"})
        self.assertEqual(self.moment("At 9:08 a.m. the sirens sounded.")["props"]["subtitle"], "")
        self.assertEqual(self.moment("The call came in at 21:40.")["props"]["text"], "21:40")

    def test_a_jump_in_years_is_the_year_line(self):
        m = self.moment("Years later, in 2008, the lake was full again.", year=1961)
        self.assertEqual((m["look"], m["props"]), (treatments.VR_YEAR, {"value": 2008, "total": 1961,
                                                                        "label": "YEARS LATER"}))
        m = self.moment("From 1961 to 2008 the lake kept falling.")
        self.assertEqual(m["props"], {"value": 2008, "total": 1961, "label": ""})
        # A year five or more from the one the story was in; before any, the story is in NOW_YEAR.
        m = self.moment("In 1974 the dam was finished.")
        self.assertEqual(m["props"], {"value": 1974, "total": treatments.NOW_YEAR, "label": ""})
        self.assertIsNone(self.moment("In 1976 the dam was finished.", year=1974))       # two years on: no jump
        # Years that are a chart's labels are not the story's time.
        self.assertIsNone(self.moment("In 2020 the lake stood at 40 percent; by 2026 it was 26 percent."))
        self.assertIsNone(self.moment("Some 1900 feet of pipe burst."))

    def test_a_place_and_a_year_in_one_clause_is_the_typed_caption(self):
        m = self.moment("In 1939, crews finished Parker Dam on the Colorado River.", year=1938)
        self.assertEqual((m["look"], m["props"]), (treatments.VR_CAPTION, {"text": "Parker Dam, 1939"}))
        m = self.moment("He met her at the University of Hawaii in 1959.", year=1958)
        self.assertEqual(m["props"], {"text": "University of Hawaii, 1959"})
        # A person or an agency is never the place.
        self.assertIsNone(self.moment("In 2008, the National Weather Service changed its rules.", year=2006))
        self.assertIsNone(self.moment("In 2024, Barack Obama spoke.", year=2025, brief={"people": ["Barack Obama"]}))

    def test_relative_times_weekdays_and_ranges_get_nothing(self):
        for line in ("On Friday the water rose.", "Last night the river crested.", "This week the town waits.",
                     "Over the next 48 hours, more storms are expected.", "Three days later, crews returned.",
                     "From September 3 to September 5 it rained.", "Between July 2 and July 5 the dam held.",
                     "They left at dawn.", "The meeting ran past midnight.", "Overnight the levee failed."):
            self.assertIsNone(self.moment(line, year=2026), line)


class Frequency(unittest.TestCase):
    def test_at_most_one_per_75_seconds_and_the_centred_date_once_per_150(self):
        # A date said every 20 s for ten minutes (the old planner drew all thirty).
        days = {i: f"On September {1 + i // 4}, 2026, the river rose again." for i in range(0, 120, 4)}
        out = _plan(_story(days, 120))
        at = [o["startFrame"] / FPS for o in _dates(out)]
        self.assertTrue(at)
        self.assertTrue(all(b - a >= treatments.VR_GAP for a, b in zip(at, at[1:])), at)
        heroes = [o["startFrame"] / FPS for o in _dates(out) if o["template"] == treatments.VR_HERO]
        self.assertTrue(all(b - a >= treatments.VR_HERO_GAP for a, b in zip(heroes, heroes[1:])), heroes)
        self.assertLessEqual(len(at), 600 / treatments.VR_HERO_GAP + 1)
        # The first full date (said in the first 90 s) is shown, as the centred date.
        self.assertEqual(_shown(out)[0], (treatments.VR_HERO, "SEPTEMBER 1", "2026"))

    def test_the_first_full_date_wins_its_window_when_said_early(self):
        lines = _story({2: "At 9:08 a.m. the sirens sounded in Ruidoso.",
                        8: "On September 23, 2026, the river crested."}, 30)
        out = _plan(lines)
        self.assertEqual(_shown(out), [(treatments.VR_HERO, "SEPTEMBER 23", "2026")])

    def test_the_strongest_moment_takes_the_window(self):
        # No full date in the first 90 s: a month and a year (weak) loses to a year jump (strong).
        lines = _story({4: "In July 2026 the river began to fall.", 10: "Years later, in 2008, it was full.",
                        40: "Plain words."}, 44)
        out = _plan(lines)
        self.assertEqual([o["template"] for o in _dates(out)], [treatments.VR_YEAR])
        # ... and a clock time with a place beats a full date without its year said later on.
        lines = _story({20: "On September 23 the river crested.", 26: "At 9:08 a.m. the sirens sounded in Ruidoso.",
                        40: "Plain words."}, 44)
        out = _plan(lines)
        self.assertEqual(_shown(out), [(treatments.VR_HERO, "SEPTEMBER 23", "")])      # the story's start date
        lines = _story({2: "On September 23, 2026, the river crested.", 30: "On September 24 it rose again.",
                        36: "At 9:08 a.m. the sirens sounded in Ruidoso.", 60: "Plain words."}, 64)
        out = _plan(lines)
        self.assertEqual([o["template"] for o in _dates(out)], [treatments.VR_HERO, treatments.VR_TIME])

    def test_a_moment_that_lost_its_room_takes_it_back_when_the_winner_never_shows(self):
        # The year jump would win the window, but its line is a full-screen animation scene.
        lines = _story({4: "In July 2026 the river began to fall.", 10: "Years later, in 2008, it was full."}, 30)
        out = _plan(lines, kinds={10: "animation"})
        self.assertEqual(_shown(out), [(treatments.VR_HERO, "JULY", "2026")])


class OneThemePerVideo(unittest.TestCase):
    def test_the_videos_style_picks_one_theme(self):
        for style in ("nature_weather", "trending_news", "news_compilation", "compilation", "explainer"):
            self.assertEqual(treatments.vr_theme(style), "serif", style)
        for style in ("documentary", "history", "story", "crime", "investigative"):
            self.assertEqual(treatments.vr_theme(style), "typewriter", style)
        # No style: the story's kind, then the pack.
        self.assertEqual(treatments.vr_theme("", {"kind": "weather"}), "serif")
        self.assertEqual(treatments.vr_theme("", {"kind": "history"}), "typewriter")
        self.assertEqual(treatments.vr_theme("", {}, {"id": "news"}), "serif")

    def test_every_date_look_of_a_video_carries_it(self):
        lines = _story({0: "On September 23, 2026, the river crested.", 16: "At 9:08 a.m. the sirens sounded.",
                        32: "Years later, in 2008, it was full.", 48: "In 2009, crews rebuilt Parker Dam.",
                        64: PLAIN}, 66)
        for style, theme in (("history", "typewriter"), ("news_compilation", "serif")):
            out = _plan(lines, video_style=style)
            dated = _dates(out)
            self.assertEqual([o["template"] for o in dated], [treatments.VR_HERO, treatments.VR_TIME,
                                                              treatments.VR_YEAR, treatments.VR_CAPTION], style)
            self.assertEqual({o["theme"] for o in dated}, {theme}, style)
            self.assertEqual(dated[3]["text"], "Parker Dam, 2009")


class TheLineAsSaid(unittest.TestCase):
    def test_on_friday_draws_no_weekday(self):
        out = _plan(["On Friday the water rose.", PLAIN, PLAIN])
        self.assertEqual(_dates(out), [])
        self.assertFalse([o for o in out["overlays"] if "FRIDAY" in str(o.get("text", "")).upper()])

    def test_at_9_08_am_is_the_time_card(self):
        out = _plan(["The first alert went out at 9:08 a.m.", PLAIN, PLAIN])
        self.assertEqual(_shown(out), [(treatments.VR_TIME, "9:08 AM", "")])

    def test_on_september_23_2026_is_the_centred_date_without_a_weekday(self):
        out = _plan(["On September 23, 2026, the river crested.", PLAIN, PLAIN])
        [o] = _dates(out)
        self.assertEqual((o["template"], o["text"], o["subtitle"]), (treatments.VR_HERO, "SEPTEMBER 23", "2026"))
        self.assertNotIn("WEDNESDAY", str(o).upper())
        # It lands on its word, not before the line.
        self.assertLessEqual(o["startFrame"], int(round(0.3 * FPS)) + 1)

    def test_years_later_in_2008_is_the_next_year_look(self):
        # The first jump is the year line; the next one takes the next year look (the owner, 2026-10-02:
        # not the year line every time), still with only the year and the words said.
        out = _plan(["In 1961 the dam was finished.", PLAIN] + [PLAIN] * 14 + ["Years later, in 2008, it was full.",
                                                                               PLAIN])
        dated = _dates(out)
        self.assertEqual([(o["template"], o.get("value"), o.get("total")) for o in dated],
                         [(treatments.VR_YEAR, 1961.0, float(treatments.NOW_YEAR)),
                          ("LIB_TL_YEAR_SCROLLER", 2008.0, None)])
        self.assertEqual(dated[1]["subtitle"], "YEARS LATER")


class NoBarsUnderTheWords(unittest.TestCase):
    def test_the_bar_looks_are_never_picked(self):
        from tests import test_look_variety as lv
        segs, shots, scenes, brief = lv.build()
        total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
        for pack in templates.style_packs():
            out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, pack),
                                  timeline._OVERLAY_SECONDS)
            used = {o["template"] for o in out["overlays"]}
            self.assertFalse(used & treatments.BAR_TEXT_LOOKS, pack)
        pack = treatments.pack_for({}, "")
        for cue in ("headline", "key-phrase", "caption", "statement", "fact", "question", "warning", "quote"):
            for _ in range(6):
                tid = treatments._template_for_cue(cue, pack, set(), {}, text="The largest reservoir is drying up")
                self.assertNotIn(tid, treatments.BAR_TEXT_LOOKS, cue)

    def test_a_directors_bar_look_is_not_placed_and_the_line_keeps_a_clean_one(self):
        shots = [{"subject": "Lake Mead", "overlay": {"type": "motion", "variant": "txt-key-phrase",
                                                      "text": "Lake Mead"}}, {"subject": "Lake Mead"}]
        out = _plan(["Lake Mead is the largest reservoir in the country.", PLAIN], shots=shots)
        self.assertFalse({o["template"] for o in out["overlays"]} & treatments.BAR_TEXT_LOOKS)

    def test_the_line_ones_are_kept(self):
        for tid in ("LIB_TXT_MINI_TIMELINE", treatments.VR_YEAR):
            self.assertTrue(treatments.auto_ok(tid), tid)
        for tid in ("LIB_TXT_KEY_PHRASE", "LIB_TXT_UNDERLINE_SWEEP", "LIB_TXT_KICKER_HEADLINE",
                    "LIB_TXT_HEADLINE_WORDS", "LIB_TXT_BREAKING_TAG", treatments.TEXT_DATE_LOOK, "LIB_DTX_DATE_TOP"):
            self.assertFalse(treatments.auto_ok(tid), tid)
        # Every one of them is a real look the editor can still choose.
        for tid in treatments.BAR_TEXT_LOOKS:
            self.assertIsNotNone(templates.get(tid), tid)


if __name__ == "__main__":
    unittest.main()
