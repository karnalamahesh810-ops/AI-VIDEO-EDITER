"""
The look pack's planner rules (2026-10-07, the owner: "build more interesting animations and overlays - best
quality ones, Premiere Pro / After Effects kind, perfect size"). Twelve looks in the kinetic-type system
(remotion/src/components/lib/LibKtPack.tsx, LibKtPictures.tsx, LibKtMaps.tsx; registry family "ktp",
scripts/library_looks_ktpack.json), each picked only where the narration fits it, with the line's own words:

  KT_QUOTE       a quote in quotation marks with its speaker named as said (or a named person of the story)
  KT_TERM        a word the line defines ("what engineers call dead pool - the level where ...")
  KT_LEVEL       "27 percent full", "22 percent of capacity": a share of a reservoir, a lake, storage (datalooks)
  KT_TREND       three or more years with their figures (the series), turn about with the premium graph
  KT_MILESTONES  three to five years said one after another, each with its event (datalooks)
  KT_POINTER     a thing the line points at that vision found in the frame (marks.py, in turn with the vm- marks)
  KT_CHAPTER     a real section start (the brief's sections), in turn with the pack's own chapter card
  KT_EVIDENCE    a photo of the place or thing named, over a weak clip of it (the photo window's moment)
  KT_THEN_NOW    a still whose line says then and now (two pictures of the subject, bound after the plan)
  KT_TWO_PLACES  two places named together, each on its own picture in the two scenes the line spans
  KT_LOCATOR     a place on the map (the place maps' rotation)
  KT_PLACE       a place named again on footage of it, while a map was shown a moment ago

Density (the owner: "use it where it matters, and don't use the same one repeatedly"): one pack look (of the
treatments planner's) at least PACK_GAP seconds after another and at most PACK_PER_MINUTE in any minute; each
look its own EVERY spacing; a look shown in the last four minutes is tried first only when nothing fresher
fits (treatments LOOK_GAP). Pure functions: no network, no paid calls.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

QUOTE = "KT_QUOTE"
TERM = "KT_TERM"
LEVEL = "KT_LEVEL"
TREND = "KT_TREND"
MILESTONES = "KT_MILESTONES"
POINTER = "KT_POINTER"
CHAPTER = "KT_CHAPTER"
EVIDENCE = "KT_EVIDENCE"
THEN_NOW = "KT_THEN_NOW"
TWO_PLACES = "KT_TWO_PLACES"
LOCATOR = "KT_LOCATOR"
PLACE = "KT_PLACE"
IDS = (QUOTE, TERM, LEVEL, TREND, MILESTONES, POINTER, CHAPTER, EVIDENCE, THEN_NOW, TWO_PLACES, LOCATOR, PLACE)
# The ones the treatments planner places (the data planner places the level and the milestones, marks the pointer).
PLANNED = (QUOTE, TERM, TREND, CHAPTER, EVIDENCE, THEN_NOW, TWO_PLACES, LOCATOR, PLACE)

PACK_GAP = 20.0             # seconds between two pack looks laid by the planner
PACK_WINDOW = 60.0          # ... and at most PACK_PER_MINUTE of them in any such window
PACK_PER_MINUTE = 2
# Each look's own spacing (seconds from its last start): a quote or a place tag may come back sooner than a map.
EVERY: Dict[str, float] = {QUOTE: 45.0, TERM: 60.0, TREND: 75.0, CHAPTER: 90.0, EVIDENCE: 60.0, THEN_NOW: 120.0,
                           TWO_PLACES: 120.0, LOCATOR: 75.0, PLACE: 40.0}
MAP_REST = 60.0             # a place named again this soon after a map: its place tag, not another map


def variant_of(tid: str) -> str:
    """KT_THEN_NOW -> 'kt-then-now'."""
    return "kt-" + tid[3:].lower().replace("_", "-")


class Pace:
    """When the planner laid each pack look: allows() says whether one more may land at `at`."""

    def __init__(self) -> None:
        self.placed: List[Tuple[str, float]] = []

    def allows(self, tid: str, at: float) -> bool:
        if tid not in PLANNED:
            return True
        if any(abs(at - t) < PACK_GAP for _x, t in self.placed):
            return False
        if sum(1 for _x, t in self.placed if 0 <= at - t < PACK_WINDOW) >= PACK_PER_MINUTE:
            return False
        last = max((t for x, t in self.placed if x == tid), default=None)
        return last is None or at - last >= EVERY.get(tid, 60.0)

    def note(self, tid: str, at: float) -> None:
        if tid in PLANNED:
            self.placed.append((tid, float(at)))


# --------------------------------------------------------------------------- the pull quote
_QUOTED = re.compile(r"[“\"]([^”\"]{12,160})[”\"]")


def quote_text(line: str) -> str:
    """The words a line quotes (in quotation marks), as said; '' when it quotes nothing."""
    m = _QUOTED.search(line or "")
    if not m:
        return ""
    q = re.sub(r"\s+", " ", m.group(1)).strip().strip(",;:")
    return q if 3 <= len(q.split()) <= 22 and len(q) <= 120 else ""


def quote_props(line: str, speaker: str = "", role: str = "", key: str = "") -> Optional[dict]:
    """
    The pull quote's props for a line that quotes someone it names: the quoted words, the speaker as the line
    (or the story's cast) names them, their role when known, and the key phrase the underline marks (the
    planner's, else the quote's strongest words: a superlative, a negation, a figure). None without a quote
    in quotation marks or without a speaker - an unattributed line is a statement, not a pull quote.
    """
    q = quote_text(line)
    speaker = re.sub(r"\s+", " ", speaker or "").strip(" ,.")
    if not q or not speaker or len(speaker) > 40:
        return None
    props = {"text": q, "label": speaker}
    if role and len(role) <= 60 and role.lower() != speaker.lower():
        props["subtitle"] = role
    hl = key if key and key.lower() in q.lower() else strong_words(q)
    if hl:
        props["highlight"] = hl
    return props


_STRONG = re.compile(
    r"\b((?:never|not|no longer|nothing|nobody|every|all|only|first|last|worst|best|lowest|highest|biggest|largest|"
    r"driest|deepest|record)(?:\s+[\w'’-]+){1,3})", re.I)
_TAIL_SKIP = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "or", "but", "is", "was", "be", "this",
              "that", "it", "we", "i", "you", "they", "our", "its"}


def strong_words(quote: str) -> str:
    """The quote's strongest two to four words, as said ("never seen it this low"), or ''."""
    m = _STRONG.search(quote or "")
    if not m:
        m = re.search(r"(\$?\d[\d,.]*\s*(?:%|percent|feet|million|billion|acre-feet|years?)?)", quote or "", re.I)
        return m.group(1).strip() if m and len(m.group(1)) >= 2 else ""
    words = m.group(1).split()
    while len(words) > 2 and words[-1].lower().strip(",.;:") in _TAIL_SKIP:
        words.pop()
    return " ".join(words).strip(",.;:")


# --------------------------------------------------------------------------- the term card
_DEF_AFTER = re.compile(r"^[\s\"”’']*(?:[,:;\-–—]\s*)?(?:(?:which|that)\s+(?:is|means|was)\s+|meaning\s+|or\s+|i\.e\.\s*,?\s*|"
                        r"basically\s+|essentially\s+)?", re.I)
_DEF_BEFORE = re.compile(r"(?:^|[.;!?]\s+)([^.;!?]{12,140}?)\s+(?:is|are|was)\s+(?:what(?:'s| is)?\s+)?(?:(?:engineers|scientists|"
                         r"experts|officials|hydrologists|people|they|we|you)\s+)?(?:call(?:ed|s)?|known as|dubbed|termed)\s*$",
                         re.I)


def _sentence_end(s: str) -> str:
    m = re.match(r"([^.!?]*)", s)
    return (m.group(1) if m else s).strip(" ,;:-–—\"”")


def definition_of(line: str, term: str) -> str:
    """
    The meaning of `term` as the line says it: what follows it ("dead pool - the level where water can no
    longer pass the dam"), else what precedes the naming ("the level where water stops ... is what engineers
    call dead pool"); four to sixteen words, the first letter capitalised; '' when the line defines nothing.
    """
    text = re.sub(r"\s+", " ", line or "").strip()
    t = (term or "").strip()
    if not text or not t:
        return ""
    at = text.lower().find(t.lower())
    if at < 0:
        return ""
    out = ""
    after = text[at + len(t):]
    lead = _DEF_AFTER.match(after)
    if lead and lead.end() > 0 and re.match(r"^[\s\"”’']*[,:;\-–—]|^\s*(?:which|that|meaning|or)\b", after, re.I):
        out = _sentence_end(after[lead.end():])
    if len(out.split()) < 4:
        before = _DEF_BEFORE.search(text[:at].rstrip(" \"“'"))
        out = before.group(1).strip(" ,;:-–—") if before else ""
        out = re.sub(r"^(?:and|but|so|because|now|then)\s+", "", out, flags=re.I)
    words = out.split()
    if not 4 <= len(words) <= 16 or len(out) > 110:
        return ""
    return out[:1].upper() + out[1:]


def term_props(line: str, term: str) -> Optional[dict]:
    """The term card's props, or None when the line does not say what the term means."""
    meaning = definition_of(line, term)
    t = (term or "").strip(" .,'\"”’")
    if not meaning or not 3 <= len(t) <= 28:
        return None
    return {"text": t[:1].upper() + t[1:] if t.islower() else t, "subtitle": meaning, "label": "Definition"}


# --------------------------------------------------------------------------- the trend line
_YEAR = re.compile(r"^(1[5-9]\d\d|20\d\d)$")


def trend_fits(items) -> bool:
    """Three to eight points, each a year with a figure, years rising, not all one value."""
    rows = [it for it in (items or []) if isinstance(it, dict)]
    if not 3 <= len(rows) <= 8:
        return False
    years, vals = [], []
    for it in rows:
        lab = str(it.get("label") or "").strip()
        v = it.get("value")
        if not _YEAR.match(lab) or not isinstance(v, (int, float)) or isinstance(v, bool):
            return False
        years.append(int(lab))
        vals.append(float(v))
    return all(b > a for a, b in zip(years, years[1:])) and max(vals) > min(vals)


# --------------------------------------------------------------------------- places
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "lake", "river", "city", "county", "united", "states"}


def place_name(label: str) -> str:
    """The name a gazetteer label starts with ("Las Vegas, Nevada, United States" -> "Las Vegas")."""
    return str(label or "").split(",")[0].strip()


def shows_place(place: str, subject: str) -> bool:
    """The shot's subject is the place (or in it): "Las Vegas Strip" shows "Las Vegas"."""
    a = {w for w in _WORD.findall(place.lower()) if w not in _STOP}
    b = {w for w in _WORD.findall((subject or "").lower()) if w not in _STOP}
    return bool(a) and a <= b


def place_tag_props(loc: dict) -> Optional[dict]:
    """The place tag's props for one gazetteer place: its location, the name as the label starts."""
    if not isinstance(loc, dict) or not isinstance(loc.get("lat"), (int, float)) or not isinstance(loc.get("lon"), (int, float)):
        return None
    name = place_name(loc.get("label") or "")
    if not 2 <= len(name) <= 26:
        return None
    return {"text": name, "locations": [loc]}


def chapter_props(title: str, number: Optional[int]) -> Optional[dict]:
    """The chapter card's props: the section's title as the hint gave it, its number when there is one."""
    t = re.sub(r"\s+", " ", title or "").strip(" .:-")
    if not 2 <= len(t) <= 48:
        return None
    out: Dict[str, object] = {"text": t}
    if isinstance(number, int) and 1 <= number <= 99:
        out.update(value=number, label="Chapter")
    return out
