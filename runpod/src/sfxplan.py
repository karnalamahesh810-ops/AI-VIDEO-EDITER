"""
The overlay sound planner: which sound each graphic gets, how loud, and exactly when.

A human editor lays a sound on the frame where a graphic lands, not where
its clip starts, keeps it under the voice, and never plays the same whoosh
six times a minute. This module does that for the planned overlays:

  * The sound comes from the look's template (registry defaults "sfx"), or a
    per-overlay "sfx"/"sfxVolume" override from the editor; "none" is silent.
    A calendar date lands on the owner's deep hit (DATE_SOUND), always.
  * Timing: every sound file has its loudest point some way in (a whoosh
    builds for 0.7 s). The sound starts early by that much so its peak lands
    on the look's own visual hit, the template's "sfxAt" frame - but never
    before the look is on screen (the head of the file is skipped instead),
    and it is over when the look leaves (the renderer fades a cut sound).
    A look cut short before its hit gets no sound at all.
  * Looks that type letter by letter get the "keys" sound for exactly the
    typing span (contract: typing starts at frame TYPE_START and reveals one
    character every FRAMES_PER_CHAR frames at 30 fps). Looks that count a
    number up get "count-tick" for the count.
  * Level (the owner, 2026-09-30: "make the sound effects NOT HIGHER than the
    voiceover - edit like a smart editor"): relative to the narration. Every
    file is loudness-matched (its loudest 400 ms ~ SFX_REF_LUFS), so a gain
    puts a sound's loudest moment a known number of dB under the voice's
    integrated loudness: typing ~10 dB under, whooshes ~9, clicks, ticks and
    paper ~7, hits, glitches and risers ~5 (sfx_meta.json "category", else
    the file's own name), times the style pack's intensity (a date's deep
    hit excepted: always at the date level), and never above one cap (cap())
    - an editor's override included.
  * Sparse: one overlay sound per GAP_SECONDS, the stronger look winning;
    a typing or date look alone on screen always keeps its sound, and of two
    looks that start within CLASH_SECONDS only the stronger one sounds.
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
# The renderer's own copy of the meta (Main.tsx imports it); new sounds may
# carry their "category" there first. The sound folder's file wins per field.
DATA_META = os.path.join(ROOT, "remotion", "src", "data", META_FILE)

BASE_FPS = 30                 # template frame numbers ("sfxAt", typing contract) are at 30 fps
TYPE_START = 6                # typing starts on this frame of the overlay (30 fps)
TYPING_MAX_SECONDS = 6.0      # a typing sound never runs longer than this
COUNT_SECONDS = 1.3           # a number counts up over about this long
GAP_SECONDS = 6.0             # one overlay sound per this many seconds at most
CLASH_SECONDS = 0.5           # two looks starting this close: only the stronger one gets a sound
VARY_SECONDS = 20.0           # the same file is not played twice within this if a sibling exists
MAX_SOUND_SECONDS = 6.0       # a one-shot sound is never scheduled longer than this
DEFAULT_SOUND_SECONDS = 3.0   # length assumed for a sound with no meta entry

# A look with no "sfxAt" lands its entrance about here (frames at 30 fps).
DEFAULT_HIT = 8
# The least of a sound worth playing (frames at 30 fps).
MIN_AUDIBLE = 4

# ------------------------------------------------------------------ levels
# Every file in public/sfx is loudness-matched: its loudest 400 ms sits at
# about SFX_REF_LUFS (true peak <= -3.5 dBFS). The narration is measured once
# per video (timeline.voice_loudness) or assumed at VOICE_LUFS_DEFAULT.
SFX_REF_LUFS = -20.0
VOICE_LUFS_DEFAULT = -16.0
# A sound's loudest moment sits this far under the voice ...
UNDER_VOICE_DB = 6.0
# ... by its category (sfx_meta.json "category"; CATEGORY for the files that predate it) ...
CATEGORY_UNDER_DB = {"typing": 10.0, "whoosh": 9.0, "shimmer": 9.0, "ui": 7.0, "tick": 7.0, "marker": 7.0,
                     "paper": 7.0, "camera": 7.0, "impact": 5.0, "glitch": 5.0, "riser": 5.0}
CATEGORY = {
    "keys": "typing", "typewriter": "typing", "typing text": "typing", "keys-mech": "typing",
    "keys-type": "typing", "keys-laptop": "typing",
    "whoosh": "whoosh", "whoosh-soft": "whoosh", "swipe": "whoosh", "map-whoosh": "whoosh",
    "whoosh-cinematic-for-maps": "whoosh",
    "click": "ui", "pop": "ui", "ding": "ui", "tick": "tick", "count-tick": "tick", "marker": "marker",
    "paper": "paper", "paper-slide": "paper", "page": "paper", "shutter": "camera",
    "impact": "impact", "hit-deep": "impact", "boom-soft": "impact", "flash-hit": "impact",
    "glitch": "glitch", "glitch-pro": "glitch", "glitch-short": "glitch", "glitch-transition": "glitch",
    "glitch fx transistion": "glitch", "riser": "riser", "riser-short": "riser",
}
# ... and never closer to it than this: the one cap every sound is held to
# (planned, transition, or an editor's 100% slider). It is the level of the
# loudest category, so nothing ever stands out over the hits.
CAP_UNDER_DB = 5.0

# Every calendar date lands on the owner's deep hit (2026-09-30: "BOLD TEXT
# date with a better sound"), at the hits' level.
DATE_SOUND = "hit-deep"

TYPING_SOUND = "keys"
COUNT_SOUND = "count-tick"
# A look that does not type must not clack: a typing sound left on it (the
# old registry gave the kicker's mask rise a typewriter) becomes one click.
NOT_TYPING_SOUND = "click"
_TYPING_NAMES = {"keys", "typewriter", "typing text", "keys-mech", "keys-type", "keys-laptop"}
# The owner's own keyboard recordings (2026-09-29) lead; typing looks take
# them in turn so two typed lines never sound the same. "keys" is the fallback.
TYPING_TAKES = ["keys-type", "keys-laptop", "keys-mech", "keys"]
# Sounds with no single hit: they run for the action and start with it.
_CONTINUOUS = {"keys", "typewriter", "typing text", "count-tick", "keys-mech", "keys-type", "keys-laptop"}
# The only stand-in allowed for a missing file: the older typing recording.
_FALLBACK = {"keys": "typewriter"}

# Siblings a repeated sound alternates with, in order of preference.
VARIANTS = {
    "whoosh": ["whoosh-soft", "swipe"],
    "whoosh-soft": ["swipe", "whoosh"],
    "swipe": ["whoosh-soft", "whoosh"],
    "map-whoosh": ["whoosh-soft", "swipe"],
    "impact": ["hit-deep", "boom-soft"],
    "boom-soft": ["hit-deep", "impact"],
    "hit-deep": ["boom-soft", "impact"],
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
# Built-in looks that type over a fixed eased window, whatever the text length
# (TextGraphics MemoBox: typed(fps*0.2, fps*1.2); BarTitle: typed(fps*0.3, fps*1.1)):
# (first typing frame, frames the sound runs) at 30 fps. The ease-out puts
# nearly all the text on screen early, so the sound stops a little before the window ends.
_FIXED_TYPING = {"memo-box": (6, 30), "bar-title": (9, 27)}
_DATE_CUES = {"date", "time-of-day", "datetime"}
_COUNT_CUES = {"percent", "big-number", "count", "money"}
_RANK = {"high": 0, "medium": 1, "low": 2}


# --------------------------------------------------------------------------- #
# The sound folder
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _meta() -> Dict[str, dict]:
    """
    {name: {duration, peak, category?}} from sfx_meta.json: the renderer's copy
    (remotion/src/data) first, the sound folder's own file over it field by
    field. Missing or broken files read as empty.
    """
    out: Dict[str, dict] = {}
    for path in (DATA_META, os.path.join(SFX_DIR, META_FILE)):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for k, v in data.items():
            if isinstance(v, dict):
                out[str(k)] = {**out.get(str(k), {}), **v}
    return out


def reload() -> None:
    """Forget the cached sound meta (after the folder changed, or in tests)."""
    _meta.cache_clear()


def exists(name: Optional[str]) -> bool:
    """True when remotion/public/sfx/<name>.mp3 ships with the renderer."""
    if not name or name in ("none", "default") or "/" in name or "\\" in name:
        return False
    return os.path.isfile(os.path.join(SFX_DIR, f"{name}.mp3"))


def _number(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
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
# Levels against the voice
# --------------------------------------------------------------------------- #

def voice_level(voice_lufs=None) -> float:
    """The narration's integrated loudness (LUFS), VOICE_LUFS_DEFAULT when unknown or absurd."""
    v = _number(voice_lufs)
    return v if v is not None and -60.0 < v < 0.0 else VOICE_LUFS_DEFAULT


def category(name: str) -> str:
    """The sound's category: sfx_meta.json's own, else the one its file name implies ('' when unknown)."""
    got = (_meta().get(name) or {}).get("category")
    if isinstance(got, str) and got.strip().lower() in CATEGORY_UNDER_DB:
        return got.strip().lower()
    return CATEGORY.get(name or "", "")


def under_voice_db(name: str) -> float:
    """How far under the voice a sound's loudest moment is set (dB)."""
    return CATEGORY_UNDER_DB.get(category(name), UNDER_VOICE_DB)


def gain(db_under: float, voice_lufs=None) -> float:
    """The linear gain that puts a loudness-matched file's loudest moment `db_under` dB under the voice."""
    return 10 ** ((voice_level(voice_lufs) - float(db_under) - SFX_REF_LUFS) / 20.0)


def cap(voice_lufs=None) -> float:
    """The one ceiling for every sound in the video (never above the renderer's 1.0)."""
    return min(1.0, gain(CAP_UNDER_DB, voice_lufs))


def level(name: str, voice_lufs=None) -> float:
    """The planned gain of a sound against this voice, before the style pack's intensity."""
    return min(cap(voice_lufs), gain(under_voice_db(name), voice_lufs))


def clamp(volume, voice_lufs=None, master=1.0) -> float:
    """
    A volume held under the cap. `master` is the document's sfxVolume, which
    the renderer multiplies in: a master above 1 lowers the ceiling to match.
    """
    v = _number(volume)
    if v is None or v <= 0:
        return 0.0
    m = _number(master)
    return min(v, cap(voice_lufs) / max(1.0, m if m is not None else 1.0))


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


def is_calendar_date(template: dict) -> bool:
    """
    A look that shows a calendar date (not a clock): it carries the date or
    datetime cue but not the time-of-day one, and is a date look (the
    TIMELINES family or the dt- library), not an effect or a year tape that
    also answers to "date".
    """
    cues = set(templates.cues_of(template))
    if not cues & {"date", "datetime"} or "time-of-day" in cues or template.get("component") == "clock-badge":
        return False
    return template.get("category") == "TIMELINES" or str(template.get("id") or "").startswith("LIB_DT_")


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
    # A calendar date always lands on the deep hit (an editor's own pick still wins).
    date = not explicit and is_calendar_date(t) and exists(DATE_SOUND)
    # A look that types always gets its keys (typing contract), even when
    # the registry left its sound at "none"; an explicit other sound wins.
    typing = _types(t) and not date and not (explicit and name not in _TYPING_NAMES)
    if date:
        name = DATE_SOUND
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
        fixed = _FIXED_TYPING.get(t.get("component") or "")
        begin = _scale(fixed[0] if fixed else TYPE_START, fps)
        if end - start <= begin:
            return None
        # Never type on after the look has left the screen.
        span = _scale(fixed[1], fps) if fixed else typing_frames(text, fps)
        length = min(span, end - start - begin)
    elif not explicit and not date and _counts(t, overlay) and exists(COUNT_SOUND):
        name, kind = COUNT_SOUND, "count"
        count = int(round(COUNT_SECONDS * fps))
        if sfx_at >= count:
            # sfxAt marks where the count lands: the ticks run up to it.
            begin = sfx_at - count
        else:
            # sfxAt is an entrance hit (the corner stat clicks in at 6, then
            # counts) or absent: the count starts on it or at the usual start.
            begin = max(sfx_at, _scale(TYPE_START, fps))
        # The ticks stop with the look, never after it.
        length = min(count, end - start - begin)
    elif name in _TYPING_NAMES and not explicit:
        # A typing sound on a look that does not type does not match it.
        name = NOT_TYPING_SOUND
    if kind == "hit" and not sfx_at:
        # No hit frame on record: the moment the entrance lands (MotionWrap
        # eases every overlay in over its first ~half second).
        begin = _scale(DEFAULT_HIT, fps)
    if kind == "hit" and start + begin >= end - _scale(MIN_AUDIBLE, fps):
        return None                        # cut short before its hit: no sound
    if kind != "hit" and length < _scale(MIN_AUDIBLE, fps):
        return None
    others = [s for j, s in enumerate(spans) if j != i]
    alone = not any(a < end and start < b for a, b in others)
    emphasis = overlay.get("emphasis") if overlay.get("emphasis") in _RANK else t.get("emphasis")
    return {
        "i": i, "name": name, "kind": kind, "explicit": explicit, "volume": vol, "fixed": date,
        "hit": start + begin, "length": length, "start": start, "end": end,
        "rank": _RANK.get(emphasis, 1),
        "protected": (kind == "typing" or date or _is_date(t)) and alone,
    }


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #

def _stronger(a: dict, b: dict) -> bool:
    """a beats b for the one sound two clashing looks may have: emphasis, then a protected look, then the first."""
    return (a["rank"], 0 if a["protected"] else 1, a["start"], a["i"]) < \
        (b["rank"], 0 if b["protected"] else 1, b["start"], b["i"])


def _select(cands: List[dict], gap: int, clash: int = 0) -> List[dict]:
    """
    One sound per look. Of two looks that start within `clash` frames only
    the stronger one sounds (protected or not); then one sound per `gap`
    frames, the stronger look winning, protected ones always staying.
    """
    kept: List[dict] = []
    for c in sorted(cands, key=lambda c: (c["start"], c["i"])):
        rival = next((k for k in kept if abs(c["start"] - k["start"]) <= clash), None) if clash else None
        if rival is None:
            kept.append(c)
        elif _stronger(c, rival):
            kept[kept.index(rival)] = c
    picks: List[dict] = []
    last = None
    for c in sorted(kept, key=lambda c: (c["hit"], c["rank"], c["i"])):
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


# The owner's own recordings lead where they fit (2026-09-29): the deep hit
# is the first choice for every impact / soft boom (date slams, bold cards).
_PREFERRED = {"impact": "hit-deep", "boom-soft": "hit-deep"}


def _vary(name: str, hit: int, last_used: Dict[str, int], window: int, style: str) -> Optional[str]:
    """The file to play: `name`, or a sibling when `name` was just heard."""
    first = name
    if exists(_PREFERRED.get(name, "")):
        first = _PREFERRED[name]
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


def plan(overlays: List[dict], fps: int, intensity: float, style: str = "",
         voice_lufs: Optional[float] = None) -> List[dict]:
    """
    The overlay sound track: [{name, startFrame, volume, durationFrames, kind: "overlay"}],
    sorted by startFrame. `intensity` is the style pack's sfxIntensity, `style`
    its id (the quiet packs start from the softer take of each sound),
    `voice_lufs` the narration's measured loudness (VOICE_LUFS_DEFAULT when None).
    """
    fps = int(fps or BASE_FPS)
    strength = _number(intensity)
    strength = 1.0 if strength is None else strength
    if strength <= 0 or not overlays:
        return []
    voice = voice_level(voice_lufs)
    top = cap(voice)
    ovs = [o for o in overlays if isinstance(o, dict)]
    spans = [_span(o, templates.get(o.get("template") or ""), fps) for o in ovs]
    cands = [c for c in (_candidate(i, o, fps, spans) for i, o in enumerate(ovs)) if c]
    picks = _select(cands, int(round(GAP_SECONDS * fps)), int(round(CLASH_SECONDS * fps)))

    out: List[dict] = []
    last_used: Dict[str, int] = {}
    window = int(round(VARY_SECONDS * fps))
    takes = [t for t in TYPING_TAKES if exists(t)]
    typed = 0
    for c in sorted(picks, key=lambda c: (c["hit"], c["i"])):
        if c["kind"] == "hit" and not c["explicit"] and not c["fixed"]:
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
            # peak stays on time) and is over when the look leaves (the
            # renderer fades a sound cut short over its last frames).
            raw = c["hit"] - (0 if name in _CONTINUOUS else peak_frames(name, fps))
            start = max(c["start"], raw)
            trim = start - raw
            audible = min(duration_frames(name, fps) - trim, c["end"] - start)
            if audible < _scale(MIN_AUDIBLE, fps):
                continue
            length = trim + audible
        else:
            start, length = c["hit"], max(1, c["length"])
        if c["volume"] is not None:
            # The editor's own level stands as set, never above the cap.
            volume = min(top, c["volume"])
        else:
            # A date's deep hit is always at the date level; the rest follow the pack's intensity.
            volume = min(top, level(name, voice) * (1.0 if c["fixed"] else strength))
        volume = round(volume, 3)
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
