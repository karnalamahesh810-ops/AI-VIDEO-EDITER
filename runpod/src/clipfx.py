"""
A clip's keyframes, effects stack, mask and motion blur (Editor v2, the After-Effects layer): the cleaning
the renderer does (remotion/src/edit/keyframes.ts and edit/effects.ts), the same rules in Python, so a
timeline that comes back from the browser renders what the editor showed and never fails on a bad value.

    scene.keyframes   {x, y, scale, rotation, opacity, anchorX, anchorY: [{t, v, e?}]}
    scene.effects     [{type, value, on?}]  (an ordered stack)
    scene.mask        {shape, x, y, w, h, feather, invert?, radius?}
    scene.motionBlur  true (shutter 0.5) or a shutter 0..1

clean(doc) runs before the render (handler.do_render): each field cleaned in place, or removed when nothing
valid is left; nothing else in the scene is touched. A bad value is dropped or held to its range - never an
error. tests/test_clip_fx.py runs the TypeScript and this module on the same random documents.

The quality check reads two answers from here: a clip blurred on purpose (an editor's blur effect) is not
"blurry" and is never swapped for a sharper shot (blurs_on_purpose), and a clip the editor faded out or
darkened is not "black over a clip" (dark_on_purpose).
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

KEY_PROPS = ("x", "y", "scale", "rotation", "opacity", "anchorX", "anchorY")
PROP_RANGE = {"x": (-4.0, 4.0), "y": (-4.0, 4.0), "scale": (0.0, 20.0), "rotation": (-3600.0, 3600.0),
              "opacity": (0.0, 1.0), "anchorX": (-2.0, 2.0), "anchorY": (-2.0, 2.0)}
PROP_DEFAULT = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "anchorX": 0.0, "anchorY": 0.0}
EASE_NAMES = ("linear", "hold", "easeIn", "easeOut", "easeInOut", "expoOut", "backOut")
MAX_KEY_T = 86400.0
MAX_KEYS = 256

# type: (min, max) - edit/effects.ts EFFECTS
EFFECTS = {
    "brightness": (-1.0, 1.0), "contrast": (-1.0, 1.0), "saturation": (-1.0, 1.0), "temperature": (-1.0, 1.0),
    "tint": (-1.0, 1.0), "exposure": (-3.0, 3.0), "blur": (0.0, 1.0), "sharpen": (0.0, 1.0), "glow": (0.0, 1.0),
    "grain": (0.0, 1.0), "vignette": (0.0, 1.0), "chromatic": (0.0, 1.0), "lut-warm": (0.0, 1.0),
    "lut-cool": (0.0, 1.0), "bw": (0.0, 1.0),
}
MAX_EFFECTS = 24
MASK_SHAPES = ("rect", "ellipse", "roundrect")
DEFAULT_SHUTTER = 0.5
FIELDS = ("keyframes", "effects", "mask", "motionBlur")

_BEZIER = re.compile(r"^bezier:\s*(-?[\d.]+(?:e-?\d+)?)\s*,\s*(-?[\d.]+(?:e-?\d+)?)\s*,\s*(-?[\d.]+(?:e-?\d+)?)\s*,"
                     r"\s*(-?[\d.]+(?:e-?\d+)?)\s*$", re.IGNORECASE)


def _num(v: Any) -> Optional[float]:
    """A finite number (never a bool: JSON true is not 1 in the renderer)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _js_number(text: str) -> Optional[float]:
    """JavaScript's Number(text) for the bezier pattern's pieces ("1.", ".5", "1e-3"); None for NaN ("1.2.3")."""
    try:
        return float(text)
    except ValueError:
        return None


def parse_bezier(e: Any):
    if not isinstance(e, str):
        return None
    m = _BEZIER.match(e)
    if not m:
        return None
    p = [_js_number(g) for g in m.groups()]
    if any(x is None or not math.isfinite(x) for x in p):
        return None
    if p[0] < 0 or p[0] > 1 or p[2] < 0 or p[2] > 1 or abs(p[1]) > 5 or abs(p[3]) > 5:
        return None
    return p


def is_ease(e: Any) -> bool:
    return isinstance(e, str) and (e in EASE_NAMES or parse_bezier(e) is not None)


def clean_keys(raw: Any, prop: str) -> Optional[List[dict]]:
    if not isinstance(raw, list):
        return None
    lo, hi = PROP_RANGE[prop]
    out: List[dict] = []
    for k in raw:
        if not isinstance(k, dict):
            continue
        t, v = _num(k.get("t")), _num(k.get("v"))
        if t is None or v is None:
            continue
        key = {"t": _clamp(t, 0.0, MAX_KEY_T), "v": _clamp(v, lo, hi)}
        e = k.get("e")
        if is_ease(e) and e != "linear":
            key["e"] = e
        out.append(key)
        if len(out) >= MAX_KEYS:
            break
    if not out:
        return None
    out.sort(key=lambda x: x["t"])          # stable, like Array.prototype.sort
    return out


def clean_keyframes(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    out = {}
    for prop in KEY_PROPS:
        keys = clean_keys(raw.get(prop), prop)
        if keys:
            out[prop] = keys
    return out or None


def clean_effects(raw: Any) -> Optional[List[dict]]:
    if not isinstance(raw, list):
        return None
    out: List[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        kind = e.get("type")
        value = _num(e.get("value"))
        if not isinstance(kind, str) or kind not in EFFECTS or value is None:
            continue
        lo, hi = EFFECTS[kind]
        fx = {"type": kind, "value": _clamp(value, lo, hi)}
        if isinstance(e.get("on"), bool):
            fx["on"] = e["on"]
        out.append(fx)
        if len(out) >= MAX_EFFECTS:
            break
    return out or None


def clean_mask(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    shape = raw.get("shape")
    if not isinstance(shape, str) or shape not in MASK_SHAPES:
        return None
    x, y, w, h = (_num(raw.get(k)) for k in ("x", "y", "w", "h"))
    if x is None or y is None or w is None or h is None or w <= 0 or h <= 0:
        return None
    feather = _num(raw.get("feather"))
    out = {"shape": shape, "x": _clamp(x, -1.0, 2.0), "y": _clamp(y, -1.0, 2.0), "w": min(w, 3.0), "h": min(h, 3.0),
           "feather": 0.0 if feather is None else _clamp(feather, 0.0, 1.0)}
    if isinstance(raw.get("invert"), bool):
        out["invert"] = raw["invert"]
    radius = _num(raw.get("radius"))
    if radius is not None:
        out["radius"] = _clamp(radius, 0.0, 0.5)
    return out


def clean_motion_blur(raw: Any) -> Optional[float]:
    if raw is True:
        return DEFAULT_SHUTTER
    v = _num(raw)
    if v is None or v <= 0:
        return None
    return min(1.0, v)


def clean_scene(scene: dict) -> dict:
    """{keyframes?, effects?, mask?, motionBlur?} of a scene, cleaned (edit/effects.ts cleanClipFx)."""
    out: Dict[str, Any] = {}
    if not isinstance(scene, dict):
        return out
    kf = clean_keyframes(scene.get("keyframes"))
    if kf:
        out["keyframes"] = kf
    fx = clean_effects(scene.get("effects"))
    if fx:
        out["effects"] = fx
    mask = clean_mask(scene.get("mask"))
    if mask:
        out["mask"] = mask
    mb = clean_motion_blur(scene.get("motionBlur"))
    if mb is not None:
        out["motionBlur"] = mb
    return out


def clean(doc: Any) -> int:
    """
    Every scene's keyframes / effects / mask / motionBlur cleaned in place (a field with nothing valid left
    is removed). Returns how many fields were changed or removed. Never raises.
    """
    changed = 0
    try:
        scenes = doc.get("scenes") if isinstance(doc, dict) else None
        for s in scenes if isinstance(scenes, list) else []:
            if not isinstance(s, dict) or not any(k in s for k in FIELDS):
                continue
            cleaned = clean_scene(s)
            for k in FIELDS:
                if k not in s:
                    continue
                if k in cleaned:
                    if cleaned[k] != s[k]:
                        changed += 1
                    s[k] = cleaned[k]
                else:
                    s.pop(k, None)
                    changed += 1
    except Exception as e:  # noqa: BLE001 - cleaning must never be what fails a render
        print(f"[clipfx] not cleaned: {type(e).__name__}: {str(e)[:120]}", flush=True)
    return changed


def _live(scene: dict) -> List[dict]:
    return [e for e in (clean_effects(scene.get("effects") if isinstance(scene, dict) else None) or [])
            if e.get("on") is not False and e["value"] != 0]


def blurs_on_purpose(scene: dict) -> bool:
    """The editor blurred this clip on purpose (a blur effect, edit/effects.ts blursOnPurpose)."""
    return any(e["type"] == "blur" and e["value"] >= 0.05 for e in _live(scene))


def dark_on_purpose(scene: dict) -> bool:
    """
    The editor made this clip go dark on purpose: its opacity keyed down to (near) nothing, an exposure or
    brightness effect that crushes it, or a mask leaving most of the frame black. Black over such a clip is
    the edit, not a defect.
    """
    if not isinstance(scene, dict):
        return False
    kf = clean_keyframes(scene.get("keyframes")) or {}
    if any(k["v"] <= 0.1 for k in kf.get("opacity") or []):
        return True
    if any(k["v"] <= 0.05 for k in kf.get("scale") or []):
        return True
    for e in _live(scene):
        if (e["type"] == "exposure" and e["value"] <= -2) or (e["type"] == "brightness" and e["value"] <= -0.7):
            return True
    mask = clean_mask(scene.get("mask"))
    if mask:
        x0, y0 = max(0.0, mask["x"]), max(0.0, mask["y"])
        x1, y1 = min(1.0, mask["x"] + mask["w"]), min(1.0, mask["y"] + mask["h"])
        inside = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        shown = 1.0 - inside if mask.get("invert") else inside
        if shown < 0.5:
            return True
    return False
