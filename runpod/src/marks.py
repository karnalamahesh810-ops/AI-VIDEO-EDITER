"""
Marks that point at something in the picture - only where it is worth it.

The owner (2026-09-30): "on the video, the arrow showing - only when it's
worth it", and photo looks that circle or point at the thing being talked
about. Both need to know WHERE the thing is, which only vision can tell
(src/anchors.find_anchor), so this runs once the timeline is built and the
clips and stills are still local files:

1. Photo looks that point (pe-red-arrow, pe-circle-spotlight) or look closer
   (pe-magnify, pe-case-file's marker ring) get the spot from vision. A
   pointing look whose spot is not found is swapped for pe-case-file, which
   reads well with its default spot: a red arrow at a random place is worse
   than no arrow.
2. Video marks (vm-arrow / vm-circle / vm-box) go on a footage scene whose
   line points at something visible ("you can see the water line", "look at
   this bridge", "notice the cracks") when vision finds that thing in the
   clip's frame at the moment the mark lands. At most MARKS_MAX per video,
   MARKS_GAP_SECONDS apart, never over another graphic.

Nothing here can fail a job: any error leaves the timeline as it was.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import config, sfxplan, templates
from .presenter import is_presenter_scene

POINTING_PHOTO = {"LIB_PE_RED_ARROW", "LIB_PE_CIRCLE_SPOTLIGHT"}
# (the photo focus, LibPremium: its push-in and ring centre on the anchor found; the frame's centre without one)
DETAIL_PHOTO = {"LIB_PE_MAGNIFY", "LIB_PE_CASE_FILE", "LIB_PR_PHOTO_FOCUS"}
PHOTO_FALLBACK = "LIB_PE_CASE_FILE"
VIDEO_MARKS = ("LIB_VM_ARROW", "LIB_VM_CIRCLE", "LIB_VM_BOX", "KT_POINTER")
MARK_SECONDS = 3.0          # a mark does not track motion: short, on a steady moment
BREATH = 0.3                # seconds kept clear around other graphics

# A line that points at something the viewer can see.
_POINT = re.compile(
    r"\b(?:you can (?:clearly |actually |still |even )?see|you'll see|look (?:closely )?at|take a look at|"
    r"notice|watch (?:the|as|how)|pointing (?:to|at)|see (?:the|that|this|how|where))\b\s*(?P<what>[^,.;:!?]{0,70})",
    re.I)
_THING = (r"bridge|dam|levee|house|home|homes|road|highway|interstate|car|cars|truck|boat|building|river|creek|"
          r"water ?line|high[- ]water mark|mark|wall|spillway|tower|sign|crack|cracks|hole|channel|intake|pipe|"
          r"barge|ship|plane|train|smoke|fire|flames|bathtub ring|shoreline|tree|trees|pole|poles|street|"
          r"intersection|field|reservoir|lake|canyon|cliff|marina|dock|pier|funnel|tornado|wall cloud|debris|"
          r"roof|window|door|gauge|meter|boat ramp|parking lot|culvert|overpass|underpass|rescue|helicopter")
_DEMONSTRATIVE = re.compile(r"\b(?:this|that|these|those) (?P<what>(?:[a-z-]+ ){0,2}(?:" + _THING + r"))\b", re.I)
_CUT_AT = re.compile(r"\s+(?:as|that|which|where|when|because|while|after|before|and then|is|are|was|were|has|have|"
                     r"had|will|would|could|can|to|from|in|on|at|of|with|for|by)\b.*$", re.I)
_LEAD = re.compile(r"^(?:the|a|an|this|that|these|those|how|where|what|its|their|his|her|our|just|now)\s+", re.I)
_THING_RE = re.compile(r"\b(?:" + _THING + r")\b", re.I)
_PARTICIPLE = re.compile(r"\s+[a-z]+ing\b.*$", re.I)
_PRONOUN = {"it", "them", "this", "that", "these", "those", "here", "there", "him", "her", "what", "how",
            "why", "who", "whom", "when", "whether", "if", "all", "everything", "something", "anything"}


def _what_from(text: str) -> str:
    """The thing a line points at ("you can see the water line on the dam" -> "water line"), or ''."""
    m = _DEMONSTRATIVE.search(text or "")
    what = m.group("what") if m else ""
    if not what:
        m = _POINT.search(text or "")
        what = m.group("what") if m else ""
    what = what.strip()
    thing = _THING_RE.search(what)
    if thing:
        # The concrete thing it names: "the cracks running down the spillway" -> "the cracks".
        what = what[:thing.end()]
    else:
        what = _PARTICIPLE.sub("", _CUT_AT.sub("", what))
    for _ in range(3):
        what = _LEAD.sub("", what).strip()
    words = what.split()
    if not words or words[0].lower() in _PRONOUN:
        return ""
    return " ".join(words[:4])


def _cue_seconds(scene: dict, fps: int) -> float:
    """When the pointing words are said (the scene's word timings), else 0.4 s into the scene."""
    start = int(scene.get("startFrame") or 0) / fps
    text = str(scene.get("text") or "")
    m = _DEMONSTRATIVE.search(text) or _POINT.search(text)
    words = [w for w in (scene.get("words") or []) if isinstance(w, dict)]
    if m and words:
        # The word at the match's character position: count words before it.
        n = len(text[:m.start()].split())
        if n < len(words):
            try:
                return max(start, float(words[n]["start"]))
            except (KeyError, TypeError, ValueError):
                pass
    return start + 0.4


def _local(path: str) -> bool:
    import os
    return bool(path) and not str(path).startswith(("http://", "https://")) and os.path.isfile(path)


def _busy(overlays: List[dict], a: int, b: int, fps: int, skip: Optional[dict] = None) -> bool:
    pad = int(round(BREATH * fps))
    for o in overlays:
        if o is skip:
            continue
        s = int(o.get("startFrame") or 0)
        e = s + int(o.get("durationInFrames") or 0)
        if s < b + pad and a < e + pad:
            return True
    return False


def _scene_at(scenes: List[dict], frame: int) -> Optional[dict]:
    for s in scenes:
        st = int(s.get("startFrame") or 0)
        if st <= frame < st + int(s.get("durationInFrames") or 0):
            return s
    return None


def _still_for(ov: dict, scene: Optional[dict]) -> str:
    """
    The local picture a photo look will show (as Main.tsx binds it): the
    overlay's own picture, else the scene's image, else its clip's thumbnail.
    '' when none is a local file (then no spot can be looked for).
    """
    own = [m for m in (ov.get("media") or []) if isinstance(m, dict)]
    if own and _local(own[0].get("url") or ""):
        return own[0]["url"]
    m = (scene or {}).get("media") or {}
    if m.get("type") == "image" and _local(m.get("url") or ""):
        return m["url"]
    if _local(m.get("thumbnail") or ""):
        return m["thumbnail"]
    return ""


def _sfx_cue(template_id: str, start: int, frames: int, fps: int, voice_lufs) -> Optional[dict]:
    """The look's own sound, peaking on its hit, at the voice-relative level (src/sfxplan)."""
    t = templates.get(template_id) or {}
    if sfxplan.has_builtin_sound(t):
        # The renderer plays this look's registry sound design inside the
        # overlay (LookSounds); a timeline row would only clutter the editor.
        return None
    d = t.get("defaults") or {}
    name = str((d.get("sfx") or {}).get("name") or "")
    if not name or name == "none" or not sfxplan.exists(name):
        return None
    hit = start + int(round(float(d.get("sfxAt") or sfxplan.DEFAULT_HIT) * fps / sfxplan.BASE_FPS))
    raw = hit - sfxplan.peak_frames(name, fps)
    begin = max(start, raw)
    trim = begin - raw
    audible = min(sfxplan.duration_frames(name, fps) - trim, start + frames - begin)
    if audible <= 0:
        return None
    cue = {"name": name, "startFrame": int(begin), "volume": round(sfxplan.level(name, voice_lufs), 3),
           "durationFrames": int(trim + audible), "kind": "overlay"}
    if trim:
        cue["trimFrames"] = int(trim)
    return cue


# The look pack's arrow callout (remotion LibKtPack.tsx kt-pointer, src/lookpack.py): a ring drawing round the
# thing, an arrow drawing to it from a frosted label on the calm side - the arrow's turn, the red marker arrow
# behind it (when the brand kit or the owner's switch leaves the pointer out).
POINTER = "KT_POINTER"


def _pick_mark(anchor: dict, n: int) -> str:
    """
    Circle a small round thing, box a wide one, else the arrow (the look pack's arrow callout first, then the
    marker arrow); alternate for variety. Only the marks the brand kit allows (the next best when the first is
    left out); "" when it allows none.
    """
    w, h = float(anchor.get("w") or 0), float(anchor.get("h") or 0)
    arrow = ([POINTER] if templates.auto_pick(POINTER) else []) + ["LIB_VM_ARROW"]
    if w and h and w / max(h, 1e-3) > 2.2:
        order = ["LIB_VM_BOX"] + arrow + ["LIB_VM_CIRCLE"]
    elif float(anchor.get("r") or 1) < 0.12:
        order = ["LIB_VM_CIRCLE"] + arrow if n % 2 == 0 else arrow + ["LIB_VM_CIRCLE"]
    else:
        order = arrow + ["LIB_VM_CIRCLE"] if n % 2 == 0 else ["LIB_VM_CIRCLE"] + arrow
    return next((t for t in order if not templates.banned(t)), "")


def _label(what: str) -> str:
    return " ".join(what.split()[:3]).upper()[:28]


def place_photo_anchors(doc: dict, find) -> Dict[str, int]:
    """Anchors for the photo looks that point; swaps a pointing look with no spot found."""
    fps = int(doc.get("fps") or 30)
    scenes = doc.get("scenes") or []
    stats = {"photoAnchored": 0, "photoSwapped": 0}
    for ov in doc.get("overlays") or []:
        tid = ov.get("template") or ""
        if tid not in POINTING_PHOTO and tid not in DETAIL_PHOTO or ov.get("anchor"):
            continue
        scene = _scene_at(scenes, int(ov.get("startFrame") or 0))
        sem = (scene or {}).get("semanticMetadata") or {}
        what = _what_from(str((scene or {}).get("text") or "")) or str(sem.get("subject") or ov.get("text") or "")
        still = _still_for(ov, scene)
        anchor = find(still, what, str((scene or {}).get("text") or "")) if (still and what) else None
        if anchor:
            ov["anchor"] = anchor
            stats["photoAnchored"] += 1
        elif tid in POINTING_PHOTO:
            # (A fallback outside the brand kit's looks: brandkit.enforce finds the closest allowed one.)
            new = templates.resolve(PHOTO_FALLBACK, props={"text": ov.get("text") or "",
                                                            "subtitle": ov.get("subtitle") or ""})
            if new:
                new.pop("seconds", None)
                new.pop("sfx", None)
                keep = {k: ov[k] for k in ("startFrame", "durationInFrames", "fontScale", "media") if k in ov}
                ov.clear()
                ov.update(new)
                ov.update(keep)
                stats["photoSwapped"] += 1
    return stats


def place_video_marks(doc: dict, find, frame_at) -> Dict[str, int]:
    """Arrow / circle / box marks on footage whose line points at something vision can find."""
    fps = int(doc.get("fps") or 30)
    scenes = doc.get("scenes") or []
    overlays = doc.setdefault("overlays", [])
    sfx = doc.setdefault("sfx", [])
    voice = (doc.get("meta") or {}).get("voiceLufs")
    limit = int(getattr(config, "MARKS_MAX", 5))
    gap = float(getattr(config, "MARKS_GAP_SECONDS", 60.0)) * fps
    frames = int(round(MARK_SECONDS * fps))
    placed: List[int] = []
    stats = {"videoMarks": 0, "videoLooked": 0}
    for scene in scenes:
        if len(placed) >= limit:
            break
        m = scene.get("media") or {}
        if m.get("type") != "video" or not _local(m.get("url") or "") or is_presenter_scene(scene):
            continue                        # (never an arrow on the presenter: src/presenter/hybrid.py)
        what = _what_from(str(scene.get("text") or ""))
        if not what:
            continue
        s0 = int(scene.get("startFrame") or 0)
        s1 = s0 + int(scene.get("durationInFrames") or 0)
        start = max(s0, int(round(_cue_seconds(scene, fps) * fps)) - 2)
        start = min(start, s1 - frames)
        if start < s0 or any(abs(start - p) < gap for p in placed):
            continue
        if _busy(overlays, start, start + frames, fps):
            continue
        # The frame of the clip file on screen when the mark lands (SceneClip
        # slows a clip shorter than its scene, never below 0.6x).
        scene_s = (s1 - s0) / fps
        clip_s = float(m.get("clipSeconds") or 0)
        rate = max(0.6, clip_s / scene_s) if 0 < clip_s < scene_s else 1.0
        hit = int(round(float((templates.get("LIB_VM_ARROW") or {}).get("defaults", {}).get("sfxAt") or 14)
                        * fps / sfxplan.BASE_FPS))
        t = ((start - s0) + hit) / fps * rate
        stats["videoLooked"] += 1
        frame = frame_at(m["url"], t)
        anchor = find(frame, what, str(scene.get("text") or "")) if frame else None
        if not anchor:
            continue
        tid = _pick_mark(anchor, len(placed))
        if not tid:
            break                       # the brand kit allows no mark
        ov = templates.resolve(tid, props={"text": _label(what)})
        if not ov:
            continue
        ov.pop("seconds", None)
        ov.pop("sfx", None)
        ov.update({"startFrame": int(start), "durationInFrames": frames, "anchor": anchor})
        overlays.append(ov)
        cue = _sfx_cue(tid, int(start), frames, fps, voice)
        if cue:
            sfx.append(cue)
        placed.append(int(start))
        stats["videoMarks"] += 1
    overlays.sort(key=lambda o: int(o.get("startFrame") or 0))
    sfx.sort(key=lambda s: int(s.get("startFrame") or 0))
    return stats


def place(doc: dict) -> Dict[str, int]:
    """Both passes; never raises. Returns counts for the job's meta."""
    if not getattr(config, "MARKS_ENABLED", True):
        return {}
    try:
        from . import anchors
    except Exception:  # noqa: BLE001
        return {}
    stats: Dict[str, int] = {}
    try:
        stats.update(place_photo_anchors(doc, anchors.find_anchor))
    except Exception as e:  # noqa: BLE001 - a nicety, never a failure
        print(f"[marks] photo anchors skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
    try:
        stats.update(place_video_marks(doc, anchors.find_anchor, anchors.frame_at))
    except Exception as e:  # noqa: BLE001
        print(f"[marks] video marks skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
    if stats:
        print(f"[marks] {stats}", flush=True)
    return stats
