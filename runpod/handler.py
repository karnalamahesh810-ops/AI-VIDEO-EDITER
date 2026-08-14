"""
ThumbGenius video worker — RunPod serverless entrypoint.

No intermediate API server. The Lovable app calls a Supabase edge function,
which submits a job here; this worker then writes its own progress, scenes and
final video URL straight back into public.video_projects with the service-role
key. The app simply watches the row.

Actions
-------
plan    : audio -> aligned segments -> sourced media -> timeline document.
          Returns the editable timeline WITHOUT rendering.
render  : take a timeline document (possibly edited by the user) -> MP4 ->
          Supabase Storage -> public URL.
build   : plan + render in one call. This is the normal path.
health  : cheap readiness probe.

Every action returns {"ok": bool, ...}; errors never raise out of the handler so
the caller always gets a structured result instead of a RunPod stack trace.
"""
import os
import shutil
import time
import traceback
import uuid

import runpod

from src import config, media, render as renderer, storage, timeline, transcribe


def _work_dir(job_id: str) -> str:
    d = os.path.join(config.WORK_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


class Reporter:
    """Mirrors progress to RunPod's job status AND to the video_projects row."""

    def __init__(self, project_id: str = ""):
        self.project_id = project_id or ""

    def __call__(self, step: str, progress: int = None, **fields):
        try:
            runpod.serverless.progress_update({"status": step, "progress": progress})
        except Exception:
            pass
        print(f"[worker] {step}" + (f" ({progress}%)" if progress is not None else ""), flush=True)
        if self.project_id:
            payload = {"current_step": step, **fields}
            if progress is not None:
                payload["progress"] = progress
            storage.patch_project(self.project_id, payload)


def do_plan(inp: dict, work: str, report: Reporter) -> dict:
    raw_audio = inp.get("audio_url") or inp.get("audio_path")
    if not raw_audio:
        raise ValueError("audio_url is required (upload a voiceover or generate TTS first)")

    report("Downloading narration", 5)
    # Handles both public URLs and private-bucket object paths.
    audio_src = storage.resolve_audio(raw_audio, bucket=inp.get("audio_bucket", "video-audio"))
    audio_path = storage.download(audio_src, os.path.join(work, "narration.mp3"))
    audio_duration = renderer.probe_duration(audio_path)

    report("Aligning narration", 12)
    words = transcribe.transcribe_words(audio_path, language=inp.get("language"))
    if not words:
        raise ValueError("no speech detected in the narration audio")
    segments = transcribe.segment_words(words)
    if inp.get("script"):
        segments = transcribe.align_to_script(segments, inp["script"])
    if not audio_duration:
        audio_duration = segments[-1].end

    total = len(segments)
    report(f"Sourcing media for {total} scenes", 20)
    prefer = inp.get("prefer", "stock")
    allow_youtube = bool(inp.get("allow_youtube", True))
    overrides = inp.get("scene_queries") or {}

    media.reset_cache()
    jobs = [
        {
            "index": i,
            "query": overrides.get(str(i)) or transcribe.keywords_for(seg),
            "seconds": seg.duration,
        }
        for i, seg in enumerate(segments)
    ]

    last_pct = [20]

    def on_done(done, n):
        # 20% -> 65% across sourcing, the longest phase. Only report on change
        # so a 300-scene job doesn't spam 300 database writes.
        pct = 20 + int(45 * done / max(n, 1))
        if pct != last_pct[0]:
            last_pct[0] = pct
            report(f"Sourced {done}/{n} scenes", pct)

    assets = media.source_many(
        jobs, work,
        prefer=prefer, allow_youtube=allow_youtube,
        workers=int(inp.get("source_workers", 6)),
        on_done=on_done,
    )

    doc = timeline.build(
        segments, assets,
        audio_url=audio_path,
        audio_duration=audio_duration,
        fps=inp.get("fps"), width=inp.get("width"), height=inp.get("height"),
        bgm_url=inp.get("bgm_url", ""),
        bgm_volume=float(inp.get("bgm_volume", 0.12)),
        captions=bool(inp.get("captions", True)),
        brand=inp.get("brand") or {},
        title_overlay=inp.get("title_overlay", ""),
    )
    doc["meta"]["scenesWithoutMedia"] = sum(
        1 for s in doc["scenes"] if s["media"]["type"] == "color"
    )
    return doc


def _sign_supabase_media(doc: dict):
    """
    Re-sign any Supabase storage URLs inside the timeline.

    Media the user swapped in from the editor is stored in a private bucket, and
    Remotion fetches those URLs from inside headless Chrome where the public
    form returns 400. Signing them here keeps private buckets working without
    exposing anything publicly. Mutates the document in place.
    """
    base = (config.SUPABASE_URL or "").rstrip("/")
    if not base:
        return
    marker = "/storage/v1/object/public/"
    for scene in doc.get("scenes", []):
        m = scene.get("media") or {}
        url = m.get("url") or ""
        if not url.startswith(base) or marker not in url:
            continue
        tail = url.split(marker, 1)[1]
        bucket, _, obj = tail.partition("/")
        try:
            m["url"] = storage.signed_url(obj, bucket=bucket)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not sign scene media {obj}: {e}", flush=True)


def do_render(doc: dict, inp: dict, work: str, report: Reporter) -> dict:
    _sign_supabase_media(doc)
    report(f"Rendering {doc['meta'].get('sceneCount', '?')} scenes", 70)
    out_path = os.path.join(work, "final.mp4")
    renderer.render(
        doc, out_path,
        composition=inp.get("composition", "Main"),
        concurrency=inp.get("concurrency"),
    )

    project_id = inp.get("project_id") or uuid.uuid4().hex
    object_path = inp.get("object_path") or f"projects/{project_id}/final.mp4"
    bucket = inp.get("bucket") or config.SUPABASE_BUCKET
    report("Uploading video", 92)
    public_url = storage.upload_to_supabase(out_path, object_path, bucket=bucket)

    # The renders bucket may be private. A public-form URL 400s there, so sign
    # the object as well — signing works against public buckets too, making this
    # correct either way. Both are returned so the app can re-sign from the path
    # when a long-lived link expires.
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
        "size_bytes": os.path.getsize(out_path),
        "duration": doc["durationInFrames"] / doc["fps"],
    }


def handler(job):
    started = time.time()
    job_id = job.get("id") or uuid.uuid4().hex
    inp = job.get("input") or {}
    action = (inp.get("action") or "build").lower()
    project_id = inp.get("project_id") or ""
    report = Reporter(project_id)
    work = _work_dir(job_id)

    try:
        if action == "health":
            return {"ok": True, "status": "ready"}

        if project_id:
            storage.patch_project(project_id, {
                "status": "rendering", "job_id": job_id,
                "progress": 0, "error_message": None,
            })

        if action == "plan":
            doc = do_plan(inp, work, report)
            if project_id:
                storage.patch_project(project_id, {
                    "scene_data": doc, "status": "editing",
                    "current_step": "Timeline ready", "progress": 65,
                })
            return {"ok": True, "action": "plan", "timeline": doc,
                    "elapsed": round(time.time() - started, 1)}

        if action == "render":
            doc = inp.get("timeline")
            if not doc:
                raise ValueError("render requires a `timeline` document")
            out = do_render(doc, inp, work, report)
            if project_id:
                storage.patch_project(project_id, {
                    "status": "done", "progress": 100, "current_step": "Done",
                    "video_url": out["video_url"],
                    "duration_seconds": out["duration"],
                    "completed_at": "now()",
                })
            return {"ok": True, "action": "render", **out,
                    "elapsed": round(time.time() - started, 1)}

        if action == "build":
            doc = do_plan(inp, work, report)
            if project_id:
                storage.patch_project(project_id, {"scene_data": doc})
            out = do_render(doc, inp, work, report)
            if project_id:
                storage.patch_project(project_id, {
                    "status": "done", "progress": 100, "current_step": "Done",
                    "video_url": out["video_url"],
                    "duration_seconds": out["duration"],
                    "completed_at": "now()",
                })
            return {"ok": True, "action": "build", "timeline": doc, **out,
                    "elapsed": round(time.time() - started, 1)}

        return {"ok": False, "error": f"unknown action '{action}'"}

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg = str(e)[:800]
        if project_id:
            storage.patch_project(project_id, {
                "status": "failed", "error_message": msg, "current_step": "Failed",
            })
        return {"ok": False, "error": msg, "elapsed": round(time.time() - started, 1)}
    finally:
        # Serverless workers are reused; a 17-minute render leaves GBs behind.
        if not inp.get("keep_workdir"):
            shutil.rmtree(work, ignore_errors=True)


runpod.serverless.start({"handler": handler})
