"""
Clip library: every approved clip, kept for the next video about the subject.

VidRush's "vector library" provider supplied 80 of 345 shots on one of their
timelines; GoMotion re-cuts the same subject videos across projects. A
channel about the water crisis says "Lake Mead", "Hoover Dam" and "Colorado
River" in every video, so after a few videos most lines can be filled from
clips already found, judged and cut - no YouTube search, no proxy traffic,
no vision call.

Storage: the clip files live in bucket video-media under
`library/clips/<id>.mp4`, written through the worker-storage broker with the
running job's authorization. The catalogue is the app's `footage_library`
table, read with the broker's `library_query` action and written with
`library_upsert` (rows survive jobs, show in the Library page and in Replace
Clip). An app without those actions yet falls back to the old
`library/index.json`. A missing or unreachable library is simply empty;
recording failures are logged, never fatal.
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
QUERY_LIMIT = 500


def _key(subject: str) -> str:
    text = re.sub(r"\b(the|a|an)\b", " ", re.sub(r"[^a-z0-9 ]+", " ", (subject or "").lower()))
    return " ".join(text.split())


def _safe_id(identity: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", identity)[:80]


def _from_row(row: dict) -> Optional[dict]:
    """A footage_library row in the entry shape find/fetch use."""
    ident = row.get("asset_id") or ""
    if not ident:
        return None
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    return {
        "id": ident, "path": row.get("storage_path") or "", "bucket": row.get("storage_bucket") or "",
        "read_url": row.get("readUrl") or "", "kind": row.get("kind") or "video",
        "subject": row.get("subject") or "", "subject_key": row.get("subject_key") or _key(row.get("subject") or ""),
        "entities": [e for e in (row.get("entities") or []) if isinstance(e, str)],
        "locations": [l for l in (row.get("locations") or []) if isinstance(l, str)],
        "description": row.get("description") or "",
        "relevance": row.get("relevance"), "quality": row.get("quality"),
        "seconds": row.get("seconds"), "url": row.get("source_url") or "",
        "attribution": analysis.get("attribution") or "", "license": analysis.get("license") or "",
        "review_required": bool(analysis.get("reviewRequired", False)),
        "review_reason": analysis.get("reviewReason") or "",
        "usage_count": row.get("usage_count") or 0, "saved": row.get("saved", True),
    }


def _to_row(entry: dict) -> dict:
    """An entry as a footage_library row for library_upsert."""
    return {
        "asset_id": entry["id"], "source": "youtube", "source_url": entry.get("url") or "",
        "storage_bucket": entry.get("bucket") or config.MEDIA_BUCKET, "storage_path": entry.get("path") or "",
        "subject": entry.get("subject") or "", "subject_key": entry.get("subject_key") or "",
        "entities": entry.get("entities") or [], "locations": entry.get("locations") or [],
        "event": entry.get("event") or "", "time_context": entry.get("time_context") or "",
        "description": entry.get("description") or "", "seconds": entry.get("seconds"),
        "quality": entry.get("quality"), "relevance": entry.get("relevance"),
        "kind": entry.get("kind") or "video", "saved": True,
        "analysis": {"attribution": entry.get("attribution") or "", "license": entry.get("license") or "",
                     "reviewRequired": bool(entry.get("review_required")),
                     "reviewReason": entry.get("review_reason") or "", "project": entry.get("project") or ""},
    }


class Library:
    def __init__(self, project_id: str = "", job_id: str = "", bucket: str = ""):
        self.project_id, self.job_id = project_id, job_id
        self.bucket = bucket or config.MEDIA_BUCKET
        self.entries: List[dict] = []
        self.loaded = False
        self.unreadable = False   # the index exists but could not be read: never overwrite it
        self.db = False           # catalogue is the footage_library table, not index.json
        self.added = 0
        self.used: set = set()    # asset ids this job filled a line with

    @property
    def enabled(self) -> bool:
        return bool(config.CLIP_LIBRARY and self.project_id and self.job_id
                    and storage.broker_enabled())

    @classmethod
    def load(cls, project_id: str, job_id: str, bucket: str = "") -> "Library":
        lib = cls(project_id, job_id, bucket)
        if not lib.enabled:
            return lib
        if lib._load_db():
            return lib
        lib._load_index()
        return lib

    def _load_db(self) -> bool:
        """The footage_library rows; False when the app has no library actions yet."""
        try:
            body = storage.broker_library_query(self.project_id, self.job_id, limit=QUERY_LIMIT)
        except Exception as e:  # noqa: BLE001
            text = str(e).lower()
            if "unknown action" in text or "unsupported" in text or "not a valid action" in text:
                return False
            self.loaded = True
            self.db = True
            self.unreadable = True
            print(f"[library] table not readable: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return True
        rows = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return False
        self.entries = [e for e in (_from_row(r) for r in rows if isinstance(r, dict)) if e]
        self.loaded = True
        self.db = True
        print(f"[library] {len(self.entries)} clip(s) in the library", flush=True)
        return True

    def _load_index(self) -> None:
        try:
            url = storage.broker_read_url(self.bucket, INDEX_PATH, self.project_id, self.job_id)
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                self.entries = [e for e in (r.json().get("clips") or []) if isinstance(e, dict)]
            self.loaded = True
            print(f"[library] {len(self.entries)} clip(s) available", flush=True)
        except Exception as e:  # noqa: BLE001 - an unreachable library is an empty one
            if "not found" in str(e).lower() or "404" in str(e):
                # First video for this app: there is no index yet. Good clips
                # from this job will start it.
                self.loaded = True
                print("[library] empty (first video): good clips from this job will seed it", flush=True)
            else:
                self.unreadable = True
                print(f"[library] not available: {type(e).__name__}: {str(e)[:120]}", flush=True)

    def find(self, subject: str, exclude: Optional[set] = None, n: int = 1,
             min_score: Optional[float] = None) -> List[dict]:
        """Best clips of a subject not already used, most relevant first."""
        key = _key(subject)
        if not key:
            return []
        floor = config.CLIP_LIBRARY_MIN_SCORE if min_score is None else min_score
        used = set(exclude or ())

        def matches(e: dict) -> bool:
            if e.get("subject_key") == key:
                return True
            # A row saved under another line's subject still shows the place
            # or thing this line names.
            names = {_key(x) for x in (e.get("entities") or []) + (e.get("locations") or [])}
            return key in names

        hits = [e for e in self.entries
                if e.get("kind", "video") == "video" and e.get("saved", True)
                and matches(e) and e.get("id") not in used
                and float(e.get("relevance") or 0) >= floor]
        hits.sort(key=lambda e: (e.get("subject_key") != key, -float(e.get("relevance") or 0),
                                 -float(e.get("quality") or 0)))
        return hits[:n]

    def fetch(self, entry: dict, work: str, seconds: float, job: dict) -> Optional[media.MediaAsset]:
        """A library clip as a local asset for one line (None if it cannot be read)."""
        path = os.path.join(work, f"lib_{_safe_id(entry['id'])}.mp4")
        try:
            url = entry.get("read_url") or storage.broker_read_url(
                entry.get("bucket") or self.bucket, entry["path"], self.project_id, self.job_id)
            storage.download(url, path)
        except Exception as e:  # noqa: BLE001 - fall back to searching
            print(f"[library] could not fetch {entry.get('id')}: {type(e).__name__}", flush=True)
            return None
        if not media.playable_video(path):
            return None
        self.used.add(entry["id"])
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
        from concurrent.futures import ThreadPoolExecutor, wait
        have = {e.get("id") for e in self.entries}
        added = 0
        picks = []
        for s in doc.get("scenes", []):
            if len(picks) >= config.CLIP_LIBRARY_MAX_PER_JOB:
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
            picks.append((s, m, sem, ident, url))
            have.add(ident)

        # Uploads run eight at a time under one time box: a real job sat
        # here for many minutes uploading clips one by one before it could
        # show its storyboard. What does not make it in time is skipped.
        def upload(item):
            _s, _m, _sem, ident, url = item
            obj = f"library/clips/{_safe_id(ident)}.mp4"
            storage.broker_upload(url, self.bucket, obj, self.project_id, self.job_id, read_ttl=60)
            return obj

        uploaded = {}
        if picks:
            pool = ThreadPoolExecutor(max_workers=8)
            futs = {pool.submit(upload, it): it for it in picks}
            done, _late = wait(futs, timeout=config.LIBRARY_SAVE_SECONDS)
            pool.shutdown(wait=False, cancel_futures=True)
            for f in done:
                it = futs[f]
                try:
                    uploaded[it[3]] = f.result()
                except Exception as e:  # noqa: BLE001 - keep the video going
                    print(f"[library] upload failed for {it[3]}: {type(e).__name__}", flush=True)
            if _late:
                print(f"[library] {len(_late)} clip(s) not saved in {config.LIBRARY_SAVE_SECONDS:.0f}s; skipped",
                      flush=True)
        for s, m, sem, ident, url in picks:
            obj = uploaded.get(ident)
            if not obj:
                continue
            intent = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else {}
            self.entries.append({
                "id": ident, "path": obj, "bucket": self.bucket, "kind": "video",
                "subject": sem.get("subject") or "",
                "subject_key": _key(sem.get("subject") or ""),
                "entities": [e for e in (intent.get("entities") or []) if isinstance(e, str)][:12],
                "locations": [l for l in (intent.get("locations") or []) if isinstance(l, str)][:12],
                "event": (intent.get("event_type") or "")[:80],
                "time_context": (intent.get("time_context") or sem.get("eventWindow") or "")[:80],
                "description": (sem.get("contentDescription") or "")[:300],
                "relevance": sem.get("relevanceScore"), "quality": sem.get("qualityScore"),
                "seconds": round(s.get("durationInFrames", 0) / max(1, doc.get("fps", 30)), 2),
                "url": sem.get("sourceUrl") or "", "attribution": (m.get("attribution") or "")[:200],
                "license": m.get("license") or "", "review_required": bool(s.get("reviewRequired")),
                "review_reason": (s.get("reviewReason") or "")[:120],
                "created": int(time.time()), "project": self.project_id, "_new": True,
            })
            added += 1
        self.added = added
        return added

    def save(self) -> bool:
        if not self.enabled or not (self.added or self.used):
            return False
        if self.db:
            return self._save_db()
        if not self.added:
            return False
        if self.unreadable:
            print("[library] not saved: the index could not be read, so it is left as it is", flush=True)
            return False
        tmp = os.path.join(tempfile.gettempdir(), f"library_index_{os.getpid()}.json")
        try:
            clips = [{k: v for k, v in e.items() if not k.startswith("_")} for e in self.entries]
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "updated": int(time.time()), "clips": clips}, fh)
            storage.broker_upload(tmp, self.bucket, INDEX_PATH, self.project_id, self.job_id, read_ttl=60)
            print(f"[library] saved: {len(self.entries)} clip(s), {self.added} new", flush=True)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[library] save failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return False
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def _save_db(self) -> bool:
        """New rows plus a usage mark for every library clip this job used."""
        rows = [_to_row(e) for e in self.entries if e.get("_new")]
        new_ids = {r["asset_id"] for r in rows}
        rows += [{"asset_id": i, "used": True} for i in sorted(self.used) if i not in new_ids]
        for r in rows:
            if r["asset_id"] in self.used:
                r["used"] = True
        if not rows:
            return False
        try:
            body = storage.broker_library_upsert(self.project_id, self.job_id, rows)
            print(f"[library] saved to the library table: {self.added} new, {len(self.used)} used "
                  f"({body.get('upserted', len(rows))} rows)", flush=True)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[library] table save failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return False
