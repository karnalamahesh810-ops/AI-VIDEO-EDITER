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

import math
import os
import threading
import time
from dataclasses import asdict, fields
from typing import Any, Callable, Dict, List, Optional

import requests

from . import config, media, storage


def enabled_for(n_scenes: int, project_id: str) -> bool:
    return bool(config.FANOUT_PARTS > 1 and n_scenes >= config.FANOUT_MIN_SCENES
                and config.FANOUT_API_KEY and config.FANOUT_ENDPOINT_ID
                and project_id and storage.broker_enabled())


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


def source(jobs: List[dict], sequences: List[dict], brief: dict, *, parent_job_id: str,
           project_id: str, bucket: str, work: str, flags: dict,
           report: Callable, local: Callable[[List[dict], set], List[Optional[media.MediaAsset]]]
           ) -> List[Optional[media.MediaAsset]]:
    """
    Sourced assets for every job (list aligned to job["index"]).

    `local(jobs, exclude)` sources jobs on this worker, for whatever the parts
    did not deliver and for cross-part duplicates.
    """
    n = max(j["index"] for j in jobs) + 1
    results: List[Optional[media.MediaAsset]] = [None] * n
    parts = split(jobs, sequences, config.FANOUT_PARTS)
    # The parent sources the first part itself instead of waiting idle, and
    # takes back any part no machine has started once it is free again.
    parts_remote = parts[1:]
    here: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def start_here(p: dict) -> None:
        run = {"part": p, "done": threading.Event(), "assets": None, "taken": False}

        def go():
            try:
                with lock:              # media's shared state: one local batch at a time
                    run["assets"] = local(p["jobs"], set())
            except Exception as e:  # noqa: BLE001 - its scenes are refilled below
                print(f"[fanout] local part failed: {e}", flush=True)
            finally:
                run["done"].set()
        here.append(run)
        threading.Thread(target=go, daemon=True).start()

    def free_here() -> bool:
        return all(r["done"].is_set() for r in here)

    def collect_here() -> int:
        n_done = 0
        for r in here:
            if r["done"].is_set() and not r["taken"]:
                r["taken"] = True
                if r["assets"] is None:
                    failed_parts.append(r["part"])
                else:
                    for j, a in zip(sorted(r["part"]["jobs"], key=lambda j: j["index"]), r["assets"]):
                        results[j["index"]] = a
            if r["done"].is_set():
                n_done += len(r["part"]["jobs"])
        return n_done

    start_here(parts[0])
    submitted = []
    for p in parts_remote:
        jid = _submit({"action": "source_part", "parent_job_id": parent_job_id,
                       "project_id": project_id, "bucket": bucket, "brief": brief,
                       "jobs": p["jobs"], "sequences": p["sequences"], "exclude": [],
                       **flags})
        submitted.append((p, jid))
    live = [(p, jid) for p, jid in submitted if jid]
    print(f"[fanout] {len(live)}/{len(parts_remote)} parts on other workers "
          f"({sum(len(p['jobs']) for p, _ in live)} scenes) + 1 here", flush=True)
    total_scenes = len(jobs)
    report(f"Sourcing in parallel on {len(live) + 1} workers", 30, done=0, total=total_scenes)

    deadline = time.time() + max(config.FANOUT_TIMEOUT_SECONDS, 6.0 * len(jobs))
    pending = {jid: p for p, jid in live}
    failed_parts = [p for p, jid in submitted if not jid]
    progress: Dict[str, int] = {}
    stolen = 0
    here_done = 0
    while (pending or not free_here()) and time.time() < deadline:
        time.sleep(8)
        here_done = collect_here()
        for jid in list(pending):
            st = _status(jid)
            state = st.get("status")
            if state == "IN_QUEUE" and free_here():
                # No machine picked this part up and this worker is free:
                # take it back and source it here now (work stealing).
                _cancel(jid)
                start_here(pending.pop(jid))
                stolen += 1
                print(f"[fanout] part {jid[:8]} never started; sourcing it here", flush=True)
                continue
            if state == "IN_PROGRESS" and isinstance(st.get("output"), dict):
                progress[jid] = int(st["output"].get("done") or 0)
            if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
                p = pending.pop(jid)
                out = st.get("output") or {}
                assets = out.get("assets") if isinstance(out, dict) else None
                if state != "COMPLETED" or not isinstance(assets, dict):
                    print(f"[fanout] part {jid[:8]} {state}: "
                          f"{str(out.get('error') if isinstance(out, dict) else out)[:160]}",
                          flush=True)
                    failed_parts.append(p)
                    continue
                progress[jid] = len(p["jobs"])
                for key, d in assets.items():
                    i = int(key)
                    url = d.get("remote_url") or ""
                    ext = os.path.splitext((d.get("storage_path") or "x.bin"))[1] or ".bin"
                    path = os.path.join(work, f"part_{i:04d}{ext}")
                    try:
                        storage.download(url, path)
                        results[i] = _asset_from(d, path)
                    except Exception as e:  # noqa: BLE001 - re-sourced below
                        print(f"[fanout] scene {i + 1}: download failed ({e})", flush=True)
        done_now = min(total_scenes, sum(progress.values()) + here_done)
        busy = len(pending) + (0 if free_here() else 1)
        report(f"Sourced {done_now}/{total_scenes} scenes on {busy} workers",
               30 + int(32 * done_now / max(1, total_scenes)), done=done_now, total=total_scenes)
    for r in here:                               # past the deadline: wait for our own work
        r["done"].wait()
    collect_here()
    for jid, p in pending.items():             # timed out: take it back
        _cancel(jid)
        failed_parts.append(p)

    # Clips two parts both picked: the first scene keeps it.
    seen: Dict[str, int] = {}
    dup_jobs = []
    by_index = {j["index"]: j for j in jobs}
    for i, a in enumerate(results):
        if a is None:
            continue
        ident = a.identity
        if ident in seen:
            results[i] = None
            dup_jobs.append(by_index[i])
        else:
            seen[ident] = i
    leftover = [j for p in failed_parts for j in p["jobs"]]
    leftover += [by_index[i] for i, a in enumerate(results)
                 if a is None and i in by_index and by_index[i] not in leftover
                 and by_index[i] not in dup_jobs]
    todo = leftover + dup_jobs
    if todo:
        print(f"[fanout] sourcing {len(todo)} scene(s) here "
              f"({len(leftover)} undelivered, {len(dup_jobs)} cross-part repeats)", flush=True)
        report(f"Filling {len(todo)} remaining scenes", 62)
        got = local(todo, set(seen))
        for j, a in zip(sorted(todo, key=lambda j: j["index"]), got):
            results[j["index"]] = a
    media.LAST_STATS["fanout"] = {"parts": len(parts), "on_workers": len(live),
                                  "stolen_back": stolen,
                                  "failed_parts": len(failed_parts),
                                  "cross_part_repeats": len(dup_jobs),
                                  "sourced_by_parent": len(todo)}
    return results


def run_part(inp: dict, work: str, source_many: Callable, set_story: Callable) -> dict:
    """The child side: source one part, upload its files, return them."""
    brief = inp.get("brief") or {}
    set_story(brief)
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
    for k, a in enumerate(assets):
        if a is None or not a.local_path or not os.path.isfile(a.local_path):
            continue
        g = global_of[k]
        ext = os.path.splitext(a.local_path)[1] or ".bin"
        obj = f"projects/{project_id}/parts/{parent}/{g:04d}{ext}"
        try:
            url = storage.broker_upload(a.local_path, bucket, obj, project_id, parent,
                                        read_ttl=60 * 60 * 6)
        except Exception as e:  # noqa: BLE001 - the parent re-sources it
            print(f"[part] scene {g + 1}: upload failed ({e})", flush=True)
            continue
        d = asdict(a)
        d.pop("local_path", None)
        d.update(remote_url=url, storage_path=obj)
        out[str(g)] = d
    return {"assets": out, "delivered": len(out), "asked": len(jobs)}
