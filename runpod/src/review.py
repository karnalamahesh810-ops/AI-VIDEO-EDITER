"""
The AI review (the owner, 2026-10-02: "AI review also good for me, if you can
build that better"): after the render a vision model watches the FINISHED
video scene by scene, fixes what it safely can and lists the rest.

The quality gate (src/quality.py) is technical: a file that will not load, a
black or frozen stretch, a clip shown twice. It cannot SEE. It does not know
that a clip shows a harbour while the line is about a dam, that a stock
agency's name is printed across a photo (the owner, 2026-10-04: "the
watermarked images ... like getty"), that one of our own titles sits on a
face, or that the music is as loud as the voice. Every clip was judged when
it was picked - but alone, before the cut, the graphics and the mix; this is
the one look at the video the viewer will get.

  Review.plan          (handler.do_render, BEFORE the gate's scan of the
                       finished file) which frames to look at and which of
                       our graphics are on them - the document as it was
                       drawn: a repair after the scan merges scenes and drops
                       looks, and the frames come from the file drawn before.
  Review.after_render  (right after the gate's scan)
      1. the picture: one frame per scene at its midpoint (two for a scene
         over 8 s) from the finished file - one short ffmpeg seek per frame,
         several at once; 4-6 scenes a call go to the vision model with their
         narration lines and the names of our own graphics on screen; it
         answers strict JSON, per scene {match 0-1, issues, note}. A scene
         the viewer does not see a clip in (a full-screen graphic, a map, a
         cold-open flash) is not asked about, nor one the gate just replaced.
         Frames that look the same across the whole video are found without
         the model (a tiny picture hash): "repeat".
      2. the sound, no model, measured while the pictures are judged: the
         mix in 50 ms windows (ffmpeg ebur128 + astats) read against the
         narration's own word timings - the music and sounds nearly as loud
         as the voice, music that stops part-way, dead air inside a scene,
         clipping. Listed, never changed.
      3. the fixes (AI_REVIEW_FIX): a picture that does not fit, is
         watermarked, blurry or AI-looking is swapped for the scene's own
         next choice - the pick-a-shot runner-ups, already downloaded and
         judged above the floor, never a shot another scene shows; a title
         over a face moves to the other side (the renderer's align /
         position) or is shortened; a repeat takes its other choice, else a
         fresh shot from the fallback ladder. Everything else is listed.
         Something fixed = the video is drawn once more through the quality
         gate's ONE second render (Gate.join_second_render) - never a third
         draw: when that render is already spent, nothing is changed.
  Review.finish        the report: doc.meta.review, the job result's "review",
                       job_progress.review, an events row review/summary and
                       one plain line - "AI review: 131/133 scenes fit the
                       narration, 2 clips swapped, 1 left for you".

A review never fails a render and never holds one up for long: the whole of
it - frames, model calls, sound, fixes - runs inside AI_REVIEW_SECONDS (and
at most AI_REVIEW_MAX_CALLS calls); no model, no answer, a budget that ran
out or a broken step is "skipped" or "not checked" in the report, and the
video goes out as the gate left it.
"""
from __future__ import annotations

import base64
import bisect
import copy
import json
import math
import os
import re
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout, wait as _wait
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, costs, events, gapfill, quality, templates
from .aifill import is_ai_scene
from .presenter import is_presenter_scene

# --------------------------------------------------------------------------- #
# What the review looks for, and what it may do about it
# --------------------------------------------------------------------------- #

ISSUES = ("mismatch", "text-over-face", "blur", "watermark", "logo", "repeat", "ai-looking", "talking-head", "other")
# A picture with one of these is swapped for the scene's other choice (most telling first).
SWAP_ISSUES = ("mismatch", "watermark", "ai-looking", "blur")
# The fault is the source's own (its watermark, its softness): another moment of the same video has it too.
SOURCE_ISSUES = {"watermark", "ai-looking", "blur", "logo"}
DEFAULT_NOTE = {
    "mismatch": "the picture does not show what the line says",
    "text-over-face": "one of our titles covers a face",
    "blur": "the picture is blurry",
    "watermark": "a watermark is printed on the picture",
    "logo": "another channel's logo or captions are on the picture",
    "repeat": "the shot looks like one already shown",
    "ai-looking": "the picture looks AI-made",
    "talking-head": "someone is talking to the camera",
    "other": "something in the picture looks wrong",
}
# What the model may call an issue, in its own words.
_ALIASES = {"text over face": "text-over-face", "text-on-face": "text-over-face", "blurry": "blur",
            "blurred": "blur", "watermarked": "watermark", "watermarks": "watermark", "repeated": "repeat",
            "duplicate": "repeat", "ai": "ai-looking", "ai-generated": "ai-looking", "ai generated": "ai-looking",
            "talking head": "talking-head", "logos": "logo", "none": "", "ok": "", "no issues": ""}

# A scene longer than this is looked at twice (the task: "two for scenes over 8 s").
LONG_SCENE_SECONDS = 8.0
# The width the model sees a frame at (258 tokens a frame on Gemini at 512 px, src/config.py VISION_FRAME_WIDTH).
FRAME_WIDTH = 512
# The frames are taken one ffmpeg seek each, this many at once, each decoding with this many threads.
# Measured on the owner's real 29-minute Lake Mead video (1080p, 60 fps, 105,000 frames; 16 cores),
# 240 frames: 25 s at 12 x 2 threads, 36 s at 8 with ffmpeg's own thread count. One ffmpeg pass with
# select='eq(n,..)+eq(n,..)...' cannot do it: ffmpeg's expression parser refuses more than ~100 terms
# ("Cannot allocate memory" - 100 frames worked, 110 failed), and it decodes every frame of the file.
FRAME_PARALLEL = 8
FRAME_THREADS = 2
# One seek decodes at most a keyframe interval (~4 s of video in our renders): this is plenty.
FRAME_TIMEOUT = 30.0
# A title has been read after this long (the graphics timing rule: on its word, gone ~2 s later).
SHORT_GRAPHIC_SECONDS = 2.0
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
# Two frames whose 64-bit picture hashes differ in this many bits or fewer are the same picture.
# Measured on 238 frames of the real Lake Mead video (28,000 pairs): the two pairs at 3 bits were
# real repeats (one photo shown at 8:14 and again at 9:20), the closest pair of different pictures
# was 5 bits apart (two of our own graphics on plain backgrounds).
REPEAT_BITS = 4
# Scenes one review may send to the fallback ladder (each can take QUALITY_REPAIR_SCENE_SECONDS).
LADDER_MAX = 6
# The model is never trusted to replace fewer than this many scenes by its share alone.
BRAKE_MIN = 3
_STILL_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"}
# The review's time (AI_REVIEW_SECONDS) is shared out: the frames may take this much of it, the model
# calls leave this much for the fixes, and the sound (measured alongside) gets this much.
FRAMES_SHARE = 0.45
FIX_RESERVE = 0.2
SOUND_SHARE = 0.5

# The sound, measured in windows of this many samples (50 ms at 48 kHz).
WINDOW_SAMPLES = 2400
# Voice against music is judged per stretch of this many seconds.
SECTION_SECONDS = 30.0
# Words closer than this are one run of speech; a gap at least PAUSE long is a
# pause, read PAUSE_TRIM in from each side (the breath and the word's tail).
SPEECH_JOIN = 0.3
PAUSE_SECONDS = 0.45
PAUSE_TRIM = 0.1
# The voice should stand this far over the music and sounds. 3 dB is "nearly
# as loud as the voice": the owner's own mix (music at 50 %, 2026-10-02) is
# his choice and must not be flagged, a bed that buries the words must.
# Measured on the real Lake Mead video (2026-10-03, the owner's mix): the
# voice stood 13.6 to 20 dB over the music in every 30 s section.
VOICE_OVER_BED_DB = 3.0
# Under this the pauses hold no music at all.
BED_SILENT_DB = -55.0
# Dead air: this quiet for this long, inside a scene (a pause between two
# lines sits on a scene boundary and is the narration's own).
DEAD_AIR_DB = -50.0
DEAD_AIR_SECONDS = 2.5
BOUNDARY_NEAR = 0.3
# The sound touching full scale in this many windows is clipping, not one stray peak.
CLIP_DB = -0.1
CLIP_WINDOWS = 3
EVENT_ROWS = 40


def _f(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _db(power: float) -> float:
    return 10.0 * math.log10(power) if power > 0 else -120.0


# --------------------------------------------------------------------------- #
# The finished file: its frames, its sound
# --------------------------------------------------------------------------- #

def probe(path: str) -> dict:
    """{"fps", "duration", "audio"} of the finished file; {} when it cannot be read."""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type,r_frame_rate:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=60)
        info = json.loads(p.stdout or "{}") or {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    fps = 0.0
    for s in info.get("streams") or []:
        if s.get("codec_type") == "video" and not fps:
            num, _, den = str(s.get("r_frame_rate") or "").partition("/")
            a, b = _f(num), _f(den or "1")
            fps = a / b if a and b else 0.0
    if fps <= 0:
        return {}
    return {"fps": fps, "duration": _f((info.get("format") or {}).get("duration")) or 0.0,
            "audio": any(s.get("codec_type") == "audio" for s in info.get("streams") or [])}


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def grab_frames(path: str, numbers: List[int], folder: str, width: int = FRAME_WIDTH,
                timeout: Optional[float] = None, fps: Optional[float] = None) -> Dict[int, str]:
    """
    The frames numbered `numbers` of a finished video (0 = its first), `width`
    px wide, as JPEG files in `folder`: one short ffmpeg run per frame that
    seeks to the keyframe before it and decodes from there, FRAME_PARALLEL at
    once (see FRAME_PARALLEL for why not one pass). `fps` is the file's frame
    rate (probed when not given); `timeout` bounds the whole grab - what is
    not taken by then is not. {frame number: file}; a frame past the end or
    one that failed has no file. Never raises.
    """
    want = sorted({int(n) for n in numbers if int(n) >= 0})
    if not want or not path or not os.path.isfile(path):
        return {}
    rate = float(fps or 0.0) or float(probe(path).get("fps") or 0.0)
    if rate <= 0:
        return {}
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return {}
    deadline = time.time() + max(1.0, float(timeout or config.QUALITY_SCAN_TIMEOUT))

    def one(n: int) -> str:
        left = deadline - time.time()
        if left < 0.5:
            return ""
        out = os.path.join(folder, f"f_{n:07d}.jpg")
        _remove(out)
        # A quarter frame early: the seek lands on frame n itself, never on n + 1.
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-v", "error", "-y", "-threads", str(FRAME_THREADS),
               "-ss", f"{max(0.0, (n - 0.25) / rate):.4f}", "-i", path, "-map", "0:v:0", "-an",
               "-frames:v", "1", "-vf", f"scale={int(width)}:-2", "-q:v", "5", out]
        try:
            subprocess.run(cmd, capture_output=True, timeout=min(FRAME_TIMEOUT, left))
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""

    pool = ThreadPoolExecutor(max_workers=max(1, min(FRAME_PARALLEL, len(want))), thread_name_prefix="review-frame")
    futures = {pool.submit(one, n): n for n in want}
    done, _late = _wait(futures, timeout=max(1.0, deadline - time.time()) + 1.0)
    pool.shutdown(wait=False, cancel_futures=True)
    got: Dict[int, str] = {}
    for fut in done:
        try:
            out = fut.result()
        except Exception:  # noqa: BLE001 - that frame is not looked at
            out = ""
        if out:
            got[futures[fut]] = out
    if not got:
        print(f"[review] no frames could be taken from {os.path.basename(path)}", flush=True)
    return got


_PTS = re.compile(r"pts_time:(-?[\d.]+)")
_RMS = re.compile(r"Overall\.RMS_level=(\S+)")
_PEAK = re.compile(r"Overall\.Peak_level=(\S+)")
_LUFS = re.compile(r"\bI:\s*(-?[\d.]+)\s*LUFS")
_TRUE_PEAK = re.compile(r"\bPeak:\s*(-?[\d.]+)\s*dBFS")
# Newer ffmpeg measures only what is asked for; an older one prints one key.
_STATS = ("astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level+Peak_level,"
          "ametadata=mode=print:file=-",
          "astats=metadata=1:reset=1,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-")


def _level(text: str) -> Optional[float]:
    v = _f(text)
    return v if v is not None else (-120.0 if "inf" in str(text).lower() else None)


def measure_audio(path: str, timeout: Optional[float] = None) -> dict:
    """
    One ffmpeg pass over the finished file's sound (the picture is not
    decoded): its loudness and true peak (ebur128) and the level of every
    50 ms window (astats) - 10 s for the real 29-minute Lake Mead video.
    `timeout` bounds the whole measurement (both forms of the filter).
    {"ok", "why", "windows": [(seconds, rms dB, peak dB or None)], "lufs",
    "truePeak", "seconds"}; ok False when unreadable.
    """
    t0 = time.time()
    out = {"ok": False, "why": "", "windows": [], "lufs": None, "truePeak": None, "seconds": 0.0}
    if not path or not os.path.isfile(path):
        out["why"] = "no finished file"
        return out
    deadline = t0 + max(1.0, float(timeout or config.QUALITY_SCAN_TIMEOUT))
    p = None
    for stats in _STATS:
        left = deadline - time.time()
        if left < 0.5:
            break
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-map", "0:a:0", "-af",
               f"ebur128=peak=true:framelog=verbose,asetnsamples=n={WINDOW_SAMPLES}:p=0,{stats}", "-f", "null", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=left)
        except (OSError, subprocess.TimeoutExpired) as e:
            out["why"] = f"the sound could not be measured ({type(e).__name__})"
            return out
        if p.returncode == 0:
            break
    if p is None or p.returncode != 0:
        out["why"] = f"the sound could not be measured ({(p.stderr or '')[-120:].strip() if p else 'no time left'})"
        return out
    windows: List[list] = []
    for line in (p.stdout or "").splitlines():
        m = _PTS.search(line)
        if m:
            windows.append([float(m.group(1)), None, None])
            continue
        if not windows:
            continue
        m = _RMS.search(line)
        if m:
            windows[-1][1] = _level(m.group(1))
            continue
        m = _PEAK.search(line)
        if m:
            windows[-1][2] = _level(m.group(1))
    err = p.stderr or ""
    lufs, peak = _LUFS.findall(err), _TRUE_PEAK.findall(err)
    out.update(ok=True, windows=[(t, r, pk) for t, r, pk in windows if r is not None],
               lufs=_f(lufs[-1]) if lufs else None, truePeak=_f(peak[-1]) if peak else None,
               seconds=round(time.time() - t0, 1))
    if not out["windows"]:
        out.update(ok=False, why="the sound's levels could not be read")
    return out


# --------------------------------------------------------------------------- #
# The sound's findings (no model)
# --------------------------------------------------------------------------- #

def speech_spans(doc: dict) -> List[Tuple[float, float]]:
    """(start, end) seconds of every run of spoken words on the narration's timeline, words under SPEECH_JOIN apart joined."""
    words = []
    for s in doc.get("scenes") or []:
        for w in (s.get("words") or []) if isinstance(s, dict) else []:
            a, b = _f((w or {}).get("start")), _f((w or {}).get("end"))
            if a is not None and b is not None and b > a:
                words.append((a, b))
    runs: List[List[float]] = []
    for a, b in sorted(words):
        if runs and a - runs[-1][1] < SPEECH_JOIN:
            runs[-1][1] = max(runs[-1][1], b)
        else:
            runs.append([a, b])
    return [(a, b) for a, b in runs]


def _inside(spans: List[Tuple[float, float]], starts: List[float], t: float) -> bool:
    k = bisect.bisect_right(starts, t) - 1
    return k >= 0 and t < spans[k][1]


def audio_findings(doc: dict, measured: dict) -> List[dict]:
    """
    What the measured sound says, as rows {"issue", "at", "note"} with `at` in
    seconds of the narration's timeline (a brand intro's length taken off):
      music-over-voice  the mix while words are spoken against the mix in the
                        pauses between them (the music and sounds alone): the
                        voice less than VOICE_OVER_BED_DB over them;
      music-stops       a video with music whose pauses go silent part-way and
                        stay silent to the end (the owner, 2026-10-04: "the
                        music ... only going 30 seconds");
      dead-air          DEAD_AIR_SECONDS of silence inside a scene;
      clipping          the sound at full scale.
    """
    from . import brandkit
    fps = max(1, int(doc.get("fps") or 30))
    intro, body, _outro, _total = brandkit.layout(doc)
    t0, length = intro / fps, body / fps
    wins = measured.get("windows") or []
    rows: List[dict] = []
    if not wins:
        return rows
    step = (wins[-1][0] - wins[0][0]) / max(1, len(wins) - 1) if len(wins) > 1 else 0.05
    step = step if step > 0 else 0.05
    scenes = doc.get("scenes") or []
    cuts = sorted(int(s.get("startFrame") or 0) / fps for s in scenes[1:])

    # Clipping: anywhere in the file.
    hot = [t for t, _r, pk in wins if pk is not None and pk >= CLIP_DB]
    true_peak = measured.get("truePeak")
    if len(hot) >= CLIP_WINDOWS:
        rows.append({"issue": "clipping", "at": max(0.0, hot[0] - t0),
                     "note": f"the sound hits full scale {len(hot)} times, first at "
                             f"{quality._clock(max(0.0, hot[0] - t0))} - it will crackle"})
    elif not hot and true_peak is not None and true_peak >= 0.0 and all(pk is None for _t, _r, pk in wins):
        rows.append({"issue": "clipping", "at": 0.0,
                     "note": f"the sound peaks at {true_peak:+.1f} dB, over full scale - it may crackle"})

    # Dead air: a quiet stretch inside the narration's timeline, away from every scene boundary.
    run: Optional[List[float]] = None
    quiet: List[Tuple[float, float]] = []
    for t, r, _pk in wins:
        at = t - t0
        if r < DEAD_AIR_DB and 0 <= at < length:
            run = [at, at + step] if run is None else [run[0], at + step]
        elif run is not None:
            quiet.append((run[0], run[1]))
            run = None
    if run is not None:
        quiet.append((run[0], run[1]))
    for a, b in quiet:
        if b - a < DEAD_AIR_SECONDS or a < 0.5 or b > length - 1.0:
            continue
        k = bisect.bisect_left(cuts, a - BOUNDARY_NEAR)
        if k < len(cuts) and cuts[k] <= b + BOUNDARY_NEAR:
            continue                        # the pause between two lines
        rows.append({"issue": "dead-air", "at": a,
                     "note": f"{b - a:.1f} s of silence in the middle of a scene at {quality._clock(a)}"})

    # Voice against the music and sounds, per section, from the narration's own word timings.
    spans = speech_spans(doc)
    if not spans:
        return rows
    starts = [a for a, _b in spans]
    pauses = [(spans[k][1] + PAUSE_TRIM, spans[k + 1][0] - PAUSE_TRIM) for k in range(len(spans) - 1)
              if spans[k + 1][0] - spans[k][1] >= PAUSE_SECONDS]
    pause_starts = [a for a, _b in pauses]
    sections: Dict[int, Dict[str, List[float]]] = {}
    for t, r, _pk in wins:
        at = t - t0 + step / 2
        if not 0 <= at < length:
            continue
        kind = "speech" if _inside(spans, starts, at) else "pause" if _inside(pauses, pause_starts, at) else ""
        if kind:
            sections.setdefault(int(at // SECTION_SECONDS), {"speech": [], "pause": []})[kind].append(10 ** (r / 10.0))
    known: List[Tuple[int, float, float]] = []          # (section, bed dB, voice over bed dB)
    for k in sorted(sections):
        sp, pa = sections[k]["speech"], sections[k]["pause"]
        if len(sp) * step < 1.0 or len(pa) * step < 0.3:
            continue                        # too little of one to compare
        p_speech, p_bed = sum(sp) / len(sp), sum(pa) / len(pa)
        bed = _db(p_bed)
        over = 99.0 if bed < BED_SILENT_DB else _db(max(p_speech - p_bed, 1e-12)) - bed
        known.append((k, bed, over))
    loud = [(k, over) for k, _bed, over in known if over < VOICE_OVER_BED_DB]
    groups: List[List[Tuple[int, float]]] = []
    for k, over in loud:
        if groups and k == groups[-1][-1][0] + 1:
            groups[-1].append((k, over))
        else:
            groups.append([(k, over)])
    for g in groups:
        a, b = g[0][0] * SECTION_SECONDS, min(length, (g[-1][0] + 1) * SECTION_SECONDS)
        worst = min(over for _k, over in g)
        how = "louder than the voice" if worst <= 0 else f"only about {worst:.0f} dB under the voice"
        rows.append({"issue": "music-over-voice", "at": a,
                     "note": f"the music and sounds are {how} from {quality._clock(a)} to {quality._clock(b)}"})
    if isinstance(doc.get("bgm"), dict) and doc["bgm"].get("url") and known:
        on = [k for k, bed, _over in known if bed >= BED_SILENT_DB]
        after = [k for k, _bed, _over in known if on and k > on[-1]]
        if on and len(after) >= 2:
            at = (on[-1] + 1) * SECTION_SECONDS
            rows.append({"issue": "music-stops", "at": at,
                         "note": f"the music stops near {quality._clock(at)} and the rest of the video has none"})
    return sorted(rows, key=lambda r: r["at"])


# --------------------------------------------------------------------------- #
# Which frames, and what is on them
# --------------------------------------------------------------------------- #

@dataclass(eq=False)
class Sample:
    """
    One scene's look, noted from the document as it was drawn: where it is
    sampled, its line and which of our graphics are on screen there. `scene`
    and `overlays` are the document's own objects (the gate's repairs change
    them in place or take them out of the lists, never copy them), so a fix
    finds them wherever they are now. Two samples are the same only when
    they are one object.
    """
    index: int                                              # the scene's place in the document as drawn
    scene_id: str
    frames: List[int] = field(default_factory=list)         # on the narration's timeline
    file_frames: List[int] = field(default_factory=list)    # in the finished file (intro and its frame rate counted)
    graphics: List[int] = field(default_factory=list)       # overlays on screen at a sampled frame (doc.overlays index as drawn)
    scene: Optional[dict] = None
    text: str = ""                                          # the narration line over it
    intent: str = ""                                        # what the planner meant it to show
    names: List[str] = field(default_factory=list)          # our graphics on screen, as the model is told
    overlays: List[dict] = field(default_factory=list)      # those graphics themselves
    at: float = 0.0                                         # where the scene starts, seconds of the narration


def covers(ov: dict) -> bool:
    """A graphic that IS the frame while it shows (a card on a blurred still, a map, a look with its own backdrop)."""
    if not isinstance(ov, dict):
        return False
    t = templates.get(ov.get("template") or "") or {}
    return bool(ov.get("backdrop") == "blur" or ov.get("fullFrame")
                or ov.get("type") in ("title", "chapter", "map", "split")
                or t.get("kind") == "map" or t.get("component") == "map" or "own-backdrop" in (t.get("tags") or []))


def _span(ov: dict) -> Tuple[int, int]:
    a = int(ov.get("startFrame") or 0)
    return a, a + int(ov.get("durationInFrames") or 0)


def _graphic_name(ov: dict) -> str:
    text = " ".join(str(ov.get("text") or ov.get("label") or "").split())[:60]
    kind = str(ov.get("type") or "graphic")
    return f'{kind} "{text}"' if text else kind


def _file_frames(frames: List[int], intro: int, fps: int, rate: float) -> List[int]:
    """Frames of the narration's timeline as frames of the finished file (the brand intro plays first)."""
    return [int(round((intro + f) * rate / fps)) for f in frames]


def plan_samples(doc: dict, file_fps: Optional[float] = None,
                 skip_ids: Optional[set] = None) -> Tuple[List[Sample], Dict[int, str]]:
    """
    (samples, not reviewed {scene index: why}). A scene is looked at where its
    clip can be seen: at its midpoint (30 % and 70 % of a scene over
    LONG_SCENE_SECONDS), moved off a full-screen graphic of ours when one is
    up at that moment. Not reviewed: a scene that is a graphic itself, a
    cold-open flash of a later shot, one wholly under a full-screen graphic,
    and any scene in `skip_ids` (the quality gate has just replaced it).
    """
    from . import brandkit
    fps = max(1, int(doc.get("fps") or 30))
    rate = float(file_fps or fps)
    intro = brandkit.layout(doc)[0]
    overlays = [ov for ov in (doc.get("overlays") or [])]
    shown = doc.get("overlaysEnabled") is not False
    cards = [_span(ov) for ov in overlays if shown and covers(ov)]
    samples: List[Sample] = []
    skipped: Dict[int, str] = {}
    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or f"#{i}")
        m = s.get("media") or {}
        if sid in (skip_ids or ()):
            skipped[i] = "the quality check has just replaced it"
            continue
        if s.get("teaser"):
            skipped[i] = "a cold-open flash of a later shot"
            continue
        if is_presenter_scene(s):
            skipped[i] = "the AI presenter talking (made and checked by its own step)"
            continue
        if is_ai_scene(s):
            skipped[i] = "an AI picture made for its line (AI fill: checked by its own step)"
            continue
        if m.get("type") not in ("video", "image") or not m.get("url"):
            skipped[i] = "a graphic of ours, not a clip"
            continue
        start, length = int(s.get("startFrame") or 0), int(s.get("durationInFrames") or 0)
        if length <= 0:
            continue
        tries = ([0.3, 0.2, 0.4], [0.7, 0.8, 0.6]) if length / fps > LONG_SCENE_SECONDS \
            else ([0.5, 0.35, 0.65, 0.2, 0.8],)
        frames = []
        for options in tries:
            for frac in options:
                f = start + min(length - 1, int(length * frac))
                if not any(a <= f < b for a, b in cards):
                    frames.append(f)
                    break
        if not frames:
            skipped[i] = "under a full-screen graphic of ours"
            continue
        on_screen = [n for n, ov in enumerate(overlays) if shown and isinstance(ov, dict) and not covers(ov)
                     and any(_span(ov)[0] <= f < _span(ov)[1] for f in frames)]
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        samples.append(Sample(index=i, scene_id=sid, frames=frames,
                              file_frames=_file_frames(frames, intro, fps, rate), graphics=on_screen,
                              scene=s, text=" ".join(str(s.get("text") or "").split())[:400],
                              intent=" ".join(str(sem.get("intent") or "").split())[:200],
                              names=[_graphic_name(overlays[n]) for n in on_screen],
                              overlays=[overlays[n] for n in on_screen], at=start / fps))
    return samples, skipped


def groups_of(items: list, size: int) -> List[list]:
    """`items` in order, in the fewest groups of at most `size`, evened out (11 by 5 -> 4, 4, 3; never 5, 5, 1)."""
    n = len(items)
    size = max(1, int(size))
    if n == 0:
        return []
    k = -(-n // size)
    base, extra = divmod(n, k)
    out, at = [], 0
    for g in range(k):
        step = base + (1 if g < extra else 0)
        out.append(items[at:at + step])
        at += step
    return out


def call_order(n: int) -> List[int]:
    """The order the groups are asked in: the opening first, the ending second (a viewer judges a video by
    how it ends), then the middle spread out (gapfill.spread), so a budget that runs out leaves scattered
    gaps - never a whole stretch unseen."""
    if n <= 2:
        return list(range(n))
    return [0, n - 1] + [1 + k for k in gapfill.spread(n - 2)]


def picture_hash(path: str) -> Optional[int]:
    """A 64-bit hash of a frame's upper 70 % (our captions and lower thirds sit below); None for a flat or unreadable one."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            g = im.convert("L").crop((0, 0, w, max(1, int(h * 0.7)))).resize((9, 8))
            px = g.tobytes()
    except Exception:  # noqa: BLE001 - that frame is not compared
        return None
    if len(px) < 72 or max(px) - min(px) < 24:
        return None                         # a dark or empty frame says nothing
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    return bits


def _chained(scene: Optional[dict]) -> bool:
    moment = ((scene or {}).get("semanticMetadata") or {}).get("moment")
    return bool(isinstance(moment, dict) and moment.get("chain"))


def find_look_alikes(doc: dict, samples: List[Sample], pics: Dict[int, str]) -> Dict[int, int]:
    """{scene index: the earlier scene it looks the same as}, by picture hash - across the whole video, which
    no single call of 4-6 scenes can see. A planned chain (the next moment of the clip before it) is not one."""
    scenes = doc.get("scenes") or []
    by_index = {smp.index: smp for smp in samples}

    def scene_of(i: int) -> Optional[dict]:
        smp = by_index.get(i)
        if smp is not None and smp.scene is not None:
            return smp.scene
        return scenes[i] if 0 <= i < len(scenes) and isinstance(scenes[i], dict) else None
    seen: List[Tuple[int, int]] = []
    out: Dict[int, int] = {}
    for smp in samples:
        path = pics.get(smp.file_frames[0]) if smp.file_frames else None
        h = picture_hash(path) if path else None
        if h is None:
            continue
        for j, other in seen:
            if bin(h ^ other).count("1") > REPEAT_BITS:
                continue
            if smp.index - j == 1 and (_chained(scene_of(j)) or _chained(scene_of(smp.index))):
                continue
            out[smp.index] = j
            break
        seen.append((smp.index, h))
    return out


# --------------------------------------------------------------------------- #
# The model: one call for a few scenes, a strict JSON answer
# --------------------------------------------------------------------------- #

_SYSTEM = (
    "You are the last check on a finished documentary video before it is published. For each SCENE you get "
    "the narration line spoken over it and one or two frames taken from the finished video at that moment. "
    "Judge only what is visible in the frames.\n"
    "For every scene answer:\n"
    "- match (0 to 1): how well the picture fits what the narration line says. 1 = exactly the thing, place, "
    "person or event the line names; 0.7 = clearly related, good B-roll for the line; 0.4 = only loosely "
    "related; 0.1 = nothing to do with it. A line that names a place, person or event, shown as somewhere, "
    "someone or something else: at most 0.3.\n"
    "- issues: none, or any of\n"
    '  "mismatch": the picture does not fit the line (match under 0.5).\n'
    '  "text-over-face": one of OUR GRAPHICS or the captions covers a person\'s face.\n'
    '  "blur": the picture is out of focus, heavily pixelated or badly upscaled.\n'
    '  "watermark": a stock agency\'s or another creator\'s watermark is printed on the picture - Getty Images, '
    "Alamy, Shutterstock, iStock, Adobe Stock, Dreamstime, Depositphotos, 123RF, Pond5, Storyblocks, a name "
    'tiled or written diagonally across it, "PREVIEW", "SAMPLE".\n'
    '  "logo": another channel\'s or TV station\'s logo, banner or burned-in subtitles.\n'
    '  "repeat": the same shot as another scene in this batch (say which scene in the note).\n'
    '  "ai-looking": an AI-generated or painted image posing as real footage.\n'
    '  "talking-head": a presenter, streamer or interviewee talking to the camera.\n'
    '  "other": anything else a viewer would call a mistake - an empty or black frame, a browser or editing '
    "program on screen, an error message, a person's head cut off by the frame.\n"
    '- face: only with "text-over-face" - where the covered face is: "left", "center" or "right".\n'
    '- covering: only with "text-over-face" - what covers it: "captions", or the name of our graphic exactly as '
    "listed for the scene.\n"
    "- note: one short plain sentence saying what is wrong; empty when nothing is.\n"
    "OUR GRAPHICS are the channel's own titles, numbers, labels, captions and corner logo, named with each "
    "scene. They are meant to be there: never report them as watermark, logo or mismatch, and judge the "
    "picture behind them.\n"
    "Be strict about watermarks and about pictures that do not fit, but do not invent problems: most scenes "
    "have none.\n"
    "Answer with ONLY this JSON, one row per scene, in order, no prose:\n"
    '{"scenes":[{"scene":1,"match":0.0,"issues":[],"face":"","covering":"","note":""}]}'
)
_NEWS_RULE = (" A TV news report's own station logo, headline banner or ticker on footage of the event is "
              "accepted in this video: do not report it as logo or watermark.")


def story_line(doc: dict) -> str:
    """One line on what the whole video is about (doc.meta.story), so a scene is judged in its story."""
    b = (doc.get("meta") or {}).get("story") if isinstance(doc.get("meta"), dict) else None
    if not isinstance(b, dict):
        return ""
    parts = [str(b.get("summary") or b.get("event") or ""),
             f"places: {', '.join(str(p) for p in (b.get('places') or [])[:4])}" if b.get("places") else "",
             f"year: {b.get('year')}" if b.get("year") else ""]
    return " | ".join(p for p in parts if p)[:400]


def build_messages(doc: dict, group: List[Sample], pics: Dict[int, str]) -> list:
    """The call for one group: the fixed instructions, then each scene's line, our graphics on it and its frame(s)."""
    captions = doc.get("captions") if isinstance(doc.get("captions"), dict) else {}
    mark = ((doc.get("brand") or {}).get("watermark") or {}) if isinstance(doc.get("brand"), dict) else {}
    story = story_line(doc)
    head = (f"STORY: {story}\n" if story else "") + f"{len(group)} scenes follow, in the order they play."
    if captions.get("enabled"):
        head += f" Our captions run along the {'middle' if captions.get('position') == 'center' else 'bottom'}."
    if mark.get("url"):
        head += f" Our own logo sits in the {mark.get('position') or 'top-right'} corner."
    content: List[dict] = [{"type": "text", "text": head}]
    for k, smp in enumerate(group, 1):
        text = f"SCENE {k}\nNARRATION: {smp.text}\n"
        if smp.intent:
            text += f"MEANT TO SHOW: {smp.intent}\n"
        text += f"OUR GRAPHICS ON SCREEN: {'; '.join(smp.names) if smp.names else 'none'}"
        content.append({"type": "text", "text": text})
        for f in smp.file_frames:
            path = pics.get(f)
            if not path:
                continue
            with open(path, "rb") as fh:
                data = base64.b64encode(fh.read()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
    system = _SYSTEM + (_NEWS_RULE if getattr(config, "NEWS_FOOTAGE", False) else "")
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def _first_json(text: str) -> str:
    """The first complete {...} or [...] in a text (a model may wrap its JSON in a sentence)."""
    start = next((k for k, ch in enumerate(text) if ch in "{["), -1)
    if start < 0:
        return ""
    depth, quote, escaped = 0, False, False
    for k in range(start, len(text)):
        ch = text[k]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return text[start:k + 1]
    return ""


def _issue(raw) -> str:
    name = " ".join(str(raw or "").strip().lower().replace("_", "-").split())
    name = _ALIASES.get(name, _ALIASES.get(name.replace("-", " "), name)).replace(" ", "-")
    return name if name in ISSUES else ("other" if name else "")


def parse_verdicts(text: str, n: int) -> Optional[Dict[int, dict]]:
    """
    {position in the group (0-based): {"match", "issues", "note", "face",
    "covering"}} from the model's answer; None when it is not the JSON asked
    for (the next model is then asked, src/vision._ask). A row without a
    usable match is dropped - a scene nobody scored is "not checked", never
    "fine".
    """
    raw = re.sub(r"^\s*```(?:json)?|```\s*$", "", (text or "").strip()).strip()
    data = None
    for cand in (raw, _first_json(raw)):
        if not cand:
            continue
        try:
            data = json.loads(cand)
            break
        except ValueError:
            continue
    rows = data.get("scenes") if isinstance(data, dict) else data
    if isinstance(data, dict) and rows is None and "match" in data:
        rows = [data]
    if not isinstance(rows, list):
        return None
    out: Dict[int, dict] = {}
    rows = [row for row in rows if isinstance(row, dict)]
    nums = [_f(row.get("scene")) for row in rows]
    # Scenes are numbered from 1, as asked. A model that counts from 0 (its numbers all
    # 0..n-1, a 0 among them) is read that way: never a verdict moved onto the scene before.
    known = [x for x in nums if x is not None]
    first = 0 if known and min(known) == 0 and max(known) <= n - 1 else 1
    for pos, (row, num) in enumerate(zip(rows, nums)):
        if num is not None:
            k = int(num) - first
        elif len(rows) == n:
            k = pos                         # unnumbered: by its place, only when every scene has a row
        else:
            continue                        # a row missing before it would put it on the wrong scene
        match = _f(row.get("match"))
        if match is None or not 0 <= k < n or k in out:
            continue
        match = max(0.0, min(1.0, match))
        listed = row.get("issues")
        listed = [listed] if isinstance(listed, str) else listed if isinstance(listed, list) else []
        issues: List[str] = []
        for x in listed:
            name = _issue(x)
            if name and name not in issues:
                issues.append(name)
        if match < config.AI_REVIEW_MIN_MATCH and "mismatch" not in issues:
            issues.insert(0, "mismatch")
        face = str(row.get("face") or "").strip().lower()
        covering = " ".join(str(row.get("covering") or "").split())[:80]
        out[k] = {"match": round(match, 2), "issues": issues, "note": " ".join(str(row.get("note") or "").split())[:160],
                  "face": face if face in ("left", "center", "right") else "",
                  "covering": "captions" if "caption" in covering.lower() else covering}
    return out or None


def _ask(messages: list, max_tokens: int, accept=None) -> Tuple[Optional[str], str]:
    """The vision model (src/vision._ask: OpenAI-compatible, hedged, the fallback models behind it)."""
    from . import vision
    token = vision._KIND.set("review")                  # its price on its own line of the ledger
    try:
        return vision._ask(messages, max_tokens, accept=accept)
    finally:
        vision._KIND.reset(token)


def _vision_on() -> bool:
    from . import vision
    return vision.enabled()


def ask_group(doc: dict, group: List[Sample], pics: Dict[int, str]) -> Tuple[Dict[int, dict], str]:
    """({scene index: verdict}, model) for one group; ({}, "") when no model gave a usable answer.
    Runs in the review's call pool: it reads the samples and changes nothing."""
    seen = [smp for smp in group if any(pics.get(f) for f in smp.file_frames)]
    if not seen:
        return {}, ""
    messages = build_messages(doc, seen, pics)
    n = len(seen)
    text, model = _ask(messages, 160 + 110 * n, accept=lambda t: parse_verdicts(t, n) is not None)
    got = parse_verdicts(text, n) if text else None
    if not got:
        return {}, ""
    return {seen[k].index: v for k, v in got.items()}, model


# --------------------------------------------------------------------------- #
# The fixes
# --------------------------------------------------------------------------- #

def clip_seconds(src: str, timeout: float = 20.0) -> float:
    """A clip's measured length (a file on this disk or a published link); 0 when it cannot be read now."""
    chk = quality.probe_video(quality._probe_source(src), timeout=max(1.0, float(timeout)))
    return float(chk.seconds) if chk.ok and not chk.unverified else 0.0


def still_ok(src: str, timeout: Optional[float] = None) -> bool:
    """A picture that can be loaded now (a file on this disk, or a link that answers with an image)."""
    path = quality.local_path(src)
    if path:
        return os.path.isfile(path) and os.path.getsize(path) >= quality.MIN_IMAGE_BYTES
    chk = quality.reach(src, "image", timeout=timeout, tries=2 if timeout else 3)
    return bool(chk.ok and not chk.unverified)


def _alt_file(alt: dict) -> str:
    """What the renderer can load of a runner-up: its published link, else its file on this disk (a build)."""
    m = alt.get("media") if isinstance(alt.get("media"), dict) else {}
    url = str(m.get("url") or "")
    if url.startswith(("http://", "https://")) or (url and os.path.isfile(url)):
        return url
    path = str(alt.get("localPath") or "")
    return path if path and os.path.isfile(path) else ""


def pick_alternative(doc: dict, i: int, used: gapfill.Used, issues: List[str],
                     deadline: Optional[float] = None) -> Optional[dict]:
    """
    The scene's best other choice that may take its place, or None. The
    choices are its pick-a-shot runner-ups (semanticMetadata.alternatives):
    clips the judge already saw for THIS line. One qualifies when it scored at
    or above the judge's floor (VISION_MIN_SCORE), can be loaded now, is not
    the shot the scene already shows nor one any other scene shows
    (gapfill.Used: file, asset, moment), covers the scene without freezing -
    and, when the fault is the source's own (a watermark, a soft or AI-made
    picture), comes from a different source. Past `deadline` nothing more is
    measured.
    """
    scenes = doc.get("scenes") or []
    s = scenes[i]
    fps = max(1, int(doc.get("fps") or 30))
    sem = s.get("semanticMetadata") or {}
    alts = [a for a in (sem.get("alternatives") or []) if isinstance(a, dict)]
    mine = gapfill.Shot.of_scene(s, fps)
    need = quality.scene_need(scenes, i, fps)
    at = int(s.get("startFrame") or 0) / fps
    for alt in sorted(alts, key=lambda a: -((_f(a.get("score")) or 0.0) + 0.1 * (_f(a.get("quality")) or 0.0))):
        left = (deadline - time.time()) if deadline is not None else 20.0
        if left <= 0:
            break
        score, qual = _f(alt.get("score")), _f(alt.get("quality"))
        if score is None or score < config.VISION_MIN_SCORE:
            continue
        if qual is not None and qual < config.VISION_MIN_QUALITY:
            continue
        src = _alt_file(alt)
        if not src:
            continue
        kind = "image" if os.path.splitext(src.split("?")[0])[1].lower() in _STILL_EXT else "video"
        ident = str(alt.get("assetId") or "")
        page = str(alt.get("url") or "")
        video = gapfill._video_of(ident, page) if kind == "video" else ""
        moment = alt.get("moment") if isinstance(alt.get("moment"), dict) else {}
        shot = gapfill.Shot(ident="" if video else ident, files=tuple(gapfill._files_of(src)), video=video,
                            start=gapfill._start_from(moment, page, src) if video else None, at=at)
        if used.why_not(i, shot):
            continue
        if mine is not None:
            same_moment = bool(shot.video and shot.video == mine.video and shot.start is not None
                               and mine.start is not None and abs(shot.start - mine.start) < 1.0)
            if (shot.ident and shot.ident == mine.ident) or set(shot.files) & set(mine.files) or same_moment:
                continue                    # the shot the scene already shows
            if SOURCE_ISSUES & set(issues) and shot.video and shot.video == mine.video:
                continue                    # another moment of the source at fault
        seconds = 0.0
        if kind == "video":
            seconds = clip_seconds(src, min(20.0, left))
            if seconds <= 0 or seconds / quality.MIN_RATE < need - quality.TOLERANCE_FRAMES / fps:
                continue
        elif not still_ok(src, min(float(config.QUALITY_HTTP_TIMEOUT), left)):
            continue
        return {"alt": alt, "src": src, "kind": kind, "seconds": seconds, "shot": shot,
                "rank": alts.index(alt) + 1, "score": score}
    return None


def swap_in(scene: dict, pick: dict, why: str) -> None:
    """Put a chosen runner-up on its scene: the media the renderer draws and what the editor shows of it."""
    alt, kind = pick["alt"], pick["kind"]
    published = alt.get("media") if isinstance(alt.get("media"), dict) else {}
    media: Dict[str, Any] = {k: published[k] for k in ("thumbnail", "previewUrl", "storage", "thumbStorage",
                                                       "previewStorage") if published.get(k)}
    media.update(type=kind, url=pick["src"],
                 source=str(alt.get("source") or (scene.get("media") or {}).get("source") or "youtube"))
    if alt.get("title"):
        media["attribution"] = str(alt["title"])
    if kind == "video":
        media["clipSeconds"] = round(float(pick["seconds"]), 2)
    if _f(alt.get("score")) is not None:
        media["relevanceScore"] = round(float(alt["score"]), 3)
    if _f(alt.get("quality")) is not None:
        media["qualityScore"] = round(float(alt["quality"]), 3)
    if alt.get("description"):
        media["contentDescription"] = str(alt["description"])
    scene["media"] = media
    sem = scene.setdefault("semanticMetadata", {})
    page = str(alt.get("url") or "")
    sem.update({"assetId": str(alt.get("assetId") or ""), "provider": str(alt.get("source") or ""),
                "sourceUrl": page if page.startswith("http") else "",
                "contentDescription": str(alt.get("description") or ""),
                "relevanceScore": _f(alt.get("score")), "qualityScore": _f(alt.get("quality")),
                "specificity": str(alt.get("specificity") or ""),
                "moment": dict(alt.get("moment") or {}) if isinstance(alt.get("moment"), dict) else {},
                "alternatives": [a for a in (sem.get("alternatives") or []) if a is not alt]})
    if kind == "image":
        scene["motion"] = scene.get("motion") or "none"
    scene["reviewRequired"] = True
    scene["reviewReason"] = f"The AI review swapped this scene's picture for its other choice ({why}) - check it fits"


def _least_seconds(template: dict) -> float:
    """The least time a look needs on screen (its entrance, hit, settle and exit: treatments.animation_seconds)."""
    try:
        from . import treatments
        return float(treatments.animation_seconds(template) or 0.0)
    except Exception:  # noqa: BLE001 - the 2 s floor alone
        return 0.0


def move_graphic(ov: dict, face: str, fps: int) -> str:
    """
    Take one of our graphics off a face; returns what was done ("" = nothing
    that would help: it is left for the owner). Only the renderer's own
    placement fields are touched:
      a figure in a corner (compact, MotionWrap's `position`) on the face's
      side goes to the other corner - one on the other side, or a face in
      the middle, is not what covers it;
      a text look (an `align` prop: LibBoldText and LibPack* draw the block
      low on the left, right or centre; no align = the left, their default)
      on the face's side or in the middle goes to the other side - one
      already on the other side is not what covers the face and stays;
      anything else (a face in the middle, a graphic with no side to go to)
      is shortened to the time a title needs to be read - the look's own
      least time and never under SHORT_GRAPHIC_SECONDS (the graphics timing
      rule: in on its word, out ~2 s later).
    """
    t = templates.get(ov.get("template") or "") or {}
    props = t.get("props") or {}
    away = {"left": "right", "right": "left"}.get(face, "")
    pos = str(ov.get("position") or "")
    if ov.get("compact") and pos in CORNERS:
        if away and pos.endswith(face):
            ov["position"] = pos[: -len(face)] + away
            return f"moved to the {away} corner"
        return ""
    if "align" in props and not ov.get("fullFrame") and away:
        side = str(ov.get("align") or "").lower()
        side = side if side in ("left", "right", "center") else "left"
        if side == away:
            return ""
        ov["align"] = away
        return f"moved to the {away}"
    least = max(_f((props.get("duration") or {}).get("min")) or 0.0, _least_seconds(t), SHORT_GRAPHIC_SECONDS)
    frames = int(math.ceil(least * fps - 1e-6))
    if int(ov.get("durationInFrames") or 0) > frames + fps // 2:
        ov["durationInFrames"] = frames
        return f"shortened to {round(least, 1):g} s"
    return ""


def _named(ov: dict, covering: str) -> bool:
    """The model named this graphic as the one over the face (its text, else its kind)."""
    def words(s) -> List[str]:
        return re.findall(r"[a-z0-9%$]+", str(s or "").lower())
    said = set(words(covering))
    text = words(ov.get("text") or ov.get("label"))
    if text:
        return all(w in said for w in text[:3])
    return bool(said & set(words(ov.get("type"))))


# --------------------------------------------------------------------------- #
# One render's review
# --------------------------------------------------------------------------- #

class Review:
    """One render's AI review. handler.do_render drives it; see the module notes."""

    def __init__(self, doc: dict, work: str, report: Callable = None):
        self.doc = doc if isinstance(doc, dict) else {}
        self.work = work or config.WORK_DIR
        self.report_fn = report
        self.on = bool(getattr(config, "AI_REVIEW", False))
        try:
            self.fps = max(1, int(self.doc.get("fps") or 30))
            self.budget = max(1.0, float(getattr(config, "AI_REVIEW_SECONDS", 300.0)))
        except (TypeError, ValueError):
            self.fps, self.budget = 30, 300.0
        self.status = "off"
        self.why = ""
        self.planned: Optional[Tuple[List[Sample], Dict[int, str]]] = None
        self.intro = 0
        self.samples: Dict[int, Sample] = {}
        self.verdicts: Dict[int, dict] = {}         # by the scene's place as drawn (Sample.index)
        self.not_reviewed: Dict[int, str] = {}      # scenes with no clip to judge (ours, a flash, covered, repaired)
        self.unchecked: Dict[int, str] = {}         # scenes the review should have seen and did not
        self.fixed: List[dict] = []
        self.left: List[dict] = []
        self.audio: Dict[str, Any] = {}
        self.notes: List[str] = []
        self.calls = 0
        self.cost = 0.0
        self.cost_measured = False
        self.model = ""
        self.seconds: Dict[str, float] = {}
        self.redraw = False
        # The job's own clock (after_render): the gate drawing the video once more anyway, when the
        # job is stopped from outside (epoch seconds, 0 = not known) and how long the first render took.
        self.again = False
        self.job_deadline = 0.0
        self.draw_seconds = 0.0
        self._undo: List[Callable[[], None]] = []
        self._report: Optional[dict] = None
        self._rows = 0
        self._started = 0.0
        self._deadline = 0.0

    # ---- talking ------------------------------------------------------------
    def _say(self, step: str, pct: int = None) -> None:
        if callable(self.report_fn):
            try:
                self.report_fn(step, pct)
            except Exception:  # noqa: BLE001 - progress never costs the video
                pass

    def _event(self, event: str, message: str, scene: Optional[int] = None, level: str = "info",
               data: Optional[dict] = None, always: bool = False) -> None:
        if not always:
            self._rows += 1
            if self._rows > EVENT_ROWS:
                return
        try:
            events.emit("review", event, level=level, scene=scene, message=message, data=data)
        except Exception:  # noqa: BLE001
            pass

    def _broke(self, what: str, err: BaseException) -> None:
        """A step that broke is logged and skipped: the review must never be what fails a video."""
        traceback.print_exc()
        self.notes.append(f"{what} broke ({type(err).__name__}: {str(err)[:120]}) and was skipped")
        self._event("check_failed", f"{what}: {type(err).__name__}: {str(err)[:200]}", level="error", always=True)

    def _left(self) -> float:
        """Seconds of the review's budget still to spend."""
        return self._deadline - time.time()

    def _row(self, i: Optional[int], issue: str, note: str, smp: Optional[Sample] = None,
             at: Optional[float] = None, **more) -> dict:
        """One line of the report: the scene (as drawn: its id and time stay what the first render showed)."""
        scenes = self.doc.get("scenes") or []
        s = scenes[i] if i is not None and 0 <= i < len(scenes) and isinstance(scenes[i], dict) else {}
        sid = smp.scene_id if smp is not None else str(s.get("id") or "")
        when = at if at is not None else smp.at if smp is not None else int(s.get("startFrame") or 0) / self.fps
        row = {"scene": sid, "issue": issue, "note": note, "at": quality._clock(when)}
        if i is not None:
            row["index"] = i
        row.update({k: v for k, v in more.items() if v not in (None, "")})
        return row

    def _leave(self, row: dict) -> None:
        self.left.append(row)
        self._event("left", f"{row['at']} {row['issue']}: {row['note']}", scene=row.get("index"), level="warning",
                    data={"issue": row["issue"], "why": row.get("why")})

    def _did(self, row: dict) -> None:
        self.fixed.append(row)
        self._event("fixed", f"{row['at']} {row['issue']}: {row['note']} -> {row['how']}", scene=row.get("index"),
                    data={"issue": row["issue"], "how": row["how"]})

    # ---- before the gate's scan ---------------------------------------------
    def plan(self) -> None:
        """
        What the first render shows, noted BEFORE the quality gate repairs
        anything (handler.do_render calls this right before Gate.after_render).
        The frames are taken from that first file, and a repair after the scan
        merges an empty scene into its neighbours (they grow over its time,
        gapfill._hold) and drops looks: planned afterwards, a neighbour's
        midpoint could land on the black stretch the gate just repaired, and a
        look's place in the list would name another look. Never raises; a plan
        that broke is made again after the scan.
        """
        if not self.on or self.planned is not None:
            return
        try:
            from . import brandkit
            self.intro = int(brandkit.layout(self.doc)[0] or 0)
            self.planned = plan_samples(self.doc)
        except Exception as e:  # noqa: BLE001 - planned again after the scan
            self._broke("the review's plan", e)
            self.planned = None

    # ---- after the render ---------------------------------------------------
    def after_render(self, path: str, gate=None, may_fix: bool = True, again: bool = False,
                     deadline: float = 0.0, draw_seconds: float = 0.0) -> bool:
        """
        Review the finished file. True when something was fixed and the video
        should be drawn once more (the gate's one second render is then taken:
        Gate.join_second_render). `may_fix` False: that render is already
        spent, so the review only lists. `again`: the gate draws the video
        once more anyway (its own repairs), so the fixes cost no render of
        their own. `deadline`: when the job is stopped from outside (epoch
        seconds; 0 = not known) and `draw_seconds` how long the first render
        took - a second render that could not finish before it is never asked
        for (_time_for_render). Never raises; takes about AI_REVIEW_SECONDS at
        most.
        """
        if not self.on:
            return False
        self._started = time.time()
        self._deadline = self._started + self.budget
        self.again = bool(again)
        self.job_deadline = max(0.0, _f(deadline) or 0.0)
        self.draw_seconds = max(0.0, _f(draw_seconds) or 0.0)
        try:
            return self._after_render(path, gate, may_fix)
        except Exception as e:  # noqa: BLE001 - the review must never be what fails a video
            self._broke("the AI review", e)
            try:
                if self.fixed:
                    self._not_applied("the review broke, so the first render is kept as it is")
                else:
                    self._take_back()
            except Exception:  # noqa: BLE001
                pass
            self.redraw = False
            if not self.verdicts:
                self.status, self.why = "skipped", "the review broke"
            return False
        finally:
            self.seconds["total"] = round(time.time() - self._started, 1)

    def _after_render(self, path: str, gate, may_fix: bool) -> bool:
        self._say("Reviewing the finished video", 90)
        info = probe(path)
        if not info:
            self.status, self.why = "skipped", "the finished file could not be read"
            return False
        # The sound: its own ffmpeg pass (no model), measured while the pictures are judged.
        sound = None
        if getattr(config, "AI_REVIEW_AUDIO", True) and info.get("audio"):
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="review-sound")
            sound = pool.submit(measure_audio, path, self.budget * SOUND_SHARE)
            pool.shutdown(wait=False)
        replaced = {str(r.get("scene")) for r in (getattr(gate, "repairs", None) or [])
                    if isinstance(r, dict) and r.get("stage") == "after the render"}
        try:
            self._pictures(path, info, replaced)
        except Exception as e:  # noqa: BLE001 - the sound is still checked
            self._broke("the picture review", e)
            self.status, self.why = "skipped", "the picture review broke"
        if sound is not None:
            try:
                self._audio(sound)
            except Exception as e:  # noqa: BLE001
                self._broke("the sound check", e)
        t0 = time.time()
        again = self._fix(gate, may_fix)
        self.seconds["fixes"] = round(time.time() - t0, 1)
        return again

    def _pictures(self, path: str, info: dict, replaced: set) -> None:
        if self.planned is None:
            # Not planned before the gate's scan (a caller that does not plan): the document as it is now.
            from . import brandkit
            self.intro = int(brandkit.layout(self.doc)[0] or 0)
            self.planned = plan_samples(self.doc)
        planned, skipped = self.planned
        self.not_reviewed = dict(skipped)
        live = {id(s) for s in self.doc.get("scenes") or [] if isinstance(s, dict)}
        rate = float(info.get("fps") or self.fps)
        samples = []
        for smp in planned:
            if smp.scene_id in replaced or (smp.scene is not None and id(smp.scene) not in live):
                # The gate replaced its picture after the scan (or merged it into its neighbours):
                # the frame in the file is the picture that is gone.
                self.not_reviewed[smp.index] = "the quality check has just replaced it"
                continue
            smp.file_frames = _file_frames(smp.frames, self.intro, self.fps, rate)
            samples.append(smp)
        self.samples = {s.index: s for s in samples}
        if not samples:
            self.status, self.why = "skipped", "no scene shows a clip to review"
            return
        if not _vision_on():
            self.status, self.why = "skipped", "no vision model is set up on this worker"
            self.unchecked = {s.index: self.why for s in samples}
            return
        size = max(4, min(6, int(config.AI_REVIEW_GROUP)))
        cap = max(0, int(config.AI_REVIEW_MAX_CALLS))
        groups = groups_of(samples, size)
        if len(groups) > cap:
            groups = groups_of(samples, 6)          # fuller calls before any scene goes unseen
        order = [groups[k] for k in call_order(len(groups))]
        chosen, late = order[:cap], order[cap:]
        for g in late:
            for smp in g:
                self.unchecked[smp.index] = "the review's call budget ran out"
        if not chosen:
            self.status, self.why = "skipped", "the review's call budget is zero"
            return
        t0 = time.time()
        pics = grab_frames(path, [f for g in chosen for smp in g for f in smp.file_frames],
                           os.path.join(self.work, "review"), fps=rate,
                           timeout=min(float(config.QUALITY_SCAN_TIMEOUT),
                                       max(5.0, min(self._left(), self.budget * FRAMES_SHARE))))
        self.seconds["frames"] = round(time.time() - t0, 1)
        if not pics:
            self.status, self.why = "skipped", "no frames could be taken from the finished video"
            self.unchecked.update({smp.index: self.why for g in chosen for smp in g})
            return
        asked = []
        for g in chosen:
            have = [smp for smp in g if any(pics.get(f) for f in smp.file_frames)]
            for smp in g:
                if smp not in have:
                    self.unchecked[smp.index] = "its frame could not be taken from the finished video"
            if have:
                asked.append(have)
        t0 = time.time()
        spent_before = float(costs.LEDGER.units.get("vision.usd", 0.0) or 0.0)
        pool = ThreadPoolExecutor(max_workers=max(1, min(int(config.AI_REVIEW_PARALLEL), len(asked) or 1)),
                                  thread_name_prefix="review")
        futures = {pool.submit(ask_group, self.doc, g, pics): g for g in asked}
        done, _late = _wait(futures, timeout=max(1.0, self._left() - self.budget * FIX_RESERVE))
        # A call still out is abandoned: its answer is never read, and the calls not yet sent are not sent.
        pool.shutdown(wait=False, cancel_futures=True)
        self.calls = sum(1 for f in futures if not f.cancelled())
        answered = 0
        for fut, g in futures.items():
            got, model = {}, ""
            if fut in done:
                try:
                    got, model = fut.result()
                except Exception as e:  # noqa: BLE001 - that group is not checked
                    print(f"[review] a call failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            if model:
                answered += 1
            self.model = self.model or model
            self._keep_repeats_once(g, got)
            for smp in g:
                if smp.index in got:
                    self.verdicts[smp.index] = got[smp.index]
                else:
                    self.unchecked[smp.index] = ("the model gave no usable answer" if fut in done
                                                 else "the review's time ran out")
        if answered:
            costs.record("vision.review", answered)       # here, never from a call that came back late
        if self.calls > len(done):
            self.notes.append(f"{quality._n(self.calls - len(done), 'model call')} still out when the review's "
                              f"time ran out - not waited for")
        self.seconds["vision"] = round(time.time() - t0, 1)
        spent = float(costs.LEDGER.units.get("vision.usd", 0.0) or 0.0) - spent_before
        prices = costs.LEDGER.prices
        self.cost_measured = spent > 0
        self.cost = spent if spent > 0 else answered * prices.get("vision.review", 0.0) * prices.get("kie.credit", 0.0)
        # The same picture twice, anywhere in the video: found on the frames themselves.
        try:
            for i, j in find_look_alikes(self.doc, [s for s in samples if s.index in self.verdicts], pics).items():
                v = self.verdicts[i]
                if "repeat" not in v["issues"]:
                    v["issues"].append("repeat")
                    v["note"] = v["note"] or f"looks the same as the shot at {quality._clock(self.samples[j].at)}"
        except Exception as e:  # noqa: BLE001 - the model's own verdicts stand
            self._broke("the look-alike check", e)
        self.status = "done" if not self.unchecked else "partial" if self.verdicts else "skipped"
        if self.status == "skipped":
            self.why = next(iter(self.unchecked.values()), "no scene could be checked")

    @staticmethod
    def _keep_repeats_once(group: List[Sample], got: Dict[int, dict]) -> None:
        """Two scenes the model calls repeats of each other: the first one to show the shot keeps it."""
        tagged = [smp.index for smp in group if "repeat" in (got.get(smp.index) or {}).get("issues", [])]
        if len(tagged) >= 2:
            got[tagged[0]]["issues"].remove("repeat")

    def _audio(self, sound) -> None:
        try:
            measured = sound.result(timeout=max(0.5, self._left()))
        except _FutureTimeout:
            measured = {"ok": False, "why": "the review's time ran out before the sound was measured"}
        self.seconds["audio"] = measured.get("seconds", 0.0)
        self.audio = {"checked": bool(measured.get("ok")), "lufs": measured.get("lufs"),
                      "truePeak": measured.get("truePeak"), "flags": 0}
        if not measured.get("ok"):
            self.audio["why"] = measured.get("why") or ""
            self.notes.append(f"the sound was not checked: {self.audio['why']}")
            return
        scenes = self.doc.get("scenes") or []
        starts = [int(s.get("startFrame") or 0) / self.fps for s in scenes]
        for f in audio_findings(self.doc, measured):
            i = max(0, bisect.bisect_right(starts, f["at"]) - 1) if starts else None
            self._leave(self._row(i, f["issue"], f["note"], at=f["at"], sound=True))
            self.audio["flags"] += 1

    # ---- the fixes ----------------------------------------------------------
    def _why_no_fix(self, gate, may_fix: bool) -> str:
        if not getattr(config, "AI_REVIEW_FIX", True):
            return "fixing is switched off (AI_REVIEW_FIX)"
        if gate is None or not may_fix:
            return "the one second render was already used"
        if not config.QUALITY_RERENDER:
            return "second renders are switched off (QUALITY_RERENDER)"
        return self._time_for_render()

    def _time_for_render(self) -> str:
        """
        "" when the job still has the time to draw the video once more, else
        why not. A job past its limit (config.JOB_MAX_SECONDS: the endpoint's
        execution timeout, a pod's watchdog) is killed with nothing saved, so
        a fix that needs a render of its own is only worth one that finishes:
        about the first render's time (draw_seconds; this machine's estimate
        for the frames when not measured) x AI_REVIEW_RENDER_FACTOR, plus
        AI_REVIEW_RENDER_RESERVE_SECONDS for the scan, the upload and saving
        after it. Not asked when the gate draws the video again anyway, or the
        job's limit is not known.
        """
        if self.again or self.job_deadline <= 0:
            return ""
        from . import render as renderer
        draw = self.draw_seconds
        if draw <= 0:
            try:
                from . import brandkit
                draw = float(renderer.estimate_seconds(brandkit.total_frames(self.doc)))
            except Exception:  # noqa: BLE001 - only the reserve is counted
                draw = 0.0
        need = draw * max(1.0, float(getattr(config, "AI_REVIEW_RENDER_FACTOR", 1.25))) \
            + max(0.0, float(getattr(config, "AI_REVIEW_RENDER_RESERVE_SECONDS", 900.0)))
        left = self.job_deadline - time.time()
        if left >= need:
            return ""
        have = renderer._minutes(left) if left >= 60 else "under a minute"
        return (f"not enough of the job's time is left for a second render "
                f"(about {renderer._minutes(need)} needed, {have} left)")

    def _snapshot(self, target: dict) -> None:
        before = copy.deepcopy(target)

        def back() -> None:
            target.clear()
            target.update(before)
        self._undo.append(back)

    def _take_back(self) -> None:
        """Every change this review made to the document, undone (the video shows the first render)."""
        while self._undo:
            try:
                self._undo.pop()()
            except Exception:  # noqa: BLE001
                pass

    def _fix(self, gate, may_fix: bool) -> bool:
        scenes = self.doc.get("scenes") or []
        # The scenes as they are now (the gate's repairs move and merge them; the objects stay the same).
        where = {id(s): k for k, s in enumerate(scenes) if isinstance(s, dict)}
        flagged: List[Tuple[int, Optional[Sample], dict]] = []
        for d, v in sorted(self.verdicts.items()):
            if not v["issues"]:
                continue
            smp = self.samples.get(d)
            k = where.get(id(smp.scene)) if smp is not None and smp.scene is not None else None
            if k is None:
                for issue in v["issues"]:
                    self._leave(self._row(None, issue, v["note"] or DEFAULT_NOTE[issue], smp=smp, match=v["match"],
                                          why="the scene changed after the first render"))
                continue
            flagged.append((k, smp, v))
        if not flagged:
            return False
        blocked = self._why_no_fix(gate, may_fix)
        if blocked:
            self.notes.append(f"nothing was changed: {blocked}")
            self._event("not_fixed", blocked, level="warning", always=True)
        floor = float(config.AI_REVIEW_MIN_MATCH)

        def wanted(v: dict) -> List[str]:
            """The scene's issues a new picture would answer (a mismatch only when the score says so too)."""
            return [x for x in SWAP_ISSUES + ("repeat",) if x in v["issues"] and (x != "mismatch" or v["match"] < floor)]
        wants = [k for k, _smp, v in flagged if wanted(v)]
        brake = ""
        if len(wants) > max(BRAKE_MIN, float(config.AI_REVIEW_MAX_FIX_SHARE) * max(1, len(self.verdicts))):
            brake = (f"the review wanted to replace {len(wants)} of {len(self.verdicts)} scenes - too many to "
                     f"trust, so nothing was swapped")
            self.notes.append(brake)
        used = gapfill.Used()
        for k, s in enumerate(scenes):
            shot = gapfill.Shot.of_scene(s, self.fps) if isinstance(s, dict) else None
            if shot is not None:
                used.add(k, shot)
        ladder: Dict[int, Tuple[str, str]] = {}
        sent: Dict[int, Tuple[Optional[Sample], dict]] = {}
        for k, smp, v in flagged:
            s = scenes[k]
            note = v["note"]
            fixable = wanted(v)
            if fixable and not blocked and not brake:
                if self._left() <= 0:
                    self._leave_scene(k, smp, v, fixable, "", "the review's time ran out before this scene was fixed")
                    continue
                pick = pick_alternative(self.doc, k, used, fixable, deadline=self._deadline)
                if pick is not None:
                    why = note or DEFAULT_NOTE[fixable[0]]
                    self._snapshot(s)
                    used.shots.pop(k, None)
                    swap_in(s, pick, why)
                    used.add(k, pick["shot"])
                    # choice/asset: which of the scene's choices it is, for the saved timeline (carry_swaps).
                    self._did(self._row(k, fixable[0], why, smp=smp, how=f"swapped for its choice {pick['rank']} "
                                        f"(scored {pick['score']:.2f} for this line)", also=fixable[1:] or None,
                                        choice=pick["rank"], asset=str(pick["alt"].get("assetId") or "")))
                    continue                # a new picture: what was said of the old one no longer holds
                if "repeat" in fixable and len(ladder) < LADDER_MAX:
                    ladder[k] = ("repeat", note or DEFAULT_NOTE["repeat"])
                    sent[k] = (smp, v)
                    continue                # the ladder below; its other issues wait for it
                if self._left() <= 0:
                    self._leave_scene(k, smp, v, fixable, "", "the review's time ran out before this scene was fixed")
                    continue
            self._leave_scene(k, smp, v, fixable, blocked,
                              blocked or brake or ("no other choice was ready for this scene" if fixable else ""))
        if ladder:
            left = self._left()
            got: Dict[int, str] = {}
            if left >= 10.0:
                self._say(f"Finding another shot for {quality._n(len(ladder), 'repeated scene')}", 90)
                for k in ladder:
                    self._snapshot(scenes[k])
                got = gate.another_shot(ladder, seconds=min(float(config.QUALITY_REPAIR_SECONDS), left))
            for k, (issue, why) in ladder.items():
                smp, v = sent[k]
                if k in got:
                    scenes[k]["reviewReason"] = (f"The AI review replaced this scene's picture ({why}) "
                                                 f"with {got[k]} - check it fits")
                    self._did(self._row(k, issue, why, smp=smp, how=f"replaced with {got[k]}"))
                else:
                    self._leave_scene(k, smp, v, wanted(v), blocked,
                                      "no other shot was found for this scene" if left >= 10.0
                                      else "the review's time ran out before another shot was searched for")
        if not self.fixed:
            self._undo.clear()
            return False
        late = self._time_for_render()          # the fixes took time too: asked again before the render
        if late:
            self._not_applied(late)
            return False
        if not gate.join_second_render([r["index"] for r in self.fixed if "index" in r], "the AI review"):
            self._not_applied("the second render could not be prepared, so the first one is kept")
            return False
        self.redraw = True
        return True

    def _leave_scene(self, k: int, smp: Optional[Sample], v: dict, fixable: List[str], blocked: str,
                     why: str) -> None:
        """A scene that keeps its picture: each thing found goes on the list; a title over a face is still moved."""
        for issue in v["issues"]:
            if issue != "text-over-face":
                self._leave(self._row(k, issue, v["note"] or DEFAULT_NOTE[issue], smp=smp, match=v["match"],
                                      why=why if issue in fixable else None))
        if "text-over-face" in v["issues"]:
            self._off_the_face(k, smp, v, blocked)

    def _off_the_face(self, k: int, smp: Optional[Sample], v: dict, blocked: str) -> None:
        """One of our graphics over a face: move it (or shorten it), else leave it for the owner."""
        note = v["note"] or DEFAULT_NOTE["text-over-face"]
        live = {id(ov) for ov in self.doc.get("overlays") or [] if isinstance(ov, dict)}
        ours = [ov for ov in (smp.overlays if smp is not None else []) if id(ov) in live]
        covering = str(v.get("covering") or "")
        if covering == "captions":
            self._leave(self._row(k, "text-over-face", note, smp=smp,
                                  why="the captions cover the face - move them in the editor"))
            return
        named = [ov for ov in ours if covering and _named(ov, covering)]
        ours = named or ours
        if blocked or not ours:
            self._leave(self._row(k, "text-over-face", note, smp=smp,
                                  why=blocked or "the text over the face is not one of our movable graphics"))
            return
        done = []
        for ov in ours[:2]:
            before = copy.deepcopy(ov)
            how = move_graphic(ov, v.get("face") or "", self.fps)
            if how:
                def back(target=ov, old=before) -> None:
                    target.clear()
                    target.update(old)
                self._undo.append(back)
                done.append(f"{_graphic_name(ov)} {how}")
        if done:
            self._did(self._row(k, "text-over-face", note, smp=smp, how="; ".join(done)))
        else:
            self._leave(self._row(k, "text-over-face", note, smp=smp,
                                  why="our graphic is already clear of that side or cannot be moved safely"))

    # ---- after the second render ---------------------------------------------
    def _not_applied(self, why: str) -> None:
        """The video shows the first render after all: the changes come out of the document and are listed."""
        self._take_back()
        for r in self.fixed:
            row = {k: v for k, v in r.items() if k not in ("how", "also", "choice", "asset")}
            row["why"] = why
            self.left.append(row)
        self.fixed = []
        self.redraw = False
        self.notes.append(f"the fixes were not applied: {why}")
        self._event("not_applied", why, level="warning", always=True)

    def after_rerender(self, kept: str) -> None:
        """Which file the gate kept after the second render ("repaired" or "first")."""
        try:
            if self.on and self.redraw and kept == "first":
                self._not_applied("the second render came out worse, so the first one is kept")
        except Exception as e:  # noqa: BLE001
            self._broke("the review after the second render", e)

    def rerender_failed(self, err: BaseException) -> None:
        try:
            if self.on and self.redraw:
                self._not_applied("the second render failed, so the first one is kept")
        except Exception as e:  # noqa: BLE001
            self._broke("the review after the second render", e)

    # ---- the report ---------------------------------------------------------
    def summary(self) -> str:
        """The app's one-liner: "AI review: 131/133 scenes fit the narration, 2 clips swapped, 1 left for you"."""
        checked = len(self.verdicts)
        parts = []
        swaps = sum(1 for r in self.fixed if r["issue"] != "text-over-face")
        moved = sum(1 for r in self.fixed if r["issue"] == "text-over-face")
        if swaps:
            parts.append(quality._n(swaps, "clip") + " swapped")
        if moved:
            parts.append(quality._n(moved, "title") + " moved")
        if self.left:
            parts.append(f"{len(self.left)} left for you")
        if self.unchecked and checked:
            parts.append(f"{len(self.unchecked)} not checked")
        if not checked:
            head = f"AI review: skipped ({self.why or 'nothing could be checked'})"
            return head + (", " + ", ".join(parts) if parts else "")
        fit = checked - sum(1 for v in self.verdicts.values() if "mismatch" in v["issues"])
        return f"AI review: {fit}/{checked} scenes fit the narration, " + (", ".join(parts) if parts else "nothing to fix")

    def finish(self) -> Optional[dict]:
        """The report (doc.meta.review, the job result's "review"); None when the review is off."""
        if not self.on:
            return None
        if self._report is not None:
            return self._report
        try:
            self._report = self._finish()
        except Exception as e:  # noqa: BLE001 - the review must never be what fails a video
            self._broke("the review's report", e)
            self._report = {"summary": "AI review: the report could not be written", "status": "skipped",
                            "checked": len(self.verdicts), "fixed": [], "left": [], "cost": 0.0,
                            "seconds": self.seconds.get("total", 0.0), "notes": self.notes[:10]}
        return self._report

    def _finish(self) -> dict:
        line = self.summary()
        checked = len(self.verdicts)
        out = {"summary": line, "status": self.status if self.status != "off" else "skipped", "why": self.why,
               "scenes": len(self.doc.get("scenes") or []), "checked": checked,
               "fit": checked - sum(1 for v in self.verdicts.values() if "mismatch" in v["issues"]),
               "notChecked": len(self.unchecked), "notReviewed": len(self.not_reviewed),
               "fixed": self.fixed[:100], "left": self.left[:100], "audio": dict(self.audio),
               "calls": self.calls, "model": self.model, "cost": round(self.cost, 4),
               "costMeasured": self.cost_measured, "seconds": self.seconds.get("total", 0.0),
               "budget": self.budget, "timings": dict(self.seconds), "rerendered": self.redraw,
               "notes": self.notes[:10]}
        self._event("summary", line, level="warning" if self.left else "info", always=True,
                    data={"checked": checked, "fixed": len(self.fixed), "left": len(self.left),
                          "notChecked": len(self.unchecked), "calls": self.calls, "cost": out["cost"],
                          "seconds": out["seconds"], "rerendered": self.redraw})
        extra = getattr(self.report_fn, "extra", None)
        if isinstance(extra, dict):
            # Rides on every later progress update (job_progress.review): small, the app's panel reads it.
            extra["review"] = {"summary": line, "status": out["status"], "checked": checked,
                               "fixed": [{k: r.get(k) for k in ("scene", "at", "issue", "how")} for r in self.fixed[:12]],
                               "left": [{k: r.get(k) for k in ("scene", "at", "issue", "note")} for r in self.left[:12]],
                               "cost": out["cost"], "seconds": out["seconds"]}
        print(f"[review] {line}", flush=True)
        return out


def carry_swaps(doc: dict, drawn: dict, reviewed: Optional[dict]) -> Dict[str, dict]:
    """
    The runner-up swaps the finished video kept, made on the saved timeline
    too (a build: `doc` is what the job saves as the project's timeline,
    `drawn` the render copy the review changed), so the editor shows the clip
    the video shows and a later render from the editor keeps it instead of
    bringing the rejected clip back. Only a scene's own choice, found again on
    the saved scene by its place and asset and showing in the render copy;
    the fallback ladder's replacements and moved titles are marked for the
    owner instead (mark_for_review), as the quality gate's repairs are.
    Returns {scene id: the saved scene as it was} for the scenes changed
    (unsaved_back puts one back when its file could not be saved). The
    clip's file may be on this disk: the caller publishes the timeline.
    Never raises.
    """
    out: Dict[str, dict] = {}
    try:
        saved = {s.get("id"): s for s in (doc or {}).get("scenes") or [] if isinstance(s, dict)}
        shown = {s.get("id"): s for s in (drawn or {}).get("scenes") or [] if isinstance(s, dict)}
        for r in (reviewed or {}).get("fixed") or []:
            if not isinstance(r, dict) or not isinstance(r.get("choice"), int) or not r.get("asset"):
                continue
            s, now = saved.get(r.get("scene")), shown.get(r.get("scene"))
            if s is None or now is None or s.get("id") in out:
                continue
            sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
            alts = [a for a in (sem.get("alternatives") or []) if isinstance(a, dict)]
            alt = alts[r["choice"] - 1] if 0 < r["choice"] <= len(alts) else None
            now_sem = now.get("semanticMetadata") if isinstance(now.get("semanticMetadata"), dict) else {}
            if alt is None or str(alt.get("assetId") or "") != r["asset"] or now_sem.get("assetId") != r["asset"]:
                continue                        # not the same choice on both: left marked for the owner
            src = _alt_file(alt)
            kind = str((now.get("media") or {}).get("type") or "")
            if not src or kind not in ("video", "image"):
                continue
            before = copy.deepcopy(s)
            swap_in(s, {"alt": alt, "src": src, "kind": kind,
                        "seconds": _f((now.get("media") or {}).get("clipSeconds")) or 0.0},
                    str(r.get("note") or DEFAULT_NOTE.get(str(r.get("issue")), "")))
            out[str(s.get("id"))] = before
    except Exception as e:  # noqa: BLE001 - the saved timeline keeps what it has, marked for the owner
        print(f"[review] the swaps were not carried to the saved timeline: {type(e).__name__}: {str(e)[:120]}",
              flush=True)
    return out


def unsaved_back(doc: dict, carried: Dict[str, dict]) -> List[str]:
    """
    A carried swap whose clip is still a file on this disk after the timeline
    was published (its upload failed) gets the saved scene it replaced back:
    a saved timeline never points at a file that goes with the job. Removes
    those from `carried`; returns their ids.
    """
    back = []
    for s in (doc or {}).get("scenes") or []:
        sid = str(s.get("id")) if isinstance(s, dict) else ""
        if sid not in carried:
            continue
        url = str((s.get("media") or {}).get("url") or "")
        if not url.startswith(("http://", "https://")):
            s.clear()
            s.update(carried.pop(sid))
            back.append(sid)
    return back


def mark_for_review(doc: dict, reviewed: Optional[dict], carried=None) -> int:
    """
    A saved timeline's scenes the review changed or flagged in the finished
    video (its render copy), marked for the editor with what was done - the
    editor shows the timeline, and the owner must see what changed (the
    quality gate's rule, quality.mark_for_review). A scene in `carried` shows
    its swap on the saved timeline already (carry_swaps: marked by the swap
    itself). The sound's findings are not a scene's. Returns how many scenes
    were marked.
    """
    by_id = {s.get("id"): s for s in (doc or {}).get("scenes") or [] if isinstance(s, dict)}
    n = 0
    for r in (reviewed or {}).get("fixed") or []:
        s = by_id.get(r.get("scene"))
        if s is None or r.get("issue") == "text-over-face" or r.get("scene") in (carried or ()):
            continue
        s["reviewRequired"] = True
        s["reviewReason"] = (f"The AI review changed this scene in the finished video ({r.get('note')}): "
                             f"{r.get('how')} - replace it here to match")
        n += 1
    for r in (reviewed or {}).get("left") or []:
        s = by_id.get(r.get("scene"))
        if s is None or r.get("sound") or r.get("issue") not in ISSUES:
            continue
        s["reviewRequired"] = True
        s["reviewReason"] = f"The AI review: {r.get('issue')} - {r.get('note')}"
        n += 1
    return n
