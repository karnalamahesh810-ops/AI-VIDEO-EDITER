"""
A stopped plan or build keeps what it made, so its Retry does not pay for it again (AI_RESUME, 2026-10-09).

When the job's AI stops (src/aiguard.py: the account ran dry, the key was refused, every model down), the plan or
build fails with a plain "top up, then press Retry" - and before it does, this saves on R2, under
projects/<project>/resume/<sig>.json:

  words    the narration's word timings (whisper's minute or two is not run again);
  brief    the story brief (one planning call);
  shots    the planner's own shots, as the AI pass wrote them (director.LAST_AI_SHOTS - the expensive part: a
           20-minute video's planning was $0.87 on fd58f969), with the signature of the beats they belong to;
  assets   every judged clip and picture already found for a line - its file copied to
           projects/<project>/resume/<sig>/, its record (media.MediaAsset) beside it.

The app's Retry sends the same job again (video-v2: the same action, audio, script, title and settings - no
resume flag). `sig` is those inputs' fingerprint, so the Retry finds the file without any app change; a changed
script, title, style or switch makes another sig, and nothing is reused. Whatever the Retry reads is used only where
it still fits: the words when they are there, the brief and the shots only for the same beats (segment_sig),
an asset only for its own line. The file is removed when the Retry finishes. Nothing here raises: an unreadable or
missing checkpoint is a fresh start; a save that fails is a Retry that pays again, never a failed job.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from . import config

VERSION = 1
# A checkpoint older than this is not read (a Retry days later starts fresh: the sources may have changed).
MAX_AGE_SECONDS = 3 * 24 * 3600.0
# Files copied up at once when a checkpoint is saved.
PARALLEL = 6


def enabled(project_id: str = "") -> bool:
    """Resume is on (AI_RESUME), the job belongs to a project, and R2 can hold the checkpoint."""
    if not getattr(config, "AI_RESUME", True) or not project_id:
        return False
    try:
        from . import r2
        return bool(r2.enabled())
    except Exception:  # noqa: BLE001
        return False


def _h(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", "replace")).hexdigest()


def signature(inp: dict, audio: str = "") -> str:
    """The fingerprint of what a Retry must share with the stopped job: the narration (its link - the made one for
    a script-only job - or the script), the title, the style and every switch that changes what is planned or
    searched."""
    keys = {
        "v": VERSION,
        "audio": str(audio or inp.get("audio_url") or inp.get("audio_path") or ""),
        "script": _h(inp.get("script") or ""),
        "title": str(inp.get("title") or inp.get("title_overlay") or ""),
        "style": str(inp.get("video_style") or ""),
        "maps": bool(inp.get("maps", True)),
        "allow_youtube": inp.get("allow_youtube"),
        "youtube_only": bool(inp.get("youtube_only")),
        "require_cc": inp.get("require_cc"),
        "allow_stock": inp.get("allow_stock"),
        "language": str(inp.get("language") or ""),
        "scene_queries": inp.get("scene_queries") or {},
        "config": inp.get("config") if isinstance(inp.get("config"), dict) else {},
        "brand": _h(json.dumps(inp.get("brand_kit") or inp.get("brand") or {}, sort_keys=True, default=str)),
    }
    return _h(json.dumps(keys, sort_keys=True, default=str))[:20]


def segment_sig(segments) -> str:
    """The fingerprint of a list of beats (their words and times): saved shots belong to these beats only."""
    rows = [[str(getattr(s, "text", "") or ""), round(float(getattr(s, "start", 0.0) or 0.0), 2),
             round(float(getattr(s, "end", 0.0) or 0.0), 2)] for s in segments or []]
    return _h(json.dumps(rows))[:20]


def _key(project_id: str, sig: str) -> str:
    return f"projects/{project_id}/resume/{sig}.json"


def _file_key(project_id: str, sig: str, index: int, path: str) -> str:
    ext = os.path.splitext(path or "")[1].lower() or ".bin"
    return f"projects/{project_id}/resume/{sig}/s{int(index):04d}{ext}"


# --------------------------------------------------------------------------- #
# The job's own record of what it made (filled as it goes, saved on a stop)
# --------------------------------------------------------------------------- #

_LOCK = threading.Lock()
_JOB: Dict[str, Any] = {}


def start(project_id: str, sig: str, loaded: Optional[dict] = None) -> None:
    """A plan or build begins: what it makes is recorded under this project and sig."""
    with _LOCK:
        _JOB.clear()
        _JOB.update(project=project_id or "", sig=sig or "", words=None, brief=None, segSig="", planSig="",
                    shots={}, assets={}, loaded=loaded or {}, used=False)
    _forget_shots()


def _forget_shots() -> None:
    """The planner's record of its own shots belongs to one job: a warm worker's last job left its shots there, and
    a stop before this job's plan (the brief, the preflight) must never save them as this job's."""
    from . import director
    with director._AI_SHOTS_LOCK:
        director.LAST_AI_SHOTS.clear()


def reset() -> None:
    with _LOCK:
        _JOB.clear()
    _forget_shots()


def active() -> bool:
    with _LOCK:
        return bool(_JOB.get("project") and _JOB.get("sig"))


def note_words(words) -> None:
    with _LOCK:
        if _JOB:
            _JOB["words"] = [[str(w.text), float(w.start), float(w.end)] for w in words or []]


def note_brief(brief: Optional[dict], segments) -> None:
    with _LOCK:
        if _JOB and isinstance(brief, dict):
            _JOB["brief"] = json.loads(json.dumps(brief, default=str))
            _JOB["segSig"] = segment_sig(segments)


def note_plan_segments(segments) -> None:
    """The beats the planner's shots belong to (after the name cuts, the hook booster and the shot cap)."""
    with _LOCK:
        if _JOB:
            _JOB["planSig"] = segment_sig(segments)


def note_assets(assets) -> None:
    """The lines' assets as they stand (a list by line index, or {index: asset}): the judged ones are kept."""
    items = assets.items() if isinstance(assets, dict) else enumerate(assets or [])
    with _LOCK:
        if not _JOB:
            return
        for i, a in items:
            if a is not None and getattr(a, "local_path", "") and keepable(a):
                _JOB["assets"][int(i)] = a


def keepable(asset) -> bool:
    """An asset a Retry may take back as it is: it has a vision verdict (a score), or it needs none (the user's
    own clip, a map, a chart, a picture the worker made). Never one placed unjudged."""
    if getattr(asset, "relevance_score", None) is not None:
        return True
    return str(getattr(asset, "source", "") or "") in ("own", "user", "upload", "generated", "map", "chart")


# --------------------------------------------------------------------------- #
# Load and save
# --------------------------------------------------------------------------- #

def load(project_id: str, sig: str) -> Optional[dict]:
    """The stopped job's checkpoint for these inputs, or None (none, too old, unreadable, another version)."""
    if not enabled(project_id) or not sig:
        return None
    try:
        from . import r2
        raw = r2.get_bytes(_key(project_id, sig), timeout=30)
        data = json.loads(raw.decode("utf-8")) if raw else None
    except Exception as e:  # noqa: BLE001 - a fresh start
        print(f"[resume] no checkpoint read: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    if not isinstance(data, dict) or data.get("v") != VERSION or data.get("sig") != sig:
        return None
    if time.time() - float(data.get("at") or 0.0) > MAX_AGE_SECONDS:
        return None
    print(f"[resume] checkpoint found: {len(data.get('words') or [])} words, brief "
          f"{'yes' if data.get('brief') else 'no'}, {len(data.get('shots') or {})} planned lines, "
          f"{len(data.get('assets') or {})} judged clips and pictures", flush=True)
    return data


def save(reason: str = "") -> bool:
    """Write what this job made to R2 (the files first, then the record). True when a checkpoint now exists."""
    with _LOCK:
        if not _JOB.get("project") or not _JOB.get("sig"):
            return False
        job = dict(_JOB)
        assets = dict(_JOB.get("assets") or {})
    project, sig = job["project"], job["sig"]
    if not enabled(project):
        return False
    from . import director
    shots = {}
    with director._AI_SHOTS_LOCK:
        shots = {str(k): v for k, v in director.LAST_AI_SHOTS.items()}
    loaded = job.get("loaded") or {}
    if not shots and loaded.get("shots") and loaded.get("planSig") == job.get("planSig"):
        shots = dict(loaded["shots"])
    saved_assets = dict(loaded.get("assets") or {}) if loaded.get("planSig") == job.get("planSig") else {}
    from . import r2

    def put(item):
        i, a = item
        try:
            key = _file_key(project, sig, i, a.local_path)
            r2.upload(a.local_path, key, content_type=r2.content_type(a.local_path))
            fields = {k: v for k, v in dataclasses.asdict(a).items() if k != "local_path"}
            fields["alternatives"] = [{k: v for k, v in alt.items() if k != "localPath"}
                                      for alt in fields.get("alternatives") or [] if isinstance(alt, dict)]
            return str(i), {"file": key, "fields": fields}
        except Exception as e:  # noqa: BLE001 - that line is searched again on the Retry
            print(f"[resume] line {i + 1} not kept: {type(e).__name__}: {str(e)[:80]}", flush=True)
            return str(i), None

    from concurrent.futures import ThreadPoolExecutor
    todo = [(i, a) for i, a in sorted(assets.items()) if a.local_path and os.path.isfile(a.local_path)]
    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        for k, got in ex.map(put, todo):
            if got is not None:
                saved_assets[k] = got
    record = {"v": VERSION, "sig": sig, "at": time.time(), "reason": reason or "",
              "words": job.get("words") or loaded.get("words") or [],
              "brief": job.get("brief") or loaded.get("brief"), "segSig": job.get("segSig") or loaded.get("segSig") or "",
              "planSig": job.get("planSig") or loaded.get("planSig") or "", "shots": shots, "assets": saved_assets}
    try:
        r2.upload_bytes(json.dumps(record, default=str).encode("utf-8"), _key(project, sig),
                        content_type="application/json")
    except Exception as e:  # noqa: BLE001 - the Retry starts over
        print(f"[resume] checkpoint not saved: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return False
    print(f"[resume] kept for the Retry: {len(record['words'])} words, {len(shots)} planned lines, "
          f"{len(saved_assets)} judged clips and pictures", flush=True)
    return True


def restore_assets(data: Optional[dict], work: str, plan_sig: str) -> Dict[int, Any]:
    """The checkpoint's judged assets as local MediaAssets ({line index: asset}) - only for the same beats
    (plan_sig) - their files fetched back from R2 into `work`. A file that cannot be fetched leaves its line to
    the search."""
    if not data or not data.get("assets") or data.get("planSig") != plan_sig:
        return {}
    from . import media, r2
    names = {f.name for f in dataclasses.fields(media.MediaAsset)}
    out: Dict[int, Any] = {}
    os.makedirs(work, exist_ok=True)

    def get(item):
        k, row = item
        try:
            key = str(row.get("file") or "")
            body = r2.get_bytes(key, timeout=120)
            if not body:
                return k, None
            path = os.path.join(work, "resume_" + os.path.basename(key))
            with open(path, "wb") as fh:
                fh.write(body)
            fields = {n: v for n, v in (row.get("fields") or {}).items() if n in names}
            fields["local_path"] = path
            return k, media.MediaAsset(**fields)
        except Exception as e:  # noqa: BLE001 - searched again
            print(f"[resume] line {int(k) + 1} not restored: {type(e).__name__}: {str(e)[:80]}", flush=True)
            return k, None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        for k, a in ex.map(get, list((data.get("assets") or {}).items())):
            if a is not None:
                out[int(k)] = a
    if out:
        print(f"[resume] {len(out)} judged clips and pictures taken back from the stopped job", flush=True)
    return out


def clear(project_id: str, sig: str) -> None:
    """The Retry finished: its checkpoint and files go (in the background; a leftover costs only storage)."""
    if not enabled(project_id) or not sig:
        return

    def run():
        try:
            from . import r2
            for row in r2.list_keys(f"projects/{project_id}/resume/{sig}/") or []:
                k = row.get("key") or row.get("Key") or ""
                if k:
                    r2.delete(k)
            r2.delete(_key(project_id, sig))
        except Exception as e:  # noqa: BLE001
            print(f"[resume] checkpoint not removed: {type(e).__name__}: {str(e)[:80]}", flush=True)
    threading.Thread(target=run, daemon=True).start()
