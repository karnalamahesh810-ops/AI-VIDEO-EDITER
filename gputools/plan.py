"""
The GPU tools worker's pure helpers (no torch, no GPU): input checks, sizes, frame counts, the 60 fps retiming
schedule and the output keys. Imported by handler.py and the engines; tested on their own in the image build
(tests/test_plan.py) and on any laptop.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

ACTIONS = ("health", "upscale", "interpolate", "music")

# Upscaling (FlashVSR): the used section of a low-resolution clip, not a whole video.
UPSCALE_DEFAULT_LINES = 1080
UPSCALE_MAX_SECONDS = 20.0          # a 3-8 s section in practice; the caller trims first
UPSCALE_MAX_SOURCE_LINES = 1079     # a clip that already has the target lines is not upscaled
VSR_MULTIPLE = 128                  # FlashVSR's sparse-attention windows: both sides a multiple of 128
VSR_TAIL = 4                        # the pipeline drops its last 4 input frames (8n+1 in, 8n-3 out)

# Frame interpolation (RIFE): a clip retimed to the render's frame rate.
INTERP_DEFAULT_FPS = 60.0
INTERP_MAX_SECONDS = 60.0
SCENE_SSIM = 0.2                    # Practical-RIFE's cut test: SSIM of 32x32 thumbnails under this = a cut

# Music (ACE-Step 1.5): an instrumental bed as long as the video (the model's own limit is 10 minutes).
MUSIC_MIN_SECONDS = 10.0
MUSIC_MAX_SECONDS = 600.0
MUSIC_DEFAULT_LUFS = -27.0          # the bundled library tracks' level (timeline.BGM_LUFS): the same 50% mix
MUSIC_CARVE_DB = 3.0
MUSIC_DEFAULT_CAPTION = ("cinematic documentary underscore, instrumental background music, warm pads, soft piano, "
                         "subtle pulse, no vocals")


class InputError(ValueError):
    """The request cannot be run as sent."""


def _num(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return min(hi, max(lo, f))


def _url(inp: Dict[str, Any], key: str = "url") -> str:
    url = str(inp.get(key) or "").strip()
    if not url.startswith("https://"):
        raise InputError(f"{key} must be an https link")
    return url


def _seed(value: Any, default: int = 1247) -> int:
    try:
        return int(value) % 2_147_483_647
    except (TypeError, ValueError):
        return default


def action_of(inp: Dict[str, Any]) -> str:
    if not isinstance(inp, dict):
        raise InputError("input must be an object")
    act = str(inp.get("action") or "").strip().lower()
    if act not in ACTIONS:
        raise InputError(f"action must be one of {', '.join(ACTIONS)}")
    return act


def check_upscale(inp: Dict[str, Any]) -> Dict[str, Any]:
    """url (https), lines 720-2160 (default 1080), start / seconds (the used section; 0 = from the start / all),
    fps 0 or 24-120 (also retime the result with RIFE in the same job), sparse 1.5-2.5, local_range 9 or 11,
    text_guard (default true)."""
    url = _url(inp)
    start = _num(inp.get("start"), 0.0, 36000.0, 0.0)
    seconds = _num(inp.get("seconds"), 0.0, UPSCALE_MAX_SECONDS, 0.0)
    fps = _num(inp.get("fps"), 0.0, 120.0, 0.0)
    return {"url": url, "lines": int(round(_num(inp.get("lines"), 720, 2160, UPSCALE_DEFAULT_LINES))),
            "start": start, "seconds": seconds, "fps": fps if fps >= 24.0 else 0.0,
            "sparse": _num(inp.get("sparse"), 1.5, 2.5, 2.0),
            "local_range": 9 if int(_num(inp.get("local_range"), 9, 11, 11)) < 10 else 11,
            "seed": _seed(inp.get("seed"), 0),
            # lettering keeps the faithful picture (textguard.py); false = FlashVSR everywhere (tests only)
            "text_guard": inp.get("text_guard") is not False}


def check_interpolate(inp: Dict[str, Any]) -> Dict[str, Any]:
    """url (https), fps 24-120 (default 60), start / seconds, scene (the cut threshold, 0-0.9)."""
    url = _url(inp)
    return {"url": url, "fps": _num(inp.get("fps"), 24.0, 120.0, INTERP_DEFAULT_FPS),
            "start": _num(inp.get("start"), 0.0, 36000.0, 0.0),
            "seconds": _num(inp.get("seconds"), 0.0, INTERP_MAX_SECONDS, 0.0),
            "scene": _num(inp.get("scene"), 0.0, 0.9, SCENE_SSIM)}


def check_music(inp: Dict[str, Any]) -> Dict[str, Any]:
    """caption (<= 512 chars), seconds 10-600, seed, bpm 40-200 (0 = the model's choice), keyscale, steps 4-20,
    lm (the 5 Hz planner, default on), lufs -40..-10 (default the library's -27), fades."""
    if not isinstance(inp, dict):
        raise InputError("input must be an object")
    caption = " ".join(str(inp.get("caption") or "").split())[:512] or MUSIC_DEFAULT_CAPTION
    seconds = _num(inp.get("seconds"), 0.0, 36000.0, 0.0)
    if seconds <= 0:
        raise InputError("seconds (the music's length) is required")
    bpm = int(round(_num(inp.get("bpm"), 0, 200, 0)))
    keyscale = " ".join(str(inp.get("keyscale") or "").split())[:24]
    return {"caption": caption, "seconds": min(MUSIC_MAX_SECONDS, max(MUSIC_MIN_SECONDS, seconds)),
            "asked_seconds": seconds, "seed": _seed(inp.get("seed")),
            "bpm": bpm if bpm >= 40 else 0, "keyscale": keyscale,
            "steps": int(round(_num(inp.get("steps"), 4, 20, 8))),
            "lm": inp.get("lm") is not False and str(inp.get("lm")).lower() not in ("0", "false", "no"),
            "lufs": _num(inp.get("lufs"), -40.0, -10.0, MUSIC_DEFAULT_LUFS),
            # short: the renderer ramps the bed in (1.5 s) and fades it out with the video, and a bed shorter than
            # the video is repeated with a 3 s crossfade - a long fade of its own would dip at every repeat
            "fade_in": _num(inp.get("fade_in"), 0.0, 10.0, 0.5),
            "fade_out": _num(inp.get("fade_out"), 0.0, 15.0, 1.0),
            # dB taken out of the narration's band (2.2 kHz, wide): an AI bed is busier and brighter than the
            # library's drone beds (gpu_tools_test/notes.md), so it makes room for the voice; 0 = as generated
            "carve_db": _num(inp.get("carve_db"), 0.0, 8.0, MUSIC_CARVE_DB)}


# ------------------------------------------------------------------ sizes
def even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def target_size(w: int, h: int, lines: int) -> Tuple[int, int]:
    """The upscaled size: the short side becomes `lines` (a landscape clip's height, a vertical clip's width),
    the aspect kept, both sides even; a clip within half a percent of 16:9 (854x480, 640x360) lands exactly on
    16:9 (1920x1080, not 1922x1080)."""
    if w <= 0 or h <= 0:
        raise InputError("the clip has no picture size")
    s = float(lines) / float(min(w, h))
    long_side = even(max(w, h) * s)
    wide = even(lines * 16.0 / 9.0)
    if abs(long_side - wide) <= max(2, round(wide * 0.005)):
        long_side = wide
    if w >= h:
        return long_side, int(lines)
    return int(lines), long_side


def padded(n: int, multiple: int = VSR_MULTIPLE) -> int:
    """`n` rounded up to a multiple (FlashVSR pads the picture up to it, the result is cropped back)."""
    return int(math.ceil(n / float(multiple))) * multiple


def vsr_frames(n: int) -> int:
    """The frame count FlashVSR is fed for an n-frame clip: 8k+1 frames, at least n + VSR_TAIL (its output is 4
    shorter than its input), the last frame repeated - so every frame of the clip comes back."""
    if n <= 0:
        raise InputError("the clip has no frames")
    need = n + VSR_TAIL
    k = int(math.ceil((need - 1) / 8.0))
    return max(25, 8 * k + 1)


# ------------------------------------------------------------------ retiming
def retime(n_in: int, fps_in: float, fps_out: float) -> List[Tuple[int, float]]:
    """
    For each output frame of a clip retimed from fps_in to fps_out: (i, t) = the source pair (i, i+1) and how far
    between them it sits (t = 0: frame i itself). The output covers the clip's own length (n_in / fps_in s). A
    position within 1% of a source frame takes that frame (no interpolation): 30 -> 60 interpolates every second
    frame, 24 -> 60 four of every five, 25 -> 60 eleven of every twelve.
    """
    if n_in <= 0 or fps_in <= 0 or fps_out <= 0:
        raise InputError("retime needs frames and frame rates")
    seconds = n_in / float(fps_in)
    n_out = max(1, int(math.floor(seconds * fps_out + 1e-6)))
    out = []
    for k in range(n_out):
        pos = k * float(fps_in) / float(fps_out)
        i = int(math.floor(pos + 1e-9))
        t = pos - i
        if t < 0.01:
            t = 0.0
        elif t > 0.99:
            i, t = i + 1, 0.0
        if i >= n_in - 1:
            i, t = n_in - 1, 0.0
        out.append((i, round(t, 4)))
    return out


def interpolated_share(schedule: List[Tuple[int, float]]) -> float:
    return sum(1 for _, t in schedule if t > 0) / float(max(1, len(schedule)))


# ------------------------------------------------------------------ outputs
def out_key(job_id: str, ext: str) -> str:
    """Where a result goes on R2: clips under gputools/out/ (picked up by the video worker within minutes - an R2
    lifecycle rule may delete them after a day or two), music beds under gputools/music/ (a project's timeline
    keeps playing its bed's link on every re-render: never expire these)."""
    safe = "".join(c for c in str(job_id) if c.isalnum() or c in "-_")[:80] or "job"
    ext = "".join(c for c in str(ext) if c.isalnum())[:5] or "bin"
    folder = "music" if ext in ("mp3", "m4a", "wav", "flac") else "out"
    return f"gputools/{folder}/{safe}.{ext}"


def gpu_dollars(seconds: float, usd_per_hour: float) -> float:
    return round(max(0.0, float(seconds)) * float(usd_per_hour) / 3600.0, 5)


def summary_size(w: int, h: int) -> str:
    return f"{int(w)}x{int(h)}"


def pick(d: Optional[Dict[str, Any]], *keys: str) -> Dict[str, Any]:
    return {k: d[k] for k in keys if d and k in d}
