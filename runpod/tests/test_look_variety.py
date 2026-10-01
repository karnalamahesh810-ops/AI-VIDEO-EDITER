"""
The owner's review (2026-09-29): the same text look every thirty seconds,
the banned white-and-red headline family, dates that never showed, the first
percent always the same gauge, one photo look on every still, no full-screen
introduction for the people of the story. A 20-minute plan must now:

  * never choose a banned look, and never show a look twice within 4 minutes;
  * give every line that names a date or a time a date/time look (the opening
    line at 0.4 s with a chapter hint included);
  * rotate percentages over at least four looks in eight lines;
  * introduce each named person full screen on their first mention only;
  * resolve the director's typewriter hints to looks that really type.
"""
import unittest

from src import templates, timeline, treatments
from src.transcribe import Segment

FPS = 30
DUR = 5.0
START = 0.4
N = 240          # 240 lines of 5 s: 20 minutes

PLAIN = ["The water kept moving through the canyon walls.", "Crews worked through the long night shift.",
         "Engineers watched the gauges closely.", "Farmers in the valley waited for news.",
         "Most residents had never seen it this low.", "The river has shaped this land for ages.",
         "The town council met again that week.", "Boat ramps now end in dry gravel.",
         "Marinas were dragged downhill again and again.", "The water managers kept their plans quiet."]
DATE_LINES = {0: "On September 15, 2026, Lake Mead fell to a level nobody alive had seen.",
              20: "By March 2026 the cuts were official.",
              50: "On Monday, August 21st, the government announced new cuts.",
              80: "At 3:45 pm on July 4, the spillway gates opened.",
              110: "The emergency meeting ran past midnight.",
              140: "On the fifteenth of June it finally rained.",
              170: "Sept. 25 was the deadline for the states.",
              200: "In October 2025 the lake hit a new low.",
              230: "They left the marina at dawn."}
PERCENTS = {10: 26, 34: 31, 58: 44, 82: 18, 106: 22, 130: 57, 154: 63, 178: 12, 202: 38, 226: 71}
CAST = [{"name": "Brad Udall", "aliases": ["Udall"], "role": "Water researcher"},
        {"name": "Katie Hobbs", "aliases": [], "role": "Governor of Arizona"},
        {"name": "Pat Mulroy", "aliases": [], "role": ""}]
# index -> (person, how the line names them); the first index per person is the first mention.
PEOPLE = {15: ("Brad Udall", "lower-third"), 40: ("Brad Udall", "text"), 95: ("Brad Udall", "text"),
          70: ("Katie Hobbs", "subject"), 100: ("Katie Hobbs", "text"), 160: ("Katie Hobbs", "text"),
          125: ("Pat Mulroy", "text"), 190: ("Pat Mulroy", "lower-third")}
TYPEWRITER = {25, 65, 105, 145, 185, 225}
QUESTIONS = {45, 135, 215}
HIGHLIGHTS = {30, 90, 150, 210}
MAPS = {60: "satellite-pulse", 120: "satellite-tilt", 180: ""}


def build(n=N):
    """(segments, shots, scenes, brief) for a 20-minute story with every kind of beat."""
    segs, shots, scenes = [], [], []
    for i in range(n):
        shot = {"subject": "Lake Mead"}
        kind = "video"
        if i in DATE_LINES:
            text = DATE_LINES[i]
            if i == 0:
                # The rule director's opening chapter: the title cut at 90 characters.
                shot["overlay"] = {"type": "chapter",
                                   "text": "Lake Mead Is Running Out Of Water And The Southwest Has No Plan B Left"}
        elif i in PERCENTS:
            text = f"Lake Mead is now at {PERCENTS[i]} percent of its capacity."
        elif i in PEOPLE:
            name, how = PEOPLE[i]
            text = (f"{name} has studied the river for decades." if how != "text"
                    else f"{name} says the numbers do not add up.")
            shot = {"subject": name, "subjectType": "person"}
            if how == "lower-third":
                shot["overlay"] = {"type": "lower-third", "text": name}
        elif i in TYPEWRITER:
            text = "So where did all of the water actually go?"
            shot["overlay"] = {"type": "typewriter", "text": text}
        elif i in QUESTIONS:
            text = "Is this the end of the Colorado River as we know it?"
        elif i in HIGHLIGHTS:
            text = "The largest reservoir in the country is disappearing."
            shot["overlay"] = {"type": "sentence-highlight", "text": text, "highlight": "largest reservoir"}
        elif i in MAPS:
            text = "It sits just outside Las Vegas, Nevada."
            shot = {"subject": "Las Vegas", "overlay": {"type": "map", "variant": MAPS[i], "text": "Las Vegas",
                                                        "locations": [{"label": "Las Vegas", "lat": 36.1,
                                                                       "lon": -115.1}]}}
        elif i % 9 == 4:
            text = "The old intake tower now stands in open air."
            kind = "image"
            shot = {"subject": ("Hoover Dam", "Intake Tower", "Boulder City")[i % 3],
                    "subjectType": ("place", "object", "place")[i % 3]}
        else:
            text = PLAIN[i % len(PLAIN)]
        a = START + i * DUR if i else START
        b = START + (i + 1) * DUR
        segs.append(Segment(text=text, start=a, end=b))
        shots.append(shot)
        scenes.append({"id": f"s{i}", "startFrame": int(round(a * FPS)) if i else 0,
                       "durationInFrames": int(round((b - (a if i else 0)) * FPS)),
                       "media": {"type": kind, "url": f"https://x/{i}.{'jpg' if kind == 'image' else 'mp4'}"},
                       "transition": "none", "motion": "none", "effect": "none"})
    brief = {"kind": "explainer", "hookBeats": [0], "cast": CAST,
             "sections": [{"from": 0, "to": 79}, {"from": 80, "to": 159}, {"from": 160, "to": n - 1}]}
    return segs, shots, scenes, brief


def run(pack="documentary"):
    segs, shots, scenes, brief = build()
    total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
    out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, pack),
                          timeline._OVERLAY_SECONDS)
    return segs, out


def cues(o):
    return set(templates.cues_of(templates.get(o["template"]) or {}))


def on_line(ovs, seg, slack=treatments.SLIDE_SLACK):
    return [o for o in ovs if seg.start - 0.2 <= o["startFrame"] / FPS < seg.end + slack]


class TwentyMinutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segs, cls.out = run()
        cls.ovs = sorted(cls.out["overlays"], key=lambda o: o["startFrame"])

    def test_never_a_banned_look_in_any_pack(self):
        for pack in templates.style_packs():
            _segs, out = run(pack)
            used = [o["template"] for o in out["overlays"]]
            self.assertFalse(set(used) & templates.BANNED, pack)
            self.assertTrue(used, pack)

    def test_no_look_twice_within_four_minutes(self):
        for pack in ("documentary", "news", "history"):
            _segs, out = run(pack)
            last = {}
            for o in sorted(out["overlays"], key=lambda o: o["startFrame"]):
                at = o["startFrame"] / FPS
                if o["template"] in (treatments.TEXT_DATE_LOOK, treatments.BOLD_COUNT_LOOK):
                    continue    # the bold-text date and count lead their cues every time (their placement turns)
                if o["template"] in last:
                    self.assertGreaterEqual(at - last[o["template"]], treatments.LOOK_GAP,
                                            f"{pack}: {o['template']} at {at:.1f}s and {last[o['template']]:.1f}s")
                last[o["template"]] = at

    def test_dates_are_rare_and_each_look_keeps_its_place(self):
        # The owner, 2026-10-01 (VidRush): one date or time graphic per 75 s at most, the
        # centred date once per 150 s, nothing for "past midnight" or "at dawn".
        vr = [o for o in self.ovs if o["template"] in treatments.VR_LOOKS]
        got = {i: [(o["template"], o.get("text"), o.get("subtitle")) for o in on_line(vr, self.segs[i])]
               for i in DATE_LINES}
        self.assertEqual(got[0], [(treatments.VR_HERO, "SEPTEMBER 15", "2026")])        # the story's start date
        self.assertEqual(got[20], [])            # "March 2026" 100 s after the first centred date
        self.assertEqual(got[50], [(treatments.VR_HERO, "AUGUST 21", "")])               # no worked-out weekday
        self.assertEqual(got[80], [(treatments.VR_TIME, "3:45 PM", "JULY 4")])           # the date said with it
        self.assertEqual(got[110], [])           # "ran past midnight": not a clock time
        self.assertEqual(got[140], [(treatments.VR_HERO, "JUNE 15", "")])
        self.assertEqual(got[230], [])           # "at dawn": not a clock time
        self.assertEqual(len(vr), sum(1 for v in got.values() if v))
        at = [o["startFrame"] / FPS for o in vr]
        self.assertTrue(all(b - a >= treatments.VR_GAP for a, b in zip(at, at[1:])), at)
        heroes = [o["startFrame"] / FPS for o in vr if o["template"] == treatments.VR_HERO]
        self.assertTrue(all(b - a >= treatments.VR_HERO_GAP for a, b in zip(heroes, heroes[1:])), heroes)
        # The opening line (0.4 s, a chapter hint on it) opens on its date.
        self.assertIs(self.ovs[0], vr[0])
        self.assertLessEqual(vr[0]["startFrame"], int(round(START * FPS)) + 1)
        self.assertFalse([o for o in self.ovs if o["template"] in treatments.OLD_DATE_LOOKS
                          or o["template"].startswith("LIB_DTX_")])

    def test_percentages_count_up_in_varied_looks(self):
        looks = []
        for i, v in PERCENTS.items():
            got = [o for o in on_line(self.ovs, self.segs[i]) if o.get("value") == float(v)]
            self.assertTrue(got, f"line {i}: {v}%")
            self.assertIn("percent", cues(got[0]), got[0]["template"])
            looks.append(got[0]["template"])
        # The bold count leads; another look comes in after two of them in a row.
        bold = treatments.BOLD_COUNT_LOOK
        self.assertEqual(looks[0], bold, looks)
        self.assertFalse(any(looks[i:i + 3] == [bold] * 3 for i in range(len(looks))), looks)
        self.assertGreaterEqual(len(set(looks[:8])), 3, looks)
        # A compact figure over footage: cards in a corner, never full screen.
        for i in PERCENTS:
            for o in on_line(self.ovs, self.segs[i]):
                if o.get("value") is not None and (templates.get(o["template"]) or {}).get("kind") != "tag":
                    self.assertTrue(o.get("compact"), o["template"])

    def test_a_person_is_introduced_full_screen_on_the_first_mention_only(self):
        intros = [o for o in self.ovs if "person-full" in cues(o)]
        firsts = {}
        for i in sorted(PEOPLE):
            firsts.setdefault(PEOPLE[i][0], i)
        self.assertEqual(sorted(o["text"] for o in intros), sorted(firsts))
        for o in intros:
            seg = self.segs[firsts[o["text"]]]
            self.assertTrue(seg.start - 0.2 <= o["startFrame"] / FPS <= seg.end + treatments.SLIDE_SLACK, o)
        cast_roles = {c["name"]: c["role"] for c in CAST}
        for o in intros:
            if cast_roles[o["text"]] and "subtitle" in templates.get(o["template"])["props"]:
                self.assertEqual(o.get("subtitle"), cast_roles[o["text"]])
        # Never two introductions within 45 s.
        starts = sorted(o["startFrame"] / FPS for o in intros)
        self.assertTrue(all(b - a >= treatments.PERSON_FULL_GAP for a, b in zip(starts, starts[1:])))

    def test_typewriter_hints_resolve_to_typing_looks(self):
        typed = 0
        for i in TYPEWRITER:
            for o in on_line(self.ovs, self.segs[i], slack=0.0):
                self.assertTrue(templates.types(templates.get(o["template"])), o["template"])
                typed += 1
        self.assertGreaterEqual(typed, 3)

    def test_text_is_a_proper_size(self):
        for o in self.ovs:
            self.assertLessEqual(o.get("fontScale", 1.0), 1.15, o["template"])

    def test_the_same_script_plans_the_same_way(self):
        _segs, again = run()
        self.assertEqual(self.out["overlays"], again["overlays"])


def small(texts, shots=None, kinds=None, pack="documentary", start=0.0, sections=()):
    segs = [Segment(text=t, start=(start if i == 0 else i * 6.0), end=(i + 1) * 6.0) for i, t in enumerate(texts)]
    shots = shots or [{"subject": "Lake Mead"} for _ in texts]
    kinds = kinds or ["video"] * len(texts)
    scenes = [{"id": f"s{i}", "startFrame": int(i * 180), "durationInFrames": 180,
               "media": {"type": k, "url": f"https://x/{i}"}, "transition": "none", "motion": "none", "effect": "none"}
              for i, k in enumerate(kinds)]
    brief = {"kind": "explainer", "hookBeats": [], "sections": [{"from": s, "to": s} for s in sections]}
    return treatments.plan(segs, shots, scenes, FPS, len(texts) * 180, brief, treatments.pack_for(brief, pack),
                           timeline._OVERLAY_SECONDS)


class Rules(unittest.TestCase):
    def test_the_opening_date_beats_a_news_chapter_banner(self):
        # Cause A (a scene-0 chapter hint won) and cause B (a first line at 0.4 s
        # could never get a card): the date card opens the video.
        shots = [{"subject": "Glen Canyon Dam", "overlay": {"type": "chapter", "text": "Glen Canyon Dam " * 6}}]
        out = small(["On the fifteenth of September, the gauge at Glen Canyon Dam read 3,510 feet."], shots,
                    pack="news", start=0.4, sections=(0,))
        first = sorted(out["overlays"], key=lambda o: o["startFrame"])[0]
        self.assertTrue(cues(first) & set(treatments.DATE_CUES), first["template"])
        self.assertEqual(first["text"], "SEPTEMBER 15")
        self.assertNotIn("HEADLINE_BANNER_V1", [o["template"] for o in out["overlays"]])

    def test_director_text_hints_go_through_the_rotation(self):
        texts, shots = [], []
        for i in range(8):
            texts.append("The largest reservoir in the country is disappearing." if i % 2 == 0 else
                         "Plain words about the water here.")
            shots.append({"subject": "Lake Mead", "overlay": {"type": "sentence-highlight", "text": texts[-1],
                                                              "highlight": "largest reservoir"}} if i % 2 == 0
                         else {"subject": "Lake Mead"})
        out = small(texts, shots)
        used = [o["template"] for o in out["overlays"]]
        self.assertTrue(used)
        self.assertFalse(set(used) & templates.BANNED)
        self.assertEqual(len(used), len(set(used)), used)
        fams = [templates.family(templates.get(t)) for t in used]
        self.assertTrue(all(a != b for a, b in zip(fams, fams[1:])), fams)

    def test_two_text_beats_in_a_row_never_share_a_family(self):
        looks = treatments._Looks(1, {})
        pool = templates.for_cue("key-phrase") + templates.for_cue("headline")
        first = looks.order(pool, 0.0, text_beat=True)[0][0]
        looks.use(first, 0.0, "text", text_beat=True)
        fresh, stale = looks.order(pool, 30.0, text_beat=True)
        others = [t for t in pool if templates.family(t) != templates.family(first)]
        if others:
            self.assertTrue(all(templates.family(t) != templates.family(first) for t in fresh + stale))

    def test_the_quiet_stretch_label_rotates_and_says_the_line(self):
        texts = ["Plain words about the water here."] * 4 + ["Now Hoover Dam comes into view."] + \
                ["Plain words about the water here."] * 4 + ["Then Boulder City appears below."]
        out = small(texts, [{"subject": ""} for _ in texts])
        labels = [(o["template"], o["text"].upper()) for o in out["overlays"]]
        self.assertEqual([t for _l, t in labels], ["HOOVER DAM", "BOULDER CITY"])
        self.assertNotEqual(labels[0][0], labels[1][0])
        for tid, _t in labels:
            self.assertTrue(cues({"template": tid}) & {"caption", "key-phrase"}, tid)

    def test_about_one_still_in_two_gets_a_photo_look_never_the_same_twice_in_a_row(self):
        n = 12
        out = small(["The old intake tower now stands in open air."] * n,
                    [{"subject": "Hoover Dam", "subjectType": "place"} for _ in range(n)], kinds=["image"] * n)
        photos = [o["template"] for o in out["overlays"]
                  if cues(o) & {"photo", "photo-place", "place-photo", "photos"}]
        self.assertTrue(3 <= len(photos) <= 8, photos)
        self.assertTrue(all(a != b for a, b in zip(photos, photos[1:])), photos)

    def test_numbers_are_never_dropped_for_rhythm(self):
        texts = ["Lake Mead is now at 26 percent of capacity.", "Lake Powell holds 31 percent of its water.",
                 "The basin lost 40 percent of its snow.", "Only 18 percent of the valley is irrigated."]
        out = small(texts)
        values = sorted(o.get("value") for o in out["overlays"] if o.get("value") is not None)
        self.assertEqual(values, [18.0, 26.0, 31.0, 40.0])
        # The bold count leads, one other look after two in a row.
        looks = [o["template"] for o in sorted(out["overlays"], key=lambda o: o["startFrame"])]
        self.assertEqual(looks.count(treatments.BOLD_COUNT_LOOK), 3, looks)
        self.assertNotEqual(looks[2], treatments.BOLD_COUNT_LOOK, looks)


if __name__ == "__main__":
    unittest.main()


class Density(unittest.TestCase):
    """Video styles (src/styles.py): a news compilation shows almost no graphics."""

    def _plan(self, density, brief_kind="explainer"):
        from unittest import mock
        from src import config
        segs, shots, scenes, brief = build()
        brief["kind"] = brief_kind
        total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
        with mock.patch.object(config, "GRAPHICS_DENSITY", density):
            return treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, "news"),
                                   timeline._OVERLAY_SECONDS)

    def test_minimal_keeps_dates_spaced_figures_and_maps_only(self):
        rich = self._plan("rich")["overlays"]
        minimal = sorted(self._plan("minimal")["overlays"], key=lambda o: o["startFrame"])
        self.assertLess(len(minimal), len(rich) / 2)
        allowed = {"date", "datetime", "time-of-day", "percent", "big-number", "count", "money", "money-compare",
                   "change", "then-now", "place", "region", "several-places", "route", "distance", "disaster",
                   "forecast", "forecast-wind", "forecast-rain", "measurement", "change-length", "series",
                   "shares", "ratio", "compare-values", "years", "span"}
        for o in minimal:
            t = templates.get(o["template"]) or {}
            self.assertTrue(cues(o) & allowed or t.get("category") == "MAPS" or o["template"] in treatments.VR_LOOKS,
                            (o["template"], cues(o)))
        # The dates are the rich plan's: as rare (one per VR_GAP at most), the same moments.
        dated = [(o["template"], o.get("text")) for o in minimal if o["template"] in treatments.VR_LOOKS]
        self.assertEqual(dated, [(o["template"], o.get("text")) for o in sorted(rich, key=lambda o: o["startFrame"])
                                 if o["template"] in treatments.VR_LOOKS])
        self.assertGreaterEqual(len(dated), 4)
        figures = [o["startFrame"] / FPS for o in minimal
                   if cues(o) & {"percent", "big-number", "count", "money"}]
        self.assertTrue(all(b - a >= treatments.MINIMAL_FIGURE_GAP - 0.01 for a, b in zip(figures, figures[1:])),
                        figures)

    def test_normal_drops_only_the_filler_label(self):
        normal = self._plan("normal")["overlays"]
        self.assertTrue(normal)
        self.assertFalse([o for o in normal if o.get("_group") == "filler"])

    def test_a_figure_that_never_showed_does_not_hold_back_the_next(self):
        # The date card takes the line and "3 feet" (not a clear figure) finds no
        # room: the 45 s window starts only when a figure lands, so the clear
        # percent 18 s later still shows.
        texts = ["The storm kept moving east."] * 12
        texts[2] = "On September 15, 3 feet of snow fell in Worcester."
        texts[5] = "By then 40% of Boston had lost power."
        out = weather_plan(texts, "minimal", kind="news", mapped=False)["overlays"]
        self.assertFalse([o for o in out if o.get("value") == 3.0], out)
        self.assertTrue([o for o in out if o.get("value") == 40.0], [o["template"] for o in out])


class ForecastMap(unittest.TestCase):
    def test_a_weather_story_forecast_line_gets_the_model_map(self):
        segs, shots, scenes, brief = build(40)
        brief["kind"] = "weather"
        segs[31] = Segment(text="Wind gusts up to 60 mph will hit the Jersey shore tonight.",
                           start=segs[31].start, end=segs[31].end)
        shots[31] = {"subject": "Jersey shore"}
        # A map earlier in the video gave the region's coordinates.
        shots[30] = {"subject": "Atlantic City", "overlay": {"type": "map", "text": "Atlantic City", "locations": [
            {"label": "Atlantic City, NJ", "lat": 39.36, "lon": -74.42}]}}
        total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
        out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, "weather"),
                              timeline._OVERLAY_SECONDS)
        wx = [o for o in out["overlays"] if str(o.get("template", "")).startswith("LIB_WX_")]
        self.assertEqual([o["template"] for o in wx], ["LIB_WX_WIND_FLOW"])
        self.assertEqual(wx[0]["locations"][0]["label"], "Atlantic City, NJ")

    def test_no_region_no_forecast_map(self):
        segs, shots, scenes, brief = build(20)
        brief["kind"] = "weather"
        segs[5] = Segment(text="Wind gusts up to 60 mph are expected.", start=segs[5].start, end=segs[5].end)
        total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
        out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, "weather"),
                              timeline._OVERLAY_SECONDS)
        self.assertFalse([o for o in out["overlays"] if str(o.get("template", "")).startswith("LIB_WX_")])

    def test_a_wind_line_never_gets_the_rain_map_and_the_other_way_round(self):
        # A wind line every 80 s: once the wind map is inside LOOK_GAP the rain
        # bands were the "fresh" forecast look - a radar titled WIND GUSTS.
        from unittest import mock
        from src import config
        for line, own, other in (("Wind gusts up to 60 mph will hit the coast tonight.", "LIB_WX_WIND_FLOW",
                                  "LIB_WX_RAIN_BANDS"),
                                 ("Heavy rain will soak the coast tonight.", "LIB_WX_RAIN_BANDS", "LIB_WX_WIND_FLOW")):
            for density in ("rich", "minimal"):
                segs, shots, scenes, brief = build(80)
                brief["kind"] = "weather"
                shots[0] = {"subject": "Boston", "overlay": {"type": "map", "text": "Boston", "locations": BOSTON}}
                for i in range(1, 80, 16):
                    segs[i] = Segment(text=line, start=segs[i].start, end=segs[i].end)
                    shots[i] = {"subject": "Boston"}
                total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
                with mock.patch.object(config, "GRAPHICS_DENSITY", density):
                    out = treatments.plan(segs, shots, scenes, FPS, total, brief,
                                          treatments.pack_for(brief, "weather"), timeline._OVERLAY_SECONDS)
                wx = [o for o in out["overlays"] if str(o.get("template", "")).startswith("LIB_WX_")]
                self.assertTrue(wx, (line, density))
                self.assertEqual({o["template"] for o in wx}, {own}, (line, density))
                for o in wx:
                    self.assertEqual(o["text"], {"LIB_WX_WIND_FLOW": "WIND GUSTS",
                                                 "LIB_WX_RAIN_BANDS": "HEAVY RAIN"}[o["template"]])
                self.assertFalse([o for o in wx if o["template"] == other])

    def test_a_storm_name_is_not_a_forecast(self):
        # "Nor'easter" named the storm, not a forecast: the count stays and no
        # wind map covers the line.
        texts = ["It sits just outside Boston."] + ["The storm kept moving east."] * 5
        texts[2] = "The nor'easter left 12,000 people without power in Massachusetts."
        for density in ("rich", "minimal"):
            out = weather_plan(texts, density, kind="news")["overlays"]
            self.assertFalse([o for o in out if str(o.get("template", "")).startswith("LIB_WX_")], density)
            self.assertTrue([o for o in out if o.get("value") == 12000.0], density)

    def test_the_line_keeps_its_figure_when_the_map_does_not_land(self):
        texts = ["It sits just outside Boston."] + ["The storm kept moving east."] * 5
        texts[2] = "Up to 12 inches of rain could fall by Friday."
        for density in ("rich", "minimal"):
            # The map lands: its legend stands for the rainfall, no separate counter.
            out = weather_plan(texts, density)["overlays"]
            self.assertEqual([o["template"] for o in out if str(o.get("template", "")).startswith("LIB_WX_")],
                             ["LIB_WX_RAIN_BANDS"], density)
            self.assertFalse([o for o in out if o.get("value") == 12.0], density)
            # No forecast look fits: the 12 inches still show.
            out = weather_plan(texts, density, no_forecast_looks=True)["overlays"]
            self.assertFalse([o for o in out if str(o.get("template", "")).startswith("LIB_WX_")], density)
            self.assertTrue([o for o in out if o.get("value") == 12.0], density)
        # A count on a wind line is not the map's to carry: it shows, the map follows.
        texts[2] = "Wind gusts up to 60 mph knocked out power to 12,000 people."
        out = weather_plan(texts, "rich")["overlays"]
        self.assertTrue([o for o in out if o.get("value") == 12000.0])


BOSTON = [{"label": "Boston, MA", "lat": 42.36, "lon": -71.06}]


def weather_plan(texts, density="rich", kind="weather", mapped=True, no_forecast_looks=False):
    """A plan of 6 s lines, the first one mapped (Boston), at a graphics density."""
    from unittest import mock
    from src import config
    segs = [Segment(text=t, start=i * 6.0, end=(i + 1) * 6.0) for i, t in enumerate(texts)]
    shots = [{"subject": "Boston"} for _ in texts]
    if mapped:
        shots[0] = {"subject": "Boston", "overlay": {"type": "map", "text": "Boston", "locations": BOSTON}}
    scenes = [{"id": f"s{i}", "startFrame": i * 180, "durationInFrames": 180,
               "media": {"type": "video", "url": f"https://x/{i}"}, "transition": "none", "motion": "none",
               "effect": "none"} for i in range(len(texts))]
    brief = {"kind": kind, "hookBeats": [], "sections": []}
    real_fits = treatments.look_fits

    def fits(tid, text):
        return not (no_forecast_looks and tid.startswith("LIB_WX_")) and real_fits(tid, text)
    with mock.patch.object(config, "GRAPHICS_DENSITY", density), mock.patch.object(treatments, "look_fits", fits):
        return treatments.plan(segs, shots, scenes, FPS, len(texts) * 180, brief, treatments.pack_for(brief, "weather"),
                               timeline._OVERLAY_SECONDS)


class PlacesMaps(unittest.TestCase):
    """A map look drawn from places renders nothing without them: never planned so."""

    @staticmethod
    def _needs_places(tid):
        t = templates.get(tid) or {}
        return t.get("category") == "MAPS" and "locations" in (t.get("props") or {})

    def test_three_places_with_values_never_get_an_empty_map(self):
        # "Denver 16 inches, Boulder 10, Aspen 8": a compare-values line with no
        # coordinates; the rotation used to hand it the choropleth (it returned null).
        for n in range(8):
            texts, shots, scenes = [], [], []
            segs = []
            for i in range(120):
                if i % 3 == 0:
                    t = (f"Denver saw {10 + (i + n) % 9} inches, Boulder {5 + n % 4} inches, "
                         f"and Aspen {1 + i % 4} inches of snow.")
                else:
                    t = ("The storm kept moving east.", "Crews worked all night.", "Residents waited for news.")[i % 3]
                segs.append(Segment(text=t, start=i * 5.0, end=(i + 1) * 5.0))
                shots.append({"subject": "Colorado"})
                scenes.append({"id": f"s{i}", "startFrame": i * 150, "durationInFrames": 150,
                               "media": {"type": "video", "url": f"https://x/{i}.mp4"}, "transition": "none",
                               "motion": "none", "effect": "none"})
            brief = {"kind": "news", "hookBeats": [], "sections": []}
            out = treatments.plan(segs, shots, scenes, FPS, 120 * 150, brief, treatments.pack_for(brief, "news"),
                                  timeline._OVERLAY_SECONDS)
            empty = [(o["startFrame"] / FPS, o["template"]) for o in out["overlays"]
                     if self._needs_places(o["template"]) and not o.get("locations")]
            self.assertFalse(empty, n)

    def test_full_screen_and_cue_picks_skip_maps_without_places(self):
        pack = treatments.pack_for({"kind": "news"}, "news")
        text = "Denver saw 16 inches, Boulder 10 inches, and Aspen 8 inches of snow."
        seg = Segment(text=text, start=0.0, end=5.0)
        # Every other compare-values look used already: the choropleth is the least used.
        counts = {t["id"]: 5 for t in templates.for_cue("compare-values", "news")}
        counts["LIB_MV_CHOROPLETH_LIFT"] = 0
        anim = treatments.animation_for(seg, {"subject": "Colorado"}, pack, None, counts=dict(counts))
        self.assertTrue(anim)
        self.assertFalse(self._needs_places(anim["template"]), anim["template"])
        tid = treatments._template_for_cue("compare-values", pack, set(), dict(counts), text=text)
        self.assertFalse(self._needs_places(tid), tid)
        # With places the map look is fine.
        tid = treatments._template_for_cue("compare-values", pack, set(), dict(counts), text=text,
                                           props={"locations": BOSTON})
        self.assertEqual(tid, "LIB_MV_CHOROPLETH_LIFT")
