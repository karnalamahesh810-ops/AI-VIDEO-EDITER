"""
The candidate pool for one scene.

Every search result the providers returned for a scene lands here,
deduplicated, and is scored on cheap metadata against the typed scene
intent before anything is downloaded. The best few are then verified by
vision, and a combined score - visual, entity and place, narration match,
moment, quality, recency, source, minus reuse penalties - picks the winner.
The runners-up stay with the scene as its alternatives.

Weights are configuration, not code: META_WEIGHTS and FINAL_WEIGHTS in
config (JSON in the environment), and KIND_ADJUST moves weight toward
recency and place for news and weather stories, toward entity and visual
match for history and biography.
"""
import json
import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from . import config
from .intent import SceneIntent, _phrase_hit, _words

DEFAULT_META_WEIGHTS = {"semantic": 0.30, "entity": 0.25, "location": 0.15, "event_time": 0.10,
                        "title": 0.10, "quality": 0.05, "source": 0.05}
DEFAULT_FINAL_WEIGHTS = {"visual": 0.35, "entity_location": 0.25, "narration": 0.15,
                         "timestamp": 0.10, "quality": 0.05, "recency": 0.05, "source": 0.05}
# Story kinds move weight; the sum stays 1.0.
KIND_ADJUST = {
    "news": {"recency": 0.05, "entity_location": 0.05, "narration": -0.05, "quality": -0.05},
    "weather": {"recency": 0.05, "entity_location": 0.05, "narration": -0.05, "quality": -0.05},
    "disaster": {"recency": 0.05, "entity_location": 0.05, "narration": -0.05, "quality": -0.05},
    "history": {"entity_location": 0.05, "visual": 0.05, "recency": -0.05, "timestamp": -0.05},
    "biography": {"entity_location": 0.05, "visual": 0.05, "recency": -0.05, "timestamp": -0.05},
}
REUSE_PENALTY = {"same_source": -0.15, "same_source_recent": -0.30, "same_channel": -0.05}
SOURCE_CONFIDENCE = {"channel": 1.0, "library": 1.0, "google": 0.7, "search": 0.5, "": 0.5}

_TALKING = re.compile(r"\b(interview|podcast|reacts?|reaction|explained|review|vlog|q&a|"
                      r"commentary|live stream|livestream|webinar|lecture|tutorial|"
                      r"how to|unboxing|gameplay|walkthrough)\b", re.I)
_BROLL = re.compile(r"\b(aerial|drone|footage|4k|b-?roll|raw|timelapse|time-lapse|"
                    r"cinematic|flyover|fly-over|scenic|documentary|archival|newsreel)\b", re.I)


def _weights(raw: Optional[dict], defaults: dict) -> dict:
    w = dict(defaults)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in w:
                try:
                    w[k] = max(0.0, float(v))
                except (TypeError, ValueError):
                    pass
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def meta_weights() -> dict:
    return _weights(config.META_WEIGHTS, DEFAULT_META_WEIGHTS)


def final_weights(story_kind: str = "") -> dict:
    w = _weights(config.FINAL_WEIGHTS, DEFAULT_FINAL_WEIGHTS)
    for k, d in (KIND_ADJUST.get(story_kind or "") or {}).items():
        w[k] = max(0.0, w.get(k, 0.0) + d)
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


@dataclass
class Candidate:
    provider: str
    id: str
    title: str
    seconds: float = 0.0
    aspect: float = 0.0
    channel: str = ""
    upload_date: str = ""          # YYYYMMDD when the provider says
    query: str = ""
    variant: str = ""
    via: str = "search"            # search | google | channel | library
    metadata: float = 0.0          # 0..1
    parts: Dict[str, float] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    def row(self) -> dict:
        """The provider's own row shape, for the download and scouting code."""
        return dict(self.raw, id=self.id, title=self.title, duration=self.seconds,
                    aspect=self.aspect, channel=self.channel)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def metadata_score(cand: Candidate, intent: Optional[SceneIntent], query: str,
                   seconds: float, weights: Optional[dict] = None,
                   this_year: Optional[int] = None) -> Tuple[float, Dict[str, float]]:
    """
    0..1 from title and metadata alone: no download, no model call.

    Each part is 0..1; a part the intent cannot judge (no locations named)
    sits at 0.5 so it neither helps nor hurts.
    """
    w = weights or meta_weights()
    title = cand.title or ""
    tw = _words(title)
    parts: Dict[str, float] = {}

    qw = _words(query)
    parts["semantic"] = (len(qw & tw) / len(qw)) if qw else 0.5

    if intent and intent.entities:
        hits = sum(_phrase_hit(e, tw) for e in intent.entities)
        parts["entity"] = _clamp(hits / min(2, len(intent.entities)))
    else:
        parts["entity"] = 0.5
    if intent and intent.locations:
        hits = sum(_phrase_hit(l, tw) for l in intent.locations)
        parts["location"] = _clamp(hits / min(2, len(intent.locations)))
    else:
        parts["location"] = 0.5

    et = 0.5
    if intent:
        when = intent.when_words()
        if when and when.lower() in title.lower():
            et = 1.0
        elif intent.event_type and _phrase_hit(intent.event_type, tw):
            et = max(et, 0.8)
        if cand.upload_date and when and re.fullmatch(r"\d{4}", when):
            et = 1.0 if cand.upload_date[:4] == when else min(et, 0.3)
        if intent.is_historical() and re.search(r"\b(20[12]\d)\b", title) and not when.startswith("20"):
            et = min(et, 0.3)      # a modern-dated title for a historical beat
    parts["event_time"] = _clamp(et)

    t = 0.5
    if _BROLL.search(title):
        t = 1.0
    if _TALKING.search(title):
        t = 0.0
    parts["title"] = t

    q = 0.5
    if cand.aspect:
        q = 1.0 if cand.aspect >= 1.7 else (0.6 if cand.aspect >= 1.2 else 0.0)
    if cand.seconds:
        if cand.seconds < max(20.0, seconds + 8):
            q = min(q, 0.1)
        elif cand.seconds > 3600:
            q = min(q, 0.4)
    parts["quality"] = _clamp(q)

    parts["source"] = SOURCE_CONFIDENCE.get(cand.via, 0.5)
    score = sum(w.get(k, 0.0) * v for k, v in parts.items())
    # An event scene whose title names neither the entity nor the place is
    # very likely the same kind of thing somewhere else.
    if intent and intent.specificity == "event" and parts["entity"] == 0.0 and parts["location"] == 0.0:
        score *= 0.5
    return _clamp(score), parts


class CandidatePool:
    """Deduplicated candidates for one scene, ranked on metadata."""

    def __init__(self, intent: Optional[SceneIntent], query: str, seconds: float,
                 used: Optional[Iterable[str]] = None, exclude_ids: Optional[Iterable[str]] = None):
        self.intent = intent
        self.query = query
        self.seconds = seconds
        self.used = set(used or ())
        self.exclude = set(exclude_ids or ())
        self.items: Dict[str, Candidate] = {}
        self.searches = 0
        self.weights = meta_weights()

    def add(self, rows: Iterable[dict], provider: str = "youtube", query: str = "",
            variant: str = "", via: str = "search") -> int:
        """Rows in the provider's shape; returns how many were new."""
        self.searches += 1
        added = 0
        for r in rows or []:
            vid = str(r.get("id") or "").strip()
            if not vid or vid in self.exclude:
                continue
            key = f"{provider}:{vid}"
            if key in self.items or f"yt:{vid}" in self.used or key in self.used:
                continue
            c = Candidate(provider=provider, id=vid, title=str(r.get("title") or ""),
                          seconds=float(r.get("duration") or 0.0), aspect=float(r.get("aspect") or 0.0),
                          channel=str(r.get("channel") or ""), upload_date=str(r.get("upload_date") or ""),
                          query=query, variant=variant, via=r.get("via") or via, raw=dict(r))
            c.metadata, c.parts = metadata_score(c, self.intent, query or self.query,
                                                  self.seconds, self.weights)
            self.items[key] = c
            added += 1
        return added

    def ranked(self) -> List[Candidate]:
        return sorted(self.items.values(), key=lambda c: c.metadata, reverse=True)

    def top(self, n: int) -> List[Candidate]:
        return self.ranked()[:max(0, n)]

    def __len__(self) -> int:
        return len(self.items)

    def summary(self) -> dict:
        r = self.ranked()
        return {"candidates": len(r), "searches": self.searches,
                "best": round(r[0].metadata, 3) if r else None,
                "top": [{"id": c.id, "title": c.title[:60], "meta": round(c.metadata, 3)} for c in r[:5]]}


def reuse_penalty(identity: str, channel: str, used: Optional[Iterable[str]] = None,
                  recent: Optional[Iterable[str]] = None,
                  used_channels: Optional[Iterable[str]] = None) -> float:
    """Negative adjustment for footage the video already shows."""
    used, recent, chans = set(used or ()), set(recent or ()), set(used_channels or ())
    p = 0.0
    if identity in recent:
        p += REUSE_PENALTY["same_source_recent"]
    elif identity in used:
        p += REUSE_PENALTY["same_source"]
    if channel and channel in chans:
        p += REUSE_PENALTY["same_channel"]
    return p


def final_score(vision_score: Optional[float], quality: Optional[float],
                moment_score: Optional[float], meta_parts: Optional[Dict[str, float]],
                specificity: str = "", story_kind: str = "", penalty: float = 0.0,
                weights: Optional[dict] = None) -> Tuple[float, Dict[str, float]]:
    """
    The combined 0..1 score that picks a winner among clips that passed.

    Visual relevance is what the judge saw; entity/location blends the title
    evidence with the judge's specificity class; narration match is the
    metadata semantic part; the moment score is the storyboard pick.
    """
    w = weights or final_weights(story_kind)
    mp = meta_parts or {}
    spec = {"event": 1.0, "location": 0.75, "generic": 0.35}.get(specificity or "", 0.5)
    ent_loc = 0.5 * (0.5 * mp.get("entity", 0.5) + 0.5 * mp.get("location", 0.5)) + 0.5 * spec
    parts = {
        "visual": _clamp(vision_score if vision_score is not None else 0.5),
        "entity_location": _clamp(ent_loc),
        "narration": _clamp(mp.get("semantic", 0.5)),
        "timestamp": _clamp(moment_score if moment_score is not None else 0.5),
        "quality": _clamp(quality if quality is not None else 0.5),
        "recency": _clamp(mp.get("event_time", 0.5)),
        "source": _clamp(mp.get("source", 0.5)),
    }
    score = sum(w.get(k, 0.0) * v for k, v in parts.items()) + penalty
    parts["penalty"] = penalty
    return _clamp(score), parts
