"""
Official weather imagery for current weather stories: NOAA GOES satellite
loops (public domain), the way news compilation channels cut to the live
satellite view while the narration explains where the storm is.

NOAA STAR publishes each regional sector as a rolling ~4-hour GEOCOLOR loop
(600x600 MP4, refreshed every few minutes). It only shows the weather NOW,
so it is used for stories about current events only - a loop of today's
clouds would be wrong for a flood from last spring.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from typing import Optional

import requests

from . import config

_BASE = "https://cdn.star.nesdis.noaa.gov/{sat}/ABI/SECTOR/{sector}/GEOCOLOR/"

# US states -> (satellite, sector). GOES-19 (East) covers the east and the
# middle of the country, GOES-18 (West) the Pacific states.
_SECTOR = {}
for states, where in (
        ("maine new-hampshire vermont massachusetts rhode-island connecticut new-york new-jersey pennsylvania "
         "delaware maryland", ("GOES19", "ne")),
        ("virginia west-virginia north-carolina south-carolina georgia florida alabama tennessee kentucky",
         ("GOES19", "se")),
        ("mississippi louisiana arkansas", ("GOES19", "smv")),
        ("minnesota iowa wisconsin missouri illinois", ("GOES19", "umv")),
        ("michigan ohio indiana", ("GOES19", "cgl")),
        ("texas oklahoma kansas", ("GOES19", "sp")),
        ("colorado new-mexico arizona utah", ("GOES19", "sr")),
        ("montana wyoming idaho north-dakota south-dakota nebraska", ("GOES19", "nr")),
        ("washington oregon", ("GOES18", "pnw")),
        ("california nevada", ("GOES18", "psw")),
        ("hawaii", ("GOES18", "hi")),
        ("alaska", ("GOES18", "ak"))):
    for s in states.split():
        _SECTOR[s.replace("-", " ")] = where
_ABBR = dict(zip(
    "ME NH VT MA RI CT NY NJ PA DE MD VA WV NC SC GA FL AL TN KY MS LA AR MN IA WI MO IL MI OH IN TX OK KS "
    "CO NM AZ UT MT WY ID ND SD NE WA OR CA NV HI AK".split(),
    ["maine", "new hampshire", "vermont", "massachusetts", "rhode island", "connecticut", "new york",
     "new jersey", "pennsylvania", "delaware", "maryland", "virginia", "west virginia", "north carolina",
     "south carolina", "georgia", "florida", "alabama", "tennessee", "kentucky", "mississippi", "louisiana",
     "arkansas", "minnesota", "iowa", "wisconsin", "missouri", "illinois", "michigan", "ohio", "indiana",
     "texas", "oklahoma", "kansas", "colorado", "new mexico", "arizona", "utah", "montana", "wyoming", "idaho",
     "north dakota", "south dakota", "nebraska", "washington", "oregon", "california", "nevada", "hawaii",
     "alaska"]))
# Regional names a script uses instead of states.
_REGIONS = {"east coast": ("GOES19", "ne"), "northeast": ("GOES19", "ne"), "new england": ("GOES19", "ne"),
            "mid-atlantic": ("GOES19", "ne"), "southeast": ("GOES19", "se"), "gulf coast": ("GOES19", "se"),
            "outer banks": ("GOES19", "se"), "long island": ("GOES19", "ne"), "midwest": ("GOES19", "umv"),
            "great lakes": ("GOES19", "cgl"), "pacific northwest": ("GOES18", "pnw"),
            "southern california": ("GOES18", "psw"), "rockies": ("GOES19", "sr"),
            # Look-alikes of state names: the capital is not Washington state,
            # and Los Angeles is not Louisiana.
            "washington, d.c.": ("GOES19", "ne"), "washington d.c.": ("GOES19", "ne"),
            "washington, dc": ("GOES19", "ne"), "washington dc": ("GOES19", "ne"),
            "district of columbia": ("GOES19", "ne"), "los angeles": ("GOES18", "psw"),
            "l.a.": ("GOES18", "psw")}
# A whole place that is only a short name ("LA", "D.C.").
_WHOLE = {"la": ("GOES18", "psw"), "dc": ("GOES19", "ne"), "d.c.": ("GOES19", "ne")}

SATELLITE_WORDS = re.compile(
    r"\b(satellite|from space|storm system|cloud (?:swirl|band|shield)|low[- ]pressure|nor'?easter|hurricane|"
    r"tropical storm|cyclone|bomb cyclone|atmospheric river|radar|the storm(?:'s)? (?:centre|center|track|eye))\b",
    re.I)

_USED: set = set()
_LOCK = threading.Lock()


def reset() -> None:
    with _LOCK:
        _USED.clear()


def is_now(story: dict, year_now: int = 0) -> bool:
    """The story is about this year's weather (a live loop shows it), not a
    past event: its year is this year, or it has no year and is marked recent."""
    import datetime
    year_now = year_now or datetime.date.today().year
    year = story.get("year")
    if isinstance(year, int) and not isinstance(year, bool):
        return year >= year_now and story.get("kind") in ("news", "weather", "disaster")
    return bool(story.get("recent")) and story.get("kind") in ("news", "weather", "disaster")


def sector_for(places) -> Optional[tuple]:
    """(satellite, sector) for the first place that names a US state or region."""
    for place in places or []:
        text = f" {str(place).lower()} "
        if text.strip() in _WHOLE:
            return _WHOLE[text.strip()]
        for name, where in _REGIONS.items():
            if name in text:
                return where
        for name, where in sorted(_SECTOR.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{re.escape(name)}\b", text):
                return where
        # A postal code only after a comma ("Denver, CO"): a bare "LA", "OR",
        # "IN" or "ME" is a city, a word or a pronoun, not a state.
        for abbr, name in _ABBR.items():
            if re.search(rf",\s*{abbr}\b", str(place)):
                return _SECTOR.get(name)
    return None


def latest_loop(sat: str, sector: str, timeout: int = 20) -> str:
    """URL of the newest GEOCOLOR MP4 loop for the sector, or ""."""
    base = _BASE.format(sat=sat, sector=sector)
    try:
        r = requests.get(base, timeout=timeout, headers={"User-Agent": config.USER_AGENT})
        if r.status_code != 200:
            return ""
        names = re.findall(r'href="([^"]+-GEOCOLOR-\d+x\d+\.mp4)"', r.text)
    except requests.RequestException:
        return ""
    return base + sorted(set(names))[-1] if names else ""


def satellite_clip(places, seconds: float, work_dir: str, story: Optional[dict] = None):
    """
    A MediaAsset of the live satellite loop over the story's region, slowed to
    cover `seconds` and framed at 1920x1080, or None (not a current story, no
    US region, sector already used, download failed).
    """
    story = story or {}
    if not is_now(story):
        return None
    where = sector_for(list(places or []) + list(story.get("places") or []))
    if not where:
        return None
    with _LOCK:
        if where in _USED:
            return None
        _USED.add(where)
    url = latest_loop(*where)
    if not url:
        return None
    from . import upscale
    from .media import MediaAsset
    from .storage import download
    raw = os.path.join(work_dir, f"goes_{where[0]}_{where[1]}_raw.mp4")
    out = os.path.join(work_dir, f"goes_{where[0]}_{where[1]}.mp4")
    try:
        download(url, raw, timeout=90)
        dur = max(1.0, _duration(raw))
        slow = max(1.0, (seconds + 0.5) / dur)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-vf",
                        f"setpts={slow:.3f}*PTS,minterpolate=fps=30:mi_mode=blend,format=yuv420p",
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out],
                       check=True, capture_output=True, timeout=180)
        upscale.frame_vertical(out)          # square loop -> sharp centre on a blurred fill
    except Exception as e:  # noqa: BLE001 - an official loop is a bonus, never a failure
        print(f"[official] GOES loop failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    return MediaAsset(kind="video", source="noaa_goes", url=url, local_path=out, duration=seconds,
                      attribution=f"NOAA {where[0].replace('GOES', 'GOES-')} satellite (public domain)",
                      license="public-domain", query="satellite loop")


def _duration(path: str) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=30)
        return float((p.stdout or "0").strip() or 0)
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        return 0.0
