"""
No shot stays on screen longer than 7 seconds (the owner, 2026-10-04: "some of
the clips are playing more than seven seconds on the timeline, fix that issue").

Measured that day on his own videos: the Lake Mead video (240 scenes) showed
132 shots (55%) for more than 7 s, and another plan of his 102 of 201 (51%).
Two things let a shot run long. The scene cutter's own ceiling is
MAX_SCENE_SECONDS (9 s unless a video style lowers it), so about half the
beats came out 7-9 s. And a line nothing was found for was covered by HOLDING
the neighbouring shot over it (src/gapfill.py, its clip slowed to 0.85x and
then 0.6x to stretch): those 24 held shots averaged 11.3 s and ran up to
16.8 s (20.3 s in the other plan).

One rule: SHOT_MAX_SECONDS (7.0; one job can change it with {"config":
{"SHOT_MAX_SECONDS": 6}}, a video style may set its own in src/styles.py;
never above CEILING, 12 s; 0 = off, every plan exactly as before).

  prepare    BEFORE the shots are planned (handler.do_plan, after src/mentions.py
             and the hook booster): every beat on screen longer than the cap is
             cut into 2+ shots on word boundaries - a sentence end, a comma or a
             breath first, never inside a phrase or a name (the same reading of
             the words as the scene cutter, transcribe._cut_features). The
             director plans each piece and each is SOURCED AND JUDGED like any
             other beat, so the rules that keep a video honest apply unchanged:
             every clip fits its own line, never the same file or moment twice.
             (Lowering the cutter's own ceiling instead moved its good cuts:
             on the two benchmark narrations the share of cuts that close a
             sentence or clause fell from 100% to 44-75%.)
  holds      AFTER the footage is found and after every repair
             (gapfill.hold_or_animate reads room/hold_rates/alternative_for
             here): a neighbouring shot is held over an empty line only while
             it stays within the cap and its clip covers the longer scene at
             real speed - a clip is never slowed to stretch. When a hold would
             break the cap the line gets, in order: a pick-a-shot runner-up of
             a shot beside it (an approved clip nobody shows yet), another
             moment of a neighbouring YouTube clip FALLBACK_MOMENT_GAP_SECONDS
             from the one shown (fetched and checked like a chain shot), the
             fallback ladder where it has not just run (the pools' spare
             moments), and only then its line as a full-screen text card.
  report     doc.meta.shotCap: shots over the cap before and after, the cuts
             made, what replaced a hold.

Full-screen graphics, maps and animation scenes keep their own lengths: they
are not shots of footage, and nothing here counts or cuts them.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

from . import config

# What the last prepare() did, and what the holds did since (handler: doc.meta.shotCap).
LAST: Dict[str, Any] = {}
# What the cap changed about the holds of this job (gapfill.hold_or_animate adds to it).
SWAPS: Dict[str, int] = {}

CEILING = 12.0             # "nothing above 12 s anywhere": the longest cap any job or style may set
FLOOR = 3.0                # a cap under this would cut every sentence to flashes
MIN_WORDS = 2              # a shot is never a single word (unless nothing else fits)
MIN_PIECE = 2.0            # a piece's shortest time on screen (s); MIN_SCENE_SECONDS / 2 when that is longer
FLASH = 1.0                # under this a piece is a flash: only when the cap cannot be kept otherwise
W_LEN = 2.0                # as transcribe._W_LENGTH: (length - target) / target, squared
W_CUT = 1.5                # as transcribe._W_CUT: x (1 - cut quality)
OVER = 1000.0              # a piece still over the cap: only when the words leave no other cut
SHORT = 60.0               # a piece under the shortest length
FEW = 30.0                 # a one-word piece
TOLERANCE_FRAMES = 2       # a scene this many frames over the cap is rounding, not a long shot
DONOR_REACH = 2            # a runner-up comes from a shot at most this many scenes away
EXAMPLES = 12              # cuts kept in the report (a 30-minute video makes over a hundred)


def limit() -> float:
    """The cap in seconds, 0.0 when the rule is off. Never above CEILING, never a cap of flashes."""
    try:
        v = float(getattr(config, "SHOT_MAX_SECONDS", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v) or v <= 0:
        return 0.0
    return min(CEILING, max(FLOOR, v))


def enabled() -> bool:
    return limit() > 0


def reset() -> None:
    """A new job: nothing cut, nothing swapped yet (the handler, with gapfill.reset)."""
    LAST.clear()
    SWAPS.clear()


def note(what: str, n: int = 1) -> None:
    SWAPS[what] = int(SWAPS.get(what, 0)) + int(n)


# --------------------------------------------------------------------------- #
# Before the shots are planned: a long beat becomes 2+ shots
# --------------------------------------------------------------------------- #

def shortest() -> float:
    """The shortest piece a cut may leave on screen (s)."""
    cap = limit() or 7.0
    half = float(getattr(config, "MIN_SCENE_SECONDS", 5.0) or 0.0) / 2.0
    return min(max(MIN_PIECE, half), cap / 2.5)


def _cut_times(words: list, t0: float, t1: float) -> List[float]:
    """
    When the picture changes for a cut before each word: on the word, or - as
    the scene cutter does (CUT_LEAD_SECONDS) - a moment early in the breath
    before a new sentence, never before the last word of the piece in front.
    times[0] and times[n] are the beat's own time on screen.
    """
    from . import transcribe
    lead = max(0.0, float(getattr(config, "CUT_LEAD_SECONDS", 0.0) or 0.0))
    times = [t0]
    for k in range(1, len(words)):
        at = float(words[k].start)
        if lead:
            back = lead if transcribe._ends_sentence(str(getattr(words[k - 1], "text", "") or "")) else lead / 2.0
            at = max(float(words[k - 1].end), at - back)
        times.append(min(t1, max(times[-1], at)))
    times.append(t1)
    return times


def choose_cuts(words: list, t0: float, t1: float, cap: float, lo: float) -> Optional[Tuple[int, ...]]:
    """
    The word indices a beat on screen from t0 to t1 is cut before, or None when
    its words offer no cut: as few shots as the cap allows, about equal, each
    cut where the narration offers one (hookboost._quality: a sentence end, a
    clause or a breath cost least; inside a phrase or a name most), every shot
    within the cap and at least `lo` seconds and two words wherever the words
    allow it. Chosen all at once (dynamic programming over the word boundaries,
    as transcribe.human_cuts).
    """
    from . import hookboost
    n = len(words)
    length = t1 - t0
    if n < 2 or length <= cap + 1e-6:
        return None
    quality = hookboost._quality(words)
    times = _cut_times(words, t0, t1)
    target = length / max(2, math.ceil(length / cap - 1e-9))
    inf = float("inf")
    best = [inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        cut = W_CUT * (1.0 - quality[j]) if j < n else 0.0
        for i in range(j - 1, -1, -1):
            if best[i] == inf:
                continue
            x = times[j] - times[i]
            cost = best[i] + W_LEN * ((x - target) / target) ** 2 + cut
            if x > cap + 1e-6:
                cost += OVER + 100.0 * (x - cap)
            if x < lo - 1e-6:
                cost += SHORT + 50.0 * (lo - x) + (300.0 if x < FLASH else 0.0)
            if j - i < MIN_WORDS:
                cost += FEW
            if cost < best[j]:
                best[j], back[j] = cost, i
    cuts = []
    j = n
    while j > 0:
        j = back[j]
        if j > 0:
            cuts.append(j)
    return tuple(sorted(cuts)) or None


def _screen(segments: list, until: Optional[float]) -> Tuple[List[float], List[float]]:
    """(start, end) of each beat ON SCREEN: from its start (the first from frame 0) to the next beat's start."""
    starts = [float(s.start) for s in segments]
    if starts:
        starts[0] = min(starts[0], 0.0)
    tail = float(until) if until else float(segments[-1].end)
    ends = starts[1:] + [max(tail, starts[-1])]
    return starts, ends


def _stats(lengths: List[float], cap: float) -> dict:
    over = [x for x in lengths if x > cap + 1e-6]
    return {"shots": len(lengths), "over": len(over),
            "share": round(len(over) / len(lengths), 3) if lengths else 0.0,
            "longest": round(max(lengths), 2) if lengths else 0.0,
            "average": round(sum(lengths) / len(lengths), 2) if lengths else 0.0}


def split_long(segments: list, until: Optional[float] = None) -> Tuple[list, List[int], dict]:
    """
    (beats, parent index of each, info): every beat on screen longer than the
    cap cut into shots. The input beats are never changed; with nothing to cut
    the same list comes back.
    """
    from . import hookboost, mentions
    cap = limit()
    lo = shortest()
    starts, ends = _screen(segments, until)
    out: list = []
    parents: List[int] = []
    splits: List[dict] = []
    after: List[float] = []
    for idx, seg in enumerate(segments):
        t0, t1 = starts[idx], ends[idx]
        words = list(getattr(seg, "words", None) or [])
        cuts = choose_cuts(words, t0, t1, cap, lo) if t1 - t0 > cap + 1e-6 else None
        if not cuts:
            out.append(seg)
            parents.append(idx)
            after.append(t1 - t0)
            continue
        times = _cut_times(words, t0, t1)
        bounds = [0] + list(cuts) + [len(words)]
        marks = [float(seg.start)] + [times[c] for c in cuts] + [float(seg.end)]
        pieces = []
        for text, a, b, t_a, t_b in zip(hookboost._texts(seg, cuts), bounds, bounds[1:], marks, marks[1:]):
            out.append(mentions._piece(seg, text, t_a, max(t_a, t_b), words[a:b]))
            parents.append(idx)
            pieces.append([round(t_a, 2), round(t_b, 2)])
        screen = [t0] + [times[c] for c in cuts] + [t1]
        after += [b - a for a, b in zip(screen, screen[1:])]
        splits.append({"beat": idx, "start": round(t0, 2), "seconds": round(t1 - t0, 2), "pieces": pieces,
                       "cutBefore": [str(getattr(words[c], "text", "")) for c in cuts]})
    info = {"seconds": cap, "beatsBefore": len(segments), "beatsAfter": len(out),
            "cut": len(splits), "shotsAdded": len(out) - len(segments),
            "before": _stats([b - a for a, b in zip(starts, ends)], cap), "planned": _stats(after, cap),
            "examples": splits[:EXAMPLES]}
    return (out if splits else segments), parents, info


def prepare(segments: list, brief: Optional[dict], focus: Optional[Dict[int, dict]] = None,
            until: Optional[float] = None) -> Tuple[list, Dict[int, dict], dict]:
    """
    (beats, focus, info) for handler.do_plan, after mentions.prepare and the hook
    booster and before the shots are planned: every beat longer than the cap
    cut into shots, the brief's beat numbers (hookBeats, sections) and the focus
    moved onto the new beats in place. `until` is where the visual track ends
    (the narration's length). Off: the beats and focus as they came, info {}.
    Never raises: anything unexpected leaves the beats as they were.
    """
    LAST.clear()
    focus = focus if focus is not None else {}
    if not enabled() or not segments:
        return segments, focus, {}
    try:
        from . import hookboost, mentions
        out, parents, info = split_long(segments, until)
        if out is not segments:
            mentions.remap_brief(brief, parents)
            focus = hookboost.remap_focus(focus, parents)
    except Exception as e:  # noqa: BLE001 - a longer shot, never a failed video
        print(f"[shotcap] skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return segments, focus, {}
    LAST.update(info)
    print(f"[shotcap] no shot over {info['seconds']:g} s: {info['before']['over']} of {info['beatsBefore']} beats "
          f"ran longer (the longest {info['before']['longest']} s); {info['cut']} cut on word boundaries -> "
          f"{info['beatsAfter']} beats, {info['planned']['over']} still over", flush=True)
    return out, focus, info


def screen_seconds(segments: list, until: Optional[float] = None) -> List[float]:
    """Each beat's time on screen, for the footage search: the clip found for it covers it at real speed."""
    starts, ends = _screen(segments, until)
    return [b - a for a, b in zip(starts, ends)]


# --------------------------------------------------------------------------- #
# After the footage is found: a hold never breaks the cap
# --------------------------------------------------------------------------- #

def cap_frames(fps: int) -> int:
    """The cap in frames (0 = off)."""
    cap = limit()
    return int(round(cap * max(1, fps))) if cap else 0


def is_shot(scene: dict) -> bool:
    """A shot of footage or a still - what the cap is about. Not a graphic, a map, an animation or an empty scene."""
    m = scene.get("media") or {}
    return m.get("type") in ("video", "image") and bool(m.get("url")) and not scene.get("animation") \
        and str(scene.get("visualType") or "footage") not in ("animation", "map")


def hold_rates() -> Tuple[float, ...]:
    """
    The speeds a held clip may play at to cover its longer scene, tried in
    order: with the cap on, real speed only (a clip is never slowed to
    stretch); off, HOLD_MIN_RATE and then the renderer's own 0.6 floor.
    """
    if enabled():
        return (1.0,)
    return (float(getattr(config, "HOLD_MIN_RATE", 0.85)), 0.6)


def room(scene: dict, fps: int, free: float) -> float:
    """Frames a shot may still grow: `free` (what its picture covers), and never past the cap."""
    cap = cap_frames(fps)
    if not cap:
        return free
    return max(0.0, min(free, cap - int(scene.get("durationInFrames") or 0)))


_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")


def _kind(path: str, default: str = "video") -> str:
    ext = os.path.splitext(str(path or "").split("?")[0].split("#")[0])[1].lower()
    return "image" if ext in _IMAGE_EXT else default


def _reach(url: str, want: str) -> bool:
    """Whether the renderer can load a runner-up's published copy (quality.reach: our R2 object, a small read)."""
    try:
        from . import quality
        return bool(quality.reach(url, want, tries=1).ok)
    except Exception:  # noqa: BLE001 - not known to be there: not taken
        return False


def _probe(src: str) -> float:
    """A clip's real length (ffprobe on its file or its published copy), 0.0 when it cannot be read."""
    try:
        from . import quality
        got = quality.probe_video(quality._probe_source(src))
        return float(got.seconds or 0.0) if got.ok and not got.unverified else 0.0
    except Exception:  # noqa: BLE001 - unknown
        return 0.0


def _alt_media(alt: dict) -> Optional[dict]:
    """
    A runner-up's picture as scene media: its file on this disk while the job
    that found it runs (the plan), else its published copy (the editor's
    pick-a-shot choice, handler._publish_choices) when that still loads.
    """
    path = str(alt.get("localPath") or "")
    if path and os.path.isfile(path):
        return {"type": _kind(path), "url": path, "source": str(alt.get("source") or ""),
                "attribution": str(alt.get("title") or "")}
    m = alt.get("media") if isinstance(alt.get("media"), dict) else {}
    url = str(m.get("url") or "")
    if not url:
        return None
    kind = _kind(url, str(m.get("type") or "video"))
    if url.startswith(("http://", "https://")) and not _reach(url, kind):
        return None
    return {**m, "type": kind}


def _alt_seconds(alt: dict, media: dict) -> float:
    """
    The runner-up clip's length: measured from its file while it is on this
    disk, else as recorded with the choice (media._best_of), else measured from
    its published copy. 0.0 = unknown, and the clip is not taken.
    """
    def number(v) -> float:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0.0

    path = str(alt.get("localPath") or "")
    url = str(media.get("url") or "")
    return (number(media.get("clipSeconds")) or (_probe(path) if path and os.path.isfile(path) else 0.0)
            or number(alt.get("seconds")) or (_probe(url) if url.startswith(("http://", "https://")) else 0.0))


def _alt_shot(alt: dict, media: dict, at: float):
    """The runner-up as gapfill judges repeats (its source video and moment, its file)."""
    from . import gapfill
    ident = str(alt.get("assetId") or "")
    src = str(alt.get("sourceUrl") or alt.get("url") or "")
    video = gapfill._video_of(ident, src) if media.get("type") == "video" else ""
    moment = alt.get("moment") if isinstance(alt.get("moment"), dict) else {}
    return gapfill.Shot(ident="" if video else ident, files=tuple(gapfill._files_of(media.get("url") or "")),
                        video=video, start=gapfill._start_from(moment, src, "") if video else None, at=at)


def alternative_for(doc: dict, i: int, used) -> Optional[dict]:
    """
    A pick-a-shot runner-up of a shot beside empty scene i (at most DONOR_REACH
    scenes away), put on the scene: a clip the judge approved for the line
    next to it that no scene shows, the nearest and best-scored first. Never
    one the video already shows (`used`, gapfill.Used: the same file, asset or
    moment, the same source video on the next scene), never a clip too short
    to cover the scene at real speed. The runner-up leaves its own scene's
    choices. Returns what was taken ({"from", "assetId"}) or None.
    """
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    need = int(s.get("durationInFrames") or 0) / fps
    at = int(s.get("startFrame") or 0) / fps
    options = []
    for reach in range(1, DONOR_REACH + 1):
        for k in (i - reach, i + reach):
            if not 0 <= k < len(scenes) or not is_shot(scenes[k]):
                continue
            sem = scenes[k].get("semanticMetadata") or {}
            for alt in sem.get("alternatives") or []:
                if not isinstance(alt, dict) or not (alt.get("localPath") or (alt.get("media") or {}).get("url")):
                    continue
                score = alt.get("finalScore") if isinstance(alt.get("finalScore"), (int, float)) else alt.get("score")
                options.append((reach, -(float(score) if isinstance(score, (int, float)) else 0.0),
                                len(options), k, alt))
    for _near, _score, _n, k, alt in sorted(options, key=lambda o: o[:3]):
        media = _alt_media(alt)
        if media is None:
            continue
        if media["type"] == "video":
            seconds = _alt_seconds(alt, media)
            if seconds < need - TOLERANCE_FRAMES / fps:
                continue                        # it would have to be slowed (or freeze) to fill the scene
            media["clipSeconds"] = round(seconds, 2)
        shot = _alt_shot(alt, media, at)
        if not used.claim(i, shot):
            continue
        donor = scenes[k]
        donor["semanticMetadata"]["alternatives"] = [a for a in donor["semanticMetadata"]["alternatives"]
                                                     if a is not alt]
        s["media"] = media
        s.pop("animation", None)
        sem = s.setdefault("semanticMetadata", {})
        src = str(alt.get("sourceUrl") or alt.get("url") or "")
        sem.update({"assetId": str(alt.get("assetId") or ""), "provider": str(alt.get("source") or ""),
                    "sourceUrl": src if src.startswith("http") else "",
                    "contentDescription": str(alt.get("description") or ""),
                    "relevanceScore": alt.get("score"), "qualityScore": alt.get("quality"),
                    "moment": dict(alt.get("moment") or {}), "alternatives": [],
                    "shotCap": {"from": str(donor.get("id") or ""), "how": "alternative"}})
        if media["type"] == "image":
            s["motion"] = s.get("motion") or "none"
        s["reviewRequired"] = True
        s["reviewReason"] = ("Another approved shot of the line beside it: nothing new was found for this line "
                             "in time, and holding the shot beside it would have run past "
                             f"{limit():g} s - replace or keep")
        return {"from": str(donor.get("id") or ""), "assetId": str(alt.get("assetId") or "")}
    return None


def _yt_of(scene: dict) -> Tuple[str, Optional[float]]:
    """(YouTube id, where in it) of a scene's clip, ("", None) for anything else."""
    from . import gapfill
    m = scene.get("media") or {}
    if m.get("type") != "video" or not m.get("url"):
        return "", None
    sem = scene.get("semanticMetadata") or {}
    src = str(sem.get("sourceUrl") or "")
    video = gapfill._video_of(str(sem.get("assetId") or ""), src)
    if not video.startswith("yt:"):
        return "", None
    moment = sem.get("moment") if isinstance(sem.get("moment"), dict) else {}
    return video[3:], gapfill._start_from(moment, src, str(m.get("url") or ""))


def same_video_moment(doc: dict, i: int, used, work: str, seconds: Optional[float] = None) -> Optional[dict]:
    """
    Another moment of a neighbouring YouTube clip for empty scene i, at least
    FALLBACK_MOMENT_GAP_SECONDS from the one shown (after it first, before it
    when the video has no room after): fetched and checked the way a planned
    chain shot is (media.fill_chains - the clip's quality, the AI-slop and
    still filters, the cross-video ledger), never a moment the video shows or
    one within the gap of it. The scene then plays on with the clip beside it
    as a chain, which the repeat rules allow on the next scene. Takes at most
    `seconds` (FALLBACK_SCENE_SECONDS). Returns {"from", "assetId"} or None.
    """
    import time

    from . import gapfill, ledger, media, ytdlp
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    need = round(int(s.get("durationInFrames") or 0) / fps + media.SEQ_SHOT_PAD, 2)
    at_line = int(s.get("startFrame") or 0) / fps
    gap = float(getattr(config, "FALLBACK_MOMENT_GAP_SECONDS", 30.0) or 30.0)
    window = float(seconds if seconds is not None else getattr(config, "FALLBACK_SCENE_SECONDS", 45.0))
    stop = time.time() + max(5.0, window)
    old = ytdlp.DEADLINE[0]
    ytdlp.set_deadline(stop)
    try:
        for k in (i - 1, i + 1):
            if not 0 <= k < len(scenes) or not is_shot(scenes[k]):
                continue
            vid, start = _yt_of(scenes[k])
            if not vid or start is None:
                continue
            donor = scenes[k]
            shown = int(donor.get("durationInFrames") or 0) / fps
            for at in (start + shown + gap, start - gap - need):
                if time.time() > stop:
                    return None
                if at < 0 or ledger.moment_used(vid, at, at + need):
                    continue
                shot = gapfill.Shot(video=f"yt:{vid}", start=at, at=at_line, chain=True)
                if not used.claim(i, shot):
                    continue
                title = str((donor.get("media") or {}).get("attribution") or "")
                try:
                    path, clean, cuts = media.fetch_clean_clip(vid, work, at, need, title)
                except Exception as e:  # noqa: BLE001 - the next moment, or the next step
                    print(f"[shotcap] scene {i + 1}: moment {at:.0f}s of {vid} not fetched: {type(e).__name__}",
                          flush=True)
                    path = ""
                asset = None
                if path:
                    asset = media.MediaAsset(
                        kind="video", source="youtube", local_path=path, duration=need,
                        url=f"https://www.youtube.com/watch?v={vid}&t={int(at)}",
                        attribution=title, license=str((donor.get("media") or {}).get("license") or ""),
                        moment_key=f"yt:{vid}@{int(at // max(1.0, float(config.POOL_MIN_GAP_SECONDS)))}",
                        moment={"start": round(at, 1), "chain": True, "clean": clean, "cuts": cuts,
                                "chain_of": str((donor.get("semanticMetadata") or {}).get("assetId") or "")})
                    if not media._asset_ok(asset)[0] or media.motion_rejects(path) or media.slop_reason(path, title):
                        asset = None
                if asset is None:
                    used.release(i, shot)
                    continue
                gapfill.apply_asset(s, asset, "")
                s["reviewRequired"] = True
                s["reviewReason"] = ("Another moment of the clip beside it: nothing new was found for this line in "
                                     f"time, and holding that clip would have run past {limit():g} s - replace or keep")
                s["semanticMetadata"]["shotCap"] = {"from": str(donor.get("id") or ""), "how": "moment"}
                return {"from": str(donor.get("id") or ""), "assetId": asset.identity}
        return None
    finally:
        ytdlp.set_deadline(old)


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #

def over_cap(doc: dict) -> List[dict]:
    """Every shot of footage or still on screen longer than the cap (graphics, maps and animations keep their length)."""
    fps = max(1, int(doc.get("fps") or 30))
    cap = cap_frames(fps)
    if not cap:
        return []
    out = []
    for s in doc.get("scenes") or []:
        frames = int(s.get("durationInFrames") or 0)
        if is_shot(s) and frames > cap + TOLERANCE_FRAMES:
            out.append({"scene": str(s.get("id") or ""), "seconds": round(frames / fps, 2),
                        "held": bool((s.get("semanticMetadata") or {}).get("heldOver"))})
    return out


def report(doc: dict, info: Optional[dict] = None) -> dict:
    """
    doc.meta.shotCap: the beats over the cap before, the cuts made on word
    boundaries, the shots over it in the timeline as built (0 unless the words
    left no cut, e.g. a silence longer than the cap), and what the cap did to
    the holds (kept within it, a runner-up or a ladder shot instead, a card).
    """
    cap = limit()
    info = info if info is not None else dict(LAST)
    if not cap:
        return {"seconds": 0.0, "enabled": False}
    fps = max(1, int(doc.get("fps") or 30))
    shots = [int(s.get("durationInFrames") or 0) / fps for s in doc.get("scenes") or [] if is_shot(s)]
    over = over_cap(doc)
    out = {"seconds": cap, "enabled": True,
           "before": dict(info.get("before") or {}), "planned": dict(info.get("planned") or {}),
           "cut": int(info.get("cut") or 0), "shotsAdded": int(info.get("shotsAdded") or 0),
           "examples": list(info.get("examples") or []),
           "after": {"shots": len(shots), "over": len(over),
                     "longest": round(max(shots), 2) if shots else 0.0,
                     "average": round(sum(shots) / len(shots), 2) if shots else 0.0},
           "left": over[:EXAMPLES],
           "holds": {k: int(SWAPS.get(k, 0)) for k in ("held", "refused", "alternative", "moment", "ladder", "card")}}
    return out
