"""
Real data graphics (the owner, 2026-10-05: "accurate, up to date, impossible for competitors to fake"): when the
narration states a measurable fact about water, drought or weather, the video shows a chart of the REAL, current
numbers from the official source - with the source and the date of the data in its corner - instead of a generic
picture.

    "Lake Powell is just 22 percent full."            -> USBR Lake Powell share of live capacity, the last 25 years
    "Lake Mead has fallen to 1,038 feet."             -> USBR Lake Mead elevation, the last 25 years
    "Nearly 60 percent of the lower 48 is in drought" -> U.S. Drought Monitor, the lower 48 in D1-D4, since 2000
    "2024 was the hottest year on record in the U.S." -> NOAA NCEI contiguous U.S. annual temperature since 1895
    "The Colorado at Lees Ferry runs at 6,600 cfs"    -> USGS 09380000 daily flow, the last 10 years

Three parts, all behind config.DATA_GRAPHICS (off: nothing here runs and the plan is unchanged):

  detect()   reads each line (spoken numbers as digits, numwords) for an entity it knows (a reservoir, a lake, a
             river station, the nation or a state: src/realdata.py's catalog), a metric (a level, a share full,
             storage, flow, drought, a temperature or rainfall record) and a time ("since 2000", "in 2022"). A line
             that names no entity takes the one its neighbours or the story brief name - only when that is the one
             it can be (a level of 1,040 feet is Lake Mead's, not Lake Powell's). Rules only: no model call.
  start()    fetches every distinct query in a background thread beside the footage search, time-boxed
             (DATA_GRAPHICS_SECONDS), into a Store for this job; use() hands it to the planner.
  build()    turns a fact and its Series into the overlay's data document (overlay.data, drawn by remotion
             LibRealData.tsx: rd-line, rd-number, rd-bars, rd-gauge), and check() compares the narration's number
             with the live one: the graphic always shows the live value with its date; a disagreement is flagged in
             the job report (meta.dataGraphics, meta.warnings) - the narration is never "corrected".

Where they land is the planner's (src/treatments.py _data_select / _data_request): on the first word of the fact
as it is said (never early), at most one per DATA_GRAPHICS_GAP seconds, none in the first
DATA_GRAPHICS_HOOK_SECONDS unless that line says the number, never stacked with another graphic.
"""
import contextlib
import contextvars
import datetime as _dt
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import config, numwords, realdata

# The looks (remotion LibRealData.tsx), registered "autoPick": false: only this path places them.
LOOKS = {"line": "LIB_RD_LINE", "number": "LIB_RD_NUMBER", "bars": "LIB_RD_BARS", "gauge": "LIB_RD_GAUGE"}
# A data graphic right after one in the same look takes this one instead (variety).
ALTERNATE = {"gauge": "line", "line": "number", "number": "line", "bars": "line"}
# Years of history a chart shows when the line names none (the owner's example: "the last 25 years").
HISTORY = {"elevation": 25, "percent_full": 25, "storage": 25, "flow": 10}
FIRST_YEAR = {"drought": 2000, "temperature": 1895, "precip": 1895}
# The same entity and metric are charted at most once per this many seconds.
REPEAT_SECONDS = 240.0
FETCH_WORKERS = 4

_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_FRACTIONS = {"half": 50.0, "a half": 50.0, "one half": 50.0, "a third": 33.3, "one third": 33.3,
              "a quarter": 25.0, "one quarter": 25.0, "a fourth": 25.0, "two thirds": 66.7, "three quarters": 75.0}
_FRAC = r"(?P<frac>(?:a|one)\s+(?:half|third|quarter|fourth)|half|two[- ]thirds|three[- ]quarters)"
# Words that make the number a bound or a guess (wider tolerance; a bound is checked as one).
_ABOUT = re.compile(r"\b(about|around|roughly|nearly|almost|approximately|some|close to|just over|just under|"
                    r"more than|over|less than|under|below|above|at least|barely)\s*$", re.I)
_MORE = re.compile(r"\b(more than|over|above|at least|just over)\s*$", re.I)
_LESS = re.compile(r"\b(less than|under|below|just under|barely)\s*$", re.I)
# Not a measurement: what might happen, a plan, a projection.
_NOT_NOW = re.compile(r"\b(if|could|would|might|should|will|projected|projects|projection|forecasts?|predicts?|"
                      r"predicted|expected to|expects|is set to|by 20[3-9]\d|in 20[3-9]\d|plans? to|aims? to|"
                      r"target|goal|imagine|suppose)\b|\bmay\s+(?:be|have|not|soon|well|reach|drop|fall|fill|see|"
                      r"never|even)\b", re.I)          # ("may" the modal, never May the month)
# Near the number: a threshold or a structure, not where the water stands.
_POOL_WORDS = re.compile(r"\b(dead pool|minimum power pool|power pool|full pool|flood stage|spillway|crest of the dam|"
                         r"top of the dam|tall|high dam|deep|intake|intakes|straw|tunnel|pipe|outlet|penstocks?|"
                         r"turbines?|pumping|wide|long|miles?)\b", re.I)
# A level is said as one: a level word or a verb of where the water is.
_LEVEL_WORDS = re.compile(r"\b(level|levels|elevation|surface|fell|fallen|falls|dropped|drops|drop|sank|sunk|sinks|sits|"
                          r"sat|stands|stood|is at|is now at|now at|now sits|hovering|hovers|hovered|record low|"
                          r"record high|low of|high of|lowest|highest|above sea level|bottomed out|peaked|reached|"
                          r"hit|plunged|dipped|rose|risen|climbed)\b", re.I)
_YEAR = re.compile(r"\b(19[0-9]{2}|20[0-9]{2})\b")
_SINCE = re.compile(r"\b(?:since|from|back in|compared (?:to|with)|than in|down from|up from)\s+(?:the\s+)?(?:year\s+|"
                    r"early\s+|late\s+|mid-?)?(19[0-9]{2}|20[0-9]{2})(s)?\b", re.I)
_SPAN = re.compile(r"\b(?:over|in|during|across)\s+the\s+(?:last|past)\s+(\d+|two|three|four|five|ten|twenty|"
                   r"twenty-five|thirty|fifty)\s+(years|decades)\b", re.I)
_DECADE = re.compile(r"\b(?:over|in|during)\s+the\s+(?:last|past)\s+decade\b", re.I)
_WORD_N = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "twenty": 20, "twenty-five": 25, "thirty": 30,
           "fifty": 50}
_LAST_YEAR = re.compile(r"\blast (year|summer|winter|spring|fall)\b", re.I)
_THIS_YEAR = re.compile(r"\bthis (year|summer|winter|spring|fall)\b", re.I)
# A year said as "2,024" by the number reader (no unit after it) is a year.
_COMMA_YEAR = re.compile(r"\b([12]),(9\d\d|0\d\d)\b(?!\s*(?:feet|foot|ft|cubic|cfs|acre|people|%|percent|million|"
                         r"inches|degrees|miles|homes))", re.I)

# ------------------------------------------------------------------ the metric patterns (on spoken-as-digits text)
_PCT = r"\s*(?:%|percent|per cent)"
_PERCENT_FULL = [
    re.compile(_NUM + _PCT + r"\s+(?:full\b|of\s+(?:its|their|the|the reservoir'?s|the lake'?s)?\s*(?:total\s+|live\s+|"
               r"storage\s+|full\s+|maximum\s+|usable\s+)?capacity\b|capacity\b)", re.I),
    re.compile(r"\b" + _FRAC + r"\s+full\b", re.I),
]
_FEET = r"\s*(?:feet|foot|ft\.?)(?![a-z])"
_LEVEL = re.compile(_NUM + _FEET, re.I)
_CHANGE = [
    re.compile(r"\b(?:dropped|fallen|fell|declined|plunged|sunk|sank|shrunk|shrank|lost|gone down|come down|"
               r"lower(?:ed)?)\s+(?:by\s+)?(?:more than\s+|nearly\s+|almost\s+|about\s+|around\s+|roughly\s+|over\s+|"
               r"some\s+|close to\s+)?" + _NUM + _FEET, re.I),
    re.compile(_NUM + _FEET + r"\s+(?:lower|down|below where it|less)\b", re.I),
]
_STORAGE = re.compile(_NUM + r"\s*million\s+acre[- ]?(?:feet|foot)\b", re.I)
_FLOW = re.compile(_NUM + r"\s*(?:cubic\s+feet\s+(?:per|a|each)\s+second|cfs)\b", re.I)
_DROUGHT_LEVEL = [("D4", re.compile(r"\bexceptional\b", re.I)), ("D3", re.compile(r"\bextreme\b", re.I)),
                  ("D2", re.compile(r"\bsevere\b", re.I)), ("D0", re.compile(r"\babnormally dry\b", re.I))]
_DROUGHT = re.compile(r"\bdrought\b", re.I)
_SHARE = re.compile(r"(?:\b(?:nearly|almost|about|roughly|more than|over|just over|just under)\s+)?(?:" + _NUM + _PCT
                    + r"|\b" + _FRAC + r")\s+of\s+", re.I)
# "... of Arizona is in severe drought", "... of the country remains under drought"
_IN_DROUGHT = re.compile(r"^[^.;!?]{0,50}?\b(?:is|are|was|were|remains?|remained|has been|have been|sits?|now|still|"
                         r"currently)?\s*(?:now\s+|currently\s+|still\s+)?(?:in|under|experiencing|facing|gripped by|"
                         r"suffering|in the grip of|affected by)\s+(?:a\s+|an\s+)?(?:[a-z-]+\s+){0,3}drought\b", re.I)
# "drought now covers 63 percent of Arizona"
_COVERS = re.compile(r"\bdrought\b[^.;!?]{0,40}?\b(?:covers|covered|grips|gripped|blankets|blanketed|spans|spanned|"
                     r"affects|affected|has spread (?:across|to|over)|stretches across|extends across|reaches|"
                     r"reached|engulfs|engulfed)\b[^.;!?]{0,30}$", re.I)
_RECORD = re.compile(r"\b(?P<word>hottest|warmest|coldest|coolest|driest|wettest)\s+(?:(?P<period>year|summer|winter|"
                     r"spring|fall|autumn|january|february|march|april|may|june|july|august|september|october|"
                     r"november|december)\b)?", re.I)
_PERIOD_WORD = re.compile(r"\b(year|summer|winter|spring|fall|autumn|january|february|march|april|june|july|august|"
                          r"september|october|november|december)\b", re.I)
_ON_RECORD = re.compile(r"\b(on record|ever recorded|in recorded history|since records began|since record[- ]keeping|"
                        r"in \d+ years of records|of the last \d+ years|in more than a century|ever measured|"
                        r"ever)\b", re.I)
_AVG_TEMP = re.compile(r"\baverage\s+(?:annual\s+|summer\s+)?temperature\s+(?:of|was|hit|reached|at)\s+" + _NUM
                       + r"\s*(?:degrees|°)", re.I)
_RAIN = re.compile(_NUM + r"\s*inches\s+of\s+(?:rain|rainfall|precipitation)\b", re.I)
_ALERTS = re.compile(_NUM + r"\s+(?P<event>flash flood|flood|tornado|severe thunderstorm|winter storm|blizzard|"
                     r"excessive heat|extreme heat|heat|red flag|hurricane|tropical storm|high wind|ice storm)\s+"
                     r"(?P<kind>warnings?|watch(?:es)?|advisor(?:y|ies))\b", re.I)
_NOW = re.compile(r"\b(now|currently|right now|tonight|today|in effect|are active|remain in effect|this morning|"
                  r"this evening)\b", re.I)
# A line about the lake or reservoir without its name.
_RES_PRONOUN = re.compile(r"\b(the (?:lake|reservoir)(?:'s)?|its (?:level|elevation|surface|water level|storage)|"
                          r"the water level|the surface|it is|it's|it\b|the nation'?s (?:largest|second[- ]largest) "
                          r"reservoir)", re.I)
_RIVER_WORDS = re.compile(r"\b(river|flows?|flowing|downstream|upstream|runoff|current)\b", re.I)


_RELATION = re.compile(r"\b(above|below|over|under|from|toward|towards|near|nearing|approaching|close to|than)\b", re.I)


def _threshold(sentence: str, start: int, end: int) -> bool:
    """The number is a threshold's or a structure's, not where the water stands: "dead pool, at 895 feet", "the
    intake at 860 feet", "726 feet tall". A pool named AFTER the number with a relation before it ("3,518 feet, just
    above minimum power pool") is a comparison: the number is the level."""
    if _POOL_WORDS.search(sentence[max(0, start - 40):start]):
        return True
    after = sentence[end:end + 32]
    m = _POOL_WORDS.search(after)
    return bool(m) and not _RELATION.search(after[:m.start()])


def _clean_num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _frac(s: str) -> Optional[float]:
    return _FRACTIONS.get(re.sub(r"[\s-]+", " ", str(s or "").lower()).strip())


def _spoken(text: str) -> str:
    """The line with its spoken numbers in digits ("twenty-two percent" -> "22%"), a year as a year. Never throws."""
    try:
        out = numwords.normalize(text or "")
    except Exception:  # noqa: BLE001 - the words as they are
        out = text or ""
    return _COMMA_YEAR.sub(lambda m: m.group(1) + m.group(2), out)


_ABBREV = re.compile(r"(?:\b(?:U\.S|D\.C|St|Mt|Dr|Mr|Mrs|Ms|Jr|Sr|Ft|No|vs|a\.m|p\.m)|\b[A-Z])\.$")


def _sentences(text: str) -> List[str]:
    """The text's sentences: a full stop ends one only before a capital or a figure and never after "U.S." or
    "St." ("Half of the U.S. is in drought" is one sentence)."""
    out, start = [], 0
    text = text or ""
    for m in re.finditer(r"[.!?;]\s+", text):
        end = m.start() + 1
        if text[m.start()] == "." and (_ABBREV.search(text[max(0, end - 6):end])
                                       or not re.match(r"[A-Z0-9\"“'‘]", text[m.end():m.end() + 1])):
            continue
        out.append(text[start:end])
        start = m.end()
    out.append(text[start:])
    return [s for s in out if s.strip()]


# ------------------------------------------------------------------ names
def _name_rx(names: Iterable[str]) -> "re.Pattern":
    alts = sorted({n for n in names if n}, key=lambda s: -len(s))
    return re.compile(r"(?<![\w])(" + "|".join(re.escape(n).replace(r"\ ", r"[\s-]+") for n in alts) + r")(?![\w])")


def _norm(name: str) -> str:
    return re.sub(r"[\s-]+", " ", name)


_RES_NAMES = {n: rid for rid, r in realdata.RESERVOIRS.items() for n in r["names"]}
_RES_RX = _name_rx(_RES_NAMES)
_LAKE_NAMES = {n: gid for gid, g in realdata.GAUGES.items() if "elevation" in (g.get("params") or {}) for n in g["names"]}
_LAKE_RX = _name_rx(_LAKE_NAMES)
_RIVERS: Dict[str, List[str]] = {}
for _gid, _g in realdata.GAUGES.items():
    if "flow" in (_g.get("params") or {}):
        for _n in _g["names"]:
            _RIVERS.setdefault(_n, []).append(_gid)
_RIVER_RX = _name_rx(_RIVERS)
_BARE_RIVER = re.compile(r"\bthe\s+(Colorado|Mississippi|Missouri|Columbia|Yellowstone|Ohio|Rio Grande)\b(?!\s+[A-Z])")
_STATE_NAMES = {name: code for code, (name, _f, _n) in realdata.STATES.items()}
_STATE_RX = _name_rx(_STATE_NAMES)
# (A name ending in a full stop - "U.S." - ends where no word character follows, not on a word boundary.)
_US = re.compile(r"\b(?:the\s+(?:entire\s+|whole\s+)?(?:United States|U\.\s?S\.|(?-i:US)|country|nation)|America)(?!\w)"
                 r"(?!\s+(?:Geological|Drought|Army|Bureau|Department|Forest|Fish|Census|Postal|Senate|Supreme|Navy|"
                 r"Air Force|government|economy|dollar|Open))", re.I)
_CONUS = re.compile(r"\b(?:the\s+)?(?:lower[- ]48(?:\s+states)?|contiguous\s+(?:United States|U\.\s?S\.|(?-i:US)|states)|"
                    r"continental\s+(?:United States|U\.\s?S\.|(?-i:US)))(?!\w)", re.I)


def _state_hits(text: str) -> List[Tuple[int, int, str]]:
    out = []
    for m in _STATE_RX.finditer(text):
        name = _norm(m.group(1))
        after = text[m.end():m.end() + 14]
        if name == "Washington" and re.match(r"\s*(?:D\.?C|Post)\b", after):
            continue
        if name == "Colorado" and re.match(r"\s+(?:River|Plateau|Basin|Springs|Rockies|Compact)\b", after):
            continue
        if name == "Mississippi" and re.match(r"\s+(?:River|Delta)\b", after):
            continue
        if name in ("Missouri", "Ohio") and re.match(r"\s+River\b", after):
            continue
        out.append((m.start(1), m.end(1), "state:" + _STATE_NAMES[name]))
    return out


def _area_hits(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, area id) of every area the text names: the lower 48, the nation, a state."""
    hits = [(m.start(), m.end(), "conus") for m in _CONUS.finditer(text)]
    hits += [(m.start(), m.end(), "us") for m in _US.finditer(text)
             if not any(a <= m.start() < b for a, b, _x in hits)]
    return sorted(hits + _state_hits(text))


def _trigger(text: str, start: int, end: int) -> str:
    """The word a name lands on: its first word that is not a generic one ("Lake Powell" -> "Powell")."""
    skip = {"the", "lake", "river", "reservoir", "dam", "entire", "whole", "lower", "contiguous", "continental"}
    words = re.findall(r"[A-Za-z][A-Za-z'.-]*", text[start:end])
    for w in words:
        if w.lower().strip(".") not in skip:
            return w.rstrip(".")
    return ""


def _brief_text(brief: Optional[dict]) -> str:
    if not isinstance(brief, dict):
        return ""
    parts = [str(p) for p in (brief.get("places") or []) if isinstance(p, str)]
    parts += [str(s.get("where") or "") for s in (brief.get("sections") or []) if isinstance(s, dict)]
    parts += [str(brief.get(k) or "") for k in ("summary", "event", "title", "subject")]
    return " . ".join(p for p in parts if p)


def brief_entities(brief: Optional[dict]) -> Dict[str, List[str]]:
    """The catalog entities the story brief names, by kind (reservoir, lake, river, area): a line that names none
    may take the one of its kind when the brief has exactly one."""
    text = _brief_text(brief)
    out: Dict[str, List[str]] = {"reservoir": [], "lake": [], "river": [], "area": []}
    for m in _RES_RX.finditer(text):
        rid = _RES_NAMES.get(_norm(m.group(1)))
        if rid and rid not in out["reservoir"]:
            out["reservoir"].append(rid)
    for m in _LAKE_RX.finditer(text):
        gid = _LAKE_NAMES.get(_norm(m.group(1)))
        if gid and gid not in out["lake"]:
            out["lake"].append(gid)
    for m in _RIVER_RX.finditer(text):
        name = _norm(m.group(1))
        if name not in out["river"]:
            out["river"].append(name)
    for _a, _b, area in _area_hits(text):
        if area.startswith("state:") and area not in out["area"]:
            out["area"].append(area)
    return out


# ------------------------------------------------------------------ detection
def _since(sentence: str, metric: str, now: int) -> Tuple[int, Optional[int], Optional[int]]:
    """(the first year to chart, the year the line compares with, the year the fact is about)."""
    default = FIRST_YEAR.get(metric, now - HISTORY.get(metric, 25))
    m = _SINCE.search(sentence)
    if m and int(m.group(1)) <= now:
        y = int(m.group(1))
        return min(default, y - 1), y, None
    m = _SPAN.search(sentence)
    if m:
        word = m.group(1).lower()
        n = int(word) if word.isdigit() else _WORD_N.get(word, 0)
        n *= 10 if m.group(2).lower().startswith("decade") else 1
        if 0 < n <= 130:
            return min(default, now - n), now - n, None
    if _DECADE.search(sentence):
        return min(default, now - 10), now - 10, None
    years = [int(y) for y in _YEAR.findall(sentence) if int(y) <= now]
    about = years[-1] if years else (now - 1 if _LAST_YEAR.search(sentence) else
                                     now if _THIS_YEAR.search(sentence) else None)
    if about is not None and about < now:
        return min(default, about - 1), None, about
    return default, None, about


def _bound(sentence: str, at: int) -> str:
    before = sentence[max(0, at - 24):at]
    if _MORE.search(before):
        return ">"
    if _LESS.search(before):
        return "<"
    return "~" if _ABOUT.search(before) else "="


def _key_of(value: Optional[float]) -> str:
    """The number as the planner times it: its digits ("22", "1038", "6.8")."""
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def _fact(line: int, entity: str, kind: str, metric: str, query: dict, *, said: Optional[float], said_text: str,
          keys: List[str], named: bool, sentence: str, bound: str = "=", **more) -> dict:
    return {"line": line, "entity": entity, "kind": kind, "metric": metric, "query": query,
            "key": realdata.query_key(query), "said": said, "saidText": said_text, "keys": [k for k in keys if k],
            "named": named, "bound": bound, "sentence": sentence.strip()[:240], **more}


def _recent(recent: List[Tuple[int, str, str]], kind: str, line: int, back: int = 2) -> List[str]:
    """The entities of a kind the last `back` lines named, the latest first."""
    return list(dict.fromkeys(e for (ln, k, e) in reversed(recent) if k == kind and 0 <= line - ln <= back))


def _reservoir_for(sentence: str, value: Optional[float], metric: str, recent, line: int,
                   brief_ents: Dict[str, List[str]]) -> Tuple[Optional[str], bool, str]:
    """(reservoir id, named in the sentence, the word to land on): the one named, else the one the context gives
    (the last two lines, else the brief) - only when it is the one the number fits."""
    named = [(m.start(1), m.end(1), _RES_NAMES.get(_norm(m.group(1)))) for m in _RES_RX.finditer(sentence)]
    named = [(a, b, rid) for a, b, rid in named if rid and not re.match(r"\s+(?:City|National)\b", sentence[b:b + 10])]

    def fits(rid: str) -> bool:
        r = realdata.RESERVOIRS[rid]
        if metric == "elevation" and value is not None:
            lo, hi = r["range_ft"]
            return lo <= value <= hi
        if metric == "storage" and value is not None:
            return bool(r.get("capacity")) and value * 1e6 <= r["capacity"] * 1.05
        if metric == "percent_full":
            return bool(r.get("capacity"))
        return True

    if named:
        fitting = [(a, b, rid) for a, b, rid in named if fits(rid)]
        if len({rid for _a, _b, rid in fitting}) == 1:
            a, b, rid = fitting[0]
            return rid, True, _trigger(sentence, a, b)
        return None, True, ""
    if metric in ("percent_full", "storage") and not _RES_PRONOUN.search(sentence):
        return None, False, ""
    cands = [rid for rid in _recent(recent, "reservoir", line) if fits(rid)]
    if not cands:
        cands = [rid for rid in brief_ents.get("reservoir") or [] if fits(rid)]
    if len(cands) == 1:
        return cands[0], False, ""
    return None, False, ""


def _river_for(sentence: str, recent, line: int, brief_ents: Dict[str, List[str]]) -> Tuple[Optional[str], bool, str]:
    """(station id, named, the word to land on): a river named (or "the Colorado" said with river words), its station
    by the place the sentence names, else its first station."""
    found = [(m.start(1), m.end(1), _norm(m.group(1))) for m in _RIVER_RX.finditer(sentence)]
    if not found and _RIVER_WORDS.search(sentence):
        for m in _BARE_RIVER.finditer(sentence):
            name = m.group(1) + ("" if m.group(1) == "Rio Grande" else " River")
            if name in _RIVERS:
                found.append((m.start(1), m.end(1), name))
    named = bool(found)
    if found:
        a, b, river = found[0]
    else:
        names = _recent(recent, "river", line) or list(brief_ents.get("river") or [])
        if len(names) != 1:
            return None, False, ""
        river, a, b = names[0], -1, -1
    stations = _RIVERS.get(river) or []
    if not stations:
        return None, named, ""
    pick = stations[0]
    for gid in stations:
        if any(re.search(r"\b" + re.escape(p) + r"\b", sentence) for p in realdata.GAUGES[gid].get("places") or []):
            pick = gid
            break
    return pick, named, (_trigger(sentence, a, b) if a >= 0 else "")


def _area_named(sentence: str, lo: int = 0, hi: int = 10 ** 6) -> Optional[Tuple[int, int, str]]:
    hits = [h for h in _area_hits(sentence) if lo <= h[0] <= hi]
    return hits[0] if hits else None


def _area_context(sentence: str, recent, line: int, brief_ents: Dict[str, List[str]]) -> Optional[str]:
    """ "the state" with no name: the state the last lines (else the brief) name, when there is one."""
    if not re.search(r"\b(the state|the region)\b", sentence, re.I):
        return None
    cands = [a for a in _recent(recent, "area", line, 3) if a.startswith("state:")] or \
        [a for a in brief_ents.get("area") or [] if a.startswith("state:")]
    return cands[0] if len(cands) == 1 else None


def detect_line(text: str, line: int = 0, recent: Optional[List[Tuple[int, str, str]]] = None,
                brief_ents: Optional[Dict[str, List[str]]] = None, now: Optional[int] = None) -> List[dict]:
    """
    The measurable facts one line states, in the order said: each {"line", "entity", "kind", "metric", "query",
    "key" (its fetch key), "said" (the narration's number, or None), "saidText", "keys" (words to land on, as said),
    "named" (the entity is named in the line), "bound" (= ~ > <), "year" / "compare" (years the line is about or
    compares with), "level" / "period" / "word" / "record" (drought level, a record's period and word), "look"}.
    `recent`: (line, kind, entity) named in the lines before; `brief_ents`: brief_entities(brief).
    """
    now = now or realdata.today().year
    recent = recent or []
    brief_ents = brief_ents or {}
    out: List[dict] = []
    for sentence in _sentences(_spoken(text)):
        if _NOT_NOW.search(sentence):
            continue                      # what might happen, a plan, a projection: not a measurement
        got = _reservoir_facts(sentence, line, recent, brief_ents, now) or \
            _lake_facts(sentence, line, recent, brief_ents, now) or _river_facts(sentence, line, recent, brief_ents, now)
        got += _drought_facts(sentence, line, recent, brief_ents, now)
        got += _record_facts(sentence, line, recent, brief_ents, now)
        got += _alert_facts(sentence, line)
        out.extend(got)
    seen, kept = set(), []
    for f in out:                         # one fact per entity and metric in a line: the first said
        k = (f["entity"], f["metric"])
        if k not in seen:
            seen.add(k)
            kept.append(f)
    return kept


def _reservoir_facts(sentence: str, line: int, recent, brief_ents, now: int) -> List[dict]:
    out: List[dict] = []
    for rx in _PERCENT_FULL:
        m = rx.search(sentence)
        if not m:
            continue
        spoken_num = "num" in rx.groupindex and m.group("num")
        value = _clean_num(m.group("num")) if spoken_num else _frac(m.group("frac"))
        if value is None or not 0 < value <= 100:
            continue
        rid, named, word = _reservoir_for(sentence, value, "percent_full", recent, line, brief_ents)
        if not rid:
            continue
        since, compare, about = _since(sentence, "percent_full", now)
        q = {"source": "usbr", "entity": rid, "metric": "percent_full", "since": since}
        out.append(_fact(line, rid, "reservoir", "percent_full", q, said=value, said_text=m.group(0).strip(),
                         keys=[word, _key_of(value) if spoken_num else "full"], named=named, sentence=sentence,
                         bound=_bound(sentence, m.start()), year=about, compare=compare, look="gauge"))
        break
    m = _STORAGE.search(sentence)
    if m:
        value = _clean_num(m.group("num"))
        rid, named, word = _reservoir_for(sentence, value, "storage", recent, line, brief_ents)
        if rid and value:
            since, compare, about = _since(sentence, "storage", now)
            q = {"source": "usbr", "entity": rid, "metric": "storage", "since": since}
            out.append(_fact(line, rid, "reservoir", "storage", q, said=value, said_text=m.group(0).strip(),
                             keys=[word, _key_of(value)], named=named, sentence=sentence,
                             bound=_bound(sentence, m.start()), year=about, compare=compare, look="number"))
    # A change ("has dropped 150 feet since 2000") is read before a level: its number is not a level.
    for rx in _CHANGE:
        m = rx.search(sentence)
        if not m:
            continue
        value = _clean_num(m.group("num"))
        if value is None or not 1 <= value <= 400 or _threshold(sentence, m.start("num"), m.end()):
            continue
        rid, named, word = _reservoir_for(sentence, None, "elevation", recent, line, brief_ents)
        if not rid:
            continue
        since, compare, about = _since(sentence, "elevation", now)
        q = {"source": "usbr", "entity": rid, "metric": "elevation", "since": since}
        out.append(_fact(line, rid, "reservoir", "elevation", q, said=None, said_text=m.group(0).strip(),
                         keys=[word, _key_of(value)], named=named, sentence=sentence, change=-value,
                         compare=compare, year=about, look="line"))
        return out
    for m in _LEVEL.finditer(sentence):
        value = _clean_num(m.group("num"))
        if value is None or value < 100:
            continue
        if _threshold(sentence, m.start(), m.end()) or not _LEVEL_WORDS.search(sentence):
            continue                      # "dead pool, at 895 feet", "the intake at 860 feet": not where it stands
        rid, named, word = _reservoir_for(sentence, value, "elevation", recent, line, brief_ents)
        if not rid:
            continue
        since, compare, about = _since(sentence, "elevation", now)
        q = {"source": "usbr", "entity": rid, "metric": "elevation", "since": since}
        out.append(_fact(line, rid, "reservoir", "elevation", q, said=value, said_text=m.group(0).strip(),
                         keys=[word, _key_of(value)], named=named, sentence=sentence,
                         bound=_bound(sentence, m.start()), year=about, compare=compare, look="line"))
        break
    return out


def _lake_facts(sentence: str, line: int, recent, brief_ents, now: int) -> List[dict]:
    """A lake the USGS measures (the Great Salt Lake): its level in feet."""
    hits = [(m.start(1), m.end(1), _LAKE_NAMES.get(_norm(m.group(1)))) for m in _LAKE_RX.finditer(sentence)]
    hits = [h for h in hits if h[2]]
    for m in _LEVEL.finditer(sentence):
        value = _clean_num(m.group("num"))
        if value is None or _threshold(sentence, m.start(), m.end()) or not _LEVEL_WORDS.search(sentence):
            continue
        cands = hits
        if not cands and re.search(r"\b(the lake|its level|the lake'?s)\b", sentence, re.I):
            ids = _recent(recent, "lake", line) or list(brief_ents.get("lake") or [])
            cands = [(-1, -1, ids[0])] if len(ids) == 1 else []
        if not cands:
            continue
        a, b, gid = cands[0]
        lo, hi = realdata.GAUGES[gid].get("range_ft") or (0.0, 1e9)
        if not lo <= value <= hi:
            continue
        since, compare, about = _since(sentence, "elevation", now)
        q = {"source": "usgs", "entity": gid, "metric": "elevation", "since": since}
        return [_fact(line, gid, "lake", "elevation", q, said=value, said_text=m.group(0).strip(),
                      keys=[_trigger(sentence, a, b) if a >= 0 else "", _key_of(value)], named=a >= 0,
                      sentence=sentence, bound=_bound(sentence, m.start()), year=about, compare=compare, look="line")]
    return []


def _river_facts(sentence: str, line: int, recent, brief_ents, now: int) -> List[dict]:
    m = _FLOW.search(sentence)
    if not m:
        return []
    value = _clean_num(m.group("num"))
    if not value:
        return []
    gid, named, word = _river_for(sentence, recent, line, brief_ents)
    if not gid:
        return []
    since, compare, about = _since(sentence, "flow", now)
    q = {"source": "usgs", "entity": gid, "metric": "flow", "since": since}
    return [_fact(line, gid, "river", "flow", q, said=value, said_text=m.group(0).strip(),
                  keys=[word, _key_of(value)], named=named, sentence=sentence,
                  bound=_bound(sentence, m.start()), year=about, compare=compare, look="number")]


def _drought_facts(sentence: str, line: int, recent, brief_ents, now: int) -> List[dict]:
    """ "60 percent of the lower 48 is in drought", "drought now covers 63 percent of Arizona", "nearly half of the
    country is in severe drought": a share OF an area, in drought."""
    if not _DROUGHT.search(sentence):
        return []
    for pm in _SHARE.finditer(sentence):
        value = _clean_num(pm.group("num")) if pm.group("num") else _frac(pm.group("frac"))
        if value is None or not 0 < value <= 100:
            continue
        hit = _area_named(sentence, pm.end() - 5, pm.end() + 3)
        area, named, word = None, False, ""
        if hit:
            if sentence[hit[1]:hit[1] + 2] in ("'s", "’s"):
                continue                  # "65 percent of Colorado's farmers": not the land
            area, named = hit[2], True
            word = _trigger(sentence, hit[0], hit[1])
            tail = sentence[hit[1]:]
        else:
            m = re.match(r"(?:the\s+)?(state|region)\b", sentence[pm.end():], re.I)
            area = _area_context(sentence, recent, line, brief_ents) if m else None
            tail = sentence[pm.end() + (m.end() if m else 0):]
        if not area:
            continue
        if not (_IN_DROUGHT.search(tail) or _COVERS.search(sentence[:pm.start()])):
            continue
        level = "D1"
        for lv, rx in _DROUGHT_LEVEL:
            if rx.search(sentence):
                level = lv
                break
        since, compare, about = _since(sentence, "drought", now)
        q = {"source": "usdm", "entity": area, "metric": "drought", "level": level, "since": since}
        keys = [word, _key_of(value) if pm.group("num") else "", "drought"]
        num_at = pm.start("num") if pm.group("num") else pm.start("frac")
        said_text = re.sub(r"\s+of\s*$", "", pm.group(0).strip(), flags=re.I)
        return [_fact(line, area, "area", "drought", q, said=value, said_text=said_text, keys=keys,
                      named=named, sentence=sentence, bound=_bound(sentence, num_at), level=level, year=about,
                      compare=compare, look=("bars" if level in ("D2", "D3", "D4") else "line"))]
    return []


def _record_facts(sentence: str, line: int, recent, brief_ents, now: int) -> List[dict]:
    out: List[dict] = []
    m = _RECORD.search(sentence)
    if m and _ON_RECORD.search(sentence[m.start():]):
        word = m.group("word").lower()
        period = (m.group("period") or "").lower()
        if not period:
            p = _PERIOD_WORD.search(sentence)
            period = p.group(1).lower() if p else ""
        period = "fall" if period == "autumn" else period
        metric = "precip" if word in ("driest", "wettest") else "temperature"
        hit = _area_named(sentence)
        area = hit[2] if hit else _area_context(sentence, recent, line, brief_ents)
        if area and period in realdata.PERIODS and realdata.AREAS.get(area, {}).get("ncei"):
            _since_y, _cmp, about = _since(sentence, metric, now)
            q = {"source": "ncei", "entity": area, "metric": metric, "period": period, "since": 1895}
            akey = _trigger(sentence, hit[0], hit[1]) if hit else ""
            out.append(_fact(line, area, "area", metric, q, said=None, said_text=m.group(0).strip()[:60],
                             keys=[str(about) if about and str(about) in sentence else "", akey, m.group("word")],
                             named=bool(hit), sentence=sentence, word=word, period=period, year=about, look="line",
                             record=True))
            return out
    t = _AVG_TEMP.search(sentence)
    if t:
        hit = _area_named(sentence)
        area = hit[2] if hit else None
        if area and realdata.AREAS.get(area, {}).get("ncei"):
            value = _clean_num(t.group("num"))
            period = "summer" if re.search(r"\bsummer\b", sentence, re.I) else "year"
            _since_y, _cmp, about = _since(sentence, "temperature", now)
            q = {"source": "ncei", "entity": area, "metric": "temperature", "period": period, "since": 1895}
            out.append(_fact(line, area, "area", "temperature", q, said=value, said_text=t.group(0).strip(),
                             keys=[_trigger(sentence, hit[0], hit[1]), _key_of(value)], named=True, sentence=sentence,
                             bound=_bound(sentence, t.start("num")), period=period, year=about, look="line"))
            return out
    r = _RAIN.search(sentence)
    if r:
        hit = _area_named(sentence)
        years = [int(y) for y in _YEAR.findall(sentence) if int(y) < now]
        if hit and years and realdata.AREAS.get(hit[2], {}).get("ncei"):
            value = _clean_num(r.group("num"))
            q = {"source": "ncei", "entity": hit[2], "metric": "precip", "period": "year", "since": 1895}
            out.append(_fact(line, hit[2], "area", "precip", q, said=value, said_text=r.group(0).strip(),
                             keys=[_trigger(sentence, hit[0], hit[1]), _key_of(value)], named=True, sentence=sentence,
                             bound=_bound(sentence, r.start()), period="year", year=years[-1], look="line"))
    return out


def _alert_facts(sentence: str, line: int) -> List[dict]:
    """ "12 flood warnings are in effect across Texas right now": the alerts of that kind in effect now."""
    m = _ALERTS.search(sentence)
    if not m or not _NOW.search(sentence):
        return []
    hits = _state_hits(sentence)
    if not hits:
        return []
    value = _clean_num(m.group("num"))
    kind = m.group("kind").lower()
    event = " ".join(w.capitalize() for w in m.group("event").split()) + " " + \
        ("Warning" if kind.startswith("warn") else "Watch" if kind.startswith("watch") else "Advisory")
    area = hits[0][2]
    q = {"source": "nws", "entity": area, "metric": "alerts", "event": event}
    return [_fact(line, area, "area", "alerts", q, said=value, said_text=m.group(0).strip()[:60],
                  keys=[_key_of(value)], named=True, sentence=sentence, event=event, look="number")]


def detect(texts: List[str], brief: Optional[dict] = None, now: Optional[int] = None) -> List[dict]:
    """Every line's facts (detect_line), reading on with what the lines before named."""
    ents = brief_entities(brief)
    recent: List[Tuple[int, str, str]] = []
    out: List[dict] = []
    for i, text in enumerate(texts):
        spoken = _spoken(text)
        for m in _RES_RX.finditer(spoken):
            rid = _RES_NAMES.get(_norm(m.group(1)))
            if rid:
                recent.append((i, "reservoir", rid))
        for m in _LAKE_RX.finditer(spoken):
            gid = _LAKE_NAMES.get(_norm(m.group(1)))
            if gid:
                recent.append((i, "lake", gid))
        for m in _RIVER_RX.finditer(spoken):
            recent.append((i, "river", _norm(m.group(1))))
        for _a, _b, area in _state_hits(spoken):
            recent.append((i, "area", area))
        out.extend(detect_line(text, i, recent, ents, now))
        recent = [r for r in recent if i - r[0] <= 3]
    return out


# ------------------------------------------------------------------ the job's store
class Store:
    """One job's fetched series by query key, filled by a background thread (start)."""

    def __init__(self):
        self.series: Dict[str, dict] = {}
        self.errors: Dict[str, str] = {}
        self.facts: List[dict] = []
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.started = time.time()
        self.seconds = 0.0

    def put(self, key: str, series: Optional[dict], why: str = "") -> None:
        with self.lock:
            if series:
                self.series[key] = series
                self.errors.pop(key, None)
            else:
                self.errors[key] = why or "no data"

    def get(self, key: str) -> Optional[dict]:
        with self.lock:
            return self.series.get(key)

    def why(self, key: str) -> str:
        with self.lock:
            if key in self.errors:
                return self.errors[key]
        return "still fetching" if not self.done.is_set() else "not asked for"

    def wait(self, timeout: float) -> bool:
        return self.done.wait(max(0.0, float(timeout)))

    def report(self) -> dict:
        with self.lock:
            return {"queries": len(self.series) + len(self.errors), "fetched": sorted(self.series),
                    "failed": dict(self.errors), "seconds": round(self.seconds, 1), "done": self.done.is_set()}


_CURRENT: contextvars.ContextVar = contextvars.ContextVar("tg_data_store", default=None)


@contextlib.contextmanager
def use(store: Optional[Store]):
    """The planner reads this job's fetched data while the block runs."""
    token = _CURRENT.set(store)
    try:
        yield store
    finally:
        _CURRENT.reset(token)


def current() -> Optional[Store]:
    return _CURRENT.get()


def queries(facts: List[dict]) -> List[dict]:
    """The distinct queries of these facts, the first said first."""
    seen, out = set(), []
    for f in facts:
        if f["key"] not in seen:
            seen.add(f["key"])
            out.append(f["query"])
    return out


def fetch_all(store: Store, qs: List[dict], budget: float) -> Store:
    """Every query fetched into the store within `budget` seconds (FETCH_WORKERS at once). Never raises."""
    t0 = time.time()
    deadline = t0 + max(1.0, float(budget))
    try:
        if qs:
            with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(qs))) as ex:
                futs = {ex.submit(realdata.fetch, q, deadline): realdata.query_key(q) for q in qs}
                for fut in as_completed(futs):
                    key = futs[fut]
                    try:
                        s, why = fut.result()
                    except Exception as e:  # noqa: BLE001
                        s, why = None, f"{type(e).__name__}: {str(e)[:120]}"
                    store.put(key, s, why)
    except Exception as e:  # noqa: BLE001 - a chart is a nicety, never a failure
        print(f"[datagraphics] fetching stopped: {type(e).__name__}: {str(e)[:160]}", flush=True)
    finally:
        store.seconds = time.time() - t0
        store.done.set()
    return store


def start(texts: List[str], brief: Optional[dict] = None, budget: Optional[float] = None) -> Store:
    """Detect the facts of a whole narration and fetch their data in a background thread (returns at once)."""
    store = Store()
    try:
        store.facts = detect(list(texts), brief)
    except Exception as e:  # noqa: BLE001
        print(f"[datagraphics] detection skipped: {type(e).__name__}: {str(e)[:160]}", flush=True)
        store.facts = []
    qs = queries(store.facts)
    print(f"[datagraphics] {len(store.facts)} fact(s), {len(qs)} series to fetch", flush=True)
    budget = float(config.DATA_GRAPHICS_SECONDS if budget is None else budget)
    threading.Thread(target=fetch_all, args=(store, qs, budget), name="data-graphics", daemon=True).start()
    return store


# ------------------------------------------------------------------ the graphic's document
def fmt(value: float, decimals: int, unit: str = "") -> str:
    """ "1,037.9 FT", "22.3%", "5.19 MAF", "6,580 CFS", "55.5°F" - a value as the report and the looks write it."""
    text = f"{float(value):,.{max(0, int(decimals))}f}"
    if unit in ("%", "°F"):
        return text + unit
    return f"{text} {unit}".strip()


def _days(iso: str) -> int:
    try:
        return _dt.date.fromisoformat(str(iso)[:10]).toordinal()
    except ValueError:
        try:
            return _dt.date(int(str(iso)[:4]), 7, 1).toordinal()
        except ValueError:
            return 0


def _year_points(points: List[list], year: int) -> List[list]:
    return [p for p in points if str(p[0])[:4] == str(year)]


def _window(points: List[list], since: int) -> List[list]:
    keep = [p for p in points if int(str(p[0])[:4]) >= since]
    return keep if len(keep) >= 2 else points


def _near(points: List[list], iso: str) -> Optional[list]:
    target = _days(iso)
    return min(points, key=lambda p: abs(_days(p[0]) - target)) if points else None


def check(fact: dict, series: dict) -> dict:
    """
    The narration's number against the live data: {"agrees": True / False / None, "said", "live", "liveText",
    "asOf", "note", ...}. A year the line is about is checked against that year's readings, a change against the
    change since the year it names, a record against that year's rank. None: nothing the line said can be checked.
    """
    dec = int(series.get("decimals") or 0)
    unit = series.get("unit") or ""
    points = series.get("points") or []
    live = (series.get("latest") or {}).get("value")
    out = {"said": fact.get("saidText") or "", "saidValue": fact.get("said"), "live": live,
           "liveText": fmt(float(live), dec, unit) if isinstance(live, (int, float)) else "",
           "asOf": series.get("asOf"), "asOfLabel": series.get("asOfLabel"), "source": series.get("sourceName"),
           "url": series.get("url"), "agrees": None, "note": ""}
    metric = fact.get("metric")
    said = fact.get("said")
    tol = {"percent_full": 2.5, "elevation": 3.0, "storage": 0.15, "drought": 3.0, "temperature": 0.3,
           "precip": 0.5, "alerts": 0.0}.get(metric, 0.0)
    if metric == "flow" and said:
        tol = 0.15 * float(said)
    if fact.get("bound") == "~":
        tol *= 2
    if fact.get("record"):
        extra = series.get("extra") or {}
        ranks = extra.get("ranks") or {}
        n = int(extra.get("years") or len(ranks))
        year = fact.get("year")
        if year is None:
            return {**out, "note": "a record said without its year: the chart marks the record year"}
        r = ranks.get(str(year))
        if r is None:
            return {**out, "note": f"no {year} value in the series yet"}
        rank = r if fact.get("word") in ("hottest", "warmest", "wettest") else n + 1 - r
        out.update(live=rank, liveText=f"#{rank} of {n} years", agrees=rank == 1)
        if rank != 1:
            out["note"] = f"{year} ranks #{rank} of {n} ({fact.get('word')}) in {series.get('source')}'s record"
        return out
    if fact.get("change") is not None:
        compare = fact.get("compare")
        if not compare:
            return {**out, "note": "a change with no start year: not checked"}
        start = _year_points(points, compare)
        if not start or live is None:
            return {**out, "note": f"no {compare} reading in the series"}
        drop = float(live) - float(start[0][1])
        out.update(live=round(drop, dec), liveText=f"{'−' if drop < 0 else '+'}{fmt(abs(drop), dec, unit)} since {compare}")
        out["agrees"] = abs(abs(drop) - abs(float(fact["change"]))) <= max(5.0, 0.1 * abs(float(fact["change"])))
        if not out["agrees"]:
            out["note"] = f"the narration says {out['said']}; {series.get('source')} shows {out['liveText']}"
        return out
    if said is None or live is None:
        return out
    year = fact.get("year")
    if year and year < realdata.today().year:
        vals = [float(p[1]) for p in _year_points(points, year)]
        if vals:
            lo, hi = min(vals), max(vals)
            ok = lo - tol <= float(said) <= hi + tol
            out.update(agrees=ok, note=f"{year} readings {fmt(lo, dec, unit)} to {fmt(hi, dec, unit)}"
                       + ("" if ok else f"; the narration says {out['said']}"))
            return out
    bound = fact.get("bound")
    if bound == ">":
        ok = float(live) >= float(said) - tol
    elif bound == "<":
        ok = float(live) <= float(said) + tol
    else:
        ok = abs(float(live) - float(said)) <= tol + 1e-9
    out["agrees"] = bool(ok)
    if not ok:
        out["note"] = (f"the narration says {out['said']}; {series.get('source')} shows {out['liveText']} "
                       f"({series.get('asOfLabel')})")
    return out


def warnings_for(report: Optional[dict]) -> List[str]:
    """The job report's warnings for the narration's numbers the official data does not bear out (meta.warnings):
    the chart showed the official number; the script keeps its words for the owner to check."""
    out = []
    for item in (report or {}).get("items") or []:
        chk = item.get("check") or {}
        if item.get("status") == "shown" and chk.get("agrees") is False:
            out.append(f"Data check, line {int(item.get('line', 0)) + 1}: "
                       f"{chk.get('note') or 'the narration and the official data differ'} - the chart shows the "
                       "official number; check the script.")
    return out


def build(fact: dict, series: dict, look: str) -> Tuple[dict, dict]:
    """
    (props, data) for a fact drawn in `look`: the overlay's own props (text, label, subtitle, value, suffix - what
    the editor shows and the reading time counts) and its data document (overlay.data, LibRealData.tsx).
    """
    dec = int(series.get("decimals") or 0)
    unit = series.get("unit") or ""
    metric = fact.get("metric")
    extra = series.get("extra") or {}
    since = int((fact.get("query") or {}).get("since") or 0)
    points = _window(list(series.get("points") or []), since)
    year_step = series.get("step") == "year"
    latest = dict(series.get("latest") or {})
    latest["label"] = series.get("asOfLabel") or ""
    data: Dict[str, Any] = {
        "v": 1, "look": look, "metric": metric, "entity": series.get("entityName"), "title": series.get("title"),
        "kicker": series.get("kicker"), "unit": unit, "decimals": dec, "step": series.get("step"), "points": points,
        # (The data's link is "sourceUrl", never "url": every "url" in a document is a media file to the render.)
        "latest": latest, "source": series.get("source"), "sourceName": series.get("sourceName"),
        "sourceUrl": series.get("url"), "asOf": series.get("asOf"), "asOfLabel": series.get("asOfLabel"),
    }
    if metric in ("percent_full", "drought"):
        data["range"] = [0, 100]
    label_of = (lambda iso: realdata.date_label(iso, "year" if year_step else "month"))
    # The point the line compares with, or the year it is about; else a year ago (a reservoir's fill, a river's flow,
    # the drought: what changed this year); else the start of the window (a level over 25 years).
    compare_pt, compare_label = None, ""
    if fact.get("compare"):
        pts = _year_points(points, fact["compare"])
        if pts:
            compare_pt, compare_label = pts[0], label_of(pts[0][0])
    elif fact.get("year") and not fact.get("record") and fact.get("said") is not None:
        pts = _year_points(points, fact["year"])
        if pts:
            compare_pt = min(pts, key=lambda p: abs(float(p[1]) - float(fact["said"])))
            compare_label = label_of(compare_pt[0])
    if compare_pt is None and (look == "gauge" or metric in ("drought", "flow")) and points and latest.get("date"):
        last = _days(latest["date"])
        prior = [p for p in points if last - 400 <= _days(p[0]) <= last - 330]
        if prior:
            compare_pt = _near(prior, _dt.date.fromordinal(last - 365).isoformat())
            compare_label = label_of(compare_pt[0])        # a monthly mean: its month, not "a year ago"
    if compare_pt is None and points and look in ("line", "number") and not fact.get("record") \
            and metric not in ("temperature", "precip", "alerts"):
        compare_pt, compare_label = points[0], label_of(points[0][0])
    if compare_pt is not None:
        data["compare"] = {"date": compare_pt[0], "value": compare_pt[1], "label": compare_label}
        if isinstance(latest.get("value"), (int, float)):
            delta = float(latest["value"]) - float(compare_pt[1])
            if abs(delta) >= 10 ** -dec:
                d_unit = "PTS" if unit == "%" else unit
                data["delta"] = {"value": round(delta, dec + 1),
                                 "text": f"{'−' if delta < 0 else '+'}{fmt(abs(delta), dec, d_unit)} SINCE {compare_label}"}
    if metric == "elevation":
        pools = extra.get("pools") or {}
        vals = [float(p[1]) for p in points] or [0.0]
        lo, hi = min(vals), max(vals)
        span = max(1.0, hi - lo)
        said = (fact.get("sentence") or "").lower()
        refs = [{"label": name.upper(), "value": level} for name, level in pools.items()
                if name in said or lo - 0.12 * span <= level <= hi + 0.12 * span]
        if refs:
            data["refs"] = sorted(refs, key=lambda r: -r["value"])[:3]
    if look == "gauge" and extra.get("capacity") and isinstance(latest.get("value"), (int, float)):
        cap = float(extra["capacity"])
        data["storage"] = {"value": round(float(latest["value"]) / 100.0 * cap / 1e6, 2),
                           "capacity": round(cap / 1e6, 2), "unit": "MAF"}
    if metric == "drought":
        cats = extra.get("categories") or {}
        level = fact.get("level") or "D1"
        names = {"D1": "IN DROUGHT", "D2": "SEVERE OR WORSE", "D3": "EXTREME OR WORSE", "D4": "EXCEPTIONAL"}
        data["bars"] = [{"label": names[lv], "value": cats.get(lv, 0.0), "highlight": lv == level}
                        for lv in ("D1", "D2", "D3", "D4")]
        data["week"] = extra.get("week")
        if look == "bars":
            data["kicker"] = f"SHARE OF AREA · WEEK OF {series.get('asOfLabel')}"
    if metric in ("temperature", "precip"):
        ranks = extra.get("ranks") or {}
        n = int(extra.get("years") or len(ranks))
        word = (fact.get("word") or ("warmest" if metric == "temperature" else "wettest")).lower()
        high = word in ("hottest", "warmest", "wettest")
        best = None
        for p in points:
            y = str(p[0])[:4]
            if y not in ranks:
                continue
            rr = ranks[y] if high else n + 1 - ranks[y]
            if fact.get("year") and int(y) == int(fact["year"]):
                best = (rr, p)
                break
            if best is None or rr < best[0]:
                best = (rr, p)
        if best:
            rr, p = best
            name = {"hottest": "WARMEST", "warmest": "WARMEST", "coldest": "COLDEST", "coolest": "COLDEST",
                    "driest": "DRIEST", "wettest": "WETTEST"}.get(word, "WARMEST")
            data["record"] = {"date": p[0], "value": p[1], "label": str(p[0])[:4], "rank": rr, "of": n, "word": name}
            data["delta"] = {"value": rr, "text": (f"{str(p[0])[:4]}: {name} OF {n} YEARS" if rr == 1
                                                   else f"{str(p[0])[:4]}: #{rr} {name} OF {n} YEARS")}
    if metric == "alerts":
        data["points"] = []
    props = {"text": str(series.get("title") or "")[:60], "label": str(data.get("kicker") or "")[:80],
             "subtitle": f"SOURCE: {series.get('source')} · DATA AS OF {series.get('asOfLabel')}"[:120]}
    if isinstance(latest.get("value"), (int, float)):
        props["value"] = latest["value"]
        props["suffix"] = unit
    return props, data
