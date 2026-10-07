"""
Lines planned without the model get a real plan before anything searches them again.

2026-10-07, the California video ("California's Water Clock Is Running Faster - These Cities Could Feel It
First"): it was built while OpenRouter was out of credit, so the build fell back to the rule planner
(director._rule_shot), which writes the video's TITLE as every line's subject - typed a person - and searches
"Phillips Station <the title> 2022". 113 of its 167 lines. The editor's "find choices" for scene 9 searched
those words, saw 100 candidates with a best relevance of 0.11 ("Earthquake Hits During Evening Newscast",
"The Cult - Rain HD") and found nothing in 6.4 minutes; a re-clip would have done the same on every line.

repair(doc) finds those lines - the subject is the title, or the search carries the whole title, or the
timeline marked the line as planned by rules (semanticMetadata.plannedBy, written since this change) - and
plans them again with the build's own planner (director.plan: the story brief and the per-beat model pass,
the prompts and models of a build). Only a repaired line's search fields change: scene.query and
semanticMetadata subject / subjectType / searchQuery / intent / sceneIntent / eventWindow, with
semanticMetadata.replanned saying how and what the subject was. A line the model leaves unplanned gets them
rebuilt from its own words and the story's places - never the title. Media, timing, graphics and every
other field stay. The repaired fields go into the saved timeline with the rest of a re-clip, so the editor's
"find choices" searches the new words too.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

from . import director
from . import intent as scene_intent
from .transcribe import Segment, keywords_for

# A title is a phrase of at least this many words; a two-word place ("Lake Mead") is a subject, never a title.
TITLE_MIN_WORDS = 4
# The same long subject on this share of the lines (and at least MIN_REPEATS of them) is the title.
TITLE_SHARE = 0.25
MIN_REPEATS = 3


def _norm(text) -> str:
    return " ".join(str(text or "").split()).strip()


def _low(text) -> str:
    return _norm(text).lower()


def titles_of(doc: dict, title: str = "") -> List[str]:
    """What the video's title reads as on its lines (lowercased): the job's title, the rule brief's event (a
    brief the model never read is built around the title) and a long subject on a quarter of the lines."""
    scenes = [s for s in doc.get("scenes") or [] if isinstance(s, dict)]
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    story = meta.get("story") if isinstance(meta.get("story"), dict) else {}
    found = [title, director.clean_title(title), meta.get("title")]
    if meta.get("planner") in ("rules", "mixed"):
        found.append(story.get("event"))
    counts = Counter(_norm((s.get("semanticMetadata") or {}).get("subject")) for s in scenes)
    for subject, n in counts.items():
        if subject and len(subject.split()) >= TITLE_MIN_WORDS + 1 \
                and n >= max(MIN_REPEATS, TITLE_SHARE * len(scenes)):
            found.append(subject)
    out = []
    for t in found:
        t = _low(t)
        if t and len(t.split()) >= TITLE_MIN_WORDS and t not in out:
            out.append(t)
    return out


def _is_title(subject: str, titles: List[str]) -> bool:
    s = _low(subject)
    return bool(s) and any(s == t or s == t[:120] or (len(s) >= 40 and t.startswith(s)) for t in titles)


def broken(doc: dict, titles: Optional[List[str]] = None) -> Dict[int, str]:
    """{scene index: why} for every line whose search was planned without the model."""
    titles = titles if titles is not None else titles_of(doc)
    out: Dict[int, str] = {}
    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict) or not _norm(s.get("text")):
            continue
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        query = _low(s.get("query") or sem.get("searchQuery"))
        if _is_title(sem.get("subject"), titles):
            out[i] = "its subject is the video's title"
        elif query and any(t in query for t in titles):
            out[i] = "its search carries the video's whole title"
        elif sem.get("plannedBy") == "rules" and not sem.get("replanned"):
            out[i] = "planned without the model"
    return out


def _segments(doc: dict) -> List[Segment]:
    fps = max(1, int(doc.get("fps") or 30))
    segs = []
    for s in doc.get("scenes") or []:
        start = int((s or {}).get("startFrame") or 0) / float(fps)
        end = start + max(1, int((s or {}).get("durationInFrames") or 0)) / float(fps)
        segs.append(Segment(text=_norm((s or {}).get("text")) or "...", start=start, end=end))
    return segs


def _clean_fields(shot: dict, titles: List[str]) -> Optional[dict]:
    """The model's search fields for one line, or None when they are still the title's."""
    if not isinstance(shot, dict) or shot.get("rule"):
        return None
    query = _norm(shot.get("query"))[:240]
    subject = _norm(shot.get("subject"))[:120]
    if not query or _is_title(subject, titles) or any(t in query.lower() for t in titles):
        return None
    return {"query": query, "subject": subject, "subjectType": str(shot.get("subjectType") or ""),
            "intent": _norm(shot.get("intent"))[:300], "sceneIntent": shot.get("sceneIntent") or None,
            "eventWindow": shot.get("eventWindow")}


def _line_fields(seg: Segment, brief: dict, carry: Tuple[str, str]) -> dict:
    """A line's search fields from its own words: the person or place it names, else the place the lines
    before it were about, else the story's first place - and its key words. Never the title."""
    text = seg.text
    places = [p for p, _tier in director.line_places(text, brief)]
    story_places = [p for p in (brief.get("places") or []) if isinstance(p, str) and p.strip()]
    named = [p for p in story_places if p.lower() in text.lower()]
    # (A place name reads like a person's to the name finder: "near Echo Summit".)
    people = [p for p in director._named_people(text) if p not in places and p not in story_places]
    if places or named:
        subject, kind = (places or named)[0], "place"
    elif people:
        subject, kind = people[0], "person"
    elif carry[0]:
        subject, kind = carry
    elif story_places:
        subject, kind = story_places[0], "place"
    else:
        subject, kind = "", ""
    terms = keywords_for(seg, max_terms=4)
    query = director.with_subject(subject, terms) if subject else terms
    shot = {"query": _norm(query)[:240], "subject": subject[:120], "subjectType": kind, "intent": text[:300]}
    try:
        shot["sceneIntent"] = scene_intent.SceneIntent.from_shot(shot, brief).to_dict()
    except Exception:  # noqa: BLE001 - the search alone
        shot["sceneIntent"] = None
    return shot


def repair(doc: dict, title: str = "", report: Optional[Callable] = None, model: bool = True) -> dict:
    """
    Plan every line whose search was planned without the model again (see the module notes); changes those
    lines' search fields in `doc` in place. Returns {"found", "replanned", "byModel", "byRules", "planner",
    "titles", "lines": [{index, id, why, was, subject, by}]}. Never raises: a planner that breaks leaves the
    rule rebuild.
    """
    say = report or (lambda *a, **k: None)
    scenes = doc.get("scenes") or []
    titles = titles_of(doc, title)
    bad = broken(doc, titles)
    out = {"found": len(bad), "replanned": 0, "byModel": 0, "byRules": 0, "planner": "",
           "titles": [t[:90] for t in titles][:3], "lines": []}
    if not bad:
        return out
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    brief = dict(meta.get("story") or {}) if isinstance(meta.get("story"), dict) else {}
    segs = _segments(doc)
    shots: Optional[List[dict]] = None
    if model and director.is_configured():
        say(f"Planning {len(bad)} lines again: they were planned without the model")
        try:
            shots, kind, _warns = director.plan(segs, title or (titles[0] if titles else ""), allow_maps=False)
            out["planner"] = kind
            if director.LAST_STORY:
                brief = dict(director.LAST_STORY)
        except Exception as e:  # noqa: BLE001 - the rule rebuild below
            print(f"[replan] the planner broke ({type(e).__name__}: {str(e)[:160]}); lines rebuilt from their "
                  "own words", flush=True)
            shots = None
    carry: Tuple[str, str] = ("", "")
    for i, s in enumerate(scenes):
        if not isinstance(s, dict):
            continue
        sem = s.setdefault("semanticMetadata", {})
        if i not in bad:
            if sem.get("subjectType") == "place" and _norm(sem.get("subject")) \
                    and not _is_title(sem.get("subject"), titles):
                carry = (_norm(sem.get("subject")), "place")
            continue
        fields = _clean_fields(shots[i], titles) if shots is not None and i < len(shots) else None
        by = "model"
        if fields is None:
            fields, by = _line_fields(segs[i], brief, carry), "rules"
        was = _norm(sem.get("subject"))[:120]
        s["query"] = fields["query"]
        sem["searchQuery"] = fields["query"]
        sem["subject"] = fields["subject"]
        sem["subjectType"] = fields["subjectType"]
        if fields.get("intent"):
            sem["intent"] = fields["intent"]
        sem["sceneIntent"] = fields.get("sceneIntent") or None
        if fields.get("eventWindow") is not None:
            sem["eventWindow"] = fields.get("eventWindow") or ""
        sem.pop("plannedBy", None)
        sem["replanned"] = {"by": by, "why": bad[i], "was": was}
        if fields["subjectType"] == "place" and fields["subject"]:
            carry = (fields["subject"], "place")
        out["replanned"] += 1
        out["byModel" if by == "model" else "byRules"] += 1
        out["lines"].append({"index": i, "id": s.get("id"), "why": bad[i], "was": was[:60],
                             "subject": fields["subject"][:60], "query": fields["query"][:90], "by": by})
    print(f"[replan] {out['replanned']} of {len(scenes)} lines planned again ({out['byModel']} by the model, "
          f"{out['byRules']} from their own words): {len(bad)} were planned without the model", flush=True)
    return out


def real_subjects(doc: dict, title: str = "") -> int:
    """How many lines have a subject of their own (not empty, not the video's title)."""
    titles = titles_of(doc, title)
    n = 0
    for s in doc.get("scenes") or []:
        subject = ((s or {}).get("semanticMetadata") or {}).get("subject")
        if _norm(subject) and not _is_title(subject, titles):
            n += 1
    return n
