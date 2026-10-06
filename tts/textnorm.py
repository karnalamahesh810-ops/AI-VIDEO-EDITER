"""
Script text -> what the voice model should read, and the pieces it reads.

Pure Python (no torch), so the offline tests run anywhere.

* normalize(): English numbers, money, percentages, years, dates, units and a
  few abbreviations spelled out the way a narrator says them ("$3.5 billion"
  -> "three point five billion dollars", "1987" -> "nineteen eighty-seven",
  "45%" -> "forty-five percent"). Voice models misread digits now and then;
  a documentary script is full of them.
* plan_chunks(): the script cut into pieces of at most ~300 characters (about
  20 s of speech) on sentence boundaries, each with the pause that follows it
  (longer after a paragraph or a question, short after a comma split). The
  model reads one piece at a time: long inputs are where open TTS models
  hallucinate or trail off, and fixed pauses between pieces give an even,
  human rhythm instead of whatever silence the model happened to leave.
* words_for_compare(): the same normalization applied to a transcript, so a
  speech-recognition check can compare what was said with what was asked.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
        "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
SCALES = [(10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand")]
SCALE_WORDS = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12,
               "k": 10 ** 3, "m": 10 ** 6, "mn": 10 ** 6, "bn": 10 ** 9, "b": 10 ** 9, "tn": 10 ** 12}


def _under_100(n: int) -> str:
    if n < 20:
        return ONES[n]
    t, o = divmod(n, 10)
    return TENS[t] + ("-" + ONES[o] if o else "")


def _under_1000(n: int) -> str:
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts.append(ONES[h] + " hundred")
    if rest:
        parts.append(_under_100(rest))
    return " ".join(parts) if parts else "zero"


def int_words(n: int) -> str:
    """1050 -> 'one thousand fifty' (American style, no 'and')."""
    if n < 0:
        return "minus " + int_words(-n)
    if n < 1000:
        return _under_1000(n)
    if n >= 10 ** 15:
        return " ".join(ONES[int(d)] for d in str(n))
    parts = []
    for value, word in SCALES:
        if n >= value:
            q, n = divmod(n, value)
            parts.append(_under_1000(q) + " " + word)
    if n:
        parts.append(_under_1000(n))
    return " ".join(parts)


def year_words(n: int) -> str:
    """1987 -> nineteen eighty-seven, 2005 -> two thousand five, 2026 -> twenty twenty-six."""
    if 2000 <= n <= 2009:
        return "two thousand" + (" " + ONES[n - 2000] if n > 2000 else "")
    if n < 1000 or n > 9999:
        return int_words(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return _under_100(hi) + " hundred"
    if lo < 10:
        return _under_100(hi) + " oh " + ONES[lo]
    return _under_100(hi) + " " + _under_100(lo)


_ORD_SPECIAL = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                "nine": "ninth", "twelve": "twelfth"}


def ordinal_words(n: int) -> str:
    words = int_words(n)
    head, sep, last = words.rpartition(" ")
    lead, dash, tail = last.rpartition("-")
    if tail in _ORD_SPECIAL:
        tail = _ORD_SPECIAL[tail]
    elif tail.endswith("y"):
        tail = tail[:-1] + "ieth"
    else:
        tail += "th"
    last = lead + dash + tail
    return head + sep + last


def plural_words(words: str) -> str:
    """'nineteen ninety' -> 'nineteen nineties' (decades)."""
    if words.endswith("y"):
        return words[:-1] + "ies"
    if words.endswith("x"):
        return words + "es"
    return words + "s"


def decimal_words(text: str) -> str:
    """'3.5' -> 'three point five', '1,050.25' -> 'one thousand fifty point two five'."""
    text = text.replace(",", "")
    if "." in text:
        whole, frac = text.split(".", 1)
        whole_w = int_words(int(whole)) if whole else "zero"
        frac = frac.rstrip("0") if len(frac) > 2 else frac
        if not frac:
            return whole_w
        return whole_w + " point " + " ".join(ONES[int(d)] for d in frac if d.isdigit())
    return int_words(int(text))


def _num_value(text: str) -> float:
    return float(text.replace(",", ""))


CURRENCY = {"$": ("dollar", "dollars", "cent", "cents"), "£": ("pound", "pounds", "penny", "pence"),
            "€": ("euro", "euros", "cent", "cents"), "₹": ("rupee", "rupees", "paisa", "paise")}

# Units read after a number (lowercase keys; matched case-sensitively where it matters below).
UNITS = {
    "mph": "miles per hour", "km/h": "kilometers per hour", "kph": "kilometers per hour",
    "km": "kilometers", "kms": "kilometers", "mi": "miles", "ft": "feet", "in.": "inches",
    "cm": "centimeters", "mm": "millimeters", "kg": "kilograms", "lbs": "pounds", "lb": "pounds",
    "sq mi": "square miles", "sq km": "square kilometers", "sq ft": "square feet",
    "km²": "square kilometers", "mi²": "square miles", "m²": "square meters", "ft²": "square feet",
    "m³": "cubic meters", "cfs": "cubic feet per second", "maf": "million acre-feet",
    "mw": "megawatts", "gw": "gigawatts", "kw": "kilowatts", "kwh": "kilowatt hours",
    "mwh": "megawatt hours", "gwh": "gigawatt hours", "mb": "megabytes", "gb": "gigabytes",
    "tb": "terabytes", "ghz": "gigahertz", "mhz": "megahertz", "hz": "hertz",
    "ml": "milliliters", "l": "liters", "oz": "ounces", "t": "tons",
}
# Words after a 4-digit number that make it a quantity ("1050 feet"), not a year.
QUANTITY_NEXT = {
    "feet", "foot", "ft", "meters", "metres", "miles", "mi", "km", "kilometers", "kilometres", "people",
    "homes", "houses", "acres", "acre-feet", "gallons", "tons", "tonnes", "pounds", "dollars", "years",
    "days", "hours", "minutes", "seconds", "species", "times", "residents", "workers", "jobs", "cars",
    "square", "cubic", "degrees", "inches", "mph", "deaths", "cases", "units", "lbs", "kg", "of",
    "million", "billion", "thousand", "trillion", "percent", "students", "soldiers", "men", "women",
    "children", "families", "buildings", "wells", "dams", "lakes", "rivers", "farms", "animals",
}
YEAR_CUES = {"in", "since", "by", "until", "till", "from", "of", "year", "early", "late", "mid",
             "around", "circa", "between", "before", "after", "during", "spring", "summer", "fall",
             "autumn", "winter", "january", "february", "march", "april", "may", "june", "july",
             "august", "september", "october", "november", "december", "jan", "feb", "mar", "apr",
             "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "through", "to", "and", "the"}

ABBREVIATIONS = [
    (r"\bDr\.(?=\s+[A-Z])", "Doctor"), (r"\bMr\.", "Mister"), (r"\bMrs\.", "Missus"), (r"\bMs\.(?=\s)", "Miz"),
    (r"\bProf\.(?=\s+[A-Z])", "Professor"), (r"\bSt\.(?=\s+[A-Z][a-z])", "Saint"), (r"\bMt\.(?=\s+[A-Z])", "Mount"),
    (r"\bFt\.(?=\s+[A-Z])", "Fort"), (r"\bGen\.(?=\s+[A-Z])", "General"), (r"\bGov\.(?=\s+[A-Z])", "Governor"),
    (r"\bSen\.(?=\s+[A-Z])", "Senator"), (r"\bRep\.(?=\s+[A-Z])", "Representative"), (r"\bPres\.(?=\s+[A-Z])", "President"),
    (r"\bvs\.?(?=\s)", "versus"), (r"\betc\.", "et cetera"), (r"\be\.g\.,?", "for example,"), (r"\bi\.e\.,?", "that is,"),
    (r"\bapprox\.", "approximately"), (r"\bNo\.\s?(?=\d)", "number "), (r"\bw/(?=\s)", "with"),
]

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]

# Square-bracket stage directions written for other engines ("[whispers]", "[pause]") are not read.
STAGE_DIRECTION = re.compile(r"\[(?:[a-z][a-z ]{0,24})\]", re.I)


def _clean_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    repl = {"‘": "'", "’": "'", "“": '"', "”": '"', " ": " ", " ": " ",
            " ": " ", "…": "...", "−": "-", "·": ", ", "•": ", "}
    for a, b in repl.items():
        text = text.replace(a, b)
    # Markdown leftovers and symbols a narrator would not read.
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~`|^<>{}]", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    # Emoji and other pictographs (the degree sign is a symbol too, and is read).
    text = "".join(ch for ch in text if ch == "°" or unicodedata.category(ch) not in ("So", "Cs", "Co"))
    return text


def _money(m: re.Match) -> str:
    sym, amount, scale = m.group(1), m.group(2), (m.group(3) or "").strip().lower()
    one, many, sub_one, sub_many = CURRENCY[sym]
    if scale:
        scale_word = {"k": "thousand", "m": "million", "mn": "million", "bn": "billion", "b": "billion",
                      "tn": "trillion"}.get(scale, scale)
        return f"{decimal_words(amount)} {scale_word} {many}"
    value = _num_value(amount)
    if "." in amount:
        whole, frac = amount.replace(",", "").split(".", 1)
        cents = int((frac + "00")[:2])
        whole_i = int(whole or 0)
        if whole_i == 0 and cents:
            return f"{int_words(cents)} {sub_one if cents == 1 else sub_many}"
        out = f"{int_words(whole_i)} {one if whole_i == 1 else many}"
        if cents:
            out += f" and {int_words(cents)} {sub_one if cents == 1 else sub_many}"
        return out
    return f"{int_words(int(value))} {one if int(value) == 1 else many}"


def _percent(m: re.Match) -> str:
    return f"{decimal_words(m.group(1))} percent"


def _ordinal(m: re.Match) -> str:
    return ordinal_words(int(m.group(1)))


def _decade(m: re.Match) -> str:
    return plural_words(year_words(int(m.group(1))))


def _short_decade(m: re.Match) -> str:
    return plural_words(TENS[int(m.group(1))])


def _temperature(m: re.Match) -> str:
    num, scale = m.group(1), (m.group(2) or "").upper()
    word = {"F": " Fahrenheit", "C": " Celsius"}.get(scale, "")
    neg = num.startswith("-")
    core = decimal_words(num.lstrip("-"))
    unit = "degree" if core == "one" else "degrees"
    return ("minus " if neg else "") + f"{core} {unit}{word}"


def _time(m: re.Match) -> str:
    h, mm, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "")
    if h > 24 or mm > 59:
        return m.group(0)
    if mm == 0:
        core = f"{int_words(h)} o'clock" if not ampm else int_words(h)
    elif mm < 10:
        core = f"{int_words(h)} oh {ONES[mm]}"
    else:
        core = f"{int_words(h)} {_under_100(mm)}"
    if ampm:
        core += " " + ("a m" if ampm.lower().startswith("a") else "p m")
    return core


def _unit(m: re.Match) -> str:
    num, unit = m.group(1), m.group(2)
    word = UNITS.get(unit.lower())
    if not word:
        return m.group(0)
    spoken = decimal_words(num)
    if spoken == "one" and word.endswith("s") and word not in ("cubic feet per second",):
        word = {"feet": "foot", "inches": "inch"}.get(word, word[:-1])
    return f"{spoken} {word}"


def _multiplier(m: re.Match) -> str:
    return f"{decimal_words(m.group(1))} times"


def _range(m: re.Match) -> str:
    a, b = m.group(1), m.group(2)
    ia, ib = int(a), int(b)
    if 1000 <= ia <= 2099 and (1000 <= ib <= 2099 or len(b) == 2):
        if len(b) == 2:
            ib = (ia // 100) * 100 + ib
        return f"{year_words(ia)} to {year_words(ib)}"
    return f"{int_words(ia)} to {int_words(ib)}"


def _date(m: re.Match) -> str:
    month, day = m.group(1), int(m.group(2))
    rest = m.group(3) or ""
    out = f"{month} {ordinal_words(day)}" if 1 <= day <= 31 else m.group(0)
    return out + rest


_INITIALISM = re.compile(r"\b((?:[A-Z]\.){2,})(?=[\s,;:!?)\"']|$)")


def _initialism(m: re.Match) -> str:
    return " ".join(ch for ch in m.group(1) if ch.isalpha())


def _bare_number(text: str, start: int, end: int, raw: str) -> str:
    """A number with nothing special around it: a year or a quantity."""
    plain = raw.replace(",", "")
    if "." in plain:
        return decimal_words(raw)
    n = int(plain)
    if "," not in raw and len(plain) == 4 and 1100 <= n <= 2099:
        after = re.match(r"\s*([A-Za-z][A-Za-z\-]*)", text[end:])
        nxt = after.group(1).lower() if after else ""
        before = re.search(r"([A-Za-z]+)[\s,]*$", text[:start])
        prev = before.group(1).lower() if before else ""
        if nxt in QUANTITY_NEXT and prev not in YEAR_CUES:
            return int_words(n)
        return year_words(n)
    if len(plain) > 1 and plain.startswith("0"):
        return " ".join(ONES[int(d)] for d in plain)
    return int_words(n)


def normalize(text: str, lang: str = "en") -> str:
    """The text a narrator would read aloud. Non-English text only gets the symbol cleanup."""
    text = _clean_unicode(text or "")
    text = STAGE_DIRECTION.sub(" ", text)
    if lang and not lang.lower().startswith("en"):
        return re.sub(r"[ \t]+", " ", text).strip()

    for pat, rep in ABBREVIATIONS:
        text = re.sub(pat, rep, text)
    text = _INITIALISM.sub(_initialism, text)
    text = text.replace("&", " and ")
    text = re.sub(r"(?<=\w)\s*\+\s*(?=\w)", " plus ", text)
    text = re.sub(r"#\s?(\d+)", r"number \1", text)

    num = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    text = re.sub(r"([$£€₹])\s?" + num + r"(\s?(?:thousand|million|billion|trillion|bn|mn|tn|k|m|b)\b)?",
                  _money, text, flags=re.I)
    text = re.sub(num + r"\s?%", _percent, text)
    text = re.sub(r"(-?(?:" + num[1:-1] + r"))\s?°\s?([FC])?\b", lambda m: _temperature(_Fake(m.group(1), m.group(2))), text)
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", _ordinal, text)
    text = re.sub(r"\b(1[0-9]\d0|20\d0)s\b", _decade, text)
    text = re.sub(r"'(\d)0s\b", _short_decade, text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\s?([ap]\.?m\.?)?(?=\W|$)", _time, text, flags=re.I)
    months = "|".join(m.capitalize() for m in MONTHS)
    text = re.sub(r"\b(" + months + r")\s+(\d{1,2})(?!\d)(,?\s+\d{4})?", _date, text)
    text = re.sub(r"\b(\d{4})\s?[-–—]\s?(\d{4}|\d{2})\b", _range, text)
    text = re.sub(r"\b(\d{1,3})\s?[-–—]\s?(\d{1,3})\b(?!\s*[-–—]\s*\d)", _range, text)
    unit_alt = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
    text = re.sub(num + r"\s?(" + unit_alt + r")(?=[\s.,;:!?)]|$)", _unit, text, flags=re.I)
    text = re.sub(num + r"x\b", _multiplier, text)
    text = re.sub(r"(?<![\w.])-" + num + r"\b", lambda m: "minus " + decimal_words(m.group(1)), text)

    out, last = [], 0
    for m in re.finditer(num, text):
        out.append(text[last:m.start()])
        out.append(_bare_number(text, m.start(), m.end(), m.group(1)))
        last = m.end()
    out.append(text[last:])
    text = "".join(out)

    text = text.replace("/", " ")
    text = re.sub(r"\(\s*", ", ", text)
    text = re.sub(r"\s*\)", ",", text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"\s+-\s+", ", ", text)
    text = re.sub(r",\s*([.!?;:])", r"\1", text)
    text = re.sub(r"([.!?;:])\s*,", r"\1", text)
    text = re.sub(r",(\s*,)+", ",", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([.,;:!?])", r"\1", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


class _Fake:
    """Adapter so _temperature can take (number, scale) from a two-group match."""

    def __init__(self, num, scale):
        self._g = {1: num, 2: scale}

    def group(self, i):
        return self._g.get(i)


# ---------------------------------------------------------------------------------------------
# Chunking

SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")


@dataclass
class Chunk:
    text: str
    pause: float  # seconds of silence after this piece
    ends_paragraph: bool = False


# Pause after a piece, in seconds, by how it ends (scaled by the take's pause setting).
PAUSES = {"paragraph": 0.72, "?": 0.46, "!": 0.42, ".": 0.38, ":": 0.32, ";": 0.3, ",": 0.16, "": 0.2}


def _pause_for(piece: str, ends_paragraph: bool) -> float:
    if ends_paragraph:
        return PAUSES["paragraph"]
    end = piece.rstrip().rstrip("\"')]")[-1:] if piece.strip() else ""
    return PAUSES.get(end, PAUSES[""])


def split_sentences(paragraph: str) -> List[str]:
    parts = [p.strip() for p in SENTENCE_END.split(paragraph) if p and p.strip()]
    return parts


def _split_long(sentence: str, max_chars: int) -> List[str]:
    """A sentence over the limit, cut at the comma / semicolon / dash / conjunction nearest its middle."""
    if len(sentence) <= max_chars:
        return [sentence]
    best = None
    mid = len(sentence) / 2
    for m in re.finditer(r"[,;:]\s+|\s+(?=(?:and|but|or|which|while|because|although|when|where|so)\s)", sentence):
        cut = m.end() if sentence[m.start()] in ",;:" else m.start()
        if 30 <= cut <= len(sentence) - 30:
            score = abs(cut - mid)
            if best is None or score < best[0]:
                best = (score, cut)
    if best is None:
        words = sentence.split()
        half = len(words) // 2 or 1
        left, right = " ".join(words[:half]), " ".join(words[half:])
    else:
        left, right = sentence[:best[1]].strip(), sentence[best[1]:].strip()
    if left and left[-1] not in ",;:.!?":
        left += ","
    return _split_long(left, max_chars) + _split_long(right, max_chars)


def plan_chunks(text: str, max_chars: int = 300, min_chars: int = 60, pause_scale: float = 1.0) -> List[Chunk]:
    """
    The script as model-sized pieces with the pause after each. Paragraphs are kept apart (a
    paragraph pause after each); inside a paragraph, sentences are packed up to `max_chars` so the
    model reads related sentences together (natural flow), and a sentence that is too long on its
    own is cut at a comma near its middle. Pieces under `min_chars` join a neighbour: very short
    inputs make the model rush or add filler.
    """
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+|\n(?=\s*[-•*]\s)", clean) if p.strip()]
    if len(paragraphs) == 1 and "\n" in paragraphs[0]:
        paragraphs = [p.strip() for p in paragraphs[0].split("\n") if p.strip()]
    chunks: List[Chunk] = []
    for para in paragraphs:
        para = re.sub(r"\s+", " ", para)
        sentences: List[str] = []
        for s in split_sentences(para):
            sentences.extend(_split_long(s, max_chars))
        packed: List[str] = []
        cur = ""
        for s in sentences:
            if not cur:
                cur = s
            elif len(cur) + 1 + len(s) <= max_chars and (len(cur) < min_chars or len(s) < min_chars or len(cur) + len(s) <= max_chars * 0.8):
                cur = cur + " " + s
            else:
                packed.append(cur)
                cur = s
        if cur:
            if packed and len(cur) < min_chars // 2 and len(packed[-1]) + 1 + len(cur) <= max_chars * 1.15:
                packed[-1] = packed[-1] + " " + cur
            else:
                packed.append(cur)
        for i, piece in enumerate(packed):
            last = i == len(packed) - 1
            chunks.append(Chunk(piece, round(_pause_for(piece, last) * pause_scale, 3), last))
    return chunks


# ---------------------------------------------------------------------------------------------
# Comparing what was said with what was asked (speech-recognition check)

def words_for_compare(text: str) -> List[str]:
    t = normalize(text or "", "en").lower()
    t = t.replace("-", " ")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = t.replace("'", "")
    return [w for w in t.split() if w]


def word_error_rate(expected: List[str], heard: List[str]) -> float:
    """Levenshtein distance over words / words expected (0 = identical)."""
    if not expected:
        return 0.0 if not heard else 1.0
    prev = list(range(len(heard) + 1))
    for i, e in enumerate(expected, 1):
        cur = [i] + [0] * len(heard)
        for j, h in enumerate(heard, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if e == h else 1))
        prev = cur
    return prev[-1] / len(expected)


def expected_seconds(text: str, wpm: float = 155.0) -> float:
    """Rough spoken length of `text` at a narration pace (for the too-long / too-short check)."""
    words = len(re.findall(r"[A-Za-z0-9']+", text or ""))
    return words * 60.0 / wpm


def first_words(text: str, n: int = 8) -> Optional[str]:
    w = (text or "").split()
    return " ".join(w[:n]) if w else None
