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
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import requests

from . import config, moments, vision
from .storage import download


# Round-robin over the configured proxies so one address does not take every
# download and get flagged — but skip any address that was just refused or
# timed out. Blind rotation meant every third request went to an IP YouTube
# had already started refusing, costing a failed search plus a retry each time.
_PROXIES = list(config.YTDLP_PROXIES)
_PROXY_LOCK = threading.Lock()
_PROXY_POS = [0]
_PROXY_BENCHED: Dict[str, float] = {}
_PROXY_BENCH_SECONDS = 600


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
    vision_model: str = ""

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
        media = {
            "type": self.kind,
            "url": self.local_path or self.url,
            "source": self.source,
            "attribution": self.attribution,
            "license": self.license,
        }
        if self.relevance_score is not None:
            media["relevanceScore"] = round(self.relevance_score, 3)
        if self.content_description:
            media["contentDescription"] = self.content_description
        return media

    def apply_verdict(self, verdict: Optional[dict], intent: str) -> "MediaAsset":
        self.intent = intent or self.intent
        if verdict:
            self.content_description = verdict.get("description", "")
            self.relevance_score = verdict.get("score")
            self.vision_model = verdict.get("model", "")
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
                             it.get("link") or ""))
        except (requests.RequestException, ValueError):
            rows = []
    if not rows:
        try:
            from ddgs import DDGS  # keyless fallback
            with DDGS() as ddg:
                for it in ddg.images(query, max_results=limit * 2):
                    rows.append((it.get("image"), it.get("width") or 0,
                                 it.get("height") or 0, it.get("title") or "",
                                 it.get("url") or ""))
        except Exception:  # noqa: BLE001 — optional dependency / network
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


def _gray_frames(path: str, count: int = 4, w: int = 320, h: int = 180):
    """`count` evenly spaced frames as (h, w) uint8 arrays, [] if unreadable."""
    try:
        import numpy as np
    except ImportError:
        return []
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", f"fps={count}/max(1\\,{max(1, count)}),scale={w}:{h},format=gray",
         "-frames:v", str(count), "-f", "rawvideo", "-"],
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


def _vision_gate(path: str, intent: str, context: str, label: str) -> tuple:
    """
    (keep, verdict) for a downloaded candidate.

    No intent means nothing to judge against, and an unreachable model returns
    None — both keep the candidate, so vision can only ever remove bad clips,
    never empty a timeline because an API is down.
    """
    if not intent or not vision.enabled():
        return True, None
    verdict = vision.judge(path, intent, context)
    keep = vision.acceptable(verdict)
    if verdict is not None:
        mark = "keep" if keep else "REJECT"
        flags = []
        if verdict["has_text_or_watermark"]:
            flags.append("text/watermark")
        if verdict["is_talking_head"]:
            flags.append("talking head")
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
            "--print", "%(id)s\t%(duration)s\t%(url)s\t\t%(title)s",
        ]
    proxy = _next_proxy()
    cmd += _yt_network_args(proxy)

    try:
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
        })
    return out


def _yt_info(video_id: str, timeout: int = 60) -> tuple:
    """(full yt-dlp info dict, proxy used) for one video, or ({}, proxy).

    Needed for moment selection: the flat search results carry no formats, and
    the storyboard (`sb*`) formats are what map thumbnails to timestamps. The
    proxy is returned because the storyboard sheets are fetched separately and
    should leave from the same address.
    """
    proxy = _next_proxy()
    cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}", "-J",
           "--no-warnings", "--ignore-config", "--socket-timeout", "20"]
    if proxy:
        cmd += ["--proxy", proxy]
    if config.YTDLP_COOKIES_FILE and os.path.isfile(config.YTDLP_COOKIES_FILE):
        cmd += ["--cookies", config.YTDLP_COOKIES_FILE]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return (json.loads(p.stdout) if p.returncode == 0 and p.stdout else {}), proxy
    except subprocess.TimeoutExpired:
        _bench_proxy(proxy, "metadata timed out")
        return {}, proxy
    except (FileNotFoundError, ValueError):
        return {}, proxy


def _yt_fetch(video_id: str, out_dir: str, start_at: float, seconds: float,
              timeout: int = 300) -> str:
    """Download one section of one known video. Returns the local path or ''."""
    # Different ranges must not reuse a previous download of the same video.
    range_key = f"{round(start_at * 1000)}_{round(seconds * 1000)}"
    out_tpl = os.path.join(out_dir, f"yt_%(id)s_{range_key}.%(ext)s")
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
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        _bench_proxy(proxy, "download timed out")
        return ""
    except FileNotFoundError:
        return ""
    if looks_blocked(p.stderr):
        _bench_proxy(proxy, "download refused")
        return ""
    if p.returncode != 0:
        return ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line and os.path.exists(line):
            return line
    guess = os.path.join(out_dir, f"yt_{video_id}_{range_key}.mp4")
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
    """_yt_fetch with one retry on the next proxy; logs a failure instead of
    swallowing it. Under load a residential IP occasionally drops a download
    that succeeds seconds later from another address."""
    for attempt in (1, 2):
        path = _yt_fetch(video_id, out_dir, start_at, seconds)
        if path:
            return path
    print(f"[media] download failed twice, skipping: {title[:60] or video_id}",
          flush=True)
    return ""


def youtube_clip(query_or_url: str, out_dir: str, seconds: float = 6.0,
                 start_at: float = 30.0, require_cc: bool = True,
                 skip: int = 0, used: set = None,
                 b_roll_intent: bool = True, intent: str = "",
                 context: str = "") -> Optional[MediaAsset]:
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

    judged = 0
    for search in searches:
        if judged >= config.VISION_MAX_CANDIDATES:
            break
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
            if _TALKING_HEAD.search(candidate["title"] or ""):
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
    vision.reset()  # per-job call/failure counts for the job result


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
                       context: str = "") -> Optional[MediaAsset]:
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
                          allow_stock=allow_stock, require_cc=require_cc,
                          intent=intent or query, context=context)
        if got:
            return got
    return None


def _source_one(query: str, seconds: float, work_dir: str, *,
                visual_type: str = "footage", nth: int = 0,
                used: set = None, prompt: str = "",
                allow_youtube: bool = None, allow_stock: bool = None,
                require_cc: bool = None, intent: str = "",
                context: str = "") -> Optional[MediaAsset]:
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
                             skip=nth, start_at=30.0 + 25.0 * nth, used=used,
                             intent=intent, context=context)
        if asset:
            return asset

    # Free footage sources beyond YouTube. These carry clean licences, so
    # they are tried for motion before falling back to a Ken Burns still —
    # a real moving shot of the subject beats a panned photograph of it.
    if visual_type == "footage":
        for search in (search_nasa_video, search_wikimedia_video):
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
    if config.PREFER_GENERATED_IMAGES:
        tried_generation = True
        if _generation_budget_left():
            made = generate_image(prompt or query, work_dir)
            if made:
                return made

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

    # Last resort: an illustration for a beat nothing real covers. Always a
    # fresh generation, so it is never a duplicate.
    # The budget is always consulted. Writing this as
    # `if PREFER_GENERATED or budget_left()` short-circuits past the check
    # whenever the preference is on, which silently disabled the spend cap
    # entirely — caught by the cap test, not by reading it.
    if not tried_generation and _generation_budget_left():
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


def source_many(jobs: List[Dict[str, Any]], work_dir: str, *,
                workers: int = 6, on_done=None, on_review=None,
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
                intent=job.get("intent", ""), context=job.get("context", ""),
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

    # Pass 2: nothing may appear twice, and nothing unusable may stay.
    #
    # Both failures want the same repair - reach further down the same result
    # list - so they share one loop. A clip that is merely a repeat is better
    # than black; a clip covered in somebody else's subtitles is not, so an
    # unusable shot is dropped even when there is nothing to put in its place.
    # Classify first (no network): the first scene to claim a clip keeps it.
    used: set = set()
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
    deadline = time.time() + config.REPLACE_BUDGET_SECONDS
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
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(replace, *t): t for t in todo}
            for n, fut in enumerate(as_completed(futures), 1):
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

    if duplicates:
        print(f"[media] resolved {duplicates} duplicate shot(s)", flush=True)
    if rejected:
        print(f"[media] rejected {rejected} unusable clip(s)", flush=True)
    if todo:
        print(f"[media] second pass: {replaced[0]}/{len(todo)} scene(s) replaced "
              f"({empty} empty, {duplicates} repeats, {rejected} unusable)", flush=True)
    return results
