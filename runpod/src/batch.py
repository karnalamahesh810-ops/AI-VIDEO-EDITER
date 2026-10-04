"""
Batch mode: several videos queued as one job, built one after another on the
same machine.

    {"action": "batch", "jobs": [<build input>, <build input>, ...], "max_parallel": 1}

Each entry of `jobs` is a normal build input - exactly what a single "build"
job carries (project_id, audio, script, style, config...). The batch hands them
to the handler one at a time (handler.handler, the same dispatch a single job
goes through), so every video gets its own config overrides, cost ledger, event
log and progress in its own project row, as if it had been queued alone. A
build that fails is recorded and the next one starts: one bad video never
costs the rest of the night's queue.

What the batch adds around each build:

  * the project rows of the videos still waiting say so ("Waiting for its turn
    (video 3 of 5)") instead of sitting at 0% with no word;
  * each video's final state - done with its link and timeline, or failed with
    its error - is written into its project by the batch itself, waited for and
    retried, the way a pod job records its one video (scripts/pod_job.py): a
    batch outlives no caller that would do it, and the machine may stop right
    after the last video. A write that never got through is tried once more
    at the end, and a batch that stops on an error of its own still marks
    every video it did not finish as failed: no project is left "rendering";
  * each video keeps its own record in the cross-video ledger (src/ledger.py
    files are named by job id, and the videos of a batch share one): later
    videos never reuse what any of them showed;
  * the same project twice in one batch is built once (a second build would
    pay for the same video again and overwrite the first);
  * a summary: {done: [...], failed: [{project, error}], total_cost, seconds},
    printed as the event batch/summary.

One at a time, on purpose. A build keeps its state module-wide (the config
overrides, the cost ledger, the event log, the storage job id), so two builds
in one process would write into each other's project; "max_parallel" and
config.BATCH_MAX_PARALLEL are honoured up to IN_PROCESS (1). Running builds
side by side needs one process per build - not built yet.

Every project of a batch must carry the batch job's own id as its job (the
app writes it when it queues the batch): the storage broker authorises a
project's updates by the job running for it.
"""
import copy
import time
import traceback
from typing import Callable, Dict, List, Optional

from . import config, costs, events, storage

IN_PROCESS = 1                  # builds this worker can run side by side in one process (see the module's note)
BIG_WRITE_SECONDS = 300.0       # how long the finished timeline may take to reach the app (retried)
STATUS_WRITE_SECONDS = 600.0    # how long the final status may take (the app's database can be down for minutes)
LAST_TRY_SECONDS = 60.0         # the one more try, at the end of the batch, for a final state that never got through
RETRY_SECONDS = 15.0


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parallel_for(asked) -> int:
    """How many builds run side by side: what was asked, never above config.BATCH_MAX_PARALLEL or IN_PROCESS."""
    return max(1, min(_int(asked, 1), _int(config.BATCH_MAX_PARALLEL, 1), IN_PROCESS))


def result_fields(out: dict) -> tuple:
    """
    (status fields, big fields) for a project row from a build's result: failed with its error, or
    done with the video's link and length - and the finished timeline and render manifest, which
    go first and separately (about 1 MB; the app takes them only while the row still says rendering).
    """
    if out.get("ok") is False or out.get("error"):
        return {"status": "failed", "current_step": "Failed",
                "error_message": str(out.get("error") or "failed")[:800]}, {}
    try:
        # duration_seconds is an INTEGER column: a fractional length is refused by the database.
        seconds = int(round(float(out.get("duration"))))
    except (TypeError, ValueError):
        seconds = None
    small = {"status": "done", "progress": 100, "current_step": "Completed",
             "video_url": out.get("video_url") or "", "render_path": out.get("object_path") or "",
             "duration_seconds": seconds,
             "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    big = {}
    if isinstance(out.get("timeline"), dict):
        big["scene_data"] = out["timeline"]
    if isinstance(out.get("render_manifest"), dict):
        big["render_manifest"] = out["render_manifest"]
    return small, big


def _can_write() -> bool:
    return bool(storage.broker_enabled() or (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY))


def _write(project_id: str, job_id: str, fields: dict, seconds: float, sleep: Callable = time.sleep) -> bool:
    """One project write, waited for and retried until `seconds` have passed. False when it never got through."""
    if not project_id or not _can_write():
        return False
    until = time.time() + seconds
    while True:
        if storage.broker_enabled() and job_id:
            done = storage._broker_patch(project_id, job_id, fields)
        else:
            done = storage.patch_project(project_id, fields, wait=True)
        if done or time.time() >= until:
            return bool(done)
        sleep(RETRY_SECONDS)


def record(project_id: str, job_id: str, out: dict, sleep: Callable = time.sleep,
           seconds: tuple = (BIG_WRITE_SECONDS, STATUS_WRITE_SECONDS)) -> bool:
    """
    A build's final state into its project row (the timeline first, then the status), each write retried for
    up to its `seconds`. True when the status is there. Never raises.
    """
    if not project_id:
        return False
    try:
        small, big = result_fields(out)
        # The handler leaves the job id in place; the final write is still this job's.
        storage.CURRENT_JOB[0] = job_id
        if big and not _write(project_id, job_id, big, seconds[0], sleep):
            print(f"[batch] could not save the finished timeline of project {project_id} (its status is next)",
                  flush=True)
        return _write(project_id, job_id, small, seconds[1], sleep)
    except Exception as e:  # noqa: BLE001 - one row's write never stops the batch
        print(f"[batch] could not record project {project_id}: {type(e).__name__}: {str(e)[:160]}", flush=True)
        return False


def _merged(defaults: dict, raw: dict) -> dict:
    """An entry over the batch's defaults (a copy); a "config" in both is merged, the entry's own keys winning."""
    sub = copy.deepcopy({**defaults, **raw})
    if isinstance(defaults.get("config"), dict) and isinstance(raw.get("config"), dict):
        sub["config"] = copy.deepcopy({**defaults["config"], **raw["config"]})
    return sub


def ledger_id(job_id: str, n: int) -> str:
    """
    Video n's own name in the cross-video ledger (src/ledger.py writes ledger/jobs/<name>.json): the batch's
    job id with the video's place. Under the shared job id each video's record would overwrite the one
    before - and once the index holds that id, a later file under it is never read - so later videos could
    show again what these showed. (The job id is cut so the name stays within the ledger's 80 characters.)
    """
    return f"{str(job_id)[:64]}-v{int(n)}"


def _cost(out: dict, seconds: float, ran: bool) -> float:
    """What this build cost: its own summary when it finished, else the ledger it left behind (a failed build cost too)."""
    c = out.get("costs")
    try:
        if isinstance(c, dict) and c.get("total") is not None:
            return float(c["total"])
        return float(costs.summary(seconds).get("total") or 0.0) if ran else 0.0
    except (TypeError, ValueError):
        return 0.0


def _one(job: dict, raw, defaults: dict, n: int, total: int, build: Callable[[dict], dict], sleep: Callable,
         seen: Dict[str, int]) -> dict:
    """
    Run entry `n` (1-based) of the batch through the handler and record its final state in its project;
    never raises. `seen`: the projects built so far in this batch (project -> video number). Returns its row
    for the summary (with "_out", the result, while its final state is not saved yet).
    """
    t0 = time.time()
    job_id = str(job.get("id") or "")
    pid = str(raw.get("project_id") or "") if isinstance(raw, dict) else ""
    row: Dict[str, object] = {"index": n - 1, "project": pid}
    out: dict
    ran = False
    mine = True                         # this entry's final state is this entry's to write
    action = str({**defaults, **raw}.get("action") or "build").lower() if isinstance(raw, dict) else ""
    if not isinstance(raw, dict):
        out = {"ok": False, "error": "not a build input (each entry of `jobs` is an object)"}
    elif pid and pid in seen:
        # Built already in this batch: never paid for twice, and its row keeps what the first build wrote.
        out = {"ok": False, "error": f"project {pid} is already in this batch (video {seen[pid]}); built once"}
        mine = False
    elif action != "build":
        out = {"ok": False, "error": f"a batch runs builds only (this entry asks for '{action[:40]}')"}
    else:
        sub = _merged(defaults, raw)
        sub["action"] = "build"
        # The batch records each video's final state itself (record), waited for and retried.
        sub["_caller_writes_result"] = True
        if job_id:
            sub["_ledger_job"] = ledger_id(job_id, n)
        if pid:
            seen[pid] = n
        print(f"[batch] video {n} of {total}: starting project {pid or '(no project)'}", flush=True)
        ran = True
        # A fresh cost ledger (the handler starts its own too): a build that fails before it gets that far
        # is never charged what the video before it spent.
        costs.reset(sub.get("prices") if isinstance(sub.get("prices"), dict) else None)
        try:
            out = build({**{k: v for k, v in job.items() if k != "input"}, "input": sub})
        except Exception as e:  # noqa: BLE001 - one video's crash is that video's failure, not the batch's
            traceback.print_exc()
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"[:800]}
        if not isinstance(out, dict):
            out = {"ok": False, "error": "the build returned no result"}
    seconds = time.time() - t0
    failed = out.get("ok") is False or bool(out.get("error"))
    row.update(ok=not failed, seconds=round(seconds, 1), cost=round(_cost(out, seconds, ran), 4))
    if failed:
        row["error"] = str(out.get("error") or "failed")[:800]
    else:
        row.update(video_url=out.get("video_url") or "", duration=out.get("duration"))
    if pid and mine:
        row["saved"] = record(pid, job_id, out, sleep)
        if not row["saved"]:
            row["_out"] = out           # tried once more at the end of the batch
    print(f"[batch] video {n} of {total}: {'failed' if failed else 'done'} in {int(seconds)}s"
          + (f" - {row['error'][:160]}" if failed else ""), flush=True)
    return row


def run(job: dict, build: Callable[[dict], dict], sleep: Callable = time.sleep) -> dict:
    """
    The handler's action "batch". `job` is the batch job ({"id", "input": {"jobs": [...], "max_parallel",
    "defaults"}}); `build` runs one job dict and returns its result (handler.handler). "defaults" (optional)
    are input fields every entry inherits unless it sets its own (a shared config, prices, bucket).
    Returns {"ok" (every video done), "action": "batch", "total", "done": [{project, index, video_url,
    duration, seconds, cost, saved}], "failed": [{project, index, error, seconds, cost, saved}],
    "total_cost", "seconds", "parallel", "events"}.
    """
    started = time.time()
    job_id = str(job.get("id") or "")
    inp = job.get("input") if isinstance(job.get("input"), dict) else {}
    jobs = inp.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return {"ok": False, "action": "batch", "error": "a batch needs `jobs`: a list of build inputs"}
    # (Never a project, an action or a field the worker sets itself: those are each entry's own.)
    defaults = {k: v for k, v in (inp.get("defaults") if isinstance(inp.get("defaults"), dict) else {}).items()
                if k not in ("jobs", "defaults", "max_parallel", "project_id", "action") and not str(k).startswith("_")}
    total = len(jobs)
    asked = _int(inp.get("max_parallel"), 1)
    parallel = parallel_for(asked)
    events.start_job(job_id, "")
    print(f"[batch] {total} video(s), {parallel} at a time"
          + (f" (asked for {asked}; this worker builds one at a time)" if asked > parallel else ""), flush=True)
    # The videos still waiting say so in their own rows (never fatal; the first one starts right away).
    storage.CURRENT_JOB[0] = job_id
    for n, raw in enumerate(jobs, start=1):
        pid = str(raw.get("project_id") or "") if isinstance(raw, dict) else ""
        if n > 1 and pid:
            try:
                storage.patch_project(pid, {"current_step": f"Waiting for its turn (video {n} of {total})"})
            except Exception as e:  # noqa: BLE001 - a word on the screen, never a failure
                print(f"[batch] could not tell project {pid} it waits: {type(e).__name__}", flush=True)

    rows: List[dict] = []
    seen: Dict[str, int] = {}
    try:
        for n, raw in enumerate(jobs, start=1):
            rows.append(_one(job, raw, defaults, n, total, build, sleep, seen))
    except Exception as e:  # noqa: BLE001 - the batch's own failure: every video it did not finish says so
        traceback.print_exc()
        why = f"the batch stopped before this video was done: {type(e).__name__}: {e}"[:800]
        for n in range(len(rows) + 1, total + 1):
            raw = jobs[n - 1]
            pid = str(raw.get("project_id") or "") if isinstance(raw, dict) else ""
            row: Dict[str, object] = {"index": n - 1, "project": pid, "ok": False, "seconds": 0.0, "cost": 0.0,
                                      "error": why}
            if pid and seen.get(pid, n) == n:
                row["saved"] = record(pid, job_id, {"ok": False, "error": why}, sleep, (0.0, LAST_TRY_SECONDS))
            rows.append(row)
    # A final state that never got through (the app's database down for many minutes) gets one more try now:
    # a project left "rendering" by a batch that has moved on is the one thing it must not leave behind.
    for r in rows:
        if "_out" in r:
            r["saved"] = record(str(r["project"]), job_id, r.pop("_out"), sleep, (LAST_TRY_SECONDS, LAST_TRY_SECONDS))
            print(f"[batch] project {r['project']}: final state {'saved' if r['saved'] else 'still not saved'} "
                  "on the last try", flush=True)

    seconds = time.time() - started
    done = [{k: r.get(k) for k in ("project", "index", "video_url", "duration", "seconds", "cost", "saved") if k in r}
            for r in rows if r["ok"]]
    failed = [{k: r.get(k) for k in ("project", "index", "error", "seconds", "cost", "saved") if k in r}
              for r in rows if not r["ok"]]
    total_cost = round(sum(float(r.get("cost") or 0.0) for r in rows), 4)
    # Each build kept (and sent) its own event log; this one is the batch's.
    events.start_job(job_id, "")
    for r in rows:
        events.emit("batch", "job_done" if r["ok"] else "job_failed", level="info" if r["ok"] else "error",
                    message=f"project {r['project'] or '-'}" + (f": {r['error']}" if not r["ok"] else ""),
                    duration_ms=float(r["seconds"]) * 1000.0,
                    data={"project": r["project"], "index": r["index"], "cost": r["cost"], "saved": r.get("saved")})
    events.emit("batch", "summary", level="info" if not failed else "warning",
                message=f"{len(done)} done, {len(failed)} failed of {total} in {int(seconds)}s, ${total_cost:.2f}",
                data={"total": total, "done": len(done), "failed": len(failed), "total_cost": total_cost,
                      "seconds": round(seconds, 1), "parallel": parallel,
                      "failed_projects": [f["project"] for f in failed]})
    return {"ok": not failed, "action": "batch", "total": total, "done": done, "failed": failed,
            "total_cost": total_cost, "seconds": round(seconds, 1), "parallel": parallel,
            **({"asked_parallel": asked} if asked != parallel else {}),
            "events": events.summary()}
