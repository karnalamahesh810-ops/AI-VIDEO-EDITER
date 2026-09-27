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
    MEDIA_UNAVAILABLE = "MEDIA_UNAVAILABLE"
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
    FailureClass.MEDIA_UNAVAILABLE: {"retries": 0, "backoff": 0.0, "switch": False, "proxy_fault": False},
    FailureClass.PROXY_FAILURE: {"retries": 2, "backoff": 1.0, "switch": True, "proxy_fault": True},
    FailureClass.INVALID_MEDIA: {"retries": 1, "backoff": 0.0, "switch": True, "proxy_fault": True},
    FailureClass.FFMPEG_FAILURE: {"retries": 1, "backoff": 0.0, "switch": False, "proxy_fault": False},
    FailureClass.AI_API_FAILURE: {"retries": 1, "backoff": 3.0, "switch": False, "proxy_fault": False},
    FailureClass.UNKNOWN: {"retries": 1, "backoff": 1.0, "switch": True, "proxy_fault": False},
}

_RULES = [
    (FailureClass.RATE_LIMITED, ("http error 429", "too many requests", "rate limit")),
    (FailureClass.MEDIA_UNAVAILABLE, (
        "video unavailable", "private video", "has been removed", "this video is not available",
        "video is unavailable", "is not available in your country", "age-restricted", "age restricted",
        "sign in to confirm your age", "members-only", "members only", "premieres in", "is a live event",
        "this live event", "no longer available", "does not exist", "video has been terminated",
        "account associated with this video has been terminated", "join this channel",
        "content is not available on this app")),
    (FailureClass.ACCESS_DENIED, (
        "sign in to confirm", "confirm you're not a bot", "confirm you are not a bot", "please sign in",
        "this content isn't available", "unable to download api page: http error 403",
        "http error 403", "requested format is not available", "login required", "captcha")),
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
    if "refused" in w or "bot" in w:
        return FailureClass.ACCESS_DENIED
    if "empty" in w:
        return FailureClass.INVALID_MEDIA
    return FailureClass.UNKNOWN
