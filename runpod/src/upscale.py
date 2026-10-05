"""
Upscaling before render: small photos get real detail, soft clips get crisp.

* Photos: Real-ESRGAN general x4v3 (Qualcomm AI Hub's ONNX export, ~5 MB,
  128x128 tiles) on onnxruntime CPU. A 640x360 web photo takes ~2 s on 8
  threads and comes out with sharp edges and texture instead of the smeared
  look of a browser blow-up. Photos with a long side under UPSCALE_AI_BELOW
  (a 1.75x or bigger enlargement) go through the model; larger ones only need
  a Lanczos resize with a light unsharp mask, which is instant.
* Clips: an AI video upscaler (SeedVR, Real-ESRGAN per frame) needs a GPU -
  on these CPU workers one minute of 30 fps video would take hours. Clips
  under UPSCALE_CLIP_BELOW lines get a light denoise, a Lanczos scale to
  1080p and an unsharp mask in one ffmpeg pass, which beats Chrome's own
  scaling at render time and costs seconds.

Everything is time-boxed (UPSCALE_SECONDS) and only ever replaces a file with
a better one: any failure keeps the original.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from . import config

_TILE = 128          # the model's fixed input
_PAD = 8             # overlap on each side, trimmed from the output
_STEP = _TILE - 2 * _PAD
_SCALE = 4
UPSCALE_AI_BELOW = int(os.getenv("UPSCALE_AI_BELOW", "1100"))

_LOCK = threading.Lock()
_STATE: dict = {"loaded": False}
STATS = {"images": 0, "ai": 0, "clips": 0, "failed": 0, "seconds": 0.0}
# Clips of this job framed in place on a blurred copy (frame_vertical). They
# measure 1920x1080 afterwards, so only this set tells them apart: they must
# not enter the shared clip library, where a documentary job would reuse a
# pillarboxed phone clip as ordinary footage.
FRAMED: set = set()
# Clips of this job sharpened up to 1080 lines in place (upscale_clip), with
# the lines they had: the file says 1080, the detail is the original's
# (src/reframe.py pushes a 720p clip no further than ~1.15x).
UPSCALED: dict = {}


def is_framed(path: str) -> bool:
    """The file at `path` was framed in place by frame_vertical in this job."""
    if not path:
        return False
    with _LOCK:
        return os.path.abspath(path) in FRAMED


def original_lines(path: str) -> int:
    """The lines a clip had before upscale_clip replaced it in this job, or 0."""
    if not path:
        return 0
    with _LOCK:
        return int(UPSCALED.get(os.path.abspath(path), 0))


def carry(src: str, dst: str) -> None:
    """`dst`, cut from `src` (a moved start), is framed or sharpened as `src` was in this job."""
    if not src or not dst:
        return
    a, b = os.path.abspath(src), os.path.abspath(dst)
    with _LOCK:
        if a in FRAMED:
            FRAMED.add(b)
        if a in UPSCALED:
            UPSCALED[b] = UPSCALED[a]


def available() -> bool:
    """The upscaler model loads (checked once)."""
    if not config.UPSCALE_ENABLED:
        return False
    _load()
    return _STATE.get("session") is not None


def _load() -> None:
    if _STATE["loaded"]:
        return
    with _LOCK:
        if _STATE["loaded"]:
            return
        _STATE["loaded"] = True
        path = config.UPSCALE_MODEL
        if not os.path.isfile(path):
            _STATE["error"] = f"no model at {path}"
            return
        try:
            import numpy  # noqa: F401
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, config.LOCAL_VISION_THREADS)
            _STATE["session"] = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
            _STATE["input"] = _STATE["session"].get_inputs()[0].name
            print(f"[upscale] Real-ESRGAN loaded from {path}", flush=True)
        except Exception as e:  # noqa: BLE001 - no runtime: upscaling is off
            _STATE["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"[upscale] off: {_STATE['error']}", flush=True)


def _esrgan(rgb):
    """uint8 HxWx3 -> uint8 (4H)x(4W)x3 through the tiled model."""
    import numpy as np
    sess, name = _STATE["session"], _STATE["input"]
    h, w, _ = rgb.shape
    # Reflect-pad so every tile window is full and edges get real context.
    ph = (-(h) % _STEP)
    pw = (-(w) % _STEP)
    src = np.pad(rgb.astype(np.float32) / 255.0,
                 ((_PAD, _PAD + ph), (_PAD, _PAD + pw), (0, 0)), mode="reflect")
    out = np.zeros(((h + ph) * _SCALE, (w + pw) * _SCALE, 3), np.float32)
    for y in range(0, h + ph, _STEP):
        for x in range(0, w + pw, _STEP):
            tile = src[y:y + _TILE, x:x + _TILE].transpose(2, 0, 1)[None]
            res = sess.run(None, {name: np.ascontiguousarray(tile)})[0][0].transpose(1, 2, 0)
            core = res[_PAD * _SCALE:(_PAD + _STEP) * _SCALE, _PAD * _SCALE:(_PAD + _STEP) * _SCALE]
            out[y * _SCALE:(y + _STEP) * _SCALE, x * _SCALE:(x + _STEP) * _SCALE] = core
    out = out[:h * _SCALE, :w * _SCALE]
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def upscale_image(path: str, target: int = 0) -> bool:
    """
    Upscale a photo in place so its long side reaches `target` (default
    UPSCALE_TARGET). True when the file was replaced. Pictures already big
    enough, unreadable ones and any failure leave the file untouched.
    """
    target = target or config.UPSCALE_TARGET
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:  # pragma: no cover
        return False
    t0 = time.time()
    try:
        alpha = None
        with Image.open(path) as im:
            im.load()
            if im.mode not in ("RGB", "L"):
                # RGBA/LA/P/CMYK...: a small photo accepted at the lowered
                # floor must still be upscaled. Real transparency is kept (as
                # PNG, the way imagefix.normalize stores it).
                from .imagefix import _has_transparency
                if _has_transparency(im):
                    im = im.convert("RGBA")
                    alpha = im.getchannel("A")
            im = im.convert("RGB")
        long_side = max(im.size)
        if long_side >= config.UPSCALE_BELOW or long_side < 64:
            return False
        used_ai = False
        if long_side < UPSCALE_AI_BELOW and available():
            big = Image.fromarray(_esrgan(np.asarray(im)))
            used_ai = True
        else:
            big = im
        s = target / max(big.size)
        size = (max(1, round(big.width * s)), max(1, round(big.height * s)))
        big = big.resize(size, Image.LANCZOS)
        if not used_ai:
            big = big.filter(ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=2))
        tmp = path + ".up.part"
        if alpha is not None:
            big = big.convert("RGBA")
            big.putalpha(alpha.resize(size, Image.LANCZOS))
            big.save(tmp, "PNG")
        else:
            big.save(tmp, "JPEG", quality=93, subsampling=0, optimize=True)
        os.replace(tmp, path)
        with _LOCK:
            STATS["images"] += 1
            STATS["ai"] += 1 if used_ai else 0
            STATS["seconds"] += time.time() - t0
        return True
    except Exception as e:  # noqa: BLE001 - the original stays
        with _LOCK:
            STATS["failed"] += 1
        print(f"[upscale] {os.path.basename(path)}: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return False


def _probe_height(path: str) -> int:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                           capture_output=True, text=True, timeout=30)
        w, h = (p.stdout or "").strip().split("\n")[0].split("x")[:2]
        return int(h) if int(w) >= int(h) else int(w)
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def upscale_clip(path: str, min_lines: int = 0) -> bool:
    """Denoise + Lanczos to 1080 lines + unsharp, in place, for clips between
    `min_lines` and UPSCALE_CLIP_BELOW lines. True when replaced."""
    lines = _probe_height(path)
    if not lines or lines >= config.UPSCALE_CLIP_BELOW or lines < max(min_lines, 240):
        return False
    t0 = time.time()
    tmp = path + ".up.mp4"
    vf = ("hqdn3d=1.2:1.2:4:4,scale=-2:1080:flags=lanczos+accurate_rnd,"
          "unsharp=5:5:0.55:5:5:0.0,format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", vf, "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "18", "-c:a", "copy", "-movflags", "+faststart", tmp]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=240)
        if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 10_000:
            raise RuntimeError((p.stderr or b"")[-200:].decode("utf-8", "replace"))
        os.replace(tmp, path)
        with _LOCK:
            STATS["clips"] += 1
            STATS["seconds"] += time.time() - t0
            UPSCALED[os.path.abspath(path)] = lines
        return True
    except Exception as e:  # noqa: BLE001 - the original stays
        with _LOCK:
            STATS["failed"] += 1
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"[upscale] clip {os.path.basename(path)}: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return False


def _dims(path: str) -> tuple:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                           capture_output=True, text=True, timeout=30)
        w, h = (p.stdout or "").strip().split("\n")[0].split("x")[:2]
        return int(w), int(h)
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        return 0, 0


def frame_vertical(path: str, width: int = 1920, height: int = 1080) -> bool:
    """
    A vertical or square clip as news compilations show it, in place: the
    middle band (VERTICAL_BAND_ASPECT, trimming platform captions and UI at
    the top and bottom) fitted to the full height, over the same clip scaled
    to cover the frame and heavily blurred - no darkening, no border. True
    when the file was replaced; landscape clips are left alone.
    """
    w, h = _dims(path)
    if not w or not h or w >= h * 1.2:
        return False
    band = max(0.5, min(1.2, config.VERTICAL_BAND_ASPECT))
    keep_h = f"min(ih\\,trunc(iw/{band}/2)*2)"
    fc = (f"[0:v]split=2[bg][fg];"
          f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase:flags=bilinear,"
          f"crop={width}:{height},gblur=sigma=40,setsar=1[b];"
          f"[fg]crop=iw:{keep_h}:0:(ih-{keep_h})/2,"
          f"scale=-2:{height}:flags=lanczos,unsharp=5:5:0.4:5:5:0.0,setsar=1[f];"
          f"[b][f]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    tmp = path + ".framed.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", path, "-filter_complex", fc, "-map", "[v]",
           "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
           "-c:a", "copy", "-movflags", "+faststart", tmp]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=240)
        if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 10_000:
            raise RuntimeError((p.stderr or b"")[-200:].decode("utf-8", "replace"))
        os.replace(tmp, path)
        with _LOCK:
            FRAMED.add(os.path.abspath(path))
            STATS["framed"] = STATS.get("framed", 0) + 1
            STATS["seconds"] += time.time() - t0
        return True
    except Exception as e:  # noqa: BLE001 - the original stays
        with _LOCK:
            STATS["failed"] += 1
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"[upscale] framing {os.path.basename(path)}: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return False


def _below_floor(path: str) -> bool:
    """A photo smaller than the normal floor (MIN_IMAGE_LONG_SIDE)."""
    if not config.MIN_IMAGE_LONG_SIDE:
        return False
    try:
        from PIL import Image
        with Image.open(path) as im:
            return max(im.size) < config.MIN_IMAGE_LONG_SIDE
    except Exception:  # noqa: BLE001 - unreadable: upscale_image leaves it alone anyway
        return False


def upscale_assets(assets: Iterable, deadline_seconds: float = 0.0) -> dict:
    """
    Upscale the chosen photos and soft clips of a job in parallel, within the
    time box. Each asset needs `kind` and `local_path`; archive film (source
    archive_org) keeps its period softness.

    Photos under MIN_IMAGE_LONG_SIDE were only accepted because the upscaler
    is installed (filters.min_image_long_side), so they go first and are
    exempt from the time box: skipped, they would render blown up.
    """
    deadline = time.time() + (deadline_seconds or config.UPSCALE_SECONDS)
    with _LOCK:
        FRAMED.clear()                  # this job's framed clips only
        UPSCALED.clear()
    seen, jobs = set(), []
    for a in assets:
        path = getattr(a, "local_path", "") or ""
        if not a or not path or path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        if a.kind == "image" and a.source != "generated":
            jobs.append(("image", path, _below_floor(path)))
        elif a.kind == "video" and a.source not in ("archive_org",):
            jobs.append(("clip", path, False))
    if not jobs or not (config.UPSCALE_ENABLED or config.ALLOW_VERTICAL):
        return {"queued": 0}
    jobs.sort(key=lambda j: not j[2])   # must-upscale photos first (stable: scene order otherwise)
    done = {"image": 0, "clip": 0, "framed": 0, "skipped_time": 0}

    def run(job):
        kind, path, must = job
        if kind == "clip" and config.ALLOW_VERTICAL and frame_vertical(path):
            done["framed"] += 1         # framing always runs: a raw vertical clip would be cropped away
            return
        if not config.UPSCALE_ENABLED:
            return
        if time.time() > deadline and not must:
            done["skipped_time"] += 1
            return
        ok = upscale_image(path) if kind == "image" else upscale_clip(path, config.MIN_CLIP_HEIGHT)
        if ok:
            done[kind] += 1

    with ThreadPoolExecutor(max_workers=max(1, config.UPSCALE_PARALLEL),
                            thread_name_prefix="upscale") as pool:
        list(pool.map(run, jobs))
    print(f"[upscale] {done['image']} photo(s) and {done['clip']} clip(s) upscaled, "
          f"{done['framed']} vertical clip(s) framed, of {len(jobs)} checked "
          f"({done['skipped_time']} skipped for time)", flush=True)
    return dict(done, queued=len(jobs))


def stats() -> dict:
    with _LOCK:
        return dict(STATS, available=_STATE.get("session") is not None, error=_STATE.get("error", ""))
