"""
Brand kits for the Smart Editor (2026-10-14): one design system per channel - palette, type, label pills,
number + unit style, map colours, easing and tempo - so every graphic of a video is "branded, not random".
The renderer's copy is remotion/src/components/smart/brandKits.ts (tests/test_smart_editor.py keeps them equal).

A spec carries "kit": "<id>" and uses tokens ("$primary", "$title", "$ease" ...) the renderer resolves.
Which kit a video gets: the job's "smart_kit", else the channel brand kit's "smart_kit", else by video style.
"""
from typing import Optional

KITS = {
    "royal": {"name": "Royal explainer",
              "colors": {"bg": "#1a1aa8", "bg2": "#0b0b5e", "primary": "#f2b630", "secondary": "#5b5bf0",
                         "region": "#4b4bdf", "text": "#ffffff", "number": "#ffffff", "muted": "#c9cbe8",
                         "pillBg": "#f2b630", "pillText": "#141414"},
              "fonts": {"title": "narrow", "number": "grotesk", "label": "narrow", "body": "inter"},
              "titleWeight": 800, "titleTracking": 0.0, "ease": "quintOut", "easeSoft": "inOut", "tempo": 1.0},
    "noir": {"name": "Documentary noir",
             "colors": {"bg": "#15171c", "bg2": "#060708", "primary": "#e8b64c", "secondary": "#8fa3b8",
                        "region": "#c9973a", "text": "#ffffff", "number": "#ffffff", "muted": "#b9bcc4",
                        "pillBg": "#e8b64c", "pillText": "#111111"},
             "fonts": {"title": "grotesk", "number": "grotesk", "label": "narrow", "body": "inter"},
             "titleWeight": 800, "titleTracking": -0.01, "ease": "expoOut", "easeSoft": "inOut", "tempo": 1.1},
    "bulletin": {"name": "News bulletin",
                 "colors": {"bg": "#1b1d22", "bg2": "#0c0d10", "primary": "#e5484d", "secondary": "#f5f5f5",
                            "region": "#e5484d", "text": "#ffffff", "number": "#ffffff", "muted": "#c3c6cc",
                            "pillBg": "#e5484d", "pillText": "#ffffff"},
                 "fonts": {"title": "kinetic", "number": "grotesk", "label": "narrow", "body": "inter"},
                 "titleWeight": 900, "titleTracking": -0.015, "ease": "expoOut", "easeSoft": "out", "tempo": 0.85},
    "atlas": {"name": "Atlas teal",
              "colors": {"bg": "#0d3b45", "bg2": "#06191e", "primary": "#f4d35e", "secondary": "#2ec4b6",
                         "region": "#2ec4b6", "text": "#ffffff", "number": "#ffffff", "muted": "#bfd8dc",
                         "pillBg": "#f4d35e", "pillText": "#10282d"},
              "fonts": {"title": "grotesk", "number": "mono", "label": "narrow", "body": "inter"},
              "titleWeight": 800, "titleTracking": 0.0, "ease": "quintOut", "easeSoft": "inOut", "tempo": 1.0},
}
DEFAULT = "noir"
_BY_STYLE = {"documentary": "noir", "news": "bulletin", "news_compilation": "bulletin", "explainer": "royal",
             "educational": "atlas", "science": "atlas"}


def choose(inp: Optional[dict] = None, brand: Optional[dict] = None, video_style: str = "") -> str:
    for src in (inp or {}, brand or {}):
        k = src.get("smart_kit") if isinstance(src, dict) else None
        if isinstance(k, str) and k in KITS:
            return k
    return _BY_STYLE.get(str(video_style or "").lower(), DEFAULT)


def get(kit_id: str) -> dict:
    return KITS.get(kit_id) or KITS[DEFAULT]
