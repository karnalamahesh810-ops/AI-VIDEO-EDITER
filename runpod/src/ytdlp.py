"""
The yt-dlp integration: one search, one metadata fetch and one section
download, each routed through the proxy manager and classified on failure,
plus the per-route probe and the PO-token server checks.

media.py re-exports every name, so callers and tests are unchanged;
higher-level orchestration (which candidate, which moment, retries by
class) stays in media.py.
"""
import contextlib
import contextvars
import heapq
import itertools
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

# Vertical uploads (Shorts, phone video) when a style frames them on a blurred
# fill: `height<=1080` alone would take a 1080x1920 Short at 480x854. A
# landscape video matches none of these and falls through to the usual list.
_VERTICAL_FIRST = ("bv*[aspect_ratio<1.2][width<=1080][ext=mp4][protocol^=https]/"
                   "bv*[aspect_ratio<1.2][width<=1080]/")


def best_bitrate() -> List[str]:
    """
    yt-dlp's sort for a download (CLIP_SHARPNESS_CHECK, the owner 2026-10-04:
    "video clips also we needed to make quality"): the biggest picture up to
    1080 lines first, then yt-dlp's own order (the newest codec). Not the
    highest bitrate: that picks YouTube's H.264 stream, about twice the bytes of
    its AV1 / VP9 one for the same picture, and the proxies are paid per GB.
    Never above 1080p. [] with the check off.
    """
    return ["-S", "res:1080"] if getattr(config, "CLIP_SHARPNESS_CHECK", False) else []


_INFO_LOCK = threading.Lock()
_YT_INFO_CACHE: Dict[str, tuple] = {}


# The job epoch. A download that started in one job and finishes after the
# next began (a straggler left running past a time box) must not leave its
# file in a work directory that is being, or has been, deleted.
EPOCH = [0]

# The job's sourcing deadline (epoch seconds, 0 = none). Past it every
# download and metadata call returns empty at once, so every loop above them
# ends in seconds and the beats left fall through to animation scenes.
DEADLINE = [0.0]


def set_deadline(at: float) -> None:
    DEADLINE[0] = float(at or 0.0)


def past_deadline() -> bool:
    return bool(DEADLINE[0]) and time.time() > DEADLINE[0]


class Box:
    """
    One time-boxed pass's stop time (epoch seconds, 0 = open), shared by every
    scene the pass starts. end() closes it: each of them stops at its next
    search, metadata call or download instead of running on unseen.
    """

    def __init__(self, at: float = 0.0):
        self.at = float(at or 0.0)

    def shorten(self, at: float) -> None:
        self.at = min(self.at, at) if self.at else float(at)

    def end(self) -> None:
        self.shorten(time.time())

    def closed(self, now: Optional[float] = None) -> bool:
        # At or past: end() must close the box at once, and the clock may not
        # move between the two reads (Windows' clock ticks every ~15 ms).
        return bool(self.at) and (now or time.time()) >= self.at


# What the scene this thread works for may still spend: (its pass's Box or
# None, its own stop time or 0). Set by media.source_many; the threads a scene
# starts carry it (with_stop). Past either, the network calls below return
# empty at once. On the owner's Lake Powell pod (2026-10-01) pass 1 gave up on
# 81 scenes at its 1800 s box, but their threads ran on unseen: at the end of
# sourcing ~370 requests still sat in the proxies' queues behind 16 network
# slots, ahead of pass 2 and the rescue pass, whose results were kept.
STOP: contextvars.ContextVar = contextvars.ContextVar("stop", default=None)


def stopped() -> bool:
    """The job's sourcing deadline is past, or this scene's pass or own time is up."""
    if past_deadline():
        return True
    got = STOP.get()
    if not got:
        return False
    box, own = got
    now = time.time()
    return bool((box is not None and box.closed(now)) or (own and now >= own))


def with_stop(fn):
    """`fn` running under this thread's scene stop, for a pool thread the scene starts."""
    got = STOP.get()
    if got is None:
        return fn

    def run(*a, **kw):
        token = STOP.set(got)
        try:
            return fn(*a, **kw)
        finally:
            STOP.reset(token)
    return run


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


# What a yt-dlp call is, for the queue: the work nearest a finished scene first.
DOWNLOAD, METADATA, SEARCH = 0, 1, 2


class Slots:
    """
    At most `n` yt-dlp processes at once, across every scene and every scout
    (config.NETWORK_CONCURRENCY), so sourcing never sends more requests than
    the proxy IPs carry. A waiting download goes before a waiting metadata
    read, and both before a search: with 28 scenes searching at once, a scene
    that had found its clip queued its download behind the next scenes'
    searches (Lake Powell: downloads waited up to 218 s, 27.7 s on average).
    A waiter whose scene is stopped (`give_up`) leaves the queue.
    """

    def __init__(self, n: int):
        self.n = max(1, int(n))
        self.busy = 0
        self.cond = threading.Condition()
        self.queue: list = []
        self.seq = itertools.count()

    def acquire(self, priority: int = SEARCH, give_up=None) -> bool:
        with self.cond:
            ticket = (priority, next(self.seq))
            heapq.heappush(self.queue, ticket)
            try:
                while not (self.busy < self.n and self.queue[0] == ticket):
                    if give_up is not None and give_up():
                        self.queue.remove(ticket)
                        heapq.heapify(self.queue)
                        return False
                    self.cond.wait(timeout=1.0)
                heapq.heappop(self.queue)
                self.busy += 1
                return True
            finally:
                self.cond.notify_all()          # the next in line may fit as well

    def release(self) -> None:
        with self.cond:
            self.busy = max(0, self.busy - 1)
            self.cond.notify_all()

    def waiting(self) -> int:
        with self.cond:
            return len(self.queue)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


_NET_SEM = Slots(config.NETWORK_CONCURRENCY)


@contextlib.contextmanager
def _net_slot(priority: int = SEARCH):
    """One network slot for a yt-dlp call; yields False when the scene stopped while it waited."""
    sem = _NET_SEM
    if isinstance(sem, Slots):
        ok = sem.acquire(priority, give_up=stopped)
        try:
            yield ok
        finally:
            if ok:
                sem.release()
    else:                                       # a plain semaphore (tests)
        with sem:
            yield True


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


def probe_youtube(video_id: str = "ka2S39HhLsM", first_ok: bool = False) -> List[dict]:
    """
    Can this worker actually download from YouTube, directly and per proxy?

    Metadata for one known video (the step that gets refused - searches keep
    working from flagged IPs, which hid the block). Routes are reported by
    number only; a proxy URL carries credentials.

    `first_ok` (a fan-out part: the parent has just checked every route): the
    proxies first, a few at once, stopping at the first that works - each part
    used to ask YouTube once per route (14 player requests a part, 20 parts a
    video) before finding a single clip.
    """
    routes = [("direct", "")] + [(f"proxy#{i + 1}", p) for i, p in enumerate(config.YTDLP_PROXIES)]
    if first_ok:
        routes = routes[1:] + routes[:1]

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

    if first_ok:
        out: List[dict] = []
        step = max(1, min(3, config.NETWORK_CONCURRENCY))
        with ThreadPoolExecutor(max_workers=step) as ex:
            for n in range(0, len(routes), step):
                got = list(ex.map(guarded, routes[n:n + step]))
                out += got
                if any(r["ok"] for r in got):
                    break
        return out
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


def _yt_network_args(proxy: Optional[str] = None, hls_fix: bool = False) -> List[str]:
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
        # hls_fix: one HTTP connection per segment (see _HLS_REUSE).
        extra = "-http_persistent 0 " if hls_fix else ""
        args += ["--proxy", proxy, "--downloader-args", f"ffmpeg_i:-loglevel error {extra}-http_proxy {proxy}"]
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
    if stopped():
        return []
    with _net_slot(SEARCH) as ok:
        if not ok:
            return []
        # The route is claimed once a slot is free and timed from the start:
        # claimed while queueing, the Lake Powell pod's proxies showed 34-59
        # "active" requests each and the queue's wait (1.3-19 s) as latency.
        proxy = _acquire_proxy()
        cmd += _yt_network_args(proxy)
        started = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
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
    if cached is None and stopped():
        return {}, None
    if cached is not None:
        return cached

    if _video_unavailable(video_id):
        return {}, ""
    with _net_slot(METADATA) as ok:
        if not ok:
            return {}, None
        proxy = _acquire_proxy()
        # The same network arguments as a download (runtime, retries, cookies,
        # the ffmpeg proxy): this call used to skip them and fail quietly, which
        # sent scouting back to the fixed grab point.
        cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}", "-J",
               "--no-warnings", "--ignore-config"] + _yt_network_args(proxy)
        started = time.time()
        try:
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


# ffmpeg's HLS demuxer keeps one connection for all segments; through a proxy a
# segment on another googlevideo host fails with this, and yt-dlp still exits 0
# with a frameless file. Not the proxy's fault: fetch again without reuse.
_HLS_REUSE = "cannot reuse http connection for different host"


def _yt_fetch(video_id: str, out_dir: str, start_at: float, seconds: float,
              timeout: int = 300, hls_fix: bool = False) -> str:
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
        # Direct https formats first: HLS sections go through ffmpeg's HLS
        # demuxer and its connection reuse (see _HLS_REUSE).
        "-f", (_VERTICAL_FIRST if config.ALLOW_VERTICAL else "")
        + ("bv*[height<=1080][ext=mp4][protocol^=https]/bv*[height<=1080][ext=mp4]"
           "/bv*[height<=1080]/b[height<=1080]"),
        *best_bitrate(),
        "--no-playlist", "--no-warnings",
        "--merge-output-format", "mp4",
        "-o", out_tpl, "--print", "after_move:filepath",
    ]
    if _video_unavailable(video_id):
        _LAST_FAILURE.set((FailureClass.MEDIA_UNAVAILABLE, ""))
        return ""
    if stopped():
        # Not the video's fault: nothing is recorded, and no retry follows.
        _LAST_FAILURE.set((FailureClass.MEDIA_UNAVAILABLE, ""))
        return ""
    epoch = EPOCH[0]
    with _net_slot(DOWNLOAD) as ok:
        if not ok:
            _LAST_FAILURE.set((FailureClass.MEDIA_UNAVAILABLE, ""))
            return ""
        proxy = _acquire_proxy()
        cmd += _yt_network_args(proxy, hls_fix=hls_fix)
        # After the shared network args: yt-dlp keeps the LAST value of a repeated
        # option, so placed before them these were silently overridden by "2".
        cmd += ["--retries", "5", "--fragment-retries", "5", "--extractor-retries", "3"]
        started = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
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
        if _HLS_REUSE in reason.lower() and not hls_fix:
            try:
                os.remove(found)
            except OSError:
                pass
            _release_proxy(proxy, True, None, started)
            print(f"[media] HLS connection reuse failed ({video_id} @{start_at:.0f}s); "
                  "fetching again without reuse", flush=True)
            return _yt_fetch(video_id, out_dir, start_at, seconds, timeout, hls_fix=True)
        events.emit("source", "empty_download", level="warning", provider="youtube",
                    failure="INVALID_MEDIA", data={"video": video_id, "proxy": _proxy_index(proxy)},
                    message=reason[-160:])
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
