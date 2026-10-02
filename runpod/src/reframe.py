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
            cx, cy = (c + float(bb[0])) * stride, (r + float(bb[1])) * stride
            bw, bh = math.exp(float(bb[2])) * stride, math.exp(float(bb[3])) * stride
            eye_y = ((float(kp[1]) + r) * stride + (float(kp[3]) + r) * stride) / 2.0
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
# The main object: U2-Net-p (Apache-2.0, 4.6 MB ONNX) salient-object maps
# --------------------------------------------------------------------------- #

_U2: Dict[str, object] = {"loaded": False, "error": ""}
_MEAN = (0.485, 0.456, 0.406)
_STD = (0.229, 0.224, 0.225)


def _u2_session():
    if _U2["loaded"]:
        return _U2.get("session")
    with _LOCK:
        if _U2["loaded"]:
            return _U2.get("session")
        _U2["loaded"] = True
        path = config.SALIENCY_MODEL
        if not os.path.isfile(path):
            _U2["error"] = f"no model at {path}"
            return None
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            opts.inter_op_num_threads = 1
            _U2["session"] = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
            _U2["input"] = _U2["session"].get_inputs()[0].name
            print(f"[reframe] salient-object model loaded from {path}", flush=True)
        except Exception as e:  # noqa: BLE001 - no runtime: the pixel saliency stands in
            _U2["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            _U2.pop("session", None)
            print(f"[reframe] salient-object model off: {_U2['error']}", flush=True)
    return _U2.get("session")


def object_map(rgb, grid_w: int = 80):
    """
    Where the main object is (0..1 probability on a grid_w-wide grid of the
    frame's own aspect), or None without the model. Trained on salient-object
    photos: a dam, a boat, a person, a ruin light up; an even landscape stays
    dark - which is the honest "no subject" this needs.
    """
    sess = _u2_session()
    if sess is None:
        return None
    a = _resize(rgb, 320, 320).astype(np.float32)
    a = a / max(1e-6, float(a.max()))
    a = (a - np.array(_MEAN, np.float32)) / np.array(_STD, np.float32)
    try:
        out = sess.run(None, {_U2["input"]: a.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    except Exception as e:  # noqa: BLE001
        print(f"[reframe] salient-object pass failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    H, W = rgb.shape[:2]
    gh = max(8, int(round(grid_w * H / float(W))))
    return _resize((np.clip(out, 0, 1) * 255).astype(np.uint8), grid_w, gh).astype(np.float32) / 255.0


def subject_from_objects(p) -> Optional[dict]:
    """
    The main object's box from an object_map, or None when the map holds no
    clear object: {"box", "share", "area", "peak", "confidence"}.
    """
    if p is None:
        return None
    peak = float(p.max())
    if peak < 0.6:
        return None
    h, w = p.shape
    mask = p >= 0.5
    if mask.mean() < 0.002:
        return None
    comps = _components(mask)
    scored = sorted(((float(sum(p[y, x] for y, x in c)), c) for c in comps), key=lambda t: -t[0])
    total = sum(m for m, _ in scored)
    top_mass, top = scored[0]
    ys0, xs0 = [q[0] for q in top], [q[1] for q in top]
    bx0, bx1, by0, by1 = min(xs0), max(xs0), min(ys0), max(ys0)
    mass = top_mass
    for m, comp in scored[1:6]:
        if m < 0.3 * top_mass:
            break
        ys, xs = [q[0] for q in comp], [q[1] for q in comp]
        gap_x = max(0, max(min(xs) - bx1, bx0 - max(xs))) / w
        gap_y = max(0, max(min(ys) - by1, by0 - max(ys))) / h
        if gap_x < 0.1 and gap_y < 0.1:
            bx0, bx1 = min(bx0, min(xs)), max(bx1, max(xs))
            by0, by1 = min(by0, min(ys)), max(by1, max(ys))
            mass += m
    # The soft edge of the object counts as the object: grow the box to
    # where the map is still above 0.25 next to it (never cut a wing tip).
    soft = p >= 0.25
    for _ in range(3):
        grown = False
        if bx0 > 0 and soft[by0:by1 + 1, bx0 - 1].any():
            bx0 -= 1; grown = True  # noqa: E702
        if bx1 < w - 1 and soft[by0:by1 + 1, bx1 + 1].any():
            bx1 += 1; grown = True  # noqa: E702
        if by0 > 0 and soft[by0 - 1, bx0:bx1 + 1].any():
            by0 -= 1; grown = True  # noqa: E702
        if by1 < h - 1 and soft[by1 + 1, bx0:bx1 + 1].any():
            by1 += 1; grown = True  # noqa: E702
        if not grown:
            break
    box = [bx0 / w, by0 / h, (bx1 + 1 - bx0) / w, (by1 + 1 - by0) / h]
    area = box[2] * box[3]
    share = mass / max(total, 1e-6)
    inside = float(p[by0:by1 + 1, bx0:bx1 + 1][mask[by0:by1 + 1, bx0:bx1 + 1]].mean()) if mask[
        by0:by1 + 1, bx0:bx1 + 1].any() else 0.0
    # Sure (bright inside), alone (most of the map's mass) and not the whole
    # frame (a subject filling 70% of it leaves nothing to push toward).
    size = 1.0 if area <= 0.4 else max(0.0, 1.0 - (area - 0.4) / 0.4)
    confidence = max(0.0, min(1.0, inside * share * size))
    return {"box": box, "share": round(share, 3), "area": round(area, 3), "peak": round(peak, 3),
            "confidence": round(confidence, 3)}


def text_in(rgb, box: list) -> bool:
    """A box of the frame that is mostly lettering (burned-in text the object model lit up)."""
    H, W = rgb.shape[:2]
    x0, y0 = int(max(0, box[0]) * W), int(max(0, box[1]) * H)
    x1, y1 = int(min(1, box[0] + box[2]) * W), int(min(1, box[1] + box[3]) * H)
    if x1 - x0 < 12 or y1 - y0 < 6:
        return False
    g = _gray(rgb[y0:y1, x0:x1])
    dens = (np.abs(np.diff(g, axis=1)) > 48).mean(axis=1)
    texty = dens > 0.08
    quiet = ~texty
    # Lettering: rows dense with letter strokes (vertical edges) in a few
    # bands, with nearly empty rows between and around them - a rock face or
    # a forest is dense everywhere, a smooth object nowhere.
    if texty.mean() < 0.12 or quiet.mean() < 0.15:
        return False
    line, gap = float(dens[texty].mean()), float(np.median(dens[quiet]))
    rows = list(np.nonzero(texty)[0])
    bands = 1 + sum(1 for a, b in zip(rows, rows[1:]) if b - a > 2)
    return bool(line >= 0.10 and gap <= 0.25 * line and _longest_run(rows) >= 4 and bands <= 6)


def black_bars(frames: list) -> Dict[str, float]:
    """Letterbox / pillarbox bars (near-black, flat, on every sampled frame): their size per side."""
    out = {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
    if not frames:
        return out
    g = np.stack([_gray(f) for f in frames[:: max(1, len(frames) // 4)][:4]]).max(axis=0)
    h, w = g.shape
    cols = g.max(axis=0)
    rows = g.max(axis=1)
    dark_c = cols < 22
    dark_r = rows < 22

    def run(flags) -> int:
        n = 0
        for f in flags:
            if not f:
                break
            n += 1
        return n
    out["left"] = run(dark_c) / w
    out["right"] = run(dark_c[::-1]) / w
    out["top"] = run(dark_r) / h
    out["bottom"] = run(dark_r[::-1]) / h
    return {k: round(v, 3) for k, v in out.items()}


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

def _longest_run(rows: list) -> int:
    run = best = 1 if rows else 0
    for a, b in zip(rows, rows[1:]):
        run = run + 1 if b - a <= 2 else 1
        best = max(best, run)
    return best


def text_bands(rgb) -> List[Tuple[int, int]]:
    """
    Rows of a frame that read as lines of lettering: dense with letter strokes
    (vertical edges in ANY colour channel - orange captions on grey gravel
    have almost no luma edge), a few rows tall, with quiet rows around them.
    """
    a = rgb.astype(np.int16)
    dens = (np.abs(np.diff(a, axis=1)).max(axis=2) > 48).mean(axis=1)
    h = len(dens)
    texty = np.nonzero(dens > 0.12)[0]
    bands, out = [], []
    for r in texty:
        if bands and r - bands[-1][1] <= 2:
            bands[-1][1] = r
        else:
            bands.append([r, r])
    for a0, b0 in bands:
        tall = b0 - a0 + 1
        if tall < 3 or tall > 0.15 * h:
            continue
        around = np.concatenate([dens[max(0, a0 - 4):a0], dens[b0 + 1:b0 + 5]])
        if around.size and float(around.mean()) > 0.45 * float(dens[a0:b0 + 1].mean()):
            continue                    # texture that goes on: a fence, a forest, a cliff
        out.append((int(a0), int(b0)))
    return out


_LOGO_PROMPTS = ["a TV channel logo", "a watermark logo", "a round emblem badge",
                 "a small logo in the corner of a video", "white text", "a news channel logo"]
_CORNER_SCENE = ["rocks", "a canyon wall", "water", "the sky", "clouds", "trees", "a road", "sand", "a building",
                 "a person", "a mountain", "grass", "a car", "a boat", "a dam", "dirt"]
CORNER_W, CORNER_H = 0.22, 0.30
LOGO_SHARE = 0.5


def corner_logos(rgb) -> List[dict]:
    """
    Corners of a frame that hold a channel bug or watermark (local CLIP:
    the corner reads as a logo rather than as scenery), as source boxes. On
    a locked-off shot a logo cannot be told from the scene by motion, and a
    push would slide it half out of the frame; a move keeps these corners
    whole instead (plan_clip). Measured on the Lake Powell clips: the real
    bugs scored 0.51-0.97, clean corners up to 0.70 - so a clean corner is
    sometimes kept too, which only makes a move smaller.
    """
    try:
        from . import localvision
        if not localvision.available():
            return []
        from PIL import Image
        im = Image.fromarray(rgb)
        W, H = im.size
        cw, ch = int(W * CORNER_W), int(H * CORNER_H)
        boxes = {(0.0, 0.0): (0, 0, cw, ch), (1 - CORNER_W, 0.0): (W - cw, 0, W, ch),
                 (0.0, 1 - CORNER_H): (0, H - ch, cw, H), (1 - CORNER_W, 1 - CORNER_H): (W - cw, H - ch, W, H)}
        prompts = _LOGO_PROMPTS + [f"a photo of {p}" for p in _CORNER_SCENE]
        with localvision._RUN:
            emb = localvision.embed_images([im.crop(b) for b in boxes.values()])
            logits = 100.0 * emb @ localvision.embed_texts(prompts).T
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        share = p[:, :len(_LOGO_PROMPTS)].sum(axis=1)
    except Exception as e:  # noqa: BLE001 - no CLIP: only the motion check below the clip finds logos
        print(f"[reframe] corner check skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return []
    return [{"x": x, "y": y, "w": CORNER_W, "h": CORNER_H, "share": round(float(s), 3)}
            for (x, y), s in zip(boxes, share) if s >= LOGO_SHARE]


def burned_overlay(frames: list, grays: Optional[list] = None) -> bool:
    """
    Somebody else's graphics on the picture - a station bug, chyron, ticker,
    a creator's captions: lines of lettering at the same rows in at least two
    of the sampled frames, or a static corner logo over a moving picture
    (filters._corner_watermark). Such a clip is never cropped (the owner).
    """
    if not frames:
        return False
    picks = frames[:: max(1, len(frames) // 4)][:4]
    found = [text_bands(_resize(p, MOTION_W, max(8, int(round(MOTION_W * p.shape[0] / float(p.shape[1]))))))
             for p in picks]
    for k, bands in enumerate(found):
        for a0, b0 in bands:
            again = sum(1 for other in found[k + 1:] if any(a1 <= b0 + 2 and a0 <= b1 + 2 for a1, b1 in other))
            if again >= 1:
                return True
    if not grays:
        return False
    try:
        from .filters import _corner_watermark
        gp = grays[:: max(1, len(grays) // 5)][:5]
        return bool(len(gp) >= 3 and _corner_watermark([g.astype(np.uint8) for g in gp], np))
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
    return int(round(min(1.0, cutoff / 0.5) * min(h, w)))


def _focus_of(motion: Optional[dict], grays: Optional[list], picks: list) -> dict:
    """
    The subject of a shot from its sampled frames: faces first, else the
    main object (U2-Net), else - without that model - pixel saliency with a
    capped confidence; on a locked-off shot, where things move adds to it.
    """
    tracks = _face_tracks([find_faces(p) for p in picks], FACE_MIN_H) if faces_available() else []
    out: Dict[str, object] = {"faces": len(tracks)}
    if tracks:
        big = tracks[0]["h"]
        keep = [t for t in tracks if t["h"] >= 0.4 * big]
        # Head and shoulders, not the face box: YuNet's box runs from the
        # brows to the chin, and a crop at its edge cuts the head.
        boxes = []
        for t in keep:
            x, y, w, h = t["box"]
            boxes.append([x - FACE_PAD_SIDE * w, y - FACE_PAD_TOP * h, w * (1 + 2 * FACE_PAD_SIDE),
                          h * (1 + FACE_PAD_TOP + FACE_PAD_BOTTOM)])
        box = _union(boxes)
        out.update(box=_clip01(box), kind="face",
                   confidence=round(min(1.0, sum(t["score"] for t in keep) / len(keep)
                                        * min(1.0, sum(t["seen"] for t in keep) / (len(keep) * len(picks)))), 3),
                   eye=round(float(min(t["eye"] for t in keep)), 4),
                   faceBoxes=[[round(float(v), 4) for v in t["box"]] for t in keep])
        return out
    act = None
    if grays and motion and not motion.get("moving"):
        a = action_map(grays)
        # Real movement (a boat, people, a spillway), not sensor noise.
        if a is not None and a[1] > 1.2:
            act = a[0]
    objs = [object_map(p) for p in picks]
    if all(o is not None for o in objs) and objs:
        omap = np.min(np.stack(objs), axis=0) if len(objs) > 1 else objs[0]
        # The object over the whole stretch: where it is in ANY sampled frame
        # (so a crop never loses it), judged by how sure the map is in all.
        union = np.max(np.stack(objs), axis=0) if len(objs) > 1 else objs[0]
        got = subject_from_objects(omap if float(omap.max()) >= 0.6 else union)
        if got:
            got_u = subject_from_objects(union) or got
            box = _union([got["box"], got_u["box"]])
            if any(text_in(p, box) for p in picks):
                out.update(kind="text", confidence=0.0, box=_clip01(box))
                out["overlay"] = True
                return out
            out.update(box=_clip01(box), kind="object", confidence=got["confidence"], share=got["share"],
                       peak=got["peak"])
            return out
        if act is not None:
            got = subject_from_map(act)
            if got and got["confidence"] >= 0.45:
                out.update(box=_clip01(got["box"]), kind="action", confidence=round(got["confidence"] * 0.8, 3))
                return out
        out.update(kind="none", confidence=0.0)
        return out
    # No object model: pixel saliency, never trusted as much (it likes skies).
    maps = [saliency_map(p) for p in picks]
    sal = np.median(np.stack(maps), axis=0) if len(maps) > 1 else maps[0]
    kind = "saliency"
    if act is not None:
        got = subject_from_map(act)
        if got and got["confidence"] >= 0.35:
            sal = _norm01(0.55 * sal + 0.45 * act)
            kind = "action"
    got = subject_from_map(sal)
    if not got:
        out.update(kind="none", confidence=0.0)
        return out
    out.update(box=_clip01(got["box"]), kind=kind, confidence=round(min(0.5, got["confidence"]), 3),
               share=got["share"])
    return out


FACE_MIN_H = 0.035          # a face shorter than this share of the frame is part of the scenery
FACE_PAD_TOP, FACE_PAD_BOTTOM, FACE_PAD_SIDE = 0.6, 0.8, 0.45


def _union(boxes: list) -> list:
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _clip01(b: list) -> dict:
    b = [float(v) for v in b]
    x0, y0 = max(0.0, b[0]), max(0.0, b[1])
    x1, y1 = min(1.0, b[0] + b[2]), min(1.0, b[1] + b[3])
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(max(0.0, x1 - x0), 4), "h": round(max(0.0, y1 - y0), 4)}


def detect_clip(path: str, shown: float, timeout: float = 30.0) -> Optional[dict]:
    """
    media.focus for the first `shown` seconds of a clip (what its scene
    plays), or None when it cannot be read:
    {"box": {x, y, w, h} of the source, "kind": face / saliency / action / none,
     "confidence", "motion": {...camera_motion}, "overlay": bool,
     "lines": real detail in lines, "srcLines": the file's lines, "faces": n}
    """
    if np is None or not path or not os.path.isfile(path):
        return None
    t0 = time.time()
    w, h, dur = _probe(path)
    if not w or not h:
        return None
    shown = max(0.5, min(shown, dur) if dur > 0 else shown)
    aw = ANALYSIS_W
    ah = _even(aw * h / float(w))
    fps = max(3.0, min(8.0, 24.0 / shown))
    frames = _decode(path, shown, fps, aw, ah, timeout=timeout)
    if len(frames) < 3:
        return None
    grays = [_resize(_gray(f).astype(np.uint8), MOTION_W, MOTION_H).astype(np.float32) for f in frames]
    motion = camera_motion(grays, 1.0 / fps)
    bars = black_bars(frames)
    focus: Dict[str, object] = {"motion": motion, "overlay": burned_overlay(frames, grays), "bars": bars,
                                "srcLines": min(w, h), "aspect": round(w / float(h), 4)}
    # A clip that can never take a move (the camera moves, a cut, a station
    # logo, letterbox bars) is not looked at any further: most of a drone-
    # heavy documentary, and the time box is shared.
    why = ("camera moves" if motion["moving"] else "logo or text burned in" if focus["overlay"]
           else "letterbox bars" if max(bars.values()) > 0.02 else "")
    if why:
        focus.update(kind="none", confidence=0.0, why=why, seconds=round(time.time() - t0, 2))
        return focus
    picks = [frames[0], frames[len(frames) // 2], frames[-1]]
    focus.update(_focus_of(motion, grays, picks))
    if focus.get("kind") in ("face", "object", "action"):
        # Only a clip that may take a move pays for these two.
        logos = corner_logos(picks[1])
        if logos:
            focus["logos"] = logos
        focus["lines"] = effective_lines(_full_gray(path, shown / 2.0, w, h))
    focus["seconds"] = round(time.time() - t0, 2)
    return focus


def detect_still(path: str) -> Optional[dict]:
    """media.focus for a photo (no motion, no overlay check: a photo has none of either)."""
    if np is None or not path or not os.path.isfile(path):
        return None
    t0 = time.time()
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            aw = ANALYSIS_W if w >= h else max(64, int(round(ANALYSIS_W * w / float(h))))
            ah = max(64, int(round(aw * h / float(w))))
            rgb = np.asarray(im.resize((aw, ah), Image.BILINEAR))
            gray = np.asarray(im.convert("L"))
    except Exception:  # noqa: BLE001 - an unreadable picture just keeps its motion
        return None
    focus = _focus_of(None, None, [rgb])
    focus["srcLines"] = min(w, h)
    focus["lines"] = effective_lines(gray)
    focus["aspect"] = round(w / float(h), 4)
    focus["seconds"] = round(time.time() - t0, 2)
    return focus


# --------------------------------------------------------------------------- #
# Planning: focus -> a gentle move (pure data the renderer interpolates)
# --------------------------------------------------------------------------- #

MIN_SCALE = 1.05            # less does not read as a move at all
ZOOM_RATE = 0.035           # scale change per second (1.12x needs 3.4 s): a camera operator's push
PAN_RATE = 0.03             # viewport travel per second, a share of the frame
MARGIN = 0.035              # room kept around the subject, a share of the frame
# Moves turn in this order so neighbours differ; most are pushes.
KINDS = ("push", "push", "pull", "push", "drift")
# Entrances that already zoom: a move that STARTS zoomed in would double it.
ZOOM_ENTRANCES = {"zoom", "punch", "zoom-punch"}
FULL = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
_NEWS = None


def _news_re():
    global _NEWS
    if _NEWS is None:
        import re
        _NEWS = re.compile(
            r"\b(news|newscast|nbc|cbs|abc ?\d*|fox ?\d*|cnn|msnbc|pbs|bbc|reuters|associated press|ap archive|"
            r"weather channel|fox ?weather|ksl|kutv|kjzz|azfamily|12news|8newsnow|ktnv|kvvu|"
            r"newshour|60 minutes|sky news|al jazeera|cbc|ctv|wral|wfaa|khou|kprc|ksat|kxan|wthr)\b", re.I)
    return _NEWS


def is_news(media: dict) -> bool:
    """A clip from a news outlet by its title or credit: shown as it is (the owner: no crop)."""
    text = " ".join(str(media.get(k) or "") for k in ("attribution", "channel"))
    return bool(_news_re().search(text))


def scale_cap(focus: dict) -> float:
    """
    How far this picture may be pushed and stay sharp: its real detail
    (effective_lines) and its file's lines, never past REFRAME_MAX_SCALE.
    0 when it is too soft to push at all.
    """
    lines = int(focus.get("lines") or 0) or int(focus.get("srcLines") or 0)
    src = int(focus.get("srcLines") or 0) or lines
    if lines < 500 or src < 480:
        return 0.0
    cap = 1.2 if lines >= 800 and src >= 1000 else 1.15 if lines >= 650 else 1.1
    return min(cap, float(config.REFRAME_MAX_SCALE))


def cover_box(box: dict, src_aspect: float, frame_aspect: float) -> Optional[dict]:
    """
    A box of the source picture in the frame's coordinates once the picture
    is cover-fitted (objectFit: cover), the part outside the frame cut off.
    None when less than 80% of it is on screen.
    """
    try:
        x, y, w, h = (float(box[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    if src_aspect <= 0 or frame_aspect <= 0 or w <= 0 or h <= 0:
        return None
    if src_aspect > frame_aspect:            # wider: the sides are cut
        keep = frame_aspect / src_aspect
        off = (1 - keep) / 2
        x0, x1, y0, y1 = (x - off) / keep, (x + w - off) / keep, y, y + h
    else:                                    # taller: top and bottom are cut
        keep = src_aspect / frame_aspect
        off = (1 - keep) / 2
        x0, x1, y0, y1 = x, x + w, (y - off) / keep, (y + h - off) / keep
    cx0, cy0, cx1, cy1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
    if cx1 <= cx0 or cy1 <= cy0 or (cx1 - cx0) * (cy1 - cy0) < 0.8 * (x1 - x0) * (y1 - y0):
        return None
    return {"x": cx0, "y": cy0, "w": cx1 - cx0, "h": cy1 - cy0}


def _r4(b: dict) -> dict:
    return {k: round(float(b[k]), 4) for k in ("x", "y", "w", "h")}


def contains(outer: dict, inner: dict, eps: float = 1e-4) -> bool:
    return (outer["x"] <= inner["x"] + eps and outer["y"] <= inner["y"] + eps
            and outer["x"] + outer["w"] >= inner["x"] + inner["w"] - eps
            and outer["y"] + outer["h"] >= inner["y"] + inner["h"] - eps)


def _place_view(keep: dict, z: float, at: Tuple[float, float], target: Tuple[float, float]) -> dict:
    """
    A viewport of scale z (a square share of the frame: the frame's own
    aspect) with `target` at the `at` share of it, then moved just enough to
    hold `keep` and stay inside the frame.
    """
    v = 1.0 / z
    x = min(max(target[0] - at[0] * v, 0.0), 1.0 - v)
    y = min(max(target[1] - at[1] * v, 0.0), 1.0 - v)
    x = max(min(x, keep["x"]), keep["x"] + keep["w"] - v)
    y = max(min(y, keep["y"]), keep["y"] + keep["h"] - v)
    x = min(max(x, 0.0), 1.0 - v)
    y = min(max(y, 0.0), 1.0 - v)
    return {"x": x, "y": y, "w": v, "h": v}


def _composition(keep: dict, eye: Optional[float]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    (at, target): the subject's centre on a vertical third when it is off
    centre (centred when it is central); a face's eye line on the upper third.
    """
    cx, cy = keep["x"] + keep["w"] / 2, keep["y"] + keep["h"] / 2
    at_x = 1 / 3.0 if cx < 0.42 else 2 / 3.0 if cx > 0.58 else 0.5
    if eye is not None:
        return (at_x, 1 / 3.0), (cx, eye)
    return (at_x, 0.5), (cx, cy)


def plan_clip(focus: dict, seconds: float, frame_aspect: float, kind: str = "push",
              transition: str = "") -> Optional[dict]:
    """
    A move for one footage scene from its focus, or None when there should be
    none: {"from", "to", "kind", "subject", "zoom"}, every box in frame
    coordinates. The subject box (with its margin) is inside both ends, so it
    is inside every box between them: no frame of the move cuts it.
    """
    if not focus or focus.get("kind") not in ("face", "object", "action") or not focus.get("box"):
        return None
    m = focus.get("motion") or {}
    if m.get("moving", True) or m.get("cut") or focus.get("overlay"):
        return None
    if max(list((focus.get("bars") or {}).values()) or [0.0]) > 0.02:
        return None
    need = {"face": 0.6, "object": 0.55, "action": 0.5}[focus["kind"]]
    if float(focus.get("confidence") or 0) < max(need, float(config.REFRAME_MIN_CONFIDENCE)):
        return None
    if seconds < float(config.REFRAME_MIN_SECONDS):
        return None
    cap = scale_cap(focus)
    if cap < MIN_SCALE:
        return None
    src_aspect = float(focus.get("aspect") or frame_aspect)
    subject = cover_box(focus["box"], src_aspect, frame_aspect)
    if subject is None:
        return None
    pad = MARGIN + 0.08 * max(subject["w"], subject["h"])
    keep = {"x": max(0.0, subject["x"] - pad), "y": max(0.0, subject["y"] - pad)}
    keep["w"] = min(1.0, subject["x"] + subject["w"] + pad) - keep["x"]
    keep["h"] = min(1.0, subject["y"] + subject["h"] + pad) - keep["y"]
    # A corner logo stays whole (never pushed half out of the frame): it is
    # kept like the subject, which anchors the move at its corner or, when
    # the subject is across the frame, leaves no room for one.
    for logo in focus.get("logos") or []:
        lb = cover_box(logo, src_aspect, frame_aspect)
        if lb:
            x0, y0 = min(keep["x"], lb["x"]), min(keep["y"], lb["y"])
            x1 = max(keep["x"] + keep["w"], lb["x"] + lb["w"])
            y1 = max(keep["y"] + keep["h"], lb["y"] + lb["h"])
            keep = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    eye = None
    if focus["kind"] == "face" and focus.get("eye") is not None:
        eb = cover_box({"x": 0.0, "y": float(focus["eye"]), "w": 1.0, "h": 1e-3}, src_aspect, frame_aspect)
        eye = eb["y"] if eb else None
    at, target = _composition(keep, eye)
    z = min(cap, 1.0 / max(keep["w"], keep["h"], 1e-6), 1.0 + ZOOM_RATE * seconds)
    view = None
    while z >= MIN_SCALE - 1e-9:
        cand = _place_view(keep, z, at, target)
        travel = math.hypot(cand["x"] + cand["w"] / 2 - 0.5, cand["y"] + cand["h"] / 2 - 0.5)
        if travel / max(seconds, 0.1) <= PAN_RATE and contains(cand, keep):
            view = cand
            break
        z -= 0.01
    if view is None:
        return None
    if kind == "pull" and transition in ZOOM_ENTRANCES:
        kind = "push"
    if kind == "drift":
        drift = _drift(keep, z, at, target, seconds)
        if drift:
            return drift
        kind = "push"
    out = {"kind": kind if kind == "pull" else "push", "subject": _r4(keep), "zoom": round(z, 3)}
    if kind == "pull":
        out.update({"from": _r4(view), "to": dict(FULL)})
    else:
        out.update({"from": dict(FULL), "to": _r4(view)})
    return out


def _drift(keep: dict, z: float, at, target, seconds: float) -> Optional[dict]:
    """A slow lateral reframe at a fixed scale that ends with the subject on its third; None without room."""
    z_d = min(z, 1.12)
    if z_d < MIN_SCALE:
        return None
    v = 1.0 / z_d
    end = _place_view(keep, z_d, at, target)
    # Start where the subject sits on the opposite side of the viewport.
    lo, hi = max(0.0, keep["x"] + keep["w"] - v), min(1.0 - v, keep["x"])
    start_x = lo if abs(lo - end["x"]) >= abs(hi - end["x"]) else hi
    travel = abs(start_x - end["x"])
    if travel < 0.04:
        return None
    if travel / seconds > PAN_RATE:
        start_x = end["x"] + math.copysign(PAN_RATE * seconds, start_x - end["x"])
        if abs(start_x - end["x"]) < 0.04:
            return None
    start = {"x": start_x, "y": end["y"], "w": v, "h": v}
    if not (contains(start, keep) and contains(end, keep)):
        return None
    return {"from": _r4(start), "to": _r4(end), "kind": "drift", "subject": _r4(keep), "zoom": round(z_d, 3)}


def bezier(t: float, x1: float = 0.45, y1: float = 0.05, x2: float = 0.55, y2: float = 0.95) -> float:
    """CSS cubic-bezier(x1, y1, x2, y2) at t: Remotion's Easing.bezier, the stills' gentle ease in and out."""
    if t <= 0 or t >= 1:
        return min(1.0, max(0.0, t))
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        x = 3 * (1 - mid) ** 2 * mid * x1 + 3 * (1 - mid) * mid ** 2 * x2 + mid ** 3
        lo, hi = (mid, hi) if x < t else (lo, mid)
    s = (lo + hi) / 2
    return 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3


def box_at(move: dict, progress: float) -> dict:
    """
    The viewport at `progress` (0..1) of a move, eased and interpolated
    exactly as the renderer does it (remotion/src/components/reframe.ts).
    """
    e = bezier(min(1.0, max(0.0, progress)))
    a, b = move["from"], move["to"]
    return {k: a[k] + (b[k] - a[k]) * e for k in ("x", "y", "w", "h")}


def aim_still(focus: dict, frame_aspect: float) -> Optional[dict]:
    """The subject box (frame coordinates, with a little room) a still's own motion is aimed at, or None."""
    if not focus or focus.get("kind") not in ("face", "object") or not focus.get("box"):
        return None
    if float(focus.get("confidence") or 0) < 0.5:
        return None
    s = cover_box(focus["box"], float(focus.get("aspect") or frame_aspect), frame_aspect)
    if s is None or s["w"] * s["h"] > 0.6:
        return None                     # a "subject" filling the picture is no aim at all
    pad = 0.02
    x0, y0 = max(0.0, s["x"] - pad), max(0.0, s["y"] - pad)
    x1, y1 = min(1.0, s["x"] + s["w"] + pad), min(1.0, s["y"] + s["h"] + pad)
    return _r4({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})


# --------------------------------------------------------------------------- #
# The pass over a document
# --------------------------------------------------------------------------- #

def _local(url: str) -> bool:
    return bool(url) and not str(url).startswith(("http://", "https://")) and os.path.isfile(url)


def shown_seconds(scene: dict, fps: float) -> float:
    """How much of its clip file a scene plays (SceneClip slows a short clip to fill, never below 0.6x)."""
    scene_s = int(scene.get("durationInFrames") or 0) / float(fps or 30)
    clip = float((scene.get("media") or {}).get("clipSeconds") or 0)
    if clip <= 0 or clip >= scene_s:
        return scene_s
    return min(clip, scene_s * max(0.6, clip / scene_s))


def _anchored_spans(doc: dict) -> List[Tuple[int, int]]:
    """Frames under a graphic placed ON the picture (a mark's arrow, a callout's point): never reframed under it."""
    out = []
    for ov in doc.get("overlays") or []:
        if isinstance(ov, dict) and (ov.get("anchor") or ov.get("labelPosition")):
            s = int(ov.get("startFrame") or 0)
            out.append((s, s + int(ov.get("durationInFrames") or 0)))
    return out


def _plain(v):
    """Numpy scalars and arrays as plain JSON values (the document is saved as JSON)."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if np is not None and isinstance(v, np.ndarray):
        return _plain(v.tolist())
    if np is not None and isinstance(v, np.generic):
        return v.item()
    return v


def _compact(focus: dict) -> dict:
    """What the document keeps of a detection (small: it is saved with every timeline)."""
    f = _plain(focus)
    keep = {}
    for k in ("box", "kind", "confidence", "faces", "eye", "faceBoxes", "logos", "overlay", "lines", "srcLines",
              "aspect", "why"):
        v = f.get(k)
        if v is None or (isinstance(v, (str, list, dict)) and not v):
            continue
        keep[k] = v
    m = f.get("motion")
    if isinstance(m, dict):
        keep["motion"] = {k: m.get(k) for k in ("moving", "pan", "panRate", "zoom", "shake", "cut")}
    return keep


def _seed(scene: dict) -> int:
    return int(hashlib.md5(str(scene.get("id") or "").encode()).hexdigest()[:8], 16)


def place(doc: dict, deadline_seconds: float = 0.0, detect_clip_fn=None, detect_still_fn=None) -> Dict[str, object]:
    """
    Detect, plan and write media.focus / media.reframe for a document whose
    media are still local files. Time-boxed (REFRAME_SECONDS), parallel
    (REFRAME_PARALLEL); never raises. Returns counts for doc.meta.reframe.
    """
    if not config.REFRAME_ENABLED or np is None:
        return {}
    t0 = time.time()
    stats: Dict[str, object] = {"clips": 0, "stills": 0, "detected": 0, "moved": 0, "aimed": 0, "skippedTime": 0,
                                "kinds": {}, "why": {}}
    try:
        return _place(doc, t0, deadline_seconds or float(config.REFRAME_SECONDS), stats,
                      detect_clip_fn or detect_clip, detect_still_fn or detect_still)
    except Exception as e:  # noqa: BLE001 - a nicety, never a failure
        print(f"[reframe] skipped: {type(e).__name__}: {str(e)[:160]}", flush=True)
        stats["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return stats


def _place(doc: dict, t0: float, budget: float, stats: dict, detect_clip_fn, detect_still_fn) -> dict:
    fps = float(doc.get("fps") or 30)
    fa = float(doc.get("width") or 1920) / float(doc.get("height") or 1080)
    scenes = [s for s in (doc.get("scenes") or []) if isinstance(s, dict)]
    anchored = _anchored_spans(doc)
    why: Dict[str, int] = {}

    def skip(reason: str) -> None:
        why[reason] = why.get(reason, 0) + 1

    try:
        from . import upscale
        framed = upscale.is_framed
    except Exception:  # noqa: BLE001
        framed = lambda _p: False  # noqa: E731
    tasks = []
    for i, s in enumerate(scenes):
        m = s.get("media")
        if not isinstance(m, dict) or m.get("reframe") or s.get("reframe") is not None:
            continue                    # planned already, or the editor's own choice
        if (s.get("frame") or "full") != "full" or not _local(m.get("url") or ""):
            continue
        seconds = int(s.get("durationInFrames") or 0) / fps
        if m.get("type") == "video":
            if not config.REFRAME_CLIPS:
                skip("clips off for this style")
            elif seconds < float(config.REFRAME_MIN_SECONDS):
                skip("short shot")
            elif is_news(m):
                skip("news footage")
            elif framed(m["url"]):
                skip("vertical clip framed on its blur")
            elif any(a < int(s.get("startFrame") or 0) + int(s.get("durationInFrames") or 0)
                     and int(s.get("startFrame") or 0) < b for a, b in anchored):
                skip("a graphic points into it")
            else:
                tasks.append(("clip", i, m["url"], shown_seconds(s, fps)))
        elif m.get("type") == "image" and config.REFRAME_STILLS:
            motion = s.get("motion") or "none"
            if motion == "parallax" or (motion == "none" and s.get("effect") != "ken-burns"):
                continue                # the whole picture shows, or it is held still
            tasks.append(("still", i, m["url"], seconds))
    stats["clips"] = sum(1 for t in tasks if t[0] == "clip")
    stats["stills"] = sum(1 for t in tasks if t[0] == "still")
    if not tasks:
        stats["why"] = why
        return stats
    # Stills first (cheap, and most of them get an aim), then the longest
    # shots (the likeliest to take a move) - what the time box cuts is the least.
    tasks.sort(key=lambda t: (t[0] != "still", -t[3]))
    deadline = t0 + budget
    found: Dict[int, dict] = {}

    def run(task):
        kind, i, path, secs = task
        if time.time() > deadline:
            return i, None, True
        try:
            f = detect_clip_fn(path, secs) if kind == "clip" else detect_still_fn(path)
        except Exception as e:  # noqa: BLE001 - one unreadable file is "no focus"
            print(f"[reframe] scene {i + 1}: {type(e).__name__}: {str(e)[:100]}", flush=True)
            f = None
        return i, f, False

    pool = ThreadPoolExecutor(max_workers=max(1, int(config.REFRAME_PARALLEL)), thread_name_prefix="reframe")
    futures = [pool.submit(run, t) for t in tasks]
    from concurrent.futures import wait
    done, pending = wait(futures, timeout=max(1.0, deadline - time.time() + 5.0))
    pool.shutdown(wait=False, cancel_futures=True)
    stats["skippedTime"] = len(pending)
    for fut in done:
        i, f, late = fut.result()
        if late:
            stats["skippedTime"] = int(stats["skippedTime"]) + 1
        elif f:
            found[i] = f
    stats["detected"] = len(found)

    # Clips: a move where it is safe and worth it, spread out.
    moves: Dict[int, dict] = {}
    for i, f in found.items():
        s = scenes[i]
        m = s["media"]
        m["focus"] = _compact(f)
        if m.get("type") != "video":
            continue
        seconds = int(s.get("durationInFrames") or 0) / fps
        plan = plan_clip(f, seconds, fa, "push", str(s.get("transition") or ""))
        if plan:
            moves[i] = plan
        else:
            skip(f.get("why") or ("no clear subject" if f.get("kind") in ("none", None) else "not safe or too small"))
    eligible = sorted(moves, key=lambda i: (-(float(found[i].get("confidence") or 0) * (moves[i]["zoom"] - 1)), i))
    cap = max(1, int(math.ceil(float(config.REFRAME_SHARE) * len(eligible)))) if eligible else 0
    chosen: List[int] = []
    for i in eligible:
        if len(chosen) >= cap:
            skip("variety")
            continue
        if any(abs(i - j) <= 1 for j in chosen):
            skip("next to another move")
            continue
        chosen.append(i)
    kinds: Dict[str, int] = {}
    for n, i in enumerate(sorted(chosen)):
        s = scenes[i]
        m = s["media"]
        seconds = int(s.get("durationInFrames") or 0) / fps
        want = KINDS[(n + _seed(s)) % len(KINDS)]
        plan = plan_clip(found[i], seconds, fa, want, str(s.get("transition") or "")) or moves[i]
        m["reframe"] = {"from": plan["from"], "to": plan["to"], "kind": plan["kind"], "subject": plan["subject"],
                        "zoom": plan["zoom"], "aspect": round(fa, 4), "seconds": round(seconds, 2),
                        "source": str(m.get("source") or ""), "by": "auto"}
        kinds[plan["kind"]] = kinds.get(plan["kind"], 0) + 1
    stats["moved"] = len(chosen)
    stats["kinds"] = kinds

    # Stills: their own motion, aimed at the subject.
    for i, f in found.items():
        s = scenes[i]
        m = s["media"]
        if m.get("type") != "image":
            continue
        subject = aim_still(f, fa)
        if subject:
            m["reframe"] = {"subject": subject, "aspect": round(fa, 4), "source": str(m.get("source") or ""),
                            "by": "auto"}
            stats["aimed"] = int(stats["aimed"]) + 1
    stats["why"] = why
    stats["seconds"] = round(time.time() - t0, 1)
    print(f"[reframe] {stats['moved']} clip move(s) {kinds}, {stats['aimed']} still(s) aimed; "
          f"{stats['detected']}/{len(tasks)} looked at in {stats['seconds']}s"
          f"{' (' + str(stats['skippedTime']) + ' skipped for time)' if stats['skippedTime'] else ''}", flush=True)
    return stats
