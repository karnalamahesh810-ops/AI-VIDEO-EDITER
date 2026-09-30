"""
Where a thing is in a picture: the anchor a red arrow, circle or box points at.

The looks that mark something on a still or on the playing clip read
overlay.anchor: {"x", "y"} in 0..1 of the frame, and optionally "r" (the
thing's radius as a share of the frame's shorter side) and "w", "h" (its box
as shares of the frame's width and height):

    vm-arrow / vm-circle / vm-box          marks over the playing clip (LibVideoMarks)
    pe-case-file / pe-circle-spotlight /   marks on a still (LibPhotoEditor), and the
    pe-magnify / pe-red-arrow ...          older pe-zoom-circle, pe-highlight-box, co-*

This module asks the vision model (src/vision.py's routing, hedging and
fallbacks) for that anchor:

    find_anchor(frame, what, context="") -> {"x", "y", "r", "w", "h", "confidence"} | None
    frame_at(video_path, seconds)       -> the frame there as a base64 JPEG | None

A mark on the wrong thing is worse than no mark, so a thing the model cannot
find, is not sure of (confidence < MIN_CONFIDENCE), finds filling the whole
picture, or that falls outside what the renderer shows comes back None and
the planner simply does not mark. Answers are cached per (frame, thing), so
asking again for the same shot costs nothing; a failed call is not cached.
"""
import base64
import hashlib
import io
import json
import math
import os
import re
import subprocess
import threading
from typing import Dict, Optional, Tuple

from . import costs, vision

MIN_CONFIDENCE = 0.6
FRAME_WIDTH = 768            # px: enough to place a mark, small enough to send fast
DISPLAY_ASPECT = 16 / 9      # the renderer's frame; media fill it with objectFit: cover
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

_SYSTEM = (
    "You locate one thing in a photo or video frame for a documentary video editor, who will draw "
    "a red arrow, circle or box on it. Find exactly the thing named, not merely something like it. "
    "Answer ONLY with JSON: "
    '{"found": true, "box_2d": [ymin, xmin, ymax, xmax], "confidence": 0.0-1.0, "label": "what you boxed"}. '
    "box_2d is the tight box round the thing in 0-1000 coordinates of the image (0,0 is the top-left "
    "corner). confidence is how sure you are that the box holds the named thing itself. "
    "If the thing is not visible, is too small to point at, cannot be told apart from several "
    'look-alikes, or is the whole picture, answer {"found": false, "confidence": 0}.'
)

# (frame digest, thing) -> the model's raw answer: (box in source 0..1, confidence) or None.
_CACHE: Dict[Tuple[str, str], Optional[Tuple[Tuple[float, float, float, float], float]]] = {}
_LOCK = threading.Lock()


def reset() -> None:
    """Forget cached answers (tests, a new job)."""
    with _LOCK:
        _CACHE.clear()


# ------------------------------------------------------------------ frames
def _run(cmd: list, timeout: int = 60) -> bytes:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).stdout or b""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return b""


def _duration(path: str) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path], timeout=30)
    try:
        return float(out.decode(errors="ignore").strip() or 0)
    except ValueError:
        return 0.0


def _grab(path: str, seconds: float, width: int) -> Optional[str]:
    jpeg = _run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, seconds):.3f}", "-i", path, "-frames:v", "1",
                 "-vf", f"scale='min({int(width)},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"])
    return base64.b64encode(jpeg).decode() if jpeg else None


def frame_at(video_path: str, seconds: float, width: int = FRAME_WIDTH) -> Optional[str]:
    """
    The frame of `video_path` at `seconds` as a base64 JPEG at most `width`
    px wide, or None when the file cannot be read. A time past the end gives
    the last frame; a still image gives itself.
    """
    if not video_path or not isinstance(video_path, str) or not os.path.isfile(video_path):
        return None
    try:
        t = float(seconds)
    except (TypeError, ValueError):
        t = 0.0
    if not math.isfinite(t) or os.path.splitext(video_path)[1].lower() in _IMAGE_EXT:
        t = 0.0
    t = max(0.0, t)
    out = _grab(video_path, t, width)
    if out is None and t > 0:
        dur = _duration(video_path)
        if dur > 0:
            out = _grab(video_path, max(0.0, min(t, dur) - 0.25), width)
    return out


def _as_b64(frame: str) -> Optional[str]:
    """Base64 image data from a file path, a data: URL or base64 text."""
    if not frame or not isinstance(frame, str):
        return None
    s = frame.strip()
    if s.startswith("data:"):
        s = s.partition(",")[2].strip()
        return s or None
    if len(s) < 4096 and "\n" not in s and os.path.isfile(s):
        if os.path.splitext(s)[1].lower() in _IMAGE_EXT:
            # A still, downscaled (vision caches its frames by content); raw bytes if ffmpeg is missing.
            frames = vision.sample_frames(s, 1, FRAME_WIDTH)
            if frames:
                return frames[0]
            try:
                with open(s, "rb") as fh:
                    return base64.b64encode(fh.read()).decode() or None
            except OSError:
                return None
        # A clip: its middle frame (pass frame_at(clip, t) for a particular moment).
        frames = vision.sample_frames(s, 1, FRAME_WIDTH)
        return frames[0] if frames else None
    body = re.sub(r"\s+", "", s)
    if len(body) >= 64 and re.fullmatch(r"[A-Za-z0-9+/_-]+=*", body):
        return body
    return None


def _mime(b64: str) -> str:
    if b64.startswith("iVBOR"):
        return "image/png"
    if b64.startswith("UklGR"):
        return "image/webp"
    return "image/jpeg"


def _size(b64: str) -> Tuple[int, int]:
    """(width, height) of the image, or 16:9 when it cannot be read."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(base64.b64decode(b64 + "=" * (-len(b64) % 4)))) as im:
            w, h = im.size
            if w > 0 and h > 0:
                return int(w), int(h)
    except Exception:  # noqa: BLE001 - an unreadable header only loses the aspect
        pass
    return 1920, 1080


# ------------------------------------------------------------------ answers
def _json_object(text: str) -> Optional[dict]:
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    depth, quote, escaped, end = 0, "", False, -1
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch == '"':
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    raw = text[start:end]
    for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", re.sub(r'([{,]\s*)([A-Za-z_][\w]*)(\s*:)', r'\1"\2"\3', raw))):
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except ValueError:
            continue
    return None


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _read(text: str) -> Optional[Tuple[Tuple[float, float, float, float], float]]:
    """
    The model's answer as ((x0, y0, x1, y1) in 0..1 of the source image,
    confidence), or None for "not found" / no usable box. Accepts the asked
    box_2d [ymin, xmin, ymax, xmax] in 0-1000 (or already 0-1) and, from a
    model that ignored that, a centre {"x", "y"} with "r" or "w"/"h".
    """
    data = _json_object(text)
    if not data:
        return None
    if data.get("found") is False:
        return None
    conf = _num(data.get("confidence", data.get("score")))
    conf = max(0.0, min(1.0, conf if conf is not None else 0.0))
    box = data.get("box_2d")
    if isinstance(box, (list, tuple)) and len(box) == 4 and all(_num(v) is not None for v in box):
        ymin, xmin, ymax, xmax = (float(v) for v in box)
        scale = 1.0 if max(abs(ymin), abs(xmin), abs(ymax), abs(xmax)) <= 1.0 else 1000.0
        x0, x1 = sorted((xmin / scale, xmax / scale))
        y0, y1 = sorted((ymin / scale, ymax / scale))
    else:
        cx, cy = _num(data.get("x")), _num(data.get("y"))
        if cx is None or cy is None:
            return None
        # The same scale as the box that was asked for: 0-1, else 0-1000.
        scale = 1.0 if max(abs(cx), abs(cy)) <= 1.0 else 1000.0
        cx, cy = cx / scale, cy / scale
        w, h, r = _num(data.get("w")), _num(data.get("h")), _num(data.get("r"))
        if w is not None and h is not None and w > 0 and h > 0:
            w, h = w / scale, h / scale
        else:
            w = h = 2 * max(0.01, (r / scale) if r is not None and r > 0 else 0.05)
        x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(1.0, x1), min(1.0, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1), conf


def _to_display(box: Tuple[float, float, float, float], src: Tuple[int, int],
                aspect: Optional[float]) -> Tuple[Tuple[float, float, float, float], Tuple[float, float]]:
    """
    A box in 0..1 of the source image, re-expressed in 0..1 of what the
    renderer shows: the source cover-cropped into a frame of `aspect`
    (None = shown as it is). Returns (box, (display w, display h) in source px).
    """
    sw, sh = src
    x0, y0, x1, y1 = box
    if not aspect or aspect <= 0 or sw <= 0 or sh <= 0 or abs(sw / sh - aspect) < 0.01:
        return (x0, y0, x1, y1), (float(sw), float(sh))
    if sw / sh > aspect:
        vis = aspect / (sw / sh)              # the sides are cropped
        off = (1 - vis) / 2
        return ((x0 - off) / vis, y0, (x1 - off) / vis, y1), (sh * aspect, float(sh))
    vis = (sw / sh) / aspect                  # the top and bottom are cropped
    off = (1 - vis) / 2
    return (x0, (y0 - off) / vis, x1, (y1 - off) / vis), (float(sw), sw / aspect)


def find_anchor(frame_path_or_b64: str, what: str, context: str = "", *,
                aspect: Optional[float] = DISPLAY_ASPECT) -> Optional[dict]:
    """
    Where `what` is in the frame, for a mark to point at:
    {"x", "y": its centre in 0..1 of the frame, "r": the radius of a circle
    round it as a share of the frame's shorter side (0..0.5), "w", "h": its
    box as shares of the frame's width and height, "confidence": 0..1},
    or None when the model is off, fails, cannot find it, is not sure
    (confidence < MIN_CONFIDENCE) or the thing fills the whole picture.

    frame_path_or_b64: an image file, a clip (its middle frame; use
    frame_at(clip, t) for a moment), a data: URL or base64 JPEG/PNG text.
    context: the narration line, to tell the model which one is meant.
    aspect: the frame the picture is shown in (the renderer covers a 16:9
    frame; None keeps the picture's own coordinates).
    """
    thing = re.sub(r"\s+", " ", str(what or "")).strip()
    if not thing or not vision.enabled():
        return None
    b64 = _as_b64(frame_path_or_b64)
    if not b64:
        return None
    key = (hashlib.sha1(b64.encode("ascii", "ignore")).hexdigest(), thing.lower()[:200])
    with _LOCK:
        cached = key in _CACHE
        answer = _CACHE.get(key)
    if not cached:
        note = re.sub(r"\s+", " ", str(context or "")).strip()[:400]
        content = [
            {"type": "text", "text": f"THING TO FIND: {thing[:200]}\n"
                                     + (f"NARRATION (which one is meant): {note}\n" if note else "")
                                     + "Answer with the JSON only."},
            {"type": "image_url", "image_url": {"url": f"data:{_mime(b64)};base64,{b64}"}},
        ]
        text, _model = vision._ask([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": content}], 300)
        if not text:
            return None                       # no model answered: not cached, the next ask tries again
        costs.record("vision.anchor")
        answer = _read(text)
        with _LOCK:
            _CACHE[key] = answer
    if not answer:
        return None
    box, conf = answer
    if conf < MIN_CONFIDENCE:
        return None
    (x0, y0, x1, y1), (dw, dh) = _to_display(box, _size(b64), aspect)
    w, h = x1 - x0, y1 - y0
    if w >= 0.9 and h >= 0.9:
        return None                           # the whole picture: nothing to point at
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
        return None                           # cropped off the screen
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
    w, h = max(0.0, x1 - x0), max(0.0, y1 - y0)
    r = 0.5 * math.hypot(w * dw, h * dh) / max(1.0, min(dw, dh))
    return {"x": round(cx, 4), "y": round(cy, 4), "r": round(max(0.02, min(0.5, r)), 4),
            "w": round(w, 4), "h": round(h, 4), "confidence": round(conf, 3)}
