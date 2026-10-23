"""
The spare bank: real footage this job already downloaded and the vision judge
already looked at, kept for the lines nothing else fills (2026-10-23).

The Mount Rainier news compilation (project b6cef117, 2026-10-23) downloaded
607 YouTube sections and judged ~310 of them, showed 50, and still left 155
of its 235 lines empty after sourcing - the ladder's "moment" rung filled one,
the rest became held shots, stretched shots and text cards. Most of the clips
the judge turned down were clean, real footage of the story's places (a drone
shot of Mount Rainier, an Orting street, the Puyallup River) that only missed
the ONE line they were searched for. A news compilation shows exactly that
footage under its other lines.

So every candidate the paid judge answered for is offered here unless its
answer rules it out for every line (another channel's text or watermark, an
AI-made picture, too poor to show, a studio or a talking head - what
media.judged_line_free and the slop filters already say). The file is kept
under a hard link (the caller deletes its own name as before), with what the
judge saw. The ladder (gapfill._from_spare) asks this bank first for an empty
line: the spares whose description shares the line's words, the line's own
place and subject words counting double, each judged again against the new
line before it is placed - one cheap vision call on a file already on disk,
no search, no download, no proxy.

Variety stays the ladder's (gapfill.Used: never the same moment, the same
source video only FALLBACK_MOMENT_GAP_SECONDS from its other moments and never
on the next scene; media.may_place with FILL_MAX_MOMENTS_PER_VIDEO), plus a
near-duplicate frame check against the shots around the line (near_duplicate).
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional

from . import config

_LOCK = threading.Lock()
# key -> entry. A key is the clip's "yt:<id>@<start rounded to 1 s>" or the picture's link.
_BANK: Dict[str, dict] = {}
# Lines (by job index) a spare was already judged against and turned down for: never asked twice.
_TRIED: Dict[str, set] = {}
_TAKEN: set = set()
STATS: Dict[str, Any] = {"banked": 0, "clips": 0, "pictures": 0, "skipped": {}, "offered": 0, "judged": 0,
                         "filled": 0, "turnedDown": 0, "nearDuplicate": 0, "tooShort": 0}

_YT_NAME = re.compile(r"^yt_([\w-]{11})_(\d+)_(\d+)_[^_]+(?:_c(\d+))?\.\w+$")
_STILL_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")
_STOP = set("""
a an the and or but of to in on at by for from with without into onto over under about above below near
this that these those it its it's is are was were be been being has have had do does did not no nor so as
than then there here their they them he she his her we our you your i me my who whom whose which what when
where why how all any both each few more most other some such only own same very can will just should now
shows show showing shown view seen frames frame shot shots footage video clip image picture photo photograph
wide close aerial background foreground distance visible appears across along around while one two three
scene line story real camera sky blue green white grey gray large small several many few people person
""".split())


def enabled() -> bool:
    return bool(getattr(config, "SPARE_BANK", True))


def reset() -> None:
    with _LOCK:
        _BANK.clear()
        _TRIED.clear()
        _TAKEN.clear()
        STATS.update(banked=0, clips=0, pictures=0, skipped={}, offered=0, judged=0, filled=0, turnedDown=0,
                     nearDuplicate=0, tooShort=0)


def stats() -> dict:
    with _LOCK:
        out = dict(STATS, skipped=dict(STATS["skipped"]))
        out["left"] = sum(1 for k in _BANK if k not in _TAKEN)
    return out


def _skip(why: str) -> None:
    with _LOCK:
        STATS["skipped"][why] = STATS["skipped"].get(why, 0) + 1


def words(*texts: str) -> set:
    """The content words of some text, lower case, a plural's s dropped."""
    out = set()
    for t in texts:
        for w in re.findall(r"[a-z][a-z'\-]{2,}", str(t or "").lower()):
            w = w.strip("'-")
            if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
                w = w[:-1]
            if len(w) >= 3 and w not in _STOP:
                out.add(w)
    return out


def youtube_origin(path: str) -> tuple:
    """(video id, start second) of a downloaded YouTube section by its file name, ("", None) when not one."""
    m = _YT_NAME.match(os.path.basename(path or ""))
    if not m:
        return "", None
    start = int(m.group(2)) / 1000.0 + (int(m.group(4)) / 10.0 if m.group(4) else 0.0)
    return m.group(1), round(start, 2)


def _in_bank(path: str) -> bool:
    return os.sep + "_spare" + os.sep in os.path.abspath(path or "") or "/_spare/" in str(path or "")


def _keep_file(path: str) -> str:
    """A second name for the file in a _spare folder beside it (a hard link, else a copy); "" on failure."""
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), "_spare")
    try:
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, os.path.basename(path))
        if os.path.exists(dest):
            return dest
        try:
            os.link(path, dest)
        except OSError:
            shutil.copy2(path, dest)
        return dest
    except OSError:
        return ""


def line_free_flaw(verdict: Optional[dict]) -> str:
    """Why the judge's answer rules a candidate out for EVERY line ("" = only for the line it was searched for)."""
    if not verdict:
        return "no verdict"
    if verdict.get("has_text_or_watermark"):
        return "text or watermark"
    if verdict.get("ai_generated"):
        return "AI-made"
    if verdict.get("studio") or verdict.get("is_talking_head"):
        return "a studio or talking head"
    if verdict.get("music_or_vice"):
        return "a music, club or smoking scene"
    q = verdict.get("quality")
    if q is not None and float(q) < max(float(getattr(config, "VISION_MIN_QUALITY", 0.0) or 0.0),
                                        float(getattr(config, "SPARE_MIN_QUALITY", 0.45) or 0.0)):
        return "too poor"
    if verdict.get("off_topic"):
        return "off the story"
    return ""


def record(path: str, verdict: Optional[dict], label: str = "", source_url: str = "", kept: bool = False) -> bool:
    """
    Offer one judged candidate to the bank (media._vision_gate, after the judge answered). True when banked.
    A YouTube section is known by its file name, a picture by its link; anything else is not banked.
    """
    if not enabled() or not path or not os.path.isfile(path) or _in_bank(path):
        return False
    why = line_free_flaw(verdict)
    if why:
        _skip(why)
        return False
    is_still = os.path.splitext(path)[1].lower() in _STILL_EXT
    if is_still:
        if not str(source_url or "").startswith("http"):
            _skip("a picture without its link")
            return False
        key, vid, start, kind = str(source_url), "", None, "image"
    else:
        vid, start = youtube_origin(path)
        if not vid:
            _skip("not a YouTube section")
            return False
        key, kind = f"yt:{vid}@{int(round(start or 0.0))}", "video"
    cap = int(getattr(config, "SPARE_MAX", 600) or 0)
    with _LOCK:
        if key in _BANK:
            return False
        if cap and len(_BANK) >= cap:
            STATS["skipped"]["bank full"] = STATS["skipped"].get("bank full", 0) + 1
            return False
    try:
        if os.path.getsize(path) > int(getattr(config, "SPARE_MAX_BYTES", 80_000_000) or 0) > 0:
            _skip("too big")
            return False
    except OSError:
        return False
    kept_path = _keep_file(path)
    if not kept_path:
        _skip("could not keep the file")
        return False
    title = re.sub(r"^YouTube:\s*", "", str(label or ""))
    desc = str((verdict or {}).get("description") or "")
    entry = {"key": key, "kind": kind, "path": kept_path, "vid": vid, "start": start,
             "url": (f"https://www.youtube.com/watch?v={vid}&t={int(start or 0)}" if vid else str(source_url)),
             "title": title[:200], "description": desc[:400], "words": words(desc, title),
             "quality": (verdict or {}).get("quality"), "score": (verdict or {}).get("score"), "kept": bool(kept)}
    with _LOCK:
        if key in _BANK:
            return False
        _BANK[key] = entry
        STATS["banked"] += 1
        STATS["clips" if kind == "video" else "pictures"] += 1
    return True


def line_words(job: dict) -> tuple:
    """(all the line's words, its place and subject words) - what a spare's description is matched on."""
    named = words(job.get("subject") or "", job.get("place") or "")
    si = job.get("scene_intent") if isinstance(job.get("scene_intent"), dict) else {}
    named |= words(" ".join(str(x) for x in (si.get("locations") or []) if x))
    allw = words(job.get("intent") or "", job.get("context") or "", job.get("query") or "",
                 " ".join(str(x) for x in (job.get("fallbacks") or [])[:3])) | named
    return allw, named


def match(entry: dict, allw: set, named: set) -> float:
    """How well a spare's description and title share the line's words (its place and subject words count double)."""
    have = entry.get("words") or set()
    shared = have & allw
    return float(len(shared) + len(have & named))


def candidates(job: dict, kind: str = "video", limit: int = 6) -> List[dict]:
    """The bank's spares for one line, best match first: not taken, not already turned down for this line, at least
    SPARE_MIN_MATCH shared words (one place/subject word and one more, or three of the line's words)."""
    if not enabled():
        return []
    allw, named = line_words(job)
    if not allw:
        return []
    floor = float(getattr(config, "SPARE_MIN_MATCH", 3.0) or 0.0)
    me = str(job.get("index"))
    with _LOCK:
        pool = [e for k, e in _BANK.items() if e["kind"] == kind and k not in _TAKEN
                and me not in _TRIED.get(k, set())]
    scored = sorted(((match(e, allw, named), e) for e in pool), key=lambda t: (-t[0], -(t[1].get("score") or 0.0)))
    return [dict(e, match=s) for s, e in scored if s >= floor][:max(0, int(limit))]


def take(entry: dict) -> bool:
    with _LOCK:
        if entry["key"] in _TAKEN or entry["key"] not in _BANK:
            return False
        _TAKEN.add(entry["key"])
        return True


def give_back(entry: dict, job_index: Optional[int] = None) -> None:
    """Put a spare back (its checks or the judge turned it down for this line: never offered to that line again)."""
    with _LOCK:
        _TAKEN.discard(entry["key"])
        if job_index is not None:
            _TRIED.setdefault(entry["key"], set()).add(str(job_index))


def note(what: str, n: int = 1) -> None:
    with _LOCK:
        STATS[what] = STATS.get(what, 0) + n


# --------------------------------------------------------------------------- #
# Near-duplicate frames
# --------------------------------------------------------------------------- #

_HASHES: Dict[str, Optional[int]] = {}


def dhash(path: str) -> Optional[int]:
    """A 64-bit difference hash of a clip's or picture's middle frame (9x8 grey), None when unreadable."""
    if not path or not os.path.isfile(path):
        return None
    with _LOCK:
        if path in _HASHES:
            return _HASHES[path]
    got = None
    try:
        from .filters import _gray_frames
        frames = _gray_frames(path, 1, 9, 8) if os.path.splitext(path)[1].lower() in _STILL_EXT \
            else _gray_frames(path, 3, 9, 8)
        if frames:
            f = frames[len(frames) // 2].astype("int16")
            bits = (f[:, 1:] > f[:, :-1]).flatten()
            got = 0
            for b in bits:
                got = (got << 1) | int(bool(b))
    except Exception:  # noqa: BLE001 - unmeasured is not a duplicate
        got = None
    with _LOCK:
        if len(_HASHES) > 5000:
            _HASHES.clear()
        _HASHES[path] = got
    return got


def near_duplicate(path: str, others: Iterable[str], bits: Optional[int] = None) -> bool:
    """The file's middle frame within `bits` (SPARE_DUPLICATE_BITS, 10 of 64) of any of `others`' middle frames:
    on screen the same picture again (two moments of one drone shot, one photo re-cropped by another site)."""
    limit = int(getattr(config, "SPARE_DUPLICATE_BITS", 10) if bits is None else bits)
    if limit < 0:
        return False
    mine = dhash(path)
    if mine is None:
        return False
    for o in others:
        if not o or o == path:
            continue
        theirs = dhash(o)
        if theirs is not None and bin(mine ^ theirs).count("1") <= limit:
            return True
    return False


def source_name(url: str) -> str:
    """The `source` a banked picture is placed under (its host decides wikimedia, else a web picture)."""
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return "wikimedia" if "wikimedia" in host or "wikipedia" in host else "web_image"
