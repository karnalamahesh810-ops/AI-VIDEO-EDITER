"""
Maps v2 planner (2026-10-14): the map looks of a plan as the branded relief maps of LibMaps2.tsx (the owner's
PointShift reference: dark 3D relief, the focus region in the brand's region colour, gold pill labels, dotted
routes, camera pushes), for every niche - history, news, travel, geography, business, true crime, sport.

Where they come from: the planner's own map looks (src/treatments.py, its places resolved by the gazetteer,
src/geocode.py - never a model's guess) are upgraded in place by what their line says (src/datalooks.finish ->
_upgrade_maps, after looks pack 3's maps). The countries and states / provinces a line names are found in the
Natural Earth name index (src/geodata/maps2_names.json, scripts/build_maps2.py names). Each part lands on its
own word (items[i].at / areas[i].at, re-timed from where the look really starts), so the owner's timing rule
holds: nothing shows before it is said.

  M2_COMPARE       two areas compared ("Texas is bigger than France", "the size of", "versus")
  M2_CHOROPLETH    three or more areas each with a figure ("Brazil grows 3.2 million tonnes, Vietnam 1.9 ...")
  M2_RADIUS        a distance round a place ("a 30-kilometre exclusion zone", "within 50 miles of")
  M2_FLOWS         goods / people moving from one place to several ("exports to", "shipped to", "migrated")
  M2_ROUTE         a route through two to six places ("from Lisbon to Madrid and on to Paris")
  M2_PLACES        three or more places named together
  M2_BORDER_TRACE  a border, frontier or coastline of a named area
  M2_RELIEF_TILT   terrain: mountains, a range, a plateau, an elevation said
  M2_ZOOM_DIVE     one place: globe -> its country -> its state (the first map of a video, a new country)
  M2_REGION_PULSE  a state / country named on its own
  M2_PIN_DROP      a town, a site, "located in", "the village of"
  M2_SAT_FLAT      a natural place (an island, a desert, a lake, a canyon) - real imagery turning into the map

Pure functions: no network, no paid calls. config.MAPS_V2 switches the upgrade (default on).
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

ZOOM_DIVE = "M2_ZOOM_DIVE"
REGION_PULSE = "M2_REGION_PULSE"
RELIEF_TILT = "M2_RELIEF_TILT"
ROUTE = "M2_ROUTE"
PLACES = "M2_PLACES"
BORDER_TRACE = "M2_BORDER_TRACE"
CHOROPLETH = "M2_CHOROPLETH"
COMPARE = "M2_COMPARE"
RADIUS = "M2_RADIUS"
FLOWS = "M2_FLOWS"
PIN_DROP = "M2_PIN_DROP"
SAT_FLAT = "M2_SAT_FLAT"
IDS = (ZOOM_DIVE, REGION_PULSE, RELIEF_TILT, ROUTE, PLACES, BORDER_TRACE, CHOROPLETH, COMPARE, RADIUS, FLOWS, PIN_DROP,
       SAT_FLAT)
SINGLE = (ZOOM_DIVE, PIN_DROP, REGION_PULSE, SAT_FLAT, RELIEF_TILT)


def variant_of(tid: str) -> str:
    """M2_ZOOM_DIVE -> 'm2-zoom-dive'."""
    return "m2-" + tid[3:].lower().replace("_", "-")


# The plan's map looks a maps-v2 look may take over: the older satellite / vector / pro maps. Looks pack 3's
# maps (a storm track, totals, routes), the premium path, the auto maps of rivers and lakes and the weather maps
# keep their place.
UPGRADABLE_PREFIX = ("MAP_", "LIB_MV_", "LIB_MX_")
UPGRADABLE = frozenset({"KT_LOCATOR", "KT_TWO_PLACES", "KT_PLACE"})


def upgradable(tid: str) -> bool:
    return tid in UPGRADABLE or tid.startswith(UPGRADABLE_PREFIX)


# --------------------------------------------------------------------------- timing (seconds from the look's start)
# When the look has landed (its last part's word plus that part's move), then a hold to read it and the exit.
LAND = {ZOOM_DIVE: 5.2, REGION_PULSE: 1.6, RELIEF_TILT: 2.2, ROUTE: 1.4, PLACES: 1.2, BORDER_TRACE: 3.4, CHOROPLETH: 1.6,
        COMPARE: 5.4, RADIUS: 2.0, FLOWS: 1.6, PIN_DROP: 2.4, SAT_FLAT: 3.4}
LEG = {ROUTE: 0.6, PLACES: 0.5, CHOROPLETH: 0.6, FLOWS: 1.0, REGION_PULSE: 0.8, COMPARE: 0.6}
HOLD = 2.6


def _last_at(ov: dict) -> float:
    best = 0.0
    for key in ("items", "areas"):
        for it in ov.get(key) or []:
            try:
                best = max(best, float((it or {}).get("at") or 0.0))
            except (TypeError, ValueError, AttributeError):
                continue
    return best


def landing_seconds(ov: dict) -> float:
    tid = str(ov.get("template") or "")
    land = LAND.get(tid, 1.5)
    if tid in LEG:
        land = max(land, _last_at(ov) + LEG[tid])
    if tid == ZOOM_DIVE:
        land = max(land, _last_at(ov) + 2.0)
    return round(land, 3)


def min_seconds(ov: dict, exit_s: float = 0.5) -> float:
    return round(landing_seconds(ov) + HOLD + exit_s, 3)


# --------------------------------------------------------------------------- names
_NAMES: Optional[dict] = None
_HERE = os.path.dirname(os.path.abspath(__file__))


def names() -> dict:
    global _NAMES
    if _NAMES is None:
        with open(os.path.join(_HERE, "geodata", "maps2_names.json"), encoding="utf-8") as fh:
            _NAMES = json.load(fh)
    return _NAMES


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() or c in "'." else " " for c in s).split())


_WORD = re.compile(r"[A-Za-z][\w'’.-]*")
# Federations whose states / provinces a story names without naming the country.
_FAMOUS_STATES = {"USA", "CAN", "AUS", "IND", "MEX", "BRA", "DEU", "CHN", "JPN", "RUS", "NGA", "ESP", "ITA", "GBR", "FRA"}


def areas_named(text: str, context_a3: Optional[set] = None) -> List[dict]:
    """
    The countries and states / provinces a text names, in order, each once: {"id", "label" (as said), "kind",
    "a3", "pos"}. A country by any of its names; a state / province only when it begins with a capital letter and
    its country is named too, is the story's (`context_a3`), or is a federation whose states are known by name
    (Texas, Bavaria, Ontario, Kerala ...). Longest names first ("New South Wales" over "Wales").
    """
    idx = names()
    ctry, regs = idx["countries"], idx["regions"]
    text = text or ""
    toks = [(m.start(), m.end(), m.group(0)) for m in _WORD.finditer(text)]
    found: List[dict] = []
    used: List[Tuple[int, int]] = []
    hits: List[Tuple[int, int, str, str]] = []           # start, end, said, normalized
    for n in range(4, 0, -1):
        for i in range(len(toks) - n + 1):
            a, b = toks[i][0], toks[i + n - 1][1]
            said = re.sub(r"['’]s?$", "", text[a:b].rstrip("."))
            key = _norm(said)
            if key in ctry or key in regs:
                hits.append((a, a + len(said), said, key))
    hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
    named_a3 = {ctry[h[3]] for h in hits if h[3] in ctry}
    ctx = set(context_a3 or set()) | named_a3
    for a, b, said, key in hits:
        if any(a < y and b > x for x, y in used):
            continue
        if key in ctry:
            if not said[:1].isupper() and key not in ("the us", "the uk"):
                continue
            found.append({"id": ctry[key], "label": said, "kind": "country", "a3": ctry[key], "pos": a})
            used.append((a, b))
            continue
        if not said[:1].isupper():
            continue
        opts = regs.get(key) or []
        pick = next((o for o in opts if o[1] in ctx), None) or (opts[0] if len(opts) == 1 and opts[0][1] in _FAMOUS_STATES else None)
        if pick:
            found.append({"id": pick[0], "label": said, "kind": "region", "a3": pick[1], "pos": a})
            used.append((a, b))
    found.sort(key=lambda x: x["pos"])
    seen, out = set(), []
    for f in found:
        if f["id"] not in seen:
            seen.add(f["id"])
            out.append(f)
    return out


def a3_of_iso2(code: str) -> str:
    return names()["iso2"].get(str(code or "").lower(), "")


# --------------------------------------------------------------------------- the line's cues
_NUM = r"\d[\d,]*(?:\.\d+)?"
_COMPARE = re.compile(r"\b(bigger|larger|smaller|wider|longer)\s+than\b|\b(?:more|fewer|less)\s+\w+(?:\s+\w+)?\s+than\b|\bthe\s+size\s+of\b|\bcompared\s+(?:to|with)\b|"
                      r"\bversus\b|\bvs\.?\b|\bas\s+(?:big|large|small)\s+as\b|\b(?:twice|three\s+times|times)\s+(?:as|the)\b|"
                      r"\bfits?\s+(?:inside|into)\b", re.I)
_RADIUS = re.compile(rf"\b(?P<v>{_NUM})[\s-]*(?P<u>miles?|mi|kilomet(?:er|re)s?|km)\b(?:[\s-]+(?:wide\s+)?)"
                     rf"(?=(?:radius|zone|exclusion|evacuation|around|from|of\s+(?:the|its)|perimeter|circle|ring)\b)"
                     rf"|\bwithin\s+(?P<v2>{_NUM})\s*(?P<u2>miles?|mi|kilomet(?:er|re)s?|km)\b", re.I)
_FLOW = re.compile(r"\b(export(?:s|ed|ing)?|import(?:s|ed|ing)?|ship(?:s|ped|ping)?\s+(?:to|from)|suppl(?:y|ies|ied)|"
                   r"trade[sd]?\s+(?:with|to)|migrat(?:e|ed|ion|ing)|flow(?:s|ed)?\s+(?:to|into|from)|sent\s+to|sends?\s+to|"
                   r"spread\s+to|fled\s+to|sold\s+to|sells?\s+to|deliver(?:s|ed)?\s+to)\b", re.I)
_INWARD = re.compile(r"\b(import(?:s|ed|ing)?\s+from|came\s+from|arriv(?:e|ed|ing)\s+from|fled\s+(?:from|to)|into\b.*\bfrom\b)", re.I)
_BORDER = re.compile(r"\b(border(?:s|ed|ing)?|frontier|boundary|boundaries|coast(?:line|s)?|shoreline)\b", re.I)
_TERRAIN = re.compile(r"\b(mountains?|mountain\s+range|range|peaks?|summit|plateau|valleys?|highlands?|terrain|elevation|altitude|"
                      r"himalayas?|andes|alps|rockies|rocky\s+mountains|volcano(?:es)?|cliffs?|gorge|canyon\s+walls)\b", re.I)
_ELEV = re.compile(rf"\b(?P<v>{_NUM})\s*(?P<u>feet|foot|ft|met(?:er|re)s?|m)\b(?=[^.]{{0,40}}\b(?:high|tall|above\s+sea|elevation|altitude|summit|peak)\b)", re.I)
_SITE = re.compile(r"\b(located|lies|sits|stands|nestled|town\s+of|village\s+of|city\s+of|the\s+site\s+of|here\b|"
                   r"headquarter(?:s|ed)|built\s+(?:in|at)|born\s+in|founded\s+in|crash(?:ed)?|happened\s+in)\b", re.I)
_NATURE = re.compile(r"\b(island|islands|desert|lake|glacier|canyon|bay|peninsula|archipelago|volcano|forest|rainforest|"
                     r"delta|reef|fjord|coast|national\s+park)\b", re.I)
_VALUE_AFTER = re.compile(rf"^[^.;]{{0,40}}?(?P<v>{_NUM})\s*(?P<s>million|billion|thousand|percent|%)?\s*(?P<u>[a-z%]+)?", re.I)


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _fmt(v: float):
    return int(v) if float(v).is_integer() else round(float(v), 3)


def _area_values(line: str, areas: List[dict]) -> List[Optional[Tuple[float, str]]]:
    """The figure said right after each area's name and before the next one (value, unit), else None."""
    out: List[Optional[Tuple[float, str]]] = []
    for i, a in enumerate(areas):
        end = areas[i + 1]["pos"] if i + 1 < len(areas) else len(line)
        seg = line[a["pos"] + len(a["label"]):end]
        m = _VALUE_AFTER.match(seg)
        if not m or re.fullmatch(r"(1[5-9]|20)\d\d", m.group("v").replace(",", "")):
            out.append(None)
            continue
        v = _num(m.group("v"))
        scale = (m.group("s") or "").lower()
        unit = "%" if scale in ("percent", "%") else {"million": "M", "billion": "B", "thousand": "K"}.get(scale, "")
        out.append((v, unit) if v is not None else None)
    return out


# --------------------------------------------------------------------------- the choice
class State:
    """What maps-v2 placed in this video so far (variety: the least used single-place look; a first-map dive)."""

    def __init__(self) -> None:
        self.counts: Dict[str, int] = {}
        self.countries: set = set()
        self.last: str = ""

    def note(self, tid: str, a3: str = "") -> None:
        self.counts[tid] = self.counts.get(tid, 0) + 1
        self.last = tid
        if a3:
            self.countries.add(a3)


def _name(label: str) -> str:
    return str(label or "").split(",")[0].strip()


def _first_at(text: str, name: str) -> int:
    if not name:
        return -1
    m = re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text)
    if m:
        return m.start()
    head = name.split()[0]
    if len(head) >= 4:
        m = re.search(r"(?<![\w])" + re.escape(head) + r"(?![\w])", text)
        if m:
            return m.start()
    return -1


def _place_at(text: str, label: str) -> int:
    """Where a place is said: its own name, else the next part of its label ('Berlin, Germany' -> 'Germany')."""
    for part in [p.strip() for p in str(label or "").split(",") if p.strip()][:3]:
        i = _first_at(text, part)
        if i >= 0:
            return i
    return -1


def upgrade(ov: dict, line: str, line_at: Callable[[int], float], start_s: float, state: State,
            ok: Callable[[str], bool] = lambda _t: True, context_a3: Optional[set] = None,
            kit: str = "") -> Optional[dict]:
    """
    The plan's map look `ov` as a maps-v2 look when its line fits one (`line`: the narration round its start,
    `line_at(i)`: the second char i of it is said at), else None. Its places stay the gazetteer's; the areas are
    the line's own names; each part carries its word's second (`_items_at` / `_areas_at`, for the lane's re-timing).
    """
    tid = str(ov.get("template") or "")
    if not upgradable(tid) or ov.get("dataLook"):
        return None
    from . import lookpack3
    if lookpack3.storm_line(line):
        return None                             # a storm's track is looks pack 3's (KT_STORM)
    locs = [x for x in (ov.get("locations") or []) if isinstance(x, dict) and isinstance(x.get("lat"), (int, float))
            and isinstance(x.get("lon"), (int, float))]
    ctx = set(context_a3 or set())
    areas = areas_named(line, ctx)
    # places in the order the line says them; each one's word
    said = [(_place_at(line, x.get("label") or ""), x) for x in locs]
    found = sorted([(i, x) for i, x in said if i >= 0], key=lambda p: p[0])
    ordered = [x for _i, x in found] + [x for i, x in said if i < 0]

    def rel(i: int) -> float:
        return round(max(0.0, line_at(i) - start_s), 2)

    base = {k: v for k, v in ov.items() if k not in ("template", "variant", "items", "value", "suffix", "prefix", "total",
                                                     "highlight", "subtitle", "label", "text", "style", "theme", "areas")}
    base.update(type="motion", motion="fade", exit="fade", upgraded=tid, text="", label="")
    if kit:
        base["kit"] = kit

    def done(t: str, extra: dict, a3: str = "") -> Optional[dict]:
        if not ok(t):
            return None
        state.note(t, a3)
        return {**base, "template": t, "variant": variant_of(t), **extra}

    def area_rows(lst: List[dict], vals: Optional[List[Optional[Tuple[float, str]]]] = None) -> Tuple[List[dict], List[float]]:
        rows, ats = [], []
        for j, a in enumerate(lst):
            row = {"id": a["id"], "label": a["label"], "at": rel(a["pos"])}
            if vals and vals[j]:
                row["value"] = _fmt(vals[j][0])
            rows.append(row)
            ats.append(line_at(a["pos"]))
        return rows, ats

    # two areas compared
    if len(areas) >= 2 and _COMPARE.search(line) and ok(COMPARE):
        rows, ats = area_rows(areas[:2])
        return done(COMPARE, {"areas": rows, "_areas_at": ats, "locations": []})
    # three or more areas, each with a figure
    if len(areas) >= 3 and ok(CHOROPLETH):
        vals = _area_values(line, areas)
        withv = [(a, v) for a, v in zip(areas, vals) if v]
        if len(withv) >= 3:
            units = {v[1] for _a, v in withv}
            rows, ats = area_rows([a for a, _v in withv][:12], [v for _a, v in withv][:12])
            return done(CHOROPLETH, {"areas": rows, "_areas_at": ats, "suffix": units.pop() if len(units) == 1 else "",
                                     "locations": []})
    # a distance round a place
    rm = _RADIUS.search(line)
    if rm and locs and ok(RADIUS):
        v = _num(rm.group("v") or rm.group("v2"))
        u = (rm.group("u") or rm.group("u2") or "").lower()
        if v and 0.5 <= v <= 3000:
            p = ordered[0]
            return done(RADIUS, {"locations": [p], "value": _fmt(v), "suffix": "mi" if u.startswith("mi") else "km",
                                 "items": [{"label": f"{_fmt(v)} {'mi' if u.startswith('mi') else 'km'}", "at": rel(rm.start())}],
                                 "_items_at": [line_at(rm.start())]})
    # goods / people moving from one place to the others
    if len(found) >= 2 and _FLOW.search(line) and ok(FLOWS):
        inward = bool(_INWARD.search(line))
        pts = [x for _i, x in found][:7]
        return done(FLOWS, {"locations": pts, "direction": "in" if inward else "out",
                            "items": [{"label": _name(x.get("label") or ""), "at": rel(i)} for i, x in found[:7]],
                            "_items_at": [line_at(i) for i, _x in found[:7]]})
    # a route
    if 2 <= len(found) <= 6 and lookpack3.route_line(line) and ok(ROUTE):
        dist = re.search(rf"\b({_NUM})[\s-]+(miles?|kilomet(?:er|re)s?|km)\b", line, re.I)
        out = {"locations": [x for _i, x in found], "items": [{"label": _name(x.get("label") or ""), **({"at": rel(i)} if j else {})}
                                                              for j, (i, x) in enumerate(found)],
               "_items_at": [None] + [line_at(i) for i, _x in found[1:]]}
        if dist and _num(dist.group(1)):
            out.update(value=_fmt(_num(dist.group(1))), suffix="mi" if dist.group(2).lower().startswith("mi") else "km")
        return done(ROUTE, out)
    # several places (the map's own, all of them: each said one lands on its word, the rest with the first)
    if len(ordered) >= 2 and ok(PLACES):
        pts = ordered[:8]
        pos = {id(x): i for i, x in found}
        first = found[0][0] if found else 0
        return done(PLACES, {"locations": pts,
                             "items": [{"label": _name(x.get("label") or ""), "at": rel(pos.get(id(x), first))} for x in pts],
                             "_items_at": [line_at(pos.get(id(x), first)) for x in pts]})
    # one focus: the area the line names, else the first place
    focus = areas[0] if areas else None
    place = ordered[0] if ordered else None
    if not focus and not place:
        return None
    a3 = (focus or {}).get("a3", "")
    at_rows, at_ats = area_rows([focus]) if focus else ([], [])
    common = {"locations": [place] if place else []}
    if focus:
        common.update(areas=at_rows, _areas_at=at_ats)
    # a border or coast
    if _BORDER.search(line) and focus and ok(BORDER_TRACE):
        return done(BORDER_TRACE, common, a3)
    # terrain
    if _TERRAIN.search(line) and ok(RELIEF_TILT) and (focus or place):
        extra = dict(common)
        em = _ELEV.search(line)
        if em and _num(em.group("v")):
            extra.update(value=_fmt(_num(em.group("v"))), suffix="ft" if em.group("u").lower().startswith("f") else "m")
        return done(RELIEF_TILT, extra, a3)
    # one place or area: the most fitting single look, turned for variety
    cands: List[str] = []
    if place and (not state.counts or (a3 and a3 not in state.countries and not focus)):
        cands.append(ZOOM_DIVE)
    if focus and focus["kind"] in ("region", "country") and not place:
        cands.append(REGION_PULSE)
    if place and _SITE.search(line):
        cands.append(PIN_DROP)
    if _NATURE.search(line):
        cands.append(SAT_FLAT)
    if place:
        cands += [ZOOM_DIVE, PIN_DROP, SAT_FLAT]
    if focus:
        cands += [REGION_PULSE, SAT_FLAT]
    cands = [c for i, c in enumerate(cands) if c not in cands[:i] and ok(c)]
    if not cands:
        return None
    # the first fitting one, unless it was the last look or is used much more than the next
    pick = cands[0]
    if len(cands) > 1 and (pick == state.last or state.counts.get(pick, 0) > state.counts.get(cands[1], 0) + 1):
        pick = cands[1]
    extra = dict(common)
    if pick in (ZOOM_DIVE, PIN_DROP) and place:
        i = _first_at(line, _name(place.get("label") or ""))
        if i >= 0:
            extra.update(items=[{"label": _name(place.get("label") or ""), "at": rel(i)}], _items_at=[line_at(i)])
    if pick == ZOOM_DIVE and place:
        # the dive's country word, then its place: both on their words when said, else the look's own pace
        country_area = next((a for a in areas if a["kind"] == "country"), None)
        if country_area and place:
            i = _first_at(line, _name(place.get("label") or ""))
            extra.update(items=[{"label": country_area["label"], "at": rel(country_area["pos"])},
                                {"label": _name(place.get("label") or ""), **({"at": rel(i)} if i >= 0 else {})}],
                         _items_at=[line_at(country_area["pos"]), line_at(i) if i >= 0 else None])
    if pick == SAT_FLAT and focus:
        extra.update(items=[{"label": focus["label"], "at": rel(focus["pos"])}], _items_at=[line_at(focus["pos"])])
    return done(pick, extra, a3)


# --------------------------------------------------------------------------- the brand kit
# The Smart Editor's kits (components/maps2/kit.ts; feature/smart-editor src/brandkits.py): same ids.
KITS = ("royal", "noir", "bulletin", "atlas")
_BY_STYLE = {"documentary": "noir", "history": "noir", "true_crime": "noir", "news": "bulletin", "news_compilation": "bulletin",
             "explainer": "royal", "educational": "atlas", "science": "atlas", "travel": "atlas", "geography": "atlas"}


def kit_of(doc: dict) -> str:
    """
    The kit a video's maps draw with: the job's / channel's smart kit (doc.meta.smart_kit, brand.kit.id or
    brand.smart_kit), else by its video style; '' leaves the renderer's default (royal, with the brand's accent).
    """
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    brand = doc.get("brand") if isinstance(doc.get("brand"), dict) else {}
    for k in (meta.get("smart_kit"), brand.get("smart_kit"), (brand.get("kit") or {}).get("id") if isinstance(brand.get("kit"), dict) else None):
        if isinstance(k, str) and k in KITS:
            return k
    style = str(meta.get("video_style") or meta.get("style") or "").lower()
    return _BY_STYLE.get(style, "")
