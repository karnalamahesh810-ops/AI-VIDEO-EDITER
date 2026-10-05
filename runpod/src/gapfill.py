"""
Every scene filled, nothing shown twice (the owner's rules, 2026-10-01).

The owner's 159-scene Lake Powell video (a pod job, SOURCE_BUDGET_MAX_SECONDS
2400) spent its whole 40-minute sourcing budget. 47 scenes were then filled
by REUSING clips already shown (each twice, 13-136 scenes apart) and 23
scenes were left empty - all of them the last 23 in story order, because
per-scene sourcing started its scenes in story order and the budget ran out
before the ending was reached. His rules: never reuse a clip within a video,
never leave a scene empty, every clip must fit its own line.

  coverage_order   the order per-scene sourcing starts its scenes in: the
                   hook first (it keeps its priority), then the rest spread
                   across the whole video (bit-reversed order), so what is
                   left when the budget runs out is scattered, never the end;
  Used             what the video already shows - files, asset ids, and per
                   source video its moments and scenes - and whether one more
                   shot may join: never the same file, asset or moment; the
                   same source video only FALLBACK_MOMENT_GAP_SECONDS from
                   its other moments and never on the next scene;
  fill_empty       the fast ladder for scenes still empty when the budget is
                   gone, cheapest first - (pack) a clip from the niche packs
                   (src/packs.py) whose picture fits the line: already cut,
                   checked and on R2, no search, no vision call; (a) the clip
                   library's unused clips of the line's subject or place,
                   (b) the subject pools' unused approved moments, (c) one
                   web/Wikimedia picture search for the subject (an AI image
                   only when the job allows one) - each through the gates
                   already in place (the library's and the pools' slop
                   checks, the vision judge), under its own short time box;
  hold_or_animate  (d) the last resort: the planner's own number/map graphic
                   for the line, else the neighbouring shot held over it (the
                   scenes merge) while the clip still covers the longer scene;
                   in the hook only when nothing else is left;
  find_repeats /   the check before the timeline goes to the editor or the
  final_check      render: a scene repeating an earlier scene's file, asset or
                   moment gets a fresh shot through the same ladder.
"""
from __future__ import annotations

import contextvars
import dataclasses
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import config, ytdlp

# Pictures tried per search in the ladder's picture rung (it was 6; most of the
# Mount Rainier video's first six came from sites that refuse downloads).
STILL_TRIES = 10
# Picture links a scene's rung found but could not download (scene index ->
# [{url, title, page}]): kept on the scene (media.wantedPictures) so the
# editor can show them and the owner can fetch one himself (the owner,
# 2026-10-02: "add links of that image to our tool if this fails").
_WANTED: Dict[int, List[dict]] = {}
_WANTED_LOCK = threading.Lock()


def _note_wanted(i: int, cand) -> None:
    with _WANTED_LOCK:
        rows = _WANTED.setdefault(i, [])
        if len(rows) < 3 and all(r["url"] != cand.url for r in rows):
            rows.append({"url": cand.url, "title": (cand.attribution or "")[:120],
                         "page": getattr(cand, "page_url", "") or ""})


def wanted_pictures(i: int) -> List[dict]:
    with _WANTED_LOCK:
        return list(_WANTED.get(i, []))

_YT_ID = re.compile(r"yt:([\w-]{11})")
_WATCH = re.compile(r"[?&]v=([\w-]{11})")
# A niche pack clip (src/packs.py): "pack:<niche>:<source>@<start second>". Every clip cut from
# one source video shares "pack:<niche>:<source>" and is a moment of it, like a YouTube video's.
_PACK = re.compile(r"^(pack:[a-z0-9_]+:.+)@\d+$")
_T = re.compile(r"[?&]t=(\d+(?:\.\d+)?)")
_SCENE_ID = re.compile(r"^s(\d+)$")

# What the last fallback passes of this job did, for the job result and log.
LAST: Dict[str, Any] = {}
# The plan this job made (handler.do_plan): its lines by index, the clip
# library and the flags, so the final check can run the same ladder. Empty
# until a plan runs in this job (reset by the handler for every job).
CONTEXT: Dict[str, Any] = {}


def reset() -> None:
    with _WANTED_LOCK:
        _WANTED.clear()
    LAST.clear()
    CONTEXT.clear()


def remember(jobs: List[dict], work: str, *, library=None, require_cc: bool = False,
             youtube_only: bool = False) -> None:
    """The plan's lines and switches, for final_check (handler, before publishing)."""
    CONTEXT.clear()
    CONTEXT.update(jobs={j["index"]: dict(j) for j in jobs or []}, work=work, library=library,
                   require_cc=bool(require_cc), youtube_only=bool(youtube_only))


# --------------------------------------------------------------------------- #
# Coverage order
# --------------------------------------------------------------------------- #

def spread(n: int) -> List[int]:
    """
    0..n-1 in an order whose every prefix covers the whole range (van der
    Corput / bit reversal): 0, n/2, n/4, 3n/4, ... A pass cut off anywhere has
    touched the start, the middle and the end alike.
    """
    if n <= 0:
        return []
    bits = max(1, (n - 1).bit_length())

    def rev(k: int) -> int:
        return int(format(k, f"0{bits}b")[::-1], 2)
    return sorted(range(n), key=rev)


def coverage_order(jobs: List[dict]) -> List[dict]:
    """The hook's lines first, in story order; then every other line spread over the video."""
    ordered = sorted(jobs or [], key=lambda j: j["index"])
    hook = [j for j in ordered if j.get("hook")]
    rest = [j for j in ordered if not j.get("hook")]
    return hook + [rest[k] for k in spread(len(rest))]


# --------------------------------------------------------------------------- #
# What the video already shows
# --------------------------------------------------------------------------- #

def _video_of(identity: str, url: str) -> str:
    m = _YT_ID.search(identity or "") or _WATCH.search(url or "")
    if m:
        return f"yt:{m.group(1)}"
    p = _PACK.match(identity or "")
    return p.group(1) if p else ""


def _start_from(moment: Any, url: str, path: str) -> Optional[float]:
    if isinstance(moment, dict) and isinstance(moment.get("start"), (int, float)) \
            and not isinstance(moment.get("start"), bool):
        return float(moment["start"])
    m = _T.search(url or "")
    if m:
        return float(m.group(1))
    name = os.path.basename(path or "")
    if name.startswith("yt_") and len(name) > 15:
        try:
            return int(name[15:].split("_")[0]) / 1000.0
        except ValueError:
            return None
    return None


def _files_of(*paths: str) -> List[str]:
    """A shot's own files: its local file and a real (http) link. A query text is not a file."""
    out = []
    for p in paths:
        p = str(p or "").strip()
        if not p:
            continue
        if p.startswith(("http://", "https://")):
            if _WATCH.search(p):
                continue                 # a YouTube page: its moment is checked, not the page
            out.append(p.split("#")[0])
        elif p.startswith("file://") or os.path.isabs(p) or os.sep in p or "/" in p:
            out.append(p)
    return out


@dataclasses.dataclass
class Shot:
    """What one scene shows, reduced to what repeats are judged on."""
    ident: str = ""                     # a non-YouTube asset's identity
    files: Tuple[str, ...] = ()
    video: str = ""                     # "yt:<id>" for every moment of a YouTube video
    start: Optional[float] = None       # where in that video
    at: Optional[float] = None          # where on the timeline
    chain: bool = False                 # the planned next moment of the line before's clip

    @classmethod
    def of_asset(cls, a, at: Optional[float] = None) -> "Shot":
        ident = getattr(a, "identity", "") or ""
        url, path = getattr(a, "url", "") or "", getattr(a, "local_path", "") or ""
        moment = getattr(a, "moment", None)
        video = _video_of(ident, url) if getattr(a, "kind", "") == "video" else ""
        return cls(ident="" if video else ident, files=tuple(_files_of(path, url)), video=video,
                   start=_start_from(moment, url, path) if video else None, at=at,
                   chain=bool(isinstance(moment, dict) and moment.get("chain")))

    @classmethod
    def of_scene(cls, scene: dict, fps: int) -> Optional["Shot"]:
        if scene.get("teaser"):
            return None         # a cold-open flash (src/hookboost.py): the shot's own line is its use
        m = scene.get("media") or {}
        if m.get("type") not in ("video", "image") or not m.get("url"):
            return None
        sem = scene.get("semanticMetadata") or {}
        ident = str(sem.get("assetId") or "")
        src = str(sem.get("sourceUrl") or "")
        video = _video_of(ident, src) if m.get("type") == "video" else ""
        moment = sem.get("moment") if isinstance(sem.get("moment"), dict) else {}
        return cls(ident="" if video else ident, files=tuple(_files_of(m.get("url") or "")), video=video,
                   start=_start_from(moment, src, m.get("url") or "") if video else None,
                   at=int(scene.get("startFrame") or 0) / max(1, fps), chain=bool(moment.get("chain")))


class Used:
    """
    The shots a video shows, by scene, and whether another may join (why_not):
    never the same file or asset, never the same moment of a source video,
    and another moment of a video already shown only FALLBACK_MOMENT_GAP_SECONDS
    from each of its other moments and never on the next scene. A moment whose
    start is unknown counts as the same moment. claim() checks and records
    under one lock, so parallel fills cannot both take one shot.
    """

    def __init__(self, gap: Optional[float] = None):
        self.gap = config.FALLBACK_MOMENT_GAP_SECONDS if gap is None else float(gap)
        self.shots: Dict[int, List[Shot]] = {}
        self.lock = threading.Lock()

    @classmethod
    def of_results(cls, results, starts: Optional[Dict[int, float]] = None) -> "Used":
        u = cls()
        items = results.items() if isinstance(results, dict) else enumerate(results or [])
        for i, a in items:
            if a is not None:
                u.add(i, Shot.of_asset(a, (starts or {}).get(i)))
        return u

    def add(self, i: int, shot: Shot) -> None:
        self.shots.setdefault(i, []).append(shot)

    def release(self, i: int, shot: Shot) -> None:
        with self.lock:
            mine = self.shots.get(i) or []
            if shot in mine:
                mine.remove(shot)

    def why_not(self, i: int, shot: Shot) -> str:
        # A snapshot: parallel fills read this while another one claims.
        for j, theirs in list(self.shots.items()):
            if j == i:
                continue
            for o in list(theirs):
                if shot.ident and shot.ident == o.ident:
                    return "the same picture or clip as another scene"
                if set(shot.files) & set(o.files):
                    return "the same file as another scene"
                if not (shot.video and shot.video == o.video):
                    continue
                near = abs(i - j) <= 1
                if near and (shot.chain or o.chain):
                    continue            # a planned chain: the next moment of the clip before it
                if near:
                    return "the same source video on the next scene"
                if shot.start is None or o.start is None or abs(shot.start - o.start) < self.gap:
                    return "the same moment of its source video"
        return ""

    def claim(self, i: int, shot: Shot) -> bool:
        with self.lock:
            if self.why_not(i, shot):
                return False
            self.add(i, shot)
            return True

    def placed(self, video: str) -> List[Optional[float]]:
        """Timeline starts of the scenes cut from `video` (for media.may_place)."""
        with self.lock:
            return [s.at for shots in self.shots.values() for s in shots if s.video == video]


# --------------------------------------------------------------------------- #
# The ladder: (a) library, (b) the pools' spare moments, (c) one picture search
# --------------------------------------------------------------------------- #

def _at(results, i: int):
    if isinstance(results, dict):
        return results.get(i)
    return results[i] if 0 <= i < len(results) else None


def _scene_context(job: dict) -> list:
    """The scene's switches on this thread (the gates read them, as in media.judge_clip)."""
    from . import media
    return [(media._SUBJECT_TYPE, media._SUBJECT_TYPE.set(job.get("subject_type") or "")),
            (media._EVENT_WINDOW, media._EVENT_WINDOW.set(job.get("event_window") or "")),
            (media._SCENE_INTENT, media._SCENE_INTENT.set(job.get("scene_intent") or None)),
            (media._IN_HOOK, media._IN_HOOK.set(bool(job.get("hook"))))]


def _names(job: dict) -> List[str]:
    out = []
    for n in (job.get("subject"), job.get("place")):
        n = " ".join(str(n or "").split())
        if n and n.lower() not in [o.lower() for o in out]:
            out.append(n)
    return out


def _library_knows(job: dict, library) -> bool:
    """
    The line names its own event or place and the clip library has an unused
    clip of that subject: that clip shows the place itself, where a pack clip
    shows only the kind of thing - so the library rung gets the line.
    """
    from . import packs
    if library is None or not getattr(library, "entries", None) or not packs.is_specific(job):
        return False
    taken = set(getattr(library, "used", set()) or set())
    for name in _names(job):
        try:
            if library.find(name, exclude=taken, n=1, kind="video"):
                return True
        except Exception:  # noqa: BLE001 - an unreadable library is an empty one
            pass
    return False


def _from_pack(job: dict, used: Used, library, work: str, stop: float, require_cc: bool):
    """
    (pack) The cheapest rung: a clip from the niche packs (src/packs.py) whose
    picture fits the line - already cut, checked and kept on R2, so no search,
    no download from a site that may refuse us, no vision call. Never a clip
    this video shows or an earlier video of the owner showed, never one under
    the line's similarity floor. A line that names its own place and has an
    unused library clip of it is left to the library rung.
    """
    from . import packs
    if _library_knows(job, library):
        return None
    got = packs.pick(job, used, work, stop, require_cc=require_cc)
    if got is None:
        return None
    base = "From a niche footage pack - the footage search ran out of time for this line; check it fits"
    got.review_required = True
    got.review_reason = f"{base}. {got.review_reason}" if got.review_reason else base
    return got


def _from_library(job: dict, used: Used, library, work: str, stop: float):
    """(a) An unused library clip of the line's subject or place (library.fetch runs the slop gates)."""
    if library is None or not getattr(library, "entries", None):
        return None
    from . import media
    i = job["index"]
    seconds = float(job.get("seconds") or 6.0) + media.SEQ_SHOT_PAD
    taken = set(getattr(library, "used", set()) or set())
    for name in _names(job):
        try:
            entries = library.find(name, exclude=taken, n=4, kind="video") or []
        except Exception:  # noqa: BLE001 - an unreadable library is an empty one
            entries = []
        for e in entries:
            if time.time() > stop:
                return None
            ident = str(e.get("id") or "")
            preview = Shot(files=tuple(_files_of(e.get("read_url") or "")),
                           video=_video_of(ident, e.get("url") or ""), at=job.get("start"))
            preview.start = _start_from(None, e.get("url") or "", "") if preview.video else None
            if not preview.video:
                preview.ident = ident
            if not used.claim(i, preview):
                continue
            try:
                got = library.fetch(e, work, seconds, job)
            except Exception:  # noqa: BLE001
                got = None
            if got is None:
                used.release(i, preview)
                continue
            got.review_required = True
            got.review_reason = ("From the clip library - the footage search ran out of time for this "
                                 "line; check it fits")
            return got
    return None


def _from_reserve(job: dict, used: Used, work: str, stop: float, require_cc: bool, library=None):
    """(b) An unused approved moment of the subject pools, the line's own subject first."""
    from . import media, pools
    i = job["index"]

    def shot(cand: dict, m: dict) -> Shot:
        return pools._spare_shot(cand, m, job.get("start"))

    def fits(c: dict, m: dict) -> bool:
        video = shot(c, m).video
        return not video or media.may_place(used.placed(video), job.get("start"))

    while time.time() < stop:
        pick = pools.take_spare(job, lambda c, m: not used.why_not(i, shot(c, m)), prefer=fits)
        if pick is None:
            return None
        key, cand, m = pick
        s = shot(cand, m)
        if not used.claim(i, s):
            pools.put_back(pick)
            continue
        try:
            got = pools._fetch(job, cand, m, work, require_cc, pools._pool_name(job) or key, library=library)
        except Exception:  # noqa: BLE001
            got = None
        if got is None:
            used.release(i, s)          # the moment is spent (its download or a gate failed)
            continue
        got.review_required = True
        got.review_reason = got.review_reason or "A spare moment of a subject pool - check it fits"
        return got
    return None


def _from_still(job: dict, used: Used, work: str, stop: float, allow_generated: bool):
    """(c) One picture search for the line's subject (web, then Wikimedia), judged like any still."""
    from . import imagefix, ledger, media, slop
    i = job["index"]
    # The line's subject first, then the scene's own search words: the Mount Rainier video (2026-10-02) left
    # 97 scenes without a picture when the one search's few pictures all failed to download.
    queries = []
    for q in (next(iter(_names(job)), ""), " ".join(str(job.get("query") or "").split())):
        if q and q not in queries:
            queries.append(q)
    if not queries:
        return None
    query = queries[0]
    intent = job.get("intent") or query
    for query in queries:
        got = _still_for(job, i, query, intent, used, work, stop, imagefix, ledger, media, slop)
        if got is not None or time.time() > stop:
            return got
    if allow_generated and media._may_generate_for(job) and media._generation_budget_left():
        left = max(20, int(stop - time.time()))
        try:
            made = media.generate_image(job.get("prompt") or query, work, timeout=left)
        except Exception:  # noqa: BLE001
            made = None
        if made is not None:
            used.add(i, Shot.of_asset(made, job.get("start")))
            return made
    return None


def _still_for(job: dict, i: int, query: str, intent: str, used: Used, work: str, stop: float,
               imagefix, ledger, media, slop):
    """The first of one picture search's results that downloads, passes its checks and is not on the timeline."""
    found = []
    for fn, key in ((media.search_web_images, "search_web_images"), (media.search_wikimedia, "search_wikimedia")):
        if time.time() > stop:
            return None
        try:
            found = media._cached_search(fn, query, key=key) or []
        except Exception:  # noqa: BLE001
            found = []
        if found:
            break
    for cand in found[:STILL_TRIES]:
        if time.time() > stop:
            return None
        if imagefix.host_refused(cand.url):
            continue                                    # its site refused the last downloads
        if ledger.photo_used(cand.url):
            continue                                    # shown in an earlier video
        from . import stockblock
        if stockblock.blocked(cand, "ladder"):
            continue                                    # a stock agency's preview (src/stockblock.py)
        if media._is_bad(cand.identity):
            continue                                    # another scene found it unusable (a watermark...)
        if slop.enabled() and (slop.ai_host(cand.url, getattr(cand, "page_url", "") or "")
                               or slop.metadata_reason(cand.attribution)):
            continue
        s = Shot.of_asset(cand, job.get("start"))
        if not used.claim(i, s):
            continue
        got = media._download(dataclasses.replace(cand), query, work)
        if got is None or not got.local_path:
            _note_wanted(i, cand)                       # the link stays with the scene for the editor
        # In the line's own context: a document line's scan is its right shot (media._asset_ok_for).
        fine, why = media._asset_ok_for(job, got) if got and got.local_path else (False, "")
        if not fine:
            media._mark_bad(cand.identity, "", why)     # too blurry for any line (src/sharpness.py)...
        ok = bool(got and got.local_path and fine and not media._photo_seen_before(got.local_path))
        verdict = None
        if ok:
            media._GATE_SLOP.set("")
            ok, verdict = media.judge_clip(got.local_path, job, media._image_label(got), source_url=got.url)
            if not ok:
                media._mark_bad(cand.identity, "", media._GATE_SLOP.get())  # line-free reasons only
        if not ok:
            used.release(i, s)
            continue
        used.add(i, Shot(files=tuple(_files_of(got.local_path)), at=job.get("start")))
        got.apply_verdict(verdict, intent)
        media._count_photo(got)
        got.review_required = True
        got.review_reason = "A picture found when the footage search ran out of time - check it fits"
        return got
    return None


def _too_short(got, job: dict) -> bool:
    """
    With SHOT_MAX_SECONDS on (src/shotcap.py), a clip that would have to be
    slowed - or freeze - to cover its line at real speed: the renderer
    stretches a short clip down to 0.6x, and the cap never lets a clip be
    slowed to fill a line. Off: never (the old rule).
    """
    from . import shotcap
    if not shotcap.enabled() or getattr(got, "kind", "") != "video":
        return False
    need = float(job.get("seconds") or 0.0)
    if need <= 0:
        return False
    try:
        from . import timeline
        real = float(timeline._clip_seconds(got) or 0.0)
    except Exception:  # noqa: BLE001 - not known to be short
        return False
    return 0 < real < need - shotcap.TOLERANCE_FRAMES / 30.0


def _budget(n: int) -> float:
    """The ladder's own time box for n empty scenes."""
    if n <= 0:
        return 0.0
    total = max(config.FALLBACK_SECONDS, config.FALLBACK_SECONDS_PER_SCENE * n)
    return min(total, config.FALLBACK_MAX_SECONDS) if config.FALLBACK_MAX_SECONDS > 0 else total


def fill_empty(jobs: List[dict], results, work: str, *, library=None, require_cc: bool = False,
               youtube_only: bool = False, indices: Optional[List[int]] = None,
               used: Optional[Used] = None, seconds: Optional[float] = None,
               scene_seconds: Optional[float] = None, label: str = "",
               keep_order: bool = False) -> Dict[str, int]:
    """
    Fill every empty line of `results` (a list by index, or a dict) - or just
    `indices` - in place through the ladder: (pack) a niche pack clip that
    fits the line (PACKS_FILL), (a) library, (b) the pools' spare moments,
    (c) a picture. Nothing another scene shows is ever taken (Used). Runs
    FALLBACK_PARALLEL scenes at once under its own time box, with a download
    window of its own (the sourcing deadline may be long past) and
    FALLBACK_SCENE_SECONDS a scene. The scenes start in coverage order, or in
    the order of `indices` with keep_order (the quality gate: the softest shot
    first). Returns {"asked", "pack", "library", "reserve", "still",
    "generated", "left", "seconds"}.
    """
    from . import media, packs
    by_index = {j["index"]: j for j in jobs or []}
    want = sorted(by_index) if indices is None else [i for i in indices if i in by_index]
    todo = [i for i in want if _at(results, i) is None]
    out = {"asked": len(todo), "pack": 0, "library": 0, "reserve": 0, "still": 0, "generated": 0, "left": 0,
           "seconds": 0.0}
    if not todo or not config.FALLBACK_FILL or not work:
        out["left"] = len(todo)
        return out
    t0 = time.time()
    if used is None:
        used = Used.of_results(results, media.scene_starts(jobs))
    total = _budget(len(todo)) if seconds is None else float(seconds)
    per_scene = config.FALLBACK_SCENE_SECONDS if scene_seconds is None else float(scene_seconds)
    deadline = t0 + total
    allow_generated = not youtube_only and config.IMAGE_MAX_PER_VIDEO > 0

    def one(job: dict):
        stop = min(deadline, time.time() + per_scene)
        tokens = _scene_context(job)
        try:
            steps: List[Tuple[str, Callable]] = []
            if packs.usable(job, media.youtube_only()):
                steps.append(("pack", lambda: _from_pack(job, used, library, work, stop, require_cc)))
            steps += [
                ("library", lambda: _from_library(job, used, library, work, stop)),
                ("reserve", lambda: _from_reserve(job, used, work, stop, require_cc, library)),
            ]
            if config.FALLBACK_STILLS and job.get("visual_type", "footage") in ("footage", "image"):
                steps.append(("still", lambda: _from_still(job, used, work, stop, allow_generated)))
            for name, step in steps:
                if time.time() > stop:
                    break
                try:
                    got = step()
                except Exception as e:  # noqa: BLE001 - the next step
                    print(f"[fill] scene {job['index'] + 1}: {name} failed: {type(e).__name__}: "
                          f"{str(e)[:80]}", flush=True)
                    got = None
                if got is not None and _too_short(got, job):
                    print(f"[fill] scene {job['index'] + 1}: the {name} clip is too short to cover the line at "
                          "real speed - the next step", flush=True)
                    continue
                if got is not None:
                    if name == "still" and got.source == "generated":
                        name = "generated"
                    return got, name
            return None
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    old = ytdlp.DEADLINE[0]
    ytdlp.set_deadline(deadline)          # a short download window of the ladder's own
    pool = ThreadPoolExecutor(max_workers=max(1, min(config.FALLBACK_PARALLEL, len(todo))))
    order = [by_index[i] for i in todo] if keep_order else coverage_order([by_index[i] for i in todo])
    futures = {pool.submit(contextvars.copy_context().run, one, j): j["index"] for j in order}
    try:
        for fut in media._until(futures, deadline + 5):
            i = futures[fut]
            try:
                got = fut.result()
            except Exception:  # noqa: BLE001
                got = None
            if got and _at(results, i) is None:
                results[i] = got[0]
                out[got[1]] += 1
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        ytdlp.set_deadline(old)
    out["left"] = sum(1 for i in todo if _at(results, i) is None)
    out["seconds"] = round(time.time() - t0, 1)
    filled = out["asked"] - out["left"]
    print(f"[fill] {label or 'fallback'}: filled {filled} of {out['asked']} empty scene(s) - "
          f"{out['pack']} from the niche packs, {out['library']} from the library, "
          f"{out['reserve']} from spare pool moments, "
          f"{out['still']} stills, {out['generated']} generated; {out['left']} left for hold/graphic "
          f"({out['seconds']:.0f}s)", flush=True)
    return out


# --------------------------------------------------------------------------- #
# (d) The last resort: the line's own graphic, or the neighbouring shot held
# --------------------------------------------------------------------------- #

def _empty(scene: dict) -> bool:
    m = scene.get("media") or {}
    return m.get("type") == "color" or (m.get("type") != "animation" and not m.get("url"))


def _hook(scene: dict, fps: int) -> bool:
    return int(scene.get("startFrame") or 0) / max(1, fps) < config.HOOK_SECONDS


def graphic_for(doc: dict, scene: dict) -> Optional[dict]:
    """The planner's own full-screen graphic for this line (a number, money, a map), or None."""
    if not (config.ANIMATION_FILL and config.TREATMENTS):
        return None
    try:
        from . import treatments as vt
        meta = doc.get("meta") or {}
        pack = vt.pack_for(meta.get("brief") or {}, str(meta.get("stylePack") or ""))
        fps = max(1, int(doc.get("fps") or 30))
        sf, df = int(scene.get("startFrame") or 0), int(scene.get("durationInFrames") or 0)
        seg = type("Seg", (), {"text": scene.get("text") or "", "start": sf / fps,
                               "end": (sf + df) / fps, "duration": df / fps})()
        shot = {"subject": (scene.get("semanticMetadata") or {}).get("subject") or ""}
        return vt.animation_for(seg, shot, pack, None)
    except Exception as e:  # noqa: BLE001 - a graphic is a nicety here
        print(f"[fill] graphic skipped: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return None


def _room(scene: dict, fps: int, rate: float, ceiling: bool = False) -> float:
    """
    Frames a scene can grow while its own picture still covers it at `rate` x
    speed or more - never past SHOT_MAX_SECONDS, or with `ceiling` never past
    shotcap.CEILING (src/shotcap.py).
    """
    from . import shotcap
    m = scene.get("media") or {}
    dur = int(scene.get("durationInFrames") or 0)
    if m.get("type") == "image" and m.get("url"):
        # A still holds as long as it is shown - but no shot past SHOT_MAX_SECONDS (src/shotcap.py).
        return shotcap.room(scene, fps, float("inf"), ceiling)
    if m.get("type") != "video" or not m.get("url"):
        return 0.0                              # never an empty scene or a graphic
    from . import media as _media
    clip = m.get("clipSeconds")
    clip_s = float(clip) if isinstance(clip, (int, float)) and clip > 0 else dur / fps + _media.SEQ_SHOT_PAD
    return shotcap.room(scene, fps, max(0.0, clip_s * fps / max(0.05, rate) - dur), ceiling)


def _hold(doc: dict, i: int, rate: Optional[float], ceiling: bool = False) -> bool:
    """
    Merge empty scene i into its neighbours: the previous scene runs longer
    and/or the next starts earlier, each only while its clip covers its longer
    scene at `rate` (None = no limit) and the shot stays within
    SHOT_MAX_SECONDS - with `ceiling`, within shotcap.CEILING (src/shotcap.py).
    The line's words go with the frames.
    """
    scenes = doc["scenes"]
    fps = max(1, int(doc.get("fps") or 30))
    s = scenes[i]
    need = int(s.get("durationInFrames") or 0)
    prev = scenes[i - 1] if i > 0 and not _empty(scenes[i - 1]) else None
    nxt = scenes[i + 1] if i + 1 < len(scenes) and not _empty(scenes[i + 1]) else None
    prev = prev if prev is not None and (prev.get("media") or {}).get("type") in ("video", "image") else None
    nxt = nxt if nxt is not None and (nxt.get("media") or {}).get("type") in ("video", "image") else None
    if prev is None and nxt is None or need <= 0:
        return False
    if rate is None:
        from . import shotcap
        rp = shotcap.room(prev, fps, float("inf"), ceiling) if prev is not None else 0.0
        rn = shotcap.room(nxt, fps, float("inf"), ceiling) if nxt is not None else 0.0
    else:
        rp = _room(prev, fps, rate, ceiling) if prev is not None else 0.0
        rn = _room(nxt, fps, rate, ceiling) if nxt is not None else 0.0
    a = int(min(rp, need // 2 if nxt is not None else need))
    b = int(min(rn, need - a))
    a = int(min(rp, need - b))
    if a + b < need:
        return False
    cut = int(s.get("startFrame") or 0) + a
    words = s.get("words") or []
    early = [w for w in words if float(w.get("start") or 0) * fps < cut] if words else []
    late = [w for w in words if w not in early]
    note = "Held over the next line: nothing new was found for it in time - replace or keep"
    sid = s.get("id") or f"scene{i}"
    if prev is not None and a > 0:
        prev["durationInFrames"] = int(prev["durationInFrames"]) + a
        prev["words"] = list(prev.get("words") or []) + early
        text = " ".join(w.get("text", "") for w in early) if words else (s.get("text") or "")
        if text:
            prev["text"] = f"{prev.get('text') or ''} {text}".strip()
        prev.setdefault("semanticMetadata", {}).setdefault("heldOver", []).append(sid)
        prev["reviewRequired"] = True
        prev["reviewReason"] = note
    if nxt is not None and b > 0:
        nxt["startFrame"] = int(nxt["startFrame"]) - b
        nxt["durationInFrames"] = int(nxt["durationInFrames"]) + b
        nxt["words"] = (late if words else []) + list(nxt.get("words") or [])
        text = " ".join(w.get("text", "") for w in late) if words else ("" if a > 0 else (s.get("text") or ""))
        if text:
            nxt["text"] = f"{text} {nxt.get('text') or ''}".strip()
        nxt.setdefault("semanticMetadata", {}).setdefault("heldOver", []).append(sid)
        nxt["reviewRequired"] = True
        nxt["reviewReason"] = note
    del scenes[i]
    return True


def _card(doc: dict, s: dict) -> bool:
    text = (s.get("text") or "").strip()
    if text and s.get("durationInFrames"):
        card = {"type": "highlight", "text": text[:180],
                "startFrame": int(s.get("startFrame") or 0), "durationInFrames": int(s["durationInFrames"])}
        overlays = doc.setdefault("overlays", [])
        # A line run through the ladder twice (a recut pass) keeps one card, not two stacked on the same
        # frames (Yellowstone 2026-10-04: 9 of its text cards were doubled).
        if not any(isinstance(ov, dict) and ov.get("type") == "highlight"
                   and all(ov.get(k) == card[k] for k in ("text", "startFrame", "durationInFrames"))
                   for ov in overlays):
            overlays.append(card)
    s["reviewRequired"] = True
    s["reviewReason"] = "No usable clip found — the line is shown as text; use Find footage to add one"
    return bool(text)


def _instead_of_hold(doc: dict, refused: List[dict], out: Dict[str, int], laddered: bool, search: Optional[bool],
                     label: str, work: str = "", banned: Sequence[Shot] = ()) -> List[dict]:
    """
    The lines no neighbour could be held over without breaking the cap
    (src/shotcap.py: the owner, 2026-10-04, "clips are playing more than seven
    seconds"), in story order: a pick-a-shot runner-up - the line's own, then
    one of a shot beside it - an approved clip no scene shows; then, where
    this job may fetch (`search`: its plan's work directory, or the caller's
    say), another moment of a neighbouring YouTube clip
    FALLBACK_MOMENT_GAP_SECONDS from the one shown, checked like a chain shot,
    a few at once under one time box; then, where the ladder has not just run
    for them (`laddered`), the fallback ladder with this job's plan (the pools'
    spare moments included). Never anything another scene shows, never a shot
    in `banned` (the quality check's failed ones). Returns the scenes still
    without a picture (they get the text card).
    """
    from . import media, shotcap
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    used = Used()
    for k, sc in enumerate(scenes):
        shot = Shot.of_scene(sc, fps)
        if shot is not None:
            used.add(k, shot)
    for n, shot in enumerate(banned or ()):
        used.add(-1 - n, shot)                  # what failed is never taken again (quality.Gate._ladder)
    todo = sorted((k for k, sc in enumerate(scenes) if any(sc is x for x in refused)))
    for k in todo:
        try:
            got = shotcap.alternative_for(doc, k, used)
        except Exception as e:  # noqa: BLE001 - the next step
            print(f"[fill] scene {k + 1}: runner-up skipped: {type(e).__name__}: {str(e)[:80]}", flush=True)
            got = None
        if got:
            out["alternative"] = out.get("alternative", 0) + 1
            shotcap.note("alternative")
    work = work or CONTEXT.get("work") or media._WORK.get("dir") or ""
    may_fetch = bool(work) and (bool(search) if search is not None else bool(CONTEXT.get("jobs")))
    fetch = [k for k in todo if _empty(scenes[k])]
    if may_fetch and fetch:
        # One time box for all the fetches, a few at once (a render's repair must not wait on YouTube for minutes).
        rounds = -(-len(fetch) // max(1, shotcap.MOMENT_PARALLEL))
        window = min(float(config.FALLBACK_SECONDS), float(config.FALLBACK_SCENE_SECONDS) * rounds)
        try:
            got = shotcap.other_moments(doc, fetch, used, work, time.time() + window)
        except Exception as e:  # noqa: BLE001 - the next step
            print(f"[fill] other moments skipped: {type(e).__name__}: {str(e)[:80]}", flush=True)
            got = {}
        if got:
            out["moment"] = out.get("moment", 0) + len(got)
            shotcap.note("moment", len(got))
    todo = [k for k in todo if _empty(scenes[k])]
    work = CONTEXT.get("work") or ""
    if todo and not laddered and CONTEXT.get("jobs") and work and config.FALLBACK_FILL and config.NO_REUSE:
        known = known_jobs(doc)
        jobs = [job_for(sc, k, fps, known) for k, sc in enumerate(scenes)]
        results: Dict[int, Any] = {}
        try:
            fill_empty(jobs, results, work, library=CONTEXT.get("library"),
                       require_cc=CONTEXT.get("require_cc", False), youtube_only=CONTEXT.get("youtube_only", False),
                       indices=todo, used=used, label=label or "instead of a long hold")
        except Exception as e:  # noqa: BLE001 - the text card below
            print(f"[fill] the ladder failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
        for k, a in results.items():
            if a is not None and 0 <= k < len(scenes) and _empty(scenes[k]):
                apply_asset(scenes[k], a, "Found when holding the shot beside it would have run too long - "
                                          "check it fits")
                out["ladder"] = out.get("ladder", 0) + 1
                shotcap.note("ladder")
    return [scenes[k] for k in todo if _empty(scenes[k])]


def _hold_long(doc: dict, cards: List[dict], out: Dict[str, int]) -> List[dict]:
    """
    The lines nothing fresh was found for: the shot beside each is held over
    it PAST SHOT_MAX_SECONDS - real footage or a real picture beats a text card
    (the owner) - but every shot stays within shotcap.CEILING and a clip is
    never slowed to stretch (it must hold the footage; a still holds any
    length). Walks `cards` as given (from the end, as hold_or_animate does),
    again while a walk still held one (a run of empty lines: the line next to
    one just held may now have a shot beside it); returns the lines still
    without a picture, in the same order.
    """
    from . import shotcap
    scenes = doc.get("scenes") or []
    left = list(cards)
    while left:
        rest = []
        for s in left:
            i = next((k for k, x in enumerate(scenes) if x is s), None)
            if i is None or not _empty(s):
                continue
            sid = s.get("id") or f"scene{i}"
            beside = [scenes[k] for k in (i - 1, i + 1) if 0 <= k < len(scenes)]
            if not _hold(doc, i, 1.0, ceiling=True):
                rest.append(s)
                continue
            out["held"] += 1
            out["long"] = out.get("long", 0) + 1
            shotcap.note("long")
            for nb in beside:
                if sid in ((nb.get("semanticMetadata") or {}).get("heldOver") or []):
                    nb["reviewReason"] = (f"Held over the next line past {shotcap.limit():g} s (never past "
                                          f"{shotcap.CEILING:g} s, never slowed): nothing new was found for it "
                                          "in time - replace or keep")
        if len(rest) == len(left):
            break
        left = rest
    return left


def hold_or_animate(doc: dict, *, label: str = "", laddered: bool = False,
                    search: Optional[bool] = None, work: str = "",
                    banned: Sequence[Shot] = (), fresh: bool = True,
                    only: Optional[Sequence[dict]] = None) -> Dict[str, int]:
    """
    (d) Every empty scene: the planner's own graphic for its line (numbers,
    money, maps), else the neighbouring shot held over it while the clip
    covers the longer scene at HOLD_MIN_RATE (then at the renderer's 0.6
    floor), else the line as a text card. In the hook only as a last resort.
    Never another scene's clip. Walks from the end, so merged scenes never
    shift an index still to be visited. Returns {"graphic", "held", "card"}.

    With SHOT_MAX_SECONDS on (src/shotcap.py) a hold never makes a shot longer
    than the cap and never slows its clip to stretch; a line that cannot be
    held that way gets a pick-a-shot runner-up (its own, else one of a shot
    beside it), then another moment of a neighbouring clip (where this job
    may fetch: `search`, else when it planned the video; into `work`, else
    the plan's directory), then the ladder (unless the caller has just run
    it: `laddered`) - none of these three with `fresh` off (a render chunk
    must draw what every other machine draws: no network) - then the shot
    beside it held past the cap up to shotcap.CEILING at real speed, and
    only then the text card ("alternative", "moment", "ladder" and "long" are
    added to the counts; a long hold also counts as "held"); never a shot in
    `banned` (the quality check's failed ones). `only` (scene dicts): just
    these of the empty scenes - the hook check's last resort for the lines it
    cleared, never another pass over every text card the plan left.
    """
    from . import shotcap
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    out = {"graphic": 0, "held": 0, "card": 0, "hook": 0}
    capped = shotcap.enabled()
    rates = shotcap.hold_rates()
    cards: List[dict] = []
    for i in range(len(scenes) - 1, -1, -1):
        s = scenes[i]
        if not _empty(s):
            continue
        if only is not None and not any(s is x for x in only):
            continue
        if _hook(s, fps):
            out["hook"] += 1
        anim = graphic_for(doc, s)
        if anim:
            s["media"] = {"type": "animation", "url": "", "source": "template"}
            s["animation"] = anim
            s["visualType"] = "animation"
            s["reviewRequired"] = True
            s["reviewReason"] = "No footage found — a motion graphic fills this beat (keep it or replace the clip)"
            out["graphic"] += 1
            continue
        links = wanted_pictures(i)
        if links:
            s.setdefault("media", {})
            s["wantedPictures"] = links
        if any(_hold(doc, i, rate) for rate in rates):
            out["held"] += 1
            if capped:
                shotcap.note("held")
            if links:
                s["reviewReason"] = (str(s.get("reviewReason") or "") +
                                     " Pictures were found but their sites refused the download: links kept.").strip()
            continue
        cards.append(s)
    if capped and cards:
        # No shot past the cap: a fresh approved shot before a text card.
        shotcap.note("refused", len(cards))
        if fresh:
            cards = list(reversed(_instead_of_hold(doc, cards, out, laddered, search, label, work, banned)))
        # Nothing fresh: real footage beats a text card - the shot beside it held past the cap, never
        # past shotcap.CEILING and never slowed.
        cards = _hold_long(doc, cards, out)
    for s in reversed(cards):                   # story order
        if _card(doc, s):
            out["card"] += 1
            if capped:
                shotcap.note("card")
    if any(out.values()):
        print(f"[fill] {label or 'last resort'}: {out['graphic']} graphic(s), {out['held']} held over from "
              f"a neighbour, {out['card']} text card(s)"
              + (f", {out.get('alternative', 0)} runner-up shot(s), {out.get('moment', 0)} other moment(s) of the "
                 f"clip beside and {out.get('ladder', 0)} ladder shot(s) instead of a hold past {shotcap.limit():g} s"
                 if out.get("alternative") or out.get("moment") or out.get("ladder") else "")
              + (f"; {out['long']} of the holds run past {shotcap.limit():g} s (at most {shotcap.CEILING:g} s) "
                 "instead of a text card" if out.get("long") else "")
              + (f"; {out['hook']} in the hook (nothing else was left)" if out["hook"] else ""), flush=True)
    return out


# --------------------------------------------------------------------------- #
# The check before publishing: no file, asset or moment twice
# --------------------------------------------------------------------------- #

def find_repeats(doc: dict) -> List[Tuple[int, str]]:
    """
    [(scene index, why)] for every scene that repeats an EARLIER scene: the
    same file, the same asset, the same moment of a source video (or one
    under FALLBACK_MOMENT_GAP_SECONDS away), or the same source video on the
    next scene. A planned chain (the next moment of the clip before it) is
    not a repeat. The first scene to show a shot keeps it.
    """
    fps = max(1, int(doc.get("fps") or 30))
    used = Used()
    out = []
    for i, s in enumerate(doc.get("scenes") or []):
        shot = Shot.of_scene(s, fps)
        if shot is None:
            continue
        why = used.why_not(i, shot)
        if why:
            out.append((i, why))
        else:
            used.add(i, shot)
    return out


def known_jobs(doc: dict, known: Optional[Dict[int, dict]] = None) -> Optional[Dict[int, dict]]:
    """
    The plan's lines (CONTEXT["jobs"], or `known`) keyed by the scene number
    each ended on, as job_for reads them (scene id s<n>). The plan keys them by
    the line's place before the cold open (HOOK_TEASER, hookboost.add_teaser:
    doc.meta.hookBoost.teaser) put its flashes in front and dropped the lines
    they covered: there scene n is line n - flashes + dropped, and flash j a
    one-second look at line fromBeat. Without a cold open: as they are.
    """
    known = CONTEXT.get("jobs") if known is None else known
    teaser = ((doc.get("meta") or {}).get("hookBoost") or {}).get("teaser") or {}
    flashes = teaser.get("flashes") if isinstance(teaser, dict) else None
    if not known or not flashes:
        return known
    n, dropped = len(flashes), int(teaser.get("droppedBeats") or 0)
    out: Dict[int, dict] = {}
    for idx, job in known.items():
        if isinstance(idx, int) and idx >= dropped:
            out[idx - dropped + n] = job
    for j, flash in enumerate(flashes):
        src = flash.get("fromBeat") if isinstance(flash, dict) else None
        if isinstance(src, int) and src in known:
            out[j] = known[src]
    return out


def job_for(scene: dict, i: int, fps: int, known: Optional[Dict[int, dict]] = None) -> dict:
    """A sourcing line for one scene: the plan's own (by scene id) when known, else read off the scene."""
    sem = scene.get("semanticMetadata") or {}
    start = int(scene.get("startFrame") or 0) / max(1, fps)
    seconds = max(1.0, int(scene.get("durationInFrames") or 0) / max(1, fps))
    m = _SCENE_ID.match(str(scene.get("id") or ""))
    base = dict((known or {}).get(int(m.group(1)), {})) if m else {}
    si = sem.get("sceneIntent") if isinstance(sem.get("sceneIntent"), dict) else None
    job = {"query": scene.get("query") or sem.get("searchQuery") or sem.get("subject") or "",
           "subject": sem.get("subject") or "", "subject_type": sem.get("subjectType") or "",
           "intent": sem.get("intent") or "", "context": scene.get("text") or "",
           "scene_intent": si, "event_window": sem.get("eventWindow") or "",
           "visual_type": "footage", "hook": start < config.HOOK_SECONDS}
    job.update({k: v for k, v in base.items() if v not in (None, "")})
    job.update(index=i, start=round(start, 2), seconds=seconds)
    return job


def apply_asset(scene: dict, asset, why: str = "") -> None:
    """Put a fallback's asset on a scene (its media and what the editor shows of it)."""
    media = asset.to_scene_media()
    if asset.kind == "video":
        try:
            from . import timeline
            clip = timeline._clip_seconds(asset)
            if clip:
                media["clipSeconds"] = round(clip, 2)
        except Exception:  # noqa: BLE001 - the renderer plays it as it is
            pass
    scene["media"] = media
    sem = scene.setdefault("semanticMetadata", {})
    sem.pop("shotCap", None)            # what the shot cap put here before (src/shotcap.py) is gone
    for key in ("judgedBy", "cutCheck"):
        sem.pop(key, None)              # the shot before's check is not this one's
    sem.update({"assetId": asset.identity, "provider": asset.source,
                "sourceUrl": asset.url if str(asset.url or "").startswith("http") else "",
                "contentDescription": asset.content_description or "",
                "relevanceScore": asset.relevance_score, "qualityScore": asset.quality,
                "moment": dict(asset.moment or {}), "alternatives": []})
    if getattr(asset, "judged_by", ""):
        sem["judgedBy"] = asset.judged_by
    if getattr(asset, "cut_check", None):
        sem["cutCheck"] = dict(asset.cut_check)
    if asset.kind == "image":
        scene["motion"] = scene.get("motion") or "none"
    scene["reviewRequired"] = True
    scene["reviewReason"] = asset.review_reason or why or "A fallback shot - check it fits"


def final_check(doc: dict, *, label: str = "before publishing") -> Dict[str, int]:
    """
    The last look before the timeline goes to the editor or the render: every
    scene that repeats an earlier scene's file, asset or moment is cleared
    and re-filled through the ladder (library, spare pool moments, a
    picture), then anything still empty gets the last resort. Needs the plan
    this job made (remember); without one nothing is touched. Returns counts.
    """
    out = {"repeats": 0, "replaced": 0, "empty": 0}
    if not CONTEXT.get("jobs") or not config.NO_REUSE:
        return out
    from . import media
    scenes = doc.get("scenes") or []
    fps = max(1, int(doc.get("fps") or 30))
    repeats = find_repeats(doc)
    out["repeats"] = len(repeats)
    for i, why in repeats:
        print(f"[fill] scene {i + 1} repeats an earlier scene ({why}); finding it another shot", flush=True)
        s = scenes[i]
        s["media"] = {"type": "color", "url": "", "source": "none"}
        sem = s.setdefault("semanticMetadata", {})
        for k in ("assetId", "sourceUrl", "moment"):
            sem.pop(k, None)
    empties = [i for i, s in enumerate(scenes) if _empty(s)]
    out["empty"] = len(empties)
    if empties:
        known = known_jobs(doc)
        jobs = [job_for(s, i, fps, known) for i, s in enumerate(scenes)]
        results: Dict[int, Any] = {}
        used = Used()
        for i, s in enumerate(scenes):
            shot = Shot.of_scene(s, fps)
            if shot is not None:
                used.add(i, shot)
        got = fill_empty(jobs, results, CONTEXT.get("work") or media._WORK.get("dir") or "",
                         library=CONTEXT.get("library"), require_cc=CONTEXT.get("require_cc", False),
                         youtube_only=CONTEXT.get("youtube_only", False), indices=empties, used=used,
                         label=label)
        for i, a in results.items():
            if a is not None:
                apply_asset(scenes[i], a, "Replaced a repeat of another scene's shot")
        out["replaced"] = sum(1 for a in results.values() if a is not None)
        LAST.setdefault("final", {}).update(fill=got)
    last = hold_or_animate(doc, label=label, laddered=bool(empties))    # the ladder has just run for them
    LAST.setdefault("final", {}).update(out, last=last)
    return out


def summary(*parts: Dict[str, int]) -> str:
    """'filled 23 scenes from library/stills/hold' style line for the job's log."""
    c = Counter()
    for p in parts:
        for k in ("pack", "library", "reserve", "still", "generated", "graphic", "held", "alternative", "moment",
                  "ladder", "card"):
            c[k] += int((p or {}).get(k) or 0)
    total = sum(c.values())
    names = {"pack": "packs", "library": "library", "reserve": "spare moments", "still": "stills",
             "generated": "generated", "graphic": "graphics", "held": "hold",
             # Instead of a hold past SHOT_MAX_SECONDS (src/shotcap.py).
             "alternative": "runner-ups", "moment": "other moments", "ladder": "ladder", "card": "text"}
    used = "/".join(names[k] for k in names if c[k])
    detail = ", ".join(f"{c[k]} {names[k]}" for k in names if c[k])
    return f"filled {total} scenes from {used or 'nothing'}" + (f" ({detail})" if detail else "")
