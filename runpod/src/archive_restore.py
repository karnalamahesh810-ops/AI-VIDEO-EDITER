"""
Old footage restore (the owner approved it 2026-10-05): archival and
low-resolution clips - newsreels, old TV, early digital, allowed down to
MIN_ARCHIVE_HEIGHT lines - are cleaned up before they are published, so they
sit next to modern 1080p footage without black edges, combing, colour
fringes and smeared noise. Off by default (ARCHIVE_RESTORE) until the owner
has seen it; a job tries it with {"config": {"ARCHIVE_RESTORE": 1}}.

What a clip gets, in one ffmpeg pass on the CPU (measured 2026-10-05 on 11
sections of KIRO-TV 1980, a 1930s Boulder Dam home movie, the 1936
"Reclamation and the Arid West" (240 lines), the 1983 Glen Canyon spillway
VHS and a 2007 camera clip; scratchpad archive_restore/):

* deinterlaced (bwdif, the field order idet found) when idet finds combing;
* deblocked on its own 8 px grid, before anything moves the grid;
* black film-gate / VHS / pillarbox borders cropped (cropdetect over the
  whole clip): cover-fit, a 4:3 clip showed them as black side bars;
  then only the middle 16:9 is kept - all a cover fit ever shows of a 4:3
  clip - so the output is exactly the 1920x1080 frame, drawn 1:1;
* a black-and-white film's chroma set to neutral: 240-line newsreels carry
  pink and green fringes that are not in the film;
* brought down to about twice its real detail first when the file is far
  bigger than its picture (an upscaled VHS upload: 1080 lines holding ~170);
* hqdn3d, light on luma (grain and faces keep their texture; nlmeans read as
  wax on rock and skin at 2x the CPU) and strong on chroma (VHS colour
  blotches);
* Lanczos to the geometric middle size, luma unsharp there, Lanczos to
  1920x1080, contrast-adaptive sharpening on luma;
* a 60p capture halved to 30p (the edit is 30 fps); optional
  (ARCHIVE_RESTORE_SMOOTH) motion-compensated smoothing of film with
  repeated frames (mpdecimate + minterpolate).
Colour is never graded (the video's grade does that, src/grade.py); the
output is tagged with the matrix the source had, so an SD clip blown up to HD
is not decoded as BT.709. Audio is copied as it was.

Not used: Real-ESRGAN x4v3 per frame (the photo model, src/upscale.py) takes
4.6 s a frame at 640x480 on 16 threads - ~970 s for a 7 s clip, ~100x the
budget - and on these sources it paints: crisp contours, flat plastic
surfaces, invented rock texture. The ffmpeg chain costs ~20-25 CPU seconds
for a 7 s 480-line clip (most of it the 1080p x264 encode), about 5 s wall
on 4 threads.

Everything is time-boxed and can only replace a clip with a better file: a
clip that times out or fails keeps its original file and goes on to the
normal polish (upscale.upscale_clip), so a job never fails or slows on a
clip. Results are cached on the machine by (video id, start, length).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Tuple

from . import config

# Bump when the chain changes: cached files of an older chain are not reused.
CHAIN_VERSION = "ar1"
# Written into the restored file's comment tag: a clip restored once (in this
# job, an earlier one or the clip library) is never restored again.
TAG = "thumbgenius-archive-restore"

# The frame the renderer draws: a restored clip is exactly this, shown 1:1.
OUT_W, OUT_H = 1920, 1080

_YT_SECTION = re.compile(r"^yt_([\w-]{11})_(\d+)_(\d+)_")
_YT_ID = re.compile(r"[?&]v=([\w-]{11})")
_BENCH = re.compile(r"utime=([\d.]+)s\s+stime=([\d.]+)s")

_LOCK = threading.Lock()
_KEY_LOCKS: Dict[str, threading.Lock] = {}
# This job's restored clips: absolute path -> what was done (upscale_assets clears it).
RESTORED: Dict[str, dict] = {}
# The last restore_assets report (handler: meta.sourcing.archiveRestore).
LAST: dict = {}


def on() -> bool:
    return bool(getattr(config, "ARCHIVE_RESTORE", False))


def reset() -> None:
    with _LOCK:
        RESTORED.clear()
        LAST.clear()


def is_restored(path: str) -> bool:
    """The file at `path` was restored in place in this job."""
    if not path:
        return False
    with _LOCK:
        return os.path.abspath(path) in RESTORED


def last_report() -> dict:
    with _LOCK:
        return json.loads(json.dumps(LAST)) if LAST else {}


# --------------------------------------------------------------------------- #
# Reading a clip
# --------------------------------------------------------------------------- #

def _ratio(text: str, default: float = 0.0) -> float:
    try:
        if "/" in str(text):
            a, b = str(text).split("/", 1)
            return float(a) / float(b) if float(b) else default
        return float(text)
    except (TypeError, ValueError):
        return default


def probe(path: str) -> dict:
    """{w, h, fps, seconds, sar, tagged, color_space, color_primaries, color_transfer}; {} unreadable."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,r_frame_rate,avg_frame_rate,sample_aspect_ratio,color_space,"
             "color_primaries,color_transfer:format=duration:format_tags=comment", "-of", "json", path],
            capture_output=True, text=True, timeout=30)
        data = json.loads(p.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    streams = data.get("streams") or []
    if not streams:
        return {}
    s, fmt = streams[0], data.get("format") or {}
    w, h = int(s.get("width") or 0), int(s.get("height") or 0)
    if not w or not h:
        return {}
    fps = _ratio(s.get("avg_frame_rate")) or _ratio(s.get("r_frame_rate"))
    if not fps or fps > 240:
        fps = _ratio(s.get("r_frame_rate"), 30.0) or 30.0
    sar = _ratio(str(s.get("sample_aspect_ratio") or "1:1").replace(":", "/"), 1.0) or 1.0
    comment = str((fmt.get("tags") or {}).get("comment") or "")
    return {"w": w, "h": h, "fps": round(fps, 3), "seconds": _ratio(fmt.get("duration")),
            "sar": sar if 0.3 < sar < 3.0 else 1.0, "tagged": TAG in comment,
            "color_space": s.get("color_space") or "", "color_primaries": s.get("color_primaries") or "",
            "color_transfer": s.get("color_transfer") or ""}


def analyse(path: str, frames: int = 360) -> dict:
    """
    One decode of the clip: idet (interlaced? which field first), cropdetect
    over every frame (the union of what is not black: a fade from black does
    not shrink it) and mpdecimate (the share of frames that are new - film
    telecined to 30 fps repeats about one in five).
    """
    out = {"interlaced": False, "parity": "", "crop": None, "unique": 1.0, "frames": 0}
    vf = "idet,cropdetect=limit=24:round=2:reset=0,mpdecimate=hi=768:lo=320:frac=0.33,showinfo"
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", path, "-an", "-sn",
                            "-frames:v", str(frames), "-vf", vf, "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return out
    err = p.stderr or ""
    # ffmpeg 9 prints idet's counts twice (a first, empty filter instance): the last is the clip's.
    multi = re.findall(r"Multi frame detection: TFF:\s*(\d+)\s+BFF:\s*(\d+)\s+Progressive:\s*(\d+)", err)
    if multi:
        tff, bff, prog = (int(x) for x in multi[-1])
        out["frames"] = tff + bff + prog
        # A real interlaced transfer reads 95%+ one field order (NARA's 1980 Mount St. Helens
        # MPEG-2: 248 BFF, 5 progressive); progressive footage reads progressive or undetermined.
        if tff + bff >= max(8, 0.6 * (tff + bff + prog)):
            out["interlaced"] = True
            out["parity"] = "tff" if tff >= bff else "bff"
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
    if crops:
        out["crop"] = tuple(int(x) for x in crops[-1])
    kept = len(re.findall(r"\[Parsed_showinfo[^\]]*\]\s*n:\s*\d+", err))
    decoded = len(re.findall(r"\[Parsed_cropdetect[^\]]*\].*crop=", err)) or out["frames"]
    if kept and decoded:
        out["unique"] = round(min(1.0, kept / float(decoded)), 3)
    return out


def monochrome(path: str, seconds: float) -> bool:
    """A black-and-white picture: almost no chroma in three frames (|UV| median < 2, 90th
    percentile < 4 of 255; a sepia print or a grey ash landscape in colour stays colour)."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return False
    sats = []
    for i in range(3):
        at = max(0.0, seconds * (i + 0.5) / 3.0) if seconds > 0 else 0.0
        try:
            q = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
                                "-vf", "scale=160:120,format=yuv444p", "-f", "rawvideo", "-"],
                               capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        a = np.frombuffer(q.stdout or b"", np.uint8)
        if a.size >= 160 * 120 * 3:
            a = a[:160 * 120 * 3].reshape(3, 120, 160).astype(np.float32)
            sats.append(np.hypot(a[1] - 128.0, a[2] - 128.0).ravel())
    if not sats:
        return False
    s = np.concatenate(sats)
    return float(np.percentile(s, 50)) < 2.0 and float(np.percentile(s, 90)) < 4.0


def archive_marked(asset) -> bool:
    """Archive film by its source or its title (media._is_archive: a year before 1990, a
    newsreel, Pathe...) - the clips sourcing lets down to MIN_ARCHIVE_HEIGHT lines."""
    from . import media
    title = f"{getattr(asset, 'attribution', '') or ''} {getattr(asset, 'query', '') or ''}"
    return media._is_archive(title, getattr(asset, "source", "") or "")


# --------------------------------------------------------------------------- #
# The decision and the chain
# --------------------------------------------------------------------------- #

def _even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def visible_box(w: int, h: int, sar: float, crop: Optional[tuple]) -> Tuple[Tuple[int, int, int, int], bool]:
    """
    ((cw, ch, x, y), borders trimmed?): the part of a w x h clip the 1920x1080
    frame shows once its black borders go - the detected picture, then its
    middle at 16:9. Every way a clip is drawn covers a 16:9 box
    (SceneClip.tsx: full frame and the player window, objectFit cover), so a
    4:3 clip's top and bottom eighths were never on screen; restoring only
    the rest makes the output exactly the frame, drawn 1:1, and saves a
    quarter of the work.
    """
    box = _crop_box(w, h, crop)
    cw, ch, x, y = box if box else (w, h, 0, 0)
    target = OUT_W / float(OUT_H)
    aspect = cw * sar / float(ch)
    if aspect < target * 0.99:                  # narrower (4:3, a film gate): the middle rows
        nh = min(ch, _even(cw * sar / target))
        y += ((ch - nh) // 2) // 2 * 2
        ch = nh
    elif aspect > target * 1.01:                # wider (scope film): the middle columns
        nw = min(cw, _even(ch * target / sar))
        x += ((cw - nw) // 2) // 2 * 2
        cw = nw
    return (cw, ch, x, y), bool(box)


def _crop_box(w: int, h: int, crop: Optional[tuple]) -> Optional[Tuple[int, int, int, int]]:
    """The detected picture (cw, ch, x, y) when it trims borders worth trimming: at least 0.5%
    of the frame, no side by more than a quarter, most of the frame kept. Each trimmed side
    goes 2 px further in (a soft or ragged edge)."""
    if not crop:
        return None
    cw, ch, x, y = crop
    if cw <= 0 or ch <= 0 or x < 0 or y < 0 or x + cw > w or y + ch > h:
        return None
    if cw * ch >= w * h * 0.995 or cw * ch < w * h * 0.55:
        return None
    left, top, right, bottom = x, y, w - x - cw, h - y - ch
    if max(left, right) > w * 0.25 or max(top, bottom) > h * 0.25:
        return None
    if left:
        x, cw = x + 2, cw - 2
    if right:
        cw -= 2
    if top:
        y, ch = y + 2, ch - 2
    if bottom:
        ch -= 2
    cw, ch = cw // 2 * 2, ch // 2 * 2
    return (cw, ch, x // 2 * 2, y // 2 * 2) if cw >= 64 and ch >= 64 else None


def decide(info: dict) -> Tuple[bool, str]:
    """(restore?, why) for a measured clip. `info` carries: archive, w, h, seconds, tagged,
    real_lines (0 = not measured), interlaced."""
    if not info.get("archive"):
        return False, "modern"
    if info.get("tagged"):
        return False, "already restored"
    w, h = int(info.get("w") or 0), int(info.get("h") or 0)
    if not w or not h:
        return False, "unreadable"
    if w < h * 1.2:
        return False, "vertical"
    if min(w, h) < 120:
        return False, "too small"
    seconds = float(info.get("seconds") or 0.0)
    if seconds > float(getattr(config, "ARCHIVE_RESTORE_MAX_CLIP_SECONDS", 30.0)):
        return False, "too long"
    lines = min(w, h)
    real = int(info.get("real_lines") or 0)
    sharp = int(getattr(config, "ARCHIVE_RESTORE_SHARP_LINES", 576))
    below = int(getattr(config, "ARCHIVE_RESTORE_BELOW", 1000))
    if info.get("interlaced"):
        return True, "interlaced"
    if lines < below:
        return True, f"{lines} lines"
    if real and real < sharp:
        return True, f"{real} real lines of {lines}"
    return False, "sharp"


def plan(info: dict) -> dict:
    """
    The geometry and the steps for a clip that is restored: `info` as for decide, plus
    sar, fps, crop (cropdetect's box), unique (share of new frames), mono, color tags.
    Returns {"vf", "steps", "size": [W, H], "work": [w, h], "fps"}.
    """
    w, h = int(info["w"]), int(info["h"])
    sar = float(info.get("sar") or 1.0)
    fps = float(info.get("fps") or 30.0)
    steps: List[str] = []
    vf: List[str] = []
    if info.get("interlaced"):
        vf.append(f"bwdif=mode=send_frame:parity={info.get('parity') or 'auto'}:deint=all")
        steps.append("deinterlace")
    # The 8 px block grid is the source's own: deblocked before a crop or a scale moves it.
    vf.append("deblock=filter=weak:block=8")
    steps.append("deblock")
    (cw, ch, x, y), borders = visible_box(w, h, sar, info.get("crop"))
    if (cw, ch) != (w, h):
        vf.append(f"crop={cw}:{ch}:{x}:{y}")
    if borders:
        steps.append("borders")
    out_fps = fps
    if fps > 31.0:
        # Half of a 50/60p capture keeps every other frame exactly (the edit is 30 fps).
        out_fps = fps / 2.0 if fps / 2.0 >= 23.0 else 30.0
        vf.append(f"fps={_rate(out_fps)}")
        steps.append(f"{fps:.0f}p->{out_fps:.0f}p")
    # The working size: the shown part at about twice its real detail when the file is
    # far bigger than that (an upscaled upload: 1080 lines holding ~170), else as it is;
    # non-square pixels are made square here.
    dw, dh = cw * sar, float(ch)
    work_h = ch
    real = int(info.get("real_lines") or 0)
    if real:
        want = _even(max(360, min(720, 2.0 * ch * real / float(min(w, h)))))
        if ch > 1.5 * want:
            work_h = want
    work_w = _even(dw * work_h / dh)
    if work_h != ch or abs(sar - 1.0) > 0.01:
        vf.append(f"scale={work_w}:{work_h}:flags=lanczos+accurate_rnd+full_chroma_int")
        if work_h != ch:
            steps.append(f"work at {work_h} lines")
    if info.get("mono"):
        vf.append("lutyuv=u=128:v=128")
        steps.append("black-and-white")
    vf.append("hqdn3d=1.5:6:3:6")
    steps.append("denoise")
    smooth = bool(getattr(config, "ARCHIVE_RESTORE_SMOOTH", False)) and \
        float(info.get("unique") or 1.0) < 0.9 and out_fps <= 31.0
    if smooth:
        # Repeated frames dropped and the motion between the rest interpolated at the
        # clip's own rate; the last frame held a little so the clip keeps its length
        # (the output is cut to it): a shorter clip would play slowed down in its scene.
        vf.append("mpdecimate=hi=768:lo=320:frac=0.33,"
                  f"minterpolate=fps={_rate(out_fps)}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
                  "tpad=stop_mode=clone:stop_duration=0.5")
        steps.append("smooth motion")
    # Two Lanczos steps with the luma sharpened at the geometric middle (edges lifted
    # where they are a few pixels wide, not after the blow-up), then CAS on luma.
    # Stronger (1.2 / 0.75) lifted the sources' compression blocks around faces.
    if OUT_H >= 2 * work_h:
        mid_h = _even(math.sqrt(work_h * OUT_H))
        mid_w = _even(mid_h * OUT_W / float(OUT_H))
        vf.append(f"scale={mid_w}:{mid_h}:flags=lanczos+accurate_rnd+full_chroma_int")
        vf.append("unsharp=5:5:0.9:3:3:0")
    vf.append(f"scale={OUT_W}:{OUT_H}:flags=lanczos+accurate_rnd+full_chroma_int")
    vf.append("cas=strength=0.5:planes=1")
    vf.append("setsar=1,format=yuv420p")
    steps.append(f"upscale to {OUT_W}x{OUT_H}")
    return {"vf": ",".join(vf), "steps": steps, "size": [OUT_W, OUT_H], "work": [work_w, work_h],
            "fps": round(out_fps, 3), "seconds": float(info.get("seconds") or 0.0) if smooth else 0.0}


def _rate(fps: float) -> str:
    """A frame rate as ffmpeg's exact fraction (29.97 -> 30000/1001)."""
    for num in (24000, 30000, 48000, 60000):
        if abs(fps - num / 1001.0) < 0.01:
            return f"{num}/1001"
    from fractions import Fraction
    f = Fraction(fps).limit_denominator(1001)
    return f"{f.numerator}/{f.denominator}" if f.denominator != 1 else str(f.numerator)


def _color_args(info: dict) -> List[str]:
    """The source's colour tags on the output; an untagged SD source tagged BT.601 (its own
    matrix - an HD-size file without tags is decoded as BT.709 by browsers)."""
    space, prim, trc = info.get("color_space"), info.get("color_primaries"), info.get("color_transfer")
    if not space or space in ("unknown", "reserved"):
        space, prim, trc = ("smpte170m",) * 3 if min(info["w"], info["h"]) < 720 else ("bt709",) * 3
    args = ["-colorspace", space]
    if prim and prim not in ("unknown", "reserved"):
        args += ["-color_primaries", prim]
    if trc and trc not in ("unknown", "reserved"):
        args += ["-color_trc", trc]
    return args


def command(src: str, dst: str, info: dict, chain: dict, threads: int) -> List[str]:
    threads = max(1, int(threads))
    cut = ["-t", f"{chain['seconds']:.3f}"] if chain.get("seconds") else []
    return (["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-benchmark", "-y",
             "-threads", str(threads), "-filter_threads", str(threads), "-i", src,
             "-map", "0:v:0", "-map", "0:a?", "-vf", chain["vf"],
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", str(threads)]
            + _color_args(info) + cut
            + ["-c:a", "copy", "-metadata", f"comment={TAG}:{CHAIN_VERSION}",
               "-movflags", "+faststart", dst])


# --------------------------------------------------------------------------- #
# The cache: one restored file per (video id, start, length)
# --------------------------------------------------------------------------- #

def _cache_dir() -> str:
    return getattr(config, "ARCHIVE_RESTORE_CACHE_DIR", "") or os.path.join(
        tempfile.gettempdir(), "tg_archive_restore")


def source_key(asset, path: str, seconds: float = 0.0) -> Tuple[str, dict]:
    """("yt-<id>-<start ms>-<length ms>" or "file-<hash>", {"video", "start", "length"}) for a
    clip: a YouTube section by its file name (yt_<id>_<start>_<length>_..., media._yt_fetch) or
    its link and moment, anything else by its bytes."""
    name = os.path.basename(path or "")
    m = _YT_SECTION.match(name)
    if m:
        vid, start, length = m.group(1), int(m.group(2)), int(m.group(3))
        return f"yt-{vid}-{start}-{length}", {"video": vid, "start": start / 1000.0, "length": length / 1000.0}
    url = str(getattr(asset, "url", "") or "")
    moment = getattr(asset, "moment", None) or {}
    m = _YT_ID.search(url)
    if m and moment.get("start") is not None:
        start = int(round(float(moment.get("start") or 0) * 1000))
        length = int(round(float(getattr(asset, "duration", 0) or seconds or 0) * 1000))
        return (f"yt-{m.group(1)}-{start}-{length}",
                {"video": m.group(1), "start": start / 1000.0, "length": length / 1000.0})
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        h.update(str(size).encode())
        with open(path, "rb") as fh:
            h.update(fh.read(1 << 16))
            if size > 1 << 17:
                fh.seek(-(1 << 16), os.SEEK_END)
                h.update(fh.read(1 << 16))
    except OSError:
        h.update(path.encode("utf-8", "replace"))
    return f"file-{h.hexdigest()[:20]}", {}


def _cached(key: str) -> str:
    p = os.path.join(_cache_dir(), f"{key}.mp4")
    if not (os.path.isfile(p) and os.path.getsize(p) > 10_000):
        return ""
    try:
        os.utime(p)                             # recently used: pruned last
    except OSError:
        pass
    return p


def _store(key: str, path: str) -> None:
    d = _cache_dir()
    try:
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, f".{key}.{os.getpid()}.{threading.get_ident()}.part")
        shutil.copyfile(path, tmp)
        os.replace(tmp, os.path.join(d, f"{key}.mp4"))
        _prune(d, float(getattr(config, "ARCHIVE_RESTORE_CACHE_MB", 2048)) * 1e6)
    except OSError as e:
        print(f"[restore] cache write failed: {e}", flush=True)


def _prune(d: str, cap: float) -> None:
    """The oldest cached files go until the cache is under `cap` bytes."""
    try:
        files = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(d)
                 if e.is_file() and e.name.endswith(".mp4")]
    except OSError:
        return
    total = sum(s for _t, s, _p in files)
    for _t, s, p in sorted(files):
        if total <= cap:
            break
        try:
            os.remove(p)
            total -= s
        except OSError:
            pass


def _key_lock(key: str) -> threading.Lock:
    with _LOCK:
        return _KEY_LOCKS.setdefault(key, threading.Lock())


# --------------------------------------------------------------------------- #
# One clip, and a job's clips
# --------------------------------------------------------------------------- #

def _measure(asset, path: str) -> dict:
    """Everything decide() and plan() read, measured on the file."""
    info = {"archive": archive_marked(asset)}
    if not info["archive"]:
        return info
    info.update(probe(path))
    if not info.get("w") or info.get("tagged"):
        return info
    ok, why = decide(info)                     # the cheap verdicts first (vertical, too long ...)
    if not ok and why not in ("sharp",):
        return info
    try:
        from . import sharpness
        w_eff, h_eff = sharpness.clip_detail(path)
        info["real_lines"] = int(min(w_eff, h_eff)) if w_eff else 0
    except Exception:  # noqa: BLE001 - unmeasured: decided on the file's lines
        info["real_lines"] = 0
    if decide(info)[0] or why == "sharp":
        info.update(analyse(path))
        info["mono"] = monochrome(path, float(info.get("seconds") or 0.0))
    return info


def restore_clip(asset, path: str, deadline: float = 0.0, threads: int = 4) -> dict:
    """
    Restore one clip in place when it is archive film that needs it. Returns a record
    {"file", "restored", "why", ...}; the original file stays on any failure or timeout.
    """
    rec: dict = {"file": os.path.basename(path or ""), "restored": False}
    t0 = time.time()
    if os.path.splitext(path or "")[1].lower() not in (".mp4", ".m4v", ".mov"):
        # The restored file is an MP4 written under the clip's own name.
        rec["why"] = "modern" if not archive_marked(asset) else "not an mp4"
        return rec
    try:
        info = _measure(asset, path)
    except Exception as e:  # noqa: BLE001 - a check that breaks restores nothing
        rec.update(why=f"unreadable ({type(e).__name__})")
        return rec
    ok, why = decide(info)
    rec["why"] = why
    if not ok:
        return rec
    key_base, where = source_key(asset, path, float(info.get("seconds") or 0.0))
    rec.update(where)
    chain = plan(info)
    # The same moment restored by the same chain (its filters carry the geometry and the steps).
    key = f"{key_base}-{hashlib.md5(chain['vf'].encode('utf-8')).hexdigest()[:10]}"
    rec.update(src=f"{info['w']}x{info['h']}@{info.get('fps', 0):g}", real=int(info.get("real_lines") or 0),
               steps=chain["steps"], size=chain["size"])
    with _key_lock(key):
        hit = _cached(key)
        if hit:
            try:
                tmp = path + ".ar.part"
                shutil.copyfile(hit, tmp)
                os.replace(tmp, path)
                rec.update(restored=True, cached=True, seconds=round(time.time() - t0, 2), cpu=0.0)
                _note(path, rec, info)
                return rec
            except OSError:
                pass
        left = float(getattr(config, "ARCHIVE_RESTORE_CLIP_SECONDS", 90.0))
        if deadline:
            left = min(left, deadline - time.time())
        if left < 5.0:
            rec["why"] = "time box"
            return rec
        tmp = path + ".ar.mp4"
        cmd = command(path, tmp, info, chain, threads)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=left)
        except subprocess.TimeoutExpired:
            _drop(tmp)
            rec.update(why="timeout", seconds=round(time.time() - t0, 2))
            print(f"[restore] {rec['file']}: timed out after {left:.0f} s; the original stays", flush=True)
            return rec
        except OSError as e:
            _drop(tmp)
            rec.update(why=f"ffmpeg missing ({e.__class__.__name__})")
            return rec
        if p.returncode != 0 or not _playable(tmp, float(info.get("seconds") or 0.0)):
            _drop(tmp)
            lines = [l for l in (p.stderr or "").strip().splitlines() if l and not l.startswith("bench:")]
            tail = (lines[-1] if p.returncode else "shorter or unreadable output")[:120] if lines else "no output"
            rec.update(why=f"failed: {tail}", seconds=round(time.time() - t0, 2))
            print(f"[restore] {rec['file']}: {rec['why']}; the original stays", flush=True)
            return rec
        m = _BENCH.findall(p.stderr or "")
        cpu = round(float(m[-1][0]) + float(m[-1][1]), 1) if m else None
        os.replace(tmp, path)
        rec.update(restored=True, cached=False, seconds=round(time.time() - t0, 2), cpu=cpu)
        _store(key, path)
    _note(path, rec, info)
    print(f"[restore] {rec['file']}: {rec['src']} -> {chain['size'][0]}x{chain['size'][1]} "
          f"({', '.join(chain['steps'])}) in {rec['seconds']} s", flush=True)
    return rec


def _note(path: str, rec: dict, info: dict) -> None:
    from . import upscale
    with _LOCK:
        RESTORED[os.path.abspath(path)] = dict(rec)
    with upscale._LOCK:
        # The lines the picture had: src/reframe.py must not push into the blow-up.
        upscale.UPSCALED[os.path.abspath(path)] = int(info.get("real_lines") or min(info["w"], info["h"]))


def _playable(path: str, seconds: float) -> bool:
    """A real video at least as long as the original, give or take two frames: the renderer
    slows a clip shorter than its scene (SceneClip.tsx), so a restore must never shorten one."""
    got = probe(path) if os.path.isfile(path) and os.path.getsize(path) > 10_000 else {}
    if not got.get("w"):
        return False
    return not seconds or got.get("seconds", 0.0) >= seconds - 0.07


def _drop(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def restore_assets(assets: Iterable, box_seconds: float = 0.0) -> dict:
    """
    Restore a job's archive clips in parallel within the time box
    (ARCHIVE_RESTORE_SECONDS): ARCHIVE_RESTORE_PARALLEL clips at once (0 =
    the machine's CPUs / ARCHIVE_RESTORE_THREADS), each ffmpeg on
    ARCHIVE_RESTORE_THREADS threads. A clip not started before the box ends
    is left as it is. Returns the report recorded in meta.sourcing.
    """
    t0 = time.time()
    box = float(box_seconds or getattr(config, "ARCHIVE_RESTORE_SECONDS", 240.0))
    deadline = t0 + box
    seen, todo = set(), []
    for a in assets or ():
        path = getattr(a, "local_path", "") or ""
        if not a or getattr(a, "kind", "") != "video" or not path or path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        todo.append((a, path))
    threads = max(1, int(getattr(config, "ARCHIVE_RESTORE_THREADS", 4)))
    parallel = int(getattr(config, "ARCHIVE_RESTORE_PARALLEL", 0)) or max(1, min(8, (os.cpu_count() or 4) // threads))
    records: List[dict] = []

    def run(item):
        a, path = item
        if time.time() > deadline - 5.0:
            return {"file": os.path.basename(path), "restored": False,
                    "why": "time box" if archive_marked(a) else "modern"}
        try:
            return restore_clip(a, path, deadline=deadline, threads=threads)
        except Exception as e:  # noqa: BLE001 - never fails a video
            return {"file": os.path.basename(path), "restored": False, "why": f"error ({type(e).__name__})"}

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(todo))),
                                thread_name_prefix="restore") as pool:
            records = list(pool.map(run, todo))
    done = [r for r in records if r.get("restored")]
    skipped: Dict[str, int] = {}
    for r in records:
        if not r.get("restored") and r.get("why") != "modern":
            k = str(r.get("why") or "")
            k = "failed" if k.startswith(("failed", "error", "ffmpeg missing")) else k
            skipped[k] = skipped.get(k, 0) + 1
    report = {
        "on": True, "chain": CHAIN_VERSION, "checked": len(records),
        "archive": sum(1 for r in records if r.get("why") != "modern"),
        "restored": len(done), "cached": sum(1 for r in done if r.get("cached")),
        "seconds": round(time.time() - t0, 1), "box": box,
        "cpuSeconds": round(sum(float(r.get("cpu") or 0.0) for r in done), 1),
        "skipped": skipped,
        "clips": [{k: r[k] for k in ("file", "video", "start", "length", "src", "real", "size", "steps",
                                     "seconds", "cpu", "cached") if k in r} for r in done],
    }
    with _LOCK:
        LAST.clear()
        LAST.update(report)
    print(f"[restore] {report['restored']} of {report['archive']} archive clip(s) restored "
          f"({report['cached']} from cache) in {report['seconds']} s; skipped {skipped}", flush=True)
    return report
