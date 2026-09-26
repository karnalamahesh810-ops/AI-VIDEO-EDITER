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
import subprocess
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
        for unit in self.units[1:]:
            jid = _submit(self.payload(unit))
            if jid:
                pending[jid] = unit
            else:
                self.failed.append(unit)
        self.live = len(pending)
        total = sum(u.get("weight", 1) for u in self.units)
        print(f"[fanout] {label}: {len(pending)} unit(s) on other workers + 1 here", flush=True)
        seen_progress: Dict[str, float] = {}
        while (pending or not self._free()) and time.time() < self.deadline:
            time.sleep(8)
            here = self._collect_here()
            for jid in list(pending):
                st = _status(jid)
                state = st.get("status")
                unit = pending[jid]
                if state == "IN_QUEUE" and self._free():
                    _cancel(jid)
                    del pending[jid]
                    self._start_here(unit)
                    self.stolen += 1
                    print(f"[fanout] {label}: unit {jid[:8]} never started; doing it here", flush=True)
                    continue
                if state == "IN_PROGRESS" and isinstance(st.get("output"), dict):
                    seen_progress[jid] = self.progress(unit, st["output"])
                if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
                    del pending[jid]
                    out = st.get("output")
                    if state != "COMPLETED" or not isinstance(out, dict) or not self.accept(unit, out, True):
                        print(f"[fanout] {label}: unit {jid[:8]} {state}: "
                              f"{str(out.get('error') if isinstance(out, dict) else out)[:160]}", flush=True)
                        self.failed.append(unit)
                    seen_progress[jid] = unit.get("weight", 1)
            busy = len(pending) + (0 if self._free() else 1)
            self.report(min(total, sum(seen_progress.values()) + here), total, busy)
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


def source(jobs: List[dict], sequences: List[dict], brief: dict, *, parent_job_id: str,
           project_id: str, bucket: str, work: str, flags: dict,
           report: Callable, local: Callable[[List[dict], set], List[Optional[media.MediaAsset]]]
           ) -> List[Optional[media.MediaAsset]]:
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
    stats: Dict[str, int] = {"parts": 0, "stolen_back": 0, "failed_parts": 0, "rounds": 0}

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
            ext = os.path.splitext((d.get("storage_path") or "x.bin"))[1] or ".bin"
            path = os.path.join(work, f"part_{i:04d}{ext}")
            try:
                storage.download(d.get("remote_url") or "", path)
                results[i] = _asset_from(d, path)
            except Exception as e:  # noqa: BLE001 - redone in the next round
                print(f"[fanout] scene {i + 1}: download failed ({e})", flush=True)
        return True

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
                               "image_budget": p["image_budget"], **flags},
            local=lambda p: local(p["jobs"], set(exclude)),
            accept=fetch,
            progress=lambda p, o: min(p["weight"], float(o.get("done") or 0)),
            report=show,
            deadline=time.time() + max(config.FANOUT_TIMEOUT_SECONDS, 6.0 * len(round_jobs)))
        failed = units.run(label)
        stats["parts"] += len(parts)
        stats["stolen_back"] += units.stolen
        stats["failed_parts"] += len(failed)
        stats["rounds"] += 1

    report(f"Sourcing in parallel: 0/{total_scenes} scenes", 30, done=0, total=total_scenes)
    run_round(jobs, sequences, set(), 30, 55, "Sourced", first=True)

    seen: Dict[str, int] = {}
    dups = _dedupe(results, jobs, seen)
    empty = [j for j in jobs if results[j["index"]] is None and j not in dups]
    todo = empty + dups
    stats["cross_part_repeats"] = len(dups)
    if len(todo) >= config.FANOUT_REFILL_MIN:
        print(f"[fanout] round 2 across workers: {len(todo)} scene(s) "
              f"({len(empty)} empty, {len(dups)} repeats)", flush=True)
        run_round(todo, [], set(seen), 55, 60, "Filling gaps:")
        stats["round2_repeats"] = len(_dedupe(results, jobs, seen))
        todo = [j for j in jobs if results[j["index"]] is None]
    if todo:
        print(f"[fanout] sourcing {len(todo)} last scene(s) here", flush=True)
        report(f"Filling the last {len(todo)} scenes", 60)
        got = local(todo, set(seen))
        for j, a in zip(sorted(todo, key=lambda j: j["index"]), got):
            results[j["index"]] = a
    stats["sourced_by_parent_last"] = len(todo)
    media.LAST_STATS["fanout"] = stats
    return results


def render_enabled(doc: dict, project_id: str) -> bool:
    seconds = doc.get("durationInFrames", 0) / max(1, doc.get("fps", 30))
    return bool(config.FANOUT_RENDER and seconds >= config.FANOUT_RENDER_MIN_SECONDS
                and config.FANOUT_API_KEY and config.FANOUT_ENDPOINT_ID
                and project_id and storage.broker_enabled())


def chunks(total_frames: int, fps: int, parts: int) -> List[tuple]:
    """Frame ranges (inclusive) of about equal length, at most `parts` of them."""
    want = max(1, min(parts, math.ceil(total_frames / (fps * config.FANOUT_RENDER_CHUNK_SECONDS))))
    size = math.ceil(total_frames / want)
    return [(a, min(total_frames, a + size) - 1) for a in range(0, total_frames, size)]


def render(doc: dict, out_path: str, *, parent_job_id: str, project_id: str, bucket: str,
           work: str, report: Callable, render_local: Callable) -> str:
    """
    Render `doc` to `out_path` in frame chunks across the workers.

    Each chunk renders silent; the narration, music and sound effects are
    rendered once here as one audio track, then the chunks are joined without
    re-encoding and the audio laid under them - no seams in the sound.
    `render_local(frames, path, muted, codec)` renders here (frames None =
    the whole timeline).
    """
    fps = int(doc.get("fps") or 30)
    ranges = chunks(int(doc["durationInFrames"]), fps, config.FANOUT_PARTS + 1)
    units = [{"i": i, "frames": fr, "weight": fr[1] - fr[0] + 1,
              "path": os.path.join(work, f"chunk_{i:03d}.mp4")} for i, fr in enumerate(ranges)]

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

    runner = _Units(
        units,
        payload=lambda u: {"action": "render_chunk", "parent_job_id": parent_job_id,
                           "project_id": project_id, "bucket": bucket, "timeline": doc,
                           "frames": list(u["frames"]), "chunk": u["i"]},
        local=lambda u: render_local(u["frames"], u["path"], True, None),
        accept=accept,
        progress=lambda u, o: u["weight"] * float(o.get("frac") or 0),
        report=show,
        deadline=time.time() + config.FANOUT_TIMEOUT_SECONDS + 3 * doc["durationInFrames"] / fps)
    failed = runner.run("render")
    for unit in failed:                         # anything lost is rendered here
        print(f"[fanout] rendering chunk {unit['i']} here", flush=True)
        render_local(unit["frames"], unit["path"], True, None)
    audio = os.path.join(work, "track.aac")
    try:
        render_local(None, audio, False, "aac")
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
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio, "-map", "0:v",
                    "-map", "1:a", "-c", "copy", "-shortest", out_path], check=True)
    media.LAST_STATS["render_fanout"] = {"chunks": len(units), "on_workers": runner.live,
                                         "stolen_back": runner.stolen, "rendered_here_after": len(failed)}
    return out_path


def run_chunk(inp: dict, work: str, render_local: Callable) -> dict:
    """The child side of render(): render one silent chunk, upload it."""
    a, b = inp["frames"]
    i = int(inp.get("chunk", 0))
    path = os.path.join(work, f"chunk_{i:03d}.mp4")
    render_local((a, b), path, True, None)
    obj = f"projects/{inp['project_id']}/parts/{inp['parent_job_id']}/render_{i:03d}.mp4"
    url = storage.broker_upload(path, inp.get("bucket") or config.MEDIA_BUCKET, obj,
                                inp["project_id"], inp["parent_job_id"], read_ttl=60 * 60 * 6)
    return {"url": url, "path": obj, "frames": [a, b]}


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
