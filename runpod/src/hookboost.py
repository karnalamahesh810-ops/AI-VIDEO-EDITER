"""
The hook booster (the owner, 2026-10-02): the first ~30 seconds hit harder.

A viewer decides in the opening whether to stay. The top documentary channels
open with short, striking shots that change while the narration hooks, a slow
push on anything that sits still, a soft whoosh on the first cuts, and no text
over the first seconds. This module does that, behind HOOK_BOOST (default off;
one job can A/B it with {"config": {"HOOK_BOOST": true}}). Off, every function
here returns its input untouched and the video is cut exactly as before.

  prepare           BEFORE the shots are planned (handler.do_plan, right after
                    src/mentions.py): each beat that starts in the first
                    HOOK_BOOST_SECONDS and runs longer than HOOK_BOOST_SPLIT_OVER
                    is cut into 2-3 beats of HOOK_BOOST_MIN_SHOT..MAX_SHOT
                    seconds, on word boundaries (the cuts the narration itself
                    offers: a sentence end, a clause, a breath, never inside a
                    phrase, never mid-word). The director then plans each piece
                    and every piece is SOURCED AND JUDGED like any other beat, so
                    the rules that keep a video honest apply to the new shots
                    unchanged: the relevance gate, "every clip must fit its own
                    line", never the same file or moment twice (gapfill.Used,
                    media.variety_violations), the hook's best-of search.
                    (Reusing the first clip's other moments or the runners-up
                    would have found almost nothing: the runners-up keep no
                    file, a fan-out part returns only its winner.) A piece that
                    finds no footage goes through the usual ladder and, last of
                    all, the neighbouring shot is held over it - the scene is
                    then as long as it was before the booster.
  rank_bonus,       the hook's PICKS: among clips that already passed the judge,
  motion_weight     those that move and show scale, people and action win near-
                    ties (media._best_of / media.apply_motion). Bounded: relevance
                    still leads, a clearly better-fitting clip always wins.
  push_in           a slow push on stills and on static clips of the opening
                    (the renderer already draws scene.reframe and a still's
                    motion: no renderer change).
  cut_sounds        the first HOOK_BOOST_SFX_CUTS cuts get a soft whoosh from the
                    existing transition sounds (timeline.plan_transition_sfx):
                    the same level rules as every transition sound, so the
                    owner's 20% sound level (SFX_VOLUME) and the voice-relative
                    ceilings apply; nothing louder is introduced.
  quiet             no text graphic in the first HOOK_BOOST_QUIET_SECONDS unless
                    it is a date or number the planner must show (treatments).
  add_teaser        HOOK_TEASER (default off): a cold open - HOOK_TEASER_SHOTS
                    one-second flashes of the video's most striking LATER shots
                    under the first line, only when that line is a hook question
                    or statement. A flashed shot shows again at its own line and
                    nowhere else (the scene carries "teaser": true and the
                    repeat checks, gapfill.Shot.of_scene, leave it out).
  opening_stats     what changed, for doc.meta.hookBoost.
"""
from __future__ import annotations

import itertools
import re
from typing import Any, Dict, List, Optional, Tuple

from . import config

# What the last prepare() did (the handler writes it into doc.meta.hookBoost).
LAST: Dict[str, Any] = {}

TARGET_SHOT = 2.4          # the length a split aims for (s)
MIN_WORDS = 2              # a shot is never a single word
W_LEN = 2.0                # as transcribe._W_LENGTH: (length - target) / target, squared
W_CUT = 1.5                # as transcribe._W_CUT: x (1 - cut quality)
W_OVER = 25.0              # a piece over HOOK_BOOST_MAX_SHOT (only when its beat has no good cut for 3)
K_COUNT = 0.6              # cost of one shot more or fewer than the length asks for
STILL_PUSH = "zoom-in"     # a still's slow centred push (remotion stillMotion.tsx)
PUSH_FROM = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
PUSH_TO = {"x": 0.035, "y": 0.035, "w": 0.93, "h": 0.93}      # ~7.5% in over the shot
PUSH_MIN_SECONDS = 1.2     # no move on a shot shorter than this
STATIC_BELOW = 0.25        # measured motion (media.motion_of, 0..1) under which a clip gets the push
SOFT_CUTS = ("zoom", "punch", "zoom")   # _TRANSITION_SFX keys: the soft whoosh, the zoom whoosh, the soft whoosh
TEXT_CATEGORIES = {"HEADLINES", "TEXT", "QUOTES", "CALLOUTS", "LOWER_THIRDS"}
TEASER_OWN_MIN = 1.5       # the first line's own shot keeps at least this long (s)
TEASER_SNAP = 0.45         # a flash cuts on the word start nearest its time, within this (s)


def enabled() -> bool:
    return bool(getattr(config, "HOOK_BOOST", False))


def window() -> float:
    """The opening the booster works on (seconds)."""
    return max(0.0, float(getattr(config, "HOOK_BOOST_SECONDS", 30.0) or 0.0))


def limits() -> Tuple[float, float, float]:
    """(shortest shot, longest shot, a beat is split when longer than this), sane whatever the config says."""
    lo = max(0.6, float(getattr(config, "HOOK_BOOST_MIN_SHOT", 1.8) or 1.8))
    hi = max(lo, float(getattr(config, "HOOK_BOOST_MAX_SHOT", 3.0) or 3.0))
    over = max(2.0 * lo, float(getattr(config, "HOOK_BOOST_SPLIT_OVER", 3.5) or 3.5))
    return lo, hi, over


# --------------------------------------------------------------------------- #
# Cutting the opening
# --------------------------------------------------------------------------- #

def _quality(words: list) -> List[float]:
    """How good a place each word boundary is to cut (transcribe._cut_features; punctuation alone if that fails)."""
    try:
        from . import transcribe
        got = transcribe._cut_features(words)["quality"]
        if len(got) == len(words) + 1:
            return list(got)
    except Exception:  # noqa: BLE001 - a plainer reading of the same words
        pass
    out = [0.0] * (len(words) + 1)
    for k in range(1, len(words)):
        t = str(getattr(words[k - 1], "text", "") or "").rstrip("\"'”’)]")
        out[k] = 1.0 if t[-1:] in ".!?" else 0.8 if t[-1:] in ";:" else 0.7 if t[-1:] == "," else 0.2
    return out


def _cut_set(seg, k: int, lo: float, hi: float) -> Optional[Tuple[float, Tuple[int, ...]]]:
    """(cost, word indices to cut before) of the best way to cut the beat into k shots, None when none fits."""
    words = list(seg.words)
    n = len(words)
    quality = _quality(words)
    t0, t1 = float(seg.start), float(seg.end)
    best: Optional[Tuple[float, Tuple[int, ...]]] = None
    for cuts in itertools.combinations(range(MIN_WORDS, n - MIN_WORDS + 1), k - 1):
        if any(b - a < MIN_WORDS for a, b in zip(cuts, cuts[1:])):
            continue
        times = [t0] + [float(words[c].start) for c in cuts] + [t1]
        lengths = [b - a for a, b in zip(times, times[1:])]
        if min(lengths) < lo - 1e-6:
            continue
        cost = sum(W_LEN * ((x - TARGET_SHOT) / TARGET_SHOT) ** 2 for x in lengths)
        cost += sum(W_OVER * ((x - hi) / hi) ** 2 for x in lengths if x > hi)
        cost += sum(W_CUT * (1.0 - quality[c]) for c in cuts)
        if best is None or cost < best[0]:
            best = (cost, cuts)
    return best


def choose_cuts(seg, lo: float, hi: float) -> Optional[Tuple[int, ...]]:
    """
    The word indices a beat is cut before (1 or 2 of them), or None to leave it
    whole: two shots up to ~6 s, three beyond, the cheapest cuts in the sense of
    transcribe.human_cuts (a sentence end, a clause or a breath cost least; inside
    a phrase most), every shot at least `lo` seconds and two words.
    """
    words = list(getattr(seg, "words", None) or [])
    d = float(seg.end) - float(seg.start)
    if len(words) < 2 * MIN_WORDS or d < 2 * lo - 1e-6:
        return None
    first = min(3, max(2, int(round(d / TARGET_SHOT))))
    best: Optional[Tuple[float, Tuple[int, ...]]] = None
    for k in (2, 3):
        if d < k * lo - 1e-6:
            continue
        got = _cut_set(seg, k, lo, hi)
        if got is None:
            continue
        total = got[0] + K_COUNT * abs(k - first)        # the usual number of shots, unless its cuts are poor
        if best is None or total < best[0]:
            best = (total, got[1])
    return best[1] if best else None


def _texts(seg, cuts: Tuple[int, ...]) -> List[str]:
    """The beat's text for each piece: the beat's own tokens when they line up with its words, else the words."""
    words = list(seg.words)
    spans = list(zip((0,) + tuple(cuts), tuple(cuts) + (len(words),)))
    tokens = (seg.text or "").split()
    if len(tokens) == len(words):
        return [" ".join(tokens[a:b]) for a, b in spans]
    return [" ".join(str(getattr(w, "text", "") or "").strip() for w in words[a:b]).strip() for a, b in spans]


def _stats(segs: list, horizon: float) -> dict:
    inside = [float(s.end) - float(s.start) for s in segs if float(s.start) < horizon]
    return {"scenes": len(inside), "avgShotSeconds": round(sum(inside) / len(inside), 2) if inside else 0.0}


def split_opening(segments: list) -> Tuple[list, List[int], dict]:
    """
    (beats, parent index of each, info): the beats of the opening cut into shots.
    The input beats are never changed; with nothing to cut the same list comes back.
    """
    from . import mentions
    lo, hi, over = limits()
    horizon = window()
    out: list = []
    parents: List[int] = []
    splits: List[dict] = []
    for idx, seg in enumerate(segments):
        cuts = None
        if float(seg.start) < horizon and float(seg.end) - float(seg.start) > over:
            cuts = choose_cuts(seg, lo, hi)
        if not cuts:
            out.append(seg)
            parents.append(idx)
            continue
        words = list(seg.words)
        bounds = [0] + list(cuts) + [len(words)]
        times = [float(seg.start)] + [float(words[c].start) for c in cuts] + [float(seg.end)]
        pieces = []
        for text, a, b, t_a, t_b in zip(_texts(seg, cuts), bounds, bounds[1:], times, times[1:]):
            out.append(mentions._piece(seg, text, t_a, t_b, words[a:b]))
            parents.append(idx)
            pieces.append([round(t_a, 2), round(t_b, 2)])
        splits.append({"beat": idx, "start": round(float(seg.start), 2), "end": round(float(seg.end), 2),
                       "pieces": pieces, "cutBefore": [str(getattr(words[c], "text", "")) for c in cuts]})
    info = {"seconds": horizon, "beatsBefore": len(segments), "beatsAfter": len(out),
            "shotsAdded": len(out) - len(segments), "splits": splits,
            "before": _stats(segments, horizon), "afterPlan": _stats(out, horizon)}
    return (out if splits else segments), parents, info


def remap_focus(focus: Dict[int, dict], parents: List[int]) -> Dict[int, dict]:
    """src/mentions.py's focus (a beat that opens with a named person) moved onto the first piece of its beat."""
    if not focus:
        return focus or {}
    first: Dict[int, int] = {}
    for new, old in enumerate(parents):
        first.setdefault(old, new)
    return {first[k]: v for k, v in focus.items() if k in first}


def prepare(segments: list, brief: Optional[dict], focus: Optional[Dict[int, dict]] = None
            ) -> Tuple[list, Dict[int, dict], dict]:
    """
    (beats, focus, info) for handler.do_plan, right after mentions.prepare and
    before the shots are planned: the opening cut into shots, the brief's beat
    numbers (hookBeats, sections) and the focus moved onto the new beats in
    place. Off: the beats and focus as they came, info {}. Never raises:
    anything unexpected leaves the beats as they were.
    """
    LAST.clear()
    focus = focus if focus is not None else {}
    if not enabled() or not segments:
        return segments, focus, {}
    try:
        from . import mentions
        out, parents, info = split_opening(segments)
        if out is not segments:
            mentions.remap_brief(brief, parents)
            focus = remap_focus(focus, parents)
    except Exception as e:  # noqa: BLE001 - a plainer opening, never a failed video
        print(f"[hookboost] skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return segments, focus, {}
    LAST.update(info)
    print(f"[hookboost] opening ({info['seconds']:.0f} s): {info['beatsBefore']} -> {info['beatsAfter']} beats, "
          f"{len(info['splits'])} cut; average shot {info['before']['avgShotSeconds']} s -> "
          f"{info['afterPlan']['avgShotSeconds']} s", flush=True)
    return out, focus, info


# --------------------------------------------------------------------------- #
# The hook's picks: footage that moves and shows scale, people and action
# --------------------------------------------------------------------------- #

_SCALE = re.compile(r"\b(aerial|drone|overhead|bird'?s[- ]eye|wide (?:shot|view|angle)|panoram\w*|skyline|"
                    r"vast|sweeping|horizon|landscape|cityscape|from above)\b", re.I)
_PEOPLE = re.compile(r"\b(crowds?|people|rescu\w*|firefight\w*|police|soldiers?|protest\w*|residents|"
                     r"workers|survivors?|evacuat\w*|responders?|children|families|men|women|man|woman)\b", re.I)
_ACTION = re.compile(r"\b(flames?|fires?|smoke|flood\w*|storms?|lightning|tornado\w*|hurricane\w*|explo\w*|"
                     r"crash\w*|collaps\w*|waves?|surge|rushing|erupt\w*|debris|destruction|destroyed|"
                     r"damage\w*|wreck\w*|burning|raging|submerged|overflow\w*|swirling|churning|cracked|"
                     r"parched|drought|receding|dry)\b", re.I)


def drama(asset) -> float:
    """0..1: how much scale, people and action the judge saw in the clip (its description), plus an event shot."""
    text = str(getattr(asset, "content_description", "") or "")
    groups = sum(1 for rx in (_SCALE, _PEOPLE, _ACTION) if rx.search(text))
    event = 1 if str(getattr(asset, "specificity", "") or "") == "event" else 0
    return (groups + event) / 4.0


def rank_bonus(asset) -> float:
    """What a clip adds to its rank among those that passed, in the hook only (media._best_of)."""
    if not enabled():
        return 0.0
    return max(0.0, float(getattr(config, "HOOK_BOOST_DRAMA", 0.0) or 0.0)) * drama(asset)


def motion_weight() -> float:
    """The motion weight the hook uses even when MOTION_PREFERENCE is 0 (media._motion_weight)."""
    if not enabled():
        return 0.0
    return max(0.0, float(getattr(config, "HOOK_BOOST_MOTION", 0.0) or 0.0))


# --------------------------------------------------------------------------- #
# Dressing the opening: a push, a whoosh, a quiet screen
# --------------------------------------------------------------------------- #

def _measure(asset) -> Optional[dict]:
    path = str(getattr(asset, "local_path", "") or "")
    if not path or getattr(asset, "kind", "") != "video":
        return None
    from . import media
    return media.motion_of(path)


def push_in(scenes: List[dict], assets: list, fps: int, measure=None) -> Dict[str, int]:
    """
    A slow push on every still without a move and every static clip in the
    opening. A still takes the renderer's "zoom-in" (even in a style that holds
    photos still); a clip measured nearly motionless (or frozen) gets
    scene.reframe, the move the renderer already draws on a clip. A scene that
    already has a move, a graphic and a teaser flash are left alone.
    """
    measure = measure or _measure
    horizon = window()
    stats = {"stills": 0, "clips": 0, "checked": 0}
    for i, sc in enumerate(scenes):
        if int(sc.get("startFrame", 0)) / max(1, fps) >= horizon:
            break
        if sc.get("teaser") or sc.get("animation") or sc.get("reframe"):
            continue
        if int(sc.get("durationInFrames", 0)) / max(1, fps) < PUSH_MIN_SECONDS:
            continue
        kind = (sc.get("media") or {}).get("type")
        if kind == "image":
            if str(sc.get("motion") or "none") == "none":
                sc["motion"] = STILL_PUSH
                stats["stills"] += 1
        elif kind == "video":
            asset = assets[i] if i < len(assets) else None
            m = measure(asset) if asset is not None else None
            if m is None:
                continue
            stats["checked"] += 1
            if m.get("static") or float(m.get("motion", 1.0)) < STATIC_BELOW:
                sc["reframe"] = {"from": dict(PUSH_FROM), "to": dict(PUSH_TO)}
                stats["clips"] += 1
    return stats


def cut_sounds(scenes: List[dict], fps: int) -> Dict[int, str]:
    """
    {scene index: transition key} for the first HOOK_BOOST_SFX_CUTS cuts of the
    video that have no sound of their own. timeline.plan_transition_sfx turns
    each into the soft whoosh that key stands for (an existing transition sound,
    at the level every transition sound has: set against the voice, under its
    ceiling, under the master SFX_VOLUME). A cut that already has a transition
    sound or a pack clip's own sound counts as one of the cuts and is left alone.
    """
    if not enabled():
        return {}
    from . import timeline
    horizon = window()
    out: Dict[int, str] = {}
    last = min(len(scenes) - 1, max(0, int(getattr(config, "HOOK_BOOST_SFX_CUTS", 0) or 0)))
    for i in range(1, last + 1):
        sc = scenes[i]
        if int(sc.get("startFrame", 0)) / max(1, fps) >= horizon:
            break
        t = sc.get("transition") or "none"
        if t in timeline._TRANSITION_SFX or timeline.pack_name(t):
            continue
        out[i] = SOFT_CUTS[(i - 1) % len(SOFT_CUTS)]
    return out


def quiet(at: float, mode: str, cue: str, template: dict, text_cues) -> bool:
    """
    True when a graphic the planner would place at `at` seconds must wait: a TEXT
    graphic (a headline, phrase, quote, label, lower third) in the first
    HOOK_BOOST_QUIET_SECONDS. A must-show graphic (a date or number the planner
    has to show, a person's introduction) and every figure, chart or map are not
    text graphics here and are never held back.
    """
    if not enabled() or mode == "must":
        return False
    if at >= max(0.0, float(getattr(config, "HOOK_BOOST_QUIET_SECONDS", 0.0) or 0.0)):
        return False
    return (cue or "") in text_cues or str((template or {}).get("category") or "") in TEXT_CATEGORIES


# --------------------------------------------------------------------------- #
# The cold open
# --------------------------------------------------------------------------- #

_QUESTION = re.compile(r"\?|^\W*(?:what|why|how|who|where|when|which|imagine|picture this|did you know|"
                       r"have you ever|ever wonder|suppose|think about)\b", re.I)
_CLAIM = re.compile(r"\b(never|nobody|no one|everything|nothing|secret|hidden|worst|deadliest|biggest|largest|"
                    r"first time|last time|million|billion|thousands|collaps\w*|disaster|catastroph\w*|crisis|"
                    r"vanish\w*|disappear\w*|ran out|running out|dying|dead|killed|shock\w*|impossible|forever|"
                    r"warning|emergency|unthinkable|devastat\w*)\b", re.I)


def is_hook_line(text: str) -> bool:
    """The first line is a hook question or a bold statement (a question, or a claim of scale, danger or loss)."""
    t = " ".join(str(text or "").split())
    return bool(t) and len(t.split()) <= 40 and bool(_QUESTION.search(t) or _CLAIM.search(t))


def _first_line(segments: list) -> Tuple[str, float]:
    """(the text of the first sentence - up to three beats, when it ends in seconds)."""
    from . import transcribe
    parts: List[str] = []
    end = float(segments[0].start)
    for seg in segments[:3]:
        parts.append(str(seg.text or ""))
        end = float(seg.end)
        words = list(getattr(seg, "words", None) or [])
        if words and transcribe._ends_sentence(str(getattr(words[-1], "text", ""))):
            break
    return " ".join(parts), end


def _score(asset, measure) -> float:
    base = asset.final_score if getattr(asset, "final_score", None) is not None else \
        (asset.relevance_score or 0.0) + 0.5 * (0.5 if asset.quality is None else asset.quality)
    m = measure(asset)
    motion = float(m["motion"]) if m and isinstance(m.get("motion"), (int, float)) else 0.5
    return base + 0.5 * drama(asset) + 0.3 * motion


def striking(segments: list, assets: list, measure=None) -> List[Tuple[float, int]]:
    """
    [(score, beat index)], best first: the clips of the part after the opening
    that pass the existing gates (a real clip, not flagged for review, judged at
    or above VISION_MIN_SCORE), one per source video, ranked by how well they
    fit their line, how much scale, people and action they show and how much
    they move.
    """
    measure = measure or _measure
    horizon = window()
    found: List[Tuple[float, int]] = []
    seen: set = set()
    scored = []
    for i, (seg, a) in enumerate(zip(segments, assets)):
        if i == 0 or a is None or getattr(a, "kind", "") != "video" or float(seg.start) < horizon:
            continue
        if not (getattr(a, "local_path", "") or getattr(a, "url", "")) or getattr(a, "review_required", False):
            continue
        rel = getattr(a, "relevance_score", None)
        if rel is None or rel < float(config.VISION_MIN_SCORE):
            continue
        scored.append((_score(a, measure), i))
    for score, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        key = getattr(assets[i], "moment_key", "") or getattr(assets[i], "identity", "")
        video = re.sub(r"@.*$", "", str(key))          # every moment of one source video counts as one
        if video in seen:
            continue
        seen.add(video)
        found.append((score, i))
    return found


def add_teaser(segments: list, shots: list, assets: list, fps: int, measure=None
               ) -> Tuple[list, list, list, dict]:
    """
    (segments, shots, assets, info): HOOK_TEASER_SHOTS one-second flashes of the
    video's most striking later shots from the very start, under the first line,
    when that line is a hook question or statement. The flashes cut on the
    narration's word starts; the first line's own shot keeps at least 1.5 s
    after them (a beat the flashes cover entirely is dropped). Each flash is a
    beat of its own that carries the later shot's clip and "teaser": true on its
    shot. Skipped (info says why) and the lists unchanged when the line is no
    hook, fewer than two later shots qualify or the line is too short.
    """
    from . import mentions
    info: Dict[str, Any] = {"enabled": True}
    if not segments or not getattr(segments[0], "words", None):
        return segments, shots, assets, dict(info, skipped="no narration words")
    line, line_end = _first_line(segments)
    if not is_hook_line(line):
        return segments, shots, assets, dict(info, skipped="the first line is not a hook question or statement")
    flash = min(1.5, max(0.6, float(getattr(config, "HOOK_TEASER_SECONDS", 1.0) or 1.0)))
    n_want = min(4, max(2, int(getattr(config, "HOOK_TEASER_SHOTS", 3) or 3)))
    pad_shots = list(shots) + [{}] * max(0, len(segments) - len(shots))
    pad_assets = list(assets) + [None] * max(0, len(segments) - len(assets))
    picks = striking(segments, pad_assets, measure)
    if len(picks) < 2:
        return segments, shots, assets, dict(info, skipped="fewer than two later shots qualify")
    starts = sorted({round(float(w.start), 3) for s in segments[:4] for w in (s.words or [])})
    t0 = float(segments[0].start)
    cuts: List[float] = []
    for n in range(min(n_want, len(picks)), 1, -1):
        cuts, prev = [], t0
        for j in range(1, n + 1):
            near = [s for s in starts if s > prev + 0.5 * flash and s <= line_end + 1e-6
                    and abs(s - (t0 + j * flash)) <= TEASER_SNAP]
            if not near:
                break
            prev = min(near, key=lambda s: abs(s - (t0 + j * flash)))
            cuts.append(prev)
        if len(cuts) == n:
            # The flashes stay under the first line, and the line keeps its own shot: at least
            # TEASER_OWN_MIN of it after them, and of the beat they stop in.
            rest = [float(s.end) for s in segments if float(s.end) > cuts[-1] + 1e-6]
            if rest and rest[0] - cuts[-1] >= TEASER_OWN_MIN and line_end - cuts[-1] >= TEASER_OWN_MIN:
                break
        cuts = []
    if len(cuts) < 2:
        return segments, shots, assets, dict(info, skipped="the first line is too short for a teaser")
    n = len(cuts)
    bounds = [t0] + cuts
    all_words = [w for s in segments[:4] for w in (s.words or [])]
    new_segs: list = []
    new_shots: list = []
    new_assets: list = []
    flashes = []
    for j in range(n):
        src = picks[j][1]
        words = [w for w in all_words if bounds[j] - 1e-6 <= float(w.start) < bounds[j + 1] - 1e-6]
        piece = mentions._piece(segments[0], " ".join(str(w.text).strip() for w in words), bounds[j], bounds[j + 1], words)
        s_shot = pad_shots[src] or {}
        new_segs.append(piece)
        new_shots.append({"query": s_shot.get("query", ""), "visualType": "footage",
                          "treatment": s_shot.get("treatment", "film"), "overlay": None, "teaser": True})
        new_assets.append(pad_assets[src])
        flashes.append({"fromBeat": src, "at": round(bounds[j], 2), "seconds": round(bounds[j + 1] - bounds[j], 2),
                        "score": round(picks[j][0], 3),
                        "relevance": getattr(pad_assets[src], "relevance_score", None),
                        "clip": getattr(pad_assets[src], "identity", "")})
    end = cuts[-1]
    dropped = 0
    for idx, seg in enumerate(segments):
        if float(seg.end) <= end + 1e-6:
            dropped += 1
            continue
        if float(seg.start) < end - 1e-6:
            words = [w for w in (seg.words or []) if float(w.start) >= end - 1e-6]
            seg = mentions._piece(seg, " ".join(str(w.text).strip() for w in words), end, float(seg.end), words)
        new_segs.append(seg)
        new_shots.append(pad_shots[idx])
        new_assets.append(pad_assets[idx])
    info.update(flashes=flashes, firstLine=line[:160], droppedBeats=dropped,
                ownShotSeconds=round(float(new_segs[n].end) - float(new_segs[n].start), 2))
    return new_segs, new_shots, new_assets, info


# --------------------------------------------------------------------------- #
# After the footage is found: never a weaker shot for the sake of a faster cut
# --------------------------------------------------------------------------- #

def _weak(scene: dict) -> bool:
    """A shot that did not clear the relevance gate (a near-miss kept so no beat is empty)."""
    m = scene.get("media") or {}
    if m.get("type") not in ("video", "image") or not m.get("url"):
        return False
    rel = m.get("relevanceScore")
    return isinstance(rel, (int, float)) and not isinstance(rel, bool) and rel < float(config.VISION_MIN_SCORE)


def _solid(scene: dict) -> bool:
    m = scene.get("media") or {}
    if str(m.get("source") or "") == "ai-presenter":
        return False            # the AI presenter is never held over another line (src/presenter/hybrid.py)
    return m.get("type") in ("video", "image") and bool(m.get("url")) and not _weak(scene)


def settle(doc: dict, info: Optional[dict]) -> Dict[str, int]:
    """
    The rule behind the cuts: a faster opening never shows a worse-fitting clip.
    Every beat prepare() cut into shots is looked at once the footage is found; a
    shot of it whose clip did not clear the relevance gate (VISION_MIN_SCORE: a
    near-miss kept so that no beat is empty) is not shown - the shot beside it from
    the same beat, which did clear it, is held over its words while its clip still
    covers the longer scene (the renderer's 0.6x floor), so that beat is as long
    on one good shot as it was before the booster. A beat whose shots all missed
    the gate is left as the sourcing made it. Returns {"beats", "held"}.
    """
    from . import gapfill, shotcap, timeline
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    out = {"beats": 0, "held": 0}
    for split in reversed((info or {}).get("splits") or []):
        lo, hi = float(split["start"]), float(split["end"])
        group = [sc for sc in scenes if lo - 0.05 <= int(sc.get("startFrame", 0)) / fps < hi - 0.05
                 and not sc.get("teaser")]
        if len(group) < 2 or not any(_solid(sc) for sc in group):
            continue
        out["beats"] += 1
        members = {id(x) for x in group}
        for sc in reversed(group):
            if not _weak(sc):
                continue
            i = next((k for k, x in enumerate(scenes) if x is sc), -1)
            prev = scenes[i - 1] if i > 0 and id(scenes[i - 1]) in members and _solid(scenes[i - 1]) else None
            nxt = scenes[i + 1] if 0 <= i + 1 < len(scenes) and id(scenes[i + 1]) in members \
                and _solid(scenes[i + 1]) else None
            need = int(sc.get("durationInFrames", 0))
            side = None
            # (With the shot cap on: within SHOT_MAX_SECONDS and at real speed only, src/shotcap.py.)
            for rate in shotcap.hold_rates():
                if prev is not None and gapfill._room(prev, fps, rate) >= need:
                    side = "prev"
                    break
                if nxt is not None and gapfill._room(nxt, fps, rate) >= need:
                    side = "next"
                    break
            if side is None:
                continue
            start = int(sc.get("startFrame", 0))
            keep = prev if side == "prev" else nxt
            words, text = list(sc.get("words") or []), str(sc.get("text") or "")
            if side == "prev":
                keep["words"] = list(keep.get("words") or []) + words
                keep["text"] = f"{keep.get('text') or ''} {text}".strip()
                gone = start                                      # the cut into the dropped shot
            else:
                keep["startFrame"] = start
                keep["words"] = words + list(keep.get("words") or [])
                keep["text"] = f"{text} {keep.get('text') or ''}".strip()
                gone = start + need                               # the cut out of it
            keep["durationInFrames"] = int(keep.get("durationInFrames", 0)) + need
            keep.setdefault("semanticMetadata", {}).setdefault("heldOver", []).append(sc.get("id") or "")
            del scenes[i]
            meta = timeline.sfx_meta()
            doc["sfx"] = [fx for fx in (doc.get("sfx") or [])
                          if not (fx.get("kind") == "transition" and abs(
                              int(fx.get("startFrame", 0)) + int(round(float(meta.get(fx.get("name"), {}).get("peak", 0.0))
                                                                          * fps)) - gone) <= 1)]
            out["held"] += 1
    if out["held"]:
        doc.setdefault("meta", {})["sceneCount"] = len(scenes)
        print(f"[hookboost] {out['held']} shot(s) of the cut opening missed the relevance gate; the better shot "
              "of the same beat is held over them", flush=True)
    return out


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #

def opening_stats(scenes: List[dict], fps: int) -> dict:
    """The opening of a built timeline: how many shots and how long they run."""
    horizon = window()
    lengths = [int(s.get("durationInFrames", 0)) / max(1, fps) for s in scenes
               if int(s.get("startFrame", 0)) / max(1, fps) < horizon and not s.get("teaser")]
    if not lengths:
        return {"scenes": 0, "avgShotSeconds": 0.0, "shortestShotSeconds": 0.0, "longestShotSeconds": 0.0}
    return {"scenes": len(lengths), "avgShotSeconds": round(sum(lengths) / len(lengths), 2),
            "shortestShotSeconds": round(min(lengths), 2), "longestShotSeconds": round(max(lengths), 2)}


def merge_report(report: Optional[dict], info: Optional[dict]) -> dict:
    """doc.meta.hookBoost as the build wrote it, plus what prepare did before the shots were planned."""
    out = dict(report or {})
    if info:
        out.update(shotsAdded=info.get("shotsAdded", 0), beatsBefore=info.get("beatsBefore"),
                   beatsAfter=info.get("beatsAfter"), splits=info.get("splits", []),
                   openingBefore=info.get("before"))
    return out
