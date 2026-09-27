"""
The template registry, read from remotion/src/templates/registry.json.

One file describes every premade animation for the planner, the renderer and
the editor: which renderer component draws it, the props a user may change,
its style, entrance and exit variants, its default duration and sound, and
the narration cues the planner matches it on. This module is the Python
view of it: look-ups, style packs, and `resolve`, which turns a template
choice plus customisations into the overlay fields the renderer reads.
"""
import json
import os
from functools import lru_cache
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "remotion", "src", "templates", "registry.json")


@lru_cache(maxsize=1)
def load() -> dict:
    with open(PATH, encoding="utf-8") as fh:
        return json.load(fh)


def all_templates() -> List[dict]:
    return list(load()["templates"])


@lru_cache(maxsize=1)
def _index() -> Dict[str, dict]:
    return {t["id"]: t for t in load()["templates"]}


def get(template_id: str) -> Optional[dict]:
    return _index().get(template_id or "")


def by_category(category: str) -> List[dict]:
    return [t for t in load()["templates"] if t["category"] == category]


def for_component(component: str, style: str = "") -> List[dict]:
    """Templates drawn by one renderer component, the style pack's favourites first."""
    found = [t for t in load()["templates"] if t["component"] == component]
    if style:
        found.sort(key=lambda t: 0 if style in t["variants"]["style"] else 1)
    return found


def for_cue(cue: str, style: str = "", exclude: Optional[set] = None) -> List[dict]:
    """Templates the planner may use for a narration cue, in preference order."""
    out = [t for t in load()["templates"] if cue in t["cues"] and t["id"] not in (exclude or set())]
    if style:
        out.sort(key=lambda t: (0 if style in t["tags"] else 1, 0 if style in t["variants"]["style"] else 1))
    return out


def style_pack(name: str) -> dict:
    packs = load()["stylePacks"]
    return dict(packs.get(name or "") or packs["documentary"])


def style_packs() -> Dict[str, dict]:
    return dict(load()["stylePacks"])


def sfx(name: str) -> Optional[dict]:
    """A semantic sound ("MAP_PING") as {file, volume}."""
    return load()["sfx"].get(name)


def image_treatment(template_id: str) -> Optional[dict]:
    return next((t for t in load()["imageTreatments"] if t["id"] == template_id), None)


def transition_value(template_id: str) -> str:
    for t in load()["transitions"]:
        if t["id"] == template_id or t["value"] == template_id:
            return t["value"]
    return "none"


def resolve(template_id: str, *, style: str = "", entrance: str = "", exit_: str = "",
            props: Optional[dict] = None, pack: Optional[dict] = None) -> dict:
    """
    The overlay fields for one template choice: the component and its
    variant, theme, entrance/exit motion, duration and sound, then the
    customisations on top. Unknown props and out-of-range choices are dropped,
    so a document from the editor can never ask the renderer for a look it
    does not have.
    """
    t = get(template_id)
    if not t:
        return {}
    d = t["defaults"]
    pack = pack or {}
    out = {
        "type": t["component"], "template": t["id"],
        "style": style if style in t["variants"]["style"] else (pack.get("caption") if pack.get("caption") in t["variants"]["style"] else t["variants"]["style"][0]),
        "motion": entrance if entrance in t["variants"]["entrance"] else d["entrance"],
        "exit": exit_ if exit_ in t["variants"]["exit"] else d["exit"],
        "seconds": float(d["duration"]),
        "sfx": dict(d.get("sfx") or {"name": "none", "volume": 0.0}),
    }
    if d.get("variant"):
        out["variant"] = d["variant"]
    theme = d.get("theme") or pack.get("theme") or ""
    if theme and theme != "accent":
        out["theme"] = theme
    allowed = t["props"]
    for k, v in (props or {}).items():
        if k not in allowed:
            continue
        spec = allowed[k]
        if spec["type"] == "enum" and v not in spec["options"]:
            continue
        if spec["type"] == "number":
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if "min" in spec:
                v = max(spec["min"], min(spec["max"], v))
        if spec["type"] == "string":
            v = str(v)[: spec.get("max", 240)]
        if k == "duration":
            out["seconds"] = v
        elif k == "theme":
            if v == "accent":
                out.pop("theme", None)
            else:
                out["theme"] = v
        elif k == "sfx":
            if v == "default":
                pass
            elif v == "none":
                out["sfx"] = {"name": "none", "volume": 0.0}
            else:
                out["sfx"] = {"name": v, "volume": out["sfx"].get("volume") or 0.3}
        elif k == "sfxVolume":
            out["sfx"] = {**out["sfx"], "volume": v}
        else:
            out[k] = v
    return out


def check() -> List[str]:
    """Consistency problems, for the test suite."""
    problems = []
    reg = load()
    seen = set()
    for t in reg["templates"]:
        if t["id"] in seen:
            problems.append(f"duplicate id {t['id']}")
        seen.add(t["id"])
        if t["category"] not in reg["categories"]:
            problems.append(f"{t['id']}: unknown category {t['category']}")
        if float(t["defaults"]["duration"]) <= 0:
            problems.append(f"{t['id']}: duration")
        if t["defaults"]["entrance"] not in reg["entrances"]:
            problems.append(f"{t['id']}: entrance")
        if t["defaults"]["exit"] not in reg["exits"]:
            problems.append(f"{t['id']}: exit")
        sfx_name = (t["defaults"].get("sfx") or {}).get("name", "none")
        if sfx_name != "none" and sfx_name not in {v["file"] for v in reg["sfx"].values()}:
            problems.append(f"{t['id']}: sfx file {sfx_name}")
    for name, pack in reg["stylePacks"].items():
        for key in ("chapter", "map", "route", "region", "multi", "lowerThird"):
            if pack[key] not in seen:
                problems.append(f"style pack {name}: {key} -> {pack[key]} missing")
        if pack["caption"] not in reg["captionStyles"]:
            problems.append(f"style pack {name}: caption style")
        if pack["imageTreatment"] not in {i["id"] for i in reg["imageTreatments"]}:
            problems.append(f"style pack {name}: image treatment")
    return problems
