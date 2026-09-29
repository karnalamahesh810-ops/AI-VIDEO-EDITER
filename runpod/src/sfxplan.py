"""
The overlay sound planner: which quiet sound each graphic gets, and exactly when.

A human editor lays a sound on the frame where a graphic lands, not where
its clip starts, keeps it well under the voice, and never plays the same
whoosh six times a minute. This module does that for the planned overlays:

  * The sound comes from the look's template (registry defaults "sfx"), or a
    per-overlay "sfx"/"sfxVolume" override from the editor; "none" is silent.
  * Timing: every sound file has its loudest point some way in (a whoosh
    builds for 0.7 s). The sound starts early by that much so its peak lands
    on the look's own visual hit, the template's "sfxAt" frame.
  * Looks that type letter by letter get the "keys" sound for exactly the
    typing span (contract: typing starts at frame TYPE_START and reveals one
    character every FRAMES_PER_CHAR frames at 30 fps). Looks that count a
    number up get "count-tick" for the count.
  * Quiet: a small base volume per kind of sound, times the style pack's
    intensity, never above MAX_VOLUME.
  * Sparse: one overlay sound per GAP_SECONDS, the stronger look winning;
    a typing or date look alone on screen always keeps its sound.
  * Never twice the same file within VARY_SECONDS when a sibling exists
    (whoosh -> whoosh-soft -> swipe), so the ear hears no loop.
  * Looks that play their own sounds inside the component are skipped, and
    a sound without a file in remotion/public/sfx is dropped.

Everything here is pure planning over plain dicts: no I/O except reading
the sound folder and its sfx_meta.json once.
"""
import json
import math
import os
from functools import lru_cache
from typing import Dict, List, Optional

from . import templates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(ROOT, "remotion", "public", "sfx")
META_FILE = "sfx_meta.json"

BASE_FPS = 30                 # template frame numbers ("sfxAt", typing contract) are at 30 fps
TYPE_START = 6                # typing starts on this frame of the overlay (30 fps)
TYPING_MAX_SECONDS = 6.0      # a typing sound never runs longer than this
COUNT_SECONDS = 1.3           # a number counts up over about this long
GAP_SECONDS = 6.0             # one overlay sound per this many seconds at most
VARY_SECONDS = 20.0           # the same file is not played twice within this if a sibling exists
MAX_SOUND_SECONDS = 6.0       # a one-shot sound is never scheduled longer than this
DEFAULT_SOUND_SECONDS = 3.0   # length assumed for a sound with no meta entry

# The owner (2026-09-29): sound effects about a quarter of the old level, a
# touch under the picture, never over the voice. (The old planner played
# 0.25-0.35 on files up to 6 dB hotter than today's loudness-matched set.)
# A look with no "sfxAt" lands its entrance about here (frames at 30 fps).
DEFAULT_HIT = 8
# Frames a hit may ring on after its look has gone, and the least worth playing.
RELEASE = 6
MIN_AUDIBLE = 4
BASE_VOLUME = 0.15
MAX_VOLUME = 0.2
VOLUME = {
    "keys": 0.1, "typewriter": 0.1, "typing text": 0.1, "keys-mech": 0.1, "keys-type": 0.1,
    "glitch-pro": 0.13,
    "count-tick": 0.12,
    "boom-soft": 0.13, "impact": 0.13, "flash-hit": 0.13,
    "marker": 0.15, "click": 0.15, "tick": 0.15,
}

TYPING_SOUND = "keys"
COUNT_SOUND = "count-tick"
# A look that does not type must not clack: a typing sound left on it (the
# old registry gave the kicker's mask rise a typewriter) becomes one click.
NOT_TYPING_SOUND = "click"
_TYPING_NAMES = {"keys", "typewriter", "typing text", "keys-mech", "keys-type"}
# The owner's own keyboard recordings (2026-09-29) lead; typing looks take
# them in turn so two typed lines never sound the same. "keys" is the fallback.
TYPING_TAKES = ["keys-type", "keys-mech", "keys"]
# Sounds with no single hit: they run for the action and start with it.
_CONTINUOUS = {"keys", "typewriter", "typing text", "count-tick", "keys-mech", "keys-type"}
# The only stand-in allowed for a missing file: the older typing recording.
_FALLBACK = {"keys": "typewriter"}

# Siblings a repeated sound alternates with, in order of preference.
VARIANTS = {
    "whoosh": ["whoosh-soft", "swipe"],
    "whoosh-soft": ["swipe", "whoosh"],
    "swipe": ["whoosh-soft", "whoosh"],
    "map-whoosh": ["whoosh-soft", "swipe"],
    "impact": ["boom-soft"],
    "boom-soft": ["impact"],
    "flash-hit": ["boom-soft"],
    "pop": ["click", "tick"],
    "click": ["tick", "pop"],
    "tick": ["click", "pop"],
    "paper": ["paper-slide", "page"],
    "paper-slide": ["paper", "page"],
    "page": ["paper-slide", "paper"],
    "glitch-transition": ["glitch-pro", "glitch-short", "glitch"],
    "glitch": ["glitch-pro", "glitch-short", "glitch-transition"],
    "glitch-short": ["glitch-pro", "glitch", "glitch-transition"],
    "glitch-pro": ["glitch-short", "glitch-transition"],
    "riser": ["riser-short"],
    "riser-short": ["riser"],
    "ding": ["marker"],
    "marker": ["ding"],
}
# Quiet style packs start from the softer take of a sound.
_SOFTER = {"whoosh": "whoosh-soft", "impact": "boom-soft", "riser": "riser-short",
           "glitch-transition": "glitch-short", "map-whoosh": "whoosh-soft"}
_SOFT_STYLES = {"cinematic", "minimal"}

# Measured on the original files (ffmpeg), used only when sfx_meta.json lacks a name.
_KNOWN_PEAK = {"impact": 0.55, "whoosh": 0.71, "map-whoosh": 0.56, "glitch-transition": 0.73,
               "riser": 2.0, "paper": 0.35, "pop": 0.03, "page": 0.46, "glitch": 0.39}
_KNOWN_DURATION = {"impact": 2.46, "whoosh": 2.32, "map-whoosh": 3.08, "riser": 5.07, "pop": 0.48,
                   "paper": 1.09, "typewriter": 3.47, "page": 2.5, "glitch-transition": 1.66,
                   "glitch": 1.02}

# Looks that play sounds inside their component (LibSpeakers Sfx, LibChartsC /
# LibBasinMap / LibPersist Tick). A timeline sound on top of them doubled up.
PLAYS_OWN_SOUND = {
    "LIB_SP_STATEMENT_CARD", "LIB_SP_CHECKLIST", "LIB_SP_CONCEPT_WAVE", "LIB_SP_NETWORK",
    "LIB_SP_QUOTE_PORTRAIT", "LIB_SP_CIRCLE_LIST", "LIB_PS_PERCENT_RING", "LIB_PS_PAPER_CHECKLIST",
}
PLAYS_OWN_PREFIXES = ("LIB_CC_", "LIB_BM_")

# Built-in looks that type, for registries built before the "types" flag.
_TYPING_TEMPLATES = {"TEXT_TYPEWRITER_V1", "TEXT_QUESTION_V1", "TEXT_MEMO_V1", "TEXT_BAR_TITLE_V1"}
_DATE_CUES = {"date", "time-of-day", "datetime"}
_COUNT_CUES = {"percent", "big-number", "count", "money"}
_RANK = {"high": 0, "medium": 1, "low": 2}


# --------------------------------------------------------------------------- #
# The sound folder
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _meta() -> Dict[str, dict]:
    """sfx_meta.json: {name: {duration, peak}}. Missing or broken reads as empty."""
    try:
        with open(os.path.join(SFX_DIR, META_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def reload() -> None:
    """Forget the cached sound meta (after the folder changed, or in tests)."""
    _meta.cache_clear()


def exists(name: Optional[str]) -> bool:
    """True when remotion/public/sfx/<name>.mp3 ships with the renderer."""
    if not name or name in ("none", "default") or "/" in name or "\\" in name:
        return False
    return os.path.isfile(os.path.join(SFX_DIR, f"{name}.mp3"))


def _number(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _seconds(name: str, key: str, known: Dict[str, float], default: float) -> float:
    v = _number((_meta().get(name) or {}).get(key))
    if v is None or v < 0:
        v = known.get(name, default)
    return v


def peak_frames(name: str, fps: int = BASE_FPS) -> int:
    """Frames from the start of a sound to its loudest point (0 when unknown)."""
    return int(round(_seconds(name, "peak", _KNOWN_PEAK, 0.0) * (fps or BASE_FPS)))


def duration_frames(name: str, fps: int = BASE_FPS) -> int:
    """The sound's own length in frames, capped at MAX_SOUND_SECONDS."""
    fps = fps or BASE_FPS
    secs = _seconds(name, "duration", _KNOWN_DURATION, DEFAULT_SOUND_SECONDS) or DEFAULT_SOUND_SECONDS
    return max(1, min(int(math.ceil(secs * fps)), int(round(MAX_SOUND_SECONDS * fps))))


def _scale(frames30, fps: int) -> int:
    """A frame number from the 30 fps contract at the video's frame rate."""
    v = _number(frames30) or 0.0
    return int(round(v * fps / BASE_FPS))


def frames_per_char(text: str) -> int:
    """Typing contract: 2 frames a character for short text, 1 for long."""
    return 2 if len(text or "") <= 48 else 1


def typing_frames(text: str, fps: int = BASE_FPS) -> int:
    """How long `text` takes to type, in frames at `fps` (capped at TYPING_MAX_SECONDS)."""
    fps = fps or BASE_FPS
    n = len(text or "")
    return min(_scale(frames_per_char(text) * n, fps), int(round(TYPING_MAX_SECONDS * fps)))


# --------------------------------------------------------------------------- #
# What a look is
# --------------------------------------------------------------------------- #

def plays_own_sound(template: dict) -> bool:
    tid = template.get("id") or ""
    d = template.get("defaults") or {}
    return bool(d.get("ownSfx")) or tid in PLAYS_OWN_SOUND or tid.startswith(PLAYS_OWN_PREFIXES)


def _types(template: dict) -> bool:
    d = template.get("defaults") or {}
    if "types" in d:
        return bool(d.get("types"))
    return template.get("id") in _TYPING_TEMPLATES


def _is_date(template: dict) -> bool:
    return bool(set(template.get("cues") or []) & _DATE_CUES) or \
        template.get("component") in ("date-stamp", "clock-badge")


def _counts(template: dict, overlay: dict) -> bool:
    d = template.get("defaults") or {}
    if "counts" in d:
        return bool(d.get("counts"))
    return bool(set(template.get("cues") or []) & _COUNT_CUES) and _number(overlay.get("value")) is not None


def _default_name(template: dict) -> str:
    s = (template.get("defaults") or {}).get("sfx")
    if isinstance(s, dict):
        return str(s.get("name") or "none")
    return str(s or "none")


def _choice(overlay: dict, template: dict):
    """
    (sound name or None for silence, explicit override?, volume override or None).
    A resolved {name, volume} equal to the template default is not an override;
    the editor's string "none" always silences.
    """
    default = _default_name(template)
    raw = overlay.get("sfx")
    name, explicit = default, False
    if isinstance(raw, dict):
        got = str(raw.get("name") or "")
        if got and got not in ("default", default):
            if got == "none":
                return None, True, None
            name, explicit = got, True
    elif isinstance(raw, str) and raw:
        if raw == "none":
            return None, True, None
        if raw not in ("default", default):
            name, explicit = raw, True
    vol = _number(overlay.get("sfxVolume"))
    return name, explicit, (None if vol is None else max(0.0, vol))


def _span(overlay: dict, template: Optional[dict], fps: int) -> tuple:
    start = int(_number(overlay.get("startFrame")) or 0)
    n = _number(overlay.get("durationInFrames"))
    if n is None:
        secs = _number(((template or {}).get("defaults") or {}).get("duration")) or 3.0
        n = secs * fps
    return start, start + max(1, int(n))


def _resolve_file(name: str) -> Optional[str]:
    if exists(name):
        return name
    alt = _FALLBACK.get(name)
    return alt if alt and exists(alt) else None


def _candidate(i: int, overlay: dict, fps: int, spans: List[tuple]) -> Optional[dict]:
    t = templates.get(overlay.get("template") or "")
    if not t or plays_own_sound(t):
        return None
    name, explicit, vol = _choice(overlay, t)
    if name is None:                       # silenced on purpose
        return None
    # A look that types always gets its keys (typing contract), even when
    # the registry left its sound at "none"; an explicit other sound wins.
    typing = _types(t) and not (explicit and name not in _TYPING_NAMES)
    if not typing and (not name or name == "none"):
        return None
    d = t.get("defaults") or {}
    start, end = spans[i]
    sfx_at = _scale(overlay.get("sfxAt", d.get("sfxAt", 0)), fps)
    text = str(overlay.get("text") or "")
    kind, begin, length = "hit", sfx_at, 0
    if typing:
        if not text.strip():
            return None
        name, kind = TYPING_SOUND, "typing"
        begin = _scale(TYPE_START, fps)
        if end - start <= begin:
            return None
        # Never type on after the look has left the screen.
        length = min(typing_frames(text, fps), end - start - begin)
    elif not explicit and _counts(t, overlay) and exists(COUNT_SOUND):
        name, kind = COUNT_SOUND, "count"
        count = int(round(COUNT_SECONDS * fps))
        if sfx_at > 0:
            begin = max(0, sfx_at - count)
            length = max(1, sfx_at - begin)
        else:
            begin = _scale(TYPE_START, fps)
            length = count
    elif name in _TYPING_NAMES and not explicit:
        # A typing sound on a look that does not type does not match it.
        name = NOT_TYPING_SOUND
    if kind == "hit" and not sfx_at:
        # No hit frame on record: the moment the entrance lands (MotionWrap
        # eases every overlay in over its first ~half second).
        begin = _scale(DEFAULT_HIT, fps)
    others = [s for j, s in enumerate(spans) if j != i]
    alone = not any(a < end and start < b for a, b in others)
    emphasis = overlay.get("emphasis") if overlay.get("emphasis") in _RANK else t.get("emphasis")
    return {
        "i": i, "name": name, "kind": kind, "explicit": explicit, "volume": vol,
        "hit": start + begin, "length": length, "start": start, "end": end,
        "rank": _RANK.get(emphasis, 1),
        "protected": (kind == "typing" or _is_date(t)) and alone,
    }


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #

def _select(cands: List[dict], gap: int) -> List[dict]:
    """One sound per `gap` frames, the stronger look winning; protected ones always stay."""
    picks: List[dict] = []
    last = None
    for c in sorted(cands, key=lambda c: (c["hit"], c["rank"], c["i"])):
        if c["protected"]:
            picks.append(c)
            last = c["hit"]
            continue
        if last is not None and c["hit"] - last < gap:
            if picks and not picks[-1]["protected"] and c["rank"] < picks[-1]["rank"]:
                picks.pop()
            else:
                continue
        picks.append(c)
        last = c["hit"]
    return picks


def _vary(name: str, hit: int, last_used: Dict[str, int], window: int, style: str) -> Optional[str]:
    """The file to play: `name`, or a sibling when `name` was just heard."""
    first = name
    if style in _SOFT_STYLES and exists(_SOFTER.get(name, "")):
        first = _SOFTER[name]
    order = [first] + [x for x in [name] + VARIANTS.get(first, []) + VARIANTS.get(name, []) if x != first]
    order = [x for x in dict.fromkeys(order) if exists(x)]
    if not order:
        return None
    for x in order:
        if hit - last_used.get(x, -10 ** 9) >= window:
            return x
    return min(order, key=lambda x: (last_used.get(x, -10 ** 9), order.index(x)))


def plan(overlays: List[dict], fps: int, intensity: float, style: str = "") -> List[dict]:
    """
    The overlay sound track: [{name, startFrame, volume, durationFrames, kind: "overlay"}],
    sorted by startFrame. `intensity` is the style pack's sfxIntensity, `style`
    its id (the quiet packs start from the softer take of each sound).
    """
    fps = int(fps or BASE_FPS)
    level = _number(intensity)
    level = 1.0 if level is None else level
    if level <= 0 or not overlays:
        return []
    ovs = [o for o in overlays if isinstance(o, dict)]
    spans = [_span(o, templates.get(o.get("template") or ""), fps) for o in ovs]
    cands = [c for c in (_candidate(i, o, fps, spans) for i, o in enumerate(ovs)) if c]
    picks = _select(cands, int(round(GAP_SECONDS * fps)))

    out: List[dict] = []
    last_used: Dict[str, int] = {}
    window = int(round(VARY_SECONDS * fps))
    takes = [t for t in TYPING_TAKES if exists(t)]
    typed = 0
    for c in sorted(picks, key=lambda c: (c["hit"], c["i"])):
        if c["kind"] == "hit" and not c["explicit"]:
            name = _vary(c["name"], c["hit"], last_used, window, style)
        elif c["kind"] == "typing" and c["name"] == TYPING_SOUND and takes:
            name = takes[typed % len(takes)]
            typed += 1
        else:
            name = _resolve_file(c["name"]) if c["kind"] != "hit" else (c["name"] if exists(c["name"]) else None)
        if not name:
            continue
        trim = 0
        if c["kind"] == "hit":
            # The loudest point lands on the look's hit. The sound never starts
            # before the look is on screen (its head is skipped instead, so the
            # peak stays on time) and stops, with a short release, when the
            # look leaves - it belongs to the animation, not around it.
            raw = c["hit"] - (0 if name in _CONTINUOUS else peak_frames(name, fps))
            start = max(c["start"], raw)
            trim = start - raw
            audible = min(duration_frames(name, fps) - trim, c["end"] - start + _scale(RELEASE, fps))
            if audible < _scale(MIN_AUDIBLE, fps):
                continue
            length = trim + audible
        else:
            start, length = c["hit"], max(1, c["length"])
        base = c["volume"] if c["volume"] is not None else VOLUME.get(name, BASE_VOLUME)
        volume = round(min(MAX_VOLUME, base * level), 3)
        if volume <= 0.005:
            continue
        last_used[name] = c["hit"]
        cue = {"name": name, "startFrame": max(0, int(start)), "volume": volume,
               "durationFrames": int(length), "kind": "overlay"}
        if trim:
            cue["trimFrames"] = int(trim)
        out.append(cue)
    out.sort(key=lambda s: s["startFrame"])
    return out
