"""
Real data: the official numbers behind a narration's water and weather facts, from free public sources, for the
real data graphics (src/datagraphics.py; the owner, 2026-10-05: "accurate, up to date, impossible for competitors
to fake").

  USBR RISE           a reservoir's elevation, storage and share of its live capacity (Lake Mead, Lake Powell,
                      Flaming Gorge ...), daily since the dam closed              data.usbr.gov/rise
  USGS                a river's flow, a lake's level (the Colorado at Lees Ferry, the Great Salt Lake ...), daily:
                      the OGC API first (api.waterdata.usgs.gov), the legacy Water Services behind it
  U.S. Drought Monitor  the share of an area in drought, by category, week by week since 2000
                      usdmdataservices.unl.edu
  NOAA NCEI           Climate at a Glance: national and state average temperature and precipitation since 1895
  NOAA NWS            the alerts in effect for a state right now (api.weather.gov)

None needs a key. Every answer is a Series - a plain dict the planner and the renderer read:

    {"key", "entity", "entityName", "metric", "title", "kicker", "unit", "decimals", "step",
     "points": [[iso date, value], ...]  (oldest first; the last one is the latest reading itself),
     "latest": {"date", "value"}, "source" (the short name on screen), "sourceName", "url" (the official data),
     "asOf" (the date of the latest reading), "asOfLabel" ("OCT 3, 2026"), "extra": {...}}

Nothing is computed that the source does not publish, except (a) a long daily record shown as monthly means
(and a weekly one as the first map of each month) with the latest reading kept as it is, and (b) a reservoir's
share of capacity: the agency's own storage over the live capacity the same agency states (CAPACITY below).

fetch() never raises: a source that is slow, down or answers nonsense gives None and the reason (the caller
keeps it for the job report). Every request is time-boxed (DATA_FETCH_SECONDS, and the caller's deadline over
all of them); a 5xx or a dropped connection is tried once more while time remains. `http_get` is the one network
call - the tests replace it with recorded answers (tests/fixtures/realdata).
"""
import csv
import datetime as _dt
import io
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config

USER_AGENT = "ThumbGenius-video-worker/1.0 (real data graphics; contact via thumbgenius)"
RISE = "https://data.usbr.gov"
OGC = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
NWIS = "https://waterservices.usgs.gov/nwis"
USDM = "https://usdmdataservices.unl.edu/api"
NCEI = "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance"
NWS = "https://api.weather.gov"

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MAX_POINTS = 360                 # a chart never carries more (25 years of monthly means is 300)


class FetchError(Exception):
    """A source that could not answer (the message is what the job report says)."""


# ------------------------------------------------------------------ the catalog
# Live capacity in acre-feet, as the agency itself states it (a reservoir's share is its storage over this):
#   USBR Lower Colorado daily report, usbr.gov/lc/region/g4000/hourly/levels.html (read 2026-10-05):
#     Lake Powell "MAX. STORAGE 23314000 AF" at 3,700.0 ft (its end-of-August 5.14 maf is "22 percent of live
#     capacity" on usbr.gov/uc/water/crsp/cs/gcd.html: 5,143,450 / 23,314,000 = 22.06%), Flaming Gorge 3,749,000
#     (6,040 ft), Navajo 1,696,000 (6,085 ft), Blue Mesa 827,472 (7,519.4 ft); Lake Mead "AVAILABLE CAPACITY
#     26120000" at 1,219.6 ft, Lake Mohave 1,873,648 (647 ft), Lake Havasu 570,253 (450 ft).
#   USBR Central Valley Project facilities, usbr.gov/mp/cvp/facilities_canals.html: Shasta 4,552,000, Folsom 977,000.
# Pool levels (ft) are USBR's own: Lake Powell full pool 3,700, minimum power pool 3,490, dead pool 3,370; Lake Mead
# minimum power pool 950, dead pool 895. `range_ft` is only a sanity window for reading a narration's number as a
# level (never drawn). RISE ids: data.usbr.gov/rise/api/catalog-item/<id> ("Daily Lake/Reservoir Elevation-ft" and
# "Storage-af" of the "Water Operations Monitoring" records).
RESERVOIRS: Dict[str, Dict[str, Any]] = {
    "lake-mead": {"name": "Lake Mead", "names": ["Lake Mead"], "elevation": 6123, "storage": 6124,
                  "capacity": 26_120_000, "range_ft": (850.0, 1240.0),
                  "pools": {"minimum power pool": 950.0, "dead pool": 895.0}},
    "lake-powell": {"name": "Lake Powell", "names": ["Lake Powell"], "elevation": 508, "storage": 509,
                    "capacity": 23_314_000, "live": True, "range_ft": (3300.0, 3710.0),
                    "pools": {"full pool": 3700.0, "minimum power pool": 3490.0, "dead pool": 3370.0}},
    "flaming-gorge": {"name": "Flaming Gorge Reservoir", "names": ["Flaming Gorge Reservoir", "Flaming Gorge"],
                      "elevation": 341, "storage": 337, "capacity": 3_749_000, "range_ft": (5900.0, 6045.0),
                      "pools": {"full pool": 6040.0}},
    "lake-mohave": {"name": "Lake Mohave", "names": ["Lake Mohave"], "elevation": 6133, "storage": 6134,
                    "capacity": 1_873_648, "range_ft": (560.0, 650.0), "pools": {}},
    "lake-havasu": {"name": "Lake Havasu", "names": ["Lake Havasu"], "elevation": 6128, "storage": 6129,
                    "capacity": 570_253, "range_ft": (430.0, 452.0), "pools": {}},
    "navajo-reservoir": {"name": "Navajo Reservoir", "names": ["Navajo Reservoir", "Navajo Lake"], "elevation": 612,
                         "storage": 613, "capacity": 1_696_000, "range_ft": (5900.0, 6090.0),
                         "pools": {"full pool": 6085.0}},
    "blue-mesa": {"name": "Blue Mesa Reservoir", "names": ["Blue Mesa Reservoir", "Blue Mesa"], "elevation": 78,
                  "storage": 76, "capacity": 827_472, "range_ft": (7300.0, 7522.0), "pools": {"full pool": 7519.4}},
    "elephant-butte": {"name": "Elephant Butte Reservoir",
                       "names": ["Elephant Butte Reservoir", "Elephant Butte Lake", "Elephant Butte"],
                       "elevation": 332, "storage": 329, "capacity": None, "range_ft": (4250.0, 4410.0), "pools": {}},
    "shasta-lake": {"name": "Shasta Lake", "names": ["Shasta Lake", "Lake Shasta"], "elevation": 10863,
                    "storage": 10864, "capacity": 4_552_000, "range_ft": (800.0, 1070.0), "pools": {}},
    "folsom-lake": {"name": "Folsom Lake", "names": ["Folsom Lake"], "elevation": 10775, "storage": 10774,
                    "capacity": 977_000, "range_ft": (300.0, 470.0), "pools": {}},
}

# USGS stations: the official name, the river or lake, what is measured there (parameter codes: 00060 discharge,
# 62614 lake elevation NGVD29). A river said with no place is read at its first station ("the Colorado River" is
# Lees Ferry, the Colorado River Compact's own point); a place named in the line picks its station.
GAUGES: Dict[str, Dict[str, Any]] = {
    "colorado-lees-ferry": {"site": "09380000", "name": "Colorado River at Lees Ferry, AZ", "water": "Colorado River",
                            "names": ["Colorado River"], "places": ["Lees Ferry"], "params": {"flow": "00060"}},
    "colorado-grand-canyon": {"site": "09402500", "name": "Colorado River near Grand Canyon, AZ",
                              "water": "Colorado River", "names": ["Colorado River"], "places": ["Grand Canyon"],
                              "params": {"flow": "00060"}},
    "rio-grande-albuquerque": {"site": "08330000", "name": "Rio Grande at Albuquerque, NM", "water": "Rio Grande",
                               "names": ["Rio Grande"], "places": ["Albuquerque"], "params": {"flow": "00060"}},
    "mississippi-st-louis": {"site": "07010000", "name": "Mississippi River at St. Louis, MO",
                             "water": "Mississippi River", "names": ["Mississippi River"], "places": ["St. Louis"],
                             "params": {"flow": "00060"}},
    "mississippi-memphis": {"site": "07032000", "name": "Mississippi River at Memphis, TN",
                            "water": "Mississippi River", "names": ["Mississippi River"], "places": ["Memphis"],
                            "params": {"flow": "00060"}},
    "missouri-hermann": {"site": "06934500", "name": "Missouri River at Hermann, MO", "water": "Missouri River",
                         "names": ["Missouri River"], "places": ["Hermann"], "params": {"flow": "00060"}},
    "columbia-the-dalles": {"site": "14105700", "name": "Columbia River at The Dalles, OR", "water": "Columbia River",
                            "names": ["Columbia River"], "places": ["The Dalles"], "params": {"flow": "00060"}},
    "yellowstone-corwin-springs": {"site": "06191500", "name": "Yellowstone River at Corwin Springs, MT",
                                   "water": "Yellowstone River", "names": ["Yellowstone River"],
                                   "places": ["Corwin Springs", "Gardiner"], "params": {"flow": "00060"}},
    "ohio-louisville": {"site": "03294500", "name": "Ohio River at Louisville, KY", "water": "Ohio River",
                        "names": ["Ohio River"], "places": ["Louisville"], "params": {"flow": "00060"}},
    "great-salt-lake": {"site": "10010000", "name": "Great Salt Lake at Saltair Boat Harbor, UT",
                        "water": "Great Salt Lake", "names": ["Great Salt Lake"], "places": [],
                        "params": {"elevation": "62614"}, "range_ft": (4180.0, 4215.0)},
}

# States: USPS code -> (name, FIPS for the Drought Monitor, NOAA NCEI's own state number for Climate at a Glance).
STATES: Dict[str, Tuple[str, str, Optional[int]]] = {
    "AL": ("Alabama", "01", 1), "AK": ("Alaska", "02", 50), "AZ": ("Arizona", "04", 2), "AR": ("Arkansas", "05", 3),
    "CA": ("California", "06", 4), "CO": ("Colorado", "08", 5), "CT": ("Connecticut", "09", 6),
    "DE": ("Delaware", "10", 7), "FL": ("Florida", "12", 8), "GA": ("Georgia", "13", 9), "HI": ("Hawaii", "15", None),
    "ID": ("Idaho", "16", 10), "IL": ("Illinois", "17", 11), "IN": ("Indiana", "18", 12), "IA": ("Iowa", "19", 13),
    "KS": ("Kansas", "20", 14), "KY": ("Kentucky", "21", 15), "LA": ("Louisiana", "22", 16), "ME": ("Maine", "23", 17),
    "MD": ("Maryland", "24", 18), "MA": ("Massachusetts", "25", 19), "MI": ("Michigan", "26", 20),
    "MN": ("Minnesota", "27", 21), "MS": ("Mississippi", "28", 22), "MO": ("Missouri", "29", 23),
    "MT": ("Montana", "30", 24), "NE": ("Nebraska", "31", 25), "NV": ("Nevada", "32", 26),
    "NH": ("New Hampshire", "33", 27), "NJ": ("New Jersey", "34", 28), "NM": ("New Mexico", "35", 29),
    "NY": ("New York", "36", 30), "NC": ("North Carolina", "37", 31), "ND": ("North Dakota", "38", 32),
    "OH": ("Ohio", "39", 33), "OK": ("Oklahoma", "40", 34), "OR": ("Oregon", "41", 35),
    "PA": ("Pennsylvania", "42", 36), "RI": ("Rhode Island", "44", 37), "SC": ("South Carolina", "45", 38),
    "SD": ("South Dakota", "46", 39), "TN": ("Tennessee", "47", 40), "TX": ("Texas", "48", 41), "UT": ("Utah", "49", 42),
    "VT": ("Vermont", "50", 43), "VA": ("Virginia", "51", 44), "WA": ("Washington", "53", 45),
    "WV": ("West Virginia", "54", 46), "WI": ("Wisconsin", "55", 47), "WY": ("Wyoming", "56", 48),
}
# The nation as each source has it: the Drought Monitor's "total" (50 states and Puerto Rico) and "conus" (the
# lower 48); NCEI's national series is the contiguous U.S. (110).
AREAS: Dict[str, Dict[str, Any]] = {
    "us": {"name": "United States", "usdm": ("USStatistics", "total"), "ncei": ("national", 110),
           "ncei_name": "Contiguous U.S."},
    "conus": {"name": "Lower 48 States", "usdm": ("USStatistics", "conus"), "ncei": ("national", 110),
              "ncei_name": "Contiguous U.S."},
}
for _code, (_name, _fips, _ncei) in STATES.items():
    AREAS["state:" + _code] = {"name": _name, "usdm": ("StateStatistics", _fips),
                               "ncei": ("statewide", _ncei) if _ncei else None, "ncei_name": _name, "state": _code}

# Drought Monitor categories as the share AT OR ABOVE each (its "traditional" statistics are cumulative).
DROUGHT_LEVELS = {"D0": "ABNORMALLY DRY OR WORSE", "D1": "IN DROUGHT", "D2": "SEVERE DROUGHT OR WORSE",
                  "D3": "EXTREME DROUGHT OR WORSE", "D4": "EXCEPTIONAL DROUGHT"}
# Climate at a Glance periods: (months in the window, the month it ends in).
PERIODS = {"year": (12, 12), "summer": (3, 8), "winter": (3, 2), "spring": (3, 5), "fall": (3, 11)}
for _i, _m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                         "october", "november", "december"]):
    PERIODS[_m] = (1, _i + 1)

# The metrics, as a chart titles them, with their unit on screen and their decimals.
METRICS = {
    "elevation": {"kicker": "ELEVATION · FEET ABOVE SEA LEVEL", "unit": "FT", "decimals": 1},
    "percent_full": {"kicker": "PERCENT OF LIVE CAPACITY", "unit": "%", "decimals": 1},
    "storage": {"kicker": "WATER IN STORAGE · MILLION ACRE-FEET", "unit": "MAF", "decimals": 2},
    "flow": {"kicker": "RIVER FLOW · CUBIC FEET PER SECOND", "unit": "CFS", "decimals": 0},
    "drought": {"kicker": "SHARE OF AREA IN DROUGHT", "unit": "%", "decimals": 1},
    "temperature": {"kicker": "AVERAGE TEMPERATURE · °F", "unit": "°F", "decimals": 1},
    "precip": {"kicker": "PRECIPITATION · INCHES", "unit": "IN", "decimals": 2},
    "alerts": {"kicker": "ALERTS IN EFFECT NOW", "unit": "", "decimals": 0},
}


def today() -> _dt.date:
    return _dt.date.today()


# ------------------------------------------------------------------ dates
def date_label(iso: str, step: str = "day") -> str:
    """ "2026-10-03" -> "OCT 3, 2026" (a day), "SEP 2026" (a month), "2025" (a year)."""
    try:
        d = _dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)[:4]
    if step == "year":
        return str(d.year)
    if step == "month":
        return f"{MONTHS[d.month - 1]} {d.year}"
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def _iso(d: _dt.date) -> str:
    return d.isoformat()


# ------------------------------------------------------------------ network
def http_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: float = 12.0) -> Tuple[int, str]:
    """The one network call: (HTTP status, body). Tests replace it with recorded answers."""
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=timeout)
    return r.status_code, r.text


def _get(url: str, params: Optional[dict] = None, deadline: Optional[float] = None,
         headers: Optional[dict] = None) -> str:
    """A body, or FetchError: each try within DATA_FETCH_SECONDS and the deadline, one more on a 5xx or a drop."""
    last = ""
    for attempt in range(2):
        left = (deadline - time.time()) if deadline else float(config.DATA_FETCH_SECONDS)
        if left < 1.0:
            raise FetchError(last or "out of time")
        try:
            status, body = http_get(url, params, headers, timeout=min(float(config.DATA_FETCH_SECONDS), left))
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {str(e)[:120]}"
            continue
        if status == 200:
            return body
        last = f"HTTP {status}"
        if status < 500:
            break
    raise FetchError(last or "no answer")


# ------------------------------------------------------------------ shaping
def _monthly(points: List[Tuple[str, float]]) -> List[List[Any]]:
    """Daily readings as monthly means dated mid-month, the latest reading kept as it is (its own month's mean
    left out, so the line ends on the real number)."""
    if not points:
        return []
    buckets: Dict[str, List[float]] = {}
    order: List[str] = []
    for d, v in points:
        ym = d[:7]
        if ym not in buckets:
            buckets[ym] = []
            order.append(ym)
        buckets[ym].append(v)
    last_date, last_value = points[-1]
    out = [[f"{ym}-15", sum(buckets[ym]) / len(buckets[ym])] for ym in order if ym != last_date[:7]]
    out.append([last_date, last_value])
    return out


def _first_of_month(points: List[Tuple[str, float]]) -> List[List[Any]]:
    """Weekly readings as the first of each month, the latest kept."""
    out: List[List[Any]] = []
    seen = set()
    for d, v in points:
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append([d, v])
    if points and (not out or out[-1][0] != points[-1][0]):
        out.append([points[-1][0], points[-1][1]])
    return out


def _thin(points: List[List[Any]], limit: int = MAX_POINTS) -> List[List[Any]]:
    """At most `limit` points, evenly kept, the first and the last always."""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / float(limit - 1)
    keep = sorted({int(round(i * step)) for i in range(limit)} | {0, len(points) - 1})
    return [points[i] for i in keep]


def _round(points: List[List[Any]], decimals: int) -> List[List[Any]]:
    d = max(0, min(4, decimals + 1))
    return [[p[0], round(float(p[1]), d)] for p in points]


def _series(key: str, entity: str, name: str, metric: str, points: List[List[Any]], *, step: str, source: str,
            source_name: str, url: str, title: str = "", kicker: str = "", unit: str = "", decimals: Optional[int] = None,
            latest_step: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    m = METRICS.get(metric, {})
    dec = m.get("decimals", 1) if decimals is None else decimals
    pts = _round(_thin(points), dec)
    last = pts[-1] if pts else [None, None]
    as_of = str(last[0] or "")
    return {
        "key": key, "entity": entity, "entityName": name, "metric": metric,
        "title": (title or name).upper(), "kicker": kicker or m.get("kicker", ""), "unit": unit or m.get("unit", ""),
        "decimals": dec, "step": step, "points": pts,
        "latest": {"date": as_of, "value": last[1]},
        "source": source, "sourceName": source_name, "url": url,
        "asOf": as_of, "asOfLabel": date_label(as_of, latest_step or ("day" if step in ("month", "day") else step)),
        "fetchedAt": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "extra": dict(extra or {}),
    }


# ------------------------------------------------------------------ USBR RISE
def parse_rise_csv(text: str) -> List[Tuple[str, float]]:
    """RISE's download CSV ("#SERIES DATA#", then Location, Parameter, Result, Units, ..., Datetime (UTC)): (date, value)."""
    rows = list(csv.reader(io.StringIO(text or "")))
    head = next((i for i, r in enumerate(rows) if len(r) > 6 and r[0] == "Location" and r[2] == "Result"), None)
    if head is None:
        raise FetchError("RISE answered without its series table")
    at = rows[head].index("Datetime (UTC)") if "Datetime (UTC)" in rows[head] else 6
    out: Dict[str, float] = {}
    for r in rows[head + 1:]:
        if len(r) <= at or not r[2]:
            continue
        try:
            out[r[at][:10]] = float(r[2])
        except ValueError:
            continue
    return sorted(out.items())


def usbr(entity: str, metric: str, since: int, deadline: Optional[float] = None) -> dict:
    """A reservoir's elevation (ft), storage (million acre-feet) or share of live capacity (%), monthly since `since`."""
    r = RESERVOIRS[entity]
    if metric == "percent_full" and not r.get("capacity"):
        raise FetchError(f"no stated capacity for {r['name']}")
    item = r["storage"] if metric in ("percent_full", "storage") else r["elevation"]
    params = {"type": "csv", "itemId": item, "after": f"{since}-01-01", "before": _iso(today() + _dt.timedelta(days=1)),
              "filename": "series", "order": "ASC"}
    body = _get(f"{RISE}/rise/api/result/download", params, deadline)
    raw = parse_rise_csv(body)
    if len(raw) < 2:
        raise FetchError(f"RISE item {item}: {len(raw)} readings")
    cap = float(r.get("capacity") or 0)
    if metric == "percent_full":
        raw = [(d, v / cap * 100.0) for d, v in raw]
    elif metric == "storage":
        raw = [(d, v / 1e6) for d, v in raw]
    url = (f"{RISE}/rise/api/result/download?type=csv&itemId={item}&after={since}-01-01&before={params['before']}"
           "&filename=series&order=ASC")
    extra: Dict[str, Any] = {"riseItem": item}
    if cap:
        extra["capacity"] = cap
    if metric == "elevation":
        extra["pools"] = dict(r.get("pools") or {})
    # The share as the agency words it: Lake Powell's is of its LIVE capacity (usbr.gov/uc ... gcd.html).
    kicker = ("PERCENT OF LIVE CAPACITY" if r.get("live") else "PERCENT OF CAPACITY") if metric == "percent_full" else ""
    return _series(f"usbr|{entity}|{metric}|{since}", entity, r["name"], metric, _monthly(raw), step="month",
                   source="USBR", source_name="U.S. Bureau of Reclamation", url=url, kicker=kicker, extra=extra)


# ------------------------------------------------------------------ USGS
def _ogc_daily(site: str, param: str, since: int, deadline: Optional[float]) -> List[Tuple[str, float]]:
    params = {"f": "json", "monitoring_location_id": f"USGS-{site}", "parameter_code": param, "statistic_id": "00003",
              "time": f"{since}-01-01/{_iso(today())}", "limit": 10000, "skipGeometry": "true",
              "properties": "time,value"}
    out: Dict[str, float] = {}
    url, page = f"{OGC}/daily/items", 0
    while url and page < 4:
        body = _get(url, params if page == 0 else None, deadline)
        page += 1
        try:
            d = json.loads(body)
        except ValueError:
            raise FetchError("USGS answered without JSON")
        for f in d.get("features") or []:
            p = f.get("properties") or {}
            try:
                out[str(p["time"])[:10]] = float(p["value"])
            except (KeyError, TypeError, ValueError):
                continue
        url = next((l.get("href") for l in d.get("links") or [] if l.get("rel") == "next"), None)
    return sorted(out.items())


def _nwis_daily(site: str, param: str, since: int, deadline: Optional[float]) -> List[Tuple[str, float]]:
    params = {"format": "json", "sites": site, "parameterCd": param, "statCd": "00003", "startDT": f"{since}-01-01",
              "endDT": _iso(today()), "siteStatus": "all"}
    body = _get(f"{NWIS}/dv/", params, deadline)
    try:
        d = json.loads(body)
    except ValueError:
        raise FetchError("USGS Water Services answered without JSON")
    out: Dict[str, float] = {}
    for ts in (d.get("value") or {}).get("timeSeries") or []:
        for block in ts.get("values") or []:
            for v in block.get("value") or []:
                try:
                    val = float(v["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                if val <= -999990:            # the service's "no value" marker
                    continue
                out[str(v.get("dateTime") or "")[:10]] = val
    return sorted(out.items())


def usgs(entity: str, metric: str, since: int, deadline: Optional[float] = None) -> dict:
    """A station's daily mean flow (cfs) or lake level (ft), monthly since `since`: the OGC API, else Water Services."""
    g = GAUGES[entity]
    param = (g.get("params") or {}).get(metric)
    if not param:
        raise FetchError(f"{g['name']} does not measure {metric}")
    raw: List[Tuple[str, float]] = []
    why = ""
    try:
        raw = _ogc_daily(g["site"], param, since, deadline)
    except FetchError as e:
        why = f"OGC API: {e}"
    if len(raw) < 2:
        try:
            raw = _nwis_daily(g["site"], param, since, deadline)
        except FetchError as e:
            raise FetchError(f"{why or 'OGC API: no readings'}; Water Services: {e}")
    if len(raw) < 2:
        raise FetchError(f"USGS {g['site']}: {len(raw)} readings")
    # A river's flow is the station's: "FLOW AT LEES FERRY, AZ" under the river's name.
    where = re.split(r"\s+(?:at|near|below|above)\s+", g["name"], maxsplit=1)
    kicker = (f"FLOW AT {where[1].upper()} · CUBIC FEET PER SECOND" if metric == "flow" and len(where) == 2 else "")
    return _series(f"usgs|{entity}|{metric}|{since}", entity, g["name"], metric, _monthly(raw), step="month",
                   source="USGS", source_name="U.S. Geological Survey",
                   url=f"https://waterdata.usgs.gov/monitoring-location/USGS-{g['site']}/",
                   title=g["water"], kicker=kicker, extra={"site": g["site"], "station": g["name"], "parameter": param})


# ------------------------------------------------------------------ U.S. Drought Monitor
def usdm(area: str, level: str, since: int, deadline: Optional[float] = None) -> dict:
    """The share of an area at or above a drought category (D0-D4), week by week since `since` (first map of each month)."""
    a = AREAS[area]
    kind, aoi = a["usdm"]
    level = level if level in DROUGHT_LEVELS else "D1"
    start = max(2000, int(since))
    params = {"aoi": aoi, "startdate": f"1/1/{start}", "enddate": f"{today().month}/{today().day}/{today().year}",
              "statisticsType": "1"}
    body = _get(f"{USDM}/{kind}/GetDroughtSeverityStatisticsByAreaPercent", params, deadline,
                headers={"Accept": "application/json"})
    try:
        rows = json.loads(body)
    except ValueError:
        raise FetchError("the Drought Monitor answered without JSON")
    if aoi in ("total", "conus"):
        want = "Total" if aoi == "total" else "CONUS"
        rows = [r for r in rows if str(r.get("areaOfInterest") or "").lower() == want.lower()] or rows
    weeks: Dict[str, dict] = {}
    for r in rows if isinstance(rows, list) else []:
        d = str(r.get("mapDate") or r.get("validStart") or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}$", d):
            weeks[d] = r
    if len(weeks) < 2:
        raise FetchError(f"Drought Monitor {aoi}: {len(weeks)} weekly maps")
    order = sorted(weeks)
    key = level.lower()
    raw = [(d, float(weeks[d].get(key) or 0.0)) for d in order]
    last = weeks[order[-1]]
    cats = {lv: round(float(last.get(lv.lower()) or 0.0), 2) for lv in DROUGHT_LEVELS}
    url = (f"{USDM}/{kind}/GetDroughtSeverityStatisticsByAreaPercent?aoi={aoi}&startdate=1/1/{start}"
           f"&enddate={params['enddate']}&statisticsType=1")
    return _series(f"usdm|{area}|drought-{level}|{start}", area, a["name"], "drought", _first_of_month(raw),
                   step="week", source="U.S. DROUGHT MONITOR", source_name="U.S. Drought Monitor (NDMC, USDA, NOAA)",
                   url=url, kicker=f"SHARE OF AREA · {DROUGHT_LEVELS[level]}", latest_step="day",
                   extra={"level": level, "categories": cats, "week": order[-1]})


# ------------------------------------------------------------------ NOAA NCEI Climate at a Glance
def ncei(area: str, metric: str, period: str, since: int, deadline: Optional[float] = None) -> dict:
    """A national or state average temperature (°F) or precipitation (in) for a period (a year, a season, a month),
    one value a year since `since`, with every year's rank (1 = the warmest / the wettest)."""
    a = AREAS[area]
    if not a.get("ncei"):
        raise FetchError(f"NCEI has no Climate at a Glance series for {a['name']}")
    scope, code = a["ncei"]
    months, end = PERIODS.get(period, PERIODS["year"])
    par = "tavg" if metric == "temperature" else "pcp"
    first = max(1895, int(since))
    path = f"{NCEI}/{scope}/time-series/{code}/{par}/{months}/{end}/{first}-{today().year}"
    body = _get(f"{path}/data.json", None, deadline, headers={"Accept": "application/json"})
    try:
        d = json.loads(body)
    except ValueError:
        raise FetchError("NCEI answered without JSON")
    data = d.get("data") or {}
    raw: List[Tuple[int, float]] = []
    for k, v in data.items():
        try:
            val = float(v["value"] if isinstance(v, dict) else v)
        except (KeyError, TypeError, ValueError):
            continue
        if val <= -99:                        # a missing year
            continue
        raw.append((int(str(k)[:4]), val))
    raw.sort()
    if len(raw) < 5:
        raise FetchError(f"NCEI {scope}/{code}: {len(raw)} years")
    by_value = sorted(raw, key=lambda p: -p[1])
    ranks = {y: i + 1 for i, (y, _v) in enumerate(by_value)}
    title = a.get("ncei_name") or a["name"]
    word = {"year": "", "summer": "SUMMER (JUN-AUG) ", "winter": "WINTER (DEC-FEB) ", "spring": "SPRING (MAR-MAY) ",
            "fall": "FALL (SEP-NOV) "}.get(period, f"{period.upper()} ")
    kicker = f"{word}AVERAGE TEMPERATURE · °F" if metric == "temperature" else f"{word}PRECIPITATION · INCHES"
    points = [[f"{y}-07-01", v] for y, v in raw]
    out = _series(f"ncei|{area}|{metric}|{period}|{first}", area, title, metric, points, step="year",
                  source="NOAA", source_name="NOAA National Centers for Environmental Information", url=path,
                  kicker=kicker, latest_step="year",
                  extra={"period": period, "ranks": {str(y): r for y, r in ranks.items()}, "years": len(raw),
                         "title": str((d.get("description") or {}).get("title") or "")})
    out["asOfLabel"] = f"THROUGH {raw[-1][0]}" if period == "year" else date_label(points[-1][0], "year")
    return out


# ------------------------------------------------------------------ NOAA NWS
def nws_alerts(state: str, event: str, deadline: Optional[float] = None) -> dict:
    """How many alerts of one kind ("Flood Warning") are in effect for a state right now."""
    a = AREAS["state:" + state]
    body = _get(f"{NWS}/alerts/active", {"area": state}, deadline, headers={"Accept": "application/geo+json"})
    try:
        d = json.loads(body)
    except ValueError:
        raise FetchError("the Weather Service answered without JSON")
    feats = [f.get("properties") or {} for f in d.get("features") or []]
    n = sum(1 for p in feats if str(p.get("event") or "").lower() == event.lower())
    stamp = str(d.get("updated") or _dt.datetime.now(_dt.timezone.utc).isoformat())
    out = _series(f"nws|state:{state}|alerts|{event.lower()}", "state:" + state, a["name"], "alerts",
                  [[stamp[:10], float(n)]], step="day", source="NWS", source_name="NOAA National Weather Service",
                  url=f"{NWS}/alerts/active?area={state}", kicker=f"{event.upper()}S IN EFFECT NOW", decimals=0,
                  extra={"event": event, "updated": stamp})
    return out


# ------------------------------------------------------------------ one door
def fetch(query: dict, deadline: Optional[float] = None) -> Tuple[Optional[dict], str]:
    """(Series, "") or (None, why). A query: {"source", "entity", "metric", "since", "level"?, "period"?, "event"?}.
    Never raises."""
    t0 = time.time()
    try:
        src = query.get("source")
        since = int(query.get("since") or today().year - 25)
        if src == "usbr":
            s = usbr(query["entity"], query["metric"], since, deadline)
        elif src == "usgs":
            s = usgs(query["entity"], query["metric"], since, deadline)
        elif src == "usdm":
            s = usdm(query["entity"], str(query.get("level") or "D1"), since, deadline)
        elif src == "ncei":
            s = ncei(query["entity"], query["metric"], str(query.get("period") or "year"), since, deadline)
        elif src == "nws":
            s = nws_alerts(str(query["entity"]).split(":", 1)[-1], str(query.get("event") or ""), deadline)
        else:
            return None, f"unknown source {src!r}"
        s["seconds"] = round(time.time() - t0, 2)
        return s, ""
    except FetchError as e:
        return None, str(e)[:200]
    except Exception as e:  # noqa: BLE001 - a chart is a nicety, never a failure
        return None, f"{type(e).__name__}: {str(e)[:160]}"


def query_key(query: dict) -> str:
    """The cache key of a query (the same text as the Series' own key)."""
    src = query.get("source")
    if src == "usdm":
        return f"usdm|{query['entity']}|drought-{query.get('level') or 'D1'}|{max(2000, int(query.get('since') or 2000))}"
    if src == "ncei":
        return (f"ncei|{query['entity']}|{query['metric']}|{query.get('period') or 'year'}|"
                f"{max(1895, int(query.get('since') or 1895))}")
    if src == "nws":
        return f"nws|{query['entity']}|alerts|{str(query.get('event') or '').lower()}"
    return f"{src}|{query['entity']}|{query['metric']}|{int(query.get('since') or today().year - 25)}"
