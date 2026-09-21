"""
Media sourcing for a scene.

This workflow is NO-STOCK. Generic stock libraries are full of a model in a
hard hat pointing at a tablet; documentary narration asks for "the Million
Dollar Highway" and "the 7.4 quake at San Jose del Palmar". So:

    footage  ->  YouTube via yt-dlp, Creative Commons only
    images   ->  Wikimedia Commons / Openverse (real photos of the real
                 subject), then a generated image as the last resort

Ordering images real-first is not only a licensing preference. A generated
photoreal image of an actual news event is a fabricated depiction of something
that really happened; where a real photograph of the subject exists it is both
more accurate and safer to use it. Generated frames are always tagged
`source="generated"` and carry review_required, so the editor can show which
shots are illustrations rather than records.

Every asset carries its `source`, `license` and `attribution` so the UI can
show where each clip came from and you can see your exposure per video.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
import base64
import os
import re
import subprocess
import threading
import requests

from . import config
from .storage import download


@dataclass
class MediaAsset:
    kind: str                 # "video" | "image"
    source: str               # youtube | wikimedia | openverse | generated | pexels | pixabay
    url: str                  # remote url (or the query, for yt-dlp searches)
    local_path: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    attribution: str = ""
    license: str = ""
    query: str = ""
    review_required: bool = False
    review_reason: str = ""

    def dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_scene_media(self) -> Dict[str, Any]:
        """
        The exact shape Remotion's `SceneMedia` expects.

        Kept here so one place knows the renderer contract: note `kind` ->
        `type`, and that a downloaded local path always wins over the remote
        URL, because headless Chrome should read from disk rather than refetch.
        """
        return {
            "type": self.kind,
            "url": self.local_path or self.url,
            "source": self.source,
            "attribution": self.attribution,
            "license": self.license,
        }


# --------------------------------------------------------------------------- #
# Real imagery: Wikimedia Commons + Openverse
# --------------------------------------------------------------------------- #

def search_wikimedia(query: str, limit: int = 5) -> List[MediaAsset]:
    """
    Wikimedia Commons images — the source that actually has the *specific*
    real-world subjects a documentary needs (named highways, quakes, landmarks)
    which generic stock libraries do not carry.
    """
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            headers={"User-Agent": config.USER_AGENT},
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
        # Commons returns the artist as an HTML fragment with a profile link.
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "") or "")
        out.append(MediaAsset(
            kind="image", source="wikimedia", url=url,
            width=info.get("thumbwidth", 0), height=info.get("thumbheight", 0),
            attribution=artist.strip()[:200],
            license=meta.get("LicenseShortName", {}).get("value", "") or "see Commons",
            query=query,
        ))
    return out


def search_openverse(query: str, limit: int = 5) -> List[MediaAsset]:
    """Openverse aggregates CC-licensed images across many providers. No key needed."""
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            headers={"User-Agent": config.USER_AGENT},
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
# Generated images
# --------------------------------------------------------------------------- #

def generate_image(prompt: str, out_dir: str, timeout: int = 180) -> Optional[MediaAsset]:
    """
    Render an illustration for a beat no real photograph covers.

    Speaks the OpenAI /images/generations shape, so it works against OpenAI
    directly or any compatible gateway — set IMAGE_API_BASE / IMAGE_API_KEY /
    IMAGE_MODEL. Returns None rather than raising when unconfigured, so the
    pipeline degrades to real imagery instead of failing the job.

    The result is tagged review_required: a generated frame is an illustration,
    not a record of the event, and the editor should be able to see which is
    which before publishing.
    """
    if not config.IMAGE_API_KEY:
        return None
    os.makedirs(out_dir, exist_ok=True)
    full_prompt = f"{prompt}. {config.IMAGE_STYLE_SUFFIX}"[:3800]
    try:
        r = requests.post(
            f"{config.IMAGE_API_BASE}/images/generations",
            headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.IMAGE_MODEL, "prompt": full_prompt,
                  "n": 1, "size": config.IMAGE_SIZE},
            timeout=timeout,
        )
        r.raise_for_status()
        item = (r.json().get("data") or [{}])[0]
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        print(f"[media] image generation failed for '{prompt[:60]}': {e}", flush=True)
        return None

    safe = "".join(ch for ch in prompt if ch.isalnum())[:24] or "gen"
    dest = os.path.join(out_dir, f"gen_{safe}_{abs(hash(prompt)) % 99999}.png")
    try:
        # gpt-image-1 returns base64; some gateways return a URL instead.
        if item.get("b64_json"):
            with open(dest, "wb") as f:
                f.write(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            download(item["url"], dest)
        else:
            return None
    except Exception as e:  # noqa: BLE001
        print(f"[media] could not save generated image: {e}", flush=True)
        return None

    return MediaAsset(
        kind="image", source="generated", url="", local_path=dest,
        attribution=f"AI-generated illustration ({config.IMAGE_MODEL})",
        license="generated - not a photograph of the real event",
        query=prompt, review_required=True,
        review_reason="Generated illustration, not documentary footage",
    )


# --------------------------------------------------------------------------- #
# YouTube via yt-dlp
# --------------------------------------------------------------------------- #

def youtube_clip(query_or_url: str, out_dir: str, seconds: float = 6.0,
                 start_at: float = 30.0, require_cc: bool = True) -> Optional[MediaAsset]:
    """
    Pull a short section of a YouTube video with yt-dlp.

    Uses --download-sections so we fetch only the slice we need instead of a
    whole 4K upload. `query_or_url` may be a URL or a plain search phrase.

    require_cc restricts this to uploads the creator published under Creative
    Commons Attribution, which is the only footage here you may legally re-cut
    and monetise. The default YouTube licence reserves every right, so anything
    else gets claimed by Content ID and is someone else's copyright besides.
    Turn it off only for footage you own or have separately licensed.
    """
    os.makedirs(out_dir, exist_ok=True)
    # Search several candidates: with the CC filter on most hits are skipped,
    # and ytsearch1 would give up after the first non-CC result.
    target = query_or_url if query_or_url.startswith("http") else f"ytsearch8:{query_or_url}"
    out_tpl = os.path.join(out_dir, "yt_%(id)s.%(ext)s")
    # Pad the requested slice: a keyframe-aligned cut can land short of the
    # scene length, and a clip shorter than its scene freezes on its last frame.
    grab = max(2.0, seconds + 1.5)
    section = f"*{start_at}-{start_at + grab}"

    cmd = [
        "yt-dlp", target,
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]",
        "--no-playlist", "--no-warnings", "--quiet",
        "--merge-output-format", "mp4",
        # Stop at the first hit that passes the licence filter.
        "--break-on-reject", "--max-downloads", "1",
        "-o", out_tpl,
        "--print", "after_move:filepath",
    ]
    if require_cc:
        # yt-dlp exposes YouTube's licence field; a match-filter keeps a search
        # rolling to the next hit instead of failing the whole scene.
        cmd += ["--match-filter", "license *= Creative Commons"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        print("[media] yt-dlp not on PATH - skipping the YouTube source", flush=True)
        return None

    # --max-downloads makes yt-dlp exit non-zero once it has what we asked for,
    # so the printed path decides success, not the return code.
    path = ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line and os.path.exists(line):
            path = line
            break
    if not path:
        return None

    return MediaAsset(
        kind="video", source="youtube", url=query_or_url, local_path=path,
        duration=grab,
        attribution="YouTube (CC BY) - credit the uploader",
        license=("Creative Commons Attribution (CC BY)" if require_cc
                 else "unverified - you must hold the rights"),
        query=query_or_url,
        review_required=not require_cc,
        review_reason="" if require_cc else "Licence unverified - confirm you hold the rights",
    )


# --------------------------------------------------------------------------- #
# Stock (escape hatch only — off unless ALLOW_STOCK is set)
# --------------------------------------------------------------------------- #

def search_pexels(query: str, kind: str = "video", per_page: int = 5) -> List[MediaAsset]:
    if not config.PEXELS_API_KEY:
        return []
    base = "https://api.pexels.com/videos/search" if kind == "video" \
        else "https://api.pexels.com/v1/search"
    try:
        r = requests.get(
            base, headers={"Authorization": config.PEXELS_API_KEY},
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
            files = sorted([f for f in v.get("video_files", []) if f.get("width")],
                           key=lambda f: abs(f.get("width", 0) - 1920))
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


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

# Downloaded-asset cache, keyed by (visual_type, query). A 17-minute script
# repeats subjects constantly ("the dam", "the highway"); without this we
# refetch the same clip dozens of times. Lives for the worker process.
_CACHE: Dict[str, "MediaAsset"] = {}
_CACHE_LOCK = threading.Lock()


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _download_first(candidates: List[MediaAsset], query: str,
                    work_dir: str) -> Optional[MediaAsset]:
    """Take the best candidate that actually downloads."""
    for best in candidates[:3]:
        ext = ".mp4" if best.kind == "video" else ".jpg"
        safe = "".join(ch for ch in query if ch.isalnum())[:24] or "asset"
        dest = os.path.join(
            work_dir, f"{best.source}_{safe}_{abs(hash(best.url)) % 99999}{ext}")
        try:
            best.local_path = download(best.url, dest)
            return best
        except Exception:
            continue
    return None


def source_for_segment(query: str, seconds: float, work_dir: str, *,
                       visual_type: str = "footage",
                       allow_youtube: bool = None, allow_stock: bool = None,
                       require_cc: bool = None) -> Optional[MediaAsset]:
    """
    Find and download one visual for a scene.

    `visual_type` is the director's call: "footage" wants moving pictures of
    the subject, "image" wants a still (a portrait, a document, a landscape)
    that Ken Burns will animate. Footage falls back to stills rather than
    leaving the scene black — a good photograph beats a wrong clip.
    """
    allow_youtube = config.ALLOW_YOUTUBE if allow_youtube is None else allow_youtube
    allow_stock = config.ALLOW_STOCK if allow_stock is None else allow_stock
    require_cc = config.REQUIRE_CC if require_cc is None else require_cc

    if visual_type == "footage" and allow_youtube:
        asset = youtube_clip(query, work_dir, seconds=seconds, require_cc=require_cc)
        if asset:
            return asset

    if allow_stock and visual_type == "footage":
        for fn in (search_pexels, search_pixabay):
            long_enough = [c for c in fn(query, kind="video")
                           if c.duration >= seconds * 0.8]
            asset = _download_first(long_enough, query, work_dir)
            if asset:
                return asset

    # Real photographs of the named subject, before any generated impression.
    for search in (search_wikimedia, search_openverse):
        asset = _download_first(search(query), query, work_dir)
        if asset:
            return asset

    if allow_stock:
        for fn in (search_pexels, search_pixabay):
            asset = _download_first(fn(query, kind="image"), query, work_dir)
            if asset:
                return asset

    # Last resort: an illustration for a beat nothing real covers.
    return generate_image(query, work_dir)


def source_many(jobs: List[Dict[str, Any]], work_dir: str, *,
                workers: int = 6, on_done=None, **kwargs) -> List[Optional[MediaAsset]]:
    """
    Source visuals for many scenes concurrently.

    Sourcing is almost entirely network-bound, so a modest thread pool turns a
    300-scene job from serial minutes into something practical.

    Duplicate queries are collapsed BEFORE dispatch rather than checked inside
    each worker: submitting them concurrently would let identical queries race
    past a cache check and fetch the same asset several times over.

    Results come back in the original scene order regardless of completion
    order. `jobs` is a list of
    {"index": int, "query": str, "seconds": float, "visual_type": str}.
    """
    results: List[Optional[MediaAsset]] = [None] * len(jobs)

    # (query, visual_type) -> scene indices wanting it, and the longest slice needed
    groups: Dict[tuple, Dict[str, Any]] = {}
    for j in jobs:
        key = (j["query"], j.get("visual_type", "footage"))
        g = groups.setdefault(key, {"indices": [], "seconds": 0.0})
        g["indices"].append(j["index"])
        g["seconds"] = max(g["seconds"], float(j.get("seconds") or 0))

    done = 0
    lock = threading.Lock()

    def fetch(key: tuple, seconds: float) -> Optional[MediaAsset]:
        cache_key = f"{key[1]}::{key[0]}"
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
        if hit:
            return hit
        try:
            asset = source_for_segment(key[0], seconds, work_dir,
                                       visual_type=key[1], **kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[media] '{key[0]}' failed: {e}", flush=True)
            return None
        if asset:
            with _CACHE_LOCK:
                _CACHE[cache_key] = asset
        return asset

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, key, g["seconds"]): key
                   for key, g in groups.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                asset = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[media] worker error on '{key[0]}': {e}", flush=True)
                asset = None
            for i in groups[key]["indices"]:
                results[i] = asset
            with lock:
                done += len(groups[key]["indices"])
                if on_done:
                    on_done(done, len(jobs))

    return results
