"""
Years said on a line rotate through the year looks (the owner, 2026-10-02:
"when we said years it only using year one ... on previous video we got lot of
different ones on timeline"). Lake Powell showed the year line five times. Now
the date pass picks the least used year look that can show what the line said:
the year line, the year scroller (the ruler under a lens), the year roll, the
decade grid, the years-later and time-passing cards for a counted jump, the
then / now card for a range as said or a year against today. They keep the
date looks' room (one per VR_GAP) and show nothing the line did not say.
"""
import re
import unittest

from src import templates, treatments
from tests.test_vidrush_dates import FPS, PLAIN, _plan

YEARS = set(treatments.YEAR_LOOKS)


def _years(out):
    return [o for o in sorted(out["overlays"], key=lambda o: o["startFrame"]) if o["template"] in YEARS]


def _story(*said, gap=17, tail=3):
    """A line that says each of `said`, `gap` plain lines apart (5 s each: 85 s, past VR_GAP)."""
    lines = []
    for text in said:
        lines += [text] + [PLAIN] * (gap - 1)
    return lines[:len(lines) - gap + 1] + [PLAIN] * tail


MANY = _story("In 1961 the dam was finished.", "Years later, in 2008, it was full.",
              "Thirty years later, in 1998, it was dry.", "From 1961 to 2008 the lake rose.",
              "Back in 1936, the dam was finished. Today it is drying up.", "In 1890 the river ran free.",
              "In 1700 nobody lived here.", "Two decades later, in 1720, a fort stood here.")


class TheLooks(unittest.TestCase):
    def test_every_year_look_is_registered_switched_on_and_not_banned(self):
        for tid in treatments.YEAR_LOOKS:
            self.assertIsNotNone(templates.get(tid), tid)
            self.assertFalse(templates.banned(tid), tid)
            self.assertTrue(treatments.auto_ok(tid), tid)

    def test_the_year_roll_keeps_its_two_years(self):
        # It rolls from items[0] to items[1]; the registry dropped "items" and the look drew nothing.
        r = templates.resolve("TL_YEAR_ROLL_V1", props={"items": [{"label": "1961"}, {"label": "2008"}], "value": 2008})
        self.assertEqual([i["label"] for i in r["items"]], ["1961", "2008"])


class ARotation(unittest.TestCase):
    def test_a_video_with_eight_jumps_shows_seven_looks_the_year_line_first(self):
        shown = [o["template"] for o in _years(_plan(MANY))]
        self.assertEqual(len(shown), 8, shown)
        self.assertEqual(shown[0], treatments.VR_YEAR)
        self.assertGreaterEqual(len(set(shown)), 7, shown)
        self.assertFalse([a for a, b in zip(shown, shown[1:]) if a == b], shown)

    def test_the_year_looks_keep_the_date_looks_room(self):
        # Two jumps 30 s apart: one graphic (VR_GAP), however different the second look would be.
        out = _plan(_story("In 1961 the dam was finished.", "Years later, in 2008, it was full.", gap=6))
        self.assertEqual(len(_years(out)), 1)
        at = [o["startFrame"] / FPS for o in _years(_plan(MANY))]
        self.assertTrue(all(b - a >= treatments.VR_GAP for a, b in zip(at, at[1:])), at)

    def test_each_one_lands_on_the_year_as_said(self):
        out = _plan(_story("In 1961 the dam was finished.", "Years later, in 2008, it was full."))
        second = _years(out)[1]
        # "Years later, in 2008": the line starts at 85 s, "2008," is its fourth word (0.9 s in).
        self.assertAlmostEqual(second["startFrame"] / FPS, 85.9, delta=0.2)


class WhatEachShows(unittest.TestCase):
    def _one(self, text, story_year=None):
        m, _now = treatments.vr_moment(text, {}, {}, story_year)
        return m

    def test_thirty_years_later_is_the_years_later_card_with_the_year_under_it(self):
        [o] = _years(_plan(["Thirty years later, in 1998, it was dry.", PLAIN, PLAIN]))
        self.assertEqual((o["template"], o["value"], o["suffix"], o["label"], o["text"]),
                         ("LIB_TL_YEARS_LATER", 30.0, "YEARS", "LATER", "1998"))

    def test_a_range_as_said_is_from_and_to(self):
        [o] = _years(_plan(["From 1961 to 2008 the lake rose.", PLAIN, PLAIN]))
        self.assertEqual(o["template"], "LIB_TL_THEN_NOW_YEARS")
        self.assertEqual([(i["label"], i["value"]) for i in o["items"]], [("FROM", 1961), ("TO", 2008)])

    def test_then_and_now_only_when_today_is_said(self):
        m = self._one("Back in 1936, the dam was finished. Today it is drying up.")
        self.assertEqual(treatments.year_look_props("LIB_TL_THEN_NOW_YEARS", m["years"])["items"],
                         [{"label": "THEN", "value": 1936}, {"label": "NOW", "value": treatments.NOW_YEAR}])
        m = self._one("Back in 1936, the dam was finished.")
        self.assertIsNone(treatments.year_look_props("LIB_TL_THEN_NOW_YEARS", m["years"]))

    def test_the_counted_cards_only_for_a_jump_said_with_its_number(self):
        for text in ("Years later, in 2008, it was full.", "A few decades later, in 2008, it was full.",
                     "In 1890 the river ran free."):
            m = self._one(text, 1961)
            for tid in treatments.YEAR_COUNT_LOOKS:
                self.assertIsNone(treatments.year_look_props(tid, m["years"]), (tid, text))
        m = self._one("Half a century later, in 2011, it was full.", 1961)
        self.assertEqual(treatments.year_look_props("LIB_TL_TIME_PASSING", m["years"]),
                         {"value": 50, "suffix": "YEARS", "label": "LATER", "text": "2011"})

    def test_no_look_shows_a_number_the_story_did_not_say(self):
        out = _plan(MANY)
        said = {int(n) for n in re.findall(r"\b\d{4}\b", " ".join(MANY))} | {treatments.NOW_YEAR, 30, 2}
        for o in _years(out):
            nums = [o.get("value"), o.get("total")] + [i.get("value") for i in o.get("items") or []] \
                + [i.get("label") for i in o.get("items") or []] + [o.get("text")]
            for n in nums:
                if n not in (None, "") and re.fullmatch(r"\d+(\.0)?", str(n)):
                    self.assertIn(int(float(n)), said, (o["template"], n))

    def test_the_jump_as_said(self):
        cases = {"thirty years later": (30, "YEARS", "LATER"), "two decades later": (2, "DECADES", "LATER"),
                 "a century later": (1, "CENTURY", "LATER"), "half a century later": (50, "YEARS", "LATER"),
                 "20 years on": (20, "YEARS", "ON"), "a decade went by": (1, "DECADE", "WENT BY"),
                 "years later": None, "a few decades later": None, "several years later": None, "fast forward": None}
        for said, want in cases.items():
            self.assertEqual(treatments._jump_count(said), want, said)


class ALookAtItsLeastTime(unittest.TestCase):
    def test_the_slow_cards_stay_until_their_years_have_landed(self):
        # At 2.5 s the then / now card's second year still rolled when it flipped away (registry leastSeconds).
        want = {"LIB_TL_THEN_NOW_YEARS": 4.0, "LIB_TL_DECADE_GRID": 4.0, "LIB_TL_YEARS_LATER": 3.2,
                "TL_YEAR_ROLL_V1": 3.0}
        got = {o["template"]: o["durationInFrames"] / FPS for o in _years(_plan(MANY)) if o["template"] in want}
        self.assertEqual(set(got), set(want))
        for tid, least in want.items():
            self.assertGreaterEqual(got[tid], least - 1.0 / FPS, tid)
            self.assertEqual(templates.get(tid)["defaults"]["leastSeconds"], least, tid)

    def test_a_window_of_exactly_its_least_time_is_placed(self):
        # 2.7666 < 2.7667: float error left out every look whose animation sets its least time.
        out = _plan(_story("In 1961 the dam was finished.", "Years later, in 2008, it was full."))
        scroller = [o for o in _years(out) if o["template"] == "LIB_TL_YEAR_SCROLLER"]
        self.assertEqual(len(scroller), 1)
        least = treatments.animation_seconds(templates.get("LIB_TL_YEAR_SCROLLER"))
        self.assertGreaterEqual(scroller[0]["durationInFrames"], int(least * FPS) - 1)


if __name__ == "__main__":
    unittest.main()
