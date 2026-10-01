"""
Spoken numbers to digits, for the words the date, time and number looks show
(the owner, 2026-10-01: "when the number is said, like September 29 or 5
days, you show it as a word ('five days') instead of numbers - fix").

A script written for a voice spells its numbers out ("five days", "September
twenty-ninth", "three thousand homes"), and the looks drew them as words.

    parse("twenty-two")                  -> 22.0
    parse("a hundred and twenty")        -> 120.0
    parse("two point five")              -> 2.5
    parse("nineteen sixty-one")          -> 1961.0   (a year said in pairs)
    ordinal("twenty-ninth")              -> 29
    normalize("five days")               -> "5 days"
    normalize("SEPTEMBER TWENTY-NINTH")  -> "SEPTEMBER 29"
    normalize("forty-eight hours")       -> "48 hours"
    normalize("three thousand homes")    -> "3,000 homes"
    normalize("two point five inches")   -> "2.5 inches"
    normalize("seventy-five million acre-feet") -> "75 million acre-feet"
    normalize("the fifteenth of September")     -> "September 15"
    normalize("seven thirty pm")         -> "7:30 pm"
    normalize("Three Rivers")            -> "Three Rivers"   (a name: nothing numeric follows it)

A phrase becomes digits when it is plainly a number: a unit, a count, a time
of day or "percent" follows it, a month stands beside it, it is a year, a
decimal, a hundred or more, a number of two or more words, or the whole text.
A single number word before anything else is left alone ("Three Rivers",
"Seven Oaks", "one of them"), and so is a capitalised one in the middle of an
ordinary sentence (a name). An ordinal becomes digits only in a date
("September twenty-ninth", "the fifteenth of September").

Its twin for the renderer is remotion/src/components/lib/numWords.ts (the
looks also read older documents and the editor's words); tests/test_numwords.py
runs both on the same cases.
"""
import re
from typing import List, Optional, Tuple

_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine".split())}
_TEENS = {w: i + 10 for i, w in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12}
_ORD_UNITS = {w: i + 1 for i, w in enumerate("first second third fourth fifth sixth seventh eighth ninth".split())}
_ORD_TEENS = {w: i + 10 for i, w in enumerate(
    "tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split())}
_ORD_TENS = {w: (i + 2) * 10 for i, w in enumerate(
    "twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth".split())}
_ORD_SCALES = {"thousandth": 10 ** 3, "millionth": 10 ** 6, "billionth": 10 ** 9}

_VOCAB = sorted(set(_UNITS) | set(_TEENS) | set(_TENS) | set(_SCALES) | set(_ORD_UNITS) | set(_ORD_TEENS)
                | set(_ORD_TENS) | set(_ORD_SCALES) | {"hundred", "hundredth", "oh", "a", "an", "and", "point", "half"},
                key=lambda w: (-len(w), w))
_ALT = "|".join(_VOCAB)
# A run of number words and the glue between them; each run is read word by word.
_RUN = re.compile(r"\b(?:" + _ALT + r")(?:(?:\s+|\s*-\s*)(?:" + _ALT + r"))*\b", re.I)
_WORD = re.compile(r"[A-Za-z]+")

MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
          "jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec")
_MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
                "NOVEMBER", "DECEMBER"]
# Words that make the number before them a quantity: units, spans of time, counts of things.
# (Never a river, a lake, an oak or a spring: "Three Rivers" and "Seven Oaks" are places.)
UNIT_WORDS = (
    "seconds?|minutes?|hours?|days?|nights?|weeks?|weekends?|months?|years?|decades?|centuries|century|"
    "inch|inches|foot|feet|ft|yards?|miles?|meters?|metres?|kilometers?|kilometres?|km|mph|knots?|"
    "acres?|acre-feet|acre-foot|square|cubic|gallons?|liters?|litres?|barrels?|tons?|tonnes?|pounds?|lbs|"
    "ounces?|degrees?|cents?|"
    "people|persons?|residents?|homes?|houses?|households?|families|family|children|child|kids?|students?|"
    "workers?|jobs?|deaths?|lives|victims?|structures?|buildings?|businesses|business|farms?|vehicles?|cars?|"
    "trucks?|animals?|trees?|visitors?|tourists?|customers?|patients?|soldiers?|troops?|refugees?|migrants?|"
    "voters?|employees?|firefighters?|states?|counties|county|cities|city|towns?|communities|community|"
    "countries|country|schools?|hospitals?|roads?|dams?|reservoirs?|storms?|floods?|fires?|wildfires?|"
    "earthquakes?|tornado(?:e?s)?|hurricanes?|times|percent|per\\s+cent|dollars?")
_UNIT_AFTER = re.compile(r"^\s*-?\s*(?:" + UNIT_WORDS + r")\b", re.I)
_PERCENT_AFTER = re.compile(r"^\s*(?:%|percent\b|per\s+cent\b)", re.I)
_DOLLARS_AFTER = re.compile(r"^\s*dollars?\b", re.I)
_AMPM_AFTER = re.compile(r"^\s*[ap]\.?\s?m\b\.?", re.I)
_OCLOCK_AFTER = re.compile(r"^\s*o['’]?\s?clock\b", re.I)
_MONTH_BEFORE = re.compile(r"\b(" + MONTHS + r")\.?\s+(?:the\s+)?$", re.I)
_THE_BEFORE = re.compile(r"\bthe\s+$", re.I)
_OF_MONTH_AFTER = re.compile(r"^\s+of\s+(" + MONTHS + r")\b\.?", re.I)
_MONTH_AFTER = re.compile(r"^\s+(" + MONTHS + r")\b", re.I)
_YEAR_BEFORE = re.compile(r"\b(?:in|since|by|until|from|of|year|before|after)\s+$", re.I)
_SENTENCE_START = re.compile(r"(?:^|[.!?:;—(\"“]\s*)$")
_ALNUM = re.compile(r"[A-Za-z0-9]")
_DIGIT_ORDINAL = re.compile(r"\b(" + MONTHS + r")(\.?\s+)(\d{1,2})(?:st|nd|rd|th)\b", re.I)
_DIGIT_THOUSAND = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s+thousand\b", re.I)
_CLOCK = re.compile(r"\b((?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
                    r"(?:\s+(?:oh\s+)?[a-z]+(?:[\s-][a-z]+)?))(\s*[ap]\.?\s?m\b\.?)", re.I)


class _Parse:
    """A number read word by word (feed one word at a time; value() once it is a whole number)."""

    def __init__(self):
        self.total = 0.0
        self.cur = 0.0
        self.unit = self.teen = self.tens = self.hund = False
        self.last_scale = 0
        self.lead_a = False        # began "a" / "an" ("a hundred", "a million")
        self.n = 0                 # number words read (not "a", "and", "point")
        self.and_pending = False   # "a hundred and ..." waits for its number
        self.half_step = 0         # "... and a half": 1 after "and", 2 after "a"
        self.after_big = False     # the last word was "hundred" or a scale
        self.point = False         # "point" read, its first digit not yet
        self.dec = ""              # the digits said after "point"
        self.half = False
        self.ordinal = False
        self.done = False          # nothing may follow (an ordinal, a zero, a half, a scale after decimals)
        self.scale_word = ""       # the largest scale said ("million"), as written
        self.big = False           # a hundred, a scale, a decimal or a half was said

    def value(self) -> Optional[float]:
        if self.and_pending or self.point or self.half_step or (self.n == 0 and not self.dec):
            return None
        v = self.total + self.cur + (float("0." + self.dec) if self.dec else 0.0)
        return v + 0.5 if self.half else v

    def feed(self, raw: str) -> bool:
        """Take one more word; False when it cannot continue the number."""
        w = raw.lower()
        if self.done:
            return False
        if self.half_step == 1:
            if w in ("a", "an"):
                self.half_step, self.and_pending = 2, False
                return True
            if not self.and_pending:
                return False
            self.half_step = 0
        elif self.half_step == 2:
            if w != "half":
                return False
            self.half_step = 0
            self.half = self.done = self.big = True
            return True
        if self.point or self.dec:
            if w in _UNITS or w == "oh":
                self.dec += str(_UNITS.get(w, 0))
                self.point = False
                return True
            if w in _SCALES and self.dec and not self.total and self.cur < 1000:
                self.cur = (self.cur + float("0." + self.dec)) * _SCALES[w]
                self.dec = ""
                self.scale_word, self.done = raw, True
                self.n += 1
                return True
            return False
        if w in ("a", "an"):
            if self.n or self.lead_a:
                return False
            self.lead_a = True
            return True
        if w == "and":
            if self.and_pending or not self.n:
                return False
            self.and_pending = self.after_big
            self.half_step = 1
            return True
        if w == "point":
            if self.hund or self.after_big or self.lead_a:
                return False
            self.point = self.big = True
            return True
        if w in ("half", "oh"):
            return False
        if self.lead_a and w not in _SCALES and w not in _ORD_SCALES and w not in ("hundred", "hundredth"):
            return False
        if w == "zero":
            if self.n:
                return False
            self.n, self.done = 1, True
            return True
        if w in _UNITS or w in _ORD_UNITS:
            if self.unit or self.teen:
                return False
            self.cur += _UNITS.get(w) or _ORD_UNITS[w]
            self.unit = True
            self.ordinal = self.done = w in _ORD_UNITS
        elif w in _TEENS or w in _ORD_TEENS:
            if self.unit or self.teen or self.tens:
                return False
            self.cur += _TEENS.get(w) or _ORD_TEENS[w]
            self.teen = True
            self.ordinal = self.done = w in _ORD_TEENS
        elif w in _TENS or w in _ORD_TENS:
            if self.unit or self.teen or self.tens:
                return False
            self.cur += _TENS.get(w) or _ORD_TENS[w]
            self.tens = True
            self.ordinal = self.done = w in _ORD_TENS
        elif w in ("hundred", "hundredth"):
            if self.hund or self.cur >= 100 or (not self.cur and not self.lead_a):
                return False
            self.cur = (self.cur or 1) * 100
            self.unit = self.teen = self.tens = False
            self.hund = self.big = True
            self.ordinal = self.done = w == "hundredth"
        elif w in _SCALES or w in _ORD_SCALES:
            scale = _SCALES.get(w) or _ORD_SCALES[w]
            if (not self.cur and not self.lead_a) or (self.last_scale and scale >= self.last_scale):
                return False
            self.total += (self.cur or 1) * scale
            self.cur = 0.0
            self.unit = self.teen = self.tens = self.hund = False
            self.last_scale = scale
            self.scale_word = self.scale_word or raw
            self.big = True
            self.ordinal = self.done = w in _ORD_SCALES
        else:
            return False
        self.after_big = w in ("hundred",) or w in _SCALES
        self.lead_a = False
        self.n += 1
        self.and_pending = False
        self.half_step = 0
        return True


def _two_digits(words: List[str]) -> Tuple[Optional[int], int]:
    """The 01-99 a year or a clock's minutes end on ("sixty-one", "oh five", "twenty"): (value, words used)."""
    if not words:
        return None, 0
    w = words[0].lower()
    nxt = words[1].lower() if len(words) > 1 else ""
    if w == "oh" and nxt in _UNITS and nxt != "zero":
        return _UNITS[nxt], 2
    if w in _TEENS:
        return _TEENS[w], 1
    if w in _TENS:
        if nxt in _UNITS and nxt != "zero":
            return _TENS[w] + _UNITS[nxt], 2
        return _TENS[w], 1
    return None, 0


def _read(words: List[str]) -> Optional[dict]:
    """The longest number the words start with: {value, used, kind, scale, big, words} or None."""
    if len(words) >= 3 and words[0].lower() == "half" and words[1].lower() in ("a", "an") \
            and words[2].lower() in _SCALES:
        return {"value": 0.5 * _SCALES[words[2].lower()], "used": 3, "kind": "cardinal", "scale": words[2],
                "big": True, "words": 2}
    p = _Parse()
    best = None
    stop = len(words)
    for i, w in enumerate(words):
        if not p.feed(w):
            stop = i
            break
        v = p.value()
        if v is not None:
            best = {"value": v, "used": i + 1, "kind": "ordinal" if p.ordinal else "decimal" if p.dec else "cardinal",
                    "scale": p.scale_word, "big": p.big, "words": p.n}
    if best and best["kind"] == "cardinal" and not best["big"] and best["used"] == stop < len(words) \
            and 15 <= p.cur <= 20 and not p.unit:
        # A year said in pairs: "nineteen sixty-one", "twenty twenty-six", "nineteen oh five".
        rest, used = _two_digits(words[stop:])
        if rest is not None:
            return {"value": float(p.cur * 100 + rest), "used": stop + used, "kind": "year", "scale": "",
                    "big": True, "words": best["words"] + used}
    return best


def parse(text: str) -> Optional[float]:
    """The number a phrase says when the whole phrase is one ('twenty-two', 'two point five'), else None."""
    words = _WORD.findall(text or "")
    got = _read(words) if words else None
    return got["value"] if got and got["used"] == len(words) and got["kind"] != "ordinal" else None


def ordinal(text: str) -> Optional[int]:
    """The number an ordinal says ('twenty-ninth' -> 29, '29th' -> 29), else None."""
    m = re.fullmatch(r"\s*(\d{1,3})(?:st|nd|rd|th)\s*", text or "", re.I)
    if m:
        return int(m.group(1))
    words = _WORD.findall(text or "")
    got = _read(words) if words else None
    return int(got["value"]) if got and got["used"] == len(words) and got["kind"] == "ordinal" else None


def _plain(q: float) -> str:
    """2.5 -> '2.5', 75.0 -> '75', 1.25 -> '1.25' (at most three decimals)."""
    s = ("%.3f" % q).rstrip("0").rstrip(".")
    return s or "0"


def _grouped(whole: int) -> str:
    return "{:,}".format(whole)


def _digits(value: float, kind: str, scale: str, comma: bool) -> str:
    if kind == "year":
        return str(int(value))
    big = (scale or "").lower()
    if big in ("million", "billion", "trillion"):
        # "75 million", "1.2 billion"; half a billion is "500 million" (half a million is 500,000).
        for name in ("trillion", "billion", "million"):
            if _SCALES[name] <= _SCALES[big] and value >= _SCALES[name]:
                word = scale if name == big else name.upper() if scale.isupper() else \
                    name.capitalize() if scale[:1].isupper() else name
                return _plain(value / _SCALES[name]) + " " + word
    s = _plain(value)
    whole, _, frac = s.partition(".")
    if comma and int(whole) >= 1000:
        whole = _grouped(int(whole))
    return whole + ("." + frac if frac else "")


def _informative_case(text: str) -> bool:
    """Ordinary sentence case (most words begin lower case): a capital mid-sentence then marks a name."""
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", text)
    return len(words) >= 3 and 2 * sum(1 for w in words if w[0].islower()) >= len(words)


def _month_name(word: str) -> str:
    """'sept' -> 'September' in the word's own case."""
    name = next((m for m in _MONTH_NAMES if m.startswith(word.upper()[:3])), word.upper())
    if word.isupper():
        return name
    return name.capitalize() if word[:1].isupper() else name.lower()


def _month_before(before: str) -> bool:
    m = _MONTH_BEFORE.search(before)
    return bool(m) and m.group(1) != "may"            # "it may one day" is not May 1


def _render(text: str, a: int, b: int, got: dict, first: str, informative: bool):
    """(replacement, start, end) for the number said at text[a:b], or None to leave it as said."""
    before, after = text[:a], text[b:]
    value, kind = got["value"], got["kind"]
    month_before = _month_before(before)
    month_after = _MONTH_AFTER.match(after)
    month_after = month_after if month_after and month_after.group(1) != "may" else None
    of_month = _OF_MONTH_AFTER.match(after)
    day = int(value) if float(value).is_integer() and 1 <= value <= 31 else 0
    the = _THE_BEFORE.search(before)
    if of_month and day and (kind == "ordinal" or (kind == "cardinal" and the)):
        # "the twenty-ninth of September" -> "September 29"
        return _month_name(of_month.group(1)) + " " + str(day), (the.start() if the else a), b + of_month.end()
    if kind == "ordinal":
        if not day or not (month_before or month_after):
            return None
        # "September the twenty-ninth" -> "September 29"
        return str(day), (the.start() if the and month_before else a), b
    unit = _UNIT_AFTER.match(after)
    ampm = _AMPM_AFTER.match(after)
    oclock = _OCLOCK_AFTER.match(after)
    whole = not _ALNUM.search(before) and not _ALNUM.search(after)
    strong = bool(unit or ampm or oclock or month_before or month_after) or kind in ("year", "decimal") or got["big"]
    if not strong:
        name = informative and first[:1].isupper() and not _SENTENCE_START.search(before)
        if name or not (got["words"] >= 2 or whole):
            return None
    if oclock and day and value <= 12:
        return str(day) + ":00", a, b + oclock.end()
    year_like = kind == "year" or (float(value).is_integer() and 1000 <= value <= 2099 and not unit
                                   and (month_before or whole or bool(_YEAR_BEFORE.search(before))))
    digits = _digits(value, "year" if year_like else kind, got["scale"], not year_like)
    percent = _PERCENT_AFTER.match(after)
    if percent:
        return digits + "%", a, b + percent.end()
    dollars = _DOLLARS_AFTER.match(after)
    if dollars:
        return "$" + digits, a, b + dollars.end()
    return digits, a, b


def _clock(text: str) -> str:
    """'seven thirty pm' -> '7:30 pm', 'eleven oh five a.m.' -> '11:05 a.m.' (an hour and its minutes before am/pm)."""

    def fix(m: "re.Match") -> str:
        words = _WORD.findall(m.group(1))
        mins, used = _two_digits(words[1:])
        h = _read(words[:1])
        if not h or not 1 <= h["value"] <= 12 or mins is None or used != len(words) - 1 or mins > 59:
            return m.group(0)
        return "%d:%02d%s" % (int(h["value"]), mins, m.group(2))

    return _CLOCK.sub(fix, text)


def normalize(text: str) -> str:
    """The text with every plainly numeric spoken number in digits (see the module's notes)."""
    if not text or not isinstance(text, str):
        return text
    text = _DIGIT_ORDINAL.sub(lambda m: m.group(1) + m.group(2) + m.group(3), text)
    text = _DIGIT_THOUSAND.sub(lambda m: _digits(float(m.group(1)) * 1000, "cardinal", "", True), text)
    text = _clock(text)
    informative = _informative_case(text)
    out: List[str] = []
    pos = 0
    for run in _RUN.finditer(text):
        spans = [(run.start() + m.start(), run.start() + m.end()) for m in _WORD.finditer(run.group(0))]
        words = [text[x:y] for x, y in spans]
        s = 0
        while s < len(words):
            if spans[s][0] < pos:
                s += 1
                continue
            got = _read(words[s:])
            rep = _render(text, spans[s][0], spans[s + got["used"] - 1][1], got, words[s], informative) if got else None
            if rep is None or rep[1] < pos:
                s += 1
                continue
            new, x, y = rep
            out.append(text[pos:x])
            out.append(new)
            pos = y
            s += got["used"]
    out.append(text[pos:])
    return "".join(out)
