"""
Split one video's sourcing across several RunPod workers.

A 30-minute narration is ~400 scenes; one worker searches, downloads and
vision-checks them with 16 threads, and every minute of that is one machine's
network and one queue of model calls. The endpoint has ten workers, so a long
video is cut into parts along story-section boundaries, each part is sourced
on its own worker (search, vision review and on-the-spot replacement all run
there), and the parent merges the results.

Protocol (same endpoint, action "source_part"):
  parent -> child input: parent_job_id, project_id, bucket, brief, jobs (with
      their global scene indices), sequences (global beat indices), exclude
      (clip identities other parts already hold - empty at the start), and
      the sourcing flags (allow_youtube, allow_stock, require_cc).
  child -> parent output: {"assets": {"<global index>": MediaAsset fields +
      "remote_url", "storage_path"}}. Files are uploaded through the app's
      storage broker under the PARENT's job id, which is what the broker
      authorises for the project.

Anything a part does not return - a failed child, a timeout, a submission
error - is sourced by the parent itself, so fanning out can only add speed,
never lose scenes. Clips two parts both picked are resolved by the parent.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
from dataclasses import asdict, fields
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from . import ytdlp
from . import config, media, storage, costs, events, r2
from . import brandkit
from . import render as renderer


def readiness(n_scenes: int, project_id: Optional[str] = None) -> dict:
    """Safe fan-out diagnostics: report missing prerequisites, never secret values."""
    missing = []
    if config.FANOUT_PARTS < 2:
        missing.append("worker_slots_must_be_at_least_2")
    if n_scenes < config.FANOUT_MIN_SCENES:
        missing.append("scene_count_below_fanout_minimum")
    if not config.FANOUT_API_KEY:
        missing.append("RunPod API key missing (FANOUT_API_KEY or RUNPOD_API_KEY)")
    if not config.FANOUT_ENDPOINT_ID:
        missing.append("endpoint id missing (FANOUT_ENDPOINT_ID or RUNPOD_ENDPOINT_ID)")
    if project_id is not None and not project_id:
        missing.append("project id required")
    if not storage.parallel_storage_enabled():
        missing.append("Supabase worker-storage or service credentials unavailable")
    return {"enabled": not missing,
            "workerSlots": config.FANOUT_PARTS,
            "remoteWorkers": max(0, config.FANOUT_PARTS - 1),
            "missing": missing}


def enabled_for(n_scenes: int, project_id: str) -> bool:
    return readiness(n_scenes, project_id)["enabled"]


def split(jobs: List[dict], sequences: List[dict], parts: int) -> List[Dict[str, Any]]:
    """
    Contiguous parts of about equal size, never cutting a sequence in two.

    Returns [{"jobs": [...], "sequences": [...]}] with global indices kept.
    """
    ordered = sorted(jobs, key=lambda j: j["index"])
    n = len(ordered)
    if n == 0:
        return []
    size = max(1, math.ceil(n / parts))
    # A boundary inside a sequence moves to that sequence's end.
    seq_end = {}
    for seq in sequences or []:
        beats = sorted(seq.get("beats") or [])
        for b in beats:
            seq_end[b] = beats[-1]
    bounds, k = [], 0
    while k < n:
        end = min(n, k + size)
        if end < n:
            last = ordered[end - 1]["index"]
            stretch = seq_end.get(last, last)
            while end < n and ordered[end]["index"] <= stretch:
                end += 1
        bounds.append((k, end))
        k = end
    out = []
    for lo, hi in bounds:
        part_jobs = ordered[lo:hi]
        idx = {j["index"] for j in part_jobs}
        part_seqs = [s for s in (sequences or [])
                     if (s.get("beats") or [None])[0] in idx]
        out.append({"jobs": part_jobs, "sequences": part_seqs})
    return out


def _asset_from(d: dict, local_path: str) -> media.MediaAsset:
    names = {f.name for f in fields(media.MediaAsset)}
    kw = {k: v for k, v in d.items() if k in names}
    kw["local_path"] = local_path
    return media.MediaAsset(**kw)


def _submit(payload: dict) -> Optional[str]:
    try:
        r = requests.post(
            f"https://api.runpod.ai/v2/{config.FANOUT_ENDPOINT_ID}/run",
            headers={"Authorization": f"Bearer {config.FANOUT_API_KEY}"},
            json={"input": payload}, timeout=30)
        return (r.json() or {}).get("id")
    except (requests.RequestException, ValueError):
        return None


def _status(job_id: str) -> dict:
    try:
        return requests.get(
            f"https://api.runpod.ai/v2/{config.FANOUT_ENDPOINT_ID}/status/{job_id}",
            headers={"Authorization": f"Bearer {config.FANOUT_API_KEY}"},
            timeout=30).json() or {}
    except (requests.RequestException, ValueError):
        return {}


def _cancel(job_id: str) -> None:
    try:
        requests.post(f"https://api.runpod.ai/v2/{config.FANOUT_ENDPOINT_ID}/cancel/{job_id}",
                      headers={"Authorization": f"Bearer {config.FANOUT_API_KEY}"}, timeout=15)
    except requests.RequestException:
        pass


class _Units:
    """
    Run units of work across the endpoint's workers, one of them here.

    The parent takes the first unit itself instead of waiting idle, takes back
    any unit no machine has started once it is free (RunPod wakes stopped
    workers slowly), and hands every failed, lost or timed-out unit back to
    the caller. `payload(unit)` is the remote job's input; `local(unit)` does
    the unit here and returns its result; `accept(unit, result, remote)`
    stores a result and says whether it was usable; `progress(unit, output)`
    reads a running child's progress in the unit's own weight.
    """

    def __init__(self, units: List[dict], *, payload: Callable, local: Callable,
                 accept: Callable, progress: Callable, report: Callable, deadline: float):
        self.units, self.payload, self.local = units, payload, local
        self.accept, self.progress, self.report = accept, progress, report
        self.deadline = deadline
        self.failed: List[dict] = []
        self.stolen = 0
        self.live = 0
        self._here: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def _start_here(self, unit: dict) -> None:
        run = {"unit": unit, "done": threading.Event(), "result": None, "error": None, "taken": False}

        def go():
            try:
                with self._lock:          # media/render state: one local unit at a time
                    run["result"] = self.local(unit)
            except Exception as e:  # noqa: BLE001 - handed back as failed
                run["error"] = e
                print(f"[fanout] local unit failed: {e}", flush=True)
            finally:
                run["done"].set()
        self._here.append(run)
        threading.Thread(target=go, daemon=True).start()

    def _free(self) -> bool:
        return all(r["done"].is_set() for r in self._here)

    def _collect_here(self) -> float:
        done = 0.0
        for r in self._here:
            if r["done"].is_set():
                if not r["taken"]:
                    r["taken"] = True
                    ok = r["error"] is None and self.accept(r["unit"], r["result"], False)
                    if not ok:
                        self.failed.append(r["unit"])
                done += r["unit"].get("weight", 1)
        return done

    def run(self, label: str) -> List[dict]:
        if not self.units:
            return []
        self._start_here(self.units[0])
        pending: Dict[str, dict] = {}
        remote_units = self.units[1:]
        if remote_units:
            # Submit all parts concurrently; serial API calls can otherwise
            # leave most of the endpoint idle while the parent waits on HTTP.
            with ThreadPoolExecutor(max_workers=min(config.FANOUT_PARTS - 1,
                                                     len(remote_units))) as pool:
                futures = {pool.submit(_submit, self.payload(unit)): unit
                           for unit in remote_units}
                for future in as_completed(futures):
                    unit = futures[future]
                    try:
                        jid = future.result()
                    except Exception:
                        jid = None
                    if jid:
                        pending[jid] = unit
                    else:
                        self.failed.append(unit)
        self.live = len(pending)
        total = sum(u.get("weight", 1) for u in self.units)
        print(f"[fanout] {label}: {len(pending)} unit(s) on other workers + 1 here", flush=True)
        seen_progress: Dict[str, float] = {}
        seen_states: Dict[str, str] = {}
        poll_delay = 1.0
        status_pool = ThreadPoolExecutor(max_workers=max(1, min(config.FANOUT_PARTS - 1,
                                                                  len(pending))))
        while (pending or not self._free()) and time.time() < self.deadline:
            time.sleep(poll_delay)
            here = self._collect_here()
            changed = False
            snapshots = list(pending.items())
            futures = {status_pool.submit(_status, jid): (jid, unit)
                       for jid, unit in snapshots}
            for future in as_completed(futures):
                jid, unit = futures[future]
                if jid not in pending:
                    continue
                try:
                    st = future.result() or {}
                except Exception:
                    st = {}
                state = st.get("status")
                if state and seen_states.get(jid) != state:
                    changed = True
                    seen_states[jid] = state
                if state == "IN_QUEUE" and self._free():
                    _cancel(jid)
                    del pending[jid]
                    self._start_here(unit)
                    self.stolen += 1
                    print(f"[fanout] {label}: unit {jid[:8]} never started; doing it here", flush=True)
                    continue
                if state == "IN_PROGRESS" and isinstance(st.get("output"), dict):
                    progress = self.progress(unit, st["output"])
                    if seen_progress.get(jid) != progress:
                        changed = True
                    seen_progress[jid] = progress
                if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
                    del pending[jid]
                    out = st.get("output")
                    if state == "COMPLETED" and isinstance(out, dict):
                        # The child's cost units and stage timings join this job's.
                        costs.absorb(out.get("costs"))
                        events.absorb(out.get("events"))
                    if state != "COMPLETED" or not isinstance(out, dict) or not self.accept(unit, out, True):
                        why = out.get("error") if isinstance(out, dict) else (out or st.get("error"))
                        print(f"[fanout] {label}: unit {jid[:8]} {state}: {str(why)[:160]}", flush=True)
                        self.failed.append(unit)
                    seen_progress[jid] = unit.get("weight", 1)
                    changed = True
            busy = len(pending) + (0 if self._free() else 1)
            self.report(min(total, sum(seen_progress.values()) + here), total, busy)
            poll_delay = 1.0 if changed else min(4.0, poll_delay * 1.6)
        status_pool.shutdown(wait=False, cancel_futures=True)
        for r in self._here:                  # past the deadline: finish our own work
            r["done"].wait()
        self._collect_here()
        for jid, unit in pending.items():     # timed out: take it back
            _cancel(jid)
            self.failed.append(unit)
        return self.failed


def _dedupe(results: List[Optional[media.MediaAsset]], jobs: List[dict],
            seen: Dict[str, int]) -> List[dict]:
    """Drop clips an earlier scene already uses; return the jobs to redo."""
    by_index = {j["index"]: j for j in jobs}
    redo = []
    for i, a in enumerate(results):
        if a is None or i not in by_index:
            continue
        if a.identity in seen and seen[a.identity] != i:
            results[i] = None
            redo.append(by_index[i])
        else:
            seen[a.identity] = i
    return redo


def _refetch_one(i: int, d: dict, work: str) -> Optional[media.MediaAsset]:
    """A lost part clip fetched again from where it came from: the same YouTube
    moment, or the picture's own URL. None when that is not possible."""
    asset = _asset_from(d, "")
    path = ""
    try:
        if asset.source == "youtube" and asset.kind == "video":
            vid, start = media._yt_origin(asset)
            if not vid:
                return None
            seconds = max(2.5, min(15.0, float(asset.duration or 0) or 6.0))
            path, _clean, _cuts = media.fetch_clean_clip(vid, work, start, seconds, (asset.attribution or "")[:60])
        elif asset.kind == "image" and str(asset.url or "").startswith("http"):
            ext = os.path.splitext(urllib.parse.urlparse(asset.url).path)[1].lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
            path = storage.download(asset.url, os.path.join(work, f"refetch_{i:04d}{ext}"))
        else:
            return None
    except Exception as e:  # noqa: BLE001 - the scene stays empty for the rescue pass
        print(f"[fanout] scene {i + 1}: refetch failed ({str(e)[:100]})", flush=True)
        return None
    if not path or not os.path.isfile(path):
        return None
    asset.local_path = path
    return asset


def refetch_lost(lost: List[tuple], results: List[Optional[media.MediaAsset]], work: str) -> int:
    """
    Fetch again, in parallel, the clips parts chose but could not hand over:
    [(scene index, the part's asset record)]. Fills `results` in place and
    returns how many came back. The choice and its vision verdict were made
    on the part; only the download is left, so it gets its own short time
    box (REFETCH_SECONDS) even past the sourcing deadline.
    """
    todo = [(i, d) for i, d in lost if 0 <= i < len(results) and results[i] is None]
    if not todo:
        return 0
    old = ytdlp.DEADLINE[0]
    ytdlp.set_deadline(max(old, time.time() + config.REFETCH_SECONDS))
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(config.REFETCH_PARALLEL, len(todo)))) as ex:
            got = list(ex.map(lambda it: _refetch_one(it[0], it[1], work), todo))
    finally:
        ytdlp.set_deadline(old)
    n = 0
    for (i, _d), a in zip(todo, got):
        if a is not None and results[i] is None:
            results[i] = a
            n += 1
    print(f"[fanout] fetched {n}/{len(todo)} lost part clip(s) again from their source", flush=True)
    return n


def source(jobs: List[dict], sequences: List[dict], brief: dict, *, parent_job_id: str,
           project_id: str, bucket: str, work: str, flags: dict,
           report: Callable, local: Callable[[List[dict], set], List[Optional[media.MediaAsset]]],
           exclude: Optional[set] = None) -> List[Optional[media.MediaAsset]]:
    """
    Sourced assets for every job (list aligned to job["index"]).

    Round 1 splits the video across the workers. Round 2 sends every scene
    round 1 left empty or doubled (two parts picking the same popular video)
    back out across the workers too, each part told which clips are already
    in use - a 22-minute video left 64 of 211 scenes for the parent to fill
    alone. Whatever is still missing after that is sourced here.
    `local(jobs, exclude)` sources jobs on this worker.
    """
    n = max(j["index"] for j in jobs) + 1
    results: List[Optional[media.MediaAsset]] = [None] * n
    total_scenes = len(jobs)
    stats: Dict[str, int] = {"parts": 0, "stolen_back": 0, "failed_parts": 0, "rounds": 0, "refetched": 0,
                             "refetch_asked": 0}
    # Clips a part chose but could not hand over (the app's storage down):
    # (scene index, the part's asset record), fetched again from their source.
    lost: List[tuple] = []

    def fetch(unit: dict, out: Any, remote: bool) -> bool:
        if not remote:
            for j, a in zip(sorted(unit["jobs"], key=lambda j: j["index"]), out or []):
                results[j["index"]] = a
            return True
        assets = out.get("assets")
        if not isinstance(assets, dict):
            return False
        for key, d in assets.items():
            i = int(key)
            if d.get("refetch") or not d.get("remote_url"):
                lost.append((i, d))
                continue
            ext = os.path.splitext((d.get("storage_path") or "x.bin"))[1] or ".bin"
            path = os.path.join(work, f"part_{i:04d}{ext}")
            try:
                storage.download(d.get("remote_url") or "", path)
                results[i] = _asset_from(d, path)
            except Exception as e:  # noqa: BLE001 - fetched again from its source below
                print(f"[fanout] scene {i + 1}: download failed ({e})", flush=True)
                lost.append((i, d))
        return True

    def recover() -> None:
        if not lost:
            return
        stats["refetch_asked"] += len(lost)
        got = refetch_lost(list(lost), results, work)
        stats["refetched"] += got
        lost.clear()

    # IMAGE_MAX_PER_VIDEO is per VIDEO: each first-round part gets its share,
    # gap-filling parts none (they exist to find footage), and the parent
    # keeps the rest for the last scenes it fills itself.
    def run_round(round_jobs: List[dict], seqs: List[dict], exclude: set, lo: int, hi: int,
                  label: str, first: bool = False) -> None:
        parts = split(round_jobs, seqs, config.FANOUT_PARTS)
        for k, p in enumerate(parts):
            p["weight"] = len(p["jobs"])
            p["image_budget"] = (config.IMAGE_MAX_PER_VIDEO * len(p["jobs"]) // max(1, total_scenes)
                                 if first and k else 0)
        if first:
            media.limit_generation(config.IMAGE_MAX_PER_VIDEO
                                   - sum(p["image_budget"] for p in parts))
        base = len(jobs) - len(round_jobs)

        def show(done, total, busy):
            report(f"{label} {base + int(done)}/{total_scenes} scenes on {busy} workers",
                   lo + int((hi - lo) * done / max(1, total)), done=base + int(done), total=total_scenes)
        units = _Units(
            parts,
            payload=lambda p: {"action": "source_part", "parent_job_id": parent_job_id,
                               "project_id": project_id, "bucket": bucket, "brief": brief,
                               "jobs": p["jobs"], "sequences": p["sequences"],
                               "exclude": sorted(exclude),
                               "image_budget": p["image_budget"],
                               "deadline_at": ytdlp.DEADLINE[0], **flags},
            local=lambda p: local(p["jobs"], set(exclude)),
            accept=fetch,
            progress=lambda p, o: min(p["weight"], float(o.get("done") or 0)),
            report=show,
            deadline=_round_deadline(len(round_jobs)))
        failed = units.run(label)
        recover()
        stats["parts"] += len(parts)
        stats["stolen_back"] += units.stolen
        stats["failed_parts"] += len(failed)
        stats["rounds"] += 1

    report(f"Sourcing in parallel: 0/{total_scenes} scenes", 30, done=0, total=total_scenes)
    if not ytdlp.DEADLINE[0]:
        ytdlp.set_deadline(time.time() + source_budget(total_scenes))
    # `exclude`: clips already on the timeline (subject pools, reused scenes).
    taken = set(exclude or ())
    run_round(jobs, sequences, set(taken), 30, 55, "Sourced", first=True)

    seen: Dict[str, int] = {ident: -1 for ident in taken}
    dups = _dedupe(results, jobs, seen)
    empty = [j for j in jobs if results[j["index"]] is None and j not in dups]
    todo = empty + dups
    stats["cross_part_repeats"] = len(dups)
    if ytdlp.past_deadline():
        print(f"[fanout] sourcing time spent; {len(todo)} scene(s) left for animation", flush=True)
        todo = []
    if len(todo) >= config.FANOUT_REFILL_MIN:
        print(f"[fanout] round 2 across workers: {len(todo)} scene(s) "
              f"({len(empty)} empty, {len(dups)} repeats)", flush=True)
        run_round(todo, [], set(seen), 55, 60, "Filling gaps:")
        stats["round2_repeats"] = len(_dedupe(results, jobs, seen))
        todo = [j for j in jobs if results[j["index"]] is None]
    if todo and ytdlp.past_deadline():
        todo = []
    if todo:
        print(f"[fanout] sourcing {len(todo)} last scene(s) here", flush=True)
        report(f"Filling the last {len(todo)} scenes", 60)
        got = local(todo, set(seen))
        for j, a in zip(sorted(todo, key=lambda j: j["index"]), got):
            results[j["index"]] = a
    stats["sourced_by_parent_last"] = len(todo)
    media.LAST_STATS["fanout"] = stats
    return results


def source_budget(n_scenes: int) -> float:
    """
    Seconds all footage finding may take for a video of n scenes: base + per
    scene, under a cap that grows with the video (SOURCE_BUDGET_MAX_SECONDS,
    or SOURCE_BUDGET_MAX_PER_SCENE a scene when that is more) and never past
    SOURCE_BUDGET_CEILING_SECONDS. A flat cap gave the owner's 159-scene
    Lake Powell video the same 40 minutes as a 100-scene one.
    """
    n = max(0, n_scenes)
    cap = max(config.SOURCE_BUDGET_MAX_SECONDS, config.SOURCE_BUDGET_MAX_PER_SCENE * n)
    if config.SOURCE_BUDGET_CEILING_SECONDS > 0:
        cap = min(cap, max(config.SOURCE_BUDGET_MAX_SECONDS, config.SOURCE_BUDGET_CEILING_SECONDS))
    return min(cap, config.SOURCE_BUDGET_BASE_SECONDS + config.SOURCE_BUDGET_PER_SCENE * n)


def _round_deadline(n_jobs: int) -> float:
    """A round's parts are collected until the job's sourcing deadline (plus the
    time a part needs to upload what it found), never longer than the old cap."""
    cap = time.time() + max(config.FANOUT_TIMEOUT_SECONDS, 6.0 * n_jobs)
    if ytdlp.DEADLINE[0]:
        return min(cap, ytdlp.DEADLINE[0] + 45.0)
    return cap


def render_enabled(doc: dict, project_id: str) -> bool:
    """The render is split across machines: a pod's spread render (render_pod,
    POD_RENDER_FANOUT) or the serverless chunk render (FANOUT_RENDER). Either
    way the scene media must be published first, so other machines can read it."""
    if pod_render_enabled(doc):
        return True
    seconds = doc.get("durationInFrames", 0) / max(1, doc.get("fps", 30))
    return bool(config.FANOUT_RENDER and seconds >= config.FANOUT_RENDER_MIN_SECONDS
                and readiness(config.FANOUT_MIN_SCENES, project_id)["enabled"])


def chunks(total_frames: int, fps: int, parts: int) -> List[tuple]:
    """Frame ranges (inclusive), filling every available worker slot."""
    if total_frames <= 0:
        return []
    # Keep even short renders distributed: the former 90-second chunk target
    # sent every short video through one worker, leaving the other nine idle.
    # A range always contains at least one frame, so a clip shorter than the
    # pool naturally uses only its available frame count.
    want = max(1, min(max(1, parts), total_frames))
    size = math.ceil(total_frames / want)
    return [(a, min(total_frames, a + size) - 1) for a in range(0, total_frames, size)]


# Frames a scene plays on under the next scene's "crossfade" (Main.tsx
# CROSSFADE_FRAMES, timeline.CROSSFADE_FRAMES).
CROSSFADE_FRAMES = 15


def _media_ref(m: dict) -> str:
    """What identifies a scene's media across renders: its storage path, not its signed URL."""
    st = m.get("storage") or {}
    if st.get("path"):
        return f"{st.get('bucket', '')}/{st['path']}"
    return str(m.get("url") or "").split("?", 1)[0]


def _renderer_id() -> str:
    """What draws the frames (render.renderer_fingerprint), '' when it cannot be read."""
    try:
        return renderer.renderer_fingerprint()
    except OSError:
        return ""


def chunk_hash(doc: dict, a: int, b: int) -> str:
    """
    A fingerprint of everything that draws frames a..b: the scenes and
    overlays that overlap the range (media by storage path, so a re-signed
    URL does not count as a change), the caption settings and the frame size.
    A scene counts over the frames it really draws: it plays on under the
    next scene's crossfade, and the next scene's cut transition draws its
    out half over this scene's last frames. The video's grade (doc.grade,
    with its frozen median tone) and each scene's measured tone count, and so
    does the renderer itself (render.renderer_fingerprint): a chunk drawn by
    older renderer code (before the grade, say) must not be joined to new ones.
    Two renders whose chunk hashes match can share the chunk file.
    `a`..`b` are frames of the whole video: a brand intro plays before the
    narration's timeline (brandkit.layout), so scenes and overlays are
    matched `intro` frames later, and the brand block itself is in the hash.
    """
    intro, body, _outro, _total = brandkit.layout(doc)
    a, b = a - intro, b - intro

    def overlaps(item: dict, extra: int = 0) -> bool:
        s0 = int(item.get("startFrame") or 0)
        s1 = s0 + int(item.get("durationInFrames") or 0) - 1 + extra
        return s0 <= b and s1 >= a

    scene_list = doc.get("scenes") or []
    scenes = []
    for i, sc in enumerate(scene_list):
        nxt = (scene_list[i + 1] if i + 1 < len(scene_list) else None) or {}
        if not overlaps(sc, CROSSFADE_FRAMES if nxt.get("transition") == "crossfade" else 0):
            continue
        m = sc.get("media") or {}
        scenes.append({k: sc.get(k) for k in ("id", "startFrame", "durationInFrames", "text",
                                                "motion", "transition", "effect", "treatment", "frame")}
                      | {"nextTransition": nxt.get("transition"),
                         "media": [m.get("type"), _media_ref(m), m.get("sourceStart"), m.get("sourceEnd"),
                                   m.get("tone")],
                         "words": [(w.get("text"), w.get("start"), w.get("end")) for w in sc.get("words") or []]})
    overlays = [o for o in doc.get("overlays") or [] if overlaps(o)]
    payload = {"fps": doc.get("fps"), "width": doc.get("width"), "height": doc.get("height"),
               "captions": doc.get("captions"), "brand": doc.get("brand"), "overlaysEnabled": doc.get("overlaysEnabled"),
               "scenes": scenes, "overlays": overlays, "grade": doc.get("grade"), "renderer": _renderer_id()}
    if intro or _outro:
        # Where the range sits against the intro, the narration and the outro.
        payload["layout"] = [intro, body, _outro, a, b]
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _reuse_chunks(units: List[dict], hashes: List[str], previous: Optional[dict], bucket: str,
                  project_id: str, parent_job_id: str, fps: int, total_frames: int) -> List[dict]:
    """Download unchanged chunks from the previous render; returns the units reused."""
    if not previous or not storage.broker_enabled():
        return []
    if int(previous.get("fps") or 0) != fps or int(previous.get("durationInFrames") or 0) != total_frames:
        return []
    old = {tuple(c.get("frames") or ()): c for c in previous.get("chunks") or []}
    reused = []
    for u, h in zip(units, hashes):
        c = old.get(tuple(u["frames"]))
        st = (c or {}).get("storage") or {}
        if not c or c.get("hash") != h or not st.get("path"):
            continue
        try:
            url = storage.broker_read_url(st.get("bucket") or bucket, st["path"], project_id, parent_job_id)
            storage.download(url, u["path"])
        except Exception as e:  # noqa: BLE001 - render it instead
            print(f"[fanout] chunk {u['i']}: previous copy unavailable ({type(e).__name__})", flush=True)
            continue
        if os.path.isfile(u["path"]) and os.path.getsize(u["path"]) > 0:
            u["storage"] = dict(st)
            reused.append(u)
    return reused


def render(doc: dict, out_path: str, *, parent_job_id: str, project_id: str, bucket: str,
           work: str, report: Callable, render_local: Callable,
           previous: Optional[dict] = None) -> str:
    """
    Render `doc` to `out_path` in frame chunks across the workers.

    Each chunk renders silent; the narration, music and sound effects are
    rendered once here as one audio track, then the chunks are joined without
    re-encoding and the audio laid under them - no seams in the sound.
    `render_local(frames, path, muted, codec)` renders here (frames None =
    the whole timeline).

    `previous` is the manifest of the last render of this project (fps,
    durationInFrames, chunks with frame ranges, hashes and storage paths).
    A chunk whose hash is unchanged is downloaded instead of rendered, so a
    Replace Clip re-renders only the chunk it touched. The new manifest is
    left in media.LAST_STATS["render_manifest"].
    """
    fps = int(doc.get("fps") or 30)
    # Every frame of the video: the brand intro and outro around the narration.
    total_frames = brandkit.total_frames(doc)
    ranges = chunks(total_frames, fps, config.FANOUT_PARTS)
    units = [{"i": i, "frames": fr, "weight": fr[1] - fr[0] + 1,
              "path": os.path.join(work, f"chunk_{i:03d}.mp4")} for i, fr in enumerate(ranges)]
    hashes = [chunk_hash(doc, a, b) for a, b in ranges]
    all_units = list(units)
    reused = _reuse_chunks(units, hashes, previous, bucket, project_id, parent_job_id, fps, total_frames)
    if reused:
        print(f"[fanout] reusing {len(reused)} of {len(units)} chunks from the previous render", flush=True)
        units = [u for u in units if u not in reused]

    def accept(unit: dict, out: Any, remote: bool) -> bool:
        if remote:
            try:
                storage.download(out.get("url") or "", unit["path"])
            except Exception as e:  # noqa: BLE001 - rendered here instead
                print(f"[fanout] chunk {unit['i']}: download failed ({e})", flush=True)
                return False
        return os.path.isfile(unit["path"]) and os.path.getsize(unit["path"]) > 0

    def show(done, total, busy):
        frac = done / max(1, total)
        report(f"Rendering video {int(frac * 100)}% on {busy} workers", 70 + int(20 * frac))

    deadline = time.time() + config.FANOUT_TIMEOUT_SECONDS + 3 * total_frames / fps
    runner = _Units(
        units,
        payload=lambda u: {"action": "render_chunk", "parent_job_id": parent_job_id,
                           "project_id": project_id, "bucket": bucket, "timeline": doc,
                           "frames": list(u["frames"]), "chunk": u["i"],
                           "deadline_at": deadline},
        local=lambda u: render_local(u["frames"], u["path"], True, None),
        accept=accept,
        progress=lambda u, o: u["weight"] * float(o.get("frac") or 0),
        report=show,
        deadline=deadline)
    failed = runner.run("render") if units else []
    for unit in failed:                         # anything lost is rendered here
        print(f"[fanout] rendering chunk {unit['i']} here", flush=True)
        render_local(unit["frames"], unit["path"], True, None)
    # Chunks rendered on this worker are kept too, so the next render of this
    # project can reuse every chunk it did not change.
    manifest_chunks = []
    for u, h in zip(all_units, hashes):
        entry = {"i": u["i"], "frames": list(u["frames"]), "hash": h}
        if not u.get("storage") and storage.broker_enabled() and project_id and parent_job_id:
            obj = f"projects/{project_id}/parts/{parent_job_id}/render_{u['i']:03d}.mp4"
            try:
                storage.broker_upload(u["path"], bucket, obj, project_id, parent_job_id, read_ttl=60)
                u["storage"] = {"bucket": bucket, "path": obj}
            except Exception as e:  # noqa: BLE001 - only the reuse is lost
                print(f"[fanout] chunk {u['i']}: not kept ({type(e).__name__})", flush=True)
        if u.get("storage"):
            entry["storage"] = u["storage"]
        manifest_chunks.append(entry)
    media.LAST_STATS["render_manifest"] = {"fps": fps, "durationInFrames": total_frames,
                                           "parts": len(all_units), "chunks": manifest_chunks,
                                           "reused": len(reused)}
    units = all_units
    # The whole sound as lossless WAV, encoded once when it is joined to the
    # picture (render.finalize: loudness set, starts on frame 0 - an ADTS AAC
    # track copied into the MP4 played 42.7 ms late).
    audio = os.path.join(work, "track.wav")
    try:
        render_local(None, audio, False, "wav")
    except Exception as e:  # noqa: BLE001 - a silent video is still caught below
        print(f"[fanout] audio track failed: {e}", flush=True)
    listing = os.path.join(work, "chunks.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{os.path.basename(u['path'])}'\n" for u in units)
    video = os.path.join(work, "video_only.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing,
                    "-c", "copy", video], cwd=work, check=True)
    if not (os.path.isfile(audio) and os.path.getsize(audio) > 0):
        raise RuntimeError("the narration track did not render")
    renderer.finalize(video, audio, out_path)
    media.LAST_STATS["render_fanout"] = {"chunks": len(units), "on_workers": runner.live,
                                         "stolen_back": runner.stolen, "rendered_here_after": len(failed),
                                         "reused": len(reused)}
    return out_path


def run_chunk(inp: dict, work: str, render_local: Callable) -> dict:
    """The child side of render(): render one silent chunk, upload it."""
    a, b = inp["frames"]
    i = int(inp.get("chunk", 0))
    path = os.path.join(work, f"chunk_{i:03d}.mp4")
    render_local((a, b), path, True, None)
    obj = f"projects/{inp['project_id']}/parts/{inp['parent_job_id']}/render_{i:03d}.mp4"
    # A rendered chunk is minutes of work; a broker hiccup must not throw it
    # away. On 2026-10-04 the worker-storage function stalled (60 s read
    # timeouts) and four children failed on their first upload attempt, so
    # the parent re-rendered every one of their chunks alone, one by one.
    # Retry until the parent stops waiting (or CHUNK_UPLOAD_GRACE_SECONDS).
    until = time.time() + config.CHUNK_UPLOAD_GRACE_SECONDS
    if inp.get("deadline_at"):
        until = max(time.time() + 60.0, float(inp["deadline_at"]) - 15.0)
    url = storage.broker_upload(path, inp.get("bucket") or config.MEDIA_BUCKET, obj,
                                inp["project_id"], inp["parent_job_id"], read_ttl=60 * 60 * 6,
                                deadline=until)
    return {"url": url, "path": obj, "frames": [a, b]}


def run_part(inp: dict, work: str, source_many: Callable, set_story: Callable) -> dict:
    """The child side: source one part, upload its files, return them."""
    brief = inp.get("brief") or {}
    set_story(brief)
    if inp.get("deadline_at"):
        ytdlp.set_deadline(float(inp["deadline_at"]) - 20.0)
    jobs = inp.get("jobs") or []
    local_of = {j["index"]: k for k, j in enumerate(sorted(jobs, key=lambda j: j["index"]))}
    local_jobs = [dict(j, index=local_of[j["index"]]) for j in jobs]
    seqs = []
    for s in inp.get("sequences") or []:
        beats = [local_of[b] for b in (s.get("beats") or []) if b in local_of]
        if beats:
            seqs.append(dict(s, beats=beats))
    assets = source_many(local_jobs, work, seqs, set(inp.get("exclude") or []))
    project_id, parent = inp["project_id"], inp["parent_job_id"]
    bucket = inp.get("bucket") or config.MEDIA_BUCKET
    out: Dict[str, dict] = {}
    global_of = {k: g for g, k in local_of.items()}
    # Uploads may be retried until just before the parent stops waiting for
    # this part (its round deadline is the sourcing deadline plus 45 s).
    upload_until = (float(inp["deadline_at"]) + config.PART_UPLOAD_GRACE_SECONDS
                    if inp.get("deadline_at") else time.time() + 60.0)

    def upload(k_a):
        k, a = k_a
        g = global_of[k]
        ext = os.path.splitext(a.local_path)[1] or ".bin"
        obj = f"projects/{project_id}/parts/{parent}/{g:04d}{ext}"
        d = asdict(a)
        d.pop("local_path", None)
        try:
            url = storage.broker_upload(a.local_path, bucket, obj, project_id, parent,
                                        read_ttl=60 * 60 * 6, deadline=upload_until)
        except Exception as e:  # noqa: BLE001 - the parent fetches it again from its source
            print(f"[part] scene {g + 1}: upload failed ({str(e)[:120]}); "
                  "handing back where it came from instead", flush=True)
            d.update(remote_url="", storage_path="", refetch=True)
            return str(g), d
        d.update(remote_url=url, storage_path=obj)
        return str(g), d

    ready = [(k, a) for k, a in enumerate(assets)
             if a is not None and a.local_path and os.path.isfile(a.local_path)]
    # Six at a time: one by one, a part's uploads could outlast the parent's wait.
    with ThreadPoolExecutor(max_workers=6) as ex:
        for got in ex.map(upload, ready):
            if got:
                out[got[0]] = got[1]
    delivered = sum(1 for d in out.values() if not d.get("refetch"))
    return {"assets": out, "delivered": delivered, "refetch": len(out) - delivered, "asked": len(jobs)}


# ===========================================================================
# One pod's render spread over the serverless workers (POD_RENDER_FANOUT)
# ===========================================================================
#
# The pod cuts the finished timeline into frame ranges at clean scene cuts,
# renders the first itself and queues the rest as "render_chunk" jobs on the
# serverless endpoint. Each worker renders its range - the picture, and that
# range's slice of the whole sound mix as lossless WAV - from the scene
# media's public R2 links, and hands both back through R2. The pod joins the
# pictures without re-encoding, the sound slices sample-exactly, and encodes
# the sound once (render.finalize): no seam in the picture (every frame is
# drawn on its own, whatever machine draws it) and none in the sound.
#
# Nothing a worker does can lose the video: a chunk that fails, times out or
# is still queued once the pod is free is rendered on the pod; the pod races
# a copy of the slowest worker chunk when it has nothing else to do; and if
# the spread render cannot start or breaks, the caller renders the whole
# video on the pod as before.

# Cut transitions drawn half over the outgoing scene's last frames and half
# over the incoming scene's first ones (remotion/src/transitions/timing.ts
# CUT_TRANSITIONS; a test keeps the two lists equal). A chunk boundary at such
# a cut would fall inside the transition.
CUT_TRANSITIONS = frozenset({"flash", "chromatic-flash", "glitch", "vhs-glitch", "film-burn", "light-leak",
                             "whip-pan", "zoom-punch", "shake-cut", "blur-dissolve", "luma-fade"})
# An overlay's entrance (and the sound built into its look) plays over its first frames.
OVERLAY_ENTRY_FRAMES = 45
# A sound effect with no planned length is taken as this long, and none plays
# longer (Main.tsx SFX_MAX_SECONDS).
SFX_DEFAULT_SECONDS = 3.0
SFX_MAX_SECONDS = 6.0
AUDIO_RATE = 48000
# How often the pod looks at its worker jobs, and how long it idles between
# looks for something to render itself.
POD_POLL_SECONDS = 3.0
POD_IDLE_SECONDS = 1.0
# After this many chunks failed on the pod it stops drawing chunks itself (the
# workers draw the rest): a pod that cannot render a range would fail them all.
POD_LOCAL_FAILURES_MAX = 2

# RunPod job ids of chunks a worker still holds, for cancel_live_jobs().
_LIVE: Dict[str, str] = {}
_LIVE_LOCK = threading.Lock()


def pod_render_ready(doc: Optional[dict] = None) -> dict:
    """Whether a spread render can run, and what is missing (never a secret value)."""
    missing = []
    if not config.POD_RENDER_FANOUT:
        missing.append("POD_RENDER_FANOUT is off")
    if not config.FANOUT_API_KEY:
        missing.append("RunPod API key missing (FANOUT_API_KEY or RUNPOD_API_KEY)")
    if not config.POD_RENDER_ENDPOINT_ID:
        missing.append("endpoint id missing (POD_RENDER_ENDPOINT_ID or FANOUT_ENDPOINT_ID)")
    if not r2.enabled():
        missing.append("Cloudflare R2 is not configured (chunks travel through it)")
    if config.POD_RENDER_CHUNKS < 2:
        missing.append("POD_RENDER_CHUNKS must be at least 2")
    if doc is not None:
        fps = max(1, int(doc.get("fps") or 30))
        if int(doc.get("durationInFrames") or 0) / fps < config.POD_RENDER_MIN_SECONDS:
            missing.append("video shorter than POD_RENDER_MIN_SECONDS")
    return {"enabled": not missing, "chunks": config.POD_RENDER_CHUNKS, "missing": missing}


def pod_render_enabled(doc: Optional[dict] = None) -> bool:
    return pod_render_ready(doc)["enabled"]


def _sfx_spans(doc: dict) -> List[tuple]:
    """(first frame, end frame) of every planned sound effect."""
    fps = max(1, int(doc.get("fps") or 30))
    out = []
    for fx in doc.get("sfx") or []:
        try:
            start = int(round(float(fx.get("startFrame") or 0)))
        except (TypeError, ValueError):
            continue
        d = fx.get("durationFrames")
        frames = int(d) if isinstance(d, (int, float)) and d > 0 else int(SFX_DEFAULT_SECONDS * fps)
        out.append((start, start + min(frames, int(SFX_MAX_SECONDS * fps))))
    return out


def chunk_cuts(doc: dict) -> Tuple[List[int], List[int], List[int]]:
    """
    Frames of the whole video where a chunk may begin, in three tiers, best first:
      clean  - no crossfade or cut transition across the cut, no sound effect
               playing across it, no overlay making its entrance;
      visual - no crossfade or cut transition across the cut;
      every  - every scene start.
    With a brand intro and outro (brandkit.layout) the scene starts come
    `intro` frames later, the end of the intro and the start of the outro are
    the cleanest cuts of all, and no cut falls inside either: each is one
    clip (or one card) with its own sound.
    """
    intro, body, outro, total = brandkit.layout(doc)
    scenes = sorted(doc.get("scenes") or [], key=lambda s: int(s.get("startFrame") or 0))
    sfx = [(a + intro, b + intro) for a, b in _sfx_spans(doc)]
    entries = []
    for o in doc.get("overlays") or []:
        s0 = int(o.get("startFrame") or 0) + intro
        entries.append((s0, s0 + min(OVERLAY_ENTRY_FRAMES, int(o.get("durationInFrames") or 0))))
    clean, visual, every = [], [], []
    for sc in scenes:
        f = int(sc.get("startFrame") or 0) + intro
        if f <= intro or f >= intro + body or (every and every[-1] == f):
            continue
        every.append(f)
        t = str(sc.get("transition") or "none")
        # A pack transition's clip (and its own sound) plays across its cut.
        if t == "crossfade" or t in CUT_TRANSITIONS or t.startswith("pack:"):
            continue
        visual.append(f)
        if any(a < f < b for a, b in sfx) or any(a < f < b for a, b in entries):
            continue
        clean.append(f)
    # The seams between the brand clips and the narration's timeline.
    seams = [f for f in (intro if intro else 0, intro + body if outro else 0) if 0 < f < total]
    for tier in (clean, visual, every):
        tier.extend(seams)
        tier.sort()
    return clean, visual, every


def plan_chunks(doc: dict, n: int, min_frames: int = 1) -> List[tuple]:
    """
    At most `n` inclusive frame ranges covering the whole video with no gap or
    overlap, each at least `min_frames` long, about equal in length, each new
    range starting on the cleanest scene cut near its ideal start (chunk_cuts;
    within half a chunk). With no scene start near, an exact frame is used:
    every frame is drawn on its own, so the picture is still identical.
    The ranges cover the whole video, a brand intro and outro included
    (brandkit.layout); an exact frame never lands inside either while a
    frame outside them is in reach.
    """
    if int(doc.get("durationInFrames") or 0) <= 0:
        return []
    intro, body, outro, total = brandkit.layout(doc)
    min_frames = max(1, int(min_frames or 1))
    n = max(1, min(int(n or 1), total // min_frames))
    if n == 1:
        return [(0, total - 1)]
    tiers = chunk_cuts(doc)
    size = total / n
    inside = [(0, intro), (intro + body, total)]          # (a, b): a < f < b is inside a brand clip
    bounds = [0]
    for i in range(1, n):
        target = int(round(i * size))
        lo = bounds[-1] + min_frames
        hi = total - min_frames * (n - i)
        if hi < lo:
            break
        pick = None
        for tier in tiers:
            near = [f for f in tier if lo <= f <= hi and abs(f - target) <= size / 2]
            if near:
                pick = min(near, key=lambda f: (abs(f - target), f))
                break
        if pick is None:
            pick = min(max(target, lo), hi)
            for a, b in inside:
                if a < pick < b:
                    # Out of the brand clip, to its nearer edge when that edge is in reach.
                    for edge in sorted((a, b), key=lambda e: abs(e - pick)):
                        if lo <= edge <= hi and edge > 0:
                            pick = edge
                            break
        bounds.append(pick)
    return [(a, b - 1) for a, b in zip(bounds, bounds[1:] + [total])]


# --- R2 transfers -----------------------------------------------------------

def _r2_location(url: str) -> Optional[Tuple[str, str]]:
    """(bucket, key) of a link under one of our R2 public bases, else None."""
    for base, bucket in ((config.R2_PUBLIC_BASE, config.R2_BUCKET),
                         (getattr(config, "R2_LIBRARY_PUBLIC_BASE", ""), getattr(config, "R2_LIBRARY_BUCKET", ""))):
        base = (base or "").rstrip("/")
        if base and bucket and url.startswith(base + "/"):
            return bucket, urllib.parse.unquote(url[len(base) + 1:].split("?", 1)[0])
    return None


def _r2_get(key: str, bucket: str, path: str) -> None:
    """One object through the S3 API (the public r2.dev link is rate limited)."""
    headers = r2._auth_headers("GET", key, {}, hashlib.sha256(b"").hexdigest(), bucket=bucket)
    headers["Accept-Encoding"] = "identity"
    with requests.get(r2._object_url(key, bucket), headers=headers, stream=True, timeout=(20, 600)) as r:
        if r.status_code != 200:
            raise RuntimeError(f"R2 GET {key}: HTTP {r.status_code}")
        _stream_to(r, path)


def _stream_to(r, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    part = path + ".part"
    with open(part, "wb") as fh:
        for block in r.iter_content(1 << 20):
            if block:
                fh.write(block)
    os.replace(part, path)


def _fetch(url: str, path: str, key: str = "", bucket: str = "", tries: int = 4) -> str:
    """
    Download `url` (or R2 `key`) to `path`, retried with backoff. Our own R2
    objects go through the S3 API with this worker's keys; anything else (a
    signed narration link, a picture elsewhere) is a plain GET.
    """
    loc = (bucket or config.R2_BUCKET, key) if key else (_r2_location(url) if url else None)
    last = ""
    for attempt in range(tries):
        try:
            if loc and r2.enabled():
                try:
                    _r2_get(loc[1], loc[0], path)
                    return path
                except Exception as e:  # noqa: BLE001 - the public link below
                    last = f"{type(e).__name__}: {str(e)[:120]}"
                    if not url:
                        raise
            if url:
                with requests.get(url, stream=True, timeout=(20, 600)) as r:
                    if r.status_code == 200:
                        _stream_to(r, path)
                        return path
                    last = f"HTTP {r.status_code}"
                    if r.status_code in (400, 401, 403, 404, 410):
                        break
        except Exception as e:  # noqa: BLE001 - retried
            last = f"{type(e).__name__}: {str(e)[:120]}"
        time.sleep(min(20.0, 2.0 * (attempt + 1)))
    raise RuntimeError(f"download failed ({last}): {key or url[:120]}")


def _delete_keys(keys: List[str]) -> None:
    for k in keys:
        try:
            r2.delete(k)
        except Exception:  # noqa: BLE001 - a leftover chunk is only storage
            pass


def _delete_prefix(prefix: str, keys: List[str]) -> None:
    """Every object of one spread render: the keys it knows and whatever else a
    worker left under its prefix (a chunk it finished after the pod raced it)."""
    found = set(keys)
    try:
        found.update(o["key"] for o in r2.list_keys(prefix) if o.get("key", "").startswith(prefix))
    except Exception:  # noqa: BLE001 - the known keys still go
        pass
    _delete_keys(sorted(found))


def _media_dicts(doc: dict) -> List[dict]:
    """Every dict in the document that points at a file the renderer reads."""
    out = []
    for sc in doc.get("scenes") or []:
        if isinstance(sc.get("media"), dict):
            out.append(sc["media"])
        anim = sc.get("animation")
        if isinstance(anim, dict):
            out += [m for m in anim.get("media") or [] if isinstance(m, dict)]
    for o in doc.get("overlays") or []:
        out += [m for m in o.get("media") or [] if isinstance(m, dict)]
    for key in ("audio", "bgm"):
        if isinstance(doc.get(key), dict):
            out.append(doc[key])
    # The brand kit's logo, intro and outro (their links; a local copy goes up too).
    brand = doc.get("brand") if isinstance(doc.get("brand"), dict) else {}
    out += [brand[k] for k in ("watermark", "intro", "outro") if isinstance(brand.get(k), dict)]
    return out


def _publish_files(doc: dict, prefix: str, deadline: float) -> Tuple[dict, List[str]]:
    """
    A copy of the pod's finished document whose every local file (its cleaned
    stills, anything not yet on the web) is uploaded to R2 under `prefix`: the
    exact bytes the pod renders, so every machine draws the same frames.
    Returns (that copy, the keys uploaded). Raises when a file cannot go up.
    """
    remote = copy.deepcopy(doc)
    refs = []
    for m in _media_dicts(remote):
        for field in ("url", "thumbnail"):
            v = str(m.get(field) or "")
            if v and not v.startswith(("http://", "https://", "bgm://", "data:")) and os.path.isfile(v):
                refs.append((m, field, v))
    files = sorted({v for _m, _f, v in refs})

    def up(path: str) -> Tuple[str, str, str]:
        ext = os.path.splitext(path)[1].lower() or ".bin"
        key = f"{prefix}assets/{hashlib.sha1(os.path.abspath(path).encode('utf-8')).hexdigest()[:16]}{ext}"
        url = r2.upload(path, key, content_type=r2.content_type(path), deadline=deadline,
                        cache_control=r2.IMMUTABLE)
        return path, key, url
    uploaded: Dict[str, Tuple[str, str]] = {}
    if files:
        with ThreadPoolExecutor(max_workers=min(8, len(files))) as ex:
            for path, key, url in ex.map(up, files):
                uploaded[path] = (key, url)
    for m, field, v in refs:
        m[field] = uploaded[v][1]
    return remote, [key for key, _url in uploaded.values()]


def _count_frames(path: str) -> int:
    """Video frames in a file (packets counted, nothing decoded); -1 when unreadable."""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                            "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=300)
        return int((p.stdout or "").strip().split(",")[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return -1


def _chunk_ok(video: str, audio: str, frames: int) -> bool:
    """A chunk's picture has exactly its frames and its sound slice exists."""
    return (os.path.isfile(video) and os.path.isfile(audio) and os.path.getsize(audio) > 44
            and _count_frames(video) == frames)


# --- the worker side ----------------------------------------------------------

def _localize(doc: dict, a: int, b: int, work: str) -> dict:
    """
    Download, in parallel, the files frames a..b draw (the scenes on screen,
    the stills their neighbours lend to animation backdrops and case-file
    looks, the overlays' pictures, the narration) and point the document at
    the local copies. Anything not fetched keeps its link and Remotion reads
    it itself. Remotion downloads a clip whole before its first frame anyway;
    done here it all happens before the first frame instead of stalling tabs,
    and our own R2 objects come through the S3 API, not the rate-limited
    public link.
    """
    started = time.time()
    scenes = doc.get("scenes") or []
    # a..b are frames of the whole video; the narration's timeline starts
    # after the brand intro, and the brand's own files go when on screen.
    intro, body, outro, _total = brandkit.layout(doc)
    brand_files: List[Tuple[dict, str]] = []
    brand = doc.get("brand") if isinstance(doc.get("brand"), dict) else {}
    if intro and a < intro and isinstance(brand.get("intro"), dict):
        brand_files.append((brand["intro"], "url"))
    if outro and b >= intro + body and isinstance(brand.get("outro"), dict):
        # (A card's logo stays a link: only url fields are served from this disk, assetserver.MEDIA_FIELDS.)
        brand_files.append((brand["outro"], "url"))
    if isinstance(brand.get("watermark"), dict) and a < intro + body and b >= intro:
        brand_files.append((brand["watermark"], "url"))
    a, b = a - intro, b - intro
    on: List[int] = []
    for i, sc in enumerate(scenes):
        s0 = int(sc.get("startFrame") or 0)
        nxt = scenes[i + 1] if i + 1 < len(scenes) else {}
        s1 = s0 + int(sc.get("durationInFrames") or 0) - 1 + (
            CROSSFADE_FRAMES if (nxt or {}).get("transition") == "crossfade" else 0)
        if s0 <= b and s1 >= a:
            on.append(i)
    wanted: List[Tuple[dict, str]] = []
    for i in on:
        m = scenes[i].get("media") or {}
        wanted += [(m, "url"), (m, "thumbnail")]
        anim = scenes[i].get("animation")
        if isinstance(anim, dict):
            wanted += [(x, "url") for x in anim.get("media") or [] if isinstance(x, dict)]
    near = set()
    for i in on:
        near.update(range(max(0, i - 3), min(len(scenes), i + 8)))
    for j in sorted(near - set(on)):
        m = scenes[j].get("media") or {}
        wanted.append((m, "thumbnail"))
        if m.get("type") == "image":
            wanted.append((m, "url"))
    for o in doc.get("overlays") or []:
        s0 = int(o.get("startFrame") or 0)
        if s0 <= b and s0 + int(o.get("durationInFrames") or 0) - 1 >= a:
            wanted += [(m, "url") for m in o.get("media") or [] if isinstance(m, dict)]
    if isinstance(doc.get("audio"), dict):
        wanted.append((doc["audio"], "url"))
    wanted += brand_files
    targets: Dict[str, str] = {}
    for m, field in wanted:
        url = str(m.get(field) or "")
        if url.startswith(("http://", "https://")) and url not in targets:
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1][:6] or ".bin"
            targets[url] = os.path.join(work, "media", hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext)

    def get(item):
        url, path = item
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return url, path                      # an earlier chunk on this machine fetched it
        try:
            return url, _fetch(url, path)
        except Exception as e:  # noqa: BLE001 - Remotion reads the link itself
            print(f"[chunk] prefetch failed, the renderer reads the link: {str(e)[:120]}", flush=True)
            return url, ""
    got: Dict[str, str] = {}
    if targets:
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as ex:
            for url, path in ex.map(get, list(targets.items())):
                if path:
                    got[url] = path
    for m, field in wanted:
        url = str(m.get(field) or "")
        if url in got:
            m[field] = got[url]
    size = sum(os.path.getsize(p) for p in got.values() if os.path.isfile(p))
    return {"files": len(got), "failed": len(targets) - len(got), "mb": round(size / 1e6, 1),
            "seconds": round(time.time() - started, 1)}


def _load_timeline(inp: dict, work: str) -> dict:
    if isinstance(inp.get("timeline"), dict):
        return copy.deepcopy(inp["timeline"])
    path = os.path.join(work, "timeline.json")
    _fetch(str(inp.get("timeline_url") or ""), path, key=str(inp.get("timeline_key") or ""))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _prefix_ok(prefix: str) -> bool:
    """A chunk may only write under the configured chunk prefix, one folder deep."""
    root = config.POD_RENDER_PREFIX.rstrip("/")
    return bool(root) and re.fullmatch(re.escape(root) + r"/[A-Za-z0-9_-]{1,120}/", prefix or "") is not None


def run_pod_chunk(inp: dict, work: str, progress: Callable = None) -> dict:
    """
    The worker side of render_pod(): render frames a..b of the pod's finished
    document - the picture, and that range's slice of the sound as WAV - and
    put both in R2 under the pod's prefix. Refuses (the pod then renders the
    chunk itself) when it starts after its deadline or when this worker's
    renderer is not the pod's: two code versions could draw different frames.
    """
    started = time.time()
    a, b = (int(x) for x in inp["frames"])
    i = int(inp.get("chunk", 0))
    prefix = str(inp.get("prefix") or "")
    if inp.get("deadline_at") and time.time() > float(inp["deadline_at"]):
        return {"ok": False, "chunk": i, "error": "the chunk started after its deadline"}
    mine = renderer.renderer_fingerprint()
    if inp.get("renderer") and inp["renderer"] != mine:
        return {"ok": False, "chunk": i, "error": f"this worker's renderer {mine} is not the pod's {inp['renderer']}"}
    if not r2.enabled():
        return {"ok": False, "chunk": i, "error": "Cloudflare R2 is not configured on this worker"}
    if not _prefix_ok(prefix):
        return {"ok": False, "chunk": i, "error": "bad chunk prefix"}
    doc = _load_timeline(inp, work)
    fetched = _localize(doc, a, b, work)
    video = os.path.join(work, f"chunk_{i:03d}.mp4")
    audio = os.path.join(work, f"chunk_{i:03d}.wav")
    # The pod's encoder settings: pictures encoded differently would not join
    # without re-encoding.
    saved = {}
    for name, value in (("RENDER_CRF", inp.get("crf")), ("RENDER_X264_PRESET", inp.get("x264"))):
        if value is not None:
            saved[name] = getattr(config, name)
            setattr(config, name, type(saved[name])(value))
    try:
        renderer.render(doc, video, composition=inp.get("composition") or "Main",
                        concurrency=config.RENDER_CONCURRENCY, serve_dir=work, on_progress=progress,
                        frames=(a, b), audio_to=audio)
    finally:
        for name, value in saved.items():
            setattr(config, name, value)
    frames = _count_frames(video)
    if frames != b - a + 1:
        return {"ok": False, "chunk": i, "error": f"rendered {frames} frames, expected {b - a + 1}"}
    token = uuid.uuid4().hex[:12]
    until = time.time() + 600
    vkey, akey = f"{prefix}{i:03d}-{token}.mp4", f"{prefix}{i:03d}-{token}.wav"
    vurl = r2.upload(video, vkey, content_type="video/mp4", deadline=until)
    aurl = r2.upload(audio, akey, content_type="audio/wav", deadline=until)
    return {"ok": True, "chunk": i, "frames": [a, b], "video_key": vkey, "video_url": vurl,
            "audio_key": akey, "audio_url": aurl, "renderer": mine, "fetched": fetched,
            "seconds": round(time.time() - started, 1)}


# --- the pod side -------------------------------------------------------------

def _register(job_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE[job_id] = config.POD_RENDER_ENDPOINT_ID


def _unregister(job_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE.pop(job_id, None)


def cancel_live_jobs() -> int:
    """Cancel every chunk job a worker still holds (the pod job is ending). Returns how many."""
    with _LIVE_LOCK:
        live = dict(_LIVE)
        _LIVE.clear()
    for jid, endpoint in live.items():
        try:
            requests.post(f"https://api.runpod.ai/v2/{endpoint}/cancel/{jid}",
                          headers={"Authorization": f"Bearer {config.FANOUT_API_KEY}"}, timeout=15)
        except requests.RequestException:
            pass
    return len(live)


def _pod_submit(payload: dict) -> Tuple[str, str]:
    """(job id, "") or ("", why). A policy RunPod refuses is dropped and the job sent again."""
    url = f"https://api.runpod.ai/v2/{config.POD_RENDER_ENDPOINT_ID}/run"
    headers = {"Authorization": f"Bearer {config.FANOUT_API_KEY}"}
    why = ""
    bodies = [payload] + ([{k: v for k, v in payload.items() if k != "policy"}] if "policy" in payload else [])
    for body in bodies:
        try:
            r = requests.post(url, headers=headers, json=body, timeout=30)
            jid = (r.json() or {}).get("id") if r.status_code < 400 else ""
            if jid:
                return str(jid), ""
            why = f"HTTP {r.status_code}: {r.text[:160]}"
        except (requests.RequestException, ValueError) as e:
            why = type(e).__name__
    return "", why


def _pod_status(job_id: str) -> dict:
    try:
        return requests.get(f"https://api.runpod.ai/v2/{config.POD_RENDER_ENDPOINT_ID}/status/{job_id}",
                            headers={"Authorization": f"Bearer {config.FANOUT_API_KEY}"},
                            timeout=30).json() or {}
    except (requests.RequestException, ValueError):
        return {}


def _pod_cancel(job_id: str) -> None:
    _unregister(job_id)
    try:
        requests.post(f"https://api.runpod.ai/v2/{config.POD_RENDER_ENDPOINT_ID}/cancel/{job_id}",
                      headers={"Authorization": f"Bearer {config.FANOUT_API_KEY}"}, timeout=15)
    except requests.RequestException:
        pass


class _Chunk:
    """One frame range of a spread render and who is drawing it."""

    def __init__(self, i: int, a: int, b: int, work: str):
        self.i, self.a, self.b = i, a, b
        self.frames = b - a + 1
        self.job = ""                 # the worker job holding it
        self.queued_at = 0.0
        self.started_at = 0.0         # a worker started it (IN_PROGRESS seen)
        self.frac = 0.0               # the worker's progress
        self.remote_dead = False      # no worker will deliver it: the pod must
        self.fetching = False         # a finished worker chunk is downloading
        self.local = False            # the pod is rendering it
        self.local_frac = 0.0
        self.local_cancel: Optional[threading.Event] = None
        self.speculative = False      # the pod races a worker for it
        self.local_failed = False
        self.handing = False          # failed on the pod, being queued for a worker
        self.done = False
        self.source = ""              # "worker" | "pod"
        self.video = self.audio = ""
        self.keys: List[str] = []     # its files in R2
        self.pod_video = os.path.join(work, f"pchunk_{i:03d}.pod.mp4")
        self.pod_audio = os.path.join(work, f"pchunk_{i:03d}.pod.wav")
        self.worker_video = os.path.join(work, f"pchunk_{i:03d}.worker.mp4")
        self.worker_audio = os.path.join(work, f"pchunk_{i:03d}.worker.wav")


class _PodRender:
    """The pod's side of one spread render: queue, watch, take back, race, collect, join."""

    def __init__(self, doc: dict, ranges: List[tuple], *, fps: int, total: int, prefix: str, tl_key: str,
                 tl_url: str, job_id: str, work: str, report: Callable, composition: str = "Main",
                 concurrency: int = None):
        self.doc = doc
        self.chunks = [_Chunk(i, a, b, work) for i, (a, b) in enumerate(ranges)]
        self.fps, self.total, self.prefix = fps, total, prefix
        self.tl_key, self.tl_url, self.job_id, self.work = tl_key, tl_url, job_id, work
        self.report, self.composition, self.concurrency = report, composition, concurrency
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.started = time.time()
        self.deadline = self.started + config.POD_RENDER_TIMEOUT_SECONDS
        self.fingerprint = renderer.renderer_fingerprint()
        self.local_fps = 0.0
        self.fatal = ""
        self.counts = {"queued": 0, "submitFailed": 0, "takenBack": 0, "raced": 0, "workerFailed": 0,
                       "timedOut": 0, "handedOver": 0}
        # Why chunks failed, here and on the workers: the pod's log is gone once
        # it stops, so the reasons travel in the stats and the job's events.
        self.errors: List[str] = []
        self.local_failures = 0
        self._last_pct = -1

    # ---- worker jobs
    def _payload(self, c: _Chunk) -> dict:
        body = {"input": {"action": "render_chunk", "upload": "r2", "parent_job_id": self.job_id,
                          "chunk": c.i, "frames": [c.a, c.b], "timeline_key": self.tl_key,
                          "timeline_url": self.tl_url, "prefix": self.prefix, "renderer": self.fingerprint,
                          "crf": config.RENDER_CRF, "x264": renderer.x264_preset(), "composition": "Main",
                          "deadline_at": self.deadline}}
        if config.POD_RENDER_JOB_POLICY:
            run_ms = int(config.POD_RENDER_CHUNK_TIMEOUT_SECONDS * 1000)
            body["policy"] = {"executionTimeout": run_ms,
                              "ttl": int(max(run_ms, (self.deadline - time.time()) * 1000) + 600_000)}
        return body

    def _submit_all(self) -> None:
        remote = self.chunks[1:]
        if not remote:
            return
        with ThreadPoolExecutor(max_workers=min(8, len(remote))) as ex:
            results = list(ex.map(lambda c: _pod_submit(self._payload(c)), remote))
        now = time.time()
        for c, (jid, why) in zip(remote, results):
            if jid:
                c.job, c.queued_at = jid, now
                _register(jid)
                self.counts["queued"] += 1
            else:
                c.remote_dead = True
                self.counts["submitFailed"] += 1
                print(f"[pod-render] chunk {c.i} could not be queued ({why}); the pod renders it", flush=True)

    def _drop_worker(self, c: _Chunk, why: str, cancel: bool = True) -> None:
        """No worker will deliver this chunk (caller holds the lock)."""
        if c.job:
            if cancel:
                threading.Thread(target=_pod_cancel, args=(c.job,), daemon=True).start()
            else:
                _unregister(c.job)
        c.job, c.remote_dead = "", True
        if why:
            print(f"[pod-render] chunk {c.i}: {why}; the pod renders it", flush=True)
            self._note(c, why, "worker_chunk_dropped")
        self.wake.set()

    def _note(self, c: _Chunk, why: str, event: str) -> None:
        """Keep a chunk's failure for the stats and the job's events (the first few)."""
        if len(self.errors) < 12:
            self.errors.append(f"chunk {c.i}: {why}"[:240])
            events.emit("render", event, level="warning", message=f"chunk {c.i}: {why}",
                        data={"chunk": c.i, "frames": [c.a, c.b]})

    def _poll(self, pool: ThreadPoolExecutor, fetch_pool: ThreadPoolExecutor) -> None:
        with self.lock:
            watch = [c for c in self.chunks if c.job and not c.done and not c.fetching]
        if not watch:
            return
        states = dict(zip([c.i for c in watch], pool.map(lambda c: _pod_status(c.job), watch)))
        now = time.time()
        with self.lock:
            for c in watch:
                if c.done or not c.job or c.fetching:
                    continue
                st = states.get(c.i) or {}
                state = st.get("status")
                out = st.get("output")
                if state == "IN_PROGRESS":
                    c.started_at = c.started_at or now
                    if isinstance(out, dict) and isinstance(out.get("frac"), (int, float)):
                        c.frac = max(c.frac, min(1.0, float(out["frac"])))
                    if now - c.started_at > config.POD_RENDER_CHUNK_TIMEOUT_SECONDS:
                        self.counts["timedOut"] += 1
                        self._drop_worker(c, "the worker took too long")
                elif state == "COMPLETED":
                    if isinstance(out, dict) and out.get("ok") and out.get("video_key") and out.get("audio_key"):
                        c.fetching = True
                        c.keys = [str(out["video_key"]), str(out["audio_key"])]
                        fetch_pool.submit(self._collect, c, out)
                    else:
                        self.counts["workerFailed"] += 1
                        err = out.get("error") if isinstance(out, dict) else out
                        self._drop_worker(c, f"the worker could not render it ({str(err)[:160]})", cancel=False)
                elif state in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    self.counts["workerFailed"] += 1
                    err = (out.get("error") if isinstance(out, dict) else out) or st.get("error") or state
                    self._drop_worker(c, f"worker job {state.lower()} ({str(err)[:160]})", cancel=False)

    def _collect(self, c: _Chunk, out: dict) -> None:
        """Download a worker's finished chunk and check it."""
        ok = False
        try:
            _fetch(str(out.get("video_url") or ""), c.worker_video, key=str(out["video_key"]))
            _fetch(str(out.get("audio_url") or ""), c.worker_audio, key=str(out["audio_key"]))
            ok = _chunk_ok(c.worker_video, c.worker_audio, c.frames)
            if not ok:
                print(f"[pod-render] chunk {c.i} from the worker is incomplete", flush=True)
        except Exception as e:  # noqa: BLE001 - rendered on the pod instead
            print(f"[pod-render] chunk {c.i}: download failed ({str(e)[:160]})", flush=True)
        with self.lock:
            c.fetching = False
            if c.job:
                _unregister(c.job)
            c.job = ""
            if ok and not c.done:
                c.done, c.source, c.video, c.audio = True, "worker", c.worker_video, c.worker_audio
                if c.local and c.local_cancel is not None:
                    c.local_cancel.set()              # the pod's race copy is not needed
            elif not ok and not c.done:
                self.counts["workerFailed"] += 1
                c.remote_dead = True
        self.wake.set()

    # ---- the pod's own rendering
    def _next_local(self) -> Optional[_Chunk]:
        """What the pod renders next (caller holds the lock)."""
        if self.local_failures >= POD_LOCAL_FAILURES_MAX:
            return None                                  # the pod's own renders keep failing: workers only
        now = time.time()
        todo = [c for c in self.chunks if not c.done and not c.local and not c.fetching and not c.local_failed]
        first = self.chunks[0]
        if first in todo and not first.job:
            return first
        for c in todo:                                   # no worker will deliver these
            if c.remote_dead and not c.job:
                return c
        if now > self.deadline:                          # the spread render is out of time
            for c in todo:
                if c.job:
                    self._drop_worker(c, "the spread render ran out of time")
                    return c
        for c in todo:                                   # still queued: take it back
            if c.job and not c.started_at and now - c.queued_at > config.POD_RENDER_QUEUE_GRACE_SECONDS:
                self.counts["takenBack"] += 1
                self._drop_worker(c, f"no worker started it in {int(now - c.queued_at)} s")
                return c
        if config.POD_RENDER_SPECULATE and self.local_fps > 0:
            best, gain = None, 0.0
            for c in todo:                               # race the slowest worker chunk
                if not (c.job and c.started_at) or c.speculative:
                    continue
                elapsed = now - c.started_at
                left = (elapsed * (1 - c.frac) / c.frac) if c.frac > 0.03 else \
                    max(0.0, config.POD_RENDER_CHUNK_TIMEOUT_SECONDS - elapsed)
                here = c.frames / self.local_fps + 20.0
                if left > here * 1.25 and left - here > gain:
                    best, gain = c, left - here
            if best is not None:
                best.speculative = True
                self.counts["raced"] += 1
                print(f"[pod-render] racing chunk {best.i} on the pod (~{int(gain)} s sooner)", flush=True)
                return best
        return None

    def _render_here(self, c: _Chunk) -> None:
        started = time.time()

        def prog(frac: float) -> None:
            c.local_frac = max(c.local_frac, float(frac))
        ok = cancelled = False
        err = ""
        try:
            # The same bytes the workers draw: the document's links fetched
            # through R2 (the pod's own stills are local files already).
            chunk_doc = copy.deepcopy(self.doc)
            _localize(chunk_doc, c.a, c.b, self.work)
            renderer.render(chunk_doc, c.pod_video, composition=self.composition, concurrency=self.concurrency,
                            serve_dir=self.work, on_progress=prog, frames=(c.a, c.b), audio_to=c.pod_audio,
                            cancel=c.local_cancel)
            ok = _chunk_ok(c.pod_video, c.pod_audio, c.frames)
            if not ok:
                err = f"incomplete on the pod ({_count_frames(c.pod_video)} of {c.frames} frames)"
        except renderer.RenderCancelled:
            cancelled = True
        except Exception as e:  # noqa: BLE001 - reported below
            err = f"failed on the pod ({type(e).__name__}: {str(e)[:300]})"
        if err:
            print(f"[pod-render] chunk {c.i} {err}", flush=True)
        hand = False
        with self.lock:
            c.local = False
            if ok:
                self.local_fps = c.frames / max(1.0, time.time() - started)
                if not c.done:
                    c.done, c.source, c.video, c.audio = True, "pod", c.pod_video, c.pod_audio
                    if c.job:
                        self._drop_worker(c, "", cancel=True)
            elif not cancelled and not c.done:
                c.local_failed = True
                self.local_failures += 1
                self._note(c, err or "failed on the pod", "pod_chunk_failed")
                if not c.job:
                    c.handing = hand = True
        if hand:
            # One failure here need not end the spread render (2026-10-01: the
            # pod's own first chunk failed and an 18-minute video went back to
            # one machine, 45 minutes): a worker draws the chunk instead.
            jid, why = _pod_submit(self._payload(c))
            with self.lock:
                c.handing = False
                if c.done:
                    pass
                elif jid:
                    c.job, c.queued_at, c.started_at, c.frac, c.remote_dead = jid, time.time(), 0.0, 0.0, False
                    _register(jid)
                    self.counts["handedOver"] += 1
                    print(f"[pod-render] chunk {c.i} goes to a worker instead", flush=True)
                else:
                    self.fatal = (f"chunk {c.i} (frames {c.a}-{c.b}) could not be rendered: {err[:160]}; "
                                  f"no worker took it ({why})")
        self.wake.set()

    def _local_loop(self) -> None:
        while True:
            with self.lock:
                if self.fatal or all(c.done for c in self.chunks):
                    return
                c = self._next_local()
                if c is not None:
                    c.local, c.local_frac = True, 0.0
                    c.local_cancel = threading.Event()
            if c is None:
                time.sleep(POD_IDLE_SECONDS)
                continue
            self._render_here(c)

    # ---- progress
    def _progress(self) -> None:
        with self.lock:
            done = sum(c.frames * (1.0 if c.done else max(c.frac * 0.95, c.local_frac)) for c in self.chunks)
            busy = sum(1 for c in self.chunks if not c.done and (c.local or c.started_at))
        frac = done / max(1, self.total)
        pct = 70 + int(20 * min(1.0, frac))
        if pct != self._last_pct:
            self._last_pct = pct
            self.report(f"Rendering video {int(min(1.0, frac) * 100)}% on {max(1, busy)} machines", pct)

    # ---- the whole run
    def run(self) -> None:
        self._submit_all()
        print(f"[pod-render] {len(self.chunks)} chunks: {self.counts['queued']} on workers, the first here",
              flush=True)
        local = threading.Thread(target=self._local_loop, daemon=True, name="pod-render-local")
        local.start()
        with ThreadPoolExecutor(max_workers=8) as pool, ThreadPoolExecutor(max_workers=4) as fetch_pool:
            while True:
                with self.lock:
                    if self.fatal or all(c.done for c in self.chunks):
                        break
                    watching = any(c.job or c.fetching or c.handing for c in self.chunks)
                    # Nobody left to draw a chunk: it failed here and on a
                    # worker, or no worker will and the pod no longer renders.
                    broken = self.local_failures >= POD_LOCAL_FAILURES_MAX
                    stuck = next((c for c in self.chunks if not c.done and not c.job and not c.fetching
                                  and not c.local and not c.handing
                                  and (c.local_failed or (broken and c.remote_dead))), None)
                    if stuck is not None:
                        last = f": {self.errors[-1]}" if self.errors else ""
                        self.fatal = f"chunk {stuck.i} (frames {stuck.a}-{stuck.b}) could not be rendered{last}"
                        break
                if not watching and not local.is_alive():
                    self.fatal = self.fatal or "nobody is rendering the remaining chunks"
                    break
                self._poll(pool, fetch_pool)
                self._progress()
                self.wake.wait(POD_POLL_SECONDS)
                self.wake.clear()
        self.cancel_all()
        local.join(timeout=60)
        if self.fatal:
            raise RuntimeError(self.fatal)

    def cancel_all(self) -> None:
        with self.lock:
            for c in self.chunks:
                if c.job and not c.fetching:
                    self._drop_worker(c, "", cancel=True)
                if c.local and c.local_cancel is not None:
                    c.local_cancel.set()

    def keys(self) -> List[str]:
        return [k for c in self.chunks for k in c.keys]

    def stats(self) -> dict:
        return {"chunks": len(self.chunks), "onWorkers": sum(1 for c in self.chunks if c.source == "worker"),
                "onPod": sum(1 for c in self.chunks if c.source == "pod"), **self.counts,
                "podFps": round(self.local_fps, 1), "seconds": round(time.time() - self.started, 1),
                "errors": list(self.errors[:6])}

    # ---- joining
    def join(self) -> Tuple[str, str]:
        """The chunks' pictures joined without re-encoding and their sound slices sample-exactly."""
        order = sorted(self.chunks, key=lambda c: c.a)
        video = os.path.join(self.work, "pod_video.mp4")
        join_videos([c.video for c in order], video, self.total)
        audio = os.path.join(self.work, "pod_audio.wav")
        join_wavs([(c.audio, c.frames) for c in order], self.fps, audio)
        return video, audio


def join_videos(paths: List[str], out: str, frames: int) -> str:
    """The chunk pictures, in order, joined without re-encoding; exactly `frames` long or an error."""
    listing = out + ".txt"
    with open(listing, "w", encoding="utf-8") as fh:
        fh.writelines("file '{}'\n".format(os.path.abspath(p).replace("\\", "/").replace("'", "'\\''"))
                      for p in paths)
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", listing, "-map", "0:v:0", "-c", "copy", out],
                       capture_output=True, text=True, timeout=1800)
    got = _count_frames(out)
    if p.returncode != 0 or got != frames:
        raise RuntimeError(f"joining the chunks gave {got} of {frames} frames: {(p.stderr or '')[-300:]}")
    return out


def join_wavs(parts: List[Tuple[str, int]], fps: int, out: str) -> str:
    """
    One WAV from sound slices [(path, frames)], each padded or trimmed to
    exactly its frames' length (48 kHz: 1600 samples a frame at 30 fps), so
    every slice starts on its own first frame and nothing drifts.
    """
    inputs, chains = [], []
    for k, (path, frames) in enumerate(parts):
        n = int(round(frames * AUDIO_RATE / max(1, fps)))
        inputs += ["-i", path]
        chains.append(f"[{k}:a]aresample={AUDIO_RATE},aformat=sample_fmts=s16:channel_layouts=stereo,"
                      f"apad=whole_len={n},atrim=end_sample={n},asetpts=N/SR/TB[a{k}]")
    graph = ";".join(chains) + ";" + "".join(f"[a{k}]" for k in range(len(parts))) + \
        f"concat=n={len(parts)}:v=0:a=1[out]"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex", graph,
                        "-map", "[out]", "-c:a", "pcm_s16le", out],
                       capture_output=True, text=True, timeout=1800)
    if p.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(f"joining the sound slices failed: {(p.stderr or '')[-300:]}")
    return out


def render_pod(doc: dict, out_path: str, *, job_id: str, work: str, report: Callable,
               composition: str = "Main", concurrency: int = None) -> bool:
    """
    Render the pod's finished document `doc` to `out_path`, spread over the
    serverless workers (see the notes above this section). True when
    `out_path` was written; False when the spread render could not run or
    broke (the reason is logged, every worker job is cancelled): the caller
    then renders the whole video on the pod.
    """
    if not pod_render_enabled(doc):
        return False
    fps = max(1, int(doc.get("fps") or 30))
    # Every frame of the video: the brand intro and outro around the narration.
    total = brandkit.total_frames(doc)
    ranges = plan_chunks(doc, config.POD_RENDER_CHUNKS, config.POD_RENDER_MIN_CHUNK_FRAMES)
    if len(ranges) < 2:
        return False
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", job_id or "job")[:60]
    prefix = f"{config.POD_RENDER_PREFIX.rstrip('/')}/{safe}-{uuid.uuid4().hex[:10]}/"
    keys: List[str] = []
    runner = None
    ok = False
    reason = ""
    try:
        report(f"Rendering video 0% on {len(ranges)} machines", 70)
        remote, asset_keys = _publish_files(doc, prefix, time.time() + 300)
        keys += asset_keys
        tl_key = prefix + "timeline.json"
        tl_url = r2.upload_bytes(json.dumps(remote).encode("utf-8"), tl_key, content_type="application/json",
                                 deadline=time.time() + 120)
        keys.append(tl_key)
        runner = _PodRender(doc, ranges, fps=fps, total=total, prefix=prefix, tl_key=tl_key, tl_url=tl_url,
                            job_id=job_id, work=work, report=report, composition=composition,
                            concurrency=concurrency)
        runner.run()
        video, audio = runner.join()
        report("Balancing the sound", 90)
        renderer.finalize(video, audio, out_path)
        ok = True
    except Exception as e:  # noqa: BLE001 - the whole video is rendered on the pod instead
        reason = f"{type(e).__name__}: {str(e)[:300]}"
        print(f"[pod-render] spread render stopped ({reason}); rendering the whole video on the pod", flush=True)
    finally:
        stats = {**(runner.stats() if runner is not None else {"chunks": len(ranges)}), "ok": ok}
        if reason:
            stats["error"] = reason
        if runner is not None:
            runner.cancel_all()
            keys += runner.keys()
        media.LAST_STATS["pod_render"] = stats
        print(f"[pod-render] {stats}", flush=True)
        # The job's events keep it after the pod is gone: how long the spread
        # took on how many machines, or why it stopped.
        events.emit("render", "spread_render" if ok else "spread_stopped", level="info" if ok else "warning",
                    message=(f"{stats.get('onWorkers', 0)} chunks on workers, {stats.get('onPod', 0)} on the pod, "
                             f"{stats.get('seconds', 0)} s") if ok else reason,
                    data={k: v for k, v in stats.items() if k != "errors"})
        if not config.POD_RENDER_KEEP_CHUNKS and (keys or runner is not None):
            threading.Thread(target=_delete_prefix, args=(prefix, list(keys)), daemon=True).start()
    return ok
