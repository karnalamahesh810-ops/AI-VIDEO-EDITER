"""
Every date, time, year, percentage, multiplier and meaningful number the
narration says gets a clean kinetic look on its word (the owner, 2026-10-05,
on his Las Vegas video: "When dates and times are mentioned they must be on
the timeline. Percentages - like the 27 percent at the beginning - didn't get
an animation ... Numbers - 60,000, 70,000, whatever - must be seen on screen
when they are said ... use it where it matters, and don't use the same one
repeatedly"), and no overlay ends before its animation has played ("The
overlay animations, map animations, whatever animation it is, end quicker than
they need to").

Two passes, both pure (no network, no paid calls):

  plan(words, fps)          the data moments in the narration, ranked, merged
                            and turned into KT_* overlays (the renderer's
                            LibKinetic looks, ids in KT below);
  schedule(items, ...)      one lane for every overlay of the video: each look
                            keeps at least its family's minimum (entry + hold +
                            exit, MIN_HOLD), lands on its word or up to its
                            slack later, and is never cut short by a scene, a
                            shot or the next look - the lower-priority one is
                            delayed or left out instead.

`finish(doc)` runs both over a timeline (a build, and the relook action of
src/relook.py) and returns what changed.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from . import templates

# --------------------------------------------------------------------------- #
# The look ids (the contract with the renderer's registry: LibKinetic "kt-")
# --------------------------------------------------------------------------- #
KT_NUMBER = "KT_NUMBER"
KT_PERCENT = "KT_PERCENT"
KT_MULTIPLIER = "KT_MULTIPLIER"
KT_DATE = "KT_DATE"
KT_YEAR = "KT_YEAR"
KT_TIME = "KT_TIME"
KT_CHIP = "KT_CHIP"
KT_COMPARE = "KT_COMPARE"
KT_PROGRESS = "KT_PROGRESS"
KT_KEYWORD = "KT_KEYWORD"
KT_STATEMENT = "KT_STATEMENT"
KT_LOWER_THIRD = "KT_LOWER_THIRD"
KT_IDS = (KT_NUMBER, KT_PERCENT, KT_MULTIPLIER, KT_DATE, KT_YEAR, KT_TIME, KT_CHIP, KT_COMPARE, KT_PROGRESS,
          KT_KEYWORD, KT_STATEMENT, KT_LOWER_THIRD)
KT_DATA = {KT_NUMBER, KT_PERCENT, KT_MULTIPLIER, KT_DATE, KT_YEAR, KT_TIME, KT_CHIP, KT_COMPARE, KT_PROGRESS}


def variant_of(tid: str) -> str:
    """KT_LOWER_THIRD -> 'kt-lower-third' (the LibKinetic variant the renderer draws)."""
    return "kt-" + tid[3:].lower().replace("_", "-")


# The retired looks (remotion/src/legacyLooks.ts RETIRED_IDS; registry "retired": true): never chosen again,
# and rewritten as their clean kt- equivalent on an existing timeline.
RETIRED_IDS = frozenset({
    "LIB_ED_WORD_BY_WORD", "LIB_ED_BOX_STACK", "LIB_ED_TYPE_CLEAN", "LIB_ED_TYPE_TERMINAL", "LIB_ED_MARKER_HIGHLIGHT",
    "LIB_ED_BLUR_IN", "LIB_ED_SPLIT_REVEAL", "LIB_ED_OUTLINE_FILL", "LIB_ED_QUOTE_TYPE", "LIB_ED_QUESTION",
    "LIB_BT_COUNT", "LIB_DT_LETTER_DROP", "LIB_DT_BOLD_HEADLINE", "LIB_DT_BIG_STACK",
    "TEXT_WORD_TYPE_V1", "TEXT_BAR_TITLE_V1", "TEXT_UNDERLINE_TITLE_V1", "TEXT_SWOOSH_TITLE_V1",
    "TEXT_SENTENCE_HIGHLIGHT_V1", "TEXT_KEY_PHRASE_V1", "TEXT_KICKER_V1", "TEXT_TYPEWRITER_V1", "TEXT_MEMO_V1",
    "TEXT_QUESTION_V1", "TEXT_LABEL_PILL_V1",
    "LIB_HL_WORD_STACK", "LIB_HL_SPLIT_LINE", "LIB_HL_WIPE_BAR", "LIB_HL_KEYWORD_POP", "LIB_HL_FOCUS_PULL",
    "LIB_HL_LETTER_FLIP", "LIB_HL_OUTLINE_FILL", "LIB_HL_MARKER_SWEEP", "LIB_HL_CENTER_STACK", "LIB_HL_TICKER_SLIDE",
    "LIB_TXT_KEY_PHRASE", "LIB_TXT_QUOTE_LINE", "LIB_TXT_HEADLINE_WORDS", "LIB_TXT_QUESTION", "LIB_TXT_UNDERLINE_SWEEP",
    "LIB_TXT_KICKER_HEADLINE", "LIB_QS_ZOOM_WORD",
})
_TYPED_RETIRED = {"LIB_ED_TYPE_CLEAN", "LIB_ED_TYPE_TERMINAL", "LIB_ED_QUOTE_TYPE", "LIB_ED_QUESTION",
                  "TEXT_TYPEWRITER_V1", "TEXT_MEMO_V1", "TEXT_QUESTION_V1", "LIB_TXT_QUOTE_LINE", "LIB_TXT_QUESTION"}
_DATE_RETIRED = {"LIB_DT_LETTER_DROP", "LIB_DT_BOLD_HEADLINE", "LIB_DT_BIG_STACK"}

# Single-figure / date / year looks the data planner replaces when one of its looks says the same thing nearby.
FIGURE_LOOKS = frozenset({
    "LIB_BT_COUNT", "LIB_VR_DATE_HERO", "LIB_VR_YEAR_LINE", "LIB_VR_TIME_CARD", "LIB_NUM_BIG_FIGURE",
    "LIB_NUM_PERCENT_LINE", "LIB_CT_CORNER_STAT", "LIB_NUM_LOWER_THIRD", "TL_YEAR_ROLL_V1", "LIB_TL_YEAR_SCROLLER",
    "LIB_TL_DECADE_GRID", "NUM_BIG_COUNTER_V1", "NUM_NUMBER_ROLL_V1", "NUM_DONUT_V1", "LIB_PR_NUMBER_REVEAL",
    "LIB_DT_CLEAN_CARD", "LIB_DT_CALENDAR_PAGE", "LIB_DT_STAMP_BAR", "LIB_DT_CLOCK_TIME", "LIB_DT_REC_STAMP",
    "LIB_DT_DATE_SLAM", "LIB_DTX_TIME_STAMP", "LIB_DTX_DATE_TOP", "LIB_DTX_DATE_PLACE", "LIB_TL_YEARS_LATER",
    "LIB_TL_TIME_PASSING",
})

# --------------------------------------------------------------------------- #
# Never end early: each family's least time on screen
# --------------------------------------------------------------------------- #
ENTRY = 0.5             # an eased entry (12-18 frames at 30 fps)
EXIT = 0.4              # a mirrored 12-frame exit
# The hold after the look has landed, per family (the owner: maps / documents / charts >= 5-6 s, numbers 3-5 s,
# dates 3 s, text >= 2.5 s after it lands).
MIN_HOLD = {
    "map": 5.5, "document": 5.0, "chart": 5.0, "number": 3.0, "ring": 3.0, "compare": 4.0, "date": 3.0,
    "image": 3.0, "person": 4.0, "lower-third": 3.0, "text": 2.5, "annotation": 3.0, "other": 2.5,
}
# How long a counting / filling look takes to land after its entry (the count, the ring, the bars).
LANDING = {"number": 0.6, "ring": 0.8, "compare": 0.9, "date": 0.3, "chart": 0.5, "map": 0.5}
# What a look is planned for when the lane has room (seconds, entry and exit included).
WANT = {"map": 7.0, "document": 6.5, "chart": 6.5, "number": 4.5, "ring": 5.0, "compare": 6.5, "date": 4.2,
        "image": 5.0, "person": 5.0, "lower-third": 4.5, "text": 4.0, "annotation": 4.0, "other": 3.6}
TYPE_CPS = 22.0         # a typed look sets this many characters a second ...
WORD_STAGGER = 0.08     # ... a word-by-word reveal one word every this many seconds
BREATH = 0.25           # between two looks in the lane
SLACK = {"data": 1.2, "kept": 2.0, "map": 1.5}
EARLY_KEPT = 1.0        # a kept picture look may start this much before its old start (its scene is on screen)
MAX_LEAD_S = 0.07       # a look starts at most 2 frames before its word (it lands on the word, never early)

_FAMILY_BY_CATEGORY = {"MAPS": "map", "DOCUMENTS": "document", "CHARTS": "chart", "COMPARISONS": "chart",
                       "NUMBERS": "number", "TIMELINES": "date", "IMAGES": "image", "HEADLINES": "text",
                       "TEXT": "text", "QUOTES": "text", "CALLOUTS": "annotation", "LOWER_THIRDS": "lower-third"}
_KT_FAMILY = {KT_NUMBER: "number", KT_CHIP: "number", KT_PERCENT: "ring", KT_PROGRESS: "ring",
              KT_MULTIPLIER: "ring", KT_COMPARE: "compare", KT_DATE: "date", KT_YEAR: "date", KT_TIME: "date",
              KT_KEYWORD: "text", KT_STATEMENT: "text", KT_LOWER_THIRD: "lower-third"}


def family_of(ov: dict) -> str:
    """The never-end-early family of an overlay (MIN_HOLD's keys)."""
    tid = str(ov.get("template") or "")
    if tid in _KT_FAMILY:
        return _KT_FAMILY[tid]
    typ = str(ov.get("type") or "")
    if typ == "map" or tid.startswith("MAP_") or tid == "LIB_PR_MAP_PATH":
        return "map"
    if tid in ("LIB_PR_DOC_SPOTLIGHT",) or tid.startswith("DOC_"):
        return "document"
    if tid.startswith(("CHART_", "LIB_RD_", "LIB_CA_")) or tid == "LIB_PR_GRAPH_BUILD":
        return "chart"
    if tid.startswith("LIB_PF_") or typ == "name-card" or tid.startswith("PERSON_"):
        return "person"
    t = templates.get(tid) or {}
    fam = _FAMILY_BY_CATEGORY.get(str(t.get("category") or ""), "")
    if fam:
        return fam
    if typ in ("photo-card",):
        return "image"
    if typ in ("lower-third",):
        return "lower-third"
    if typ in ("title", "chapter", "callout", "kicker", "typewriter", "memo-box", "bar-title"):
        return "text"
    return "other"


def _types(ov: dict) -> bool:
    tid = str(ov.get("template") or "")
    if tid == KT_STATEMENT:
        return True
    try:
        return templates.types(templates.get(tid))
    except Exception:  # noqa: BLE001
        return False


def landing_seconds(ov: dict) -> float:
    """When the look has landed, from its start: the entry, then its count / fill / typing / word reveal."""
    fam = family_of(ov)
    text = str(ov.get("text") or "")
    land = ENTRY + LANDING.get(fam, 0.0)
    if fam == "text":
        if _types(ov):
            land = ENTRY + len(text) / TYPE_CPS
        else:
            land = ENTRY + WORD_STAGGER * max(0, len(text.split()) - 1)
    return land


def min_seconds(ov: dict) -> float:
    """entry + landing + the family's hold + exit: the least time a look may be on screen."""
    fam = family_of(ov)
    return round(landing_seconds(ov) + MIN_HOLD.get(fam, MIN_HOLD["other"]) + EXIT, 3)


def min_frames(ov: dict, fps: int) -> int:
    return int(math.ceil(min_seconds(ov) * fps - 1e-6))


def want_seconds(ov: dict) -> float:
    return max(min_seconds(ov), WANT.get(family_of(ov), WANT["other"]))


# --------------------------------------------------------------------------- #
# The narration as one text, every character tied to its word's time
# --------------------------------------------------------------------------- #
_GLUE = re.compile(r"^(?:[,.]\d|%|-[A-Za-z]|'s\b|’s\b)")


class Narration:
    """All words of the video in order, joined into one text (`50 ,000` -> `50,000`, `27 %` -> `27%`)."""

    def __init__(self, words: List[dict]):
        parts: List[str] = []
        self.starts: List[int] = []         # char offset of each word
        self.times: List[Tuple[float, float]] = []
        pos = 0
        for w in words:
            tok = str(w.get("text") or w.get("word") or "").strip()
            if not tok:
                continue
            try:
                a, b = float(w.get("start")), float(w.get("end", w.get("start")))
            except (TypeError, ValueError):
                continue
            glue = bool(parts) and bool(_GLUE.match(tok))
            if parts and not glue:
                parts.append(" ")
                pos += 1
            self.starts.append(pos)
            self.times.append((a, max(a, b)))
            parts.append(tok)
            pos += len(tok)
        self.text = "".join(parts)

    def word_at(self, char: int) -> int:
        lo, hi = 0, len(self.starts) - 1
        if hi < 0:
            return -1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= char:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def time_at(self, char: int) -> float:
        i = self.word_at(char)
        return self.times[i][0] if i >= 0 else 0.0

    def end_at(self, char: int) -> float:
        i = self.word_at(max(0, char - 1))
        return self.times[i][1] if i >= 0 else 0.0

    def sentence(self, char: int) -> Tuple[int, int]:
        """The sentence around a character: (start, end) offsets."""
        t = self.text
        a = max(t.rfind(". ", 0, char), t.rfind("? ", 0, char), t.rfind("! ", 0, char))
        a = 0 if a < 0 else a + 2
        ends = [i for i in (t.find(". ", char), t.find("? ", char), t.find("! ", char)) if i >= 0]
        b = min(ends) + 1 if ends else len(t)
        return a, b


def words_of(doc: dict) -> List[dict]:
    """Every timed word of a timeline, in order (scene words are in seconds of the video)."""
    out: List[dict] = []
    for s in doc.get("scenes") or []:
        for w in (s or {}).get("words") or []:
            if isinstance(w, dict):
                out.append(w)
    out.sort(key=lambda w: float(w.get("start") or 0.0))
    return out


# --------------------------------------------------------------------------- #
# Finding the moments
# --------------------------------------------------------------------------- #
_UNITS = [
    (r"acre[\s-]*f(?:ee|oo)t", "ACRE-FT"), (r"million\s+acre[\s-]*f(?:ee|oo)t", "ACRE-FT"),
    (r"people|residents", "PEOPLE"), (r"homes|houses", "HOMES"), (r"miles?", "MILES"), (r"feet|foot|ft", "FT"),
    (r"gallons?", "GALLONS"), (r"dollars?", "$"), (r"years?", "YEARS"), (r"months?", "MONTHS"), (r"days?", "DAYS"),
    (r"inches|inch", "IN"), (r"degrees", "°"), (r"jobs", "JOBS"), (r"farms?", "FARMS"), (r"acres?", "ACRES"),
    (r"tons?", "TONS"), (r"kilometers?|kilometres?|km", "KM"), (r"meters?|metres?", "M"), (r"deaths|dead", "DEAD"),
    (r"cubic\s+feet\s+per\s+second|cfs", "CFS"), (r"households|families", "FAMILIES"),
]
_UNIT_RX = re.compile(r"\s*(?:of\s+)?(" + "|".join(u for u, _ in _UNITS) + r")\b", re.I)
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_SPELL_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
_SPELL_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SPELL_WORD = "|".join(sorted(list(_SPELL_UNITS) + list(_SPELL_TENS), key=len, reverse=True))
# A figure: digits ("760,000", "2.8", "$1.25") or spelled ("two and a half", "a billion", "ninety"), then a scale.
_FIGURE = re.compile(
    r"(?<![\w.,$])(\$\s?)?(?:(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?|((?:a|an|one|two|three|four|five|six|seven|eight|"
    r"nine|ten)\s+and\s+a\s+half|a|an|" + _SPELL_WORD + r"(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?))"
    r"(?:\s+(hundred))?(?:\s+(thousand|million|billion|trillion))?(?![\w])", re.I)
_PERCENT_TAIL = re.compile(r"\s*(?:%|percent\b|per\s*cent\b)", re.I)
_TIMES_TAIL = re.compile(r"\s+times\b", re.I)
_FILLER_BEFORE = re.compile(r"\b(?:one of|a couple|a few|one more|one day|no one|any one|every one|one by one)\s*$", re.I)
_YEARISH = re.compile(r"^(1[5-9]\d\d|20\d\d)$")
_HEDGE = re.compile(r"\b(almost|nearly|about|roughly|around|more than|over|under|less than|just over|"
                    r"just under|close to|up to|at least)\s*$", re.I)
_IMPORTANT = re.compile(r"\b(record|lowest|highest|largest|biggest|smallest|worst|most|entire|total|all of|"
                        r"every|whole|first|last|only|never|shocking|more than|less than|against|than)\b", re.I)
_COMPARE_LINK = re.compile(r"\b(against|versus|vs\.?|compared (?:to|with)|while|whereas|than)\b", re.I)
_PROPER = re.compile(r"\b([A-Z][a-z'’]+(?:\s+[A-Z][a-z'’]+){0,2})\b")
_NOT_LABEL = {"The", "A", "An", "And", "But", "So", "Then", "That", "This", "It", "Its", "It's", "In", "On", "At",
              "By", "For", "From", "Of", "To", "Read", "Put", "Line", "Look", "Now", "Back", "Whatever", "Whole",
              "Two", "One", "Three", "Nearly", "About", "More", "Less", "Last", "Across",
              "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December", "Friday", "Monday", "Tuesday", "Wednesday", "Thursday", "Saturday", "Sunday",
              "Why", "What", "How", "When", "Where", "Who", "Here", "There", "They", "Those", "These", "He", "She",
              "We", "You", "I", "If", "Or", "Nor", "Yet", "Still", "Even", "Just", "Only", "Every", "Each"}
_WORDNUM = {**_SPELL_UNITS, **_SPELL_TENS, "a": 1, "an": 1, "twice": 2, "double": 2, "triple": 3, "half": 0.5}
_SHARE_WORDS = {"a third": (1, 3), "one third": (1, 3), "two thirds": (2, 3), "two-thirds": (2, 3),
                "a quarter": (1, 4), "one quarter": (1, 4), "three quarters": (3, 4), "three-quarters": (3, 4),
                "half": (1, 2), "a half": (1, 2)}
_SHARE = re.compile(r"\b(a third|one third|two[\s-]+thirds|a quarter|one quarter|three[\s-]+quarters)\b(?:\s+of\b)?",
                    re.I)
_X_OF_Y = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:of|out of|in)\s+(?:every\s+)?"
                     r"(\d{1,3}|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)\b", re.I)
_MULT_WORD = re.compile(r"\b(?:(more than|nearly|almost|about|over)\s+)?(twice|double|triple)\b(?:\s+(as|over|the|that|what))?",
                        re.I)
_FOR_EVERY = re.compile(r"\bfor every\b", re.I)
_TIME = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?::([0-5]\d))?\s*"
                   r"(?:o['’]?\s?clock\s*)?(in the morning|in the afternoon|in the evening|at night|a\.?\s?m\b\.?|"
                   r"p\.?\s?m\b\.?)", re.I)


def _spelled(s: str) -> Optional[float]:
    s = re.sub(r"\s+", " ", s.strip().lower().replace("-", " "))
    if s in ("a", "an"):
        return 1.0
    m = re.fullmatch(r"(\w+) and a half", s)
    if m:
        base = _WORDNUM.get(m.group(1))
        return None if base is None else base + 0.5
    total = 0.0
    for w in s.split():
        if w in _SPELL_TENS:
            total += _SPELL_TENS[w]
        elif w in _SPELL_UNITS:
            total += _SPELL_UNITS[w]
        else:
            return None
    return total


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ,.;:-")


def _context_after(text: str, at: int, end: int, limit: int = 34) -> str:
    """The few words that follow a figure in its clause ("a year", "below its legal limit")."""
    tail = text[at:end]
    tail = re.split(r"[.;:!?,]|\s(?:and|but)\s(?=[A-Z])", tail)[0]
    words = tail.split()
    out = ""
    for w in words[:7]:
        cand = (out + " " + w).strip()
        if len(cand) > limit:
            break
        out = cand
    out = _clean(out)
    # never end on a little word ("of the", "for")
    while out and out.split()[-1].lower() in {"of", "the", "a", "an", "to", "for", "and", "in", "on", "its", "by",
                                               "that", "with", "from", "at", "is", "was", "every", "more", "little",
                                               "than", "as", "so", "it", "their", "his", "her", "our", "one"}:
        out = " ".join(out.split()[:-1])
    return out


def _label_before(text: str, sent_start: int, at: int) -> str:
    """The proper noun the figure belongs to in its clause ("Nevada's cut" -> NEVADA), else ''."""
    head = text[sent_start:at]
    head = re.split(r"[;:]|,\s|\b(?:and|but|while|then|against)\b", head)[-1]
    found = [m.group(1) for m in _PROPER.finditer(head)]
    for name in reversed(found):
        first = name.split()[0]
        if first in _NOT_LABEL or name in _NOT_LABEL:
            continue
        name = re.sub(r"['’]s$", "", name)
        if 2 <= len(name) <= 24:
            return name.upper()
    return ""


def _unit_after(text: str, end: int) -> Tuple[str, int]:
    m = _UNIT_RX.match(text, end)
    if not m:
        return "", end
    raw = m.group(1).lower()
    for rx, short in _UNITS:
        if re.fullmatch(rx, raw, re.I):
            return short, m.end()
    return "", end


def moments(nar: Narration) -> List[dict]:
    """
    Every data moment the narration says, in time order: {kind, at, end, value, ...}. kind is one of
    percent, multiplier, progress, number, date, year, time. Positions are char offsets into nar.text.
    """
    text = nar.text
    out: List[dict] = []
    taken: List[Tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(kind: str, a: int, b: int, **kw) -> None:
        taken.append((a, b))
        s0, s1 = nar.sentence(a)
        out.append({"kind": kind, "a": a, "b": b, "at": nar.time_at(a), "end": nar.end_at(b),
                    "said": text[a:b], "sentence": text[s0:s1], "s0": s0, "s1": s1, **kw})

    # 1. dates ("Friday, August 21, 2026", "January 2026", "December 31", "January 1, 2027")
    from .treatments import date_parts
    pos = 0
    while pos < len(text):
        d = date_parts(text[pos:])
        if not d:
            break
        a, b = pos + d["start"], pos + d["end"]
        wd = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s*$", text[max(0, a - 12):a], re.I)
        if free(a, b):
            month = d["month"].title()
            add("date", a, b, month=month, day=d.get("day"), year=d.get("year"),
                weekday=(wd.group(1).upper() if wd else ""))
        pos = b
    # 2. times of day ("three in the morning", "3 p.m.")
    for m in _TIME.finditer(text):
        raw = m.group(1).lower()
        h = int(raw) if raw.isdigit() else _WORDNUM.get(raw, 0)
        if not 1 <= h <= 12 or not free(m.start(), m.end()):
            continue
        part = m.group(3).lower()
        ampm = "AM" if ("morning" in part or part.startswith("a")) else "PM"
        if "night" in part:
            ampm = "AM" if h < 5 else "PM"
        add("time", m.start(), m.end(), label=f"{h}{':' + m.group(2) if m.group(2) else ''} {ampm}")
    # 3. shares said in words ("two-thirds", "nearly three of every four", "more than a third")
    for m in _X_OF_Y.finditer(text):
        x, y = m.group(1).lower(), m.group(2).lower()
        xv = float(x) if x.isdigit() else _WORDNUM.get(x)
        yv = float(y) if y.isdigit() else _WORDNUM.get(y)
        if not xv or not yv or xv >= yv or yv > 100 or not free(m.start(), m.end()):
            continue
        if not re.search(r"\bevery\b|\bout of\b", m.group(0), re.I) and yv > 12:
            continue
        add("progress", m.start(), m.end(), value=xv, total=yv)
    for m in _SHARE.finditer(text):
        key = re.sub(r"[\s-]+", " ", m.group(1).lower()).replace("two thirds", "two-thirds").replace(
            "three quarters", "three-quarters")
        xv, yv = _SHARE_WORDS.get(key, (None, None))
        if xv and free(m.start(), m.end()):
            add("progress", m.start(), m.end(), value=float(xv), total=float(yv))
    # 4. "twice as", "more than twice over"
    for m in _MULT_WORD.finditer(text):
        if not (m.group(1) or m.group(3)) or not free(m.start(), m.end()):
            continue
        add("multiplier", m.start(), m.end(), value=float(_WORDNUM[m.group(2).lower()]))
    # 5. figures: percent, "15 times", numbers with a noun or unit, years
    for m in _FIGURE.finditer(text):
        a, b = m.start(), m.end()
        if not free(a, b):
            continue
        dollar, digits, frac, words, hundred, scale = m.groups()
        if digits:
            v = float(digits.replace(",", "") + ("." + frac if frac else ""))
            spelled = False
        else:
            sv = _spelled(words or "")
            if sv is None:
                continue
            v, spelled = sv, True
        if hundred:
            v *= 100
        split = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|\d)\.\s$", text[max(0, a - 7):a], re.I)
        if split and digits and not frac and scale and len(digits) <= 2:
            w = split.group(1).lower()
            v = (float(w) if w.isdigit() else float(_WORDNUM[w])) + float("0." + digits)
            a = a - (len(split.group(0)))
        sc = (scale or "").lower()
        # a bare "a"/"an" is a figure only before a scale word ("a billion dollars")
        if spelled and (words or "").lower() in ("a", "an") and not sc and not hundred:
            continue
        before = text[max(0, a - 24):a]
        if _FILLER_BEFORE.search(text[max(0, a - 14):a] + (words or digits or "")):
            continue
        hedge = (_HEDGE.search(before).group(1) if _HEDGE.search(before) else "")
        rest = b
        pm = _PERCENT_TAIL.match(text, b)
        if pm:
            add("percent", a, pm.end(), value=v, hedge=hedge)
            continue
        tm = _TIMES_TAIL.match(text, b)
        if tm and not re.match(r"\s+(?:a|an|per|each|every|in a)\s", text[tm.end():tm.end() + 8], re.I):
            if 1 < v <= 1000:
                add("multiplier", a, tm.end(), value=v, hedge=hedge)
            continue
        # a year as a year (never "2,000 people"): leave it to the year pass below
        if digits and not frac and not sc and not dollar and _YEARISH.match(digits):
            unit_y, _ = _unit_after(text, b)
            if not unit_y:
                continue
        full = v * _SCALE.get(sc, 1.0)
        unit, rest = _unit_after(text, b)
        if dollar:
            unit = "$"
        if not unit:
            # "California is allowed to take almost 15" after "for every bucket ..." = 1 vs 15
            s0, _s1 = nar.sentence(a)
            prev0, _ = nar.sentence(max(0, s0 - 2))
            if hedge and _FOR_EVERY.search(text[prev0:a]) and 1 < v <= 100:
                add("multiplier", a, b, value=v, hedge=hedge, ratio=True)
                continue
            if not sc and not (digits and (full >= 1000 or "," in digits)):
                continue                        # a bare small number: filler
        if spelled and full < 10 and (unit not in ("MONTHS", "YEARS", "DAYS", "MILES", "$") or full < 2):
            continue                            # "three states", "two great reservoirs", "in one year"
        if full == 0:
            continue
        add("number", a, rest, value=v, scale=sc, unit=unit, full=full, hedge=hedge, money=bool(dollar) or unit == "$")
    # 6. years said as years ("built in 1970", "In 2022", "for 2027 and 2028")
    from .treatments import _YEAR_SAID
    for m in _YEAR_SAID.finditer(text):
        a, b = m.start(1), m.end(1)
        if not free(a, b):
            continue
        y = int(m.group(1))
        rng = re.match(r"\s*(?:and|to|through|-|–)\s*(1[5-9]\d\d|20\d\d)\b", text[b:b + 16])
        if rng:
            b2 = b + rng.end()
            add("year", a, b2, value=y, to=int(rng.group(1)))
            taken.append((b, b2))
        else:
            add("year", a, b, value=y)
    out.sort(key=lambda x: (x["at"], x["a"]))
    # "California's is 4.4 million against Nevada's 300,000": the unit said with the figure just before
    last_unit: Tuple[float, str] = (-1e9, "")
    for m in out:
        if m["kind"] != "number":
            continue
        if m.get("unit"):
            last_unit = (m["at"], m["unit"])
        elif m["at"] - last_unit[0] <= 12.0 and last_unit[1] and last_unit[1] != "$":
            m["unit"] = last_unit[1]
            m["inherited"] = True
    return out


# --------------------------------------------------------------------------- #
# Ranking and the looks
# --------------------------------------------------------------------------- #
HOOK_SECONDS = 120.0
REPEAT_SECONDS = 60.0       # the same figure already shown this recently is not shown again ...
REPEAT_FAR = 180.0          # ... and a figure shown before comes back only this much later ...
REPEAT_MAX = 3              # ... at most this many times in a video
MERGE_SECONDS = 2.5         # two moments this close become one look
COMPARE_SPAN = 9.0          # values of one unit said this close, each with its own name, become a comparison
COMPARE_ALONE = 4.6         # ... and its first value, said this long before the last, also gets its own look
HERO_SCORE = 3.0


def _key(m: dict) -> str:
    k = m["kind"]
    if k == "number":
        return f"n:{m['full']:g}:{m.get('unit')}"
    if k == "percent":
        return f"p:{round(float(m['value'])):g}"
    if k == "multiplier":
        return f"{'r' if m.get('ratio') else 'x'}:{m['value']:g}"
    if k == "progress":
        return f"p:{round(100.0 * float(m['value']) / float(m['total'])):g}"
    if k == "date":
        return f"d:{m.get('month')}:{m.get('day')}:{m.get('year')}"
    if k == "year":
        return f"y:{m['value']}:{m.get('to')}"
    if k == "time":
        return f"t:{m['label']}"
    return f"{k}:{m.get('value')}"


def score(m: dict) -> float:
    s = 1.0
    k = m["kind"]
    sent = m.get("sentence") or ""
    if k in ("percent", "multiplier", "date", "progress"):
        s += 2.0
    if k == "number":
        full = float(m.get("full") or 0)
        s += 1.5 if full >= 100_000 else (1.0 if full >= 1000 else 0.0)
        s += 0.5 if m.get("unit") in ("ACRE-FT", "PEOPLE", "$") else 0.0
        s += 1.0 if m.get("money") else 0.0
    if k == "year":
        s += 0.5
    if m["at"] < HOOK_SECONDS:
        s += 1.5
    if _IMPORTANT.search(sent):
        s += 1.0
    if k == "time":
        s += 1.5
    return s


def _fmt_value(v: float) -> float:
    return int(v) if float(v).is_integer() else round(float(v), 3)


def _hedge_label(h: str) -> str:
    return {"more than": "MORE THAN", "over": "OVER", "almost": "ALMOST", "nearly": "NEARLY", "about": "ABOUT",
            "roughly": "ROUGHLY", "around": "AROUND", "under": "UNDER", "less than": "LESS THAN",
            "just over": "JUST OVER", "just under": "JUST UNDER", "close to": "CLOSE TO", "up to": "UP TO",
            "at least": "AT LEAST"}.get((h or "").lower(), "")


def look_for(m: dict, nar: Narration, hero: bool) -> dict:
    """The KT overlay props for one moment (no timing yet)."""
    text = nar.text
    k = m["kind"]
    ctx = _context_after(text, m["b"], m["s1"])
    label = _label_before(text, m["s0"], m["a"])
    hedge = _hedge_label(m.get("hedge", ""))
    if k == "percent":
        return {"template": KT_PERCENT, "value": _fmt_value(m["value"]), "suffix": "%",
                "label": label or hedge, "subtitle": ctx}
    if k == "progress":
        return {"template": KT_PROGRESS, "value": _fmt_value(m["value"]), "total": _fmt_value(m["total"]),
                "label": label, "subtitle": ctx or _clean(m["said"])}
    if k == "multiplier":
        sub = ctx
        if m.get("ratio"):
            sub = sub or "for every 1"
        return {"template": KT_MULTIPLIER, "value": _fmt_value(m["value"]), "suffix": "×",
                "label": label or hedge, "subtitle": sub}
    if k == "date":
        main = m["month"] + (f" {m['day']}" if m.get("day") else "")
        return {"template": KT_DATE, "text": main, "subtitle": str(m["year"]) if m.get("year") else "",
                "label": m.get("weekday") or ""}
    if k == "year":
        sub = f"to {m['to']}" if m.get("to") and m["to"] - m["value"] > 1 else (
            f"and {m['to']}" if m.get("to") else "")
        return {"template": KT_YEAR, "value": m["value"], "label": "",
                "subtitle": sub or _context_after(text, m["b"], m["s1"], 28)}
    if k == "time":
        return {"template": KT_TIME, "text": m["label"], "label": ""}
    # numbers
    unit = m.get("unit") or ""
    sc = m.get("scale") or ""
    props: Dict[str, Any] = {"value": _fmt_value(m["value"]), "label": label or hedge, "subtitle": ctx}
    if unit == "$":
        props["prefix"] = "$"
        props["suffix"] = sc.upper() if sc else ""
    else:
        props["suffix"] = (sc.upper() + " " + unit).strip() if sc and unit else (sc.upper() if sc else unit)
        if sc and unit:
            # the renderer reads a scale word as the suffix; the unit rides as the context's first word
            props["suffix"] = sc.upper()
            words = unit.replace("-", " ").lower().replace("acre ft", "acre-feet") + " " + ctx
            props["subtitle"] = _context_after(words, 0, len(words), 34)
    props["template"] = KT_NUMBER if hero else KT_CHIP
    return props


# A calendar date always keeps its own look (a date is never shown as a bare year); the rest rotate.
ALTERNATE = {KT_NUMBER: KT_CHIP, KT_CHIP: KT_NUMBER, KT_PERCENT: KT_PROGRESS, KT_PROGRESS: KT_PERCENT,
             KT_MULTIPLIER: KT_COMPARE, KT_YEAR: KT_DATE, KT_TIME: KT_DATE}


def _alternate(props: dict) -> Optional[dict]:
    """The same moment in the other style of its kind (so one style never shows twice in a row)."""
    t = props["template"]
    alt = ALTERNATE.get(t)
    p = dict(props)
    if alt is None:
        return None
    if t in (KT_NUMBER, KT_CHIP):
        p["template"] = alt
        return p
    if t == KT_PERCENT:
        p.update(template=KT_PROGRESS, total=100)
        return p
    if t == KT_PROGRESS:
        tot = float(props.get("total") or 100)
        p.update(template=KT_PERCENT, value=round(100.0 * float(props["value"]) / tot), suffix="%")
        p.pop("total", None)
        return p
    if t == KT_MULTIPLIER:
        v = float(props["value"])
        p = {"template": KT_COMPARE, "text": props.get("label") or "", "subtitle": props.get("subtitle") or "",
             "suffix": "×", "items": [{"label": "1×", "value": 1},
                                      {"label": f"{_fmt_value(v)}×", "value": _fmt_value(v)}]}
        return p
    if t == KT_YEAR:
        return {"template": KT_DATE, "text": "", "subtitle": str(props["value"]), "label": props.get("label") or ""}
    if t == KT_TIME:
        return {"template": KT_DATE, "text": props.get("text", ""), "subtitle": "", "label": props.get("label") or ""}
    return None


def _compare_groups(ms: List[dict], nar: Narration) -> List[List[dict]]:
    """Runs of 2-3 numbers of one unit, each with its own name, said within COMPARE_SPAN (then vs now, A vs B)."""
    groups: List[List[dict]] = []
    nums = [m for m in ms if m["kind"] == "number"]
    i = 0
    while i < len(nums):
        run = [nums[i]]
        j = i + 1
        while j < len(nums) and len(run) < 3:
            n = nums[j]
            if n.get("unit") != run[0].get("unit") or n["at"] - run[0]["at"] > COMPARE_SPAN:
                break
            run.append(n)
            j += 1
        labels = [_label_before(nar.text, m["s0"], m["a"]) for m in run]
        linked = any(_COMPARE_LINK.search(nar.text[run[0]["a"]:m["b"]]) for m in run[1:])
        named = all(labels) and len(set(labels)) == len(labels)
        if len(run) >= 2 and (named or linked):
            for m, lab in zip(run, labels):
                m["_label"] = lab
            groups.append(run)
            i = j
        else:
            i += 1
    return groups


def plan(words: List[dict], fps: int, shown: Optional[Dict[str, float]] = None) -> Tuple[List[dict], List[dict]]:
    """
    The KT overlays for every data moment of the narration, and the log of every moment (shown or why not).
    Each overlay carries `at` (the word's second), priority and the moment it shows; startFrame /
    durationInFrames are set by schedule().
    """
    nar = Narration(words)
    ms = moments(nar)
    log: List[dict] = []
    for m in ms:
        m["score"] = score(m)
    # comparisons first: a run of named values of one unit is one look
    grouped = set()
    looks: List[dict] = []
    for run in _compare_groups(ms, nar):
        unit = run[0].get("unit") or ""
        items = []
        for m in run:
            items.append({"label": m.get("_label") or _clean(m["said"])[:18].upper(), "value": _fmt_value(m["full"])})
            grouped.add(id(m))
        # The comparison lands when its last value is said (never before a value is spoken); a first value said
        # well before it is shown on its own word as well.
        head = run[-1]
        if run[-1]["at"] - run[0]["at"] >= COMPARE_ALONE:
            grouped.discard(id(run[0]))
        looks.append({"m": head, "run": run, "props": {
            "template": KT_COMPARE, "items": items, "suffix": "" if unit == "$" else unit,
            "prefix": "$" if unit == "$" else "", "text": "", "subtitle": _context_after(nar.text, run[-1]["b"], run[-1]["s1"]),
            "label": ""}, "score": max(x["score"] for x in run) + 1.0})
    for m in ms:
        if id(m) in grouped:
            continue
        looks.append({"m": m, "run": [m], "props": None, "score": m["score"]})
    looks.sort(key=lambda x: x["m"]["at"])
    # merge two moments that land within MERGE_SECONDS: keep the stronger
    merged: List[dict] = []
    for lk in looks:
        if merged and lk["m"]["at"] - merged[-1]["m"]["at"] < MERGE_SECONDS:
            prev = merged[-1]
            loser = lk if prev["score"] >= lk["score"] else prev
            winner = prev if loser is lk else lk
            log.append({"at": round(loser["m"]["at"], 2), "said": loser["m"]["said"], "kind": loser["m"]["kind"],
                        "look": None, "why": f"merged into '{winner['m']['said']}' ({MERGE_SECONDS:g} s rule)"})
            merged[-1] = winner
            continue
        merged.append(lk)
    # repeats, hero / chip, rotation
    seen: Dict[str, List[float]] = {k: [v] for k, v in (shown or {}).items()}
    out: List[dict] = []
    last_tid = ""
    uses: Dict[str, int] = {}
    for lk in merged:
        m = lk["m"]
        key = "c:" + "|".join(_key(x) for x in lk["run"]) if len(lk["run"]) > 1 else _key(m)
        times = seen.get(key, [])
        if times and (m["at"] - times[-1] < REPEAT_SECONDS):
            log.append({"at": round(m["at"], 2), "said": m["said"], "kind": m["kind"], "look": None,
                        "why": f"shown {m['at'] - times[-1]:.0f} s before"})
            continue
        if times and (m["at"] - times[-1] < REPEAT_FAR or len(times) >= REPEAT_MAX) and lk["score"] < 5.0:
            log.append({"at": round(m["at"], 2), "said": m["said"], "kind": m["kind"], "look": None,
                        "why": f"said again ({len(times)} time(s) shown, last {m['at'] - times[-1]:.0f} s before)"})
            continue
        props = lk["props"] or look_for(m, nar, hero=lk["score"] >= HERO_SCORE)
        n_data = max(1, sum(uses.values()))
        if props["template"] == KT_NUMBER and uses.get(KT_NUMBER, 0) / n_data > 0.4 and lk["score"] < 4.5:
            props = dict(props, template=KT_CHIP)
        if props["template"] == last_tid:
            alt = _alternate(props)
            if alt is not None:
                props = alt
        seen.setdefault(key, []).append(m["at"])
        tid = props["template"]
        uses[tid] = uses.get(tid, 0) + 1
        last_tid = tid
        end = lk["run"][-1]["end"]
        ov = {"type": "motion", "variant": variant_of(tid), **props, "motion": "fade", "exit": "fade",
              "dataLook": True, "said": _clean(nar.text[lk["run"][0]["a"]:lk["run"][-1]["b"]])[:120],
              "_at": m["at"], "_end": end, "_score": round(lk["score"], 2)}
        ov = {k: v for k, v in ov.items() if v not in (None,)}
        out.append(ov)
        log.append({"at": round(m["at"], 2), "said": ov["said"], "kind": "compare" if len(lk["run"]) > 1 else m["kind"],
                    "look": tid, "score": round(lk["score"], 2)})
    return out, log


# --------------------------------------------------------------------------- #
# Retired looks on an existing timeline
# --------------------------------------------------------------------------- #
_RETIRED_MULT = re.compile(r"\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|"
                           r"twenty)\s*(?:times|x|×)\b|\b(twice|double|triple)\b", re.I)
_BARE = re.compile(r"^(?:(almost|about|nearly|roughly|over|more than|under|less than)\s+)?(\d[\d,]*(?:\.\d+)?)\s*$", re.I)


def remap_retired(ov: dict) -> Optional[dict]:
    """
    A retired look as the clean kt- look that says the same (remotion/src/legacyLooks.ts remapRetired);
    None when it is not retired. Timing and the overlay's other fields are kept.
    """
    tid = str(ov.get("template") or "")
    if tid not in RETIRED_IDS:
        return None
    text = re.sub(r"\s+", " ", str(ov.get("text") or "")).strip()
    value = ov.get("value") if isinstance(ov.get("value"), (int, float)) and not isinstance(ov.get("value"), bool) else None
    suffix = str(ov.get("suffix") or "").strip()
    base = {k: v for k, v in ov.items() if k not in ("template", "variant", "textStyle", "align", "text", "label",
                                                    "subtitle", "value", "suffix", "total", "items")}

    def kt(t: str, **props) -> dict:
        return {**base, "type": "motion", "template": t, "variant": variant_of(t), "motion": "fade", "exit": "fade",
                **props}

    if tid in _DATE_RETIRED:
        from .treatments import date_parts
        d = date_parts(text)
        if d:
            return kt(KT_DATE, text=d["month"].title() + (f" {d['day']}" if d.get("day") else ""),
                      subtitle=str(d["year"]) if d.get("year") else "", label="")
        return kt(KT_KEYWORD, text=text, label="")
    if value is not None and tid in ("LIB_BT_COUNT", "TEXT_LABEL_PILL_V1"):
        word = text.lower()
        if suffix == "%":
            return kt(KT_PERCENT, value=value, suffix="%", label="", subtitle=word)
        if tid == "TEXT_LABEL_PILL_V1":
            return kt(KT_CHIP, value=value, suffix=suffix, label=text)
        if suffix.upper() in ("MILLION", "BILLION", "THOUSAND"):
            return kt(KT_NUMBER, value=value, suffix=suffix, label="", subtitle=word)
        return kt(KT_NUMBER, value=value, suffix=suffix, label=text)
    m = _RETIRED_MULT.search(text)
    if m:
        raw = (m.group(1) or m.group(2) or "").lower()
        n = float(raw) if re.match(r"^\d", raw) else _WORDNUM.get(raw)
        if n:
            return kt(KT_MULTIPLIER, value=_fmt_value(n), suffix="×", label="", subtitle="")
    b = _BARE.match(text)
    if b:
        return kt(KT_NUMBER, value=_fmt_value(float(b.group(2).replace(",", ""))), suffix="",
                  label=(b.group(1) or "").upper(), subtitle="")
    if tid in _TYPED_RETIRED or len(text.split()) > 6:
        return kt(KT_STATEMENT, text=text, label="The question" if ("QUESTION" in tid or text.endswith("?")) else "")
    sub = str(ov.get("subtitle") or ov.get("label") or "")
    return kt(KT_KEYWORD, text=text, label=sub if len(sub) <= 28 else "")


# --------------------------------------------------------------------------- #
# One lane: every look keeps its least time
# --------------------------------------------------------------------------- #
PRIORITY = {"title": 100, "map": 90, "chart": 85, "document": 84, "compare": 82, "ring": 80, "date": 78,
            "number": 76, "person": 70, "image": 60, "lower-third": 58, "annotation": 50, "text": 40, "other": 30}


def _priority(ov: dict) -> float:
    if ov.get("type") == "title":
        return PRIORITY["title"]
    fam = family_of(ov)
    p = PRIORITY.get(fam, 30)
    if ov.get("dataLook"):
        p += min(6.0, float(ov.get("_score") or 0))
        if ov.get("template") == KT_CHIP:
            p -= 22                 # a minor figure gives way to a picture look
    return p


def schedule(overlays: List[dict], fps: int, total_frames: int) -> Tuple[List[dict], List[dict]]:
    """
    Place every overlay in one lane, highest priority first: each at its word (or its old start) or up to its
    slack later, for at least min_frames and up to its wanted length, never over another. A look that cannot
    have its least time anywhere in its window is left out (logged), never cut short. Returns (placed in time
    order, dropped rows).
    """
    breath = int(round(BREATH * fps))
    items = []
    for i, ov in enumerate(overlays):
        if not isinstance(ov, dict):
            continue
        at = ov.get("_at")
        want_start = int(round(float(at) * fps)) - int(round(MAX_LEAD_S * fps)) if at is not None else int(ov.get("startFrame") or 0)
        want_start = max(0, want_start)
        need = min_frames(ov, fps)
        early = 0
        if ov.get("dataLook"):
            want = max(need, int(round(want_seconds(ov) * fps)))
            slack = int(round(SLACK["data"] * fps))
        else:
            old = int(ov.get("durationInFrames") or 0)
            want = max(need, old, int(round(want_seconds(ov) * fps)) if old < need else old)
            slack = int(round(SLACK["map" if family_of(ov) == "map" else "kept"] * fps))
            if family_of(ov) in ("image", "person", "annotation", "other"):
                early = int(round(EARLY_KEPT * fps))     # a picture look may come a beat early to keep its time
        if ov.get("type") == "title":
            need = want = max(1, int(ov.get("durationInFrames") or need))
            slack = 0
        items.append({"i": i, "ov": ov, "start": want_start, "need": need, "want": want, "slack": slack,
                      "early": early, "pri": _priority(ov)})
    for it in items:
        it["lo"] = max(0, it["start"] - it["early"])
        it["hi"] = it["start"] + it["slack"]
    placed: List[dict] = []                    # items with "s": each holds [s, s + need + breath) at least
    dropped: List[dict] = []

    def blockers(s: int, need: int, skip=None) -> List[dict]:
        return [p for p in placed if p is not skip and s < p["s"] + p["need"] + breath and s + need + breath > p["s"]]

    def fits(it: dict, s: int, skip=None) -> bool:
        return 0 <= s and s + it["need"] <= total_frames and not blockers(s, it["need"], skip)

    def place(it: dict) -> bool:
        # 1. the first free start in its window
        s = it["lo"]
        while s <= it["hi"]:
            if s + it["need"] > total_frames:
                break
            bl = blockers(s, it["need"])
            if not bl:
                it["s"] = s
                return True
            s = max(p["s"] + p["need"] + breath for p in bl)
        # 2. make room: move one look that is in the way inside its own window (never shorter)
        for s in (it["start"], it["lo"], it["hi"]):
            if s < 0 or s + it["need"] > total_frames:
                continue
            bl = blockers(s, it["need"])
            if len(bl) != 1 or bl[0]["pri"] >= 100:
                continue
            p = bl[0]
            for ps in (s + it["need"] + breath, s - p["need"] - breath):
                if p["lo"] <= ps <= p["hi"] and fits(p, ps, skip=p):
                    old = p["s"]
                    p["s"] = ps
                    if not blockers(s, it["need"]):
                        it["s"] = s
                        return True
                    p["s"] = old
        return False

    for it in sorted(items, key=lambda x: (-x["pri"], x["start"])):
        if place(it):
            placed.append(it)
            continue
        dropped.append({"template": it["ov"].get("template"), "at": round(it["start"] / fps, 2),
                        "said": it["ov"].get("said") or it["ov"].get("text") or "",
                        "why": "no room for its full animation (it would have been cut short)"
                        if it["start"] + it["need"] <= total_frames else "too close to the end of the video"})
    # every placed look as long as it wants, up to the next one
    placed.sort(key=lambda p: p["s"])
    for k, p in enumerate(placed):
        nxt = placed[k + 1]["s"] if k + 1 < len(placed) else total_frames + breath
        dur = max(p["need"], min(p["want"], nxt - breath - p["s"], total_frames - p["s"]))
        p["ov"]["startFrame"] = int(p["s"])
        p["ov"]["durationInFrames"] = int(dur)
    return [p["ov"] for p in placed], dropped


def short_overlays(overlays: List[dict], fps: int) -> List[dict]:
    """Every overlay shorter than its family's entry + least hold + exit (should be none)."""
    bad = []
    for ov in overlays:
        if not isinstance(ov, dict) or ov.get("type") == "title":
            continue
        if int(ov.get("durationInFrames") or 0) < min_frames(ov, fps):
            bad.append({"template": ov.get("template"), "startFrame": ov.get("startFrame"),
                        "frames": ov.get("durationInFrames"), "least": min_frames(ov, fps)})
    return bad


def overlapping(overlays: List[dict]) -> List[Tuple[int, int]]:
    """Pairs of overlays that are on screen at the same time (should be none)."""
    ov = sorted([o for o in overlays if isinstance(o, dict)], key=lambda o: int(o.get("startFrame") or 0))
    bad = []
    for a, b in zip(ov, ov[1:]):
        if int(b["startFrame"]) < int(a["startFrame"]) + int(a["durationInFrames"]):
            bad.append((int(a["startFrame"]), int(b["startFrame"])))
    return bad


# --------------------------------------------------------------------------- #
# The whole pass over a timeline
# --------------------------------------------------------------------------- #
NEAR_SECONDS = 3.5          # a kept figure look this close to a new data look says the same thing: replaced


def strip_private(ov: dict) -> dict:
    return {k: v for k, v in ov.items() if not k.startswith("_")}


def finish(doc: dict, *, plan_data: bool = True) -> Dict[str, Any]:
    """
    Re-plan the data looks of a timeline in place and give every overlay its full animation:
      * the data moments of the narration as KT looks (plan);
      * retired looks rewritten as their clean equivalent - or left out when a new data look says the same;
      * figure / date / year looks of the old planner replaced where a new data look lands nearby;
      * one lane, every look at least its family's minimum (schedule).
    Returns the report: counts by family, the moments, what was removed, added and dropped.
    """
    fps = int(doc.get("fps") or 30)
    total = int(doc.get("durationInFrames") or 0) or max(
        [int(s.get("startFrame") or 0) + int(s.get("durationInFrames") or 0) for s in doc.get("scenes") or []] + [0])
    before = [dict(o) for o in doc.get("overlays") or [] if isinstance(o, dict)]
    new, log = plan(words_of(doc), fps) if plan_data else ([], [])
    # A brand kit that names its looks: only the KT looks it allows (another style of the same kind first).
    allowed = templates.allowed()
    if allowed is None:
        picks = (((doc.get("meta") or {}).get("brandKit") or {}).get("picks") or {}) if isinstance(
            doc.get("meta"), dict) else {}
        if isinstance(picks.get("looks"), list):
            allowed = frozenset(str(x) for x in picks["looks"])
    if allowed is not None:
        kept_new = []
        for o in new:
            if o["template"] not in allowed:
                alt = _alternate(strip_private(o))
                if alt is None or alt["template"] not in allowed:
                    for row in log:
                        if row.get("look") == o["template"] and abs(row["at"] - float(o["_at"])) < 0.01:
                            row["look"], row["why"] = None, "the brand kit does not allow this look"
                    continue
                o = {**o, **alt, "variant": variant_of(alt["template"])}
            kept_new.append(o)
        new = kept_new
    # The video's own colour for the new looks: the theme / style the figure looks had (a kit's "accent2").
    themes: Dict[str, int] = {}
    styles: Dict[str, int] = {}
    for o in before:
        if str(o.get("template") or "").startswith("LIB_VR_"):
            continue        # the VidRush date looks' "serif" / "typewriter" is their lettering, not a colour
        if o.get("theme") and (str(o.get("template") or "") in FIGURE_LOOKS or o.get("template") in RETIRED_IDS
                               or o.get("template") in KT_DATA):
            themes[str(o["theme"])] = themes.get(str(o["theme"]), 0) + 3
        elif o.get("theme"):
            themes[str(o["theme"])] = themes.get(str(o["theme"]), 0) + 1
        if o.get("style"):
            styles[str(o["style"])] = styles.get(str(o["style"]), 0) + 1
    for o in new:
        if themes and "theme" not in o:
            o["theme"] = max(themes.items(), key=lambda kv: kv[1])[0]
        if styles and "style" not in o:
            o["style"] = max(styles.items(), key=lambda kv: kv[1])[0]
    new_at = [float(o["_at"]) for o in new]

    def near_new(ov: dict) -> bool:
        t = int(ov.get("startFrame") or 0) / fps
        return any(abs(t - a) <= NEAR_SECONDS for a in new_at)

    kept: List[dict] = []
    removed: List[dict] = []
    remapped: List[dict] = []
    for ov in before:
        tid = str(ov.get("template") or "")
        if tid in KT_DATA and (ov.get("dataLook") or (plan_data and allowed is None)):
            # this planner's own looks, and the build's KT figure leads (treatments.BOLD_COUNT_LOOK): every
            # figure is ranked and placed again here, so one moment is never shown twice
            removed.append({"template": tid, "at": round(int(ov.get("startFrame") or 0) / fps, 2), "why": "re-planned"})
            continue
        if tid in RETIRED_IDS:
            if near_new(ov) or (plan_data and allowed is None
                                and (tid in ("LIB_BT_COUNT", "TEXT_LABEL_PILL_V1") or tid in _DATE_RETIRED)):
                removed.append({"template": tid, "at": round(int(ov.get("startFrame") or 0) / fps, 2),
                                "text": ov.get("text"), "why": "retired; its words are a new data look"
                                if near_new(ov) else "retired figure look; the data planner covers figures"})
                continue
            nv = remap_retired(ov)
            if allowed is not None and nv["template"] not in allowed:
                kept.append(ov)
                continue
            remapped.append({"from": tid, "to": nv["template"], "at": round(int(ov.get("startFrame") or 0) / fps, 2),
                             "text": ov.get("text")})
            kept.append(nv)
            continue
        if tid in FIGURE_LOOKS and plan_data and near_new(ov):
            removed.append({"template": tid, "at": round(int(ov.get("startFrame") or 0) / fps, 2),
                            "text": ov.get("text"), "why": "a new data look says the same"})
            continue
        kept.append(ov)
    placed, dropped = schedule(kept + new, fps, total)
    doc["overlays"] = [strip_private(o) for o in placed]
    shown_ids = {id(o) for o in placed}
    added = [o for o in new if id(o) in shown_ids]
    for row in log:
        if row.get("look"):
            hit = next((o for o in added if abs(float(o["_at"]) - row["at"]) < 0.01 and o["template"] == row["look"]),
                       None)
            if hit is None:
                hit_any = next((o for o in new if abs(float(o["_at"]) - row["at"]) < 0.01), None)
                row["why"] = "no room in the lane (a higher-priority look is on screen)"
                row["look"] = None if hit_any is not None else row["look"]
            else:
                row["startFrame"] = hit["startFrame"]
                row["seconds"] = round(hit["durationInFrames"] / fps, 2)

    def fams(ovs: List[dict]) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for o in ovs:
            c[family_of(o)] = c.get(family_of(o), 0) + 1
        return dict(sorted(c.items()))

    short_before = short_overlays(before, fps)
    return {
        "fps": fps, "overlaysBefore": len(before), "overlaysAfter": len(doc["overlays"]),
        "byFamilyBefore": fams(before), "byFamilyAfter": fams(doc["overlays"]),
        "added": [{"template": o["template"], "at": round(o["startFrame"] / fps, 2),
                   "seconds": round(o["durationInFrames"] / fps, 2), "said": o.get("said", "")} for o in added],
        "addedByLook": {t: sum(1 for o in added if o["template"] == t) for t in sorted({o["template"] for o in added})},
        "removed": removed, "remapped": remapped,
        "dropped": dropped, "moments": log,
        "shortBefore": len(short_before), "shortAfter": len(short_overlays(doc["overlays"], fps)),
        "overlapAfter": len(overlapping(doc["overlays"])),
    }
