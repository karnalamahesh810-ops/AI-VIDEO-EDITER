"""
The cross-video ledger: every moment and photo a finished video used, so the
next video never shows them again.

The owner (2026-09-30): "the same clip was literally used in the previous
video." Within one video the variety rules (media.variety_violations) keep a
source from repeating. Across videos nothing did: the clip library served
clips of past videos on purpose, and a new YouTube search could cut the same
moment of the same report again. The ledger is the memory of what is out
there already:

    YouTube        video id + [start, end] seconds of every moment shown
    other video    its page URL (+ its range when known: Dailymotion, web)
    photo          its URL + a 64-bit perceptual hash (dHash), so a resized or
                   re-hosted copy is still the same photo
    library        the asset id of every clip shown (library ids are asset ids)

Sourcing skips a moment of a video that overlaps a used one or comes within
CROSS_VIDEO_GAP_SECONDS of it - the other moments of a long report stay
usable - and any photo whose URL or hash matches, for CROSS_VIDEO_REUSE_DAYS
(0 = off). A project never blocks itself: planning or rendering one video
again reads the ledger without its own entries.

Storage: Cloudflare R2, the library bucket, read and written through the S3
API (no CDN copy in between):

    ledger/jobs/<job id>.json   one file per finished plan, build or render,
                                written once and never changed
    ledger/index.json           a compacted copy of many job files, rewritten
                                by a finishing job once LEDGER_COMPACT_EVERY or
                                more files are not in it; it lists the job
                                files it holds

A job starts reading when it starts (start_loading, in the background while
the narration is transcribed): the index, the listing of ledger/jobs/ and, in
parallel, every job file the index does not hold. Sourcing waits for it at
most LEDGER_LOAD_SECONDS after the job's start, then goes on with what was
read. Two jobs compacting at once lose nothing - the job files stay, and an
index that misses one only means that file is read on its own. A missing,
unreadable or slow ledger is an empty one: it never fails a video.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Dict, Iterable, List, Optional, Tuple

from . import config

VERSION = 1
_INF = float("inf")
_YT_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|\byt:)([\w-]{11})(?![\w-])")
_T_PARAM = re.compile(r"[?&#]t=(\d+(?:\.\d+)?)(?:s|$|&)|[?&#]t=(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)")
# Never recorded: pictures and loops made for this video, and empty scenes.
_NEVER = {"", "none", "generated", "noaa_goes", "upload", "animation", "color", "template"}
_JOB_KEY = re.compile(r"([^/]+)\.json$")


# --------------------------------------------------------------------------- #
# Keys and small helpers
# --------------------------------------------------------------------------- #

def window_days() -> int:
    return max(0, int(getattr(config, "CROSS_VIDEO_REUSE_DAYS", 0) or 0))


def on() -> bool:
    """The rule is on (sourcing checks what is loaded; tests load by hand)."""
    return window_days() > 0


def enabled() -> bool:
    """The rule is on and the shared ledger can be read and written (R2 library bucket)."""
    if not on():
        return False
    from . import r2
    return r2.library_enabled()


def _prefix() -> str:
    base = str(getattr(config, "LEDGER_PREFIX", "ledger/") or "ledger/")
    return f"{config.R2_LIBRARY_PREFIX}{base.rstrip('/')}/"


def job_key(job_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(job_id or "job"))[:80] or "job"
    return f"{_prefix()}jobs/{safe}.json"


def index_key() -> str:
    return f"{_prefix()}index.json"


def youtube_id(*texts) -> str:
    """The 11-character video id in a watch URL, a youtu.be link or an asset id ("yt:<id>@4")."""
    for t in texts:
        m = _YT_ID.search(str(t or ""))
        if m:
            return m.group(1)
    return ""


def url_start(url: str) -> Optional[float]:
    """The t= offset of a video URL, in seconds ("&t=95", "&t=1m35s"), or None."""
    m = _T_PARAM.search(str(url or ""))
    if not m:
        return None
    if m.group(1):
        return float(m.group(1))
    h, mi, s = (int(x) if x else 0 for x in m.group(2, 3, 4))
    return float(h * 3600 + mi * 60 + s)


def norm_url(url: str) -> str:
    """A URL as the ledger compares it: host without www./m., path, and the
    query only for a page without a file name (?v=, ?id=); a Wikimedia
    thumbnail's "960px-" size prefix goes."""
    u = str(url or "").strip()
    if not u:
        return ""
    try:
        p = urllib.parse.urlsplit(u if "://" in u else f"https://{u}")
    except ValueError:
        return u.lower()
    host = (p.netloc or "").lower()
    for pre in ("www.", "m.", "mobile."):
        if host.startswith(pre):
            host = host[len(pre):]
    path = re.sub(r"/\d+px-", "/", p.path or "").rstrip("/")
    query = ""
    if not os.path.splitext(path)[1] and p.query:
        keep = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() in ("v", "id", "video_id", "fbid")]
        query = urllib.parse.urlencode(sorted(keep))
    return f"{host}{path}" + (f"?{query}" if query else "")


def photo_hash(path: str) -> Optional[int]:
    """64-bit dHash of a picture file (9x8 grey), None when it cannot be read or is flat."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            grey = im.convert("L")
            if grey.getextrema()[1] - grey.getextrema()[0] < 12:
                return None                             # a flat picture's bits are noise
            small = grey.resize((9, 8), Image.BILINEAR)
            px = list(small.tobytes())                   # one byte per pixel in mode L
    except Exception:  # noqa: BLE001 - unreadable: no hash, the URL still counts
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col + 1] > px[row * 9 + col] else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #

class Ledger:
    """What earlier videos showed, as lookups: overlapping moments, photo URLs and hashes, asset ids."""

    def __init__(self, project_id: str = "", days: Optional[float] = None, gap: Optional[float] = None,
                 now: Optional[float] = None):
        self.project_id = str(project_id or "")
        self.days = window_days() if days is None else max(0.0, float(days))
        self.gap = float(config.CROSS_VIDEO_GAP_SECONDS if gap is None else gap)
        self.now = float(now or _now())
        self.lock = threading.Lock()
        self.yt: Dict[str, List[Tuple[float, float]]] = {}
        self.urls: Dict[str, List[Tuple[float, float]]] = {}
        self.photo_urls: set = set()
        self.photo_hashes: List[int] = []
        self.assets: set = set()
        self.jobs: set = set()
        self.items = 0
        self.skipped: Dict[str, int] = {"moment": 0, "url": 0, "photo": 0, "library": 0}

    # ------------------------------------------------------------ filling
    def _fresh(self, ts) -> bool:
        if not self.days:
            return True
        try:
            return float(ts) >= self.now - self.days * 86400.0
        except (TypeError, ValueError):
            return True                                   # an undated item counts

    def add_record(self, record: dict) -> int:
        """One job file: its items, unless it is this project's own or older than the window."""
        if not isinstance(record, dict):
            return 0
        job = str(record.get("job") or "")
        with self.lock:
            if job and job in self.jobs:
                return 0
            if job:
                self.jobs.add(job)
        if self.project_id and str(record.get("project") or "") == self.project_id:
            return 0
        ts = record.get("ts")
        if not self._fresh(ts):
            return 0
        n = 0
        for item in record.get("items") or []:
            if isinstance(item, dict) and self.add(item):
                n += 1
        return n

    def add_index(self, index: dict) -> int:
        """The compacted index: its items carry their own job, project and time."""
        if not isinstance(index, dict):
            return 0
        n = 0
        with self.lock:
            self.jobs.update(str(j) for j in (index.get("jobs") or []) if j)
        for item in index.get("items") or []:
            if not isinstance(item, dict):
                continue
            if self.project_id and str(item.get("p") or "") == self.project_id:
                continue
            if not self._fresh(item.get("ts")):
                continue
            if self.add(item):
                n += 1
        return n

    def add(self, item: dict) -> bool:
        kind = item.get("k")
        start = item.get("s")
        end = item.get("e")
        try:
            rng = (float(start), float(end) if end is not None else float(start)) if start is not None \
                else (0.0, _INF)
        except (TypeError, ValueError):
            rng = (0.0, _INF)
        with self.lock:
            if item.get("a"):
                self.assets.add(str(item["a"]))
            if kind == "yt" and item.get("id"):
                self.yt.setdefault(str(item["id"]), []).append(rng)
            elif kind == "url" and item.get("u"):
                self.urls.setdefault(str(item["u"]), []).append(rng)
            elif kind == "photo":
                if item.get("u"):
                    self.photo_urls.add(str(item["u"]))
                h = item.get("h")
                if h:
                    try:
                        self.photo_hashes.append(int(str(h), 16))
                    except ValueError:
                        pass
            elif kind != "lib":
                return False
            self.items += 1
        return True

    # ------------------------------------------------------------ asking
    def _overlaps(self, ranges: Iterable[Tuple[float, float]], start: Optional[float],
                  end: Optional[float]) -> bool:
        if start is None:
            return bool(list(ranges))                   # an unknown moment: any use of the video counts
        s = float(start)
        e = float(end) if end is not None else s
        gap = self.gap
        return any(s < hi + gap and e > lo - gap for lo, hi in ranges)

    def moment_used(self, video_id: str, start: Optional[float] = None, end: Optional[float] = None) -> bool:
        """A moment [start, end] of a YouTube video overlaps (or comes within the gap of) a used one."""
        if not video_id:
            return False
        with self.lock:
            ranges = list(self.yt.get(video_id) or ())
        return bool(ranges) and self._overlaps(ranges, start, end)

    def blocked(self, video_id: str) -> List[Tuple[float, float]]:
        """The used ranges of a YouTube video, widened by the gap (for choosing another moment)."""
        with self.lock:
            return [(max(0.0, lo - self.gap), hi + self.gap) for lo, hi in self.yt.get(video_id) or ()]

    def url_used(self, url: str, start: Optional[float] = None, end: Optional[float] = None) -> bool:
        """A non-YouTube video page (with a range when known) or a photo URL an earlier video showed."""
        key = norm_url(url)
        if not key:
            return False
        vid = youtube_id(url)
        if vid:
            return self.moment_used(vid, start, end)
        with self.lock:
            ranges = list(self.urls.get(key) or ())
            photo = key in self.photo_urls
        return photo or (bool(ranges) and self._overlaps(ranges, start, end))

    def photo_used(self, url: str = "", phash: Optional[int] = None) -> bool:
        key = norm_url(url)
        with self.lock:
            if key and key in self.photo_urls:
                return True
            hashes = list(self.photo_hashes)
        if phash is None:
            return False
        bits = int(getattr(config, "LEDGER_PHOTO_BITS", 6))
        return any(_hamming(phash, h) <= bits for h in hashes)

    def asset_used(self, asset_id: str) -> bool:
        with self.lock:
            return bool(asset_id) and str(asset_id) in self.assets

    def library_used(self, entry: dict) -> bool:
        """A library entry an earlier video showed: its id, or its YouTube moment."""
        if not isinstance(entry, dict):
            return False
        if self.asset_used(entry.get("id") or ""):
            return True
        vid = youtube_id(entry.get("url"), entry.get("id"))
        if not vid:
            return False
        start = url_start(entry.get("url") or "")
        if start is None:
            m = re.search(r"@(\d+)$", str(entry.get("id") or ""))
            if m:
                start = int(m.group(1)) * max(1.0, float(config.POOL_MIN_GAP_SECONDS))
        secs = float(entry.get("seconds") or 6.0)
        return self.moment_used(vid, start, None if start is None else start + secs)

    def summary(self) -> dict:
        with self.lock:
            return {"jobs": len(self.jobs), "items": self.items, "videos": len(self.yt), "pages": len(self.urls),
                    "photos": len(self.photo_urls), "hashes": len(self.photo_hashes),
                    "skipped": dict(self.skipped), "days": self.days, "gap": self.gap}


# --------------------------------------------------------------------------- #
# The job's ledger: loaded in the background, asked while sourcing
# --------------------------------------------------------------------------- #

_STATE: Dict[str, object] = {"ledger": Ledger(), "done": None, "deadline": 0.0, "job": "", "project": "",
                             "index_jobs": set(), "unindexed": 0, "pending": None, "loaded": False}
_STATE_LOCK = threading.Lock()


def _get_json(key: str, timeout: int = 20) -> Optional[dict]:
    from . import r2
    raw = r2.get_bytes(key, bucket=config.R2_LIBRARY_BUCKET, timeout=timeout)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print(f"[ledger] {key} is not readable JSON; skipped", flush=True)
        return None
    return data if isinstance(data, dict) else None


def _put_json(key: str, obj: dict, seconds: float = 30.0) -> None:
    from . import r2
    r2.upload_bytes(json.dumps(obj, separators=(",", ":")).encode("utf-8"), key,
                    content_type="application/json", deadline=time.time() + seconds,
                    bucket=config.R2_LIBRARY_BUCKET, base=config.R2_LIBRARY_PUBLIC_BASE,
                    cache_control="no-store")


def _load_into(led: Ledger, done: threading.Event, deadline: float) -> None:
    from . import r2
    t0 = time.time()
    index_jobs: set = set()
    try:
        index = None
        try:
            index = _get_json(index_key(), timeout=15)
        except Exception as e:  # noqa: BLE001 - the job files alone still work
            print(f"[ledger] index not read: {type(e).__name__}: {str(e)[:100]}", flush=True)
        if index:
            led.add_index(index)
            index_jobs = {str(j) for j in (index.get("jobs") or []) if j}
        keys = r2.list_keys(prefix=f"{_prefix()}jobs/", bucket=config.R2_LIBRARY_BUCKET, limit=20000)
        todo = []
        for row in keys:
            m = _JOB_KEY.search(row.get("key") or "")
            if m and m.group(1) not in index_jobs:
                todo.append(row["key"])
        with _STATE_LOCK:
            if _STATE.get("ledger") is led:
                _STATE["index_jobs"] = set(index_jobs)
                _STATE["unindexed"] = len(todo)
        if todo:
            pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ledger-read")
            futs = [pool.submit(_get_json, k, 15) for k in todo]
            finished, late = wait(futs, timeout=max(1.0, deadline - time.time() + 20.0))
            pool.shutdown(wait=False, cancel_futures=True)
            for f in finished:
                try:
                    led.add_record(f.result())
                except Exception:  # noqa: BLE001 - one bad file is skipped
                    pass
            if late:
                print(f"[ledger] {len(late)} job file(s) not read in time", flush=True)
        print(f"[ledger] {led.summary()['items']} item(s) from {len(led.jobs)} earlier job(s) "
              f"({len(index_jobs)} via the index, {len(todo)} file(s)) in {time.time() - t0:.1f}s", flush=True)
    except Exception as e:  # noqa: BLE001 - an unreadable ledger is an empty one
        print(f"[ledger] not read: {type(e).__name__}: {str(e)[:120]}", flush=True)
    finally:
        with _STATE_LOCK:
            if _STATE.get("ledger") is led:
                _STATE["loaded"] = True
        done.set()


def start_loading(job_id: str = "", project_id: str = "") -> bool:
    """
    A fresh ledger for this job, read in the background when the shared one
    is enabled (else it stays empty). Call at the job's start, after the
    job's config overrides. True when a read was started.
    """
    led = Ledger(project_id)
    done = threading.Event()
    with _STATE_LOCK:
        _STATE.update(ledger=led, done=done, deadline=time.time() + float(config.LEDGER_LOAD_SECONDS),
                      job=str(job_id or ""), project=str(project_id or ""), index_jobs=set(),
                      unindexed=0, pending=None, loaded=False)
    if not enabled():
        done.set()
        return False
    threading.Thread(target=_load_into, args=(led, done, float(_STATE["deadline"])),
                     name="ledger-load", daemon=True).start()
    return True


def current() -> Ledger:
    """The job's ledger, waiting for the background read until LEDGER_LOAD_SECONDS after the job's start."""
    done = _STATE.get("done")
    if isinstance(done, threading.Event) and not done.is_set():
        left = float(_STATE.get("deadline") or 0.0) - time.time()
        if left > 0:
            done.wait(left)
    return _STATE["ledger"]  # type: ignore[return-value]


def use(led: Ledger, job_id: str = "", project_id: str = "") -> None:
    """Set the job's ledger directly (tests, tools)."""
    done = threading.Event()
    done.set()
    with _STATE_LOCK:
        _STATE.update(ledger=led, done=done, deadline=0.0, job=job_id, project=project_id,
                      index_jobs=set(), unindexed=0, pending=None, loaded=True)


def _count(kind: str) -> None:
    led = _STATE["ledger"]
    with led.lock:  # type: ignore[union-attr]
        led.skipped[kind] = led.skipped.get(kind, 0) + 1  # type: ignore[union-attr]


# The checks sourcing makes: cheap after the read, False with the rule off.

def moment_used(video_id: str, start: Optional[float] = None, end: Optional[float] = None) -> bool:
    if not on() or not video_id:
        return False
    hit = current().moment_used(video_id, start, end)
    if hit:
        _count("moment")
    return hit


def url_used(url: str, start: Optional[float] = None, end: Optional[float] = None) -> bool:
    if not on() or not url:
        return False
    hit = current().url_used(url, start, end)
    if hit:
        _count("url")
    return hit


def photo_used(url: str = "", phash: Optional[int] = None) -> bool:
    if not on() or not (url or phash is not None):
        return False
    hit = current().photo_used(url, phash)
    if hit:
        _count("photo")
    return hit


def library_used(entry: dict) -> bool:
    if not on():
        return False
    hit = current().library_used(entry)
    if hit:
        _count("library")
    return hit


def blocked(video_id: str) -> List[Tuple[float, float]]:
    return current().blocked(video_id) if on() and video_id else []


def stats() -> dict:
    """What the job's ledger holds and what it turned down (for the job result)."""
    out = current().summary() if on() else {"items": 0}
    out["enabled"] = enabled()
    return out


# --------------------------------------------------------------------------- #
# Recording a finished video
# --------------------------------------------------------------------------- #

def _local(path: str) -> str:
    p = str(path or "")
    return p if p and not p.startswith(("http://", "https://")) and os.path.isfile(p) else ""


def items_from_doc(doc: dict) -> List[dict]:
    """
    What a timeline shows, as ledger items: a YouTube moment (id + range, or
    the whole video when the range is unknown), another video's page, a photo
    (URL + dHash of the local file when it is still here), and the asset id of
    every shot. Generated pictures, live satellite loops, uploads and empty or
    animation scenes are not recorded.
    """
    fps = max(1, int((doc or {}).get("fps") or 30))
    out: List[dict] = []
    seen: set = set()
    for s in (doc or {}).get("scenes") or []:
        if not isinstance(s, dict):
            continue
        m = s.get("media") if isinstance(s.get("media"), dict) else {}
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        kind = m.get("type") or ""
        source = str(m.get("source") or sem.get("provider") or "")
        if kind not in ("video", "image") or source in _NEVER or m.get("generated"):
            continue
        secs = max(0.5, int(s.get("durationInFrames") or fps) / fps)
        clip = m.get("clipSeconds")
        shown = min(secs, float(clip)) if isinstance(clip, (int, float)) and clip > 0 else secs
        # Where the shot came from (never the copy this job stored on R2).
        url = str(sem.get("sourceUrl") or "")
        aid = str(sem.get("assetId") or "")
        moment = sem.get("moment") if isinstance(sem.get("moment"), dict) else {}
        start = moment.get("start")
        if not isinstance(start, (int, float)) or isinstance(start, bool):
            start = url_start(url)
        item: dict
        if kind == "video":
            vid = youtube_id(url, aid)
            if vid:
                item = {"k": "yt", "id": vid}
            elif url:
                item = {"k": "url", "u": norm_url(url)}
            elif aid:
                item = {"k": "lib"}
            else:
                continue
            if start is not None and item["k"] != "lib":
                item.update(s=round(float(start), 1), e=round(float(start) + shown, 1))
        else:
            item = {"k": "photo", "u": norm_url(url)} if url else {"k": "photo"}
            local = _local(m.get("url") or "")
            h = photo_hash(local) if local else None
            if h is not None:
                item["h"] = f"{h:016x}"
            if not item.get("u") and not item.get("h"):
                continue
        if aid:
            item["a"] = aid[:160]
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def note(doc: dict) -> int:
    """Remember what this job's timeline shows (call while its files are still local: photo hashes)."""
    try:
        items = items_from_doc(doc)
    except Exception as e:  # noqa: BLE001 - the ledger never fails a video
        print(f"[ledger] could not read the timeline: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return 0
    meta = (doc or {}).get("meta") if isinstance((doc or {}).get("meta"), dict) else {}
    story = meta.get("story") if isinstance(meta.get("story"), dict) else {}
    with _STATE_LOCK:
        _STATE["pending"] = {"items": items, "style": str(meta.get("videoStyle") or ""),
                             "event": str(story.get("event") or "")[:120]}
    return len(items)


def save(job_id: str = "", project_id: str = "", doc: Optional[dict] = None) -> bool:
    """
    Write this job's file (ledger/jobs/<job id>.json) after the video is
    done, from note()'s record (or `doc` when note() was not called), then
    compact the index when enough files are outside it. Never raises.
    """
    if not enabled():
        return False
    try:
        pending = _STATE.get("pending")
        if doc is not None and not pending:
            note(doc)
            pending = _STATE.get("pending")
        if not isinstance(pending, dict) or not pending.get("items"):
            return False
        job = str(job_id or _STATE.get("job") or "")
        if not job:
            return False
        now = _now()
        record = {"v": VERSION, "job": job, "project": str(project_id or _STATE.get("project") or ""),
                  "ts": int(now), "at": datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "style": pending.get("style") or "", "event": pending.get("event") or "",
                  "items": pending["items"]}
        _put_json(job_key(job), record)
        print(f"[ledger] recorded {len(record['items'])} item(s) of this video ({job_key(job)})", flush=True)
        with _STATE_LOCK:
            _STATE["pending"] = None
        if int(_STATE.get("unindexed") or 0) + 1 >= max(1, int(config.LEDGER_COMPACT_EVERY)) \
                and _STATE.get("loaded"):
            compact(record)
        return True
    except Exception as e:  # noqa: BLE001 - never fails a finished video
        print(f"[ledger] not saved: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


def compact(extra: Optional[dict] = None) -> bool:
    """
    Rewrite ledger/index.json from everything readable now: the old index and
    every job file (this job's `extra` record included), items kept for
    max(365, 2 x the window) days. Job files are never deleted.
    """
    from . import r2
    try:
        keep_days = max(365, 2 * window_days())
        horizon = _now() - keep_days * 86400.0
        index = _get_json(index_key(), timeout=20) or {}
        jobs = {str(j) for j in (index.get("jobs") or []) if j}
        items = [it for it in (index.get("items") or [])
                 if isinstance(it, dict) and float(it.get("ts") or 0) >= horizon]
        records = []
        for row in r2.list_keys(prefix=f"{_prefix()}jobs/", bucket=config.R2_LIBRARY_BUCKET, limit=20000):
            m = _JOB_KEY.search(row.get("key") or "")
            if not m or m.group(1) in jobs:
                continue
            if extra and m.group(1) == re.sub(r"[^A-Za-z0-9_-]+", "_", str(extra.get("job") or "")):
                continue
            rec = _get_json(row["key"], timeout=15)
            if rec:
                records.append((m.group(1), rec))
        if extra:
            records.append((re.sub(r"[^A-Za-z0-9_-]+", "_", str(extra.get("job") or "")), extra))
        for name, rec in records:
            jobs.add(name)
            ts = rec.get("ts") or 0
            if float(ts or 0) < horizon:
                continue
            for it in rec.get("items") or []:
                if isinstance(it, dict):
                    items.append(dict(it, ts=ts, p=str(rec.get("project") or ""), j=name))
        _put_json(index_key(), {"v": VERSION, "updated": int(_now()), "jobs": sorted(jobs), "items": items},
                  seconds=60.0)
        print(f"[ledger] index rewritten: {len(items)} item(s) from {len(jobs)} job(s)", flush=True)
        with _STATE_LOCK:
            _STATE["unindexed"] = 0
        return True
    except Exception as e:  # noqa: BLE001 - the job files still hold everything
        print(f"[ledger] index not rewritten: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False
