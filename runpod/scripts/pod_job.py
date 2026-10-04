"""
One video on a RunPod CPU pod (no serverless).

JOB_URL (a signed link to the job JSON, as the app's video-v2 function
launches pods - a render's timeline is too big for an environment variable)
or JOB_B64 = base64 of {"id": "pod-...", "input": {...}} - the same input the
app's video-v2 function sends. An id of "pod-self" becomes "pod-<this pod's
id>", which is what the app records as the project's job. The handler runs once; the result is written into the
project through the app's broker (status, video, timeline), then this pod stops
itself so nothing is billed after the video is done (the pod volume is kept).
"""
import base64
import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import handler  # noqa: E402
from src import config, storage  # noqa: E402


def load_job() -> dict:
    """The job: JOB_URL (retried, the app's storage can be slow) or JOB_B64."""
    url = os.environ.get("JOB_URL", "")
    if url:
        last = None
        for attempt in range(6):
            try:
                r = requests.get(url, timeout=60)
                if r.status_code == 200:
                    job = r.json()
                    break
                last = f"HTTP {r.status_code}"
            except (requests.RequestException, ValueError) as e:
                last = type(e).__name__
            time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"could not load the job from JOB_URL ({last})")
    else:
        job = json.loads(base64.b64decode(os.environ["JOB_B64"]))
    if str(job.get("id") or "") in ("", "pod-self"):
        job["id"] = "pod-" + os.environ.get("RUNPOD_POD_ID", "unknown")
    return job


def _cancel_chunks() -> None:
    """Cancel the serverless render chunks this pod still has queued or running (src/fanout.py render_pod)."""
    try:
        from src import fanout
        n = fanout.cancel_live_jobs()
        if n:
            print(f"[pod] cancelled {n} render chunk job(s) still on the workers", flush=True)
    except Exception as e:  # noqa: BLE001 - never blocks the pod's own exit
        print(f"[pod] could not cancel render chunks: {type(e).__name__}", flush=True)


def stop_this_pod(terminate: bool = False) -> None:
    """Stop this pod, or terminate it (the app's pods: nothing left to keep)."""
    pod = os.environ.get("RUNPOD_POD_ID", "")
    key = os.environ.get("POD_STOP_KEY") or config.FANOUT_API_KEY or os.environ.get("RUNPOD_API_KEY", "")
    if not (pod and key):
        print("[pod] no pod id or key; not stopping", flush=True)
        return
    for attempt in range(3):
        try:
            if terminate:
                r = requests.delete(f"https://rest.runpod.io/v1/pods/{pod}",
                                    headers={"Authorization": f"Bearer {key}"}, timeout=30)
            else:
                r = requests.post(f"https://rest.runpod.io/v1/pods/{pod}/stop",
                                  headers={"Authorization": f"Bearer {key}"}, timeout=30)
            print(f"[pod] {'terminate' if terminate else 'stop'} requested: HTTP {r.status_code}", flush=True)
            if r.status_code < 400:
                return
        except requests.RequestException as e:
            print(f"[pod] stop failed: {type(e).__name__}", flush=True)
        time.sleep(5)


def audit_rows(timeline: dict) -> list:
    """One row per scene: what it shows and where from (source, title, URL, moment, scores, review)."""
    rows = []
    fps = max(1, int((timeline or {}).get("fps") or 30))
    for i, s in enumerate((timeline or {}).get("scenes") or []):
        m = s.get("media") or {}
        sem = s.get("semanticMetadata") or {}
        rows.append({"i": i, "start": round(int(s.get("startFrame") or 0) / fps, 2),
                     "seconds": round(int(s.get("durationInFrames") or 0) / fps, 2),
                     "text": (s.get("text") or "")[:200], "type": m.get("type"), "source": m.get("source"),
                     "title": (m.get("attribution") or "")[:160], "sourceUrl": sem.get("sourceUrl") or "",
                     "assetId": sem.get("assetId") or "", "moment": sem.get("moment") or {},
                     "query": s.get("query") or "", "intent": (sem.get("intent") or "")[:200],
                     "relevance": sem.get("relevanceScore"), "quality": sem.get("qualityScore"),
                     "finalScore": sem.get("finalScore"), "scoreParts": sem.get("scoreParts") or {},
                     "description": (sem.get("contentDescription") or "")[:300],
                     "review": s.get("reviewReason") or ""})
    return rows


def save_adhoc_result(job: dict, out: dict) -> str:
    """
    A test or benchmark job (no project) keeps its result for an audit: the
    job result - timeline with its meta (sourcing stats, per-scene media) -
    plus a per-scene audit table, as projects/adhoc/<job id>/result.json in
    the R2 videos bucket. Returns the public URL ("" when R2 is off or it failed).
    """
    from src import r2
    if not r2.enabled():
        return ""
    job_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(job.get("id") or "job"))[:80]
    body = dict(out)
    if isinstance(out.get("timeline"), dict):
        body["audit"] = audit_rows(out["timeline"])
    try:
        data = json.dumps(body, default=str, separators=(",", ":")).encode("utf-8")
        url = r2.upload_bytes(data, f"projects/adhoc/{job_id}/result.json", content_type="application/json",
                              deadline=time.time() + 120, cache_control="no-store")
        print(f"[pod] job result saved for the audit: {url}", flush=True)
        return url
    except Exception as e:  # noqa: BLE001 - an audit copy never fails the job
        print(f"[pod] could not save the job result to R2: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return ""


def after_job(safe: bool, kept: bool, laptop_has_it, wait_seconds: float, sleep=time.sleep) -> str:
    """
    "stop" or "stay" once the job is over. The owner: never turn the pod off
    unless the video is safe - a stopped pod's disk is wiped, and on 2026-09-28
    that took a finished 22-minute render with it.

    safe: the video is in the app (uploaded and the project row updated).
    kept: a copy sits in RENDER_KEEP_DIR, served to the laptop (src/podfetch.py).
    Not safe but kept: stay up serving it, until someone stops the pod by hand.
    Safe and kept: give the laptop up to `wait_seconds` to finish its copy, then stop.
    Nothing kept: stop (there is nothing to save).
    """
    if kept and not safe:
        return "stay"
    if kept and laptop_has_it is not None:
        until = time.time() + wait_seconds
        while time.time() < until and not laptop_has_it():
            sleep(10)
    return "stop"


def main() -> None:
    # The app's pods (POD_EXIT=terminate) never outlive POD_MAX_SECONDS (5 h by
    # default; a 22-minute video takes about 2 h): a hung job stops billing.
    cap = float(os.environ.get("POD_MAX_SECONDS", "") or (18000 if os.environ.get("POD_EXIT") == "terminate" else 0))
    if cap > 0:
        import threading

        def _deadline():
            time.sleep(cap)
            print(f"[pod] over the {int(cap // 60)} min limit: stopping this pod", flush=True)
            _cancel_chunks()
            stop_this_pod()
            os._exit(3)
        threading.Thread(target=_deadline, daemon=True, name="pod-deadline").start()
    try:
        job = load_job()
    except Exception as e:  # noqa: BLE001
        # Nothing to run: stop now instead of idling (and billing) forever. The
        # app's status check then sees the pod gone and marks the job failed.
        print(f"[pod] could not load the job: {type(e).__name__}: {e}", flush=True)
        stop_this_pod()
        return
    inp = job.setdefault("input", {})
    pid = inp.get("project_id") or ""
    # This script records the final status itself (one waited, retried write).
    # The handler's own terminal write would move the row off "rendering" first,
    # the broker would then refuse this one, and the pod would read the video as
    # not safe and never stop.
    inp["_caller_writes_result"] = True
    started = time.time()
    token = os.environ.get("POD_FETCH_TOKEN", "")
    fetch = None
    if token and config.RENDER_KEEP_DIR:
        from src import podfetch
        try:
            fetch = podfetch.start(config.RENDER_KEEP_DIR, token, int(os.environ.get("POD_FETCH_PORT", "8888")))
            print("[pod] serving the finished video to the laptop when it is ready", flush=True)
        except OSError as e:
            print(f"[pod] could not serve the video for the laptop: {e}", flush=True)
    try:
        out = handler.handler(job)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    # A spread render's worker chunks never outlive the pod's job.
    _cancel_chunks()
    if not isinstance(out, dict):
        out = {"ok": False, "error": "the job returned no result"}
    # handler() cleared nothing about the job id; the final write is still this job's.
    storage.CURRENT_JOB[0] = job.get("id") or ""
    if out.get("ok") is False or out.get("error"):
        fields = {"status": "failed", "current_step": "Failed",
                  "error_message": str(out.get("error") or "failed")[:800]}
    else:
        # duration_seconds is an INTEGER column: 720.92 was refused by the
        # database on every retry, so the app never heard the video was done and
        # showed 99% forever (2026-10-01, and the Glen Canyon pod run before it).
        try:
            seconds = int(round(float(out.get("duration"))))
        except (TypeError, ValueError):
            seconds = None
        fields = {"status": "done", "progress": 100, "current_step": "Completed",
                  "video_url": out.get("video_url") or "", "render_path": out.get("object_path") or "",
                  "duration_seconds": seconds,
                  "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if isinstance(out.get("timeline"), dict):
            fields["scene_data"] = out["timeline"]
        if isinstance(out.get("render_manifest"), dict):
            fields["render_manifest"] = out["render_manifest"]
    kept = bool(config.RENDER_KEEP_DIR) and os.path.isfile(os.path.join(config.RENDER_KEEP_DIR, "final.mp4"))
    if fields["status"] == "failed" and kept:
        fields["error_message"] = (fields["error_message"] + " | The finished video is kept on the pod; "
                                   "it stays on until it is saved.")[:800]
    # The small "video is ready" fields first, the (~1 MB) timeline after, each sent
    # straight to the broker - not behind the progress updates queued on the one
    # background writer. On 2026-09-29 the single combined write waited out its
    # 240 s behind that queue, the pod stopped, and the app never learned that the
    # 1.2 GB video had uploaded. The app's database can be down for minutes, so
    # each write is retried.
    big = {k: fields.pop(k) for k in ("scene_data", "render_manifest") if k in fields}

    def write(f: dict, seconds: float) -> bool:
        until = time.time() + seconds
        while True:
            if storage.broker_enabled() and storage.CURRENT_JOB[0]:
                done = storage._broker_patch(pid, storage.CURRENT_JOB[0], f)
            else:
                done = storage.patch_project(pid, f, wait=True)
            if done or time.time() >= until:
                return done
            time.sleep(15)

    if not pid:
        # No project (a health check or a benchmark): nothing to record in the
        # app - the result goes to R2 for an audit instead.
        big = {}
        save_adhoc_result(job, out)
    if big:
        # While the row is still "rendering": the broker refuses writes once it is done.
        if not write(big, 300):
            print("[pod] could not save the finished timeline to the app (the video itself is next)", flush=True)
    ok = write(fields, 600) if pid else True
    succeeded = fields["status"] == "done"
    safe = succeeded and ok
    if str(inp.get("action") or "").lower() == "batch" and isinstance(out.get("total"), int):
        # A batch (src/batch.py) wrote each video's own row itself, and every video it made is in R2 already:
        # what this pod keeps is safe once every finished video's row is saved. A video of the batch that
        # failed keeps nothing up (nothing of it to keep); the pod is deleted only when every video is done.
        ok = all(d.get("saved") for d in out.get("done") or [] if isinstance(d, dict) and d.get("project"))
        succeeded = out.get("ok") is True
        safe = ok
    print(f"[pod] job finished in {int(time.time() - started)}s: {fields.get('status')} "
          f"(project updated: {ok}) {str(out.get('video_url') or out.get('error') or '')[:160]}", flush=True)
    if fetch:
        fetch.set_job("done" if succeeded and ok else "failed", "" if succeeded else fields.get("error_message", ""))
    decision = after_job(safe, kept, fetch.laptop_has_it if fetch else None,
                         float(os.environ.get("POD_FETCH_WAIT_SECONDS", "1800")))
    if decision == "stay":
        cap = float(os.environ.get("POD_STAY_MAX_SECONDS", "0") or 0)
        print("[pod] the video is not safe in the app yet: staying up and serving it "
              + (f"for up to {int(cap // 60)} min" if cap else "(stop this pod by hand once the video is saved)"),
              flush=True)
        until = time.time() + cap if cap else float("inf")
        while time.time() < until:
            time.sleep(min(600, max(1, until - time.time())))
    # The app's pods are deleted once the video is safe (nothing left to keep,
    # nothing billed); a failed one is only stopped, so its log can be read.
    stop_this_pod(terminate=os.environ.get("POD_EXIT") == "terminate" and succeeded and ok)


if __name__ == "__main__":
    main()
