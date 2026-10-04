"""
ThumbGenius video worker — RunPod serverless entrypoint.

No intermediate API server. The Lovable app calls a Supabase edge function,
which submits a job here; this worker then writes its own progress, scenes and
final video URL straight back into public.video_projects with the service-role
key. The app simply watches the row.

    narration audio
        -> whisper word timings          transcribe.py
        -> clause beats (VidRush pacing) transcribe.py
        -> shot plan per beat            director.py     (what to show, which graphic)
        -> sourced media per beat        media.py        (yt-dlp CC / real photos / generated)
        -> timeline document             timeline.py     (validated before rendering)
        -> MP4                           render.py       (Remotion)
        -> Supabase Storage              storage.py

A job that brings a `script` and no narration has the narration made first by
the free, self-hosted voice (tts.py; TTS_API_BASE), then runs exactly as above.

Actions
-------
plan    : everything up to the timeline document. Returns it WITHOUT rendering,
          so the user can fix shots before paying for a render.
resource: re-source ONE scene's media and hand the timeline back, so the
          editor can replace a bad shot without re-running the whole plan.
render  : take a timeline document (possibly edited by the user) -> MP4.
build   : plan + render in one call.
health  : cheap readiness probe.
selftest: render the whole template library in-container, upload nothing.
          Proves ffmpeg, Chrome, the asset server, every animation and the
          whisper model all work on this worker — with no credentials set.
pack_build: build or refresh one niche's footage pack on R2 (NASA, Wikimedia
          Commons, Internet Archive, the owner's unused library clips):
          {"niche": "water", "max_clips": 40, "dry_run": false}. See
          src/packbuild.py and scripts/build_pack.py. No project is touched.
restore_media: put back the scene media of a project whose stored files
          vanished, under the links its timeline already has (src/restore.py):
          {"project_id", "timeline" | "timeline_url" | "timeline_key",
          "dry_run", "parts", "plan_jobs"}. The copy a plan's part sourced
          first, else the shot fetched again from its source, then the
          editor's thumbnail and preview; what cannot be restored is listed.
          The timeline and the project row are never changed, nothing is
          deleted or overwritten.
batch   : several videos as one job, built one after another on this machine:
          {"jobs": [<build inputs>], "max_parallel": 1}. Each is a normal build
          through this handler (its own config, costs, events and project row);
          a failed one does not stop the rest. Returns {done, failed,
          total_cost, seconds}. See src/batch.py.

Every action returns {"ok": bool, ...}; errors never raise out of the handler
so the caller always gets a structured result instead of a RunPod stack trace.
"""
import collections
import copy
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from typing import Dict, List

import runpod

from src import (config, costs, director, events, fanout, geocode, library, media, pools,
                 render as renderer, selftest, storage, timeline, transcribe, vision)
from src import intent as scene_intent_mod
from src import templates
from src import ledger, localvision, marks, r2, reframe, styles, upscale
from src import ambience, gapfill, grade, packs, quality, review, voicepolish
from src import brandkit
from src import restore
from src import batch, sources
from src import tts


def _work_dir(job_id: str) -> str:
    d = os.path.join(config.WORK_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


# Pipeline phases, in order, for the app's progress screen. The key is sent as
# `phase` (not `stage`: the app already reads `stage` as the display text).
PHASES = ("narration", "transcribe", "plan", "source", "design", "sound", "render", "upload", "save")
_PHASE_BY_PREFIX = (
    ("Making the narration", "narration"),
    ("Downloading narration", "narration"),
    ("Aligning narration", "transcribe"),
    ("Reading the whole story", "plan"), ("Planning", "plan"),
    ("Sourcing", "source"), ("Sourced", "source"), ("Re-sourcing", "source"),
    ("Replacing", "source"), ("Rechecking", "source"),
    ("Building shot pools", "source"), ("Finding footage", "source"), ("Filling", "source"),
    ("Designing", "design"),
    ("Mixing", "sound"),
    ("Rendering", "render"), ("Replaced", "render"), ("Balancing the sound", "render"),
    ("Uploading", "upload"),
    ("Saving", "save"),
)
# The app's agent cards (GoMotion-style progress screen).
_AGENT_BY_PHASE = {"narration": "voice", "transcribe": "voice", "plan": "director", "source": "assets",
                   "design": "motion", "sound": "sound", "render": "editor", "upload": "editor",
                   "save": "editor"}


class _LogTail:
    """
    Keeps the last lines this worker printed, so a job's status can say what
    it is doing right now. RunPod has no API for worker logs; without this a
    job that sits at "Finding footage" for ten minutes cannot be told apart
    from one that is stuck. Proxies are only ever logged by index.
    """

    def __init__(self, stream, keep: int = 60):
        self.stream = stream
        self.lines = collections.deque(maxlen=keep)
        self.lock = threading.Lock()
        self.count = 0
        self._buf = ""

    def write(self, s):
        self.stream.write(s)
        with self.lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.rstrip()
                if line:
                    self.lines.append(f"{time.strftime('%H:%M:%S')} {line[:220]}")
                    self.count += 1

    def flush(self):
        self.stream.flush()

    def tail(self, n: int = 30):
        with self.lock:
            return list(self.lines)[-n:]

    def __getattr__(self, name):
        return getattr(self.stream, name)


if not isinstance(sys.stdout, _LogTail):
    sys.stdout = _LogTail(sys.stdout)
LOG_TAIL = sys.stdout


class Reporter:
    """Mirrors progress to RunPod's job status AND to the video_projects row."""

    HEARTBEAT = 20  # seconds between status refreshes while a phase runs
    # Every this many heartbeats the event log goes to the project (live diagnosis).
    FLUSH_EVERY = 3
    # A RunPod serverless job has a status to report to; a pod does not.
    SERVERLESS = bool(os.environ.get("RUNPOD_WEBHOOK_GET_JOB"))

    def __init__(self, project_id: str = "", job: dict = None):
        self.project_id = project_id or ""
        # runpod's progress_update(job, progress) needs the job itself. It
        # used to be called with the progress alone; the TypeError was
        # swallowed below, so no progress ever reached RunPod or the app.
        self.job = job
        self._last = None
        self._started = time.time()
        self._phase = ""
        self._phase_started = time.time()
        self._estimate = None
        self._update = None
        self._pushed_count = -1
        self._stop = threading.Event()
        # Fields every later update carries (the quality check's one-liner).
        self.extra: dict = {}
        if job and job.get("id"):
            threading.Thread(target=self._heartbeat, daemon=True).start()

    def _push(self):
        update = dict(self._update or {})
        update["elapsed"] = round(time.time() - self._started)
        update["recent"] = LOG_TAIL.tail()
        self._pushed_count = LOG_TAIL.count
        if not self.SERVERLESS:
            return
        try:
            runpod.serverless.progress_update(self.job, update)
        except Exception as e:  # noqa: BLE001 — progress must never kill a job
            self.stream_print(f"[worker] progress update failed: {e}")

    @staticmethod
    def stream_print(msg: str):
        print(msg, flush=True)

    def _heartbeat(self):
        # A long phase ("Finding footage by subject") prints plenty but reports
        # nothing; every HEARTBEAT seconds the status gets the fresh log tail.
        beats = 0
        while not self._stop.wait(self.HEARTBEAT):
            beats += 1
            if self._update and LOG_TAIL.count != self._pushed_count:
                self._push()
                if not self.SERVERLESS and self.project_id:
                    # A pod has no RunPod status: the project row carries the tail.
                    storage.patch_project(self.project_id, {"job_progress": self._compact()})
            if beats % self.FLUSH_EVERY == 0:
                try:
                    events.flush(storage.broker_events)
                except Exception:  # noqa: BLE001 - diagnosis must never cost the job
                    pass

    def _compact(self, update: dict = None) -> dict:
        """job_progress for the project row: the update plus the last 8 log lines, short."""
        src = update if update is not None else (self._update or {})
        out = {k: v for k, v in src.items() if k != "recent"}
        out["recent"] = [str(l)[:160] for l in LOG_TAIL.tail()[-8:]]
        out["elapsed"] = round(time.time() - self._started)
        return out

    def finish(self):
        self._stop.set()

    def estimate(self, narration_seconds: float) -> None:
        """Expected total minutes for a narration this long (measured on the owner's videos)."""
        n = max(0.0, float(narration_seconds or 0)) / 60.0
        self._estimate = [round(5 + 1.6 * n), round(8 + 2.6 * n)]

    def __call__(self, step: str, progress: int = None, *, done: int = None,
                 total: int = None, **fields):
        phase = next((p for prefix, p in _PHASE_BY_PREFIX if step.startswith(prefix)), "") or self._phase
        if phase != self._phase:
            self._phase, self._phase_started = phase, time.time()
        update = {"status": step, "progress": progress, "phase": phase,
                  "phases": list(PHASES), "agent": _AGENT_BY_PHASE.get(phase, ""),
                  "phase_started_at": round(self._phase_started)}
        if self._estimate:
            update["estimate_minutes"] = list(self._estimate)
        update.update(self.extra)
        if done is not None and total is not None:
            update.update(done=done, total=total)
        print(f"[worker] {step}" + (f" ({progress}%)" if progress is not None else ""),
              flush=True)
        if self.job and self.job.get("id"):
            self._update = update
            self._push()
        if not self.project_id:
            return
        # A 600-scene job would otherwise write the same row hundreds of times.
        if (step, progress) == self._last:
            return
        self._last = (step, progress)
        payload = {"current_step": step, **fields}
        if progress is not None:
            payload["progress"] = progress
        # The app's agent screen reads job_progress (serverless: from RunPod's
        # status; a pod has none, so the worker writes it).
        payload["job_progress"] = self._compact(update)
        storage.patch_project(self.project_id, payload)


def _machine() -> dict:
    """
    What this worker can actually use, as the container sees it.

    os.cpu_count() reports the HOST; the cgroup files say what this container
    is allowed. Render concurrency and the thread-spawn crash both depend on
    the real limits, not the host's.
    """
    def read(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            return ""
    info = {"hostCpus": os.cpu_count()}
    try:
        info["usableCpus"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    quota = read("/sys/fs/cgroup/cpu.max").split()
    if len(quota) == 2 and quota[0] != "max":
        info["cgroupCpus"] = round(int(quota[0]) / int(quota[1]), 2)
    mem = read("/sys/fs/cgroup/memory.max")
    if mem.isdigit():
        info["memoryGb"] = round(int(mem) / 2 ** 30, 1)
    for line in read("/proc/meminfo").splitlines()[:1]:
        info["hostMemoryGb"] = round(int(line.split()[1]) / 2 ** 20, 1)
    info["pidsMax"] = (read("/sys/fs/cgroup/pids.max")
                       or read("/sys/fs/cgroup/pids/pids.max") or None)
    info["pidsCurrent"] = (read("/sys/fs/cgroup/pids.current")
                           or read("/sys/fs/cgroup/pids/pids.current") or None)
    mem1 = read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if mem1.isdigit() and int(mem1) < 2 ** 50:
        info["memoryGb"] = round(int(mem1) / 2 ** 30, 1)
    try:
        import resource
        info["nprocLimit"] = resource.getrlimit(resource.RLIMIT_NPROC)[0]
    except Exception:  # noqa: BLE001
        pass
    info["threadsMax"] = read("/proc/sys/kernel/threads-max") or None
    info["gpu"] = bool(os.path.exists("/dev/nvidia0"))
    return info


def _thumbnail(path: str, work: str, scene_id: str) -> str:
    """A 320px JPEG of the scene for the editor's filmstrip, or "" on failure."""
    out = os.path.join(work, f"thumb_{scene_id}.jpg")
    seek = []
    if os.path.splitext(path)[1].lower() in (".mp4", ".webm", ".mov", ".m4v", ".mkv"):
        dur = renderer.probe_duration(path) or 0
        seek = ["-ss", f"{dur / 2:.2f}"]
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *seek, "-i", path, "-frames:v", "1",
                        "-vf", "scale=320:-2", "-q:v", "5", out],
                       capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out if os.path.isfile(out) else ""


_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".mkv")


def _preview_proxy(path: str, work: str, scene_id: str) -> str:
    """
    A light copy of a video clip for the editor's live preview, or "".

    The editor's player streamed every scene's full source clip (up to 1080p,
    whatever bitrate the upload had) the moment the scene started, so each cut
    waited on a fresh multi-megabyte download and the preview buffered. This
    is 640px wide, silent (the narration is its own track), with the index at
    the front (+faststart) so it starts on the first bytes, and a keyframe
    every half second so scrubbing lands instantly. The render always uses the
    full clip.
    """
    if os.path.splitext(path)[1].lower() not in _VIDEO_EXTS:
        return ""
    out = os.path.join(work, f"preview_{scene_id}.mp4")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-an",
                        # 720p at CRF 24: the owner judged footage quality from
                        # these (they were 640x360 at ~300 kbps while the clips
                        # themselves were 1080p). Still small enough to scrub.
                        "-vf", f"scale='min({config.PREVIEW_WIDTH},iw)':-2", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", str(config.PREVIEW_CRF), "-g", "15",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                       capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""


# Media links in a saved timeline. The editor can sit on a project for weeks;
# the render step re-signs from media.storage regardless.
_MEDIA_LINK_TTL = 60 * 60 * 24 * 30


def _kie_credit() -> float:
    """
    The Kie account balance, or +inf when it cannot be read (not Kie, no key,
    network hiccup) - an unknown balance never blocks a job.
    """
    base = (config.DIRECTOR_API_BASE or "") + (config.VISION_API_BASE or "")
    key = config.DIRECTOR_API_KEY or config.VISION_API_KEY
    if "kie.ai" not in base or not key:
        return float("inf")
    try:
        import requests
        r = requests.get("https://api.kie.ai/api/v1/chat/credit",
                         headers={"Authorization": f"Bearer {key}"}, timeout=15)
        return float(r.json().get("data"))
    except Exception:  # noqa: BLE001
        return float("inf")


def _require_ai_credit() -> None:
    """
    Refuse to start a sourcing job with an empty AI account.

    With no Kie credit the story director falls back to rules and vision is
    off, so nothing checks what the clips show: a real 95 s job came out as a
    lyric video, a singer, strangers' weddings and glitch art - ten minutes
    spent producing a video nobody would publish. Failing in a second with
    the reason is better. REQUIRE_AI_CREDIT=0 turns this off.
    """
    if not config.REQUIRE_AI_CREDIT:
        return
    credit = _kie_credit()
    if credit < config.MIN_AI_CREDIT:
        raise RuntimeError(
            f"The AI account (Kie) is out of credit (balance {credit:.2f}). Without it the "
            "director cannot read the story and nothing checks the clips, so the video "
            "would be random footage. Top up at kie.ai, then run this again.")


def _require_youtube() -> None:
    """
    Refuse to start when no connection this worker has can download from YouTube.

    A blocked IP still returns search results, so a job used to run to the end
    with every download refused and the empty scenes filled with paid AI
    images: two real videos came out with 0 YouTube clips out of 51 scenes.
    Checked before any AI is spent. REQUIRE_YOUTUBE=0 turns this off.
    """
    if not config.REQUIRE_YOUTUBE:
        return
    routes = media.probe_youtube()
    if not any(r["ok"] for r in routes):
        routes = media.probe_youtube()          # one retry: a single slow answer is not a block
    ok = [r["route"] for r in routes if r["ok"]]
    print(f"[worker] YouTube reachable via: {', '.join(ok) or 'nothing'}", flush=True)
    if not ok:
        detail = "; ".join(f"{r['route']}: {r['why'] or 'failed'}" for r in routes)
        raise RuntimeError(
            "YouTube is refusing every connection this worker has (" + detail + "). "
            "Nothing was spent. Without YouTube the video would be AI images, so the job "
            "stopped. Add working US proxies (YTDLP_PROXY) and run it again.")


_STORAGE_REFS = ("storage", "thumbStorage", "previewStorage")


def _scene_media_on_r2() -> bool:
    """Scene files go to Cloudflare R2 under a public, link-only name: R2_SCENE_MEDIA, and always when
    the worker stores in Cloudflare only (R2_ONLY) - with R2 configured."""
    return bool((config.R2_SCENE_MEDIA or storage.r2_only()) and r2.enabled())


def _put_scene_file(local: str, obj: str, bucket: str, project_id: str, job_id: str) -> tuple:
    """
    (url, storage ref or None) for one scene file. Cloudflare R2 first
    (R2_SCENE_MEDIA, bucket R2_BUCKET under a link-only name): a public link
    that never expires, so the timeline carries no storage reference and
    neither the app nor the render re-signs it - and the app's storage stays
    small. The app's storage (a signed link plus the reference it is
    re-signed from) when R2 is off or refuses.

    What this returns is SAVED in the timeline (scene_data) and the library,
    so with no storage reference it must be a link that never expires: the
    public R2 link (r2.upload), never a presigned one. Cloudflare-only
    (R2_ONLY) with R2_SCENE_MEDIA off used to return storage.broker_upload's
    presigned R2 link here - it dies after 7 days at most and nothing could
    re-sign it, so every scene of a saved video would have gone dark.
    """
    if _scene_media_on_r2():
        try:
            return r2.upload(local, r2.tokened(obj), content_type=r2.content_type(local),
                             deadline=time.time() + config.R2_MEDIA_UPLOAD_SECONDS,
                             cache_control=r2.IMMUTABLE), None
        except Exception as e:  # noqa: BLE001 - the app's storage below
            if storage.r2_only():
                raise           # Cloudflare only: never fall back to the app's storage
            print(f"[worker] R2 upload of {os.path.basename(obj)} failed, using app storage: "
                  f"{type(e).__name__}: {str(e)[:120]}", flush=True)
    ref = {"bucket": bucket, "path": obj}
    if storage.broker_enabled():
        return storage.broker_upload(local, bucket, obj, project_id, job_id, read_ttl=_MEDIA_LINK_TTL), ref
    storage.upload_to_supabase(local, obj, bucket=bucket)
    return storage.signed_url(obj, bucket=bucket, expires_in=_MEDIA_LINK_TTL), ref


def publish_media(doc: dict, project_id: str, bucket: str, report: Reporter,
                  job_id: str = "", band: tuple = (66, 68)) -> int:
    """
    Upload sourced media (Cloudflare R2, or the app's storage) and point the
    timeline at it (_put_scene_file).

    Needed because `plan` and `render` are separate serverless jobs. The work
    directory is wiped when a job ends, and the next job may land on a
    different worker entirely, so a timeline holding local paths is already
    broken by the time the user presses Render. Publishing makes the document
    self-contained — and is what lets the editor show each scene's media at
    all.

    Skipped for `build`, which renders in the same job and would be paying for
    storage it never reads. Failures are logged per asset, not fatal: a scene
    that fails to publish keeps its local path and is flagged for review.
    """
    published: Dict[str, tuple] = {}
    failures = 0
    scenes = doc.get("scenes", [])
    lo, hi = band
    last_pct = [None]
    work = os.path.dirname(next((s["media"]["url"] for s in scenes
                                 if os.path.isfile((s.get("media") or {}).get("url") or "")),
                                "")) or config.WORK_DIR

    def put(local: str, obj: str) -> tuple:
        return _put_scene_file(local, obj, bucket, project_id, job_id)

    # One job per distinct file, run 8 at a time: every clip is an upload, a
    # thumbnail and a re-encoded preview copy, and doing 23 of those one after
    # another made "Saving clips for editing" take 320 s of a 600 s job.
    first_scene: Dict[str, dict] = {}
    for scene in scenes:
        path = (scene.get("media") or {}).get("url") or ""
        if path and os.path.isfile(path) and path not in first_scene:
            first_scene[path] = scene

    def publish_one(path: str, scene: dict):
        ext = os.path.splitext(path)[1] or ".bin"
        obj = f"projects/{project_id}/media/{scene['id']}{ext}"
        try:
            url, ref = put(path, obj)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not publish {obj}: {e}", flush=True)
            return None
        # A signed URL expires; the app re-signs from `storage` before a
        # render. An R2 link does not expire and carries no reference.
        fields = {"url": url, "storage": ref}
        thumb = _thumbnail(path, work, scene["id"])
        if thumb:
            tobj = f"projects/{project_id}/thumbs/{scene['id']}.jpg"
            try:
                fields["thumbnail"], fields["thumbStorage"] = put(thumb, tobj)
            except Exception as e:  # noqa: BLE001 — a missing thumb is cosmetic
                print(f"[worker] could not save thumbnail {tobj}: {e}", flush=True)
        preview = _preview_proxy(path, work, scene["id"])
        if preview:
            pobj = f"projects/{project_id}/preview/{scene['id']}.mp4"
            try:
                fields["previewUrl"], fields["previewStorage"] = put(preview, pobj)
            except Exception as e:  # noqa: BLE001 — the editor falls back to the full clip
                print(f"[worker] could not save preview {pobj}: {e}", flush=True)
        return url, {k: v for k, v in fields.items() if v is not None}

    total = len(first_scene)
    report(f"Saving clips for editing 0/{total}", lo, done=0, total=total)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(publish_one, path, scene): path
                   for path, scene in first_scene.items()}
        for n, fut in enumerate(as_completed(futures), 1):
            got = fut.result()
            if got:
                published[futures[fut]] = got
            pct = lo + int((hi - lo) * n / max(total, 1))
            if pct != last_pct[0]:
                last_pct[0] = pct
                report(f"Saving clips for editing {n}/{total}", pct, done=n, total=total)

    for scene in scenes:
        media = scene.get("media") or {}
        path = media.get("url") or ""
        if not path or not os.path.isfile(path):
            continue
        if path in published:
            # A reference left from an earlier save would make the app re-sign
            # that old file over the new link.
            for key in _STORAGE_REFS:
                media.pop(key, None)
            media.update(published[path][1])
        else:
            scene["reviewRequired"] = True
            scene["reviewReason"] = "Media could not be saved; re-source before rendering"
            failures += 1
    doc["meta"]["publishedMedia"] = len(published)
    if failures:
        doc["meta"]["warnings"].append(
            f"{failures} scene(s) could not be saved to storage.")
    return len(published)


def _source_with_pools(jobs: list, work: str, *, require_cc: bool, exclude: set, source_rest,
                       report=None, library=None):
    """
    Everything one worker does for its lines: subject pools first, per-scene
    sourcing for what the pools did not cover (`source_rest(rest, taken)`),
    then the pools' spare moments for lines still empty or repeated - or
    breaking a variety rule (media.variety_violations: the owner's review,
    2026-09-30), while this worker still holds its pools' spares; the parent
    judges the whole video again after every part is in.
    Returns (assets aligned to the jobs sorted by index, pooled).
    """
    ordered = sorted(jobs, key=lambda j: j["index"])
    pooled: dict = {}
    if config.SUBJECT_POOLS and jobs:
        pooled = pools.source_by_subject(jobs, work, require_cc=require_cc, report=report, library=library)
        print(f"[worker] subject pools covered {len(pooled)}/{len(jobs)} lines", flush=True)
    taken = set(exclude or ()) | {a.identity for a in pooled.values()} | pools.video_ids(pooled)
    rest = [j for j in ordered if j["index"] not in pooled]
    by_index = dict(pooled)
    if rest:
        # Per-scene sourcing indexes its results by job["index"], so the lines
        # it gets must be numbered 0..n-1: a part handed [0, 2, 3] crashed with
        # IndexError and every part fell back to the parent (a 107-minute job).
        dense = [dict(j, index=k) for k, j in enumerate(rest)]
        got = source_rest(dense, taken) or []
        for j, a in zip(rest, got):
            by_index[j["index"]] = a
    if pooled:
        seen: set = set()
        redo = []
        for j in ordered:
            a = by_index.get(j["index"])
            if a is None or a.identity in seen:
                redo.append(j["index"])
            else:
                seen.add(a.identity)
        # A still in the hook keeps its place until the parent's footage retry.
        redo += [i for i, (_why, kind) in media.variety_violations(ordered, by_index).items()
                 if kind != "upgrade" and i not in redo]
        redo.sort()
        if redo:
            extra = pools.fill_from_reserve(jobs, redo, work, require_cc=require_cc, assets=by_index)
            by_index.update(extra)
            print(f"[worker] {len(extra)}/{len(redo)} empty or repeated line(s) filled from "
                  "spare pool moments", flush=True)
    return [by_index.get(j["index"]) for j in ordered], pooled


def _bind_split_images(doc: dict, work: str, put) -> int:
    """
    Contrasts told with pictures (the owner: a picture left, a picture right,
    a line in the middle). Every two-label overlay (label-boxes with two items)
    gets a photo searched for each side - "<subject> <label>" - and becomes a
    left/right split (ProSplit). Both photos or neither: a contrast with one
    picture keeps its label pills. `put(local, object)` uploads a file and
    returns its link. Time boxed by SPLIT_IMAGES_SECONDS. Returns how many.
    """
    if not config.SPLIT_IMAGES:
        return 0
    from concurrent.futures import ThreadPoolExecutor, wait as _wait
    import requests as _rq
    scenes = doc.get("scenes") or []

    def subject_at(frame: int) -> str:
        for sc in scenes:
            if sc["startFrame"] <= frame < sc["startFrame"] + sc["durationInFrames"]:
                return ((sc.get("semanticMetadata") or {}).get("subject") or "").strip()
        return ""

    targets = []
    for n, ov in enumerate(doc.get("overlays") or []):
        labels = [(it.get("label") or it.get("text") or "").strip() for it in (ov.get("items") or [])]
        labels = [l for l in labels if l]
        if ov.get("type") == "label-boxes" and len(labels) == 2 and not ov.get("media"):
            targets.append((n, ov, labels, subject_at(int(ov.get("startFrame") or 0))))
    if not targets:
        return 0

    # The address each picture came from, kept on the look's media as sourceUrl:
    # a restore of a project whose files vanished (src/restore.py) can fetch
    # it again; the two deleted projects' contrast pictures had no record.
    picked: Dict[str, str] = {}

    def fetch(query: str, dest: str) -> str:
        from PIL import Image
        try:
            found = media.search_web_images(query, 6) or []
        except Exception:  # noqa: BLE001
            return ""
        for a in found:
            url = getattr(a, "url", "") or ""
            if not url.startswith("http"):
                continue
            try:
                r = _rq.get(url, timeout=15, headers={"User-Agent": config.USER_AGENT})
                if r.status_code != 200 or len(r.content) > 15_000_000:
                    continue
                raw = dest + ".src"
                with open(raw, "wb") as fh:
                    fh.write(r.content)
                im = Image.open(raw).convert("RGB")
                if min(im.size) < 360:
                    continue
                im.save(dest, "JPEG", quality=88)
                picked[dest] = url
                return dest
            except Exception:  # noqa: BLE001 - try the next result
                continue
        return ""

    jobs = {}
    pool = ThreadPoolExecutor(max_workers=8)
    for n, ov, labels, subject in targets:
        for side, label in enumerate(labels):
            q = f"{subject} {label}".strip()
            dest = os.path.join(work, f"split_{n}_{side}.jpg")
            jobs[pool.submit(fetch, q, dest)] = (n, side)
    done, _late = _wait(jobs, timeout=config.SPLIT_IMAGES_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)
    got = {}
    for f in done:
        try:
            path = f.result()
        except Exception:  # noqa: BLE001
            path = ""
        if path:
            got[jobs[f]] = path
    made = 0
    for n, ov, labels, subject in targets:
        a, b = got.get((n, 0)), got.get((n, 1))
        if not (a and b):
            continue
        try:
            urls = [put(p, f"split/{n:03d}_{i}.jpg") for i, p in enumerate((a, b))]
        except Exception as e:  # noqa: BLE001 - the label pills stay
            print(f"[worker] split images for overlay {n}: upload failed ({type(e).__name__})", flush=True)
            continue
        ov["type"] = "split"
        ov["template"] = "CMP_SPLIT_V1"
        ov["items"] = [{"label": labels[0]}, {"label": labels[1]}]
        ov["media"] = [{"type": "image", "url": u, "source": "web", **({"sourceUrl": picked[p]} if picked.get(p) else {})}
                       for u, p in zip(urls, (a, b))]
        made += 1
    if made:
        print(f"[worker] {made} contrast(s) shown as a split of two photos", flush=True)
    return made


def _bind_overlay_photos(doc: dict, work: str, put) -> int:
    """
    The case-file looks that show a picture the footage does not have: a
    photo window of the place or thing named, riding on a weak clip
    (PHOTO_PIP_V1), and the framed photo beside a map pin (MAP_PHOTO_PIN_V1).
    One web photo is searched for each ("<subject>" or the pinned place,
    plus the story's subject when it adds context), checked for size,
    uploaded and bound as overlay.media. A photo window that finds nothing is
    removed (an empty window is worse than none); a map without its photo
    stays a plain pin. Time boxed by SPLIT_IMAGES_SECONDS. Returns how many.
    """
    if not config.SPLIT_IMAGES:
        return 0
    from concurrent.futures import ThreadPoolExecutor, wait as _wait
    import requests as _rq
    overlays = doc.get("overlays") or []
    story = str(((doc.get("meta") or {}).get("planner") or {}).get("subject") or "").strip() \
        if isinstance((doc.get("meta") or {}).get("planner"), dict) else ""
    targets = []
    for n, ov in enumerate(overlays):
        if ov.get("media"):
            continue
        tpl = templates.get(ov.get("template") or "") or {}
        if ov.get("template") == "PHOTO_PIP_V1" or (ov.get("type") == "photo-card" and ov.get("variant") == "pip") \
                or ("subject-photo" in (tpl.get("cues") or []) and "still" in (tpl.get("tags") or [])):
            q = str(ov.get("text") or "").strip()
        elif ov.get("type") == "map" and ov.get("variant") == "satellite-photo":
            locs = ov.get("locations") or []
            q = str((locs[0] or {}).get("label") or "").split(",")[0].strip() if locs else ""
        else:
            continue
        if len(q) < 3:
            continue
        if story and story.lower() not in q.lower() and len(q.split()) < 3:
            q = f"{q} {story}"
        targets.append((n, ov, q))
    if not targets:
        return 0

    # The address each picture came from, kept on the look's media as sourceUrl:
    # a restore of a project whose files vanished (src/restore.py) can fetch
    # it again; the two deleted projects' contrast pictures had no record.
    picked: Dict[str, str] = {}

    def fetch(query: str, dest: str) -> str:
        from PIL import Image
        try:
            found = media.search_web_images(query, 6) or []
        except Exception:  # noqa: BLE001
            return ""
        for a in found:
            url = getattr(a, "url", "") or ""
            if not url.startswith("http"):
                continue
            try:
                r = _rq.get(url, timeout=15, headers={"User-Agent": config.USER_AGENT})
                if r.status_code != 200 or len(r.content) > 15_000_000:
                    continue
                raw = dest + ".src"
                with open(raw, "wb") as fh:
                    fh.write(r.content)
                im = Image.open(raw).convert("RGB")
                if min(im.size) < 360:
                    continue
                im.save(dest, "JPEG", quality=88)
                picked[dest] = url
                return dest
            except Exception:  # noqa: BLE001 - try the next result
                continue
        return ""

    pool = ThreadPoolExecutor(max_workers=8)
    jobs = {pool.submit(fetch, q, os.path.join(work, f"ovphoto_{n}.jpg")): n for n, _ov, q in targets}
    done, _late = _wait(jobs, timeout=config.SPLIT_IMAGES_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)
    got = {}
    for f in done:
        try:
            path = f.result()
        except Exception:  # noqa: BLE001
            path = ""
        if path:
            got[jobs[f]] = path
    made, drop = 0, set()
    for n, ov, _q in targets:
        path = got.get(n)
        url = ""
        if path:
            try:
                url = put(path, f"overlay/{n:03d}.jpg")
            except Exception as e:  # noqa: BLE001
                print(f"[worker] overlay photo {n}: upload failed ({type(e).__name__})", flush=True)
        if url:
            ov["media"] = [{"type": "image", "url": url, "source": "web",
                            **({"sourceUrl": picked[path]} if picked.get(path) else {})}]
            made += 1
        elif ov.get("type") != "map":
            drop.add(n)
    if drop:
        doc["overlays"] = [ov for i, ov in enumerate(overlays) if i not in drop]
    if made or drop:
        print(f"[worker] overlay photos: {made} bound, {len(drop)} photo window(s) dropped (nothing found)", flush=True)
    return made


def _fill_missing_media(doc: dict) -> int:
    """
    Give every scene something to render, never another scene's clip.

    `build` sources and renders in one job with nothing shown to the user in
    between, so a single scene nothing could be found for used to fail
    `timeline.validate(require_media=True)` inside do_render and destroy the
    whole job: the exception unwinds past the point where the work directory
    is deleted, taking every other scene's already-downloaded clip with it.
    Twenty minutes of sourcing was lost over one hard beat.

    This used to borrow another scene's shot ("a repeat is better than
    black"). The owner's rules (2026-10-01) - never reuse a clip within a
    video, never leave a scene empty - turned that round: an empty scene gets
    the planner's own graphic for its line (a number, money, a map), else the
    neighbouring shot held over it while its clip still covers the longer
    scene (the scenes merge, src/gapfill.hold_or_animate), else its line as a
    text card on the quiet background. Returns how many scenes were patched.
    """
    got = gapfill.hold_or_animate(doc, label="before the render")
    return int(got.get("graphic", 0)) + int(got.get("held", 0)) + int(got.get("card", 0))


def _store_narration(local: str, ext: str, inp: dict) -> str:
    """
    The made narration where the app, the editor and every later render can
    read it; "" when this run has no storage at all (a local run keeps the
    file on its disk).

    Cloudflare R2 first, under a link-only name that never expires - a
    timeline can sit in the editor for weeks and its narration link must
    still open. The app's storage (a signed link, 30 days) only where R2 is
    not configured; with R2_ONLY an R2 failure is an error, never a quiet
    fallback (the owner's storage is Cloudflare only since 2026-10-04).
    """
    project_id, job_id = inp.get("project_id") or "", inp.get("_job_id") or ""
    folder = f"projects/{project_id}" if project_id else f"jobs/{job_id or uuid.uuid4().hex}"
    obj = f"{folder}/audio/narration{ext or '.mp3'}"
    if r2.enabled():
        try:
            return r2.upload(local, r2.tokened(obj), content_type=r2.content_type(obj, "audio/mpeg"),
                             deadline=time.time() + 2 * config.R2_MEDIA_UPLOAD_SECONDS,
                             cache_control=r2.IMMUTABLE)
        except Exception as e:  # noqa: BLE001 - the app's storage below, unless Cloudflare only
            if storage.r2_only() or not project_id:
                raise
            print(f"[worker] R2 upload of the narration failed, using app storage: "
                  f"{type(e).__name__}: {str(e)[:120]}", flush=True)
    if project_id and (storage.broker_enabled() or (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)):
        bucket = inp.get("media_bucket") or config.MEDIA_BUCKET
        return storage.broker_upload(local, bucket, obj, project_id, job_id, read_ttl=_MEDIA_LINK_TTL,
                                     deadline=time.time() + 300)
    return ""


def _narration_from_script(inp: dict, work: str, report: Reporter) -> dict:
    """
    Script -> video. The job brought a script and no voice-over (the owner's
    flow, 2026-08-14: "just paste script, select voice over or directly
    upload audio, and make video"), so the narration is made here by the
    free voice (src/tts.py), stored, and put into the input as a normal
    audio_url: everything after this runs as it always did, and whisper
    still measures the real word timings from the audio.

    The file lands where a downloaded narration would (<work>/narration.mp3,
    the name the loudness measurement and the polish look for). The project
    row is told its audio_url, so the app shows and re-sends it like an
    uploaded voice-over; the captions read the words as they were voiced
    (the script without its [directions] and markdown).
    Returns {"url", "path", "report"}; raises tts.TtsError with the reason.
    """
    report("Making the narration (free voice)", 3)
    events.phase("narration")

    def progress(done: int, total: int) -> None:
        report(f"Making the narration (free voice): part {done} of {total}", 3, done=done, total=total)
    made = tts.synthesize(inp["script"], os.path.join(work, "tts"), opts=tts.options(inp), on_progress=progress)
    local = os.path.join(work, "narration.mp3")
    shutil.move(made["path"], local)
    info = {"source": "tts", **{k: v for k, v in made.items() if k not in ("path", "text")}}
    url = _store_narration(local, os.path.splitext(made["path"])[1], inp)
    if url:
        inp["audio_url"] = url
        if inp.get("project_id"):
            storage.patch_project(inp["project_id"], {"audio_url": url})
    else:
        inp["audio_path"] = local
        print("[worker] no storage configured: the narration stays on this disk", flush=True)
    inp["script"] = made["text"]
    events.emit("narration", "made", provider=str(made.get("model") or ""),
                data={k: info.get(k) for k in ("seconds", "chars", "parts", "voice", "cloned", "lufs",
                                               "retries", "gpuSeconds", "tookSeconds")})
    return {"url": url or local, "path": local, "report": info}


def _narration_fields(doc: dict) -> dict:
    """For the caller: the narration this job made from the script, and the link it is kept under."""
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    if not isinstance(meta.get("narration"), dict):
        return {}
    src = str(meta.get("audioSource") or "")
    return {"narration": meta["narration"], **({"audio_url": src} if src.startswith("http") else {})}


def do_plan(inp: dict, work: str, report: Reporter) -> dict:
    raw_audio = inp.get("audio_url") or inp.get("audio_path")
    made = None
    if not raw_audio and tts.configured() and tts.wanted(inp):
        # A script and no voice-over: the free voice makes the narration first.
        # Without TTS_API_BASE nothing here runs: such a job fails exactly as
        # it always did ("audio_url is required" below).
        made = _narration_from_script(inp, work, report)
        raw_audio = made["url"]
    if not raw_audio:
        raise ValueError("audio_url is required (upload a voiceover or generate TTS first)")

    if not made:
        report("Downloading narration", 4)
        events.phase("narration")
    if made:
        # Made on this disk a moment ago: nothing to download.
        audio_src, audio_path = made["url"], made["path"]
    elif str(raw_audio).startswith("bench://"):
        # A benchmark narration baked into the image (bench/audio/<case>.mp3),
        # so the seven-script benchmark needs no upload and no credentials.
        case = "".join(ch for ch in str(raw_audio)[8:] if ch.isalnum() or ch in "_-")
        bench_src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "bench", "audio", f"{case}.mp3")
        if not os.path.isfile(bench_src):
            raise ValueError(f"unknown benchmark case '{case}'")
        audio_src = str(raw_audio)
        audio_path = shutil.copy(bench_src, os.path.join(work, "narration.mp3"))
    else:
        # Handles both public URLs and private-bucket object paths.
        audio_src = storage.resolve_audio(raw_audio, bucket=inp.get("audio_bucket", "video-audio"))
        audio_path = storage.download(audio_src, os.path.join(work, "narration.mp3"))
    audio_duration = renderer.probe_duration(audio_path)
    if audio_duration:
        report.estimate(audio_duration)

    report("Aligning narration", 8)
    events.phase("transcribe")
    words = transcribe.transcribe_words(
        audio_path, language=inp.get("language"),
        # 8 -> 13%: the band between download and the planner.
        on_progress=lambda f: report("Aligning narration", 8 + int(5 * f)))
    if not words:
        raise ValueError("no speech detected in the narration audio")
    # Cut where an editor would (src/transcribe.py human_cuts): the visual
    # track runs from frame 0 to the narration's end.
    segments = transcribe.segment_words(words, origin=0.0, until=audio_duration or None)
    if inp.get("script"):
        segments = transcribe.align_to_script(segments, inp["script"])
    if not audio_duration:
        audio_duration = segments[-1].end

    # Read the whole story once: it steers every beat's plan, and after
    # sourcing it steers the recheck of scenes still missing a shot.
    title = director.clean_title(inp.get("title") or inp.get("title_overlay") or "")
    report("Reading the whole story", 13)
    events.phase("plan")
    brief = director.story_brief(segments, title, configured=director.is_configured())
    # Which footage packs this story is about (src/packs.py): a Lake Powell video
    # reads the water and nature shelves, for the fallback ladder's first rung.
    packs.use_job(title=title, brief=brief, style=styles.resolve(inp.get("video_style")))
    # Every vision judgement sees the whole story, not just its own line.
    vision.set_story(brief)
    # And YouTube searches the archive or news channels for this kind of story.
    media.set_story_kind(brief.get("kind", ""))
    # Cut on names (src/mentions.py): a beat is split where it names one of the
    # story's people, so their shot starts WHILE the name is said; the brief's
    # beat numbers follow the new beats.
    from src import mentions
    segments, mention_focus = mentions.prepare(segments, brief)
    # The hook booster (src/hookboost.py, HOOK_BOOST): the opening's long beats cut
    # into 2-3 shots on word boundaries, so every shot is planned, sourced and
    # judged like any beat. Off: the beats as they are.
    from src import hookboost
    segments, mention_focus, boost_info = hookboost.prepare(segments, brief, mention_focus)

    # Shot plan: what is on screen while each beat is spoken.
    geocode.reset_cache()
    director.CHAT_CALLS["n"] = 0   # per-job AI usage count
    shots, planner, warnings = director.plan(
        segments,
        title=title,
        report=report,
        allow_maps=bool(inp.get("maps", True)),
        brief=brief,
    )
    # ...and a beat that opens with a named person shows that person.
    mentions.apply_focus(shots, segments, mention_focus, brief)
    # Out of AI credits already: stop before a single footage search is paid for.
    vision.require_credits()

    # Per-scene overrides from the editor win over the director's choice.
    for key, query in (inp.get("scene_queries") or {}).items():
        try:
            idx = int(key)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(shots) and str(query).strip():
            shots[idx]["query"] = str(query).strip()[:240]

    total = len(segments)
    report(f"Sourcing media for {total} scenes", 22, done=0, total=total)
    events.phase("source")
    media.reset_cache()
    # "start" places each line on the timeline for the variety rules (one
    # video's scenes SAME_VIDEO_GAP_SECONDS apart); every line that starts
    # within HOOK_SECONDS is a hook line (best-of search, no generated image);
    # "place" and "recency" carry the line's own place and "last month first"
    # into the pools and the searches (the owner's review, 2026-09-30).
    jobs = [{"index": i, "query": shot["query"], "seconds": seg.duration,
             "start": round(float(seg.start), 2),
             "visual_type": shot.get("visualType", "footage"),
             "fallbacks": shot.get("fallbacks") or [],
             "prompt": shot.get("prompt") or "",
             "intent": shot.get("intent") or "",
             "subject_type": shot.get("subjectType") or "",
             "subject": shot.get("subject") or "",
             "place": shot.get("linePlace") or "",
             "event_window": shot.get("eventWindow") or "",
             "recency": shot.get("recency") or "",
             "scene_intent": shot.get("sceneIntent") or None,
             "hook": bool(shot.get("hook")) or float(seg.start) < config.HOOK_SECONDS,
             "context": seg.text}
            for i, (seg, shot) in enumerate(zip(segments, shots))]

    last_pct = [22]

    # Plan the video in sequences: runs of lines about one subject and setting,
    # each gathering one pool of shots that the editor call lays out.
    sequences = []
    # Subject pools (src/pools.py) do this job better and cheaper; the old
    # sequence pools on top of them cost ~4 minutes and hundreds of vision
    # calls on a 3-minute video for nothing new.
    if config.SEQUENCE_SOURCING and not config.SUBJECT_POOLS:
        report("Planning sequences", 22)
        sequences = director.plan_sequences(segments, shots, brief)

    def on_pool(done, n):
        # 22% -> 50% while the sequence pools are built.
        pct = 22 + int(28 * done / max(n, 1))
        if pct > last_pct[0] or done == n:
            last_pct[0] = max(last_pct[0], pct)
            report(f"Building shot pools {done}/{n} sequences", last_pct[0], done=done, total=n)

    def on_done(done, n):
        # Up to 65% across sourcing, the longest phase; never backwards after the pools.
        pct = 22 + int(43 * done / max(n, 1))
        if pct > last_pct[0]:
            last_pct[0] = pct
            report(f"Sourced {done}/{n} scenes", pct, done=done, total=n)

    flags = {"allow_youtube": inp.get("allow_youtube"), "allow_stock": inp.get("allow_stock"),
             "require_cc": inp.get("require_cc"), "youtube_only": bool(inp.get("youtube_only"))}
    media.set_youtube_only(flags["youtube_only"])
    if flags["youtube_only"]:
        for j in jobs:
            j["visual_type"] = "footage"

    def local(some_jobs, exclude, seqs=None, progress=True):
        """Source some jobs on this worker; results aligned to their order."""
        ordered_jobs = sorted(some_jobs, key=lambda j: j["index"])
        re_index = {j["index"]: k for k, j in enumerate(ordered_jobs)}
        local_jobs = [dict(j, index=re_index[j["index"]]) for j in ordered_jobs]
        local_seqs = []
        for s in seqs or []:
            beats = [re_index[b] for b in (s.get("beats") or []) if b in re_index]
            if beats:
                local_seqs.append(dict(s, beats=beats))
        return media.source_many(
            local_jobs, work,
            # The per-scene work is mostly waiting on the vision model and the
            # network, and the network side is capped separately (NETWORK_CONCURRENCY).
            workers=int(inp.get("source_workers", config.SOURCE_WORKERS)),
            on_done=on_done if progress else None,
            # A part run on this worker for the fan-out must not report as the
            # whole job: its "Filling ... 65%" made the bar jump backwards.
            on_review=(lambda d, n: report(f"Filling empty or repeated scenes {d}/{n}", 65, done=d, total=n))
            if progress else None,
            # A fan-out unit (progress=False) only finds: no rescue queries and
            # no refill time box, the same rule as a part on another worker
            # (commit 9757e11). Those ran here for minutes after every other
            # part had finished. The final local fill keeps the full machinery.
            rescue=(lambda items: director.rescue_queries(items, story=brief)) if progress else None,
            refill=progress,
            on_recheck=(lambda n: report(f"Rechecking {n} missing scenes against the story", 66))
            if progress else None,
            sequences=local_seqs or None,
            assign=lambda lines, pool: director.assign_shots(lines, pool, story=brief),
            on_pool=on_pool if progress else None,
            exclude=exclude, **{k: v for k, v in flags.items() if k != "youtube_only"})

    project_id = inp.get("project_id") or ""
    # GoMotion's method first: a few long videos per subject, judged once,
    # many moments cut from each (src/pools.py). Whatever the pools do not
    # cover - people, stills, one-off subjects - goes to per-scene sourcing,
    # which is told to leave the pool videos alone.
    pooled: dict = {}
    require_cc = bool(flags["require_cc"] if flags["require_cc"] is not None else config.REQUIRE_CC)
    # Clips kept from earlier videos about the same subjects come first.
    # One sourcing budget for the whole job (every worker shares it).
    from src import ytdlp as _ytdlp_mod
    _ytdlp_mod.set_deadline(time.time() + fanout.source_budget(len(jobs)))
    print(f"[worker] sourcing budget {fanout.source_budget(len(jobs)):.0f}s for {len(jobs)} scenes", flush=True)
    lib = library.Library.load(project_id, (report.job or {}).get("id", ""),
                               inp.get("media_bucket") or config.MEDIA_BUCKET)
    LAST_LIBRARY["lib"] = lib
    # The lines and switches the fallback ladder and the check before
    # publishing need (src/gapfill.py).
    gapfill.remember(jobs, work, library=lib, require_cc=require_cc, youtube_only=flags["youtube_only"])
    # Parts on other workers apply the same per-job config overrides.
    fan_flags = ({**flags, "config": inp["config"]} if isinstance(inp.get("config"), dict) else flags)
    # PACKS_FIRST (off; A/B one job with {"config": {"PACKS_FIRST": true}}): before any
    # search, the lines a niche pack clip fits best (src/packs.py) - never the hook,
    # never a line that needs its exact event or place. Those lines are settled here
    # and left out of every search below.
    packed = packs.first_pass(jobs, work, require_cc=require_cc) if config.PACKS_FIRST else {}
    open_jobs = [j for j in jobs if j["index"] not in packed] if packed else jobs
    pools_wanted = bool(config.SUBJECT_POOLS and inp.get("allow_youtube") is not False)
    in_parts = bool(pools_wanted and config.POOLS_IN_PARTS and open_jobs
                    and fanout.enabled_for(len(open_jobs), project_id))
    if pools_wanted and not in_parts:
        report("Finding footage by subject", 22, done=0, total=len(open_jobs))
        pooled = pools.source_by_subject(open_jobs, work, require_cc=require_cc, report=report, library=lib)
        print(f"[worker] subject pools covered {len(pooled)}/{len(open_jobs)} lines", flush=True)
    pool_stats = dict(media.LAST_STATS.get("pools") or {}, covered_lines=len(pooled))
    if packed:
        pool_stats["packs_first"] = len(packed)
    taken = {a.identity for a in pooled.values()} | pools.video_ids(pooled) | {a.identity for a in packed.values()}
    rest = [j for j in open_jobs if j["index"] not in pooled]
    assets = [pooled.get(j["index"]) or packed.get(j["index"]) for j in jobs]
    if in_parts:
        # Every worker starts now: each part pools its own subjects, sources
        # the rest and fills from its spare moments; the parent's own share
        # goes through the same path with the clip library.
        report("Finding footage on every worker", 22, done=0, total=len(open_jobs))
        pool_stats["in_parts"] = True
        got = fanout.source(
            open_jobs, sequences or [], brief,
            parent_job_id=(report.job or {}).get("id", ""), project_id=project_id,
            bucket=inp.get("media_bucket") or config.MEDIA_BUCKET, work=work,
            flags={**fan_flags, "pools": True}, report=report, exclude=set(),
            local=lambda some, exclude: _source_with_pools(
                some, work, require_cc=require_cc, exclude=exclude,
                source_rest=lambda r, ex: local(r, ex, progress=False), library=lib)[0])
        for j in open_jobs:
            assets[j["index"]] = got[j["index"]] if j["index"] < len(got) else None
    elif rest and fanout.enabled_for(len(rest), project_id):
        # Long video: each part is found, vision-checked and repaired on its
        # own worker at the same time; the parent fills whatever comes back
        # missing and resolves clips two parts both picked.
        got = fanout.source(
            rest, sequences or [], brief,
            parent_job_id=(report.job or {}).get("id", ""), project_id=project_id,
            bucket=inp.get("media_bucket") or config.MEDIA_BUCKET, work=work,
            flags=fan_flags,
            report=report, exclude=taken,
            local=lambda some, exclude: local(some, exclude, progress=False))
        for j in rest:
            assets[j["index"]] = got[j["index"]] if j["index"] < len(got) else None
    elif rest:
        got = local(rest, set(taken), seqs=sequences)
        for j, a in zip(sorted(rest, key=lambda j: j["index"]), got):
            assets[j["index"]] = a
    # Lines the per-scene path left empty, or filled with a clip already on the
    # timeline, get the pools' spare approved moments: real, distinct footage of
    # the story's subjects instead of a black hole or a repeat.
    if pooled:
        seen_ids: set = set()
        redo = []
        for j in jobs:
            a = assets[j["index"]]
            if a is None or a.identity in seen_ids:
                redo.append(j["index"])
            else:
                seen_ids.add(a.identity)
        if redo:
            extra = pools.fill_from_reserve(jobs, redo, work, require_cc=require_cc, assets=assets, library=lib)
            for i, a in extra.items():
                assets[i] = a
            pool_stats["reserve_filled"] = len(extra)
            print(f"[worker] {len(extra)}/{len(redo)} empty or repeated line(s) filled from "
                  "spare pool moments", flush=True)
    # The owner's review of the Texas flood video (2026-09-30): 4 of its first
    # 5 scenes were AI illustrations, one drone video played 4 times in the
    # first minute and 28 photo scenes showed 15 photos. Every scene that
    # breaks a variety rule (media.variety_violations: a video past
    # MAX_MOMENTS_PER_VIDEO scenes or within SAME_VIDEO_GAP_SECONDS of itself,
    # a photo or generated image shown again, a generated image or a still in
    # the hook) is cleared here and goes through the pools' spare moments and
    # the rescue pass like an empty scene - a hook scene for footage only.
    # What nothing replaced comes back where the rules allow
    # (media.restore_held) before any shot is reused.
    results_by_index = [None] * (max(j["index"] for j in jobs) + 1)
    for j in jobs:
        results_by_index[j["index"]] = assets[j["index"]]
    held = media.hold_violations(jobs, results_by_index)
    if held and pools_wanted:
        extra = pools.fill_from_reserve(jobs, sorted(held), work, require_cc=require_cc,
                                        assets=results_by_index, library=lib)
        for i, a in extra.items():
            results_by_index[i] = a
    rescued: dict = {}
    # Still empty: one last time-boxed pass before the render repeats a shot
    # (the Glen Canyon job repeated ~19 clips across 148 empty scenes).
    if any(results_by_index[j["index"]] is None for j in jobs):
        n_empty = sum(1 for j in jobs if results_by_index[j["index"]] is None)
        report(f"Finding footage for {n_empty} empty scenes", 62)
        rescued = media.rescue_fill(jobs, results_by_index, work, youtube_only=bool(flags.get("youtube_only")),
                                    footage_only={j["index"] for j in jobs
                                                  if j.get("hook") and j.get("subject_type") != "document"})
    if held:
        pool_stats["variety"] = dict(media.restore_held(jobs, results_by_index, held), held=len(held),
                                     reasons=dict(collections.Counter(r for _a, r, _k in held.values())))
        print(f"[worker] variety: {pool_stats['variety']}", flush=True)
    # Still empty: never a reused shot (the owner, 2026-10-01: the Lake Powell
    # video reused 47 clips here and left its last 23 scenes empty). The fast
    # fallback ladder instead - the library's unused clips of the line's
    # subject or place, the pools' unused approved moments, one picture
    # search - in its own short time box (src/gapfill.py). What it cannot
    # fill gets the planner's graphic or the neighbouring shot held over it
    # once the timeline is built.
    fallback: dict = {}
    if any(results_by_index[j["index"]] is None for j in jobs):
        if config.NO_REUSE:
            n_left = sum(1 for j in jobs if results_by_index[j["index"]] is None)
            report(f"Filling {n_left} scenes the footage search ran out of time for", 63)
            fallback = gapfill.fill_empty(jobs, results_by_index, work, library=lib, require_cc=require_cc,
                                          youtube_only=bool(flags.get("youtube_only")),
                                          label="after the footage search")
            pool_stats["fallback"] = fallback
        elif config.REUSE_SHOTS_TO_FILL and config.RESCUE_BEFORE_REUSE:
            # The old rule (NO_REUSE=0): a shot reused at most REUSE_MAX_USES times.
            rescued["reused"] = media.fill_from_story(jobs, results_by_index, max_uses=config.REUSE_MAX_USES)
    for j in jobs:
        assets[j["index"]] = results_by_index[j["index"]]
    if rescued:
        pool_stats["rescue"] = rescued
    _ytdlp_mod.set_deadline(0.0)               # later steps (resource, render) are not time boxed here
    # Small photos get Real-ESRGAN detail and soft clips a sharpen pass to
    # 1080p, before anything is uploaded or rendered (time-boxed; a failure
    # keeps the original file).
    if config.UPSCALE_ENABLED or config.ALLOW_VERTICAL:
        report("Enhancing pictures and clips to HD", 64)
        try:
            pool_stats["upscale"] = upscale.upscale_assets([a for a in assets if a is not None])
        except Exception as e:  # noqa: BLE001 - never fail a video over polish
            print(f"[worker] upscale skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    media.LAST_STATS["pools"] = pool_stats     # per-scene sourcing resets the stats
    media.LAST_STATS["proxies"] = media.proxy_snapshot()
    vision.require_credits()

    # No percentage: the sourcing bands already reach the mid 60s.
    report("Designing motion graphics and animations")
    doc = timeline.build(
        segments, shots, assets,
        # The resolved URL, not the temp path: the document has to stay
        # meaningful after this job's work directory is gone.
        audio_url=audio_src or audio_path,
        audio_duration=audio_duration,
        inp=inp,
        planner=planner,
        warnings=warnings,
        # The narration on this disk: every sound is levelled against its
        # measured loudness (the owner's Lake Powell video was planned
        # against an assumed voice, voiceLufsSource "assumed").
        narration_path=audio_path,
        # Its pictures of a subject fill an image look's slots the story cannot.
        library=LAST_LIBRARY.get("lib"),
    )
    # What the hook booster changed (src/hookboost.py): the cuts made before the
    # shots were planned, and the opening as it was built.
    if doc.get("meta", {}).get("hookBoost") or boost_info:
        doc.setdefault("meta", {})["hookBoost"] = hookboost.merge_report(doc["meta"].get("hookBoost"), boost_info)
    # Arrows / circles that point at the thing the line talks about, only
    # where vision finds it (src/marks.py) - while the clips are still local.
    doc.setdefault("meta", {})["marks"] = marks.place(doc)
    try:
        def _put_split(local: str, name: str) -> str:
            obj = f"projects/{project_id}/{name}"
            if project_id and (_scene_media_on_r2() or storage.broker_enabled()):
                # R2 first: a public link that never expires (the signed one lapsed after 30 days).
                return _put_scene_file(local, obj, inp.get("media_bucket") or config.MEDIA_BUCKET, project_id,
                                       (report.job or {}).get("id", ""))[0]
            return local
        _bind_split_images(doc, work, _put_split)
        _bind_overlay_photos(doc, work, _put_split)
    except Exception as e:  # noqa: BLE001 - a nicety, never a failure
        print(f"[worker] split images skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    # (d) the last resort for a line the ladder could not fill: the planner's
    # graphic for it, else the neighbouring shot held over it (src/gapfill.py).
    # Never an empty scene, never another scene's clip.
    last = gapfill.hold_or_animate(doc, label="after the fallback fill")
    doc["meta"]["fallbackFill"] = {"ladder": fallback, "lastResort": last}
    if boost_info and doc["meta"].get("hookBoost") is not None:
        # A shot of a cut beat that missed the relevance gate gives way to the good shot beside it.
        doc["meta"]["hookBoost"]["settled"] = hookboost.settle(doc, boost_info)
    if fallback or any(last.values()):
        print(f"[worker] {gapfill.summary(fallback, last)}", flush=True)
    # One grade for the whole video (src/grade.py): its settings, and each
    # scene's tone measured from the files while they are still on this disk.
    report("Matching the colour of the clips")
    doc["meta"]["grade"] = grade.prepare(doc, remote=False)
    # A slow push toward the subject of a locked-off shot, and stills aimed at
    # theirs (src/reframe.py): the scenes' final lengths are known and the
    # files are still local. Time-boxed; written into the document, so every
    # machine of a split render draws the same move.
    if config.REFRAME_ENABLED:
        report("Framing shots on their subjects")
        doc["meta"]["reframe"] = reframe.place(doc)
    # The source tags (src/sources.py) with the pictures final: one whose corner has a face under it
    # takes the other low corner or is left out, and none stays on a scene that became a full-screen
    # graphic. A no-op for a video with no source tag (every video while SOURCE_TAGS is off).
    if config.SOURCE_TAGS:
        settled = sources.settle(doc)
        if settled:
            doc["meta"].setdefault("sourceTags", {})["settled"] = settled
    # A signed URL expires; keep the original reference so render can re-sign.
    unsupported = [k for k in ("own_clips", "channels")
                   if inp.get(k) and inp.get("source") in ("clips", "channels")]
    if unsupported:
        doc["meta"]["warnings"].append(
            f"Requested source mode '{inp.get('source')}' is not implemented yet; "
            f"sourced from Creative Commons YouTube and Commons instead.")
    # Which image/footage sources answered, came back empty, or failed, and why.
    doc["meta"]["sourceStats"] = media.source_stats()
    doc["meta"]["vision"] = vision.stats()
    if vision.out_of_credits():
        doc["meta"]["warnings"].insert(0, (
            "The AI account (Kie) ran out of credits during this job, so vision "
            "checks, AI rescue and AI images stopped partway. Top up Kie and "
            "re-run for full quality."))
    doc["meta"]["audioSource"] = raw_audio
    if made:
        # The narration was made from the script by the free voice (src/tts.py):
        # which voice, how long, how loud - and that it was not an upload.
        doc["meta"]["narration"] = made["report"]
    # Where the sourcing time actually went, visible from outside the worker.
    doc["meta"]["sourcing"] = dict(media.LAST_STATS)
    # What this video cost on the AI account (Kie credits), estimated from
    # measured per-call prices (2026-09-25, Gemini 3.8 Flash): vision ~0.08
    # per check, a planning call ~0.15, gpt-image-2 ~4 per image. A key that
    # drained 900 credits in an afternoon needs a per-job number to find why.
    vstats = vision.stats()
    usage = {"visionCalls": vstats.get("calls", 0),
             "directorCalls": director.CHAT_CALLS["n"],
             "imagesGenerated": media.generated_count()}
    usage["estimatedCredits"] = round(0.08 * usage["visionCalls"] + 0.15 * usage["directorCalls"]
                                      + 4.0 * usage["imagesGenerated"], 1)
    doc["meta"]["aiUsage"] = usage
    # What the AI understood the video to be about (kind, event, places, cast
    # with aliases, per-section footage), for the editor to show.
    doc["meta"]["story"] = dict(director.LAST_STORY) or dict(brief)
    # The editor's story card reads startBeat/endBeat/queries; keep both spellings.
    doc["meta"]["story"]["sections"] = [
        {**sec, "startBeat": sec.get("from"), "endBeat": sec.get("to"),
         "queries": sec.get("footage", [])}
        for sec in (doc["meta"]["story"].get("sections") or [])]
    doc["meta"]["audioBucket"] = inp.get("audio_bucket", "video-audio")
    # Replace Clip (resource) re-applies it: the app only sends video_style
    # with plan/build.
    doc["meta"]["videoStyle"] = styles.resolve(inp.get("video_style"))
    # The music sections, ducking and sound effects were laid out by the build.
    report("Mixing music and sound effects")
    # Only the brand kit's looks: the planner drew none other; a look a side
    # path placed (an archive tag, a mark, a one-picture swap) becomes the
    # closest allowed one or goes, and a full-screen graphic no allowed look
    # can draw becomes the neighbouring shot held over its line.
    kit = brandkit.from_input(inp)
    if kit is not None:
        doc["meta"]["brandKitApplied"] = brandkit.enforce(doc, kit)
    # The air under the scenes (wind, water, rain, city...) and a soft swell
    # into the biggest reveals, against the measured voice (src/ambience.py).
    doc["meta"]["ambience"] = ambience.apply(doc)
    if doc["meta"].get("hookBoost"):
        # The opening as it ended up (a shot the ladder could not fill was held over by its neighbour).
        doc["meta"]["hookBoost"]["opening"] = hookboost.opening_stats(doc["scenes"], doc["fps"])
    # Catch a malformed plan here rather than inside headless Chrome. Media may
    # still be missing at plan time — that is what the editor is for. One bad
    # graphic is dropped, never the video (a 30-minute job failed on one).
    timeline.drop_invalid_overlays(doc)
    timeline.validate(doc, require_media=False, allow_stock=inp.get("allow_stock"))
    return doc


def _replan_beat(scene: dict, doc: dict, story: dict, title: str) -> dict:
    """
    Regenerate: plan this one beat again from the story, as the planner
    would, and return the new shot (query, intent, sceneIntent).
    """
    fps = int(doc.get("fps") or config.DEFAULT_FPS)
    start = int(scene.get("startFrame") or 0) / fps
    end = start + max(1, int(scene.get("durationInFrames") or fps)) / fps
    seg = transcribe.Segment(text=str(scene.get("text") or ""), start=start, end=end)
    title = director.clean_title(title or story.get("event") or "")
    shots = [director._rule_shot(seg, 0, title)]
    if director.is_configured():
        director._ai_pass([seg], title, shots, brief=story)
    director.anchor_to_story(shots, [seg], story)
    shot = shots[0]
    si = (scene_intent_mod.SceneIntent.from_dict(shot["sceneIntent"]) if shot.get("sceneIntent")
          else scene_intent_mod.SceneIntent.from_shot(shot, story))
    shot["sceneIntent"] = si.to_dict()
    shot["fallbacks"] = list(dict.fromkeys(si.queries(shot.get("query", ""))[1:]
                                           + list(shot.get("fallbacks") or [])))
    return shot


def _candidate_entry(asset, rank: int, winner: bool) -> dict:
    return {
        "rank": rank, "winner": winner, "assetId": asset.identity,
        "sourceUrl": asset.url if str(asset.url or "").startswith("http") else "",
        "title": (asset.attribution or "")[:160], "source": asset.source,
        "score": asset.relevance_score, "quality": asset.quality,
        "finalScore": asset.final_score, "specificity": asset.specificity,
        "description": (asset.content_description or "")[:300],
        "moment": dict(asset.moment or {}), "media": asset.to_scene_media(),
    }


def _publish_alternatives(cands: List[dict], project_id: str, bucket: str, job_id: str,
                          scene_id: str, work: str) -> None:
    """Upload each alternative's clip, thumbnail and preview; fill its media (R2 first, see _put_scene_file)."""
    def put(local: str, obj: str) -> tuple:
        return _put_scene_file(local, obj, bucket, project_id, job_id)

    for n, c in enumerate(cands, 1):
        path = c.pop("localPath", "") or (c.get("media") or {}).get("url") or ""
        if not path or not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1] or ".mp4"
        tag = f"{scene_id}_alt{n}"
        obj = f"projects/{project_id}/alts/{tag}{ext}"
        try:
            url, ref = put(path, obj)
        except Exception as e:  # noqa: BLE001 - the choice is lost, the rest stand
            print(f"[replace] could not publish alternative {n}: {e}", flush=True)
            c["media"] = {}
            continue
        media_fields = {k: v for k, v in (c.get("media") or {}).items() if k not in _STORAGE_REFS}
        media_fields.update({"type": "video", "url": url, "storage": ref})
        thumb = _thumbnail(path, work, tag)
        if thumb:
            tobj = f"projects/{project_id}/thumbs/{tag}.jpg"
            try:
                media_fields["thumbnail"], media_fields["thumbStorage"] = put(thumb, tobj)
            except Exception:  # noqa: BLE001 - cosmetic
                pass
        preview = _preview_proxy(path, work, tag)
        if preview:
            pobj = f"projects/{project_id}/preview/{tag}.mp4"
            try:
                media_fields["previewUrl"], media_fields["previewStorage"] = put(preview, pobj)
            except Exception:  # noqa: BLE001 - the editor falls back to the clip
                pass
        c["media"] = {k: v for k, v in media_fields.items() if v is not None}


def _publish_choices(doc: dict, project_id: str, bucket: str, job_id: str, work: str, report: Reporter) -> int:
    """
    Pick-a-shot: every scene's runner-up clips whose files were kept
    (media._best_of, PICK_A_SHOT) are uploaded like Replace Clip's choices and
    their links put on semanticMetadata.alternatives[].media - the app's
    plan store turns those into playable choices the editor shows on a click.
    Nothing is searched or judged again. Returns the number published.
    """
    if not getattr(config, "PICK_A_SHOT", False):
        return 0
    todo = []
    for s in doc.get("scenes") or []:
        sem = s.get("semanticMetadata") if isinstance(s, dict) else None
        alts = [a for a in ((sem or {}).get("alternatives") or []) if isinstance(a, dict)
                and a.get("localPath") and os.path.isfile(a.get("localPath") or "")]
        if alts:
            todo.append((s, alts[:config.PICK_A_SHOT_CHOICES]))
    if not todo:
        return 0
    report(f"Saving other choices for {len(todo)} scenes", 67)
    n = 0

    def one(item):
        s, alts = item
        cands = [{"localPath": a["localPath"], "media": {}} for a in alts]
        _publish_alternatives(cands, project_id, bucket, job_id, str(s.get("id") or ""), work)
        got = 0
        for a, c in zip(alts, cands):
            if c.get("media", {}).get("url"):
                a["media"] = c["media"]
                got += 1
        return got

    with ThreadPoolExecutor(max_workers=6) as pool:
        for got in pool.map(one, todo):
            n += got
    print(f"[choices] pick-a-shot: {n} runner-up clip(s) published for {len(todo)} scene(s)", flush=True)
    return n


def do_resource(inp: dict, work: str, report: Reporter) -> tuple:
    """
    Replace Clip: re-source ONE scene and return the timeline plus the ranked
    choices (the winner and up to REPLACE_ALTERNATIVES - 1 alternatives), each
    published with a thumbnail and preview so the editor can show them.

    Timing is untouched: only `media` and its review flags change, so the
    visual track still tiles the narration exactly. The search honours the
    scene's typed intent, never returns the clip being replaced, one the user
    rejected (`exclude`), or one another scene already shows. `mode`:
    "replace" (default) or "more" search again; "regenerate" plans the beat
    again from the story first.
    """
    doc = inp.get("timeline")
    if not isinstance(doc, dict):
        raise ValueError("resource requires the current `timeline` document")
    scenes = doc.get("scenes") or []
    idx = inp.get("scene_index")
    if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(scenes):
        raise ValueError(f"scene_index must be between 0 and {len(scenes) - 1}")

    scene = scenes[idx]
    fps = int(doc.get("fps") or config.DEFAULT_FPS)
    seconds = max(0.4, int(scene.get("durationInFrames", fps)) / fps)
    sem = dict(scene.get("semanticMetadata") or {})
    story = dict((doc.get("meta") or {}).get("story") or {})
    mode = str(inp.get("mode") or "replace").lower()
    count = max(1, int(inp.get("count") or config.REPLACE_ALTERNATIVES))

    query = str(inp.get("query") or scene.get("query") or scene.get("text") or "").strip()[:240]
    intent = str(inp.get("intent") or sem.get("intent") or "")[:300]
    scene_intent = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else None
    fallbacks: List[str] = []
    if mode == "regenerate":
        report(f"Planning scene {idx + 1} again", 10)
        shot = _replan_beat(scene, doc, story, str(inp.get("title") or ""))
        query, intent = shot["query"], shot.get("intent") or intent
        scene_intent, fallbacks = shot.get("sceneIntent"), list(shot.get("fallbacks") or [])
        sem["subject"] = shot.get("subject") or sem.get("subject", "")
        sem["subjectType"] = shot.get("subjectType") or sem.get("subjectType", "")
    elif scene_intent:
        fallbacks = scene_intent_mod.SceneIntent.from_dict(scene_intent).queries(query)[1:]
    if not query:
        raise ValueError("this scene has nothing to search for - set a query first")

    # Never the clip being replaced, never one the user rejected, never one
    # another scene already shows.
    exclude = {str(x) for x in (inp.get("exclude") or []) if x}
    if sem.get("assetId"):
        exclude.add(str(sem["assetId"]))
    for k, other in enumerate(scenes):
        if k != idx:
            aid = (other.get("semanticMetadata") or {}).get("assetId")
            if aid:
                exclude.add(str(aid))

    report(f"Finding {count} choices for scene {idx + 1}", 20)
    vision.set_story(story)
    media.set_story_kind(story.get("kind", ""))
    media.reset_cache()
    overrides = _apply_config({
        "JUDGE_BEST_OF": count, "EXCELLENT_SCORE": 1.01,
        "VISION_MAX_CANDIDATES": max(count, config.VISION_MAX_CANDIDATES),
        "POOL_SCOUT": max(count + 2, config.POOL_SCOUT),
        "JUDGE_MAX_PER_SCENE": max(count + 3, config.JUDGE_MAX_PER_SCENE),
    })
    keep = media._KEEP_ALT_FILES.set(True)
    # The same rules as the plan: a scene in the first HOOK_SECONDS gets the
    # hook search (footage, never an AI image), and a scene of this year's
    # story searches the last month's uploads first.
    hook = int(scene.get("startFrame") or 0) / fps < config.HOOK_SECONDS
    recency = "month" if sem.get("eventWindow") == "year" and config.RECENT_FOOTAGE_FIRST else ""
    try:
        asset = media.source_for_segment(
            query, seconds, work,
            visual_type=scene.get("visualType", "footage"),
            used=exclude, fallbacks=fallbacks,
            allow_youtube=inp.get("allow_youtube"),
            allow_stock=inp.get("allow_stock"),
            require_cc=inp.get("require_cc"),
            intent=intent, context=str(scene.get("text") or ""),
            subject_type=str(sem.get("subjectType") or ""),
            subject=str(sem.get("subject") or ""),
            event_window=str(sem.get("eventWindow") or ""),
            scene_intent=scene_intent, hook=hook, recency=recency,
        )
    finally:
        media._KEEP_ALT_FILES.reset(keep)
        _restore_config(overrides)
    if not asset:
        raise ValueError(f"no usable media found for '{query}' - try different wording")

    # The same polish as a build: with the style's ALLOW_VERTICAL a vertical
    # replacement (or choice) is framed on its blurred copy, not cropped at render.
    if config.UPSCALE_ENABLED or config.ALLOW_VERTICAL:
        try:
            upscale.upscale_assets([asset])
        except Exception as e:  # noqa: BLE001 - never fail a replacement over polish
            print(f"[worker] upscale skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    if config.ALLOW_VERTICAL:
        for alt in list(asset.alternatives or [])[:count - 1]:
            p = alt.get("localPath") or ""
            if os.path.splitext(p)[1].lower() in (".mp4", ".webm", ".mov", ".mkv") and os.path.isfile(p):
                upscale.frame_vertical(p)

    scene["media"] = asset.to_scene_media()
    if asset.kind == "video":
        # Its measured length, as a build records it: without one the renderer
        # plays a clip shorter than its scene at 1x and holds its last frame
        # (measured on Remotion 4.0.511).
        clip_s = timeline._clip_seconds(asset)
        if clip_s:
            scene["media"]["clipSeconds"] = round(clip_s, 2)
    # Its tone for the video's grade (src/grade.py), read while the file is here
    # (a link is left for the render's own time-boxed pass).
    tone = grade.measure(scene["media"]) if grade.is_local(scene["media"].get("url")) else None
    if tone:
        scene["media"]["tone"] = tone
    scene["query"] = query
    scene["motion"] = (timeline._IMAGE_MOTIONS[idx % len(timeline._IMAGE_MOTIONS)]
                       if asset.kind == "image" else "none")
    scene["reviewRequired"] = bool(asset.review_required)
    scene["reviewReason"] = asset.review_reason or ""
    alternatives = list(asset.alternatives or [])
    scene["semanticMetadata"] = {
        **sem,
        "intent": intent,
        "searchQuery": query,
        "sceneIntent": scene_intent,
        "contentDescription": asset.content_description or "",
        "relevanceScore": asset.relevance_score,
        "qualityScore": asset.quality,
        "provider": asset.source or "",
        "assetId": asset.identity,
        "sourceUrl": asset.url if str(asset.url or "").startswith("http") else "",
        "specificity": asset.specificity,
        "finalScore": asset.final_score,
        "scoreParts": dict(asset.score_parts or {}),
        "moment": dict(asset.moment or {}),
        "alternatives": [{k: v for k, v in a.items() if k != "localPath"} for a in alternatives][:4],
    }

    candidates = [_candidate_entry(asset, 1, True)]
    for n, alt in enumerate(alternatives[:count - 1], 2):
        candidates.append({"rank": n, "winner": False, "assetId": alt.get("assetId"),
                           "sourceUrl": alt.get("url") if str(alt.get("url") or "").startswith("http") else "",
                           "title": alt.get("title", ""), "source": alt.get("source", ""),
                           "score": alt.get("score"), "quality": alt.get("quality"),
                           "finalScore": alt.get("finalScore"), "specificity": alt.get("specificity", ""),
                           "description": alt.get("description", ""), "moment": alt.get("moment") or {},
                           "localPath": alt.get("localPath", ""), "media": {}})

    project_id = inp.get("project_id") or ""
    if project_id and inp.get("publish_media", True):
        report("Saving replacement media", 70)
        publish_media(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                      report, job_id=inp.get("_job_id", ""), band=(70, 72))
        candidates[0]["media"] = dict(scene.get("media") or {})
        report("Saving the other choices", 80)
        _publish_alternatives(candidates[1:], project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                              inp.get("_job_id", ""), scene["id"], work)
    for c in candidates:
        c.pop("localPath", None)

    meta = doc.setdefault("meta", {})
    meta["scenesWithoutMedia"] = sum(
        1 for s in scenes if (s.get("media") or {}).get("type") == "color")
    meta["scenesNeedingReview"] = sum(1 for s in scenes if s.get("reviewRequired"))
    # Only this scene changed, so validate without demanding the rest be filled.
    timeline.drop_invalid_overlays(doc)
    timeline.validate(doc, require_media=False, allow_stock=inp.get("allow_stock"))
    return doc, candidates


def _sign_supabase_urls(doc: dict):
    """
    Re-sign any Supabase storage URLs inside the timeline.

    Media the user swapped in from the editor lives in a private bucket, and
    Remotion fetches those URLs from inside headless Chrome where the public
    form returns 400. Signing them here keeps private buckets working without
    exposing anything publicly. Mutates the document in place.
    """
    base = (config.SUPABASE_URL or "").rstrip("/")
    if not base:
        return
    marker = "/storage/v1/object/public/"

    def resign(url: str) -> str:
        if not url.startswith(base) or marker not in url:
            return url
        bucket, _, obj = url.split(marker, 1)[1].partition("/")
        try:
            return storage.signed_url(obj, bucket=bucket)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not sign {obj}: {e}", flush=True)
            return url

    audio = doc.get("audio") or {}
    if audio.get("url"):
        audio["url"] = resign(audio["url"])
    bgm = doc.get("bgm") or {}
    if bgm.get("url"):
        bgm["url"] = timeline.current_bgm_url(resign(bgm["url"]))
    for scene in doc.get("scenes", []):
        m = scene.get("media") or {}
        if m.get("url"):
            m["url"] = resign(m["url"])
        # The still an animation scene blurs behind its graphic: re-signed
        # like the clip, or dropped when it cannot be (a dead link would fail
        # the render; without it the scene draws on the charcoal grid).
        if m.get("thumbnail"):
            try:
                m["thumbnail"] = resign(m["thumbnail"])
            except Exception:  # noqa: BLE001
                m.pop("thumbnail", None)
    for ov in doc.get("overlays", []):
        for m in (ov.get("media") or []):
            if isinstance(m, dict) and m.get("url"):
                m["url"] = resign(m["url"])


def _sanitize_videos(doc: dict) -> int:
    """
    Blank every scene whose local clip is not a playable video, then cover it.

    A download can come back as a frameless MP4 shell; published and rendered
    as-is it produced an empty editor tile and a render that died on frame 0
    ("Is this a video file?"). Runs before publishing, so a stub never reaches
    storage. Returns how many scenes were blanked.
    """
    from src.assetserver import is_local
    dropped = 0
    for s in doc.get("scenes", []):
        m = s.get("media") or {}
        url = m.get("url") or ""
        if m.get("type") != "video" or not (is_local(url) and os.path.isfile(url)):
            continue
        if not media.playable_video(url):
            m.clear()
            m.update({"type": "color", "url": "", "source": "none"})
            s["reviewRequired"] = True
            s["reviewReason"] = "The downloaded clip was empty - covered by another shot; use Find footage"
            dropped += 1
    if dropped:
        print(f"[worker] {dropped} empty clip(s) dropped before publishing", flush=True)
        _fill_missing_media(doc)
    return dropped


def _no_repeats(doc: dict, report: Reporter = None) -> dict:
    """
    The check before the timeline is published (saved for the editor,
    uploaded, rendered): a scene showing the same file, asset or moment as an
    earlier scene - or its source video on the very next scene - gets a fresh
    shot through the fallback ladder (library, spare pool moments, a picture),
    else the last resort (src/gapfill.final_check). The owner's rule
    (2026-10-01): never reuse a clip within a video. Never fails the job.
    """
    try:
        found = gapfill.find_repeats(doc)
        if found and report is not None:
            report(f"Replacing {len(found)} repeated shots", 66)
        got = gapfill.final_check(doc)
    except Exception as e:  # noqa: BLE001 - the timeline as it is beats a failed job
        print(f"[worker] repeat check skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return {}
    if got.get("repeats") or got.get("empty"):
        print(f"[worker] before publishing: {got.get('repeats', 0)} repeated shot(s), "
              f"{got.get('replaced', 0)} replaced by fresh ones; {got.get('empty', 0)} empty scene(s) filled",
              flush=True)
        doc.setdefault("meta", {}).setdefault("fallbackFill", {})["beforePublishing"] = dict(got)
    return got


def _sanitize_stills(doc: dict, work: str, fetched: dict = None) -> int:
    """
    Re-encode every still to a real JPEG before Chrome sees it.

    Web image search saves whatever the server sent under the name it asked
    for: a WebP, an AVIF or an HTML error page named ".jpg". Chrome refuses to
    decode it and Remotion fails the WHOLE render - a real 23-scene job died at
    frame 356 on one airport photo. Each still is decoded by ffmpeg into a
    clean JPEG (remote ones are fetched first, or taken from `fetched`: the
    copies the quality check downloaded to decode them); one that cannot be
    decoded is turned into an empty scene, which _fill_missing_media then
    covers with a matching shot. Returns how many stills were dropped.
    """
    from src.assetserver import is_local
    dropped = 0
    medias = [s.get("media") for s in doc.get("scenes", [])]
    medias += [m for o in doc.get("overlays", []) for m in (o.get("media") or [])]
    for n, media in enumerate(medias):
        if not isinstance(media, dict) or media.get("type") != "image" or not media.get("url"):
            continue
        url = media["url"]
        src = url if is_local(url) and os.path.isfile(url) else ""
        if not src and os.path.isfile((fetched or {}).get(url) or ""):
            src = fetched[url]
        if not src and url.startswith("http"):
            src = os.path.join(work, f"still_src_{n}")
            try:
                storage.download(url, src)
            except Exception:  # noqa: BLE001
                src = ""
        out = os.path.join(work, f"still_{n}_{uuid.uuid4().hex[:6]}.jpg")
        ok = False
        if src and os.path.isfile(src):
            try:
                # Pillow first: AVIF/HEIC/CMYK/animated WebP and EXIF-rotated
                # phone photos come out as an upright RGB JPEG ffmpeg can read.
                from src import imagefix
                imagefix.normalize(src)
            except Exception:  # noqa: BLE001 - ffmpeg below is the real test
                pass
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-frames:v", "1",
                                "-vf", "scale='min(2560,iw)':-2", "-q:v", "3", out],
                               capture_output=True, timeout=60)
                ok = os.path.isfile(out) and os.path.getsize(out) > 2000
            except (subprocess.TimeoutExpired, FileNotFoundError):
                ok = False
        if ok:
            media["url"] = out
        else:
            dropped += 1
            media.clear()
            media.update({"type": "color", "url": "", "source": "none"})
    if dropped:
        print(f"[worker] {dropped} still(s) could not be decoded; covered by other shots",
              flush=True)
        _fill_missing_media(doc)
    return dropped


# Contact sheets of the last render, for {"return_frames": true}. Kept at
# module level so the job's error path can still return them when the upload
# after the render fails.
LAST_FRAMES: list = []
# The clip library the current plan loaded, so the build/plan branches can
# record this job's good clips into it before the work directory is wiped.
LAST_LIBRARY: dict = {"lib": None}


def _finish_costs(doc: dict, started: float) -> dict:
    """Measured credits, the priced ledger and the event summary into the result and the doc."""
    costs.measure_end()
    summary = costs.summary(time.time() - started)
    doc.setdefault("meta", {})["costs"] = summary
    doc["meta"]["events"] = events.summary()
    doc["meta"]["proxies"] = media.proxy_snapshot()
    return summary


def _keep_in_library(doc: dict, report: Reporter) -> None:
    lib = LAST_LIBRARY.get("lib")
    if lib is None or not lib.enabled:
        return
    try:
        report("Keeping clips for future videos", 61)
        events.phase("library")
        # New good clips are added; clips the job reused are marked used.
        lib.record_from_doc(doc)
        lib.save()
    except Exception as e:  # noqa: BLE001 - the library must never fail a video
        print(f"[library] skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
# The planned timeline of the current build, returned on failure in QA mode
# (return_frames) so a failed render can be reproduced locally.
LAST_TIMELINE: dict = {}


def _contact_sheets(video: str, work: str, every: float = 3.0, per_sheet: int = 16) -> list:
    """Base64 JPEG sheets (4x4 tiles, one frame every `every` seconds)."""
    import base64
    import glob
    out = os.path.join(work, "sheet_%02d.jpg")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video,
                        "-vf", f"fps=1/{every},scale=384:216,tile=4x4:padding=4",
                        "-q:v", "5", out], capture_output=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    sheets = []
    for f in sorted(glob.glob(os.path.join(work, "sheet_*.jpg")))[:12]:
        with open(f, "rb") as fh:
            sheets.append(base64.b64encode(fh.read()).decode())
    return sheets


def _preflight_media(doc: dict, gate=None) -> int:
    """
    The quality check before the render (src/quality.py Gate.before_render):
    every scene, still, overlay picture, the narration and the music are read
    (our R2 objects by an S3 HEAD, other links by a small range GET, in
    parallel), clips measured against their scenes, stills decoded, repeats
    found; whatever fails is repaired through the fallback ladder and the last
    resort, so the render never dies on one file - one unreadable clip killed
    a 15-minute render at frame 22,534 (storage answered 500 for it). Returns
    how many scenes were repaired.
    """
    gate = gate or quality.Gate(doc, config.WORK_DIR)
    return gate.before_render()


def _all_remote(doc: dict) -> bool:
    """Every visual in the document is a URL another worker can fetch."""
    medias = [s.get("media") or {} for s in doc.get("scenes", [])]
    medias += [m for o in doc.get("overlays", []) for m in (o.get("media") or [])]
    # An animation scene draws from the template registry and needs no file,
    # so it never keeps a render on one worker (it did: every video with an
    # animation scene rendered its whole length on the parent alone).
    return all(m.get("type") in ("color", "animation") or str(m.get("url", "")).startswith("http")
               for m in medias)


def _local_renderer(doc: dict, inp: dict, work: str, on_progress=None):
    def go(frames, path, muted, codec):
        return renderer.render(
            doc, path, composition=inp.get("composition", "Main"),
            concurrency=inp.get("concurrency") or config.RENDER_CONCURRENCY,
            on_progress=on_progress if frames is None and codec is None else None,
            serve_dir=work, frames=frames, muted=muted, codec=codec)
    return go


def _keep_render(out_path: str) -> None:
    """
    Copy the finished video to config.RENDER_KEEP_DIR/final.mp4 (set on pods),
    outside the job's work directory, which is deleted when the job ends. The pod
    serves that copy to the owner's laptop (src/podfetch.py) and keeps it when the
    upload fails. Written under a temporary name and renamed, so a reader never
    sees half a file. Never fails the job.
    """
    keep = config.RENDER_KEEP_DIR
    if not keep or not os.path.isfile(out_path):
        return
    try:
        os.makedirs(keep, exist_ok=True)
        part = os.path.join(keep, "final.mp4.part")
        shutil.copyfile(out_path, part)
        os.replace(part, os.path.join(keep, "final.mp4"))
        print(f"[worker] render kept for the laptop: {os.path.getsize(out_path) / 1e6:.0f} MB", flush=True)
    except OSError as e:
        print(f"[worker] could not keep a copy of the render: {e}", flush=True)


def _raise_explained(err: BaseException, gate) -> None:
    """
    Raise a failed render's error as the job's error. When files the video
    needs are gone from storage now (the gate asks every one once more), that
    is the error, in plain words - how many scenes, which, what storage
    answered - instead of what the renderer printed: on 2026-10-04 a project's
    media was deleted mid-render and its error message was a raw 404 page.
    """
    why = ""
    if not isinstance(err, quality.MediaMissing):
        try:
            why = gate.explain(err) if gate is not None else ""
        except Exception:  # noqa: BLE001 - the render's own error stands
            why = ""
    if why:
        raise renderer.RenderError(why) from err
    if renderer.has_markup(str(err)):
        # A chunk worker's error, or an older image's: still never a raw web page.
        raise renderer.RenderError(renderer.plain_error(str(err))) from err
    raise err


def _job_deadline(inp: dict) -> float:
    """
    When this job is stopped from outside (epoch seconds): its start (handler
    sets inp["_job_started"]) plus config.JOB_MAX_SECONDS - the serverless
    endpoint's execution timeout or a pod's own watchdog. 0 = not known (no
    limit set, or a caller that did not say when the job started). Never raises.
    """
    try:
        started = float(inp.get("_job_started") or 0)
        limit = float(config.JOB_MAX_SECONDS or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return started + limit if started > 0 and limit > 0 else 0.0


def do_render(doc: dict, inp: dict, work: str, report: Reporter,
              split: bool = False) -> dict:
    # The document may have come back from a browser, so validate before
    # spending GPU minutes on it. A scene without media is the quality check's
    # to repair first (below); the render requires every one after that.
    timeline.drop_invalid_overlays(doc)
    timeline.validate(doc, require_media=False, allow_stock=inp.get("allow_stock"))

    # A plan can sit in the editor for days; any signed URL in it has long
    # since expired. Re-resolve the narration from the reference the plan
    # recorded, then re-sign whatever else points at Supabase.
    # The caller's fresh narration link wins: the plan's own link is signed
    # for hours, and a timeline can sit in the editor for days.
    source = inp.get("audio_url") or (doc.get("meta") or {}).get("audioSource")
    if source:
        try:
            doc["audio"]["url"] = storage.resolve_audio(
                source, bucket=(doc["meta"].get("audioBucket") or "video-audio"))
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not refresh narration url: {e}", flush=True)
    _sign_supabase_urls(doc)
    # A plan levelled against an assumed voice: measure the narration now and
    # bring the sounds under it (timeline.relevel_to_voice) - never a failure.
    try:
        timeline.relevel_to_voice(doc)
    except Exception as e:  # noqa: BLE001
        print(f"[worker] narration level not re-measured: {type(e).__name__}: {str(e)[:100]}", flush=True)
    # The brand kit's identity as it is now (the job's kit, else the plan's):
    # the logo checked, the intro and outro measured and given their frames.
    # A brand file that cannot be read is left out - never a failed render.
    try:
        brand_report = brandkit.prepare_render(doc, inp, work)
        if brand_report:
            doc.setdefault("meta", {})["brand"] = brand_report
    except Exception as e:  # noqa: BLE001 - the video renders without the brand extras
        print(f"[worker] brand kit left out of the render: {type(e).__name__}: {str(e)[:160]}", flush=True)
        for key in ("intro", "outro"):
            (doc.get("brand") or {}).pop(key, None)
    # The quality check (src/quality.py): every scene, picture and sound the
    # renderer will load is checked, and whatever fails is repaired through
    # the fallback ladder before any frame is drawn - one unreadable clip
    # killed a 15-minute render at frame 22,534 (storage answered 500 for it).
    gate = quality.Gate(doc, work, report)
    broken = _preflight_media(doc, gate=gate)
    if broken:
        report(f"Repaired {broken} scene(s) before the render", 69)
    timeline.validate(doc, require_media=True, allow_stock=inp.get("allow_stock"))
    # The narration cleaned once (src/voicepolish.py: rumble, hum, room noise,
    # harsh esses, peaks, level drift - only what it measures as needed), at
    # its own loudness and timing; every draw below reads the cleaned copy.
    # Any failure keeps the original.
    report("Polishing the narration", 69)
    voicepolish.for_render(doc, work, inp)
    # The video's grade: the default when the document has none (GRADE), and
    # the tone of any scene without one (an older plan, a repaired scene) -
    # time-boxed; a scene left unmeasured keeps the shared look only.
    grade.prepare(doc, remote=True)
    # A bed the renderer cannot play (an unknown file, an editor's bad numbers) is dropped.
    ambience.clean(doc)
    out_path = os.path.join(work, "final.mp4")
    drawing = time.time()               # how long a draw takes here: the AI review's second render is timed by it
    try:
        _draw(doc, inp, work, report, split, out_path, gate)
    except Exception as e:  # noqa: BLE001 - drawn once more when the error names files that can be replaced
        # (Too much of the media gone to repair: gate.recover raises that, in plain words.)
        if not gate.recover(e):
            _raise_explained(e, gate)
        print(f"[worker] the render failed on files it named; repaired them, rendering once more: "
              f"{type(e).__name__}: {str(e)[:200]}", flush=True)
        try:
            _draw(doc, inp, work, quality.floor(report, 70, "Second render: "), split, out_path, gate)
        except Exception as e2:  # noqa: BLE001 - the one second render is spent
            _raise_explained(e2, gate)
    # The finished file is scanned (black, frozen, silent): a real defect is
    # repaired and the video drawn once more - never twice - and the better
    # of the two files is kept.
    drawn_in = time.time() - drawing
    spent = gate.rerendered             # that one second render already drawn (a render that failed on a file)
    # The AI review (src/review.py, AI_REVIEW; off = none of this does anything):
    # a vision model looks at the finished video scene by scene and the sound is
    # measured; what it can fix safely (a clip that does not fit swapped for the
    # scene's other choice, a title moved off a face) joins the SAME second
    # render - one more draw for the gate's repairs and the review's together,
    # never a third. Its frames are planned on the document as it was drawn,
    # before the gate's scan repairs anything. A second render of its own is
    # asked for only while the job has the time to finish it (_job_deadline).
    reviewer = review.Review(doc, work, report)
    reviewer.plan()
    again = gate.after_render(out_path)
    if reviewer.after_render(out_path, gate, may_fix=not spent, again=again,
                             deadline=_job_deadline(inp), draw_seconds=drawn_in):
        again = True
        try:
            _sign_supabase_urls(doc)    # a swapped-in choice may live in the app's private storage
        except Exception as e:  # noqa: BLE001 - a finished render is never lost to this
            print(f"[worker] links not re-signed for the second render: {type(e).__name__}: {str(e)[:120]}",
                  flush=True)
    if again:
        first = os.path.join(work, "final.first.mp4")
        os.replace(out_path, first)
        try:
            _draw(doc, inp, work, quality.floor(report, 90, "Second render: "), split, out_path, gate)
        except Exception as e:  # noqa: BLE001 - the first render stands, its problems reported
            gate.rerender_failed(e)
            reviewer.rerender_failed(e)
            os.replace(first, out_path)
        else:
            reviewer.after_rerender(gate.after_rerender(out_path, first))
    checked = gate.finish()
    doc.setdefault("meta", {})["quality"] = checked
    report(checked["summary"], 90)
    # What goes back with the video: the gate's report and, when it ran, the review's.
    reports = {"quality": checked}
    reviewed = reviewer.finish()
    if reviewed:
        doc["meta"]["review"] = reports["review"] = reviewed
        report(reviewed["summary"], 90)
    # Over the app's per-file storage limit: re-encode to fit, not fail the
    # upload. R2 has no such cap, so the full-quality file goes there as is.
    if not r2.enabled():
        renderer.fit_size(out_path)
    _keep_render(out_path)

    report("Uploading video", 91)
    events.phase("upload")
    # The whole video: the brand intro and outro around the narration.
    duration = brandkit.total_frames(doc) / doc["fps"]

    # Preferred: the caller pre-signed a destination for us, so this worker
    # needs no Supabase credentials at all. The app's video-render edge
    # function already does this — it holds the service key, we do not.
    LAST_FRAMES.clear()
    if inp.get("return_frames"):
        LAST_FRAMES.extend(_contact_sheets(out_path, work))

    if inp.get("return_video"):
        # A benchmark render with no project to upload to: the file rides
        # back in the job result (RunPod caps results, so small renders only).
        import base64
        size = os.path.getsize(out_path)
        cap = int(config.RETURN_VIDEO_MAX_MB * 1024 * 1024)
        if size > cap:
            raise RuntimeError(f"rendered file is {size / 1e6:.1f} MB, over the {config.RETURN_VIDEO_MAX_MB} MB "
                               "return cap; render smaller (width/height) or give the job a project")
        with open(out_path, "rb") as fh:
            payload = base64.b64encode(fh.read()).decode("ascii")
        return {"video_url": "", "public_url": "", "object_path": "", "bucket": "",
                "uploadedVia": "inline", "size_bytes": size, "duration": duration,
                "video_b64": payload, **reports}

    upload_url = inp.get("upload_url")
    if upload_url and not storage.r2_only():   # Cloudflare only: R2 below instead
        size = storage.upload_to_signed_url(out_path, upload_url)
        public_url = inp.get("public_url") or ""
        return {
            "video_url": public_url,
            "public_url": public_url,
            "object_path": inp.get("video_path") or "",
            "bucket": "",
            "uploadedVia": "signed_url",
            "size_bytes": size,
            "duration": duration,
            **reports,
        }

    # Cloudflare R2 first: no 2 GB cap, no download fees. The object name ends
    # in a random token, so the public link is unguessable. Any failure falls
    # through to the app's own storage below.
    if r2.enabled():
        project_id = inp.get("project_id") or "adhoc"
        key = f"projects/{project_id}/final-{int(time.time())}-{uuid.uuid4().hex[:12]}.mp4"
        try:
            url = r2.upload(out_path, key, deadline=time.time() + config.FINAL_UPLOAD_RETRY_SECONDS)
            print(f"[worker] final video on R2: {key}", flush=True)
            return {
                "video_url": url,
                "public_url": url,
                "object_path": key,
                "bucket": f"r2:{config.R2_BUCKET}",
                "uploadedVia": "r2",
                "size_bytes": os.path.getsize(out_path),
                "duration": duration,
                **reports,
            }
        except Exception as e:  # noqa: BLE001 - the app's storage is the fallback
            if storage.r2_only():
                raise           # Cloudflare only: never fall back to the app's storage
            print(f"[worker] R2 upload failed, using app storage: {type(e).__name__}: {str(e)[:200]}",
                  flush=True)
            renderer.fit_size(out_path)     # app storage still caps each file

    # No key on this worker: the app's broker signs the one destination.
    if storage.broker_enabled() and inp.get("project_id"):
        bucket = config.RENDER_BUCKET
        object_path = f"projects/{inp['project_id']}/final-{int(time.time())}.mp4"
        playable = storage.broker_upload(
            out_path, bucket, object_path, inp["project_id"], inp.get("_job_id", ""),
            read_ttl=int(inp.get("signed_url_ttl", 60 * 60 * 24 * 7)),
            # The whole video rides on this one upload: wait out an app outage.
            deadline=time.time() + config.FINAL_UPLOAD_RETRY_SECONDS)
        return {
            "video_url": playable,
            "public_url": "",
            "object_path": object_path,
            "bucket": bucket,
            "uploadedVia": "broker",
            "size_bytes": os.path.getsize(out_path),
            "duration": duration,
            **reports,
        }

    # Fallback: upload with our own service-role key.
    project_id = inp.get("project_id") or uuid.uuid4().hex
    object_path = inp.get("object_path") or f"projects/{project_id}/final.mp4"
    bucket = inp.get("bucket") or config.SUPABASE_BUCKET
    public_url = storage.upload_to_supabase(out_path, object_path, bucket=bucket)

    # The bucket may be private. A public-form URL 400s there, so sign the
    # object as well — signing works against public buckets too, making this
    # correct either way. Both are returned so the app can re-sign from the
    # path when a long-lived link expires.
    playable = public_url
    try:
        playable = storage.signed_url(
            object_path, bucket=bucket,
            expires_in=int(inp.get("signed_url_ttl", 60 * 60 * 24 * 7)),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[worker] could not sign render, falling back to public url: {e}", flush=True)

    return {
        "video_url": playable,
        "public_url": public_url,
        "object_path": object_path,
        "bucket": bucket,
        "uploadedVia": "service_key",
        "size_bytes": os.path.getsize(out_path),
        "duration": duration,
        **reports,
    }


def _links_for_chunks(remote_doc: dict, inp: dict) -> bool:
    """
    The chunk render without R2 (fanout.render) sends the document itself to
    its workers, so every picture in it must be a link. What is still a file
    on this disk - a scene the quality check repaired a moment ago, a still it
    cut from a clip - is uploaded to the job's parts folder (temporary, like
    the chunks) and linked in the workers' copy only; the saved timeline is
    never touched. True when every visual is then a link. It used to be
    all-or-nothing: on 2026-10-03 one repaired scene's local file sent a
    29-minute video to one worker, which ran out of time at 55%.
    """
    # (Chunks render silent: the narration and the music stay on this machine.)
    sounds = {id(remote_doc.get(k)) for k in ("audio", "bgm") if isinstance(remote_doc.get(k), dict)}
    refs = [(m, field, path) for m, field, path in fanout.local_refs(remote_doc) if id(m) not in sounds]
    if not refs:
        return _all_remote(remote_doc)
    project_id, job_id = inp.get("project_id") or "", inp.get("_job_id") or ""
    if not (project_id and job_id):
        return False
    bucket = inp.get("media_bucket") or config.MEDIA_BUCKET
    links: Dict[str, str] = {}
    until = time.time() + 180

    def put(path: str) -> tuple:
        import hashlib
        name = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
        obj = f"projects/{project_id}/parts/{job_id}/local_{name}{os.path.splitext(path)[1].lower() or '.bin'}"
        return path, storage.broker_upload(path, bucket, obj, project_id, job_id, read_ttl=60 * 60 * 6,
                                           deadline=until)
    try:
        files = sorted({path for _m, _f, path in refs})
        if files:
            with ThreadPoolExecutor(max_workers=min(8, len(files))) as pool:
                links.update(pool.map(put, files))
    except Exception as e:  # noqa: BLE001 - the whole video renders here, as before
        print(f"[worker] local files could not be published for the chunk render: {type(e).__name__}: "
              f"{str(e)[:160]}", flush=True)
        return False
    for m, field, path in refs:
        m[field] = links[path]
    print(f"[worker] published {len(links)} local file(s) for the chunk render", flush=True)
    return _all_remote(remote_doc)


def _on_one_machine(doc: dict, concurrency, spread: bool) -> None:
    """
    Before the whole video is rendered on this one machine (the last resort):
    a long video says so, with the reason the workers were not used, in the
    log and the job's events - a 29-minute video once rendered whole on one
    16-vCPU worker and nobody knew why until it timed out (2026-10-03). A
    video that could not finish inside the longest a render may run
    (RENDER_TIMEOUT_MAX_SECONDS) is refused now, with the reason, instead of
    running for hours and timing out with nothing saved.
    """
    frames = brandkit.total_frames(doc)
    fps = max(1, int(doc.get("fps") or 30))
    minutes = frames / fps / 60.0
    if minutes < 3:
        return
    seconds = renderer.estimate_seconds(frames, concurrency)
    if spread:
        why = str((media.LAST_STATS.get("pod_render") or {}).get("error") or "the spread render could not run")
    else:
        why = "; ".join(fanout.pod_render_ready(doc)["missing"]) or "the spread render is off"
    limit = float(config.RENDER_TIMEOUT_MAX_SECONDS)
    line = (f"the whole {minutes:.0f}-minute video on this one machine ({renderer.cpus()} CPUs, about "
            f"{renderer._minutes(seconds)}); the workers were not used: {why[:300]}")
    if seconds > limit:
        text = (f"This {minutes:.0f}-minute video cannot be rendered on one machine: it would take about "
                f"{renderer._minutes(seconds)} and no render may run longer than {renderer._minutes(limit)}. "
                f"Rendering across the workers was not possible ({why[:300]}). Nothing was rendered.")
        events.emit("render", "whole_render_refused", level="error", message=text,
                    data={"frames": frames, "estimateSeconds": int(seconds), "limitSeconds": int(limit)})
        raise renderer.RenderError(text)
    print(f"[worker] rendering {line}", flush=True)
    events.emit("render", "whole_render", level="warning", message="Rendering " + line,
                data={"frames": frames, "estimateSeconds": int(seconds), "cpus": renderer.cpus()})


def _draw(doc: dict, inp: dict, work: str, report, split: bool, out_path: str, gate=None) -> None:
    """
    Draw `doc` to `out_path`, picture and balanced sound, whichever way this
    render runs: a pod's render spread over the workers, the serverless chunk
    render, or one machine. do_render calls it a second time (once) when the
    quality check repaired scenes after the first.
    """
    # Chunk workers get the document with its web links and clean their own
    # stills; the cleaned copies below are files on this worker's disk only.
    remote_doc = copy.deepcopy(doc) if split else None
    _sanitize_stills(doc, work, fetched=getattr(gate, "fetched", None))
    if gate is not None:
        gate.no_empty_scenes()          # a still that would not decode leaves no empty frame

    report(f"Rendering {doc['meta'].get('sceneCount', len(doc['scenes']))} scenes", 70)
    events.phase("render")
    last_pct = [70]

    def on_render(frac: float):
        # 70 -> 90%: Remotion's own progress, instead of a bar that sits at 70.
        # "on one machine": the whole video is being drawn here, not spread
        # over the workers (their line reads "... on 10 machines").
        pct = 70 + int(20 * max(0.0, min(1.0, frac)))
        if pct != last_pct[0]:
            last_pct[0] = pct
            report(f"Rendering video {int(frac * 100)}% on one machine", pct)

    concurrency = inp.get("concurrency") or config.RENDER_CONCURRENCY
    # True once the sound has been balanced and joined to the picture in one
    # pass (render.finalize): the chunked renders and the separate-audio render.
    finished = False
    # The render is spread over the serverless workers (POD_RENDER_FANOUT),
    # whether this machine is a pod or itself one of those workers: this
    # finished document - stills cleaned, gaps filled, repaired scenes and all -
    # is what every machine draws, and whatever in it is a file on this disk is
    # published for them first (fanout.local_refs). When it cannot run or the
    # machines fail, the whole video renders here; only when storage says files
    # it draws are gone does it raise (fanout.SpreadFailed) - do_render then
    # repairs what is named or fails.
    spread = fanout.pod_render_enabled(doc)
    if spread:
        finished = fanout.render_pod(doc, out_path,
                                     job_id=inp.get("_job_id") or (getattr(report, "job", None) or {}).get("id", ""),
                                     work=work, report=report, composition=inp.get("composition", "Main"),
                                     concurrency=concurrency)
    if finished:
        pass
    # The Supabase-broker chunk render only when Cloudflare R2 is not set up:
    # with R2, chunks travel through R2 alone (render_pod above).
    elif split and not spread and not r2.enabled() and remote_doc is not None \
            and _links_for_chunks(remote_doc, inp):
        fanout.render(remote_doc, out_path, parent_job_id=(report.job or {}).get("id", ""),
                      project_id=inp.get("project_id") or "",
                      bucket=inp.get("media_bucket") or config.MEDIA_BUCKET, work=work,
                      report=report, render_local=_local_renderer(doc, inp, work),
                      # The previous render's manifest: unchanged chunks are reused.
                      previous=inp.get("render_manifest") if isinstance(inp.get("render_manifest"), dict) else None)
        finished = True
    else:
        # The last resort: the whole video on this one machine. Said in the
        # log and the job's events with the reason, and refused when it could
        # not finish inside the longest a render may run (_on_one_machine).
        _on_one_machine(doc, concurrency, spread)
        if config.RENDER_SEPARATE_AUDIO:
            # The picture alone, the sound as lossless WAV beside it, joined with
            # the loudness set and AAC encoded once: the sound starts on frame 0
            # (Remotion's own AAC ran 42.7 ms late) and the file is written once.
            picture = os.path.join(work, "final.picture.mp4")
            mix = os.path.join(work, "final.mix.wav")
            rendered = renderer.render(doc, picture, composition=inp.get("composition", "Main"),
                                       concurrency=concurrency,
                                       on_progress=on_render, serve_dir=work, audio_to=mix) or picture
            report("Balancing the sound", 90)
            if os.path.isfile(rendered) and os.path.isfile(mix):
                renderer.finalize(rendered, mix, out_path)
                finished = True
                for leftover in (rendered, mix):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
            elif rendered != out_path and os.path.isfile(rendered):
                # A renderer that kept the sound in its own file: the old path below.
                os.replace(rendered, out_path)
        else:
            renderer.render(
                doc, out_path,
                composition=inp.get("composition", "Main"),
                # Left unset, Remotion auto-detects concurrency from the host's CPU
                # count, which is a GPU pod's real vCPU count - not what a Docker
                # container is actually allowed to spawn threads for. A real render
                # crashed at 4% ("thread::unix::Thread::new::thread_start", a Rust
                # panic in the compositor failing to spawn a new OS thread) right
                # after the heaviest-possible run of the memory/thread-heavy parallel
                # sourcing phase. RENDER_CONCURRENCY caps it to a value verified safe
                # in this container instead.
                concurrency=concurrency,
                on_progress=on_render,
                # Everything sourced for this job lives here; the renderer serves it
                # over loopback so headless Chrome can actually fetch it.
                serve_dir=work,
            )

    # YouTube loudness (-14 LUFS): the raw narration sat ~10 dB under
    # every competitor's render. Never fails the job.
    if not finished:
        report("Balancing the sound", 90)
        renderer.normalize_loudness(out_path)


def _done_fields(out: dict) -> dict:
    return {
        "status": "done", "progress": 100, "current_step": "Done",
        "video_url": out["video_url"],
        # An INTEGER column: a fractional length is refused by the database.
        "duration_seconds": int(round(float(out["duration"] or 0))),
        "completed_at": "now()",
    }


# Settings a job may override for itself ({"config": {...}} in the input), so
# the benchmark can A/B a selection change on one image. Coerced to the type
# the setting already has; anything else is ignored.
CONFIG_OVERRIDABLE = ("CANDIDATE_POOL", "JUDGE_BEST_OF", "EXCELLENT_SCORE", "JUDGE_MAX_PER_SCENE",
                      "POOL_EXTRA_QUERIES", "POOL_SCOUT", "INTENT_QUERIES_MAX",
                      "VISION_MAX_CANDIDATES", "META_WEIGHTS", "FINAL_WEIGHTS",
                      "TREATMENTS", "STYLE_PACK", "MOMENT_FINE_PASS", "CLEAN_CUTS",
                      # Video styles (src/styles.py) ride on these.
                      "MIN_SCENE_SECONDS", "TARGET_SCENE_SECONDS", "MAX_SCENE_SECONDS",
                      "ALLOW_VERTICAL", "VERTICAL_BAND_ASPECT", "NEWS_FOOTAGE", "GRAPHICS_DENSITY",
                      "TRANSITION_STYLE", "TRANSITION_PACK", "UPSCALE_ENABLED", "LOCAL_VISION_ENABLED",
                      # The news styles turn AI images off (the owner's review,
                      # 2026-09-30), and any style may tune the variety rules.
                      "IMAGE_MAX_PER_VIDEO", "PREFER_GENERATED_IMAGES", "GENERATED_IMAGES_IN_HOOK",
                      "HOOK_SECONDS", "MAX_MOMENTS_PER_VIDEO", "SAME_VIDEO_GAP_SECONDS",
                      "REUSE_MIN_GAP_SECONDS", "IMAGE_MAX_USES", "RECENT_FOOTAGE_FIRST",
                      "MENTION_CUTS", "MARKS_ENABLED", "MARKS_MAX", "STILL_MOTION",
                      # Human cuts, the Nature & Weather edit, no reuse across
                      # videos and the AI-slop filter (2026-09-30).
                      "HUMAN_CUTS", "CUT_FAST_SECONDS", "CUT_SLOW_SECONDS", "CUT_HOOK_FACTOR",
                      "CUT_LEAD_SECONDS", "EYEWITNESS_SEARCHES", "COMING_SHOTS", "HOOK_INTENSITY",
                      "MOTION_PREFERENCE", "PHOTO_MAX_PER_10MIN", "REGION_BLOCKS", "CHAIN_SHOTS",
                      "CHAIN_MAX", "POOL_JUDGE_CLIPS", "AI_SLOP_FILTER", "CROSS_VIDEO_REUSE_DAYS",
                      "CROSS_VIDEO_GAP_SECONDS", "LIBRARY_SAVE_UNUSED",
                      # The look and sound pass (2026-10-02): A/B one job without a redeploy.
                      "VOICE_POLISH", "GRADE", "GRADE_PRESET", "GRADE_STRENGTH", "GRADE_NORMALIZE",
                      "AMBIENCE", "AMBIENCE_UNDER_VOICE_DB", "RISERS",
                      # Smart reframing (src/reframe.py); the news styles keep clips as shot.
                      "REFRAME_ENABLED", "REFRAME_CLIPS", "REFRAME_STILLS", "REFRAME_MAX_SCALE",
                      "REFRAME_SHARE", "REFRAME_SECONDS", "REFRAME_MIN_SECONDS",
                      # Niche footage packs (src/packs.py): PACKS_FIRST (pack clips before any search)
                      # is the one to A/B; the rest tune what a pack may supply.
                      "PACKS_FILL", "PACKS_FIRST", "PACKS_NICHES", "PACKS_MIN_SIMILARITY",
                      "PACKS_FIRST_MIN_SIMILARITY", "PACKS_FIRST_MAX_SHARE", "PACKS_LICENSES",
                      # The hook booster (src/hookboost.py): A/B one job without a redeploy.
                      "HOOK_BOOST", "HOOK_BOOST_SECONDS", "HOOK_BOOST_SPLIT_OVER", "HOOK_BOOST_MIN_SHOT",
                      "HOOK_BOOST_MAX_SHOT", "HOOK_BOOST_MOTION", "HOOK_BOOST_DRAMA", "HOOK_BOOST_QUIET_SECONDS",
                      "HOOK_BOOST_SFX_CUTS", "HOOK_TEASER", "HOOK_TEASER_SHOTS", "HOOK_TEASER_SECONDS",
                      # Auto maps (src/automaps.py): named rivers, reservoirs, dams and canals on real geography.
                      "AUTO_MAPS", "AUTO_MAP_GAP",
                      # On-screen sources (src/sources.py): "SOURCE: USBR, 2024" where the narration names its source.
                      "SOURCE_TAGS", "SOURCE_TAG_GAP", "SOURCE_TAG_FIRST_SECONDS", "SOURCE_TAG_SECONDS",
                      # The AI review of the finished video (src/review.py): one job can try it
                      # ({"config": {"AI_REVIEW": 1}}), or review without fixing (AI_REVIEW_FIX 0).
                      "AI_REVIEW", "AI_REVIEW_FIX", "AI_REVIEW_AUDIO", "AI_REVIEW_GROUP", "AI_REVIEW_MAX_CALLS",
                      "AI_REVIEW_SECONDS", "AI_REVIEW_MIN_MATCH", "AI_REVIEW_MAX_FIX_SHARE")


def _apply_config(overrides) -> dict:
    """Apply per-job overrides; returns what to put back."""
    previous = {}
    if not isinstance(overrides, dict):
        return previous
    for key, value in overrides.items():
        if key not in CONFIG_OVERRIDABLE or not hasattr(config, key):
            continue
        current = getattr(config, key)
        try:
            if isinstance(current, bool):
                value = str(value).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(current, int):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            elif current is None or isinstance(current, dict):
                value = json.loads(value) if isinstance(value, str) else value
                if not isinstance(value, dict):
                    continue
            elif isinstance(current, str):
                value = str(value)[:64]
            else:
                continue
        except (TypeError, ValueError):
            continue
        previous[key] = current
        setattr(config, key, value)
    if previous:
        print(f"[worker] config overrides: {sorted(previous)}", flush=True)
    return previous


def _restore_config(previous: dict) -> None:
    for key, value in (previous or {}).items():
        setattr(config, key, value)


def do_restore(inp: dict, work: str, report: Reporter) -> dict:
    """
    Put back the stored files of a project that vanished (src/restore.py):
    the Cloudflare R2 folders of two projects were deleted by hand on
    2026-10-04 and their timelines pointed at nothing. The timeline is read
    (from the input or through storage) and never changed; the video style
    it was planned with is in force, so a restored clip is framed and
    upscaled the way its plan did it.
    """
    doc = restore.load_timeline(inp, work)
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    style_inp = {"video_style": inp.get("video_style") or meta.get("videoStyle") or "",
                 "config": dict(inp["config"]) if isinstance(inp.get("config"), dict) else None}
    styles.apply(style_inp)
    previous = _apply_config(style_inp.get("config"))
    try:
        return restore.run(inp, doc, work, report, thumbnail=_thumbnail, preview=_preview_proxy)
    finally:
        _restore_config(previous)


def handler(job):
    started = time.time()
    job_id = job.get("id") or uuid.uuid4().hex
    inp = job.get("input") or {}
    if str(inp.get("action") or "").lower() == "batch":
        # Several videos as one job (src/batch.py): each is a normal build through this same
        # handler, one after another, with its own config, costs, events and project row.
        try:
            return batch.run({**job, "id": job_id, "input": inp}, handler)
        except Exception as e:  # noqa: BLE001 - errors never raise out of the handler
            traceback.print_exc()
            return {"ok": False, "action": "batch", "error": f"{type(e).__name__}: {e}"[:800],
                    "elapsed": round(time.time() - started, 1)}
    # The storage broker authorises uploads by the running job's id.
    inp["_job_id"] = job_id
    # When the job started: what may still start a long step near the end reads how much of
    # the job's time is left from it (do_render's AI review: _job_deadline). A caller running
    # several videos in one job passes the job's own start.
    inp.setdefault("_job_started", started)
    # The video style (news compilation, documentary...) becomes per-job
    # config overrides before they are applied, so fan-out parts inherit it.
    # Replace Clip sources with the style the timeline was planned with.
    act = (inp.get("action") or "build").lower()
    if act == "resource" and not inp.get("video_style"):
        tl = inp.get("timeline") if isinstance(inp.get("timeline"), dict) else {}
        meta = tl.get("meta") if isinstance(tl.get("meta"), dict) else {}
        inp["video_style"] = meta.get("videoStyle") or ""
    # The customer's brand kit (src/brandkit.py): its defaults (density, sound,
    # captions, colours) go into the input before the video style is applied,
    # and its picks are in force for everything this job plans. A render or a
    # Replace Clip without one keeps the picks its timeline was planned with.
    kit = None
    if act in ("plan", "build", "resource", "render"):
        kit = brandkit.prepare_input(inp)
        if kit is None and isinstance(inp.get("timeline"), dict):
            kit = brandkit.from_doc(inp["timeline"])
        if kit is not None:
            print(f"[worker] brand kit: {kit['name']} ({brandkit.describe(kit)})", flush=True)
    if act in ("plan", "build", "resource"):
        vstyle = styles.apply(inp)
        if vstyle:
            print(f"[worker] video style: {vstyle}", flush=True)
    config_before = _apply_config(inp.get("config"))
    action = (inp.get("action") or "build").lower()
    project_id = inp.get("project_id") or ""
    # Project updates go through the broker as this job; parts and render
    # chunks are not the project's job and never write the row.
    storage.CURRENT_JOB[0] = job_id if action in ("plan", "build", "render", "resource") else ""
    # Every job keeps its own ledger and event log; a fan-out child returns
    # both in its result and the parent absorbs them.
    costs.reset(inp.get("prices") if isinstance(inp.get("prices"), dict) else None)
    # A restore (src/restore.py) is not the project's job: its progress and its
    # events stay with this job's own status and result, so nothing of it is
    # ever written to the app's database.
    reports_to = "" if action == "restore_media" else project_id
    events.start_job(job_id, reports_to, part=("part" if action in ("source_part", "render_chunk") else ""))
    if action in ("plan", "build", "render", "resource"):
        costs.measure_start()
    report = Reporter(reports_to, job=job)
    work = _work_dir(job_id)
    gapfill.reset()                     # the fallback ladder's plan is this job's own
    packs.reset()                       # and the niches its footage packs are read for
    quality.reset()                     # and so is the quality check's
    kit_scope = brandkit.scope(kit)     # left in the finally below, whatever happens
    kit_scope.__enter__()

    # This video's own name in the cross-video ledger: the job id, or - for a video of a batch, which
    # shares the batch's job id with the others (src/batch.py) - one of its own, so no video's record
    # overwrites another's.
    ledger_job = str(inp.get("_ledger_job") or job_id)

    try:
        if action in ("plan", "build", "resource", "source_part"):
            # What earlier videos showed (src/ledger.py), read in the background
            # while the narration is transcribed; sourcing never repeats it.
            ledger.start_loading(ledger_job, project_id)
        if action == "source_part":
            # One part of a long video, queued by its parent job (src/fanout.py).
            def set_story(brief):
                vision.set_story(brief)
                media.set_story_kind((brief or {}).get("kind", ""))
                # The pools read the story (year, kind) to decide on news searches.
                director.LAST_STORY.clear()
                director.LAST_STORY.update(brief or {})

            def part_progress(done, n):
                # The parent sums these across parts for the app's progress bar.
                try:
                    runpod.serverless.progress_update(job, {"done": done, "total": n})
                except Exception:  # noqa: BLE001 - progress must never kill a part
                    pass

            media.reset_cache()
            media.set_youtube_only(bool(inp.get("youtube_only")))
            if inp.get("allow_youtube") is not False:
                _require_youtube()      # a blocked machine fails fast; the parent redoes its part
            media.limit_generation(inp.get("image_budget", config.IMAGE_MAX_PER_VIDEO))

            def source_part(jobs, w, seqs, exclude):
                b = inp.get("brief") or {}

                # A part only finds; the parent fills gaps (spare pool moments,
                # then its own pass), so no rescue or refill time box here.
                def find(lines, ex):
                    return media.source_many(
                        lines, w, workers=config.SOURCE_WORKERS, on_done=part_progress,
                        rescue=None, refill=False,
                        sequences=seqs or None,
                        assign=lambda ls, pool: director.assign_shots(ls, pool, story=b),
                        exclude=ex, allow_youtube=inp.get("allow_youtube"),
                        allow_stock=inp.get("allow_stock"), require_cc=inp.get("require_cc"))
                if inp.get("pools"):
                    # This part pools its own subjects first (POOLS_IN_PARTS).
                    rc = bool(inp["require_cc"] if inp.get("require_cc") is not None else config.REQUIRE_CC)
                    return _source_with_pools(jobs, w, require_cc=rc, exclude=set(exclude), source_rest=find)[0]
                return find(jobs, exclude)
            out = fanout.run_part(inp, work, source_part, set_story)
            return {"ok": True, "action": "source_part", **out,
                    "costs": costs.summary(time.time() - started),
                    "events": events.summary(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "render_chunk" and inp.get("upload") == "r2":
            # One chunk of a pod's spread render (fanout.render_pod): the pod's
            # finished document by link (stills already cleaned, gaps filled - so
            # every machine draws the same frames); picture and sound slice go
            # back through R2. Never touches the project.
            def pod_chunk_progress(frac):
                try:
                    runpod.serverless.progress_update(job, {"frac": round(frac, 3)})
                except Exception:  # noqa: BLE001 - progress must never kill a chunk
                    pass
            out = fanout.run_pod_chunk(inp, work, pod_chunk_progress)
            return {**out, "action": "render_chunk",
                    "costs": costs.summary(time.time() - started),
                    "events": events.summary(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "render_chunk":
            # One frame range of a split render, queued by its parent (src/fanout.py).
            doc = inp.get("timeline") or {}
            _sanitize_stills(doc, work)
            _fill_missing_media(doc)

            def chunk_progress(frac):
                try:
                    runpod.serverless.progress_update(job, {"frac": round(frac, 3)})
                except Exception:  # noqa: BLE001 - progress must never kill a chunk
                    pass

            def render_chunk(frames, path, muted, codec):
                return renderer.render(doc, path, composition=inp.get("composition", "Main"),
                                       concurrency=config.RENDER_CONCURRENCY, serve_dir=work,
                                       on_progress=chunk_progress, frames=frames,
                                       muted=muted, codec=codec)
            out = fanout.run_chunk(inp, work, render_chunk)
            return {"ok": True, "action": "render_chunk", **out,
                    "costs": costs.summary(time.time() - started),
                    "events": events.summary(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "selftest":
            out = selftest.run(work, width=int(inp.get("width", 854)), report=report)
            return {"ok": out.get("ok", False), "action": "selftest", **out,
                    "elapsed": round(time.time() - started, 1)}

        if action == "pack_build":
            # Build or refresh one niche's footage pack (src/packbuild.py, scripts/build_pack.py):
            # NASA, Wikimedia Commons, the Internet Archive and - with "library" in sources and a
            # running project - the owner's unused library clips; nothing else. Touches no project.
            from src import packbuild
            lib = None
            if inp.get("project_id") and "library" in (inp.get("sources") or []) and not inp.get("dry_run"):
                storage.CURRENT_JOB[0] = job_id           # the broker authorises the running job only
                lib = library.Library(inp["project_id"], job_id)
                if not (lib.enabled and lib._load_db()):
                    lib = None
            out = packbuild.run(
                str(inp.get("niche") or ""), max_clips=int(inp.get("max_clips") or 40),
                sources=inp.get("sources") or None, dry_run=bool(inp.get("dry_run")),
                resolve=bool(inp.get("resolve")), seconds=float(inp.get("seconds") or 1500),
                library=lib, parallel=int(inp.get("parallel") or 2), work=work, report=report)
            return {**out, "ok": bool(out.get("ok", True)), "action": "pack_build",
                    "elapsed": round(time.time() - started, 1)}

        if action == "restore_media":
            # A project's stored media put back under the links its timeline
            # already has (src/restore.py). It reads the timeline and writes
            # files only: the project row is never written, and a failure
            # here never marks the project failed (the except below would).
            events.phase("restore")
            try:
                out = do_restore(inp, work, report)
            except Exception as e:  # noqa: BLE001 - reported in the result, the project is not touched
                traceback.print_exc()
                out = {"ok": False, "error": str(e)[:800]}
            return {**out, "action": "restore_media", "events": events.summary(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "health":
            # Include the storage preflight: a missing bucket or bad key is
            # otherwise only discovered at the upload step, after the render.
            store = storage.check(inp.get("bucket"))
            return {"ok": True, "status": "ready",
                    "sourcePolicy": "stock_allowed" if config.ALLOW_STOCK else "no_stock",
                    "director": bool(config.DIRECTOR_API_KEY),
                    "imageModel": bool(config.IMAGE_API_KEY),
                    "imageModelName": config.IMAGE_MODEL if config.IMAGE_API_KEY else "",
                    "preferGenerated": config.PREFER_GENERATED_IMAGES,
                    "imageCapPerVideo": config.IMAGE_MAX_PER_VIDEO,
                    "storage": store,
                    "readyToRender": store.get("ok", False),
                    "parallelWorkers": fanout.readiness(config.FANOUT_MIN_SCENES),
                    # A pod's render spread over these workers (POD_RENDER_FANOUT) and the
                    # renderer version a chunk must match (render.renderer_fingerprint).
                    "podRender": fanout.pod_render_ready(),
                    "renderer": renderer.renderer_fingerprint(),
                    "x264Preset": renderer.x264_preset() or "medium",
                    "machine": _machine(),
                    "potProvider": media.pot_provider_alive(),
                    **({} if media.pot_provider_alive() else {"potLog": media.pot_provider_log()}),
                    # The baked-in CPU models (Dockerfile: scripts/fetch_models.py).
                    "localVision": localvision.available(),
                    "upscaler": upscale.available(),
                    "r2": r2.enabled(),
                    # Script -> video: whether a script-only job can have its narration made here.
                    "freeVoice": tts.status(),
                    # The footage library's own bucket (src/libstore.py) and scene media on R2.
                    "r2Library": r2.library_enabled(),
                    "r2SceneMedia": _scene_media_on_r2(),
                    # How a long render runs from this machine: whether it is one of the endpoint's
                    # own workers, the chunks a spread render is cut into, and the CPUs a render gets.
                    "spread": {"parentIsWorker": fanout.parent_is_worker(), "chunks": fanout.spread_chunks(),
                               "cpus": renderer.cpus(),
                               "wholeRenderLimitSeconds": int(config.RENDER_TIMEOUT_MAX_SECONDS)},
                    # Real download check per route: {"probe_youtube": true}.
                    "proxies": media.proxy_snapshot(),
                    **({"youtube": media.probe_youtube()} if inp.get("probe_youtube") else {}),
                    # One real model call, so only on request: {"probe": true}.
                    **({"vision": vision.probe()} if inp.get("probe") else {})}

        if project_id:
            storage.patch_project(project_id, {
                "status": "rendering", "job_id": job_id,
                "progress": 0, "error_message": None,
            })

        if action in ("plan", "build", "resource"):
            _require_ai_credit()
            if inp.get("allow_youtube") is not False:
                report("Checking the YouTube connection", 2)
                _require_youtube()

        if action in ("plan", "build") and project_id:
            # Old library clips are checked and moved to R2 in the background
            # while the narration is transcribed; the footage search waits for
            # it briefly (library.start_maintenance / Library.load).
            library.start_maintenance(project_id, job_id, inp.get("media_bucket") or config.MEDIA_BUCKET)

        if action == "plan":
            doc = do_plan(inp, work, report)
            _sanitize_videos(doc)
            _no_repeats(doc, report)            # the last look before the editor gets it
            _keep_in_library(doc, report)
            ledger.note(doc)                    # while the photos are still here to hash
            # Without this the timeline points at files this job is about to
            # delete. See publish_media().
            if project_id and inp.get("publish_media", True):
                report("Saving sourced media", 66)
                events.phase("publish")
                publish_media(doc, project_id,
                              inp.get("media_bucket") or config.MEDIA_BUCKET, report,
                              job_id=job_id)
                # Pick-a-shot: each scene's runner-ups go up too, so the editor can swap in one at once.
                _publish_choices(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                                 job_id, work, report)
            library._strip_local_alternatives(doc)      # no work-dir path ever reaches the saved timeline
            if project_id:
                storage.patch_project(project_id, {
                    "scene_data": doc, "status": "editing",
                    "current_step": "Timeline ready", "progress": 68,
                })
                ledger.save(ledger_job, project_id)     # later videos never show these moments again
            summary = _finish_costs(doc, started)
            return {"ok": True, "action": "plan", "timeline": doc, "costs": summary,
                    **_narration_fields(doc),
                    "events": doc["meta"]["events"],
                    "vision": vision.stats(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "resource":
            doc, candidates = do_resource(inp, work, report)
            if project_id:
                storage.patch_project(project_id, {
                    "scene_data": doc, "status": "editing",
                    "current_step": "Scene re-sourced", "progress": 100,
                })
            costs.measure_end()
            return {"ok": True, "action": "resource", "timeline": doc,
                    "scene_index": inp.get("scene_index"),
                    "mode": str(inp.get("mode") or "replace"),
                    "candidates": candidates,
                    "costs": costs.summary(time.time() - started),
                    "events": events.summary(),
                    "vision": vision.stats(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "render":
            doc = inp.get("timeline")
            if not doc:
                raise ValueError("render requires a `timeline` document")
            # Export must not fail over one empty scene either: that was the
            # "Scene 6 still needs media before it can render" a user hit
            # pressing Render. The quality check before the render (do_render,
            # src/quality.py) gives every empty or broken scene a picture -
            # the fallback ladder first, here with this timeline's story and
            # the project's clip library - in the render copy only; the saved
            # timeline still shows the gap for Find footage.
            doc = copy.deepcopy(doc)
            meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
            bucket = inp.get("media_bucket") or config.MEDIA_BUCKET
            # A scene the quality check repairs may take a clip from the niche
            # packs of the timeline's own story (src/packs.py).
            packs.use_job(brief=meta.get("story") if isinstance(meta.get("story"), dict) else None,
                          style=str(meta.get("videoStyle") or ""))
            quality.set_context(
                ladder=True, story=meta.get("story") if isinstance(meta.get("story"), dict) else None,
                require_cc=bool(inp["require_cc"] if inp.get("require_cc") is not None else config.REQUIRE_CC),
                allow_generated=config.QUALITY_REPAIR_GENERATED,
                library_loader=(lambda: library.Library.load(project_id, job_id, bucket)) if project_id else None)
            # Editor renders are split across every worker too. They used to
            # render the whole video on one worker: a 15-minute video took
            # 15 minutes of one CPU and then failed on one broken clip.
            split = bool(project_id and fanout.render_enabled(doc, project_id))
            out = do_render(doc, inp, work, report, split=split)
            if project_id:
                # Before the done write: the broker takes rows only while the project renders.
                library.record_shown(doc, project_id, job_id)
            if project_id and not inp.get("_caller_writes_result"):
                storage.patch_project(project_id, _done_fields(out))
            if project_id:
                ledger.save(ledger_job, project_id, doc=doc)    # the edited, rendered video's own shots
            costs.measure_end()
            return {"ok": True, "action": "render", **out,
                    "render_manifest": media.LAST_STATS.get("render_manifest"),
                    "costs": costs.summary(time.time() - started),
                    "events": events.summary(),
                    "filledScenes": sum(1 for r in (out.get("quality") or {}).get("repairs") or []
                                        if r.get("problem") == "empty"),
                    "elapsed": round(time.time() - started, 1)}

        if action == "build":
            doc = do_plan(inp, work, report)
            _sanitize_videos(doc)
            _no_repeats(doc, report)            # the last look before the render and the editor
            _keep_in_library(doc, report)
            ledger.note(doc)                    # while the photos are still here to hash
            if project_id:
                # Saved before the render: a failure there keeps the search.
                storage.patch_project(project_id, {"scene_data": doc}, wait=True)
            # Render from the local files (fast), THEN save the clips, so the
            # finished video opens in the editor with every scene replaceable.
            local_doc = copy.deepcopy(doc)
            LAST_TIMELINE.clear()
            LAST_TIMELINE.update(doc)
            patched = _fill_missing_media(local_doc)
            if patched:
                print(f"[worker] {patched} scene(s) had no media; reused a "
                     "nearby clip so the render could complete", flush=True)
            split = (project_id and inp.get("publish_media", True)
                     and fanout.render_enabled(doc, project_id))
            # The quality check before the render repairs with this job's own
            # plan: its lines, clip library, spare pool moments and flags.
            quality.set_context(ladder=True, plan=True, allow_generated=config.QUALITY_REPAIR_GENERATED)
            if split:
                # Long video: save the clips first so every worker can fetch
                # them, then render in chunks across the workers.
                publish_media(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                              report, job_id=job_id, band=(62, 69))
                local_doc = copy.deepcopy(doc)
                _fill_missing_media(local_doc)
                out = do_render(local_doc, inp, work, report, split=True)
            else:
                out = do_render(local_doc, inp, work, report)
            if isinstance(out.get("quality"), dict):
                # What the check found and repaired, with the saved timeline -
                # and the scenes it replaced in the video flagged for the editor.
                doc.setdefault("meta", {})["quality"] = out["quality"]
                quality.mark_for_review(doc, out["quality"])
            if isinstance(out.get("review"), dict):
                # The AI review's report with the saved timeline too. A clip it swapped for the
                # scene's own other choice is swapped on the saved timeline as well, so the editor
                # and a later render show what the video shows (review.carry_swaps): its file is
                # saved with the others below, or now when they were saved before the render - a
                # swap whose file cannot be saved is taken back there. The rest it changed or
                # found is marked for the editor.
                doc.setdefault("meta", {})["review"] = out["review"]
                carried = review.carry_swaps(doc, local_doc, out["review"])
                if carried and split:
                    count = doc["meta"].get("publishedMedia")
                    try:
                        n = publish_media(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                                          report, job_id=job_id, band=(93, 94))
                        if isinstance(count, int):
                            doc["meta"]["publishedMedia"] = count + n
                    except Exception as e:  # noqa: BLE001 - the video is done; the saved clips stay as they were
                        print(f"[review] swapped clips not saved: {type(e).__name__}: {str(e)[:120]}", flush=True)
                    review.unsaved_back(doc, carried)
                review.mark_for_review(doc, out["review"], carried=carried)
            if not split and project_id and inp.get("publish_media", True):
                publish_media(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                              report, job_id=job_id, band=(93, 99))
            if project_id:
                # Every shown clip into the app's library, before the done write (the broker
                # takes rows only while the project renders).
                library.record_shown(doc, project_id, job_id)
            if project_id and not inp.get("_caller_writes_result"):
                storage.patch_project(project_id, _done_fields(out))
            if project_id:
                ledger.save(ledger_job, project_id)     # later videos never show these moments again
            summary = _finish_costs(doc, started)
            return {"ok": True, "action": "build", "timeline": doc, **out, "costs": summary,
                    **_narration_fields(doc),
                    "events": doc["meta"]["events"],
                    **({"frames": list(LAST_FRAMES)} if inp.get("return_frames") else {}),
                    "vision": vision.stats(),
                    "elapsed": round(time.time() - started, 1)}

        return {"ok": False, "error": f"unknown action '{action}'"}

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg = str(e)
        if renderer.has_markup(msg):
            # Whatever failed, the project's error message is never a raw web
            # page (a storage 404 page was one, 2026-10-04).
            msg = renderer.plain_error(msg)
        msg = msg[:800]
        # A render that failed still says what its quality check found and did.
        gate = quality.LAST.get("gate")
        checked = gate.finish() if gate is not None else None
        # A restore is not the project's job: whatever breaks in it, the
        # project row is never written (never marked failed) - src/restore.py.
        if project_id and action != "restore_media":
            # The broker takes events only while the project is "rendering":
            # send them before the status changes, or a failed job has no log.
            try:
                events.flush(storage.broker_events)
            except Exception:  # noqa: BLE001
                pass
            if not inp.get("_caller_writes_result"):
                storage.patch_project(project_id, {
                    "status": "failed", "error_message": msg, "current_step": "Failed",
                })
        return {"ok": False, "error": msg, "elapsed": round(time.time() - started, 1),
                **({"quality": checked} if checked else {}),
                **({"frames": list(LAST_FRAMES)} if inp.get("return_frames") and LAST_FRAMES else {}),
                **({"timeline": dict(LAST_TIMELINE)} if inp.get("return_frames") and LAST_TIMELINE else {})}
    finally:
        # Stragglers a time box left running get a bounded moment to finish
        # before the work directory goes and the next job starts.
        media.drain_pools(config.DRAIN_SECONDS)
        _restore_config(config_before)
        kit_scope.__exit__(None, None, None)
        quality.reset()
        events.phase("")
        try:
            events.flush(storage.broker_events)
        except Exception:  # noqa: BLE001
            pass
        # A spread render's chunk files are deleted from R2 in the background;
        # a serverless worker is frozen once its job returns, so wait a moment
        # for that (a failed render got here seconds after it started them).
        try:
            fanout.finish_cleanup(20.0)
        except Exception:  # noqa: BLE001 - leftover chunks are only storage
            pass
        report.finish()
        # Serverless workers are reused; a 17-minute render leaves GBs behind.
        if not inp.get("keep_workdir"):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
