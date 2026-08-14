"""
ThumbGenius video worker — RunPod serverless entrypoint.

Actions
-------
plan    : audio -> aligned segments -> sourced media -> timeline document.
          Returns the editable timeline WITHOUT rendering, which is what the
          UI shows in the editor (same as hitting generate in VidRush).
render  : take a timeline document (possibly edited by the user) -> MP4 ->
          Supabase Storage -> public URL.
build   : plan + render in one call, for fully automatic runs.
health  : cheap readiness probe.

Every action returns {"ok": bool, ...}; errors never raise out of the handler so
the frontend always gets a structured result instead of a RunPod stack trace.
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


def _progress(msg: str):
    try:
        runpod.serverless.progress_update({"status": msg})
    except Exception:
        pass
    print(f"[worker] {msg}", flush=True)


def do_plan(inp: dict, work: str) -> dict:
    audio_url = inp.get("audio_url")
    if not audio_url:
        raise ValueError("audio_url is required (upload the VO or generate TTS first)")

    _progress("downloading narration")
    audio_path = storage.download(audio_url, os.path.join(work, "narration.mp3"))
    audio_duration = renderer.probe_duration(audio_path)

    _progress("aligning narration")
    words = transcribe.transcribe_words(audio_path, language=inp.get("language"))
    if not words:
        raise ValueError("no speech detected in the narration audio")
    segments = transcribe.segment_words(words)
    if inp.get("script"):
        segments = transcribe.align_to_script(segments, inp["script"])
    if not audio_duration:
        audio_duration = segments[-1].end

    _progress(f"sourcing media for {len(segments)} scenes")
    prefer = inp.get("prefer", "stock")
    allow_youtube = bool(inp.get("allow_youtube", True))
    overrides = inp.get("scene_queries") or {}

    assets = []
    for i, seg in enumerate(segments):
        query = overrides.get(str(i)) or transcribe.keywords_for(seg)
        try:
            asset = media.source_for_segment(
                query, seg.duration, work,
                prefer=prefer, allow_youtube=allow_youtube,
            )
        except Exception as e:
            print(f"[worker] scene {i} sourcing failed: {e}", flush=True)
            asset = None
        assets.append(asset)
        if i % 10 == 0:
            _progress(f"sourced {i + 1}/{len(segments)} scenes")

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
    missing = sum(1 for s in doc["scenes"] if s["media"]["type"] == "color")
    doc["meta"]["scenesWithoutMedia"] = missing
    return doc


def do_render(doc: dict, inp: dict, work: str) -> dict:
    _progress(f"rendering {doc['meta'].get('sceneCount', '?')} scenes")
    out_path = os.path.join(work, "final.mp4")
    renderer.render(
        doc, out_path,
        composition=inp.get("composition", "Main"),
        concurrency=inp.get("concurrency"),
    )

    project_id = inp.get("project_id") or uuid.uuid4().hex
    object_path = inp.get("object_path") or f"projects/{project_id}/final.mp4"
    _progress("uploading to supabase storage")
    url = storage.upload_to_supabase(
        out_path, object_path, bucket=inp.get("bucket"),
    )
    return {
        "video_url": url,
        "object_path": object_path,
        "size_bytes": os.path.getsize(out_path),
        "duration": doc["durationInFrames"] / doc["fps"],
    }


def handler(job):
    started = time.time()
    job_id = job.get("id") or uuid.uuid4().hex
    inp = job.get("input") or {}
    action = (inp.get("action") or "build").lower()
    work = _work_dir(job_id)

    try:
        if action == "health":
            return {"ok": True, "status": "ready"}

        if action == "plan":
            doc = do_plan(inp, work)
            return {"ok": True, "action": "plan", "timeline": doc,
                    "elapsed": round(time.time() - started, 1)}

        if action == "render":
            doc = inp.get("timeline")
            if not doc:
                raise ValueError("render requires a `timeline` document")
            out = do_render(doc, inp, work)
            return {"ok": True, "action": "render", **out,
                    "elapsed": round(time.time() - started, 1)}

        if action == "build":
            doc = do_plan(inp, work)
            out = do_render(doc, inp, work)
            return {"ok": True, "action": "build", "timeline": doc, **out,
                    "elapsed": round(time.time() - started, 1)}

        return {"ok": False, "error": f"unknown action '{action}'"}

    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)[:800],
                "elapsed": round(time.time() - started, 1)}
    finally:
        # Serverless workers are reused; a 17-minute render leaves GBs behind.
        if not inp.get("keep_workdir"):
            shutil.rmtree(work, ignore_errors=True)


runpod.serverless.start({"handler": handler})
