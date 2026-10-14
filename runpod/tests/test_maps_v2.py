"""
Maps v2 (2026-10-14): twelve branded relief-map looks (remotion/src/components/lib/LibMaps2.tsx, components/maps2;
scripts/library_looks_maps2.json) on bundled Natural Earth geography, planned by src/mapsv2.py from the plan's own
map looks and their lines - for every niche (history, travel, business, news, geography, true crime, science).

  - the data is bundled, small and public domain (the licence file names every source);
  - registered (family "maps2", template ids M2_*), drawn by the renderer, listed in the index, brand kits equal
    to the Smart Editor's ids;
  - the names: countries by any of their names, states / provinces only when they cannot be a word or another place;
  - the upgrade: each line picks the look that shows what it says, places stay the gazetteer's, each part lands on
    its own word (never before it), the first map of a video dives from the globe; MAPS_V2 off keeps the old maps.
Offline: no network, no paid calls.
"""
import json
import os
import re
import unittest

from src import config, datalooks as dl, mapsv2, templates, treatments

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
DATA = os.path.join(REMOTION, "src", "data", "maps2")
LIB = os.path.join(REMOTION, "src", "components", "lib")
FPS = 30

KYOTO = {"label": "Kyoto, Japan", "lat": 35.0116, "lon": 135.7681}
LISBON = {"label": "Lisbon, Portugal", "lat": 38.7223, "lon": -9.1393}
MADRID = {"label": "Madrid, Spain", "lat": 40.4168, "lon": -3.7038}
PARIS = {"label": "Paris, France", "lat": 48.8566, "lon": 2.3522}
SHANGHAI = {"label": "Shanghai, China", "lat": 31.2304, "lon": 121.4737}
LA = {"label": "Los Angeles, California", "lat": 34.0522, "lon": -118.2437}
ROTTERDAM = {"label": "Rotterdam, Netherlands", "lat": 51.9244, "lon": 4.4777}
CHERNOBYL = {"label": "Chernobyl, Ukraine", "lat": 51.2763, "lon": 30.2219}
CUSCO = {"label": "Cusco, Peru", "lat": -13.532, "lon": -71.967}
AUSTIN = {"label": "Austin, Texas", "lat": 30.2672, "lon": -97.7431}
BERLIN = {"label": "Berlin, Germany", "lat": 52.52, "lon": 13.405}


def words_for(line, t=1.0, per_word=0.32):
    out = []
    for tok in line.split(" "):
        if tok:
            out.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.02, 3)})
            t += per_word
    return out


def doc_for(line, maps):
    words = words_for(line)
    total = int((words[-1]["end"] + 12.0) * FPS)
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": total, "overlays": list(maps), "sfx": [],
            "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": total, "text": "", "words": words,
                        "media": {"type": "video", "url": "https://x/0.mp4"}}]}


def old_map(places, at=1.0, tid="MAP_LOCATION_ZOOM_V1"):
    return {"type": "map", "template": tid, "variant": "satellite", "startFrame": int(at * FPS), "durationInFrames": 150,
            "text": "", "locations": [dict(p) for p in places]}


def upgraded(line, places, state=None, at=0.0):
    words = words_for(line, 0.0)
    nar = dl.Narration(words)
    return mapsv2.upgrade(old_map(places, at), nar.text, nar.time_at, at, state or mapsv2.State())


class Data(unittest.TestCase):
    def test_bundled_small_and_public_domain(self):
        with open(os.path.join(DATA, "LICENSE-natural-earth.txt"), encoding="utf-8") as fh:
            lic = fh.read()
        self.assertIn("public domain", lic)
        for f in ("ne_countries.json", "ne_regions.json", "ne_cities.json", "relief_manifest.json"):
            self.assertIn(f, lic)
        size = sum(os.path.getsize(os.path.join(DATA, f)) for f in os.listdir(DATA) if f.endswith(".json"))
        self.assertLess(size, 2_600_000)

    def test_every_relief_tile_the_manifest_names_is_there(self):
        with open(os.path.join(DATA, "relief_manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh)
        base = os.path.join(REMOTION, "public", "maps2", "relief")
        total = 0
        for z, bits in man["z"].items():
            n = 2 ** int(z)
            v = int(bits, 16)
            want = {f"{i % n}_{i // n}.jpg" for i in range(n * n) if v >> i & 1}
            self.assertEqual(want, set(os.listdir(os.path.join(base, z))), z)
            total += sum(os.path.getsize(os.path.join(base, z, f)) for f in want)
        self.assertLess(total, 6_000_000)


class Registered(unittest.TestCase):
    def test_twelve_looks_the_planner_may_pick_drawn_and_listed(self):
        with open(os.path.join(LIB, "LibMaps2.tsx"), encoding="utf-8") as fh:
            src = fh.read()
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        drawn = set(re.findall(r'"(m2-[a-z-]+)": guard\(', src[src.index("export const LOOKS"):]))
        self.assertEqual(drawn, {mapsv2.variant_of(t) for t in mapsv2.IDS})
        for tid in mapsv2.IDS:
            t = templates.get(tid)
            self.assertTrue(t, tid)
            self.assertTrue(treatments.auto_ok(tid), tid)
            self.assertEqual(t["defaults"]["variant"], mapsv2.variant_of(tid))
            self.assertIn(f'"{mapsv2.variant_of(tid)}"', index)
            self.assertTrue(t["defaults"]["sounds"], tid)
            self.assertIsInstance(t["defaults"].get("sample"), dict, tid)
        self.assertEqual(templates.check(), [])

    def test_no_picture_through_remotion_img_and_the_brand_kits_are_the_smart_editors(self):
        with open(os.path.join(REMOTION, "src", "components", "maps2", "kit.ts"), encoding="utf-8") as fh:
            kit = fh.read()
        self.assertEqual(set(re.findall(r"^  (\w+): \{ bg:", kit, re.M)), set(mapsv2.KITS))
        for name in ("MapCanvas.tsx", "parts.tsx", "../lib/LibMaps2.tsx"):
            with open(os.path.join(REMOTION, "src", "components", "maps2", name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotRegex(src, r"<Img[\s/]")
            self.assertNotRegex(src, r"import\s*\{[^}]*\bImg\b[^}]*\}\s*from\s*\"remotion\"")


class Names(unittest.TestCase):
    def test_countries_and_states_by_name_never_a_plain_word(self):
        got = mapsv2.areas_named("Texas is bigger than France, and Bavaria is a state of Germany.")
        self.assertEqual([a["id"] for a in got], ["US-TX", "FRA", "DE-BY", "DEU"])
        self.assertEqual(mapsv2.areas_named("He drove to the central valley and the north coast."), [])
        self.assertEqual([a["id"] for a in mapsv2.areas_named("The war in Georgia began in 2008.")], ["GEO"])
        self.assertEqual([a["id"] for a in mapsv2.areas_named("Kerala in India has the highest literacy.")], ["IN-KL", "IND"])
        self.assertEqual([a["id"] for a in mapsv2.areas_named("New South Wales is in Australia.")], ["AU-NSW", "AUS"])


class Upgrade(unittest.TestCase):
    def test_each_niche_gets_the_look_that_shows_what_it_says(self):
        cases = [
            ("Texas is bigger than France and still growing.", [AUSTIN], mapsv2.COMPARE),
            ("Brazil grows 3.2 million tonnes, Vietnam 1.9 million and Colombia 0.7 million every year.", [], None),
            ("Everyone within 30 kilometres of Chernobyl was evacuated in 1986.", [CHERNOBYL], mapsv2.RADIUS),
            ("Factories in Shanghai export to Los Angeles and Rotterdam every week.", [SHANGHAI, LA, ROTTERDAM], mapsv2.FLOWS),
            ("The night train runs from Lisbon to Madrid and on to Paris.", [LISBON, MADRID, PARIS], mapsv2.ROUTE),
            ("The company built plants in Austin, Berlin and Shanghai.", [AUSTIN, BERLIN, SHANGHAI], mapsv2.PLACES),
            ("The Inca capital Cusco sits high in the Andes mountains of Peru.", [CUSCO], mapsv2.RELIEF_TILT),
        ]
        for line, places, want in cases:
            got = upgraded(line, places or [AUSTIN])
            if want is None:
                continue
            self.assertIsNotNone(got, line)
            self.assertEqual(got["template"], want, line)
            self.assertEqual(got["variant"], mapsv2.variant_of(want))

    def test_figures_by_area_make_a_choropleth_with_the_said_values(self):
        line = "Brazil grows 3.2 million tonnes, Vietnam 1.9 million, Colombia 0.7 million and Ethiopia 0.5 million."
        got = upgraded(line, [{"label": "Brazil", "lat": -10.0, "lon": -52.0}])
        self.assertEqual(got["template"], mapsv2.CHOROPLETH)
        self.assertEqual([(a["id"], a["value"]) for a in got["areas"]], [("BRA", 3.2), ("VNM", 1.9), ("COL", 0.7), ("ETH", 0.5)])

    def test_the_first_map_dives_from_the_globe_and_single_places_turn(self):
        st = mapsv2.State()
        first = upgraded("Kyoto was the imperial capital of Japan for a thousand years.", [KYOTO], st)
        self.assertEqual(first["template"], mapsv2.ZOOM_DIVE)
        picks = [upgraded("Then the court moved to Kyoto.", [KYOTO], st)["template"] for _ in range(4)]
        self.assertGreaterEqual(len(set(picks)), 2, picks)
        self.assertNotEqual(picks[0], mapsv2.ZOOM_DIVE)

    def test_each_part_lands_on_its_word_never_before(self):
        line = "The night train runs from Lisbon to Madrid and on to Paris."
        words = words_for(line, 4.0)
        doc = doc_for(line, [old_map([LISBON, MADRID, PARIS], at=4.0, tid="MAP_ROUTE_SAT_V1")])
        doc["scenes"][0]["words"] = words
        with templates.only(set(mapsv2.IDS)):           # (looks pack 3's route would take it first)
            rep = dl.finish(doc)
        got = [o for o in doc["overlays"] if str(o.get("template", "")).startswith("M2_")]
        self.assertEqual(len(got), 1, rep.get("upgraded"))
        o = got[0]
        self.assertTrue(all(not k.startswith("_") for k in o))
        start = o["startFrame"] / FPS
        for it in o["items"][1:]:
            said = next(w["start"] for w in words if w["text"].strip(",.") == it["label"])
            self.assertAlmostEqual(start + it["at"], said, delta=0.15)
        self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS))

    def test_switched_off_the_old_maps_stay(self):
        line = "Kyoto was the imperial capital of Japan for a thousand years."
        before = config.MAPS_V2
        try:
            config.MAPS_V2 = False
            doc = doc_for(line, [old_map([KYOTO])])
            dl.finish(doc)
            self.assertFalse(any(str(o.get("template", "")).startswith("M2_") for o in doc["overlays"]))
            config.MAPS_V2 = True
            doc = doc_for(line, [old_map([KYOTO])])
            dl.finish(doc)
            self.assertTrue(any(str(o.get("template", "")).startswith("M2_") for o in doc["overlays"]))
        finally:
            config.MAPS_V2 = before

    def test_the_brand_kit_rides_on_the_look(self):
        self.assertEqual(mapsv2.kit_of({"meta": {"smart_kit": "atlas"}}), "atlas")
        self.assertEqual(mapsv2.kit_of({"brand": {"kit": {"id": "noir"}}}), "noir")
        self.assertEqual(mapsv2.kit_of({"meta": {"video_style": "news"}}), "bulletin")
        self.assertEqual(mapsv2.kit_of({}), "")


if __name__ == "__main__":
    unittest.main()
