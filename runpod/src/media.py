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
from collections import Counter
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

from . import candidates, config, costs, events, intent, ledger, moments, providers, proxies, vision
from . import imagefix as _imagefix
from . import localvision as _localvision
from . import sharpness as _sharpness
from . import stockblock as _stockblock
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
    # A web picture's page (its Referer when the host blocks hotlinks) and the
    # search engine's own smaller copy of it (the last resort when the host
    # refuses every download: the Mount Rainier video lost 166 pictures to
    # 403s and HTML pages, 2026-10-02).
    page_url: str = ""
    thumbnail: str = ""
    # The combined score that chose this clip over the others that passed
    # (src/candidates.py), its parts, and a summary of the pool it came from.
    final_score: Optional[float] = None
    score_parts: Dict[str, float] = field(default_factory=dict)
    pool: Dict[str, Any] = field(default_factory=dict)
    # Where in the source the clip was cut and how that was decided: start,
    # coarse or fine storyboard score, whether the cut window was free of
    # shot changes (src/moments.py, clean_window below).
    moment: Dict[str, Any] = field(default_factory=dict)
    # How the shot was checked against its line - the editor and the later
    # checks read it (semanticMetadata.judgedBy; the owner's Glen Canyon test,
    # 2026-10-05, opened on two clips nothing had looked at): "frames" the
    # vision judge on three frames, "opening" the same judge's opening check
    # (the first moment, middle and end of what the scene shows - every clip
    # of the hook, src/hookcheck.py), "tile" a storyboard tile's rating (a
    # subject pool's moment), "library" / "pack" judged when first found,
    # "local" the local CLIP model only, "none" nothing, "" not recorded.
    judged_by: str = ""
    # The opening check's verdict on this very cut (vision.cut_record).
    cut_check: Dict[str, Any] = field(default_factory=dict)

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
            self.cut_check = vision.cut_record(verdict)
            self.judged_by = "opening" if self.cut_check else "frames"
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

def _sized_image_rows(query: str, count: int, proxy: Optional[str]) -> List[tuple]:
    """
    (url, width, height, title, page, thumbnail) rows of Bing's image search -
    the engine DuckDuckGo's image search runs on - with its "larger than W x H"
    filter at the size a sharp full-screen picture needs (sharpness.min_size).
    Measured 2026-10-04: the plain search returned 4-14 of 35 pictures big
    enough ("Lake Powell drought bathtub ring": 5), the filtered one 32-35.
    """
    from ddgs.engines.bing_images import BingImages
    w, h = _sharpness.min_size()

    class _Sized(BingImages):
        def build_payload(self, *args, **kwargs):
            p = super().build_payload(*args, **kwargs)
            size = f"+filterui:imagesize-custom_{w}_{h}"
            p["qft"] = size + (f"+{p['qft']}" if p.get("qft") else "")
            return p

    found = _Sized(proxy=proxy, timeout=15).search(query, region="us-en", safesearch="moderate", timelimit=None,
                                                    page=1, max_results=count) or []
    return [(getattr(r, "image", "") or "", getattr(r, "width", 0) or 0, getattr(r, "height", 0) or 0,
             getattr(r, "title", "") or "", getattr(r, "url", "") or "", getattr(r, "thumbnail", "") or "")
            for r in found]


def search_web_images(query: str, limit: int = 6, full_screen: bool = True) -> List[MediaAsset]:
    """
    Real photographs of the named subject from a general image search.

    This is VidRush's `google_images` provider — 51 of the stills on one of
    their timelines. Archives like Commons have the landscape but rarely the
    specific press photo a documentary line is about. Serper (Google Images)
    when SERPER_API_KEY is set, the keyless DuckDuckGo search otherwise.
    Web results carry stock watermarks and unknown licences, so every one is
    vision-checked for watermarks and flagged for review.

    `full_screen` (PICTURE_SHARPNESS_CHECK on): pictures big enough to fill
    the frame sharply are asked for first (_sized_image_rows; the plain
    search adds to them only when they are too few), and a result whose own
    size could never be sharp full screen is not offered at all. Off for a
    graphic's small photo window.
    """
    if not config.ALLOW_WEB_IMAGES or not query.strip():
        return []
    big_first = bool(full_screen and _sharpness.picture_on())
    rows = []
    # (Bright Data's SERP API used to be asked first; removed 2026-10-04 at the owner's
    # word: it took 44 s a search and timed out 300+ times a video. DuckDuckGo
    # through a residential route answers in 1-3 s with its own thumbnail copy.)
    if config.SERPER_API_KEY:
        try:
            r = requests.post("https://google.serper.dev/images",
                              headers={"X-API-KEY": config.SERPER_API_KEY,
                                       "Content-Type": "application/json"},
                              json={"q": query, "num": limit * 2}, timeout=20)
            r.raise_for_status()
            for it in r.json().get("images", []):
                rows.append((it.get("imageUrl"), it.get("imageWidth") or 0,
                             it.get("imageHeight") or 0, it.get("title") or "",
                             it.get("link") or "", it.get("thumbnailUrl") or ""))
        except (requests.RequestException, ValueError):
            rows = []
    if not rows:
        # Keyless fallback. Through the proxy pool when there is one: a real
        # RunPod job returned no web images at all, consistent with the image
        # search rate-limiting a datacenter address the way YouTube does.
        # One direct attempt stays as the fallback for an unproxied box.
        # A picture route when there is one (every Decodo IP: config.IMAGE_PROXIES), else a YouTube one.
        from_proxy = _imagefix._residential_route() or _next_proxy()
        routes = [from_proxy, None] if from_proxy else [None]
        # The whole first page (~35 rows, the same one request as 12): stock
        # agencies fill most of the top rows for some lines ("Lake Mead bathtub
        # ring": 10 of the first 12, 1 usable picture left of 18; 6 of 35) and
        # are never used (src/stockblock.py, 2026-10-04).
        page_rows = max(limit * 2, 40)
        if big_first:
            for proxy in routes:
                try:
                    rows = _sized_image_rows(query, page_rows, proxy)
                except Exception as e:  # noqa: BLE001 — optional dependency / network
                    _source_error("web_images_sized", e)
                    rows = []
                if rows:
                    break
        # Too few big pictures that are not an agency's: the plain search adds to them.
        usable = [r for r in rows if str(r[0] or "").startswith("http")
                  and not _stockblock.reason(r[0], str(r[4] or ""), str(r[5] or ""), str(r[3] or ""))]
        if len(usable) < limit:
            plain: List[tuple] = []
            for proxy in routes:
                try:
                    from ddgs import DDGS
                    with DDGS(proxy=proxy, timeout=15) as ddg:
                        for it in ddg.images(query, max_results=page_rows):
                            plain.append((it.get("image"), it.get("width") or 0,
                                          it.get("height") or 0, it.get("title") or "",
                                          it.get("url") or "", it.get("thumbnail") or ""))
                except Exception as e:  # noqa: BLE001 — optional dependency / network
                    _source_error("web_images_ddg", e)
                    plain = []
                if plain:
                    break
            have = {r[0] for r in rows}
            rows += [r for r in plain if r[0] not in have]
        if not rows:
            # The free searches came back empty: SerpApi's Google Images
            # (quota-limited, so only here).
            rows = _serpapi_images("google_images", query)
        if not rows:
            return []

    out = []
    for row in rows:
        url, w, h, title, page = row[:5]
        thumb = row[5] if len(row) > 5 else ""
        if not url or not url.startswith("http"):
            continue
        # A stock agency's preview (Alamy, Getty, iStock, Shutterstock...): its
        # stamp and credit bar, and its licence, never on a timeline (src/stockblock.py).
        why = _stockblock.reason(url, str(page or ""), str(thumb or ""), str(title or ""))
        if why:
            _stockblock.note(why, "search", key=url)
            continue
        # DuckDuckGo reports sizes as strings, Serper as ints.
        try:
            w, h = int(w or 0), int(h or 0)
        except (TypeError, ValueError):
            w, h = 0, 0
        # Thumbnails and icons are useless full-frame at 1080p.
        if w and h and (w < 800 or h < 450):
            continue
        # Too small to be sharp full screen even if every pixel were real (src/sharpness.py).
        if big_first and not _sharpness.possible(w, h):
            continue
        out.append(MediaAsset(
            kind="image", source="web_image", url=url, width=int(w or 0),
            height=int(h or 0),
            attribution=(f"{title} — {page}" if page else title)[:300],
            license="unverified — web image, confirm you hold the rights",
            query=query, review_required=True,
            review_reason="Web image: licence unverified",
            page_url=page if str(page).startswith("http") else "",
            thumbnail=thumb if str(thumb).startswith("http") else ""))
        if len(out) >= limit:
            break
    return out


_YANDEX_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# SerpApi searches spent by this job (the plan's monthly quota is small).
_SERPAPI_USED = {"n": 0}


def _serpapi_spent(error) -> None:
    """SerpApi answered 429 / 401 / 403 (the month's searches are used up, or the key is refused): no more
    calls for the rest of this job - each one only costs time."""
    if re.search(r"\b(429|401|403)\b", str(error)):
        with _CACHE_LOCK:
            _SERPAPI_USED["n"] = max(_SERPAPI_USED["n"], config.SERPAPI_MAX_PER_JOB)
            _SERPAPI_VIDEO_USED["n"] = max(_SERPAPI_VIDEO_USED["n"], config.SERPAPI_VIDEO_MAX_PER_JOB)
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
                         it.get("title") or "", it.get("link") or it.get("source") or "",
                         it.get("thumbnail") or ""))
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
    # Bigger than a sharp full-screen picture needs first ("isize=gt": 12 of 13
    # results big enough, against 4 of 6 for "large", 2026-10-04), the large
    # size class after it when that found too few (PICTURE_SHARPNESS_CHECK).
    asks = [{"text": query, "isize": "large"}]
    if _sharpness.picture_on():
        w, h = _sharpness.min_size()
        asks.insert(0, {"text": query, "isize": "gt", "iw": str(w), "ih": str(h)})
    found: List[str] = []
    proxy = _next_proxy()
    for params in asks:
        got: List[str] = []
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
            got = [urllib.parse.unquote(u) for u in re.findall(r"img_url=(https?%3A[^&\"']+)", text)]
            got += re.findall(r'"origUrl":"(https?:[^"]+)"', text)
            if got:
                break
        found += [u for u in got if u not in found]
        if len(found) >= limit:
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
        # Stock sellers' watermarked comps never make a cut (src/stockblock.py).
        host = urllib.parse.urlparse(url).netloc.lower()
        why = _stockblock.reason(url)
        if why:
            _stockblock.note(why, "search", key=url)
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
# Wikimedia's standard thumbnail widths above the frame's (2025: other widths are rate limited).
_COMMONS_STEPS = (1920, 3840)
_THUMB_WIDTH = re.compile(r"/(\d+)px-")


def _commons_full_screen(info: dict) -> Optional[tuple]:
    """
    (url, width, height) of a Wikimedia file at the size a sharp full-screen
    picture needs (PICTURE_SHARPNESS_CHECK): the API's thumbnail (asked for at
    1920 px) when that is enough, else a 3840 px thumbnail of a bigger original
    (a panorama: a cover fit crops it to a band), else the original file itself
    - never a smaller copy when the original holds more. None when even the
    original could not be sharp full screen.
    """
    ow, oh = int(info.get("width") or 0), int(info.get("height") or 0)
    thumb, orig = str(info.get("thumburl") or ""), str(info.get("url") or "")
    tw, th = int(info.get("thumbwidth") or 0), int(info.get("thumbheight") or 0)
    if not ow or not oh:
        return (thumb or orig, tw, th) if (thumb or orig) else None
    if not _sharpness.possible(ow, oh):
        return None
    if thumb and tw and th and _sharpness.possible(tw, th):
        return thumb, tw, th
    for step in _COMMONS_STEPS:
        if step < ow and thumb and _THUMB_WIDTH.search(thumb) and _sharpness.possible(step, oh * step / ow):
            return _THUMB_WIDTH.sub(f"/{step}px-", thumb, count=1), step, int(round(oh * step / ow))
    return (orig, ow, oh) if orig else None


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
    sharp = _sharpness.picture_on()
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            headers={"User-Agent": config.USER_AGENT},
            params={"action": "query", "format": "json", "redirects": 1,
                    "titles": title, "generator": "images", "gimlimit": 50,
                    "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                    # A copy that fills the frame, not a 1280 px one blown up (_commons_full_screen).
                    "iiurlwidth": 1920 if sharp else 1280},
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
        w, h = info.get("thumbwidth") or info.get("width") or 0, info.get("thumbheight") or info.get("height") or 0
        if sharp:
            picked = _commons_full_screen(info)
            if picked is None:
                continue                    # even the original would be blurry full screen
            url, w, h = picked
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "") or "")
        out.append(MediaAsset(
            kind="image", source="wikipedia", url=url,
            width=w,
            height=h,
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
    sharp = _sharpness.picture_on()
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            headers={"User-Agent": config.USER_AGENT},
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": limit,
                "gsrnamespace": 6, "prop": "imageinfo",
                # The original's size too: a copy that fills the frame is picked from it.
                "iiprop": "url|size|extmetadata" if sharp else "url|extmetadata", "iiurlwidth": 1920,
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
        w, h = info.get("thumbwidth", 0), info.get("thumbheight", 0)
        if sharp:
            picked = _commons_full_screen(info)
            if picked is None:
                continue                    # even the original would be blurry full screen
            url, w, h = picked
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        # Commons returns the artist as an HTML fragment with a profile link.
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "") or "")
        out.append(MediaAsset(
            kind="image", source="wikimedia", url=url,
            width=w, height=h,
            attribution=artist.strip()[:200],
            license=meta.get("LicenseShortName", {}).get("value", "") or "see Commons",
            query=query,
        ))
    return out


def openverse_on() -> bool:
    """Openverse is asked for pictures: always while pictures need not be sharp full
    screen, and with PICTURE_SHARPNESS_CHECK on only when OPENVERSE_WHEN_SHARP says so -
    it serves Flickr's 1024 px copies (its listed size is the original's), and none of
    24 passed the real-detail check on Yellowstone searches (2026-10-04)."""
    return bool(getattr(config, "OPENVERSE_WHEN_SHARP", False)) or not _sharpness.picture_on()


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
    # A new file per generation. Named after the prompt alone, two scenes
    # with one prompt wrote the same file and so showed the same image (its
    # identity is the path) - part of the owner's "7 generated scenes, 4
    # images" (2026-09-30).
    dest = os.path.join(out_dir, f"gen_{safe}_{uuid.uuid4().hex[:12]}.png")
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
# Set while sourcing a scene of the opening (the job's "hook" flag: a hook
# beat of the brief, or a line that starts within config.HOOK_SECONDS). The
# owner's Texas flood video (2026-09-30) opened on 4 AI illustrations in its
# first 5 scenes: a hook scene is never generated (_generation_budget_left)
# unless GENERATED_IMAGES_IN_HOOK, and it judges more candidates and keeps
# the best of more passes (_judge_limits).
_IN_HOOK: contextvars.ContextVar = contextvars.ContextVar("in_hook", default=False)
# The seconds of a clip its scene shows, while a hook scene is sourced or
# checked: the judge's opening check looks at the clip's first moment, middle
# and end of that span (vision.judge `span`, src/hookcheck.py) - the owner's
# Glen Canyon test (2026-10-05) opened on 1.4 s of another shot the judge's
# frames at a quarter, a half and three quarters of the clip never saw.
_SHOWN_SECONDS: contextvars.ContextVar = contextvars.ContextVar("shown_seconds", default=None)


def _opening_span(path: str) -> Optional[float]:
    """The span the judge's opening check reads for `path` here, or None (not a hook clip, or the check is off)."""
    if not (_IN_HOOK.get() and getattr(config, "HOOK_CUT_CHECK", False)) or _is_still(path):
        return None
    try:
        span = float(_SHOWN_SECONDS.get() or 0.0)
    except (TypeError, ValueError):
        return None
    return span if span > 0 else None


# "month" (or "week") for a line of a story about now: YouTube's and
# Dailymotion's uploads of the last month are searched first, and older
# uploads only when nothing recent passes (config.RECENT_FOOTAGE_FIRST).
_RECENCY: contextvars.ContextVar = contextvars.ContextVar("recency", default="")
# Set while a clip-first line is sourced (config.CLIPS_FIRST): its own, larger vision budget and
# scouts (_judge_limits), and its candidates' metadata read before any scout (_prequalified).
_CLIP_FIRST: contextvars.ContextVar = contextvars.ContextVar("clip_first", default=False)
# Set while one of a clip-first line's wider rungs is searched (clip_rungs): {"label": the subject the
# rung names}. Its YouTube search is a fresh one (not the subject's cached list) and its candidates are
# judged as "shows that subject" (_rung_judging) instead of "this exact moment".
_RUNG: contextvars.ContextVar = contextvars.ContextVar("rung", default=None)
# Which of a clip-first line's own wordings is searched (0 = its first): the second and third are NEW
# searches of their own words - answered from the subject's cached list, they only re-ranked the first
# wording's candidates (the review of 2026-10-06).
_WORDING: contextvars.ContextVar = contextvars.ContextVar("wording", default=0)
# A list a scene's YouTube search reports to (src/reclip.py's per-scene trace: each search, each download,
# filter and verdict - the Obama re-clip of 2026-10-07 found 8 clips in 110 lines and left no record of why).
# None = off.
_TRACE: contextvars.ContextVar = contextvars.ContextVar("trace", default=None)
TRACE_ROWS = 60


def _flags_of(verdict: Optional[dict]) -> str:
    """The hard flags a verdict raised, in a few words ("" = none)."""
    v = verdict or {}
    names = (("has_text_or_watermark", "text/watermark"), ("is_talking_head", "talking head"),
             ("ai_generated", "AI-made"), ("studio", "studio"), ("music_or_vice", "music/vice"),
             ("off_topic", "off the story"))
    flags = [label for key, label in names if v.get(key)]
    if v.get("opening") is False:
        flags.append("opening frame")
    # The quality floor turned a well-scored shot down too (the Obama apply: 0.8 and 0.9 verdicts gone with
    # no reason in the trace).
    q = v.get("quality")
    if isinstance(q, (int, float)) and q < _quality_floor():
        flags.append(f"quality {q:.2f}")
    return ", ".join(flags)


def _quality_floor() -> float:
    """The judge's quality floor for this line: a period line's (PERIOD_MIN_QUALITY) - the era's broadcast
    video reads soft to the judge - else VISION_MIN_QUALITY."""
    if _period_line():
        return float(getattr(config, "PERIOD_MIN_QUALITY", config.VISION_MIN_QUALITY))
    return float(config.VISION_MIN_QUALITY)


def _trace(**row) -> None:
    """One row of this scene's trace (when a caller asked for one)."""
    got = _TRACE.get()
    if got is not None and len(got) < TRACE_ROWS:
        got.append({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()
                    if v is not None and v != ""})


# (query, subject) of every line whose clip-first search ran all its clip stages in this job without
# being stopped: the rescue pass's judged search asks it again only for the lines that ran out of time.
_CLIP_SEARCHED: set = set()


def _searched_key(query: str, subject: str = "") -> tuple:
    return (" ".join(str(query or "").split()).lower(), " ".join(str(subject or "").split()).lower())



# Stock libraries upload watermarked previews to YouTube (ZapataStock,
# FootageForPro... filled a real video with logo-stamped dolphins and
# Statues of Liberty). Their titles and channel names give them away.
_STOCK_SELLER = re.compile(
    r"stock (?:footage|video|clip)|footage ?for ?pro|zapata|pond5|storyblocks|"
    r"shutterstock|videoblocks|videohive|envato|artgrid|artlist|motion ?array|"
    r"getty ?images|istock|adobe ?stock|dissolve|filmsupply|framepool|"
    r"christoryman|royalty[- ]free|free (?:stock|footage)|no copyright",
    re.IGNORECASE)


def _usable_title(title: str, channel: str = "", aspect: float = 0.0, context: str = "") -> bool:
    """
    The one title-and-shape check every source applies before spending
    anything: not a stock seller's listing, not a talking head, not
    vertical. It was written five times with small drifts between them.
    Not a music video, a lyric / audio upload or a rap performance either,
    unless the story or the line (`context`) is about music (src/topics.py;
    the owner, 2026-10-06: rapper clips in a story about his brothers).
    """
    if _stock_seller(title or "", channel or ""):
        return False
    from . import topics
    if topics.off_topic_title(title or "", channel or "", line=context or ""):
        return False
    if _talking_head(title or "", context or ""):
        return False
    if aspect and aspect < 1.2 and not config.ALLOW_VERTICAL:
        return False                        # vertical, unusable in 16:9
    # AI-made (an "AI story", Sora, Midjourney...) or a game: never real footage (src/slop.py).
    from . import slop
    if slop.enabled() and slop.metadata_reason(title, channel):
        return False
    return True


def _stock_seller(*texts: str) -> bool:
    return any(t and _STOCK_SELLER.search(t) for t in texts)


_NEWS_WORDS = {"news", "interview", "press conference", "briefing"}


# A named person's own appearances: on a line about that person, these words name the footage wanted, not a
# creator talking about them (the vision judge still turns down an anchor desk or another face).
_PERSON_WORDS = re.compile(r"^(?:interview|debate|panel|discussion|responds?|talks? about|sits? down with|"
                           r"speaks? (?:out|to)|breaks? (?:down|silence)|on (?:cnn|fox|msnbc|abc|nbc|cbs)|"
                           r"news|press conference|briefing)$", re.I)


def _talking_head(title: str, line: str = "") -> bool:
    """
    True when the title disqualifies a candidate.

    For a recent event story the bare word "news" does not: "Drone video shows
    flooding in Davenport | WQAD News 8" is exactly the footage wanted. Anchors,
    press conferences, interviews and the rest still disqualify, and the vision
    judge still rejects an anchor desk or burned-in text on the actual frames.

    Nor does a word the `line` itself uses: a line about the 2016 debate wants
    "... Presidential Debate" uploads - every one of them was turned away on its
    title, and the Obama re-clip's opening (two lines about that debate) had no
    candidate left (2026-10-07). On a line about a named person, that person's own
    appearances (an interview, a debate, a panel, "speaks out") are the footage.
    """
    hits = [m.group(1).lower() for m in _TALKING_HEAD.finditer(title or "")]
    if _EVENT_WINDOW.get():
        hits = [h for h in hits if h != "news"]
    if config.NEWS_FOOTAGE:
        # News reports, interviews and press conferences are what GoMotion
        # shows for the event a line names; the judge still rejects an anchor
        # at a studio desk on the actual frames.
        hits = [h for h in hits if h not in _NEWS_WORDS]
    if hits and line:
        said = f" {' '.join(re.findall(r'[a-z0-9&]+', line.lower()))} "
        hits = [h for h in hits if f" {' '.join(re.findall(r'[a-z0-9&]+', h))} " not in said]
    if hits and _SUBJECT_TYPE.get() == "person":
        hits = [h for h in hits if not _PERSON_WORDS.match(h)]
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

# A line whose wanted shots ask for a map, or for a chart / diagram / cross-section /
# graphic (the director's "Idaho map", "state outlines", "cross-section graphic",
# "comparison graphic"): a real published one is the shot for it. Scene intents carry
# no visual type of their own, so such a line was treated like any other - its maps
# turned down as TV weather maps, its diagrams as slides - and 8 of the Yellowstone
# re-cut's 16 hardest still lines (2026-10-04) were lines like these.
_WANTS_MAP = re.compile(r"\b(?:maps?|outlines?)\b", re.I)
_WANTS_CHART = re.compile(r"\b(?:charts?|graphs?|graphics?|infographics?|diagrams?|cross[- ]?sections?)\b", re.I)


def wanted_kind(scene_intent: Optional[dict] = None) -> str:
    """"map", "chart" or "document" when this line asks for that kind of picture, else "": the
    scene intent's own visual type, else the words of its wanted shots and visual subjects.
    Without an argument, the intent of the scene being sourced on this thread."""
    si = _SCENE_INTENT.get() if scene_intent is None else scene_intent
    if not isinstance(si, dict):
        return ""
    v = str(si.get("visualType") or si.get("visual_type") or "").lower()
    if v in ("map", "chart", "document"):
        return v
    words = []
    for key in ("desired_shots", "visual_subjects"):
        vals = si.get(key)
        vals = [vals] if isinstance(vals, str) else (vals if isinstance(vals, (list, tuple)) else [])
        words += [str(x) for x in vals if isinstance(x, str)]
    blob = " ".join(words)
    if _WANTS_MAP.search(blob):
        return "map"
    if _WANTS_CHART.search(blob):
        return "chart"
    return ""


def _local_check(path: str, intent_text: str) -> Optional[dict]:
    """The local model's verdict for this scene's candidate, or None when the
    model is not installed (tests, a laptop without /opt/models)."""
    if not config.LOCAL_VISION_ENABLED or not _localvision.available():
        return None
    si = _SCENE_INTENT.get() or {}
    return _localvision.check(path, intent_text, subject_type=_SUBJECT_TYPE.get() or "",
                              subject=str((si or {}).get("subject") or "") if isinstance(si, dict) else "",
                              wants=wanted_kind())


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


# Candidates the AI-slop / not-footage filters turned down, by reason (job stats).
SLOP_REJECTED: Dict[str, int] = {}

# Candidates found unusable for a reason that holds for every line - generated
# or painted, a slideshow or a held still, another creator's captions, burned-in
# text, a download that will not play - by source video ("yt:<id>", "dm:<id>"),
# by moment ("yt:<id>@<10 s bucket>") or by picture: every other scene skips
# them instead of downloading and checking them again. The Lake Powell job
# (2026-10-01) fetched one Dailymotion section at least four times and could
# not read it any time. A studio or a TV map is not here: a line about a named
# person or one asking for a map may use it.
_BAD: Dict[str, str] = {}
# A paid verdict that turns a candidate down for every line (JUDGE_MEMORY): remembered for
# that moment of a clip, or that picture - never the whole video on one verdict.
_JUDGED_LINE_FREE = "judged unusable for any line"
_LINE_FREE = ("an AI-generated", "AI-made or a game", "an AI picture site", "a still with a slow pan or zoom",
              "a slideshow of stills", "a frozen", "another creator's burned-in captions", "burned-in text or UI",
              "a download that will not play",
              # A stock agency's credit bar or stamp (src/stockblock.py) is on the picture whatever the line.
              "an agency credit bar", "an agency watermark",
              # Too soft for the frame (src/sharpness.py): a property of the file, whatever the line.
              "a blurry picture", "low detail",
              _JUDGED_LINE_FREE)
# An upscaled upload is soft in every moment of it.
_VIDEO_WIDE = ("an AI-generated", "AI-made or a game", "an AI picture site", "a download that will not play",
               "low detail")
# The AI-slop filter's reason for the gate's last rejection on this thread ("" = not slop).
_GATE_SLOP: contextvars.ContextVar = contextvars.ContextVar("gate_slop", default="")


def _is_bad(*keys: str) -> str:
    """Why one of these candidates is unusable for any line ("" = not known to be)."""
    with _CACHE_LOCK:
        return next((_BAD[k] for k in keys if k and k in _BAD), "")


def _mark_bad(video: str, moment: str, why: str) -> None:
    """Remember a line-independent rejection: for the whole source video when the
    reason covers it (generated, unreadable), else for that moment only."""
    if not why or not why.startswith(_LINE_FREE):
        return
    key = video if why.startswith(_VIDEO_WIDE) or not moment else moment
    with _CACHE_LOCK:
        if len(_BAD) > 20000:
            _BAD.clear()
        _BAD[key] = why[:80]


def judge_clip(path: str, job: Dict[str, Any], label: str = "", source_url: str = "",
               shown: Optional[float] = None) -> tuple:
    """
    (keep, verdict) for a clip found outside the per-scene search (a subject
    pool's moment): the same gate a searched clip passes - the AI-slop and
    not-footage filters, the local model and the vision judge - against the
    line's own intent, place and event. A hook line's clip gets the opening
    check on the `shown` seconds its scene plays (the line's own seconds when
    not given).
    """
    span = shown if shown is not None else job.get("seconds")
    tokens = [(_SUBJECT_TYPE, _SUBJECT_TYPE.set(job.get("subject_type") or "")),
              (_EVENT_WINDOW, _EVENT_WINDOW.set(job.get("event_window") or "")),
              (_SCENE_INTENT, _SCENE_INTENT.set(job.get("scene_intent") or None)),
              (_IN_HOOK, _IN_HOOK.set(bool(job.get("hook")))),
              (_SHOWN_SECONDS, _SHOWN_SECONDS.set(span))]
    try:
        return _vision_gate(path, job.get("intent") or job.get("query") or "", job.get("context") or "", label,
                            source_url)
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


# Photo desks and archives whose pictures are real (the label carries the
# source: "... | AP News", "... | Bureau of Reclamation", "static.independent.co.uk").
# Red-rock desert and saturated lake photos read as "painted" to CLIP: on
# 2026-10-01 it threw out an AP News Lake Powell photo and a Wikimedia Glen
# Canyon Dam one. The vision judge still looks at them.
_REAL_PHOTO_SOURCE = re.compile(
    r"\b(?:AP News|Associated Press|AP Photo|apnews|Reuters|Getty|AFP|EPA|USGS|Bureau of Reclamation|usbr|"
    r"National Park Service|nps\.gov|NOAA|NASA|Wikimedia|Wikipedia|commons|CNN|NBC|CBS|ABC News|Fox News|BBC|"
    r"New York Times|nytimes|Washington Post|washingtonpost|Guardian|independent\.co\.uk|Axios|Los Angeles Times|"
    r"latimes|Salt Lake Tribune|sltrib|KSL|azcentral|Arizona Republic|Deseret|AccuWeather|weather\.com|"
    r"National Geographic|nationalgeographic|Smithsonian|NPR|PBS|USA Today|Bloomberg|Al Jazeera)\b", re.I)


def _real_photo_source(label: str = "", source_url: str = "") -> bool:
    """A picture from a photo desk or archive, by its label or by the host it came
    from (assets.science.nasa.gov, npr.brightspotcdn.com, upload.wikimedia.org)."""
    host = urllib.parse.urlparse(source_url or "").netloc if str(source_url or "").startswith("http") else ""
    return bool(_REAL_PHOTO_SOURCE.search(label or "") or (host and _REAL_PHOTO_SOURCE.search(host)))


def slop_reason(path: str, label: str = "", source_url: str = "") -> str:
    """Why src/slop.py turns a downloaded candidate down for this scene ("" = keep), counted.
    `source_url`: where a picture was downloaded from (its host can name the photo desk)."""
    from . import slop
    if not slop.enabled():
        return ""
    wants = wanted_kind()
    kind = "image" if _is_still(path) else "video"
    try:
        why = slop.metadata_reason(label) or slop.check_file(
            path, kind, allow_people=_SUBJECT_TYPE.get() == "person",
            allow_maps=wants in ("map", "chart", "document") or _SUBJECT_TYPE.get() == "document")
    except Exception as e:  # noqa: BLE001 - a filter error never drops a clip
        print(f"[slop] check failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return ""
    # Only CLIP's reading of the colours is waived for a photo desk - and for a
    # line that asks for a map or a diagram, whose published pictures are drawn
    # (CLIP reads an agency's cross-section as "an illustration"); the vision
    # judge still turns down an AI-made one. A picture whose own content
    # credentials say "generated" never is.
    if why.startswith("an AI-generated or painted picture") and kind == "image" \
            and (_real_photo_source(label, source_url) or wants in ("map", "chart")):
        why = ""
    if why:
        with _CACHE_LOCK:
            key = why.split(" (")[0]
            SLOP_REJECTED[key] = SLOP_REJECTED.get(key, 0) + 1
    return why


def watermark_reason(path: str, where: str = "", bar: bool = True, stamp: bool = True) -> str:
    """Why a downloaded picture's pixels say it is a stock agency's preview ("" = keep; "" for a clip), counted.
    `bar` (free) / `stamp` (the local CLIP model, ~0.7 s): which checks run (src/stockblock.py)."""
    if not path or not _stockblock.is_still(path):
        return ""
    try:
        why = _stockblock.watermark_reason(path, bar=bar, stamp=stamp)
    except Exception as e:  # noqa: BLE001 - a check error never drops a picture
        print(f"[stockblock] check failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return ""
    if why:
        _stockblock.note_watermark(why, where)
    return why


def judged_line_free(verdict: Optional[dict], allow_vice: bool = True) -> str:
    """
    Why a paid verdict turns its candidate down for EVERY line ("" = for this line
    only, or kept): what vision.acceptable rejects whatever the line and whoever it
    names - other people's text or a watermark, an AI-made picture, footage too poor
    to show (the judge rates quality "whatever the subject"). A studio or talking head
    is not here: a line about a named person may use it; nor a low score, which is
    about this line's intent.

    A music performance, a club or a smoking / drugs / drinking scene (the judge's
    music_or_vice) is here when the story and the line are not about it
    (allow_vice False: src/topics.py): that moment is never judged again in this job.
    """
    if not verdict:
        return ""
    if verdict.get("has_text_or_watermark"):
        return f"{_JUDGED_LINE_FREE}: text or watermark"
    if verdict.get("ai_generated"):
        return f"{_JUDGED_LINE_FREE}: AI-made"
    if verdict.get("music_or_vice") and not allow_vice:
        return f"{_JUDGED_LINE_FREE}: a music, club or smoking scene off the story"
    quality = verdict.get("quality")
    if quality is not None and quality < config.VISION_MIN_QUALITY:
        return f"{_JUDGED_LINE_FREE}: too poor to show"
    return ""


def off_story(verdict: Optional[dict], line: str) -> bool:
    """The judge saw a music performance, a club or a smoking / drugs / drinking scene, and neither the
    story nor this line is about it (src/topics.py): a clear no, never the 'best available'."""
    if not verdict or not verdict.get("music_or_vice"):
        return False
    from . import topics
    return not topics.allows_vice(line)


def _vision_gate(path: str, intent: str, context: str, label: str, source_url: str = "") -> tuple:
    """
    (keep, verdict) for a downloaded candidate.

    No intent means nothing to judge against, and an unreachable model returns
    None — both keep the candidate, so vision can only ever remove bad clips,
    never empty a timeline because an API is down.

    Before any of it, the AI-slop and not-footage filters (src/slop.py): an
    AI-made or painted picture, a still or slideshow posing as footage,
    another creator's captions, a TV studio, presenter, stream or TV map is
    turned down on the spot, intent or not (the owner, 2026-09-30).

    A picture's own pixels are read for a stock agency's mark whether or not
    any model judges it (src/stockblock.py; the owner, 2026-10-04: "the images
    it is using are sometimes watermarked images, like Getty ... Alamy"): the
    free credit-bar check first, the slower stamp check (the local CLIP model,
    ~0.7 s) only on a picture about to be kept - the judge sees a still 384 px
    wide, where a faint stamp is nearly invisible.
    """
    t0 = time.time()
    try:
        why = watermark_reason(path, "gate", stamp=False)
        if why:
            _GATE_SLOP.set(why)
            print(f"[stockblock] REJECT {why}: {label[:60]!r}", flush=True)
            return False, None
        keep, verdict = _judge_gate(path, intent, context, label, source_url)
        if keep:
            why = watermark_reason(path, "gate", bar=False)
            if why:
                _GATE_SLOP.set(why)
                print(f"[stockblock] REJECT {why}: {label[:60]!r}", flush=True)
                return False, None
        return keep, verdict
    finally:
        _stage(f"gate:{'picture' if _is_still(path) else 'clip'}", time.time() - t0)


def _judge_gate(path: str, intent: str, context: str, label: str, source_url: str = "") -> tuple:
    """_vision_gate after the credit bar: the AI-slop filters, the local model, the vision judge."""
    why = slop_reason(path, label, source_url)
    _GATE_SLOP.set(why)
    if why:
        print(f"[slop] REJECT {why}: {label[:60]!r}", flush=True)
        return False, None
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
    wants = wanted_kind()
    # The line as written (before a rung rewrites the intent): what the topic rules read (src/topics.py).
    line = f"{intent} {context}"
    # A clip in the hook: the judge looks at its first moment, middle and end, and says whether the
    # first frame itself fits (vision.judge `span`; src/hookcheck.py) - same one call.
    span = _opening_span(path)
    # A wider rung of a clip-first line (clip_rungs): judged as "shows the subject it names",
    # never against the exact moment, and never under the one-event rule.
    event = bool(_EVENT_WINDOW.get())
    rung = _RUNG.get()
    if rung and not _is_still(path):
        intent, scene, event = rung_judging(intent, scene, rung)
    # A line asking for a map or a diagram: the judge is told a real published one is acceptable
    # (real footage or a photo that fits stays just as good - the INTENT decides).
    verdict = vision.judge(path, intent, context, event=event,
                           **({"scene": scene} if scene else {}),
                           **({"wants": wants} if wants in ("map", "chart") else {}),
                           **({"span": span} if span else {}))
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
    allow_vice = not off_story(verdict, line)
    keep = vision.acceptable(verdict, allow_people=_SUBJECT_TYPE.get() == "person", allow_vice=allow_vice,
                             min_quality=_quality_floor())
    if verdict is not None and not allow_vice:
        # A music, club or smoking scene the story is not about: a clear no for the near-miss
        # and opening checks too (a copy - the cached verdict stays as the model answered).
        verdict = dict(verdict, off_topic=True)
        print(f"[vision] REJECT a music, club or smoking scene off the story: {label[:60]!r}", flush=True)
    if not keep and verdict is not None and config.JUDGE_MEMORY:
        # Turned down for a reason no other line can change: every caller remembers it
        # (_mark_bad with the gate's reason), so no other scene pays for this answer again.
        why = judged_line_free(verdict, allow_vice=allow_vice)
        if why:
            _GATE_SLOP.set(why)
    if verdict is not None and verdict.get("frames"):
        # The opening check's own decision goes with the verdict (a copy: the cached one stays as the
        # model answered) - the scene keeps it (MediaAsset.cut_check) and src/hookcheck.py reads it.
        verdict = dict(verdict, accepted=keep)
    if verdict is not None:
        mark = "keep" if keep else "REJECT"
        flags = []
        if verdict["has_text_or_watermark"]:
            flags.append("text/watermark")
        if verdict["is_talking_head"]:
            flags.append("talking head")
        if verdict.get("quality") is not None:
            flags.append(f"quality {verdict['quality']:.2f}")
        if verdict.get("opening") is False:
            flags.append("opening frame does not fit")
        print(f"[vision] {mark} {verdict['score']:.2f} {label[:50]!r}"
              f"{' (' + ', '.join(flags) + ')' if flags else ''}"
              f" — {verdict['description'][:90]}", flush=True)
    return keep, verdict


# --------------------------------------------------------------------------- #
# The Nature & Weather edit (src/styles.py): eyewitness titles, motion, photos
# --------------------------------------------------------------------------- #

# What eyewitness footage of an event is called on YouTube and TikTok: phone,
# drone, storm-chaser and news-helicopter video (config.EYEWITNESS_SEARCHES).
_EYEWITNESS = re.compile(
    r"\b(caught on (?:camera|video|tape)|video shows|viewer (?:video|submitted)|phone video|cell ?phone|"
    r"dash ?cam|ring (?:camera|doorbell)|storm chas\w+|chaser|helicopter|chopper|sky ?\d+|drone|"
    r"eyewitness|witness(?:es)?|raw (?:video|footage)|live (?:look|view|cam)|web ?cam|timelapse|"
    r"this morning|right now)\b", re.I)
# A compilation mixes other storms and other places; a "top 10" ranks them.
_COMPILATION = re.compile(r"\b(compilation|top \d+|worst \w+ (?:ever|of all time)|most (?:shocking|terrifying|"
                          r"insane|extreme)|scariest|best of|caught on camera compilation|mother nature'?s)\b",
                          re.I)


def eyewitness_bonus(title: str) -> float:
    """Title evidence that a clip is an eyewitness recording of the event (+1.5), or a compilation (-2)."""
    if not config.EYEWITNESS_SEARCHES:
        return 0.0
    t = title or ""
    if _COMPILATION.search(t):
        return -2.0
    return 1.5 if _EYEWITNESS.search(t) else 0.0


# --------------------------------------------------------------------------- #
# Another place, storm, kind of weather or year in the title (the Texas test)
# --------------------------------------------------------------------------- #
#
# The Texas flood-threat test (2026-09-30, news_compilation) showed "RUIDOSO,
# NM", "VENTURA COUNTY", "CAMERON, LOUISIANA", the 2021 Fort Worth I-35 ice
# pileup and 2020's "Tropical Storm Edouard" under a Texas rain story. For an
# event story (news, weather, disaster, or a story about now) a candidate
# whose title names another US state or country than the story and the line,
# another named storm, another kind of weather, or another year is not
# looked at. On-screen chyrons are the vision judge's (src/vision.py).

_COUNTRIES = (
    "mexico canada india pakistan bangladesh china japan philippines indonesia italy spain france germany "
    "england britain scotland wales ireland australia brazil turkey greece libya nigeria kenya vietnam "
    "thailand malaysia korea taiwan russia ukraine poland romania dubai emirates saudi iran afghanistan nepal "
    "sri lanka chile peru colombia argentina venezuela cuba haiti jamaica bahamas zealand portugal austria "
    "switzerland slovenia croatia belgium netherlands norway sweden egypt morocco algeria sudan ethiopia "
    "somalia congo ghana singapore hong kong myanmar cambodia laos mongolia kazakhstan uzbekistan iraq syria "
    "israel lebanon jordan yemen oman qatar kuwait bosnia serbia hungary slovakia czech bulgaria albania "
    "guatemala honduras nicaragua salvador panama ecuador bolivia paraguay uruguay dominican")
_COUNTRY_RE = re.compile(r"\b(" + "|".join(sorted({c for c in _COUNTRIES.split(" ") if len(c) > 3} |
                                                  {"sri lanka", "hong kong", "new zealand", "united kingdom",
                                                   "south africa", "north korea", "south korea",
                                                   "costa rica", "puerto rico"}, key=len, reverse=True))
                         + r")\b", re.I)
_NAMED_STORM = re.compile(r"\b(?:[Hh]urricane|HURRICANE|[Tt]ropical [Ss]torm|TROPICAL STORM|[Tt]ropical [Dd]epression|"
                          r"[Tt]yphoon|TYPHOON|[Ss]uper [Tt]yphoon|[Cc]yclone|CYCLONE|[Ww]inter [Ss]torm|WINTER STORM)"
                          r"\s+([A-Z][A-Za-z]{2,})\b")
_NOT_STORM_NAMES = {"surge", "damage", "chaser", "chasers", "team", "tracker", "update", "warning", "watch",
                    "season", "center", "centre", "coverage", "footage", "video", "news", "live", "alert",
                    "shelter", "cleanup", "recovery", "impact", "impacts", "system", "cell", "front", "drain",
                    "drains", "prep", "preps", "preparations", "hits", "slams", "brings", "flooding", "floods",
                    "prediction", "watches", "warnings", "landfall", "makes", "making", "remnants", "force"}
# Kinds of weather a title can name that a story about something else must not show.
_WEATHER_KINDS = {
    "winter": re.compile(r"\b(snow\w*|blizzard\w*|ice storm|icy|black ice|freez\w*|sleet|frost\w*|"
                         r"winter storm|pile-?ups?|avalanche)\b", re.I),
    "fire": re.compile(r"\b(wild ?fires?|brush ?fires?|forest ?fires?|bush ?fires?|blaze|burn scar|"
                       r"inferno|evacuation fire)\b", re.I),
    "tornado": re.compile(r"\b(tornado\w*|twisters?|funnel cloud)\b", re.I),
    "tropical": re.compile(r"\b(hurricane\w*|tropical storm|tropical depression|typhoon\w*|cyclone\w*)\b", re.I),
    "quake": re.compile(r"\b(earthquake\w*|quake|tsunami\w*)\b", re.I),
    "heat": re.compile(r"\b(heat ?wave\w*|extreme heat|heat dome)\b", re.I),
    "drought": re.compile(r"\b(drought\w*|dried up|dry lake)\b", re.I),
}
_TITLE_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def _state_names() -> Dict[str, str]:
    from .official import _ABBR
    return dict(_ABBR)


def _regions_in(text: str, codes: bool = False) -> set:
    """US states and countries a text names (states as their full lower-case names)."""
    out: set = set()
    t = text or ""
    low = f" {t.lower()} "
    abbr = _state_names()
    for name in abbr.values():
        if re.search(rf"\b{re.escape(name)}\b", low):
            out.add(name)
    # "Washington, D.C." is not the state; "Kansas City" is Missouri's too - left as named.
    if "washington" in out and re.search(r"washington,? d\.?c\.?", low):
        out.discard("washington")
    if codes:
        # A postal code after a comma or in capitals on its own: "RUIDOSO, NM", "Norfolk VA".
        for m in re.finditer(r"(?:,\s*|\s)([A-Z]{2})\b(?![a-z])", t):
            name = abbr.get(m.group(1))
            if name and m.group(1) not in ("IN", "OR", "ME", "OK", "HI", "US", "AL", "LA", "PA", "MA", "DE",
                                           "CO", "MO", "ID", "MI"):
                out.add(name)
            elif name and re.search(rf",\s*{m.group(1)}\b", t):
                out.add(name)
    # "New Mexico" is a state, not the country.
    for m in _COUNTRY_RE.finditer(re.sub(r"(?i)new mexico", " ", t)):
        out.add(m.group(1).lower())
    return out


def _story_blob(context: str = "") -> tuple:
    """(story brief, its text: event, summary, places, title and the line) for the title checks."""
    try:
        from . import director
        brief = dict(director.LAST_STORY or {})
    except Exception:  # noqa: BLE001
        brief = {}
    si = _SCENE_INTENT.get() or {}
    locs = si.get("locations") if isinstance(si, dict) else None
    parts = [brief.get("event") or "", brief.get("summary") or "", " ".join(brief.get("places") or []),
             " ".join(locs or []), context or ""]
    return brief, " ".join(p for p in parts if p)


def _event_story(brief: dict) -> bool:
    if not config.NEWS_FOOTAGE or not isinstance(brief, dict) or not brief:
        return False
    try:
        from . import director
        return brief.get("kind") in director.EVENT_KINDS or bool(director.current_story(brief))
    except Exception:  # noqa: BLE001
        return False


def title_conflict(title: str, context: str = "") -> str:
    """
    Why a candidate's title rules it out for this event story's line ("" =
    fine): another US state or country than the story's and the line's,
    another named storm, another kind of weather than the story talks about,
    or another year than the story's (the line's own years excepted).
    """
    t = str(title or "")
    if not t:
        return ""
    brief, story = _story_blob(context)
    if not _event_story(brief):
        return ""
    want = _regions_in(story, codes=True)
    named = _regions_in(t, codes=True)
    if want and named and not (named & want):
        return f"another place ({', '.join(sorted(named))[:40]})"
    for m in _NAMED_STORM.finditer(t):
        name = m.group(1)
        if name.lower() in _NOT_STORM_NAMES:
            continue
        if not re.search(rf"\b{re.escape(name)}\b", story, re.I):
            return f"another named storm ({name})"
    for kind, pattern in _WEATHER_KINDS.items():
        if pattern.search(t) and not pattern.search(story):
            return f"another kind of event ({kind})"
    year = brief.get("year")
    if isinstance(year, int) and not isinstance(year, bool):
        own = {int(y) for y in _TITLE_YEAR.findall(story)} | {year}
        years = {int(y) for y in _TITLE_YEAR.findall(t)}
        if years and not (years & own):
            return f"another year ({min(years)})"
    return ""


def upload_conflict(info: Optional[dict], older_ok_years: int = 0) -> str:
    """
    An upload that cannot show this event: named for AI (src/slop.py
    metadata), or - for a line that must show this event in a story about
    now - uploaded before the story's year. `older_ok_years`: a subject pool
    for a named place (a landmark, a dam) takes uploads this many years older.
    """
    if not isinstance(info, dict):
        return ""
    from . import slop
    why = slop.metadata_reason(info.get("title"), info.get("channel") or info.get("uploader"),
                               str(info.get("description") or "")[:800], " ".join(info.get("tags") or [])[:400])
    if why:
        return why
    brief, _story = _story_blob()
    if not _event_story(brief):
        return ""
    si = _SCENE_INTENT.get() or {}
    if isinstance(si, dict) and si.get("specificity") not in (None, "", "event"):
        return ""                               # a place or illustrative shot may be older
    year = brief.get("year")
    up = str(info.get("upload_date") or "")
    if isinstance(year, int) and not isinstance(year, bool) and re.fullmatch(r"\d{8}", up):
        grace = max(1 if datetime.date.today().month <= 2 else 0, int(older_ok_years or 0))
        if int(up[:4]) < year - grace:
            return f"uploaded in {up[:4]}, before this {year} story"
    return ""


# Measured motion of a cut clip (config.MOTION_PREFERENCE): mean change
# between 5 frames at 160x90, median over the 4 gaps, so one shot change
# inside the cut does not count as action.
MOTION_FRAMES = 5
MOTION_FULL = 12.0        # mean grey change that counts as full motion (a wave, a rushing street)
MOTION_FLOOR = 1.5        # below this the shot is nearly still


def motion_of(path: str) -> Optional[dict]:
    """
    {"motion": 0..1, "raw", "static", "slideshow"} of a clip, or None when it
    cannot be read (a still, a missing file, no ffmpeg). Four gaps between
    five frames at 160 px - a few milliseconds of numpy after one ffmpeg call.
    """
    p = str(path or "")
    if not p or not os.path.isfile(p) or _is_still(p):
        return None
    try:
        key = f"{p}|{os.path.getsize(p)}|{os.path.getmtime(p)}"
    except OSError:
        return None
    with _MOTION_LOCK:
        if key in _MOTION_CACHE:
            return _MOTION_CACHE[key]
    try:
        import numpy as np
        frames = _filters._gray_frames(p, MOTION_FRAMES, 160, 90)
    except Exception:  # noqa: BLE001 - unmeasured is neutral
        frames = []
    got = None
    if len(frames) >= 3:
        diffs = [float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) for a, b in zip(frames, frames[1:])]
        raw = sorted(diffs)[len(diffs) // 2]
        still = sum(1 for d in diffs if d < 0.8)
        got = {"motion": round(max(0.0, min(1.0, (raw - MOTION_FLOOR) / (MOTION_FULL - MOTION_FLOOR))), 3),
               "raw": round(raw, 2),
               "static": max(diffs) < 1.2,
               "slideshow": still >= max(2, len(diffs) - 2) and any(d > 20 for d in diffs)}
    with _MOTION_LOCK:
        _MOTION_CACHE[key] = got
    return got


_MOTION_CACHE: Dict[str, Optional[dict]] = {}
_MOTION_LOCK = threading.Lock()


def _motion_weight(hook: Optional[bool] = None) -> float:
    w = max(0.0, float(config.MOTION_PREFERENCE or 0.0))
    in_hook = _IN_HOOK.get() if hook is None else hook
    if in_hook:
        # The opening prefers footage that moves even where MOTION_PREFERENCE is 0 (the owner,
        # 2026-10-06: the start must use better clips): HOOK_MOTION_WEIGHT, or the hook booster's
        # own weight (src/hookboost.py) when that is on and bigger.
        w = max(w, float(getattr(config, "HOOK_MOTION_WEIGHT", 0.0) or 0.0))
        if getattr(config, "HOOK_BOOST", False):
            from . import hookboost
            w = max(w, hookboost.motion_weight())
    return w * (2.0 if in_hook else 1.0)


def motion_rejects(path: str) -> str:
    """Why a clip is turned down on its motion ("" = kept): a frozen shot or a slideshow, with MOTION_PREFERENCE on."""
    if not config.MOTION_PREFERENCE:
        return ""
    m = motion_of(path)
    if m is None:
        return ""
    if m["slideshow"]:
        return "a slideshow of stills"
    if m["static"]:
        return "a frozen, motionless shot"
    return ""


def apply_motion(asset: "MediaAsset", measured: Optional[dict] = None) -> Optional[dict]:
    """
    Fold measured motion into a passed clip's combined score: +/- the weight
    around the middle, doubled in the hook, a still shot at the full penalty.
    Returns the measure (None when unmeasured or the preference is off).
    """
    w = _motion_weight()
    if not w or asset is None or asset.kind != "video":
        return None
    m = measured if measured is not None else motion_of(asset.local_path)
    if m is None:
        return None
    adj = w * (m["motion"] - 0.5) * 2.0
    if m["static"] or m["slideshow"]:
        adj = -w * 2.0
    base = asset.final_score if asset.final_score is not None else vision.appeal(asset.relevance_score, asset.quality)
    asset.final_score = round(max(0.0, min(1.0, float(base) + adj)), 4)
    asset.score_parts = dict(asset.score_parts or {}, motion=m["motion"], motionAdj=round(adj, 3))
    return m


# Real photos per video (config.PHOTO_MAX_PER_10MIN): this process's share,
# set from the lines it sources (a fan-out part: its lines), and how many it
# placed. The parent's variety pass counts the whole video.
_PHOTOS: Dict[str, Any] = {"cap": None, "used": 0}


def photo_cap(seconds: float) -> Optional[int]:
    """Photos allowed in `seconds` of video, None without a cap."""
    per = float(config.PHOTO_MAX_PER_10MIN or 0.0)
    if per <= 0:
        return None
    return max(1, int(round(per * max(0.0, float(seconds)) / 600.0)))


def _jobs_seconds(jobs: List[Dict[str, Any]]) -> float:
    return sum(float(j.get("seconds") or 0.0) for j in jobs or [])


def _photos_left() -> bool:
    with _CACHE_LOCK:
        cap = _PHOTOS["cap"]
        return cap is None or _PHOTOS["used"] < cap


def _count_photo(asset: Optional["MediaAsset"]) -> None:
    if asset is not None and asset.kind == "image" and asset.source != "generated":
        with _CACHE_LOCK:
            _PHOTOS["used"] += 1


_FOOTAGE_PROVIDERS: Optional[set] = None


def _footage_providers() -> set:
    global _FOOTAGE_PROVIDERS
    if _FOOTAGE_PROVIDERS is None:
        _FOOTAGE_PROVIDERS = {p.name for p in providers.REGISTRY if p.kind == "footage"}
    return _FOOTAGE_PROVIDERS


# The library keeps a job's approved-but-unused clips (library.record_from_doc):
# while on, the runner-up files that passed the judge stay on disk.
_LIBRARY_KEEP = {"on": False}


def keep_alternatives_for_library(on: bool) -> None:
    _LIBRARY_KEEP["on"] = bool(on)


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
    score += eyewitness_bonus(title)
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
    # The scene's time box goes with each lookup thread (ytdlp.with_stop).
    one = _ytdlp.with_stop(lambda t: _yt_candidates(t, False, limit=6, timeout=45))
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        lists = list(ex.map(one, targets))
    merged, seen = [], set()
    for rank in range(max((len(x) for x in lists), default=0)):
        for found in lists:
            if rank < len(found) and found[rank]["id"] not in seen:
                seen.add(found[rank]["id"])
                merged.append(found[rank])
    if merged or not _ytdlp.stopped():
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
    if not query.strip() or not config.SERPAPI_API_KEY:
        return []
    key = query.strip().lower()
    with _CACHE_LOCK:
        if key in _GOOGLE_VIDEO_CACHE:
            return _GOOGLE_VIDEO_CACHE[key]
    if _ytdlp.stopped():
        return []
    # SerpApi's Google Videos, a few per video (the owner's plan is 250 searches a month).
    rows: List[dict] = _serpapi_videos(query, limit)
    if rows or not _ytdlp.stopped():
        with _CACHE_LOCK:
            _GOOGLE_VIDEO_CACHE[key] = rows
    return rows


def _clock_seconds(text) -> float:
    """"3:12" / "1:02:03" -> seconds (0 when there is none)."""
    parts = [int(p) for p in re.findall(r"\d+", str(text or ""))]
    return float(sum(p * 60 ** i for i, p in enumerate(reversed(parts)))) if parts else 0.0


_SERPAPI_VIDEO_USED = {"n": 0}


def _serpapi_videos(query: str, limit: int = 10) -> List[dict]:
    """SerpApi's Google Videos: [{url, title, site, seconds}], at most SERPAPI_VIDEO_MAX_PER_JOB a job."""
    if not config.SERPAPI_API_KEY or not query.strip():
        return []
    with _CACHE_LOCK:
        if _SERPAPI_VIDEO_USED["n"] >= config.SERPAPI_VIDEO_MAX_PER_JOB:
            return []
        _SERPAPI_VIDEO_USED["n"] += 1
    try:
        r = requests.get("https://serpapi.com/search.json", timeout=60,
                         params={"engine": "google_videos", "q": query, "api_key": config.SERPAPI_API_KEY})
        r.raise_for_status()
        body = r.json()
        costs.record("serpapi.search")
    except (requests.RequestException, ValueError) as e:
        _source_error("serpapi_google_videos", e)
        _serpapi_spent(e)
        return []
    out = []
    for it in (body.get("video_results") or [])[:limit]:
        url = it.get("link") or ""
        if url.startswith("http"):
            out.append({"url": url, "title": (it.get("title") or "")[:200],
                        "site": urllib.parse.urlparse(url).netloc.replace("www.", ""),
                        "seconds": _clock_seconds(it.get("duration"))})
    return out


def _google_youtube_candidates(query: str) -> List[dict]:
    """YouTube videos Google finds for the query, shaped like _yt_candidates rows."""
    out = []
    for row in search_google_videos(query):
        m = re.search(r"youtube\.com/watch\?v=([\w-]{11})", row["url"])
        if not m or _video_unavailable(m.group(1)):
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
    # A clip-first line's wider rung (clip_rungs) and its second and third wordings are NEW searches: keyed
    # (and cached for every other line that asks them) by their own words, not by the subject - keyed by
    # subject, they got the line's first list back and never searched. (Read here on the scene's thread;
    # _youtube_pool runs this on pool threads in a copy of the scene's context.)
    if _RUNG.get():
        subject = f"rung::{target}"
    elif _CLIP_FIRST.get() and _WORDING.get() > 0:
        subject = f"wording::{target}"
    key = f"ytc::{require_cc}::{variant}::{(subject or target).strip().lower()}"
    if subject:
        with _CACHE_LOCK:
            if key in _YT_CANDIDATES_CACHE:
                return _YT_CANDIDATES_CACHE[key]
    found = _yt_candidates(target, require_cc)
    # Google finds YouTube videos yt-dlp's own search misses; they join the
    # list after the direct hits (never for a Creative-Commons-only search,
    # whose licence filter Google cannot apply). For the plain query, not its
    # rewordings ("... drone aerial footage", the intent's own searches): one
    # paid Google search per attempt instead of four, behind three SERP slots
    # (Lake Powell: 170 SERP calls, 13 answered "not JSON").
    if not require_cc and target.startswith("ytsearch") and variant not in ("broll", "intent"):
        have = {c["id"] for c in found}
        found = found + [c for c in _google_youtube_candidates(target.split(":", 1)[-1])
                         if c["id"] not in have]
    if subject and not (_ytdlp.stopped() and not found):
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


def _judge_limits() -> dict:
    """
    How hard this scene may look: {"best_of", "candidates", "per_scene", "scouts"}.

    A hook scene (the owner, 2026-09-30: the opening must be the strongest
    footage) scouts more of the candidate pool, judges more downloads and
    keeps the best of more passing clips. max() so a job's own larger values
    (Replace Clip raises all of them) are never lowered.
    """
    out = {"best_of": config.JUDGE_BEST_OF, "candidates": config.VISION_MAX_CANDIDATES,
           "per_scene": config.JUDGE_MAX_PER_SCENE, "scouts": config.POOL_SCOUT}
    # A clip-first line (config.CLIPS_FIRST) looks further before a picture may stand in: more
    # scouts a search and a bigger budget across its wordings and wider rungs.
    extra = 0
    if _CLIP_FIRST.get():
        extra = max(0, int(getattr(config, "CLIPS_FIRST_JUDGE_MAX_PER_SCENE", 0) or 0) - config.JUDGE_MAX_PER_SCENE)
        out["per_scene"] += extra
        out["scouts"] = max(out["scouts"], int(getattr(config, "CLIPS_FIRST_POOL_SCOUT", 0) or 0))
    if _IN_HOOK.get():
        out["best_of"] = max(out["best_of"], config.HOOK_JUDGE_BEST_OF)
        out["candidates"] = max(out["candidates"], config.HOOK_JUDGE_BEST_OF + 1)
        out["per_scene"] = max(out["per_scene"], config.HOOK_JUDGE_MAX_PER_SCENE + extra)
        out["scouts"] = max(out["scouts"], config.HOOK_POOL_SCOUT)
    return out


def _vision_budget_left() -> int:
    cap = _judge_limits()["per_scene"]
    counter = _SCENE_JUDGED.get()
    if counter is None:
        return cap
    return max(0, cap - counter[0])


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
    why = upload_conflict(info) or title_conflict(info.get("title") or "", context) or _music_upload(
        info, f"{intent} {context}")
    if why:
        # An AI story, or an upload from before this story's year (the owner's
        # Texas test, 2026-09-30): dropped before any storyboard is read.
        print(f"[media] skip {candidate['id']}: {why}", flush=True)
        got = {"start": 0.0, "score": 0.0, "description": why, "tile": 0}
    elif w and h and w / h < 1.2 and not config.ALLOW_VERTICAL:
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
    scout = _ytdlp.with_stop(_scout)               # the scene's time box goes with each scout
    with ThreadPoolExecutor(max_workers=len(scouts)) as pool:
        futures = {pool.submit(scout, c, grab, intent, context): c["id"] for c in scouts}
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
        if _ytdlp.stopped():
            return ""
        t0 = time.time()
        path = _yt_fetch(video_id, out_dir, start_at, seconds)
        _stage("download:youtube" if path else "download:youtube_failed", time.time() - t0)
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
    return counter is not None and counter[0] >= _judge_limits()["per_scene"]


def _count_judged() -> None:
    counter = _SCENE_JUDGED.get()
    if counter is not None:
        counter[0] += 1


def _good_enough(passed: List[MediaAsset]) -> bool:
    """Stop judging: enough clips passed (more for a hook scene), or one is plainly excellent."""
    if len(passed) >= _judge_limits()["best_of"]:
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
        base = a.final_score if a.final_score is not None else vision.appeal(a.relevance_score, a.quality)
        # A near tie goes to the sharper shot (its measured real detail; src/sharpness.py).
        base += _sharpness.rank_bonus(a)
        if hook_boost:
            # The hook booster: a near-tie goes to the clip with more scale,
            # people and action (a small, bounded bonus - relevance still leads).
            base += hookboost.rank_bonus(a)
        return base

    hook_boost = bool(_IN_HOOK.get() and getattr(config, "HOOK_BOOST", False))
    if hook_boost:
        from . import hookboost
    ranked = sorted(passed, key=rank, reverse=True)
    winner, losers = ranked[0], ranked[1:]
    keep_files = bool(_KEEP_ALT_FILES.get())
    for a in losers:
        if a.kind == "image" and _stockblock.blocked(a, "alternatives"):
            continue                    # never offered as an editor's choice either
        entry = {
            "assetId": a.identity, "url": a.url, "title": (a.attribution or "")[:120],
            "score": a.relevance_score, "quality": a.quality, "finalScore": a.final_score,
            "specificity": a.specificity, "moment": dict(a.moment or {}),
            "description": (a.content_description or "")[:160], "source": a.source}
        if a.cut_check:
            entry["cutCheck"] = dict(a.cut_check)       # a hook line's opening check on this very cut
        # The library keeps approved clips the video does not show
        # (library.record_from_doc): their files stay until the job ends.
        keep = keep_files or (_LIBRARY_KEEP["on"] and a.kind == "video" and not a.review_reason.startswith(
            "Best available") and (a.relevance_score or 0) >= config.CLIP_LIBRARY_MIN_SCORE)
        # Pick-a-shot: the best PICK_A_SHOT_CHOICES runner-ups keep their files for the editor's choices.
        if getattr(config, "PICK_A_SHOT", False) and len(winner.alternatives) < config.PICK_A_SHOT_CHOICES                 and not a.review_reason.startswith("Best available"):
            keep = True
        if keep:
            entry["localPath"] = a.local_path
            if a.kind == "video" and (a.duration or 0) > 0:
                # Its length stays with the choice: a runner-up may stand in for a hold that would run
                # past SHOT_MAX_SECONDS, but only when it covers the scene at real speed (src/shotcap.py).
                entry["seconds"] = round(float(a.duration), 2)
        winner.alternatives.append(entry)
        if keep:
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
    # (search, variant, recency: "" / True = this year / "month" / "week")
    searches = []
    recency = _RECENCY.get() if config.RECENT_FOOTAGE_FIRST else ""
    if _EVENT_WINDOW.get() == "year" and not require_cc:
        # A recent event: this year's uploads first, so the flood on screen is
        # the one being narrated. News titles rarely say "drone aerial", so
        # the bias word is just "footage". The unfiltered plain query stays
        # last for an event YouTube has little of yet. A story about now
        # (the owner's news compilations, 2026-09-30) asks for the last
        # month's uploads before this year's.
        if recency in _RECENT_SP:
            searches += [(f"{query_or_url} footage", f"{recency}-footage", recency),
                         (query_or_url, recency, recency)]
            # The Nature & Weather edit: the eyewitness searches the director
            # wrote for the line ("Atlantic City flooding video"), among the
            # same recent uploads.
            searches += [(q, f"{recency}-eyewitness{n}", recency)
                         for n, q in enumerate(_eyewitness_queries(query_or_url)[:2])]
        searches += [(f"{query_or_url} footage", "recent-footage", True),
                      (query_or_url, "recent", True)]
    elif b_roll_intent:
        searches.append((f"{query_or_url} {B_ROLL_INTENT}", "broll", False))
    searches.append((query_or_url, "plain", False))
    # The archive / news channels first: that is where the real footage of
    # an era or an event is, ahead of general uploads. Once per scene: every
    # fallback query asked all of them again (7 lookups each attempt in a
    # news story, Lake Powell 2026-10-01), and what the channels hold on the
    # subject is in the scene's pool from its first search.
    tried = _scene_tried()
    if _story_channels() and not require_cc and "__channels__" not in tried:
        tried.add("__channels__")
        searches.insert(0, (query_or_url, "channels", False))

    if config.CANDIDATE_POOL:
        recent = [s for s in searches if s[2] in _RECENT_SP]
        if not recent:
            return _youtube_pool(query_or_url, out_dir, seconds, start_at, require_cc, skip,
                                 used, intent, context, subject, searches)
        # Recent uploads first, on their own: the older ones are only pooled,
        # scouted and judged when nothing from the last month passed.
        first = _youtube_pool(query_or_url, out_dir, seconds, start_at, require_cc, skip,
                              used, intent, context, subject, recent, expand=False)
        if first is not None and not _near_miss(first):
            return first
        later = _youtube_pool(query_or_url, out_dir, seconds, start_at, require_cc, skip,
                              used, intent, context, subject, [s for s in searches if s not in recent])
        return _better_pick(first, later)

    judged = 0
    passed: List[MediaAsset] = []
    # Videos this call already downloaded or judged. The search variants
    # overlap heavily; before best-of-N the first pass returned at once, so a
    # repeat could not cost a second download and a second model call.
    tried: set = set()
    for search, variant, this_year in searches:
        if judged >= _judge_limits()["candidates"] or _scene_cap_reached() or _good_enough(passed):
            break
        target = _search_target(search, require_cc, this_year)

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
            if candidate["id"] in tried or _video_unavailable(candidate["id"]):
                continue
            # A disqualifying title excludes the candidate outright. Scoring it
            # down is not enough: the loop still takes the best of what is left,
            # so when a query finds nothing good a penalised tutorial wins
            # anyway. That is how a Premiere Pro screen recording ended up in a
            # documentary. No clip is better than the wrong clip - the caller
            # falls through to the next query, and the timeline holds the
            # previous shot.
            if not _usable_title(candidate["title"], candidate.get("channel", ""), candidate["aspect"],
                                 f"{intent} {context}"):
                continue
            if title_conflict(candidate["title"], context):
                continue                            # another state, storm, kind of weather or year
            eligible.append(candidate)
        if not eligible:
            continue

        grab = max(2.0, seconds + 1.5)
        plan = _plan_grabs(eligible, grab, start_at, intent, context)

        for candidate, point, moment in plan:
            if judged >= _judge_limits()["candidates"] or _scene_cap_reached() or _good_enough(passed):
                break
            tried.add(candidate["id"])
            if ledger.moment_used(candidate["id"], point, point + grab):
                continue                            # an earlier video showed this moment
            # With a margin, cut clean: never opening on the end of the shot before (filters.tidy_clip).
            path, clean, cuts = fetch_clean_clip(candidate["id"], out_dir, point, grab, candidate["title"],
                                                 least=_plays(seconds, grab))
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
            # An upscaled upload is soft in every moment of it (src/sharpness.py).
            soft = clip_detail_reason(path, candidate["title"])
            if soft:
                print(f"[media] {soft}, skipping: {candidate['title'][:60]}", flush=True)
                _mark_bad(f"yt:{candidate['id']}", "", soft)
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
            asset.moment = {"start": round(float(point), 1), "score": (moment or {}).get("score"),
                            "clean": clean, "cuts": cuts}
            # Not returned yet: the first clip to clear the floor is rarely the
            # best one available. Up to JUDGE_BEST_OF passing clips are compared.
            passed.append(asset.apply_verdict(verdict, intent))
    return _best_of(passed)


def _eyewitness_queries(query: str) -> List[str]:
    """The line's eyewitness searches (director.eyewitness_queries, carried in its scene intent)."""
    if not config.EYEWITNESS_SEARCHES:
        return []
    si = _SCENE_INTENT.get() or {}
    got = si.get("eyewitness") if isinstance(si, dict) else None
    low = (query or "").strip().lower()
    return [q for q in (got or []) if isinstance(q, str) and q.strip() and q.strip().lower() != low]


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


def search_dailymotion_this_month(query: str) -> List[dict]:
    """Uploads of the last 30 days, for a story about now (named for the same cache reason)."""
    start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
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
            "-f", "b[height<=1080]/bv*[height<=1080]+ba", *_ytdlp.best_bitrate(),
            "--merge-output-format", "mp4", "--no-playlist", "--no-warnings",
            "--ignore-config", "--socket-timeout", "20", "--retries", "2",
            "-o", out_tpl, "--print", "after_move:filepath"]
    for routed in (False, True):
        if routed and not _PROXIES:
            break
        if _ytdlp.stopped():
            return ""
        with _ytdlp._net_slot(_ytdlp.DOWNLOAD) as ok:
            if not ok:
                return ""
            # The proxy is claimed only for the proxied try, once a slot is
            # free: claimed up front, it was never given back when the direct
            # try worked, and the route looked busier with every clip.
            proxy = _acquire_proxy("dailymotion.com") if routed else ""
            if routed and not proxy:
                break
            cmd = base + (["--proxy", proxy] if proxy else [])
            started = time.time()
            try:
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
        if config.RECENT_FOOTAGE_FIRST and _RECENCY.get() in _RECENT_SP:
            # A story about now: the last month's uploads before the year's.
            month = rank(_cached_search(search_dailymotion_this_month, query, cache_key=subject))
            have = {c["id"] for c in month}
            recent = month + [c for c in recent if c["id"] not in have]
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
        if (not _usable_title(c["title"], c.get("channel", ""), c["aspect"], f"{intent} {context}")
                or title_conflict(c["title"], context)):
            continue
        if c["duration"] and c["duration"] < grab + 4:
            continue
        point = _fixed_point(c, grab, 10.0)
        if ledger.url_used(page, point, point + grab):
            continue                                # an earlier video showed this moment
        vkey, mkey = f"dm:{c['id']}", f"dm:{c['id']}@{int(point // 10)}"
        if _is_bad(vkey, mkey):
            continue                                # another scene found it unusable
        margin = config.CUT_MARGIN_SECONDS if config.CLEAN_CUTS else 0.0
        path = _dm_fetch(c["id"], out_dir, max(0.0, point - margin), grab + 2 * margin)
        if path and not playable_video(path):
            # yt-dlp exited 0 with no picture to read (an audio-only or
            # duration-less section): the Lake Powell job judged 109 of these
            # ("no frames"), the same few videos again and again.
            print(f"[media] Dailymotion {c['id']}: the download will not play; skipped for this video",
                  flush=True)
            _mark_bad(vkey, mkey, "a download that will not play")
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        if path and margin:
            path = tidy_clip(path, grab, prefer=min(point, margin), least=_plays(seconds, grab))[0]
        if not path:
            continue
        why = "burned-in text or UI" if has_burned_captions(path) else motion_rejects(path)
        why = why or clip_detail_reason(path, c["title"])      # an upscaled upload (src/sharpness.py)
        if why:
            _mark_bad(vkey, mkey, why)
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        judged += 1
        _GATE_SLOP.set("")
        keep, verdict = _vision_gate(path, intent, context, c["title"])
        if not keep:
            _mark_bad(vkey, mkey, _GATE_SLOP.get())
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
            # Where it was cut: the cross-video ledger records the range.
            moment={"start": round(float(point), 1)},
        ).apply_verdict(verdict, intent)
    return None


_WEB_VIDEO_SKIP = ("youtube.com", "youtu.be", "dailymotion.com", "google.com")


def _web_fetch(url: str, out_dir: str, start_at: float, seconds: float, timeout: int = 240) -> str:
    """One section of a non-YouTube web video through yt-dlp; '' on failure."""
    out_tpl = os.path.join(out_dir, f"web_%(extractor)s_%(id)s_{int(start_at)}_{uuid.uuid4().hex[:6]}.%(ext)s")
    cmd = ["yt-dlp", url, "--download-sections", f"*{start_at:.1f}-{start_at + seconds:.1f}",
           "--force-keyframes-at-cuts", "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]/b",
           *_ytdlp.best_bitrate(),
           "--no-playlist", "--no-warnings", "--quiet", "--max-filesize", "300M",
           "--merge-output-format", "mp4", "-o", out_tpl, "--print", "after_move:filepath"]
    domain = (urllib.parse.urlparse(url).hostname or "web").removeprefix("www.")
    if _ytdlp.stopped():
        return ""
    with _ytdlp._net_slot(_ytdlp.DOWNLOAD) as ok:
        if not ok:
            return ""
        proxy = _acquire_proxy(domain)
        cmd += _yt_network_args(proxy)
        started = time.time()
        try:
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
        # A web clip's identity is "web_video:<url>" (MediaAsset.identity);
        # the old "web:" key never matched, so one could play twice.
        if used and (f"web_video:{row['url']}" in used or f"web:{row['url']}" in used):
            continue
        if _talking_head(row["title"]) or _stock_seller(row["title"], row["site"]):
            continue
        from . import slop
        if slop.metadata_reason(row["title"], row["site"], row["url"]) or title_conflict(row["title"], context):
            continue
        if row["seconds"] and row["seconds"] < grab + 2:
            continue
        if judged >= config.VISION_MAX_CANDIDATES:
            break
        start = _fixed_point({"duration": row["seconds"]}, grab, 5.0) if row["seconds"] else 5.0
        if ledger.url_used(row["url"], start, start + grab):
            continue                                # an earlier video showed this moment
        key = f"web:{row['url']}"
        if _is_bad(key):
            continue                                # another scene found it unusable
        margin = config.CUT_MARGIN_SECONDS if config.CLEAN_CUTS else 0.0
        path = _web_fetch(row["url"], out_dir, max(0.0, start - margin), grab + 2 * margin)
        if path and margin:
            path = tidy_clip(path, grab, prefer=min(start, margin), least=_plays(seconds, grab))[0]
        if not path:
            continue
        w, h = _video_dims(path)
        why = "burned-in text or UI" if has_burned_captions(path) else motion_rejects(path)
        vertical = bool(w and h and w < h * 1.2 and not config.ALLOW_VERTICAL)
        why = why or ("" if vertical else clip_detail_reason(path, row["title"]))   # src/sharpness.py
        if vertical or why:
            _mark_bad(key, "", why)
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        judged += 1
        _GATE_SLOP.set("")
        keep, verdict = _vision_gate(path, intent, context, row["title"])
        if not keep:
            _mark_bad(key, "", _GATE_SLOP.get())
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
            moment={"start": round(float(start), 1)},
        ).apply_verdict(verdict, intent)
    return None


# YouTube's own upload-date filters for the results page ("sp"): this week,
# this month. This year is _YT_THIS_YEAR (ytdlp).
_YT_THIS_WEEK = "EgIIAw%3D%3D"
_YT_THIS_MONTH = "EgIIBA%3D%3D"
_RECENT_SP = {"week": _YT_THIS_WEEK, "month": _YT_THIS_MONTH}


def _search_target(search: str, require_cc: bool, this_year) -> str:
    """
    The yt-dlp target of one search. `this_year` is the search's recency:
    falsy (any upload), True or "year" (this year's), "month" or "week"
    (the last month's / week's uploads, for a story about now).
    """
    if require_cc:
        # yt-dlp's flat search extractor reports license=NA for every hit,
        # so a CC match-filter over ytsearch rejects everything. YouTube's
        # own results page with its CC filter populates the field.
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(search) + "&sp=EgIwAQ%3D%3D")
    if this_year in _RECENT_SP:
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(search) + "&sp=" + _RECENT_SP[this_year])
    if this_year:
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(search) + "&sp=" + _YT_THIS_YEAR)
    return f"ytsearch{config.YT_SEARCH_RESULTS}:{search}"


def _near_miss(asset: Optional[MediaAsset]) -> bool:
    """The best-available pick kept under the vision floor (_youtube_pool's `soft`)."""
    return bool(asset is not None and (asset.review_reason or "").startswith("Best available"))


def _better_pick(first: Optional[MediaAsset], later: Optional[MediaAsset]) -> Optional[MediaAsset]:
    """
    Of a recent-uploads pick and an any-upload pick for one scene, the one to
    keep: a clip that passed the judge over a near-miss, the recent one when
    both are near-misses of equal score. The loser's file is removed.
    """
    if first is None or later is None:
        return first if later is None else later
    keep, drop = first, later
    if _near_miss(first) and (not _near_miss(later)
                              or (later.relevance_score or 0) > (first.relevance_score or 0)):
        keep, drop = later, first
    try:
        if drop.local_path and drop.local_path != keep.local_path and os.path.exists(drop.local_path):
            os.remove(drop.local_path)
    except OSError:
        pass
    return keep


def _music_upload(info: Optional[dict], line: str = "") -> str:
    """A music video or performance by its YouTube metadata (category Music, title, channel) in a story and
    a line not about music (src/topics.py; "" = not one, or the story is about music)."""
    if not info:
        return ""
    from . import topics
    return topics.off_topic_title(str(info.get("title") or ""),
                                  str(info.get("channel") or info.get("uploader") or ""),
                                  info.get("categories") or [], line=line)


def meta_reject(info: Optional[dict], title: str = "", context: str = "", need: float = 0.0,
                line: str = "", query: str = "") -> str:
    """
    Why a YouTube video can never be this line's clip, read from its metadata alone ("" = it may be):
    vertical (unless the style frames vertical video), an upload under MIN_CLIP_HEIGHT lines that is not
    archive film (clip_quality drops such a file after its download - and its judge call - anyway),
    shorter than the shot, or another year / place / storm by its upload date and title. Unknown
    metadata never rejects. A music video (YouTube's Music category) in a story and a `line` not about
    music is turned down too (src/topics.py). Archive film by its title or by the line's `query` (an old
    era's search) may be small, as _asset_ok lets it be.
    """
    if not info:
        return ""
    music = _music_upload(info, line or context)
    if music:
        return music
    try:
        w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    except (TypeError, ValueError):
        w, h = 0, 0
    name = str(info.get("title") or title or "")
    if w and h:
        if w / float(h) < 1.2 and not config.ALLOW_VERTICAL:
            return "vertical video"
        floor = int(config.MIN_CLIP_HEIGHT or 0)
        lines = min(w, h)
        if floor and _period_line():
            floor = min(floor, int(getattr(config, "PERIOD_MIN_HEIGHT", 480) or 480))
        if floor and lines < floor and not _is_archive(f"{name} {query}"):
            return f"low detail: the upload is {lines}p (under {floor} lines)"
    try:
        dur = float(info.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur and need and dur < need:
        return "shorter than the shot"
    return upload_conflict(info) or title_conflict(name, context)


def _prequalified(ranked: list, want: int, context: str, need: float, line: str = "", query: str = "") -> list:
    """
    `ranked` (CandidatePool entries) with the ones meta_reject turns down left out - for a clip-first
    line only (config.CLIP_PREQUALIFY; anything else gets `ranked` back as it was). The metadata is
    read in rank order, `want` at a time in parallel (the scouts read the same, cached), until `want`
    candidates qualify or CLIP_PREQUALIFY have been read; the rest keep their place unread.
    """
    limit = int(getattr(config, "CLIP_PREQUALIFY", 0) or 0)
    if limit <= 0 or not _CLIP_FIRST.get() or not ranked:
        return ranked
    keep, read = [], 0
    fetch = _ytdlp.with_stop(lambda vid: _yt_info(vid))
    while read < min(limit, len(ranked)) and len(keep) < want and not _ytdlp.stopped():
        batch = ranked[read:min(limit, len(ranked), read + max(1, want))]
        read += len(batch)
        with ThreadPoolExecutor(max_workers=max(1, len(batch))) as ex:
            infos = list(ex.map(lambda c: fetch(c.id), batch))
        for c, got in zip(batch, infos):
            info = got[0] if isinstance(got, tuple) else {}
            why = meta_reject(info, c.title, context, need, line, query)
            if why:
                # Not remembered for the job: a line of an old era may take a small upload (the metadata
                # is cached, so another line reads it again for free).
                print(f"[pool] skip {c.id} before scouting: {why}", flush=True)
                continue
            keep.append(c)
    return keep + ranked[read:]


def _youtube_pool(query: str, out_dir: str, seconds: float, start_at: float,
                  require_cc: bool, skip: int, used: Optional[set], intent_text: str,
                  context: str, subject: str, searches: List[tuple],
                  expand: bool = True) -> Optional[MediaAsset]:
    """
    The candidate-pool way to find a clip (src/candidates.py).

    Every search variant and the intent's own expanded searches run first and
    their results are pooled and deduplicated; the pool is ranked on metadata
    against the typed intent; the best few are scouted and judged; and the
    combined score - not the order the searches happened to return - picks
    the winner. The runners-up stay with the scene as alternatives.

    expand=False leaves the intent's searches out: youtube_clip's first,
    recent-uploads-only pass (they are not date filtered, so they belong to
    the pass that may take older uploads).
    """
    si = intent.SceneIntent.from_dict(_SCENE_INTENT.get()) if _SCENE_INTENT.get() else None
    # A scene that cannot scout or judge one more candidate does not search
    # for one: each fallback query cost its searches (and a news story's 7
    # channel lookups) before this same check turned it away.
    if _vision_budget_left() < 2:
        print(f"[pool] scene out of vision budget ({_judge_limits()['per_scene']}); no more searches", flush=True)
        return None
    pool = candidates.CandidatePool(si, query, seconds, used=used)
    targets = list(searches)
    tried = _scene_tried()
    # The intent's own expanded searches join the first attempt's pool only;
    # a fallback attempt already has their results and adds its own query.
    if expand and si and config.POOL_EXTRA_QUERIES > 0 and not require_cc and "__intent_searched__" not in tried:
        tried.add("__intent_searched__")
        for q in si.queries(query)[1:1 + config.POOL_EXTRA_QUERIES]:
            targets.append((q, "intent", False))

    def fetch_one(t):
        search, variant, this_year = t
        if variant == "channels":
            return t, _channel_candidates(search, _story_channels(), subject), "channel"
        return t, _yt_candidates_cached(_search_target(search, require_cc, this_year),
                                        require_cc, subject, variant), "search"

    # Each search runs in a copy of this scene's context: a pool thread starts with none, and a rung's or
    # a later wording's search read as the line's first one (the subject's cached list, never searched).
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(targets)))) as ex:
        futures = [ex.submit(contextvars.copy_context().run, _ytdlp.with_stop(fetch_one), t) for t in targets]
        for fut in futures:
            t, rows, via = fut.result()
            pool.add(rows, query=t[0], variant=t[1], via=via)

    # A video YouTube already refused for good (paid, members-only, age-gated...: _video_unavailable)
    # leaves the ranking too: the search lists are cached, and it used to take a scout's place.
    ranked = [c for c in pool.ranked()
              if c.id not in tried and _usable_title(c.title, c.channel, c.aspect, f"{intent_text} {context}")
              and not title_conflict(c.title, context) and not _is_bad(f"yt:{c.id}")
              and not _video_unavailable(c.id)]
    if config.EYEWITNESS_SEARCHES:
        # Phone, drone, chaser and helicopter titles first, compilations last
        # (the Nature & Weather edit), on top of the metadata score.
        ranked.sort(key=lambda c: -(c.metadata + 0.06 * eyewitness_bonus(c.title)))
    if skip:
        ranked = ranked[skip:] + ranked[:skip]
    if not ranked:
        return None
    # Scouting spends one model call per candidate; leave room for judging.
    # A hook scene scouts more of the pool (_judge_limits).
    limits = _judge_limits()
    left = _vision_budget_left()
    if left < 2:
        print(f"[pool] scene out of vision budget ({limits['per_scene']}); no more searches", flush=True)
        return None
    n_scouts = max(1, min(limits["scouts"], left - 2))
    # A clip-first line reads its next candidates' metadata first (CLIP_PREQUALIFY): an upload under
    # MIN_CLIP_HEIGHT, a vertical one or one too short never takes a scout or a download.
    ranked = _prequalified(ranked, n_scouts, context, max(2.0, seconds + 1.5), f"{intent_text} {context}", query)
    _trace(step="search", query=query[:80], rung=str((_RUNG.get() or {}).get("label") or "")[:60],
           candidates=len(pool), usable=len(ranked), scouts=min(n_scouts, len(ranked)))
    if not ranked:
        return None
    print(f"[pool] {len(pool)} candidates from {pool.searches} searches ({len(ranked)} new); "
          f"best meta {ranked[0].metadata:.2f} {ranked[0].title[:50]!r}; scouting {n_scouts}", flush=True)

    grab = max(2.0, seconds + 1.5)
    scouts = ranked[:n_scouts]
    tried.update(c.id for c in scouts)
    by_id = {c.id: c for c in scouts}
    # A wider rung's storyboard moment is picked for what the rung names (rung_judging), as its judge
    # reads it: picked against the line's exact moment, a rung's candidates scored under the floor and
    # were dropped before any download.
    seek = rung_judging(intent_text, _SCENE_INTENT.get(), _RUNG.get())[0] if _RUNG.get() and intent_text \
        else intent_text
    # Scouting runs in pool threads, which do not see this scene's budget
    # counter, so the fresh (unmemoised) scouts are counted here first.
    if config.MOMENT_SELECTION and seek and vision.enabled():
        with _SCENE_LOCK:
            fresh = sum(1 for c in scouts if _scout_memo_key(c.id, grab, seek) not in _SCOUT_MEMO)
        for _ in range(fresh):
            _count_judged()
    plan = _plan_grabs([c.row() for c in scouts], grab, start_at, seek, context)
    _trace(step="scout", kept=len(plan), of=len(scouts),
           titles=" | ".join(c.title[:40] for c in scouts)[:200])
    story_kind = _STORY_KIND["kind"]
    passed: List[MediaAsset] = []
    soft: Optional[dict] = None       # the best candidate under the floor, if any
    judged = 0
    fine_done = False
    claimed: List[str] = []
    for row, point, moment in plan:
        if judged >= limits["candidates"] or _vision_budget_left() < 1 or _good_enough(passed):
            break
        c = by_id[row["id"]]
        if not _claim_inflight(c.id, used):
            continue                        # another scene is downloading it right now
        claimed.append(c.id)
        if config.JUDGE_MEMORY and _is_bad(f"yt:{c.id}@{int(point // 10)}"):
            # Another scene's judge turned this moment down for every line: not
            # refined (a paid call) only to be skipped after it.
            _release_inflight(c.id)
            continue
        # The fine pass (one more model call) goes to the best-ranked
        # download only; the others keep their coarse pick.
        if not fine_done and _vision_budget_left() >= 2:
            fine_done = True
            _count_judged()
            moment = _refine_moment(row, moment, grab, seek, context)
        if moment and moment.get("fine"):
            point = moment["start"]
        if ledger.moment_used(c.id, point, point + grab):
            # An earlier video showed this moment of this video (the owner,
            # 2026-09-30): the next candidate instead.
            print(f"[ledger] skip {c.id} @ {point:.0f}s: shown in an earlier video", flush=True)
            _release_inflight(c.id)
            continue
        mkey = f"yt:{c.id}@{int(point // 10)}"
        least = _plays(seconds, grab)
        if _is_bad(mkey) or _short_section(mkey, least):
            _release_inflight(c.id)
            continue                        # another scene found this moment unusable (or too short for it)
        path, clean, cuts = fetch_clean_clip(c.id, out_dir, point, grab, c.title, least=least)
        if not path:
            if clean is False:
                _note_short_section(mkey, least)    # downloaded, but no clean start long enough: not again
            _trace(step="download", video=c.id, title=c.title[:60],
                   why="no clean stretch long enough" if clean is False else "download failed")
            _release_inflight(c.id)
            continue
        still = motion_rejects(path)
        why = "burned-in text or UI" if has_burned_captions(path) else still
        # An upscaled upload (src/sharpness.py: under MIN_CLIP_REAL_HEIGHT lines of real
        # detail in its best frame) is turned down before any vision call, for every scene.
        why = still or why or clip_detail_reason(path, c.title)
        if why:
            print(f"[media] {why if why != 'burned-in text or UI' else 'hardsubs'}, skipping: {c.title[:60]}",
                  flush=True)
            _trace(step="filter", video=c.id, title=c.title[:60], why=str(why)[:90])
            _mark_bad(f"yt:{c.id}", mkey, why)
            try:
                os.remove(path)
            except OSError:
                pass
            _release_inflight(c.id)
            continue
        judged += 1
        _count_judged()
        _GATE_SLOP.set("")
        keep, verdict = _vision_gate(path, intent_text, context, c.title)
        _trace(step="judge", video=c.id, title=c.title[:60], keep=bool(keep),
               score=(verdict or {}).get("score"), quality=(verdict or {}).get("quality"),
               why=_GATE_SLOP.get()[:90] or _flags_of(verdict),
               saw=str((verdict or {}).get("description") or "")[:110])
        if not keep:
            _mark_bad(f"yt:{c.id}", mkey, _GATE_SLOP.get())
            v = verdict or {}
            score = float(v.get("score") or 0.0)
            # (A hook clip that opens on something else is a clear no too: never the "best available".)
            clear_no = bool(v.get("has_text_or_watermark")) or bool(v.get("is_talking_head")) \
                or bool(v.get("ai_generated")) or bool(v.get("studio")) or v.get("opening") is False \
                or bool(v.get("off_topic"))
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
        # Footage that moves wins over a still shot of the same thing
        # (MOTION_PREFERENCE, doubled in the hook).
        apply_motion(asset)
        _note_detail(asset)                 # its real detail breaks a near tie (_best_of)
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
                     title: str = "", least: Optional[float] = None) -> tuple:
    """
    (path, clean, cuts): a YouTube section with margin, cut clean around
    `start`. `least`: the shortest clip the caller can use (tidy_clip; `need`
    when not given). ("", True, 0) when the download failed; ("", False, cuts)
    when it came but no clean start leaves `least` (filters.tidy_clip).
    """
    margin = config.CUT_MARGIN_SECONDS if config.CLEAN_CUTS else 0.0
    fetch_start = max(0.0, start - margin)
    path = _yt_fetch_retry(video_id, out_dir, fetch_start, need + 2 * margin, title)
    if not path:
        return "", True, 0
    if not margin:
        return path, True, 0
    return tidy_clip(path, need, prefer=start - fetch_start, least=least)


def _plays(seconds: float, grab: float) -> float:
    """The shortest clip a line of `seconds` can use from a `grab`-second section: what its scene plays,
    a crossfade into the next included (SEQ_SHOT_PAD) - the rest of the grab is only margin."""
    return min(float(grab), max(1.0, float(seconds or 0.0)) + SEQ_SHOT_PAD)


# Sections tidy_clip threw away (no clean start long enough), by moment key -> the shortest clip
# a line asked for there: a line asking for as much or more skips the download.
_SHORT_SECTIONS: Dict[str, float] = {}


def _short_section(mkey: str, least: float) -> bool:
    with _CACHE_LOCK:
        got = _SHORT_SECTIONS.get(mkey)
    return got is not None and least >= got - 0.01


def _note_short_section(mkey: str, least: float) -> None:
    with _CACHE_LOCK:
        if len(_SHORT_SECTIONS) > 5000:
            _SHORT_SECTIONS.clear()
        _SHORT_SECTIONS[mkey] = min(float(least), _SHORT_SECTIONS.get(mkey, float(least)))


# Fine passes already paid for in this job (JUDGE_MEMORY): video, coarse moment, clip
# length and intent -> the refined moment, as _SCOUT_MEMO keeps the coarse pick.
_FINE_MEMO: Dict[str, dict] = {}


def _fine_memo_key(video_id: str, moment: dict, grab: float, intent: str) -> str:
    return f"{video_id}|{round(float(moment.get('start') or 0.0), 1)}|{round(grab)}|{(intent or '')[:120]}"


def _refine_moment(candidate: dict, moment: Optional[dict], grab: float,
                   intent_text: str, context: str) -> Optional[dict]:
    """The fine storyboard pass around a coarse pick (moments.refine), or the pick.
    With JUDGE_MEMORY a refined moment is remembered (only one that came back: a
    pass that found nothing, or failed, is asked again next time, as before)."""
    if not moment or not config.MOMENT_FINE_PASS or not intent_text:
        return moment
    key = _fine_memo_key(candidate["id"], moment, grab, intent_text) if config.JUDGE_MEMORY else ""
    if key:
        with _SCENE_LOCK:
            known = _FINE_MEMO.get(key)
        if known:
            return dict(known)
    try:
        info, proxy = _yt_info(candidate["id"])
        fine = moments.refine(info, moment, intent_text, context, grab, proxy) if info else None
    except Exception as e:  # noqa: BLE001 - the coarse pick stands
        print(f"[moment] fine pass failed: {type(e).__name__}", flush=True)
        fine = None
    if key and fine:
        with _SCENE_LOCK:
            _FINE_MEMO[key] = dict(fine)
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


# Where sourcing's time goes, per stage, for the job result (meta.sourcing.stageSeconds,
# a re-cut's stageSeconds): each search by source, each picture download (arrived or
# failed), a picture's checks before the judge, each gate (the AI filters, the local
# model, the vision judge, the stamp) for a picture or a clip, each YouTube section.
# Thread-seconds: sixteen scenes at once add up to sixteen seconds a second. The
# Yellowstone re-cut (2026-10-04) said only that 39 pieces ran out of time.
_STAGES: Dict[str, List[float]] = {}


def _stage(name: str, seconds: float) -> None:
    with _CACHE_LOCK:
        row = _STAGES.setdefault(name, [0, 0.0])
        row[0] += 1
        row[1] += max(0.0, float(seconds))


def stage_seconds() -> Dict[str, Dict[str, float]]:
    """{stage: {"n": calls, "seconds": thread-seconds, "mean": seconds a call}} of this job so far."""
    with _CACHE_LOCK:
        return {k: {"n": int(n), "seconds": round(s, 1), "mean": round(s / n, 2) if n else 0.0}
                for k, (n, s) in sorted(_STAGES.items())}


def reset_cache():
    """Call between jobs — serverless worker processes are reused across renders."""
    with _SCENE_LOCK:
        _SCOUT_MEMO.clear()
        _FINE_MEMO.clear()
        _INFLIGHT.clear()
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()
        _YT_CANDIDATES_CACHE.clear()
        _GOOGLE_VIDEO_CACHE.clear()
        _SOURCE_STATS.clear()
        _STAGES.clear()
        _USED_CHANNELS.clear()
        _GENERATED[0] = 0
        _PHOTOS.update(cap=None, used=0)
    with _MOTION_LOCK:
        _MOTION_CACHE.clear()
    SLOP_REJECTED.clear()
    with _CACHE_LOCK:
        _BAD.clear()                    # what was unusable is decided again per job
        _SHORT_SECTIONS.clear()
        _CLIP_SEARCHED.clear()          # which lines' clip searches ran to their end
    _LIBRARY_KEEP["on"] = False         # the job's Library.load turns it on
    from . import official
    official.reset()                    # each satellite sector once per video
    LOCAL_REJECTED["n"] = 0
    _sharpness.reset()                  # the job's measures and its count of blurry candidates
    _stockblock.reset()                 # the job's count of stock-agency pictures kept out
    _SERPAPI_USED["n"] = 0              # SerpApi's per-job budget starts again
    _SERPAPI_VIDEO_USED["n"] = 0
    _IMAGE_NO_CREDIT["hit"] = False
    UNJUDGED_KEPT.update(n=0, rejected=0)
    _ytdlp.reset()
    vision.reset()  # per-job call/failure counts for the job result
    moments.reset_cache()  # storyboard sheets, cached per video across beats


def _generation_budget_left() -> bool:
    # Never in the opening (the owner, 2026-09-30: 4 of the first 5 scenes of
    # a news video were AI illustrations). The providers registry asks this
    # before every generation, on the scene's own thread, so the hook flag
    # set by source_for_segment is visible here; nothing is counted.
    if _IN_HOOK.get() and not config.GENERATED_IMAGES_IN_HOOK:
        return False
    with _CACHE_LOCK:
        if _GENERATED[0] >= config.IMAGE_MAX_PER_VIDEO:
            return False
        _GENERATED[0] += 1
    costs.record("image.generate")
    with _CACHE_LOCK:
        return True


def _may_generate_for(job: Dict[str, Any]) -> bool:
    """A job's scene may get a generated image: never a real person, never the hook."""
    if job.get("subject_type") == "person":
        return False
    return not (job.get("hook") and not config.GENERATED_IMAGES_IN_HOOK)


def _scene_flags(job: Dict[str, Any]) -> Dict[str, Any]:
    """The per-scene switches a job carries into source_for_segment (hook, recency, where it starts)."""
    out = {"hook": bool(job.get("hook")), "recency": str(job.get("recency") or "")}
    try:
        if job.get("start") is not None:
            out["start"] = float(job["start"])
    except (TypeError, ValueError):
        pass
    return out


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
    if _ytdlp.stopped():
        return []
    t0 = time.time()
    try:
        found = fn(query)
    except Exception as e:  # noqa: BLE001
        print(f"[media] {name} '{query}' failed: {e}", flush=True)
        _source_error(name, e)
        found = []
    _stage(f"search:{name}", time.time() - t0)
    with _CACHE_LOCK:
        st = _source_stat(name)
        st["searches"] += 1
        st["withResults"] += 1 if found else 0
    if not found and _ytdlp.stopped():
        return found                    # cut short by the scene's time box: another scene may ask again
    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = found
    return found


def _download(candidate: MediaAsset, query: str, work_dir: str) -> Optional[MediaAsset]:
    if _ytdlp.stopped():
        return None
    # A stock agency's picture never downloads, whichever search found it (src/stockblock.py).
    if candidate.kind == "image" and _stockblock.blocked(candidate, "download"):
        return None
    ext = ".mp4" if candidate.kind == "video" else ".jpg"
    safe = "".join(ch for ch in query if ch.isalnum())[:24] or "asset"
    dest = os.path.join(
        work_dir, f"{candidate.source}_{safe}_{abs(hash(candidate.url)) % 999999}{ext}")
    kind = "picture" if candidate.kind == "image" else "file"
    t0 = time.time()
    try:
        if candidate.kind == "image":
            # Browser-style retries for hotlink blocks, and whatever format
            # arrived (WebP, AVIF, HEIC, CMYK...) rewritten as a clean JPEG.
            # The search engine's ~300-500 px thumbnail is never asked for while
            # pictures must be sharp full screen (src/sharpness.py): it could not pass.
            thumb = "" if _sharpness.picture_on() else (getattr(candidate, "thumbnail", "") or "")
            candidate.local_path = _imagefix.fetch(candidate.url, dest,
                                                   getattr(candidate, "page_url", "") or "",
                                                   thumbnail=thumb)
        else:
            # An archive's footage is a whole file (archive.org, NASA, Wikimedia Commons video):
            # bounded in size and time (WHOLE_FILE_MAX_MB, WHOLE_FILE_SECONDS) and by the scene's stop.
            mb = float(getattr(config, "WHOLE_FILE_MAX_MB", 0) or 0)
            secs = float(getattr(config, "WHOLE_FILE_SECONDS", 0) or 0)
            candidate.local_path = download(candidate.url, dest, max_bytes=int(mb * (1 << 20)) if mb > 0 else 0,
                                            max_seconds=secs if secs > 0 else 0.0,
                                            stop=_ytdlp.stopped if (mb > 0 or secs > 0) else None)
        _stage(f"download:{kind}", time.time() - t0)
        return candidate
    except Exception as e:  # noqa: BLE001
        _stage(f"download:{kind}_failed", time.time() - t0)
        _source_error(f"download_{candidate.source}", e)
        return None


def _photo_seen_before(path: str) -> bool:
    """A downloaded photo whose perceptual hash matches one an earlier video showed (removed if so)."""
    if not ledger.on() or not path or not ledger.current().photo_hashes:
        return False
    h = ledger.photo_hash(path)
    if h is None or not ledger.photo_used("", h):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return True


def _bigger_first(candidates: List[MediaAsset], window: int = 3) -> List[MediaAsset]:
    """
    Pictures in the search's order, except that among neighbours (`window`
    results of about the same relevance) the ones whose own size can be sharp
    full screen come first - a near tie goes to the sharper picture - and the
    ones that never could are left out. Clips and pictures of unknown size
    keep their place.
    """
    if not _sharpness.picture_on():
        return list(candidates)
    out = []
    for n, c in enumerate(candidates):
        if c.kind != "image":
            rank = 1
        elif not (c.width and c.height):
            rank = 1
        elif not _sharpness.possible(c.width, c.height):
            continue
        else:
            rank = 0
        out.append((n // max(1, window), rank, n, c))
    return [c for *_k, c in sorted(out, key=lambda t: t[:3])]


def picture_blur_reason(path: str, zoom: Optional[float] = None) -> str:
    """Why a downloaded picture may not be shown full screen ("" = sharp enough, the check is
    off, or it cannot be measured) - its real detail blown up past MAX_PICTURE_MAGNIFICATION."""
    got = _sharpness.picture_check(path, zoom=zoom)
    return "" if got["ok"] else got["why"]


def _is_archive(title: str = "", source: str = "") -> bool:
    """Archive film by its source or its title (a year before 1990, a newsreel, Pathe...)."""
    return source == "archive_org" or bool(_ARCHIVE_TITLE_RE.search(title or ""))


def _period_line() -> bool:
    """
    This scene's line is about a year at least PERIOD_FOOTAGE_YEARS back (its scene intent's time_context;
    config off = 0): its news footage only exists as the era's broadcast video, so a clip is held to
    PERIOD_MIN_HEIGHT lines and PERIOD_REAL_LINES of real detail instead of the modern floors.
    """
    years = int(getattr(config, "PERIOD_FOOTAGE_YEARS", 0) or 0)
    if years <= 0:
        return False
    si = _SCENE_INTENT.get() or {}
    m = re.match(r"((?:19|20)\d\d)", str(si.get("time_context") or "").strip())
    return bool(m) and int(m.group(1)) <= datetime.date.today().year - years


def _period_lines() -> Optional[float]:
    """The real-detail floor a period line's clip is held to (None = the modern one)."""
    return float(getattr(config, "PERIOD_REAL_LINES", 400) or 400) if _period_line() else None


def clip_detail_reason(path: str, title: str = "", source: str = "") -> str:
    """Why a downloaded clip is turned down on its real detail ("" = kept): a modern clip whose
    best frame holds under MIN_CLIP_REAL_HEIGHT lines (an upscaled upload). Archive film is
    exempt; so is anything that cannot be measured. A period line's clip (PERIOD_FOOTAGE_YEARS)
    is held to PERIOD_REAL_LINES."""
    got = _sharpness.clip_check(path, archive=_is_archive(title, source), need=_period_lines())
    return "" if got["ok"] else got["why"]


def _note_detail(asset: Optional["MediaAsset"]) -> None:
    """The measured real detail on a passed asset's score parts (its rank among near ties,
    the editor's view of the pick). Only reads what the checks already measured (cached)."""
    if asset is None or not asset.local_path:
        return
    try:
        if asset.kind == "image" and _sharpness.picture_on() and asset.source != "generated":
            got = _sharpness.picture_check(asset.local_path)
            if got["magnification"] is not None:
                asset.score_parts = dict(asset.score_parts or {}, magnification=got["magnification"])
        elif asset.kind == "video" and _sharpness.clip_on():
            got = _sharpness.clip_check(asset.local_path)
            if got["lines"] is not None:
                asset.score_parts = dict(asset.score_parts or {}, lines=got["lines"])
    except Exception:  # noqa: BLE001 - a note only
        pass


def _worth_a_try(candidate: MediaAsset, used: Optional[set]) -> bool:
    """The free look at a candidate before its download: not on this timeline, not shown
    in an earlier video, not an AI picture site or name, not found unusable by another scene."""
    if used is not None and candidate.identity in used:
        return False
    # Shown in an earlier video (src/ledger.py): the page, the photo URL.
    if (candidate.kind == "image" and ledger.photo_used(candidate.url)) or \
            (candidate.kind == "video" and ledger.url_used(candidate.url)):
        return False
    # An AI picture site or an AI-made picture by its name (src/slop.py).
    from . import slop
    if slop.enabled() and (slop.ai_host(candidate.url, getattr(candidate, "page_url", "") or "")
                           or slop.metadata_reason(candidate.attribution)):
        return False
    return not _is_bad(candidate.identity)  # another scene found it unusable


def _downloads_ahead(candidates: List[MediaAsset], used: Optional[set], query: str, work_dir: str):
    """
    (candidate, its download or None) in the candidates' order, for each one
    worth a try. Up to PICTURE_PREFETCH downloads run at once, each under the
    asking scene's own stop: while one picture is checked and judged, the next
    PICTURE_PREFETCH - 1 are already downloading instead of each waiting for
    the one before it. When the caller stops asking (a picture kept), the
    downloads not started never start and those running finish on their own -
    at most PICTURE_PREFETCH - 1 a search did not need.
    """
    ahead = int(getattr(config, "PICTURE_PREFETCH", 0) or 0)
    todo = (c for c in candidates if _worth_a_try(c, used))
    if ahead <= 1:
        for c in todo:
            yield c, _download(c, query, work_dir)
        return
    window: list = []
    pools: list = []

    def fill(limit: int) -> None:
        while len(window) < limit:
            c = next(todo, None)
            if c is None:
                return
            if not pools:
                pools.append(_new_pool(ahead))
            window.append((c, pools[0].submit(contextvars.copy_context().run, _download, c, query, work_dir)))
    try:
        fill(ahead)
        while window:
            c, fut = window.pop(0)
            try:
                got = fut.result()
            except Exception:  # noqa: BLE001 - a download that broke is one that failed
                got = None
            fill(ahead - 1)                 # the next ones download while this one is checked
            yield c, got
    finally:
        for _c, fut in window:
            fut.cancel()
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)
            if not any(fut.running() for _c, fut in window):
                _forget_pool(pool)          # nothing left in flight: the job's end need not wait for it


def _pick_unused(candidates: List[MediaAsset], used: Optional[set],
                 query: str, work_dir: str, intent: str = "",
                 context: str = "") -> Optional[MediaAsset]:
    """First unused candidate that downloads, passes the checks every caller asks
    of a picture afterwards (_asset_ok: not a page of text, big enough, sharp
    enough to fill the frame - src/sharpness.py) before any vision call, and
    passes the vision gate. The candidates download a few at a time ahead of
    the checks (_downloads_ahead); they are checked and judged in order."""
    ahead = _downloads_ahead(_bigger_first(candidates), used, query, work_dir)
    try:
        return _first_that_passes(ahead, used, intent, context)
    finally:
        ahead.close()                       # the downloads not started never start


def _first_that_passes(ahead, used: Optional[set], intent: str, context: str) -> Optional[MediaAsset]:
    judged = 0
    for candidate, got in ahead:
        if (used is not None and candidate.identity in used) or _is_bad(candidate.identity):
            continue                        # taken, or found unusable, while it downloaded
        if not got:
            continue
        if got.kind == "image" and _photo_seen_before(got.local_path):
            continue
        # Too soft to fill the frame (src/sharpness.py): no vision call is spent on it,
        # and no other scene downloads it again. A picture gets the whole verdict its
        # caller asks of it afterwards (_asset_ok), here, before the judge: a page of
        # text used to pass the judge, come back and be thrown out - and the scene
        # then searched again from the start (the Yellowstone re-cut, 2026-10-04: 6 of
        # its 39 empty pieces ended on "a page of text, not a photo").
        t0 = time.time()
        if got.kind == "image":
            ok, why = _asset_ok(got)
            why = "" if ok else (why or "not usable")
        else:
            why = clip_detail_reason(got.local_path, got.attribution, got.source)
        _stage(f"checks:{'picture' if got.kind == 'image' else 'file'}", time.time() - t0)
        if why:
            print(f"[media] REJECT before judging: {why}: {_image_label(got)[:60]!r}", flush=True)
            _mark_bad(candidate.identity, "", why)
            continue
        judged += 1
        _GATE_SLOP.set("")
        keep, verdict = _vision_gate(got.local_path, intent, context, _image_label(got), source_url=got.url)
        if keep:
            _note_detail(got)
            return got.apply_verdict(verdict, intent)
        _mark_bad(candidate.identity, "", _GATE_SLOP.get())
        if judged >= config.VISION_MAX_CANDIDATES:
            break
    return None


def clips_first_for(visual_type: str, subject_type: str = "", scene_intent: Optional[dict] = None) -> bool:
    """
    Whether a line searches clips on all its wordings and wider rungs before any picture
    (config.CLIPS_FIRST): every footage line, and - with CLIPS_FIRST_STILLS - a still line that is not
    a document, a named person's portrait or a map / chart / document line (those keep pictures first).
    A YouTube-only job keeps its own one-source order.
    """
    if not getattr(config, "CLIPS_FIRST", False) or youtube_only():
        return False
    if visual_type == "footage":
        return True
    if visual_type != "image" or not getattr(config, "CLIPS_FIRST_STILLS", False):
        return False
    if config.PREFER_GENERATED_IMAGES:
        return False                    # an illustrated style: its stills are its illustrations
    if (subject_type or "") in ("document", "person"):
        return False
    return wanted_kind(scene_intent if isinstance(scene_intent, dict) else {}) not in ("map", "chart", "document")


# Years, decades, brackets and slashes: never part of a rung's subject.
_RUNG_NOISE = re.compile(r"\((?:[^)]*)\)|\b(?:1[89]|20)\d\d(?:s)?\b|[/|]")
# The medium words a planner query carries ("footage", "aerial", "archival"...): a rung adds its own.
_RUNG_MEDIUM = re.compile(r"\b(?:footage|video|clips?|b-?roll|aerial|drone|archival|archive|news|report|photos?|"
                          r"pictures?|images?|close[- ]?up|wide|shot|4k|hd)\b", re.I)


# A place a planner split into words ("Portland", "Harbour", "Maine"; "Lake", "Mead"; "New", "York"): one of
# its words is a feature noun or a name's first word. "Kenya", "Hawaii" are two places.
_PLACE_PART = re.compile(r"^(?:harbou?r|bay|river|lake|county|city|valley|beach|island|islands|park|dam|canyon|"
                         r"mountains?|mount|mt|falls|creek|port|coast|delta|basin|reservoir|desert|springs?|"
                         r"new|san|santa|los|las|el|la|le|saint|st|fort|north|south|east|west|upper|lower|"
                         r"great|little|grand)$", re.I)


def _rung_label(text: str, words: int = 5) -> str:
    t = _RUNG_MEDIUM.sub(" ", _RUNG_NOISE.sub(" ", str(text or "")))
    t = " ".join(w for w in t.replace(",", " ").split() if w.strip("-'"))
    return " ".join(t.split()[:words]).strip()


def clip_rungs(query: str, subject: str = "", scene_intent: Optional[dict] = None,
               taken=(), limit: Optional[int] = None, person: bool = False) -> List[dict]:
    """
    A clip-first line's wider rungs, after its own wordings found no clip: [{"query", "label"}], each a
    YouTube search for the thing the line is about - for a line about an event at a place, that event
    there ("Portland Maine coastal flooding footage"), then its subject ("Barack Obama footage"), its
    entities and its places - judged as "shows <label>" (rung_judging), not as the line's exact moment.
    Never a wording the line already asked (`taken`); at most `limit` (config.CLIP_RUNGS). A line about a
    named `person` gets the person's own rung only: an entity or place rung shows other people, and on
    that line any face reads as the person's.
    """
    limit = int(getattr(config, "CLIP_RUNGS", 0) or 0) if limit is None else int(limit)
    if limit <= 0:
        return []
    si = scene_intent if isinstance(scene_intent, dict) else {}

    def strs(key: str, n: int) -> List[str]:
        vals = si.get(key)
        vals = [vals] if isinstance(vals, str) else (vals if isinstance(vals, (list, tuple)) else [])
        return [str(v) for v in vals if isinstance(v, str) and v.strip()][:n]
    entities = [_rung_label(e) for e in strs("entities", 2)]
    places = [_rung_label(p, 4) for p in strs("locations", 3)]
    # "Portland", "Harbour", "Maine": a planner that split one place into words gets them joined back -
    # never two places ("Kenya", "Hawaii": no feature noun, no name's first word among them).
    one_place = any(_PLACE_PART.match(p.strip(".")) for p in places)
    if len(places) > 1 and all(len(p.split()) == 1 for p in places) and one_place:
        places = [" ".join(places)]
    event = _rung_label(si.get("event_type") or "", 3) if si.get("specificity") == "event" else ""
    # A past event's year goes in its event-at-place search (never in its label): "Las Vegas presidential
    # debate footage" answered the 2020 Democratic debates there, the 2016 one the line is about came last.
    # A current event's is left out (its searches ask for recent uploads instead).
    year_m = re.match(r"((?:19|20)\d\d)$", str(si.get("time_context") or "").strip())
    past_year = year_m.group(1) if year_m and int(year_m.group(1)) <= datetime.date.today().year - 2 else ""
    labels: List[str] = []
    event_label = ""
    if person:
        labels.append(_rung_label(subject))
    else:
        if event and places:
            event_label = f"{places[0]} {event}"
            labels.append(event_label)
        labels.append(_rung_label(subject))
        labels += entities + places
    done = {str(t).strip().lower() for t in (taken or ())}
    out, seen = [], set()
    for label in labels:
        key = label.strip().lower()
        if len(key) < 4 or key in seen:
            continue
        seen.add(key)
        q = f"{label} {past_year} footage" if label == event_label and past_year else f"{label} footage"
        if q.lower() in done or label.lower() in done:
            continue
        out.append({"query": q, "label": label})
        if len(out) >= limit:
            break
    return out


def rung_judging(intent: str, scene: Optional[dict], rung: dict) -> tuple:
    """
    (intent, scene intent, event) a wider rung's candidate is judged on: real footage that clearly shows
    the subject the rung names passes, whether or not it shows the line's exact moment; another
    country's or region's footage, or another kind of event, does not.
    """
    label = str((rung or {}).get("label") or "").strip()
    if not label:
        return intent, scene, False
    text = (f"Clear real footage of {label} itself - its people, its place, its setting. Score 0.75-0.9 when "
            f"the frames clearly show {label} (higher when they also fit the line's moment), below 0.6 when "
            f"{label} is not clearly what is shown, or the footage is from another country or region, or shows "
            f"another kind of event than the story's. The line: {intent}")[:700]
    si = dict(scene) if isinstance(scene, dict) else None
    if si is not None:
        si["specificity"] = "generic"
        si["generic_ok"] = True
        # The line's era stays when it is in the past (a 1960s line never takes today's footage); a
        # present or unknown time is let go (the subject as it looks, whenever it was filmed).
        try:
            from .intent import SceneIntent     # (`intent` is the line's text here)
            past = SceneIntent.from_dict(scene).is_historical()
        except Exception:  # noqa: BLE001 - an odd scene intent: no era
            past = False
        if not past:
            si["time_context"] = "unknown"
    return text, si, False


def _clip_stage_stop(plan: List[tuple]):
    """
    A token for a clip-first line's clip stages' own stop (CLIPS_FIRST_CLIP_SHARE of the line's time left),
    set on this thread - None when no picture stage follows them (they get all of it), the line has no own
    stop time, or the share is 1. The caller resets it before the first picture stage.
    """
    share = float(getattr(config, "CLIPS_FIRST_CLIP_SHARE", 1.0) or 1.0)
    if share >= 1.0 or not any(stage not in ("youtube", "other_footage") for stage, _q, _r in plan):
        return None
    got = _ytdlp.STOP.get()
    if not got:
        return None
    box, own = got
    now = time.time()
    if not own or own <= now:
        return None
    return _ytdlp.STOP.set((box, now + max(0.0, share) * (own - now)))


def _clip_first_plan(query: str, attempts: List[str], subject: str, scene_intent: Optional[dict],
                     no_stills: bool = False) -> List[tuple]:
    """
    The order a clip-first line asks its sources in: [(stage, wording, rung or None)] - YouTube on its own
    first CLIP_WORDINGS wordings, YouTube on its wider rungs (clip_rungs), the other clip sources on its
    first CLIP_OTHER_WORDINGS wordings, then (unless `no_stills`) pictures on every wording and one
    illustration (none when illustrations are asked for first: PREFER_GENERATED_IMAGES).
    """
    own = attempts[:max(1, int(getattr(config, "CLIP_WORDINGS", 1) or 1))]
    rungs = clip_rungs(query, subject, scene_intent, taken=attempts, person=_SUBJECT_TYPE.get() == "person")
    plan = [("youtube", q, None) for q in own] + [("youtube", r["query"], r) for r in rungs]
    plan += [("other_footage", q, None) for q in attempts[:max(0, int(getattr(config, "CLIP_OTHER_WORDINGS", 0) or 0))]]
    if not no_stills:
        plan += [("pictures", q, None) for q in attempts]
        if not config.PREFER_GENERATED_IMAGES:
            plan.append(("generated", attempts[0], None))
    return plan


def source_for_segment(query: str, seconds: float, work_dir: str, *,
                       visual_type: str = "footage", nth: int = 0,
                       used: set = None, fallbacks: List[str] = None,
                       prompt: str = "",
                       allow_youtube: bool = None, allow_stock: bool = None,
                       require_cc: bool = None, intent: str = "",
                       context: str = "", subject_type: str = "",
                       subject: str = "", event_window: str = "",
                       scene_intent: Optional[dict] = None, hook: bool = False,
                       recency: str = "", start: Optional[float] = None,
                       clips_only: bool = False) -> Optional[MediaAsset]:
    """
    Source one scene, relaxing the query until something is found.

    The specific phrasing is tried first because it gives the most relevant
    visual; each fallback is broader. Without this a precise query that
    matches nothing leaves the scene black, which is far worse than a
    slightly more general shot of the right subject.

    subject_type "person": the line is about a named person, so a portrait or
    that person speaking passes the vision gate, and no image is ever
    GENERATED - an invented photo of a real person is a fabrication.

    hook: the scene opens the video (the job's "hook" flag). It is a footage
    beat unless it shows a document, it looks harder for its clip
    (_judge_limits) and it is never given a generated image (the owner,
    2026-09-30). recency "month": a line of a story about now, whose searches
    ask for the last month's uploads first.

    Clips first (config.CLIPS_FIRST, clips_first_for): YouTube on the line's own
    wordings and then on its wider rungs (clip_rungs), the other clip sources,
    and only then pictures and one illustration (_clip_first_plan) - a line in
    the first HOOK_NO_STILL_SECONDS (`start`) takes no picture here at all.
    `clips_only`: the clip stages only (the rescue pass, the reclip action).
    """
    if _ytdlp.stopped():
        # The job's sourcing time is spent (or this scene's): the beat goes to
        # the fallback ladder and, failing that, becomes a graphic.
        return None
    if config.REQUIRE_AI and vision.ai_exhausted():
        return None   # the job is stopping; do not spend on searches it will discard
    if hook and visual_type == "image" and subject_type != "document":
        visual_type = "footage"
    clip_first = clips_only or clips_first_for(visual_type, subject_type, scene_intent)
    still_line = visual_type == "image"             # (a still line keeps its pictures under the photo cap)
    if clip_first:
        visual_type = "footage"                     # the clip stages ask the footage sources
    first_token = _CLIP_FIRST.set(bool(clip_first))
    token = _SUBJECT_TYPE.set(subject_type or "")
    window_token = _EVENT_WINDOW.set(event_window or "")
    intent_token = _SCENE_INTENT.set(scene_intent or None)
    judged_token = _SCENE_JUDGED.set([0])
    tried_token = _SCENE_TRIED.set(set())
    hook_token = _IN_HOOK.set(bool(hook))
    shown_token = _SHOWN_SECONDS.set(seconds)       # a hook clip's opening check reads this span
    recency_token = _RECENCY.set(recency or "")
    # A footage beat falls back to a photo only while the style's photo cap
    # (PHOTO_MAX_PER_10MIN) has room; after that it stays a footage search
    # and an empty beat goes to the spare moments and the rescue pass.
    allowed = _ENABLED_PROVIDERS.get()
    providers_token = None
    if visual_type == "footage" and not still_line and not _photos_left():
        only = _footage_providers() if allowed is None else set(allowed) & _footage_providers()
        providers_token = _ENABLED_PROVIDERS.set(only)
    clip_stop = None                                # the clip stages' own, earlier stop (_clip_stage_stop)
    try:
        from .director import relaxed_queries
        attempts = list(dict.fromkeys([query] + list(fallbacks or []) + relaxed_queries(query)))
        if clip_first:
            no_stills = bool(clips_only) or bool(
                hook and start is not None and float(start) < float(getattr(config, "HOOK_NO_STILL_SECONDS", 0) or 0))
            plan = _clip_first_plan(query, attempts, subject, scene_intent, no_stills=no_stills)
        else:
            # A still line (STILLS_ALL_WORDINGS_FIRST) asks every wording for pictures first, then
            # lets footage stand in for the still on every wording, then one illustration - each
            # wording used to walk pictures, footage and an illustration before the next wording
            # was asked at all (the Yellowstone re-cut, 2026-10-04: 140 YouTube sections for 10
            # clip pieces, and Wikimedia Commons answers the short wordings that come last).
            stages: List[Optional[str]] = [None]
            if visual_type == "image" and getattr(config, "STILLS_ALL_WORDINGS_FIRST", False) and not youtube_only():
                stages = ["pictures", "footage"] + ([] if config.PREFER_GENERATED_IMAGES else ["generated"])
            plan = [(stage, attempt, None) for stage in stages
                    for attempt in (attempts[:1] if stage == "generated" else attempts)]
        # A clip-first line keeps a near-miss clip (under the judge's floor: "Best available") only until
        # its clip stages are done - a passing clip on a later wording or rung wins - and then before any
        # picture, as a near-miss always has.
        soft: Optional[MediaAsset] = None
        clips_done = False
        clips_cut = False                           # the clip stages' share ran out before they were done
        wordings = 0                                # the line's own wordings YouTube was asked so far
        # Pictures after the clips: the clip stages stop at CLIPS_FIRST_CLIP_SHARE of the line's own time,
        # the rest is the pictures' (a long clip search used to leave the line empty).
        clip_stop = _clip_stage_stop(plan) if clip_first else None
        for stage, attempt, rung in plan:
            clip_stage = stage in ("youtube", "other_footage")
            if clip_stop is not None and (not clip_stage or _ytdlp.stopped()):
                _ytdlp.STOP.reset(clip_stop)
                clip_stop = None
                if clip_stage and not _ytdlp.stopped():
                    # Only the clips' share is spent (not the line's own time): on to the pictures.
                    clips_cut = True
                    print(f"[media] clip stages out of their share: pictures for {query[:60]!r}", flush=True)
            if clips_cut and clip_stage:
                continue
            if _ytdlp.stopped():
                break
            if clip_first and not clips_done and not clip_stage:
                clips_done = True
                if not clips_cut:
                    with _CACHE_LOCK:
                        _CLIP_SEARCHED.add(_searched_key(query, subject))
            if soft is not None and stage not in ("youtube", "other_footage"):
                _count_photo(soft)
                return soft
            rung_token = _RUNG.set(rung) if rung else None
            wording_token = None
            if clip_first and stage == "youtube" and not rung:
                wording_token = _WORDING.set(wordings)
                wordings += 1
            try:
                got = _source_one(attempt, seconds, work_dir, visual_type=visual_type,
                                  nth=nth, used=used, prompt=prompt,
                                  allow_youtube=allow_youtube,
                                  allow_stock=allow_stock, require_cc=require_cc,
                                  intent=intent or query, context=context,
                                  subject=subject, **({"stage": stage} if stage else {}))
            finally:
                if wording_token is not None:
                    _WORDING.reset(wording_token)
                if rung_token is not None:
                    _RUNG.reset(rung_token)
            if got and stage in ("youtube", "other_footage") and got.kind != "video":
                # A clip stage keeps clips only (an archive's search can hold its stills too).
                if got.local_path and os.path.exists(got.local_path):
                    try:
                        os.remove(got.local_path)
                    except OSError:
                        pass
                got = None
            if got and rung and got.kind == "video":
                # Found on a wider rung: it shows the line's subject, not necessarily its moment.
                got.score_parts = dict(got.score_parts or {}, rung=str(rung.get("label") or "")[:80])
            if got and clip_first and stage in ("youtube", "other_footage") and _near_miss(got):
                keep, drop = (got, soft) if soft is None or (got.relevance_score or 0) > (soft.relevance_score or 0) \
                    else (soft, got)
                if drop is not None and drop.local_path and drop.local_path != keep.local_path \
                        and os.path.exists(drop.local_path):
                    try:
                        os.remove(drop.local_path)
                    except OSError:
                        pass
                soft = keep
                continue
            if got:
                if soft is not None and soft.local_path and os.path.exists(soft.local_path):
                    try:
                        os.remove(soft.local_path)
                    except OSError:
                        pass
                _count_photo(got)
                return got
        if clip_first and not clips_done and not clips_cut and not _ytdlp.stopped():
            with _CACHE_LOCK:
                _CLIP_SEARCHED.add(_searched_key(query, subject))     # a clips-only plan, run to its end
        if soft is not None:
            _count_photo(soft)
        return soft
    finally:
        if clip_stop is not None:
            _ytdlp.STOP.reset(clip_stop)
        _CLIP_FIRST.reset(first_token)
        if providers_token is not None:
            _ENABLED_PROVIDERS.reset(providers_token)
        _RECENCY.reset(recency_token)
        _SHOWN_SECONDS.reset(shown_token)
        _IN_HOOK.reset(hook_token)
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
                context: str = "", subject: str = "",
                stage: Optional[str] = None) -> Optional[MediaAsset]:
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
    `stage` asks one part of a still line's list only (providers.still_stage).
    """
    allow_youtube = config.ALLOW_YOUTUBE if allow_youtube is None else allow_youtube
    allow_stock = config.ALLOW_STOCK if allow_stock is None else allow_stock
    require_cc = config.REQUIRE_CC if require_cc is None else require_cc
    if youtube_only():
        visual_type, allow_youtube, allow_stock = "footage", True, False
        stage = None
    ctx = providers.SourceContext(
        query=query, seconds=seconds, work_dir=work_dir, visual_type=visual_type, nth=nth,
        used=used, prompt=prompt, allow_youtube=bool(allow_youtube), allow_stock=bool(allow_stock),
        require_cc=bool(require_cc), intent=intent, context=context, subject=subject,
        subject_type=_SUBJECT_TYPE.get() or "", youtube_only=bool(youtube_only()),
        enabled_names=_ENABLED_PROVIDERS.get(), stage=stage,
        current=(_RECENCY.get() or "") in ("month", "week") or _EVENT_WINDOW.get() == "year")
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
    # The era's own broadcast video for a line about a past year (PERIOD_FOOTAGE_YEARS, off by default).
    period = asset.kind == "video" and not archive and _period_line()
    # A page of text (slide, screenshot, scan) only for a beat about a document.
    if asset.kind == "image" and _SUBJECT_TYPE.get() != "document" and _filters.text_page_still(path):
        return False, "a page of text, not a photo"
    ok, why = clip_quality(path, config.MIN_ARCHIVE_HEIGHT if archive else (
        int(getattr(config, "PERIOD_MIN_HEIGHT", 480) or 480) if period else config.MIN_CLIP_HEIGHT))
    if not ok:
        return ok, why
    # Real detail, not file size (src/sharpness.py): a picture the screen would blow up
    # past MAX_PICTURE_MAGNIFICATION, a modern clip with fewer real lines than
    # MIN_CLIP_REAL_HEIGHT (an upscaled upload). Measured once per file (cached).
    if asset.kind == "image":
        why = picture_blur_reason(path)
    elif asset.kind == "video":
        got = _sharpness.clip_check(path, archive=archive, need=_period_lines() if period else None)
        why = "" if got["ok"] else got["why"]
        if not why and period:
            # Taken as the era's own video: the scene says so (semanticMetadata.scoreParts.period), so the
            # check before the render holds it to the same floor (quality.Gate._soft_scenes, period_need).
            asset.score_parts = dict(asset.score_parts or {}, period=True)
    return (False, why) if why else (True, "")


def period_need(sem: Optional[dict]) -> Optional[float]:
    """
    The real-detail floor a placed clip is held to before the render: PERIOD_REAL_LINES for a clip taken as
    the era's own video (scoreParts.period, or - PERIOD_FOOTAGE_YEARS on - a line about a year long past),
    None (the modern floor) for every other. The Obama render of 2026-10-07 swapped two such clips the
    re-clip had placed for pictures, as "low detail".
    """
    sem = sem if isinstance(sem, dict) else {}
    parts = sem.get("scoreParts") if isinstance(sem.get("scoreParts"), dict) else {}
    if parts.get("period"):
        return float(getattr(config, "PERIOD_REAL_LINES", 400) or 400)
    si = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else None
    if si is None:
        return None
    token = _SCENE_INTENT.set(si)
    try:
        return _period_lines()
    finally:
        _SCENE_INTENT.reset(token)


_ARCHIVE_TITLE_RE = re.compile(r"\b(newsreel|archive|archival|pathe|path\u00e9|periscope|movietone|travelogue|"
                               r"huntley|18\d\d|19[0-8]\d|1990s?)\b", re.I)


def _asset_ok_for(job: Optional[Dict[str, Any]], asset) -> tuple:
    """
    _asset_ok in the line's own context. Outside source_for_segment - pass 2's check and its
    replacements, the rescue and the fallback ladder's pictures - the line's subject type
    was not set, so a document line's scan, its right shot, was turned down as "a page of
    text, not a photo": the scan found in pass 1 was dropped, three paid searches brought
    scans turned down the same way, and the line ended empty (verified 2026-10-05).
    """
    token = _SUBJECT_TYPE.set(str((job or {}).get("subject_type") or ""))
    try:
        return _asset_ok(asset)
    finally:
        _SUBJECT_TYPE.reset(token)


def _verdicts(assets: Dict[int, Optional["MediaAsset"]], workers: int = 6,
              jobs: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[int, tuple]:
    """_asset_ok for many assets at once, by index (each reads its own file; a check that
    breaks is left out, for the caller to run again where it would have run). `jobs`: each
    index's line, whose context the check runs in (_asset_ok_for)."""
    items = [(i, a) for i, a in assets.items() if a is not None]
    out: Dict[int, tuple] = {}
    if len(items) < 2:
        return out

    def check(i: int, a) -> tuple:
        return _asset_ok_for(jobs[i], a) if jobs and i in jobs else _asset_ok(a)
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers or 1), len(items)))) as pool:
        futures = {pool.submit(contextvars.copy_context().run, check, i, a): i for i, a in items}
        for fut in as_completed(futures):
            try:
                out[futures[fut]] = fut.result()
            except Exception:  # noqa: BLE001 - checked again in order
                pass
    return out


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


def _forget_pool(pool: ThreadPoolExecutor) -> None:
    """A pool with nothing left running: no longer one the job's end waits for."""
    with _POOLS_LOCK:
        try:
            _LIVE_POOLS.remove(pool)
        except ValueError:
            pass


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


def scene_seconds(left: float, workers: int, n: int) -> float:
    """
    One scene's own share of a time-boxed pass, or 0 (no limit of its own):
    when more scenes wait than threads run, the pass's seconds x threads /
    scenes, kept between SCENE_SECONDS_MIN and SCENE_SECONDS_MAX - every scene
    gets its turn before the box closes, instead of the first ones spending it
    on fallback after fallback (Lake Powell: 49 of 130 scenes in 1800 s).
    """
    if config.SCENE_SECONDS_MAX <= 0 or left <= 0 or n <= max(1, workers):
        return 0.0
    share = left * max(1, workers) / float(n)
    return max(config.SCENE_SECONDS_MIN, min(config.SCENE_SECONDS_MAX, share))


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
    with _CACHE_LOCK:
        if _PHOTOS["cap"] is None:
            # This worker's share of the video's photos (a fan-out part: its lines').
            _PHOTOS["cap"] = photo_cap(_jobs_seconds(jobs))
    if work_dir:
        _WORK["dir"] = work_dir
    # Chain lines are not searched: they continue the line before's clip
    # (fill_chains, after sourcing). Any still empty then go to the rescue.
    chained = {j["index"] for j in ordered if is_chain(j)}

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
    pass1 = [(j, nth) for j, nth in plan if results[j["index"]] is None and j["index"] not in chained]
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
            **_scene_flags(job), **kwargs)

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

    # Pass 1's time box, shared by its scenes (closed when the pass ends, so a
    # scene it gave up on stops at its next network call), and each scene's
    # own share of it when more scenes wait than threads run (scene_seconds).
    box = _ytdlp.Box()
    share = [0.0]

    def fetch(job, nth):
        own = (time.time() + share[0] * (1.5 if job.get("hook") else 1.0)) if share[0] else 0.0
        token = _ytdlp.STOP.set((box, own))
        try:
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
        finally:
            _ytdlp.STOP.reset(token)

    # Not a `with` block: its exit waits for every thread, and one hung
    # download then holds the whole video. A real job sat at "Sourced 22/23"
    # for over ten minutes on a single stalled scene. Stragglers are left
    # running in the background and their scenes fall through to the
    # recheck / fill steps below, which exist for exactly that.
    pool = _new_pool(max(1, workers))
    started = time.time()
    deadline = started + _budget(config.PASS1_BUDGET_SECONDS, 3.0, len(pass1))
    if _ytdlp.DEADLINE[0]:
        # The job's sourcing deadline wins: a part must hand back what it found
        # (and upload it) before the parent stops waiting, or all of it is lost.
        deadline = min(deadline, _ytdlp.DEADLINE[0] - 25.0)
    box.shorten(deadline)
    share[0] = scene_seconds(deadline - started, workers, len(pass1))
    if share[0]:
        print(f"[media] pass 1: {len(pass1)} scene(s) on {workers} thread(s) in {deadline - started:.0f}s, "
              f"{share[0]:.0f}s a scene at most", flush=True)
    # Started in coverage order (src/gapfill.py): the hook's lines first, then
    # every other line spread over the whole video. In story order the pool
    # reached the ending last, and when the owner's 159-scene Lake Powell job
    # ran out of time its last 23 lines were the ones left empty (2026-10-01).
    nths = {j["index"]: nth for j, nth in pass1}
    from . import gapfill
    futures = {pool.submit(fetch, job, nths[job["index"]]): job["index"]
               for job in gapfill.coverage_order([j for j, _nth in pass1])}
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
                box.shorten(deadline)
        if pending:
            stuck = sorted(futures[f] + 1 for f in pending)
            print(f"[media] gave up waiting on scene(s) {stuck}; they go to the recheck",
                  flush=True)
            LAST_STATS["pass1_stragglers"] = len(stuck)
            LAST_STATS["pass1_never_started"] = sum(1 for f in pending if not f.running())
            with lock:
                done += len(pending)
                if on_done:
                    on_done(done, len(jobs))
    finally:
        box.end()                       # the scenes still running stop at their next network call
        pool.shutdown(wait=False, cancel_futures=True)
    LAST_STATS["scene_seconds"] = round(share[0], 1)

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
    # Each check reads its own file (a clip's frames, a picture's real detail): they run
    # side by side first, and the scenes are then decided in story order as before.
    verdicts = _verdicts({job["index"]: results[job["index"]] for job, _nth in plan}, workers,
                         jobs={job["index"]: job for job, _nth in plan})
    for job, nth in plan:
        i = job["index"]
        asset = results[i]
        if asset is None:
            if i in chained:
                continue                    # filled from the line before's clip later
            empty += 1
            todo.append((job, nth, "", False))
            continue
        ok, why = verdicts[i] if i in verdicts else _asset_ok_for(job, asset)
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
    box2 = _ytdlp.Box(deadline)         # pass 2's own box, closed when it ends

    def replace(job, nth, bad_reason, is_dup):
        token = _ytdlp.STOP.set((box2, 0.0))
        try:
            return replace_in_box(job, nth, bad_reason, is_dup)
        finally:
            _ytdlp.STOP.reset(token)

    def replace_in_box(job, nth, bad_reason, is_dup):
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
                    **_scene_flags(job), **kwargs)
            except Exception:  # noqa: BLE001
                candidate = None
            if not candidate:
                continue
            ok, why = _asset_ok_for(job, candidate)
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
            box2.end()
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
               if (results[job["index"]] is None and job["index"] not in chained) or is_repeat(results[job["index"]])]
    if empties and rescue:
        if on_recheck:
            on_recheck(len(empties))
        ideas = rescue([recheck_item(j) for j in empties]) or {}
        rescue_deadline = time.time() + _budget(config.RESCUE_BUDGET_SECONDS, 3.0, len(empties))
        box3 = _ytdlp.Box(rescue_deadline)

        def rescue_one(job):
            alts = ideas.get(job["index"]) or []
            if not alts or time.time() >= rescue_deadline:
                return None
            _ytdlp.STOP.set((box3, 0.0))      # this task runs in its own copied context
            try:
                got = source_for_segment(
                    alts[0], float(job.get("seconds") or 0), work_dir,
                    visual_type=job.get("visual_type", "footage"), used=used,
                    fallbacks=alts[1:], prompt=job.get("prompt", ""),
                    intent=job.get("intent", ""), context=job.get("context", ""),
                    subject_type=job.get("subject_type", ""),
                    event_window=job.get("event_window", ""),
                    scene_intent=job.get("scene_intent"), **_scene_flags(job), **kwargs)
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
            box3.end()
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
    # Never in the hook either (the owner, 2026-09-30): the opening scenes
    # stay empty for the job's rescue pass to find footage for.
    empties = [job for job, _ in plan if results[job["index"]] is None and _may_generate_for(job)
               and job["index"] not in chained]
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

    fresh = fresh_moments([j for j in ordered if j["index"] not in chained], results, work_dir) \
        if config.FRESH_MOMENTS else 0
    if fresh:
        print(f"[media] {fresh} scene(s) got another moment of a video the story already uses "
              f"instead of a repeated shot", flush=True)
    LAST_STATS.update(fresh_moments=fresh)
    # Reusing a shot waits until after the job's rescue pass has looked for fresh
    # footage (handler): run here first, it filled 51 of 164 scenes with repeats.
    # Never with NO_REUSE (the owner, 2026-10-01: never reuse a clip within a video).
    reused = (fill_from_story(ordered, results)
              if config.REUSE_SHOTS_TO_FILL and not config.RESCUE_BEFORE_REUSE and not config.NO_REUSE else 0)
    if reused:
        print(f"[media] reused a shot from elsewhere in the story for {reused} "
              f"scene(s) nothing else could fill", flush=True)
    try:
        LAST_STATS["ledger"] = ledger.stats()           # what earlier videos kept out of this one
    except Exception:  # noqa: BLE001 - stats only
        pass
    with _CACHE_LOCK:
        LAST_STATS["photos"] = {"cap": _PHOTOS["cap"], "used": _PHOTOS["used"]}
        LAST_STATS["slop_rejected"] = dict(SLOP_REJECTED)
    LAST_STATS["stockBlocked"] = _stockblock.stats()        # the handler refreshes it after the rescue pass
    # Pictures and clips measured for real detail, how many were too soft, the seconds spent.
    LAST_STATS["sharpness"] = _sharpness.stats()
    LAST_STATS["stageSeconds"] = stage_seconds()           # where the sourcing threads' time went
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


# At least config.FALLBACK_MOMENT_GAP_SECONDS (30 s) from the donor's moment:
# another moment of a video shown elsewhere must be clearly another moment.
_FRESH_OFFSETS = (30.0, -30.0, 45.0, -45.0, 70.0, -70.0, 95.0)


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


# --------------------------------------------------------------------------- #
# Variety: a few scenes per source video, far apart (the owner, 2026-09-30)
# --------------------------------------------------------------------------- #
#
# The Texas flood video drew 97 YouTube scenes from 55 videos and showed
# "Drone's eye view of Texas flood damage" 4 times in its first minute. They
# were four DIFFERENT moments of one video, so no duplicate check fired (the
# moment keys "yt:<id>@<bucket>" differ), yet on screen it was one shot again
# and again. These rules are about the SOURCE (video_key) and about where the
# scenes sit on the timeline: the jobs' "start", which handler.do_plan sets;
# a job without one can only be counted, not spaced.


def video_key(asset: Optional[MediaAsset]) -> str:
    """The source a shot was cut from: "yt:<id>" for every moment of one YouTube video, else its identity."""
    if asset is None:
        return ""
    if asset.source == "youtube" or (asset.identity or "").startswith("yt:"):
        vid, _start = _yt_origin(asset)
        if vid:
            return f"yt:{vid}"
    return asset.identity


def scene_starts(jobs: List[Dict[str, Any]]) -> Dict[int, float]:
    """{job index: second its line starts on the timeline}, for the jobs that carry a start."""
    out: Dict[int, float] = {}
    for j in jobs or []:
        at = j.get("start")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            out[j["index"]] = float(at)
    return out


def may_place(prev: List[Optional[float]], at: Optional[float]) -> bool:
    """
    May one more scene starting at `at` be cut from a video whose scenes
    already start at `prev`? At most MAX_MOMENTS_PER_VIDEO scenes per video,
    each SAME_VIDEO_GAP_SECONDS from the others (0 turns a rule off). An
    unknown start is only counted.
    """
    cap = config.MAX_MOMENTS_PER_VIDEO
    if cap > 0 and len(prev) >= cap:
        return False
    gap = config.SAME_VIDEO_GAP_SECONDS
    if at is None or gap <= 0:
        return True
    return all(p is None or abs(at - p) >= gap for p in prev)


def _near_twin(prev: List[Optional[float]], at: Optional[float]) -> bool:
    """A scene at `at` would play within REUSE_MIN_GAP_SECONDS of a scene cut from the same video."""
    gap = config.REUSE_MIN_GAP_SECONDS
    if at is None or gap <= 0:
        return False
    return any(p is not None and abs(at - p) < gap for p in prev)


def _asset_at(results, i: int) -> Optional[MediaAsset]:
    if isinstance(results, dict):
        return results.get(i)
    return results[i] if 0 <= i < len(results) else None


def placements(results, starts: Dict[int, float], skip=()) -> Dict[str, List[Optional[float]]]:
    """{video key: starts of the scenes cut from it} over `results` (a list by index, or a dict)."""
    items = results.items() if isinstance(results, dict) else enumerate(results or [])
    out: Dict[str, List[Optional[float]]] = {}
    for i, a in items:
        if a is None or i in skip or a.kind != "video" or _chain_member(a):
            continue            # a chain's later moments count with the line that opened it
        out.setdefault(video_key(a), []).append(starts.get(i))
    return out


def variety_violations(jobs: List[Dict[str, Any]], results) -> Dict[int, tuple]:
    """
    {scene index: (reason, kind)} for every scene that breaks a variety rule,
    walking the video in story order: the first scene to use a source keeps
    it. `kind`:

      hard     never kept - a generated image in the hook or shown a second
               time, a photo shown more than IMAGE_MAX_USES times;
      soft     kept only when nothing else is found, and never within
               REUSE_MIN_GAP_SECONDS of its twin - the same shot twice, a
               video past MAX_MOMENTS_PER_VIDEO scenes, or one playing again
               within SAME_VIDEO_GAP_SECONDS;
      upgrade  a hook scene on a still, or a photo past the style's photo cap
               (PHOTO_MAX_PER_10MIN over the lines' seconds): footage is
               looked for, and the still stays when none is found.
    """
    starts = scene_starts(jobs)
    by_index = {j["index"]: j for j in jobs or []}
    kept: Dict[str, List[Optional[float]]] = {}
    shots: set = set()
    shown: Dict[str, int] = {}
    out: Dict[int, tuple] = {}
    cap = photo_cap(_jobs_seconds(jobs))
    photos = 0
    for i in sorted(by_index):
        a = _asset_at(results, i)
        if a is None:
            continue
        job = by_index[i]
        hook = bool(job.get("hook"))
        if a.source == "generated":
            if hook and not config.GENERATED_IMAGES_IN_HOOK:
                out[i] = ("a generated image in the opening", "hard")
            elif shown.get(a.identity):
                out[i] = ("a generated image already shown", "hard")
            else:
                shown[a.identity] = 1
            continue
        if a.kind == "image":
            if shown.get(a.identity, 0) >= max(1, config.IMAGE_MAX_USES):
                out[i] = ("a photo already shown", "hard")
                continue
            shown[a.identity] = shown.get(a.identity, 0) + 1
            if hook and job.get("subject_type") != "document":
                out[i] = ("a still in the opening", "upgrade")
            elif cap is not None and job.get("subject_type") != "document":
                photos += 1
                if photos > cap:
                    out[i] = (f"more than the style's {cap} photos", "upgrade")
            continue
        key = video_key(a)
        prev = kept.setdefault(key, [])
        if _chain_member(a):
            continue            # the next moment of the line before's clip: one source with it
        if a.identity in shots:
            out[i] = ("the same shot again", "soft")
            continue
        if not may_place(prev, starts.get(i)):
            cap = config.MAX_MOMENTS_PER_VIDEO
            out[i] = ((f"its video already supplies {len(prev)} scenes" if 0 < cap <= len(prev)
                       else f"its video plays within {config.SAME_VIDEO_GAP_SECONDS:.0f} s"), "soft")
            continue
        shots.add(a.identity)
        prev.append(starts.get(i))
    return out


def is_chain(job: Optional[Dict[str, Any]]) -> bool:
    """A line that plays the next moment of the previous line's clip (director.chain_shots)."""
    si = (job or {}).get("scene_intent")
    return isinstance(si, dict) and si.get("role") == "chain"


def _chain_member(asset: Optional[MediaAsset]) -> bool:
    return bool(asset is not None and isinstance(asset.moment, dict) and asset.moment.get("chain"))


# Where this job's files go, for the passes the handler calls without one
# (fill_chains inside hold_violations): set by source_many and the pools.
_WORK: Dict[str, str] = {"dir": ""}
# Forward past the previous shot's moment: a cut, not a continuous take.
CHAIN_SKIP_SECONDS = 0.8


def fill_chains(jobs: List[Dict[str, Any]], results, work_dir: str = "") -> int:
    """
    Every chain line (director.chain_shots) plays the next moment of the
    previous line's YouTube clip - jumped forward CHAIN_SKIP_SECONDS past what
    that line showed - checked like any clip (quality, the AI-slop and still
    filters, the cross-video ledger). A chain whose clip cannot continue is
    left empty for the rescue pass. Chains run in parallel, each in order.
    Returns how many lines were filled.
    """
    work_dir = work_dir or _WORK["dir"]
    by_index = {j["index"]: j for j in jobs or []}
    todo = [i for i in sorted(by_index) if is_chain(by_index[i]) and _asset_at(results, i) is None]
    if not todo or not work_dir:
        return 0
    runs: List[List[int]] = []
    for i in todo:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])

    def put(i: int, asset: MediaAsset) -> None:
        results[i] = asset                          # a list by index or a dict alike

    def one(run: List[int]) -> int:
        filled = 0
        for i in run:
            prev = _asset_at(results, i - 1)
            if prev is None or prev.kind != "video":
                break
            vid, start = _yt_origin(prev)
            if not vid:
                break
            prev_job = by_index.get(i - 1) or {}
            job = by_index[i]
            shown = float(prev_job.get("seconds") or prev.duration or 5.0)
            at = float(start) + shown + CHAIN_SKIP_SECONDS
            need = max(2.0, float(job.get("seconds") or 5.0)) + SEQ_SHOT_PAD
            if ledger.moment_used(vid, at, at + need):
                break
            path, clean, cuts = fetch_clean_clip(vid, work_dir, at, need, prev.attribution or "")
            if not path:
                break
            if not _asset_ok(MediaAsset(kind="video", source="youtube", url="", local_path=path))[0] \
                    or motion_rejects(path) or slop_reason(path, prev.attribution or ""):
                break
            # Not judged itself: its verdict is the clip before's (judgedBy "chain"); a hook line's
            # chain is judged on its own cut by the hook check (src/hookcheck.py).
            asset = _dc_replace(prev, local_path=path, url=f"https://www.youtube.com/watch?v={vid}&t={int(at)}",
                                duration=need, moment_key=f"yt:{vid}@{int(at // max(1.0, float(config.POOL_MIN_GAP_SECONDS)))}",
                                moment={"start": round(at, 1), "chain": True, "chain_of": prev.identity,
                                        "clean": clean, "cuts": cuts},
                                alternatives=[], intent=job.get("intent") or prev.intent,
                                judged_by="chain", cut_check={})
            put(i, asset)
            filled += 1
        return filled

    total = 0
    with ThreadPoolExecutor(max_workers=max(1, min(6, len(runs)))) as ex:
        for got in ex.map(one, runs):
            total += got
    print(f"[media] clip chains: {total}/{len(todo)} line(s) continue the clip before them", flush=True)
    return total


def hold_violations(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]]) -> Dict[int, tuple]:
    """
    Clear every scene variety_violations names, so the reserve and rescue
    passes treat it like an empty one; returns {index: (asset, reason, kind)}
    for restore_held. Chain lines are filled first (fill_chains): a chain
    continues its clip whatever the variety rules say about the video.
    """
    try:
        fill_chains(jobs, results)
    except Exception as e:  # noqa: BLE001 - a chain left empty goes to the rescue pass
        print(f"[media] clip chains skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    held: Dict[int, tuple] = {}
    for i, (reason, kind) in variety_violations(jobs, results).items():
        held[i] = (results[i], reason, kind)
        results[i] = None
    if held:
        by_kind = Counter(kind for _a, _r, kind in held.values())
        print(f"[variety] {len(held)} scene(s) to find again: {by_kind.get('soft', 0)} repeated video(s), "
              f"{by_kind.get('hard', 0)} repeated or opening image(s), {by_kind.get('upgrade', 0)} "
              f"opening still(s)", flush=True)
    return held


def restore_held(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]],
                 held: Dict[int, tuple]) -> Dict[str, int]:
    """
    After the reserve and rescue passes: put back what nothing replaced,
    where the rules allow - a repeated video only when it does not play within
    REUSE_MIN_GAP_SECONDS of its twin (flagged for review), an opening still
    as it was, a repeated or opening generated image or a repeated photo
    never. Returns {"replaced", "restored", "dropped"}.
    """
    starts = scene_starts(jobs)
    out = {"replaced": 0, "restored": 0, "dropped": 0}
    from . import gapfill
    for i in sorted(held):
        asset, reason, kind = held[i]
        if results[i] is not None:
            out["replaced"] += 1
            continue
        if kind == "hard":
            out["dropped"] += 1
            continue
        if kind == "soft":
            prev = placements(results, starts, skip={i}).get(video_key(asset), [])
            if _near_twin(prev, starts.get(i)):
                print(f"[variety] scene {i + 1}: {reason}, within {config.REUSE_MIN_GAP_SECONDS:.0f} s "
                      "of its twin - left empty", flush=True)
                out["dropped"] += 1
                continue
            # Never a repeat (the owner, 2026-10-01): not the same shot or
            # moment, not its video under FALLBACK_MOMENT_GAP_SECONDS from
            # another of its moments, not its video on the next line.
            why = gapfill.Used.of_results(results, starts).why_not(i, gapfill.Shot.of_asset(asset, starts.get(i))) \
                if config.NO_REUSE else ""
            if why:
                print(f"[variety] scene {i + 1}: {reason} - {why}; left for the fallback fill", flush=True)
                out["dropped"] += 1
                continue
            note = "Same source video as another scene - nothing else was found for this line"
            asset = _dc_replace(asset, review_required=True,
                                review_reason=note + (f"; {asset.review_reason}" if asset.review_reason else ""))
        results[i] = asset
        out["restored"] += 1
    return out


def fresh_moments(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]], work_dir: str) -> int:
    """
    Fill scenes still empty with ANOTHER moment of a same-subject YouTube video
    the story already uses - GoMotion's many-moments-per-video method - rather
    than repeating a shot. Each try is a 10 s bucket no scene uses, 25-95 s
    from the donor's moment, passes clip_quality and (when vision is on) the
    judge against the scene's intent. Parallel, time boxed by
    FRESH_MOMENT_SECONDS. Returns how many scenes were filled.

    A donor video only gives another scene when the variety rules allow it
    (may_place: at most MAX_MOMENTS_PER_VIDEO scenes per video, the same
    video SAME_VIDEO_GAP_SECONDS apart) - the owner's Texas flood video
    (2026-09-30) played four moments of one drone video in its first minute.
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
    starts = scene_starts(jobs)
    placed = placements(results, starts)
    deadline = time.time() + config.FRESH_MOMENT_SECONDS

    def reserve(vid: str, at: Optional[float]) -> bool:
        with lock:
            prev = placed.setdefault(f"yt:{vid}", [])
            if not may_place(prev, at):
                return False
            prev.append(at)
            return True

    def unreserve(vid: str, at: Optional[float]) -> None:
        with lock:
            prev = placed.get(f"yt:{vid}") or []
            if at in prev:
                prev.remove(at)

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
        scene_at = starts.get(i)
        for donor in donors_for(i):
            vid, start = _yt_origin(donor)
            if not reserve(vid, scene_at):
                continue                    # that video has its scenes, or plays too close
            for off in _FRESH_OFFSETS:
                if time.time() > deadline:
                    unreserve(vid, scene_at)
                    return None
                at = start + off
                if at < 3:
                    continue
                key = f"yt:{vid}@{int(at // 10)}"
                with lock:
                    if key in used:
                        continue
                    used.add(key)
                if ledger.moment_used(vid, at, at + need):
                    continue                        # shown in an earlier video
                # With a margin, cut clean: never opening on the end of the shot before (filters.tidy_clip).
                path, clean, cuts = fetch_clean_clip(vid, work_dir, at, need, job.get("subject") or "")
                if not path:
                    continue
                if motion_rejects(path):
                    continue
                asset = MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(at)}",
                                   local_path=path, license=donor.license, attribution=donor.attribution,
                                   query=job.get("query", ""), moment_key=key,
                                   moment={"start": round(at, 1), "fresh_from": donor.identity,
                                           "clean": clean, "cuts": cuts},
                                   relevance_score=(donor.relevance_score * 0.95 if donor.relevance_score is not None else None),
                                   review_required=True,
                                   review_reason=f"Another moment of a video used for {job.get('subject') or 'this subject'}")
                ok, why = _asset_ok(asset)
                if not ok:
                    continue
                if slop_reason(path, donor.attribution):
                    continue                        # AI-made, a still, a studio... (src/slop.py)
                local = _local_check(path, job.get("intent", "")) if job.get("intent") else None
                if local is not None and local["reject"]:
                    continue
                asset.judged_by = "local" if local is not None else "none"
                if vision.enabled() and job.get("intent"):
                    # A hook line's moment gets the opening check on what its scene shows (src/hookcheck.py).
                    hook_span = float(job.get("seconds") or need) if job.get("hook") and \
                        getattr(config, "HOOK_CUT_CHECK", False) else None
                    verdict = vision.judge(path, job.get("intent", ""), job.get("query", ""),
                                           **({"span": hook_span} if hook_span else {}))
                    if verdict is not None and (float(verdict.get("score") or 0) < config.VISION_SOFT_MIN_SCORE
                                                or verdict.get("ai_generated") or verdict.get("studio")
                                                or verdict.get("opening") is False
                                                or off_story(verdict, f"{job.get('intent', '')} "
                                                                      f"{job.get('context', '')}")):
                        continue
                    if verdict is not None:
                        asset.relevance_score = float(verdict.get("score") or 0)
                        asset.content_description = str(verdict.get("description") or "")[:300]
                        asset.cut_check = vision.cut_record(dict(verdict, accepted=vision.acceptable(
                            verdict, allow_vice=True)))     # off-story music / smoking was turned down above
                        asset.judged_by = "opening" if asset.cut_check else "frames"
                return asset
            unreserve(vid, scene_at)
        return None

    filled = 0
    with ThreadPoolExecutor(max_workers=min(6, len(empties))) as pool:
        for i, got in zip(empties, pool.map(one, empties)):
            if got is not None:
                results[i] = got
                filled += 1
    return filled


def rescue_fill(jobs: List[Dict[str, Any]], results: List[Optional[MediaAsset]], work_dir: str,
                youtube_only: bool = False, footage_only=()) -> Dict[str, int]:
    """
    The last pass over scenes still empty after sourcing, before any shot is
    repeated (handler._fill_missing_media borrows one). In order: another
    moment of a same-subject video already on the timeline (fresh_moments),
    the best-titled YouTube result no scene uses, then a web picture. No
    vision call - it is the step that failed - so the title has to name what
    the line is about (_title_fits), and everything found here is flagged for
    review. Parallel, time boxed by RESCUE_SECONDS past any sourcing
    deadline. Fills `results` in place; returns how many per step.

    `footage_only`: scene indices that get no picture - the opening, whose
    stills and generated images the job's variety pass cleared for a footage
    retry (the owner, 2026-09-30). A line of a story about now (job recency
    "month") searches the last month's uploads before any upload.
    """
    footage_only = set(footage_only or ())
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
            targets = [f"ytsearch8:{q}"]
            recency = str(job.get("recency") or "")
            if config.RECENT_FOOTAGE_FIRST and recency in _RECENT_SP:
                targets.insert(0, _search_target(q, False, recency))
            # One ranked list per search, the last month's first: an older
            # upload is only tried after every recent one that fits.
            cands, seen_ids = [], set()
            for target in targets:
                try:
                    found = _yt_candidates(target, False, limit=8, timeout=40)
                except Exception:  # noqa: BLE001
                    found = []
                found = [c for c in found if c.get("id") not in seen_ids
                         and float(c.get("duration") or 0) >= need + 8
                         and not _talking_head(c.get("title") or "", f"{intent_text} {job.get('context') or ''}")
                         and _usable_title(c.get("title") or "", c.get("channel") or "", float(c.get("aspect") or 0),
                                           f"{intent_text} {job.get('context') or ''}")
                         and not title_conflict(c.get("title") or "", job.get("context") or "")
                         and _title_fits(c.get("title") or "", intent_text)]
                seen_ids.update(c.get("id") for c in found)
                found.sort(key=lambda c: -_score_candidate(c.get("title") or "", float(c.get("duration") or 0),
                                                           float(c.get("aspect") or 0), need))
                cands += found
            for c in cands[:4]:
                if time.time() > until - 15:
                    return None
                if not claim(c["id"], used):
                    continue
                dur = float(c.get("duration") or 0)
                point = max(5.0, dur * 0.35)
                if ledger.moment_used(c["id"], point, point + need):
                    continue                        # shown in an earlier video
                path, clean, cuts = fetch_clean_clip(c["id"], work_dir, point, need, c.get("title") or "")
                if not path:
                    continue
                if _filters.has_burned_captions(path) or motion_rejects(path) or slop_reason(path, c.get("title") or ""):
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
                asset.judged_by = "local" if config.LOCAL_VISION_ENABLED and _localvision.available() else "none"
                asset.review_required = True
                asset.review_reason = "Found in the last pass without an AI check - make sure it fits the line"
                if job.get("hook"):
                    # The opening never takes a clip nothing looked at (the owner's Glen Canyon test,
                    # 2026-10-05): the judge's opening check on this very cut, or the next result.
                    from . import hookcheck
                    keep, verdict = hookcheck.judge(path, dict(job, intent=intent_text),
                                                    float(job.get("seconds") or need))
                    if keep is False:
                        print(f"[rescue] hook line {job['index'] + 1}: {c['id']} turned down by the opening "
                              f"check ({hookcheck.why(verdict)})", flush=True)
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        continue
                    if verdict:
                        asset.apply_verdict(verdict, intent_text)
                        asset.review_reason = "Found in the last pass; the opening check passed it - check it fits"
                return asset
            return None

        # The style's photo cap (PHOTO_MAX_PER_10MIN) over the whole video:
        # a picture only while there is room, else the scene becomes an
        # animation or a reused shot.
        cap = photo_cap(_jobs_seconds(jobs))
        room = [None if cap is None else cap - sum(
            1 for r in results if r is not None and r.kind == "image" and r.source != "generated")]

        def picture(job: dict, q: str, intent_text: str) -> Optional[MediaAsset]:
            with lock:
                if room[0] is not None and room[0] <= 0:
                    return None
            for cand in _cached_search(search_web_images, q)[:5]:
                if time.time() > until - 10:
                    return None
                if ledger.photo_used(cand.url):
                    continue                        # shown in an earlier video
                if _stockblock.blocked(cand, "rescue"):
                    continue                        # a stock agency's preview (src/stockblock.py)
                if _is_bad(cand.identity):
                    continue                        # another scene found this picture unusable
                if not claim(cand.identity, used_images):
                    continue
                from . import slop
                if slop.ai_host(cand.url, getattr(cand, "page_url", "") or "") or slop.metadata_reason(cand.attribution):
                    continue
                got = _download(_dc_replace(cand), q, work_dir)
                fine, why = _asset_ok_for(job, got) if got else (True, "")
                if not fine:
                    _mark_bad(cand.identity, "", why)     # too blurry for any line (src/sharpness.py)...
                    got = None
                # No vision judge here, so the picture's own pixels are read for an
                # agency's credit bar (free, first) and stamp (the slow one, last,
                # once everything else has passed).
                mark = watermark_reason(got.local_path, "rescue", stamp=False) if got else ""
                if got and (mark or not _rescue_local_ok(got.local_path, intent_text)
                            or _photo_seen_before(got.local_path)
                            or slop_reason(got.local_path, _image_label(got), source_url=got.url)):
                    got = None
                if got:
                    mark = watermark_reason(got.local_path, "rescue", bar=False)
                    if mark:
                        got = None
                if mark:
                    _mark_bad(cand.identity, "", mark)  # every other scene skips it
                if got:
                    with lock:
                        if room[0] is not None:
                            if room[0] <= 0:
                                return None
                            room[0] -= 1
                    got.intent = intent_text
                    got.judged_by = "local" if config.LOCAL_VISION_ENABLED and _localvision.available() else "none"
                    got.review_required = True
                    got.review_reason = "Picture found in the last pass without an AI check - make sure it fits"
                    return got
            return None

        # What the judged search below never takes: every asset on the timeline and every YouTube video it
        # shows ("yt:<id>": youtube_clip skips a candidate by its video, never by one moment's identity).
        taken = {r.identity for r in results if r is not None} | {f"yt:{v}" for v in used}

        def judged(job: dict, q: str) -> Optional[MediaAsset]:
            """
            The clip-first search, judged, with the wider rungs (source_for_segment clips_only), for a line
            nothing filled - a line about a person too (the judge sees the face and the title; a picture
            nobody judged never stands in for a person). Each line in its own share of the pass.
            """
            if not getattr(config, "CLIPS_FIRST", False) or youtube_only:
                return None
            with _CACHE_LOCK:
                done = _searched_key(q, job.get("subject") or "") in _CLIP_SEARCHED
            if done:
                return None                     # its whole clip search already ran (not cut short): not again
            # Its share of the pass: every line gets a turn (RESCUE_PARALLEL at a time) and its unjudged steps
            # below keep ~30% of it - at 120 s a line, the 54th of 54 lines never started.
            lanes = max(1, min(int(config.RESCUE_PARALLEL or 1), len(todo)))
            per = min(float(getattr(config, "RESCUE_SCENE_SECONDS", 120) or 120),
                      0.7 * float(config.RESCUE_SECONDS) * lanes / max(1, len(todo)))
            own = min(until - 20.0, time.time() + per)
            if own <= time.time() + 5:
                return None
            box = _ytdlp.Box(own)
            stop = _ytdlp.STOP.set((box, own))
            try:
                with lock:
                    # (and every video the unjudged search below took since `taken` was made)
                    exclude = set(taken) | {f"yt:{v}" for v in used}
                got = source_for_segment(
                    q, float(job.get("seconds") or 0), work_dir, visual_type=job.get("visual_type") or "footage",
                    used=exclude, fallbacks=job.get("fallbacks"), intent=job.get("intent") or "",
                    context=job.get("context") or "", subject_type=job.get("subject_type") or "",
                    subject=job.get("subject") or "", event_window=job.get("event_window") or "",
                    scene_intent=job.get("scene_intent"), clips_only=True, **_scene_flags(job))
            except Exception as e:  # noqa: BLE001 - the unjudged steps below
                print(f"[rescue] line {job['index'] + 1}: clip search failed: {type(e).__name__}: {str(e)[:80]}",
                      flush=True)
                got = None
            finally:
                box.end()
                _ytdlp.STOP.reset(stop)
            if got is None:
                return None
            vid = _yt_origin(got)[0] if got.source == "youtube" else ""
            with lock:
                # One video once: another line's judged or unjudged search may have taken it meanwhile.
                if got.identity in taken or (vid and (vid in used or f"yt:{vid}" in taken)):
                    clash = True
                else:
                    clash = False
                    taken.add(got.identity)
                    if vid:
                        taken.add(f"yt:{vid}")
                        used.add(vid)           # the unjudged search below never takes its video again
            if clash:
                if got.local_path and os.path.exists(got.local_path):
                    try:
                        os.remove(got.local_path)
                    except OSError:
                        pass
                return None
            got.review_required = True
            got.review_reason = "Found in the last pass (judged) - check it fits the line"
            return got

        def one(i: int) -> Optional[MediaAsset]:
            job = by_index[i]
            q = " ".join(str(job.get("query") or job.get("subject") or "").split())
            if not q or time.time() > until - 20:
                return None
            intent_text = job.get("intent") or q
            need = max(2.5, min(12.0, float(job.get("seconds") or 5.0)))
            token = _SCENE_INTENT.set(job.get("scene_intent") or None)
            try:
                got = judged(job, q) if (job.get("subject_type") != "document" or i in footage_only) else None
                if got is not None:
                    return got
                if job.get("subject_type") == "person":
                    return None    # an unjudged search: a searched face can be the wrong person
                if job.get("visual_type", "footage") != "image" or i in footage_only:
                    got = footage(job, q, intent_text, need)
                if got is None and not youtube_only and i not in footage_only and config.ALLOW_WEB_IMAGES:
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

    Reuse is for FOOTAGE (the owner's Texas flood video, 2026-09-30: 28
    photo scenes showed 15 photos, 7 generated scenes 4 images): a photo is
    never shown more than IMAGE_MAX_USES times (once by default) and a
    generated image never twice, so neither is a donor. Where the lines'
    starts are known a reused clip never plays within REUSE_MIN_GAP_SECONDS
    of a scene cut from the same video, and a donor whose video could take
    the scene under the variety rules (may_place) is preferred. A line that
    names its own place never borrows another place's shot.
    """
    by_index = {j["index"]: j for j in jobs}
    order = sorted(by_index)
    starts = scene_starts(jobs)
    uses: Dict[str, int] = {}
    for r in results:
        if r is not None:
            uses[r.identity] = uses.get(r.identity, 0) + 1
    placed = placements(results, starts)

    def spent(k: int) -> bool:
        a = results[k]
        if a.source == "generated":
            return True
        limit = config.IMAGE_MAX_USES if a.kind == "image" else max_uses
        return limit is not None and uses.get(a.identity, 0) >= limit

    def too_close(k: int, i: int) -> bool:
        a = results[k]
        return a.kind == "video" and _near_twin(placed.get(video_key(a), []), starts.get(i))

    def fits(k: int, i: int) -> bool:
        a = results[k]
        return a.kind != "video" or may_place(placed.get(video_key(a), []), starts.get(i))

    def elsewhere(k: int, i: int) -> bool:
        mine, theirs = by_index[i].get("place") or "", by_index[k].get("place") or ""
        return bool(mine and theirs and not same_subject(mine, theirs))

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
        # Nearest donors first, those the variety rules allow here before the
        # rest; a donor is any scene that has media it may still lend.
        donors = sorted((k for k in order if k != i and results[k] is not None and not spent(k)
                         and not too_close(k, i) and not elsewhere(k, i)),
                        key=lambda k: (not fits(k, i), abs(k - i)))
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
            pick = max(same, key=lambda k: abs(k - i)) if same else None   # farthest of them
        if pick is None:
            continue
        donor = results[pick]
        uses[donor.identity] = uses.get(donor.identity, 0) + 1
        if donor.kind == "video":
            placed.setdefault(video_key(donor), []).append(starts.get(i))
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
                if _usable_title(c["title"], c.get("channel", ""), c["aspect"], f"{intent} {context}")
                and not (c["duration"] and c["duration"] < window + 10)
                and f"yt:{c['id']}" not in used]
    shots: List[dict] = []
    videos = 0
    for cand, start, _moment in _plan_grabs(eligible, window, 30.0, intent, context):
        if len(shots) >= need or videos >= SEQ_MAX_VIDEOS:
            break
        if ledger.moment_used(cand["id"], start, start + window):
            continue                                # shown in an earlier video
        path = _yt_fetch_retry(cand["id"], out_dir, start, window, cand["title"])
        if not path:
            continue
        if has_burned_captions(path):
            continue
        soft = clip_detail_reason(path, cand["title"])           # an upscaled upload (src/sharpness.py)
        if soft:
            _mark_bad(f"yt:{cand['id']}", "", soft)
            continue
        keep, verdict = _vision_gate(path, intent, context, cand["title"])
        if not keep:
            continue
        videos += 1
        cut = split_window(path, f"{tag}_{cand['id']}", lengths[:per], out_dir)
        # The shots are the window's own frames: its measure stands for them (no second read).
        _sharpness.same_detail(path, [p for p, _o in cut])
        for n, (shot_path, offset) in enumerate(cut):
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
    searches = (search_wikimedia, search_web_images) + ((search_openverse,) if openverse_on() else ())
    for q in queries:
        for search in searches:
            found += _cached_search(search, q)
    shots, seen = [], set()
    for cand in found:
        if len(shots) >= need:
            break
        if cand.identity in seen or cand.identity in used or ledger.photo_used(cand.url):
            continue
        seen.add(cand.identity)
        got = _download(_dc_replace(cand), cand.query or subject, out_dir)
        if not got or _photo_seen_before(got.local_path):
            continue
        blur = picture_blur_reason(got.local_path)                # src/sharpness.py
        if blur:
            _mark_bad(cand.identity, "", blur)
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
