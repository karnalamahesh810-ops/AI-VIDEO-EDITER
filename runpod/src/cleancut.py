"""
Clean cut (the owner, 2026-10-28: our own text pops, number / data looks and motion cards are "literally bad, you
made it even worse recently"; and the measured news-compilation reference shows no on-screen text at all - yet the
Hoover Dam video, news_compilation, carried 63 graphics and 38 punch whooshes).

A per-job mode: footage with straight cuts, a short crossfade only now and then, gentle movement on stills, and none
of our in-house graphics - no text pops or statements, no number / date / data looks, no motion cards (full-screen
graphic scenes), no marks or pointers, no punch-ins or their whooshes, no look or transition sounds. What stays:

  * factual lower-third NAMES of people (the small clean style, src/motionspec.py LABEL_SIZE) - CLEAN_CUT_NAMES;
  * MAPS, only where the line names a place - CLEAN_CUT_MAPS;
  * the source / AI tags (LIB_SRC_TAG: a citation, the "AI: ILLUSTRATION" label - never dropped).

Default for news_compilation (src/styles.py: CLEAN_CUT); any other style keeps its graphics unless the job asks:
{"clean_cut": true} (or false to bring graphics back to a news video). fold_job puts the mode and its config into
the job before the plan (fewer generators run: no data looks, data graphics, marks, animation fills, punches); apply
is the last pass of the plan and settles whatever a planner still drew. meta.cleanCut reports it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from . import config

# Config a clean-cut job runs with (the job's own explicit values win): the generators of our graphics stay off.
OVERRIDES = {
    "DATA_GRAPHICS": False,          # full-screen data charts (LIB_RD_*)
    "MARKS_ENABLED": False,          # arrows / circles / pointers on the picture
    "ANIMATION_FILL": False,         # a motion card standing in for a missing shot
    "EDIT_V3_PUNCHES": False,        # editing v3 punch-ins ...
    "EDIT_V3_INTERRUPTS": False,     # ... and the "something new every 30 s" punches
    "EDIT_V3_PUNCH_SOUND": False,    # ... and their whooshes
    "EDIT_V3_SPLIT_HOLDS": False,    # no detail-crop "shots" of one photo (zoom crops)
    "STILL_MOTION_MAX_ZOOM": 1.06,   # gentle movement on stills
}
# Which overlays are names, maps and tags (everything else is one of our graphics).
_MAP_TEMPLATE = re.compile(r"MAP|GEO|LOCATOR|KT_PLACE|KT_REGIONS|KT_ROUTE|KT_STORM|KT_TOTALS|KT_TWO_PLACES", re.I)
_NAME_TEMPLATES = {"KT_LOWER_THIRD", "LOWER_THIRD", "PERSON_CARD_V1", "LIB_NAME_TAG"}
_TAG_TEMPLATES = {"LIB_SRC_TAG"}
# A short crossfade at most every this many cuts (the rest are straight cuts), never a flashy transition.
CROSSFADE_EVERY = 6


def wanted(inp: Optional[dict] = None, cfg: Optional[dict] = None) -> bool:
    """The job's own "clean_cut" (a bool) first, then its config's CLEAN_CUT (a style's default), then the
    template's CLEAN_CUT."""
    v = (inp or {}).get("clean_cut")
    if isinstance(v, bool):
        return v
    c = cfg if cfg is not None else ((inp or {}).get("config") if isinstance((inp or {}).get("config"), dict) else {})
    if isinstance(c, dict) and "CLEAN_CUT" in c:
        x = c["CLEAN_CUT"]
        return x if isinstance(x, bool) else str(x).strip().lower() in ("1", "true", "yes", "on")
    return bool(getattr(config, "CLEAN_CUT", False))


def fold_job(inp: dict) -> bool:
    """Fold the mode into the job before its config is applied: CLEAN_CUT and, when on, OVERRIDES (the job's own
    explicit values win) - so every part and pod of the job reads the same. Returns whether it is on."""
    if not isinstance(inp, dict):
        return False
    cfg = dict(inp["config"]) if isinstance(inp.get("config"), dict) else {}
    on = wanted(inp, cfg)
    cfg["CLEAN_CUT"] = on
    if on:
        explicit = inp.get("config") if isinstance(inp.get("config"), dict) else {}
        for k, v in OVERRIDES.items():
            if k not in explicit:
                cfg[k] = v
    inp["config"] = cfg
    return on


def enabled() -> bool:
    return bool(getattr(config, "CLEAN_CUT", False))


def _scene_at(scenes: list, frame: int) -> Optional[dict]:
    found = None
    for s in scenes:
        if int(s.get("startFrame") or 0) > frame:
            break
        found = s
    return found


def _names_place(scene: Optional[dict], overlay: dict) -> bool:
    """The line under a map names a place: its scene intent's locations, or the map's own place words."""
    sem = (scene or {}).get("semanticMetadata") or {}
    si = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else {}
    if any(str(x).strip() for x in (si.get("locations") or [])):
        return True
    if str(sem.get("subjectType") or "") == "place":
        return True
    return bool(str(overlay.get("text") or "").strip() or overlay.get("items") or overlay.get("places"))


def kind_of(overlay: dict) -> str:
    """'tag', 'name', 'map' or 'graphic' for one overlay."""
    tid = str(overlay.get("template") or "")
    if tid in _TAG_TEMPLATES or overlay.get("aiLabel"):
        return "tag"
    design = ((overlay.get("smart") or {}).get("design") or {}) if isinstance(overlay.get("smart"), dict) else {}
    dkind = str(design.get("kind") or "")
    if tid in _NAME_TEMPLATES or (tid == "SMART_SPEC" and dkind == "label"):
        return "name"
    if _MAP_TEMPLATE.search(tid) or (tid == "SMART_SPEC" and dkind == "map"):
        return "map"
    return "graphic"


def apply(doc: dict) -> Dict[str, Any]:
    """The last pass of a clean-cut plan (CLEAN_CUT): only names, maps where a place is named and tags stay; motion
    cards give their time to the shot before; transitions become straight cuts with a short crossfade every
    CROSSFADE_EVERY cuts; punch, look and transition sounds go. Returns the counts (also meta.cleanCut)."""
    out: Dict[str, Any] = {"on": True, "kept": {"name": 0, "map": 0, "tag": 0}, "dropped": 0, "cards": 0,
                           "sounds": 0, "crossfades": 0, "cuts": 0}
    if not isinstance(doc, dict):
        return out
    scenes = [s for s in doc.get("scenes") or [] if isinstance(s, dict)]
    names = bool(getattr(config, "CLEAN_CUT_NAMES", True))
    maps = bool(getattr(config, "CLEAN_CUT_MAPS", True))
    kept = []
    for o in doc.get("overlays") or []:
        if not isinstance(o, dict):
            continue
        k = kind_of(o)
        ok = k == "tag" or (k == "name" and names) or (
            k == "map" and maps and _names_place(_scene_at(scenes, int(o.get("startFrame") or 0)), o))
        if ok:
            kept.append(o)
            out["kept"][k] += 1
        else:
            out["dropped"] += 1
    doc["overlays"] = kept
    # Motion cards (a full-screen graphic as a scene): the shot before plays on over its time (the first: the next).
    merged = []
    for s in scenes:
        if (s.get("media") or {}).get("type") == "animation" or s.get("visualType") == "animation":
            out["cards"] += 1
            host = merged[-1] if merged else None
            if host is not None:
                host["durationInFrames"] = int(host.get("durationInFrames") or 0) + int(s.get("durationInFrames") or 0)
                host["text"] = " ".join(x for x in (str(host.get("text") or ""), str(s.get("text") or "")) if x)
                continue
            s["_cardLead"] = True
        merged.append(s)
    if merged and merged[0].pop("_cardLead", False) and len(merged) > 1:
        nxt = merged[1]
        nxt["durationInFrames"] = int(nxt.get("durationInFrames") or 0) + int(merged[0].get("durationInFrames") or 0)
        nxt["startFrame"] = int(merged[0].get("startFrame") or 0)
        nxt["transition"] = merged[0].get("transition", nxt.get("transition"))
        merged = merged[1:]
    for s in merged:
        s.pop("_cardLead", None)
    if out["cards"]:
        doc["scenes"] = merged
    # Straight cuts; a short crossfade now and then; never a flashy transition.
    n = 0
    for i, s in enumerate(doc.get("scenes") or []):
        if i == 0 or s.get("splitFrom"):
            continue
        n += 1
        out["cuts"] += 1
        if n % CROSSFADE_EVERY == 0 and s.get("transition") in ("crossfade", "fade", "blur-dissolve", "dissolve"):
            s["transition"] = "crossfade"
            out["crossfades"] += 1
        else:
            s["transition"] = "none"
            s.pop("transitionGain", None)
    # No punch whooshes, no look sounds, no transition sounds (the narration and the music carry it).
    sfx = doc.get("sfx") or []
    keep_sfx = [x for x in sfx if isinstance(x, dict) and str(x.get("kind") or "") not in
                ("punch", "smart", "look", "transition", "whoosh", "impact", "riser")]
    out["sounds"] = len(sfx) - len(keep_sfx)
    doc["sfx"] = keep_sfx
    doc.setdefault("meta", {})["cleanCut"] = out
    return out
