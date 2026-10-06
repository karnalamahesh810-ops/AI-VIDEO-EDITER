"""
One video on a RunPod CPU pod (no serverless).

JOB_URL (a signed link to the job JSON, as the app's video-v2 function
launches pods - a render's timeline is too big for an environment variable)
or JOB_B64 = base64 of {"id": "pod-...", "input": {...}} - the same input the
app's video-v2 function sends. An id of "pod-self" becomes "pod-<this pod's
id>", which is what the app records as the project's job. The handler runs
once; the result is written into the project through the app's broker (a
plan's timeline and "editing", a build's video and "done", or "failed"), then
the pod goes, so nothing is billed after the job: the app's pods
(POD_EXIT=terminate) are deleted whether the job succeeded or failed, a pod
started by hand is stopped. Only a finished video the app does not have yet
keeps a pod up, for at most POD_STAY_MAX_SECONDS (src/podfetch.py serves it),
and a result the app's database would not take is written again meanwhile.
"""
import base64
import json
import math
import os
import re
import sys
import time
import traceback
from typing import Optional, Tuple

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


def _key() -> str:
    """The RunPod key this pod acts on itself with (stop, delete, its own record); never printed."""
    return os.environ.get("POD_STOP_KEY") or config.FANOUT_API_KEY or os.environ.get("RUNPOD_API_KEY", "")


def pod_price(timeout: float = 15.0) -> Tuple[Optional[float], str]:
    """
    (this pod's price in $/hour, where it came from): POD_COST_PER_HR when the
    launcher set it, else the pod's own RunPod record (costPerHr - the machine
    RunPod actually gave it: the app asks for 16 to 32 vCPUs across six
    families, $0.48 to $1.47 an hour), else (None, "") and the cost ledger
    takes a 16-vCPU pod's price. Never raises; the record (it carries the pod's
    environment, keys and all) is never printed.
    """
    raw = os.environ.get("POD_COST_PER_HR", "").strip()
    if raw:
        try:
            v = float(raw)
            if math.isfinite(v) and v > 0:
                return v, "POD_COST_PER_HR"
        except ValueError:
            pass
    pod, key = os.environ.get("RUNPOD_POD_ID", ""), _key()
    if not (pod and key):
        return None, ""
    try:
        r = requests.get(f"https://rest.runpod.io/v1/pods/{pod}", headers={"Authorization": f"Bearer {key}"},
                         timeout=timeout)
        if r.status_code == 200:
            body = r.json()
            v = float((body if isinstance(body, dict) else {}).get("costPerHr") or 0.0)
            if math.isfinite(v) and v > 0:
                return v, "runpod"
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        pass
    return None, ""


def container_age() -> float:
    """
    Seconds since this container started (its first process, PID 1, read from
    /proc): the pod's start-up before its job, billed like the rest. 0 when it
    cannot be read (not Linux) or makes no sense.
    """
    try:
        with open("/proc/uptime") as fh:
            up = float(fh.read().split()[0])
        with open("/proc/1/stat") as fh:
            stat = fh.read()
        # Field 22 (starttime, clock ticks after boot); the fields after "(name)" start at field 3.
        ticks = float(stat.rsplit(")", 1)[1].split()[19])
        age = up - ticks / float(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError, AttributeError):
        return 0.0
    return age if 0.0 <= age <= 6 * 3600 else 0.0


def price_this_pod() -> None:
    """The cost ledger prices this job's own seconds at this pod's price, its start-up included (src/costs.py)."""
    from src import costs
    rate, source = pod_price()
    boot = container_age()
    costs.use_pod(rate, boot_seconds=boot, source=source)
    print(f"[pod] priced at ${rate if rate else costs.DEFAULT_POD_USD_PER_HOUR:.3f}/h "
          f"({source or 'not known: a 16-vCPU pod'}); started {int(boot)} s before its job", flush=True)


def stop_this_pod(terminate: bool = False) -> None:
    """Stop this pod, or terminate it (the app's pods: nothing left to keep)."""
    pod = os.environ.get("RUNPOD_POD_ID", "")
    key = _key()
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


def save_adhoc_result(job: dict, out: dict, project_id: str = "") -> str:
    """
    A test or benchmark job (no project) keeps its result for an audit: the
    job result - timeline with its meta (sourcing stats, per-scene media) -
    plus a per-scene audit table, as projects/adhoc/<job id>/result.json in
    the R2 videos bucket. A project job whose result the app's database never
    took keeps it the same way, as projects/<project>/unsaved/<job id>.json,
    so it can be put back by hand. Returns the public URL ("" when R2 is off
    or it failed).
    """
    from src import r2
    if not r2.enabled():
        return ""
    job_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(job.get("id") or "job"))[:80]
    project = re.sub(r"[^A-Za-z0-9_-]+", "_", str(project_id or ""))[:80]
    key = f"projects/{project}/unsaved/{job_id}.json" if project else f"projects/adhoc/{job_id}/result.json"
    body = dict(out)
    if isinstance(out.get("timeline"), dict):
        body["audit"] = audit_rows(out["timeline"])
    try:
        data = json.dumps(body, default=str, separators=(",", ":")).encode("utf-8")
        url = r2.upload_bytes(data, key, content_type="application/json",
                              deadline=time.time() + 120, cache_control="no-store")
        print(f"[pod] job result saved for the audit: {url}", flush=True)
        return url
    except Exception as e:  # noqa: BLE001 - an audit copy never fails the job
        print(f"[pod] could not save the job result to R2: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return ""


def after_job(safe: bool, kept: bool, laptop_has_it, wait_seconds: float, sleep=time.sleep,
              unsaved: bool = False) -> str:
    """
    "stop" or "stay" once the job is over ("stop": the pod goes - deleted when
    it is one of the app's, stopped when it was started by hand). The owner:
    never turn the pod off unless the video is safe - a stopped pod's disk is
    wiped, and on 2026-09-28 that took a finished 22-minute render with it.

    safe: the job's result is in the app (the video uploaded and the project row updated).
    kept: a copy of the video sits in RENDER_KEEP_DIR, served to the laptop (src/podfetch.py).
    unsaved: the job finished but its result (a plan's timeline, a build's video link) did not
    reach the app's database: the pod stays and writes it again (main), rather than lose the work.
    Not safe and kept or unsaved: stay up (for at most POD_STAY_MAX_SECONDS when it is set).
    Safe and kept: give the laptop up to `wait_seconds` to finish its copy, then go.
    Otherwise - a plan written, a failure recorded, nothing kept: go now (nothing is left to save).
    """
    if (kept or unsaved) and not safe:
        return "stay"
    if kept and laptop_has_it is not None:
        until = time.time() + wait_seconds
        while time.time() < until and not laptop_has_it():
            sleep(10)
    return "stop"


def result_fields(action: str, out: dict) -> Tuple[dict, dict]:
    """
    (status fields, big fields) for the project row from the job's result; the
    big ones (the ~1 MB timeline, the render manifest) are written first, while
    the row still says "rendering" (the broker takes nothing after that).

    A plan (and a Replace Clip) hands back a timeline to edit: "editing" with
    the timeline - never "done", it has no video. (The handler's own queued
    "editing" write used to land first; the broker then refused this pod's
    writes, it retried them for 15 minutes and was left stopped, not deleted.)
    A build or a render: "done", the video's link and length, its timeline and
    render manifest. A failure: "failed" with its error - except a failed new
    shot, which leaves the project editing (handler.resource_failed).
    """
    error = str(out.get("error") or "failed")[:800]
    if out.get("ok") is False or out.get("error"):
        if out.get("project_status") == "editing":
            return ({"status": "editing", "current_step": str(out.get("current_step") or "No new shot")[:200],
                     "progress": 100, "error_message": error}, {})
        return {"status": "failed", "current_step": "Failed", "error_message": error}, {}
    big = {"scene_data": out["timeline"]} if isinstance(out.get("timeline"), dict) else {}
    if action in ("plan", "resource"):
        if not big:
            return {"status": "failed", "current_step": "Failed", "error_message": "The job returned no timeline."}, {}
        return {"status": "editing", "progress": 100,
                "current_step": "Storyboard ready" if action == "plan" else "Scene re-sourced"}, big
    # duration_seconds is an INTEGER column: 720.92 was refused by the
    # database on every retry, so the app never heard the video was done and
    # showed 99% forever (2026-10-01, and the Glen Canyon pod run before it).
    try:
        seconds = int(round(float(out.get("duration"))))
    except (TypeError, ValueError):
        seconds = None
    if isinstance(out.get("render_manifest"), dict):
        big["render_manifest"] = out["render_manifest"]
    return {"status": "done", "progress": 100, "current_step": "Completed",
            "video_url": out.get("video_url") or "", "render_path": out.get("object_path") or "",
            "duration_seconds": seconds,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, big


# While a pod stays up for a result the app's database would not take, it writes it again this often.
STAY_RETRY_SECONDS = 120


def main() -> None:
    # The app's pods (POD_EXIT=terminate) are deleted when the job is over,
    # whatever its outcome: a stopped pod keeps nothing (its disk is wiped) and
    # sat EXITED in the account. A pod started by hand is only stopped.
    terminate = os.environ.get("POD_EXIT") == "terminate"
    # The app's pods never outlive POD_MAX_SECONDS (5 h by default; a
    # 22-minute video takes about 2 h): a hung job stops billing.
    cap = float(os.environ.get("POD_MAX_SECONDS", "") or (18000 if terminate else 0))
    if cap > 0:
        import threading

        def _deadline():
            time.sleep(cap)
            print(f"[pod] over the {int(cap // 60)} min limit: {'deleting' if terminate else 'stopping'} this pod",
                  flush=True)
            _cancel_chunks()
            stop_this_pod(terminate=terminate)
            os._exit(3)
        threading.Thread(target=_deadline, daemon=True, name="pod-deadline").start()
    try:
        job = load_job()
    except Exception as e:  # noqa: BLE001
        # Nothing to run: gone now instead of idling (and billing) forever. The
        # app's status check then sees the pod gone and marks the job failed.
        print(f"[pod] could not load the job: {type(e).__name__}: {e}", flush=True)
        stop_this_pod(terminate=terminate)
        return
    inp = job.setdefault("input", {})
    pid = inp.get("project_id") or ""
    action = str(inp.get("action") or "build").lower()
    # This script records the final status itself (one waited, retried write).
    # The handler's own terminal write would move the row off "rendering" first,
    # the broker would then refuse this one, and the pod would read the video as
    # not safe and never stop.
    inp["_caller_writes_result"] = True
    started = time.time()
    try:
        price_this_pod()
    except Exception as e:  # noqa: BLE001 - the ledger then prices it as a serverless worker
        print(f"[pod] could not price this pod: {type(e).__name__}", flush=True)
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
    # The (~1 MB) timeline and the render manifest first, while the row still says
    # "rendering", then the small status fields, each sent straight to the broker -
    # not behind the progress updates queued on the one background writer. On
    # 2026-09-29 a single combined write waited out its 240 s behind that queue, the
    # pod stopped, and the app never learned that the 1.2 GB video had uploaded. The
    # app's database can be down for minutes, so each write is retried.
    fields, big = result_fields(action, out)
    succeeded = not (out.get("ok") is False or out.get("error"))
    kept = bool(config.RENDER_KEEP_DIR) and os.path.isfile(os.path.join(config.RENDER_KEEP_DIR, "final.mp4"))
    if fields["status"] == "failed" and kept:
        stay = float(os.environ.get("POD_STAY_MAX_SECONDS", "0") or 0)
        fields["error_message"] = (fields["error_message"] + " | The finished video is kept on the pod; it stays up "
                                   + (f"for {int(stay // 60)} minutes so it can be saved." if stay > 0
                                      else "until it is saved."))[:800]

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
    big_saved = not big
    if big:
        # While the row is still "rendering": the broker refuses writes once it is done.
        big_saved = write(big, 300)
        if not big_saved:
            print("[pod] could not save the finished timeline to the app", flush=True)
    # A plan's status waits for its timeline: "editing" over the old one would show an empty
    # storyboard as finished, and the broker takes nothing more once the row has left
    # "rendering". A build's video link goes in all the same (the video itself is in storage).
    status_waits = not big_saved and action in ("plan", "resource")
    ok = write(fields, 600) if pid and not status_waits else not pid
    safe = succeeded and ok
    batch = action == "batch" and isinstance(out.get("total"), int)
    if batch:
        # A batch (src/batch.py) wrote each video's own row itself, and every video it made is in R2 already:
        # what this pod keeps is safe once every finished video's row is saved. A video of the batch that
        # failed keeps nothing up (nothing of it to keep).
        ok = all(d.get("saved") for d in out.get("done") or [] if isinstance(d, dict) and d.get("project"))
        succeeded = out.get("ok") is True
        safe = ok
    print(f"[pod] job finished in {int(time.time() - started)}s: {fields.get('status')} "
          f"(project updated: {ok}) {str(out.get('video_url') or out.get('error') or '')[:160]}", flush=True)
    if fetch:
        fetch.set_job("done" if succeeded and ok else "failed", "" if succeeded else fields.get("error_message", ""))
    # A finished job whose result the app's database would not take (it was down longer than the retries
    # above): the pod stays and writes it again, instead of throwing a plan's timeline away.
    unsaved = succeeded and not ok and bool(pid) and not batch
    decision = after_job(safe, kept, fetch.laptop_has_it if fetch else None,
                         float(os.environ.get("POD_FETCH_WAIT_SECONDS", "1800")), unsaved=unsaved)
    if decision == "stay":
        cap = float(os.environ.get("POD_STAY_MAX_SECONDS", "0") or 0)
        what = "its result is not in the app yet: staying up and writing it again" if unsaved and not kept else \
            "the video is not safe in the app yet: staying up and serving it"
        print(f"[pod] {what} "
              + (f"for up to {int(cap // 60)} min" if cap else "(stop this pod by hand once the video is saved)"),
              flush=True)
        until = time.time() + cap if cap else float("inf")
        while time.time() < until:
            time.sleep(min(STAY_RETRY_SECONDS if unsaved else 600, max(1, until - time.time())))
            if unsaved:
                big_saved = big_saved or write(big, 0)
                if big_saved and write(fields, 0):
                    unsaved, ok = False, True
                    print("[pod] the result reached the app at last", flush=True)
                    if fetch:
                        fetch.set_job("done", "")
                    break
    if succeeded and pid and not batch and not (ok and big_saved):
        # Some of a finished result never reached the app (its timeline, or all of it): a copy in R2,
        # so the work can be put back by hand.
        save_adhoc_result(job, out, project_id=pid)
    # The pod goes now: the app's pods are deleted, finished or failed (a stopped
    # pod keeps nothing - its disk is wiped - and stays in the account as EXITED);
    # a pod started by hand is stopped.
    stop_this_pod(terminate=terminate)


if __name__ == "__main__":
    main()
