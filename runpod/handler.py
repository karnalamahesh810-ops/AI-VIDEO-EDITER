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
import copy
import os
import shutil
import subprocess
import time
import traceback
import uuid
from typing import Dict

import runpod

from src import (config, director, geocode, media, render as renderer,
                 selftest, storage, timeline, transcribe, vision)


def _work_dir(job_id: str) -> str:
    d = os.path.join(config.WORK_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


# Pipeline phases, in order, for the app's progress screen. The key is sent as
# `phase` (not `stage`: the app already reads `stage` as the display text).
PHASES = ("narration", "transcribe", "plan", "source", "render", "upload", "save")
_PHASE_BY_PREFIX = (
    ("Downloading narration", "narration"),
    ("Aligning narration", "transcribe"),
    ("Reading the whole story", "plan"), ("Planning", "plan"),
    ("Sourcing", "source"), ("Sourced", "source"), ("Re-sourcing", "source"),
    ("Replacing", "source"), ("Rechecking", "source"),
    ("Building shot pools", "source"),
    ("Rendering", "render"),
    ("Uploading", "upload"),
    ("Saving", "save"),
)


class Reporter:
    """Mirrors progress to RunPod's job status AND to the video_projects row."""

    def __init__(self, project_id: str = "", job: dict = None):
        self.project_id = project_id or ""
        # runpod's progress_update(job, progress) needs the job itself. It
        # used to be called with the progress alone; the TypeError was
        # swallowed below, so no progress ever reached RunPod or the app.
        self.job = job
        self._last = None
        self._started = time.time()
        # Seconds spent per stage, so a slow job says where its time went.
        self._stage = ("", self._started)
        self._timings: dict = {}

    def _clock(self, stage: str) -> None:
        name, since = self._stage
        if stage == name:
            return
        now = time.time()
        if name:
            self._timings[name] = round(self._timings.get(name, 0.0) + now - since, 1)
        self._stage = (stage, now)

    def timings(self) -> dict:
        """{stage: seconds} so far, the current stage included, plus the total."""
        name, since = self._stage
        out = dict(self._timings)
        if name:
            out[name] = round(out.get(name, 0.0) + time.time() - since, 1)
        out["total"] = round(time.time() - self._started, 1)
        return out

    def __call__(self, step: str, progress: int = None, *, done: int = None,
                 total: int = None, **fields):
        prefix = next((p for p, _ in _PHASE_BY_PREFIX if step.startswith(p)), step[:40])
        self._clock("Sourcing" if prefix == "Sourced" else prefix)
        phase = next((p for prefix, p in _PHASE_BY_PREFIX if step.startswith(prefix)), "")
        update = {"status": step, "progress": progress, "phase": phase,
                  "phases": list(PHASES),
                  "elapsed": round(time.time() - self._started)}
        if done is not None and total is not None:
            update.update(done=done, total=total)
        if self.job and self.job.get("id"):
            try:
                runpod.serverless.progress_update(self.job, update)
            except Exception as e:  # noqa: BLE001 — progress must never kill a job
                print(f"[worker] progress update failed: {e}", flush=True)
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


def _machine() -> dict:
    """
    What this worker can actually use, as the container sees it.

    os.cpu_count() reports the HOST; the cgroup files say what this container
    is allowed. Render concurrency and the thread-spawn crash both depend on
    the real limits, not the host's.
    """
    def read(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            return ""
    info = {"hostCpus": os.cpu_count()}
    try:
        info["usableCpus"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    quota = read("/sys/fs/cgroup/cpu.max").split()
    if len(quota) == 2 and quota[0] != "max":
        info["cgroupCpus"] = round(int(quota[0]) / int(quota[1]), 2)
    mem = read("/sys/fs/cgroup/memory.max")
    if mem.isdigit():
        info["memoryGb"] = round(int(mem) / 2 ** 30, 1)
    for line in read("/proc/meminfo").splitlines()[:1]:
        info["hostMemoryGb"] = round(int(line.split()[1]) / 2 ** 20, 1)
    info["pidsMax"] = read("/sys/fs/cgroup/pids.max") or None
    info["gpu"] = bool(os.path.exists("/dev/nvidia0"))
    return info


def _thumbnail(path: str, work: str, scene_id: str) -> str:
    """A 320px JPEG of the scene for the editor's filmstrip, or "" on failure."""
    out = os.path.join(work, f"thumb_{scene_id}.jpg")
    seek = []
    if os.path.splitext(path)[1].lower() in (".mp4", ".webm", ".mov", ".m4v", ".mkv"):
        dur = renderer.probe_duration(path) or 0
        seek = ["-ss", f"{dur / 2:.2f}"]
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *seek, "-i", path, "-frames:v", "1",
                        "-vf", "scale=320:-2", "-q:v", "5", out],
                       capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out if os.path.isfile(out) else ""


_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".mkv")


def _preview_proxy(path: str, work: str, scene_id: str) -> str:
    """
    A light copy of a video clip for the editor's live preview, or "".

    The editor's player streamed every scene's full source clip (up to 1080p,
    whatever bitrate the upload had) the moment the scene started, so each cut
    waited on a fresh multi-megabyte download and the preview buffered. This
    is 640px wide, silent (the narration is its own track), with the index at
    the front (+faststart) so it starts on the first bytes, and a keyframe
    every half second so scrubbing lands instantly. The render always uses the
    full clip.
    """
    if os.path.splitext(path)[1].lower() not in _VIDEO_EXTS:
        return ""
    out = os.path.join(work, f"preview_{scene_id}.mp4")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-an",
                        "-vf", "scale='min(640,iw)':-2", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "30", "-g", "15",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                       capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""


# Media links in a saved timeline. The editor can sit on a project for weeks;
# the render step re-signs from media.storage regardless.
_MEDIA_LINK_TTL = 60 * 60 * 24 * 30


def publish_media(doc: dict, project_id: str, bucket: str, report: Reporter,
                  job_id: str = "", band: tuple = (66, 68)) -> int:
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
    published: Dict[str, tuple] = {}
    failures = 0
    scenes = doc.get("scenes", [])
    lo, hi = band
    last_pct = [None]
    work = os.path.dirname(next((s["media"]["url"] for s in scenes
                                 if os.path.isfile((s.get("media") or {}).get("url") or "")),
                                "")) or config.WORK_DIR

    def put(local: str, obj: str) -> str:
        if storage.broker_enabled():
            return storage.broker_upload(local, bucket, obj, project_id, job_id,
                                         read_ttl=_MEDIA_LINK_TTL)
        storage.upload_to_supabase(local, obj, bucket=bucket)
        return storage.signed_url(obj, bucket=bucket, expires_in=_MEDIA_LINK_TTL)

    for i, scene in enumerate(scenes):
        pct = lo + int((hi - lo) * i / max(len(scenes), 1))
        if pct != last_pct[0]:
            last_pct[0] = pct
            report(f"Saving clips for editing {i}/{len(scenes)}", pct, done=i, total=len(scenes))
        media = scene.get("media") or {}
        path = media.get("url") or ""
        if not path or not os.path.isfile(path):
            continue
        if path in published:
            media.update(published[path][1])
            continue
        ext = os.path.splitext(path)[1] or ".bin"
        obj = f"projects/{project_id}/media/{scene['id']}{ext}"
        try:
            url = put(path, obj)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not publish {obj}: {e}", flush=True)
            scene["reviewRequired"] = True
            scene["reviewReason"] = "Media could not be saved; re-source before rendering"
            failures += 1
            continue
        fields = {"url": url,
                  # The signed URL expires; the app re-signs from this before a render.
                  "storage": {"bucket": bucket, "path": obj}}
        thumb = _thumbnail(path, work, scene["id"])
        if thumb:
            tobj = f"projects/{project_id}/thumbs/{scene['id']}.jpg"
            try:
                fields["thumbnail"] = put(thumb, tobj)
                fields["thumbStorage"] = {"bucket": bucket, "path": tobj}
            except Exception as e:  # noqa: BLE001 — a missing thumb is cosmetic
                print(f"[worker] could not save thumbnail {tobj}: {e}", flush=True)
        preview = _preview_proxy(path, work, scene["id"])
        if preview:
            pobj = f"projects/{project_id}/preview/{scene['id']}.mp4"
            try:
                fields["previewUrl"] = put(preview, pobj)
                fields["previewStorage"] = {"bucket": bucket, "path": pobj}
            except Exception as e:  # noqa: BLE001 — the editor falls back to the full clip
                print(f"[worker] could not save preview {pobj}: {e}", flush=True)
        media.update(fields)
        published[path] = (url, fields)
    doc["meta"]["publishedMedia"] = len(published)
    if failures:
        doc["meta"]["warnings"].append(
            f"{failures} scene(s) could not be saved to storage.")
    return len(published)


def _fill_missing_media(doc: dict) -> int:
    """
    Give every scene something to render, for the `build` path only.

    `build` sources and renders in one job with nothing shown to the user in
    between, so a single scene nothing could be found for used to fail
    `timeline.validate(require_media=True)` inside do_render and destroy the
    whole job: the exception unwinds past the point where the work directory
    is deleted, taking every other scene's already-downloaded clip with it.
    Twenty minutes of sourcing was lost over one hard beat.

    The scene_data already saved to the project (before this is ever called)
    keeps the honest "no media found" / reviewRequired record, so the editor
    and its readiness panel still show the real gap. This only patches the
    throwaway render copy: it borrows a scene that does have media and flags
    the borrow for review, the same "a repeat is better than black" rule
    already used for duplicates.

    Borrows prefer a scene about the SAME subject first (matching the story,
    not just filling the frame - a shot of the actual thing being narrated
    beats a shot of whatever else happened to be nearby), then spread across
    every available scene (least-borrowed first, nearest as the tiebreak)
    rather than always the closest one. Several empty scenes in a row are
    common — a hard subject is usually hard for several consecutive beats,
    not one — and always reaching for "nearest" means every one of them
    collapses onto the SAME single neighbour: a visible run of the identical
    clip repeated back to back, which reads far worse than the same clip
    appearing twice somewhere apart in the video.
    Returns how many scenes were patched.
    """
    scenes = doc.get("scenes", [])
    have = [i for i, s in enumerate(scenes)
           if (s.get("media") or {}).get("type") != "color"]
    if not have:
        # Nothing was sourced anywhere in the whole video - there is no clip
        # to borrow. Never leave this as a black hole: give each empty scene
        # a text card over its own narration line, the same fallback VidRush
        # itself reaches for on an unfindable beat. SceneClip already draws a
        # quiet gradient instead of flat black behind it.
        overlays = doc.setdefault("overlays", [])
        cards = 0
        for s in scenes:
            text = (s.get("text") or "").strip()
            if not text:
                continue
            overlays.append({
                "type": "highlight", "text": text[:180],
                "startFrame": s["startFrame"], "durationInFrames": s["durationInFrames"],
            })
            s["reviewRequired"] = True
            s["reviewReason"] = "No usable clip or image found — text card shown instead"
            cards += 1
        return cards
    def subject_of(idx: int) -> str:
        return ((scenes[idx].get("semanticMetadata") or {}).get("subject") or "").strip().lower()

    borrowed = {h: 0 for h in have}
    patched = 0
    for i, s in enumerate(scenes):
        if (s.get("media") or {}).get("type") == "color":
            want = subject_of(i)
            same_subject = [h for h in have if want and subject_of(h) == want]
            pool = same_subject or have
            pick = min(pool, key=lambda h: (borrowed[h], abs(h - i)))
            borrowed[pick] += 1
            s["media"] = dict(scenes[pick]["media"])
            s["motion"] = scenes[pick].get("motion", "none")
            s["reviewRequired"] = True
            reason = ("No usable clip found — reused a shot of the same subject; use Find footage to replace it"
                     if pool is same_subject else
                     "No usable clip found — reused another scene; use Find footage to replace it")
            s["reviewReason"] = reason
            patched += 1
    return patched


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
    words = transcribe.transcribe_words(
        audio_path, language=inp.get("language"),
        # 8 -> 13%: the band between download and the planner.
        on_progress=lambda f: report("Aligning narration", 8 + int(5 * f)))
    if not words:
        raise ValueError("no speech detected in the narration audio")
    segments = transcribe.segment_words(words)
    if inp.get("script"):
        segments = transcribe.align_to_script(segments, inp["script"])
    if not audio_duration:
        audio_duration = segments[-1].end

    # Read the whole story once: it steers every beat's plan, and after
    # sourcing it steers the recheck of scenes still missing a shot.
    title = director.clean_title(inp.get("title") or inp.get("title_overlay") or "")
    report("Reading the whole story", 13)
    brief = director.story_brief(segments, title, configured=director.is_configured())
    # Every vision judgement sees the whole story, not just its own line.
    vision.set_story(brief)
    # And YouTube searches the archive or news channels for this kind of story.
    media.set_story_kind(brief.get("kind", ""))

    # Shot plan: what is on screen while each beat is spoken.
    geocode.reset_cache()
    shots, planner, warnings = director.plan(
        segments,
        title=title,
        report=report,
        allow_maps=bool(inp.get("maps", True)),
        brief=brief,
    )
    # Out of AI credits already: stop before a single footage search is paid for.
    vision.require_credits()

    # Per-scene overrides from the editor win over the director's choice.
    for key, query in (inp.get("scene_queries") or {}).items():
        try:
            idx = int(key)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(shots) and str(query).strip():
            shots[idx]["query"] = str(query).strip()[:240]

    total = len(segments)
    report(f"Sourcing media for {total} scenes", 22, done=0, total=total)
    media.reset_cache()
    media.set_story_script(" ".join(seg.text for seg in segments))
    # A 1961 story ranks 1961 footage above 4K drone tours of today.
    if brief.get("kind") in ("history", "biography"):
        media.set_story_era(brief.get("year"))
    jobs = [{"index": i, "query": shot["query"], "seconds": seg.duration,
             "visual_type": shot.get("visualType", "footage"),
             "fallbacks": shot.get("fallbacks") or [],
             "prompt": shot.get("prompt") or "",
             "intent": shot.get("intent") or "",
             "subject_type": shot.get("subjectType") or "",
             "subject": shot.get("subject") or "",
             "event_window": shot.get("eventWindow") or "",
             "hook": bool(shot.get("hook")),
             "context": seg.text}
            for i, (seg, shot) in enumerate(zip(segments, shots))]

    last_pct = [22]

    # Plan the video in sequences: runs of lines about one subject and setting,
    # each gathering one pool of shots that the editor call lays out.
    sequences = []
    if config.SEQUENCE_SOURCING:
        report("Planning sequences", 22)
        sequences = director.plan_sequences(segments, shots, brief)

    def on_pool(done, n):
        # 22% -> 50% while the sequence pools are built.
        pct = 22 + int(28 * done / max(n, 1))
        if pct > last_pct[0] or done == n:
            last_pct[0] = max(last_pct[0], pct)
            report(f"Building shot pools {done}/{n} sequences", last_pct[0], done=done, total=n)

    def on_done(done, n):
        # Up to 65% across sourcing, the longest phase; never backwards after the pools.
        pct = 22 + int(43 * done / max(n, 1))
        if pct > last_pct[0]:
            last_pct[0] = pct
            report(f"Sourced {done}/{n} scenes", pct, done=done, total=n)

    assets = media.source_many(
        jobs, work,
        # 8: the per-scene work is mostly waiting on the vision model and the
        # network, and the network side is capped separately (NETWORK_CONCURRENCY).
        workers=int(inp.get("source_workers", 8)),
        allow_youtube=inp.get("allow_youtube"),
        allow_stock=inp.get("allow_stock"),
        require_cc=inp.get("require_cc"),
        on_done=on_done,
        on_review=lambda d, n: report(f"Replacing weak clips {d}/{n}", 65, done=d, total=n),
        rescue=lambda items: director.rescue_queries(items, story=brief),
        on_recheck=lambda n: report(f"Rechecking {n} missing scenes against the story", 66),
        sequences=sequences,
        assign=lambda lines, pool: director.assign_shots(lines, pool, story=brief),
        on_pool=on_pool,
    )
    vision.require_credits()

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
    # Which image/footage sources answered, came back empty, or failed, and why.
    doc["meta"]["sourceStats"] = media.source_stats()
    doc["meta"]["vision"] = vision.stats()
    if vision.out_of_credits():
        doc["meta"]["warnings"].insert(0, (
            "The AI account (Kie) ran out of credits during this job, so vision "
            "checks, AI rescue and AI images stopped partway. Top up Kie and "
            "re-run for full quality."))
    doc["meta"]["audioSource"] = raw_audio
    # Where the sourcing time actually went, visible from outside the worker.
    doc["meta"]["sourcing"] = dict(media.LAST_STATS)
    # What the AI understood the video to be about (kind, event, places, cast
    # with aliases, per-section footage), for the editor to show.
    doc["meta"]["story"] = dict(director.LAST_STORY) or dict(brief)
    # The editor's story card reads startBeat/endBeat/queries; keep both spellings.
    doc["meta"]["story"]["sections"] = [
        {**sec, "startBeat": sec.get("from"), "endBeat": sec.get("to"),
         "queries": sec.get("footage", [])}
        for sec in (doc["meta"]["story"].get("sections") or [])]
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

    # The same matching as the plan: the vision model scores candidates
    # against what the beat should show, not just the search words.
    sem = scene.get("semanticMetadata") or {}
    intent = str(inp.get("intent") or sem.get("intent") or "")[:300]

    report(f"Re-sourcing scene {idx + 1}", 20)
    media.reset_cache()
    media.set_story_script(" ".join(str(s.get("text") or "") for s in scenes))
    story = (doc.get("meta") or {}).get("story") or {}
    if story.get("kind") in ("history", "biography"):
        media.set_story_era(story.get("year"))
    asset = media.source_for_segment(
        query, seconds, work,
        visual_type=scene.get("visualType", "footage"),
        allow_youtube=inp.get("allow_youtube"),
        allow_stock=inp.get("allow_stock"),
        require_cc=inp.get("require_cc"),
        intent=intent, context=str(scene.get("text") or ""),
        subject_type=str(sem.get("subjectType") or ""),
        event_window=str(sem.get("eventWindow") or ""),
    )
    if not asset:
        raise ValueError(f"no usable media found for '{query}' — try different wording")

    scene["media"] = asset.to_scene_media()
    scene["query"] = query
    scene["motion"] = (timeline._IMAGE_MOTIONS[idx % len(timeline._IMAGE_MOTIONS)]
                       if asset.kind == "image" else "none")
    scene["reviewRequired"] = bool(asset.review_required)
    scene["reviewReason"] = asset.review_reason or ""
    scene["semanticMetadata"] = {
        **sem,
        "intent": intent,
        "searchQuery": query,
        "contentDescription": asset.content_description or "",
        "relevanceScore": asset.relevance_score,
        "provider": asset.source or "",
    }

    project_id = inp.get("project_id") or ""
    if project_id and inp.get("publish_media", True):
        report("Saving replacement media", 70)
        publish_media(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                      report, job_id=inp.get("_job_id", ""), band=(70, 72))

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


def _sanitize_stills(doc: dict, work: str) -> int:
    """
    Re-encode every still to a real JPEG before Chrome sees it.

    Web image search saves whatever the server sent under the name it asked
    for: a WebP, an AVIF or an HTML error page named ".jpg". Chrome refuses to
    decode it and Remotion fails the WHOLE render - a real 23-scene job died at
    frame 356 on one airport photo. Each still is decoded by ffmpeg into a
    clean JPEG (remote ones are fetched first); one that cannot be decoded is
    turned into an empty scene, which _fill_missing_media then covers with a
    matching shot. Returns how many stills were dropped.
    """
    from src.assetserver import is_local
    dropped = 0
    medias = [s.get("media") for s in doc.get("scenes", [])]
    medias += [m for o in doc.get("overlays", []) for m in (o.get("media") or [])]
    for n, media in enumerate(medias):
        if not isinstance(media, dict) or media.get("type") != "image" or not media.get("url"):
            continue
        url = media["url"]
        src = url if is_local(url) and os.path.isfile(url) else ""
        if not src and url.startswith("http"):
            src = os.path.join(work, f"still_src_{n}")
            try:
                storage.download(url, src)
            except Exception:  # noqa: BLE001
                src = ""
        out = os.path.join(work, f"still_{n}_{uuid.uuid4().hex[:6]}.jpg")
        ok = False
        if src and os.path.isfile(src):
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-frames:v", "1",
                                "-vf", "scale='min(2560,iw)':-2", "-q:v", "3", out],
                               capture_output=True, timeout=60)
                ok = os.path.isfile(out) and os.path.getsize(out) > 2000
            except (subprocess.TimeoutExpired, FileNotFoundError):
                ok = False
        if ok:
            media["url"] = out
        else:
            dropped += 1
            media.clear()
            media.update({"type": "color", "url": "", "source": "none"})
    if dropped:
        print(f"[worker] {dropped} still(s) could not be decoded; covered by other shots",
              flush=True)
        _fill_missing_media(doc)
    return dropped


def do_render(doc: dict, inp: dict, work: str, report: Reporter) -> dict:
    # The document may have come back from a browser, so validate before
    # spending GPU minutes on it.
    timeline.validate(doc, require_media=True)

    # A plan can sit in the editor for days; any signed URL in it has long
    # since expired. Re-resolve the narration from the reference the plan
    # recorded, then re-sign whatever else points at Supabase.
    # The caller's fresh narration link wins: the plan's own link is signed
    # for hours, and a timeline can sit in the editor for days.
    source = inp.get("audio_url") or (doc.get("meta") or {}).get("audioSource")
    if source:
        try:
            doc["audio"]["url"] = storage.resolve_audio(
                source, bucket=(doc["meta"].get("audioBucket") or "video-audio"))
        except Exception as e:  # noqa: BLE001
            print(f"[worker] could not refresh narration url: {e}", flush=True)
    _sign_supabase_urls(doc)
    _sanitize_stills(doc, work)

    report(f"Rendering {doc['meta'].get('sceneCount', len(doc['scenes']))} scenes", 70)
    out_path = os.path.join(work, "final.mp4")
    last_pct = [70]

    def on_render(frac: float):
        # 70 -> 90%: Remotion's own progress, instead of a bar that sits at 70.
        pct = 70 + int(20 * max(0.0, min(1.0, frac)))
        if pct != last_pct[0]:
            last_pct[0] = pct
            report(f"Rendering video {int(frac * 100)}%", pct)

    renderer.render(
        doc, out_path,
        composition=inp.get("composition", "Main"),
        # Left unset, Remotion auto-detects concurrency from the host's CPU
        # count, which is a GPU pod's real vCPU count - not what a Docker
        # container is actually allowed to spawn threads for. A real render
        # crashed at 4% ("thread::unix::Thread::new::thread_start", a Rust
        # panic in the compositor failing to spawn a new OS thread) right
        # after the heaviest-possible run of the memory/thread-heavy parallel
        # sourcing phase. RENDER_CONCURRENCY caps it to a value verified safe
        # in this container instead.
        concurrency=inp.get("concurrency") or config.RENDER_CONCURRENCY,
        on_progress=on_render,
        # Everything sourced for this job lives here; the renderer serves it
        # over loopback so headless Chrome can actually fetch it.
        serve_dir=work,
    )

    report("Uploading video", 91)
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

    # No key on this worker: the app's broker signs the one destination.
    if storage.broker_enabled() and inp.get("project_id"):
        bucket = config.RENDER_BUCKET
        object_path = f"projects/{inp['project_id']}/final-{int(time.time())}.mp4"
        playable = storage.broker_upload(
            out_path, bucket, object_path, inp["project_id"], inp.get("_job_id", ""),
            read_ttl=int(inp.get("signed_url_ttl", 60 * 60 * 24 * 7)))
        return {
            "video_url": playable,
            "public_url": "",
            "object_path": object_path,
            "bucket": bucket,
            "uploadedVia": "broker",
            "size_bytes": os.path.getsize(out_path),
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
    # The storage broker authorises uploads by the running job's id.
    inp["_job_id"] = job_id
    action = (inp.get("action") or "build").lower()
    project_id = inp.get("project_id") or ""
    report = Reporter(project_id, job=job)
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
                    "imageModelName": config.IMAGE_MODEL if config.IMAGE_API_KEY else "",
                    "preferGenerated": config.PREFER_GENERATED_IMAGES,
                    "imageCapPerVideo": config.IMAGE_MAX_PER_VIDEO,
                    "storage": store,
                    "readyToRender": store.get("ok", False),
                    "machine": _machine(),
                    # Real download check per route: {"probe_youtube": true}.
                    **({"youtube": media.probe_youtube()} if inp.get("probe_youtube") else {}),
                    # One real model call, so only on request: {"probe": true}.
                    **({"vision": vision.probe()} if inp.get("probe") else {})}

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
                              inp.get("media_bucket") or config.MEDIA_BUCKET, report,
                              job_id=job_id)
            doc.setdefault("meta", {})["timings"] = report.timings()
            print(f"[worker] timings {doc['meta']['timings']}", flush=True)
            if project_id:
                storage.patch_project(project_id, {
                    "scene_data": doc, "status": "editing",
                    "current_step": "Timeline ready", "progress": 68,
                })
            return {"ok": True, "action": "plan", "timeline": doc,
                    "vision": vision.stats(),
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
                    "vision": vision.stats(),
                    "elapsed": round(time.time() - started, 1)}

        if action == "render":
            doc = inp.get("timeline")
            if not doc:
                raise ValueError("render requires a `timeline` document")
            # Export must not fail over one empty scene either: that was the
            # "Scene 6 still needs media before it can render" a user hit
            # pressing Render. The gap is filled and flagged in the render
            # copy only; the saved timeline still shows it for Find footage.
            doc = copy.deepcopy(doc)
            patched = _fill_missing_media(doc)
            out = do_render(doc, inp, work, report)
            if project_id:
                storage.patch_project(project_id, _done_fields(out))
            return {"ok": True, "action": "render", **out,
                    "filledScenes": patched,
                    "elapsed": round(time.time() - started, 1)}

        if action == "build":
            doc = do_plan(inp, work, report)
            if project_id:
                storage.patch_project(project_id, {"scene_data": doc})
            # Render from the local files (fast), THEN save the clips, so the
            # finished video opens in the editor with every scene replaceable.
            local_doc = copy.deepcopy(doc)
            patched = _fill_missing_media(local_doc)
            if patched:
                print(f"[worker] {patched} scene(s) had no media; reused a "
                     "nearby clip so the render could complete", flush=True)
            out = do_render(local_doc, inp, work, report)
            if project_id and inp.get("publish_media", True):
                publish_media(doc, project_id, inp.get("media_bucket") or config.MEDIA_BUCKET,
                              report, job_id=job_id, band=(93, 99))
            doc.setdefault("meta", {})["timings"] = report.timings()
            print(f"[worker] timings {doc['meta']['timings']}", flush=True)
            if project_id:
                storage.patch_project(project_id, {**_done_fields(out), "scene_data": doc})
            return {"ok": True, "action": "build", "timeline": doc, **out,
                    "vision": vision.stats(),
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
