"""
One grade for the whole video.

Clips from YouTube, news channels and Wikimedia photos come from a hundred
cameras and decades: cut together raw they read as a scrapbook. The renderer
(remotion/src/components/gradeMath.ts, applied in SceneClip) draws every
scene's picture - video or photo, never the overlays or text - through one
SVG colour filter built from two parts:

  1. normalize: each scene is pulled part of the way toward the video's own
     common look - its exposure (a gamma that keeps black and white where
     they are), hazy blacks and dim highlights, saturation and colour cast,
     each measured here per scene ("tone") and compared with the median of
     all the scenes, so a red-rock canyon video stays red and only the clip
     that stands out is brought into line;
  2. look: one gentle preset over every scene - a soft S-curve that never
     crushes the blacks (the toe is lifted, the shoulder rolled), a hint of
     warmth or coolness in the midtones only (no orange-and-teal) and a
     saturation trim.

This module owns the document side: the settings (doc.grade = {"preset",
"strength", "normalize"}; PRESETS must match GRADE_PRESETS in gradeMath.ts,
a test keeps them equal) and each scene's measured tone (scene.media.tone =
{"l": mean luma, "lo"/"hi": its 2nd/98th percentiles, "s": mean chroma,
"rg"/"bg": the red and blue against green in the midtones, "v": version}),
read from up to three small frames with ffmpeg. Everything the renderer
needs is in the document, so every machine of a split render draws the same
grade. A document without "grade" renders exactly as before.
"""
from __future__ import annotations

import math
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional

from . import config

PRESETS = ("none", "neutral", "documentary", "warm-doc", "cool-news", "archival")
TONE_VERSION = 1
SAMPLE_W, SAMPLE_H = 64, 36
_FRAME_BYTES = SAMPLE_W * SAMPLE_H * 3


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def default_settings() -> Dict[str, Any]:
    preset = str(config.GRADE_PRESET or "documentary").strip().lower()
    return {"preset": preset if preset in PRESETS else "documentary",
            "strength": max(0.0, min(1.0, float(config.GRADE_STRENGTH))),
            "normalize": bool(config.GRADE_NORMALIZE)}


def clean_settings(value: Any) -> Optional[Dict[str, Any]]:
    """A document's grade as the renderer reads it, or None when it is not a grade."""
    if not isinstance(value, dict):
        return None
    preset = str(value.get("preset") or "documentary").strip().lower()
    if preset not in PRESETS:
        preset = "documentary"
    try:
        strength = float(value.get("strength", 1.0))
    except (TypeError, ValueError):
        strength = 1.0
    if not math.isfinite(strength):
        strength = 1.0
    return {"preset": preset, "strength": round(max(0.0, min(1.0, strength)), 3),
            "normalize": value.get("normalize") is not False}


def ensure(doc: Dict[str, Any]) -> bool:
    """
    The video's grade in the document: the configured default (config.GRADE)
    when it has none, an editor's own kept (cleaned). True when one was added.
    A document whose grade is null or {"preset": "none"} keeps its picture as sourced.
    """
    if "grade" in doc:
        if doc["grade"] is not None:
            cleaned = clean_settings(doc["grade"])
            if cleaned is not None:
                doc["grade"] = cleaned
        return False
    if not config.GRADE:
        return False
    doc["grade"] = default_settings()
    return True


# --------------------------------------------------------------------------- #
# Measuring a picture
# --------------------------------------------------------------------------- #

def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    f = math.floor(k)
    c = min(len(s) - 1, f + 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def tone_of(frames: List[bytes]) -> Optional[Dict[str, float]]:
    """The tone of some rgb24 frames (SAMPLE_W x SAMPLE_H): see the module notes. None when empty."""
    rs: List[float] = []
    gs: List[float] = []
    bs: List[float] = []
    for raw in frames:
        n = len(raw) - len(raw) % 3
        rs.extend(raw[0:n:3])
        gs.extend(raw[1:n:3])
        bs.extend(raw[2:n:3])
    if len(rs) < 64:
        return None
    k = 1.0 / 255.0
    ys, chroma = [], []
    mid_r = mid_g = mid_b = 0.0
    mid_n = 0
    for r, g, b in zip(rs, gs, bs):
        r, g, b = r * k, g * k, b * k
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        ys.append(y)
        chroma.append(max(r, g, b) - min(r, g, b))
        if 0.12 < y < 0.88:
            mid_r += r
            mid_g += g
            mid_b += b
            mid_n += 1
    if mid_n < len(ys) * 0.1:
        mid_r, mid_g, mid_b, mid_n = sum(rs) * k, sum(gs) * k, sum(bs) * k, len(rs)
    g_mean = max(mid_g / mid_n, 1e-3)
    return {"l": round(sum(ys) / len(ys), 3), "lo": round(_percentile(ys, 2), 3), "hi": round(_percentile(ys, 98), 3),
            "s": round(sum(chroma) / len(chroma), 3), "rg": round((mid_r / mid_n) / g_mean, 3),
            "bg": round((mid_b / mid_n) / g_mean, 3), "v": TONE_VERSION}


def _frame(source: str, at: Optional[float], timeout: float) -> Optional[bytes]:
    """One SAMPLE_W x SAMPLE_H rgb24 frame of a picture or a clip (at `at` seconds), or None."""
    argv = ["ffmpeg", "-v", "error", "-nostdin"]
    if source.startswith(("http://", "https://")):
        argv += ["-rw_timeout", str(int(timeout * 1_000_000))]
    if at is not None:
        argv += ["-ss", f"{max(0.0, at):.3f}"]
    argv += ["-i", source, "-frames:v", "1", "-vf", f"scale={SAMPLE_W}:{SAMPLE_H}:flags=area,format=rgb24",
             "-f", "rawvideo", "-"]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 and len(p.stdout) >= _FRAME_BYTES else None


def _duration(path: str, timeout: float = 20) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=timeout)
        return float((p.stdout or "0").strip() or 0.0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _local(url: str) -> str:
    u = url[len("file://"):] if url.startswith("file://") else url
    return u if u and "://" not in u and os.path.isfile(u) else ""


def measure(media: Dict[str, Any], timeout: float = 20.0) -> Optional[Dict[str, float]]:
    """
    The tone of a scene's picture: a still read whole; a clip on this disk at
    20%, 50% and 80% of its length; a clip on the web by its thumbnail (one
    small still of it) or else its middle frame. None when nothing could be read.
    """
    kind = media.get("type")
    url = str(media.get("url") or "")
    if kind not in ("video", "image") or not url:
        return None
    local = _local(url)
    frames: List[bytes] = []
    if kind == "image":
        got = _frame(local or url, None, timeout)
        frames = [got] if got else []
    elif local:
        seconds = float(media.get("clipSeconds") or 0.0) or _duration(local)
        for frac in ((0.2, 0.5, 0.8) if seconds > 0.3 else (None,)):
            got = _frame(local, None if frac is None else seconds * frac, timeout)
            if got:
                frames.append(got)
    else:
        thumb = str(media.get("thumbnail") or "")
        got = _frame(_local(thumb) or thumb, None, timeout) if thumb else None
        if not got:
            seconds = float(media.get("clipSeconds") or 0.0)
            got = _frame(url, seconds / 2.0 if seconds > 0 else 0.5, timeout)
        frames = [got] if got else []
    return tone_of(frames) if frames else None


def measure_scenes(doc: Dict[str, Any], budget: Optional[float] = None, workers: Optional[int] = None,
                   remote: bool = True) -> Dict[str, Any]:
    """
    Measure the tone of every scene picture that has none (or an older
    version's), in parallel, within `budget` seconds (config.GRADE_MEASURE_SECONDS);
    `remote` False measures only files on this disk. A scene left unmeasured
    gets the shared look without its own correction. Never raises.
    """
    started = time.time()
    budget = float(config.GRADE_MEASURE_SECONDS if budget is None else budget)
    todo = []
    for sc in doc.get("scenes") or []:
        m = sc.get("media") if isinstance(sc, dict) else None
        if not isinstance(m, dict) or m.get("type") not in ("video", "image") or not m.get("url"):
            continue
        tone = m.get("tone")
        if isinstance(tone, dict) and tone.get("v") == TONE_VERSION:
            continue
        if not remote and not _local(str(m["url"])):
            continue
        todo.append(m)
    out = {"measured": 0, "missing": 0, "seconds": 0.0}
    if not todo or budget <= 0:
        out["missing"] = len(todo)
        return out
    pool = ThreadPoolExecutor(max_workers=max(1, min(int(workers or config.GRADE_MEASURE_WORKERS), len(todo))))
    futures = {pool.submit(measure, m, min(20.0, max(2.0, budget))): m for m in todo}
    done, late = wait(futures, timeout=max(1.0, budget - (time.time() - started)))
    pool.shutdown(wait=False, cancel_futures=True)
    for f in done:
        try:
            tone = f.result()
        except Exception:  # noqa: BLE001 - that scene keeps the shared look only
            tone = None
        if tone:
            futures[f]["tone"] = tone
            out["measured"] += 1
        else:
            out["missing"] += 1
    out["missing"] += len(late)
    out["seconds"] = round(time.time() - started, 1)
    return out


def prepare(doc: Dict[str, Any], *, remote: bool = True, budget: Optional[float] = None) -> Dict[str, Any]:
    """
    The grade before a plan is saved or a render is drawn: the default
    settings when the document has none (config.GRADE), then the tone of every
    scene that lacks it. Returns what was done; never raises.
    """
    report: Dict[str, Any] = {"added": False}
    try:
        report["added"] = ensure(doc)
        grade = doc.get("grade")
        if not isinstance(grade, dict) or grade.get("preset") == "none" or grade.get("normalize") is False:
            return report
        report.update(measure_scenes(doc, budget=budget, remote=remote))
        if report.get("measured") or report.get("missing"):
            print(f"[grade] {grade.get('preset')} at {grade.get('strength')}: measured {report.get('measured', 0)} "
                  f"scene(s), {report.get('missing', 0)} without a tone ({report.get('seconds', 0)} s)", flush=True)
    except Exception as e:  # noqa: BLE001 - a grade never costs the video
        report["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return report
