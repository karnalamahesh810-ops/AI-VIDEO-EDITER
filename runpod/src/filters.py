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
    if config.NEWS_FOOTAGE:
        # A news report's banner, ticker or subtitle band is allowed (GoMotion
        # shows them); a screen recording's text all over the frame is not.
        return texty_hits >= need
    return sub_hits >= need or texty_hits >= need


def text_page_still(path: str) -> bool:
    """
    True for a still that is a page of text - a presentation slide, a web or
    app screenshot, a scanned document - rather than a photograph: mostly
    white, with rows of letters over much of it. Checked without any model,
    because it slipped through when vision was down (a "Front Range drought
    response" slide stood in for farms, dams and rivers).
    """
    try:
        import numpy as np
    except ImportError:
        return False
    if not _is_still(path):
        return False
    frames = _gray_frames(path, 1, w=480, h=270)
    if not frames:
        return False
    fr = frames[0]
    bright = float((fr > 225).mean())
    rows = _texty_rows(fr, np)
    return bright >= 0.45 and len(rows) >= fr.shape[0] * 0.10


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


def min_image_long_side() -> int:
    """The smallest usable photo: lower when the Real-ESRGAN upscaler is
    installed, because a 700 px photo then reaches 1920 px with real detail."""
    if not config.MIN_IMAGE_LONG_SIDE:
        return 0
    try:
        from . import upscale
        if upscale.available():
            return min(config.MIN_IMAGE_LONG_SIDE, config.MIN_IMAGE_LONG_SIDE_UPSCALED)
    except Exception:  # noqa: BLE001
        pass
    return config.MIN_IMAGE_LONG_SIDE


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
        # Text on a still is judged by the caller (a document beat wants it;
        # see text_page_still). Frozen means nothing for a photo.
        if float(frames[0].mean()) < 26:
            return False, "near-black"
        # A thumbnail blown up to 1080p reads as a mistake: a 55 KB slide
        # screenshot filled nine scenes of the Glen Canyon video.
        w, h = _video_dims(path)
        floor = min_image_long_side()
        if floor and w and h and max(w, h) < floor:
            return False, f"low resolution ({w}x{h})"
        return True, ""

    if has_burned_captions(path):
        return False, "burned-in text or UI"

    # A phone or screen recording turned sideways: on a 16:9 canvas it is
    # pillarboxed with blurred edges and reads as a mistake (one slipped
    # into a real render as a vertical dashboard capture).
    w, h = _video_dims(path)
    if w and h and w < h * 1.2:
        if not config.ALLOW_VERTICAL:
            return False, "vertical or square video"
        # Framed on a blurred fill before render (upscale.frame_vertical):
        # its width is what ends up as the picture's height.
        h = min(w, h)
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
    if not config.NEWS_FOOTAGE and _corner_watermark(frames, np):
        # With news footage on, a station logo in a corner is expected.
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
# ffmpeg's metadata filter (print mode): "frame:44   pts:132132  pts_time:1.46667", then one line per key.
_FRAME_RE = re.compile(r"frame:\s*(\d+)\s+pts:\s*\S+\s+pts_time:\s*([0-9.]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
# The frames either side of a softer jump are compared this small, in grey (shot_changes).
_CMP_W, _CMP_H = 48, 27
# The frames around a softer jump it must stand out from (seconds either side).
_AROUND_SECONDS = 0.5
# The frames after a softer jump whose steadiness is measured (shot_changes, SHOT_CUT_STEADY).
_STEADY_FRAMES = 3
# A small grey frame whose pixels vary less than this (standard deviation) has no structure to
# correlate - black, a white flash, a flat sky (_alike).
_FLAT = 3.0
# How far the picture may move between two of those frames (pixels of the 48x27 copy: about an
# eighth of the width, a sixth of the height) and still be the same picture moved (_moved).
_MOVE_X, _MOVE_Y = 6, 3
# A jump whose picture is back within this long, either side, is a flash - lightning, a strobe,
# a camera flash, a flash frame - not a shot change (_flash) ...
_FLASH_SECONDS = 0.4
# ... where the frames before it and after it, the flash itself left out, are this alike (_moved).
_COMES_BACK = 0.9


def _scan(path: str, timeout: int = 120, frames: bool = False) -> tuple:
    """
    ([(frame number, seconds, scene score)] for every frame in order - the
    first scores 0 - and, with `frames`, every frame as a small grey array
    (None without numpy, or when the decode and the scores disagree). One
    decode of the file either way.
    """
    np = None
    if frames:
        try:
            import numpy as np  # noqa: F811
        except ImportError:
            np = None
    vf = "select='gte(scene,0)',metadata=print:key=lavfi.scene_score"
    if np is not None:
        vf += f",scale={_CMP_W}:{_CMP_H},format=gray"
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-an", "-vf", vf]
    # The raw frames exactly as decoded: the rawvideo muxer is constant-rate by default, so on a
    # variable-rate file (a phone clip, a webm) or one whose picture starts after its sound ffmpeg
    # would duplicate or drop frames after the metadata filter numbered them, and picture n would
    # no longer be frame n.
    raw = ["-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    cmd += raw if np is not None else ["-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if np is not None and p.returncode != 0 and b"fps_mode" in (p.stderr or b""):
            # An ffmpeg older than 5.0 has no -fps_mode: the frames as it writes them, checked below.
            p = subprocess.run(cmd[:-len(raw)] + ["-f", "rawvideo", "-"], capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return [], None
    rows, current = [], None
    for line in (p.stderr or b"").decode("utf-8", "replace").splitlines():
        m = _FRAME_RE.search(line)
        if m:
            current = (int(m.group(1)), float(m.group(2)))
            continue
        s = _SCORE_RE.search(line)
        if s and current is not None:
            rows.append((current[0], current[1], float(s.group(1))))
            current = None
    pictures = None
    if np is not None and rows and p.stdout:
        size = _CMP_W * _CMP_H
        n = len(p.stdout) // size
        # One picture for every numbered frame, no more and no fewer: anything else means the
        # pictures and the scores no longer line up, and shot_changes keeps to the hard threshold.
        if n and n == max(r[0] for r in rows) + 1:
            pictures = np.frombuffer(p.stdout[:n * size], dtype=np.uint8).reshape(n, _CMP_H, _CMP_W)
    return rows, pictures


def scene_scores(path: str, timeout: int = 120) -> List[Tuple[float, float]]:
    """[(seconds, ffmpeg scene score)] for every frame of `path`, in order ([] when unreadable)."""
    return [(t, s) for _n, t, s in _scan(path, timeout)[0]]


def same_picture(a, b) -> float:
    """
    How alike two small grey frames are in structure: the normalised
    correlation of their pixels, 1.0 the same picture (whatever its
    brightness), near 0 two different shots.
    """
    x = a.astype("float32") - float(a.mean())
    y = b.astype("float32") - float(b.mean())
    d = float(((x * x).sum() * (y * y).sum()) ** 0.5)
    return float((x * y).sum() / d) if d > 0 else 1.0


def _alike(a, b) -> float:
    """
    same_picture, where a featureless frame (under _FLAT: black, a white
    flash, a flat sky) has no structure to correlate: two of them are the same
    picture when about as bright, one against a frame with structure never.
    """
    fa, fb = float(a.std()), float(b.std())
    if fa < _FLAT or fb < _FLAT:
        return 1.0 if fa < _FLAT and fb < _FLAT and abs(float(a.mean()) - float(b.mean())) < 24.0 else 0.0
    return same_picture(a, b)


def _moved(a, b) -> float:
    """
    _alike of two small frames allowing for the picture having moved between
    them - a pan, a tilt, a handheld camera's jolt: the best over shifts of up
    to _MOVE_X and _MOVE_Y pixels (a sixth of a smaller crop), each on the
    part both frames show.
    """
    h, w = a.shape
    rx, ry = min(_MOVE_X, w // 6), min(_MOVE_Y, h // 6)
    best = _alike(a, b)
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            if dx or dy:
                best = max(best, _alike(a[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)],
                                        b[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)]))
    return best


def _flash(rows: List[tuple], k: int, pictures) -> bool:
    """
    The jump at rows[k] is a flash, not a cut: the picture is back within
    _FLASH_SECONDS - a frame just before the jump and one shortly after it
    (_moved at least _COMES_BACK) show the same picture. Lightning, a strobe or
    a camera flash scores two hard jumps (on, then off) that otherwise read as
    two shot changes - a storm clip with a few strikes in a row used to lose
    its in-point to them, or be thrown away (clean_window).
    """
    t = rows[k][1]

    def pick(js, targets):
        got = []
        for want in targets:
            near = min(js, key=lambda j: abs(abs(rows[j][1] - t) - want), default=None)
            if near is not None and near not in got:
                got.append(near)
        return [rows[j][0] for j in got]
    before, after = [], []
    for j in range(k - 1, -1, -1):
        if t - rows[j][1] > _FLASH_SECONDS:
            break
        before.append(j)
    for j in range(k + 1, len(rows)):
        if rows[j][1] - t > _FLASH_SECONDS:
            break
        after.append(j)
    if not before or not after:
        return False
    # Only the part of the frame the jump changed is compared: a news clip's pillarbox panels and
    # channel bug stay put across a real cut and would make any two of its shots look alike.
    box = _changed_box(pictures[rows[k][0] - 1], pictures[rows[k][0]]) if rows[k][0] > 0 else None
    if box is None:
        return False
    ys, xs = box
    b = pick(before, (0.0, _FLASH_SECONDS / 2, _FLASH_SECONDS))
    a = pick(after, (_FLASH_SECONDS / 3, 2 * _FLASH_SECONDS / 3, _FLASH_SECONDS))
    return any(_moved(pictures[x][ys, xs], pictures[y][ys, xs]) >= _COMES_BACK for x in b for y in a)


def _changed_box(a, b):
    """(rows, columns) slices of the part of two small frames that differs, or None when too little does."""
    import numpy as np
    diff = np.abs(a.astype("int16") - b.astype("int16")) > 12
    rows = np.flatnonzero(diff.mean(axis=1) > 0.2)
    cols = np.flatnonzero(diff.mean(axis=0) > 0.2)
    if len(rows) < 8 or len(cols) < 12:
        return None
    return slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1)


def _new_shot(pictures, n: int) -> bool:
    """
    Frame n opens a new shot, not a camera starting to move inside one: ffmpeg's
    score answers a change in motion, not motion, so a handheld or eyewitness
    camera that starts to swing jumps it for one frame as a cut does. Not a new
    shot when frame n is frame n-1's picture moved (_moved at least
    SHOT_CUT_MOVED), or when the picture after it does not hold steady - the
    median _moved of each of its next _STEADY_FRAMES frames to the one after
    under SHOT_CUT_STEADY: a swing too fast for _moved, a zoom, a spinning
    transition. Measured on 81 softer jumps in real downloads (2026-10-05):
    swings and jolts 0.82-0.97 moved, real cuts 0.79 at most; after a real cut
    the new shot holds at 0.87-1.0 (one cut into a fast zoom, 0.58, is missed -
    as the fixed threshold missed it), inside a swing 0.53-0.83.
    """
    import statistics
    moved = float(getattr(config, "SHOT_CUT_MOVED", 0.0) or 0.0)
    if moved > 0 and _moved(pictures[n - 1], pictures[n]) >= moved:
        return False
    steady = float(getattr(config, "SHOT_CUT_STEADY", 0.0) or 0.0)
    if steady > 0:
        pairs = [_moved(pictures[j], pictures[j + 1]) for j in range(n, min(n + _STEADY_FRAMES, len(pictures) - 1))]
        if not pairs or statistics.median(pairs) < steady:
            return False
    return True


def shot_changes(rows: List[tuple], pictures=None, hard: Optional[float] = None) -> List[float]:
    """
    Seconds of every shot change in `rows` ((frame, seconds, score) from _scan):
    a score above SHOT_CUT_THRESHOLD (`hard`), as before; and a softer jump - at
    least SHOT_CUT_SOFT_THRESHOLD and SHOT_CUT_RATIO times the median of the
    frames within half a second - whose two frames do not show the same picture
    (same_picture under SHOT_CUT_SAME_PICTURE): the Glen Canyon opening's cut
    between two grey shots scored 0.36 against ~0.02 around it, an old film's
    exposure flicker 0.23 with the picture unchanged (0.87) - and that opens a
    new shot (_new_shot: not the same picture moved, and steady after it - a
    handheld camera starting to swing jumps the score too). With the frames, no
    jump whose picture is back within _FLASH_SECONDS counts, hard or soft
    (_flash: lightning, a strobe). The softer jumps need the frames
    (`pictures`, one for every numbered frame): without them, or when they do
    not line up with `rows`, only the fixed threshold counts.
    """
    import statistics
    hard = config.SHOT_CUT_THRESHOLD if hard is None else hard
    soft = float(getattr(config, "SHOT_CUT_SOFT_THRESHOLD", 0.0) or 0.0)
    ratio = float(getattr(config, "SHOT_CUT_RATIO", 4.0) or 4.0)
    alike = float(getattr(config, "SHOT_CUT_SAME_PICTURE", 0.75) or 0.75)
    seen = _lined_up(rows, pictures)
    out = []
    for k, (n, t, s) in enumerate(rows):
        if s > hard:
            if not (seen and k and _flash(rows, k, pictures)):
                out.append(t)
            continue
        if not seen or soft <= 0 or s < soft or k == 0 or n == 0:
            continue
        around = [x for (_m, u, x) in rows[max(0, k - 60):k + 61] if 0 < abs(u - t) <= _AROUND_SECONDS]
        if not around or s < ratio * max(statistics.median(around), 0.005):
            continue
        if _alike(pictures[n - 1], pictures[n]) >= alike:
            continue                    # the same picture brighter or darker: a flicker or a flash, not a cut
        if not _new_shot(pictures, n):
            continue                    # the same picture moved, or moving on: a camera starting to swing
        if _flash(rows, k, pictures):
            continue                    # the picture is back a moment later: a flash
        out.append(t)
    return sorted(out)


def _lined_up(rows: List[tuple], pictures) -> bool:
    """`pictures` holds exactly one frame for every frame `rows` numbers (_scan), so picture n is frame n."""
    try:
        return bool(rows) and pictures is not None and len(pictures) == max(r[0] for r in rows) + 1
    except (TypeError, ValueError):
        return False


def scene_cuts(path: str, threshold: Optional[float] = None, timeout: int = 120) -> List[float]:
    """
    Seconds at which a shot changes: ffmpeg's scene score above `threshold`
    when one is given; otherwise shot_changes - above SHOT_CUT_THRESHOLD, or a
    softer jump that stands out from the frames around it and changes the
    picture.
    """
    if threshold is not None:
        return sorted(t for _n, t, s in _scan(path, timeout)[0] if s > threshold)
    rows, pictures = _scan(path, timeout, frames=True)
    return shot_changes(rows, pictures)


def snap_past_cut(start: float, cuts: List[float], guard: Optional[float] = None,
                  pad: Optional[float] = None) -> float:
    """
    An in-point never on the end of a shot: while a shot change lies under
    `guard` (CUT_GUARD_SECONDS) after `start` - or within `pad` before it, its
    frames still the change itself - the start moves to `pad` (CUT_SNAP_PAD)
    past that change.
    """
    guard = config.CUT_GUARD_SECONDS if guard is None else guard
    pad = config.CUT_SNAP_PAD if pad is None else pad
    for _ in range(len(cuts) + 1):
        near = [c for c in cuts if start - pad < c <= start + guard]
        if not near:
            break
        start = max(near) + pad
    return start


# What a cut may come out short of what was asked: two frames, rounding (shotcap.TOLERANCE_FRAMES).
_SHORT_OK = 2 / 30.0


def clean_window(total: float, cuts: List[float], need: float, prefer: float,
                 least: Optional[float] = None) -> tuple:
    """
    (offset, clean, cuts_inside): where to cut `need` seconds out of a file
    `total` seconds long whose shot changes are at `cuts`, preferring the
    stretch that holds the intended moment at `prefer`. A stretch that opens
    on a shot change starts CUT_SNAP_PAD past it, so no frame of the shot
    before shows. `least` (at most `need`, `need` when not given) is the
    shortest clip the caller can still use - what its scene plays, a
    crossfade included - and a stretch that long is clean too. `clean` is
    False when no stretch is long enough (rapid cutting): the caller keeps the
    moment and scores the timing down - but never opens on the last second of
    a shot (snap_past_cut: the start moves past the change and the clip keeps
    its length from later in the file); when that runs too far, the start just
    after another shot change that still leaves `least` (the longest first
    shot, then the nearest the moment). offset None: no start after a shot
    change leaves `least` - nothing usable here.
    """
    inner = sorted(c for c in cuts if 0.2 < c < total - 0.2)
    if total <= 0:
        return 0.0, True, 0
    least = need if least is None else max(0.0, min(need, float(least)))
    pad = config.CUT_SNAP_PAD
    edges = [0.0] + inner + [total]
    # (first usable second, end, where the stretch really starts) - a cut's own frames padded off.
    windows = [(a + (pad if k else 0.0), b, a) for k, (a, b) in enumerate(zip(edges, edges[1:]))]
    longest = max(windows, key=lambda w: w[1] - w[0])
    # The full length first, then two frames short of it (the snap pad alone must not cost a clean
    # stretch), then what the line plays - each in the moment's own stretch first, else the longest.
    for want, short in dict.fromkeys(((need, 0.0), (need, _SHORT_OK), (least, 0.0), (least, _SHORT_OK))):
        for lo, b, a in windows:
            if a <= prefer < b and b - lo >= want - short:
                return max(lo, min(prefer, b - want)), True, len(inner)
        lo, b, _a = longest
        if b - lo >= want - short:
            return lo, True, len(inner)
    moment = max(0.0, min(prefer, total - need))
    start = snap_past_cut(moment, inner)
    if total - start >= least - _SHORT_OK:
        return start, False, len(inner)
    # The snap ran past what the file has left (a run of short shots): the start just after another
    # shot change - a shot's first frame, never its last second - that still leaves enough: the
    # longest first shot (up to CUT_GUARD_SECONDS), then the nearest the moment.
    guard = float(config.CUT_GUARD_SECONDS)
    after = []
    for k, c in enumerate(inner):
        x = c + pad
        first = (inner[k + 1] if k + 1 < len(inner) else total) - x
        if first >= pad and total - x >= least - _SHORT_OK:
            after.append((round(min(guard, first), 3), -abs(x - moment), x))
    if after:
        return max(after)[2], False, len(inner)
    return None, False, len(inner)


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


def _drop(path: str, why: str, inner: int) -> tuple:
    print(f"[cut] {os.path.basename(path)}: {why} - not used", flush=True)
    try:
        os.remove(path)
    except OSError:
        pass
    return "", False, inner


def tidy_clip(path: str, need: float, prefer: float, least: Optional[float] = None) -> tuple:
    """
    (path, clean, cuts) for a downloaded section: the `need` seconds cut from
    its cleanest stretch around `prefer`, never opening on the end of a shot
    (clean_window). `least` (at most `need`; `need` when not given): the
    shortest clip the caller can use - what its scene plays at real speed. The
    original file is replaced. ("", False, cuts) when no start just after a
    shot change leaves `least`: the file is gone and the caller tries its next
    candidate or leaves the line to the fallback ladder - a clip is never
    slowed.
    """
    if not path or not config.CLEAN_CUTS:
        return path, True, 0
    total = _video_seconds(path)
    if total <= 0:
        return path, True, 0             # unreadable here: kept as it came
    cuts = scene_cuts(path)
    if total <= need + 0.6:
        # Nothing to choose a stretch from - but no clip opens on the last second of a shot.
        inner = sum(1 for c in cuts if 0.2 < c < total - 0.2)
        start = snap_past_cut(0.0, cuts)
        clean = not any(start < c < min(total, start + need) - 0.2 for c in cuts)
        if not start:
            return path, clean, inner
        floor = need if least is None else min(need, float(least))
        if total - start < floor - _SHORT_OK:
            return _drop(path, f"opens {start - config.CUT_SNAP_PAD:.2f}s before a shot change and the rest "
                               f"is too short for {floor:.1f}s", inner)
        out = trim_clip(path, start, need + 0.5)
        if not out:
            return path, False, inner
        try:
            os.remove(path)
        except OSError:
            pass
        print(f"[cut] {os.path.basename(out)}: clip from {start:.2f}s, past a shot change at its start", flush=True)
        return out, clean, inner
    offset, clean, inner = clean_window(total, cuts, need, prefer, least)
    if offset is None:
        return _drop(path, f"no start after a shot change leaves {need if least is None else least:.1f}s", inner)
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
