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
import urllib.parse
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

    @property
    def identity(self) -> str:
        """
        What makes this asset the same asset.

        Used to guarantee no two scenes show the same visual. For YouTube it
        is the video id, so two differently-worded searches that land on the
        same upload still count as one. For everything else the remote URL,
        and for a generated image the local file, since each generation is
        unique by construction.
        """
        if self.source == "youtube" and self.local_path:
            name = os.path.basename(self.local_path)
            if name.startswith("yt_"):
                return f"yt:{name[3:].rsplit('.', 1)[0]}"
        return f"{self.source}:{self.url or self.local_path}"

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
                 start_at: float = 30.0, require_cc: bool = True,
                 skip: int = 0, used: set = None) -> Optional[MediaAsset]:
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
    if query_or_url.startswith("http"):
        target = query_or_url
    elif require_cc:
        # NOT ytsearch: yt-dlp's flat search extractor reports license=NA for
        # every hit, so a "license *= Creative Commons" match-filter rejects
        # the entire result set and this source silently never returns
        # anything. Measured, not assumed. Going through YouTube's own search
        # page with its Creative Commons filter (sp=EgIwAQ%3D%3D) returns
        # results whose licence field is populated, so the filter below then
        # works as a second check rather than as the only one.
        target = ("https://www.youtube.com/results?search_query="
                  + urllib.parse.quote_plus(query_or_url) + "&sp=EgIwAQ%3D%3D")
    else:
        target = f"ytsearch8:{query_or_url}"
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
        "--no-warnings", "--quiet",
        "--merge-output-format", "mp4",
        # A search page is a playlist. `skip` starts further down it, so a
        # scene repeating an earlier query gets a different upload rather
        # than the same top hit again.
        "--playlist-items", f"{skip + 1}-{skip + 12}", "--max-downloads", "1",
        "-o", out_tpl,
        "--print", "after_move:filepath",
    ]
    # Reject portrait uploads. A 608x1080 clip in a 1920x1080 frame gets
    # object-fit: cover'd into a massive centre crop — measured on a real CC
    # search result, which is how this filter came to exist. It has to be
    # aspect_ratio against a literal: a match-filter compares a field to a
    # constant, so "width > height" parses `height` as a string and every
    # candidate errors out with int > str.
    match = ["aspect_ratio > 1.2"]
    if require_cc:
        # yt-dlp exposes YouTube's licence field; a match-filter keeps a search
        # rolling to the next hit instead of failing the whole scene.
        match.append("license *= Creative Commons")
    cmd += ["--match-filter", " & ".join(match)]
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

    # Two differently-worded queries can still land on the same upload;
    # reject it here so the caller falls through to another source instead
    # of showing the same footage twice.
    if used:
        name = os.path.basename(path)
        vid = f"yt:{name[3:].rsplit('.', 1)[0]}" if name.startswith("yt_") else ""
        if vid and vid in used:
            try:
                os.remove(path)
            except OSError:
                pass
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

# Search results are cached per query; the ASSETS handed out from them are not
# shared. An earlier version cached one downloaded asset per query and reused
# it for every scene that asked the same thing — fast, but a 20-minute script
# repeats subjects constantly ("the lake", "the ramp"), so the same clip came
# back a dozen times and the video looked broken. Caching the candidate LIST
# keeps the API savings while still giving every scene its own visual.
_SEARCH_CACHE: Dict[str, List[MediaAsset]] = {}
_CACHE_LOCK = threading.Lock()


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()


def _cached_search(fn, query: str) -> List[MediaAsset]:
    key = f"{fn.__name__}::{query}"
    with _CACHE_LOCK:
        if key in _SEARCH_CACHE:
            return _SEARCH_CACHE[key]
    try:
        found = fn(query)
    except Exception as e:  # noqa: BLE001
        print(f"[media] {fn.__name__} '{query}' failed: {e}", flush=True)
        found = []
    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = found
    return found


def _download(candidate: MediaAsset, query: str, work_dir: str) -> Optional[MediaAsset]:
    ext = ".mp4" if candidate.kind == "video" else ".jpg"
    safe = "".join(ch for ch in query if ch.isalnum())[:24] or "asset"
    dest = os.path.join(
        work_dir, f"{candidate.source}_{safe}_{abs(hash(candidate.url)) % 999999}{ext}")
    try:
        candidate.local_path = download(candidate.url, dest)
        return candidate
    except Exception:
        return None


def _pick_unused(candidates: List[MediaAsset], used: Optional[set],
                 query: str, work_dir: str) -> Optional[MediaAsset]:
    """First candidate whose identity hasn't been used yet, that also downloads."""
    for candidate in candidates:
        if used is not None and candidate.identity in used:
            continue
        got = _download(candidate, query, work_dir)
        if got:
            return got
    return None


def source_for_segment(query: str, seconds: float, work_dir: str, *,
                       visual_type: str = "footage", nth: int = 0,
                       used: set = None,
                       allow_youtube: bool = None, allow_stock: bool = None,
                       require_cc: bool = None) -> Optional[MediaAsset]:
    """
    Find and download one visual for a scene.

    `visual_type` is the director's call: "footage" wants moving pictures,
    "image" wants a still that Ken Burns will animate. Footage falls back to
    stills rather than leaving the scene black — a good photograph beats a
    wrong clip.

    `nth` and `used` are what keep a long video from repeating itself. `nth`
    is how many earlier scenes already asked this exact question, so the Nth
    one reaches further down the result list instead of taking the same top
    hit. `used` is every asset already placed anywhere in this video, so even
    two differently-worded queries cannot land on the same clip.
    """
    allow_youtube = config.ALLOW_YOUTUBE if allow_youtube is None else allow_youtube
    allow_stock = config.ALLOW_STOCK if allow_stock is None else allow_stock
    require_cc = config.REQUIRE_CC if require_cc is None else require_cc

    if visual_type == "footage" and allow_youtube:
        # Skip past results earlier scenes already took, and offset the grab
        # point so a repeat of the same subject is at least a different
        # moment of footage rather than the identical seconds again.
        asset = youtube_clip(query, work_dir, seconds=seconds, require_cc=require_cc,
                             skip=nth, start_at=30.0 + 25.0 * nth, used=used)
        if asset:
            return asset

    if allow_stock and visual_type == "footage":
        for fn in (search_pexels, search_pixabay):
            clips = [c for c in _cached_search(lambda q: fn(q, kind="video"), query)
                     if c.duration >= seconds * 0.8]
            asset = _pick_unused(clips[nth:] + clips[:nth], used, query, work_dir)
            if asset:
                return asset

    # Real photographs of the named subject, before any generated impression.
    for search in (search_wikimedia, search_openverse):
        found = _cached_search(search, query)
        # Rotate the list so repeats start further down, but still fall back
        # to earlier entries rather than giving up and rendering black.
        ordered = found[nth:] + found[:nth] if found else []
        asset = _pick_unused(ordered, used, query, work_dir)
        if asset:
            return asset

    if allow_stock:
        for fn in (search_pexels, search_pixabay):
            found = _cached_search(lambda q: fn(q, kind="image"), query)
            asset = _pick_unused(found[nth:] + found[:nth], used, query, work_dir)
            if asset:
                return asset

    # Last resort: an illustration for a beat nothing real covers. Always a
    # fresh generation, so it is never a duplicate.
    return generate_image(query, work_dir)


def source_many(jobs: List[Dict[str, Any]], work_dir: str, *,
                workers: int = 6, on_done=None, **kwargs) -> List[Optional[MediaAsset]]:
    """
    Source visuals for many scenes, with no two scenes sharing a visual.

    Sourcing is network-bound, so scenes are fetched through a thread pool.
    Duplicate suppression needs a shared view of what has been taken, which a
    pool cannot provide safely mid-flight, so it works in two passes:

      1. Fetch every scene in parallel. Each scene is told how many earlier
         scenes asked the same question (`nth`) and reaches that far down the
         result list, which resolves the common case — a repeated subject —
         without any coordination.
      2. Walk the results in order and re-source, serially, any scene whose
         asset was already claimed by an earlier one. Only actual collisions
         pay for this, and each retry reaches further down the list.

    `jobs` is a list of
    {"index": int, "query": str, "seconds": float, "visual_type": str}.
    """
    results: List[Optional[MediaAsset]] = [None] * len(jobs)
    ordered = sorted(jobs, key=lambda j: j["index"])

    # How many earlier scenes already asked this exact question.
    seen: Dict[tuple, int] = {}
    plan = []
    for j in ordered:
        key = (j["query"], j.get("visual_type", "footage"))
        plan.append((j, seen.get(key, 0)))
        seen[key] = seen.get(key, 0) + 1

    done = 0
    lock = threading.Lock()

    def fetch(job, nth):
        try:
            return source_for_segment(
                job["query"], float(job.get("seconds") or 0), work_dir,
                visual_type=job.get("visual_type", "footage"), nth=nth, **kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[media] '{job['query']}' failed: {e}", flush=True)
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, job, nth): job["index"] for job, nth in plan}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[media] worker error on scene {idx}: {e}", flush=True)
            with lock:
                done += 1
                if on_done:
                    on_done(done, len(jobs))

    # Pass 2: nothing may appear twice.
    used: set = set()
    duplicates = 0
    for job, nth in plan:
        i = job["index"]
        asset = results[i]
        if asset and asset.identity not in used:
            used.add(asset.identity)
            continue
        if asset:
            duplicates += 1
        replacement = None
        # Reach progressively further down the result list.
        for attempt in range(1, 4):
            try:
                replacement = source_for_segment(
                    job["query"], float(job.get("seconds") or 0), work_dir,
                    visual_type=job.get("visual_type", "footage"),
                    nth=nth + attempt, used=used, **kwargs)
            except Exception:  # noqa: BLE001
                replacement = None
            if replacement and replacement.identity not in used:
                break
            replacement = None
        if replacement:
            results[i] = replacement
            used.add(replacement.identity)
        elif asset:
            # Nothing else available. Keep the repeat rather than rendering
            # black, but say so — the editor can swap it with `resource`.
            asset.review_required = True
            asset.review_reason = "Repeat of an earlier shot — no other match found"
            used.add(asset.identity)

    if duplicates:
        print(f"[media] resolved {duplicates} duplicate shot(s)", flush=True)
    return results
