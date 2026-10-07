"""
Re-cut a timeline that is already sourced: every shot on screen longer than
the cap is cut on its own words into shorter shots, the new ones get new
footage or pictures, and no shot the video already has is lost (the owner,
2026-10-04: "some of the clips run more than seven seconds").

The shot cap (src/shotcap.py) cuts a long beat BEFORE a plan sources it. The
owner's two finished-but-unrendered videos were sourced before it existed -
Yellowstone (9c467873) had 100 of 201 scenes over 7.5 s, up to 33 s, Lake
Powell (15eb0bc3) 79 - and planning them again would pay for the whole
footage search a second time and throw his edits away. This works on the
saved timeline instead, the way an editor would cut it:

  plan    a scene of footage or a still longer than the cap + SLACK (7.5 s) is
          cut on its words: a sentence end first, then a clause or a comma,
          then the widest breath, near the even split (transcribe._cut_features
          through hookboost._quality - the reading the scene cutter and the
          shot cap use), every piece at most the cap and at least MIN_PIECE
          seconds, the pieces tiling the scene's frames exactly, each with its
          own words and text. A graphic placed ON the picture (a mark's arrow,
          a callout's point) stays over the scene's own clip: no cut before it
          ends. Graphics, maps, animation scenes and cold-open flashes keep
          their length; an empty scene is filled (and cut when long) the same
          way, and left for the render's quality check when nothing is found.
  source  the first piece keeps the scene's own shot: the same file, the same
          in-point, its entrance and its look. Each further piece gets a new
          shot, in order: the scene's own runner-ups (a pick-a-shot choice
          already published, else the YouTube moment the judge approved for
          this line, fetched again); another moment of the scene's own source
          video, FALLBACK_MOMENT_GAP_SECONDS (30 s) from every moment the video
          shows, fetched, gated and judged like a pool's moment (at most
          MOMENTS_PER_SCENE a scene, so a long line is not one video cut five
          times); then a fresh search with the scene's query, intent,
          fallbacks and scene intent and the piece's own words as context (a
          picture search for a still), judged like a plan judges. Never a shot
          the video already shows (every asset id and source video of the
          timeline, and every piece's pick), never a moment an earlier video
          showed (src/ledger.py), never an AI-made picture. The pieces are
          searched in parallel (SOURCE_WORKERS, a plan's own setting) under
          one time box that also stops what is still in flight.
  settle  a piece nothing was found for goes back into the piece beside it
          whose picture still covers both at real speed - the scene's own clip
          covers its whole line - so the scene simply stays longer: never an
          empty piece, never a text card, never a slowed clip.
  save    (apply) the timeline as it was goes to R2 first
          (projects/<project>/backups/scene_data-<job>.json: a re-cut can be
          undone), the new files as a plan publishes them, the new timeline
          beside the backup, then the project row ONCE: scene_data, status
          "editing", "Long shots re-cut". Nothing fails half-way into the row.

A cut between two pieces of one line is a plain cut: a new piece enters with
transition "none", so no transition clip and no transition sound. The
narration, music, sound effects, ambience and the graphics track are
frame-positioned and never change. A dry run (the default) reads the timeline
and returns the plan with an estimate: nothing is written anywhere and
nothing is paid for.
"""
from __future__ import annotations

import contextvars
import copy
import datetime
import hashlib
import json
import math
import os
import re
import string
import threading
import time
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, events, gapfill, grade, ledger, media, r2, shotcap, storage, timeline, upscale, ytdlp

CAP = 7.0                  # the longest a shot stays on screen (s)
SLACK = 0.5                # a scene is cut when it runs longer than CAP + SLACK
MIN_PIECE = 2.5            # the shortest piece a cut leaves (s)
MOMENTS_PER_SCENE = 1      # other moments of a scene's own source video, per scene
SECONDS = 2400.0           # the time box (s)
# A piece still running this long after its own share of the box is not waited
# for once every other piece is in: whatever it still holds (a stalled download,
# a model call) would only come back late. The Yellowstone re-cut (9c467873,
# 2026-10-04, pass 2) had 51 of 52 pieces in at 925 s and then waited 1,100 s
# more, with no event at all, for the last one - over half the job.
STRAGGLER_GRACE = 120.0
WRITE_WAIT = 900.0         # how long an apply waits for the project to be handed to it (s)
POLL = 30.0                # seconds between two asks while it waits
PAD = media.SEQ_SHOT_PAD   # a new clip runs this much past its piece
MOMENT_TRIES = 3           # moments of the scene's own video tried per piece
TOL = shotcap.TOLERANCE_FRAMES
# The cut costs, as src/shotcap.py weighs them: a piece's distance from the even
# split, the cut's quality (1 = a sentence end), a one-word piece. And one more
# for every piece: each is a new shot to find (a search, a judgement, a file),
# so a line gets as few pieces as the cap allows unless their cuts are poor - a
# third piece cut on two sentence ends loses to two pieces cut between words.
W_LEN, W_CUT, FEW, W_PIECE = 2.0, 1.5, 30.0, 0.6
ROWS = 800                 # piece rows kept in a job result
# Keys of a scene's semanticMetadata that describe its SHOT (not its line): a new piece gets its own.
SHOT_FIELDS = ("assetId", "sourceUrl", "pageUrl", "sourceThumbnail", "moment", "alternatives", "candidates",
               "contentDescription", "relevanceScore", "qualityScore", "provider", "specificity", "finalScore",
               "scoreParts", "heldOver", "shotCap", "recut", "title")

# The dry run's estimate, from the owner's own jobs: a plan judged ~4.6 shots a
# scene (Atlantic City, 2026-10-01: 638 vision calls for 139 scenes; Kie bills
# ~$0.0026-0.0038 a call), a fresh search holds one thread ~1.5 min, a moment
# ~0.7 min (one download, one judgement), a vision call ~6 s with VISION_CONCURRENCY
# at once, and the 16-core serverless worker costs $0.576 an hour.
VISION_PER_SEARCH = 4.6
VISION_PER_MOMENT = 1.3
VISION_USD = 0.0035
VISION_SECONDS = 6.0
SEARCH_MINUTES = 1.5
MOMENT_MINUTES = 0.7
RUNNER_MINUTES = 0.3
PUBLISH_SECONDS = 4.0      # one new file: upload, thumbnail, preview copy (8 at a time)
WORKER_USD_PER_MINUTE = 0.576 / 60.0


class RecutError(RuntimeError):
    """Why a re-cut could not run or save, in words the owner can read."""


@dataclass
class Piece:
    """One planned piece of a scene: frames [start, end), its words and its text."""
    k: int
    start: int
    end: int
    words: List[dict]
    text: str

    @property
    def frames(self) -> int:
        return self.end - self.start


@dataclass
class Plan:
    """What happens to one scene: cut into pieces, or one piece (an empty scene to fill)."""
    index: int
    id: str
    kind: str                  # "video" | "image" | "empty"
    start: int
    end: int
    pieces: List[Piece]
    cut_before: List[str] = field(default_factory=list)
    over: int = 0              # pieces still over the cap (the words left no other cut)
    why: str = ""              # why a long scene is left whole
    long: bool = False
    limit: float = math.inf    # frames over which a shot is a long one (cap + SLACK)

    def needs(self) -> List[Piece]:
        """The pieces that need a new shot: all but the first, every piece of an empty scene."""
        return [p for p in self.pieces if p.k > 0 or self.kind == "empty"]

    def longest(self) -> int:
        """Frames of the longest piece: every new clip runs at least this long, so it can stand in for another."""
        return max((p.frames for p in self.pieces), default=0)


@dataclass
class Found:
    """The shot a piece got."""
    how: str                   # original | runner-up | moment | search | picture
    cover: float               # frames its picture plays at real speed (inf: a still, or the scene's own shot)
    k: int = 0                 # the piece it was found for
    media: Dict[str, Any] = field(default_factory=dict)
    asset: Any = None          # a MediaAsset with its file on this disk (published at the end)
    alt: Optional[int] = None  # the scene's runner-up it is (it leaves the scene's choices)
    sem: Dict[str, Any] = field(default_factory=dict)
    review: Tuple[bool, str] = (False, "")
    detail: str = ""


@dataclass
class Seg:
    """A piece while its scene settles: frames, words and the shot (None: nothing found)."""
    start: int
    end: int
    words: List[dict]
    texts: List[str]
    found: Optional[Found]
    ks: List[int]

    @property
    def frames(self) -> int:
        return self.end - self.start


# --------------------------------------------------------------------------- #
# Reading the timeline
# --------------------------------------------------------------------------- #

def fingerprint(doc: dict) -> str:
    """
    sha256 (hex) of every scene's media link and length in order - the same
    string scratchpad/recut_project.py computes and asks the database for -
    so the timeline a job read can be told apart from the one saved.
    """
    rows = [f"{((s if isinstance(s, dict) else {}).get('media') or {}).get('url') or ''}:"
            f"{(s if isinstance(s, dict) else {}).get('durationInFrames')}"
            for s in (doc or {}).get("scenes") or []]
    return hashlib.sha256("|".join(rows).encode("utf-8")).hexdigest()


def _fps(doc: dict) -> int:
    try:
        fps = int((doc or {}).get("fps") or 0)
    except (TypeError, ValueError):
        fps = 0
    return fps if fps > 0 else int(config.DEFAULT_FPS)


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def kind_of(scene: Any) -> str:
    """
    "video" / "image": a shot of footage or a still; "empty": a scene still
    without one; "graphic": an animation, a map or a full-screen look (keeps
    its length); "teaser": a cold-open flash (src/hookboost.py); "" otherwise.
    """
    if not isinstance(scene, dict):
        return ""
    if scene.get("teaser"):
        return "teaser"
    m = scene.get("media") if isinstance(scene.get("media"), dict) else {}
    vt = str(scene.get("visualType") or "footage")
    if scene.get("animation") or m.get("type") == "animation" or vt in ("animation", "map"):
        return "graphic"
    if m.get("type") in ("video", "image") and m.get("url"):
        return str(m["type"])
    if gapfill._empty(scene):
        return "empty"
    return ""


def _anchored_until(doc: dict, start: int, end: int) -> int:
    """
    The last frame inside [start, end) under a graphic placed ON the picture
    (a mark's arrow, a callout's point - reframe._anchored_spans reads them
    the same way), 0 when none: it points at something in the scene's own
    clip, so no cut may come before it ends.
    """
    until = 0
    for ov in (doc or {}).get("overlays") or []:
        if not isinstance(ov, dict) or not (ov.get("anchor") or ov.get("labelPosition")):
            continue
        try:
            a = int(ov.get("startFrame") or 0)
            b = a + int(ov.get("durationInFrames") or 0)
        except (TypeError, ValueError):
            continue
        if a < end and b > start:
            until = max(until, min(b, end))
    return until


class _W:
    """A timeline word ({text, start, end}) as the cut readers want it (attributes)."""
    __slots__ = ("text", "start", "end")

    def __init__(self, w: dict):
        self.text = str(w.get("text") or "")
        self.start = float(w.get("start") or 0.0)
        end = _num(w.get("end"))
        self.end = end if end is not None else self.start


def _timed(words: List[Any]) -> bool:
    return bool(words) and all(isinstance(w, dict) and _num(w.get("start")) is not None for w in words)


def choose_cuts(words: List[dict], start: int, end: int, fps: int, cap: float = CAP, lo: float = MIN_PIECE,
                keep_until: int = 0) -> Optional[List[Tuple[int, int]]]:
    """
    [(word index, frame)] a scene on screen from frame `start` to `end` is cut
    before, in order, or None when it is within the cap or its words leave no
    cut. Each cut lands where the picture would change for that word
    (shotcap._cut_times: on the word, or a moment early in the breath before a
    sentence with CUT_LEAD_SECONDS), never closer than `lo` seconds to another
    cut or the scene's edges; the first not before `keep_until` (a graphic on
    the picture). Chosen all at once over the word boundaries: no piece over
    the cap first, then as close to over as the words allow, then the cheapest
    cuts in the sense of transcribe.human_cuts - a sentence end, a clause, a
    comma or a breath near the even split - and never a one-word piece when
    another way exists.
    """
    from . import hookboost
    n = len(words)
    total = int(end) - int(start)
    cap_f = max(1, int(math.floor(cap * fps + 1e-6)))
    lo_f = max(1, int(math.ceil(lo * fps - 1e-6)))
    if n < 2 or total <= cap_f or total < 2 * lo_f:
        return None
    ws = [_W(w) for w in words]
    quality = list(hookboost._quality(ws))
    times = shotcap._cut_times(ws, start / float(fps), end / float(fps))
    nodes: List[Tuple[int, int, float]] = [(int(start), 0, 0.0)]          # (frame, word index, cut quality)
    for k in range(1, n):
        f = int(round(float(times[k]) * fps))
        if f - start < lo_f or end - f < lo_f or f < nodes[-1][0]:
            continue
        q = float(quality[k]) if k < len(quality) else 0.0
        if f == nodes[-1][0]:
            if q > nodes[-1][2]:
                nodes[-1] = (f, k, q)               # two words starting on one frame: the better cut
            continue
        nodes.append((f, k, q))
    nodes.append((int(end), n, 0.0))
    last = len(nodes) - 1
    if last < 2:
        return None
    m = max(2, int(math.ceil(total / float(cap_f) - 1e-9)))
    target = total / float(m)
    inf = (math.inf, math.inf, math.inf)
    best: List[Tuple[float, float, float]] = [inf] * len(nodes)
    back = [-1] * len(nodes)
    best[0] = (0.0, 0.0, 0.0)
    for j in range(1, len(nodes)):
        fj, kj, qj = nodes[j]
        for i in range(j):
            if best[i] == inf:
                continue
            fi, ki, _qi = nodes[i]
            length = fj - fi
            if length < lo_f:
                continue
            if i == 0 and keep_until and fj < keep_until and j != last:
                continue                            # the graphic on the picture stays over the scene's own shot
            over = length > cap_f
            cost = W_PIECE + W_LEN * ((length - target) / target) ** 2
            cost += W_CUT * (1.0 - qj) if j != last else 0.0
            cost += FEW if kj - ki < 2 else 0.0
            cand = (best[i][0] + (1.0 if over else 0.0), best[i][1] + max(0, length - cap_f), best[i][2] + cost)
            if cand < best[j]:
                best[j], back[j] = cand, i
    if best[last] == inf:
        return None
    path = []
    j = back[last]
    while j > 0:
        path.append(j)
        j = back[j]
    if not path:
        return None
    return [(nodes[c][1], nodes[c][0]) for c in sorted(path)]


_EDGE = string.punctuation + "‘’“”–—…"


def _text_marks(text: str, words: List[dict], firsts: List[int]) -> Optional[List[int]]:
    """
    Where in the scene's `text` each word at `firsts` begins, every word found
    in order (its letters and digits, case aside, never inside another word),
    or None when one is not there - the transcript writes "7" ".3" where the
    line says "7.3", so the words and the line's tokens need not line up.
    """
    low = text.lower()
    want = set(firsts)
    at, marks = 0, []
    for k, w in enumerate(words):
        raw = str(w.get("text") or "").strip().lower()
        core = raw.strip(_EDGE)
        if not core:
            if k in want:
                return None
            continue
        pos = low.find(core, at)
        while pos >= 0 and ((pos > at and low[pos - 1].isalnum())
                            or (pos + len(core) < len(low) and low[pos + len(core)].isalnum())):
            pos = low.find(core, pos + 1)
        if pos < 0:
            return None
        if k in want:
            lead = raw[:len(raw) - len(raw.lstrip(_EDGE))]      # its own leading marks: ",708", ".3"
            start = pos - len(lead) if lead and low[max(0, pos - len(lead)):pos] == lead else pos
            marks.append(max(at, start))
        at = pos + len(core)
    return marks


def _join_words(words: List[dict]) -> str:
    """The words as a line: "13" ",800" -> "13,800" (a number the transcript split), the rest spaced."""
    out = ""
    for w in words:
        t = str(w.get("text") or "").strip()
        if not t:
            continue
        out += ("" if not out or (re.match(r"[.,]\d", t) and out[-1].isdigit()) else " ") + t
    return out


def _texts(scene: dict, words: List[dict], bounds: List[int]) -> List[str]:
    """
    Each piece's text, always the scene's own line when it has one (the
    editor lets the owner rewrite a line without its words): its tokens
    when they line up with the words; else cut where each piece's first word
    begins in it; else (a rewritten line) its tokens shared out like the
    words. Only a scene without a line gets its words.
    """
    spans = list(zip(bounds, bounds[1:]))
    text = str(scene.get("text") or "")
    tokens = text.split()
    if len(tokens) == len(words):
        return [" ".join(tokens[a:b]) for a, b in spans]
    marks = _text_marks(text, words, [a for a, _b in spans[1:]])
    if marks is not None:
        edges = [0] + marks + [len(text)]
        out = [" ".join(text[x:y].split()) for x, y in zip(edges, edges[1:])]
        if all(out) and all(x < y for x, y in zip(edges, edges[1:])):
            return out
    if tokens:
        edges = [0] + [min(len(tokens), int(round(a * len(tokens) / float(max(1, len(words))))))
                       for a, _b in spans[1:]] + [len(tokens)]
        return [" ".join(tokens[x:y]) for x, y in zip(edges, edges[1:])]
    return [_join_words(words[a:b]) for a, b in spans]


def _left(scene: dict, i: int, fps: int, why: str) -> dict:
    return {"scene": str(scene.get("id") or f"scene {i + 1}"), "index": i,
            "seconds": round(int(scene.get("durationInFrames") or 0) / float(fps), 2), "why": why}


def plan_doc(doc: dict, cap: float = CAP, lo: float = MIN_PIECE,
             slack: float = SLACK) -> Tuple[List[Plan], List[dict], dict]:
    """
    (plans, the long scenes left whole and why, counts) for a timeline: every
    shot longer than cap + slack cut on its words, every empty scene to fill.
    Reads only.
    """
    fps = _fps(doc)
    scenes = (doc or {}).get("scenes") or []
    cap_f = int(math.floor(cap * fps + 1e-6))
    limit = (cap + slack) * fps
    plans: List[Plan] = []
    left: List[dict] = []
    counts: Dict[str, Any] = {"scenes": len(scenes), "long": 0, "longByKind": {}, "longest": 0.0, "empty": 0,
                              "cut": 0, "pieces": 0, "newPieces": 0}
    reasons = {"graphic": "a graphic or animation keeps its own length", "teaser": "a cold-open flash",
               "": "not a shot of footage or a still"}
    for i, s in enumerate(scenes):
        if not isinstance(s, dict):
            continue
        start = int(s.get("startFrame") or 0)
        frames = int(s.get("durationInFrames") or 0)
        end = start + frames
        kind = kind_of(s)
        long = frames > (cap + slack) * fps + 1e-6
        if long:
            counts["long"] += 1
            k = kind if kind in ("video", "image", "empty") else "other"
            counts["longByKind"][k] = counts["longByKind"].get(k, 0) + 1
            counts["longest"] = max(counts["longest"], round(frames / float(fps), 2))
        if kind == "empty":
            counts["empty"] += 1
        if kind not in ("video", "image", "empty"):
            if long:
                left.append(_left(s, i, fps, reasons.get(kind, reasons[""])))
            continue
        if not long and kind != "empty":
            continue
        sid = str(s.get("id") or f"s{i:04d}")
        words = list(s.get("words") or [])
        cuts: Optional[List[Tuple[int, int]]] = None
        why = ""
        if long:
            if len(words) < 2 or not _timed(words):
                why = "it has no word timings to cut on"
            else:
                keep = _anchored_until(doc, start, end) if kind != "empty" else 0
                cuts = choose_cuts(words, start, end, fps, cap, lo, keep_until=keep)
                if not cuts:
                    why = ("a graphic points into its picture until too late to cut it"
                           if keep and choose_cuts(words, start, end, fps, cap, lo) else
                           "its words leave no cut within the limits")
        if cuts:
            bounds = [0] + [k for k, _f in cuts] + [len(words)]
            marks = [start] + [f for _k, f in cuts] + [end]
            texts = _texts(s, words, bounds)
            pieces = [Piece(k=n, start=marks[n], end=marks[n + 1],
                            words=[dict(w) for w in words[bounds[n]:bounds[n + 1]]], text=texts[n])
                      for n in range(len(marks) - 1)]
            plan = Plan(index=i, id=sid, kind=kind, start=start, end=end, pieces=pieces, long=True,
                        cut_before=[str(words[k].get("text") or "") for k, _f in cuts],
                        over=sum(1 for p in pieces if p.frames > cap_f), limit=limit)
            counts["cut"] += 1
        elif kind == "empty":
            plan = Plan(index=i, id=sid, kind=kind, start=start, end=end, long=long, why=why, limit=limit,
                        pieces=[Piece(0, start, end, [dict(w) for w in words if isinstance(w, dict)],
                                      str(s.get("text") or ""))])
            if long:
                left.append(_left(s, i, fps, why))
        else:
            left.append(_left(s, i, fps, why))
            continue
        plans.append(plan)
        counts["pieces"] += len(plan.pieces)
        counts["newPieces"] += len(plan.needs())
    return plans, left, counts


# --------------------------------------------------------------------------- #
# Runner-ups and what a dry run expects
# --------------------------------------------------------------------------- #

_PICTURE_SOURCES = ("web", "web_image", "wikimedia", "openverse", "wikipedia", "nasa", "yandex", "image")


def _alt_youtube(alt: dict) -> Tuple[str, Optional[float]]:
    """(YouTube id, start) of a runner-up the judge approved, ("", None) when it is not a YouTube moment."""
    vid = ledger.youtube_id(alt.get("url"), alt.get("assetId"), alt.get("sourceUrl"))
    if not vid:
        return "", None
    moment = alt.get("moment") if isinstance(alt.get("moment"), dict) else {}
    start = _num(moment.get("start"))
    if start is None:
        start = ledger.url_start(str(alt.get("url") or alt.get("sourceUrl") or ""))
    return vid, start


def _alt_picture(alt: dict) -> str:
    """A still runner-up's own address ("" when it is not a picture)."""
    url = str(alt.get("url") or alt.get("sourceUrl") or "")
    if not url.startswith(("http://", "https://")) or ledger.youtube_id(url):
        return ""
    source = str(alt.get("source") or "").lower()
    if shotcap._kind(url, "") == "image" or any(source.startswith(p) for p in _PICTURE_SOURCES):
        return url
    return ""


def runner_ups(scene: dict) -> List[Tuple[int, dict]]:
    """(place in the scene's choices, choice) of every runner-up a piece could show."""
    sem = scene.get("semanticMetadata") if isinstance(scene.get("semanticMetadata"), dict) else {}
    out = []
    for n, alt in enumerate(sem.get("alternatives") or []):
        if not isinstance(alt, dict):
            continue
        m = alt.get("media") if isinstance(alt.get("media"), dict) else {}
        vid, start = _alt_youtube(alt)
        if m.get("url") or (vid and start is not None) or _alt_picture(alt):
            out.append((n, alt))
    return out


def _yt_origin(scene: dict) -> Tuple[str, Optional[float]]:
    try:
        return shotcap._yt_of(scene)
    except Exception:  # noqa: BLE001 - not a YouTube clip then
        return "", None


def estimate(doc: dict, plans: List[Plan], workers: int, moments_per_scene: int = MOMENTS_PER_SCENE,
             seconds: float = SECONDS) -> dict:
    """
    What an apply would most likely do and cost: the first rung each piece
    tries (its scene's runner-ups, a moment of its own video, a fresh search
    or picture search), the vision calls, minutes and dollars - from the
    owner's measured jobs (the constants above). A guess, never a promise:
    a search that finds nothing costs as much as one that does.
    """
    scenes = (doc or {}).get("scenes") or []
    ladder = {"runnerUps": 0, "moments": 0, "searches": 0, "pictures": 0}
    for p in plans:
        s = scenes[p.index]
        alts = len(runner_ups(s))
        vid, start = _yt_origin(s) if p.kind == "video" else ("", None)
        moments = max(0, int(moments_per_scene)) if vid and start is not None else 0
        for _c in p.needs():
            if alts:
                ladder["runnerUps"] += 1
                alts -= 1
            elif moments:
                ladder["moments"] += 1
                moments -= 1
            elif p.kind == "image":
                ladder["pictures"] += 1
            else:
                ladder["searches"] += 1
    searches = ladder["searches"] + ladder["pictures"]
    vision = int(round(ladder["moments"] * VISION_PER_MOMENT + searches * VISION_PER_SEARCH))
    workers = max(1, int(workers))
    thread_minutes = (searches * SEARCH_MINUTES + ladder["moments"] * MOMENT_MINUTES
                      + ladder["runnerUps"] * RUNNER_MINUTES)
    judging = vision * VISION_SECONDS / max(1, int(config.VISION_CONCURRENCY)) / 60.0
    new = sum(ladder.values())
    sourcing = min(max(thread_minutes / workers, judging), max(1.0, seconds / 60.0))
    minutes = 1.0 + sourcing + new * PUBLISH_SECONDS / 8.0 / 60.0 + 0.5
    return {"ladder": ladder, "newShots": new, "visionCalls": vision, "minutes": round(minutes, 1),
            "usd": round(vision * VISION_USD + minutes * WORKER_USD_PER_MINUTE, 2),
            "note": "the first rung each piece tries; a piece that finds nothing there goes on to the next"}


def _plan_row(p: Plan, fps: int) -> dict:
    return {"scene": p.id, "index": p.index, "kind": p.kind, "seconds": round((p.end - p.start) / float(fps), 2),
            "cutAt": [c.start for c in p.pieces[1:]], "cutBefore": p.cut_before,
            "pieces": [round(c.frames / float(fps), 2) for c in p.pieces], "words": [len(c.words) for c in p.pieces],
            "texts": [c.text[:70] for c in p.pieces], **({"over": p.over} if p.over else {}),
            **({"why": p.why} if p.why else {})}


# --------------------------------------------------------------------------- #
# Finding the new shots
# --------------------------------------------------------------------------- #

def _remove(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _licence_review(licence: str) -> Tuple[bool, str]:
    if str(licence or "").startswith("unverified"):
        return True, "Licence unverified — confirm you hold the rights"
    return False, ""


def _alt_sem(alt: dict) -> dict:
    """What the editor shows of a runner-up put on a piece (as a plan records a found clip)."""
    src = str(alt.get("sourceUrl") or alt.get("url") or "")
    return {"assetId": str(alt.get("assetId") or ""), "provider": str(alt.get("source") or ""),
            "sourceUrl": src if src.startswith("http") else "",
            "contentDescription": str(alt.get("description") or ""), "relevanceScore": alt.get("score"),
            "qualityScore": alt.get("quality"), "finalScore": alt.get("finalScore"),
            "specificity": str(alt.get("specificity") or ""), "moment": dict(alt.get("moment") or {}),
            "alternatives": []}


def _asset_sem(a) -> dict:
    """What a plan records of a found clip or picture (timeline.build's semanticMetadata)."""
    sem = {"provider": a.source or "", "assetId": a.identity,
           "sourceUrl": a.url if str(a.url or "").startswith("http") else "",
           "contentDescription": a.content_description or "", "relevanceScore": a.relevance_score,
           "qualityScore": a.quality, "specificity": a.specificity or "",
           "alternatives": list(a.alternatives or [])[:4], "finalScore": a.final_score,
           "scoreParts": dict(a.score_parts or {}), "moment": dict(a.moment or {}), "candidates": dict(a.pool or {})}
    if getattr(a, "page_url", ""):
        sem["pageUrl"] = a.page_url
    if getattr(a, "thumbnail", ""):
        sem["sourceThumbnail"] = a.thumbnail
    return sem


class Finder:
    """
    A new shot for every piece that needs one: each piece tries its scene's
    runner-ups, another moment of its scene's own video, then a fresh search,
    on SOURCE_WORKERS threads at once. One time box (`deadline`): the job's
    download deadline and every piece's stop are set to it, so what is still
    in flight stops at its next search, metadata call or download; a result
    that comes in after it is not used.
    """

    def __init__(self, doc: dict, plans: List[Plan], work: str, *, workers: int, deadline: float,
                 moments_per_scene: int = MOMENTS_PER_SCENE, flags: Optional[dict] = None,
                 say: Optional[Callable] = None):
        self.doc = doc
        self.scenes = doc.get("scenes") or []
        self.fps = _fps(doc)
        self.plans = {p.index: p for p in plans}
        self.work = work
        self.workers = max(1, int(workers))
        self.deadline = float(deadline)
        self.moments_per_scene = max(0, int(moments_per_scene))
        self.flags = {k: v for k, v in (flags or {}).items() if v is not None}
        self.say = say or (lambda *a, **k: None)
        self.lock = threading.Lock()
        self.used = gapfill.Used()
        self.exclude: set = set()
        self.layout: Dict[Tuple[int, int], int] = {}
        self.spent: Dict[int, set] = {}            # scene -> its runner-ups already tried
        self.moment_count: Dict[int, int] = {}     # scene -> other moments of its video taken or being tried
        self.moment_starts: Dict[int, List[float]] = {}
        self.moment_tried: Dict[int, set] = {}
        self.video_moments: Dict[str, List[float]] = {}   # "yt:<id>" -> every moment the timeline shows of it
        self.found: Dict[Tuple[int, int], Found] = {}
        self.notes: Dict[Tuple[int, int], List[str]] = {}
        self.late: set = set()
        self.done: set = set()
        self.began: Dict[Tuple[int, int], float] = {}       # piece -> when its thread took it
        self.step: Dict[Tuple[int, int], str] = {}          # piece -> the rung it is on (or was last on)
        self.took: Dict[Tuple[int, int], Dict[str, float]] = {}   # piece -> seconds spent on each rung
        self.stuck: Dict[Tuple[int, int], Tuple[float, str]] = {}  # piece not waited for -> (seconds, its rung)
        self.box: Optional[ytdlp.Box] = None
        self.share = 0.0
        self._build()

    # -------------------------------------------------------------- setup
    def _build(self) -> None:
        """Every scene's place in the cut timeline, the shots it already shows, the sources never to search again."""
        pos = 0
        for i, s in enumerate(self.scenes):
            p = self.plans.get(i)
            for k in ([c.k for c in p.pieces] if p else [0]):
                self.layout[(i, k)] = pos
                if k == 0 and (p is None or p.kind != "empty") and isinstance(s, dict):
                    shot = gapfill.Shot.of_scene(s, self.fps)
                    if shot is not None:
                        self.used.add(pos, shot)
                        if shot.video:
                            # (None: a moment nobody recorded - it could be anywhere in the video.)
                            self.video_moments.setdefault(shot.video, []).append(shot.start)
                pos += 1
            if not isinstance(s, dict):
                continue
            sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
            aid = str(sem.get("assetId") or "")
            src = str(sem.get("sourceUrl") or "")
            if aid:
                self.exclude.add(aid)
            video = gapfill._video_of(aid, src)
            if video:
                self.exclude.add(video)
            provider = str(sem.get("provider") or (s.get("media") or {}).get("source") or "")
            if provider and src.startswith("http"):
                self.exclude.add(f"{provider}:{src}")

    def job(self, i: int, c: Piece) -> dict:
        """The sourcing line of one piece: its scene's search, intent and switches, its own words as context."""
        s = self.scenes[i]
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        si = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else None
        query = " ".join(str(s.get("query") or sem.get("searchQuery") or sem.get("subject") or c.text or "")
                         .split())[:240]
        fallbacks: List[str] = []
        if si:
            try:
                from .intent import SceneIntent
                fallbacks = SceneIntent.from_dict(si).queries(query)[1:]
            except Exception:  # noqa: BLE001 - the query alone
                fallbacks = []
        plan = self.plans[i]
        vt = str(s.get("visualType") or "footage")
        if plan.kind == "image":
            vt = "image"
        elif plan.kind == "video" or vt not in ("footage", "image"):
            vt = "footage"
        at = c.start / float(self.fps)
        # Every new clip of a line runs as long as its longest piece (and a little more): one that
        # finds nothing can then be covered by a neighbour's shot moving on to it (settle).
        need = round(max(c.frames, plan.longest()) / float(self.fps) + PAD, 2)
        return {"index": self.layout[(i, c.k)], "query": query, "fallbacks": fallbacks,
                "intent": str(sem.get("intent") or query)[:300], "context": c.text,
                "subject_type": str(sem.get("subjectType") or ""), "subject": str(sem.get("subject") or ""),
                "event_window": str(sem.get("eventWindow") or ""), "scene_intent": si,
                "hook": at < float(config.HOOK_SECONDS),
                "recency": "month" if sem.get("eventWindow") == "year" and config.RECENT_FOOTAGE_FIRST else "",
                "visual_type": vt, "seconds": round(c.frames / float(self.fps), 2), "need": need,
                "start": round(at, 2)}

    def note(self, key: Tuple[int, int], text: str) -> None:
        with self.lock:
            rows = self.notes.setdefault(key, [])
            if len(rows) < 8:
                rows.append(str(text)[:160])

    def _taken(self, *names: str) -> None:
        with self.lock:
            self.exclude.update(n for n in names if n)

    def _cover(self, asset, fallback_frames: int) -> float:
        if asset.kind != "video":
            return math.inf
        secs = timeline._clip_seconds(asset)
        return secs * self.fps if secs > 0 else float(fallback_frames)

    # -------------------------------------------------------------- the rungs
    def runner_up(self, i: int, c: Piece, job: dict) -> Optional[Found]:
        """(1) The scene's own runner-ups: clips the judge approved for this very line. Each is tried once."""
        key = (i, c.k)
        for n, alt in runner_ups(self.scenes[i]):
            if ytdlp.stopped():
                return None
            with self.lock:
                spent = self.spent.setdefault(i, set())
                if n in spent:
                    continue
                spent.add(n)
            try:
                got = self._alt(i, c, job, n, alt)
            except Exception as e:  # noqa: BLE001 - the next runner-up
                self.note(key, f"runner-up {n + 1}: {type(e).__name__}: {str(e)[:80]}")
                got = None
            if got is not None:
                return got
        return None

    def _alt(self, i: int, c: Piece, job: dict, n: int, alt: dict) -> Optional[Found]:
        key = (i, c.k)
        idx = self.layout[key]
        at = c.start / float(self.fps)
        title = str(alt.get("title") or "")
        m = alt.get("media") if isinstance(alt.get("media"), dict) else {}
        # Never a source the video already shows (another scene's clip or picture, or a piece's pick):
        # only the moment rung goes back to the scene's own video.
        aid = str(alt.get("assetId") or "")
        names = {aid, gapfill._video_of(aid, str(alt.get("url") or alt.get("sourceUrl") or ""))} - {""}
        with self.lock:
            clash = bool(names & self.exclude)
        if clash:
            self.note(key, f"runner-up {n + 1}: the video already shows that source")
            return None
        if m.get("url"):
            # A pick-a-shot choice already published (handler._publish_choices): nothing to fetch.
            med = shotcap._alt_media(alt)
            if med is None:
                self.note(key, f"runner-up {n + 1}: its saved copy does not load")
                return None
            cover = math.inf
            if med.get("type") == "video":
                secs = shotcap._alt_seconds(alt, med)
                if secs * self.fps < c.frames - TOL:
                    self.note(key, f"runner-up {n + 1}: {secs:.1f} s, too short for the piece")
                    return None
                med["clipSeconds"] = round(secs, 2)
                cover = secs * self.fps
            shot = shotcap._alt_shot(alt, med, at)
            if not self.used.claim(idx, shot):
                self.note(key, f"runner-up {n + 1}: {self.used.why_not(idx, shot) or 'the video shows it'}")
                return None
            self._taken(str(alt.get("assetId") or ""), shot.video)
            return Found(how="runner-up", cover=cover, k=c.k, media=med, alt=n, sem=_alt_sem(alt),
                         review=_licence_review(med.get("license")), detail=f"runner-up {n + 1} (its saved choice)")
        vid, start = _alt_youtube(alt)
        if vid and start is not None:
            need = float(job["need"])
            if ledger.moment_used(vid, start, start + need):
                self.note(key, f"runner-up {n + 1}: an earlier video showed that moment")
                return None
            shot = gapfill.Shot(video=f"yt:{vid}", start=float(start), at=at)
            if not self.used.claim(idx, shot):
                self.note(key, f"runner-up {n + 1}: {self.used.why_not(idx, shot) or 'the video shows it'}")
                return None
            moment = dict(alt.get("moment") or {}) if isinstance(alt.get("moment"), dict) else {}
            asset = self._clip(vid, float(start), need, title, key, licence=str(alt.get("license") or ""),
                               moment=moment, label=f"runner-up {n + 1}", least=c.frames)
            if asset is None:
                self.used.release(idx, shot)
                return None
            # Judged for this line when the plan found it: its verdict stays with it.
            asset.relevance_score = _num(alt.get("score"))
            asset.quality = _num(alt.get("quality"))
            asset.final_score = _num(alt.get("finalScore"))
            asset.content_description = str(alt.get("description") or "")
            asset.specificity = str(alt.get("specificity") or "")
            if "@" in str(alt.get("assetId") or ""):
                asset.moment_key = str(alt["assetId"])
            self._taken(asset.identity, f"yt:{vid}")
            return Found(how="runner-up", cover=self._cover(asset, c.frames), k=c.k, asset=asset, alt=n,
                         detail=f"runner-up {n + 1} (YouTube {vid} at {start:.0f} s)")
        url = _alt_picture(alt)
        if url:
            if ledger.photo_used(url):
                self.note(key, f"runner-up {n + 1}: an earlier video showed that picture")
                return None
            cand = media.MediaAsset(kind="image", source=str(alt.get("source") or "web"), url=url,
                                    attribution=title, license=str(alt.get("license") or ""))
            shot = gapfill.Shot.of_asset(cand, at)
            if not self.used.claim(idx, shot):
                return None
            got = media._download(cand, job["query"], self.work)
            if got is None or not got.local_path or not media._asset_ok(got)[0] \
                    or media._photo_seen_before(got.local_path):
                self.used.release(idx, shot)
                self.note(key, f"runner-up {n + 1}: the picture did not download or is not usable")
                return None
            got.relevance_score = _num(alt.get("score"))
            got.quality = _num(alt.get("quality"))
            got.content_description = str(alt.get("description") or "")
            self._taken(got.identity)
            return Found(how="runner-up", cover=math.inf, k=c.k, asset=got, alt=n,
                         detail=f"runner-up {n + 1} (its picture)")
        return None

    def _clip(self, vid: str, start: float, need: float, title: str, key: Tuple[int, int], *,
              licence: str, moment: dict, label: str, least: int):
        """
        A YouTube section of `need` seconds fetched and gated like a chain shot
        (quality, stills, AI-made), at least `least` frames long - its own
        piece at real speed - or None.
        """
        try:
            path, clean, cuts = media.fetch_clean_clip(vid, self.work, start, need, title)
        except Exception as e:  # noqa: BLE001 - the next try
            self.note(key, f"{label}: not fetched ({type(e).__name__})")
            return None
        if not path:
            self.note(key, f"{label}: YouTube {vid} at {start:.0f} s did not download")
            return None
        asset = media.MediaAsset(
            kind="video", source="youtube", local_path=path, duration=need,
            url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}", attribution=title,
            license=licence or shotcap.UNVERIFIED,
            moment_key=f"yt:{vid}@{int(start // max(1.0, float(config.POOL_MIN_GAP_SECONDS)))}",
            moment=dict(moment, start=round(float(start), 1), clean=clean, cuts=cuts))
        ok, why = media._asset_ok(asset)
        if ok:
            why = media.motion_rejects(path) or media.slop_reason(path, title)
        if not why:
            secs = timeline._clip_seconds(asset)
            if 0 < secs * self.fps < least - TOL:
                why = f"only {secs:.1f} s long"
        if why or not ok:
            self.note(key, f"{label}: {why or 'not usable'}")
            _remove(path)
            return None
        return asset

    def moment(self, i: int, c: Piece, job: dict) -> Optional[Found]:
        """(2) Another moment of the scene's own source video, judged against the line (at most MOMENTS_PER_SCENE)."""
        plan = self.plans[i]
        if plan.kind != "video" or self.moments_per_scene <= 0:
            return None
        vid, start = _yt_origin(self.scenes[i])
        if not vid or start is None:
            return None
        with self.lock:
            if self.moment_count.get(i, 0) >= self.moments_per_scene:
                return None
            self.moment_count[i] = self.moment_count.get(i, 0) + 1
        got = None
        try:
            got = self._moment(i, c, job, vid, float(start))
            return got
        finally:
            if got is None:
                with self.lock:
                    self.moment_count[i] -= 1

    def _positions(self, start: float, shown: float, need: float, gap: float, length: float) -> List[float]:
        """Where in the video to look: after the shot first, then before it, each a gap from the last."""
        out = []
        for j in range(MOMENT_TRIES):
            for at in (start + shown + gap + j * (gap + need), start - gap - need - j * (gap + need)):
                if at < 0 or (length and at + need > length - 1.0):
                    continue
                out.append(round(at, 1))
        return out

    def _moment(self, i: int, c: Piece, job: dict, vid: str, start: float) -> Optional[Found]:
        key = (i, c.k)
        idx = self.layout[key]
        at_line = c.start / float(self.fps)
        s = self.scenes[i]
        m = s.get("media") if isinstance(s.get("media"), dict) else {}
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        shown = max(_num(m.get("clipSeconds")) or 0.0, int(s.get("durationInFrames") or 0) / float(self.fps))
        need = float(job["need"])
        gap = float(getattr(config, "FALLBACK_MOMENT_GAP_SECONDS", 30.0) or 30.0)
        title = str(m.get("attribution") or "")
        try:
            info, _proxy = media._yt_info(vid)
            length = float((info or {}).get("duration") or 0.0)
        except Exception:  # noqa: BLE001 - its length unknown: every position is tried
            length = 0.0
        # Every moment of this video the timeline shows - this scene's and any other scene's - stays
        # the gap away (gapfill.Used does not ask it of the scene beside a chain shot).
        shown_moments = list(self.video_moments.get(f"yt:{vid}", []))
        if any(t is None for t in shown_moments):
            self.note(key, "moment: another scene shows this video at a moment nobody recorded")
            return None
        tries = 0
        for at in self._positions(start, shown, need, gap, length):
            if tries >= MOMENT_TRIES or ytdlp.stopped():
                break
            if any(abs(at - t) < gap for t in shown_moments):
                continue
            with self.lock:
                tried = self.moment_tried.setdefault(i, set())
                taken = self.moment_starts.setdefault(i, [])
                if round(at) in tried or any(abs(at - t) < gap for t in taken):
                    continue
                tried.add(round(at))
                taken.append(at)
            tries += 1
            got = None
            shot = gapfill.Shot(video=f"yt:{vid}", start=at, at=at_line, chain=True)
            claimed = False
            try:
                if ledger.moment_used(vid, at, at + need):
                    self.note(key, f"moment {at:.0f} s: an earlier video showed it")
                    continue
                claimed = self.used.claim(idx, shot)
                if not claimed:
                    self.note(key, f"moment {at:.0f} s: {self.used.why_not(idx, shot) or 'the video shows it'}")
                    continue
                asset = self._clip(vid, at, need, title, key, licence=str(m.get("license") or ""),
                                   moment={"chain": True, "chain_of": str(sem.get("assetId") or ""), "recut": True},
                                   label=f"moment {at:.0f} s", least=c.frames)
                if asset is None:
                    continue
                keep, verdict = media.judge_clip(asset.local_path, job, title, source_url=asset.url)
                if not keep:
                    self.note(key, f"moment {at:.0f} s: the judge turned it down"
                              + (f" ({verdict.get('score', 0):.2f})" if isinstance(verdict, dict) else ""))
                    _remove(asset.local_path)
                    continue
                asset.apply_verdict(verdict, job["intent"])
                asset.review_required, asset.review_reason = _licence_review(asset.license)
                self._taken(asset.identity)
                got = Found(how="moment", cover=self._cover(asset, c.frames), k=c.k, asset=asset,
                            detail=f"YouTube {vid} at {at:.0f} s (the scene's own shot is at {start:.0f} s)")
                return got
            finally:
                if got is None:
                    if claimed:
                        self.used.release(idx, shot)
                    with self.lock:
                        if at in taken:
                            taken.remove(at)
        return None

    def search(self, i: int, c: Piece, job: dict) -> Optional[Found]:
        """(3) A fresh search for the piece - its scene's query, intent and fallbacks, its own words - judged as a plan judges."""
        key = (i, c.k)
        idx = self.layout[key]
        at = c.start / float(self.fps)
        plan = self.plans[i]
        nth = max(0, c.k - (0 if plan.kind == "empty" else 1))     # the pieces of one line reach for different results
        for attempt in range(2):
            if ytdlp.stopped():
                return None
            try:
                asset = media.source_for_segment(
                    job["query"], job["need"], self.work, visual_type=job["visual_type"], nth=nth + attempt,
                    used=self.exclude, fallbacks=job["fallbacks"], intent=job["intent"], context=job["context"],
                    subject_type=job["subject_type"], subject=job["subject"], event_window=job["event_window"],
                    scene_intent=job["scene_intent"], hook=job["hook"], recency=job["recency"], **self.flags)
            except Exception as e:  # noqa: BLE001 - nothing for this piece
                self.note(key, f"search: {type(e).__name__}: {str(e)[:80]}")
                return None
            if asset is None:
                self.note(key, "search: nothing found that passed the judge")
                return None
            why = self._fresh_why(asset, c)
            if not why:
                with self.lock:
                    if asset.identity in self.exclude:
                        why = "another piece took the same shot"
                    else:
                        self.exclude.add(asset.identity)
                        self.exclude.add(media.video_key(asset) or asset.identity)
            if not why:
                shot = gapfill.Shot.of_asset(asset, at)
                if not self.used.claim(idx, shot):
                    why = self.used.why_not(idx, shot) or "the video shows it"
            if why:
                # (Its file stays: two searches that land on one clip share one download, and the work
                # directory goes when the job ends.)
                self.note(key, f"search: {asset.source} {why}")
                continue
            how = "picture" if asset.kind == "image" else "search"
            return Found(how=how, cover=self._cover(asset, c.frames), k=c.k, asset=asset,
                         review=(bool(asset.review_required), asset.review_reason or ""),
                         detail=f"{asset.source}: {(asset.attribution or asset.query or '')[:70]}")
        return None

    def _fresh_why(self, asset, c: Piece) -> str:
        if asset.source == "generated":
            return "an AI-made picture (never used to re-cut)"
        if asset.kind not in ("video", "image"):
            return "not a clip or a picture"
        ok, why = media._asset_ok(asset)
        if not ok:
            return why or "not usable"
        if asset.kind == "video":
            secs = timeline._clip_seconds(asset)
            if 0 < secs * self.fps < c.frames - TOL:
                return f"only {secs:.1f} s long"
        return ""

    # -------------------------------------------------------------- running
    def one(self, i: int, c: Piece) -> Optional[Found]:
        """One piece's rungs in order, on its own thread, under the box and its own share of it."""
        key = (i, c.k)
        began = time.time()
        with self.lock:
            self.began[key] = began
        own = began + self.share if self.share else 0.0
        stop = ytdlp.STOP.set((self.box, own))
        tokens: list = []
        try:
            job = self.job(i, c)
            tokens = gapfill._scene_context(job)    # the gates read the line's subject, event and intent
            for name, step in (("runner-up", self.runner_up), ("moment", self.moment), ("search", self.search)):
                if ytdlp.stopped():
                    break
                t0 = time.time()
                with self.lock:
                    self.step[key] = name
                try:
                    got = step(i, c, job)
                except Exception as e:  # noqa: BLE001 - the next rung
                    self.note(key, f"{name}: {type(e).__name__}: {str(e)[:100]}")
                    got = None
                finally:
                    with self.lock:
                        spent = self.took.setdefault(key, {})
                        spent[name] = round(spent.get(name, 0.0) + time.time() - t0, 1)
                if got is not None:
                    return got
            if ytdlp.stopped():
                self.note(key, "the time box ran out")
                with self.lock:
                    self.late.add(key)
            return None
        finally:
            for var, token in reversed(tokens):
                var.reset(token)
            ytdlp.STOP.reset(stop)

    def run(self) -> Dict[Tuple[int, int], Found]:
        todo = [(i, c) for i in sorted(self.plans) for c in self.plans[i].needs()]
        if not todo:
            return self.found
        lines = [{"index": self.layout[(i, c.k)], "hook": c.start / float(self.fps) < float(config.HOOK_SECONDS),
                  "_piece": (i, c)} for i, c in todo]
        order = [j["_piece"] for j in gapfill.coverage_order(lines)]   # the hook first, then spread over the video
        old = ytdlp.DEADLINE[0]
        ytdlp.set_deadline(self.deadline)
        self.box = ytdlp.Box(self.deadline)
        self.share = media.scene_seconds(self.deadline - time.time(), self.workers, len(todo))
        pool = media._new_pool(min(self.workers, len(todo)))
        futures = {pool.submit(contextvars.copy_context().run, self.one, i, c): (i, c.k) for i, c in order}
        count, last = 0, None
        pending = set(futures)
        try:
            while pending:
                now = time.time()
                if now >= self.deadline:
                    break
                if self._all_stuck([futures[f] for f in pending], now):
                    break                       # only stragglers left: their results would come back late
                finished, pending = wait(pending, timeout=min(self.deadline - now, 5.0), return_when=FIRST_COMPLETED)
                for fut in finished:
                    key = futures[fut]
                    try:
                        got = fut.result()
                    except Exception as e:  # noqa: BLE001 - one piece never stops the rest
                        self.note(key, f"{type(e).__name__}: {str(e)[:100]}")
                        got = None
                    if time.time() > self.deadline:
                        with self.lock:
                            self.late.add(key)          # in by the end of the box but past it: not used
                    elif got is not None:
                        self.found[key] = got
                    self.done.add(key)
                    count += 1
                    pct = 8 + int(70 * count / len(todo))
                    if pct != last:
                        last = pct
                        self.say(f"Re-sourcing long shots {count}/{len(todo)}", pct, done=count, total=len(todo))
        finally:
            self.box.end()                  # whatever still runs stops at its next network call
            pool.shutdown(wait=False, cancel_futures=True)
            ytdlp.set_deadline(old)
        now = time.time()
        for i, c in todo:
            key = (i, c.k)
            if key in self.done:
                continue
            with self.lock:
                began, step = self.began.get(key), self.step.get(key, "")
            if began is not None and self.share and now > began + self.share:
                self.stuck[key] = (round(now - began, 1), step)
                self.note(key, f"not waited for: still in its {step or 'first'} step {now - began:.0f} s after "
                               f"it started (its share {self.share:.0f} s)")
                print(f"[recut] piece {self.scenes[i].get('id') if isinstance(self.scenes[i], dict) else i}"
                      f"/{c.k + 1} not waited for: still in its {step or 'first'} step {now - began:.0f} s "
                      f"after it started", flush=True)
            self.late.add(key)
            self.note(key, "the time box ran out")
        return self.found

    def _all_stuck(self, keys: List[Tuple[int, int]], now: float) -> bool:
        """
        Every piece still out has been running past its own share and
        STRAGGLER_GRACE after it - stopped at its next search or download, but
        held inside one that does not return. A piece not started yet, or one
        without a share of its own (fewer pieces than threads), is waited for.
        """
        if not keys or not self.share:
            return False
        with self.lock:
            began = [self.began.get(k) for k in keys]
        return all(b is not None and now > b + self.share + STRAGGLER_GRACE for b in began)


# --------------------------------------------------------------------------- #
# Settling and building the new timeline
# --------------------------------------------------------------------------- #

def settle(segs: List[Seg], long_frames: float = math.inf) -> Tuple[List[Seg], List[Tuple[int, str]]]:
    """
    A scene's pieces with nothing missing. The pieces are grouped back
    together where shots are missing, each group shown by one shot that plays
    it at real speed (a still covers any length; the scene's own shot covers
    its whole line and always opens it); the shots keep their order. Chosen
    all at once over the groupings (a few pieces a scene): the fewest shots
    still over the cap (`long_frames`), then the least time over it, then
    the most shots kept, then each shot as near its own words as can be - a
    piece nothing was found for goes into the shot beside it, or a new shot
    moves on to it while the scene's own shot takes its old place. Never an
    empty piece, never a slowed clip. Returns (the pieces, [(piece, why) of
    the new shots that found no place]). Only a scene that had no shot at all
    (an empty scene nothing covers) ends as one piece without one.
    """
    n = len(segs)
    if not n:
        return [], []
    shots = [(i, s.found) for i, s in enumerate(segs) if s.found is not None]
    opens = bool(shots) and shots[0][0] == 0 and shots[0][1].how == "original"
    inf = (math.inf,) * 5
    best: Dict[Tuple[int, int], Tuple[float, ...]] = {}
    pick: Dict[Tuple[int, int], Tuple[int, int]] = {}
    m = len(shots)
    for j in range(m + 1):
        best[(n, j)] = (0.0,) * 5
    for p in range(n - 1, -1, -1):
        for j in range(m, -1, -1):
            here, choice = inf, None
            for t in range(j, m):
                if opens and (p == 0) != (t == 0):
                    continue                        # the scene's own shot opens it, and only it
                k, f = shots[t]
                for q in range(p + 1, n + 1):
                    length = segs[q - 1].end - segs[p].start
                    if f.cover + TOL < length:
                        break                       # (a longer group would not fit either)
                    rest = best.get((q, t + 1), inf)
                    if rest == inf:
                        continue
                    over = length > long_frames + 1e-6
                    # (Last, on a tie: the scene's own shot stays on longer - the plainest way back.)
                    cost = (rest[0] + (1 if over else 0), rest[1] + (length - long_frames if over else 0.0),
                            rest[2] - 1.0, rest[3] + (0.0 if p <= k < q else float(min(abs(k - p), abs(k - q + 1)))),
                            rest[4] - (length if f.how == "original" else 0))
                    if cost < here:
                        here, choice = cost, (t, q)
            best[(p, j)] = here
            if choice is not None:
                pick[(p, j)] = choice
    if best[(0, 0)] == inf:
        # Nothing can show the whole scene (an empty scene whose clips cover their own piece only).
        whole = Seg(segs[0].start, segs[-1].end, [w for s in segs for w in s.words],
                    [t for s in segs for t in s.texts], None, [k for s in segs for k in s.ks])
        return [whole], [(f.k, "nothing could show the rest of its scene") for _i, f in shots]
    out: List[Seg] = []
    gave_up: List[Tuple[int, str]] = []
    p, j = 0, 0
    while p < n:
        t, q = pick[(p, j)]
        for _i, f in shots[j:t]:
            if f.how != "original":
                gave_up.append((f.k, "its clip is too short for the time left beside it"))
        group = segs[p:q]
        out.append(Seg(group[0].start, group[-1].end, [w for s in group for w in s.words],
                       [x for s in group for x in s.texts], shots[t][1], [k for s in group for k in s.ks]))
        p, j = q, t + 1
    gave_up += [(f.k, "its clip is too short for the time left beside it") for _i, f in shots[j:]
                if f.how != "original"]
    return out, gave_up


def _letters():
    """b, c, ... z, ba, bb, ...: the second piece of s0012 is s0012-b."""
    abc = string.ascii_lowercase
    n = 1
    while True:
        out, x = "", n
        while True:
            out = abc[x % 26] + out
            x //= 26
            if not x:
                break
        yield out
        n += 1


def _motion(n: int, avoid: set) -> str:
    """A still's move: the n-th of the planner's moves, never its neighbours' (timeline._IMAGE_MOTIONS)."""
    if str(getattr(config, "STILL_MOTION", "") or "").lower() == "none":
        return "none"
    moves = list(timeline._IMAGE_MOTIONS)
    for k in range(len(moves)):
        pick = moves[(n + k) % len(moves)]
        if pick not in avoid:
            return pick
    return moves[n % len(moves)]


def _new_scene(orig: dict, seg: Seg, first: bool, n: int) -> dict:
    """A piece showing a new shot: the line's own fields, the shot's media and match record, a plain cut in."""
    f = seg.found
    if first:
        # An empty scene's first piece: its id, entrance, look and grade, now with a shot.
        s = copy.deepcopy(orig)
        s.pop("wantedPictures", None)
        s.pop("animation", None)
    else:
        s = {k: copy.deepcopy(orig[k]) for k in ("query", "visualType", "treatment", "effect", "frame") if k in orig}
        s["transition"] = "none"            # a plain cut inside one line: no transition, no transition sound
    sem = {k: v for k, v in copy.deepcopy(orig.get("semanticMetadata") or {}).items() if k not in SHOT_FIELDS}
    sem.update(copy.deepcopy(f.sem))
    sem["recut"] = {"from": str(orig.get("id") or ""), "how": f.how}
    s["media"] = copy.deepcopy(f.media)
    s["semanticMetadata"] = sem
    s["motion"] = (_motion(n, {str(orig.get("motion") or "")}) if (f.media or {}).get("type") == "image" else "none")
    s["reviewRequired"], s["reviewReason"] = bool(f.review[0]), str(f.review[1] or "")
    return s


def assemble(doc: dict, plans: List[Plan], shots: Dict[Tuple[int, int], Optional[Found]]
             ) -> Tuple[List[dict], List[Optional[Tuple[int, int]]], Dict[Tuple[int, int], str], Dict[int, List[Seg]]]:
    """
    (the new scenes, for each the (scene, piece) of the new shot it shows or
    None, the new shots given up while settling and why, the settled pieces of
    each planned scene). Pure: the timeline is read, never changed.
    """
    scenes = doc.get("scenes") or []
    plan_of = {p.index: p for p in plans}
    ids = {str(s.get("id") or "") for s in scenes if isinstance(s, dict)}
    out: List[dict] = []
    marks: List[Optional[Tuple[int, int]]] = []
    gave: Dict[Tuple[int, int], str] = {}
    settled: Dict[int, List[Seg]] = {}
    for i, orig in enumerate(scenes):
        p = plan_of.get(i)
        if p is None:
            out.append(copy.deepcopy(orig))
            marks.append(None)
            continue
        segs = []
        for c in p.pieces:
            f = Found(how="original", cover=math.inf, k=0) if c.k == 0 and p.kind != "empty" else shots.get((i, c.k))
            segs.append(Seg(c.start, c.end, [dict(w) for w in c.words], [c.text], f, [c.k]))
        segs, given = settle(segs, p.limit)
        for k, why in given:
            gave[(i, k)] = why
        settled[i] = segs
        if len(segs) == 1 and (segs[0].found is None or segs[0].found.how == "original"):
            out.append(copy.deepcopy(orig))            # the scene as it was
            marks.append(None)
            continue
        letters = _letters()
        shown_alts = {sg.found.alt for sg in segs if sg.found.how != "original" and sg.found.alt is not None}
        for n, sg in enumerate(segs):
            first = n == 0
            if sg.found.how == "original":
                s = copy.deepcopy(orig)
                sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else None
                if sem is not None and shown_alts and isinstance(sem.get("alternatives"), list):
                    # A runner-up now on screen leaves the line's choices; its other choices stay.
                    sem["alternatives"] = [a for k, a in enumerate(sem["alternatives"]) if k not in shown_alts]
            else:
                s = _new_scene(orig, sg, first, i + n)
            if first:
                s["id"] = str(orig.get("id") or f"s{i:04d}")
            else:
                base = str(orig.get("id") or f"s{i:04d}")
                sid = f"{base}-{next(letters)}"
                while sid in ids:
                    sid = f"{base}-{next(letters)}"
                ids.add(sid)
                s["id"] = sid
            s["startFrame"], s["durationInFrames"] = int(sg.start), int(sg.frames)
            s["words"] = [dict(w) for w in sg.words]
            s["text"] = " ".join(t for t in sg.texts if t).strip()
            out.append(s)
            marks.append((i, sg.found.k) if sg.found.how != "original" else None)
    return out, marks, gave, settled


def repeats(scenes: List[dict], marks: List[Optional[Tuple[int, int]]], fps: int) -> List[Tuple[int, str]]:
    """
    [(place, why)] of every new shot that repeats a shot the video shows - the
    same file, asset or moment, the same source video on the next scene unless
    a planned chain (gapfill.Used, the check the render's quality gate makes).
    The video's own shots always win; of two new shots the earlier one does.
    """
    used = gapfill.Used()
    shots = [gapfill.Shot.of_scene(s, fps) if isinstance(s, dict) else None for s in scenes]
    for j, sh in enumerate(shots):
        if marks[j] is None and sh is not None:
            used.add(j, sh)
    bad = []
    for j, sh in enumerate(shots):
        if marks[j] is None or sh is None:
            continue
        why = used.why_not(j, sh)
        if why:
            bad.append((j, why))
        else:
            used.add(j, sh)
    return bad


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #

def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "job"))[:80] or "job"


def backup_key(project_id: str, job_id: str, suffix: str = "") -> str:
    return f"projects/{project_id}/backups/scene_data-{_safe(job_id)}{suffix}.json"


def _ours(project_id: str, key: str) -> bool:
    from . import restore
    return restore._ours(project_id, (config.R2_BUCKET, key))


def save_json(project_id: str, key: str, doc: dict) -> str:
    """One timeline as JSON under the project's own folder of R2, never over an object that is there. Its key."""
    if not _ours(project_id, key):
        raise RecutError(f"{key} is not under this project's folder: nothing written")
    if r2.head(key) is not None:
        raise RecutError(f"{key} is there already: a re-cut never overwrites a file")
    r2.upload_bytes(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), key,
                    content_type="application/json", deadline=time.time() + 120, cache_control="no-store")
    return key


def hold_project(project_id: str, say: Callable, wait: float = WRITE_WAIT,
                 step: str = "Re-clipping") -> Tuple[bool, str]:
    """
    The project held for this job BEFORE anything is spent or written (a re-clip that saves as it goes,
    src/reclip.py): with the service key at once; through the app's storage broker the same hand-over as
    write_project - a one-field update (current_step) every POLL seconds for up to `wait`, its status saying it
    waits (awaitHandover) - until the row is "rendering" under this job. (True, "") or (False, why).
    """
    if not storage.broker_enabled():
        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            return True, ""
        return False, "this worker has no way to write the project (no storage broker, no service key)"
    if not storage.CURRENT_JOB[0]:
        return False, "no job id to write the project as"
    until = time.time() + max(0.0, float(wait))
    told = False
    while True:
        if storage.patch_project(project_id, {"current_step": step}, wait=True):
            return True, ""
        if time.time() + POLL > until:
            return False, ("the project was not handed to this job"
                           + (f" within {wait / 60.0:.0f} min" if wait else "")
                           + ": nothing was spent or written")
        if not told:
            extra = getattr(say, "extra", None)
            if isinstance(extra, dict):
                extra["awaitHandover"] = {"job": storage.CURRENT_JOB[0], "project": project_id, "until": int(until)}
            say("Waiting for the project to be handed to this job", 3)
            told = True
        time.sleep(POLL)


def save_project(project_id: str, doc: dict, step: str, final: bool = False) -> bool:
    """One save of a held project's timeline: the row stays "rendering" under this job (more saves follow)
    unless `final` (status "editing", progress 100). False when the app did not take it."""
    fields = {"scene_data": doc, "current_step": step}
    if final:
        fields.update(status="editing", progress=100)
    try:
        return bool(storage.patch_project(project_id, fields, wait=True))
    except Exception as e:  # noqa: BLE001 - not saved, said by the caller
        print(f"[recut] a save of {project_id} broke: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


def release_project(project_id: str, why: str) -> bool:
    """A held project handed back without a new timeline (the last save stands): status "editing"."""
    try:
        return bool(storage.patch_project(project_id, {"status": "editing", "current_step": why[:120]}, wait=True))
    except Exception:  # noqa: BLE001
        return False


def write_project(project_id: str, doc: dict, say: Callable, wait: float = WRITE_WAIT,
                  step: str = "Long shots re-cut") -> Tuple[bool, str]:
    """
    The project row, once: the re-cut timeline, status "editing", "Long shots
    re-cut", progress 100. With the service key it is written straight away.
    Through the app's storage broker (every deployed worker) the row must be
    "rendering" under this job first - the app hands a project to the job it
    starts. A re-cut started from a script asks with a one-field update
    (current_step) every POLL seconds for up to `wait`, its status saying it
    waits (awaitHandover, for scratchpad/recut_project.py), then writes the
    timeline; never anything else, nothing when it is not handed over.
    """
    fields = {"scene_data": doc, "status": "editing", "current_step": step, "progress": 100}
    if not storage.broker_enabled():
        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            if storage.patch_project(project_id, fields, wait=True):
                return True, ""
            return False, "the database did not take the update (see the job log)"
        return False, "this worker has no way to write the project (no storage broker, no service key)"
    if not storage.CURRENT_JOB[0]:
        return False, "no job id to write the project as"
    until = time.time() + max(0.0, float(wait))
    told = False
    while True:
        saving = "Saving the re-cut timeline" if step == "Long shots re-cut" else f"Saving: {step}"
        if storage.patch_project(project_id, {"current_step": saving}, wait=True):
            if storage.patch_project(project_id, fields, wait=True):
                return True, ""
            return False, "the project was handed over but the app did not take the timeline (see the job log)"
        if time.time() + POLL > until:
            return False, ("the project was not handed to this job"
                           + (f" within {wait / 60.0:.0f} min" if wait else "")
                           + " (the app's broker writes a project only while it is \"rendering\" under the job): "
                             "the re-cut timeline is kept beside the backup, apply it from there")
        if not told:
            extra = getattr(say, "extra", None)
            if isinstance(extra, dict):
                extra["awaitHandover"] = {"job": storage.CURRENT_JOB[0], "project": project_id, "until": int(until)}
            say("Waiting for the project to be handed to this job", 97)
            told = True
        time.sleep(POLL)


def _local_refs(doc: dict) -> List[str]:
    """Links in the timeline that are files on this disk (never saved: the next job cannot read them)."""
    out = []
    for s in doc.get("scenes") or []:
        m = s.get("media") if isinstance(s.get("media"), dict) else {}
        for k in ("url", "thumbnail", "previewUrl"):
            v = str(m.get(k) or "")
            if v and not v.startswith(("http://", "https://", "data:", "bgm://")) and (os.path.isabs(v) or os.sep in v
                                                                                     or "/" in v):
                out.append(f"{s.get('id')}: {k}")
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        for a in sem.get("alternatives") or []:
            if isinstance(a, dict) and a.get("localPath"):
                out.append(f"{s.get('id')}: a choice's file")
    return out


def _strip_local_alternatives(doc: dict) -> None:
    for s in doc.get("scenes") or []:
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        for a in sem.get("alternatives") or []:
            if isinstance(a, dict):
                a.pop("localPath", None)


def _check(doc: dict) -> None:
    """The timeline as the render would read it (a copy: nothing in it changes), or RecutError."""
    probe = copy.deepcopy(doc)
    try:
        timeline.drop_invalid_overlays(probe)
        timeline.validate(probe, require_media=False)
    except ValueError as e:
        raise RecutError(f"the timeline does not check out: {e}") from e


def _shots_over(doc: dict, cap: float, slack: float) -> List[float]:
    fps = _fps(doc)
    return [round(int(s.get("durationInFrames") or 0) / float(fps), 2) for s in doc.get("scenes") or []
            if kind_of(s) in ("video", "image") and int(s.get("durationInFrames") or 0) > (cap + slack) * fps + 1e-6]


# --------------------------------------------------------------------------- #
# The action
# --------------------------------------------------------------------------- #

def _cap(inp: dict) -> float:
    v = _num(inp.get("cap", inp.get("cap_seconds")))
    if v is None or v <= 0:
        v = CAP
    return float(min(shotcap.CEILING, max(shotcap.FLOOR, v)))


def run(inp: dict, doc: dict, work: str, report: Optional[Callable] = None, *,
        publish: Optional[Callable[[dict], int]] = None, choices: Optional[Callable[[dict], int]] = None,
        ready: Optional[Callable[[], None]] = None) -> dict:
    """
    Re-cut `doc` (the saved timeline). inp: project_id; apply (False = a dry
    run, the default); cap (seconds, 7.0); seconds (the time box, 2400);
    parallel (SOURCE_WORKERS); moments_per_scene (1); write_wait (seconds an
    apply waits to be handed the project, 900); expect_fingerprint (refuse a
    timeline that is not this one); allow_youtube / allow_stock / require_cc.
    `publish(doc)` saves the new files like a plan (handler.publish_media),
    `choices(doc)` their pick-a-shot runner-ups (handler._publish_choices),
    `ready()` refuses to start without AI credit or YouTube (the handler's
    checks) - all three only on an apply.

    Returns the plan, the counts and an estimate; an apply also what was done:
    the shots found and how, the pieces merged back and why, the scenes that
    stayed long, the backup, whether the project was written.
    """
    started = time.time()
    say = report or (lambda *a, **k: None)
    apply = bool(inp.get("apply"))
    project_id = str(inp.get("project_id") or "").strip()
    job_id = str(inp.get("_job_id") or "")
    cap = _cap(inp)
    lo = MIN_PIECE
    seconds = min(7200.0, max(60.0, _num(inp.get("seconds")) or SECONDS))
    workers = max(1, int(_num(inp.get("parallel")) or config.SOURCE_WORKERS))
    per_scene = max(0, int(_num(inp.get("moments_per_scene")) if _num(inp.get("moments_per_scene")) is not None
                           else MOMENTS_PER_SCENE))
    fps = _fps(doc)
    fp = fingerprint(doc)
    expect = str(inp.get("expect_fingerprint") or "").strip().lower()
    if expect and expect != fp:
        raise RecutError(f"the timeline read (fingerprint {fp[:12]}...) is not the one expected ({expect[:12]}...): "
                         "it changed since it was checked against the database - nothing was done")
    _check(doc)
    say("Re-cutting long shots: reading the timeline", 2)
    plans, left, counts = plan_doc(doc, cap, lo)
    est = estimate(doc, plans, workers, per_scene, seconds)
    out: Dict[str, Any] = {
        "ok": True, "project_id": project_id, "dry_run": not apply, "fingerprint": fp, "fps": fps, "cap": cap,
        "minPiece": lo, **counts, "stayLong": {"count": len(left), "why": _why_counts(left)}, "left": left[:200],
        "estimate": est, "plan": [_plan_row(p, fps) for p in plans]}
    print(f"[recut] {counts['scenes']} scenes at {fps} fps: {counts['long']} over {cap + SLACK:g} s "
          f"{counts['longByKind']} (longest {counts['longest']} s); {counts['cut']} cut into {counts['pieces']} "
          f"piece(s), {counts['newPieces']} new shot(s) to find; {len(left)} stay long; "
          f"estimate {est['ladder']}, ~{est['visionCalls']} vision calls, ~{est['minutes']} min, ~${est['usd']}",
          flush=True)
    if not apply:
        for row in out["plan"][:400]:
            print(f"[recut] PLAN {row['scene']:>10s} {row['kind']:5s} {row['seconds']:6.2f} s -> {row['pieces']}"
                  + (f" cut before {row['cutBefore']}" if row["cutBefore"] else ""), flush=True)
        for row in left[:200]:
            print(f"[recut] STAYS {row['scene']:>10s} {row['seconds']:6.2f} s: {row['why']}", flush=True)
        events.emit("recut", "dry_run", data={k: counts[k] for k in ("scenes", "long", "cut", "pieces", "newPieces")})
        out["seconds"] = round(time.time() - started, 1)
        return out

    # ------------------------------------------------------------------ apply
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", project_id):
        raise RecutError("an apply needs the project_id")
    if not r2.enabled():
        raise RecutError("Cloudflare R2 is not configured on this worker: there is nowhere to keep the backup "
                         "and the new shots")
    out.update(written=False, writeError="")
    if not any(p.needs() for p in plans):
        out["writeError"] = "nothing to re-cut"
        out["seconds"] = round(time.time() - started, 1)
        return out
    if ready is not None:
        ready()                         # no AI credit or no YouTube: refused before anything is written
    # The timeline as it was, first: everything after it can be undone.
    say("Re-cutting long shots: keeping the timeline as it was", 4)
    out["backup"] = save_json(project_id, backup_key(project_id, job_id), doc)
    print(f"[recut] the timeline as it was: {out['backup']}", flush=True)
    deadline = started + seconds
    # The end of the time box is kept for the polish and for saving the new files (8 at a time):
    # the search stops early enough for both.
    saving = 60.0 + counts["newPieces"] * PUBLISH_SECONDS / 8.0
    reserve = min(0.4 * seconds, saving + min(float(config.UPSCALE_SECONDS), 120.0))
    media.reset_cache()                 # a reused worker: what an earlier job found unusable is asked again
    media.limit_generation(0)           # never an AI-made picture to re-cut a real video
    finder = Finder(doc, plans, work, workers=workers, deadline=deadline - reserve, moments_per_scene=per_scene,
                    flags={"allow_youtube": inp.get("allow_youtube"), "allow_stock": inp.get("allow_stock"),
                           "require_cc": inp.get("require_cc")}, say=say)
    say("Re-sourcing long shots", 8)
    events.phase("recut-source")
    found = dict(finder.run())
    events.phase("recut")
    out["stageSeconds"] = media.stage_seconds()     # searches, downloads, checks and gates: thread-seconds

    # The same polish as a plan (upscale.upscale_assets: a vertical clip framed, a soft one sharpened, a
    # small photo upscaled), time-boxed; then each file's real length and tone, while it is on this disk.
    say("Polishing the new shots", 80)
    assets = [f.asset for f in found.values() if f.asset is not None]
    left_s = deadline - time.time() - saving
    if assets and (config.UPSCALE_ENABLED or config.ALLOW_VERTICAL or config.ARCHIVE_RESTORE) and left_s > 10:
        try:
            polished = upscale.upscale_assets(assets, deadline_seconds=min(float(config.UPSCALE_SECONDS), left_s))
            if config.ARCHIVE_RESTORE and (polished or {}).get("archiveRestore"):
                out["archiveRestore"] = polished["archiveRestore"]      # old footage restored (src/archive_restore.py)
        except Exception as e:  # noqa: BLE001 - never fail a re-cut over polish
            print(f"[recut] polish skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    _finish(found, fps, deadline - saving)

    shots: Dict[Tuple[int, int], Optional[Found]] = dict(found)
    dropped: Dict[Tuple[int, int], str] = {}
    scenes, marks, gave, settled = assemble(doc, plans, shots)
    for _round in range(8):
        bad = repeats(scenes, marks, fps)
        if not bad:
            break
        for j, why in bad:
            key = marks[j]
            print(f"[recut] {scenes[j].get('id')}: its new shot would repeat another scene ({why}); dropped",
                  flush=True)
            shots[key] = None
            dropped[key] = f"its new shot would repeat another scene ({why})"
        scenes, marks, gave, settled = assemble(doc, plans, shots)

    new_doc = {k: v for k, v in doc.items() if k not in ("scenes", "meta")}
    new_doc["meta"] = copy.deepcopy(doc.get("meta") or {})
    new_doc["scenes"] = scenes
    if not any(m is not None for m in marks) and not _filled_empties(doc, scenes):
        out["writeError"] = "no new shot was found: nothing changed"
        _summarise(out, doc, new_doc, plans, finder, shots, dropped, gave, settled, cap)
        out["seconds"] = round(time.time() - started, 1)
        return out

    # The new files to R2 like a plan saves them; one that cannot be saved goes back into its neighbour.
    ledger.note({"fps": fps, "meta": new_doc["meta"],
                 "scenes": [s for s, m in zip(scenes, marks) if m is not None]})   # photos still here to hash
    if publish is not None:
        meta = new_doc["meta"]
        warnings = list(meta.get("warnings") or [])
        published = int(_num(meta.get("publishedMedia")) or 0)
        meta.setdefault("warnings", [])
        for _round in range(4):
            published += int(publish(new_doc) or 0)
            # (publish_media counts this call's files and warns about the ones it could not save:
            # those go back into their neighbours below, so the plan's own counts and warnings stand.)
            meta["warnings"], meta["publishedMedia"] = list(warnings), published
            failed = []
            for j, key in enumerate(marks):
                if key is None or shots.get(key) is None:
                    continue
                sm = new_doc["scenes"][j].get("media") or {}
                url = str(sm.get("url") or "")
                if url.startswith(("http://", "https://")):
                    shots[key].media = copy.deepcopy(sm)        # its saved links, kept through a re-settle
                else:
                    failed.append(key)
            if not failed:
                break
            for key in failed:
                shots[key] = None
                dropped[key] = "its file could not be saved"
            scenes, marks, gave, settled = assemble(doc, plans, shots)
            new_doc["scenes"] = scenes
        if not any(m is not None for m in marks):
            out["writeError"] = "no new shot could be saved: nothing changed"
            _summarise(out, doc, new_doc, plans, finder, shots, dropped, gave, settled, cap)
            out["seconds"] = round(time.time() - started, 1)
            return out
    if choices is not None and time.time() < deadline:
        try:
            choices(new_doc)                # the new shots' pick-a-shot runner-ups, while the box has time
        except Exception as e:  # noqa: BLE001 - the choices are a nicety
            print(f"[recut] runner-ups not saved: {type(e).__name__}: {str(e)[:100]}", flush=True)
    _strip_local_alternatives(new_doc)      # a choice not saved keeps its scores, never a file path
    leftovers = _local_refs(new_doc)
    if leftovers:
        raise RecutError(f"{len(leftovers)} link(s) would point at files on this worker ({leftovers[:3]}): "
                         "nothing was written to the project")
    for k in doc:
        if k not in ("scenes", "meta") and json.dumps(doc[k], sort_keys=True, default=str) != \
                json.dumps(new_doc[k], sort_keys=True, default=str):
            raise RecutError(f"the timeline's {k} changed: nothing was written to the project")
    _update_meta(new_doc)
    _check(new_doc)
    _summarise(out, doc, new_doc, plans, finder, shots, dropped, gave, settled, cap)
    new_doc["meta"]["recut"] = {
        "cap": out["cap"], "totals": out["totals"], "stayLong": out["stayLong"], "job": job_id,
        "backup": out.get("backup", ""), "fingerprintBefore": fp,
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    out["fingerprintAfter"] = fingerprint(new_doc)
    out["recutKey"] = save_json(project_id, backup_key(project_id, job_id, "-recut"), new_doc)
    say("Saving the re-cut timeline", 95)
    wait = _num(inp.get("write_wait"))
    written, why = write_project(project_id, new_doc, say, WRITE_WAIT if wait is None else max(0.0, wait))
    out["written"], out["writeError"] = written, why
    if written:
        ledger.save(job_id, project_id)            # later videos never show these moments again
    out["timeline"] = new_doc
    t = out["totals"]
    events.emit("recut", "summary", level="info" if written else "warning",
                data={k: t.get(k) for k in ("scenesBefore", "scenesAfter", "longBefore", "longAfter", "newShots")},
                message=(f"{t['newShots']} new shot(s); {t['longAfter']} shot(s) still over {cap + SLACK:g} s; "
                         + ("saved" if written else f"NOT saved: {why}"))[:300])
    print(f"[recut] {project_id}: {t['scenesBefore']} -> {t['scenesAfter']} scenes, {t['newShots']} new shot(s) "
          f"{t['by']}, {t['mergedBack']} piece(s) merged back, {t['longAfter']} still over {cap + SLACK:g} s; "
          + ("project saved" if written else f"project NOT saved: {why}"), flush=True)
    out["seconds"] = round(time.time() - started, 1)
    out["timedOut"] = bool(finder.late)
    return out


def _filled_empties(doc: dict, scenes: List[dict]) -> int:
    before = sum(1 for s in doc.get("scenes") or [] if kind_of(s) == "empty")
    after = sum(1 for s in scenes if kind_of(s) == "empty")
    return max(0, before - after)


def _finish(found: Dict[Tuple[int, int], Found], fps: int, deadline: float) -> None:
    """Each found file's scene media: its real length (the cover a merge relies on) and its tone, in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    def one(f: Found) -> None:
        a = f.asset
        if a is None:
            return
        m = a.to_scene_media()
        if a.kind == "video":
            secs = timeline._clip_seconds(a)
            if secs > 0:
                m["clipSeconds"] = round(secs, 2)
                f.cover = secs * fps
        if time.time() < deadline and grade.is_local(m.get("url")):
            try:
                tone = grade.measure(m)
            except Exception:  # noqa: BLE001 - the render measures what has none
                tone = None
            if tone:
                m["tone"] = tone
        f.media = m
        f.sem = _asset_sem(a)
        if f.how in ("search", "picture"):
            f.review = (bool(a.review_required), a.review_reason or "")
        elif not f.review[0]:
            f.review = _licence_review(a.license)

    items = [f for f in found.values() if f.asset is not None]
    if not items:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(items)), thread_name_prefix="recut-finish") as pool:
        list(pool.map(one, items))


def _why_counts(rows: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r["why"]] = out.get(r["why"], 0) + 1
    return out


def _update_meta(doc: dict) -> None:
    """The counts the editor shows, as the timeline now stands (the shot cap's report too, when it has one)."""
    meta = doc.setdefault("meta", {})
    fps = _fps(doc)
    scenes = doc.get("scenes") or []
    meta["sceneCount"] = len(scenes)
    if "cutsPerMinute" in meta:
        minutes = int(doc.get("durationInFrames") or 0) / float(fps) / 60.0
        meta["cutsPerMinute"] = round(len(scenes) / max(minutes, 0.01), 1)
    meta["scenesWithoutMedia"] = sum(1 for s in scenes if kind_of(s) == "empty")
    meta["scenesNeedingReview"] = sum(1 for s in scenes if s.get("reviewRequired"))
    if isinstance(meta.get("shotCap"), dict) and shotcap.enabled():
        try:
            meta["shotCap"] = shotcap.report(doc, meta["shotCap"])
        except Exception:  # noqa: BLE001 - a report only
            pass


def _summarise(out: dict, doc: dict, new_doc: dict, plans: List[Plan], finder: Finder,
               shots: Dict[Tuple[int, int], Optional[Found]], dropped: Dict[Tuple[int, int], str],
               gave: Dict[Tuple[int, int], str], settled: Dict[int, List[Seg]], cap: float) -> None:
    """The counts, the piece log and the scenes that stayed long (and why) into the result."""
    fps = _fps(doc)
    scenes = new_doc.get("scenes") or []
    by: Dict[str, int] = {}
    final_id: Dict[Tuple[int, int], str] = {}       # (scene, piece) -> the new scene its time ended up in
    shown_at: Dict[Tuple[int, int], str] = {}       # (scene, piece) -> the new scene showing the shot found for it
    pos = 0
    plan_of = {p.index: p for p in plans}
    for i, orig in enumerate(doc.get("scenes") or []):
        segs = settled.get(i)
        if segs is None or (len(segs) == 1 and (segs[0].found is None or segs[0].found.how == "original")):
            for c in (plan_of[i].pieces if i in plan_of else []):
                final_id[(i, c.k)] = str(scenes[pos].get("id") or "") if pos < len(scenes) else ""
            pos += 1
            continue
        for sg in segs:
            sid = str(scenes[pos].get("id") or "") if pos < len(scenes) else ""
            for k in sg.ks:
                final_id[(i, k)] = sid
            if sg.found is not None and sg.found.how != "original":
                by[sg.found.how] = by.get(sg.found.how, 0) + 1
                shown_at[(i, sg.found.k)] = sid
            pos += 1
    rows = []
    merged = 0
    for p in plans:
        segs = settled.get(p.index) or []
        own = {sg.found.k for sg in segs if sg.found is not None and sg.found.how != "original"}
        for c in p.needs():
            key = (p.index, c.k)
            f = finder.found.get(key)
            if c.k in own:
                result, why = "new", ""
            else:
                merged += 1
                result = "merged"
                why = (dropped.get(key) or gave.get(key)
                       or ("the time box ran out" if key in finder.late else "nothing usable was found"))
            row = {"scene": p.id, "piece": c.k + 1, "at": round(c.start / float(fps), 2),
                   "seconds": round(c.frames / float(fps), 2), "result": result,
                   "as": shown_at.get(key) or final_id.get(key, "")}
            if result == "new" and shown_at.get(key) and shown_at[key] != final_id.get(key):
                row["moved"] = True                 # its shot moved on to the piece after it (settle)
            if f is not None:
                row.update(how=f.how, detail=f.detail)
            if why:
                row["why"] = why
            tried = finder.notes.get(key) or []
            if tried and result != "new":
                row["tried"] = tried[:4]
            spent = finder.took.get(key)
            if spent:
                row["spent"] = dict(spent)          # seconds on each rung: where the piece's time went
            rows.append(row)
    stay: List[dict] = []
    for r in out.get("left") or []:
        stay.append(dict(r))
    for p in plans:
        if not p.long or p.why:
            continue
        segs = settled.get(p.index) or []
        longest = max((sg.frames for sg in segs), default=0)
        if longest > (cap + SLACK) * fps + 1e-6:
            missing = [r for r in rows if r["scene"] == p.id and r["result"] != "new"]
            reasons = sorted({r.get("why", "") for r in missing if r.get("why")})
            stay.append({"scene": p.id, "index": p.index, "seconds": round(longest / float(fps), 2),
                         "why": (f"no new shot for {len(missing)} of its piece(s): " + "; ".join(reasons))[:300]
                         if missing else "a piece stays over the cap (its words left no other cut)"})
    over_after = _shots_over(new_doc, cap, SLACK)
    rung_seconds: Dict[str, float] = {}
    for spent in finder.took.values():
        for rung, secs in spent.items():
            rung_seconds[rung] = round(rung_seconds.get(rung, 0.0) + secs, 1)
    out["totals"] = {
        "scenesBefore": len(doc.get("scenes") or []), "scenesAfter": len(scenes),
        "longBefore": len(_shots_over(doc, cap, SLACK)), "longAfter": len(over_after),
        "longestAfter": max(over_after, default=0.0), "cut": sum(1 for s in settled.values() if len(s) > 1),
        "newShots": sum(by.values()), "by": by, "mergedBack": merged,
        "emptyFilled": _filled_empties(doc, scenes), "lateByTimeBox": len(finder.late),
        "notWaitedFor": len(finder.stuck), "rungSeconds": rung_seconds}
    out["stayLong"] = {"count": len(stay), "why": _why_counts([{"why": r["why"].split(":")[0]} for r in stay])}
    out["left"] = stay[:200]
    out["rows"] = rows[:ROWS]
