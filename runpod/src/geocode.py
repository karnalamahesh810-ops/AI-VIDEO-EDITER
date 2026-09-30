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


def lookup(name: str, timeout: int = 20) -> Optional[Place]:
    """Resolve one place name. Returns None when nothing matches a real place — never a guess."""
    key = (name or "").strip().lower()
    if not key:
        return None
    with _lock:
        if key in _cache:
            return _cache[key]

    place: Optional[Place] = None
    try:
        with _lock:
            wait = _RATE_LIMIT_SECONDS - (time.monotonic() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.monotonic()
        r = requests.get(
            NOMINATIM,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en"},
            params={"q": name, "format": "jsonv2", "limit": _CANDIDATES},
            timeout=timeout,
        )
        r.raise_for_status()
        hits = r.json()
        hit = next((h for h in (hits or []) if isinstance(h, dict) and is_place(h)), None)
        if hits and hit is None:
            print(f"[geocode] '{name}' is not a place ({(hits[0] or {}).get('category') or (hits[0] or {}).get('class')}"
                  f"/{(hits[0] or {}).get('type')}); no map", flush=True)
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
                )
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"[geocode] '{name}' lookup failed: {e}", flush=True)

    with _lock:
        _cache[key] = place
    return place


def resolve_all(names: List[str]) -> List[dict]:
    """
    Resolve several place names, dropping the ones that don't exist.

    Serial on purpose: Nominatim's one-request-per-second policy makes a thread
    pool pointless here, and a documentary rarely names more than a handful of
    distinct places.
    """
    out, seen = [], set()
    for name in names:
        place = lookup(name)
        if place and (place.lat, place.lon) not in seen:
            seen.add((place.lat, place.lon))
            out.append(place.dict())
    return out


def reset_cache():
    with _lock:
        _cache.clear()
