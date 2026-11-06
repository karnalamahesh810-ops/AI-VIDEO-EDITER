"""
The Breaking News Desk's footage library on R2: pods search shots that were already downloaded and indexed once, instead of
downloading from YouTube (a pod gets bot-checked: 455 of 491 downloads failed on 2026-11-05). The kit's engine/index format on
a private bucket, built and pushed from the laptop by scripts/library_push.py:

    sdlib/v1/catalog.json              {"version", "sources": {id: {channel, title, date, w, h, dur, size, key, kind}}}
    sdlib/v1/index_pack.npz            every source's shots in one file: ids, src, emb (N x 512, CLIP ViT-B-32 laion2b),
                                       a, b (shot times), text, text_top (share of the frame with text, whole / a station's
                                       crop), face (biggest face's share), k (the kit's shot number)
    sdlib/v1/index/<id>.npz            the same per source (the kit's own files, kept for re-packing)
    sdlib/v1/src/<id>.mp4              the source, fetched by a pod only when a shot of it is placed, by a presigned link
    sdlib/v1/models/clip_b32_text.onnx the text half of the same CLIP (a pod has only ViT-B/16)
    sdlib/v1/rejected.json             moments the gates refused on any machine: never offered again

The bucket must be private. R2_SDLIB_BUCKET equal to a bucket with a public r2.dev or custom domain turns the library off:
every object in those can be read by anyone with its name. Nothing here prints a key or a link.

What a pod picks is what tools/libpick.py picks: stations first, no anchors, reporters, graphics, maps or rooms (the same reject
labels), no text the crop keeps, no face over 0.4%, no openings or end cards, no moment in this customer's ledger, no shot
rejected anywhere, no banned source, no personality channel, no source whose title is about another place. Placement, caps and
cuts are the source bank's (src/srcbank.py), so a library shot is a bank shot to everything downstream.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from . import config

PREFIX = "sdlib/v1/"
CATALOG_KEY = PREFIX + "catalog.json"
PACK_KEY = PREFIX + "index_pack.npz"
TEXT_MODEL_KEY = PREFIX + "models/clip_b32_text.onnx"
REJECTED_KEY = PREFIX + "rejected.json"
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdkit", "libseed")

MIN_SHOT = 2.2                  # shorter shots cannot carry a line (tools/library.py)
SKIP_HEAD = 3.0                 # openings: a station's promo, a QR code, a logo
SKIP_TAIL = 8.0                 # end cards
MIN_P = 0.30                    # how sure the match must be (tools/libpick.py)
MAX_TEXT = 0.004
MAX_FACE = 0.004
PER_LINE = 60                   # candidates a line keeps for the placement's caps to choose from
PER_SOURCE_LINE = 14            # one source fills one line's list only so far (tools/libpick.py PER_SOURCE)
FLOOR = 0.25
FETCH_PARALLEL = 6
FETCH_TRIES = 3
FETCH_MAX_GB = 40.0             # a pod's disk: sources kept at once
CACHE_SECONDS = 3600.0
REJECT = {                      # tools/libpick.py
    "X_anchor": "a TV news anchor sitting at a desk in a television studio",
    "X_reporter": "a TV news reporter standing outdoors holding a microphone and talking to the camera",
    "X_interview": "a close-up of a person talking to the camera in an interview",
    "X_podium": "a person speaking at a podium or a news conference",
    "X_people": "a portrait of people looking at the camera",
    "X_graphic": "a TV news graphic, chart, map or weather map with text",
    "X_title": "a title card or end screen with large text or logos",
    "X_black": "a black or nearly black screen",
    "X_selfie": "a person filming a selfie vlog, holding the camera",
    "X_car": "the inside of a car or a road seen from a car",
    "X_room": "the inside of a house, an office or a meeting room",
    "X_crowd": "people sitting at a public meeting",
    "X_map": "a map or satellite image with pins, roads and labels",
    "X_split": "a split screen video call with several windows on a screen",
    "X_leisure": "tourists on vacation, people hiking, wakeboarding, jet skiing or on a speedboat",
    "X_close": "a close-up of a hand or an object filling the frame",
}

_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}
_JOB_BAD: List[list] = []
STATS: Dict[str, Any] = {}


def reset() -> None:
    """A new job: this job's rejected moments and report start empty (the loaded index stays, a batch reuses it)."""
    with _LOCK:
        _JOB_BAD.clear()
        STATS.clear()


# --------------------------------------------------------------------------- #
# Where it lives
# --------------------------------------------------------------------------- #
def bucket() -> str:
    """The private bucket, "" when none is set or the one set is public."""
    name = str(getattr(config, "R2_SDLIB_BUCKET", "") or "").strip()
    if not name:
        return ""
    public = {str(getattr(config, "R2_BUCKET", "") or "").strip(), str(getattr(config, "R2_LIBRARY_BUCKET", "") or "").strip()}
    if name in public:
        if not _CACHE.get("warned"):
            _CACHE["warned"] = True
            print("[sdlib] off: R2_SDLIB_BUCKET is one of the buckets with a public domain; the library needs a private one", flush=True)
        return ""
    return name


def enabled() -> bool:
    from . import r2
    return bool(getattr(config, "STORM_LIBRARY", True) and bucket() and r2._creds())


# --------------------------------------------------------------------------- #
# The kit's lists
# --------------------------------------------------------------------------- #
def _seed(name: str, default: Any) -> Any:
    key = "seed_" + name
    if key not in _CACHE:
        try:
            with open(os.path.join(SEED_DIR, name), encoding="utf-8") as f:
                _CACHE[key] = json.load(f)
        except (OSError, ValueError):
            _CACHE[key] = default
    return _CACHE[key]


def bad_sources() -> Set[str]:
    return set(_seed("bad_sources.json", []))


def bad_shots() -> Set[str]:
    return set(_seed("bad_shots.json", [])) | set(_CACHE.get("rejected") or ())


def station_modes() -> dict:
    """Tuned crops: {id: "news0.68@0.0"}; null = the full frame."""
    return dict(_seed("station_modes.json", {}))


def is_bad(vid: str, a: float, bad: Optional[Set[str]] = None) -> bool:
    """A shot rejected in any video: the same second, one either side (tools/library.py)."""
    bad = (bad_shots() | _job_bad_keys()) if bad is None else bad
    v = _bare(vid)
    return any(f"{v}@{round(float(a)) + d}" in bad for d in (-1, 0, 1))


def _job_bad_keys() -> Set[str]:
    with _LOCK:
        return {f"{r[0]}@{s}" for r in _JOB_BAD for s in range(int(r[1]), int(r[2]) + 1)}


def _bare(vid: str) -> str:
    v = str(vid or "")
    return v[3:] if v.startswith("yt:") else v


def remember_bad(vid: str, a: float, b: float) -> None:
    """A moment a gate refused: never offered again in this job, and on R2 for every later one (flush_bad)."""
    with _LOCK:
        _JOB_BAD.append([_bare(vid), float(a), float(b)])
    STATS["rejected"] = STATS.get("rejected", 0) + 1


def flush_bad() -> bool:
    """This job's refused moments into rejected.json. Two pods at once may lose each other's few: the gate catches them again."""
    if not enabled():
        return False
    keys = _job_bad_keys()
    if not keys:
        return False
    try:
        from . import r2
        raw = r2.get_bytes(REJECTED_KEY, bucket=bucket())
        have = set(json.loads(raw).get("shots") or []) if raw else set()
        r2.upload_bytes(json.dumps({"shots": sorted(have | keys), "updated": int(time.time())}, separators=(",", ":")).encode(),
                        REJECTED_KEY, bucket=bucket(), deadline=time.time() + 60)
        return True
    except Exception as e:  # noqa: BLE001 - the video goes on
        print(f"[sdlib] rejected moments not saved: {type(e).__name__}", flush=True)
        return False


# --------------------------------------------------------------------------- #
# The index
# --------------------------------------------------------------------------- #
class Index:
    """The library in memory: per-shot arrays plus the source table."""

    def __init__(self, sources: Dict[str, dict], ids: Sequence[str], src: Any, emb: Any, a: Any, b: Any, text: Any, text_top: Any, face: Any):
        import numpy as np
        self.sources, self.ids = sources, [str(x) for x in ids]
        self.src, self.emb = np.asarray(src), np.asarray(emb, np.float32)
        self.a, self.b = np.asarray(a, np.float32), np.asarray(b, np.float32)
        self.text, self.text_top = np.asarray(text, np.float32), np.asarray(text_top, np.float32)
        self.face = np.asarray(face, np.float32)

    def __len__(self) -> int:
        return len(self.a)


def load(get: Optional[Callable[[str], Optional[bytes]]] = None) -> Optional[Index]:
    """The index from R2, kept for an hour in this process (a batch's videos share it). None without a library."""
    import io
    import numpy as np
    if get is None and not enabled():
        return None
    hit = _CACHE.get("index")
    if get is None and hit is not None and time.time() - _CACHE.get("index_at", 0.0) < CACHE_SECONDS:
        return hit
    if get is None:
        from . import r2

        def get(key: str) -> Optional[bytes]:
            return r2.get_bytes(key, bucket=bucket(), timeout=180)
    t0 = time.time()
    try:
        cat = get(CATALOG_KEY)
        pack = get(PACK_KEY)
        if not cat or not pack:
            print("[sdlib] no index on the bucket yet", flush=True)
            return None
        sources = json.loads(cat).get("sources") or {}
        with np.load(io.BytesIO(pack)) as z:
            idx = Index(sources, list(z["ids"]), z["src"], z["emb"], z["a"], z["b"], z["text"], z["text_top"], z["face"])
        rej = get(REJECTED_KEY)
        if rej:
            _CACHE["rejected"] = set(json.loads(rej).get("shots") or [])
    except Exception as e:  # noqa: BLE001 - without the library the video goes on to its other rungs
        print(f"[sdlib] index not read: {type(e).__name__}: {str(e)[:160]}", flush=True)
        return None
    _CACHE["index"], _CACHE["index_at"] = idx, time.time()
    print(f"[sdlib] {len(idx.ids)} sources, {len(idx)} shots in {time.time() - t0:.1f} s", flush=True)
    return idx


# --------------------------------------------------------------------------- #
# Text embeddings (the same CLIP the shots were indexed with)
# --------------------------------------------------------------------------- #
def _text_session(work: str = "") -> Tuple[Any, Any]:
    if "text_session" in _CACHE:
        return _CACHE["text_session"]
    import onnxruntime as ort
    from tokenizers import Tokenizer
    from . import r2
    path = os.path.join(getattr(config, "WORK_DIR", "") or work or ".", "clip_b32_text.onnx")
    if not (os.path.isfile(path) and os.path.getsize(path) > 1000):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        _download(r2.presign(TEXT_MODEL_KEY, bucket=bucket(), expires=3600), path)
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, int(getattr(config, "LOCAL_VISION_THREADS", 4)))
    sess = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
    tok = Tokenizer.from_file(os.path.join(config.LOCAL_VISION_DIR, "tokenizer.json"))   # one CLIP vocabulary for every CLIP
    _CACHE["text_session"] = (sess, tok)
    return sess, tok


def embed_texts(texts: Sequence[str], work: str = "") -> Any:
    """Unit-length embeddings (N x 512)."""
    import numpy as np
    sess, tok = _text_session(work)
    name = sess.get_inputs()[0].name
    out = []
    memo = _CACHE.setdefault("text_memo", {})
    for t in texts:
        t = str(t or "").strip()[:300]
        if t not in memo:
            ids = (tok.encode(t).ids[:77] + [0] * 77)[:77]          # the exported model takes exactly 77 (open_clip pads with 0)
            v = sess.run(None, {name: np.array([ids], np.int64)})[0][0]
            memo[t] = v / max(1e-8, float(np.linalg.norm(v)))
        out.append(memo[t])
    return np.stack(out)


# --------------------------------------------------------------------------- #
# Which shots may be offered
# --------------------------------------------------------------------------- #
def place_rx(inp: Optional[dict], story: Optional[dict] = None) -> Optional[Any]:
    from . import stormdesk
    return stormdesk.place_regex(inp, story)


def free_part(a: float, b: float, used: Sequence[Tuple[float, float]], min_len: float = MIN_SHOT) -> Optional[Tuple[float, float]]:
    """The longest stretch of [a, b] no earlier video used, or None (tools/library.py)."""
    gaps, cur = [], a
    for x, y in sorted(u for u in used if u[1] > a and u[0] < b):
        if x > cur:
            gaps.append((cur, x))
        cur = max(cur, y)
    if cur < b:
        gaps.append((cur, b))
    best = max(gaps, key=lambda g: g[1] - g[0], default=None)
    return best if best and best[1] - best[0] >= min_len else None


def _source_kind(meta: dict) -> str:
    from . import stormdesk, stormledger
    ch = str(meta.get("channel") or "")
    if stormledger.is_personality(ch):
        return "personality"
    return stormdesk.source_kind(ch, str(meta.get("title") or ""))


def usable(idx: Index, led: Any, rx: Optional[Any], blocked: Optional[Set[str]] = None) -> Tuple[Any, Dict[int, Tuple[float, float]], Dict[str, int]]:
    """(mask over the shots, their free stretch by shot number, why the rest were dropped)."""
    import numpy as np
    n = len(idx)
    keep = np.zeros(n, bool)
    free: Dict[int, Tuple[float, float]] = {}
    why = {"source": 0, "place": 0, "short_or_edge": 0, "face": 0, "text": 0, "used_or_rejected": 0}
    ok_src, kind_of = {}, {}
    bad = bad_sources() | set(blocked or ())
    for k, vid in enumerate(idx.ids):
        meta = idx.sources.get(vid) or {}
        kind = _source_kind(meta) if meta else "none"
        kind_of[k] = kind
        if vid in bad or not meta or kind in ("personality", "reupload", "unknown", "none"):
            ok_src[k] = 0
        elif rx is not None and not rx.search(str(meta.get("title") or "")):
            ok_src[k] = -1
        else:
            ok_src[k] = 1
    badset = bad_shots() | _job_bad_keys()
    for i in range(n):
        s = int(idx.src[i])
        st = ok_src.get(s, 0)
        if st != 1:
            why["source" if st == 0 else "place"] += 1
            continue
        vid = idx.ids[s]
        meta = idx.sources[vid]
        a, b = float(idx.a[i]), float(idx.b[i])
        dur = float(meta.get("dur") or 0.0)
        if b - a < MIN_SHOT or a < SKIP_HEAD or (dur and b > dur - SKIP_TAIL):
            why["short_or_edge"] += 1
            continue
        if float(idx.face[i]) > MAX_FACE:
            why["face"] += 1
            continue
        text = float(idx.text_top[i]) if kind_of[s] == "station" else float(idx.text[i])
        if text > MAX_TEXT:
            why["text"] += 1
            continue
        if is_bad(vid, a, badset):
            why["used_or_rejected"] += 1
            continue
        used = led.ranges(vid) if led is not None else []
        fr = free_part(a + 0.3, b - 0.3, used)
        if fr is None:
            why["used_or_rejected"] += 1
            continue
        keep[i] = True
        free[i] = (round(fr[0], 2), round(fr[1], 2))
    return keep, free, why


def line_text(j: dict) -> str:
    """What the shot should show, in the words a CLIP prompt uses."""
    t = str(j.get("intent") or j.get("query") or j.get("context") or "").strip()
    place = str(j.get("place") or "").strip()
    return f"{t} {place}".strip()[:280] or "water"


def rank(idx: Index, lines: Sequence[dict], keep: Any, free: Dict[int, Tuple[float, float]], embed: Callable[[Sequence[str]], Any],
         relaxed: bool = False) -> Dict[int, List[Tuple[int, float]]]:
    """line index -> [(shot number, fit 0..1)] best first. A shot goes to a line only when the line beats every reject label by
    tools/libpick.py's score (relaxed: the line beats them, however unsure). Stations rank above anyone else."""
    import numpy as np
    if not lines or not keep.any():
        return {}
    shots = np.nonzero(keep)[0]
    T = embed([line_text(j) for j in lines])
    R = embed(list(REJECT.values()))
    E = idx.emb[shots]
    S, X = E @ T.T, E @ R.T
    xbest = X.max(axis=1)
    xsum = np.exp(100.0 * (X - xbest[:, None])).sum(axis=1)
    kinds = {k: _source_kind(idx.sources.get(v) or {}) for k, v in enumerate(idx.ids)}
    out: Dict[int, List[Tuple[int, float]]] = {}
    for c, j in enumerate(lines):
        s = S[:, c]
        d = np.clip(100.0 * (s - xbest), -50.0, 50.0)
        p = np.exp(d) / (np.exp(d) + xsum)
        good = (s > xbest) if relaxed else (p >= MIN_P)
        order = np.argsort(-s)
        rows, per = [], {}
        need = float(j.get("seconds") or 3.0) + 0.3
        for o in order:
            if not good[o]:
                continue
            i = int(shots[o])
            fr = free.get(i)
            if fr is None or fr[1] - fr[0] < need:
                continue
            k = int(idx.src[i])
            per[k] = per.get(k, 0) + 1
            if per[k] > PER_SOURCE_LINE:
                continue
            near = max(0.0, min(1.0, (float(s[o]) - 0.12) / 0.2))
            # Stations and agencies first, then the best match (tools/libpick.py): their worst outranks anyone else's best.
            rows.append((i, round(0.6 + 0.4 * near if kinds[k] in ("station", "original") else 0.3 + 0.25 * near, 3)))
            if len(rows) >= PER_LINE:
                break
        out[int(j["index"])] = sorted(rows, key=lambda r: -r[1])
    return out


# --------------------------------------------------------------------------- #
# Sources on this disk
# --------------------------------------------------------------------------- #
def _download(url: str, path: str, want: int = 0, tries: int = FETCH_TRIES, get: Optional[Callable] = None) -> None:
    import requests
    get = get or (lambda u: requests.get(u, stream=True, timeout=60))
    tmp = path + ".part"
    last: Optional[Exception] = None
    for k in range(tries):
        try:
            with get(url) as r:
                if getattr(r, "status_code", 200) != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if want and os.path.getsize(tmp) != want:
                raise RuntimeError(f"{os.path.getsize(tmp)} bytes, wanted {want}")
            os.replace(tmp, path)
            return
        except Exception as e:  # noqa: BLE001 - tried again; the message never carries the link
            last = RuntimeError(type(e).__name__)
            time.sleep(1.0 + k)
    raise RuntimeError(f"library source not fetched: {last}")


def fetch_source(vid: str, meta: dict, work: str, get: Optional[Callable] = None) -> str:
    """The source's file on this disk (one download per source), <work>/bank/<id>.mp4 so the bank's helpers find it. "" on failure."""
    from . import r2
    folder = os.path.join(work, "bank")
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"{vid}.mp4")
    if os.path.isfile(out) and os.path.getsize(out) > 10000:
        return out
    try:
        key = str(meta.get("key") or f"{PREFIX}src/{vid}.mp4")
        _download(r2.presign(key, bucket=bucket(), expires=3600), out, int(meta.get("size") or 0), get=get)
    except Exception as e:  # noqa: BLE001
        print(f"[sdlib] {vid}: {str(e)[:120]}", flush=True)
        return ""
    STATS["fetchedBytes"] = STATS.get("fetchedBytes", 0) + os.path.getsize(out)
    STATS["fetchedSources"] = STATS.get("fetchedSources", 0) + 1
    return out


def ensure_source(video_id: str, work: str) -> str:
    """A library source's file for a pause clip ("" when it is not in the library)."""
    idx = _CACHE.get("index")
    vid = _bare(video_id)
    meta = (idx.sources.get(vid) if idx is not None else None) or None
    if not meta or not enabled():
        return ""
    path = fetch_source(vid, meta, work)
    if path:
        from . import srcbank
        for src in srcbank._STATE.get("sources") or []:
            if src.id == vid and not src.path:
                src.path = path
    return path


# --------------------------------------------------------------------------- #
# Placing
# --------------------------------------------------------------------------- #
def _register(idx: Index, shots: Set[int], free: Dict[int, Tuple[float, float]]) -> List[Any]:
    """The shots as the source bank's pieces, each source once in its state, already reviewed and approved."""
    from . import srcbank, ytdlp
    st = srcbank._STATE
    known = {s.id: k for k, s in enumerate(st["sources"])}
    by_shot: List[Any] = []
    for i in sorted(shots):
        vid = idx.ids[int(idx.src[i])]
        if vid not in known:
            meta = idx.sources[vid]
            source = srcbank.Source(id=vid, title=str(meta.get("title") or ""), channel=str(meta.get("channel") or ""),
                                    duration=float(meta.get("dur") or 0.0), upload_date=str(meta.get("date") or ""),
                                    width=int(meta.get("w") or 0), height=int(meta.get("h") or 0),
                                    kind=_source_kind(meta), cached=True, library=True)
            st["sources"].append(source)
            known[vid] = len(st["sources"]) - 1
            st["ids"].add(vid)
            if source.duration:
                with ytdlp._INFO_LOCK:
                    ytdlp._DURATION[vid] = source.duration
        k = known[vid]
        a, b = free[i]
        p = srcbank.Piece(src=k, n=int(i), start=a, end=b, take=int(i), take_end=b, ok=True, desc=st["sources"][k].title[:90], quality=0.7)
        p.vec = idx.emb[i]
        st["sources"][k].pieces.append(p)
        by_shot.append(p)
    return by_shot


def _cut_one(p: Any, a: float, b: float, job: dict, fit: float) -> Optional[Any]:
    from . import filters, srcbank
    src = srcbank._STATE["sources"][p.src]
    if not src.path:
        p.bad = True
        return None
    path = filters.trim_clip(src.path, a, b - a)
    if not path:
        p.bad = True
        return None
    asset = srcbank.asset_for(p, a, b, job, path, fit=fit)
    asset.pool = {**(getattr(asset, "pool", None) or {}), "library": True}
    return asset


def _over_creator_cap(plan: Dict[int, tuple], srcs: Sequence[Any], per_creator: Dict[str, int]) -> List[int]:
    """Lines placed on a person's own channel past its 2 shots (tools/channels.py): that channel's other shots go, so a later line
    never takes them. Counted over the whole video in `per_creator`."""
    from . import stormledger
    over: List[int] = []
    for i in sorted(plan):
        src = srcs[plan[i][0].src]
        if src.kind != "creator":
            continue
        per_creator[src.channel] = per_creator.get(src.channel, 0) + 1
        if per_creator[src.channel] > stormledger.CREATOR_SHOTS:
            over.append(i)
            per_creator[src.channel] = stormledger.CREATOR_SHOTS
            for s in srcs:
                if s.channel == src.channel:
                    for q in s.pieces:
                        q.bad = True
    return over


def place_and_cut(idx: Index, lines: Sequence[dict], ranks: Dict[int, List[Tuple[int, float]]], free: Dict[int, Tuple[float, float]], work: str,
                  *, floor: float = FLOOR, relax: float = 1.0, neighbours: Optional[Dict[int, str]] = None,
                  fetch: Optional[Callable[[str, dict, str], str]] = None) -> Dict[int, Any]:
    """Placement by the bank's rules (share caps, no source twice in a row, no moment twice, look-alikes), only the sources
    placed fetched, the shots cut. A source that cannot be fetched gives way and its lines are placed again."""
    from . import srcbank
    fetch = fetch or fetch_source
    shots = {i for rows in ranks.values() for i, _f in rows}
    pieces = {i: p for i, p in zip(sorted(shots), _register(idx, shots, free))}
    pid_ranks = {ln: [(pieces[i].pid, f) for i, f in rows] for ln, rows in ranks.items()}
    srcs = srcbank._STATE["sources"]
    out: Dict[int, Any] = {}
    todo = list(lines)
    per_creator: Dict[str, int] = {}
    for _round in range(4):
        if not todo:
            break
        plan = srcbank.place(todo, pid_ranks, list(pieces.values()), floor=floor, relax=relax, neighbours=neighbours)
        if not plan:
            break
        over = _over_creator_cap(plan, srcs, per_creator)
        if over:
            jobs_ = {j["index"]: j for j in lines}
            for i in over:
                srcbank.release(i)
                plan.pop(i)
            todo = [jobs_[i] for i in over] + [j for j in todo if j["index"] in plan]
            for rnd_i in list(plan):            # placed again together, so the freed lines see what the others took
                srcbank.release(rnd_i)
            plan = srcbank.place(todo, pid_ranks, list(pieces.values()), floor=floor, relax=relax, neighbours=neighbours)
            if not plan:
                break
        need = sorted({srcs[v[0].src].id for v in plan.values() if not srcs[v[0].src].path})

        def get_one(vid: str) -> Tuple[str, str]:
            return vid, fetch(vid, idx.sources[vid], work)
        if need:
            with ThreadPoolExecutor(FETCH_PARALLEL) as ex:
                for vid, path in ex.map(get_one, need):
                    for s in srcs:
                        if s.id == vid:
                            s.path = path
                            if not path:
                                s.why = "library fetch failed"
                                for q in s.pieces:
                                    q.bad = True
        jobs = {j["index"]: j for j in todo}
        with ThreadPoolExecutor(max(1, int(getattr(config, "SOURCE_BANK_CUT_PARALLEL", 6)))) as ex:
            got = dict(zip(plan.keys(), ex.map(lambda kv: _cut_one(kv[1][0], kv[1][1], kv[1][2], jobs[kv[0]], kv[1][3]), plan.items())))
        retry = []
        for i, asset in got.items():
            if asset is None:
                srcbank.release(i)
                retry.append(jobs[i])
            else:
                out[i] = asset
        todo = retry
    return out


def fill(jobs: Sequence[dict], work: str, *, inp: Optional[dict] = None, story: Optional[dict] = None, led: Any = None,
         index: Optional[Index] = None, embed: Optional[Callable] = None, fetch: Optional[Callable] = None,
         report: Optional[Callable] = None) -> Dict[int, Any]:
    """line index -> MediaAsset for the lines the library fills, before any search. Never raises: {} sends them to the bank."""
    from . import srcbank
    t0 = time.time()
    try:
        idx = index if index is not None else load()
        if idx is None or not len(idx):
            return {}
        lines = srcbank.line_jobs(jobs)
        if not lines:
            return {}
        if report:
            report(f"Searching the footage library for {len(lines)} lines", 22)
        srcbank._STATE["total"] = srcbank._STATE.get("total") or sum(float(j.get("seconds") or 0.0) for j in jobs)
        srcbank._STATE["work"] = srcbank._STATE.get("work") or work
        keep, free, dropped = usable(idx, led, place_rx(inp, story), srcbank._STATE.get("blocked_ids"))
        ranks = rank(idx, lines, keep, free, embed or (lambda t: embed_texts(t, work)))
        STATS.update(searchSeconds=round(time.time() - t0, 2), shots=len(idx), offered=int(keep.sum()), dropped=dropped)
        got = place_and_cut(idx, lines, ranks, free, work, fetch=fetch)
        STATS.update(filled=STATS.get("filled", 0) + len(got), seconds=round(time.time() - t0, 2))
        print(f"[sdlib] {len(got)} of {len(lines)} lines filled: {json.dumps(STATS)[:300]}", flush=True)
        return got
    except Exception as e:  # noqa: BLE001 - the library never fails a video
        print(f"[sdlib] stopped: {type(e).__name__}: {str(e)[:200]}", flush=True)
        STATS["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return {}


def fill_scenes(jobs: Sequence[dict], work: str, *, inp: Optional[dict] = None, story: Optional[dict] = None,
                index: Optional[Index] = None, embed: Optional[Callable] = None, fetch: Optional[Callable] = None,
                led: Any = None) -> Dict[int, Any]:
    """The ladder's rung: shots with nothing to show, any free shot of the story, however unsure, as long as it is not an anchor
    or a graphic. {} when the library has nothing."""
    from . import srcbank, stormdesk
    try:
        idx = index if index is not None else load()
        if idx is None or not len(idx):
            return {}
        led = led if led is not None else stormdesk.JOB_LEDGER
        srcbank._STATE["work"] = srcbank._STATE.get("work") or work
        keep, free, _d = usable(idx, led, place_rx(inp, story), srcbank._STATE.get("blocked_ids"))
        ranks = rank(idx, jobs, keep, free, embed or (lambda t: embed_texts(t, work)), relaxed=True)
        got = place_and_cut(idx, jobs, ranks, free, work, floor=0.0, relax=float(getattr(config, "SOURCE_BANK_GAP_RELAX", 1.5)), fetch=fetch)
        STATS["ladderFilled"] = STATS.get("ladderFilled", 0) + len(got)
        return got
    except Exception as e:  # noqa: BLE001
        print(f"[sdlib] ladder stopped: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return {}


def report() -> dict:
    return dict(STATS)
