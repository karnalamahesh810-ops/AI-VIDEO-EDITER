"""
The AI presenter video's timeline: the shots and their generated files as the
worker's normal render document (src/timeline.py build), so the editor, the
quality gate, publishing and the renderer all work on it unchanged - then the
style's own pass over it.

What the style sets (the owner's six reference videos, docs/ai-avatar-
reference-analysis-2026-10-07.md section 8.2, and the build brief):
  * hard cuts - always into and out of the presenter; an optional dissolve
    between b-roll shots only ("dissolves": share of b-roll joins, default 0);
  * no effects, no graphics planner, no sound effects; captions only when the
    job asks (the references have none); the presenter's lower third only
    when the job asks ("lower_third": true - the clean editorial look:
    white type, a small gold rule);
  * stills move like the references': mostly a slow push-in, now and then a
    pull-back or drift (no two rules fight: the renderer eases them), with
    living-photo depth where the picture allows (src/living.py);
  * about a third of the presenter's appearances as a 50/50 split screen:
    the presenter on the left, the line's own picture on the right with a
    slow push-in (scene.frame "split", media.split - remotion SceneClip);
  * the bare edit of the references by default: no grade, no grain. "look":
    "warm" adds one warm grade over every picture (src/grade.py preset
    warm-doc, normalised to the video's median tone) and a light film grain
    and soft vignette over the picture track (doc.look, remotion FilmLook),
    so the presenter, the AI clips and the stills read as one camera;
  * music only when the job names a track (none of the bundled beds suits
    a talking-head video, and the references run without);
  * a line nothing could be made for is held by the still before it (its
    move just runs longer) - never a repeated picture.
"""
from __future__ import annotations

import contextlib
import dataclasses
import zlib
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import config, grade, living, timeline
from ..media import MediaAsset
from ..transcribe import Segment, Word
from .generate import SPLIT, Asset
from .shotplan import Shot

# Still moves, by shot: mostly the references' slow push-in.
STILL_MOVES = ("zoom-in", "zoom-in", "push-offcenter", "zoom-in", "zoom-out", "zoom-in", "drift-diagonal", "zoom-in",
               "push-offcenter", "zoom-in")
LOOK = {"grain": 0.05, "vignette": 0.16}
GRADE = {"preset": "warm-doc", "strength": 0.85, "normalize": True}
LOWER_THIRD_SECONDS = 4.5


@contextlib.contextmanager
def _config(**values: Any) -> Iterator[None]:
    """Settings the presenter build needs whatever the job's config says (put back after)."""
    old = {k: getattr(config, k) for k in values if hasattr(config, k)}
    try:
        for k, v in values.items():
            if hasattr(config, k):
                setattr(config, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(config, k, v)


# A held AI clip plays no slower than this (the renderer slows a clip that is shorter than its scene; a
# presenter clip is never held: its lips follow the voice).
HOLD_MIN_RATE = 0.75


def _can_hold(a: Optional[Asset], seconds: float) -> bool:
    """Whether this asset can stay on screen for `seconds`: any still; an AI clip slowed no more than HOLD_MIN_RATE."""
    if a is None:
        return False
    if a.kind == "image":
        return True
    return a.source == "ai-video" and float(a.seconds or 0.0) >= HOLD_MIN_RATE * seconds


def settle(shots: List[Shot], assets: Dict[str, Optional[Asset]]) -> List[Tuple[Shot, Optional[Asset]]]:
    """
    Each shot with its asset. A shot that got nothing is held by its
    neighbour - the shot before, else the one after - when that one can stay
    on screen that long (a still; an AI clip slowed no more than 0.75x; never
    the presenter): its span grows over the line. Only a line with neither
    stays empty (the check before the render gives it a text card).
    """
    items: List[Tuple[Shot, Optional[Asset]]] = []
    for s in shots:
        s = dataclasses.replace(s, words=list(s.words), beats=list(s.beats))
        a = assets.get(s.id)
        if a is None and items:
            prev, pa = items[-1]
            if _can_hold(pa, s.end - prev.start):
                items[-1] = (dataclasses.replace(prev, end=s.end, text=f"{prev.text} {s.text}".strip(),
                                                 words=prev.words + s.words, beats=prev.beats + s.beats), pa)
                continue
        items.append((s, a))
    k = 0
    while k + 1 < len(items):
        s, a = items[k]
        nxt, na = items[k + 1]
        if a is None and _can_hold(na, nxt.end - s.start):
            items[k:k + 2] = [(dataclasses.replace(nxt, start=s.start, text=f"{s.text} {nxt.text}".strip(),
                                                   words=s.words + nxt.words, beats=s.beats + nxt.beats), na)]
            continue
        k += 1
    return items


def _media_asset(shot: Shot, a: Optional[Asset], kit: dict) -> Optional[MediaAsset]:
    if a is None:
        return None
    who = f"AI presenter {kit.get('name')}" if a.source == "ai-presenter" else "AI-generated"
    return MediaAsset(kind=a.kind, source=a.source, url=a.url if a.url.startswith("http") else "",
                      local_path=a.path, width=int(a.width or 0), height=int(a.height or 0),
                      duration=float(a.seconds or 0.0), attribution=f"{who} ({a.model or 'kit picture'})",
                      license="generated", query=(a.prompt or shot.still or shot.text)[:240],
                      review_required=bool(a.fallback), review_reason=(a.fallback or "")[:300],
                      intent=shot.role)


def _build_input(inp: Dict[str, Any], kit: dict) -> Dict[str, Any]:
    out = dict(inp)
    out["transition_pack"] = False                   # no overlay transition clips: hard cuts
    out["transitions"] = ["crossfade"]               # whatever the cutting planner picks becomes a dissolve or a cut
    out.setdefault("captions", False)                # the references run without captions
    out["brief"] = {"kind": "other", "summary": str(inp.get("title") or "")}
    if not (inp.get("bgm_url") or inp.get("bgm_genre") or inp.get("bgm_track")):
        out["bgm"] = bool(inp.get("bgm", False))     # no bundled bed suits it: music only when asked for
    out["sfx"] = bool(inp.get("sfx", False))
    return out


def build(*, shots: List[Shot], assets: Dict[str, Optional[Asset]], audio_url: str, narration_path: str,
          duration: float, inp: Dict[str, Any], kit: dict, planner: str = "presenter",
          warnings: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Tuple[Shot, Optional[Asset]]]]:
    """(the render document, the shots as they ended up with their assets)."""
    items = settle(shots, assets)
    segments, shot_rows, media = [], [], []
    for k, (s, a) in enumerate(items):
        segments.append(Segment(text=s.text, start=0.0 if k == 0 else float(s.start), end=float(s.end),
                                words=[Word(text=w.text, start=float(w.start), end=float(w.end)) for w in s.words]))
        presenter = s.kind == "presenter" and a is not None and a.source == "ai-presenter"
        shot_rows.append({"query": (s.still or s.text)[:240], "intent": s.role,
                          "visualType": "footage" if a is not None and a.kind == "video" else "image",
                          "treatment": "none", "subject": kit.get("name") if presenter else "",
                          "subjectType": "presenter" if presenter else ""})
        media.append(_media_asset(s, a, kit))
    with _config(TREATMENTS=False, HOOK_TEASER=False, HOOK_BOOST=False, STILL_MOTION=""):
        doc = timeline.build(segments, shot_rows, media, audio_url=audio_url, audio_duration=duration,
                             inp=_build_input(inp, kit), planner=planner, warnings=list(warnings or []),
                             narration_path=narration_path)
    _finish_scenes(doc, items, kit, assets)
    _transitions(doc, items, float(inp.get("dissolves") or 0.0))
    if inp.get("lower_third"):
        _lower_third(doc, items, kit)
    _look(doc, kit, str(inp.get("look") or "none"))
    if config.LIVING_PHOTOS:
        # The stills' depth layers (src/living.py), whatever the look: the move with parallax, for free.
        try:
            doc.setdefault("meta", {})["living"] = living.place(doc)
        except Exception as e:  # noqa: BLE001 - the stills move flat
            doc.setdefault("meta", {})["living"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return doc, items


def _split_half(scene: Dict[str, Any], s: Shot, a: Asset, half: Optional[Asset], kit: dict) -> None:
    """A presenter scene drawn 50/50: the presenter left (cropped on the face), the line's picture right."""
    if half is None or a.source != "ai-presenter":
        return
    framing = next((f for f in kit.get("framings") or [] if f.get("id") == a.framing), {}) or {}
    try:
        face_x = float(framing.get("face_x", 0.5))
    except (TypeError, ValueError):
        face_x = 0.5
    scene["frame"] = "split"
    scene["media"]["split"] = {"type": "image", "url": half.url if half.url.startswith("http") else half.path,
                               "source": half.source, "motion": "zoom-in",
                               # object-position x (%) that centres the face in the left half (cover crop of 16:9)
                               "focusX": round(max(0.0, min(100.0, (2 * face_x - 0.5) * 100)), 1)}
    scene.setdefault("semanticMetadata", {})["split"] = {"picture": half.report(), "prompt": half.prompt[:300]}


def _finish_scenes(doc: Dict[str, Any], items: List[Tuple[Shot, Optional[Asset]]], kit: dict,
                   assets: Optional[Dict[str, Optional[Asset]]] = None) -> None:
    for scene, (s, a) in zip(doc.get("scenes") or [], items):
        if a is not None and s.split:
            _split_half(scene, s, a, (assets or {}).get(f"{s.id}{SPLIT}"), kit)
        scene["effect"] = "none"
        scene["treatment"] = "none"
        media = scene.get("media") or {}
        if media.get("type") == "image":
            scene["motion"] = STILL_MOVES[zlib.crc32(s.id.encode("utf-8")) % len(STILL_MOVES)]
        elif media.get("type") == "video":
            scene["motion"] = "none"
        sem = scene.setdefault("semanticMetadata", {})
        sem["shotKind"] = s.kind if a is None or a.source != "kit-set" else "picture"
        sem["role"] = s.role
        if a is not None:
            sem["generated"] = {k: v for k, v in a.report().items() if k not in ("checks",)}
            sem["generated"]["checks"] = {k: v for k, v in (a.checks or {}).items() if k in ("face", "look")}
            if a.url:
                sem["originalUrl"] = a.url
            if a.source == "ai-presenter":
                window = {k: v for k, v in ((a.checks or {}).get("window") or {}).items() if k != "path"}
                sem["presenter"] = {"kit": kit.get("id"), "name": kit.get("name"), "framing": a.framing,
                                    "lag": a.lag, "window": window}
            if a.fallback:
                scene["reviewRequired"] = True
                scene["reviewReason"] = a.fallback[:300]
            else:
                scene["reviewRequired"] = False
                scene["reviewReason"] = ""
        if s.reason:
            sem["planReason"] = s.reason


def _is_presenter(scene: Dict[str, Any]) -> bool:
    return str((scene.get("media") or {}).get("source") or "") == "ai-presenter"


def _transitions(doc: Dict[str, Any], items: List[Tuple[Shot, Optional[Asset]]], dissolves: float) -> None:
    """Hard cuts; with `dissolves` > 0 that share of the b-roll-to-b-roll joins dissolve (never a presenter join)."""
    scenes = doc.get("scenes") or []
    fps = int(doc.get("fps") or 30)
    for i, sc in enumerate(scenes):
        sc["transition"] = "none"
        if i == 0 or dissolves <= 0:
            continue
        prev = scenes[i - 1]
        if _is_presenter(sc) or _is_presenter(prev):
            continue
        if sc["durationInFrames"] < fps or prev["durationInFrames"] < fps:
            continue
        if zlib.crc32(f"xf:{sc.get('id')}".encode("utf-8")) % 100 < dissolves * 100:
            pm = prev.get("media") or {}
            # The scene before plays on under the dissolve: a clip must be long enough to.
            if pm.get("type") == "video" and float(pm.get("clipSeconds") or 0) * fps < prev["durationInFrames"] + 15:
                continue
            sc["transition"] = "crossfade"
    doc["sfx"] = [x for x in doc.get("sfx") or [] if x.get("kind") != "transition"]


def _lower_third(doc: Dict[str, Any], items: List[Tuple[Shot, Optional[Asset]]], kit: dict) -> None:
    """The presenter's name, low left, on their first appearance long enough to read it (clean editorial look)."""
    fps = int(doc.get("fps") or 30)
    name = str(kit.get("name") or "").strip()
    if not name:
        return
    for sc in doc.get("scenes") or []:
        if not _is_presenter(sc) or sc["durationInFrames"] < int(3.4 * fps):
            continue
        start = sc["startFrame"] + int(0.6 * fps)
        dur = min(int(LOWER_THIRD_SECONDS * fps), sc["durationInFrames"] - int(0.9 * fps))
        doc.setdefault("overlays", []).append({
            "type": "motion", "template": "KT_LOWER_THIRD", "variant": "kt-lower-third", "typeStyle": "editorial",
            "text": name, **({"subtitle": kit["title"]} if kit.get("title") else {}),
            "startFrame": int(start), "durationInFrames": int(max(fps * 2, dur)), "presenter": True})
        return


def _look(doc: Dict[str, Any], kit: dict, look: str) -> None:
    """One warm grade over every picture and a light grain + vignette over the picture track ("none": neither)."""
    if look == "none":
        doc["grade"] = None
        doc.pop("look", None)
        return
    preset = str(kit.get("grade") or GRADE["preset"])
    if preset not in grade.PRESETS:
        preset = GRADE["preset"]
    doc["grade"] = dict(GRADE, preset=preset)
    doc["look"] = dict(LOOK)
    doc.setdefault("meta", {})["grade"] = grade.prepare(doc, remote=False)
