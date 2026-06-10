"""RunPod Serverless handler — one worker = one video job. Scale = max workers (10+).
Input  (from /run):  {"audio_url": "...", "title": "...", "channels": "a,b" (optional),
                      "source": "auto"|"channels" (optional)}
Output: {"video_url": "...", "duration_min": float, "size_mb": int}
Progress: mirrors the pipeline's status JSON into runpod progress (site polls /status/{id}).

Endpoint env vars (set in RunPod console):
  GEMINI_KEY            kie.ai or Google key (clip tagging + overlays + auto-discovery)
  SUPABASE_URL          https://<project>.supabase.co
  SUPABASE_SERVICE_KEY  service-role key (uploads the finished mp4 to Storage)
  SUPABASE_BUCKET       e.g. "videos" (public bucket)
"""
import json, os, shutil, subprocess, time
import requests
import runpod

APP = "/app"
STATUS = f"{APP}/out/pipeline_status.json"


def _prepare_workspace():
    # fresh per-job state; keep the baked remotion + runtime_assets
    for d in ("in", "out", "runtime", "channel_src"):
        shutil.rmtree(f"{APP}/{d}", ignore_errors=True)
        os.makedirs(f"{APP}/{d}", exist_ok=True)
    shutil.copytree(f"{APP}/runtime_assets/fx", f"{APP}/runtime/fx", dirs_exist_ok=True)
    key = os.environ.get("GEMINI_KEY", "")
    if key:
        open(f"{APP}/gemini_key.txt", "w").write(key)


def _upload_supabase(path, dest_name):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    bucket = os.environ.get("SUPABASE_BUCKET", "videos")
    with open(path, "rb") as f:
        r = requests.post(
            f"{url}/storage/v1/object/{bucket}/{dest_name}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "video/mp4",
                     "x-upsert": "true"},
            data=f, timeout=900)
    r.raise_for_status()
    return f"{url}/storage/v1/object/public/{bucket}/{dest_name}"


def handler(job):
    inp = job.get("input", {}) or {}
    audio_url = inp.get("audio_url")
    if not audio_url:
        return {"error": "audio_url is required"}
    title = inp.get("title", "")
    channels = inp.get("channels", "")

    _prepare_workspace()

    cmd = ["python3", f"{APP}/pipeline_sl.py", "--audio", audio_url, "--title", title]
    if channels:
        cmd += ["--channels", channels, "--source", "channels"]
    else:
        cmd += ["--source", inp.get("source", "auto")]

    log_path = f"{APP}/out/job.log"
    proc = subprocess.Popen(cmd, stdout=open(log_path, "w"), stderr=subprocess.STDOUT)

    last = ""
    while proc.poll() is None:
        time.sleep(4)
        try:
            st = json.load(open(STATUS))
            cur = f"{st.get('stage')}|{st.get('pct')}"
            if cur != last:
                runpod.serverless.progress_update(job, st)
                last = cur
        except Exception:
            pass

    final = f"{APP}/out/final.mp4"
    if proc.returncode != 0 or not os.path.exists(final):
        tail = ""
        try:
            tail = open(log_path).read()[-1500:]
        except Exception:
            pass
        return {"error": f"pipeline exited {proc.returncode}", "log_tail": tail}

    size_mb = round(os.path.getsize(final) / 1e6)
    dur = ""
    try:
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", final], capture_output=True, text=True).stdout.strip()
    except Exception:
        pass
    dest = f"{job['id']}.mp4"
    try:
        video_url = _upload_supabase(final, dest)
    except Exception as e:
        return {"error": f"render OK but upload failed: {e}", "size_mb": size_mb}
    return {"video_url": video_url, "size_mb": size_mb,
            "duration_min": round(float(dur or 0) / 60, 1), "title": title}


runpod.serverless.start({"handler": handler})
