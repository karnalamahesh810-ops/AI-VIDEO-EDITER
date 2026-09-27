"""
Typed scene intent: what a beat must show, as data that ranking, the query
expander and the vision judge can check.

The planner's free-text `intent` ("Lake Mead 2026 exposed shoreline aerial
footage (Nevada, 2026)") stays for the vision prompt. But nothing could tell
its place from its year from its subject, so a flooded street on another
continent could pass on the strength of the word "flood". This object names
the entities, the locations, the event and the time separately, classes the
scene as event / location / generic, and turns itself into the searches a
researcher would actually type, specific first.
"""
import datetime
import math
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

from . import config

SPECIFICITY = ("event", "location", "generic")

# What a desired shot type adds to a search. Empty means the type is real
# but changes no words: a search engine has no "medium shot".
SHOT_WORDS = {
    "aerial": "aerial drone footage", "drone": "aerial drone footage",
    "wide": "wide shot", "establishing": "establishing shot",
    "detail": "close up", "close": "close up", "closeup": "close up",
    "human": "people", "crowd": "crowd", "night": "at night",
    "interior": "interior", "exterior": "exterior",
    "archival": "archival footage", "news": "news footage",
    "satellite": "satellite view", "timelapse": "timelapse",
    "portrait": "portrait photo",
    "medium": "", "activity": "", "infrastructure": "", "map": "", "data": "",
}
_STOP = {"the", "of", "a", "an", "and", "in", "at", "on", "to", "for", "de", "la", "le",
         "county", "city", "state", "river", "lake", "dam", "mount", "mt", "st", "san"}
# Words that name half the map: on their own they prove nothing.
_GENERIC_WORDS = {"north", "south", "east", "west", "united", "states", "national",
                  "park", "valley", "creek", "island", "beach", "canyon", "america",
                  "american", "central", "great", "grand"}
_PLACE_KINDS = {"natural-feature", "landmark", "building", "city-region"}
_EVENT_KINDS = {"news", "weather", "disaster"}


def _today() -> datetime.date:
    return datetime.date.today()


def _clean_list(raw, limit: int = 6, width: int = 60) -> List[str]:
    out: List[str] = []
    for item in (raw if isinstance(raw, list) else []):
        s = re.sub(r"\s+", " ", str(item or "")).strip(" .,;")
        if s and s.lower() not in {o.lower() for o in out}:
            out.append(s[:width])
        if len(out) >= limit:
            break
    return out


def _words(text: str) -> set:
    text = re.sub(r"'s\b", "", (text or "").lower())      # Obama's -> obama
    return {w for w in re.findall(r"[a-z0-9]+", text)
            if len(w) > 2 and w not in _STOP}


def _phrase_hit(phrase: str, title_words: set) -> bool:
    """
    Does a title name this phrase? All of its real words, or its one
    distinctive word: "Obama" carries "Barack Obama Sr.", "Mexico" carries
    "New Mexico", but "New" alone does not.
    """
    ws = _words(phrase.split(",")[0])
    if not ws:
        return False
    if ws <= title_words:
        return True
    return any(len(w) >= 5 and w not in _GENERIC_WORDS and w in title_words for w in ws)


def _dedupe(items: List[str], width: int = 120) -> List[str]:
    out: List[str] = []
    seen = set()
    for q in items:
        q = re.sub(r"\s+", " ", (q or "")).strip()[:width]
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out


@dataclass
class SceneIntent:
    entities: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    event_type: str = ""
    visual_subjects: List[str] = field(default_factory=list)
    desired_shots: List[str] = field(default_factory=list)
    # current | recent | historical | a year ("1964") | a decade ("1960s")
    time_context: str = "unknown"
    # event: only that event at that place will do. location: the place must
    # match, the moment need not. generic: illustrative footage is fine.
    specificity: str = "generic"
    generic_ok: bool = True

    # ----------------------------------------------------------------- build
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "SceneIntent":
        d = d if isinstance(d, dict) else {}
        spec = d.get("specificity")
        return cls(
            entities=_clean_list(d.get("entities")),
            locations=_clean_list(d.get("locations")),
            event_type=re.sub(r"\s+", " ", str(d.get("event_type") or "")).strip()[:80],
            visual_subjects=_clean_list(d.get("visual_subjects")),
            desired_shots=[s.lower() for s in _clean_list(d.get("desired_shots"), 4, 30)],
            time_context=str(d.get("time_context") or "unknown").strip().lower()[:20],
            specificity=spec if spec in SPECIFICITY else "generic",
            generic_ok=bool(d.get("generic_ok", True)),
        )

    @classmethod
    def from_shot(cls, shot: dict, story: Optional[dict] = None) -> "SceneIntent":
        """The intent a shot implies when the planner gave none (rule shots, old plans)."""
        story = story or {}
        kind = story.get("kind") or ""
        anchored = shot.get("anchor") is not False and kind in _EVENT_KINDS
        subject = re.sub(r"\s+", " ", str(shot.get("subject") or "")).strip()
        entity = shot.get("entity") or ""
        year = story.get("year")
        if story.get("recent"):
            when = "current"
        elif year:
            when = str(year)
        else:
            when = "unknown"
        if anchored:
            spec = "event"
        elif entity in _PLACE_KINDS or shot.get("subjectType") == "place":
            spec = "location"
        else:
            spec = "generic"
        return cls(
            entities=[subject[:60]] if subject else [],
            locations=_clean_list(story.get("places"), 2) if anchored else [],
            event_type=(str(story.get("event") or "")[:80] if anchored else ""),
            visual_subjects=[],
            desired_shots=["aerial"] if entity in {"natural-feature", "city-region", "landmark"} else [],
            time_context=when,
            specificity=spec,
            generic_ok=spec == "generic",
        )

    @classmethod
    def parse(cls, raw, shot: dict, story: Optional[dict] = None) -> "SceneIntent":
        """The model's `scene` object, with its gaps filled from the shot and story."""
        base = cls.from_shot(shot, story)
        if not isinstance(raw, dict):
            return base
        got = cls.from_dict({
            "entities": raw.get("entities"),
            "locations": raw.get("locations"),
            "event_type": raw.get("eventType") or raw.get("event_type"),
            "visual_subjects": raw.get("visualSubjects") or raw.get("visual_subjects"),
            "desired_shots": raw.get("desiredShots") or raw.get("desired_shots"),
            "time_context": raw.get("timeContext") or raw.get("time_context") or base.time_context,
            "specificity": raw.get("specificity") or base.specificity,
            "generic_ok": raw.get("genericOk", raw.get("generic_ok", base.generic_ok)),
        })
        # The named subject is always an entity: the search is built on it.
        if base.entities and not any(_phrase_hit(base.entities[0], _words(e)) for e in got.entities):
            got.entities = (got.entities + base.entities)[:6]
        if not got.locations:
            got.locations = base.locations
        if not got.event_type:
            got.event_type = base.event_type
        if not got.desired_shots:
            got.desired_shots = base.desired_shots
        # A beat anchored to a news, weather or disaster story is about that
        # event whatever the model said, unless it marked the beat a metaphor.
        if base.specificity == "event":
            got.specificity = "event"
            got.generic_ok = False
        return got

    # ------------------------------------------------------------------ use
    @property
    def is_empty(self) -> bool:
        return not (self.entities or self.locations or self.visual_subjects)

    def when_words(self) -> str:
        """The year or decade a search should carry, or ''."""
        t = (self.time_context or "").strip().lower()
        if t in ("current", "recent"):
            return str(_today().year)
        if re.fullmatch(r"(1[89]|20)\d\d", t) or re.fullmatch(r"(1[89]|20)\d0s", t):
            return t
        return ""

    def is_historical(self) -> bool:
        t = (self.time_context or "").strip().lower()
        if t == "historical":
            return True
        m = re.match(r"(1[89]|20)\d\d", t)
        return bool(m) and int(t[:4]) < _today().year - 3

    def medium(self) -> str:
        if self.is_historical():
            return "archival footage"
        if self.specificity == "event":
            return "news footage"
        return "footage"

    def queries(self, base_query: str = "", max_n: Optional[int] = None) -> List[str]:
        """
        The searches this intent expands to, most specific first, the
        planner's own query first of all. Bounded, deduplicated, on topic:
        every one names an entity or a location.
        """
        n = max_n or config.INTENT_QUERIES_MAX
        ents = self.entities[:2]
        locs = [l.split(",")[0].strip() for l in self.locations[:2]]
        subjects = self.visual_subjects[:3]
        shots = [SHOT_WORDS.get(s.split()[0], "") for s in self.desired_shots[:3] if s]
        when = self.when_words()
        medium = self.medium()
        e0 = ents[0] if ents else ""
        l0 = locs[0] if locs else ""
        out = [base_query]
        if e0 and subjects:
            out += [f"{e0} {v}" for v in subjects]
        if e0 and l0 and subjects and l0.lower() not in e0.lower():
            out.append(f"{e0} {l0} {subjects[0]}")
        if e0:
            out += [f"{e0} {s}" for s in shots if s]
        if e0 and when:
            out.append(f"{e0} {when} {medium}")
        if e0 and self.event_type:
            out.append(f"{e0} {self.event_type}")
        if l0 and self.event_type and l0.lower() not in e0.lower():
            out.append(f"{l0} {self.event_type} {when}".strip())
        if e0 and l0 and l0.lower() not in e0.lower():
            out.append(f"{e0} {l0} {medium}")
        for e in ents[1:]:
            out.append(f"{e} {subjects[0] if subjects else medium}")
        if e0:
            out.append(f"{e0} {medium}")
        return _dedupe(out)[:max(1, n)]

    def title_match(self, title: str) -> Tuple[int, int, int]:
        """(entities, locations, visual subjects) a title names."""
        tw = _words(title)
        return (sum(_phrase_hit(e, tw) for e in self.entities),
                sum(_phrase_hit(l, tw) for l in self.locations),
                sum(_phrase_hit(v, tw) for v in self.visual_subjects))

    def vision_lines(self) -> str:
        """The lines the vision judge reads under INTENT."""
        lines = []
        if self.entities:
            lines.append("ENTITIES: " + "; ".join(self.entities))
        if self.locations:
            lines.append("LOCATIONS: " + "; ".join(self.locations))
        if self.event_type:
            lines.append("EVENT: " + self.event_type)
        if self.time_context and self.time_context != "unknown":
            lines.append("TIME: " + self.time_context)
        if self.specificity == "event":
            lines.append("SPECIFICITY: event - the frames must show THIS event at THIS place; "
                         "the same kind of thing elsewhere scores below 0.7.")
        elif self.specificity == "location":
            lines.append("SPECIFICITY: location - the frames must show THIS place; "
                         "the moment need not be a particular event.")
        else:
            lines.append("SPECIFICITY: generic - illustrative footage of the subject is acceptable.")
        return "\n".join(lines) + "\n" if lines else ""
