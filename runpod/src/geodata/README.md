# Bundled geodata for the auto maps

Committed files, read by `src/automaps.py`. The worker downloads nothing at run time.
Rebuild with `python scripts/build_geo.py [--cache DIR] [--offline]` (needs `requests` and the network once).

| File | What | Size |
| --- | --- | --- |
| `rivers.json` | 1,455 named rivers; 55 curated (source to mouth, so the draw runs with the water), the rest as Natural Earth draws them | ~0.63 MB |
| `lakes.json` | 1,714 named lakes and reservoirs, outer outlines | ~0.46 MB |
| `canals.json` | 5 hand-traced aqueducts (approximate) + 2 Natural Earth canals | ~2 KB |
| `dams.json` | 31 major dams, hand-kept | ~6 KB |

Lines are Google-polyline text at 1/1000 degree (about 110 m), simplified with Douglas-Peucker at 0.006 degrees
(about 600 m: under 1.5 px at the closest framing the looks use). `decode()` in `scripts/build_geo.py` and
`src/automaps.py` reads them.

## Sources and licences

* **Natural Earth 1:10m** `ne_10m_rivers_lake_centerlines`, `ne_10m_rivers_north_america`, `ne_10m_lakes`,
  `ne_10m_lakes_north_america`, release **v5.1.2** (nvkelso/natural-earth-vector, GeoJSON). **Public domain**
  (naturalearthdata.com/about/terms-of-use). SHA-256 of the files the build used:
  * rivers_lake_centerlines `bb854a900ecbd3b408df46d5e16e3e0f974ba55993f9d8b5c26e855273c0905a`
  * rivers_north_america `dcd2348655a5f3d0ea7be35024073ab24f09115d2e4efb77e7bc0a33567db682`
  * lakes `2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9`
  * lakes_north_america `76f49d4b698f3529e690136a989713bcd3c028ade150346f4b358de9815cfc43`
* **Dams**: coordinates are facts from public records (USGS GNIS, US Army Corps National Inventory of Dams,
  Wikipedia), typed in by hand; the reservoir and river each names are checked against the lines above.
* **Canals**: the Central Arizona Project, California Aqueduct, All-American Canal, Colorado River Aqueduct and
  Los Angeles Aqueduct are coarse traces through public landmarks (intakes, pumping plants, reservoirs, towns).
  They are marked `approx` and drawn dashed: the route, not the survey. (The USGS NHD web service, public domain,
  would give exact lines but timed out; swap it in `build_canals` if it answers.) Erie and Welland come from Natural Earth.

## Known limits

* Natural Earth draws some narrow canyon reservoirs partly (Lake Mohave, Grand Coulee's Lake Roosevelt, Flaming Gorge
  stop short of their dams); the planner then pins the dam and leaves the outline out.
* Natural Earth's own labels are followed: its "Columbia" lines include the Snake River; the curated Snake and Columbia
  are cut from them by source and mouth.
* Only rivers with a curated source and mouth carry `flow: true` (streaming dashes); the others are drawn without them.
