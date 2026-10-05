"""
Living photos: a still picture moves with real depth.

The owner (2026-10-05) approved this as the biggest visible change left: 40-60% of
a documentary is still pictures, and each one moves as one flat sheet (a Ken
Burns push, pan or turn, remotion/src/transitions/stillMotion.tsx). A camera that
moves past real things shows depth - the rock in front slides against the canyon
behind it. Here, per picture, while the files are still on this disk (do_plan,
after the upscale and the reframe pass):

1. depth: Depth-Anything-V2-Small (Apache-2.0; the onnx-community fp32 export,
   onnxruntime on the CPU) at about 500 patches - ~0.4 s of one core. Never the
   Base or Large models: those are CC-BY-NC. Baked in by scripts/fetch_models.py.
2. cuts: the picture is split only where its depth JUMPS - an occlusion edge (a
   rock tower against the lake, a dam against the canyon) - never across a
   smooth slope, which would shear. Two or three layers, or none: a picture
   without a clean depth edge keeps today's flat move.
3. layers, made from the full-size picture at the detail the frame shows (the
   cover fit times the move's zoom, src/sharpness.py): each layer's edge follows
   the picture's own edges (a guided filter) - crisp along a depth jump, a wide
   soft blend where a cut crosses a slope - and what a nearer layer hides
   behind a jump is filled from the layer's own pixels (the row's background
   mirrored in, a push-pull fill where a row has none), away from a margin that
   also takes the near object's fringe off: a move reveals background, never a
   hole or a ghost outline. The back layer is a JPEG, the nearer ones WebP with
   alpha cut to their own box, next to the picture; media.living lists them
   back to front with their depth, and publish() puts them on R2 with the
   scene's other files.
4. the renderer (remotion/src/transitions/livingPhoto.tsx) draws the scene's own
   move (timeline._IMAGE_MOTIONS, aimed by src/reframe.py) on the stack and
   moves each layer against it by its depth: nearer layers slide and grow a
   little more, farther ones less - up to LIVING_PHOTOS_STRENGTH (3.5%) of the
   frame between the nearest and the farthest over a shot, eased, each layer
   overscanned so no edge ever shows. Missing or unloadable layers: today's
   flat picture, never a failed render.

Skipped: documents, maps, charts, screenshots and text-heavy pictures, faces in
close-up (parallax on a face looks fake), held-still styles, inset and window
frames, short shots, pictures too soft for the move, and whatever the time box
(LIVING_PHOTOS_SECONDS) does not reach. Off until the owner has seen the demo:
LIVING_PHOTOS, per job {"config": {"LIVING_PHOTOS": 1}}. Nothing here can fail
a job.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Dict, List, Optional, Tuple

from . import config

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with faster-whisper
    np = None

MODEL = "depth-anything-v2-small"
VERSION = 1
# The depth model's input: about this many 14 px patches at the picture's own
# aspect (~250 x 380 for a 3:2 photo). 500 costs ~0.42 s of one core (fp32,
# measured 2026-10-05); 800 costs 0.73 s for edges no layer needs.
TOKENS = 500
_PATCH = 14
_MEAN = (0.485, 0.456, 0.406)
_STD = (0.229, 0.224, 0.225)

# Cuts, on the depth map normalised to 0..1 (1 = nearest).
CUT_GRID = tuple(round(0.08 + 0.02 * k, 2) for k in range(43))     # 0.08 .. 0.92
EDGE_STEP = 0.14        # a depth jump this big inside 7x7 depth pixels is an occlusion edge
MIN_EDGE_SHARE = 0.55   # of a cut's boundary, at least this share runs along such jumps
MIN_LAYER_SHARE = 0.03  # every layer is at least this share of the picture
MAX_FRONT_SHARE = 0.72  # the nearest layer at most this (else it IS the picture)
MIN_CUT_GAP = 0.14      # two cuts at least this far apart in depth
# Where parallax looks fake: a nearest layer that is only a strip along an edge
# of the picture (a sliver of ground or a scan's border), or whose outline is
# intricate (a crane's lattice, a bridge's trusses, branches - cut-out bits).
EDGE_STRIP = 0.14
MAX_INTRICATE = 14.0
# The layers' edges: the depth map is lifted to the picture's own edges at a
# work size (guided filter: radius, regularisation), then cut softly (+-EDGE_SOFT).
WORK_LONG = 768
GUIDE_RADIUS = 6
GUIDE_EPS = 2e-3
EDGE_SOFT = 0.035
# Where a cut crosses a smooth slope (the local depth range under WEAK_STEP)
# instead of a jump, its edge is this soft and nothing is filled behind it.
WEAK_STEP = 0.06
SLOPE_SOFT = 0.12
# The widest strip a move ever reveals beside a near object (a share of the
# long side, with room): behind an occlusion edge all of it is filled. It grows
# with LIVING_PHOTOS_STRENGTH (reveal_share()): livingPhoto.tsx parts the layers
# by at most about half the strength on either side.
REVEAL_SHARE = 0.025
# What a nearer layer hides is filled from pixels at least this share of the
# long side away from it (the near object's fringe - mixed edge pixels - never
# feeds the fill): the row's background mirrored in at MIRROR_LONG px, a smooth
# push-pull fill at FILL_LONG px where a row has none. Only a strip ever shows.
HIDE_MARGIN = 0.012
FILL_LONG = 384
MIRROR_LONG = 960
# A gentle depth of field (the owner, 2026-10-05: "even better"): when the
# nearest layer is this much nearer than the farthest and at least this share of
# the picture, the far part of the back layer is blurred by up to DOF_RADIUS px of
# the frame - fading to none DOF_FREE (in depth) short of the foreground's depth.
DOF_RADIUS = 2.4
DOF_MIN_SEP = 0.45
DOF_MIN_FRONT = 0.06
DOF_FREE = 0.15
# A face taller than this share of the picture is a close-up (YuNet boxes run
# brow to chin) - when the detector is sure (FACE_SURE) or CLIP sees a person:
# YuNet finds faces at 0.6-0.75 in rock texture and aerial views.
FACE_MAX_SHARE = 0.12
FACE_SURE = 0.8
# Local CLIP classes (src/localvision.py) that are not a scene with depth. Its
# zero-shot classes are broad (a landscape photo reads ~0.5 "photo" and up to
# ~0.35 "text"; a page of text 0.86): one of these kinds is the picture when it
# reaches FLAT_SHARE, or FLAT_LEAD and more than "photo".
FLAT_KINDS = ("slide", "text", "map", "chart", "logo")
FLAT_SHARE = 0.5
FLAT_LEAD = 0.3
RENDER_SHARE = 0.4
# How much closer the living move may bring the nearest layer than the scene's
# own move, per unit of strength (src/sharpness.py checks the picture's real
# detail against it). livingPhoto.tsx's dolly never enlarges the subject (the far
# layers zoom less instead); only its overscan, solved against the move's own
# margin, may add a little when a sideways move needs more room than it has.
ZOOM_GAIN = 0.4

_LOCK = threading.Lock()
_STATE: Dict[str, object] = {"loaded": False, "error": ""}
STATS = {"pictures": 0, "layered": 0, "failed": 0, "seconds": 0.0, "cpuSeconds": 0.0}


# --------------------------------------------------------------------------- #
# The depth model
# --------------------------------------------------------------------------- #

def _session():
    if _STATE["loaded"]:
        return _STATE.get("session")
    with _LOCK:
        if _STATE["loaded"]:
            return _STATE.get("session")
        _STATE["loaded"] = True
        path = config.LIVING_DEPTH_MODEL
        if np is None:
            _STATE["error"] = "no numpy"
            return None
        if not os.path.isfile(path):
            _STATE["error"] = f"no model at {path}"
            return None
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            # One thread per call, several pictures at once (LIVING_PHOTOS_PARALLEL):
            # no thread spinning, so the CPU it reports is the work it did.
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
            sess = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
            _STATE["input"] = sess.get_inputs()[0].name
            _STATE["session"] = sess
            print(f"[living] depth model loaded from {path}", flush=True)
        except Exception as e:  # noqa: BLE001 - no runtime: living photos are off
            _STATE["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            _STATE.pop("session", None)
            print(f"[living] off: {_STATE['error']}", flush=True)
    return _STATE.get("session")


def available() -> bool:
    """The depth model loads (checked once)."""
    return _session() is not None


def model_size(w: int, h: int, tokens: int = TOKENS) -> Tuple[int, int]:
    """The depth model's input size for a w x h picture: about `tokens` patches, multiples of 14."""
    s = (tokens * _PATCH * _PATCH / float(max(1, w * h))) ** 0.5
    return (max(_PATCH * 8, int(round(w * s / _PATCH)) * _PATCH),
            max(_PATCH * 8, int(round(h * s / _PATCH)) * _PATCH))


def depth_map(im) -> Optional["np.ndarray"]:
    """
    Relative depth of a PIL picture as a float32 map at the model's size,
    normalised to 0..1 (1 = nearest; the 1st..99th percentile stretched), or
    None without the model or for a picture with no depth to speak of.
    """
    sess = _session()
    if sess is None:
        return None
    from PIL import Image
    w, h = model_size(*im.size)
    a = np.asarray(im.convert("RGB").resize((w, h), Image.BICUBIC), np.float32) / 255.0
    a = (a - np.array(_MEAN, np.float32)) / np.array(_STD, np.float32)
    out = sess.run(None, {_STATE["input"]: np.ascontiguousarray(a.transpose(2, 0, 1)[None])})[0]
    d = np.asarray(out, np.float32).reshape(out.shape[-2], out.shape[-1])
    lo, hi = np.percentile(d, (1.0, 99.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-6:
        return None
    return np.clip((d - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------- #
# Small array tools (numpy only: no OpenCV or SciPy in the image)
# --------------------------------------------------------------------------- #

def _box(a, r: int):
    """Mean over a (2r+1)^2 window of a 2-D map, edges extended (running sums, float32)."""
    a = np.asarray(a, np.float32)
    if r <= 0:
        return a
    k = 2 * r + 1
    p = np.pad(a, ((r + 1, r), (0, 0)), mode="edge")
    p[0] = 0.0
    c = np.cumsum(p, axis=0, dtype=np.float32)
    v = c[k:] - c[:-k]
    p = np.pad(v, ((0, 0), (r + 1, r)), mode="edge")
    p[:, 0] = 0.0
    c = np.cumsum(p, axis=1, dtype=np.float32)
    return (c[:, k:] - c[:, :-k]) / float(k * k)


def _extreme(a, r: int, fn):
    """Max (fn=np.maximum) or min filter over a (2r+1)^2 window of a 2-D map, separable, edge-padded."""
    if r <= 0:
        return a
    h, w = a.shape
    p = np.pad(a, ((r, r), (0, 0)), mode="edge")
    acc = p[0:h].copy()
    for k in range(1, 2 * r + 1):
        fn(acc, p[k:k + h], out=acc)
    p = np.pad(acc, ((0, 0), (r, r)), mode="edge")
    acc = p[:, 0:w].copy()
    for k in range(1, 2 * r + 1):
        fn(acc, p[:, k:k + w], out=acc)
    return acc


def _maxf(a, r: int):
    return _extreme(a, r, np.maximum)


def _minf(a, r: int):
    return _extreme(a, r, np.minimum)


def _resize_f(a, w: int, h: int):
    """A float32 map resized (bilinear) to w x h."""
    from PIL import Image
    return np.asarray(Image.fromarray(np.ascontiguousarray(a, dtype=np.float32), "F").resize((w, h), Image.BILINEAR),
                      np.float32)


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _guided(guide, src, r: int, eps: float):
    """He et al.'s guided filter, returned as its (A, B): src ~ A * guide + B, edges from the guide."""
    mi, mp = _box(guide, r), _box(src, r)
    cov = _box(guide * src, r) - mi * mp
    var = _box(guide * guide, r) - mi * mi
    a = cov / (var + eps)
    b = mp - a * mi
    return _box(a, r), _box(b, r)


def push_pull(rgb, weight):
    """
    Fill the unweighted parts of an image from the weighted ones: halve with
    weighted means until nothing is missing, then come back up blending each
    level's own pixels (by weight) over the coarser fill. Smooth, quick, never
    a hole. rgb: float32 (h, w, 3); weight: float32 (h, w) in 0..1.
    """
    from PIL import Image
    levels = []
    c, w = rgb.astype(np.float32), np.clip(weight.astype(np.float32), 0.0, 1.0)
    while True:
        levels.append((c, w))
        h, wd = w.shape
        if (w.min() > 0.999) or h < 2 or wd < 2:
            break
        hh, ww = h + (h % 2), wd + (wd % 2)
        if (hh, ww) != (h, wd):
            c = np.pad(c, ((0, hh - h), (0, ww - wd), (0, 0)), mode="edge")
            w = np.pad(w, ((0, hh - h), (0, ww - wd)), mode="edge")
        cw = c * w[..., None]
        sc = cw[0::2, 0::2] + cw[1::2, 0::2] + cw[0::2, 1::2] + cw[1::2, 1::2]
        sw = w[0::2, 0::2] + w[1::2, 0::2] + w[0::2, 1::2] + w[1::2, 1::2]
        c = sc / np.maximum(sw, 1e-6)[..., None]
        w = np.minimum(sw, 1.0)
    filled = levels[-1][0]
    if levels[-1][1].min() <= 0.999:            # nothing known at all: grey
        filled = np.where(levels[-1][1][..., None] > 0, filled, 127.0).astype(np.float32)
    for c, w in reversed(levels[:-1]):
        h, wd = w.shape
        up = np.asarray(Image.fromarray(np.clip(filled + 0.5, 0, 255).astype(np.uint8), "RGB")
                        .resize((wd, h), Image.BILINEAR), np.float32)
        filled = c * w[..., None] + up * (1.0 - w[..., None])
    return filled


def mirror_fill(rgb, known, fallback, band: Optional[int] = None, stats: Optional[dict] = None):
    """
    Fill the unknown pixels of each row with the row's own picture mirrored
    across the nearest known edge (the texture of the background beside the
    hole, not a smear), weighted toward the nearer side; where a row has no
    known pixel to mirror, the nearest known one; with none at all, `fallback`.
    The camera's parallax is mostly sideways, so what a move reveals is that
    row's background continued. Only the strip within `band` px of the known
    edge is worked out (deeper in is never seen); `stats` gets "fallback": the
    share of the hole within that reach that only `fallback` could fill.
    rgb, fallback: float32 (h, w, 3); known: bool (h, w).
    """
    h, w = known.shape
    idx = np.broadcast_to(np.arange(w, dtype=np.int32)[None, :], (h, w))
    left = np.maximum.accumulate(np.where(known, idx, -1), axis=1)
    right = np.minimum.accumulate(np.where(known, idx, w)[:, ::-1], axis=1)[:, ::-1]
    out = np.where(known[..., None], rgb, fallback).astype(np.float32)
    band = int(band if band is not None else REVEAL_SHARE * max(h, w)) + 2
    strip = ~known & (((idx - left <= band) & (left >= 0)) | ((right - idx <= band) & (right < w)))
    if stats is not None:
        # The hole within reach of the background in any direction (on a quarter-size grid).
        k = 4
        small = known[::k, ::k].astype(np.float32)
        near = _maxf(small, max(1, band // k)) > 0
        zone = ~known & np.repeat(np.repeat(near, k, 0), k, 1)[:h, :w]
        n = int(zone.sum())
        stats["fallback"] = round(float((zone & ~strip).sum()) / n, 3) if n else 0.0
    hy, hx = np.nonzero(strip)
    if not len(hy):
        return out
    lft, rgt = left[hy, hx], right[hy, hx]
    has_l, has_r = lft >= 0, rgt < w
    ml = np.clip(2 * lft - hx + 1, 0, w - 1)             # the pixel as far left of the edge as this one is right
    mr = np.clip(2 * rgt - hx - 1, 0, w - 1)
    use_l = np.where(has_l & known[hy, ml], ml, np.clip(lft, 0, w - 1))
    use_r = np.where(has_r & known[hy, mr], mr, np.clip(rgt, 0, w - 1))
    wl = np.where(has_l, 1.0 / np.maximum(hx - lft, 1), 0.0).astype(np.float32)
    wr = np.where(has_r, 1.0 / np.maximum(rgt - hx, 1), 0.0).astype(np.float32)
    total = wl + wr
    side = (rgb[hy, use_l] * wl[:, None] + rgb[hy, use_r] * wr[:, None]) / np.maximum(total, 1e-6)[:, None]
    out[hy, hx] = np.where((total > 0)[:, None], side, fallback[hy, hx])
    return out


# --------------------------------------------------------------------------- #
# Where to cut
# --------------------------------------------------------------------------- #

def plan_cuts(d, max_layers: int = 3) -> dict:
    """
    The depths to cut a picture's normalised depth map at: {"cuts": [t, ...]
    (1 or 2, ascending), "quality", "front", "depths": per layer back to front,
    "focus": {x, y} of the nearest layer (picture shares)} - or {"cuts": [],
    "why"}. A cut must run along depth JUMPS for most of its length (an
    occlusion edge): one through a smooth slope would shear the ground.
    """
    if d is None or d.ndim != 2 or min(d.shape) < 16:
        return {"cuts": [], "why": "no depth"}
    h, w = d.shape
    ds = _box(d, 1)
    mn, mx = _minf(ds, 1), _maxf(ds, 1)
    strong = (_maxf(ds, 3) - _minf(ds, 3)) >= EDGE_STEP
    least = 0.25 * min(h, w)
    rows = []
    for t in CUT_GRID:
        share = float((ds >= t).mean())
        if share < MIN_LAYER_SHARE or share > MAX_FRONT_SHARE or 1.0 - share < MIN_LAYER_SHARE:
            continue
        edge = (mn < t) & (mx >= t)
        n = int(edge.sum())
        if n < least:
            continue
        q = float((edge & strong).sum()) / n
        rows.append({"t": t, "q": q, "share": share, "score": q - 0.1 * abs(share - 0.3), "edge": edge})
    good = [r for r in rows if r["q"] >= MIN_EDGE_SHARE]
    if not good:
        best = max((r["q"] for r in rows), default=0.0)
        return {"cuts": [], "why": "no clear depth edge", "quality": round(best, 3)}

    def centred(r: dict) -> dict:
        """The middle of the run of cuts along the same jump (same split, as clean): the cut sits
        in the middle of the jump, so both sides of its soft edge stay inside it."""
        same = [x for x in good if abs(x["share"] - r["share"]) <= 0.02 and x["q"] >= r["q"] - 0.05]
        return sorted(same, key=lambda x: x["t"])[len(same) // 2]

    first = centred(max(good, key=lambda r: r["score"]))
    cuts = [first["t"]]
    if max_layers >= 3:
        near_first = _maxf(first["edge"].astype(np.float32), 2) > 0

        def distinct(r: dict) -> bool:
            """A second cut along a boundary of its own (not the first cut's jump seen at another depth),
            leaving every layer a real share of the picture."""
            lo, hi = sorted((first["t"], r["t"]))
            shares = (float((ds < lo).mean()), float(((ds >= lo) & (ds < hi)).mean()), float((ds >= hi).mean()))
            shared = float((r["edge"] & near_first).sum()) / max(1, int(r["edge"].sum()))
            return min(shares) >= MIN_LAYER_SHARE and shared <= 0.5
        second = [r for r in good if abs(r["t"] - first["t"]) >= MIN_CUT_GAP and distinct(r)]
        if second:
            cuts.append(centred(max(second, key=lambda r: r["score"]))["t"])
    cuts.sort()
    bounds = [-1.0] + cuts + [2.0]
    depths = []
    for k in range(len(bounds) - 1):
        band = (ds >= bounds[k]) & (ds < bounds[k + 1])
        depths.append(round(float(ds[band].mean()) if band.any() else (bounds[k] + bounds[k + 1]) / 2, 3))
    front = ds >= cuts[-1]
    ys, xs = np.nonzero(front)
    focus = {"x": round(float((xs.mean() + 0.5) / w), 4), "y": round(float((ys.mean() + 0.5) / h), 4)} \
        if len(xs) else {"x": 0.5, "y": 0.5}
    quality = min(r["q"] for r in rows if r["t"] in cuts)
    # How intricate the nearest layer's outline is: its edge length against the
    # side of a square of its area (a disc ~3.5, a rock 5-8, a crane's lattice 20+).
    edge_px = sum(int(r["edge"].sum()) for r in rows if r["t"] == cuts[-1])
    intricate = edge_px / max(1.0, float(len(xs)) ** 0.5)
    out = {"cuts": cuts, "quality": round(quality, 3), "front": round(float(front.mean()), 3),
           "depths": depths, "focus": focus, "intricate": round(intricate, 2)}
    if len(xs):
        x0, x1, y0, y1 = xs.min() / w, (xs.max() + 1) / w, ys.min() / h, (ys.max() + 1) / h
        strip = (y1 - y0 <= EDGE_STRIP and (y0 <= 0.01 or y1 >= 0.99)) or \
            (x1 - x0 <= EDGE_STRIP and (x0 <= 0.01 or x1 >= 0.99))
        if strip:
            return {"cuts": [], "why": "only a strip at the edge in front", "quality": out["quality"]}
    if intricate > MAX_INTRICATE:
        return {"cuts": [], "why": "an intricate outline in front", "quality": out["quality"],
                "intricate": out["intricate"]}
    return out


MAX_STRENGTH = 0.1          # livingPhoto.tsx LIVING_MAX_STRENGTH


def reveal_share(strength: Optional[float] = None) -> float:
    """The widest strip beside a near object a move may reveal (a share of the long side, with room)."""
    s = float(config.LIVING_PHOTOS_STRENGTH if strength is None else strength)
    return max(REVEAL_SHARE, 0.55 * max(0.0, min(MAX_STRENGTH, s)) + 0.012)


def safety(plan: dict, info: Optional[dict] = None) -> Dict[str, float]:
    """
    How much of the full move a picture can take without showing a flaw (0..1
    each; the move is scaled down by the smallest rather than showing it):
    "edges" - the share of the cut that runs along real depth jumps (the rest
    shears a slope); "outline" - an intricate front outline; "fill" - how much
    of what a move reveals had to be a smooth fill rather than the row's own
    background; "front" - a front so big the background mostly fills in.
    """
    info = info or {}
    q = float(plan.get("quality") or 0)
    return {"edges": round(max(0.35, min(1.0, 0.35 + (q - 0.55) * 2.2)), 3),
            "outline": round(max(0.6, min(1.0, 1.3 - float(plan.get("intricate") or 0) / 25.0)), 3),
            "fill": round(max(0.5, min(1.0, 1.15 - float(info.get("fallback") or 0))), 3),
            "front": round(max(0.6, min(1.0, 1.4 - float(plan.get("front") or 0))), 3)}


def strength_for(plan: dict, info: Optional[dict] = None) -> float:
    """The relative shift (frame shares, nearest vs farthest layer, over a shot) a picture gets:
    LIVING_PHOTOS_STRENGTH for a clean, deep cut, scaled down for a shallow one and by the
    smallest safety() factor - a smaller move rather than a visible flaw."""
    base = max(0.0, min(MAX_STRENGTH, float(config.LIVING_PHOTOS_STRENGTH)))
    depths = plan.get("depths") or [0.0, 1.0]
    sep = max(0.75, min(1.0, (depths[-1] - depths[0]) / 0.5))
    return round(base * sep * min(safety(plan, info).values()), 4)


# --------------------------------------------------------------------------- #
# The layers
# --------------------------------------------------------------------------- #

def layer_size(w: int, h: int, frame_w: int, frame_h: int, zoom: float) -> Tuple[int, int]:
    """The layers' size: the picture's own, or less when the frame never shows that much
    (its cover fit times the move's largest zoom) - never more than the picture."""
    k = max(frame_w / float(w), frame_h / float(h)) * max(1.0, zoom)
    s = min(1.0, k)
    return max(16, int(round(w * s))), max(16, int(round(h * s)))


def _kept(alpha, r: int = 2):
    """0..1: what of a layer's alpha stays once its specks are gone - what a (2r+1) px opening
    removes (isolated bits the depth map put in front would float on their own) - keeping the
    soft edge of the rest."""
    core = _maxf(_minf((alpha > 0.5).astype(np.float32), r), r + 2)
    return np.clip(_box(core, 1), 0.0, 1.0)


def _clean(alpha, r: int = 2):
    """A layer's alpha without its specks (_kept)."""
    return alpha * _kept(alpha, r)


def _unmix(layer, mask, behind, picture, nearer=None):
    """
    A layer's soft edge with its colours solved so the stack draws exactly the
    picture while nothing moves: where the edge is part-transparent, the colour
    is (picture - (1 - a) * what lies behind) / a - the near object's edge
    without the background mixed into it (a matte's foreground). Without it a
    soft edge over a filled background showed a stripe of that fill. `nearer`:
    where a nearer layer's fill lies, left as it is. PIL images in, RGB out.
    """
    from PIL import Image
    a8 = np.asarray(mask)
    soft = (a8 > 2) & (a8 < 253)
    if nearer is not None:
        soft &= np.asarray(nearer) < 5
    ys, xs = np.nonzero(soft)
    if not len(ys):
        return layer
    a = a8[ys, xs].astype(np.float32)[:, None] / 255.0
    rgb = np.array(layer)
    under = np.asarray(behind)[ys, xs].astype(np.float32)
    want = picture[ys, xs].astype(np.float32)
    rgb[ys, xs] = np.clip((want - (1.0 - a) * under) / np.maximum(a, 0.05) + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def dof_radius(plan: dict, lw: int, lh: int, frame_w: int, frame_h: int) -> float:
    """The far layer's blur (px of the layer) when the foreground is close and big enough to be
    the subject - DOF_RADIUS px of the frame - else 0."""
    depths = plan.get("depths") or []
    if DOF_RADIUS <= 0 or len(depths) < 2 or depths[-1] - depths[0] < DOF_MIN_SEP \
            or float(plan.get("front") or 0) < DOF_MIN_FRONT:
        return 0.0
    per_frame_px = 1.0 / max(frame_w / float(lw), frame_h / float(lh))     # layer px per frame px (cover fit)
    return round(DOF_RADIUS * per_frame_px, 2)


def make_layers(im, plan: dict, stem: str, frame_w: int, frame_h: int, zoom: float, d=None,
                info: Optional[dict] = None) -> List[dict]:
    """
    Write the layers of a PIL picture (RGB) cut at plan["cuts"]: [{"path",
    "depth"[, "box"]}] back to front. The back layer is the whole picture, a
    JPEG, with what the nearer layers cover filled in; each nearer layer is a
    WebP with alpha cut to its own box ([x0, y0, x1, y1], picture shares) and,
    under the layers nearer still, a fill from its own pixels - moving those
    reveals it, never a hole. `d`: the normalised depth map plan_cuts read.
    `info` gets "fallback" (mirror_fill) and "dof" (the back layer's blur, px).
    """
    info = info if info is not None else {}
    from PIL import Image
    cuts = list(plan["cuts"])
    W, H = im.size
    lw, lh = layer_size(W, H, frame_w, frame_h, zoom)
    pic = im if (lw, lh) == (W, H) else im.resize((lw, lh), Image.BICUBIC, reducing_gap=2.0)
    s = min(1.0, WORK_LONG / float(max(lw, lh)))
    sw, sh = max(16, int(round(lw * s))), max(16, int(round(lh * s)))
    small = pic.resize((sw, sh), Image.BILINEAR, reducing_gap=2.0)
    g_lo = np.asarray(small.convert("L"), np.float32) / 255.0
    a, b = _guided(g_lo, _resize_f(d, sw, sh), GUIDE_RADIUS, GUIDE_EPS)
    q_lo = a * g_lo + b
    # Where the depth jumps (an occlusion edge) a cut is crisp and what it hides
    # is filled; where a cut crosses a smooth slope (the foot of a rock, a shore)
    # it is a wide, soft blend of the picture's own pixels instead - the slope
    # shears gently as the layers part, never showing a fill band.
    ds = _box(d, 1)
    jump = _resize_f(np.clip((_maxf(ds, 3) - _minf(ds, 3) - WEAK_STEP) / (EDGE_STEP - WEAK_STEP), 0.0, 1.0), sw, sh)
    reach = max(2, int(round(reveal_share() * max(sw, sh))))     # past the most a layer is ever moved
    sharp = np.clip(_box(_maxf(jump, reach), 2), 0.0, 1.0)
    soft = EDGE_SOFT + (SLOPE_SOFT - EDGE_SOFT) * (1.0 - sharp)
    # Each cut's alpha at the work size (the edges follow the picture's own, the
    # specks gone); a nearer cut's region always lies inside a farther one's.
    raw = [_smoothstep((q_lo - (t - soft)) / (2 * soft)) for t in cuts]
    kept = [_kept(x) for x in raw]
    alphas = [x * k_ for x, k_ in zip(raw, kept)]
    for k in range(len(alphas) - 1, 0, -1):
        alphas[k - 1] = np.maximum(alphas[k - 1], alphas[k])
    # The same cuts at the picture's full size for the layers' own edges (He's fast
    # guided filter: the work-size coefficients applied to the full-size picture), so a
    # cut lies on the picture's own edge to the pixel - one cut 3 px off at the work
    # size carried a sliver of the lake along with the rock.
    g_full = np.asarray(pic.convert("L"), np.float32) / 255.0
    q_full = _resize_f(a, lw, lh) * g_full + _resize_f(b, lw, lh)
    del g_full
    soft_full = _resize_f(soft, lw, lh)
    edges = []
    for t, k_ in zip(cuts, kept):
        x = (q_full - (t - soft_full)) / (2.0 * soft_full)
        edges.append(_smoothstep(x) * _resize_f(k_, lw, lh))
    del q_full, soft_full
    for k in range(len(edges) - 1, 0, -1):
        edges[k - 1] = np.maximum(edges[k - 1], edges[k])
    masks = [Image.fromarray(np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8), "L") for x in edges]
    del edges
    f = min(1.0, FILL_LONG / float(max(lw, lh)))
    fw, fh = max(8, int(round(lw * f))), max(8, int(round(lh * f)))
    rgb_f = np.asarray(pic.resize((fw, fh), Image.BILINEAR, reducing_gap=2.0), np.float32)
    m = min(1.0, MIRROR_LONG / float(max(lw, lh)))
    mw, mh = max(8, int(round(lw * m))), max(8, int(round(lh * m)))
    rgb_m = np.asarray(pic.resize((mw, mh), Image.BILINEAR, reducing_gap=2.0), np.float32)
    margin = max(2, int(round(HIDE_MARGIN * max(mw, mh))))

    def as_l(x, w_, h_):
        img = Image.fromarray(np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8), "L")
        return img if img.size == (w_, h_) else img.resize((w_, h_), Image.BILINEAR)

    def filled(source, nearer):
        """`source` (the layer's own region, work size) with what `nearer` covers filled from
        its pixels away from that edge: the row's background mirrored in, a smooth fill where
        a row has none; full size, RGB."""
        near_m = _resize_f(nearer, mw, mh)
        keep = _resize_f(source, mw, mh) * (1.0 - np.clip(_box(_maxf((near_m > 0.02).astype(np.float32), margin), 1),
                                                          0.0, 1.0))
        smooth_fill = push_pull(rgb_f, _resize_f(keep, fw, fh))
        smooth_m = np.asarray(Image.fromarray(np.clip(smooth_fill + 0.5, 0, 255).astype(np.uint8), "RGB")
                              .resize((mw, mh), Image.BILINEAR), np.float32)
        st: dict = {}
        fill = mirror_fill(rgb_m, keep > 0.5, smooth_m, band=margin + int(reveal_share() * max(mw, mh)), stats=st)
        info["fallback"] = max(float(info.get("fallback") or 0), float(st.get("fallback") or 0))
        fill_img = Image.fromarray(np.clip(fill + 0.5, 0, 255).astype(np.uint8), "RGB").resize((lw, lh),
                                                                                               Image.BILINEAR)
        # Fill under the nearer layer, one work pixel wider (no pixel the near object's
        # edge tinted stays behind it as a ghost outline when it moves) - except along a
        # soft slope edge and as far as a move reveals beside it: the picture's own pixels.
        slope = ((nearer > 0.02) & (nearer < 0.98) & (sharp < 0.5)).astype(np.float32)
        own = np.clip(_box(_maxf(slope, reach), 2), 0.0, 1.0)
        return Image.composite(fill_img, pic, as_l(_maxf(nearer, 1) * (1.0 - own), lw, lh))

    out: List[dict] = []
    depths = list(plan.get("depths") or [])
    back = filled(np.ones_like(alphas[0]), alphas[0])
    dof = dof_radius(plan, lw, lh, frame_w, frame_h)
    if dof > 0:
        # A gentle depth of field: the far part of the back layer (by depth: the
        # farther, the more) a touch out of focus when the foreground is close.
        focus, far = depths[-1] - DOF_FREE, depths[0]
        weight = _smoothstep((focus - _resize_f(ds, sw, sh)) / max(0.05, focus - far))
        from PIL import ImageFilter
        back = Image.composite(back.filter(ImageFilter.GaussianBlur(dof)), back, as_l(weight, lw, lh))
    path = f"{stem}.living0.jpg"
    back.save(path, "JPEG", quality=92)
    info["dof"] = round(dof, 2)
    out.append({"path": path, "depth": depths[0] if depths else 0.0})
    picture = np.asarray(pic)
    behind = back                                       # the stack drawn so far
    for k in range(1, len(cuts) + 1):
        alpha = alphas[k - 1]
        layer = filled(alpha, alphas[k]) if k < len(cuts) else pic
        mask = masks[k - 1]
        box = mask.getbbox()
        if not box:
            continue
        x0, y0 = max(0, box[0] - 2), max(0, box[1] - 2)
        x1, y1 = min(lw, box[2] + 2), min(lh, box[3] + 2)
        cut = (x0, y0, x1, y1)
        part_mask = mask.crop(cut)
        part = _unmix(layer.crop(cut), part_mask, behind.crop(cut), picture[y0:y1, x0:x1],
                      masks[k].crop(cut) if k < len(cuts) else None)
        if k < len(cuts):
            whole = layer.copy()
            whole.paste(part, (x0, y0))
            behind = Image.composite(whole, behind, mask)
        part.putalpha(part_mask)
        path = f"{stem}.living{k}.webp"
        part.save(path, "WEBP", quality=86, method=0, alpha_quality=90)
        out.append({"path": path, "depth": depths[k] if k < len(depths) else 1.0,
                    "box": [round(x0 / lw, 5), round(y0 / lh, 5), round(x1 / lw, 5), round(y1 / lh, 5)]})
    return out


# --------------------------------------------------------------------------- #
# Which pictures
# --------------------------------------------------------------------------- #

def _seconds(scene: dict, fps: float) -> float:
    return int(scene.get("durationInFrames") or 0) / max(1.0, fps)


def _anchored(doc: dict) -> List[Tuple[int, int]]:
    """Frames under a graphic placed ON the picture (a mark's arrow, a callout's point)."""
    out = []
    for ov in doc.get("overlays") or []:
        if isinstance(ov, dict) and (ov.get("anchor") or ov.get("labelPosition")):
            s = int(ov.get("startFrame") or 0)
            out.append((s, s + int(ov.get("durationInFrames") or 0)))
    return out


def scene_reason(scene: dict, fps: float, anchored: List[Tuple[int, int]] = ()) -> str:
    """Why a scene's picture gets no living move ("" when it may), from the document alone."""
    m = scene.get("media")
    if not isinstance(m, dict) or m.get("type") != "image" or not m.get("url"):
        return "not a still"
    if m.get("living"):
        return "layered already"
    if scene.get("living") in (False, "off"):
        return "off for this scene"
    if (scene.get("frame") or "full") != "full":
        return "inset or window frame"
    if isinstance(scene.get("reframe"), dict) or scene.get("reframe") in ("off", False):
        return "the editor's own framing"
    motion = str(scene.get("motion") or "none")
    if motion == "none" and scene.get("effect") != "ken-burns":
        return "held still"
    if _seconds(scene, fps) < float(config.LIVING_PHOTOS_MIN_SECONDS):
        return "short shot"
    sem = scene.get("semanticMetadata") if isinstance(scene.get("semanticMetadata"), dict) else {}
    if str(sem.get("subjectType") or "").lower() == "document":
        return "a document"
    focus = m.get("focus") if isinstance(m.get("focus"), dict) else {}
    if focus.get("kind") == "text" or focus.get("overlay"):
        return "lettering on the picture"
    if any(isinstance(b, (list, tuple)) and len(b) >= 4 and float(b[3]) >= FACE_MAX_SHARE
           for b in focus.get("faceBoxes") or []):
        return "a face in close-up"
    s0 = int(scene.get("startFrame") or 0)
    s1 = s0 + int(scene.get("durationInFrames") or 0)
    if any(a < s1 and s0 < b for a, b in anchored):
        return "a graphic points into it"
    url = str(m.get("url") or "")
    if url.lower().startswith(("http://", "https://")) or not os.path.isfile(url):
        return "not on this disk"
    return ""


def picture_reason(im) -> str:
    """Why this picture gets no living move ("" when it may): a close-up face, lettering, or a
    document / map / chart / screenshot / illustration by the local CLIP classes."""
    from PIL import Image
    w, h = im.size
    aw = 640 if w >= h else max(64, int(round(640 * w / float(h))))
    ah = max(64, int(round(aw * h / float(w))))
    small = im.resize((aw, ah), Image.BILINEAR, reducing_gap=2.0)
    rgb = np.asarray(small)
    faces: list = []
    try:
        from . import reframe
        if reframe.faces_available():
            # One scale: a close-up face is big (find_faces adds 640 px for small faces).
            faces = [f for f in reframe._yunet(rgb, 320, 0.6) if f[3] >= FACE_MAX_SHARE]
            if any(f[4] >= FACE_SURE for f in faces):
                return "a face in close-up"
        if len(reframe.text_bands(rgb)) >= 3:
            return "lettering on the picture"
    except Exception as e:  # noqa: BLE001 - the checks below still run
        print(f"[living] face/text check skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    try:
        from . import localvision
        if localvision.available():
            with localvision._RUN:
                classes = localvision.classify(localvision.embed_images([small]))
            photo = classes.get("photo", 0.0)
            top = max(FLAT_KINDS, key=lambda k: classes.get(k, 0.0))
            share = classes.get(top, 0.0)
            if share >= FLAT_SHARE or (share >= FLAT_LEAD and share > photo):
                return {"slide": "a screenshot or slide", "text": "a page of text", "map": "a map",
                        "chart": "a chart", "logo": "a logo"}[top]
            if classes.get("render", 0.0) >= RENDER_SHARE and classes.get("render", 0.0) > photo:
                return "an illustration or render"
            if faces and classes.get("person", 0.0) >= 0.25:
                return "a face in close-up"
    except Exception as e:  # noqa: BLE001 - no CLIP: the depth decides
        print(f"[living] picture classes skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
    return ""


def move_zoom(motion: str) -> float:
    """The largest zoom of a still's living move: the scene's own move (src/sharpness.py
    MOTION_ZOOM; a "parallax" still is drawn as a pan here) a little closer for the nearest layer."""
    from . import sharpness
    m = "pan-left" if motion == "parallax" else ("zoom-in" if motion in ("", "none") else motion)
    return round(sharpness.motion_zoom(m) * (1.0 + ZOOM_GAIN * max(0.0, float(config.LIVING_PHOTOS_STRENGTH))), 4)


# --------------------------------------------------------------------------- #
# One picture, a whole document
# --------------------------------------------------------------------------- #

def sharp_enough(path: str, zoom: float, known: Optional[float] = None) -> bool:
    """
    The picture's real detail holds the living move's zoom (src/sharpness.py,
    MAX_PICTURE_MAGNIFICATION). `known`: the magnification sourcing measured
    at the planner's typical zoom (scoreParts.magnification) - scaled to this
    zoom it settles most pictures without measuring again; the file (perhaps
    upscaled since) is measured only when that is not enough.
    """
    from . import sharpness
    if not sharpness.picture_on() or sharpness.limit() <= 0:
        return True
    try:
        if known and float(known) > 0 and \
                float(known) * zoom / max(1e-6, sharpness.planned_zoom()) <= sharpness.limit() + 1e-9:
            return True
    except (TypeError, ValueError):
        pass
    return bool(sharpness.picture_check(path, zoom=zoom).get("ok", True))


def build(path: str, motion: str, frame_w: int = 1920, frame_h: int = 1080, check_picture: bool = True,
          known_magnification: Optional[float] = None) -> dict:
    """
    Everything for one picture on this disk: {"layers": [{"path", "depth"
    [, "box"]}], "plan", "zoom", "seconds", "cpu"} or {"why": reason}. Never
    raises.
    """
    t0, c0 = time.time(), time.thread_time()
    out: dict = {}
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as src:
            im = ImageOps.exif_transpose(src).convert("RGB")
        if min(im.size) < 64:
            out = {"why": "too small"}
        else:
            why = picture_reason(im) if check_picture else ""
            if why:
                out = {"why": why}
            else:
                d = depth_map(im)
                plan = plan_cuts(d, max(2, min(3, int(config.LIVING_PHOTOS_MAX_LAYERS))))
                if not plan.get("cuts"):
                    out = {"why": plan.get("why") or "no clear depth edge", "plan": plan}
                else:
                    zoom = move_zoom(motion)
                    if check_picture and not sharp_enough(path, zoom, known_magnification):
                        out = {"why": "too soft for the move", "plan": plan}
                    if not out:
                        stem = os.path.splitext(path)[0]
                        info: dict = {}
                        layers = make_layers(im, plan, stem, frame_w, frame_h, zoom, d=d, info=info)
                        out = ({"layers": layers, "plan": plan, "zoom": zoom, "info": info,
                                "aspect": round(im.width / im.height, 5)}
                               if len(layers) >= 2 else {"why": "nothing left in front", "plan": plan})
    except Exception as e:  # noqa: BLE001 - one picture is never the job's problem
        out = {"why": f"failed ({type(e).__name__}: {str(e)[:80]})", "error": True}
    out["seconds"] = round(time.time() - t0, 3)
    out["cpu"] = round(time.thread_time() - c0, 3)
    with _LOCK:
        STATS["pictures"] += 1
        STATS["layered"] += 1 if out.get("layers") else 0
        STATS["failed"] += 1 if out.get("error") else 0
        STATS["seconds"] += out["seconds"]
        STATS["cpuSeconds"] += out["cpu"]
    return out


def block(media: dict, got: dict) -> dict:
    """media.living for a build() result: the layers back to front, where the nearest one's
    middle is (picture shares), the shift the renderer gives it, bound to the media's source."""
    plan = got.get("plan") or {}
    info = got.get("info") or {}
    return {"v": VERSION,
            "layers": [{"url": x["path"], "depth": round(float(x["depth"]), 3),
                        **({"box": list(x["box"])} if x.get("box") else {})} for x in got["layers"]],
            "focus": dict(plan.get("focus") or {"x": 0.5, "y": 0.5}),
            "aspect": got.get("aspect"),
            "strength": strength_for(plan, info),
            "quality": plan.get("quality"),
            # Why the move is as big as it is (the smallest of these scaled it), and the far layer's blur.
            "safety": safety(plan, info),
            **({"dof": info["dof"]} if info.get("dof") else {}),
            "source": str(media.get("source") or ""),
            "by": MODEL}


def place(doc: dict, deadline_seconds: float = 0.0, build_fn: Optional[Callable] = None) -> Dict[str, object]:
    """
    Layer every eligible still of a document whose pictures are still local
    files, writing media.living. Time-boxed (LIVING_PHOTOS_SECONDS for the
    whole video), LIVING_PHOTOS_PARALLEL pictures at once; never raises.
    Returns counts for doc.meta.living ({} with the flag off).
    """
    if not config.LIVING_PHOTOS:
        return {}
    t0 = time.time()
    stats: Dict[str, object] = {"stills": 0, "layered": 0, "layers": 0, "skippedTime": 0, "why": {},
                                "model": MODEL}
    try:
        if build_fn is None and not available():
            stats["error"] = str(_STATE.get("error") or "the depth model is not installed")
            print(f"[living] skipped: {stats['error']}", flush=True)
            return stats
        return _place(doc, t0, deadline_seconds or float(config.LIVING_PHOTOS_SECONDS), stats, build_fn or build)
    except Exception as e:  # noqa: BLE001 - a nicety, never a failure
        print(f"[living] skipped: {type(e).__name__}: {str(e)[:160]}", flush=True)
        stats["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return stats


def _place(doc: dict, t0: float, budget: float, stats: dict, build_fn: Callable) -> dict:
    fps = float(doc.get("fps") or 30)
    fw, fh = int(doc.get("width") or 1920), int(doc.get("height") or 1080)
    anchored = _anchored(doc)
    why: Dict[str, int] = {}

    def skip(reason: str) -> None:
        why[reason] = why.get(reason, 0) + 1

    tasks = []
    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        if (s.get("media") or {}).get("type") == "image":
            stats["stills"] = int(stats["stills"]) + 1
        reason = scene_reason(s, fps, anchored)
        if reason:
            if reason != "not a still":
                skip(reason)
            continue
        tasks.append((i, s))
    if not tasks:
        stats["why"] = why
        return stats
    # Longest shots first: the move reads best there, and the time box cuts the shortest.
    tasks.sort(key=lambda t: -int(t[1].get("durationInFrames") or 0))
    deadline = t0 + budget
    by_path: Dict[str, dict] = {}
    lock = threading.Lock()

    def run(task):
        i, s = task
        path = s["media"]["url"]
        if time.time() > deadline:
            return i, None, True
        with lock:
            hit = by_path.get(path)
        if hit is None:
            try:
                hit = build_fn(path, str(s.get("motion") or "none"), fw, fh, known_magnification=_known_mag(s))
            except Exception as e:  # noqa: BLE001 - this picture stays flat, the others go on
                hit = {"why": f"failed ({type(e).__name__}: {str(e)[:80]})", "error": True}
            with lock:
                by_path[path] = hit
        return i, hit, False

    pool = ThreadPoolExecutor(max_workers=max(1, int(config.LIVING_PHOTOS_PARALLEL)), thread_name_prefix="living")
    futures = [pool.submit(run, t) for t in tasks]
    done, pending = wait(futures, timeout=max(1.0, deadline - time.time() + 10.0))
    pool.shutdown(wait=False, cancel_futures=True)
    stats["skippedTime"] = len(pending)
    scenes = doc["scenes"]
    cpu, secs = [], []
    for fut in done:
        i, got, late = fut.result()
        if late or got is None:
            stats["skippedTime"] = int(stats["skippedTime"]) + 1
            continue
        if got.get("cpu") is not None:
            cpu.append(float(got["cpu"]))
            secs.append(float(got.get("seconds") or 0))
        if not got.get("layers"):
            skip(str(got.get("why") or "no layers"))
            continue
        m = scenes[i]["media"]
        m["living"] = block(m, got)
        stats["layered"] = int(stats["layered"]) + 1
        stats["layers"] = int(stats["layers"]) + len(got["layers"])
    stats["why"] = why
    stats["seconds"] = round(time.time() - t0, 1)
    if cpu:
        stats["cpuPerPicture"] = round(sum(cpu) / len(cpu), 3)
        stats["cpuMax"] = round(max(cpu), 3)
        stats["secondsPerPicture"] = round(sum(secs) / len(secs), 3)
    print(f"[living] {stats['layered']}/{len(tasks)} still(s) layered ({stats['layers']} layers) in "
          f"{stats['seconds']}s, {stats.get('cpuPerPicture', 0)} s CPU each"
          f"{' (' + str(stats['skippedTime']) + ' skipped for time)' if stats['skippedTime'] else ''}; "
          f"why not: {why}", flush=True)
    return stats


def place_one(doc: dict, index: int) -> bool:
    """One scene's new picture (a Replace Clip) layered like a plan's; True when it got layers."""
    if not config.LIVING_PHOTOS:
        return False
    scenes = doc.get("scenes") or []
    if not 0 <= index < len(scenes) or not available():
        return False
    s = scenes[index]
    if scene_reason(s, float(doc.get("fps") or 30), _anchored(doc)):
        return False
    got = build(s["media"]["url"], str(s.get("motion") or "none"),
                int(doc.get("width") or 1920), int(doc.get("height") or 1080), known_magnification=_known_mag(s))
    if not got.get("layers"):
        return False
    s["media"]["living"] = block(s["media"], got)
    return True


def _known_mag(scene: dict) -> Optional[float]:
    """The magnification sourcing measured for the scene's picture (scoreParts), or None."""
    sem = scene.get("semanticMetadata") if isinstance(scene.get("semanticMetadata"), dict) else {}
    parts = sem.get("scoreParts") if isinstance(sem.get("scoreParts"), dict) else {}
    try:
        v = float(parts.get("magnification") or 0)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# --------------------------------------------------------------------------- #
# Saving and checking the layers
# --------------------------------------------------------------------------- #

def _is_link(url) -> bool:
    return str(url or "").lower().startswith(("http://", "https://"))


def drop(media: dict) -> bool:
    """Take a picture's layers off (it is drawn flat, as before). True when it had some."""
    return isinstance(media, dict) and media.pop("living", None) is not None


def blocks(doc: dict) -> List[Tuple[int, dict]]:
    """(scene index, media.living) of every scene drawn with layers."""
    out = []
    for i, s in enumerate(doc.get("scenes") or []):
        m = s.get("media") if isinstance(s, dict) else None
        if isinstance(m, dict) and isinstance(m.get("living"), dict):
            out.append((i, m["living"]))
    return out


def publish(doc: dict, put: Optional[Callable[[str, str], str]], prefix: str) -> Dict[str, int]:
    """
    Upload every layer still on this disk - put(local, object) returns its
    public link (R2: a link that never expires) - and point the document at
    it. A scene whose layers cannot all be saved, or with no `put` (scene
    media not on R2: a signed link would die and nothing re-signs layers), is
    drawn flat. Never raises.
    """
    out = {"uploaded": 0, "dropped": 0}
    todo = []
    for i, liv in blocks(doc):
        layers = liv.get("layers") if isinstance(liv.get("layers"), list) else []
        local = [x for x in layers if isinstance(x, dict) and not _is_link(x.get("url"))]
        if not local:
            continue
        if put is None or not all(os.path.isfile(str(x.get("url") or "")) for x in local):
            drop(doc["scenes"][i]["media"])
            out["dropped"] += 1
            continue
        todo.append((i, local))
    if not todo:
        return out
    scenes = doc["scenes"]

    def one(item):
        i, local = item
        sid = str(scenes[i].get("id") or f"s{i:04d}")
        try:
            links = []
            for n, x in enumerate(local):
                ext = os.path.splitext(str(x["url"]))[1].lower() or ".bin"
                links.append(put(str(x["url"]), f"{prefix}/{sid}-living{n}{ext}"))
            return i, local, links
        except Exception as e:  # noqa: BLE001 - this scene is drawn flat
            print(f"[living] layers of {sid} not saved: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return i, local, None

    with ThreadPoolExecutor(max_workers=min(8, len(todo))) as pool:
        for i, local, links in pool.map(one, todo):
            if not links or not all(_is_link(u) for u in links):
                drop(scenes[i]["media"])
                out["dropped"] += 1
                continue
            for x, url in zip(local, links):
                x["url"] = url
            out["uploaded"] += len(links)
    return out


def strip_local(doc: dict) -> int:
    """Before a document is saved: layers still on this disk (never published) are taken off,
    so no work-directory path reaches the saved timeline. Returns how many scenes."""
    n = 0
    for i, liv in blocks(doc):
        layers = liv.get("layers") if isinstance(liv.get("layers"), list) else []
        if not layers or any(not _is_link((x or {}).get("url")) for x in layers):
            drop(doc["scenes"][i]["media"])
            n += 1
    return n


def stats() -> dict:
    with _LOCK:
        return dict(STATS, available=_STATE.get("session") is not None, error=_STATE.get("error", ""))


def status() -> dict:
    """For the health check, without loading the model: on, installed, loaded."""
    return {"on": bool(config.LIVING_PHOTOS), "installed": os.path.isfile(config.LIVING_DEPTH_MODEL),
            "loaded": _STATE.get("session") is not None, "model": MODEL,
            **({"error": _STATE["error"]} if _STATE.get("error") else {})}
