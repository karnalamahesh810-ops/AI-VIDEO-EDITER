"""
Where a clip plays from and how fast: the editor's slip, split, roll and speed (the pro editor, 2026-10-09).

The same rules as the renderer's remotion/src/edit/clipTime.ts (tests/test_pro_editor.py runs both on the
same cases): the quality check before a render (src/quality.py) must judge a clip by what the renderer will
draw - a scene the editor slipped or split starts part-way into its file, so the file's length alone no longer
says whether it covers the scene.

Fields (all optional; a document the editor never touched plays exactly as before):
  media.trimStart  seconds into the clip file the scene starts at
  speed            a constant speed, 0.1-8
  speedRamp        [{t, v}]: the speed v at t seconds from the clip's start, straight lines between
  splitFrom        the id of the scene this one was split from (it continues that shot: not a repeat)

An edited clip that runs out of picture is slowed just enough to reach its scene's end (never frozen); an
unedited one is slowed to fill, never under MIN_FILL_RATE (0.6), as SceneClip always did.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

MIN_FILL_RATE = 0.6
MIN_SPEED = 0.1
MAX_SPEED = 8.0
MIN_PLAY_RATE = 0.0625


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _round(x: float) -> int:
    """JavaScript's Math.round (halves go up), so both sides pick the same frame."""
    return int(math.floor(x + 0.5))


def trim_start(media: Optional[dict]) -> float:
    t = _num((media or {}).get("trimStart"))
    return t if t is not None and t > 0 else 0.0


def speed_of(clip: Optional[dict]) -> float:
    s = _num((clip or {}).get("speed"))
    return max(MIN_SPEED, min(MAX_SPEED, s)) if s is not None and s > 0 else 1.0


def ramp_of(clip: Optional[dict]) -> Optional[List[Dict[str, float]]]:
    raw = (clip or {}).get("speedRamp")
    if not isinstance(raw, list):
        return None
    keys = []
    for k in raw:
        if not isinstance(k, dict):
            continue
        t, v = _num(k.get("t")), _num(k.get("v"))
        if t is None or v is None or v <= 0:
            continue
        keys.append({"t": max(0.0, t), "v": max(MIN_SPEED, min(MAX_SPEED, v))})
    if not keys:
        return None
    keys.sort(key=lambda k: k["t"])
    return keys


def ramp_at(keys: List[Dict[str, float]], t: float) -> float:
    if t <= keys[0]["t"]:
        return keys[0]["v"]
    last = keys[-1]
    if t >= last["t"]:
        return last["v"]
    for i in range(1, len(keys)):
        b = keys[i]
        if t <= b["t"]:
            a = keys[i - 1]
            span = b["t"] - a["t"]
            return a["v"] + (b["v"] - a["v"]) * (t - a["t"]) / span if span > 0 else b["v"]
    return last["v"]


def is_edited(timing: dict) -> bool:
    return trim_start(timing) > 0 or speed_of(timing) != 1.0 or ramp_of(timing) is not None


def fill_rate(clip_seconds: float, scene_seconds: float) -> float:
    return max(MIN_FILL_RATE, clip_seconds / scene_seconds) if 0 < clip_seconds < scene_seconds else 1.0


def timing_of(scene: dict) -> dict:
    """The fields clip_plan reads, from a scene (or a picture-in-picture layer)."""
    m = scene.get("media") if isinstance(scene.get("media"), dict) else {}
    return {"clipSeconds": m.get("clipSeconds") if m.get("type") == "video" else 0, "trimStart": m.get("trimStart"),
            "speed": scene.get("speed"), "speedRamp": scene.get("speedRamp")}


def clip_plan(timing: dict, frames: float, fps: float) -> List[Dict[str, float]]:
    """[{from, frames, rate, trimBefore}]: the stretches that cover `frames` frames (clipTime.ts clipPlan)."""
    n = max(1, _round(frames))
    f = fps if fps and fps > 0 else 30.0
    need = n / f
    clip = max(0.0, _num(timing.get("clipSeconds")) or 0.0)
    if not is_edited(timing):
        return [{"from": 0, "frames": n, "rate": fill_rate(clip, need), "trimBefore": 0}]
    trim = trim_start(timing)
    if clip > 0:
        trim = min(trim, max(0.0, clip - 1 / f))
    start = _round(trim * f)
    avail = max(0.0, clip - start / f) if clip > 0 else 0.0
    ramp = ramp_of(timing)
    if ramp is None:
        s = speed_of(timing)
        rate = max(MIN_PLAY_RATE, avail / need) if avail > 0 and need * s > avail else s
        return [{"from": 0, "frames": n, "rate": rate, "trimBefore": start}]
    v = [ramp_at(ramp, (i + 0.5) / f) for i in range(n)]
    total = sum(v)
    fit = (avail * f) / total if avail > 0 and total / f > avail else 1.0
    pos = [float(start)]
    for x in v:
        pos.append(pos[-1] + x * fit)
    step = max(1, _round(f / 6))
    out: List[Dict[str, float]] = []
    first = pos[0]
    a = 0
    while a < n:
        b = min(n, a + step)
        rate = max(MIN_PLAY_RATE, (pos[b] - pos[a]) / (b - a))
        if out and abs(out[-1]["rate"] - rate) <= out[-1]["rate"] * 0.005:
            out[-1]["frames"] += b - a
            out[-1]["rate"] = max(MIN_PLAY_RATE, (pos[b] - first) / out[-1]["frames"])
        else:
            first = pos[a]
            out.append({"from": a, "frames": b - a, "rate": rate, "trimBefore": _round(pos[a])})
        a = b
    return out


def plan_source_seconds(plan: List[Dict[str, float]], fps: float) -> float:
    """Seconds of the clip file a plan shows (its in-point to where its last stretch ends)."""
    if not plan:
        return 0.0
    last = plan[-1]
    return (last["trimBefore"] + last["rate"] * last["frames"] - plan[0]["trimBefore"]) / (fps or 30.0)


def covers(scene: dict, real_seconds: float, need_seconds: float, fps: float, tolerance: float = 0.0) -> bool:
    """
    Whether a clip `real_seconds` long covers an EDITED scene shown for `need_seconds` (its in-point and
    speed as the renderer reads them): such a clip is slowed to reach its scene's end, so it covers unless its
    in-point leaves nothing of the file, or it would have to play slower than MIN_PLAY_RATE.
    """
    timing = dict(timing_of(scene), clipSeconds=real_seconds)
    plan = clip_plan(timing, need_seconds * (fps or 30.0), fps)
    shown = plan_source_seconds(plan, fps)
    start = plan[0]["trimBefore"] / (fps or 30.0) if plan else 0.0
    return real_seconds - start >= shown - tolerance
