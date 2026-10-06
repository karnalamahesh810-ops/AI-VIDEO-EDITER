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

nature_weather ("Nature & Weather", the owner, 2026-09-30: "most clips are
realistic flood/storm footage of the exact place, few images, and the editing
keeps people watching to the end, like something is coming") is the same
reference channel built out: every line searched as the place it names plus
the event, the way eyewitness uploads are titled (EYEWITNESS_SEARCHES);
forward-looking lines cut to what is coming - clouds rolling in, a shelf
cloud, the radar, the live satellite loop (COMING_SHOTS); the opening asks for
the most dramatic real clips (HOOK_INTENSITY) and every pick prefers footage
that moves (MOTION_PREFERENCE); a few real photos per 10 minutes and no AI
image (PHOTO_MAX_PER_10MIN, IMAGE_MAX_PER_VIDEO 0); cuts that follow the
narration and never hold a shot past 7 s (the owner's rule); dates as the
only graphics (GRAPHICS_DENSITY minimal, no marks); suspense music, ducked.
"""
from __future__ import annotations

from typing import Dict

# transitions: the cutting style src/timeline.py plans (timeline.STYLES:
# documentary/history/story soft and rare, trending/compilation/explainer
# energetic flashes, glitches and whips, crossfade = soft 0.5 s dissolves).
# graphics: how busy the overlay planner is ("minimal", "normal", "rich").
# Every style has music (the owner, 2026-09-30); only the job's own
# "bgm": false turns it off.
# No shot on screen longer than SHOT_MAX_SECONDS (src/shotcap.py; the owner,
# 2026-10-04: "some of the clips are playing more than seven seconds on the
# timeline"): every style follows the 7 s default, whatever its cutting ceiling
# (MAX_SCENE_SECONDS: a longer beat is cut into 2+ shots on word boundaries). A
# style may set its own "SHOT_MAX_SECONDS" in its config; none may go above
# 12 s (shotcap.CEILING).
STYLES: Dict[str, dict] = {
    "documentary": {
        "label": "Documentary",
        "transitions": "documentary", "graphics": "rich",
        "config": {},
    },
    "news_compilation": {
        "label": "News compilation",
        "transitions": "crossfade", "graphics": "minimal",
        # Re-measured 2026-09-30 (scratchpad ref_noreaster/style_rules.json):
        # footage shots median 5.3 s, p10 1.8 s, the picture changing 0.14 s
        # before a sentence; the owner's rule caps a shot at 7 s. The Nature &
        # Weather work where it applies: eyewitness searches of the named
        # place in its region, one strong clip cut into several shots, moving
        # footage, no TV studio or AI (src/slop.py, every style).
        "config": {"MIN_SCENE_SECONDS": 2.2, "TARGET_SCENE_SECONDS": 5.3, "MAX_SCENE_SECONDS": 7.0,
                   "CUT_FAST_SECONDS": 5.3, "CUT_SLOW_SECONDS": 6.5, "CUT_HOOK_FACTOR": 1.2,
                   "CUT_LEAD_SECONDS": 0.14,
                   # Its own measured rule, kept whatever the default becomes (src/shotcap.py).
                   "SHOT_MAX_SECONDS": 7.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True,
                   # News shows what happened: never an AI-generated picture.
                   "IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False,
                   "EYEWITNESS_SEARCHES": True, "REGION_BLOCKS": True, "CHAIN_SHOTS": True,
                   "MOTION_PREFERENCE": 0.08, "RECENT_FOOTAGE_FIRST": True, "POOL_JUDGE_CLIPS": True,
                   # News clips as shot: never pushed or cropped (the owner, src/reframe.py).
                   "REFRAME_CLIPS": False,
                   # A news compilation is clips (the owner, 2026-10-06: ~85%+): every line but a
                   # document's asks for a clip on all its wordings and one more wider rung first, and
                   # real photos stay a few per 10 minutes.
                   "CLIPS_FIRST": True, "CLIPS_FIRST_STILLS": True, "CLIP_RUNGS": 4,
                   "PHOTO_MAX_PER_10MIN": 8.0},
    },
    "nature_weather": {
        "label": "Nature & Weather",
        "transitions": "crossfade", "graphics": "minimal", "music": "suspense",
        # The reference channel (four Nor'easter videos, re-measured
        # 2026-09-30) under the owner's rules: a shot never past 7 s, so its
        # long takes become a clip cut forward into several shots (CHAIN_SHOTS);
        # median 5.3 s, the hook held longer (x1.25, the reference's hook runs
        # 7.0 s against 5.5 s), no faster cutting on intense lines (fast =
        # target), figures and settings held longer, the cut 0.14 s before a
        # new sentence. Real footage of the named place in its region, recent
        # first; real photos allowed but a minority (PHOTO_MAX_PER_10MIN 12,
        # ~12% of the time at 6 s each); never AI or a TV studio.
        "config": {"MIN_SCENE_SECONDS": 2.2, "TARGET_SCENE_SECONDS": 5.3, "MAX_SCENE_SECONDS": 7.0,
                   "CUT_FAST_SECONDS": 5.3, "CUT_SLOW_SECONDS": 6.5, "CUT_HOOK_FACTOR": 1.25,
                   "CUT_LEAD_SECONDS": 0.14, "HUMAN_CUTS": True, "SHOT_MAX_SECONDS": 7.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True, "RECENT_FOOTAGE_FIRST": True,
                   "IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False,
                   "GENERATED_IMAGES_IN_HOOK": False, "PHOTO_MAX_PER_10MIN": 12.0,
                   "EYEWITNESS_SEARCHES": True, "REGION_BLOCKS": True, "CHAIN_SHOTS": True, "CHAIN_MAX": 3,
                   "COMING_SHOTS": True, "HOOK_INTENSITY": True, "HOOK_SECONDS": 50.0,
                   "MOTION_PREFERENCE": 0.12, "POOL_JUDGE_CLIPS": True,
                   # Dates are the only graphics (the date look is the renderer's).
                   "MARKS_ENABLED": False,
                   # Real photos held still, as the reference shows them (no zoom or pan),
                   # and its eyewitness/news clips as shot (src/reframe.py).
                   "STILL_MOTION": "none", "REFRAME_CLIPS": False},
    },
    "trending_news": {
        "label": "Trending news",
        "transitions": "trending", "graphics": "normal",
        "config": {"MIN_SCENE_SECONDS": 3.0, "TARGET_SCENE_SECONDS": 5.0, "MAX_SCENE_SECONDS": 9.0,
                   "ALLOW_VERTICAL": True, "NEWS_FOOTAGE": True,
                   "IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False, "REFRAME_CLIPS": False},
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

# The owner's overlay transition pack (remotion/public/transitions, 2026-10-01:
# "not on every clip - some clips don't need a transition, some need one; never
# the same transition on the next one; use it tastefully; update this for every
# style that needs transitions"). timeline.plan_pack_transitions reads, per style:
#   gap        - fewest seconds between two pack transitions
#   every      - the spacing it aims for on average: a cut that has only a pause
#                or a new subject going for it waits this long after the last
#   fill       - after this long without one, any sentence start may take one
#                (0: never - only the moments the style names)
#   only       - when set, the only moments that may take one
#   impact     - how much an impact line ("exploded", "collapsed") counts
#   clear      - seconds either side kept free of the style's own transitions
#   characters - how much the style likes each look (flash, burn, leak, film,
#                glitch, streak); the line's own words add to it
# Calm styles mark their turns rarely and softly (leaks, burns, film); news,
# trending and compilations punctuate more, with flashes and glitches; Nature &
# Weather only at a region change and the end of the hook, flashes and leaks.
PACK_TRANSITIONS: Dict[str, dict] = {
    "documentary": {"gap": 12.0, "every": 38.0, "fill": 75.0, "impact": 0.5, "clear": 4.0,
                    "characters": {"leak": 3.0, "burn": 2.6, "film": 2.2, "flash": 1.2, "streak": 0.6, "glitch": 0.2}},
    "history": {"gap": 12.0, "every": 36.0, "fill": 75.0, "impact": 0.5, "clear": 4.0,
                "characters": {"burn": 3.0, "film": 3.0, "leak": 2.0, "flash": 1.0, "streak": 0.4, "glitch": 0.2}},
    "story": {"gap": 12.0, "every": 40.0, "fill": 80.0, "impact": 0.5, "clear": 4.0,
              "characters": {"leak": 3.0, "burn": 2.6, "film": 1.8, "flash": 1.4, "streak": 0.5, "glitch": 0.2}},
    "explainer": {"gap": 10.0, "every": 32.0, "fill": 60.0, "impact": 1.0, "clear": 3.0,
                  "characters": {"flash": 2.6, "streak": 2.6, "leak": 2.2, "glitch": 1.6, "film": 1.0, "burn": 1.0}},
    "trending_news": {"gap": 8.0, "every": 25.0, "fill": 45.0, "impact": 1.5, "clear": 2.5,
                      "characters": {"flash": 3.0, "glitch": 2.6, "streak": 2.6, "burn": 1.2, "leak": 0.8,
                                     "film": 0.6}},
    "compilation": {"gap": 8.0, "every": 25.0, "fill": 45.0, "impact": 1.5, "clear": 2.5,
                    "characters": {"flash": 3.0, "glitch": 2.6, "streak": 2.4, "burn": 1.6, "film": 1.0, "leak": 0.8}},
    "news_compilation": {"gap": 10.0, "every": 30.0, "fill": 60.0, "impact": 1.5, "clear": 2.5,
                         "characters": {"flash": 3.0, "glitch": 2.2, "streak": 2.2, "leak": 1.4, "burn": 0.8,
                                        "film": 0.6}},
    "nature_weather": {"gap": 15.0, "every": 60.0, "fill": 0.0, "impact": 0.0, "clear": 2.5,
                       "only": ("region", "hook"),
                       "characters": {"flash": 3.0, "leak": 3.0, "streak": 1.0, "burn": 0.4, "film": 0.2,
                                      "glitch": 0.2}},
}
# A job with no video style cuts in a transition style (timeline.STYLES); the
# pack rhythm that goes with it.
PACK_FOR_CUT_STYLE = {"documentary": "documentary", "history": "history", "story": "story",
                      "explainer": "explainer", "news": "trending_news", "trending": "trending_news",
                      "compilation": "compilation", "weather": "nature_weather", "crossfade": "news_compilation"}


def pack_rhythm(video_style: str = "", cut_style: str = "") -> dict:
    """The pack-transition rhythm of a job: its video style's, else its cutting style's, else the documentary one."""
    key = resolve(video_style) or PACK_FOR_CUT_STYLE.get(str(cut_style or "").strip().lower(), "")
    key = key if key in PACK_TRANSITIONS else "documentary"
    return {"style": key, **PACK_TRANSITIONS[key]}


_ALIASES = {"news": "trending_news", "news-compilation": "news_compilation", "compilation_news":
            "news_compilation", "top": "compilation", "top_list": "compilation", "documentary_story": "story",
            "nature": "nature_weather", "weather": "nature_weather", "nature_&_weather": "nature_weather",
            "nature_and_weather": "nature_weather", "nature-weather": "nature_weather",
            "nature/weather": "nature_weather", "nature_/_weather": "nature_weather"}


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
    empty. Music is never switched off by a style; a style with a "music"
    mood (nature_weather: suspense) picks it unless the job chose a track or
    genre (bgm_genre). Returns the resolved style id ("" for auto).
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
    if spec.get("music") and not inp.get("bgm_genre") and not inp.get("bgm_track") and not inp.get("bgm_url"):
        inp["bgm_genre"] = spec["music"]            # read by timeline._bgm_for; ducked under the voice
    return style
