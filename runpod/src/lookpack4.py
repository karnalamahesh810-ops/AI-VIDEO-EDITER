"""
Looks pack 4's planner rules (2026-10-08, the owner: "it's not a weather channel creating tool ... it needs to do
everything"). Twelve general looks for every faceless niche - history, finance and business, tech, true crime,
travel, food, sports, science, biography, education, gaming, health - in the kinetic-type system (remotion
src/components/lib/LibKtPack4.tsx and LibKtCards4.tsx; registry family "ktp4", scripts/library_looks_ktpack4.json),
each picked only where the narration says what it shows, with the narration's own words and figures:

  KT_PRICE      a price said over time ("Bitcoin went from $1,000 in 2017 to nearly $20,000 by December, then
                crashed to $3,200"): a market line through the said prices, each point on its word, the peak or the
                crash called out, the change in a pill
  KT_MONEY      a big sum of money ("Facebook paid $1 billion for Instagram"): digit reels roll and land, the
                currency and the scale word (BILLION), one line of what it was
  KT_TABLE      two sides compared on two to four things ("Messi scored 672 goals in 778 games; Ronaldo 701 goals
                in 1,000 games", "In 1970 gas cost 36 cents and a car $3,500. Today gas is $3.50 and a car
                $48,000"): a table whose cells land on their words
  KT_PROSCONS   the upsides and the downsides said ("The upside: lower fees and faster transfers. The downside:
                volatility"): two columns, each point on its word
  KT_PROFILE    a person introduced with facts ("Steve Jobs, the co-founder of Apple, was born in 1955 in San
                Francisco"; "Sarah Collins, 34, a nurse from Dayton"): an ID card, the portrait from the scene
                picture when the scene shows that person (else the initials), the role, the facts on their words
  KT_STEPS      steps said in order ("First, ... Second, ... Third, ..."; "Step one: ..."): a numbered list
                landing step by step (said close together), or one card per step with the steps so far
  KT_CHAIN      a chain of causes ("Rising rates led to falling prices, which triggered a wave of defaults"):
                nodes joined by arrows, each consequence on its word
  KT_CASE       a crime or a mystery with its facts (date, place, status: "remains unsolved"): a case file, the
                status stamped on its word
  KT_POST       a social post quoted ("In 2018 Elon Musk tweeted: "Funding secured.""): a platform-neutral post
                card - the name as said, a handle only when one is said, the likes only when they are said
  KT_FACTCHECK  a claim and its verdict ("You may have heard that we only use 10 percent of our brains. That's a
                myth."): the claim, a FALSE / TRUE / MISLEADING stamp on the verdict word, the fact under it
  KT_PODIUM     a top three ("Bolt took gold, Blake silver and Gatlin bronze"; "the three richest men are ..."):
                podium blocks rising on each name
  KT_VERSUS     a head-to-head ("Real Madrid beat Barcelona 3-1", "Obama won 365 electoral votes to McCain's
                173", "50,000 Carthaginians against 86,000 Romans"): a scoreboard split, the winner in the accent

One pass with looks pack 3 (find): both packs' candidates; of two over the same words the more specific look wins
(SPECIFIC) - unless its spacing refuses it, then the next one over those words may take the moment; then time order
with one shared pace (Pace: a pack-3 or pack-4 look at least GAP seconds after another, at most PER_MINUTE in a
minute, each look its own EVERY spacing and its per-video MAX). Pure functions: no network, no paid calls.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import lookpack3 as p3
from .lookpack3 import _NUM, _YEAR, _cand, _cap, _clean, _fmt, _sentences, _time, _words_after, number_of

PRICE = "KT_PRICE"
MONEY = "KT_MONEY"
TABLE = "KT_TABLE"
PROSCONS = "KT_PROSCONS"
PROFILE = "KT_PROFILE"
STEPS = "KT_STEPS"
CHAIN = "KT_CHAIN"
CASE = "KT_CASE"
POST = "KT_POST"
FACTCHECK = "KT_FACTCHECK"
PODIUM = "KT_PODIUM"
VERSUS = "KT_VERSUS"
IDS = (PRICE, MONEY, TABLE, PROSCONS, PROFILE, STEPS, CHAIN, CASE, POST, FACTCHECK, PODIUM, VERSUS)
# The two cut transitions of the pack (remotion/src/transitions/TransitionFrame.tsx; src/timeline.py cycles).
TRANSITIONS = ("card-zoom", "shutter")


def variant_of(tid: str) -> str:
    """KT_FACTCHECK -> 'kt-factcheck'."""
    return "kt-" + tid[3:].lower().replace("_", "-")


# --------------------------------------------------------------------------- pace (shared with pack 3)
GAP = p3.PACK3_GAP          # seconds between two pack looks (pack 3 or 4)
WINDOW = p3.PACK3_WINDOW    # ... and at most PER_MINUTE of them in any such window
PER_MINUTE = p3.PACK3_PER_MINUTE
# Each look's own spacing (seconds from its last start): a person's card or a step may come back sooner than a table.
EVERY: Dict[str, float] = {PRICE: 90.0, MONEY: 75.0, TABLE: 120.0, PROSCONS: 150.0, PROFILE: 45.0, STEPS: 30.0,
                           CHAIN: 90.0, CASE: 120.0, POST: 60.0, FACTCHECK: 60.0, PODIUM: 120.0, VERSUS: 75.0}
# ... and at most this many in a video (the owner: "don't use the same one repeatedly").
MAX_PER_VIDEO: Dict[str, int] = {PRICE: 5, MONEY: 8, TABLE: 4, PROSCONS: 3, PROFILE: 8, STEPS: 10, CHAIN: 5, CASE: 4,
                                 POST: 5, FACTCHECK: 5, PODIUM: 3, VERSUS: 5}
REPEAT = p3.REPEAT          # the same thing said again this soon is not shown again
PROFILE_REPEAT = 1e9        # a person's card once a video


class Pace(p3.Pace):
    """
    The one spacing of looks pack 3 and pack 4 (one list of placed looks): a pack-4 look keeps GAP seconds from any
    pack look, at most PER_MINUTE in a minute, its own EVERY and MAX_PER_VIDEO; pack 3's own rules are unchanged
    and see the pack-4 looks in the same list.
    """

    def allows(self, tid: str, at: float) -> bool:
        if tid not in IDS:
            return super().allows(tid, at)
        if any(abs(at - t) < GAP for _x, t in self.placed):
            return False
        if sum(1 for _x, t in self.placed if abs(at - t) < WINDOW) >= PER_MINUTE:
            return False
        mine = [t for x, t in self.placed if x == tid]
        if len(mine) >= MAX_PER_VIDEO.get(tid, 6):
            return False
        return all(abs(at - t) >= EVERY.get(tid, 60.0) for t in mine)

    def note(self, tid: str, at: float) -> None:
        if tid in IDS:
            self.placed.append((tid, float(at)))
        else:
            super().note(tid, at)


# --------------------------------------------------------------------------- timing (seconds)
# When a look has landed, from its first frame (the renderer's frames / 30): its entry, then its own move. A look
# whose parts land on their words (items[].at) lands when its last part has (LEG after its word).
LAND = {PRICE: 1.3, MONEY: 1.6, TABLE: 1.0, PROSCONS: 1.0, PROFILE: 1.3, STEPS: 1.0, CHAIN: 1.0, CASE: 1.3, POST: 1.6,
        FACTCHECK: 1.2, PODIUM: 1.1, VERSUS: 1.6}
LEG = {PRICE: 0.9, TABLE: 0.6, PROSCONS: 0.6, PROFILE: 0.6, STEPS: 0.7, CHAIN: 0.8, CASE: 0.9, FACTCHECK: 0.9,
       PODIUM: 0.8, VERSUS: 1.3}
# The hold once landed: long enough to read it (the owner: about two seconds after its word; a table, a post or a
# claim a little longer to be read), then the 12-frame exit.
HOLD = {PRICE: 3.0, MONEY: 2.6, TABLE: 3.2, PROSCONS: 3.0, PROFILE: 3.0, STEPS: 2.6, CHAIN: 2.8, CASE: 3.0, POST: 3.0,
        FACTCHECK: 3.0, PODIUM: 3.0, VERSUS: 3.0}
WANT_EXTRA = 1.0
FAMILY = {PRICE: "chart", MONEY: "number", TABLE: "compare", PROSCONS: "compare", PROFILE: "person", STEPS: "text",
          CHAIN: "annotation", CASE: "document", POST: "text", FACTCHECK: "text", PODIUM: "chart", VERSUS: "compare"}
# The lane's priority (datalooks.schedule; maps 90, dates 86, charts 85, documents 84, figures 76, text 40).
PRIORITY = {PRICE: 85.0, MONEY: 77.0, TABLE: 82.0, PROSCONS: 76.0, PROFILE: 72.0, STEPS: 74.0, CHAIN: 70.0, CASE: 80.0,
            POST: 74.0, FACTCHECK: 78.0, PODIUM: 84.0, VERSUS: 82.0}


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
    if tid == POST:
        # the post is read while it is said: it lands when the quote has been said
        try:
            land = max(land, float(ov.get("_said_s") or 0.0) + 0.3)
        except (TypeError, ValueError):
            pass
    return round(land, 3)


def min_seconds(ov: dict, exit_s: float = 0.4) -> float:
    tid = str(ov.get("template") or "")
    return round(landing_seconds(ov) + HOLD.get(tid, 2.6) + exit_s, 3)


# --------------------------------------------------------------------------- words
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_SHORT = {m: m[:3] for m in _MONTHS.split("|")}
_SMALL = {"of", "the", "a", "an", "to", "for", "and", "in", "on", "its", "by", "that", "with", "from", "at", "is",
          "was", "as", "it", "their", "his", "her", "our", "than", "or", "but", "so", "were", "are", "be", "this",
          "which", "who", "your", "my", "into", "over", "about", "then", "very", "just"}
# A person's (or a team's) name: two to four capitalised words ("Steve Jobs", "Real Madrid", "Martin Luther King Jr.",
# "John McCain", "Shaquille O'Neal"); never the possessive's "'s" (it is not part of the name)
_CAPW = r"(?:[A-Z][a-z]+(?:[A-Z][a-z]+)*|[A-Z]['’][A-Z][a-z]+|[A-Z]\.|[A-Z]{2,5})(?:-[A-Z][a-z]+)?"
_LINK = r"(?:de|da|van|von|bin|al|del|la|le|du|di|Jr\.?|Sr\.?|III|II)"
_NAME2 = rf"(?<![\w'’]){_CAPW}(?:\s+(?:{_CAPW}|{_LINK})){{1,3}}"
# One word is a name too for a team or a known surname ("Messi", "Ronaldo", "Barcelona")
_NAME1 = rf"(?<![\w'’]){_CAPW}(?:\s+(?:{_CAPW}|{_LINK})){{0,3}}"
# A product or a model ("iPhone 15", "Pixel 8", "Galaxy S24 Ultra", "Model 3"): a name with its model words
_PRODUCT = rf"(?<![\w'’])(?:i[A-Z][a-z]+|{_CAPW})(?:\s+(?:{_CAPW}|[A-Z]?\d{{1,4}}[A-Za-z]?|Pro|Max|Plus|Ultra|Mini|Lite)){{0,3}}"
_NOT_PERSON_WORD = re.compile(
    r"\b(?:University|College|School|Institute|Company|Corporation|Corp|Inc|Group|Bank|Party|River|Lake|County|City|"
    r"Street|Avenue|Road|Church|War|Army|Navy|House|Court|Times|Post|Journal|News|Museum|Park|Valley|Mountains?|"
    r"Island|Islands|Bay|Ocean|Sea|Department|Agency|Bureau|Committee|Council|Senate|Congress|Revolution|Empire|"
    r"Republic|Kingdom|States|Union|Airport|Station|Bridge|Tower|Center|Centre|Hospital|Prison|Foundation|Award|"
    r"Prize|Games|Olympics|Cup|League|Series|Bowl|Championship|Festival|Day|Act|Treaty|Office|Market|Exchange|"
    r"Street|Square|Hall|Hotel|Stadium|Arena|Theater|Theatre|Capitol|Mall|Studios?|Records|Press|Books)\b")
_NOT_FIRST = p3._NOT_NAME | {"Back", "Today", "Yesterday", "Meanwhile", "However", "Still", "Even", "After", "Before",
                             "During", "Since", "Until", "While", "Although", "Though", "Because", "Once", "Later",
                             "Earlier", "Soon"} | set(_MONTHS.split("|"))
_PLACES = set(p3.US_STATES) | set(p3.COUNTRIES)


def _is_place(name: str) -> bool:
    """A state or a country, or "Town, State" / "City, Country" (the part after the comma one of those)."""
    name = name.strip(" ,.")
    if name in _PLACES or name.split(",")[0].strip() in _PLACES:
        return True
    parts = [p.strip() for p in name.split(",")]
    return len(parts) == 2 and parts[1] in _PLACES


def _person_ok(name: str) -> bool:
    """A name that can be a person's: two to four words, not a place, an organisation, a month or a sentence head."""
    words = name.split()
    if not 2 <= len(words) <= 4 or len(name) > 36:
        return False
    if words[0] in _NOT_FIRST or _is_place(name) or _NOT_PERSON_WORD.search(name):
        return False
    return not any(w.isupper() and len(w) > 3 for w in words)


def _who_ok(name: str) -> bool:
    """A side's name (a person, a team, a country, an army): one to four capitalised words, not a sentence head."""
    words = name.split()
    if not 1 <= len(words) <= 4 or len(name) > 32:
        return False
    return words[0] not in _NOT_FIRST and words[0].lower() not in _SMALL


def _trim_tail(words: List[str]) -> List[str]:
    while words and words[-1].lower().strip(",.;:") in _SMALL:
        words = words[:-1]
    return words


def _phrase(s: str, most: int = 6) -> str:
    """A short phrase as said: the first clause, at most `most` words, never ending on a small word."""
    s = re.split(r"[.;:!?]|,\s|\s[-–—]\s", s or "")[0]
    words = _trim_tail(s.split()[:most])
    return _cap(" ".join(words))


# --------------------------------------------------------------------------- money
_SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9,
           "trillion": 1e12, "tn": 1e12, "t": 1e12}
_CUR_WORD = {"dollar": "$", "dollars": "$", "bucks": "$", "euro": "€", "euros": "€", "yen": "¥", "rupees": "₹"}
_MONEY = re.compile(
    r"(?<![\w$€£¥₹.,])(?P<cur>[$€£¥₹])\s?(?P<n>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<sw>thousand|million|billion|trillion)\b|(?P<sl>k|mn|bn|tn|m|b|t)\b)?"
    r"|(?<![\w$€£¥₹.,])(?P<n2>\d[\d,]*(?:\.\d+)?)(?:\s+(?P<sw2>thousand|million|billion|trillion))?\s+"
    r"(?P<cw>dollars?|bucks|euros?|yen|rupees)\b"
    r"|(?<![\w.,$])(?P<c>\d{1,2})\s+cents\b", re.I)


def money_in(text: str, offset: int = 0) -> List[dict]:
    """Every sum of money a text says: {a, b, value (in units), n (as said), scale word, cur}."""
    out = []
    for m in _MONEY.finditer(text or ""):
        if m.group("c"):
            v = number_of(m.group("c"))
            if v is None:
                continue
            out.append({"a": offset + m.start(), "b": offset + m.end(), "value": v / 100.0, "n": v, "scale": "cents",
                        "cur": "$", "va": offset + m.start()})
            continue
        raw = m.group("n") or m.group("n2")
        v = number_of(raw)
        if v is None:
            continue
        sw = (m.group("sw") or m.group("sw2") or m.group("sl") or "").lower()
        cur = m.group("cur") or _CUR_WORD.get((m.group("cw") or "").lower(), "$")
        word = {"k": "thousand", "m": "million", "mn": "million", "b": "billion", "bn": "billion", "t": "trillion",
                "tn": "trillion"}.get(sw, sw)
        out.append({"a": offset + m.start(), "b": offset + m.end(), "value": v * _SCALES.get(sw, 1.0), "n": v,
                    "scale": word, "cur": cur, "va": offset + m.start()})
    return out


def _scale_for(values: Sequence[float]) -> Tuple[float, str]:
    """The one display scale for a series of sums: (divisor, letter) - B for billions, M for millions, else none."""
    top = max(abs(v) for v in values) if values else 0.0
    for div, letter in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if top >= div:
            return div, letter
    return 1.0, ""


def _round(v: float) -> float:
    return _fmt(round(float(v), 3))


# --------------------------------------------------------------------------- time words
_TIME_AFTER = re.compile(rf"^[^.;$€£¥₹\d]{{0,26}}?\b(?:in|by|of|during|around|back\s+in)\s+(?:early\s+|late\s+|mid-?)?"
                         rf"(?P<t>(?:{_MONTHS})(?:\s+(?:1[89]|20)\d\d)?|(?:1[89]|20)\d\d)\b")
_TIME_BEFORE = re.compile(rf"\b(?:in|by|of|during|around)\s+(?:early\s+|late\s+|mid-?)?(?P<t>(?:{_MONTHS})"
                          rf"(?:\s+(?:1[89]|20)\d\d)?|(?:1[89]|20)\d\d)\b[^.;$€£¥₹\d]{{0,40}}$")
_NOW = re.compile(r"\b(today|now|these\s+days|nowadays|at\s+its\s+peak|by\s+the\s+end)\b", re.I)


def _time_label(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    m = re.match(rf"({_MONTHS})(?:\s+((?:1[89]|20)\d\d))?$", t)
    if m:
        return f"{_MONTH_SHORT[m.group(1)]} {m.group(2)}" if m.group(2) else _MONTH_SHORT[m.group(1)]
    return t


# --------------------------------------------------------------------------- KT_PRICE
_PRICE_CTX = re.compile(
    r"\b(prices?|priced|stocks?|shares?|traded|trading|trades|valuation|valued|market\s+(?:cap|capitalization|value)|"
    r"worth|bitcoin|ethereum|crypto(?:currency|currencies)?|tokens?|gold|silver|oil|gas|gasoline|housing|homes?|"
    r"houses?|rent|index|dow|nasdaq|s&p|ipo|listed|opened|closed|peaked|bottomed|all[- ]time\s+high|record\s+high|"
    r"crashed|soared|plunged|plummeted|tanked|rallied|cost|costs|sold\s+for|went\s+for|ticket|tuition|salary|wages?)\b",
    re.I)
_PEAK = re.compile(r"\b(all[- ]time\s+high|record\s+high|peak(?:ed|ing)?|high\s+of|topped\s+out|hit\s+a\s+high|"
                   r"record\s+of)\b[^$€£¥₹\d]{0,22}$", re.I)
_CRASH = re.compile(r"\b(crash(?:ed|ing)?|collaps(?:ed|ing)|plunged|plummeted|tanked|cratered|bottomed(?:\s+out)?|"
                    r"low\s+of|fell|dropped|sank|slid|tumbled)\b[^$€£¥₹\d]{0,22}$", re.I)
_PRICE_TITLE = re.compile(r"\b((?:[A-Z][\w&.'’-]*)(?:\s+[A-Z][\w&.'’-]*){0,2})(?:['’]s)?\s+(stock|shares|share\s+price|"
                          r"stock\s+price|price|valuation|market\s+cap)\b")
# "A Big Mac cost $0.45 ...", "The first iPhone sold for $499": the thing and its price
_THING_COST = re.compile(rf"\b(?:(?i:an?|the)\s+(?:(?i:first|original|average|new)\s+)?)?(?P<n>{_PRODUCT})\s+"
                         r"(?:cost|costs|sold\s+for|sells\s+for|went\s+for|was\s+priced\s+at|traded\s+at|retailed\s+for)\b")
_PRICE_OF = re.compile(r"\b(?:the\s+)?(?:average\s+)?(price|cost)\s+of\s+(?:an?\s+|the\s+)?((?:[a-z]+\s+){0,2}?[a-z]+)\b",
                       re.I)
_COMMODITY = re.compile(r"\b(bitcoin|ethereum|dogecoin|gold|silver|oil|gasoline|gas|bread|eggs|rent|tuition)\b", re.I)


def _price_title(win: str) -> str:
    m = _PRICE_TITLE.search(win)
    if m and m.group(1).split()[0] not in _NOT_FIRST:
        kind = re.sub(r"\s+", " ", m.group(2).lower())
        name = m.group(1)
        return f"{name} {kind}" if len(name) <= 22 else kind.capitalize()
    m = _THING_COST.search(win)
    if m and m.group("n").split()[0] not in _NOT_FIRST and len(m.group("n")) <= 22:
        return f"{m.group('n')} price"
    m = _PRICE_OF.search(win)
    if m:
        what = m.group(2).strip()
        if what.split()[-1].lower() not in _SMALL and len(what) <= 24:
            return _cap(f"{what} {m.group(1).lower()}")
    m = _COMMODITY.search(win)
    if m:
        w = m.group(1).lower()
        return w.capitalize() if w in ("bitcoin", "ethereum", "dogecoin") else f"{w.capitalize()} price"
    return "Price"


# The words of a price moving over time - never the thing priced ("went from ... then crashed to ... by December").
_SERIES_WORDS = {"price", "prices", "stock", "stocks", "share", "shares", "value", "valuation", "worth", "trading", "traded",
                 "high", "low", "peak", "record", "all-time", "time", "crashed", "crash", "dropped", "fell", "rose",
                 "climbed", "soared", "went", "from", "to", "nearly", "then", "later", "year", "years", "month", "months",
                 "week", "weeks", "day", "days", "before", "after", "collapsing", "collapsed", "peaked", "plunged",
                 "plummeted", "tanked", "rallied", "jumped", "surged", "sank", "slid", "tumbled", "bottomed", "out",
                 "hit", "reached", "touched", "topped", "again", "once", "back", "down", "up", "low", "lows", "highs",
                 "early", "late", "mid", "end", "start", "beginning", "following", "next", "same", "that", "this",
                 "today", "now", "less", "more", "than", "almost", "barely", "nearly", "roughly", "about", "around",
                 "above", "below", "under", "over", "of", "per", "each", "every", "trade", "trades", "closing",
                 "opening", "opened", "closed", "ipo", "listing", "listed", "debut", "debuted", "market", "cap"}


def _owner_before(text: str, start: int, a: int) -> str:
    """The proper name a figure belongs to when one stands right before it ("Apple, $3 trillion"), else ''."""
    chunk = text[start:a]
    m = re.search(rf"({_NAME1})(?:['’]s)?\s*(?:,|:|\(|—|–)?\s*(?:(?:is|was|at|with|has|had|worth|valued\s+at)\s+)?"
                  rf"(?:(?:about|nearly|almost|over|around|just)\s+)?$", chunk)
    if not m:
        return ""
    name = m.group(1)
    return "" if name.split()[0] in _NOT_FIRST else name


def find_prices(nar) -> List[dict]:
    out = []
    text = nar.text
    sents = _sentences(nar)
    done_until = -1
    for i, (s0, s1) in enumerate(sents):
        if s0 < done_until:
            continue
        w1 = s1
        if i + 1 < len(sents) and _time(nar, sents[i + 1][0]) - _time(nar, s0) < 15.0:
            w1 = sents[i + 1][1]
        win = text[s0:w1]
        if not _PRICE_CTX.search(win):
            continue
        sums = [m for m in money_in(win, s0) if m["scale"] != "cents" or True]
        if len(sums) < 2 or len(sums) > 6 or len({m["cur"] for m in sums}) != 1:
            continue
        # a series of one subject: figures owned by different names are a ranking, not a price over time
        owners = set()
        prev = s0
        for m in sums:
            o = _owner_before(text, prev, m["a"])
            if o:
                owners.add(o)
            prev = m["b"]
        if len(owners) >= 2:
            continue
        # ... and figures of different things ("a gallon of gas ... a new car ... the average home") are a table
        things = set()
        prev = s0
        for m in sums:
            chunk = re.split(r"[,;:]|\band\b", text[prev:m["a"]])[-1]
            cw = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]*", chunk)
                  if w.lower() not in _VERBISH and w.lower() not in _SERIES_WORDS and w not in _MONTHS.split("|")]
            if cw:
                things.add(_lemma(cw[-1]))
            prev = m["b"]
        if len(things) >= 2:
            continue
        callouts: Dict[int, str] = {}
        for j, m in enumerate(sums):
            head = text[max(s0, m["a"] - 40):m["a"]]
            pk, cr = _PEAK.search(head), _CRASH.search(head)
            if pk:
                w = pk.group(1).lower()
                callouts[j] = "All-time high" if "all" in w else "Record high" if "record" in w else "Peak"
            elif cr:
                w = cr.group(1).lower()
                callouts[j] = "Crash" if re.match(r"crash|collaps|plung|plummet|tank|crater", w) else "Low"
        if len(sums) < 3 and not callouts:
            continue
        labels = []
        used = s0                               # (a time said after one figure is that figure's, never the next one's)
        for j, m in enumerate(sums):
            nxt = sums[j + 1]["a"] if j + 1 < len(sums) else w1
            after = _TIME_AFTER.search(text[m["b"]:nxt])
            lab = after.group("t") if after else ""
            if after:
                used = m["b"] + after.end()
            if not lab:
                before = _TIME_BEFORE.search(text[max(used, (sums[j - 1]["b"] if j else s0)):m["a"]])
                lab = before.group("t") if before else ""
            if not lab and j == len(sums) - 1 and _NOW.search(text[max(s0, m["a"] - 30):min(w1, m["b"] + 30)]):
                lab = "Today"
            labels.append(_time_label(lab))
        div, letter = _scale_for([m["value"] for m in sums])
        t0 = _time(nar, sums[0]["a"]) - 0.07
        items, ats = [], []
        for j, m in enumerate(sums):
            at = _time(nar, m["a"])
            it = {"label": labels[j], "value": _round(m["value"] / div), "at": round(max(0.0, at - t0), 2)}
            if j in callouts:
                it["text"] = callouts[j]
            items.append(it)
            ats.append(at)
        if len({it["value"] for it in items}) < 2:
            continue
        props = {"template": PRICE, "text": _price_title(win), "items": items, "prefix": sums[0]["cur"],
                 "suffix": letter}
        a, b = sums[0]["a"], sums[-1]["b"]
        out.append(_cand(PRICE, nar, a, b, props, ats, score=6.0 + 0.3 * len(sums),
                         key="pr:" + "|".join(str(it["value"]) for it in items), absorb=(s0, b), at=t0 + 0.07))
        done_until = b
    return out


# --------------------------------------------------------------------------- KT_MONEY
_MONEY_HEDGE = re.compile(r"\b(nearly|almost|about|around|roughly|over|more\s+than|less\s+than|under|close\s+to|"
                          r"at\s+least|up\s+to|just\s+over|just\s+under)\s+$", re.I)


_MONEY_VERB = re.compile(r"\s+(?:will\s+|would\s+|could\s+|has\s+|have\s+|had\s+|is\s+|was\s+|were\s+|are\s+)?(?:now\s+|still\s+|"
                         r"reportedly\s+|eventually\s+|finally\s+)?(?:cost|costs|costing|paid|pays|spent|spends|raised|raises|lost|"
                         r"loses|earned|earns|made|makes|sold\s+for|bought\s+for|went\s+for|valued\s+at|worth|stole|took|netted|"
                         r"generated|brought\s+in|owed|owes|fined|charged|invested|received|got|won|cost\s+taxpayers|totaled|"
                         r"totalled|reached|hit|be|been)\b.*$", re.I)


def _money_subject(text: str, s0: int, a: int, keep_the: bool = False) -> str:
    """
    What a sum belongs to, from its clause's own subject ("The Obama Presidential Center will cost about ..." ->
    "Obama Presidential Center"; with keep_the "The Obama Presidential Center"): the words before the verb, at most
    five, never a pronoun; '' when the clause does not say.
    """
    head = re.split(r"[;:,]\s*|\b(?:and|but|while|then|which|who)\b", text[s0:a])[-1]
    m = _MONEY_VERB.search(head)
    if not m:
        return ""
    words = head[:m.start()].split()
    if not keep_the:
        while words and words[0].lower() in ("the", "a", "an", "its", "their", "his", "her", "this", "that"):
            words = words[1:]
    if not words or len(words) > 5 or words[-1].lower() in _SMALL:
        return ""
    if words[0].lower() in ("it", "they", "he", "she", "we", "you", "i", "this", "that", "there", "which", "who"):
        return ""
    return " ".join(words)


# the time a sentence opens with ("In 2012, ...", "In August 2018, ...", "On June 4, 1998, ..."): a look over the
# rest of that sentence shows it (a big sum's line, a post's date, a claim's kicker), never a date look beside it.
# (Used with match(text, pos): no "^", which would only match at the text's very start.)
_LEAD_TIME = re.compile(rf"\s*(?P<p>(?:back\s+)?in|by|during|on)\s+(?:the\s+(?:night|morning|evening|afternoon|day)\s+"
                        rf"of\s+)?(?:early\s+|late\s+|mid-?)?(?P<t>(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+"
                        rf"(?:1[5-9]|20)\d\d|(?:{_MONTHS})\s+(?:1[5-9]|20)\d\d|(?:1[5-9]|20)\d\d)\b\s*,?\s*", re.I)


def _lead_time(text: str, s0: int, a: int) -> Tuple[str, str]:
    """The time its sentence (from `s0`) opens with, said before `a`: (the word before it as said - "in", "by",
    "on" -, the time as shown - "2012", "Aug 2018", "Jun 4, 1998"), or ("", "")."""
    m = _LEAD_TIME.match(text, s0, a)
    if not m:
        return "", ""
    p = re.sub(r"\s+", " ", m.group("p")).lower()
    return ("in" if p == "back in" else p), _date_text(m.group("t"))


def find_money(nar) -> List[dict]:
    out = []
    text = nar.text
    for s0, s1 in _sentences(nar):
        sums = money_in(text[s0:s1], s0)
        if len(sums) > 1:
            continue                            # two sums or more: a comparison, a change or a series (their looks)
        for m in sums:
            if m["value"] < 1e6 or m["scale"] == "cents":
                continue                        # a smaller sum is a figure (KT_NUMBER / KT_CHIP)
            v, word = m["n"], m["scale"]
            if not word:
                div, letter = _scale_for([m["value"]])
                word = {"T": "trillion", "B": "billion", "M": "million"}.get(letter, "")
                v = m["value"] / div
            hedge = _MONEY_HEDGE.search(text[max(s0, m["a"] - 16):m["a"]])
            hedge_w = re.sub(r"\s+", " ", hedge.group(1)).upper() if hedge else ""
            subject = p3._subject_before(text, s0, m["a"]) or _money_subject(text, s0, m["a"])
            ctx = _words_after(text, m["b"], 40)
            if ctx:
                # who as the kicker, what it was under the figure ("FACEBOOK" ... "For Instagram")
                label, sub = (subject.upper() if subject and len(subject) <= 28 else hedge_w), _cap(ctx)
            else:
                # nothing said after the sum: the hedge as the kicker, the thing it is under the figure
                label, sub = hedge_w, _cap(_money_subject(text, s0, m["a"], keep_the=True) or subject)
            # the year the sentence opens with ("In 2012, Facebook paid ...") is the card's: shown on it, never
            # a year look of its own beside it
            prep, when = _lead_time(text, s0, m["a"])
            lead = bool(when) and not re.search(r"(?:1[5-9]|20)\d\d", sub)
            if lead:
                if not label:
                    label = f"{prep} {when}".upper()
                elif len(sub) + len(when) <= 34:
                    sub = f"{sub}, {prep} {when}" if sub else _cap(f"{prep} {when}")
                else:
                    lead = False
            props = {"template": MONEY, "value": _round(v), "prefix": m["cur"], "suffix": word.upper(),
                     "label": label, "subtitle": sub}
            tail = text.find(ctx, m["b"]) if ctx else -1
            end = tail + len(ctx) if tail >= 0 else m["b"]
            out.append(_cand(MONEY, nar, m["a"], m["b"], props, None, score=4.0 + (1.0 if m["value"] >= 1e9 else 0.0),
                             key=f"mo:{m['value']:g}", absorb=(s0 if lead else m["a"], end)))
    return out


# --------------------------------------------------------------------------- KT_TABLE
_UNIT_AFTER = [(r"%|percent", "%"), (r"-?inch(?:es)?", "IN"), (r"gb|gigabytes?", "GB"), (r"tb|terabytes?", "TB"),
               (r"mb|megabytes?", "MB"), (r"mph", "MPH"), (r"km/h", "KM/H"), (r"-?megapixels?", "MP"),
               (r"mah", "MAH"), (r"hz", "HZ"), (r"kg|kilograms?", "KG"), (r"lbs", "LB"), (r"hours?", "HRS"),
               (r"minutes?", "MIN"), (r"years?", "YRS"), (r"km|kilomet(?:er|re)s?", "KM"), (r"miles?", "MI"),
               (r"feet|ft", "FT"), (r"meters?|metres?", "M")]
_UNIT_AFTER_RX = re.compile(r"^\s*(" + "|".join(u for u, _ in _UNIT_AFTER) + r")\b", re.I)
_FIG_PLAIN = re.compile(rf"(?<![\w$€£¥₹.,-])(?P<n>{_NUM})(?P<sc>\s+(?:thousand|million|billion))?(?![\w,.]?\d)")
_NOUN_AFTER = re.compile(r"^\s*(?:of\s+)?(?P<noun>[A-Za-z][A-Za-z-]{1,20}(?:\s+[A-Za-z][A-Za-z-]{1,20})?)")
_VERBISH = {"cost", "costs", "was", "were", "is", "are", "at", "for", "of", "had", "has", "have", "with", "about",
            "around", "nearly", "just", "only", "roughly", "over", "under", "sold", "went", "paid", "pays", "earned",
            "earns", "made", "makes", "hit", "reached", "scored", "scores", "a", "an", "the", "and", "but", "while",
            "whereas", "today", "now", "back", "then", "in", "by", "it", "its", "their", "his", "her", "costing",
            "priced", "selling", "sells", "ran", "runs", "gets", "got", "takes", "took", "weighs", "weighed",
            "lasted", "lasts", "holds", "held", "carries", "carried", "fielded", "fields", "boasts", "boasted",
            "offers", "offered", "packs", "packed", "comes", "came", "starts", "started"}
_NOUN_STOP = {"in", "on", "at", "for", "and", "but", "while", "whereas", "per", "a", "an", "the", "to", "than", "of",
              "with", "from", "by", "over", "across", "during", "each", "every", "his", "her", "its", "their"}
_SPLIT_FRAMES = re.compile(r";\s*|,?\s+\b(?:while|whereas|but|compared\s+(?:to|with)|versus|vs\.?)\s+", re.I)
_TIME_HEAD = re.compile(rf"^(?:[,\s]*(?:and|but|so|yet)\s+)?(?:(?:back\s+)?in\s+(?P<y>(?:1[5-9]|20)\d\d)|(?P<now>today|now|"
                        rf"these\s+days|nowadays))\b", re.I)


def _lemma(w: str) -> str:
    w = w.lower().strip(".,;:")
    for suf, rep in (("ies", "y"), ("ses", "s"), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)] + rep
    return w


def _frame_figures(text: str, a: int, b: int) -> List[dict]:
    """The figures of one side of a comparison, each with the thing it measures (the word after it, or before it)."""
    seg = text[a:b]
    figs = []
    for m in money_in(seg, a):
        figs.append({"a": m["a"], "b": m["b"], "value": m["n"] if m["scale"] in ("thousand", "million", "billion",
                                                                                   "trillion") else m["value"],
                     "prefix": m["cur"] if m["scale"] != "cents" else "", "suffix": {"thousand": "K", "million": "M",
                                                                                    "billion": "B", "trillion": "T",
                                                                                    "cents": "¢"}.get(m["scale"], ""),
                     "money": True, "n": m["n"]})
    taken = [(f["a"], f["b"]) for f in figs]
    for m in _FIG_PLAIN.finditer(seg):
        fa, fb = a + m.start(), a + m.end()
        if any(not (fb <= x or fa >= y) for x, y in taken):
            continue
        raw = m.group("n")
        if re.fullmatch(_YEAR, raw.replace(",", "")) and not m.group("sc"):
            continue                            # a year is a column's head, never a cell
        v = number_of(raw)
        if v is None:
            continue
        sc = (m.group("sc") or "").strip().lower()
        figs.append({"a": fa, "b": fb, "value": v, "prefix": "", "suffix": {"thousand": "K", "million": "M",
                                                                             "billion": "B"}.get(sc, ""),
                     "money": False, "n": v})
    figs.sort(key=lambda f: f["a"])
    prev = a
    for f in figs:
        # the unit right after it ("8 GB", "6.1-inch"), then the thing ("goals", "RAM", "screen")
        rest = text[f["b"]:b]
        um = _UNIT_AFTER_RX.match(rest)
        if um and not f["suffix"]:
            raw = um.group(1).lower()
            for rx, short in _UNIT_AFTER:
                if re.fullmatch(rx, raw, re.I):
                    f["suffix"] = short
                    break
            rest = rest[um.end():]
        nm = _NOUN_AFTER.match(rest)
        after = ""
        if nm:
            words = [w for w in nm.group("noun").split()]
            if words and words[0].lower() not in _NOUN_STOP:
                after = words[-1] if len(words) == 2 and words[1].lower() not in _NOUN_STOP else words[0]
                if len(words) == 2 and words[0].lower() in ("of",):
                    after = words[1]
        # the thing named before it ("a gallon of gas cost 36 cents", "the average home $23,000")
        chunk = re.split(r"[,;:]|\band\b", text[prev:f["a"]])[-1]
        cw = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", chunk) if w.lower() not in _VERBISH]
        before = cw[-1] if cw else ""
        f["after"] = after if after and after.lower() not in _NOUN_STOP and not after[0].isdigit() else ""
        f["before"] = before
        prev = f["b"]
    return figs


def _frame_head(text: str, a: int, b: int) -> Tuple[str, str, int]:
    """
    A side's head and where it ends: ('time', '1970' / 'Today', end) or ('name', 'Messi' / 'iPhone 15', end), from
    the side's first words; ('', '', a) when it has none.
    """
    head = text[a:b]
    m = _TIME_HEAD.search(head)
    if m:
        return ("time", m.group("y") if m.group("y") else "Today", a + m.end())
    y = re.search(r"\b(?:[Ii]n|[Bb]y)\s+((?:1[5-9]|20)\d\d)\b", head[:48])
    if y:
        return ("time", y.group(1), a + y.end())
    for nm in re.finditer(rf"({_PRODUCT})", head):
        name = nm.group(1)
        if name.split()[0] in _NOT_FIRST or name.lower() in _SMALL:
            continue
        if nm.start() > 60:
            break
        return ("name", name, a + nm.end())
    return ("", "", a)


def find_tables(nar) -> List[dict]:
    out = []
    text = nar.text
    sents = _sentences(nar)
    # the sides: each sentence, and a sentence's halves around "while" / "whereas" / ";" / "compared to"
    frames: List[Tuple[int, int]] = []
    for s0, s1 in sents:
        cuts = [s0] + [s0 + m.end() for m in _SPLIT_FRAMES.finditer(text[s0:s1])] + [s1]
        for x, y in zip(cuts, cuts[1:]):
            if y - x > 6:
                frames.append((x, y))
    used_until = -1
    for i in range(len(frames) - 1):
        (a0, a1), (b0, b1) = frames[i], frames[i + 1]
        if a0 < used_until or _time(nar, b1 - 1) - _time(nar, a0) > 24.0:
            continue
        ha, hb = _frame_head(text, a0, a1), _frame_head(text, b0, b1)
        if not ha[0] or ha[0] != hb[0] or ha[1].lower() == hb[1].lower():
            continue
        # (a figure inside the head is the head's own: "iPhone 15", "Model 3")
        fa = [f for f in _frame_figures(text, a0, a1) if f["a"] >= ha[2]]
        fb = [f for f in _frame_figures(text, b0, b1) if f["a"] >= hb[2]]
        if not 2 <= len(fa) <= 5 or not 1 <= len(fb) <= 5:
            continue
        # the rows: the things both sides give a figure for, in the first side's order
        best: List[Tuple[str, dict, dict]] = []
        for side in ("after", "before"):
            rows = []
            seen = set()
            for x in fa:
                k = _lemma(x[side]) if x[side] else ""
                if not k or k in seen:
                    continue
                y = next((y for y in fb if (_lemma(y["after"]) == k or _lemma(y["before"]) == k)), None)
                if y is not None:
                    rows.append((x[side], x, y))
                    seen.add(k)
            if len(rows) > len(best):
                best = rows
        if len(best) < 2:
            continue
        best = best[:4]
        t0 = _time(nar, min(r[1]["a"] for r in best)) - 0.07
        items, ats = [], []
        for col in (1, 2):
            for word, x, y in best:
                f = x if col == 1 else y
                at = _time(nar, f["a"])
                it = {"label": _cap(word.lower() if not word.isupper() else word), "value": _round(f["value"]),
                      "at": round(max(0.0, at - t0), 2)}
                if f["prefix"]:
                    it["prefix"] = f["prefix"]
                if f["suffix"]:
                    it["suffix"] = f["suffix"]
                items.append(it)
                ats.append(at)
        head_a = ha[1] if ha[0] == "name" else ha[1]
        props = {"template": TABLE, "text": f"{head_a} vs {hb[1]}", "items": items}
        if ha[0] == "time":
            props["label"] = "Then and now" if hb[1] == "Today" else ""
        a = min(r[1]["a"] for r in best)
        b = max(r[2]["b"] for r in best)
        out.append(_cand(TABLE, nar, a, b, props, ats, score=6.5 + 0.3 * len(best),
                         key="tb:" + "|".join(sorted(_lemma(r[0]) for r in best)) + f":{ha[1]}:{hb[1]}",
                         absorb=(a0, b1), at=t0 + 0.07))
        used_until = b1
    return out


# --------------------------------------------------------------------------- KT_PROSCONS
_PRO_MARK = re.compile(r"\b(?:(?:the|one|another|a|its|their|the\s+(?:big|main|biggest|other))\s+)?(?:(?:big|main|biggest|"
                       r"obvious|clear|real)\s+)?(?P<w>pros?|upsides?|advantages?|benefits?|plus(?:es)?|positives?|"
                       r"good\s+news)\b(?:\s+(?:of|to|for)\s+(?P<what>[^:.,;!?]{2,40}?)(?=\s*:|\s+(?:is|are|was|were|"
                       r"include|includes)\b))?(?:\s+(?:is|are|was|were|include|includes|here)\b)?\s*[:,-]?\s*(?:that\s+)?|"
                       r"\bon\s+the\s+(?:plus|bright|upside|positive)\s+side\s*,?\s*", re.I)
# what the pros are of, said before them ("Electric cars have clear benefits: ...")
_PRO_SUBJECT = re.compile(r"(?P<s>[A-Z][\w'’-]*(?:\s+[\w'’-]+){0,3}?)\s+(?:has|have|had|offers?|offered|brings?|brought)\s+"
                          r"(?:some\s+|many\s+|several\s+|a\s+few\s+|two\s+|three\s+)?$")
_CON_MARK = re.compile(r"\b(?:(?:the|one|another|a|its|their|the\s+(?:big|main|biggest|other))\s+)?(?:(?:big|main|biggest|"
                       r"obvious|real)\s+)?(?P<w>cons?|downsides?|disadvantages?|drawbacks?|negatives?|catch|bad\s+news|"
                       r"risks?)\b(?:\s+(?:is|are|was|were|include|includes|here)\b)?\s*[:,-]?\s*(?:that\s+)?|"
                       r"\bon\s+the\s+(?:minus|down|downside|negative|flip)\s+side\s*,?\s*", re.I)
_ITEM_LEAD = re.compile(r"^(?:that\s+|it(?:'s|\s+is)\s+|there(?:'s|\s+is|\s+are)\s+|you\s+get\s+|you(?:'ll)?\s+(?:have|pay)\s+|"
                        r"they(?:'re|\s+are)\s+|we\s+get\s+)", re.I)


def _list_items(s: str, most: int = 3) -> List[Tuple[str, int]]:
    """A list said after a marker ("lower fees, faster transfers and no middleman"): each item and its offset in s."""
    s = re.split(r"[.;!?]", s)[0]
    out = []
    pos = 0
    for part in re.split(r"(,\s*(?:and\s+|or\s+|plus\s+)?|\s+and\s+|\s+plus\s+|\s+or\s+)", s):
        if not part or re.fullmatch(r",\s*(?:and\s+|or\s+|plus\s+)?|\s+and\s+|\s+plus\s+|\s+or\s+", part):
            pos += len(part)
            continue
        raw = part
        lead = _ITEM_LEAD.match(raw)
        start = pos + (lead.end() if lead else 0)
        words = _trim_tail(raw[(lead.end() if lead else 0):].split()[:6])
        phrase = " ".join(words).strip(" ,")
        if phrase and len(phrase) >= 3 and not re.match(r"^(?:the|a|an)$", phrase, re.I):
            out.append((_cap(phrase), start + (len(raw[(lead.end() if lead else 0):]) - len(raw[(lead.end() if lead else 0):].lstrip()))))
        pos += len(part)
        if len(out) >= most:
            break
    return out


def find_proscons(nar) -> List[dict]:
    out = []
    text = nar.text
    pros = [m for m in _PRO_MARK.finditer(text)]
    cons = [m for m in _CON_MARK.finditer(text)]
    used = -1
    for pm in pros:
        if pm.start() < used:
            continue
        t_pro = _time(nar, pm.start())
        cm = next((c for c in cons if c.start() > pm.end() and _time(nar, c.start()) - t_pro <= 30.0), None)
        if cm is None:
            continue
        p_items = _list_items(text[pm.end():cm.start()])
        c_items = _list_items(text[cm.end():cm.end() + 220])
        if not p_items or not c_items or len(p_items) + len(c_items) < 3:
            continue
        t0 = t_pro - 0.07
        items, ats = [], []
        for (lab, off), base, sign in [(x, pm.end(), 1) for x in p_items] + [(x, cm.end(), -1) for x in c_items]:
            at = _time(nar, base + off)
            items.append({"label": lab, "value": sign, "at": round(max(0.0, at - t0), 2)})
            ats.append(at)
        title_m = re.search(r"\bpros\s+and\s+cons\s+of\s+([^.,;!?]{3,40})", text[max(0, pm.start() - 200):pm.start()], re.I)
        title = _phrase(title_m.group(1), 5) if title_m else ""
        if not title and pm.group("what"):
            title = _phrase(pm.group("what"), 5)                    # "The upside of electric cars: ..."
        if not title:
            ps0, _ps1 = nar.sentence(pm.start())
            sm = _PRO_SUBJECT.search(text[ps0:pm.start()])
            subj = sm.group("s") if sm else ""
            if subj and subj.split()[0].lower() not in ("it", "they", "this", "that", "there", "he", "she", "we", "you"):
                title = _phrase(re.sub(r"^(?:the|a|an)\s+", "", subj, flags=re.I), 5)
        last = cm.end() + max(off for _l, off in c_items) + 1
        end = text.find(".", last)
        b = end if end > 0 else min(len(text), last + 40)
        props = {"template": PROSCONS, "text": title, "items": items}
        out.append(_cand(PROSCONS, nar, pm.start(), b, props, ats, score=5.5,
                         key="pc:" + "|".join(sorted(it["label"].lower() for it in items)), at=t0 + 0.07))
        used = b
    return out


# --------------------------------------------------------------------------- KT_PROFILE
_BORN = re.compile(rf"\bborn\b(?:\s+(?:on|in)\s+(?P<when>(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:1[5-9]|20)\d\d|"
                   rf"(?:{_MONTHS})\s+(?:1[5-9]|20)\d\d|(?:1[5-9]|20)\d\d))?(?:,?\s+(?:in|at)\s+(?P<where>(?:[A-Z][a-z'’.-]+)"
                   rf"(?:\s+[A-Z][a-z'’.-]+){{0,2}}(?:,\s+[A-Z][a-z'’.-]+(?:\s+[A-Z][a-z'’.-]+)?)?))?(?:,?\s+(?:on|in)\s+"
                   rf"(?P<when2>(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:1[5-9]|20)\d\d|(?:{_MONTHS})\s+"
                   rf"(?:1[5-9]|20)\d\d|(?:1[5-9]|20)\d\d))?")
_DIED = re.compile(rf"\b(?:died|passed\s+away|was\s+killed|was\s+assassinated)\b(?:\s+(?:on|in)\s+(?P<when>(?:{_MONTHS})\s+"
                   rf"\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:1[5-9]|20)\d\d|(?:{_MONTHS})\s+(?:1[5-9]|20)\d\d|"
                   rf"(?:1[5-9]|20)\d\d))")
_LIFESPAN = re.compile(r"\(\s*((?:1[5-9]|20)\d\d)\s*[-–—]\s*((?:1[5-9]|20)\d\d)\s*\)")
_APPOS = re.compile(rf"(?P<name>{_NAME2}),\s+(?:(?P<age>\d{{1,2}}),\s+)?(?P<role>(?:a|an|the)\s+[^,.;()]{{3,60}}?)"
                    rf"(?=,|\s+who\b|\s+was\b|\s+is\b|\s+had\b|\.|;)")
_AGE_ROLE = re.compile(rf"\b(?P<age>\d{{1,2}})-year-old\s+(?:(?P<role>[a-z]+(?:\s+[a-z]+)?)\s+)?(?P<name>{_NAME2})")
_NAME_AGE = re.compile(rf"(?P<name>{_NAME2}),\s+(?P<age>\d{{1,2}}),")
_FROM = re.compile(r"\bfrom\s+(?P<p>[A-Z][a-z'’.-]+(?:\s+[A-Z][a-z'’.-]+){0,2}(?:,\s+[A-Z][a-z'’.-]+(?:\s+[A-Z][a-z'’.-]+)?)?)")
_ROLE_KICKER = re.compile(r"\b(?:the\s+)?(victim|suspect|killer|accused|defendant|witness|founder|inventor|ceo|president|"
                          r"leader|commander|general|captain|coach)\b", re.I)


def _date_text(s: str) -> str:
    s = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", re.sub(r"\s+", " ", s or "").strip())
    m = re.match(rf"({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})$", s)
    if m:
        return f"{_MONTH_SHORT[m.group(1)]} {int(m.group(2))}, {m.group(3)}"
    m = re.match(rf"({_MONTHS})\s+(\d{{4}})$", s)
    if m:
        return f"{_MONTH_SHORT[m.group(1)]} {m.group(2)}"
    return s


def _name_before(text: str, s0: int, at: int) -> Tuple[str, int]:
    """The person a clause is about: the last full name before `at` in its sentence (its start), or ('', -1)."""
    best = ("", -1)
    for m in re.finditer(rf"({_NAME2})", text[s0:at]):
        name = re.sub(r"['’]s$", "", m.group(1))
        if _person_ok(name):
            best = (name, s0 + m.start())
    return best


_ROLE_IS = re.compile(rf"(?P<name>{_NAME2})\s+(?:was|is|became|had\s+become)\s+(?P<role>(?:a|an|the)\s+(?!(?:man|woman|"
                      rf"person|boy|girl|kid|child|one|reason|first\s+time|last\s+time|same)\b)[^,.;()]{{3,60}}?)(?=,|\.|;|"
                      rf"\s+who\b|\s+when\b|\s+and\b)")
_LAST_SEEN = re.compile(rf"\blast\s+seen\s+(?:alive\s+)?(?:on\s+(?P<when>(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+"
                        rf"(?:1[5-9]|20)\d\d|(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?)|in\s+(?P<where>[A-Z][a-z]+"
                        rf"(?:\s+[A-Z][a-z]+){{0,2}}(?:,\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)?))")
_PRONOUN_START = re.compile(r"^\s*(?:(?:and|but|then|later|sadly|tragically)\s*,?\s+)?(?:he|she)\b", re.I)


def _place_text(p: str) -> str:
    return re.sub(r"\s+", " ", (p or "")).strip(" ,.;:")


def _person_facts(text: str, a: int, b: int) -> List[Tuple[str, str, int]]:
    """Born / died / last seen said between a and b: (label, value, char)."""
    sent = text[a:b]
    facts: List[Tuple[str, str, int]] = []
    m = _BORN.search(sent)
    if m and (m.group("when") or m.group("where") or m.group("when2")):
        when = m.group("when") or m.group("when2") or ""
        where = _place_text(m.group("where") or "")
        if where and (where.split()[0] in _NOT_FIRST or re.match(rf"(?:{_MONTHS})\b", where)):
            where = ""
        val = " · ".join(x for x in (_date_text(when), where) if x)
        if val:
            facts.append(("Born", val, a + m.start()))
    m = _DIED.search(sent)
    if m and m.group("when"):
        facts.append(("Died", _date_text(m.group("when")), a + m.start()))
    m = _LAST_SEEN.search(sent)
    if m and (m.group("when") or m.group("where")):
        facts.append(("Last seen", _date_text(m.group("when")) if m.group("when") else _place_text(m.group("where")),
                      a + m.start()))
    return facts


def find_profiles(nar) -> List[dict]:
    out = []
    text = nar.text
    sents = _sentences(nar)
    for i, (s0, s1) in enumerate(sents):
        sent = text[s0:s1]
        facts: List[Tuple[str, str, int]] = []      # (label, value, char)
        name, name_at, role = "", -1, ""
        m = _APPOS.search(sent)
        if m and _person_ok(m.group("name")):
            name, name_at = m.group("name"), s0 + m.start("name")
            role = re.sub(r"^(?:a|an|the)\s+", "", m.group("role").strip(), flags=re.I)
            if m.group("age"):
                facts.append(("Age", m.group("age"), s0 + m.start("age")))
        m = _AGE_ROLE.search(sent)
        if m and _person_ok(m.group("name")) and (not name or m.group("name") == name):
            name, name_at = m.group("name"), name_at if name else s0 + m.start("name")
            if not any(f[0] == "Age" for f in facts):
                facts.append(("Age", m.group("age"), s0 + m.start("age")))
            if m.group("role") and not role:
                role = m.group("role")
        m = _NAME_AGE.search(sent)
        if m and _person_ok(m.group("name")) and (not name or m.group("name") == name):
            name, name_at = m.group("name"), name_at if name else s0 + m.start("name")
            if not any(f[0] == "Age" for f in facts):
                facts.append(("Age", m.group("age"), s0 + m.start("age")))
        m = _ROLE_IS.search(sent)
        if m and _person_ok(m.group("name")) and (not name or m.group("name") == name):
            name, name_at = m.group("name"), name_at if name else s0 + m.start("name")
            if not role:
                role = re.sub(r"^(?:a|an|the)\s+", "", m.group("role").strip(), flags=re.I)
        own = _person_facts(text, s0, s1)
        if own and not name:
            first = min(f[2] for f in own)
            name, name_at = _name_before(text, s0, first)
            if not name:
                after = re.search(rf",\s*({_NAME2})", text[first:min(s1, first + 80)])
                if after and _person_ok(after.group(1)):
                    name, name_at = after.group(1), first + after.start(1)
        facts += [f for f in own if not any(g[0] == f[0] for g in facts)]
        # "(1809-1865)" after the name
        ls = _LIFESPAN.search(sent)
        if ls:
            nm = re.search(rf"({_NAME2})$", sent[:ls.start()].rstrip())
            if nm and _person_ok(nm.group(1)) and (not name or nm.group(1) == name):
                name, name_at = nm.group(1), name_at if name else s0 + nm.start(1)
                if not any(f[0] == "Born" for f in facts):
                    facts.append(("Born", ls.group(1), s0 + ls.start(1)))
                if not any(f[0] == "Died" for f in facts):
                    facts.append(("Died", ls.group(2), s0 + ls.start(2)))
        if not name:
            continue
        # the next sentence goes on about the same person ("He died in 1865.")
        b_end = s1
        if i + 1 < len(sents):
            n0, n1 = sents[i + 1]
            nxt = text[n0:n1]
            if (_PRONOUN_START.match(nxt) or re.match(rf"\s*{re.escape(_surname_word(name))}\b", nxt)) \
                    and _time(nar, n0) - _time(nar, s0) <= 14.0:
                more = [f for f in _person_facts(text, n0, n1) if not any(g[0] == f[0] for g in facts)]
                if more:
                    facts += more
                    b_end = n1
        if not facts:
            continue
        fm = _FROM.search(sent)
        if fm and not any(fm.group("p") in f[1] for f in facts) and s0 + fm.start() > name_at:
            p = _place_text(fm.group("p"))
            if p.split()[0] not in _NOT_FIRST:
                facts.append(("From", p, s0 + fm.start("p")))
        if len(facts) + (1 if role else 0) < 2 or not any(f[0] in ("Born", "Died", "Age", "Last seen") for f in facts):
            continue
        facts.sort(key=lambda f: f[2])
        t0 = _time(nar, name_at) - 0.07
        items, ats = [], []
        for lab, val, ch in facts[:4]:
            at = _time(nar, ch)
            items.append({"label": lab, "text": val, "at": round(max(0.0, at - t0), 2)})
            ats.append(at)
        if any(f[0] == "From" for f in facts):
            role = re.sub(r"\s+from\s+.*$", "", role)         # (the place has its own line)
        role = _cap(role.strip())
        if len(role) > 44:
            role = _phrase(role, 6)
        kick = _ROLE_KICKER.search(text[max(s0, name_at - 30):name_at])
        props = {"template": PROFILE, "text": name, "subtitle": role, "items": items}
        if kick:
            props["label"] = kick.group(1).capitalize()
        out.append(_cand(PROFILE, nar, name_at, b_end, props, ats, score=5.0 + 0.4 * len(items),
                         key=f"pf:{name.lower()}", absorb=(s0, b_end), at=t0 + 0.07))
    return out


def _surname_word(name: str) -> str:
    words = [w for w in name.split() if not re.match(r"^(?:Jr\.?|Sr\.?|III|II)$", w)]
    return words[-1] if words else name


# --------------------------------------------------------------------------- KT_STEPS
_ORD = {"first": 1, "firstly": 1, "second": 2, "secondly": 2, "third": 3, "thirdly": 3, "fourth": 4, "fourthly": 4,
        "fifth": 5, "fifthly": 5, "sixth": 6, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}
_STEP_MARK = re.compile(
    r"(?:^|(?<=[.!?:]\s)|(?<=[.!?:]\s\s))(?:(?:and|so|now)\s+)?(?:"
    r"(?P<ord>first(?:ly)?|second(?:ly)?|third(?:ly)?|fourth(?:ly)?|fifth(?:ly)?|sixth|finally|lastly)\s*,\s*|"
    r"step\s+(?P<n>one|two|three|four|five|six|[1-6])\s*(?:[:,.]|\s[-–—]|\s+is\s+(?:to\s+)?)?\s*|"
    r"(?:the\s+)?(?P<ord2>first|second|third|fourth|fifth|sixth|final|last|next)\s+step\s+(?:is|was)\s+(?:to\s+)?)",
    re.I)
_STEP_LEAD = re.compile(r"^(?:you(?:'ll|\s+will)?\s+(?:need|want|have|ought)\s+to\s+|you\s+(?:should|must|need|can|"
                        r"could)\s+|make\s+sure\s+(?:that\s+)?(?:you\s+|to\s+)?|it(?:'s|\s+is)\s+(?:time\s+)?to\s+|"
                        r"is\s+to\s+|we(?:'ll)?\s+|let's\s+|i\s+|try\s+to\s+|don't\s+forget\s+to\s+|remember\s+to\s+|"
                        r"just\s+|simply\s+|go\s+ahead\s+and\s+)", re.I)
TIGHT_STEPS = 22.0          # steps said this close together are one list; further apart, one card per step


def _step_label(s: str) -> str:
    s = re.split(r"[.;:!?]|,\s|\s(?:so\s+that|so|because|which|where|when|while|then|until|before|after|otherwise)\s",
                 s or "")[0]
    for _ in range(3):
        m = _STEP_LEAD.match(s.strip())
        if not m:
            break
        s = s.strip()[m.end():]
    words = _trim_tail(s.split()[:6])
    return _cap(" ".join(words))


def find_steps(nar) -> List[dict]:
    out = []
    text = nar.text
    marks = []
    for m in _STEP_MARK.finditer(text):
        w = (m.group("ord") or m.group("n") or m.group("ord2") or "").lower()
        label = _step_label(text[m.end():m.end() + 160])
        if not label or len(label) < 3:
            continue
        n = _ORD.get(w)
        marks.append({"n": n, "last": w in ("finally", "lastly", "final", "last"), "next": w == "next", "a": m.start(),
                      "b": m.end(), "at": _time(nar, m.start()), "label": label,
                      "label_at": _time(nar, m.end())})
    # runs: 1, 2, 3 ... (a "finally" may close a run of two or more); steps at most 2 minutes apart
    runs: List[List[dict]] = []
    run: List[dict] = []
    for mk in marks:
        expect = len(run) + 1
        if run and mk["at"] - run[-1]["at"] > 120.0:
            if len(run) >= 3:
                runs.append(run)
            run = []
            expect = 1
        if mk["n"] == expect or (run and (mk["last"] or mk["next"]) and len(run) >= 2) and not (mk["n"] and mk["n"] != expect):
            run.append(mk)
            if mk["last"]:
                if len(run) >= 3:
                    runs.append(run)
                run = []
        elif mk["n"] == 1:
            if len(run) >= 3:
                runs.append(run)
            run = [mk]
        else:
            if len(run) >= 3:
                runs.append(run)
            run = []
    if len(run) >= 3:
        runs.append(run)
    for run in runs:
        run = run[:6]
        head = text[max(0, run[0]["a"] - 220):run[0]["a"]]
        tm = re.search(r"\b(?:here(?:'s|\s+is)|this\s+is|that's)\s+how\s+(?:to\s+|you\s+)?(?P<t>[^.,;!?]{3,40})", head, re.I)
        tm2 = re.search(r"\b(?:three|four|five|six|\d)\s+(?:simple\s+|easy\s+|key\s+|basic\s+|quick\s+)?steps\s+to\s+"
                        r"(?P<t>[^.,;!?]{3,36})", head, re.I)
        title = ""
        if tm:
            title = "How to " + " ".join(_trim_tail(tm.group("t").split()[:5])) if "how to" in tm.group(0).lower() \
                else _phrase(tm.group("t"), 5)
        elif tm2:
            title = _cap(" ".join(_trim_tail(tm2.group("t").split()[:5])))
        total = len(run)
        if run[-1]["at"] - run[0]["at"] <= TIGHT_STEPS:
            t0 = run[0]["at"] - 0.07
            items = [{"label": mk["label"], "at": round(max(0.0, mk["at"] - t0), 2)} for mk in run]
            props = {"template": STEPS, "text": title, "items": items, "total": total}
            out.append(_cand(STEPS, nar, run[0]["a"], run[-1]["b"] + 40, props, [mk["at"] for mk in run],
                             score=6.0 + 0.2 * total, key="sp:" + "|".join(mk["label"].lower() for mk in run),
                             absorb=(run[0]["a"], run[-1]["b"]), at=t0 + 0.07))
            continue
        # spread out: one card per step, the steps so far above it, the new one landing on its word
        for j, mk in enumerate(run):
            items = [{"label": x["label"]} for x in run[:j]] + [{"label": mk["label"], "at": 0.07}]
            props = {"template": STEPS, "text": title, "items": items, "total": total}
            out.append(_cand(STEPS, nar, mk["a"], mk["b"] + 40, props, [None] * j + [mk["at"]], score=5.0,
                             key=f"sp:{j}:{mk['label'].lower()}", absorb=(mk["a"], mk["b"])))
    return out


# --------------------------------------------------------------------------- KT_CHAIN
_CAUSE = re.compile(r"\b(led\s+to|leads\s+to|leading\s+to|caused|causing|triggered|triggering|sparked|sparking|"
                    r"set\s+off|resulted\s+in|resulting\s+in|gave\s+rise\s+to|paved\s+the\s+way\s+for|fu(?:e)?l(?:l)?ed|"
                    r"brought\s+about|ushered\s+in)\b", re.I)
_PRONOUN = re.compile(r"^(?:this|that|it|which|they|he|she|we|you|i|these|those|there)(?:\s+in\s+turn)?$", re.I)
_NODE_TAIL = re.compile(r",?\s*(?:which|that|and|this|in\s+turn|and\s+that|and\s+this|then)\s*$", re.I)


def _node(s: str, head: bool) -> str:
    """A cause or an effect as said, cleaned: the clause next to its verb, at most six words."""
    s = re.sub(r"\s+", " ", s or "").strip(" ,;:")
    if head:
        s = re.split(r"[,;:]\s*", s)[-1]
        s = re.sub(r"^(?:and|but|so|then|because|since|as|when|while|however)\s+", "", s, flags=re.I)
        s = re.sub(r"^(?:in\s+(?:the\s+)?(?:\d{4}s?|\w+)\s*,?\s*)", "", s)
    else:
        s = re.split(r"[,;:]|\s(?:which|that|and\s+that|and\s+this|who|before|after|when|while|because|until)\s", s)[0]
    s = _NODE_TAIL.sub("", s).strip()
    words = _trim_tail(s.split())
    if not words or len(words) > 7 or _PRONOUN.match(" ".join(words)):
        return ""
    return _cap(" ".join(words))


def find_chains(nar) -> List[dict]:
    out = []
    text = nar.text
    sents = _sentences(nar)
    i = 0
    while i < len(sents):
        s0, s1 = sents[i]
        verbs = list(_CAUSE.finditer(text, s0, s1))
        if not verbs:
            i += 1
            continue
        nodes: List[Tuple[str, int]] = []
        first = _node(text[s0:verbs[0].start()], True)
        if not first:
            i += 1
            continue
        start = text.find(first.split()[0], s0) if first else s0
        start = start if s0 <= start < verbs[0].start() else s0
        nodes.append((first, start))
        for j, v in enumerate(verbs):
            end = verbs[j + 1].start() if j + 1 < len(verbs) else s1
            nd = _node(text[v.end():end], False)
            if not nd:
                break
            pos = v.end() + (len(text[v.end():end]) - len(text[v.end():end].lstrip()))
            nodes.append((nd, pos))
        j2 = i + 1
        # "... That triggered a wave of defaults." continues the chain
        while j2 < len(sents) and len(nodes) < 4:
            n0, n1 = sents[j2]
            cont = re.match(r"\s*(?:and\s+)?(?:this|that|which|it)(?:\s+in\s+turn)?\s+(?=" + _CAUSE.pattern[2:-2] + r")",
                            text[n0:n1], re.I)
            if not cont or _time(nar, n0) - _time(nar, nodes[-1][1]) > 10.0:
                break
            v = _CAUSE.match(text, n0 + cont.end())
            if not v:
                break
            nd = _node(text[v.end():n1], False)
            if not nd:
                break
            nodes.append((nd, v.end() + 1))
            j2 += 1
        nodes = nodes[:4]
        if len(nodes) < 2 or (len(nodes) == 2 and (len(nodes[0][0].split()) > 5 or len(nodes[1][0].split()) > 5)):
            i += 1
            continue
        if len({n.lower() for n, _p in nodes}) < len(nodes):
            i += 1
            continue
        t0 = _time(nar, nodes[0][1]) - 0.07
        items, ats = [], []
        for n, p in nodes:
            at = _time(nar, p)
            items.append({"label": n, "at": round(max(0.0, at - t0), 2)})
            ats.append(at)
        title = "Domino effect" if re.search(r"\bdomino\s+effect\b", text[max(0, s0 - 120):s1], re.I) else ""
        b = sents[j2 - 1][1]
        props = {"template": CHAIN, "text": title, "items": items}
        out.append(_cand(CHAIN, nar, nodes[0][1], b, props, ats, score=4.6 + 0.5 * len(nodes),
                         key="ch:" + "|".join(n.lower() for n, _p in nodes), absorb=(s0, b), at=t0 + 0.07))
        i = j2
    return out


# --------------------------------------------------------------------------- KT_CASE
_CRIME = re.compile(r"\b(murder(?:ed|s)?|killed|killing|homicide|shot\s+dead|stabbed|strangled|disappear(?:ed|ance)|"
                    r"hijack(?:ed|ing|er)?|"
                    r"vanished|went\s+missing|abduct(?:ed|ion)|kidnapp?(?:ed|ing)|robbery|robbed|heist|stolen|theft|"
                    r"fraud|arson|crime|investigation|investigators|detectives?|police|FBI|sheriff|suspects?|victims?|"
                    r"body\s+was\s+found|remains\s+were\s+found|cold\s+case|unsolved|serial\s+killer|manhunt|ransom)\b",
                    re.I)
_STATUS = [
    (re.compile(r"\bcold\s+case\b", re.I), "Cold case"),
    (re.compile(r"\b(?:remains?|is\s+still|still|was\s+never|has\s+never\s+been|never\s+(?:been\s+)?)\s*(?:officially\s+)?"
                r"(?:unsolved|solved)\b|\bunsolved\b", re.I), "Unsolved"),
    (re.compile(r"\bno\s+one\s+(?:was|has)\s+(?:ever\s+)?(?:been\s+)?(?:charged|arrested|convicted)\b|\bno\s+arrests?\b",
                re.I), "Unsolved"),
    (re.compile(r"\b(?:never\s+(?:been\s+)?found|still\s+missing|remains?\s+missing)\b", re.I), "Missing"),
    (re.compile(r"\b(?:remains?|is\s+still|still)\s+open\b|\bcase\s+(?:is\s+)?(?:still\s+)?open\b", re.I), "Open"),
    (re.compile(r"\b(?:was|were)\s+(?:later\s+|eventually\s+|finally\s+)?convicted\b|\bfound\s+guilty\b", re.I), "Convicted"),
    (re.compile(r"\b(?:was|were)\s+(?:later\s+)?acquitted\b|\bfound\s+not\s+guilty\b", re.I), "Acquitted"),
    (re.compile(r"\bcase\s+(?:was\s+)?closed\b|\bclosed\s+the\s+case\b", re.I), "Closed"),
    (re.compile(r"\b(?:solved|cracked)\s+the\s+case\b|\bcase\s+was\s+(?:finally\s+)?solved\b", re.I), "Solved"),
    (re.compile(r"\b(?:was|were)\s+(?:later\s+|finally\s+)?arrested\b", re.I), "Arrested"),
]
_CASE_TITLE = [
    re.compile(r"\b(?i:the)\s+(?P<k>(?i:murders?|disappearance|death|kidnapping|abduction|killing|assassination|case))\s+"
               r"(?i:of)\s+(?P<n>(?:[A-Z][\w.'’-]+)(?:\s+[A-Z][\w.'’-]+){0,3})"),
    re.compile(r"\b(?i:the)\s+(?P<n>(?:[A-Z][\w'’-]+)(?:\s+[A-Z][\w'’-]+){0,2})\s+(?P<k>case|murders?|killings?|heist|"
               r"robbery|disappearance|kidnapping|mystery)\b"),
    re.compile(r"\b(?i:the)\s+(?P<n>(?:[A-Z][\w'’-]+)(?:\s+[A-Z][\w'’-]+){0,1}\s+Killer)\b"),
]
# "Jenny Lin vanished ...", "Asha Degree disappeared ...", "Jane Doe was murdered ...": the case is that person's
_CASE_WHO = re.compile(rf"(?P<n>{_NAME2})\s+(?:(?i:vanished|disappeared|went\s+missing|hijacked|robbed|was\s+(?:murdered|"
                       rf"killed|abducted|kidnapped|found\s+dead|last\s+seen|never\s+seen\s+again)))\b")
_CASE_PLACE = re.compile(r"\b(?:in|at|near|outside|out\s+of|from)\s+(?:the\s+)?(?:small\s+|quiet\s+|rural\s+)?(?:town|city|village|suburb|"
                         r"county)?\s*(?:of\s+)?(?P<p>(?:[A-Z][a-z'’.-]+)(?:\s+[A-Z][a-z'’.-]+){0,2}(?:,\s+[A-Z][a-z'’.-]+"
                         r"(?:\s+[A-Z][a-z'’.-]+)?)?)")


def find_cases(nar) -> List[dict]:
    from .treatments import date_parts
    out = []
    text = nar.text
    sents = _sentences(nar)
    used = -1
    for i, (s0, s1) in enumerate(sents):
        if s0 < used:
            continue
        sent = text[s0:s1]
        if not _CRIME.search(sent):
            continue
        fields: List[Tuple[str, str, int]] = []
        d = date_parts(sent)
        if d:
            fields.append(("Date", _date_text(text[s0 + d["start"]:s0 + d["end"]].replace("the ", "")) if d.get("day")
                           else d["label"].title().replace(",", ""), s0 + d["start"]))
        else:
            y = re.search(r"\b(?:in|on|of)\s+((?:1[89]|20)\d\d)\b", sent)
            if y:
                fields.append(("Date", y.group(1), s0 + y.start(1)))
        pm = None
        for m in _CASE_PLACE.finditer(sent):
            p = _place_text(m.group("p"))
            if p.split()[0] in _NOT_FIRST or re.match(rf"(?:{_MONTHS})\b", p) or (_person_ok(p) and not _is_place(p)):
                continue
            pm = m
            break
        if pm:
            fields.append(("Location", _place_text(pm.group("p")), s0 + pm.start("p")))
        # the status: in this sentence or the next two (within 25 s)
        status = None
        for j in range(i, min(len(sents), i + 3)):
            a, b = sents[j]
            if _time(nar, a) - _time(nar, s0) > 25.0:
                break
            for rx, lab in _STATUS:
                m = rx.search(text, a, b)
                if m:
                    status = (lab, m.start(), b)
                    break
            if status:
                break
        if status:
            fields.append(("Status", status[0], status[1]))
        if len(fields) < 2 or not any(f[0] in ("Date", "Location") for f in fields):
            continue
        title = ""
        win = text[max(0, s0 - 160):s1]
        for rx in _CASE_TITLE:
            m = rx.search(win)
            if m:
                n = m.group("n")
                k = (m.groupdict().get("k") or "").lower()
                title = f"{k.capitalize()} of {n}" if rx is _CASE_TITLE[0] and k != "case" else (
                    f"{n} {k}" if k else n)
                if rx is _CASE_TITLE[0] and k == "case":
                    title = f"The {n} case"
                break
        if not title:
            who = _CASE_WHO.search(win)
            if who and _person_ok(who.group("n")):
                title = f"The {who.group('n')} case"
        t0 = _time(nar, min(f[2] for f in fields)) - 0.07
        t0 = min(t0, _time(nar, s0))
        items, ats = [], []
        for lab, val, ch in fields:
            at = _time(nar, ch)
            items.append({"label": lab, "text": val, "at": round(max(0.0, at - t0), 2)})
            ats.append(at)
        b = status[2] if status else s1
        props = {"template": CASE, "text": title[:40], "label": "Case file", "items": items}
        out.append(_cand(CASE, nar, s0, b, props, ats, score=5.5 + 0.3 * len(items),
                         key="cs:" + (title.lower() or "|".join(f[1].lower() for f in fields)), absorb=(s0, b),
                         at=t0 + 0.07))
        used = b
    return out


# --------------------------------------------------------------------------- KT_POST
_POST_VERB = r"(?:tweeted|posted|wrote|replied|commented|shared|captioned|messaged)"
_PLATFORM = r"(?:X|Twitter|Facebook|Instagram|Reddit|TikTok|LinkedIn|Threads|YouTube|Snapchat|Bluesky|Truth\s+Social|" \
            r"Weibo|Telegram|Discord|social\s+media)"
_GENERIC_WHO = r"(?:one\s+user|a\s+user|another\s+user|someone|one\s+fan|a\s+fan|an\s+employee|a\s+redditor|one\s+redditor|" \
               r"an\s+anonymous\s+user|the\s+company|the\s+official\s+account|its\s+official\s+account)"
_QUOTE = r"[“\"](?P<q>[^”\"]{6,280})[”\"]"
_HANDLE_WHO = r"(?:(?i:the\s+|one\s+|an?\s+)?(?i:account|user|page|handle)\s+)?@[A-Za-z0-9_]{2,30}"
_POST_RX = [
    re.compile(rf"(?P<who>{_HANDLE_WHO}|{_NAME1}|(?i:{_GENERIC_WHO}))(?:\s+(?i:on)\s+(?P<plat0>{_PLATFORM}))?\s+(?:(?i:then|later|"
               rf"simply|once|famously|publicly|also|even|had)\s+)?(?P<verb>(?i:{_POST_VERB}))(?:\s+(?i:on|to)\s+"
               rf"(?P<plat>{_PLATFORM}))?(?:\s+(?i:that|this))?\s*[:,]?\s*{_QUOTE}"),
    re.compile(rf"(?i:in|on)\s+a\s+(?i:post|tweet|comment|reply|message|thread)(?:\s+(?i:on)\s+(?P<plat>{_PLATFORM}))?"
               rf"\s*,?\s*(?P<who>{_NAME1}|(?i:{_GENERIC_WHO}))\s+(?i:wrote|said|posted|added)\s*[:,]?\s*{_QUOTE}"),
    re.compile(rf"(?P<who>{_NAME1})\s+(?P<verb>(?i:tweeted|posted))(?:\s+(?i:on)\s+(?P<plat>{_PLATFORM}))?\s*:\s*"
               rf"(?P<q>[^.!?\"“”]{{8,200}}[.!?])"),
]
_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,30})\b|\b(?:user|account|username|handle)\s+(?:called|named)\s+"
                     r"([A-Za-z0-9_]{3,30})\b")
_LIKES = re.compile(r"(?P<n>\d[\d,.]*)\s*(?P<sc>thousand|million|k\b|m\b)?\s+(?P<what>likes|retweets|reposts|shares|"
                    r"views|comments|upvotes|replies)\b", re.I)


def find_posts(nar) -> List[dict]:
    out = []
    text = nar.text
    for rx in _POST_RX:
        for m in rx.finditer(text):
            who = re.sub(r"\s+", " ", m.group("who")).strip()
            at_handle = re.search(r"@([A-Za-z0-9_]{2,30})$", who)
            generic = bool(re.match(_GENERIC_WHO, who, re.I))
            if not generic and not at_handle and (who.split()[0] in _NOT_FIRST or who.lower() in _SMALL
                                                  or re.fullmatch(_PLATFORM, who)):
                continue
            q = re.sub(r"\s+", " ", m.group("q")).strip()
            if len(q.split()) > 40 or len(q.split()) < 2:
                continue
            if at_handle:
                name = at_handle.group(1)              # an account said by its handle: the handle is its name
            else:
                name = re.sub(r"^(?:one|a|an|another|its|the)\s+", "", who, flags=re.I) if generic else who
                name = name[:1].upper() + name[1:]
            if name.lower() == "company":
                name = "Official account"
            s0, s1 = nar.sentence(m.start())
            nxt_end = nar.sentence(min(len(text) - 1, s1 + 2))[1] if s1 + 2 < len(text) else s1
            hm = _HANDLE.search(text, s0, s1)
            handle = ("@" + (hm.group(1) or hm.group(2))) if hm else ""
            # the time the sentence opens with is the post's date, beside the handle ("@handle · Aug 2018")
            _prep, when = _lead_time(text, s0, m.start()) if s0 <= m.start() else ("", "")
            if when:
                handle = f"{handle} · {when}" if handle else when
            props: Dict[str, Any] = {"template": POST, "label": name, "text": q, "subtitle": handle}
            plat = m.groupdict().get("plat") or m.groupdict().get("plat0") or ""
            if plat and not re.match(r"social\s+media", plat, re.I):
                props["highlight"] = re.sub(r"\s+", " ", plat)
            lk = _LIKES.search(text, m.end(), nxt_end)
            if lk:
                v = number_of(lk.group("n").rstrip(".,"))
                sc = (lk.group("sc") or "").lower()
                if v is not None:
                    v *= {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6}.get(sc, 1.0)
                    props["value"] = _round(v)
                    props["suffix"] = lk.group("what").lower()
            qa = m.start("q")
            said = max(0.0, nar.end_at(m.end("q")) - _time(nar, qa))
            c = _cand(POST, nar, m.start(), (lk.end() if lk else m.end()), props, None, score=5.5,
                      key="po:" + q.lower()[:40], absorb=(s0 if when else m.start(), lk.end() if lk else m.end()),
                      at=_time(nar, m.start()))
            c["said_s"] = round(_time(nar, qa) - _time(nar, m.start()) + said, 2)
            out.append(c)
    out.sort(key=lambda c: c["at"])
    dedup, last = [], -1e9
    for c in out:
        if dedup and abs(c["at"] - last) < 1.0:
            continue
        dedup.append(c)
        last = c["at"]
    return dedup


# --------------------------------------------------------------------------- KT_FACTCHECK
_CLAIM = re.compile(
    r"\b(?:you(?:'ve|\s+have)?\s+(?:may\s+|might\s+|probably\s+)?(?:have\s+)?(?:heard|read|been\s+told)\s+(?:it\s+said\s+)?"
    r"(?:that\s+)?|many\s+(?:people\s+)?(?:still\s+|once\s+)?(?:believed?|think|thought|say|said|assumed?|claimed?)\s+"
    r"(?:that\s+)?|(?:most\s+)?people\s+(?:often\s+|once\s+|long\s+)?(?:believed?|think|thought|say|said|assumed?)\s+"
    r"(?:that\s+)?|"
    r"it(?:'s|\s+is)\s+(?:often|commonly|widely|frequently)\s+(?:said|believed|claimed|repeated)\s+(?:that\s+)?|"
    r"(?:a|the)\s+(?:popular|common|widespread|persistent|famous|old)\s+(?:myth|belief|claim|misconception|idea)\s+"
    r"(?:is|says|holds|goes)\s+(?:that\s+)?|the\s+claim\s+(?:is\s+|was\s+)?that\s+|rumou?rs?\s+(?:say|said|claim|had\s+it)\s+"
    r"(?:that\s+)?|myth\s*:\s*)(?P<claim>[^.?!]{8,150})", re.I)
_VERDICTS = [
    (re.compile(r"\b(?:that(?:'s|\s+is)|this\s+is|it(?:'s|\s+is)|which\s+is)\s+(?:completely\s+|totally\s+|simply\s+|actually\s+|"
                r"just\s+|entirely\s+)?(?:misleading|half[- ]true|only\s+(?:partly|half)\s+true|partly\s+true|"
                r"an?\s+exaggeration|exaggerated|oversimplified|not\s+quite\s+(?:right|true)|not\s+the\s+whole\s+story)\b|"
                r"\b(?:misleading|half[- ]true)\b", re.I), "Misleading"),
    (re.compile(r"\b(?:that(?:'s|\s+is)|this\s+is|it(?:'s|\s+is)|which\s+is)\s+(?:completely\s+|totally\s+|simply\s+|actually\s+|"
                r"just\s+|entirely\s+|absolutely\s+)?(?:false|not\s+true|untrue|wrong|a\s+myth|nonsense|a\s+lie|incorrect|"
                r"fake|fiction|a\s+misconception)\b|\b(?:this|that|it)\s+(?:claim\s+)?(?:has\s+been|was)\s+debunked\b|"
                r"\b(?:is|was)\s+(?:a\s+)?(?:complete\s+|total\s+)?myth\b|\bnot\s+true\b|\bdebunked\b", re.I), "False"),
    (re.compile(r"\b(?:that(?:'s|\s+is)|this\s+is|it(?:'s|\s+is)|which\s+is)\s+(?:actually\s+|completely\s+|absolutely\s+|"
                r"entirely\s+)?(?:true|correct|accurate|right|real)\b(?!\s+that)|\bturns\s+out\s+(?:it(?:'s|\s+is)|that(?:'s|\s+is)"
                r"|they(?:'re|\s+are))\s+(?:actually\s+)?(?:true|right|correct)\b|\bit\s+really\s+(?:is|does|did|happened)\b",
                re.I), "True"),
]
_FACT_LEAD = re.compile(r"^\s*(?:in\s+(?:reality|fact|truth)|actually|the\s+truth\s+is|the\s+reality\s+is|fact\s*:)\s*,?\s*"
                        r"(?:that\s+)?", re.I)
# a sentence that moves on rather than saying the fact
_NOT_FACT = re.compile(r"^\s*(?:but|and|so|now|here|let's|let\s+us|today|next|in\s+the\s+next|stay|subscribe|why|what|how|"
                       r"who|when|where|which|this\s+(?:video|story)|that's\s+(?:why|how|what))\b", re.I)


def find_factchecks(nar) -> List[dict]:
    out = []
    text = nar.text
    for m in _CLAIM.finditer(text):
        claim = re.sub(r"\s+", " ", m.group("claim")).strip(" ,;:\"“”")
        claim = re.split(r",\s+(?:but|and\s+that's|which\s+is)\s", claim)[0]
        if len(claim.split()) < 3 or len(claim.split()) > 22:
            continue
        _s0, s1 = nar.sentence(m.start())
        # the verdict: in the claim's own sentence (after the claim) or the next two, within 12 s
        pos, search_to = s1, s1
        for _k in range(2):
            if pos >= len(text) - 2:
                break
            _a, b = nar.sentence(pos + 2)
            if b <= pos:
                break
            pos = search_to = b
        best = None
        for rx, lab in _VERDICTS:
            vm = rx.search(text, m.start("claim"), search_to)
            if vm and _time(nar, vm.start()) - _time(nar, m.end("claim")) <= 12.0:
                if best is None or vm.start() < best[1].start():
                    best = (lab, vm)
        if best is None:
            continue
        lab, vm = best
        # the fact: the next sentence after the verdict when it says how it really is
        fact = ""
        va, vb = nar.sentence(vm.start())
        after = text[vm.end():vb].strip(" ,;:")
        lead = _FACT_LEAD.match(after)
        if lead and len(after[lead.end():].split()) >= 3:
            fact = _phrase(after[lead.end():], 14)
        elif vb + 2 < len(text):
            na, nb = nar.sentence(vb + 2)
            nxt = text[na:nb]
            lead = _FACT_LEAD.match(nxt)
            soon = _time(nar, na) - _time(nar, vm.end()) <= 6.0
            if lead and soon:
                fact = _phrase(nxt[lead.end():], 14)
            elif soon and len(nxt.split()) <= 14 and not _NOT_FACT.match(nxt) and not _CLAIM.search(nxt):
                # the sentence right after the verdict says how it really is ("He was about average height.")
                fact = _phrase(nxt, 14)
        claim_text = _cap(claim)
        t0 = _time(nar, m.start("claim")) - 0.07
        v_at = _time(nar, vm.start())
        props = {"template": FACTCHECK, "text": claim_text, "subtitle": fact,
                 "items": [{"label": lab, "at": round(max(0.0, v_at - t0), 2)}]}
        # the time its sentence opens with is the claim's ("In 1969, many believed ..."): its kicker, "CLAIM · 1969"
        _prep, when = _lead_time(text, _s0, m.start())
        if when:
            props["label"] = when
        b = max(vm.end(), m.end("claim"))
        out.append(_cand(FACTCHECK, nar, m.start("claim"), b, props, [v_at], score=6.0,
                         key="fc:" + claim.lower()[:40], absorb=(_s0 if when else m.start(), vb), at=t0 + 0.07))
    return out


# --------------------------------------------------------------------------- KT_PODIUM
_MEDAL = re.compile(rf"(?P<name>{_NAME1})\s+(?i:took|won|claimed|grabbed|earned|got|snatched|collected|picked\s+up)\s+"
                    rf"(?i:the\s+)?(?P<m>(?i:gold|silver|bronze))\b|\b(?P<m2>(?i:gold|silver|bronze))\s+(?i:went\s+to|for)\s+"
                    rf"(?P<name2>{_NAME1})|\b(?i:and)\s+(?P<m3>(?i:silver|bronze))\s+(?i:to)\s+(?P<name3>{_NAME1})|"
                    rf"(?P<name4>{_NAME1})\s+(?P<m4>(?i:silver|bronze))\b(?=\s*(?:,|and\b|\.|$))")
_PLACE_RANK = re.compile(rf"(?P<name>{_NAME1})\s+(?i:finished|came|placed|ended\s+up|was|took)\s+(?i:in\s+)?"
                         rf"(?P<p>(?i:first|second|third))(?:\s+(?i:place))?\b|\b(?P<p2>(?i:first|second|third))\s+(?i:place)\s+"
                         rf"(?i:went\s+to|was|is|belongs\s+to)\s*:?\s*(?P<name2>{_NAME1})")
_TOP3 = re.compile(rf"\b(?i:the\s+)?(?:(?i:top\s+three)|(?i:three)\s+(?P<sup>(?:\w+est|(?i:most|best|largest|biggest)"
                   rf"(?:\s+\w+)?)(?:\s+\w+){{0,5}}?))\s+(?i:are|were|is|was)\s*:?\s*(?P<a>{_NAME1})(?:\s*\([^)]*\))?"
                   rf"(?:\s*,?\s*(?i:with|at)\s+[^,]{{1,24}})?\s*,\s*(?P<b>{_NAME1})(?:\s*\([^)]*\))?(?:\s*,?\s*(?i:with|at)\s+"
                   rf"[^,]{{1,24}})?\s*,?\s*(?i:and)\s+(?P<c>{_NAME1})")
_RANK_OF = {"gold": 1, "silver": 2, "bronze": 3, "first": 1, "second": 2, "third": 3}
_EVENT = re.compile(r"\b(?i:in|at)\s+(?i:the)\s+(?P<ev>(?:(?:19|20)\d\d\s+)?(?:[A-Z][\w'’.-]*\s+){0,4}?(?:(?i:final|race|"
                    r"olympics|games|championships?|cup|open|grand\s+prix|marathon|tournament|world\s+cup|derby|classic|"
                    r"event)))\b")


def find_podiums(nar) -> List[dict]:
    out = []
    text = nar.text
    sents = _sentences(nar)
    for i, (s0, s1) in enumerate(sents):
        w1 = sents[i + 1][1] if i + 1 < len(sents) and _time(nar, sents[i + 1][0]) - _time(nar, s0) < 10.0 else s1
        win = text[s0:w1]
        ranks: Dict[int, Tuple[str, int]] = {}
        for m in _MEDAL.finditer(win):
            for g, ng in (("m", "name"), ("m2", "name2"), ("m3", "name3"), ("m4", "name4")):
                if m.group(g):
                    name = m.group(ng)
                    r = _RANK_OF[m.group(g).lower()]
                    if _who_ok(name) and r not in ranks and name not in [x[0] for x in ranks.values()]:
                        ranks[r] = (name, s0 + m.start(ng))
        for m in _PLACE_RANK.finditer(win):
            name = m.group("name") or m.group("name2")
            r = _RANK_OF[(m.group("p") or m.group("p2")).lower()]
            if _who_ok(name) and r not in ranks and name not in [x[0] for x in ranks.values()]:
                ranks[r] = (name, s0 + m.start("name" if m.group("name") else "name2"))
        title = ""
        if len(ranks) < 3:
            m = _TOP3.search(win)
            if m and all(_who_ok(m.group(g)) for g in "abc") and len({m.group(g) for g in "abc"}) == 3:
                ranks = {1: (m.group("a"), s0 + m.start("a")), 2: (m.group("b"), s0 + m.start("b")),
                         3: (m.group("c"), s0 + m.start("c"))}
                sup = m.group("sup") or ""
                title = _phrase(("Top three " + sup) if sup else "Top three", 6)
                if sup:
                    title = _cap(re.sub(r"^\s*", "", sup))
        if sorted(ranks) != [1, 2, 3]:
            continue
        if any(ranks[r][1] < s0 or ranks[r][1] >= w1 for r in ranks):
            continue
        ev = _EVENT.search(win)
        if ev and not title:
            title = ev.group("ev")
        vals = {v["name"]: v for v in p3._named_values(win)}
        order = sorted(ranks.items())
        first_at = min(p for _r, (_n, p) in order)
        t0 = _time(nar, first_at) - 0.07
        items, ats = [], []
        for r, (name, p) in order:
            at = _time(nar, p)
            it: Dict[str, Any] = {"label": name, "at": round(max(0.0, at - t0), 2)}
            v = vals.get(name)
            if v is not None:
                it["value"] = _round(v["value"])
            items.append(it)
            ats.append(at)
        if any("value" in it for it in items) and not all("value" in it for it in items):
            for it in items:
                it.pop("value", None)
        props = {"template": PODIUM, "text": title[:36], "items": items}
        last = max(p for _r, (_n, p) in order)
        out.append(_cand(PODIUM, nar, first_at, last + 20, props, ats, score=6.5,
                         key="pd:" + "|".join(n.lower() for _r, (n, _p) in order), absorb=(s0, w1), at=t0 + 0.07))
    return out


# --------------------------------------------------------------------------- KT_VERSUS
_TEAM = rf"(?:the\s+)?{_NAME1}"
_SCORE = r"(?P<s1>\d{1,3})\s*(?:-|–|—|to)\s*(?P<s2>\d{1,3})"
_VERSUS_RX = [
    ("beat", re.compile(rf"(?P<a>{_TEAM})\s+(?i:beat|defeated|edged(?:\s+out)?|crushed|thrashed|routed|downed|stunned|"
                        rf"upset|outscored|topped|overcame|dominated|swept|hammered|demolished)\s+(?P<b>{_TEAM})\s*,?\s*"
                        rf"(?:(?i:by\s+)?(?i:a\s+score\s+of\s+)?){_SCORE}")),
    ("won", re.compile(rf"(?P<a>{_TEAM})\s+(?i:won)\s+{_SCORE}\s+(?i:against|over|versus|vs\.?)\s+(?P<b>{_TEAM})")),
    ("lost", re.compile(rf"(?P<b>{_TEAM})\s+(?i:lost)\s+(?P<s2>\d{{1,3}})\s*(?:-|–|—|to)\s*(?P<s1>\d{{1,3}})\s+(?i:to|against)\s+"
                        rf"(?P<a>{_TEAM})")),
    ("lost2", re.compile(rf"(?P<b>{_TEAM})\s+(?i:lost\s+to)\s+(?P<a>{_TEAM})\s*,?\s*{_SCORE}")),
    ("winover", re.compile(rf"(?P<a>{_TEAM})['’]s\s+{_SCORE}\s+(?i:win|victory|triumph)\s+(?i:over|against)\s+(?P<b>{_TEAM})")),
    ("votes", re.compile(rf"(?P<a>{_NAME1})\s+(?i:won|took|received|got|secured)\s+(?P<n1>{_NUM})\s+(?P<what>(?i:electoral\s+votes|"
                         rf"votes|seats|delegates))\s*,?\s*(?i:to|against|versus|compared\s+to)\s+(?P<b>{_NAME1})['’]s\s+"
                         rf"(?P<n2>{_NUM})")),
    ("army", re.compile(rf"(?P<n1>{_NUM})\s+(?P<a>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?s)\s+(?i:against|faced|versus|vs\.?|took\s+on|"
                        rf"fought|met)\s+(?P<n2>{_NUM})\s+(?P<b>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?s)\b")),
    ("withx", re.compile(rf"(?P<a>{_NAME1})\s*,?\s+(?i:with)\s+(?P<n1>{_NUM})\s+(?P<what>(?i:soldiers|troops|men|ships|tanks|"
                         rf"planes|fighters|warriors|knights|employees|stores|users|subscribers|fans|players))\s*,?\s+"
                         rf"(?i:against|faced|versus|vs\.?|took\s+on)\s+(?P<b>{_NAME1})(?:['’]s)?\s+(?:(?i:with)\s+)?"
                         rf"(?P<n2>{_NUM})")),
]
_VS_EVENT = re.compile(r"\b(?i:in|at)\s+(?i:the)\s+(?P<ev>(?:(?:19|20)\d\d\s+)?(?:[A-Z][\w'’.-]*\s+){0,4}?(?i:final|cup|"
                       r"series|bowl|championship|semifinals?|game|match|derby|classico|election|race|tournament|playoffs?|"
                       r"open)(?:\s+(?i:final|semifinal|game|match|series))?)\b|\b(?:the\s+)?(?P<battle>Battle\s+of\s+"
                       r"[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)")
# "In 2016, Trump won ...", "At Cannae, 50,000 Carthaginians ...": the year or the place said first is the event's
_VS_LEAD = re.compile(r"^\s*(?:(?i:in|by)\s+(?P<y>(?:19|20)\d\d)|(?i:at)\s+(?P<pl>[A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’-]+)?))\s*,")


def _strip_the(s: str) -> str:
    return re.sub(r"^the\s+", "", s.strip(), flags=re.I)


def find_versus(nar) -> List[dict]:
    out = []
    text = nar.text
    for kind, rx in _VERSUS_RX:
        for m in rx.finditer(text):
            a, b = _strip_the(m.group("a")), _strip_the(m.group("b"))
            if not (_who_ok(a) and _who_ok(b)) or a.lower() == b.lower():
                continue
            if kind in ("votes", "army", "withx"):
                v1, v2 = number_of(m.group("n1")), number_of(m.group("n2"))
                what = (m.groupdict().get("what") or "").lower()
                label = {"electoral votes": "Electoral votes", "votes": "Votes", "seats": "Seats",
                         "delegates": "Delegates"}.get(what, what.capitalize() if what else "Troops")
                winner = a if kind == "votes" and v1 is not None and v2 is not None and v1 > v2 else ""
            else:
                v1, v2 = number_of(m.group("s1")), number_of(m.group("s2"))
                label = "Final score"
                winner = a
                if v1 is not None and v2 is not None and v1 < v2:
                    v1, v2 = v2, v1             # "beat them 1-3" still reads winner first
            if v1 is None or v2 is None:
                continue
            s0, s1 = nar.sentence(m.start())
            ev = _VS_EVENT.search(text[max(0, s0 - 80):s1])
            title = ""
            if ev:
                title = ev.group("battle") or ev.group("ev") or ""
            if not title:
                lead = _VS_LEAD.match(text[s0:s1])
                if lead:
                    title = lead.group("y") or lead.group("pl") or ""
            ta = _time(nar, m.start("a"))
            tb = _time(nar, m.start("b"))
            t0 = min(ta, tb, _time(nar, m.start())) - 0.07
            items = [{"label": a, "value": _round(v1), "at": round(max(0.0, ta - t0), 2)},
                     {"label": b, "value": _round(v2), "at": round(max(0.0, tb - t0), 2)}]
            props: Dict[str, Any] = {"template": VERSUS, "text": title[:40], "label": label, "items": items}
            if winner:
                props["highlight"] = winner
            out.append(_cand(VERSUS, nar, m.start(), m.end(), props, [ta, tb], score=6.0,
                             key=f"vs:{a.lower()}:{b.lower()}:{v1:g}:{v2:g}", absorb=(m.start(), m.end()),
                             at=t0 + 0.07))
    out.sort(key=lambda c: c["at"])
    return out


FINDERS = (find_prices, find_tables, find_podiums, find_versus, find_cases, find_profiles, find_posts,
           find_factchecks, find_proscons, find_steps, find_chains, find_money)

# Of two looks over the same words, the more specific one (lower first): a lake's levels before a price series, a
# series before a single sum, a table before a change, a top three before a ranking.
SPECIFIC = {p3.WATERLINE: 0, TABLE: 1, PRICE: 2, PODIUM: 3, VERSUS: 4, p3.RANKING: 5, CASE: 6, PROFILE: 7, POST: 8,
            FACTCHECK: 9, PROSCONS: 10, STEPS: 11, CHAIN: 12, p3.DELTA: 13, p3.STREAK: 14, p3.SEVERITY: 15,
            p3.ALERT: 16, p3.REGIONS: 17, MONEY: 18}


def candidates(nar) -> List[dict]:
    """Every candidate of looks pack 3 and pack 4 in the narration (a rule's bug never costs the other looks)."""
    cands: List[dict] = []
    for fn in tuple(p3.FINDERS) + FINDERS:
        try:
            cands.extend(fn(nar))
        except Exception as e:  # noqa: BLE001
            print(f"[lookpack4] {fn.__name__} failed: {type(e).__name__}: {e}", flush=True)
    return cands


def find(nar, allowed: Optional[frozenset] = None, ok: Optional[Callable[[str], bool]] = None,
         skip: Sequence[Tuple[float, float]] = (), pace: Optional[p3.Pace] = None) -> Tuple[List[dict], List[dict]]:
    """
    The data moments of looks pack 3 and pack 4 in the narration (a datalooks.Narration), each one look over its
    words (`absorb`: the figures it shows are not shown again by the data planner) - never two over the same words
    (the more specific first, the next one when the pace refuses it), spaced (one Pace for both packs), only looks
    the brand kit allows (`allowed`) and the planner may pick (`ok`), none in a `skip` span (the presenter on
    camera). Returns (accepted, log rows of the ones left out).
    """
    pace = pace if pace is not None else Pace()
    log: List[dict] = []
    live: List[dict] = []
    for c in candidates(nar):
        why = ""
        if allowed is not None and c["tid"] not in allowed:
            why = "the brand kit does not allow this look"
        elif ok is not None and not ok(c["tid"]):
            why = "not picked automatically"
        elif any(a <= c["at"] < b for a, b in skip):
            why = "the presenter says it on camera"
        if why:
            log.append({"at": round(c["at"], 2), "said": c["said"], "kind": c["tid"], "look": None, "why": why})
            continue
        live.append(c)

    def overlaps(x: dict, y: dict) -> bool:
        return not (x["absorb"][1] <= y["absorb"][0] or x["absorb"][0] >= y["absorb"][1])

    # groups of candidates over the same words (connected by overlap), in time order
    live.sort(key=lambda c: (c["absorb"][0], c["at"]))
    groups: List[List[dict]] = []
    for c in live:
        if groups and any(overlaps(c, x) for x in groups[-1]):
            groups[-1].append(c)
        else:
            groups.append([c])
    groups.sort(key=lambda g: min(x["at"] for x in g))
    seen: Dict[str, float] = {}
    out: List[dict] = []
    for g in groups:
        taken: List[dict] = []
        for c in sorted(g, key=lambda x: (SPECIFIC.get(x["tid"], 50), -x["score"], x["at"])):
            why = ""
            repeat = PROFILE_REPEAT if c["tid"] == PROFILE else REPEAT
            if any(overlaps(c, x) for x in taken):
                why = "its words are another pack look's"
            elif c["key"] in seen and c["at"] - seen[c["key"]] < repeat:
                why = f"shown {c['at'] - seen[c['key']]:.0f} s before"
            elif not pace.allows(c["tid"], c["at"]):
                why = "the packs' spacing (one every 24 s, two a minute, each look its own gap and its cap)"
            if why:
                log.append({"at": round(c["at"], 2), "said": c["said"], "kind": c["tid"], "look": None, "why": why})
                continue
            pace.note(c["tid"], c["at"])
            seen[c["key"]] = c["at"]
            taken.append(c)
            out.append(c)
    out.sort(key=lambda c: c["at"])
    return out, log


# --------------------------------------------------------------------------- the profile card's picture
PICTURE_NEAR_S = 8.0        # a scene this close to the card may lend its picture when it is of the same person


def _surname(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’-]+", name) if w not in ("Jr", "Sr", "III", "II")]
    return words[-1].lower() if words else ""


def portrait_for(ov: dict, scenes: List[dict], fps: int) -> Optional[dict]:
    """
    The picture a profile card shows: a scene picture (its still, or its clip's frame) on screen at the card or
    within PICTURE_NEAR_S of it whose subject names the person (the full name, or the surname with a face found in
    it) - never the AI presenter's own face. None: the card shows the person's initials.
    """
    from .presenter import is_presenter_scene
    name = str(ov.get("text") or "").strip()
    sur = _surname(name)
    if not name or not sur:
        return None
    at = int(ov.get("startFrame") or 0)
    best = None
    for sc in scenes or []:
        if not isinstance(sc, dict) or is_presenter_scene(sc):
            continue
        st = int(sc.get("startFrame") or 0)
        en = st + int(sc.get("durationInFrames") or 0)
        d = 0 if st <= at < en else min(abs(st - at), abs(en - at)) / max(1, fps)
        if d > PICTURE_NEAR_S:
            continue
        media = sc.get("media") or {}
        if media.get("type") == "image":
            url = str(media.get("url") or "")
        elif media.get("type") == "video":
            url = str(media.get("thumbnail") or "")
        else:
            url = ""
        if not url.startswith(("http://", "https://")):
            continue
        subject = str(((sc.get("semanticMetadata") or {}).get("subject")) or "")
        low = subject.lower()
        focus = media.get("focus") if isinstance(media.get("focus"), dict) else {}
        face = bool(focus.get("faceBoxes")) or focus.get("kind") == "face"
        full = name.lower() in low
        if not (full or (sur in re.findall(r"[a-z'’-]+", low) and (face or len(sur) >= 5))):
            continue
        # someone else of the same name ("Barack Obama Sr." for "Barack Obama") is someone else
        if full and re.search(re.escape(name.lower()) + r"\s+(?:sr|jr|iii|ii)\b", low) and not re.search(
                r"\b(?:sr|jr|iii|ii)\b", name.lower()):
            continue
        score = (0 if full else 1, 0 if media.get("type") == "image" else 1, d)
        if best is None or score < best[0]:
            pic: Dict[str, Any] = {"type": "image", "url": url, "source": "scene"}
            if focus:
                keep = {k: focus[k] for k in ("faceBoxes", "box", "kind", "aspect") if k in focus}
                if keep:
                    pic["focus"] = keep
            best = (score, pic)
    return best[1] if best else None


def bind_portraits(overlays: List[dict], scenes: List[dict], fps: int) -> int:
    """Each profile card without a picture gets its person's scene picture when there is one (in place). Returns how many."""
    n = 0
    for ov in overlays or []:
        if not isinstance(ov, dict) or ov.get("template") != PROFILE:
            continue
        if any(isinstance(m, dict) and m.get("url") for m in ov.get("media") or []):
            continue
        pic = portrait_for(ov, scenes, fps)
        if pic:
            ov["media"] = [pic]
            n += 1
    return n
