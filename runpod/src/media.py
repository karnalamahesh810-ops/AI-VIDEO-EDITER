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
import itertools
import subprocess
import threading
import urllib.parse
import requests

from . import config
from .storage import download


# Round-robin over the configured proxies so one address does not take every
# download and get flagged. itertools.cycle is not thread-safe on its own.
_PROXY_CYCLE = itertools.cycle(config.YTDLP_PROXIES) if config.YTDLP_PROXIES else None
_PROXY_LOCK = threading.Lock()


def _next_proxy() -> str:
    if not _PROXY_CYCLE:
        return ""
    with _PROXY_LOCK:
        return next(_PROXY_CYCLE)


# How YouTube refuses a datacenter IP. It does not always use the famous
# "sign in to confirm you're not a bot" wording — on a RunPod worker the
# observed message was "The following content is not available on this app",
# which reads like a missing video rather than a blocked client. Matching only
# the famous string reported that as "no results", which is precisely the
# ambiguity this detection exists to remove.
BLOCK_SIGNS = (
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you are not a bot",
    "not available on this app",
    "this content isn't available",
    "please sign in",
    "http error 429",
    "too many requests",
)
BOT_CHECK = BLOCK_SIGNS[0]  # kept for callers that check the classic wording


def looks_blocked(stderr: str) -> bool:
    """True when yt-dlp's failure is the IP being refused, not an empty search."""
    low = (stderr or "").lower()
    return any(sign in low for sign in BLOCK_SIGNS)


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


def search_wikimedia_video(query: str, limit: int = 5) -> List[MediaAsset]:
    """
    Commons holds video, not just stills, and the old code never asked for it.

    `filetype:bitmap` was hard-coded into the only Commons search, so every
    piece of freely-licensed footage on Commons was invisible to this
    pipeline. Chrome plays webm natively and Ogg Theora too, so these drop
    straight into the renderer.
    """
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            headers={"User-Agent": config.USER_AGENT},
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{query} filetype:video", "gsrlimit": limit,
                "gsrnamespace": 6, "prop": "imageinfo",
                "iiprop": "url|size|extmetadata",
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
        url = info.get("url") or ""
        # Commons appends utm_* tracking params, so the extension has to be
        # read off the parsed PATH. Checking the raw URL matched nothing and
        # silently disabled this whole source.
        ext = urllib.parse.urlparse(url).path.lower()
        if not ext.endswith((".webm", ".ogv", ".mp4")):
            continue
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "") or "")
        out.append(MediaAsset(
            kind="video", source="wikimedia", url=url,
            width=info.get("width", 0), height=info.get("height", 0),
            attribution=artist.strip()[:200],
            license=meta.get("LicenseShortName", {}).get("value", "") or "see Commons",
            query=query,
        ))
    return out


def search_nasa(query: str, want_video: bool = False,
                limit: int = 5) -> List[MediaAsset]:
    """
    NASA's image and video library. Public domain, no key, no attribution
    obligation — and squarely on-topic for a channel about water, weather and
    land in the United States: Landsat and MODIS coverage of reservoirs,
    drought, flooding, storms and wildfire.

    Two calls: search returns an id, the asset endpoint returns the actual
    renditions. Worth it, because this is the one source whose licence is
    unambiguous and whose subject matter matches the niche exactly.
    """
    media_type = "video" if want_video else "image"
    try:
        r = requests.get(
            "https://images-api.nasa.gov/search",
            headers={"User-Agent": config.USER_AGENT},
            params={"q": query, "media_type": media_type},
            timeout=25,
        )
        r.raise_for_status()
        items = ((r.json().get("collection") or {}).get("items") or [])[:limit]
    except Exception:
        return []

    out: List[MediaAsset] = []
    for item in items:
        data = (item.get("data") or [{}])[0]
        nasa_id = data.get("nasa_id")
        if not nasa_id:
            continue
        try:
            a = requests.get(f"https://images-api.nasa.gov/asset/{nasa_id}",
                             headers={"User-Agent": config.USER_AGENT}, timeout=25)
            a.raise_for_status()
            hrefs = [x.get("href", "") for x in
                     ((a.json().get("collection") or {}).get("items") or [])]
        except Exception:
            continue

        if want_video:
            # Prefer a mid-size mp4; "~orig" can be a multi-GB master.
            picks = [h for h in hrefs if h.endswith(".mp4") and "~orig" not in h] \
                or [h for h in hrefs if h.endswith(".mp4")]
        else:
            picks = [h for h in hrefs if h.endswith((".jpg", ".png"))
                     and ("~large" in h or "~orig" in h)] \
                or [h for h in hrefs if h.endswith((".jpg", ".png"))]
        if not picks:
            continue
        out.append(MediaAsset(
            kind="video" if want_video else "image",
            source="nasa", url=picks[0].replace("http://", "https://"),
            attribution=f"NASA — {data.get('title', nasa_id)}"[:200],
            license="Public domain (NASA)", query=query,
        ))
    return out


def search_nasa_video(query: str, limit: int = 5) -> List[MediaAsset]:
    """NASA footage. A named function so _cached_search keys it separately."""
    return search_nasa(query, want_video=True, limit=limit)


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


# Titles that almost always mean a person talking to camera. A documentary
# needs the thing itself, not somebody discussing it — the single most common
# failure in the first real run was an interview clip standing in for a shot
# of the subject.
_TALKING_HEAD = re.compile(
    r"\b(interview|podcast|reaction|react|vlog|q&a|ama|explained|"
    r"my thoughts|commentary|discussion|talks? about|responds?|"
    r"live ?stream|full episode|ep\.? ?\d+|tutorial|how to)\b", re.I)

# Titles that usually mean actual footage of the subject.
_B_ROLL = re.compile(
    r"\b(drone|aerial|4k|footage|b[- ]?roll|timelapse|time[- ]lapse|"
    r"flyover|walkthrough|tour|no commentary|ambience|cinematic|"
    r"raw video|caught on|satellite)\b", re.I)

# Search suffix that biases YouTube itself toward footage rather than people
# discussing the subject. Tried first; the plain query remains the fallback.
B_ROLL_INTENT = "drone aerial footage"


def _score_candidate(title: str, duration: float, aspect: float,
                     seconds: float) -> float:
    """
    How likely is this result to be usable footage of the subject?

    Cheap title/metadata heuristics only — no downloads, no API calls. It
    cannot tell what is actually on screen, but it reliably demotes the
    obvious failures (a podcast episode, a two-hour livestream, a vertical
    short) that dominated the first real run.
    """
    score = 0.0
    if _B_ROLL.search(title):
        score += 3.0
    if _TALKING_HEAD.search(title):
        score -= 4.0
    # Too short to cut from, or so long it is a stream/compilation.
    if duration and duration < max(20.0, seconds + 8):
        score -= 3.0
    elif duration and duration > 3600:
        score -= 2.5
    elif 60 <= (duration or 0) <= 900:
        score += 1.0
    if aspect and aspect < 1.2:
        score -= 5.0          # vertical; object-fit would crop it to nothing
    elif aspect and aspect >= 1.7:
        score += 1.0
    return score


def _yt_candidates(target: str, require_cc: bool, limit: int = 12,
                   timeout: int = 90) -> List[dict]:
    """
    List search results with the metadata needed to choose between them.

    Metadata only — no video is fetched. Downloading the first hit and hoping
    is what produced a man in an armchair for a line about a boat trailer.
    """
    cmd = [
        "yt-dlp", target, "--skip-download", "--no-warnings",
        "--playlist-items", f"1-{limit}",
        "--print", "%(id)s\t%(duration)s\t%(width)s\t%(height)s\t%(title)s",
    ]
    if require_cc:
        cmd += ["--match-filter", "license *= Creative Commons"]
    proxy = _next_proxy()
    if proxy:
        cmd += ["--proxy", proxy]
    if config.YTDLP_COOKIES_FILE and os.path.isfile(config.YTDLP_COOKIES_FILE):
        cmd += ["--cookies", config.YTDLP_COOKIES_FILE]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if looks_blocked(p.stderr):
        print("[media] YouTube refused this IP — set YTDLP_PROXY to a residential "
              "proxy. RunPod workers have datacenter IPs and cannot download.",
              flush=True)
        return []

    out = []
    for line in (p.stdout or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 5 or not parts[0].strip():
            continue
        vid, dur, w, h, title = parts[0], parts[1], parts[2], parts[3], "\t".join(parts[4:])

        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        width, height = num(w), num(h)
        out.append({
            "id": vid.strip(),
            "duration": num(dur),
            "aspect": (width / height) if height else 0.0,
            "title": title.strip(),
        })
    return out


def _yt_fetch(video_id: str, out_dir: str, start_at: float, seconds: float,
              timeout: int = 300) -> str:
    """Download one section of one known video. Returns the local path or ''."""
    out_tpl = os.path.join(out_dir, "yt_%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
        "--download-sections", f"*{start_at:.1f}-{start_at + seconds:.1f}",
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]",
        "--no-playlist", "--no-warnings", "--quiet",
        "--merge-output-format", "mp4",
        "-o", out_tpl, "--print", "after_move:filepath",
    ]
    proxy = _next_proxy()
    if proxy:
        cmd += ["--proxy", proxy]
    if config.YTDLP_COOKIES_FILE and os.path.isfile(config.YTDLP_COOKIES_FILE):
        cmd += ["--cookies", config.YTDLP_COOKIES_FILE]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    if looks_blocked(p.stderr):
        return ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line and os.path.exists(line):
            return line
    guess = os.path.join(out_dir, f"yt_{video_id}.mp4")
    return guess if os.path.exists(guess) else ""


def youtube_clip(query_or_url: str, out_dir: str, seconds: float = 6.0,
                 start_at: float = 30.0, require_cc: bool = True,
                 skip: int = 0, used: set = None,
                 b_roll_intent: bool = True) -> Optional[MediaAsset]:
    """
    Find and download a clip that plausibly shows the subject.

    Two passes, because one was not enough. The old version searched, took the
    first result, and grabbed the seconds at 0:30 — which on a real script
    produced talking heads, vertical phone video, and podcast intros. Now the
    search returns metadata for a dozen candidates, they are scored on title
    and shape, and only the winner is downloaded.

    The grab point is a fraction of the video's own length rather than a fixed
    offset: 0:30 of a ten-minute documentary is still the intro, but 35% in is
    reliably the body. `skip` walks further down the ranking so a repeated
    subject gets a different video.

    require_cc restricts this to Creative Commons uploads, the only footage
    you may legally re-cut and monetise. Turning it off opens up the whole of
    YouTube — far better footage, and someone else's copyright.
    """
    os.makedirs(out_dir, exist_ok=True)

    if query_or_url.startswith("http"):
        path = _yt_fetch(query_or_url.rsplit("=", 1)[-1], out_dir,
                         start_at, max(2.0, seconds + 1.5))
        if not path:
            return None
        return _asset_for(path, query_or_url, seconds, require_cc)

    # Bias the search itself toward footage; fall back to the plain query.
    searches = []
    if b_roll_intent:
        searches.append(f"{query_or_url} {B_ROLL_INTENT}")
    searches.append(query_or_url)

    for search in searches:
        if require_cc:
            # yt-dlp's flat search extractor reports license=NA for every hit,
            # so a CC match-filter over ytsearch rejects everything. YouTube's
            # own results page with its CC filter populates the field.
            target = ("https://www.youtube.com/results?search_query="
                      + urllib.parse.quote_plus(search) + "&sp=EgIwAQ%3D%3D")
        else:
            target = f"ytsearch12:{search}"

        candidates = _yt_candidates(target, require_cc)
        if not candidates:
            continue

        ranked = sorted(candidates,
                        key=lambda c: _score_candidate(c["title"], c["duration"],
                                                       c["aspect"], seconds),
                        reverse=True)
        for candidate in ranked[skip:] + ranked[:skip]:
            if used and f"yt:{candidate['id']}" in used:
                continue
            if candidate["aspect"] and candidate["aspect"] < 1.2:
                continue                       # vertical, unusable in 16:9
            duration = candidate["duration"] or 0
            grab = max(2.0, seconds + 1.5)
            # 35% in skips intros and titles; clamp so we never run off the end.
            point = max(5.0, duration * 0.35) if duration else start_at
            if duration:
                point = min(point, max(5.0, duration - grab - 2))
            path = _yt_fetch(candidate["id"], out_dir, point, grab)
            if path:
                return _asset_for(path, query_or_url, grab, require_cc,
                                  title=candidate["title"])
    return None


def _asset_for(path: str, query: str, seconds: float, require_cc: bool,
               title: str = "") -> MediaAsset:
    return MediaAsset(
        kind="video", source="youtube", url=query, local_path=path,
        duration=seconds,
        attribution=(f"YouTube: {title}" if title else "YouTube — credit the uploader"),
        license=("Creative Commons Attribution (CC BY)" if require_cc
                 else "unverified — you must hold the rights"),
        query=query,
        review_required=not require_cc,
        review_reason=("" if require_cc
                       else "Licence unverified — confirm you hold the rights"),
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

# Generated images are billed per call, so the budget is enforced here rather
# than trusted to callers. Reset per job alongside the cache.
_GENERATED = [0]


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()
        _GENERATED[0] = 0


def _generation_budget_left() -> bool:
    with _CACHE_LOCK:
        if _GENERATED[0] >= config.IMAGE_MAX_PER_VIDEO:
            return False
        _GENERATED[0] += 1
        return True


def generated_count() -> int:
    with _CACHE_LOCK:
        return _GENERATED[0]


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
                       used: set = None, fallbacks: List[str] = None,
                       prompt: str = "",
                       allow_youtube: bool = None, allow_stock: bool = None,
                       require_cc: bool = None) -> Optional[MediaAsset]:
    """
    Source one scene, relaxing the query until something is found.

    The specific phrasing is tried first because it gives the most relevant
    visual; each fallback is broader. Without this a precise query that
    matches nothing leaves the scene black, which is far worse than a
    slightly more general shot of the right subject.
    """
    for attempt in [query] + list(fallbacks or []):
        got = _source_one(attempt, seconds, work_dir, visual_type=visual_type,
                          nth=nth, used=used, prompt=prompt,
                          allow_youtube=allow_youtube,
                          allow_stock=allow_stock, require_cc=require_cc)
        if got:
            return got
    return None


def _source_one(query: str, seconds: float, work_dir: str, *,
                visual_type: str = "footage", nth: int = 0,
                used: set = None, prompt: str = "",
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

    # Free footage sources beyond YouTube. These carry clean licences, so
    # they are tried for motion before falling back to a Ken Burns still —
    # a real moving shot of the subject beats a panned photograph of it.
    if visual_type == "footage":
        for search in (search_nasa_video, search_wikimedia_video):
            found = _cached_search(search, query)
            ordered = found[nth:] + found[:nth] if found else []
            got = _pick_unused(ordered, used, query, work_dir)
            if got:
                return got

    if allow_stock and visual_type == "footage":
        for fn in (search_pexels, search_pixabay):
            clips = [c for c in _cached_search(lambda q: fn(q, kind="video"), query)
                     if c.duration >= seconds * 0.8]
            asset = _pick_unused(clips[nth:] + clips[:nth], used, query, work_dir)
            if asset:
                return asset

    # Generated stills first, when asked for. The prompt is the narration
    # line rather than the search keywords: "Lake Powell concrete ramp" is a
    # good thing to search for and a poor thing to describe to an image model.
    tried_generation = False
    if config.PREFER_GENERATED_IMAGES:
        tried_generation = True
        if _generation_budget_left():
            made = generate_image(prompt or query, work_dir)
            if made:
                return made

    # Real photographs of the named subject, before any generated impression.
    for search in (search_wikimedia, search_nasa, search_openverse):
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
    # The budget is always consulted. Writing this as
    # `if PREFER_GENERATED or budget_left()` short-circuits past the check
    # whenever the preference is on, which silently disabled the spend cap
    # entirely — caught by the cap test, not by reading it.
    if not tried_generation and _generation_budget_left():
        return generate_image(prompt or query, work_dir)
    return None


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
                visual_type=job.get("visual_type", "footage"), nth=nth,
                fallbacks=job.get("fallbacks"), prompt=job.get("prompt", ""),
                **kwargs)
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
                    nth=nth + attempt, used=used,
                    fallbacks=job.get("fallbacks"), prompt=job.get("prompt", ""),
                    **kwargs)
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
