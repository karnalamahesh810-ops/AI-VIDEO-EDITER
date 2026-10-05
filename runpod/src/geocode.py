"""
Place name -> coordinates, from a real gazetteer.

Map overlays are the one template where a wrong value is worse than no
template at all: a map confidently pointing at the wrong continent reads as a
factual claim. The VidRush reference renders actually ship this bug — one map's
city field says "Santa Marta" while its own caption reads "EPICENTER: SAN JOSE
DEL PALMAR", 700km apart.

So coordinates never come from the language model. The director may only name a
place; this module resolves that name against OpenStreetMap's Nominatim, and a
name only counts as a place when the gazetteer files it as one (a boundary, a
settlement, a natural feature, a waterway or a road - PLACE_CLASSES). A paint
store, an office or a restaurant that happens to match the name is not a place
to map (the owner's Texas flood video got "Sherwin-Williams, United States" on
a satellite map). If the lookup fails the map is dropped and the scene keeps
its footage.

The label drawn is the place as the story says it ("North Texas", "El Paso"),
never the gazetteer's first display part, which for a business is its brand.

Nominatim's usage policy requires an identifying User-Agent and at most one
request per second, both honoured here.
"""
from dataclasses import dataclass
import math
import re
from typing import Dict, List, Optional
import threading
import time
import requests

from . import config

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim result classes ("category" in jsonv2, "class" in json) that are places.
PLACE_CLASSES = {"boundary", "place", "natural", "waterway", "highway"}
# Hits looked at per name: the first one that is a place wins.
_CANDIDATES = 5
# A country the label need not repeat ("El Paso, Texas, USA" -> "El Paso, Texas").
_COUNTRY_TAIL = re.compile(r",\s*(?:united states(?: of america)?|u\.?s\.?a?\.?)\s*$", re.I)

_cache: Dict[str, Optional["Place"]] = {}
_lock = threading.Lock()
_last_call = [0.0]
_RATE_LIMIT_SECONDS = 1.1


@dataclass
class Place:
    label: str          # the gazetteer's name, NOT the requested string
    lat: float
    lon: float
    kind: str = ""      # city / mountain / river ... as classified upstream
    country: str = ""   # its country code ("us"), for the sanity checks; never drawn

    def dict(self) -> dict:
        return {"label": self.label, "lat": self.lat, "lon": self.lon, "kind": self.kind}


def _short_label(display_name: str, fallback: str) -> str:
    """
    "San José del Palmar, Chocó, 27600, Colombia" -> "San José del Palmar, Colombia".

    Nominatim display names run to six or seven comma-separated parts, which is
    unreadable at title size. Place plus country carries the meaning.
    """
    parts = [p.strip() for p in (display_name or "").split(",") if p.strip()]
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}, {parts[-1]}"


def is_place(hit: dict) -> bool:
    """A Nominatim hit filed as a place (PLACE_CLASSES), not a shop, office, amenity or company."""
    return str(hit.get("category") or hit.get("class") or "").lower() in PLACE_CLASSES


def spoken_label(name: str) -> str:
    """The place as the story names it, tidied: 'El Paso, Texas, USA' -> 'El Paso, Texas'."""
    label = re.sub(r"\s+", " ", (name or "").strip()).strip(" ,.")
    return _COUNTRY_TAIL.sub("", label).strip(" ,.") or label


# --------------------------------------------------------------------------- #
# The story's region, a built-in gazetteer and sanity checks (the owner,
# 2026-10-05: at 8:18 of his Las Vegas video "Lake Mead to Lake Powell" drew
# a route from Australia - the gazetteer's 2nd hit for "Lake Powell" is a
# Lake Powell in Victoria, AU, and "Lake Mead" came back as a canal in Dubai).
# --------------------------------------------------------------------------- #
# Well-known places the stories name again and again, as facts: the lookup never asks for these.
# name -> (label, lat, lon, kind, country)
GAZETTEER: Dict[str, tuple] = {
    "lake mead": ("Lake Mead", 36.25, -114.39, "reservoir", "us"),
    "lake powell": ("Lake Powell", 37.07, -111.24, "reservoir", "us"),
    "lake mohave": ("Lake Mohave", 35.45, -114.65, "reservoir", "us"),
    "lake havasu": ("Lake Havasu", 34.46, -114.37, "reservoir", "us"),
    "lake havasu city": ("Lake Havasu City", 34.4839, -114.3225, "city", "us"),
    "lake tahoe": ("Lake Tahoe", 39.09, -120.04, "lake", "us"),
    "great salt lake": ("Great Salt Lake", 41.1, -112.5, "lake", "us"),
    "salton sea": ("Salton Sea", 33.3, -115.8, "lake", "us"),
    "lake oroville": ("Lake Oroville", 39.6, -121.4, "reservoir", "us"),
    "shasta lake": ("Shasta Lake", 40.78, -122.33, "reservoir", "us"),
    "lake shasta": ("Shasta Lake", 40.78, -122.33, "reservoir", "us"),
    "lake lanier": ("Lake Lanier", 34.2, -83.95, "reservoir", "us"),
    "lake okeechobee": ("Lake Okeechobee", 26.95, -80.8, "lake", "us"),
    "lake michigan": ("Lake Michigan", 44.0, -87.0, "lake", "us"),
    "lake superior": ("Lake Superior", 47.7, -87.5, "lake", "us"),
    "lake erie": ("Lake Erie", 42.2, -81.2, "lake", "us"),
    "grand canyon": ("Grand Canyon", 36.1069, -112.1129, "canyon", "us"),
    "glen canyon": ("Glen Canyon", 37.0, -111.5, "canyon", "us"),
    "lees ferry": ("Lees Ferry", 36.865, -111.588, "place", "us"),
    "hite": ("Hite", 37.88, -110.39, "place", "us"),
    "imperial valley": ("Imperial Valley", 32.85, -115.57, "valley", "us"),
    "central valley": ("Central Valley", 36.75, -119.8, "valley", "us"),
    "central arizona": ("Central Arizona", 33.3, -111.8, "region", "us"),
    "southern nevada": ("Southern Nevada", 36.1, -115.1, "region", "us"),
    "southern california": ("Southern California", 34.05, -118.0, "region", "us"),
    "las vegas": ("Las Vegas", 36.1699, -115.1398, "city", "us"),
    "las vegas strip": ("Las Vegas Strip", 36.1147, -115.1728, "place", "us"),
    "henderson": ("Henderson", 36.0395, -114.9817, "city", "us"),
    "boulder city": ("Boulder City", 35.9786, -114.8325, "city", "us"),
    "phoenix": ("Phoenix", 33.4484, -112.074, "city", "us"),
    "tucson": ("Tucson", 32.2226, -110.9747, "city", "us"),
    "yuma": ("Yuma", 32.6927, -114.6277, "city", "us"),
    "flagstaff": ("Flagstaff", 35.1983, -111.6513, "city", "us"),
    "page": ("Page", 36.9147, -111.4558, "city", "us"),
    "scottsdale": ("Scottsdale", 33.4942, -111.9261, "city", "us"),
    "mesa": ("Mesa", 33.4152, -111.8315, "city", "us"),
    "los angeles": ("Los Angeles", 34.0522, -118.2437, "city", "us"),
    "san diego": ("San Diego", 32.7157, -117.1611, "city", "us"),
    "san francisco": ("San Francisco", 37.7749, -122.4194, "city", "us"),
    "sacramento": ("Sacramento", 38.5816, -121.4944, "city", "us"),
    "denver": ("Denver", 39.7392, -104.9903, "city", "us"),
    "salt lake city": ("Salt Lake City", 40.7608, -111.891, "city", "us"),
    "albuquerque": ("Albuquerque", 35.0844, -106.6504, "city", "us"),
    "el paso": ("El Paso", 31.7619, -106.485, "city", "us"),
    "houston": ("Houston", 29.7604, -95.3698, "city", "us"),
    "dallas": ("Dallas", 32.7767, -96.797, "city", "us"),
    "austin": ("Austin", 30.2672, -97.7431, "city", "us"),
    "san antonio": ("San Antonio", 29.4241, -98.4936, "city", "us"),
    "new orleans": ("New Orleans", 29.9511, -90.0715, "city", "us"),
    "miami": ("Miami", 25.7617, -80.1918, "city", "us"),
    "atlanta": ("Atlanta", 33.749, -84.388, "city", "us"),
    "new york city": ("New York City", 40.7128, -74.006, "city", "us"),
    "chicago": ("Chicago", 41.8781, -87.6298, "city", "us"),
    "seattle": ("Seattle", 47.6062, -122.3321, "city", "us"),
    "arizona": ("Arizona", 34.2, -111.7, "state", "us"),
    "nevada": ("Nevada", 39.3, -116.6, "state", "us"),
    "california": ("California", 37.2, -119.5, "state", "us"),
    "utah": ("Utah", 39.3, -111.7, "state", "us"),
    "colorado": ("Colorado", 39.0, -105.5, "state", "us"),
    "new mexico": ("New Mexico", 34.4, -106.1, "state", "us"),
    "wyoming": ("Wyoming", 43.0, -107.5, "state", "us"),
    "texas": ("Texas", 31.0, -99.3, "state", "us"),
}
_US_STATES = sorted({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida",
    "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska",
    "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming"}, key=len, reverse=True)
# Countries a story may name, as Nominatim's country codes.
COUNTRIES = {
    "united states": "us", "america": "us", "u.s.": "us", "usa": "us", "american": "us",
    "australia": "au", "australian": "au", "canada": "ca", "canadian": "ca", "mexico": "mx", "mexican": "mx",
    "united kingdom": "gb", "britain": "gb", "england": "gb", "scotland": "gb", "wales": "gb", "ireland": "ie",
    "india": "in", "china": "cn", "japan": "jp", "germany": "de", "france": "fr", "italy": "it", "spain": "es",
    "brazil": "br", "argentina": "ar", "chile": "cl", "peru": "pe", "colombia": "co", "egypt": "eg",
    "ethiopia": "et", "south africa": "za", "nigeria": "ng", "kenya": "ke", "new zealand": "nz",
    "pakistan": "pk", "bangladesh": "bd", "indonesia": "id", "philippines": "ph", "vietnam": "vn",
    "turkey": "tr", "iran": "ir", "iraq": "iq", "israel": "il", "ukraine": "ua", "russia": "ru",
    "united arab emirates": "ae", "dubai": "ae", "saudi arabia": "sa",
}
_COUNTRY_RX = re.compile(r"(?<![\w.])(" + "|".join(re.escape(k) for k in sorted(COUNTRIES, key=len, reverse=True))
                         + r")(?![\w])", re.I)
_STATE_RX = re.compile(r"\b(" + "|".join(re.escape(k) for k in _US_STATES) + r")\b", re.I)
MAX_PATH_KM = 1000.0        # two points of one map look farther apart than this are not one story's path ...
_FAR_SAID = re.compile(r"\b(\d[\d,]{3,})\s*(?:miles|kilometers|kilometres|km)\b", re.I)   # ... unless it says so


def countries_named(text: str) -> List[str]:
    """The country codes a text names ('Lake Powell, Victoria, Australia' -> ['au'])."""
    found: List[str] = []
    for m in _COUNTRY_RX.finditer(text or ""):
        code = COUNTRIES[m.group(1).lower()]
        if code not in found:
            found.append(code)
    return found


def story_region(text: str = "", brief: Optional[dict] = None) -> str:
    """
    The country the story is set in, as a Nominatim country code ('' when it cannot be told): the
    country it names most, counting US states and the gazetteer's US places for 'us'.
    """
    parts = [text or ""]
    if isinstance(brief, dict):
        for k in ("places", "event", "title", "topic", "country", "region"):
            v = brief.get(k)
            parts.append(" ".join(map(str, v)) if isinstance(v, list) else str(v or ""))
    blob = " ".join(parts)
    counts: Dict[str, int] = {}
    for m in _COUNTRY_RX.finditer(blob):
        code = COUNTRIES[m.group(1).lower()]
        counts[code] = counts.get(code, 0) + 1
    us = len(_STATE_RX.findall(blob)) + sum(
        1 for k, rec in GAZETTEER.items() if rec[4] == "us" and rec[3] != "state"
        and re.search(r"\b" + re.escape(k) + r"\b", blob, re.I))
    if us:
        counts["us"] = counts.get("us", 0) + us
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def hav_km(a: "Place", b: "Place") -> float:
    """Great-circle distance between two places, km."""
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _gazetteer(name: str, region: str = "") -> Optional[Place]:
    """A well-known place from the built-in gazetteer (or the bundled dams), when the region allows it."""
    key = re.sub(r"\s+", " ", (name or "").strip().lower()).strip(" ,.")
    key = re.sub(r"^the\s+", "", key)
    key = _COUNTRY_TAIL.sub("", key).strip(" ,.")
    rec = GAZETTEER.get(key)
    if rec is None:
        # "Las Vegas, Nevada" / "Phoenix, Arizona": the place before its state
        head, _, tail = key.partition(",")
        if tail and tail.strip() in _US_STATES:
            rec = GAZETTEER.get(head.strip())
    if rec is None:
        try:
            from . import automaps
            n = automaps.norm(key)
            dam = next((d for d in automaps.data().dams
                        if n == automaps.norm(d.get("name") or "")
                        or n in [automaps.norm(x) for x in (d.get("aliases") or [])]), None)
        except Exception:  # noqa: BLE001 - the bundled data is a convenience
            dam = None
        if dam and dam.get("lat") is not None and dam.get("lon") is not None:
            lat, lon = float(dam["lat"]), float(dam["lon"])
            us = 15 < lat < 72 and -170 < lon < -60 and not (lat < 32.5 and lon > -117 and lon < -97 and lat < 26)
            rec = (dam["name"], lat, lon, "dam", "us" if us else "")
    if rec is None:
        return None
    label, lat, lon, kind, country = rec
    if region and country and country != region:
        return None
    return Place(label=spoken_label(name) or label, lat=lat, lon=lon, kind=kind, country=country)


def lookup(name: str, timeout: int = 20, region: str = "") -> Optional[Place]:
    """
    Resolve one place name. Returns None when nothing matches a real place — never a guess. `region` (a
    country code, story_region) keeps the lookup inside the story's country: the built-in gazetteer first,
    then Nominatim restricted to that country; a hit from another country is never taken. A name that says
    its own country ("Perth, Australia") is looked up there.
    """
    key = (name or "").strip().lower()
    if not key:
        return None
    region = (region or "").lower()
    named = countries_named(name)
    if named:
        region = named[0]
    ckey = f"{key}|{region}"
    with _lock:
        if ckey in _cache:
            return _cache[ckey]
    place = _gazetteer(name, region)
    if place is not None:
        with _lock:
            _cache[ckey] = place
        return place
    try:
        with _lock:
            wait = _RATE_LIMIT_SECONDS - (time.monotonic() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.monotonic()
        params = {"q": name, "format": "jsonv2", "limit": _CANDIDATES, "addressdetails": 1}
        if region:
            params["countrycodes"] = region
        r = requests.get(
            NOMINATIM,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en"},
            params=params,
            timeout=timeout,
        )
        r.raise_for_status()
        hits = r.json()

        def country_of(h: dict) -> str:
            return str(((h.get("address") or {}).get("country_code")) or "").lower()

        hit = next((h for h in (hits or []) if isinstance(h, dict) and is_place(h)
                    and (not region or not country_of(h) or country_of(h) == region)), None)
        if hits and hit is None:
            first = hits[0] or {}
            print(f"[geocode] '{name}' is not a place in '{region or 'anywhere'}' "
                  f"({first.get('category') or first.get('class')}/{first.get('type')}, {country_of(first) or '?'})"
                  "; no map", flush=True)
        if hit:
            lat, lon = float(hit["lat"]), float(hit["lon"])
            # A gazetteer should never return these, but a bad proxy might, and
            # an out-of-range coordinate would fail validation far downstream.
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                place = Place(
                    label=spoken_label(name) or _short_label(hit.get("display_name", ""), name),
                    lat=round(lat, 5),
                    lon=round(lon, 5),
                    kind=hit.get("addresstype") or hit.get("type") or "",
                    country=country_of(hit),
                )
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"[geocode] '{name}' lookup failed: {e}", flush=True)

    with _lock:
        _cache[ckey] = place
    return place


def sane(places: List[Place], text: str = "", region: str = "") -> str:
    """'' when the points of one map look belong together, else why not (the look is then dropped)."""
    named = set(countries_named(text))
    for p in places:
        if region and p.country and p.country != region and p.country not in named:
            return f"{p.label} resolved to '{p.country}', outside the story's '{region}'"
    countries = {p.country for p in places if p.country}
    if len(countries) > 1 and not countries <= named:
        return f"the points sit in different countries ({', '.join(sorted(countries))})"
    far = max([float(m.group(1).replace(",", "")) * (1.609 if "mile" in m.group(0).lower() else 1.0)
               for m in _FAR_SAID.finditer(text or "")] + [0.0])
    limit = max(MAX_PATH_KM, far * 1.3)
    for i in range(len(places)):
        for j in range(i + 1, len(places)):
            d = hav_km(places[i], places[j])
            if d > limit:
                return f"{places[i].label} and {places[j].label} are {d:.0f} km apart (over {limit:.0f} km)"
    return ""


def resolve_all(names: List[str], text: str = "", brief: Optional[dict] = None, region: Optional[str] = None,
                why: Optional[list] = None) -> List[dict]:
    """
    Resolve the place names of one map look, dropping the ones that don't exist - and all of them when the
    points do not belong together (sane): every lookup is biased to the story's region (story_region of the
    line and the brief; `region` overrides it), retried once inside the country most points agree on when
    there is no region, and the look is dropped rather than drawn wrong (`why` gets the reason).

    Serial on purpose: Nominatim's one-request-per-second policy makes a thread
    pool pointless here, and a documentary rarely names more than a handful of
    distinct places.
    """
    if region is None:
        region = story_region(text, brief)
    places: List[Place] = []
    seen = set()
    for name in names:
        place = lookup(name, region=region)
        if place and (place.lat, place.lon) not in seen:
            seen.add((place.lat, place.lon))
            places.append(place)
    bad = sane(places, text, region)
    if bad and not region:
        votes: Dict[str, int] = {}
        for p in places:
            if p.country:
                votes[p.country] = votes.get(p.country, 0) + 1
        if votes:
            again = max(votes.items(), key=lambda kv: kv[1])[0]
            places = [q for q in (lookup(n, region=again) for n in names) if q]
            bad = sane(places, text, again)
    if bad:
        print(f"[geocode] map dropped: {bad}", flush=True)
        if why is not None:
            why.append(bad)
        return []
    return [p.dict() for p in places]


def reset_cache():
    with _lock:
        _cache.clear()
