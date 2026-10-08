"""
What an AI presenter video costs and how long it takes to make, per tier, before it is made.

The app shows these numbers on the style card ($ per 10 / 15 / 20-minute
video). The arithmetic is the research's cost model (scratchpad
avatar_research/cost_model4.py, docs/ai-avatar-style-plan-2026-10-07.md
section 6) with the counts the owner's reference videos actually use
(docs/ai-avatar-reference-analysis-2026-10-07.md section 8: a 20-minute video
is ~200-240 stills, ~30-40 clips and ~2.5-4 minutes of presenter) and the
tier's own shares and first-choice models:

  presenter   on-screen seconds x 1.1 (handles and retakes) x its $/s; one
              appearance per ~5 s on screen (on-screen seconds = the tier's
              share x the length, never past the job's max_seconds when it
              sends one; the stills take the rest)
  AI video    on-screen seconds x 1.4 (trims and rejected takes) x its $/s;
              one clip per ~4.5 s on screen, each from its own start still
  pictures    one new still per ~4 s of still time, the clips' start stills
              (x 1.1 for retakes), and one still per split-screen appearance;
              the presenter-in-action share at Nano Banana Pro's price
  fixed       script ~$0.013/min, our voice ~$0.0075/min ($0 when the user
              uploads their own), planning + prompts + checks ~$0.04/min,
              edit and render on a RunPod CPU worker ~$0.02 + $0.033/min

Times (minutes) are estimates from the same model: pictures ~20 s each 8 at
a time, presenter shots ~2 min per job 10 at a time, AI clips ~1 min
(Seedance, Veo) or ~4.4 min (MiniMax, Wan) 16 at a time.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from . import tiers as _tiers

OVER_PRESENTER = 1.1
OVER_VIDEO = 1.4
CLIP_ON_SCREEN = 4.5
PRESENTER_APPEARANCE = 5.0
START_SPARE = 1.1
SECONDS_PER_PICTURE = 4.0
SCRIPT_PER_MIN = 0.20 / 15
VOICE_PER_MIN = 0.0075
PLAN_PER_MIN = 0.04
RENDER_BASE, RENDER_PER_MIN = 0.02, 0.033
PAR_PICTURES, PAR_PRESENTER, PAR_CLIPS = 8, 10, 16
SLOW_CLIP_MODELS = ("minimax/", "alibaba/wan")


def estimate(minutes: float, tier: Any = None, *, own_voice: bool = False,
             overrides: Optional[dict] = None, max_seconds: Optional[float] = None) -> Dict[str, Any]:
    """
    $ and minutes for one video of `minutes` at `tier` ({"usd", "parts", "counts", "makeMinutes", ...});
    `max_seconds`: the job's cap on the presenter's whole time (the stills take the rest).
    """
    spec = tier if isinstance(tier, dict) and "presenter_share" in tier else _tiers.resolve(tier, overrides)
    m = max(0.0, float(minutes or 0.0))
    s = m * 60.0
    p_share, v_share = float(spec["presenter_share"]), float(spec["ai_video_share"])
    presenter_s, video_s = s * p_share, s * v_share
    if max_seconds and float(max_seconds) > 0:
        presenter_s = min(presenter_s, float(max_seconds))
    still_s = max(0.0, s - presenter_s - video_s)

    pres_model, pres_res = (list(spec.get("presenter_model") or ["heygen/avatar-iv", "1080p"]) + ["1080p"])[:2]
    video = (_tiers.pairs(spec, "video_models") or [("bytedance/seedance-1-5-pro", "720p")])[0]
    image = (_tiers.pairs(spec, "image_models") or [("google/gemini-nano-banana-2.1", "2K")])[0]
    pimage = (_tiers.pairs(spec, "presenter_image_models") or [("google/gemini-3-pro-image", "2K")])[0]

    appearances = presenter_s / PRESENTER_APPEARANCE
    clips = video_s / CLIP_ON_SCREEN
    stills = still_s / SECONDS_PER_PICTURE
    start_stills = clips * START_SPARE
    split_stills = appearances * float(spec.get("split_share") or 0.0)
    pictures = stills + start_stills + split_stills
    in_action = (stills + start_stills) * float(spec.get("presenter_broll") or 0.0)

    presenter_usd = presenter_s * OVER_PRESENTER * _tiers.usd_per_second(pres_model, pres_res)
    video_usd = video_s * OVER_VIDEO * _tiers.usd_per_second(*video)
    pictures_usd = (pictures - in_action) * _tiers.image_usd(*image) + in_action * _tiers.image_usd(*pimage)
    fixed = {"script": SCRIPT_PER_MIN * m, "voice": 0.0 if own_voice else VOICE_PER_MIN * m,
             "planAndChecks": PLAN_PER_MIN * m, "editAndRender": (RENDER_BASE + RENDER_PER_MIN * m) if m else 0.0}
    parts = {"presenter": presenter_usd, "aiVideo": video_usd, "pictures": pictures_usd, **fixed}
    total = sum(parts.values())

    # How long it takes (minutes): script, voice, planning, then the generation (the slowest pool), then the render.
    clip_minutes = 4.4 if str(video[0]).startswith(SLOW_CLIP_MODELS) else 1.0
    t_pictures = pictures * 20.0 / PAR_PICTURES / 60.0
    t_presenter = (appearances / PAR_PRESENTER) * 2.0
    t_clips = start_stills * 20.0 / PAR_PICTURES / 60.0 * 0.3 + (clips * START_SPARE / PAR_CLIPS) * clip_minutes
    generate = max(t_pictures, t_presenter, t_clips) + 2.0 if m else 0.0
    render = (0.6 * m + 1.0) if m else 0.0          # 7 / 10 / 13 min for 10 / 15 / 20 min (RunPod CPU)
    make = (2.0 + (0.2 * m + 2.0) + 3.0 + generate + render) if m else 0.0
    return {
        "tier": spec.get("id"), "label": spec.get("label"), "minutes": m,
        "maxSeconds": float(max_seconds) if max_seconds and float(max_seconds) > 0 else None,
        "usd": round(total, 2),
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "seconds": {"presenter": round(presenter_s), "aiVideo": round(video_s), "stills": round(still_s)},
        "counts": {"stills": int(math.ceil(stills)), "clipStartStills": int(math.ceil(start_stills)),
                   "splitStills": int(math.ceil(split_stills)), "pictures": int(math.ceil(pictures)),
                   "presenterInAction": int(math.ceil(in_action)), "aiClips": int(math.ceil(clips)),
                   "presenterAppearances": int(math.ceil(appearances)),
                   "presenterMinutes": round(presenter_s / 60.0, 1)},
        "models": {"presenter": [pres_model, pres_res], "aiVideo": list(video), "pictures": list(image),
                   "presenterPictures": list(pimage)},
        "makeMinutes": int(round(make)),
    }


def table(minutes: Iterable[float] = (10, 15, 20), tiers: Optional[Iterable[str]] = None,
          own_voice: bool = False) -> Dict[str, Any]:
    """Every tier's estimate at each length: {"tiers": {id: {"label", "byMinutes": {"10": {...}}}}, ...}."""
    lengths = [float(x) for x in minutes]
    names = list(tiers) if tiers else list(_tiers.all_tiers())
    out: Dict[str, Any] = {}
    for name in names:
        spec = _tiers.resolve(name)
        rows = {str(int(x) if x.is_integer() else x): estimate(x, spec, own_voice=own_voice) for x in lengths}
        first = rows[next(iter(rows))] if rows else None
        out[spec["id"]] = {"label": spec.get("label"), "byMinutes": rows,
                           "usdPerMinute": round(first["usd"] / max(first["minutes"], 1e-9), 3) if first else 0.0}
    return {"currency": "USD", "defaultTier": _tiers.DEFAULT_TIER, "tiers": out,
            "assumptions": {"presenterOverhead": OVER_PRESENTER, "aiVideoOverhead": OVER_VIDEO,
                            "secondsPerStill": SECONDS_PER_PICTURE, "clipOnScreenSeconds": CLIP_ON_SCREEN,
                            "presenterAppearanceSeconds": PRESENTER_APPEARANCE, "ownVoice": own_voice,
                            "note": "Estimates; the job records what each call really cost (meta.costs, "
                                    "meta.presenter.costs)."}}
