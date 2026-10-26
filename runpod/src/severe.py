"""
The severe weather update style's finishing pass (video_style "severe_weather", src/styles.py).

Measured on Severe Weather USA, 8 recent uploads (2026-10-26; docs/style-refs/severe-weather-usa-STYLE.md):

  * nothing of the channel's own is drawn on the picture but its name, a faint centred watermark in a condensed
    bold face (~28% white, letters ~5.6% of the frame's height, the line ~35% of its width) on every frame;
  * the forecast part of the script ("Monday brings real relief ... Farmington 64, Albuquerque 68 ...") plays
    over a screen-recorded forecast model map - one block of 30-180 s, usually in the last fifth, the model's
    time chip stepping through the days the voice names;
  * no dates, figures, name cards, marks, captions or sound effects.

finish(doc, inp) runs after the plan (handler.do_plan): it keeps only the forecast maps and the job's own
on-screen source tags, lays the forecast block over the forecast lines with our own forecast-model views
(remotion components/lib/LibWeatherMaps.tsx: wx-rain-bands, wx-wind-flow, wx-temp - no third-party map or
branding), and stamps the channel's name (doc.channelMark, components/brand/ChannelMark.tsx) when the job names
one (inp.channel_watermark). Every figure on the temperature view is one the narration says on that line; a day
chip shows only a day the narration names (the owner's rule: never a weekday the voice-over did not say).
No network but the gazetteer the planner already uses; never raises.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

STYLE = "severe_weather"

# The watermark as measured (components/brand/ChannelMark.tsx draws it).
MARK_OPACITY = 0.28
MARK_SIZE = 0.075

# What a forecast line says. A line counts when it names a forecast quantity, or a day with a figure.
_DAY = re.compile(r"\b(today|tonight|tomorrow|this (?:afternoon|evening|morning|weekend)|"
                  r"(?:mon|tues|wednes|thurs|fri|satur|sun)day(?: night| morning| afternoon)?|weekend)\b", re.I)
_FORECAST = re.compile(r"\b(forecast|chances?|percent|precipitation|highs?|lows?|temperatures?|degrees|"
                       r"day by day|what happens next|the (?:week|days) ahead|watch(?:es)?|rain rates?|"
                       r"warm(?:s|ing|er)?|cool(?:s|ing|er)?|dry (?:day|air|skies)|showers?|rain(?:fall)? returns?|"
                       r"snow(?:fall)?|wind chills?|gusts?|mph|inch(?:es)?|outlook|models?)\b|\d+\s*%|\d+\s*°",
                       re.I)
_NUMBER = re.compile(r"\d")
_OUTRO = re.compile(r"\b(takeaways?|before you go|subscribe|hit (?:that )?like|stay safe|see you in the next|"
                    r"thoughts are with)\b", re.I)
_TEMP = re.compile(r"\b(highs?|lows?|temperatures?|degrees|warm(?:s|ing|er)?|cool(?:s|ing|er)?|heat|"
                   r"cold|freez\w*|°)", re.I)
_WIND = re.compile(r"\b(winds?|gusts?|gusting|mph)\b", re.I)
_WET = re.compile(r"\b(rain\w*|showers?|storms?|thunderstorms?|precipitation|snow\w*|flood\w*|chances?|"
                  r"percent|wet)\b|\d+\s*%", re.I)
# "Albuquerque reaches 68", "Santa Fe 64", "Farmington at 80% Friday": a place, then its figure.
_PLACE_FIGURE = re.compile(r"\b((?:[A-Z][a-z]+\.?)(?:\s+[A-Z][a-z]+){0,2})\s+(?:reaches\s+|at\s+|near\s+|hits\s+|"
                           r"climbs to\s+|tops out (?:near|at)\s+)?(\d{1,3})(?!\s*(?:%|percent|mph|inch|in\b|ft|feet))"
                           r"\s*(?:°|degrees)?", re.U)
_NOT_PLACES = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Today", "Tonight",
               "October", "November", "December", "January", "February", "March", "April", "May", "June", "July",
               "August", "September", "Highs", "High", "Lows", "Low", "The", "By", "And", "On", "In", "At", "With",
               "Precipitation", "Temperatures", "Interstate", "Highway", "US", "I", "NWS", "Route"}

BLOCK_MIN_SECONDS = 20.0          # a run of forecast lines shorter than this keeps its footage
BLOCK_FROM_SHARE = 0.35           # the forecast block sits in the back two-thirds (measured: the last fifth)
SEGMENT_MIN_SECONDS = 4.0         # one map view at least this long; a shorter one joins the one before
VIEWS = {"rain": "LIB_WX_RAIN_BANDS", "wind": "LIB_WX_WIND_FLOW", "temp": "LIB_WX_TEMP"}


def is_style(inp: Optional[dict] = None, doc: Optional[dict] = None) -> bool:
    from . import styles
    if inp is not None and styles.resolve(inp.get("video_style")) == STYLE:
        return True
    return bool(doc) and str(((doc or {}).get("meta") or {}).get("videoStyle") or "") == STYLE


# --------------------------------------------------------------------------- #
# The watermark
# --------------------------------------------------------------------------- #

def channel_mark(inp: dict) -> Optional[dict]:
    """The doc's channelMark from the job's channel_watermark (a string, or {text, opacity}); None = no stamp."""
    raw = inp.get("channel_watermark")
    if isinstance(raw, dict):
        text, opacity = str(raw.get("text") or ""), raw.get("opacity")
    else:
        text, opacity = str(raw or ""), None
    text = " ".join(text.split())[:40]
    if not text or raw is False:
        return None
    try:
        op = float(opacity) if opacity is not None else MARK_OPACITY
    except (TypeError, ValueError):
        op = MARK_OPACITY
    return {"text": text, "opacity": round(max(0.1, min(0.6, op)), 3), "size": MARK_SIZE, "x": 0.5, "y": 0.5,
            "font": "Oswald"}


# --------------------------------------------------------------------------- #
# The forecast block
# --------------------------------------------------------------------------- #

def _forecast_line(text: str) -> bool:
    """A line of the forecast: a forecast quantity or word, or a day ("Monday brings real relief")."""
    t = text or ""
    return bool(_FORECAST.search(t)) or bool(_DAY.search(t))


def find_blocks(scenes: List[dict], fps: int) -> List[Tuple[int, int]]:
    """
    (first, last) scene indexes of each forecast block: a run of forecast lines in the back two-thirds, at most
    one plain line between two forecast lines, ending before the sign-off; runs under BLOCK_MIN_SECONDS dropped.
    """
    n = len(scenes)
    if not n:
        return []
    total = max(1, scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"])
    outro = next((i for i in range(n) if scenes[i]["startFrame"] > total * 0.6
                  and _OUTRO.search(str(scenes[i].get("text") or ""))), n)
    hits = [i < outro and scenes[i]["startFrame"] >= total * BLOCK_FROM_SHARE
            and _forecast_line(str(scenes[i].get("text") or "")) for i in range(n)]
    blocks, i = [], 0
    while i < n:
        if not hits[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and (hits[j + 1] or (j + 2 < n and hits[j + 2] and j + 2 < outro)):
            j += 1 if hits[j + 1] else 2
        a, b = scenes[i], scenes[j]
        if (b["startFrame"] + b["durationInFrames"] - a["startFrame"]) / float(fps) >= BLOCK_MIN_SECONDS:
            blocks.append((i, j))
        i = j + 1
    return blocks


def view_of(text: str) -> str:
    """Which model view a forecast line gets: temperature, wind or rain (the default)."""
    t = text or ""
    if _TEMP.search(t) and not _WET.search(t):
        return "temp"
    if _WIND.search(t) and not _WET.search(t):
        return "wind"
    if _TEMP.search(t) and spoken_figures(t) and not re.search(r"\d+\s*%|percent", t):
        return "temp"
    return "rain"


def day_of(text: str) -> str:
    """The day a line names, as the chip shows it ("MONDAY", "TONIGHT"), or ""."""
    m = _DAY.search(text or "")
    return m.group(1).upper() if m else ""


def spoken_figures(text: str) -> List[Tuple[str, int]]:
    """(place, °F) pairs the line says: "Albuquerque reaches 68, Santa Fe 64" -> [("Albuquerque", 68), ...]."""
    out, seen = [], set()
    for m in _PLACE_FIGURE.finditer(text or ""):
        name = m.group(1).strip().rstrip(".")
        words = [w for w in name.split() if w not in _NOT_PLACES]
        if not words:
            continue
        name = " ".join(words)
        v = int(m.group(2))
        if not -40 <= v <= 125 or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append((name, v))
    return out


def _segments(scenes: List[dict], first: int, last: int, fps: int) -> List[dict]:
    """The block cut into map views: a new view where the line names a new day or asks for another quantity."""
    segs: List[dict] = []
    chip = ""
    for k in range(first, last + 1):
        sc = scenes[k]
        text = str(sc.get("text") or "")
        day = day_of(text)
        view = view_of(text) if _forecast_line(text) else (segs[-1]["view"] if segs else "rain")
        if day:
            chip = day
        if segs and segs[-1]["view"] == view and (not day or day == segs[-1]["chip"]):
            seg = segs[-1]
            seg["end"] = sc["startFrame"] + sc["durationInFrames"]
            seg["text"] += " " + text
        else:
            segs.append({"start": sc["startFrame"], "end": sc["startFrame"] + sc["durationInFrames"],
                         "view": view, "chip": chip, "text": text})
    merged: List[dict] = []
    for seg in segs:
        if merged and (seg["end"] - seg["start"]) / float(fps) < SEGMENT_MIN_SECONDS:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] += " " + seg["text"]
            continue
        merged.append(seg)
    if len(merged) > 1 and (merged[0]["end"] - merged[0]["start"]) / float(fps) < SEGMENT_MIN_SECONDS:
        merged[1]["start"] = merged[0]["start"]
        merged[1]["text"] = merged[0]["text"] + " " + merged[1]["text"]
        merged.pop(0)
    return merged


def _places(doc: dict, block_text: str, brief: Optional[dict]) -> List[dict]:
    """The block's map pins: the places its lines name with a figure, else the story's places, gazetteer-checked."""
    from . import geocode
    names: List[str] = []
    for name, _ in spoken_figures(block_text):
        if name not in names:
            names.append(name)
    for p in (brief or {}).get("places") or []:
        p = str(p or "").strip()
        if p and p not in names:
            names.append(p)
    if not names:
        return []
    try:
        return geocode.resolve_all(names[:6], text=block_text, brief=brief)
    except Exception as e:  # noqa: BLE001 - a map without pins centres on the region; never fails the video
        print(f"[severe] forecast map places not found: {type(e).__name__}", flush=True)
        return []


def forecast_block(doc: dict, brief: Optional[dict] = None) -> dict:
    """Lay the forecast-model views over the forecast lines. Returns {blocks, views, seconds}."""
    from . import templates
    fps = int(doc.get("fps") or 30)
    scenes = sorted([s for s in doc.get("scenes") or [] if isinstance(s, dict)], key=lambda s: s["startFrame"])
    total = int(doc.get("durationInFrames") or 0)
    report = {"blocks": 0, "views": 0, "seconds": 0.0}
    for first, last in find_blocks(scenes, fps):
        segs = _segments(scenes, first, last, fps)
        text = " ".join(str(scenes[k].get("text") or "") for k in range(first, last + 1))
        locs = _places(doc, text, brief)
        start, end = segs[0]["start"], min(total, segs[-1]["end"])
        # The block owns its stretch: nothing else drawn over the map.
        doc["overlays"] = [ov for ov in doc.get("overlays") or []
                           if ov["startFrame"] + ov["durationInFrames"] <= start or ov["startFrame"] >= end]
        for seg in segs:
            template = VIEWS[seg["view"]]
            base = templates.resolve(template, props={"text": "", "label": seg["chip"]})
            if not base:
                continue
            figures = dict((n.lower(), v) for n, v in spoken_figures(seg["text"]))
            items = [{"label": l["label"].split(",")[0], "value": figures[l["label"].split(",")[0].lower()]}
                     for l in locs if l["label"].split(",")[0].lower() in figures] if seg["view"] == "temp" else []
            ov = dict(base)
            ov.update({"startFrame": int(seg["start"]), "durationInFrames": int(max(1, min(total, seg["end"]) - seg["start"])),
                       "text": "", "label": seg["chip"], "locations": locs[:6], "plain": True,
                       "sfx": {"name": "none", "volume": 0.0}, "severeForecast": True})
            if items:
                ov["items"] = items
            doc["overlays"].append(ov)
            report["views"] += 1
        report["blocks"] += 1
        report["seconds"] += round((end - start) / float(fps), 1)
    doc["overlays"] = sorted(doc.get("overlays") or [], key=lambda o: o["startFrame"])
    return report


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #

def _kept(ov: dict, inp: dict) -> bool:
    """The only graphics the style shows: the forecast maps, and the source tags the job asked for."""
    tid = str(ov.get("template") or ov.get("type") or "")
    if tid.startswith("LIB_WX_") or str(ov.get("variant") or "").startswith("wx-"):
        return True
    return bool(inp.get("on_screen_sources")) and ("source" in tid.lower())


def finish(doc: dict, inp: dict, brief: Optional[dict] = None) -> Dict[str, Any]:
    """The style's finishing pass over a planned doc (in place). Returns meta.severeWeather."""
    report: Dict[str, Any] = {}
    try:
        before = len(doc.get("overlays") or [])
        doc["overlays"] = [ov for ov in doc.get("overlays") or [] if isinstance(ov, dict) and _kept(ov, inp)]
        report["graphicsDropped"] = before - len(doc["overlays"])
        report["forecast"] = forecast_block(doc, brief)
        mark = channel_mark(inp)
        if mark:
            doc["channelMark"] = mark
        else:
            doc.pop("channelMark", None)
        report["watermark"] = bool(mark)
        # No sound effects in this style (the reference has none): looks' own sounds off too.
        doc["sfx"] = []
        doc["sfxEnabled"] = False
    except Exception as e:  # noqa: BLE001 - the plan stands without the finishing pass
        report["error"] = f"{type(e).__name__}: {e}"[:200]
        print(f"[severe] finishing pass skipped: {report['error']}", flush=True)
    return report
