"""
Structured job events: what happened, where, to which scene, and how long
each stage took.

Every event carries the project, the job, the part (for fan-out children),
the stage, an event name, a level, and where they apply a scene index, a
provider, a failure class and a duration. They print as one compact line
each (so the log tail in the job status shows them), ride in the job result
as a summary (counts by stage and failure class, seconds per stage), and
are flushed in batches to the app's `video_job_events` table through the
storage broker, so "why did this scene fail" is answered from the database.
"""
import json
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
# One flush at a time: the heartbeat and the job's end must not send a batch twice.
_FLUSH_LOCK = threading.Lock()
_CTX: Dict[str, str] = {"project": "", "job": "", "part": ""}
_EVENTS: List[dict] = []
_PHASE: Dict[str, Any] = {"name": "", "since": 0.0}
_STAGE_SECONDS: Dict[str, float] = defaultdict(float)
_CHILD_STAGE_SECONDS: Dict[str, float] = defaultdict(float)
_CHILD_FAILURES: Dict[str, int] = defaultdict(int)
_FLUSHED = [0]
_SINK_DOWN = [False]
KEEP = 2000


def start_job(job_id: str, project_id: str = "", part: str = "") -> None:
    with _LOCK:
        _CTX.update(job=job_id or "", project=project_id or "", part=part or "")
        _EVENTS.clear()
        _PHASE.update(name="", since=time.time())
        _STAGE_SECONDS.clear()
        _CHILD_STAGE_SECONDS.clear()
        _CHILD_FAILURES.clear()
        _FLUSHED[0] = 0
        _SINK_DOWN[0] = False


def emit(stage: str, event: str, level: str = "info", scene: Optional[int] = None,
         provider: str = "", failure: str = "", message: str = "",
         data: Optional[dict] = None, duration_ms: Optional[float] = None) -> dict:
    ev = {"at": round(time.time(), 3), "project_id": _CTX["project"], "job_id": _CTX["job"],
          "part": _CTX["part"], "stage": stage, "event": event, "level": level}
    if scene is not None:
        ev["scene_index"] = int(scene)
    if provider:
        ev["provider"] = provider
    if failure:
        ev["failure_class"] = str(failure)
    if message:
        ev["message"] = message[:300]
    if duration_ms is not None:
        ev["duration_ms"] = int(duration_ms)
    if data:
        ev["data"] = {k: v for k, v in data.items() if v is not None}
    with _LOCK:
        _EVENTS.append(ev)
        if len(_EVENTS) > KEEP:
            del _EVENTS[: len(_EVENTS) - KEEP]
    bits = [f"[event] {stage}/{event}"]
    if scene is not None:
        bits.append(f"scene={scene}")
    if provider:
        bits.append(f"provider={provider}")
    if failure:
        bits.append(f"class={failure}")
    if duration_ms is not None:
        bits.append(f"ms={int(duration_ms)}")
    if message:
        bits.append(message[:120])
    if level in ("warning", "error"):
        bits.append(f"level={level}")
    print(" ".join(bits), flush=True)
    return ev


def phase(name: str) -> None:
    """Close the running stage (timing it) and open `name`."""
    now = time.time()
    with _LOCK:
        prev, since = _PHASE["name"], _PHASE["since"]
        if prev:
            _STAGE_SECONDS[prev] += now - since
        _PHASE.update(name=name, since=now)
    if prev:
        emit(prev, "end", duration_ms=(now - since) * 1000.0)
    if name:
        emit(name, "start")


def absorb(child: Optional[dict]) -> None:
    """A fan-out child's summary: its stage seconds and failures join this job's."""
    if not isinstance(child, dict):
        return
    with _LOCK:
        for k, v in (child.get("stage_seconds") or {}).items():
            try:
                _CHILD_STAGE_SECONDS[k] += float(v)
            except (TypeError, ValueError):
                pass
        for k, v in (child.get("failures_by_class") or {}).items():
            try:
                _CHILD_FAILURES[k] += int(v)
            except (TypeError, ValueError):
                pass


def summary() -> dict:
    now = time.time()
    with _LOCK:
        stages = dict(_STAGE_SECONDS)
        if _PHASE["name"]:
            stages[_PHASE["name"]] = stages.get(_PHASE["name"], 0.0) + (now - _PHASE["since"])
        failures: Dict[str, int] = defaultdict(int)
        by_stage: Dict[str, int] = defaultdict(int)
        providers: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        errors = 0
        for ev in _EVENTS:
            by_stage[ev["stage"]] += 1
            if ev.get("failure_class"):
                failures[ev["failure_class"]] += 1
                if ev.get("provider"):
                    providers[ev["provider"]]["failed"] += 1
            elif ev.get("provider") and ev["event"] in ("found", "download_ok", "search_ok"):
                providers[ev["provider"]]["ok"] += 1
            if ev.get("level") == "error":
                errors += 1
        for k, v in _CHILD_FAILURES.items():
            failures[k] += v
        return {"count": len(_EVENTS), "errors": errors,
                "stage_seconds": {k: round(v, 1) for k, v in stages.items()},
                "child_stage_seconds": {k: round(v, 1) for k, v in _CHILD_STAGE_SECONDS.items()},
                "failures_by_class": dict(failures), "by_stage": dict(by_stage),
                "providers": {p: dict(c) for p, c in providers.items()},
                "recent": [{k: v for k, v in ev.items() if k not in ("project_id", "job_id")}
                           for ev in _EVENTS[-20:]]}


def pending() -> List[dict]:
    with _LOCK:
        return list(_EVENTS[_FLUSHED[0]:])


def flush(sink) -> int:
    """
    Send the events not yet sent through `sink(project_id, job_id, events)`.
    A sink that fails is not retried in this job (one line says so).
    """
    with _FLUSH_LOCK:
        if _SINK_DOWN[0]:
            return 0
        batch = pending()
        if not batch or not _CTX["project"]:
            return 0
        try:
            sink(_CTX["project"], _CTX["job"], batch)
        except Exception as e:  # noqa: BLE001 - events must never fail a job
            _SINK_DOWN[0] = True
            print(f"[event] sink unavailable ({type(e).__name__}: {str(e)[:100]}); "
                  f"events stay in the job result only", flush=True)
            return 0
        with _LOCK:
            _FLUSHED[0] += len(batch)
        return len(batch)


def to_json_lines() -> str:
    with _LOCK:
        return "\n".join(json.dumps(ev, ensure_ascii=False) for ev in _EVENTS)
