"""
Pixel and file checks on sourced media, plus the clean-cut trimming.

Everything here judges bytes on disk: is it a real video, is it vertical,
blurry, near-black or frozen, does it carry burned-in captions or a static
corner watermark, and where are its shot changes so a clip can be cut from
a clean stretch. No network, no model calls. media.py re-exports every
name so existing callers and tests are unchanged.
"""
import os
import re
import subprocess
from typing import List, Optional, Tuple

from . import config


_STILL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _is_still(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in _STILL_EXTS


def _video_seconds(path: str) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30)
        return max(0.0, float((p.stdout or "0").strip() or 0))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _gray_frames(path: str, count: int = 4, w: int = 320, h: int = 180):
    """
    `count` evenly spaced frames as (h, w) uint8 arrays, [] if unreadable.

    A still yields its one frame. The old filter (`fps=N/N`) produced ZERO
    frames from a single image - ffmpeg's fps filter drops a lone frame with
    no duration - so every web photo and archive still was judged
    "unreadable" and thrown away after passing vision. That one bug sent
    18 of 23 beats of an image-heavy story into the slow replacement pass,
    where every replacement photo failed the same way. For video it also
    sampled only the first `count` seconds rather than across the clip.
    """
    try:
        import numpy as np
    except ImportError:
        return []
    if _is_still(path):
        vf, frames = f"scale={w}:{h},format=gray", 1
    else:
        seconds = _video_seconds(path)
        rate = f"{count}/{seconds:.3f}" if seconds > count else "1"
        vf, frames = f"fps={rate},scale={w}:{h},format=gray", count
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", vf,
         "-frames:v", str(frames), "-f", "rawvideo", "-"],
        capture_output=True, timeout=90)
    buf = p.stdout or b""
    n = len(buf) // (w * h)
    if n == 0:
        return []
    import numpy as np
    return [np.frombuffer(buf[i * w * h:(i + 1) * w * h], dtype="uint8").reshape(h, w)
            for i in range(n)]


def has_burned_captions(path: str, count: int = 4) -> bool:
    """
    True when a clip carries text that is not ours: hardsubs, or a UI.

    Two separate failures, one cheap geometric test each:

    * **Subtitles** sit in the lower third and make a tight horizontal band of
      many strong vertical edges - letter strokes. Scenery rarely does that in
      a band a few rows tall.
    * **Screen recordings** (gameplay HUDs, leaderboards, dashboards, slides)
      spread that same signature across the whole frame. The clip that forced
      this was a Diablo IV leaderboard with a webcam in the corner: no
      subtitles at all, and unusable as documentary footage.

    Runs on the downloaded section, because a title never admits to either.
    """
    try:
        import numpy as np
    except ImportError:
        return False
    frames = _gray_frames(path, count)
    if not frames:
        return False

    sub_hits = texty_hits = 0
    for fr in frames:
        h, w = fr.shape
        rows = _texty_rows(fr, np)
        if not rows:
            continue
        lower = [r for r in rows if r >= h * 0.62]
        # a caption band: a short contiguous run down in the lower third
        if lower and _longest_run(lower) >= 3 and len(lower) <= h * 0.20:
            sub_hits += 1
        # a UI: text-like rows scattered over much of the frame height
        if len(rows) >= h * 0.14 and (max(rows) - min(rows)) > h * 0.45:
            texty_hits += 1

    need = max(2, len(frames) // 2)
    return sub_hits >= need or texty_hits >= need


def _texty_rows(frame, np) -> list:
    """Row indices whose strong-vertical-edge count looks like a line of text."""
    h, w = frame.shape
    a = frame.astype("int16")
    edges = np.abs(np.diff(a, axis=1)) > 48
    per_row = edges.sum(axis=1)
    return [i for i, c in enumerate(per_row) if c > w * 0.16]


def _longest_run(rows: list) -> int:
    run = best = 1
    for a, b in zip(rows, rows[1:]):
        run = run + 1 if b - a <= 2 else 1
        best = max(best, run)
    return best


def playable_video(path: str, min_seconds: float = 0.5) -> bool:
    """A real, decodable video: a video stream at least min_seconds long."""
    try:
        if os.path.getsize(path) < 2_000:
            return False
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name:format=duration",
                            "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        lines = [l.strip() for l in (p.stdout or "").splitlines() if l.strip()]
        codec = next((l for l in lines if not re.fullmatch(r"[\d.]+", l)), "")
        seconds = max((float(l) for l in lines if re.fullmatch(r"[\d.]+", l)), default=0.0)
        return bool(codec) and seconds >= min_seconds
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def clip_quality(path: str, min_height: int = 0) -> tuple:
    """
    (ok, reason) for a sourced file. Reason is empty when it passes.

    Everything here is a failure that only shows up once the bytes are on disk,
    which is why the title heuristics upstream cannot catch it:

    * somebody else's text - hardsubs, or a UI (see has_burned_captions)
    * near-black - a fade, a night shot, or a download that grabbed the gap
      between scenes
    * frozen - a still image uploaded as a video, or a held title card, which
      reads as a broken player rather than a cut
    """
    if not path or not os.path.exists(path):
        return False, "missing"
    try:
        import numpy as np
    except ImportError:
        return True, ""
    frames = _gray_frames(path, 4)
    if not frames:
        return False, "unreadable"

    if _is_still(path):
        # Text on a still was already judged by vision, and a document photo
        # is text by design - the caption detector would reject every one.
        # Frozen means nothing for a photo. Only a black frame is a failure.
        return (False, "near-black") if float(frames[0].mean()) < 26 else (True, "")

    if has_burned_captions(path):
        return False, "burned-in text or UI"

    # A phone or screen recording turned sideways: on a 16:9 canvas it is
    # pillarboxed with blurred edges and reads as a mistake (one slipped
    # into a real render as a vertical dashboard capture).
    w, h = _video_dims(path)
    if w and h and w < h * 1.2:
        return False, "vertical or square video"
    if min_height and h and h < min_height:
        # A 360p upload blown up to 1080p reads as a mistake next to sharp clips.
        return False, f"low resolution ({h}p)"

    dark = sum(1 for f in frames if float(f.mean()) < 26)
    if dark >= max(2, len(frames) // 2):
        return False, "near-black"

    if len(frames) >= 2:
        deltas = [float(np.abs(a.astype("int16") - b.astype("int16")).mean())
                  for a, b in zip(frames, frames[1:])]
        if max(deltas) < 1.2:
            return False, "frozen frame"
    if _blurry(frames, np):
        return False, "blurry"
    if _corner_watermark(frames, np):
        return False, "corner watermark"
    return True, ""


def _video_dims(path: str) -> tuple:
    """(width, height) of the first video stream, (0, 0) when unknown."""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=20)
        a, b = (p.stdout.strip().splitlines() or [""])[0].split(",")[:2]
        return int(a), int(b)
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return 0, 0


def _blurry(frames, np) -> bool:
    """
    Out of focus or badly upscaled in every sampled frame.

    The variance of a Laplacian is the standard focus measure: sharp detail
    gives strong second derivatives, blur flattens them. Judged on the
    320x180 grey frames; the threshold is deliberately low so only clips
    that are soft everywhere are dropped, not a shallow-focus shot.
    """
    if not frames:
        return False
    scores = []
    for f in frames:
        a = f.astype("float32")
        lap = (4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:])
        scores.append(float(lap.var()))
    scores.sort()
    return scores[len(scores) // 2] < 12.0


def _corner_watermark(frames, np) -> bool:
    """
    A channel logo or stock watermark parked in a corner.

    Across a clip the picture moves but a burned-in logo does not: a corner
    box that is edge-dense yet nearly unchanged between frames while the
    rest of the frame changes is a watermark. Needs three frames and real
    motion elsewhere, so a static landscape is never mistaken for one.
    """
    if len(frames) < 3:
        return False
    h, w = frames[0].shape
    bh, bw = max(8, int(h * 0.16)), max(8, int(w * 0.22))
    corners = {"tl": (slice(0, bh), slice(0, bw)), "tr": (slice(0, bh), slice(w - bw, w)),
               "bl": (slice(h - bh, h), slice(0, bw)), "br": (slice(h - bh, h), slice(w - bw, w))}
    arr = [f.astype("int16") for f in frames]
    whole = float(np.mean([np.abs(a - b).mean() for a, b in zip(arr, arr[1:])]))
    if whole < 3.0:
        return False
    for ys, xs in corners.values():
        boxes = [a[ys, xs] for a in arr]
        moving = float(np.mean([np.abs(a - b).mean() for a, b in zip(boxes, boxes[1:])]))
        gx = np.abs(np.diff(boxes[0], axis=1)); gy = np.abs(np.diff(boxes[0], axis=0))
        edges = float((gx > 40).mean() + (gy > 40).mean()) / 2
        if edges > 0.05 and moving < whole * 0.25:
            return True
    return False


_PTS_RE = re.compile(r"pts_time:\s*([0-9.]+)")


def scene_cuts(path: str, threshold: Optional[float] = None, timeout: int = 120) -> List[float]:
    """Seconds at which ffmpeg's scene detector sees a shot change."""
    thr = config.SHOT_CUT_THRESHOLD if threshold is None else threshold
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-an",
           "-vf", f"select='gt(scene,{thr})',showinfo", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    return sorted(float(m) for m in _PTS_RE.findall(p.stderr or ""))


def clean_window(total: float, cuts: List[float], need: float, prefer: float) -> tuple:
    """
    (offset, clean, cuts_inside): where to cut `need` seconds out of a file
    `total` seconds long whose shot changes are at `cuts`, preferring the
    stretch that holds the intended moment at `prefer`. `clean` is False when
    no stretch is long enough (rapid cutting): the caller keeps the moment
    and scores the timing down.
    """
    inner = sorted(c for c in cuts if 0.2 < c < total - 0.2)
    if total <= 0:
        return 0.0, True, 0
    edges = [0.0] + inner + [total]
    windows = list(zip(edges, edges[1:]))
    for a, b in windows:
        if a <= prefer < b and b - a >= need:
            return max(a, min(prefer, b - need)), True, len(inner)
    a, b = max(windows, key=lambda w: w[1] - w[0])
    if b - a >= need:
        return a, True, len(inner)
    return max(0.0, min(prefer, total - need)), False, len(inner)


def trim_clip(path: str, offset: float, seconds: float, timeout: int = 180) -> str:
    """`seconds` of `path` from `offset`, re-encoded so the cut is exact; '' on failure."""
    base, _ = os.path.splitext(path)
    out = f"{base}_c{int(round(offset * 10)):05d}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, offset):.2f}", "-i", path,
           "-t", f"{seconds:.2f}", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out if playable_video(out, min_seconds=min(1.0, seconds * 0.5)) else ""


def tidy_clip(path: str, need: float, prefer: float) -> tuple:
    """
    (path, clean, cuts) for a downloaded section: the `need` seconds cut from
    its cleanest stretch around `prefer`. The original file is replaced.
    """
    if not path or not config.CLEAN_CUTS:
        return path, True, 0
    total = _video_seconds(path)
    if total <= need + 0.6:
        return path, True, 0             # nothing to choose from
    offset, clean, inner = clean_window(total, scene_cuts(path), need, prefer)
    out = trim_clip(path, offset, need + 0.5)
    if not out:
        return path, clean, inner
    try:
        os.remove(path)
    except OSError:
        pass
    if inner:
        print(f"[cut] {os.path.basename(out)}: {inner} shot change(s) in the section, "
              f"clip from {offset:.1f}s{'' if clean else ' (no clean stretch long enough)'}",
              flush=True)
    return out, clean, inner
