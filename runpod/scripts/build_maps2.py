"""
Builds the maps-v2 geography (2026-10-14) from Natural Earth (public domain, https://www.naturalearthdata.com;
remotion/src/data/maps2/LICENSE-natural-earth.txt):

  python scripts/build_maps2.py names
      remotion/src/data/maps2/ne_countries.json + ne_regions.json -> src/geodata/maps2_names.json, the planner's
      name index (src/mapsv2.py: "Texas" -> US-TX, "France" -> FRA). Run after the shapes change.

  python scripts/build_maps2.py all <dir with the unzipped Natural Earth downloads> <mapshaper binary>
      everything from the downloads (naciscdn.org/naturalearth: 50m/cultural/ne_50m_admin_0_countries,
      10m/cultural/ne_10m_admin_1_states_provinces, 10m/cultural/ne_10m_populated_places_simple,
      10m/raster/SR_HR): the two TopoJSON shapes (mapshaper 0.6.102), the cities, the relief tiles, the names.

Run downloaded files with `python -I`, the downloads in their own folder (they are data, never code).
"""
import csv
import json
import math
import os
import subprocess
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "remotion", "src", "data", "maps2")
RELIEF = os.path.join(ROOT, "remotion", "public", "maps2", "relief")
NAMES = os.path.join(ROOT, "src", "geodata", "maps2_names.json")

# What a narration calls a country beside its Natural Earth names.
COUNTRY_ALIASES = {
    "USA": ["united states", "united states of america", "america", "the us", "the u.s.", "usa", "u.s.a."],
    "GBR": ["united kingdom", "uk", "the uk", "britain", "great britain"],
    "RUS": ["russia", "russian federation"], "CHN": ["china", "mainland china", "prc"], "KOR": ["south korea", "korea"],
    "PRK": ["north korea"], "IRN": ["iran"], "SYR": ["syria"], "VNM": ["vietnam", "viet nam"], "LAO": ["laos"],
    "CZE": ["czech republic", "czechia"], "COD": ["democratic republic of the congo", "dr congo", "drc", "congo-kinshasa"],
    "COG": ["republic of the congo", "congo-brazzaville"], "CIV": ["ivory coast", "cote d'ivoire"], "MMR": ["myanmar", "burma"],
    "TWN": ["taiwan"], "ARE": ["united arab emirates", "uae", "the emirates"], "NLD": ["netherlands", "holland", "the netherlands"],
    "PSE": ["palestine"], "VAT": ["vatican", "vatican city"], "BOL": ["bolivia"], "VEN": ["venezuela"], "TZA": ["tanzania"],
    "MKD": ["north macedonia", "macedonia"], "SWZ": ["eswatini", "swaziland"], "CPV": ["cape verde"], "TLS": ["east timor", "timor-leste"],
}
# Region names that are ordinary words, or a country's too: never matched as a region by name alone.
REGION_STOP = {"central", "north", "south", "east", "west", "northern", "southern", "eastern", "western", "capital", "centre",
               "center", "georgia", "national capital", "federal", "coast", "interior", "highland", "highlands", "lakes",
               "upper", "lower", "middle", "mountain", "islands", "island", "city", "border", "valley", "delta", "plateau",
               "river", "atlantic", "pacific", "midlands", "north east", "south east", "north west", "south west"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() or c in "'." else " " for c in s).split())


def props(topo_path: str, key: str):
    with open(topo_path, encoding="utf-8") as fh:
        topo = json.load(fh)
    return [g.get("properties") or {} for g in topo["objects"][key]["geometries"]]


def build_names() -> dict:
    countries = {}
    iso2 = {}
    for p in props(os.path.join(DATA, "ne_countries.json"), "countries"):
        a3 = p.get("a") or ""
        if not a3 or a3 == "ATA":
            continue
        for n in (p.get("n"), p.get("l")):
            if n:
                countries.setdefault(norm(n), a3)
        if p.get("i") and p["i"] != "-99":
            iso2[p["i"].lower()] = a3
    for a3, names in COUNTRY_ALIASES.items():
        for n in names:
            countries[norm(n)] = a3
    regions = {}
    for p in props(os.path.join(DATA, "ne_regions.json"), "regions"):
        a3 = p.get("a") or ""
        name = p.get("n") or p.get("e") or ""
        code = p.get("c") or ""
        rid = code if code and code != "-99" else f"{a3}:{name}"
        for n in {norm(p.get("n")), norm(p.get("e"))}:
            if not n or len(n) < 4 or n in REGION_STOP or n in countries:
                continue
            regions.setdefault(n, [])
            if [rid, a3] not in regions[n]:
                regions[n].append([rid, a3, str(p.get("t") or "")])
    out = {"_about": "Natural Earth names (public domain) for src/mapsv2.py; built by scripts/build_maps2.py names.",
           "countries": dict(sorted(countries.items())), "regions": dict(sorted(regions.items())), "iso2": dict(sorted(iso2.items()))}
    with open(NAMES, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=True, separators=(",", ":"), sort_keys=False)
    print(f"names: {len(countries)} country names, {len(regions)} region names -> {NAMES}")
    return out


def build_cities(src_dir: str, mapshaper: str) -> None:
    shp = os.path.join(src_dir, "ne_10m_populated_places_simple", "ne_10m_populated_places_simple.shp")
    tmp = os.path.join(src_dir, "places.csv")
    subprocess.run([mapshaper, shp, "-o", tmp, "format=csv"], check=True)
    keep = []
    with open(tmp, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sr = int(float(r["scalerank"] or 10))
            pop = float(r["pop_max"] or 0)
            cap = r["adm0cap"] in ("1", "1.0")
            if sr <= 5 or pop >= 400000 or cap:
                keep.append([r["nameascii"] or r["name"], round(float(r["latitude"]), 3), round(float(r["longitude"]), 3),
                             r["adm0_a3"], sr, int(pop), 1 if cap else 0])
    keep.sort(key=lambda x: -x[5])
    with open(os.path.join(DATA, "ne_cities.json"), "w", encoding="utf-8") as fh:
        json.dump({"fields": ["name", "lat", "lon", "adm0", "rank", "pop", "capital"], "rows": keep}, fh, separators=(",", ":"))
    print(f"cities: {len(keep)}")


def build_shapes(src_dir: str, mapshaper: str) -> None:
    subprocess.run([mapshaper, os.path.join(src_dir, "ne_50m_admin_0_countries", "ne_50m_admin_0_countries.shp"),
                    "-filter-fields", "ADM0_A3,NAME,NAME_LONG,ISO_A2,CONTINENT", "-rename-fields",
                    "a=ADM0_A3,n=NAME,l=NAME_LONG,i=ISO_A2,k=CONTINENT", "-simplify", "35%", "keep-shapes", "-rename-layers",
                    "countries", "-o", os.path.join(DATA, "ne_countries.json"), "format=topojson", "quantization=60000"], check=True)
    subprocess.run([mapshaper, os.path.join(src_dir, "ne_10m_admin_1_states_provinces", "ne_10m_admin_1_states_provinces.shp"),
                    "-filter-fields", "name,adm0_a3,iso_3166_2,type_en,name_en", "-rename-fields",
                    "n=name,a=adm0_a3,c=iso_3166_2,t=type_en,e=name_en", "-simplify", "6%", "weighting=0.7", "keep-shapes",
                    "-rename-layers", "regions", "-o", os.path.join(DATA, "ne_regions.json"), "format=topojson",
                    "quantization=80000"], check=True)


def build_relief(tif: str, zmax: int = 5) -> None:
    """SR_HR -> Web-Mercator grey tiles (128 = flat); flat tiles and south of 60 S left out; the manifest beside."""
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    T, FLAT, GAIN = 256, 206.0, 1.7
    src = Image.open(tif)
    W = T * 2 ** zmax
    a = np.asarray(src.resize((W, src.size[1]), Image.LANCZOS), dtype=np.float32)
    hs = a.shape[0]
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (np.arange(W) + 0.5) / W))))
    sy = (90.0 - lat) / 180.0 * hs - 0.5
    y0 = np.clip(np.floor(sy).astype(int), 0, hs - 1)
    y1 = np.clip(y0 + 1, 0, hs - 1)
    t = (sy - y0)[:, None]
    img = np.clip(128.0 + ((a[y0] * (1 - t) + a[y1] * t) - FLAT) * GAIN, 0, 255)
    del a
    manifest = {}
    for z in range(zmax, -1, -1):
        n = 2 ** z
        bits = 0
        os.makedirs(os.path.join(RELIEF, str(z)), exist_ok=True)
        for ty in range(n):
            north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
            for tx in range(n):
                tile = img[ty * T:(ty + 1) * T, tx * T:(tx + 1) * T]
                if north < -60 or np.abs(tile - 128).max() < 6:
                    continue
                bits |= 1 << (tx + ty * n)
                Image.fromarray(tile.round().astype(np.uint8), "L").save(os.path.join(RELIEF, str(z), f"{tx}_{ty}.jpg"),
                                                                         quality=72, optimize=True)
        manifest[str(z)] = format(bits, "x")
        if z:
            h = img.shape[0] // 2
            img = img.reshape(h, 2, h, 2).mean(axis=(1, 3))
    with open(os.path.join(DATA, "relief_manifest.json"), "w") as fh:
        json.dump({"tile": T, "maxZoom": zmax, "flat": 128, "z": manifest}, fh)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "names"
    if what == "all":
        src, ms = sys.argv[2], sys.argv[3]
        build_shapes(src, ms)
        build_cities(src, ms)
        build_relief(os.path.join(src, "SR_HR", "SR_HR.tif"))
    build_names()
