"""
Media sourcing for a scene.

Order matters. Stock and public-domain sources are tried before YouTube because
footage lifted from other creators' uploads can attract Content ID claims on a
monetised channel. Set prefer="youtube" to flip that.

Every asset carries its `source` and `attribution` so the UI can show where each
clip came from and you can see your exposure per video.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
import os
import subprocess
import threading
import requests

from . import config
from .storage import download

USER_AGENT = "ThumbGenius/1.0 (video worker; contact: karnalamahesh810@gmail.com)"


@dataclass
class MediaAsset:
    kind: str                 # "video" | "image"
    source: str               # pexels | pixabay | wikimedia | openverse | youtube
    url: str                  # remote url
    local_path: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    attribution: str = ""
    license: str = ""
    query: str = ""

    def dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Stock video / image APIs
# --------------------------------------------------------------------------- #

def search_pexels(query: str, kind: str = "video", per_page: int = 5) -> List[MediaAsset]:
    if not config.PEXELS_API_KEY:
        return []
    base = "https://api.pexels.com/videos/search" if kind == "video" \
        else "https://api.pexels.com/v1/search"
    try:
        r = requests.get(
            base,
            headers={"Authorization": config.PEXELS_API_KEY},
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    out: List[MediaAsset] = []
    if kind == "video":
        for v in data.get("videos", []):
            files = sorted(
                [f for f in v.get("video_files", []) if f.get("width")],
                key=lambda f: abs(f.get("width", 0) - 1920),
            )
            if not files:
                continue
            f = files[0]
            out.append(MediaAsset(
                kind="video", source="pexels", url=f["link"],
                width=f.get("width", 0), height=f.get("height", 0),
                duration=float(v.get("duration", 0)),
                attribution=v.get("user", {}).get("name", ""),
                license="Pexels License", query=query,
            ))
    else:
        for p in data.get("photos", []):
            out.append(MediaAsset(
                kind="image", source="pexels", url=p["src"]["large2x"],
                width=p.get("width", 0), height=p.get("height", 0),
                attribution=p.get("photographer", ""),
                license="Pexels License", query=query,
            ))
    return out


def search_pixabay(query: str, kind: str = "video", per_page: int = 5) -> List[MediaAsset]:
    if not config.PIXABAY_API_KEY:
        return []
    base = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
    try:
        r = requests.get(base, params={
            "key": config.PIXABAY_API_KEY, "q": query,
            "per_page": max(3, per_page), "safesearch": "true",
        }, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    out: List[MediaAsset] = []
    for hit in data.get("hits", []):
        if kind == "video":
            v = (hit.get("videos") or {}).get("large") or (hit.get("videos") or {}).get("medium")
            if not v:
                continue
            out.append(MediaAsset(
                kind="video", source="pixabay", url=v["url"],
                width=v.get("width", 0), height=v.get("height", 0),
                duration=float(hit.get("duration", 0)),
                attribution=hit.get("user", ""), license="Pixabay License", query=query,
            ))
        else:
            out.append(MediaAsset(
                kind="image", source="pixabay", url=hit.get("largeImageURL", ""),
                width=hit.get("imageWidth", 0), height=hit.get("imageHeight", 0),
                attribution=hit.get("user", ""), license="Pixabay License", query=query,
            ))
    return [a for a in out if a.url]


def search_wikimedia(query: str, limit: int = 5) -> List[MediaAsset]:
    """
    Wikimedia Commons images. This is the source that actually has the *specific*
    real-world subjects a documentary needs (named highways, quakes, landmarks)
    which generic stock libraries do not carry.
    """
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            headers={"User-Agent": USER_AGENT},
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": limit,
                "gsrnamespace": 6, "prop": "imageinfo",
                "iiprop": "url|extmetadata", "iiurlwidth": 1920,
            },
            timeout=25,
        )
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except Exception:
        return []

    out: List[MediaAsset] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        out.append(MediaAsset(
            kind="image", source="wikimedia", url=url,
            width=info.get("thumbwidth", 0), height=info.get("thumbheight", 0),
            attribution=(meta.get("Artist", {}).get("value", "") or "")[:200],
            license=meta.get("LicenseShortName", {}).get("value", "") or "see Commons",
            query=query,
        ))
    return out


def search_openverse(query: str, limit: int = 5) -> List[MediaAsset]:
    """Openverse aggregates CC-licensed images across many providers. No key needed."""
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            headers={"User-Agent": USER_AGENT},
            params={"q": query, "page_size": limit, "license_type": "commercial"},
            timeout=25,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception:
        return []
    return [
        MediaAsset(
            kind="image", source="openverse", url=x.get("url", ""),
            width=x.get("width", 0) or 0, height=x.get("height", 0) or 0,
            attribution=x.get("creator", "") or "", license=x.get("license", "") or "",
            query=query,
        )
        for x in results if x.get("url")
    ]


# --------------------------------------------------------------------------- #
# YouTube via yt-dlp
# --------------------------------------------------------------------------- #

def youtube_clip(query_or_url: str, out_dir: str, seconds: float = 6.0,
                 start_at: float = 30.0) -> Optional[MediaAsset]:
    """
    Pull a short section of a YouTube video with yt-dlp.

    Uses --download-sections so we fetch only the slice we need instead of a
    whole 4K upload. `query_or_url` may be a URL or a plain search phrase.
    """
    os.makedirs(out_dir, exist_ok=True)
    target = query_or_url if query_or_url.startswith("http") else f"ytsearch1:{query_or_url}"
    out_tpl = os.path.join(out_dir, "yt_%(id)s.%(ext)s")
    section = f"*{start_at}-{start_at + seconds}"

    cmd = [
        "yt-dlp", target,
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]",
        "--no-playlist", "--no-warnings", "--quiet",
        "--merge-output-format", "mp4",
        "-o", out_tpl,
        "--print", "after_move:filepath",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None

    path = ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line and os.path.exists(line):
            path = line
            break
    if not path:
        cands = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("yt_")]
        if not cands:
            return None
        path = max(cands, key=os.path.getmtime)

    return MediaAsset(
        kind="video", source="youtube", url=query_or_url, local_path=path,
        duration=seconds, attribution="YouTube source",
        license="unverified - review before monetised use", query=query_or_url,
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

DEFAULT_ORDER = ["pexels", "pixabay", "wikimedia", "openverse", "youtube"]
YOUTUBE_FIRST = ["youtube", "pexels", "pixabay", "wikimedia", "openverse"]

# Downloaded-asset cache, keyed by query. A 17-minute script repeats subjects
# constantly ("the dam", "the highway"); without this we refetch the same clip
# dozens of times. Persists for the life of the worker process.
_CACHE: Dict[str, "MediaAsset"] = {}
_CACHE_LOCK = threading.Lock()


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _CACHE_LOCK:
        _CACHE.clear()


def source_many(
    jobs: List[Dict[str, Any]], work_dir: str, *,
    prefer: str = "stock", allow_youtube: bool = True,
    workers: int = 6, on_done=None,
) -> List[Optional["MediaAsset"]]:
    """
    Source visuals for many scenes concurrently.

    Sourcing is almost entirely network-bound, so a modest thread pool turns a
    300-scene job from serial minutes into something practical.

    Duplicate queries are collapsed BEFORE dispatch rather than checked inside
    each worker: submitting them concurrently would let identical queries race
    past a cache check and fetch the same asset several times over.

    Results come back in the original scene order regardless of completion order.
    `jobs` is a list of {"index": int, "query": str, "seconds": float}.
    """
    results: List[Optional[MediaAsset]] = [None] * len(jobs)

    # query -> the scene indices that want it, and the longest duration needed
    groups: Dict[str, Dict[str, Any]] = {}
    for j in jobs:
        key = j["query"]
        g = groups.setdefault(key, {"indices": [], "seconds": 0.0})
        g["indices"].append(j["index"])
        g["seconds"] = max(g["seconds"], float(j.get("seconds") or 0))

    done = 0
    lock = threading.Lock()

    def fetch(key: str, seconds: float) -> Optional[MediaAsset]:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit:
            return hit
        try:
            asset = source_for_segment(
                key, seconds, work_dir,
                prefer=prefer, allow_youtube=allow_youtube,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[media] '{key}' failed: {e}", flush=True)
            return None
        if asset:
            with _CACHE_LOCK:
                _CACHE[key] = asset
        return asset

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(fetch, key, g["seconds"]): key
            for key, g in groups.items()
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                asset = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[media] worker error on '{key}': {e}", flush=True)
                asset = None
            idxs = groups[key]["indices"]
            for i in idxs:
                results[i] = asset
            with lock:
                done += len(idxs)
                if on_done:
                    on_done(done, len(jobs))

    return results


def source_for_segment(query: str, seconds: float, work_dir: str,
                       prefer: str = "stock", allow_youtube: bool = True,
                       want: str = "auto") -> Optional[MediaAsset]:
    """
    Find and download one visual for a scene.

    want: "video" | "image" | "auto" (auto tries video first, falls back to image)
    """
    order = YOUTUBE_FIRST if prefer == "youtube" else DEFAULT_ORDER
    if not allow_youtube:
        order = [s for s in order if s != "youtube"]

    candidates: List[MediaAsset] = []
    for src in order:
        if src == "youtube":
            asset = youtube_clip(query, work_dir, seconds=seconds)
            if asset:
                return asset
            continue

        if want in ("auto", "video") and src in ("pexels", "pixabay"):
            fn = search_pexels if src == "pexels" else search_pixabay
            candidates = fn(query, kind="video")
            # A clip shorter than the scene would freeze on its last frame.
            candidates = [c for c in candidates if c.duration >= seconds * 0.8] or candidates

        if not candidates and want in ("auto", "image"):
            if src == "pexels":
                candidates = search_pexels(query, kind="image")
            elif src == "pixabay":
                candidates = search_pixabay(query, kind="image")
            elif src == "wikimedia":
                candidates = search_wikimedia(query)
            elif src == "openverse":
                candidates = search_openverse(query)

        if candidates:
            best = candidates[0]
            ext = ".mp4" if best.kind == "video" else ".jpg"
            safe = "".join(ch for ch in query if ch.isalnum())[:24] or "asset"
            dest = os.path.join(work_dir, f"{best.source}_{safe}_{abs(hash(best.url)) % 99999}{ext}")
            try:
                best.local_path = download(best.url, dest)
                return best
            except Exception:
                candidates = []
                continue

    return None
