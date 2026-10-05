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
  runner-ups AFTER the footage search and BEFORE the fallback ladder
  first      (handler.do_plan, runner_ups_first): a piece of a cut beat that
             found nothing takes a clip the judge approved for this very line
             (the pick-a-shot runner-ups of a clip the variety rules took off
             it) or for another piece of the same beat (its sibling's
             runner-ups, on this disk in media._best_of's localPath) - real
             footage of the same sentence before the ladder's pictures.
  holds      AFTER the footage is found and after every repair
             (gapfill.hold_or_animate reads room/hold_rates/alternative_for
             here): a neighbouring shot is held over an empty line only while
             it stays within the cap and its clip covers the longer scene at
             real speed - a clip is never slowed to stretch. When a hold would
             break the cap the line gets, in order: a pick-a-shot runner-up -
             its own first (a scene whose clip broke or repeated keeps the
             choices its search made), then one of a shot beside it (an
             approved clip nobody shows yet) - another moment of a
             neighbouring YouTube clip FALLBACK_MOMENT_GAP_SECONDS from the
             one shown (fetched and checked like a chain shot, a few at once),
             the fallback ladder where it has not just run (the pools' spare
             moments), then the shot beside it held PAST the cap - real
             footage beats a text card (the owner) - but never past CEILING
             and never slowed, and only then its line as a full-screen text
             card. Each fresh clip covers its scene at real speed, and with a
             style that allows vertical clips one is framed on its blurred
             copy as the plan frames its own (upscale.frame_vertical).
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
# Moments of a source video this job fetched for an empty line and could not use (the download
# failed, or the clip failed a check): the last resort runs several times a job (the plan, the
# check before publishing, the build's render copy) and never downloads one of these again -
# (video, 10 s bucket) for every line, (video, bucket, scene id) when the hook's opening check
# turned it down for that line alone (its score, its first frame against that line's intent).
FAILED_MOMENTS: set = set()

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
MOMENT_PARALLEL = 6        # other moments fetched at once (as media.fill_chains: a few proxies, not sixteen)
# A runner-up's licence is not kept with the choice: the plan's own words for a clip it cannot vouch for.
UNVERIFIED = "unverified — you must hold the rights"


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
    FAILED_MOMENTS.clear()


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
            # Which beat each new one was cut from (runner_ups_first: a piece's siblings); not in the report.
            info["parents"] = list(parents)
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
# After the footage search, before the fallback ladder: a runner-up of the same sentence
# --------------------------------------------------------------------------- #

def _number(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0.0


def _runner_up_asset(i: int, job: dict, donor, how: str, used, starts: Dict[int, float]):
    """The first of `donor`'s runner-ups that may go on line i, as an asset (claimed in `used`), or None."""
    from . import gapfill, media
    need = float(job.get("seconds") or 0.0)
    at = starts.get(i)
    for alt in list(getattr(donor, "alternatives", None) or []):
        if not isinstance(alt, dict):
            continue
        path = str(alt.get("localPath") or "")
        if not path or not os.path.isfile(path):
            continue                            # not kept, or on a fan-out part's own machine
        kind = _kind(path)
        seconds = 0.0
        if kind == "video":
            seconds = _probe(path) or _number(alt.get("seconds"))
            if seconds < need - TOLERANCE_FRAMES / 30.0:
                continue                        # it would have to be slowed (or freeze) to fill the line
        src = str(alt.get("url") or "")
        ident = str(alt.get("assetId") or "")
        moment = dict(alt.get("moment") or {}) if isinstance(alt.get("moment"), dict) else {}
        asset = media.MediaAsset(
            kind=kind, source=str(alt.get("source") or getattr(donor, "source", "") or "youtube"), url=src,
            local_path=path, duration=round(seconds, 2) if seconds else 0.0,
            attribution=str(alt.get("title") or ""),
            # The donor's own search found it: the same licence terms (require_cc or not).
            license=str(getattr(donor, "license", "") or UNVERIFIED),
            query=str(job.get("query") or ""), intent=str(job.get("intent") or ""),
            review_required=True,
            review_reason=("Another clip the judge approved for this line (its first choice broke a variety rule)"
                           if how == "own" else
                           "A clip the judge approved for the other part of this sentence: nothing was found for "
                           "this part in time") + " - check it fits",
            content_description=str(alt.get("description") or ""),
            relevance_score=alt.get("score") if _number(alt.get("score")) else None,
            quality=alt.get("quality") if _number(alt.get("quality")) else None,
            specificity=str(alt.get("specificity") or ""),
            final_score=alt.get("finalScore") if _number(alt.get("finalScore")) else None,
            moment=moment, moment_key=ident if "@" in ident else "",
            # The judge approved it for its own line (media._best_of keeps only clips that passed) - for
            # a hook line with the opening check on this very cut (src/hookcheck.py).
            judged_by=(("opening" if how == "own" and alt.get("cutCheck") else "frames")
                       if _number(alt.get("score")) else ""),
            cut_check=dict(alt["cutCheck"]) if how == "own" and isinstance(alt.get("cutCheck"), dict) else {})
        shot = gapfill.Shot.of_asset(asset, at)
        if shot.video and not media.may_place(used.placed(shot.video), at):
            continue                            # its video already plays too often or too near
        if not used.claim(i, shot):
            continue                            # the video shows it already, or its video on the next line
        donor.alternatives = [a for a in donor.alternatives if a is not alt]
        return asset
    return None


def runner_ups_first(jobs: List[dict], results: list, info: Optional[dict] = None,
                     held: Optional[Dict[int, tuple]] = None) -> Dict[str, int]:
    """
    Every line the footage search left empty gets, before the fallback
    ladder's pictures (handler.do_plan), a runner-up of its own sentence when
    one is on this disk: first one of its own (a clip the variety rules took
    off it - media.hold_violations, `held` - kept the pick-a-shot runner-ups
    its search judged for this very line), then one of another piece of the
    same beat the cap cut (`info["parents"]` from prepare; the nearest piece
    first). The runner-ups' files stay on the disk of the machine that found
    them (media._best_of, PICK_A_SHOT_CHOICES): a fan-out part's are passed
    over. Never a shot the video already shows or one its variety rules forbid
    (gapfill.Used, media.may_place), never a clip too short to cover the
    line's time on screen at real speed; a runner-up taken leaves its donor's
    choices. Off (SHOT_MAX_SECONDS 0): nothing. Returns {"own", "sibling"}.
    """
    out = {"own": 0, "sibling": 0}
    if not enabled() or not jobs or not results:
        return out
    from . import gapfill, media
    by_index = {j["index"]: j for j in jobs}
    parents = list((info or {}).get("parents") or [])

    def at(k: int):
        return results[k] if 0 <= k < len(results) else None

    empty = [i for i in sorted(by_index) if at(i) is None]
    if not empty:
        return out
    starts = media.scene_starts(jobs)
    used = gapfill.Used.of_results(results, starts)
    for i in empty:
        donors = []
        mine = (held or {}).get(i)
        if mine and mine[0] is not None:
            donors.append(("own", mine[0]))
        if 0 <= i < len(parents):
            reach = 1
            while True:
                sides = [k for k in (i - reach, i + reach) if 0 <= k < len(parents) and parents[k] == parents[i]]
                if not sides:
                    break                       # a beat's pieces are next to each other
                donors += [("sibling", at(k)) for k in sides if at(k) is not None]
                reach += 1
        for how, donor in donors:
            try:
                got = _runner_up_asset(i, by_index[i], donor, how, used, starts)
            except Exception as e:  # noqa: BLE001 - the ladder below
                print(f"[shotcap] line {i + 1}: runner-up skipped: {type(e).__name__}: {str(e)[:80]}", flush=True)
                got = None
            if got is not None:
                results[i] = got
                out[how] += 1
                break
    if any(out.values()):
        note("first", sum(out.values()))
        print(f"[shotcap] {sum(out.values())} of {len(empty)} empty line(s) took a runner-up of their own "
              f"sentence before the ladder ({out['own']} their own, {out['sibling']} another piece's)", flush=True)
    return out


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


def ceiling_frames(fps: int) -> int:
    """CEILING in frames: no shot is ever longer, not even one held past the cap instead of a text card."""
    return int(round(CEILING * max(1, fps)))


def room(scene: dict, fps: int, free: float, ceiling: bool = False) -> float:
    """
    Frames a shot may still grow: `free` (what its picture covers), and never
    past the cap - or, with `ceiling` (a hold that is all that stands between
    a line and its text card, gapfill.hold_or_animate), never past CEILING.
    """
    cap = cap_frames(fps)
    if not cap:
        return free
    if ceiling:
        cap = max(cap, ceiling_frames(fps))
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
    pick-a-shot choice, handler._publish_choices) when that still loads. With
    the fields a found clip's media carries (MediaAsset.to_scene_media): its
    licence - unverified, as the choice does not keep one - and its scores.
    """
    extra: Dict[str, Any] = {"license": str(alt.get("license") or UNVERIFIED)}
    for key, field in (("score", "relevanceScore"), ("quality", "qualityScore")):
        v = alt.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            extra[field] = round(float(v), 3)
    if alt.get("description"):
        extra["contentDescription"] = str(alt["description"])
    path = str(alt.get("localPath") or "")
    if path and os.path.isfile(path):
        return {"type": _kind(path), "url": path, "source": str(alt.get("source") or ""),
                "attribution": str(alt.get("title") or ""), **extra}
    m = alt.get("media") if isinstance(alt.get("media"), dict) else {}
    url = str(m.get("url") or "")
    if not url:
        return None
    kind = _kind(url, str(m.get("type") or "video"))
    if url.startswith(("http://", "https://")) and not _reach(url, kind):
        return None
    return {"source": str(alt.get("source") or ""), "attribution": str(alt.get("title") or ""),
            **extra, **m, "type": kind}


def _frame(path: str) -> None:
    """
    A vertical clip on this disk framed on its blurred copy, the way the plan
    frames its own before the timeline is built (upscale.frame_vertical) - only
    where the video's style allows vertical clips (ALLOW_VERTICAL); without
    it object-fit would crop a phone clip to a strip. Landscape clips are left
    alone; a failure keeps the clip as it is.
    """
    if not getattr(config, "ALLOW_VERTICAL", False) or not path or not os.path.isfile(path):
        return
    if _kind(path) != "video":
        return
    try:
        from . import upscale
        upscale.frame_vertical(path)
    except Exception as e:  # noqa: BLE001 - shown as it is
        print(f"[shotcap] framing skipped: {type(e).__name__}: {str(e)[:80]}", flush=True)


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
    A pick-a-shot runner-up for empty scene i, put on the scene: its own first
    (a scene whose clip broke or repeated keeps the choices its search made:
    clips the judge approved for this very line), then one of a shot beside it
    (at most DONOR_REACH scenes away): a clip the judge approved for the line
    next to it that no scene shows, the nearest and best-scored first. Never
    one the video already shows (`used`, gapfill.Used: the same file, asset or
    moment, the same source video on the next scene), never one whose video
    the variety rules forbid here (media.may_place: MAX_MOMENTS_PER_VIDEO,
    SAME_VIDEO_GAP_SECONDS), never a clip too short to cover the scene at
    real speed. The runner-up leaves its scene's choices; the scene's own
    other choices stay. Returns what was taken ({"from", "assetId"}) or None.
    """
    from . import media as _media
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    need = int(s.get("durationInFrames") or 0) / fps
    at = int(s.get("startFrame") or 0) / fps
    options = []
    for reach in range(0, DONOR_REACH + 1):
        for k in ((i,) if reach == 0 else (i - reach, i + reach)):
            # (A cold-open flash of a later shot is not a shot of this part of the story.)
            if not 0 <= k < len(scenes) or scenes[k].get("teaser") or (reach and not is_shot(scenes[k])):
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
        if shot.video and not _media.may_place(used.placed(shot.video), at):
            continue                            # its video already plays too often or too near (variety rules)
        if not used.claim(i, shot):
            continue
        donor = scenes[k]
        donor["semanticMetadata"]["alternatives"] = [a for a in donor["semanticMetadata"]["alternatives"]
                                                     if a is not alt]
        _frame(str(media.get("url") or ""))
        s["media"] = media
        s.pop("animation", None)
        sem = s.setdefault("semanticMetadata", {})
        src = str(alt.get("sourceUrl") or alt.get("url") or "")
        own = [a for a in sem.get("alternatives") or [] if a is not alt]
        sem.pop("cutCheck", None)              # the shot before's check is not this one's
        sem.update({"assetId": str(alt.get("assetId") or ""), "provider": str(alt.get("source") or ""),
                    "sourceUrl": src if src.startswith("http") else "",
                    "contentDescription": str(alt.get("description") or ""),
                    "relevanceScore": alt.get("score"), "qualityScore": alt.get("quality"),
                    "moment": dict(alt.get("moment") or {}), "alternatives": own,
                    "judgedBy": "frames" if _number(alt.get("score")) else "",
                    "shotCap": {"from": str(donor.get("id") or ""), "how": "alternative"}})
        if k == i and isinstance(alt.get("cutCheck"), dict) and alt["cutCheck"]:
            # Its own line's runner-up, judged with the opening check on this very cut (src/hookcheck.py).
            sem["cutCheck"] = dict(alt["cutCheck"])
            sem["judgedBy"] = "opening"
        if media["type"] == "image":
            s["motion"] = s.get("motion") or "none"
        s["reviewRequired"] = True
        s["reviewReason"] = (("Another approved shot for this line: its first choice could not be used"
                              if k == i else "Another approved shot of the line beside it: nothing new was "
                              "found for this line in time")
                             + f", and holding the shot beside it would have run past {limit():g} s - replace or keep")
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


def find_moment(doc: dict, i: int, used, work: str, stop: float) -> Optional[Tuple[Any, dict]]:
    """
    Another moment of a neighbouring YouTube clip for empty scene i, at least
    FALLBACK_MOMENT_GAP_SECONDS from the one shown (after it first, before it
    when the video has no room after): fetched and checked the way a planned
    chain shot is (media.fill_chains - the clip's quality, the AI-slop and
    still filters, the cross-video ledger), never a moment the video shows or
    one within the gap of it, never a clip too short to cover the scene at
    real speed (a moment near the end of its video comes out short). The scene
    then plays on with the clip beside it as a chain, which the repeat rules
    allow on the next scene. Nothing is tried after `stop`. Returns (the
    asset, the scene beside it) - claimed in `used`, not yet on the timeline
    (put_moment) - or None.
    """
    import time

    from . import gapfill, ledger, media, timeline
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    seconds = int(s.get("durationInFrames") or 0) / fps
    need = round(seconds + media.SEQ_SHOT_PAD, 2)
    at_line = int(s.get("startFrame") or 0) / fps
    line = str(s.get("id") or f"#{i}")          # by id: a hold deletes scenes and shifts the indices
    gap = float(getattr(config, "FALLBACK_MOMENT_GAP_SECONDS", 30.0) or 30.0)
    for k in (i - 1, i + 1):
        if not 0 <= k < len(scenes) or scenes[k].get("teaser") or not is_shot(scenes[k]):
            continue
        vid, start = _yt_of(scenes[k])
        if not vid or start is None:
            continue
        donor = scenes[k]
        shown = int(donor.get("durationInFrames") or 0) / fps
        for at in (start + shown + gap, start - gap - need):
            if time.time() > stop:
                return None
            failed = (vid, int(at // 10))           # (a 10 s bucket: the donor's own length may have changed since)
            mine = failed + (line,)                 # turned down for this line only (_opening_turned_down)
            if at < 0 or failed in FAILED_MOMENTS or mine in FAILED_MOMENTS or ledger.moment_used(vid, at, at + need):
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
                    attribution=title, license=str((donor.get("media") or {}).get("license") or UNVERIFIED),
                    moment_key=f"yt:{vid}@{int(at // max(1.0, float(config.POOL_MIN_GAP_SECONDS)))}",
                    moment={"start": round(at, 1), "chain": True, "clean": clean, "cuts": cuts,
                            "chain_of": str((donor.get("semanticMetadata") or {}).get("assetId") or "")},
                    judged_by="none")
                if not media._asset_ok(asset)[0] or media.motion_rejects(path) or media.slop_reason(path, title):
                    asset = None
                    FAILED_MOMENTS.add(failed)
                elif 0 < timeline._clip_seconds(asset) < seconds - TOLERANCE_FRAMES / fps:
                    print(f"[shotcap] scene {i + 1}: moment {at:.0f}s of {vid} too short for its scene", flush=True)
                    asset = None                # it would be slowed (or freeze) to fill the scene
                else:
                    turned = _opening_turned_down(doc, i, asset, seconds)
                    if turned:
                        asset = None            # a hook line: its first frame (or the clip) does not fit the line
                        # A verdict about the clip itself (text, AI-made, poor footage) holds for every line; one
                        # about this line (its score, its first frame against its intent) for this line only.
                        FAILED_MOMENTS.add(failed if turned == TURNED_FOR_ANY_LINE else mine)
            elif time.time() <= stop:
                FAILED_MOMENTS.add(failed)          # not a download cut off by the time box: never asked again
            if asset is None:
                used.release(i, shot)
                continue
            _frame(path)
            return asset, donor
    return None


# _opening_turned_down: the verdict turned the clip down for any line, or for this one.
TURNED_FOR_ANY_LINE = "any line"
TURNED_FOR_THIS_LINE = "this line"


def _opening_turned_down(doc: dict, i: int, asset, seconds: float) -> str:
    """
    Another moment for a line of the hook (src/hookcheck.py): the judge's
    opening check on this very cut - its first moment, middle and end - before
    it goes on the line; the verdict stays with the asset. "" when it was kept;
    when it was turned down (its file is gone), TURNED_FOR_ANY_LINE for a
    reason in the clip itself (text or a watermark, AI-made, poor footage),
    else TURNED_FOR_THIS_LINE (its score, its first frame against this line's
    intent, a presenter a person's line may use). The owner's Glen Canyon test
    (2026-10-05) opened on a moment taken here by arithmetic alone, 1.47 s
    before a cut in its source.
    """
    from . import gapfill, hookcheck
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    if not hookcheck.in_hook(int(s.get("startFrame") or 0) / fps):
        return ""
    job = dict(gapfill.job_for(s, i, fps, gapfill.known_jobs(doc)), hook=True, seconds=seconds)
    keep, verdict = hookcheck.judge(asset.local_path, job, seconds)
    if keep is False:
        print(f"[shotcap] scene {i + 1}: another moment turned down by the opening check "
              f"({hookcheck.why(verdict)})", flush=True)
        try:
            os.remove(asset.local_path)
        except OSError:
            pass
        v = verdict or {}
        q = v.get("quality")
        if v.get("has_text_or_watermark") or v.get("ai_generated") or (q is not None and q < config.VISION_MIN_QUALITY):
            return TURNED_FOR_ANY_LINE
        return TURNED_FOR_THIS_LINE
    if verdict:
        asset.apply_verdict(verdict, str(job.get("intent") or ""))
    return ""


def put_moment(doc: dict, i: int, asset, donor: dict) -> dict:
    """The moment find_moment fetched, on scene i. Returns {"from", "assetId"}."""
    from . import gapfill
    s = doc["scenes"][i]
    gapfill.apply_asset(s, asset, "")
    s["reviewRequired"] = True
    s["reviewReason"] = ("Another moment of the clip beside it: nothing new was found for this line in "
                         f"time, and holding that clip would have run past {limit():g} s - replace or keep")
    s["semanticMetadata"]["shotCap"] = {"from": str(donor.get("id") or ""), "how": "moment"}
    return {"from": str(donor.get("id") or ""), "assetId": asset.identity}


def other_moments(doc: dict, todo: List[int], used, work: str, stop: float) -> Dict[int, dict]:
    """
    find_moment for several empty scenes, MOMENT_PARALLEL at once, all under
    one time box (`stop`, epoch seconds): only what is found by then goes on
    the timeline, here on this thread, so a fetch that finishes late never
    lands on a scene that has had its text card since. The downloads keep to
    the box on their own threads (ytdlp.STOP) and the job's deadline is set to
    it for the while (as the fallback ladder does). Returns {scene index:
    what was taken}.
    """
    import contextvars
    import time
    from concurrent.futures import ThreadPoolExecutor

    from . import gapfill, media, ytdlp
    scenes = doc.get("scenes") or []
    todo = [k for k in todo if 0 <= k < len(scenes) and gapfill._empty(scenes[k])]
    if not todo or not work or time.time() >= stop:
        return {}

    def one(k: int):
        token = ytdlp.STOP.set((None, stop))
        try:
            return find_moment(doc, k, used, work, stop)
        finally:
            ytdlp.STOP.reset(token)

    out: Dict[int, dict] = {}
    old = ytdlp.DEADLINE[0]
    ytdlp.set_deadline(stop)
    pool = ThreadPoolExecutor(max_workers=max(1, min(MOMENT_PARALLEL, len(todo))), thread_name_prefix="shotcap")
    futures = {pool.submit(contextvars.copy_context().run, one, k): k for k in todo}
    try:
        for fut in media._until(futures, stop + 5):
            k = futures[fut]
            try:
                got = fut.result()
            except Exception as e:  # noqa: BLE001 - its text card
                print(f"[shotcap] scene {k + 1}: another moment skipped: {type(e).__name__}: {str(e)[:80]}",
                      flush=True)
                got = None
            if got and gapfill._empty(scenes[k]):
                out[k] = put_moment(doc, k, *got)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        ytdlp.set_deadline(old)
    return out


def same_video_moment(doc: dict, i: int, used, work: str, seconds: Optional[float] = None) -> Optional[dict]:
    """
    other_moments for one empty scene, put on it: at most `seconds`
    (FALLBACK_SCENE_SECONDS). Returns {"from", "assetId"} or None.
    """
    import time
    window = float(seconds if seconds is not None else getattr(config, "FALLBACK_SCENE_SECONDS", 45.0))
    return other_moments(doc, [i], used, work, time.time() + max(5.0, window)).get(i)


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #

def over_cap(doc: dict) -> List[dict]:
    """Every shot of footage or still on screen longer than the cap (graphics, maps, animations keep their length)."""
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
    left no cut, e.g. a silence longer than the cap, or a shot was held past
    it - up to CEILING - where the only other choice was a text card), and
    what the cap did to the holds (kept within it, a runner-up or a ladder
    shot instead, held long, a card).
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
           # "long": a shot held past the cap (never past CEILING, never slowed) instead of a text card.
           "holds": {k: int(SWAPS.get(k, 0)) for k in ("held", "refused", "alternative", "moment", "ladder", "long",
                                                         "card")},
           # Empty lines that took a runner-up of their own sentence before the ladder (runner_ups_first).
           "runnerUpsFirst": int(SWAPS.get("first", 0))}
    return out
