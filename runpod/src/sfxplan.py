"""
The overlay sound planner: which sound each graphic gets, how loud, and exactly when.

Since 2026-09-30 (the owner: "when you make an animation, the animation needs
its specific sound BUILT IN - not us adding sounds on the timeline") every
look in the registry carries its own sound design (defaults.sounds, written
by scripts/build_registry.py) and the renderer plays it inside the overlay
(remotion/src/components/lib/LookSounds.tsx): such a look gets NO timeline
row here. The second half of this module is the Python twin of the
renderer's schedule (look_sounds, plan_looks, builtin_busy): the same frames,
files and levels, so the planner can keep the transition sounds clear of the
looks' own sounds and the tests can check the renderer's arithmetic. The
row planner below remains for documents and registries from before that
(a template without "sounds"):

A human editor lays a sound on the frame where a graphic lands, not where
its clip starts, keeps it under the voice, and never plays the same whoosh
six times a minute. This module does that for the planned overlays:

  * The sound comes from the look's template (registry defaults "sfx"), or a
    per-overlay "sfx"/"sfxVolume" override from the editor; "none" is silent.
    A calendar date lands on a soft digital tick (DATE_SOUND), never a hit.
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
    voiceover - edit like a smart editor"; 2026-10-01: they still were, the
    glitches most): relative to the narration. Every file's loudest 400 ms
    is measured (sfx_meta.json "lufs"; about SFX_REF_LUFS, the matched
    level), so a gain puts a sound's loudest moment a known number of dB
    under the voice's integrated loudness: typing ~10 dB under, whooshes and
    glitches ~9, clicks, ticks and paper ~7, hits and risers ~6
    (sfx_meta.json "category", else the file's own name), times the style
    pack's intensity (a date's tick excepted: always at its own level), and
    never closer than the ceiling (cap(): 6 dB under the voice, a glitch or
    static sound 9) - an editor's override included.
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
# about SFX_REF_LUFS (true peak <= -3.5 dBFS). sfx_meta.json "lufs" is that
# loudest 400 ms as measured per file (BS.1770 momentary loudness, the file
# padded with silence; "peakDb" its sample peak): a file hotter than the
# reference is turned down by the difference, a quieter one is never raised.
# The narration is measured once per video (timeline.voice_loudness) or
# assumed at VOICE_LUFS_DEFAULT.
SFX_REF_LUFS = -20.0
# A narration nobody could measure is assumed where measured ones sit (the
# bench narrations -19.9 to -20.3 LUFS). Assuming a louder voice (-16, until
# 2026-10-01) set every sound of the owner's Lake Powell video for a voice
# 4 dB louder than a typical one: the sounds stood over the narration.
VOICE_LUFS_DEFAULT = -20.0
# A sound's loudest moment sits this far under the voice ...
UNDER_VOICE_DB = 6.0
# ... by its category (sfx_meta.json "category"; CATEGORY for the files that predate it) ...
CATEGORY_UNDER_DB = {"typing": 10.0, "whoosh": 9.0, "shimmer": 9.0, "ui": 7.0, "tick": 7.0, "marker": 7.0,
                     "paper": 7.0, "camera": 7.0, "impact": 6.0, "glitch": 9.0, "riser": 6.0}
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
    # The sound designer's premium set (2026-09-30; sfx_meta.json carries the
    # same categories): a look asking for one that does not ship plays its stand-in.
    "alert-tone": "ui", "boom-sub": "impact", "camera-flash-pop": "camera", "camera-shutter": "camera",
    "count-final": "ui", "count-roll": "tick", "folder-open": "paper",
    "frame-drop": "impact", "glitch-digital": "glitch", "glitch-short-v2": "glitch",
    "letter-tick": "tick", "light-shimmer": "shimmer", "magnifier-glide": "shimmer", "map-swoop": "whoosh",
    "marker-draw": "marker", "marker-underline": "marker", "page-flip": "paper", "paper-pin": "paper",
    "paper-slide-v2": "paper", "paper-tear": "paper", "pen-scribble": "marker", "phone-buzz": "ui",
    "pin-drop": "ui", "radar-ping": "ui", "record-beep": "camera", "reverse-swell": "riser",
    "riser-short-v2": "riser", "shutter-slide": "paper", "stamp": "impact", "swoosh-text": "whoosh",
    "tape-rip": "paper", "typewriter-clean": "typing", "ui-click": "ui", "ui-pop": "ui", "ui-swipe": "whoosh",
    "ui-tick": "tick", "whoosh-cinematic": "whoosh", "whoosh-fast": "whoosh", "whoosh-soft-v2": "whoosh",
    "zoom-in-whoosh": "whoosh",
}
# ... and never closer to it than this: the ceiling every sound is held to
# (planned, transition, or an editor's 100% slider). The owner, 2026-10-01:
# no sound effect or transition sound is ever louder than the narration -
# its peaks sit about 6 dB under the voice, a glitch or static sound a
# further 3 dB (CAP_UNDER_CATEGORY_DB). It is the level of the loudest
# category, so nothing ever stands out over the hits.
CAP_UNDER_DB = 6.0
GLITCH_EXTRA_DB = 3.0
CAP_UNDER_CATEGORY_DB = {"glitch": CAP_UNDER_DB + GLITCH_EXTRA_DB}

# A calendar date sounds like its digits: one soft digital tick, never a hit
# (the owner, 2026-10-01: "only a digit sound ... you used a punch sound as
# well, we don't need that, that sound is super bad, remove that sound effect
# from our list" - the date slam and the impact punch are gone from the set).
DATE_SOUND = "letter-tick"
DATE_SOUND_ALT = ("ui-tick", "tick")

TYPING_SOUND = "keys"
# A number counts up on the counter's roll and lands on its final click.
COUNT_SOUND = "count-roll"
COUNT_FINAL = "count-final"
# A look that does not type must not clack: a typing sound left on it (the
# old registry gave the kicker's mask rise a typewriter) becomes one click.
NOT_TYPING_SOUND = "click"
_TYPING_NAMES = {"keys", "typewriter", "typing text", "keys-mech", "keys-type", "keys-laptop", "typewriter-clean"}
# The owner's own keyboard recordings (2026-09-29) lead; typing looks take
# them in turn so two typed lines never sound the same. "keys" is the fallback.
TYPING_TAKES = ["keys-type", "keys-laptop", "keys-mech", "keys"]
# Sounds with no single hit: they run for the action and start with it.
_CONTINUOUS = {"keys", "typewriter", "typing text", "count-tick", "keys-mech", "keys-type", "keys-laptop",
               "count-roll", "typewriter-clean"}
# The only stand-ins allowed for a missing file: the older recordings.
_FALLBACK = {"keys": "typewriter", "count-roll": "count-tick"}

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
    # The sound designer's premium set (2026-09-30).
    "whoosh-cinematic": ["whoosh-soft-v2", "map-swoop"], "whoosh-soft-v2": ["swoosh-text", "ui-swipe"],
    "swoosh-text": ["ui-swipe", "whoosh-soft-v2"], "whoosh-fast": ["ui-swipe", "swoosh-text"],
    "ui-swipe": ["whoosh-fast", "swoosh-text"], "map-swoop": ["whoosh-cinematic", "map-whoosh"],
    "zoom-in-whoosh": ["whoosh-fast"], "boom-sub": ["hit-deep"], "ui-pop": ["ui-click", "ui-tick"],
    "ui-click": ["ui-tick", "ui-pop"], "ui-tick": ["ui-click"], "paper-slide-v2": ["page-flip", "folder-open"],
    "page-flip": ["paper-slide-v2"], "folder-open": ["paper-slide-v2"], "tape-rip": ["paper-tear"],
    "paper-tear": ["tape-rip"], "marker-draw": ["marker-underline"], "marker-underline": ["marker-draw"],
    "glitch-digital": ["glitch-pro", "glitch-short-v2"], "glitch-short-v2": ["glitch-pro", "glitch-digital"],
    "riser-short-v2": ["reverse-swell"], "reverse-swell": ["riser-short-v2"], "light-shimmer": ["whoosh-soft-v2"],
    "camera-shutter": ["camera-flash-pop"], "camera-flash-pop": ["camera-shutter"], "pin-drop": ["ui-pop"],
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
_FIXED_TYPING = {"memo-box": (6, 36), "bar-title": (9, 33)}      # the rebuilt looks type 6..42 and 9..42 (2026-09-30 audit)
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


def ceiling_db(name: Optional[str] = None) -> float:
    """How close to the voice a sound may ever come at its loudest (dB under): CAP_UNDER_DB, a glitch further."""
    return max(CAP_UNDER_DB, CAP_UNDER_CATEGORY_DB.get(category(name or ""), CAP_UNDER_DB))


def file_lufs(name: Optional[str] = None) -> float:
    """
    The loudest 400 ms of a sound file as levelled: its measured "lufs" when
    that is hotter than the matched SFX_REF_LUFS (it is turned down by the
    difference), else the reference (a quieter file is never raised).
    """
    v = _number((_meta().get(name) or {}).get("lufs")) if name else None
    return SFX_REF_LUFS if v is None else max(SFX_REF_LUFS, v)


def gain(db_under: float, voice_lufs=None, name: Optional[str] = None) -> float:
    """The linear gain that puts a file's loudest moment `db_under` dB under the voice (`name`: that file's own loudness)."""
    return 10 ** ((voice_level(voice_lufs) - float(db_under) - file_lufs(name)) / 20.0)


def cap(voice_lufs=None, name: Optional[str] = None) -> float:
    """
    The ceiling a sound is held under (never above the renderer's 1.0): its
    loudest moment CAP_UNDER_DB under the voice, a glitch's further
    (ceiling_db). Without a name, the ceiling of a matched file of no category.
    """
    return min(1.0, gain(ceiling_db(name), voice_lufs, name))


def level(name: str, voice_lufs=None) -> float:
    """The planned gain of a sound against this voice, before the style pack's intensity."""
    return min(cap(voice_lufs, name), gain(under_voice_db(name), voice_lufs, name))


def clamp(volume, voice_lufs=None, master=1.0, name: Optional[str] = None) -> float:
    """
    A volume held under the sound's ceiling (cap). `master` is the document's
    sfxVolume, which the renderer multiplies in: a master above 1 lowers the
    ceiling to match.
    """
    v = _number(volume)
    if v is None or v <= 0:
        return 0.0
    m = _number(master)
    return min(v, cap(voice_lufs, name) / max(1.0, m if m is not None else 1.0))


def peak_under_voice(name: str, volume: float, voice_lufs=None) -> Optional[float]:
    """
    How far (dB) a sound's loudest moment, played at `volume`, sits under the
    voice's loudness: its measured "lufs" (else the matched reference) plus
    the gain, against voice_level. None for a silent volume.
    """
    v = _number(volume)
    if v is None or v <= 0:
        return None
    got = _number((_meta().get(name) or {}).get("lufs"))
    loud = SFX_REF_LUFS if got is None else got
    return voice_level(voice_lufs) - (loud + 20.0 * math.log10(v))


# --------------------------------------------------------------------------- #
# What a look is
# --------------------------------------------------------------------------- #

def plays_own_sound(template: dict) -> bool:
    """A look whose component plays its own <Audio> (LibSpeakers, LibPersist, LibChartsC, LibBasinMap)."""
    tid = template.get("id") or ""
    d = template.get("defaults") or {}
    return bool(d.get("ownSfx") or d.get("ownSound")) or tid in PLAYS_OWN_SOUND or tid.startswith(PLAYS_OWN_PREFIXES)


def has_builtin_sound(template: Optional[dict]) -> bool:
    """A look with its sound design built in (the registry's defaults.sounds, even an empty one)."""
    d = (template or {}).get("defaults") or {}
    return isinstance(d.get("sounds"), list)


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


def date_sound() -> Optional[str]:
    """The file a calendar date ticks on: DATE_SOUND, else its first stand-in that ships."""
    return next((n for n in (DATE_SOUND,) + tuple(DATE_SOUND_ALT) if exists(n)), None)


def _candidate(i: int, overlay: dict, fps: int, spans: List[tuple]) -> Optional[dict]:
    t = templates.get(overlay.get("template") or "")
    if not t or plays_own_sound(t) or has_builtin_sound(t):
        # A look with its sound built in plays it itself (LookSounds.tsx):
        # a timeline row on top of it would double it.
        return None
    name, explicit, vol = _choice(overlay, t)
    if name is None:                       # silenced on purpose
        return None
    # A calendar date always lands on its soft tick (an editor's own pick still wins).
    tick = date_sound()
    date = not explicit and is_calendar_date(t) and bool(tick)
    # A look that types always gets its keys (typing contract), even when
    # the registry left its sound at "none"; an explicit other sound wins.
    typing = _types(t) and not date and not (explicit and name not in _TYPING_NAMES)
    if date:
        name = tick
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
    elif not explicit and not date and _counts(t, overlay) and _resolve_file(COUNT_SOUND):
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
# is the first choice for every impact / soft boom (bold cards; never a date or a number).
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
            natural = duration_frames(name, fps) - trim
            audible = min(natural, c["end"] - start)
            # A short tick plays whole; only a sound the look's end cuts to almost nothing is dropped.
            if audible <= 0 or (audible < natural and audible < _scale(MIN_AUDIBLE, fps)):
                continue
            length = trim + audible
        else:
            start, length = c["hit"], max(1, c["length"])
        top = cap(voice, name)
        if c["volume"] is not None:
            # The editor's own level stands as set, never above the cap.
            volume = min(top, c["volume"])
        else:
            # A date's tick is always at its own level; the rest follow the pack's intensity.
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
        if c["kind"] == "count" and exists(COUNT_FINAL):
            # The count lands on its final click, never after the look has left.
            land = int(start) + int(length)
            raw = land - peak_frames(COUNT_FINAL, fps)
            audible = min(duration_frames(COUNT_FINAL, fps), c["end"] - max(0, raw))
            if land < c["end"] - _scale(MIN_AUDIBLE, fps) and audible >= _scale(MIN_AUDIBLE, fps):
                out.append({"name": COUNT_FINAL, "startFrame": max(0, raw), "kind": "overlay", "durationFrames": audible,
                            "volume": round(min(cap(voice, COUNT_FINAL), level(COUNT_FINAL, voice) * strength
                                                if c["volume"] is None else c["volume"]), 3)})
    out.sort(key=lambda s: s["startFrame"])
    return out


# =========================================================================== #
# Sounds built into the looks: the Python twin of lookSoundPlan.ts
# =========================================================================== #
#
# A look's sound design is a list of cues (registry defaults.sounds, or the
# cues a component schedules from its own animation with useLookSound):
#
#   name       a file in remotion/public/sfx (no extension)
#   alt        stand-ins, in order, while `name` does not ship
#   at         30-fps frame from the look's first frame: where the sound's
#              loudest moment lands (align "peak", the default for one-shots)
#              or where it starts (align "start", the default for loops)
#   align      "peak" | "start"
#   until      a run: it plays from `at` to this frame (a loopable file loops)
#   kind       "typing": the video's current typing take, for the typing
#              contract's span of the overlay's text
#   every, count   the cue again every `every` frames, `count` times in all
#              ("items" / "locations": once per overlay item / place)
#   gain_db    dB against the sound's category level for this voice
#   fade       fade-out frames at its end (a sound cut by the look's end always fades)
#   when       "value" | "no-value": only when the overlay has (no) number
#   fixed      not scaled by the style pack's intensity
#   scale      cue frames stretch with the look's duration against its default
#   pitch      the render's tone change (1 = as recorded)
#
# Every cue is set against the narration like the rows above: level() for
# its file's category, times 10^(gain_db/20), the pack's intensity (unless
# fixed), the overlay's soundGain trim and the document's sfxVolume, never
# above cap(). Both twins round like JavaScript (_jr) so they agree frame
# for frame; tests/test_builtin_sounds.py runs the TypeScript against this.

# Stand-ins by category for a file that does not ship (the first that does wins).
CATEGORY_FALLBACK = {
    "impact": ["hit-deep", "boom-sub", "boom-soft", "impact"],
    "tick": ["ui-tick", "tick", "letter-tick", "click"], "ui": ["ui-click", "ui-pop", "click", "pop"],
    "whoosh": ["whoosh-soft-v2", "swoosh-text", "whoosh-soft", "swipe"],
    "paper": ["paper-slide-v2", "paper-slide", "paper", "page"], "marker": ["marker-draw", "marker", "tick"],
    "typing": ["keys", "typewriter-clean", "typewriter"], "camera": ["camera-shutter", "shutter", "click"],
    "glitch": ["glitch-short-v2", "glitch-short", "glitch-pro"], "riser": ["riser-short-v2", "riser-short", "riser"],
    "shimmer": ["light-shimmer", "whoosh-soft-v2", "whoosh-soft"],
}
# Files that loop seamlessly when sfx_meta.json does not say ("loop").
LOOP_NAMES = {"keys", "typewriter", "keys-mech", "keys-type", "keys-laptop", "typing text", "count-roll",
              "typewriter-clean"}
MAX_REPEATS = 200
PROTECTED_COMPONENTS = ("date-stamp", "clock-badge")


def _jr(x) -> int:
    """JavaScript's Math.round (halves up), so the two twins agree frame for frame."""
    return int(math.floor(float(x) + 0.5))


def _r4(x: float) -> float:
    return math.floor(x * 10000 + 0.5) / 10000


def shipped(name) -> bool:
    """A file the renderer can play: in public/sfx and in sfx_meta.json (all the renderer can see)."""
    return isinstance(name, str) and bool(name) and name in _meta() and exists(name)


def resolve_sound(name, alt=None) -> Optional[str]:
    """`name` if it ships, else its first shipped stand-in (`alt`, then its category's), else None."""
    order = [name] + [a for a in (alt or []) if isinstance(a, str)] \
        + CATEGORY_FALLBACK.get(category(str(name or "")), [])
    return next((x for x in order if shipped(x)), None)


def loopable(name: str) -> bool:
    got = (_meta().get(name) or {}).get("loop")
    return got if isinstance(got, bool) else name in LOOP_NAMES


def _file_frames(name: str, fps: int) -> int:
    d = _number((_meta().get(name) or {}).get("duration"))
    return max(1, int(math.ceil((d if d is not None and d > 0 else DEFAULT_SOUND_SECONDS) * fps)))


def _peak(name: str, fps: int) -> int:
    p = _number((_meta().get(name) or {}).get("peak"))
    return max(0, _jr((p if p is not None else 0.0) * fps))


def value_of(overlay: dict) -> Optional[float]:
    """The overlay's number, when it has one."""
    v = (overlay or {}).get("value")
    return float(v) if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) else None


def cue_live(cue: dict, text: str = "", value: Optional[float] = None) -> bool:
    """Whether a cue plays for this overlay (its `when`; a typing run needs words)."""
    when = cue.get("when")
    if (when == "value" and value is None) or (when == "no-value" and value is not None):
        return False
    return not (cue.get("kind") == "typing" and not str(text or "").strip())


def typing_span(text: str, fps: int) -> int:
    """The typing contract's span in frames: 2 frames a character up to 48, else 1 (30 fps), at most 6 s."""
    n = len(text or "")
    return min(_jr((2 if n <= 48 else 1) * n * fps / BASE_FPS), _jr(TYPING_MAX_SECONDS * fps))


def _num_or(value, default: float) -> float:
    v = _number(value)
    return default if v is None else v


def look_sounds(cues, *, fps: int, frames: int, text: str = "", value: Optional[float] = None,
                take: Optional[str] = None, default_frames: int = 0, voice_lufs=None, intensity: float = 1.0,
                gain: float = 1.0, master: float = 1.0, items: int = 0, locations: int = 0) -> List[dict]:
    """
    The sounds one look plays, as the renderer schedules them: [{name, from,
    frames, trim, loop, fade, volume, pitch}], `from` counted from the look's
    first frame, `trim` frames skipped at the file's head (a peak landing
    early), `frames` played. Nothing rings past the look: a sound running
    over its last frame is cut there and fades, a hit that would land in its
    last MIN_AUDIBLE frames does not play, and neither does a sound cut to
    less than that.
    """
    fps = int(fps or BASE_FPS)
    frames = int(frames or 0)
    if frames <= 0:
        return []
    s = fps / BASE_FPS
    voice = voice_level(voice_lufs)
    stretch = frames / default_frames if default_frames and default_frames > 0 else 1.0
    least = _jr(MIN_AUDIBLE * s)
    longest = _jr(MAX_SOUND_SECONDS * fps)
    trim_gain = max(0.0, _num_or(gain, 1.0))
    level_master = max(0.0, _num_or(master, 1.0))
    level_pack = max(0.0, _num_or(intensity, 1.0))
    out: List[dict] = []
    for cue in cues or []:
        if not isinstance(cue, dict) or not cue_live(cue, text, value):
            continue
        at0 = _num_or(cue.get("at"), 0.0)
        every = _num_or(cue.get("every"), 0.0)
        per = cue.get("count")
        if every <= 0:
            count = 1
        elif per in ("items", "locations"):
            count = max(0, min(MAX_REPEATS, int(items if per == "items" else locations)))
        else:
            count = max(1, min(MAX_REPEATS, int(math.floor(_num_or(per, 1.0)))))
        k = stretch if cue.get("scale") else 1.0
        until = _number(cue.get("until"))
        typing = cue.get("kind") == "typing"
        for r in range(count):
            at = _jr((at0 + r * every) * s * k)
            name = (take if typing and take else None) or resolve_sound(cue.get("name"), cue.get("alt"))
            if not name:
                continue
            file_frames = _file_frames(name, fps)
            loops = loopable(name)
            if typing:
                start, trim = at, 0
                want = _jr(until * s * k) - at if until is not None else typing_span(text, fps)
            else:
                align = cue.get("align") or ("start" if loops or until is not None else "peak")
                if until is None and align == "peak" and at >= frames - least:
                    continue                  # its hit would land as the look leaves
                raw = at - (_peak(name, fps) if align == "peak" else 0)
                start = max(0, raw)
                trim = start - raw
                want = _jr(until * s * k) - start if until is not None else file_frames - trim
            if start >= frames:
                continue
            natural = file_frames - trim
            if not loops:
                want = min(want, natural)
            want = min(want, longest)
            if want <= 0:
                continue
            n = min(want, frames - start)
            if n < want and n < least:
                continue                      # cut by the look's end to almost nothing
            looped = loops and n > natural
            fade_asked = _number(cue.get("fade"))
            if fade_asked is not None and fade_asked > 0:
                fade = _jr(fade_asked * s)
            else:
                fade = max(1, min(_jr(4 * s), n // 3)) if (n < natural or looped) else 0
            fade = min(fade, n)
            db = _num_or(cue.get("gain_db"), 0.0)
            vol = level(name, voice) * 10 ** (db / 20.0) * (1.0 if cue.get("fixed") else level_pack) \
                * trim_gain * level_master
            vol = _r4(min(cap(voice, name), max(0.0, vol)))
            if vol <= 0.001:
                continue
            pitch = _number(cue.get("pitch"))
            out.append({"name": name, "from": int(start), "frames": int(n), "trim": int(trim), "loop": bool(looped),
                        "fade": int(fade), "volume": vol, "pitch": pitch if pitch is not None and pitch > 0 else 1.0})
    out.sort(key=lambda x: x["from"])
    return out


def sfx_choice(overlay: dict, template: dict) -> Optional[str]:
    """
    The editor's pick for a look's sound: "none" silences it (the string
    "none" always), another name replaces its design with that one hit, None
    keeps the design (a resolved {name, volume} equal to the default included).
    """
    default = _default_name(template)
    raw = (overlay or {}).get("sfx")
    if isinstance(raw, dict):
        got = str(raw.get("name") or "")
        return got if got and got not in ("default", default) else None
    if isinstance(raw, str) and raw:
        if raw == "none":
            return "none"
        return raw if raw not in ("default", default) else None
    return None


def look_mode(template: Optional[dict], overlay: dict, built_in: bool = True) -> str:
    """
    How a look sounds: "own" (its component plays its own <Audio>), "self"
    (the component schedules its cues, useLookSound), "cues" (the registry
    design, LookSounds), "none". Registry designs play only on documents that
    carry them (built_in: doc.lookSounds); older ones keep their sfx rows.
    """
    if not template:
        return "none"
    d = template.get("defaults") or {}
    if plays_own_sound(template):
        return "own"
    choice = sfx_choice(overlay, template)
    if choice == "none":
        return "none"
    if d.get("soundTiming") == "look":
        return "self"
    if not built_in or not isinstance(d.get("sounds"), list):
        return "none"
    if choice:
        return "cues"
    text, value = str((overlay or {}).get("text") or ""), value_of(overlay)
    return "cues" if any(isinstance(c, dict) and cue_live(c, text, value) for c in d["sounds"]) else "none"


def entry_cues(template: dict, overlay: dict, mode: str) -> List[dict]:
    """The cues a look plays: its design, or the editor's one sound on its hit."""
    d = template.get("defaults") or {}
    choice = sfx_choice(overlay, template) if mode == "cues" else None
    if choice and choice != "none":
        at = _number(d.get("sfxAt"))
        return [{"name": choice, "at": at if at else DEFAULT_HIT}]
    return [c for c in (d.get("sounds") or []) if isinstance(c, dict)]


def look_entries(overlays: List[dict], scenes: List[dict]) -> List[dict]:
    """Every look of a document, as the renderer walks them: the overlays, then the full-screen animation scenes."""
    out = []
    for ov in overlays or []:
        if isinstance(ov, dict):
            out.append({"start": int(_num_or(ov.get("startFrame"), 0)),
                        "frames": int(_num_or(ov.get("durationInFrames"), 0)),
                        "template": templates.get(ov.get("template") or ""), "overlay": ov})
    for sc in scenes or []:
        if not isinstance(sc, dict) or (sc.get("media") or {}).get("type") != "animation":
            continue
        spec = sc.get("animation") if isinstance(sc.get("animation"), dict) else {}
        out.append({"start": int(_num_or(sc.get("startFrame"), 0)),
                    "frames": int(_num_or(sc.get("durationInFrames"), 0)),
                    "template": templates.get(spec.get("template") or ""),
                    "overlay": {**spec, "text": spec.get("text") or sc.get("text") or ""}})
    return out


def _protected_kind(template: dict) -> bool:
    """A typing or date look: alone on screen it keeps its sound over any rival (the rows' rule)."""
    cues = (template.get("defaults") or {}).get("sounds") or []
    if any(isinstance(c, dict) and (c.get("kind") == "typing" or c.get("fixed")) for c in cues):
        return True
    return bool(set(template.get("cues") or []) & _DATE_CUES) or template.get("component") in PROTECTED_COMPONENTS


def plan_looks(entries: List[dict], fps: int, built_in: bool = True) -> List[dict]:
    """
    The document's one pass over its looks, as Main.tsx makes it: each look's
    mode, whether it is muted (of two looks starting within CLASH_SECONDS only
    the stronger sounds: emphasis, then a typing or date look alone on screen,
    then the first), and the typing take it plays (the owner's keyboards in turn).
    """
    fps = int(fps or BASE_FPS)
    clash = _jr(CLASH_SECONDS * fps)
    states = [{"mode": look_mode(e.get("template"), e.get("overlay") or {}, built_in), "muted": False, "take": None}
              for e in entries]
    spans = [(int(e["start"]), int(e["start"]) + max(1, int(e["frames"]))) for e in entries]

    def alone(i: int) -> bool:
        a, b = spans[i]
        return not any(j != i and spans[j][0] < b and a < spans[j][1] for j in range(len(spans)))

    def rank(i: int) -> tuple:
        t = entries[i].get("template") or {}
        ov = entries[i].get("overlay") or {}
        emph = ov.get("emphasis") if ov.get("emphasis") in _RANK else t.get("emphasis")
        protected = _protected_kind(t) and alone(i)
        return _RANK.get(emph, 1), 0 if protected else 1, spans[i][0], i

    order = sorted((i for i, s in enumerate(states) if s["mode"] in ("cues", "self")), key=lambda i: (spans[i][0], i))
    kept: List[int] = []
    for i in order:
        rival = next((k for k in kept if abs(spans[i][0] - spans[k][0]) <= clash), None)
        if rival is None:
            kept.append(i)
        elif rank(i) < rank(rival):
            kept[kept.index(rival)] = i
            states[rival]["muted"] = True
        else:
            states[i]["muted"] = True
    takes = [t for t in TYPING_TAKES if shipped(t)]
    n = 0
    for i in order:
        st = states[i]
        if st["muted"] or st["mode"] != "cues" or not takes:
            continue
        cues = entry_cues(entries[i]["template"], entries[i].get("overlay") or {}, st["mode"])
        if any(c.get("kind") == "typing" for c in cues):
            st["take"] = takes[n % len(takes)]
            n += 1
    return states


def look_sounds_on(doc: dict) -> bool:
    """Whether a document's looks play their built-in sounds (doc.lookSounds present: an object, or true)."""
    v = (doc or {}).get("lookSounds")
    return isinstance(v, dict) or v is True


def doc_look_sounds(doc: dict, built_in: Optional[bool] = None) -> List[dict]:
    """
    Every sound the renderer's looks will play in a document, in absolute
    frames: [{name, startFrame, from, frames, trim, loop, fade, volume, pitch,
    look}] (`look` = the index in look_entries). Self-timed looks count with
    their registry design (their component's exact frames depend on the drawing).
    """
    fps = int(doc.get("fps") or BASE_FPS)
    if built_in is None:
        built_in = look_sounds_on(doc)
    if doc.get("sfxEnabled") is False:
        return []
    entries = look_entries(doc.get("overlays") or [], doc.get("scenes") or [])
    states = plan_looks(entries, fps, built_in)
    settings = doc.get("lookSounds") if isinstance(doc.get("lookSounds"), dict) else {}
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    out: List[dict] = []
    for idx, (e, st) in enumerate(zip(entries, states)):
        if st["muted"] or st["mode"] not in ("cues", "self"):
            continue
        t, ov = e["template"], e.get("overlay") or {}
        d = t.get("defaults") or {}
        for snd in look_sounds(entry_cues(t, ov, st["mode"]), fps=fps, frames=e["frames"],
                               text=str(ov.get("text") or ""), value=value_of(ov), take=st["take"],
                               default_frames=_jr(_num_or(d.get("duration"), 0.0) * fps),
                               voice_lufs=meta.get("voiceLufs"),
                               intensity=_num_or(settings.get("intensity"), 1.0),
                               gain=_num_or(ov.get("soundGain"), 1.0),
                               master=_num_or(doc.get("sfxVolume"), 1.0),
                               items=len(ov["items"]) if isinstance(ov.get("items"), list) else 0,
                               locations=len(ov["locations"]) if isinstance(ov.get("locations"), list) else 0):
            out.append({**snd, "startFrame": e["start"] + snd["from"], "look": idx})
    out.sort(key=lambda x: (x["startFrame"], x["look"]))
    return out


def builtin_busy(overlays: List[dict], scenes: List[dict], fps: int) -> List[dict]:
    """The looks' own sounds as sfx-row shapes ({name, startFrame, durationFrames}), to keep other sounds clear."""
    doc = {"fps": fps, "overlays": overlays, "scenes": scenes, "lookSounds": {}}
    return [{"name": s["name"], "startFrame": s["startFrame"], "durationFrames": s["frames"], "kind": "look"}
            for s in doc_look_sounds(doc, built_in=True)]


def sound_levels() -> dict:
    """The level and timing constants the renderer's twin reads (registry.json "soundLevels")."""
    return {
        "refLufs": SFX_REF_LUFS, "voiceDefault": VOICE_LUFS_DEFAULT, "underDefault": UNDER_VOICE_DB,
        "capUnder": CAP_UNDER_DB, "capUnderCategory": dict(CAP_UNDER_CATEGORY_DB),
        "categoryUnder": dict(CATEGORY_UNDER_DB), "nameCategory": dict(CATEGORY),
        "categoryFallback": {k: list(v) for k, v in CATEGORY_FALLBACK.items()}, "loopNames": sorted(LOOP_NAMES),
        "typingTakes": list(TYPING_TAKES), "typeStart": TYPE_START, "typingMaxSeconds": TYPING_MAX_SECONDS,
        "maxSeconds": MAX_SOUND_SECONDS, "minAudible": MIN_AUDIBLE, "clashSeconds": CLASH_SECONDS,
        "defaultHit": DEFAULT_HIT, "maxRepeats": MAX_REPEATS, "dateCues": sorted(_DATE_CUES),
        "protectedComponents": list(PROTECTED_COMPONENTS),
    }
