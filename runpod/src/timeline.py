"""
The timeline document: the contract between worker, renderer and UI.

One JSON shape does three jobs. The worker writes it, Remotion renders it, and
the ThumbGenius editor reads and mutates it — so a user edit is just a changed
document sent back to `render`. That is what makes the plan/edit/render loop
possible without a second data model.

`validate()` is the gate in front of the renderer. It runs on documents the
worker built AND on documents that came back from the browser after editing,
so it assumes nothing about where a field came from. A render is minutes of
GPU time; failing here with a sentence the UI can show beats failing inside
headless Chrome with a stack trace.
"""
import math
import os
import subprocess
from typing import Any, Dict, List, Optional

from . import config
from .director import TEMPLATES
from .transcribe import Segment
from .media import MediaAsset

SCHEMA_VERSION = 2

# Stills need Ken Burns or they read as a stalled video. Cycled rather than
# random so a re-plan of the same script produces the same document.
_IMAGE_MOTIONS = ["zoom-in", "pan-left", "zoom-out", "pan-right"]

# Scene entrances and per-clip effects. Both lists are a contract with
# remotion/src/types.ts (SceneTransition / SceneEffect) and SceneEffects.tsx;
# a test asserts they agree.
TRANSITIONS = {"none", "fade", "film-burn", "zoom", "glitch", "slide",
               "whip", "flash", "light-leak", "dip", "blur", "punch"}
EFFECTS = {"none", "ken-burns", "light-leaks", "dust", "film-flicker", "color-shift"}

# Rotation for the strong transitions at section changes. Film burn leads
# because it is VidRush's most-used transition (24 of 61 on one timeline).
# Every entrance VidRush uses, in an order where neighbours never look alike
# (a warm burst is never followed by another warm burst, a motion move by a
# motion move).
_TRANSITION_CYCLE = ["film-burn", "whip", "flash", "zoom", "light-leak", "slide",
                     "dip", "punch", "glitch", "blur", "fade"]

# One effect per clip, weighted roughly like VidRush's own distribution
# (colour 37, Ken Burns 34, light leaks 29, flicker 21, dust 15 per 160 clips).
_EFFECT_CYCLE = ["color-shift", "ken-burns", "light-leaks", "color-shift",
                 "film-flicker", "ken-burns", "dust", "light-leaks"]

# Fewest cuts between two transitions. Transitions are punctuation; on every
# cut they read as an amateur edit.
_MIN_TRANSITION_GAP = 3


def plan_transitions(shots: List[dict]) -> List[str]:
    """
    Entrance per scene: hard cuts by default, a real transition where the
    story changes section.

    A section change is a chapter/title graphic, or the named subject moving on
    ("Lake Mead" -> "Hoover Dam"). VidRush runs about one transition per four
    cuts; the gap rule keeps it near that and never back to back.
    """
    out, last, used = [], -99, 0
    prev_subject = None
    for i, shot in enumerate(shots):
        subject = (shot.get("subject") or "").strip().lower()
        overlay = shot.get("overlay") or {}
        choice = "none"
        if i > 0 and i - last >= _MIN_TRANSITION_GAP:
            chapter = overlay.get("type") in ("chapter", "title")
            moved_on = bool(subject and prev_subject and subject != prev_subject)
            if chapter:
                choice = "film-burn"
            elif moved_on:
                choice = _TRANSITION_CYCLE[used % len(_TRANSITION_CYCLE)]
        if choice != "none":
            last, used = i, used + 1
        out.append(choice)
        if subject:
            prev_subject = subject
    return out

# How long each graphic wants to be on screen, in seconds, independent of the
# beat that triggered it. Measured from the reference renders: supporting shots
# run 2-4s but an explanatory graphic holds far longer (bar chart 10.5s, city
# map 9.0s, callout 3.5s). A chart cut after 2.6s is a chart nobody can read.
_OVERLAY_SECONDS = {
    # Tuned against the ~7s-beat GoMotion pacing; VidRush's own 3.3-3.7s
    # median (now this worker's pacing too) made the longest of these span
    # 2-3 beats of unrelated narration underneath a graphic that had already
    # finished saying its piece. Trimmed toward roughly a beat and a half,
    # kept longer only where there is genuinely more to read (a chart, a
    # document, several dated events).
    "title": 3.0, "chapter": 2.5, "callout": 3.0, "typewriter": 3.0,
    "stat": 3.5, "bar-chart": 6.0, "map": 5.5, "quote": 4.0,
    "timeline": 6.0, "highlight": 3.0, "lower-third": 3.5,
    "comparison": 5.0, "arrow": 2.5, "split": 4.0,
    "sentence-highlight": 4.0, "article-zoom": 5.0, "date-stamp": 3.0,
    "photo-card": 4.0, "name-card": 3.5,
    # Footage tags ride on a playing shot; VidRush holds them 4-5.5 s.
    "stat-tag": 4.0, "label-boxes": 4.0, "ring-stat": 4.5, "bullets": 5.5,
    "swoosh-title": 3.0, "kicker": 3.0, "memo-box": 3.5, "word-type": 2.5,
    "underline-title": 3.5, "bar-title": 3.5, "age-tag": 3.0, "clock-badge": 3.5,
    "red-strip": 3.0,
    "line-chart": 5.5, "path-steps": 5.5, "progress-steps": 4.5, "span": 4.5,
    "icon-pop": 3.0,
}

# Sources this workflow refuses. Kept as data so the check and the error
# message can't drift apart.
_STOCK_SOURCES = {"pexels", "pixabay", "stock", "shutterstock", "storyblocks"}


def _media_dims(asset) -> tuple:
    """(width, height) of an asset: from the source when it reported them,
    else probed from the downloaded file. (0, 0) when neither is possible."""
    w, h = int(getattr(asset, "width", 0) or 0), int(getattr(asset, "height", 0) or 0)
    if w and h:
        return w, h
    path = getattr(asset, "local_path", "") or ""
    if not path or not os.path.isfile(path):
        return 0, 0
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=20)
        a, b = (p.stdout.strip().splitlines() or [""])[0].split(",")[:2]
        return int(a), int(b)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0, 0


def pick_frame(asset, treatment: str, subject_type: str) -> str:
    """
    "inset" or "full" for one scene. Always "full" - VidRush's own inset-on-a-
    backdrop archival look (see SceneClip.tsx, still there) turned out to read
    as a bug, not a style, once watched in a real render: told directly to
    stop, on sight, no exceptions. `asset`/`treatment`/`subject_type` are
    still accepted so nothing upstream needs to change if this is revisited.
    """
    return "full"


def _scene_bounds(segments: List[Segment], fps: int, total: int) -> List[int]:
    """
    Frame boundaries for the visual track: [0, b1, b2, ..., total].

    The visual track must tile the narration exactly — no gaps, no overlaps,
    covering frame 0 to the last frame. Rounding each segment start
    independently does not guarantee that: a segment can round onto its
    neighbour, the first can start late, and the last can stop short of the
    audio. So boundaries are walked forward, each forced at least one frame
    past the previous and far enough from the end to leave every remaining
    scene a frame of its own.
    """
    n = len(segments)
    if total < n:
        raise ValueError(
            f"{n} scenes will not fit in {total} frames of narration; "
            "raise TARGET_SCENE_SECONDS or check the audio duration")
    bounds = [0]
    for i in range(1, n):
        want = int(round(segments[i].start * fps))
        bounds.append(max(bounds[-1] + 1, min(want, total - (n - i))))
    bounds.append(total)
    return bounds


def build(segments: List[Segment], shots: List[dict],
          assets: List[Optional[MediaAsset]], *,
          audio_url: str, audio_duration: float, inp: Dict[str, Any],
          planner: str = "rules", warnings: List[str] = None) -> Dict[str, Any]:
    """Assemble the render document from beats, shot plan and sourced media."""
    warnings = list(warnings or [])
    fps = int(inp.get("fps") or config.DEFAULT_FPS)
    width = int(inp.get("width") or config.DEFAULT_WIDTH)
    height = int(inp.get("height") or config.DEFAULT_HEIGHT)
    brand = inp.get("brand") or {}
    total = max(1, int(round(audio_duration * fps)))
    bounds = _scene_bounds(segments, fps, total)

    scenes: List[Dict[str, Any]] = []
    overlays: List[Dict[str, Any]] = []
    # Off unless asked for: captions are a choice made in the editor, and a
    # burned-in default is the first thing a creator has to undo. Word
    # timings are stored either way, so switching them on later gets real
    # word-synced phrases instead of a scene's whole text at once.
    keep_captions = bool(inp.get("captions", False))

    entrances = plan_transitions(list(shots) + [{}] * max(0, len(segments) - len(shots)))

    for i, seg in enumerate(segments):
        shot = shots[i] if i < len(shots) else {}
        asset = assets[i] if i < len(assets) else None
        start, duration = bounds[i], bounds[i + 1] - bounds[i]

        if asset is None:
            media = {"type": "color", "url": "", "source": "none"}
            motion = "none"
            review, reason = True, "No media found for this beat"
        else:
            media = asset.to_scene_media()
            motion = _IMAGE_MOTIONS[i % len(_IMAGE_MOTIONS)] if asset.kind == "image" else "none"
            review, reason = asset.review_required, asset.review_reason

        scenes.append({
            "id": f"s{i:04d}",
            "startFrame": start,
            "durationInFrames": duration,
            "text": seg.text,
            "query": shot.get("query", ""),
            "visualType": shot.get("visualType", "footage"),
            "media": media,
            "motion": motion,
            "treatment": shot.get("treatment", "film"),
            "transition": entrances[i] if i < len(entrances) else "none",
            "frame": pick_frame(asset, shot.get("treatment", "film"),
                                shot.get("subjectType", "")),
            "effect": ("none" if asset is None
                       else _EFFECT_CYCLE[i % len(_EFFECT_CYCLE)]),
            "semanticMetadata": {
                "intent": shot.get("intent", ""),
                "subject": shot.get("subject", ""),
                "subjectType": shot.get("subjectType", ""),
                "searchQuery": shot.get("query", ""),
                "eventWindow": shot.get("eventWindow", ""),
                "contentDescription": getattr(asset, "content_description", "") or "",
                "relevanceScore": getattr(asset, "relevance_score", None),
                "qualityScore": getattr(asset, "quality", None),
                "provider": getattr(asset, "source", "") or "",
            },
            "words": [{"text": w.text, "start": w.start, "end": w.end}
                      for w in seg.words],
            "reviewRequired": bool(review),
            "reviewReason": reason or "",
        })

        overlay = shot.get("overlay")
        if overlay and overlay["type"] in {"photo-card", "name-card"}:
            # Bind only this beat's sourced, reviewed image. Never substitute a
            # previous scene's person or generate a portrait to fill a card.
            if asset is not None and asset.kind == "image" and not review:
                overlay = {**overlay, "media": [media]}
            else:
                overlay = None
        if overlay:
            # A graphic runs for as long as it needs to be read, not for as
            # long as the beat that introduced it — so it can span later cuts.
            want = int(round(_OVERLAY_SECONDS.get(overlay["type"], 3.5) * fps))
            overlays.append({**overlay,
                             "startFrame": start,
                             "durationInFrames": min(max(duration, want), total - start)})

    if inp.get("title_overlay"):
        overlays.insert(0, {
            "type": "title", "text": str(inp["title_overlay"])[:240],
            "startFrame": int(round(1.0 * fps)),
            "durationInFrames": min(int(round(3.5 * fps)), max(1, total - int(round(1.0 * fps)))),
        })

    missing = sum(1 for a in assets if a is None)
    if missing:
        warnings.append(f"{missing} scene(s) have no media and will render black.")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "fps": fps,
        "width": width,
        "height": height,
        "durationInFrames": total,
        "audio": {"url": audio_url, "volume": float(inp.get("audio_volume", 1.0))},
        "bgm": ({"url": inp["bgm_url"], "volume": float(inp.get("bgm_volume", 0.12))}
                if inp.get("bgm_url") else None),
        "captions": {
            "enabled": keep_captions,
            "position": brand.get("captionPosition", "bottom"),
            "accent": brand.get("accent", "#FFD400"),
            "fontFamily": brand.get("fontFamily", "Inter"),
        },
        "scenes": scenes,
        "overlays": overlays,
        "meta": {
            "schemaVersion": SCHEMA_VERSION,
            "sceneCount": len(scenes),
            "overlayCount": len(overlays),
            "planner": planner,
            "sourcePolicy": "stock_allowed" if config.ALLOW_STOCK else "no_stock",
            "cutsPerMinute": round(len(scenes) / max(audio_duration / 60, 0.01), 1),
            "sources": sorted({a.source for a in assets if a}),
            "scenesWithoutMedia": missing,
            "scenesNeedingReview": sum(1 for s in scenes if s["reviewRequired"]),
            "generatedScenes": sum(1 for a in assets if a and a.source == "generated"),
            "warnings": warnings,
        },
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _integer(value, name: str, lo: int, hi: int) -> int:
    # bool is an int subclass in Python; True would sail through as 1.
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{name} must be a whole number from {lo} to {hi}")
    return value


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _validate_overlay(ov: Any, index: int, total: int) -> None:
    where = f"Overlay {index + 1}"
    if not isinstance(ov, dict):
        raise ValueError(f"{where} is not an object")
    if ov.get("type") not in TEMPLATES:
        raise ValueError(f"{where}: unknown animation template {ov.get('type')!r}")
    start = _integer(ov.get("startFrame"), f"{where} start", 0, total - 1)
    length = _integer(ov.get("durationInFrames"), f"{where} duration", 1, total)
    if start + length > total:
        raise ValueError(f"{where} runs past the end of the narration")

    kind = ov["type"]
    if kind == "map":
        places = ov.get("locations")
        if not isinstance(places, list) or not places:
            raise ValueError(f"{where}: a map needs at least one verified location")
        for p in places:
            if not isinstance(p, dict) or not str(p.get("label", "")).strip():
                raise ValueError(f"{where}: every map location needs a label")
            for key, limit in (("lat", 90), ("lon", 180)):
                if abs(_number(p.get(key), f"{where} {key}")) > limit:
                    raise ValueError(f"{where}: {key} is out of range")
    elif kind in {"split", "photo-card", "name-card"}:
        media = ov.get("media")
        minimum = 2 if kind == "split" else 1
        if not isinstance(media, list) or len(media) < minimum:
            raise ValueError(f"{where}: a split screen needs two media assets"
                             if kind == "split" else
                             f"{where}: {kind} needs a real image asset")
        if kind != "split" and any(not isinstance(m, dict) or m.get("type") != "image" or not m.get("url") for m in media):
            raise ValueError(f"{where}: image cards need real image assets")
    elif kind == "stat":
        _number(ov.get("value"), f"{where} value")
    elif kind in {"bar-chart", "comparison"}:
        items = ov.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError(f"{where}: a chart needs at least two items")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{where}: malformed chart item")
            _number(item.get("value"), f"{where} item value")
    elif kind == "timeline":
        items = ov.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError(f"{where}: a timeline needs at least two entries")


def validate(doc: Any, require_media: bool = True,
             allow_stock: bool = None) -> Dict[str, Any]:
    """
    Check a timeline document before spending a render on it.

    Raises ValueError with a message meant to be shown to the user. Set
    require_media=False to validate a plan that the editor is still filling in.
    """
    allow_stock = config.ALLOW_STOCK if allow_stock is None else allow_stock
    if not isinstance(doc, dict):
        raise ValueError("Timeline must be an object")

    fps = _integer(doc.get("fps"), "fps", 12, 120)
    width = _integer(doc.get("width"), "width", 320, 3840)
    height = _integer(doc.get("height"), "height", 180, 2160)
    if width % 2 or height % 2:
        # h.264 chroma subsampling needs even dimensions; ffmpeg refuses odd ones.
        raise ValueError("Video width and height must both be even numbers")
    total = _integer(doc.get("durationInFrames"), "durationInFrames", 1, fps * 7200)

    audio = doc.get("audio")
    if not isinstance(audio, dict) or not str(audio.get("url", "")).strip():
        raise ValueError("Timeline has no narration audio — the render would be silent")

    scenes = doc.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 4000:
        raise ValueError("Timeline needs between 1 and 4000 scenes")

    cursor = 0
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i + 1} is not an object")
        start = _integer(scene.get("startFrame"), f"Scene {i + 1} start", 0, total - 1)
        length = _integer(scene.get("durationInFrames"), f"Scene {i + 1} duration", 1, total)
        if start != cursor:
            raise ValueError(
                f"Scene {i + 1} starts at frame {start} but the previous scene ends at "
                f"{cursor} — the visual track must stay flush with the narration")
        cursor += length

        media = scene.get("media")
        if not isinstance(media, dict):
            raise ValueError(f"Scene {i + 1} has no media object")
        source = str(media.get("source", "")).lower()
        if not allow_stock and source in _STOCK_SOURCES:
            raise ValueError(
                f"Scene {i + 1} uses {source} footage; this workflow is no-stock "
                "(set ALLOW_STOCK=1 to override)")
        if require_media and (media.get("type") == "color" or not media.get("url")):
            raise ValueError(f"Scene {i + 1} still needs media before it can render")

    if cursor != total:
        raise ValueError(
            f"Scenes cover {cursor} frames but the narration is {total} — "
            "the visual track must cover it exactly")

    overlays = doc.get("overlays")
    if overlays is not None:
        if not isinstance(overlays, list):
            raise ValueError("overlays must be a list")
        for i, ov in enumerate(overlays):
            _validate_overlay(ov, i, total)

    return doc
