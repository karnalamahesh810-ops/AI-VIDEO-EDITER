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

Every action returns {"ok": bool, ...}; errors never raise out of the handler
so the caller always gets a structured result instead of a RunPod stack trace.
"""
import os
import shutil
import time
import traceback
import uuid
from typing import Dict

import runpod

from src import (config, director, geocode, media, render as renderer,
                 selftest, storage, timeline, transcribe)


def _work_dir(job_id: str) -> str:
    d = os.path.join(config.WORK_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


class Reporter:
    """Mirrors progress to RunPod's job status AND to the video_projects row."""

    def __init__(self, project_id: str = ""):
        self.project_id = project_id or ""
        self._last = None

    def __call__(self, step: str, progress: int = None, **fields):
        try:
            runpod.serverless.progress_update({"status": step, "progress": progress})
        except Exception:
            pass
        print(f"[worker] {step}" + (f" ({progress}%)" if progress is not None else ""),
              flush=True)
        if not self.project_id:
            return
        # A 600-scene job would otherwise write the same row hundreds of times.
        if (step, progress) == self._last:
            return
        self._last = (step, progress)
        payload = {"current_step": step, **fields}
        if progress is not None:
            payload["progress"] = progress
        storage.patch_project(self.project_id, payload)


def publish_media(doc: dict, project_id: str, bucket: str, report: Reporter) -> int:
    """
    Upload sourced media to Supabase and point the timeline at it.

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
    published: Dict[str, str] = {}
    failures = 0
    scenes = doc.get("scenes", [])
    for i, scene in enumerate(scenes):
        media = scene.get("media") or {}
        path = media.get("url") or ""
        if not path or not os.path.isfile(path):
            continue
        if path in published:
            media["url"] = published[path]
            continue
        ext = os.path.splitext(path)[1] or ".bin"
        obj = f"projects/{project_id}/media/{scene['id']}{ext}"
        try:
            storage.upload_to_supabase(path, obj, bucket=bucket)
            url = storage.signed_url(obj, bucket=bucket, expires_in=60 * 60 * 24 * 7)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not publish {obj}: {e}", flush=True)
            scene["reviewRequired"] = True
            scene["reviewReason"] = "Media could not be saved; re-source before rendering"
            failures += 1
            continue
        published[path] = url
        media["url"] = url
        if i % 20 == 0:
            report(f"Saving media {i + 1}/{len(scenes)}", 66)
    doc["meta"]["publishedMedia"] = len(published)
    if failures:
        doc["meta"]["warnings"].append(
            f"{failures} scene(s) could not be saved to storage.")
    return len(published)


def do_plan(inp: dict, work: str, report: Reporter) -> dict:
    raw_audio = inp.get("audio_url") or inp.get("audio_path")
    if not raw_audio:
        raise ValueError("audio_url is required (upload a voiceover or generate TTS first)")

    report("Downloading narration", 4)
    # Handles both public URLs and private-bucket object paths.
    audio_src = storage.resolve_audio(raw_audio, bucket=inp.get("audio_bucket", "video-audio"))
    audio_path = storage.download(audio_src, os.path.join(work, "narration.mp3"))
    audio_duration = renderer.probe_duration(audio_path)

    report("Aligning narration", 8)
    words = transcribe.transcribe_words(audio_path, language=inp.get("language"))
    if not words:
        raise ValueError("no speech detected in the narration audio")
    segments = transcribe.segment_words(words)
    if inp.get("script"):
        segments = transcribe.align_to_script(segments, inp["script"])
    if not audio_duration:
        audio_duration = segments[-1].end

    # Shot plan: what is on screen while each beat is spoken.
    geocode.reset_cache()
    shots, planner, warnings = director.plan(
        segments,
        title=inp.get("title") or inp.get("title_overlay") or "",
        report=report,
        allow_maps=bool(inp.get("maps", True)),
    )

    # Per-scene overrides from the editor win over the director's choice.
    for key, query in (inp.get("scene_queries") or {}).items():
        try:
            idx = int(key)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(shots) and str(query).strip():
            shots[idx]["query"] = str(query).strip()[:240]

    total = len(segments)
    report(f"Sourcing media for {total} scenes", 22)
    media.reset_cache()
    jobs = [{"index": i, "query": shot["query"], "seconds": seg.duration,
             "visual_type": shot.get("visualType", "footage"),
             "fallbacks": shot.get("fallbacks") or []}
            for i, (seg, shot) in enumerate(zip(segments, shots))]

    last_pct = [22]

    def on_done(done, n):
        # 22% -> 65% across sourcing, the longest phase.
        pct = 22 + int(43 * done / max(n, 1))
        if pct != last_pct[0]:
            last_pct[0] = pct
            report(f"Sourced {done}/{n} scenes", pct)

    assets = media.source_many(
        jobs, work,
        workers=int(inp.get("source_workers", 6)),
        allow_youtube=inp.get("allow_youtube"),
        allow_stock=inp.get("allow_stock"),
        require_cc=inp.get("require_cc"),
        on_done=on_done,
    )

    doc = timeline.build(
        segments, shots, assets,
        # The resolved URL, not the temp path: the document has to stay
        # meaningful after this job's work directory is gone.
        audio_url=audio_src or audio_path,
        audio_duration=audio_duration,
        inp=inp,
        planner=planner,
        warnings=warnings,
    )
    # A signed URL expires; keep the original reference so render can re-sign.
    unsupported = [k for k in ("own_clips", "channels")
                   if inp.get(k) and inp.get("source") in ("clips", "channels")]
    if unsupported:
        doc["meta"]["warnings"].append(
            f"Requested source mode '{inp.get('source')}' is not implemented yet; "
            f"sourced from Creative Commons YouTube and Commons instead.")
    doc["meta"]["audioSource"] = raw_audio
    doc["meta"]["audioBucket"] = inp.get("audio_bucket", "video-audio")
    # Catch a malformed plan here rather than inside headless Chrome. Media may
    # still be missing at plan time — that is what the editor is for.
    timeline.validate(doc, require_media=False)
    return doc


def do_resource(inp: dict, work: str, report: Reporter) -> dict:
    """
    Re-source the media for ONE scene and return the whole timeline back.

    This is what makes the editor usable: the user rejects a single shot and
    gets a replacement in seconds, instead of re-running a twenty-minute plan
    to change one clip. Timing is deliberately untouched — only `media` and
    its review flags change, so the visual track still tiles the narration
    exactly and the voiceover cannot drift.
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
    query = str(inp.get("query") or scene.get("query")
                or scene.get("text") or "").strip()[:240]
    if not query:
        raise ValueError("this scene has nothing to search for — set a query first")

    report(f"Re-sourcing scene {idx + 1}", 20)
    media.reset_cache()
    asset = media.source_for_segment(
        query, seconds, work,
        visual_type=scene.get("visualType", "footage"),
        allow_youtube=inp.get("allow_youtube"),
        allow_stock=inp.get("allow_stock"),
        require_cc=inp.get("require_cc"),
    )
    if not asset:
        raise ValueError(f"no usable media found for '{query}' — try different wording")

    scene["media"] = asset.to_scene_media()
    scene["query"] = query
    scene["motion"] = (timeline._IMAGE_MOTIONS[idx % len(timeline._IMAGE_MOTIONS)]
                       if asset.kind == "image" else "none")
    scene["reviewRequired"] = bool(asset.review_required)
    scene["reviewReason"] = asset.review_reason or ""

    project_id = inp.get("project_id") or ""
    if project_id and inp.get("publish_media", True):
        report("Saving replacement media", 70)
        publish_media(doc, project_id,
                      inp.get("media_bucket") or config.SUPABASE_BUCKET, report)

    meta = doc.setdefault("meta", {})
    meta["scenesWithoutMedia"] = sum(
        1 for s in scenes if (s.get("media") or {}).get("type") == "color")
    meta["scenesNeedingReview"] = sum(1 for s in scenes if s.get("reviewRequired"))
    # Only this scene changed, so validate without demanding the rest be filled.
    timeline.validate(doc, require_media=False)
    return doc


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
        bgm["url"] = resign(bgm["url"])
    for scene in doc.get("scenes", []):
        m = scene.get("media") or {}
        if m.get("url"):
            m["url"] = resign(m["url"])
    for ov in doc.get("overlays", []):
        for m in (ov.get("media") or []):
            if isinstance(m, dict) and m.get("url"):
                m["url"] = resign(m["url"])


def do_render(doc: dict, inp: dict, work: str, report: Reporter) -> dict:
    # The document may have come back from a browser, so validate before
    # spending GPU minutes on it.
    timeline.validate(doc, require_media=True)

    # A plan can sit in the editor for days; any signed URL in it has long
    # since expired. Re-resolve the narration from the reference the plan
    # recorded, then re-sign whatever else points at Supabase.
    source = (doc.get("meta") or {}).get("audioSource")
    if source:
        try:
            doc["audio"]["url"] = storage.resolve_audio(
                source, bucket=(doc["meta"].get("audioBucket") or "video-audio"))
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not refresh narration url: {e}", flush=True)
    _sign_supabase_urls(doc)

    report(f"Rendering {doc['meta'].get('sceneCount', len(doc['scenes']))} scenes", 70)
    out_path = os.path.join(work, "final.mp4")
    renderer.render(
        doc, out_path,
        composition=inp.get("composition", "Main"),
        concurrency=inp.get("concurrency"),
        # Everything sourced for this job lives here; the renderer serves it
        # over loopback so headless Chrome can actually fetch it.
        serve_dir=work,
    )

    report("Uploading video", 92)
    duration = doc["durationInFrames"] / doc["fps"]

    # Preferred: the caller pre-signed a destination for us, so this worker
    # needs no Supabase credentials at all. The app's video-render edge
    # function already does this — it holds the service key, we do not.
    upload_url = inp.get("upload_url")
    if upload_url:
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
    }


def _done_fields(out: dict) -> dict:
    return {
        "status": "done", "progress": 100, "current_step": "Done",
        "video_url": out["video_url"],
        "duration_seconds": out["duration"],
        "completed_at": "now()",
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
        if action == "selftest":
            out = selftest.run(work, width=int(inp.get("width", 854)), report=report)
            return {"ok": out.get("ok", False), "action": "selftest", **out,
                    "elapsed": round(time.time() - started, 1)}

        if action == "health":
            # Include the storage preflight: a missing bucket or bad key is
            # otherwise only discovered at the upload step, after the render.
            store = storage.check(inp.get("bucket"))
            return {"ok": True, "status": "ready",
                    "sourcePolicy": "stock_allowed" if config.ALLOW_STOCK else "no_stock",
                    "director": bool(config.DIRECTOR_API_KEY),
                    "imageModel": bool(config.IMAGE_API_KEY),
                    "storage": store,
                    "readyToRender": store.get("ok", False)}

        if project_id:
            storage.patch_project(project_id, {
                "status": "rendering", "job_id": job_id,
                "progress": 0, "error_message": None,
            })

        if action == "plan":
            doc = do_plan(inp, work, report)
            # Without this the timeline points at files this job is about to
            # delete. See publish_media().
            if project_id and inp.get("publish_media", True):
                report("Saving sourced media", 66)
                publish_media(doc, project_id,
                              inp.get("media_bucket") or config.SUPABASE_BUCKET, report)
            if project_id:
                storage.patch_project(project_id, {
                    "scene_data": doc, "status": "editing",
                    "current_step": "Timeline ready", "progress": 68,
                })
            return {"ok": True, "action": "plan", "timeline": doc,
                    "elapsed": round(time.time() - started, 1)}

        if action == "resource":
            doc = do_resource(inp, work, report)
            if project_id:
                storage.patch_project(project_id, {
                    "scene_data": doc, "status": "editing",
                    "current_step": "Scene re-sourced", "progress": 100,
                })
            return {"ok": True, "action": "resource", "timeline": doc,
                    "scene_index": inp.get("scene_index"),
                    "elapsed": round(time.time() - started, 1)}

        if action == "render":
            doc = inp.get("timeline")
            if not doc:
                raise ValueError("render requires a `timeline` document")
            out = do_render(doc, inp, work, report)
            if project_id:
                storage.patch_project(project_id, _done_fields(out))
            return {"ok": True, "action": "render", **out,
                    "elapsed": round(time.time() - started, 1)}

        if action == "build":
            doc = do_plan(inp, work, report)
            if project_id:
                storage.patch_project(project_id, {"scene_data": doc})
            out = do_render(doc, inp, work, report)
            if project_id:
                storage.patch_project(project_id, _done_fields(out))
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


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
