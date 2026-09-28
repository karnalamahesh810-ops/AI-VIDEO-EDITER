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


def main() -> None:
    job = json.loads(base64.b64decode(os.environ["JOB_B64"]))
    inp = job.get("input") or {}
    pid = inp.get("project_id") or ""
    started = time.time()
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
    ok = storage.patch_project(pid, fields, wait=True)
    print(f"[pod] job finished in {int(time.time() - started)}s: {fields.get('status')} "
          f"(project updated: {ok}) {str(out.get('video_url') or out.get('error') or '')[:160]}", flush=True)
    stop_this_pod()


if __name__ == "__main__":
    main()
