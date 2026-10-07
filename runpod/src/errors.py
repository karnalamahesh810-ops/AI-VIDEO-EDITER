"""
Typed failure classes and the retry policy that goes with each.

A download that fails is not one thing. A timeout wants another try on
another route; a removed video wants no retry at all; an IP YouTube has
flagged wants the route benched, not the video; a dropped stream wants one
more try. Before this every failure came back as '' and the caller retried
three times regardless, which burned proxies on unavailable videos and gave
up on transient ones.
"""
import re
from enum import Enum
from typing import Dict, Optional


class FailureClass(str, Enum):
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    ACCESS_DENIED = "ACCESS_DENIED"
    # YouTube's own "Sign in to confirm you're not a bot" (or its captcha, or "not
    # available on this app"): the ADDRESS is flagged, never the video. Measured
    # 2026-10-03..07: 39 of 46 videos refused this way came down on another route.
    BOT_CHECK = "BOT_CHECK"
    MEDIA_UNAVAILABLE = "MEDIA_UNAVAILABLE"
    # "Not made available in your country": another country's route may get it.
    GEO_BLOCKED = "GEO_BLOCKED"
    # The video's stream itself answered 403 after its formats were read (ffmpeg
    # "Server returned 403 Forbidden" on googlevideo): 218 of 368 failed YouTube
    # downloads 2026-10-03..07, spread evenly over every route, and 183 of the 197
    # videos it hit came down on a later try. Neither the video's fault nor the route's.
    STREAM_REFUSED = "STREAM_REFUSED"
    PROXY_FAILURE = "PROXY_FAILURE"
    INVALID_MEDIA = "INVALID_MEDIA"
    FFMPEG_FAILURE = "FFMPEG_FAILURE"
    AI_API_FAILURE = "AI_API_FAILURE"
    UNKNOWN = "UNKNOWN"


# retries: further attempts after the first; backoff: seconds, multiplied by
# the attempt number; switch: try another proxy; proxy_fault: counts against
# the proxy's health.
RETRY: Dict[FailureClass, dict] = {
    FailureClass.NETWORK_TIMEOUT: {"retries": 2, "backoff": 2.0, "switch": True, "proxy_fault": True},
    FailureClass.PROVIDER_UNAVAILABLE: {"retries": 0, "backoff": 0.0, "switch": False, "proxy_fault": False},
    FailureClass.RATE_LIMITED: {"retries": 1, "backoff": 5.0, "switch": True, "proxy_fault": True},
    FailureClass.ACCESS_DENIED: {"retries": 2, "backoff": 0.0, "switch": True, "proxy_fault": True},
    FailureClass.BOT_CHECK: {"retries": 2, "backoff": 0.0, "switch": True, "proxy_fault": True},
    FailureClass.MEDIA_UNAVAILABLE: {"retries": 0, "backoff": 0.0, "switch": False, "proxy_fault": False},
    FailureClass.GEO_BLOCKED: {"retries": 1, "backoff": 0.0, "switch": True, "proxy_fault": False},
    FailureClass.STREAM_REFUSED: {"retries": 2, "backoff": 0.0, "switch": True, "proxy_fault": False},
    FailureClass.PROXY_FAILURE: {"retries": 2, "backoff": 1.0, "switch": True, "proxy_fault": True},
    FailureClass.INVALID_MEDIA: {"retries": 1, "backoff": 0.0, "switch": True, "proxy_fault": True},
    FailureClass.FFMPEG_FAILURE: {"retries": 1, "backoff": 0.0, "switch": False, "proxy_fault": False},
    FailureClass.AI_API_FAILURE: {"retries": 1, "backoff": 3.0, "switch": False, "proxy_fault": False},
    FailureClass.UNKNOWN: {"retries": 1, "backoff": 1.0, "switch": True, "proxy_fault": False},
}

# First match wins, so the order matters: a rate-limited session and a geo lock
# read like "this video is not available" too, and the video's own refusals
# ("Private video. Sign in if you've been granted access") carry sign-in words.
_RULES = [
    (FailureClass.RATE_LIMITED, ("http error 429", "too many requests", "rate limit", "rate-limited by youtube",
                                 "this content isn't available, try again later")),
    (FailureClass.GEO_BLOCKED, (
        "not made this video available in your country", "not available from your location",
        "geo restriction", "geo-restrict", "blocked it in your country", "is not available in your country")),
    (FailureClass.BOT_CHECK, (
        "not a bot", "captcha", "content is not available on this app",
        "unable to download api page: http error 403")),
    (FailureClass.MEDIA_UNAVAILABLE, (
        "video unavailable", "private video", "has been removed", "this video is not available",
        "video is unavailable", "age-restricted", "age restricted", "sign in to confirm your age",
        "inappropriate for some users", "members-only", "members only", "join this channel",
        "channel's members", "requires payment", "music premium", "youtube premium members",
        "premieres in", "is a live event", "this live event", "live stream recording is not available",
        "no longer available", "does not exist", "video has been terminated",
        "account associated with this video has been terminated")),
    (FailureClass.STREAM_REFUSED, (
        "server returned 403 forbidden", "unable to download video data: http error 403",
        "server returned 4xx client error")),
    (FailureClass.ACCESS_DENIED, (
        "sign in to confirm", "please sign in", "this content isn't available",
        "http error 403", "requested format is not available", "login required",
        "only available for registered users")),
    (FailureClass.PROXY_FAILURE, (
        "unable to connect to proxy", "proxy", "tunnel connection failed", "connection reset",
        "connection refused", "remote end closed", "eof occurred", "ssl:", "sslerror",
        "read timed out", "timed out", "connection aborted", "network is unreachable",
        "temporary failure in name resolution", "http error 502", "http error 503", "http error 504")),
    (FailureClass.FFMPEG_FAILURE, ("ffmpeg exited", "postprocessing:", "ffmpeg not found", "merging")),
    (FailureClass.PROVIDER_UNAVAILABLE, ("no such file or directory: 'yt-dlp'", "unsupported url",
                                         "extractor", "internal server error", "http error 500")),
]


def classify_ytdlp(stderr: str = "", returncode: Optional[int] = None,
                   timed_out: bool = False, empty: bool = False,
                   missing: bool = False) -> FailureClass:
    """The class of one failed yt-dlp run, from what it printed."""
    if missing:
        return FailureClass.PROVIDER_UNAVAILABLE
    if timed_out:
        return FailureClass.NETWORK_TIMEOUT
    if empty:
        return FailureClass.INVALID_MEDIA
    low = (stderr or "").lower()
    for cls, signs in _RULES:
        if any(s in low for s in signs):
            # "Video unavailable" wins over the proxy words that often follow it.
            return cls
    if returncode == 0:
        return FailureClass.INVALID_MEDIA
    return FailureClass.UNKNOWN


_COOKIES_ADVICE = re.compile(r"\.?\s*(?:Use --cookies-from-browser or --cookies|This helps protect our community)\b.*$",
                             re.IGNORECASE | re.DOTALL)


def ytdlp_reason(stderr: str = "", limit: int = 160) -> str:
    """
    The words that say why a yt-dlp run failed: its last ERROR line without yt-dlp's
    cookies advice, links blanked; for "ffmpeg exited" the ffmpeg line before it.
    The tail of stderr used to be stored instead, which for a refusal is only the
    advice: all 48 sign-in failures of 2026-10-03..07 were saved as "...for how to
    manually pass cookies...", the reason itself cut off.
    """
    lines = [l.strip() for l in (stderr or "").splitlines() if l.strip()]
    errors = [l for l in lines if l.startswith("ERROR")]
    text = errors[-1] if errors else (lines[-1] if lines else "")
    if errors and "ffmpeg exited" in text.lower():
        before = [l for l in lines if not l.startswith(("ERROR", "WARNING"))]
        if before:
            text = f"{before[-1]} | {text}"
    text = _COOKIES_ADVICE.sub("", re.sub(r"https?://\S+", "[URL]", text)).strip()
    return text[:limit]


def classify_exception(exc: Exception, status: Optional[int] = None) -> FailureClass:
    """The class of a provider (HTTP API) failure."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    code = status
    if code is None:
        m = re.search(r"\b(4\d\d|5\d\d)\b", text)
        code = int(m.group(1)) if m else None
    if "timeout" in name or "timed out" in text:
        return FailureClass.NETWORK_TIMEOUT
    if code == 429:
        return FailureClass.RATE_LIMITED
    if code in (401, 403):
        return FailureClass.ACCESS_DENIED
    if code == 404:
        return FailureClass.MEDIA_UNAVAILABLE
    if code and code >= 500:
        return FailureClass.PROVIDER_UNAVAILABLE
    if "proxy" in text or "connection" in name or "connection" in text:
        return FailureClass.PROXY_FAILURE
    if "json" in name or "decode" in name or "value" in name:
        return FailureClass.INVALID_MEDIA
    return FailureClass.UNKNOWN


def from_reason(why: str) -> FailureClass:
    """The old free-text bench reasons, kept for callers that still pass them."""
    w = (why or "").lower()
    if "timed out" in w or "timeout" in w:
        return FailureClass.NETWORK_TIMEOUT
    if "bot" in w:
        return FailureClass.BOT_CHECK
    if "refused" in w:
        return FailureClass.ACCESS_DENIED
    if "empty" in w:
        return FailureClass.INVALID_MEDIA
    return FailureClass.UNKNOWN
