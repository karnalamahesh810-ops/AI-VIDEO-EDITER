"""
Smart re-render: every rendered chunk of a video is kept in Cloudflare R2 under
a content hash of everything that draws its frames, and a later render of the
same project reuses each chunk whose hash is unchanged. After a small edit (one
line's clip swapped, a look's words changed) only the chunks the edit touched
are drawn again; the rest are downloaded and joined without re-encoding, and
the sound and its loudness are always set again from the whole mix.

Chunk boundaries (stable_chunks) are fixed by the timeline itself: each chunk
is about POD_RENDER_CHUNK_SECONDS long and ends on the cleanest scene cut near
that length, chosen left to right. A boundary depends only on the cuts within
reach of it, never on the video's total length or the machine, so an edit late
in the video never moves an earlier boundary: when the narration's timing
shifts after time T, every chunk before T is reused and the ones after it are
drawn again.

What a chunk's hash covers (picture_hash) - absolute frame positions, since
many looks read them (a REC timecode, a style picked from the overlay's start):
  * every scene drawn in its frames (a crossfade's tail included), all of its
    fields the renderer reads, with media by identity: a web link without its
    signature, a file on this machine by its bytes;
  * the shots the renderer borrows from other scenes for those frames: an
    animation's or a picture's backdrop (the nearest real shot), the next
    scene's transition, a pack transition laid over a nearby cut;
  * every overlay on screen in or near the frames (a full-screen graphic moves
    the clip under it a few frames before and after itself), and the pictures
    an image look borrows (the scene it starts on and its neighbours, the
    scenes it names in mediaFrom, the stills that follow it);
  * the subtitles when they are on (the cues are set over the whole
    narration), the grade with its frozen median tone, the film look, the
    brand kit, the frame size and rate;
  * the renderer itself (render.renderer_fingerprint) and every encoder
    setting (render.encoder_settings): a cached chunk always joins the new
    ones without re-encoding.
A field is left out only when the renderer never reads it (SCENE_NOT_DRAWN,
MEDIA_NOT_DRAWN; tests/test_render_cache.py checks that against remotion/src).
Anything unknown counts: a false miss only costs a render, a false hit would
show the wrong picture.

The sound (audio_hash) is everything audible: the narration (the polished file
by its bytes), music, beds, sound effects, the looks' and transitions' own
sounds. A re-render whose sound did not change reuses the whole mix; one whose
sound changed draws it again, whole, from the timeline (render.render, WAV).

Storage (R2_BUCKET, never under projects/): RENDER_CACHE_PREFIX/<scope>/
  c-<hash>.mp4   a chunk's picture (H.264, exactly its frames)
  a-<hash>.flac  the whole sound mix before loudness
The scope is the project id (or a job's render_cache_scope). Entries expire
by age: an R2 lifecycle rule on the prefix, or cleanup() - which only ever
deletes under RENDER_CACHE_PREFIX and refreshes nothing a render used
(touch()). docs/render-cache.md has both.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import brandkit, config, r2, templates
from . import render as renderer

HASH_VERSION = 2

# Scene and media fields the renderer never reads (remotion/src): an editor's
# or the sourcing's notes. Everything else of a scene counts.
SCENE_NOT_DRAWN = frozenset({"semanticMetadata", "query", "reviewRequired", "reviewReason", "visualTreatment",
                             "visualType", "wantedPictures", "alternatives", "choices",
                             # The words only set the subtitles (the caption context counts them when they
                             # are on) and the beds' ducking (the sound).
                             "words"})
MEDIA_NOT_DRAWN = frozenset({"attribution", "license", "contentDescription", "qualityScore", "relevanceScore",
                             "previewUrl", "storage", "sourceStart", "sourceEnd"})
# Top-level fields that only make sound (audio_hash counts them) or are not the drawing at all.
AUDIO_ONLY = frozenset({"audio", "bgm", "music", "ambience", "sfx", "sfxEnabled", "sfxVolume", "lookSounds"})
NOT_DRAWN_TOP = frozenset({"meta", "schemaVersion"})
# Top-level fields that only change the picture (audio_hash leaves them out).
PICTURE_ONLY = frozenset({"grade", "look", "captions", "width", "height", "schemaVersion"})

# Main.tsx: a scene's crossfade into the next (CROSSFADE_FRAMES), image looks (PHOTO_CARDS, STILL_LOOKS,
# PICTURE_NEAR, up to six stills of the scenes that follow). tests/test_render_cache.py keeps them equal.
CROSSFADE_FRAMES = 15
PHOTO_CARDS = frozenset({"photo-card", "name-card"})
STILL_LOOKS = frozenset({"board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"})
PICTURE_NEAR = 8
FOLLOWING_STILLS = 6
# components/motion/stage.tsx: a full-screen graphic moves the clip under it STAGE_PRE frames before it and
# settles STAGE_POST after (30 fps frames, scaled by the real rate); the margin covers both.
STAGE_REACH_30FPS = 8
# A subtitle cue reaches this far (fanout.CAPTION_REACH_SECONDS: 7 s cue + 1.2 s band, and a margin).
CAPTION_REACH_SECONDS = 9.0

# Signed links: their signature changes on every signing, the file does not.
_SIGNED = re.compile(r"(?:^|&)(?:token|X-Amz-[A-Za-z-]+|Signature|Expires|Key-Pair-Id|sig|se|sp|sv|sr|st)=", re.I)


# --------------------------------------------------------------------------- identities

class _Files:
    """Content hashes of local files, computed once per file (size and mtime must not change)."""

    def __init__(self):
        self.seen: Dict[str, Tuple[int, int, str]] = {}
        self.lock = threading.Lock()

    def digest(self, path: str) -> str:
        try:
            st = os.stat(path)
        except OSError:
            return ""
        with self.lock:
            got = self.seen.get(path)
            if got and got[0] == st.st_size and got[1] == st.st_mtime_ns:
                return got[2]
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        d = h.hexdigest()[:24]
        with self.lock:
            self.seen[path] = (st.st_size, st.st_mtime_ns, d)
        return d


FILES = _Files()


def _local_path(v: str) -> str:
    """The file on this disk a string names (a path or a file:// link), else ""."""
    if not v or v.lower().startswith(("http://", "https://", "bgm://", "data:", "blob:")):
        return ""
    if v.lower().startswith("file://"):
        from urllib.request import url2pathname
        v = url2pathname(urllib.parse.urlparse(v).path)
    return v if len(v) < 1024 and os.path.isfile(v) else ""


def identity(v: Any) -> Any:
    """What a string stands for across renders: a signed link without its signature, a local file by its bytes."""
    if not isinstance(v, str):
        return v
    if v.startswith(("http://", "https://")):
        base, _, query = v.partition("?")
        return base if query and _SIGNED.search(query) else v
    path = _local_path(v)
    if path:
        d = FILES.digest(path)
        return f"file:{d}" if d else v
    return v


def _norm(node: Any) -> Any:
    """A copy with every string as its identity (signed links unsigned, local files as content hashes)."""
    if isinstance(node, dict):
        return {str(k): _norm(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_norm(v) for v in node]
    return identity(node)


def _digest(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
                        .encode("utf-8")).hexdigest()[:20]


def _still_of(m: Any) -> Optional[list]:
    """What an image look or a backdrop shows of a scene's media (Main.tsx stillOf): [type, picture]."""
    if not isinstance(m, dict) or not m.get("url"):
        return None
    if m.get("type") == "image":
        return ["image", identity(m["url"])]
    return ["thumb", identity(m.get("thumbnail"))] if m.get("thumbnail") else None


# --------------------------------------------------------------------------- the document, read once

class Doc:
    """One document's scenes, overlays and layout, prepared for hashing every chunk of it."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.fps = max(1, int(doc.get("fps") or 30))
        self.scenes: List[dict] = [s for s in doc.get("scenes") or [] if isinstance(s, dict)]
        self.overlays: List[dict] = [o for o in doc.get("overlays") or [] if isinstance(o, dict)]
        self.intro, self.body, self.outro, self.total = brandkit.layout(doc)
        n = len(self.scenes)
        self.start = [int(s.get("startFrame") or 0) for s in self.scenes]
        self.dur = [int(s.get("durationInFrames") or 0) for s in self.scenes]
        # The frames each scene really draws: its own, and a crossfade's tail under the next scene.
        self.span = []
        for i in range(n):
            nxt = self.scenes[i + 1] if i + 1 < n else {}
            ext = CROSSFADE_FRAMES if (nxt or {}).get("transition") == "crossfade" else 0
            self.span.append((self.start[i], self.start[i] + self.dur[i] - 1 + ext))
        self.by_id = {}
        for i, s in enumerate(self.scenes):
            self.by_id.setdefault(str(s.get("id")), i)
        self._drawn: Dict[int, dict] = {}
        self._backdrop: Dict[int, Optional[int]] = {}
        self.pack_spans = self._pack_spans()
        self.stage = int(round(STAGE_REACH_30FPS * self.fps / 30.0)) + 2

    # -- scenes
    def drawn(self, i: int) -> dict:
        """Scene i as the renderer reads it (SCENE_NOT_DRAWN, MEDIA_NOT_DRAWN left out), identities resolved."""
        if i not in self._drawn:
            sc = self.scenes[i]
            out = {k: v for k, v in sc.items() if k not in SCENE_NOT_DRAWN}
            m = sc.get("media")
            if isinstance(m, dict):
                out["media"] = {k: v for k, v in m.items() if k not in MEDIA_NOT_DRAWN}
            sub = (sc.get("semanticMetadata") or {}).get("subject") if isinstance(sc.get("semanticMetadata"),
                                                                                 dict) else None
            if sub:
                out["subject"] = sub            # read by image looks (Main.tsx lookPictures)
            self._drawn[i] = _norm(out)
        return self._drawn[i]

    def _real(self, j: int) -> bool:
        m = self.scenes[j].get("media") if 0 <= j < len(self.scenes) else None
        return isinstance(m, dict) and bool(m.get("url")) and m.get("type") in ("video", "image")

    def backdrop(self, i: int) -> Optional[int]:
        """The scene an animation's or a picture's backdrop comes from (Main.tsx backdrops): nearest real shot."""
        if i not in self._backdrop:
            pick = None
            for d in range(1, len(self.scenes)):
                if self._real(i - d):
                    pick = i - d
                    break
                if self._real(i + d):
                    pick = i + d
                    break
                if i - d < 0 and i + d >= len(self.scenes):
                    break
            self._backdrop[i] = pick
        return self._backdrop[i]

    def at(self, frame: int) -> int:
        """The scene a body frame falls in (Main.tsx scenes.find: the first in array order), -1 when none."""
        for i, (s0, d) in enumerate(zip(self.start, self.dur)):
            if s0 <= frame < s0 + d:
                return i
        return -1

    def _pack_spans(self) -> List[Tuple[int, int, int]]:
        """(scene index, first frame, last frame) of every pack transition clip (packLevels.ts packSpan)."""
        meta = _pack_meta()
        out = []
        for i, sc in enumerate(self.scenes):
            t = str(sc.get("transition") or "")
            if i == 0 or not t.startswith("pack:"):
                continue
            m = meta.get(t[5:])
            if m:
                same = abs(float(m.get("fps") or 0) - self.fps) < 1e-6
                lead = int(m.get("peakFrame") or 0) if same else int(round(float(m.get("peak") or 0) * self.fps))
                length = int(m.get("frames") or 1) if same else max(1, int(float(m.get("duration") or 0) * self.fps))
                a = self.start[i] - lead
                out.append((i, a, a + length - 1))
            else:                                   # an unknown clip: a generous two seconds either side
                out.append((i, self.start[i] - 2 * self.fps, self.start[i] + 2 * self.fps))
        return out


_PACK_META: Dict[str, dict] = {}


def _pack_meta() -> Dict[str, dict]:
    if not _PACK_META:
        path = os.path.join(config.REMOTION_DIR, "src", "data", "transitions_meta.json")
        try:
            with open(path, encoding="utf-8") as fh:
                _PACK_META.update((json.load(fh) or {}).get("transitions") or {})
        except (OSError, ValueError):
            pass
    return _PACK_META


# --------------------------------------------------------------------------- image looks

_SUBJECT_STOP = frozenset({"the", "and", "for", "with", "from", "this", "that", "its", "their", "over", "into",
                           "near", "about"})
PERSON_CUES = frozenset({"person", "person-full", "profile"})


def _subject_words(s: Any) -> set:
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(s or "").lower()) if w not in _SUBJECT_STOP}


def same_subject(a: Any, b: Any) -> bool:
    """Main.tsx sameSubject: most of the shorter subject's words are in the other."""
    wa, wb = _subject_words(a), _subject_words(b)
    if not wa or not wb:
        return False
    both = sum(1 for w in wa if w in wb)
    return both >= max(1, -(-3 * min(len(wa), len(wb)) // 5))


def _subject(sc: dict) -> Any:
    sem = sc.get("semanticMetadata")
    return sem.get("subject") if isinstance(sem, dict) else None


def look_pictures(d: "Doc", ov: dict) -> Optional[List[str]]:
    """
    The pictures an image look shows (Main.tsx lookPictures, ported line for line; tests/test_render_cache.py
    runs both on real timelines): its own (library ones last), those of the scenes it names (mediaFrom), and
    when those are too few the scene it starts on, the neighbours about the same subject and, for a look of
    several pictures, the stills that follow. None for a look that shows none. A retired or unknown look
    (its registry entry is not known here): None, and the caller counts every picture it could borrow.
    """
    t = templates.get(str(ov.get("template") or "")) if ov.get("template") else None
    defaults = (t or {}).get("defaults") or {}
    variant = str(ov.get("variant") or defaults.get("variant") or "")
    kind = str(ov.get("type") or (t or {}).get("component") or "")
    tags = list((t or {}).get("tags") or [])
    many = variant == "collage" or "stills" in tags
    if not many and not (kind in PHOTO_CARDS or variant in STILL_LOOKS or "still" in tags):
        return None
    person = kind == "name-card" or any(c in PERSON_CUES for c in (t or {}).get("cues") or [])
    raw: List[str] = []                         # the pictures as the renderer compares them (their raw links)
    out: List[str] = []                         # and as this hash counts them

    def add(m) -> None:
        if not isinstance(m, dict) or not m.get("url"):
            return
        url = m["url"] if m.get("type") == "image" else m.get("thumbnail")
        if url and url not in raw:
            raw.append(url)
            out.append(identity(url))
    own = [m for m in (ov.get("media") if isinstance(ov.get("media"), list) else []) if isinstance(m, dict)]
    for m in own:
        if m.get("source") != "library":
            add(m)
    for x in ov.get("mediaFrom") if isinstance(ov.get("mediaFrom"), list) else []:
        j = d.by_id.get(str(x))
        add(d.scenes[j].get("media") if j is not None else None)
    for m in own:
        if m.get("source") == "library":
            add(m)
    if not out or (many and len(out) < 2):
        at = d.at(int(ov.get("startFrame") or 0))
        if at >= 0:
            add(d.scenes[at].get("media"))
            subject = _subject(d.scenes[at])
            dist = 1
            while not person and dist <= PICTURE_NEAR and len(out) < (FOLLOWING_STILLS if many else 1):
                for j in (at - dist, at + dist):
                    if 0 <= j < len(d.scenes) and same_subject(subject, _subject(d.scenes[j])):
                        add(d.scenes[j].get("media"))
                dist += 1
            i = at + 1
            while many and i < len(d.scenes) and len(out) < FOLLOWING_STILLS:
                add(d.scenes[i].get("media"))
                i += 1
    return out[:FOLLOWING_STILLS if many else max(1, len(own))]


def _look_closure(d: Doc, ov: dict) -> dict:
    """
    What an overlay reads from other scenes: of the scene it starts on, its kind and what the worker found
    in its picture (media.focus: faces, logos, lettering - motion/avoid.ts) and its still (a blurred
    backdrop, an image look's fallback); and, for an image look, the pictures it shows (look_pictures). A look
    the registry does not know counts every picture it could borrow.
    """
    at = d.at(int(ov.get("startFrame") or 0))
    m = (d.scenes[at].get("media") if at >= 0 else None) or {}
    m = m if isinstance(m, dict) else {}
    out: Dict[str, Any] = {"at": at, "under": [m.get("type"), _norm(m.get("focus"))]}
    tid = str(ov.get("template") or "")
    tpl = templates.get(tid) if tid else None
    # A retired look is drawn as its replacement (legacyLooks.ts remapRetired), which is not known here.
    if not (tpl and tpl.get("retired") is True):
        pics = look_pictures(d, ov)
        if ov.get("backdrop") == "blur" or pics is not None:
            out["underStill"] = _still_of(m)
        if pics is not None:
            out["pictures"] = pics
        return out
    # Unknown or retired: everything lookPictures could reach.
    out["underStill"] = _still_of(m)
    names = [str(x) for x in ov.get("mediaFrom") or []] if isinstance(ov.get("mediaFrom"), list) else []
    out["from"] = [[x, _still_of((d.scenes[d.by_id[x]].get("media") if x in d.by_id else None))] for x in names]
    if at >= 0:
        out["near"] = [[j, _still_of(d.scenes[j].get("media")), _subject(d.scenes[j])]
                       for j in range(max(0, at - PICTURE_NEAR), min(len(d.scenes), at + PICTURE_NEAR + 1))]
        follow, seen = [], set()
        for j in range(at + 1, len(d.scenes)):
            s = _still_of(d.scenes[j].get("media"))
            follow.append([j, s])
            if s:
                seen.add(s[1])
            if len(seen) >= FOLLOWING_STILLS:
                break
        out["follow"] = follow
    return out


# --------------------------------------------------------------------------- the hashes

def _globals(doc: dict, skip: Iterable[str]) -> dict:
    """Every top-level field but the scene/overlay lists, the length and `skip`: an unknown one counts."""
    drop = set(skip) | {"scenes", "overlays", "durationInFrames"}
    return {k: _norm(v) for k, v in doc.items() if k not in drop}


def _caption_context(d: Doc, a: int, b: int) -> dict:
    """The subtitles on body frames a..b: cues are set over the whole narration (captionCues.ts buildCues is one
    dynamic programme, shot changes included), and placed clear of every graphic within a cue's reach."""
    words = [(w.get("text"), w.get("start"), w.get("end")) for sc in d.scenes for w in sc.get("words") or []
             if isinstance(w, dict)]
    shots = [(s.get("startFrame"), s.get("durationInFrames"), None if s.get("words") else s.get("text"))
             for s in d.scenes]
    reach = int(round(CAPTION_REACH_SECONDS * d.fps))
    near = [_norm(o) for o in d.overlays
            if int(o.get("startFrame") or 0) <= b + reach
            and int(o.get("startFrame") or 0) + int(o.get("durationInFrames") or 0) >= a - reach]
    rects = [[i, d.drawn(i).get("media", {}).get("focus") if isinstance(d.drawn(i).get("media"), dict) else None]
             for i in range(len(d.scenes)) if d.span[i][0] <= b + reach and d.span[i][1] >= a - reach]
    return {"words": _digest([words, shots]), "graphics": near, "scenes": rects}


def picture_hash(doc: dict, a: int, b: int, enc: Optional[dict] = None, prepared: Optional[Doc] = None) -> str:
    """
    The hash of everything that draws frames a..b (frames of the whole video, the brand intro and outro
    included) - see the module notes. Two renders whose chunk hashes match draw the same frames.
    """
    d = prepared or Doc(doc)
    enc = enc if enc is not None else renderer.encoder_settings()
    near_end = int(b) + 3 * d.fps >= d.intro + d.body - 1
    # The brand kit: its watermark, colours and type are on every frame; its intro and outro only on theirs.
    # The intro's length places every later frame; the video's own length matters near its end only (an
    # overlay or a pack clip running past the end is cut there, the outro starts there): a narration that
    # got longer or shorter at minute 15 leaves the chunks before it as they were.
    brand = doc.get("brand") if isinstance(doc.get("brand"), dict) else None
    glob = _globals(doc, AUDIO_ONLY | NOT_DRAWN_TOP | {"brand"})
    if brand is not None:
        glob["brand"] = _norm({k: v for k, v in brand.items() if k not in ("intro", "outro")})
    payload: Dict[str, Any] = {"v": HASH_VERSION, "enc": enc, "range": [int(a), int(b)], "intro": d.intro,
                               "globals": glob}
    if brand is not None and d.intro and int(a) < d.intro:
        payload["brandIntro"] = _norm(brand.get("intro"))
    if near_end:
        payload["end"] = [d.body, d.outro]
    if brand is not None and d.outro and int(b) >= d.intro + d.body:
        payload["brandOutro"] = _norm(brand.get("outro"))
    grade = doc.get("grade")
    if isinstance(grade, dict) and grade.get("preset") != "none" and not isinstance(grade.get("medians"), dict):
        # No frozen median: the renderer takes it from every scene's tone (Grade.tsx gradeStateFor).
        payload["tones"] = _digest([(s.get("media") or {}).get("tone") for s in d.scenes])
    ba, bb = int(a) - d.intro, int(b) - d.intro          # body frames
    if bb >= 0 and ba < d.body:
        lo, hi = max(0, ba), min(d.body - 1, bb)
        S = [i for i, (s0, s1) in enumerate(d.span) if s0 <= hi and s1 >= lo]
        payload["scenes"] = [[i, d.drawn(i)] for i in S]
        payload["next"] = [[i, (d.scenes[i + 1] or {}).get("transition")] for i in S if i + 1 < len(d.scenes)]
        # An animation draws the nearest real shot blurred behind it. (A picture's own backdrop is only its
        # fallback when the picture cannot be drawn at all - SceneClip's hold - and is left out: a swapped
        # neighbour would otherwise re-render every chunk with a still beside it.)
        back = []
        for i in S:
            if (d.scenes[i].get("media") or {}).get("type") == "animation":
                j = d.backdrop(i)
                back.append([i, j, _still_of(d.scenes[j].get("media")) if j is not None else None])
        payload["backdrops"] = back
        payload["packs"] = [[i, d.scenes[i].get("transition"), s0] for i, s0, s1 in d.pack_spans
                            if s0 <= hi and s1 >= lo]
        m = d.stage
        O = [k for k, o in enumerate(d.overlays)
             if int(o.get("startFrame") or 0) - m <= hi
             and int(o.get("startFrame") or 0) + int(o.get("durationInFrames") or 0) - 1 + m >= lo]
        payload["overlays"] = [[k, _norm(d.overlays[k]), _look_closure(d, d.overlays[k])] for k in O]
        # A look that runs past the video's end is drawn shorter (Main.tsx clamps its Sequence, and its
        # motion follows its own length): the length counts for all of its frames.
        if any(int(d.overlays[k].get("startFrame") or 0) + int(d.overlays[k].get("durationInFrames") or 0)
               > d.body for k in O):
            payload["end"] = [d.body, d.outro]
        caps = doc.get("captions")
        if isinstance(caps, dict) and caps.get("enabled"):
            payload["captionContext"] = _caption_context(d, lo, hi)
    if d.outro and int(b) >= d.intro + d.body and d.scenes:
        # An end card shows the last scene's still (Main.tsx lastStill).
        payload["lastStill"] = _still_of(d.scenes[-1].get("media"))
    return _digest(payload)


def audio_hash(doc: dict) -> str:
    """The hash of everything audible: a re-render whose sound did not change reuses the whole mix."""
    d = Doc(doc)
    scenes = []
    for s in d.scenes:
        m = s.get("media") if isinstance(s.get("media"), dict) else {}
        scenes.append([s.get("id"), s.get("startFrame"), s.get("durationInFrames"), s.get("text"),
                       [(w.get("text"), w.get("start"), w.get("end")) for w in s.get("words") or []
                        if isinstance(w, dict)],
                       s.get("transition"), s.get("transitionGain"), m.get("type"), _norm(s.get("animation"))])
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    payload = {"v": HASH_VERSION, "renderer": renderer.renderer_fingerprint(), "fps": d.fps,
               "layout": [d.intro, d.body, d.outro], "globals": _globals(doc, PICTURE_ONLY | NOT_DRAWN_TOP),
               "voiceLufs": meta.get("voiceLufs"), "overlays": _norm(d.overlays), "scenes": scenes}
    return _digest(payload)


# --------------------------------------------------------------------------- chunk boundaries

def chunk_frames(doc: dict) -> int:
    """
    A chunk's planned length in frames: POD_RENDER_CHUNK_SECONDS of the video, never under
    POD_RENDER_MIN_CHUNK_FRAMES. Only the timeline decides it - never the machine (its CPUs, its
    concurrency): a re-render on another kind of machine must cut the video exactly as the last one did.
    """
    fps = max(1, int(doc.get("fps") or 30))
    want = int(round(float(config.POD_RENDER_CHUNK_SECONDS) * fps))
    return max(1, int(config.POD_RENDER_MIN_CHUNK_FRAMES), want)


def stable_chunks(doc: dict, target: int, min_frames: int = 1) -> List[Tuple[int, int]]:
    """
    Inclusive frame ranges covering the whole video (brand intro and outro included), chosen left to
    right: each next chunk starts on the cleanest scene cut (fanout.chunk_cuts: clean, then without a
    transition across it, then any scene start) nearest to `target` frames after the last start, within
    a quarter of it (then half); with no scene start that near, on the exact frame. A last chunk shorter
    than half a chunk joins the one before it. Each boundary depends only on the cuts near it: an edit
    never moves a boundary before it (fanout.plan_chunks evened its chunks over the whole length, so a
    one-frame change at the end moved every boundary).
    """
    from . import fanout
    if int(doc.get("durationInFrames") or 0) <= 0:
        return []
    intro, body, outro, total = brandkit.layout(doc)
    target = max(1, int(target))
    min_frames = max(1, min(int(min_frames or 1), target))
    if total <= int(target * 1.25):
        return [(0, total - 1)]
    tiers = fanout.chunk_cuts(doc)
    inside = [(0, intro), (intro + body, total)]          # (x, y): x < f < y is inside a brand clip
    bounds = [0]
    pos = 0
    while total - pos > target * 1.25:
        ideal = pos + target
        top = total - min_frames
        pick = None
        for lo, hi in ((pos + int(target * 0.75), pos + int(target * 1.25)),
                       (pos + int(target * 0.5), pos + int(target * 1.5))):
            lo, hi = max(lo, pos + min_frames), min(hi, top)
            if hi < lo:
                continue
            for tier in tiers:
                near = [f for f in tier if lo <= f <= hi]
                if near:
                    pick = min(near, key=lambda f: (abs(f - ideal), f))
                    break
            if pick is not None:
                break
        if pick is None:
            pick = min(max(ideal, pos + min_frames), top)
            for x, y in inside:
                if x < pick < y:
                    for edge in sorted((x, y), key=lambda e: abs(e - pick)):
                        if pos + min_frames <= edge <= top:
                            pick = edge
                            break
        if pick <= pos:
            break
        bounds.append(pick)
        pos = pick
    ranges = [(x, y - 1) for x, y in zip(bounds, bounds[1:] + [total])]
    if len(ranges) > 1 and ranges[-1][1] - ranges[-1][0] + 1 < max(min_frames, target // 2):
        ranges[-2:] = [(ranges[-2][0], total - 1)]
    return ranges


# --------------------------------------------------------------------------- the store

def _safe(scope: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(scope or ""))[:80].strip("_")


def mode_of(value: Any) -> str:
    """A job's render_cache: "on" (reuse and keep), "refresh" (draw everything, keep it), "off" (neither)."""
    v = str(value or "on").strip().lower()
    return v if v in ("on", "refresh", "off") else "on"


class Cache:
    """One scope's chunks and sound mixes in R2 (RENDER_CACHE_PREFIX/<scope>/)."""

    def __init__(self, scope: str, mode: str = "on"):
        self.scope = _safe(scope)
        self.mode = mode_of(mode)
        root = str(getattr(config, "RENDER_CACHE_PREFIX", "") or "render-cache/v1/").strip("/")
        self.prefix = f"{root}/{self.scope}/"
        self._listing: Optional[Dict[str, int]] = None
        self.lock = threading.Lock()

    @property
    def usable(self) -> bool:
        return bool(self.scope) and self.mode != "off" and r2.enabled()

    def chunk_key(self, h: str) -> str:
        return f"{self.prefix}c-{h}.mp4"

    def audio_key(self, h: str) -> str:
        return f"{self.prefix}a-{h}.flac"

    def listing(self) -> Dict[str, int]:
        """{key: size} of what this scope holds (one listing per render); {} when it cannot be read."""
        with self.lock:
            if self._listing is None:
                try:
                    self._listing = {o["key"]: int(o.get("size") or 0) for o in r2.list_keys(self.prefix)
                                     if str(o.get("key") or "").startswith(self.prefix)}
                except Exception as e:  # noqa: BLE001 - nothing reused, everything drawn
                    print(f"[render-cache] cannot list {self.prefix}: {type(e).__name__}: {str(e)[:120]}",
                          flush=True)
                    self._listing = {}
            return dict(self._listing)

    def has(self, key: str) -> bool:
        """`key` may be reused: it is there (and this render may read the cache at all)."""
        return self.usable and self.mode == "on" and self.listing().get(key, 0) > 0

    def get(self, key: str, path: str) -> bool:
        from . import fanout
        try:
            fanout._fetch("", path, key=key, tries=3)
            return os.path.isfile(path) and os.path.getsize(path) > 0
        except Exception as e:  # noqa: BLE001 - drawn instead
            print(f"[render-cache] {key}: not read ({type(e).__name__}: {str(e)[:120]})", flush=True)
            return False

    def put(self, path: str, key: str) -> bool:
        if not self.usable or not os.path.isfile(path):
            return False
        try:
            r2.upload(path, key, content_type=r2.content_type(path) if not path.endswith(".flac") else "audio/flac",
                      deadline=time.time() + 300, cache_control="no-store")
            with self.lock:
                if self._listing is not None:
                    self._listing[key] = os.path.getsize(path)
            return True
        except Exception as e:  # noqa: BLE001 - only the next reuse is lost
            print(f"[render-cache] {key}: not kept ({type(e).__name__}: {str(e)[:120]})", flush=True)
            return False

    def copy_in(self, src_key: str, key: str) -> bool:
        """A chunk a worker already put in R2 kept under its hash: copied inside R2, nothing downloaded."""
        if not self.usable:
            return False
        try:
            r2.copy(src_key, key)
            return True
        except Exception as e:  # noqa: BLE001 - only the next reuse is lost
            print(f"[render-cache] {key}: not kept ({type(e).__name__}: {str(e)[:120]})", flush=True)
            return False

    def touch(self, key: str) -> None:
        """A reused entry starts its age again: age-based expiry never takes what renders keep using."""
        try:
            r2.copy(key, key, replace_metadata=True)
        except Exception:  # noqa: BLE001 - it only expires sooner
            pass


def cleanup(days: float = None, scope: str = "", dry_run: bool = True, now: Optional[float] = None) -> dict:
    """
    Delete cache entries older than `days` (RENDER_CACHE_KEEP_DAYS): every scope, or one. Only keys under
    RENDER_CACHE_PREFIX are ever listed or deleted - never a project's media or a finished video. A dry run
    (the default) only counts. Returns {"listed", "old", "deleted", "bytes", "prefix"}.
    """
    days = float(config.RENDER_CACHE_KEEP_DAYS if days is None else days)
    root = str(getattr(config, "RENDER_CACHE_PREFIX", "") or "render-cache/v1/").strip("/") + "/"
    prefix = root + (f"{_safe(scope)}/" if scope else "")
    if not prefix.startswith("render-cache/") or len(prefix) < len("render-cache/"):
        raise ValueError(f"refusing to clean {prefix!r}: not a render cache prefix")
    cutoff = (now if now is not None else time.time()) - days * 86400.0
    listed = r2.list_keys(prefix)
    old = []
    total = 0
    for o in listed:
        key = str(o.get("key") or "")
        when = _epoch(o.get("modified"))
        if key.startswith(prefix) and when is not None and when < cutoff:
            old.append(key)
            total += int(o.get("size") or 0)
    deleted = 0
    if not dry_run:
        for key in old:
            if key.startswith(root) and r2.delete(key):
                deleted += 1
    return {"prefix": prefix, "listed": len(listed), "old": len(old), "deleted": deleted, "bytes": total,
            "days": days, "dryRun": bool(dry_run)}


def _epoch(stamp: Any) -> Optional[float]:
    if not stamp:
        return None
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --------------------------------------------------------------------------- what the app is shown

def _fnv(text: str) -> str:
    """FNV-1a 32-bit as 8 hex digits: the app computes the same over the same text (renderEstimate.ts)."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def scene_sig(sc: dict) -> str:
    """A scene as the editor changes it: start, length, shot, transition, motion, effect, treatment, frame."""
    m = sc.get("media") if isinstance(sc.get("media"), dict) else {}
    url = str(m.get("url") or "")
    if url.startswith(("http://", "https://")):
        url = url.split("?", 1)[0]
    parts = [sc.get("startFrame"), sc.get("durationInFrames"), m.get("type"), url, sc.get("transition"),
             sc.get("motion"), sc.get("effect"), sc.get("treatment"), sc.get("frame"), sc.get("text")]
    return _fnv("|".join("" if p is None else str(p) for p in parts))


def overlay_sig(o: dict) -> str:
    """An overlay as the editor changes it: start, length, look and words."""
    parts = [o.get("startFrame"), o.get("durationInFrames"), o.get("template"), o.get("type"), o.get("variant"),
             o.get("text"), o.get("subtitle"), o.get("label"), o.get("value")]
    return _fnv("|".join("" if p is None else str(p) for p in parts))


def app_signatures(doc: dict) -> dict:
    """Per-scene and per-overlay signatures for the app's re-render estimate (no hash the app cannot repeat)."""
    return {"scenes": [scene_sig(s) for s in doc.get("scenes") or [] if isinstance(s, dict)],
            "overlays": [[int(o.get("startFrame") or 0), int(o.get("durationInFrames") or 0), overlay_sig(o)]
                         for o in doc.get("overlays") or [] if isinstance(o, dict)]}


# The settings every frame depends on: when one changed since the last render, the editor estimates a full one.
APP_GLOBALS = ("fps", "width", "height", "grade", "captions", "look", "overlaysEnabled")


def manifest_for_app(manifest: Optional[dict], sent: Optional[dict]) -> Optional[dict]:
    """
    A render's manifest with what the editor compares a later timeline against: the signatures and the
    frame-wide settings of the timeline AS THE APP SENT IT (the render's own copy has local stills and
    repairs the editor never sees). The grade's frozen median is the render's, never the editor's.
    """
    if not isinstance(manifest, dict) or not isinstance(sent, dict):
        return manifest
    out = dict(manifest)
    try:
        out["sig"] = app_signatures(sent)
        glob = {k: sent.get(k) for k in APP_GLOBALS if k in sent}
        if isinstance(glob.get("grade"), dict):
            glob["grade"] = {k: v for k, v in glob["grade"].items() if k != "medians"}
        out["globals"] = glob
    except Exception:  # noqa: BLE001 - the estimate is only a hint
        pass
    return out
