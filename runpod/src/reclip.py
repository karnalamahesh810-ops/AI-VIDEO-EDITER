"""
Re-clip a timeline that is already sourced: the first minute, every empty or
text-filled scene and the weakest pictures get real video clips, judged like
a plan judges them; the words, the timing, the graphics, the music and the
voice stay (the owner, 2026-10-06, on "Why Barack Obama's Brothers HATED Him
So Much", 70bc06d2: 29 clips in 192 scenes, the first minute almost without
one, 11 empty spots shown as text - "video clips are the main part of what we
make ... make it better and cleaner").

  plan    the scenes to re-clip, in order (plan_targets):
            0  every scene of the first HOOK_SECONDS that is not a clip (a
               document's scan excepted), and every empty or text-filled
               scene there - the opening first;
            1  every other empty or text-filled scene (a colour scene, or the
               last resort's "shown as text" / "motion graphic fills" look);
            2  the pictures, weakest first: an AI picture, a picture held
               over, borrowed or found in the last pass without a judge, then
               by the judge's score - never a document's scan, a named
               person's portrait or a map / chart line (they are the right
               still: media.clips_first_for's rule).
          A planner's own graphics (data looks, maps) and the clips stay.
  source  each target, on SOURCE_WORKERS threads under one time box: the
          clip-first search (media.source_for_segment clips_only: the scene's
          own wordings, then wider rungs naming its subject, the other clip
          sources) with the scene's query, fallbacks, intent, scene intent and
          subject, judged; never a video the timeline already shows, never a
          moment an earlier video showed (src/ledger.py). An empty or
          text-filled scene then tries another moment of a clip the video
          shows (gapfill._from_moment, judged) and a picture (gapfill's
          picture rung, with a push-in and depth layers).
  settle  a picture nothing better was found for stays as it was. An empty
          or text-filled scene nothing was found for goes through the no-text
          last resort (gapfill.hold_or_animate, NO_TEXT_FILL): a data look of
          its figure, the shot beside it held, another moment of any clip
          without a judge, a still beside it held - never a text card while
          anything real can stand in, never a scene left empty.
  save    (apply, with expect_fingerprint) as recut saves: the timeline as it
          was to R2 first (projects/<project>/backups/scene_data-<job>.json),
          the new files as a plan publishes them, the new timeline beside the
          backup (-reclip), then the project row once (recut.write_project:
          the broker writes only while the project is "rendering" under this
          job - the runner prints the hand over).

A dry run (the default) reads the timeline and returns the plan with an
estimate - nothing is written and nothing paid for. With "probe": true it
also asks YouTube's search (free: one flat search per target, no download,
no model call) how many usable candidates each target has, so the estimate
says how many clips to expect.
"""
from __future__ import annotations

import contextvars
import copy
import datetime
import json
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, events, gapfill, grade, ledger, media, r2, recut, timeline, ytdlp

SECONDS = 2400.0           # the time box (s)
WRITE_WAIT = recut.WRITE_WAIT
STRAGGLER_GRACE = 120.0    # a target still running this long past its share, once the rest are in, is let go
PAD = media.SEQ_SHOT_PAD
ROWS = 600                 # plan / result rows kept in a job result

# The estimate, from the owner's own jobs. The 5-minute A/B build of 2026-10-05 (ab_A): 471 vision calls for
# 60 scenes on google/gemini-2.5-flash for $0.298 (OpenRouter) - ~7.8 calls and $0.0049 a scene; a clip
# search holds one thread ~1.6 min (2-4 YouTube sections through the proxies at ~12-16 s, the scouts and the
# judge), another moment ~0.7 min; the 16-core serverless worker costs $0.576 an hour; a new file is saved
# in ~4 s (8 at a time). PROBE_HIT: the share of targets a clip-first search fills when the probe has not
# been asked (the owner's pod builds kept a judged clip for ~45-60% of the footage lines whose first
# wording was searched; the clip-first search asks 3 wordings and 3 wider rungs).
VISION_PER_SEARCH = 7.8
VISION_PER_MOMENT = 2.0
VISION_USD = 0.00065
SEARCH_MINUTES = 1.6
MOMENT_MINUTES = 0.7
PUBLISH_SECONDS = 4.0
WORKER_USD_PER_MINUTE = 0.576 / 60.0
PROBE_HIT = 0.65

# The last resort's own looks on a line nothing was found for (gapfill._card, quality.text_scene,
# gapfill.hold_or_animate's graphic, hookcheck.clear): a text card is not a shot.
_FILLER_REASONS = ("No usable clip found", "Nothing usable was found", "No footage found",
                   "The start of the video: its clip was turned down")
# Reasons that say a picture is a stand-in, weakest first in the plan.
_WEAK_REASONS = ("Held over", "Picture found in the last pass", "Best available", "Found in the last pass",
                 "Nothing was found", "A picture found when", "Not checked by the vision AI")


class ReclipError(RuntimeError):
    """The action cannot go on; nothing was written."""


@dataclass
class Found:
    index: int
    how: str = ""                       # "clip" | "moment" | "picture"
    asset: Any = None
    note: str = ""


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


def plan_targets(doc: dict, *, pictures: bool = True, limit: Optional[int] = None,
                 hook_seconds: Optional[float] = None) -> List[dict]:
    """The scenes to re-clip, in the order they are worked: [{"index", "id", "tier", "kind", ...}] (module doc)."""
    fps = recut._fps(doc)
    hook = float(config.HOOK_SECONDS if hook_seconds is None else hook_seconds)
    rows = []
    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        k = kind_of(s)
        if k not in ("empty", "filler", "image"):
            continue
        sem = _sem(s)
        start = int(s.get("startFrame") or 0) / float(fps)
        in_hook = start < hook
        if k == "image":
            if in_hook and str(sem.get("subjectType") or "") != "document":
                tier = 0
            elif not pictures or _still_kind(s):
                continue
            else:
                tier = 2
        else:
            tier = 0 if in_hook else 1
        rows.append({"index": i, "id": str(s.get("id") or f"#{i}"), "tier": tier, "kind": k,
                     "start": round(start, 2), "seconds": round(int(s.get("durationInFrames") or 0) / float(fps), 2),
                     "weakness": weakness(s) if k == "image" else 1.0,
                     "subject": str(sem.get("subject") or "")[:80], "subjectType": str(sem.get("subjectType") or ""),
                     "query": " ".join(str(s.get("query") or sem.get("searchQuery") or "").split())[:120],
                     "was": str((s.get("media") or {}).get("source") or k)})
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


def taken_videos(doc: dict) -> Tuple[set, gapfill.Used]:
    """("yt:<id>" of every video the timeline shows and every asset id, the shots it shows) - never taken again."""
    fps = recut._fps(doc)
    exclude: set = set()
    used = gapfill.Used()
    for k, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        shot = gapfill.Shot.of_scene(s, fps)
        if shot is not None:
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
# The estimate (and the free probe)
# --------------------------------------------------------------------------- #

def probe(doc: dict, targets: List[dict], seconds: float = 240.0, parallel: int = 3) -> dict:
    """
    How many usable YouTube candidates name what each target is about, from YouTube's own search (free: a flat
    search of the target's own wording and, when that names too little, of its first wider rung - no download,
    no model call): not a video the timeline shows, a usable title, long enough for its scene, a title that
    names the line's subject (media._title_fits). {"asked", "answered", "own", "rung", "none",
    "withCandidates", "perTarget": {id: [own, rung]}}: "own" = targets whose own wording has one, "rung" = only
    a wider rung has one.
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
                                     limit=1)
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


def estimate(targets: List[dict], workers: int, probed: Optional[dict] = None) -> dict:
    """What an apply would cost and take, and how many clips to expect (the constants at the top)."""
    n = len(targets)
    fill = sum(1 for t in targets if t["kind"] in ("empty", "filler"))
    hit = PROBE_HIT
    if probed and probed.get("answered"):
        # A title naming the line's subject on its own wording: the judge passes ~3 in 4 such lines; only on
        # a wider rung (judged as "shows the subject"): ~3 in 5; nothing named: ~1 in 6 (another rung, the
        # other clip sources, another moment of the video's clips).
        a = float(probed["answered"])
        hit = (0.75 * probed.get("own", 0) + 0.6 * probed.get("rung", 0) + 0.15 * probed.get("none", 0)) / a
    vision = n * VISION_PER_SEARCH + fill * VISION_PER_MOMENT
    thread_minutes = n * SEARCH_MINUTES + fill * MOMENT_MINUTES
    clips = int(round(n * hit))
    minutes = thread_minutes / max(1, workers) + clips * PUBLISH_SECONDS / 8.0 / 60.0 + 2.0
    usd = vision * VISION_USD + minutes * WORKER_USD_PER_MINUTE
    return {"targets": n, "byTier": {str(k): sum(1 for t in targets if t["tier"] == k) for k in (0, 1, 2)},
            "fillers": fill, "expectedClips": clips, "hitRate": round(hit, 2), "visionCalls": int(round(vision)),
            "minutes": round(minutes, 1), "usd": round(usd, 2), "workers": workers}


# --------------------------------------------------------------------------- #
# Finding the clips
# --------------------------------------------------------------------------- #

class Finder:
    """A clip (or, for an empty line, another moment or a picture) for every target, in parallel, one time box."""

    def __init__(self, doc: dict, targets: List[dict], work: str, *, workers: int, deadline: float,
                 flags: Optional[dict] = None, say: Optional[Callable] = None):
        self.doc = doc
        self.targets = targets
        self.work = work
        self.workers = max(1, int(workers))
        self.deadline = float(deadline)
        self.flags = {k: v for k, v in (flags or {}).items() if v is not None}
        self.say = say or (lambda *a, **k: None)
        self.lock = threading.Lock()
        self.exclude, self.used = taken_videos(doc)
        self.donors = gapfill.donors_from_doc(doc)
        self.found: Dict[int, Found] = {}
        self.late: set = set()
        self.box: Optional[ytdlp.Box] = None
        self.share = 0.0

    def _claim(self, asset) -> bool:
        """The found clip's video (or picture) for this target only: the next targets skip it."""
        keys = {asset.identity}
        if asset.source == "youtube":
            vid, _s = media._yt_origin(asset)
            if vid:
                keys.add(f"yt:{vid}")
        with self.lock:
            if keys & self.exclude:
                return False
            self.exclude |= keys
            return True

    def one(self, t: dict) -> Optional[Found]:
        i = t["index"]
        job = job_for(self.doc, i)
        own = (time.time() + self.share * (1.5 if job["hook"] else 1.0)) if self.share else 0.0
        token = ytdlp.STOP.set((self.box, min(own, self.deadline) if own else self.deadline))
        try:
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
            if got is not None and got.kind == "video" and not gapfill._too_short(got, job) and self._claim(got):
                return Found(i, "clip", got)
            if got is not None:
                recut._remove(got.local_path)
            if t["kind"] not in ("empty", "filler") or ytdlp.stopped():
                return None
            stop = min(self.deadline, time.time() + float(config.FALLBACK_SCENE_SECONDS))
            tokens = gapfill._scene_context(job)
            try:
                moment = gapfill._from_moment(job, self.used, self.work, stop, self.donors)
                if moment is not None and self._claim(moment):
                    return Found(i, "moment", moment)
                if config.FALLBACK_STILLS and time.time() < stop:
                    pic = gapfill._from_still(job, self.used, self.work, stop, allow_generated=False)
                    if pic is not None and self._claim(pic):
                        return Found(i, "picture", pic)
            finally:
                for var, tok in reversed(tokens):
                    var.reset(tok)
            return None
        finally:
            ytdlp.STOP.reset(token)

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
                if pending and len(pending) <= max(1, len(futures) // 10):
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
    a = f.asset
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
    sem = {k: v for k, v in copy.deepcopy(_sem(scene)).items() if k not in recut.SHOT_FIELDS
           and k not in ("borrowedFrom", "judgedBy", "cutCheck")}
    sem.update(recut._asset_sem(a))
    if getattr(a, "judged_by", ""):
        sem["judgedBy"] = a.judged_by
    if getattr(a, "cut_check", None):
        sem["cutCheck"] = dict(a.cut_check)
    sem["reclip"] = {"how": f.how, "was": str((scene.get("media") or {}).get("source")
                                              or (scene.get("media") or {}).get("type") or "")}
    scene["media"] = m
    scene["semanticMetadata"] = sem
    scene.pop("animation", None)
    scene.pop("wantedPictures", None)
    if a.kind == "video":
        scene["visualType"] = "footage"
        scene["motion"] = "none"
    else:
        scene["visualType"] = "image"
        if (scene.get("motion") or "none") == "none" and str(getattr(config, "STILL_MOTION", "") or "") != "none":
            scene["motion"] = "zoom-in"
    review, why = recut._licence_review(a.license)
    if f.how != "clip" or a.review_required:
        review, why = True, a.review_reason or why
    scene["reviewRequired"], scene["reviewReason"] = bool(review), str(why or "")


def _clear(scene: dict) -> None:
    """A text-filled scene nothing was found for, made empty for the no-text last resort."""
    scene["media"] = {"type": "color", "url": "", "source": "none"}
    scene.pop("animation", None)
    if str(scene.get("visualType") or "") == "animation":
        scene["visualType"] = "footage"


def _drop_cards(doc: dict, scenes: List[dict]) -> int:
    """The highlight text cards the last resort laid over these scenes' frames (gapfill._card)."""
    spans = {(int(s.get("startFrame") or 0), int(s.get("durationInFrames") or 0)) for s in scenes}
    overlays = doc.get("overlays")
    if not isinstance(overlays, list):
        return 0
    before = len(overlays)
    overlays[:] = [ov for ov in overlays if not (isinstance(ov, dict) and ov.get("type") == "highlight" and
                                                 (int(ov.get("startFrame") or -1),
                                                  int(ov.get("durationInFrames") or -1)) in spans)]
    return before - len(overlays)


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


# --------------------------------------------------------------------------- #
# The action
# --------------------------------------------------------------------------- #

def run(inp: dict, doc: dict, work: str, report: Optional[Callable] = None, *,
        publish: Optional[Callable[[dict], int]] = None, choices: Optional[Callable[[dict], int]] = None,
        ready: Optional[Callable[[], None]] = None) -> dict:
    """
    {"project_id", "apply", "expect_fingerprint" (needed to apply), "seconds" (time box, 60-7200), "limit"
    (targets at most), "pictures" (false: only the opening and the empty / text scenes), "parallel",
    "probe" (a dry run asks YouTube's free search per target), "write_wait"}. Returns the plan, the counts
    before (and after) and an estimate; an apply also what was found, the backup and whether it was written.
    """
    started = time.time()
    say = report or (lambda *a, **k: None)
    apply = bool(inp.get("apply"))
    project_id = str(inp.get("project_id") or "").strip()
    job_id = str(inp.get("_job_id") or "")
    seconds = min(7200.0, max(60.0, _num(inp.get("seconds")) or SECONDS))
    workers = max(1, int(_num(inp.get("parallel")) or config.SOURCE_WORKERS))
    fps = recut._fps(doc)
    fp = recut.fingerprint(doc)
    expect = str(inp.get("expect_fingerprint") or "").strip().lower()
    if expect and expect != fp:
        raise ReclipError(f"the timeline read (fingerprint {fp[:12]}...) is not the one expected ({expect[:12]}...): "
                          "it changed since it was checked against the database - nothing was done")
    recut._check(doc)
    say("Re-clipping: reading the timeline", 2)
    targets = plan_targets(doc, pictures=inp.get("pictures") is not False, limit=int(_num(inp.get("limit")) or 0))
    before = counts_of(doc)
    probed = None
    if not apply and inp.get("probe"):
        say("Re-clipping: asking YouTube's search for each scene (free)", 5)
        probed = probe(doc, targets, seconds=min(600.0, max(30.0, _num(inp.get("probe_seconds")) or 240.0)))
    est = estimate(targets, workers, probed)
    out: Dict[str, Any] = {"ok": True, "project_id": project_id, "dry_run": not apply, "fingerprint": fp, "fps": fps,
                           "before": before, "estimate": est, "plan": targets[:ROWS]}
    if probed is not None:
        out["probe"] = {k: v for k, v in probed.items() if k != "perTarget"}
    print(f"[reclip] {before['scenes']} scenes: {before['clips']} clips, {before['pictures']} pictures, "
          f"{before['fillers']} empty or text; first minute {before['hookClips']}/{before['hookScenes']} clips. "
          f"Targets {est['targets']} {est['byTier']}; expect ~{est['expectedClips']} clips, "
          f"~{est['visionCalls']} vision calls, ~{est['minutes']} min, ~${est['usd']}", flush=True)
    if not apply:
        for row in targets[:ROWS]:
            n = (probed or {}).get("perTarget", {}).get(row["id"])
            print(f"[reclip] PLAN t{row['tier']} {row['id']:>8s} {row['start']:7.1f}s {row['kind']:6s} "
                  f"w{row['weakness']:.2f} {row['subject'][:40]!r}" + (f" candidates {n}" if n is not None else ""),
                  flush=True)
        events.emit("reclip", "dry_run", data={"targets": est["targets"], "expectedClips": est["expectedClips"]})
        out["seconds"] = round(time.time() - started, 1)
        return out

    # ------------------------------------------------------------------ apply
    if not expect:
        raise ReclipError("an apply needs expect_fingerprint (the read-only check query's answer)")
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", project_id):
        raise ReclipError("an apply needs the project_id")
    if not r2.enabled():
        raise ReclipError("Cloudflare R2 is not configured on this worker: there is nowhere to keep the backup "
                          "and the new shots")
    out.update(written=False, writeError="")
    if not targets:
        out["writeError"] = "nothing to re-clip"
        out["seconds"] = round(time.time() - started, 1)
        return out
    if ready is not None:
        ready()                         # no AI credit or no YouTube: refused before anything is written
    say("Re-clipping: keeping the timeline as it was", 4)
    out["backup"] = recut.save_json(project_id, recut.backup_key(project_id, job_id), doc)
    print(f"[reclip] the timeline as it was: {out['backup']}", flush=True)
    deadline = started + seconds
    saving = 60.0 + len(targets) * PUBLISH_SECONDS / 8.0
    reserve = min(0.35 * seconds, saving + 120.0)
    media.reset_cache()
    media.limit_generation(0)           # never an AI-made picture in a real video
    finder = Finder(doc, targets, work, workers=workers, deadline=deadline - reserve,
                    flags={"allow_youtube": inp.get("allow_youtube"), "allow_stock": inp.get("allow_stock"),
                           "require_cc": inp.get("require_cc")}, say=say)
    say("Re-clipping: finding clips", 8)
    events.phase("reclip-source")
    found = finder.run()
    events.phase("reclip")
    out["stageSeconds"] = media.stage_seconds()

    new_doc = copy.deepcopy(doc)
    scenes = new_doc.get("scenes") or []
    by_how: Dict[str, int] = {}
    changed: List[dict] = []                # the scenes that got a new shot (a hold below may shift indices)
    for i, f in sorted(found.items()):
        if 0 <= i < len(scenes) and f.asset is not None:
            put(scenes[i], f, fps)
            if f.asset.kind == "image":
                gapfill._living(new_doc, i, f.asset)
            by_how[f.how] = by_how.get(f.how, 0) + 1
            changed.append(scenes[i])
    # The empty and text-filled lines nothing was found for: the no-text last resort, never a text card
    # while anything real can stand in.
    rest = [scenes[t["index"]] for t in targets
            if t["kind"] in ("empty", "filler") and t["index"] not in found and 0 <= t["index"] < len(scenes)]
    last: Dict[str, int] = {}
    if rest:
        _drop_cards(new_doc, rest)
        for s in rest:
            _clear(s)
        last = gapfill.hold_or_animate(new_doc, label="re-clip", laddered=True, search=True, work=work, fresh=True,
                                       only=rest)
    after = counts_of(new_doc)
    out.update(found={"clips": by_how.get("clip", 0), "moments": by_how.get("moment", 0),
                      "pictures": by_how.get("picture", 0)}, lastResort=last, after=after,
               late=len(finder.late))
    if not found and not any(last.get(k) for k in ("graphic", "held", "moment")):
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
        # A file that could not be saved: its scene goes back to what it showed.
        restored = 0
        old_by_id = {str(s.get("id")): s for s in doc.get("scenes") or [] if isinstance(s, dict)}
        for k, s in enumerate(scenes):
            m = s.get("media") if isinstance(s.get("media"), dict) else {}
            url = str(m.get("url") or "")
            if url and not url.startswith(("http://", "https://", "data:", "bgm://")):
                orig = old_by_id.get(str(s.get("id")))
                if orig is not None:
                    scenes[k] = copy.deepcopy(orig)
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
        "found": out["found"], "before": before, "after": out["after"],
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
                data={"found": out["found"], "before": before, "after": a},
                message=(f"{sum(out['found'].values())} new shot(s); clips {before['clips']} -> {a['clips']}, "
                         f"first minute {before['hookClips']} -> {a['hookClips']}; "
                         + ("saved" if written else f"NOT saved: {why}"))[:300])
    print(f"[reclip] {project_id}: clips {before['clips']} -> {a['clips']} of {a['scenes']}, pictures "
          f"{before['pictures']} -> {a['pictures']}, empty/text {before['fillers']} -> {a['fillers']}, first minute "
          f"{before['hookClips']}/{before['hookScenes']} -> {a['hookClips']}/{a['hookScenes']}; "
          + ("project saved" if written else f"project NOT saved: {why}"), flush=True)
    out["seconds"] = round(time.time() - started, 1)
    return out
