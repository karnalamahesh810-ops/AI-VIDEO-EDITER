"""
One video on a RunPod CPU pod (no serverless).

JOB_B64 = base64 of {"id": "pod-...", "input": {...}} - the same input the app's
video-v2 function sends. The handler runs once; the result is written into the
project through the app's broker (status, video, timeline), then this pod stops
itself so nothing is billed after the video is done (the pod volume is kept).
"""
import base64
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import handler  # noqa: E402
from src import config, storage  # noqa: E402


def stop_this_pod() -> None:
    pod = os.environ.get("RUNPOD_POD_ID", "")
    key = os.environ.get("POD_STOP_KEY") or config.FANOUT_API_KEY or os.environ.get("RUNPOD_API_KEY", "")
    if not (pod and key):
        print("[pod] no pod id or key; not stopping", flush=True)
        return
    for attempt in range(3):
        try:
            r = requests.post(f"https://rest.runpod.io/v1/pods/{pod}/stop",
                              headers={"Authorization": f"Bearer {key}"}, timeout=30)
            print(f"[pod] stop requested: HTTP {r.status_code}", flush=True)
            if r.status_code < 400:
                return
        except requests.RequestException as e:
            print(f"[pod] stop failed: {type(e).__name__}", flush=True)
        time.sleep(5)


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
    job = json.loads(base64.b64decode(os.environ["JOB_B64"]))
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
    if not isinstance(out, dict):
        out = {"ok": False, "error": "the job returned no result"}
    # handler() cleared nothing about the job id; the final write is still this job's.
    storage.CURRENT_JOB[0] = job.get("id") or ""
    if out.get("ok") is False or out.get("error"):
        fields = {"status": "failed", "current_step": "Failed",
                  "error_message": str(out.get("error") or "failed")[:800]}
    else:
        fields = {"status": "done", "progress": 100, "current_step": "Completed",
                  "video_url": out.get("video_url") or "", "render_path": out.get("object_path") or "",
                  "duration_seconds": out.get("duration"),
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

    if big:
        # While the row is still "rendering": the broker refuses writes once it is done.
        if not write(big, 300):
            print("[pod] could not save the finished timeline to the app (the video itself is next)", flush=True)
    ok = write(fields, 600)
    succeeded = fields["status"] == "done"
    print(f"[pod] job finished in {int(time.time() - started)}s: {fields.get('status')} "
          f"(project updated: {ok}) {str(out.get('video_url') or out.get('error') or '')[:160]}", flush=True)
    if fetch:
        fetch.set_job("done" if succeeded and ok else "failed", "" if succeeded else fields.get("error_message", ""))
    decision = after_job(succeeded and ok, kept, fetch.laptop_has_it if fetch else None,
                         float(os.environ.get("POD_FETCH_WAIT_SECONDS", "1800")))
    if decision == "stay":
        print("[pod] the video is not safe in the app yet: staying up and serving it "
              "(stop this pod by hand once the video is saved)", flush=True)
        while True:
            time.sleep(3600)
    stop_this_pod()


if __name__ == "__main__":
    main()
