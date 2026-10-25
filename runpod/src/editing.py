"""
Editing v3 (2026-10-25): the finishing pass an editor makes once the shots, graphics and grade are placed.

Measured against top faceless channels in three niches (SunnyV2, MagnatesMedia, LEMMiNO) and the owner's own
references (docs/editing-v3/audit.md): something new lands on the spoken word every 2-5 s, the hook is denser than
the body, nothing sits still for long, the type is one system, texture is a whole-video grade. Our videos held
stills 15-18 s (a third of the Mount Rainier video sat in shots over 10 s), had no emphasis on the words that matter,
drew some figures twice, repeated the same caption four times and wobbled the hue of random modern clips.

One pass over the finished document, no network, no AI call (cost 0); everything it writes is plain timeline data
the renderer already draws (the editor's keyframes, trimStart, splitFrom), so the web editor shows and changes it:

* split_holds  (EDIT_V3_SPLIT_HOLDS, EDIT_V3_HOOK_PACE): a still held past the limit becomes 2-3 shots of the same
  photograph cut on word boundaries (a pause or a sentence end first), each later one a detail framing aimed at the
  subject - the documentary editor's "several shots from one photo". A long clip continues forward in its own file
  (a chain cut, never a crop) when the file has the footage. The opening HOOK_SECONDS uses a lower limit.
* punches     (EDIT_V3_PUNCHES): a punch-in on the strongest emphasis word of a line (a figure, a superlative, a
  turn), eased in fast (expoOut) and held to the cut, with motion blur - never near a graphic's entrance, never on a
  clip the style keeps uncropped, at least PUNCH_GAP s apart (less in the hook).
* interrupts  (EDIT_V3_INTERRUPTS): no stretch longer than INTERRUPT_SECONDS without a new event (a graphic, a
  transition, a change of picture type, a punch): the best word in a quiet stretch gets a punch.
* punch sound (EDIT_V3_PUNCH_SOUND): a soft whoosh under each punch, levelled against the voice like every sound
  (the SFX master, the owner's 0.4, scales it in the renderer).
* hygiene     (EDIT_V3_HYGIENE): a graphic over a full-screen graphic scene goes (the same figure drawn twice); a
  caption that repeats one shown in the last REPEAT_SECONDS goes, with its own sound.
* clean effects (EDIT_V3_CLEAN_EFFECTS): no colour-shift, light leak, flicker or dust on a clip unless the scene is
  treated as film / vintage / archival.

EDITING_V3=0 (env or job config) or a job's "editing_v3": false: the document is left exactly as it was.
apply() never raises: any error leaves the document as it was and is reported in meta.editingV3.
"""
from __future__ import annotations

import copy
import math
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from . import config

VERSION = 1

# ---------------------------------------------------------------------------------------------------------------
# Settings (config.py holds the flags; these are the measured numbers behind them)
# ---------------------------------------------------------------------------------------------------------------
HOOK_SECONDS = 30.0             # the references' first 30 s run at 18-20 changes / min against 11-15 after
HOLD_LIMIT_HOOK = 5.0           # a shot in the hook longer than this is split
HOLD_LIMIT_MIN = 7.5            # ... and in the body (or the style's SHOT_MAX_SECONDS + 0.5, whichever is longer)
PIECE_MIN = 2.2                 # no piece of a split shot shorter than this
DETAIL_SCALE = 1.2              # a detail framing of a still (the renderer's cover fit is the 1.0)
DETAIL_SCALE_SMALL = 1.12       # ... of a still whose file is small
CLIP_SKIP = 0.8                 # a chained clip piece jumps this far forward in its file
PUNCH_SCALE = 1.08              # the owner's Premiere rules: same-shot punch 12 %, emphasis zooms held, no boomerang
PUNCH_SCALE_HOOK = 1.1
PUNCH_IN = 0.28                 # seconds to land the punch (expoOut)
PUNCH_LEAD = 0.04               # the punch starts this far before its word
PUNCH_GAP = 10.0                # fewest seconds between two punches in the body ...
PUNCH_GAP_HOOK = 4.0            # ... and in the hook
PUNCH_MIN_SCORE = 3.0           # the first pass punches only strong words; interrupts take weaker ones
PUNCH_MAX_PER_MIN = 2.5
PUNCH_EDGE = 0.7                # never in a shot's first or last 0.7 s (it would read as a cut)
GRAPHIC_CLEAR = 1.5             # never within this of a graphic's entrance (the graphic is the emphasis there)
INTERRUPT_SECONDS = 30.0        # the longest stretch with nothing new (references: 2-8 s; owner's 20-40 s rule)
REPEAT_SECONDS = 240.0          # a caption repeating one shown this recently is dropped
REPEAT_SIMILARITY = 0.6
PUNCH_SOUND = "zoom-in-whoosh"
PUNCH_SOUND_ALT = "whoosh-soft-v2"
PUNCH_SOUND_UNDER_DB = 13.0     # softer than any transition sound (theirs 9.5-12 dB under the voice)
TEXTURE_EFFECTS = {"color-shift", "light-leaks", "film-flicker", "dust"}
FILM_TREATMENTS = {"film", "vintage", "archival"}
KEEP_OVER_SCENE = {"LIB_SRC_TAG"}   # the source tag is settled by sources.settle, never over a graphic anyway
STILL_MOTIONS = ["push-offcenter", "reveal-left", "drift-diagonal", "pull-back", "parallax", "zoom-in",
                 "rotate-settle", "reveal-right", "pan-left", "push-rotate", "zoom-out", "pan-right"]

# ---------------------------------------------------------------------------------------------------------------
# Emphasis: the words an editor hits (any niche)
# ---------------------------------------------------------------------------------------------------------------
_NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                 "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
                 "hundreds", "thousand", "thousands", "million", "millions", "billion", "billions", "trillion",
                 "trillions", "dozens", "half"}
_SUPERLATIVE = {"biggest", "largest", "highest", "deepest", "worst", "best", "most", "least", "first", "last",
                "only", "never", "ever", "forever", "every", "record", "nobody", "nothing", "none", "entire",
                "fastest", "richest", "oldest", "youngest", "deadliest", "strongest", "longest", "tallest",
                "smallest", "greatest", "single", "all-time", "unprecedented", "everything", "everyone"}
_INTENSIFIER = {"massive", "huge", "enormous", "giant", "gigantic", "staggering", "shocking", "insane",
                "incredible", "catastrophic", "devastating", "deadly", "brutal", "terrifying", "impossible",
                "historic", "explosive", "collapse", "collapsed", "exploded", "destroyed", "vanished", "crashed",
                "bankrupt", "fired", "banned", "arrested", "killed", "died", "dead", "illegal", "fraud", "scam"}
_REVEAL = {"secret", "secretly", "truth", "hidden", "discovered", "revealed", "finally", "suddenly", "mystery",
           "warning", "nobody", "lie", "lied", "lies", "betrayed", "exposed", "leaked", "proof", "evidence",
           "changed", "wrong", "real", "actually"}
_PIVOT = {"but", "yet", "instead", "until", "except", "however"}
_EST_NOT = {"interest", "forest", "honest", "west", "test", "rest", "nest", "chest", "guest", "protest", "request",
            "suggest", "harvest", "modest", "contest", "manifest", "earnest", "invest", "arrest", "digest", "latest",
            "midwest", "southwest", "northwest", "pest", "quest", "crest", "conquest", "budapest", "everest"}
_STOP = {"the", "and", "for", "that", "with", "this", "from", "they", "were", "have", "has", "had", "was", "are",
         "its", "his", "her", "their", "there", "then", "than", "into", "onto", "about", "which", "what", "when"}
_SENT_END = re.compile(r"[.!?…][\"'”’)\]]*$")
_CLAUSE_END = re.compile(r"[,;:—–-][\"'”’)\]]*$")
_DIGIT = re.compile(r"\d")


def _norm(text: str) -> str:
    return re.sub(r"[^\w\-]", "", str(text or "").replace("’", "'").lower().split("'")[0])


def word_score(words: List[dict], k: int) -> float:
    """How strongly an editor would hit word k (0 = never)."""
    w = words[k]
    raw = str(w.get("text") or "")
    n = _norm(raw)
    if not n:
        return 0.0
    score = 0.0
    if _DIGIT.search(raw):
        # "1,000" / "$5" / "40%"; a lone small digit ("1", "2") is weaker
        digits = re.sub(r"\D", "", raw)
        score = 3.5 if ("$" in raw or "%" in raw or len(digits) >= 3) else 2.5
    elif n in _NUMBER_WORDS:
        score = 3.0
    elif n in _SUPERLATIVE:
        score = 3.0
    elif n.endswith("est") and len(n) > 5 and n not in _EST_NOT:
        score = 2.5
    elif n in _INTENSIFIER:
        score = 2.5
    elif n in _REVEAL:
        score = 2.0
    elif n in _PIVOT and (k == 0 or _SENT_END.search(str(words[k - 1].get("text") or ""))):
        score = 2.0
    elif n in _STOP or len(n) < 3:
        return 0.0
    if score <= 0:
        return 0.0
    # A word that ends a sentence or is followed by a breath lands harder.
    nxt = words[k + 1] if k + 1 < len(words) else None
    gap = (float(nxt.get("start", 0)) - float(w.get("end", 0))) if nxt else 1.0
    if gap >= 0.3 or _SENT_END.search(raw):
        score += 0.5
    if raw.rstrip("\"'”’").endswith("!"):
        score += 0.5
    return score


# ---------------------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------------------
def _f(v, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _flag(name: str, cfg: Optional[dict], default: bool = True) -> bool:
    if cfg and name in cfg:
        v = cfg[name]
        return v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes", "on"}
    return bool(getattr(config, name, default))


def enabled(inp: Optional[dict] = None) -> bool:
    """The pass runs: EDITING_V3 (env / job config) and the job's own "editing_v3" (default on)."""
    inp = inp or {}
    if "editing_v3" in inp and inp.get("editing_v3") is not None:
        v = inp.get("editing_v3")
        return v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes", "on"}
    return _flag("EDITING_V3", inp.get("config") if isinstance(inp.get("config"), dict) else None)


def _is_presenter(scene: dict) -> bool:
    try:
        from .presenter import is_presenter_scene
        return bool(is_presenter_scene(scene))
    except Exception:  # noqa: BLE001
        return False


def _mtype(scene: dict) -> str:
    return str((scene.get("media") or {}).get("type") or "")


def _span(scene: dict, fps: int) -> Tuple[float, float]:
    a = int(scene.get("startFrame") or 0) / fps
    return a, a + int(scene.get("durationInFrames") or 0) / fps


def _overlay_span(ov: dict, fps: int) -> Tuple[float, float]:
    a = int(_f(ov.get("startFrame"))) / fps
    return a, a + max(0, int(_f(ov.get("durationInFrames")))) / fps


def _overlay_text(ov: dict) -> str:
    parts = []
    for k in ("text", "label", "subtitle", "value", "suffix"):
        v = ov.get(k)
        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
            parts.append(str(v))
    props = ov.get("props")
    if isinstance(props, dict):
        for k in ("text", "label", "subtitle", "value"):
            v = props.get(k)
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                parts.append(str(v))
    return " ".join(parts)


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower()) if t not in _STOP and len(t) > 1}


def shot_stats(doc: dict) -> dict:
    """The numbers the audit compares: shot lengths, long holds, events and the longest quiet stretch."""
    fps = max(1, int(doc.get("fps") or 30))
    scenes = [s for s in doc.get("scenes") or [] if isinstance(s, dict)]
    durs = [int(s.get("durationInFrames") or 0) / fps for s in scenes if int(s.get("durationInFrames") or 0) > 0]
    total = sum(durs) or 1.0
    if not durs:
        return {"shots": 0}
    xs = sorted(durs)
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
    stills_over8 = sum(int(s.get("durationInFrames") or 0) / fps for s in scenes
                       if _mtype(s) == "image" and int(s.get("durationInFrames") or 0) / fps > 8)
    hook = [d for s, d in zip(scenes, durs) if int(s.get("startFrame") or 0) / fps < HOOK_SECONDS]
    ev = events(doc)
    lo, hi = extent(doc)
    quiet = longest_quiet(ev, lo, hi)
    return {"shots": len(durs), "perMinute": round(len(durs) * 60 / total, 1),
            "p10": round(q(0.1), 2), "median": round(statistics.median(xs), 2), "p90": round(q(0.9), 2),
            "max": round(xs[-1], 2), "over8Share": round(sum(d for d in durs if d > 8) / total, 3),
            "over10Share": round(sum(d for d in durs if d > 10) / total, 3),
            "under2_5Share": round(sum(1 for d in durs if d < 2.5) / len(durs), 3),
            "stillsOver8Seconds": round(stills_over8, 1), "hookShots": len(hook),
            "events": len(ev), "eventsPerMinute": round(len(ev) * 60 / total, 1),
            "longestQuiet": round(quiet, 1),
            "punches": sum(1 for s in scenes if (s.get("semanticMetadata") or {}).get("punch"))}


def events(doc: dict) -> List[float]:
    """Seconds at which something new happens on screen beyond the base cut rhythm: a graphic enters, a transition
    other than the style's plain dissolve, the picture type changes (clip / still / graphic), a punch lands."""
    fps = max(1, int(doc.get("fps") or 30))
    out = []
    for ov in doc.get("overlays") or []:
        if isinstance(ov, dict) and ov.get("template") not in KEEP_OVER_SCENE:
            out.append(_overlay_span(ov, fps)[0])
    prev = None
    for s in doc.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        a, _ = _span(s, fps)
        t = str(s.get("transition") or "none")
        if t not in ("none", "crossfade", "") and not s.get("splitFrom"):
            out.append(a)
        mt = _mtype(s)
        if prev is not None and mt != prev:
            out.append(a)
        prev = mt
        p = (s.get("semanticMetadata") or {}).get("punch")
        if isinstance(p, dict):
            out.append(a + _f(p.get("at")))
    return sorted(out)


def extent(doc: dict) -> Tuple[float, float]:
    """The first scene's start and the last one's end (seconds): a slice of a timeline need not start at 0."""
    fps = max(1, int(doc.get("fps") or 30))
    spans = [_span(s, fps) for s in doc.get("scenes") or [] if isinstance(s, dict)]
    if not spans:
        return 0.0, 0.0
    return min(a for a, _ in spans), max(b for _, b in spans)


def quiet_gaps(ev: List[float], lo: float, hi: float) -> List[Tuple[float, float]]:
    pts = [lo] + [e for e in ev if lo <= e <= hi] + [hi]
    return list(zip(pts, pts[1:]))


def longest_quiet(ev: List[float], lo: float, hi: float) -> float:
    return max((b - a for a, b in quiet_gaps(ev, lo, hi)), default=hi - lo)


# ---------------------------------------------------------------------------------------------------------------
# Hygiene: no figure drawn twice, no caption repeated
# ---------------------------------------------------------------------------------------------------------------
def hygiene(doc: dict) -> dict:
    fps = max(1, int(doc.get("fps") or 30))
    overlays = doc.get("overlays")
    if not isinstance(overlays, list) or not overlays:
        return {"overScene": 0, "repeated": 0, "sounds": 0}
    full = [_span(s, fps) for s in doc.get("scenes") or []
            if isinstance(s, dict) and _mtype(s) == "animation"]
    keep, over_scene, repeated, dropped_starts = [], 0, 0, []
    shown: List[Tuple[float, set]] = []
    for ov in sorted(overlays, key=lambda o: _f(o.get("startFrame")) if isinstance(o, dict) else 0):
        if not isinstance(ov, dict):
            keep.append(ov)
            continue
        a, b = _overlay_span(ov, fps)
        if ov.get("template") in KEEP_OVER_SCENE or b <= a:
            keep.append(ov)
            continue
        # Over a full-screen graphic scene for most of its time: the scene already is the graphic.
        cover = sum(max(0.0, min(b, e) - max(a, s)) for s, e in full)
        if cover >= 0.4 * (b - a):
            over_scene += 1
            dropped_starts.append(int(_f(ov.get("startFrame"))))
            continue
        toks = _tokens(_overlay_text(ov))
        if len(toks) >= 2:
            dup = False
            for t0, prev in shown:
                if a - t0 <= REPEAT_SECONDS and prev and len(toks & prev) / max(1, len(toks | prev)) >= REPEAT_SIMILARITY:
                    dup = True
                    break
            if dup:
                repeated += 1
                dropped_starts.append(int(_f(ov.get("startFrame"))))
                continue
            shown.append((a, toks))
        keep.append(ov)
    sounds = 0
    if dropped_starts:
        # The original order is kept for the overlays that stay (nothing else reorders them).
        kept_ids = {id(o) for o in keep}
        overlays[:] = [o for o in overlays if id(o) in kept_ids]
        # A dropped graphic's own planned sound goes with it (the Smart Editor's rows sit on its first frame).
        rows = doc.get("sfx")
        if isinstance(rows, list):
            before = len(rows)
            rows[:] = [r for r in rows if not (isinstance(r, dict) and r.get("kind") in ("smart", "overlay")
                                               and any(abs(int(_f(r.get("startFrame"))) - s) <= 3
                                                       for s in dropped_starts))]
            sounds = before - len(rows)
    return {"overScene": over_scene, "repeated": repeated, "sounds": sounds}


# ---------------------------------------------------------------------------------------------------------------
# Clean effects
# ---------------------------------------------------------------------------------------------------------------
def clean_effects(doc: dict) -> int:
    n = 0
    for s in doc.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        if s.get("effect") in TEXTURE_EFFECTS and str(s.get("treatment") or "none") not in FILM_TREATMENTS:
            s["effect"] = "ken-burns" if _mtype(s) == "image" else "none"
            n += 1
    return n


# ---------------------------------------------------------------------------------------------------------------
# Split long holds
# ---------------------------------------------------------------------------------------------------------------
def _limits(cfg: Optional[dict]) -> Tuple[float, float, float]:
    shot_max = _f((cfg or {}).get("SHOT_MAX_SECONDS", getattr(config, "SHOT_MAX_SECONDS", 7.0)), 7.0)
    target = _f((cfg or {}).get("TARGET_SCENE_SECONDS", getattr(config, "TARGET_SCENE_SECONDS", 7.0)), 7.0)
    body = max(HOLD_LIMIT_MIN, (shot_max + 0.5) if shot_max > 0 else HOLD_LIMIT_MIN)
    piece = max(3.2, min(5.0, 0.75 * target))
    return body, HOLD_LIMIT_HOOK, piece


def _cut_points(words: List[dict], a: float, b: float, n: int) -> List[float]:
    """n-1 cut times inside (a, b), each just before a word, preferring sentence ends and breaths, near even thirds."""
    cands = []
    for k in range(1, len(words)):
        w0, w1 = words[k - 1], words[k]
        t = _f(w1.get("start")) - 0.06
        if t - a < PIECE_MIN or b - t < PIECE_MIN:
            continue
        gap = _f(w1.get("start")) - _f(w0.get("end"))
        bonus = 0.0
        raw = str(w0.get("text") or "")
        if _SENT_END.search(raw):
            bonus = 1.2
        elif _CLAUSE_END.search(raw):
            bonus = 0.6
        bonus += min(0.8, max(0.0, gap) * 2.0)
        cands.append((t, bonus))
    if not cands:
        return []
    cuts: List[float] = []
    lo = a
    for j in range(1, n):
        ideal = a + (b - a) * j / n
        best, best_s = None, -1e9
        for t, bonus in cands:
            if t - lo < PIECE_MIN or b - t < PIECE_MIN * (n - j):
                continue
            s = bonus - abs(t - ideal) / max(1.0, (b - a) / n) * 2.0
            if s > best_s:
                best, best_s = t, s
        if best is None:
            break
        cuts.append(best)
        lo = best
    return cuts


def _detail_anchor(scene: dict, k: int) -> Tuple[float, float]:
    """Where a detail framing of a still aims (anchor shares, 0 = centre): the planned subject, else a little off
    centre, alternating sides so two details of one photo never frame alike."""
    m = scene.get("media") or {}
    box = None
    rf = m.get("reframe") if isinstance(m.get("reframe"), dict) else None
    if rf and isinstance(rf.get("subject"), dict):
        box = rf.get("subject")
    elif isinstance((m.get("focus") or {}).get("box"), dict) and _f((m.get("focus") or {}).get("confidence"), 0) >= 0.5:
        box = (m.get("focus") or {}).get("box")
    if box:
        cx = _f(box.get("x")) + _f(box.get("w")) / 2
        cy = _f(box.get("y")) + _f(box.get("h")) / 2
        return max(-0.4, min(0.4, cx - 0.5)), max(-0.4, min(0.4, cy - 0.5))
    side = -0.16 if k % 2 else 0.16
    return side, -0.06


def _split_scene(scene: dict, cuts: List[float], fps: int, crop_ok: bool) -> Optional[List[dict]]:
    a, b = _span(scene, fps)
    bounds = [a] + cuts + [b]
    m = scene.get("media") or {}
    still = _mtype(scene) == "image"
    if not still:
        # A chain inside the clip's own file: piece k plays later footage, never a crop. Only when the file holds it.
        clip = _f(m.get("clipSeconds"))
        trim = _f(m.get("trimStart"))
        need = sum(bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)) + CLIP_SKIP * (len(bounds) - 2)
        if clip <= 0 or trim + need > clip + 0.05 or scene.get("speed") or scene.get("speedRamp"):
            return None
    pieces = []
    words = [w for w in scene.get("words") or [] if isinstance(w, dict)]
    base_id = str(scene.get("id") or "s")
    offset = _f(m.get("trimStart"))
    prev_id = base_id
    motion0 = str(scene.get("motion") or "none")
    last = len(bounds) - 2
    start0 = int(scene["startFrame"])
    end0 = start0 + int(scene["durationInFrames"])
    for i in range(len(bounds) - 1):
        s0, s1 = bounds[i], bounds[i + 1]
        f0 = start0 if i == 0 else int(round(s0 * fps))
        f1 = end0 if i == last else int(round(s1 * fps))
        if f1 - f0 < int(PIECE_MIN * fps * 0.9):
            return None
        p = copy.deepcopy(scene)
        p["startFrame"] = f0
        p["durationInFrames"] = f1 - f0
        if i == 0:
            ws = [w for w in words if _f(w.get("start")) < s1]
        elif i == last:
            ws = [w for w in words if _f(w.get("start")) >= s0]
        else:
            ws = [w for w in words if s0 <= _f(w.get("start")) < s1]
        p["words"] = copy.deepcopy(ws)
        if words:
            p["text"] = " ".join(str(w.get("text") or "") for w in ws).strip()
        if i:
            p["id"] = f"{base_id}-e{i}"
            p["splitFrom"] = prev_id
            p["transition"] = "none"
            p.pop("transitionGain", None)
            p.pop("reviewRequired", None)
            p.pop("reviewReason", None)
            sem = dict(p.get("semanticMetadata") or {})
            sem["editSplit"] = {"from": base_id, "piece": i}
            sem.pop("punch", None)
            p["semanticMetadata"] = sem
            pm = p.setdefault("media", {})
            if still:
                ax, ay = _detail_anchor(scene, i)
                small = bool(m.get("upscaled")) or (0 < _f(m.get("width"), 0) < 1600)
                sc = DETAIL_SCALE_SMALL if small else DETAIL_SCALE
                p["keyframes"] = {"scale": [{"t": 0, "v": sc}], "anchorX": [{"t": 0, "v": round(ax, 3)}],
                                  "anchorY": [{"t": 0, "v": round(ay, 3)}]}
                # A different hand move from the piece before (never the same move twice running).
                try:
                    j = STILL_MOTIONS.index(motion0)
                except ValueError:
                    j = -1
                if motion0 != "none":
                    p["motion"] = STILL_MOTIONS[(j + 1 + 2 * i) % len(STILL_MOTIONS)]
                # A planned slow move belongs to the first shot only.
                if isinstance(pm.get("reframe"), dict) and "from" in pm["reframe"]:
                    pm.pop("reframe", None)
            else:
                offset += (bounds[i] - bounds[i - 1]) + CLIP_SKIP
                pm["trimStart"] = round(offset, 3)
                if isinstance(pm.get("reframe"), dict) and "from" in pm["reframe"]:
                    pm.pop("reframe", None)
            prev_id = p["id"]
        pieces.append(p)
    return pieces


def split_holds(doc: dict, cfg: Optional[dict], hook_pace: bool, body: bool) -> dict:
    fps = max(1, int(doc.get("fps") or 30))
    scenes = doc.get("scenes")
    if not isinstance(scenes, list):
        return {"split": 0, "pieces": 0}
    body_limit, hook_limit, piece = _limits(cfg)
    still_motion = str((cfg or {}).get("STILL_MOTION", getattr(config, "STILL_MOTION", "")) or "").lower()
    crop_ok = _flag("REFRAME_CLIPS", cfg, True)
    out, split, added, refused = [], 0, 0, 0
    for s in scenes:
        if not isinstance(s, dict):
            out.append(s)
            continue
        a, b = _span(s, fps)
        du = b - a
        mt = _mtype(s)
        hook = a < HOOK_SECONDS
        limit = hook_limit if (hook and hook_pace) else body_limit
        ok = (mt in ("image", "video") and du > limit and (body or (hook and hook_pace))
              and str(s.get("frame") or "full") == "full" and not s.get("keyframes") and not s.get("splitFrom")
              and not _is_presenter(s) and not (mt == "image" and still_motion == "none"))
        if not ok:
            out.append(s)
            continue
        n = max(2, int(round(du / (min(piece, limit) if hook else piece))))
        n = min(n, max(2, int(du // PIECE_MIN)), 4)
        cuts = _cut_points([w for w in s.get("words") or [] if isinstance(w, dict)], a, b, n)
        pieces = _split_scene(s, cuts, fps, crop_ok) if cuts else None
        if not pieces:
            refused += 1
            out.append(s)
            continue
        split += 1
        added += len(pieces) - 1
        out.extend(pieces)
    scenes[:] = out
    return {"split": split, "pieces": added, "refused": refused, "limit": round(body_limit, 2),
            "hookLimit": hook_limit if hook_pace else None}


# ---------------------------------------------------------------------------------------------------------------
# Punches and interrupts
# ---------------------------------------------------------------------------------------------------------------
def _punchable(s: dict, crop_ok: bool) -> bool:
    if not isinstance(s, dict) or s.get("keyframes") or str(s.get("frame") or "full") != "full" or _is_presenter(s):
        return False
    m = s.get("media") or {}
    mt = _mtype(s)
    if mt == "image":
        return True
    if mt != "video" or not crop_ok:
        return False
    focus = m.get("focus") or {}
    if focus.get("overlay"):
        return False                       # burned-in lettering / a station logo: never cropped
    if isinstance(m.get("reframe"), dict) and "from" in m["reframe"]:
        return False                       # a planned slow move: a second move would fight it
    if isinstance(s.get("reframe"), (dict, str)) and s.get("reframe") not in ("auto",):
        return False
    return True


def _candidates(doc: dict, crop_ok: bool) -> List[Tuple[float, float, int, float]]:
    """(score, time, scene index, offset into the scene) for every word a punch could land on."""
    fps = max(1, int(doc.get("fps") or 30))
    out = []
    for i, s in enumerate(doc.get("scenes") or []):
        if not _punchable(s, crop_ok):
            continue
        a, b = _span(s, fps)
        ws = [w for w in s.get("words") or [] if isinstance(w, dict)]
        for k in range(len(ws)):
            sc = word_score(ws, k)
            if sc <= 0:
                continue
            t = _f(ws[k].get("start")) - PUNCH_LEAD
            if t - a < PUNCH_EDGE or b - t < PUNCH_EDGE + PUNCH_IN:
                continue
            out.append((sc, t, i, t - a))
    return out


_PUNCH_VARY = (0.0, 0.02, -0.01)     # a hand-made feel: never three identical punches in a row


def _place_punch(s: dict, at: float, scale: float, word: str, why: str, n: int = 0) -> None:
    scale = scale + _PUNCH_VARY[n % len(_PUNCH_VARY)]
    kf = {"scale": [{"t": round(at, 3), "v": 1.0},
                    {"t": round(at + PUNCH_IN, 3), "v": round(scale, 3), "e": "expoOut"}]}
    m = s.get("media") or {}
    rf = m.get("reframe") if isinstance(m.get("reframe"), dict) else None
    box = rf.get("subject") if rf and isinstance(rf.get("subject"), dict) else None
    if box:
        # Into the subject (a still's planned subject box, frame shares), never off it.
        kf["anchorX"] = [{"t": 0, "v": round(max(-0.35, min(0.35, _f(box.get("x")) + _f(box.get("w")) / 2 - 0.5)), 3)}]
        kf["anchorY"] = [{"t": 0, "v": round(max(-0.35, min(0.35, _f(box.get("y")) + _f(box.get("h")) / 2 - 0.5)), 3)}]
    else:
        kf["anchorY"] = [{"t": 0, "v": -0.06}]     # a touch above centre, where the subject of most frames sits
    s["keyframes"] = kf
    s["motionBlur"] = 0.5
    sem = dict(s.get("semanticMetadata") or {})
    sem["punch"] = {"at": round(at, 3), "scale": round(scale, 3), "word": word[:40], "why": why}
    s["semanticMetadata"] = sem


def punches(doc: dict, cfg: Optional[dict], base: bool, interrupts: bool) -> dict:
    fps = max(1, int(doc.get("fps") or 30))
    scenes = doc.get("scenes") or []
    crop_ok = _flag("REFRAME_CLIPS", cfg, True)
    lo, hi = extent(doc)
    total = hi - lo
    if total <= 0:
        return {"punches": 0, "interrupts": 0}
    graphic_starts = [_overlay_span(ov, fps)[0] for ov in doc.get("overlays") or [] if isinstance(ov, dict)]
    cands = _candidates(doc, crop_ok)
    cap = max(1, int(PUNCH_MAX_PER_MIN * total / 60.0))
    placed: List[float] = []
    used_scenes = set()

    def free(t: float, i: int, gap: float) -> bool:
        if i in used_scenes:
            return False
        if any(abs(t - g) < GRAPHIC_CLEAR for g in graphic_starts):
            return False
        return all(abs(t - p) >= gap for p in placed)

    def word_at(i: int, t: float) -> str:
        for w in scenes[i].get("words") or []:
            if abs(_f(w.get("start")) - PUNCH_LEAD - t) < 1e-6:
                return str(w.get("text") or "")
        return ""

    n_base = n_int = 0
    if base:
        for sc, t, i, off in sorted(cands, key=lambda c: (-c[0], c[1])):
            if len(placed) >= cap:
                break
            hook = t < HOOK_SECONDS
            if sc < (PUNCH_MIN_SCORE - (0.5 if hook else 0.0)):
                continue
            if not free(t, i, PUNCH_GAP_HOOK if hook else PUNCH_GAP):
                continue
            _place_punch(scenes[i], off, PUNCH_SCALE_HOOK if hook else PUNCH_SCALE, word_at(i, t),
                         "hook" if hook else "emphasis", len(placed))
            placed.append(t)
            used_scenes.add(i)
            n_base += 1
    if interrupts:
        for _ in range(200):
            if len(placed) >= cap:
                break
            ev = events(doc)
            gaps = sorted(((b - a, a, b) for a, b in quiet_gaps(ev, lo, hi) if b - a > INTERRUPT_SECONDS), reverse=True)
            done = False
            for _, a, b in gaps:
                inside = [c for c in cands if a + 6.0 <= c[1] <= b - 6.0 and free(c[1], c[2], 6.0)]
                if not inside:
                    continue
                mid = (a + b) / 2
                sc, t, i, off = max(inside, key=lambda c: (c[0] - abs(c[1] - mid) / 30.0))
                _place_punch(scenes[i], off, PUNCH_SCALE, word_at(i, t), "interrupt", len(placed))
                placed.append(t)
                used_scenes.add(i)
                n_int += 1
                done = True
                break
            if not done:
                break
    return {"punches": n_base, "interrupts": n_int}


def punch_sounds(doc: dict) -> int:
    """A soft whoosh under each punch: its loudest moment on the punch's landing, PUNCH_SOUND_UNDER_DB under the voice,
    never another sound within a second (a graphic's own sound wins)."""
    try:
        from . import sfxplan, templates
        from .timeline import sfx_meta
    except Exception:  # noqa: BLE001
        return 0
    fps = max(1, int(doc.get("fps") or 30))
    have = templates.sfx_files()
    name = PUNCH_SOUND if (not have or PUNCH_SOUND in have) else (PUNCH_SOUND_ALT if PUNCH_SOUND_ALT in have else "")
    if not name:
        return 0
    meta = sfx_meta().get(name) or {"duration": 0.6, "peak": 0.3}
    voice = (doc.get("meta") or {}).get("voiceLufs")
    under = max(PUNCH_SOUND_UNDER_DB, sfxplan.ceiling_db(name))
    vol = round(min(sfxplan.cap(voice, name), sfxplan.gain(under, voice, name)), 3)
    if vol <= 0.005:
        return 0
    rows = doc.setdefault("sfx", [])
    busy = [int(_f(r.get("startFrame"))) for r in rows if isinstance(r, dict)]
    busy += [int(_f(ov.get("startFrame"))) for ov in doc.get("overlays") or [] if isinstance(ov, dict)]
    near = fps
    n = 0
    dur = max(1, int(math.ceil(_f(meta.get("duration"), 0.6) * fps)))
    for s in doc.get("scenes") or []:
        p = (s.get("semanticMetadata") or {}).get("punch") if isinstance(s, dict) else None
        if not isinstance(p, dict):
            continue
        land = int(s.get("startFrame") or 0) + int(round((_f(p.get("at")) + PUNCH_IN * 0.6) * fps))
        start = land - int(round(_f(meta.get("peak"), 0.3) * fps))
        if start < 0 or any(abs(b - start) <= near or abs(b - land) <= near for b in busy):
            continue
        rows.append({"kind": "punch", "name": name, "startFrame": start, "durationFrames": dur, "volume": vol})
        busy.append(start)
        n += 1
    return n


# ---------------------------------------------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------------------------------------------
def apply(doc: dict, inp: Optional[dict] = None) -> dict:
    """Run every enabled step on `doc` in place; returns the report (also stored in doc.meta.editingV3)."""
    inp = inp or {}
    cfg = inp.get("config") if isinstance(inp.get("config"), dict) else None
    if not isinstance(doc, dict) or not enabled(inp):
        return {"on": False}
    report: Dict[str, Any] = {"on": True, "version": VERSION}
    snapshot = copy.deepcopy({k: doc.get(k) for k in ("scenes", "overlays", "sfx")})
    try:
        report["before"] = shot_stats(doc)
        flags = {name: _flag(name, cfg) for name in ("EDIT_V3_HYGIENE", "EDIT_V3_CLEAN_EFFECTS", "EDIT_V3_SPLIT_HOLDS",
                                                     "EDIT_V3_HOOK_PACE", "EDIT_V3_PUNCHES", "EDIT_V3_INTERRUPTS",
                                                     "EDIT_V3_PUNCH_SOUND")}
        report["flags"] = flags
        if flags["EDIT_V3_HYGIENE"]:
            report["hygiene"] = hygiene(doc)
        if flags["EDIT_V3_CLEAN_EFFECTS"]:
            report["effectsCleared"] = clean_effects(doc)
        if flags["EDIT_V3_SPLIT_HOLDS"] or flags["EDIT_V3_HOOK_PACE"]:
            report["holds"] = split_holds(doc, cfg, flags["EDIT_V3_HOOK_PACE"], flags["EDIT_V3_SPLIT_HOLDS"])
        if flags["EDIT_V3_PUNCHES"] or flags["EDIT_V3_INTERRUPTS"]:
            report.update(punches(doc, cfg, flags["EDIT_V3_PUNCHES"], flags["EDIT_V3_INTERRUPTS"]))
        if flags["EDIT_V3_PUNCH_SOUND"]:
            report["sounds"] = punch_sounds(doc)
        report["after"] = shot_stats(doc)
    except Exception as e:  # noqa: BLE001 - a finishing pass never fails a video
        for k, v in snapshot.items():
            if v is not None:
                doc[k] = v
        report = {"on": True, "version": VERSION, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    doc.setdefault("meta", {})["editingV3"] = report
    return report
