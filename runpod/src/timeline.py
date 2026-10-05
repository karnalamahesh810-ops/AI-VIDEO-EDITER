"""
The timeline document: the contract between worker, renderer and UI.

One JSON shape does three jobs. The worker writes it, Remotion renders it, and
the ThumbGenius editor reads and mutates it — so a user edit is just a changed
document sent back to `render`. That is what makes the plan/edit/render loop
possible without a second data model.

`validate()` is the gate in front of the renderer. It runs on documents the
worker built AND on documents that came back from the browser after editing,
so it assumes nothing about where a field came from. A render is minutes of
GPU time; failing here with a sentence the UI can show beats failing inside
headless Chrome with a stack trace.
"""
import math
import os
import re
import subprocess
import zlib
from typing import Any, Dict, List, Optional, Tuple

from . import config, hookboost, sfxplan, templates
from .director import TEMPLATES
from .transcribe import Segment
from .media import MediaAsset

SCHEMA_VERSION = 2

# Stills need movement or they read as a stalled video. Cycled rather than
# random so a re-plan of the same script produces the same document. The
# n-th still of the video takes the n-th move (not the scene index), so two
# stills in a row never move alike; neighbours in the list also differ in
# kind (a push is followed by a slide, a drift, a turn - never another push).
# The moves are drawn by remotion/src/transitions/stillMotion.tsx.
_IMAGE_MOTIONS = ["push-offcenter", "reveal-left", "drift-diagonal", "pull-back", "parallax",
                  "zoom-in", "rotate-settle", "reveal-right", "pan-left", "push-rotate",
                  "zoom-out", "pan-right"]

# Scene entrances and per-clip effects. Both lists are a contract with
# remotion/src/types.ts (SceneTransition / SceneEffect) and SceneEffects.tsx;
# a test asserts they agree.
TRANSITIONS = {"none", "fade", "film-burn", "zoom", "glitch", "slide",
               "whip", "flash", "light-leak", "dip", "blur", "punch",
               "split-wipe", "bar-wipe", "mosaic", "color-wash",
               # Editor cut transitions that straddle the cut (remotion/src/transitions).
               "whip-pan", "zoom-punch", "shake-cut", "blur-dissolve", "luma-fade",
               "chromatic-flash", "vhs-glitch",
               # A true cross-dissolve: the outgoing shot plays on under the
               # incoming one as it fades in (news-compilation style).
               "crossfade"}
EFFECTS = {"none", "ken-burns", "light-leaks", "dust", "film-flicker", "color-shift"}

# The rotation used before transitions were planned by style; kept for any
# caller that still reads it.
_TRANSITION_CYCLE = ["film-burn", "whip", "flash", "zoom", "light-leak", "slide",
                     "dip", "punch", "glitch", "blur", "fade"]

# How a style cuts. A documentary editor mostly hard-cuts and marks a change
# of section with something soft (~1 cut in 6 at most); a news, compilation or
# trending edit punctuates more (~1 cut in 3-4) with energetic transitions.
#   cycle   - the transitions in turn; neighbours never look alike
#   chapter - what a chapter / title card change gets
#   gap     - fewest cuts from one transition to the next (>= 3: never on
#             consecutive cuts)
#   force   - after this many plain cuts a transition goes in even without a
#             section change (0: only at section changes)
STYLES = ("documentary", "history", "story", "news", "compilation", "trending", "explainer", "weather",
          "crossfade")
_STYLE_TRANSITIONS = {
    "documentary": {"cycle": ["light-leak", "blur-dissolve", "luma-fade", "film-burn"],
                    "chapter": "light-leak", "gap": 6, "force": 0},
    "history": {"cycle": ["film-burn", "blur-dissolve", "light-leak", "luma-fade"],
                "chapter": "film-burn", "gap": 6, "force": 0},
    "story": {"cycle": ["blur-dissolve", "light-leak", "luma-fade", "film-burn"],
              "chapter": "luma-fade", "gap": 6, "force": 0},
    "explainer": {"cycle": ["blur-dissolve", "whip-pan", "luma-fade", "zoom-punch", "light-leak"],
                  "chapter": "luma-fade", "gap": 5, "force": 0},
    "weather": {"cycle": ["whip-pan", "flash", "blur-dissolve", "zoom-punch", "luma-fade", "glitch"],
                "chapter": "flash", "gap": 4, "force": 6},
    "news": {"cycle": ["whip-pan", "flash", "zoom-punch", "glitch", "shake-cut", "chromatic-flash"],
             "chapter": "flash", "gap": 3, "force": 4},
    "compilation": {"cycle": ["whip-pan", "glitch", "zoom-punch", "chromatic-flash", "shake-cut",
                              "vhs-glitch", "flash"],
                    "chapter": "chromatic-flash", "gap": 3, "force": 4},
    "trending": {"cycle": ["zoom-punch", "chromatic-flash", "whip-pan", "vhs-glitch", "shake-cut",
                           "flash", "glitch"],
                 "chapter": "chromatic-flash", "gap": 3, "force": 4},
}
# The style a style pack or a story kind implies when the job names none.
_PACK_STYLE = {"documentary": "documentary", "history": "history", "news": "news", "weather": "weather",
               "tech": "explainer", "cinematic": "story", "minimal": "documentary",
               "youtube_modern": "trending"}
_KIND_STYLE = {"news": "news", "weather": "weather", "disaster": "weather", "history": "history",
               "biography": "history", "science": "explainer", "explainer": "explainer"}

# A transition needs room: the incoming shot must hold long enough to settle
# and the outgoing one to start its half (frames).
_MIN_IN_FRAMES = 9
_MIN_OUT_FRAMES = 6

# The sound a transition makes, and how far under the voice its loudest point
# sits (dB; src/sfxplan.py turns that into a gain against the measured
# narration). Its loudest point (sfx_meta.json "peak") lands on the cut. A
# transition is punctuation, not a moment: each sits at or under its
# sound's own category level, never closer to the voice than the ceiling
# (sfxplan.cap: 6 dB, a glitch 9 - the owner, 2026-10-01: the transition
# sounds stood over the narration, the glitches most), the soft dissolves
# quietest - a whisper of air; a dip through black is silent.
# The sound designer's premium set (2026-09-30): a whip is a fast whoosh, a
# zoom punch lands its thump on the cut, a light leak or film burn shimmers,
# a flash pops; the owner's glitch and deep hit stay.
_TRANSITION_SFX = {
    "glitch": ("glitch-pro", 9.0), "vhs-glitch": ("glitch-short-v2", 9.5),
    "flash": ("camera-flash-pop", 7.0), "chromatic-flash": ("camera-flash-pop", 7.0),
    "whip-pan": ("whoosh-fast", 9.0), "zoom-punch": ("zoom-in-whoosh", 9.5),
    "film-burn": ("light-shimmer", 10.0), "light-leak": ("light-shimmer", 11.0),
    "blur-dissolve": ("whoosh-soft-v2", 11.0), "shake-cut": ("hit-deep", 7.0),
    # The older entrances an editor can still pick.
    "whip": ("whoosh-fast", 9.5), "punch": ("zoom-in-whoosh", 10.0), "zoom": ("whoosh-soft-v2", 11.0),
    "slide": ("ui-swipe", 11.0), "mosaic": ("glitch-short-v2", 11.0),
}
# The older file a transition plays while its premium one does not ship.
_TRANSITION_ALT = {"glitch-short-v2": "glitch-short", "camera-flash-pop": "flash-hit", "whoosh-fast": "swipe",
                   "zoom-in-whoosh": "swipe", "light-shimmer": "whoosh-soft", "whoosh-soft-v2": "whoosh-soft",
                   "ui-swipe": "whoosh-soft"}
# Another sound this close (seconds) to a transition's sound silences the transition's.
_TRANSITION_SFX_CLEARANCE = 1.0

# Used when public/sfx/sfx_meta.json cannot be read (duration, peak seconds).
_SFX_META_FALLBACK = {
    "glitch-short": {"duration": 0.5, "peak": 0.175}, "flash-hit": {"duration": 0.62, "peak": 0.075},
    "glitch-pro": {"duration": 0.48, "peak": 0.01}, "hit-deep": {"duration": 2.319, "peak": 0.02},
    "swipe": {"duration": 0.44, "peak": 0.195}, "whoosh-soft": {"duration": 1.12, "peak": 0.419},
    "boom-soft": {"duration": 1.71, "peak": 0.309},
    "glitch-short-v2": {"duration": 0.35, "peak": 0.02}, "camera-flash-pop": {"duration": 0.2, "peak": 0.01},
    "whoosh-fast": {"duration": 0.223, "peak": 0.055}, "zoom-in-whoosh": {"duration": 0.543, "peak": 0.381},
    "light-shimmer": {"duration": 1.127, "peak": 0.449}, "whoosh-soft-v2": {"duration": 0.798, "peak": 0.125},
    "ui-swipe": {"duration": 0.445, "peak": 0.18},
}
_SFX_META_CACHE: Dict[str, Any] = {}


def sfx_meta() -> Dict[str, Dict[str, float]]:
    """{name: {"duration": s, "peak": s}} for every sound file (public/sfx/sfx_meta.json)."""
    path = os.path.join(templates.SFX_DIR, "sfx_meta.json")
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return dict(_SFX_META_FALLBACK)
    if _SFX_META_CACHE.get("stamp") != stamp:
        try:
            import json
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            _SFX_META_CACHE.update(stamp=stamp, data={**_SFX_META_FALLBACK, **(data or {})})
        except (OSError, ValueError):
            return dict(_SFX_META_FALLBACK)
    return _SFX_META_CACHE["data"]


# --------------------------------------------------------------------------- #
# The voice's level: every sound and the music are set against it
# --------------------------------------------------------------------------- #

VOICE_MEASURE_TIMEOUT = 240          # seconds; a 30-minute mp3 measures in well under a minute
_VOICE_CACHE: Dict[tuple, Optional[float]] = {}
_LUFS_LINE = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.M)


def measure_lufs(path: str) -> Optional[float]:
    """
    The integrated loudness (EBU R128, ffmpeg's ebur128) of a local audio
    file, measured once per file; None when it cannot be read or is silence.
    """
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
    if key in _VOICE_CACHE:
        return _VOICE_CACHE[key]
    value = None
    # framelog=quiet keeps a long file's per-frame log out of the pipe; an
    # ffmpeg without the option measures the plain way.
    for af in ("ebur128=framelog=quiet", "ebur128"):
        try:
            p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af", af, "-f", "null", "-"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=VOICE_MEASURE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            break
        found = _LUFS_LINE.findall(p.stderr or "")
        if found:
            v = float(found[-1])             # the summary's integrated loudness is the last I:
            value = v if -70.0 < v < 0.0 else None
            break
    _VOICE_CACHE[key] = value
    return value


def narration_file(audio_url: str, inp: Dict[str, Any], narration_path: str = "") -> str:
    """
    The narration as a file on this worker's disk, or "": the caller's path,
    the document's audio when it is a local file, the job's audio_path, or
    the copy the handler downloaded (<WORK_DIR>/<job id>/narration.mp3). A
    signed URL is never downloaded again just to be measured.
    """
    candidates = [narration_path, audio_url, (inp or {}).get("audio_path")]
    job = str((inp or {}).get("_job_id") or "")
    if job and "/" not in job and "\\" not in job and ".." not in job:
        candidates.append(os.path.join(config.WORK_DIR, job, "narration.mp3"))
    for c in candidates:
        c = str(c or "")
        if c.startswith("file://"):
            c = c[len("file://"):]
        if c and "://" not in c and os.path.isfile(c):
            return c
    return ""


def voice_loudness(audio_url: str, inp: Dict[str, Any], narration_path: str = "") -> tuple:
    """
    (LUFS, how it was found: "measured" | "given" | "assumed"). A job may
    pin it (inp["voice_lufs"]); else the local narration is measured once;
    else sfxplan.VOICE_LUFS_DEFAULT is assumed.
    """
    given = (inp or {}).get("voice_lufs")
    if isinstance(given, (int, float)) and not isinstance(given, bool) and -60.0 < float(given) < 0.0:
        return float(given), "given"
    path = narration_file(audio_url, inp, narration_path)
    value = measure_lufs(path) if path else None
    if value is not None:
        return value, "measured"
    if (inp or {}).get("_job_id"):
        # Said out loud in a job's log: an unmeasured voice levels every sound against a guess.
        print(f"[worker] narration loudness not measured ({'no local file' if not path else 'unreadable'}); "
              f"assuming {sfxplan.VOICE_LUFS_DEFAULT} LUFS", flush=True)
    return sfxplan.VOICE_LUFS_DEFAULT, "assumed"


VOICE_URL_TIMEOUT = 90               # seconds to read a narration over the network at render time


def measure_lufs_url(url: str, timeout: float = VOICE_URL_TIMEOUT) -> Optional[float]:
    """The integrated loudness of a narration at an http(s) link (ffmpeg reads it); None when it cannot."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    try:
        # rw_timeout (microseconds): a stalled read gives up instead of holding the render.
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-rw_timeout", "20000000", "-i", url, "-vn",
                            "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    found = _LUFS_LINE.findall(p.stderr or "")
    v = float(found[-1]) if found else None
    return v if v is not None and -70.0 < v < 0.0 else None


def relevel_to_voice(doc: Dict[str, Any], measure=None) -> bool:
    """
    A document planned against a voice nobody measured (meta.voiceLufsSource
    "assumed"): measure the narration now (doc.audio.url, `measure` =
    measure_lufs_url) and level the sounds to it. The looks'
    own sounds and the pack clips follow meta.voiceLufs in the renderer; the
    planned rows (sfx kind "transition" / "overlay") and the pack scenes'
    transitionGain come down by the difference when the voice is quieter
    than assumed (never raised). The editor's own rows stay as set, held
    under the ceilings by cap_sfx_levels. Returns whether the voice was measured.
    """
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else None
    if meta is None or not isinstance(doc.get("audio"), dict) or meta.get("voiceLufsSource") != "assumed":
        return False
    known = meta.get("voiceLufs")
    got = (measure or measure_lufs_url)(str(doc["audio"].get("url") or ""))
    if got is None:
        return False
    planned = sfxplan.voice_level(known)
    meta["voiceLufs"] = round(float(got), 1)
    meta["voiceLufsSource"] = "measured"
    meta["voiceLufsPlanned"] = round(planned, 1)
    drop = float(got) - planned
    if drop < 0:
        k = 10 ** (drop / 20.0)
        for fx in doc.get("sfx") or []:
            v = fx.get("volume") if isinstance(fx, dict) else None
            if fx.get("kind") in ("transition", "overlay", "riser") and isinstance(v, (int, float)) \
                    and not isinstance(v, bool):
                fx["volume"] = round(float(v) * k, 3)
        for sc in doc.get("scenes") or []:
            g = sc.get("transitionGain") if isinstance(sc, dict) else None
            if isinstance(g, (int, float)) and not isinstance(g, bool):
                sc["transitionGain"] = round(float(g) * k, 3)
        # The ambience beds were set against the same voice (src/ambience.py).
        amb = doc.get("ambience") if isinstance(doc.get("ambience"), dict) else {}
        for bed in amb.get("beds") or []:
            for key in ("volume", "ceiling"):
                v = bed.get(key) if isinstance(bed, dict) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bed[key] = round(float(v) * k, 4)
    cap_sfx_levels(doc)
    print(f"[worker] narration measured at render: {got:.1f} LUFS (planned against {planned:.1f})", flush=True)
    return True


def cap_sfx_levels(doc: Dict[str, Any]) -> int:
    """
    Hold every sound of a document under the voice-relative cap (sfxplan.cap
    against doc.meta.voiceLufs, lowered by a master sfxVolume above 1). The
    editor's sliders write absolute volumes up to 1.0 straight into
    doc["sfx"]; this is where they come back into line. Returns how many were lowered.
    """
    sfx = doc.get("sfx") if isinstance(doc, dict) else None
    if not isinstance(sfx, list):
        return 0
    voice = (doc.get("meta") or {}).get("voiceLufs") if isinstance(doc.get("meta"), dict) else None
    lowered = 0
    for fx in sfx:
        if not isinstance(fx, dict):
            continue
        v = fx.get("volume")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        # Each sound under its own ceiling: a glitch further under the voice.
        held = sfxplan.clamp(v, voice, doc.get("sfxVolume", 1.0), name=str(fx.get("name") or ""))
        if held < v - 1e-9:
            fx["volume"] = round(held, 3)
            lowered += 1
    return lowered


def transition_style(inp: Optional[Dict[str, Any]] = None, pack: Optional[dict] = None,
                     brief: Optional[dict] = None) -> str:
    """The cutting style: the job's `style`, else its style pack's, else the story kind's."""
    inp = inp or {}
    asked = str(inp.get("style") or "").strip().lower()
    if asked in _STYLE_TRANSITIONS or asked == "crossfade":
        return asked
    pack_id = str((pack or {}).get("id") or inp.get("style_pack") or "").strip().lower()
    if pack_id in _PACK_STYLE:
        return _PACK_STYLE[pack_id]
    if pack_id in _STYLE_TRANSITIONS:
        return pack_id
    return _KIND_STYLE.get(str((brief or {}).get("kind") or "").lower(), "documentary")

# One effect per clip, weighted roughly like VidRush's own distribution
# (colour 37, Ken Burns 34, light leaks 29, flicker 21, dust 15 per 160 clips).
_EFFECT_CYCLE = ["color-shift", "ken-burns", "light-leaks", "color-shift",
                 "film-flicker", "ken-burns", "dust", "light-leaks"]

# Fewest cuts between two transitions. Transitions are punctuation; on every
# cut they read as an amateur edit.
_MIN_TRANSITION_GAP = 3


# The music that ships with the renderer (remotion/public/bgm/<track>.mp3),
# chosen by the story's kind when the job names no track. "bgm://<track>" is
# resolved by the renderer to its bundled file and loops under the narration.
# The owner's full-length tracks (added 2026-09-28) come first; the original
# 12-minute beds (<genre>.mp3) stay for projects that already name them.
# The owner's own tracks (re-exported from CapCut, 2026-10-01; the old 12-min
# beds were removed): investigative 30 / 20 min, suspense 30 min, crime 30 min.
BGM_TRACKS = {
    "investigative": (("investigative-v5", 1800), ("investigative-20m", 1199)),
    "suspense": (("suspense-v2", 1800),),
    "crime": (("crime-v1", 1800),),
}
BGM_GENRES = tuple(BGM_TRACKS)
# The beds those tracks replaced: a document planned before 2026-10-01 still
# names them, and the missing file failed its whole re-render.
BGM_RENAMED = {"investigative": "investigative-v5", "suspense": "suspense-v2", "crime": "crime-v1"}


def current_bgm_url(url: str) -> str:
    """ "bgm://investigative" (a removed bed) -> "bgm://investigative-v5"; anything else unchanged."""
    if isinstance(url, str) and url.startswith("bgm://"):
        name = url[len("bgm://"):]
        return "bgm://" + BGM_RENAMED.get(name, name)
    return url
# The mood of the music follows the story (the owner, 2026-09-30: music in
# every style, picked by mood): tense for news, weather and disasters, a true-
# crime bed when the story is about a crime, the calm investigative bed for a
# documentary (history, biography, science, explainers).
_BGM_BY_KIND = {"news": "suspense", "weather": "suspense", "disaster": "suspense",
                "history": "investigative", "biography": "investigative", "science": "investigative",
                "explainer": "investigative", "nature": "investigative", "other": "investigative"}
# Moods an editor or a job may name, as the bundled genre that plays them.
_BGM_MOODS = {"documentary": "investigative", "calm": "investigative", "tension": "suspense", "tense": "suspense",
              "news": "suspense", "dramatic": "suspense", "true-crime": "crime", "true_crime": "crime",
              "mystery": "crime", "dark": "crime"}
# A story told around a crime (at least CRIME_HITS of these words) gets the crime bed.
_CRIME_WORDS = re.compile(r"\b(murder(?:s|ed|er|ers)?|homicides?|killers?|serial killer|detectives?|"
                          r"police (?:said|say|found|arrested)|arrest(?:ed|s)?|suspects?|convicted|prison|"
                          r"kidnapp(?:ed|ing)|heist|robbery|cartel|gang|trial|jury|verdict|crime scene|"
                          r"true crime|investigators)\b", re.I)
CRIME_HITS = 3
# Integrated loudness of the bundled tracks (EBU R128 over the whole file,
# measured 2026-10-01 on the owner's CapCut re-exports). They come quiet
# (-30.6 to -35.5 LUFS), so under a loud narration even full gain left them
# far down; each file is raised by a fixed gain to about -27 LUFS (peaks -12
# to -17 dBFS, no limiting). A job's own track is assumed to be a normal release.
BGM_LUFS = {"investigative-v5": -26.9, "investigative-20m": -26.9, "suspense-v2": -27.0, "crime-v1": -26.9}
BGM_LUFS_UNKNOWN = -14.0


def _bgm_track(genre: str, seconds: float, seed: str) -> str:
    """
    A track of the genre long enough to play under the whole narration without
    looping (else the longest ones, which repeat with a crossfade the fewest
    times - a 40-minute narration could draw the 20-minute track and hear it
    start over twice), varied between projects by a stable seed. (The list
    used to end with a 12-minute bed that was skipped here; those were removed
    with the owner's new tracks, 2026-10-01.)
    """
    tracks = BGM_TRACKS[genre]
    longest = max(length for _, length in tracks)
    long_enough = ([name for name, length in tracks if length >= seconds]
                   or [name for name, length in tracks if length == longest])
    return long_enough[zlib.crc32(seed.encode("utf-8")) % len(long_enough)]


def bgm_mood(brief: Optional[dict], story_text: str = "") -> str:
    """The bundled genre for a story: crime when it is told around a crime, else by its kind."""
    blob = " ".join([str((brief or {}).get("summary") or ""), str((brief or {}).get("event") or ""), story_text or ""])
    if len(_CRIME_WORDS.findall(blob)) >= CRIME_HITS:
        return "crime"
    return _BGM_BY_KIND.get(str((brief or {}).get("kind") or ""), "investigative")


def _bgm_for(inp: Dict[str, Any], pack: Optional[dict], brief: Optional[dict],
             seconds: float = 0.0, story_text: str = "") -> Optional[dict]:
    """
    The music under the video: the job's own track, else a bundled one picked
    by the story's mood and long enough to run under the whole narration
    (the renderer loops it when the video is longer). Every style has music;
    only the job's own "bgm": false turns it off. `pack` is unused (music
    no longer depends on the graphics planner).
    """
    if inp.get("bgm_url"):
        return {"url": str(inp["bgm_url"]), "volume": float(inp.get("bgm_volume", 0.12)), "loop": True}
    if not inp.get("bgm", config.BGM_AUTO):
        return None
    asked = str(inp.get("bgm_genre") or "").strip().lower()
    genre = _BGM_MOODS.get(asked, asked) or bgm_mood(brief, story_text)
    names = {name for tracks in BGM_TRACKS.values() for name, _ in tracks}
    track = str(inp.get("bgm_track") or "")
    # The editor's music list names tracks ("investigative-v5") in bgm_genre; a
    # plain genre ("investigative") still means "the best track of that genre".
    if not track and genre in names and genre not in BGM_GENRES:
        track = genre
    if track in names:
        genre = next(g for g, tracks in BGM_TRACKS.items() if any(n == track for n, _ in tracks))
    elif track in BGM_GENRES:
        # The removed 12-minute beds were named like their genre ("crime"):
        # a document naming one plays that genre's current track.
        genre = track
    if genre not in BGM_GENRES:
        genre = "investigative"
    seed = str(inp.get("project_id") or inp.get("title") or "")
    if track not in names:
        track = _bgm_track(genre, seconds, seed)
    # The brand kit's music (only when the job chose none itself): its tracks
    # and genres only - the story's mood picks among them, the nearest genre
    # when its own is not liked; "none" is no music at all.
    from . import brandkit
    liked = brandkit.music_limit(inp)
    if liked == brandkit.NONE:
        return None
    if liked:
        genre, track = brandkit.pick_music(genre, track, seconds, liked, seed)
    length = next((n for tracks in BGM_TRACKS.values() for name, n in tracks if name == track), 0)
    return {"url": f"bgm://{track}", "volume": float(inp.get("bgm_volume", 0.12)), "genre": genre,
            "track": track, "trackSeconds": length,
            # Main.tsx loops the track, so a video longer than it still has music to the end.
            "loop": True}


# ------------------------------------------------------------------ music levels
# The owner (2026-09-30): music under every video, the whole way through,
# ducked under the voice like a sidechain: ~18 dB under it while it speaks,
# up a little in a pause longer than 1.2 s, in over the first 1.5 s and out
# over the last 3 s. The renderer (Main.tsx makeMusicVolume) reaches each
# music section's level 1.5 s after the section starts and multiplies a
# per-word duck on top; the plan below switches that duck off (1.0) and
# writes the whole automation as sections.
MUSIC_UNDER_VOICE_DB = 18.0
MUSIC_PAUSE_SECONDS = 1.2
MUSIC_PAUSE_RISE_DB = 3.0
MUSIC_FADE_IN = 1.5
MUSIC_FADE_OUT = 3.0
MUSIC_RAMP = 1.5            # Main.tsx: a section's level is reached this long after it starts
MUSIC_RELEASE = 0.1         # the rise starts this long after the last word before a pause
MUSIC_BACK_EARLY = 1.2      # ... and the level heads back down this long before the next word
MUSIC_MAX_RISES = 160       # the longest pauses first: a long video stays cheap to render
MUSIC_MOOD_REF = 0.12       # the registry's mood levels (musicMoods) are relative to this
_MOOD_DB_LIMIT = 4.0


def _speech_spans(segments: List[Segment]) -> List[tuple]:
    """(start, end) seconds of every spoken word, in order (the lines themselves when there are no word timings)."""
    spans = [(float(w.start), float(w.end)) for s in segments for w in (getattr(s, "words", None) or [])
             if getattr(w, "end", None) is not None and getattr(w, "start", None) is not None]
    if not spans:
        spans = [(float(s.start), float(s.end)) for s in segments]
    return sorted(spans)


def music_flat(music: Optional[dict], bgm: Optional[dict], fps: int, total: int, voice_lufs: float,
               level: float) -> dict:
    """
    The music at one level under the whole video (the editor's Music volume),
    x config.MUSIC_DUCK while a word is spoken, faded in from silence at the
    start and out at the end: the owner's approved Lake Powell mix (20%,
    2026-10-01). Same shape as music_automation's result.
    """
    music = dict(music or {})
    fps = int(fps or 30)
    total = max(1, int(total))
    level = round(max(0.0, min(1.0, float(level))), 4)
    mood = str(((music.get("sections") or [{}])[0] or {}).get("mood") or (bgm or {}).get("genre") or "")
    fade_out = max(2, total - int(round(MUSIC_FADE_OUT * fps)))
    fade_half = max(fade_out + 1, total - int(round(MUSIC_RAMP * fps)))
    out = [{"startFrame": 0, "volume": 0.0, "mood": mood, "kind": "fade-in"},
           {"startFrame": 1, "volume": level, "mood": mood, "kind": "voice"},
           {"startFrame": fade_out, "volume": round(level / 2, 4), "mood": mood, "kind": "fade-out"},
           {"startFrame": fade_half, "volume": 0.0, "mood": mood, "kind": "fade-out"}]
    for k, s in enumerate(out):
        s["endFrame"] = max(s["startFrame"] + 1, out[k + 1]["startFrame"] if k + 1 < len(out) else total)
    track_lufs = BGM_LUFS.get(str((bgm or {}).get("track") or ""), BGM_LUFS_UNKNOWN)
    return {**music, "sections": out, "duck": round(max(0.0, min(1.0, float(config.MUSIC_DUCK))), 3),
            "levels": {"voiceLufs": round(float(voice_lufs), 1), "trackLufs": track_lufs, "mode": "flat",
                       "speech": level}}


def music_automation(music: Optional[dict], bgm: Optional[dict], segments: List[Segment], fps: int, total: int,
                     voice_lufs: float, level: Optional[float] = None) -> dict:
    """
    The music's level over the whole video as renderer sections (see the
    constants above). Under speech the bed plays at the gain that puts the
    track MUSIC_UNDER_VOICE_DB under the voice (BGM_LUFS; a job's own track
    is assumed a normal release), the section's mood a few dB either way.
    `level` (a job's bgm_volume) trims that: MUSIC_MOOD_REF (0.12, the old
    default) is the automatic level, twice it is 6 dB louder. The renderer
    never goes above 1.0, so a very quiet track sits as close under the voice
    as it can.
    """
    music = dict(music or {})
    fps = int(fps or 30)
    total = max(1, int(total))
    moods = [s for s in (music.get("sections") or []) if isinstance(s, dict)]
    if not moods:
        moods = [{"startFrame": 0, "endFrame": total, "mood": "EXPLANATION", "volume": MUSIC_MOOD_REF}]
    moods = sorted(moods, key=lambda s: int(s.get("startFrame", 0)))
    track_lufs = BGM_LUFS.get(str((bgm or {}).get("track") or ""), BGM_LUFS_UNKNOWN)
    base_db = float(voice_lufs) - MUSIC_UNDER_VOICE_DB - track_lufs
    rise = 10 ** (MUSIC_PAUSE_RISE_DB / 20.0)

    def speech_gain(section: dict) -> float:
        try:
            ratio = float(section.get("volume") or MUSIC_MOOD_REF) / MUSIC_MOOD_REF
        except (TypeError, ValueError):
            ratio = 1.0
        mood_db = max(-_MOOD_DB_LIMIT, min(_MOOD_DB_LIMIT, 20 * math.log10(max(ratio, 1e-3))))
        g = 10 ** ((base_db + mood_db) / 20.0)
        if level is not None:
            g *= max(0.0, float(level)) / MUSIC_MOOD_REF
        return max(0.0, min(1.0, g))

    def mood_at(frame: int) -> dict:
        at = moods[0]
        for s in moods:
            if int(s.get("startFrame", 0)) <= frame:
                at = s
        return at

    fade_out = max(2, total - int(round(MUSIC_FADE_OUT * fps)))
    fade_half = max(fade_out + 1, total - int(round(MUSIC_RAMP * fps)))
    out: List[dict] = [{"startFrame": 0, "volume": 0.0, "mood": str(moods[0].get("mood") or ""), "kind": "fade-in"}]
    for k, s in enumerate(moods):
        # The music starts with the picture (from silence at frame 0), not with the first word.
        start = 1 if k == 0 else max(1, int(s.get("startFrame", 0)))
        if start < fade_out:
            out.append({"startFrame": start, "volume": round(speech_gain(s), 4), "mood": str(s.get("mood") or ""),
                        "kind": "voice"})
    # A pause longer than MUSIC_PAUSE_SECONDS: up a little, back down by the next word.
    spoken = _speech_spans(segments)
    pauses = []
    for (a0, a1), (b0, _b1) in zip(spoken, spoken[1:]):
        if b0 - a1 > MUSIC_PAUSE_SECONDS:
            pauses.append((a1, b0))
    if spoken and total / fps - spoken[-1][1] > MUSIC_PAUSE_SECONDS:
        pauses.append((spoken[-1][1], None))           # the voice has finished: the music may come up
    longest = sorted(pauses, key=lambda p: -((p[1] if p[1] is not None else total / fps) - p[0]))
    pauses = sorted(longest[:MUSIC_MAX_RISES], key=lambda p: p[0])
    for end, nxt in pauses:
        up = int(round((end + MUSIC_RELEASE) * fps))
        down = int(round((nxt - MUSIC_BACK_EARLY) * fps)) if nxt is not None else fade_out
        down = min(down, fade_out)
        if up < 1 or down - up < 1:
            continue
        section = mood_at(up)
        g = speech_gain(section)
        lifted = min(1.0, g * rise)
        if lifted - g < 0.005:
            continue                                    # already as loud as the renderer allows
        out.append({"startFrame": up, "volume": round(lifted, 4), "mood": str(section.get("mood") or ""),
                    "kind": "pause"})
        if nxt is not None and down < fade_out:
            back = mood_at(int(round(nxt * fps)))
            out.append({"startFrame": down, "volume": round(speech_gain(back), 4), "mood": str(back.get("mood") or ""),
                        "kind": "voice"})
    last = mood_at(fade_out)
    tail = speech_gain(last)
    out.append({"startFrame": fade_out, "volume": round(tail / 2, 4), "mood": str(last.get("mood") or ""),
                "kind": "fade-out"})
    out.append({"startFrame": fade_half, "volume": 0.0, "mood": str(last.get("mood") or ""), "kind": "fade-out"})
    out.sort(key=lambda s: s["startFrame"])            # stable: a pause's rise stays after the voice level it lifts
    for k, s in enumerate(out):
        s["endFrame"] = max(s["startFrame"] + 1, out[k + 1]["startFrame"] if k + 1 < len(out) else total)
    return {**music, "sections": out, "duck": 1.0,
            "levels": {"voiceLufs": round(float(voice_lufs), 1), "trackLufs": track_lufs,
                       "underVoiceDb": MUSIC_UNDER_VOICE_DB, "speech": round(speech_gain(moods[0]), 4)}}


def music_fit(music: Optional[dict], total: int, fps: int) -> Tuple[Optional[dict], str]:
    """
    The music on the video's own clock, and what was wrong ("" = nothing).
    The owner (2026-10-04): "the music didn't match the full length of the
    narration". Measured that day: the editor's 60 fps export doubled every
    frame number of the document except the music's, so the plan's fade-out
    (3 s before the end at 30 fps) sat in the middle of the 60 fps video - the
    music faded out halfway and the second half was silent (Yellowstone:
    sections ending at frame 52,810 of 105,620).

    The same rule as the renderer's fitMusic (remotion/src/components/
    musicMix.ts, which a test keeps equal): sections that end where the video
    ends are left alone; a lone level set in the editor covers the whole
    video; sections that end at exactly half or twice the video's length are
    scaled to its clock (with the editor's trim); a plan whose video was made
    longer or shorter keeps its levels and gets its fade-out at the new end.
    """
    if not isinstance(music, dict):
        return music, ""
    sections = [s for s in (music.get("sections") or []) if isinstance(s, dict)]
    if not sections:
        return music, ""
    fps = max(1, int(fps or 30))
    n = max(1, int(round(float(total or 1))))

    def num(v) -> float:
        try:
            f = float(v)
            return f if math.isfinite(f) else 0.0
        except (TypeError, ValueError):
            return 0.0

    planned = any(s.get("kind") for s in sections)
    if not planned and len(sections) == 1:
        only = sections[0]
        if num(only.get("startFrame")) == 0 and num(only.get("endFrame")) == n:
            return music, ""
        return {**music, "sections": [{**only, "startFrame": 0, "endFrame": n}]}, ""   # the renderer never read them
    end = max(num(s.get("endFrame")) for s in sections)
    if not end > 0 or abs(end - n) <= 1:
        return music, ""
    scale = 2.0 if abs(end * 2 - n) <= 2 else 0.5 if abs(end - n * 2) <= 2 else 1.0

    def at(v) -> int:
        return max(0, int(math.floor(num(v) * scale + 0.5)))

    out = [{**s, "startFrame": at(s.get("startFrame")), "endFrame": at(s.get("endFrame"))} for s in sections]
    why = (f"the music was timed for a {_mmss(end / fps)} video, this one is {_mmss(n / fps)}"
           if scale == 1.0 else
           f"the music was left at {'30' if scale == 2.0 else '60'} fps frame numbers by a "
           f"{'60' if scale == 2.0 else '30'} fps export: it "
           + (f"faded out at {_mmss(end / fps)} of {_mmss(n / fps)}" if scale == 2.0 else "ran past the video's end"))
    if planned and abs(at(end) - n) > 1:
        fade_out = max(2, n - int(math.floor(MUSIC_FADE_OUT * fps + 0.5)))
        fade_half = max(fade_out + 1, n - int(math.floor(MUSIC_RAMP * fps + 0.5)))
        body = [s for s in out if s.get("kind") != "fade-out" and s["startFrame"] < fade_out]
        voice = next((s for s in reversed(body) if s.get("kind") == "voice"), body[-1] if body else None)
        level = num(voice.get("volume")) if voice else 0.0
        mood = (voice or {}).get("mood", "")
        out = body + [{"startFrame": fade_out, "volume": round(level / 2, 4), "mood": mood, "kind": "fade-out"},
                      {"startFrame": fade_half, "volume": 0.0, "mood": mood, "kind": "fade-out"}]
    out.sort(key=lambda s: s["startFrame"])            # stable, as the plan was written
    for k, s in enumerate(out):
        s["endFrame"] = max(s["startFrame"] + 1, out[k + 1]["startFrame"] if k + 1 < len(out) else n)
    fitted = {**music, "sections": out}
    if scale != 1.0:
        for key in ("from", "to"):
            if isinstance(music.get(key), (int, float)) and not isinstance(music.get(key), bool):
                fitted[key] = at(music[key])
    return fitted, why


def _mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


def _pack_transitions(entrances: List[str], pack: dict) -> List[str]:
    """The planned entrances, kept to the transitions the style pack allows."""
    allowed = [t for t in (pack.get("transitions") or []) if t in TRANSITIONS]
    if not allowed:
        return entrances
    out, used = [], 0
    for e in entrances:
        if e == "none" or e in allowed:
            out.append(e)
        else:
            out.append(allowed[used % len(allowed)])
            used += 1
    return out


def plan_transitions(shots: List[dict], style: str = "documentary",
                     durations: Optional[List[int]] = None) -> List[str]:
    """
    Entrance per scene: hard cuts by default, a real transition where the
    story changes section, in the style's own vocabulary and rhythm.

    A section change is a chapter/title graphic, or the named subject moving on
    ("Lake Mead" -> "Hoover Dam"). Calm styles (documentary, history, story)
    only mark those, softly, at most about one cut in six. Energetic styles
    (news, compilation, trending) also punctuate a long run of plain cuts, so
    they land near one cut in three or four. Never on consecutive cuts, never
    the same transition twice in a row. `durations` (frames per scene), when
    given, keeps transitions off cuts too short to carry one.
    """
    if style == "crossfade":
        return _plan_crossfades(shots, durations)
    spec = _STYLE_TRANSITIONS.get(style) or _STYLE_TRANSITIONS["documentary"]
    cycle, gap, force = spec["cycle"], max(_MIN_TRANSITION_GAP, int(spec["gap"])), int(spec["force"])
    out, last, used = [], -99, 0
    prev_subject, prev_choice = None, None
    for i, shot in enumerate(shots):
        shot = shot or {}
        subject = (shot.get("subject") or "").strip().lower()
        overlay = shot.get("overlay") or {}
        choice = "none"
        roomy = durations is None or (
            i < len(durations) and durations[i] >= _MIN_IN_FRAMES
            and durations[i - 1] >= _MIN_OUT_FRAMES)
        # A human rhythm, not a metronome: now and then one more plain cut
        # before the next transition (stable per beat, so re-plans agree).
        need = gap + (1 if zlib.crc32(f"{i}:{subject}".encode("utf-8")) % 2 == 0 else 0)
        if force:
            need = min(need, force)
        if i > 0 and i - last >= need and roomy:
            chapter = overlay.get("type") in ("chapter", "title")
            moved_on = bool(subject and prev_subject and subject != prev_subject)
            due = force > 0 and i - (last if last >= 0 else 0) >= force
            if chapter:
                choice = spec["chapter"]
            elif moved_on or due:
                choice = cycle[used % len(cycle)]
            if choice != "none" and choice == prev_choice:
                # A chapter pick that repeats the last transition takes the next in turn.
                choice = cycle[(cycle.index(choice) + 1) % len(cycle)] if choice in cycle else cycle[0]
        if choice != "none":
            last, used, prev_choice = i, used + 1, choice
        out.append(choice)
        if subject:
            prev_subject = subject
    return out


# The news-compilation cut (src/styles.py, measured from the Nor'easter
# reference channel): ~80% of changes are a soft 0.5 s cross-dissolve, the
# rest hard cuts; no effects, no sounds.
CROSSFADE_SHARE = 0.8
CROSSFADE_FRAMES = 15


def _plan_crossfades(shots: List[dict], durations: Optional[List[int]] = None) -> List[str]:
    """ "crossfade" on about CROSSFADE_SHARE of cuts (stable per beat), a hard
    cut on the rest and wherever either shot is too short to dissolve."""
    out = []
    for i, shot in enumerate(shots):
        subject = str((shot or {}).get("subject") or "").strip().lower()
        roomy = durations is None or (
            i < len(durations) and durations[i] >= CROSSFADE_FRAMES * 2
            and durations[i - 1] >= CROSSFADE_FRAMES * 2)
        pick = (zlib.crc32(f"xf:{i}:{subject}".encode("utf-8")) % 100) < CROSSFADE_SHARE * 100
        out.append("crossfade" if i > 0 and roomy and pick else "none")
    return out


# --------------------------------------------------------------------------- #
# The owner's overlay transition pack
# --------------------------------------------------------------------------- #
# remotion/public/transitions/mlt<N>.mp4 (the Mr.YTR pack, 2026-10-01): film
# burns, light leaks, white flashes, film strips, glitches and streaks shot on
# black, each with its own sound. A scene entering with "pack:<name>" is a hard
# cut with the clip screen-blended over it, its most covered frame on the cut
# (remotion/src/transitions/PackTransition.tsx), its own sound playing - so no
# timeline transition sound is ever planned on that cut. The owner: not on
# every cut, never the same one twice running, placed where the story turns.
# Its sound is levelled against the narration like every other sound (the
# owner, 2026-10-01: the pack's sounds stood over the voice): the clip's
# measured loudness (transitions_meta.json "lufs") sets a gain that puts its
# loudest moment PACK_UNDER_DB under the voice, a glitch clip's
# PACK_GLITCH_UNDER_DB, never above 1 (as recorded): pack_gain, stored on the
# scene as "transitionGain"; the renderer holds it under the same ceiling.
PACK_PREFIX = "pack:"
PACK_CHARACTERS = ("flash", "burn", "leak", "film", "glitch", "streak")
PACK_META_PATH = os.path.join(os.path.dirname(templates.PATH), "..", "data", "transitions_meta.json")
PACK_EDGE_START = 1.5       # seconds at the start of the video with no pack transition
PACK_EDGE_END = 2.0         # ... and at its end
PACK_RECENT = 3             # a clip is not used again within this many picks
PACK_ROOM = 0.25            # seconds each scene keeps clear of the clip beyond the cut it covers
PACK_SOUND_CLEAR = 0.3      # seconds: another sound this close to the clip's span blocks the cut
_PACK_META_CACHE: Dict[str, Any] = {}

_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*\s*$")
# Words that turn the story to a new part ("Now let's head to...", "Years later", "Number 5").
_PACK_SECTION = re.compile(
    r"^\W*(?:(?:all right|alright|okay|ok|so|and|but|well)[,.]?\s+)*(?:"
    r"now,?\s+let'?s\b|let'?s (?:take a (?:closer )?look|look at|turn to|talk about|go back|start|begin|dive|rewind)\b|"
    r"meanwhile\b|elsewhere\b|moving on\b|next up\b|up next\b|but first\b|first,|finally,|fast[- ]forward\b|"
    r"(?:years|decades|months|weeks|days|hours|centuries) later\b|back in\b|in (?:the )?(?:year )?(?:1[5-9]\d\d|20\d\d)\b|"
    r"number (?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b|#\d+|chapter\b|part (?:\d+|one|two|three)\b|"
    r"so (?:what|how|why)\b|here'?s (?:what|why|how|the thing)\b|but (?:then|that'?s not all)\b|"
    r"the next (?:day|morning|year|week)\b)", re.I)
_PACK_IMPACT = re.compile(
    r"\b(?:suddenly|explo(?:ded|sion|des)|blast|crash(?:ed|es)?|collaps(?:ed|es)|slamm(?:ed|ing)|struck|"
    r"shock(?:ing|ed)|stunn(?:ing|ed)|devastat(?:ing|ed|ion)|destroy(?:ed|s)|deadly|killed|catastroph\w*|"
    r"breaking|out of nowhere|that'?s when|turns? out)\b", re.I)
# The look a line asks for by its own words (glitch for tech and alerts, film
# and burns for the past, a flash for an impact or a reveal, a leak for a calm move).
_PACK_CUES = (
    ("glitch", re.compile(r"\b(?:breaking|alert|warning|emergency|hack(?:ed|ers?|ing)?|cyber\w*|glitch\w*|"
                          r"computers?|software|digital|internet|online|data|signal|radar|satellite|malfunction\w*|"
                          r"outage|blackout|virus|AI|artificial intelligence|robots?|technology)\b", re.I)),
    ("streak", re.compile(r"\b(?:fast(?:er|est)?|speed\w*|rac(?:e|ing)|rush(?:ed|ing)|scan\w*|tracking|lightning|"
                          r"electric\w*|lasers?|in seconds|instantly|across the (?:country|state|region|world))\b", re.I)),
    ("film", re.compile(r"\b(?:1[5-9]\d\d|archive\w*|footage|filmed|newsreel|photographs?|vintage|decades ago|"
                        r"back then|histor(?:y|ic|ical)|memories)\b", re.I)),
    ("burn", re.compile(r"\b(?:centur(?:y|ies)|ancient|empire|kings?|queens?|war|battle|burn(?:ed|ing|s)?|flames?|"
                        r"founded|legend\w*|long ago|origins?|blaze|inferno)\b", re.I)),
    ("flash", re.compile(r"\b(?:suddenly|explo(?:ded|sion|des)|blast|crash(?:ed|es)?|collaps(?:ed|es)|struck|"
                         r"slamm(?:ed|ing)|shock(?:ing|ed)|stunn(?:ing|ed)|reveal(?:ed|s)?|discover(?:ed|y)|massive|"
                         r"devastat(?:ing|ed)|destroyed|deadly|but then|that'?s when|turns? out|boom)\b", re.I)),
    ("leak", re.compile(r"\b(?:meanwhile|elsewhere|morning|evening|sunset|sunrise|dawn|dusk|quiet(?:ly)?|calm|"
                        r"peaceful|journey|travel\w*|head(?:ing|ed)? (?:to|north|south|east|west|over)|"
                        r"let'?s (?:head|move|go)|over in|down in|up in|summer|spring|golden)\b", re.I)),
)


# How far a line's own words pull toward a look: an alert or an impact is a
# strong ask; a calm or a historic word only leans (the style still decides).
_PACK_CUE_WEIGHT = {"glitch": 3.0, "flash": 2.5, "film": 2.0, "burn": 2.0, "leak": 2.0, "streak": 2.0}


def pack_meta() -> Dict[str, dict]:
    """{name: {duration, fps, frames, peakFrame, peak, audioPeak, character, ...}} of every pack clip
    (remotion/src/data/transitions_meta.json); {} when it cannot be read."""
    try:
        stamp = os.path.getmtime(PACK_META_PATH)
    except OSError:
        return {}
    if _PACK_META_CACHE.get("stamp") != stamp:
        try:
            import json
            with open(PACK_META_PATH, encoding="utf-8") as fh:
                data = (json.load(fh) or {}).get("transitions") or {}
        except (OSError, ValueError, AttributeError):
            return {}
        _PACK_META_CACHE.update(stamp=stamp, data={
            k: v for k, v in data.items() if isinstance(v, dict) and v.get("character") in PACK_CHARACTERS
            and float(v.get("duration") or 0) > 0 and 0 <= float(v.get("peak") or 0) <= float(v["duration"])})
    return _PACK_META_CACHE["data"]


def pack_name(t: Any) -> str:
    """ "mlt5" for "pack:mlt5" when the pack ships that clip, else "". """
    if isinstance(t, str) and t.startswith(PACK_PREFIX) and t[len(PACK_PREFIX):] in pack_meta():
        return t[len(PACK_PREFIX):]
    return ""


# How far under the voice a pack clip's loudest moment sits (dB): the sound
# ceiling (sfxplan.CAP_UNDER_DB), a glitch clip the glitches' further 3 dB.
PACK_UNDER_DB = sfxplan.CAP_UNDER_DB
PACK_GLITCH_UNDER_DB = sfxplan.CAP_UNDER_DB + sfxplan.GLITCH_EXTRA_DB


def pack_under_db(name: str) -> float:
    """dB under the voice a pack clip's loudest moment is set: glitch clips further."""
    return PACK_GLITCH_UNDER_DB if (pack_meta().get(name) or {}).get("character") == "glitch" else PACK_UNDER_DB


def pack_gain(name: str, voice_lufs: Optional[float] = None) -> float:
    """
    The gain of a pack clip's own sound against this voice: its loudest 400 ms
    (transitions_meta.json "lufs"; a clip not measured counts as a matched
    sound file, SFX_REF_LUFS) pack_under_db under the voice, never above 1
    (the clip as recorded). The renderer's twin is PackTransition.tsx packGain.
    """
    m = pack_meta().get(name) or {}
    loud = m.get("lufs")
    if isinstance(loud, bool) or not isinstance(loud, (int, float)) or not math.isfinite(loud):
        loud = sfxplan.SFX_REF_LUFS
    return min(1.0, 10 ** ((sfxplan.voice_level(voice_lufs) - pack_under_db(name) - float(loud)) / 20.0))


def _pack_span(m: dict, fps: int) -> tuple:
    """(frames before the cut, frames from the cut on) a clip covers at this fps (as PackTransition.tsx lays it)."""
    same = abs(float(m.get("fps") or 0) - fps) < 1e-6
    lead = int(m["peakFrame"]) if same else int(round(float(m["peak"]) * fps))
    length = int(m["frames"]) if same else max(1, int(math.floor(float(m["duration"]) * fps)))
    return lead, max(1, length - lead)


def _pack_moments(segments: List[Segment], shots: List[dict], bounds: List[int], fps: int,
                  rhythm: dict, brief: Optional[dict], busy: List[tuple]) -> List[dict]:
    """
    Every cut that may take a pack transition, with how strongly the story
    turns there: {"i", "t", "score", "tags", "cues"}. Only sentence starts (or
    a long pause in an unpunctuated transcript), outside the first
    PACK_EDGE_START and last PACK_EDGE_END seconds, with room on both sides for
    the shortest clip, and clear of every other sound (`busy` frame spans): a
    graphic's own sound on that beat wins and two sounds never stack.
    """
    from .director import region_turn
    n = len(segments)
    meta = pack_meta()
    if n < 2 or not meta:
        return []
    total = bounds[-1]
    spans = [_pack_span(m, fps) for m in meta.values()]
    min_lead, min_tail = min(s[0] for s in spans), min(s[1] for s in spans)
    max_lead, max_tail = max(s[0] for s in spans), max(s[1] for s in spans)
    room = int(round(PACK_ROOM * fps))
    clear = int(round(PACK_SOUND_CLEAR * fps))
    punctuated = any(_SENTENCE_END.search(s.text or "") for s in segments)
    shots = list(shots) + [{}] * max(0, n - len(shots))

    def first_word(k):
        w = getattr(segments[k], "words", None) or []
        return float(w[0].start) if w else float(segments[k].start)

    def last_word(k):
        w = getattr(segments[k], "words", None) or []
        return float(w[-1].end) if w else float(segments[k].end)

    def opens_sentence(k):
        if k <= 0:
            return True
        if punctuated:
            return bool(_SENTENCE_END.search(segments[k - 1].text or ""))
        return first_word(k) - last_word(k - 1) >= 0.35

    # The end of the hook: the first beat after the hook beats (director marks
    # them), else the sentence start after the longest pause 12-40 s in.
    hooks = [k for k, sh in enumerate(shots[:n]) if (sh or {}).get("hook")]
    hook_end = max(hooks) + 1 if hooks else None
    while hook_end is not None and hook_end < n and not opens_sentence(hook_end):
        hook_end += 1
    if hook_end is None:
        early = [k for k in range(1, n) if 12.0 <= bounds[k] / fps <= 40.0 and opens_sentence(k)]
        if early:
            hook_end = max(early, key=lambda k: (first_word(k) - last_word(k - 1), -k))
    sections = {}
    prev_sec = None
    for sec in sorted([s for s in (brief or {}).get("sections") or [] if isinstance(s, dict)
                       and isinstance(s.get("from"), int)], key=lambda s: s["from"]):
        if prev_sec is not None and (sec.get("where"), sec.get("when")) != (prev_sec.get("where"), prev_sec.get("when")):
            sections[sec["from"]] = True
        prev_sec = sec
    only = set(rhythm.get("only") or ())
    out = []
    for k in range(1, n):
        cut, t = bounds[k], bounds[k] / fps
        if t < PACK_EDGE_START or t > total / fps - PACK_EDGE_END or not opens_sentence(k):
            continue
        if bounds[k] - bounds[k - 1] < min_lead + room or bounds[k + 1] - bounds[k] < min_tail + room:
            continue
        lo, hi = cut - max_lead - clear, cut + max_tail + clear
        if any(s < hi and lo < e for s, e in busy):
            continue
        text = segments[k].text or ""
        shot, before = shots[k] or {}, shots[k - 1] or {}
        tags, score = [], 0.0
        if hook_end == k:
            tags.append("hook"); score += 3.0
        if (shot.get("overlay") or {}).get("type") in ("chapter", "title"):
            tags.append("section"); score += 3.0
        elif sections.get(k):
            tags.append("section"); score += 2.5
        region, was = str(shot.get("region") or "").strip().lower(), str(before.get("region") or "").strip().lower()
        if region and was and region != was:
            tags.append("region"); score += 3.0
        elif region_turn(text):
            tags.append("region"); score += 2.5
        if "section" not in tags and _PACK_SECTION.search(text):
            tags.append("section"); score += 2.0
        pause = first_word(k) - last_word(k - 1)
        if pause >= 0.6:
            tags.append("pause"); score += 1.5 if pause >= 1.0 else 1.0
        subject = str(shot.get("subject") or "").strip().lower()
        if subject and subject != str(before.get("subject") or "").strip().lower() and before.get("subject"):
            tags.append("subject"); score += 1.3 if shot.get("subjectType") == "place" else 1.0
        if _PACK_IMPACT.search(text) and float(rhythm.get("impact") or 0) > 0:
            tags.append("impact"); score += float(rhythm["impact"])
        if only and not only & set(tags):
            continue
        out.append({"i": k, "t": t, "score": score, "tags": tags,
                    "cues": [c for c, rx in _PACK_CUES if rx.search(text)]})
    return out


def plan_pack_transitions(segments: List[Segment], shots: List[dict], bounds: List[int], fps: int,
                          rhythm: dict, brief: Optional[dict] = None, busy: Optional[List[dict]] = None,
                          allowed: Optional[Any] = None) -> Dict[int, str]:
    """
    {scene index: pack clip name} - where the owner's overlay transitions go.

    A strong turn (the end of the hook, a chapter, a region change) takes one
    as soon as `gap` seconds have passed since the last; a section phrase
    ("Now let's head to...") after 0.6 x `every`; a long pause, a new subject or
    an impact line after `every`; any other sentence start only after `fill`
    (never when 0). A stronger moment just ahead wins over a weaker one now,
    and the total stays near one per `every` seconds. Each pick takes the clip
    whose look (rhythm["characters"] plus the line's own words) fits best,
    never one of the last PACK_RECENT, and never one that would overrun its
    scenes. `busy` is every other planned sound ({startFrame, durationFrames}).
    `allowed` (the brand kit's clips, brandkit.pack_clips): only those; None = every clip.
    """
    meta = pack_meta()
    if allowed is not None:
        meta = {k: v for k, v in meta.items() if k in set(allowed)}
    n = len(segments)
    if not meta or n < 2 or len(bounds) < n + 1:
        return {}
    spans = []
    for o in busy or []:
        s = int(o.get("startFrame", 0))
        d = o.get("durationFrames")
        if not isinstance(d, (int, float)) or d <= 0:
            m = sfx_meta().get(o.get("name")) or {}
            d = math.ceil(float(m.get("duration", 1.0)) * fps)
        spans.append((s, s + max(1, int(math.ceil(d)) - int(o.get("trimFrames") or 0))))
    moments = _pack_moments(segments, shots, bounds, fps, rhythm, brief, spans)
    gap, every = float(rhythm.get("gap", 12.0)), float(rhythm.get("every", 38.0))
    fill = float(rhythm.get("fill", 0.0) or 0.0)

    def need(score: float) -> float:
        if score >= 3.0:
            return gap
        if score >= 2.0:
            return max(gap, 0.6 * every)
        if score >= 1.0:
            return max(gap, every)
        return max(gap, fill) if fill > 0 else math.inf

    picks, last = [], None
    for k, m in enumerate(moments):
        since = m["t"] - (last if last is not None else 0.0)
        want = need(m["score"]) * (0.5 if last is None else 1.0)
        if since < want:
            continue
        ahead = [d for d in moments[k + 1:] if d["t"] - m["t"] < gap and d["score"] > m["score"]
                 and d["t"] - (last if last is not None else 0.0) >= need(d["score"]) * (0.5 if last is None else 1.0)]
        if ahead:
            continue
        picks.append(m)
        last = m["t"]
    budget = max(1, int(round(bounds[-1] / fps / every)))
    while len(picks) > budget:
        picks.remove(min(picks, key=lambda p: (p["score"], -p["t"])))

    likes = dict(rhythm.get("characters") or {})
    room = int(round(PACK_ROOM * fps))
    out: Dict[int, str] = {}
    recent: List[str] = []
    prev_look = ""
    for p in picks:
        i = p["i"]
        cut, before, after = bounds[i], bounds[i] - bounds[i - 1], bounds[i + 1] - bounds[i]
        best, best_w = "", -math.inf
        for name in sorted(meta):
            m = meta[name]
            lead, tail = _pack_span(m, fps)
            if name in recent[-PACK_RECENT:] or before < lead + room or after < tail + room \
                    or cut - lead < 0 or cut + tail > bounds[-1]:
                continue
            look = m["character"]
            w = float(likes.get(look, 0.5)) + (_PACK_CUE_WEIGHT.get(look, 2.0) if look in p["cues"] else 0.0) \
                - (1.2 if look == prev_look else 0.0) + 0.4 * float(m.get("coverage") or 0.0) \
                + (zlib.crc32(f"{i}:{name}".encode("utf-8")) % 100) / 250.0
            if w > best_w:
                best, best_w = name, w
        if best:
            out[i] = best
            recent.append(best)
            prev_look = meta[best]["character"]
    return out


def apply_pack_transitions(scenes: List[dict], picks: Dict[int, str], fps: int, clear_seconds: float = 3.0,
                           voice_lufs: Optional[float] = None) -> int:
    """
    Set each picked scene's entrance to its pack clip (any crossfade or style
    transition there becomes the hard cut the clip covers) and clear the
    style's own transitions within `clear_seconds` of it (crossfades stay).
    Each pack scene carries its clip's sound level against this voice
    ("transitionGain", pack_gain). Returns how many pack transitions were set.
    """
    near = int(round(max(0.0, clear_seconds) * fps))
    cuts = [int(scenes[i]["startFrame"]) for i in picks if 0 < i < len(scenes)]
    for i, sc in enumerate(scenes):
        t = sc.get("transition") or "none"
        if i in picks and 0 < i < len(scenes):
            sc["transition"] = PACK_PREFIX + picks[i]
            sc["transitionGain"] = round(pack_gain(picks[i], voice_lufs), 3)
        elif t not in ("none", "crossfade") and not pack_name(t) \
                and any(abs(int(sc.get("startFrame", 0)) - c) <= near for c in cuts):
            sc["transition"] = "none"
        else:
            continue
        vt = sc.get("visualTreatment")
        if isinstance(vt, dict) and "transitionIn" in vt:
            vt["transitionIn"] = sc["transition"]
    return len(cuts)


def plan_transition_sfx(scenes: List[dict], fps: int, others: List[dict],
                        intensity: float = 1.0, voice_lufs: Optional[float] = None,
                        soft: Optional[Dict[int, str]] = None) -> List[dict]:
    """
    A sound for each transition, placed so its loudest point lands on the
    cut, set against the voice (`voice_lufs`, see _TRANSITION_SFX) at the
    style pack's sfxIntensity like the graphics' sounds, never above its
    ceiling (sfxplan.cap: 6 dB under the voice, a glitch 9). Skipped when
    another sound starts within a second of it or is still playing across
    it (a typing run, a count, a riser): a graphic's own sound on that beat
    wins, and two sounds never stack. `soft` ({scene index: transition key},
    the hook booster's first cuts, src/hookboost.py) gives a cut the sound of
    that transition although the scene itself enters with a hard cut; it goes
    through every rule above, so it is never louder than any transition sound.
    """
    meta = sfx_meta()
    have = templates.sfx_files()
    near = int(round(_TRANSITION_SFX_CLEARANCE * fps))
    try:
        level = max(0.0, float(intensity))
    except (TypeError, ValueError):
        level = 1.0
    busy = []   # (start, end) of every sound already planned, as the renderer plays it
    for o in others:
        s = int(o.get("startFrame", 0))
        d = o.get("durationFrames")
        if not isinstance(d, (int, float)) or d <= 0:
            m = meta.get(o.get("name")) or _SFX_META_FALLBACK.get(o.get("name")) or {}
            d = math.ceil(float(m.get("duration", 1.0)) * fps)
        # Main.tsx plays a cue for durationFrames minus its skipped head (trimFrames).
        d = int(math.ceil(d)) - int(o.get("trimFrames") or 0)
        busy.append((s, s + max(1, d)))
    picks = []
    for idx, sc in enumerate(scenes):
        t = sc.get("transition") or "none"
        if t not in _TRANSITION_SFX and soft and idx in soft and not pack_name(t):
            t = soft[idx]
        if t not in _TRANSITION_SFX:
            continue
        name, under = _TRANSITION_SFX[t]
        if have and name not in have:
            name = _TRANSITION_ALT.get(name, "")
            if name not in have:
                continue
        m = meta.get(name) or _SFX_META_FALLBACK.get(name) or {"duration": 1.0, "peak": 0.0}
        cut = int(sc.get("startFrame", 0))
        start = cut - int(round(float(m.get("peak", 0.0)) * fps))
        if cut <= 0 or start < 0:
            continue
        dur = max(1, int(math.ceil(float(m.get("duration", 1.0)) * fps)))
        end = start + dur
        if any(abs(s - start) <= near or abs(s - cut) <= near or (s < end and start < e)
               for s, e in busy):
            continue
        # Under its own ceiling, never above it (sfxplan.cap: the file's measured loudness counts).
        under = max(float(under), sfxplan.ceiling_db(name))
        vol = round(min(sfxplan.cap(voice_lufs, name), sfxplan.gain(under, voice_lufs, name) * level), 3)
        if vol <= 0.005:
            continue
        picks.append({"name": name, "startFrame": start, "volume": vol,
                      "durationFrames": dur, "kind": "transition"})
        busy.append((start, end))
    return picks

# How long each graphic wants to be on screen, in seconds, independent of the
# beat that triggered it. Measured from the reference renders: supporting shots
# run 2-4s but an explanatory graphic holds far longer (bar chart 10.5s, city
# map 9.0s, callout 3.5s). A chart cut after 2.6s is a chart nobody can read.
_OVERLAY_SECONDS = {
    # Tuned against the ~7s-beat GoMotion pacing; VidRush's own 3.3-3.7s
    # median (now this worker's pacing too) made the longest of these span
    # 2-3 beats of unrelated narration underneath a graphic that had already
    # finished saying its piece. Trimmed toward roughly a beat and a half,
    # kept longer only where there is genuinely more to read (a chart, a
    # document, several dated events).
    "title": 3.0, "chapter": 2.5, "callout": 3.0, "typewriter": 3.0,
    "stat": 3.5, "bar-chart": 6.0, "map": 5.5, "quote": 4.0,
    "timeline": 6.0, "highlight": 3.0, "lower-third": 3.5,
    "comparison": 5.0, "arrow": 2.5, "split": 4.0,
    "sentence-highlight": 4.0, "article-zoom": 5.0, "date-stamp": 3.0,
    "photo-card": 4.0, "name-card": 3.5,
    # Footage tags ride on a playing shot; VidRush holds them 4-5.5 s.
    "stat-tag": 4.0, "label-boxes": 4.0, "ring-stat": 4.5, "bullets": 5.5,
    "swoosh-title": 3.0, "kicker": 3.0, "memo-box": 3.5, "word-type": 2.5,
    "underline-title": 3.5, "bar-title": 3.5, "age-tag": 3.0, "clock-badge": 3.5,
    "red-strip": 3.0,
    "line-chart": 5.5, "path-steps": 5.5, "progress-steps": 4.5, "span": 4.5,
    "icon-pop": 3.0,
    "donut": 5.0, "area-chart": 6.0, "progress-bar": 4.5, "icon-array": 4.0,
    "ranking": 5.5, "counter": 4.5, "number-roll": 3.5, "trend": 4.0,
    "year-roll": 5.0, "banner": 4.0, "scale-compare": 5.0,
    # Library looks carry their own duration in the registry.
    "motion": 4.5,
}

# Sources this workflow refuses. Kept as data so the check and the error
# message can't drift apart.
_STOCK_SOURCES = {"pexels", "pixabay", "stock", "shutterstock", "storyblocks"}


# How graphics move in (MotionWrap.tsx), varied the way an editor varies
# them: charts rise or zoom in, number punches slam or glitch, tags slide.
# Full-screen graphics (maps, documents, chapter cards) carry their own move.
_FULL_SCREEN = {"map", "article-zoom", "chapter", "split", "photo-card", "name-card", "banner"}
_DATA = {"donut", "area-chart", "progress-bar", "icon-array", "ranking", "counter", "bar-chart",
         "line-chart", "comparison", "scale-compare", "stat", "timeline", "year-roll"}
_PUNCH = {"number-roll", "trend", "stat-tag", "ring-stat", "red-strip", "kicker", "callout", "icon-pop"}
_MOTION_TURNS = {
    "data": ["rise", "zoom-in", "wipe-up", "blur", "flip"],
    "punch": ["zoom-out", "glitch", "drop", "slide-left", "wipe"],
    "text": ["rise", "slide-left", "wipe", "blur", "slide-right", "zoom-in"],
}


def with_motion(overlay: dict, n: int) -> dict:
    if overlay.get("motion") or overlay["type"] in _FULL_SCREEN:
        return overlay
    family = "data" if overlay["type"] in _DATA else "punch" if overlay["type"] in _PUNCH else "text"
    turns = _MOTION_TURNS[family]
    return {**overlay, "motion": turns[n % len(turns)]}


def _media_dims(asset) -> tuple:
    """(width, height) of an asset: from the source when it reported them,
    else probed from the downloaded file. (0, 0) when neither is possible."""
    w, h = int(getattr(asset, "width", 0) or 0), int(getattr(asset, "height", 0) or 0)
    if w and h:
        return w, h
    path = getattr(asset, "local_path", "") or ""
    if not path or not os.path.isfile(path):
        return 0, 0
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=20)
        a, b = (p.stdout.strip().splitlines() or [""])[0].split(",")[:2]
        return int(a), int(b)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0, 0


def pick_frame(asset, treatment: str, subject_type: str) -> str:
    """
    "inset" or "full" for one scene. Always "full" - VidRush's own inset-on-a-
    backdrop archival look (see SceneClip.tsx, still there) turned out to read
    as a bug, not a style, once watched in a real render: told directly to
    stop, on sight, no exceptions. `asset`/`treatment`/`subject_type` are
    still accepted so nothing upstream needs to change if this is revisited.
    """
    return "full"


def _scene_bounds(segments: List[Segment], fps: int, total: int) -> List[int]:
    """
    Frame boundaries for the visual track: [0, b1, b2, ..., total].

    The visual track must tile the narration exactly — no gaps, no overlaps,
    covering frame 0 to the last frame. Rounding each segment start
    independently does not guarantee that: a segment can round onto its
    neighbour, the first can start late, and the last can stop short of the
    audio. So boundaries are walked forward, each forced at least one frame
    past the previous and far enough from the end to leave every remaining
    scene a frame of its own.
    """
    n = len(segments)
    if total < n:
        raise ValueError(
            f"{n} scenes will not fit in {total} frames of narration; "
            "raise TARGET_SCENE_SECONDS or check the audio duration")
    bounds = [0]
    for i in range(1, n):
        want = int(round(segments[i].start * fps))
        bounds.append(max(bounds[-1] + 1, min(want, total - (n - i))))
    bounds.append(total)
    return bounds


# Which animation moments carry a sound, and at what level - read off
# VidRush's own Obama-family project: 9 sounds in 25 minutes, each tied to an
# animation (typewriter title 25-30%, timeline / map / year stamp / article
# zoom 35%, image highlight 20%), transitions silent. Files: remotion/public/sfx.
_SFX_FOR = {
    "typewriter": ("typewriter", 0.28), "memo-box": ("typewriter", 0.25),
    "bar-title": ("typewriter", 0.25), "word-type": ("typewriter", 0.25),
    "timeline": ("pop", 0.35), "span": ("pop", 0.35), "path-steps": ("pop", 0.35),
    "map": ("whoosh", 0.35), "date-stamp": ("impact", 0.3),
    "article-zoom": ("paper", 0.35), "chapter": ("impact", 0.3),
    "swoosh-title": ("whoosh", 0.3), "red-strip": ("impact", 0.3),
    "icon-pop": ("pop", 0.3), "ring-stat": ("pop", 0.3), "kicker": ("typewriter", 0.25),
}
SFX_NAMES = ({name for name, _ in _SFX_FOR.values()} | {"glitch", "glitch-transition", "map-whoosh", "riser", "page"}
             | {name for name, _ in _TRANSITION_SFX.values()})


def plan_sfx(overlays: List[dict], fps: int, min_gap_seconds: float) -> List[dict]:
    """
    Sounds for the biggest animation moments, sparsely.

    One per min_gap_seconds at most (VidRush: ~1 per 2-3 minutes); chapter
    breaks and date titles first when two compete, then the order they appear.
    """
    rank = {"chapter": 0, "date-stamp": 1, "map": 2, "timeline": 2, "article-zoom": 3}
    picks, last = [], -1e9
    for ov in sorted(overlays, key=lambda o: o.get("startFrame", 0)):
        kind = ov.get("type")
        if kind not in _SFX_FOR:
            continue
        if kind == "date-stamp" and ov.get("variant") != "title":
            continue            # the small corner stamp stays silent
        at = ov.get("startFrame", 0) / fps
        if at - last < min_gap_seconds:
            # A higher-ranked moment inside the gap replaces the last pick.
            if picks and rank.get(kind, 9) < rank.get(picks[-1]["_kind"], 9):
                picks.pop()
            else:
                continue
        name, vol = _SFX_FOR[kind]
        picks.append({"name": name, "startFrame": int(ov.get("startFrame", 0)),
                      "volume": vol, "_kind": kind})
        last = at
    for p in picks:
        p.pop("_kind", None)
    return picks


def _clip_seconds(asset) -> float:
    """Measured length of a video asset's file, else its recorded duration."""
    path = getattr(asset, "local_path", "") or ""
    if path and os.path.isfile(path):
        try:
            import subprocess
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
            return float((out.stdout or "0").strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return float(getattr(asset, "duration", 0) or 0)


def build(segments: List[Segment], shots: List[dict],
          assets: List[Optional[MediaAsset]], *,
          audio_url: str, audio_duration: float, inp: Dict[str, Any],
          planner: str = "rules", warnings: List[str] = None, narration_path: str = "",
          library=None) -> Dict[str, Any]:
    """
    Assemble the render document from beats, shot plan and sourced media.
    `narration_path` is the narration on this worker's disk when the caller
    has it (audio_url is usually a signed URL): the sounds and the music are
    levelled against its measured loudness (voice_loudness). `library` is
    the clip library the job loaded (src/library.py): its pictures of a
    subject fill an image look's slots the story's own pictures cannot.
    The job's brand kit (inp["brand_kit"]) is in force throughout: only its
    looks, transitions and music, its colours and font (src/brandkit.py).
    """
    from . import brandkit
    with brandkit.scope(brandkit.from_input(inp)):
        return _build(segments, shots, assets, audio_url=audio_url, audio_duration=audio_duration, inp=inp,
                      planner=planner, warnings=warnings, narration_path=narration_path, library=library)


def _build(segments: List[Segment], shots: List[dict],
           assets: List[Optional[MediaAsset]], *,
           audio_url: str, audio_duration: float, inp: Dict[str, Any],
           planner: str = "rules", warnings: List[str] = None, narration_path: str = "",
           library=None) -> Dict[str, Any]:
    warnings = list(warnings or [])
    fps = int(inp.get("fps") or config.DEFAULT_FPS)
    width = int(inp.get("width") or config.DEFAULT_WIDTH)
    height = int(inp.get("height") or config.DEFAULT_HEIGHT)
    brand = dict(inp.get("brand") or {})
    from . import brandkit
    _kit = brandkit.from_input(inp)
    if _kit:
        # The kit's colour and font win over the project's own (brandkit.prepare_input does the same).
        brand.update({k: v for k, v in (("accent", _kit.get("accent")), ("fontFamily", _kit.get("font"))) if v})
        if _kit.get("caption_style") and not inp.get("caption_style"):
            inp["caption_style"] = _kit["caption_style"]
    total = max(1, int(round(audio_duration * fps)))
    # The hook booster's cold open (HOOK_TEASER, src/hookboost.py): flashes of the
    # video's most striking later shots under a hook first line. Off: untouched.
    teaser_info = None
    if config.HOOK_TEASER:
        segments, shots, assets, teaser_info = hookboost.add_teaser(segments, shots, assets, fps)
    bounds = _scene_bounds(segments, fps, total)
    # Measured once: every sound effect and the music are set against the voice.
    voice_lufs, voice_how = voice_loudness(audio_url, inp, narration_path)

    scenes: List[Dict[str, Any]] = []
    overlays: List[Dict[str, Any]] = []
    # Off unless asked for: captions are a choice made in the editor, and a
    # burned-in default is the first thing a creator has to undo. Word
    # timings are stored either way, so switching them on later gets real
    # word-synced phrases instead of a scene's whole text at once.
    keep_captions = bool(inp.get("captions", False))

    # The visual treatment planner (src/treatments.py): the style pack decides
    # the looks, the narration decides where a treatment goes.
    from . import brandkit, director, treatments as vt
    brief = inp.get("brief") if isinstance(inp.get("brief"), dict) else dict(director.LAST_STORY)
    pack = vt.pack_for(brief, str(inp.get("style_pack") or config.STYLE_PACK or "")) if config.TREATMENTS else None
    # The customer's brand kit (src/brandkit.py): its colour replaces the
    # style pack's, so every look draws in the brand accent (captions.accent);
    # its picks limit the looks, transitions and music below.
    kit = brandkit.from_input(inp)
    if pack and kit and kit.get("accent"):
        pack = dict(pack, theme="accent")
    # Transitions follow the cutting style (a documentary mostly hard-cuts, a
    # news edit punctuates); a job can still pin the allowed set.
    style = transition_style(inp, pack, brief)
    entrances = plan_transitions(list(shots) + [{}] * max(0, len(segments) - len(shots)), style,
                                 durations=[bounds[i + 1] - bounds[i] for i in range(len(segments))])
    if isinstance(inp.get("transitions"), list) and inp["transitions"]:
        entrances = _pack_transitions(entrances, {"transitions": inp["transitions"]})
    # Only the kit's transitions: each other one becomes the nearest the kit
    # allows, or a hard cut.
    entrances = brandkit.limit_transitions(entrances, kit)
    if teaser_info and teaser_info.get("flashes"):
        # A flash and the shot after the last one are hard cuts.
        for i in range(len(entrances)):
            if bool((shots[i] if i < len(shots) else {}).get("teaser")) or (
                    i > 0 and bool((shots[i - 1] if i - 1 < len(shots) else {}).get("teaser"))):
                entrances[i] = "none"
    if pack:
        image_look = templates.image_treatment(pack.get("imageTreatment", "")) or {}
    else:
        image_look = {}
    stills_seen = 0

    seen_figures: Dict[tuple, float] = {}
    anim_counts: Dict[str, int] = {}
    for i, seg in enumerate(segments):
        shot = shots[i] if i < len(shots) else {}
        asset = assets[i] if i < len(assets) else None
        start, duration = bounds[i], bounds[i + 1] - bounds[i]

        animation = None
        if pack and vt.wants_animation(seg, shot, asset, brief, seen=seen_figures):
            animation = vt.animation_for(seg, shot, pack, brief, counts=anim_counts)
            vt.note_figure(seen_figures, seg, animation)
        if animation:
            # A data beat: the number, money or comparison graphic full
            # screen on the blurred nearest clip.
            media = {"type": "animation", "url": "", "source": "template"}
            motion = "none"
            review = asset is None
            reason = ("No footage found — a motion graphic fills this beat (keep it or replace the clip)"
                      if asset is None else "")
        elif asset is None:
            media = {"type": "color", "url": "", "source": "none"}
            motion = "none"
            review, reason = True, "No media found for this beat"
        else:
            media = asset.to_scene_media()
            motion = "none"
            if asset.kind == "image":
                # The n-th still takes the n-th move: consecutive stills never match.
                # A style may hold real photos still (config.STILL_MOTION "none"):
                # the reference weather channel shows ~150 photos, none with a
                # zoom or pan (measured 2026-09-30).
                if str(getattr(config, "STILL_MOTION", "") or "").lower() == "none":
                    motion = "none"
                else:
                    motion = _IMAGE_MOTIONS[stills_seen % len(_IMAGE_MOTIONS)]
                stills_seen += 1
            if asset.kind == "video":
                # The clip's real length. A clip cut for the planned line can
                # come out shorter than the final scene (a real job: 3.48 s of
                # footage in a 5.10 s scene) and the scene then ended in
                # black; the renderer slows such a clip to fill its scene.
                clip_s = _clip_seconds(asset)
                if clip_s:
                    media["clipSeconds"] = round(clip_s, 2)
            review, reason = asset.review_required, asset.review_reason

        scenes.append({
            "id": f"s{i:04d}",
            "startFrame": start,
            "durationInFrames": duration,
            "text": seg.text,
            **({"teaser": True} if shot.get("teaser") else {}),
            "query": shot.get("query", ""),
            "visualType": "animation" if animation else shot.get("visualType", "footage"),
            "media": media,
            **({"animation": animation} if animation else {}),
            "motion": motion,
            "treatment": (image_look.get("treatment") if image_look and asset is not None
                          and asset.kind == "image" and shot.get("treatment", "film") == "film"
                          else shot.get("treatment", "film")),
            "transition": entrances[i] if i < len(entrances) else "none",
            "frame": pick_frame(asset, shot.get("treatment", "film"),
                                shot.get("subjectType", "")),
            "effect": ("none" if asset is None
                       else image_look.get("effect", _EFFECT_CYCLE[i % len(_EFFECT_CYCLE)])
                       if image_look and asset.kind == "image"
                       else _EFFECT_CYCLE[i % len(_EFFECT_CYCLE)]),
            "semanticMetadata": {
                "intent": shot.get("intent", ""),
                "subject": shot.get("subject", ""),
                "subjectType": shot.get("subjectType", ""),
                "searchQuery": shot.get("query", ""),
                "eventWindow": shot.get("eventWindow", ""),
                "contentDescription": getattr(asset, "content_description", "") or "",
                "relevanceScore": getattr(asset, "relevance_score", None),
                "qualityScore": getattr(asset, "quality", None),
                # How that verdict was reached (media.MediaAsset.judged_by) and, for a hook clip, the
                # opening check on this very cut (src/hookcheck.py).
                **({"judgedBy": asset.judged_by} if asset is not None and getattr(asset, "judged_by", "") else {}),
                **({"cutCheck": dict(asset.cut_check)} if asset is not None and getattr(asset, "cut_check", None)
                   else {}),
                "provider": getattr(asset, "source", "") or "",
                # What makes this clip this clip (video id + moment), so the
                # clip library can keep and re-find it.
                "assetId": getattr(asset, "identity", "") if asset is not None else "",
                "sourceUrl": (getattr(asset, "url", "") or "") if asset is not None
                and str(getattr(asset, "url", "") or "").startswith("http") else "",
                # A web picture's page and the search engine's small copy of it:
                # what fetching it again falls back to when its host refuses
                # (imagefix.fetch), so a restore (src/restore.py) can ask the
                # same way the plan did. Left out when the shot has none.
                **({"pageUrl": asset.page_url} if asset is not None and getattr(asset, "page_url", "") else {}),
                **({"sourceThumbnail": asset.thumbnail} if asset is not None
                   and getattr(asset, "thumbnail", "") else {}),
                # The typed intent the scene was sourced against, the judge's
                # class of the frames, and the runner-up clips for Replace Clip.
                "sceneIntent": shot.get("sceneIntent") or None,
                "specificity": (getattr(asset, "specificity", "") or "") if asset is not None else "",
                "alternatives": (list(getattr(asset, "alternatives", None) or [])[:4]
                                 if asset is not None else []),
                "finalScore": getattr(asset, "final_score", None) if asset is not None else None,
                "scoreParts": dict(getattr(asset, "score_parts", None) or {}) if asset is not None else {},
                "moment": dict(getattr(asset, "moment", None) or {}) if asset is not None else {},
                "candidates": dict(getattr(asset, "pool", None) or {}) if asset is not None else {},
            },
            "words": [{"text": w.text, "start": w.start, "end": w.end}
                      for w in seg.words],
            "reviewRequired": bool(review),
            "reviewReason": reason or "",
        })

        overlay = shot.get("overlay")
        if overlay and overlay["type"] in {"photo-card", "name-card"}:
            # Bind only this beat's sourced, reviewed image. Never substitute a
            # previous scene's person or generate a portrait to fill a card.
            if asset is not None and asset.kind == "image" and not review:
                overlay = {**overlay, "media": [media]}
            else:
                overlay = None
        if overlay:
            # A graphic runs for as long as it needs to be read, not for as
            # long as the beat that introduced it — so it can span later cuts.
            want = int(round(_OVERLAY_SECONDS.get(overlay["type"], 3.5) * fps))
            overlay = with_motion(overlay, len(overlays))
            overlays.append({**overlay,
                             "startFrame": start,
                             "durationInFrames": min(max(duration, want), total - start)})

    # The hook booster: a slow push on the opening's stills and static clips.
    push_stats = hookboost.push_in(scenes, assets, fps) if hookboost.enabled() else None
    if hookboost.enabled():
        hookboost.LAST["quietedKeys"] = set()      # counted by the planner (treatments._place)

    if inp.get("title_overlay"):
        overlays.insert(0, {
            "type": "title", "text": str(inp["title_overlay"])[:240],
            "startFrame": int(round(1.0 * fps)),
            "durationInFrames": min(int(round(3.5 * fps)), max(1, total - int(round(1.0 * fps)))),
        })

    music: Dict[str, Any] = {"sections": [], "duck": 0.55}
    treatment_counts: Dict[str, Any] = {}
    sfx_list = plan_sfx(overlays, fps, config.SFX_MIN_GAP_SECONDS)
    # The looks' own sounds (remotion LookSounds): set by the planner that
    # knows them; without it the rows above carry every sound, as before.
    look_sounds: Optional[Dict[str, Any]] = None
    # The source tags the planner placed (src/sources.py, config.SOURCE_TAGS), for meta: which words named each.
    source_tags: List[dict] = []
    # The real data graphics' report (src/datagraphics.py, config.DATA_GRAPHICS): every fact, shown or why not.
    data_graphics: Optional[Dict[str, Any]] = None
    if pack:
        title_card = [o for o in overlays if o.get("type") == "title" and inp.get("title_overlay")
                      and o.get("text") == str(inp["title_overlay"])[:240]]
        # The job's title card holds its seconds: the planner lays nothing over it.
        reserved = [(o["startFrame"] / fps, (o["startFrame"] + o["durationInFrames"]) / fps) for o in title_card]
        planned = vt.plan(segments, shots, scenes, fps, total, brief, pack, _OVERLAY_SECONDS,
                          voice_lufs=voice_lufs, reserved=reserved,
                          video_style=str(inp.get("video_style") or ""))
        overlays = title_card + planned["overlays"]
        for i, scene in enumerate(scenes):
            if i < len(planned["treatments"]):
                scene["visualTreatment"] = planned["treatments"][i]
        sfx_list = planned["sfx"]
        music = planned["music"]
        treatment_counts = planned["counts"]
        look_sounds = planned.get("lookSounds")
        source_tags = list(planned.get("sources") or [])
        data_graphics = planned.get("dataGraphics")
        if data_graphics:
            # A narration number the official data does not bear out: flagged, never "corrected".
            from . import datagraphics
            warnings.extend(datagraphics.warnings_for(data_graphics))
    # Every image look gets a real picture for every slot (the scene's own,
    # then nearby ones of the same subject, then the clip library), or a look
    # that needs fewer, or none (the owner's Lake Powell video: empty slots).
    pictures = vt.bind_look_pictures(overlays, scenes, library=library, story=brief)
    # The kit's second colour on its figures and charts (overlays.tsx accentFor "accent2").
    brandkit.second_colour(overlays, scenes, kit)
    if pictures["swapped"] or pictures["dropped"]:
        print(f"[timeline] image looks: {pictures['bound']} bound, {pictures['swapped']} became one-picture looks, "
              f"{pictures['dropped']} left out (no picture)", flush=True)
    busy = list(sfx_list) + (sfxplan.builtin_busy(overlays, scenes, fps) if look_sounds is not None else [])
    # The owner's overlay transition pack: a few chosen cuts take a clip that
    # brings its own sound, so only where no other sound is on that beat
    # (config.TRANSITION_PACK, a job's "transition_pack"; a job that pins its
    # own "transitions" list gets them only when it names "pack").
    want_pack = inp.get("transition_pack")
    pinned = inp.get("transitions") if isinstance(inp.get("transitions"), list) else []
    # The brand kit's pack clips only (none allowed: no pack transitions).
    clips = brandkit.pack_clips(kit)
    if (want_pack if isinstance(want_pack, bool) else config.TRANSITION_PACK) and (
            not pinned or any(str(t).startswith("pack") for t in pinned)) and (clips is None or clips):
        from . import styles as video_styles
        rhythm = video_styles.pack_rhythm(str(inp.get("video_style") or ""), style)
        apply_pack_transitions(scenes, plan_pack_transitions(segments, shots, bounds, fps, rhythm, brief, busy,
                                                             allowed=clips),
                               fps, float(rhythm.get("clear", 3.0)), voice_lufs=voice_lufs)
    # Each transition's own sound, peaking on its cut, unless a graphic's
    # sound is already there (a row, or the sound built into a look); then
    # every sound under its ceiling. A pack transition plays its own: none here.
    soft_cuts = hookboost.cut_sounds(scenes, fps) if hookboost.enabled() else {}
    sfx_list = sorted(list(sfx_list) + plan_transition_sfx(
                          scenes, fps, busy, (pack or {}).get("sfxIntensity", 1.0), voice_lufs=voice_lufs,
                          soft=soft_cuts or None),
                      key=lambda s: int(s.get("startFrame", 0)))
    for fx in sfx_list:
        top = sfxplan.cap(voice_lufs, str(fx.get("name") or ""))
        if isinstance(fx.get("volume"), (int, float)) and fx["volume"] > top:
            fx["volume"] = round(top, 3)

    # Music under every video, set against the voice (music_automation).
    story_text = " ".join(s.text for s in segments[:60])
    bgm = _bgm_for(inp, pack, brief, audio_duration, story_text=story_text)
    if bgm:
        own_level = inp.get("bgm_volume") if "bgm_volume" in inp else None
        own_level = (float(own_level) if isinstance(own_level, (int, float)) and not isinstance(own_level, bool)
                     else None)
        if own_level is None and config.MUSIC_LEVEL > 0:
            # The owner's level (20%), the same in every video and in the editor.
            music = music_flat(music, bgm, fps, total, voice_lufs, config.MUSIC_LEVEL)
        else:
            music = music_automation(music, bgm, segments, fps, total, voice_lufs, level=own_level)
        bgm["volume"] = music["levels"]["speech"]

    missing = sum(1 for a in assets if a is None)
    if missing:
        warnings.append(f"{missing} scene(s) have no media and will render black.")

    hook_boost = None
    if hookboost.enabled() or teaser_info:
        hook_boost = {"enabled": hookboost.enabled(), "seconds": hookboost.window(),
                      "opening": hookboost.opening_stats(scenes, fps)}
        if hookboost.enabled():
            hook_boost.update(
                pushIns=push_stats, cutSounds=len(soft_cuts),
                quietedGraphics=len(hookboost.LAST.get("quietedKeys") or ()),
                strongestFirst={"motionWeight": hookboost.motion_weight(),
                                "dramaBonus": float(getattr(config, "HOOK_BOOST_DRAMA", 0.0) or 0.0)})
        if teaser_info:
            hook_boost["teaser"] = teaser_info

    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "fps": fps,
        "width": width,
        "height": height,
        "durationInFrames": total,
        "audio": {"url": audio_url, "volume": float(inp.get("audio_volume", 1.0))},
        "bgm": bgm,
        "captions": {
            "enabled": keep_captions,
            "position": brand.get("captionPosition", "bottom"),
            "accent": brand.get("accent", "#FFD400"),
            "fontFamily": brand.get("fontFamily", "Inter"),
            # The subtitle style shown when the user switches captions on: theirs (an older id draws as
            # its closest new style), else Netflix - the style pack no longer picks one (the owner,
            # 2026-10-05: clean Netflix-like subtitles by default).
            "style": templates.caption_style_id(inp.get("caption_style")),
        },
        "music": music,
        "scenes": scenes,
        "overlays": overlays,
        "sfx": (sfx_list if inp.get("sfx", config.SFX_ENABLED) else []),
        "sfxVolume": float(inp.get("sfx_volume", config.SFX_VOLUME)),
        "sfxEnabled": bool(inp.get("sfx", config.SFX_ENABLED)),
        # Present: every look plays the sound built into it (at this intensity,
        # against meta.voiceLufs); the sfx rows are transitions and the editor's own.
        **({"lookSounds": look_sounds} if look_sounds is not None else {}),
        # The brand kit's identity for the renderer: colours, font, watermark,
        # intro and outro (their frames are written at render: brandkit.prepare_render).
        **({"brand": brandkit.doc_brand(kit)} if kit else {}),
        "meta": {
            # The kit and the picks this video was planned with (render-time
            # repairs and Replace Clip keep to them).
            **({"brandKit": brandkit.meta(kit)} if kit else {}),
            "schemaVersion": SCHEMA_VERSION,
            "sceneCount": len(scenes),
            "overlayCount": len(overlays),
            "treatments": treatment_counts,
            "stylePack": (pack or {}).get("id", ""),
            "planner": planner,
            "sourcePolicy": "stock_allowed" if config.ALLOW_STOCK else "no_stock",
            "cutsPerMinute": round(len(scenes) / max(audio_duration / 60, 0.01), 1),
            "sources": sorted({a.source for a in assets if a}),
            "scenesWithoutMedia": missing,
            "scenesNeedingReview": sum(1 for s in scenes if s["reviewRequired"]),
            # Image looks: given their pictures, made one-picture looks, left out (bind_look_pictures).
            "lookPictures": pictures,
            "generatedScenes": sum(1 for a in assets if a and a.source == "generated"),
            # The narration's loudness every sound and the music were set against.
            "voiceLufs": round(float(voice_lufs), 1),
            "voiceLufsSource": voice_how,
            "warnings": warnings,
            **({"hookBoost": hook_boost} if hook_boost else {}),
            # On-screen sources: each tag with the narration's words that named its source (never invented).
            **({"sourceTags": {"placed": source_tags}} if source_tags else {}),
            # Real data graphics: each fact the narration stated, its chart or why not, and its number checked.
            **({"dataGraphics": data_graphics} if data_graphics else {}),
        },
    }
    if getattr(config, "DATA_LOOKS", True) and pack:
        # Every date, time, year, percentage, multiplier and meaningful number on its word as a clean KT look,
        # the retired looks rewritten, and every look its full animation in one lane (src/datalooks.py).
        try:
            from . import datalooks
            report = datalooks.finish(doc)
            doc["meta"]["overlayCount"] = len(doc["overlays"])
            # A transition's sound never lands within a second of a look's own, nor over it (as when it was
            # planned): the re-planned looks bring their sounds to new frames, so a clashing cut goes quiet.
            near = sfxplan.doc_look_sounds(doc)
            if near:
                def _clear(tr: dict) -> bool:
                    a, d = int(tr.get("startFrame") or 0), int(tr.get("durationFrames") or 0)
                    return not any(abs(a - s["startFrame"]) <= 30 or (s["startFrame"] < a + d
                                                                      and a < s["startFrame"] + s["frames"])
                                   for s in near)
                doc["sfx"] = [s for s in doc.get("sfx") or [] if s.get("kind") != "transition" or _clear(s)]
            doc["meta"]["dataLooks"] = {k: report[k] for k in ("addedByLook", "shortBefore", "shortAfter")} | {
                "dropped": len(report["dropped"]), "removed": len(report["removed"])}
            print(f"[timeline] data looks: {report['addedByLook']}; {len(report['removed'])} old figure look(s) "
                  f"replaced, {len(report['dropped'])} left out for room; short looks {report['shortBefore']} -> "
                  f"{report['shortAfter']}", flush=True)
        except Exception as e:  # noqa: BLE001 - the plan as it was is still a video
            print(f"[timeline] data looks skipped: {type(e).__name__}: {str(e)[:160]}", flush=True)
    return doc


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _integer(value, name: str, lo: int, hi: int) -> int:
    # bool is an int subclass in Python; True would sail through as 1.
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{name} must be a whole number from {lo} to {hi}")
    return value


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


# Photo looks the renderer fills from the story's own pictures when they carry
# none (Main.tsx renderOverlay): the collage from the following scenes' stills,
# the case-file looks from the still of the scene under them.
_BORROWING_VARIANTS = {"collage", "board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"}


def _borrows_pictures(ov: dict) -> bool:
    if (ov.get("variant") or "") in _BORROWING_VARIANTS:
        return True
    if isinstance(ov.get("mediaFrom"), list) and ov["mediaFrom"]:
        return True             # the scenes the planner chose (treatments.bind_look_pictures)
    t = templates.get(ov.get("template") or "") or {}
    tags = t.get("tags") or []
    return "still" in tags or "stills" in tags


def drop_invalid_overlays(doc: dict) -> int:
    """
    Remove overlays that would fail validation, with a warning each, so one
    malformed graphic never fails a video that already spent its sourcing.
    """
    overlays = doc.get("overlays")
    if not isinstance(overlays, list):
        return 0
    # The same line's text card twice on the same frames (a recut pass ran the ladder again): one stays.
    from . import screentext
    screentext.dedupe_cards(overlays)
    total = int(doc.get("durationInFrames") or 0)
    kept, dropped = [], []
    for i, ov in enumerate(overlays):
        try:
            _validate_overlay(ov, i, total)
            kept.append(ov)
        except ValueError as e:
            dropped.append(str(e))
    if dropped:
        doc["overlays"] = kept
        meta = doc.setdefault("meta", {})
        meta.setdefault("warnings", []).append(
            f"{len(dropped)} graphic(s) left out: {'; '.join(dropped[:3])}")
        print(f"[timeline] dropped {len(dropped)} overlay(s): {dropped[:3]}", flush=True)
    return len(dropped)


def _validate_overlay(ov: Any, index: int, total: int) -> None:
    where = f"Overlay {index + 1}"
    if not isinstance(ov, dict):
        raise ValueError(f"{where} is not an object")
    if ov.get("type") not in TEMPLATES:
        raise ValueError(f"{where}: unknown animation template {ov.get('type')!r}")
    start = _integer(ov.get("startFrame"), f"{where} start", 0, total - 1)
    length = _integer(ov.get("durationInFrames"), f"{where} duration", 1, total)
    if start + length > total:
        raise ValueError(f"{where} runs past the end of the narration")

    kind = ov["type"]
    if kind == "map":
        places = ov.get("locations")
        if not isinstance(places, list) or not places:
            raise ValueError(f"{where}: a map needs at least one verified location")
        for p in places:
            if not isinstance(p, dict) or not str(p.get("label", "")).strip():
                raise ValueError(f"{where}: every map location needs a label")
            for key, limit in (("lat", 90), ("lon", 180)):
                if abs(_number(p.get(key), f"{where} {key}")) > limit:
                    raise ValueError(f"{where}: {key} is out of range")
    elif kind in {"split", "photo-card", "name-card"}:
        media = ov.get("media")
        minimum = 2 if kind == "split" else 1
        if not isinstance(media, list) or len(media) < minimum:
            if kind != "split" and _borrows_pictures(ov):
                return          # the renderer fills it from the scenes' own pictures
            raise ValueError(f"{where}: a split screen needs two media assets"
                             if kind == "split" else
                             f"{where}: {kind} needs a real image asset")
        if kind != "split" and any(not isinstance(m, dict) or m.get("type") != "image" or not m.get("url") for m in media):
            raise ValueError(f"{where}: image cards need real image assets")
    elif kind == "stat":
        _number(ov.get("value"), f"{where} value")
    elif kind in {"bar-chart", "comparison"}:
        items = ov.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError(f"{where}: a chart needs at least two items")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{where}: malformed chart item")
            _number(item.get("value"), f"{where} item value")
    elif kind == "timeline":
        items = ov.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError(f"{where}: a timeline needs at least two entries")


def validate(doc: Any, require_media: bool = True,
             allow_stock: bool = None) -> Dict[str, Any]:
    """
    Check a timeline document before spending a render on it.

    Raises ValueError with a message meant to be shown to the user. Set
    require_media=False to validate a plan that the editor is still filling in.
    One thing is corrected rather than refused: a sound effect set louder than
    the voice-relative cap (the editor's volume sliders reach 100%) is brought
    down to it (cap_sfx_levels).
    """
    allow_stock = config.ALLOW_STOCK if allow_stock is None else allow_stock
    if not isinstance(doc, dict):
        raise ValueError("Timeline must be an object")

    fps = _integer(doc.get("fps"), "fps", 12, 120)
    width = _integer(doc.get("width"), "width", 320, 3840)
    height = _integer(doc.get("height"), "height", 180, 2160)
    if width % 2 or height % 2:
        # h.264 chroma subsampling needs even dimensions; ffmpeg refuses odd ones.
        raise ValueError("Video width and height must both be even numbers")
    total = _integer(doc.get("durationInFrames"), "durationInFrames", 1, fps * 7200)

    audio = doc.get("audio")
    if not isinstance(audio, dict) or not str(audio.get("url", "")).strip():
        raise ValueError("Timeline has no narration audio — the render would be silent")

    scenes = doc.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 4000:
        raise ValueError("Timeline needs between 1 and 4000 scenes")

    cursor = 0
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i + 1} is not an object")
        start = _integer(scene.get("startFrame"), f"Scene {i + 1} start", 0, total - 1)
        length = _integer(scene.get("durationInFrames"), f"Scene {i + 1} duration", 1, total)
        if start != cursor:
            raise ValueError(
                f"Scene {i + 1} starts at frame {start} but the previous scene ends at "
                f"{cursor} — the visual track must stay flush with the narration")
        cursor += length

        media = scene.get("media")
        if not isinstance(media, dict):
            raise ValueError(f"Scene {i + 1} has no media object")
        source = str(media.get("source", "")).lower()
        if not allow_stock and source in _STOCK_SOURCES:
            raise ValueError(
                f"Scene {i + 1} uses {source} footage; this workflow is no-stock "
                "(set ALLOW_STOCK=1 to override)")
        if require_media and (media.get("type") == "color" or
                              (media.get("type") != "animation" and not media.get("url"))):
            raise ValueError(f"Scene {i + 1} still needs media before it can render")

    if cursor != total:
        raise ValueError(
            f"Scenes cover {cursor} frames but the narration is {total} — "
            "the visual track must cover it exactly")

    overlays = doc.get("overlays")
    if overlays is not None:
        if not isinstance(overlays, list):
            raise ValueError("overlays must be a list")
        for i, ov in enumerate(overlays):
            _validate_overlay(ov, i, total)

    cap_sfx_levels(doc)
    return doc
