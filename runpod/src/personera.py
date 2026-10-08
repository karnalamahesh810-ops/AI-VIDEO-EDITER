"""
People from before video existed (2026-10-09; config.PERSON_ERA_PHOTOS).

A line about a real person in an era nobody filmed them - a biography's early life (born, school, college, a first
job, a wedding), or anyone before film was common (PERSON_ERA_FILM_YEAR) - shows real PHOTOS of that person in that
era, moved with a clean camera move, before random modern clips of the places the line names or a text card.

The 2026-10-08 bench's Obama biography put a 1960s Honolulu street, Punahou's campus today, a 4K Occidental College
tour, a Harvard lawn and a UChicago drone flight under the lines about his childhood and his studies - never a picture
of him - and text cards under three more; planned the older way, its opening lines asked for "Barack Obama speaking on
camera ... 1961-1963" and stayed empty.

detect() reads the story brief (its people and cast, its kind and year), the line's words, the director's shot and its
scene intent, and returns {"person", "year", "era", "early", "stage"} for such a line (None otherwise). queries() are
its picture searches and scene() the scene intent its pictures are judged against: that person, that time. The
sourcing side is media.source_for_segment (`person_era`): these pictures first, then - for a person before film was
common, never for a private early life - one search for archive film of them, then the line's own plan.
"""
import datetime
import re
from typing import Dict, List, Optional

from . import config

# What says a line is about a private stretch of a life nobody filmed (a childhood, school, a wedding...).
_EARLY = re.compile(
    r"\b(?:born|birth|baby|infant|toddler|child|children|childhood|boyhood|girlhood|kids?|grew up|growing up|raised|"
    r"young|youth|teens?|teenage|teenager|adolescen\w*|schools?|schoolboy|schoolgirl|classmates?|students?|studied|"
    r"studying|college|university|graduat\w*|degree|parents|mother|father|grandparents?|grandmother|grandfather|"
    r"famil(?:y|ies)|siblings?|son of|daughter of|married|marry|marriage|wedding|first job|worked as|work as|"
    r"apprentice\w*|enlisted|"
    r"drafted|boot camp|scholarship)\b", re.I)
_PRONOUN = re.compile(r"\b(?:he|she|him|her|his|hers)\b", re.I)
_YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-4]\d)\b")
_DECADE = re.compile(r"\b(1[5-9]\d0|20[0-4]0)s\b")
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "senior", "junior"}
# A life stage the picture search can name, checked in this order ("school" alone is a child's; a college, a
# university or a law school a student's).
_STAGES = (("baby", re.compile(r"\b(?:born|birth|baby|infant|toddler)\b", re.I)),
           ("wedding", re.compile(r"\b(?:married|marry|marriage|wedding)\b", re.I)),
           ("student", re.compile(r"\b(?:students?|studied|studying|college|university|graduat\w*|degree|"
                                  r"law school|classmates?)\b", re.I)),
           ("child", re.compile(r"\b(?:child|childhood|boyhood|girlhood|kids?|grew up|growing up|raised|schools?|"
                                r"schoolboy|schoolgirl|grandparents?)\b", re.I)))
_STAGE_WORDS = {"baby": "as a baby", "child": "as a child", "student": "as a student", "wedding": "wedding"}
# An age the line gives ("until he was ten", "when she was 7", "at age 9"): a child, whatever else it names.
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12}
_AGE = re.compile(r"\b(?:when|until|by the time|before|after) (?:he|she|they) (?:was|were|turned) (?:a )?"
                  r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b|"
                  r"\bat (?:the )?age (?:of )?(\d{1,2})\b", re.I)


def enabled() -> bool:
    return bool(getattr(config, "PERSON_ERA_PHOTOS", False))


def story_people(brief: Optional[dict]) -> List[str]:
    """The story's people, its cast first (the brief's own order: the lead first)."""
    b = brief if isinstance(brief, dict) else {}
    names: List[str] = []
    for c in b.get("cast") or []:
        if isinstance(c, dict) and str(c.get("name") or "").strip():
            names.append(str(c["name"]).strip())
    for p in b.get("people") or []:
        if isinstance(p, str) and p.strip():
            names.append(p.strip())
    out: List[str] = []
    for n in names:
        if n.lower() not in {o.lower() for o in out}:
            out.append(n)
    return out[:8]


def _surname(name: str) -> str:
    words = [w.strip(".,'\"()").lower() for w in name.split()]
    words = [w for w in words if w and w not in _SUFFIX]
    return words[-1] if len(words) >= 2 else ""


def _first_mention(text: str, name: str) -> Optional[int]:
    """Where the line names this person first: the full name, else the surname (at least 4 letters)."""
    low = (text or "").lower()
    full = re.search(rf"\b{re.escape(name.lower())}(?!\w)", low)      # ("Sr." ends on a dot: no \b after it)
    if full:
        return full.start()
    sur = _surname(name)
    if len(sur) >= 4:
        m = re.search(rf"\b{re.escape(sur)}\b", low)
        if m:
            return m.start()
    return None


def named_person(text: str, people: List[str]) -> str:
    """The story person this text names first ("" = none). Two names met at the same place: the longer full name
    ("Barack Obama Sr." over "Barack Obama" on "Barack Obama Sr. was..."); a surname alone ("Obama"): the one the
    story names first - its lead."""
    best = None
    low = (text or "").lower()
    for k, name in enumerate(people or []):
        at = _first_mention(text, name)
        if at is None:
            continue
        full = re.search(rf"\b{re.escape(name.lower())}(?!\w)", low)
        full_at = full.start() if full else None
        key = (at, 0, -len(name)) if full_at == at else (at, 1, k)
        if best is None or key < best[0]:
            best = (key, name)
    return best[1] if best else ""


def line_year(text: str, scene: Optional[dict], brief: Optional[dict]) -> Optional[int]:
    """The year a line is about: one it says, else its scene intent's time (a year, the first of a range, a
    decade), else - its time historical or unknown - the story's year."""
    m = _YEAR.search(text or "")
    if m:
        return int(m.group(1))
    si = scene if isinstance(scene, dict) else {}
    t = str(si.get("time_context") or "").strip().lower()
    m = _YEAR.search(t)
    if m:
        return int(m.group(1))
    m = _DECADE.search(t)
    if m:
        return int(m.group(1))
    if t in ("current", "recent"):
        return None
    b = brief if isinstance(brief, dict) else {}
    y = b.get("year")
    return y if isinstance(y, int) and not isinstance(y, bool) else None


def stage_of(text: str) -> str:
    """The life stage a line names ("baby", "child", "student", "wedding"; "" = none). An age of twelve or under the
    line gives makes it a child's ("a student from Kenya. His parents separated when he was two")."""
    m = _AGE.search(text or "")
    if m:
        raw = (m.group(1) or m.group(2) or "").lower()
        age = _NUMBERS.get(raw) if not raw.isdigit() else int(raw)
        if age is not None and age <= 12:
            return "baby" if age <= 1 else "child"
    for name, rx in _STAGES:
        if rx.search(text or ""):
            return name
    return ""


def detect(text: str, shot: Optional[dict], brief: Optional[dict],
           today: Optional[datetime.date] = None, prev: Optional[Dict] = None) -> Optional[Dict]:
    """
    {"person", "year", "era", "early", "stage"} for a line about a real person in an era nobody filmed them, else
    None:
      - the person: a story person the line (or its scene intent, or the shot's subject) names; in a biography, a
        line that names no other story person is about its subject (the lead);
      - the time: the line's year (line_year; a line that says none goes on from `prev`, the line before's
        result - a life is told in order) at least PERSON_ERA_YEARS back;
      - unfilmed: before PERSON_ERA_FILM_YEAR, or the line is about a private stretch of the life (born, school,
        college, a first job, a wedding: _EARLY) - a public life after film (a speech, a launch) keeps its footage.
    """
    if not enabled():
        return None
    people = story_people(brief)
    if not people:
        return None
    b = brief if isinstance(brief, dict) else {}
    shot = shot if isinstance(shot, dict) else {}
    si = shot.get("sceneIntent") if isinstance(shot.get("sceneIntent"), dict) else {}
    bio = str(b.get("kind") or "") == "biography"
    person = named_person(text, people)
    if person and bio and person != people[0]:
        # "he taught constitutional law, married Michelle Robinson": the biography's subject, told by a pronoun
        # before another person is named, is who the line is about.
        pro = _PRONOUN.search(text or "")
        at = _first_mention(text, person)
        if pro and at is not None and pro.start() < at and _first_mention(text, people[0]) is None:
            person = people[0]
    if not person:
        person = named_person(" ; ".join([str(e) for e in (si.get("entities") or [])] + [str(shot.get("subject") or "")]),
                              people)
    if not person and bio:
        person = people[0]
    if not person:
        return None
    year = line_year(text, si, b)
    if year is None and isinstance(prev, dict) and prev.get("year"):
        year = int(prev["year"])
    if year is None:
        return None
    today = today or datetime.date.today()
    back = int(getattr(config, "PERSON_ERA_YEARS", 8) or 0)
    if year > today.year - back:
        return None
    early = bool(_EARLY.search(text or ""))
    film = int(getattr(config, "PERSON_ERA_FILM_YEAR", 1950) or 0)
    if not (year < film or early):
        return None
    return {"person": person, "year": year, "era": f"{year // 10 * 10}s", "early": early, "stage": stage_of(text)}


def _place(scene: Optional[dict], person: str) -> str:
    si = scene if isinstance(scene, dict) else {}
    for v in list(si.get("entities") or []) + list(si.get("locations") or []):
        v = str(v or "").split(",")[0].strip()
        if v and v.lower() != person.lower() and not named_person(v, [person]):
            return v[:60]
    return ""


def queries(pe: Dict, scene: Optional[dict] = None, limit: int = 3) -> List[str]:
    """The picture searches for a person-era line, most specific first: the person at that stage of life or in that
    year, the person at the line's place, the person in that decade."""
    person, year, era = pe["person"], int(pe["year"]), pe.get("era") or f"{int(pe['year']) // 10 * 10}s"
    place = _place(scene, person)
    stage = pe.get("stage") or ""
    out: List[str] = []
    if pe.get("early"):
        out.append(f"{person} {_STAGE_WORDS[stage]} photo" if stage else f"young {person} {year} photo")
        if place:
            out.append(f"{person} {place} {year} photo")
    else:
        out.append(f"{person} {year} photo")
        if place:
            out.append(f"{person} {place} photo")
    out.append(f"{person} {era} photograph")
    seen, res = set(), []
    for q in out:
        q = " ".join(q.split())
        if q.lower() not in seen:
            seen.add(q.lower())
            res.append(q)
    return res[:max(1, int(limit))]


def clip_query(pe: Dict) -> str:
    """The one search for archive film of a person before film was common (never for a private early life)."""
    return f"{pe['person']} {int(pe['year'])} archival footage"


def scene(pe: Dict, line_scene: Optional[dict] = None) -> dict:
    """The scene intent a person-era picture is judged against: that person (ENTITIES), the line's places, that
    time - any photograph of them then, not the line's exact moment."""
    si = line_scene if isinstance(line_scene, dict) else {}
    stage = pe.get("stage") or ""
    return {"entities": [pe["person"]], "locations": list(si.get("locations") or [])[:2],
            "event_type": "", "visual_subjects": [f"{pe['person']} {_STAGE_WORDS[stage]}" if stage
                                                  else f"{pe['person']} around {pe['year']}"],
            "desired_shots": ["portrait", "archival"],
            "time_context": str(si.get("time_context") or pe["year"]) if pe.get("early") else str(pe["year"]),
            "specificity": "generic", "generic_ok": True}


def intent(pe: Dict, line: str = "") -> str:
    """What a person-era picture must show, for the judge."""
    stage = pe.get("stage") or ""
    when = f"{_STAGE_WORDS[stage]}, around {pe['year']}" if stage else f"around {pe['year']} ({pe.get('era')})"
    return (f"A real period photograph of {pe['person']} {when} - the person themselves at that time of their life, "
            f"as the line tells it: {str(line or '')[:160]}")[:300]
