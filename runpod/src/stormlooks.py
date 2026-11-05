"""
The Dark Horizon looks on spoken words, written by themselves (the kit's hand-written <project>/looks_timeline.py).
Every look lands on the word that says it, stays about 3 s, and only one shows at a time. Numbers come from the script
only: a stat whose digits are not spoken right there is thrown away, whoever wrote it.

  red stats         "13 DAYS UP", on the number's word
  place tags        the first time each place of the story is said
  camcorder stamps  a spoken date, with the block's own label
  chapter titles    before a pause that ends a chapter (footage to black)
  typewriter date   on the hook, when the story's day is recent
  satellite pin     the story's main places, on USGS imagery (public domain, US only: elsewhere no pin map)

timeline(doc, ...) returns the dict stormpieces reads and doc.stormDesk.looks stores. The model is asked once to word the
stats; without it (or when it fails) the rules below still give every look.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

STAT_SECONDS = 2.8
PLACE_SECONDS = 4.4
STAMP_SECONDS = 4.4
MAP_SECONDS = 7.0
GAP_SECONDS = 0.5           # between two looks
STAT_EVERY = 9.0            # at least this far apart
PLACE_MAX = 6
STAMP_MAX = 4
TITLE_MAX = 3
MAP_MAX = 3
TITLE_LEAD = 2.6            # a chapter title starts this long before its pause ...
TITLE_BLACK = 0.7           # ... and the footage is black this long before it
SAT_ZOOM = 13
SAT_HALF = (1800, 1150)     # mosaic pixels each side of a pin: what L.map_pin shows at its widest (scale 0.62) and its lift

_NUM = re.compile(r"^[~+\-$]?\d[\d,]*(?:\.\d+)?(?:%|st|nd|rd|th)?[.,;:!?)]*$", re.I)
UNITS = {
    "feet": "FT", "foot": "FT", "ft": "FT", "acre-feet": "ACRE-FT", "acre-foot": "ACRE-FT", "inches": "IN", "inch": "IN",
    "miles": "MILES", "mile": "MILE", "mph": "MPH", "percent": "%", "%": "%", "cfs": "CFS", "days": "DAYS", "day": "DAY",
    "weeks": "WEEKS", "week": "WEEK", "months": "MONTHS", "years": "YEARS", "hours": "HOURS", "minutes": "MIN",
    "people": "PEOPLE", "homes": "HOMES", "houses": "HOMES", "cars": "CARS", "dead": "DEAD", "deaths": "DEAD", "killed": "KILLED",
    "missing": "MISSING", "injured": "INJURED", "rescued": "RESCUED", "evacuated": "EVACUATED", "billion": "BILLION",
    "million": "MILLION", "thousand": "THOUSAND", "trillion": "TRILLION", "degrees": "DEG", "turbines": "TURBINES",
    "gallons": "GALLONS", "dollars": "DOLLARS", "megawatts": "MW", "tons": "TONS", "towns": "TOWNS", "counties": "COUNTIES",
    "states": "STATES", "storms": "STORMS", "buildings": "BUILDINGS", "businesses": "BUSINESSES", "residents": "RESIDENTS",
}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
           "december")


def _clean(w: str) -> str:
    return re.sub(r"^[^\w$~+\-]+|[^\w%]+$", "", str(w or ""))


def _words(doc: dict) -> List[dict]:
    """Every spoken word on the video's clock, in order."""
    out = []
    for s in doc.get("scenes") or []:
        for w in s.get("words") or []:
            t = str(w.get("text") or "").strip()
            if t:
                out.append({"t": t, "s": float(w.get("start", 0.0)), "e": float(w.get("end", 0.0))})
    out.sort(key=lambda x: x["s"])
    return out


def stat_candidates(words: Sequence[dict]) -> List[dict]:
    """[{"at", "text", "i"}]: a spoken number with its unit: "13 days" -> "13 DAYS", "2 feet" -> "2 FT". Years and bare
    numbers no."""
    out = []
    for i, w in enumerate(words):
        tok = _clean(w["t"])
        if not _NUM.match(tok):
            continue
        num = tok.rstrip(".,;:!?)")
        nxt = _clean(words[i + 1]["t"]).lower() if i + 1 < len(words) else ""
        nxt2 = _clean(words[i + 2]["t"]).lower() if i + 2 < len(words) else ""
        if num.endswith("%"):
            out.append({"at": w["s"], "text": num.upper(), "i": i})
            continue
        unit = UNITS.get(nxt)
        extra = ""
        if unit in ("MILLION", "BILLION", "THOUSAND", "TRILLION") and UNITS.get(nxt2):
            extra = " " + UNITS[nxt2]
        if nxt == "acre" and nxt2.startswith("f"):
            unit = "ACRE-FT"
        if not unit:
            continue
        sep = "" if unit == "%" else " "
        out.append({"at": w["s"], "text": f"{num}{sep}{unit}{extra}".upper(), "i": i})
    return out


def _digits(text: str) -> List[str]:
    return re.findall(r"\d[\d,.]*\d|\d", str(text))


def stat_ok(text: str, words: Sequence[dict], at: float, window: float = 6.0) -> bool:
    """Its digits are said within `window` seconds of where it lands (the owner: numbers only from the script)."""
    text = str(text or "").strip()
    if not text or len(text) > 28 or len(text.split()) > 5:
        return False
    near = " ".join(w["t"] for w in words if abs(w["s"] - at) <= window)
    return all(d.rstrip(",.") in near for d in _digits(text))


_ASK = ("You word the big red on-screen numbers of a news video. For each candidate write the shortest honest words: the "
        "number exactly as spoken plus what it counts, 2-4 words, CAPITALS (\"13 DAYS UP\", \"1,039.21 FT\", \"UP ~38%\"). Use only "
        "the sentence you are given; never change a number; never add one. Set keep false for a number that is not a fact "
        "of the story (a chapter number, an aside). Answer JSON: {\"stats\":[{\"i\":<candidate>,\"text\":\"...\",\"keep\":true}]}")


def word_stats(cands: List[dict], words: Sequence[dict], ask: Optional[Callable]) -> List[dict]:
    """The model's wording, checked; the rules' wording for anything it refused or broke."""
    if not ask or not cands:
        return cands
    try:
        rows = []
        for k, c in enumerate(cands):
            near = " ".join(w["t"] for w in words if abs(w["s"] - c["at"]) <= 5.0)
            rows.append({"i": k, "number": c["text"], "sentence": near[:220]})
        raw = ask(_ASK, {"candidates": rows[:60]})
        got = raw if isinstance(raw, dict) else json.loads(raw)
        out = []
        told = {int(x["i"]): x for x in got.get("stats") or [] if isinstance(x, dict) and "i" in x}
        for k, c in enumerate(cands):
            x = told.get(k)
            if x is None:
                out.append(c)
            elif x.get("keep") is False:
                continue
            else:
                t = str(x.get("text") or "").upper().strip()
                out.append({**c, "text": t} if stat_ok(t, words, c["at"]) else c)
        return out
    except Exception as e:  # noqa: BLE001 - the rules' wording stands
        print(f"[looks] stats kept as spoken: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return cands


def find_phrase(words: Sequence[dict], phrase: str, after: float = 0.0) -> Optional[float]:
    """The start of the first run of words that says `phrase`."""
    want = re.sub(r"[^a-z0-9]", "", str(phrase).lower())
    if not want:
        return None
    for i, w in enumerate(words):
        if w["s"] < after:
            continue
        acc, j = "", i
        while j < len(words) and len(acc) < len(want):
            acc += re.sub(r"[^a-z0-9]", "", words[j]["t"].lower())
            j += 1
        if acc == want:
            return w["s"]
    return None


class Track:
    """One look at a time: a look takes its window only when nothing else holds it."""

    def __init__(self, blocked: Sequence[Tuple[float, float]] = ()):
        self.spans: List[Tuple[float, float]] = [(float(a), float(b)) for a, b in blocked]

    def free(self, a: float, b: float, gap: float = GAP_SECONDS) -> bool:
        return all(b + gap <= x or a - gap >= y for x, y in self.spans)

    def take(self, a: float, b: float) -> bool:
        if not self.free(a, b):
            return False
        self.spans.append((a, b))
        return True


def spoken_dates(words: Sequence[dict], today: datetime.date) -> List[Tuple[float, datetime.date]]:
    """Dates said in the narration: ("October 15", ...), the most recent past such day."""
    out = []
    for i in range(len(words) - 1):
        m = _clean(words[i]["t"]).lower()
        d = re.sub(r"(st|nd|rd|th)$", "", _clean(words[i + 1]["t"]).lower())
        if m in _MONTHS and d.isdigit() and 1 <= int(d) <= 31:
            try:
                x = datetime.date(today.year, _MONTHS.index(m) + 1, int(d))
                if x > today + datetime.timedelta(days=30):
                    x = x.replace(year=x.year - 1)
                out.append((words[i]["s"], x))
            except ValueError:
                pass
    return out


def merc(lat: float, lon: float, z: int) -> Tuple[float, float]:
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def fetch_mosaic(lat: float, lon: float, folder: str, z: int = SAT_ZOOM,
                 fetch: Optional[Callable[[str], bytes]] = None) -> Optional[dict]:
    """USGS National Map imagery (public domain) around a place -> {"file", "meta"}. None when most tiles are missing
    (outside the US, or the service is down): no pin map then, never a black one."""
    from PIL import Image
    import io
    import urllib.request

    def get(u: str) -> bytes:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "thumbgenius-worker"}), timeout=40) as r:
            return r.read()
    fetch = fetch or get
    cx, cy = merc(lat, lon, z)
    tx0, ty0 = int((cx - SAT_HALF[0]) // 256), int((cy - SAT_HALF[1]) // 256)
    tx1, ty1 = int((cx + SAT_HALF[0]) // 256), int((cy + SAT_HALF[1]) // 256)
    jobs = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]

    def one(j: Tuple[int, int]):
        tx, ty = j
        u = f"https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{ty}/{tx}"
        for _ in range(3):
            try:
                b = fetch(u)
                if b and len(b) > 1000:
                    return j, Image.open(io.BytesIO(b)).convert("RGB")
            except Exception:  # noqa: BLE001
                pass
        return j, None
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(one, jobs))
    if sum(1 for _, im in got if im is not None) < 0.9 * len(jobs):
        return None
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    mosaic = Image.new("RGB", (W, H))
    for (tx, ty), im in got:
        if im is not None:
            mosaic.paste(im, ((tx - tx0) * 256, (ty - ty0) * 256))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"sat_{z}_{tx0}_{ty0}_{W}x{H}.png")
    mosaic.save(path)
    return {"file": path, "meta": {"z": z, "ox": tx0 * 256, "oy": ty0 * 256, "w": W, "h": H}}


def timeline(doc: dict, blocks: Sequence[dict], pauses: Sequence[dict], brief: Optional[dict] = None,
             day: Optional[datetime.date] = None, work: str = "", ask: Optional[Callable] = None,
             lookup: Optional[Callable[[str], Any]] = None, mosaic: Optional[Callable[[float, float], Optional[dict]]] = None,
             today: Optional[datetime.date] = None, opts: Optional[dict] = None) -> dict:
    """{"type", "stats", "places", "stamps", "titles", "maps"}: video seconds, on the words."""
    opts = opts or {}
    words = _words(doc)
    total = int(doc.get("durationInFrames") or 0) / float(doc.get("fps") or 30)
    today = today or datetime.date.today()
    tl: Dict[str, Any] = {"type": [], "stats": [], "places": [], "stamps": [], "titles": [], "maps": []}
    if not words:
        return tl
    # Hook and pause clips keep their picture (a small caption only): no look over them.
    track = Track([(float(p["t0"]), float(p["t1"])) for p in pauses])
    hook_end = max([float(p["t1"]) for p in pauses if p.get("open")] or [0.0])
    places = [str(x) for x in ((brief or {}).get("places") or []) if x]

    # Titles first (they belong to their pause), then maps, then the short looks around them.
    if opts.get("titles", True) is not False:
        n = 0
        for p in pauses:
            if p.get("open") or n >= TITLE_MAX:
                continue
            b = next((b for b in reversed(list(blocks)) if float(b["start"]) < float(p["t0"]) - TITLE_LEAD), None)
            head = str((b or {}).get("headline") or " ".join((b or {}).get("lines") or [])).strip().upper()
            if not head or len(head) > 30 or float(p["t0"]) - float(b["start"]) < 15.0:
                continue
            a, end = float(p["t0"]) - TITLE_LEAD, float(p["t0"]) - 0.1
            if track.free(a, end, 0.0):         # (it ends right where its pause starts)
                track.spans.append((a, end))
                tl["titles"].append([round(a, 3), round(float(p["t0"]) - TITLE_BLACK, 3), round(end, 3), head,
                                     str((b or {}).get("tab") or "")[:24]])
                n += 1
    if opts.get("maps", True) is not False:
        made: Dict[str, dict] = {}
        for name in places:
            if len(tl["maps"]) >= MAP_MAX:
                break
            at = find_phrase(words, str(name).split(",")[0], hook_end)
            if at is None or at < hook_end + 8.0 or at + MAP_SECONDS > total - 5.0:
                continue
            a = max(hook_end + 0.5, at - 0.6)
            if any(abs(a - m["t0"]) < 45.0 for m in tl["maps"]) or not track.free(a, a + MAP_SECONDS):
                continue
            pl = None
            try:
                pl = (lookup or _lookup)(name)
            except Exception:  # noqa: BLE001
                pl = None
            if pl is None or str(getattr(pl, "country", "us") or "us").lower() not in ("us", "usa", ""):
                continue
            got = made.get(name) or (mosaic or (lambda la, lo: fetch_mosaic(la, lo, os.path.join(work or ".", "sdmaps"))))(pl.lat, pl.lon)
            if not got:
                continue
            made[name] = got
            track.take(a, a + MAP_SECONDS)
            tl["maps"].append({"t0": round(a, 3), "t1": round(a + MAP_SECONDS, 3), "pin": round(at, 3), "lat": pl.lat, "lon": pl.lon,
                               "label": str(name).split(",")[0][:30], "stat": "", "file": got["file"], "meta": got["meta"]})

    # Dates and places are rare: they choose before the stats. Each place once, the first time it is said.
    for name in places:
        if len(tl["places"]) >= PLACE_MAX:
            break
        short = str(name).split(",")[0]
        at = find_phrase(words, short, hook_end)
        if at is not None and at + PLACE_SECONDS < total - 1.0 and track.take(at, at + PLACE_SECONDS):
            tl["places"].append([round(at, 3), round(at + PLACE_SECONDS, 3), str(name).upper()[:34]])
    # A spoken date: the camcorder stamp, with its block's label.
    for at, d in spoken_dates(words, today)[:STAMP_MAX * 3]:
        if len(tl["stamps"]) >= STAMP_MAX or at < hook_end:
            continue
        b = next((b for b in reversed(list(blocks)) if float(b["start"]) <= at), None)
        label = str((b or {}).get("tab") or "").upper()[:18]
        if track.take(at, at + STAMP_SECONDS):
            tl["stamps"].append([round(at, 3), round(at + STAMP_SECONDS, 3), d.strftime("%m-%d-%Y"), label])
    # Stats on their number's word.
    cands = word_stats(stat_candidates(words), words, ask)
    last = -1e9
    for c in cands:
        a = float(c["at"])
        if a < hook_end or a - last < STAT_EVERY or a + STAT_SECONDS > total - 1.0 or not stat_ok(c["text"], words, a):
            continue
        if track.take(a, a + STAT_SECONDS):
            tl["stats"].append([round(a, 3), round(a + STAT_SECONDS, 3), c["text"]])
            last = a
    # The story's day, typed on the hook, when it is this story's own (an older hook leaves it out).
    if day and hook_end >= 3.0 and (today - day).days <= 14 and opts.get("type", True) is not False:
        tl["type"].append([0.4, min(4.4, hook_end - 0.3), day.strftime("%B ") + str(day.day) + day.strftime(", %Y")])
    return tl


def _lookup(name: str):
    from . import geocode
    return geocode.lookup(name, region="us")


def summary(tl: dict) -> dict:
    return {k: len(tl.get(k) or []) for k in ("type", "stats", "places", "stamps", "titles", "maps")}
