"""
AI visuals: a whole video made only of AI clips and AI pictures (the owner, 2026-10-28), for any niche.

Job input (docs/ai-visuals-contract.md in the app repo):

    "visual_source": "ai",
    "ai_visuals": {"clip_pct": 70, "provider": "avatarity", "video_model": "veo-3.1-lite",
                   "image_model": "nano-banana-pro", "resolution": "720p", "look": "photoreal",
                   "style_notes": "", "max_video_units": 120, "max_images": 200},
    "ai_prompts": {"s012": {"still": "...", "motion": "..."}}      (optional: the user's / editor's own prompts)

How it runs (no new pipeline - the footage pipeline with its search switched off):
  prepare_input   the job becomes a plan with no footage search (allow_youtube false), scenes paced for ~8 s Veo
                  clips (3.2-7 s), and an AI fill block in "full" mode: every line gets an AI picture (Nano Banana
                  Pro, photoreal by default) and clip_pct of the screen time is animated from those pictures into
                  Veo clips (image-to-video: the picture is the clip's start frame, so what was checked is what
                  moves). The prompt model writes the visual bible and each line's picture + motion (src/aifill.py
                  describe), the user's own prompts win, the look check turns down text, frames, warped hands or
                  faces and slop, with one retry.
  do_plan         (handler) skips the subject pools, the per-line search, the rescue, the runner-ups, the ladder and
                  stills-to-clips when ai_only; AI fill's full pass fills the timeline.
  annotate        meta.aiVisuals: the mode, models, look, bible, counts and the usage line (Avatarity units used and
                  left, OpenRouter $), with the AI disclosure first in meta.warnings.
  regenerate      the editor's "Regenerate picture / clip" for one scene (handler.do_resource modes ai_image /
                  ai_clip) with the edited prompt.

Never: a real, identifiable person drawn photorealistically (AI fill's person rule: the line's setting instead),
text / logos / dates / frames in a picture (the prompt rule + the look check), a fake news chyron.
"""
from __future__ import annotations

import copy
import os
import time
from typing import Any, Dict, Optional

from . import config

DISCLOSURE = ("This video is made of AI-generated clips and pictures (no real footage): tick \"Altered or synthetic "
              "content\" in YouTube Studio when uploading.")
LOOKS = ("photoreal", "cinematic", "archival", "3d", "anime")
# Pacing for ~8 s clips: a line is one shot, 3.2-7 s, cut on the narration's sentences.
PACING = {"MIN_SCENE_SECONDS": 3.2, "TARGET_SCENE_SECONDS": 5.8, "MAX_SCENE_SECONDS": 7.0, "SHOT_MAX_SECONDS": 7.0}


def wanted(inp: Optional[dict]) -> bool:
    return str((inp or {}).get("visual_source") or "").strip().lower() == "ai"


def settings(inp: Optional[dict]) -> Dict[str, Any]:
    """The job's ai_visuals block, normalised."""
    from . import aifill
    raw = (inp or {}).get("ai_visuals") if isinstance((inp or {}).get("ai_visuals"), dict) else {}
    try:
        pct = float(raw.get("clip_pct", 70))
    except (TypeError, ValueError):
        pct = 70.0
    look = str(raw.get("look") or "photoreal").strip().lower()
    out = {"clip_pct": max(0.0, min(100.0, pct)), "look": look if look in LOOKS else "photoreal",
           "style_notes": " ".join(str(raw.get("style_notes") or "").split())[:400]}
    out.update(aifill.provider_fields(raw))
    try:
        out["max_images"] = max(1, min(400, int(raw.get("max_images") or 0))) if raw.get("max_images") else 0
    except (TypeError, ValueError):
        out["max_images"] = 0
    return out


def prepare_input(inp: dict) -> Dict[str, Any]:
    """The job as a plan with no footage search and an AI fill block for every line (idempotent)."""
    s = settings(inp)
    inp["allow_youtube"] = False
    inp["youtube_only"] = False
    inp["allow_stock"] = False
    cfg = dict(inp.get("config") or {}) if isinstance(inp.get("config"), dict) else {}
    for k, v in PACING.items():
        cfg.setdefault(k, v)
    cfg.setdefault("AI_FILL_SECONDS", config.AI_VISUALS_SECONDS)
    cfg.setdefault("AI_FILL_PARALLEL", 4)
    cfg.setdefault("AI_FILL_CLIP_PARALLEL", 4)
    cfg.setdefault("AI_FILL_LABEL", False)          # the whole video is AI: one disclosure, no per-scene tag
    cfg.setdefault("AI_FILL_NEWS_EVENTS", True)     # every line needs a picture (a generic one, never a fake chyron)
    cfg.setdefault("IMAGE_MAX_PER_VIDEO", 0)        # the old generated-image path stays off: AI fill makes them all
    inp["config"] = cfg
    # Every line: pictures for all, clips for clip_pct of the time. Caps: the plan allowance's (units, images);
    # the dollar budget covers only OpenRouter (prompts, checks, fallbacks).
    minutes = max(1.0, float(inp.get("_minutes") or 12.0))
    lines = int(minutes * 60 / PACING["TARGET_SCENE_SECONDS"]) + 10
    inp["ai_fill"] = {
        "enabled": True, "full": True, "clip_pct": s["clip_pct"], "look": s["look"],
        "style_notes": s["style_notes"], "provider": s["provider"], "resolution": s["resolution"],
        "image_model": s.get("image_model") or "", "video_model": s.get("video_model") or "",
        "max_images": s["max_images"] or 400, "max_clips": 300,
        "max_video_units": s["max_video_units"], "max_av_images": s["max_av_images"],
        "budget_usd": round(min(float(config.AI_FILL_MAX_BUDGET), 0.6 + 0.01 * lines), 2),
        "quality": "standard",
        **({"prompts": inp["ai_prompts"]} if isinstance(inp.get("ai_prompts"), dict) else {}),
        **({"or_image_model": s["or_image_model"]} if s.get("or_image_model") else {}),
        **({"or_video_model": s["or_video_model"]} if s.get("or_video_model") else {}),
    }
    if s["provider"] == "openrouter":
        inp["ai_fill"]["image_models"] = [[s.get("or_image_model") or "google/gemini-nano-banana-2.1", "2K"]]
        inp["ai_fill"]["video_models"] = [[s.get("or_video_model") or "google/veo-3.1-lite", "720p"]]
    return s


def annotate(doc: dict, rep: Dict[str, Any], block: Dict[str, Any]) -> None:
    """meta.aiVisuals (the report the app shows) and the disclosure first in meta.warnings."""
    meta = doc.setdefault("meta", {})
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    from . import aifill
    clips = stills = empty = 0
    clip_frames = total = 0
    for sc in scenes:
        n = int(sc.get("durationInFrames") or 0)
        total += n
        if aifill.is_ai_scene(sc):
            if (sc.get("media") or {}).get("type") == "video":
                clips += 1
                clip_frames += n
            else:
                stills += 1
        else:
            empty += 1
    from . import costs
    try:
        summ = costs.summary(0.0) if hasattr(costs, "summary") else {}
    except Exception:  # noqa: BLE001
        summ = {}
    llm = 0.0
    for k in ("llm.usd", "vision.usd"):
        try:
            llm += float(((summ.get("items") or {}).get(k) if isinstance(summ.get("items"), dict) else 0) or 0)
        except (TypeError, ValueError):
            pass
    usage = dict(rep.get("usage") or {})
    usage.setdefault("aiTextUsd", round(llm, 4) if llm else None)
    usage.setdefault("voiceUsd", None)
    usage.setdefault("renderUsd", None)
    meta["aiVisuals"] = {
        "mode": "ai", "clipPct": block.get("clip_pct"),
        "actualClipPct": round(100.0 * clip_frames / total, 1) if total else 0.0,
        "provider": block.get("provider"),
        "models": {"video": block.get("video_model") or block.get("or_video_model"),
                   "image": block.get("image_model") or block.get("or_image_model")},
        "resolution": block.get("resolution"), "look": block.get("look"),
        "styleNotes": block.get("style_notes") or "",
        "bible": (rep.get("bible") or {}),
        "scenes": {"clips": clips, "stills": stills, "empty": empty, "seconds": round(total / fps, 1)},
        "usage": usage, "fallbacks": list(rep.get("fallbacks") or []),
        "disclosure": DISCLOSURE, "fill": {k: rep.get(k) for k in ("images", "clips", "failed", "spentUsd",
                                                                  "skipped", "stopped") if k in rep},
    }
    meta["aiFill"] = rep
    warnings = meta.setdefault("warnings", [])
    if isinstance(warnings, list) and DISCLOSURE not in warnings:
        warnings.insert(0, DISCLOSURE)


def regenerate(doc: dict, idx: int, kind: str, prompt: str, inp: dict, work: str, report=None) -> Dict[str, Any]:
    """
    The editor's Regenerate for one AI scene (handler.do_resource modes "ai_image" / "ai_clip"): a new picture -
    and for a clip, its animation - from `prompt` (the edited description; empty = the scene's own aiPrompt).
    Timing is untouched. Returns {"ok", "usage", "error"?}; the scene in `doc` is changed in place.
    """
    from . import aifill, gapfill
    scenes = doc.get("scenes") or []
    sc = scenes[idx]
    sem = sc.setdefault("semanticMetadata", {})
    text = " ".join(str(prompt or sem.get("aiPrompt") or (sem.get("aiFill") or {}).get("prompt") or
                        sc.get("text") or "").split())[:900]
    if not text:
        raise ValueError("this scene has no prompt to make a picture from - write one first")
    sem["aiPrompt"], sem["aiPromptEdited"] = text, bool(prompt)
    if kind == "ai_clip" and inp.get("ai_motion"):
        sem["aiMotion"], sem["aiMotionEdited"] = " ".join(str(inp["ai_motion"]).split())[:400], True
    # One scene, made by AI fill's own path: the scene emptied, a block for exactly one picture (and clip).
    s = settings(inp) if isinstance(inp.get("ai_visuals"), dict) else aifill.provider_fields(
        (doc.get("meta") or {}).get("aiVisuals") or {})
    block = {"enabled": True, "full": True, "clip_pct": 100 if kind == "ai_clip" else 0,
             "look": s.get("look") or ((doc.get("meta") or {}).get("aiVisuals") or {}).get("look") or "photoreal",
             "style_notes": s.get("style_notes") or "", "provider": s.get("provider"),
             "resolution": s.get("resolution"), "image_model": s.get("image_model") or "",
             "video_model": s.get("video_model") or "", "max_images": 1, "max_clips": 1 if kind == "ai_clip" else 0,
             "max_video_units": 2, "max_av_images": 2, "budget_usd": 0.3, "quality": "standard",
             "prompts": {str(sc.get("id") or idx): {"still": text, **({"motion": sem["aiMotion"]}
                                                                     if kind == "ai_clip" and sem.get("aiMotion")
                                                                     else {})}}}
    old = copy.deepcopy(sc.get("media"))
    sc["media"] = None
    sc.pop("animation", None)
    job = {"ai_fill": block, "video_style": inp.get("video_style") or ""}
    aifill.start(job, work=work, project_id=str(inp.get("project_id") or ""), job_id=str(inp.get("_job_id") or ""))
    from . import avatarity
    avatarity.reset_ledger()
    t0 = time.time()
    try:
        got = aifill.fill_doc(doc, work=work, only=[sc], label="regenerate", why="the editor asked for a new one")
    finally:
        if gapfill._empty(sc):
            sc["media"] = old                   # nothing passed: the scene keeps what it had
    out = {"ok": bool(got.get("images")), "made": got, "usage": aifill.usage(), "seconds": round(time.time() - t0, 1)}
    if not out["ok"]:
        out["error"] = "No new picture passed the checks - try again or change the prompt."
    aifill.reset()
    return out
