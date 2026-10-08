"""
How much real detail a picture or a clip holds, and how far the screen blows
it up (the owner, 2026-10-04: "fix blur image issues", "images needed HD to
4K level and video clips also").

A file's pixel size says little: of the 141 full-screen pictures of the Lake
Powell video (15eb0bc3) most were stored 1920 px wide or more, yet 40 showed
their real detail blown up more than 1.6x - a 1920x1008 file holding about
360x189 px of picture, a Yandex result upscaled from 400x250. They had passed
every size check (MIN_IMAGE_LONG_SIDE, QUALITY_MIN_IMAGE_SIDE), because a
search engine's thumbnail, a page's upscaled copy and the Real-ESRGAN pass
all make big files of small pictures. Clips do the same: a 480p upload
re-encoded at 1080p says 1080 lines.

real_detail is the round trip: the part of the picture the screen shows (a
cover fit into the output frame keeps the middle band of a portrait) is
shrunk to s of its size and blown up again, Lanczos both ways; while the copy
stays within PSNR_DB of the original, nothing finer than s was ever there.
The smallest such s - found coarse to fine, then interpolated between the
two closest tries - times the stored size is the picture's real detail. It
is measured on a grey copy no bigger than the output frame (detail finer than
the screen shows is never needed), and the error is read where the picture
has texture (its most textured 30% of 32 px blocks) on a copy stretched to
the full grey range: a plain PSNR over the whole frame called a sharp dusk
photo and a calm lake blurry, because dark, flat and smooth pictures lose
little in any round trip.

screen_magnification is how much that real detail is enlarged on screen: the
cover fit into the output frame times the move's zoom (the Ken Burns moves of
remotion/src/transitions/stillMotion.tsx hold the picture up to 1.22x
closer). A picture above MAX_PICTURE_MAGNIFICATION is not used full screen:
sourcing takes the next candidate, footage or the fallback ladder, and the
quality gate replaces it before the render when something sharper exists -
never with an empty scene, a text card or a picture inset on a backdrop (the
owner banned that look).

A clip's real detail is the best of a few of its frames (motion blur and
fades soften single frames; an upscaled upload is soft in all of them).
"""
from __future__ import annotations

import contextvars
import math
import os
import subprocess
import threading
import time
from typing import Dict, Iterable, Optional, Tuple

from . import config

# A round trip through s of the size that stays this close to the original
# (over the textured blocks, contrast stretched) lost nothing that was there.
# Calibrated 2026-10-04: ten sharp 4K pictures of the Lake Powell video
# degraded to a known real detail and saved as web JPEGs read back within
# ~0.02 of the truth from 0.5 to 0.9 of the size at 37 dB (median; 35 dB
# reads 0.8 as 0.74, 39 dB reads it as 0.87), the same at 40% contrast; of 25
# of the video's own pictures judged by eye at 1:1, the 5 sharp ones read at
# most 1.20x at rest and 7 of the 8 blurry ones over 1.25x.
PSNR_DB = float(os.getenv("SHARPNESS_PSNR_DB", "37"))
# The error is read over this share of the picture's 32 px blocks, the most textured.
TEXTURED_SHARE = 0.3
_BLOCK = 32
# The contrast stretch (1st..99th percentile to the full range) is at most this
# gain: more amplified the compression noise of dark pictures into "detail".
MAX_GAIN = 3.0
# The scales tried first, coarse to fine; the bracket they find is bisected.
_COARSE = (0.95, 0.75, 0.55, 0.4, 0.28, 0.18, 0.1)
_BISECT = 1
# The output frame the renderer draws.
OUT_W, OUT_H = 1920, 1080
# Compressed video reads a little under its true detail: genuine 720p YouTube
# sections read 0.85-1.0 of their 720 lines, the same clips upscaled to 1080p
# and re-encoded ~600-730 lines, 480p uploads upscaled to 1080p ~410, 360p ones
# 220-480 (2026-10-04, 70 sections). A clip passes at this share of
# MIN_CLIP_REAL_HEIGHT and more (576 of 720 lines).
CLIP_SLACK = float(os.getenv("CLIP_SHARPNESS_SLACK", "0.8"))
# One frame read from a clip (a seek and a decode) takes at most this long.
FRAME_SECONDS = 20.0

# How much closer each still move brings the picture than a plain cover fit,
# at its largest held scale (remotion/src/transitions/stillMotion.tsx): the
# first second of a reveal or a settle is left out (it passes in a blur of
# motion). "parallax" draws a contained print over a blurred copy - its
# picture is never bigger than a cover fit. No move, or an unknown one: 1.06.
MOTION_ZOOM: Dict[str, float] = {
    "zoom-in": 1.15, "zoom-out": 1.16, "pan-left": 1.15, "pan-right": 1.15,
    "reveal-left": 1.16, "reveal-right": 1.16, "push-rotate": 1.18, "push-offcenter": 1.22,
    "pull-back": 1.22, "drift-diagonal": 1.16, "rotate-settle": 1.14, "parallax": 1.0,
}
DEFAULT_ZOOM = 1.06
# EXIF orientations that turn the picture a quarter (its displayed size is its stored size swapped).
_QUARTER = (5, 6, 7, 8)
# Ranking only: the most real detail adds to a passed candidate's score (a near tie goes
# to the sharper shot; relevance still leads - judge scores differ by 0.05-0.2).
DETAIL_BONUS = 0.03

_LOCK = threading.Lock()
_CACHE: Dict[tuple, Tuple[int, int]] = {}
_PROBES: Dict[tuple, Tuple[int, int, float]] = {}
# What the checks found in this job, per file measured: rejected or not (the job's stats).
_SEEN: Dict[str, Dict[str, bool]] = {"pictures": {}, "clips": {}}
_SECONDS = [0.0]


def reset() -> None:
    with _LOCK:
        _CACHE.clear()
        _PROBES.clear()
        for seen in _SEEN.values():
            seen.clear()
        _SECONDS[0] = 0.0


def stats() -> dict:
    """{"pictures", "pictures_rejected", "clips", "clips_rejected", "seconds"} of this job."""
    with _LOCK:
        out = {}
        for kind, seen in _SEEN.items():
            out[kind] = len(seen)
            out[f"{kind}_rejected"] = sum(1 for bad in seen.values() if bad)
        out["seconds"] = round(_SECONDS[0], 1)
        return out


def _note(kind: str, path: str, rejected: bool) -> None:
    with _LOCK:
        if len(_SEEN[kind]) > 20000:
            _SEEN[kind].clear()
        _SEEN[kind][os.path.abspath(path) if path and not str(path).startswith("http") else str(path)] = rejected


def _spent(seconds: float) -> None:
    with _LOCK:
        _SECONDS[0] += max(0.0, seconds)


def _file_key(path, *extra) -> Optional[tuple]:
    """A cache key that changes when the file does (its size and time), None for a link."""
    if not path or not isinstance(path, (str, os.PathLike)) or str(path).startswith(("http://", "https://")):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), st.st_size, st.st_mtime_ns) + tuple(extra)


# --------------------------------------------------------------------------- #
# The measure
# --------------------------------------------------------------------------- #

def motion_zoom(motion: Optional[str]) -> float:
    """How much closer a still's move brings it than a cover fit (1.06 for none or an unknown move)."""
    return MOTION_ZOOM.get(str(motion or "").strip().lower(), DEFAULT_ZOOM)


def planned_zoom() -> float:
    """The zoom a still found now will most likely get: the planner gives the n-th still the n-th
    move (timeline._IMAGE_MOTIONS), so the middle of those; a style that holds stills still
    (STILL_MOTION "none") draws them at 1.06."""
    if str(getattr(config, "STILL_MOTION", "") or "").lower() == "none":
        return DEFAULT_ZOOM
    try:
        from .timeline import _IMAGE_MOTIONS
        zooms = sorted(motion_zoom(m) for m in _IMAGE_MOTIONS)
    except Exception:  # noqa: BLE001 - the moves as of 2026-10-04
        zooms = sorted(MOTION_ZOOM.values())
    return zooms[len(zooms) // 2] if zooms else DEFAULT_ZOOM


def screen_magnification(w_eff: float, h_eff: float, out_w: int = OUT_W, out_h: int = OUT_H,
                         zoom: float = 1.0) -> float:
    """How many times the screen enlarges a picture's real detail (w_eff x h_eff px): a cover
    fit into out_w x out_h (the frame filled, the overflow cropped - a portrait picture must
    fill the width), times the move's zoom. 1.0 = shown at its own detail; inf when unknown."""
    try:
        w_eff, h_eff = float(w_eff or 0), float(h_eff or 0)
    except (TypeError, ValueError):
        return float("inf")
    if w_eff <= 0 or h_eff <= 0:
        return float("inf")
    return max(out_w / w_eff, out_h / h_eff) * max(0.01, float(zoom or 1.0))


def _psnr(mse: float) -> float:
    return 99.0 if mse <= 1e-9 else 10.0 * math.log10(255.0 ** 2 / mse)


class _Trip:
    """
    Round trips of one grey work image, remembered by scale. The error is
    read over the picture's most textured blocks (TEXTURED_SHARE of its
    _BLOCK px blocks by their own spread: a big sky or a calm lake loses
    nothing in any round trip and must not dilute the rest), and as if the
    picture filled the grey range (1st..99th percentile; a dark or flat
    picture's errors are as small as its contrast).
    """

    def __init__(self, gray):
        import numpy as np
        self.img = gray
        self.a = np.asarray(gray, dtype=np.float32)
        self.buf = np.empty_like(self.a)
        self.seen: Dict[float, float] = {}
        h, w = self.a.shape
        self.weights = None
        hb, wb = h // _BLOCK, w // _BLOCK
        if hb * wb >= 8:
            spread = self.a[:hb * _BLOCK, :wb * _BLOCK].reshape(hb, _BLOCK, wb, _BLOCK).std(axis=(1, 3))
            keep = spread >= np.quantile(spread, 1.0 - TEXTURED_SHARE)
            mask = np.zeros((h, w), dtype=np.float32)
            mask[:hb * _BLOCK, :wb * _BLOCK] = np.repeat(np.repeat(keep, _BLOCK, axis=0), _BLOCK, axis=1)
            if float(mask.sum()) > 0:
                self.weights = mask / float(mask.sum())
        sample = self.a[::4, ::4]
        lo, hi = np.percentile(sample, 1), np.percentile(sample, 99)
        self.offset = 20.0 * math.log10(min(MAX_GAIN, max(1.0, 255.0 / max(1.0, float(hi - lo)))))

    def psnr(self, s: float) -> float:
        s = round(float(s), 4)
        if s in self.seen:
            return self.seen[s]
        import numpy as np
        from PIL import Image
        w, h = self.img.size
        sw, sh = max(4, int(round(w * s))), max(4, int(round(h * s)))
        back = self.img.resize((sw, sh), Image.LANCZOS).resize((w, h), Image.LANCZOS)
        np.subtract(self.a, np.asarray(back, dtype=np.float32), out=self.buf)
        np.square(self.buf, out=self.buf)
        mse = float(np.vdot(self.buf, self.weights)) if self.weights is not None else float(self.buf.mean())
        p = _psnr(mse) - self.offset
        self.seen[s] = p
        return p


def fraction(gray, psnr_db: Optional[float] = None) -> float:
    """
    The share (0.1..1] of a grey picture's own size that holds real detail:
    the smallest round-trip scale that stays within `psnr_db` of it. Coarse
    steps first, then the bracket they find is bisected and interpolated.
    """
    p = PSNR_DB if psnr_db is None else float(psnr_db)
    w, h = gray.size
    if min(w, h) < 16:
        return 1.0
    trip = _Trip(gray)
    hi, lo = 1.0, None                      # hi: passes (or the full size), lo: fails
    for s in _COARSE:
        if trip.psnr(s) >= p:
            hi = s
        else:
            lo = s
            break
    if lo is None:
        return hi                           # soft even at the smallest step
    if hi >= 1.0:
        return 1.0                          # detail right up to the pixel
    for _ in range(_BISECT):
        mid = (hi + lo) / 2.0
        if trip.psnr(mid) >= p:
            hi = mid
        else:
            lo = mid
    ph, pl = trip.psnr(hi), trip.psnr(lo)
    # Where between lo (fails) and hi (passes) the curve crosses p.
    t = (p - pl) / max(1e-6, ph - pl)
    return max(0.05, min(1.0, lo + max(0.0, min(1.0, t)) * (hi - lo)))


def _region(size: Tuple[int, int], out_w: int, out_h: int) -> Tuple[int, int, int, int]:
    """The part of a w x h picture a cover fit into out_w x out_h shows (centred)."""
    w, h = size
    c = max(out_w / float(w), out_h / float(h))
    rw, rh = min(float(w), out_w / c), min(float(h), out_h / c)
    x0, y0 = (w - rw) / 2.0, (h - rh) / 2.0
    return int(round(x0)), int(round(y0)), int(round(x0 + rw)), int(round(y0 + rh))


def _work(gray, out_w: int, out_h: int):
    """(the visible region of a grey picture at no more than the output size, its scale:
    work pixels per picture pixel, 1.0 when the region is not bigger than the frame)."""
    from PIL import Image
    box = _region(gray.size, out_w, out_h)
    reg = gray if box == (0, 0) + tuple(gray.size) else gray.crop(box)
    rw, rh = reg.size
    k = min(1.0, out_w / float(rw), out_h / float(rh))
    if k < 1.0:
        reg = reg.resize((max(1, int(round(rw * k))), max(1, int(round(rh * k)))), Image.LANCZOS)
    return reg, k


def _load(src, out_w: int, out_h: int):
    """(grey picture, its scale against the stored picture, the stored size as displayed).
    A big JPEG is decoded at a reduced scale no smaller than its cover fit needs (draft):
    about twice as fast on a 4K photo, and detail finer than the screen is not measured."""
    from PIL import Image
    if hasattr(src, "size") and hasattr(src, "resize"):
        return (src if src.mode == "L" else src.convert("L")), 1.0, tuple(src.size)
    im = Image.open(src)
    try:
        orient = int(im.getexif().get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001
        orient = 1
    sw, sh = im.size
    dw, dh = (sh, sw) if orient in _QUARTER else (sw, sh)
    c = max(out_w / float(dw), out_h / float(dh))
    if c < 1.0 and (im.format or "").upper() == "JPEG":
        try:
            im.draft("L", (int(math.ceil(sw * c)), int(math.ceil(sh * c))))
        except Exception:  # noqa: BLE001 - decoded whole
            pass
    gray = im.convert("L")
    if orient in (2, 3, 4, 5, 6, 7, 8):
        method = {2: Image.FLIP_LEFT_RIGHT, 3: Image.ROTATE_180, 4: Image.FLIP_TOP_BOTTOM,
                  5: Image.TRANSPOSE, 6: Image.ROTATE_270, 7: Image.TRANSVERSE, 8: Image.ROTATE_90}[orient]
        gray = gray.transpose(method)
    return gray, gray.size[0] / float(dw), (dw, dh)


def real_detail(src, out_w: int = OUT_W, out_h: int = OUT_H) -> Tuple[int, int]:
    """
    (w_eff, h_eff): the real detail of a picture (a path or a PIL image), in
    pixels of the whole picture at its stored proportions. Measured on the
    part a cover fit into out_w x out_h shows, at no more than that size, so a
    picture with more detail than the screen can show reads as the screen's
    worth. (0, 0) when it cannot be read. About 0.13 s for a 1920 px photo.
    """
    key = None
    if isinstance(src, (str, os.PathLike)):
        key = _file_key(src, out_w, out_h, PSNR_DB)
        if key is None:
            return 0, 0
        with _LOCK:
            if key in _CACHE:
                return _CACHE[key]
    t0 = time.time()
    try:
        gray, scale, (w, h) = _load(src, out_w, out_h)
        work, k = _work(gray, out_w, out_h)
        f = fraction(work) * k * scale
    except Exception as e:  # noqa: BLE001 - unreadable: no verdict
        print(f"[sharpness] {os.path.basename(str(src))[:60]}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return 0, 0
    finally:
        _spent(time.time() - t0)
    got = (max(1, int(round(w * f))), max(1, int(round(h * f))))
    if key is not None:
        with _LOCK:
            if len(_CACHE) > 4096:
                _CACHE.clear()
            _CACHE[key] = got
    return got


# --------------------------------------------------------------------------- #
# Pictures
# --------------------------------------------------------------------------- #

def picture_on() -> bool:
    return bool(getattr(config, "PICTURE_SHARPNESS_CHECK", True))


# A looser limit while it is set (2026-10-09): media sets PERSON_ERA_MAX_MAGNIFICATION while a line about a person
# from before video existed searches photos of them (src/personera.py) - an archive print is soft by nature: the
# Obama biography's Punahou and Occidental photos measured 2.0-2.9x and were all thrown away at 1.86x.
CAP: contextvars.ContextVar = contextvars.ContextVar("sharpness_cap", default=None)


def limit() -> float:
    cap = CAP.get()
    if cap:
        return float(cap)
    return float(getattr(config, "MAX_PICTURE_MAGNIFICATION", 1.45) or 0.0)


def possible(width, height, zoom: Optional[float] = None) -> bool:
    """False when a picture of this stored size could not pass full screen even if every pixel
    were real (a search result's reported size: no need to download it). True when unknown."""
    try:
        width, height = int(float(width or 0)), int(float(height or 0))
    except (TypeError, ValueError):
        return True
    if not picture_on() or width <= 0 or height <= 0 or limit() <= 0:
        return True
    z = planned_zoom() if zoom is None else zoom
    return screen_magnification(width, height, zoom=z) <= limit() + 1e-9


def min_size(zoom: Optional[float] = None) -> Tuple[int, int]:
    """The smallest stored size (w, h) that can pass full screen (both sides at least these):
    1536 x 864 with the defaults - what a search is asked for first."""
    z = planned_zoom() if zoom is None else zoom
    lim = limit() or 1.0
    return int(math.ceil(OUT_W * z / lim)), int(math.ceil(OUT_H * z / lim))


def picture_check(path: str, zoom: Optional[float] = None, cap: Optional[float] = None) -> dict:
    """
    {"ok", "magnification", "detail": [w_eff, h_eff], "size": [w, h], "why"}
    for a picture shown full screen, with the move's zoom (default: the one
    the planner will most likely give it). ok is True when the check is off,
    when the file cannot be measured (a check never drops what it cannot
    read), or when the screen enlarges its real detail no more than
    MAX_PICTURE_MAGNIFICATION (`cap`: another limit for this picture - a period photo of a person, CAP).
    """
    out = {"ok": True, "magnification": None, "detail": None, "size": None, "why": ""}
    lim = float(cap) if cap else limit()
    if not picture_on() or not path or lim <= 0:
        return out
    w_eff, h_eff = real_detail(path)
    if not w_eff:
        return out
    try:
        from PIL import Image
        with Image.open(path) as im:
            size = list(im.size)
    except Exception:  # noqa: BLE001
        size = None
    z = planned_zoom() if zoom is None else float(zoom)
    mag = screen_magnification(w_eff, h_eff, zoom=z)
    out.update(magnification=round(mag, 2), detail=[w_eff, h_eff], size=size)
    if mag > lim + 1e-9:
        out["ok"] = False
        out["why"] = (f"a blurry picture: real detail about {w_eff}x{h_eff}"
                      + (f" of {size[0]}x{size[1]}" if size else "")
                      + f", blown up {mag:.1f}x on screen (limit {lim:.2f}x)")
    _note("pictures", path, not out["ok"])
    return out


def rank_bonus(asset) -> float:
    """A bounded addition to a passed candidate's score for its measured real detail (its
    score_parts "magnification" or "lines"): 0 at the limit, DETAIL_BONUS at full detail."""
    parts = getattr(asset, "score_parts", None) or {}
    kind = getattr(asset, "kind", "")
    try:
        if kind == "image" and picture_on() and parts.get("magnification"):
            best, worst = planned_zoom(), limit()
            share = (worst - float(parts["magnification"])) / max(1e-6, worst - best)
        elif kind == "video" and clip_on() and parts.get("lines"):
            worst, best = min_clip_lines() * CLIP_SLACK, OUT_H * 0.9
            share = (float(parts["lines"]) - worst) / max(1e-6, best - worst)
        else:
            return 0.0
    except (TypeError, ValueError):
        return 0.0
    return DETAIL_BONUS * max(0.0, min(1.0, share))


# --------------------------------------------------------------------------- #
# Clips
# --------------------------------------------------------------------------- #

def clip_on() -> bool:
    return bool(getattr(config, "CLIP_SHARPNESS_CHECK", True))


def min_clip_lines() -> int:
    return int(getattr(config, "MIN_CLIP_REAL_HEIGHT", 720) or 0)


def _probe(path: str, timeout: float = 30) -> Tuple[int, int, float]:
    """(width, height, seconds) of a clip's picture (a file or a link); zeros when unreadable."""
    key = _file_key(path, "probe")
    if key is not None:
        with _LOCK:
            if key in _PROBES:
                return _PROBES[key]
    cmd = ["ffprobe", "-v", "error"]
    if str(path).startswith(("http://", "https://")):
        cmd += ["-rw_timeout", str(int(timeout * 1_000_000))]
    cmd += ["-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
            "-of", "csv=p=0:s=x", str(path)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        lines = [l.strip() for l in (p.stdout or "").splitlines() if l.strip()]
        w, h = (int(x) for x in lines[0].split("x")[:2])
        try:
            secs = float(lines[1]) if len(lines) > 1 else 0.0
        except ValueError:
            secs = 0.0
        got = (w, h, secs)
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0, 0, 0.0
    if key is not None:
        with _LOCK:
            if len(_PROBES) > 4096:
                _PROBES.clear()
            _PROBES[key] = got
    return got


def _frame(path: str, at: float, fw: int, fh: int, scaled: bool, timeout: float = FRAME_SECONDS):
    """One grey frame of a clip at `at` seconds (fw x fh), or None."""
    import numpy as np
    from PIL import Image
    cmd = ["ffmpeg", "-v", "error"]
    if str(path).startswith(("http://", "https://")):
        cmd += ["-rw_timeout", str(int(timeout * 1_000_000))]
    vf = f"scale={fw}:{fh}:flags=lanczos,format=gray" if scaled else "format=gray"
    cmd += ["-ss", f"{max(0.0, at):.3f}", "-i", str(path), "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    buf = p.stdout or b""
    if len(buf) < fw * fh:
        return None
    return Image.fromarray(np.frombuffer(buf[:fw * fh], dtype=np.uint8).reshape(fh, fw))


def clip_frames(path: str, n: int = 3, out_w: int = OUT_W, out_h: int = OUT_H,
                size: Optional[Tuple[int, int, float]] = None) -> list:
    """Up to n grey frames of a clip (a file or a link), one from the middle of each of n equal
    parts, at their own size or the output frame's when bigger; [] when unreadable."""
    return list(_frames(path, n, out_w, out_h, size))


def _frames(path: str, n: int, out_w: int, out_h: int, size: Optional[Tuple[int, int, float]] = None):
    w, h, secs = size or _probe(path)
    if not w or not h:
        return
    k = min(1.0, out_w / float(w), out_h / float(h))
    fw, fh = (max(2, int(round(w * k / 2)) * 2), max(2, int(round(h * k / 2)) * 2)) if k < 1.0 else (w, h)
    for at in ([secs * (i + 0.5) / n for i in range(n)] if secs > 0 else [0.0]):
        fr = _frame(path, at, fw, fh, k < 1.0)
        if fr is not None:
            yield fr


def clip_detail(path: str, n: int = 3, out_w: int = OUT_W, out_h: int = OUT_H,
                enough: float = 0.0) -> Tuple[int, int]:
    """
    (w_eff, h_eff) of a clip (a file or a link): the best real detail of n of
    its frames, in the clip's own pixels. A dark or flat frame (a fade, a night
    sky) is left out. With `enough` (lines), it stops at the first frame that
    holds that much: the best so far, never less than `enough`. (0, 0) when no
    frame can be read.
    """
    key = _file_key(path, "clip", n, out_w, out_h, PSNR_DB)
    if key is not None:
        with _LOCK:
            hit = _CACHE.get(key)
        # A measure that stopped early holds for any need it met; one of every frame, for all.
        if hit is not None and (min(hit[:2]) >= enough or hit[2:] == ("all",)):
            return hit[:2]
    size = _probe(path)
    w, h, _secs = size
    if not w or not h:
        return 0, 0
    import numpy as np
    t0 = time.time()
    best, read_all = 0.0, True
    try:
        for fr in _frames(path, n, out_w, out_h, size):
            a = np.asarray(fr, dtype=np.float32)
            if float(a.mean()) < 26 or float(a.std()) < 6:
                continue
            work, k = _work(fr, out_w, out_h)
            best = max(best, fraction(work) * k * fr.size[0] / float(w))
            if enough and min(w, h) * best >= enough:
                read_all = False
                break
    finally:
        _spent(time.time() - t0)
    got = (int(round(w * best)), int(round(h * best))) if best > 0 else (0, 0)
    if key is not None and best > 0:
        with _LOCK:
            _CACHE[key] = got + (("all",) if read_all else ())
    return got


def same_detail(src: str, copies: Iterable[str]) -> None:
    """Files cut from `src` (its own frames re-encoded: a sequence's shots) carry its measure."""
    if not clip_on():
        return
    key = _file_key(src, "clip", 3, OUT_W, OUT_H, PSNR_DB)
    with _LOCK:
        hit = _CACHE.get(key) if key is not None else None
    if hit is None:
        return
    for p in copies or ():
        k = _file_key(p, "clip", 3, OUT_W, OUT_H, PSNR_DB)
        if k is not None:
            with _LOCK:
                _CACHE[k] = hit


def clip_check(path: str, archive: bool = False, need: Optional[float] = None) -> dict:
    """
    {"ok", "lines", "detail": [w_eff, h_eff], "size": [w, h], "why"} for a
    clip shown full screen: a modern clip whose best frame holds fewer than
    CLIP_SLACK x MIN_CLIP_REAL_HEIGHT lines of real detail (an upscaled upload,
    whatever its file says) is not ok. Archive film is exempt (it only exists
    soft), as is anything that cannot be measured. Frames are read one at a
    time and the first that holds enough ends the check. `need`: the lines a
    clip must hold instead (a period line's broadcast video, PERIOD_REAL_LINES).
    """
    out = {"ok": True, "lines": None, "detail": None, "size": None, "why": ""}
    if not clip_on() or archive or not path or min_clip_lines() <= 0:
        return out
    w, h, _secs = _probe(path)
    if not w or not h:
        return out
    need = float(need) if need else min_clip_lines() * CLIP_SLACK
    w_eff, h_eff = clip_detail(path, enough=need)
    if not w_eff:
        return out
    # The lines the picture fills on screen: a vertical clip is framed to the frame's height.
    lines = min(w_eff, h_eff)
    out.update(lines=int(lines), detail=[w_eff, h_eff], size=[w, h])
    if lines < need:
        out["ok"] = False
        out["why"] = (f"low detail: about {w_eff}x{h_eff} real of {w}x{h} "
                      f"(under {min_clip_lines()} lines - an upscaled upload)")
    _note("clips", path, not out["ok"])
    return out
