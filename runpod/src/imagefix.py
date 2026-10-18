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
from .storage import STOPPED, NotAPhoto, StorageError, download

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


_SVG_PATH = re.compile(r"\.svgz?$", re.I)
_SVG_QUERY = re.compile(r"(?:^|&)(?:format|fm|ext|type|mime)=(?:image%2Fsvg|image/svg|svg)", re.I)


def not_a_photo_url(url: str) -> str:
    """"svg" when the link itself says the picture is an SVG drawing (a logo, a map, an
    icon - never a photograph: 149 such downloads of 2026-10-12/13 ended "not a photo
    (svg)"), else "". A Wikimedia PNG rendering of an SVG ("...x.svg.png") is a PNG."""
    u = str(url or "").strip()
    if u[:5].lower() == "data:":
        return "svg" if u[5:18].lower().startswith("image/svg") else ""
    try:
        parts = urllib.parse.urlparse(u)
    except ValueError:
        return ""
    path = urllib.parse.unquote(parts.path or "")
    if _SVG_PATH.search(path) or _SVG_QUERY.search(parts.query or ""):
        return "svg"
    return ""


# Yandex's own picture host. A link to it names a size: a path ending in the size
# alias (/get-<namespace>/<group>/<name>/<alias>, "orig" the original) or, for its
# search thumbnails (/i?id=...), an n= parameter. Without a valid one it answers
# "400 Use thumbnail sizes like ..." (144 Yandex downloads of 2026-10-12/13).
_YANDEX_AVATARS = "avatars.mds.yandex.net"


def _yandex_host(url: str) -> bool:
    return _host(url) == _YANDEX_AVATARS or _host(url).endswith("." + _YANDEX_AVATARS)


def yandex_sized(url: str) -> str:
    """The link with a size Yandex's picture host accepts when it has none (a /get-... link
    without its alias gets "orig", an /i?id= link without n= gets n=13); any other link as is."""
    if not _yandex_host(url):
        return url
    parts = urllib.parse.urlparse(url)
    segs = [s for s in parts.path.split("/") if s]
    if segs and segs[0] == "i":
        q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        if "id" in q and not (q.get("n") or [""])[0]:
            q["n"] = ["13"]
            return urllib.parse.urlunparse(parts._replace(query=urllib.parse.urlencode(q, doseq=True)))
        return url
    if segs and segs[0].startswith("get-") and len(segs) == 3:
        return urllib.parse.urlunparse(parts._replace(path="/" + "/".join(segs + ["orig"])))
    return url


def yandex_size_variants(url: str) -> list:
    """Other sizes of a Yandex-hosted picture to ask after it answered 400 for its size:
    the original ("orig") for a /get-... link, n=13 for an /i?id= link. [] otherwise."""
    if not _yandex_host(url):
        return []
    parts = urllib.parse.urlparse(url)
    segs = [s for s in parts.path.split("/") if s]
    out = []
    if segs and segs[0] == "i":
        q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        if "id" in q and (q.get("n") or [""])[0] != "13":
            q["n"] = ["13"]
            out.append(urllib.parse.urlunparse(parts._replace(query=urllib.parse.urlencode(q, doseq=True))))
    elif segs and segs[0].startswith("get-") and len(segs) >= 3:
        base = segs[:3]
        if len(segs) == 3 or segs[3] != "orig":
            out.append(urllib.parse.urlunparse(parts._replace(path="/" + "/".join(base + ["orig"]), query="")))
    return [u for u in out if u != url]


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
_HOST_FAILS: dict = {}           # host (or a shared host's part) -> (failures, time of the last one)
_NEVER_SKIPPED = set(_HOST_LIMIT)

# Hosts that serve many unrelated sites' or people's pictures. A refusal there is
# about one site's part of the host - or one picture - never the whole host: two
# 403s for one WordPress site behind Jetpack's i0.wp.com used to skip every
# WordPress site's pictures for half an hour, two for one Pinterest pin every pin.
# The number is how many leading path segments name that part (the site behind
# i0.wp.com/<site>/..., a Squarespace site id, a Shopify store, a path-style S3
# bucket, a YouTube video's thumbnails); 0 = each picture is its own part.
_SHARED_HOSTS = {
    "i0.wp.com": 1, "i1.wp.com": 1, "i2.wp.com": 1, "i3.wp.com": 1,
    "images.squarespace-cdn.com": 3, "cdn.shopify.com": 4, "s3.amazonaws.com": 1, "i.ytimg.com": 2,
    "i.pinimg.com": 0, "live.staticflickr.com": 0, "pbs.twimg.com": 0, "i.redd.it": 0, "preview.redd.it": 0,
    "i.imgur.com": 0, "static.wixstatic.com": 0, "media.licdn.com": 0, "cdn.discordapp.com": 0,
}
# Families of such hosts by the end of their name: each picture its own part.
_SHARED_SUFFIXES = (".staticflickr.com", ".googleusercontent.com", ".bp.blogspot.com", ".wixmp.com",
                    ".fbcdn.net", ".cdninstagram.com", ".pinimg.com", ".twimg.com")
# A shared host as a whole is still skipped when its parts refused this often in
# HOST_FAILS_SECONDS: a CDN that refuses this worker's address everywhere.
SHARED_FAILS_MAX = 6


def _host(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.lower()


def _shared_depth(host: str) -> Optional[int]:
    """How many leading path segments name one site on a shared host (0: each picture),
    or None for an ordinary site."""
    if host in _SHARED_HOSTS:
        return _SHARED_HOSTS[host]
    return 0 if host.endswith(_SHARED_SUFFIXES) else None


def _refusal_keys(url: str) -> list:
    """[(key, limit)] a picture's refusals are counted under: its host - or, on a shared host,
    the part of it the picture belongs to (HOST_FAILS_MAX) and the whole host (SHARED_FAILS_MAX)."""
    parts = urllib.parse.urlparse(url or "")
    host = parts.netloc.lower()
    depth = _shared_depth(host)
    if depth is None:
        return [(host, HOST_FAILS_MAX)]
    segs = [s for s in parts.path.split("/") if s]
    part = host + "/" + "/".join(segs if depth == 0 else segs[:depth])
    return [(part, HOST_FAILS_MAX), (host, SHARED_FAILS_MAX)]


def host_refused(url: str) -> bool:
    """True when this picture's site (on a shared host: its part of it, or the whole host
    when every part refuses) refused or ignored enough downloads lately that asking again
    only wastes a scene's time."""
    host = _host(url)
    if not host or host in _NEVER_SKIPPED:
        return False
    now = time.time()
    with _HOST_LOCK:
        for key, limit in _refusal_keys(url):
            n, last = _HOST_FAILS.get(key, (0, 0.0))
            if n >= limit and now - last < HOST_FAILS_SECONDS:
                return True
    return False


def _note_refusal(url: str, why: str = "") -> None:
    host = _host(url)
    if not host or host in _NEVER_SKIPPED:
        return
    if re.search(r"\b(404|410)\b", why or ""):
        return                     # that one picture is gone, not the site refusing
    if _bad_request_final() and re.search(r"\b400\b", why or ""):
        return                     # that one link is malformed (a Yandex link without its size)
    if "not a photo" in (why or ""):
        return                     # a drawing where a photo was hoped for: the site answered fine
    if re.search(r"\b429\b", why or ""):
        # A rate limit, not a refusal: a busy shared host (Flickr's live.staticflickr.com answered
        # 429 twice on 2026-10-04 and seven good pictures on it were then skipped for 30 minutes).
        return
    if STOPPED in (why or ""):
        return                     # the asking scene's time ran out, not the site's fault
    now = time.time()
    with _HOST_LOCK:
        if len(_HOST_FAILS) > 5000:            # a long-lived worker: one key a refused picture
            for key in [k for k, (_n, t) in _HOST_FAILS.items() if now - t >= HOST_FAILS_SECONDS]:
                del _HOST_FAILS[key]
        for key, _limit in _refusal_keys(url):
            n, last = _HOST_FAILS.get(key, (0, 0.0))
            if now - last >= HOST_FAILS_SECONDS:
                n = 0
            _HOST_FAILS[key] = (n + 1, now)


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


def _bad_request_final() -> bool:
    return bool(getattr(config, "PICTURE_BAD_REQUEST_FINAL", True))


class _Refused(StorageError):
    """The picture's site is being skipped for now (host_refused): nothing was asked."""


def fetch(url: str, dest: str, page_url: str = "", thumbnail: str = "", *, allow_agency: bool = False,
          alternates=()) -> str:
    """
    Download a picture to `dest` and normalize it. Raises StorageError when
    every way of asking failed.

    Order: the identifying agent first (Wikimedia's terms require it), then a
    browser's headers with a Referer (hotlink blocks), then the picture the
    page stands for when the URL was a web page, then curl_cffi's Chrome
    fingerprint.

    `allow_agency`: a picture a timeline already shows, fetched again to put
    it back (src/restore.py) - the stock-agency block is for new choices.

    `alternates`: other links to the same picture the search gave (Yandex's
    duplicates on other sites), asked when the picture itself cannot be had
    (PICTURE_ALTERNATES) - before the search engine's small thumbnail.
    """
    if os.path.isfile(url):
        with _dest_lock(url):
            _note_provenance(url)
            return normalize(url)
    # A drawing (an SVG logo or map) is never a photo: not downloaded at all.
    if getattr(config, "PICTURE_SKIP_SVG", True) and not_a_photo_url(url):
        raise NotAPhoto(f"not a photo ({not_a_photo_url(url)}): not downloaded")
    # A stock agency's picture is never fetched as a new choice, whoever asks (src/stockblock.py).
    from . import stockblock
    why = "" if allow_agency else stockblock.reason(url, page_url, thumbnail)
    if why:
        stockblock.note(why, "fetch", key=url)
        raise StorageError(f"picture not fetched: {why}")
    if getattr(config, "YANDEX_RESULT_DETAILS", True):
        url = yandex_sized(url)
    with _dest_lock(dest):
        if os.path.isfile(dest) and sniff(dest) in ("jpeg", "png"):
            return normalize(dest)          # a parallel scene already fetched this picture
        try:
            if host_refused(url):
                raise _Refused("picture download failed: its site refused or ignored the last downloads; "
                               "not asked again for now")
            with _slot(url):
                try:
                    got = _fetch_raw(url, dest, page_url, allow_agency=allow_agency)
                except StorageError as e:
                    _note_refusal(url, str(e))
                    raise
        except StorageError as e:
            got = _from_alternates(url, e, alternates, dest, page_url, allow_agency)
            if not got:
                # The search engine's own copy of the picture (Google's / DuckDuckGo's
                # thumbnail, ~300-800 px): small, but a real photo of the right thing
                # beats a held-over shot or an empty scene. It is upscaled later like
                # any small still (src/upscale.py).
                if thumbnail and thumbnail != url and STOPPED not in str(e) \
                        and not isinstance(e, (_Refused, NotAPhoto)):
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


def _from_alternates(url: str, error: StorageError, alternates, dest: str, page_url: str,
                     allow_agency: bool) -> str:
    """
    The picture from another copy of it, after `url` failed with `error`, or "".

    Asked in order: a Yandex-hosted link that was refused for its size, at a size
    Yandex accepts; then the search's other copies of the same picture (Yandex's
    duplicates on other sites: the original's site had removed it - 216 Yandex
    pictures of 2026-10-12/13 were a 404). At most PICTURE_ALTERNATES_MAX copies,
    one plain and one browser ask each; never after the scene's stop, never for a
    drawing, never a stock agency's copy or a site being skipped.
    """
    if not getattr(config, "PICTURE_ALTERNATES", True):
        return ""
    if isinstance(error, NotAPhoto) or STOPPED in str(error) or _stopped():
        return ""
    tries = []
    if re.search(r"\b400\b", str(error)) or "thumbnail sizes" in str(error).lower():
        tries += yandex_size_variants(url)
    tries += [u for u in (alternates or []) if isinstance(u, str)]
    from . import stockblock
    seen, asked = {url}, 0
    limit = max(0, int(getattr(config, "PICTURE_ALTERNATES_MAX", 2) or 0))
    for alt in tries:
        if asked >= limit or _stopped():
            break
        alt = yandex_sized(alt.strip())
        if alt in seen or not alt.startswith("http") or not_a_photo_url(alt) or host_refused(alt):
            continue
        seen.add(alt)
        if not allow_agency and stockblock.reason(alt):
            stockblock.note(stockblock.reason(alt), "fetch", key=alt)
            continue
        asked += 1
        with _slot(alt):
            for headers in (None, _browser_headers(alt, page_url)):
                try:
                    return _get(alt, dest, headers=headers)
                except NotAPhoto:
                    break
                except StorageError as e:
                    _note_refusal(alt, str(e))
                    if _gone(e) or STOPPED in str(e):
                        break                # gone there too: the next copy
    return ""


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
    if getattr(config, "PICTURE_SKIP_SVG", True):
        kw["refuse_types"] = ("image/svg+xml",)       # ends at the headers: no drawing is downloaded
    return download(url, dest, timeout=timeout, attempts=1, headers=headers,
                    connect_timeout=float(getattr(config, "PICTURE_CONNECT_SECONDS", 20.0) or 20.0),
                    max_seconds=float(getattr(config, "PICTURE_FETCH_SECONDS", 0.0) or 0.0), stop=_stopped, **kw)


def _no_connection(e: Exception) -> bool:
    """The host never took the connection: no request was sent, so other headers or a Chrome TLS
    fingerprint cannot change the answer - only another route can."""
    return isinstance(getattr(e, "__cause__", None), requests.exceptions.ConnectTimeout)


def _status(e: Exception):
    """The HTTP status a failed try was answered with (None: no answer, or not an HTTP error)."""
    resp = getattr(getattr(e, "__cause__", None), "response", None)
    return getattr(resp, "status_code", None)


def _gone(e: Exception) -> bool:
    """The host answered that the picture is not there (404 / 410) - or, with
    PICTURE_BAD_REQUEST_FINAL, that the link itself is malformed (400)."""
    final = (400, 404, 410) if _bad_request_final() else (404, 410)
    return _status(e) in final


# What a residential try's failure says about the route rather than the picture:
# no answer through it (proxy error, connect/read timeout), the proxy's own
# refusal (407), an error page where the picture was (an HTML page, 422, a 5xx
# from the gateway), a transfer cut short. Another route can change those.
_ROUTE_SIDE_CODES = (407, 422, 500, 502, 503, 504, 520, 521, 522, 523, 524)


def _route_side(e: Exception) -> bool:
    if isinstance(e, NotAPhoto) or STOPPED in str(e):
        return False
    code = _status(e)
    if code is not None:
        return code in _ROUTE_SIDE_CODES
    cause = getattr(e, "__cause__", None)
    if isinstance(cause, (requests.exceptions.ProxyError, requests.exceptions.Timeout,
                          requests.exceptions.ConnectionError, requests.exceptions.SSLError,
                          requests.exceptions.ChunkedEncodingError)):
        return True
    text = str(e).lower()
    return any(s in text for s in ("html error page", "incomplete download", "empty file",
                                   "timed out", "proxy"))


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
    asking scene's time is up. A drawing (the answer said image/svg+xml) is
    final at once, and a 400 for both asks is final like a 404
    (PICTURE_BAD_REQUEST_FINAL: the link itself is malformed).
    """
    errors = []
    try:
        return _get(url, dest)
    except NotAPhoto:
        raise
    except StorageError as e:
        errors.append(str(e))
        first = e
    if _no_connection(first):
        return _by_route(url, dest, page_url, errors)
    if STOPPED in str(first):
        raise StorageError("picture download failed: " + " | ".join(errors)[:400])
    try:
        return _get(url, dest, headers=_browser_headers(url, page_url))
    except NotAPhoto:
        raise
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
    a browser at home would arrive. Raises with every try's error otherwise.

    A residential try that failed on the route itself (_route_side: no answer
    through it, the proxy's 407, an HTML page or a gateway's 422/5xx, a cut
    transfer) is made once more through a different route (PICTURE_SECOND_ROUTE);
    the origin's own 400/403/404/410/429 through a home address is final."""
    proxy = _residential_route() if not _stopped() else ""
    if proxy:
        try:
            return _get(url, dest, headers=_browser_headers(url, page_url), proxy=proxy, timeout=25)
        except NotAPhoto:
            raise
        except StorageError as e:
            errors.append("via proxy: " + str(e)[:100])
            again = _route_side(e) and getattr(config, "PICTURE_SECOND_ROUTE", True) and not _stopped()
        other = _other_route(proxy) if again else ""
        if other:
            try:
                return _get(url, dest, headers=_browser_headers(url, page_url), proxy=other, timeout=25)
            except NotAPhoto:
                raise
            except StorageError as e:
                errors.append("via another proxy: " + str(e)[:100])
    raise StorageError("picture download failed: " + " | ".join(errors)[:400])


def _other_route(used: str) -> str:
    """The next picture route that is not `used`, or "" when the pool has no other."""
    pool = config.IMAGE_PROXIES or []
    if len(set(pool) - {used}) == 0:
        return ""
    for _ in range(len(pool)):
        p = _residential_route()
        if p and p != used:
            return p
    return ""


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
