"""
Place name -> coordinates, from a real gazetteer.

Map overlays are the one template where a wrong value is worse than no
template at all: a map confidently pointing at the wrong continent reads as a
factual claim. The VidRush reference renders actually ship this bug — one map's
city field says "Santa Marta" while its own caption reads "EPICENTER: SAN JOSE
DEL PALMAR", 700km apart.

So coordinates never come from the language model. The director may only name a
place; this module resolves that name against OpenStreetMap's Nominatim and the
label we draw is the one the gazetteer returned, not the one that was asked
for. If the lookup fails the map is dropped and the scene keeps its footage.

Nominatim's usage policy requires an identifying User-Agent and at most one
request per second, both honoured here.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
import threading
import time
import requests

from . import config

NOMINATIM = "https://nominatim.openstreetmap.org/search"

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


def lookup(name: str, timeout: int = 20) -> Optional[Place]:
    """Resolve one place name. Returns None when nothing matches — never a guess."""
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
            params={"q": name, "format": "jsonv2", "limit": 1},
            timeout=timeout,
        )
        r.raise_for_status()
        hits = r.json()
        if hits:
            hit = hits[0]
            lat, lon = float(hit["lat"]), float(hit["lon"])
            # A gazetteer should never return these, but a bad proxy might, and
            # an out-of-range coordinate would fail validation far downstream.
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                place = Place(
                    label=_short_label(hit.get("display_name", ""), name),
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
