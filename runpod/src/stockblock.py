"""
Stock-agency and watermarked pictures: never on a timeline.

The owner (2026-10-04): "the images it is using are sometimes watermarked
images, like Getty ... Alamy ... fix that".

Measured on his Lake Mead video (project d784a461, 201 pictures): 20 came from
stock agencies - 11 Alamy comps with "alamy" stamped across the picture and a
black "Image ID ... www.alamy.com" bar under it, a Getty and an iStock preview
with their credit box, a Shutterstock editorial preview tiled with its name,
2 Dreamstime, a Freepik "premium photo", a Shutterstock video thumbnail and 2
Getty pictures on news sites. 17 of the 20 were placed with no AI check at all
("Picture found in the last pass without an AI check": 99 of the 201 pictures
were). The Powell video (15eb0bc3): 9 of 142 pictures. The picture search
returns them because the agencies' pages rank first for "Lake Mead drought",
and the vision judge looks at a still 384 px wide, where a faint stamp is
nearly invisible.

Two layers, both free:

1. names   - the picture's address, its page, the search engine's small copy
             of it, an agency's file name ("GettyImages-1325430438.jpg") and
             the words of its title ("... Stock Photo - Alamy", "Editorial
             use only"): reason(). Checked BEFORE any download, on every path
             a picture takes (media.search_web_images / search_yandex_images,
             media._download, imagefix.fetch and its og:image and thumbnail
             fallbacks, the rescue pass, the fallback ladder, the overlay
             photos, the clip library, the editor's choices).
2. pixels  - what a preview looks like when it arrives from somewhere else (a
             blog's or Pinterest's copy of an Alamy comp): the agency's credit
             bar along the bottom edge (credit_bar, free) and its name stamped
             over the picture, read by the local CLIP model on tiles of the
             picture at full size (stamp_share, ~0.7 s): watermark_reason().
             Every downloaded picture's bar is read before anything else; its
             stamp once it is about to be kept, whether or not the vision judge
             saw it (media._vision_gate, the rescue pass, overlay photos).

Measured 2026-10-04 (scratchpad wm_eval, measure_v2.py): 102 agency previews
with a visible mark and 267 clean pictures - the Lake Mead video's own (200),
Wikimedia photos, and a HELD-OUT set fetched after the prompts were chosen (55
Commons pictures, half of them manuscripts, newspapers and museum labels; 26
new agency previews):
  bar + stamp at 0.75   74 of 102 turned down (bar 36, stamp 38), 5 of 267
                        clean (1.9 %): an ocean wave, a river with a rainbow,
                        lightning, and a YouTube title card and a product shot
                        the judge turns down anyway. Held-out alone: 20 of 26,
                        2 of 55.
  the bar alone         36 of 102 (every Alamy, Bigstock and Shutterstock comp
                        and their search-engine thumbnails), 0 of 267.
  first prompts at 0.8  73 of 102, but 17 of 267 clean (6.4 %; 10 of the 55
                        held-out) - documents read as stamps.
  Missed (28): Adobe Stock's small credit up the left edge (9 of 11), faint
  diagonal tiles (Depositphotos 4 of 7, Science Photo Library 4 of 4), 4 of
  11 Getty boxes. Their own addresses are blocked by name; only a copy
  elsewhere relies on the pixels. An autocorrelation search for the repeated
  stamp did not separate the sets and is not used.
  Review (same day): on clean weather pictures the stamp read polished skies
  and seas as stock - 29 of 352 Commons pictures (half the lightning strikes,
  breaking waves, surf, storm surge, waterfalls); with plain prompts for the
  storm, sea and sky 10 of 352, the clean set above 2 of 267, the agency
  previews still 74 of 102 (PLAIN_PROMPTS). Every one of the Lake Mead
  video's 20 agency pictures came from an agency's own address or file name,
  which the names block before any download.

Counted for the job (stats(): doc.meta.sourcing.stockBlocked). Nothing here
raises: an unreadable file or a missing model is "no finding".
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from . import config

# --------------------------------------------------------------------------- #
# 1. Names: hosts, file names, title words
# --------------------------------------------------------------------------- #

# An agency's name as a whole host label (or the name plus "images", "photos"...),
# so every country site and CDN of it matches ("c8.alamy.com", "www.alamy.de",
# "alamyimages.fr", "media.gettyimages.com", "www.gettyimages.co.uk",
# "editorial01.shutterstock.com", "thumbs.dreamstime.com", "st2.depositphotos.com",
# "previews.123rf.com") and a site whose name merely starts or ends with it does
# not ("salamy.example", "natureplanet.org" is not Nature Picture Library).
_BRANDS: Dict[str, str] = {
    "alamy": "alamy", "gettyimages": "getty", "istockphoto": "istock", "shutterstock": "shutterstock",
    "dreamstime": "dreamstime", "depositphotos": "depositphotos", "123rf": "123rf",
    "agefotostock": "agefotostock", "pond5": "pond5", "bigstockphoto": "bigstock", "bigstock": "bigstock",
    "imago-images": "imago", "picfair": "picfair", "sciencephoto": "science photo library",
    "superstock": "superstock", "pixtastock": "pixta", "eyeem": "eyeem", "zumapress": "zuma press",
    "mediastorehouse": "media storehouse", "bridgemanimages": "bridgeman", "lookandlearn": "look and learn",
    "vecteezy": "vecteezy", "freepik": "freepik", "pngtree": "pngtree", "storyblocks": "storyblocks",
    "videoblocks": "storyblocks", "canstockphoto": "can stock photo", "stocksy": "stocksy",
    "masterfile": "masterfile", "fotosearch": "fotosearch", "colourbox": "colourbox",
    "robertharding": "robert harding", "naturepl": "nature picture library", "akg-images": "akg images",
    "maryevans": "mary evans", "topfoto": "topfoto", "heritage-images": "heritage images",
    "wirestock": "wirestock", "motionarray": "motion array", "envato": "envato", "stockfresh": "stockfresh",
    "featurepics": "featurepics", "crushpixel": "crushpixel", "yayimages": "yay images",
    "mostphotos": "mostphotos", "panthermedia": "panthermedia", "westend61": "westend61",
    "mauritius-images": "mauritius images", "plainpicture": "plainpicture", "stockfood": "stockfood",
    "imagebroker": "imagebroker", "diomedia": "diomedia", "profimedia": "profimedia",
    "fineartamerica": "fine art america", "photocase": "photocase",
}
# Whole domains, where a name alone would be too loose ("granger", "pixels")
# or the CDN is not named after its agency (Adobe Stock's ftcdn.net,
# Shutterstock's picdn.net, Getty's short links).
_DOMAINS: Dict[str, str] = {
    "stock.adobe.com": "adobe stock", "ftcdn.net": "adobe stock", "picdn.net": "shutterstock",
    "gty.im": "getty", "gettyimagesbank.com": "getty", "granger.com": "granger", "pixta.jp": "pixta",
    "newscom.com": "newscom", "photo12.com": "photo12", "apimages.com": "ap images", "imagn.com": "imagn",
    "sciencesource.com": "science source", "pixels.com": "fine art america",
}
_LABEL_SUFFIXES = ("", "images", "image", "photos", "photo", "pictures", "stock")
# Free picture libraries whose own page titles say "stock photo" ("Lake ·
# Free Stock Photo" on Pexels, "Download Free Images & Stock Photos" on
# Unsplash): no watermark, a licence that allows this use. The generic listing
# words do not block their pictures; a named agency still does.
_FREE_LIBRARIES = ("pexels.com", "pixabay.com", "unsplash.com", "wikimedia.org", "wikipedia.org",
                   "stocksnap.io", "burst.shopify.com")
_URL_HOST = re.compile(r"https?://([^/\s\"'<>?#]+)", re.I)
_BARE_HOST = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.I)
# The file name an agency gives its pictures, as newsrooms and blogs re-publish
# them: "GettyImages-1325430438.jpg", "gettyimages-640472731",
# "Shutterstock_12951675b.jpg", "iStock-1171164520.jpg", "AdobeStock_301.jpeg",
# "depositphotos_1234-stock-photo.jpg", "dreamstime_xl_1880226.jpg".
_FILE_MARK = re.compile(
    r"(?<![a-z])(getty[-_ ]?images|shutterstock|istock(?:photo)?|adobe[-_ ]?stock|depositphotos|dreamstime|"
    r"bigstock(?:photo)?|123rf|alamy|agefotostock)[-_ ]?(?:[a-z]{1,3}[-_ ])?\d{4,}", re.I)
_FILE_AGENCY = (("getty", "getty"), ("shutterstock", "shutterstock"), ("istock", "istock"), ("adobe", "adobe stock"),
                ("depositphotos", "depositphotos"), ("dreamstime", "dreamstime"), ("bigstock", "bigstock"),
                ("123rf", "123rf"), ("alamy", "alamy"), ("agefotostock", "agefotostock"))
# A listing's own words. "Stock photo" needs its own word start: "livestock
# photo" and "Woodstock photos" are not listings.
_NAMED = re.compile(
    r"\b(?:alamy|getty ?images|shutterstock|istock(?:photo)?|dreamstime|depositphotos|123rf|adobe ?stock|"
    r"agefotostock|bigstock|pond5|freepik|vecteezy|pngtree|superstock|science photo library|"
    r"premium (?:photo|vector|psd)|free (?:photo|vector|psd) \|)\b", re.I)
_LISTING = re.compile(
    r"\b(?:stock (?:photo(?:s|graphy|graph)?|image(?:s|ry)?|picture(?:s)?|illustration(?:s)?|vector(?:s)?|"
    r"footage|video(?:s)?|clip(?:s)?|art)|royalty[- ]free|rights[- ]managed|(?:for )?editorial use(?: only)?)\b", re.I)
_WORD_AGENCY = (("alamy", "alamy"), ("getty", "getty"), ("shutterstock", "shutterstock"), ("istock", "istock"),
                ("dreamstime", "dreamstime"), ("depositphotos", "depositphotos"), ("123rf", "123rf"),
                ("adobe", "adobe stock"), ("agefotostock", "agefotostock"), ("bigstock", "bigstock"),
                ("pond5", "pond5"), ("freepik", "freepik"), ("premium", "freepik"), ("free ", "freepik"),
                ("vecteezy", "vecteezy"), ("pngtree", "pngtree"), ("superstock", "superstock"),
                ("science photo", "science photo library"))


def enabled() -> bool:
    return bool(getattr(config, "STOCK_BLOCK", True))


def _hosts(text: str) -> List[str]:
    """Every host named in a string: a URL's own, one carried in its query
    ("...aggregator-api/download?url=https://c8.alamy.com/..."), a bare host
    in a credit line ("Yandex image result — c8.alamy.com", "| Dreamstime.com")."""
    text = str(text or "").strip()
    if not text:
        return []
    if "%3a%2f%2f" in text.lower():
        text = urllib.parse.unquote(text)
    found = [h.lower().split("@")[-1].split(":")[0] for h in _URL_HOST.findall(text)]
    for tok in text.split():
        tok = tok.strip("()[],;|").lower()
        if _BARE_HOST.match(tok) and tok not in found:
            found.append(tok)
    return found


def host_agency(*urls) -> str:
    """The agency one of these addresses belongs to ("alamy"), or ""."""
    for u in urls:
        for host in _hosts(u):
            for d, agency in _DOMAINS.items():
                if host == d or host.endswith("." + d):
                    return agency
            for label in host.split("."):
                for brand, agency in _BRANDS.items():
                    if label.startswith(brand) and label[len(brand):] in _LABEL_SUFFIXES:
                        return agency
    return ""


def free_library(*urls) -> bool:
    """One of these addresses is a free picture library's (Pexels, Pixabay, Unsplash, Wikimedia)."""
    return any(host == d or host.endswith("." + d) for u in urls for host in _hosts(u) for d in _FREE_LIBRARIES)


def file_agency(*urls) -> str:
    """The agency whose file name a picture carries ("GettyImages-1325430438.jpg" -> "getty"), or ""."""
    for u in urls:
        u = str(u or "")
        if not u.startswith("http"):
            continue
        parts = urllib.parse.urlparse(u)
        m = _FILE_MARK.search(urllib.parse.unquote(parts.path + " " + parts.query))
        if m:
            key = re.sub(r"[-_ ]", "", m.group(1).lower())
            return next((a for k, a in _FILE_AGENCY if key.startswith(k)), key)
    return ""


def words_agency(*texts, generic: bool = True) -> str:
    """The agency (or "stock listing") a title or credit line names, or "".
    `generic` False: only a named agency counts, not "stock photo" or "royalty-free"
    (a free library's own picture, src/stockblock._FREE_LIBRARIES)."""
    blob = " ".join(str(t or "") for t in texts if t)
    if not blob:
        return ""
    blob = re.sub(r"https?://\S+", " ", blob)                    # words, not URL paths
    m = _NAMED.search(blob)
    if m:
        hit = m.group(0).lower()
        return next((a for k, a in _WORD_AGENCY if hit.startswith(k)), "stock listing")
    return "stock listing" if generic and _LISTING.search(blob) else ""


def agency(url: str = "", page_url: str = "", thumbnail: str = "", title: str = "", attribution: str = "") -> str:
    """Which agency a picture candidate belongs to by its names ("" = none found)."""
    if not enabled():
        return ""
    found = host_agency(url, page_url, thumbnail, attribution)
    if not found and getattr(config, "STOCK_BLOCK_FILE_NAMES", True):
        found = file_agency(url, thumbnail)
    if not found and getattr(config, "STOCK_BLOCK_WORDS", True):
        found = words_agency(title, attribution, generic=not free_library(url, page_url))
    return found


def reason(url: str = "", page_url: str = "", thumbnail: str = "", title: str = "", attribution: str = "") -> str:
    """Why a picture candidate must not be used ("" = keep): "a stock-agency picture (alamy)"."""
    found = agency(url, page_url, thumbnail, title, attribution)
    return f"a stock-agency picture ({found})" if found else ""


def _fields(item: Any) -> Dict[str, str]:
    """url / page / thumbnail / title / attribution of a MediaAsset, or of an
    editor's-choice, library or scene-media dict (whose sourceUrl is where the
    picture came from; its url is our own copy)."""
    if isinstance(item, dict):
        get = item.get
        url = str(get("sourceUrl") or get("source_url") or get("url") or "")
        return {"url": url if url.startswith("http") else "",
                "page_url": str(get("page_url") or get("pageUrl") or get("page") or ""),
                "thumbnail": str(get("thumbnail") or get("thumb") or ""),
                "title": str(get("title") or ""), "attribution": str(get("attribution") or "")}
    url = str(getattr(item, "url", "") or "")
    return {"url": url if url.startswith("http") else "",
            "page_url": str(getattr(item, "page_url", "") or ""),
            "thumbnail": str(getattr(item, "thumbnail", "") or ""),
            "title": "", "attribution": str(getattr(item, "attribution", "") or "")}


def asset_reason(item: Any) -> str:
    """reason() for a MediaAsset or a dict (an editor's choice, a library row, a
    scene's media). Never for a picture the worker generated itself."""
    if item is None or not enabled():
        return ""
    source = item.get("source") if isinstance(item, dict) else getattr(item, "source", "")
    if source == "generated":
        return ""
    return reason(**_fields(item))


# --------------------------------------------------------------------------- #
# The job's count
# --------------------------------------------------------------------------- #

_LOCK = threading.Lock()
_STATS: Dict[str, Any] = {}
_SEEN: set = set()


def reset() -> None:
    """Between jobs (media.reset_cache)."""
    with _LOCK:
        _STATS.clear()
        _SEEN.clear()
        _PIXELS.clear()


def _bump(group: str, key: str, n: int = 1) -> None:
    box = _STATS.setdefault(group, {})
    box[key] = box.get(key, 0) + n


def note(why: str, where: str = "", key: str = "") -> None:
    """Count one candidate turned down by its names. `key` (its address) counts
    a picture once however many scenes' searches return it."""
    if not why:
        return
    m = re.search(r"\(([^)]*)\)", why)
    with _LOCK:
        if key:
            if key in _SEEN:
                return
            if len(_SEEN) > 50000:
                _SEEN.clear()
            _SEEN.add(key)
        _STATS["blocked"] = _STATS.get("blocked", 0) + 1
        _bump("byAgency", (m.group(1) if m else why)[:40])
        if where:
            _bump("byPath", where)


def note_watermark(why: str, where: str = "") -> None:
    """Count one downloaded picture turned down by its pixels."""
    with _LOCK:
        _STATS["watermarked"] = _STATS.get("watermarked", 0) + 1
        _bump("byMark", (why or "watermark").split(" (")[0][:60])
        if where:
            _bump("byPath", where)


def blocked(item: Any, where: str = "") -> str:
    """asset_reason(), counted: why this candidate is skipped ("" = it may be used)."""
    why = asset_reason(item)
    if why:
        f = _fields(item)
        note(why, where, key=f["url"] or f["page_url"] or f["attribution"])
    return why


def stats() -> Dict[str, Any]:
    """{"blocked": n kept out by their names, "byAgency": {...}, "byPath": {...},
    "watermarked": n turned down by their pixels, "byMark": {...},
    "pixels": {"barChecked": n, "stampChecked": n, "stampSkipped": n with the model busy past
    STAMP_WAIT_SECONDS}, "pixelSeconds": time the pixel checks took}"""
    with _LOCK:
        out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _STATS.items()}
    out.setdefault("blocked", 0)
    out.setdefault("watermarked", 0)
    if "pixelSeconds" in out:
        out["pixelSeconds"] = round(float(out["pixelSeconds"]), 1)
    return out


def merge(other: Optional[dict]) -> None:
    """Add another machine's count (a part of a long video sourced elsewhere: src/fanout.py)."""
    if not isinstance(other, dict):
        return
    with _LOCK:
        for k, v in other.items():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                _STATS[k] = _STATS.get(k, 0) + v
            elif isinstance(v, dict):
                for kk, n in v.items():
                    if isinstance(n, (int, float)) and not isinstance(n, bool):
                        _bump(k, str(kk), n)


# --------------------------------------------------------------------------- #
# 2. Pixels: the credit bar, the stamp
# --------------------------------------------------------------------------- #

_STILL_EXT = {".jpg", ".jpeg", ".png", ".webp"}
# The bar: a strip of one flat colour along the whole bottom edge, 2.5-20 % of
# the height, the picture ending sharply above it, small high-contrast text in
# it (an agency's logo, "Image ID", its address) and no border of the same
# colour on the other sides (a mounted print, a letterbox).
BAR_WIDTH = 640
BAR_TOLERANCE = 14
BAR_INK_GAP = 60
BAR_MIN_TRANSITIONS = 20
# CLIP's prompts for the stamp, scored on the whole picture and six square tiles
# of it at full size (a stamp is small; at 224 px of the whole picture it is
# gone). The share is the softmax mass of the first group (as localvision.classify).
# Documents and archive prints are written on, so without plain prompts of
# their own CLIP read their writing as a stamp: a ledger page, a 2007 Record of
# Decision and a captioned 1930s print of Black Canyon were turned down on the
# Lake Mead video's pictures until the six document prompts were added (2026-10-04).
# The weather channel's own subjects need theirs too: the stamp prompts also
# draw a polished, stock-looking sky or sea with no mark at all. On 352 clean
# Wikimedia Commons weather pictures (three sets, the third untouched until
# the prompts were chosen) 29 were turned down - 4 of 8 lightning strikes, 3
# of 8 breaking waves, big-wave surf, storm surge, aurora, waterfalls - and
# 10 with the last three prompts (2.8 %); the other clean pictures 5 -> 2 of
# 267, the 102 agency previews still 74, synthetic stamps on weather pictures
# 94 -> 86 of 117 (review, 2026-10-04).
STAMP_PROMPTS = ["a watermark", "watermarked image", "stock photo watermark", "alamy", "gettyimages",
                 "shutterstock", "iStock", "dreamstime", "depositphotos", "adobe stock", "123rf"]
PLAIN_PROMPTS = ["a photo", "a landscape", "a building", "people", "a river", "a lake", "a desert", "a city",
                 "an old photo", "a map", "text", "a sign",
                 "a document", "a page of handwriting", "a scanned document", "a letter",
                 "an archive photograph with a caption", "a historical photograph",
                 "a storm", "the sea", "the sky"]
# How long a picture waits for one of the local model's few slots
# (localvision._RUN, shared with the clip checks) before its stamp check is
# skipped - no finding, as with no model. Measured 2026-10-04 on an 8-core
# laptop with 16 sourcing threads asking at once: 8 s at the median, 12 s at most.
STAMP_WAIT_SECONDS = 30.0


def is_still(path: str) -> bool:
    return os.path.splitext(str(path or ""))[1].lower() in _STILL_EXT


def credit_bar(path: str) -> Optional[dict]:
    """The agency credit bar along the bottom edge of a picture, or None.
    {"height": share of the height, "ink": share of text pixels, "transitions": text edges on its busiest row}"""
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w != BAR_WIDTH:
                im = im.resize((BAR_WIDTH, max(16, round(h * BAR_WIDTH / w))), Image.BILINEAR)
            a = np.asarray(im, np.int16)
    except Exception:  # noqa: BLE001 - an unreadable picture is "no finding"
        return None
    H, W, _ = a.shape
    base = max(2, int(H * 0.012))
    colour = np.median(a[H - base:, :, :].reshape(-1, 3), axis=0)
    dist = np.abs(a - colour).max(axis=2)
    flat = dist <= BAR_TOLERANCE
    frac = flat.mean(axis=1)
    n = 0
    while n < int(H * 0.22) and frac[H - 1 - n] >= 0.70:
        n += 1
    if n < max(8, int(H * 0.025)) or n >= int(H * 0.20):
        return None
    above = frac[max(0, H - n - 4):H - n]
    if above.size == 0 or float(above.min()) > 0.5:
        return None                                     # the picture fades into it: no bar edge
    ink_px = dist[H - n:, :] > BAR_INK_GAP
    ink = float(ink_px.mean())
    transitions = int(np.abs(np.diff(ink_px.astype(np.int8), axis=1)).sum(axis=1).max())
    top = float(flat[:max(4, n // 2), :].mean())
    side = max(float(flat[:H - n, :max(4, W // 50)].mean()), float(flat[:H - n, -max(4, W // 50):].mean()))
    if transitions < BAR_MIN_TRANSITIONS or not 0.004 <= ink <= 0.30 or top >= 0.5 or side >= 0.5:
        return None
    return {"height": round(n / H, 4), "ink": round(ink, 4), "transitions": transitions,
            "colour": [int(x) for x in colour]}


def _tiles(im, cols: int = 3, rows: int = 2) -> list:
    """The whole picture and square crops covering it, each seen by CLIP at 224 px."""
    w, h = im.size
    out = [im]
    tw, th = w / cols, h / rows
    side = max(tw, th)
    for r in range(rows):
        for c in range(cols):
            cx, cy = (c + 0.5) * tw, (r + 0.5) * th
            x0 = int(min(max(0, cx - side / 2), max(0, w - side)))
            y0 = int(min(max(0, cy - side / 2), max(0, h - side)))
            out.append(im.crop((x0, y0, int(min(w, x0 + side)), int(min(h, y0 + side)))))
    return out


def _model_size(im, side: int):
    """A tile at the size localvision._prep makes of it (shortest side `side`):
    shrunk here, before the model's few slots are taken - the same pixels,
    less time holding one (Pillow returns a copy when the size already fits)."""
    from PIL import Image
    w, h = im.size
    s = side / max(1, min(w, h))
    size = (max(side, round(w * s)), max(side, round(h * s)))
    return im if im.size == size else im.resize(size, Image.BICUBIC)


def stamp_share(path: str) -> Optional[float]:
    """How much the local CLIP model reads an agency stamp on the picture or on
    any tile of it (0-1), or None when the model is not installed."""
    from . import localvision
    if not localvision.available():
        return None
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            tiles = [_model_size(t, localvision._SIZE) for t in _tiles(im.convert("RGB"))]
        if not localvision._RUN.acquire(timeout=STAMP_WAIT_SECONDS):
            with _LOCK:
                _bump("pixels", "stampSkipped")
            print(f"[stockblock] stamp check skipped: the local model stayed busy {STAMP_WAIT_SECONDS:.0f} s",
                  flush=True)
            return None
        try:
            emb = localvision.embed_images(tiles)
            txt = localvision.embed_texts(STAMP_PROMPTS + PLAIN_PROMPTS)
        finally:
            localvision._RUN.release()
        logits = 100.0 * emb @ txt.T
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        return float(p[:, :len(STAMP_PROMPTS)].sum(axis=1).max())
    except Exception as e:  # noqa: BLE001 - a model error never drops a picture
        print(f"[stockblock] stamp check failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None


# Each picture's measures by its content, so a picture several scenes' searches
# return (each saving its own copy) is read once per job: the bar's reason and
# the stamp's share (the threshold is applied on every call: a job may change it).
_PIXELS: Dict[str, Any] = {}
_MISS = object()


def _digest(path: str) -> str:
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _measured(key: str, counter: str, measure) -> Any:
    with _LOCK:
        hit = _PIXELS.get(key, _MISS)
    if hit is not _MISS:
        return hit
    t0 = time.time()
    hit = measure()
    with _LOCK:
        if len(_PIXELS) > 20000:
            _PIXELS.clear()
        _PIXELS[key] = hit
        _bump("pixels", counter)
        _STATS["pixelSeconds"] = _STATS.get("pixelSeconds", 0.0) + (time.time() - t0)
    return hit


def watermark_reason(path: str, bar: bool = True, stamp: bool = True) -> str:
    """Why a downloaded picture's own pixels say it is an agency preview ("" = nothing found).
    `bar`: the credit bar (free, ~50 ms, no model) - goes first. `stamp`: the
    local CLIP model's read of a stamp (seven looks, ~0.7 s on a laptop) at
    WATERMARK_CLIP_SHARE or more, 0 = off; a caller runs it only on a picture
    it is about to keep (src/media.py)."""
    if not getattr(config, "WATERMARK_CHECK", True) or not path or not is_still(path) or not os.path.isfile(path):
        return ""
    try:
        key = _digest(path)
    except OSError:
        return ""
    if bar:
        found = _measured(f"bar:{key}", "barChecked", lambda: credit_bar(path))
        if found:
            return f"an agency credit bar along the bottom edge ({found['height'] * 100:.0f}% of the height)"
    floor = float(getattr(config, "WATERMARK_CLIP_SHARE", 0.75))
    if stamp and floor > 0:
        share = _measured(f"stamp:{key}", "stampChecked", lambda: stamp_share(path))
        if share is not None and share >= floor:
            return f"an agency watermark stamped on the picture (local check {share:.2f})"
    return ""
