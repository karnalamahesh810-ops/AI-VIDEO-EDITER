"""
Every picture a look shows is ours, checked, before the timeline is saved
(the owner, 2026-10-05: "Some images in the overlay animations ... are not
showing - not loading while the video plays. Figure out a way to replace them").

His Las Vegas video had three: a person card hot-linking iid.com (403 with an
HTML page to anything but a browser on their site) and two person cards whose
"link" was a file path on the pod that planned them (/tmp/work/pod-.../...jpg),
never uploaded. Scene pictures were all fine: they go through publish_media.

So, for every image an overlay names (overlay.media[].url):
  * a file on this machine, a link elsewhere on the web, or one of ours that no
    longer answers is fetched and checked: it decodes as a picture, is big
    enough (MIN_SIDE), and is not an error page;
  * a good one is re-hosted under the project's own R2 folder (a public link
    that never expires, like the scene media) - `put(bytes, key, type)`;
  * a bad one is swapped for the next candidate (the entry's own source page
    picture, the overlay's other pictures, the scene picture at that moment),
    or the look becomes its text-only kt- variant, or it is left out - never a
    broken picture in a look.

`fix(overlays, ...)` does it for a timeline; `fetch` and `put` are passed in so
the tests (and a dry run) touch no network and no bucket.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

MIN_SIDE = 240              # a picture smaller than this on its short side is not shown full-size in a look
MAX_BYTES = 25_000_000
FETCH_TIMEOUT = 25
_HTML = re.compile(rb"^\s*(?:<!doctype|<html|<\?xml|<head|<body|\{)", re.I)

Fetch = Callable[[str], Tuple[bytes, str]]          # url or path -> (bytes, content type)
TRANSIENT = "transient: "


def transient(e: Exception) -> bool:
    """A timeout, a dropped connection, a busy server (429 / 5xx): the picture may be fine."""
    name = type(e).__name__
    if name in ("Timeout", "ReadTimeout", "ConnectTimeout", "ConnectionError", "ReadTimeoutError",
                "ChunkedEncodingError", "TimeoutError", "ProtocolError"):
        return True
    resp = getattr(e, "response", None)
    code = getattr(resp, "status_code", None)
    return isinstance(code, int) and (code == 429 or code >= 500)
Put = Callable[[bytes, str, str], str]             # (bytes, key, content type) -> public url


def default_fetch(url: str) -> Tuple[bytes, str]:
    """GET a link (as a browser would ask) or read a local file. Raises on any failure."""
    if os.path.isfile(url):
        with open(url, "rb") as fh:
            return fh.read(MAX_BYTES + 1), ""
    if not re.match(r"^https?://", url or "", re.I):
        raise ValueError("not a link and not a file on this machine")
    import requests
    from . import config
    host = urllib.parse.urlparse(url).netloc
    r = requests.get(url, timeout=FETCH_TIMEOUT, stream=True, headers={
        "User-Agent": getattr(config, "BROWSER_USER_AGENT", "") or
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8", "Referer": f"https://{host}/"})
    r.raise_for_status()
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    return data, str(r.headers.get("content-type") or "")


def check(data: bytes, ctype: str = "") -> Tuple[bool, str, Tuple[int, int]]:
    """(ok, why not, (w, h)): the bytes are a real picture, big enough, not an error page."""
    if not data:
        return False, "empty", (0, 0)
    if len(data) > MAX_BYTES:
        return False, "too big", (0, 0)
    if "html" in (ctype or "").lower() or _HTML.match(data[:64]):
        return False, "an error page, not a picture", (0, 0)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            im.verify()
    except Exception as e:  # noqa: BLE001 - anything that does not decode is not a picture
        return False, f"does not decode ({type(e).__name__})", (0, 0)
    if min(w, h) < MIN_SIDE:
        return False, f"too small ({w}x{h})", (w, h)
    return True, "", (w, h)


def _ext(data: bytes) -> Tuple[str, str]:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif", "image/gif"
    return ".jpg", "image/jpeg"


def ours(url: str, project_id: str, public_base: str = "") -> bool:
    """A link into this project's own R2 folder."""
    if not url or not project_id:
        return False
    if public_base and url.startswith(public_base.rstrip("/") + "/"):
        return f"/projects/{project_id}/" in url
    return bool(re.match(r"^https://[^/]+\.r2\.dev/projects/" + re.escape(project_id) + r"/", url))


def image_entries(ov: dict) -> List[dict]:
    """The picture entries a look shows (overlay.media[] of type image, or with no type and an image link)."""
    out = []
    for m in ov.get("media") or []:
        if not isinstance(m, dict) or not m.get("url"):
            continue
        typ = str(m.get("type") or "").lower()
        if typ in ("image", "photo", "") and typ != "video":
            out.append(m)
    return out


def _text_variant(ov: dict) -> Optional[dict]:
    """The look without its picture: a person card becomes a lower third, anything else its key words."""
    from .datalooks import KT_KEYWORD, KT_LOWER_THIRD, variant_of
    text = re.sub(r"\s+", " ", str(ov.get("text") or "")).strip()
    if not text:
        return None
    keep = {k: v for k, v in ov.items() if k in ("startFrame", "durationInFrames", "style", "theme", "sfx",
                                                  "soundGain", "motion", "exit")}
    tid = str(ov.get("template") or "")
    if tid.startswith(("LIB_PF_", "PERSON_")) or ov.get("type") in ("name-card",):
        sub = str(ov.get("subtitle") or "")
        return {**keep, "type": "motion", "template": KT_LOWER_THIRD, "variant": variant_of(KT_LOWER_THIRD),
                "text": text[:60], "label": sub[:60], "subtitle": sub[:80]}
    if len(text) > 60:
        return None
    return {**keep, "type": "motion", "template": KT_KEYWORD, "variant": variant_of(KT_KEYWORD), "text": text,
            "label": ""}


def fix(overlays: List[dict], *, project_id: str = "", scenes: Optional[List[dict]] = None, fps: int = 30,
        fetch: Optional[Fetch] = None, put: Optional[Put] = None, public_base: str = "",
        verify_ours: bool = True) -> Dict[str, Any]:
    """
    Check every overlay picture, re-host the good ones, replace or drop the bad ones. In place.
    `put` None = a dry run: what would be re-hosted is reported, the links stay as they are.
    Returns {checked, ok, rehosted, replaced, textOnly, dropped, rows: [...]}.
    """
    fetch = fetch or default_fetch
    rows: List[dict] = []
    counts = {"checked": 0, "ok": 0, "rehosted": 0, "wouldRehost": 0, "replaced": 0, "textOnly": 0, "dropped": 0,
              "unchecked": 0}
    cache: Dict[str, Tuple[bool, str, bytes]] = {}

    def good(url: str) -> Tuple[bool, str, bytes]:
        if url in cache:
            return cache[url]
        why = ""
        for attempt in range(2):
            try:
                data, ctype = fetch(url)
                ok, why, _wh = check(data, ctype)
                break
            except Exception as e:  # noqa: BLE001
                data, ok, why = b"", False, f"{type(e).__name__}: {str(e)[:80]}"
                if not transient(e):
                    break
                why = TRANSIENT + why          # a slow or busy server: never a reason to replace a picture
        cache[url] = (ok, why, data if ok else b"")
        return cache[url]

    def scene_picture(ov: dict) -> List[str]:
        """The scene pictures on screen around the look (the runner-up for a lost picture)."""
        out = []
        if not scenes:
            return out
        at = int(ov.get("startFrame") or 0)
        near = sorted(scenes, key=lambda s: abs(int(s.get("startFrame") or 0) - at))[:3]
        for s in near:
            md = s.get("media") or {}
            if str(md.get("type") or "") == "image" and md.get("url"):
                out.append(md["url"])
            elif md.get("thumbnail"):
                out.append(md["thumbnail"])
        return out

    keep: List[dict] = []
    for ov in overlays:
        if not isinstance(ov, dict):
            continue
        entries = image_entries(ov)
        if not entries:
            keep.append(ov)
            continue
        alive = True
        for m in entries:
            url = str(m.get("url") or "")
            counts["checked"] += 1
            row = {"template": ov.get("template"), "at": round(int(ov.get("startFrame") or 0) / max(1, fps), 2),
                   "url": url[-90:]}
            mine = ours(url, project_id, public_base)
            if mine and not verify_ours:
                counts["ok"] += 1
                continue
            ok, why, data = good(url)
            if ok and mine:
                counts["ok"] += 1
                continue
            if not ok and why.startswith(TRANSIENT):
                counts["unchecked"] += 1
                rows.append({**row, "action": "kept (could not be checked now)", "why": why[len(TRANSIENT):]})
                continue
            if ok:
                if put is None:
                    counts["wouldRehost"] += 1
                    rows.append({**row, "action": "would re-host on R2"})
                else:
                    ext, ctype = _ext(data)
                    key = f"projects/{project_id or 'adhoc'}/overlay/{hashlib.sha1(data).hexdigest()[:16]}{ext}"
                    m["url"] = put(data, key, ctype)
                    m.pop("storage", None)
                    counts["rehosted"] += 1
                    rows.append({**row, "action": "re-hosted", "to": m["url"][-60:]})
                continue
            # the picture is lost: the next candidate
            cands = []
            src = str(m.get("sourceUrl") or "")
            if src and src != url and re.match(r"^https?://", src):
                cands.append(src)
            cands += [str(x.get("url")) for x in image_entries(ov) if x is not m and x.get("url")]
            # a scene picture stands in for a place or a thing - never for a person's portrait
            if not (str(ov.get("template") or "").startswith(("LIB_PF_", "PERSON_")) or ov.get("type") == "name-card"):
                cands += [u for u in scene_picture(ov) if u]
            got = None
            for c in cands:
                cok, _cwhy, cdata = good(c)
                if cok:
                    got = (c, cdata)
                    break
            if got is not None:
                c, cdata = got
                if put is not None and not ours(c, project_id, public_base):
                    ext, ctype = _ext(cdata)
                    key = f"projects/{project_id or 'adhoc'}/overlay/{hashlib.sha1(cdata).hexdigest()[:16]}{ext}"
                    c = put(cdata, key, ctype)
                m["url"] = c
                m.pop("storage", None)
                counts["replaced"] += 1
                rows.append({**row, "action": "replaced", "why": why, "with": c[-90:]})
                continue
            alive = False
            rows.append({**row, "action": "lost", "why": why})
            break
        if alive:
            keep.append(ov)
            continue
        alt = _text_variant(ov)
        if alt is not None:
            counts["textOnly"] += 1
            rows[-1]["action"] = f"no picture: became {alt['template']}"
            keep.append(alt)
        else:
            counts["dropped"] += 1
            rows[-1]["action"] = "no picture: left out"
    overlays[:] = keep
    return {**counts, "rows": rows}
