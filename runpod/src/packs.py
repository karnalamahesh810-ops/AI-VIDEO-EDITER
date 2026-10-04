"""
Niche footage packs: a shelf of pre-checked clips per niche, always reachable,
so a scene the footage search left empty gets a clip that fits its line - at
once, for free, with no search (the owner's rules, 2026-10-01: "no missing
clips, no missing images, perfect video"; every clip must fit its own line).

A pack is one manifest on R2, packs/<niche>/index.json in the library bucket,
read by its PUBLIC link - the worker needs no key to read it; only a pack build
(src/packbuild.py, scripts/build_pack.py) writes. Each entry is one 4-10 second
clip, already cut at a shot change, transcoded to the worker's clip format and
passed through the library's quality gate (decodes, long enough, not black,
frozen, soft, letterboxed, covered in text or graphics, AI-made or a cartoon),
with where it came from, its licence, the people to credit, and a CLIP picture
embedding (the mean of the clip's frames, float16 in base64). Sources are only
NASA, Wikimedia Commons (public domain, CC0, or CC BY / BY-SA with the author
and licence stored), the Internet Archive (an explicit public-domain or CC0
licence URL) and the owner's own unused library clips - see packbuild.

  NICHES          water, weather, fire, earth, nature, cities - each a list of
                  topics (a short phrase, a few CLIP prompts, the words a line
                  would use, the searches a build runs);
  detect_niches   which niches a story is about, off its title, brief and style
                  (a Lake Powell video: water + nature); use_job keeps them for
                  the job, niches_for adds the ones the line itself names;
  load            a niche's manifest, by public link (or PACKS_DIR), kept in
                  memory PACKS_CACHE_SECONDS; a missing one is an empty shelf;
  find            the clips whose picture best fits a line: the CLIP cosine of
                  the line's description to each clip's embedding, never under
                  a minimum (a clip that does not fit is never used), a small
                  bonus for topic words the line shares, never a clip the video
                  already shows (gapfill.Used), never one an earlier video of
                  the owner showed (the cross-video ledger, CROSS_VIDEO_REUSE_DAYS);
  pick / fetch    the fallback ladder's first rung (gapfill._from_pack): claim
                  one, download it, hand it over as a MediaAsset;
  first_pass      PACKS_FIRST (off): before any search, the lines a pack fits
                  best - never the hook, never an exact event or place.

Limits, honestly. A pack holds general footage - satellite passes, aerial and
time-lapse shots, archive film - so it fits a line about "a drought" or "a
reservoir with a bathtub ring", never "the exact bridge in the exact town": a
line that names its own event or place needs a higher similarity and the
clip is flagged for review. Its size is the size of the last build; with the
cross-video rule on, a pack of a few hundred clips lasts a handful of videos
before it runs dry, and only a new build refills it. Retrieval is CLIP's
sense of the line's words against the clip's frames - good at things and
scenes, weak at numbers, names and dates. Without the local CLIP model, or
without a manifest, nothing is found and the ladder goes on to the library.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import math
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from . import config

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with faster-whisper
    np = None

MANIFEST_VERSION = 1
MODEL = "clip-vit-base-patch16"
LICENSE_CLASSES = ("pd", "cc0", "cc-by", "cc-by-sa", "unverified")


# --------------------------------------------------------------------------- #
# The niches
# --------------------------------------------------------------------------- #

@dataclasses.dataclass(frozen=True)
class Topic:
    """One kind of shot a niche is made of."""
    name: str                       # "low lake levels"
    prompts: Tuple[str, ...]        # CLIP prompts: how a picture of it would be described
    words: Tuple[str, ...] = ()     # what a narration line says about it
    queries: Tuple[str, ...] = ()   # what a build searches the archives for


@dataclasses.dataclass(frozen=True)
class Niche:
    name: str
    label: str
    keywords: Tuple[str, ...]       # words and phrases that say a story is about this niche
    topics: Tuple[Topic, ...]

    def topic(self, name: str) -> Optional[Topic]:
        return next((t for t in self.topics if t.name == name), None)


def _t(name: str, prompts: Sequence[str], words: str = "", queries: str = "") -> Topic:
    def split(s: str) -> Tuple[str, ...]:
        return tuple(x.strip() for x in s.split(",") if x.strip())
    return Topic(name, tuple(prompts), split(words), split(queries) or (name,))


def _n(name: str, label: str, keywords: str, topics: Sequence[Topic]) -> Niche:
    return Niche(name, label, tuple(k.strip() for k in keywords.split(",") if k.strip()), tuple(topics))


NICHES: Dict[str, Niche] = {n.name: n for n in (
    _n("water", "Water", (
        "water, drought, megadrought, reservoir, dam, lake, river, canal, aqueduct, irrigation, aquifer, "
        "groundwater, snowpack, runoff, desalination, shortage, watershed, spillway, hydroelectric, rationing, "
        "colorado river, lake mead, lake powell, hoover dam, glen canyon, bathtub ring, water level, "
        "water supply, drinking water"), [
        _t("drought", ["cracked dry earth in a drought", "a parched drought-stricken landscape",
                       "aerial view of dry brown barren land"],
           "drought, dry, parched, arid, cracked, barren, dust, thirsty", "drought, dry cracked earth"),
        _t("reservoirs", ["a reservoir surrounded by canyon walls", "aerial view of a large reservoir lake",
                          "a man-made lake behind a dam"],
           "reservoir, lake, storage, impound, canyon", "reservoir, lake aerial"),
        _t("low lake levels", ["a lake with very low water and an exposed shoreline",
                               "a shrinking lake with a dry cracked lakebed",
                               "boat docks stranded on dry land beside a low lake"],
           "low, level, shrinking, receding, exposed, shoreline, record, falling, drop, dropped, feet, capacity",
           "low water level lake, lake mead, lake powell"),
        _t("bathtub rings", ["a white mineral bathtub ring on canyon walls above a reservoir",
                             "a reservoir with a pale high-water line on the rock walls"],
           "bathtub, ring, line, mineral, bleached, stain, high-water", "bathtub ring lake mead, lake mead low water"),
        _t("dams", ["a huge concrete dam wall", "aerial view of a hydroelectric dam",
                    "water pouring through a dam spillway"],
           "dam, spillway, hydroelectric, hoover, glen, turbine, concrete, wall, power", "dam, hoover dam, glen canyon dam"),
        _t("dry riverbeds", ["a dry riverbed with cracked mud", "an empty river channel with no water",
                             "a river running low over dry rocks"],
           "river, riverbed, creek, stream, dry, empty, trickle, bed", "dry riverbed, river drought"),
        _t("canals", ["a concrete canal carrying water through the desert", "an irrigation canal with flowing water",
                      "aerial view of a long straight canal"],
           "canal, channel, diversion, ditch, diverted", "canal, irrigation canal"),
        _t("aqueducts", ["a large aqueduct carrying water across land", "a water pipeline crossing the desert",
                         "a water conveyance tunnel and pipes"],
           "aqueduct, pipeline, pipe, conveyance, tunnel, pump", "aqueduct, water pipeline"),
        _t("irrigation", ["center pivot irrigation in green farm fields", "sprinklers watering crops in a field",
                          "aerial view of circular irrigated fields in the desert"],
           "irrigation, irrigate, irrigated, sprinkler, farm, farmer, crops, field, agriculture, pivot, alfalfa",
           "irrigation, center pivot irrigation"),
        _t("water towers", ["a water tower against the sky", "an elevated municipal water storage tank"],
           "tower, tank, municipal, tap, supply, utility", "water tower"),
        _t("desalination", ["a desalination plant on the coast",
                            "a reverse osmosis water treatment facility with pipes and tanks"],
           "desalination, desalinate, seawater, osmosis, treatment, plant, salt", "desalination plant, reverse osmosis"),
    ]),
    _n("weather", "Weather", (
        "weather, storm, rain, rainfall, flood, flooding, hurricane, typhoon, cyclone, tornado, lightning, "
        "thunderstorm, snow, blizzard, heatwave, heat wave, wind, forecast, tropical, monsoon, hail, nor easter, "
        "noreaster, derecho, squall, gale, atmospheric river, el nino, la nina, storm surge, downpour"), [
        _t("storm clouds", ["dark storm clouds gathering over a landscape", "a towering thunderstorm cloud",
                            "a shelf cloud rolling in ahead of a storm"],
           "storm, cloud, clouds, thunderstorm, supercell, dark, front, brewing", "storm clouds, thunderstorm timelapse, shelf cloud"),
        _t("rain", ["heavy rain falling on a street", "rain pouring down on a city",
                    "raindrops on a window and wet pavement"],
           "rain, rainfall, downpour, shower, wet, precipitation, soaked", "heavy rain, rainstorm"),
        _t("flooding streets", ["a flooded street with water covering cars", "floodwater rushing through a town",
                                "aerial view of a flooded neighborhood"],
           "flood, flooding, flooded, inundated, floodwater, submerged, surge, rescue", "flooded street, flood aerial, flash flood"),
        _t("hurricanes from space", ["a hurricane seen from space",
                                     "a satellite view of a spiral tropical storm over the ocean",
                                     "the eye of a hurricane from the international space station"],
           "hurricane, typhoon, cyclone, tropical, eye, satellite, space, landfall, category",
           "hurricane from space, hurricane satellite, tropical storm space station"),
        _t("tornadoes", ["a tornado funnel touching the ground", "a large wedge tornado across a field",
                         "a funnel cloud descending from a storm"],
           "tornado, twister, funnel, supercell, wedge, vortex, touchdown", "tornado, funnel cloud"),
        _t("lightning", ["lightning bolts striking in a night sky", "a lightning storm over a city",
                         "lightning seen from space"],
           "lightning, thunder, bolt, strike, electric, flash", "lightning, lightning storm"),
        _t("snow storms", ["a heavy snowstorm with blowing snow", "snow falling on a street in a blizzard",
                           "a snow-covered road in a winter storm"],
           "snow, blizzard, snowstorm, winter, ice, freezing, whiteout, snowfall", "snowstorm, blizzard"),
        _t("heat haze", ["heat haze shimmering over a hot road", "a blazing sun over a scorched dry landscape",
                         "a heatwave with the sun low and hazy"],
           "heat, heatwave, hot, haze, scorching, sun, temperature, swelter, triple-digit", "heat haze, heatwave"),
        _t("wind", ["strong wind bending trees", "wind blowing dust across a field",
                    "a windstorm tearing at palm trees"],
           "wind, gale, gust, gusts, windstorm, breeze, blow, blowing", "strong wind, windstorm trees"),
    ]),
    _n("fire", "Fire", (
        "wildfire, fire, blaze, smoke, burn, burned, firefighter, evacuation, flames, arson, inferno, burn scar, "
        "red flag, containment, air tanker, fire season"), [
        _t("wildfire", ["a wildfire burning across hills", "flames racing through a forest",
                        "an aerial view of an active wildfire at night"],
           "wildfire, fire, flames, blaze, burn, burning, inferno, spreading", "wildfire, forest fire"),
        _t("smoke plumes", ["a huge column of smoke rising from a fire", "a smoke plume over mountains",
                            "wildfire smoke seen from space"],
           "smoke, plume, haze, smog, ash, column, orange", "smoke plume, wildfire smoke satellite"),
        _t("burned forest", ["a burned forest with blackened tree trunks", "a charred hillside after a wildfire",
                             "a burn scar landscape of ash"],
           "burned, burnt, charred, scorched, ash, aftermath, scar, blackened", "burned forest, burn scar"),
        _t("firefighting aircraft", ["an air tanker dropping fire retardant", "a helicopter dropping water on a wildfire",
                                     "firefighters battling a blaze"],
           "firefighter, firefighters, aircraft, tanker, helicopter, retardant, drop, crew, hotshot",
           "air tanker fire retardant, firefighting helicopter"),
    ]),
    _n("earth", "Earth", (
        "earthquake, quake, seismic, volcano, eruption, lava, magma, landslide, mudslide, sinkhole, tsunami, fault, "
        "aftershock, tectonic, richter, magnitude, subsidence, rockfall"), [
        _t("earthquake damage", ["a collapsed building after an earthquake", "rubble and a cracked road after an earthquake",
                                 "earthquake damage to a city street"],
           "earthquake, quake, seismic, tremor, collapse, collapsed, rubble, damage, fault, magnitude",
           "earthquake damage, earthquake rubble"),
        _t("volcano", ["a volcano erupting with lava and ash", "an ash plume rising from a volcano",
                       "glowing lava flowing down a slope"],
           "volcano, eruption, erupt, lava, magma, ash, crater, volcanic", "volcano eruption, lava flow"),
        _t("landslide", ["a landslide scar on a mountain slope", "mud and rocks sliding down a hillside",
                         "a road buried by a landslide"],
           "landslide, mudslide, slope, debris, rockfall, slide, slip", "landslide, mudslide"),
        _t("sinkholes", ["a huge sinkhole opening in the ground", "a collapsed hole in a road",
                         "an aerial view of a circular sinkhole"],
           "sinkhole, subsidence, collapse, cavity, hole, sinking", "sinkhole, land subsidence"),
    ]),
    _n("nature", "Nature", (
        "nature, forest, mountain, desert, canyon, glacier, coast, coastline, ocean, wildlife, landscape, wilderness, "
        "national park, river, lake, valley, plateau, island, beach, jungle, rainforest, ice, tundra, arctic"), [
        _t("aerial landscapes", ["an aerial view of a vast landscape", "drone footage flying over mountains and valleys",
                                 "a sweeping aerial shot of canyons"],
           "aerial, landscape, drone, scenic, vista, mountains, canyon, terrain, valley, plateau",
           "aerial landscape, drone landscape, canyon aerial"),
        _t("rivers", ["a river winding through a valley", "an aerial view of a meandering river",
                      "a fast flowing river over rocks"],
           "river, stream, creek, flow, flowing, rapids, meander", "river aerial, river flowing"),
        _t("forests", ["a dense green forest", "an aerial view of a forest canopy", "sunlight through tall trees"],
           "forest, trees, woods, canopy, woodland, timber, pine", "forest, forest aerial"),
        _t("deserts", ["a vast desert with sand dunes", "a dry desert landscape with rocks and cacti",
                       "an aerial view of a barren desert"],
           "desert, dunes, sand, arid, cactus, badlands, dry, mesa", "desert, desert aerial, sand dunes"),
        _t("coastlines", ["waves crashing on a rocky coastline", "an aerial view of a beach and coast",
                          "ocean waves rolling onto a shore"],
           "coast, coastline, shore, beach, ocean, sea, waves, cliff, tide", "coastline, ocean waves coast, beach aerial"),
        _t("glaciers", ["a glacier and ice field", "an ice sheet calving into the sea",
                        "an aerial view of a melting glacier"],
           "glacier, ice, iceberg, melt, melting, calving, polar, arctic, sheet", "glacier, glacier melting, ice sheet"),
    ]),
    _n("cities", "Cities", (
        "city, cities, skyline, downtown, urban, traffic, highway, freeway, bridge, infrastructure, skyscraper, metro, "
        "street, commute, suburb, power grid, blackout, housing, crowd, pedestrians"), [
        _t("skylines", ["a city skyline at dusk", "an aerial view of skyscrapers downtown",
                        "a skyline across a river at night"],
           "skyline, city, downtown, skyscraper, tower, urban, buildings", "city skyline, downtown aerial"),
        _t("traffic", ["heavy traffic on a highway", "cars on a busy city street",
                       "an aerial view of a freeway interchange"],
           "traffic, highway, freeway, cars, road, commute, congestion, drivers", "highway traffic, traffic timelapse"),
        _t("crowds", ["a crowd of people walking on a city street", "a large crowd gathered in a plaza",
                      "pedestrians crossing a busy intersection"],
           "crowd, crowds, people, pedestrians, street, plaza, rush, residents", "crowd, pedestrians city"),
        _t("infrastructure", ["a bridge over a river", "power lines and an electric substation",
                              "a power plant with cooling towers", "pipes and an industrial facility"],
           "infrastructure, bridge, power, grid, plant, pipeline, substation, transmission, utility, aging",
           "bridge, power lines, power plant"),
    ]),
)}

# A video style that is about a niche whatever its title says.
STYLE_NICHES = {"nature_weather": ("weather", "nature")}

_STOP = {"the", "a", "an", "of", "in", "on", "at", "and", "or", "to", "for", "with", "from", "by", "is", "are", "was",
         "were", "it", "its", "this", "that", "as", "be", "has", "have", "had", "more", "than", "into", "over"}


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower().replace("'", "")).split())


def _stem(word: str) -> str:
    """A crude stem, enough for 'floods/flooded/flooding', 'lake/lakes' and 'wildfire/wildfires' to meet."""
    w = word
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[:-len(suf)]
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def _stems(text: Any) -> set:
    return {_stem(w) for w in _norm(text).split() if len(w) > 2 and w not in _STOP and not w.isdigit()}


def _has_keyword(kw: str, stems: set, text: str) -> bool:
    kw = _norm(kw)
    if " " in kw:
        return f" {kw} " in f" {text} "
    return _stem(kw) in stems


def detect_niches(*texts: Any, style: str = "", limit: int = 3) -> List[str]:
    """
    The niches a story is about, best first: how many of each niche's words
    and phrases the texts (title, event, summary, places, a line) use. The best
    niche always counts; another needs two hits and a quarter of the best one's,
    so one stray word ("city" in a drought story) does not bring a shelf along.
    A Lake Powell story: water + nature (lake, canyon).
    """
    text = _norm(" ".join(str(t or "") for t in texts))
    stems = _stems(text)
    scores: Dict[str, float] = {}
    for niche in NICHES.values():
        hits = sum(1 for kw in niche.keywords if _has_keyword(kw, stems, text))
        if niche.name in STYLE_NICHES.get(str(style or "").strip().lower(), ()):
            hits += 2
        if hits:
            scores[niche.name] = float(hits)
    if not scores:
        return []
    top = max(scores.values())
    order = list(NICHES)
    ranked = sorted(scores, key=lambda n: (-scores[n], order.index(n)))
    keep = [n for n in ranked if scores[n] == top or (scores[n] >= 2 and scores[n] >= 0.25 * top)]
    return keep[:max(1, limit)]


# The job's niches, read once off its story (use_job); a scene adds its own (niches_for).
JOB: Dict[str, Any] = {}
STATS: Dict[str, Any] = {"loaded": {}, "lookups": 0, "hits": 0}
# Pack clips this job found too soft for the frame (src/sharpness.py): not fetched again.
_SOFT: set = set()


def reset() -> None:
    JOB.clear()
    STATS.update(loaded={}, lookups=0, hits=0)
    _SOFT.clear()


def use_job(title: str = "", brief: Optional[dict] = None, style: str = "", text: str = "") -> List[str]:
    """Read the job's niches off its title, story brief and video style; returns them."""
    brief = brief if isinstance(brief, dict) else {}
    try:
        places = " ".join(str(p) for p in (brief.get("places") or []) if isinstance(p, str))
        niches = detect_niches(title, brief.get("event"), brief.get("summary"), brief.get("kind"), places, text,
                               style=style)
    except Exception as e:  # noqa: BLE001 - a footage shelf never fails a video
        print(f"[packs] niches not read: {type(e).__name__}: {str(e)[:80]}", flush=True)
        niches = []
    JOB.update(niches=niches, title=str(title or "")[:120], style=str(style or ""))
    if niches:
        print(f"[packs] this video's niches: {', '.join(niches)}", flush=True)
    return niches


def forced_niches() -> List[str]:
    """PACKS_NICHES ("water,nature"): the job's own choice, unknown names ignored."""
    return [n for n in (x.strip().lower() for x in str(config.PACKS_NICHES or "").split(",")) if n in NICHES]


# --------------------------------------------------------------------------- #
# Small codecs
# --------------------------------------------------------------------------- #

def encode_vec(vec) -> str:
    """A unit vector as base64 float16 (about 1.4 KB for CLIP's 512 numbers)."""
    return base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode("ascii")


def decode_vec(text: str):
    """The unit vector encode_vec wrote (float32), None when it cannot be read."""
    try:
        raw = base64.b64decode(str(text or ""), validate=True)
        v = np.frombuffer(raw, dtype=np.float16).astype(np.float32)
    except (ValueError, TypeError):
        return None
    n = float(np.linalg.norm(v))
    return v / n if v.size and n > 1e-6 and math.isfinite(n) else None


def safe_id(text: str, width: int = 90) -> str:
    """Letters, digits, '_' and '-' only: a YouTube-style 'yt:' prefix must not survive in a clip's name."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(text or "")).strip("_")[:width]


# --------------------------------------------------------------------------- #
# Entries and packs
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class Entry:
    """One clip of a pack, as its manifest keeps it."""
    id: str                                   # "<source>-<source id>@<start second>"
    niche: str
    url: str                                  # the clip, public (a local file in a local pack)
    seconds: float = 0.0
    width: int = 0
    height: int = 0
    topics: List[str] = dataclasses.field(default_factory=list)
    source: str = ""                          # nasa | wikimedia | archive_org | library
    license: str = ""                         # as shown to the owner: "Public domain (NASA)", "CC BY-SA 4.0"
    license_class: str = "unverified"         # pd | cc0 | cc-by | cc-by-sa | unverified
    license_url: str = ""
    attribution: str = ""                     # who to credit, kept for every entry that needs it
    source_url: str = ""                      # the page it came from
    start: float = 0.0                        # where in that source this clip begins
    title: str = ""
    thumb: str = ""
    phash: List[Optional[str]] = dataclasses.field(default_factory=list)
    checks: Dict[str, Any] = dataclasses.field(default_factory=dict)
    created: str = ""
    vec: Any = dataclasses.field(default=None, repr=False, compare=False)

    @property
    def asset_id(self) -> str:
        """What the timeline and the ledger call this clip: pack:<niche>:<source>@<start>."""
        return f"pack:{self.niche}:{self.id}"

    @property
    def video(self) -> str:
        """The source video every clip cut from it shares (gapfill treats the starts as moments of it)."""
        return self.asset_id.rsplit("@", 1)[0] if "@" in self.asset_id else self.asset_id

    @property
    def moment_url(self) -> str:
        """The source page at this clip's start: sibling clips of one source differ, like moments of a YouTube video."""
        page = self.source_url
        if not page:
            return ""
        if self.source == "library" or re.search(r"[?&](?:v|t)=", page):
            return page                       # a YouTube link already says where
        return f"{page}{'&' if '?' in page else '?'}t={int(self.start)}"

    @property
    def words(self) -> frozenset:
        """The stems of the words the clip's topics use (for the small ranking bonus)."""
        niche = NICHES.get(self.niche)
        out: set = set()
        for name in self.topics:
            topic = niche.topic(name) if niche else None
            out |= _stems(name)
            if topic:
                for w in topic.words:
                    out |= _stems(w)
        return frozenset(out)

    def to_dict(self) -> dict:
        d = {"id": self.id, "url": self.url, "niche": self.niche, "topics": list(self.topics),
             "seconds": round(float(self.seconds), 2), "width": int(self.width), "height": int(self.height),
             "source": self.source, "license": self.license, "licenseClass": self.license_class,
             "licenseUrl": self.license_url, "attribution": self.attribution, "sourceUrl": self.source_url,
             "start": round(float(self.start), 2), "title": self.title, "thumb": self.thumb,
             "phash": list(self.phash), "checks": dict(self.checks), "created": self.created}
        if self.vec is not None:
            d["embedding"] = encode_vec(self.vec)
        return d

    @classmethod
    def from_dict(cls, d: dict, niche: str = "") -> Optional["Entry"]:
        """An entry from its manifest row; None for a row that cannot be used (no link, no readable embedding)."""
        if not isinstance(d, dict) or not d.get("id") or not d.get("url"):
            return None
        vec = decode_vec(d.get("embedding"))
        if vec is None:
            return None
        klass = str(d.get("licenseClass") or "unverified").lower()
        try:
            return cls(
                id=str(d["id"]), niche=str(d.get("niche") or niche), url=str(d["url"]),
                seconds=float(d.get("seconds") or 0.0), width=int(d.get("width") or 0), height=int(d.get("height") or 0),
                topics=[str(t) for t in (d.get("topics") or []) if t], source=str(d.get("source") or ""),
                license=str(d.get("license") or ""), license_class=klass if klass in LICENSE_CLASSES else "unverified",
                license_url=str(d.get("licenseUrl") or ""), attribution=str(d.get("attribution") or ""),
                source_url=str(d.get("sourceUrl") or ""), start=float(d.get("start") or 0.0),
                title=str(d.get("title") or ""), thumb=str(d.get("thumb") or ""),
                phash=list(d.get("phash") or []), checks=dict(d.get("checks") or {}),
                created=str(d.get("created") or ""), vec=vec)
        except (TypeError, ValueError):
            return None


class Pack:
    """A niche's entries with their embeddings stacked for one matrix product."""

    def __init__(self, niche: str, entries: List[Entry], meta: Optional[dict] = None):
        self.niche = niche
        self.meta = dict(meta or {})
        dim = len(entries[0].vec) if entries else 0
        self.entries = [e for e in entries if e.vec is not None and len(e.vec) == dim]
        self.dropped = len(entries) - len(self.entries)
        self.matrix = np.stack([e.vec for e in self.entries]) if self.entries else None
        self.loaded_at = time.time()

    @property
    def dim(self) -> int:
        return int(self.matrix.shape[1]) if self.matrix is not None else 0

    @classmethod
    def from_manifest(cls, niche: str, data: dict) -> "Pack":
        rows = data.get("entries") if isinstance(data, dict) else None
        entries = [e for e in (Entry.from_dict(r, niche) for r in rows or []) if e]
        meta = {k: v for k, v in (data or {}).items() if k != "entries"} if isinstance(data, dict) else {}
        return cls(niche, entries, meta)

    def by_id(self, entry_id: str) -> Optional[Entry]:
        return next((e for e in self.entries if e.id == entry_id), None)


def manifest(niche: str, entries: Iterable[Entry], sources: Optional[dict] = None, **extra) -> dict:
    """The manifest a pack build writes (and load reads back)."""
    items = sorted(entries, key=lambda e: e.id)
    dim = next((len(e.vec) for e in items if e.vec is not None), 0)
    return {"v": MANIFEST_VERSION, "niche": niche, "model": MODEL, "dim": dim,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": len(items), "entries": [e.to_dict() for e in items],
            "sources": dict(sources or {}), **extra}


# --------------------------------------------------------------------------- #
# Where packs live, and reading them
# --------------------------------------------------------------------------- #

def key_prefix(niche: str) -> str:
    """The R2 key folder of a niche: <library prefix>packs/<niche>/."""
    return f"{config.R2_LIBRARY_PREFIX}{str(config.PACKS_PREFIX or 'packs/').strip('/')}/{niche}/"


def public_base() -> str:
    return str(config.PACKS_PUBLIC_BASE or getattr(config, "R2_LIBRARY_PUBLIC_BASE", "") or "").rstrip("/")


def manifest_url(niche: str) -> str:
    """The public link of a niche's manifest ("" when no public domain is configured)."""
    base = public_base()
    return f"{base}/{key_prefix(niche)}index.json" if base else ""


def available() -> bool:
    """Packs can be read here (a public domain or a local folder is configured)."""
    return bool(config.PACKS_DIR or public_base())


_CACHE: Dict[str, Tuple[float, Optional[Pack]]] = {}
_CACHE_LOCK = threading.Lock()
_LOAD_LOCKS: Dict[str, threading.Lock] = {}
_MISSING_SECONDS = 60.0


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _read_manifest(niche: str) -> Optional[dict]:
    if config.PACKS_DIR:
        path = os.path.join(config.PACKS_DIR, niche, "index.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    url = manifest_url(niche)
    if not url:
        return None
    r = requests.get(url, timeout=(5, 25), headers={"User-Agent": config.USER_AGENT})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def load(niche: str, refresh: bool = False) -> Optional[Pack]:
    """
    A niche's pack, from memory when read within PACKS_CACHE_SECONDS; None when
    there is none (not built yet, no public domain, unreachable). A miss is
    remembered for a minute so a dead link costs one request, not one per
    scene. Never raises.
    """
    niche = str(niche or "").strip().lower()
    if niche not in NICHES or not available():
        return None
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(niche)
        lock = _LOAD_LOCKS.setdefault(niche, threading.Lock())
    if hit and not refresh and now - hit[0] < (config.PACKS_CACHE_SECONDS if hit[1] else _MISSING_SECONDS):
        return hit[1]
    with lock:                                    # one request per niche, however many scenes ask at once
        with _CACHE_LOCK:
            hit = _CACHE.get(niche)
        if hit and not refresh and time.time() - hit[0] < (config.PACKS_CACHE_SECONDS if hit[1] else _MISSING_SECONDS):
            return hit[1]
        pack = None
        try:
            data = _read_manifest(niche)
            if data is not None:
                pack = Pack.from_manifest(niche, data)
                STATS["loaded"][niche] = len(pack.entries)
                print(f"[packs] {niche}: {len(pack.entries)} clip(s)"
                      + (f", {pack.dropped} unreadable row(s) left out" if pack.dropped else ""), flush=True)
        except Exception as e:  # noqa: BLE001 - an unreadable shelf is an empty one
            print(f"[packs] {niche}: not read ({type(e).__name__}: {str(e)[:100]})", flush=True)
        with _CACHE_LOCK:
            _CACHE[niche] = (time.time(), pack if pack and pack.entries else None)
        return _CACHE[niche][1]


# --------------------------------------------------------------------------- #
# What a line is about
# --------------------------------------------------------------------------- #

def _clean(text: Any, width: int = 200) -> str:
    return " ".join(str(text or "").split())[:width]


def line_texts(job: dict) -> List[str]:
    """
    How the line's picture would be described, best first: the planner's intent
    for the shot, the search it ran, the scene's visual subjects, the narration
    itself. CLIP reads each against the clip's frames; the best one counts.
    """
    out: List[str] = []
    si = job.get("scene_intent") if isinstance(job.get("scene_intent"), dict) else {}
    parts = [job.get("intent"), job.get("query"), *(si.get("visual_subjects") or [])[:2], job.get("subject"),
             job.get("context")]
    for p in parts:
        p = _clean(p)
        if p and p.lower() not in [o.lower() for o in out]:
            out.append(p)
    return out[:5]


def niches_for(job: Optional[dict] = None) -> List[str]:
    """PACKS_NICHES if set; else the video's niches plus the ones the line itself is about (three at most)."""
    forced = forced_niches()
    if forced:
        return forced
    out = list(JOB.get("niches") or [])
    if job:
        for n in detect_niches(*line_texts(job), limit=2):
            if n not in out:
                out.append(n)
    return out[:3]


def allowed_licenses(require_cc: bool = False) -> set:
    """The licence classes a job may take (PACKS_LICENSES); a claim-free channel never takes 'unverified'."""
    got = {c.strip() for c in str(config.PACKS_LICENSES or "").split(",") if c.strip() in LICENSE_CLASSES}
    return got - {"unverified"} if require_cc else got


def _clip():
    """The local CLIP module when it can embed text, else None."""
    if np is None:
        return None
    try:
        from . import localvision
        return localvision if localvision.available() else None
    except Exception:  # noqa: BLE001
        return None


def query_vectors(texts: Sequence[str]):
    """One unit vector per text: CLIP's reading of 'a photo of X' and 'footage of X', averaged (as Library.search does)."""
    lv = _clip()
    if lv is None or not texts:
        return None
    rows = []
    for t in texts:
        v = lv.embed_texts([f"a photo of {t}", f"footage of {t}"]).mean(axis=0)
        rows.append(v / max(float(np.linalg.norm(v)), 1e-8))
    return np.stack(rows)


def threshold(job: Optional[dict] = None, first: bool = False) -> float:
    """
    The least similarity a clip needs for this line: PACKS_MIN_SIMILARITY (or
    PACKS_FIRST_MIN_SIMILARITY before any search), PACKS_SPECIFIC_EXTRA more
    for a line that names its own event or place - a general clip proves
    little about an exact one.
    """
    base = config.PACKS_FIRST_MIN_SIMILARITY if first else config.PACKS_MIN_SIMILARITY
    return base + (config.PACKS_SPECIFIC_EXTRA if is_specific(job) else 0.0)


def is_specific(job: Optional[dict]) -> bool:
    """The line needs its exact event or place (scene intent: event/location, generic not ok)."""
    si = (job or {}).get("scene_intent")
    return bool(isinstance(si, dict) and si.get("specificity") in ("event", "location") and not si.get("generic_ok", True))


# --------------------------------------------------------------------------- #
# What the video and the owner's other videos already show
# --------------------------------------------------------------------------- #

def shot_of(entry: Entry, at: Optional[float] = None):
    """The clip as a gapfill.Shot: its file, and its start in its source video (a moment of it)."""
    from . import gapfill
    return gapfill.Shot(files=(entry.url,), video=entry.video, start=float(entry.start), at=at)


def seen_before(entry: Entry) -> bool:
    """An earlier video (within CROSS_VIDEO_REUSE_DAYS) showed this clip, or this source video near this moment."""
    try:
        from . import ledger
        return ledger.pack_used(entry.asset_id, entry.moment_url, entry.start, entry.start + max(1.0, entry.seconds))
    except Exception:  # noqa: BLE001 - a ledger problem never empties a shelf
        return False


# --------------------------------------------------------------------------- #
# Finding
# --------------------------------------------------------------------------- #

# A scene number that is nobody's, for a look-up not made for one scene.
_NO_SCENE = 10 ** 9


@dataclasses.dataclass
class Hit:
    entry: Entry
    similarity: float          # CLIP cosine of the best description of the line to the clip
    score: float               # similarity + topic bonus - short-clip penalty (the ranking)
    topics: List[str]


def covers(entry: Entry, seconds: float) -> bool:
    """The clip can fill `seconds` without playing slower than the renderer's floor (0.6x, src/quality.py)."""
    return seconds <= 0 or entry.seconds <= 0 or entry.seconds / 0.6 >= seconds - 0.07


def find(text, niches: Optional[Sequence[str]] = None, used=None, *, index: Optional[int] = None,
         at: Optional[float] = None, seconds: float = 0.0, n: int = 5, min_similarity: Optional[float] = None,
         exclude: Optional[set] = None, require_cc: bool = False, cross_video: bool = True) -> List[Hit]:
    """
    The clips of `niches` that best fit `text` (one description of the line, or
    several), best first - never one under `min_similarity`.

    A clip is left out when: its licence class is not allowed (PACKS_LICENSES;
    'unverified' never for a claim-free job); it is in `exclude` (ids or asset
    ids); it is too short to cover `seconds`; an earlier video of the owner
    showed it (cross_video: the ledger); or `used` (gapfill.Used) says this
    video cannot show it on scene `index` - the same file, the same clip, the
    same source video's neighbouring moment. Without the local CLIP model, a
    manifest or any similar clip the answer is [].
    """
    texts = [_clean(text)] if isinstance(text, str) else [_clean(t) for t in text or []]
    texts = [t for t in texts if t]
    if not texts:
        return []
    names = [x for x in (niches if niches is not None else detect_niches(*texts)) if x in NICHES]
    packs = [p for p in (load(x) for x in dict.fromkeys(names)) if p is not None]
    if not packs:
        return []
    q = query_vectors(texts)
    if q is None:
        return []
    floor = config.PACKS_MIN_SIMILARITY if min_similarity is None else float(min_similarity)
    allowed = allowed_licenses(require_cc)
    skip = set(exclude or ())
    wanted = set().union(*(_stems(t) for t in texts))
    STATS["lookups"] += 1
    found: List[Hit] = []
    for pack in packs:
        if pack.matrix is None or pack.dim != q.shape[1]:
            continue
        sims = (pack.matrix @ q.T).max(axis=1)
        for k in np.argsort(-sims):
            sim = float(sims[k])
            if sim < floor:
                break
            e = pack.entries[int(k)]
            if e.license_class not in allowed or e.id in skip or e.asset_id in skip or not covers(e, seconds):
                continue
            if cross_video and seen_before(e):
                continue
            if used is not None and used.why_not(_NO_SCENE if index is None else index, shot_of(e, at)):
                continue
            bonus = config.PACKS_TOPIC_BONUS * min(2, len(e.words & wanted)) / 2.0
            short = 0.04 * max(0.0, 1.0 - e.seconds / seconds) if seconds > 0 and e.seconds > 0 else 0.0
            found.append(Hit(e, sim, sim + bonus - short, [t for t in e.topics]))
            if len([h for h in found if h.entry.niche == pack.niche]) >= max(n, 1) * 3:
                break                                  # plenty from this shelf; the ranking below picks
    found.sort(key=lambda h: -h.score)
    if found:
        STATS["hits"] += 1
    return found[:max(1, n)]


# --------------------------------------------------------------------------- #
# Taking a clip
# --------------------------------------------------------------------------- #

_REVIEW = {"pd": "", "cc0": "",
           "cc-by": "Pack clip under CC BY: credit the author in the video's description",
           "cc-by-sa": "Pack clip under CC BY-SA: credit the author in the video's description",
           "unverified": "Pack clip from the clip library; licence unverified - confirm you hold the rights"}


def score_for(similarity: float) -> float:
    """CLIP cosine on the 0-1 scale the vision judge's relevance uses (src/localvision.as_verdict)."""
    return round(max(0.0, min(1.0, config.VISION_MIN_SCORE + (similarity - config.LOCAL_VISION_MIN_RELEVANCE) * 4.0)), 3)


def fetch(entry: Entry, work: str, job: Optional[dict] = None, similarity: Optional[float] = None):
    """
    The clip as a local MediaAsset for one line, None when it cannot be
    downloaded or does not decode. The pack's own file is never the working
    copy (a local pack is copied): later steps rewrite clips in place.
    """
    from . import filters, media, storage
    job = job or {}
    path = os.path.join(work, f"pack_{safe_id(entry.id)}.mp4")
    try:
        os.makedirs(work, exist_ok=True)
        if os.path.isfile(entry.url):
            shutil.copyfile(entry.url, path)
        else:
            storage.download(entry.url, path, timeout=120)
    except Exception as e:  # noqa: BLE001 - the ladder goes on
        print(f"[packs] could not fetch {entry.id}: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    if not filters.playable_video(path, min_seconds=min(1.0, max(0.5, entry.seconds * 0.5))):
        print(f"[packs] {entry.id} does not play; left out", flush=True)
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    # Held to the same real-detail check as a searched clip (src/sharpness.py; archive film exempt).
    soft = media.clip_detail_reason(path, f"{entry.title} {entry.attribution}", entry.source or "")
    if soft:
        print(f"[packs] {entry.id}: {soft}; left out", flush=True)
        _SOFT.add(entry.id)
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    note = _REVIEW.get(entry.license_class, "")
    topics = ", ".join(entry.topics[:3])
    asset = media.MediaAsset(
        kind="video", source=entry.source or "pack", url=entry.moment_url, local_path=path,
        width=entry.width, height=entry.height, duration=float(entry.seconds),
        attribution=(entry.attribution or entry.title)[:300], license=entry.license,
        query=(entry.topics[0] if entry.topics else entry.niche),
        intent=str(job.get("intent") or job.get("query") or ""),
        review_required=bool(note), review_reason=note,
        content_description=(f"{entry.title} ({topics})" if entry.title else topics)[:300],
        relevance_score=score_for(similarity) if similarity is not None else None,
        moment_key=entry.asset_id, moment={"start": float(entry.start), "pack": entry.niche})
    return asset


def pick(job: dict, used, work: str, stop: float, *, require_cc: bool = False, first: bool = False,
         min_similarity: Optional[float] = None):
    """
    One pack clip for one line: the best fit the video does not show yet,
    claimed in `used` before it is downloaded (released again if the download
    fails). None when no clip clears the line's similarity floor.
    """
    from . import media
    i = job["index"]
    seconds = float(job.get("seconds") or 6.0) + media.SEQ_SHOT_PAD
    floor = threshold(job, first) if min_similarity is None else min_similarity
    hits = find(line_texts(job), niches_for(job), used, index=i, at=job.get("start"), seconds=seconds, n=4,
                min_similarity=floor, require_cc=require_cc)
    for hit in hits:
        if time.time() > stop:
            return None
        if hit.entry.id in _SOFT:
            continue                        # found too soft for the frame earlier in this job
        shot = shot_of(hit.entry, job.get("start"))
        if not used.claim(i, shot):
            continue
        got = fetch(hit.entry, work, job, hit.similarity)
        if got is None:
            used.release(i, shot)
            continue
        print(f"[packs] scene {i + 1}: {hit.entry.id} ({hit.entry.niche}: {', '.join(hit.entry.topics[:2])}; "
              f"fit {hit.similarity:.2f})", flush=True)
        return got
    return None


def eligible(job: dict, youtube_only: bool = False) -> bool:
    """
    Is this a line a pack may fill: footage or a picture beat, not a person, and
    the job did not ask for YouTube only (the user's own choice of sources -
    a pack's NASA, Wikimedia and archive film are other sources).
    """
    if youtube_only or job.get("subject_type") == "person":
        return False
    return job.get("visual_type", "footage") in ("footage", "image")


def usable(job: dict, youtube_only: bool = False) -> bool:
    """The fallback ladder's first rung may try this line (PACKS_FILL on, a shelf reachable, an eligible line)."""
    return bool(config.PACKS_FILL and available() and eligible(job, youtube_only))


def first_pass(jobs: List[dict], work: str, *, require_cc: bool = False, seconds: Optional[float] = None) -> Dict[int, Any]:
    """
    PACKS_FIRST: before any search, the lines a pack clip fits best. Never the
    hook (it keeps the best search), never a person, never a line that needs
    its exact event or place; at most PACKS_FIRST_MAX_SHARE of the video's
    lines, the best fits first, each above PACKS_FIRST_MIN_SIMILARITY.
    Returns {line index: MediaAsset}; {} when no pack is here.
    """
    from . import gapfill, media
    if not (config.PACKS_FIRST and available() and jobs):
        return {}
    t0 = time.time()
    deadline = t0 + float(config.PACKS_FIRST_SECONDS if seconds is None else seconds)
    yt_only = media.youtube_only()
    used = gapfill.Used()

    def best(job: dict, n: int) -> List[Hit]:
        return find(line_texts(job), niches_for(job), used, index=job["index"], at=job.get("start"),
                    seconds=float(job.get("seconds") or 6.0) + media.SEQ_SHOT_PAD, n=n,
                    min_similarity=config.PACKS_FIRST_MIN_SIMILARITY, require_cc=require_cc)

    scored = []
    for job in sorted(jobs, key=lambda j: j["index"]):
        if job.get("hook") or is_specific(job) or not eligible(job, yt_only):
            continue
        hits = best(job, 1)
        if hits:
            scored.append((hits[0].similarity, job["index"], job))
    scored.sort(key=lambda t: -t[0])
    cap = int(len(jobs) * max(0.0, config.PACKS_FIRST_MAX_SHARE))
    chosen = []
    for _sim, i, job in scored:
        if len(chosen) >= cap:
            break
        for hit in best(job, 3):
            shot = shot_of(hit.entry, job.get("start"))
            if used.claim(i, shot):
                chosen.append((i, job, hit, shot))
                break

    def get(item):
        _i, job, hit, _shot = item
        return None if time.time() > deadline else fetch(hit.entry, work, job, hit.similarity)

    out: Dict[int, Any] = {}
    if chosen:
        pool = ThreadPoolExecutor(max_workers=max(1, min(8, len(chosen))))
        try:
            for (i, _job, hit, shot), asset in zip(chosen, pool.map(get, chosen)):
                if asset is None:
                    used.release(i, shot)
                    continue
                if hit.entry.license_class in ("pd", "cc0"):
                    asset.review_required, asset.review_reason = False, ""      # clean licence, fit already judged
                out[i] = asset
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    if out:
        print(f"[packs] first pass: {len(out)} of {len(jobs)} line(s) taken from the packs in "
              f"{time.time() - t0:.0f}s (before any search)", flush=True)
    return out
