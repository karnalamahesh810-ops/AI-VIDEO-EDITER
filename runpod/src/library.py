"""
Clip library: every approved clip, kept for the next video about the subject.

VidRush's "vector library" provider supplied 80 of 345 shots on one of their
timelines; GoMotion re-cuts the same subject videos across projects. A
channel about the water crisis says "Lake Mead", "Hoover Dam" and "Colorado
River" in every video, so after a few videos most lines can be filled from
clips already found, judged and cut - no YouTube search, no proxy traffic,
no vision call.

Storage: bucket video-media, `library/index.json` (the catalogue) and
`library/clips/<id>.mp4`, written through the worker-storage broker with the
running job's authorization. A missing or unreachable library is simply
empty; recording failures are logged, never fatal.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Dict, List, Optional

import requests

from . import config, media, storage

INDEX_PATH = "library/index.json"


def _key(subject: str) -> str:
    text = re.sub(r"\b(the|a|an)\b", " ", re.sub(r"[^a-z0-9 ]+", " ", (subject or "").lower()))
    return " ".join(text.split())


def _safe_id(identity: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", identity)[:80]


class Library:
    def __init__(self, project_id: str = "", job_id: str = "", bucket: str = ""):
        self.project_id, self.job_id = project_id, job_id
        self.bucket = bucket or config.MEDIA_BUCKET
        self.entries: List[dict] = []
        self.loaded = False
        self.added = 0

    @property
    def enabled(self) -> bool:
        return bool(config.CLIP_LIBRARY and self.project_id and self.job_id
                    and storage.broker_enabled())

    @classmethod
    def load(cls, project_id: str, job_id: str, bucket: str = "") -> "Library":
        lib = cls(project_id, job_id, bucket)
        if not lib.enabled:
            return lib
        try:
            url = storage.broker_read_url(lib.bucket, INDEX_PATH, project_id, job_id)
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                lib.entries = [e for e in (r.json().get("clips") or []) if isinstance(e, dict)]
            lib.loaded = True
            print(f"[library] {len(lib.entries)} clip(s) available", flush=True)
        except Exception as e:  # noqa: BLE001 - an unreachable library is an empty one
            print(f"[library] not available: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return lib

    def find(self, subject: str, exclude: Optional[set] = None, n: int = 1,
             min_score: Optional[float] = None) -> List[dict]:
        """Best clips of a subject not already used, most relevant first."""
        key = _key(subject)
        floor = config.CLIP_LIBRARY_MIN_SCORE if min_score is None else min_score
        used = set(exclude or ())
        hits = [e for e in self.entries
                if e.get("subject_key") == key and e.get("id") not in used
                and float(e.get("relevance") or 0) >= floor]
        hits.sort(key=lambda e: (-float(e.get("relevance") or 0), -float(e.get("quality") or 0)))
        return hits[:n]

    def fetch(self, entry: dict, work: str, seconds: float, job: dict) -> Optional[media.MediaAsset]:
        """A library clip as a local asset for one line (None if it cannot be read)."""
        path = os.path.join(work, f"lib_{_safe_id(entry['id'])}.mp4")
        try:
            url = storage.broker_read_url(self.bucket, entry["path"], self.project_id, self.job_id)
            storage.download(url, path)
        except Exception as e:  # noqa: BLE001 - fall back to searching
            print(f"[library] could not fetch {entry.get('id')}: {type(e).__name__}", flush=True)
            return None
        if not media.playable_video(path):
            return None
        return media.MediaAsset(
            kind="video", source="youtube", url=entry.get("url") or "",
            local_path=path, duration=float(entry.get("seconds") or seconds),
            attribution=entry.get("attribution") or "", license=entry.get("license") or "",
            query=entry.get("subject") or "", intent=job.get("intent") or entry.get("subject") or "",
            review_required=bool(entry.get("review_required", True)),
            review_reason=entry.get("review_reason") or "",
            content_description=entry.get("description") or "",
            relevance_score=entry.get("relevance"), quality=entry.get("quality"),
            moment_key=entry["id"])

    def record_from_doc(self, doc: dict) -> int:
        """
        Keep this job's good clips: local video scenes scored >= the floor
        that the library does not have yet. Uploads the clip files first;
        an entry is only written for a clip that made it to storage.
        """
        if not self.enabled:
            return 0
        from .assetserver import is_local
        have = {e.get("id") for e in self.entries}
        added = 0
        for s in doc.get("scenes", []):
            if added >= config.CLIP_LIBRARY_MAX_PER_JOB:
                break
            m, sem = s.get("media") or {}, s.get("semanticMetadata") or {}
            ident = sem.get("assetId") or ""
            url = m.get("url") or ""
            if (m.get("type") != "video" or m.get("source") != "youtube" or not ident
                    or ident in have or not is_local(url) or not os.path.isfile(url)):
                continue
            if float(sem.get("relevanceScore") or 0) < config.CLIP_LIBRARY_MIN_SCORE:
                continue
            if s.get("reviewReason", "").startswith("The downloaded clip was empty"):
                continue
            obj = f"library/clips/{_safe_id(ident)}.mp4"
            try:
                storage.broker_upload(url, self.bucket, obj, self.project_id, self.job_id,
                                      read_ttl=60)
            except Exception as e:  # noqa: BLE001 - keep the video going
                print(f"[library] upload failed for {ident}: {type(e).__name__}", flush=True)
                continue
            self.entries.append({
                "id": ident, "path": obj, "subject": sem.get("subject") or "",
                "subject_key": _key(sem.get("subject") or ""),
                "description": (sem.get("contentDescription") or "")[:300],
                "relevance": sem.get("relevanceScore"), "quality": sem.get("qualityScore"),
                "seconds": round(s.get("durationInFrames", 0) / max(1, doc.get("fps", 30)), 2),
                "url": sem.get("sourceUrl") or "", "attribution": (m.get("attribution") or "")[:200],
                "license": m.get("license") or "", "review_required": bool(s.get("reviewRequired")),
                "review_reason": (s.get("reviewReason") or "")[:120],
                "created": int(time.time()), "project": self.project_id,
            })
            have.add(ident)
            added += 1
        self.added = added
        return added

    def save(self) -> bool:
        if not self.enabled or not self.added:
            return False
        tmp = os.path.join(tempfile.gettempdir(), f"library_index_{os.getpid()}.json")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "updated": int(time.time()), "clips": self.entries}, fh)
            storage.broker_upload(tmp, self.bucket, INDEX_PATH, self.project_id, self.job_id, read_ttl=60)
            print(f"[library] saved: {len(self.entries)} clip(s), {self.added} new", flush=True)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[library] save failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return False
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
