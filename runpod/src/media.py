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
from dataclasses import dataclass, asdict, field, replace as _dc_replace
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

from . import candidates, config, costs, events, intent, moments, providers, proxies, vision
from . import imagefix as _imagefix
from . import localvision as _localvision
from .errors import RETRY, FailureClass, classify_exception, classify_ytdlp, from_reason
from .storage import download


# Split out in Phase F: pixel/file checks and the yt-dlp primitives live in
# their own modules; the names stay importable from here.
from .filters import (  # noqa: F401
    _STILL_EXTS, _is_still, _video_seconds, _gray_frames, has_burned_captions, _texty_rows, _longest_run, playable_video, clip_quality, _video_dims, _blurry, _corner_watermark, _PTS_RE, scene_cuts, clean_window, trim_clip, tidy_clip)
from .ytdlp import (  # noqa: F401
    _PROXIES, PROXY_MANAGER, _UNAVAILABLE_VIDEOS, _DENIED_ON, _FAIL_LOCK, _LAST_FAILURE, _NET_SEM, _next_proxy, _acquire_proxy, _release_proxy, _proxy_index, proxy_snapshot, _note_failure, _video_unavailable, pot_provider_alive, pot_provider_log, probe_youtube, _bench_proxy, _yt_network_args, BLOCK_SIGNS, BOT_CHECK, looks_blocked, _YT_THIS_YEAR, _yt_candidates, _yt_info, _yt_fetch)
from . import ytdlp as _ytdlp  # noqa: F401
from . import filters as _filters  # noqa: F401

# "" is the worker's own address. Proxies are only worth it while YouTube has
# not flagged them; when it has (2026-09-25: every proxy answered "Sign in to
# confirm you're not a bot" to downloads while searches still worked), the
# machine's own IP may be the better route. YTDLP_DIRECT=1 adds it.
if config.YTDLP_DIRECT and "" not in _PROXIES:
    _PROXIES.insert(0, "")



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
    # The vision judge's class of the frames against the scene intent: event,
    # location, generic, or "" when not judged.
    specificity: str = ""
    # Runner-up clips that also passed the judge (id, url, scores and
    # description, never the files), for Replace Clip.
    alternatives: List[dict] = field(default_factory=list)
    # The combined score that chose this clip over the others that passed
    # (src/candidates.py), its parts, and a summary of the pool it came from.
    final_score: Optional[float] = None
    score_parts: Dict[str, float] = field(default_factory=dict)
    pool: Dict[str, Any] = field(default_factory=dict)
    # Where in the source the clip was cut and how that was decided: start,
    # coarse or fine storyboard score, whether the cut window was free of
    # shot changes (src/moments.py, clean_window below).
    moment: Dict[str, Any] = field(default_factory=dict)

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
            self.specificity = verdict.get("specificity", "") or ""
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

# Bright Data's SERP zone answers some calls with a page that is not JSON.
# Measured locally that was 2 in 9; on the worker, ten fan-out parts firing
# searches at once got 212 of them in one job. So: a few at a time per
# worker, and up to three tries with a pause between.
_SERP_SLOTS = threading.BoundedSemaphore(max(1, int(os.getenv("SERP_CONCURRENCY", "3"))))


# Set when Bright Data refuses the account (no credit, key revoked): every later
# search skips it - images go straight to DuckDuckGo - instead of paying a
# failed request (and its retries) per search.
_BRIGHTDATA_REFUSED = {"why": ""}
_REFUSAL_WORDS = ("balance", "credit", "payment", "insufficient", "suspended", "billing")


def brightdata_available() -> bool:
    return bool(config.BRIGHTDATA_API_KEY and config.BRIGHTDATA_SERP_ZONE and not _BRIGHTDATA_REFUSED["why"])


def _brightdata_serp(google_url: str, timeout: int = 150) -> dict:
    """The parsed JSON Bright Data returns for one Google results URL (raises on failure)."""
    if _BRIGHTDATA_REFUSED["why"]:
        raise ValueError(f"Bright Data off for this worker: {_BRIGHTDATA_REFUSED['why']}")
    last = ""
    for attempt in range(2):
        if attempt:
            costs.record("serp.call")
            time.sleep(2.0)
        try:
            with _SERP_SLOTS:
                r = requests.post(
                    "https://api.brightdata.com/request",
                    headers={"Authorization": f"Bearer {config.BRIGHTDATA_API_KEY}",
                             "Content-Type": "application/json"},
                    json={"zone": config.BRIGHTDATA_SERP_ZONE, "format": "raw", "url": google_url},
                    timeout=timeout)
        except requests.RequestException as e:
            last = type(e).__name__
            continue
        text = r.text if isinstance(getattr(r, "text", ""), str) else ""
        refusal = r.status_code in (401, 402, 403) or (
            r.status_code >= 400 and any(w in text.lower()[:400] for w in _REFUSAL_WORDS))
        if refusal:
            _BRIGHTDATA_REFUSED["why"] = f"HTTP {r.status_code}"
            print(f"[media] Bright Data refused the account (HTTP {r.status_code}); "
                  "image search falls back to DuckDuckGo for the rest of this worker", flush=True)
            raise ValueError(f"Bright Data SERP refused: HTTP {r.status_code}")
        if "throttled" in text[:300].lower():
            # "The request was auto-throttled due to low success rate": it will
            # not get better within this job.
            _brightdata_off("throttled")
            raise ValueError("Bright Data SERP: throttled")
        if r.status_code == 429 or r.status_code >= 500:
            last = f"HTTP {r.status_code}"
            continue
        r.raise_for_status()
        try:
            body = r.json()
        except ValueError:
            last = f"not JSON: {text[:100]!r}"
            continue
        if isinstance(body, dict):
            with _CACHE_LOCK:
                _BRIGHTDATA_FAILS["n"] = 0
            return body
        last = f"unexpected {type(body).__name__}"
    with _CACHE_LOCK:
        _BRIGHTDATA_FAILS["n"] += 1
        failing = _BRIGHTDATA_FAILS["n"] >= 3
    if failing:
        _brightdata_off(f"3 calls in a row failed ({last})")
    raise ValueError(f"Bright Data SERP: {last}")


# Consecutive failed SERP calls. Throttled or empty answers used to be retried
# three times per search (up to 150 s each) all job long, behind a two-slot
# semaphore: clip finding queued on a service that had stopped working.
_BRIGHTDATA_FAILS = {"n": 0}


def _brightdata_off(why: str) -> None:
    if not _BRIGHTDATA_REFUSED["why"]:
        _BRIGHTDATA_REFUSED["why"] = why
        print(f"[media] Bright Data off for the rest of this job: {why}", flush=True)


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
    if brightdata_available():
        # Google Images through Bright Data's SERP API: 100 results per call
        # with the full-size original (press photos: NOAA, TIME, NASA...).
        # Billed per successful search, not per image.
        costs.record("serp.call")
        try:
            body = _brightdata_serp("https://www.google.com/search?tbm=isch&brd_json=1&q="
                                    + urllib.parse.quote_plus(query), timeout=90)
            for it in (body.get("images") or [])[:limit * 3]:
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
            # The free searches came back empty: SerpApi's Google Images
            # (quota-limited, so only here).
            rows = _serpapi_images("google_images", query)
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


_YANDEX_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# SerpApi searches spent by this job (the plan's monthly quota is small).
_SERPAPI_USED = {"n": 0}
# Social-network crawler links SerpApi's Google Images returns: short-lived,
# login-walled, usually a post with text on it - never worth a download.
_SERPAPI_SKIP_HOSTS = ("lookaside.fbsbx.com", "lookaside.instagram.com")


def _serpapi_images(engine: str, query: str) -> List[tuple]:
    """(url, width, height, title, page) rows from SerpApi's google_images or
    yandex_images engine, or [] when unconfigured, over this job's quota, or
    failing. Each call is one search against the monthly plan."""
    if not config.SERPAPI_API_KEY or not query.strip():
        return []
    with _CACHE_LOCK:
        if _SERPAPI_USED["n"] >= config.SERPAPI_MAX_PER_JOB:
            return []
        _SERPAPI_USED["n"] += 1
    params = {"engine": engine, "api_key": config.SERPAPI_API_KEY}
    params["text" if engine == "yandex_images" else "q"] = query
    try:
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=45)
        r.raise_for_status()
        rows = []
        for it in (r.json().get("images_results") or []):
            url = it.get("original") or ""
            if not url.startswith("http") or any(h in url for h in _SERPAPI_SKIP_HOSTS):
                continue
            rows.append((url, it.get("original_width") or 0, it.get("original_height") or 0,
                         it.get("title") or "", it.get("link") or it.get("source") or ""))
        costs.record("serpapi.search")
        return rows
    except (requests.RequestException, ValueError) as e:
        _source_error(f"serpapi_{engine}", e)
        return []


def search_yandex_images(query: str, limit: int = 8) -> List[MediaAsset]:
    """
    Full-size photos from Yandex Images - GoMotion's picture source, strong on
    local news photos (a "Long Beach Island flooding" search returns the
    stations' own pictures). Keyless: the results page carries each original
    as an img_url parameter. Asked directly first, then through the proxy pool
    when a datacenter address gets a captcha instead of results.
    """
    if not config.ALLOW_YANDEX_IMAGES or not query.strip():
        return []
    headers = {"User-Agent": _YANDEX_UA, "Accept-Language": "en-US,en;q=0.9"}
    params = {"text": query, "isize": "large"}
    found: List[str] = []
    proxy = _next_proxy()
    for via in ([None, proxy] if proxy else [None]):
        try:
            r = requests.get("https://yandex.com/images/search", params=params, headers=headers,
                             timeout=20, proxies={"http": via, "https": via} if via else None)
        except requests.RequestException as e:
            _source_error("yandex_images", e)
            continue
        text = r.text.replace("\\u002F", "/")
        if "captcha" in (r.url or "") or "SmartCaptcha" in text:
            _source_error("yandex_images", RuntimeError("captcha"))
            continue
        found = [urllib.parse.unquote(u) for u in re.findall(r"img_url=(https?%3A[^&\"']+)", text)]
        found += re.findall(r'"origUrl":"(https?:[^"]+)"', text)
        if found:
            break
    if not found:
        # Yandex answered with a captcha on every route: SerpApi's Yandex engine.
        found = [row[0] for row in _serpapi_images("yandex_images", query)]
    import html as _html
    out, seen = [], set()
    for url in found:
        url = _html.unescape(url)
        if url in seen or not url.startswith("http"):
            continue
        seen.add(url)
        # Stock sellers' watermarked comps never make a cut.
        host = urllib.parse.urlparse(url).netloc.lower()
        if any(s in host for s in ("alamy", "gettyimages", "shutterstock", "istockphoto", "dreamstime",
                                   "depositphotos", "123rf", "adobe")):
            continue
        out.append(MediaAsset(
            kind="image", source="yandex_image", url=url,
            attribution=f"Yandex image result — {host}"[:300],
            license="unverified — web image, confirm you hold the rights",
            query=query, review_required=True, review_reason="Web image: licence unverified"))
        if len(out) >= limit:
            break
    costs.record("yandex.search")
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


# The image account answered "credits insufficient" in this job.
_IMAGE_NO_CREDIT = {"hit": False}


def _ai_on_kie() -> bool:
    """True when vision or the director uses the Kie account."""
    return "kie.ai" in (config.VISION_API_BASE or "") + (config.DIRECTOR_API_BASE or "")


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
                _IMAGE_NO_CREDIT["hit"] = True
                # The same empty account behind vision/the director stops them
                # too; an image account alone must not (vision on Google kept
                # working while Kie was at -3.25).
                if _ai_on_kie():
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
    if "kie.ai" in config.IMAGE_API_BASE and (_IMAGE_NO_CREDIT["hit"] or (_ai_on_kie() and vision.out_of_credits())):
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


# Set by source_for_segment for the scene being sourced; read by the vision
# gate deep in the call chain. A context variable rather than a parameter
# threaded through every source function: each scene is sourced on one
# thread, start to finish, so it cannot leak into another scene.
_SUBJECT_TYPE: contextvars.ContextVar = contextvars.ContextVar("subject_type", default="")
# A job's allow-list of provider names (src/providers.py), or None for all.
_ENABLED_PROVIDERS: contextvars.ContextVar = contextvars.ContextVar("enabled_providers", default=None)

# Set while sourcing a beat of a news/weather/disaster story (from the
# director's story brief): "event", or "year" when the event is this year's.
# News-outlet uploads - the main source of real event footage - are then no
# longer rejected on the word "news", and for "year" searches try this year's
# uploads first so a 2026 flood does not get 2019's.
_EVENT_WINDOW: contextvars.ContextVar = contextvars.ContextVar("event_window", default="")
# The typed scene intent (src/intent.py) of the scene being sourced, and a
# per-scene count of clips judged, so the expanded searches cannot spend
# without limit.
_SCENE_INTENT: contextvars.ContextVar = contextvars.ContextVar("scene_intent", default=None)
# One vision budget per scene: every model call made for it (scouting a
# storyboard, the fine pass, judging a download) counts, across all of the
# scene's fallback searches. Before this only judgements counted, so a hard
# scene spent 30-40 calls re-scouting the same videos for every fallback.
_SCENE_JUDGED: contextvars.ContextVar = contextvars.ContextVar("scene_judged", default=None)
# Videos this scene has already scouted or downloaded, across its fallback
# searches: the next search only brings NEW candidates.
_SCENE_TRIED: contextvars.ContextVar = contextvars.ContextVar("scene_tried", default=None)
# Storyboard picks memoised per (video, intent) for the job, and the videos
# some scene is downloading right now, so parallel scenes stop converging on
# the same top-ranked candidate.
_SCOUT_MEMO: Dict[str, Optional[dict]] = {}
_INFLIGHT: set = set()
_SCENE_LOCK = threading.Lock()
# Replace Clip keeps the runner-up files so they can be published as choices.
_KEEP_ALT_FILES: contextvars.ContextVar = contextvars.ContextVar("keep_alt_files", default=False)



# Stock libraries upload watermarked previews to YouTube (ZapataStock,
# FootageForPro... filled a real video with logo-stamped dolphins and
# Statues of Liberty). Their titles and channel names give them away.
_STOCK_SELLER = re.compile(
    r"stock (?:footage|video|clip)|footage ?for ?pro|zapata|pond5|storyblocks|"
    r"shutterstock|videoblocks|videohive|envato|artgrid|artlist|motion ?array|"
    r"getty ?images|istock|adobe ?stock|dissolve|filmsupply|framepool|"
    r"christoryman|royalty[- ]free|free (?:stock|footage)|no copyright",
    re.IGNORECASE)


def _usable_title(title: str, channel: str = "", aspect: float = 0.0) -> bool:
    """
    The one title-and-shape check every source applies before spending
    anything: not a stock seller's listing, not a talking head, not
    vertical. It was written five times with small drifts between them.
    """
    if _stock_seller(title or "", channel or ""):
        return False
    if _talking_head(title or ""):
        return False
    if aspect and aspect < 1.2 and not config.ALLOW_VERTICAL:
        return False                        # vertical, unusable in 16:9
    return True


def _stock_seller(*texts: str) -> bool:
    return any(t and _STOCK_SELLER.search(t) for t in texts)


_NEWS_WORDS = {"news", "interview", "press conference", "briefing"}


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
    if config.NEWS_FOOTAGE:
        # News reports, interviews and press conferences are what GoMotion
        # shows for the event a line names; the judge still rejects an anchor
        # at a studio desk on the actual frames.
        hits = [h for h in hits if h not in _NEWS_WORDS]
    return bool(hits)


# Candidates kept (n) or dropped (rejected) on their title alone because no
# vision model could judge them.
UNJUDGED_KEPT = {"n": 0, "rejected": 0}
_GENERIC_TITLE_WORDS = set("""footage video videos clip clips stock aerial aerials drone drones view views shot
shots cinematic 4k hd uhd 8k broll b-roll film filmed scenery landscape landscapes beautiful amazing relaxing music
ambient timelapse lapse slow motion best top new official full part episode story documentary the and for with from
into over under near about this that these those what when where which who how why its their his her our your
you are was were been being has have had not but all any one two three""".split())


def _salient_words(text: str) -> set:
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text or ""):
        w = w.lower().strip("'-")
        if w in _GENERIC_TITLE_WORDS:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def _title_fits(title: str, intent_text: str) -> bool:
    """Does a candidate's title name what the line is about? The scene's typed
    entities and places decide when there are any (one of them plus one more
    hit), else the intent's own words (two of them, one when it has only two)."""
    si = _SCENE_INTENT.get()
    if si:
        ents, locs, subj = intent.SceneIntent.from_dict(si).title_match(title)
        if ents + locs >= 1 and ents + locs + subj >= 2:
            return True
    want = _salient_words(intent_text)
    if not want:
        return False
    hits = len(want & _salient_words(title))
    return hits >= (2 if len(want) >= 3 else 1)


def _image_label(asset) -> str:
    """What a picture is called, for the title check when no model can judge it:
    its file or page name ("Glen Canyon Dam 1964.jpg") and any caption, not only
    the credit line ("Tuxyso", "C. S. Fly"), which names nothing in the picture."""
    name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(asset.url or "").path))
    name = re.sub(r"^\d+px-", "", os.path.splitext(name)[0]).replace("_", " ").replace("-", " ")
    parts = [name, asset.attribution or "", asset.content_description or ""]
    return " | ".join(p for p in parts if p)[:300]


# Candidates the local CLIP pass rejected before any remote call.
LOCAL_REJECTED = {"n": 0}


def _local_check(path: str, intent_text: str) -> Optional[dict]:
    """The local model's verdict for this scene's candidate, or None when the
    model is not installed (tests, a laptop without /opt/models)."""
    if not config.LOCAL_VISION_ENABLED or not _localvision.available():
        return None
    si = _SCENE_INTENT.get() or {}
    wants = ""
    if isinstance(si, dict):
        v = str(si.get("visualType") or si.get("visual_type") or "").lower()
        if v in ("map", "chart", "document"):
            wants = v
    return _localvision.check(path, intent_text, subject_type=_SUBJECT_TYPE.get() or "",
                              subject=str((si or {}).get("subject") or "") if isinstance(si, dict) else "",
                              wants=wants)


def _local_keep(local: dict, label: str, intent_text: str, why: str) -> bool:
    """Keep/reject from the local verdict when no remote model answered:
    close enough to the line, or named after it and not far off."""
    floor = config.LOCAL_VISION_MIN_RELEVANCE
    rel = float(local.get("relevance") or 0.0)
    keep = rel >= floor or (rel >= floor - 0.035 and _title_fits(label, intent_text))
    with _CACHE_LOCK:
        UNJUDGED_KEPT["n" if keep else "rejected"] += 1
        _localvision.STATS["decided"] += 1
    print(f"[vision] no verdict ({why}): {'keep' if keep else 'REJECT'} by local check "
          f"(relevance {rel:.3f}, {local.get('kind')}) {label[:50]!r}", flush=True)
    return keep


def _rescue_local_ok(path: str, intent_text: str) -> bool:
    """The last-pass fill has no remote check; the local one still keeps out
    slides, cartoons, logos and clearly off-topic frames."""
    local = _local_check(path, intent_text) if intent_text else None
    if local is None:
        return True
    return not local["reject"] and local["relevance"] >= config.LOCAL_VISION_MIN_RELEVANCE - 0.035


def _vision_gate(path: str, intent: str, context: str, label: str) -> tuple:
    """
    (keep, verdict) for a downloaded candidate.

    No intent means nothing to judge against, and an unreachable model returns
    None — both keep the candidate, so vision can only ever remove bad clips,
    never empty a timeline because an API is down.
    """
    if not intent:
        return True, None
    # The local CLIP pass first: the wrong KIND of picture (slide, text page,
    # cartoon, logo, a portrait on a place line) never costs a Gemini call.
    local = _local_check(path, intent)
    if local is not None and local["reject"]:
        with _CACHE_LOCK:
            LOCAL_REJECTED["n"] += 1
        print(f"[vision] REJECT locally: {local['reject']} {label[:50]!r}", flush=True)
        return False, None
    if not vision.enabled():
        if local is not None:
            return _local_keep(local, label, intent, "no remote model"), None
        return True, None
    scene = _SCENE_INTENT.get()
    verdict = vision.judge(path, intent, context, event=bool(_EVENT_WINDOW.get()),
                           **({"scene": scene} if scene else {}))
    if verdict is None and not config.ACCEPT_UNJUDGED:
        # Every model failed on this clip. Google answered "high demand" for
        # half an hour on 2026-09-29 and rejecting all of those left most of a
        # 22-minute video empty (then filled with repeats). The local model
        # decides now; without it, the title: a video named after what the
        # line is about stays, anything else goes.
        if local is not None:
            return _local_keep(local, label, intent, "models busy"), None
        keep = _title_fits(label, intent)
        with _CACHE_LOCK:
            UNJUDGED_KEPT["n" if keep else "rejected"] += 1
        print(f"[vision] no verdict (models busy): {'keep' if keep else 'REJECT'} by title {label[:60]!r}",
              flush=True)
        return keep, None
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
        # Vertical; object-fit would crop it to nothing. News-compilation
        # styles frame it on a blurred fill instead (upscale.frame_vertical),
        # so there it only ranks a little behind landscape video.
        score -= 1.0 if config.ALLOW_VERTICAL else 5.0
    elif aspect and aspect >= 1.7:
        score += 1.0
    # The typed intent: a title that names the entity, the place or what the
    # frames must contain ranks ahead of one that merely shares a word. An
    # event scene demotes a title that names neither the entity nor the place.
    si = _SCENE_INTENT.get()
    if si:
        ents, locs, subj = intent.SceneIntent.from_dict(si).title_match(title)
        score += 2.0 * min(ents, 2) + 1.5 * min(locs, 2) + 1.0 * min(subj, 2)
        if si.get("specificity") == "event" and not (ents or locs):
            score -= 3.0
    return score


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


_GOOGLE_VIDEO_CACHE: Dict[str, List[dict]] = {}


def search_google_videos(query: str, limit: int = 10) -> List[dict]:
    """
    Google's video search (Bright Data SERP zone): [{url, title, site, seconds}].

    A second finder beside yt-dlp's own search: on "Lake Mead drought aerial
    footage" it returned 8 YouTube videos the flat search had not, plus
    TikTok/Facebook clips. One paid call per distinct query, cached per job.
    """
    if not (brightdata_available() and query.strip()):
        return []
    key = query.strip().lower()
    with _CACHE_LOCK:
        if key in _GOOGLE_VIDEO_CACHE:
            return _GOOGLE_VIDEO_CACHE[key]
    rows: List[dict] = []
    costs.record("serp.call")
    try:
        body = _brightdata_serp("https://www.google.com/search?tbm=vid&brd_json=1&q="
                                + urllib.parse.quote_plus(query))
        for it in (body.get("organic") or [])[:limit]:
            url = it.get("link") or ""
            if not url.startswith("http"):
                continue
            secs = it.get("duration_sec")
            if not secs and it.get("duration"):
                parts = [int(p) for p in re.findall(r"\d+", str(it["duration"]))]
                secs = sum(p * 60 ** i for i, p in enumerate(reversed(parts))) if parts else 0
            rows.append({"url": url, "title": (it.get("title") or "")[:200],
                         "site": urllib.parse.urlparse(url).netloc.replace("www.", ""),
                         "seconds": float(secs or 0)})
    except (requests.RequestException, ValueError) as e:
        _source_error("search_google_videos", e)
        rows = []
    with _CACHE_LOCK:
        _GOOGLE_VIDEO_CACHE[key] = rows
    return rows


def _google_youtube_candidates(query: str) -> List[dict]:
    """YouTube videos Google finds for the query, shaped like _yt_candidates rows."""
    out = []
    for row in search_google_videos(query):
        m = re.search(r"youtube\.com/watch\?v=([\w-]{11})", row["url"])
        if not m:
            continue
        out.append({"id": m.group(1), "duration": row["seconds"], "aspect": 0.0,
                    "title": row["title"], "channel": "", "via": "google"})
    return out


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
    # Google finds YouTube videos yt-dlp's own search misses; they join the
    # list after the direct hits (never for a Creative-Commons-only search,
    # whose licence filter Google cannot apply).
    if not require_cc and target.startswith("ytsearch"):
        have = {c["id"] for c in found}
        found = found + [c for c in _google_youtube_candidates(target.split(":", 1)[-1])
                         if c["id"] not in have]
    if subject:
        with _CACHE_LOCK:
            _YT_CANDIDATES_CACHE[key] = found
    return found


def _fixed_point(candidate: dict, grab: float, start_at: float) -> float:
    """The old grab point: 35% in skips intros, clamped inside the video."""
    duration = candidate.get("duration") or 0
    point = max(5.0, duration * 0.35) if duration else start_at
    if duration:
        point = min(point, max(5.0, duration - grab - 2))
    return point


def _scene_tried() -> set:
    tried = _SCENE_TRIED.get()
    return tried if tried is not None else set()


def _vision_budget_left() -> int:
    counter = _SCENE_JUDGED.get()
    if counter is None:
        return config.JUDGE_MAX_PER_SCENE
    return max(0, config.JUDGE_MAX_PER_SCENE - counter[0])


def _claim_inflight(video_id: str, used: Optional[set]) -> bool:
    """Claim a video for this scene's download; False if another scene has it."""
    key = f"yt:{video_id}"
    with _SCENE_LOCK:
        if key in _INFLIGHT or (used and key in used):
            return False
        _INFLIGHT.add(key)
        return True


def _release_inflight(video_id: str) -> None:
    with _SCENE_LOCK:
        _INFLIGHT.discard(f"yt:{video_id}")


def _scout(candidate: dict, grab: float, intent: str, context: str) -> Optional[dict]:
    """Storyboard moment for one candidate video, or None if unavailable."""
    memo_key = _scout_memo_key(candidate["id"], grab, intent)
    with _SCENE_LOCK:
        if memo_key in _SCOUT_MEMO:
            return _SCOUT_MEMO[memo_key]
    info, proxy = _yt_info(candidate["id"])
    if not info:
        return None
    w, h = info.get("width") or 0, info.get("height") or 0
    if w and h and w / h < 1.2 and not config.ALLOW_VERTICAL:
        # Vertical. The flat search cannot see this; a zero score drops it
        # before anything is downloaded.
        got = {"start": 0.0, "score": 0.0, "description": "vertical video", "tile": 0}
    else:
        got = moments.pick(info, intent, context, grab, proxy)
    with _SCENE_LOCK:
        _SCOUT_MEMO[memo_key] = got
    return got


def _scout_memo_key(video_id: str, grab: float, intent: str) -> str:
    return f"{video_id}|{round(grab)}|{(intent or '')[:120]}"


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
    attempts = 0
    while True:
        if _ytdlp.past_deadline():
            return ""
        path = _yt_fetch(video_id, out_dir, start_at, seconds)
        if path:
            return path
        cls, _proxy = _LAST_FAILURE.get() or (FailureClass.UNKNOWN, "")
        policy = RETRY.get(cls, RETRY[FailureClass.UNKNOWN])
        attempts += 1
        if cls == FailureClass.MEDIA_UNAVAILABLE:
            print(f"[media] not retrying {title[:50] or video_id}: the video is unavailable", flush=True)
            return ""
        if attempts > policy["retries"] or attempts >= 4:
            print(f"[media] giving up on {title[:50] or video_id} after {attempts} "
                  f"attempt(s): {cls.value}", flush=True)
            return ""
        if policy["backoff"]:
            time.sleep(policy["backoff"] * attempts)


def _scene_cap_reached() -> bool:
    counter = _SCENE_JUDGED.get()
    return counter is not None and counter[0] >= config.JUDGE_MAX_PER_SCENE


def _count_judged() -> None:
    counter = _SCENE_JUDGED.get()
    if counter is not None:
        counter[0] += 1


def _good_enough(passed: List[MediaAsset]) -> bool:
    """Stop judging: enough clips passed, or one is plainly excellent."""
    if len(passed) >= config.JUDGE_BEST_OF:
        return True
    return any((a.relevance_score or 0) >= config.EXCELLENT_SCORE for a in passed)


def _best_of(passed: List[MediaAsset]) -> Optional[MediaAsset]:
    """
    The strongest of the clips that passed; the others become its
    alternatives and their files go. Relevance leads, quality breaks ties.
    """
    if not passed:
        return None

    def rank(a: MediaAsset) -> float:
        # The combined score when the pool computed one; the judge's appeal
        # (relevance first, quality second) for clips found the old way.
        return a.final_score if a.final_score is not None else vision.appeal(a.relevance_score, a.quality)

    ranked = sorted(passed, key=rank, reverse=True)
    winner, losers = ranked[0], ranked[1:]
    keep_files = bool(_KEEP_ALT_FILES.get())
    for a in losers:
        entry = {
            "assetId": a.identity, "url": a.url, "title": (a.attribution or "")[:120],
            "score": a.relevance_score, "quality": a.quality, "finalScore": a.final_score,
            "specificity": a.specificity, "moment": dict(a.moment or {}),
            "description": (a.content_description or "")[:160], "source": a.source}
        if keep_files:
            entry["localPath"] = a.local_path
        winner.alternatives.append(entry)
        if keep_files:
            continue
        try:
            if a.local_path and os.path.exists(a.local_path):
                os.remove(a.local_path)
        except OSError:
            pass
    if losers:
        print(f"[media] best of {len(passed)}: {winner.relevance_score or 0:.2f} over "
              + ", ".join(f"{a.relevance_score or 0:.2f}" for a in losers), flush=True)
    return winner


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

    if config.CANDIDATE_POOL:
        return _youtube_pool(query_or_url, out_dir, seconds, start_at, require_cc, skip,
                             used, intent, context, subject, searches)

    judged = 0
    passed: List[MediaAsset] = []
    # Videos this call already downloaded or judged. The search variants
    # overlap heavily; before best-of-N the first pass returned at once, so a
    # repeat could not cost a second download and a second model call.
    tried: set = set()
    for search, variant, this_year in searches:
        if judged >= config.VISION_MAX_CANDIDATES or _scene_cap_reached() or _good_enough(passed):
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
            target = f"ytsearch{config.YT_SEARCH_RESULTS}:{search}"

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
            if candidate["id"] in tried:
                continue
            # A disqualifying title excludes the candidate outright. Scoring it
            # down is not enough: the loop still takes the best of what is left,
            # so when a query finds nothing good a penalised tutorial wins
            # anyway. That is how a Premiere Pro screen recording ended up in a
            # documentary. No clip is better than the wrong clip - the caller
            # falls through to the next query, and the timeline holds the
            # previous shot.
            if not _usable_title(candidate["title"], candidate.get("channel", ""), candidate["aspect"]):
                continue
            eligible.append(candidate)
        if not eligible:
            continue

        grab = max(2.0, seconds + 1.5)
        plan = _plan_grabs(eligible, grab, start_at, intent, context)

        for candidate, point, moment in plan:
            if judged >= config.VISION_MAX_CANDIDATES or _scene_cap_reached() or _good_enough(passed):
                break
            tried.add(candidate["id"])
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
            _count_judged()
            keep, verdict = _vision_gate(path, intent, context, candidate["title"])
            if not keep:
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            asset = _asset_for(path, query_or_url, grab, require_cc,
                               title=candidate["title"])
            # Not returned yet: the first clip to clear the floor is rarely the
            # best one available. Up to JUDGE_BEST_OF passing clips are compared.
            passed.append(asset.apply_verdict(verdict, intent))
    return _best_of(passed)


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
    for proxy in ("", _acquire_proxy("dailymotion.com")):
        cmd = base + (["--proxy", proxy] if proxy else [])
        started = time.time()
        try:
            with _NET_SEM:
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            if proxy:
                _release_proxy(proxy, False, FailureClass.NETWORK_TIMEOUT, started, "dailymotion.com")
            continue
        except FileNotFoundError:
            if proxy:
                _release_proxy(proxy, False, FailureClass.PROVIDER_UNAVAILABLE, started, "dailymotion.com")
            continue
        for line in (p.stdout or "").splitlines():
            line = line.strip()
            if line and os.path.exists(line):
                if proxy:
                    _release_proxy(proxy, True, None, started, "dailymotion.com")
                return line
        if proxy:
            _release_proxy(proxy, False, classify_ytdlp(p.stderr, p.returncode), started, "dailymotion.com")
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
        if not _usable_title(c["title"], c.get("channel", ""), c["aspect"]):
            continue
        if c["duration"] and c["duration"] < grab + 4:
            continue
        point = _fixed_point(c, grab, 10.0)
        margin = config.CUT_MARGIN_SECONDS if config.CLEAN_CUTS else 0.0
        path = _dm_fetch(c["id"], out_dir, max(0.0, point - margin), grab + 2 * margin)
        if path and margin:
            path = tidy_clip(path, grab, prefer=min(point, margin))[0]
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


_WEB_VIDEO_SKIP = ("youtube.com", "youtu.be", "dailymotion.com", "google.com")


def _web_fetch(url: str, out_dir: str, start_at: float, seconds: float, timeout: int = 240) -> str:
    """One section of a non-YouTube web video through yt-dlp; '' on failure."""
    out_tpl = os.path.join(out_dir, f"web_%(extractor)s_%(id)s_{int(start_at)}_{uuid.uuid4().hex[:6]}.%(ext)s")
    cmd = ["yt-dlp", url, "--download-sections", f"*{start_at:.1f}-{start_at + seconds:.1f}",
           "--force-keyframes-at-cuts", "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]/b",
           "--no-playlist", "--no-warnings", "--quiet", "--max-filesize", "300M",
           "--merge-output-format", "mp4", "-o", out_tpl, "--print", "after_move:filepath"]
    domain = (urllib.parse.urlparse(url).hostname or "web").removeprefix("www.")
    proxy = _acquire_proxy(domain)
    cmd += _yt_network_args(proxy)
    started = time.time()
    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        _release_proxy(proxy, False, FailureClass.NETWORK_TIMEOUT, started, domain)
        return ""
    except FileNotFoundError:
        _release_proxy(proxy, False, FailureClass.PROVIDER_UNAVAILABLE, started, domain)
        return ""
    if p.returncode != 0:
        _release_proxy(proxy, False, classify_ytdlp(p.stderr, p.returncode), started, domain)
        return ""
    for line in (p.stdout or "").splitlines():
        if line.strip() and os.path.exists(line.strip()):
            ok = playable_video(line.strip())
            _release_proxy(proxy, ok, None if ok else FailureClass.INVALID_MEDIA, started, domain)
            return line.strip() if ok else ""
    _release_proxy(proxy, False, FailureClass.INVALID_MEDIA, started, domain)
    return ""


def web_video_clip(query: str, out_dir: str, seconds: float = 6.0, used: set = None,
                   intent: str = "", context: str = "") -> Optional[MediaAsset]:
    """
    A clip from the non-YouTube videos Google's video search returns - TikTok,
    Facebook, Vimeo, news sites - held to the Dailymotion rules: not a
    talking-head title, not vertical, no burned-in text, and the vision model
    must see the intent in the downloaded frames. yt-dlp handles the sites.
    """
    if not config.ALLOW_WEB_VIDEO:
        return None
    os.makedirs(out_dir, exist_ok=True)
    grab = max(2.0, seconds + 1.5)
    judged = 0
    for row in search_google_videos(query):
        if any(s in row["site"] for s in _WEB_VIDEO_SKIP):
            continue
        if used and f"web:{row['url']}" in used:
            continue
        if _talking_head(row["title"]) or _stock_seller(row["title"], row["site"]):
            continue
        if row["seconds"] and row["seconds"] < grab + 2:
            continue
        if judged >= config.VISION_MAX_CANDIDATES:
            break
        start = _fixed_point({"duration": row["seconds"]}, grab, 5.0) if row["seconds"] else 5.0
        margin = config.CUT_MARGIN_SECONDS if config.CLEAN_CUTS else 0.0
        path = _web_fetch(row["url"], out_dir, max(0.0, start - margin), grab + 2 * margin)
        if path and margin:
            path = tidy_clip(path, grab, prefer=min(start, margin))[0]
        if not path:
            continue
        w, h = _video_dims(path)
        if (w and h and w < h * 1.2 and not config.ALLOW_VERTICAL) or has_burned_captions(path):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        judged += 1
        keep, verdict = _vision_gate(path, intent, context, row["title"])
        if not keep:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        return MediaAsset(
            kind="video", source="web_video", url=row["url"], local_path=path,
            duration=grab, attribution=f"{row['site']}: {row['title']}"[:200],
            license="unverified — you must hold the rights", query=query,
            review_required=True,
            review_reason="Licence unverified — confirm you hold the rights",
        ).apply_verdict(verdict, intent)
    return None


def _search_target(search: str, require_cc: bool, this_year: bool) -> str:
    if require_cc:
        # yt-dlp's flat search extractor reports license=NA for every hit,
        # so a CC match-filter over ytsearch rejects everything. YouTube's
        # own results page with its CC filter populates the field.
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(search) + "&sp=EgIwAQ%3D%3D")
    if this_year:
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(search) + "&sp=" + _YT_THIS_YEAR)
    return f"ytsearch{config.YT_SEARCH_RESULTS}:{search}"


def _youtube_pool(query: str, out_dir: str, seconds: float, start_at: float,
                  require_cc: bool, skip: int, used: Optional[set], intent_text: str,
                  context: str, subject: str, searches: List[tuple]) -> Optional[MediaAsset]:
    """
    The candidate-pool way to find a clip (src/candidates.py).

    Every search variant and the intent's own expanded searches run first and
    their results are pooled and deduplicated; the pool is ranked on metadata
    against the typed intent; the best few are scouted and judged; and the
    combined score - not the order the searches happened to return - picks
    the winner. The runners-up stay with the scene as alternatives.
    """
    si = intent.SceneIntent.from_dict(_SCENE_INTENT.get()) if _SCENE_INTENT.get() else None
    pool = candidates.CandidatePool(si, query, seconds, used=used)
    targets = list(searches)
    tried = _scene_tried()
    # The intent's own expanded searches join the first attempt's pool only;
    # a fallback attempt already has their results and adds its own query.
    if si and config.POOL_EXTRA_QUERIES > 0 and not require_cc and "__intent_searched__" not in tried:
        tried.add("__intent_searched__")
        for q in si.queries(query)[1:1 + config.POOL_EXTRA_QUERIES]:
            targets.append((q, "intent", False))

    def fetch_one(t):
        search, variant, this_year = t
        if variant == "channels":
            return t, _channel_candidates(search, _story_channels(), subject), "channel"
        return t, _yt_candidates_cached(_search_target(search, require_cc, this_year),
                                        require_cc, subject, variant), "search"

    with ThreadPoolExecutor(max_workers=max(1, min(4, len(targets)))) as ex:
        for t, rows, via in ex.map(fetch_one, targets):
            pool.add(rows, query=t[0], variant=t[1], via=via)

    ranked = [c for c in pool.ranked()
              if c.id not in tried and _usable_title(c.title, c.channel, c.aspect)]
    if skip:
        ranked = ranked[skip:] + ranked[:skip]
    if not ranked:
        return None
    # Scouting spends one model call per candidate; leave room for judging.
    left = _vision_budget_left()
    if left < 2:
        print(f"[pool] scene out of vision budget ({config.JUDGE_MAX_PER_SCENE}); no more searches", flush=True)
        return None
    n_scouts = max(1, min(config.POOL_SCOUT, left - 2))
    print(f"[pool] {len(pool)} candidates from {pool.searches} searches ({len(ranked)} new); "
          f"best meta {ranked[0].metadata:.2f} {ranked[0].title[:50]!r}; scouting {n_scouts}", flush=True)

    grab = max(2.0, seconds + 1.5)
    scouts = ranked[:n_scouts]
    tried.update(c.id for c in scouts)
    by_id = {c.id: c for c in scouts}
    # Scouting runs in pool threads, which do not see this scene's budget
    # counter, so the fresh (unmemoised) scouts are counted here first.
    if config.MOMENT_SELECTION and intent_text and vision.enabled():
        with _SCENE_LOCK:
            fresh = sum(1 for c in scouts if _scout_memo_key(c.id, grab, intent_text) not in _SCOUT_MEMO)
        for _ in range(fresh):
            _count_judged()
    plan = _plan_grabs([c.row() for c in scouts], grab, start_at, intent_text, context)
    story_kind = _STORY_KIND["kind"]
    passed: List[MediaAsset] = []
    soft: Optional[dict] = None       # the best candidate under the floor, if any
    judged = 0
    fine_done = False
    claimed: List[str] = []
    for row, point, moment in plan:
        if judged >= config.VISION_MAX_CANDIDATES or _vision_budget_left() < 1 or _good_enough(passed):
            break
        c = by_id[row["id"]]
        if not _claim_inflight(c.id, used):
            continue                        # another scene is downloading it right now
        claimed.append(c.id)
        # The fine pass (one more model call) goes to the best-ranked
        # download only; the others keep their coarse pick.
        if not fine_done and _vision_budget_left() >= 2:
            fine_done = True
            _count_judged()
            moment = _refine_moment(row, moment, grab, intent_text, context)
        if moment and moment.get("fine"):
            point = moment["start"]
        path, clean, cuts = fetch_clean_clip(c.id, out_dir, point, grab, c.title)
        if not path:
            _release_inflight(c.id)
            continue
        if has_burned_captions(path):
            print(f"[media] hardsubs, skipping: {c.title[:60]}", flush=True)
            try:
                os.remove(path)
            except OSError:
                pass
            _release_inflight(c.id)
            continue
        judged += 1
        _count_judged()
        keep, verdict = _vision_gate(path, intent_text, context, c.title)
        if not keep:
            v = verdict or {}
            score = float(v.get("score") or 0.0)
            clear_no = bool(v.get("has_text_or_watermark")) or bool(v.get("is_talking_head"))
            if (score >= config.VISION_SOFT_MIN_SCORE and not clear_no
                    and (soft is None or score > soft["score"])):
                # The best near-miss so far: kept in case nothing passes.
                if soft is not None:
                    try:
                        os.remove(soft["path"])
                    except OSError:
                        pass
                soft = {"path": path, "score": score, "verdict": verdict, "c": c, "point": point,
                        "moment": moment, "clean": clean, "cuts": cuts}
                continue
            try:
                os.remove(path)
            except OSError:
                pass
            _release_inflight(c.id)
            continue
        asset = _asset_for(path, query, grab, require_cc, title=c.title)
        asset.url = f"https://www.youtube.com/watch?v={c.id}&t={int(point)}"
        asset.apply_verdict(verdict, intent_text)
        penalty = candidates.reuse_penalty(f"yt:{c.id}", c.channel, used, used_channels=_USED_CHANNELS)
        asset.final_score, asset.score_parts = candidates.final_score(
            asset.relevance_score, asset.quality, _moment_score(moment, clean), c.parts,
            asset.specificity, story_kind, penalty=penalty)
        asset.score_parts["meta"] = round(c.metadata, 3)
        asset.pool = pool.summary()
        asset.moment = {"start": round(float(point), 1), "score": (moment or {}).get("score"),
                        "fine": bool((moment or {}).get("fine")), "span": (moment or {}).get("span"),
                        "clean": clean, "cuts": cuts}
        print(f"[pool] judged {c.id} final {asset.final_score:.2f} "
              f"(visual {asset.relevance_score or 0:.2f}, meta {c.metadata:.2f}, "
              f"{asset.specificity or 'unclassed'})", flush=True)
        passed.append(asset)
    winner = _best_of(passed)
    if winner is None and soft is not None:
        # Nothing cleared the floor: the best near-miss, flagged for review.
        # The editor shows the flag and the alternatives; a related shot the
        # user can swap beats a beat with nothing on it.
        c, point, moment = soft["c"], soft["point"], soft["moment"]
        asset = _asset_for(soft["path"], query, grab, require_cc, title=c.title)
        asset.url = f"https://www.youtube.com/watch?v={c.id}&t={int(point)}"
        asset.apply_verdict(soft["verdict"], intent_text)
        asset.review_required = True
        asset.review_reason = (f"Best available: the vision check scored it {soft['score']:.2f}, "
                               f"under the {config.VISION_MIN_SCORE:.2f} floor")
        penalty = candidates.reuse_penalty(f"yt:{c.id}", c.channel, used, used_channels=_USED_CHANNELS)
        asset.final_score, asset.score_parts = candidates.final_score(
            asset.relevance_score, asset.quality, _moment_score(moment, soft["clean"]), c.parts,
            asset.specificity, story_kind, penalty=penalty)
        asset.score_parts["meta"] = round(c.metadata, 3)
        asset.pool = pool.summary()
        asset.moment = {"start": round(float(point), 1), "score": (moment or {}).get("score"),
                        "fine": bool((moment or {}).get("fine")), "span": (moment or {}).get("span"),
                        "clean": soft["clean"], "cuts": soft["cuts"]}
        print(f"[pool] best available {c.id} {soft['score']:.2f} (under the floor) - flagged for review",
              flush=True)
        winner = asset
    elif soft is not None:
        try:
            os.remove(soft["path"])
        except OSError:
            pass
    # The claims only had to cover the download-and-judge window, when two
    # scenes could converge on one video; the caller records the winner in
    # `used` as soon as this returns.
    for vid in claimed:
        _release_inflight(vid)
    if winner is not None:
        chan = by_id.get(winner.identity[3:], None)
        if chan is not None and chan.channel:
            _USED_CHANNELS.add(chan.channel)
    return winner


# --------------------------------------------------------------------------- #
# Clean cuts: a clip that starts on a shot change or straddles one reads as a
# mistake. Every downloaded section is taken with a margin on each side, its
# shot changes are found, and the clip is cut from the longest stretch that
# holds the intended moment and no cut.
# --------------------------------------------------------------------------- #



def fetch_clean_clip(video_id: str, out_dir: str, start: float, need: float,
                     title: str = "") -> tuple:
    """(path, clean, cuts): a YouTube section with margin, cut clean around `start`."""
    margin = config.CUT_MARGIN_SECONDS if config.CLEAN_CUTS else 0.0
    fetch_start = max(0.0, start - margin)
    path = _yt_fetch_retry(video_id, out_dir, fetch_start, need + 2 * margin, title)
    if not path:
        return "", True, 0
    if not margin:
        return path, True, 0
    return tidy_clip(path, need, prefer=start - fetch_start)


def _refine_moment(candidate: dict, moment: Optional[dict], grab: float,
                   intent_text: str, context: str) -> Optional[dict]:
    """The fine storyboard pass around a coarse pick (moments.refine), or the pick."""
    if not moment or not config.MOMENT_FINE_PASS or not intent_text:
        return moment
    try:
        info, proxy = _yt_info(candidate["id"])
        fine = moments.refine(info, moment, intent_text, context, grab, proxy) if info else None
    except Exception as e:  # noqa: BLE001 - the coarse pick stands
        print(f"[moment] fine pass failed: {type(e).__name__}", flush=True)
        fine = None
    if fine:
        print(f"[moment] fine {fine['score']:.2f} @ {fine['start']:.1f}s over {fine['span']:.0f}s "
              f"(coarse {moment.get('score', 0):.2f} @ {moment.get('start', 0):.1f}s)", flush=True)
        return fine
    return moment


def _moment_score(moment: Optional[dict], clean: bool) -> Optional[float]:
    s = (moment or {}).get("score")
    if s is None:
        return None
    return float(s) * (1.0 if clean else 0.5)


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
_YT_INFO_CACHE = _ytdlp._YT_INFO_CACHE   # one cache, owned by ytdlp

# Generated images are billed per call, so the budget is enforced here rather
# than trusted to callers. Reset per job alongside the cache.
_GENERATED = [0]

# Per-source search outcomes for the job result. The search functions return
# [] on any failure, so a source that was blocked, rate-limited or down looked
# exactly like one with no matches: a 362-scene job lost 300 photo scenes and
# nothing said which source failed or why.
_SOURCE_STATS: Dict[str, Dict[str, Any]] = {}
# Channels whose footage the video already uses (a reuse penalty, not a bar).
_USED_CHANNELS: set = set()


def _source_stat(name: str) -> Dict[str, Any]:
    return _SOURCE_STATS.setdefault(name, {"searches": 0, "withResults": 0,
                                           "errors": 0, "recentErrors": []})


def _source_error(name: str, exc: Exception) -> None:
    """Record why a source failed, and its class; never raises."""
    cls = classify_exception(exc)
    events.emit("source", "provider_failed", level="warning", provider=name, failure=cls.value,
                message=f"{type(exc).__name__}: {str(exc)[:100]}")
    with _CACHE_LOCK:
        st = _source_stat(name)
        st["errors"] += 1
        st["recentErrors"] = (st["recentErrors"] + [f"{cls.value}: {type(exc).__name__}: {str(exc)[:120]}"])[-4:]
        by = st.setdefault("byClass", {})
        by[cls.value] = by.get(cls.value, 0) + 1


def source_stats() -> Dict[str, Any]:
    with _CACHE_LOCK:
        return {k: dict(v, recentErrors=list(v["recentErrors"])) for k, v in _SOURCE_STATS.items()}


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _SCENE_LOCK:
        _SCOUT_MEMO.clear()
        _INFLIGHT.clear()
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()
        _YT_CANDIDATES_CACHE.clear()
        _GOOGLE_VIDEO_CACHE.clear()
        _SOURCE_STATS.clear()
        _USED_CHANNELS.clear()
        _GENERATED[0] = 0
    _BRIGHTDATA_REFUSED["why"] = ""     # a topped-up account works again on the next job
    from . import official
    official.reset()                    # each satellite sector once per video
    LOCAL_REJECTED["n"] = 0
    _SERPAPI_USED["n"] = 0              # SerpApi's per-job budget starts again
    _BRIGHTDATA_FAILS["n"] = 0
    _IMAGE_NO_CREDIT["hit"] = False
    UNJUDGED_KEPT.update(n=0, rejected=0)
    _ytdlp.reset()
    vision.reset()  # per-job call/failure counts for the job result
    moments.reset_cache()  # storyboard sheets, cached per video across beats


def _generation_budget_left() -> bool:
    with _CACHE_LOCK:
        if _GENERATED[0] >= config.IMAGE_MAX_PER_VIDEO:
            return False
        _GENERATED[0] += 1
    costs.record("image.generate")
    with _CACHE_LOCK:
        return True


def limit_generation(n: int) -> None:
    """Allow at most `n` more generated images in this job (a fan-out part's share)."""
    with _CACHE_LOCK:
        _GENERATED[0] = max(0, config.IMAGE_MAX_PER_VIDEO - max(0, int(n)))


def generated_count() -> int:
    with _CACHE_LOCK:
        return _GENERATED[0]


def _cached_search(fn, query: str, cache_key: str = "", key: str = "") -> List[MediaAsset]:
    """
    Cache `fn(query)` under `cache_key` (default: the query itself).

    `key` names the source when `fn` is a lambda: every lambda is called
    "<lambda>", so without it Pixabay was handed Pexels's cached results.

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
    name = key or fn.__name__
    key = f"{name}::{cache_key or query}"
    with _CACHE_LOCK:
        if key in _SEARCH_CACHE:
            return _SEARCH_CACHE[key]
    try:
        found = fn(query)
    except Exception as e:  # noqa: BLE001
        print(f"[media] {name} '{query}' failed: {e}", flush=True)
        _source_error(name, e)
        found = []
    with _CACHE_LOCK:
        st = _source_stat(name)
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
        if candidate.kind == "image":
            # Browser-style retries for hotlink blocks, and whatever format
            # arrived (WebP, AVIF, HEIC, CMYK...) rewritten as a clean JPEG.
            candidate.local_path = _imagefix.fetch(candidate.url, dest,
                                                   getattr(candidate, "page_url", "") or "")
        else:
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
        keep, verdict = _vision_gate(got.local_path, intent, context, _image_label(got))
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
                       subject: str = "", event_window: str = "",
                       scene_intent: Optional[dict] = None) -> Optional[MediaAsset]:
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
    if _ytdlp.past_deadline():
        # The job's sourcing time is spent: the beat becomes an animation scene.
        return None
    if config.REQUIRE_AI and vision.ai_exhausted():
        return None   # the job is stopping; do not spend on searches it will discard
    token = _SUBJECT_TYPE.set(subject_type or "")
    window_token = _EVENT_WINDOW.set(event_window or "")
    intent_token = _SCENE_INTENT.set(scene_intent or None)
    judged_token = _SCENE_JUDGED.set([0])
    tried_token = _SCENE_TRIED.set(set())
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
        _SCENE_TRIED.reset(tried_token)
        _SCENE_JUDGED.reset(judged_token)
        _SCENE_INTENT.reset(intent_token)
        _EVENT_WINDOW.reset(window_token)
        _SUBJECT_TYPE.reset(token)


def _source_one(query: str, seconds: float, work_dir: str, *,
                visual_type: str = "footage", nth: int = 0,
                used: set = None, prompt: str = "",
                allow_youtube: bool = None, allow_stock: bool = None,
                require_cc: bool = None, intent: str = "",
                context: str = "", subject: str = "") -> Optional[MediaAsset]:
    """
    Find and download one visual for a scene, from the provider registry
    (src/providers.py) in its order: YouTube, Dailymotion, web video, the
    public-domain and Creative Commons archives, stock when allowed, then
    stills (the subject's own article, web images, the archives, stock), a
    still's last resort of footage, and a generated illustration.

    `visual_type` is the director's call: "footage" wants moving pictures,
    "image" wants a still that Ken Burns will animate. Footage falls back to
    stills rather than leaving the scene black - a good photograph beats a
    wrong clip. `nth` and `used` keep a long video from repeating itself:
    the Nth scene to ask the same question reaches further down the result
    list, and `used` is every asset already placed anywhere in this video.
    """
    allow_youtube = config.ALLOW_YOUTUBE if allow_youtube is None else allow_youtube
    allow_stock = config.ALLOW_STOCK if allow_stock is None else allow_stock
    require_cc = config.REQUIRE_CC if require_cc is None else require_cc
    if youtube_only():
        visual_type, allow_youtube, allow_stock = "footage", True, False
    ctx = providers.SourceContext(
        query=query, seconds=seconds, work_dir=work_dir, visual_type=visual_type, nth=nth,
        used=used, prompt=prompt, allow_youtube=bool(allow_youtube), allow_stock=bool(allow_stock),
        require_cc=bool(require_cc), intent=intent, context=context, subject=subject,
        subject_type=_SUBJECT_TYPE.get() or "", youtube_only=bool(youtube_only()),
        enabled_names=_ENABLED_PROVIDERS.get())
    return providers.source_one(ctx)


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
    # Archive film only exists small; everything else must be at least
    # MIN_CLIP_HEIGHT lines (the owner: 1080p-quality clips).
    title = f"{getattr(asset, 'attribution', '') or ''} {getattr(asset, 'query', '') or ''}"
    archive = asset.source == "archive_org" or bool(_ARCHIVE_TITLE_RE.search(title))
    # A page of text (slide, screenshot, scan) only for a beat about a document.
    if asset.kind == "image" and _SUBJECT_TYPE.get() != "document" and _filters.text_page_still(path):
        return False, "a page of text, not a photo"
    return clip_quality(path, config.MIN_ARCHIVE_HEIGHT if archive else config.MIN_CLIP_HEIGHT)


_ARCHIVE_TITLE_RE = re.compile(r"\b(newsreel|archive|archival|pathe|path\u00e9|periscope|movietone|travelogue|"
                               r"huntley|18\d\d|19[0-8]\d|1990s?)\b", re.I)


# What the last source_many() did, phase by phase, for the job result. The
# worker's own log shows this, but RunPod doesn't expose that log - without
# it, "why is this slow" was guesswork: a real job sent 19-21 of 23 beats to
# the slow replacement pass and there was no way to see which of empty /
# repeat / rejected was the cause.
LAST_STATS: Dict[str, Any] = {}


# Thread pools that a time box leaves running. They are shut down without
# waiting (a hung download must not hold the video), tracked here, and
# drained for a bounded time when the job ends so stragglers do not run on
# into the next job on this process.
_LIVE_POOLS: List[ThreadPoolExecutor] = []
_POOLS_LOCK = threading.Lock()


def _new_pool(workers: int) -> ThreadPoolExecutor:
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    with _POOLS_LOCK:
        _LIVE_POOLS.append(pool)
    return pool


def drain_pools(timeout: float = 15.0) -> int:
    """Wait up to `timeout` seconds for the tracked pools' running work; returns how many were still busy."""
    with _POOLS_LOCK:
        pools, _LIVE_POOLS[:] = list(_LIVE_POOLS), []
    if not pools:
        return 0
    busy = [0]

    def close_all():
        for pool in pools:
            pool.shutdown(wait=True, cancel_futures=True)

    t = threading.Thread(target=close_all, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        busy[0] = len(pools)
        print(f"[media] {len(pools)} pool(s) still busy after {timeout:.0f}s; left to finish in the background",
              flush=True)
    return busy[0]


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
                refill: bool = True, **kwargs) -> List[Optional[MediaAsset]]:
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
        seq_pool = _new_pool(max(1, workers))
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
                    scene_intent=job.get("scene_intent"),
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
    pool = _new_pool(max(1, workers))
    futures = {pool.submit(fetch, job, nth): job["index"] for job, nth in pass1}
    started = time.time()
    deadline = started + _budget(config.PASS1_BUDGET_SECONDS, 3.0, len(pass1))
    if _ytdlp.DEADLINE[0]:
        # The job's sourcing deadline wins: a part must hand back what it found
        # (and upload it) before the parent stops waiting, or all of it is lost.
        deadline = min(deadline, _ytdlp.DEADLINE[0] - 25.0)
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
    # refill=False (a fan-out part): classify only. The parent de-duplicates
    # across parts and fills gaps from the pools' spare moments; a part
    # spending its own time box here held the whole video for minutes.
    deadline = time.time() + (_budget(config.REPLACE_BUDGET_SECONDS, 3.0, len(todo)) if refill else 0.0)
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
                    scene_intent=job.get("scene_intent"),
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
        pool = _new_pool(max(1, workers))
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
                    event_window=job.get("event_window", ""),
                    scene_intent=job.get("scene_intent"), **kwargs)
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
        pool = _new_pool(max(1, workers))
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

    fresh = fresh_moments(ordered, results, work_dir) if config.FRESH_MOMENTS else 0
    if fresh:
        print(f"[media] {fresh} scene(s) got another moment of a video the story already uses "
              f"instead of a repeated shot", flush=True)
    LAST_STATS.update(fresh_moments=fresh)
    # Reusing a shot waits until after the job's rescue pass has looked for fresh
    # footage (handler): run here first, it filled 51 of 164 scenes with repeats.
    reused = (fill_from_story(ordered, results)
              if config.REUSE_SHOTS_TO_FILL and not config.RESCUE_BEFORE_REUSE else 0)
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


_FRESH_OFFSETS = (25.0, -25.0, 45.0, -45.0, 70.0, -70.0, 95.0)


def _yt_origin(asset: MediaAsset) -> tuple:
    """(video id, start seconds) of a YouTube clip, ("", 0.0) when unknown."""
    m = re.search(r"yt:([\w-]{11})", asset.identity or "") or re.search(r"[?&]v=([\w-]{11})", asset.url or "")
    vid = m.group(1) if m else ""
    start = asset.moment.get("start") if isinstance(asset.moment, dict) else None
    if start is None and asset.local_path:
        name = os.path.basename(asset.local_path)
        if name.startswith("yt_"):
            rest = name[15:].split("_")
            try:
                start = int(rest[0]) / 1000.0
            except (ValueError, IndexError):
                start = None
    return vid, float(start or 0.0)


def fresh_moments(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]], work_dir: str) -> int:
    """
    Fill scenes still empty with ANOTHER moment of a same-subject YouTube video
    the story already uses - GoMotion's many-moments-per-video method - rather
    than repeating a shot. Each try is a 10 s bucket no scene uses, 25-95 s
    from the donor's moment, passes clip_quality and (when vision is on) the
    judge against the scene's intent. Parallel, time boxed by
    FRESH_MOMENT_SECONDS. Returns how many scenes were filled.
    """
    if not work_dir:
        return 0
    by_index = {j["index"]: j for j in jobs}
    empties = [i for i in sorted(by_index) if results[i] is None and by_index[i].get("subject_type") != "person"
               and by_index[i].get("visual_type", "footage") == "footage"]
    if not empties:
        return 0
    lock = threading.Lock()
    used = set()
    for r in results:
        if r is not None and r.source == "youtube":
            vid, start = _yt_origin(r)
            if vid:
                used.add(f"yt:{vid}@{int(start // 10)}")
    deadline = time.time() + config.FRESH_MOMENT_SECONDS

    def donors_for(i: int) -> List[MediaAsset]:
        subject = by_index[i].get("subject") or ""
        out, seen = [], set()
        for k in sorted((k for k in by_index if results[k] is not None), key=lambda k: abs(k - i)):
            r = results[k]
            if r.source != "youtube" or r.kind != "video" or not same_subject(subject, by_index[k].get("subject") or ""):
                continue
            vid, _s = _yt_origin(r)
            if vid and vid not in seen:
                seen.add(vid)
                out.append(r)
        return out[:2]

    def one(i: int) -> Optional[MediaAsset]:
        job = by_index[i]
        need = max(2.5, min(12.0, float(job.get("seconds") or 5.0)))
        for donor in donors_for(i):
            vid, start = _yt_origin(donor)
            for off in _FRESH_OFFSETS:
                if time.time() > deadline:
                    return None
                at = start + off
                if at < 3:
                    continue
                key = f"yt:{vid}@{int(at // 10)}"
                with lock:
                    if key in used:
                        continue
                    used.add(key)
                path = _yt_fetch_retry(vid, work_dir, at, need, title=job.get("subject") or "")
                if not path:
                    continue
                asset = MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(at)}",
                                   local_path=path, license=donor.license, attribution=donor.attribution,
                                   query=job.get("query", ""), moment_key=key,
                                   moment={"start": round(at, 1), "fresh_from": donor.identity},
                                   relevance_score=(donor.relevance_score * 0.95 if donor.relevance_score is not None else None),
                                   review_required=True,
                                   review_reason=f"Another moment of a video used for {job.get('subject') or 'this subject'}")
                ok, why = _asset_ok(asset)
                if not ok:
                    continue
                local = _local_check(path, job.get("intent", "")) if job.get("intent") else None
                if local is not None and local["reject"]:
                    continue
                if vision.enabled() and job.get("intent"):
                    verdict = vision.judge(path, job.get("intent", ""), job.get("query", ""))
                    if verdict is not None and float(verdict.get("score") or 0) < config.VISION_SOFT_MIN_SCORE:
                        continue
                    if verdict is not None:
                        asset.relevance_score = float(verdict.get("score") or 0)
                        asset.content_description = str(verdict.get("description") or "")[:300]
                return asset
        return None

    filled = 0
    with ThreadPoolExecutor(max_workers=min(6, len(empties))) as pool:
        for i, got in zip(empties, pool.map(one, empties)):
            if got is not None:
                results[i] = got
                filled += 1
    return filled


def rescue_fill(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]], work_dir: str,
                youtube_only: bool = False) -> Dict[str, int]:
    """
    The last pass over scenes still empty after sourcing, before any shot is
    repeated (handler._fill_missing_media borrows one). In order: another
    moment of a same-subject video already on the timeline (fresh_moments),
    the best-titled YouTube result no scene uses, then a web picture. No
    vision call - it is the step that failed - so the title has to name what
    the line is about (_title_fits), and everything found here is flagged for
    review. Parallel, time boxed by RESCUE_SECONDS past any sourcing
    deadline. Fills `results` in place; returns how many per step.
    """
    out = {"fresh": 0, "search": 0, "image": 0, "asked": 0}
    by_index = {j["index"]: j for j in jobs if j["index"] < len(results)}

    def empty() -> List[int]:
        return [i for i in sorted(by_index) if results[i] is None]

    if not work_dir or config.RESCUE_SECONDS <= 0 or not empty():
        return out
    out["asked"] = len(empty())
    old = _ytdlp.DEADLINE[0]
    until = time.time() + config.RESCUE_SECONDS
    _ytdlp.set_deadline(until)
    try:
        if config.FRESH_MOMENTS:
            out["fresh"] = fresh_moments(jobs, results, work_dir)
        # Beats the director meant as a graphic stay a graphic.
        todo = [i for i in empty() if (by_index[i].get("visual_type") or "footage") in ("footage", "image")]
        used = set()
        for r in results:
            if r is not None and r.source == "youtube":
                vid, _s = _yt_origin(r)
                if vid:
                    used.add(vid)
        used_images = {r.identity for r in results if r is not None and r.kind == "image"}
        lock = threading.Lock()

        def claim(key: str, pool: set) -> bool:
            with lock:
                if key in pool:
                    return False
                pool.add(key)
                return True

        def footage(job: dict, q: str, intent_text: str, need: float) -> Optional[MediaAsset]:
            try:
                cands = _yt_candidates(f"ytsearch8:{q}", False, limit=8, timeout=40)
            except Exception:  # noqa: BLE001
                return None
            cands = [c for c in cands if float(c.get("duration") or 0) >= need + 8
                     and not _talking_head(c.get("title") or "")
                     and _title_fits(c.get("title") or "", intent_text)]
            cands.sort(key=lambda c: -_score_candidate(c.get("title") or "", float(c.get("duration") or 0),
                                                       float(c.get("aspect") or 0), need))
            for c in cands[:4]:
                if time.time() > until - 15:
                    return None
                if not claim(c["id"], used):
                    continue
                dur = float(c.get("duration") or 0)
                point = max(5.0, dur * 0.35)
                path, clean, cuts = fetch_clean_clip(c["id"], work_dir, point, need, c.get("title") or "")
                if not path:
                    continue
                if _filters.has_burned_captions(path):
                    continue
                asset = _asset_for(path, q, need, False, title=c.get("title") or "")
                asset.url = f"https://www.youtube.com/watch?v={c['id']}&t={int(point)}"
                asset.intent = intent_text
                asset.moment_key = f"yt:{c['id']}@{int(point // 10)}"
                asset.moment = {"start": round(point, 1), "clean": clean, "cuts": cuts, "rescue": True}
                ok, _why = _asset_ok(asset)
                if not ok:
                    continue
                if not _rescue_local_ok(path, intent_text):
                    continue
                asset.review_required = True
                asset.review_reason = "Found in the last pass without an AI check - make sure it fits the line"
                return asset
            return None

        def picture(job: dict, q: str, intent_text: str) -> Optional[MediaAsset]:
            for cand in _cached_search(search_web_images, q)[:5]:
                if time.time() > until - 10:
                    return None
                if not claim(cand.identity, used_images):
                    continue
                got = _download(_dc_replace(cand), q, work_dir)
                if got and (not _asset_ok(got)[0] or not _rescue_local_ok(got.local_path, intent_text)):
                    got = None
                if got:
                    got.intent = intent_text
                    got.review_required = True
                    got.review_reason = "Picture found in the last pass without an AI check - make sure it fits"
                    return got
            return None

        def one(i: int) -> Optional[MediaAsset]:
            job = by_index[i]
            q = " ".join(str(job.get("query") or job.get("subject") or "").split())
            if not q or time.time() > until - 20:
                return None
            if job.get("subject_type") == "person":
                return None        # a searched face can be the wrong person; the scene gets a graphic
            intent_text = job.get("intent") or q
            need = max(2.5, min(12.0, float(job.get("seconds") or 5.0)))
            token = _SCENE_INTENT.set(job.get("scene_intent") or None)
            try:
                got = None
                if job.get("visual_type", "footage") != "image":
                    got = footage(job, q, intent_text, need)
                if got is None and not youtube_only and config.ALLOW_WEB_IMAGES:
                    got = picture(job, q, intent_text)
                return got
            finally:
                _SCENE_INTENT.reset(token)

        if todo:
            with ThreadPoolExecutor(max_workers=max(1, min(config.RESCUE_PARALLEL, len(todo)))) as pool:
                for i, got in zip(todo, pool.map(one, todo)):
                    if got is not None and results[i] is None:
                        results[i] = got
                        out["image" if got.kind == "image" else "search"] += 1
    finally:
        _ytdlp.set_deadline(old)
    print(f"[rescue] {out['asked']} empty scene(s): {out['fresh']} other moments, {out['search']} searched clips, "
          f"{out['image']} pictures; {len(empty())} still empty", flush=True)
    return out


def fill_from_story(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]],
                    max_uses: Optional[int] = None) -> int:
    """
    Give every scene still empty a real shot from elsewhere in the same story.

    The last step, after searching, the AI recheck and generation. A real
    person may have five photos online and forty lines in a biography; with
    each shot usable once, the other thirty-five scenes rendered black. First
    choice is a shot of the same subject placed more than REUSE_MIN_GAP scenes
    away, then a shot from a nearby scene - never a photo of a different
    person, which would put the wrong face on screen - and last the same
    subject's farthest shot, never on the scene right next to it. Every reuse
    is flagged for review. With `max_uses`, a shot appears at most that many
    times in the video (the owner: no clip shown again and again). Returns how
    many scenes were filled.
    """
    by_index = {j["index"]: j for j in jobs}
    order = sorted(by_index)
    uses: Dict[str, int] = {}
    for r in results:
        if r is not None:
            uses[r.identity] = uses.get(r.identity, 0) + 1

    def spent(k: int) -> bool:
        return max_uses is not None and uses.get(results[k].identity, 0) >= max_uses

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
        donors = sorted((k for k in order if k != i and results[k] is not None and not spent(k)),
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
        uses[donor.identity] = uses.get(donor.identity, 0) + 1
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
                if _usable_title(c["title"], c.get("channel", ""), c["aspect"])
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
        keep, verdict = _vision_gate(got.local_path, intent, context, _image_label(got))
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
