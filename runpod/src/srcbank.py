"""
The source bank: find footage the way the owner's laptop workflow does (2026-11-03), for every video style.

Measured on the app's own videos (docs/quality-cost-plan-2026-11-03.md): the per-line search took about one new
YouTube source per 1.3 shots (MAX_MOMENTS_PER_VIDEO 2, 120 s apart) - 87 sources for the 109 clips of a 10-minute
Las Vegas video, 521 section downloads and 3,515 vision calls - and a local story simply has no 80 original sources:
the gaps went to re-upload channels, other cities' stations and photos (28-72% of the runtime were photos). The
laptop videos the owner approved were cut from ~40 whole sources, 6-15 shots each:

  1. many targeted searches per topic (the place / subject with the event word, "news", "video", "drone",
     "#shorts", the director's own line searches), original channels only - re-upload and compilation channels,
     blocked channels and other places' stations never enter;
  2. each source downloaded ONCE, whole (<= SOURCE_BANK_MAX_SOURCE_SECONDS), and split into its shots with an
     ffmpeg scene cut;
  3. ONE vision call per source on a sheet of its real frames: every shot usable or not (anchor desk, someone
     talking to camera, text, graphics, hands, blur, dark) and what it shows - cached on R2 per video id, so a
     later video reuses the review;
  4. the narration lines matched to those shots (the model ranks, rules decide): no moment twice, never the same
     source on two lines in a row, a share cap per source and per channel (soft fallback), the CLIP look-alike
     check against every shot already placed, the cross-video ledger (never a moment an earlier video showed),
     fresh uploads before older ones (ARCHIVE) for a story about now;
  5. each shot cut locally from its file (no download), checked by the local AI-slop / text filters.

Lines the bank does not fill go through the subject pools and the per-line search exactly as before, and the
lines still empty after them take the bank's unused approved shots (fill_gaps) before the fallback ladder's
pictures, holds and cards. SOURCE_BANK=0 turns it off (one job: {"config": {"SOURCE_BANK": false}}).
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import config

REVIEW_VERSION = 1
_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("""
a an the and or but of to in on at for with from by as is are was were be been being it its this that these those
there here than then so very just also into over under after before about against between through during out up
down off again once more most some such no nor not only own same too can will would should could may might must
do does did done having have has had i you he she we they them his her their our your my me him us what which who
whom whose when where why how all any both each few other new now one two three four five six seven eight nine ten
says said say week day days year years today yesterday tonight morning night still even like get got going
""".split())


def enabled() -> bool:
    return bool(getattr(config, "SOURCE_BANK", False))


# --------------------------------------------------------------------------- #
# Per-job state
# --------------------------------------------------------------------------- #

@dataclass
class Piece:
    """One reviewable stretch of a source: a shot, or ~PIECE_SECONDS of a longer continuous take."""
    src: int                     # index into _STATE["sources"]
    n: int                       # 1-based number on the review sheet
    start: float
    end: float
    take: int                    # pieces of one continuous take share it
    take_end: float = 0.0
    ok: Optional[bool] = None
    why: str = ""
    desc: str = ""
    quality: Optional[float] = None
    vec: Any = None              # CLIP embedding of its middle frame (look-alike check)
    frame: str = ""              # its middle frame on disk
    bad: bool = False            # its cut failed a local check
    band: bool = False           # its only text is a band along the bottom (a station's lower third / ticker)
    crop: float = 0.0            # keep this share of the height (the band cropped off), 0 = as it is

    @property
    def pid(self) -> str:
        return f"{self.src}.{self.n}"


@dataclass
class Source:
    id: str
    title: str = ""
    channel: str = ""
    duration: float = 0.0
    upload_date: str = ""
    width: int = 0
    height: int = 0
    kind: str = ""               # stormdesk.source_kind
    path: str = ""
    archive: bool = False        # uploaded before the story's event day
    topics: List[str] = field(default_factory=list)
    hits: int = 0
    rank: float = 0.0
    recent: bool = False
    pieces: List[Piece] = field(default_factory=list)
    compilation: bool = False
    cached: bool = False
    description: str = ""
    why: str = ""                # why it was dropped ("" = in the bank)


def _fresh_state() -> dict:
    return {"sources": [], "lines": {}, "used": {}, "src_secs": {}, "chan_secs": {}, "placed_vecs": [],
            "placed": {}, "total": 0.0, "stats": Counter(), "rejects": Counter(), "seconds": {},
            "story": {}, "ids": set(), "work": ""}


_STATE: dict = _fresh_state()
_LOCK = threading.Lock()


def reset() -> None:
    global _STATE
    _STATE = _fresh_state()


def ids() -> set:
    """The YouTube ids the bank downloaded or found re-uploading (the per-line search leaves them alone)."""
    return set(_STATE["ids"]) | set(_STATE.get("blocked_ids") or ())


def stats() -> dict:
    st = _STATE
    srcs = [s for s in st["sources"] if not s.why]
    per_src = Counter(a.split("@")[0] for a in (st["placed"] or {}).values())
    return {**dict(st["stats"]), "rejects": dict(st["rejects"]),
            "sources": len(srcs), "sourcesUsed": len(per_src),
            "shotsPerSource": round(sum(per_src.values()) / max(1, len(per_src)), 2),
            "pieces": sum(len(s.pieces) for s in srcs),
            "approved": sum(1 for s in srcs for p in s.pieces if p.ok),
            "seconds": {k: round(v, 1) for k, v in st["seconds"].items()},
            "kinds": dict(Counter(s.kind for s in srcs)),
            "used": [{"id": s.id, "channel": s.channel[:40], "kind": s.kind, "archive": s.archive,
                      "seconds": round(st["src_secs"].get(s.id, 0.0), 1),
                      "shots": per_src.get(f"yt:{s.id}", 0)} for s in srcs if per_src.get(f"yt:{s.id}")][:40],
            "archive": sum(1 for s in srcs if s.archive)}


class _Timer:
    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.t0 = time.time()

    def __exit__(self, *a):
        with _LOCK:
            _STATE["seconds"][self.name] = _STATE["seconds"].get(self.name, 0.0) + time.time() - self.t0


# --------------------------------------------------------------------------- #
# Lines and topics
# --------------------------------------------------------------------------- #

def words(text: str) -> List[str]:
    return [w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP and len(w) > 2]


def line_jobs(jobs: Sequence[dict]) -> List[dict]:
    """The lines the bank may fill: footage lines about a place, thing or event (people keep the per-line rules:
    their footage must show that person)."""
    out = []
    for j in sorted(jobs or [], key=lambda j: j["index"]):
        if (j.get("visual_type") or "footage") != "footage":
            continue
        if j.get("subject_type") == "person":
            continue
        si = j.get("scene_intent") if isinstance(j.get("scene_intent"), dict) else {}
        if si.get("role") == "chain":
            continue
        out.append(j)
    return out


def topic_of(job: dict) -> str:
    from .pools import subject_key
    return subject_key((job.get("place") or job.get("subject") or "").strip())


def _story(lines: Sequence[dict]) -> dict:
    from . import pools
    try:
        st = pools.subject_story(list(lines))
    except Exception:  # noqa: BLE001 - a story read never stops the bank
        st = {}
    return dict(st or {})


def queries(lines: Sequence[dict], story: dict, limit: int) -> List[Tuple[str, str, str]]:
    """(query, variant, recency): the topics' targeted searches, round-robin so every topic is searched, then the
    director's most common line searches."""
    topics: Counter = Counter()
    names: Dict[str, str] = {}
    for j in lines:
        k = topic_of(j)
        if k:
            topics[k] += 1
            names.setdefault(k, (j.get("place") or j.get("subject") or "").strip())
    year = str(story.get("year") or "")
    word = str(story.get("word") or "").strip()
    event = bool(story.get("is_event"))
    now = story.get("recency") or ("month" if event else "")
    shorts = bool(getattr(config, "ALLOW_VERTICAL", False) or getattr(config, "SHORTS_QUERIES", False))
    per_topic: List[List[Tuple[str, str, str]]] = []
    for k, _n in topics.most_common(int(getattr(config, "SOURCE_BANK_TOPICS", 10))):
        name = names[k]
        if event:
            what = name if (word and word[:5].lower() in name.lower()) or not word else f"{name} {word}"
            qs = [(f"{what} {year}".strip(), "event", now), (f"{what} news", "news", now),
                  (f"{what} video", "eyewitness", now), (f"{what} footage", "footage", ""),
                  (f"{what} drone", "drone", "")]
            if shorts:
                qs.insert(3, (f"{what} #shorts", "shorts", now))
        else:
            qs = [(f"{name} footage", "footage", ""), (f"{name} drone 4k", "drone", ""),
                  (f"{name} documentary", "doc", ""), (f"{name} b roll", "broll", "")]
        per_topic.append(qs)
    out, seen = [], set()
    depth = max((len(q) for q in per_topic), default=0)
    for d in range(depth):
        for qs in per_topic:
            if d < len(qs):
                q = qs[d]
                key = (q[0].lower(), q[2])
                if key not in seen:
                    seen.add(key)
                    out.append(q)
    line_qs = Counter(str(j.get("query") or "").strip() for j in lines if str(j.get("query") or "").strip())
    for q, _n in line_qs.most_common(int(getattr(config, "SOURCE_BANK_LINE_QUERIES", 8))):
        key = (q.lower(), "")
        if key not in seen:
            seen.add(key)
            out.append((q, "line", ""))
    # The topics' first searches always fit; the line searches fill what the cap leaves.
    return out[:max(1, int(limit))]


# --------------------------------------------------------------------------- #
# Search and the original-source gate
# --------------------------------------------------------------------------- #

def _search(q: str, variant: str, recency: str, require_cc: bool) -> List[dict]:
    from . import media, pools
    target = pools._target(q, require_cc, recency)
    return media._yt_candidates_cached(target, require_cc, f"bank::{q}::{recency}", variant=f"bank:{variant}")


def gate(c: dict, story_places: set, topic: str = "") -> str:
    """Why a search result can never be a bank source ("" = it may): a stock seller, a blocked channel, a music /
    off-topic upload, another place or year by its title, a re-upload or compilation channel or title, a station
    from another place, too short or too long, vertical when the style does not frame it."""
    from . import media, stormdesk
    title, chan = str(c.get("title") or ""), str(c.get("channel") or "")
    aspect = float(c.get("aspect") or 0.0)
    if aspect and aspect < 1.0 and not getattr(config, "ALLOW_VERTICAL", False):
        return "vertical"
    if stormdesk.compilation_title(title):
        return "compilation"
    if not media._usable_title(title, chan, 0.0 if aspect < 1.0 else aspect, topic):
        return "title"
    if media.title_conflict(title, topic):
        return "another place or year"
    if stormdesk.source_kind(chan, title) == "reupload":
        return "re-upload channel"
    if story_places and stormdesk.station_conflict(chan, title, story_places):
        return "a station from another place"
    dur = float(c.get("duration") or 0.0)
    if dur and dur < float(getattr(config, "SOURCE_BANK_MIN_SOURCE_SECONDS", 6)):
        return "too short"
    if dur > float(getattr(config, "SOURCE_BANK_MAX_SOURCE_SECONDS", 900)):
        return "too long"
    return ""


def rank(c: dict, topic_words: Sequence[str], story: dict) -> float:
    from . import pools, stormdesk
    title, chan = str(c.get("title") or ""), str(c.get("channel") or "")
    tw = set(words(title))
    r = 1.0 * int(c.get("_hits") or 1)
    r += 1.5 * len(tw & set(topic_words))
    kind = stormdesk.source_kind(chan, title)
    if kind in ("station", "original"):
        r += 1.0
    if story.get("is_event"):
        if pools._news_title(title, chan):
            r += 0.8
        if c.get("_recent"):
            r += 1.5
    dur = float(c.get("duration") or 0.0)
    if 20 <= dur <= 600:
        r += 0.5
    elif dur > 600:
        r -= 0.5
    if re.search(r"\b(live|livestream|podcast|reaction|explained|interview|press conference|forecast|futurecast|first alert|weather update|briefing|vlog)\b", title, re.I):
        r -= 1.5
    return round(r, 3)


def shortlist(lines: Sequence[dict], story: dict, require_cc: bool,
              search: Optional[Callable] = None) -> List[Source]:
    """Every search, merged, gated and ranked; at most SOURCE_BANK_PER_CHANNEL per channel."""
    from . import stormdesk
    search = search or _search
    qs = queries(lines, story, int(getattr(config, "SOURCE_BANK_MAX_SEARCHES", 28)))
    places = stormdesk.story_places(" ".join(
        [str(_STATE.get("story_text") or "")] + [str(j.get("place") or "") for j in lines]))
    topic_words = sorted({w for j in lines for w in words(f"{j.get('place') or ''} {j.get('subject') or ''}")})
    rows: Dict[str, dict] = {}

    def one(q):
        try:
            return q, search(q[0], q[1], q[2], require_cc) or []
        except Exception as e:  # noqa: BLE001 - one search never stops the bank
            print(f"[bank] search failed ({q[0][:40]}): {type(e).__name__}", flush=True)
            return q, []

    with _Timer("search"), ThreadPoolExecutor(max(1, int(getattr(config, "SOURCE_BANK_SEARCH_PARALLEL", 4)))) as ex:
        results = list(ex.map(one, qs))
    st = _STATE["stats"]
    st["searches"] += len(qs)
    for (q, variant, recency), got in results:
        if got:
            st["searchesWithResults"] += 1
        for c in got:
            vid = str(c.get("id") or "")
            if not vid:
                continue
            if vid in rows:
                rows[vid]["_hits"] = int(rows[vid].get("_hits") or 1) + 1
                rows[vid]["_recent"] = rows[vid].get("_recent") or bool(recency)
                rows[vid]["_topics"].add(q)
                continue
            rows[vid] = dict(c, _hits=1, _recent=bool(recency), _topics={q})
    st["candidates"] += len(rows)
    out: List[Source] = []
    for vid, c in rows.items():
        why = gate(c, places, " ".join(sorted(c["_topics"]))[:200])
        if why:
            _STATE["rejects"][why] += 1
            continue
        out.append(Source(id=vid, title=str(c.get("title") or ""), channel=str(c.get("channel") or ""),
                          duration=float(c.get("duration") or 0.0), kind=stormdesk.source_kind(
                              str(c.get("channel") or ""), str(c.get("title") or "")),
                          topics=sorted(c["_topics"]), hits=int(c["_hits"]), recent=bool(c["_recent"]),
                          rank=rank(c, topic_words, story)))
    out.sort(key=lambda s: s.rank, reverse=True)
    per_chan: Counter = Counter()
    cap = int(getattr(config, "SOURCE_BANK_PER_CHANNEL", 4))
    keep = []
    for s in out:
        ch = _chan_key(s.channel)
        if ch and per_chan[ch] >= cap:
            continue
        per_chan[ch] += 1
        keep.append(s)
    want = max(int(getattr(config, "SOURCE_BANK_MIN_SOURCES", 10)), math.ceil(len(lines) / 3.0))
    return keep[:min(int(getattr(config, "SOURCE_BANK_MAX_SOURCES", 32)), want)]


def _chan_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


# --------------------------------------------------------------------------- #
# Download (whole file, once)
# --------------------------------------------------------------------------- #

def _format(duration: float) -> str:
    h = 1080 if 0 < duration <= float(getattr(config, "SOURCE_BANK_1080_SECONDS", 240)) else 720
    return (f"bv*[height<={h}][vcodec^=avc1][protocol^=https]+ba[ext=m4a][protocol^=https]/"
            f"b[height<={h}][ext=mp4][protocol^=https]/bv*[height<={h}][protocol^=https]+ba[protocol^=https]/"
            f"b[height<={h}]")


def download(src: Source, work: str) -> str:
    """The whole source as <work>/bank/<id>.mp4 (with its sound) through the job's proxies, 2 routes tried;
    its info file fills the upload date, channel and description. '' on failure."""
    from . import costs, events, ytdlp
    from .errors import FailureClass, classify_ytdlp
    folder = os.path.join(work, "bank")
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"{src.id}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        _read_info(src, os.path.join(folder, f"{src.id}.info.json"))
        return out
    if ytdlp._video_unavailable(src.id):
        return ""
    timeout = int(min(480, 90 + 0.8 * max(30.0, src.duration or 120.0)))
    for attempt in range(2):
        if ytdlp.stopped() or ytdlp.past_deadline() or _past():
            return ""
        with ytdlp._net_slot(ytdlp.DOWNLOAD) as ok:
            if not ok:
                return ""
            proxy = ytdlp._acquire_proxy()
            cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={src.id}", "--no-playlist", "--no-warnings",
                   "-f", _format(src.duration), "--merge-output-format", "mp4", "--remux-video", "mp4",
                   "--max-filesize", f"{int(getattr(config, 'SOURCE_BANK_MAX_MB', 400))}M", "--write-info-json",
                   "-o", os.path.join(folder, f"{src.id}.%(ext)s")]
            cmd += ytdlp._yt_network_args(proxy)
            cmd += ["--retries", "4", "--fragment-retries", "4", "--extractor-retries", "2",
                    "--concurrent-fragments", "4"]
            cmd += ytdlp._client_args()
            started = time.time()
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=timeout)
            except subprocess.TimeoutExpired:
                ytdlp._release_proxy(proxy, False, FailureClass.NETWORK_TIMEOUT, started)
                _STATE["stats"]["downloadTimeouts"] += 1
                _cleanup_partial(folder, src.id)
                continue
            except FileNotFoundError:
                ytdlp._release_proxy(proxy, False, FailureClass.PROVIDER_UNAVAILABLE, started)
                return ""
        got = os.path.exists(out) and os.path.getsize(out) > 10000
        if got:
            ytdlp._release_proxy(proxy, True, None, started)
            size = os.path.getsize(out)
            costs.record("proxy.bytes", size)
            _STATE["stats"]["downloadBytes"] += size
            _read_info(src, os.path.join(folder, f"{src.id}.info.json"))
            return out
        cls = classify_ytdlp(p.stderr or "", p.returncode)
        cls = ytdlp._note_failure(src.id, cls, proxy)
        ytdlp._release_proxy(proxy, False, cls, started)
        events.emit("source", "download_failed", level="warning", provider="youtube", failure=cls.value,
                    data={"video": src.id, "proxy": ytdlp._proxy_index(proxy), "whole": True},
                    message="source bank download")
        _cleanup_partial(folder, src.id)
        if ytdlp._video_unavailable(src.id):
            break
    return ""


def _cleanup_partial(folder: str, vid: str) -> None:
    for f in glob.glob(os.path.join(folder, f"{glob.escape(vid)}.*")):
        if not f.endswith(".info.json"):
            try:
                os.remove(f)
            except OSError:
                pass


def _read_info(src: Source, path: str) -> None:
    try:
        info = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return
    src.title = str(info.get("title") or src.title)
    src.channel = str(info.get("channel") or info.get("uploader") or src.channel)
    src.upload_date = str(info.get("upload_date") or src.upload_date)
    src.duration = float(info.get("duration") or src.duration or 0.0)
    src.width, src.height = int(info.get("width") or 0), int(info.get("height") or 0)
    src.description = str(info.get("description") or "")[:3000]


def after_download(src: Source, event_day) -> str:
    """Why a downloaded source leaves the bank ("" = keeps it), and its ARCHIVE mark: older than the story's event
    day (one day's grace) for a story about now."""
    from . import stormdesk
    if stormdesk.reupload_text(src.description):
        return "re-upload (its description credits other footage)"
    kind = stormdesk.source_kind(src.channel, src.title, src.description)
    src.kind = kind
    if kind == "reupload":
        return "re-upload channel"
    w, h = int(src.width or 0), int(src.height or 0)
    if w and h:
        if h > w and not getattr(config, "ALLOW_VERTICAL", False):
            return "vertical"
        floor = int(getattr(config, "MIN_CLIP_HEIGHT", 720) or 0)
        if floor and min(w, h) < min(floor, 720) * 0.66:
            return "low resolution"
    story = _STATE.get("story") or {}
    if re.fullmatch(r"\d{8}", src.upload_date or ""):
        import datetime
        d = datetime.date(int(src.upload_date[:4]), int(src.upload_date[4:6]), int(src.upload_date[6:]))
        if event_day:
            src.archive = d < event_day - datetime.timedelta(days=1)
        elif story.get("is_event") and str(story.get("year") or "").isdigit():
            src.archive = d.year < int(story["year"])
    return ""


# --------------------------------------------------------------------------- #
# Scene split + frames (one decode)
# --------------------------------------------------------------------------- #

TILE_W, TILE_H = 256, 144


def scan(src: Source, folder: str) -> List[Piece]:
    """The source's shots (ffmpeg scene cut at 0.30) with long takes in ~PIECE_SECONDS pieces, and one frame a
    second on disk for the review sheet - one decode of the file."""
    from . import machine
    fdir = os.path.join(folder, f"{src.id}_f")
    os.makedirs(fdir, exist_ok=True)
    thr = str(max(1, min(4, machine.encode_threads() or 2)))
    vf = (f"[0:v]scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,"
          f"pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,split[a][b];"
          f"[a]select='gt(scene,{float(getattr(config, 'SOURCE_BANK_SCENE', 0.30)):.2f})',showinfo[s];[b]fps=1[f]")
    cmd = ["ffmpeg", "-v", "info", "-nostdin", "-threads", thr, "-i", src.path, "-filter_complex", vf,
           "-map", "[s]", "-f", "null", "-", "-map", "[f]", "-q:v", "5", os.path.join(fdir, "f%05d.jpg")]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    cuts = [float(m) for m in re.findall(r"pts_time:([\d.]+)", p.stderr or "")]
    dur = src.duration or _probe_seconds(src.path)
    src.duration = dur
    return pieces_from_cuts(src, cuts, dur, fdir)


def _probe_seconds(path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=nk=1:nw=1", path], capture_output=True, text=True, timeout=30).stdout
        return float(str(out).strip().split()[0].rstrip(","))
    except (ValueError, IndexError, subprocess.TimeoutExpired, FileNotFoundError):
        return 0.0


def pieces_from_cuts(src: Source, cuts: Sequence[float], dur: float, fdir: str = "") -> List[Piece]:
    if dur <= 0:
        return []
    edge = 0.3
    bounds = [edge] + sorted(c for c in cuts if edge + 0.3 < c < dur - edge - 0.3) + [max(edge, dur - edge)]
    piece_s = float(getattr(config, "SOURCE_BANK_PIECE_SECONDS", 5.0))
    out: List[Piece] = []
    take = 0
    for a, b in zip(bounds, bounds[1:]):
        if b - a < float(getattr(config, "SOURCE_BANK_MIN_SHOT", 1.2)):
            continue
        take += 1
        n = max(1, int(round((b - a) / piece_s)))
        step = (b - a) / n
        for k in range(n):
            out.append(Piece(src=-1, n=0, start=round(a + k * step, 2), end=round(a + (k + 1) * step, 2),
                             take=take, take_end=round(b, 2)))
    cap = int(getattr(config, "SOURCE_BANK_MAX_PIECES", 48))
    if len(out) > cap:
        step = len(out) / float(cap)
        out = [out[int(k * step)] for k in range(cap)]
    for k, p in enumerate(out, 1):
        p.n = k
        if fdir:
            sec = int(round((p.start + p.end) / 2.0))
            p.frame = os.path.join(fdir, f"f{max(1, sec + 1):05d}.jpg")
    return out


# --------------------------------------------------------------------------- #
# The review: one vision call per source
# --------------------------------------------------------------------------- #

_REVIEW_SYSTEM = (
    "You review raw footage for a video editor. Each image is a grid of numbered stills, one per shot of ONE "
    "source video (the number is in the box at each still's top-left; left to right, top to bottom). For EVERY "
    "number say whether the shot is usable B-roll and what it shows.\n"
    "USABLE = real camera footage of a place, a thing, people doing something or an event happening, clean "
    "enough to show full screen. Only a small station logo in a corner is fine.\n"
    "NOT usable (ok false, give the reason word): anchor (a TV studio, anchor desk, weather presenter, map "
    "wall), talk (a person talking to the camera: reporter stand-up, interview, press conference, vlogger, face "
    "cam), text (titles, captions, subtitles, a list, a page or screen of text, any banner, ticker, headline bar, "
    "\"BREAKING NEWS\" strip or lower third over the picture), graphic (maps, charts, animation, a rendered or "
    "AI-looking picture, a cartoon, a title card), hand (a hand or finger in front of the lens, a phone or TV "
    "screen being filmed), blur (blurry, out of focus, shaking hard, through a dirty or rain-covered window), "
    "dark (black, nearly black, a fade), other.\n"
    "For a shot whose ONLY problem is text in a band along the bottom edge (a lower third, ticker or headline bar "
    "that cropping off the bottom fifth would remove), also give \"band\": true.\n"
    "Also judge the whole video: compilation true when the stills look like a montage of other people's videos "
    "(different outlets' logos, mixed frames, phone clips framed between blurred side panels under one channel's "
    "own banner or captions).\n"
    "Reply with JSON only: {\"compilation\": bool, \"shots\": [{\"n\": int, \"ok\": bool, \"why\": "
    "\"anchor|talk|text|graphic|hand|blur|dark|other\" (only when ok is false), \"band\": true (only for such a "
    "text band), \"d\": \"what it shows, at most 10 words\" (when ok, or when band), \"q\": 0-1 picture quality "
    "(when ok, or when band)}]} - compact, on one line, no spaces or line breaks between fields."
)


def _sheet_images(pieces: Sequence[Piece]) -> List[str]:
    """Numbered 3x2 grids of 256x144 stills (768x288 each: a multi-image request bills each image as one tile)."""
    import base64
    import io
    from PIL import Image, ImageDraw
    out = []
    cols, rows = 3, 2
    per = cols * rows
    for k in range(0, len(pieces), per):
        group = pieces[k:k + per]
        canvas = Image.new("RGB", (cols * TILE_W, rows * TILE_H), "black")
        d = ImageDraw.Draw(canvas)
        for m, p in enumerate(group):
            x, y = (m % cols) * TILE_W, (m // cols) * TILE_H
            try:
                im = Image.open(p.frame).convert("RGB")
                if im.size != (TILE_W, TILE_H):
                    im = im.resize((TILE_W, TILE_H))
                canvas.paste(im, (x, y))
            except Exception:  # noqa: BLE001 - a missing frame shows black (the model says "dark")
                pass
            label = str(p.n)
            d.rectangle((x, y, x + 9 + 9 * len(label), y + 20), fill="white")
            d.text((x + 4, y + 3), label, fill="black")
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=82)
        out.append(base64.b64encode(buf.getvalue()).decode())
    return out


def review(src: Source, story_line: str = "", ask: Optional[Callable] = None) -> bool:
    """Sets every piece's ok / why / desc / quality and the source's compilation mark from one vision call.
    False when no model answered (the source stays out: nothing unjudged is placed)."""
    from . import costs, vision
    if not src.pieces:
        return False
    images = _sheet_images(src.pieces)
    n = len(src.pieces)
    text = (f"STORY: {story_line[:300]}\n" if story_line else "") + \
        f"SOURCE: {src.title[:140]} - {src.channel[:60]} - uploaded {src.upload_date or 'unknown'}\n" + \
        f"There are {n} shots, numbered 1-{n}, shown across {len(images)} image(s), in order."
    messages = [{"role": "system", "content": _REVIEW_SYSTEM},
                {"role": "user", "content": [{"type": "text", "text": text}] + [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]}]
    if ask is None:
        token = vision._KIND.set("bank_review")
        try:
            raw, _model = vision._ask(messages, 120 + 48 * n)
        finally:
            vision._KIND.reset(token)
        if raw:
            costs.record("vision.bank_review")
    else:
        raw = ask(messages)
    data = _parse_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        # A reply cut off by the token limit (or wrapped in prose): every complete shot row in it still counts.
        rows = _salvage_rows(raw)
        if not rows:
            return False
        data = {"shots": rows, "compilation": bool(re.search(r'"compilation"\s*:\s*true', str(raw or "")))}
        _STATE["stats"]["reviewsSalvaged"] += 1
    by_n = {p.n: p for p in src.pieces}
    for row in data["shots"]:
        if not isinstance(row, dict):
            continue
        try:
            p = by_n.get(int(row.get("n")))
        except (TypeError, ValueError):
            continue
        if p is None:
            continue
        p.ok = bool(row.get("ok"))
        p.why = "" if p.ok else str(row.get("why") or "other")[:20]
        p.band = bool(row.get("band")) and not p.ok and p.why == "text"
        p.desc = str(row.get("d") or "")[:120] if (p.ok or p.band) else ""
        try:
            p.quality = (max(0.0, min(1.0, float(row.get("q")))) if (p.ok or p.band) and row.get("q") is not None
                         else None)
        except (TypeError, ValueError):
            p.quality = None
    for p in src.pieces:
        if p.ok is None:
            p.ok, p.why = False, "unanswered"
    src.compilation = bool(data.get("compilation"))
    return True


_ROW = re.compile(r'\{[^{}]*"n"\s*:\s*\d+[^{}]*\}')


def _salvage_rows(raw: Optional[str]) -> List[dict]:
    out = []
    for m in _ROW.finditer(str(raw or "")):
        try:
            row = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _parse_json(raw: Optional[str]) -> Any:
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    try:
        return json.loads(s)
    except ValueError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _cache_key(vid: str) -> str:
    return f"{getattr(config, 'R2_LIBRARY_PREFIX', '')}bank/reviews/v{REVIEW_VERSION}/{vid}.json"


def cached_review(src: Source) -> bool:
    if not getattr(config, "SOURCE_BANK_CACHE", True):
        return False
    try:
        from . import ledger, r2
        if not r2.library_enabled():
            return False
        data = ledger._get_json(_cache_key(src.id), timeout=10)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(data, dict) or not isinstance(data.get("pieces"), list):
        return False
    src.pieces = []
    for row in data["pieces"]:
        try:
            src.pieces.append(Piece(src=-1, n=int(row["n"]), start=float(row["s"]), end=float(row["e"]),
                                    take=int(row.get("t") or 0), take_end=float(row.get("te") or row["e"]),
                                    ok=bool(row.get("ok")), why=str(row.get("why") or ""),
                                    desc=str(row.get("d") or ""), quality=row.get("q"), band=bool(row.get("b"))))
        except (KeyError, TypeError, ValueError):
            continue
    src.compilation = bool(data.get("compilation"))
    src.cached = bool(src.pieces)
    return src.cached


def save_review(src: Source) -> None:
    if not getattr(config, "SOURCE_BANK_CACHE", True) or src.cached:
        return
    try:
        from . import ledger, r2
        if not r2.library_enabled():
            return
        ledger._put_json(_cache_key(src.id), {
            "v": REVIEW_VERSION, "id": src.id, "title": src.title, "channel": src.channel,
            "upload_date": src.upload_date, "duration": src.duration, "compilation": src.compilation,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pieces": [{"n": p.n, "s": p.start, "e": p.end, "t": p.take, "te": p.take_end, "ok": p.ok,
                        "why": p.why, "d": p.desc, "q": p.quality, "b": p.band} for p in src.pieces]})
    except Exception as e:  # noqa: BLE001 - the cache never fails a video
        print(f"[bank] review not cached ({src.id}): {type(e).__name__}", flush=True)


BAND_KEEP = 0.78                 # a station's lower third cropped off: the top 78% of the picture, scaled back
BAND_MIN_LINES = 600             # ... only when that keeps at least this many of the source's lines


def judge_source(src: Source) -> str:
    """Why a reviewed source leaves the bank ("" = it stays), after its review: the model called it a compilation;
    an uploader that is not a station or agency puts its own banner over most shots, or frames vertical phone
    clips between blurred side panels (a re-upload of other people's footage). A station's or agency's own lower
    third is cropped off its shots when enough lines are left (BAND_KEEP / BAND_MIN_LINES)."""
    if src.compilation:
        return "a compilation (its shots)"
    reviewed = [p for p in src.pieces if p.ok is not None]
    if not reviewed:
        return ""
    own = src.kind in ("station", "original")
    banded = [p for p in reviewed if p.band]
    texted = [p for p in reviewed if p.why == "text"]
    if not own and len(texted) >= 0.4 * len(reviewed) and len(texted) >= 3:
        return "its own banner over most shots (a re-upload)"
    if not own and (src.width or 1) > (src.height or 0) and _framed_vertical(src):
        return "vertical clips framed in blur (a re-upload)"
    if own and banded and (src.height or 0) * BAND_KEEP >= BAND_MIN_LINES:
        for p in banded:
            p.ok, p.crop = True, BAND_KEEP
    return ""


def _framed_vertical(src: Source) -> bool:
    """Most review stills show a sharp centre panel over blurred sides (stormdesk.blurred_sides on 6 stills)."""
    try:
        import numpy as np
        from PIL import Image
        from . import stormdesk
        frames = [p.frame for p in src.pieces if p.frame and os.path.exists(p.frame)]
        if len(frames) < 4:
            return False
        step = max(1, len(frames) // 6)
        pick = frames[::step][:6]
        hits = 0
        for k in range(0, len(pick) - 1, 2):
            pair = [np.asarray(Image.open(f).convert("RGB")) for f in pick[k:k + 2]]
            if stormdesk.blurred_sides(pair) > 0:
                hits += 1
        return hits >= 2
    except Exception:  # noqa: BLE001 - no verdict: the review stands
        return False


def _frames_for_cached(src: Source, folder: str) -> None:
    """Middle frames of a cached review's approved pieces (for the look-alike check), one ffmpeg seek each."""
    fdir = os.path.join(folder, f"{src.id}_f")
    os.makedirs(fdir, exist_ok=True)
    for p in src.pieces:
        if not p.ok:
            continue
        f = os.path.join(fdir, f"c{p.n:03d}.jpg")
        t = (p.start + p.end) / 2.0
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", src.path, "-frames:v", "1",
                        "-vf", f"scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,"
                               f"pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2", f], capture_output=True, timeout=60)
        if os.path.exists(f):
            p.frame = f


def _embed(pieces: Sequence[Piece]) -> None:
    from . import localvision
    todo = [p for p in pieces if p.ok and p.frame and os.path.exists(p.frame) and p.vec is None]
    if not todo:
        return
    try:
        if not localvision.available():
            return
        from PIL import Image
        vecs = localvision.embed_images([Image.open(p.frame).convert("RGB") for p in todo])
        for p, v in zip(todo, vecs):
            p.vec = v
    except Exception as e:  # noqa: BLE001 - no look-alike check rather than no bank
        print(f"[bank] look-alike embeddings skipped: {type(e).__name__}", flush=True)


# --------------------------------------------------------------------------- #
# Matching lines to shots
# --------------------------------------------------------------------------- #

_MATCH_SYSTEM = (
    "You match narration lines to B-roll shots for a video editor. For each line pick up to 3 shots that show what "
    "the line is about - its place, thing, people or event - best first, each with a fit score 0-1. Prefer a shot of "
    "the exact place / thing / event the line names; then the same subject in general. Never pick a shot of another "
    "place or another event than the line's, nor one that contradicts the line. A line nothing fits gets an empty "
    "list. Shots are 'source.shot' ids; SOURCES says where each source comes from.\n"
    "Reply with JSON only: {\"lines\": [{\"i\": int, \"shots\": [[\"id\", score], ...]}]}"
)


def match(lines: Sequence[dict], pieces: Sequence[Piece], story_line: str = "",
          ask: Optional[Callable] = None) -> Dict[int, List[Tuple[str, float]]]:
    """line index -> [(piece id, fit)] best first: the model's ranking (batches of SOURCE_BANK_MATCH_BATCH lines),
    the word-overlap ranking for every line it left out or when no model answers."""
    from . import costs, vision
    by_id = {p.pid: p for p in pieces}
    srcs = _STATE["sources"]
    used_src = sorted({p.src for p in pieces})
    sources = {str(k): f"{srcs[k].title[:80]} | {srcs[k].channel[:40]} | {srcs[k].upload_date or '?'}"
               for k in used_src}
    shots = [[p.pid, p.desc[:90]] for p in pieces]
    out: Dict[int, List[Tuple[str, float]]] = {}
    batch = max(10, int(getattr(config, "SOURCE_BANK_MATCH_BATCH", 50)))
    if pieces and getattr(config, "SOURCE_BANK_MODEL_MATCH", True):
        for k in range(0, len(lines), batch):
            group = lines[k:k + batch]
            payload = {"story": story_line[:300], "sources": sources, "shots": shots,
                       "lines": [[j["index"], str(j.get("context") or "")[:220],
                                  f"{j.get('place') or ''} / {j.get('subject') or ''}"[:80]] for j in group]}
            messages = [{"role": "system", "content": _MATCH_SYSTEM},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
            if ask is None:
                if not vision.configured():
                    break
                token = vision._KIND.set("bank_match")
                try:
                    raw, _m = vision._ask(messages, 80 + 40 * len(group))
                finally:
                    vision._KIND.reset(token)
                if raw:
                    costs.record("vision.bank_match")
            else:
                raw = ask(messages)
            data = _parse_json(raw)
            rows = data.get("lines") if isinstance(data, dict) else None
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                try:
                    i = int(row.get("i"))
                except (TypeError, ValueError, AttributeError):
                    continue
                got = []
                for item in row.get("shots") or []:
                    try:
                        pid, score = str(item[0]), float(item[1])
                    except (TypeError, ValueError, IndexError, KeyError):
                        continue
                    if pid in by_id:
                        got.append((pid, max(0.0, min(1.0, score))))
                out[i] = got
            _STATE["stats"]["matchCalls"] += 1
    # Word overlap: every line the model did not answer, and runners-up behind the model's picks - the line's
    # words against the shot's description and its source's title, plus its topic (the source was found by a
    # search about the line's place or subject). Up to SOURCE_BANK_TAIL of them, so the placement rules (share
    # caps, no source twice in a row) always have other sources to turn to.
    tail_n = int(getattr(config, "SOURCE_BANK_TAIL", 40))
    src_words = {k: set(words(srcs[k].title)) for k in used_src}
    src_topics = {k: " ".join(srcs[k].topics).lower() for k in used_src}
    for j in lines:
        lw = set(words(f"{j.get('context') or ''} {j.get('place') or ''} {j.get('subject') or ''}"))
        tw = set(words(f"{j.get('place') or ''} {j.get('subject') or ''}"))
        topic = str(j.get("place") or j.get("subject") or "").strip().lower()
        scored = []
        for p in pieces:
            pw = set(words(p.desc)) | src_words[p.src]
            hit = len(lw & pw) + 1.5 * len(tw & pw) + (1.0 if topic and topic in src_topics[p.src] else 0.0)
            if hit:
                scored.append((p.pid, round(min(0.6, 0.15 + 0.08 * hit), 3), p.quality or 0.5))
        scored = _spread(scored, by_id)
        have = {pid for pid, _s in out.get(j["index"], [])}
        model_answered = j["index"] in out
        tail = [(pid, round(sc * (0.7 if model_answered else 1.0), 3)) for pid, sc, _q in scored[:tail_n]
                if pid not in have]
        out[j["index"]] = list(out.get(j["index"], [])) + tail
    return out


def _spread(scored: List[Tuple[str, float, float]], by_id: Dict[str, Piece]) -> List[Tuple[str, float, float]]:
    """Best first, but taken in turns from every source at the same score level: a tail made of one source's
    pieces would leave the placement nothing once that source's share cap is reached."""
    groups: Dict[int, List[Tuple[str, float, float]]] = {}
    for row in sorted(scored, key=lambda x: (x[1], x[2]), reverse=True):
        groups.setdefault(by_id[row[0]].src, []).append(row)
    order = sorted(groups.values(), key=lambda g: (g[0][1], g[0][2]), reverse=True)
    out: List[Tuple[str, float, float]] = []
    k = 0
    while any(k < len(g) for g in order):
        level = [g[k] for g in order if k < len(g)]
        out.extend(sorted(level, key=lambda x: (x[1], x[2]), reverse=True))
        k += 1
    return out


# --------------------------------------------------------------------------- #
# Placement: the editor's rules
# --------------------------------------------------------------------------- #

def _cap_seconds(total: float) -> Tuple[float, float]:
    """(seconds one source may fill, seconds one channel may fill). With the style's CHANNEL_MAX_SHARE (storm desk
    ~7%) the channel cap is exactly what the variety rules allow (media.variety_violations), and a source never
    more than its channel."""
    share = float(getattr(config, "SOURCE_BANK_SHARE", 0.08))
    src_cap = max(float(getattr(config, "SOURCE_BANK_MIN_CAP", 12.0)), share * total)
    chan_share = float(getattr(config, "CHANNEL_MAX_SHARE", 0) or 0)
    if chan_share > 0:
        chan_cap = chan_share * total + 0.5
        return min(src_cap, chan_cap), chan_cap
    return src_cap, 2.0 * src_cap


def _window(p: Piece, need: float, used: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """Where in its take a line of `need` seconds can be cut from piece `p`: from the piece's start (a cut point
    for the first piece of a take), within the take, clear of every moment of the video already used."""
    gap = float(getattr(config, "SOURCE_BANK_MOMENT_GAP", 1.0))
    start = p.start + 0.12
    end = start + need
    if end > p.take_end - 0.08:
        return None
    for a, b in used:
        if start < b + gap and a < end + gap:
            return None
    return round(start, 2), round(end, 2)


def _lookalike(p: Piece, placed: Sequence[Tuple[Piece, int]], line_i: int) -> bool:
    if p.vec is None:
        return False
    thr = float(getattr(config, "SOURCE_BANK_LOOKALIKE", 0.95))
    import numpy as np
    for q, j in placed:
        if q.vec is None:
            continue
        try:
            if float(np.dot(p.vec, q.vec)) >= thr:
                return True
        except Exception:  # noqa: BLE001
            return False
    return False


def place(lines: Sequence[dict], ranks: Dict[int, List[Tuple[str, float]]], pieces: Sequence[Piece],
          floor: Optional[float] = None, relax: float = 1.0, neighbours: Optional[Dict[int, str]] = None
          ) -> Dict[int, Tuple[Piece, float, float, float]]:
    """line index -> (piece, start, end, fit), in timeline order under the rules (see the module doc). `relax`
    multiplies the share caps (the soft fallback); `neighbours`: line index -> the source video id already on
    that line (lines outside this pass), so no source plays on two lines in a row."""
    from . import ledger
    st = _STATE
    floor = float(getattr(config, "SOURCE_BANK_MIN_FIT", 0.45)) if floor is None else floor
    by_id = {p.pid: p for p in pieces}
    srcs = st["sources"]
    src_cap, chan_cap = _cap_seconds(st["total"] or sum(float(j.get("seconds") or 0) for j in lines))
    src_cap, chan_cap = src_cap * relax, chan_cap * relax
    pad = 0.3
    out: Dict[int, Tuple[Piece, float, float, float]] = {}
    on_line: Dict[int, str] = dict(neighbours or {})
    for k, (q, _a, _b, _f) in (st.get("placed_full") or {}).items():
        on_line[k] = srcs[q.src].id
    for j in sorted(lines, key=lambda j: j["index"]):
        i = j["index"]
        need = float(j.get("seconds") or 3.0) + pad
        current = bool(st["story"].get("is_event"))
        best = None
        for pid, fit in ranks.get(i, []):
            p = by_id.get(pid)
            if p is None or not p.ok or p.bad:
                continue
            src = srcs[p.src]
            score = fit * (0.6 if (current and src.archive) else 1.0) * (0.9 + 0.1 * (p.quality or 0.7))
            if score < floor or (best and score <= best[3]):
                continue
            if on_line.get(i - 1) == src.id or on_line.get(i + 1) == src.id:
                continue
            if st["src_secs"].get(src.id, 0.0) + need > src_cap:
                continue
            ch = _chan_key(src.channel)
            if ch and st["chan_secs"].get(ch, 0.0) + need > chan_cap:
                continue
            w = _window(p, need, st["used"].get(src.id, []))
            if w is None:
                continue
            try:
                if ledger.on() and ledger.moment_used(src.id, w[0], w[1]):
                    continue
            except Exception:  # noqa: BLE001
                pass
            if _lookalike(p, [(q, k) for k, (q, _a, _b, _f) in (st.get("placed_full") or {}).items()], i):
                st["stats"]["lookalikeSkipped"] += 1
                continue
            best = (p, w[0], w[1], score)
        if best is None:
            continue
        p, a, b, score = best
        src = srcs[p.src]
        st["used"].setdefault(src.id, []).append((a, b))
        st["src_secs"][src.id] = st["src_secs"].get(src.id, 0.0) + (b - a)
        ch = _chan_key(src.channel)
        if ch:
            st["chan_secs"][ch] = st["chan_secs"].get(ch, 0.0) + (b - a)
        st.setdefault("placed_full", {})[i] = (p, a, b, score)
        on_line[i] = src.id
        out[i] = best
    return out


def release(i: int) -> None:
    """Take back line i's placement (its cut failed a local check)."""
    st = _STATE
    got = (st.get("placed_full") or {}).pop(i, None)
    if not got:
        return
    p, a, b, _s = got
    src = st["sources"][p.src]
    rng = st["used"].get(src.id, [])
    if (a, b) in rng:
        rng.remove((a, b))
    st["src_secs"][src.id] = max(0.0, st["src_secs"].get(src.id, 0.0) - (b - a))
    ch = _chan_key(src.channel)
    if ch:
        st["chan_secs"][ch] = max(0.0, st["chan_secs"].get(ch, 0.0) - (b - a))
    st["placed"].pop(i, None)


# --------------------------------------------------------------------------- #
# Cutting + the asset
# --------------------------------------------------------------------------- #

def cut(p: Piece, a: float, b: float, job: dict) -> Optional[Any]:
    """The line's clip cut from its source file, checked by the local filters, as a MediaAsset (None = turned
    down: the piece is marked bad)."""
    from . import filters, media
    src = _STATE["sources"][p.src]
    path = filters.trim_clip(src.path, a, b - a)
    if not path:
        p.bad = True
        return None
    if p.crop:
        from . import stormdesk
        if not stormdesk.crop_bottom(path, p.crop):
            p.bad = True
            try:
                os.remove(path)
            except OSError:
                pass
            return None
    why = ""
    try:
        why = media.slop_reason(path, src.title) or (
            "burned-in text" if filters.has_burned_captions(path) else "")
    except Exception:  # noqa: BLE001 - a filter error never drops a clip
        why = ""
    if why:
        _STATE["rejects"][f"cut: {why.split(' (')[0][:40]}"] += 1
        p.bad = True
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return asset_for(p, a, b, job, path)


def asset_for(p: Piece, a: float, b: float, job: dict, path: str, fit: Optional[float] = None) -> Any:
    from . import media
    src = _STATE["sources"][p.src]
    fit = fit if fit is not None else ((_STATE.get("placed_full") or {}).get(job["index"], (None, 0, 0, None))[3])
    mkey = f"yt:{src.id}@b{int(round(a * 10))}"
    asset = media.MediaAsset(
        kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={src.id}&t={int(a)}",
        local_path=path, duration=round(b - a, 2), attribution=f"YouTube: {src.title}"[:200],
        license="unverified — you must hold the rights", query=job.get("query") or "",
        intent=job.get("intent") or job.get("query") or "", review_required=True,
        review_reason="Licence unverified — confirm you hold the rights",
        content_description=p.desc, relevance_score=fit, quality=p.quality, moment_key=mkey,
        moment={"start": round(a, 2), "end": round(b, 2), "bank": True, "clean": True, "cuts": 0,
                "score": fit, "fine": False},
        judged_by="sheet", channel=src.channel, upload_date=src.upload_date)
    asset.pool = {"bank": True, "kind": src.kind, "archive": src.archive, "reviewCached": src.cached}
    if src.archive:
        asset.score_parts = {"archive": 1.0}
    with _LOCK:
        _STATE["placed"][job["index"]] = mkey
    return asset


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #

def _past() -> bool:
    d = _STATE.get("deadline") or 0.0
    return bool(d) and time.time() > d


def build(jobs: Sequence[dict], work: str, *, require_cc: bool = False, report: Optional[Callable] = None,
          story_line: str = "", search: Optional[Callable] = None) -> List[Source]:
    """Search, gate, download, split and review the bank's sources (state kept for fill / fill_gaps)."""
    from . import media
    st = _STATE
    lines = line_jobs(jobs)
    st["lines"] = {j["index"]: j for j in lines}
    st["total"] = sum(float(j.get("seconds") or 0.0) for j in jobs or [])
    st["work"] = work
    st["deadline"] = time.time() + float(getattr(config, "SOURCE_BANK_SECONDS", 900))
    st["story"] = _story(lines)
    st["story_text"] = story_line
    if len(lines) < int(getattr(config, "SOURCE_BANK_MIN_LINES", 4)):
        st["stats"]["skipped"] = 1
        return []
    srcs = shortlist(lines, st["story"], require_cc, search=search)
    st["stats"]["shortlisted"] = len(srcs)
    folder = os.path.join(work, "bank")
    os.makedirs(folder, exist_ok=True)
    event_day = media.EVENT_DAY[0] if getattr(media, "EVENT_DAY", None) else None
    done = [0]

    def one(src: Source) -> Source:
        if _past():
            src.why = "time box"
            return src
        with _Timer("download"):
            src.path = download(src, work)
        if not src.path:
            src.why = "download failed"
            return src
        why = after_download(src, event_day)
        if why:
            src.why = why
            return src
        with _Timer("scan"):
            if not cached_review(src):
                src.pieces = scan(src, folder)
        if not src.pieces:
            src.why = src.why or "no shots"
            return src
        if not src.cached:
            with _Timer("review"):
                if not review(src, story_line):
                    src.why = "not reviewed"
                    return src
            save_review(src)
        else:
            _frames_for_cached(src, folder)
        src.why = src.why or judge_source(src)
        with _LOCK:
            done[0] += 1
            if report:
                try:
                    report(f"Reviewing whole sources {done[0]}/{len(srcs)}", 24, done=done[0], total=len(srcs))
                except Exception:  # noqa: BLE001
                    pass
        return src

    with ThreadPoolExecutor(max(1, int(getattr(config, "SOURCE_BANK_PARALLEL", 4)))) as ex:
        srcs = list(ex.map(one, srcs))
    for k, s in enumerate(srcs):
        for p in s.pieces:
            p.src = k
        if s.why:
            st["rejects"][s.why] += 1
            if _REUPLOAD_WHY.search(s.why) and s.kind not in ("station", "original"):
                # Seen re-uploading: the per-line search and every later fetch of this job leave its channel and
                # its uploads alone too (media.BLOCKED_CHANNELS, ids()).
                st.setdefault("blocked_ids", set()).add(s.id)
                if s.channel.strip() and s.channel not in media.BLOCKED_CHANNELS:
                    media.BLOCKED_CHANNELS.append(s.channel)
                    st["stats"]["channelsBlocked"] += 1
        else:
            st["ids"].add(s.id)
            st["stats"]["reviewCached"] += int(s.cached)
    st["sources"] = srcs
    with _Timer("embed"):
        _embed([p for s in srcs if not s.why for p in s.pieces])
    return srcs


_REUPLOAD_WHY = re.compile(r"re-upload|compilation")


def _approved() -> List[Piece]:
    return [p for s in _STATE["sources"] if not s.why for p in s.pieces if p.ok and not p.bad]


def fill(jobs: Sequence[dict], work: str, *, require_cc: bool = False, report: Optional[Callable] = None,
         story_line: str = "", search: Optional[Callable] = None) -> Dict[int, Any]:
    """line index -> MediaAsset for every line the bank fills (see the module doc)."""
    t0 = time.time()
    try:
        build(jobs, work, require_cc=require_cc, report=report, story_line=story_line, search=search)
        pieces = _approved()
        lines = list(_STATE["lines"].values())
        if not pieces or not lines:
            return {}
        if report:
            report(f"Matching {len(lines)} lines to {len(pieces)} reviewed shots", 30)
        with _Timer("match"):
            ranks = match(lines, pieces, story_line)
        _STATE["ranks"] = ranks
        got = _place_and_cut(lines, ranks, pieces)
        _STATE["stats"]["filled"] += len(got)
        return got
    except Exception as e:  # noqa: BLE001 - the bank never fails a video: the per-line search takes over
        print(f"[bank] stopped: {type(e).__name__}: {str(e)[:200]}", flush=True)
        _STATE["stats"]["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return {}
    finally:
        _STATE["seconds"]["total"] = time.time() - t0


def _place_and_cut(lines: Sequence[dict], ranks: Dict[int, List[Tuple[str, float]]], pieces: Sequence[Piece],
                   floor: Optional[float] = None, relax: float = 1.0,
                   neighbours: Optional[Dict[int, str]] = None) -> Dict[int, Any]:
    out: Dict[int, Any] = {}
    todo = list(lines)
    for _round in range(3):
        if not todo:
            break
        plan = place(todo, ranks, pieces, floor=floor, relax=relax, neighbours=neighbours)
        if not plan:
            break
        jobs_by = {j["index"]: j for j in todo}
        with _Timer("cut"), ThreadPoolExecutor(max(1, int(getattr(config, "SOURCE_BANK_CUT_PARALLEL", 6)))) as ex:
            got = dict(zip(plan.keys(), ex.map(lambda kv: cut(kv[1][0], kv[1][1], kv[1][2], jobs_by[kv[0]]),
                                               plan.items())))
        retry = []
        for i, a in got.items():
            if a is None:
                release(i)
                retry.append(jobs_by[i])
            else:
                out[i] = a
        todo = retry
    return out


def fill_gaps(jobs: Sequence[dict], results, work: str = "") -> Dict[int, Any]:
    """Lines still empty after every search: the bank's unused approved shots, best matching first, relaxed
    (any shot of the story's sources, share caps x SOURCE_BANK_GAP_RELAX), never next to its own source."""
    if not enabled() or not _STATE["sources"]:
        return {}
    try:
        pieces = _approved()
        if not pieces:
            return {}

        def at(i):
            if isinstance(results, dict):
                return results.get(i)
            return results[i] if 0 <= i < len(results) else None

        empty = [j for j in sorted(jobs, key=lambda j: j["index"]) if at(j["index"]) is None
                 and (j.get("visual_type") or "footage") in ("footage", "image")
                 and j.get("subject_type") not in ("person", "document")]
        if not empty:
            return {}
        neighbours = {}
        from . import media
        for j in jobs:
            a = at(j["index"])
            if a is not None and getattr(a, "kind", "") == "video":
                vid, _s = media._yt_origin(a)
                if vid:
                    neighbours[j["index"]] = vid
        ranks = dict(_STATE.get("ranks") or {})
        missing = [j for j in empty if not ranks.get(j["index"])]
        if missing:
            ranks.update(match(missing, pieces, str(_STATE.get("story_text") or ""),
                               ask=(lambda m: None) if not getattr(config, "SOURCE_BANK_MODEL_MATCH", True) else None))
        # Any approved shot of the story is a better gap filler than a photo of something else or a held shot:
        # every line's ranking gets the rest of the bank behind its own picks at a low fit.
        rest = sorted(pieces, key=lambda p: -(p.quality or 0.5))
        for j in empty:
            have = {pid for pid, _s in ranks.get(j["index"], [])}
            ranks[j["index"]] = list(ranks.get(j["index"], [])) + [(p.pid, 0.3) for p in rest if p.pid not in have]
        got = _place_and_cut(empty, ranks, pieces, floor=0.25,
                             relax=float(getattr(config, "SOURCE_BANK_GAP_RELAX", 1.5)), neighbours=neighbours)
        _STATE["stats"]["gapFilled"] += len(got)
        return got
    except Exception as e:  # noqa: BLE001
        print(f"[bank] gap fill stopped: {type(e).__name__}: {str(e)[:160]}", flush=True)
        return {}


def source_path(video_id: str) -> str:
    """The bank's whole file of a YouTube video ('' when the bank did not download it)."""
    vid = video_id[3:] if str(video_id).startswith("yt:") else str(video_id)
    for src in _STATE.get("sources") or []:
        if src.id == vid and src.path and os.path.isfile(src.path):
            return src.path
    work = _STATE.get("work") or ""
    p = os.path.join(work, "bank", f"{vid}.mp4") if work else ""
    return p if p and os.path.isfile(p) else ""


def local_section(video_id: str, start: float, seconds: float, out_dir: str, audio: bool = True) -> str:
    """`seconds` of a banked source from `start`, cut from its file WITH its sound (a storm desk pause clip): no
    download. '' when the bank has no file for it or the cut fails."""
    path = source_path(video_id)
    if not path or seconds <= 0:
        return ""
    vid = video_id[3:] if str(video_id).startswith("yt:") else str(video_id)
    out = os.path.join(out_dir, f"bank_{vid}_{int(round(start * 1000))}_{int(round(seconds * 1000))}.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, start):.2f}", "-i", path, "-t",
           f"{seconds:.2f}", "-map", "0:v:0", *(["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"] if audio else
                                                ["-an"]),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           out]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    from .filters import playable_video
    if playable_video(out, min_seconds=min(1.0, seconds * 0.5)):
        _STATE["stats"]["localSections"] += 1
        return out
    return ""
