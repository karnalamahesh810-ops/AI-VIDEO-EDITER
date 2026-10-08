"""
Looks pack 3's planner rules (2026-10-08, the owner: "more animations, better animations ... extra ones that are
perfectly quality ones"). Ten looks in the kinetic-type system (remotion/src/components/lib/LibKtPack3.tsx,
LibKtMaps3.tsx; registry family "ktp3", scripts/library_looks_ktpack3.json), each picked only where the
narration says what it shows, with the narration's own words and figures:

  KT_RANKING    three to six names, each with its value of one unit ("Flagstaff got 3.4 inches, Prescott 2.9,
                Phoenix 2.1 ..."), or "the five driest cities are A, B, C, D and E": the rank slots fill as each
                one is said
  KT_WATERLINE  a lake's level in feet with its years ("1,225 feet in 1983 ... 1,040 feet in 2022"), or a drop
                since a year ("Lake Mead has dropped 170 feet since 2000")
  KT_SEVERITY   a level on a known scale: a hurricane's category, a tornado's EF rating, the drought monitor's
                D0-D4 (or its words: "exceptional drought"), the Colorado River's shortage tiers, "level 3 of 4"
  KT_DELTA      a change said from one figure to another ("fell from 1,225 feet to 1,040"), or a change since a
                year ("down 38 percent since 2000")
  KT_STREAK     a streak of days ("31 straight days above 110 degrees", "143 days without rain") - never a span
                of time ("three days later", "within 48 hours": the owner's rule, no graphic at all)
  KT_ALERT      an official alert by name ("a flash flood warning until 9 p.m. for Clark County", "evacuation
                orders"), with what was said of it (until when, where, who issued it)
  KT_REGIONS    three to twelve US states (or countries) named in one list
  KT_ROUTE      an older two-to-six-place map whose line is a route (from / to / through, a river, a canal)
  KT_STORM      an older map whose line is a storm moving through its places
  KT_TOTALS     an older several-place map whose line gives each place a value of one unit

The seven data looks are planned with the data planner (src/datalooks.py: on their words, in its one lane, on a
build and on the relook action); the three maps upgrade an older map look of the plan in place, its places
kept (src/datalooks.py finish -> upgrade_maps). Density: one pack-3 look at least PACK3_GAP seconds after
another, at most PACK3_PER_MINUTE in any minute, each look its own EVERY spacing. Pure functions: no network,
no paid calls.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RANKING = "KT_RANKING"
WATERLINE = "KT_WATERLINE"
SEVERITY = "KT_SEVERITY"
DELTA = "KT_DELTA"
STREAK = "KT_STREAK"
ALERT = "KT_ALERT"
REGIONS = "KT_REGIONS"
ROUTE = "KT_ROUTE"
STORM = "KT_STORM"
TOTALS = "KT_TOTALS"
DATA_IDS = (RANKING, WATERLINE, SEVERITY, DELTA, STREAK, ALERT, REGIONS)
MAP_IDS = (ROUTE, STORM, TOTALS)
IDS = DATA_IDS + MAP_IDS
# The two cut transitions of the pack (remotion/src/transitions/TransitionFrame.tsx; src/timeline.py cycles).
TRANSITIONS = ("light-sweep", "soft-whip")


def variant_of(tid: str) -> str:
    """KT_WATERLINE -> 'kt-waterline'."""
    return "kt-" + tid[3:].lower().replace("_", "-")


# --------------------------------------------------------------------------- pace
PACK3_GAP = 24.0            # seconds between two pack-3 looks
PACK3_WINDOW = 60.0         # ... and at most PACK3_PER_MINUTE of them in any such window
PACK3_PER_MINUTE = 2
# Each look's own spacing (seconds from its last start): an alert or a scale may come back sooner than a map.
EVERY: Dict[str, float] = {RANKING: 90.0, WATERLINE: 120.0, SEVERITY: 60.0, DELTA: 60.0, STREAK: 90.0, ALERT: 60.0,
                           REGIONS: 120.0, ROUTE: 90.0, STORM: 120.0, TOTALS: 120.0}
REPEAT = 90.0               # the same ranking / level / alert said again this soon is not shown again


class Pace:
    """When each pack-3 look landed: allows() says whether one more may land at `at`."""

    def __init__(self) -> None:
        self.placed: List[Tuple[str, float]] = []

    def allows(self, tid: str, at: float) -> bool:
        if tid not in IDS:
            return True
        if any(abs(at - t) < PACK3_GAP for _x, t in self.placed):
            return False
        if sum(1 for _x, t in self.placed if 0 <= at - t < PACK3_WINDOW or 0 <= t - at < PACK3_WINDOW) >= PACK3_PER_MINUTE:
            return False
        last = [t for x, t in self.placed if x == tid]
        return all(abs(at - t) >= EVERY.get(tid, 60.0) for t in last)

    def note(self, tid: str, at: float) -> None:
        if tid in IDS:
            self.placed.append((tid, float(at)))

    def forget(self, tid: str, at: float) -> None:
        """A look that will not show after all (another took its moment)."""
        self.placed = [(x, t) for x, t in self.placed if not (x == tid and abs(t - float(at)) < 0.01)]


# --------------------------------------------------------------------------- timing (seconds)
# When a look has landed, from its first frame (the renderer's frames / 30): its entry, then its own move. A look
# whose parts land on their words (items[].at) lands when its last part has (LEG after its word).
LAND = {RANKING: 1.0, WATERLINE: 1.2, SEVERITY: 1.3, DELTA: 1.6, STREAK: 1.55, ALERT: 1.0, REGIONS: 1.0, ROUTE: 1.8,
        STORM: 2.2, TOTALS: 1.2}
LEG = {RANKING: 0.75, WATERLINE: 2.2, DELTA: 1.1, REGIONS: 0.7, ROUTE: 0.6, STORM: 0.6, TOTALS: 0.75}
# The hold once landed: long enough to read it (the owner: a graphic stays about two seconds after its word; a
# table of rows or a map a little longer to be read), then the 12-frame exit.
HOLD = {RANKING: 3.0, WATERLINE: 3.0, SEVERITY: 2.6, DELTA: 2.6, STREAK: 2.6, ALERT: 3.0, REGIONS: 2.8, ROUTE: 3.0,
        STORM: 3.0, TOTALS: 3.0}
WANT_EXTRA = 1.0            # what a look is planned for when the lane has room: its least time and this
FAMILY = {RANKING: "chart", WATERLINE: "chart", SEVERITY: "ring", DELTA: "compare", STREAK: "number", ALERT: "text",
          REGIONS: "map", ROUTE: "map", STORM: "map", TOTALS: "map"}


def _item_last(ov: dict) -> float:
    best = 0.0
    for it in ov.get("items") or []:
        try:
            best = max(best, float((it or {}).get("at") or 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
    return best


def landing_seconds(ov: dict) -> float:
    """When the look has landed, from its start (its last part's word plus that part's own move)."""
    tid = str(ov.get("template") or "")
    land = LAND.get(tid, 1.0)
    if tid in LEG:
        land = max(land, _item_last(ov) + LEG[tid])
    if tid == SEVERITY:
        try:
            land = max(land, (18 + 5 * max(0, int(float(ov.get("value") or 1)) - 1) + 12) / 30.0)
        except (TypeError, ValueError):
            pass
    return round(land, 3)


def min_seconds(ov: dict, exit_s: float = 0.4) -> float:
    tid = str(ov.get("template") or "")
    return round(landing_seconds(ov) + HOLD.get(tid, 2.6) + exit_s, 3)


# --------------------------------------------------------------------------- words
_NUM = r"\d[\d,]*(?:\.\d+)?"
_SPELLED_SMALL = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                            "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_SPELLED_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                 "ninety": 90}
_SPELLED_RX = r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?|" \
              r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|" \
              r"seventeen|eighteen|nineteen)"
_YEAR = r"(?:1[89]\d\d|20\d\d)"
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def number_of(s: str) -> Optional[float]:
    """'1,225' -> 1225.0, 'thirty-one' -> 31.0, '$4.5' -> 4.5; None when it is not a number."""
    t = (s or "").strip().lower().replace("$", "")
    if re.fullmatch(_NUM, t):
        try:
            return float(t.replace(",", ""))
        except ValueError:
            return None
    t = t.replace("-", " ")
    total = 0.0
    for w in t.split():
        if w in _SPELLED_TENS:
            total += _SPELLED_TENS[w]
        elif w in _SPELLED_SMALL:
            total += _SPELLED_SMALL[w]
        else:
            return None
    return total if t.split() else None


def _fmt(v: float):
    return int(v) if float(v).is_integer() else round(float(v), 3)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" ,.;:-–—")


def _cap(s: str) -> str:
    s = _clean(s)
    return s[:1].upper() + s[1:] if s else ""


_TAIL_SMALL = {"of", "the", "a", "an", "to", "for", "and", "in", "on", "its", "by", "that", "with", "from", "at", "is",
               "was", "as", "it", "their", "his", "her", "our", "than", "or", "but", "so"}


def _words_after(text: str, at: int, limit: int = 40) -> str:
    """The few words that follow `at` in its clause, never ending on a small word."""
    tail = re.split(r"[.;:!?,]|\s[-–—]\s", text[at:])[0]
    out = ""
    for w in tail.split()[:8]:
        cand = (out + " " + w).strip()
        if len(cand) > limit:
            break
        out = cand
    words = out.split()
    while words and words[-1].lower().strip(",.") in _TAIL_SMALL:
        words.pop()
    return " ".join(words)


# --------------------------------------------------------------------------- places named
US_STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
             "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
             "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
             "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
             "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas",
             "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"]
COUNTRIES = ["Mexico", "Canada", "Brazil", "Argentina", "Chile", "Peru", "Colombia", "Venezuela", "Cuba", "Haiti",
             "Jamaica", "Guatemala", "Honduras", "Nicaragua", "Panama", "Spain", "Portugal", "France", "Germany", "Italy",
             "Greece", "Turkey", "Egypt", "Libya", "Morocco", "Algeria", "Sudan", "Ethiopia", "Kenya", "Somalia", "Nigeria",
             "Niger", "Mali", "Chad", "South Africa", "Zimbabwe", "Zambia", "Iran", "Iraq", "Syria", "Jordan", "Israel",
             "Saudi Arabia", "Yemen", "Afghanistan", "Pakistan", "India", "Bangladesh", "Nepal", "China", "Mongolia",
             "Japan", "Vietnam", "Thailand", "Cambodia", "Laos", "Myanmar", "Philippines", "Indonesia", "Australia",
             "New Zealand", "Russia", "Ukraine", "Poland", "Kazakhstan", "Uzbekistan"]
_STATE_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(s) for s in US_STATES), key=len, reverse=True)) + r")\b")
_COUNTRY_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(s) for s in COUNTRIES), key=len, reverse=True)) + r")\b")
# A state's name that is part of another name, not the state: "Arizona Republic", "George Washington", "New York Times".
_NOT_STATE_AFTER = re.compile(r"^\s+(?:Republic|Times|Post|Department|Dept|University|State University|Test|Avenue|Street|"
                              r"Boulevard|Cardinals|Diamondbacks|Jazz|Rockies|Raiders|Suns|Coyotes|Wild|Nationals|Monthly|"
                              r"Public|Water|Power|Project|Highway|Route|Senator|Governor|Attorney|Supreme|Legislature)\b")
_NOT_STATE_BEFORE = re.compile(r"\b(?:George|President|Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Fort|Lake|Mount|University of|Gulf of|"
                               r"Sea of|Bank of)\s+$")
_LIST_GAP = re.compile(r"^\s*(?:,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+|\s*&\s*)$")


def states_listed(text: str, minimum: int = 3) -> List[Tuple[str, int, int]]:
    """
    The longest run of US states (else of countries) a text names as one list - "Wyoming, Colorado, Utah, New Mexico,
    Nevada, Arizona and California" - each with its place in the text; [] when it names fewer than `minimum`.
    """
    for rx in (_STATE_RX, _COUNTRY_RX):
        hits = []
        for m in rx.finditer(text or ""):
            if _NOT_STATE_AFTER.match(text[m.end():]) or _NOT_STATE_BEFORE.search(text[max(0, m.start() - 20):m.start()]):
                continue
            hits.append((m.group(1), m.start(), m.end()))
        best: List[Tuple[str, int, int]] = []
        run: List[Tuple[str, int, int]] = []
        for h in hits:
            if run and _LIST_GAP.match(text[run[-1][2]:h[1]]) and h[0] not in [x[0] for x in run]:
                run.append(h)
            else:
                run = [h]
            if len(run) > len(best):
                best = list(run)
        if len(best) >= minimum:
            return best[:12]
    return []


# --------------------------------------------------------------------------- the narration's moments
def _time(nar, char: int) -> float:
    return float(nar.time_at(char))


# A sentence ends at . ! ? - never inside "9 p.m.", "U.S.", "Dr.", "St.", "Mt." or "vs.", nor after a name's initial
# ("D. B. Cooper", "John F. Kennedy": looks pack 4).
_SENTENCE_END = re.compile(r"(?<!\b[ap]\.m)(?<!\bU\.S)(?<!\bDr)(?<!\bSt)(?<!\bMt)(?<!\bMr)(?<!\bMs)(?<!\bvs)(?<!\bFt)"
                           r"(?<!\b[A-Z])[.!?](?=\s|$)")


def _sentences(nar) -> List[Tuple[int, int]]:
    """Every sentence of the narration as (start, end) offsets."""
    text = nar.text
    out = []
    a = 0
    for m in _SENTENCE_END.finditer(text):
        b = m.end()
        if b - a > 2:
            out.append((a, b))
        a = b + 1
    if len(text) - a > 2:
        out.append((a, len(text)))
    return out


def _cand(tid: str, nar, a: int, b: int, props: dict, items_at: Optional[List[Optional[float]]] = None,
          score: float = 4.0, key: str = "", absorb: Optional[Tuple[int, int]] = None, at: Optional[float] = None) -> dict:
    at0 = _time(nar, a) if at is None else at
    return {"tid": tid, "a": a, "b": b, "at": at0, "end": float(nar.end_at(b)), "props": props,
            "items_at": items_at, "score": score, "key": key or f"{tid}:{nar.text[a:b][:60].lower()}",
            "absorb": absorb or (a, b), "said": _clean(nar.text[a:b])[:120]}


# ---- KT_RANKING ------------------------------------------------------------------------------------------------
_NAME = r"(?:[A-Z][a-z'’.-]+|[A-Z]{2,4})(?:\s+(?:[A-Z][a-z'’.-]+|of|de|del|la|el|los|las|St\.|Ft\.))*"
_NV = re.compile(
    rf"(?P<name>{_NAME})(?:['’]s)?\s*(?:,|:|\(|—|–)?\s*"
    r"(?:(?:got|had|saw|recorded|received|reported|picked\s+up|measured|hit|reached|topped|logged|came\s+in\s+at|"
    r"(?:is|was|sat|sits|stood|stands)\s+at|at|with|reaching|totaled|totalled|totaling|totalling)\s+)?"
    r"(?:(?:just|only|about|around|nearly|almost|over|more\s+than|under|less\s+than|roughly)\s+)?"
    rf"(?P<val>\$?{_NUM})(?P<scale>\s+(?:thousand|million|billion))?"
    r"(?P<unit>\s*(?:%|percent\b|inches\b|inch\b|in\.(?=\s)|feet\b|foot\b|ft\b|degrees\b|°|mph\b|miles\b|acre[\s-]feet\b|"
    r"people\b|homes\b|acres\b))?"
    r"(?P<of>\s+of\s+(?:rain|snow|rainfall|snowfall|water|precipitation)\b)?")
_NV_GAP = re.compile(r"^[\s,;]*(?:(?:and|while|then|with|followed\s+by|but|plus)\s+)?(?:(?:just|only)\s+)?$", re.I)
_NOT_NAME = {"The", "A", "An", "And", "But", "So", "Then", "That", "This", "It", "Its", "In", "On", "At", "By", "For",
             "From", "Of", "To", "Now", "Back", "Nearly", "About", "More", "Less", "Last", "Just", "Only", "Over", "Under",
             "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
             "Today", "Tonight", "Yesterday", "Some", "All", "Most", "Each", "Every", "One", "Two", "Three", "Four",
             "Five", "Six", "Seven", "Eight", "Nine", "Ten", "We", "They", "He", "She", "You", "I", "If", "When", "Where",
             "Why", "How", "What", "Who", "Up", "Down", "Around", "Roughly", "Almost", "Here", "There", "Meanwhile"}
_UNIT_WORDS = [(r"%|percent", "%"), (r"inches|inch|in\.", "IN"), (r"feet|foot|ft", "FT"), (r"degrees|°", "°"),
               (r"mph", "MPH"), (r"miles", "MI"), (r"acre[\s-]feet", "ACRE-FT"), (r"people", "PEOPLE"),
               (r"homes", "HOMES"), (r"acres", "ACRES")]
_ASCENDING = re.compile(r"\b(driest|lowest|least|fewest|smallest|coldest|shallowest|cheapest|shortest|slowest|"
                        r"emptiest|lowest-?lying)\b", re.I)
_SUPERLATIVE_TITLE = re.compile(r"\b(?:the\s+)?(?:(?:top|(?:three|four|five|six|3|4|5|6))\s+)?"
                                r"((?:\w+est|largest|biggest|most\s+\w+|least\s+\w+)\s+(?:\w+\s+){0,1}?"
                                r"(?:cities|towns|states|counties|places|reservoirs|lakes|rivers|countries|areas|spots|"
                                r"years|months|days|users|basins|dams))\b", re.I)


def _unit_short(raw: str) -> str:
    r = (raw or "").strip().lower()
    for rx, short in _UNIT_WORDS:
        if r and re.fullmatch(rx, r):
            return short
    return ""


def _named_values(sentence: str) -> List[dict]:
    """Every 'Name ... value [unit]' in a sentence, in order."""
    out = []
    for m in _NV.finditer(sentence):
        name = m.group("name").strip().rstrip(".,;:")
        first = name.split()[0]
        if first in _NOT_NAME or name in _NOT_NAME or re.fullmatch(_YEAR, m.group("val").replace(",", "")):
            continue
        if re.fullmatch(r"(?:Lake|River|Mount|Fort|San|Santa|Las|Los|New|North|South|East|West)", name):
            continue
        v = number_of(m.group("val"))
        if v is None:
            continue
        v *= _SCALE.get((m.group("scale") or "").strip().lower(), 1.0)
        out.append({"name": name, "value": v, "unit": _unit_short(m.group("unit") or ""), "a": m.start("name"),
                    "b": m.end(), "va": m.start("val")})
    return out


def _ranking_runs(sentence: str) -> List[List[dict]]:
    """Runs of 3-6 named values said one after another (only separators between them), one unit, distinct names."""
    vals = _named_values(sentence)
    runs: List[List[dict]] = []
    run: List[dict] = []
    for v in vals:
        if run and _NV_GAP.match(sentence[run[-1]["b"]:v["a"]]) and v["name"] not in [x["name"] for x in run] \
                and (not v["unit"] or not run[0]["unit"] or v["unit"] == run[0]["unit"]):
            run.append(v)
        else:
            if len(run) >= 3:
                runs.append(run)
            run = [v]
    if len(run) >= 3:
        runs.append(run)
    return [r[:6] for r in runs]


_TOP_LIST = re.compile(r"\b(?:the\s+)?(?P<n>three|four|five|six|3|4|5|6|top)\s+(?P<what>(?:\w+\s+){0,2}?(?:\w+est|largest|"
                       r"biggest|most\s+\w+)(?:\s+\w+){0,4}?)\s*(?:\s(?:are|were|include|included)\s+|:\s*)", re.I)


def find_rankings(nar) -> List[dict]:
    out = []
    text = nar.text
    for s0, s1 in _sentences(nar):
        sent = text[s0:s1]
        for run in _ranking_runs(sent):
            unit = next((v["unit"] for v in run if v["unit"]), "")
            asc = bool(_ASCENDING.search(sent[:max(0, run[0]["a"])] or sent))
            ordered = sorted(run, key=lambda v: (v["value"] if asc else -v["value"]))
            a, b = s0 + run[0]["a"], s0 + run[-1]["b"]
            t0 = _time(nar, a) - 0.07
            title_m = _SUPERLATIVE_TITLE.search(sent)
            title = _cap(title_m.group(1)) if title_m else ""
            # the unit line as said with the first figure that has one ("inches of rain")
            unit_v = next((v for v in run if v["unit"]), None)
            sub = ""
            if unit_v and unit in ("IN", "FT", "°", "MPH", "MI", "ACRE-FT"):
                said_unit = sent[unit_v["va"]:unit_v["b"]].split(None, 1)
                sub = _cap(said_unit[1]) if len(said_unit) > 1 else ""
            items, ats = [], []
            for v in ordered:
                at = _time(nar, s0 + v["a"])
                items.append({"label": v["name"], "value": _fmt(v["value"]), "at": round(max(0.0, at - t0), 2)})
                ats.append(at)
            props = {"template": RANKING, "text": title, "subtitle": sub, "items": items,
                     "suffix": "" if unit in ("%",) else unit, **({"suffix": "%"} if unit == "%" else {})}
            out.append(_cand(RANKING, nar, a, b, props, ats, score=4.5 + 0.3 * len(run),
                             key="rk:" + "|".join(sorted(v["name"].lower() for v in run))))
        # a ranked list of names, said in its order: "the five driest cities are Yuma, Las Vegas, ..."
        for m in _TOP_LIST.finditer(sent):
            rest = sent[m.end():]
            names = []
            pos = m.end()
            for nm in re.finditer(rf"({_NAME})", rest):
                gap = rest[names[-1][2] - m.end():nm.start()] if names else rest[:nm.start()]
                if names and not _LIST_GAP.match(gap):
                    break
                if not names and gap.strip():
                    break
                if nm.group(1).split()[0] in _NOT_NAME:
                    break
                name = nm.group(1).rstrip(".,;:")
                names.append((name, m.end() + nm.start(), m.end() + nm.start() + len(name)))
                pos = m.end() + nm.end()
            if not 3 <= len(names) <= 6:
                continue
            want = number_of(m.group("n")) if m.group("n").lower() != "top" else None
            if want and int(want) != len(names):
                continue
            a, b = s0 + m.start(), s0 + pos
            t0 = _time(nar, s0 + names[0][1]) - 0.07
            ats = [_time(nar, s0 + x[1]) for x in names]
            items = [{"label": x[0], "at": round(max(0.0, t - t0), 2)} for x, t in zip(names, ats)]
            props = {"template": RANKING, "text": _cap(m.group("what")), "items": items}
            out.append(_cand(RANKING, nar, s0 + names[0][1], b, props, ats, score=4.0,
                             key="rk:" + "|".join(sorted(x[0].lower() for x in names)), absorb=(a, b)))
    return out


# ---- KT_WATERLINE ----------------------------------------------------------------------------------------------
_LAKE_NAME = re.compile(r"\b(Lake\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[A-Z][a-z]+\s+(?:Lake|Reservoir))\b")
_LAKE_WORDS = re.compile(r"\b(lake|lakes|reservoir|reservoirs|water level|water levels|surface elevation|elevation|"
                         r"above sea level|full pool|dead pool|bathtub ring|high[- ]water mark|waterline|shoreline)\b", re.I)
_FEET_YEAR = re.compile(rf"(?P<v>{_NUM})\s+(?:feet|foot|ft)\b(?:\s+above\s+sea\s+level)?(?P<mid>[^.;]{{0,26}}?)\b(?:in|by|of)\s+(?P<y>{_YEAR})\b"
                        rf"|\b(?:in|by)\s+(?P<y2>{_YEAR})\b(?P<mid2>[^.;]{{0,48}}?)(?P<v2>{_NUM})\s+(?:feet|foot|ft)\b", re.I)
_DROP_SINCE = re.compile(rf"\b(?P<verb>dropped|fallen|fell|declined|sunk|sank|lost|is\s+down|has\s+dropped|has\s+fallen|"
                         rf"down)\s+(?:by\s+)?(?:(?:more\s+than|nearly|almost|about|over|roughly)\s+)?(?P<v>{_NUM}|{_SPELLED_RX})"
                         rf"\s+(?:feet|foot|ft)\b(?P<mid>[^.;]{{0,30}}?)\bsince\s+(?P<y>{_YEAR})\b", re.I)


def find_waterlines(nar) -> List[dict]:
    out = []
    text = nar.text
    sents = _sentences(nar)
    for i, (s0, s1) in enumerate(sents):
        # the sentence and the next one (a level and the next year's are often said a sentence apart)
        w1 = sents[i + 1][1] if i + 1 < len(sents) and _time(nar, sents[i + 1][0]) - _time(nar, s0) < 15.0 else s1
        win = text[s0:w1]
        if not _LAKE_WORDS.search(win):
            continue
        name_m = _LAKE_NAME.search(win) or _LAKE_NAME.search(text[sents[i - 1][0]:s0] if i else "")
        lake = name_m.group(1) if name_m else ""
        sea = bool(re.search(r"above\s+sea\s+level", win, re.I))
        pairs = []
        for m in _FEET_YEAR.finditer(win):
            v = number_of(m.group("v") or m.group("v2"))
            y = int(m.group("y") or m.group("y2"))
            if v is None or v < 200:
                continue
            va = s0 + (m.start("v") if m.group("v") else m.start("v2"))
            if all(p["year"] != y for p in pairs):
                pairs.append({"year": y, "value": v, "at": _time(nar, va), "a": s0 + m.start(), "b": s0 + m.end()})
        if len(pairs) >= 2:
            pairs = sorted(pairs, key=lambda p: p["year"])[-4:]
            if pairs[0]["value"] != pairs[-1]["value"] and pairs[0]["a"] < s1:
                t0 = min(p["at"] for p in pairs) - 0.07
                items = [{"label": str(p["year"]), "value": _fmt(p["value"]), "at": round(max(0.0, p["at"] - t0), 2)}
                         for p in pairs]
                a, b = min(p["a"] for p in pairs), max(p["b"] for p in pairs)
                props = {"template": WATERLINE, "text": lake, "subtitle": "Feet above sea level" if sea else "", "suffix": "FT",
                         "items": items}
                out.append(_cand(WATERLINE, nar, a, b, props, [p["at"] for p in pairs], score=6.0,
                                 key="wl:" + "|".join(str(p["year"]) for p in pairs), at=t0 + 0.07))
                continue
        m = _DROP_SINCE.search(text[s0:s1])
        if m:
            v = number_of(m.group("v"))
            if v and 1 <= v <= 1000:
                a, b = s0 + m.start(), s0 + m.end()
                now = "Today" if re.search(r"\btoday\b", text[s0:s1], re.I) else "Now"
                y = m.group("y")
                ya = _time(nar, s0 + m.start("y"))
                t0 = _time(nar, a) - 0.07
                props = {"template": WATERLINE, "text": lake, "subtitle": "Feet above sea level" if sea else "",
                         "suffix": "FT", "value": _fmt(v),
                         "items": [{"label": y}, {"label": now, "at": round(max(0.0, ya - t0) + 0.4, 2)}]}
                out.append(_cand(WATERLINE, nar, a, b, props, [None, ya + 0.4], score=5.5, key=f"wl:drop:{y}:{_fmt(v)}"))
    return out


# ---- KT_DELTA --------------------------------------------------------------------------------------------------
_CHANGE_VERB = r"(?:fell|fallen|dropped|declined|decreased|shrank|shrunk|plunged|plummeted|sank|sunk|slid|tumbled|rose|risen|" \
               r"climbed|grew|grown|increased|jumped|surged|soared|swelled|went\s+up|went\s+down|went|shot\s+up|doubled|" \
               r"tripled)"
_FIG = rf"(?:\$\s?)?{_NUM}(?:\s+(?:thousand|million|billion))?"
_UNIT_RX = r"(?:%|percent\b|feet\b|foot\b|ft\b|inches\b|degrees\b|°|miles\b|acre[\s-]feet\b|people\b|homes\b|dollars\b|" \
           r"gallons\b|cfs\b|cubic\s+feet\s+per\s+second\b|acres\b)"
_FROM_TO = re.compile(
    rf"\b(?P<verb>{_CHANGE_VERB})\b(?:\s+[\w'’]+){{0,4}}?\s+from\s+(?:(?:about|nearly|almost|more\s+than|over|roughly|around)\s+)?"
    rf"(?P<a>{_FIG})(?:\s*(?P<ua>{_UNIT_RX}))?(?:\s+(?:in|back\s+in)\s+(?P<ya>{_YEAR}))?\s*,?\s*(?:(?:down|up)\s+)?to\s+"
    rf"(?:(?:about|nearly|almost|just|only|under|over|less\s+than|more\s+than|roughly|around|barely)\s+)?(?P<b>{_FIG})"
    rf"(?:\s*(?P<ub>{_UNIT_RX}))?(?:\s+(?:in|by)\s+(?P<yb>{_YEAR}))?", re.I)
_SINCE = re.compile(
    rf"\b(?P<verb>{_CHANGE_VERB}|(?:is|are|was|were|has\s+been|have\s+been)\s+(?:down|up)|down|up)\s+(?:by\s+)?"
    rf"(?:(?:about|nearly|almost|more\s+than|over|roughly|around)\s+)?(?P<v>{_NUM})\s*(?P<u>%|percent\b)"
    rf"(?P<mid>[^.;]{{0,24}}?)\bsince\s+(?P<y>{_YEAR})\b", re.I)
_DOWN = re.compile(r"\b(fell|fallen|dropped|declined|decreased|shrank|shrunk|plunged|plummeted|sank|sunk|slid|tumbled|down|"
                   r"went\s+down)\b", re.I)
_PROPER_SUBJ = re.compile(r"\b((?:[A-Z][a-z'’]+)(?:\s+(?:[A-Z][a-z'’]+|River|Lake|of)){0,3})")


def _subject_before(text: str, s0: int, at: int) -> str:
    head = re.split(r"[;:,]|\b(?:and|but|while|then)\b", text[s0:at])[-1]
    # (a name never ends on its "of": "Shares of the company rose ..." is about the shares)
    found = [re.sub(r"\s+of$", "", m.group(1)) for m in _PROPER_SUBJ.finditer(head) if m.group(1).split()[0] not in _NOT_NAME]
    return found[-1] if found and len(found[-1]) <= 32 else ""


def find_deltas(nar) -> List[dict]:
    out = []
    text = nar.text
    for s0, s1 in _sentences(nar):
        sent = text[s0:s1]
        for m in _FROM_TO.finditer(sent):
            if re.fullmatch(_YEAR, m.group("a").replace(",", "")):
                continue
            # "from 18 million to 12 million", "from 18 to 12 million": the figures as said with their scale letter
            sa = re.search(r"\b(thousand|million|billion)\b", m.group("a"), re.I)
            sb = re.search(r"\b(thousand|million|billion)\b", m.group("b"), re.I)
            scale_w = (sb or sa).group(1).lower() if (sa or sb) else ""
            a_v = number_of(re.match(rf"(?:\$\s?)?({_NUM})", m.group("a").strip()).group(1))
            b_v = number_of(re.match(rf"(?:\$\s?)?({_NUM})", m.group("b").strip()).group(1))
            if a_v is None or b_v is None or a_v == b_v:
                continue
            unit = _unit_short(m.group("ua") or m.group("ub") or "")
            money = bool(re.search(r"\$", m.group("a") + m.group("b"))) or bool(re.search(r"\bdollars\b", m.group("ub") or "", re.I))
            if unit == "FT" and _LAKE_WORDS.search(sent) and (a_v >= 200 or b_v >= 200):
                continue                        # a lake's level: its waterline (find_waterlines)
            a, b = s0 + m.start(), s0 + m.end()
            t_b = _time(nar, s0 + m.start("b"))
            t0 = _time(nar, s0 + m.start("a")) - 0.07
            letter = {"thousand": "K", "million": "M", "billion": "B"}.get(scale_w, "")
            if letter:
                suffix = letter                 # "18M" -> "12M"; the unit word rides in the context line
            else:
                suffix = "" if unit in ("$", "") else unit
            ctx = _words_after(text, b, 40)
            if letter and unit and not ctx:
                said_unit = (m.group("ub") or m.group("ua") or "").strip()
                ctx = f"{scale_w} {said_unit}"
            props = {"template": DELTA, "text": _subject_before(text, s0, s0 + m.start()),
                     "subtitle": _cap(ctx),
                     "items": [{"label": m.group("ya") or "", "value": _fmt(a_v)},
                               {"label": m.group("yb") or "", "value": _fmt(b_v), "at": round(max(0.0, t_b - t0), 2)}],
                     "suffix": suffix, **({"prefix": "$"} if money else {})}
            out.append(_cand(DELTA, nar, s0 + m.start("a"), b, props, [None, t_b], score=5.0,
                             key=f"dl:{_fmt(a_v)}:{_fmt(b_v)}", absorb=(a, b), at=t0 + 0.07))
        for m in _SINCE.finditer(sent):
            v = number_of(m.group("v"))
            if v is None or v <= 0 or v > 100:
                continue
            down = bool(_DOWN.search(m.group("verb")))
            a, b = s0 + m.start(), s0 + m.end()
            props = {"template": DELTA, "text": _subject_before(text, s0, a), "value": _fmt(-v if down else v),
                     "suffix": "%", "label": f"Since {m.group('y')}", "subtitle": _cap(_words_after(text, b, 40))}
            out.append(_cand(DELTA, nar, s0 + m.start("v"), b, props, None, score=4.5, key=f"dl:since:{m.group('y')}:{_fmt(v)}",
                             absorb=(a, b)))
    return out


# ---- KT_STREAK -------------------------------------------------------------------------------------------------
_STREAK = re.compile(
    rf"\b(?P<n>\d{{1,3}}|{_SPELLED_RX})\s+(?P<q>straight|consecutive)\s+days?\b"
    rf"|\b(?P<n2>\d{{1,3}}|{_SPELLED_RX})\s+days?\s+(?P<q2>in\s+a\s+row)\b"
    rf"|\b(?P<n3>\d{{1,3}}|{_SPELLED_RX})\s+(?:straight\s+)?days?\s+(?P<q3>without(?:\s+(?:a\s+drop\s+of|any|measurable|significant))?\s+\w+)"
    rf"|\bthe\s+(?P<n4>\d{{1,3}})(?:st|nd|rd|th)\s+(?P<q4>straight|consecutive)\s+day\b", re.I)


def find_streaks(nar) -> List[dict]:
    out = []
    text = nar.text
    for m in _STREAK.finditer(text):
        raw = m.group("n") or m.group("n2") or m.group("n3") or m.group("n4")
        v = number_of(raw)
        if v is None or not 2 <= v <= 371:
            continue
        q = m.group("q") or m.group("q2") or m.group("q3") or m.group("q4") or ""
        # "31 straight days" reads IN A ROW over the figure (STRAIGHT alone is not a heading); the others as said
        kicker = "In a row" if q.lower() == "straight" else _cap(q)
        ctx = _words_after(text, m.end(), 40)
        # the words after it are its context line: a figure in them ("above 110 degrees") is shown there, not again
        tail = text.find(ctx, m.end()) if ctx else -1
        end = tail + len(ctx) if tail >= 0 else m.end()
        props = {"template": STREAK, "value": int(v), "suffix": "days", "text": kicker, "subtitle": _cap(ctx)}
        out.append(_cand(STREAK, nar, m.start(), m.end(), props, None, score=5.0, key=f"st:{int(v)}:{q.lower()}",
                         absorb=(m.start(), end)))
    return out


# ---- KT_SEVERITY -----------------------------------------------------------------------------------------------
_CAT = re.compile(rf"\bcategory[\s-](?P<n>[1-5]|one|two|three|four|five)\b", re.I)
_EF = re.compile(r"\b(?:an?\s+)?EF[\s-]?(?P<n>[0-5])\b")
_DCODE = re.compile(r"\b(?P<d>D[0-4])\b")
_DWORDS = re.compile(r"\b(?P<w>abnormally\s+dry|moderate\s+drought|severe\s+drought|extreme\s+drought|exceptional\s+drought)\b", re.I)
_TIER = re.compile(r"\btier\s+(?P<n>zero|one|two|three|0|1|2|3)(?P<ab>\s?[ab])?\b(?=[^.]{0,40}\bshortage)|\b(?P<n2>zero|one|two|three|0|1|2|3)"
                   r"(?P<ab2>[ab])?\s+shortage\b", re.I)
_LEVEL_OF = re.compile(rf"\b(?P<what>level|stage|tier|category)\s+(?P<n>\d|{_SPELLED_RX})\s+(?:of|out\s+of)\s+"
                       rf"(?P<m>\d|{_SPELLED_RX})\b", re.I)
_D_NAMES = ["Abnormally dry", "Moderate drought", "Severe drought", "Extreme drought", "Exceptional drought"]
_WIND = re.compile(rf"\b(?:winds?\s+(?:of\s+|up\s+to\s+|near\s+|topping\s+)?)?(?P<v>\d{{2,3}})\s*(?:mph|miles\s+(?:per|an)\s+hour)\b"
                   r"(?:\s+winds?)?", re.I)


def find_scales(nar) -> List[dict]:
    out = []
    text = nar.text
    for s0, s1 in _sentences(nar):
        sent = text[s0:s1]
        m = _CAT.search(sent)
        if m and re.search(r"\b(hurricane|storm|typhoon|cyclone)\b", sent, re.I):
            n = int(number_of(m.group("n")) or 0)
            wind = _WIND.search(sent)
            props = {"template": SEVERITY, "text": f"Category {n}", "value": n, "total": 5,
                     "label": "Hurricane" if re.search(r"\bhurricane\b", sent, re.I) else "Storm",
                     "subtitle": _cap(wind.group(0)) if wind else "",
                     "items": [{"label": str(i)} for i in range(1, 6)]}
            out.append(_cand(SEVERITY, nar, s0 + m.start(), s0 + m.end(), props, None, score=5.0, key=f"sv:cat:{n}"))
            continue
        m = _EF.search(sent)
        if m and re.search(r"\btornado", sent, re.I):
            n = int(m.group("n"))
            props = {"template": SEVERITY, "text": f"EF{n}", "value": n + 1, "total": 6, "label": "Tornado",
                     "subtitle": _cap(_WIND.search(sent).group(0)) if _WIND.search(sent) else "",
                     "items": [{"label": f"EF{i}"} for i in range(6)]}
            out.append(_cand(SEVERITY, nar, s0 + m.start(), s0 + m.end(), props, None, score=5.0, key=f"sv:ef:{n}"))
            continue
        md, mw = _DCODE.search(sent), _DWORDS.search(sent)
        if (md and re.search(r"\bdrought\b", sent, re.I)) or mw:
            if md:
                n = int(md.group("d")[1])
                text_l, at_m = md.group("d"), md
            else:
                n = [x.lower() for x in _D_NAMES].index(re.sub(r"\s+", " ", mw.group("w").lower()))
                text_l, at_m = _D_NAMES[n], mw
            props = {"template": SEVERITY, "text": text_l, "value": n + 1, "total": 5, "label": "Drought monitor"
                     if re.search(r"drought\s+monitor", sent, re.I) else "Drought",
                     "subtitle": _D_NAMES[n] if md else "", "items": [{"label": f"D{i}"} for i in range(5)]}
            out.append(_cand(SEVERITY, nar, s0 + at_m.start(), s0 + at_m.end(), props, None, score=4.5, key=f"sv:d:{n}"))
            continue
        m = _TIER.search(sent)
        if m:
            n = int(number_of(m.group("n") or m.group("n2")) or 0)
            ab = (m.group("ab") or m.group("ab2") or "").strip().lower()
            levels = ["Tier 0", "Tier 1", "Tier 2a", "Tier 2b", "Tier 3"]
            idx = {0: 0, 1: 1, 2: 3 if ab == "b" else 2, 3: 4}[n]
            props = {"template": SEVERITY, "text": f"Tier {n}{ab}", "value": idx + 1, "total": 5, "label": "Shortage",
                     "subtitle": "", "items": [{"label": x} for x in levels]}
            out.append(_cand(SEVERITY, nar, s0 + m.start(), s0 + m.end(), props, None, score=5.0, key=f"sv:tier:{n}{ab}"))
            continue
        m = _LEVEL_OF.search(sent)
        if m:
            n, tot = number_of(m.group("n")), number_of(m.group("m"))
            if n and tot and 2 <= tot <= 8 and 1 <= n <= tot:
                what = m.group("what").capitalize()
                after = _words_after(text, s0 + m.end(), 36)
                props = {"template": SEVERITY, "text": f"{what} {int(n)} of {int(tot)}", "value": int(n), "total": int(tot),
                         "label": "", "subtitle": _cap(after) if re.match(r"(?:risk|threat|alert|warning|restrictions?|"
                                                                          r"of\b)", after, re.I) else "",
                         "items": [{"label": str(i)} for i in range(1, int(tot) + 1)]}
                out.append(_cand(SEVERITY, nar, s0 + m.start(), s0 + m.end(), props, None, score=4.5,
                                 key=f"sv:lv:{int(n)}:{int(tot)}"))
    return out


# ---- KT_ALERT --------------------------------------------------------------------------------------------------
_ALERT = re.compile(
    r"\b(?P<name>(?:flash\s+flood|coastal\s+flood|areal\s+flood|flood|excessive\s+heat|extreme\s+heat|heat|red\s+flag|"
    r"fire\s+weather|winter\s+storm|blizzard|ice\s+storm|hard\s+freeze|freeze|frost|high\s+wind|wind|dust\s+storm|"
    r"tornado|severe\s+thunderstorm|hurricane|tropical\s+storm|storm\s+surge|tsunami|air\s+quality|wind\s+chill|"
    r"extreme\s+cold|special\s+weather)\s+(?:warnings?|watch(?:es)?|advisor(?:y|ies)|emergency|statement)"
    r"|evacuation\s+orders?|evacuation\s+warnings?|boil[\s-]water\s+(?:notice|advisory|order)|state\s+of\s+emergency|"
    r"drought\s+emergency|water\s+emergency)\b", re.I)
_UNTIL = re.compile(r"\buntil\s+(?P<t>(?:\d{1,2}(?::\d\d)?\s*(?:a\.?m\.?|p\.?m\.?)|noon|midnight|tonight|tomorrow(?:\s+morning|\s+night|"
                    r"\s+evening)?|this\s+(?:morning|afternoon|evening)|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                    r"(?:\s+(?:morning|afternoon|evening|night))?))", re.I)
_AREA = re.compile(r"\b(?:for|in|across|covering|over)\s+(?:(?:all\s+of|parts\s+of|much\s+of|most\s+of)\s+)?(?:the\s+)?"
                   r"(?P<a>(?:[A-Z][a-z'’.-]+)(?:\s+[A-Z][a-z'’.-]+){0,2}\s+(?:County|Counties|Parish|Valley|Metro|Basin|Coast)|"
                   r"(?:[A-Z][a-z'’.-]+)(?:\s+[A-Z][a-z'’.-]+){0,2}(?:,\s+[A-Z][a-z]+)?)")
_ISSUER = re.compile(r"\b(National\s+Weather\s+Service|NWS|National\s+Hurricane\s+Center|Storm\s+Prediction\s+Center|"
                     r"Weather\s+Prediction\s+Center|FEMA|Cal\s+Fire|CAL\s+FIRE)\b")


def _clock_label(t: str) -> str:
    t = re.sub(r"\s+", " ", t.strip())
    m = re.match(r"(\d{1,2})(?::(\d\d))?\s*([ap])\.?m\.?", t, re.I)
    if m:
        return f"{int(m.group(1))}{':' + m.group(2) if m.group(2) else ''} {m.group(3).upper()}M"
    return t[:1].upper() + t[1:].lower()


def find_alerts(nar) -> List[dict]:
    out = []
    text = nar.text
    for s0, s1 in _sentences(nar):
        sent = text[s0:s1]
        m = _ALERT.search(sent)
        if not m:
            continue
        name = re.sub(r"\s+", " ", m.group("name")).strip()
        name = " ".join(w[:1].upper() + w[1:].lower() for w in name.split())
        name = re.sub(r"\b(Warnings|Watches|Advisories|Orders)\b", lambda x: {"Warnings": "Warning", "Watches": "Watch",
                                                                               "Advisories": "Advisory", "Orders": "Orders"}[x.group(1)], name)
        parts = []
        until = _UNTIL.search(sent, m.end())
        if until:
            parts.append(f"Until {_clock_label(until.group('t'))}")
        area = _AREA.search(sent, m.end())
        if area and area.group("a").split()[0] not in _NOT_NAME:
            parts.append(area.group("a").strip(" ,"))
        issuer = _ISSUER.search(sent)
        props = {"template": ALERT, "text": name, "subtitle": " · ".join(parts),
                 "label": re.sub(r"\s+", " ", issuer.group(1)) if issuer else "Alert"}
        b = max([m.end()] + ([until.end()] if until else []) + ([area.end()] if area else []))
        out.append(_cand(ALERT, nar, s0 + m.start(), s0 + b, props, None, score=5.0, key=f"al:{name.lower()}",
                         absorb=(s0 + m.start(), s0 + b)))
    return out


# ---- KT_REGIONS ------------------------------------------------------------------------------------------------
_TITLE_NAME = re.compile(r"\b((?:the\s+)?(?:[A-Z][a-z]+\s+){1,3}(?:River\s+Basin|River|Basin|Compact|Valley|Plains|Desert|"
                         r"Southwest|Midwest|Northeast|Southeast|Gulf\s+Coast|Coast|Region))\b")


def find_regions(nar) -> List[dict]:
    out = []
    text = nar.text
    for s0, s1 in _sentences(nar):
        sent = text[s0:s1]
        listed = states_listed(sent, 3)
        if not listed:
            continue
        t0 = _time(nar, s0 + listed[0][1]) - 0.07
        ats = [_time(nar, s0 + x[1]) for x in listed]
        items = [{"label": x[0], "at": round(max(0.0, t - t0), 2)} for x, t in zip(listed, ats)]
        tm = _TITLE_NAME.search(sent)
        title = re.sub(r"^the\s+", "", tm.group(1)).strip() if tm else ""
        if title and (any(title == x[0] for x in listed) or tm.start() >= listed[0][1]):
            title = ""                          # a state's own name, or words inside the list, is no title
        props = {"template": REGIONS, "text": title[:32], "items": items}
        a, b = s0 + listed[0][1], s0 + listed[-1][2]
        out.append(_cand(REGIONS, nar, a, b, props, ats, score=4.5, key="rg:" + "|".join(x[0].lower() for x in listed)))
    return out


FINDERS = (find_waterlines, find_rankings, find_deltas, find_streaks, find_scales, find_alerts, find_regions)


def find(nar, allowed: Optional[frozenset] = None, ok: Optional[Callable[[str], bool]] = None,
         skip: Sequence[Tuple[float, float]] = (), pace: Optional[Pace] = None) -> Tuple[List[dict], List[dict]]:
    """
    The pack's data moments of the narration (a datalooks.Narration), each one its look's props and the span of
    words it covers (`absorb`: the figures it shows are not shown again by the data planner) - spaced (Pace),
    never two over the same words, only looks the brand kit allows (`allowed`) and the planner may pick (`ok`),
    none in a `skip` span (the presenter on camera). Returns (accepted, log rows of the ones left out).
    """
    cands: List[dict] = []
    for fn in FINDERS:
        try:
            cands.extend(fn(nar))
        except Exception as e:  # noqa: BLE001 - a rule's bug must never cost the other looks
            print(f"[lookpack3] {fn.__name__} failed: {type(e).__name__}: {e}", flush=True)
    # (two rules over the same words: the more specific first - a lake's levels before a change, a ranking before)
    rank = {WATERLINE: 0, RANKING: 1, DELTA: 2, STREAK: 3, SEVERITY: 4, ALERT: 5, REGIONS: 6}
    cands.sort(key=lambda c: (c["at"], rank.get(c["tid"], 9)))
    pace = pace or Pace()
    taken: List[Tuple[int, int]] = []
    seen: Dict[str, float] = {}
    out, log = [], []
    for c in cands:
        why = ""
        if allowed is not None and c["tid"] not in allowed:
            why = "the brand kit does not allow this look"
        elif ok is not None and not ok(c["tid"]):
            why = "not picked automatically"
        elif any(a <= c["at"] < b for a, b in skip):
            why = "the presenter says it on camera"
        elif any(not (c["absorb"][1] <= x or c["absorb"][0] >= y) for x, y in taken):
            why = "its words are another pack-3 look's"
        elif c["key"] in seen and c["at"] - seen[c["key"]] < REPEAT:
            why = f"shown {c['at'] - seen[c['key']]:.0f} s before"
        elif not pace.allows(c["tid"], c["at"]):
            why = "the pack's spacing (one every 24 s, two a minute, each look its own gap)"
        if why:
            log.append({"at": round(c["at"], 2), "said": c["said"], "kind": c["tid"], "look": None, "why": why})
            continue
        pace.note(c["tid"], c["at"])
        taken.append(c["absorb"])
        seen[c["key"]] = c["at"]
        out.append(c)
    return out, log


# --------------------------------------------------------------------------- the maps: an older map look upgraded
# Map looks of the plan whose places a pack-3 map can take over (the planner's older route, distance and several-place
# maps). The premium map path (LIB_PR_MAP_PATH) and the pack's own maps stay as they are, except that a storm's line
# turns any of them into the storm track.
OLD_ROUTES = frozenset({"MAP_ROUTE_SAT_V1", "MAP_ROUTE_DARK_V1", "MAP_ROUTE_PAPER_V1", "MAP_TRACE_V1", "MAP_DISTANCE_V1",
                        "LIB_MV_ARC_FLIGHT", "LIB_MX_ROUTE_DRAW", "LIB_MX_MEASURE_LINE"})
OLD_MANY = frozenset({"MAP_SPREAD_V1", "MAP_SPREAD_DARK_V1", "LIB_MV_PINBOARD_LIST", "LIB_MV_CHOROPLETH_LIFT",
                      "LIB_MX_PATH_TRACE", "LIB_MV_RIVER_DRAW"})
STORM_ONLY = frozenset({"LIB_PR_MAP_PATH", "KT_TWO_PLACES", "KT_ROUTE"})
_STORM_LINE = re.compile(r"\b(hurricane|tropical\s+storm|tropical\s+depression|the\s+storm|this\s+storm|the\s+system|"
                         r"storm\s+system|cyclone|typhoon|nor'?easter|derecho|the\s+front|cold\s+front|the\s+low)\b", re.I)
_STORM_MOVE = re.compile(r"\b(made\s+landfall|landfall|moved?|moving|moves|tracked|tracking|tracks|headed|heading|heads|"
                         r"pushed|pushing|pushes|swept|sweeping|sweeps|crossed|crossing|crosses|marched|churned|churning|"
                         r"barreled|slammed|plowed|turned\s+north|turned|drifted|stalled\s+over|reached|reaches|"
                         r"reaching|toward|towards|into|through|across|over)\b", re.I)
_ROUTE_LINE = re.compile(r"\b((?i:from)\s+[A-Z][\w'’.-]+[^.]{0,80}?\b(?i:to)\s+[A-Z]|(?i:flows?|flowing|flowed|runs?\s+(?:on\s+)?"
                         r"(?:from|through|down|to|into)|carries|carried|carry|pipes?|piped|pipelines?|canals?|aqueducts?|"
                         r"downstream|upstream|route|journey|drive|drove|travel(?:s|ed|led|ing)?|trucks?|ships?|shipped|"
                         r"miles\s+(?:to|from|away|long|south|north|east|west)|winds?\s+(?:its\s+way\s+)?through))\b")
_TIME_WORDS = re.compile(r"\b(?:(?:by|on|at|around)\s+)?(?P<t>(?:(?:early|late)\s+)?(?:\d{1,2}(?::\d\d)?\s*(?:a\.?m\.?|p\.?m\.?)|"
                         r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:morning|afternoon|evening|night))?|"
                         r"(?:this|that|tomorrow|the\s+next)\s+(?:morning|afternoon|evening|night)|tonight|midnight|noon|"
                         r"(?:morning|afternoon|evening)|overnight))\b", re.I)


def _name_of(label: str) -> str:
    return str(label or "").split(",")[0].strip()


def _first_at(text: str, name: str, start: int = 0) -> int:
    """Where `name` (or its first word) is said in `text` from `start`, -1 when it is not."""
    if not name:
        return -1
    m = re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text[start:])
    if m:
        return start + m.start()
    head = name.split()[0]
    if len(head) >= 4:
        m = re.search(r"(?<![\w])" + re.escape(head) + r"(?![\w])", text[start:])
        if m:
            return start + m.start()
    return -1


def _storm_time(text: str, at: int, until: int = -1) -> str:
    """
    The time said with a place in a storm's line ('by Tuesday night', 'at 4 a.m.'), as a chip label, or '': in the
    words after the place up to the next place (`until`) or the sentence's end, else just before it in its clause.
    """
    end = until if until > at else at + 70
    clause = re.sub(r"\b([ap])\.m\.", r"\1m", text[at:min(end, at + 70)], flags=re.I)
    clause = re.split(r"[.;]", clause)[0]
    before = re.sub(r"\b([ap])\.m\.", r"\1m", text[max(0, at - 40):at], flags=re.I)
    m = _TIME_WORDS.search(clause) or (_TIME_WORDS.search(re.split(r"[.;,]", before)[-1]) if before else None)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group("t")).strip()
    clock = re.match(r"(?:(early|late)\s+)?(\d{1,2})(?::(\d\d))?\s*([ap])", t, re.I)
    if clock:
        return f"{int(clock.group(2))}{':' + clock.group(3) if clock.group(3) else ''} {clock.group(4).upper()}M"
    return " ".join(w[:1].upper() + w[1:].lower() for w in t.split())[:20]


def route_line(text: str) -> bool:
    """A line that tells a route: from one place to another, through, a river's course, a canal, a pipeline."""
    return bool(_ROUTE_LINE.search(text or ""))


def storm_line(text: str) -> bool:
    """A line that tells a storm moving through places."""
    return bool(_STORM_LINE.search(text or "") and _STORM_MOVE.search(text or ""))


def upgrade_map(ov: dict, line: str, line_at: Callable[[int], float], start_s: float, pace: Pace,
                ok: Callable[[str], bool], two_ok: bool = True) -> Optional[dict]:
    """
    An older map look of the plan as its pack-3 map, when its line fits one (`line`: the narration round its
    start; `line_at(i)`: the second char i of `line` is said at): its places' line is a storm moving through them
    -> the storm track; values said for three or more of its places -> the totals map; a route (from / to,
    through, a river, a canal) through two to six of them -> the route (a two-place route only when `two_ok`: in
    turn with the old route looks). The places stay the overlay's own (resolved by the gazetteer), in the order
    the line says them; each item lands on its own word (`_items_at`: the seconds, for the lane's re-timing).
    None when nothing fits.
    """
    tid = str(ov.get("template") or "")
    locs = [x for x in (ov.get("locations") or []) if isinstance(x, dict) and isinstance(x.get("lat"), (int, float))]
    if len(locs) < 2 or ov.get("dataLook") or tid in MAP_IDS and tid != ROUTE:
        return None
    if tid not in OLD_ROUTES and tid not in OLD_MANY and tid not in STORM_ONLY:
        return None
    said = [(_first_at(line, _name_of(x.get("label") or "")), x) for x in locs]
    found = sorted([(i, x) for i, x in said if i >= 0], key=lambda p: p[0])
    if len(found) < 2:
        return None
    ordered = [x for _i, x in found] + [x for i, x in said if i < 0]
    pos = [i for i, _x in found]

    def at_of(i: int) -> float:
        return round(max(0.0, line_at(i) - start_s), 2)

    base = {k: v for k, v in ov.items() if k not in ("template", "variant", "items", "value", "suffix", "prefix", "total",
                                                     "highlight", "subtitle", "label", "text", "style", "theme")
            or (k == "theme" and v)}
    base.update(type="motion", motion="fade", exit="fade", upgraded=tid)
    # a storm moving through its places
    if storm_line(line) and ok(STORM) and pace.allows(STORM, start_s):
        name = re.search(r"\b((?:Hurricane|Tropical\s+Storm|Typhoon|Cyclone)\s+[A-Z][a-z]+)\b", line)
        cat = re.search(r"\b(category\s+(?:[1-5]|one|two|three|four|five))\b", line, re.I)
        items = [{"label": _storm_time(line, p, pos[j + 1] if j + 1 < len(pos) else -1), **({"at": at_of(p)} if j else {})}
                 for j, p in enumerate(pos)]
        items += [{"label": ""} for _x in ordered[len(pos):]]
        return {**base, "template": STORM, "variant": variant_of(STORM), "locations": ordered[:6],
                "text": name.group(1) if name else "", "subtitle": _cap(cat.group(1)) if cat else "",
                "label": "Storm track", "items": items[:6],
                "_items_at": ([None] + [line_at(p) for p in pos[1:]] + [None] * (len(ordered) - len(pos)))[:6]}
    if tid in STORM_ONLY:
        return None
    # values said for three or more of its places
    vals = {_name_of(v["name"]).lower(): v for v in _named_values(line)}
    hit = [(p, x, vals.get(_name_of(x.get("label") or "").lower())) for p, x in found]
    if len([h for h in hit if h[2]]) >= 3 and ok(TOTALS) and pace.allows(TOTALS, start_s):
        rows = [h for h in hit if h[2]][:6]
        unit = next((h[2]["unit"] for h in rows if h[2]["unit"]), "")
        of_what = re.search(r"\b(rain|rainfall|snow|snowfall|wind|gusts|heat)\b", line, re.I)
        title = {"rain": "Rainfall totals", "rainfall": "Rainfall totals", "snow": "Snowfall totals",
                 "snowfall": "Snowfall totals", "wind": "Wind gusts", "gusts": "Wind gusts", "heat": "Highs"}.get(
            (of_what.group(1).lower() if of_what else ""), "")
        return {**base, "template": TOTALS, "variant": variant_of(TOTALS), "locations": [h[1] for h in rows],
                "text": title, "subtitle": "", "label": "", "suffix": "" if unit == "%" else unit,
                "items": [{"label": _name_of(h[1].get("label") or ""), "value": _fmt(h[2]["value"]), "at": at_of(h[0])}
                          for h in rows],
                "_items_at": [line_at(h[0]) for h in rows]}
    # a route through them
    if route_line(line) and ok(ROUTE) and pace.allows(ROUTE, start_s) and len(found) <= 6:
        if len(found) == 2 and not two_ok:
            return None                         # a two-place route: every other one stays the old route look
        dist = re.search(rf"\b({_NUM})[\s-]+(miles?|kilometers?|kilometres?|km)\b", line, re.I)
        out = {**base, "template": ROUTE, "variant": variant_of(ROUTE), "locations": [x for _i, x in found],
               "text": "", "label": "Route",
               "items": [{"label": _name_of(x.get("label") or ""), **({"at": at_of(p)} if j else {})}
                         for j, (p, x) in enumerate(found)],
               "_items_at": [None] + [line_at(p) for p in pos[1:]]}
        if dist:
            out.update(value=_fmt(number_of(dist.group(1)) or 0), suffix="KM" if dist.group(2).lower().startswith("k") else "MI")
        return out
    return None
