"""
How each still picture sits in the frame and how far it may move (the owner, 2026-10-26, the Hoover Dam video):

  "images movements and zooms worst and bad ... when people names come this is how it showed image"

At 05:07 a web photo of Jack Schmidt (a portrait) filled the 16:9 frame: the cover fit kept the middle band of the
portrait - his chin, mouth and shirt - blown up and pushed in further by a zoom, for 4.4 s. Measured over the video:
of the 87 stills sourcing measured, 61 were shown past their real detail before any move (36 past 1.3x), the moves
went up to 1.38x (pull-back, reveal), and editing v3 added a 1.08x punch and 1.36x detail framings on top.

One pass over the built document while the files are still local (no network, no AI; time-boxed):

* A portrait - a named person's line, a picture taller than it is wide (or nearly square), or a face the 16:9 crop
  would cut - is never cropped to fill the frame: it becomes a framed card (motion "parallax": the whole picture,
  sharp, over a blurred copy of itself), no taller than its real detail allows (STILL_CARD_UPSCALE) and placed a
  little right of centre when a name card shares the frame (media.card {"max", "x"}).
* Every other still keeps the cover fit, aimed at its face when it has one (media.reframe.subject), and gets
  media.maxZoom: how far its move may push before its real detail is blown up past STILL_PEAK_MAGNIFICATION (a sharp
  photo keeps the full move, a soft one barely moves). The renderer scales the move to it
  (remotion/src/transitions/stillMotion.tsx) and editing v3 never punches or detail-frames past it.
* Flashy moves (reveals, turns, the 1.38x pull-back) leave the automatic rotation (timeline._IMAGE_MOTIONS); an old
  document's are drawn as a calm push or pull within maxZoom.

Nothing here can fail a job: any error leaves the scene as it was. meta.stillFrame reports what it did.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from . import config

OUT_W, OUT_H = 1920, 1080
FRAME_ASPECT = OUT_W / OUT_H
CARD_ASPECT = 1.25              # a picture narrower than this (w / h) is a portrait: a card, never a crop
CARD_MAX = 0.84                 # the card's height at most (a share of the frame height)
CARD_MIN = 0.42                 # ... and at least (a smaller picture would not read; the quality gate keeps tiny ones out)
CARD_X_BESIDE_NAME = 0.6        # the card's centre when a name lower third shares the frame (it sits low left)
FACE_PAD_TOP, FACE_PAD_BOTTOM, FACE_PAD_SIDE = 0.6, 0.8, 0.45   # head and shoulders around YuNet's brow-to-chin box
# The documentary moves of stillMotion.tsx at their largest scale (the move's peak), for the zoom budget.
MOVE_PEAK = {"zoom-in": 1.15, "zoom-out": 1.16, "pan-left": 1.15, "pan-right": 1.15, "reveal-left": 1.38,
             "reveal-right": 1.38, "push-rotate": 1.18, "push-offcenter": 1.22, "pull-back": 1.38,
             "drift-diagonal": 1.16, "rotate-settle": 1.22, "parallax": 1.0, "none": 1.06}


def enabled() -> bool:
    return bool(getattr(config, "STILL_FRAME", True))


def _local(url: str) -> bool:
    return bool(url) and not str(url).startswith(("http://", "https://")) and os.path.isfile(url)


def facts(path: str) -> Optional[dict]:
    """{"w", "h", "lines", "faces"} of a picture file: its size, its real detail (lines of its short side,
    reframe.effective_lines) and its faces ([x, y, w, h, score, eye] shares of the picture). None if unreadable."""
    try:
        import numpy as np
        from PIL import Image
        from . import reframe
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            aw = 640 if w >= h else max(64, int(round(640 * w / float(h))))
            ah = max(64, int(round(aw * h / float(w))))
            rgb = np.asarray(im.resize((aw, ah), Image.BILINEAR))
            gray = np.asarray(im.convert("L"))
        # The calibrated round-trip measure first (src/sharpness.py: a search thumbnail, a page's upscaled copy and
        # a Real-ESRGAN pass all make big files of small pictures); the spectrum estimate only without it.
        lines = 0
        try:
            from . import sharpness
            ew, eh = sharpness.real_detail(path)
            if ew and eh:
                lines = int(round(min(ew, eh)))
        except Exception:  # noqa: BLE001 - the spectrum estimate below
            lines = 0
        lines = lines or int(reframe.effective_lines(gray) or 0) or min(w, h)
        faces = reframe.find_faces(rgb) if reframe.faces_available() else []
        return {"w": int(w), "h": int(h), "lines": min(lines, min(w, h)),
                "faces": [list(map(float, f[:6])) for f in faces if f[3] >= 0.035]}
    except Exception as e:  # noqa: BLE001 - an unreadable picture keeps its framing
        print(f"[stillframe] {os.path.basename(str(path))}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return None


def with_known_detail(f: dict, magnification: Optional[float]) -> dict:
    """`f` with its real detail from the magnification sourcing measured on the ORIGINAL download
    (semanticMetadata.scoreParts.magnification, at the planner's typical move) when that says less detail than
    the file does - the file may be an upscaled copy (UPSCALE_ENABLED) that looks sharp to any measure."""
    try:
        mag = float(magnification or 0)
    except (TypeError, ValueError):
        return f
    if mag <= 0:
        return f
    try:
        from . import sharpness
        zoom = float(sharpness.planned_zoom() or 1.16)
    except Exception:  # noqa: BLE001
        zoom = 1.16
    m0 = mag / max(1.0, zoom)
    w, h = float(f["w"]), float(f["h"])
    aspect = w / max(1.0, h)
    eh = OUT_H / m0 if aspect >= FRAME_ASPECT else (OUT_W / m0) / aspect
    lines = int(round(min(eh * aspect, eh)))
    return dict(f, lines=min(int(f.get("lines") or lines), lines)) if lines > 0 else f


def detail_size(f: dict) -> Tuple[float, float]:
    """The picture's real detail in pixels (w, h): its short side's real lines, the long side in proportion."""
    w, h, lines = float(f["w"]), float(f["h"]), float(f.get("lines") or min(f["w"], f["h"]))
    k = lines / max(1.0, min(w, h))
    return w * k, h * k


def cover_magnification(f: dict) -> float:
    """How many times a cover fit into 1920 x 1080 blows the picture's real detail up, at rest."""
    ew, eh = detail_size(f)
    return max(OUT_W / max(1.0, ew), OUT_H / max(1.0, eh))


def _head(face: list) -> list:
    x, y, w, h = face[:4]
    return [x - FACE_PAD_SIDE * w, y - FACE_PAD_TOP * h, w * (1 + 2 * FACE_PAD_SIDE), h * (1 + FACE_PAD_TOP + FACE_PAD_BOTTOM)]


def cover_window(aspect: float, zoom: float = 1.0) -> Tuple[float, float, float, float]:
    """The part of the picture (x0, y0, x1, y1 shares) a centred cover fit into 16:9 shows at `zoom`."""
    if aspect >= FRAME_ASPECT:
        half_w, half_h = FRAME_ASPECT / aspect / 2, 0.5
    else:
        half_w, half_h = 0.5, aspect / FRAME_ASPECT / 2
    half_w, half_h = half_w / max(1.0, zoom), half_h / max(1.0, zoom)
    return 0.5 - half_w, 0.5 - half_h, 0.5 + half_w, 0.5 + half_h


def crop_cuts_face(f: dict, zoom: float = 1.06) -> bool:
    """True when the centred 16:9 cover fit (at the gentlest move's zoom) cuts into a face's head and shoulders."""
    aspect = f["w"] / float(max(1, f["h"]))
    x0, y0, x1, y1 = cover_window(aspect, zoom)
    for face in f.get("faces") or []:
        # The head itself (brow to chin plus a little hair) must be whole; the shoulders may run off.
        top = face[1] - 0.35 * face[3]
        if face[0] < x0 - 1e-3 or face[0] + face[2] > x1 + 1e-3 or top < y0 - 1e-3 or face[1] + face[3] > y1 + 1e-3:
            return True
    return False


def is_portrait(scene: dict, f: dict) -> bool:
    """A card, never a crop: a named person's line, a tall or near-square picture, or a face the crop would cut."""
    sem = scene.get("semanticMetadata") or {}
    aspect = f["w"] / float(max(1, f["h"]))
    if aspect < CARD_ASPECT:
        return True
    if str(sem.get("subjectType") or "") == "person" and (f.get("faces") or aspect < FRAME_ASPECT):
        return True
    return crop_cuts_face(f)


def card_for(f: dict, beside_name: bool) -> dict:
    """media.card: the card's height (a share of the frame, never past its real detail x STILL_CARD_UPSCALE) and x."""
    up = float(getattr(config, "STILL_CARD_UPSCALE", 1.15) or 1.15)
    _ew, eh = detail_size(f)
    aspect = f["w"] / float(max(1, f["h"]))
    # Its real detail (x the allowed upscale), 84 % of the frame height, and - a wide one - 84 % of the frame width.
    size = min(CARD_MAX, eh * up / OUT_H, 0.84 * OUT_W / max(0.01, aspect) / OUT_H)
    return {"max": round(max(CARD_MIN, size), 3), "x": CARD_X_BESIDE_NAME if beside_name else 0.5}


def max_zoom(f: dict) -> float:
    """media.maxZoom: how far a cover-fitted still may be scaled in all (its move, a punch, a detail framing) before
    its real detail is shown past STILL_PEAK_MAGNIFICATION (a picture already past it at rest barely moves: 1.02)."""
    peak = float(getattr(config, "STILL_PEAK_MAGNIFICATION", 1.3) or 1.3)
    m0 = cover_magnification(f)
    return round(max(1.02, min(1.6, peak / max(0.01, m0))), 3)


def move_max() -> Optional[float]:
    """media.moveMax: the style's own ceiling on a still's move (STILL_MOTION_MAX_ZOOM; news holds photos nearly
    still, like its reference channel), None when the moves keep their own size."""
    cap = float(getattr(config, "STILL_MOTION_MAX_ZOOM", 0) or 0)
    return round(cap, 3) if 1.0 < cap < 1.38 else None


def face_aim(f: dict) -> Optional[dict]:
    """The biggest face's head and shoulders in FRAME shares of the cover fit (media.reframe.subject), or None."""
    faces = sorted(f.get("faces") or [], key=lambda x: -x[2] * x[3])
    if not faces:
        return None
    aspect = f["w"] / float(max(1, f["h"]))
    x0, y0, x1, y1 = cover_window(aspect, 1.0)
    hx, hy, hw, hh = _head(faces[0])
    fx0, fy0 = (hx - x0) / (x1 - x0), (hy - y0) / (y1 - y0)
    fx1, fy1 = (hx + hw - x0) / (x1 - x0), (hy + hh - y0) / (y1 - y0)
    fx0, fy0, fx1, fy1 = max(0.0, fx0), max(0.0, fy0), min(1.0, fx1), min(1.0, fy1)
    if fx1 - fx0 <= 0.01 or fy1 - fy0 <= 0.01 or (fx1 - fx0) * (fy1 - fy0) > 0.6:
        return None
    return {"x": round(fx0, 4), "y": round(fy0, 4), "w": round(fx1 - fx0, 4), "h": round(fy1 - fy0, 4)}


def _names_at(doc: dict, scene: dict) -> bool:
    """A name / place lower third (a smart label or a kinetic lower third) over this scene."""
    a = int(scene.get("startFrame") or 0)
    b = a + int(scene.get("durationInFrames") or 0)
    for o in doc.get("overlays") or []:
        if not isinstance(o, dict):
            continue
        s0 = int(o.get("startFrame") or 0)
        s1 = s0 + int(o.get("durationInFrames") or 0)
        if s1 <= a or s0 >= b:
            continue
        kind = str(((o.get("smart") or {}).get("design") or {}).get("kind") or "")
        if kind in ("label", "place") or str(o.get("template") or "") in ("KT_LOWER_THIRD", "LOWER_THIRD"):
            return True
    return False


def calm_motion(motion: str) -> str:
    """A flashy move of an old document as the calm push or pull it stands for."""
    m = str(motion or "none")
    if m in ("pull-back", "zoom-out"):
        return "zoom-out"
    if m in ("reveal-left", "reveal-right", "push-rotate", "rotate-settle"):
        return "push-offcenter"
    return m


def place(doc: dict, seconds: Optional[float] = None, facts_fn=None) -> Dict[str, object]:
    """Frame every local still of the document (see the module doc). Returns the counts for meta.stillFrame."""
    stats: Dict[str, object] = {"stills": 0, "measured": 0, "cards": 0, "aimed": 0, "capped": 0, "calmed": 0,
                                "seconds": 0.0}
    if not enabled():
        return stats
    t0 = time.time()
    budget = float(getattr(config, "STILL_FRAME_SECONDS", 60) if seconds is None else seconds)
    todo = [s for s in doc.get("scenes") or [] if isinstance(s, dict)
            and (s.get("media") or {}).get("type") == "image" and str(s.get("frame") or "full") == "full"
            and _local((s.get("media") or {}).get("url") or "")]
    stats["stills"] = len(todo)
    fn = facts_fn or facts
    got: Dict[int, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(int(getattr(config, "STILL_FRAME_PARALLEL", 4) or 4),
                                                   len(todo) or 1))) as ex:
        futs = {id(s): ex.submit(fn, s["media"]["url"]) for s in todo}
        for s in todo:
            left = budget - (time.time() - t0)
            try:
                got[id(s)] = futs[id(s)].result(timeout=max(0.1, left))
            except Exception:  # noqa: BLE001 - out of time or unreadable: the scene keeps its framing
                got[id(s)] = None
    mags = []
    for s in todo:
        m = s["media"]
        f = got.get(id(s))
        mot = str(s.get("motion") or "none")
        calm = calm_motion(mot)
        if calm != mot:
            s["motion"] = calm
            stats["calmed"] += 1
        if not f:
            continue
        f = with_known_detail(f, ((s.get("semanticMetadata") or {}).get("scoreParts") or {}).get("magnification"))
        stats["measured"] += 1
        mag = cover_magnification(f)
        mags.append(mag)
        m["pixels"] = {"w": f["w"], "h": f["h"], "lines": f["lines"]}
        if is_portrait(s, f):
            s["motion"] = "parallax"
            m["card"] = card_for(f, _names_at(doc, s))
            m.pop("reframe", None)
            stats["cards"] += 1
            continue
        if s["motion"] == "parallax":
            s["motion"] = "zoom-in"             # the card move is for portraits; a landscape fills the frame
        m["maxZoom"] = max_zoom(f)
        mm = move_max()
        if mm:
            m["moveMax"] = mm
        if min(m["maxZoom"], mm or 9.0) < MOVE_PEAK.get(str(s.get("motion") or "none"), 1.15) - 1e-3:
            stats["capped"] += 1
        aim = face_aim(f)
        if aim and not isinstance(m.get("reframe"), dict):
            m["reframe"] = {"subject": aim, "source": m.get("source") or "", "aspect": round(FRAME_ASPECT, 4),
                            "kind": "face"}
            stats["aimed"] += 1
    if mags:
        mags.sort()
        stats["restMagnification"] = {"median": round(mags[len(mags) // 2], 2),
                                      "over1.3": sum(1 for v in mags if v > 1.3)}
    stats["seconds"] = round(time.time() - t0, 1)
    print(f"[stillframe] {stats['measured']}/{stats['stills']} stills: {stats['cards']} portrait cards, "
          f"{stats['capped']} moves held to their detail, {stats['aimed']} aimed at a face, "
          f"{stats['calmed']} flashy moves calmed ({stats['seconds']} s)", flush=True)
    return stats
