"""
Real data graphics (src/realdata.py, src/datagraphics.py, the rd- looks, config.DATA_GRAPHICS): when the narration
states a measurable water or weather fact, the video charts the REAL numbers from the official source, the source
and the date of the data in its corner.

  * the connectors read the sources' real answers (tests/fixtures/realdata, recorded 2026-10-05 from data.usbr.gov
    RISE, api.waterdata.usgs.gov and waterservices.usgs.gov, usdmdataservices.unl.edu, NOAA NCEI Climate at a
    Glance and api.weather.gov; long daily records thinned to every 8th-16th row, the format untouched) and never
    raise: a 5xx is tried once more, a dead source or a passed deadline gives (None, why);
  * detection: a line's entity, metric, number and years, spoken numbers read as digits, the entity from context only
    when the number fits it; projections, thresholds, structures and "Colorado's farmers" are not measurements;
  * the check: the narration's number against the live one (a year said: that year's readings; a change: since the
    year said; a record: its rank), a disagreement flagged, the chart always the live value;
  * the planner: off changes nothing; on, a chart lands on the fact's first word (never early), one per
    DATA_GRAPHICS_GAP, none in the hook without a number, never stacked, the line's own number not drawn twice;
  * the wiring: the flag and its tunables overridable per job, the four looks registered "autoPick": false and drawn
    by the renderer, the TypeScript helpers through node.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import requests

from src import config, datagraphics as D, realdata as R, templates, timeline, treatments
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "realdata")
REMOTION = os.path.join(ROOT, "remotion")
LIB = os.path.join(REMOTION, "src", "components", "lib")
TODAY = datetime.date(2026, 10, 5)
FPS = 30
SECS = 5.0
PLAIN = "Plain words about the desert and the river here."


# --------------------------------------------------------------------------- the recorded sources
def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class Recorded:
    """realdata.http_get answered from the fixtures: (status, body); `fail` maps a host part to a status."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = dict(fail or {})

    def __call__(self, url, params=None, headers=None, timeout=12.0):
        params = params or {}
        self.calls.append((url, dict(params)))
        for part, status in self.fail.items():
            if part in url:
                if isinstance(status, Exception):
                    raise status
                return status, "<html>Service Unavailable</html>"
        name = None
        if "rise/api/result/download" in url:
            name = f"rise_{params.get('itemId')}.csv"
        elif "ogcapi" in url and "/daily/" in url:
            name = f"ogc_{str(params.get('monitoring_location_id', '')).replace('USGS-', '')}.json"
        elif "waterservices.usgs.gov/nwis/dv" in url:
            name = f"nwis_{params.get('sites')}.json"
        elif "usdmdataservices" in url:
            name = f"usdm_{params.get('aoi')}.json"
        elif "climate-at-a-glance" in url:
            m = re.search(r"/(national|statewide)/time-series/(\d+)/(\w+)/(\d+)/(\d+)/", url)
            name = f"ncei_{m.group(1)}_{m.group(2)}_{m.group(3)}_{m.group(4)}_{m.group(5)}.json" if m else None
        elif "api.weather.gov/alerts" in url:
            name = f"nws_{params.get('area')}.json"
        if name and os.path.isfile(os.path.join(FIXTURES, name)):
            return 200, _read(name)
        return 404, "not found"


class OnRecord(unittest.TestCase):
    """Every test here reads the recorded answers, on the day they were recorded."""

    def setUp(self):
        self.http = Recorded()
        patches = [mock.patch.object(R, "http_get", self.http), mock.patch.object(R, "today", lambda: TODAY)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fetch(self, **q):
        s, why = R.fetch(q, deadline=None)
        self.assertIsNotNone(s, why)
        return s


# --------------------------------------------------------------------------- connectors
class Connectors(OnRecord):
    def test_rise_csv_is_read_as_dated_values(self):
        rows = R.parse_rise_csv(_read("rise_6123.csv"))
        self.assertGreater(len(rows), 50)
        self.assertEqual(rows[-1], ("2026-10-03", 1037.93))
        self.assertEqual(rows, sorted(rows))
        with self.assertRaises(R.FetchError):
            R.parse_rise_csv("<html>maintenance</html>")

    def test_reservoir_level_monthly_ending_on_the_real_reading(self):
        s = self.fetch(source="usbr", entity="lake-mead", metric="elevation", since=2001)
        self.assertEqual(s["key"], "usbr|lake-mead|elevation|2001")
        self.assertEqual(s["latest"], {"date": "2026-10-03", "value": 1037.93})
        self.assertEqual((s["source"], s["unit"], s["asOf"], s["asOfLabel"]), ("USBR", "FT", "2026-10-03", "OCT 3, 2026"))
        dates = [p[0] for p in s["points"]]
        self.assertEqual(dates, sorted(dates))
        self.assertTrue(all(d.endswith("-15") for d in dates[:-1]))       # monthly means, mid-month
        self.assertEqual(len({d[:7] for d in dates}), len(dates))          # one point a month, October's is the reading
        self.assertIn("itemId=6123", s["url"])
        self.assertEqual(s["extra"]["pools"]["dead pool"], 895.0)
        self.assertEqual(self.http.calls[0][1]["after"], "2001-01-01")

    def test_share_of_capacity_is_the_agencys_storage_over_its_capacity(self):
        s = self.fetch(source="usbr", entity="lake-powell", metric="percent_full", since=2001)
        # 5,194,250 af on Oct 3 over USBR's stated 23,314,000 af live capacity.
        self.assertAlmostEqual(s["latest"]["value"], 5194250 / 23314000 * 100, places=2)
        self.assertEqual(s["kicker"], "PERCENT OF LIVE CAPACITY")
        mead = self.fetch(source="usbr", entity="lake-mead", metric="percent_full", since=2001)
        self.assertEqual(mead["kicker"], "PERCENT OF CAPACITY")           # Lake Mead's is not called "live"
        st = self.fetch(source="usbr", entity="lake-powell", metric="storage", since=2001)
        self.assertAlmostEqual(st["latest"]["value"], 5.19425, places=3)
        self.assertEqual(st["unit"], "MAF")
        s, why = R.fetch({"source": "usbr", "entity": "elephant-butte", "metric": "percent_full", "since": 2001})
        self.assertIsNone(s)                                               # no stated capacity: no share
        self.assertIn("capacity", why)

    def test_river_flow_from_the_ogc_api(self):
        s = self.fetch(source="usgs", entity="colorado-lees-ferry", metric="flow", since=2016)
        self.assertEqual(s["latest"], {"date": "2026-10-03", "value": 6580.0})
        self.assertEqual((s["title"], s["unit"], s["source"]), ("COLORADO RIVER", "CFS", "USGS"))
        self.assertEqual(s["kicker"], "FLOW AT LEES FERRY, AZ · CUBIC FEET PER SECOND")
        self.assertEqual(s["url"], "https://waterdata.usgs.gov/monitoring-location/USGS-09380000/")
        self.assertTrue(all("ogcapi" in u for u, _p in self.http.calls))

    def test_water_services_stands_in_when_the_ogc_api_is_down(self):
        self.http.fail["ogcapi"] = 503
        s = self.fetch(source="usgs", entity="colorado-lees-ferry", metric="flow", since=2026)
        self.assertEqual(s["latest"]["date"], "2026-10-03")
        self.assertTrue(any("waterservices" in u for u, _p in self.http.calls))
        self.assertEqual(sum("ogcapi" in u for u, _p in self.http.calls), 2)    # tried once more, then the fallback

    def test_great_salt_lake_level(self):
        s = self.fetch(source="usgs", entity="great-salt-lake", metric="elevation", since=2001)
        self.assertEqual(s["latest"], {"date": "2026-10-03", "value": 4189.7})
        lows = [p for p in s["points"] if p[0].startswith("2022")]
        self.assertLess(min(v for _d, v in lows), 4189.5)                  # the 2022 record low is in the record

    def test_drought_share_with_its_categories(self):
        s = self.fetch(source="usdm", entity="conus", level="D1", since=2000)
        self.assertEqual(s["key"], "usdm|conus|drought-D1|2000")
        self.assertEqual(s["latest"], {"date": "2026-09-29", "value": 59.38})
        self.assertEqual(s["extra"]["categories"], {"D0": 78.36, "D1": 59.38, "D2": 33.78, "D3": 11.53, "D4": 1.59})
        self.assertEqual(s["source"], "U.S. DROUGHT MONITOR")
        self.assertEqual(s["asOfLabel"], "SEP 29, 2026")
        az = self.fetch(source="usdm", entity="state:AZ", level="D2", since=2000)
        self.assertEqual(az["latest"]["value"], 24.11)                    # severe or worse
        self.assertEqual(self.http.calls[-1][1]["aoi"], "04")              # the state's FIPS code
        total = self.fetch(source="usdm", entity="us", level="D1", since=2026)
        self.assertEqual(total["latest"]["value"], 49.78)                 # all states and Puerto Rico, not the lower 48

    def test_temperature_record_with_ranks(self):
        s = self.fetch(source="ncei", entity="us", metric="temperature", period="year", since=1895)
        self.assertEqual(s["extra"]["ranks"]["2024"], 1)
        self.assertEqual(s["extra"]["years"], 131)
        self.assertEqual(s["asOfLabel"], "THROUGH 2025")
        self.assertEqual(s["title"], "CONTIGUOUS U.S.")
        self.assertEqual(s["unit"], "°F")
        tx = self.fetch(source="ncei", entity="state:TX", metric="temperature", period="summer", since=1895)
        self.assertEqual(tx["extra"]["ranks"]["2011"], 1)
        self.assertIn("SUMMER", tx["kicker"])
        self.assertIn("/statewide/time-series/41/tavg/3/8/", self.http.calls[-1][0])

    def test_alerts_in_effect_by_kind(self):
        s = self.fetch(source="nws", entity="state:TX", metric="alerts", event="Coastal Flood Advisory")
        self.assertEqual(s["latest"]["value"], 1.0)
        s = self.fetch(source="nws", entity="state:TX", metric="alerts", event="Flood Warning")
        self.assertEqual(s["latest"]["value"], 0.0)

    def test_query_key_is_the_series_key(self):
        for q in ({"source": "usbr", "entity": "lake-mead", "metric": "elevation", "since": 2001},
                  {"source": "usgs", "entity": "colorado-lees-ferry", "metric": "flow", "since": 2016},
                  {"source": "usdm", "entity": "conus", "metric": "drought", "level": "D1", "since": 2000},
                  {"source": "ncei", "entity": "us", "metric": "temperature", "period": "year", "since": 1895}):
            self.assertEqual(R.query_key(q), self.fetch(**q)["key"])

    def test_a_long_series_is_thinned_keeping_both_ends(self):
        pts = [[f"2000-01-{(i % 28) + 1:02d}", float(i)] for i in range(1000)]
        out = R._thin(pts, 100)
        self.assertLessEqual(len(out), 101)
        self.assertEqual((out[0], out[-1]), (pts[0], pts[-1]))


class NeverFails(OnRecord):
    def test_a_dead_source_is_none_with_its_reason(self):
        self.http.fail["data.usbr.gov"] = 500
        s, why = R.fetch({"source": "usbr", "entity": "lake-mead", "metric": "elevation", "since": 2001})
        self.assertIsNone(s)
        self.assertEqual(why, "HTTP 500")
        self.assertEqual(len(self.http.calls), 2)                         # one more try on a 5xx, no more

    def test_a_refusal_is_not_retried(self):
        self.http.fail["usdmdataservices"] = 404
        s, why = R.fetch({"source": "usdm", "entity": "conus", "level": "D1", "since": 2000})
        self.assertIsNone(s)
        self.assertEqual(len(self.http.calls), 1)

    def test_a_dropped_connection_and_nonsense(self):
        self.http.fail["climate-at-a-glance"] = requests.ConnectionError("reset")
        s, why = R.fetch({"source": "ncei", "entity": "us", "metric": "temperature", "period": "year"})
        self.assertIsNone(s)
        self.assertIn("ConnectionError", why)
        with mock.patch.object(R, "http_get", lambda *a, **k: (200, "{not json")):
            self.assertIsNone(R.fetch({"source": "usdm", "entity": "conus", "level": "D1"})[0])
        with mock.patch.object(R, "http_get", lambda *a, **k: (200, "[]")):
            self.assertIsNone(R.fetch({"source": "usdm", "entity": "conus", "level": "D1"})[0])
        self.assertIsNone(R.fetch({"source": "nobody", "entity": "x"})[0])
        self.assertIsNone(R.fetch({"source": "usbr", "entity": "no-such-lake", "metric": "elevation"})[0])

    def test_a_passed_deadline_asks_nothing(self):
        s, why = R.fetch({"source": "usbr", "entity": "lake-mead", "metric": "elevation", "since": 2001},
                         deadline=0.0 + 1.0)
        self.assertIsNone(s)
        self.assertEqual(self.http.calls, [])

    def test_the_store_fills_in_the_background_and_reports(self):
        store = D.start(["Lake Powell is just 22 percent full.", "Lake Mead has fallen to 1,038 feet.",
                         "Nearly 60 percent of the lower 48 is in drought.", "If Lake Mead drops below 950 feet..."],
                        {"places": ["Lake Powell"]}, budget=30)
        self.assertTrue(store.wait(30))
        rep = store.report()
        self.assertEqual(rep["queries"], 3)
        self.assertEqual(set(rep["fetched"]), {"usbr|lake-powell|percent_full|2001", "usbr|lake-mead|elevation|2001",
                                               "usdm|conus|drought-D1|2000"})
        self.assertEqual(rep["failed"], {})
        self.assertEqual(store.why("nothing"), "not asked for")

    def test_failures_are_recorded_not_raised(self):
        self.http.fail["ogcapi"] = 500
        self.http.fail["waterservices"] = 500
        store = D.Store()
        D.fetch_all(store, [{"source": "usgs", "entity": "colorado-lees-ferry", "metric": "flow", "since": 2016}], 20)
        self.assertTrue(store.done.is_set())
        self.assertIn("usgs|colorado-lees-ferry|flow|2016", store.errors)
        self.assertIn("Water Services", store.why("usgs|colorado-lees-ferry|flow|2016"))


# --------------------------------------------------------------------------- detection
def one(text, **kw):
    got = D.detect_line(text, 0, now=2026, **kw)
    return got[0] if got else None


class Detection(unittest.TestCase):
    def test_the_owners_examples(self):
        f = one("Lake Powell is just twenty-two percent full.")
        self.assertEqual((f["entity"], f["metric"], f["said"], f["look"]), ("lake-powell", "percent_full", 22.0, "gauge"))
        self.assertEqual(f["query"], {"source": "usbr", "entity": "lake-powell", "metric": "percent_full", "since": 2001})
        self.assertEqual(f["keys"], ["Powell", "22"])
        f = one("Lake Mead has fallen to about one thousand thirty-eight feet above sea level.")
        self.assertEqual((f["entity"], f["metric"], f["said"], f["bound"]), ("lake-mead", "elevation", 1038.0, "~"))
        f = one("Nearly sixty percent of the lower forty-eight is in drought.")
        self.assertEqual((f["entity"], f["metric"], f["said"], f["level"], f["look"]), ("conus", "drought", 60.0, "D1", "line"))
        self.assertEqual(f["keys"], ["60", "drought"])
        f = one("The Colorado River at Lees Ferry is running at just 6,600 cubic feet per second.")
        self.assertEqual((f["entity"], f["metric"], f["said"]), ("colorado-lees-ferry", "flow", 6600.0))
        f = one("Two thousand twenty-four was the hottest year on record in the United States.")
        self.assertEqual((f["entity"], f["metric"], f["record"], f["year"], f["period"]), ("us", "temperature", True, 2024, "year"))
        self.assertIsNone(f["said"])

    def test_more_facts(self):
        f = one("About 24 percent of Arizona is in severe drought or worse.")
        self.assertEqual((f["entity"], f["level"], f["look"], f["said"]), ("state:AZ", "D2", "bars", 24.0))
        f = one("Drought now covers 63 percent of Arizona.")
        self.assertEqual((f["entity"], f["said"]), ("state:AZ", 63.0))
        f = one("Nearly half of the country is in drought right now.")
        self.assertEqual((f["entity"], f["said"], f["bound"]), ("us", 50.0, "~"))
        f = one("Texas just had its hottest summer on record.")
        self.assertEqual((f["entity"], f["period"]), ("state:TX", "summer"))
        f = one("The Great Salt Lake dropped to a record low of 4,188.5 feet in 2022.")
        self.assertEqual((f["entity"], f["metric"], f["said"], f["year"]), ("great-salt-lake", "elevation", 4188.5, 2022))
        f = one("Lake Powell holds just 5.2 million acre-feet of water.")
        self.assertEqual((f["metric"], f["said"], f["look"]), ("storage", 5.2, "number"))
        f = one("Right now, 12 flood warnings are in effect across Texas.")
        self.assertEqual((f["metric"], f["query"]["event"], f["said"]), ("alerts", "Flood Warning", 12.0))

    def test_years_and_changes(self):
        f = one("Lake Mead has dropped more than 150 feet since 2000.")
        self.assertEqual((f["change"], f["compare"], f["query"]["since"]), (-150.0, 2000, 1999))
        f = one("In 2022, Lake Mead fell to 1,040 feet, its lowest level since it was filled.")
        self.assertEqual((f["year"], f["said"]), (2022, 1040.0))
        f = one("Lake Powell has lost a third of its water over the last two decades and is now 22 percent full.")
        self.assertEqual((f["compare"], f["query"]["since"]), (2006, 2001))

    def test_not_measurements(self):
        for text in ("The white bathtub ring on the canyon walls now stands more than 150 feet tall.",
                     "Another dry winter could push the lake toward dead pool.",
                     "If Lake Mead drops below 950 feet, Hoover Dam stops making power.",
                     "Lake Mead's third intake sits at 860 feet.",
                     "Dead pool at Lake Mead is 895 feet.",
                     "65 percent of Colorado's farmers say the drought hurt them.",
                     "The Colorado River supplies 40 million people.",
                     "By 2030 Lake Powell is projected to be 15 percent full.",
                     "Hoover Dam is 726 feet tall.",
                     "The canyon here is 500 feet deep.",
                     "Snowpack is at 60 percent of normal."):
            self.assertEqual(D.detect_line(text, 0, now=2026), [], text)
        # A pool named after the level, with a relation, is a comparison: the number is still the level.
        f = one("Lake Powell has fallen to about 3,518 feet, just above minimum power pool.")
        self.assertEqual((f["entity"], f["said"]), ("lake-powell", 3518.0))

    def test_the_entity_from_context_only_when_the_number_fits(self):
        facts = D.detect(["Lake Powell sits behind Glen Canyon Dam.", "It is now a quarter full."], now=2026)
        self.assertEqual([(f["line"], f["entity"], f["said"]) for f in facts], [(1, "lake-powell", 25.0)])
        self.assertFalse(facts[0]["named"])
        # A level said with no name is the reservoir whose levels it fits, from the lines before or the brief.
        facts = D.detect(["Lake Powell and Lake Mead are both shrinking.", "The lake has fallen to 1,040 feet."], now=2026)
        self.assertEqual([f["entity"] for f in facts], ["lake-mead"])
        facts = D.detect(["The water keeps falling.", "The lake has fallen to 3,520 feet."],
                         {"places": ["Lake Powell", "Page, Arizona"]}, now=2026)
        self.assertEqual([f["entity"] for f in facts], ["lake-powell"])
        # Two reservoirs it could be: none.
        self.assertEqual(D.detect(["It is now 25 percent full."], {"places": ["Lake Powell", "Lake Mead"]}, now=2026), [])
        # A state said as "the state" is the one the brief names.
        facts = D.detect(["Here 63 percent of the state is in drought."], {"places": ["Phoenix, Arizona"]}, now=2026)
        self.assertEqual([f["entity"] for f in facts], ["state:AZ"])

    def test_a_state_is_not_a_river_and_back(self):
        self.assertIsNone(one("The Colorado River Compact divides 15 million acre-feet."))
        f = one("Nearly 80 percent of Colorado is in drought.")
        self.assertEqual(f["entity"], "state:CO")
        self.assertIsNone(one("Washington D.C. saw 30 percent of the region in drought."))

    def test_abbreviations_months_and_pronouns(self):
        self.assertEqual(one("Nearly half of the U.S. is in drought.")["entity"], "us")      # one sentence, not two
        self.assertEqual(one("About 60 percent of the contiguous U.S. is in drought.")["entity"], "conus")
        self.assertEqual(one("The U.S. Drought Monitor says 63 percent of Arizona is in drought.")["entity"], "state:AZ")
        f = one("In May 2022, Lake Mead fell to 1,040 feet.")                                # May the month
        self.assertEqual((f["entity"], f["year"]), ("lake-mead", 2022))
        self.assertIsNone(one("Lake Mead may soon drop to 1,000 feet."))                      # may the modal
        self.assertEqual(one("It hit 1,040 ft. in July 2022 at Lake Mead.")["said"], 1040.0)
        self.assertIsNone(one("Tell us 60 percent of what you think about drought."))         # "us" is not the U.S.

    def test_one_fact_per_entity_and_metric_in_a_line(self):
        got = D.detect_line("Lake Powell is 22 percent full, and Lake Powell was 25 percent full last spring.", 0, now=2026)
        self.assertEqual(len(got), 1)


# --------------------------------------------------------------------------- the check
def series(points, unit="%", decimals=1, **extra):
    return {"points": [list(p) for p in points], "latest": {"date": points[-1][0], "value": points[-1][1]},
            "unit": unit, "decimals": decimals, "source": "USBR", "sourceName": "U.S. Bureau of Reclamation",
            "asOf": points[-1][0], "asOfLabel": "OCT 3, 2026", "url": "https://x", "extra": dict(extra), "step": "month"}


class Checks(unittest.TestCase):
    def test_agrees_within_tolerance_and_flags_otherwise(self):
        s = series([("2025-10-15", 29.1), ("2026-10-03", 22.28)])
        self.assertTrue(D.check({"metric": "percent_full", "said": 22.0, "saidText": "22%", "bound": "="}, s)["agrees"])
        bad = D.check({"metric": "percent_full", "said": 40.0, "saidText": "40% full", "bound": "="}, s)
        self.assertFalse(bad["agrees"])
        self.assertIn("40% full", bad["note"])
        self.assertIn("22.3%", bad["note"])
        self.assertTrue(D.check({"metric": "percent_full", "said": 20.0, "saidText": "more than 20%", "bound": ">"}, s)["agrees"])
        self.assertFalse(D.check({"metric": "percent_full", "said": 30.0, "saidText": "more than 30%", "bound": ">"}, s)["agrees"])
        self.assertTrue(D.check({"metric": "percent_full", "said": 25.0, "saidText": "about 25%", "bound": "~"}, s)["agrees"])

    def test_a_year_said_is_checked_against_that_years_readings(self):
        s = series([("2022-06-15", 1045.0), ("2022-07-15", 1041.5), ("2023-06-15", 1062.0), ("2026-10-03", 1037.93)],
                   unit="FT")
        self.assertTrue(D.check({"metric": "elevation", "said": 1040.0, "saidText": "1,040 feet", "year": 2022}, s)["agrees"])
        self.assertFalse(D.check({"metric": "elevation", "said": 1100.0, "saidText": "1,100 feet", "year": 2022}, s)["agrees"])

    def test_a_change_since_a_year(self):
        s = series([("2000-01-15", 1210.0), ("2026-10-03", 1037.93)], unit="FT")
        got = D.check({"metric": "elevation", "change": -150.0, "compare": 2000, "saidText": "more than 150 feet"}, s)
        self.assertFalse(got["agrees"])                     # it fell 172 ft: "150" is off by more than 10%
        got = D.check({"metric": "elevation", "change": -170.0, "compare": 2000, "saidText": "170 feet"}, s)
        self.assertTrue(got["agrees"])
        self.assertIsNone(D.check({"metric": "elevation", "change": -170.0, "saidText": "170 feet"}, s)["agrees"])

    def test_a_record_by_its_rank(self):
        s = series([("2012-07-01", 55.3), ("2024-07-01", 55.48), ("2025-07-01", 54.62)], unit="°F",
                   ranks={"2024": 1, "2012": 2, "2025": 4}, years=131)
        self.assertTrue(D.check({"metric": "temperature", "record": True, "word": "hottest", "year": 2024}, s)["agrees"])
        no = D.check({"metric": "temperature", "record": True, "word": "hottest", "year": 2025}, s)
        self.assertFalse(no["agrees"])
        self.assertEqual(no["liveText"], "#4 of 131 years")
        self.assertIsNone(D.check({"metric": "temperature", "record": True, "word": "hottest", "year": None}, s)["agrees"])

    def test_only_shown_disagreements_become_warnings(self):
        rep = {"items": [{"line": 4, "status": "shown", "check": {"agrees": False, "note": "the narration says 40%"}},
                         {"line": 9, "status": "shown", "check": {"agrees": True}},
                         {"line": 12, "status": "skipped: x", "check": {"agrees": False, "note": "n"}}]}
        got = D.warnings_for(rep)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("Data check, line 5: the narration says 40%"))


# --------------------------------------------------------------------------- the document
class Documents(OnRecord):
    def build(self, text, look=None):
        f = one(text)
        s = self.fetch(**f["query"])
        return D.build(f, s, look or f["look"])

    def test_a_level_over_25_years_with_its_change_and_pools(self):
        props, data = self.build("Lake Powell has fallen to about 3,518 feet, just above minimum power pool.")
        self.assertEqual((data["look"], data["unit"], data["title"], data["source"]), ("line", "FT", "LAKE POWELL", "USBR"))
        self.assertEqual(data["latest"]["label"], "OCT 3, 2026")
        self.assertIn({"label": "MINIMUM POWER POOL", "value": 3490.0}, data["refs"])
        self.assertTrue(data["delta"]["text"].startswith("−"))
        self.assertIn("SINCE", data["delta"]["text"])
        self.assertNotIn("url", data)                                     # media walkers never take it for a file
        self.assertTrue(data["sourceUrl"].startswith("https://data.usbr.gov/"))
        self.assertEqual(props["subtitle"], "SOURCE: USBR · DATA AS OF OCT 3, 2026")
        self.assertEqual((props["value"], props["suffix"]), (3518.79, "FT"))

    def test_a_gauge_with_last_years_month_and_the_storage(self):
        _p, data = self.build("Lake Powell is just 22 percent full.")
        self.assertEqual(data["range"], [0, 100])
        self.assertEqual(data["compare"]["label"], "OCT 2025")
        self.assertEqual(data["storage"], {"value": 5.19, "capacity": 23.31, "unit": "MAF"})
        self.assertIn("SINCE OCT 2025", data["delta"]["text"])

    def test_drought_bars_this_week(self):
        _p, data = self.build("About 24 percent of Arizona is in severe drought or worse.")
        self.assertEqual([b["label"] for b in data["bars"]], ["IN DROUGHT", "SEVERE OR WORSE", "EXTREME OR WORSE", "EXCEPTIONAL"])
        self.assertEqual([b["highlight"] for b in data["bars"]], [False, True, False, False])
        self.assertEqual(data["bars"][1]["value"], 24.11)
        self.assertIn("WEEK OF SEP 29, 2026", data["kicker"])

    def test_a_record_marks_its_year(self):
        _p, data = self.build("2024 was the hottest year on record in the United States.")
        self.assertEqual(data["record"]["label"], "2024")
        self.assertEqual((data["record"]["rank"], data["record"]["of"], data["record"]["word"]), (1, 131, "WARMEST"))
        self.assertEqual(data["delta"]["text"], "2024: WARMEST OF 131 YEARS")
        self.assertEqual(data["asOfLabel"], "THROUGH 2025")

    def test_a_year_said_is_the_point_compared(self):
        _p, data = self.build("The Great Salt Lake dropped to a record low of 4,188.5 feet in 2022.")
        self.assertEqual(data["compare"]["date"][:4], "2022")
        self.assertEqual(data["compare"]["value"], min(v for d, v in data["points"] if d.startswith("2022")))


# --------------------------------------------------------------------------- the planner
def _seg(i, text, secs=SECS):
    words = [Word(text=w, start=i * secs + j * 0.3, end=i * secs + j * 0.3 + 0.25) for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * secs, end=(i + 1) * secs, words=words)


def _plan(lines, brief=None, secs=SECS):
    segs = [_seg(i, t, secs) for i, t in enumerate(lines)]
    n = int(secs * FPS)
    scenes = [{"id": f"s{i}", "startFrame": i * n, "durationInFrames": n,
               "media": {"type": "video", "url": f"https://x/{i}.mp4", "thumbnail": f"https://x/{i}.jpg"},
               "transition": "none", "motion": "none", "effect": "none"} for i in range(len(lines))]
    brief = brief or {"kind": "explainer", "hookBeats": [], "sections": []}
    shots = [{"subject": "water"} for _ in lines]
    return treatments.plan(segs, shots, scenes, FPS, len(lines) * n, brief, treatments.pack_for(brief, "documentary"),
                           timeline._OVERLAY_SECONDS)


def charts(plan):
    return [o for o in plan["overlays"] if o.get("data")]


POWELL = "Lake Powell is just twenty-two percent full."
MEAD = "Downstream, Lake Mead has fallen to about 1,038 feet above sea level."
DROUGHT = "Nearly sixty percent of the lower forty-eight is in drought."


class ThePlanner(OnRecord):
    def setUp(self):
        super().setUp()
        self.store = D.Store()
        D.fetch_all(self.store, D.queries(D.detect([POWELL, MEAD, DROUGHT,
                                                    "2024 was the hottest year on record in the United States."])), 30)
        cm = D.use(self.store)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_flag_is_off_by_default_and_overridable(self):
        self.assertFalse(config.DATA_GRAPHICS)
        import handler
        for key in ("DATA_GRAPHICS", "DATA_GRAPHICS_GAP", "DATA_GRAPHICS_HOOK_SECONDS", "DATA_GRAPHICS_SECONDS",
                    "DATA_GRAPHICS_WAIT"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
        prev = handler._apply_config({"DATA_GRAPHICS": "true", "DATA_GRAPHICS_GAP": "45"})
        try:
            self.assertTrue(config.DATA_GRAPHICS)
            self.assertEqual(config.DATA_GRAPHICS_GAP, 45.0)
        finally:
            handler._restore_config(prev)
        self.assertFalse(config.DATA_GRAPHICS)

    def test_flag_off_changes_nothing(self):
        lines = [PLAIN] * 4 + [POWELL] + [PLAIN] * 9 + [MEAD] + [PLAIN] * 4
        with mock.patch.object(config, "DATA_GRAPHICS", False):
            off_with_data = _plan(lines)
        with D.use(None), mock.patch.object(config, "DATA_GRAPHICS", False):
            off_without = _plan(lines)
        dump = lambda p: json.dumps(p, sort_keys=True, default=str)  # noqa: E731
        self.assertEqual(dump(off_with_data), dump(off_without))
        self.assertEqual(charts(off_with_data), [])
        self.assertNotIn("dataGraphics", off_with_data)
        # On, a script that states no fact is planned exactly as with the flag off.
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plain_on = _plan([PLAIN] * 12)
        with mock.patch.object(config, "DATA_GRAPHICS", False):
            plain_off = _plan([PLAIN] * 12)
        self.assertEqual(dump(plain_on), dump(plain_off))

    def test_a_chart_lands_on_the_facts_first_word(self):
        lines = [PLAIN] * 4 + [POWELL] + [PLAIN] * 4
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan(lines)
        (ov,) = charts(plan)
        self.assertEqual((ov["template"], ov["type"], ov["variant"]), ("LIB_RD_GAUGE", "motion", "rd-gauge"))
        word = 4 * SECS + 1 * 0.3                                          # "Powell"
        start = ov["startFrame"] / FPS
        self.assertGreaterEqual(start, word - treatments.PRE_ROLL_FRAMES / FPS - 1e-6)    # never early
        self.assertLess(start, word + 0.2)
        self.assertGreaterEqual(ov["durationInFrames"] / FPS, 4.0 - 1e-6)  # its animation's least time
        self.assertLessEqual(ov["durationInFrames"] / FPS, treatments.TALKING_MAX + 1e-6)
        self.assertEqual(ov["backdrop"], "blur")
        self.assertEqual(ov["data"]["latest"]["value"], 22.28)
        self.assertEqual(ov["subtitle"], "SOURCE: USBR · DATA AS OF OCT 3, 2026")
        rep = plan["dataGraphics"]
        self.assertEqual((rep["facts"], rep["shown"], rep["disagree"]), (1, 1, 0))
        self.assertEqual(rep["items"][0]["status"], "shown")
        self.assertTrue(rep["items"][0]["check"]["agrees"])
        total = len(lines) * int(SECS * FPS)
        for i, o in enumerate(plan["overlays"]):
            timeline._validate_overlay(o, i, total)

    def test_the_figure_never_lands_before_its_number_is_said(self):
        long_line = ("Downstream, Lake Mead, which supplies Las Vegas and Phoenix with water, has fallen to about "
                     "1,038 feet.")
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan([PLAIN] * 4 + [long_line] + [PLAIN] * 4, secs=8.0)
        (ov,) = charts(plan)
        number = 4 * 8.0 + long_line.split().index("1,038") * 0.3
        mead = 4 * 8.0 + 2 * 0.3
        start = ov["startFrame"] / FPS
        hit = templates.get(ov["template"])["defaults"]["sfxAt"] / 30.0
        self.assertGreater(start, mead)                                   # not on "Mead": its figure would land early
        self.assertGreaterEqual(start + hit, number - 1e-6)               # the figure lands on or after "1,038"
        self.assertLess(start + hit, number + 1.0)
        # Said close together ("Powell ... twenty-two"), the chart comes in on the first word of the fact.
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan([PLAIN] * 4 + [POWELL] + [PLAIN] * 4)
        (ov,) = charts(plan)
        self.assertAlmostEqual(ov["startFrame"] / FPS, 4 * SECS + 1 * 0.3 - treatments.PRE_ROLL_FRAMES / FPS, delta=0.04)

    def test_the_lines_own_number_is_not_drawn_as_well(self):
        lines = [PLAIN] * 4 + ["Lake Powell is just 22 percent full."] + [PLAIN] * 4
        with mock.patch.object(config, "DATA_GRAPHICS", False):
            before = _plan(lines)
        self.assertTrue([o for o in before["overlays"] if o.get("value") == 22.0])   # without it: a figure look
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan(lines)
        self.assertEqual([o for o in plan["overlays"] if not o.get("data") and o.get("value") == 22.0], [])

    def test_never_stacked_with_another_graphic(self):
        lines = ([PLAIN, "On September 29, 2026, officials met in Page, Arizona.", "Brad Udall said the river is dying.",
                  "The lake had 40,000 visitors that weekend.", POWELL, "On October 1, 2026, the gates opened.",
                  "Another 12 percent of the water went to Arizona."] + [PLAIN] * 6)
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan(lines)
        (ov,) = charts(plan)
        a, b = ov["startFrame"], ov["startFrame"] + ov["durationInFrames"]
        for o in plan["overlays"]:
            if o is ov:
                continue
            s, e = o["startFrame"], o["startFrame"] + o["durationInFrames"]
            self.assertFalse(s < b and a < e, (o.get("template"), s, e, a, b))

    def test_one_per_gap_the_strongest_first(self):
        lines = [PLAIN] * 4 + [POWELL] + [PLAIN] * 2 + [MEAD] + [PLAIN] * 4
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan(lines)
        self.assertEqual(len(charts(plan)), 1)
        items = {i["line"]: i["status"] for i in plan["dataGraphics"]["items"]}
        self.assertEqual(items[4], "shown")
        self.assertEqual(items[7], f"skipped: another data graphic within {config.DATA_GRAPHICS_GAP:g} s")
        with mock.patch.object(config, "DATA_GRAPHICS", True), mock.patch.object(config, "DATA_GRAPHICS_GAP", 10.0):
            self.assertEqual(len(charts(_plan(lines))), 2)

    def test_the_hook_needs_its_number(self):
        record = "2024 was the hottest year on record in the United States."
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            early = _plan([record] + [PLAIN] * 5)
            late = _plan([PLAIN] * 4 + [record] + [PLAIN] * 4)
            said = _plan([POWELL] + [PLAIN] * 5)
        self.assertEqual(charts(early), [])
        self.assertIn("the line says no number", early["dataGraphics"]["items"][0]["status"])
        self.assertEqual([o["template"] for o in charts(late)], ["LIB_RD_LINE"])
        self.assertEqual(charts(late)[0]["data"]["record"]["label"], "2024")
        self.assertEqual(len(charts(said)), 1)                            # the hook may state its number

    def test_a_number_the_data_does_not_bear_out_is_flagged_not_corrected(self):
        lines = [PLAIN] * 4 + ["Lake Powell is just forty percent full."] + [PLAIN] * 4
        with mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan(lines)
        (ov,) = charts(plan)
        self.assertEqual(ov["data"]["latest"]["value"], 22.28)            # the live value is what shows
        item = plan["dataGraphics"]["items"][0]
        self.assertFalse(item["check"]["agrees"])
        self.assertEqual(plan["dataGraphics"]["disagree"], 1)
        (warning,) = D.warnings_for(plan["dataGraphics"])
        self.assertIn("line 5", warning)
        self.assertIn("40% full", warning)

    def test_no_data_no_chart(self):
        with D.use(D.Store()), mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan([PLAIN] * 4 + [POWELL] + [PLAIN] * 4)
        self.assertEqual(charts(plan), [])
        self.assertTrue(plan["dataGraphics"]["items"][0]["status"].startswith("no data"))
        with D.use(None), mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan([PLAIN] * 4 + [POWELL] + [PLAIN] * 4)
        self.assertEqual(plan["dataGraphics"]["items"][0]["status"], "no data: nothing was fetched")

    def test_a_brand_kit_without_the_looks_gets_none(self):
        others = [t["id"] for t in templates.all_templates() if not t["id"].startswith("LIB_RD_")]
        with templates.only(others), mock.patch.object(config, "DATA_GRAPHICS", True):
            plan = _plan([PLAIN] * 4 + [POWELL] + [PLAIN] * 4)
        self.assertEqual(charts(plan), [])
        self.assertEqual(plan["dataGraphics"]["items"][0]["status"], "skipped: its look is not allowed in this video")

    def test_the_next_chart_takes_another_look(self):
        lines = [PLAIN] * 4 + [MEAD] + [PLAIN] * 12 + [DROUGHT] + [PLAIN] * 3
        with mock.patch.object(config, "DATA_GRAPHICS", True), mock.patch.object(config, "DATA_GRAPHICS_GAP", 30.0):
            plan = _plan(lines)
        self.assertEqual([o["data"]["look"] for o in charts(plan)], ["line", "number"])


# --------------------------------------------------------------------------- wiring
class Wiring(unittest.TestCase):
    LOOK_IDS = ("LIB_RD_LINE", "LIB_RD_NUMBER", "LIB_RD_BARS", "LIB_RD_GAUGE")

    def test_registered_but_never_picked_on_their_own(self):
        for tid in self.LOOK_IDS:
            t = templates.get(tid)
            self.assertIsNotNone(t, tid)
            self.assertFalse(templates.auto_pick(t), tid)
            self.assertEqual((t["category"], t["kind"], t["component"]), ("CHARTS", "card", "motion"), tid)
            self.assertTrue(t["defaults"]["sounds"], tid)
            self.assertEqual(t["defaults"]["soundTiming"], "look", tid)
            self.assertGreaterEqual(t["defaults"]["leastSeconds"], 4.0, tid)
            self.assertLess(t["defaults"]["sfxAt"] / 30.0, t["defaults"]["leastSeconds"], tid)
            for p in ("text", "label", "subtitle", "value", "suffix"):
                self.assertIn(p, t["props"], tid)
        self.assertEqual(templates.for_cue("data"), [])                  # no other path finds them
        self.assertEqual(set(D.LOOKS.values()), set(self.LOOK_IDS))

    def test_the_renderer_draws_them(self):
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        with open(os.path.join(LIB, "LibRealData.tsx"), encoding="utf-8") as fh:
            lib = fh.read()
        with open(os.path.join(REMOTION, "src", "types.ts"), encoding="utf-8") as fh:
            types = fh.read()
        for variant in ("rd-line", "rd-number", "rd-bars", "rd-gauge"):
            self.assertIn(f'"{variant}"', index)
            self.assertIn(f'"{variant}": guard(', lib)
        self.assertNotIn("Math.random", lib)
        self.assertIn("data?: DataDoc", types)
        self.assertIn("SourceLine", lib)                                  # the source tag's own line in the corner

    def test_the_sounds_land_where_the_looks_do(self):
        with open(os.path.join(LIB, "LibRealData.tsx"), encoding="utf-8") as fh:
            lib = fh.read()
        for tid, const in (("LIB_RD_LINE", "LINE"), ("LIB_RD_NUMBER", "NUM"), ("LIB_RD_BARS", "BARS"),
                           ("LIB_RD_GAUGE", "GAUGE")):
            m = re.search(r"const " + const + r" = \{[^}]*land: (\d+)", lib)
            self.assertIsNotNone(m, const)
            self.assertEqual(int(m.group(1)), templates.get(tid)["defaults"]["sfxAt"], tid)


# --------------------------------------------------------------------------- the TypeScript helpers
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import * as F from "@FORMAT@";
const doc: any = {points: [["2026-10-03", 1037.93], ["2001-01-15", 1196.4], ["bad", 1], ["2010-05-15", "x"]],
  decimals: 1, asOfLabel: "OCT 3, 2026"};
process.stdout.write(JSON.stringify({
  series: F.seriesOf(doc).map((p) => [p.date, p.v]),
  fmt: [F.fmtVal(1037.93, 1), F.fmtVal(6580, 0), F.fmtVal(22.284, 1), F.fmtVal(NaN, 1)],
  value: [F.valueText(22.28, 1, "%"), F.valueText(1037.93, 1, "ft"), F.valueText(55.48, 1, "°F")],
  years: [F.yearTicks(Date.UTC(2001, 0, 15), Date.UTC(2026, 9, 3)), F.yearTicks(Date.UTC(1895, 6, 1), Date.UTC(2025, 6, 1))],
  period: [F.periodLabel("2001-01-15"), F.periodLabel("2024-07-01", "year"), F.periodLabel("nope")],
  note: [F.asOfNote(doc), F.asOfNote({asOfLabel: "THROUGH 2025"} as any), F.asOfNote(null)],
  data: [F.dataOf({data: doc} as any) === doc, F.dataOf({} as any), F.decimalsOf({decimals: 7} as any)],
}));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Formatting(unittest.TestCase):
    def test_the_helpers(self):
        node, esbuild = _node()
        tmp = tempfile.mkdtemp()
        try:
            entry = os.path.join(tmp, "harness.ts")
            with open(entry, "w", encoding="utf-8") as fh:
                fh.write(HARNESS.replace("@FORMAT@", os.path.join(LIB, "rdFormat").replace("\\", "/")))
            bundle = os.path.join(tmp, "harness.cjs")
            subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={bundle}",
                            "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
            got = json.loads(subprocess.run([node, bundle], capture_output=True, text=True, encoding="utf-8",
                                            timeout=120, check=True).stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(got["series"], [["2001-01-15", 1196.4], ["2026-10-03", 1037.93]])
        self.assertEqual(got["fmt"], ["1,037.9", "6,580", "22.3", ""])
        self.assertEqual(got["value"], ["22.3%", "1,037.9 FT", "55.5°F"])
        self.assertEqual(got["years"], [[2005, 2010, 2015, 2020, 2025], [1900, 1925, 1950, 1975, 2000, 2025]])
        self.assertEqual(got["period"], ["JAN 2001", "2024", ""])
        self.assertEqual(got["note"], ["DATA AS OF OCT 3, 2026", "DATA THROUGH 2025", ""])
        self.assertEqual(got["data"], [True, None, 3])


if __name__ == "__main__":
    unittest.main()
