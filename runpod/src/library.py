"""
Clip library: every approved clip and photo, kept for the next video about
the subject.

VidRush's "vector library" provider supplied 80 of 345 shots on one of their
timelines; GoMotion re-cuts the same subject videos across projects. A
channel about the water crisis says "Lake Mead", "Hoover Dam" and "Colorado
River" in every video, so after a few videos most lines can be filled from
clips already found, judged and cut - no YouTube search, no proxy traffic,
no vision call.

Catalogue: the app's `footage_library` table, read with the worker-storage
broker's `library_query` action and written with `library_upsert` (rows
survive jobs, show in the Library page and in Replace Clip).

Files (2026-09-30): the library's own Cloudflare R2 bucket (src/libstore.py)
- clips/, images/, thumbs/ and CLIP embedding sidecars under embeddings/ -
with rows marked storage_bucket "r2:<bucket>" and read straight from the
public URL: no broker, no signing. Every clip and photo passes libstore's
quality gate before it is kept, and a duplicate of a kept clip is not kept.

Rows from before R2 (bucket video-media, library/clips/<id>.mp4) are still
read through the broker. A background pass started with each plan/build job
(start_maintenance -> Library.maintain) checks them against the same gate:
good ones are copied to R2 and their row repointed, bad ones are marked
saved=false with analysis.removedReason - reversible from the Library page;
nothing is deleted. A bad old clip a job happens to fetch before the pass
reaches it is caught the same way and not used.

Without R2 the old behaviour stands (clips uploaded to
video-media/library/clips through the broker; an app without the table falls
back to library/index.json). A missing or unreachable library is simply
empty; failures are logged, never fatal.

No reuse across videos (the owner, 2026-09-30: "the same clip was literally
used in the previous video"). With the cross-video ledger on (src/ledger.py)
find() never offers a clip an earlier video showed - its asset id or its
YouTube moment is in the ledger - and record_from_doc keeps each job's
approved clips the video did NOT show instead of the ones it did
(LIBRARY_SAVE_UNUSED): the runner-ups the judge passed (their files kept for
this while the job runs: media.keep_alternatives_for_library) and up to
LIBRARY_SPARES_MAX of the subject pools' spare moments (downloaded here). The
library still saves later videos their searches, and never with a repeat.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Dict, List, Optional

import requests

from . import config, ledger, libstore, media, storage

INDEX_PATH = "library/index.json"
# The broker signs two URLs per row it returns: 500 rows meant ~1000 storage
# calls in one burst against the app's small database, two minutes before it
# stopped answering on 2026-09-29.
QUERY_LIMIT = 250
# Never kept: a generated picture, a live satellite loop, an empty scene, or
# the user's own upload (the app saves those itself).
_NEVER_SOURCES = {"", "none", "generated", "noaa_goes", "upload", "animation", "color"}
# Row kinds the gate may judge and move (the user's uploads are left alone).
_CHECKED_KINDS = ("video", "image")
_STOP = {"the", "a", "an", "of", "in", "on", "at", "and", "or", "to", "for", "with", "from", "by",
         "after", "before", "during", "near", "over", "new", "news", "update", "live"}
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _key(subject: str) -> str:
    text = re.sub(r"\b(the|a|an)\b", " ", re.sub(r"[^a-z0-9 ]+", " ", (subject or "").lower()))
    return " ".join(text.split())


def _safe_id(identity: str) -> str:
    return libstore.safe_id(identity)


def _stem(word: str) -> str:
    for suf in ("ing", "es", "ed", "s"):
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[:-len(suf)]
    return word


def _words(text: str) -> set:
    return {_stem(w) for w in _key(text).split()
            if len(w) > 2 and w not in _STOP and not w.isdigit()}


def _contains(a: str, b: str) -> bool:
    """One place name inside the other, on word boundaries ("texas" / "north texas")."""
    return bool(a and b) and (f" {a} " in f" {b} " or f" {b} " in f" {a} ")


def _date(text: str) -> Optional[datetime.date]:
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", str(text or ""))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def _from_row(row: dict) -> Optional[dict]:
    """A footage_library row in the entry shape find/fetch use."""
    ident = row.get("asset_id") or ""
    if not ident:
        return None
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    bucket, path = row.get("storage_bucket") or "", row.get("storage_path") or ""
    read = row.get("readUrl") or ""
    thumb = row.get("thumbnail_path") or ""
    if libstore.is_r2_ref(bucket):
        # Public: this worker builds the URL itself; the row and the broker agree.
        read = libstore.url_for(bucket, path) or analysis.get("publicUrl") or read
        thumb_url = libstore.url_for(bucket, thumb) or analysis.get("thumbUrl") or row.get("thumbUrl") or ""
    else:
        if path.startswith("http"):
            read = path
        thumb_url = thumb if thumb.startswith("http") else (row.get("thumbUrl") or "")
    return {
        "id": ident, "path": path, "bucket": bucket, "read_url": read, "kind": row.get("kind") or "video",
        "source": row.get("source") or "youtube",
        "subject": row.get("subject") or "", "subject_key": row.get("subject_key") or _key(row.get("subject") or ""),
        "entities": [e for e in (row.get("entities") or []) if isinstance(e, str)],
        "locations": [l for l in (row.get("locations") or []) if isinstance(l, str)],
        "event": row.get("event") or "", "time_context": row.get("time_context") or "",
        "description": row.get("description") or "",
        "relevance": row.get("relevance"), "quality": row.get("quality"),
        "seconds": row.get("seconds"), "width": row.get("width"), "height": row.get("height"),
        "url": row.get("source_url") or "",
        "attribution": analysis.get("attribution") or "", "license": analysis.get("license") or "",
        "review_required": bool(analysis.get("reviewRequired", False)),
        "review_reason": analysis.get("reviewReason") or "",
        "usage_count": row.get("usage_count") or 0, "saved": row.get("saved", True),
        "thumb": thumb, "thumb_url": thumb_url, "created": row.get("created_at") or "",
        "analysis": analysis, "phash": libstore.parse_hashes(analysis.get("phash")),
    }


def _to_row(entry: dict) -> dict:
    """An entry as a footage_library row for library_upsert."""
    analysis = {"attribution": entry.get("attribution") or "", "license": entry.get("license") or "",
                "reviewRequired": bool(entry.get("review_required")),
                "reviewReason": entry.get("review_reason") or "", "project": entry.get("project") or ""}
    analysis.update(entry.get("extra") or {})
    row = {
        "asset_id": entry["id"], "source": entry.get("source") or "youtube", "source_url": entry.get("url") or "",
        "storage_bucket": entry.get("bucket") or config.MEDIA_BUCKET, "storage_path": entry.get("path") or "",
        "subject": entry.get("subject") or "", "subject_key": entry.get("subject_key") or "",
        "entities": entry.get("entities") or [], "locations": entry.get("locations") or [],
        "event": entry.get("event") or "", "time_context": entry.get("time_context") or "",
        "description": entry.get("description") or "", "seconds": entry.get("seconds"),
        "quality": entry.get("quality"), "relevance": entry.get("relevance"),
        "kind": entry.get("kind") or "video", "saved": True,
        "analysis": analysis,
    }
    # Only what is known: the old path measures nothing.
    for col, k in (("thumbnail_path", "thumb"), ("width", "width"), ("height", "height")):
        if entry.get(k):
            row[col] = entry[k]
    return row


def _user_kept(entry: dict) -> bool:
    """The owner put this clip back from Removed: the check never takes it out again."""
    return bool((entry.get("analysis") or {}).get("restoredAt"))


def _removal_row(entry: dict, verdict: "libstore.Verdict") -> dict:
    """saved=false with the reason; the old analysis is kept (reversible from the app)."""
    return {"asset_id": entry["id"], "saved": False,
            "analysis": {**(entry.get("analysis") or {}), "removedReason": "; ".join(verdict.reasons)[:300],
                         "removedAt": libstore.now_iso(), "removedBy": "library-check",
                         "check": verdict.summary()}}


def _last_story() -> dict:
    try:
        from . import director       # lazy: director is heavy and never imports the library
        return dict(director.LAST_STORY or {})
    except Exception:  # noqa: BLE001
        return {}


def _current(brief: dict) -> bool:
    try:
        from . import director
        return bool(director.current_story(brief))
    except Exception:  # noqa: BLE001
        return False


def saves_unused() -> bool:
    """The library keeps a job's unused approved moments, not its shown clips (the ledger keeps those out)."""
    return bool(config.LIBRARY_SAVE_UNUSED and ledger.on())


def shown(entry: dict) -> bool:
    """A clip a finished video shows (record_shown): the owner may pick it by hand, the picker never does."""
    return bool((entry.get("analysis") or {}).get("shownIn"))


def _r2_location(url: str) -> Optional[tuple]:
    """(bucket, key) of a link under one of our R2 public bases, else None."""
    for base, bucket in ((config.R2_PUBLIC_BASE, config.R2_BUCKET),
                         (getattr(config, "R2_LIBRARY_PUBLIC_BASE", ""), getattr(config, "R2_LIBRARY_BUCKET", ""))):
        base = (base or "").rstrip("/")
        if base and bucket and str(url or "").startswith(base + "/"):
            from urllib.parse import unquote
            return bucket, unquote(str(url)[len(base) + 1:].split("?", 1)[0])
    return None


def shown_rows(doc: dict, project_id: str) -> List[dict]:
    """
    One footage_library row per clip or picture file the video shows, stored
    on our R2 (the scene media publish puts every one there): the file, its
    still, the line's subject, the vision model's description, the source and
    its scores. Marked shownIn: the automatic picker never puts it in another
    video (the cross-video rule, src/ledger.py); the owner can, by hand.
    """
    rows, seen = [], set()
    for s in (doc or {}).get("scenes") or []:
        m = s.get("media") if isinstance(s, dict) else None
        if not isinstance(m, dict) or m.get("type") not in ("video", "image"):
            continue
        loc = _r2_location(m.get("url") or "")
        if not loc or loc[1] in seen:
            continue
        seen.add(loc[1])
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        thumb = _r2_location(m.get("thumbnail") or "")
        subject = str(sem.get("subject") or sem.get("searchQuery") or s.get("query") or "")[:200]
        kind = ("generated" if m.get("generated") or m.get("source") == "generated"
                else "image" if m.get("type") == "image" else "video")
        rows.append({
            "asset_id": f"file:{loc[1]}", "kind": kind, "source": str(m.get("source") or ""),
            "source_url": str(sem.get("sourceUrl") or m.get("sourceUrl") or ""),
            "storage_bucket": f"r2:{loc[0]}", "storage_path": loc[1],
            **({"thumbnail_path": thumb[1]} if thumb and thumb[0] == loc[0] else {}),
            "subject": subject, "subject_key": _key(subject),
            "description": str(sem.get("contentDescription") or "")[:2000],
            "seconds": m.get("clipSeconds"), "quality": m.get("qualityScore"),
            "relevance": m.get("relevanceScore") if m.get("relevanceScore") is not None else sem.get("relevanceScore"),
            "saved": True, "used": True,
            "analysis": {"shownIn": project_id, "publicUrl": m.get("url"), "thumbUrl": m.get("thumbnail") or "",
                         "attribution": str(m.get("attribution") or "")[:200], "license": str(m.get("license") or ""),
                         "line": str(s.get("text") or "")[:300]},
        })
    return rows


def record_shown(doc: dict, project_id: str, job_id: str) -> int:
    """
    Every clip and picture of the finished video into the app's library (the
    owner, 2026-10-01: "you're saving clips on Cloudflare and it's not showing
    on this library" - only the unused runner-ups were kept, and the Lake
    Powell video added 1 clip for 159 scenes). Before the job's done write: the
    broker only takes rows while the project is still rendering. Never fails a
    video; returns how many rows were written.
    """
    if not (config.LIBRARY_SHOWN and project_id and job_id and storage.broker_enabled()):
        return 0
    rows = shown_rows(doc, project_id)
    done = 0
    try:
        for k in range(0, len(rows), 100):
            got = storage.broker_library_upsert(project_id, job_id, rows[k:k + 100])
            done += int(got.get("upserted") or 0)
        print(f"[library] {done} clip(s) and picture(s) of this video are in the library", flush=True)
    except Exception as e:  # noqa: BLE001 - the library must never fail a video
        print(f"[library] the video's clips were not added: {type(e).__name__}: {str(e)[:160]}", flush=True)
    return done


def _strip_local_alternatives(doc: dict) -> None:
    """The runner-ups' local files were only for the library: no work-dir path goes into the saved timeline."""
    for s in (doc or {}).get("scenes") or []:
        sem = s.get("semanticMetadata") if isinstance(s, dict) else None
        for alt in (sem or {}).get("alternatives") or []:
            if isinstance(alt, dict):
                alt.pop("localPath", None)


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
        self.pending: Dict[str, dict] = {}   # row changes found while fetching (removals)
        self.rejected: Dict[str, int] = {}   # why new clips were not kept, counted
        self.story: Optional[dict] = None    # the story brief (else director.LAST_STORY)
        self._lock = threading.Lock()
        self._emb: Dict[str, list] = {}      # asset id -> CLIP embedding, for search()

    @property
    def enabled(self) -> bool:
        return bool(config.CLIP_LIBRARY and self.project_id and self.job_id
                    and storage.broker_enabled())

    @classmethod
    def load(cls, project_id: str, job_id: str, bucket: str = "") -> "Library":
        lib = cls(project_id, job_id, bucket)
        if not lib.enabled:
            return lib
        # The judge's runner-ups stay on disk for record_from_doc: the video
        # does not show them, so the library keeps them for later videos.
        media.keep_alternatives_for_library(saves_unused() and libstore.enabled())
        # The pass started with this job may still be moving a clip: let it
        # finish what it holds, then use the rows it loaded and updated (one
        # library query per job, not two).
        wait_maintenance()
        m = _MAINT.get("lib")
        if isinstance(m, Library) and (m.project_id, m.job_id) == (project_id, job_id) \
                and m.loaded and m.db and not m.unreadable:
            _MAINT["lib"] = None
            lib.entries, lib.loaded, lib.db = list(m.entries), True, True
            print(f"[library] {len(lib.entries)} item(s) in the library (as checked by this job's pass)", flush=True)
        elif not lib._load_db():
            lib._load_index()
            return lib
        if libstore.enabled() and any(lib._legacy(e) and e.get("saved", True) for e in lib.entries):
            libstore.warm()              # old clips are judged as they are fetched, in pool threads
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
        on_r2 = sum(1 for e in self.entries if libstore.is_r2_ref(e.get("bucket")))
        removed = sum(1 for e in self.entries if not e.get("saved", True))
        print(f"[library] {len(self.entries)} item(s) in the library ({on_r2} on R2, {removed} removed)",
              flush=True)
        return True

    def _load_legacy(self) -> int:
        """
        Old rows beyond the first QUERY_LIMIT (the broker's `legacy` filter),
        merged in for the maintenance pass. Only asked when the first query
        came back full; an app without the filter returns rows already here.
        """
        if len(self.entries) < QUERY_LIMIT:
            return 0
        try:
            body = storage.broker_library_query(self.project_id, self.job_id, limit=QUERY_LIMIT, legacy=True)
        except Exception as e:  # noqa: BLE001 - the pass works on what it has
            print(f"[library] old rows not listed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return 0
        have = {e["id"] for e in self.entries}
        added = 0
        for r in (body.get("rows") if isinstance(body, dict) else None) or []:
            e = _from_row(r) if isinstance(r, dict) else None
            if e and e["id"] not in have:
                self.entries.append(e)
                have.add(e["id"])
                added += 1
        return added

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

    # ------------------------------------------------------------------ #
    # Finding
    # ------------------------------------------------------------------ #

    def set_story(self, brief: Optional[dict]) -> None:
        self.story = dict(brief or {})

    def _context(self, story: Optional[dict] = None) -> dict:
        brief = story if story is not None else (self.story if self.story is not None else _last_story())
        if not isinstance(brief, dict) or not brief:
            return {}
        places = [_key(p) for p in (brief.get("places") or []) if isinstance(p, str) and _key(p)]
        place_words = {w for p in places for w in _words(p)}
        current = _current(brief)
        year = brief.get("year") if isinstance(brief.get("year"), int) and not isinstance(brief.get("year"), bool) \
            else None
        if current and not year:
            year = datetime.date.today().year
        return {"places": places, "event": _words(brief.get("event") or "") - place_words,
                "current": current, "year": year}

    @staticmethod
    def _hits(e: dict, ctx: dict, subject: str = "") -> int:
        """How many of the story's place and event this entry shows (0-2)."""
        if not ctx:
            return 0
        names = {_key(x) for x in (e.get("locations") or []) + (e.get("entities") or [])}
        names.add(e.get("subject_key") or _key(e.get("subject") or ""))
        place = any(_contains(p, x) for p in ctx.get("places") or () for x in names if x)
        # "Lake Mead drought" for a Lake Mead line: the event is "drought".
        wanted = (ctx.get("event") or set()) - _words(subject)
        event = bool(wanted and wanted & _words(f"{e.get('event') or ''} {e.get('description') or ''}"))
        return int(place) + int(event)

    @staticmethod
    def _recorded(e: dict) -> Optional[datetime.date]:
        a = e.get("analysis") or {}
        return _date(a.get("recordedAt") or "") or _date(e.get("created") or "") or \
            (datetime.date.fromtimestamp(e["created"]) if isinstance(e.get("created"), (int, float)) else None)

    def _fresh(self, e: dict, ctx: dict) -> float:
        """1 for a clip recorded this week, falling to 0 at LIBRARY_FRESH_DAYS; 0 unless a current story."""
        if not ctx.get("current"):
            return 0.0
        when = self._recorded(e)
        if when is None:
            return 0.0
        days = (datetime.date.today() - when).days
        return 1.0 if days <= 7 else max(0.0, 1.0 - (days - 7) / max(1, config.LIBRARY_FRESH_DAYS))

    @staticmethod
    def _stale(e: dict, ctx: dict) -> bool:
        """A current story never takes a clip dated to another year (another flood, another fire)."""
        if not (ctx.get("current") and ctx.get("year")):
            return False
        years = {int(y) for y in _YEAR.findall(f"{e.get('time_context') or ''} "
                                                f"{(e.get('analysis') or {}).get('recordedAt') or ''}")}
        return bool(years) and ctx["year"] not in years

    def find(self, subject: str, exclude: Optional[set] = None, n: int = 1,
             min_score: Optional[float] = None, kind: str = "video",
             story: Optional[dict] = None) -> List[dict]:
        """
        Best items of a subject not already used: the subject's own first,
        then those that also show the story's place and event, then (for a
        story about now) the freshest, then by relevance and quality.
        """
        key = _key(subject)
        if not key:
            return []
        floor = config.CLIP_LIBRARY_MIN_SCORE if min_score is None else min_score
        used = set(exclude or ())
        ctx = self._context(story)

        def matches(e: dict) -> bool:
            if e.get("subject_key") == key:
                return True
            # A row saved under another line's subject still shows the place
            # or thing this line names.
            names = {_key(x) for x in (e.get("entities") or []) + (e.get("locations") or [])}
            return key in names

        hits = [e for e in self.entries
                if e.get("kind", "video") == kind and e.get("saved", True) and not shown(e)
                and matches(e) and e.get("id") not in used
                and float(e.get("relevance") or 0) >= floor and not self._stale(e, ctx)
                # Never a clip an earlier video showed (src/ledger.py).
                and not ledger.library_used(e)]
        hits.sort(key=lambda e: (e.get("subject_key") != key, -self._hits(e, ctx, subject), -self._fresh(e, ctx),
                                 -float(e.get("relevance") or 0), -float(e.get("quality") or 0)))
        return hits[:n]

    def search(self, text: str, n: int = 5, kind: str = "video", timeout: float = 10.0) -> List[tuple]:
        """
        [(cosine, entry)] of the kept items whose CLIP embedding (the R2
        sidecar) is closest to `text` - a semantic search across subjects.
        [] without the local model.
        """
        try:
            from . import localvision
            if not text or not localvision.available():
                return []
            import numpy as np
        except Exception:  # noqa: BLE001
            return []
        cands = [e for e in self.entries if e.get("saved", True) and e.get("kind", "video") == kind
                 and not shown(e) and (e.get("analysis") or {}).get("embeddingKey")]
        todo = [e for e in cands if e["id"] not in self._emb]

        def get(e: dict):
            url = libstore.url_for(e.get("bucket") or "", e["analysis"]["embeddingKey"])
            if not url:
                return e["id"], None
            try:
                r = requests.get(url, timeout=15)
                return e["id"], (r.json().get("embedding") if r.status_code == 200 else None)
            except (requests.RequestException, ValueError):
                return e["id"], None
        if todo:
            pool = ThreadPoolExecutor(max_workers=8)
            futs = [pool.submit(get, e) for e in todo]
            done, _late = wait(futs, timeout=timeout)
            pool.shutdown(wait=False, cancel_futures=True)
            for f in done:
                ident, emb = f.result()
                if emb:
                    self._emb[ident] = emb
        have = [e for e in cands if e["id"] in self._emb]
        if not have:
            return []
        q = localvision.embed_texts([f"a photo of {text}", f"footage of {text}"]).mean(axis=0)
        q = q / max(float(np.linalg.norm(q)), 1e-8)
        scored = [(float(np.dot(q, np.asarray(self._emb[e["id"]], dtype=np.float32))), e) for e in have]
        scored.sort(key=lambda t: -t[0])
        return scored[:n]

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #

    @staticmethod
    def _legacy(entry: dict) -> bool:
        """An old row: its file is not in the R2 library yet."""
        return not libstore.is_r2_ref(entry.get("bucket") or "")

    def known_hashes(self, kind: str = "video", exclude: str = "") -> Dict[str, list]:
        """{asset id: hashes} of what the library keeps (the duplicate rule's reference)."""
        with self._lock:
            return {e["id"]: e.get("phash") or [] for e in self.entries
                    if e.get("saved", True) and e.get("kind", "video") == kind and e.get("phash")
                    and e["id"] != exclude}

    def fetch(self, entry: dict, work: str, seconds: float, job: dict) -> Optional[media.MediaAsset]:
        """A library item as a local asset for one line (None if it cannot be read or is bad)."""
        kind = entry.get("kind") or "video"
        path = os.path.join(work, f"lib_{_safe_id(entry['id'])}{'.jpg' if kind == 'image' else '.mp4'}")
        try:
            url = entry.get("read_url") or storage.broker_read_url(
                entry.get("bucket") or self.bucket, entry["path"], self.project_id, self.job_id)
            storage.download(url, path)
        except Exception as e:  # noqa: BLE001 - fall back to searching
            print(f"[library] could not fetch {entry.get('id')}: {type(e).__name__}", flush=True)
            return None
        if kind == "video" and not media.playable_video(path):
            return None
        # AI slop and not-footage never come back out of the library either
        # (src/slop.py): rows kept before the filter existed are checked as
        # they are fetched and taken out of the library, reversibly.
        from . import slop
        why = "" if _user_kept(entry) else (slop.metadata_reason(entry.get("attribution"), entry.get("description"))
                                            or media.slop_reason(path, entry.get("attribution") or ""))
        if why:
            v = libstore.Verdict(kind=kind)
            v.bad(why)
            with self._lock:
                entry["saved"] = False
                self.pending[entry["id"]] = _removal_row(entry, v)
            print(f"[library] {entry['id']} removed from the library: {why}", flush=True)
            return None
        if self._legacy(entry) and libstore.enabled() and kind in _CHECKED_KINDS and not _user_kept(entry):
            # Not checked yet (the maintenance pass has not reached it): judged
            # now, before a bad old clip lands in another video.
            v = libstore.check(path, kind=kind, subject=entry.get("subject") or "", event=entry.get("event") or "",
                               known=self.known_hashes(kind, exclude=entry["id"]))
            if not v.ok:
                with self._lock:
                    entry["saved"] = False
                    self.pending[entry["id"]] = _removal_row(entry, v)
                print(f"[library] {entry['id']} removed from the library: {'; '.join(v.reasons)}", flush=True)
                return None
        with self._lock:
            self.used.add(entry["id"])
        return media.MediaAsset(
            kind=kind, source=entry.get("source") or "youtube", url=entry.get("url") or "",
            local_path=path, duration=float(entry.get("seconds") or seconds),
            attribution=entry.get("attribution") or "", license=entry.get("license") or "",
            query=entry.get("subject") or "", intent=job.get("intent") or entry.get("subject") or "",
            review_required=bool(entry.get("review_required", True)),
            review_reason=entry.get("review_reason") or "",
            content_description=entry.get("description") or "",
            relevance_score=entry.get("relevance"), quality=entry.get("quality"),
            moment_key=entry["id"])

    # ------------------------------------------------------------------ #
    # Keeping this job's good clips and photos
    # ------------------------------------------------------------------ #

    def record_from_doc(self, doc: dict) -> int:
        """
        Keep this job's good clips (and, on R2, photos). With the cross-video
        ledger on (saves_unused) and the library on R2: the approved moments
        the video did NOT show - the judge's runner-ups and the subject pools'
        spare moments (_unused_picks) - since the shown ones are kept out of
        later videos anyway. Otherwise the shown clips: local scenes scored >=
        the floor that the library does not have yet. On R2 each passes the
        quality gate and the duplicate rule first. Uploads the files first; an
        entry is only written for one that made it to storage.
        """
        if not self.enabled:
            return 0
        from .assetserver import is_local
        from . import upscale
        on_r2 = libstore.enabled()
        have = {e.get("id") for e in self.entries}
        if on_r2 and saves_unused():
            picks = self._unused_picks(doc, have)
            _strip_local_alternatives(doc)
            return self._keep(doc, picks, on_r2)
        picks = []
        for s in doc.get("scenes", []):
            if len(picks) >= config.CLIP_LIBRARY_MAX_PER_JOB:
                break
            m, sem = s.get("media") or {}, s.get("semanticMetadata") or {}
            ident = sem.get("assetId") or ""
            url = m.get("url") or ""
            kind = m.get("type") or ""
            source = m.get("source") or ""
            if not ident or ident in have or not is_local(url) or not os.path.isfile(url):
                continue
            if kind == "video":
                # The old app-storage path keeps YouTube clips only, as before.
                if source in _NEVER_SOURCES or (not on_r2 and source != "youtube"):
                    continue
            elif kind == "image":
                if not (on_r2 and config.LIBRARY_IMAGES) or source in _NEVER_SOURCES or m.get("generated"):
                    continue
            else:
                continue
            if float(sem.get("relevanceScore") or 0) < config.CLIP_LIBRARY_MIN_SCORE:
                continue
            reason = s.get("reviewReason", "") or ""
            if reason.startswith("The downloaded clip was empty") or reason.startswith("Reused shot"):
                continue
            if kind == "video" and upscale.is_framed(url):
                # A vertical clip framed on its blurred copy for this style: as
                # a 1920x1080 library clip it would pass every later check and
                # show up pillarboxed in videos that never allow vertical.
                continue
            picks.append((s, m, sem, ident, url, kind))
            have.add(ident)
        return self._keep(doc, picks, on_r2)

    def _unused_picks(self, doc: dict, have: set) -> list:
        """
        The job's approved moments the video does not show, as picks: each
        scene's runner-ups the judge passed (their files kept for this) and up
        to LIBRARY_SPARES_MAX of the subject pools' spare moments (downloaded
        when their turn comes). Never a moment within CROSS_VIDEO_GAP_SECONDS
        of one this video or an earlier one shows.
        """
        fps = max(1, int(doc.get("fps") or 30))
        shown = ledger.Ledger(days=0)
        for item in ledger.items_from_doc(doc):
            shown.add(item)
        gap = max(1.0, float(config.POOL_MIN_GAP_SECONDS))

        def free(vid: str, start: float, secs: float) -> bool:
            return not shown.moment_used(vid, start, start + secs) and not ledger.moment_used(vid, start,
                                                                                              start + secs)

        picks: list = []
        cap = config.CLIP_LIBRARY_MAX_PER_JOB
        for s in doc.get("scenes", []):
            sem = s.get("semanticMetadata") or {}
            for alt in sem.get("alternatives") or []:
                if len(picks) >= cap:
                    break
                path = alt.get("localPath") or ""
                if not path or not os.path.isfile(path) or (alt.get("source") or "youtube") in _NEVER_SOURCES:
                    continue
                if float(alt.get("score") or 0) < config.CLIP_LIBRARY_MIN_SCORE:
                    continue
                vid = ledger.youtube_id(alt.get("url"), alt.get("assetId"))
                start = (alt.get("moment") or {}).get("start")
                if start is None:
                    start = ledger.url_start(alt.get("url") or "")
                secs = max(2.0, int(s.get("durationInFrames") or fps) / fps)
                if vid and start is not None:
                    if not free(vid, float(start), secs):
                        continue
                    ident = f"yt:{vid}@{int(float(start) // gap)}"
                else:
                    ident = str(alt.get("assetId") or "")
                if not ident or ident in have:
                    continue
                have.add(ident)
                m = {"type": "video", "source": alt.get("source") or "youtube",
                     "attribution": alt.get("title") or "", "license": "unverified — you must hold the rights"}
                asem = {"assetId": ident, "subject": sem.get("subject") or "",
                        "contentDescription": alt.get("description") or "", "relevanceScore": alt.get("score"),
                        "qualityScore": alt.get("quality"), "sceneIntent": sem.get("sceneIntent"),
                        "sourceUrl": alt.get("url") or "", "eventWindow": sem.get("eventWindow") or ""}
                picks.append(({"durationInFrames": s.get("durationInFrames"), "reviewRequired": True,
                               "reviewReason": "Licence unverified — confirm you hold the rights"},
                              m, asem, ident, path, "video"))
        try:
            from . import pools
            spares = pools.spare_moments()
        except Exception:  # noqa: BLE001
            spares = []
        taken = 0
        work = media._WORK.get("dir") or tempfile.gettempdir()
        for sp in spares:
            if len(picks) >= cap or taken >= max(0, int(config.LIBRARY_SPARES_MAX)):
                break
            cand, mo, meta = sp["cand"], sp["moment"], sp.get("meta") or {}
            vid = str(cand.get("id") or "")
            if not re.fullmatch(r"[\w-]{11}", vid) or float(mo.get("score") or 0) < config.CLIP_LIBRARY_MIN_SCORE:
                continue
            start = float(mo.get("start") or 0.0)
            secs = float(meta.get("seconds") or 6.5)
            ident = f"yt:{vid}@{int(start // gap)}"
            if ident in have or not free(vid, start, secs):
                continue
            have.add(ident)
            taken += 1
            title = cand.get("title") or ""

            def fetch(vid=vid, start=start, secs=secs, title=title) -> str:
                path = media.fetch_clean_clip(vid, work, start, secs, title)[0]
                return path if path and not media.slop_reason(path, title) else ""

            m = {"type": "video", "source": "youtube", "attribution": f"YouTube: {title}"[:200],
                 "license": "unverified — you must hold the rights"}
            asem = {"assetId": ident, "subject": sp.get("name") or "",
                    "contentDescription": mo.get("description") or "", "relevanceScore": mo.get("score"),
                    "qualityScore": None, "sceneIntent": meta.get("scene_intent"),
                    "sourceUrl": f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                    "eventWindow": meta.get("event_window") or ""}
            picks.append(({"durationInFrames": int(secs * fps), "reviewRequired": True,
                           "reviewReason": "Licence unverified — confirm you hold the rights"},
                          m, asem, ident, fetch, "video"))
        print(f"[library] keeping the job's unused approved moments: {len(picks) - taken} runner-up(s), "
              f"{taken} spare pool moment(s)", flush=True)
        return picks

    def _keep(self, doc: dict, picks: list, on_r2: bool) -> int:
        """Check, upload and catalogue the picks: (scene, media, semantic, id, local path or a fetch, kind)."""
        added = 0
        known = {"video": self.known_hashes("video"), "image": self.known_hashes("image")}
        rejected: Dict[str, int] = {}

        def keep_r2(item):
            s, m, sem, ident, url, kind = item
            if callable(url):
                url = url()                             # a spare moment, downloaded now
                if not url:
                    return None
            intent = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else {}
            v = libstore.check(url, kind=kind, subject=sem.get("subject") or "",
                               event=intent.get("event_type") or "")
            with self._lock:
                dup = libstore.duplicate_of(v.hashes, known[kind]) if v.ok else ""
                if dup:
                    v.bad(f"duplicate of {dup}")
                if not v.ok:
                    for r in v.reasons:
                        label = r.split(" (")[0].split(" of ")[0]
                        rejected[label] = rejected.get(label, 0) + 1
                    return None
                known[kind][ident] = v.hashes          # claimed before the upload: no twin slips in
            meta = {"subject": sem.get("subject") or "", "description": (sem.get("contentDescription") or "")[:300],
                    "entities": intent.get("entities") or [], "locations": intent.get("locations") or [],
                    "event": intent.get("event_type") or "", "sourceUrl": sem.get("sourceUrl") or ""}
            return v, libstore.store(url, ident, kind, v, meta)

        def keep_supabase(item):
            _s, _m, _sem, ident, url, _kind = item
            obj = f"library/clips/{_safe_id(ident)}.mp4"
            storage.broker_upload(url, self.bucket, obj, self.project_id, self.job_id, read_ttl=60)
            return None, {"storage_bucket": self.bucket, "storage_path": obj}

        # Checks and uploads run eight at a time under one time box: a real
        # job sat here for many minutes uploading clips one by one before it
        # could show its storyboard. What does not make it in time is skipped.
        uploaded = {}
        if picks:
            if on_r2:
                libstore.warm()
            pool = ThreadPoolExecutor(max_workers=8)
            futs = {pool.submit(keep_r2 if on_r2 else keep_supabase, it): it for it in picks}
            done, _late = wait(futs, timeout=config.LIBRARY_SAVE_SECONDS)
            pool.shutdown(wait=False, cancel_futures=True)
            for f in done:
                it = futs[f]
                try:
                    got = f.result()
                    if got:
                        uploaded[it[3]] = got
                except Exception as e:  # noqa: BLE001 - keep the video going
                    print(f"[library] upload failed for {it[3]}: {type(e).__name__}: {str(e)[:100]}", flush=True)
            if _late:
                print(f"[library] {len(_late)} item(s) not saved in {config.LIBRARY_SAVE_SECONDS:.0f}s; skipped",
                      flush=True)
        self.rejected = rejected
        if rejected:
            print(f"[library] not kept (quality gate): {rejected}", flush=True)
        for s, m, sem, ident, url, kind in picks:
            got = uploaded.get(ident)
            if not got:
                continue
            v, fields = got
            intent = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else {}
            extra = dict(fields.get("analysis") or {})
            extra["savedAt"] = libstore.now_iso()
            recorded = sem.get("uploadDate") or m.get("uploadDate") or ""
            if recorded:
                extra["recordedAt"] = str(recorded)[:10]
            entry = {
                "id": ident, "path": fields["storage_path"], "bucket": fields["storage_bucket"], "kind": kind,
                "source": m.get("source") or "youtube",
                "subject": sem.get("subject") or "",
                "subject_key": _key(sem.get("subject") or ""),
                "entities": [e for e in (intent.get("entities") or []) if isinstance(e, str)][:12],
                "locations": [l for l in (intent.get("locations") or []) if isinstance(l, str)][:12],
                "event": (intent.get("event_type") or "")[:80],
                "time_context": (intent.get("time_context") or sem.get("eventWindow") or "")[:80],
                "description": (sem.get("contentDescription") or "")[:300],
                "relevance": sem.get("relevanceScore"), "quality": sem.get("qualityScore"),
                "seconds": (round(v.seconds, 2) if v is not None and kind == "video" and v.seconds
                            else round((s.get("durationInFrames") or 0) / max(1, doc.get("fps", 30)), 2)),
                "url": sem.get("sourceUrl") or "", "attribution": (m.get("attribution") or "")[:200],
                "license": m.get("license") or "", "review_required": bool(s.get("reviewRequired")),
                "review_reason": (s.get("reviewReason") or "")[:120],
                "created": int(time.time()), "project": self.project_id, "_new": True,
            }
            if v is not None:
                entry.update({"width": v.width or None, "height": v.height or None,
                              "thumb": fields.get("thumbnail_path") or "", "phash": v.hashes,
                              "read_url": extra.get("publicUrl") or "", "extra": extra, "analysis": extra})
            self.entries.append(entry)
            added += 1
        self.added = added
        return added

    def save(self) -> bool:
        if not self.enabled or not (self.added or self.used or self.pending):
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
        """New rows, a usage mark for every library clip this job used, and removals found while fetching."""
        rows = [_to_row(e) for e in self.entries if e.get("_new")]
        new_ids = {r["asset_id"] for r in rows}
        rows += [{"asset_id": i, "used": True} for i in sorted(self.used) if i not in new_ids]
        for r in rows:
            if r["asset_id"] in self.used:
                r["used"] = True
        with self._lock:
            rows += [p for i, p in sorted(self.pending.items()) if i not in new_ids]
        if not rows:
            return False
        try:
            body = storage.broker_library_upsert(self.project_id, self.job_id, rows)
            print(f"[library] saved to the library table: {self.added} new, {len(self.used)} used, "
                  f"{len(self.pending)} removed ({body.get('upserted', len(rows))} rows)", flush=True)
            with self._lock:
                self.pending.clear()
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[library] table save failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return False

    # ------------------------------------------------------------------ #
    # Maintenance: old rows to R2, bad ones out
    # ------------------------------------------------------------------ #

    def maintain(self, seconds: Optional[float] = None, max_items: Optional[int] = None,
                 dry_run: bool = False, stop: Optional[threading.Event] = None,
                 parallel: int = 3, write_every: int = 5) -> dict:
        """
        Check old rows (files not in the R2 library yet), most used first:
        a good one is copied to R2 and its row repointed (storage_bucket
        "r2:<bucket>", storage_path, thumbnail, size, hashes, embedding
        sidecar); a bad one is marked saved=false with analysis.removedReason.
        Idempotent - rows already on R2 or already removed are skipped - and
        bounded by `seconds` and `max_items`. `dry_run` judges without
        writing anything. Returns the counts.
        """
        seconds = config.LIBRARY_MAINTENANCE_SECONDS if seconds is None else seconds
        max_items = config.LIBRARY_MAINTENANCE_MAX if max_items is None else max_items
        stats = {"legacy": 0, "checked": 0, "moved": 0, "removed": 0, "failed": 0, "left": 0,
                 "reasons": {}, "dry_run": bool(dry_run), "seconds": 0.0, "verdicts": []}
        t0 = time.time()
        if not (self.loaded and self.db and not self.unreadable):
            stats["note"] = "library table not loaded"
            return stats
        if not dry_run and not libstore.enabled():
            stats["note"] = "R2 library bucket not configured"
            return stats
        if not libstore.tools():
            stats["note"] = "ffmpeg/ffprobe/numpy missing"
            return stats
        todo = [e for e in self.entries if e.get("saved", True) and self._legacy(e)
                and (e.get("kind") or "video") in _CHECKED_KINDS and (e.get("read_url") or e.get("path"))]
        todo.sort(key=lambda e: (-int(e.get("usage_count") or 0), -float(e.get("relevance") or 0),
                                 -float(e.get("quality") or 0)))
        stats["legacy"] = len(todo)
        todo = todo[:max(0, max_items)]
        if todo:
            libstore.warm()
        deadline = t0 + max(0.0, seconds)
        work = tempfile.mkdtemp(prefix="libmaint_")
        known = {"video": self.known_hashes("video"), "image": self.known_hashes("image")}
        rows: List[dict] = []
        lock = threading.Lock()

        def flush(force: bool = False) -> None:
            with lock:
                if not rows or dry_run or (len(rows) < write_every and not force):
                    return
                batch = list(rows)
                rows.clear()
            try:
                storage.broker_library_upsert(self.project_id, self.job_id, batch)
            except Exception as e:  # noqa: BLE001 - the next pass does them again (idempotent)
                print(f"[library] maintenance save failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
                with lock:
                    stats["failed"] += len(batch)
                    stats["moved"] -= sum(1 for r in batch if r.get("storage_bucket"))
                    stats["removed"] -= sum(1 for r in batch if r.get("saved") is False)

        def one(e: dict) -> None:
            kind = e.get("kind") or "video"
            path = os.path.join(work, f"m_{_safe_id(e['id'])}{'.jpg' if kind == 'image' else '.mp4'}")
            try:
                url = e.get("read_url") or storage.broker_read_url(
                    e.get("bucket") or self.bucket, e["path"], self.project_id, self.job_id)
                storage.download(url, path, timeout=120)
                v = libstore.check(path, kind=kind, subject=e.get("subject") or "", event=e.get("event") or "")
                with lock:
                    dup = libstore.duplicate_of(v.hashes, known[kind]) if v.ok else ""
                    if dup:
                        v.bad(f"duplicate of {dup}")
                    if v.ok or _user_kept(e):
                        known[kind][e["id"]] = v.hashes
                verdict = {"id": e["id"], "subject": e.get("subject") or "", "ok": v.ok, "reasons": v.reasons,
                           **{k: val for k, val in v.summary().items() if k not in ("v", "at", "ok", "reasons")}}
                if not v.ok and _user_kept(e):
                    # Restored by the owner: moved like a good one, its check kept for reference.
                    verdict["keptByOwner"] = True
                    with lock:
                        stats["kept_by_owner"] = stats.get("kept_by_owner", 0) + 1
                if not v.ok and not _user_kept(e):
                    row = _removal_row(e, v)
                    if not dry_run:
                        with self._lock:
                            e["saved"] = False
                    with lock:
                        stats["removed"] += 1
                        for r in v.reasons:
                            label = r.split(" (")[0].split(" of ")[0]
                            stats["reasons"][label] = stats["reasons"].get(label, 0) + 1
                else:
                    row = None
                    if not dry_run:
                        fields = libstore.store(path, e["id"], kind, v, {
                            "subject": e.get("subject") or "", "description": e.get("description") or "",
                            "entities": e.get("entities") or [], "locations": e.get("locations") or [],
                            "event": e.get("event") or "", "sourceUrl": e.get("url") or ""})
                        analysis = {**(e.get("analysis") or {}), **fields["analysis"],
                                    "migratedFrom": {"bucket": e.get("bucket") or "", "path": e.get("path") or ""},
                                    "migratedAt": libstore.now_iso()}
                        row = {"asset_id": e["id"], "storage_bucket": fields["storage_bucket"],
                               "storage_path": fields["storage_path"], "width": v.width or None,
                               "height": v.height or None, "analysis": analysis}
                        if fields.get("thumbnail_path"):
                            row["thumbnail_path"] = fields["thumbnail_path"]
                        if v.seconds:
                            row["seconds"] = round(v.seconds, 2)
                        with self._lock:
                            e.update({"bucket": fields["storage_bucket"], "path": fields["storage_path"],
                                      "read_url": analysis.get("publicUrl") or e.get("read_url") or "",
                                      "thumb": fields.get("thumbnail_path") or "",
                                      "thumb_url": analysis.get("thumbUrl") or "",
                                      "analysis": analysis, "phash": v.hashes,
                                      "width": v.width, "height": v.height})
                    with lock:
                        stats["moved"] += 1
                with lock:
                    stats["checked"] += 1
                    stats["verdicts"].append(verdict)
                    if row:
                        rows.append(row)
                flush()
            except Exception as ex:  # noqa: BLE001 - one bad row never stops the pass
                with lock:
                    stats["failed"] += 1
                print(f"[library] maintenance: {e.get('id')}: {type(ex).__name__}: {str(ex)[:120]}", flush=True)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

        pool = ThreadPoolExecutor(max_workers=max(1, parallel), thread_name_prefix="library-check")
        running: set = set()
        queue = list(todo)
        try:
            while queue or running:
                while queue and len(running) < max(1, parallel) and time.time() < deadline \
                        and not (stop is not None and stop.is_set()):
                    running.add(pool.submit(one, queue.pop(0)))
                if not running:
                    break
                done, running = wait(running, timeout=max(0.5, min(5.0, deadline - time.time() + 30)),
                                     return_when=FIRST_COMPLETED)
                if time.time() > deadline + 120:
                    break                   # a stuck download never holds the job
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            flush(force=True)
            shutil.rmtree(work, ignore_errors=True)
        stats["left"] = max(0, stats["legacy"] - stats["checked"] - stats["failed"])
        stats["seconds"] = round(time.time() - t0, 1)
        print(f"[library] maintenance{' (dry run)' if dry_run else ''}: {stats['checked']} checked of "
              f"{stats['legacy']} old item(s) - {stats['moved']} {'good' if dry_run else 'moved to R2'}, "
              f"{stats['removed']} removed {stats['reasons'] or ''}, {stats['failed']} failed, "
              f"{stats['left']} left, {stats['seconds']}s", flush=True)
        return stats


# --------------------------------------------------------------------------- #
# The per-job maintenance pass
# --------------------------------------------------------------------------- #

_MAINT: Dict[str, object] = {"thread": None, "stop": None, "result": None, "lib": None}


def start_maintenance(project_id: str, job_id: str, bucket: str = "") -> bool:
    """
    Start the old-rows pass in the background (plan/build jobs): it runs while
    the narration is transcribed and the story planned, and Library.load
    waits (briefly) for it before the footage search. True when started.
    """
    if not (config.LIBRARY_MAINTENANCE and config.CLIP_LIBRARY and libstore.enabled()):
        return False
    t = _MAINT.get("thread")
    if t is not None and t.is_alive():           # a pass from an earlier job is still finishing
        return False
    lib = Library(project_id, job_id, bucket)
    if not lib.enabled:
        return False
    stop = threading.Event()

    def run() -> None:
        try:
            if lib._load_db() and lib.db and not lib.unreadable:
                lib._load_legacy()
                _MAINT["result"] = lib.maintain(stop=stop)
        except Exception as e:  # noqa: BLE001 - never fails a job
            print(f"[library] maintenance skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)

    thread = threading.Thread(target=run, name="library-maintenance", daemon=True)
    _MAINT.update(thread=thread, stop=stop, result=None, lib=lib)
    thread.start()
    return True


def wait_maintenance(grace: float = 15.0) -> Optional[dict]:
    """Ask a running pass to take no more rows and give it `grace` seconds to finish."""
    t = _MAINT.get("thread")
    if t is None:
        return None
    if t.is_alive():
        _MAINT["stop"].set()
        t.join(grace)
    return _MAINT.get("result")
