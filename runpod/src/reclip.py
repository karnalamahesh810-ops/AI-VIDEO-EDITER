"""
Re-clip a timeline that is already sourced: the first minute, every empty or
text-filled scene, every clip that should not be there and the weakest
pictures get real video clips, judged like a plan judges them; the words, the
timing, the graphics, the music and the voice stay (the owner, 2026-10-06, on
"Why Barack Obama's Brothers HATED Him So Much", 70bc06d2: 29 clips in 192
scenes, the first minute almost without one, 11 empty spots shown as text -
"video clips are the main part of what we make ... make it better and
cleaner"; then on "California's Water Clock", c4db28b3, built while the judge
was out of credit: "replace the bad clips - swap and fix the bad ones - and
don't burn my credits"; and rapper / music-video clips in stories that are not
about music: "we don't want those clips in our videos").

  check   (apply) every clip nothing judged (judgedBy none / local, or no
          score) is read from its saved copy and judged against its own line:
          one model call each, CHECK_PARALLEL at a time. Kept: its record gets
          the verdict. Turned down: it becomes a target.
  plan    the scenes to re-clip, in order (plan_targets):
            0  in the first HOOK_SECONDS: every scene that is not a clip (a
               document's scan excepted), every empty or text-filled scene,
               every clip to replace - the opening first;
            1  every other empty or text-filled scene (a colour scene, the
               last resort's text card or line graphic) and every other clip
               to replace: a music video, a rap performance, a club or a
               smoking / drugs / drinking scene in a story and a line not about
               it (src/topics.py), or a clip the check turned down;
            2  the pictures, weakest first: an AI picture, a picture held
               over, borrowed or found in the last pass without a judge, then
               by the judge's score - never a document's scan, a named
               person's portrait, a map / chart line or a picture a graphic
               points into.
          A planner's own graphics (data looks, maps) and the good clips stay.
  source  each target, on SOURCE_WORKERS threads under one time box and one
          budget (budget_usd, BUDGET_USD by default), cheapest first:
            a  its own runner-up the judge approved when the plan found it
               (a published pick-a-shot choice, or that YouTube moment): no
               model call;
            b  a clip of the line's subject from the clip library or the niche
               packs (already on storage), judged for this line;
            c  another moment of a clip the video shows (gapfill._from_moment:
               judged, the variety rules);
            d  the clip-first search (media.source_for_segment clips_only: the
               line's own wordings, then wider rungs naming its subject), judged,
               narrower than a plan's (RECLIP_CONFIG) - only while the budget
               lasts, and never for a line YouTube's free search names nothing
               for (probe, run first: those lines found nothing and cost most);
            e  an empty, text-filled or turned-down line: a picture
               (gapfill's picture rung, a push-in and depth layers).
          Never a video the timeline already shows (a moment excepted, under
          the variety rules), never a moment an earlier video showed
          (src/ledger.py); a picture is only ever replaced by a clip that
          passed the judge (never a near-miss).
  settle  a picture nothing better was found for stays as it was, and so does
          a data look of a line's figure, and so does a shot the check turned
          down (marked for review: clearing them held neighbours over 23 lines
          and left 8 text cards on the Obama re-clip, 2026-10-07). An empty or
          text-filled scene, and a shot off the story, nothing was found for
          goes through the no-text last resort
          (gapfill.hold_or_animate, NO_TEXT_FILL): a data look of its figure,
          the shot beside it held, another moment of any clip, a still beside
          it held - never a text card while anything real can stand in, never
          a scene left empty.
  save    (apply, with expect_fingerprint) as recut saves: the timeline as it
          was to R2 first (projects/<project>/backups/scene_data-<job>.json),
          the new files as a plan publishes them, the new timeline beside the
          backup (-reclip), then the project row once (recut.write_project:
          the broker writes only while the project is "rendering" under this
          job - the runner prints the hand over).

A dry run (the default) reads the timeline and returns the plan with an
estimate - nothing is written and nothing paid for: the clips and pictures nothing judged
are counted (and how many of them have a title that does not name their
line), and the music / smoking scenes the topic rules see are listed. With
"probe": true it also asks YouTube's search (free: one flat search per
target, no download, no model call) how many usable candidates each target
has, so the estimate says how many clips to expect - from what the Obama
re-clip measured (PASS_LOW) to what the water builds did (PROBE_HIT).

A trial ("trial": true, best with "only": a few scene indices) runs the paid
search on its targets under its own small cap (TRIAL_BUDGET_USD) and time box
and writes nothing anywhere: what each would get, and - for every target of a
trial or an apply - a trace of each search, download, filter and verdict
(media._TRACE) and their sum ("why").
"""
from __future__ import annotations

import contextvars
import copy
import datetime
import json
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, costs, events, gapfill, grade, ledger, media, r2, recut, shotcap, storage, timeline, topics
from . import replan, ytdlp

SECONDS = 2400.0           # the time box (s)
WRITE_WAIT = recut.WRITE_WAIT
STRAGGLER_GRACE = 120.0    # a target still running this long past its share, once the rest are in, is let go
PAD = media.SEQ_SHOT_PAD
ROWS = 600                 # plan / result rows kept in a job result
# The owner's cap for one video's re-clip (RunPod + OpenRouter), 2026-10-06: "don't burn my credits".
BUDGET_USD = 1.50
# A trial (the paid search on a few lines, nothing written): its own small cap and time box.
TRIAL_BUDGET_USD = 0.10
TRIAL_SECONDS = 420.0
CHECK_PARALLEL = 8
CHECK_MAX_MB = 300         # a saved clip larger than this is not read for the check

# The estimate, from the owner's own jobs - and from the Obama re-clip of 2026-10-07 (70bc06d2, 110 lines
# searched): 864 vision calls for $0.827 on google/gemini-2.5-flash ($0.00096 a call: a storyboard pick sends
# a 20-tile sheet), ~7.9 calls a line; a line's search held one thread ~5 min (YouTube sections at 34 s
# through busy proxies, the gate at 28 s, every wording and rung walked when nothing passed) - narrower
# under RECLIP_CONFIG, ~3 min; another moment ~0.7 min, the check of a saved shot ~0.15 min (read from
# storage, one call); the 16-core serverless worker costs $0.576 an hour; a new file is saved in ~4 s (8 at a
# time). PROBE_HIT: the share of targets the search fills when the probe has not been asked (the owner's
# water builds: ~45-60% of footage lines). PASS_LOW: what the Obama re-clip measured - 8 clips for 110 lines
# with YouTube candidates (the judge turns most news and interview footage down for a line about one person,
# one paper or one feeling); the estimate gives both ends.
VISION_PER_SEARCH = 7.9
VISION_PER_MOMENT = 2.0
VISION_PER_CHECK = 1.0
VISION_USD = 0.00096
SEARCH_MINUTES = 3.0
MOMENT_MINUTES = 0.7
CHECK_MINUTES = 0.15
PUBLISH_SECONDS = 4.0
WORKER_USD_PER_MINUTE = 0.576 / 60.0
PROBE_HIT = 0.65
PASS_LOW = 0.08
# A re-clip's searches, narrower than a plan's (the job's own "config" wins): its own two wordings and two
# wider rungs on YouTube, no other clip source (Dailymotion, web video and the archives found nothing in
# the Obama re-clip and cost a third of its time), two scouts a search, 12 model calls and 3 minutes a line.
RECLIP_CONFIG = {"CLIP_WORDINGS": 2, "CLIP_RUNGS": 2, "CLIP_OTHER_WORDINGS": 0, "CLIPS_FIRST_POOL_SCOUT": 2,
                 "CLIPS_FIRST_JUDGE_MAX_PER_SCENE": 12, "SCENE_SECONDS_MAX": 180.0}
# What the budget keeps back for a step while it runs (its worst case: a clip-first search's 20 model calls
# and its share of the worker's time; a moment's or a picture's 4 calls; one call), and for the saving at
# the end.
STEP_USD = {"search": 0.012, "moment": 0.005, "picture": 0.005, "shelf": 0.002, "check": 0.002}
SAVE_USD = 0.05

# The last resort's own looks on a line nothing was found for (gapfill._card, quality.text_scene,
# gapfill.hold_or_animate's graphic, hookcheck.clear). A text card is not a shot; a data look of the line's
# figure is (it stays when nothing better is found).
_TEXT_REASONS = ("No usable clip found", "Nothing usable was found", "The start of the video: its clip was turned down")
_DATA_REASONS = ("No footage found",)
_FILLER_REASONS = _TEXT_REASONS + _DATA_REASONS
# Reasons that say a picture is a stand-in, weakest first in the plan.
_WEAK_REASONS = ("Held over", "Picture found in the last pass", "Best available", "Found in the last pass",
                 "Nothing was found", "A picture found when", "Not checked by the vision AI")


class ReclipError(RuntimeError):
    """The action cannot go on; nothing was written."""


@dataclass
class Found:
    index: int
    how: str = ""                       # "runner-up" | "library" | "pack" | "moment" | "clip" | "picture"
    asset: Any = None                   # a MediaAsset, or None for a published runner-up (media / sem below)
    note: str = ""
    media: Optional[dict] = None
    sem: Dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        if self.asset is not None:
            return str(getattr(self.asset, "kind", "") or "")
        return str((self.media or {}).get("type") or "")


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sem(s: dict) -> dict:
    return s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}


def kind_of(s: Any) -> str:
    """recut.kind_of, plus "filler": the last resort's text card or line-as-graphic on a line nothing was found for."""
    k = recut.kind_of(s)
    if not isinstance(s, dict):
        return k
    reason = str(s.get("reviewReason") or "")
    if k in ("graphic", "empty") and reason.startswith(_FILLER_REASONS):
        return "filler"
    return k


def _data_look(s: dict) -> bool:
    """A filler that shows the line's figure (a data look): it stays when nothing better is found."""
    return kind_of(s) == "filler" and str(s.get("reviewReason") or "").startswith(_DATA_REASONS)


def _still_kind(s: dict) -> bool:
    """A still that is the right shot for its line: a document's scan, a named person's portrait, a map / chart."""
    sem = _sem(s)
    st = str(sem.get("subjectType") or "")
    if st == "document":
        return True
    if st == "person" and str(s.get("visualType") or "") == "image":
        return True
    si = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else None
    return bool(si) and media.wanted_kind(si) in ("map", "chart", "document")


def _title(s: dict) -> str:
    m = s.get("media") if isinstance(s.get("media"), dict) else {}
    t = str(m.get("attribution") or "")
    for prefix in ("YouTube: ", "Dailymotion: "):
        if t.startswith(prefix):
            t = t[len(prefix):]
    return t


def _line(s: dict) -> str:
    return f"{_sem(s).get('intent') or ''} {s.get('text') or ''}"


def off_story(s: dict) -> str:
    """
    Why a scene's clip or picture is a music video, a rap or music performance, a club or a smoking / drugs /
    drinking scene in a story and a line not about it (src/topics.py - its title, its channel words and the
    judge's description of it), "" when it is not.
    """
    if kind_of(s) not in ("video", "image"):
        return ""
    title, line = _title(s), _line(s)
    return (topics.scene_reason(f"{title} {_sem(s).get('contentDescription') or ''}", line)
            or topics.off_topic_title(title, "", line=line))


def needs_check(s: dict) -> bool:
    """A clip or picture nothing judged (no score, or kept by the local model or by its title alone) - a
    document's scan excepted (the judge's score says little about a page)."""
    if kind_of(s) not in ("video", "image"):
        return False
    sem = _sem(s)
    if str(sem.get("subjectType") or "") == "document":
        return False
    return _num(sem.get("relevanceScore")) is None or str(sem.get("judgedBy") or "") in ("none", "local")


def weakness(s: dict) -> float:
    """How much a picture is a stand-in (0..1, higher = re-clip it sooner)."""
    m = s.get("media") if isinstance(s.get("media"), dict) else {}
    sem = _sem(s)
    if str(m.get("source") or "") == "generated":
        return 1.0
    rel = _num(sem.get("relevanceScore"))
    w = 0.7 if rel is None else max(0.0, min(1.0, 1.0 - rel))
    if str(s.get("reviewReason") or "").startswith(_WEAK_REASONS):
        w += 0.3
    if sem.get("borrowedFrom"):
        w += 0.3
    if str(sem.get("judgedBy") or "") in ("none", "local"):
        w += 0.1
    return round(min(1.0, w), 3)


def _anchored(doc: dict, s: dict) -> bool:
    """A graphic placed ON this scene's picture (a mark's arrow, a callout's point) points at something in it."""
    start = int(s.get("startFrame") or 0)
    return recut._anchored_until(doc, start, start + int(s.get("durationInFrames") or 0)) > 0


def plan_targets(doc: dict, *, pictures: bool = True, limit: Optional[int] = None,
                 hook_seconds: Optional[float] = None, checked: Optional[Dict[int, dict]] = None) -> List[dict]:
    """
    The scenes to re-clip, in the order they are worked: [{"index", "id", "tier", "kind", "why", ...}] (module
    doc). kind: "empty" | "filler" | "image" | "bad" (a clip or picture that must go: off the story, or turned
    down by the check - `checked`, {index: check_clips' row}).
    """
    fps = recut._fps(doc)
    hook = float(config.HOOK_SECONDS if hook_seconds is None else hook_seconds)
    checked = checked or {}
    rows = []
    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        k = kind_of(s)
        sem = _sem(s)
        start = int(s.get("startFrame") or 0) / float(fps)
        in_hook = start < hook
        why = ""
        if k == "video":
            why = off_story(s)
            c = checked.get(i)
            if not why and c is not None and not c.get("keep"):
                why = f"the judge turned it down: {c.get('why') or 'not for this line'}"
            if not why:
                continue
            kind, tier = "bad", 0 if in_hook else 1
        elif k in ("empty", "filler"):
            kind, tier = k, 0 if in_hook else 1
        elif k == "image":
            why = off_story(s)
            c = checked.get(i)
            if why:
                kind, tier = "bad", 0 if in_hook else 1
            elif _anchored(doc, s):
                continue                    # a graphic points into this very picture
            elif c is not None and not c.get("keep"):
                # A picture nothing had judged, turned down now (a wrong face, another place): it goes too.
                why = f"the judge turned it down: {c.get('why') or 'not for this line'}"
                kind, tier = "bad", 0 if in_hook else 1
            elif in_hook and str(sem.get("subjectType") or "") != "document":
                kind, tier = "image", 0
            elif not pictures or _still_kind(s):
                continue
            else:
                kind, tier = "image", 2
        else:
            continue
        rows.append({"index": i, "id": str(s.get("id") or f"#{i}"), "tier": tier, "kind": kind, "why": why[:120],
                     "start": round(start, 2), "seconds": round(int(s.get("durationInFrames") or 0) / float(fps), 2),
                     "weakness": weakness(s) if kind == "image" else 1.0,
                     "subject": str(sem.get("subject") or "")[:80], "subjectType": str(sem.get("subjectType") or ""),
                     "query": " ".join(str(s.get("query") or sem.get("searchQuery") or "").split())[:120],
                     "was": str((s.get("media") or {}).get("source") or k), "title": _title(s)[:80]})
    rows.sort(key=lambda r: (r["tier"], -r["weakness"] if r["tier"] == 2 else r["start"]))
    n = int(limit) if limit else 0
    return rows[:n] if n > 0 else rows


def job_for(doc: dict, i: int) -> dict:
    """The sourcing line of one scene (recut.Finder.job without the pieces): its search, intent and switches."""
    fps = recut._fps(doc)
    s = doc["scenes"][i]
    sem = _sem(s)
    si = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else None
    query = " ".join(str(s.get("query") or sem.get("searchQuery") or sem.get("subject") or s.get("text") or "")
                     .split())[:240]
    fallbacks: List[str] = []
    if si:
        try:
            from .intent import SceneIntent
            fallbacks = SceneIntent.from_dict(si).queries(query)[1:]
        except Exception:  # noqa: BLE001 - the query alone
            fallbacks = []
    start = int(s.get("startFrame") or 0) / float(fps)
    seconds = max(1.0, int(s.get("durationInFrames") or 0) / float(fps))
    return {"index": i, "query": query, "fallbacks": fallbacks, "intent": str(sem.get("intent") or query)[:300],
            "context": str(s.get("text") or ""), "subject_type": str(sem.get("subjectType") or ""),
            "subject": str(sem.get("subject") or ""), "event_window": str(sem.get("eventWindow") or ""),
            "scene_intent": si, "hook": start < float(config.HOOK_SECONDS),
            "recency": "month" if sem.get("eventWindow") == "year" and config.RECENT_FOOTAGE_FIRST else "",
            "visual_type": "footage", "seconds": round(seconds, 2), "start": round(start, 2)}


def taken_videos(doc: dict, skip=()) -> Tuple[set, gapfill.Used]:
    """
    ("yt:<id>" of every video the timeline shows and every asset id, the shots it shows) - never taken again.
    `skip`: scenes whose shot goes (a clip off the story): its video is never taken again either, but its
    shot no longer counts against the variety rules.
    """
    fps = recut._fps(doc)
    skip = set(skip or ())
    exclude: set = set()
    used = gapfill.Used()
    for k, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        shot = gapfill.Shot.of_scene(s, fps)
        if shot is not None and k not in skip:
            used.add(k, shot)
        sem = _sem(s)
        aid = str(sem.get("assetId") or "")
        if aid:
            exclude.add(aid)
        video = gapfill._video_of(aid, str(sem.get("sourceUrl") or ""))
        if video:
            exclude.add(video)
    return exclude, used


# --------------------------------------------------------------------------- #
# The budget
# --------------------------------------------------------------------------- #

class Budget:
    """
    The job's spend (src/costs.py: the worker's time since the job began and every model call, as the job's
    own result reports it) against a cap: a paid step starts only while what is spent, what the running steps
    may still spend (STEP_USD each) and the saving at the end (SAVE_USD) stay under it. cap 0 = no cap.
    """

    def __init__(self, cap: float, save: float = SAVE_USD):
        self.cap = max(0.0, float(cap or 0.0))
        self.save = max(0.0, float(save))           # what the saving at the end keeps back (a trial saves nothing)
        self.lock = threading.Lock()
        self.held = 0.0
        self.stopped = False
        self.refused = 0

    @staticmethod
    def spent() -> float:
        try:
            return float(costs.summary().get("total") or 0.0)
        except Exception:  # noqa: BLE001 - an unreadable ledger is an empty one
            return 0.0

    def take(self, step: str) -> float:
        """The step may start: what it holds back (give it back with done()); 0.0 = it may not."""
        hold = float(STEP_USD.get(step, 0.02))
        with self.lock:
            if self.cap <= 0:
                self.held += hold
                return hold
            if self.stopped or self.spent() + self.held + hold + self.save > self.cap:
                self.stopped = True
                self.refused += 1
                return 0.0
            self.held += hold
            return hold

    def done(self, hold: float) -> None:
        with self.lock:
            self.held = max(0.0, self.held - float(hold or 0.0))

    def report(self) -> dict:
        return {"capUsd": round(self.cap, 2), "spentUsd": round(self.spent(), 4), "stopped": self.stopped,
                "refusedSteps": self.refused}


# --------------------------------------------------------------------------- #
# The check of the clips nothing judged
# --------------------------------------------------------------------------- #

def _clear_no(verdict: Optional[dict]) -> bool:
    """A turned-down clip that must go even when nothing replaces it (not a near-miss)."""
    from . import hookcheck
    return bool(verdict) and not hookcheck.soft(verdict)


def check_clips(doc: dict, indices: List[int], work: str, *, budget: Budget, deadline: float,
                parallel: int = CHECK_PARALLEL, say: Optional[Callable] = None) -> Dict[int, dict]:
    """
    {index: {"keep", "score", "why", "clear", "verdict"}} for clips nothing judged: each read from its saved
    copy and judged against its own line (media.judge_clip: the slop filters, the local model, the judge and,
    in the opening, the opening check) - one model call each. A clip that cannot be read, or that no model
    answered for, is left out (it stays as it is).
    """
    from . import hookcheck
    out: Dict[int, dict] = {}
    lock = threading.Lock()
    scenes = doc.get("scenes") or []

    def one(i: int) -> None:
        if time.time() > deadline:
            return
        s = scenes[i]
        url = str((s.get("media") or {}).get("url") or "")
        if not url.startswith(("http://", "https://")):
            return
        hold = budget.take("check")
        if not hold:
            return
        path = os.path.join(work, f"check_{i}{os.path.splitext(url.split('?')[0])[1] or '.mp4'}")
        slop = ""
        try:
            storage.download(url, path, timeout=120, attempts=2, max_seconds=max(10.0, deadline - time.time()),
                             max_bytes=CHECK_MAX_MB * 1024 * 1024)
            job = job_for(doc, i)
            media._GATE_SLOP.set("")
            keep, verdict = media.judge_clip(path, job, _title(s), source_url=str(_sem(s).get("sourceUrl") or ""))
            slop = "" if keep else media._GATE_SLOP.get()
        except Exception as e:  # noqa: BLE001 - that clip stays as it is
            print(f"[reclip] check of scene {i + 1}: {type(e).__name__}: {str(e)[:100]}", flush=True)
            return
        finally:
            budget.done(hold)
            try:
                os.remove(path)
            except OSError:
                pass
        if verdict is None:
            if not slop:
                return                      # no model answered: it stays as it is
            # Turned down before any model looked: AI-made, a still, a studio, burned-in captions, a stock
            # agency's mark (src/slop.py, src/stockblock.py) - whatever the line, it goes.
            row = {"keep": False, "score": None, "verdict": None, "why": slop, "clear": True}
        else:
            row = {"keep": bool(keep), "score": _num(verdict.get("score")), "verdict": verdict,
                   "why": "" if keep else hookcheck.why(verdict), "clear": not keep and _clear_no(verdict)}
        with lock:
            out[i] = row
        print(f"[reclip] check scene {i + 1}: {'kept' if keep else 'TURNED DOWN'} "
              f"{row['score'] if row['score'] is not None else '-'} {_title(s)[:60]!r}"
              + ("" if keep else f" - {row['why']}"), flush=True)

    todo = [i for i in indices if 0 <= i < len(scenes)]
    if not todo:
        return out
    if say:
        say(f"Re-clipping: checking {len(todo)} clips and pictures nothing judged", 6)
    with ThreadPoolExecutor(max_workers=max(1, min(int(parallel), len(todo))), thread_name_prefix="recheck") as pool:
        futures = [pool.submit(contextvars.copy_context().run, one, i) for i in todo]
        for fut in futures:
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001 - that clip stays as it is
                print(f"[reclip] a check failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
    return out


def _record_check(s: dict, row: dict) -> None:
    """A kept clip's record gets the judge's verdict (as a plan records a judged clip)."""
    v = row.get("verdict") or {}
    sem = s.setdefault("semanticMetadata", {})
    if v.get("score") is not None:
        sem["relevanceScore"] = round(float(v["score"]), 3)
    if v.get("quality") is not None:
        sem["qualityScore"] = round(float(v["quality"]), 3)
    if v.get("description"):
        sem["contentDescription"] = str(v["description"])[:300]
    sem["judgedBy"] = "opening" if v.get("frames") else "frames"
    if v.get("frames"):
        from . import vision
        sem["cutCheck"] = vision.cut_record(v)


# --------------------------------------------------------------------------- #
# The estimate (and the free probe)
# --------------------------------------------------------------------------- #

def probe(doc: dict, targets: List[dict], seconds: float = 240.0, parallel: int = 3) -> dict:
    """
    How many usable YouTube candidates name what each target is about, from YouTube's own search (free: a flat
    search of the target's own wording and, when that names too little, of its first wider rung - no download,
    no model call): not a video the timeline shows, a usable title (never a music video in a story not about
    music), long enough for its scene, a title that names the line's subject (media._title_fits).
    {"asked", "answered", "own", "rung", "none", "withCandidates", "perTarget": {id: [own, rung]}}: "own" =
    targets whose own wording has one, "rung" = only a wider rung has one.
    """
    exclude, _used = taken_videos(doc)
    until = time.time() + max(10.0, float(seconds))
    out: Dict[str, Any] = {"asked": len(targets), "answered": 0, "own": 0, "rung": 0, "none": 0,
                           "withCandidates": 0, "perTarget": {}}
    lock = threading.Lock()

    def count(query: str, need: float, about: str, line: str = "") -> Optional[int]:
        try:
            rows = media._yt_candidates(f"ytsearch12:{query}", False, limit=12, timeout=45)
        except Exception:  # noqa: BLE001 - not answered
            return None
        return sum(1 for c in rows if f"yt:{c.get('id')}" not in exclude
                   and float(c.get("duration") or 0) >= need
                   and media._usable_title(str(c.get("title") or ""), str(c.get("channel") or ""),
                                           float(c.get("aspect") or 0), line)
                   and media._title_fits(str(c.get("title") or ""), about))

    def one(t: dict) -> None:
        if time.time() > until:
            return
        job = job_for(doc, t["index"])
        need = float(job["seconds"]) + 8.0
        about = job["subject"] or job["query"]
        line = f"{job['intent']} {job['context']}"
        own = count(job["query"], need, about, line)
        if own is None:
            return
        rung_n = 0
        if own < 1 and time.time() < until:
            rungs = media.clip_rungs(job["query"], job["subject"], job["scene_intent"], taken=[job["query"]],
                                     limit=1, person=job["subject_type"] == "person")
            if rungs:
                rung_n = count(rungs[0]["query"], need, rungs[0]["label"], line) or 0
        with lock:
            out["answered"] += 1
            key = "own" if own >= 1 else ("rung" if rung_n >= 1 else "none")
            out[key] += 1
            out["withCandidates"] += 1 if key != "none" else 0
            out["perTarget"][t["id"]] = [own, rung_n]

    with ThreadPoolExecutor(max_workers=max(1, int(parallel))) as pool:
        list(pool.map(one, targets))
    return out


def estimate(targets: List[dict], workers: int, probed: Optional[dict] = None, *, checks: int = 0,
             likely_bad: int = 0, budget: float = BUDGET_USD) -> dict:
    """
    What an apply would cost and take, and how many clips to expect (the constants at the top). `checks`: the
    clips nothing judged (one call each); `likely_bad`: how many of them the check will probably turn down
    (their title does not name their line) - each one more target. Over `budget`, "fits" says how many of
    the targets (in plan order) the budget covers.
    """
    n = len(targets) + int(likely_bad)
    fill = sum(1 for t in targets if t["kind"] in ("empty", "filler", "bad")) + int(likely_bad)
    hit = PROBE_HIT
    if probed and probed.get("answered"):
        # A title naming the line's subject on its own wording: the judge passes ~3 in 4 such lines; only on
        # a wider rung (judged as "shows the subject"): ~3 in 5; nothing named: ~1 in 6 (another rung, the
        # other clip sources, another moment of the video's clips).
        a = float(probed["answered"])
        hit = (0.75 * probed.get("own", 0) + 0.6 * probed.get("rung", 0) + 0.15 * probed.get("none", 0)) / a
    vision = n * VISION_PER_SEARCH + fill * VISION_PER_MOMENT + checks * VISION_PER_CHECK
    thread_minutes = n * SEARCH_MINUTES + fill * MOMENT_MINUTES + checks * CHECK_MINUTES
    clips = int(round(n * hit))
    with_cands = (float(probed.get("withCandidates", 0)) / max(1.0, float(probed["answered"])) * n
                  if probed and probed.get("answered") else float(n))
    low = int(round(with_cands * PASS_LOW))
    minutes = thread_minutes / max(1, workers) + clips * PUBLISH_SECONDS / 8.0 / 60.0 + 2.0
    usd = vision * VISION_USD + minutes * WORKER_USD_PER_MINUTE
    per_target = (usd - checks * (VISION_PER_CHECK * VISION_USD)) / max(1, n)
    fits = n if usd <= budget or budget <= 0 else max(0, int((budget - SAVE_USD - checks * VISION_PER_CHECK
                                                              * VISION_USD) / max(1e-6, per_target)))
    return {"targets": n, "byTier": {str(k): sum(1 for t in targets if t["tier"] == k) for k in (0, 1, 2)},
            "fillers": fill, "checks": int(checks), "likelyTurnedDown": int(likely_bad),
            "expectedClips": clips, "expectedClipsLow": min(low, clips), "hitRate": round(hit, 2),
            "visionCalls": int(round(vision)),
            "minutes": round(minutes, 1), "usd": round(usd, 2), "workers": workers,
            "budgetUsd": round(float(budget), 2), "overBudget": bool(budget > 0 and usd > budget),
            "fits": min(n, fits)}


# --------------------------------------------------------------------------- #
# Finding the clips
# --------------------------------------------------------------------------- #

class Finder:
    """A clip (or, for an empty line, another moment or a picture) for every target, in parallel, one time box."""

    def __init__(self, doc: dict, targets: List[dict], work: str, *, workers: int, deadline: float,
                 flags: Optional[dict] = None, say: Optional[Callable] = None, budget: Optional[Budget] = None,
                 library=None, skip=(), hopeless=()):
        self.doc = doc
        self.targets = targets
        self.work = work
        self.workers = max(1, int(workers))
        self.deadline = float(deadline)
        self.flags = {k: v for k, v in (flags or {}).items() if v is not None}
        self.say = say or (lambda *a, **k: None)
        self.budget = budget or Budget(0.0)
        self.library = library
        self.lock = threading.Lock()
        self.exclude, self.used = taken_videos(doc, skip=skip)
        bad = set(skip or ())
        self.donors = [d for d in gapfill.donors_from_doc(doc) if d.get("index") not in bad]
        self.found: Dict[int, Found] = {}
        self.late: set = set()
        self.unpaid: set = set()                    # targets a paid step was refused for (the budget)
        self.hopeless: set = set(hopeless or ())    # targets no YouTube title names (the free probe): no search
        self.traces: Dict[int, List[dict]] = {}     # each target's trace (media._TRACE): what was tried, why not
        self.box: Optional[ytdlp.Box] = None
        self.share = 0.0

    def _claim(self, asset, whole_video: bool = True) -> bool:
        """The found clip's video (or picture) for this target only: the next targets skip it. Another moment
        of a video the timeline shows (`whole_video` False) claims that moment only - its video is on the
        timeline already, and gapfill.Used has kept it to the variety rules."""
        keys = {asset.identity}
        if whole_video and asset.source == "youtube":
            vid, _s = media._yt_origin(asset)
            if vid:
                keys.add(f"yt:{vid}")
        with self.lock:
            if keys & self.exclude:
                return False
            self.exclude |= keys
            return True

    def _paid(self, step: str) -> float:
        hold = self.budget.take(step)
        return hold

    # -- a: its own runner-up --------------------------------------------------
    def runner_up(self, i: int, job: dict) -> Optional[Found]:
        """The scene's own runner-ups the judge approved when the plan found them: no model call."""
        fps = recut._fps(self.doc)
        s = self.doc["scenes"][i]
        line = _line(s)
        at = int(s.get("startFrame") or 0) / float(fps)
        frames = int(s.get("durationInFrames") or 0)
        for _n, alt in recut.runner_ups(s):
            if ytdlp.stopped():
                return None
            title = str(alt.get("title") or "")
            score = _num(alt.get("score"))
            if score is None or score < config.VISION_MIN_SCORE:
                continue
            if topics.scene_reason(f"{title} {alt.get('description') or ''}", line) \
                    or topics.off_topic_title(title, "", line=line):
                continue
            aid = str(alt.get("assetId") or "")
            names = {aid, gapfill._video_of(aid, str(alt.get("url") or alt.get("sourceUrl") or ""))} - {""}
            with self.lock:
                if names & self.exclude:
                    continue
            m = alt.get("media") if isinstance(alt.get("media"), dict) else {}
            if m.get("url"):
                med = shotcap._alt_media(alt)
                if med is None or med.get("type") != "video":
                    continue
                secs = shotcap._alt_seconds(alt, med)
                if secs * fps < frames - 1:
                    continue
                med["clipSeconds"] = round(secs, 2)
                shot = shotcap._alt_shot(alt, med, at)
                if not self.used.claim(i, shot):
                    continue
                with self.lock:
                    self.exclude |= names
                return Found(i, "runner-up", None, "its saved choice", media=med, sem=recut._alt_sem(alt))
            vid, start = recut._alt_youtube(alt)
            if not vid or start is None:
                continue
            need = float(job["seconds"]) + PAD
            if ledger.moment_used(vid, start, start + need):
                continue
            shot = gapfill.Shot(video=f"yt:{vid}", start=float(start), at=at)
            if not self.used.claim(i, shot):
                continue
            try:
                path, clean, cuts = media.fetch_clean_clip(vid, self.work, float(start), need, title)
            except Exception:  # noqa: BLE001 - the next runner-up
                path, clean, cuts = "", True, 0
            if not path:
                self.used.release(i, shot)
                continue
            asset = media.MediaAsset(
                kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                local_path=path, license=str(alt.get("license") or "unverified — you must hold the rights"),
                attribution=f"YouTube: {title}"[:200], query=job["query"],
                moment=dict(alt.get("moment") or {}, clean=clean, cuts=cuts), judged_by="frames")
            asset.relevance_score = score
            asset.quality = _num(alt.get("quality"))
            asset.content_description = str(alt.get("description") or "")
            if "@" in aid:
                asset.moment_key = aid
            if gapfill._too_short(asset, job) or not self._claim(asset):
                recut._remove(path)
                self.used.release(i, shot)
                continue
            return Found(i, "runner-up", asset, f"its runner-up (YouTube {vid} at {start:.0f} s)")
        return None

    # -- b: the clip library and the niche packs ---------------------------------
    def shelf(self, i: int, job: dict, stop: float) -> Optional[Found]:
        """A clip of the line's subject already on storage (the clip library, the niche packs), judged for this
        line as "shows that subject" - one model call."""
        from . import packs
        steps = []
        if self.library is not None and getattr(self.library, "entries", None):
            steps.append(("library", lambda: gapfill._from_library(job, self.used, self.library, self.work, stop)))
        try:
            pack_ok = packs.usable(job, media.youtube_only())
        except Exception:  # noqa: BLE001 - no shelf here
            pack_ok = False
        if pack_ok:
            steps.append(("pack", lambda: gapfill._from_pack(job, self.used, self.library, self.work, stop,
                                                              bool(self.flags.get("require_cc")))))
        for name, step in steps:
            if time.time() > stop or ytdlp.stopped():
                return None
            hold = self._paid("shelf")
            if not hold:
                self.unpaid.add(i)
                return None
            try:
                got = step()
                if got is None or got.kind != "video" or gapfill._too_short(got, job):
                    if got is not None:
                        recut._remove(got.local_path)
                    continue
                label = str(job.get("subject") or "")
                token = media._RUNG.set({"label": label}) if label else None
                try:
                    keep, verdict = media.judge_clip(got.local_path, job, got.attribution or "", source_url=got.url)
                finally:
                    if token is not None:
                        media._RUNG.reset(token)
            finally:
                self.budget.done(hold)
            media._trace(step=name, title=str(got.attribution or "")[:60], keep=bool(keep and verdict is not None),
                         score=(verdict or {}).get("score"), why=media._flags_of(verdict))
            if not keep or verdict is None:
                recut._remove(got.local_path)
                continue
            got.apply_verdict(verdict, str(job.get("intent") or ""))
            if not self._claim(got):
                recut._remove(got.local_path)
                continue
            return Found(i, name, got)
        return None

    def one(self, t: dict) -> Optional[Found]:
        i = t["index"]
        trace: List[dict] = []
        self.traces[i] = trace
        token = media._TRACE.set(trace)
        try:
            got = self._one(t)
        finally:
            media._TRACE.reset(token)
        if got is not None:
            trace.append({"step": "found", "how": got.how,
                          "score": getattr(got.asset, "relevance_score", None) if got.asset is not None
                          else (got.sem or {}).get("relevanceScore")})
        return got

    def _one(self, t: dict) -> Optional[Found]:
        i, kind = t["index"], t["kind"]
        job = job_for(self.doc, i)
        fill = kind in ("empty", "filler", "bad")
        own = (time.time() + self.share * (1.5 if job["hook"] else 1.0)) if self.share else 0.0
        token = ytdlp.STOP.set((self.box, min(own, self.deadline) if own else self.deadline))
        try:
            # a: its own runner-up (no model call)
            got = self.runner_up(i, job)
            if got is not None:
                return got
            stop = min(self.deadline, time.time() + float(config.FALLBACK_SCENE_SECONDS))
            tokens = gapfill._scene_context(job)
            try:
                # b: a clip of the line's subject already on storage, judged for this line
                got = self.shelf(i, job, stop)
                if got is not None:
                    return got
                # c: another moment of a clip the video shows (judged, the variety rules)
                if config.FALLBACK_MOMENTS and self.donors and job["subject_type"] != "document" \
                        and not ytdlp.stopped():
                    hold = self._paid("moment")
                    if hold:
                        try:
                            moment = gapfill._from_moment(job, self.used, self.work,
                                                          gapfill._share_of(stop, gapfill.MOMENT_SHARE), self.donors)
                        finally:
                            self.budget.done(hold)
                        media._trace(step="moment", found=moment is not None)
                        if moment is not None and self._claim(moment, whole_video=False):
                            return Found(i, "moment", moment)
                    else:
                        self.unpaid.add(i)
            finally:
                for var, tok in reversed(tokens):
                    var.reset(tok)
            # d: the clip-first search, while the budget lasts - not for a line YouTube's own (free) search
            # has no titled candidate for: such searches found nothing on the Obama re-clip but cost the most
            # (scouts on every wording and rung).
            if ytdlp.stopped():
                return None
            if i in self.hopeless:
                media._trace(step="search", why="skipped: no YouTube title names this line (the free probe)")
            else:
                got = self._search(t, job, fill)
                if got is not None:
                    return got
            if not fill or ytdlp.stopped() or not config.FALLBACK_STILLS:
                return None
            # e: an empty, text-filled or turned-down line: a picture
            stop = min(self.deadline, time.time() + float(config.FALLBACK_SCENE_SECONDS))
            tokens = gapfill._scene_context(job)
            try:
                hold = self._paid("picture")
                if not hold:
                    self.unpaid.add(i)
                    return None
                try:
                    pic = gapfill._from_still(job, self.used, self.work, stop, allow_generated=False)
                finally:
                    self.budget.done(hold)
                media._trace(step="picture", found=pic is not None)
                if pic is not None and self._claim(pic):
                    return Found(i, "picture", pic)
            finally:
                for var, tok in reversed(tokens):
                    var.reset(tok)
            return None
        finally:
            ytdlp.STOP.reset(token)

    def _search(self, t: dict, job: dict, fill: bool) -> Optional[Found]:
        """(d) The clip-first search, clips only, judged; a near-miss only for a line that has nothing."""
        i = t["index"]
        hold = self._paid("search")
        if not hold:
            self.unpaid.add(i)
            return None
        with self.lock:
            exclude = set(self.exclude)
        try:
            got = media.source_for_segment(
                job["query"], float(job["seconds"]), self.work, visual_type="footage", used=exclude,
                fallbacks=job["fallbacks"], intent=job["intent"], context=job["context"],
                subject_type=job["subject_type"], subject=job["subject"], event_window=job["event_window"],
                scene_intent=job["scene_intent"], hook=job["hook"], recency=job["recency"], start=job["start"],
                clips_only=True, **self.flags)
        except Exception as e:  # noqa: BLE001 - the next step
            print(f"[reclip] {t['id']}: clip search failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
            got = None
        finally:
            self.budget.done(hold)
        if got is not None and got.kind == "video" and not gapfill._too_short(got, job) \
                and (fill or not media._near_miss(got)) and self._claim(got):
            return Found(i, "clip", got)
        if got is not None:
            if not fill and media._near_miss(got):
                media._trace(step="search", why=f"a near-miss ({got.relevance_score}) never replaces a picture")
            recut._remove(got.local_path)
        return None

    def run(self) -> Dict[int, Found]:
        if not self.targets:
            return {}
        old = ytdlp.DEADLINE[0]
        ytdlp.set_deadline(self.deadline)
        self.box = ytdlp.Box(self.deadline)
        self.share = media.scene_seconds(self.deadline - time.time(), self.workers, len(self.targets))
        pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="reclip")
        futures = {pool.submit(contextvars.copy_context().run, self.one, t): t for t in self.targets}
        pending = set(futures)
        done_n = 0
        try:
            while pending:
                left = self.deadline - time.time()
                if left <= 0:
                    break
                finished, pending = wait(pending, timeout=min(left, 5), return_when=FIRST_COMPLETED)
                for fut in finished:
                    t = futures[fut]
                    done_n += 1
                    try:
                        got = fut.result()
                    except Exception as e:  # noqa: BLE001 - that target keeps what it had
                        print(f"[reclip] {t['id']}: {type(e).__name__}: {str(e)[:100]}", flush=True)
                        got = None
                    if got is not None:
                        self.found[got.index] = got
                if finished:
                    self.say(f"Re-clipping: {done_n}/{len(futures)} scenes searched, {len(self.found)} new shots",
                             8 + int(70 * done_n / max(1, len(futures))))
                # The last few still out once the rest are in get STRAGGLER_GRACE more - only when the
                # targets outnumber the threads (each then has a share of its own, recut.Finder's rule too).
                # With fewer targets than threads every one runs its whole ladder inside the box: the grace
                # used to start at once on a single target (or on the last of a few), cut its clip search
                # and its picture never got tried (the Obama re-clip, 2026-10-07: scene 1 stayed text twice).
                if self.share and pending and len(pending) <= max(1, len(futures) // 10):
                    self.deadline = min(self.deadline, time.time() + STRAGGLER_GRACE)
                    self.box.shorten(self.deadline)
                if self.budget.stopped and pending:
                    # Out of budget: what is running finishes its step, nothing new is paid for.
                    self.deadline = min(self.deadline, time.time() + STRAGGLER_GRACE)
                    self.box.shorten(self.deadline)
            self.late = {futures[f]["index"] for f in pending}
        finally:
            self.box.end()
            pool.shutdown(wait=False, cancel_futures=True)
            ytdlp.set_deadline(old)
        return self.found


# --------------------------------------------------------------------------- #
# Putting them on the timeline
# --------------------------------------------------------------------------- #

def put(scene: dict, f: Found, fps: int) -> None:
    """A found shot on its scene: its media and match record; the line's words, timing and entrance stay."""
    was = str((scene.get("media") or {}).get("source") or (scene.get("media") or {}).get("type") or "")
    sem = {k: v for k, v in copy.deepcopy(_sem(scene)).items() if k not in recut.SHOT_FIELDS
           and k not in ("borrowedFrom", "judgedBy", "cutCheck")}
    a = f.asset
    if a is None:
        # A published runner-up: its saved copy and the judge's record of it, as the plan kept them.
        m = dict(f.media or {})
        sem.update(f.sem or {})
        sem["judgedBy"] = "frames"
        kind = str(m.get("type") or "video")
        review, why = recut._licence_review(m.get("license"))
    else:
        m = a.to_scene_media()
        if a.kind == "video":
            secs = timeline._clip_seconds(a)
            if secs > 0:
                m["clipSeconds"] = round(secs, 2)
        if grade.is_local(m.get("url")):
            try:
                tone = grade.measure(m)
            except Exception:  # noqa: BLE001 - the render measures what has none
                tone = None
            if tone:
                m["tone"] = tone
        sem.update(recut._asset_sem(a))
        if getattr(a, "judged_by", ""):
            sem["judgedBy"] = a.judged_by
        if getattr(a, "cut_check", None):
            sem["cutCheck"] = dict(a.cut_check)
        kind = a.kind
        review, why = recut._licence_review(a.license)
        if f.how not in ("clip", "runner-up") or a.review_required:
            review, why = True, a.review_reason or why
    sem["reclip"] = {"how": f.how, "was": was}
    scene["media"] = m
    scene["semanticMetadata"] = sem
    scene.pop("animation", None)
    scene.pop("wantedPictures", None)
    if kind == "video":
        scene["visualType"] = "footage"
        scene["motion"] = "none"
    else:
        scene["visualType"] = "image"
        if (scene.get("motion") or "none") == "none" and str(getattr(config, "STILL_MOTION", "") or "") != "none":
            scene["motion"] = "zoom-in"
    scene["reviewRequired"], scene["reviewReason"] = bool(review), str(why or "")


def _clear(scene: dict) -> None:
    """A scene nothing was found for that must not stay as it was (a text card, a clip off the story or turned
    down), made empty for the no-text last resort."""
    scene["media"] = {"type": "color", "url": "", "source": "none"}
    scene.pop("animation", None)
    sem = scene.get("semanticMetadata")
    if isinstance(sem, dict):
        for k in ("assetId", "sourceUrl", "moment", "contentDescription", "relevanceScore", "judgedBy", "cutCheck"):
            sem.pop(k, None)
    if str(scene.get("visualType") or "") in ("animation", "image"):
        scene["visualType"] = "footage"


def _drop_cards(doc: dict, scenes: List[dict]) -> int:
    """The highlight text cards the last resort laid over these scenes' frames (gapfill._card)."""
    return gapfill.drop_cards(doc, scenes)


def counts_of(doc: dict, hook_seconds: Optional[float] = None) -> dict:
    """Clips / pictures / empty-or-text scenes, overall and in the first minute, by scene and by time."""
    fps = recut._fps(doc)
    hook = float(config.HOOK_SECONDS if hook_seconds is None else hook_seconds)
    out = {"scenes": 0, "clips": 0, "pictures": 0, "fillers": 0, "other": 0, "clipTimeShare": 0.0,
           "hookScenes": 0, "hookClips": 0}
    total = clip_frames = 0
    for s in doc.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        k = kind_of(s)
        out["scenes"] += 1
        d = int(s.get("durationInFrames") or 0)
        total += d
        key = {"video": "clips", "image": "pictures", "empty": "fillers", "filler": "fillers"}.get(k, "other")
        out[key] += 1
        if k == "video":
            clip_frames += d
        if int(s.get("startFrame") or 0) / float(fps) < hook:
            out["hookScenes"] += 1
            out["hookClips"] += 1 if k == "video" else 0
    out["clipTimeShare"] = round(clip_frames / float(total), 3) if total else 0.0
    return out


def scan(doc: dict, pictures: bool = True) -> dict:
    """
    What a dry run shows before anything is paid for: the scenes off the story (src/topics.py) and the clips
    and pictures nothing judged - how many, how many of them have a title that does not name their line, and
    how many of those are not targets already (a clip, a portrait: the check would add them).
    """
    off, unchecked, unnamed, new = [], [], 0, 0
    fps = recut._fps(doc)
    targets = {t["index"] for t in plan_targets(doc, pictures=pictures)}
    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        why = off_story(s)
        if why:
            off.append({"index": i, "id": str(s.get("id") or ""), "at": round(int(s.get("startFrame") or 0) / fps, 1),
                        "title": _title(s)[:90], "why": why})
        elif needs_check(s):
            unchecked.append(i)
            job = job_for(doc, i)
            if not media._title_fits(_title(s), job["subject"] or job["intent"]):
                unnamed += 1
                new += 0 if i in targets else 1
    return {"offStory": off, "unchecked": len(unchecked), "uncheckedIndices": unchecked,
            "uncheckedUnnamed": unnamed, "likelyNewTargets": new}


# --------------------------------------------------------------------------- #
# The action
# --------------------------------------------------------------------------- #

def _only(inp: dict, doc: dict) -> Optional[set]:
    """The scene indices "only" names (indices or scene ids), None when it names none."""
    raw = inp.get("only")
    if not raw:
        return None
    vals = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    ids = {str(s.get("id")): k for k, s in enumerate(doc.get("scenes") or []) if isinstance(s, dict)}
    out = set()
    for v in vals:
        v = str(v).strip()
        if v.isdigit():
            out.add(int(v))
        elif v in ids:
            out.add(ids[v])
    return out


def why_summary(traces: Dict[int, List[dict]]) -> dict:
    """What the traces say, counted: searches, scouts, downloads failed, filter reasons, the judge's verdicts."""
    out: Dict[str, Any] = {"searches": 0, "noUsableTitle": 0, "scouted": 0, "downloadsFailed": 0, "filtered": {},
                           "judged": 0, "passed": 0, "nearMisses": 0, "turnedDown": {}, "skippedNoCandidates": 0}
    for rows in traces.values():
        for r in rows:
            step = r.get("step")
            if step == "search":
                if str(r.get("why") or "").startswith("skipped"):
                    out["skippedNoCandidates"] += 1
                    continue
                if "candidates" in r:
                    out["searches"] += 1
                    out["noUsableTitle"] += 1 if not r.get("usable") else 0
            elif step == "scout":
                out["scouted"] += int(r.get("of") or 0)
            elif step == "download":
                out["downloadsFailed"] += 1
            elif step == "filter":
                why = str(r.get("why") or "")
                key = why.split(":")[0][:40] or "?"
                out["filtered"][key] = out["filtered"].get(key, 0) + 1
            elif step == "judge":
                out["judged"] += 1
                if r.get("keep"):
                    out["passed"] += 1
                else:
                    score = r.get("score")
                    if score is not None and float(score) >= config.VISION_SOFT_MIN_SCORE and not r.get("why"):
                        out["nearMisses"] += 1
                    key = str(r.get("why") or "")[:40] or (
                        f"scored {float(score):.1f}" if score is not None else "no verdict")
                    out["turnedDown"][key] = out["turnedDown"].get(key, 0) + 1
    out["turnedDown"] = dict(sorted(out["turnedDown"].items(), key=lambda kv: -kv[1])[:15])
    return out


def _with_config(overrides: dict, keep: dict):
    """Set config values (the job's own `keep` win); returns what to put back."""
    old = {}
    for k, v in overrides.items():
        if k in keep or not hasattr(config, k):
            continue
        old[k] = getattr(config, k)
        setattr(config, k, v)
    return old


def run(inp: dict, doc: dict, work: str, report: Optional[Callable] = None, *,
        publish: Optional[Callable[[dict], int]] = None, choices: Optional[Callable[[dict], int]] = None,
        ready: Optional[Callable[[], None]] = None, library=None) -> dict:
    """
    {"project_id", "apply", "expect_fingerprint" (needed to apply), "seconds" (time box, 60-7200), "limit"
    (targets at most), "only" (scene indices or ids: those scenes only), "pictures" (false: only the opening,
    the empty / text scenes and the shots that must go), "check" (false: the shots nothing judged are not
    checked), "budget_usd" (the cap, BUDGET_USD; 0 = none), "trial" (with apply false: the paid search on the
    targets - with "only", a few of them - under budget_usd (TRIAL_BUDGET_USD by default), nothing written
    anywhere: what each would get and why), "parallel", "probe" (a dry run asks YouTube's free search per
    target), "write_wait"}. Returns the plan, the counts before (and after) and an estimate; a trial or an
    apply also what was found, why the rest was not (trace, why), the budget; an apply also the backup and
    whether it was written.
    """
    started = time.time()
    say = report or (lambda *a, **k: None)
    apply = bool(inp.get("apply"))
    trial = bool(inp.get("trial")) and not apply
    project_id = str(inp.get("project_id") or "").strip()
    job_id = str(inp.get("_job_id") or "")
    seconds = min(7200.0, max(60.0, _num(inp.get("seconds")) or (TRIAL_SECONDS if trial else SECONDS)))
    workers = max(1, int(_num(inp.get("parallel")) or config.SOURCE_WORKERS))
    cap = _num(inp.get("budget_usd"))
    cap = (TRIAL_BUDGET_USD if trial else BUDGET_USD) if cap is None else max(0.0, cap)
    fps = recut._fps(doc)
    fp = recut.fingerprint(doc)
    expect = str(inp.get("expect_fingerprint") or "").strip().lower()
    if expect and expect != fp:
        raise ReclipError(f"the timeline read (fingerprint {fp[:12]}...) is not the one expected ({expect[:12]}...): "
                          "it changed since it was checked against the database - nothing was done")
    recut._check(doc)
    say("Re-clipping: reading the timeline", 2)
    # Lines planned without the model (the video's title as their subject and in their search) are planned
    # again first: every search below - and the editor's "find choices" once the timeline is saved - uses the
    # new words (src/replan.py; the California video, 2026-10-07: 113 of 167 lines).
    title = str(inp.get("title") or "")
    replanned = (replan.repair(doc, title=title, report=lambda m: say(m, 3))
                 if inp.get("replan") is not False else {})
    pictures = inp.get("pictures") is not False
    limit = int(_num(inp.get("limit")) or 0)
    only = _only(inp, doc)
    found_scan = scan(doc, pictures=pictures)
    if only is not None:
        found_scan["uncheckedIndices"] = [i for i in found_scan["uncheckedIndices"] if i in only]
        found_scan["unchecked"] = len(found_scan["uncheckedIndices"])

    def planned(checked=None) -> List[dict]:
        rows = plan_targets(doc, pictures=pictures, checked=checked)
        if only is not None:
            rows = [t for t in rows if t["index"] in only]
        return rows[:limit] if limit > 0 else rows

    targets = planned()
    before = counts_of(doc)
    checks = found_scan["unchecked"] if inp.get("check") is not False else 0
    probed = None
    if not apply and not trial and inp.get("probe"):
        say("Re-clipping: asking YouTube's search for each scene (free)", 5)
        probed = probe(doc, targets, seconds=min(600.0, max(30.0, _num(inp.get("probe_seconds")) or 240.0)))
    est = estimate(targets, workers, probed, checks=checks,
                   likely_bad=found_scan["likelyNewTargets"] if checks and only is None else 0, budget=cap)
    out: Dict[str, Any] = {"ok": True, "project_id": project_id, "dry_run": not apply, "trial": trial,
                           "fingerprint": fp, "fps": fps, "before": before, "estimate": est, "plan": targets[:ROWS],
                           "offStory": found_scan["offStory"][:ROWS], "unchecked": found_scan["unchecked"],
                           "replanned": {k: v for k, v in replanned.items() if k != "lines"},
                           "replannedLines": list(replanned.get("lines") or [])[:ROWS],
                           "realSubjects": replan.real_subjects(doc, title)}
    if probed is not None:
        out["probe"] = {k: v for k, v in probed.items() if k != "perTarget"}
    print(f"[reclip] {before['scenes']} scenes: {before['clips']} clips, {before['pictures']} pictures, "
          f"{before['fillers']} empty or text; first minute {before['hookClips']}/{before['hookScenes']} clips; "
          f"{len(found_scan['offStory'])} off the story, {found_scan['unchecked']} clips and pictures nothing judged "
          f"({found_scan['uncheckedUnnamed']} whose title does not name their line). Targets {len(targets)} "
          f"{est['byTier']}; expect ~{est['expectedClipsLow']}-{est['expectedClips']} clips, "
          f"~{est['visionCalls']} vision calls, ~{est['minutes']} min, ~${est['usd']} (cap ${cap:.2f})", flush=True)
    for row in found_scan["offStory"]:
        print(f"[reclip] OFF STORY scene {row['index'] + 1} at {row['at']} s: {row['why']} - {row['title']!r}",
              flush=True)
    if not apply and not trial:
        for row in targets[:ROWS]:
            n = (probed or {}).get("perTarget", {}).get(row["id"])
            print(f"[reclip] PLAN t{row['tier']} {row['id']:>8s} {row['start']:7.1f}s {row['kind']:6s} "
                  f"w{row['weakness']:.2f} {row['subject'][:40]!r}" + (f" candidates {n}" if n is not None else "")
                  + (f" ({row['why']})" if row.get("why") else ""), flush=True)
        events.emit("reclip", "dry_run", data={"targets": est["targets"], "expectedClips": est["expectedClips"],
                                               "offStory": len(found_scan["offStory"])})
        out["seconds"] = round(time.time() - started, 1)
        return out

    # ------------------------------------------------------------------ trial / apply
    if apply:
        if not expect:
            raise ReclipError("an apply needs expect_fingerprint (the read-only check query's answer)")
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", project_id):
            raise ReclipError("an apply needs the project_id")
        if not r2.enabled():
            raise ReclipError("Cloudflare R2 is not configured on this worker: there is nowhere to keep the backup "
                              "and the new shots")
        out.update(written=False, writeError="")
    if not targets and not checks and not (apply and replanned.get("replanned")):
        out["writeError"] = "nothing to re-clip"
        out["seconds"] = round(time.time() - started, 1)
        return out
    if ready is not None:
        ready()                         # no AI credit or no YouTube: refused before anything is written or paid
    if apply:
        say("Re-clipping: keeping the timeline as it was", 4)
        out["backup"] = recut.save_json(project_id, recut.backup_key(project_id, job_id), doc)
        print(f"[reclip] the timeline as it was: {out['backup']}", flush=True)
    deadline = started + seconds
    # (A trial saves nothing: no reserve for it. The Obama trials of 2026-10-07 lost three of their four
    # lines to reserves at a $0.10 cap: 4 searches x $0.02 + $0.05 for a save that never comes.)
    budget = Budget(cap, save=0.0 if trial else SAVE_USD)
    media.reset_cache()
    media.limit_generation(0)           # never an AI-made picture in a real video
    # A re-clip's searches are narrower than a plan's (RECLIP_CONFIG): the Obama re-clip asked every wording,
    # every rung and the other clip sources of 110 lines, ~5 minutes and ~8 model calls each, for 8 clips.
    restore_config = _with_config(RECLIP_CONFIG, inp.get("config") if isinstance(inp.get("config"), dict) else {})
    try:
        # The clips and pictures nothing judged: judged now (one call each), the turned-down ones become targets.
        checked: Dict[int, dict] = {}
        if checks:
            events.phase("reclip-check")
            checked = check_clips(doc, found_scan["uncheckedIndices"], work, budget=budget,
                                  deadline=min(deadline - 0.5 * seconds, time.time() + 0.2 * seconds), say=say)
            targets = planned(checked)
            out["plan"] = targets[:ROWS]
        out["checked"] = {"asked": checks, "answered": len(checked),
                          "kept": sum(1 for r in checked.values() if r["keep"]),
                          "turnedDown": sum(1 for r in checked.values() if not r["keep"])}
        # YouTube's own search, free (a flat search per line, no download, no model call): a line no title
        # names gets no paid search (its moment and picture steps still run), and the lines that have the
        # most candidates go first in their tier.
        hopeless: set = set()
        if targets and inp.get("free_probe") is not False:
            say("Re-clipping: asking YouTube's search for each scene (free)", 6)
            probed = probe(doc, targets, seconds=min(300.0, 20.0 + 3.0 * len(targets)), parallel=8)
            per = probed.get("perTarget") or {}
            hopeless = {t["index"] for t in targets if per.get(t["id"]) == [0, 0]}
            rank = {t["id"]: -(sum(per.get(t["id"]) or [0, 0])) for t in targets}
            targets = sorted(targets, key=lambda t: (t["tier"], t["index"] in hopeless, rank[t["id"]],
                                                     -t["weakness"] if t["tier"] == 2 else t["start"]))
            out["probe"] = {k: v for k, v in probed.items() if k != "perTarget"}
            out["noCandidates"] = len(hopeless)
        saving = 60.0 + len(targets) * PUBLISH_SECONDS / 8.0
        reserve = min(0.35 * seconds, saving + 120.0) if apply else 30.0
        gone = {t["index"] for t in targets if t["kind"] == "bad" and off_story(doc["scenes"][t["index"]])}
        finder = Finder(doc, targets, work, workers=workers, deadline=deadline - reserve,
                        flags={"allow_youtube": inp.get("allow_youtube"), "allow_stock": inp.get("allow_stock"),
                               "require_cc": inp.get("require_cc")}, say=say, budget=budget, library=library,
                        skip=gone, hopeless=hopeless)
        say("Re-clipping: finding clips", 8)
        events.phase("reclip-source")
        found = finder.run()
        events.phase("reclip")
    finally:
        for k, v in restore_config.items():
            setattr(config, k, v)
    out["stageSeconds"] = media.stage_seconds()
    ids = {t["index"]: t["id"] for t in targets}
    out["trace"] = {ids.get(i, str(i)): rows[:40] for i, rows in sorted(finder.traces.items())}
    out["why"] = why_summary(finder.traces)
    found_counts = {"clips": 0, "moments": 0, "pictures": 0, "runnerUps": 0, "library": 0}
    for f in found.values():
        key = {"clip": "clips", "moment": "moments", "picture": "pictures", "runner-up": "runnerUps"}.get(f.how, "library")
        found_counts[key] += 1
    out.update(found=found_counts, late=len(finder.late), budget=budget.report(), unpaid=len(finder.unpaid))
    print(f"[reclip] why: {json.dumps(out['why'])[:900]}", flush=True)
    if trial:
        # Nothing is written anywhere: what each target would get, and why the rest would not.
        out["foundShots"] = [{"index": i, "id": ids.get(i, ""), "how": f.how,
                              "score": getattr(f.asset, "relevance_score", None) if f.asset is not None
                              else (f.sem or {}).get("relevanceScore"),
                              "title": str(getattr(f.asset, "attribution", "") or (f.media or {}).get("attribution")
                                           or "")[:90],
                              "saw": str(getattr(f.asset, "content_description", "") or (f.sem or {})
                                         .get("contentDescription") or "")[:160],
                              "url": str(getattr(f.asset, "url", "") or (f.sem or {}).get("sourceUrl") or "")}
                             for i, f in sorted(found.items())]
        for f in found.values():
            if f.asset is not None:
                recut._remove(getattr(f.asset, "local_path", ""))
        out["seconds"] = round(time.time() - started, 1)
        events.emit("reclip", "trial", data={"found": found_counts, "budget": out["budget"]})
        return out

    new_doc = copy.deepcopy(doc)
    scenes = new_doc.get("scenes") or []
    # The clips the check kept: their records get the judge's verdict.
    recorded = 0
    for i, row in checked.items():
        if row.get("keep") and 0 <= i < len(scenes) and i not in found:
            _record_check(scenes[i], row)
            recorded += 1
    by_how: Dict[str, int] = {}
    changed: List[dict] = []                # the scenes that got a new shot
    for i, f in sorted(found.items()):
        if 0 <= i < len(scenes) and (f.asset is not None or f.media):
            put(scenes[i], f, fps)
            if f.asset is not None and f.asset.kind == "image":
                gapfill._living(new_doc, i, f.asset)
            by_how[f.how] = by_how.get(f.how, 0) + 1
            changed.append(scenes[i])
    if changed:
        _drop_cards(new_doc, changed)       # a text card laid over a line that now shows a shot
    # What nothing was found for. An empty or text-filled scene goes through the no-text last resort, and so
    # does a music / smoking shot the story is not about. A shot the check only turned down STAYS (marked for
    # review with the judge's reason): the Obama re-clip cleared 30 of them, and the last resort held their
    # neighbours over 23 lines and put 8 text cards where real shots had been (2026-10-07). A picture and a
    # data look of the line's figure stay as they were.
    rest = []
    kept_bad = 0
    for t in targets:
        i = t["index"]
        if i in found or not 0 <= i < len(scenes):
            continue
        s = scenes[i]
        if t["kind"] == "empty" or (t["kind"] == "filler" and not _data_look(s)):
            rest.append(s)
        elif t["kind"] == "bad" and off_story(s):
            rest.append(s)
        elif t["kind"] == "bad":
            row = checked.get(i) or {}
            if row.get("verdict"):
                _record_check(s, row)
            s["reviewRequired"] = True
            s["reviewReason"] = (f"The vision check turned this shot down ({row.get('why') or 'not for its line'}) "
                                 "and nothing better was found - replace it if you can")[:240]
            kept_bad += 1
    last: Dict[str, int] = {}
    if rest:
        _drop_cards(new_doc, rest)
        for s in rest:
            _clear(s)
        last = gapfill.hold_or_animate(new_doc, label="re-clip", laddered=True, search=True, work=work, fresh=True,
                                       only=rest)
    after = counts_of(new_doc)
    out.update(lastResort=last, after=after, recorded=recorded, keptTurnedDown=kept_bad)
    shown = any(int(v or 0) for k, v in last.items() if k not in ("card", "asked", "left", "seconds"))
    if not found and not rest and not recorded and not shown and not kept_bad:
        out["writeError"] = "no new shot was found: nothing changed"
        out["seconds"] = round(time.time() - started, 1)
        return out

    ledger.note({"fps": fps, "meta": new_doc.get("meta") or {},
                 "scenes": [s for s in changed if any(s is x for x in scenes)]})
    if publish is not None:
        meta = new_doc.setdefault("meta", {})
        warnings = list(meta.get("warnings") or [])
        published = int(_num(meta.get("publishedMedia")) or 0) + int(publish(new_doc) or 0)
        meta["warnings"], meta["publishedMedia"] = warnings, published
        # A file that could not be saved: its scene shows what it showed (its timing as it is now).
        restored = 0
        old_by_id = {str(s.get("id")): s for s in doc.get("scenes") or [] if isinstance(s, dict)}
        for s in scenes:
            m = s.get("media") if isinstance(s.get("media"), dict) else {}
            url = str(m.get("url") or "")
            if url and not url.startswith(("http://", "https://", "data:", "bgm://")):
                orig = old_by_id.get(str(s.get("id")))
                if orig is not None:
                    for k in ("media", "semanticMetadata", "visualType", "motion", "animation", "reviewRequired",
                              "reviewReason"):
                        if k in orig:
                            s[k] = copy.deepcopy(orig[k])
                        else:
                            s.pop(k, None)
                    restored += 1
        out["notSaved"] = restored
    if choices is not None and time.time() < deadline:
        try:
            choices(new_doc)
        except Exception as e:  # noqa: BLE001 - the choices are a nicety
            print(f"[reclip] runner-ups not saved: {type(e).__name__}: {str(e)[:100]}", flush=True)
    recut._strip_local_alternatives(new_doc)
    leftovers = recut._local_refs(new_doc)
    if leftovers:
        raise ReclipError(f"{len(leftovers)} link(s) would point at files on this worker ({leftovers[:3]}): "
                          "nothing was written to the project")
    for k in doc:
        if k in ("scenes", "meta", "overlays"):
            continue
        if json.dumps(doc[k], sort_keys=True, default=str) != json.dumps(new_doc.get(k), sort_keys=True, default=str):
            raise ReclipError(f"the timeline's {k} changed: nothing was written to the project")
    recut._update_meta(new_doc)
    recut._check(new_doc)
    out["after"] = counts_of(new_doc)
    new_doc["meta"]["reclip"] = {
        "job": job_id, "backup": out.get("backup", ""), "fingerprintBefore": fp, "targets": len(targets),
        "found": out["found"], "checked": out["checked"], "offStory": len(found_scan["offStory"]),
        "before": before, "after": out["after"], "budget": out["budget"], "why": out["why"],
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    out["fingerprintAfter"] = recut.fingerprint(new_doc)
    out["reclipKey"] = recut.save_json(project_id, recut.backup_key(project_id, job_id, "-reclip"), new_doc)
    say("Saving the re-clipped timeline", 95)
    wait_s = _num(inp.get("write_wait"))
    written, why = recut.write_project(project_id, new_doc, say, WRITE_WAIT if wait_s is None else max(0.0, wait_s),
                                       step="Clips added")
    out["written"], out["writeError"] = written, why
    if written:
        ledger.save(job_id, project_id)
    out["timeline"] = new_doc
    a = out["after"]
    events.emit("reclip", "summary", level="info" if written else "warning",
                data={"found": out["found"], "before": before, "after": a, "budget": out["budget"]},
                message=(f"{sum(out['found'].values())} new shot(s); clips {before['clips']} -> {a['clips']}, "
                         f"first minute {before['hookClips']} -> {a['hookClips']}; "
                         + ("saved" if written else f"NOT saved: {why}"))[:300])
    print(f"[reclip] {project_id}: clips {before['clips']} -> {a['clips']} of {a['scenes']}, pictures "
          f"{before['pictures']} -> {a['pictures']}, empty/text {before['fillers']} -> {a['fillers']}, first minute "
          f"{before['hookClips']}/{before['hookScenes']} -> {a['hookClips']}/{a['hookScenes']}; spent "
          f"${out['budget']['spentUsd']:.2f} of ${cap:.2f}; " + ("project saved" if written else f"project NOT saved: {why}"),
          flush=True)
    out["seconds"] = round(time.time() - started, 1)
    return out
