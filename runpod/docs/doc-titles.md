# Documentary titles (2026-10-28)

New looks built for the owner after "our motion graphics are literally bad": act title cards, real maps, numbers,
a lower-third. A new type pairing, never the old ml- / pack looks. Module: `src/doctitles.py` (PIL reference
renderer, used for the Hoover Dam laptop video); a Remotion port is the next step for the app's renderer.

## Type and sizes (1080p)

| Element | Font | Size |
|---|---|---|
| Act label ("ACT 2") | Manrope 600, caps tracked +12 % (gold) | 30 px |
| Act title | Playfair Display SemiBold | 72 px (62 px over 34 characters) |
| Number | Manrope 700 | 96 px (72 px when long), never full-screen |
| Number caption | Manrope 500 | 28 px |
| Lower-third name / role | Manrope 700 / 600 caps tracked | 40 / 26 px |
| Quote line | Playfair Display 500 | 40 px |
| Map place label / state | Manrope 700 / 700 caps tracked | 30 / 24 px |

Fonts: `assets/doctitles/fonts` (OFL 1.1, licences beside them). Colour: white, one thin gold rule (#C9A227), soft
shadows, a faint dark glow behind lower-left text. No outlines, no boxes, no yellow. The same place every time:
numbers and names lower-left inside the title-safe area, act cards centred.

## Motion

350-400 ms ease-out cubic: slide-up 22 px + fade, the gold rule wipes in, a letter-spacing settle on act titles and
place names, a quick count-up only where it means something (a drop, a record). Out: 250-300 ms fade.
Act cards darken the shot ~42 % with a soft vignette for ~2.8 s from the spoken "Act N".

## Maps (real geography only)

- Land and relief: open DEM tiles (AWS Terrain Tiles, Terrarium encoding, SRTM-derived; `DEM_DIR`) shaded at the
  zoom that fits the view (z7-z9), else the Natural Earth z5 relief tiles in `assets/doctitles/geo/relief5`.
- States: Natural Earth 1:10m admin-1 (US, Mexico, Canada) `geo/ne_admin1_na.json` (from the maps-v2 extract).
- Lakes: OpenStreetMap outlines for Lake Mead, Powell, Mohave, Havasu (`geo/osm_lakes.json`, ODbL, simplified
  0.0004 deg), Natural Earth for every other lake; rivers from `src/geodata/rivers.json` (curated source to mouth).
- A slow push (4-6 %), the river stretch between two real points draws in, lakes and states highlight, labels
  land on their spoken words, labels stand in clear space with a thin leader (never over water, a line or a dot),
  a vignette draws the eye in.

## Attribution

Natural Earth (public domain); OpenStreetMap contributors (ODbL 1.0); terrain tiles: Mapzen / AWS Terrain Tiles
(SRTM, USGS NED and others, see https://github.com/tilezen/joerd/blob/master/docs/attribution.md).
