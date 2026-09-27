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
"""
import re
from typing import Any, Dict, List, Optional

from . import config, templates
from .transcribe import Segment

# Read off VidRush's own timelines (an animation block every 8-10 s through
# the first two minutes, then every 15-25 s): denser than a "treatment every
# 20-40 s" documentary, because a faceless channel's viewer is on a phone.
MIN_GAP = 8.0           # seconds between any two treatments
TAG_GAP = 5.0           # a tag riding on the footage may follow sooner
QUIET_MAX = 18.0        # after this long with plain footage a light label is allowed
FAMILY_GAP = 45.0       # the same category is not repeated within this
SFX_GAP = 12.0          # seconds between two sounds
HIGH_GAP = 5.0          # a chapter, a number or a map may follow anything after this
HOOK_SECONDS = 120.0    # the opening, where the cadence is tightest
REPEAT_GAP = 90.0       # the same figure is not drawn again as a graphic within this
PRE_ROLL = 0.12         # a graphic lands this far ahead of the word it shows
TAIL = 0.45             # ... and stays this long after its sentence ends
MIN_HOLD = 2.2          # never shorter than this (readable)
HOLD_SLACK = 1.0        # never longer than the template's own hold plus this
HOOK_GAP = 6.0          # ... and any treatment may follow another after this
STRONG_CUES = {"percent", "change", "then-now", "big-number", "date", "route", "place", "quote", "chapter",
               "money", "money-compare", "series", "shares", "ratio", "measurement", "change-length",
               "compare-values", "recording", "document"}
# The owner: the full-screen layout is for percentages, money and comparisons,
# not for titles or quotes. Only these cues (and mapped places) become
# animation scenes; a plain line without footage borrows a matching shot.
SCENE_CUES = {"percent", "change", "then-now", "big-number", "money", "money-compare", "series", "shares",
              "ratio", "measurement", "change-length", "compare-values"}

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)", re.I)
_NUMBER_UNIT = re.compile(
    r"(\$?\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|feet|foot|ft|miles?|meters?|metres?|km|"
    r"acres?|gallons?|acre-feet|people|homes?|structures?|deaths?|hours?|minutes?|days?|"
    r"tons?|degrees|inches|dollars|residents|families|vehicles|square miles)\b", re.I)
_CHANGE = re.compile(
    r"\b(fell|fallen|dropped|declined|decreased|lost|shrank|rose|risen|increased|climbed|gained|"
    r"jumped|surged|grew)\b[^.]{0,60}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft|miles|meters|inches|"
    r"degrees|million|billion|thousand)?", re.I)
_DATE = re.compile(rf"\b(({_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*(?:1[89]|20)\d\d|({_MONTHS})\s+(?:1[89]|20)\d\d)\b", re.I)
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
               "acre-feet": "ACRE-FT", "acres": "ACRES", "acre": "ACRES", "gallons": "GAL", "gallon": "GAL",
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
do does did means meant mean says said shows showed which who whom whose what when where while it they we you""".split())


def _noun_after(text: str, match_end: int) -> str:
    """The noun a figure belongs to ("26% capacity", "26 percent of its
    capacity" -> CAPACITY); nothing when the next words are a verb or a
    function word ("26% means..." used to label the gauge MEANS)."""
    tail = text[match_end:match_end + 60]
    words = re.findall(r"[A-Za-z][\w-]*", tail)
    i = 0
    # "to" is not skipped: "cost $1.4 billion to build" names no noun.
    while i < len(words) and words[i].lower() in ("of", "in", "for", "at", "the", "its", "their", "his", "her", "our"):
        i += 1
    out = []
    for w in words[i:i + 3]:
        if w.lower() in _LABEL_SKIP or (out and w[0].isupper() and not out[-1][0].isupper()):
            break
        out.append(w)
        if len(out) == 2:
            break
    return " ".join(out).upper()[:32]


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


# --------------------------------------------------------------- cues
def cues_for(seg: Segment, shot: dict, brief: Optional[dict]) -> List[dict]:
    """
    What the line asks for, most specific first: [{cue, props, emphasis}].
    Only the line's own words and numbers ever reach a template.
    """
    text = seg.text or ""
    out: List[dict] = []
    m = _TWO_YEARS.search(text)
    if m and m.group(1) != m.group(4):
        a, b = _num(m.group(2)), _num(m.group(5))
        if a is not None and b is not None:
            unit = _UNIT_SHORT.get((m.group(3) or m.group(6) or "").lower(), "")
            out.append({"cue": "then-now", "emphasis": "high",
                        "props": {"text": _subject_words(shot, seg), "items": [
                            {"label": m.group(1), "value": a, "suffix": unit},
                            {"label": m.group(4), "value": b, "suffix": unit}]}})
    money = _money(text)
    if len(money) >= 2 and not out and re.search(r"\bfrom\b.*\bto\b", text, re.I):
        (a, ua, _e1), (b, ub, _e2) = money[0], money[1]
        out.append({"cue": "money-compare", "emphasis": "high",
                    "props": {"text": _subject_words(shot, seg), "items": [
                        {"label": "BEFORE", "value": a, "prefix": "$", "suffix": ua},
                        {"label": "AFTER", "value": b, "prefix": "$", "suffix": ub}]}})
    elif money and not out:
        v, unit, end = money[0]
        out.append({"cue": "money", "emphasis": "high",
                    "props": {"value": v, "prefix": "$", "suffix": unit,
                              "text": _noun_after(text, end) or _subject_words(shot, seg).upper()}})
    m = _CHANGE.search(text)
    if m and _num(m.group(2)) is not None and not any(c["cue"] in ("money", "money-compare") for c in out):
        down = m.group(1).lower() in ("fell", "fallen", "dropped", "declined", "decreased", "lost", "shrank")
        out.append({"cue": "change", "emphasis": "high",
                    "props": {"value": _num(m.group(2)), "suffix": _UNIT_SHORT.get((m.group(3) or "").lower(), ""),
                              "label": "down" if down else "up", "text": _subject_words(shot, seg)}})
    m = _PERCENT.search(text)
    if m and _num(m.group(1)) is not None and not any(c["cue"] in ("then-now", "change", "money", "money-compare")
                                                        for c in out):
        out.append({"cue": "percent", "emphasis": "high",
                    "props": {"value": _num(m.group(1)), "suffix": "%",
                              "text": _noun_after(text, m.end()) or _subject_words(shot, seg).upper()}})
    m = _NUMBER_UNIT.search(text)
    if m and _num(m.group(1)) is not None and not out:
        unit = m.group(2).lower()
        out.append({"cue": "big-number", "emphasis": "high",
                    "props": {"value": _num(m.group(1)), "suffix": _UNIT_SHORT.get(unit, unit.upper()[:8]),
                              "text": _subject_words(shot, seg).upper()}})
    m = _QUOTE.search(text)
    if m:
        out.append({"cue": "quote", "emphasis": "high",
                    "props": {"text": m.group(1).strip(), "label": _subject_words(shot, seg)}})
    elif _SAID.search(text) and len(text) < 220:
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
    m = _DATE.search(text)
    if m:
        out.append({"cue": "date", "emphasis": "medium", "props": {"text": m.group(1).upper()}})
    return _more_cues(text, seg, shot, out)


def _more_cues(text: str, seg: Segment, shot: dict, out: List[dict]) -> List[dict]:
    """The charts, ratios, rulers, recordings and documents a line can also ask for."""
    subject = _subject_words(shot, seg)
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
            props = {"value": _num(m.group(1)), "suffix": unit, "text": noun or subject.upper()}
            if noun in _SIZE_WORDS:
                props.update(text=subject.upper(), subtitle=noun)
            out.insert(idx, {"cue": "measurement", "emphasis": "high", "props": props})
    if _RECORDING.search(text):
        q = next((c for c in out if c["cue"] == "quote"), None)
        words = (q["props"]["text"] if q else text.strip().rstrip(".")).strip()
        if 12 <= len(words) <= 200:
            idx = next((i for i, c in enumerate(out) if c["cue"] == "quote"), len(out))
            out.insert(idx, {"cue": "recording", "emphasis": "high",
                             "props": {"text": words, "label": subject, "subtitle": "Audio recording"}})
    doc = _document(text)
    if doc:
        loose = next((i for i, c in enumerate(out) if c["cue"] == "quote" and c["emphasis"] != "high"), None)
        out.insert(loose if loose is not None else len(out), {"cue": "document", "emphasis": "high", "props": doc})
    return out


# ------------------------------------------------------------ choosing
class _Rhythm:
    def __init__(self):
        # The opening counts as a visual event: no filler label in the first
        # QUIET_MAX seconds, only treatments the lines ask for.
        self.last_any = 0.0
        self.last_card = -1e9
        self.last_by_cat: Dict[str, float] = {}
        self.last_sfx = -1e9

    def allows(self, at: float, t: dict) -> bool:
        # The opening two minutes run at VidRush's hook cadence: anything may
        # follow anything after HOOK_GAP, as long as no card is still up.
        if at < HOOK_SECONDS and at - self.last_any >= HOOK_GAP and not (
                t["kind"] in CARD_KINDS and self.overlaps(at)):
            return True
        gap = at - self.last_any
        need = TAG_GAP if t["kind"] == "tag" else MIN_GAP
        if t["emphasis"] == "high":
            need = min(need, HIGH_GAP)
        if gap < need and at > 0.0:
            return False
        if at - self.last_by_cat.get(t["category"], -1e9) < FAMILY_GAP and t["emphasis"] != "high":
            return False
        if t["kind"] in CARD_KINDS and at - self.last_card < (HIGH_GAP if t["emphasis"] == "high" else MIN_GAP):
            return False
        return True

    def overlaps(self, at: float) -> bool:
        """A card is still on screen."""
        return at < self.last_card - 0.5

    def note(self, at: float, t: dict, seconds: float) -> None:
        end = at + seconds
        self.last_any = end
        self.last_by_cat[t["category"]] = end
        if t["kind"] in CARD_KINDS:
            self.last_card = end


def _least_used(ids: List[str], counts: Optional[Dict[str, int]]) -> Optional[str]:
    """The first of `ids` that exists and has been used least (registry order breaks ties)."""
    real = []
    for tid in ids:
        if tid and templates.get(tid) and tid not in real:
            real.append(tid)
    if not real:
        return None
    if not counts:
        return real[0]
    return min(real, key=lambda t: (counts.get(t, 0), real.index(t)))


def _place_maps(pack: dict) -> List[str]:
    """The looks a single mapped place rotates through: the pack's own first."""
    return [pack.get("map", ""), "MAP_FOCUS_V1", "MAP_PHOTO_PIN_V1", "MAP_TILT_V1", "MAP_INSET_V1"]


def _from_hint(overlay: dict, pack: dict, n_locs: int, text: str,
               counts: Optional[Dict[str, int]] = None) -> Optional[str]:
    """The template for an overlay the AI director or the rules proposed."""
    kind = overlay.get("type")
    variant = overlay.get("variant") or ""
    if kind == "map":
        if variant.startswith("route") or variant == "satellite-route":
            return _least_used([pack["route"], "MAP_TRACE_V1"], counts)
        if variant.startswith("spread") or n_locs > 1:
            return pack["multi"]
        if variant == "region":
            return pack["region"]
        return _least_used(_place_maps(pack), counts)
    if kind == "bullets" and not variant and counts is not None:
        return _least_used(["CALL_BULLETS_V1", "FACTS_CARD_V1"], counts)
    if kind == "chapter":
        return pack["chapter"]
    if kind == "lower-third":
        return pack["lowerThird"]
    options = templates.for_component(kind, pack.get("id", ""))
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


def _template_for_cue(cue: str, pack: dict, used_recently: set,
                      counts: Optional[Dict[str, int]] = None) -> Optional[str]:
    if cue == "route":
        return _least_used([pack["route"], "MAP_TRACE_V1"], counts)
    if cue == "place":
        return _least_used(_place_maps(pack), counts)
    if cue == "chapter":
        return pack["chapter"]
    options = templates.for_cue(cue, pack.get("id", ""), exclude=used_recently)
    if counts:
        # The least used look for this cue first (registry order breaks ties),
        # so a video's percentages rotate gauge, ring, dots, bar... instead of
        # the same gauge every time.
        options = sorted(options, key=lambda t: counts.get(t["id"], 0))
    return options[0]["id"] if options else None


def _hint_props(overlay: dict) -> dict:
    keep = {}
    for k in ("text", "subtitle", "label", "suffix", "value", "items", "locations", "highlight", "body",
              "media", "anchor", "labelPosition", "places"):
        if overlay.get(k) is not None:
            keep[k] = overlay[k]
    return keep


WINDOW_GAP = 90.0        # seconds between two scenes shown in a player window
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
    resolved = templates.resolve("TAG_SOURCE_V1", style=style, props=props, pack=pack)
    if not resolved:
        return None
    resolved.pop("seconds", None)
    resolved.pop("sfx", None)
    n = max(1, min(int(round(3.5 * fps)), frames, total - start))
    return {**resolved, "startFrame": start, "durationInFrames": n}


def plan(segments: List[Segment], shots: List[dict], scenes: List[dict], fps: int, total: int,
         brief: Optional[dict], pack: dict, seconds_for: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Overlays, transitions, sounds, music sections and per-scene treatments.

    `scenes` are the built scene dicts (start/duration frames, media type);
    `seconds_for` is the renderer's minimum hold per component.
    """
    seconds_for = seconds_for or {}
    rhythm = _Rhythm()
    overlays: List[dict] = []
    treatments: List[dict] = []
    used_recently: Dict[str, float] = {}
    use_count: Dict[str, int] = {}
    seen_figures: Dict[tuple, float] = {}
    # Figures already drawn full screen by animation scenes count as seen.
    for sc_i, sc in enumerate(scenes):
        anim = sc.get("animation") if (sc.get("media") or {}).get("type") == "animation" else None
        if anim and anim.get("value") is not None and sc_i < len(segments):
            seen_figures[("figure", float(anim["value"]))] = segments[sc_i].start
    style = pack.get("id", "documentary")
    intensity = float(pack.get("animationIntensity", 1.0))
    hooks = set((brief or {}).get("hookBeats") or [])
    # The case-file devices, each rationed: one intro collage, a player
    # window at most every WINDOW_GAP seconds, an archive tag per archival run.
    intro_done = False
    last_window = -1e9
    prev_archival = False

    for i, seg in enumerate(segments):
        shot = shots[i] if i < len(shots) else {}
        scene = scenes[i] if i < len(scenes) else {}
        at = seg.start
        start = int(scene.get("startFrame", int(round(at * fps))))
        scene_frames = int(scene.get("durationInFrames", int(round(seg.duration * fps))))
        if (scene.get("media") or {}).get("type") == "animation":
            # The beat already IS a graphic (timeline.build filled it): no
            # overlay on top, but it counts against the rhythm like a card.
            anim = scene.get("animation") or {}
            t = templates.get(anim.get("template") or "")
            treatments.append({
                "primaryType": "animation", "secondaryType": t["category"].lower() if t else None,
                "template": anim.get("template"), "variant": anim.get("variant") or anim.get("style"),
                "entrance": anim.get("motion"), "exit": anim.get("exit"),
                "duration": round(scene_frames / fps, 2), "emphasis": "high", "animation": anim.get("motion"),
                "data": {k: anim[k] for k in ("value", "suffix", "items") if k in anim},
                "text": str(anim.get("text") or ""),
                "mapData": {"locations": anim.get("locations")} if anim.get("locations") else None,
                "chartData": None, "overlays": [], "transitionIn": scene.get("transition", "none"),
                "transitionOut": "none", "sfx": None, "musicCue": None,
            })
            if t:
                rhythm.note(at, t, scene_frames / fps)
                used_recently[t["id"]] = at
                use_count[t["id"]] = use_count.get(t["id"], 0) + 1
            prev_archival = False
            continue
        chosen: Optional[dict] = None
        chosen_id = ""
        props: dict = {}
        emphasis = "medium"

        hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else None
        if hint and hint.get("type") and hint["type"] not in ("photo-card", "name-card"):
            tid = _from_hint(hint, pack, len(hint.get("locations") or hint.get("places") or []), seg.text, use_count)
            t = templates.get(tid or "")
            # The director already spaced its own proposals (_thin_overlays);
            # only a card still on screen stops one.
            if t and not (t["kind"] in CARD_KINDS and rhythm.overlaps(at)):
                chosen, chosen_id, props = t, t["id"], _hint_props(hint)
                if hint.get("motion"):
                    props["_motion"] = hint["motion"]
                emphasis = t["emphasis"]
        if chosen is None and (scene.get("media") or {}).get("type") == "image":
            # A still is never just zoomed: it becomes a photo animation, by
            # what it shows (VidRush's person, place and object cards).
            pt = photo_template(shot)
            t = templates.get(pt[0])
            if t and not rhythm.overlaps(at):
                chosen, chosen_id, props, emphasis = t, t["id"], pt[1], t["emphasis"]
        if chosen is None:
            repeated = None
            for cue in cues_for(seg, shot, brief):
                key = _figure_key(cue)
                if key and at - seen_figures.get(key, -1e9) < REPEAT_GAP:
                    # "26%" again twenty seconds later: not the same gauge twice.
                    repeated = cue
                    continue
                recent = {k for k, v in used_recently.items() if at - v < FAMILY_GAP}
                tid = _template_for_cue(cue["cue"], pack, recent, use_count)
                t = templates.get(tid or "")
                if not t or not rhythm.allows(at, t):
                    continue
                chosen, chosen_id, props, emphasis = t, t["id"], dict(cue["props"]), cue["emphasis"]
                if key:
                    seen_figures[key] = at
                break
            if chosen is None and repeated is not None:
                # The repeat gets words instead of a graphic: the sentence with
                # the figure highlighted, riding on the footage.
                t = templates.get("TEXT_SENTENCE_HIGHLIGHT_V1")
                sentence = (seg.text or "").strip()
                if t and len(sentence) <= 110 and rhythm.allows(at, t):
                    chosen, chosen_id, emphasis = t, t["id"], "medium"
                    props = {"text": sentence, "highlight": _figure_words(sentence, repeated)}
        media_kind = (scene.get("media") or {}).get("type")
        if chosen is None and not intro_done and at < 150.0 and _INTRO.search(seg.text or "") \
                and len(scenes) - i > 4:
            # "This is the story of...": a burst of the video's own pictures.
            t = templates.get("PHOTO_COLLAGE_V1")
            if t and rhythm.allows(at, t):
                chosen, chosen_id, props, emphasis = t, t["id"], {}, "high"
                intro_done = True
        if chosen is None and media_kind == "video":
            pip = _pip_for(shot, scene)
            t = templates.get("PHOTO_PIP_V1") if pip else None
            if t and rhythm.allows(at, t) and not rhythm.overlaps(at):
                chosen, chosen_id, props, emphasis = t, t["id"], pip, "medium"
        if chosen is None and at - rhythm.last_any > QUIET_MAX and intensity >= 0.6:
            # A long stretch of plain footage: a light label, if the line names
            # a subject (the planner's, never a guessed capitalised word).
            subject = (shot.get("subject") or "").strip()[:60]
            if subject and len(subject) > 3:
                t = templates.get("TEXT_KICKER_V1")
                if t and rhythm.allows(at, t):
                    chosen, chosen_id, props, emphasis = t, t["id"], {"text": subject.upper()}, "low"

        transition_in = scene.get("transition", "none")
        entry = {
            "primaryType": ("image" if (scene.get("media") or {}).get("type") == "image" else
                            "footage" if (scene.get("media") or {}).get("type") == "video" else "empty"),
            "secondaryType": chosen["category"].lower() if chosen else None,
            "template": chosen_id or None, "variant": None, "entrance": None, "exit": None,
            "duration": None, "emphasis": emphasis if chosen else "low", "animation": None,
            "data": {}, "text": "", "mapData": None, "chartData": None, "overlays": [],
            "transitionIn": transition_in, "transitionOut": "none", "sfx": None, "musicCue": None,
        }
        if chosen:
            motion = props.pop("_motion", "")
            resolved = templates.resolve(chosen_id, style=style, entrance=motion, props=props, pack=pack)
            hold = max(resolved.get("seconds", 3.0), seconds_for.get(resolved["type"], 0.0))
            # On the voice: the graphic lands with the word it shows (the
            # figure, the date, the name) and leaves just after its sentence,
            # never the whole scene long (a scene can run 15 s).
            # A chart, comparison, timeline or map needs its full hold to be
            # read whatever the sentence; a number or a label follows the voice.
            min_hold = hold if chosen.get("category") in DATA_CATEGORIES else MIN_HOLD
            t_in, t_out = _voice_window(seg, props, hold, min_hold)
            o_start = max(0, min(int(round(t_in * fps)), total - 1))
            frames = max(1, min(int(round((t_out - t_in) * fps)), total - o_start))
            sfx = resolved.pop("sfx", {"name": "none", "volume": 0.0})
            overlay = {**resolved, "startFrame": o_start, "durationInFrames": frames}
            overlay.pop("seconds", None)
            overlays.append(overlay)
            rhythm.note(at, chosen, frames / fps)
            used_recently[chosen_id] = at
            use_count[chosen_id] = use_count.get(chosen_id, 0) + 1
            entry.update({
                "variant": overlay.get("variant") or overlay.get("style"), "entrance": overlay.get("motion"),
                "exit": overlay.get("exit"), "duration": round(frames / fps, 2), "animation": overlay.get("motion"),
                "text": str(overlay.get("text") or ""), "overlays": [chosen_id],
                "data": {k: overlay[k] for k in ("value", "suffix", "items") if k in overlay},
                "mapData": {"locations": overlay.get("locations")} if overlay.get("locations") else None,
                "chartData": {"items": overlay.get("items")} if overlay.get("items") and chosen["category"] in ("CHARTS", "COMPARISONS", "TIMELINES") else None,
                "sfx": (sfx if sfx.get("name") not in (None, "none") else None),
            })
            if i in hooks:
                entry["emphasis"] = "high"
        treatments.append(entry)

        archival = media_kind == "video" and scene.get("treatment") in ("archival", "vintage")
        if archival and not prev_archival and chosen is None:
            tag = _archive_tag(scene, style, pack, fps, start, scene_frames, total)
            if tag:
                overlays.append(tag)
        prev_archival = archival
        if (media_kind == "video" and at - last_window >= WINDOW_GAP and _FOOTAGE_WORDS.search(seg.text or "")
                and not (chosen and chosen.get("kind") in CARD_KINDS) and scene_frames >= fps * 2.5):
            # "Footage shows...": the clip plays in a player window on the desk.
            scene["frame"] = "window"
            last_window = at

    sfx = _plan_sfx(overlays, treatments, fps, float(pack.get("sfxIntensity", 1.0)))
    music = _plan_music(segments, brief, fps, total, hooks)
    for i, entry in enumerate(treatments):
        cue = next((s["mood"] for s in music["sections"] if s["startFrame"] <= scenes[i].get("startFrame", 0) < s["endFrame"]), None) if i < len(scenes) else None
        entry["musicCue"] = cue
    return {"overlays": overlays, "treatments": treatments, "sfx": sfx, "music": music,
            "counts": counts(scenes, overlays, sfx, music, treatments)}


def _plan_sfx(overlays: List[dict], treatments: List[dict], fps: int, intensity: float) -> List[dict]:
    """One sound per graphic moment at most every SFX_GAP seconds, the strongest moment winning."""
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
        picks.append({"name": s["name"], "startFrame": int(ov["startFrame"]),
                      "volume": round(min(1.0, float(s["volume"]) * intensity), 3), "_e": e})
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

_PHOTO_CYCLE = ["PHOTO_CARD_V1", "PHOTO_GRID_V1", "PHOTO_WINDOW_V1", "PHOTO_STACK_V1", "PHOTO_BOARD_V1",
                "PHOTO_EVIDENCE_V1"]
_PERSON_CYCLE = ["PERSON_CARD_V1", "PHOTO_BOARD_V1"]
_PLACE_CYCLE = ["PLACE_CARD_V1", "PHOTO_WINDOW_V1"]
_OBJECT_CYCLE = ["OBJECT_CARD_V1", "PHOTO_BOARD_V1", "PHOTO_EVIDENCE_V1"]
_photo_turn = [0]
_kind_turn = {"person": [0], "place": [0], "object": [0]}


def _turn(kind: str, cycle: List[str]) -> str:
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
    if kind == "person" and subject:
        return _turn("person", _PERSON_CYCLE), {"text": subject}
    if kind in ("place", "location", "landmark") and subject:
        tid = _turn("place", _PLACE_CYCLE)
        locs = hint.get("locations") if hint.get("type") == "map" else None
        if tid == "PLACE_CARD_V1" and locs:
            return tid, {"text": subject, "locations": locs[:1]}
        return tid, {"text": subject}
    if kind in ("object", "document", "thing", "artifact") and subject:
        return _turn("object", _OBJECT_CYCLE), {"text": subject}
    tid = _PHOTO_CYCLE[_photo_turn[0] % len(_PHOTO_CYCLE)]
    _photo_turn[0] += 1
    return tid, ({"text": subject.upper()} if subject else {})
_WEAK_REASONS = ("Best available", "Reused shot", "Repeat of an earlier shot", "No usable clip",
                 "No footage found")


DATA_CATEGORIES = {"CHARTS", "COMPARISONS", "TIMELINES", "MAPS", "DOCUMENTS"}


def _voice_window(seg, props: dict, hold: float, min_hold: float = MIN_HOLD) -> tuple:
    """
    (in, out) seconds for a graphic on this line: in when the word carrying
    what it shows is spoken (the figure's digits, the date, the quoted words;
    the line's start otherwise), out just after the line ends, clamped to
    MIN_HOLD .. hold + HOLD_SLACK.
    """
    words = list(getattr(seg, "words", None) or [])
    start = float(seg.start)
    t_in = start
    key = ""
    v = props.get("value") if isinstance(props, dict) else None
    if v is not None:
        try:
            key = str(int(float(v))) if float(v).is_integer() else str(v)
        except (TypeError, ValueError):
            key = ""
    elif isinstance(props, dict) and props.get("text"):
        first = str(props["text"]).split()[0] if str(props["text"]).split() else ""
        key = first if len(first) >= 3 else ""
    if key and words:
        norm = lambda w: re.sub(r"[^0-9a-z.]", "", str(w).lower())
        target = norm(key)
        for w in words:
            wt = norm(getattr(w, "text", "") if not isinstance(w, dict) else w.get("text", ""))
            if target and (wt == target or wt.startswith(target) or (len(target) > 2 and target in wt)):
                ws = getattr(w, "start", None) if not isinstance(w, dict) else w.get("start")
                if ws is not None:
                    t_in = max(start, float(ws) - PRE_ROLL)
                break
    t_out = float(seg.end) + TAIL
    dur = max(min_hold, min(t_out - t_in, hold + HOLD_SLACK))
    return t_in, t_in + dur


def _figure_key(cue: dict) -> Optional[tuple]:
    """The figure a cue draws, for repeat checks: ("figure", 26.0)."""
    v = (cue.get("props") or {}).get("value")
    if cue.get("cue") in ("percent", "change", "change-length", "big-number", "money", "measurement", "ratio") \
            and v is not None:
        try:
            return ("figure", float(v))
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
            options = [t for t in templates.for_cue(cue["cue"], pack.get("id", "")) if t["kind"] in CARD_KINDS]
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
