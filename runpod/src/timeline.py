"""
Build the Remotion props document.

This is the contract between the worker and the renderer, and between the
backend and the ThumbGenius UI: the frontend timeline editor reads and writes
this same shape, so a user edit is just a mutated document re-sent to render.
"""
from typing import List, Dict, Any, Optional
import random

from . import config
from .transcribe import Segment
from .media import MediaAsset

# Alternating Ken Burns keeps still images alive. Videos mostly play straight,
# matching the reference renders where motion comes from the footage itself.
_IMAGE_MOTIONS = ["zoom-in", "zoom-out", "pan-left", "pan-right"]


def _sec_to_frames(seconds: float, fps: int) -> int:
    return max(1, int(round(seconds * fps)))


def build(
    segments: List[Segment],
    assets: List[Optional[MediaAsset]],
    audio_url: str,
    audio_duration: float,
    *,
    fps: int = None,
    width: int = None,
    height: int = None,
    bgm_url: str = "",
    bgm_volume: float = 0.12,
    captions: bool = True,
    brand: Dict[str, Any] = None,
    title_overlay: str = "",
    seed: int = 7,
) -> Dict[str, Any]:
    fps = fps or config.DEFAULT_FPS
    width = width or config.DEFAULT_WIDTH
    height = height or config.DEFAULT_HEIGHT
    brand = brand or {}
    rng = random.Random(seed)

    scenes: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments):
        asset = assets[i] if i < len(assets) else None
        start_f = _sec_to_frames(seg.start, fps)
        dur_f = _sec_to_frames(max(seg.duration, 0.4), fps)

        if asset is None:
            media = {"type": "color", "url": "", "source": "none"}
            motion = "none"
        else:
            media = {
                "type": asset.kind,
                "url": asset.local_path or asset.url,
                "source": asset.source,
                "attribution": asset.attribution,
                "license": asset.license,
            }
            motion = rng.choice(_IMAGE_MOTIONS) if asset.kind == "image" else "none"

        scenes.append({
            "id": f"s{i:04d}",
            "startFrame": start_f,
            "durationInFrames": dur_f,
            "text": seg.text,
            "media": media,
            "motion": motion,
            "transition": "fade" if i > 0 else "none",
            "words": [
                {"text": w.text, "start": w.start, "end": w.end} for w in seg.words
            ] if captions else [],
        })

    overlays: List[Dict[str, Any]] = []
    if title_overlay and scenes:
        overlays.append({
            "type": "title",
            "variant": "multiFont",
            "text": title_overlay,
            "startFrame": _sec_to_frames(1.0, fps),
            "durationInFrames": _sec_to_frames(3.5, fps),
        })

    total_frames = _sec_to_frames(audio_duration, fps)

    return {
        "fps": fps,
        "width": width,
        "height": height,
        "durationInFrames": total_frames,
        "audio": {"url": audio_url, "volume": 1.0},
        "bgm": {"url": bgm_url, "volume": bgm_volume} if bgm_url else None,
        "captions": {
            "enabled": bool(captions),
            "position": brand.get("captionPosition", "bottom"),
            "accent": brand.get("accent", "#FFD400"),
            "fontFamily": brand.get("fontFamily", "Inter"),
        },
        "scenes": scenes,
        "overlays": overlays,
        "meta": {
            "sceneCount": len(scenes),
            "cutsPerMinute": round(len(scenes) / max(audio_duration / 60, 0.01), 1),
            "sources": sorted({s["media"].get("source", "none") for s in scenes}),
        },
    }
