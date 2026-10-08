import React from "react";
import { AbsoluteFill } from "remotion";
import { GIBS_MAX, ImageryTile, TILE, TileFilters, USGS_MAX, usgsZoom } from "../motion/satelliteTiles";
import { geoAlbers, geoBounds, geoCentroid, geoContains, geoGraticule10, geoOrthographic, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import worldTopology from "world-atlas/countries-110m.json";
import statesTopology from "../../data/us-states.json";
import type { Overlay } from "../../types";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import {
  ANTON, MONO, SUBLINE, Grain, Vignette, backOut, caps, clamp01, easeInOut, easeOut, exitOf, expoOut, fit, guard, heavy,
  hotOf, inOf, lerp, lift, rgba, textWidth, useBase, useSvgId, type Look,
} from "./proKit";
import { type Place, clip, coordText, digits, distanceText, milesBetween, num, placeName, placesOf, str } from "./proFormat";

/**
 * MAPS PRO (family "mx-"): seven map looks with a documentary map room's
 * finish - real imagery graded like a film (USGS orthoimagery inside the US,
 * NASA Blue Marble elsewhere, the same public-domain tiles the satellite maps
 * use), clean vector outlines in the same projection, refined markers and
 * labels that stay legible on any terrain:
 *
 *   mx-globe-dive     a globe turns to the place and dives into it - globe, region, then the real ground -
 *                     the marker lands and the place is named (place)
 *   mx-terrain-pin    a monochrome terrain push onto the place, survey hairlines closing on it, the name and
 *                     its coordinates (place)
 *   mx-route-draw     two places framed, the route drawn from one to the other with direction marks, the
 *                     distance in a tag at its middle (route)
 *   mx-measure-line   two places and a surveyor's dimension line between them, the distance counting along it
 *                     (distance)
 *   mx-region-pulse   a clean vector map: the state (or country) holding the place fills, its outline pulses
 *                     outward, the camera leans in, the name beside it (region, place)
 *   mx-path-trace     several places in order joined by one flowing line, a numbered stop at each (several places)
 *   mx-pull-back      the reverse of a zoom: from the ground up to the whole country, the place held by its
 *                     marker, the state outlined - where in the world this is (place)
 *
 * Places come only from the gazetteer (overlay.locations); a look with none
 * draws nothing. A missing tile leaves its square dark, it never fails the
 * render. The sounds are the map's own: a soft swoop on a camera move, one
 * pin as the marker lands, ticks while a distance counts.
 */

type Geometry = { type: string; coordinates: unknown };
type Feat = { type: string; id?: string | number; properties?: { name?: string }; geometry: Geometry | null };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };
type Pt = [number, number];

// ------------------------------------------------------------------ geography
const WORLD_FC = feature(worldTopology as never, worldTopology.objects.countries as never) as unknown as FeatColl;
const COUNTRIES = WORLD_FC.features.filter((f) => f.properties?.name !== "Antarctica");
const STATES = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features;
const LOWER48 = STATES.filter((f) => {
  const id = Number(f.id);
  return Number.isFinite(id) && id <= 56 && id !== 2 && id !== 15;
});
const US_BOXES = [[18, 50, -126, -65], [51, 72, -170, -129], [18, 23, -161, -154]];
const inUS = (p: Place) => US_BOXES.some(([a, b, c, d]) => p.lat >= a && p.lat <= b && p.lon >= c && p.lon <= d);
const contains = (f: Feat, p: Place) => {
  try {
    return geoContains(f as never, [p.lon, p.lat]);
  } catch {
    return false;
  }
};
const stateOf = (p: Place) => (inUS(p) ? STATES.find((f) => contains(f, p)) || null : null);
const countryOf = (p: Place) => COUNTRIES.find((f) => contains(f, p)) || null;
/** The state or country the overlay names (its text), else the one holding the first place. */
const regionFor = (p: Place, named: string): Feat | null => {
  const n = named.toLowerCase().trim();
  if (n) {
    const byName = [...STATES, ...COUNTRIES].find((f) => (f.properties?.name || "").toLowerCase() === n);
    if (byName) return byName;
  }
  return stateOf(p) || countryOf(p);
};

// ------------------------------------------------------------------ web mercator camera
const DISPLAY = 1.5;
const RAD = Math.PI / 180;
const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) => {
  const s = Math.sin(Math.max(-85, Math.min(85, lat)) * RAD);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};
/** The camera: the centre in mercator units (0..1) and a fractional zoom. */
interface Cam { mx: number; my: number; z: number }
const camOn = (p: { lat: number; lon: number }, z: number): Cam => ({ mx: mercX(p.lon), my: mercY(p.lat), z });

/** How close the camera lands on a place, by what the gazetteer says it is. */
const LANDING: Record<string, number> = {
  country: 5, state: 6.6, region: 6.6, province: 6.6, county: 9, city: 11.6, town: 12.2, village: 12.6, hamlet: 12.8,
  suburb: 13, neighbourhood: 14, water: 10, lake: 10.4, reservoir: 10.4, river: 9, peak: 12.4, mountain: 11.4,
  mountain_range: 8.2, national_park: 9.4, dam: 14.2, building: 15.6, road: 14, island: 9.6, bay: 9.4,
};
const landingZoom = (p: Place, us: boolean) => Math.min(LANDING[p.kind || ""] ?? 11, us ? USGS_MAX - 0.4 : GIBS_MAX);

/** The zoom at which the places fill `boxW` x `boxH` px. */
const fitZoom = (ps: Place[], boxW: number, boxH: number, unit: number, zMax: number) => {
  const xs = ps.map((p) => mercX(p.lon));
  const ys = ps.map((p) => mercY(p.lat));
  const dx = Math.max(1e-7, Math.max(...xs) - Math.min(...xs));
  const dy = Math.max(1e-7, Math.max(...ys) - Math.min(...ys));
  const z = Math.log2(Math.min(boxW / (dx * TILE * unit), boxH / (dy * TILE * unit)));
  return Math.max(2, Math.min(zMax, z));
};
const centreOf = (ps: Place[]): Cam => {
  const xs = ps.map((p) => mercX(p.lon));
  const ys = ps.map((p) => mercY(p.lat));
  return { mx: (Math.min(...xs) + Math.max(...xs)) / 2, my: (Math.min(...ys) + Math.max(...ys)) / 2, z: 0 };
};

/** A projector for a camera: (lat, lon) -> screen px. */
const projector = (cam: Cam, unit: number, width: number, height: number) => {
  const s = TILE * 2 ** cam.z * unit;
  return (lat: number, lon: number): Pt => [width / 2 + (mercX(lon) - cam.mx) * s, height / 2 + (mercY(lat) - cam.my) * s];
};

/**
 * The imagery under a camera: the tiles of its zoom (the next level fading in
 * as it nears), USGS inside the US with a Blue Marble underlay for the sea,
 * graded by `grade` (a CSS filter). USGS no-data is dropped and a missing USGS
 * level is drawn from the next (motion/satelliteTiles); a tile that fails
 * leaves its square to the underlay.
 */
const Tiles: React.FC<{ cam: Cam; us: boolean; grade: string; opacity?: number }> = ({ cam, us, grade, opacity = 1 }) => {
  const { kw, width, height } = useBase();
  const id = useSvgId("mxt");
  const unit = DISPLAY * kw;
  const zMax = us ? USGS_MAX : GIBS_MAX;
  const zc = Math.max(0, cam.z);
  const base = Math.min(zMax, Math.floor(zc));
  const frac = zc > zMax ? 0 : zc - base;
  const layers: { z: number; o: number }[] = [{ z: base, o: 1 }];
  if (base + 1 <= zMax && frac > 0.55) layers.push({ z: base + 1, o: clamp01((frac - 0.55) / 0.4) });
  const under = usgsZoom(base, us) ? [{ z: Math.min(GIBS_MAX, base), o: 1 }] : [];
  const layer = ({ z, o }: { z: number; o: number }, gibs: boolean) => {
    const scale = unit * 2 ** (zc - z);
    const size = TILE * scale;
    const n = 2 ** z;
    const cx = cam.mx * n * TILE;
    const cy = cam.my * n * TILE;
    const left = cx - width / 2 / scale - 2;
    const right = cx + width / 2 / scale + 2;
    const top = cy - height / 2 / scale - 2;
    const bottom = cy + height / 2 / scale + 2;
    const out: React.ReactNode[] = [];
    for (let ty = Math.floor(top / TILE); ty <= Math.floor(bottom / TILE); ty++) {
      if (ty < 0 || ty >= n) continue;
      for (let tx = Math.floor(left / TILE); tx <= Math.floor(right / TILE); tx++) {
        const wx = ((tx % n) + n) % n;
        out.push(
          <ImageryTile key={`${gibs ? "g" : "u"}${z}-${tx}-${ty}`} id={id} z={z} x={wx} y={ty} us={us} under={gibs}
            left={width / 2 + (tx * TILE - cx) * scale} top={height / 2 + (ty * TILE - cy) * scale} size={size} opacity={o} />,
        );
      }
    }
    return out;
  };
  return (
    <AbsoluteFill style={{ background: "#0b1a2c", filter: grade, opacity }}>
      <TileFilters id={id} />
      {under.flatMap((l) => layer(l, true))}
      {layers.flatMap((l) => layer(l, false))}
    </AbsoluteFill>
  );
};

/** The film grade on imagery: dark, cool and desaturated, so the markers and words carry the colour. */
const NIGHT = "saturate(0.62) brightness(0.6) contrast(1.16)";
/** A monochrome terrain grade (the imagery as relief): grey, lifted contrast, a cool cast. */
const MONO_GRADE = "contrast(1.18) brightness(1.02)";

/** The duotone the terrain look grades its imagery with: navy shadows, a cool mid, warm paper highlights. */
const Duotone: React.FC<{ id: string }> = ({ id }) => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <filter id={id} colorInterpolationFilters="sRGB">
      <feColorMatrix type="matrix" values="0.30 0.55 0.15 0 0  0.30 0.55 0.15 0 0  0.30 0.55 0.15 0 0  0 0 0 1 0" />
      <feComponentTransfer>
        <feFuncR type="table" tableValues="0.02 0.09 0.30 0.68 0.93" />
        <feFuncG type="table" tableValues="0.04 0.12 0.31 0.64 0.88" />
        <feFuncB type="table" tableValues="0.07 0.17 0.33 0.58 0.79" />
      </feComponentTransfer>
    </filter>
  </svg>
);

/** A feature's outline as an SVG path in mercator screen space (rings culled when far off screen). */
const mercPath = (f: Feat | null, proj: (lat: number, lon: number) => Pt): string => {
  if (!f || !f.geometry) return "";
  const g = f.geometry;
  const polys = (g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? (g.coordinates as unknown[]) : []) as
    number[][][][];
  let d = "";
  for (const poly of polys) {
    for (const ring of poly) {
      if (!ring.length) continue;
      d += `M${ring.map(([lon, lat]) => {
        const [x, y] = proj(lat, lon);
        return `${x.toFixed(1)} ${y.toFixed(1)}`;
      }).join(" L")} Z `;
    }
  }
  return d;
};

// ------------------------------------------------------------------ markers and labels
/** A place marker: a white core in an accent ring, a soft pulse, popping in at `at` (frames, 30 fps). */
const Marker: React.FC<{ x: number; y: number; at: number; accent: string; size?: number; pulse?: boolean }> =
  ({ x, y, at, accent, size = 1, pulse = true }) => {
    const { f, S, k, fps } = useBase();
    const p = inOf(f, at * S, 12 * S, (t) => backOut(t, 2.2));
    if (p <= 0) return null;
    const q = pulse ? ((f - at * S) / (fps * 1.4)) % 1 : 1;
    return (
      <g>
        {pulse ? <circle cx={x} cy={y} r={(16 + 46 * q) * k * size} fill="none" stroke={accent} strokeWidth={3 * k}
          opacity={(1 - q) * 0.75 * p} /> : null}
        <circle cx={x} cy={y} r={17 * k * size * p} fill="rgba(8,10,14,.55)" stroke={accent} strokeWidth={4 * k}
          style={{ filter: `drop-shadow(0 0 ${10 * k}px ${rgba(accent, 0.7)})` }} />
        <circle cx={x} cy={y} r={7 * k * size * p} fill="#fff" />
      </g>
    );
  };

/** A place's name, region and (optionally) coordinates on a dark glass plate, at a corner of its point. */
const PlaceLabel: React.FC<{ x: number; y: number; place: Place; at: number; side?: "right" | "left"; coords?: boolean;
  size?: number; title?: string; accent: string }> = ({ x, y, place, at, side = "right", coords = false, size = 1, title, accent }) => {
  const { f, S, k, width } = useBase();
  const p = inOf(f, at * S, 14 * S);
  if (p <= 0) return null;
  const nm = placeName(place.label);
  const name = clip(digits(title || nm.name || place.label), 30).toUpperCase();
  const region = clip(nm.region, 28).toUpperCase();
  const nameSize = 58 * k * size;
  const nameW = textWidth(name, ANTON, nameSize, 400, 0.02);
  const regW = region ? textWidth(region, SUBLINE, 24 * k, 700, 0.18) : 0;
  const coordW = coords ? textWidth(coordText(place.lat, place.lon), MONO, 22 * k, 500) : 0;
  const w = Math.max(nameW, regW, coordW) + 48 * k;
  const room = side === "right" ? x + 44 * k + w < width - 80 * k : x - 44 * k - w < 80 * k;
  const right = side === "right" ? room : !room;
  const left = right ? x + 44 * k : x - 44 * k - w;
  return (
    <div style={{ position: "absolute", left, top: y - nameSize * 0.92, width: w, opacity: p,
      transform: `translateX(${((1 - p) * (right ? -18 : 18) * k).toFixed(1)}px)` }}>
      <div style={{ padding: `${16 * k}px ${24 * k}px`, borderRadius: 8 * k, background: "rgba(8,10,14,.66)",
        backdropFilter: `blur(${10 * k}px)`, border: `${Math.max(1, 1.2 * k)}px solid rgba(255,255,255,.12)`,
        boxShadow: `0 ${14 * k}px ${36 * k}px rgba(0,0,0,.45)` }}>
        {region ? <div style={{ ...caps(24 * k, hotOf(accent), 0.18), marginBottom: 10 * k }}>{region}</div> : null}
        <div style={{ ...heavy(nameSize, "#fff", 0.02) }}>{name}</div>
        {coords ? (
          <div style={{ fontFamily: MONO, fontWeight: 500, fontSize: 22 * k, color: "rgba(255,255,255,.62)", marginTop: 12 * k,
            whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{coordText(place.lat, place.lon)}</div>
        ) : null}
      </div>
    </div>
  );
};

/** The look's title, top-left, when the plan gave one that is not just the place's name. */
const MapTitle: React.FC<{ text: string; places: Place[]; at: number; out: number }> = ({ text, places, at, out }) => {
  const { f, S, k, kw } = useBase();
  const t = clip(digits(str(text)), 48).toUpperCase();
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (!t || places.some((p) => norm(placeName(p.label).name) === norm(t))) return null;
  const p = inOf(f, at * S, 14 * S);
  const fitted = fit(t, { font: ANTON, tracking: 0.01 }, 1100 * kw, 54 * k, 36 * k, 1);
  return (
    <div style={{ position: "absolute", left: 110 * kw, top: 90 * kw, opacity: p * (1 - out),
      transform: `translateY(${((1 - p) * 14 * k).toFixed(1)}px)`, ...heavy(fitted.size, "#fff"), textShadow: lift(k, 0.75) }}>
      {fitted.lines[0]}
    </div>
  );
};

// ================================================================== mx-globe-dive
const DIVE = { rotFrames: 22, diveAt: 16, diveFrames: 46, pin: 68 };

/** The place, its landing zoom and whether the imagery is USGS's. */
export const divePlan = (ov: Overlay) => {
  const ps = placesOf(ov.locations, 1);
  if (!ps.length) return null;
  const us = inUS(ps[0]);
  return { place: ps[0], us, zEnd: landingZoom(ps[0], us) };
};

const GlobeDive: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("mxg");
  const plan = divePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "map-whoosh", alt: ["whoosh-cinematic-for-maps", "map-swoop", "whoosh-soft-v2"], at: DIVE.diveAt + 24, gain_db: -7 },
    { name: "pin-drop", alt: ["ui-pop", "pop"], at: DIVE.pin, gain_db: -6 },
  ] : []);
  if (!plan) return null;
  const { place, us } = plan;
  const unit = DISPLAY * kw;
  const cosL = Math.max(0.2, Math.cos(place.lat * RAD));
  // The globe's radius R (px) and the tile zoom z are one camera: R = world width / (2 pi cos lat).
  const zOfR = (R: number) => Math.log2((2 * Math.PI * R * cosL) / (TILE * unit));
  const R0 = 330 * k;
  const z0 = zOfR(R0);
  const dive = inOf(f, DIVE.diveAt * S, DIVE.diveFrames * S, easeInOut);
  const z = lerp(z0, plan.zEnd, dive) + 0.12 * clamp01((f - (DIVE.diveAt + DIVE.diveFrames) * S) / Math.max(1, dur));
  const R = (TILE * 2 ** z * unit) / (2 * Math.PI * cosL);
  const rot = inOf(f, 0, DIVE.rotFrames * S, easeOut);
  const lam = lerp(place.lon + 62, place.lon, rot);
  const phi = lerp(place.lat * 0.35 - 6, place.lat, rot);
  // The imagery takes over from the globe between zoom 4.8 and 6.
  const tileO = clamp01((z - 4.8) / 1.2);
  const globeO = 1 - clamp01((z - 5.4) / 1.0);
  const proj = geoOrthographic().rotate([-lam, -phi]).scale(R).translate([width / 2, height / 2]).clipAngle(90);
  const path = geoPath(proj);
  const cam = camOn(place, z);
  const project = projector(cam, unit, width, height);
  const [px, py] = tileO > 0.5 ? project(place.lat, place.lon) : (proj([place.lon, place.lat]) || [width / 2, height / 2]) as Pt;
  const state = tileO > 0 ? stateOf(place) : null;
  const statePath = state ? mercPath(state, project) : "";
  const showGlobe = globeO > 0.001;
  const atmo = Math.min(R * 1.18, Math.hypot(width, height));
  return (
    <AbsoluteFill style={{ background: "#03060b" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        {showGlobe ? (
          <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: globeO }}>
            <defs>
              <radialGradient id={`${id}o`} cx={width / 2 - R * 0.35} cy={height / 2 - R * 0.4} r={R * 1.5} gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor="#1d4a78" />
                <stop offset="0.55" stopColor="#0d2846" />
                <stop offset="1" stopColor="#040d1a" />
              </radialGradient>
              <radialGradient id={`${id}l`} cx={width / 2 - R * 0.4} cy={height / 2 - R * 0.45} r={R * 1.6} gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor="rgba(255,250,235,.16)" />
                <stop offset="0.45" stopColor="rgba(255,250,235,0)" />
                <stop offset="0.8" stopColor="rgba(0,0,0,.28)" />
                <stop offset="1" stopColor="rgba(0,0,0,.55)" />
              </radialGradient>
              <radialGradient id={`${id}a`} cx={width / 2} cy={height / 2} r={atmo} gradientUnits="userSpaceOnUse">
                <stop offset={String(Math.min(0.985, R / atmo))} stopColor="rgba(140,200,255,.42)" />
                <stop offset={String(Math.min(0.995, R / atmo + 0.04))} stopColor="rgba(140,200,255,.16)" />
                <stop offset="1" stopColor="rgba(140,200,255,0)" />
              </radialGradient>
              <clipPath id={`${id}disc`}><circle cx={width / 2} cy={height / 2} r={R} /></clipPath>
            </defs>
            <circle cx={width / 2} cy={height / 2} r={atmo} fill={`url(#${id}a)`} />
            <circle cx={width / 2} cy={height / 2} r={R} fill={`url(#${id}o)`} />
            <path d={path(geoGraticule10()) || ""} fill="none" stroke="rgba(170,210,255,.09)" strokeWidth={1 * k} />
            {COUNTRIES.map((c, i) => (
              <path key={i} d={path(c as never) || ""} fill="#4a5a43" stroke="rgba(230,236,220,.38)" strokeWidth={0.9 * k} />
            ))}
            <circle cx={width / 2} cy={height / 2} r={R} fill={`url(#${id}l)`} clipPath={`url(#${id}disc)`} />
            <circle cx={width / 2} cy={height / 2} r={R} fill="none" stroke="rgba(190,225,255,.5)" strokeWidth={1.6 * k} />
          </svg>
        ) : null}
        {tileO > 0 ? <Tiles cam={cam} us={us} grade={NIGHT} opacity={tileO} /> : null}
        <Vignette strength={0.55} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          {statePath ? <path d={statePath} fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={2 * k} opacity={tileO}
            strokeDasharray={`${8 * k} ${6 * k}`} /> : null}
          {f < DIVE.pin * S ? (
            <circle cx={px} cy={py} r={6 * k} fill={hot} opacity={inOf(f, 10 * S, 8 * S)}
              style={{ filter: `drop-shadow(0 0 ${10 * k}px ${hot})` }} />
          ) : null}
          <Marker x={px} y={py} at={DIVE.pin} accent={hot} size={1.1} />
        </svg>
        <PlaceLabel x={px} y={py} place={place} at={DIVE.pin + 4} coords accent={accent} />
      </AbsoluteFill>
      <MapTitle text={str(overlay.text)} places={[place]} at={4} out={out} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

// ================================================================== mx-terrain-pin
const TER = { push: 34, lock: 30, pin: 34 };

const TerrainPin: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const duo = useSvgId("mxduo");
  const plan = divePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "zoom-in-whoosh", alt: ["whoosh-soft-v2", "swoosh-text"], at: 16, gain_db: -9 },
    { name: "pin-drop", alt: ["ui-pop", "pop"], at: TER.pin, gain_db: -6 },
  ] : []);
  if (!plan) return null;
  const { place, us } = plan;
  const unit = DISPLAY * kw;
  const zEnd = plan.zEnd - 0.3;
  const push = inOf(f, 0, TER.push * S, easeOut);
  const z = lerp(zEnd - 3, zEnd, push) + 0.15 * clamp01((f - TER.push * S) / Math.max(1, dur));
  // The place sits a little left of centre: its label reads to the right.
  const cam0 = camOn(place, z);
  const cam = { ...cam0, mx: cam0.mx + (140 * kw) / (TILE * 2 ** z * unit) };
  const project = projector(cam, unit, width, height);
  const [px, py] = project(place.lat, place.lon);
  const lock = inOf(f, 10 * S, (TER.lock - 10) * S, easeInOut);
  const state = stateOf(place);
  const statePath = state ? mercPath(state, project) : "";
  const hair = "rgba(255,255,255,.72)";
  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Duotone id={duo} />
        <AbsoluteFill style={{ filter: `url(#${duo})` }}>
          <Tiles cam={cam} us={us} grade={MONO_GRADE} />
        </AbsoluteFill>
        <AbsoluteFill style={{ background: `radial-gradient(circle ${(620 * k).toFixed(0)}px at ${px.toFixed(0)}px ${py.toFixed(0)}px, `
          + "rgba(0,0,0,0) 0%, rgba(3,6,10,.22) 55%, rgba(3,6,10,.62) 100%)" }} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          {statePath ? <path d={statePath} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth={2 * k}
            strokeDasharray={`${10 * k} ${8 * k}`} /> : null}
          {/* survey hairlines closing on the place */}
          <line x1={lerp(0, px - 46 * k, lock)} x2={px - 46 * k} y1={py} y2={py} stroke={hair} strokeWidth={1.6 * k} opacity={lock} />
          <line x1={px + 46 * k} x2={lerp(width, px + 46 * k, lock)} y1={py} y2={py} stroke={hair} strokeWidth={1.6 * k} opacity={lock} />
          <line x1={px} x2={px} y1={lerp(0, py - 46 * k, lock)} y2={py - 46 * k} stroke={hair} strokeWidth={1.6 * k} opacity={lock} />
          <line x1={px} x2={px} y1={py + 46 * k} y2={lerp(height, py + 46 * k, lock)} stroke={hair} strokeWidth={1.6 * k} opacity={lock} />
          <circle cx={px} cy={py} r={lerp(140, 34, lock) * k} fill="none" stroke="rgba(255,255,255,.85)" strokeWidth={2 * k}
            opacity={lock * (f < TER.pin * S ? 1 : 1 - inOf(f, TER.pin * S, 10 * S))} />
          <Marker x={px} y={py} at={TER.pin} accent={hot} />
        </svg>
        <PlaceLabel x={px} y={py} place={place} at={TER.pin + 3} coords accent={accent} />
      </AbsoluteFill>
      <MapTitle text={str(overlay.text)} places={[place]} at={4} out={out} />
      <Grain opacity={0.06} />
    </AbsoluteFill>
  );
};

// ================================================================== two places
/** The first two places framed: their camera, zoom and the distance as the map writes it. */
export const pairPlan = (ov: Overlay, frameW = 0.56, frameH = 0.5) => {
  const ps = placesOf(ov.locations, 2);
  if (ps.length < 2) return null;
  const us = ps.every(inUS);
  const miles = milesBetween(ps[0], ps[1]);
  return { a: ps[0], b: ps[1], us, frameW, frameH, miles, distance: distanceText(miles, num(ov.value), ov.suffix) };
};

/** A smooth bow from a to b (a quadratic curve lifted by `bend` of its length). */
const bow = (a: Pt, b: Pt, bend: number) => {
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const side = ny > 0 ? -1 : 1;
  const c: Pt = [mx + nx * len * bend * side, my + ny * len * bend * side];
  const at = (t: number): Pt => [(1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0],
    (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]];
  return { c, at };
};

// ================================================================== mx-route-draw
const ROUTE = { push: 30, drawAt: 12, drawFrames: 36, land: 48 };

const RouteDraw: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("mxr");
  const plan = pairPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "whoosh-soft-v2", alt: ["swoosh-text", "whoosh-soft"], at: ROUTE.drawAt + 6, gain_db: -9 },
    { name: "pin-drop", alt: ["ui-pop", "pop"], at: ROUTE.land, gain_db: -6 },
  ] : []);
  if (!plan) return null;
  const { a, b, us } = plan;
  const unit = DISPLAY * kw;
  const zMax = us ? USGS_MAX - 0.3 : GIBS_MAX;
  const zFit = fitZoom([a, b], width * plan.frameW, height * plan.frameH, unit, zMax);
  const push = inOf(f, 0, ROUTE.push * S, easeOut);
  const z = lerp(zFit - 1.1, zFit, push) + 0.1 * clamp01((f - ROUTE.push * S) / Math.max(1, dur));
  const cam = { ...centreOf([a, b]), z };
  const project = projector(cam, unit, width, height);
  const A = project(a.lat, a.lon);
  const B = project(b.lat, b.lon);
  const curve = bow(A, B, 0.16);
  const draw = inOf(f, ROUTE.drawAt * S, ROUTE.drawFrames * S, easeInOut);
  const N = 72;
  const pts: Pt[] = [];
  for (let i = 0; i <= N; i++) pts.push(curve.at((i / N) * draw));
  const d = `M${pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L")}`;
  const head = pts[pts.length - 1];
  // Direction marks every ~110 px along the drawn part.
  let along = 0;
  const marks: React.ReactNode[] = [];
  for (let i = 1; i < pts.length; i++) {
    const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    along += seg;
    if (along >= 110 * k && i < pts.length - 4) {
      along = 0;
      const ang = Math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0]) * (180 / Math.PI);
      marks.push(<path key={i} d={`M${-7 * k} ${-7 * k} L${4 * k} 0 L${-7 * k} ${7 * k}`} fill="none" stroke="#0b0d11"
        strokeWidth={3 * k} strokeLinecap="round" strokeLinejoin="round"
        transform={`translate(${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)}) rotate(${ang.toFixed(1)})`} />);
    }
  }
  const mid = curve.at(0.5);
  const tagP = inOf(f, (ROUTE.land + 2) * S, 12 * S);
  const tag = plan.distance;
  const tagW = tag ? textWidth(tag, ANTON, 44 * k, 400, 0.02) + 40 * k : 0;
  const leftA = A[0] > B[0];
  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Tiles cam={cam} us={us} grade={NIGHT} />
        <Vignette strength={0.5} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <filter id={`${id}g`} x="-10%" y="-10%" width="120%" height="120%">
              <feGaussianBlur stdDeviation={6 * k} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          {draw > 0 ? (
            <>
              <path d={d} fill="none" stroke="rgba(0,0,0,.55)" strokeWidth={14 * k} strokeLinecap="round" strokeLinejoin="round" />
              <path d={d} fill="none" stroke={hot} strokeWidth={8 * k} strokeLinecap="round" strokeLinejoin="round"
                filter={`url(#${id}g)`} />
              {marks}
              {f < (ROUTE.land + 1) * S ? <circle cx={head[0]} cy={head[1]} r={9 * k} fill="#fff"
                style={{ filter: `drop-shadow(0 0 ${10 * k}px ${hot})` }} /> : null}
            </>
          ) : null}
          <Marker x={A[0]} y={A[1]} at={6} accent={hot} size={0.8} pulse={false} />
          <Marker x={B[0]} y={B[1]} at={ROUTE.land} accent={hot} size={1.1} />
        </svg>
        <PlaceLabel x={A[0]} y={A[1]} place={a} at={8} side={leftA ? "right" : "left"} size={0.72} accent={accent} />
        <PlaceLabel x={B[0]} y={B[1]} place={b} at={ROUTE.land + 3} side={leftA ? "left" : "right"} accent={accent} />
        {tag ? (
          <div style={{ position: "absolute", left: mid[0] - tagW / 2, top: mid[1] - 34 * k, width: tagW, height: 64 * k,
            display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 32 * k, background: "#0b0d11",
            border: `${2 * k}px solid ${hot}`, opacity: tagP, transform: `scale(${(0.86 + 0.14 * tagP).toFixed(3)})`,
            boxShadow: `0 ${10 * k}px ${28 * k}px rgba(0,0,0,.5)` }}>
            <span style={{ ...heavy(44 * k, "#fff", 0.02) }}>{tag}</span>
          </div>
        ) : null}
      </AbsoluteFill>
      <MapTitle text={str(overlay.text)} places={[a, b]} at={4} out={out} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

// ================================================================== mx-measure-line
const MEAS = { pinsAt: 4, lineAt: 16, land: 44 };

const MeasureLine: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const plan = pairPlan(overlay, 0.5, 0.42);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "ui-tick", alt: ["tick"], at: MEAS.pinsAt + 4, gain_db: -8 },
    { name: "ui-tick", alt: ["tick"], at: MEAS.pinsAt + 10, gain_db: -8 },
    { name: "count-roll", alt: ["count-tick", "ui-tick"], at: MEAS.lineAt + 4, align: "start", until: MEAS.land - 1, gain_db: -12 },
    { name: "count-final", alt: ["ui-tick", "tick"], at: MEAS.land, gain_db: -5 },
  ] : []);
  if (!plan) return null;
  const { a, b, us } = plan;
  const unit = DISPLAY * kw;
  const zMax = us ? USGS_MAX - 0.3 : GIBS_MAX;
  const zFit = fitZoom([a, b], width * plan.frameW, height * plan.frameH, unit, zMax);
  const z = zFit - 0.35 + 0.35 * inOf(f, 0, dur, easeInOut);
  const cam = { ...centreOf([a, b]), z, my: centreOf([a, b]).my + (40 * kw) / (TILE * 2 ** z * unit) };
  const project = projector(cam, unit, width, height);
  const A = project(a.lat, a.lon);
  const B = project(b.lat, b.lon);
  const dx = B[0] - A[0];
  const dy = B[1] - A[1];
  const len = Math.hypot(dx, dy) || 1;
  // The dimension line runs parallel to A-B, offset to the upper side.
  let nx = -dy / len;
  let ny = dx / len;
  if (ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  const off = 90 * k;
  const A2: Pt = [A[0] + nx * off, A[1] + ny * off];
  const B2: Pt = [B[0] + nx * off, B[1] + ny * off];
  const grow = inOf(f, MEAS.lineAt * S, (MEAS.land - MEAS.lineAt) * S, easeInOut);
  const M: Pt = [(A2[0] + B2[0]) / 2, (A2[1] + B2[1]) / 2];
  const L1: Pt = [lerp(M[0], A2[0], grow), lerp(M[1], A2[1], grow)];
  const L2: Pt = [lerp(M[0], B2[0], grow), lerp(M[1], B2[1], grow)];
  let ang = Math.atan2(dy, dx) * (180 / Math.PI);
  if (ang > 90) ang -= 180;
  if (ang < -90) ang += 180;
  const extP = inOf(f, (MEAS.lineAt - 6) * S, 12 * S);
  const said = num(overlay.value);
  const unitWord = /k/i.test(str(overlay.suffix)) && said !== null ? "KM" : "MI";
  const total = said !== null && /^(MI|KM|miles?|kilometers?|km)$/i.test(str(overlay.suffix)) ? said : plan.miles;
  const shown = total * grow;
  const shownText = `${shown < 10 ? shown.toFixed(1) : Math.round(shown).toLocaleString("en-US")} ${unitWord}`;
  const finalText = plan.distance || shownText;
  const textSize = 54 * k;
  const tw = textWidth(f >= MEAS.land * S ? finalText : shownText, ANTON, textSize, 400, 0.02) + 36 * k;
  const arrow = (P: Pt, dir: number) => {
    const ux = (dx / len) * dir;
    const uy = (dy / len) * dir;
    return `M${P[0] + ux * 18 * k + uy * 9 * k} ${P[1] + uy * 18 * k - ux * 9 * k} L${P[0]} ${P[1]} `
      + `L${P[0] + ux * 18 * k - uy * 9 * k} ${P[1] + uy * 18 * k + ux * 9 * k}`;
  };
  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Tiles cam={cam} us={us} grade={NIGHT} />
        {/* a faint survey grid */}
        <AbsoluteFill style={{ opacity: 0.09 * inOf(f, 0, 14 * S),
          backgroundImage: "linear-gradient(rgba(255,255,255,1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,1) 1px, transparent 1px)",
          backgroundSize: `${120 * k}px ${120 * k}px` }} />
        <Vignette strength={0.5} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <line x1={A[0]} y1={A[1]} x2={B[0]} y2={B[1]} stroke="rgba(255,255,255,.55)" strokeWidth={2 * k}
            strokeDasharray={`${8 * k} ${8 * k}`} opacity={extP} />
          <line x1={A[0] + nx * 22 * k} y1={A[1] + ny * 22 * k} x2={A2[0] + nx * 16 * k} y2={A2[1] + ny * 16 * k}
            stroke="rgba(255,255,255,.75)" strokeWidth={2 * k} opacity={extP} />
          <line x1={B[0] + nx * 22 * k} y1={B[1] + ny * 22 * k} x2={B2[0] + nx * 16 * k} y2={B2[1] + ny * 16 * k}
            stroke="rgba(255,255,255,.75)" strokeWidth={2 * k} opacity={extP} />
          {grow > 0 ? (
            <g>
              <line x1={L1[0]} y1={L1[1]} x2={L2[0]} y2={L2[1]} stroke={hot} strokeWidth={3.4 * k}
                style={{ filter: `drop-shadow(0 0 ${6 * k}px ${rgba(hot, 0.6)})` }} />
              {grow > 0.96 ? (
                <>
                  <path d={arrow(A2, 1)} fill="none" stroke={hot} strokeWidth={3.4 * k} strokeLinecap="round" strokeLinejoin="round" />
                  <path d={arrow(B2, -1)} fill="none" stroke={hot} strokeWidth={3.4 * k} strokeLinecap="round" strokeLinejoin="round" />
                </>
              ) : null}
            </g>
          ) : null}
          <Marker x={A[0]} y={A[1]} at={MEAS.pinsAt} accent={hot} size={0.9} pulse={false} />
          <Marker x={B[0]} y={B[1]} at={MEAS.pinsAt + 6} accent={hot} size={0.9} pulse={false} />
        </svg>
        {grow > 0 ? (
          <div style={{ position: "absolute", left: M[0] - tw / 2, top: M[1] - textSize * 0.68, width: tw, height: textSize * 1.36,
            display: "flex", alignItems: "center", justifyContent: "center", transform: `rotate(${ang.toFixed(2)}deg)`,
            background: "#0b0d11", borderRadius: 8 * k, border: `${2 * k}px solid ${rgba(hot, 0.85)}`,
            opacity: inOf(f, (MEAS.lineAt + 2) * S, 8 * S) }}>
            <span style={{ ...heavy(textSize, "#fff", 0.02) }}>{f >= MEAS.land * S ? finalText : shownText}</span>
          </div>
        ) : null}
        <PlaceLabel x={A[0]} y={A[1] + 70 * k} place={a} at={MEAS.pinsAt + 6} side={A[0] < B[0] ? "left" : "right"} size={0.66}
          accent={accent} />
        <PlaceLabel x={B[0]} y={B[1] + 70 * k} place={b} at={MEAS.pinsAt + 12} side={A[0] < B[0] ? "right" : "left"} size={0.66}
          accent={accent} />
      </AbsoluteFill>
      <MapTitle text={str(overlay.text)} places={[a, b]} at={4} out={out} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

// ================================================================== mx-region-pulse
const PULSE = { push: 40, fillAt: 10, hit: 22 };

/** The region to light (named in the text, else holding the place) and the place, or null. */
export const regionPlan = (ov: Overlay) => {
  const ps = placesOf(ov.locations, 1);
  if (!ps.length) return null;
  const region = regionFor(ps[0], str(ov.text));
  if (!region) return null;
  return { place: ps[0], region, us: inUS(ps[0]) && LOWER48.includes(region) };
};

const RegionPulse: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur, fps } = useBase();
  const id = useSvgId("mxp");
  const plan = regionPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [{ name: "radar-ping", alt: ["ui-pop", "pop"], at: PULSE.hit, gain_db: -10 }] : []);
  // Projections are built once per document (they never change with the frame).
  const geo = React.useMemo(() => {
    if (!plan) return null;
    const pool = plan.us ? LOWER48 : COUNTRIES;
    const projection = plan.us
      ? geoAlbers().fitExtent([[160 * kw, 150 * kw], [width - 160 * kw, height - 120 * kw]], { type: "FeatureCollection", features: LOWER48 } as never)
      : (() => {
        const [[x0, y0], [x1, y1]] = geoBounds(plan.region as never);
        const pad = Math.max(8, (x1 - x0) * 1.2, (y1 - y0) * 1.2);
        return geoAlbers().rotate([-(x0 + x1) / 2, 0]).center([0, (y0 + y1) / 2]).parallels([y0, y1])
          .fitExtent([[160 * kw, 150 * kw], [width - 160 * kw, height - 120 * kw]],
            { type: "MultiPoint", coordinates: [[x0 - pad, y0 - pad / 2], [x1 + pad, y1 + pad / 2]] } as never);
      })();
    const path = geoPath(projection);
    const c = geoCentroid(plan.region as never);
    const centre = projection(c as [number, number]) || [width / 2, height / 2];
    const bounds = path.bounds(plan.region as never);
    return { pool: pool.map((x) => ({ d: path(x as never) || "", me: x === plan.region })), region: path(plan.region as never) || "",
      centre, bounds, place: projection([plan.place.lon, plan.place.lat]) || centre };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.region, plan?.place.lat, plan?.place.lon, width, height]);
  if (!plan || !geo) return null;
  const push = inOf(f, 0, PULSE.push * S, easeInOut);
  const [[bx0, by0], [bx1, by1]] = geo.bounds;
  const want = Math.min((width * 0.42) / Math.max(1, bx1 - bx0), (height * 0.5) / Math.max(1, by1 - by0));
  const zoom = lerp(1, Math.max(1, Math.min(2.6, want)), push) * (1 + 0.02 * clamp01(f / Math.max(1, dur)));
  const cx = lerp(width / 2, geo.centre[0], push);
  const cy = lerp(height / 2, geo.centre[1], push);
  const sx = (x: number) => width * 0.4 + (x - cx) * zoom;
  const sy = (y: number) => height / 2 + (y - cy) * zoom;
  const transform = `translate(${(width * 0.4).toFixed(1)} ${(height / 2).toFixed(1)}) scale(${zoom.toFixed(4)}) translate(${(-cx).toFixed(1)} ${(-cy).toFixed(1)})`;
  const fillP = inOf(f, PULSE.fillAt * S, 14 * S);
  const pulses = [PULSE.hit, PULSE.hit + 16, PULSE.hit + 32].map((at) => clamp01((f - at * S) / (26 * S)));
  const name = clip(digits(str(overlay.label) || plan.region.properties?.name || placeName(plan.place.label).region), 26).toUpperCase();
  const sub = clip(digits(str(overlay.subtitle)), 40).toUpperCase();
  const lx = sx(bx1) + 60 * k;
  const ly = sy((by0 + by1) / 2);
  const labelP = inOf(f, (PULSE.hit + 4) * S, 14 * S);
  const nameSize = fit(name, { font: ANTON }, width - lx - 100 * kw, 92 * k, 48 * k, 1).size;
  const t = f / fps;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse 90% 80% at 45% 45%, #142030 0%, #0a111b 60%, #05080d 100%)" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <filter id={`${id}g`} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation={10 * k / zoom} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <g transform={transform}>
            {geo.pool.map((p, i) => (p.me ? null : (
              <path key={i} d={p.d} fill="#1b2633" stroke="rgba(170,190,215,.32)" strokeWidth={1.2 * k / zoom} />
            )))}
            {pulses.map((q, i) => (q > 0 && q < 1 ? (
              <g key={i} transform={`translate(${geo.centre[0]} ${geo.centre[1]}) scale(${(1 + 0.42 * easeOut(q)).toFixed(4)}) translate(${-geo.centre[0]} ${-geo.centre[1]})`}>
                <path d={geo.region} fill="none" stroke={hot} strokeWidth={3 * k / zoom} opacity={(1 - q) * 0.7} />
              </g>
            ) : null))}
            <path d={geo.region} fill={rgba(hot, 0.28 * fillP)} stroke={hot} strokeWidth={3.2 * k / zoom} opacity={Math.max(0.35, fillP)}
              filter={`url(#${id}g)`} />
            <circle cx={geo.place[0]} cy={geo.place[1]} r={(7 + Math.sin(t * 4) * 1.2) * k / zoom} fill="#fff"
              opacity={inOf(f, PULSE.hit * S, 10 * S)} style={{ filter: `drop-shadow(0 0 ${8 * k}px ${hot})` }} />
          </g>
        </svg>
        <div style={{ position: "absolute", left: lx, top: ly - nameSize * 0.75, opacity: labelP,
          transform: `translateX(${((1 - labelP) * -20 * k).toFixed(1)}px)` }}>
          <div style={{ ...heavy(nameSize, "#fff", 0.02), textShadow: lift(k, 0.6) }}>{name}</div>
          {sub ? <div style={{ ...caps(26 * k, hot, 0.18), marginTop: 16 * k }}>{sub}</div> : null}
        </div>
      </AbsoluteFill>
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

// ================================================================== mx-path-trace
const TRACE = { drawAt: 10, drawFrames: 50 };

/** Three to eight places in order, framed, or null. */
export const tracePlan = (ov: Overlay) => {
  const ps = placesOf(ov.locations, 8);
  if (ps.length < 3) return null;
  return { places: ps, us: ps.every(inUS) };
};

/** A Catmull-Rom curve through the points, sampled: [points, the index of each stop in the samples]. */
const catmull = (P: Pt[], per = 24): { pts: Pt[]; stops: number[] } => {
  const pts: Pt[] = [];
  const stops: number[] = [0];
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(0, i - 1)];
    const p1 = P[i];
    const p2 = P[i + 1];
    const p3 = P[Math.min(P.length - 1, i + 2)];
    for (let s = 0; s < per; s++) {
      const t = s / per;
      const t2 = t * t;
      const t3 = t2 * t;
      pts.push([
        0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
        0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
      ]);
    }
    stops.push(pts.length);
  }
  pts.push(P[P.length - 1]);
  stops[stops.length - 1] = pts.length - 1;
  return { pts, stops };
};

const PathTrace: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur, fps } = useBase();
  const id = useSvgId("mxc");
  const plan = tracePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const n = plan ? plan.places.length : 0;
  const stopAt = (i: number) => TRACE.drawAt + (TRACE.drawFrames * i) / Math.max(1, n - 1);
  const sound = useLookSound(plan ? plan.places.slice(0, 7).map((_, i) => ({ name: "ui-pop", alt: ["pop", "ui-tick"],
    at: Math.round(stopAt(i)), gain_db: i === n - 1 ? -6 : -10 })) as SoundCue[] : []);
  if (!plan) return null;
  const { places, us } = plan;
  const unit = DISPLAY * kw;
  const zMax = us ? USGS_MAX - 0.3 : GIBS_MAX;
  const zFit = fitZoom(places, width * 0.6, height * 0.56, unit, zMax);
  const z = zFit - 0.5 + 0.5 * inOf(f, 0, 40 * S, easeOut) + 0.08 * clamp01(f / Math.max(1, dur));
  const cam = { ...centreOf(places), z };
  const project = projector(cam, unit, width, height);
  const P = places.map((p) => project(p.lat, p.lon));
  const { pts, stops } = catmull(P);
  const draw = clamp01((f - TRACE.drawAt * S) / (TRACE.drawFrames * S));
  const upto = Math.max(1, Math.round(draw * (pts.length - 1)));
  const shown = pts.slice(0, upto + 1);
  const d = `M${shown.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L")}`;
  const full = `M${pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L")}`;
  const flowing = f >= (TRACE.drawAt + TRACE.drawFrames) * S;
  const t = f / fps;
  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Tiles cam={cam} us={us} grade={NIGHT} />
        <Vignette strength={0.5} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <filter id={`${id}g`} x="-10%" y="-10%" width="120%" height="120%">
              <feGaussianBlur stdDeviation={6 * k} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <path d={d} fill="none" stroke="rgba(0,0,0,.5)" strokeWidth={13 * k} strokeLinecap="round" strokeLinejoin="round" />
          <path d={d} fill="none" stroke={hot} strokeWidth={7 * k} strokeLinecap="round" strokeLinejoin="round" filter={`url(#${id}g)`} />
          {flowing ? (
            <path d={full} fill="none" stroke="rgba(255,255,255,.85)" strokeWidth={3 * k} strokeLinecap="round"
              strokeDasharray={`${2 * k} ${34 * k}`} strokeDashoffset={-t * 90 * k} />
          ) : null}
          {P.map(([x, y], i) => {
            const at = Math.round(stopAt(i));
            const p = inOf(f, at * S, 10 * S, (q) => backOut(q, 2));
            if (p <= 0) return null;
            return (
              <g key={i} transform={`translate(${x} ${y}) scale(${p.toFixed(3)})`}>
                <circle r={22 * k} fill="#0b0d11" stroke={hot} strokeWidth={4 * k} />
                <text y={9 * k} textAnchor="middle" fill="#fff" style={{ fontFamily: ANTON, fontSize: 26 * k }}>{i + 1}</text>
              </g>
            );
          })}
        </svg>
        {places.map((p, i) => {
          const [x, y] = P[i];
          const at = Math.round(stopAt(i)) + 2;
          const lp = inOf(f, at * S, 12 * S);
          const name = clip(placeName(p.label).name, 26).toUpperCase();
          // Labels sit away from the line: on the side of the next stop's opposite.
          const nx = (P[Math.min(n - 1, i + 1)][0] + P[Math.max(0, i - 1)][0]) / 2;
          const right = x >= nx ? true : x + 420 * k > width - 80 * kw ? false : x < nx - 1 ? false : true;
          const w = textWidth(name, SUBLINE, 28 * k, 700, 0.12) + 28 * k;
          return (
            <div key={i} style={{ position: "absolute", top: y - 22 * k, left: right ? x + 36 * k : x - 36 * k - w, width: w,
              opacity: lp, transform: `translateX(${((1 - lp) * (right ? -12 : 12) * k).toFixed(1)}px)`, padding: `${8 * k}px ${14 * k}px`,
              borderRadius: 6 * k, background: "rgba(8,10,14,.7)", ...caps(28 * k, "#fff", 0.12), boxSizing: "border-box",
              textAlign: right ? "left" : "right" }}>{name}</div>
          );
        })}
      </AbsoluteFill>
      <MapTitle text={str(overlay.text)} places={places} at={4} out={out} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

// ================================================================== mx-pull-back
const PULL = { holdTo: 8, pullFrames: 58, land: 66 };

const PullBack: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const plan = divePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "whoosh-cinematic", alt: ["map-swoop", "whoosh-soft-v2"], at: PULL.holdTo + 18, gain_db: -9 },
    { name: "ui-pop", alt: ["pop", "ui-tick"], at: PULL.land, gain_db: -7 },
  ] : []);
  if (!plan) return null;
  const { place, us } = plan;
  const unit = DISPLAY * kw;
  // The context: the lower 48 (or the place's country) in view.
  const ctx = us ? fitZoom([{ label: "", lat: 49, lon: -124.5 }, { label: "", lat: 25, lon: -67 }], width * 0.86, height * 0.8, unit, 6)
    : Math.max(2.2, plan.zEnd - 5.5);
  const pull = inOf(f, PULL.holdTo * S, PULL.pullFrames * S, easeInOut);
  const z = lerp(plan.zEnd, ctx, pull);
  const drift = clamp01((pull - 0.55) / 0.45) ** 2;
  const focus = us ? { mx: lerp(mercX(place.lon), mercX(-96.5), drift), my: lerp(mercY(place.lat), mercY(38.2), drift) }
    : camOn(place, 0);
  const cam = { mx: focus.mx, my: focus.my, z };
  const project = projector(cam, unit, width, height);
  const [px, py] = project(place.lat, place.lon);
  // The imagery hands over to a clean vector map as the view widens.
  const vec = clamp01((6.4 - z) / 1.6);
  const pool = us ? LOWER48 : COUNTRIES;
  const state = stateOf(place) || countryOf(place);
  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Tiles cam={cam} us={us} grade={NIGHT} opacity={1 - vec * 0.85} />
        <AbsoluteFill style={{ opacity: vec, background: "radial-gradient(ellipse 90% 80% at 50% 45%, rgba(20,32,48,.86) 0%, rgba(8,13,20,.94) 100%)" }} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          {vec > 0 ? pool.map((s, i) => (
            <path key={i} d={mercPath(s, project)} fill={s === state ? rgba(hot, 0.22 * vec) : "rgba(30,42,56,.9)"}
              stroke={s === state ? hot : "rgba(170,190,215,.35)"} strokeWidth={(s === state ? 2.6 : 1.2) * k} opacity={vec} />
          )) : null}
          {state && vec < 0.6 ? <path d={mercPath(state, project)} fill="none" stroke="rgba(255,255,255,.6)" strokeWidth={2 * k}
            strokeDasharray={`${8 * k} ${6 * k}`} opacity={clamp01(pull * 3) * (1 - vec)} /> : null}
          <Marker x={px} y={py} at={2} accent={hot} size={1.0} />
        </svg>
        <PlaceLabel x={px} y={py} place={place} at={PULL.land} accent={accent} />
      </AbsoluteFill>
      <MapTitle text={str(overlay.text)} places={[place]} at={4} out={out} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "mx-globe-dive": guard(GlobeDive),
  "mx-terrain-pin": guard(TerrainPin),
  "mx-route-draw": guard(RouteDraw),
  "mx-measure-line": guard(MeasureLine),
  "mx-region-pulse": guard(RegionPulse),
  "mx-path-trace": guard(PathTrace),
  "mx-pull-back": guard(PullBack),
};
