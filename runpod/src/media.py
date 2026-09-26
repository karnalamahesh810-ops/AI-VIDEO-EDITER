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
from concurrent.futures import (FIRST_COMPLETED, ThreadPoolExecutor, as_completed,
                                wait)
from concurrent.futures import TimeoutError as FuturesTimeout
import contextvars
from dataclasses import dataclass, asdict, replace as _dc_replace
from typing import List, Optional, Dict, Any
import base64
import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
import requests

from . import config, moments, vision
from .storage import download


# Round-robin over the configured proxies so one address does not take every
# download and get flagged — but skip any address that was just refused or
# timed out. Blind rotation meant every third request went to an IP YouTube
# had already started refusing, costing a failed search plus a retry each time.
_PROXIES = list(config.YTDLP_PROXIES)
# "" is the worker's own address. Proxies are only worth it while YouTube has
# not flagged them; when it has (2026-09-25: every proxy answered "Sign in to
# confirm you're not a bot" to downloads while searches still worked), the
# machine's own IP may be the better route. YTDLP_DIRECT=1 adds it.
if config.YTDLP_DIRECT and "" not in _PROXIES:
    _PROXIES.insert(0, "")
_PROXY_LOCK = threading.Lock()
_PROXY_POS = [0]
_PROXY_BENCHED: Dict[str, float] = {}
_PROXY_BENCH_SECONDS = 600

# Bounds how many yt-dlp subprocesses run at once, across every scene and
# every scout, so sourcing does not send more simultaneous requests than
# there are proxy IPs to carry them. See config.NETWORK_CONCURRENCY.
_NET_SEM = threading.Semaphore(config.NETWORK_CONCURRENCY)


def _next_proxy() -> str:
    """Next healthy proxy; if every one is benched, the least-recently benched."""
    if not _PROXIES:
        return ""
    now = time.time()
    with _PROXY_LOCK:
        for _ in range(len(_PROXIES)):
            proxy = _PROXIES[_PROXY_POS[0] % len(_PROXIES)]
            _PROXY_POS[0] += 1
            if _PROXY_BENCHED.get(proxy, 0) <= now:
                return proxy
        return min(_PROXIES, key=lambda p: _PROXY_BENCHED.get(p, 0))


def pot_provider_alive() -> bool:
    """Is the YouTube PO-token server (scripts/start.sh) answering on this worker?"""
    try:
        return requests.get("http://127.0.0.1:4416/ping", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def probe_youtube(video_id: str = "ka2S39HhLsM") -> List[dict]:
    """
    Can this worker actually download from YouTube, directly and per proxy?

    Metadata for one known video (the step that gets refused - searches keep
    working from flagged IPs, which hid the block). Routes are reported by
    number only; a proxy URL carries credentials.
    """
    routes = [("direct", "")] + [(f"proxy#{i + 1}", p) for i, p in enumerate(config.YTDLP_PROXIES)]

    def one(route):
        name, proxy = route
        cmd = ["yt-dlp", "--skip-download", "--print", "%(id)s",
               f"https://www.youtube.com/watch?v={video_id}"] + _yt_network_args(proxy)
        t = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            ok = video_id in (p.stdout or "")
            why = "" if ok else ("bot check" if looks_blocked(p.stderr) else
                                 ((p.stderr or "").strip().splitlines() or ["no output"])[-1][:80])
        except subprocess.TimeoutExpired:
            ok, why = False, "timeout"
        # Never echo anything that could contain the proxy URL.
        why = re.sub(r"https?://\S+", "<url>", why)
        return {"route": name, "ok": ok, "seconds": round(time.time() - t, 1), "why": why}

    with ThreadPoolExecutor(max_workers=len(routes)) as ex:
        return list(ex.map(one, routes))


def _bench_proxy(proxy: str, why: str = "") -> None:
    """Take a refused or timed-out proxy out of rotation for ten minutes."""
    if not proxy:
        return
    with _PROXY_LOCK:
        _PROXY_BENCHED[proxy] = time.time() + _PROXY_BENCH_SECONDS
        idx = _PROXIES.index(proxy) + 1 if proxy in _PROXIES else "?"
    # Never print the proxy URL: it carries credentials.
    print(f"[media] benched proxy #{idx} for {_PROXY_BENCH_SECONDS // 60} min"
          f"{' (' + why + ')' if why else ''}", flush=True)


def _yt_network_args(proxy: Optional[str] = None) -> List[str]:
    """Shared bounded network/runtime settings; never log credential values."""
    args = ["--ignore-config", "--js-runtimes", "node",
            "--socket-timeout", "20", "--retries", "2",
            "--extractor-retries", "2", "--fragment-retries", "2",
            "--concurrent-fragments", "1"]
    proxy = _next_proxy() if proxy is None else proxy
    if proxy:
        args += ["--proxy", proxy]
    if config.YTDLP_COOKIES_FILE and os.path.isfile(config.YTDLP_COOKIES_FILE):
        args += ["--cookies", config.YTDLP_COOKIES_FILE]
    return args


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
    # A flagged IP served no stream formats at all (the "-f .../b" chain still
    # found nothing): a soft block, seen on residential sessions.
    "requested format is not available",
    # Search itself refused. A 403 on a single video can be a geo/age lock, but
    # on the search API it is the IP: seen on a Webshare proxy YouTube had banned.
    "unable to download api page: http error 403",
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
    # VidRush-style match record, filled by the vision judge. `intent` is what
    # the shot was supposed to show; `content_description` is what a vision
    # model saw in the actual frames; `relevance_score` compares the two.
    intent: str = ""
    content_description: str = ""
    relevance_score: Optional[float] = None
    # The same judge's 0-1 rating of the footage itself (sharp, stable, lit,
    # framed), whatever it shows. Used to pick between clips that both match.
    quality: Optional[float] = None
    vision_model: str = ""
    # Set for subject-pool shots (src/pools.py): "yt:<id>@<10 s bucket>". A
    # long subject video supplies many DIFFERENT moments - GoMotion's method -
    # so these are distinct from each other but never the same moment twice.
    moment_key: str = ""

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
        if self.moment_key:
            return self.moment_key
        if self.source == "youtube":
            # The video id from the watch URL first: sequence-pool shots are
            # named seq_<tag>_<id>_<n>.mp4 and their URL carries "&t=<start>",
            # so two shots of one video at different times used to count as
            # two different clips - one more way the same video repeated.
            m = re.search(r"[?&]v=([\w-]{11})", self.url or "")
            if m:
                return f"yt:{m.group(1)}"
        if self.source == "youtube" and self.local_path:
            name = os.path.basename(self.local_path)
            if name.startswith("yt_"):
                # Video id only. Files are named yt_<id>_<start>_<len>.mp4
                # since per-range downloads were added, and taking everything
                # before the extension made the identity range-specific: the
                # "already used" check (`yt:<id>`) never matched, so one video
                # was reused across many scenes a few seconds apart - near-
                # identical shots again and again. YouTube ids are always 11
                # characters and may themselves contain "_", so slice, don't
                # split.
                return f"yt:{name[3:14]}"
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
        media = {
            "type": self.kind,
            "url": self.local_path or self.url,
            "source": self.source,
            "attribution": self.attribution,
            "license": self.license,
        }
        if self.relevance_score is not None:
            media["relevanceScore"] = round(self.relevance_score, 3)
        if self.quality is not None:
            media["qualityScore"] = round(self.quality, 3)
        if self.content_description:
            media["contentDescription"] = self.content_description
        return media

    def apply_verdict(self, verdict: Optional[dict], intent: str) -> "MediaAsset":
        self.intent = intent or self.intent
        if verdict:
            self.content_description = verdict.get("description", "")
            self.relevance_score = verdict.get("score")
            self.quality = verdict.get("quality")
            self.vision_model = verdict.get("model", "")
        elif intent and vision.enabled() and self.source != "generated":
            # Vision is on but no model could judge this one: it is kept (an API
            # outage must not empty the timeline) but must not pass silently.
            self.review_required = True
            self.review_reason = self.review_reason or \
                "Not checked by the vision AI (model unavailable) - check it matches"
        return self


# --------------------------------------------------------------------------- #
# Real imagery: Wikimedia Commons + Openverse
# --------------------------------------------------------------------------- #

def search_web_images(query: str, limit: int = 6) -> List[MediaAsset]:
    """
    Real photographs of the named subject from a general image search.

    This is VidRush's `google_images` provider — 51 of the stills on one of
    their timelines. Archives like Commons have the landscape but rarely the
    specific press photo a documentary line is about. Serper (Google Images)
    when SERPER_API_KEY is set, the keyless DuckDuckGo search otherwise.
    Web results carry stock watermarks and unknown licences, so every one is
    vision-checked for watermarks and flagged for review.
    """
    if not config.ALLOW_WEB_IMAGES or not query.strip():
        return []
    rows = []
    if config.BRIGHTDATA_API_KEY and config.BRIGHTDATA_SERP_ZONE:
        # Google Images through Bright Data's SERP API: 100 results per call
        # with the full-size original (press photos: NOAA, TIME, NASA...).
        # Billed per successful search, not per image.
        try:
            r = requests.post(
                "https://api.brightdata.com/request",
                headers={"Authorization": f"Bearer {config.BRIGHTDATA_API_KEY}",
                         "Content-Type": "application/json"},
                json={"zone": config.BRIGHTDATA_SERP_ZONE, "format": "raw",
                      "url": "https://www.google.com/search?tbm=isch&brd_json=1&q="
                             + urllib.parse.quote_plus(query)},
                timeout=90)
            r.raise_for_status()
            for it in (r.json().get("images") or [])[:limit * 3]:
                rows.append((it.get("original_image"), 0, 0,
                             it.get("image_alt") or it.get("source") or "",
                             it.get("title") or ""))
        except (requests.RequestException, ValueError) as e:
            _source_error("web_images_brightdata", e)
            rows = []
    if not rows and config.SERPER_API_KEY:
        try:
            r = requests.post("https://google.serper.dev/images",
                              headers={"X-API-KEY": config.SERPER_API_KEY,
                                       "Content-Type": "application/json"},
                              json={"q": query, "num": limit * 2}, timeout=20)
            r.raise_for_status()
            for it in r.json().get("images", []):
                rows.append((it.get("imageUrl"), it.get("imageWidth") or 0,
                             it.get("imageHeight") or 0, it.get("title") or "",
                             it.get("link") or ""))
        except (requests.RequestException, ValueError):
            rows = []
    if not rows:
        # Keyless fallback. Through the proxy pool when there is one: a real
        # RunPod job returned no web images at all, consistent with the image
        # search rate-limiting a datacenter address the way YouTube does.
        # One direct attempt stays as the fallback for an unproxied box.
        from_proxy = _next_proxy()
        for proxy in ([from_proxy, None] if from_proxy else [None]):
            try:
                from ddgs import DDGS
                with DDGS(proxy=proxy, timeout=15) as ddg:
                    for it in ddg.images(query, max_results=limit * 2):
                        rows.append((it.get("image"), it.get("width") or 0,
                                     it.get("height") or 0, it.get("title") or "",
                                     it.get("url") or ""))
            except Exception as e:  # noqa: BLE001 — optional dependency / network
                _source_error("web_images_ddg", e)
                rows = []
            if rows:
                break
        if not rows:
            return []

    out = []
    for url, w, h, title, page in rows:
        if not url or not url.startswith("http"):
            continue
        # DuckDuckGo reports sizes as strings, Serper as ints.
        try:
            w, h = int(w or 0), int(h or 0)
        except (TypeError, ValueError):
            w, h = 0, 0
        # Thumbnails and icons are useless full-frame at 1080p.
        if w and h and (w < 800 or h < 450):
            continue
        out.append(MediaAsset(
            kind="image", source="web_image", url=url, width=int(w or 0),
            height=int(h or 0),
            attribution=(f"{title} — {page}" if page else title)[:300],
            license="unverified — web image, confirm you hold the rights",
            query=query, review_required=True,
            review_reason="Web image: licence unverified"))
        if len(out) >= limit:
            break
    return out


# File names on an article that are page furniture, not photographs.
_NOT_A_PHOTO = ("logo", "icon", "flag of", "flag_of", "seal of", "seal_of", "signature",
                "coat of arms", "coat_of_arms", "wikiquote", "wikisource", "commons-",
                "symbol", "question_book", "edit-clear", "padlock", "ambox")


def search_wikipedia_article_images(title: str, limit: int = 20) -> List[MediaAsset]:
    """
    The photographs on the subject's own English Wikipedia article.

    For a named person this is the most reliable real photo source there is:
    a keyword search such as "Anne Dunham young archival photograph" matches
    nothing on Commons, while the "Ann Dunham" article carries several real
    photos of her. One request lists every file the article uses, with its
    image info (redirects resolve spelling variants). Logos, flags, icons,
    signatures, SVGs and thumbnails are dropped.
    """
    title = (title or "").strip()
    if not title:
        return []
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            headers={"User-Agent": config.USER_AGENT},
            params={"action": "query", "format": "json", "redirects": 1,
                    "titles": title, "generator": "images", "gimlimit": 50,
                    "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                    "iiurlwidth": 1280},
            timeout=25,
        )
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except Exception as e:  # noqa: BLE001
        _source_error("wikipedia", e)
        return []

    out: List[MediaAsset] = []
    for page in pages.values():
        name = str(page.get("title") or "").lower()
        if any(k in name for k in _NOT_A_PHOTO):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if (info.get("width") or 0) < 400 or (info.get("height") or 0) < 300:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "") or "")
        out.append(MediaAsset(
            kind="image", source="wikipedia", url=url,
            width=info.get("thumbwidth") or info.get("width") or 0,
            height=info.get("thumbheight") or info.get("height") or 0,
            attribution=artist.strip()[:200],
            license=meta.get("LicenseShortName", {}).get("value", "") or "see Wikipedia",
            query=title,
        ))
        if len(out) >= limit:
            break
    return out


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
    except Exception as e:  # noqa: BLE001
        _source_error("wikimedia", e)
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
    except Exception as e:  # noqa: BLE001
        _source_error("openverse", e)
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
    except Exception as e:  # noqa: BLE001
        _source_error("wikimedia_video", e)
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
    except Exception as e:  # noqa: BLE001
        _source_error("nasa", e)
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


# Only a licence IA itself tags as fully open and commercial-safe: public
# domain, CC0, plain CC-BY or CC-BY-SA. archive.org's `movies` mediatype is
# mostly the TV News Archive (unedited broadcast captures kept for research
# under fair use, not licensed for reuse) and NC/ND-licensed uploads, which
# would be a worse Content ID risk on a monetised channel than YouTube - so
# this is a strict allow-list, not a "looks free" guess.
_ARCHIVE_ORG_OPEN_LICENCE = re.compile(
    r"(publicdomain|/zero/1\.0|/by/\d|/by-sa/\d)", re.I)
_ARCHIVE_ORG_VIDEO_EXT = (".mp4", ".ogv", ".webm")

# Collections IA itself curates as public-domain film: Prelinger (industrial,
# educational and ephemeral film) and every US federal government production
# (federal works carry no copyright at all). Searched first, narrower but
# reliably clean; the general query below is the fallback for what they miss.
_ARCHIVE_ORG_SAFE_COLLECTIONS = "(collection:prelinger OR collection:usgovfilms)"


def _archive_org_search(q: str, limit: int) -> List[dict]:
    try:
        r = requests.get(
            "https://archive.org/advancedsearch.php",
            headers={"User-Agent": config.USER_AGENT},
            params={"q": q, "fl[]": ["identifier", "title", "licenseurl"],
                    "rows": limit, "output": "json"},
            timeout=25,
        )
        r.raise_for_status()
        return (r.json().get("response") or {}).get("docs") or []
    except Exception as e:  # noqa: BLE001
        _source_error("archive_org", e)
        return []


def search_archive_org_video(query: str, limit: int = 5) -> List[MediaAsset]:
    """
    Internet Archive's `movies` collection: real newsreels, ephemeral and US
    government films — the same kind of documentary b-roll VidRush and
    GoMotion draw on beyond YouTube, and a source this worker had none of.
    Public-domain government footage is common here and licence-unambiguous.

    The known-safe collections are tried first (narrower, but everything in
    them is public domain by construction) and topped up from the general
    movies search, which needs each hit's licence checked individually.
    """
    # Membership in a known-safe collection is trusted on its own - US federal
    # works are public domain by law, whether or not this item also carries a
    # licenceurl tag. Anything from the general search still needs one.
    safe = _archive_org_search(f"mediatype:movies AND {_ARCHIVE_ORG_SAFE_COLLECTIONS} "
                               f"AND ({query})", limit * 3)
    docs = [(d, True) for d in safe]
    if len(docs) < limit:
        general = _archive_org_search(
            f"mediatype:movies AND ({query}) AND licenseurl:*", limit * 4)
        docs += [(d, False) for d in general]

    out: List[MediaAsset] = []
    for doc, trusted in docs:
        if len(out) >= limit:
            break
        if not trusted and not _ARCHIVE_ORG_OPEN_LICENCE.search(doc.get("licenseurl") or ""):
            continue
        ident = doc.get("identifier") or ""
        if not ident:
            continue
        try:
            m = requests.get(f"https://archive.org/metadata/{ident}",
                             headers={"User-Agent": config.USER_AGENT}, timeout=25)
            m.raise_for_status()
            files = m.json().get("files") or []
        except Exception:
            continue
        # The largest real video file - thumbnails, torrents and the XML
        # sidecars are never candidates, and a bigger file is a better print.
        vids = sorted(
            (f for f in files if str(f.get("name", "")).lower().endswith(_ARCHIVE_ORG_VIDEO_EXT)),
            key=lambda f: int(f.get("size") or 0), reverse=True)
        if not vids:
            continue
        f = vids[0]
        out.append(MediaAsset(
            kind="video", source="archive_org",
            url=f"https://archive.org/download/{ident}/{f['name']}",
            width=int(f.get("width") or 0), height=int(f.get("height") or 0),
            attribution=f"Internet Archive — {doc.get('title', ident)}"[:200],
            license="CC/public domain (Internet Archive) — see item page",
            query=query,
        ))
    return out


# --------------------------------------------------------------------------- #
# Generated images
# --------------------------------------------------------------------------- #

def _openai_generate(full_prompt: str, timeout: int) -> Optional[dict]:
    """One image from an OpenAI-compatible /images/generations endpoint."""
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
        return (r.json().get("data") or [{}])[0]
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        print(f"[media] image generation failed: {e}", flush=True)
        return None


def _kie_image_size(size: str) -> str:
    """OpenAI's WIDTHxHEIGHT -> the aspect ratio string KIE's jobs API wants."""
    try:
        w, h = (int(v) for v in size.lower().split("x"))
    except (ValueError, AttributeError):
        return "3:2"
    from math import gcd
    g = gcd(w, h) or 1
    w, h = w // g, h // g
    # Snap to the ratios KIE actually accepts rather than emitting 48:32.
    best, ratio = "3:2", w / h
    for cand in ("1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4"):
        cw, ch = (int(x) for x in cand.split(":"))
        if abs(cw / ch - ratio) < abs(int(best.split(":")[0]) / int(best.split(":")[1]) - ratio):
            best = cand
    return best


def _kie_generate(full_prompt: str, timeout: int) -> Optional[str]:
    """Submit one image job to KIE and block until it has a URL.

    KIE has no OpenAI-compatible /images/generations (it 404s). Everything goes
    through one asynchronous jobs API: createTask returns a taskId, and
    recordInfo reports state until `success`, at which point resultJson carries
    the URLs. Observed cost is ~70s per image, which is why the caller runs
    these on the sourcing thread pool rather than one at a time.
    """
    base = config.IMAGE_API_BASE.rstrip("/")
    if not base.endswith("/api/v1"):
        base = "https://api.kie.ai/api/v1"
    headers = {"Authorization": f"Bearer {config.IMAGE_API_KEY}",
               "Content-Type": "application/json"}
    try:
        r = requests.post(
            f"{base}/jobs/createTask", headers=headers, timeout=60,
            json={"model": config.IMAGE_MODEL,
                  "input": {"prompt": full_prompt,
                            "image_size": _kie_image_size(config.IMAGE_SIZE)}},
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 200:
            if vision.is_credit_error(body.get("code"), body.get("msg")):
                vision.note_out_of_credits()
            print(f"[media] kie createTask refused: {body.get('code')} "
                  f"{body.get('msg')}", flush=True)
            return None
        task_id = (body.get("data") or {}).get("taskId")
        if not task_id:
            return None
    except (requests.RequestException, ValueError) as e:
        print(f"[media] kie createTask failed: {e}", flush=True)
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        try:
            q = requests.get(f"{base}/jobs/recordInfo", headers=headers,
                             params={"taskId": task_id}, timeout=45).json()
        except (requests.RequestException, ValueError):
            continue
        data = q.get("data") or {}
        state = (data.get("state") or "").lower()
        if state == "success":
            try:
                urls = json.loads(data.get("resultJson") or "{}").get("resultUrls") or []
            except ValueError:
                urls = []
            return urls[0] if urls else None
        if state in ("fail", "failed", "error"):
            print(f"[media] kie image failed: {data.get('failMsg')}", flush=True)
            return None
    print(f"[media] kie image timed out after {timeout}s", flush=True)
    return None


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
    if "kie.ai" in config.IMAGE_API_BASE and vision.out_of_credits():
        return None
    os.makedirs(out_dir, exist_ok=True)
    full_prompt = f"{prompt}. {config.IMAGE_STYLE_SUFFIX}"[:3800]

    # KIE speaks its own asynchronous jobs API, not OpenAI's synchronous one.
    if "kie.ai" in config.IMAGE_API_BASE:
        url = _kie_generate(full_prompt, timeout)
        item = {"url": url} if url else None
    else:
        item = _openai_generate(full_prompt, timeout)
    if not item:
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
    r"my thoughts|(?<!no )commentary|discussion|talks? about|responds?|"
    r"live ?stream|full episode|ep\.? ?\d+|tutorial|how to|"
    # Broadcast desks and commentary: an anchor reading copy, or a creator
    # reviewing the subject, is not footage OF the subject. Both dominated
    # the first Yellowstone run.
    r"news|anchor|press conference|briefing|panel|debate|"
    r"sits? down with|speaks? (?:out|to)|breaks? (?:down|silence)|"
    r"on (?:cnn|fox|msnbc|abc|nbc|cbs)|late night|"
    r"recap|review|ranking|top \d+|theory|theories|"
    r"everything we know|what happened to|"
    # Editing-software content: screen recordings of Premiere, After
    # Effects and friends answer "cinematic trailer" all day long.
    r"premiere pro|after effects|photoshop|davinci|final cut|"
    r"template|preset|free download|plugin|"
    # Screen captures: gameplay, streams and desktop recordings are
    # all text-covered UI, whatever the subject.
    r"gameplay|let's play|lets play|speedrun|playthrough|"
    r"build guide|tier list|patch notes|season \\d+ ladder|"
    r"stream (?:highlights|vod)|twitch)\b", re.I)

# Titles that usually mean actual footage of the subject.
_B_ROLL = re.compile(
    r"\b(drone|aerial|4k|footage|b[- ]?roll|timelapse|time[- ]lapse|"
    r"flyover|tour|no commentary|ambience|cinematic|"
    r"raw video|caught on|satellite)\b", re.I)

# Search suffix that biases YouTube itself toward footage rather than people
# discussing the subject. Tried first; the plain query remains the fallback.
B_ROLL_INTENT = "drone aerial footage"


_STILL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _is_still(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in _STILL_EXTS


def _video_seconds(path: str) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30)
        return max(0.0, float((p.stdout or "0").strip() or 0))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _gray_frames(path: str, count: int = 4, w: int = 320, h: int = 180):
    """
    `count` evenly spaced frames as (h, w) uint8 arrays, [] if unreadable.

    A still yields its one frame. The old filter (`fps=N/N`) produced ZERO
    frames from a single image - ffmpeg's fps filter drops a lone frame with
    no duration - so every web photo and archive still was judged
    "unreadable" and thrown away after passing vision. That one bug sent
    18 of 23 beats of an image-heavy story into the slow replacement pass,
    where every replacement photo failed the same way. For video it also
    sampled only the first `count` seconds rather than across the clip.
    """
    try:
        import numpy as np
    except ImportError:
        return []
    if _is_still(path):
        vf, frames = f"scale={w}:{h},format=gray", 1
    else:
        seconds = _video_seconds(path)
        rate = f"{count}/{seconds:.3f}" if seconds > count else "1"
        vf, frames = f"fps={rate},scale={w}:{h},format=gray", count
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", vf,
         "-frames:v", str(frames), "-f", "rawvideo", "-"],
        capture_output=True, timeout=90)
    buf = p.stdout or b""
    n = len(buf) // (w * h)
    if n == 0:
        return []
    import numpy as np
    return [np.frombuffer(buf[i * w * h:(i + 1) * w * h], dtype="uint8").reshape(h, w)
            for i in range(n)]


def has_burned_captions(path: str, count: int = 4) -> bool:
    """
    True when a clip carries text that is not ours: hardsubs, or a UI.

    Two separate failures, one cheap geometric test each:

    * **Subtitles** sit in the lower third and make a tight horizontal band of
      many strong vertical edges - letter strokes. Scenery rarely does that in
      a band a few rows tall.
    * **Screen recordings** (gameplay HUDs, leaderboards, dashboards, slides)
      spread that same signature across the whole frame. The clip that forced
      this was a Diablo IV leaderboard with a webcam in the corner: no
      subtitles at all, and unusable as documentary footage.

    Runs on the downloaded section, because a title never admits to either.
    """
    try:
        import numpy as np
    except ImportError:
        return False
    frames = _gray_frames(path, count)
    if not frames:
        return False

    sub_hits = texty_hits = 0
    for fr in frames:
        h, w = fr.shape
        rows = _texty_rows(fr, np)
        if not rows:
            continue
        lower = [r for r in rows if r >= h * 0.62]
        # a caption band: a short contiguous run down in the lower third
        if lower and _longest_run(lower) >= 3 and len(lower) <= h * 0.20:
            sub_hits += 1
        # a UI: text-like rows scattered over much of the frame height
        if len(rows) >= h * 0.14 and (max(rows) - min(rows)) > h * 0.45:
            texty_hits += 1

    need = max(2, len(frames) // 2)
    return sub_hits >= need or texty_hits >= need


def _texty_rows(frame, np) -> list:
    """Row indices whose strong-vertical-edge count looks like a line of text."""
    h, w = frame.shape
    a = frame.astype("int16")
    edges = np.abs(np.diff(a, axis=1)) > 48
    per_row = edges.sum(axis=1)
    return [i for i, c in enumerate(per_row) if c > w * 0.16]


def _longest_run(rows: list) -> int:
    run = best = 1
    for a, b in zip(rows, rows[1:]):
        run = run + 1 if b - a <= 2 else 1
        best = max(best, run)
    return best


# Set by source_for_segment for the scene being sourced; read by the vision
# gate deep in the call chain. A context variable rather than a parameter
# threaded through every source function: each scene is sourced on one
# thread, start to finish, so it cannot leak into another scene.
_SUBJECT_TYPE: contextvars.ContextVar = contextvars.ContextVar("subject_type", default="")

# Set while sourcing a beat of a news/weather/disaster story (from the
# director's story brief): "event", or "year" when the event is this year's.
# News-outlet uploads - the main source of real event footage - are then no
# longer rejected on the word "news", and for "year" searches try this year's
# uploads first so a 2026 flood does not get 2019's.
_EVENT_WINDOW: contextvars.ContextVar = contextvars.ContextVar("event_window", default="")

# YouTube's own "Upload date: This year" filter, for the results page.
_YT_THIS_YEAR = "EgIIBQ%3D%3D"


# Stock libraries upload watermarked previews to YouTube (ZapataStock,
# FootageForPro... filled a real video with logo-stamped dolphins and
# Statues of Liberty). Their titles and channel names give them away.
_STOCK_SELLER = re.compile(
    r"stock (?:footage|video|clip)|footage ?for ?pro|zapata|pond5|storyblocks|"
    r"shutterstock|videoblocks|videohive|envato|artgrid|artlist|motion ?array|"
    r"getty ?images|istock|adobe ?stock|dissolve|filmsupply|framepool|"
    r"christoryman|royalty[- ]free|free (?:stock|footage)|no copyright",
    re.IGNORECASE)


def _stock_seller(*texts: str) -> bool:
    return any(t and _STOCK_SELLER.search(t) for t in texts)


def _talking_head(title: str) -> bool:
    """
    True when the title disqualifies a candidate.

    For a recent event story the bare word "news" does not: "Drone video shows
    flooding in Davenport | WQAD News 8" is exactly the footage wanted. Anchors,
    press conferences, interviews and the rest still disqualify, and the vision
    judge still rejects an anchor desk or burned-in text on the actual frames.
    """
    hits = [m.group(1).lower() for m in _TALKING_HEAD.finditer(title or "")]
    if _EVENT_WINDOW.get():
        hits = [h for h in hits if h != "news"]
    return bool(hits)


def _vision_gate(path: str, intent: str, context: str, label: str) -> tuple:
    """
    (keep, verdict) for a downloaded candidate.

    No intent means nothing to judge against, and an unreachable model returns
    None — both keep the candidate, so vision can only ever remove bad clips,
    never empty a timeline because an API is down.
    """
    if not intent or not vision.enabled():
        return True, None
    verdict = vision.judge(path, intent, context, event=bool(_EVENT_WINDOW.get()))
    keep = vision.acceptable(verdict, allow_people=_SUBJECT_TYPE.get() == "person")
    if verdict is not None:
        mark = "keep" if keep else "REJECT"
        flags = []
        if verdict["has_text_or_watermark"]:
            flags.append("text/watermark")
        if verdict["is_talking_head"]:
            flags.append("talking head")
        if verdict.get("quality") is not None:
            flags.append(f"quality {verdict['quality']:.2f}")
        print(f"[vision] {mark} {verdict['score']:.2f} {label[:50]!r}"
              f"{' (' + ', '.join(flags) + ')' if flags else ''}"
              f" — {verdict['description'][:90]}", flush=True)
    return keep, verdict


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
    if _talking_head(title):
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


def _yt_candidates(target: str, require_cc: bool, limit: int = 20,
                   timeout: int = 90) -> List[dict]:
    """
    List search results with the metadata needed to choose between them.

    Metadata only — no video is fetched. Downloading the first hit and hoping
    is what produced a man in an armchair for a line about a boat trailer.

    A flat search: one request for the results page. Asking for width/height
    made yt-dlp open every result's player (twelve extra requests with a JS
    challenge each): measured 30 s and a bot-check refusal against 5.5 s and
    twelve results for the flat form. Shorts are recognised from their URL;
    any other vertical video is dropped when it is scouted (_scout), which
    reads the full info anyway. Only the CC-only mode still needs the full
    form, because the licence is not on the results page.
    """
    if require_cc:
        cmd = [
            "yt-dlp", target, "--skip-download", "--no-warnings",
            "--playlist-items", f"1-{limit}",
            "--print", "%(id)s\t%(duration)s\t%(width)s\t%(height)s\t%(title)s",
            "--match-filter", "license *= Creative Commons",
        ]
    else:
        cmd = [
            "yt-dlp", target, "--flat-playlist", "--no-warnings",
            "--playlist-items", f"1-{limit}",
            "--print", "%(id)s\t%(duration)s\t%(url)s\t%(channel)s\t%(title)s",
        ]
    proxy = _next_proxy()
    cmd += _yt_network_args(proxy)

    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        _bench_proxy(proxy, "search timed out")
        return []
    except FileNotFoundError:
        return []
    if looks_blocked(p.stderr):
        _bench_proxy(proxy, "search refused")
        print("[media] YouTube rejected this request. Check proxy health, "
              "yt-dlp/runtime support, and source availability.",
              flush=True)
        return []

    out = []
    for line in (p.stdout or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 5 or not parts[0].strip():
            continue
        vid, dur, w, h, title = parts[0], parts[1], parts[2], parts[3], "\t".join(parts[4:])
        channel = h if h and not h.replace(".", "").isdigit() and h != "NA" else ""

        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        if require_cc:
            width, height = num(w), num(h)
            aspect = (width / height) if height else 0.0
        else:
            # Flat results carry the URL where the full form had dimensions.
            aspect = 9 / 16 if "/shorts/" in w else 0.0
        out.append({
            "id": vid.strip(),
            "duration": num(dur),
            "aspect": aspect,
            "title": title.strip(),
            "channel": channel,
        })
    return out


# Where VidRush-grade footage actually lives. A plain YouTube search for
# "Honolulu 1960s" returns vlogs and slideshows; British Pathé and Periscope
# Film return "A Trip To Honolulu (1966)" and "HONOLULU HAWAII 1969
# TRAVELOGUE". The story kind (set per job) picks the channel set.
_STORY_KIND = {"kind": ""}
# Job option youtube_only: every scene is a footage search and nothing but
# YouTube may fill it - no Dailymotion, archive, stills, photos or images.
_YOUTUBE_ONLY = {"on": False}


def set_story_kind(kind: str) -> None:
    _STORY_KIND["kind"] = (kind or "").strip().lower()


def set_youtube_only(on: bool) -> None:
    _YOUTUBE_ONLY["on"] = bool(on)


def youtube_only() -> bool:
    return _YOUTUBE_ONLY["on"]


def _story_channels() -> List[str]:
    kind = _STORY_KIND["kind"]
    if kind in ("history", "biography"):
        return config.ARCHIVE_CHANNELS
    if kind in ("news", "weather", "disaster"):
        return config.NEWS_CHANNELS
    return []


def _channel_candidates(query: str, channels: List[str], subject: str = "") -> List[dict]:
    """
    One search inside each channel, in parallel, results interleaved so the
    best hit of every channel comes before the second of any. Cached like
    the plain search. Channels that time out or have nothing are skipped.
    """
    key = f"ytch::{','.join(channels)}::{(subject or query).strip().lower()}::{query.lower()}"
    with _CACHE_LOCK:
        if key in _YT_CANDIDATES_CACHE:
            return _YT_CANDIDATES_CACHE[key]
    targets = [f"https://www.youtube.com/{ch}/search?query={urllib.parse.quote_plus(query)}"
               for ch in channels]
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        lists = list(ex.map(lambda t: _yt_candidates(t, False, limit=6, timeout=45), targets))
    merged, seen = [], set()
    for rank in range(max((len(x) for x in lists), default=0)):
        for found in lists:
            if rank < len(found) and found[rank]["id"] not in seen:
                seen.add(found[rank]["id"])
                merged.append(found[rank])
    with _CACHE_LOCK:
        _YT_CANDIDATES_CACHE[key] = merged
    return merged


def _yt_candidates_cached(target: str, require_cc: bool, subject: str = "",
                          variant: str = "") -> List[dict]:
    """
    _yt_candidates, reused across every beat that shares a subject.

    `variant` names which of a beat's searches this is (footage-biased,
    plain, this-year-only). Keyed by subject alone, the second search of a
    beat returned the first one's cached list, so the plain-query fallback
    never actually ran once a subject was known.
    """
    key = f"ytc::{require_cc}::{variant}::{(subject or target).strip().lower()}"
    if subject:
        with _CACHE_LOCK:
            if key in _YT_CANDIDATES_CACHE:
                return _YT_CANDIDATES_CACHE[key]
    found = _yt_candidates(target, require_cc)
    if subject:
        with _CACHE_LOCK:
            _YT_CANDIDATES_CACHE[key] = found
    return found


def _yt_info(video_id: str, timeout: int = 60) -> tuple:
    """(full yt-dlp info dict, proxy used) for one video, or ({}, proxy).

    Needed for moment selection: the flat search results carry no formats, and
    the storyboard (`sb*`) formats are what map thumbnails to timestamps. This
    is a full extraction (opens the player, runs its JS challenge) - as slow
    as the per-result lookup the flat search above exists to avoid - so a
    popular subject that several scenes reach for the same candidate is
    cached rather than re-extracted every time.
    """
    with _CACHE_LOCK:
        cached = _YT_INFO_CACHE.get(video_id)
    if cached is not None:
        return cached

    proxy = _next_proxy()
    cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}", "-J",
           "--no-warnings", "--ignore-config", "--socket-timeout", "20"]
    if proxy:
        cmd += ["--proxy", proxy]
    if config.YTDLP_COOKIES_FILE and os.path.isfile(config.YTDLP_COOKIES_FILE):
        cmd += ["--cookies", config.YTDLP_COOKIES_FILE]
    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
        info = json.loads(p.stdout) if p.returncode == 0 and p.stdout else {}
    except subprocess.TimeoutExpired:
        _bench_proxy(proxy, "metadata timed out")
        return {}, proxy
    except (FileNotFoundError, ValueError):
        return {}, proxy
    if info:
        # A failed extraction is never cached - the next scout should retry
        # it, possibly through a different (unbenched) proxy.
        with _CACHE_LOCK:
            _YT_INFO_CACHE[video_id] = (info, proxy)
    return info, proxy


def _yt_fetch(video_id: str, out_dir: str, start_at: float, seconds: float,
              timeout: int = 300) -> str:
    """Download one section of one known video. Returns the local path or ''."""
    # Different ranges must not reuse a previous download of the same video.
    range_key = f"{round(start_at * 1000)}_{round(seconds * 1000)}"
    # Each parallel scene gets its own path even when it selects the same
    # source/time range; yt-dlp otherwise races over one partial output file.
    fetch_id = uuid.uuid4().hex[:10]
    out_tpl = os.path.join(out_dir, f"yt_%(id)s_{range_key}_{fetch_id}.%(ext)s")
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
    cmd += _yt_network_args(proxy)
    # After the shared network args: yt-dlp keeps the LAST value of a repeated
    # option, so placed before them these were silently overridden by "2".
    cmd += ["--retries", "5", "--fragment-retries", "5", "--extractor-retries", "3"]
    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        _bench_proxy(proxy, "download timed out")
        print(f"[media] YouTube clip download timed out ({video_id}, {start_at:.1f}s)", flush=True)
        return ""
    except FileNotFoundError:
        print("[media] yt-dlp executable is missing; cannot download YouTube footage", flush=True)
        return ""
    if looks_blocked(p.stderr):
        _bench_proxy(proxy, "download refused")
        print(f"[media] YouTube refused the worker connection ({video_id}); check YTDLP_PROXY", flush=True)
        return ""
    if p.returncode != 0:
        reason = re.sub(r"https?://[^\s]+", "[URL]", (p.stderr or "").strip())
        print(f"[media] yt-dlp failed ({video_id}, exit {p.returncode}): {reason[-240:] or 'no diagnostic'}", flush=True)
        return ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line and os.path.exists(line):
            return line
    guess = os.path.join(out_dir, f"yt_{video_id}_{range_key}_{fetch_id}.mp4")
    return guess if os.path.exists(guess) else ""


def _fixed_point(candidate: dict, grab: float, start_at: float) -> float:
    """The old grab point: 35% in skips intros, clamped inside the video."""
    duration = candidate.get("duration") or 0
    point = max(5.0, duration * 0.35) if duration else start_at
    if duration:
        point = min(point, max(5.0, duration - grab - 2))
    return point


def _scout(candidate: dict, grab: float, intent: str, context: str) -> Optional[dict]:
    """Storyboard moment for one candidate video, or None if unavailable."""
    info, proxy = _yt_info(candidate["id"])
    if not info:
        return None
    w, h = info.get("width") or 0, info.get("height") or 0
    if w and h and w / h < 1.2:
        # Vertical. The flat search cannot see this; a zero score drops it
        # before anything is downloaded.
        return {"start": 0.0, "score": 0.0, "description": "vertical video", "tile": 0}
    return moments.pick(info, intent, context, grab, proxy)


def _plan_grabs(eligible: List[dict], grab: float, start_at: float,
                intent: str, context: str) -> List[tuple]:
    """
    Ordered (candidate, start_seconds, moment) to try downloading.

    Scouting reads each video's storyboard and asks the vision model where the
    intent is on screen. Done one video at a time it made a single beat take
    four and a half minutes; done in parallel the beat costs roughly the
    slowest scout. Videos whose best moment scores under the floor are dropped
    before any footage is downloaded. Videos with no readable storyboard keep
    the old fixed grab point, ranked after every scored match.
    """
    if not (intent and config.MOMENT_SELECTION and vision.enabled()):
        return [(c, _fixed_point(c, grab, start_at), None) for c in eligible]

    scouts = eligible[:max(1, config.MOMENT_PARALLEL)]
    results: Dict[str, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=len(scouts)) as pool:
        futures = {pool.submit(_scout, c, grab, intent, context): c["id"] for c in scouts}
        for fut in as_completed(futures):
            try:
                results[futures[fut]] = fut.result()
            except Exception:  # noqa: BLE001 - a failed scout just loses its pick
                results[futures[fut]] = None

    scored, unscored = [], []
    for c in scouts:
        m = results.get(c["id"])
        if m is None:
            unscored.append((c, _fixed_point(c, grab, start_at), None))
        elif m["score"] >= config.VISION_MIN_SCORE:
            scored.append((c, m["start"], m))
            print(f"[moment] {m['score']:.2f} @ {m['start']:.1f}s "
                  f"{c['title'][:45]!r} - {m['description'][:70]}", flush=True)
        else:
            print(f"[moment] skip {m['score']:.2f} {c['title'][:50]!r} "
                  f"- no matching moment", flush=True)
    scored.sort(key=lambda x: x[2]["score"], reverse=True)
    return scored + unscored


def _yt_fetch_retry(video_id: str, out_dir: str, start_at: float, seconds: float,
                    title: str = "") -> str:
    """_yt_fetch retried on the next proxy; logs a failure instead of
    swallowing it. A residential home IP drops or crawls on about a third of
    downloads (measured: 15/24 first tries, 502s from IPs going offline) and
    the same clip succeeds seconds later from another address - three tries
    on different IPs gets ~95% through."""
    for attempt in (1, 2, 3):
        path = _yt_fetch(video_id, out_dir, start_at, seconds)
        if path:
            return path
    print(f"[media] download failed three times, skipping: {title[:60] or video_id}",
          flush=True)
    return ""


def youtube_clip(query_or_url: str, out_dir: str, seconds: float = 6.0,
                 start_at: float = 30.0, require_cc: bool = True,
                 skip: int = 0, used: set = None,
                 b_roll_intent: bool = True, intent: str = "",
                 context: str = "", subject: str = "") -> Optional[MediaAsset]:
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
    # (search, variant, this-year-only)
    searches = []
    if _EVENT_WINDOW.get() == "year" and not require_cc:
        # A recent event: this year's uploads first, so the flood on screen is
        # the one being narrated. News titles rarely say "drone aerial", so
        # the bias word is just "footage". The unfiltered plain query stays
        # last for an event YouTube has little of yet.
        searches += [(f"{query_or_url} footage", "recent-footage", True),
                     (query_or_url, "recent", True)]
    elif b_roll_intent:
        searches.append((f"{query_or_url} {B_ROLL_INTENT}", "broll", False))
    searches.append((query_or_url, "plain", False))
    # The archive / news channels first: that is where the real footage of
    # an era or an event is, ahead of general uploads.
    if _story_channels() and not require_cc:
        searches.insert(0, (query_or_url, "channels", False))

    judged = 0
    for search, variant, this_year in searches:
        if judged >= config.VISION_MAX_CANDIDATES:
            break
        if require_cc:
            # yt-dlp's flat search extractor reports license=NA for every hit,
            # so a CC match-filter over ytsearch rejects everything. YouTube's
            # own results page with its CC filter populates the field.
            target = ("https://www.youtube.com/results?search_query="
                      + urllib.parse.quote_plus(search) + "&sp=EgIwAQ%3D%3D")
        elif this_year:
            target = ("https://www.youtube.com/results?search_query="
                      + urllib.parse.quote_plus(search) + "&sp=" + _YT_THIS_YEAR)
        else:
            target = f"ytsearch12:{search}"

        if variant == "channels":
            candidates = _channel_candidates(search, _story_channels(), subject)
        else:
            candidates = _yt_candidates_cached(target, require_cc, subject, variant)
        if not candidates:
            continue

        ranked = sorted(candidates,
                        key=lambda c: _score_candidate(c["title"], c["duration"],
                                                       c["aspect"], seconds),
                        reverse=True)
        eligible = []
        for candidate in ranked[skip:] + ranked[:skip]:
            if used and f"yt:{candidate['id']}" in used:
                continue
            # A disqualifying title excludes the candidate outright. Scoring it
            # down is not enough: the loop still takes the best of what is left,
            # so when a query finds nothing good a penalised tutorial wins
            # anyway. That is how a Premiere Pro screen recording ended up in a
            # documentary. No clip is better than the wrong clip - the caller
            # falls through to the next query, and the timeline holds the
            # previous shot.
            if _stock_seller(candidate["title"], candidate.get("channel", "")):
                continue
            if _talking_head(candidate["title"]):
                continue
            if candidate["aspect"] and candidate["aspect"] < 1.2:
                continue                       # vertical, unusable in 16:9
            eligible.append(candidate)
        if not eligible:
            continue

        grab = max(2.0, seconds + 1.5)
        plan = _plan_grabs(eligible, grab, start_at, intent, context)

        for candidate, point, moment in plan:
            if judged >= config.VISION_MAX_CANDIDATES:
                break
            path = _yt_fetch_retry(candidate["id"], out_dir, point, grab,
                                   candidate["title"])
            if not path:
                continue
            # Burned-in subtitles only become visible after the download, and a
            # clip carrying them puts two sets of captions on screen at once.
            if has_burned_captions(path):
                print(f"[media] hardsubs, skipping: {candidate['title'][:60]}",
                      flush=True)
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            # The storyboard picked the moment; the full-resolution frames of
            # the actual cut decide. Bounded per search so one bad query cannot
            # spend a dozen model calls.
            judged += 1
            keep, verdict = _vision_gate(path, intent, context, candidate["title"])
            if not keep:
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            asset = _asset_for(path, query_or_url, grab, require_cc,
                               title=candidate["title"])
            return asset.apply_verdict(verdict, intent)
    return None


def search_dailymotion(query: str, limit: int = 12, created_after: int = 0) -> List[dict]:
    """
    Dailymotion's public API: no key, ~1.5 s, and the dimensions come back
    with the hit, so vertical uploads are filtered before any download.
    Its catalogue is heavy on news-outlet clips - exactly the real-event
    footage a flood or wildfire script needs when YouTube's top results miss.
    """
    params = {"search": query, "limit": limit, "sort": "relevance",
              "fields": "id,title,duration,width,height"}
    if created_after:
        params["created_after"] = created_after
    try:
        r = requests.get(
            "https://api.dailymotion.com/videos",
            headers={"User-Agent": config.USER_AGENT},
            params=params,
            timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("list") or []
    except Exception as e:  # noqa: BLE001
        _source_error("dailymotion", e)
        return []
    out = []
    for it in items:
        w, h = float(it.get("width") or 0), float(it.get("height") or 0)
        out.append({"id": str(it.get("id") or ""), "title": str(it.get("title") or ""),
                    "duration": float(it.get("duration") or 0),
                    "aspect": (w / h) if h else 0.0})
    return [c for c in out if c["id"]]


def search_dailymotion_this_year(query: str) -> List[dict]:
    """Uploads since 1 January: a named function so _cached_search keys it apart."""
    start = datetime.datetime(datetime.date.today().year, 1, 1,
                              tzinfo=datetime.timezone.utc)
    return search_dailymotion(query, created_after=int(start.timestamp()))


def _dm_fetch(video_id: str, out_dir: str, start_at: float, seconds: float,
              timeout: int = 240) -> str:
    """
    Download one section of a Dailymotion video. Direct first: in testing
    Dailymotion served the HLS formats to a plain connection and "no video
    formats" through the residential proxies, the reverse of YouTube. One
    proxied retry covers a host that blocks the direct address instead.
    Needs curl_cffi, which yt-dlp uses to impersonate Chrome for Dailymotion.
    """
    range_key = f"{round(start_at * 1000)}_{round(seconds * 1000)}"
    out_tpl = os.path.join(out_dir, f"dm_%(id)s_{range_key}_{uuid.uuid4().hex[:10]}.%(ext)s")
    base = ["yt-dlp", f"https://www.dailymotion.com/video/{video_id}",
            "--download-sections", f"*{start_at:.1f}-{start_at + seconds:.1f}",
            "--force-keyframes-at-cuts",
            "-f", "b[height<=1080]/bv*[height<=1080]+ba",
            "--merge-output-format", "mp4", "--no-playlist", "--no-warnings",
            "--ignore-config", "--socket-timeout", "20", "--retries", "2",
            "-o", out_tpl, "--print", "after_move:filepath"]
    for proxy in ("", _next_proxy()):
        cmd = base + (["--proxy", proxy] if proxy else [])
        try:
            with _NET_SEM:
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        for line in (p.stdout or "").splitlines():
            line = line.strip()
            if line and os.path.exists(line):
                return line
        if not proxy and not _PROXIES:
            break
    return ""


def dailymotion_clip(query: str, out_dir: str, seconds: float = 6.0,
                     skip: int = 0, used: set = None, intent: str = "",
                     context: str = "", subject: str = "") -> Optional[MediaAsset]:
    """
    A second real-footage source after YouTube, held to the same rules: no
    talking-head titles, no vertical uploads, no burned-in captions, and the
    vision model must see the intent in the actual downloaded frames. There
    is no storyboard to scout, so the grab point is the fixed 35% one.
    """
    os.makedirs(out_dir, exist_ok=True)

    def rank(cands):
        return sorted(cands, key=lambda c: _score_candidate(c["title"], c["duration"],
                                                            c["aspect"], seconds),
                      reverse=True)

    ranked = rank(_cached_search(search_dailymotion, query, cache_key=subject))
    if _EVENT_WINDOW.get() == "year":
        # This year's uploads first, whatever their title score; the rest after.
        recent = rank(_cached_search(search_dailymotion_this_year, query,
                                     cache_key=subject))
        ids = {c["id"] for c in recent}
        ranked = recent + [c for c in ranked if c["id"] not in ids]
    if not ranked:
        return None
    grab = max(2.0, seconds + 1.5)
    judged = 0
    for c in ranked[skip:] + ranked[:skip]:
        if judged >= config.VISION_MAX_CANDIDATES:
            break
        page = f"https://www.dailymotion.com/video/{c['id']}"
        if used and f"dailymotion:{page}" in used:
            continue
        if _talking_head(c["title"]) or (c["aspect"] and c["aspect"] < 1.2):
            continue
        if c["duration"] and c["duration"] < grab + 4:
            continue
        path = _dm_fetch(c["id"], out_dir, _fixed_point(c, grab, 10.0), grab)
        if not path:
            continue
        if has_burned_captions(path):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        judged += 1
        keep, verdict = _vision_gate(path, intent, context, c["title"])
        if not keep:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        return MediaAsset(
            kind="video", source="dailymotion", url=page, local_path=path,
            duration=grab, attribution=f"Dailymotion: {c['title']}"[:200],
            license="unverified — you must hold the rights", query=query,
            review_required=True,
            review_reason="Licence unverified — confirm you hold the rights",
        ).apply_verdict(verdict, intent)
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
_YT_CANDIDATES_CACHE: Dict[str, List[dict]] = {}
_CACHE_LOCK = threading.Lock()

# One yt-dlp -J extraction per video per job, however many scenes scout it.
_YT_INFO_CACHE: Dict[str, tuple] = {}

# Generated images are billed per call, so the budget is enforced here rather
# than trusted to callers. Reset per job alongside the cache.
_GENERATED = [0]

# Per-source search outcomes for the job result. The search functions return
# [] on any failure, so a source that was blocked, rate-limited or down looked
# exactly like one with no matches: a 362-scene job lost 300 photo scenes and
# nothing said which source failed or why.
_SOURCE_STATS: Dict[str, Dict[str, Any]] = {}


def _source_stat(name: str) -> Dict[str, Any]:
    return _SOURCE_STATS.setdefault(name, {"searches": 0, "withResults": 0,
                                           "errors": 0, "recentErrors": []})


def _source_error(name: str, exc: Exception) -> None:
    """Record why a source failed; never raises."""
    with _CACHE_LOCK:
        st = _source_stat(name)
        st["errors"] += 1
        st["recentErrors"] = (st["recentErrors"] + [f"{type(exc).__name__}: {str(exc)[:140]}"])[-4:]


def source_stats() -> Dict[str, Any]:
    with _CACHE_LOCK:
        return {k: dict(v, recentErrors=list(v["recentErrors"])) for k, v in _SOURCE_STATS.items()}


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()
        _YT_INFO_CACHE.clear()
        _YT_CANDIDATES_CACHE.clear()
        _SOURCE_STATS.clear()
        _GENERATED[0] = 0
    vision.reset()  # per-job call/failure counts for the job result
    moments.reset_cache()  # storyboard sheets, cached per video across beats


def _generation_budget_left() -> bool:
    with _CACHE_LOCK:
        if _GENERATED[0] >= config.IMAGE_MAX_PER_VIDEO:
            return False
        _GENERATED[0] += 1
        return True


def limit_generation(n: int) -> None:
    """Allow at most `n` more generated images in this job (a fan-out part's share)."""
    with _CACHE_LOCK:
        _GENERATED[0] = max(0, config.IMAGE_MAX_PER_VIDEO - max(0, int(n)))


def generated_count() -> int:
    with _CACHE_LOCK:
        return _GENERATED[0]


def _cached_search(fn, query: str, cache_key: str = "") -> List[MediaAsset]:
    """
    Cache `fn(query)` under `cache_key` (default: the query itself).

    Sourcing passes `cache_key=subject` wherever a subject is known: a
    passage that stays on one subject for several beats used to re-search
    from scratch every beat, because each beat's query has different
    wording (with_subject adds whatever detail that specific line needs).
    Searching is the one part of sourcing that is genuinely the SAME
    question for every beat on that subject - which candidates exist for
    it - so the first beat's results are reused. Per-beat precision is
    unaffected: which MOMENT of a candidate is used, and whether it passes
    the vision judge, are still decided from that beat's own intent.
    """
    key = f"{fn.__name__}::{cache_key or query}"
    with _CACHE_LOCK:
        if key in _SEARCH_CACHE:
            return _SEARCH_CACHE[key]
    try:
        found = fn(query)
    except Exception as e:  # noqa: BLE001
        print(f"[media] {fn.__name__} '{query}' failed: {e}", flush=True)
        _source_error(fn.__name__, e)
        found = []
    with _CACHE_LOCK:
        st = _source_stat(fn.__name__)
        st["searches"] += 1
        st["withResults"] += 1 if found else 0
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
    except Exception as e:  # noqa: BLE001
        _source_error(f"download_{candidate.source}", e)
        return None


def _pick_unused(candidates: List[MediaAsset], used: Optional[set],
                 query: str, work_dir: str, intent: str = "",
                 context: str = "") -> Optional[MediaAsset]:
    """First unused candidate that downloads and passes the vision gate."""
    judged = 0
    for candidate in candidates:
        if used is not None and candidate.identity in used:
            continue
        got = _download(candidate, query, work_dir)
        if not got:
            continue
        judged += 1
        keep, verdict = _vision_gate(got.local_path, intent, context,
                                     got.attribution or got.url)
        if keep:
            return got.apply_verdict(verdict, intent)
        if judged >= config.VISION_MAX_CANDIDATES:
            break
    return None


def source_for_segment(query: str, seconds: float, work_dir: str, *,
                       visual_type: str = "footage", nth: int = 0,
                       used: set = None, fallbacks: List[str] = None,
                       prompt: str = "",
                       allow_youtube: bool = None, allow_stock: bool = None,
                       require_cc: bool = None, intent: str = "",
                       context: str = "", subject_type: str = "",
                       subject: str = "", event_window: str = "") -> Optional[MediaAsset]:
    """
    Source one scene, relaxing the query until something is found.

    The specific phrasing is tried first because it gives the most relevant
    visual; each fallback is broader. Without this a precise query that
    matches nothing leaves the scene black, which is far worse than a
    slightly more general shot of the right subject.

    subject_type "person": the line is about a named person, so a portrait or
    that person speaking passes the vision gate, and no image is ever
    GENERATED - an invented photo of a real person is a fabrication.
    """
    if config.REQUIRE_AI and vision.ai_exhausted():
        return None   # the job is stopping; do not spend on searches it will discard
    token = _SUBJECT_TYPE.set(subject_type or "")
    window_token = _EVENT_WINDOW.set(event_window or "")
    try:
        from .director import relaxed_queries
        attempts = list(dict.fromkeys([query] + list(fallbacks or []) + relaxed_queries(query)))
        for attempt in attempts:
            got = _source_one(attempt, seconds, work_dir, visual_type=visual_type,
                              nth=nth, used=used, prompt=prompt,
                              allow_youtube=allow_youtube,
                              allow_stock=allow_stock, require_cc=require_cc,
                              intent=intent or query, context=context,
                              subject=subject)
            if got:
                return got
        return None
    finally:
        _EVENT_WINDOW.reset(window_token)
        _SUBJECT_TYPE.reset(token)


def _source_one(query: str, seconds: float, work_dir: str, *,
                visual_type: str = "footage", nth: int = 0,
                used: set = None, prompt: str = "",
                allow_youtube: bool = None, allow_stock: bool = None,
                require_cc: bool = None, intent: str = "",
                context: str = "", subject: str = "") -> Optional[MediaAsset]:
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
    if youtube_only():
        visual_type, allow_youtube, allow_stock = "footage", True, False

    if visual_type == "footage" and allow_youtube:
        # Skip past results earlier scenes already took, and offset the grab
        # point so a repeat of the same subject is at least a different
        # moment of footage rather than the identical seconds again.
        asset = youtube_clip(query, work_dir, seconds=seconds, require_cc=require_cc,
                             skip=nth, start_at=30.0 + 25.0 * nth, used=used,
                             intent=intent, context=context, subject=subject)
        if asset:
            return asset
    if youtube_only():
        return None

    if visual_type == "footage" and config.ALLOW_DAILYMOTION and not require_cc:
        asset = dailymotion_clip(query, work_dir, seconds=seconds, skip=nth,
                                 used=used, intent=intent, context=context,
                                 subject=subject)
        if asset:
            return asset

    # Free footage sources beyond YouTube. These carry clean licences, so
    # they are tried for motion before falling back to a Ken Burns still —
    # a real moving shot of the subject beats a panned photograph of it.
    if visual_type == "footage":
        extra = (search_archive_org_video,) if config.ALLOW_ARCHIVE_ORG else ()
        for search in (search_nasa_video, search_wikimedia_video) + extra:
            found = _cached_search(search, query)
            ordered = found[nth:] + found[:nth] if found else []
            got = _pick_unused(ordered, used, query, work_dir, intent, context)
            if got:
                return got

    if allow_stock and visual_type == "footage":
        for fn in (search_pexels, search_pixabay):
            clips = [c for c in _cached_search(lambda q: fn(q, kind="video"), query)
                     if c.duration >= seconds * 0.8]
            asset = _pick_unused(clips[nth:] + clips[:nth], used, query, work_dir, intent, context)
            if asset:
                return asset

    # Generated stills first, when asked for. The prompt is the narration
    # line rather than the search keywords: "Lake Powell concrete ramp" is a
    # good thing to search for and a poor thing to describe to an image model.
    tried_generation = False
    person = _SUBJECT_TYPE.get() == "person"
    if config.PREFER_GENERATED_IMAGES and not person:
        tried_generation = True
        if _generation_budget_left():
            made = generate_image(prompt or query, work_dir)
            if made:
                return made

    # The subject's own Wikipedia article first: for a named person or place
    # it holds real photos of exactly that subject, where keyword searches
    # built from the line ("Anne Dunham teenage archival photo") match nothing.
    if subject and _SUBJECT_TYPE.get() in ("person", "place", "event"):
        found = _cached_search(search_wikipedia_article_images, subject)
        ordered = found[nth:] + found[:nth] if found else []
        asset = _pick_unused(ordered, used, subject, work_dir, intent, context)
        if asset:
            return asset

    # Real photographs of the named subject, before any generated impression.
    # A general web image search finds the specific press photo; the archives
    # follow with cleaner licences but narrower coverage.
    for search in (search_web_images, search_wikimedia, search_nasa, search_openverse):
        found = _cached_search(search, query)
        # Rotate the list so repeats start further down, but still fall back
        # to earlier entries rather than giving up and rendering black.
        ordered = found[nth:] + found[:nth] if found else []
        asset = _pick_unused(ordered, used, query, work_dir, intent, context)
        if asset:
            return asset

    if allow_stock:
        for fn in (search_pexels, search_pixabay):
            found = _cached_search(lambda q: fn(q, kind="image"), query)
            asset = _pick_unused(found[nth:] + found[:nth], used, query, work_dir, intent, context)
            if asset:
                return asset

    # A still nothing was found for tries moving footage of the same thing.
    # Footage already fell back to stills; stills never fell back to footage,
    # and on a 362-scene biography the planner made 300 lines photos - photo
    # search came back empty for nearly all of them while footage filled 94%
    # of its scenes, so 86% of the video rendered black. For a person the
    # vision gate already accepts footage of that person speaking.
    if visual_type == "image":
        if allow_youtube:
            asset = youtube_clip(query, work_dir, seconds=seconds, require_cc=require_cc,
                                 skip=nth, start_at=30.0 + 25.0 * nth, used=used,
                                 intent=intent, context=context, subject=subject)
            if asset:
                return asset
        if config.ALLOW_DAILYMOTION and not require_cc:
            asset = dailymotion_clip(query, work_dir, seconds=seconds, skip=nth,
                                     used=used, intent=intent, context=context,
                                     subject=subject)
            if asset:
                return asset

    # Last resort: an illustration for a beat nothing real covers. Always a
    # fresh generation, so it is never a duplicate.
    # The budget is always consulted. Writing this as
    # `if PREFER_GENERATED or budget_left()` short-circuits past the check
    # whenever the preference is on, which silently disabled the spend cap
    # entirely — caught by the cap test, not by reading it.
    if not tried_generation and not person and _generation_budget_left():
        return generate_image(prompt or query, work_dir)
    return None


def clip_quality(path: str) -> tuple:
    """
    (ok, reason) for a sourced file. Reason is empty when it passes.

    Everything here is a failure that only shows up once the bytes are on disk,
    which is why the title heuristics upstream cannot catch it:

    * somebody else's text - hardsubs, or a UI (see has_burned_captions)
    * near-black - a fade, a night shot, or a download that grabbed the gap
      between scenes
    * frozen - a still image uploaded as a video, or a held title card, which
      reads as a broken player rather than a cut
    """
    if not path or not os.path.exists(path):
        return False, "missing"
    try:
        import numpy as np
    except ImportError:
        return True, ""
    frames = _gray_frames(path, 4)
    if not frames:
        return False, "unreadable"

    if _is_still(path):
        # Text on a still was already judged by vision, and a document photo
        # is text by design - the caption detector would reject every one.
        # Frozen means nothing for a photo. Only a black frame is a failure.
        return (False, "near-black") if float(frames[0].mean()) < 26 else (True, "")

    if has_burned_captions(path):
        return False, "burned-in text or UI"

    dark = sum(1 for f in frames if float(f.mean()) < 26)
    if dark >= max(2, len(frames) // 2):
        return False, "near-black"

    if len(frames) >= 2:
        deltas = [float(np.abs(a.astype("int16") - b.astype("int16")).mean())
                  for a, b in zip(frames, frames[1:])]
        if max(deltas) < 1.2:
            return False, "frozen frame"
    return True, ""


def _asset_ok(asset) -> tuple:
    """
    Quality verdict for a MediaAsset.

    Only judges what it can actually open. An asset with nothing on disk is
    trusted rather than dropped: the inspection is the whole basis of the
    verdict, and guessing without it would throw away perfectly good remote
    assets (and every asset in a test that does not touch the filesystem).
    """
    if asset is None:
        return False, "missing"
    if asset.source == "generated":
        return True, ""
    path = getattr(asset, "local_path", "") or ""
    if not path or not os.path.exists(path):
        return True, ""
    return clip_quality(path)


# What the last source_many() did, phase by phase, for the job result. The
# worker's own log shows this, but RunPod doesn't expose that log - without
# it, "why is this slow" was guesswork: a real job sent 19-21 of 23 beats to
# the slow replacement pass and there was no way to see which of empty /
# repeat / rejected was the cause.
LAST_STATS: Dict[str, Any] = {}


def _budget(base: float, per_item: float, n: int) -> float:
    """
    A pass budget that grows with the video.

    Fixed budgets were sized on a 95 s test (23 scenes). A 23-minute video
    has ~400 scenes: the same 420 s cut most of them off, and the empties were
    covered with repeats and generated stills - "the same clips over and
    over, a lot of AI images". The base stays the floor; each scene adds
    per_item seconds (measured ~40 s of search per scene across 16 threads).
    """
    if base <= 0:
        return 0.0       # an explicit 0 turns the pass off
    return max(base, per_item * n)


def _until(futures, deadline: float):
    """
    Yield futures as they finish, stopping at `deadline`.

    The pass budgets used to be checked only between attempts, and every pass
    ended in a `with ThreadPoolExecutor` block that waits for all threads -
    so one slow attempt ran as long as it liked and held the video: a real
    job's 240 s replacement pass took 525 s for six scenes. The caller shuts
    its pool down with wait=False; late threads finish in the background and
    their results are ignored.
    """
    pending = set(futures)
    while pending:
        left = deadline - time.time()
        if left <= 0:
            return
        finished, pending = wait(pending, timeout=min(left, 5), return_when=FIRST_COMPLETED)
        yield from finished


def source_many(jobs: List[Dict[str, Any]], work_dir: str, *,
                workers: int = 6, on_done=None, on_review=None, rescue=None,
                on_recheck=None, sequences: Optional[List[dict]] = None,
                assign=None, on_pool=None, exclude: Optional[set] = None,
                **kwargs) -> List[Optional[MediaAsset]]:
    """
    Source visuals for many scenes, with no two scenes sharing a visual.

    Sourcing is network-bound, so scenes are fetched through a thread pool.
    Duplicate suppression needs a shared view of what has been taken, which a
    pool cannot provide safely mid-flight, so it works in two passes:

      1. Fetch every scene in parallel. Each scene is told how many earlier
         scenes asked the same question (`nth`) and reaches that far down the
         result list, which resolves the common case — a repeated subject —
         without any coordination.
      2. Walk the results in order to find repeats, unusable clips and empty
         scenes, then re-source those in parallel under
         REPLACE_BUDGET_SECONDS, reporting through `on_review(done, total)`.
         Each retry reaches further down the same result list.

    `jobs` is a list of
    {"index": int, "query": str, "seconds": float, "visual_type": str}.
    """
    results: List[Optional[MediaAsset]] = [None] * len(jobs)
    ordered = sorted(jobs, key=lambda j: j["index"])
    t_start = time.time()
    LAST_STATS.clear()
    LAST_STATS.update(scenes=len(jobs))

    # How many earlier scenes already drew from the same candidate list, so
    # each reaches a different entry of it. Keyed on the SUBJECT when there is
    # one, because that is what the candidate search is cached on
    # (_yt_candidates_cached / _cached_search). Keyed on the exact query, every
    # same-subject beat got nth=0 - their wording differs - so all of them,
    # running in parallel, picked the same top video from the shared list, and
    # all but one were thrown out as duplicates: a real 23-beat job sent 21 to
    # the slow one-by-one replacement pass.
    seen: Dict[tuple, int] = {}
    plan = []
    for j in ordered:
        who = (j.get("subject") or "").strip().lower() or j["query"]
        key = (who, j.get("visual_type", "footage"))
        plan.append((j, seen.get(key, 0)))
        seen[key] = seen.get(key, 0) + 1

    done = 0
    lock = threading.Lock()
    # Claimed as each scene finishes, so a scene that starts later skips a
    # video an earlier one already took. Without it every parallel scene
    # asking about the same subject grabbed the same top result, and pass 2
    # had to re-source most of them. Races still happen (two scenes finishing
    # at once); pass 2 below catches those.
    live_used: set = set(exclude or ())   # clips another part already took

    # Sequence pools first: each run of lines about one subject and setting
    # gathers its shots together and is laid out by the editor call. Lines a
    # pool cannot fill fall through to the one-by-one search below, then the
    # recheck and the story fill.
    if sequences and config.SEQUENCE_SOURCING:
        by_index = {j["index"]: j for j in ordered}
        pooled = [0]
        if on_pool:
            on_pool(0, len(sequences))

        def run_sequence(n, seq):
            try:
                return source_sequence(
                    seq, by_index, work_dir, live_used, lock, assign=assign,
                    require_cc=kwargs.get("require_cc"),
                    allow_youtube=kwargs.get("allow_youtube"), tag=str(n))
            except Exception as e:  # noqa: BLE001 - its lines fall back to per-line search
                print(f"[media] sequence {n + 1} failed: {e}", flush=True)
                return {}

        # Same straggler rule as pass 1: a pool still running at the budget
        # is abandoned and its lines fall through to the one-by-one search.
        seq_pool = ThreadPoolExecutor(max_workers=max(1, workers))
        futures = [seq_pool.submit(contextvars.copy_context().run, run_sequence, n, seq)
                   for n, seq in enumerate(sequences)]
        try:
            for fut in as_completed(futures, timeout=_budget(
                    config.SEQUENCE_BUDGET_SECONDS, 2.0, len(jobs))):
                for idx, asset in (fut.result() or {}).items():
                    if 0 <= idx < len(results) and results[idx] is None:
                        results[idx] = asset
                with lock:
                    pooled[0] += 1
                    if on_pool:
                        on_pool(pooled[0], len(sequences))
        except FuturesTimeout:
            print(f"[media] {sum(1 for f in futures if not f.done())} sequence pool(s) over "
                  f"budget; their lines go to the one-by-one search", flush=True)
        finally:
            seq_pool.shutdown(wait=False, cancel_futures=True)
        filled = sum(1 for r in results if r is not None)
        print(f"[media] sequence pools filled {filled}/{len(jobs)} scene(s) from "
              f"{len(sequences)} sequence(s)", flush=True)
    # Only the lines still empty go to the one-by-one search; every line,
    # pooled or not, still goes through the duplicate/quality pass below.
    pass1 = [(j, nth) for j, nth in plan if results[j["index"]] is None]
    done = len(plan) - len(pass1)

    def attempt(job, nth):
        return source_for_segment(
            job["query"], float(job.get("seconds") or 0), work_dir,
            visual_type=job.get("visual_type", "footage"), nth=nth,
            used=live_used,
            fallbacks=job.get("fallbacks"), prompt=job.get("prompt", ""),
            intent=job.get("intent", ""), context=job.get("context", ""),
            subject_type=job.get("subject_type", ""), subject=job.get("subject", ""),
            event_window=job.get("event_window", ""),
            **kwargs)

    def stronger_hook(job, nth, got):
        # The opening beats decide whether a viewer stays, so they do not take
        # the first clip that merely passes: one more candidate is judged and
        # the one with more appeal (relevance first, footage quality second)
        # opens the video.
        try:
            alt = attempt(job, nth + 1)
        except Exception:  # noqa: BLE001
            return got
        if alt is None or alt.relevance_score is None:
            return got
        before = vision.appeal(got.relevance_score, got.quality)
        after = vision.appeal(alt.relevance_score, alt.quality)
        if after <= before:
            return got
        with lock:
            if alt.identity in live_used:
                return got
            live_used.discard(got.identity)
            live_used.add(alt.identity)
        print(f"[media] scene {job['index'] + 1}: stronger hook shot "
              f"{before:.2f} -> {after:.2f}", flush=True)
        return alt

    def fetch(job, nth):
        try:
            got = attempt(job, nth)
        except Exception as e:  # noqa: BLE001
            print(f"[media] '{job['query']}' failed: {e}", flush=True)
            return None
        if got:
            with lock:
                live_used.add(got.identity)
            if job.get("hook") and got.relevance_score is not None:
                got = stronger_hook(job, nth, got)
        return got

    # Not a `with` block: its exit waits for every thread, and one hung
    # download then holds the whole video. A real job sat at "Sourced 22/23"
    # for over ten minutes on a single stalled scene. Stragglers are left
    # running in the background and their scenes fall through to the
    # recheck / fill steps below, which exist for exactly that.
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futures = {pool.submit(fetch, job, nth): job["index"] for job, nth in pass1}
    started = time.time()
    deadline = started + _budget(config.PASS1_BUDGET_SECONDS, 3.0, len(pass1))
    pending = set(futures)
    try:
        while pending:
            left = deadline - time.time()
            if left <= 0:
                break
            finished, pending = wait(pending, timeout=min(left, 5), return_when=FIRST_COMPLETED)
            for fut in finished:
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:  # noqa: BLE001
                    print(f"[media] worker error on scene {idx}: {e}", flush=True)
                with lock:
                    done += 1
                    if on_done:
                        on_done(done, len(jobs))
            # Once nearly everything is in, the last few get a short grace
            # period rather than the whole budget.
            if pending and len(pending) <= max(1, len(futures) // 10):
                deadline = min(deadline, time.time() + config.STRAGGLER_GRACE_SECONDS)
        if pending:
            stuck = sorted(futures[f] + 1 for f in pending)
            print(f"[media] gave up waiting on scene(s) {stuck}; they go to the recheck",
                  flush=True)
            LAST_STATS["pass1_stragglers"] = len(stuck)
            with lock:
                done += len(pending)
                if on_done:
                    on_done(done, len(jobs))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    t_pass2 = time.time()
    # Pass 2: nothing may appear twice, and nothing unusable may stay.
    #
    # Both failures want the same repair - reach further down the same result
    # list - so they share one loop. A clip that is merely a repeat is better
    # than black; a clip covered in somebody else's subtitles is not, so an
    # unusable shot is dropped even when there is nothing to put in its place.
    # Classify first (no network): the first scene to claim a clip keeps it.
    # A clip another part of the same video already took counts as claimed.
    used: set = set(exclude or ())
    duplicates = rejected = empty = 0
    todo = []  # (job, nth, bad_reason, is_duplicate)
    for job, nth in plan:
        i = job["index"]
        asset = results[i]
        if asset is None:
            empty += 1
            todo.append((job, nth, "", False))
            continue
        ok, why = _asset_ok(asset)
        if not ok:
            rejected += 1
            print(f"[media] scene {i + 1}: dropping clip ({why})", flush=True)
            todo.append((job, nth, why, False))
        elif asset.identity in used:
            duplicates += 1
            todo.append((job, nth, "", True))
        else:
            used.add(asset.identity)

    # Then replace in parallel, under a time budget. This pass used to run one
    # scene at a time with up to three full attempts each and no progress
    # report: on a 17-scene test it sat at "Sourced 17/17" for over ten
    # minutes. Parallelising it, not shrinking it, is what fixes that - the
    # wall-clock deadline below already bounds the worst case, so every kind
    # of miss (empty, duplicate, rejected) still gets the full three reaches.
    # A truly empty scene is the one most likely to need them: pass 1 found
    # nothing at nth=0, which says nothing about nth=1..3.
    claim = threading.Lock()
    deadline = time.time() + _budget(config.REPLACE_BUDGET_SECONDS, 3.0, len(todo))
    replaced = [0]

    def replace(job, nth, bad_reason, is_dup):
        for attempt in range(1, 4):
            if time.time() >= deadline:
                return None
            try:
                candidate = source_for_segment(
                    job["query"], float(job.get("seconds") or 0), work_dir,
                    visual_type=job.get("visual_type", "footage"),
                    nth=nth + attempt, used=used,
                    fallbacks=job.get("fallbacks"), prompt=job.get("prompt", ""),
                    intent=job.get("intent", ""), context=job.get("context", ""),
                    subject_type=job.get("subject_type", ""), subject=job.get("subject", ""),
                    event_window=job.get("event_window", ""),
                    **kwargs)
            except Exception:  # noqa: BLE001
                candidate = None
            if not candidate:
                continue
            ok, why = _asset_ok(candidate)
            if not ok:
                print(f"[media] scene {job['index'] + 1}: replacement also bad ({why})",
                      flush=True)
                continue
            with claim:
                if candidate.identity in used:
                    continue
                used.add(candidate.identity)
            return candidate
        return None

    if todo:
        if on_review:
            on_review(0, len(todo))
        pool = ThreadPoolExecutor(max_workers=max(1, workers))
        futures = {pool.submit(contextvars.copy_context().run, replace, *t): t for t in todo}
        try:
            for n, fut in enumerate(_until(futures, deadline + 15), 1):
                job, nth, bad_reason, is_dup = futures[fut]
                i = job["index"]
                try:
                    replacement = fut.result()
                except Exception:  # noqa: BLE001
                    replacement = None
                if replacement:
                    results[i] = replacement
                    replaced[0] += 1
                    if bad_reason:
                        print(f"[media] scene {i + 1}: replaced", flush=True)
                elif bad_reason:
                    # Nothing clean to put here. Leaving it empty lets the
                    # timeline hold the previous shot instead of the bad one.
                    results[i] = None
                elif is_dup and results[i]:
                    # Keep the repeat rather than rendering black, but say so -
                    # the editor can swap it with `resource`.
                    results[i].review_required = True
                    results[i].review_reason = "Repeat of an earlier shot — no other match found"
                if on_review:
                    on_review(n, len(todo))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    if duplicates:
        print(f"[media] resolved {duplicates} duplicate shot(s)", flush=True)
    if rejected:
        print(f"[media] rejected {rejected} unusable clip(s)", flush=True)
    if todo:
        print(f"[media] second pass: {replaced[0]}/{len(todo)} scene(s) replaced "
              f"({empty} empty, {duplicates} repeats, {rejected} unusable)", flush=True)
    LAST_STATS.update(pass1_seconds=round(t_pass2 - t_start, 1),
                      pass2_seconds=round(time.time() - t_pass2, 1),
                      pass1_empty=empty, pass1_repeats=duplicates,
                      pass1_unusable=rejected, pass2_replaced=replaced[0])

    # Recheck with AI: every scene still without a shot of its own - empty, or
    # holding only a copy of another scene's clip, which on screen reads as a
    # missing shot just the same - goes to one model call that proposes
    # DIFFERENT things to show, knowing the lines around it and what the
    # neighbouring scenes already show. Each idea is sourced like a normal
    # scene. The planner's fallbacks only broaden the same idea, which cannot
    # help a subject with no footage at all - the medieval-history test left 9
    # of 17 scenes empty that way.
    def is_repeat(asset):
        return bool(asset and asset.review_reason.startswith("Repeat of an earlier shot"))

    by_index = {job["index"]: job for job, _ in plan}

    def recheck_item(job):
        i = job["index"]
        near = [by_index.get(i - 1), by_index.get(i + 1)]
        shows = [results[n["index"]].content_description for n in near
                 if n and results[n["index"]] is not None
                 and results[n["index"]].content_description]
        return {"index": i, "text": job.get("context", ""), "query": job["query"],
                "intent": job.get("intent", ""),
                "before": near[0].get("context", "") if near[0] else "",
                "after": near[1].get("context", "") if near[1] else "",
                "shows": shows, "repeat": is_repeat(results[i])}

    empties = [job for job, _ in plan
               if results[job["index"]] is None or is_repeat(results[job["index"]])]
    if empties and rescue:
        if on_recheck:
            on_recheck(len(empties))
        ideas = rescue([recheck_item(j) for j in empties]) or {}
        rescue_deadline = time.time() + _budget(config.RESCUE_BUDGET_SECONDS, 3.0, len(empties))

        def rescue_one(job):
            alts = ideas.get(job["index"]) or []
            if not alts or time.time() >= rescue_deadline:
                return None
            try:
                got = source_for_segment(
                    alts[0], float(job.get("seconds") or 0), work_dir,
                    visual_type=job.get("visual_type", "footage"), used=used,
                    fallbacks=alts[1:], prompt=job.get("prompt", ""),
                    intent=job.get("intent", ""), context=job.get("context", ""),
                    subject_type=job.get("subject_type", ""),
                    event_window=job.get("event_window", ""), **kwargs)
            except Exception:  # noqa: BLE001
                return None
            if not got:
                return None
            with claim:
                if got.identity in used:
                    return None
                used.add(got.identity)
            return got

        filled_by_ai = 0
        pool = ThreadPoolExecutor(max_workers=max(1, workers))
        futures = {pool.submit(contextvars.copy_context().run, rescue_one, job): job
                   for job in empties}
        try:
            for fut in _until(futures, rescue_deadline + 15):
                got = fut.result() if not fut.exception() else None
                if got:
                    results[futures[fut]["index"]] = got
                    filled_by_ai += 1
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        print(f"[media] AI recheck gave {filled_by_ai}/{len(empties)} missing or "
              f"repeated scene(s) a shot of their own", flush=True)
        LAST_STATS.update(rescue_tried=len(empties), rescue_filled=filled_by_ai)

    # Last resort for whatever is still empty: one generated still each,
    # within IMAGE_MAX_PER_VIDEO. Inside source_for_segment generation only
    # happens at the very end of an attempt, which the pass-2 time budget
    # often cut off before it was reached - a real 19-scene job ended with
    # five black scenes and none of its six allowed images used.
    # Never for a person: an invented photograph of a real person is a
    # fabrication, and the editor can Find footage for that scene instead.
    empties = [job for job, _ in plan if results[job["index"]] is None
               and job.get("subject_type") != "person"]
    if empties:
        def gen(job):
            if not _generation_budget_left():
                return None
            return generate_image(job.get("prompt") or job["query"], work_dir)

        with ThreadPoolExecutor(max_workers=min(4, len(empties))) as pool:
            for job, made in zip(empties, pool.map(gen, empties)):
                if made:
                    results[job["index"]] = made
        filled = sum(1 for job in empties if results[job["index"]] is not None)
        print(f"[media] generated stills for {filled}/{len(empties)} empty scene(s)",
              flush=True)
        LAST_STATS.update(generated_tried=len(empties), generated_filled=filled)

    reused = fill_from_story(ordered, results) if config.REUSE_SHOTS_TO_FILL else 0
    if reused:
        print(f"[media] reused a shot from elsewhere in the story for {reused} "
              f"scene(s) nothing else could fill", flush=True)
    LAST_STATS.update(total_seconds=round(time.time() - t_start, 1),
                      reused_to_fill=reused,
                      still_empty=sum(1 for r in results if r is None),
                      by_source=dict(sorted(
                          ((src, sum(1 for r in results if r and r.source == src))
                           for src in {r.source for r in results if r}),
                          key=lambda kv: -kv[1])))
    return results


# Tokens that do not identify a person on their own.
_NAME_SUFFIX = {"sr", "jr", "ii", "iii", "iv"}
# Scenes on either side where a reused shot must not already appear.
REUSE_MIN_GAP = 3


def _name_tokens(subject: str) -> tuple:
    """(surname, suffix, given-name tokens) with "Anne" and "Ann" folded together."""
    words = [w.strip(".,'’\"()").lower() for w in (subject or "").split()]
    words = [w for w in words if w]
    suffix = words.pop() if words and words[-1] in _NAME_SUFFIX else ""
    if not words:
        return "", suffix, frozenset()
    fold = lambda w: w[:-1] if len(w) > 3 and w.endswith("e") else w  # noqa: E731
    return words[-1], suffix, frozenset(fold(w) for w in words[:-1])


def same_subject(a: str, b: str) -> bool:
    """
    True when two subject labels name the same thing.

    The planner writes one person several ways across a long script ("Anne
    Dunham", "Ann Dunham", "Stanley Ann Dunham"); those must pool their shots.
    "Madelyn Dunham" is a different person, and "Barack Obama Sr." is not
    "Barack Obama": the surname alone is never enough.
    """
    if not a or not b:
        return False
    if a.strip().lower() == b.strip().lower():
        return True
    sa, xa, ga = _name_tokens(a)
    sb, xb, gb = _name_tokens(b)
    if not sa or sa != sb or xa != xb:
        return False
    if not ga or not gb:
        return ga == gb
    return bool(ga & gb)


def fill_from_story(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]]) -> int:
    """
    Give every scene still empty a real shot from elsewhere in the same story.

    The last step, after searching, the AI recheck and generation. A real
    person may have five photos online and forty lines in a biography; with
    each shot usable once, the other thirty-five scenes rendered black. First
    choice is a shot of the same subject placed more than REUSE_MIN_GAP scenes
    away, then a shot from a nearby scene - never a photo of a different
    person, which would put the wrong face on screen - and last the same
    subject's farthest shot, never on the scene right next to it. Every reuse
    is flagged for review. Returns how many scenes were filled.
    """
    by_index = {j["index"]: j for j in jobs}
    order = sorted(by_index)

    def placed_near(identity: str, i: int) -> bool:
        return any(results[k] is not None and results[k].identity == identity
                   for k in range(i - REUSE_MIN_GAP, i + REUSE_MIN_GAP + 1)
                   if k != i and 0 <= k < len(results))

    filled = 0
    for i in order:
        if results[i] is not None:
            continue
        job = by_index[i]
        subject = job.get("subject") or ""
        person = job.get("subject_type") == "person"
        # Nearest donors first; a donor is any scene that has media.
        donors = sorted((k for k in order if k != i and results[k] is not None),
                        key=lambda k: abs(k - i))
        pick = None
        for k in donors:                       # 1. the same subject
            if same_subject(subject, by_index[k].get("subject") or "") \
                    and not placed_near(results[k].identity, i):
                pick = k
                break
        if pick is None:                       # 2. a nearby scene, never another person
            for k in donors:
                other = by_index[k]
                if other.get("subject_type") == "person" and not same_subject(
                        subject, other.get("subject") or ""):
                    continue
                if person and results[k].kind == "image":
                    continue
                if not placed_near(results[k].identity, i):
                    pick = k
                    break
        if pick is None:                       # 3. the same subject, closer in, never adjacent
            same = [k for k in donors if abs(k - i) >= 2
                    and same_subject(subject, by_index[k].get("subject") or "")]
            pick = same[-1] if same else None   # farthest of them
        if pick is None:
            continue
        donor = results[pick]
        results[i] = _dc_replace(
            donor, review_required=True,
            review_reason=(f"Reused shot of {by_index[pick].get('subject') or 'another scene'}"
                           " - no other footage found for this line"))
        filled += 1
    return filled


# --------------------------------------------------------------------------- #
# Sequence pools - source a run of lines together, as an editor does
# --------------------------------------------------------------------------- #

# Shots cut from one downloaded window of a video, and the most videos and
# photos a sequence gathers. One window replaces up to three separate
# searches + scouts + downloads + vision checks, and consecutive shots from it
# play as one continuous moment across consecutive lines.
SEQ_SHOTS_PER_WINDOW = 1   # never the same video twice
# One shot per video now (no repeats), so a section needs as many videos as
# it has lines: 4 left 6 of every 10 lines to the slow one-by-one search.
SEQ_MAX_VIDEOS = 10
SEQ_MAX_IMAGES = 6
SEQ_SHOT_PAD = 0.5
# Footage searches per sequence run concurrently (see source_sequence).
SEQ_PARALLEL_SEARCHES = 3


def _cut(src: str, out: str, start: float, seconds: float) -> str:
    """Re-encode [start, start+seconds) of src to its own file; "" on failure."""
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", src,
                        "-t", f"{seconds:.2f}", "-an", "-c:v", "libx264", "-preset",
                        "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", out],
                       capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""


def split_window(path: str, key: str, lengths: List[float], out_dir: str) -> List[tuple]:
    """(file, offset) for consecutive shots of the given lengths cut from one window."""
    shots, t = [], 0.0
    for n, secs in enumerate(lengths):
        out = os.path.join(out_dir, f"seq_{key}_{n}.mp4")
        got = _cut(path, out, t, secs)
        if not got:
            break
        shots.append((got, t))
        t += secs
    return shots


def _footage_pool(query: str, need: int, lengths: List[float], intent: str,
                  context: str, used: set, out_dir: str, require_cc: bool,
                  tag: str) -> List[dict]:
    """Shots for a sequence from one footage search: windows cut into several shots."""
    per = max(1, min(SEQ_SHOTS_PER_WINDOW, need))
    window = sum(lengths[:per]) + 1.0
    if require_cc:
        target = ("https://www.youtube.com/results?search_query="
                  + urllib.parse.quote_plus(query) + "&sp=EgIwAQ%3D%3D")
    else:
        target = f"ytsearch20:{query}"  # no-repeats across long videos needs depth
    cands = _yt_candidates_cached(target, require_cc, "", variant=f"seq:{query}")
    eligible = [c for c in sorted(cands, key=lambda c: _score_candidate(
                    c["title"], c["duration"], c["aspect"], window), reverse=True)
                if not _talking_head(c["title"])
                and not _stock_seller(c["title"], c.get("channel", ""))
                and not (c["aspect"] and c["aspect"] < 1.2)
                and not (c["duration"] and c["duration"] < window + 10)
                and f"yt:{c['id']}" not in used]
    shots: List[dict] = []
    videos = 0
    for cand, start, _moment in _plan_grabs(eligible, window, 30.0, intent, context):
        if len(shots) >= need or videos >= SEQ_MAX_VIDEOS:
            break
        path = _yt_fetch_retry(cand["id"], out_dir, start, window, cand["title"])
        if not path:
            continue
        if has_burned_captions(path):
            continue
        keep, verdict = _vision_gate(path, intent, context, cand["title"])
        if not keep:
            continue
        videos += 1
        for n, (shot_path, offset) in enumerate(
                split_window(path, f"{tag}_{cand['id']}", lengths[:per], out_dir)):
            asset = MediaAsset(
                kind="video", source="youtube",
                url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(start + offset)}",
                local_path=shot_path, duration=lengths[n],
                attribution=f"YouTube: {cand['title']}",
                license=("Creative Commons Attribution (CC BY)" if require_cc
                         else "unverified — you must hold the rights"),
                query=query, review_required=not require_cc,
                review_reason=("" if require_cc
                               else "Licence unverified — confirm you hold the rights"),
            ).apply_verdict(verdict, intent)
            shots.append({"kind": "footage", "video": cand["id"], "asset": asset})
    return shots


def _image_pool(queries: List[str], subject: str, subject_type: str, need: int,
                intent: str, context: str, used: set, out_dir: str) -> List[dict]:
    """Real photos for a sequence: the subject's own Wikipedia article, then searches."""
    found: List[MediaAsset] = []
    if subject and subject_type in ("person", "place", "event"):
        found += _cached_search(search_wikipedia_article_images, subject)
    for q in queries:
        for search in (search_wikimedia, search_web_images, search_openverse):
            found += _cached_search(search, q)
    shots, seen = [], set()
    for cand in found:
        if len(shots) >= need:
            break
        if cand.identity in seen or cand.identity in used:
            continue
        seen.add(cand.identity)
        got = _download(_dc_replace(cand), cand.query or subject, out_dir)
        if not got:
            continue
        keep, verdict = _vision_gate(got.local_path, intent, context,
                                     got.attribution or got.url)
        if keep:
            shots.append({"kind": "image", "video": "", "asset": got.apply_verdict(verdict, intent)})
    return shots


def greedy_assign(beats: List[dict], shots: List[dict],
                  chosen: Optional[Dict[int, str]] = None) -> Dict[int, str]:
    """
    Lay beats out in order, each taking the best unused shot of its wanted
    kind, else the best unused shot of any kind. Keeps what `chosen` already has.
    """
    chosen = dict(chosen or {})
    taken = set(chosen.values())
    free = sorted((s for s in shots if s["id"] not in taken),
                  key=lambda s: -(s.get("score") if s.get("score") is not None else 0.5))
    for b in beats:
        if b["index"] in chosen or not free:
            continue
        want = b.get("want") or "footage"
        pick = next((s for s in free if s["kind"] == want), free[0])
        chosen[b["index"]] = pick["id"]
        free.remove(pick)
    return chosen


def source_sequence(seq: dict, jobs: Dict[int, Dict[str, Any]], work_dir: str,
                    used: set, claim: threading.Lock, assign=None,
                    require_cc: bool = None, allow_youtube: bool = None,
                    tag: str = "0") -> Dict[int, MediaAsset]:
    """
    Gather one pool of shots for a sequence and lay its lines out across it.

    Returns beat index -> asset for the beats it could fill; the caller
    sources the rest one by one. Footage searches download a window per video
    and cut it into several shots; image searches (and the subject's own
    Wikipedia article) supply real photos. Each window or photo is judged by
    the vision model once, against the sequence's setting, then `assign`
    (the director's editor call) or the greedy fallback gives every line the
    shot that best shows it.
    """
    require_cc = config.REQUIRE_CC if require_cc is None else require_cc
    allow_youtube = config.ALLOW_YOUTUBE if allow_youtube is None else allow_youtube
    beats = [jobs[i] for i in seq.get("beats", []) if i in jobs]
    if not beats or (config.REQUIRE_AI and vision.ai_exhausted()):
        return {}
    subject = seq.get("subject") or beats[0].get("subject") or ""
    subject_type = seq.get("subjectType") or beats[0].get("subject_type") or ""
    intent = seq.get("setting") or subject or beats[0].get("intent") or ""
    context = " ".join(b.get("context", "") for b in beats)[:600]
    lengths = [float(b.get("seconds") or 3.0) + SEQ_SHOT_PAD for b in beats]
    n_img = sum(1 for b in beats if b.get("visual_type") == "image")
    n_foot = len(beats) - n_img

    token = _SUBJECT_TYPE.set(subject_type)
    window_token = _EVENT_WINDOW.set(beats[0].get("event_window") or "")
    pool: List[dict] = []
    try:
        foot = [s["q"] for s in seq.get("searches", []) if s.get("kind") != "image"]
        imgs = [s["q"] for s in seq.get("searches", []) if s.get("kind") == "image"]
        # Spare footage for photo lines that find no photo, and vice versa.
        need_foot = n_foot + (n_img + 1) // 2
        need_img = min(SEQ_MAX_IMAGES, n_img + (1 if n_foot else 0))
        # The first searches and the photo search run AT THE SAME TIME. Run
        # one after another they made each sequence wait on every download
        # and vision check in turn (a 23-line job spent ~6 minutes here).
        # Each task gets its own copy of this thread's context: the subject
        # type and event window are context variables, and a pool thread
        # does not inherit them.
        first = foot[:SEQ_PARALLEL_SEARCHES] if allow_youtube else []
        rest = foot[SEQ_PARALLEL_SEARCHES:] if allow_youtube else []
        with ThreadPoolExecutor(max_workers=len(first) + 1) as ex:
            img_fut = (ex.submit(contextvars.copy_context().run, _image_pool, imgs, subject,
                                 subject_type, need_img, intent, context, used, work_dir)
                       if need_img else None)
            share = [need_foot] + [max(1, (need_foot + 1) // 2)] * (len(first) - 1)
            foot_futs = [ex.submit(contextvars.copy_context().run, _footage_pool, q, share[n],
                                   lengths, intent, context, used, work_dir, require_cc,
                                   f"{tag}_p{n}")
                         for n, q in enumerate(first)]
            for fut in foot_futs:
                have = sum(1 for x in pool if x["kind"] == "footage")
                # Concurrent searches can land on the same video; the earlier
                # search keeps it (one window, several shots is by design).
                taken = {x.get("video") for x in pool if x.get("video")}
                got = [x for x in (fut.result() or []) if not x.get("video") or x["video"] not in taken]
                pool += got[:max(0, need_foot - have)]
            for q in rest:
                have = sum(1 for x in pool if x["kind"] == "footage")
                if have >= need_foot:
                    break
                pool += _footage_pool(q, need_foot - have, lengths, intent, context,
                                      used, work_dir, require_cc, f"{tag}_{len(pool)}")
            if img_fut is not None:
                pool += img_fut.result() or []
    finally:
        _EVENT_WINDOW.reset(window_token)
        _SUBJECT_TYPE.reset(token)
    if not pool:
        return {}

    for n, p in enumerate(pool):
        p["id"] = f"s{n}"
    shots = [{"id": p["id"], "kind": p["kind"], "video": p["video"],
              "description": p["asset"].content_description,
              "score": p["asset"].relevance_score} for p in pool]
    lines = [{"index": b["index"], "text": b.get("context", ""),
              "want": "image" if b.get("visual_type") == "image" else "footage"} for b in beats]
    try:
        chosen = assign(lines, shots) if assign else greedy_assign(lines, shots)
    except Exception as e:  # noqa: BLE001
        print(f"[media] sequence layout failed, using greedy: {e}", flush=True)
        chosen = greedy_assign(lines, shots)
    by_id = {p["id"]: p["asset"] for p in pool}
    out: Dict[int, MediaAsset] = {}
    with claim:
        for idx, sid in chosen.items():
            asset = by_id.get(sid)
            if asset is None or asset.identity in used:
                continue
            asset = _dc_replace(asset, intent=jobs[idx].get("intent") or asset.intent)
            used.add(asset.identity)
            out[idx] = asset
    return out
