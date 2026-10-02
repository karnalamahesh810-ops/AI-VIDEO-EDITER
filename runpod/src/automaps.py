"""
Auto maps: when the narration names a river, a lake or reservoir, a dam or a
canal, show that feature drawn on real geography - the river along its true
course, the reservoir's outline, the dam where it stands.

Nothing is invented. A feature is mapped only when the line names it (the names
and aliases come from the bundled geodata, src/geodata/, built by
scripts/build_geo.py from Natural Earth and public records), the geometry is the
geodata's, and the labels are the feature's own name. A bare name that is also a
state or a city ("Colorado", "Columbia") counts only as "the Colorado" with river
words in the same sentence; a name two rivers share is mapped only when the
context picks one (hints) or one is plainly meant (primary) - else no map.

plan_for_line() is what treatments.py calls (behind config.AUTO_MAPS). It returns
a request - the look, the word to land on, the geometry document the renderer
draws (overlay "geo") - or None. Pure functions, no network, deterministic.
"""
import json
import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

GEODIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geodata")
PRECISION = 1000

LOOK_RIVER = "LIB_GEO_RIVER_TRACE"      # a river or a canal traced along its course
LOOK_RESERVOIR = "LIB_GEO_RESERVOIR"    # a lake, a reservoir or a dam
LOOKS = (LOOK_RIVER, LOOK_RESERVOIR)

MAX_LINE_POINTS = 420                    # a line in the document is thinned to this many points
MAX_RING_POINTS = 260
STRETCH_KM = 700.0                       # a river longer than this is framed on the stretch the story is about
STRETCH_HALF_KM = 300.0                  # ... around the one place it names
NEAR_RIVER_KM = 40.0                     # a named place is "on" a river when it is this close to its line
RING_NEAR_KM = 10.0                      # a dam this far from its reservoir's outline is pinned without it

_RIVER_CONTEXT = re.compile(
    r"\b(rivers?|flows?|flowing|flowed|downstream|upstream|tributar\w+|watershed|basin|delta|canyon|snowmelt|headwaters?|"
    r"mouth|dams?|reservoirs?|lakes?|water from|diverts?|diverted|stretch(?:es)?|miles long|banks?|floods?|flooding|"
    r"drought|runs? (?:through|along|from|into))\b", re.I)
_PROPER_AFTER = re.compile(r"\s+([A-Z][\w'-]*)")


# ------------------------------------------------------------------ the geodata
def norm(text: str) -> str:
    s = str(text or "").lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' .-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return re.sub(r"^the ", "", s)


def decode(text: str, scale: int = PRECISION) -> List[List[float]]:
    """Google polyline text -> [[lon, lat], ...]."""
    pts: List[List[float]] = []
    i = lon = lat = 0
    while i < len(text):
        pair = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(text[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            pair.append(~(result >> 1) if result & 1 else result >> 1)
        lat += pair[0]
        lon += pair[1]
        pts.append([lon / scale, lat / scale])
    return pts


def hav_km(a: Sequence[float], b: Sequence[float]) -> float:
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(h)))


class Geodata:
    """The bundled files, read once, with an index of every name a story may use."""

    def __init__(self, folder: str = GEODIR):
        def load(name: str, key: str) -> list:
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    return json.load(fh).get(key) or []
            except (OSError, ValueError):
                return []
        self.rivers = load("rivers.json", "rivers")
        self.lakes = load("lakes.json", "lakes")
        self.canals = load("canals.json", "canals")
        self.dams = load("dams.json", "dams")
        self.by_id: Dict[str, dict] = {}
        self.explicit: Dict[str, List[Tuple[str, dict]]] = {}     # alias -> [(kind, record)]
        self.bare: Dict[str, List[dict]] = {}                     # "colorado" -> rivers said as "the Colorado"
        for kind, recs in (("river", self.rivers), ("lake", self.lakes), ("canal", self.canals), ("dam", self.dams)):
            for rec in recs:
                rec["_kind"] = kind
                self.by_id[kind + ":" + rec["id"]] = rec
                for a in rec.get("aliases") or []:
                    a = norm(a)
                    if a:
                        self.explicit.setdefault(a, []).append((kind, rec))
                for a in rec.get("bare") or []:
                    self.bare.setdefault(norm(a), []).append(rec)
        names = sorted(self.explicit, key=lambda s: (-len(s), s))
        self._rx = re.compile(r"(?<![\w])(?:the\s+)?(" + "|".join(re.escape(n).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]") for n in names)
                              + r")(?![\w])", re.I) if names else None
        bare = sorted(self.bare, key=lambda s: (-len(s), s))
        self._bare_rx = re.compile(r"(?<![\w])the\s+(" + "|".join(re.escape(n) for n in bare) + r")(?![\w])", re.I) if bare else None

    def river(self, rid: str) -> Optional[dict]:
        return self.by_id.get("river:" + rid)

    def lake(self, name: str) -> Optional[dict]:
        n = norm(name)
        return next((l for l in self.lakes if norm(l["name"]) == n), None)


_DATA: Optional[Geodata] = None


def data() -> Geodata:
    global _DATA
    if _DATA is None:
        _DATA = Geodata()
    return _DATA


# ------------------------------------------------------------------ detection
def _capitalised(text: str, start: int, end: int) -> bool:
    """The name is written as a name: its first letter is a capital (not 'the green river' / 'a salt river')."""
    return text[start:end][:1].isupper()


def find_names(text: str, g: Optional[Geodata] = None) -> List[dict]:
    """
    Every feature the line names, in the order said:
    {"kind", "rec", "start", "end", "form", "bare"}.  A river said bare ("the Colorado") needs river words in the
    sentence and no proper noun after it ("the Colorado Rockies").
    """
    g = g or data()
    out: List[dict] = []
    text = text or ""
    if g._rx:
        for m in g._rx.finditer(text):
            if not _capitalised(text, m.start(1), m.end(1)):
                continue
            form = norm(re.sub(r"[\s-]+", " ", m.group(1)))
            for kind, rec in g.explicit.get(form) or g.explicit.get(norm(m.group(1))) or []:
                out.append({"kind": kind, "rec": rec, "start": m.start(1), "end": m.end(1), "form": form, "bare": False})
    if g._bare_rx and _RIVER_CONTEXT.search(text):
        for m in g._bare_rx.finditer(text):
            if not _capitalised(text, m.start(1), m.end(1)):
                continue
            after = _PROPER_AFTER.match(text, m.end(1))
            if after:
                continue            # "the Colorado Rockies", "the Mississippi Delta": a different proper name
            if any(o["start"] <= m.start(1) < o["end"] for o in out):
                continue
            form = norm(m.group(1))
            for rec in g.bare.get(form, []):
                out.append({"kind": "river", "rec": rec, "start": m.start(1), "end": m.end(1), "form": form, "bare": True})
    out.sort(key=lambda o: (o["start"], -(o["end"] - o["start"])))
    return out


def resolve(cands: List[dict], context: str) -> Optional[dict]:
    """One feature among those that share a name: the one the context points to, else the one plainly meant, else None."""
    recs = {id(c["rec"]): c for c in cands}
    cands = list(recs.values())
    if len(cands) == 1:
        return cands[0]
    ctx = norm(context)
    scored = []
    for c in cands:
        hits = sum(1 for h in c["rec"].get("hints") or [] if h and re.search(r"(?<![a-z])" + re.escape(h) + r"(?![a-z])", ctx))
        scored.append((hits, c))
    best = max(h for h, _c in scored)
    if best > 0:
        top = [c for h, c in scored if h == best]
        if len(top) == 1:
            return top[0]
    primary = [c for c in cands if c["rec"].get("primary")]
    if len(primary) == 1 and best == 0:
        return primary[0]
    return None


# ------------------------------------------------------------------ geometry
def thin(pts: List[List[float]], limit: int) -> List[List[float]]:
    """Douglas-Peucker with a growing tolerance until the line has at most `limit` points."""
    if len(pts) <= limit:
        return pts
    tol = 0.004
    out = pts
    while len(out) > limit and tol < 1.0:
        out = _dp(pts, tol)
        tol *= 1.4
    return out


def _dp(pts: List[List[float]], tol: float) -> List[List[float]]:
    n = len(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        dx, dy = pts[b][0] - ax, pts[b][1] - ay
        l2 = dx * dx + dy * dy
        best, at = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if l2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, at = d, i
        if best > tol:
            keep[at] = True
            stack.append((a, at))
            stack.append((at, b))
    return [p for p, k in zip(pts, keep) if k]


def _round(pts: List[List[float]]) -> List[List[float]]:
    return [[round(p[0], 3), round(p[1], 3)] for p in pts]


def line_km(pts: Sequence[Sequence[float]]) -> float:
    return sum(hav_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _along(pts: List[List[float]]) -> List[float]:
    out, d = [0.0], 0.0
    for i in range(len(pts) - 1):
        d += hav_km(pts[i], pts[i + 1])
        out.append(d)
    return out


def nearest_vertex(pts: List[List[float]], p: Sequence[float]) -> Tuple[int, float]:
    best = (0, 1e18)
    for i, q in enumerate(pts):
        d = hav_km(q, p)
        if d < best[1]:
            best = (i, d)
    return best


def bbox_of(groups: Sequence[Sequence[Sequence[float]]]) -> List[float]:
    xs = [p[0] for g in groups for p in g]
    ys = [p[1] for g in groups for p in g]
    return [min(xs), min(ys), max(xs), max(ys)]


def pad_box(b: List[float], margin: float = 0.18, min_span: float = 0.5) -> List[float]:
    """The frame: the box plus a margin, never narrower than min_span degrees, and never taller than wide by more than the screen."""
    w, s, e, n = b
    cx, cy = (w + e) / 2, (s + n) / 2
    hw = max((e - w) * (1 + 2 * margin) / 2, min_span / 2)
    hh = max((n - s) * (1 + 2 * margin) / 2, min_span / 2 * 0.6)
    return [round(cx - hw, 3), round(cy - hh, 3), round(cx + hw, 3), round(cy + hh, 3)]


def clip_line(pts: List[List[float]], box: List[float], grow: float = 0.6) -> List[List[List[float]]]:
    """The parts of a line inside the box grown by `grow` of its size (one point past each edge kept)."""
    w, s, e, n = box
    gw, gh = (e - w) * grow, (n - s) * grow
    w, s, e, n = w - gw, s - gh, e + gw, n + gh
    inside = [w <= p[0] <= e and s <= p[1] <= n for p in pts]
    parts, cur = [], []
    for i, p in enumerate(pts):
        if inside[i]:
            if not cur and i > 0:
                cur.append(pts[i - 1])
            cur.append(p)
        else:
            if cur:
                cur.append(p)
                parts.append(cur)
                cur = []
    if cur:
        parts.append(cur)
    return [pt for pt in parts if len(pt) >= 2]


def _label(rec: dict) -> str:
    return str(rec.get("name") or "").upper()


def trigger_word(text: str, start: int, end: int, rec: dict) -> str:
    """The word to land on: the first word of the name as said that is not a generic one."""
    skip = {"the", "lake", "river", "dam", "canal", "aqueduct", "reservoir"}
    for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text[start:end]):
        if w.lower() not in skip:
            return w
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", text[start:end])
    return words[0] if words else str(rec.get("name") or "")


def river_doc(rec: dict, places: List[dict], kind: str = "river") -> dict:
    """The geometry document for a river or a canal: its line, framed on the stretch the story is about."""
    lines = [decode(t) for t in rec["lines"]]
    main = max(lines, key=line_km)
    total = line_km(main)
    along = _along(main)
    marks = []
    for p in places:
        i, d = nearest_vertex(main, [p["lon"], p["lat"]])
        if d <= NEAR_RIVER_KM:
            marks.append(i)
    lo, hi = 0, len(main) - 1
    stretch = False
    if len(set(marks)) >= 2 and along[max(marks)] - along[min(marks)] >= 0.05 * total:
        lo, hi = min(marks), max(marks)
        stretch = True
    elif len(marks) >= 1 and total > STRETCH_KM:
        mid = along[marks[0]]
        lo = next(i for i, a in enumerate(along) if a >= mid - STRETCH_HALF_KM)
        hi = max(i for i, a in enumerate(along) if a <= mid + STRETCH_HALF_KM)
        stretch = True
    focus = main[lo:hi + 1] if stretch else [p for ln in lines for p in ln]
    box = pad_box(bbox_of([focus]), 0.16, 0.6)
    drawn: List[List[List[float]]] = []
    for ln in lines:
        for part in (clip_line(ln, box) if stretch else [ln]):
            drawn.append(_round(thin(part, MAX_LINE_POINTS)))
    pins = [{"label": p["label"], "lat": round(p["lat"], 4), "lon": round(p["lon"], 4), "kind": p.get("kind", "")}
            for p in places if box[0] <= p["lon"] <= box[2] and box[1] <= p["lat"] <= box[3]
            and nearest_vertex(main, [p["lon"], p["lat"]])[1] <= NEAR_RIVER_KM]
    return {"kind": kind, "name": rec["name"], "label": _label(rec), "bbox": box, "lines": drawn,
            "flow": bool(rec.get("flow")), "approx": bool(rec.get("approx")), "pins": pins[:3], "stretch": stretch}


def reservoir_doc(g: Geodata, lake: Optional[dict], dams: List[dict]) -> Optional[dict]:
    """A lake or reservoir (its outline) with the dam(s) named; a dam alone is framed round its pin."""
    rings = [decode(t) for t in lake["rings"]] if lake else []
    pins = [{"label": d["name"], "lat": d["lat"], "lon": d["lon"], "kind": "dam"} for d in dams]
    if rings and pins:
        near = min(hav_km([p["lon"], p["lat"]], q) for p in pins for r in rings for q in r)
        if near > RING_NEAR_KM:
            rings = []                       # the outline stops short of the dam: pin it alone
    if not rings and not pins:
        return None
    context = []
    river_rec = None
    for d in dams:
        river_rec = river_rec or (g.river(d["river"]) if d.get("river") else None)
    focus: List[List[float]] = [p for r in rings for p in r] + [[p["lon"], p["lat"]] for p in pins]
    if rings:
        box = pad_box(bbox_of([focus]), 0.22, 0.4)
    else:
        box = pad_box(bbox_of([focus]), 0.0, 0.5)
    if river_rec:
        main = max((decode(t) for t in river_rec["lines"]), key=line_km)
        for part in clip_line(main, box, 0.3)[:2]:
            context.append(_round(thin(part, 160)))
    name = lake["name"] if lake else dams[0]["name"]
    return {"kind": "reservoir" if rings else "dam", "name": name, "label": name.upper(), "bbox": box,
            "rings": [_round(thin(r, MAX_RING_POINTS)) for r in rings], "context": context, "pins": pins[:3],
            "river": river_rec["name"] if river_rec else ""}


# ------------------------------------------------------------------ the plan for a line
def plan_for_line(text: str, context: str = "", places: Optional[List[dict]] = None, used: Optional[set] = None,
                  g: Optional[Geodata] = None) -> Optional[dict]:
    """
    The auto map a line asks for, or None: {"id", "kind", "look", "key", "label", "geo"}.
    `context`: other words that say where the story is (the lines around, the brief); `places`: geocoded places the
    story names ({"label", "lat", "lon"}) - they frame the stretch of a long river; `used`: ids already mapped in
    this section (one auto map per feature per section).
    """
    g = g or data()
    used = used if used is not None else set()
    found = find_names(text, g)
    if not found:
        return None
    ctx = " ".join([text or "", context or ""])
    # group the matches that share a position (the same name for two rivers) and keep the first said that resolves
    groups: Dict[Tuple[int, int], List[dict]] = {}
    for f in found:
        groups.setdefault((f["start"], f["end"]), []).append(f)
    chosen: List[dict] = []
    for (_s, _e), cands in sorted(groups.items()):
        c = resolve(cands, ctx)
        if c is not None:
            chosen.append(c)
    if not chosen:
        return None
    dams = [c for c in chosen if c["kind"] == "dam"]
    lakes = [c for c in chosen if c["kind"] == "lake"]
    first = chosen[0]
    # a dam and its reservoir named together are one map
    if first["kind"] in ("dam", "lake"):
        lake_rec = lakes[0]["rec"] if lakes else None
        dam_recs = [d["rec"] for d in dams]
        if not lake_rec and dam_recs and dam_recs[0].get("lake"):
            lake_rec = g.lake(dam_recs[0]["lake"])
        fid = "lake:" + (lake_rec["id"] if lake_rec else "dam:" + dam_recs[0]["id"])
        if fid in used:
            return None
        doc = reservoir_doc(g, lake_rec, dam_recs)
        if not doc:
            return None
        word = trigger_word(text, first["start"], first["end"], first["rec"])
        return {"id": fid, "kind": doc["kind"], "look": LOOK_RESERVOIR, "key": word, "label": doc["label"], "geo": doc}
    rec = first["rec"]
    fid = first["kind"] + ":" + rec["id"]
    if fid in used:
        return None
    pl = list(places or [])
    pl += [{"label": d["rec"]["name"], "lat": d["rec"]["lat"], "lon": d["rec"]["lon"], "kind": "dam"} for d in dams]
    for l in lakes:
        b = l["rec"]["bbox"]
        pl.append({"label": l["rec"]["name"], "lat": (b[1] + b[3]) / 2, "lon": (b[0] + b[2]) / 2, "kind": "lake"})
    doc = river_doc(rec, pl, first["kind"])
    word = trigger_word(text, first["start"], first["end"], rec)
    return {"id": fid, "kind": first["kind"], "look": LOOK_RIVER, "key": word, "label": doc["label"], "geo": doc}
