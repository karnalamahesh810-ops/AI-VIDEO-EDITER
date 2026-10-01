"""
Smart reframing: a slow, subject-aware move on static footage, and stills
aimed at their subject.

The owner (2026-10-01): "auto-zoom/crop onto the subject (faces, landmarks,
the action) instead of static wide shots - it feels hand-edited". Earlier he
rejected the opposite: a 6% crop on EVERY clip and a 1.24x cut-in halfway
through long ones read as zooming, and news clips must never be cropped to
hide their logo or chyron. So a move here is rare, slow and safe:

* only on a shot whose camera is still (a pan, a drone flight, a push or a
  shaky phone already moves - a second move would fight it);
* only when something clearly is the subject: faces, else what stands out
  (saliency) or what moves in a locked-off frame (the action);
* never past ~1.15x (REFRAME_MAX_SCALE), less on a soft or low-resolution
  picture, never into blur;
* the subject (head and shoulders for a face) stays inside the frame on
  EVERY frame of the move - guaranteed by construction (both end boxes hold
  it, so every box between them does);
* not on short shots (the cut rhythm), not on news footage, a burned-in
  station logo or chyron, a vertical clip framed on its blurred copy, or a
  scene a graphic points into; and not every shot that could move does.

Two halves:

1. detect (the worker, CPU, while the files are still local; time-boxed and
   parallel): media.focus = {box, kind, confidence, motion, ...} per scene.
2. plan: media.reframe = {from, to, kind, ...}: two viewport boxes in frame
   coordinates the renderer interpolates as one CSS transform
   (remotion/src/components/reframe.ts). Pure data in the document, so every
   machine of a split render draws the same frames.

Stills keep their own motion (timeline._IMAGE_MOTIONS); media.reframe on a
still only carries the subject box, and the renderer aims the push, pull or
pan at it instead of the centre (transitions/stillMotion.tsx).

Coordinates: media.focus.box is a fraction of the SOURCE picture; every box
in media.reframe is a fraction of the FRAME as the scene shows it (the
picture cover-fitted to the composition), x/y the top-left corner.

Nothing here can fail a job: any error leaves the scene as it was.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from . import config

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with faster-whisper
    np = None

_STILL_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
ANALYSIS_W = 640            # faces and saliency are found on frames this wide
MOTION_W, MOTION_H = 320, 180
_LOCK = threading.Lock()
_FACE: Dict[str, object] = {"loaded": False, "error": ""}
STATS = {"scenes": 0, "detected": 0, "faces": 0, "moving": 0, "overlay": 0, "planned": 0,
         "stillsAimed": 0, "skippedTime": 0, "failed": 0, "seconds": 0.0}


# --------------------------------------------------------------------------- #
# Frames
# --------------------------------------------------------------------------- #

def _probe(path: str) -> Tuple[int, int, float]:
    """(width, height, seconds) of a video as it decodes (rotation applied)."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate:format=duration",
             "-of", "default=nw=1", path],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return 0, 0, 0.0
    vals: Dict[str, str] = {}
    for line in (p.stdout or "").splitlines():
        k, _, v = line.partition("=")
        vals.setdefault(k.strip().lower(), v.strip())
    try:
        w, h = int(vals.get("width") or 0), int(vals.get("height") or 0)
    except ValueError:
        return 0, 0, 0.0
    try:
        rot = abs(int(float(vals.get("rotation") or vals.get("tag:rotate") or 0))) % 180
    except ValueError:
        rot = 0
    if rot == 90:
        w, h = h, w
    try:
        seconds = float(vals.get("duration") or 0)
    except ValueError:
        seconds = 0.0
    return w, h, seconds if math.isfinite(seconds) else 0.0


def _even(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def _decode(path: str, seconds: float, fps: float, w: int, h: int, start: float = 0.0,
            pix: str = "rgb24", timeout: float = 30.0) -> list:
    """Frames of `path` from `start` for `seconds` at `fps`, as uint8 arrays (h, w[, 3])."""
    ch = 3 if pix == "rgb24" else 1
    vf = f"fps={fps:.4f},scale={w}:{h}:flags=area"
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path, "-t", f"{max(0.1, seconds):.3f}", "-an", "-vf", vf,
            "-pix_fmt", pix, "-f", "rawvideo", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return []
    size = w * h * ch
    buf = p.stdout or b""
    n = len(buf) // size
    shape = (h, w, 3) if ch == 3 else (h, w)
    return [np.frombuffer(buf[i * size:(i + 1) * size], dtype=np.uint8).reshape(shape) for i in range(n)]


def _full_gray(path: str, at: float, w: int, h: int, timeout: float = 20.0):
    """One frame at the file's own resolution, grey (for the sharpness measure)."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, at):.3f}", "-i", path,
           "-frames:v", "1", "-an", "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    buf = p.stdout or b""
    if len(buf) < w * h:
        return None
    return np.frombuffer(buf[:w * h], dtype=np.uint8).reshape(h, w)


def _resize(a, w: int, h: int):
    from PIL import Image
    mode = "RGB" if a.ndim == 3 else "L"
    return np.asarray(Image.fromarray(a, mode).resize((w, h), Image.BILINEAR))


def _gray(rgb):
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32)


# --------------------------------------------------------------------------- #
# Faces: YuNet (OpenCV Zoo, MIT, 230 KB ONNX) on onnxruntime
# --------------------------------------------------------------------------- #

_YUNET_SIZE = 640
_STRIDES = (8, 16, 32)


def _face_session():
    if _FACE["loaded"]:
        return _FACE.get("session")
    with _LOCK:
        if _FACE["loaded"]:
            return _FACE.get("session")
        _FACE["loaded"] = True
        path = config.FACE_MODEL
        if not os.path.isfile(path):
            _FACE["error"] = f"no model at {path}"
            return None
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            _FACE["session"] = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
            _FACE["names"] = [o.name for o in _FACE["session"].get_outputs()]
            _FACE["input"] = _FACE["session"].get_inputs()[0].name
            print(f"[reframe] face model loaded from {path}", flush=True)
        except Exception as e:  # noqa: BLE001 - no runtime: saliency only
            _FACE["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            _FACE.pop("session", None)
            print(f"[reframe] faces off: {_FACE['error']}", flush=True)
    return _FACE.get("session")


def faces_available() -> bool:
    return np is not None and _face_session() is not None


def _nms(boxes: list, iou_max: float = 0.3) -> list:
    """Greedy non-maximum suppression over [x, y, w, h, score, ...] rows."""
    out: list = []
    for b in sorted(boxes, key=lambda r: -r[4]):
        if all(_iou(b, k) <= iou_max for k in out):
            out.append(b)
    return out


def _iou(a, b) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax1, bx1) - max(a[0], b[0]))
    ih = max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _yunet(rgb, long_side: int, threshold: float) -> list:
    """Faces in one frame at one scale: [x, y, w, h, score, eye_y] as fractions of the frame."""
    sess = _face_session()
    if sess is None:
        return []
    H, W = rgb.shape[:2]
    s = long_side / float(max(H, W))
    w2, h2 = max(8, int(round(W * s))), max(8, int(round(H * s)))
    canvas = np.zeros((_YUNET_SIZE, _YUNET_SIZE, 3), np.float32)
    canvas[:h2, :w2] = _resize(rgb, w2, h2)[..., ::-1]          # BGR, 0-255, as OpenCV feeds it
    outs = dict(zip(_FACE["names"], sess.run(None, {_FACE["input"]: canvas.transpose(2, 0, 1)[None]})))
    found = []
    for stride in _STRIDES:
        cols = _YUNET_SIZE // stride
        cls = np.clip(outs[f"cls_{stride}"][0, :, 0], 0, 1)
        obj = np.clip(outs[f"obj_{stride}"][0, :, 0], 0, 1)
        score = np.sqrt(cls * obj)
        for i in np.where(score >= threshold)[0]:
            r, c = divmod(int(i), cols)
            bb = outs[f"bbox_{stride}"][0, i]
            kp = outs[f"kps_{stride}"][0, i]
            cx, cy = (c + bb[0]) * stride, (r + bb[1]) * stride
            bw, bh = math.exp(float(bb[2])) * stride, math.exp(float(bb[3])) * stride
            eye_y = ((kp[1] + r) * stride + (kp[3] + r) * stride) / 2.0
            found.append([(cx - bw / 2) / w2, (cy - bh / 2) / h2, bw / w2, bh / h2, float(score[i]), eye_y / h2])
    return found


def find_faces(rgb, threshold: float = 0.6) -> list:
    """Faces at two scales (small faces at 640 px, close-ups at 320 px), merged."""
    if rgb is None or not faces_available():
        return []
    try:
        found = _yunet(rgb, 640, threshold) + _yunet(rgb, 320, threshold)
    except Exception as e:  # noqa: BLE001 - a model error is "no face"
        print(f"[reframe] face pass failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return []
    keep = []
    for f in _nms(found, 0.35):
        x, y, w, h = f[:4]
        if w <= 0 or h <= 0 or x + w < 0.02 or y + h < 0.02 or x > 0.98 or y > 0.98:
            continue
        keep.append([max(0.0, x), max(0.0, y), min(w, 1 - max(0.0, x)), min(h, 1 - max(0.0, y)), f[4], f[5]])
    return keep


def _face_tracks(per_frame: List[list], min_h: float) -> list:
    """
    Faces seen in most of the sampled frames (a person, not a flicker of
    texture): [(union box, mean score, eye line, frames seen)], biggest first.
    """
    n = len(per_frame)
    tracks: list = []
    for k, faces in enumerate(per_frame):
        for f in faces:
            if f[3] < min_h:
                continue
            best, best_d = None, 0.0
            for t in tracks:
                last = t["last"]
                d = _iou(f, last)
                near = abs((f[0] + f[2] / 2) - (last[0] + last[2] / 2)) < max(f[2], last[2]) * 1.2 and \
                    abs((f[1] + f[3] / 2) - (last[1] + last[3] / 2)) < max(f[3], last[3]) * 1.2
                if (d > 0.1 or near) and t["frame"] != k and d >= best_d:
                    best, best_d = t, d
            if best is None:
                tracks.append({"boxes": [f], "last": f, "frame": k})
            else:
                best["boxes"].append(f)
                best["last"] = f
                best["frame"] = k
    out = []
    for t in tracks:
        seen = len(t["boxes"])
        if seen < max(1, math.ceil(n * 0.6)):
            continue
        bs = t["boxes"]
        x0 = min(b[0] for b in bs)
        y0 = min(b[1] for b in bs)
        x1 = max(b[0] + b[2] for b in bs)
        y1 = max(b[1] + b[3] for b in bs)
        h_mean = sum(b[3] for b in bs) / seen
        out.append({"box": [x0, y0, x1 - x0, y1 - y0], "score": sum(b[4] for b in bs) / seen,
                    "eye": sum(b[5] for b in bs) / seen, "seen": seen, "h": h_mean})
    out.sort(key=lambda t: -t["h"])
    return out


# --------------------------------------------------------------------------- #
# What stands out: saliency, and the action on a locked-off shot
# --------------------------------------------------------------------------- #

def _gauss_kernel(sigma: float):
    r = max(1, int(round(sigma * 3)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-(x * x) / (2 * sigma * sigma))
    return k / k.sum()


def _blur(a, sigma: float):
    """Separable Gaussian blur (edge-padded)."""
    k = _gauss_kernel(sigma)
    r = len(k) // 2
    p = np.pad(a, ((0, 0), (r, r)), mode="edge")
    a = sum(k[i] * p[:, i:i + a.shape[1]] for i in range(len(k)))
    p = np.pad(a, ((r, r), (0, 0)), mode="edge")
    return sum(k[i] * p[i:i + a.shape[0], :] for i in range(len(k)))


def _spectral_residual(g):
    """Hou & Zhang's spectral residual saliency on a small grey image."""
    F = np.fft.fft2(g)
    log_a = np.log(np.abs(F) + 1e-6)
    pad = np.pad(log_a, 1, mode="wrap")
    avg = sum(pad[dy:dy + g.shape[0], dx:dx + g.shape[1]] for dy in range(3) for dx in range(3)) / 9.0
    s = np.abs(np.fft.ifft2(np.exp(log_a - avg + 1j * np.angle(F)))) ** 2
    return _blur(s.astype(np.float32), max(1.0, g.shape[1] / 28.0))


def _lab(rgb):
    """sRGB uint8 -> CIE Lab (D65), float32."""
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    x = (c[..., 0] * 0.4124 + c[..., 1] * 0.3576 + c[..., 2] * 0.1805) / 0.95047
    y = c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722
    z = (c[..., 0] * 0.0193 + c[..., 1] * 0.1192 + c[..., 2] * 0.9505) / 1.08883

    def f(t):
        return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16.0 / 116.0)
    fx, fy, fz = f(x), f(y), f(z)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1).astype(np.float32)


def _contrast(rgb):
    """Achanta's frequency-tuned saliency: how far each (blurred) colour is from the picture's mean."""
    lab = _lab(rgb)
    sm = np.stack([_blur(lab[..., i], 1.5) for i in range(3)], axis=-1)
    d = sm - lab.reshape(-1, 3).mean(axis=0)
    return (d * d).sum(axis=-1)


def _norm01(a):
    lo, hi = float(np.percentile(a, 2)), float(a.max())
    if hi - lo < 1e-9:
        return np.zeros_like(a, dtype=np.float32)
    return np.clip((a - lo) / (hi - lo), 0, 1).astype(np.float32)


def saliency_map(rgb, grid_w: int = 80):
    """What stands out in a frame, on a small grid (grid_w wide), 0..1."""
    H, W = rgb.shape[:2]
    gh = max(8, int(round(grid_w * H / float(W))))
    small = _resize(rgb, grid_w, gh)
    sr = _norm01(_spectral_residual(_gray(_resize(rgb, 64, max(8, int(round(64 * H / float(W))))))))
    sr = _resize((sr * 255).astype(np.uint8), grid_w, gh).astype(np.float32) / 255.0
    ft = _norm01(_contrast(small))
    return _norm01(0.5 * sr + 0.5 * ft)


def _components(mask) -> list:
    """8-connected components of a small boolean grid: lists of (y, x)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, comp = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
        comps.append(comp)
    return comps


def subject_from_map(m) -> Optional[dict]:
    """
    The region of a 0..1 map that holds most of what stands out, or None
    when nothing does (an even landscape, texture everywhere):
    {"box": [x, y, w, h] fractions, "share": mass inside / all, "area": box
    area, "confidence"}.
    """
    h, w = m.shape
    floor = float(np.percentile(m, 55))
    v = np.clip(m - floor, 0, None)
    total = float(v.sum())
    if total <= 1e-6:
        return None
    mask = v >= 0.35 * float(v.max())
    comps = _components(mask)
    if not comps:
        return None
    scored = sorted(((float(sum(v[y, x] for y, x in c)), c) for c in comps), key=lambda t: -t[0])
    top_mass, top = scored[0]
    keep = list(top)
    ys0, xs0 = [p[0] for p in top], [p[1] for p in top]
    bx0, bx1, by0, by1 = min(xs0), max(xs0), min(ys0), max(ys0)
    # A second blob close by and nearly as strong is the same subject (a
    # boat and its wake, a dam's two halves); a far one makes the box wide
    # and the confidence low, which is the honest answer.
    for mass, comp in scored[1:4]:
        if mass < 0.45 * top_mass:
            break
        ys, xs = [p[0] for p in comp], [p[1] for p in comp]
        gap_x = max(0, max(min(xs) - bx1, bx0 - max(xs))) / w
        gap_y = max(0, max(min(ys) - by1, by0 - max(ys))) / h
        if gap_x < 0.12 and gap_y < 0.12:
            keep += comp
            bx0, bx1 = min(bx0, min(xs)), max(bx1, max(xs))
            by0, by1 = min(by0, min(ys)), max(by1, max(ys))
    box = [bx0 / w, by0 / h, (bx1 + 1 - bx0) / w, (by1 + 1 - by0) / h]
    inside = float(v[by0:by1 + 1, bx0:bx1 + 1].sum())
    share = inside / total
    area = box[2] * box[3]
    # Concentrated (most of the mass in a small box) = a clear subject.
    confidence = max(0.0, min(1.0, share * (1.0 - area) * 1.6 - 0.25))
    return {"box": box, "share": round(share, 3), "area": round(area, 3), "confidence": round(confidence, 3)}


# --------------------------------------------------------------------------- #
# The camera's own move: block phase correlation
# --------------------------------------------------------------------------- #

_BLOCK = 64
_BX = (0, 64, 128, 192, 256)
_BY = (0, 58, 116)
_WIN = None


def _window():
    global _WIN
    if _WIN is None:
        _WIN = np.outer(np.hanning(_BLOCK), np.hanning(_BLOCK)).astype(np.float32)
    return _WIN


def _spectra(g):
    blocks = np.stack([g[y:y + _BLOCK, x:x + _BLOCK] for y in _BY for x in _BX]).astype(np.float32)
    blocks -= blocks.mean(axis=(1, 2), keepdims=True)
    tex = (np.abs(np.diff(blocks, axis=2)).mean(axis=(1, 2)) + np.abs(np.diff(blocks, axis=1)).mean(axis=(1, 2)))
    return np.fft.fft2(blocks * _window()), tex


_CENTRES = None


def _centres():
    global _CENTRES
    if _CENTRES is None:
        _CENTRES = np.array([(x + _BLOCK / 2 - MOTION_W / 2, y + _BLOCK / 2 - MOTION_H / 2)
                             for y in _BY for x in _BX], np.float32)
    return _CENTRES


def _pair_motion(fa, fb, tex):
    """Global (tx, ty, k) between two frames' block spectra, or None when it cannot be told."""
    r = np.conj(fa) * fb
    r /= np.abs(r) + 1e-6
    corr = np.fft.ifft2(r).real
    n = corr.shape[0]
    flat = corr.reshape(n, -1)
    idx = flat.argmax(axis=1)
    peak = flat.max(axis=1)
    py, px = np.unravel_index(idx, (_BLOCK, _BLOCK))
    rows = np.arange(n)

    def sub(c, l, r_):
        den = l - 2 * c + r_
        return np.where(np.abs(den) > 1e-9, 0.5 * (l - r_) / np.where(np.abs(den) > 1e-9, den, 1), 0.0)
    c0 = corr[rows, py, px]
    sx = sub(c0, corr[rows, py, (px - 1) % _BLOCK], corr[rows, py, (px + 1) % _BLOCK])
    sy = sub(c0, corr[rows, (py - 1) % _BLOCK, px], corr[rows, (py + 1) % _BLOCK, px])
    dx = np.where(px > _BLOCK // 2, px - _BLOCK, px) + np.clip(sx, -0.5, 0.5)
    dy = np.where(py > _BLOCK // 2, py - _BLOCK, py) + np.clip(sy, -0.5, 0.5)
    ok = (peak > 0.08) & (tex > 1.2)
    if ok.sum() < 5:
        return None
    c = _centres()
    for _ in range(2):
        w = peak[ok]
        a = np.zeros((2 * int(ok.sum()), 3), np.float64)
        b = np.zeros(2 * int(ok.sum()), np.float64)
        ww = np.repeat(w, 2)
        a[0::2, 0] = 1
        a[0::2, 2] = c[ok, 0]
        a[1::2, 1] = 1
        a[1::2, 2] = c[ok, 1]
        b[0::2] = dx[ok]
        b[1::2] = dy[ok]
        sol, *_ = np.linalg.lstsq(a * ww[:, None], b * ww, rcond=None)
        err = np.hypot(dx - (sol[0] + sol[2] * c[:, 0]), dy - (sol[1] + sol[2] * c[:, 1]))
        inliers = ok & (err < 1.5)
        if inliers.sum() < 5 or inliers.sum() == ok.sum():
            ok = inliers if inliers.sum() >= 5 else ok
            break
        ok = inliers
    if ok.sum() < 5:
        return None
    return float(sol[0]), float(sol[1]), float(sol[2]), float(peak[ok].mean()), int(ok.sum())


def camera_motion(grays: list, dt: float) -> dict:
    """
    How the camera itself moves over grey frames `dt` seconds apart (320x180):
    pan in frame widths/heights, zoom as a share, shake, cuts.
    {"moving": bool, "known": share of pairs measured, "pan": net pan,
     "panRate": per second, "zoom": net zoom, "shake": jitter, "cut": bool}
    """
    out = {"moving": True, "known": 0.0, "pan": 0.0, "panRate": 0.0, "zoom": 0.0, "shake": 0.0, "cut": False,
           "pairs": max(0, len(grays) - 1)}
    if len(grays) < 3:
        return out
    specs = [_spectra(g) for g in grays]
    txs, tys, ks = [], [], []
    unknown = 0
    for (fa, ta), (fb, tb), ga, gb in zip(specs, specs[1:], grays, grays[1:]):
        m = _pair_motion(fa, fb, np.minimum(ta, tb))
        raw = float(np.abs(ga - gb).mean())
        if m is None:
            unknown += 1
            if raw > 22.0:
                out["cut"] = True
            continue
        tx, ty, k, peak, n = m
        if raw > 22.0 and peak < 0.12:
            out["cut"] = True
        txs.append(tx / MOTION_W)
        tys.append(ty / MOTION_H)
        ks.append(k)
    pairs = len(grays) - 1
    out["known"] = round(1.0 - unknown / pairs, 3)
    if not txs:
        return out
    tx, ty, k = np.array(txs), np.array(tys), np.array(ks)
    net = math.hypot(float(tx.sum()), float(ty.sum()))
    rate = float(np.median(np.hypot(tx, ty))) / dt
    zoom = float(np.exp(k.sum()) - 1.0)
    # Shake: the jitter left after the steady drift is removed.
    if len(tx) >= 3:
        jx = tx - np.convolve(tx, np.ones(3) / 3, mode="same")
        jy = ty - np.convolve(ty, np.ones(3) / 3, mode="same")
        shake = float(np.sqrt(np.mean(jx[1:-1] ** 2 + jy[1:-1] ** 2))) if len(tx) > 2 else 0.0
    else:
        shake = 0.0
    out.update(pan=round(net, 4), panRate=round(rate, 4), zoom=round(zoom, 4), shake=round(shake, 4))
    out["moving"] = bool(out["cut"] or out["known"] < MOTION_KNOWN_MIN or net > STATIC_PAN or rate > STATIC_PAN_RATE
                         or abs(zoom) > STATIC_ZOOM or shake > STATIC_SHAKE)
    return out


# A shot counts as locked off ("static") within these, over its shown stretch.
STATIC_PAN = 0.025          # net drift, a share of the frame
STATIC_PAN_RATE = 0.012     # per second
STATIC_ZOOM = 0.025         # the camera's own zoom over the stretch
STATIC_SHAKE = 0.004        # frame-to-frame jitter
MOTION_KNOWN_MIN = 0.7      # pairs that could be measured


def action_map(grays: list, grid_w: int = 80):
    """Where things move inside a locked-off frame: mean |difference| between frames, 0..1 on the grid."""
    if len(grays) < 2:
        return None
    gh = max(8, int(round(grid_w * MOTION_H / float(MOTION_W))))
    acc = None
    for a, b in zip(grays, grays[1:]):
        d = np.abs(_blur(a, 1.0) - _blur(b, 1.0))
        acc = d if acc is None else acc + d
    acc = acc / (len(grays) - 1)
    small = _resize(np.clip(acc * 8, 0, 255).astype(np.uint8), grid_w, gh).astype(np.float32)
    return _norm01(_blur(small, 1.2)), float(acc.mean())


# --------------------------------------------------------------------------- #
# Burned-in logos, chyrons and tickers (never cropped: the owner's rule)
# --------------------------------------------------------------------------- #

def _text_rows(g) -> list:
    edges = np.abs(np.diff(g.astype(np.int16), axis=1)) > 48
    return [i for i, c in enumerate(edges.sum(axis=1)) if c > g.shape[1] * 0.12]


def _longest_run(rows: list) -> int:
    run = best = 1 if rows else 0
    for a, b in zip(rows, rows[1:]):
        run = run + 1 if b - a <= 2 else 1
        best = max(best, run)
    return best


def burned_overlay(grays: list) -> bool:
    """
    A station bug, chyron, ticker or caption band: text-like rows near the
    top or bottom that stay put across the frames, or a static corner logo
    over a moving picture (filters._corner_watermark).
    """
    if not grays:
        return False
    hits = 0
    for g in grays[:: max(1, len(grays) // 4)][:4]:
        h = g.shape[0]
        rows = _text_rows(g)
        low = [r for r in rows if r >= h * 0.66]
        top = [r for r in rows if r <= h * 0.14]
        if _longest_run(low) >= 3 or _longest_run(top) >= 3:
            hits += 1
    sampled = len(grays[:: max(1, len(grays) // 4)][:4])
    if hits >= max(2, (sampled + 1) // 2):
        return True
    try:
        from .filters import _corner_watermark
        picks = grays[:: max(1, len(grays) // 5)][:5]
        return bool(len(picks) >= 3 and _corner_watermark([p.astype(np.uint8) for p in picks], np))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# How sharp the picture really is
# --------------------------------------------------------------------------- #

def effective_lines(g) -> int:
    """
    The picture's real detail, in lines: where its spectrum falls to the
    noise floor. A 720p clip upscaled to 1080 (or a soft phone video) has
    nothing above 720/1080 of the file's Nyquist frequency, however many
    pixels the file has. 0 when it cannot be told.
    """
    if g is None:
        return 0
    h, w = g.shape
    side = 1 << int(math.log2(max(64, min(h, w, 1024))))
    y0, x0 = (h - side) // 2, (w - side) // 2
    a = g[y0:y0 + side, x0:x0 + side].astype(np.float32)
    a -= a.mean()
    win = np.outer(np.hanning(side), np.hanning(side)).astype(np.float32)
    p = np.abs(np.fft.fftshift(np.fft.fft2(a * win))) ** 2
    yy, xx = np.indices(p.shape)
    r = np.hypot(yy - side / 2, xx - side / 2) / side            # cycles per pixel, 0..~0.7
    bins = np.clip((r / 0.5 * 64).astype(int), 0, 80)
    radial = np.bincount(bins.ravel(), p.ravel()) / np.maximum(np.bincount(bins.ravel()), 1)
    radial = radial[:64]
    if radial[1:8].mean() <= 0:
        return 0
    floor = float(np.median(radial[58:64]))
    lr = np.log10(radial[1:] + 1e-12)
    ref = float(np.log10(floor + 1e-12))
    # The highest frequency still clearly (6 dB+) above the floor.
    above = np.where(lr > ref + 0.6)[0]
    if not len(above):
        return 0
    cutoff = (int(above.max()) + 2) / 64.0 * 0.5               # cycles per pixel
    return int(round(min(1.0, cutoff / 0.5) * min(h, w if w < h else h)))
