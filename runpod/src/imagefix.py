"""
Pictures that actually arrive, and arrive as clean JPEG/PNG files.

Web pictures failed in three ways the render never recovered from:

* the host refused the download - a 403 hotlink block for anything that is not
  a browser (news sites, CDNs), a 429 rate limit (Wikimedia under parallel
  scenes), or an HTML page where the picture was expected;
* the file was not what its name said - every picture was saved as ".jpg",
  but a third of web pictures are WebP, AVIF, HEIC, GIF or CMYK JPEG, which
  ffmpeg and the frame filters mis-read or cannot open;
* phone photos stored sideways with an EXIF rotation flag.

fetch() retries a refused download the way a browser would ask for it, and
normalize() rewrites whatever arrived as an upright RGB JPEG (PNG when it has
real transparency), capped at 3840 px.
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.parse
import uuid
from typing import Optional

import requests

from . import config
from .storage import STOPPED, StorageError, download

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MAX_SIDE = 3840

# Parallel scenes used to hit one host with dozens of requests at once and get
# 429s back; a few at a time per host is faster overall.
_HOST_LIMIT = {"upload.wikimedia.org": 4, "commons.wikimedia.org": 4}
_HOST_SLOTS: dict = {}
_HOST_LOCK = threading.Lock()
# Parallel scenes can pick the same picture, and media._download names the
# file after its URL: one download + normalize per destination at a time, or
# one thread truncates or re-downloads raw bytes over the other's JPEG.
_DEST_LOCKS: dict = {}

try:  # HEIC/HEIF (iPhone photos) when the plugin is installed
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001 - optional
    pass


def _slot(url: str) -> threading.BoundedSemaphore:
    host = urllib.parse.urlparse(url).netloc.lower()
    with _HOST_LOCK:
        sem = _HOST_SLOTS.get(host)
        if sem is None:
            sem = _HOST_SLOTS[host] = threading.BoundedSemaphore(_HOST_LIMIT.get(host, 8))
        return sem


# A site that refused a picture (403, an HTML page instead of the image) or
# never answered, HOST_FAILS_MAX times within HOST_FAILS_SECONDS, is not asked
# again in that time: the Mount Rainier video (2026-10-02) lost 166 picture
# downloads, one news site timing out three tries at a time, a dozen times,
# while its scenes ran out of time - 97 scenes then had no picture at all.
# Wikimedia only rate-limits (its slots above), so it is never skipped.
HOST_FAILS_MAX = 2
HOST_FAILS_SECONDS = 1800.0
_HOST_FAILS: dict = {}           # host -> (failures, time of the last one)
_NEVER_SKIPPED = set(_HOST_LIMIT)


def _host(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.lower()


def host_refused(url: str) -> bool:
    """True when this picture's site refused or ignored enough downloads lately that asking again only wastes a
    scene's time."""
    host = _host(url)
    if not host or host in _NEVER_SKIPPED:
        return False
    with _HOST_LOCK:
        n, last = _HOST_FAILS.get(host, (0, 0.0))
    return n >= HOST_FAILS_MAX and time.time() - last < HOST_FAILS_SECONDS


def _note_refusal(url: str, why: str = "") -> None:
    host = _host(url)
    if not host or host in _NEVER_SKIPPED:
        return
    if re.search(r"\b(404|410)\b", why or ""):
        return                     # that one picture is gone, not the site refusing
    if re.search(r"\b429\b", why or ""):
        # A rate limit, not a refusal: a busy shared host (Flickr's live.staticflickr.com answered
        # 429 twice on 2026-10-04 and seven good pictures on it were then skipped for 30 minutes).
        return
    if STOPPED in (why or ""):
        return                     # the asking scene's time ran out, not the site's fault
    with _HOST_LOCK:
        n, last = _HOST_FAILS.get(host, (0, 0.0))
        if time.time() - last >= HOST_FAILS_SECONDS:
            n = 0
        _HOST_FAILS[host] = (n + 1, time.time())


def _dest_lock(path: str) -> threading.Lock:
    key = os.path.abspath(path)
    with _HOST_LOCK:
        lock = _DEST_LOCKS.get(key)
        if lock is None:
            if len(_DEST_LOCKS) > 4096:         # a long-lived worker: drop idle ones
                for k in [k for k, v in _DEST_LOCKS.items() if not v.locked()]:
                    del _DEST_LOCKS[k]
            lock = _DEST_LOCKS[key] = threading.Lock()
        return lock


def _browser_headers(url: str, page_url: str = "") -> dict:
    parts = urllib.parse.urlparse(page_url or url)
    return {"User-Agent": BROWSER_UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{parts.scheme}://{parts.netloc}/" if parts.netloc else ""}


def _og_image(url: str, page_url: str = "") -> str:
    """The picture a web page stands for (og:image / twitter:image), or ""."""
    import requests
    try:
        r = requests.get(url, timeout=20, headers=_browser_headers(url, page_url))
        if "text/html" not in (r.headers.get("Content-Type") or "").lower():
            return ""
        html = r.text[:400_000]
    except Exception:  # noqa: BLE001
        return ""
    for prop in ("og:image:secure_url", "og:image", "twitter:image"):
        m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']+)' % re.escape(prop),
                      html, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(prop),
                      html, re.I)
        if m:
            return urllib.parse.urljoin(url, m.group(1).replace("&amp;", "&"))
    return ""


def _curl_cffi_get(url: str, dest: str, page_url: str = "") -> str:
    """Last try: a real Chrome TLS fingerprint (curl_cffi), for CDNs that
    block any non-browser handshake."""
    from curl_cffi import requests as creq  # type: ignore
    r = creq.get(url, impersonate="chrome", timeout=30, headers=_browser_headers(url, page_url))
    if r.status_code >= 400:
        raise StorageError(f"download failed: HTTP {r.status_code}")
    if "text/html" in (r.headers.get("Content-Type") or "").lower() or not r.content:
        raise StorageError("download returned an HTML error page")
    tmp = f"{dest}.{uuid.uuid4().hex}.cffi.part"
    try:
        with open(tmp, "wb") as fh:
            fh.write(r.content)
        os.replace(tmp, dest)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest


def fetch(url: str, dest: str, page_url: str = "", thumbnail: str = "", *, allow_agency: bool = False) -> str:
    """
    Download a picture to `dest` and normalize it. Raises StorageError when
    every way of asking failed.

    Order: the identifying agent first (Wikimedia's terms require it), then a
    browser's headers with a Referer (hotlink blocks), then the picture the
    page stands for when the URL was a web page, then curl_cffi's Chrome
    fingerprint.

    `allow_agency`: a picture a timeline already shows, fetched again to put
    it back (src/restore.py) - the stock-agency block is for new choices.
    """
    if os.path.isfile(url):
        with _dest_lock(url):
            _note_provenance(url)
            return normalize(url)
    # A stock agency's picture is never fetched as a new choice, whoever asks (src/stockblock.py).
    from . import stockblock
    why = "" if allow_agency else stockblock.reason(url, page_url, thumbnail)
    if why:
        stockblock.note(why, "fetch", key=url)
        raise StorageError(f"picture not fetched: {why}")
    with _dest_lock(dest):
        if os.path.isfile(dest) and sniff(dest) in ("jpeg", "png"):
            return normalize(dest)          # a parallel scene already fetched this picture
        if host_refused(url):
            raise StorageError("picture download failed: its site refused or ignored the last downloads; "
                               "not asked again for now")
        with _slot(url):
            try:
                got = _fetch_raw(url, dest, page_url, allow_agency=allow_agency)
            except StorageError as e:
                _note_refusal(url, str(e))
                # The search engine's own copy of the picture (Google's / DuckDuckGo's
                # thumbnail, ~300-800 px): small, but a real photo of the right thing
                # beats a held-over shot or an empty scene. It is upscaled later like
                # any small still (src/upscale.py).
                if thumbnail and thumbnail != url and STOPPED not in str(e):
                    try:
                        got = download(thumbnail, dest, timeout=30, headers=_browser_headers(thumbnail))
                    except StorageError:
                        raise e
                else:
                    raise
        # Content credentials ("generated by AI") live in the raw bytes, which
        # normalize may rewrite as a clean JPEG without them (src/slop.py).
        _note_provenance(got)
        # A file that arrived but is not a photo (an SVG logo, a corrupt file) is
        # final: asking again returns the same bytes.
        return normalize(got)


def _note_provenance(path: str) -> None:
    try:
        from . import slop
        slop.note_download(path)
    except Exception:  # noqa: BLE001 - a scan error never loses a picture
        pass


def _stopped() -> bool:
    """The asking scene's time is up (src/ytdlp.py's stop and deadline): no new try is made and a
    transfer in flight ends, as at a scene's next search or clip download."""
    try:
        from . import ytdlp
        return ytdlp.stopped()
    except Exception:  # noqa: BLE001 - no stop known
        return False


def _get(url: str, dest: str, headers: Optional[dict] = None, proxy: str = "", timeout: int = 20) -> str:
    """One try of a picture: a short wait for the connection, the whole transfer bounded
    (PICTURE_CONNECT_SECONDS, PICTURE_FETCH_SECONDS) and the asking scene's stop heard."""
    kw = {"proxy": proxy} if proxy else {}
    return download(url, dest, timeout=timeout, attempts=1, headers=headers,
                    connect_timeout=float(getattr(config, "PICTURE_CONNECT_SECONDS", 20.0) or 20.0),
                    max_seconds=float(getattr(config, "PICTURE_FETCH_SECONDS", 0.0) or 0.0), stop=_stopped, **kw)


def _no_connection(e: Exception) -> bool:
    """The host never took the connection: no request was sent, so other headers or a Chrome TLS
    fingerprint cannot change the answer - only another route can."""
    return isinstance(getattr(e, "__cause__", None), requests.exceptions.ConnectTimeout)


def _gone(e: Exception) -> bool:
    """The host answered that the picture is not there (404 / 410)."""
    resp = getattr(getattr(e, "__cause__", None), "response", None)
    return getattr(resp, "status_code", None) in (404, 410)


def _fetch_raw(url: str, dest: str, page_url: str, allow_agency: bool = False) -> str:
    """
    The tries for one picture, each only while it can still help (measured
    off RunPod 2026-10-04 on Yellowstone searches): a host that never took the
    connection goes straight to the residential route (the browser and Chrome
    tries cost 20 s each and cannot change a refused connection); a picture
    both the plain and the browser ask found gone (404/410) is final - no
    fingerprint or route brings it back (each such link cost two more tries,
    one of them through the residential route). A refusal (403, an HTML page,
    a rate limit) and a slow answer still get every try. No new try once the
    asking scene's time is up.
    """
    errors = []
    try:
        return _get(url, dest)
    except StorageError as e:
        errors.append(str(e))
        first = e
    if _no_connection(first):
        return _by_route(url, dest, page_url, errors)
    if STOPPED in str(first):
        raise StorageError("picture download failed: " + " | ".join(errors)[:400])
    try:
        return _get(url, dest, headers=_browser_headers(url, page_url))
    except StorageError as e:
        errors.append(str(e))
        second = e
    if (_gone(first) and _gone(second)) or _stopped():
        raise StorageError("picture download failed: " + " | ".join(errors)[:400])
    if any("HTML" in e for e in errors):
        og = _og_image(url, page_url)
        from . import stockblock
        if og and og != url and not allow_agency and stockblock.reason(og):
            stockblock.note(stockblock.reason(og), "fetch", key=og)
            og = ""                     # the page stands for an agency's preview
        if og and og != url:
            try:
                return _get(og, dest, headers=_browser_headers(og, url))
            except StorageError as e:
                errors.append(str(e))
    try:
        return _curl_cffi_get(url, dest, page_url)
    except Exception as e:  # noqa: BLE001 - curl_cffi missing or refused too
        errors.append(str(e)[:120])
    return _by_route(url, dest, page_url, errors)


def _by_route(url: str, dest: str, page_url: str, errors: list) -> str:
    """The host refused or ignored a datacenter address (403, an HTML challenge
    page, no answer): once more through a residential route (IMAGE_PROXIES), as
    a browser at home would arrive. Raises with every try's error otherwise."""
    proxy = _residential_route() if not _stopped() else ""
    if proxy:
        try:
            return _get(url, dest, headers=_browser_headers(url, page_url), proxy=proxy, timeout=25)
        except StorageError as e:
            errors.append("via proxy: " + str(e)[:100])
    raise StorageError("picture download failed: " + " | ".join(errors)[:400])


_ROUTE_TURN = [0]


def _residential_route() -> str:
    """The next picture route (config.IMAGE_PROXIES, round robin), or "" without any."""
    pool = config.IMAGE_PROXIES
    if not pool:
        return ""
    with _HOST_LOCK:
        p = pool[_ROUTE_TURN[0] % len(pool)]
        _ROUTE_TURN[0] += 1
    return p


def sniff(path: str) -> str:
    """The real format from the file's first bytes: jpeg, png, webp, gif,
    avif, heic, bmp, tiff, svg, html or ""."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return ""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return "heic"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    low = head.lower().lstrip()
    if low.startswith(b"<svg") or (low.startswith(b"<?xml") and b"svg" in low):
        return "svg"
    if low.startswith(b"<!doctype") or low.startswith(b"<html"):
        return "html"
    return ""


def normalize(path: str) -> str:
    """
    Rewrite the picture at `path` in place as an upright RGB JPEG (or PNG when
    it has real transparency), at most MAX_SIDE px. Returns the path. Raises
    StorageError for files that are not pictures (HTML, SVG logos, corrupt).
    """
    kind = sniff(path)
    if kind in ("html", "svg"):
        raise StorageError(f"not a photo ({kind})")
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover
        return path
    # A unique name: parallel scenes may normalize the same file, and a
    # shared temp would be truncated under the other's encoder.
    tmp = f"{path}.{uuid.uuid4().hex}.norm.part"
    try:
        with Image.open(path) as im:
            im.seek(0)                                # first frame of a GIF/animated WebP
            fmt = (im.format or "").upper()
            exif_rotated = False
            try:
                exif_rotated = bool(im.getexif().get(0x0112, 1) not in (0, 1))
            except Exception:  # noqa: BLE001
                pass
            needs = (fmt not in ("JPEG", "PNG") or im.mode not in ("RGB", "L", "RGBA")
                     or exif_rotated or max(im.size) > MAX_SIDE)
            if not needs:
                return path
            im = ImageOps.exif_transpose(im)
            alpha = im.mode in ("RGBA", "LA", "P") and _has_transparency(im)
            if max(im.size) > MAX_SIDE:
                s = MAX_SIDE / max(im.size)
                im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
            if alpha:
                im.convert("RGBA").save(tmp, "PNG", optimize=False)
            else:
                im.convert("RGB").save(tmp, "JPEG", quality=93, subsampling=0, optimize=True)
        os.replace(tmp, path)
        return path
    except StorageError:
        raise
    except Exception as e:  # noqa: BLE001 - an unreadable picture is not a picture
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise StorageError(f"unreadable picture ({kind or 'unknown'}): {type(e).__name__}") from e


def _has_transparency(im) -> bool:
    try:
        if im.mode == "P":
            return "transparency" in im.info
        alpha = im.getchannel("A")
        lo, _ = alpha.getextrema()
        return lo < 250
    except Exception:  # noqa: BLE001
        return False


def dims(path: str) -> Optional[tuple]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None
