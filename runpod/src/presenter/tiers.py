"""
The AI presenter style's tiers and the models they use (docs/ai-avatar-style-plan-2026-10-07.md).

A tier is configuration, not code: how much of the video's screen time is the
presenter talking, how much is AI video (an image-to-video clip that starts
from one of our stills), the rest being stills with free camera moves and
living-photo parallax - and which model makes each, in the order they are
tried. Everything is overridable without a deploy: the environment's
PRESENTER_TIERS (JSON, merged over these) and a job's own "presenter_config"
(merged over the tier it picked), so one job can A/B a model or a share.

Prices are what OpenRouter's catalogue (/api/v1/videos/models, read
2026-10-07) and the prototype's measured calls say; they size the budget
guard and the estimate. The money actually counted is always the provider's
own usage.cost for each call.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TIER = "budget"

# Every model the style can call, with what it accepts and what a second costs.
# kind: "avatar" (one picture + our audio -> a lip-synced talking clip),
# "i2v" (a start frame + a motion prompt -> a clip), "image" (prompt [+ references] -> a still).
MODELS: Dict[str, Dict[str, Any]] = {
    # The presenter: HeyGen Avatar IV through OpenRouter, $0.05 a second at 720p or 1080p.
    # Measured 2026-10-07 (prototype): 6.7-8.9 s clips in 67-83 s, $0.34-0.44, 25 fps, length = the audio's.
    "heygen/avatar-iv": {"kind": "avatar", "usd_per_second": {"720p": 0.05, "1080p": 0.05}},
    # Image-to-video b-roll. "durations": the clip lengths the model accepts (seconds).
    # "audio_flag": the request takes generate_audio (sent false: the narration is the only sound).
    "bytedance/seedance-1-5-pro": {"kind": "i2v", "usd_per_second": {"480p": 0.012, "720p": 0.026, "1080p": 0.059},
                                   "durations": list(range(4, 13)), "audio_flag": True},
    "google/veo-3.1-lite": {"kind": "i2v", "usd_per_second": {"720p": 0.03, "1080p": 0.05},
                            "durations": [4, 6, 8], "audio_flag": True},
    "google/veo-3.1-fast": {"kind": "i2v", "usd_per_second": {"720p": 0.08, "1080p": 0.10},
                            "durations": [4, 6, 8], "audio_flag": True},
    "minimax/hailuo-3-max": {"kind": "i2v", "usd_per_second": {"480p": 0.05, "768p": 0.08},
                             "durations": list(range(5, 16))},
    "minimax/hailuo-3": {"kind": "i2v", "usd_per_second": {"2K": 0.13}, "durations": list(range(5, 16)),
                         "audio_flag": True},
    "alibaba/wan-3.0": {"kind": "i2v", "usd_per_second": {"720p": 0.10, "1080p": 0.20},
                        "durations": list(range(2, 31)), "audio_flag": True},
    "kwaivgi/kling-v3.0-std": {"kind": "i2v", "usd_per_second": {"720p": 0.084}, "durations": list(range(3, 16)),
                               "audio_flag": True},
    # Stills. usd: per picture at that size (OpenRouter / Google price pages; Nano Banana 2.1 measured at
    # $0.053 for 2K on 2026-10-07).
    "google/gemini-nano-banana-2.1": {"kind": "image", "usd": {"1K": 0.034, "2K": 0.053}},
    "google/gemini-3.1-flash-image": {"kind": "image", "usd": {"1K": 0.067, "2K": 0.101}},
    "google/gemini-3-pro-image": {"kind": "image", "usd": {"1K": 0.134, "2K": 0.140}},
}

# The tiers. Shares are of the video's screen time. The default is the owner's six reference videos' own
# mix (docs/ai-avatar-reference-analysis-2026-10-07.md: ~14% presenter, ~15% AI video clips animated from
# that line's still, ~70% AI stills with a slow move, 0% stock): "budget", alias "reference". Standard and
# premium keep that edit and raise the share of moving shots, on better models.
#   presenter_share     the presenter talking on screen (opens at 0:00, then ~5 s every 15-40 s, heavier early)
#   ai_video_share      image-to-video clips (things that must move: pouring, steam, wind, hands at work)
#   split_share         presenter appearances drawn 50/50 with that line's picture (presenter left): ~1/3
#   presenter_broll     share of the b-roll showing the presenter doing the thing (2-30% in the references),
#                       always drawn from the kit's master portrait on Nano Banana Pro (the face stays theirs)
#   *_models            tried in order: [model, resolution or picture size]
# The presenter costs the same at 720p and 1080p ($0.05/s), so every tier asks for 1080p.
TIERS: Dict[str, Dict[str, Any]] = {
    "budget": {
        "label": "Reference (budget)",
        "presenter_share": 0.14,
        "ai_video_share": 0.15,
        "split_share": 0.33,
        "presenter_broll": 0.15,
        "presenter_model": ["heygen/avatar-iv", "1080p"],
        "video_models": [["bytedance/seedance-1-5-pro", "720p"], ["google/veo-3.1-lite", "720p"]],
        "image_models": [["google/gemini-nano-banana-2.1", "1K"], ["google/gemini-3.1-flash-image", "1K"]],
        "presenter_image_models": [["google/gemini-3-pro-image", "2K"]],
    },
    "standard": {
        "label": "Standard",
        "presenter_share": 0.15,
        "ai_video_share": 0.25,
        "split_share": 0.33,
        "presenter_broll": 0.20,
        "presenter_model": ["heygen/avatar-iv", "1080p"],
        # Seedance 1.5 Pro at 1080p: the prototype's best value ($0.29 for 5 s, sharp); MiniMax H3 Max looked
        # best and answered in 17 s but delivers 1344x768 (softer next to 1080p shots).
        "video_models": [["bytedance/seedance-1-5-pro", "1080p"], ["minimax/hailuo-3-max", "768p"],
                         ["google/veo-3.1-lite", "1080p"]],
        "image_models": [["google/gemini-nano-banana-2.1", "2K"], ["google/gemini-3.1-flash-image", "2K"]],
        "presenter_image_models": [["google/gemini-3-pro-image", "2K"]],
    },
    "premium": {
        "label": "Premium",
        "presenter_share": 0.18,
        "ai_video_share": 0.40,
        "split_share": 0.33,
        "presenter_broll": 0.25,
        "presenter_model": ["heygen/avatar-iv", "1080p"],
        "video_models": [["minimax/hailuo-3", "2K"], ["alibaba/wan-3.0", "1080p"], ["minimax/hailuo-3-max", "768p"]],
        "image_models": [["google/gemini-3-pro-image", "2K"], ["google/gemini-nano-banana-2.1", "2K"]],
        "presenter_image_models": [["google/gemini-3-pro-image", "2K"]],
    },
}
_ALIASES = {"reference": "budget", "ref": "budget", "low": "budget", "cheap": "budget", "basic": "budget",
            "default": "budget", "std": "standard", "normal": "standard", "pro": "premium", "high": "premium",
            "best": "premium"}

# The text and vision models of the style (OpenRouter ids). The planner writes every still's and
# clip's prompt (one call per ~50 lines); the checker looks at every generated clip and still.
DIRECTOR_MODEL = os.getenv("PRESENTER_DIRECTOR_MODEL", "openai/gpt-5.2").strip()
DIRECTOR_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "PRESENTER_DIRECTOR_FALLBACK_MODELS", "google/gemini-2.5-flash").split(",") if m.strip()]
CHECK_MODEL = os.getenv("PRESENTER_CHECK_MODEL", "google/gemini-2.5-flash").strip()
CHECK_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "PRESENTER_CHECK_FALLBACK_MODELS", "openai/gpt-5-mini").split(",") if m.strip()]


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _env_tiers() -> Dict[str, dict]:
    raw = os.getenv("PRESENTER_TIERS", "").strip()
    if not raw:
        return {}
    try:
        got = json.loads(raw)
    except ValueError:
        print("[presenter] PRESENTER_TIERS is not JSON; using the built-in tiers", flush=True)
        return {}
    return got if isinstance(got, dict) else {}


def all_tiers() -> Dict[str, Dict[str, Any]]:
    """The tiers in force: the built-in ones with the environment's PRESENTER_TIERS merged over them."""
    out = copy.deepcopy(TIERS)
    for name, spec in _env_tiers().items():
        if isinstance(spec, dict):
            out[name] = _deep_merge(out.get(name, out[DEFAULT_TIER]), spec)
    return out


def resolve_name(name: Any) -> str:
    key = str(name or "").strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in all_tiers() else DEFAULT_TIER


def resolve(name: Any = None, overrides: Optional[dict] = None) -> Dict[str, Any]:
    """The tier a job asked for (an unknown name: the default), its own presenter_config merged over it."""
    key = resolve_name(name)
    spec = all_tiers()[key]
    if isinstance(overrides, dict) and overrides:
        spec = _deep_merge(spec, {k: v for k, v in overrides.items() if k != "id"})
    spec = dict(spec, id=key)
    spec["presenter_share"] = max(0.0, min(0.9, float(spec.get("presenter_share", 0.25))))
    spec["ai_video_share"] = max(0.0, min(0.9, float(spec.get("ai_video_share", 0.0))))
    if spec["presenter_share"] + spec["ai_video_share"] > 0.95:
        spec["ai_video_share"] = round(0.95 - spec["presenter_share"], 3)
    spec["presenter_broll"] = max(0.0, min(0.8, float(spec.get("presenter_broll", 0.0))))
    spec["split_share"] = max(0.0, min(0.8, float(spec.get("split_share", 0.0))))
    return spec


def model_info(model: str) -> Dict[str, Any]:
    return MODELS.get(str(model or ""), {})


def usd_per_second(model: str, resolution: str) -> float:
    """What a second of this model's clip costs at this resolution (its dearest known rate if unknown)."""
    rates = model_info(model).get("usd_per_second") or {}
    if resolution in rates:
        return float(rates[resolution])
    return float(max(rates.values())) if rates else 0.15


def image_usd(model: str, size: str) -> float:
    prices = model_info(model).get("usd") or {}
    if size in prices:
        return float(prices[size])
    return float(max(prices.values())) if prices else 0.14


def clip_seconds_for(model: str, wanted: float) -> int:
    """The shortest clip length the model accepts that covers `wanted` seconds (its longest if none does)."""
    durations = sorted(int(d) for d in (model_info(model).get("durations") or [5, 6, 8, 10]))
    for d in durations:
        if d + 1e-6 >= wanted:
            return d
    return durations[-1]


def pairs(spec: Dict[str, Any], key: str) -> List[Tuple[str, str]]:
    """A tier's [model, resolution] list as tuples (a bare model id gets its first known resolution)."""
    out: List[Tuple[str, str]] = []
    for item in spec.get(key) or []:
        if isinstance(item, (list, tuple)) and item:
            model = str(item[0])
            res = str(item[1]) if len(item) > 1 else ""
        else:
            model, res = str(item), ""
        if not res:
            info = model_info(model)
            res = next(iter(info.get("usd_per_second") or info.get("usd") or {"": 0}), "")
        out.append((model, res))
    return out


def summary(spec: Dict[str, Any]) -> Dict[str, Any]:
    """What a tier is, for the plan's meta and the app."""
    return {"id": spec.get("id"), "label": spec.get("label"),
            "presenterShare": spec.get("presenter_share"), "aiVideoShare": spec.get("ai_video_share"),
            "pictureShare": round(max(0.0, 1.0 - spec.get("presenter_share", 0) - spec.get("ai_video_share", 0)), 3),
            "presenterBroll": spec.get("presenter_broll"), "splitShare": spec.get("split_share"),
            "presenterModel": list(spec.get("presenter_model") or []),
            "videoModels": [list(p) for p in pairs(spec, "video_models")],
            "imageModels": [list(p) for p in pairs(spec, "image_models")]}
