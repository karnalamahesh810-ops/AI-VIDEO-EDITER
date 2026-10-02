#!/usr/bin/env python3
"""
Builds the bundled geodata of the auto maps (src/geodata/*.json) - reproducibly.

    python scripts/build_geo.py [--cache DIR] [--offline]

What it makes (all of it public domain, see src/geodata/README.md):

  rivers.json   named rivers, each a chain of lines from Natural Earth 1:10m
                "rivers_lake_centerlines" and its North America supplement
                (the river through its lakes, joined end to end), simplified
                and delta-coded (Google polyline, 1e-3 degrees);
  lakes.json    named lakes and reservoirs: the outline of Natural Earth 1:10m
                "lakes" and its North America supplement;
  canals.json   canals and aqueducts: coarse traces through public landmarks
                (hand-kept here, marked approximate) plus the few canals
                Natural Earth draws;
  dams.json     is NOT built here: it is a hand-kept list (name, coordinates,
                river, reservoir). This script only checks it against the
                lakes and rivers it names.

Nothing is downloaded at run time of the worker: the files are committed.
Run this only to rebuild them; --offline reads the sources from --cache and
fails if one is missing. The sources are pinned (a release tag, a SHA-256).
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "src", "geodata")

# ------------------------------------------------------------------ sources (pinned)
NE_TAG = "v5.1.2"
NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/" + NE_TAG + "/geojson/"
NE_FILES = {
    "ne_10m_rivers_lake_centerlines": "",
    "ne_10m_rivers_north_america": "",
    "ne_10m_lakes": "",
    "ne_10m_lakes_north_america": "",
}

PRECISION = 1000                 # degrees x 1000 = 111 m: finer than the simplification below
RIVER_TOL = 0.006                # Douglas-Peucker tolerance in degrees (~600 m: under 1.5 px at the closest framing)
LAKE_TOL = 0.006
JOIN_TOL = 0.03                  # two line ends closer than this are the same point (degrees)
BRANCH_MIN = 0.15                # a side branch shorter than this share of the main chain is left out
NA_MAX_RANK = 10                 # the North America supplement's smallest rivers are creeks: scalerank above this is dropped


# ------------------------------------------------------------------ geometry helpers
def norm(text: str) -> str:
    """A name as compared: lower case, no accents, single spaces, no leading 'the'."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9' .-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return re.sub(r"^the ", "", s)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")


def hav_km(a: Sequence[float], b: Sequence[float]) -> float:
    """Great-circle distance in km between (lon, lat) points."""
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(h)))


def line_km(pts: Sequence[Sequence[float]]) -> float:
    return sum(hav_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def bbox_of(lines: Iterable[Sequence[Sequence[float]]]) -> List[float]:
    xs = [p[0] for ln in lines for p in ln]
    ys = [p[1] for ln in lines for p in ln]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def simplify(pts: List[List[float]], tol: float) -> List[List[float]]:
    """Douglas-Peucker (iterative); a closed ring keeps at least four points."""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a][0], pts[a][1]
        dx, dy = pts[b][0] - ax, pts[b][1] - ay
        l2 = dx * dx + dy * dy
        best, at = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i][0], pts[i][1]
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
    out = [p for p, k in zip(pts, keep) if k]
    if pts[0] == pts[-1] and len(out) < 4 and n >= 4:
        out = [pts[0], pts[n // 3], pts[2 * n // 3], pts[-1]]
    return out


def encode(pts: Sequence[Sequence[float]], scale: int = PRECISION) -> str:
    """Google polyline text, (lon, lat) points at 1/scale degree."""
    out: List[str] = []
    plon = plat = 0
    for lon, lat in pts:
        ilon, ilat = int(round(lon * scale)), int(round(lat * scale))
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plon, plat = ilon, ilat
    return "".join(out)


def decode(text: str, scale: int = PRECISION) -> List[List[float]]:
    """The inverse of encode(): [[lon, lat], ...]."""
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


def dedupe(pts: List[List[float]]) -> List[List[float]]:
    """Drop repeated points (after rounding to the stored precision)."""
    out: List[List[float]] = []
    for p in pts:
        q = [round(p[0] * PRECISION) / PRECISION, round(p[1] * PRECISION) / PRECISION]
        if not out or q != out[-1]:
            out.append(q)
    return out


def lines_of(geom: Optional[dict]) -> List[List[List[float]]]:
    if not geom:
        return []
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return [list(c) for c in geom["coordinates"]]
    return []


def outer_rings(geom: Optional[dict]) -> List[List[List[float]]]:
    """The outer ring of every polygon (holes - islands in a lake - are left out)."""
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def ring_area(ring: Sequence[Sequence[float]]) -> float:
    """Planar area of a ring in square degrees (enough to rank pieces of one lake)."""
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2


# ------------------------------------------------------------------ chaining line parts into rivers
def chain_parts(parts: List[List[List[float]]], tol: float = JOIN_TOL) -> List[List[List[float]]]:
    """
    Join unordered, unoriented line parts end to end by their nearest ends.
    The longest part starts the first chain; at a fork the continuation that
    turns least is taken. Returns the chains, longest first.
    """
    parts = [p for p in parts if len(p) >= 2]
    n = len(parts)
    used = [False] * n
    cell = tol
    grid: Dict[Tuple[int, int], List[Tuple[int, int]]] = defaultdict(list)

    def cell_of(pt):
        return (math.floor(pt[0] / cell), math.floor(pt[1] / cell))

    for i, p in enumerate(parts):
        grid[cell_of(p[0])].append((i, 0))
        grid[cell_of(p[-1])].append((i, 1))

    def candidates(pt):
        cx, cy = cell_of(pt)
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, e in grid.get((cx + dx, cy + dy), ()):
                    if used[i]:
                        continue
                    q = parts[i][0] if e == 0 else parts[i][-1]
                    d = math.hypot(q[0] - pt[0], q[1] - pt[1])
                    if d <= tol:
                        out.append((d, i, e))
        return out

    def heading(seq, back: bool):
        """Unit vector leaving the end of `seq` (back: looking along the last points) or its first points."""
        if back:
            a, b = seq[max(0, len(seq) - 4)], seq[-1]
            v = (b[0] - a[0], b[1] - a[1])
        else:
            a, b = seq[0], seq[min(3, len(seq) - 1)]
            v = (b[0] - a[0], b[1] - a[1])
        m = math.hypot(*v) or 1.0
        return (v[0] / m, v[1] / m)

    order = sorted(range(n), key=lambda i: -line_km(parts[i]))
    chains: List[List[List[float]]] = []
    for s in order:
        if used[s]:
            continue
        used[s] = True
        chain = [list(p) for p in parts[s]]
        for _ in range(2):                      # extend the end, flip, extend the other end, flip back
            while True:
                cands = candidates(chain[-1])
                if not cands:
                    break
                h0 = heading(chain, True)
                best = None
                for d, i, e in cands:
                    seq = parts[i] if e == 0 else parts[i][::-1]
                    h1 = heading(seq, False)
                    score = h0[0] * h1[0] + h0[1] * h1[1] - d * 4
                    if best is None or score > best[0]:
                        best = (score, i, seq)
                _score, i, seq = best
                used[i] = True
                chain.extend([list(p) for p in seq[1:]])
            chain.reverse()
        chains.append(chain)
    chains.sort(key=lambda c: -line_km(c))
    return chains


def components(parts: List[List[List[float]]], tol: float = JOIN_TOL) -> List[List[List[List[float]]]]:
    """Group line parts that touch (ends within tol of another part's ends or points)."""
    n = len(parts)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cell = tol
    grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i, p in enumerate(parts):
        for pt in (p[0], p[-1]):
            grid[(math.floor(pt[0] / cell), math.floor(pt[1] / cell))].append(i)
    for i, p in enumerate(parts):
        for pt in (p[0], p[-1]):
            cx, cy = math.floor(pt[0] / cell), math.floor(pt[1] / cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((cx + dx, cy + dy), ()):
                        if j == i:
                            continue
                        q0, q1 = parts[j][0], parts[j][-1]
                        if min(math.hypot(q0[0] - pt[0], q0[1] - pt[1]), math.hypot(q1[0] - pt[0], q1[1] - pt[1])) <= tol:
                            parent[find(i)] = find(j)
    groups: Dict[int, List[List[List[float]]]] = defaultdict(list)
    for i, p in enumerate(parts):
        groups[find(i)].append(p)
    return list(groups.values())


def orient(chain: List[List[float]], source: Optional[Sequence[float]]) -> Tuple[List[List[float]], bool]:
    """(chain running source -> mouth, True) when a source point is known, else (chain, False)."""
    if not source:
        return chain, False
    if hav_km(chain[0], source) <= hav_km(chain[-1], source):
        return chain, True
    return chain[::-1], True


# ------------------------------------------------------------------ the sources
def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_ne(cache: str, offline: bool) -> Dict[str, List[dict]]:
    """The Natural Earth GeoJSON features by file name (downloaded once into `cache`)."""
    os.makedirs(cache, exist_ok=True)
    out: Dict[str, List[dict]] = {}
    for name in NE_FILES:
        path = os.path.join(cache, f"{name}.geojson")
        if not os.path.exists(path):
            if offline:
                raise SystemExit(f"missing {path} (--offline)")
            import requests
            r = requests.get(NE_BASE + name + ".geojson", timeout=180)
            r.raise_for_status()
            with open(path, "wb") as fh:
                fh.write(r.content)
        digest = sha256(path)
        want = NE_FILES[name]
        if want and digest != want:
            raise SystemExit(f"{name}: SHA-256 {digest} is not the pinned {want}")
        print(f"[source] {name}: {os.path.getsize(path):,} bytes sha256 {digest}", flush=True)
        with open(path, encoding="utf-8") as fh:
            out[name] = json.load(fh)["features"]
    return out


# ------------------------------------------------------------------ the rivers the planner knows by heart
# (id, name as drawn, Natural Earth names, source (lon, lat), mouth (lon, lat), options)
#   The path is the shortest way along the river lines of those names from the source to the mouth, so it runs
#   with the water (the draw and the streaming dashes follow it) and leaves out a fork or a mislabelled branch.
#   bare: said "the Colorado" (with river words in the line); hints: words that pick this river among others
#   of the same name (the line, the brief, the places already named); primary: the one a line means when
#   nothing in its context says otherwise.
RIVERS: List[tuple] = [
    ("colorado-river", "Colorado River", ("colorado",), (-105.85, 40.40), (-115.04, 31.97), dict(
        bare=["colorado"], primary=True,
        hints=["arizona", "utah", "nevada", "california", "new mexico", "wyoming", "lake powell", "lake mead", "grand canyon",
               "glen canyon", "hoover dam", "imperial valley", "yuma", "las vegas", "phoenix", "upper basin", "lower basin",
               "compact", "rockies", "mexico", "colorado river basin", "colorado river compact"])),
    ("colorado-river-texas", "Colorado River", ("colorado",), (-101.31, 32.61), (-95.96, 28.61), dict(
        aliases=["colorado river"],
        hints=["texas", "austin", "lake travis", "lake buchanan", "lcra", "hill country", "matagorda", "houston", "san antonio"])),
    ("green-river", "Green River", ("green",), (-109.91, 43.37), (-109.87, 38.19), dict(
        hints=["wyoming", "utah", "flaming gorge", "colorado river", "canyonlands", "dinosaur", "moab", "lake powell"])),
    ("san-juan-river", "San Juan River", ("san juan",), (-106.80, 37.43), (-110.90, 37.19), dict(
        hints=["new mexico", "utah", "navajo", "lake powell", "colorado river", "farmington", "four corners"])),
    ("gila-river", "Gila River", ("gila",), (-108.20, 33.58), (-114.56, 32.73), dict(hints=["arizona", "new mexico", "phoenix"])),
    ("salt-river", "Salt River", ("salt",), (-110.24, 33.74), (-112.35, 33.39), dict(
        hints=["arizona", "phoenix", "roosevelt", "tempe", "mesa"])),
    ("little-colorado-river", "Little Colorado River", ("little colorado",), (-109.35, 34.49), (-111.80, 36.19), dict(
        bare=["little colorado"], primary=True)),
    ("rio-grande", "Rio Grande", ("rio grande",), (-107.43, 37.78), (-97.14, 25.97), dict(
        aliases=["rio grande", "rio grande river", "rio bravo"], bare=["rio grande"], primary=True)),
    ("pecos-river", "Pecos River", ("pecos",), (-105.64, 35.85), (-101.37, 29.69), dict(primary=True)),
    ("brazos-river", "Brazos River", ("brazos",), (-100.50, 32.90), (-95.38, 28.88), dict(primary=True)),
    ("trinity-river-texas", "Trinity River", ("trinity",), (-96.90, 32.81), (-94.74, 29.78), dict(
        aliases=["trinity river"], hints=["texas", "dallas", "houston", "fort worth"])),
    ("red-river", "Red River", ("red",), (-100.90, 34.64), (-91.66, 31.00), dict(
        hints=["texas", "oklahoma", "louisiana", "arkansas", "shreveport", "lake texoma"])),
    ("red-river-of-the-north", "Red River of the North", ("red",), (-96.60, 45.82), (-96.60, 50.98), dict(
        aliases=["red river of the north", "red river"],
        hints=["north dakota", "minnesota", "manitoba", "fargo", "winnipeg", "grand forks", "red river valley"])),
    ("arkansas-river", "Arkansas River", ("arkansas",), (-106.38, 39.22), (-91.07, 33.79), dict(primary=True)),
    ("canadian-river", "Canadian River", ("canadian",), (-104.62, 36.91), (-95.06, 35.46), dict(primary=True)),
    ("platte-river", "Platte River", ("platte",), (-100.31, 41.01), (-95.87, 41.05), dict(primary=True)),
    ("north-platte-river", "North Platte River", ("north platte",), (-106.43, 40.43), (-100.31, 41.01), dict(primary=True)),
    ("south-platte-river", "South Platte River", ("south platte",), (-106.03, 39.24), (-100.30, 41.00), dict(primary=True)),
    ("missouri-river", "Missouri River", ("missouri",), (-111.52, 46.36), (-90.13, 38.82), dict(bare=["missouri"], primary=True)),
    ("yellowstone-river", "Yellowstone River", ("yellowstone",), (-109.99, 44.06), (-103.95, 48.00), dict(primary=True)),
    ("mississippi-river", "Mississippi River", ("mississippi",), (-95.18, 47.22), (-89.41, 28.94), dict(
        bare=["mississippi"], primary=True)),
    ("ohio-river", "Ohio River", ("ohio",), (-79.99, 40.45), (-89.12, 36.98), dict(bare=["ohio"], primary=True)),
    ("tennessee-river", "Tennessee River", ("tennessee",), (-83.97, 35.87), (-88.59, 37.09), dict(primary=True)),
    ("cumberland-river", "Cumberland River", ("cumberland",), (-82.81, 37.05), (-88.43, 37.14), dict(primary=True)),
    ("columbia-river", "Columbia River", ("columbia",), (-115.87, 50.29), (-123.21, 46.17), dict(primary=True)),
    ("snake-river", "Snake River", ("columbia", "snake"), (-110.63, 43.84), (-119.03, 46.22), dict(primary=True)),
    ("sacramento-river", "Sacramento River", ("sacramento",), (-122.43, 41.25), (-121.69, 38.15), dict(primary=True)),
    ("san-joaquin-river", "San Joaquin River", ("san joaquin",), (-118.74, 37.10), (-121.45, 38.00), dict(primary=True)),
    ("hudson-river", "Hudson River", ("hudson",), (-74.07, 44.10), (-73.95, 41.31), dict(primary=True)),
    # the world's rivers a water documentary reaches for
    ("nile", "Nile", ("nile",), (33.79, 18.35), (31.24, 30.12), dict(
        aliases=["nile", "nile river"], bare=["nile"], primary=True)),
    ("blue-nile", "Blue Nile", ("blue nile",), (37.39, 11.63), (32.49, 15.63), dict(
        aliases=["blue nile", "blue nile river"], primary=True)),
    ("white-nile", "White Nile", ("white nile",), (31.15, 6.83), (32.49, 15.63), dict(
        aliases=["white nile", "white nile river"], primary=True)),
    ("amazon-river", "Amazon River", ("amazonas",), (-73.49, -4.44), (-52.71, -1.58), dict(
        aliases=["amazon river", "river amazon"], bare=["amazon"], primary=True)),
    ("orinoco-river", "Orinoco River", ("orinoco",), (-63.44, 2.37), (-62.33, 9.72), dict(
        aliases=["orinoco river", "orinoco"], primary=True)),
    ("sao-francisco-river", "Sao Francisco River", ("sao francisco",), (-45.09, -19.05), (-36.41, -10.50), dict(
        aliases=["sao francisco river", "rio sao francisco"], primary=True)),
    ("congo-river", "Congo River", ("congo",), (26.44, -8.27), (13.18, -5.86), dict(
        aliases=["congo river"], bare=["congo"], primary=True)),
    ("niger-river", "Niger River", ("niger",), (-10.73, 9.09), (5.50, 5.14), dict(aliases=["niger river"], primary=True)),
    ("zambezi-river", "Zambezi River", ("zambezi",), (24.27, -11.38), (35.76, -18.08), dict(
        aliases=["zambezi river", "zambezi"], bare=["zambezi"], primary=True)),
    ("limpopo-river", "Limpopo River", ("limpopo",), (26.96, -23.74), (33.53, -25.19), dict(
        aliases=["limpopo river", "limpopo"], primary=True)),
    ("orange-river", "Orange River", ("orange",), (29.06, -29.08), (16.49, -28.57), dict(
        aliases=["orange river"], primary=True)),
    ("tigris-river", "Tigris River", ("tigris",), (42.38, 37.06), (47.43, 31.02), dict(
        aliases=["tigris river", "tigris"], bare=["tigris"], primary=True)),
    ("euphrates-river", "Euphrates River", ("euphrates",), (40.99, 34.43), (47.47, 30.97), dict(
        aliases=["euphrates river", "euphrates"], bare=["euphrates"], primary=True)),
    ("jordan-river", "Jordan River", ("jordan",), (35.86, 33.60), (35.40, 31.23), dict(aliases=["jordan river"], primary=True)),
    ("indus-river", "Indus River", ("indus",), (79.73, 32.44), (67.76, 24.05), dict(
        aliases=["indus river", "indus"], bare=["indus"], primary=True)),
    ("ganges-river", "Ganges River", ("ganges",), (79.84, 30.89), (89.75, 23.85), dict(
        aliases=["ganges river", "ganges", "ganga", "river ganges"], bare=["ganges", "ganga"], primary=True)),
    ("brahmaputra-river", "Brahmaputra River", ("brahmaputra",), (95.40, 28.00), (90.25, 23.46), dict(
        aliases=["brahmaputra river", "brahmaputra"], bare=["brahmaputra"], primary=True)),
    ("mekong-river", "Mekong River", ("mekong",), (96.94, 31.97), (105.84, 10.00), dict(
        aliases=["mekong river", "mekong"], bare=["mekong"], primary=True)),
    ("irrawaddy-river", "Irrawaddy River", ("irrawaddy",), (97.49, 25.70), (94.99, 16.25), dict(
        aliases=["irrawaddy river", "irrawaddy", "ayeyarwady"], primary=True)),
    ("yangtze-river", "Yangtze River", ("yangtze",), (98.54, 31.69), (119.61, 32.20), dict(
        aliases=["yangtze river", "yangtze", "chang jiang"], bare=["yangtze"], primary=True)),
    ("yellow-river", "Yellow River", ("huang", "yellow"), (96.16, 35.13), (119.03, 37.80), dict(
        aliases=["yellow river", "huang he"], primary=True)),
    ("amur-river", "Amur River", ("amur",), (121.41, 53.32), (140.71, 53.11), dict(aliases=["amur river", "amur"], primary=True)),
    ("volga-river", "Volga River", ("volga",), (32.60, 57.25), (47.56, 45.77), dict(
        aliases=["volga river", "volga"], bare=["volga"], primary=True)),
    ("danube-river", "Danube", ("danube",), (8.18, 48.09), (28.75, 45.23), dict(
        aliases=["danube river", "danube"], bare=["danube"], primary=True)),
    ("murray-river", "Murray River", ("murray",), (148.00, -36.97), (139.36, -35.38), dict(
        aliases=["murray river", "river murray"], primary=True)),
    ("darling-river", "Darling River", ("darling",), (147.41, -30.12), (141.93, -34.12), dict(
        aliases=["darling river", "river darling"], primary=True)),
]
RIVER_WORDS = {"river", "rio", "creek", "fork", "canal", "wash", "bayou", "stream", "brook", "run", "branch", "kill", "arroyo"}
GENERIC_MIN_KM = 60.0            # a named stretch shorter than this is not a river a story reaches for


# ------------------------------------------------------------------ the graph of a name's line parts
class Net:
    """The vertices of line parts as a graph (parts joined where their ends meet), for shortest paths along rivers."""

    def __init__(self, parts: List[List[List[float]]]):
        self.pts: List[Tuple[float, float]] = []
        self.adj: List[List[Tuple[int, float]]] = []
        self.index: Dict[Tuple[int, int], int] = {}
        self.grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        ends: List[int] = []
        for part in parts:
            prev = None
            for k, (x, y) in enumerate(part):
                n = self._node(x, y)
                if prev is not None and prev != n:
                    w = hav_km(self.pts[prev], self.pts[n])
                    self.adj[prev].append((n, w))
                    self.adj[n].append((prev, w))
                prev = n
                if k == 0 or k == len(part) - 1:
                    ends.append(n)
        # parts meet where an end is within JOIN_TOL of another part's vertex
        cell = JOIN_TOL
        for n in ends:
            x, y = self.pts[n]
            cx, cy = math.floor(x / cell), math.floor(y / cell)
            best = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for m in self.grid.get((cx + dx, cy + dy), ()):
                        if m == n or any(m == a for a, _w in self.adj[n]):
                            continue
                        d = math.hypot(self.pts[m][0] - x, self.pts[m][1] - y)
                        if d <= JOIN_TOL and (best is None or d < best[0]):
                            best = (d, m)
            if best:
                w = hav_km(self.pts[n], self.pts[best[1]])
                self.adj[n].append((best[1], w))
                self.adj[best[1]].append((n, w))

    def _node(self, x: float, y: float) -> int:
        key = (int(round(x * 1e4)), int(round(y * 1e4)))
        n = self.index.get(key)
        if n is None:
            n = len(self.pts)
            self.index[key] = n
            self.pts.append((x, y))
            self.adj.append([])
            self.grid[(math.floor(x / JOIN_TOL), math.floor(y / JOIN_TOL))].append(n)
        return n

    def nearest(self, lon: float, lat: float, within: float = 0.5) -> Optional[int]:
        best = None
        r = int(math.ceil(within / JOIN_TOL))
        cx, cy = math.floor(lon / JOIN_TOL), math.floor(lat / JOIN_TOL)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for m in self.grid.get((cx + dx, cy + dy), ()):
                    d = math.hypot(self.pts[m][0] - lon, self.pts[m][1] - lat)
                    if d <= within and (best is None or d < best[0]):
                        best = (d, m)
        return best[1] if best else None

    def path(self, a: int, b: int) -> Optional[List[List[float]]]:
        """The shortest path of vertices from node a to node b, or None when they are not joined."""
        import heapq
        dist = {a: 0.0}
        prev: Dict[int, int] = {}
        heap = [(0.0, a)]
        while heap:
            d, n = heapq.heappop(heap)
            if n == b:
                break
            if d > dist.get(n, 1e18):
                continue
            for m, w in self.adj[n]:
                nd = d + w
                if nd < dist.get(m, 1e18):
                    dist[m] = nd
                    prev[m] = n
                    heapq.heappush(heap, (nd, m))
        if b not in dist:
            return None
        out, n = [], b
        while True:
            out.append([self.pts[n][0], self.pts[n][1]])
            if n == a:
                break
            n = prev[n]
        return out[::-1]


def river_alias_forms(name: str) -> List[str]:
    """What a story calls an ordinary river by name: 'Gunnison' -> 'gunnison river'; 'Rio Grande' as it is."""
    key = norm(name)
    words = key.split()
    if not words:
        return []
    if words[-1] in RIVER_WORDS or words[0] in RIVER_WORDS:
        return [key]
    return [key + " river"]


def display_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    low = name.lower().split()
    if low and low[-1] not in RIVER_WORDS and low[0] not in RIVER_WORDS:
        name += " River"
    return name


def read_river_parts(ne: Dict[str, List[dict]]) -> Dict[str, dict]:
    """{normalised name: {"name": as written, "parts": [line parts]}} from both river files."""
    out: Dict[str, dict] = {}
    for src, key in (("m", "ne_10m_rivers_lake_centerlines"), ("n", "ne_10m_rivers_north_america")):
        for f in ne[key]:
            p = f["properties"]
            nm = p.get("name_en") or p.get("name")
            if not nm or p.get("featurecla") not in ("River", "Lake Centerline"):
                continue
            if src == "n" and (p.get("scalerank") or 99) > NA_MAX_RANK:
                continue
            ent = out.setdefault(norm(nm), {"name": str(nm), "parts": []})
            ent["parts"].extend(ln for ln in lines_of(f["geometry"]) if len(ln) >= 2)
    return out


def tidy_line(pts: List[List[float]], tol: float) -> List[List[float]]:
    return dedupe(simplify(pts, tol))


def river_record(rid: str, name: str, lines: List[List[List[float]]], flow: bool, aliases: List[str],
                 extra: Optional[dict] = None) -> dict:
    lines = [tidy_line(ln, RIVER_TOL) for ln in lines]
    lines = [ln for ln in lines if len(ln) >= 2]
    rec = {"id": rid, "name": name, "aliases": aliases, "bbox": bbox_of(lines),
           "km": int(round(sum(line_km(ln) for ln in lines))), "flow": flow}
    if extra:
        rec.update({k: v for k, v in extra.items() if v})
    rec["lines"] = [encode(ln) for ln in lines]
    return rec


def build_rivers(ne: Dict[str, List[dict]]) -> List[dict]:
    named = read_river_parts(ne)
    out: List[dict] = []
    consumed: set = set()                       # (name, component index) already drawn by a curated river
    comps_of = {k: components(v["parts"]) for k, v in named.items()}
    for rid, title, names, src, mouth, opt in RIVERS:
        parts = [p for n in names for p in named.get(norm(n), {}).get("parts", [])]
        if not parts:
            raise SystemExit(f"{rid}: no Natural Earth lines named {names}")
        net = Net(parts)
        a, b = net.nearest(*src), net.nearest(*mouth)
        if a is None or b is None:
            raise SystemExit(f"{rid}: source {src} or mouth {mouth} is not on the {names} lines")
        path = net.path(a, b)
        if not path:
            raise SystemExit(f"{rid}: the {names} lines do not join {src} to {mouth}")
        km = line_km(path)
        direct = hav_km(path[0], path[-1])
        if km < 0.9 * direct or km > 2.6 * direct:
            raise SystemExit(f"{rid}: path {km:.0f} km for {direct:.0f} km between its ends")
        # the components this river runs through are drawn: no second, generic river for them
        keys = {(round(x, 3), round(y, 3)) for x, y in path}
        for n in names:
            for i, comp in enumerate(comps_of.get(norm(n), [])):
                if any((round(pt[0], 3), round(pt[1], 3)) in keys for part in comp for pt in part):
                    consumed.add((norm(n), i))
        aliases = [norm(x) for x in opt.get("aliases", [])] or [norm(title)]
        out.append(river_record(rid, title, [path], True, sorted(set(aliases)), {
            "bare": sorted(set(norm(x) for x in opt.get("bare", []))),
            "primary": bool(opt.get("primary")),
            "hints": [norm(h) for h in opt.get("hints", [])],
        }))
    used_ids = {r["id"] for r in out}
    generic = 0
    for key, ent in sorted(named.items()):
        for i, comp in enumerate(comps_of[key]):
            if (key, i) in consumed:
                continue
            chains = chain_parts(comp)
            main_km = line_km(chains[0])
            if main_km < GENERIC_MIN_KM:
                continue
            lines = [chains[0]] + [c for c in chains[1:] if line_km(c) >= BRANCH_MIN * main_km]
            bb = bbox_of(lines)
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            rid = slug(ent["name"])
            if rid in used_ids:
                rid += f"-{'n' if cy >= 0 else 's'}{abs(int(round(cy))):02d}{'e' if cx >= 0 else 'w'}{abs(int(round(cx))):03d}"
            used_ids.add(rid)
            out.append(river_record(rid, display_name(ent["name"]), lines, False, sorted(set(river_alias_forms(ent["name"])))))
            generic += 1
    print(f"[rivers] {len(RIVERS)} curated, {generic} others", flush=True)
    return out


# ------------------------------------------------------------------ lakes and reservoirs
# Other ways a story names a lake, by Natural Earth label.
LAKE_ALIASES = {
    "Franklin D. Roosevelt Lake": ["lake roosevelt", "franklin d. roosevelt lake"],
    "Theodore Roosevelt Lake": ["roosevelt lake", "theodore roosevelt lake"],
    "Lake Sidney Lanier": ["lake lanier", "lake sidney lanier"],
    "Lake Sakakawea": ["lake sakakawea"],
    "Amistad Reservoir": ["lake amistad", "amistad reservoir"],
    "Falcon Lake": ["falcon lake", "falcon reservoir"],
    "Represa Itaipu": ["itaipu reservoir"],
    "South Aral Sea": ["aral sea"],
    "Lake Oroville": ["lake oroville"],
    "Lake Mohave": ["lake mohave"],
}
LAKE_MIN_DEG = 0.03              # a lake smaller than this across is not worth a map


def build_lakes(ne: Dict[str, List[dict]]) -> List[dict]:
    out: List[dict] = []
    seen_id, seen_ne = set(), set()
    for key in ("ne_10m_lakes", "ne_10m_lakes_north_america"):
        for f in ne[key]:
            p = f["properties"]
            label = str(p.get("name") or p.get("label") or p.get("name_en") or "").strip()
            if not label or p.get("ne_id") in seen_ne:
                continue
            rings = sorted(outer_rings(f["geometry"]), key=ring_area, reverse=True)
            if not rings:
                continue
            seen_ne.add(p.get("ne_id"))
            big = ring_area(rings[0])
            rings = [r for r in rings[:8] if ring_area(r) >= 0.02 * big]
            rings = [dedupe(simplify(r, LAKE_TOL)) for r in rings]
            rings = [r for r in rings if len(r) >= 4]
            if not rings:
                continue
            bb = bbox_of(rings)
            if max(bb[2] - bb[0], bb[3] - bb[1]) < LAKE_MIN_DEG:
                continue
            aliases = {norm(label), norm(p.get("label") or "")}
            for alt in re.split(r"[;|]", str(p.get("name_alt") or "")):
                if norm(alt) and len(norm(alt).split()) >= 2:
                    aliases.add(norm(alt))
            aliases.update(norm(a) for a in LAKE_ALIASES.get(label, []))
            lid = slug(label)
            if lid in seen_id:
                lid += f"-{'n' if bb[1] >= 0 else 's'}{abs(int(bb[1])):02d}{'e' if bb[0] >= 0 else 'w'}{abs(int(bb[0])):03d}"
            seen_id.add(lid)
            rec = {"id": lid, "name": label, "aliases": sorted(a for a in aliases if a),
                   "kind": "reservoir" if p.get("featurecla") == "Reservoir" else "lake", "bbox": bb,
                   "rings": [encode(r) for r in rings]}
            if p.get("dam_name"):
                rec["dam"] = str(p["dam_name"])
            out.append(rec)
    print(f"[lakes] {len(out)} lakes and reservoirs", flush=True)
    return out


# ------------------------------------------------------------------ canals and aqueducts (hand-traced, approximate)
# Coarse traces through public landmarks of each works (intakes, pumping plants, reservoirs, towns on the route:
# USGS GNIS / Wikipedia coordinates), water entering at the first point. They are drawn dashed and marked
# "approx": the route, not the survey. (The USGS NHD service would give exact lines but it times out.)
CANAL_TRACES = [
    ("central-arizona-project", "Central Arizona Project", ["central arizona project", "central arizona project canal", "cap canal"],
     [(-114.15, 34.31), (-113.95, 34.12), (-113.55, 33.95), (-113.1, 33.85), (-112.7, 33.8), (-112.27, 33.85), (-112.05, 33.72),
      (-111.8, 33.55), (-111.55, 33.38), (-111.42, 33.15), (-111.46, 32.95), (-111.4, 32.64), (-111.25, 32.45), (-111.12, 32.25),
      (-111.08, 32.08)]),
    ("california-aqueduct", "California Aqueduct", ["california aqueduct", "state water project aqueduct"],
     [(-121.62, 37.80), (-121.35, 37.4), (-121.13, 37.06), (-120.6, 36.6), (-119.95, 36.0), (-119.5, 35.5), (-119.2, 35.2),
      (-118.65, 35.05), (-118.2, 34.75), (-117.9, 34.5), (-117.45, 34.35), (-117.3, 34.28)]),
    ("all-american-canal", "All-American Canal", ["all-american canal", "all american canal"],
     [(-114.47, 32.88), (-114.65, 32.78), (-114.85, 32.73), (-115.1, 32.72), (-115.4, 32.68), (-115.58, 32.67)]),
    ("colorado-river-aqueduct", "Colorado River Aqueduct", ["colorado river aqueduct"],
     [(-114.14, 34.29), (-114.8, 34.2), (-115.3, 34.05), (-115.6, 33.8), (-116.1, 33.75), (-116.55, 33.88), (-116.9, 33.92),
      (-117.2, 33.85), (-117.45, 33.85)]),
    ("los-angeles-aqueduct", "Los Angeles Aqueduct", ["los angeles aqueduct", "la aqueduct"],
     [(-118.2, 36.8), (-118.0, 36.4), (-117.95, 36.15), (-117.9, 35.95), (-118.1, 35.5), (-118.17, 35.05), (-118.45, 34.75),
      (-118.5, 34.5), (-118.48, 34.3)]),
]
NE_CANALS = {"Erie Canal": ("erie-canal", ["erie canal"]), "Welland Canal": ("welland-canal", ["welland canal"])}


def build_canals(ne: Dict[str, List[dict]]) -> List[dict]:
    out: List[dict] = []
    for cid, title, aliases, trace in CANAL_TRACES:
        out.append(river_record(cid, title, [[list(p) for p in trace]], True, sorted(set(norm(a) for a in aliases)),
                                {"approx": True}))
    for f in ne["ne_10m_rivers_north_america"]:
        p = f["properties"]
        if p.get("featurecla") == "Canal" and p.get("name") in NE_CANALS:
            cid, aliases = NE_CANALS[p["name"]]
            if any(c["id"] == cid for c in out):
                continue
            chains = chain_parts(lines_of(f["geometry"]))
            if chains:
                out.append(river_record(cid, p["name"], chains[:1], False, aliases, {"approx": True}))
    print(f"[canals] {len(out)} canals", flush=True)
    return out


# ------------------------------------------------------------------ the hand-kept dams, checked
def check_dams(dams: List[dict], rivers: List[dict], lakes: List[dict]) -> None:
    """A dam sits where its river runs and (when Natural Earth draws it) at its reservoir: say when it does not."""
    by_lake = {norm(l["name"]): l for l in lakes}
    by_river = {r["id"]: r for r in rivers}
    bad = 0
    for d in dams:
        pt = [d["lon"], d["lat"]]
        notes = []
        lake = by_lake.get(norm(d.get("lake", "")))
        if d.get("lake") and lake:
            near = min(hav_km(pt, q) for r in lake["rings"] for q in decode(r))
            if near > d.get("lake_km", 12):
                notes.append(f"{near:.0f} km from the outline of {d['lake']}")
        river = by_river.get(d.get("river", ""))
        if d.get("river") and river:
            near = min(hav_km(pt, q) for ln in river["lines"] for q in decode(ln))
            if near > d.get("river_km", 8):
                notes.append(f"{near:.0f} km from {river['name']}")
        elif d.get("river") and not river:
            notes.append(f"unknown river id {d['river']}")
        if notes:
            bad += 1
            print(f"[dams] CHECK {d['name']}: " + "; ".join(notes), flush=True)
    print(f"[dams] {len(dams)} dams, {bad} to look at", flush=True)


def write_json(name: str, data: dict) -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, separators=(",", ":"), ensure_ascii=False, sort_keys=False)
    print(f"[write] {name}: {os.path.getsize(path):,} bytes", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--cache", default=os.path.join(ROOT, ".geo_cache"), help="where the downloaded sources are kept")
    ap.add_argument("--offline", action="store_true", help="never download; fail when a source is missing")
    args = ap.parse_args()
    ne = fetch_ne(args.cache, args.offline)
    rivers = build_rivers(ne)
    lakes = build_lakes(ne)
    write_json("rivers.json", {"version": 1, "precision": PRECISION, "rivers": rivers})
    write_json("lakes.json", {"version": 1, "precision": PRECISION, "lakes": lakes})
    write_json("canals.json", {"version": 1, "precision": PRECISION, "canals": build_canals(ne)})
    with open(os.path.join(OUT, "dams.json"), encoding="utf-8") as fh:
        check_dams(json.load(fh)["dams"], rivers, lakes)


if __name__ == "__main__":
    main()
