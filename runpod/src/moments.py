"""
Pick the moment inside a YouTube video that actually shows the beat.

A relevant video is not a relevant shot. The old selector found a plausible
video by title and cut it 35% of the way in — so "Lake Mead's exposed boat
ramps" could land on the presenter, the title card, or a map, from a genuinely
on-topic documentary.

YouTube publishes storyboards for every video: the sprite sheets behind the
hover-preview thumbnails, roughly one frame per second, a few hundred KB for the
whole video. yt-dlp lists them as the `sb*` formats with their grid size and
per-sheet duration, so every tile maps to an exact timestamp. This module lays
~20 tiles from across the video into one numbered contact sheet and asks the
vision model which number shows the intent. The clip is then cut at that
timestamp — and a video whose best tile scores below the floor is skipped
before a single byte of footage is downloaded.
"""
import base64
import io
import threading
from typing import Dict, List, Optional, Tuple

import requests

from . import config, vision

_TILE_W, _TILE_H = 240, 135        # upscaled from 160x90 so the model can read it

# The sheet itself (which tiles, at which timestamps) only depends on the
# video and how long a clip needs to be, not on any one scene's intent - a
# subject that repeats across several beats used to re-fetch and re-build it
# from scratch for every beat that scouted the same candidate. Only the
# vision judgement of that sheet (config.MOMENT_TILES tiles is scene-specific
# and is never cached here.
_SHEET_CACHE: Dict[str, Optional[Tuple[str, List[float]]]] = {}
_SHEET_LOCK = threading.Lock()


def reset_cache() -> None:
    """Call between jobs, alongside media.reset_cache()."""
    with _SHEET_LOCK:
        _SHEET_CACHE.clear()


def _storyboard_format(info: dict) -> Optional[dict]:
    """
    The sharpest storyboard, chosen by pixel width - never by format id.

    The ids do not map to fixed sizes: on one video `sb1` is 160x90, on another
    it is 80x45. Picking by id handed the model an 80x45 tile upscaled 3x, and
    it confidently "saw" Hoover Dam in what was a river through woods.
    """
    boards = [f for f in (info.get("formats") or [])
              if str(f.get("format_id", "")).startswith("sb") and f.get("fragments")
              and f.get("rows") and f.get("columns")]
    if not boards:
        return None
    best = max(boards, key=lambda f: int(f.get("width") or 0))
    # Below this the model is guessing, and a guess is worse than no pick.
    return best if int(best.get("width") or 0) >= 120 else None


def _tile_times(fmt: dict) -> List[Tuple[int, int, float]]:
    """(fragment_index, tile_index, seconds) for every tile in the storyboard."""
    rows, cols = int(fmt.get("rows") or 0), int(fmt.get("columns") or 0)
    fps = float(fmt.get("fps") or 0)
    if not rows or not cols or fps <= 0:
        return []
    out, t0 = [], 0.0
    for fi, frag in enumerate(fmt["fragments"]):
        dur = float(frag.get("duration") or 0)
        per = rows * cols
        count = min(per, max(1, int(round(dur * fps))))
        for ti in range(count):
            out.append((fi, ti, t0 + ti / fps))
        t0 += dur
    return out


def _fetch(url: str, proxy: str) -> Optional[bytes]:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = requests.get(url, proxies=proxies, timeout=20)
        if r.ok and r.content:
            return r.content
    except requests.RequestException:
        pass
    return None


def contact_sheet(info: dict, seconds: float, proxy: str = "",
                  tiles: int = 20) -> Optional[Tuple[str, List[float]]]:
    """(base64 JPEG of a numbered grid, timestamp of each number) or None."""
    vid = info.get("id") or ""
    key = f"{vid}::{round(seconds)}::{tiles}" if vid else ""
    if key:
        with _SHEET_LOCK:
            if key in _SHEET_CACHE:
                return _SHEET_CACHE[key]
    made = _build_contact_sheet(info, seconds, proxy, tiles)
    if key:
        with _SHEET_LOCK:
            _SHEET_CACHE[key] = made
    return made


def _build_contact_sheet(info: dict, seconds: float, proxy: str,
                         tiles: int) -> Optional[Tuple[str, List[float]]]:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    fmt = _storyboard_format(info)
    duration = float(info.get("duration") or 0)
    if not fmt or duration <= 0:
        return None
    rows, cols = int(fmt["rows"]), int(fmt["columns"])
    tw, th = int(fmt.get("width") or 160), int(fmt.get("height") or 90)

    # Skip the first and last 5% (intros, end screens) and anything too close
    # to the end to fit a full clip.
    latest = max(0.0, duration - seconds - 1.0)
    pool = [t for t in _tile_times(fmt)
            if duration * 0.05 <= t[2] <= min(duration * 0.95, latest)]
    if not pool:
        return None
    step = max(1, len(pool) // tiles)
    chosen = pool[::step][:tiles]

    sheets = {}
    grid_cols = 5
    grid_rows = (len(chosen) + grid_cols - 1) // grid_cols
    canvas = Image.new("RGB", (grid_cols * _TILE_W, grid_rows * _TILE_H), "black")
    draw = ImageDraw.Draw(canvas)
    times = []
    for n, (fi, ti, t) in enumerate(chosen):
        if fi not in sheets:
            raw = _fetch(fmt["fragments"][fi].get("url") or "", proxy)
            try:
                sheets[fi] = Image.open(io.BytesIO(raw)).convert("RGB") if raw else None
            except Exception:  # noqa: BLE001 — a corrupt sheet just loses its tiles
                sheets[fi] = None
        sheet = sheets[fi]
        if sheet is None:
            continue
        r, c = divmod(ti, cols)
        tile = sheet.crop((c * tw, r * th, c * tw + tw, r * th + th)).resize((_TILE_W, _TILE_H))
        x, y = (len(times) % grid_cols) * _TILE_W, (len(times) // grid_cols) * _TILE_H
        canvas.paste(tile, (x, y))
        label = str(len(times) + 1)
        draw.rectangle([x, y, x + 28, y + 20], fill="black")
        draw.text((x + 5, y + 4), label, fill="yellow")
        times.append(t)
    if len(times) < 3:
        return None
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode(), times


def pick(info: dict, intent: str, context: str, seconds: float,
         proxy: str = "") -> Optional[dict]:
    """
    {"start": seconds, "score": 0-1, "description": str} for the best moment,
    or None when there is no storyboard or no model — the caller then falls back
    to its old fixed grab point.
    """
    if not config.MOMENT_SELECTION or not intent or not vision.enabled():
        return None
    made = contact_sheet(info, seconds, proxy, config.MOMENT_TILES)
    if not made:
        return None
    sheet_b64, times = made
    verdict = vision.pick_tile(sheet_b64, len(times), intent, context)
    if not verdict:
        return None
    idx = verdict["tile"] - 1
    if not 0 <= idx < len(times):
        return None
    # Start a touch before the chosen frame so the moment is inside the cut,
    # not at its very first frame.
    start = max(0.0, times[idx] - min(1.0, seconds * 0.2))
    return {"start": start, "score": verdict["score"],
            "description": verdict["description"], "tile": verdict["tile"]}
