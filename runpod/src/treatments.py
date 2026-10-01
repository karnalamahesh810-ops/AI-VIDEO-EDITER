"""
The visual treatment planner: what each beat gets besides its footage.

A professionally edited faceless documentary is not footage, footage,
footage. Every twenty to forty seconds the edit leaves the picture for a
treatment that the line itself asks for: a percentage gets a gauge, a fall
of twelve feet gets a trend figure, a place gets a map, a route a drawn
route, a quote a quote card, a question a typed question, a warning a red
strip, a date a date card, a chapter a chapter title. The planner reads the
narration for those cues (and keeps whatever the AI director already
proposed), picks a template from the registry that the style pack prefers,
fills its props with the line's own words and numbers, and lays it on the
timeline with an entrance, an exit and a sound.

Rhythm is a secondary signal only: treatments are not inserted on a timer,
but two never crowd each other, a family is not repeated within a minute,
and after a long stretch of plain footage a light label is allowed where
the line offers one.

Variety (the owner, 2026-09-29: "the same look every 30 seconds"): every
choice - the director's hints included - goes through one rotation over all
the looks that carry the cue, built-in and library alike. A look is not
shown twice within LOOK_GAP (four minutes) while another fits, two text beats
in a row never share a family, and the order is shuffled per video so two
videos do not open on the same looks. The banned headline looks
(templates.BANNED) are never chosen, nor are the long-text looks with a bar,
rule or underline beside or under the words (NOT_AUTO_LOOKS). Some things
always show: a clear figure (it counts up) and the first mention of a named
person (a full-screen introduction, at most one per 45 s).

Dates and times (the owner, 2026-10-01, after four VidRush exports): about one
date or time graphic every two to three minutes, never on every mention, in
four looks with fixed places and one colour theme per video - a big centred
date, a time card top-left, a typed "Place, Year" caption bottom-left, a year
on a line for a jump in years (see VR_LOOKS, vr_moment, _Planner._vr_select).
Nothing the narration did not say: no worked-out weekday, no year it did not
name, no place it did not name (or its section's region).
"""
import datetime
import re
import zlib
from typing import Any, Dict, List, Optional

from . import config, numwords, templates
from .transcribe import Segment

# Read off VidRush's own timelines (an animation block every 8-10 s through
# the first two minutes, then every 15-25 s): denser than a "treatment every
# 20-40 s" documentary, because a faceless channel's viewer is on a phone.
MIN_GAP = 8.0           # seconds between any two treatments
TAG_GAP = 5.0           # a tag riding on the footage may follow sooner
QUIET_MAX = 18.0        # after this long with plain footage a light label is allowed
# Graphics density "minimal" (news compilation): one figure per this many seconds.
MINIMAL_FIGURE_GAP = 45.0
# The forecast-model map (LIB_WX_*): at most one per this many seconds.
FORECAST_GAP = 75.0
# (A storm's name is not a forecast: "the nor'easter left 12,000 people without
# power" is a count, and a news story names its nor'easter on every line.)
_FORECAST = re.compile(r"\b(gusts?|wind speeds?|winds? (?:of|up to|near)|forecast|storm (?:track|system|centre|center)|"
                       r"low[- ]pressure|inches of rain|rainfall|heavy rain|snowfall|the (?:storm|system) (?:moves|tracks|"
                       r"will move|is moving|pushes))\b", re.I)
_FORECAST_RAIN = re.compile(r"\b(rain|rainfall|inches|flood(?:ing)? rain|snow|downpours?)\b", re.I)
_FORECAST_WIND = re.compile(r"\b(wind|gusts?|mph)\b", re.I)
# The figures a forecast map's legend stands for: a wind speed, a rainfall.
_WX_UNITS = {"MPH", "KM/H", "KPH", "KNOTS", "IN", "INCHES", '"'}
_PER_HOUR = re.compile(r"\b(?:miles|kilometers|kilometres) (?:per|an) hour\b", re.I)
FAMILY_GAP = 45.0       # the same category is not repeated within this
SFX_GAP = 12.0          # seconds between two sounds
HIGH_GAP = 5.0          # a chapter, a number or a map may follow anything after this
HOOK_SECONDS = 120.0    # the opening, where the cadence is tightest
REPEAT_GAP = 90.0       # the same figure is not drawn again as a graphic within this
# Timing (the owner, 2026-09-30): a graphic starts on the spoken word that
# triggers it - never before it, at most PRE_ROLL_FRAMES early for
# anticipation - and ends when the phrase that says it ends plus TAIL. Its
# time on screen is capped by kind (LAYOUT_WINDOWS: tags and labels 2-4 s,
# cards and full-screen graphics 2.5-5 s, maps and charts up to TALKING_MAX
# only while the narration keeps talking about them), and it is never
# shorter than its own animation in and out (animation_seconds).
PRE_ROLL_FRAMES = 2
TAIL = 0.4
TALKING_MAX = 6.0
HOOK_GAP = 6.0          # ... and any treatment may follow another after this
LOOK_GAP = 240.0        # the same look is not shown again within four minutes (while another fits)
TEXT_GAP = 10.0         # two text looks (headline, phrase, quote, question...) never closer than this
SOFT_TEXT_GAP = 20.0    # a line's own typed / term / headline look waits this long after the last text look
PERSON_FULL_GAP = 45.0  # at most one full-screen person introduction per this
BREATH = 0.3            # a must-show graphic lands this long after the previous one leaves
SLIDE_SLACK = 0.4       # ... and may wait at most this long after its word for it (else it cuts the other short)
PHOTO_WINDOW = 300.0    # a photo look is used at most PHOTO_MAX times per this
PHOTO_MAX = 2
TYPE_START = 6          # typing contract: the first letter lands at frame 6 ...
TYPE_HOLD = 0.9         # ... and a typed line stays this long after its last letter
STRONG_CUES = {"percent", "change", "then-now", "big-number", "date", "route", "place", "quote", "chapter",
               "money", "money-compare", "series", "shares", "ratio", "measurement", "change-length",
               "compare-values", "recording", "document", "count", "datetime", "time-of-day", "person-full"}
# The owner: the full-screen layout is for percentages, money and comparisons,
# not for titles or quotes. Only these cues (and mapped places) become
# animation scenes; a plain line without footage borrows a matching shot.
SCENE_CUES = {"percent", "change", "then-now", "big-number", "money", "money-compare", "series", "shares",
              "ratio", "measurement", "change-length", "compare-values", "count"}
DATE_CUES = ("datetime", "date", "time-of-day")
# ------------------------------------------------ overlay layout (the owner, 2026-09-28 evening)
# One figure is a compact overlay in a corner; several values (or a timeline)
# are full screen for their moment; text rides on the picture (see layout_class).
SINGLE_FIGURE_CUES = {"percent", "change", "change-length", "big-number", "money", "measurement", "ratio", "count"}
FULL_DATA_CUES = {"series", "shares", "compare-values", "ranking", "then-now", "money-compare", "sequence", "years",
                  "span", "steps"}
TEXT_CUES = {"headline", "key-phrase", "statement", "fact", "term", "typewriter", "caption", "question", "quote",
             "warning", "date", "datetime", "list", "summary", "age", "time-of-day", "chapter"}
# (min, max) seconds on screen by layout class (the owner's caps, 2026-09-30):
# a figure or a text tag is a label (2-4 s), a card or a full-screen graphic
# 2.5-5 s (a text look drawn as a card takes the card window), a map needs
# its fly-in (3.5 s) and may run to TALKING_MAX while the narration stays on it.
LAYOUT_WINDOWS = {"figure": (2.0, 4.0), "full": (2.5, 5.0), "map": (3.5, 5.0), "cutaway": (2.5, 5.0),
                  "text": (2.0, 4.0),
                  # A named person's full-screen introduction: long enough to read a name and a role.
                  "person": (3.0, 5.0),
                  # The LibPersist family ("ps-"): built to ride on footage across cuts, so it
                  # keeps a longer hold than the figure window's 4 s - at most 8 s since the
                  # owner's "don't keep it longer" (2026-09-30; it was 12 s).
                  "persist": (5.0, 8.0)}
# A look's own animation, when the registry gives no "sfxAt": its entrance
# lands about here (frames at 30 fps); every look leaves over its last
# EXIT_FRAMES; the landed look is seen at least SETTLE seconds in between.
ENTRANCE_FRAMES = 15
EXIT_FRAMES = 12
SETTLE = 0.5
# Cues whose looks are words on screen: two of them in a row never share a family.
TEXT_BEAT_CUES = {"headline", "key-phrase", "statement", "fact", "term", "question", "warning", "quote",
                  "typewriter", "caption", "chapter"}
# When a cue's own looks are all used up, these stand in (a count is a big number, a caption a key phrase).
CUE_FALLBACK = {"count": ["big-number"], "key-phrase": ["caption"], "caption": ["key-phrase"],
                "statement": ["fact", "key-phrase"], "fact": ["statement", "key-phrase"], "term": ["key-phrase"],
                "headline": ["key-phrase"], "question": ["typewriter"]}
# The director's overlay types, read as the cue they ask for; the look then
# comes out of the same rotation as everything else.
HINT_CUES = {"sentence-highlight": "key-phrase", "underline-title": "headline", "swoosh-title": "headline",
             "word-type": "headline", "red-strip": "headline", "kicker": "key-phrase", "callout": "key-phrase",
             "typewriter": "typewriter", "memo-box": "typewriter", "bar-title": "typewriter", "quote": "quote",
             "chapter": "headline", "banner": "headline", "title": "headline", "date-stamp": "date",
             "clock-badge": "time-of-day", "ring-stat": "percent", "stat": "percent", "donut": "percent",
             "counter": "big-number", "number-roll": "big-number", "stat-tag": "big-number"}

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)", re.I)
_NUMBER_UNIT = re.compile(
    r"(\$?\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|acre[- ]feet|acre[- ]foot|feet|foot|ft|miles?|"
    r"meters?|metres?|km|acres?|gallons?|people|homes?|structures?|deaths?|hours?|minutes?|days?|"
    r"tons?|degrees|inches|dollars|residents|families|vehicles|square miles)\b", re.I)
_CHANGE = re.compile(
    r"\b(fell|fallen|dropped|declined|decreased|lost|shrank|rose|risen|increased|climbed|gained|"
    r"jumped|surged|grew)\b[^.]{0,60}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft|miles|meters|inches|"
    r"degrees|million|billion|thousand)?", re.I)
_DATE = re.compile(rf"\b(({_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*(?:1[89]|20)\d\d|({_MONTHS})\s+(?:1[89]|20)\d\d)\b", re.I)
# Dates as narrators say them: "on the fifteenth of September", "August 21st",
# "September 15, 2026". The old pattern needed a year, so the Glen Canyon
# opening line got a typed sentence instead of a date card.
_ORDINAL_DAYS = {w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split())}
_ORDINAL_DAYS.update({f"twenty-{w}": 20 + n for w, n in list(_ORDINAL_DAYS.items())[:9]})
_ORDINAL_DAYS.update({"thirtieth": 30, "thirty-first": 31})
_DAY = (r"(\d{1,2})(?:st|nd|rd|th)?|("
        + "|".join(sorted((re.escape(w).replace(r"\-", "[- ]") for w in _ORDINAL_DAYS), key=len, reverse=True))
        + ")")
_DATE_DM = re.compile(rf"\b(?:the\s+)?(?:{_DAY})\s+of\s+({_MONTHS})\b(?:,?\s+((?:1[89]|20)\d\d)\b)?", re.I)
_DATE_MD = re.compile(rf"\b({_MONTHS})\s+(?:the\s+)?(?:{_DAY})\b(?:,?\s+((?:1[89]|20)\d\d)\b)?", re.I)
_DATE_MY = re.compile(rf"\b({_MONTHS})\s+((?:1[89]|20)\d\d)\b", re.I)
# "Sept. 25", "Aug 21st, 2026" (capitalised, so "mar" the verb is never a month)
# and "9/25/2026". The label always spells the month out: "SEPTEMBER 25".
_ABBR_MONTHS = {"jan": "JANUARY", "feb": "FEBRUARY", "mar": "MARCH", "apr": "APRIL", "jun": "JUNE", "jul": "JULY",
                "aug": "AUGUST", "sep": "SEPTEMBER", "sept": "SEPTEMBER", "oct": "OCTOBER", "nov": "NOVEMBER",
                "dec": "DECEMBER"}
_DATE_ABBR = re.compile(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|JAN|FEB|MAR|APR|JUN|JUL|AUG|SEPT?|OCT|NOV|DEC)"
                        r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+((?:1[89]|20)\d\d)\b)?")
_DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/((?:19|20)\d\d)\b")
_MONTH_NAMES = [m.upper() for m in _MONTHS.split("|")]
_WEEKDAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)


def date_in(text: str) -> Optional[tuple]:
    """(label, offset) of the first calendar date a line names - 'SEPTEMBER 15',
    'AUGUST 21, 2026', 'MARCH 2026' - or None."""
    d = date_parts(text)
    return (d["label"], d["start"]) if d else None


def date_parts(text: str) -> Optional[dict]:
    """
    The first calendar date a line names, in parts: {label, start, end,
    month ('SEPTEMBER'), day (int or None), year (int or None)} - or None.
    """
    found = []
    for rx, kind in ((_DATE_DM, "dm"), (_DATE_MD, "md"), (_DATE_MY, "my"), (_DATE_ABBR, "abbr"), (_DATE_NUM, "num")):
        for m in rx.finditer(text or ""):
            if kind == "dm":
                num, word, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
            elif kind == "md":
                month, num, word, year = m.group(1), m.group(2), m.group(3), m.group(4)
            elif kind == "abbr":
                month, num, word, year = _ABBR_MONTHS[m.group(1).lower()], m.group(2), None, m.group(3)
            elif kind == "num":
                mo = int(m.group(1))
                if not 1 <= mo <= 12:
                    continue
                month, num, word, year = _MONTH_NAMES[mo - 1], m.group(2), None, m.group(3)
            else:
                month, year, num, word = m.group(1), m.group(2), None, None
            day = int(num) if num else (_ORDINAL_DAYS.get(re.sub(r"\s+", "-", word.lower())) if word else None)
            if kind != "my" and not (day and 1 <= day <= 31):
                continue
            label = month.upper() + (f" {day}" if day else "")
            if year:
                label += f", {year}" if day else f" {year}"
            found.append((m.start(), -len(label), {"label": label, "start": m.start(), "end": m.end(),
                                                   "month": month.upper(), "day": day or None,
                                                   "year": int(year) if year else None}))
            break
    if not found:
        return None
    return min(found, key=lambda f: (f[0], f[1]))[2]


# Times of day as narrators say them: "3:45 pm", "3 p.m.", "at noon",
# "midnight", "at dawn", "seven o'clock that evening".
_TIME_AMPM = re.compile(r"\b(\d{1,2})(?::([0-5]\d))?\s*([ap])\.?\s?m\b\.?", re.I)
_TIME_AT = re.compile(r"\b(?:at|by|around|about|until|before|after|near|just after|just before)\s+(\d{1,2}):([0-5]\d)\b",
                      re.I)
_TIME_WORD = re.compile(r"\b(noon|midday|midnight)\b", re.I)
_TIME_LIGHT = re.compile(r"\b(?:at|by|before|after|around|until|near|just after|just before)\s+"
                         r"(dawn|dusk|sunrise|sunset|daybreak|nightfall|first light)\b", re.I)
_CLOCK_WORDS = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split())}
_TIME_OCLOCK = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
                          r"o['’]?\s?clock\b(?:\s+(in the morning|that morning|in the afternoon|that afternoon|"
                          r"in the evening|that evening|at night|that night))?", re.I)


def time_in(text: str) -> Optional[tuple]:
    """(label, offset) of the first time of day a line names - '3:45 PM', '3 PM', '12:00 AM', 'DAWN' - or None."""
    text = text or ""
    found = []
    # (offset, how specific - an "am/pm" reading beats a bare "3:45" at the same place, label)
    for m in _TIME_AMPM.finditer(text):
        h = int(m.group(1))
        if 1 <= h <= 12:
            found.append((m.start(1), 0, f"{h}{':' + m.group(2) if m.group(2) else ''} {m.group(3).upper()}M"))
            break
    for m in _TIME_AT.finditer(text):
        h = int(m.group(1))
        if 0 <= h <= 23:
            found.append((m.start(1), 1, f"{h}:{m.group(2)}"))
            break
    m = _TIME_WORD.search(text)
    if m:
        found.append((m.start(), 0, "12:00 AM" if m.group(1).lower() == "midnight" else "12:00 PM"))
    m = _TIME_LIGHT.search(text)
    if m:
        found.append((m.start(1), 0, m.group(1).upper()))
    m = _TIME_OCLOCK.search(text)
    if m:
        raw = m.group(1).lower()
        h = int(raw) if raw.isdigit() else _CLOCK_WORDS.get(raw, 0)
        if 1 <= h <= 12:
            part = (m.group(2) or "").lower()
            ampm = " AM" if "morning" in part else " PM" if part else ""
            found.append((m.start(), 0, f"{h}:00{ampm}"))
    if not found:
        return None
    start, _prio, label = min(found)
    return label, start


# A span of time, the countdown look's only job (the owner, 2026-09-30: a
# plain "WEDNESDAY" drew a countdown): "3 days later", "two weeks earlier",
# "within 48 hours", "over the next 72 hours", "for three days".
_SPAN_WORDS = ("a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
               "sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety")
_SPAN_NUM = rf"(\d{{1,3}}|(?:{_SPAN_WORDS})(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?)"
_SPAN_UNIT = r"(hours?|days?|nights?|weeks?)"
_TIME_SPAN = re.compile(
    rf"\b{_SPAN_NUM}[\s-]+{_SPAN_UNIT}\s+(later|earlier|after|before|ago|on)\b"
    rf"|\b(?:within|in|for|after|over|during)\s+(?:the\s+(?:next|past|last|first|following)\s+)?"
    rf"{_SPAN_NUM}[\s-]+{_SPAN_UNIT}\b", re.I)


def time_span_in(text: str) -> Optional[tuple]:
    """(label, value, offset, spoken number) of the first span of time a line names -
    ('3 DAYS LATER', 3.0, ...), ('48 HOURS', 48.0, ...) - or None."""
    m = _TIME_SPAN.search(text or "")
    if not m:
        return None
    num, unit, tail = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), "")
    raw = num.lower()
    value = float(raw) if raw.isdigit() else (1.0 if raw in ("a", "an") else _spelled_value(raw.replace("-", " ")))
    if not value or value <= 0:
        return None
    unit = unit.lower().rstrip("s")
    unit = unit if value == 1 else unit + "s"
    shown = str(int(value)) if float(value).is_integer() else str(value)
    label = " ".join(x for x in (shown, unit.upper(), (tail or "").upper()) if x)
    return label, float(value), m.start(1) if m.group(1) else m.start(4), num.split()[0].split("-")[0]


def _weekday_before(text: str, offset: int) -> str:
    """'MONDAY' when the date is introduced by its weekday ("On Monday, September 15...")."""
    m = None
    for m2 in _WEEKDAY.finditer(text[max(0, offset - 24):offset + 1]):
        m = m2
    return m.group(1).upper() if m else ""
_YEAR = re.compile(r"\b((?:1[89]|20)\d\d)\b")
_QUOTE = re.compile(r"[“\"]([^”\"]{12,160})[”\"]")
_SAID = re.compile(r"\b(said|says|warned|warns|according to|told|wrote|called it|described it as|put it)\b", re.I)
_WARN = re.compile(r"\b(warning|emergency|critical|danger(?:ous)?|evacuat\w*|dead pool|record (?:low|high|crest)|"
                   r"life-threatening|catastroph\w*|fatal|deadly|collapse)\b", re.I)
_VS = re.compile(r"\b(versus|vs\.?|compared (?:to|with))\b", re.I)
_ROUTE = re.compile(r"\bfrom\s+([A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+){0,3})\s+to\s+([A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+){0,3})")
_TWO_YEARS = re.compile(r"\b((?:19|20)\d\d)\b[^.]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft)?[^.]{0,60}?\b((?:19|20)\d\d)\b[^.]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft)?", re.I)
_UNIT_SHORT = {"feet": "FT", "foot": "FT", "ft": "FT", "mile": "MI", "miles": "MI", "meter": "M", "meters": "M",
               "metre": "M", "metres": "M", "km": "KM", "percent": "%", "%": "%", "million": "MILLION",
               "billion": "BILLION", "thousand": "THOUSAND", "degrees": "°", "inches": "IN", "dollars": "USD",
               "acre-feet": "ACRE-FT", "acre-foot": "ACRE-FT", "acres": "ACRES", "acre": "ACRES",
               "gallons": "GAL", "gallon": "GAL",
               "square miles": "SQ MI"}

CARD_KINDS = {"card", "map"}


def pack_for(brief: Optional[dict], requested: str = "") -> dict:
    """The style pack: the one asked for, else the one the story's kind suggests."""
    if requested and requested in templates.style_packs():
        return dict(templates.style_pack(requested), id=requested)
    kind = (brief or {}).get("kind") or ""
    name = {"news": "news", "weather": "weather", "disaster": "weather", "history": "history",
            "biography": "history", "science": "tech", "explainer": "documentary"}.get(kind, "documentary")
    return dict(templates.style_pack(name), id=name)


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _subject_words(shot: dict, seg: Segment, n: int = 4) -> str:
    subject = (shot.get("subject") or "").strip()
    if subject:
        return subject[:60]
    words = [w for w in re.findall(r"[A-Za-z][\w'-]*", seg.text) if w[0].isupper()]
    return " ".join(words[:n])[:60]


_LABEL_SKIP = set("""a an the its their his her our this that these those of in for at to on by from with as
and or but so than then now just only still more less most over under down up since during about around nearly
almost roughly some all is are was were be been being will would could can may might must should has have had
do does did means meant mean says said shows showed which who whom whose what when where while it they we you
beneath below above across along behind beyond inside outside through toward towards within without underneath
per each every away ago later before after""".split())


# Never a label (the owner, 2026-09-30: a number looked "GREG ABBOTT", "LOOK
# LIKE", "PEOPLE"): verbs and filler that follow or precede a figure.
_NOT_A_LABEL = _LABEL_SKIP | set("""look looks looked like likes get gets got getting make makes making see sees saw
seeing go goes went going gone come comes came coming take takes took taking know knows knew think thinks thought
want wants wanted need needs needed feel feels felt seem seems seemed become becomes became keep keeps kept put puts
let lets say tell tells told show call calls give gives gave find finds found leave leaves turn turns turned hit hits
reach reaches remain remains stay stays rise rises rose fall falls fell drop drops use uses used cost costs paid pay
hold holds held run runs ran live lives lived work works worked last next just also even really very already yet
again there here if because though although whether not no never ever another other such same own much many few
several lot lots kind sort way thing things something anything everything nothing someone anyone everyone ones
time times today tonight tomorrow yesterday now then later earlier ago than rather quite enough alone""".split())
# Words that tie a noun phrase to a figure after it ("a death toll of 27", "rainfall totals reached 15").
_LINKS = {"of", "at", "to", "reached", "hit", "topped", "passed", "exceeded", "was", "is", "were", "are", "now",
          "stood", "rose", "fell", "climbed", "jumped", "dropped", "least", "more", "nearly", "about", "around",
          "over", "almost", "roughly", "just", "than", "up", "down", "totaled", "totalled", "hits", "reaches"}


def _noun_after(text: str, match_end: int) -> str:
    """The counted noun a figure belongs to ("26% capacity", "26 percent of its
    capacity" -> CAPACITY, "12 inches of rain" -> RAIN); nothing when the next
    words are a verb, filler or a proper name ("26% means...", "40 percent look
    like...", "4,000 Greg Abbott...")."""
    tail = text[match_end:match_end + 60]
    tail = re.split(r"[.;:!?,]", tail, maxsplit=1)[0]
    words = re.findall(r"[A-Za-z][\w'-]*", tail)
    i = 0
    # "to" is not skipped: "cost $1.4 billion to build" names no noun.
    while i < len(words) and words[i].lower() in ("of", "in", "for", "at", "the", "its", "their", "his", "her", "our",
                                                  "a", "an", "all"):
        i += 1
    out = []
    for w in words[i:i + 3]:
        lw = w.lower()
        if lw in _NOT_A_LABEL or w[0].isupper() or lw.endswith("ly") or "'" in w:
            break
        out.append(w)
        if len(out) == 2:
            break
    if out and re.fullmatch(_COUNTABLE_WORDS, out[0].lower()):
        # "40 million people depend..." counts PEOPLE, not "PEOPLE DEPEND".
        out = out[:1]
    elif len(out) == 2 and (out[1].lower().endswith(("ing", "ed")) and out[1].lower() not in ("red", "bed", "shed")):
        out = out[:1]                     # "acres burning", "homes flooded": the noun, not the verb after it
    return " ".join(out).upper()[:32]


def _noun_before(text: str, match_start: int) -> str:
    """The noun phrase a figure completes ("a death toll of 27", "rainfall totals
    reached 15 inches" -> DEATH TOLL, RAINFALL TOTALS), or ''. Only when a
    linking word joins them; never a verb, filler or proper name."""
    head = re.split(r"[.;:!?,]", text[:match_start])[-1]
    words = re.findall(r"[A-Za-z][\w'-]*", head)
    if not words or words[-1].lower() not in _LINKS:
        return ""
    while words and words[-1].lower() in _LINKS:
        words.pop()
    # The line's own first word is capitalised as a sentence, not as a name.
    opener = (re.findall(r"[A-Za-z][\w'-]*", text) or [""])[0]
    out: List[str] = []
    for k in range(len(words) - 1, -1, -1):
        w = words[k]
        lw = w.lower()
        if lw in _NOT_A_LABEL or lw.endswith(("ly", "ed", "ing")) or "'" in w:
            break
        if w[0].isupper() and not (k == 0 and w == opener and head.lstrip().startswith(w)):
            break                          # a name, never a label
        out.insert(0, w)
        if len(out) == 2:
            break
    if out and out[0][0].isupper() and _is_name(" ".join(out)):
        return ""
    return " ".join(out).upper()[:32]


def _figure_label(text: str, start: int, end: int, shot: dict, seg, brief: Optional[dict] = None) -> str:
    """
    The label under a number: the counted noun after it, else the noun phrase
    it completes, else the story's subject when the line names it and it is
    not a person, else nothing (the look shows the figure alone).
    """
    return _noun_after(text, end) or _noun_before(text, start) or _label_subject(shot, seg, brief)


def _label_subject(shot: dict, seg, brief: Optional[dict] = None, words: int = 3) -> str:
    """The shot's subject as a label or a chart title - never a person ('' when it is one or the line does not name it)."""
    subject = re.sub(r"\s+", " ", str((shot or {}).get("subject") or "")).strip()
    text = (getattr(seg, "text", "") or "").lower()
    if subject and not _person_like(subject, shot, brief) and len(subject.split()) <= words \
            and len(subject) <= 30 and subject.lower().split()[0] in text:
        return subject.upper()
    for place in (brief or {}).get("places") or []:
        name = str(place or "").split(",")[0].strip()
        if 3 < len(name) <= 30 and len(name.split()) <= words and re.search(
                r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", text):
            return name.upper()
    return ""


_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|trillion|thousand|[mbk]n?)?\b"
                    r"|(\d[\d,]*(?:\.\d+)?)\s*(million|billion|trillion|thousand)?\s*dollars", re.I)
_MONEY_UNIT = {"million": "M", "m": "M", "billion": "B", "b": "B", "bn": "B", "trillion": "T", "thousand": "K", "k": "K"}


def _money(text: str) -> List[tuple]:
    """[(value, unit, end)] for every amount of money in the line."""
    out = []
    for m in _MONEY.finditer(text):
        raw, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        v = _num(raw)
        if v is None:
            continue
        out.append((v, _MONEY_UNIT.get((unit or "").lower(), ""), m.end()))
    return out



# ------------------------------------------------ more data cues, case-file cues
# (the owner: more charts, numbers and comparisons; the Dr Insanity pass: a
# report or a newspaper, a recording, footage shown as footage, an archive tag.)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "twenty": 20, "hundred": 100, "a hundred": 100}
_RATIO = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|\d{1,2})\s+(?:in|out\s+of|of\s+every)\s+"
                    r"(two|three|four|five|six|seven|eight|nine|ten|twenty|a\s+hundred|hundred|\d{1,3})\b", re.I)
_MEASURE = re.compile(r"(\d[\d,]*(?:\.\d+)?)[\s-]*(feet|foot|ft|miles?|meters?|metres?|kilometers?|kilometres?|km|inches|inch)\b",
                      re.I)
_LENGTH_UNITS = {"FT", "MI", "M", "KM", "IN"}
_SIZE_WORDS = {"TALL", "HIGH", "DEEP", "LONG", "WIDE", "LOWER", "HIGHER", "BELOW", "ABOVE", "AWAY", "ACROSS",
               "UNDERWATER", "UNDERGROUND", "DOWN", "UP"}
_LENGTH_SHORT = {"feet": "FT", "foot": "FT", "ft": "FT", "mile": "MI", "miles": "MI", "meter": "M", "meters": "M",
                 "metre": "M", "metres": "M", "kilometer": "KM", "kilometers": "KM", "kilometre": "KM",
                 "kilometres": "KM", "km": "KM", "inch": "IN", "inches": "IN"}
_SERIES_UNIT = r"(percent|%|feet|ft|million|billion|thousand|acre-feet|gallons|people)"
_YEAR_VAL = re.compile(r"\b((?:19|20)\d\d)\b[^.;\d]{0,32}?(\$?\d[\d,]*(?:\.\d+)?)\s*" + _SERIES_UNIT + r"?", re.I)
_VAL_YEAR = re.compile(r"(\$?\d[\d,]*(?:\.\d+)?)\s*" + _SERIES_UNIT + r"?\s+(?:in|by)\s+((?:19|20)\d\d)\b", re.I)
_VAL_TODAY = re.compile(r"(\$?\d[\d,]*(?:\.\d+)?)\s*" + _SERIES_UNIT + r"?\s+(?:today|now)\b"
                        r"|\b(?:today|now)[^.;\d]{0,20}?(\$?\d[\d,]*(?:\.\d+)?)\s*" + _SERIES_UNIT + r"?", re.I)
_SHARE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)\b\s*(?:of\s+(?:it|that|this|them|the\s+\w+|all\s+\w+)\s+)?"
                    r"(?:goes|went|is|are|was|were|comes|came|belongs?|flows?|used)?\s*(?:to|for|by|on|in|from)?\s*"
                    r"(?:the\s+)?([a-z][a-z-]+(?:\s[a-z][a-z-]+)?)", re.I)
_LABEL_NUM = re.compile(r"\b([A-Z][a-zA-Z.'-]+(?:\s[A-Z][a-zA-Z.'-]+){0,2})\b[^.;\d]{0,24}?(\$?\d[\d,]*(?:\.\d+)?)\s*"
                        r"(million|billion|thousand|percent|%)?")
_DOC = re.compile(
    r"\b(?:according to (?:a|the|an|new|recent)\s+(?:[\w-]+\s){0,3}?(report|study|survey|analysis|document|records?|filing|audit|memo|assessment)"
    r"|(?:a|the|new|recent)\s+(?:[\w-]+\s){0,3}?(report|study|survey|analysis|audit|assessment)\s+"
    r"(?:found|finds|shows?|showed|says|said|warned|warns|estimates?|estimated|concluded|revealed)"
    r"|(records|documents|filings) show(?:ed)?"
    r"|(headlines?|newspapers?|front page)"
    r"|the (law|bill|act|ruling|lawsuit|order|agreement|compact|treaty|decree)\s+"
    r"(?:says|said|requires|required|states|stated|set|sets|gave|gives|split|splits))\b", re.I)
_RECORDING = re.compile(r"\b(911 call|phone call|voicemail|recorded (?:call|interview|message|statement)|recording|"
                        r"radio (?:interview|station|show)|podcast|told (?:a )?(?:local )?(?:radio|tv|television)|"
                        r"on tape|press conference|in an interview)\b", re.I)
_FOOTAGE_WORDS = re.compile(r"\b(footage|video shows|videos? (?:show|shows|showed|captured)|filmed|film shows|"
                            r"cameras? (?:captured|caught|recorded)|caught on camera|was recorded|broadcast|newsreel|"
                            r"live ?stream|drone (?:video|footage)|security camera|body ?cam\w*|dash ?cam\w*)\b", re.I)
_INTRO = re.compile(r"\b(this is the story|in this video|here'?s (?:how|why|what)|let'?s (?:dive|take a look|find out|look at)|"
                    r"today,? we|by the end of this|what happened next)\b", re.I)
_ARCHIVE_TITLE = re.compile(r"\b(newsreel|archive|archival|pathe|periscope|movietone|travelogue|huntley|19[0-8]\d|"
                            r"18\d\d)\b", re.I)
_CAP_STOP = set("""The A An In On At By And But Or So If When While Since From To Of For With This That These Those
It Its They Their We Our You Your He She His Her Today Now Then There Here What Why How Who Which Yet Still Just
Only Even Also After Before During About Over Under Between Across Around Nearly Almost Roughly More Less Most Some
All Every Each Both Many Much One Two Three Four Five Six Seven Eight Nine Ten Last Next First""".split()) | {
    m.capitalize() for m in _MONTHS.split("|")}
_MULT = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def _series(text: str) -> Optional[tuple]:
    """Three or more (year, value) pairs in one line: (items, unit) for a line chart."""
    def pairs(rx, y, v, u):
        out = []
        for m in rx.finditer(text):
            val = _num(m.group(v))
            if val is None or (1800 <= val <= 2100 and float(val).is_integer()):
                continue
            out.append((m.group(y), val, (m.group(u) or "").lower()))
        return out
    a = pairs(_YEAR_VAL, 1, 2, 3)
    b = pairs(_VAL_YEAR, 3, 1, 2)
    got = b if len(b) > len(a) else a
    seen, out = set(), []
    for y, v, u in got:
        if y not in seen:
            seen.add(y)
            out.append((y, v, u))
    m = _VAL_TODAY.search(text)
    if m and out:
        raw, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        v = _num(raw or "")
        if v is not None and all(abs(v - o[1]) > 1e-9 for o in out):
            out.append(("TODAY", v, (unit or "").lower()))
    if len(out) < 3:
        return None
    years = [o for o in out if o[0] != "TODAY"]
    years.sort(key=lambda o: int(o[0]))
    out = years + [o for o in out if o[0] == "TODAY"]
    unit = next((u for _y, _v, u in out if u), "")
    return [{"label": y, "value": v} for y, v, _u in out[:8]], _UNIT_SHORT.get(unit, unit.upper()[:8])


def _shares(text: str) -> Optional[list]:
    """Two or more percentages of one whole ("70 percent to farms, 20 percent to cities")."""
    out, seen = [], set()
    for m in _SHARE.finditer(text):
        v = _num(m.group(1))
        words = [w for w in (m.group(2) or "").lower().split() if w not in _LABEL_SKIP]
        if v is None or not words:
            continue
        label = " ".join(words)
        if label in seen:
            continue
        seen.add(label)
        out.append({"label": label.upper()[:22], "value": v})
    if len(out) >= 2 and sum(i["value"] for i in out) <= 100.5:
        return out[:5]
    return None


def _ratio(text: str) -> Optional[dict]:
    """"one in four", "3 out of 10": value, total and what is counted."""
    m = _RATIO.search(text)
    if not m:
        return None
    a, b = m.group(1).lower(), re.sub(r"\s+", " ", m.group(2).lower())
    n = int(a) if a.isdigit() else _WORDNUM.get(a)
    total = int(b) if b.isdigit() else _WORDNUM.get(b)
    if not n or not total or n >= total or total > 100:
        return None
    return {"value": n, "total": total, "text": _noun_after(text, m.end())}


def _labelled_values(text: str) -> Optional[tuple]:
    """Three or four named values in one line ("California 4.4 million, Arizona 2.8 million, Nevada 300,000")."""
    rows, seen = [], set()
    for m in _LABEL_NUM.finditer(text):
        words = m.group(1).split()
        while words and words[0] in _CAP_STOP:
            words = words[1:]
        v = _num(m.group(2))
        if not words or v is None or (1800 <= v <= 2100 and float(v).is_integer()):
            continue
        label = " ".join(words)
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        unit = (m.group(3) or "").lower()
        rows.append((label, v, unit))
    if len(rows) < 3:
        return None
    pct = {u in ("percent", "%") for _l, _v, u in rows}
    if len(pct) > 1 and any(u in ("percent", "%") for _l, _v, u in rows):
        return None
    if any(u in ("percent", "%") for _l, _v, u in rows):
        return [{"label": l.upper()[:18], "value": v} for l, v, _u in rows[:4]], "%"
    absolute = [v * _MULT.get(u, 1.0) for _l, v, u in rows]
    top = max(absolute)
    div, suffix = (1e9, "B") if top >= 1e9 else (1e6, "M") if top >= 1e6 else (1.0, "")
    return [{"label": rows[i][0].upper()[:18], "value": round(absolute[i] / div, 2)} for i in range(min(4, len(rows)))], suffix


def _document(text: str) -> Optional[dict]:
    """A report, a study, records, a newspaper or a law named in the line: the page, its headline and its key line."""
    m = _DOC.search(text)
    if not m:
        return None
    kind = next((g for g in m.groups() if g), "report").lower()
    kind = {"records": "records", "documents": "documents", "filings": "court filings", "headlines": "headline",
            "newspapers": "newspaper", "front page": "newspaper"}.get(kind, kind)
    rest = text[m.end():].strip(" ,:;")
    rest = re.sub(r"^(?:that|how|why)\s+", "", rest, flags=re.I)
    head = rest if len(rest) >= 24 else text
    head = head.strip().rstrip(".!?")
    if len(head) > 72:
        head = head[:72].rsplit(" ", 1)[0]
    sentence = text.strip()
    return {"text": head, "highlight": sentence[:200], "body": sentence[:400], "label": kind.upper()}


# ------------------------------------------------ spelled-out numbers, counts
# A pasted script is read as written: "twenty-two percent", "three thousand
# homes", "a million acre-feet" drew nothing before.
_NUM_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
_NUM_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_NUM_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_NUM_WORD = "(?:" + "|".join(sorted(list(_NUM_UNITS) + list(_NUM_TENS) + list(_NUM_SCALES), key=len, reverse=True)) + ")"
_SPELLED = re.compile(rf"\b(?:(?:a|an)\s+(?=(?:hundred|thousand|million|billion)\b))?{_NUM_WORD}"
                      rf"(?:(?:\s+and\s+|[\s-]+){_NUM_WORD})*\b", re.I)
_PERCENT_AFTER = re.compile(r"\s*(?:%|percent\b|per cent\b)", re.I)
# Things a count counts: a counter reads "12,000 / PEOPLE DISPLACED".
_COUNTABLE_WORDS = (r"(?:people|persons|residents|homes|houses|households|families|children|students|workers|jobs|"
                    r"deaths|lives|victims|structures|buildings|businesses|farms|vehicles|cars|wells|animals|trees|"
                    r"visitors|tourists|customers|patients|soldiers|troops|refugees|migrants|voters|employees|"
                    r"firefighters|acres)")
_COUNTABLE = re.compile(r"\s*(" + _COUNTABLE_WORDS + r")\b", re.I)
_COUNT_UNITS = {"people", "homes", "home", "structures", "structure", "deaths", "death", "residents", "families",
                "vehicles"}


def _spelled_value(words: str) -> Optional[float]:
    """'twenty-two' -> 22, 'three thousand' -> 3000, 'a million' -> 1e6, 'one hundred and twenty' -> 120."""
    total, current, seen = 0, 0, False
    for w in re.findall(r"[a-z]+", words.lower()):
        if w in ("and",):
            continue
        if w in ("a", "an"):
            current = 1
            continue
        if w in _NUM_UNITS:
            current += _NUM_UNITS[w]
        elif w in _NUM_TENS:
            current += _NUM_TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in _NUM_SCALES:
            total += (current or 1) * _NUM_SCALES[w]
            current = 0
        else:
            return None
        seen = True
    return float(total + current) if seen else None


# What can have happened to what was counted, besides a past participle ("displaced").
_COUNT_STATES = {"died", "fled", "dead", "missing", "homeless", "stranded", "trapped", "unaccounted", "hurt"}
_NOT_PARTICIPLES = {"need", "needed", "feed", "seed", "speed", "breed", "bleed", "exceed", "proceed", "succeed", "shed",
                    "used", "based", "related", "called", "named", "expected", "estimated", "reported"}


def _participle(text: str, end: int) -> str:
    """'people were displaced' -> 'DISPLACED', 'people died' -> 'DIED', 'remain missing' -> 'MISSING'
    (the word that says what happened to what was counted); '' for any other verb."""
    words = re.findall(r"[A-Za-z][\w-]*", re.split(r"[.;:!?,]", text[end:end + 40], maxsplit=1)[0])
    for w in words[:3]:
        lw = w.lower()
        if lw in ("were", "was", "have", "has", "had", "been", "are", "is", "now", "already", "remain", "remained",
                  "still", "left", "reportedly"):
            continue
        if lw in _COUNT_STATES or (lw.endswith("ed") and len(lw) > 4 and lw not in _NOT_PARTICIPLES):
            return w.upper()
        return ""
    return ""


def _spelled_figure(text: str, shot: dict, seg, brief: Optional[dict] = None) -> Optional[dict]:
    """A figure written out in words: a percent, a big number with its scale, or a count of things."""
    for m in _SPELLED.finditer(text):
        v = _spelled_value(m.group(0))
        if v is None or v <= 0:
            continue
        rest = text[m.end():]
        key = m.group(0).split()[0] if not m.group(0).lower().startswith(("a ", "an ")) else m.group(0).split()[1]
        if _PERCENT_AFTER.match(rest):
            if v <= 100:
                return {"cue": "percent", "emphasis": "high",
                        "props": {"value": v, "suffix": "%", "_key": key,
                                  "text": _figure_label(text, m.start(), m.end() + _PERCENT_AFTER.match(rest).end(),
                                                        shot, seg, brief)}}
            continue
        last = re.findall(r"[a-z]+", m.group(0).lower())[-1]
        countable = _COUNTABLE.match(rest)
        loose = m.group(0).lower().startswith(("a ", "an ", "one "))
        if countable and 100 <= v < 1_000_000 and not loose:
            # "three thousand homes": a count that counts up to 3,000.
            noun = countable.group(1).upper()
            done = _participle(text, m.end() + countable.end())
            return {"cue": "count", "emphasis": "high",
                    "props": {"value": v, "suffix": "", "_key": key, "text": f"{noun} {done}".strip()}}
        if last in ("thousand", "million", "billion"):
            if loose and not (countable or _NUMBER_UNIT.match("1 " + rest.lstrip()[:30])):
                continue            # "a million reasons" is a figure of speech
            scale = _NUM_SCALES[last]
            return {"cue": "big-number", "emphasis": "high",
                    "props": {"value": round(v / scale, 2), "suffix": last.upper(), "_key": key,
                              "text": _figure_label(text, m.start(), m.end(), shot, seg, brief)}}
        if countable and v >= 100:
            noun = countable.group(1).upper()
            done = _participle(text, m.end() + countable.end())
            return {"cue": "count", "emphasis": "high",
                    "props": {"value": v, "suffix": "", "_key": key, "text": f"{noun} {done}".strip()}}
    return None


# ------------------------------------------------ the text cues
# A line's own words as a graphic: a short punchy line is a headline, a named
# thing a key phrase, a flat declarative a statement (a fact when it carries a
# figure or a superlative), a rhetorical or record-setting line is typed out.
_RHETORICAL = re.compile(r"^(?:but|and yet|yet|here'?s the thing|the truth is|nobody|no one|none of|not one|"
                         r"there (?:is|was) no|it was never|this was never|and then)\b", re.I)
_RECORD = re.compile(r"\b(on record|ever recorded|record[- ](?:low|high|breaking)|in (?:recorded )?history|"
                     r"for the first time|never before|lowest (?:level|point) ever|highest (?:level|point) ever)\b", re.I)
_TERM = re.compile(r"\b(?:(?:call|calls|called)\s+(?:it|this|that|them)|called|known as|dubbed|nicknamed|termed|"
                   r"so-called|what(?:'s| is) called)\s+"
                   r"(?:the\s+|a\s+|an\s+)?[\"“']?([A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*){0,3})", re.I)
_SUPERLATIVE = re.compile(r"\b(?:the\s+)?((?:largest|biggest|worst|lowest|highest|deepest|driest|hottest|wettest|"
                          r"longest|oldest|fastest|deadliest|costliest|first|last|only)(?:\s+[a-z][\w-]*){1,3})", re.I)
_PROPER = re.compile(r"\b[A-Z][a-zA-Z'’.-]*(?:\s+(?:of|the|de|del|la|du|von|van|and)\s+[A-Z][a-zA-Z'’.-]*"
                     r"|\s+[A-Z][a-zA-Z'’.-]*){0,4}")
_PHRASE_TAIL = {"of", "the", "de", "del", "la", "du", "von", "van", "and"}
_NOT_A_PHRASE = {m.upper() for m in _MONTHS.split("|")} | {
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY", "I", "OK", "AM", "PM"}


def _words(text: str) -> List[str]:
    return re.findall(r"[\w'’-]+", text or "")


def _clause(text: str, max_words: int = 8, max_chars: int = 64) -> str:
    """The line, or its first clause, when it is short enough to stand on screen; '' otherwise."""
    t = re.sub(r"\s+", " ", (text or "").strip()).rstrip(".!;,:")
    if len(_words(t)) <= max_words and len(t) <= max_chars:
        return t
    for part in re.split(r"\s*[,;:—–]\s*|\s+-\s+", t):
        part = part.strip().rstrip(".!;,:")
        if 3 <= len(_words(part)) <= max_words and len(part) <= max_chars:
            return part
    return ""


def _key_phrase(text: str, shot: Optional[dict] = None) -> str:
    """
    The salient noun phrase of a line, as a human editor would put it on a
    label: a proper name ("Hoover Dam", "the Colorado River Compact"), else a
    superlative ("lowest level on record"), else the shot's subject when the
    line names it. '' when the line has none (the filler then stays off).
    """
    text = text or ""
    first_alpha = next((k for k, ch in enumerate(text) if ch.isalpha()), 0)
    best = ""
    for m in _PROPER.finditer(text):
        words = m.group(0).split()
        lead = m.start()
        while words and (words[0].strip(".,'’") in _CAP_STOP or words[0].upper() in _NOT_A_PHRASE):
            lead += len(words[0]) + 1
            words = words[1:]
        while words and words[-1].lower() in _PHRASE_TAIL:
            words = words[:-1]
        if not words or all(w.upper().strip(".,") in _NOT_A_PHRASE for w in words):
            continue
        if len(words) == 1 and (lead <= first_alpha or len(words[0]) < 4):
            continue            # one capitalised word opening the line is just the sentence's first word
        phrase = " ".join(words).strip(".,;:'’")
        if len(phrase) > len(best) and len(phrase) <= 36:
            best = phrase
    if best:
        return best
    m = _SUPERLATIVE.search(text)
    if m:
        words = [w for w in m.group(1).split()][:4]
        while words and words[-1].lower() in _LABEL_SKIP:
            words = words[:-1]
        if len(words) >= 2:
            return " ".join(words)
    subject = ((shot or {}).get("subject") or "").strip()
    if subject and 3 < len(subject) <= 36 and subject.lower().split()[0] in text.lower():
        return subject
    return ""


def _headline(text: str) -> str:
    """A short punchy line (3-8 words, two of them carrying meaning) as it would stand on screen."""
    t = (text or "").strip()
    words = _words(t)
    if not 3 <= len(words) <= 8 or t.endswith("?"):
        return ""
    content = [w for w in words if w.lower() not in _LABEL_SKIP and not w.isdigit() and len(w) > 2]
    if len(content) < 2:
        return ""
    return t.rstrip(".!;,:")


def _text_cues(text: str, seg, shot: dict, have: set) -> List[dict]:
    """The line's own words as graphics: typewriter, term, headline, fact/statement, key phrase, caption."""
    out: List[dict] = []
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return out
    words = _words(t)
    phrase = _key_phrase(t, shot)
    if _RHETORICAL.match(t) or _RECORD.search(t) or (t.endswith("?") and "question" in have):
        typed = _clause(t, 12, 64)
        if typed:
            out.append({"cue": "typewriter", "emphasis": "medium", "props": {"text": typed}})
    m = _TERM.search(t)
    if m:
        term = m.group(1).strip(" .,'\"”’")
        term_words = [w for w in term.split() if w.lower() not in _LABEL_SKIP] or term.split()
        term = " ".join(term_words[:3])
        if 3 <= len(term) <= 30:
            out.append({"cue": "term", "emphasis": "medium",
                        "props": {"text": term.title() if term.islower() else term, "_key": term.split()[0]}})
    head = _headline(t)
    if head:
        out.append({"cue": "headline", "emphasis": "medium", "props": {"text": head}})
    content = [w for w in words if w.lower() not in _LABEL_SKIP and not w.isdigit() and len(w) > 2]
    if not t.endswith("?") and len(t) <= 110 and len(content) >= 3:
        figure = any(not (len(n) == 4 and 1800 <= int(n) <= 2100) for n in re.findall(r"\b\d+\b", t.replace(",", "")))
        factual = figure or bool(_SUPERLATIVE.search(t) or _RECORD.search(t))
        if factual and len(words) <= 22:
            out.append({"cue": "fact", "emphasis": "medium",
                        "props": {"text": t.rstrip("."), **({"highlight": phrase} if phrase else {})}})
        elif 5 <= len(words) <= 16:
            out.append({"cue": "statement", "emphasis": "medium",
                        "props": {"text": t.rstrip("."), **({"highlight": phrase} if phrase else {})}})
    if phrase:
        out.append({"cue": "key-phrase", "emphasis": "low", "props": {"text": phrase, "_key": phrase.split()[0]}})
        out.append({"cue": "caption", "emphasis": "low", "props": {"text": phrase.upper(), "_key": phrase.split()[0]}})
    return out


# ------------------------------------------------ people
_NOT_A_PERSON_START = {"lake", "mount", "mt", "new", "united", "white", "north", "south", "east", "west", "saint", "san",
                       "los", "las", "fort", "national", "federal", "state", "county", "city", "river", "valley",
                       "ocean", "gulf", "cape", "hurricane", "storm", "tropical", "the", "glen", "hoover", "grand"}
_NAME = re.compile(r"^(?:(?:Dr|Mr|Mrs|Ms|Gov|Sen|Rep|Gen|Col|Capt|Judge|President|Mayor)\.?\s+)?"
                   r"[A-Z][a-zA-Z'’-]+(?:\s+(?:[A-Z]\.|[A-Z][a-zA-Z'’-]+|de|van|von|da|del|bin|al)){1,3}"
                   r"(?:,?\s+(?:Jr|Sr|II|III)\.?)?$")


def _is_name(s: str) -> bool:
    s = (s or "").strip()
    if not _NAME.match(s):
        return False
    first = re.sub(r"^(?:Dr|Mr|Mrs|Ms|Gov|Sen|Rep|Gen|Col|Capt|Judge|President|Mayor)\.?\s+", "", s).split()[0]
    return first.lower() not in _NOT_A_PERSON_START and first.upper() not in _NOT_A_PHRASE


# Words that make a name an organisation, an agency or a place, never a person
# (the owner's Texas flood video introduced "Weather Prediction Center" full
# screen as WHO IS). Words that are also common surnames (Park, Hill, Stone,
# Wood, Field, Brooks, Street) are left out on purpose.
_ORG_WORDS = set("""center centre centers service services agency agencies department dept office offices administration
bureau council committee commission university college institute institution academy school schools association
authority corporation corp company co inc llc ltd foundation ministry hospital organization organisation patrol
survey laboratory lab observatory museum society network court senate congress parliament police sheriff sheriffs
army navy corps guard force fund group party union board team club coalition weather prediction forecast emergency
management national federal state county city township district region government republic kingdom news times
tribune gazette journal herald press channel radio station airport highway interstate bridge river creek canyon
valley lake lakes mount mountain mountains dam bay island islands harbor harbour gulf basin reservoir springs falls
desert forest camp fort coast ocean sea country hills plains prairie delta peninsula border area metro downtown
village town borough parish province territory avenue road boulevard canal port heights gardens""".split())


def _is_org_or_place(name: str) -> bool:
    """An organisation, agency or place (by its words, or an acronym like FEMA), not a person."""
    words = re.findall(r"[A-Za-z][A-Za-z'’.-]*", name or "")
    if not words:
        return False
    if any(w.lower().strip(".'’") in _ORG_WORDS for w in words):
        return True
    return len(words) == 1 and words[0].isupper() and len(words[0]) >= 3


def _real_person(name: str) -> bool:
    """A name worth a WHO IS card: a person's name, not an organisation or a place."""
    return bool(name) and _is_name(name) and not _is_org_or_place(name)


def _person_like(name: str, shot: Optional[dict] = None, brief: Optional[dict] = None) -> bool:
    """True when `name` is (or could be) a person: never use it as a number's label or a chart title."""
    name = (name or "").strip()
    if not name:
        return False
    if str((shot or {}).get("subjectType") or "").lower() == "person" \
            and name == str((shot or {}).get("subject") or "").strip():
        return True
    for c in (brief or {}).get("cast") or []:
        if isinstance(c, dict) and any(_same_person(name, str(n)) for n in [c.get("name") or ""] + list(c.get("aliases") or [])
                                       if n):
            return True
    if any(isinstance(p, str) and _same_person(name, p) for p in (brief or {}).get("people") or []):
        return True
    return _real_person(name)


def _mentions(text: str, name: str) -> bool:
    name = (name or "").strip()
    return len(name) >= 4 and re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text or "") is not None


def person_key(name: str) -> str:
    """A name reduced for "have we introduced them": 'Dr. Brad Udall' and 'Brad Udall' are one person."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower())
             if w not in ("dr", "mr", "mrs", "ms", "gov", "sen", "rep", "gen", "jr", "sr", "ii", "iii")]
    return " ".join(words)


def _same_person(a: str, b: str) -> bool:
    ka, kb = set(person_key(a).split()), set(person_key(b).split())
    if not ka or not kb:
        return False
    small, big = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    return small == big or (len(small) >= 2 and small <= big)


def _named_person(text: str, shot: dict, brief: Optional[dict]) -> Optional[tuple]:
    """
    (name, role, spoken name) of a real person the line names or the shot is
    about, else None. Only a person's own name counts: never an organisation,
    an agency or a place (whatever the brief's cast or people say), never an
    unnamed cast member known only by an alias ("the boy").
    """
    brief = brief or {}
    cast = [c for c in (brief.get("cast") or []) if isinstance(c, dict)]
    for c in cast:
        name = str(c.get("name") or "").strip()
        # The cast is the story's people ("Cher" too), but never an organisation or a place.
        if not name or _is_org_or_place(name):
            continue
        for n in [name] + [str(a) for a in (c.get("aliases") or [])]:
            if _mentions(text, n):
                return name, str(c.get("role") or "").strip(), n
    for p in brief.get("people") or []:
        if isinstance(p, str) and _real_person(p) and _mentions(text, p):
            return p, _role_of(p, cast), p
    subject = (shot.get("subject") or "").strip()
    if (shot.get("subjectType") or "").lower() == "person" and _real_person(subject):
        return subject, _role_of(subject, cast), subject
    return None


def _role_of(name: str, cast: List[dict]) -> str:
    for c in cast:
        if _same_person(name, str(c.get("name") or "")) or any(_same_person(name, str(a)) for a in c.get("aliases") or []):
            return str(c.get("role") or "").strip()
    return ""


# --------------------------------------------------------------- cues
def cues_for(seg: Segment, shot: dict, brief: Optional[dict]) -> List[dict]:
    """
    What the line asks for, most specific first: [{cue, props, emphasis}].
    Only the line's own words and numbers ever reach a template.
    """
    text = seg.text or ""
    out: List[dict] = []
    # A chart's title or a figure's label is what the line counts, never a
    # person (the owner, 2026-09-30: "GREG ABBOTT" under a rolling number).
    title = _label_subject(shot, seg, brief)
    m = _TWO_YEARS.search(text)
    if m and m.group(1) != m.group(4):
        a, b = _num(m.group(2)), _num(m.group(5))
        if a is not None and b is not None:
            unit = _UNIT_SHORT.get((m.group(3) or m.group(6) or "").lower(), "")
            out.append({"cue": "then-now", "emphasis": "high",
                        "props": {"text": title, "items": [
                            {"label": m.group(1), "value": a, "suffix": unit},
                            {"label": m.group(4), "value": b, "suffix": unit}]}})
    money = _money(text)
    if len(money) >= 2 and not out and re.search(r"\bfrom\b.*\bto\b", text, re.I):
        (a, ua, _e1), (b, ub, _e2) = money[0], money[1]
        out.append({"cue": "money-compare", "emphasis": "high",
                    "props": {"text": title, "items": [
                        {"label": "BEFORE", "value": a, "prefix": "$", "suffix": ua},
                        {"label": "AFTER", "value": b, "prefix": "$", "suffix": ub}]}})
    elif money and not out:
        v, unit, end = money[0]
        start = next((mm.start() for mm in _MONEY.finditer(text) if mm.end() == end), end)
        out.append({"cue": "money", "emphasis": "high",
                    "props": {"value": v, "prefix": "$", "suffix": unit,
                              "text": _figure_label(text, start, end, shot, seg, brief)}})
    m = _CHANGE.search(text)
    if m and _num(m.group(2)) is not None and not any(c["cue"] in ("money", "money-compare") for c in out):
        down = m.group(1).lower() in ("fell", "fallen", "dropped", "declined", "decreased", "lost", "shrank")
        # What changed: "the death toll rose to 104" -> DEATH TOLL, else the story's subject.
        out.append({"cue": "change", "emphasis": "high",
                    "props": {"value": _num(m.group(2)), "suffix": _UNIT_SHORT.get((m.group(3) or "").lower(), ""),
                              "label": "down" if down else "up",
                              "text": _noun_before(text, m.start(2)) or title}})
    m = _PERCENT.search(text)
    if m and _num(m.group(1)) is not None and not any(c["cue"] in ("then-now", "change", "money", "money-compare")
                                                        for c in out):
        out.append({"cue": "percent", "emphasis": "high",
                    "props": {"value": _num(m.group(1)), "suffix": "%",
                              "text": _figure_label(text, m.start(), m.end(), shot, seg, brief)}})
    m = _NUMBER_UNIT.search(text)
    if m and _num(m.group(1)) is not None and not out:
        unit = re.sub(r"\s+", "-", m.group(2).lower())
        if unit in _COUNT_UNITS:
            # A count of things counts up to its number: "12,000 / PEOPLE DISPLACED".
            done = _participle(text, m.end())
            out.append({"cue": "count", "emphasis": "high",
                        "props": {"value": _num(m.group(1)), "suffix": "",
                                  "text": f"{m.group(2).upper()} {done}".strip()}})
        else:
            # The label says what the figure counts ("75 MILLION / ACRE FEET"); the
            # story's subject under every number read "75 MILLION / GLEN CANYON DAM".
            out.append({"cue": "big-number", "emphasis": "high",
                        "props": {"value": _num(m.group(1)), "suffix": _UNIT_SHORT.get(unit, unit.upper()[:8]),
                                  "text": _figure_label(text, m.start(), m.end(), shot, seg, brief)}})
    if not out and not _RATIO.search(text):
        spelled = _spelled_figure(text, shot, seg, brief)
        if spelled:
            out.append(spelled)
    span = time_span_in(text)
    if span:
        # "Three days later", "within 48 hours": a span of time counts on the
        # countdown look, not as a plain big number.
        label, value, _at, spoken = span
        out = [c for c in out if not (c["cue"] in ("big-number", "count") and c["props"].get("value") == value)]
        out.append({"cue": "time-span", "emphasis": "high", "props": {"text": label, "value": value, "_key": spoken}})
    m = _QUOTE.search(text)
    if m:
        out.append({"cue": "quote", "emphasis": "high",
                    "props": {"text": m.group(1).strip(), "label": _subject_words(shot, seg)}})
    elif _SAID.search(text) and len(text) < 140:
        # (A 200-character "quote" only fits on screen in tiny type: the owner wants a proper size.)
        out.append({"cue": "quote", "emphasis": "medium",
                    "props": {"text": text.strip().rstrip("."), "label": _subject_words(shot, seg)}})
    if text.strip().endswith("?") and len(text) <= 90:
        out.append({"cue": "question", "emphasis": "medium", "props": {"text": text.strip()}})
    m = _WARN.search(text)
    if m:
        a = max(0, m.start() - 24)
        b = min(len(text), m.end() + 24)
        while a > 0 and text[a - 1].isalnum():
            a += 1
            if a >= m.start():
                a = m.start()
                break
        while b < len(text) and text[b - 1].isalnum() and text[b].isalnum():
            b -= 1
            if b <= m.end():
                b = m.end()
                break
        phrase = re.sub(r"[^\w\s-]", "", text[a:b]).strip().upper()
        if len(phrase) > 40:
            phrase = phrase[:40].rsplit(" ", 1)[0]
        out.append({"cue": "warning", "emphasis": "medium", "props": {"text": phrase}})
    m = _ROUTE.search(text)
    locs = shot.get("overlay", {}).get("locations") if isinstance(shot.get("overlay"), dict) else None
    if m and locs and len(locs) >= 2:
        out.append({"cue": "route", "emphasis": "high",
                    "props": {"text": f"{m.group(1)} to {m.group(2)}", "locations": locs[:2]}})
    date = date_in(text)
    clock = time_in(text)
    if date or clock:
        at = min(x[1] for x in (date, clock) if x)
        weekday = _weekday_before(text, date[1]) if date else ""
        if date and clock:
            # A date and a time together: one card, "SEPTEMBER 25, 2026 · 3:45 PM".
            cue = {"cue": "datetime", "props": {"text": f"{date[0]} · {clock[0]}", "date": date[0], "time": clock[0],
                                                **({"label": weekday} if weekday else {})}}
        elif date:
            cue = {"cue": "date", "props": {"text": date[0], **({"label": weekday} if weekday else {})}}
        else:
            cue = {"cue": "time-of-day", "props": {"text": clock[0]}}
        cue["props"]["_key"] = next((w for w in re.findall(r"[\w:]+", text[at:])
                                     if w.lower() not in ("the", "on", "at", "by", "around", "about", "until", "before",
                                                          "after", "near", "just")), "")
        if at <= 25:
            # The line opens on its date ("On the fifteenth of September, ..."):
            # that is the moment for the date card, ahead of any figure after it.
            out.insert(0, dict(cue, emphasis="high"))
        else:
            out.append(dict(cue, emphasis="medium"))
    out = _more_cues(text, seg, shot, out, brief)
    person = _named_person(text, shot, brief)
    if person:
        name, role, spoken = person
        out.append({"cue": "person-full", "emphasis": "high",
                    "props": {"text": name[:60], "subtitle": role[:90], "label": "WHO IS",
                              "_key": spoken.split()[0] if spoken.split() else ""}})
    return out + _text_cues(text, seg, shot, {c["cue"] for c in out})


def _more_cues(text: str, seg: Segment, shot: dict, out: List[dict], brief: Optional[dict] = None) -> List[dict]:
    """The charts, ratios, rulers, recordings and documents a line can also ask for."""
    # A chart title or a figure's label, never a person's name.
    subject = _label_subject(shot, seg, brief)
    series = _series(text)
    if series:
        # Three or more years: a line chart instead of a single then-vs-now.
        out = [c for c in out if c["cue"] not in ("then-now", "percent", "big-number", "change")]
        out.insert(0, {"cue": "series", "emphasis": "high",
                       "props": {"text": subject, "items": series[0], "suffix": series[1]}})
    shares = None if series else _shares(text)
    if shares:
        out = [c for c in out if c["cue"] != "percent"]
        out.insert(0, {"cue": "shares", "emphasis": "high", "props": {"text": subject, "items": shares}})
    ratio = _ratio(text)
    if ratio:
        out.insert(0, {"cue": "ratio", "emphasis": "high",
                       "props": {"value": ratio["value"], "total": ratio["total"],
                                 "text": ratio["text"] or subject.upper()}})
    lv = None if (series or shares) else _labelled_values(text)
    if lv:
        items = [dict(it, suffix=lv[1]) for it in lv[0]]
        idx = next((i for i, c in enumerate(out) if c["cue"] in ("big-number", "percent", "money")), len(out))
        out.insert(idx, {"cue": "compare-values", "emphasis": "high", "props": {"text": subject, "items": items}})
    for c in out:
        # A fall or rise in feet or miles is a level on a ruler as well as a trend.
        if c["cue"] == "change" and (c["props"].get("suffix") or "") in _LENGTH_UNITS:
            c["cue"] = "change-length"
    if not any(c["cue"] in ("change-length", "series", "compare-values") for c in out):
        m = _MEASURE.search(text)
        unit = _LENGTH_SHORT.get(m.group(2).lower(), "") if m else ""
        if m and unit and _num(m.group(1)) is not None:
            idx = next((i for i, c in enumerate(out) if c["cue"] == "big-number"), len(out))
            noun = _noun_after(text, m.end())
            props = {"value": _num(m.group(1)), "suffix": unit,
                     "text": noun or _noun_before(text, m.start()) or subject.upper()}
            if noun in _SIZE_WORDS:
                props.update(text=subject.upper(), subtitle=noun)
            out.insert(idx, {"cue": "measurement", "emphasis": "high", "props": props})
    if _RECORDING.search(text):
        q = next((c for c in out if c["cue"] == "quote"), None)
        words = (q["props"]["text"] if q else text.strip().rstrip(".")).strip()
        if 12 <= len(words) <= 200:
            idx = next((i for i, c in enumerate(out) if c["cue"] == "quote"), len(out))
            # (Who is heard may be a person: the recording's own label keeps the speaker.)
            out.insert(idx, {"cue": "recording", "emphasis": "high",
                             "props": {"text": words, "label": _subject_words(shot, seg), "subtitle": "Audio recording"}})
    doc = _document(text)
    if doc:
        loose = next((i for i, c in enumerate(out) if c["cue"] == "quote" and c["emphasis"] != "high"), None)
        out.insert(loose if loose is not None else len(out), {"cue": "document", "emphasis": "high", "props": doc})
    return out


# ------------------------------------------------------------ dates and times, VidRush's way
# The owner, 2026-10-01, comparing four VidRush exports with ours: we showed
# dates far too often, jumped between corners (top-left, top-centre,
# bottom-left, right), and showed weekdays and days the narration never said.
# VidRush shows about ONE date or time graphic every two to three minutes,
# never on every mention, in four looks with fixed places and one colour theme
# per video:
#   VR_HERO     centred: the date as said ("SEPTEMBER 23"; "JULY" for a month
#               and a year), the year small under it when the year was said;
#   VR_TIME     top-left: the time as said ("9:08 AM") over a strip with the
#               date said in the same sentence, else the place the line or its
#               section is about, else nothing;
#   VR_CAPTION  bottom-left: a typed "Place, Year" ("Parker Dam, 1938");
#   VR_YEAR     centred: the year said on a line, its dot moving from the year
#               the story was in (else NOW_YEAR) - a jump in years.
# A weekday alone, "last night", "48 hours", "this week", a range or any other
# relative time gets no date graphic. The old rotation (the letter drop and
# the placed looks of LibPackDates) stays in the registry for the editor only.
VR_HERO = "LIB_VR_DATE_HERO"
VR_TIME = "LIB_VR_TIME_CARD"
VR_CAPTION = "LIB_VR_CAPTION_TYPED"
VR_YEAR = "LIB_VR_YEAR_LINE"
VR_LOOKS = (VR_HERO, VR_TIME, VR_CAPTION, VR_YEAR)
VR_GAP = 75.0            # at most one of them per this many seconds of video
VR_HERO_GAP = 150.0      # the big centred date at most once per this
VR_FIRST_HERO = 90.0     # the video's first full date is always shown when it is said this early
YEAR_JUMP = 5            # a year said this far from the one the story was in is a jump
NOW_YEAR = datetime.date.today().year      # the year a story is in until it names one (2026 now)
CAPTION_MAX = 42         # "University of Hawaii, 1959"
STRIP_MAX = 32           # the time card's label strip
# One colour theme per video: gold serif for news, weather and explainers, red
# typewriter for documentaries, history, stories and crime.
VR_SERIF_STYLES = {"nature_weather", "trending_news", "news_compilation", "compilation", "explainer"}
VR_TYPEWRITER_STYLES = {"documentary", "history", "story", "crime", "investigative", "true_crime"}
_VR_THEME_BY_KIND = {"news": "serif", "weather": "serif", "disaster": "serif", "nature": "serif",
                     "science": "serif", "explainer": "serif", "history": "typewriter",
                     "biography": "typewriter", "crime": "typewriter", "investigative": "typewriter"}


def vr_theme(video_style: str = "", brief: Optional[dict] = None, pack: Optional[dict] = None) -> str:
    """The video's one theme for its date and time looks: "serif" (gold) or "typewriter" (red).
    The job's video style decides; without one the story's kind, then the style pack."""
    from . import styles
    raw = str(video_style or "").strip().lower().replace(" ", "_").replace("-", "_")
    key = styles.resolve(raw) or raw
    if key in VR_SERIF_STYLES:
        return "serif"
    if key in VR_TYPEWRITER_STYLES or key.startswith(("crime", "true_crime", "investigat")):
        return "typewriter"
    kind = str((brief or {}).get("kind") or "").strip().lower()
    if kind in _VR_THEME_BY_KIND:
        return _VR_THEME_BY_KIND[kind]
    return "serif" if str((pack or {}).get("id") or "") in ("news", "weather", "tech", "youtube_modern") \
        else "typewriter"


# A clock time, the time card's only job: "9:08 a.m.", "at 21:40", "seven
# o'clock that evening", "at noon", "at midnight". Never dawn or dusk, "past
# midnight", "overnight" or "this morning": relative times get no graphic.
_CLOCK_WORD = re.compile(r"\b(?:at|around|about|just\s+after|just\s+before|shortly\s+after|shortly\s+before|"
                         r"right\s+at|exactly\s+at)\s+(noon|midday|midnight)\b", re.I)


def clock_in(text: str) -> Optional[tuple]:
    """(label, offset) of the first clock time a line says - '9:08 AM', '21:40', '7:00 PM', '12:00 AM' - or None."""
    text = text or ""
    found = []
    # (offset, how specific - an "am/pm" reading beats a bare "3:45" at the same place, label)
    for m in _TIME_AMPM.finditer(text):
        h = int(m.group(1))
        if 1 <= h <= 12:
            found.append((m.start(1), 0, f"{h}{':' + m.group(2) if m.group(2) else ''} {m.group(3).upper()}M"))
            break
    for m in _TIME_AT.finditer(text):
        h = int(m.group(1))
        if 0 <= h <= 23:
            found.append((m.start(1), 1, f"{h}:{m.group(2)}"))
            break
    m = _CLOCK_WORD.search(text)
    if m:
        found.append((m.start(1), 0, "12:00 AM" if m.group(1).lower() == "midnight" else "12:00 PM"))
    m = _TIME_OCLOCK.search(text)
    if m:
        raw = m.group(1).lower()
        h = int(raw) if raw.isdigit() else _CLOCK_WORDS.get(raw, 0)
        if 1 <= h <= 12:
            part = (m.group(2) or "").lower()
            ampm = " AM" if "morning" in part else " PM" if part else ""
            found.append((m.start(), 0, f"{h}:00{ampm}"))
    if not found:
        return None
    start, _prio, label = min(found)
    return label, start


# A year as a year: never a figure ("2,000 people", "1900 feet"), a decade ("the
# 1960s"), money or a code. The years of a chart ("in 2020 it was 40 percent; by
# 2026, 26") are its labels, not the story's time (vr_moment skips those lines).
_YEAR_SAID = re.compile(
    r"(?<![\d$£€#.,/:-])\b(1[5-9]\d\d|20\d\d)\b(?![,.]?\d)(?!\s*(?:%|percent|per\s*cent|feet|foot|ft|acres?|"
    r"acre-feet|miles?|meters?|metres?|km|kilomet\w+|people|persons|homes?|houses?|residents|families|deaths?|"
    r"dollars|tons?|gallons?|inches|degrees|cfs|mph|hours?|minutes?|seconds?|days?|weeks?|months?|years?|"
    r"times|cases|votes|jobs|students|cars|vehicles|structures?|buildings?|square|cubic)\b)", re.I)
_YEAR_RANGE = re.compile(r"\b(?:from|between)\s+(?:the\s+years?\s+)?(1[5-9]\d\d|20\d\d)\s*,?\s*"
                         r"(?:to|and|until|till|through|thru|[-–—])\s*(1[5-9]\d\d|20\d\d)\b"
                         r"|\b(1[5-9]\d\d|20\d\d)\s*[-–—]\s*(1[5-9]\d\d|20\d\d)\b", re.I)
_JUMP_COUNT = (r"(?:a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|"
               r"fifty|sixty|seventy|eighty|ninety|a\s+few|a\s+couple\s+of|several|many|some|\d{1,3})")
_YEAR_JUMP = re.compile(rf"\b(?:{_JUMP_COUNT}\s+)?(?:years?|decades?|centur(?:y|ies)|half\s+a\s+century)\s+"
                        r"(?:later|earlier|on|passed|went\s+by)\b|\bfast[\s-]+forward(?:ing)?\b", re.I)
# A date that opens a range ("July 2 to July 5", "September 3-5", "between June 1 and June 4"): no graphic.
_DATE_RANGE_AFTER = re.compile(
    rf"^\s*(?:[-–—]|to|through|thru|until|till|and|or)\s+(?:the\s+)?(?:(?:{_MONTHS})\b|\d{{1,2}}(?:st|nd|rd|th)?\b|"
    + "|".join(sorted((re.escape(w).replace(r"\-", "[- ]") for w in _ORDINAL_DAYS), key=len, reverse=True)) + ")",
    re.I)
# Words that make a capitalised name a place ("Parker Dam", "Kerr County",
# "University of Hawaii"), and words that make one an organisation instead
# ("National Weather Service").
_VR_PLACE_WORDS = set("""dam dams river creek canyon valley lake lakes mount mountain mountains bay island islands
harbor harbour gulf basin reservoir springs falls desert forest camp fort coast ocean sea county city township
district region state park beach village town borough parish province territory avenue road boulevard canal port
heights gardens plains prairie delta peninsula border hills university college school hospital airport highway
interstate bridge station museum observatory square street hall base mine plant refinery prison cemetery church
cathedral stadium arena tower capitol courthouse ranch farm keys bayou""".split())
_VR_NOT_PLACE_WORDS = set("""service services agency agencies department dept office offices administration bureau
council committee commission authority corporation corp company inc llc ltd foundation ministry association
organization organisation network news times tribune gazette journal herald press channel radio party union board
team club coalition group fund senate congress parliament government police sheriff sheriffs patrol guard army navy
corps force court institute prediction weather""".split())
_VR_AT_PLACE = re.compile(r"\b(?:in|at|near|outside|inside|across|throughout)\s+(?:the\s+)?$", re.I)


def years_said(text: str) -> List[tuple]:
    """[(year, offset)] of the years a line says as years, up to this year, in the order said."""
    return [(int(m.group(1)), m.start(1)) for m in _YEAR_SAID.finditer(text or "")
            if 1500 <= int(m.group(1)) <= NOW_YEAR]


def _ranged(text: str, end: int) -> bool:
    """The date that ends at `end` opens a range of dates."""
    return bool(_DATE_RANGE_AFTER.match((text or "")[end:end + 40]))


def _part_at(text: str, at: int, splits: str) -> tuple:
    """(start, end) of the stretch of `text` around offset `at` between any of the `splits` characters."""
    text = text or ""
    a = max((text.rfind(ch, 0, at) for ch in splits), default=-1) + 1
    ends = [k for k in (text.find(ch, at) for ch in splits) if k >= 0]
    return a, (min(ends) if ends else len(text))


def _sentence_at(text: str, at: int) -> str:
    # (A clock's "a.m." or a "Sept." is not a full stop: a full stop ends a sentence before a space and a capital.)
    marks = [m.end() for m in re.finditer(r"[.!?](?=\s+[A-Z])", text or "")]
    a = max([k for k in marks if k <= at], default=0)
    b = min([k for k in marks if k > at], default=len(text or ""))
    return (text or "")[a:b]


def _word_at(text: str, at: int) -> str:
    m = re.match(r"[\w:'’]+", (text or "")[at:])
    return m.group(0) if m else ""


def places_said(text: str, shot: Optional[dict] = None, brief: Optional[dict] = None) -> List[tuple]:
    """
    [(place as said, offset)] the line itself names, in the order said: one of
    the story's places, a map location the director gave the line, a place the
    line was pinned to, a name with a place word ("Parker Dam", "Kerr County",
    "University of Hawaii") or a name after "in", "at", "near"... Never a
    person, an agency, a month or a weekday.
    """
    text = text or ""
    brief = brief if isinstance(brief, dict) else {}
    shot = shot if isinstance(shot, dict) else {}
    hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else {}
    known = [str(p).split(",")[0].strip() for p in (brief.get("places") or []) if isinstance(p, str)]
    known += [str(loc.get("label") or "").split(",")[0].strip() for loc in (hint.get("locations") or [])
              if isinstance(loc, dict)]
    known += [str(p).split(",")[0].strip() for p in (shot.get("linePlaces") or []) if isinstance(p, str)]
    people = [str(p) for p in (brief.get("people") or []) if isinstance(p, str)]
    people += [str(c.get("name") or "") for c in (brief.get("cast") or []) if isinstance(c, dict)]
    if str(shot.get("subjectType") or "").lower() == "person" and shot.get("subject"):
        people.append(str(shot["subject"]))
    found: List[tuple] = []                 # (name, start, end)
    for name in sorted({k for k in known if len(k) >= 3}, key=len, reverse=True):
        m = re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text)
        if m and not any(a <= m.start() < b for _n, a, b in found):
            found.append((m.group(0), m.start(), m.end()))
    for m in _PROPER.finditer(text):
        words = m.group(0).split()
        lead = m.start()
        while words and (words[0].strip(".,'’") in _CAP_STOP or words[0].upper().strip(".,") in _NOT_A_PHRASE):
            lead += len(words[0]) + 1
            words = words[1:]
        while words and words[-1].lower() in _PHRASE_TAIL:
            words = words[:-1]
        name = " ".join(words).strip(".,;:'’")
        if len(name) < 3 or name.endswith(("'s", "’s")) or any(a <= lead < b for _n, a, b in found):
            continue
        low = [w.lower().strip(".,'’") for w in name.split()]
        if any(w in _VR_NOT_PLACE_WORDS for w in low) or any(_same_person(name, p) for p in people if p):
            continue
        if not any(w in _VR_PLACE_WORDS for w in low) and (_real_person(name) or not _VR_AT_PLACE.search(text[:lead])):
            continue
        found.append((name, lead, lead + len(name)))
    return [(n, a) for n, a, _b in sorted(found, key=lambda f: f[1])]


def _strip(text: str) -> str:
    """A place for the time card's strip, upper case, cut at a comma to fit."""
    parts = [p.strip() for p in str(text or "").split(",") if p.strip()]
    out = ""
    for p in parts[:2]:
        nxt = f"{out}, {p}" if out else p
        if len(nxt) > STRIP_MAX:
            break
        out = nxt
    return out.upper()


def vr_moment(text: str, shot: Optional[dict] = None, brief: Optional[dict] = None,
              story_year: Optional[int] = None, region: str = "") -> tuple:
    """
    (the date or time graphic a line asks for, or None; the year the story is
    in after the line). The graphic: {"look", "cue", "props", "key" (the word
    it lands on), "strength", "full_date"}. In order: a clock time is the time
    card; a full date (month and day) the hero; a jump in years ("years later"
    with a year, "from 1961 to 2008", a year YEAR_JUMP or more from the one the
    story was in) the year line; a month and a year the hero; a place and a
    year in one clause the typed caption. Only what the line says reaches the
    screen; `region` (the line's section) may only fill the time card's strip.
    """
    text = text or ""
    was = story_year or NOW_YEAR
    # Years that are a chart's labels ("in 2020 ... 40 percent; by 2026 ... 26") are not the story's time.
    data = bool(_TWO_YEARS.search(text)) or bool(_series(text))
    years = [] if data else years_said(text)
    span = None if data else _YEAR_RANGE.search(text)
    now = years[-1][0] if years else story_year
    if span:
        a, b = int(span.group(1) or span.group(3)), int(span.group(2) or span.group(4))
        now = b if b <= NOW_YEAR else now
    date = date_parts(text)
    if date and _ranged(text, date["end"]):
        date = None                       # "July 2 to July 5": a range gets no date graphic
    clock = clock_in(text)
    if clock:
        sentence = _sentence_at(text, clock[1])
        said = date_parts(sentence)
        if said and _ranged(sentence, said["end"]):
            said = None
        strip = said["label"] if said else ""
        if not strip:
            places = places_said(text, shot, brief)
            strip = _strip(places[0][0] if places else region)
        return ({"look": VR_TIME, "cue": "time-of-day", "props": {"text": clock[0], "subtitle": strip},
                 "key": _word_at(text, clock[1]), "strength": 3 if strip else 2,
                 "full_date": bool(said and said["day"])}, now)
    if date and date["day"]:
        return ({"look": VR_HERO, "cue": "date",
                 "props": {"text": f"{date['month']} {date['day']}",
                           "subtitle": str(date["year"]) if date["year"] else ""},
                 "key": _word_at(text, date["start"]), "strength": 2 if date["year"] else 1, "full_date": True}, now)
    jump = None if data else _YEAR_JUMP.search(text)
    target = None
    if span and a != b and b <= NOW_YEAR:
        target = (b, a, span.start(1) if span.group(1) else span.start(3), "")
    elif years and jump:
        y, at = next(((y, at) for y, at in years if at >= jump.start()), years[0])
        said = re.sub(r"\s+", " ", jump.group(0)).upper()
        target = (y, was, at, said if not said.startswith("FAST") and len(said) <= 18 else "")
    elif years and abs(years[0][0] - was) >= YEAR_JUMP:
        target = (years[0][0], was, years[0][1], "")
    if target and target[0] != target[1]:
        y, frm, at, label = target
        return ({"look": VR_YEAR, "cue": "years", "props": {"value": y, "total": frm, "label": label},
                 "key": _word_at(text, at), "strength": 3, "full_date": False}, now)
    if date and date["year"]:
        return ({"look": VR_HERO, "cue": "date", "props": {"text": date["month"], "subtitle": str(date["year"])},
                 "key": _word_at(text, date["start"]), "strength": 1, "full_date": False}, now)
    for y, at in years:
        a0, b0 = _part_at(text, at, ".;:!?—–()")
        places = places_said(text[a0:b0], shot, brief)
        if places:
            caption = f"{places[0][0]}, {y}"
            if len(caption) <= CAPTION_MAX:
                first = min(at, a0 + places[0][1])
                return ({"look": VR_CAPTION, "cue": "date", "props": {"text": caption},
                         "key": _word_at(text, first), "strength": 2, "full_date": False}, now)
    return None, now


def _vr_fits(m: dict, others: List[dict], margin: float = 0.0) -> bool:
    """`m` keeps VR_GAP from every other date or time graphic (VR_HERO_GAP between two heroes)."""
    for o in others:
        d = abs(float(m["at"]) - float(o["at"]))
        if d < VR_GAP + margin or (m["look"] == VR_HERO and o["look"] == VR_HERO and d < VR_HERO_GAP + margin):
            return False
    return True


# ------------------------------------------------------------ choosing
class _Rhythm:
    def __init__(self):
        # Nothing has been on screen yet: the first graphic of the video is
        # always allowed (a line starting at 0.4 s lost its date card to a
        # "last graphic ended at 0.0" rule). The filler label still waits
        # QUIET_MAX seconds from the opening (quiet_from).
        self.last_any = -1e9
        self.quiet_from = 0.0
        self.last_card = -1e9
        self.last_text = -1e9
        self.last_by_cat: Dict[str, float] = {}
        self.last_sfx = -1e9

    def allows(self, at: float, t: dict, cue: str = "") -> bool:
        if cue in TEXT_BEAT_CUES and at - self.last_text < TEXT_GAP:
            return False        # two text looks never follow each other closely
        # The opening two minutes run at VidRush's hook cadence: anything may
        # follow anything after HOOK_GAP, as long as no card is still up.
        if at < HOOK_SECONDS and at - self.last_any >= HOOK_GAP and not (
                t["kind"] in CARD_KINDS and self.overlaps(at)):
            return True
        gap = at - self.last_any
        need = TAG_GAP if t["kind"] == "tag" else MIN_GAP
        if t["emphasis"] == "high":
            need = min(need, HIGH_GAP)
        if gap < need:
            return False
        # Text beats have their own spacing (TEXT_GAP) and their own variety
        # rule (never the same family twice in a row); the category gap is for the rest.
        if at - self.last_by_cat.get(t["category"], -1e9) < FAMILY_GAP and t["emphasis"] != "high" \
                and cue not in TEXT_BEAT_CUES:
            return False
        if t["kind"] in CARD_KINDS and at - self.last_card < (HIGH_GAP if t["emphasis"] == "high" else MIN_GAP):
            return False
        return True

    def overlaps(self, at: float) -> bool:
        """A card is still on screen."""
        return at < self.last_card - 0.5

    def note(self, at: float, t: dict, seconds: float, cue: str = "") -> None:
        end = at + seconds
        self.last_any = max(self.last_any, end)
        self.quiet_from = max(self.quiet_from, end)
        self.last_by_cat[t["category"]] = end
        if t["kind"] in CARD_KINDS:
            self.last_card = max(self.last_card, end)
        if cue in TEXT_BEAT_CUES:
            self.last_text = max(self.last_text, end)


def _least_used(ids: List[str], counts: Optional[Dict[str, int]]) -> Optional[str]:
    """The first of `ids` that exists and has been used least (registry order breaks ties); never a banned look."""
    real = []
    for tid in ids:
        if tid and templates.get(tid) and tid not in real and not templates.banned(tid):
            real.append(tid)
    if not real:
        return None
    if not counts:
        return real[0]
    return min(real, key=lambda t: (counts.get(t, 0), real.index(t)))


# The realistic satellite looks a single mapped place rotates through, in
# every pack (the owner: more satellite maps, and varied). MAP_PHOTO_PIN_V1
# joins when there is a still to pin; history and tech mix their paper or
# dark vector map in at most one map in four.
SATELLITE_PLACE_MAPS = ["MAP_LOCATION_ZOOM_V1", "MAP_LOCATION_PULSE_V1", "MAP_TILT_V1", "MAP_INSET_V1",
                        "MAP_FOCUS_V1", "MAP_TRACE_V1", "MAP_DISASTER_V1"]
TWO_PLACE_MAPS = ["MAP_DISTANCE_V1", "MAP_TRACE_V1"]
VECTOR_MAP_EVERY = 4


def _is_satellite(tid: str) -> bool:
    return str(((templates.get(tid) or {}).get("defaults") or {}).get("variant") or "").startswith("satellite")


def _place_maps(pack: dict, still: bool = False, n_maps: int = 0) -> List[str]:
    """The looks a single mapped place rotates through: the pack's own first when it is a satellite look."""
    own = pack.get("map", "")
    out = ([own] if _is_satellite(own) else []) + [m for m in SATELLITE_PLACE_MAPS if m != own]
    if still:
        out.append("MAP_PHOTO_PIN_V1")
    if own and not _is_satellite(own) and n_maps % VECTOR_MAP_EVERY == VECTOR_MAP_EVERY - 1:
        out.insert(0, own)
    return out


def _map_ids(overlay: dict, pack: dict, still: bool = False, n_maps: int = 0) -> tuple:
    """(candidate map templates, the one the director's variant names or '') for a map hint."""
    variant = overlay.get("variant") or ""
    n_locs = len(overlay.get("locations") or overlay.get("places") or [])
    by_variant = next((t["id"] for t in templates.for_component("map")
                       if (t.get("defaults") or {}).get("variant") == variant), "") if variant else ""
    if variant.startswith("route") or variant == "satellite-route":
        ids, fits = [pack["route"], "MAP_ROUTE_SAT_V1", "MAP_TRACE_V1"], by_variant.startswith("MAP_ROUTE")
    elif variant.startswith("spread") or n_locs >= 3:
        # Three or more areas: the spread map lights each one in turn.
        ids, fits = [pack["multi"]], by_variant.startswith("MAP_SPREAD")
    elif variant == "region":
        ids, fits = [pack["region"]], False
    elif n_locs == 2:
        ids, fits = list(TWO_PLACE_MAPS), by_variant in TWO_PLACE_MAPS
    else:
        ids = _place_maps(pack, still, n_maps)
        fits = _is_satellite(by_variant) and by_variant not in ("MAP_DISTANCE_V1", "MAP_ROUTE_SAT_V1") \
            and (still or by_variant != "MAP_PHOTO_PIN_V1")
    if not fits:
        by_variant = ""
    elif by_variant not in ids:
        ids.insert(0, by_variant)
    return ids, by_variant


def _from_hint(overlay: dict, pack: dict, n_locs: int, text: str,
               counts: Optional[Dict[str, int]] = None) -> Optional[str]:
    """The template for an overlay the AI director or the rules proposed."""
    kind = overlay.get("type")
    variant = overlay.get("variant") or ""
    if kind == "map":
        maps = sum(v for k, v in (counts or {}).items() if k.startswith("MAP_"))
        ids, by_variant = _map_ids(overlay, pack, False, maps)
        if by_variant and not (counts or {}).get(by_variant):
            return by_variant
        return _least_used(ids, counts)
    if kind == "bullets" and not variant and counts is not None:
        return _least_used(["CALL_BULLETS_V1", "FACTS_CARD_V1"], counts)
    if kind == "chapter":
        return pack["chapter"]
    if kind == "lower-third":
        return pack["lowerThird"]
    options = [t for t in templates.for_component(kind, pack.get("id", "")) if look_fits(t["id"], text)]
    if not options:
        return None
    if variant:
        for t in options:
            if t["defaults"].get("variant") == variant:
                return t["id"]
    for t in options:
        if not t["defaults"].get("variant"):
            return t["id"]
    return options[0]["id"]


# Looks that picture one particular thing, and the words a line needs for it.
# Rotating every look of a cue for variety put a thermometer on "13 miles
# beneath Rocky Mountain National Park" and a block chart on "75 million
# acre-feet"; GoMotion shows the plain figure ("13 MILES") on the footage.
_LOOK_NEEDS = {
    "LIB_NC_THERMOMETER": r"\b(degrees?|temperatures?|heat|hott?er|warm\w*|cold\w*|fahrenheit|celsius)\b|°",
    "LIB_NC_STOPWATCH": r"\b(seconds?|minutes?|stopwatch|race|fastest|record time)\b",
    "LIB_IC_POWER_BOLT": r"\b(power|electric\w*|megawatts?|gigawatts?|kilowatts?|energy|grid|turbines?|hydropower)\b",
    "LIB_IC_FIRE_FLICKER": r"\b(fires?|wildfires?|burn\w*|blaze|flames?)\b",
    "LIB_IC_FACTORY_SMOKE": r"\b(factor(?:y|ies)|emissions?|pollut\w*|smoke\w*|carbon)\b",
    "LIB_IC_TRAFFIC_QUEUE": r"\b(cars?|traffic|vehicles?|trucks?|commut\w*|drivers?)\b",
    "LIB_IC_CROWD_SWELL": r"\b(people|residents|population|crowds?|voters?|workers|families|visitors|tourists)\b",
    "LIB_NC_POPULATION_CLOCK": r"\b(population|residents|births?|born)\b",
    "LIB_IC_HOUSE_GRID": r"\b(homes?|houses?|households?|housing)\b",
    "LIB_IC_DROP_FILL": r"\b(water|drops?|rain\w*|drink\w*)\b",
    "LIB_SC_AQUIFER_DROP": r"\b(aquifers?|groundwater|wells?)\b",
    "LIB_SC_DAM_LEVEL": r"\b(dams?|reservoirs?|capacity|full)\b",
    "NUM_TANK_V1": r"\b(reservoirs?|lakes?|tanks?|capacity|full|storage)\b",
    "LIB_NC_BATTERY": r"\b(battery|batteries|charg\w*)\b",
    "LIB_NC_SPEEDO_GAUGE": r"\b(speed|mph|km/?h|miles per hour|pace)\b",
    "LIB_NC_COUNTDOWN_DIAL": r"\b(countdown|remaining|deadline|days? left|left to)\b",
    "LIB_UI_POLL_RESULTS": r"\b(polls?|survey\w*|voters?|respondents|votes?|approv\w*)\b",
    "LIB_NC_FLIP_CLOCK": r"\b(clock|o'clock|countdown)\b",
    "LIB_NC_LED_COUNTER": r"\b(counter|counting|tally|scoreboard)\b",
    "LIB_NS_GOAL_TRACK": r"\b(goals?|targets?|promised|promise|pledge\w*|quota|required|owed)\b",
    "LIB_NS_BLOCK_STACK": r"\b(blocks?|stack\w*|pallets?|bricks?)\b",
    "LIB_CP_SPECTRUM_MARKER": r"\b(scale|spectrum|index|category)\b",
    "NUM_MEASURE_V1": r"\b(feet|foot|ft|inches|meters?|metres?|deep|depth|height|level|elevation|fell|fallen|"
                      r"dropp?ed|rose|risen|lower|higher)\b",
    "LIB_CO_MEASURE_LINE": r"\b(feet|foot|ft|inches|meters?|metres?|miles?|km|long|wide|tall|deep)\b",
    # Pack B (LibPackNumbers): the figures drawn with a picture of their subject.
    "LIB_NUM_RAINFALL": r"\b(rain\w*|precipitation|downpours?|showers?|deluge)\b",
    "LIB_NUM_WIND_GAUGE": r"\b(winds?|gusts?|gusting|windy)\b",
    "LIB_NUM_WATER_LEVEL": r"\b(rivers?|creeks?|streams?|crest\w*|flood\w*|gauges?|lakes?|reservoirs?|tides?|surge|"
                           r"water levels?)\b",
    "LIB_NUM_TEMPERATURE": r"\b(degrees?|temperatures?|heat|hott?er|hottest|warm\w*|cold\w*|fahrenheit|celsius|"
                           r"freez\w*|chill)\b|°",
}
_LOOK_NEEDS_RX ={k: re.compile(v, re.I) for k, v in _LOOK_NEEDS.items()}
# The letter drop (LibBoldText): every date, date-and-time and time of day
# until 2026-10-01, clean Anton letters low on the left or the right in turn.
# Since then the planner shows dates and times in the VidRush looks only
# (VR_LOOKS); the letter drop, the bold cards and the placed looks of
# LibPackDates stay in the registry for the editor (OLD_DATE_LOOKS, auto_ok).
# date_looks() still answers what the registry offers for a date cue.
TEXT_DATE_LOOK = "LIB_DT_LETTER_DROP"
BOLD_DATE_LOOKS = [TEXT_DATE_LOOK]
# Only if the registry lacks the letter drop: the two bold type looks left
# (the date slam, the clean card and the spaced title are banned, 2026-09-30 audit).
LEGACY_DATE_LOOKS = ["LIB_DT_BOLD_HEADLINE", "LIB_DT_BIG_STACK"]
# A figure is bold text too (the owner: "also for other numbers, count text like
# that, with a digit count sound"): the bold count leads for a number, a count,
# a percentage, money and an age; the other number looks come in for variety,
# once after every BOLD_COUNT_RUN bold counts in a row.
BOLD_COUNT_LOOK = "LIB_BT_COUNT"
BOLD_COUNT_CUES = {"big-number", "count", "percent", "money", "age"}
BOLD_COUNT_RUN = 2
# Where the text-only looks sit, in turn: the lower third at the safe margin,
# left or right, never mid-frame (the owner, 2026-10-01: "not in perfect
# places"); the editor may still choose the centre.
TEXT_LOOK_ALIGNS = {TEXT_DATE_LOOK: ["left", "right"], BOLD_COUNT_LOOK: ["right", "left"]}
# How they are lettered, in turn across both looks so no two in a row look the same
# (LibBoldText: clean white with a rule, silver shine, the key part in amber, white on a soft shade).
TEXT_LOOK_STYLES = ["clean", "shine", "accent", "shade"]
# The countdown card (banned, boxed). A span of time ("3 days later", "48 hours")
# is a relative time since 2026-10-01: no graphic at all (_musts).
COUNTDOWN_LOOK = "LIB_DT_COUNTDOWN_DAYS"
DATE_LOOKS = BOLD_DATE_LOOKS
# "Now let's head to New Jersey", "Down in North Carolina", "Moving north into
# Virginia": the narration walks to a new region (the reference channel's
# sections) - the section marker names it (pack C, LibPackPlaces).
_REGION_CHANGE = re.compile(
    r"^\s*(?i:and\s+)?(?i:now,?\s+|next,?\s+|so\s+)?(?i:"
    r"let'?s\s+(?:head|move|go|turn|look)\s+(?:up\s+|down\s+|over\s+|north\s+|south\s+|east\s+|west\s+)?(?:to|into|towards?|at)\s+"
    r"|(?:down|up|over|out|back)\s+in\s+"
    r"|(?:moving|heading|turning)\s+(?:north|south|east|west|inland|up|down|over)\s+(?:to|into|towards?)\s+)"
    r"(?i:the\s+)?(?P<place>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})")
SECTION_LOOK = "LIB_PLC_SECTION_MARKER"
# The bold text looks a date or a time used to land on: the letter drop and the
# placed looks of pack A (LibPackDates). Since 2026-10-01 (VR_LOOKS) the planner
# never picks them; they stay in the registry for the editor.
DATE_TEXT_LOOKS = {TEXT_DATE_LOOK, "LIB_DTX_TIME_STAMP", "LIB_DTX_DATE_TOP", "LIB_DTX_DATE_PLACE",
                   "LIB_DTX_DATE_RANGE", "LIB_DTX_DAY_MARKER", "LIB_DTX_TIME_OF_DAY", "LIB_DTX_LEAD_TIME",
                   "LIB_DTX_UPDATED_STAMP", "LIB_DTX_WEEK_STRIP", "LIB_DTX_WEEKDAY_STACK", "LIB_DTX_YEAR_MARKER",
                   "LIB_DTX_RELATIVE_TAG", "LIB_DTX_CLOCK_LIVE"}
OLD_DATE_LOOKS = DATE_TEXT_LOOKS | set(BOLD_DATE_LOOKS) | set(LEGACY_DATE_LOOKS)
# Words with a red or amber bar, rule or underline beside or under them (the
# owner, 2026-10-01: "not great"; VidRush's own text has none). Never picked by
# the planner, the director's hints included; the editor may still choose them.
# Kept: the mini timeline (txt-mini-timeline, "the line one") and the year line.
BAR_TEXT_LOOKS = {
    # LibPackText: an amber rule beside, before or under the words
    "LIB_TXT_KEY_PHRASE", "LIB_TXT_UNDERLINE_SWEEP", "LIB_TXT_KICKER_HEADLINE", "LIB_TXT_HEADLINE_WORDS",
    "LIB_TXT_BREAKING_TAG", "LIB_TXT_QUESTION",
    # the built-ins: a dark pill with an accent bar down its left side, a thick
    # accent bar under a typed headline, a BREAKING bar with an accent underline
    "TEXT_KEY_PHRASE_V1", "TEXT_BAR_TITLE_V1", "HEADLINE_BANNER_V1",
    # LibEditorText / LibCallouts: an accent bar between two lines, an amber cell
    # and dark bar beside the words, a marker scribble under the key word
    "LIB_ED_SPLIT_REVEAL", "LIB_ED_ALERT_BAR", "LIB_CO_SCRIBBLE_UNDERLINE",
    # LibHeadlines: an accent spine beside the stack, wiping bars, an accent
    # underline, an accent bar or band under the line, rules above and below
    "LIB_HL_WORD_STACK", "LIB_HL_WIPE_BAR", "LIB_HL_KEYWORD_POP", "LIB_HL_LETTER_FLIP", "LIB_HL_TICKER_SLIDE",
    "LIB_HL_SPLIT_LINE",
    # LibQuotes / LibSpeakers: an accent edge or rail beside the quote, underlines
    # under its words, a paper card with an accent spine and a highlighter under it
    "LIB_QS_SIDE_PANEL", "LIB_QS_TESTIMONY_RAIL", "LIB_QS_KARAOKE", "LIB_QS_ZOOM_WORD", "LIB_SP_STATEMENT_CARD",
    # an accent rule or a gold dash under a title, a hairline drawn beneath a line
    "LIB_CH_GLITCH_RESOLVE", "LIB_FX_SHAPE_WIPE", "LIB_CN_FOCUS_VIGNETTE",
    # LibPackPlaces: a thin amber rule under the warning
    "LIB_PLC_WARNING_LABEL",
}


def auto_ok(template_id: str) -> bool:
    """False for a look the planner never picks on its own (BAR_TEXT_LOOKS, the old date rotation)."""
    tid = template_id or ""
    return tid not in BAR_TEXT_LOOKS and tid not in OLD_DATE_LOOKS and not tid.startswith("LIB_DTX_")


NOT_FOR_A_DATE = {"LIB_TL_CALENDAR_FLIP", "LIB_TL_DATE_STAMP_CIRCLE", "LIB_LT_DATE_PLACE", "LIB_FX_LIGHT_STREAK",
                  "LIB_FX_FILM_BURN", "LIB_FX_PAPER_TEAR", "LIB_TL_YEAR_SCROLLER", "LIB_TL_DECADE_GRID",
                  "LIB_CH_YEAR_TAPE", "LIB_PB_DATE_PLATE", COUNTDOWN_LOOK}


def look_fits(template_id: str, text: str) -> bool:
    """False for a look that pictures one particular thing the line does not mention (or a banned look)."""
    if templates.banned(template_id):
        return False
    rx = _LOOK_NEEDS_RX.get(template_id)
    return rx is None or bool(rx.search(text or ""))


def _needs_places(t: dict, props: Optional[dict]) -> bool:
    """A map look drawn from places, asked for with none: it would render nothing."""
    return (t.get("category") == "MAPS" and "locations" in (t.get("props") or {})
            and not (props or {}).get("locations"))


def _weather_figure(req: dict, text: str) -> bool:
    """A must-show wind speed or rainfall the forecast map's legend stands for."""
    if req.get("figure_key") is None or not (_FORECAST_WIND.search(text) or _FORECAST_RAIN.search(text)):
        return False
    unit = str((req.get("props") or {}).get("suffix") or "").upper().strip()
    if unit in ("MI", "KM") and _PER_HOUR.search(text):
        unit = "MPH"
    return unit in _WX_UNITS


def _looks_for(ids: List[str], cue: str) -> List[dict]:
    out = []
    for tid in ids:
        t = templates.get(tid)
        if t and not templates.banned(tid) and cue in templates.cues_of(t):
            out.append(t)
    return out


def bold_date_looks(cue: str = "date") -> List[dict]:
    """The text-only date look for a cue (the letter drop); the old bold cards when the registry lacks it."""
    return _looks_for(BOLD_DATE_LOOKS, cue) or ([] if cue == "time-of-day" else _looks_for(LEGACY_DATE_LOOKS, cue))


def date_looks(cue: str = "date", style: str = "") -> List[dict]:
    """
    The looks that draw a date, a time or both: bold text for a date, a date
    and a time or a time of day (BOLD_DATE_LOOKS); the clock looks for a time
    of day only when the registry has no letter drop.
    """
    bold = bold_date_looks(cue)
    if bold:
        return bold
    options = [t for t in templates.for_cue(cue, style) if t["id"] not in NOT_FOR_A_DATE
               and "stills" not in (t.get("tags") or []) and t.get("category") != "IMAGES"]
    if cue == "time-of-day":
        # A clock, never a bold date card that happens to take a time.
        options = [t for t in options if t["id"] not in LEGACY_DATE_LOOKS] or options
    return options


def lead_look(tid: str) -> Optional[str]:
    """`tid` when the registry has it and it is not banned, else None."""
    return tid if templates.get(tid) and not templates.banned(tid) else None


def span_look() -> str:
    """The look for a span of time: the countdown while it may be used, else the bold count."""
    return lead_look(COUNTDOWN_LOOK) or BOLD_COUNT_LOOK


def _template_for_cue(cue: str, pack: dict, used_recently: set,
                      counts: Optional[Dict[str, int]] = None, text: str = "",
                      props: Optional[dict] = None) -> Optional[str]:
    if cue == "route":
        return _least_used([pack["route"], "MAP_TRACE_V1"], counts)
    if cue == "place":
        return _least_used(_place_maps(pack), counts)
    if cue == "chapter":
        return pack["chapter"]
    if cue in DATE_CUES:
        options = [t for t in date_looks(cue, pack.get("id", "")) if t["id"] not in used_recently]
    else:
        options = templates.for_cue(cue, pack.get("id", ""), exclude=used_recently)
    if cue == "typewriter":
        options = [t for t in options if templates.types(t)]
    options = [t for t in options if look_fits(t["id"], text) and not _needs_places(t, props) and auto_ok(t["id"])
               and t["id"] not in VR_LOOKS]
    if cue in SINGLE_FIGURE_CUES or (cue in TEXT_CUES and cue != "chapter"):
        # One figure, or words: on the clip, never a card that covers it.
        options = [t for t in options if "own-backdrop" not in (t.get("tags") or [])] or options
    elif cue in FULL_DATA_CUES:
        # Several values: a full-screen chart, not a tag squeezed onto the clip.
        options = [t for t in options if t.get("kind") != "tag"] or options
    if counts:
        # The least used look for this cue first (registry order breaks ties),
        # so a video's percentages rotate gauge, ring, dots, bar... instead of
        # the same gauge every time.
        options = sorted(options, key=lambda t: counts.get(t["id"], 0))
    return options[0]["id"] if options else None


def _hint_date_cue(hint: Optional[dict]) -> str:
    """
    The date cue a director's library look asks for by name ("dt-calendar-page"
    -> "date", "dt-clock-time" -> "time-of-day"), or ''. Such a hint is shown
    like any date on the line: in bold type, or a clock for a time alone.
    """
    if not isinstance(hint, dict) or hint.get("type") != "motion" or not hint.get("variant"):
        return ""
    # (Any look of the library, a banned one included: only its cues are read.)
    t = next((x for x in templates.all_templates() if x.get("component") == "motion"
              and (x.get("defaults") or {}).get("variant") == hint["variant"]), None)
    if not t or t.get("category") != "TIMELINES":
        return ""
    cues = set(templates.cues_of(t))
    if "time-of-day" in cues and "date" not in cues:
        return "time-of-day"
    return "date" if cues & {"date", "datetime"} else ""


def _hint_props(overlay: dict) -> dict:
    keep = {}
    for k in ("text", "subtitle", "label", "suffix", "value", "items", "locations", "highlight", "body",
              "media", "anchor", "labelPosition", "places"):
        if overlay.get(k) is not None:
            keep[k] = overlay[k]
    return keep


WINDOW_GAP = 90.0        # seconds between two scenes shown in a player window
_ARCHIVE_COUNTS: Dict[str, int] = {}
_PIP_KINDS = {"place", "location", "landmark", "building", "structure", "object", "artifact", "thing", "document"}


def _pip_for(shot: dict, scene: dict) -> Optional[dict]:
    """
    A photo window of the place or thing named, over footage that does not
    show it well (a weak or borrowed clip). People are left out on purpose: a
    searched photo of a name can be the wrong person.
    """
    subject = (shot.get("subject") or "").strip()
    kind = (shot.get("subjectType") or "").lower()
    if not subject or len(subject) < 4 or kind not in _PIP_KINDS:
        return None
    meta = scene.get("semanticMetadata") or {}
    score = meta.get("relevanceScore")
    reason = str(scene.get("reviewReason") or "")
    weak = (score is not None and float(score) < config.ANIMATION_OVER_FOOTAGE_BELOW) or reason.startswith(_WEAK_REASONS)
    if not weak:
        return None
    return {"text": subject[:60]}


def _archive_tag(scene: dict, style: str, pack: dict, fps: int, start: int, frames: int, total: int) -> Optional[dict]:
    """"ARCHIVE FOOTAGE · 1969" on the first clip of an archival run, only when the clip is archive film."""
    media = scene.get("media") or {}
    title = str(media.get("attribution") or "")
    if media.get("source") != "archive_org" and not _ARCHIVE_TITLE.search(title):
        return None
    year = re.search(r"\b(1[89]\d\d)\b", title)
    props = {"text": "Archive footage", **({"subtitle": year.group(1)} if year else {})}
    tid = _least_used(["TAG_SOURCE_V1"] + [t for t in _lib_looks("archive", still=False)
                                           if (templates.get(t) or {}).get("kind") == "tag"], _ARCHIVE_COUNTS) or "TAG_SOURCE_V1"
    _ARCHIVE_COUNTS[tid] = _ARCHIVE_COUNTS.get(tid, 0) + 1
    resolved = templates.resolve(tid, style=style, props=props, pack=pack)
    if not resolved:
        return None
    resolved.pop("seconds", None)
    resolved.pop("sfx", None)
    n = max(1, min(int(round(3.5 * fps)), frames, total - start))
    return {**resolved, "startFrame": start, "durationInFrames": n}


def _reset_rotation() -> None:
    """Every video starts its turns from zero (a warm worker used to carry them over between jobs)."""
    _ARCHIVE_COUNTS.clear()
    _corner_turn[0] = 0
    _photo_turn[0] = 0
    for n in _kind_turn.values():
        n[0] = 0


def _still_of(media: Optional[dict]) -> Optional[dict]:
    """The scene's picture: its image, or a frame of its clip (the renderer's stillOf)."""
    m = media or {}
    if not m.get("url"):
        return None
    if m.get("type") == "image":
        return dict(m)
    if m.get("thumbnail"):
        return {**m, "type": "image", "url": m["thumbnail"]}
    return None


def _seed(segments: List[Segment]) -> int:
    """A per-video shuffle: the same script plans the same way, two scripts do not open on the same looks."""
    return zlib.crc32("|".join((getattr(s, "text", "") or "") for s in segments[:8]).encode("utf-8"))


def _offset(text: str, key) -> int:
    """Where in the line a graphic's word is said (to order two graphics on one line)."""
    if key is None or key == "":
        return 0
    if isinstance(key, (int, float)):
        v = float(key)
        key = str(int(v)) if v.is_integer() else str(v)
        # "3,510" is said as the figure 3510: match the digits with or without their commas.
        m = re.search(r",?".join(re.escape(ch) for ch in key), text or "")
        return m.start() if m else 0
    k = (text or "").lower().find(str(key).lower())
    return k if k >= 0 else 0


def _clear_figure(cue: dict) -> bool:
    """A figure worth a counting graphic every time: a percent, money, a ratio, a count, several values,
    a span of time, or a number of ten or more (with its scale)."""
    name = cue.get("cue")
    if name in ("percent", "money", "money-compare", "ratio", "count", "time-span") or name in FULL_DATA_CUES:
        return True
    p = cue.get("props") or {}
    try:
        v = float(p.get("value"))
    except (TypeError, ValueError):
        return False
    scale = str(p.get("suffix") or "").upper()
    return abs(v) >= 10 or scale in ("MILLION", "BILLION", "THOUSAND", "M", "B", "K", "T", "%") \
        or not float(v).is_integer()


class _Looks:
    """
    Which look goes next. The least used look for the cue first; a look shown
    in the last LOOK_GAP seconds only when nothing else fits; a different
    family from the previous graphic first; the pack's or the director's
    preference, then a per-video shuffle, break ties.
    """

    def __init__(self, seed: int, uses: Dict[str, int]):
        self.seed = seed
        self.uses = uses
        self.last: Dict[str, float] = {}
        self.times: Dict[str, List[float]] = {}
        self.last_family = ""
        self.last_text_family = ""
        self.last_in: Dict[str, str] = {}

    def _h(self, tid: str) -> int:
        return zlib.crc32(f"{self.seed}|{tid}".encode("utf-8"))

    def fresh(self, tid: str, at: float) -> bool:
        return at - self.last.get(tid, -1e9) >= LOOK_GAP

    def recent(self, tid: str, at: float, window: float) -> int:
        return sum(1 for x in self.times.get(tid, []) if 0 <= at - x < window)

    def order(self, pool: List[dict], at: float, prefer=(), demote=(), text_beat: bool = False) -> tuple:
        """(fresh, stale): the looks in the order to try them."""
        seen, uniq = set(), []
        for t in pool:
            if t and t["id"] not in seen and not templates.banned(t["id"]):
                seen.add(t["id"])
                uniq.append(t)
        if text_beat and self.last_text_family:
            # Two text beats in a row never share a family.
            other = [t for t in uniq if templates.family(t) != self.last_text_family]
            uniq = other or uniq

        def key(t):
            tid = t["id"]
            return (1 if tid in demote else 0,
                    1 if self.last_family and templates.family(t) == self.last_family else 0,
                    self.uses.get(tid, 0),
                    0 if tid in prefer else 1,
                    self._h(tid))
        fresh = sorted((t for t in uniq if self.fresh(t["id"], at)), key=key)
        stale = sorted((t for t in uniq if not self.fresh(t["id"], at)), key=lambda t: (self.last.get(t["id"], -1e9), key(t)))
        return fresh, stale

    def use(self, t: dict, at: float, group: str = "", text_beat: bool = False) -> None:
        tid = t["id"]
        self.uses[tid] = self.uses.get(tid, 0) + 1
        self.last[tid] = at
        self.times.setdefault(tid, []).append(at)
        self.last_family = templates.family(t)
        if text_beat:
            self.last_text_family = self.last_family
        if group:
            self.last_in[group] = tid


# How long a graphic must stay up before a must-show graphic may cut it short.
MIN_VISIBLE = {"text": 1.6, "figure": 1.8, "full": 3.0, "map": 3.5, "cutaway": 2.5, "person": 2.5, "persist": 3.0}
_TEXT_CATEGORIES = {"TEXT", "HEADLINES", "QUOTES", "LOWER_THIRDS"}
# The renderer draws the text families a fifth larger by default (Main.tsx); the
# owner wants text a proper size, so the planner sets it: 1.1 for a text look,
# as designed for a tag riding on the footage.
TEXT_FONT_SCALE = 1.1
# A span of time ("3 days later") is a figure too: it counts up on the countdown look.
FIGURE_CUES = SINGLE_FIGURE_CUES | FULL_DATA_CUES | {"count", "time-span"}
# The cues whose looks show numbers: written in digits however they were said (numwords).
DIGIT_CUES = FIGURE_CUES | set(DATE_CUES) | {"age"}
# What a line asks for in words, strongest first; each still needs the rhythm.
STRONG_LINE_CUES = ("recording", "document", "quote", "question", "warning", "route")
SOFT_LINE_CUES = ("typewriter", "term")
_NUMERIC_HINTS = {"ring-stat", "stat", "donut", "counter", "number-roll", "stat-tag"}
_SFX_PROPS = ("text", "value", "suffix", "prefix", "label", "subtitle", "highlight", "items", "locations", "total")


def plan(segments: List[Segment], shots: List[dict], scenes: List[dict], fps: int, total: int,
         brief: Optional[dict], pack: dict, seconds_for: Optional[Dict[str, float]] = None,
         voice_lufs: Optional[float] = None, reserved: Optional[List[tuple]] = None,
         video_style: str = "") -> Dict[str, Any]:
    """
    Overlays, transitions, sounds, music sections and per-scene treatments.

    `scenes` are the built scene dicts (start/duration frames, media type);
    `seconds_for` (the renderer's hold per component) is kept for callers -
    the owner's per-kind windows (LAYOUT_WINDOWS) now decide how long a look
    stays. `voice_lufs` is the narration's loudness the sounds are set
    against; `reserved` are (start, end) seconds already taken on screen
    (the job's title card): nothing is laid over them. `video_style` (the
    job's, src/styles.py) picks the date and time looks' theme (vr_theme).
    """
    return _Planner(segments, shots, scenes, fps, total, brief, pack, seconds_for, voice_lufs, reserved,
                    video_style).run()


class _Planner:
    """One video's treatment plan (see plan())."""

    def __init__(self, segments, shots, scenes, fps, total, brief, pack, seconds_for, voice_lufs=None, reserved=None,
                 video_style=""):
        _reset_rotation()
        self.segments, self.shots, self.scenes = segments, shots, scenes
        self.fps, self.total = fps, total
        self.brief = brief if isinstance(brief, dict) else {}
        self.pack = pack
        self.seconds_for = seconds_for or {}
        self.voice_lufs = voice_lufs
        self.style = pack.get("id", "documentary")
        self.intensity = float(pack.get("animationIntensity", 1.0))
        self.hooks = set(self.brief.get("hookBeats") or [])
        self.section_starts = {int(s["from"]) for s in (self.brief.get("sections") or [])
                               if isinstance(s, dict) and isinstance(s.get("from"), int)
                               and not isinstance(s.get("from"), bool)}
        self.cast = [c for c in (self.brief.get("cast") or []) if isinstance(c, dict)]
        self.rhythm = _Rhythm()
        self.use_count: Dict[str, int] = {}
        self.looks = _Looks(_seed(segments), self.use_count)
        self.overlays: List[dict] = []
        self.treatments: List[dict] = []
        # What is on screen, in order: {"start", "end", "idx", "klass", "must", "tr"} (seconds).
        self.spans: List[dict] = []
        self.silent: set = set()
        self.seen_figures: Dict[tuple, float] = {}
        self.introduced: List[str] = []
        self.last_person_full = -1e9
        self.phrases: Dict[str, float] = {}
        self.skip_next_still = False
        self.n_maps = 0
        self.i = 0
        # Video style (src/styles.py): "minimal" = a news compilation's cut -
        # dates, spaced figures and maps only; "normal" drops the filler label.
        self.density = (config.GRAPHICS_DENSITY or "rich").lower()
        self.last_min_figure = -1e9
        # The last geocoded places a map hint carried, for the forecast map.
        self.last_locations: List[dict] = []
        self.last_forecast = -1e9
        # Dates and times (VR_LOOKS): one theme for the whole video, every line's
        # moment (vr_moment), the ones chosen to show (_vr_select) and the ones shown.
        self.vr_theme = vr_theme(video_style, self.brief, pack)
        self.vr_moments: Dict[int, dict] = {}
        self.vr_chosen: set = set()
        self.vr_placed: List[dict] = []
        # The text-only looks' placements in turn, their letterings in turn (one turn shared by the
        # date and the count, from a per-video start), and the figure looks shown (the bold count's run).
        self.align_turn: Dict[str, int] = {}
        self.style_turn = _seed(segments) % len(TEXT_LOOK_STYLES)
        self.figure_looks: List[str] = []
        # The case-file devices, each rationed: one intro collage, a player
        # window at most every WINDOW_GAP seconds, an archive tag per archival run.
        self.intro_done = False
        self.last_window = -1e9
        self.prev_archival = False
        # A persisting look (LibPersist, "ps-") is one object riding across cuts:
        # no second one is scheduled while it is live.
        self.persist_until = -1e9
        # (overlay index, treatment index, layout class) of the overlays that may
        # be held across the short cuts that follow them (_persist_figures).
        self.persisting: List[tuple] = []
        # Frame spans the clip is covered by (full-screen graphics): a persisting
        # figure never runs under one.
        self.covered: List[tuple] = []
        # Seconds where no overlay may be (the owner's Texas video: tags laid
        # over full-screen graphics were hidden by them): every animation scene,
        # which IS a full-screen graphic or chart.
        self.blocks: List[tuple] = []
        for sc in self.scenes:
            if (sc.get("media") or {}).get("type") == "animation":
                a = int(sc.get("startFrame", 0))
                self.blocks.append((a / fps, (a + int(sc.get("durationInFrames", 0))) / fps))
        # Seconds already taken by the caller (the job's title card): held like a must-show graphic.
        for a, b in reserved or []:
            try:
                a, b = float(a), float(b)
            except (TypeError, ValueError):
                continue
            if b > a:
                self.spans.append({"start": a, "end": b, "idx": None, "klass": "full", "must": True, "tr": None})
                self.covered.append((int(round(a * fps)), int(round(b * fps))))

    # ------------------------------------------------------------------ run
    def run(self) -> Dict[str, Any]:
        # Figures already drawn full screen by animation scenes count as seen.
        for sc_i, sc in enumerate(self.scenes):
            anim = sc.get("animation") if (sc.get("media") or {}).get("type") == "animation" else None
            if anim and anim.get("value") is not None and sc_i < len(self.segments):
                try:
                    self.seen_figures[("figure", float(anim["value"]))] = self.segments[sc_i].start
                except (TypeError, ValueError):
                    pass
        self._vr_select()
        for i, seg in enumerate(self.segments):
            self.i = i
            self._beat(i, seg)
        _persist_figures(self.overlays, self.treatments, self.persisting, self.covered, self.scenes, self.fps,
                         self.total, self.segments)
        # One graphic at a time, never over a full-screen scene (a safety net
        # behind the placement rules; the sounds are planned after it).
        self._one_at_a_time()
        sfx = self._sfx()
        music = _plan_music(self.segments, self.brief, self.fps, self.total, self.hooks)
        for i, entry in enumerate(self.treatments):
            cue = next((s["mood"] for s in music["sections"]
                        if s["startFrame"] <= self.scenes[i].get("startFrame", 0) < s["endFrame"]), None) \
                if i < len(self.scenes) else None
            entry["musicCue"] = cue
        return {"overlays": self.overlays, "treatments": self.treatments, "sfx": sfx, "music": music,
                "counts": counts(self.scenes, self.overlays, sfx, music, self.treatments),
                # Every look plays the sound built into it (LookSounds.tsx), at the
                # pack's intensity against the voice; `sfx` holds no row for them.
                "lookSounds": {"intensity": round(max(0.0, float(self.pack.get("sfxIntensity", 1.0))), 3)}}

    def _sfx(self) -> List[dict]:
        """The sound pass (src/sfxplan.py) when it is there, else one sound per graphic moment."""
        intensity = float(self.pack.get("sfxIntensity", 1.0))
        live = [ov for j, ov in enumerate(self.overlays) if j not in self.silent]
        try:
            from . import sfxplan
        except ImportError:
            sfxplan = None
        if sfxplan is not None and hasattr(sfxplan, "plan"):
            items = [{**ov, "durationFrames": int(ov.get("durationInFrames") or 0),
                      "props": {k: ov[k] for k in _SFX_PROPS if k in ov}} for ov in live]
            try:
                return list(sfxplan.plan(items, self.fps, intensity, self.style, voice_lufs=self.voice_lufs) or [])
            except Exception as e:      # a sound bug must never cost the video
                print(f"[treatments] sound planner failed ({type(e).__name__}: {e}); one sound per graphic instead")
        return _plan_sfx(live, self.treatments, self.fps, intensity, self.voice_lufs)

    def _one_at_a_time(self) -> None:
        """
        Never two overlays on screen at once and never one over a full-screen
        scene: an overlay still up when the next one lands ends there, one
        running into an animation scene ends where it starts, and one that
        would start on such a scene - or be left too short to read - is dropped.
        """
        fps = self.fps
        blocks = [(int(round(a * fps)), int(round(b * fps))) for a, b in self.blocks]
        order = sorted(range(len(self.overlays)), key=lambda j: (int(self.overlays[j]["startFrame"]), j))
        drop = set()
        for n, j in enumerate(order):
            ov = self.overlays[j]
            s = int(ov["startFrame"])
            e = s + int(ov["durationInFrames"])
            if any(a <= s < b for a, b in blocks):
                drop.add(j)
                continue
            limit = min([a for a, _b in blocks if a > s] + [e])
            nxt = next((int(self.overlays[k]["startFrame"]) for k in order[n + 1:] if k not in drop), None)
            if nxt is not None:
                limit = min(limit, max(s, nxt))
            if limit < e:
                # Never shorter than its own animation: rather not at all.
                least = int(round(max(1.0, animation_seconds(templates.get(ov.get("template") or "") or {})) * fps))
                if limit - s < least:
                    drop.add(j)
                    continue
                ov["durationInFrames"] = limit - s
                self._sync_duration(j, limit - s)
        if drop:
            keep = [j for j in range(len(self.overlays)) if j not in drop]
            index = {old: new for new, old in enumerate(keep)}
            self.overlays = [self.overlays[j] for j in keep]
            self.silent = {index[j] for j in self.silent if j in index}

    # ------------------------------------------------------- dates and times
    def _section_place(self, i: int) -> str:
        """The region tag of line i's section: the shot's region, else the brief section's "where"."""
        shot = self.shots[i] if 0 <= i < len(self.shots) else {}
        region = str((shot or {}).get("region") or "").strip()
        if region:
            return region
        for s in self.brief.get("sections") or []:
            if isinstance(s, dict) and isinstance(s.get("from"), int) and isinstance(s.get("to"), int) \
                    and s["from"] <= i <= s["to"]:
                return str(s.get("where") or "").strip()
        return ""

    def _vr_select(self) -> None:
        """
        Every line's date or time moment (vr_moment), and the ones to show: at
        most one per VR_GAP seconds, the hero at most once per VR_HERO_GAP, the
        strongest first - the story's start date (its first full date, always
        shown when said in the first VR_FIRST_HERO seconds), a clock time with
        a place or a date, a jump in years - then the rest where room is left.
        """
        year = None
        first = True
        for i, seg in enumerate(self.segments):
            shot = self.shots[i] if i < len(self.shots) else {}
            scene = self.scenes[i] if i < len(self.scenes) else {}
            m, year = vr_moment(seg.text or "", shot, self.brief, year, self._section_place(i))
            if m is None or (scene.get("media") or {}).get("type") == "animation":
                continue                    # (an animation scene IS a full-screen graphic: nothing lands on it)
            m = dict(m, i=i, at=_voice_window(seg, {"_key": m["key"]}, 1.0, 1.0, self.fps)[0], forced=False)
            if m["full_date"] and first:
                first = False
                m["strength"] = 4
                m["forced"] = m["at"] < VR_FIRST_HERO
            self.vr_moments[i] = m
        chosen: List[dict] = []
        for m in sorted(self.vr_moments.values(), key=lambda m: (not m["forced"], -m["strength"], m["at"])):
            # (A graphic may land up to SLIDE_SLACK late: the plan keeps that much more room.)
            if _vr_fits(m, chosen, SLIDE_SLACK):
                chosen.append(m)
        self.vr_chosen = {m["i"] for m in chosen}

    def _vr_request(self, seg) -> Optional[dict]:
        """The date or time graphic for this line, when it was chosen - or when the one that took its room never showed."""
        m = self.vr_moments.get(self.i)
        if not m:
            return None
        if self.i not in self.vr_chosen:
            ahead = [self.vr_moments[j] for j in self.vr_chosen if j > self.i]
            if not (_vr_fits(m, self.vr_placed) and _vr_fits(m, ahead, SLIDE_SLACK)):
                return None
        props = dict(m["props"], theme=self.vr_theme, _key=m["key"])
        return {"ids": [m["look"]], "cues": [], "cue": m["cue"], "props": props, "mode": "must", "group": "",
                "emphasis": "high", "layout": "text", "offset": _offset(seg.text or "", m["key"]), "vr": True}

    def _sync_duration(self, j: int, frames: int) -> None:
        """A treatment entry that shows overlay j follows its new length."""
        tid = self.overlays[j].get("template")
        start = int(self.overlays[j]["startFrame"])
        for span in self.spans:
            if span.get("idx") == j and span.get("tr") is not None and span["tr"] < len(self.treatments):
                entry = self.treatments[span["tr"]]
                if entry.get("overlays") and entry["overlays"][0] == tid:
                    entry["duration"] = round(frames / self.fps, 2)
                span["end"] = (start + frames) / self.fps

    # ----------------------------------------------------------------- beat
    def _beat(self, i: int, seg) -> None:
        shot = self.shots[i] if i < len(self.shots) else {}
        scene = self.scenes[i] if i < len(self.scenes) else {}
        at = float(seg.start)
        fps = self.fps
        start = int(scene.get("startFrame", int(round(at * fps))))
        scene_frames = int(scene.get("durationInFrames", int(round(seg.duration * fps))))
        media_kind = (scene.get("media") or {}).get("type")
        if media_kind == "animation":
            self._animation_scene(seg, scene, at, scene_frames)
            return
        text = seg.text or ""
        hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else None
        if hint and (not hint.get("type") or hint["type"] in ("photo-card", "name-card")):
            hint = None
        cues = cues_for(seg, shot, self.brief)
        placed: List[dict] = []

        # 1. What always shows: a date or a time, a clear figure (it counts up),
        #    the first mention of a named person - in the order they are said.
        musts, repeated = self._musts(seg, shot, scene, cues, hint)
        minimal = self.density == "minimal"
        if hint and hint.get("type") == "map" and hint.get("locations"):
            self.last_locations = list(hint["locations"])
        # A weather story's forecast line ("gusts to 60 mph", "the storm tracks
        # up the coast"): the animated forecast-model map of the region takes
        # the line - its legend carries the speeds, so no separate counter.
        forecast = None
        if self.last_locations and at - self.last_forecast >= FORECAST_GAP                 and self.brief.get("kind") in ("weather", "disaster", "news") and _FORECAST.search(text):
            rain = bool(_FORECAST_RAIN.search(text)) and not _FORECAST_WIND.search(text)
            # Only the view the title names: a wind line never gets the rain bands.
            forecast = {"cues": ["forecast-rain" if rain else "forecast-wind"], "group": "map",
                        "emphasis": "high", "mode": "must",
                        "props": {"text": "HEAVY RAIN" if rain else "WIND GUSTS",
                                  "locations": self.last_locations[:5]}}
        if minimal:
            # A news compilation shows almost no graphics: the date, a figure
            # now and then, maps. No person cards, no text looks. (The figure
            # window starts when a figure lands: _place.)
            kept = []
            for req in musts:
                if req.get("group") == "person":
                    continue
                if req.get("figure_key") is not None and at - self.last_min_figure < MINIMAL_FIGURE_GAP:
                    continue
                kept.append(req)
            musts = kept
            repeated = None
        # The wind speed or rainfall waits for the forecast map, and shows only
        # when the map does not land. Any other figure keeps its place.
        weather_figs: List[dict] = []
        if forecast:
            weather_figs = [r for r in musts if _weather_figure(r, text)]
            musts = [r for r in musts if not _weather_figure(r, text)]
        for req in musts:
            if len(placed) >= 2:
                break
            got = self._request(req, seg, scene, req.get("mode", "must"))
            if got:
                placed.append(got)
        if forecast and len(placed) < 2:
            got = self._request(forecast, seg, scene, "seq" if placed else "must")
            if got:
                placed.append(got)
                self.last_forecast = at
                weather_figs = []
        for req in weather_figs:
            if len(placed) >= 2:
                break
            got = self._request(req, seg, scene, req.get("mode", "must"))
            if got:
                placed.append(got)
        # 2. The director's proposal, through the same rotation. A map may follow
        #    a must-show graphic on the same line when there is room.
        if hint:
            req = self._hint_request(i, seg, shot, scene, hint, cues, placed)
            if req and minimal and req.get("group") != "map":
                req = None
            if req and (not placed or (req.get("group") == "map" and len(placed) < 2)):
                got = self._request(req, seg, scene, "seq" if placed else req.get("mode", "normal"))
                if got:
                    placed.append(got)
        if minimal:
            self.treatments.append(self._entry(scene, placed, i))
            return
        # 3. About one still in two becomes a photo animation, by what it shows.
        if media_kind == "image":
            if self.skip_next_still:
                self.skip_next_still = False
            elif not placed:
                got = self._photo(i, seg, shot, scene)
                if got:
                    placed.append(got)
                    self.skip_next_still = True
        # 4. The line's own words: a quote, a question, a warning; then a typed
        #    rhetorical line or a term, less often.
        typed_hint = bool(hint) and HINT_CUES.get(hint.get("type") or "") == "typewriter"
        if not placed:
            for c in cues:
                if c["cue"] in STRONG_LINE_CUES and not (typed_hint and c["cue"] == "question"):
                    # (A line the director wanted typed is typed or left alone, never a static title.)
                    got = self._request(self._cue_request(c, seg), seg, scene, "normal")
                    if got:
                        placed.append(got)
                        break
        if not placed and at - self.rhythm.last_text >= SOFT_TEXT_GAP:
            for c in cues:
                if c["cue"] in SOFT_LINE_CUES:
                    got = self._request(self._cue_request(c, seg), seg, scene, "normal")
                    if got:
                        placed.append(got)
                        break
        # 5. A figure said again within REPEAT_GAP: the words, the figure highlighted.
        if not placed and repeated is not None:
            req = self._fact_request(seg, repeated)
            got = self._request(req, seg, scene, "normal") if req else None
            if got:
                placed.append(got)
        # 6. "This is the story of...": a burst of the video's own pictures, once.
        if not placed and not self.intro_done and at < 150.0 and _INTRO.search(text) and len(self.scenes) - i > 4:
            req = {"ids": ["PHOTO_COLLAGE_V1"] + _lib_looks("intro", still=False), "prefer": ["PHOTO_COLLAGE_V1"],
                   "props": {}, "group": "intro", "emphasis": "high"}
            got = self._request(req, seg, scene, "normal")
            if got:
                placed.append(got)
                self.intro_done = True
        # 7. A photo window of the place or thing over a weak clip of it.
        if not placed and media_kind == "video":
            pip = _pip_for(shot, scene)
            if pip:
                req = {"ids": ["PHOTO_PIP_V1"] + _lib_looks("subject-photo"), "prefer": ["PHOTO_PIP_V1"],
                       "props": pip, "group": "pip", "emphasis": "medium"}
                got = self._request(req, seg, scene, "normal")
                if got:
                    placed.append(got)
        # 8. A section opens on a short line: its headline.
        if not placed and i in self.section_starts and i > 0:
            head = next((c for c in cues if c["cue"] == "headline"), None)
            if head:
                got = self._request(self._cue_request(head, seg), seg, scene, "normal")
                if got:
                    placed.append(got)
        # 9. A long stretch of plain footage: a light label with the line's key
        #    phrase (a name, a superlative), never the same phrase twice in a row.
        if not placed and at - self.rhythm.quiet_from > QUIET_MAX and self.intensity >= 0.6                 and self.density == "rich":
            c = next((c for c in cues if c["cue"] in ("key-phrase", "caption")), None)
            phrase = str((c or {}).get("props", {}).get("text") or "").strip()
            if phrase and at - self.phrases.get(phrase.upper(), -1e9) >= LOOK_GAP:
                key = phrase.split()[0]
                req = {"cues": ["caption", "key-phrase"], "merge": True, "group": "filler", "emphasis": "low",
                       "props": {"text": phrase.upper(), "_key": key},
                       "props_by_cue": {"caption": {"text": phrase.upper(), "_key": key},
                                        "key-phrase": {"text": phrase, "_key": key}}}
                got = self._request(req, seg, scene, "normal")
                if got:
                    placed.append(got)
                    self.phrases[phrase.upper()] = at

        self.treatments.append(self._entry(scene, placed, i))
        chosen = placed[0]["t"] if placed else None
        archival = media_kind == "video" and scene.get("treatment") in ("archival", "vintage")
        if archival and not self.prev_archival and not placed:
            tag = _archive_tag(scene, self.style, self.pack, fps, start, scene_frames, self.total)
            if tag:
                # One graphic at a time: the tag waits for a free screen (or is left out).
                a = tag["startFrame"] / fps
                free = self._clear_until(a)
                if any(s["start"] <= a < s["end"] + BREATH for s in self.spans) or free - a < 1.5 \
                        or any(b0 <= a < b1 for b0, b1 in self.blocks):
                    tag = None
                elif (tag["startFrame"] + tag["durationInFrames"]) / fps > free:
                    tag["durationInFrames"] = max(1, int(free * fps) - tag["startFrame"])
            if tag:
                self.silent.add(len(self.overlays))
                self.spans.append({"start": tag["startFrame"] / fps,
                                   "end": (tag["startFrame"] + tag["durationInFrames"]) / fps,
                                   "idx": len(self.overlays), "klass": "text", "must": False, "tr": None})
                self.overlays.append(tag)
        self.prev_archival = archival
        if (media_kind == "video" and at - self.last_window >= WINDOW_GAP and _FOOTAGE_WORDS.search(text)
                and not (chosen and chosen.get("kind") in CARD_KINDS) and scene_frames >= fps * 2.5):
            # "Footage shows...": the clip plays in a player window on the desk.
            scene["frame"] = "window"
            self.last_window = at

    def _animation_scene(self, seg, scene: dict, at: float, scene_frames: int) -> None:
        """The beat already IS a graphic (timeline.build filled it): no overlay on top, but it counts."""
        anim = scene.get("animation") or {}
        t = templates.get(anim.get("template") or "")
        self.treatments.append({
            "primaryType": "animation", "secondaryType": t["category"].lower() if t else None,
            "template": anim.get("template"), "variant": anim.get("variant") or anim.get("style"),
            "entrance": anim.get("motion"), "exit": anim.get("exit"),
            "duration": round(scene_frames / self.fps, 2), "emphasis": "high", "animation": anim.get("motion"),
            "data": {k: anim[k] for k in ("value", "suffix", "items") if k in anim},
            "text": str(anim.get("text") or ""),
            "mapData": {"locations": anim.get("locations")} if anim.get("locations") else None,
            "chartData": None, "overlays": [], "transitionIn": scene.get("transition", "none"),
            "transitionOut": "none", "sfx": None, "musicCue": None,
        })
        if t:
            self.rhythm.note(at, t, scene_frames / self.fps)
            self.looks.use(t, at)
            if t.get("kind") == "map" or t.get("component") == "map":
                self.n_maps += 1
        # Nothing may be cut short into it, and nothing lands on it.
        self.spans.append({"start": at, "end": at + scene_frames / self.fps, "idx": None, "klass": "full",
                           "must": True, "tr": None})
        self.prev_archival = False

    # ------------------------------------------------------------- requests
    def _musts(self, seg, shot: dict, scene: dict, cues: List[dict], hint: Optional[dict]) -> tuple:
        """(requests that must show on this line, the repeated figure if any)."""
        text = seg.text or ""
        at = float(seg.start)
        out: List[dict] = []
        repeated = None
        # A date or a time: only the moments _vr_select chose, in the VidRush
        # looks. The director's own date stamps are not shown: their words
        # ("WEDNESDAY", a worked-out date) are not always the narration's.
        vr = self._vr_request(seg)
        if vr:
            out.append(vr)
        fig = None
        for c in cues:
            if c["cue"] not in FIGURE_CUES or c["cue"] == "time-span":
                continue            # ("3 days later", "48 hours": a relative time gets no graphic)
            key = _figure_key(c)
            if key and at - self.seen_figures.get(key, -1e9) < REPEAT_GAP:
                # "26%" again twenty seconds later: not the same gauge twice.
                repeated = repeated or c
                continue
            fig = c
            break
        if fig is None and repeated is None and hint and hint.get("type") in _NUMERIC_HINTS \
                and hint.get("value") is not None:
            pct = str(hint.get("suffix") or "").strip() == "%" or hint["type"] in ("ring-stat", "donut")
            fig = {"cue": "percent" if pct else "big-number", "emphasis": "high", "props": _hint_props(hint)}
        if fig is not None:
            req = self._cue_request(fig, seg)
            req["mode"] = "must" if _clear_figure(fig) else "normal"
            req["figure_key"] = _figure_key(fig)
            out.append(req)
        person = next((c for c in cues if c["cue"] == "person-full"), None)
        if person:
            name = person["props"].get("text") or ""
            if name and not any(_same_person(name, n) for n in self.introduced):
                # The first mention only: later lines keep the lower third.
                self.introduced.append(name)
                if at - self.last_person_full >= PERSON_FULL_GAP:
                    props = dict(person["props"])
                    out.append({"cues": ["person-full"], "props": props, "mode": "must", "group": "person",
                                "emphasis": "high", "layout": "person", "media": _still_of(scene.get("media")),
                                "offset": _offset(text, props.get("_key", ""))})
        region = _REGION_CHANGE.search(text)
        if region and not out and lead_look(SECTION_LOOK):
            # The walk to a new region gets its marker ("NOW · NEW JERSEY"), on
            # a line that has no date or figure of its own.
            out.append({"ids": [SECTION_LOOK], "cues": [], "cue": "section", "group": "section",
                        "props": {"text": region.group("place").rstrip(".,;:").upper()[:28]}, "mode": "normal",
                        "emphasis": "medium", "offset": 0})
        out.sort(key=lambda r: r.get("offset", 0))
        return out, repeated

    def _cue_request(self, c: dict, seg) -> dict:
        props = dict(c.get("props") or {})
        req = {"cues": [c["cue"]] + CUE_FALLBACK.get(c["cue"], []), "props": props, "mode": "normal",
               "group": "text" if c["cue"] in TEXT_BEAT_CUES else c["cue"], "emphasis": c.get("emphasis") or "medium",
               "offset": _offset(seg.text or "", props.get("_key") or _num(str(props.get("value") or "")))}
        lead = lead_look(BOLD_COUNT_LOOK) if c["cue"] in BOLD_COUNT_CUES else None
        recent = self.figure_looks[-BOLD_COUNT_RUN:]
        if lead and not (len(recent) == BOLD_COUNT_RUN and all(x == lead for x in recent)):
            # The bold count leads; after BOLD_COUNT_RUN of them in a row, one other look for variety.
            req["lead"] = lead
        if c["cue"] == "route":
            req.update(ids=[self.pack["route"], "MAP_ROUTE_SAT_V1", "MAP_TRACE_V1"], cues=[], cue="route",
                       group="map", mode="seq")
        # (A span of time - "3 days later", "48 hours" - is a relative time: _musts gives it no graphic.)
        return req

    def _fact_request(self, seg, repeated: dict) -> Optional[dict]:
        sentence = (seg.text or "").strip()
        if len(sentence) > 110:
            return None
        words = _figure_words(sentence, repeated)
        return {"cues": ["fact", "statement", "key-phrase"], "group": "text", "emphasis": "medium",
                "props": {"text": sentence.rstrip("."), "highlight": words},
                "props_by_cue": {"key-phrase": {"text": words, "_key": words.split()[0] if words.split() else ""}}}

    def _hint_request(self, i: int, seg, shot: dict, scene: dict, hint: dict, cues: List[dict],
                      placed: List[dict]) -> Optional[dict]:
        """The director's overlay, read as a cue (or a map, a lower third, a chapter) for the rotation."""
        kind = hint.get("type") or ""
        variant = hint.get("variant") or ""
        text = seg.text or ""
        props = _hint_props(hint)
        if hint.get("motion"):
            props["_motion"] = hint["motion"]
        if kind == "map":
            still = _still_of(scene.get("media"))
            ids, by_variant = _map_ids(hint, self.pack, bool(still), self.n_maps)
            return {"ids": ids, "first": by_variant, "prefer": [self.pack.get("map", "")], "props": props,
                    "mode": "director", "group": "map", "emphasis": "high",
                    "media_for": {"MAP_PHOTO_PIN_V1": still} if still else {}}
        if kind == "lower-third":
            name = str(hint.get("text") or "").strip()
            if name and any(_same_person(name, n) for n in self.introduced) and any(
                    p["cue"] == "person-full" for p in placed):
                return None
            if name and not any(_same_person(name, n) for n in self.introduced):
                self.introduced.append(name)
            role = _role_of(name, self.cast)
            if role and not props.get("subtitle"):
                props["subtitle"] = role
            own = self.pack.get("lowerThird", "")
            ids = [own] + [t["id"] for t in templates.for_cue("person", self.style)
                           if t.get("category") == "LOWER_THIRDS" and t.get("kind") == "tag"
                           and "own-backdrop" not in (t.get("tags") or [])]
            return {"ids": ids, "prefer": [own], "props": props, "mode": "director", "group": "lower-third",
                    "emphasis": "low"}
        if kind == "bullets" and not variant:
            return {"ids": ["CALL_BULLETS_V1", "FACTS_CARD_V1"], "props": props, "mode": "director",
                    "group": "bullets", "emphasis": "medium"}
        if kind == "chapter":
            title = _clause(str(hint.get("text") or ""), 8, 60)
            if i in self.section_starts and title:
                # A real section start keeps a chapter card (never the news
                # banner, which reads "BREAKING" over a chapter title).
                own = self.pack.get("chapter", "")
                own_t = templates.get(own) or {}
                own = own if own_t and own_t.get("component") != "banner" else ""
                ids = ([own] if own else []) + [
                    t["id"] for t in templates.for_cue("chapter", self.style)
                    if t.get("component") not in ("banner",) and not ({"still", "stills"} & set(t.get("tags") or []))
                    and t.get("category") in ("HEADLINES", "TEXT")]
                return {"ids": ids, "prefer": [own] if own else [], "cue": "chapter", "mode": "director",
                        "group": "text", "emphasis": "high", "props": {**props, "text": title}}
        if kind == "motion" and variant:
            if _hint_date_cue(hint):
                return None         # a date look by name: the must-show pass showed it in bold type
            t = next((x for x in templates.for_component("motion") if (x.get("defaults") or {}).get("variant") == variant),
                     None)
            if t:
                cue0 = next((c for c in templates.cues_of(t)), "")
                return {"ids": [t["id"]], "cues": ([cue0] + CUE_FALLBACK.get(cue0, [])) if cue0 else [],
                        "cue": cue0, "props": props, "mode": "normal",
                        "group": "text" if cue0 in TEXT_BEAT_CUES else cue0, "emphasis": t.get("emphasis", "medium")}
            return None
        cue = HINT_CUES.get(kind)
        if cue in FIGURE_CUES or cue in DATE_CUES:
            return None             # the must-show pass placed (or deliberately skipped) it
        if cue:
            return self._text_hint(kind, cue, hint, props, seg, shot, cues)
        # Any other component the director asked for (a timeline, a trend...):
        # its looks, the variant it named first, on the director's word.
        options = [t for t in templates.for_component(kind, self.style) if look_fits(t["id"], text)]
        if not options:
            return None
        first = next((t["id"] for t in options if variant and (t.get("defaults") or {}).get("variant") == variant), "")
        return {"ids": [t["id"] for t in options], "first": first, "props": props, "mode": "director",
                "group": kind, "emphasis": options[0].get("emphasis", "medium")}

    def _text_hint(self, kind: str, cue: str, hint: dict, props: dict, seg, shot: dict, cues: List[dict]) -> Optional[dict]:
        """A text overlay the director proposed, as a headline, key phrase, quote or typed line."""
        text = seg.text or ""
        said = str(hint.get("text") or text).strip()
        own = {c["cue"]: c for c in cues}
        if kind == "red-strip" and _WARN.search(text):
            cue = "warning"
        if cue in ("headline", "key-phrase"):
            short = _clause(said, 8, 60) or _clause(text, 8, 60)
            phrase = str(hint.get("highlight") or "").strip()
            if not (phrase and len(_words(phrase)) <= 5):
                phrase = _key_phrase(text, shot)
            if cue == "key-phrase" and not phrase and short:
                cue = "headline"
            elif cue == "headline" and not short and phrase:
                cue = "key-phrase"
            if cue == "headline" and short:
                p = {"text": short, **({"highlight": phrase} if phrase else {})}
            elif cue == "key-phrase" and phrase:
                p = {"text": phrase, "_key": phrase.split()[0]}
            else:
                return None
        elif cue == "warning":
            p = dict(own["warning"]["props"]) if "warning" in own else {"text": _clause(said, 6, 40).upper()}
            if not p.get("text"):
                return None
        elif cue == "quote":
            if "quote" in own:
                p = dict(own["quote"]["props"])
            else:
                quoted = said if len(said) <= 140 else said[:140].rsplit(" ", 1)[0]
                p = {"text": quoted, "label": _subject_words(shot, seg)}
        elif cue == "typewriter":
            typed = _clause(said, 12, 64) or _clause(text, 12, 64)
            if not typed:
                typed = said[:64].rsplit(" ", 1)[0] if len(said) > 64 else said
            p = {"text": typed}
        else:
            p = {k: v for k, v in props.items() if k != "_motion"}
        if props.get("_motion"):
            p["_motion"] = props["_motion"]
        return {"cues": [cue] + CUE_FALLBACK.get(cue, []), "props": p, "group": "text",
                "emphasis": "medium", "mode": "normal"}

    def _photo(self, i: int, seg, shot: dict, scene: dict) -> Optional[dict]:
        """A photo animation for a still, by what it shows, rotating over every photo look."""
        subject = (shot.get("subject") or "").strip()
        kind = (shot.get("subjectType") or "").lower()
        if kind == "person" and subject and _is_org_or_place(subject):
            kind = "place"                  # an agency or a place filed as a person: never a person card
        if kind == "person" and subject:
            own = ["photo-person", "person"]
        elif kind in ("place", "location", "landmark") and subject:
            own = ["photo-place", "place-photo"]
        elif kind in ("object", "document", "thing", "artifact") and subject:
            own = ["photo-object", "object-photo"]
        else:
            own = []
        many = self._stills_after(i) >= 3
        pool, specific = [], []
        for c in own + ["photo"]:
            for t in templates.for_cue(c, self.style):
                tags = set(t.get("tags") or [])
                if t["id"] in ("PHOTO_PIP_V1", "PHOTO_COLLAGE_V1") or t.get("category") in ("QUOTES", "DOCUMENTS"):
                    continue
                if not (t.get("component") in ("photo-card", "name-card") or "still" in tags or "stills" in tags):
                    continue
                if "stills" in tags and not many:
                    continue
                if t["id"] in {x["id"] for x in pool}:
                    continue
                pool.append(t)
                if c in own:
                    specific.append(t["id"])
        if not pool:
            return None
        props = {"text": subject.upper()} if subject and not own else ({"text": subject} if subject else {})
        by_id = {}
        hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else {}
        if hint.get("type") == "map" and hint.get("locations"):
            by_id["PLACE_CARD_V1"] = {**props, "locations": hint["locations"][:1]}
        req = {"ids": [t["id"] for t in pool], "prefer": specific, "props": props, "props_by_id": by_id,
               "mode": "director", "group": "photo", "emphasis": "medium", "never_again": True}
        return self._request(req, seg, scene, "director")

    def _stills_after(self, i: int) -> int:
        """How many still pictures the next scenes have (for the multi-photo looks)."""
        return sum(1 for sc in self.scenes[i + 1:i + 7] if (sc.get("media") or {}).get("type") == "image"
                   and (sc.get("media") or {}).get("url"))

    # ------------------------------------------------------------ candidates
    def _pool(self, cue: str, text: str, scene: dict) -> List[dict]:
        """Every look that carries the cue and fits this line and this scene."""
        pool = date_looks(cue, self.style) if cue in DATE_CUES else templates.for_cue(cue, self.style)
        pool = [t for t in pool if look_fits(t["id"], text) and t.get("kind") != "map"]
        if cue == "typewriter":
            pool = [t for t in pool if templates.types(t)]
        if cue in TEXT_CUES and cue not in DATE_CUES and cue != "chapter":
            # Words ride on the clip, never on a card that covers it.
            pool = [t for t in pool if "own-backdrop" not in (t.get("tags") or [])]
        elif cue in SINGLE_FIGURE_CUES:
            pool = [t for t in pool if "own-backdrop" not in (t.get("tags") or [])] or pool
        elif cue in FULL_DATA_CUES:
            pool = [t for t in pool if t.get("kind") != "tag"] or pool
        media = scene.get("media") or {}
        if not (media.get("url") and media.get("type") in ("image", "video")):
            # No picture and no clip to take a frame from: no look that shows one.
            pool = [t for t in pool if not ({"still", "stills"} & set(t.get("tags") or []))]
        elif any("stills" in (t.get("tags") or []) for t in pool) and self._stills_after(self.i) < 3:
            pool = [t for t in pool if "stills" not in (t.get("tags") or [])]
        return pool

    def _candidates(self, req: dict, seg, scene: dict, mode: str):
        """(template, cue, props) in the order to try them."""
        at = float(seg.start)
        text = seg.text or ""
        group = req.get("group", "")
        text_beat = group == "text" or group == "filler"
        prefer = set(req.get("prefer") or ())
        by_cue = req.get("props_by_cue") or {}
        by_id = req.get("props_by_id") or {}
        stages = []
        if req.get("ids"):
            pool = [templates.get(x) for x in req["ids"]]
            stages.append(([t for t in pool if t and look_fits(t["id"], text)], req.get("cue", ""), req["props"]))
        for cue in req.get("cues") or []:
            stages.append((self._pool(cue, text, scene), cue, by_cue.get(cue, req["props"])))
        if req.get("merge") and len(stages) > 1:
            merged, owner = [], {}
            for pool, cue, props in stages:
                for t in pool:
                    if t["id"] not in owner:
                        owner[t["id"]] = (cue, props)
                        merged.append(t)
            stages = [(merged, None, owner)]
        last = self.looks.last_in.get(group) if req.get("never_again") else None
        lead = req.get("lead")
        if not lead and "age" in ([req.get("cue")] + list(req.get("cues") or [])):
            lead = lead_look(BOLD_COUNT_LOOK)       # an age is a bold count too ("87 YEARS OLD")
        if lead and lead != last:
            # The look this cue always tries first, however recently it was shown.
            t = templates.get(lead)
            if t and look_fits(lead, text) and not _needs_places(t, by_id.get(lead, req["props"])):
                cue0 = req.get("cue") or ((req.get("cues") or [""])[0])
                yield t, cue0, dict(by_id.get(lead, by_cue.get(cue0, req["props"])))
        asked_demote = set(req.get("demote") or ())
        demote = set(asked_demote)
        stale_all = []
        first = req.get("first")
        if first and first != last and self.looks.fresh(first, at):
            t = templates.get(first)
            if t and look_fits(first, text):
                yield t, req.get("cue", ""), dict(by_id.get(first, req["props"]))
        over_footage = (scene.get("media") or {}).get("type") in ("video", "image")
        for pool, cue, props in stages:
            stage_prefer = prefer
            if cue in FIGURE_CUES:
                # The persisting looks hold 6-12 s: only when nothing else is left.
                demote = asked_demote | {t["id"] for t in pool if is_persist_look(t)}
            if cue in SINGLE_FIGURE_CUES and over_footage:
                # One figure over footage: the compact corner looks first (tags ride on the clip).
                stage_prefer = set(prefer) | {t["id"] for t in pool if t.get("kind") == "tag"}
            fresh, stale = self.looks.order(pool, at, prefer=stage_prefer, demote=demote,
                                            text_beat=text_beat or cue in TEXT_BEAT_CUES)
            for t in fresh:
                if t["id"] == last:
                    continue
                c, p = (props[t["id"]] if cue is None else (cue, props))
                yield t, c, dict(by_id.get(t["id"], p))
            for t in stale:
                c, p = (props[t["id"]] if cue is None else (cue, props))
                stale_all.append((t, c, dict(by_id.get(t["id"], p))))
        if req.get("stale_ok", mode in ("must", "director", "seq")):
            for t, c, p in stale_all:
                if t["id"] == last or t["id"] == self.looks.last_in.get(group):
                    continue
                if group == "photo" and self.looks.recent(t["id"], at, PHOTO_WINDOW) >= PHOTO_MAX:
                    continue
                yield t, c, p

    def _request(self, req: Optional[dict], seg, scene: dict, mode: str) -> Optional[dict]:
        if not req:
            return None
        tried = set()
        for t, cue, props in self._candidates(req, seg, scene, mode):
            # (The VidRush date looks carry generic cues - "caption", "date" - but only
            # the date pass, _vr_request, may place them.)
            if t["id"] in tried or not auto_ok(t["id"]) or (t["id"] in VR_LOOKS and not req.get("vr")):
                continue
            tried.add(t["id"])
            got = self._place(t, cue, props, req, seg, scene, mode)
            if got:
                return got
            if len(tried) >= 16:
                break
        return None

    # --------------------------------------------------------------- placing
    def _place(self, t: dict, cue: str, props: dict, req: dict, seg, scene: dict, mode: str) -> Optional[dict]:
        """Lay one look on the timeline on its word, or say why not (None)."""
        fps = self.fps
        at = float(seg.start)
        props = dict(props or {})
        if t["id"] in TEXT_LOOK_ALIGNS or (cue or "") in DIGIT_CUES or t.get("category") in ("TIMELINES", "NUMBERS"):
            # A date, a time or a number shows its numbers in digits, however the script spelled
            # them out ("five days" -> "5 DAYS", "September twenty-ninth" -> "SEPTEMBER 29"; the
            # owner, 2026-10-01). The spoken word that times it (_key) stays as said.
            for k in ("text", "label", "subtitle"):
                if isinstance(props.get(k), str) and props[k]:
                    props[k] = numwords.normalize(props[k])
        if _needs_places(t, props):
            return None
        motion = props.pop("_motion", "")
        key = props.pop("_key", "")
        resolved = templates.resolve(t["id"], style=self.style, entrance=motion, props=props, pack=self.pack)
        if not resolved:
            return None
        klass = req.get("layout") or layout_class(t, cue or "")
        if klass == "persist" and at < self.persist_until:
            return None
        lo, hi = layout_window(t, klass)
        least = max(1.0, animation_seconds(t))
        # A must-show graphic may cut this one short only after it has played its own animation.
        keep = max(MIN_VISIBLE.get(klass, 1.6), least)
        if templates.types(t):
            # The typing contract: from frame TYPE_START, one letter every 2
            # frames (1 past 48 letters), then a beat to read it. A typed line
            # is never cut short before its last letter.
            n = len(str(props.get("text") or ""))
            typed = (TYPE_START + (2 if n <= 48 else 1) * n) / 30.0     # contract frames are at 30 fps
            lo = max(lo, typed + TYPE_HOLD)
            hi = max(hi, lo)
            keep = max(keep, typed + 0.3)
            least = max(least, typed + 0.3)
        until = None
        if klass == "map" or (klass == "full" and t.get("category") in ("CHARTS", "COMPARISONS", "TIMELINES")):
            # A map or a chart may stay to TALKING_MAX, but only while the
            # narration is still on it: the next line names the same place or subject.
            until = self._still_about(seg, props)
            if until is not None:
                hi = max(hi, TALKING_MAX)
        wprops = dict(props, _key=key) if key else props
        t_in, t_out = _voice_window(seg, wprops, lo, hi, fps, until)
        if any(a <= t_in < b for a, b in self.blocks):
            return None                    # a full-screen graphic is on screen: nothing lands on it
        if t["id"] in VR_LOOKS and not _vr_fits({"at": t_in, "look": t["id"]}, self.vr_placed):
            return None                    # one date or time graphic per VR_GAP, on screen (it may only slide later)
        prev = max(self.spans, key=lambda s: s["end"]) if self.spans else None
        busy = prev is not None and prev["end"] + BREATH > t_in
        if mode == "normal":
            if busy or not self.rhythm.allows(t_in, t, cue or ""):
                return None
        elif busy:
            cut = t_in - BREATH
            trim_ok = (mode == "must" and prev["idx"] is not None
                       and cut - prev["start"] >= prev.get("keep", MIN_VISIBLE.get(prev["klass"], 1.6)))
            slide_to = prev["end"] + BREATH
            if trim_ok:
                # On its word: the graphic still up has been read, it gives way
                # (only when this one really lands - nothing is cut for nothing).
                if min(t_out, self._clear_until(t_in)) - t_in < least:
                    return None
                self._trim(prev, cut)
            elif slide_to - t_in <= SLIDE_SLACK and slide_to * fps < self.total - 1:
                # A moment late at most - never seconds after its word.
                t_out = slide_to + max(lo, min(t_out - slide_to, hi))
                t_in = slide_to
            else:
                return None
        elif mode == "director" and t.get("kind") in CARD_KINDS and self.rhythm.overlaps(t_in):
            return None
        # Never into a full-screen scene or a span already taken ahead (the job's title card).
        t_out = min(t_out, self._clear_until(t_in))
        if t_out - t_in < least:
            return None
        o_start = max(0, min(int(round(t_in * fps)), self.total - 1))
        frames = max(1, min(int(round((t_out - t_in) * fps)), self.total - o_start))
        sfx = resolved.pop("sfx", {"name": "none", "volume": 0.0})
        overlay = {**resolved, "startFrame": o_start, "durationInFrames": frames}
        overlay.pop("seconds", None)
        if t["id"] in VR_LOOKS:
            # One theme for every date and time look of the video, whatever the pack's colour.
            overlay["theme"] = self.vr_theme
            self.vr_placed.append({"at": o_start / fps, "look": t["id"]})
        apply_layout(overlay, t, klass)
        if t["id"] in TEXT_LOOK_ALIGNS and overlay.get("align") in (None, "auto"):
            overlay["align"] = self._align_for(t["id"], scene)
        if t["id"] in TEXT_LOOK_ALIGNS and overlay.get("textStyle") in (None, "auto"):
            overlay["textStyle"] = TEXT_LOOK_STYLES[self.style_turn % len(TEXT_LOOK_STYLES)]
            self.style_turn += 1
        if t.get("category") in _TEXT_CATEGORIES and "fontScale" not in overlay:
            overlay["fontScale"] = 1.0 if t.get("kind") == "tag" else TEXT_FONT_SCALE
        media = req.get("media") or (req.get("media_for") or {}).get(t["id"])
        if media:
            overlay["media"] = [media]
        idx = len(self.overlays)
        self.overlays.append(overlay)
        tr_idx = len(self.treatments)
        if klass in _PERSIST_CLASSES:
            self.persisting.append((idx, tr_idx, klass))
        if klass == "persist":
            self.persist_until = max(self.persist_until, (o_start + frames) / fps)
        if klass in _FULLSCREEN_CLASSES:
            self.covered.append((o_start, o_start + frames))
        self.spans.append({"start": o_start / fps, "end": (o_start + frames) / fps, "idx": idx, "klass": klass,
                           "must": mode == "must", "tr": tr_idx, "keep": keep})
        text_beat = (cue or "") in TEXT_BEAT_CUES or req.get("group") in ("text", "filler")
        self.rhythm.note(o_start / fps, t, frames / fps, cue if text_beat else "")
        if text_beat:
            self.rhythm.last_text = max(self.rhythm.last_text, (o_start + frames) / fps)
        group = req.get("group", "")
        # Remembered at the moment it is on screen (a slid graphic lands after its
        # line starts), so "not within LOOK_GAP" holds on screen, not just on paper.
        self.looks.use(t, o_start / fps, group, text_beat=text_beat)
        if group == "map":
            self.n_maps += 1
        if cue == "person-full":
            self.last_person_full = o_start / fps
        if cue in ("key-phrase", "caption") and props.get("text"):
            self.phrases[str(props["text"]).upper()] = at
        if req.get("figure_key") is not None or (cue or "") in BOLD_COUNT_CUES:
            self.figure_looks.append(t["id"])      # every figure shown: the bold count's run is counted over them
        if req.get("figure_key"):
            self.seen_figures[req["figure_key"]] = at
            if self.density == "minimal":
                # A news compilation's one figure per MINIMAL_FIGURE_GAP, from
                # the figure that showed (not one that was only tried).
                self.last_min_figure = at
        return {"idx": idx, "t": t, "cue": cue or "", "sfx": sfx, "klass": klass,
                "emphasis": req.get("emphasis") or t["emphasis"]}

    def _align_for(self, tid: str, scene: dict) -> str:
        """The next placement of a text-only look (TEXT_LOOK_ALIGNS), never the centre on a person's shot."""
        turn = TEXT_LOOK_ALIGNS[tid]
        shot = self.shots[self.i] if 0 <= self.i < len(self.shots) else {}
        person = (shot or {}).get("subjectType") == "person" or bool((shot or {}).get("mention")) \
            or "person" in str(((scene or {}).get("semanticMetadata") or {}).get("intent") or "").lower()
        n = self.align_turn.get(tid, 0)
        for k in range(len(turn)):
            pick = turn[(n + k) % len(turn)]
            if not (person and pick == "center"):
                self.align_turn[tid] = n + k + 1
                return pick
        return turn[0]

    def _still_about(self, seg, props: dict) -> Optional[float]:
        """
        When the next line, said straight after this one, still names a map's
        place or a chart's subject: the time that line ends plus TAIL; else None.
        """
        nxt = self.segments[self.i + 1] if 0 <= self.i + 1 < len(self.segments) else None
        if nxt is None or float(nxt.start) - float(seg.end) > 0.6:
            return None
        names = [str(loc.get("label") or "").split(",")[0] for loc in (props.get("locations") or [])
                 if isinstance(loc, dict)] + [str(props.get("text") or "")]
        about = {w.lower() for n in names for w in re.findall(r"[A-Za-z][\w'-]{3,}", n)} - _NOT_A_LABEL
        said = {w.lower() for w in re.findall(r"[A-Za-z][\w'-]{3,}", getattr(nxt, "text", "") or "")}
        return float(nxt.end) + TAIL if about & said else None

    def _clear_until(self, t_in: float) -> float:
        """Where the screen stops being free after t_in: the next full-screen scene or span already taken."""
        ahead = [a for a, _b in self.blocks if a > t_in + 1e-6] + \
            [s["start"] for s in self.spans if s["start"] > t_in + 1e-6]
        return min(ahead) if ahead else float("inf")

    def _trim(self, span: dict, cut: float) -> None:
        """Cut an overlay short so a must-show graphic can land on its word."""
        ov = self.overlays[span["idx"]]
        frames = max(1, int(round(cut * self.fps)) - int(ov["startFrame"]))
        if frames >= int(ov["durationInFrames"]):
            return
        old_end = int(ov["startFrame"]) + int(ov["durationInFrames"])
        ov["durationInFrames"] = frames
        new_end = int(ov["startFrame"]) + frames
        span["end"] = new_end / self.fps
        self.covered = [(a, new_end) if (a, b) == (int(ov["startFrame"]), old_end) else (a, b) for a, b in self.covered]
        if span.get("tr") is not None and span["tr"] < len(self.treatments):
            entry = self.treatments[span["tr"]]
            if entry.get("overlays") and entry["overlays"][0] == ov.get("template"):
                entry["duration"] = round(frames / self.fps, 2)

    def _entry(self, scene: dict, placed: List[dict], i: int) -> dict:
        media_type = (scene.get("media") or {}).get("type")
        first = placed[0] if placed else None
        chosen = first["t"] if first else None
        entry = {
            "primaryType": ("image" if media_type == "image" else "footage" if media_type == "video" else "empty"),
            "secondaryType": chosen["category"].lower() if chosen else None,
            "template": chosen["id"] if chosen else None, "variant": None, "entrance": None, "exit": None,
            "duration": None, "emphasis": first["emphasis"] if first else "low", "animation": None,
            "data": {}, "text": "", "mapData": None, "chartData": None, "overlays": [],
            "transitionIn": scene.get("transition", "none"), "transitionOut": "none", "sfx": None, "musicCue": None,
        }
        if first:
            overlay = self.overlays[first["idx"]]
            sfx = first["sfx"] or {}
            entry.update({
                "variant": overlay.get("variant") or overlay.get("style"), "entrance": overlay.get("motion"),
                "exit": overlay.get("exit"), "duration": round(overlay["durationInFrames"] / self.fps, 2),
                "animation": overlay.get("motion"),
                "text": str(overlay.get("text") or ""), "overlays": [p["t"]["id"] for p in placed],
                "data": {k: overlay[k] for k in ("value", "suffix", "items") if k in overlay},
                "mapData": {"locations": overlay.get("locations")} if overlay.get("locations") else None,
                "chartData": ({"items": overlay.get("items")} if overlay.get("items")
                              and chosen["category"] in ("CHARTS", "COMPARISONS", "TIMELINES") else None),
                "sfx": (sfx if sfx.get("name") not in (None, "none") else None),
            })
            if i in self.hooks:
                entry["emphasis"] = "high"
        return entry


# A figure rides across a cut only while the voice runs straight on: a pause
# longer than this between two lines is the voice moving on (the owner,
# 2026-09-30: "no look lingers after the voice has moved on").
PERSIST_PAUSE = 0.25


def _persist_figures(overlays: List[dict], treatments: List[dict], persisting: List[tuple], covered: List[tuple],
                     scenes: List[dict], fps: int, total: int, segments: Optional[List[Segment]] = None) -> None:
    """
    GoMotion's persistent figure: a compact ring or number on the clip stays
    up across the short cuts that follow it ("22% OF CAPACITY REMAINING" rode
    three consecutive shots) instead of leaving with its own sentence.

    After its voice-synced window is set, a figure-class overlay is extended
    to the end of each following scene while (a) that scene is shorter than
    PERSIST_SCENE_MAX, (b) the whole run stays within PERSIST_MAX_SECONDS of
    the overlay's start, (c) no other overlay starts inside the extended span,
    (d) the scene is not an animation scene and no full-screen graphic covers
    it, and (e) the narration runs on into that scene's line without a pause
    longer than PERSIST_PAUSE (`segments`, one per scene). Off with
    PERSIST_FIGURES=0 (the overlays are left as planned).
    """
    if not config.PERSIST_FIGURES or not persisting or not scenes:
        return
    scene_max = float(config.PERSIST_SCENE_MAX) * fps
    run_max = float(config.PERSIST_MAX_SECONDS) * fps
    starts = sorted((ov["startFrame"], j) for j, ov in enumerate(overlays))
    for idx, tr_idx, _klass in persisting:
        ov = overlays[idx]
        o_start = int(ov["startFrame"])
        o_end = o_start + int(ov["durationInFrames"])
        home = next((s for s, sc in enumerate(scenes)
                     if sc.get("startFrame", 0) <= o_start < sc.get("startFrame", 0) + sc.get("durationInFrames", 0)), None)
        if home is None:
            continue
        new_end = o_end
        for k in range(home + 1, len(scenes)):
            sc = scenes[k]
            sc_start = int(sc.get("startFrame", 0))
            sc_end = sc_start + int(sc.get("durationInFrames", 0))
            if sc_end <= new_end:
                continue
            if segments is not None and 0 < k < len(segments) \
                    and float(segments[k].start) - float(segments[k - 1].end) > PERSIST_PAUSE:
                break                                                # (e) the voice paused: it moved on
            if segments is not None and k >= len(segments):
                break
            if sc_end - sc_start >= scene_max:                       # (a) a long shot: the figure leaves
                break
            if sc_end - o_start > run_max + 1e-6:                    # (b) the run is long enough
                break
            if (sc.get("media") or {}).get("type") == "animation":   # (d) the beat IS a graphic
                break
            if any(a < sc_end and b > sc_start for a, b in covered):  # (d) a full-screen graphic covers it
                break
            if any(o_start < s < sc_end for s, j in starts if j != idx):  # (c) another graphic starts in the span
                break
            new_end = sc_end
        new_end = min(new_end, total)
        if new_end > o_end:
            ov["durationInFrames"] = new_end - o_start
            if 0 <= tr_idx < len(treatments):
                treatments[tr_idx]["duration"] = round((new_end - o_start) / fps, 2)


def _plan_sfx(overlays: List[dict], treatments: List[dict], fps: int, intensity: float,
              voice_lufs: Optional[float] = None) -> List[dict]:
    """One sound per graphic moment at most every SFX_GAP seconds, the strongest moment winning,
    at the same voice-relative level and under the same cap as the sound pass (src/sfxplan.py)."""
    from . import sfxplan
    rank = {"high": 0, "medium": 1, "low": 2}
    picks: List[dict] = []
    by_start = sorted((ov for ov in overlays), key=lambda o: o["startFrame"])
    emph = {}
    for tr in treatments:
        if tr.get("template"):
            emph.setdefault(tr["template"], tr["emphasis"])
    last = -1e9
    for ov in by_start:
        t = templates.get(ov.get("template") or "")
        if not t:
            continue
        s = t["defaults"].get("sfx") or {}
        if not s.get("name") or s["name"] == "none":
            continue
        at = ov["startFrame"] / fps
        e = emph.get(ov.get("template"), t["emphasis"])
        if at - last < SFX_GAP:
            if picks and rank.get(e, 9) < rank.get(picks[-1]["_e"], 9):
                picks.pop()
            else:
                continue
        level = sfxplan.level(s["name"], voice_lufs) * max(0.0, float(intensity))
        picks.append({"name": s["name"], "startFrame": int(ov["startFrame"]),
                      "volume": round(min(sfxplan.cap(voice_lufs), level), 3), "_e": e})
        last = at
    for p in picks:
        p.pop("_e", None)
    return picks


def _plan_music(segments: List[Segment], brief: Optional[dict], fps: int, total: int, hooks: set) -> dict:
    """Sections with a mood and a level; the renderer ramps the music between them and keeps it under the voice."""
    moods = templates.load()["musicMoods"]
    sections = list((brief or {}).get("sections") or [])
    kind = (brief or {}).get("kind") or ""
    tense = kind in ("news", "weather", "disaster")
    out = []
    if not segments:
        return {"sections": [], "duck": 0.55}
    if not sections:
        n = len(segments)
        cuts = [0, max(1, n // 4), max(2, n // 2), max(3, (3 * n) // 4), n]
        sections = [{"from": cuts[k], "to": cuts[k + 1] - 1} for k in range(4) if cuts[k] < cuts[k + 1]]
    sections = [s for s in sections if isinstance(s, dict) and all(
        isinstance(s.get(k, 0), (int, float)) and not isinstance(s.get(k, 0), bool) for k in ("from", "to"))] or \
        [{"from": 0, "to": len(segments) - 1}]
    for k, sec in enumerate(sections):
        a, b = int(sec.get("from", 0)), int(sec.get("to", len(segments) - 1))
        a, b = max(0, min(a, len(segments) - 1)), max(0, min(b, len(segments) - 1))
        if k == 0:
            mood = "INTRO"
        elif k == len(sections) - 1:
            mood = "OUTRO" if len(sections) > 2 else "RESOLUTION"
        elif tense:
            mood = ("TENSION", "BUILD", "REVELATION")[k % 3]
        else:
            mood = ("EXPLANATION", "BUILD", "EMOTIONAL")[k % 3]
        start = int(round(segments[a].start * fps))
        end = int(round(segments[b].end * fps)) if b < len(segments) else total
        if k == len(sections) - 1:
            end = total
        out.append({"startFrame": start, "endFrame": max(start + 1, end), "mood": mood,
                    "volume": moods.get(mood, 0.12)})
    for i in sorted(hooks):
        if 0 <= i < len(segments):
            for s in out:
                if s["startFrame"] <= int(segments[i].start * fps) < s["endFrame"] and s["mood"] == "INTRO":
                    s["volume"] = max(s["volume"], moods.get("REVELATION", 0.15))
    return {"sections": out, "duck": 0.55}


FULLSCREEN_CUES = {"then-now", "compare-values", "ranking", "series", "shares", "money-compare"}

# ------------------------------------------------ overlay layout (the owner, 2026-09-28 evening)
# The clip keeps its slot and the graphic rides on top of it. One figure is a
# compact overlay in a corner; several values (or a timeline) are full screen
# for their moment on a blurred still of that clip; maps draw their own frame;
# text rides on the picture. Each class has its own time on screen.
# (SINGLE_FIGURE_CUES, FULL_DATA_CUES, TEXT_CUES and LAYOUT_WINDOWS are at the top of the module.)
COMPACT_SCALE = 0.55
_CORNERS = ["bottom-left", "bottom-right"]
_corner_turn = [0]
# Built-in tags that draw themselves in the middle of the frame (the ring):
# over footage they are made compact in a corner like a figure card.
_CENTRED_TAGS = {"ring-stat"}
# Layout classes that cover the clip (a persisting figure never runs under them).
_FULLSCREEN_CLASSES = {"full", "cutaway", "map", "person"}
# Layout classes whose overlay may persist across the short cuts that follow it.
_PERSIST_CLASSES = {"figure", "persist"}


def is_persist_look(template: dict) -> bool:
    """A LibPersist look ("ps-..."): registered as LIB_PS_* with the look id as its variant."""
    variant = str((template.get("defaults") or {}).get("variant") or "")
    return variant.startswith("ps-") or str(template.get("id") or "").startswith("LIB_PS_")


def layout_class(template: dict, cue: str = "") -> str:
    """figure | full | map | cutaway | text | persist: how a chosen template sits on its clip."""
    tags = template.get("tags") or []
    if is_persist_look(template):
        return "persist"
    if template.get("kind") == "map" or template.get("component") == "map":
        return "map"
    if "own-backdrop" in tags:
        return "cutaway"
    if cue in SINGLE_FIGURE_CUES:
        return "figure"
    if cue in FULL_DATA_CUES:
        return "full"
    if not cue:
        if template.get("category") == "NUMBERS":
            return "figure"
        if template.get("category") in ("CHARTS", "COMPARISONS", "TIMELINES"):
            return "full"
    return "text"


def apply_layout(overlay: dict, template: dict, klass: str) -> None:
    """Mark a planned overlay compact (one figure on the clip) or full screen (several values)."""
    if klass == "persist" or (template.get("kind") == "tag" and template.get("component") not in _CENTRED_TAGS):
        # A tag or a persisting look places and sizes itself: no scrim, no compact scaling.
        return
    if klass == "figure":
        overlay["compact"] = True
        overlay["position"] = _CORNERS[_corner_turn[0] % len(_CORNERS)]
        _corner_turn[0] += 1
        overlay["scale"] = COMPACT_SCALE
    elif klass == "full":
        overlay["backdrop"] = "blur"

_PHOTO_CYCLE = ["PHOTO_CARD_V1", "PHOTO_GRID_V1", "PHOTO_WINDOW_V1", "PHOTO_STACK_V1", "PHOTO_BOARD_V1",
                "PHOTO_EVIDENCE_V1"]
_PERSON_CYCLE = ["PERSON_CARD_V1", "PHOTO_BOARD_V1"]
_PLACE_CYCLE = ["PLACE_CARD_V1", "PHOTO_WINDOW_V1"]
_OBJECT_CYCLE = ["OBJECT_CARD_V1", "PHOTO_BOARD_V1", "PHOTO_EVIDENCE_V1"]
_photo_turn = [0]
_kind_turn = {"person": [0], "place": [0], "object": [0], "photo": [0]}


def _lib_looks(cue: str, still: bool = True) -> List[str]:
    """Library looks (component "motion") registered for a cue; `still`: only those that show one picture."""
    return [t["id"] for t in templates.for_cue(cue)
            if t.get("component") == "motion" and (not still or "still" in (t.get("tags") or []))]


def _turn(kind: str, cycle: List[str]) -> str:
    cue = {"person": "person", "place": "place-photo", "object": "object-photo"}.get(kind, "photo")
    cycle = list(cycle) + [t for t in _lib_looks(cue) if t not in cycle]
    n = _kind_turn[kind]
    tid = cycle[n[0] % len(cycle)]
    n[0] += 1
    return tid


def photo_template(shot: dict) -> tuple:
    """(template id, props) for a photo beat: a person card for a named person,
    a place card for a place, an object spotlight for a thing or a document,
    otherwise a framed photo (the three generic looks take turns)."""
    subject = (shot.get("subject") or "").strip()
    kind = (shot.get("subjectType") or "").lower()
    hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else {}
    if kind == "person" and subject and not _is_org_or_place(subject):
        return _turn("person", _PERSON_CYCLE), {"text": subject}
    if kind in ("place", "location", "landmark") and subject:
        tid = _turn("place", _PLACE_CYCLE)
        locs = hint.get("locations") if hint.get("type") == "map" else None
        if tid == "PLACE_CARD_V1" and locs:
            return tid, {"text": subject, "locations": locs[:1]}
        return tid, {"text": subject}
    if kind in ("object", "document", "thing", "artifact") and subject:
        return _turn("object", _OBJECT_CYCLE), {"text": subject}
    tid = _turn("photo", _PHOTO_CYCLE)
    return tid, ({"text": subject.upper()} if subject else {})
_WEAK_REASONS = ("Best available", "Reused shot", "Repeat of an earlier shot", "No usable clip",
                 "No footage found")


DATA_CATEGORIES = {"CHARTS", "COMPARISONS", "TIMELINES", "MAPS", "DOCUMENTS"}


def _trigger_key(props: dict) -> str:
    """The word a graphic is triggered by: the cue's own word ("Sept.", "twenty-two", "Udall"), the
    figure's digits, else the first word of its text."""
    if not isinstance(props, dict):
        return ""
    if props.get("_key"):
        return str(props["_key"])
    v = props.get("value")
    if v is not None:
        try:
            return str(int(float(v))) if float(v).is_integer() else str(v)
        except (TypeError, ValueError):
            return ""
    first = str(props.get("text") or "").split()[:1]
    return first[0] if first and len(first[0]) >= 3 else ""


def _word_time(seg, props: dict) -> Optional[float]:
    """When the word that triggers a graphic is said (seconds), or None when the line has no word timings."""
    words = list(getattr(seg, "words", None) or [])
    key = _trigger_key(props)
    if not key or not words:
        return None

    def attr(w, name):
        return w.get(name) if isinstance(w, dict) else getattr(w, name, None)

    norm = lambda w: re.sub(r"[^0-9a-z.]", "", str(w).lower())
    target = norm(key)
    for w in words:
        wt = norm(attr(w, "text") or "")
        if target and (wt == target or wt.startswith(target) or (len(target) > 2 and target in wt)):
            ws = attr(w, "start")
            if ws is not None:
                return float(ws)
    # Not spelled the same in the transcript ("22" vs "twenty-two"): the word
    # standing where the key stands in the line.
    at = _offset(getattr(seg, "text", "") or "", key)
    n = len(re.findall(r"\S+", (getattr(seg, "text", "") or "")[:at])) if at > 0 else 0
    if 0 < n < len(words) and attr(words[n], "start") is not None:
        return float(attr(words[n], "start"))
    return None


def _voice_window(seg, props: dict, lo: float, hi: float, fps: int = 30, until: Optional[float] = None) -> tuple:
    """
    (in, out) seconds for a graphic on this line: in on the word that
    triggers it (at most PRE_ROLL_FRAMES early, never before the line; the
    line's start when there are no word timings), out when the phrase ends
    plus TAIL (or `until`, while the narration keeps talking about it), and
    on screen at least `lo` and at most `hi` seconds.
    """
    start = float(seg.start)
    said = _word_time(seg, props)
    t_in = start if said is None else max(start, said - PRE_ROLL_FRAMES / float(fps or 30))
    t_out = float(until) if until is not None else float(seg.end) + TAIL
    dur = max(lo, min(t_out - t_in, max(hi, lo)))
    return t_in, t_in + dur


def animation_seconds(template: dict) -> float:
    """
    The least time a look needs on screen: its entrance up to its visual hit
    (the registry's sfxAt, else ENTRANCE_FRAMES), SETTLE seconds landed, and
    its exit (EXIT_FRAMES), all at 30 fps.
    """
    d = (template or {}).get("defaults") or {}
    try:
        hit = float(d.get("sfxAt")) if d.get("sfxAt") is not None else float(ENTRANCE_FRAMES)
    except (TypeError, ValueError):
        hit = float(ENTRANCE_FRAMES)
    return (max(0.0, hit) + EXIT_FRAMES) / 30.0 + SETTLE


def layout_window(template: dict, klass: str) -> tuple:
    """(min, max) seconds on screen for a look in a layout class (LAYOUT_WINDOWS), never under its own animation."""
    lo, hi = LAYOUT_WINDOWS[klass]
    if klass == "text" and template.get("kind") == "card":
        lo, hi = LAYOUT_WINDOWS["full"]          # a card of words is a card: 2.5-5 s
    lo = max(lo, animation_seconds(template))
    return lo, max(hi, lo)


def _figure_key(cue: dict) -> Optional[tuple]:
    """The figure a cue draws, for repeat checks: ("figure", 26.0), a span of time ("span", 48.0)."""
    v = (cue.get("props") or {}).get("value")
    if cue.get("cue") in ("percent", "change", "change-length", "big-number", "money", "measurement", "ratio",
                          "count", "time-span") and v is not None:
        try:
            return ("span" if cue.get("cue") == "time-span" else "figure", float(v))
        except (TypeError, ValueError):
            return None
    return None


def _figure_words(sentence: str, cue: dict) -> str:
    """The words of the sentence that carry the figure, for the highlight."""
    v = (cue.get("props") or {}).get("value")
    if v is None:
        return ""
    num = str(int(v)) if float(v).is_integer() else str(v)
    m = re.search(re.escape(num) + r"[\d,.]*\s*(?:%|percent|feet|ft|million|billion|dollars)?", sentence, re.I)
    return m.group(0).strip() if m else num


def wants_animation(seg, shot: dict, asset, brief: Optional[dict], seen: Optional[dict] = None) -> bool:
    """
    Should this beat be a full-screen animation scene instead of footage?

    - No footage at all: yes.
    - A chart moment (then vs now, a comparison, a ranking, a series of
      values): yes, whatever the footage - VidRush shows graphs full screen.
    - A strong cue (a figure, a date, a mapped place, a quote, a chapter)
      over WEAK footage: yes. Weak means the vision judge scored it under
      ANIMATION_OVER_FOOTAGE_BELOW, or it is a borrowed, repeated or
      best-available shot. The licence flag every web clip carries is not
      weakness: treating it as such swapped good matching footage for cards.
    - Otherwise the footage stays and the planner puts the graphic on it.
    """
    if not config.ANIMATION_FILL:
        return False
    cues = cues_for(seg, shot, brief)
    hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else None
    mapped = bool(hint and hint.get("type") == "map" and (hint.get("locations") or hint.get("places")))
    if seen is not None and not mapped:
        # A figure already shown full screen in the last REPEAT_GAP seconds
        # is not shown full screen again.
        fresh = []
        for c in cues:
            key = _figure_key(c)
            if key and seg.start - seen.get(key, -1e9) < REPEAT_GAP:
                continue
            fresh.append(c)
        cues = fresh
    if not mapped and not any(c["cue"] in SCENE_CUES for c in cues):
        return False
    if asset is None:
        return True
    # The owner (2026-09-28): fill the clip and put the graphic on top of it.
    # A beat that has footage keeps it; the planner lays the number, chart or
    # map over the clip for its moment (layout_class / apply_layout).
    if not config.ANIMATION_OVER_FOOTAGE:
        return False
    if any(c["cue"] in FULLSCREEN_CUES for c in cues):
        return True
    score = getattr(asset, "relevance_score", None)
    reason = str(getattr(asset, "review_reason", "") or "")
    weak = ((score is not None and float(score) < config.ANIMATION_OVER_FOOTAGE_BELOW)
            or reason.startswith(_WEAK_REASONS))
    if not weak:
        return False
    return mapped or any(c["cue"] in SCENE_CUES and c["emphasis"] == "high" for c in cues)


def animation_for(seg, shot: dict, pack: dict, brief: Optional[dict],
                  counts: Optional[Dict[str, int]] = None) -> Optional[dict]:
    """
    A full-screen motion graphic for a beat, or None. Only data earns the
    full-screen layout (the owner: percentages, money, comparisons): a map for
    a place the director mapped, a number, money or comparison graphic for a
    figure in the line. A plain line gets None - it keeps its footage, or
    borrows a matching shot - never a title card on a blurred background.
    """
    pack = pack or {}
    hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else None
    tid, props = "", {}
    if hint and hint.get("type") == "map" and (hint.get("locations") or hint.get("places")):
        tid = _from_hint(hint, pack, len(hint.get("locations") or hint.get("places") or []), seg.text, counts) or ""
        props = _hint_props(hint)
    if not tid:
        for cue in cues_for(seg, shot, brief):
            if cue["cue"] not in SCENE_CUES:
                continue
            # The least used full-frame look for the cue, so a video's
            # full-screen numbers rotate (tank, pie, gauge, dots...) instead of
            # one gauge every time. Tags that ride on footage are not candidates.
            options = []
            for name in [cue["cue"]] + (CUE_FALLBACK.get(cue["cue"], []) if cue["cue"] == "count" else []):
                options = [t for t in templates.for_cue(name, pack.get("id", ""))
                           if t["kind"] in CARD_KINDS and look_fits(t["id"], seg.text or "")
                           and not _needs_places(t, cue["props"])]
                if options:
                    break
            if not options:
                continue
            if counts:
                options = sorted(options, key=lambda t: counts.get(t["id"], 0))
            tid, props = options[0]["id"], dict(cue["props"])
            break
    if not tid:
        return None
    if counts is not None:
        counts[tid] = counts.get(tid, 0) + 1
    resolved = templates.resolve(tid, style=str(pack.get("caption") or ""), props=props, pack=pack)
    resolved.pop("seconds", None)
    resolved.pop("sfx", None)
    resolved.pop("_motion", None)
    return resolved


def counts(scenes: List[dict], overlays: List[dict], sfx: List[dict], music: dict,
           treatments: List[dict]) -> Dict[str, Any]:
    cat = {}
    for ov in overlays:
        t = templates.get(ov.get("template") or "")
        c = t["category"] if t else "OTHER"
        cat[c] = cat.get(c, 0) + 1
    footage = sum(1 for s in scenes if (s.get("media") or {}).get("type") == "video")
    animations = sum(1 for s in scenes if (s.get("media") or {}).get("type") == "animation")
    stills = [s for s in scenes if (s.get("media") or {}).get("type") == "image"]
    image_treated = sum(1 for s in stills if (s.get("motion") or "none") != "none" or (s.get("effect") or "none") != "none")
    transitions = sum(1 for s in scenes if (s.get("transition") or "none") != "none")
    text = sum(cat.get(c, 0) for c in ("TEXT", "HEADLINES", "LOWER_THIRDS", "QUOTES", "DOCUMENTS"))
    data = sum(cat.get(c, 0) for c in ("NUMBERS", "CHARTS", "COMPARISONS", "TIMELINES"))
    return {
        "scenes": len(scenes), "footage_scenes": footage, "image_scenes": len(stills),
        "animation_scenes": animations,
        "text_treatments": text, "maps": cat.get("MAPS", 0), "data_graphics": data,
        "callouts": cat.get("CALLOUTS", 0), "image_treatments": image_treated,
        "transitions": transitions, "sfx": len(sfx), "music_cues": len(music.get("sections") or []),
        "total_treatments": len(overlays) + image_treated + transitions + animations,
        "by_category": cat,
        "unique_templates": len({ov.get("template") for ov in overlays if ov.get("template")}),
    }


def note_figure(seen: dict, seg, animation: Optional[dict]) -> None:
    """Record the figure an animation scene drew (for wants_animation's repeat check)."""
    if animation and animation.get("value") is not None:
        try:
            seen[("figure", float(animation["value"]))] = seg.start
        except (TypeError, ValueError):
            pass
