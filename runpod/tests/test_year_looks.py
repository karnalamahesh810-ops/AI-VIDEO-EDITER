"""
Years said on a line (the owner, 2026-10-02: "when we said years it only using year one ... on previous video we
got lot of different ones on timeline"; 2026-10-06, on the "Year Scroller Lens" of his Obama video - a big gold
"2008" in a glowing lens over blurred footage: "not great, remove it").

The scroller, the year roll, the decade grid, the years-later and time-passing cards and the then / now card are
retired (remotion/src/legacyLooks.ts draws them as the date family; the registry hides them). The build's date
pass keeps the year line for a jump in years; the data planner (src/datalooks.py) puts every year said on the
date family - the year counter rolling from the year the story was in, the timeline sliding to it, the badge -
never the same look twice in a row and never a year the narration did not say.
"""
import os
import re
import unittest

from src import datalooks as dl
from src import templates, treatments
from tests.test_vidrush_dates import FPS, PLAIN, _plan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEARS = set(treatments.YEAR_LOOKS) | set(treatments.RETIRED_YEAR_LOOKS)


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


def _words(lines, secs=5.0):
    out = []
    for i, text in enumerate(lines):
        for j, w in enumerate(text.split()):
            out.append({"text": w, "start": i * secs + j * 0.3, "end": i * secs + j * 0.3 + 0.25})
    return out


class TheRetiredLooks(unittest.TestCase):
    def test_they_are_retired_in_the_registry_and_the_renderer_and_never_picked(self):
        with open(os.path.join(ROOT, "remotion", "src", "legacyLooks.ts"), encoding="utf-8") as fh:
            ts = fh.read()
        for tid in treatments.RETIRED_YEAR_LOOKS:
            t = templates.get(tid)
            self.assertIsNotNone(t, tid)
            self.assertTrue(t.get("retired"), tid)
            self.assertFalse(templates.auto_pick(t), tid)
            self.assertFalse(treatments.auto_ok(tid), tid)
            self.assertIn(f'"{tid}"', ts, tid)
            self.assertIn(tid, dl.RETIRED_IDS, tid)
        self.assertEqual(treatments.YEAR_LOOKS, (treatments.VR_YEAR,))

    def test_an_older_plan_draws_them_as_the_date_family(self):
        got = dl.remap_retired({"template": "LIB_TL_YEAR_SCROLLER", "value": 2008, "subtitle": "YEARS LATER",
                                "startFrame": 30, "durationInFrames": 131})
        self.assertEqual((got["template"], got["value"], got["label"], got["startFrame"]),
                         (dl.KT_YEAR, 2008, "YEARS LATER", 30))
        roll = dl.remap_retired({"template": "TL_YEAR_ROLL_V1", "items": [{"label": "1961"}, {"label": "2008"}],
                                 "value": 2008})
        self.assertEqual([i["value"] for i in roll["items"]], [1961, 2008])
        then_now = dl.remap_retired({"template": "LIB_TL_THEN_NOW_YEARS",
                                     "items": [{"label": "FROM", "value": 1961}, {"label": "TO", "value": 2008}]})
        self.assertEqual((then_now["template"], [i["value"] for i in then_now["items"]]), (dl.KT_DATE_LINE, [1961, 2008]))
        later = dl.remap_retired({"template": "LIB_TL_YEARS_LATER", "value": 30, "suffix": "YEARS", "label": "LATER",
                                  "text": "1998"})
        self.assertEqual((later["template"], later["value"], later["label"]), (dl.KT_YEAR, 1998, "30 YEARS LATER"))
        card = dl.remap_retired({"template": "LIB_DT_CLEAN_CARD", "text": "SEPTEMBER 25, 2026", "label": "Lake Mead"})
        self.assertEqual((card["template"], card["text"], card["subtitle"], card["label"]),
                         (dl.KT_DATE_CARD, "September 25", "2026", "LAKE MEAD"))


class TheBuildsDatePass(unittest.TestCase):
    def test_a_jump_takes_the_year_line_never_a_retired_look(self):
        shown = [o["template"] for o in _years(_plan(MANY))]
        self.assertTrue(shown)
        self.assertEqual(set(shown), {treatments.VR_YEAR})

    def test_the_year_looks_keep_the_date_looks_room(self):
        out = _plan(_story("In 1961 the dam was finished.", "Years later, in 2008, it was full.", gap=6))
        self.assertEqual(len(_years(out)), 1)
        at = [o["startFrame"] / FPS for o in _years(_plan(MANY))]
        self.assertTrue(all(b - a >= treatments.VR_GAP for a, b in zip(at, at[1:])), at)

    def test_each_one_lands_on_the_year_as_said(self):
        out = _plan(_story("In 1961 the dam was finished.", "Years later, in 2008, it was full."))
        second = _years(out)[1]
        # "Years later, in 2008": the line starts at 85 s, "2008," is its fourth word (0.9 s in).
        self.assertAlmostEqual(second["startFrame"] / FPS, 85.9, delta=0.2)


class TheDataPlanner(unittest.TestCase):
    def setUp(self):
        self.looks, self.log = dl.plan(_words(MANY), FPS)
        self.years = [o for o in self.looks if o["template"] in dl.DATE_LOOKS]

    def test_every_year_said_has_a_look_and_no_look_repeats_back_to_back(self):
        said = sorted({int(y) for y in re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", " ".join(MANY))})
        shown = set()
        for o in self.years:
            shown.add(int(o.get("value") or o.get("subtitle")))
            shown.update(int(i["value"]) for i in o.get("items") or [])
        self.assertTrue(set(said) <= shown, (said, shown))
        ids = [o["template"] for o in self.years]
        self.assertFalse([a for a, b in zip(ids, ids[1:]) if a == b], ids)
        self.assertGreaterEqual(len(set(ids)), 2, ids)            # a jump: the counter and the timeline in turn
        self.assertTrue(set(ids) <= {dl.KT_YEAR, dl.KT_DATE_LINE, dl.KT_DATE_BADGE, dl.KT_DATE}, ids)

    def test_a_jump_rolls_from_the_year_the_story_was_in(self):
        later = next(o for o in self.years if o.get("value") == 2008 and o["template"] in (dl.KT_YEAR, dl.KT_DATE_LINE))
        self.assertEqual([i["value"] for i in later["items"]], [1961, 2008])

    def test_a_range_as_said_is_one_timeline(self):
        looks, _ = dl.plan(_words(["From 1961 to 2008 the lake rose.", PLAIN, PLAIN]), FPS)
        [o] = looks
        self.assertEqual(o["template"], dl.KT_DATE_LINE)
        self.assertEqual([i["value"] for i in o["items"]], [1961, 2008])
        self.assertGreater(o["items"][1]["at"], 0.0)              # the dot slides on when "2008" is said

    def test_no_look_shows_a_year_the_story_did_not_say(self):
        said = {int(n) for n in re.findall(r"\b\d{4}\b", " ".join(MANY))}
        for o in self.years:
            for n in [o.get("value")] + [i.get("value") for i in o.get("items") or []]:
                if n is not None:
                    self.assertIn(int(n), said, o)

    def test_the_jump_as_said(self):
        cases = {"thirty years later": (30, "YEARS", "LATER"), "two decades later": (2, "DECADES", "LATER"),
                 "a century later": (1, "CENTURY", "LATER"), "half a century later": (50, "YEARS", "LATER"),
                 "20 years on": (20, "YEARS", "ON"), "a decade went by": (1, "DECADE", "WENT BY"),
                 "years later": None, "a few decades later": None, "several years later": None, "fast forward": None}
        for said, want in cases.items():
            self.assertEqual(treatments._jump_count(said), want, said)


if __name__ == "__main__":
    unittest.main()
