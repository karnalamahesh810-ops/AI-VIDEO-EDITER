"""
The hook's own check (the owner, 2026-10-05, a 5-minute Glen Canyon test: "the first second or two
didn't match" - and the opening is what decides whether a viewer stays).

What that video did. Its first beat ("On the 6th of June, 1983, engineers at Glen Canyon Dam heard
something they had never heard before.") was cut in two by the shot cap (src/shotcap.py). Nothing
the hook search judged passed for either piece, so the second piece (3.0-8.0 s) took the rescue
pass's best-titled search result, cut 35 % into its video with no vision call (media.rescue_fill),
and the first (0.0-3.0 s) another moment of that same video 30 s earlier, picked by arithmetic with
no vision call either (shotcap.find_moment). That moment began 1.47 s before a hard cut in its
source - a cut ffmpeg scored 0.36, under the 0.4 the clean-cut trimming looked for - so the video
opened on the end of the shot before: another creator's "CAVITATION" explainer graphic, under our
JUNE 6 / 1983 title. Neither scene had a verdict on record, and the judge's own three frames (a
quarter, a half and three quarters into a clip) never look at a clip's first second anyway.

  judge(path, job, span)  the vision judge with the opening check (vision.judge `span`): frames at
                          the clip's first moment (0.3 s in), middle and end of the `span` its
                          scene shows, the first frame judged on its own (vision.acceptable). One
                          call. The rescue pass and the shot cap's other moments ask it for a hook
                          line before they place a clip; the hook search's own judge does the same
                          in the call it always made (media._opening_span).
  check(doc)              after the timeline is final (handler: after the check before publishing):
                          every clip and picture starting within HOOK_SECONDS whose own cut has no
                          opening check yet is judged, and the verdict goes on the scene
                          (relevanceScore, contentDescription, judgedBy, cutCheck) for the editor
                          and the later checks. A clip turned down, in order:
                            1. its start moves - past a shot change in its first seconds or the
                               opening the judge turned down, inside its file; or, a YouTube clip
                               whose middle and end fit, cut again from its middle - and the new
                               cut is judged;
                            2. a pick-a-shot runner-up (its own, then one of a shot beside it:
                               shotcap.alternative_for) passes the same check;
                            3. the clip goes and the last resort covers the line
                               (gapfill.hold_or_animate: the line's graphic, the shot beside it
                               held, a fresh shot - judged here the same way - then its text).
                          A clip under the floor with a fitting opening and nothing better stays,
                          flagged, as the hook search keeps its "best available". No verdict at
                          all (vision off, every model failing): the clip stays as it is, marked
                          unjudged - an outage never empties the opening.

Cost: one vision call per hook clip no earlier step judged on its own cut this way, plus one per
new cut tried for a clip turned down (a moved start - at most two - or a runner-up - at most
HOOK_CUT_TRIES), never more than HOOK_CUT_MAX_CALLS a video. Clips that pass cost nothing more.
"""
from __future__ import annotations

import copy
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import config
from .aifill import is_ai_scene
from .presenter import is_presenter_scene

# A clip's file must run on this much past what its scene shows before its opening moves inside it (s).
MIN_SHIFT = 0.3
# The opening moves past a shot change at most this far into the clip (s).
MOVE_REACH = 2.5
# Scenes the report names (the first ones turned down).
EXAMPLES = 12
# Verdicts asked for at once (src/vision.py caps the requests in flight on its own).
PREFETCH_PARALLEL = 4
# yt_<id>_<section start ms>_<section ms>_<fetch id>[_c<offset x 10>] (ytdlp._yt_fetch, filters.trim_clip).
_YT_FILE = re.compile(r"^yt_([\w-]{11})_(\d+)_(\d+)_[0-9a-f]+(?:_c(\d{5}))?")

# Vision calls this job's hook checks made (judge), against HOOK_CUT_MAX_CALLS.
_SPENT = {"calls": 0}
_LOCK = threading.Lock()


def reset() -> None:
    """A new job (the handler, with shotcap.reset)."""
    with _LOCK:
        _SPENT["calls"] = 0


def enabled() -> bool:
    return bool(getattr(config, "HOOK_CUT_CHECK", False)) and float(getattr(config, "HOOK_SECONDS", 0) or 0) > 0


def in_hook(start_seconds: Optional[float]) -> bool:
    """A line starting here is part of the hook, and the check is on."""
    try:
        return enabled() and start_seconds is not None and float(start_seconds) < float(config.HOOK_SECONDS)
    except (TypeError, ValueError):
        return False


def spent() -> bool:
    """This job's hook checks have made HOOK_CUT_MAX_CALLS vision calls."""
    return left() == 0


def left() -> Optional[int]:
    """Vision calls this job's hook checks may still make (None = no cap)."""
    cap = int(getattr(config, "HOOK_CUT_MAX_CALLS", 0) or 0)
    if cap <= 0:
        return None
    with _LOCK:
        return max(0, cap - _SPENT["calls"])


def _reserve() -> bool:
    """
    One call of the budget taken before the judge runs (judge settles it to
    what the call cost), so checks running side by side - the prefetch, the
    rescue pass, the shot cap's other moments - never all pass spent() at once.
    False when none is left.
    """
    cap = int(getattr(config, "HOOK_CUT_MAX_CALLS", 0) or 0)
    with _LOCK:
        if cap > 0 and _SPENT["calls"] >= cap:
            return False
        _SPENT["calls"] += 1
        return True


def judge(path: str, job: Dict[str, Any], span: Optional[float] = None) -> Tuple[Optional[bool], Optional[dict]]:
    """
    (keep, verdict) for one cut of a hook line: the vision judge on the `span`
    seconds its scene shows (the line's own seconds when not given), with the
    opening check for a clip. keep None = no verdict (the check off or its calls
    spent, vision off, every model failing, nothing to judge against): the
    caller keeps what it had. The verdict carries the gate's "accepted".
    """
    from . import media, vision
    if not enabled() or not path or not os.path.isfile(path) or not vision.enabled() or spent():
        return None, None
    intent = " ".join(str(job.get("intent") or job.get("query") or job.get("subject") or "").split())
    if not intent:
        return None, None
    try:
        span = float(span if span is not None else job.get("seconds") or 0.0)
    except (TypeError, ValueError):
        span = 0.0
    si = job.get("scene_intent") if isinstance(job.get("scene_intent"), dict) else None
    wants = media.wanted_kind(si or {})
    if not _reserve():
        return None, None                       # another check took the last call meanwhile
    made = 0
    try:
        # This check's own calls - this thread's, not the shared count other judges add to meanwhile.
        before = vision.calls_here()
        verdict = vision.judge(path, intent, str(job.get("context") or ""), event=bool(job.get("event_window")),
                               **({"scene": si} if si else {}),
                               **({"wants": wants} if wants in ("map", "chart") else {}),
                               **({"span": span} if span > 0 else {}))
        made = max(0, vision.calls_here() - before)
    finally:
        with _LOCK:
            _SPENT["calls"] += made - 1         # the reservation becomes what it cost (0: a remembered verdict)
    if verdict is None:
        return None, None
    # A music, club or smoking scene the story and the line are not about (src/topics.py): a clear no.
    off = media.off_story(verdict, f"{intent} {job.get('context') or ''}")
    keep = vision.acceptable(verdict, allow_people=job.get("subject_type") == "person", allow_vice=not off)
    return keep, dict(verdict, accepted=keep, **({"off_topic": True} if off else {}))


def why(verdict: Optional[dict]) -> str:
    """The judge's reason to turn a cut down, in plain words."""
    v = verdict or {}
    if not v:
        return "not checked"
    if v.get("opening") is False:
        return "its first frame shows something else"
    if v.get("has_text_or_watermark"):
        return "text or a watermark on it"
    if v.get("ai_generated"):
        return "it looks AI-made"
    if v.get("off_topic"):
        return "a music, club or smoking scene the story is not about"
    if v.get("studio"):
        return "a studio, presenter or screen"
    if v.get("is_talking_head"):
        return "a talking head"
    q = v.get("quality")
    if q is not None and q < config.VISION_MIN_QUALITY:
        return f"footage quality {q:.2f}"
    return f"it scored {float(v.get('score') or 0):.2f} for its line"


def soft(verdict: Optional[dict]) -> bool:
    """Under the floor only on its score, but near it and with an opening that fits: the 'best available'."""
    v = verdict or {}
    if not v or v.get("opening") is False or v.get("has_text_or_watermark") or v.get("ai_generated") \
            or v.get("studio") or v.get("is_talking_head") or v.get("off_topic"):
        return False
    q = v.get("quality")
    if q is not None and q < config.VISION_MIN_QUALITY:
        return False
    return float(v.get("score") or 0.0) >= config.VISION_SOFT_MIN_SCORE


# --------------------------------------------------------------------------- #
# The scenes
# --------------------------------------------------------------------------- #

def _local(url: str) -> str:
    """The scene's file on this disk, or '' (a link: a render-time timeline is not checked here)."""
    url = str(url or "")
    if url.lower().startswith("file://"):
        url = url[7:]
    if not url or url.lower().startswith(("http://", "https://", "data:", "blob:")):
        return ""
    return url if os.path.isfile(url) else ""


def _checked(scene: dict) -> bool:
    """
    Its own picture already had this check: a clip whose cut passed the opening
    check (the hook search's winner, a rescue clip or moment checked before it
    was placed, a cut this check judged) or one the hook search kept knowingly
    under the floor; a picture with a vision verdict of its own.
    """
    sem = scene.get("semanticMetadata") or {}
    if (scene.get("media") or {}).get("type") == "image":
        return sem.get("relevanceScore") is not None and str(sem.get("judgedBy") or "") not in ("tile", "local",
                                                                                                "none", "chain")
    cut = sem.get("cutCheck") if isinstance(sem.get("cutCheck"), dict) else {}
    return bool(cut.get("frames")) and cut.get("opening") is not False and cut.get("ok") is not None


def record(scene: dict, verdict: Optional[dict], keep: Optional[bool]) -> None:
    """The verdict on the scene, where the editor and the later checks read it."""
    from . import vision
    sem = scene.setdefault("semanticMetadata", {})
    m = scene.setdefault("media", {})
    if not verdict:
        sem["cutCheck"] = {"ok": None, "unjudged": True}
        return
    desc = str(verdict.get("description") or "")[:300]
    score = verdict.get("score")
    quality = verdict.get("quality")
    sem["contentDescription"] = desc
    sem["relevanceScore"] = score
    sem["qualityScore"] = quality
    if verdict.get("specificity"):
        sem["specificity"] = verdict["specificity"]
    m["contentDescription"] = desc
    if isinstance(score, (int, float)):
        m["relevanceScore"] = round(float(score), 3)
    if isinstance(quality, (int, float)):
        m["qualityScore"] = round(float(quality), 3)
    cut = vision.cut_record(dict(verdict, accepted=keep))
    sem["judgedBy"] = "opening" if cut else "frames"
    sem["cutCheck"] = cut or {"score": score, "ok": keep}


def _source_point(scene: dict, path: str) -> Tuple[str, Optional[float]]:
    """(YouTube id, the second of its video the clip starts at), from its file's name, else its scene."""
    m = _YT_FILE.match(os.path.basename(path or ""))
    if m:
        return m.group(1), int(m.group(2)) / 1000.0 + (int(m.group(4)) / 10.0 if m.group(4) else 0.0)
    from . import shotcap
    return shotcap._yt_of(scene)


def _put_cut(scene: dict, path: str, seconds: float, start: Optional[float] = None) -> None:
    """A new cut of the same shot on the scene: its file, its length, where in its source it starts."""
    m = scene["media"]
    m["url"] = path
    if seconds > 0:
        m["clipSeconds"] = round(seconds, 2)
    sem = scene.setdefault("semanticMetadata", {})
    if start is not None:
        moment = dict(sem.get("moment") or {}) if isinstance(sem.get("moment"), dict) else {}
        moment["start"] = round(float(start), 1)
        sem["moment"] = moment
        src = str(sem.get("sourceUrl") or "")
        if "youtube.com/watch" in src:
            sem["sourceUrl"] = re.sub(r"([?&])t=\d+(?:\.\d+)?", rf"\g<1>t={int(start)}", src) if "t=" in src \
                else f"{src}&t={int(start)}"


def move_start(scene: dict, path: str, job: dict, span: float, verdict: Optional[dict], work: str = "",
               cover: Optional[float] = None, until: float = 0.0,
               others: Sequence[Tuple[str, float, float]] = ()) -> bool:
    """
    A clip whose opening was turned down, its start moved and the new cut judged
    (True when it passed and is on the scene): first inside its own file - past
    a shot change in its first MOVE_REACH seconds, else (the first frame turned
    down) as far as the file runs on past what the scene shows - and then, a
    YouTube clip whose first frame was turned down, cut again from its source
    starting at its middle frame (one download, the new cut judged like any:
    the verdict's own score takes in that bad first frame - a title card there
    is told to score 0 - so it says nothing about the middle). Never a cut
    shorter than `cover` (what the scene plays, a crossfade into the next
    included; `span` when not given): a clip is never slowed. Nothing is tried
    that no verdict could follow (vision off, the calls spent). The download
    keeps to FALLBACK_SCENE_SECONDS, and to `until` (epoch seconds, the whole
    check's box; 0 = none): past it nothing is fetched. Never a start whose
    footage another scene shows (`others`: (YouTube id, from, to) of what the
    other scenes play - the chained next moment of this very clip above all,
    which the repeat checks let through as a chain).
    """
    from . import filters, media
    if (scene.get("media") or {}).get("type") != "video" or not path or not _can_judge():
        return False
    v = verdict or {}
    cover = max(span, float(cover or 0.0))
    dur = filters._video_seconds(path)
    if dur > 0:
        pad = float(config.CUT_SNAP_PAD)
        cuts = filters.scene_cuts(path)
        early = [c for c in cuts if 0.0 < c <= MOVE_REACH]
        starts = [max(early) + pad] if early else []
        if v.get("opening") is False and dur - cover >= MIN_SHIFT:
            starts.append(dur - cover)          # as far as the file runs on past what the scene plays
        vid0, was0 = _source_point(scene, path)
        for at in dict.fromkeys(round(a, 3) for a in starts):
            if dur - at < cover - 0.05:
                continue                        # what is left would have to be slowed to fill the scene
            if any(at - pad / 2 < c <= at + float(config.CUT_GUARD_SECONDS) for c in cuts):
                continue                        # it would open on the last moments of a shot again
            if was0 is not None and _shown_elsewhere(others, vid0, was0 + at, was0 + at + span):
                continue                        # another scene shows that footage (the clip chained after it)
            out = filters.trim_clip(path, at, dur - at)
            if not out:
                continue
            _carry_framing(path, out)           # still the framed clip the plan made: never into the library
            keep, again = judge(out, job, span)
            if keep:
                _vid, was = _source_point(scene, path)
                _put_cut(scene, out, filters._video_seconds(out) or (dur - at),
                         (was + at) if was is not None else None)
                record(scene, again, keep)
                scene["semanticMetadata"]["cutCheck"]["moved"] = round(at, 2)
                return True
            _remove(out)
    if v.get("opening") is not False or not work:
        return False
    vid, was = _source_point(scene, path)
    frames = list(v.get("frames") or [])
    if not vid or was is None or len(frames) < 2:
        return False
    shift = float(frames[1])                    # the middle frame: the judge saw it fit
    need = max(span + media.SEQ_SHOT_PAD, cover)
    from . import ledger
    if ledger.moment_used(vid, was + shift, was + shift + need):
        return False                            # an earlier video showed that moment
    if _shown_elsewhere(others, vid, was + shift, was + shift + span):
        return False                            # another scene of this video shows it (the clip chained after it)
    if not _can_judge():
        return False                            # a download no verdict could follow
    stop = time.time() + float(getattr(config, "FALLBACK_SCENE_SECONDS", 45.0) or 45.0)
    if until:
        if time.time() >= until:
            print(f"[hook] {scene.get('id')}: no time left to cut it again", flush=True)
            return False
        stop = min(stop, until)
    title = str((scene.get("media") or {}).get("attribution") or "")
    from . import ytdlp
    token = ytdlp.STOP.set((None, stop))        # no retry starts past it (the plan's deadline is off by now)
    try:
        got, _clean, _cuts = media.fetch_clean_clip(vid, work, was + shift, need, title)
    except Exception as e:  # noqa: BLE001 - the next step
        print(f"[hook] {scene.get('id')}: moving its start failed: {type(e).__name__}: {str(e)[:80]}", flush=True)
        got = ""
    finally:
        ytdlp.STOP.reset(token)
    if not got:
        return False
    secs = filters._video_seconds(got)
    if 0 < secs < cover - 0.05:
        _remove(got)
        return False
    keep, again = judge(got, job, span)
    if not keep:
        _remove(got)
        return False
    # A new download, raw: a vertical clip framed on its blurred copy as the plan frames its own
    # (shotcap._frame, where the style allows vertical clips) - else the renderer crops it to a strip.
    from . import shotcap
    shotcap._frame(got)
    _put_cut(scene, got, filters._video_seconds(got) or secs, was + shift)
    record(scene, again, keep)
    scene["semanticMetadata"]["cutCheck"]["moved"] = round(shift, 2)
    return True


def _shown_elsewhere(others: Sequence[Tuple[str, float, float]], vid: str, a: float, b: float) -> bool:
    """Another scene plays part of [a, b) seconds of YouTube video `vid` (more than a frame or so)."""
    return bool(vid) and any(v == vid and lo < b - 0.05 and a < hi - 0.05 for v, lo, hi in others or ())


def _played(scenes: List[dict], i: int, fps: int) -> List[Tuple[str, float, float]]:
    """(YouTube id, from, to) of the footage every scene but i plays, where its file or link says."""
    out = []
    for k, sc in enumerate(scenes):
        m = sc.get("media") or {}
        if k == i or m.get("type") != "video":
            continue
        vid, start = _source_point(sc, _local(m.get("url")) or str(m.get("url") or ""))
        if vid and start is not None:
            out.append((vid, float(start), float(start) + int(sc.get("durationInFrames") or 0) / fps))
    return out


def _carry_framing(src: str, dst: str) -> None:
    try:
        from . import upscale
        upscale.carry(src, dst)
    except Exception:  # noqa: BLE001 - a record only
        pass


def _can_judge() -> bool:
    """A verdict could still come: the check on, vision on and calls left."""
    from . import vision
    return enabled() and vision.enabled() and not spent()


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def unmark(doc: dict, scene: dict) -> int:
    """
    The marks vision placed on this scene's old picture (src/marks.py: an arrow,
    a circle, a box at a spot it found in that frame) go with it. Returns how many.
    """
    s0 = int(scene.get("startFrame") or 0)
    s1 = s0 + int(scene.get("durationInFrames") or 0)
    keep, gone = [], 0
    for ov in doc.get("overlays") or []:
        if isinstance(ov, dict) and ov.get("anchor"):
            a = int(ov.get("startFrame") or 0)
            b = a + int(ov.get("durationInFrames") or 0)
            if a < s1 and b > s0:
                gone += 1
                continue
        keep.append(ov)
    if gone:
        doc["overlays"] = keep
    return gone


def swap_runner_up(doc: dict, i: int, job: dict, span: float) -> bool:
    """
    A pick-a-shot runner-up on scene i - its own, then one of a shot beside it
    (shotcap.alternative_for: never one the video shows or its variety rules
    forbid, never one too short to cover the scene) - that passes the same
    check; HOOK_CUT_TRIES of them at most. True when one is on the scene.
    """
    from . import gapfill, shotcap
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    near = range(max(0, i - shotcap.DONOR_REACH), min(len(scenes), i + shotcap.DONOR_REACH + 1))
    turned: List[Tuple[int, dict]] = []         # a neighbour's runner-up this line turned down: it stays its choice
    try:
        for _ in range(max(0, int(getattr(config, "HOOK_CUT_TRIES", 2) or 0))):
            lists = {k: list((scenes[k].get("semanticMetadata") or {}).get("alternatives") or []) for k in near}
            used = gapfill.Used()
            for k, sc in enumerate(scenes):
                shot = gapfill.Shot.of_scene(sc, fps) if k != i else None
                if shot is not None:
                    used.add(k, shot)
            if not shotcap.alternative_for(doc, i, used):
                return False
            path = _local((s.get("media") or {}).get("url"))
            keep, verdict = judge(path, job, span) if path else (None, None)
            if keep is None:
                # No verdict (the calls spent, vision gone, every model failing): an unjudged runner-up
                # never takes the opening. It goes back to its choices; the caller keeps the clip as
                # the best available or leaves the line to the last resort.
                for k, was in lists.items():
                    sem = scenes[k].setdefault("semanticMetadata", {})
                    now = sem.get("alternatives") or []
                    gone = [a for a in was if not any(a is b for b in now)]
                    if gone:
                        sem["alternatives"] = list(now) + gone
                return False
            record(s, verdict, keep)
            if keep is False and not soft(verdict):
                for k, was in lists.items():    # turned down too: the next runner-up
                    if k == i:
                        continue
                    now = (scenes[k].get("semanticMetadata") or {}).get("alternatives") or []
                    turned += [(k, a) for a in was if not any(a is b for b in now)]
                continue
            s["reviewRequired"] = True
            s["reviewReason"] = ("Another approved shot: the first one was turned down at the start of the video "
                                 "(the hook check) - check it fits")
            return True
        return False
    finally:
        for k, alt in turned:
            sem = scenes[k].setdefault("semanticMetadata", {})
            sem["alternatives"] = list(sem.get("alternatives") or []) + [alt]


def clear(scene: dict, reason: str) -> None:
    """The scene's picture goes; the last resort covers the line (gapfill.hold_or_animate)."""
    scene["media"] = {"type": "color", "url": "", "source": "none"}
    sem = scene.setdefault("semanticMetadata", {})
    turned = {"why": reason, "assetId": sem.get("assetId") or "", "score": sem.get("relevanceScore"),
              "description": str(sem.get("contentDescription") or "")[:160]}
    for key in ("assetId", "sourceUrl", "moment", "cutCheck", "judgedBy", "shotCap", "contentDescription",
                "relevanceScore", "qualityScore", "specificity", "finalScore"):
        sem.pop(key, None)
    sem["hookCheck"] = {"turnedDown": turned}
    scene["reviewRequired"] = True
    scene["reviewReason"] = (f"The start of the video: its clip was turned down ({reason}) and nothing that "
                             "passed was found - use Find footage")


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #

def _plays(scenes: List[dict], i: int, fps: int) -> float:
    """Seconds scene i's clip is on screen, a crossfade into the next included (quality.scene_need)."""
    try:
        from . import quality
        return float(quality.scene_need(scenes, i, fps))
    except Exception:  # noqa: BLE001 - its own length, then
        return int(scenes[i].get("durationInFrames") or 0) / max(1, fps)


def _hook_shot(scene: dict) -> str:
    """
    The scene's clip or picture on this disk when it is one this check reads,
    else ''. A cold open's flash (HOOK_TEASER) too: it is the video's very
    first second - the first second of a later clip, judged against that
    clip's own line (gapfill.known_jobs).
    """
    m = scene.get("media") or {}
    if scene.get("animation") or m.get("type") not in ("video", "image"):
        return ""
    if is_presenter_scene(scene):
        return ""               # the AI presenter (src/presenter/hybrid.py): made and checked by its own step
    if is_ai_scene(scene):
        return ""               # an AI picture or clip made for its line (src/aifill.py): checked by its own step
    return _local(m.get("url"))


def _todo(scenes: List[dict], fps: int, known) -> Dict[int, tuple]:
    """
    {scene index: (file, job, span)} for every shot of the hook not yet
    checked on its own cut. `known`: the plan's lines by scene number
    (gapfill.known_jobs - after a cold open, not by the line's old place).
    """
    from . import gapfill
    out: Dict[int, tuple] = {}
    for i, s in enumerate(scenes):
        if int(s.get("startFrame") or 0) / fps >= float(config.HOOK_SECONDS):
            break
        path = _hook_shot(s)
        if not path or _checked(s):
            continue
        span = int(s.get("durationInFrames") or 0) / fps
        out[i] = (path, dict(gapfill.job_for(s, i, fps, known), hook=True, seconds=span), span)
    return out


def _prefetch(todo: Dict[int, tuple]) -> Dict[int, tuple]:
    """
    {scene index: (keep, verdict)}: the verdicts the pass is about to ask for,
    a few at once (each is a model call of several seconds) - never more than
    the calls this job's hook checks have left. {} for fewer than two.
    """
    room = left()
    keys = list(todo)[: (room if room is not None else len(todo))]
    if len(keys) < 2:
        return {}
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=min(PREFETCH_PARALLEL, len(keys)), thread_name_prefix="hook") as ex:
            return dict(zip(keys, ex.map(lambda k: judge(*todo[k]), keys)))
    except Exception as e:  # noqa: BLE001 - the pass asks for each, one at a time
        print(f"[hook] verdicts not fetched ahead: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return {}


def check(doc: dict, *, work: str = "", label: str = "the hook check") -> Dict[str, Any]:
    """
    Every clip and picture of the hook judged on its own cut (see the module
    docstring); the timeline is changed in place. Returns the report for
    doc.meta.hookCheck.
    """
    out: Dict[str, Any] = {"enabled": enabled(), "scenes": 0, "checked": 0, "kept": 0, "unjudged": 0,
                           "moved": 0, "swapped": 0, "keptUnderFloor": 0, "cleared": 0, "calls": 0,
                           "seconds": 0.0, "turnedDown": [], "lastResort": {}}
    if not out["enabled"] or not doc.get("scenes"):
        return out
    from . import gapfill, media, vision
    if not vision.enabled():
        out["visionOff"] = True                 # nothing can judge: the opening stays as the plan left it
        return out
    t0 = time.time()
    # The downloads a moved start needs keep to one box for the whole check (other_moments and the
    # ladder keep to their own): the plan's sourcing deadline is off by now.
    until = t0 + float(getattr(config, "FALLBACK_SECONDS", 180.0) or 180.0)
    calls0 = vision.calls_made()
    work = work or str(gapfill.CONTEXT.get("work") or "") or str(media._WORK.get("dir") or "")
    seen: set = set()
    for rnd in range(2):
        scenes = doc.get("scenes") or []
        fps = max(1, int(doc.get("fps") or 30))
        known = gapfill.known_jobs(doc)        # by scene number, a cold open's flashes counted
        todo = _todo(scenes, fps, known)
        ahead = _prefetch(todo)
        cleared: List[dict] = []
        for i, s in enumerate(scenes):
            if int(s.get("startFrame") or 0) / fps >= float(config.HOOK_SECONDS):
                break
            if i not in todo and not _hook_shot(s):
                continue
            if id(s) not in seen:
                seen.add(id(s))
                out["scenes"] += 1
            if i not in todo:
                continue                        # already checked on its own cut
            if i not in ahead and spent():
                out["budgetSpent"] = True
                break
            path, job, span = todo[i]
            m = s.get("media") or {}
            keep, verdict = ahead[i] if i in ahead else judge(path, job, span)
            out["checked"] += 1
            record(s, verdict, keep)
            if keep is None:
                out["unjudged"] += 1
                continue
            if keep:
                out["kept"] += 1
                continue
            reason = why(verdict)
            if len(out["turnedDown"]) < EXAMPLES:
                out["turnedDown"].append({"scene": str(s.get("id") or i), "why": reason,
                                          "score": verdict.get("score") if verdict else None,
                                          "opening": verdict.get("opening") if verdict else None})
            print(f"[hook] {s.get('id')}: turned down - {reason}", flush=True)
            if m.get("type") == "video" and move_start(s, path, job, span, verdict, work,
                                                       cover=_plays(scenes, i, fps), until=until,
                                                       others=_played(scenes, i, fps)):
                out["moved"] += 1
                unmark(doc, s)
                s["reviewRequired"] = True
                s["reviewReason"] = (f"The start of the video: its clip now starts later - the first cut was "
                                     f"turned down ({reason}) - check it fits")
                print(f"[hook] {s.get('id')}: its start moved and the new cut passed", flush=True)
                continue
            before = (copy.deepcopy(s.get("media")), copy.deepcopy(s.get("semanticMetadata")),
                      s.get("reviewRequired"), s.get("reviewReason"))
            # (A cold open's flash is a look at a later clip, not a line of its own: no runner-up.)
            if not s.get("teaser") and swap_runner_up(doc, i, job, span):
                out["swapped"] += 1
                unmark(doc, s)
                print(f"[hook] {s.get('id')}: a runner-up took its place", flush=True)
                continue
            # No runner-up passed: the scene is its own clip again (a runner-up tried may still sit on
            # it) - with the choices left after the tries.
            left_over = (s.get("semanticMetadata") or {}).get("alternatives")
            s["media"], s["semanticMetadata"], s["reviewRequired"], s["reviewReason"] = before
            if left_over is not None and isinstance(s.get("semanticMetadata"), dict):
                s["semanticMetadata"]["alternatives"] = left_over
            if soft(verdict):
                # Nothing better: the clip it had stays, flagged - the hook search's "best available".
                record(s, verdict, keep)
                s["reviewRequired"] = True
                s["reviewReason"] = (f"Best available at the start of the video: the hook check scored it "
                                     f"{float(verdict.get('score') or 0):.2f}, under the "
                                     f"{config.VISION_MIN_SCORE:.2f} floor - check it fits")
                out["keptUnderFloor"] += 1
                continue
            unmark(doc, s)
            clear(s, reason)
            cleared.append(s)
            out["cleared"] += 1
        if not cleared:
            break
        # The last resort for the lines whose clip went: the first time with fresh shots (runner-ups,
        # other moments, the ladder - each checked on the next round), then without fetching anything.
        fresh = rnd == 0 and bool(work)
        try:
            # Only the lines this round cleared: the text cards the plan left elsewhere had their ladder and
            # their last resort, and another pass over them would be time and model calls outside this cap.
            got = gapfill.hold_or_animate(doc, label=label, laddered=not fresh, fresh=fresh,
                                          search=fresh, work=work, only=cleared)
        except Exception as e:  # noqa: BLE001 - a text card is what is left
            print(f"[hook] last resort failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            got = {}
        for k, n in (got or {}).items():
            out["lastResort"][k] = int(out["lastResort"].get(k, 0)) + int(n or 0)
    out["calls"] = vision.calls_made() - calls0
    out["seconds"] = round(time.time() - t0, 1)
    if out["checked"]:
        print(f"[hook] {label}: {out['scenes']} hook shot(s), {out['checked']} judged on their own cut "
              f"({out['calls']} vision call(s)): {out['kept']} kept, {out['moved']} start(s) moved, "
              f"{out['swapped']} runner-up(s), {out['keptUnderFloor']} best available, {out['cleared']} "
              f"covered another way, {out['unjudged']} unjudged", flush=True)
    return out
