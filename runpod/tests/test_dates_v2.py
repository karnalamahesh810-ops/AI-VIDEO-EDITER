"""
The date family, v2 (the owner, 2026-10-06, on his Obama video: "When dates are mentioned it barely shows them.
We need a PERFECT SIZE - not big, not small. The white one with the line is not great ... When dates are shown,
and percentages, detect them and add the animations - perfect ones, not full-screen ones, perfectly matched").

  * seven date / year / time looks (remotion LibKtDates.tsx) in one size rule: the date line a headline
    (capitals 6 % of the height), the kicker 2.5 %, the block 17-30 % of the width, 3.5-5 s on screen;
  * every date, year and time said gets one (a repeat within 20 s excepted), the looks rotate and never repeat
    back to back, two said a beat apart share one look (a timeline that slides on, a kicker);
  * every share said - "27 percent", "27%", "a quarter", "more than half", "one in three", "two-thirds",
    "doubled" - its ring / dots / bars on its word; never a half-brother or "one of three sons";
  * a date outranks the picture looks in the lane, and a scene's own text card is never moved for it.
Offline: no network, no database.
"""
import json
import os
import re
import unittest

from src import datalooks as dl
from src import lookplace, sfxplan, templates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS = 30


def words_for(lines, per_word=0.32):
    out = []
    for t, line in lines:
        for tok in line.split(" "):
            if tok:
                out.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.02, 3)})
                t += per_word
    return out


def moments(line):
    return dl.moments(dl.Narration(words_for([(0.0, line)])))


def doc_for(lines, overlays=None, seconds=None):
    words = words_for(lines)
    end = seconds or (words[-1]["end"] + 8.0)
    total = int(end * FPS)
    scenes = []
    for i in range(0, total, 150):
        scenes.append({"id": f"s{i}", "startFrame": i, "durationInFrames": min(150, total - i), "text": "",
                       "words": [w for w in words if i / FPS <= w["start"] < (i + 150) / FPS],
                       "media": {"type": "video", "url": f"https://x/{i}.mp4"}})
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": total, "scenes": scenes,
            "overlays": overlays or [], "sfx": []}


# Lines of the Obama script (project 70bc06d2), as its transcript has them.
OBAMA = [
    (0.0, "There's a photograph from the 3rd of October 1992, a church on the south side of Chicago,"),
    (42.0, "after their father. In 2011, the internal revenue service sent it a letter granting tax exempt status."),
    (73.0, "near Lake Victoria in 1936. He left on a scholarship to the University of Hawaii,"),
    (94.0, "They had a son, Roy, in 1958, and a daughter, Oma, in 1960."),
    (111.0, "Barack, was born on the 4th of August 1961. For a month in 1971, one month."),
    (140.0, "Then, Ken the last son. George was born in Nairobi in 1982"),
    (183.0, "And in November 1982, that surname came with an estate attached."),
    (192.0, "On the 24th of November 1982, Barack Obama's senior's car left the road in Nairobi."),
    (480.0, "In the summer of 2008, the reporters went to Cogalo."),
    (537.0, "They said he had visited in 1988 and again in 2006 as a senator."),
    (759.0, "Two years later, he appeared in a documentary by Dinesh D'Souza called 2016 Obama's America."),
    (792.0, "He sat in the debate hall in Las Vegas on the 19th of October 2016 as a guest of the Trump campaign."),
]


class TheSizeRule(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "typeScale.json"), encoding="utf-8") as fh:
            self.scale = json.load(fh)

    def test_a_date_is_a_headline_never_a_takeover(self):
        cap = 0.727                                         # Inter Tight's capitals (em)
        font = self.scale["dateLine"]["share"] / cap        # the date line's font as a share of the height
        self.assertTrue(0.07 <= font <= 0.09, font)          # 8.2 %: 89 px at 1080p
        self.assertAlmostEqual(self.scale["dateKicker"]["share"] / cap, 0.025, delta=0.003)
        block = self.scale["dateBlock"]
        self.assertTrue(0.15 <= block["minW"] < block["maxW"] <= 0.30, block)
        self.assertTrue(3.5 <= block["least"] < block["most"] <= 5.0, block)
        self.assertTrue(0.16 <= self.scale["ringD"]["share"] <= 0.20)
        self.assertTrue(0.12 <= self.scale["clock"]["diameter"] <= 0.2)

    def test_every_date_look_is_registered_ticks_and_stays_3_5_to_5_seconds(self):
        for tid in dl.DATE_LOOKS:
            t = templates.get(tid)
            self.assertIsNotNone(t, tid)
            self.assertTrue(templates.auto_pick(t), tid)
            self.assertFalse(t.get("retired"), tid)
            self.assertEqual(t["defaults"]["variant"], dl.variant_of(tid))
            least = dl.min_seconds({"template": tid})
            self.assertTrue(3.5 <= least <= 5.0, (tid, least))
            self.assertTrue(least <= dl.want_seconds({"template": tid}) <= 5.0, tid)
            self.assertGreaterEqual(t["defaults"]["leastSeconds"] + 1e-6, least, tid)
            # a date or a number only ever ticks (the owner, 2026-10-01)
            self.assertTrue(t["defaults"]["sounds"], tid)
            for s in t["defaults"]["sounds"]:
                self.assertEqual(sfxplan.category(s["name"]), "tick", (tid, s))
        self.assertTrue(set(dl.DATE_LOOKS) <= __import__("src.treatments", fromlist=["x"]).KT_DATE_LOOKS)

    def test_the_renderer_draws_every_one(self):
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "LibKtDates.tsx"), encoding="utf-8") as fh:
            src = fh.read()
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        for tid in dl.DATE_LOOKS:
            self.assertIn(f'"{dl.variant_of(tid)}": guard(', src, tid)
            self.assertIn(f'"{dl.variant_of(tid)}"', index, tid)


class EveryShareSaid(unittest.TestCase):
    def one(self, line, kind):
        got = [m for m in moments(line) if m["kind"] == kind]
        self.assertEqual(len(got), 1, (line, [(m["kind"], m["said"]) for m in moments(line)]))
        return got[0]

    def test_every_form(self):
        self.assertEqual(self.one("The lake is 27 percent full.", "percent")["value"], 27)
        self.assertEqual(self.one("The lake is 27% full.", "percent")["value"], 27)
        self.assertEqual(self.one("It fell to 27 per cent of its size.", "percent")["value"], 27)
        self.assertEqual(self.one("Only twenty-seven percent of it is left.", "percent")["value"], 27)
        q = self.one("A quarter of the water is gone.", "share")
        self.assertEqual((q["value"], q["total"]), (1, 4))
        t = self.one("Two-thirds of the river goes to farms.", "share")
        self.assertEqual((t["value"], t["total"]), (2, 3))
        self.assertEqual(self.one("More than half of the water goes to farms.", "percent")["value"], 50)
        self.assertEqual(self.one("Half the country is in drought.", "percent")["value"], 50)
        o = self.one("One in three Americans lives with a warning.", "progress")
        self.assertEqual((o["value"], o["total"], o["joiner"]), (1, 3, "in"))
        o = self.one("Three out of four gallons go to farms.", "progress")
        self.assertEqual((o["value"], o["total"], o["joiner"]), (3, 4, "out of"))
        self.assertEqual(self.one("Nearly three of every four gallons go to farms.", "progress")["total"], 4)
        self.assertEqual(self.one("Water use doubled in a decade.", "multiplier")["value"], 2)
        self.assertEqual(self.one("The price tripled.", "multiplier")["value"], 3)
        self.assertEqual(self.one("Demand grew tenfold.", "multiplier")["value"], 10)
        self.assertEqual(self.one("The budget was cut in half.", "percent")["value"], 50)

    def test_never_a_half_brother_a_member_or_a_span(self):
        for line in ("His half-brother Malik was the best man.", "his older half -brother Malik had flown in.",
                     "the father's half sister was living in Boston.", "the father's half brother was arrested.",
                     "For half a century, it sat with the federal government.", "It took two and a half years.",
                     "In the first half of the year it rained.", "He was one of three sons.",
                     "One of eight children stayed.", "A third brother lived there.",
                     "It lasted a quarter of a century.", "The dam is a third of a mile wide.",
                     "They met at a quarter past nine."):
            got = [m for m in moments(line) if m["kind"] in ("percent", "share", "progress")]
            self.assertEqual(got, [], line)

    def test_each_has_its_look_on_its_word(self):
        looks, _ = dl.plan(words_for([(0.0, "Lake Mead is 27 percent full."),
                                      (20.0, "More than half of the water goes to farms."),
                                      (40.0, "One in three Americans lives with a warning."),
                                      (60.0, "Two-thirds of the river goes to farms."),
                                      (80.0, "Water use doubled in a decade.")]), FPS)
        def near(t):
            return next(o for o in looks if abs(o["_at"] - t) < 3.0)
        self.assertEqual((near(0)["template"], near(0)["value"]), (dl.KT_PERCENT, 27))
        self.assertAlmostEqual(near(0)["_at"], 3 * 0.32, delta=0.01)          # on "27"
        self.assertEqual((near(20)["value"], near(20)["label"]), (50, "MORE THAN"))
        p = near(40)               # the dots ("1 in 3"), or the ring ("1/3") when the look before it had the dots' style
        self.assertEqual((p["value"], p["total"]), (1, 3))
        self.assertTrue((p["template"], p.get("text")) in ((dl.KT_PROGRESS, "in"), (dl.KT_PERCENT, None)), p)
        self.assertEqual((near(60)["value"], near(60)["total"]), (2, 3))       # the ring "2/3" (or the dots after a ring)
        self.assertIn(near(60)["template"], (dl.KT_PERCENT, dl.KT_PROGRESS))
        self.assertEqual((near(80)["template"], near(80)["value"], near(80)["label"]), (dl.KT_MULTIPLIER, 2, "DOUBLED"))


class EveryDateSaid(unittest.TestCase):
    def test_dates_times_years_and_a_scenes_time_of_day(self):
        [d] = [m for m in moments("There's a photograph from the 3rd of October 1992, a church.") if m["kind"] == "date"]
        self.assertEqual((d["month"], d["day"], d["year"]), ("October", 3, 1992))
        self.assertEqual([m["label"] for m in moments("Lights on the strip at three in the morning.")
                          if m["kind"] == "time"], ["3 AM"])
        [t] = [m for m in moments("The call came at seven o'clock that evening.") if m["kind"] == "time"]
        self.assertEqual((t["label"], t["kicker"]), ("7:00 PM", "THAT EVENING"))
        self.assertEqual([m["label"] for m in moments("They met at noon.") if m["kind"] == "time"], ["12:00 PM"])
        self.assertEqual([m["label"] for m in moments("The alarm came in at 21:40 that day.") if m["kind"] == "time"],
                         ["21:40"])
        self.assertEqual([m["label"] for m in moments("The first alert went out at 9:08 a.m. sharp.")
                          if m["kind"] == "time"], ["9:08 AM"])
        self.assertEqual([m["label"] for m in moments("Plain words. That evening, the rain began.")
                          if m["kind"] == "daypart"], ["That evening"])
        # a year that names a work is not the story's time
        self.assertFalse([m for m in moments("He appeared in a documentary called 2016 Obama's America.")
                          if m["kind"] == "year"])

    def test_the_kicker_is_what_the_narration_said_with_it(self):
        def kicker(line, kind):
            return next(m for m in moments(line) if m["kind"] == kind)["kicker"]
        self.assertEqual(kicker("George was born in Nairobi in 1982 to a woman.", "year"), "NAIROBI")
        self.assertEqual(kicker("He sat in the debate hall in Las Vegas on the 19th of October 2016 as a guest.", "date"),
                         "LAS VEGAS")
        self.assertEqual(kicker("In the summer of 2008, the reporters went to Cogalo.", "year"), "THE SUMMER OF")
        self.assertEqual(kicker("On the night of the 24th of November 1982, the car left the road.", "date"),
                         "THE NIGHT OF")
        self.assertEqual(kicker("On Friday, August 21, 2026, it was decided.", "date"), "FRIDAY")
        self.assertEqual(kicker("In 2011, the internal revenue service sent it a letter.", "year"), "")
        self.assertEqual(kicker("Barack was born on the 4th of August 1961.", "date"), "")

    def test_every_one_gets_a_date_look_rotating_never_back_to_back(self):
        looks, log = dl.plan(words_for(OBAMA), FPS)
        dates = [o for o in looks if o["template"] in dl.DATE_LOOKS]
        ids = [o["template"] for o in dates]
        self.assertFalse([a for a, b in zip(ids, ids[1:]) if a == b], ids)
        self.assertGreaterEqual(len(set(ids)), 4, ids)
        shown = set()
        for o in dates:
            shown.update(int(i["value"]) for i in o.get("items") or [])
            for v in (o.get("value"), o.get("subtitle")):
                if v not in (None, ""):
                    shown.add(int(v))
        # every year said, but the film's title and the summer of 2008 shown 20 s before... (none here: 2008 is new)
        said = {1992, 2011, 1936, 1958, 1960, 1961, 1971, 1982, 2008, 1988, 2006, 2016}
        self.assertEqual(said - shown, set())
        # the dates as said, with what came with them
        card = next(o for o in dates if o.get("text") == "October 19")
        self.assertEqual((card["subtitle"], card["label"]), ("2016", "LAS VEGAS"))
        nairobi = next(o for o in dates if 1982 in [int(o.get("value") or 0)] + [i["value"] for i in o.get("items") or []]
                       and o["_at"] < 150)
        self.assertEqual(nairobi["label"], "NAIROBI")
        # no look for the film's "2016" (a title), none early: each starts on its first word
        self.assertFalse([o for o in dates if 760 < o["_at"] < 790])

    def test_two_years_a_beat_apart_are_one_timeline_that_slides_on_when_the_second_is_said(self):
        looks, log = dl.plan(words_for([(94.0, "They had a son, Roy, in 1958, and a daughter, Oma, in 1960.")]), FPS)
        [o] = looks
        self.assertEqual(o["template"], dl.KT_DATE_LINE)
        self.assertEqual([i["value"] for i in o["items"]], [1958, 1960])
        gap = 6 * 0.32                                               # "1958," ... "1960." six words on
        self.assertAlmostEqual(o["items"][1]["at"], gap + dl.MAX_LEAD_S, delta=0.05)
        self.assertTrue(any("timeline" in (r.get("why") or "") for r in log))
        # the look stays until the second year has landed and held
        self.assertGreaterEqual(dl.min_seconds(o), o["items"][1]["at"] + dl.DATE_LEG[o["template"]] + dl.MIN_HOLD["date"])

    def test_repeats_within_20_seconds_are_one_later_ones_show_again(self):
        looks, log = dl.plan(words_for([(0.0, "It began in 1982."), (10.0, "By 1982 it was over."),
                                        (40.0, "In 1982 the court opened the file.")]), FPS)
        ats = [round(o["_at"]) for o in looks]
        self.assertEqual(ats, [1, 40])
        self.assertTrue(any("shown" in (r.get("why") or "") for r in log))

    def test_a_time_and_its_date_are_one_look_a_figure_carries_its_date(self):
        looks, _ = dl.plan(words_for([(0.0, "On August 21, 2026, at 3 a.m., the dam broke.")]), FPS)
        [o] = looks
        self.assertEqual((o["template"] in (dl.KT_TIME, dl.KT_TIME_CLOCK), o["text"], o["label"]),
                         (True, "3 AM", "AUG 21, 2026"))
        looks, _ = dl.plan(words_for([(0.0, "In 2008, Lake Mead was 27 percent full.")]), FPS)
        [o] = looks
        self.assertEqual((o["template"], o["value"], o["label"]), (dl.KT_PERCENT, 27, "LAKE MEAD · 2008"))

    def test_the_lane_never_drops_a_date_for_a_picture_look(self):
        # a postcard and a document planned right on the year: the year keeps its word, they move or go
        over = [{"type": "motion", "template": "LIB_PX_POSTCARD", "startFrame": 30 * 40, "durationInFrames": 150,
                 "text": "Nairobi"},
                {"type": "motion", "template": "LIB_PR_DOC_SPOTLIGHT", "startFrame": 30 * 41, "durationInFrames": 180,
                 "text": "The letter"}]
        doc = doc_for([(40.0, "In 2011, the service sent it a letter granting tax exempt status.")], overlays=over,
                      seconds=80)
        dl.finish(doc)
        year = next(o for o in doc["overlays"] if o["template"] in dl.DATE_LOOKS)
        self.assertLessEqual(abs(year["startFrame"] / FPS - (40.0 + 0.32)), 0.1)
        self.assertEqual(dl.overlapping(doc["overlays"]), [])
        self.assertEqual(dl.short_overlays(doc["overlays"], FPS), [])

    def test_a_scenes_own_text_card_keeps_its_frames(self):
        card = {"type": "highlight", "text": "There's a photograph from the 3rd of October 1992,", "startFrame": 0,
                "durationInFrames": 187}
        doc = doc_for([(0.0, "There's a photograph from the 3rd of October 1992, a church on the south side.")],
                      overlays=[dict(card)], seconds=40)
        rep = dl.finish(doc)
        self.assertIn(card, doc["overlays"])
        self.assertTrue([o for o in doc["overlays"] if o.get("template") in dl.DATE_LOOKS])
        self.assertEqual(rep["shortAfter"], 0)

    def test_a_brand_kit_that_leaves_one_look_out_gets_another_date_look(self):
        doc = doc_for(OBAMA[:5], seconds=140)
        doc["meta"] = {"brandKit": {"picks": {"looks": [dl.KT_DATE, dl.KT_YEAR, dl.KT_TIME]}}}
        dl.finish(doc)
        ids = {o["template"] for o in doc["overlays"]}
        self.assertTrue(ids)
        self.assertTrue(ids <= {dl.KT_DATE, dl.KT_YEAR, dl.KT_TIME}, ids)


class TheRetiredLooks(unittest.TestCase):
    def test_the_worker_and_the_renderer_retire_the_same_looks(self):
        with open(os.path.join(ROOT, "remotion", "src", "legacyLooks.ts"), encoding="utf-8") as fh:
            src = fh.read()
        body = re.sub(r"//[^\n]*", "", re.search(r"RETIRED_IDS\s*=\s*\[(.*?)\]\s*as const", src, re.S).group(1))
        self.assertEqual(set(re.findall(r'"([A-Z0-9_]+)"', body)), set(dl.RETIRED_IDS))
        for tid in ("LIB_TL_YEAR_SCROLLER", "LIB_TL_DECADE_GRID", "LIB_TL_YEARS_LATER", "LIB_TL_TIME_PASSING",
                    "LIB_TL_THEN_NOW_YEARS", "LIB_TL_DATE_STAMP_CIRCLE", "LIB_TL_CALENDAR_FLIP", "TL_YEAR_ROLL_V1",
                    "TL_DATE_TITLE_V1", "LIB_DT_DATE_SLAM", "LIB_DT_CLEAN_CARD"):
            self.assertTrue(templates.get(tid).get("retired"), tid)
            self.assertIsNotNone(dl.remap_retired({"template": tid, "text": "March 1, 1936", "value": 1936}), tid)

    def test_a_replan_takes_them_off_and_shows_the_year_on_the_date_family(self):
        over = [{"type": "motion", "template": "LIB_TL_YEAR_SCROLLER", "startFrame": 30 * 41, "durationInFrames": 131,
                 "value": 2011}]
        doc = doc_for([(40.0, "In 2011, the service sent it a letter granting tax exempt status.")], overlays=over,
                      seconds=80)
        rep = dl.finish(doc)
        ids = [o["template"] for o in doc["overlays"]]
        self.assertNotIn("LIB_TL_YEAR_SCROLLER", ids)
        self.assertTrue(set(ids) & set(dl.DATE_LOOKS))
        self.assertTrue(any(r["template"] == "LIB_TL_YEAR_SCROLLER" for r in rep["removed"]))


class ThePlace(unittest.TestCase):
    def test_a_date_draws_its_own_glass_never_the_side_panel(self):
        ovs = [{"template": tid, "startFrame": 10 + i * 200, "durationInFrames": 150} for i, tid in enumerate(dl.DATE_LOOKS)]
        scenes = [{"id": "s0", "startFrame": 0, "durationInFrames": 3000,
                   "media": {"type": "video", "url": "https://x/c.mp4", "focus": {"busy": 0.9}}}]
        lookplace.place(ovs, scenes, fetch=lambda u: None)
        self.assertFalse([o for o in ovs if o.get("backing")])


if __name__ == "__main__":
    unittest.main()
