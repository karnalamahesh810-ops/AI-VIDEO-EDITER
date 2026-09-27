"""
The yt-dlp integration: one search, one metadata fetch and one section
download, each routed through the proxy manager and classified on failure,
plus the per-route probe and the PO-token server checks.

media.py re-exports every name, so callers and tests are unchanged;
higher-level orchestration (which candidate, which moment, retries by
class) stays in media.py.
"""
import contextvars
import json
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import requests

from . import config, costs, events, proxies
from .errors import FailureClass, classify_ytdlp, from_reason
from .filters import playable_video

_INFO_LOCK = threading.Lock()
_YT_INFO_CACHE: Dict[str, tuple] = {}


# The job epoch. A download that started in one job and finishes after the
# next began (a straggler left running past a time box) must not leave its
# file in a work directory that is being, or has been, deleted.
EPOCH = [0]


def reset() -> None:
    """Between jobs: forget unavailable videos, the metadata cache and the counters."""
    EPOCH[0] += 1
    with _INFO_LOCK:
        _YT_INFO_CACHE.clear()
    with _FAIL_LOCK:
        _UNAVAILABLE_VIDEOS.clear()
        _DENIED_ON.clear()
    PROXY_MANAGER.reset_stats()


# Round-robin over the configured proxies so one address does not take every
# download and get flagged — but skip any address that was just refused or
# timed out. Blind rotation meant every third request went to an IP YouTube
# had already started refusing, costing a failed search plus a retry each time.
_PROXIES = list(config.YTDLP_PROXIES)


# The proxy manager (src/proxies.py) owns health, latency and quarantine
# per route; the helpers below are the call sites' view of it.
PROXY_MANAGER = proxies.ProxyManager(config.YTDLP_PROXIES, direct=bool(config.YTDLP_DIRECT))


# Per job: videos found unavailable (never retried), and the routes each
# video was refused on - a second refusal on a different route means the
# video, not the route, is the problem.
_UNAVAILABLE_VIDEOS: set = set()


_DENIED_ON: Dict[str, set] = {}


_FAIL_LOCK = threading.Lock()


# The class of the last failed yt-dlp run in this thread, for the retry policy.
_LAST_FAILURE: contextvars.ContextVar = contextvars.ContextVar("last_failure", default=None)


# Bounds how many yt-dlp subprocesses run at once, across every scene and
# every scout, so sourcing does not send more simultaneous requests than
# there are proxy IPs to carry them. See config.NETWORK_CONCURRENCY.
_NET_SEM = threading.Semaphore(config.NETWORK_CONCURRENCY)


def _next_proxy() -> str:
    """The route the manager would give the next request (no claim)."""
    if not _PROXIES:
        return ""
    return PROXY_MANAGER.peek()


def _acquire_proxy(domain: str = "youtube.com") -> str:
    if not _PROXIES:
        return ""
    return PROXY_MANAGER.acquire(domain)


def _release_proxy(proxy: str, ok: bool, failure: Optional[FailureClass] = None,
                   started: Optional[float] = None, domain: str = "youtube.com") -> None:
    if not _PROXIES:
        return
    latency = (time.time() - started) * 1000.0 if started else None
    PROXY_MANAGER.release(proxy, ok, failure, latency, domain)


def _proxy_index(proxy: str) -> int:
    return PROXY_MANAGER.index_of(proxy)


def proxy_snapshot() -> List[dict]:
    """Health of every route, by index only (a proxy URL carries credentials)."""
    return PROXY_MANAGER.snapshot()


def _note_failure(video_id: str, cls: FailureClass, proxy: str) -> FailureClass:
    """
    Record a failed download; returns the class to act on. A video refused
    on two different routes is unavailable, whatever YouTube said, and the
    second route is not to blame.
    """
    _LAST_FAILURE.set((cls, proxy))
    if cls == FailureClass.MEDIA_UNAVAILABLE:
        with _FAIL_LOCK:
            _UNAVAILABLE_VIDEOS.add(video_id)
        return cls
    if cls == FailureClass.ACCESS_DENIED and video_id:
        with _FAIL_LOCK:
            routes = _DENIED_ON.setdefault(video_id, set())
            routes.add(proxy)
            if len(routes) >= 2:
                _UNAVAILABLE_VIDEOS.add(video_id)
                _LAST_FAILURE.set((FailureClass.MEDIA_UNAVAILABLE, proxy))
                return FailureClass.MEDIA_UNAVAILABLE
    return cls


def _video_unavailable(video_id: str) -> bool:
    with _FAIL_LOCK:
        return video_id in _UNAVAILABLE_VIDEOS


def pot_provider_alive() -> bool:
    """Is the YouTube PO-token server (scripts/start.sh) answering on this worker?"""
    try:
        return requests.get("http://127.0.0.1:4416/ping", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def pot_provider_log(lines: int = 8) -> List[str]:
    """The server's last log lines, for a health probe when it is not answering."""
    try:
        with open("/tmp/bgutil.log", encoding="utf-8", errors="replace") as fh:
            return [l.rstrip()[:200] for l in fh.readlines()[-lines:]]
    except OSError:
        return ["(no /tmp/bgutil.log - server never started)"]


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

    def guarded(route):
        with _NET_SEM:                  # the probe used to start one process per route at once
            return one(route)

    with ThreadPoolExecutor(max_workers=max(1, min(len(routes), config.NETWORK_CONCURRENCY))) as ex:
        return list(ex.map(guarded, routes))


def _bench_proxy(proxy: str, why: str = "") -> None:
    """A failure on a route, by the old free-text reason; the manager decides what it costs."""
    if not proxy:
        return
    cls = from_reason(why)
    PROXY_MANAGER.report(proxy, cls)
    r = PROXY_MANAGER.by_url.get(proxy)
    state = r.state if r else "?"
    # Never print the proxy URL: it carries credentials.
    print(f"[media] proxy #{_proxy_index(proxy)} {cls.value.lower()} ({why}); now {state}", flush=True)


def _yt_network_args(proxy: Optional[str] = None) -> List[str]:
    """Shared bounded network/runtime settings; never log credential values."""
    args = ["--ignore-config", "--js-runtimes", "node",
            "--socket-timeout", "20", "--retries", "2",
            "--extractor-retries", "2", "--fragment-retries", "2",
            "--concurrent-fragments", "1"]
    proxy = _next_proxy() if proxy is None else proxy
    if proxy:
        # yt-dlp hands section downloads to ffmpeg and passes the proxy only
        # as an environment variable, which ffmpeg ignores for https:// stream
        # URLs. The fetch then left the worker on its own (blocked) IP with a
        # link minted for the proxy's IP: a frameless 262-byte file, exit 0,
        # on every route. ffmpeg's -http_proxy option covers https.
        args += ["--proxy", proxy, "--downloader-args", f"ffmpeg_i:-http_proxy {proxy}"]
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


# YouTube's own "Upload date: This year" filter, for the results page.
_YT_THIS_YEAR = "EgIIBQ%3D%3D"


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
    proxy = _acquire_proxy()
    cmd += _yt_network_args(proxy)
    started = time.time()

    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        _release_proxy(proxy, False, FailureClass.NETWORK_TIMEOUT, started)
        print(f"[media] search timed out via proxy #{_proxy_index(proxy)}", flush=True)
        return []
    except FileNotFoundError:
        _release_proxy(proxy, False, FailureClass.PROVIDER_UNAVAILABLE, started)
        return []
    if looks_blocked(p.stderr):
        cls = classify_ytdlp(p.stderr, p.returncode)
        _release_proxy(proxy, False, cls, started)
        print(f"[media] YouTube rejected this search via proxy #{_proxy_index(proxy)} "
              f"({cls.value}); the route is {PROXY_MANAGER.by_url.get(proxy).state if proxy in PROXY_MANAGER.by_url else 'direct'}",
              flush=True)
        return []
    _release_proxy(proxy, p.returncode == 0, None if p.returncode == 0 else classify_ytdlp(p.stderr, p.returncode),
                   started)

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


def _yt_info(video_id: str, timeout: int = 60) -> tuple:
    """(full yt-dlp info dict, proxy used) for one video, or ({}, proxy).

    Needed for moment selection: the flat search results carry no formats, and
    the storyboard (`sb*`) formats are what map thumbnails to timestamps. This
    is a full extraction (opens the player, runs its JS challenge) - as slow
    as the per-result lookup the flat search above exists to avoid - so a
    popular subject that several scenes reach for the same candidate is
    cached rather than re-extracted every time.
    """
    with _INFO_LOCK:
        cached = _YT_INFO_CACHE.get(video_id)
    if cached is not None:
        return cached

    if _video_unavailable(video_id):
        return {}, ""
    proxy = _acquire_proxy()
    # The same network arguments as a download (runtime, retries, cookies,
    # the ffmpeg proxy): this call used to skip them and fail quietly, which
    # sent scouting back to the fixed grab point.
    cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}", "-J",
           "--no-warnings", "--ignore-config"] + _yt_network_args(proxy)
    started = time.time()
    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
        info = json.loads(p.stdout) if p.returncode == 0 and p.stdout else {}
    except subprocess.TimeoutExpired:
        _release_proxy(proxy, False, FailureClass.NETWORK_TIMEOUT, started)
        print(f"[media] metadata timed out ({video_id}) via proxy #{_proxy_index(proxy)}", flush=True)
        return {}, proxy
    except FileNotFoundError:
        _release_proxy(proxy, False, FailureClass.PROVIDER_UNAVAILABLE, started)
        return {}, proxy
    except ValueError:
        _release_proxy(proxy, False, FailureClass.INVALID_MEDIA, started)
        return {}, proxy
    if not info:
        cls = _note_failure(video_id, classify_ytdlp(p.stderr, p.returncode), proxy)
        _release_proxy(proxy, False, cls, started)
        print(f"[media] metadata failed ({video_id}, {cls.value}) via proxy #{_proxy_index(proxy)}", flush=True)
        return {}, proxy
    _release_proxy(proxy, True, None, started)
    if info:
        # A failed extraction is never cached - the next scout should retry
        # it, possibly through a different (unbenched) proxy.
        with _INFO_LOCK:
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
    if _video_unavailable(video_id):
        _LAST_FAILURE.set((FailureClass.MEDIA_UNAVAILABLE, ""))
        return ""
    proxy = _acquire_proxy()
    cmd += _yt_network_args(proxy)
    # After the shared network args: yt-dlp keeps the LAST value of a repeated
    # option, so placed before them these were silently overridden by "2".
    cmd += ["--retries", "5", "--fragment-retries", "5", "--extractor-retries", "3"]
    started = time.time()
    epoch = EPOCH[0]
    try:
        with _NET_SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        cls = _note_failure(video_id, FailureClass.NETWORK_TIMEOUT, proxy)
        _release_proxy(proxy, False, cls, started)
        print(f"[media] YouTube clip download timed out ({video_id}, {start_at:.1f}s) "
              f"via proxy #{_proxy_index(proxy)}", flush=True)
        return ""
    except FileNotFoundError:
        _note_failure(video_id, FailureClass.PROVIDER_UNAVAILABLE, proxy)
        _release_proxy(proxy, False, FailureClass.PROVIDER_UNAVAILABLE, started)
        print("[media] yt-dlp executable is missing; cannot download YouTube footage", flush=True)
        return ""
    if p.returncode != 0:
        cls = _note_failure(video_id, classify_ytdlp(p.stderr, p.returncode), proxy)
        _release_proxy(proxy, False, cls, started)
        reason = re.sub(r"https?://[^\s]+", "[URL]", (p.stderr or "").strip())
        print(f"[media] download failed ({video_id}, {cls.value}) via proxy #{_proxy_index(proxy)}: "
              f"{reason[-160:] or 'no diagnostic'}", flush=True)
        events.emit("source", "download_failed", level="warning", provider="youtube",
                    failure=cls.value, data={"video": video_id, "proxy": _proxy_index(proxy)},
                    message=reason[-120:])
        return ""
    found = ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line and os.path.exists(line):
            found = line
            break
    if not found:
        guess = os.path.join(out_dir, f"yt_{video_id}_{range_key}_{fetch_id}.mp4")
        found = guess if os.path.exists(guess) else ""
    if found and not playable_video(found):
        # yt-dlp exited 0 but the section has no frames: a 262-byte MP4 shell
        # (seen when a proxy dropped the stream mid-section). Uploaded as-is it
        # killed a whole render ("Is this a video file?"). Drop it so the
        # retry goes through another proxy.
        reason = re.sub(r"https?://[^\s]+", "[URL]", (p.stderr or "").strip())
        print(f"[media] empty download ({video_id} @{start_at:.0f}s, "
              f"{os.path.getsize(found)} bytes) via proxy #{_proxy_index(proxy)}: "
              f"{reason[-160:] or 'no diagnostic'}", flush=True)
        try:
            os.remove(found)
        except OSError:
            pass
        cls = _note_failure(video_id, FailureClass.INVALID_MEDIA, proxy)
        _release_proxy(proxy, False, cls, started)
        return ""
    if not found:
        cls = _note_failure(video_id, classify_ytdlp(p.stderr, p.returncode, empty=True), proxy)
        _release_proxy(proxy, False, cls, started)
        return ""
    _release_proxy(proxy, True, None, started)
    _LAST_FAILURE.set(None)
    if EPOCH[0] != epoch:
        # The job this download belonged to has ended; its directory is gone
        # or going. Nothing may be left behind for the next job.
        try:
            os.remove(found)
        except OSError:
            pass
        print(f"[media] straggler download from an earlier job discarded ({video_id})", flush=True)
        return ""
    try:
        costs.record("proxy.bytes", os.path.getsize(found))
    except OSError:
        pass
    events.emit("source", "download_ok", provider="youtube",
                data={"video": video_id, "seconds": round(seconds, 1), "proxy": _proxy_index(proxy)},
                duration_ms=(time.time() - started) * 1000.0)
    return found
