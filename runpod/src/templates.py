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


# The owner (2026-09-29): the white words with red underline / red accent
# blocks (the ProHeadline family) must never be used again. No planner path
# may choose these; the editor can still open an old document that has one.
#
# The animation audit (2026-09-30, grades D/F): amateur or broken renders, and
# every boxed or banded date, time and age look (the owner: "NO background
# layout, ONLY TEXT: the date in white BOLD ... with a black stroke") - dates,
# times and ages go to the text-only looks (LibBoldText). They stay renderable.
AUDIT_BANNED = frozenset({
    "HEADLINE_TITLE_V1", "HEADLINE_NEWS_V1", "TL_RULER_V1", "TL_SPAN_V1", "TL_DATE_STAMP_V1", "TL_DATE_TITLE_V1",
    "TL_AGE_TAG_V1", "TL_CLOCK_V1", "DOC_ARTICLE_V1", "QUOTE_CALLOUT_V1", "LIB_PB_DATE_PLATE", "LIB_CO_SPEECH_BUBBLE",
    "LIB_CO_CHIP_STACK", "LIB_NS_DUAL_GAUGE", "LIB_CA_RADIAL_BARS", "LIB_AL_COUNTDOWN_TIMER", "LIB_AL_LIVE_TAG",
    "LIB_AL_SLIM_TICKER", "LIB_SC_WATER_CYCLE", "LIB_SC_MOLECULE_ORBIT", "LIB_SC_HEAT_SUN", "LIB_CC_CIRCLE_ROW",
    "LIB_CC_WAVE_CHAIN", "LIB_SP_CIRCLE_LIST", "LIB_ED_GLASS_CAPTION", "LIB_DT_CLEAN_CARD", "LIB_DT_CALENDAR_PAGE",
    "LIB_DT_STAMP_BAR", "LIB_DT_CLOCK_TIME", "LIB_DT_REC_STAMP", "LIB_DT_DATE_SLAM", "LIB_DT_TIMELINE_TICK",
    "LIB_DT_COUNTDOWN_DAYS", "LIB_PE_ZOOM_CIRCLE", "NUM_DONUT_V1", "NUM_NUMBER_ROLL_V1", "CHART_PIE_V1",
})
BANNED = frozenset({"TEXT_UNDERLINE_TITLE_V1", "TEXT_SWOOSH_TITLE_V1", "TEXT_SENTENCE_HIGHLIGHT_V1",
                    "TEXT_WORD_TYPE_V1"}) | AUDIT_BANNED


def banned(template_id: str) -> bool:
    return (template_id or "") in BANNED


def auto_pick(t) -> bool:
    """
    False for a look registered with "autoPick": false (library_looks.json):
    built, rendered and offered in the editor, but never chosen by the
    planner on its own until the owner switches it on (the new pro looks
    wait for his approval of their contact sheets). Takes a template or its
    id; an id that is not in the registry is False. A template without the
    flag is picked as before.
    """
    if isinstance(t, str):
        t = get(t)
    if not isinstance(t, dict):
        return False
    return t.get("autoPick", True) is not False


# The planner's cue vocabulary for the built-in looks. The library looks carry
# the new cues in library_looks.json; the built-ins predate them, so the
# planner reads these on top of each template's own "cues" (the registry file
# is not changed). Only looks that draw the cue well are listed: a typed memo
# is a typewriter line, a person card is a full-screen introduction, a date
# stamp can type a date and a time together.
EXTRA_CUES: Dict[str, List[str]] = {
    "TEXT_KEY_PHRASE_V1": ["key-phrase", "caption"],
    "TEXT_KICKER_V1": ["caption", "key-phrase"],
    "TEXT_MEMO_V1": ["typewriter", "statement", "fact"],
    "TEXT_BAR_TITLE_V1": ["typewriter", "headline"],
    "TEXT_TYPEWRITER_V1": ["typewriter", "statement"],
    "TEXT_LABEL_PILL_V1": ["count"],
    "LIB_SP_STATEMENT_CARD": ["statement", "fact"],
    "TL_DATE_STAMP_V1": ["datetime", "time-of-day"],
    "TL_CLOCK_V1": ["time-of-day"],
    "NUM_BIG_COUNTER_V1": ["count"],
    "NUM_NUMBER_ROLL_V1": ["count"],
    "PERSON_CARD_V1": ["photo-person", "person-full"],
    "PLACE_CARD_V1": ["photo-place"],
    "OBJECT_CARD_V1": ["photo-object"],
    "PHOTO_EVIDENCE_V1": ["photo-object"],
    "PHOTO_WINDOW_V1": ["photo-place"],
}

# Built-in components that really type their text letter by letter
# (TextGraphics MemoBox / BarTitle, DateStamp, and the typewriter, which the
# renderer now draws with the typing look EdTypeClean). Library looks say so
# with "types": true in their registry defaults.
TYPING_COMPONENTS = {"memo-box", "bar-title"}
TYPING_IDS = {"TEXT_TYPEWRITER_V1"}


def cues_of(t: dict) -> List[str]:
    """Every cue a template answers to: its own, plus the planner's vocabulary for the built-ins."""
    return list(t.get("cues") or []) + [c for c in EXTRA_CUES.get(t.get("id", ""), []) if c not in (t.get("cues") or [])]


def types(t: Optional[dict]) -> bool:
    """True for a look that types its text letter by letter (the typing-speed contract applies)."""
    if not t:
        return False
    d = t.get("defaults") or {}
    if "types" in d:
        return bool(d.get("types"))
    if t.get("id") in TYPING_IDS or t.get("component") in TYPING_COMPONENTS:
        return True
    return t.get("component") == "date-stamp" and not d.get("variant")


def family(t: Optional[dict]) -> str:
    """
    The look family, for "never the same family twice in a row": a library
    look's family ("ed", "dt", "ct", "pe", "hl"...), a built-in's id prefix
    ("TEXT", "NUM", "TL", "MAP"...; the photo cards are one family).
    """
    if not t:
        return ""
    tags = t.get("tags") or []
    if t.get("component") == "motion":
        if len(tags) >= 2 and tags[0] == "lib":
            return str(tags[1])
        v = str((t.get("defaults") or {}).get("variant") or "")
        return v.split("-", 1)[0] if v else "lib"
    head = str(t.get("id") or "").split("_", 1)[0]
    return {"PLACE": "PHOTO", "OBJECT": "PHOTO", "PERSON": "PHOTO", "FACTS": "CALL", "DOSSIER": "CALL",
            "TAG": "CALL", "CMP": "CHART"}.get(head, head)


def for_component(component: str, style: str = "") -> List[dict]:
    """Templates drawn by one renderer component, the style pack's favourites first (never a banned look, never
    one waiting to be switched on: auto_pick)."""
    found = [t for t in load()["templates"] if t["component"] == component and t["id"] not in BANNED and auto_pick(t)]
    if style:
        found.sort(key=lambda t: 0 if style in t["variants"]["style"] else 1)
    return found


_CUE_INDEX: Dict[int, Dict[str, List[dict]]] = {}


def _by_cue() -> Dict[str, List[dict]]:
    """cue -> templates in registry order, built once per registry (the planner asks it on every beat)."""
    reg = load()
    idx = _CUE_INDEX.get(id(reg))
    if idx is None:
        idx = {}
        for t in reg["templates"]:
            for c in cues_of(t):
                idx.setdefault(c, []).append(t)
        _CUE_INDEX.clear()
        _CUE_INDEX[id(reg)] = idx
    return idx


def for_cue(cue: str, style: str = "", exclude: Optional[set] = None) -> List[dict]:
    """Templates the planner may use for a narration cue, in preference order (never a banned look, never one
    waiting to be switched on: auto_pick)."""
    out = [t for t in _by_cue().get(cue, []) if t["id"] not in (exclude or set()) and t["id"] not in BANNED
           and auto_pick(t)]
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


SFX_DIR = os.path.join(os.path.dirname(PATH), "..", "..", "public", "sfx")


def sfx_files() -> set:
    """The sound names the renderer can play: public/sfx/<name>.mp3."""
    try:
        return {f[:-4] for f in os.listdir(SFX_DIR) if f.endswith(".mp3")}
    except OSError:
        return set()


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
        # A named semantic sound, or any file that ships in public/sfx (the
        # sound pass added whoosh-soft, keys, tick... next to the old set).
        if sfx_name != "none" and sfx_name not in {v["file"] for v in reg["sfx"].values()} \
                and sfx_name not in sfx_files():
            problems.append(f"{t['id']}: sfx file {sfx_name}")
    # Every sound the registry names must ship with the renderer: a missing
    # file is a 404 that kills the whole render, not a silent beat.
    for name in sorted({v["file"] for v in reg["sfx"].values()} | set(reg["templates"][0]["props"]["sfx"]["options"]) - {"default", "none"}):
        if name not in sfx_files():
            problems.append(f"sfx file missing: public/sfx/{name}.mp3")
    for name, pack in reg["stylePacks"].items():
        for key in ("chapter", "map", "route", "region", "multi", "lowerThird"):
            if pack[key] not in seen:
                problems.append(f"style pack {name}: {key} -> {pack[key]} missing")
        if pack["caption"] not in reg["captionStyles"]:
            problems.append(f"style pack {name}: caption style")
        if pack["imageTreatment"] not in {i["id"] for i in reg["imageTreatments"]}:
            problems.append(f"style pack {name}: image treatment")
    return problems
