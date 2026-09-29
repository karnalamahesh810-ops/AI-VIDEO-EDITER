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
on-screen text, soft 0.5 s crossfades, narration only (no music).
"""
from __future__ import annotations

from typing import Dict

# transitions: the cutting style src/timeline.py plans (timeline.STYLES:
# documentary/history/story soft and rare, trending/compilation/explainer
# energetic flashes, glitches and whips, crossfade = soft 0.5 s dissolves).
# graphics: how busy the overlay planner is ("minimal", "normal", "rich").
STYLES: Dict[str, dict] = {
    "documentary": {
        "label": "Documentary",
        "transitions": "documentary", "graphics": "rich",
        "config": {},
    },
    "news_compilation": {
        "label": "News compilation",
        "transitions": "crossfade", "graphics": "minimal", "bgm": False,
        "config": {"MIN_SCENE_SECONDS": 3.0, "TARGET_SCENE_SECONDS": 5.5, "MAX_SCENE_SECONDS": 12.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True},
    },
    "trending_news": {
        "label": "Trending news",
        "transitions": "trending", "graphics": "normal",
        "config": {"MIN_SCENE_SECONDS": 3.0, "TARGET_SCENE_SECONDS": 5.0, "MAX_SCENE_SECONDS": 9.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True},
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


def apply(inp: dict) -> str:
    """
    Fold the job's video_style into its input, in place, before config
    overrides are applied: the style's config goes under inp["config"]
    (explicit per-job overrides win), and style / transition_style /
    graphics_density / style_pack / bgm defaults are set where the job left
    them empty. Returns the resolved style id ("" for auto).
    """
    style = resolve(inp.get("video_style"))
    if not style:
        return ""
    spec = STYLES[style]
    merged = dict(spec.get("config") or {})
    if isinstance(inp.get("config"), dict):
        merged.update(inp["config"])
    merged.setdefault("GRAPHICS_DENSITY", spec["graphics"])
    merged.setdefault("TRANSITION_STYLE", spec["transitions"])
    inp["config"] = merged
    inp["video_style"] = style
    inp.setdefault("style", spec["transitions"])           # read by timeline.transition_style
    inp.setdefault("graphics_density", spec["graphics"])
    if spec.get("pack") and not inp.get("style_pack"):
        inp["style_pack"] = spec["pack"]
    # Music off for styles that have none, unless the job picked a track.
    if spec.get("bgm") is False and "bgm" not in inp and not inp.get("bgm_url") and not inp.get("bgm_genre"):
        inp["bgm"] = False
    return style
