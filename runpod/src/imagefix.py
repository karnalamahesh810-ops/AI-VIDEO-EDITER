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
import urllib.parse
import uuid
from typing import Optional

import requests

from . import config
from .storage import StorageError, download

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


def fetch(url: str, dest: str, page_url: str = "") -> str:
    """
    Download a picture to `dest` and normalize it. Raises StorageError when
    every way of asking failed.

    Order: the identifying agent first (Wikimedia's terms require it), then a
    browser's headers with a Referer (hotlink blocks), then the picture the
    page stands for when the URL was a web page, then curl_cffi's Chrome
    fingerprint.
    """
    if os.path.isfile(url):
        with _dest_lock(url):
            return normalize(url)
    with _dest_lock(dest):
        if os.path.isfile(dest) and sniff(dest) in ("jpeg", "png"):
            return normalize(dest)          # a parallel scene already fetched this picture
        with _slot(url):
            got = _fetch_raw(url, dest, page_url)
        # A file that arrived but is not a photo (an SVG logo, a corrupt file) is
        # final: asking again returns the same bytes.
        return normalize(got)


def _fetch_raw(url: str, dest: str, page_url: str) -> str:
    errors = []
    try:
        return download(url, dest, timeout=60)
    except StorageError as e:
        errors.append(str(e))
        # The host never answered: other headers or a Chrome TLS fingerprint
        # cannot help, and each retry would hold a sourcing thread another
        # minute. (A TLS or refused connection still goes on to curl_cffi.)
        if isinstance(e.__cause__, requests.Timeout):
            raise StorageError("picture download failed: " + str(e)[:400]) from e
    try:
        return download(url, dest, timeout=60, headers=_browser_headers(url, page_url))
    except StorageError as e:
        errors.append(str(e))
    if any("HTML" in e for e in errors):
        og = _og_image(url, page_url)
        if og and og != url:
            try:
                return download(og, dest, timeout=60, headers=_browser_headers(og, url))
            except StorageError as e:
                errors.append(str(e))
    try:
        return _curl_cffi_get(url, dest, page_url)
    except Exception as e:  # noqa: BLE001 - curl_cffi missing or refused too
        errors.append(str(e)[:120])
    raise StorageError("picture download failed: " + " | ".join(errors)[:400])


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
