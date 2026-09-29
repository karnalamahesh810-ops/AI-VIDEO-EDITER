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
import subprocess
import zlib
from typing import Any, Dict, List, Optional

from . import config, templates
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

# The sound a transition makes, and how loud (0-1 before the master slider).
# Its loudest point (sfx_meta.json "peak") lands on the cut. Soft transitions
# get a whisper of air; a dip through black is silent, as an editor leaves it.
_TRANSITION_SFX = {
    "glitch": ("glitch-short", 0.13), "vhs-glitch": ("glitch-short", 0.12),
    "flash": ("flash-hit", 0.13), "chromatic-flash": ("flash-hit", 0.13),
    "whip-pan": ("swipe", 0.13), "zoom-punch": ("swipe", 0.12),
    "film-burn": ("whoosh-soft", 0.09), "light-leak": ("whoosh-soft", 0.07),
    "blur-dissolve": ("whoosh-soft", 0.07), "shake-cut": ("boom-soft", 0.13),
    # The older entrances an editor can still pick.
    "whip": ("swipe", 0.12), "punch": ("swipe", 0.1), "zoom": ("whoosh-soft", 0.07),
    "slide": ("whoosh-soft", 0.07), "mosaic": ("glitch-short", 0.09),
}
# Another sound this close (seconds) to a transition's sound silences the transition's.
_TRANSITION_SFX_CLEARANCE = 1.0

# Used when public/sfx/sfx_meta.json cannot be read (duration, peak seconds).
_SFX_META_FALLBACK = {
    "glitch-short": {"duration": 0.5, "peak": 0.175}, "flash-hit": {"duration": 0.62, "peak": 0.075},
    "swipe": {"duration": 0.44, "peak": 0.195}, "whoosh-soft": {"duration": 1.12, "peak": 0.419},
    "boom-soft": {"duration": 1.71, "peak": 0.309},
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
BGM_TRACKS = {
    "investigative": (("investigative-v5", 1800), ("investigative-20m", 1199), ("investigative", 720)),
    "suspense": (("suspense-v2", 1800), ("suspense", 720)),
    "crime": (("crime-v1", 1800), ("crime", 720)),
}
BGM_GENRES = tuple(BGM_TRACKS)
_BGM_BY_KIND = {"news": "suspense", "weather": "suspense", "disaster": "suspense",
                "history": "investigative", "biography": "investigative", "science": "investigative",
                "explainer": "investigative", "nature": "investigative", "other": "investigative"}


def _bgm_track(genre: str, seconds: float, seed: str) -> str:
    """
    A track of the genre long enough to play under the whole narration without
    looping (else the longest ones, which loop), varied between projects by a
    stable seed. The old 12-minute beds are only used when a job names them.
    """
    tracks = BGM_TRACKS[genre]
    fresh = [name for name, length in tracks[:-1]] or [tracks[0][0]]
    long_enough = [name for name, length in tracks[:-1] if length >= seconds] or fresh
    return long_enough[zlib.crc32(seed.encode("utf-8")) % len(long_enough)]


def _bgm_for(inp: Dict[str, Any], pack: Optional[dict], brief: Optional[dict],
             seconds: float = 0.0) -> Optional[dict]:
    if inp.get("bgm_url"):
        return {"url": str(inp["bgm_url"]), "volume": float(inp.get("bgm_volume", 0.12))}
    if not inp.get("bgm", config.BGM_AUTO) or not pack:
        return None
    genre = str(inp.get("bgm_genre") or _BGM_BY_KIND.get((brief or {}).get("kind") or "", "investigative"))
    names = {name for tracks in BGM_TRACKS.values() for name, _ in tracks}
    track = str(inp.get("bgm_track") or "")
    # The editor's music list names tracks ("investigative-v5") in bgm_genre; a
    # plain genre ("investigative") still means "the best track of that genre".
    if not track and genre in names and genre not in BGM_GENRES:
        track = genre
    if track in names:
        genre = next(g for g, tracks in BGM_TRACKS.items() if any(n == track for n, _ in tracks))
    if genre not in BGM_GENRES:
        genre = "investigative"
    if track not in names:
        track = _bgm_track(genre, seconds, str(inp.get("project_id") or inp.get("title") or ""))
    return {"url": f"bgm://{track}", "volume": float(inp.get("bgm_volume", 0.12)), "genre": genre,
            "track": track}


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


def plan_transition_sfx(scenes: List[dict], fps: int, others: List[dict]) -> List[dict]:
    """
    A quiet sound for each transition, placed so its loudest point lands on
    the cut. Skipped when another sound starts within a second of it: a
    graphic's own sound on that beat wins, and two sounds never stack.
    """
    meta = sfx_meta()
    have = templates.sfx_files()
    near = int(round(_TRANSITION_SFX_CLEARANCE * fps))
    taken = [int(o.get("startFrame", 0)) for o in others]
    picks = []
    for sc in scenes:
        t = sc.get("transition") or "none"
        if t not in _TRANSITION_SFX:
            continue
        name, volume = _TRANSITION_SFX[t]
        if have and name not in have:
            continue
        m = meta.get(name) or _SFX_META_FALLBACK.get(name) or {"duration": 1.0, "peak": 0.0}
        cut = int(sc.get("startFrame", 0))
        start = cut - int(round(float(m.get("peak", 0.0)) * fps))
        if cut <= 0 or start < 0:
            continue
        if any(abs(o - start) <= near or abs(o - cut) <= near for o in taken):
            continue
        picks.append({"name": name, "startFrame": start, "volume": volume,
                      "durationFrames": max(1, int(math.ceil(float(m.get("duration", 1.0)) * fps))),
                      "kind": "transition"})
        taken.append(start)
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
          planner: str = "rules", warnings: List[str] = None) -> Dict[str, Any]:
    """Assemble the render document from beats, shot plan and sourced media."""
    warnings = list(warnings or [])
    fps = int(inp.get("fps") or config.DEFAULT_FPS)
    width = int(inp.get("width") or config.DEFAULT_WIDTH)
    height = int(inp.get("height") or config.DEFAULT_HEIGHT)
    brand = inp.get("brand") or {}
    total = max(1, int(round(audio_duration * fps)))
    bounds = _scene_bounds(segments, fps, total)

    scenes: List[Dict[str, Any]] = []
    overlays: List[Dict[str, Any]] = []
    # Off unless asked for: captions are a choice made in the editor, and a
    # burned-in default is the first thing a creator has to undo. Word
    # timings are stored either way, so switching them on later gets real
    # word-synced phrases instead of a scene's whole text at once.
    keep_captions = bool(inp.get("captions", False))

    # The visual treatment planner (src/treatments.py): the style pack decides
    # the looks, the narration decides where a treatment goes.
    from . import director, treatments as vt
    brief = inp.get("brief") if isinstance(inp.get("brief"), dict) else dict(director.LAST_STORY)
    pack = vt.pack_for(brief, str(inp.get("style_pack") or config.STYLE_PACK or "")) if config.TREATMENTS else None
    # Transitions follow the cutting style (a documentary mostly hard-cuts, a
    # news edit punctuates); a job can still pin the allowed set.
    style = transition_style(inp, pack, brief)
    entrances = plan_transitions(list(shots) + [{}] * max(0, len(segments) - len(shots)), style,
                                 durations=[bounds[i + 1] - bounds[i] for i in range(len(segments))])
    if isinstance(inp.get("transitions"), list) and inp["transitions"]:
        entrances = _pack_transitions(entrances, {"transitions": inp["transitions"]})
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
                "provider": getattr(asset, "source", "") or "",
                # What makes this clip this clip (video id + moment), so the
                # clip library can keep and re-find it.
                "assetId": getattr(asset, "identity", "") if asset is not None else "",
                "sourceUrl": (getattr(asset, "url", "") or "") if asset is not None
                and str(getattr(asset, "url", "") or "").startswith("http") else "",
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

    if inp.get("title_overlay"):
        overlays.insert(0, {
            "type": "title", "text": str(inp["title_overlay"])[:240],
            "startFrame": int(round(1.0 * fps)),
            "durationInFrames": min(int(round(3.5 * fps)), max(1, total - int(round(1.0 * fps)))),
        })

    music: Dict[str, Any] = {"sections": [], "duck": 0.55}
    treatment_counts: Dict[str, Any] = {}
    sfx_list = plan_sfx(overlays, fps, config.SFX_MIN_GAP_SECONDS)
    if pack:
        planned = vt.plan(segments, shots, scenes, fps, total, brief, pack, _OVERLAY_SECONDS)
        title_card = [o for o in overlays if o.get("type") == "title" and inp.get("title_overlay")
                      and o.get("text") == str(inp["title_overlay"])[:240]]
        overlays = title_card + planned["overlays"]
        for i, scene in enumerate(scenes):
            if i < len(planned["treatments"]):
                scene["visualTreatment"] = planned["treatments"][i]
        sfx_list = planned["sfx"]
        music = planned["music"]
        treatment_counts = planned["counts"]
    # Each transition's own quiet sound, peaking on its cut, unless a
    # graphic's sound is already there.
    sfx_list = sorted(list(sfx_list) + plan_transition_sfx(scenes, fps, sfx_list),
                      key=lambda s: int(s.get("startFrame", 0)))

    missing = sum(1 for a in assets if a is None)
    if missing:
        warnings.append(f"{missing} scene(s) have no media and will render black.")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "fps": fps,
        "width": width,
        "height": height,
        "durationInFrames": total,
        "audio": {"url": audio_url, "volume": float(inp.get("audio_volume", 1.0))},
        "bgm": _bgm_for(inp, pack, brief, audio_duration),
        "captions": {
            "enabled": keep_captions,
            "position": brand.get("captionPosition", "bottom"),
            "accent": brand.get("accent", "#FFD400"),
            "fontFamily": brand.get("fontFamily", "Inter"),
            "style": str(inp.get("caption_style") or (pack or {}).get("caption") or "documentary"),
        },
        "music": music,
        "scenes": scenes,
        "overlays": overlays,
        "sfx": (sfx_list if inp.get("sfx", config.SFX_ENABLED) else []),
        "sfxVolume": float(inp.get("sfx_volume", config.SFX_VOLUME)),
        "sfxEnabled": bool(inp.get("sfx", config.SFX_ENABLED)),
        "meta": {
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
            "generatedScenes": sum(1 for a in assets if a and a.source == "generated"),
            "warnings": warnings,
        },
    }


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

    return doc
