"""
Where a kinetic-type look sits on its picture (the owner, 2026-10-05, on the boxed "ALMOST 15" over a detailed
map at 02:05 of his Las Vegas video: "use a perfect place to put the animations" - the calmest side, never over
lettering burned into the footage, a soft blurred panel over busy pictures like detailed maps).

For each KT look, the picture it starts on is measured: the worker's vision data when it has it (media.focus.busy,
two or more rows of burned-in lettering, a picture whose subject is text), else a cheap local check - the edge
density of the look's corner of a 192x108 grey copy of the picture (its thumbnail for a clip). No paid call.

  * busy under the look's home  -> overlay.backing = "panel" (LibKinetic's slim blurred side panel);
  * the mirrored side much calmer -> overlay.zone = that side (one kind still lands in one of two places).

The renderer reads both (remotion/src/components/lib/typeKit.tsx zoneFor, LibKinetic useLook); a planner's choice
wins over the renderer's own busy check (Main.tsx).
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

KT_UPPER = {"KT_DATE", "KT_YEAR", "KT_TIME", "KT_DATE_CARD", "KT_DATE_LINE", "KT_TIME_CLOCK"}
KT_FIXED_LOWER = {"KT_LOWER_THIRD", "KT_CHIP", "KT_DATE_BADGE"}
# The date family draws its own frosted glass (remotion LibKtDates.tsx): never the side panel, but it still
# takes the calmer side of its picture.
KT_SELF_BACKED = KT_UPPER | {"KT_DATE_BADGE"}
# The look pack (remotion LibKtPack / LibKtPictures / LibKtMaps, src/lookpack.py) places itself: its cards bring their
# own glass and side (the term, the gauge, the trend, the milestones, the place tag, the evidence print), the arrow
# keeps to the calm side of the thing it points at, the full-frame ones cover the picture. Only its pull quote is
# words on the footage like the kinetic words above (home low left, the panel over a busy picture).
KT_PACK_OWN_PLACE = {"KT_TERM", "KT_LEVEL", "KT_TREND", "KT_MILESTONES", "KT_POINTER", "KT_CHAPTER", "KT_EVIDENCE",
                     "KT_THEN_NOW", "KT_TWO_PLACES", "KT_LOCATOR", "KT_PLACE"}
# Looks pack 3 (remotion LibKtPack3 / LibKtMaps3, src/lookpack3.py): its maps cover the frame (left alone); its cards
# take the calmer side of their picture - the glass ones (the ranking, the waterline, the scale, the alert) never the
# panel, they bring their own; the change and the streak (a figure on a soft shade, like kt-number) the panel over a busy
# picture.
KT_PACK3_MAPS = {"KT_ROUTE", "KT_STORM", "KT_TOTALS", "KT_REGIONS"}
KT_PACK3_HOME = {"KT_RANKING": "right-panel", "KT_WATERLINE": "right-panel", "KT_SEVERITY": "lower-left",
                 "KT_ALERT": "upper-left"}
KT_PACK3_GLASS = set(KT_PACK3_HOME)
# Looks pack 4 (remotion LibKtPack4 / LibKtCards4, src/lookpack4.py): its cards take the calmer side of their picture
# and bring their own glass (never the panel); the money counter (a figure on a soft shade, like kt-number) takes the
# panel over a busy picture; the versus scoreboard and the cause chain place themselves (low in the middle, up top off a
# face or lettering) and are left alone.
KT_PACK4_HOME = {"KT_PRICE": "right-panel", "KT_TABLE": "right-panel", "KT_PROSCONS": "right-panel",
                 "KT_PODIUM": "right-panel", "KT_CASE": "right-panel", "KT_POST": "right-panel",
                 "KT_PROFILE": "lower-left", "KT_STEPS": "left-panel", "KT_FACTCHECK": "left-panel"}
KT_PACK4_GLASS = set(KT_PACK4_HOME)
KT_PACK4_SELF = {"KT_VERSUS", "KT_CHAIN"}
BUSY_EDGE = 45.0        # mean edge strength (0-255) of the look's corner above which words get the panel
CALMER = 0.7            # the mirrored corner is used when it is at most this share of the home corner's
# the corners measured, as shares of the frame (x0, y0, x1, y1)
BOXES = {"lower-left": (0.0, 0.55, 0.45, 0.95), "lower-right": (0.55, 0.55, 1.0, 0.95),
         "upper-left": (0.0, 0.05, 0.45, 0.4), "upper-right": (0.55, 0.05, 1.0, 0.4),
         "left-panel": (0.0, 0.3, 0.45, 0.75), "right-panel": (0.55, 0.3, 1.0, 0.75)}
MIRROR = {"lower-left": "lower-right", "upper-left": "upper-right", "left-panel": "right-panel",
          "lower-right": "lower-left", "upper-right": "upper-left", "right-panel": "left-panel"}


def _focus_busy(media: dict) -> Optional[bool]:
    """remotion avoid.ts mediaBusy: the worker's own measure, or lettering in the picture (None: no data)."""
    focus = media.get("focus") if isinstance(media, dict) else None
    if not isinstance(focus, dict):
        return None
    b = focus.get("busy")
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        return float(b) >= 0.55
    if b is True:
        return True
    if (isinstance(focus.get("bands"), list) and len(focus["bands"]) >= 2) or focus.get("kind") == "text":
        return True
    return None


def edge_map(data: bytes):
    """A 192x108 edge-strength copy of the picture, cover-cropped to 16:9 (None when it does not decode)."""
    try:
        from PIL import Image, ImageFilter
        im = Image.open(io.BytesIO(data)).convert("L")
    except Exception:  # noqa: BLE001
        return None
    w, h = im.size
    if w < 16 or h < 9:
        return None
    if w / h > 16 / 9:
        nw = int(h * 16 / 9)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * 9 / 16)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return im.resize((192, 108)).filter(ImageFilter.FIND_EDGES)


def corner(edges, zone: str) -> float:
    x0, y0, x1, y1 = BOXES[zone]
    W, H = edges.size
    c = edges.crop((int(x0 * W) + 1, int(y0 * H) + 1, int(x1 * W) - 1, int(y1 * H) - 1))
    px = c.tobytes()
    return sum(px) / max(1, len(px))


def _home(tid: str, panel: bool) -> str:
    if tid in KT_PACK3_HOME:
        return KT_PACK3_HOME[tid]
    if tid in KT_PACK4_HOME:
        return KT_PACK4_HOME[tid]
    if tid in KT_UPPER:
        return "upper-left"
    if tid in KT_FIXED_LOWER:
        return "lower-left"
    return "left-panel" if panel else "lower-left"


def _picture_url(media: dict) -> str:
    if not isinstance(media, dict):
        return ""
    if media.get("type") == "image":
        return str(media.get("thumbnail") or media.get("url") or "")
    return str(media.get("thumbnail") or "")


def _default_fetch(url: str) -> Optional[bytes]:
    import requests
    try:
        r = requests.get(url, timeout=(10, 30), headers={"User-Agent": "ThumbGenius-lookplace/1.0"})
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:  # noqa: BLE001
        return None
    return None


def place(overlays: List[dict], scenes: List[dict], *, fetch: Optional[Callable[[str], Optional[bytes]]] = None,
          measure: bool = True) -> Dict[str, Any]:
    """Set backing / zone on the KT looks in place. Returns counts. A look the planner already placed is kept."""
    fetch = fetch or _default_fetch
    starts = sorted((int(s.get("startFrame") or 0), i) for i, s in enumerate(scenes or []))

    def scene_at(frame: int) -> Optional[dict]:
        found = None
        for st, i in starts:
            if st > frame:
                break
            found = scenes[i]
        return found

    todo = []
    for ov in overlays or []:
        tid = str(ov.get("template") or "")
        if not tid.startswith("KT_") or tid in KT_PACK_OWN_PLACE or tid in KT_PACK3_MAPS or tid in KT_PACK4_SELF \
                or ov.get("backing") or ov.get("zone"):
            continue
        sc = scene_at(int(ov.get("startFrame") or 0))
        if sc is not None:
            todo.append((ov, sc))
    urls = sorted({_picture_url(sc.get("media") or {}) for _ov, sc in todo
                   if measure and _focus_busy(sc.get("media") or {}) is None} - {""})
    maps: Dict[str, Any] = {}
    if urls:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for url, data in zip(urls, pool.map(fetch, urls)):
                maps[url] = edge_map(data) if data else None
    out = {"looks": len(todo), "panel": 0, "flipped": 0, "measured": 0, "unmeasured": 0}
    for ov, sc in todo:
        media = sc.get("media") or {}
        tid = str(ov["template"])
        busy = _focus_busy(media)
        edges = maps.get(_picture_url(media))
        if edges is None and busy is None:
            out["unmeasured"] += 1
            continue
        home = _home(tid, False)
        here = corner(edges, home) if edges is not None else None
        if busy is None:
            busy = here is not None and here >= BUSY_EDGE
        out["measured"] += 1
        if busy and tid not in KT_FIXED_LOWER and tid not in KT_SELF_BACKED and tid not in KT_PACK3_GLASS \
                and tid not in KT_PACK4_GLASS:
            ov["backing"] = "panel"
            out["panel"] += 1
        if edges is not None and here is not None and here >= BUSY_EDGE * 0.8:
            zone = _home(tid, ov.get("backing") == "panel")
            mine, theirs = corner(edges, zone), corner(edges, MIRROR[zone])
            if theirs <= mine * CALMER:
                ov["zone"] = MIRROR[zone]
                out["flipped"] += 1
    return out
