"""
Video styles: how the whole video is edited, chosen per job (inp.video_style).

A style pack only colours the graphics. A style decides the editing itself:
shot length, what footage is looked for (vertical phone video or not), how
many graphics go on screen, which transitions cut between shots, and whether
music plays. Each style is a set of per-job config overrides (applied through
handler._apply_config, which fan-out parts inherit) plus a few job inputs.

news_compilation is measured from a real daily weather-news channel (four
Nor'easter videos, 2026-09-29): phone/social clips of the named towns, about
half of them vertical and shown on a blurred copy of themselves, shots of
3-12 s (median ~5.5 s), official NWS graphics and forecast maps, almost no
on-screen text, soft 0.5 s crossfades. The reference ran narration only; the
owner (2026-09-30) wants music under every style, news included (the timeline
picks the track by the story's mood and ducks it under the voice). News uses
real pictures only: no AI-generated images (IMAGE_MAX_PER_VIDEO 0).
"""
from __future__ import annotations

from typing import Dict

# transitions: the cutting style src/timeline.py plans (timeline.STYLES:
# documentary/history/story soft and rare, trending/compilation/explainer
# energetic flashes, glitches and whips, crossfade = soft 0.5 s dissolves).
# graphics: how busy the overlay planner is ("minimal", "normal", "rich").
# Every style has music (the owner, 2026-09-30); only the job's own
# "bgm": false turns it off.
STYLES: Dict[str, dict] = {
    "documentary": {
        "label": "Documentary",
        "transitions": "documentary", "graphics": "rich",
        "config": {},
    },
    "news_compilation": {
        "label": "News compilation",
        "transitions": "crossfade", "graphics": "minimal",
        "config": {"MIN_SCENE_SECONDS": 3.0, "TARGET_SCENE_SECONDS": 5.5, "MAX_SCENE_SECONDS": 12.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True,
                   # News shows what happened: never an AI-generated picture.
                   "IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False},
    },
    "trending_news": {
        "label": "Trending news",
        "transitions": "trending", "graphics": "normal",
        "config": {"MIN_SCENE_SECONDS": 3.0, "TARGET_SCENE_SECONDS": 5.0, "MAX_SCENE_SECONDS": 9.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True,
                   "IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False},
    },
    "story": {
        "label": "Story narration",
        "transitions": "story", "graphics": "normal", "pack": "cinematic",
        "config": {"MIN_SCENE_SECONDS": 4.0, "TARGET_SCENE_SECONDS": 6.5, "MAX_SCENE_SECONDS": 10.0},
    },
    "history": {
        "label": "History",
        "transitions": "history", "graphics": "rich", "pack": "history",
        "config": {"MIN_SCENE_SECONDS": 5.0, "TARGET_SCENE_SECONDS": 7.0, "MAX_SCENE_SECONDS": 10.0},
    },
    "explainer": {
        "label": "Explainer / trending topic",
        "transitions": "explainer", "graphics": "rich",
        "config": {"MIN_SCENE_SECONDS": 3.5, "TARGET_SCENE_SECONDS": 5.5, "MAX_SCENE_SECONDS": 8.0},
    },
    "compilation": {
        "label": "Compilation / Top list",
        "transitions": "compilation", "graphics": "normal",
        "config": {"MIN_SCENE_SECONDS": 3.0, "TARGET_SCENE_SECONDS": 5.0, "MAX_SCENE_SECONDS": 9.0,
                   "ALLOW_VERTICAL": True},
    },
}

_ALIASES = {"news": "trending_news", "news-compilation": "news_compilation", "compilation_news":
            "news_compilation", "top": "compilation", "top_list": "compilation", "documentary_story": "story"}


def resolve(name: str) -> str:
    """A known style id, or "" (auto: the story's kind decides as before)."""
    key = str(name or "").strip().lower().replace(" ", "_")
    key = _ALIASES.get(key, key)
    return key if key in STYLES else ""


_DENSITY = {"minimal": "minimal", "normal": "normal", "rich": "rich", "full": "rich", "less": "minimal",
            "more": "rich"}


def density(value) -> str:
    """The owner's Animations choice as a graphics density, or "" (auto)."""
    return _DENSITY.get(str(value or "").strip().lower(), "")


def apply(inp: dict) -> str:
    """
    Fold the job's video_style into its input, in place, before config
    overrides are applied: the style's config goes under inp["config"]
    (explicit per-job overrides win), and style / transition_style /
    graphics_density / style_pack defaults are set where the job left them
    empty. Music is never switched off by a style. Returns the resolved style
    id ("" for auto).
    """
    style = resolve(inp.get("video_style"))
    chosen = density(inp.get("graphics_density"))
    if not style:
        if chosen:
            # Animations picked with no style: only the density changes.
            cfg = dict(inp["config"]) if isinstance(inp.get("config"), dict) else {}
            cfg.setdefault("GRAPHICS_DENSITY", chosen)
            inp["config"] = cfg
            inp["graphics_density"] = chosen
        return ""
    spec = STYLES[style]
    merged = dict(spec.get("config") or {})
    if isinstance(inp.get("config"), dict):
        merged.update(inp["config"])
    # The owner's Animations choice beats the style's own default.
    merged.setdefault("GRAPHICS_DENSITY", chosen or spec["graphics"])
    merged.setdefault("TRANSITION_STYLE", spec["transitions"])
    inp["config"] = merged
    inp["video_style"] = style
    inp.setdefault("style", spec["transitions"])           # read by timeline.transition_style
    inp["graphics_density"] = merged["GRAPHICS_DENSITY"]
    if spec.get("pack") and not inp.get("style_pack"):
        inp["style_pack"] = spec["pack"]
    return style
