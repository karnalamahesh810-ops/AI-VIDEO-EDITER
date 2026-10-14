import React from "react";
import { AbsoluteFill } from "remotion";
import { geoArea, geoCircle, geoContains, geoInterpolate, geoMercator, geoPath } from "d3-geo";
import type { MapArea, Overlay } from "../../types";
import { guard, useSvgId, type Look } from "./proKit";
import { figureOf, num, placesOf, str, type Place } from "./proFormat";
import { useLookSound } from "./LookSounds";
import {
  areaBox, boxOf, cities, mainGeometry, countryAt, findArea, fitCam, flyCam, frameBox, joinBox, kmBetween, labelPoint, mercY,
  projectionOf, regionAt, worldPx, type Area, type Cam, type XY,
} from "../maps2/geo";
import { MapCanvas, tiltPoint, type Fill, type Tilt } from "../maps2/MapCanvas";
import { alpha, mix, type MapKit } from "../maps2/kit";
import {
  BigFigure, Dot, MapTitle, Pill, PinMark, Vignette, backOut, clamp01, cubicInOut, cubicOut, figureFrom, quintOut,
  shortName, useMap,
} from "../maps2/parts";
import { GIBS_MAX, ImageryTile, TILE, TileFilters, USGS_MAX, usgsZoom } from "../motion/satelliteTiles";

/**
 * MAPS V2 (2026-10-14): twelve branded map looks for every niche (history, news, travel, geography, business,
 * true crime, sport ...), built to the owner's PointShift reference (docs/smart-editor/ref/sheet_1.jpg): a dark
 * 3D-relief map, the focus region filled in the kit's region colour (relief showing through it), small gold pill
 * labels, white dotted routes, heavy white figures with small-caps units, and eased camera pushes - all in the
 * channel's brand kit (components/maps2/kit.ts). Geography is Natural Earth (public domain, bundled: countries,
 * states / provinces, key cities, shaded relief - src/data/maps2); places come only from the gazetteer
 * (overlay.locations, src/geocode.py) and areas from the planner's name lookup (overlay.areas, src/mapsv2.py).
 * Every part lands on its word (items[i].at / areas[i].at, seconds from the look's start); all motion is a pure
 * function of the frame (30 fps frames scaled, so 60 fps is the same move, twice as smooth).
 *
 *   m2-zoom-dive      the globe turns to the place, dives into its country (filled), then on to its state / region
 *   m2-region-pulse   a country or region fills in the region colour, its outline pulsing outward, its name pill
 *   m2-relief-tilt    the relief map lays back in 3D and the region rises out of it as an extruded block
 *   m2-route          a white dotted route draws stop to stop with a moving marker, the distance counting
 *   m2-places         several places: a dot and a gold pill each, staggered on their words
 *   m2-border-trace   a border or coastline draws on in gold, then the area fills
 *   m2-choropleth     areas shaded by their values (ramp to the region colour), a counter and a legend
 *   m2-compare        two areas side by side at true scale, their sizes (or said values) counting, then laid over
 *   m2-radius         a true-distance circle grows round a place, the radius counting, the cities inside named
 *   m2-flows          curved arrows flow from one place to the others (or into it), dashes streaming along them
 *   m2-pin-drop       "you are here": the camera flies in, a pin drops and bounces, a ripple, its name and position
 *   m2-sat-flat       real satellite imagery of the place crossfades into the flat branded map, the area filling
 */

type AreaRef = MapArea;
type O = Overlay & { areas?: AreaRef[]; kit?: string; direction?: string };

// ------------------------------------------------------------------ inputs
const placesIn = (o: O, max = 8): Place[] => placesOf(o.locations, max);
const areasIn = (o: O): { area: Area; ref: AreaRef }[] => (Array.isArray(o.areas) ? o.areas : [])
  .map((ref) => ({ ref, area: findArea(ref?.id) || findArea(ref?.label) }))
  .filter((x): x is { area: Area; ref: AreaRef } => !!x.area);
const nameOf = (ref: AreaRef | undefined, a: Area) => shortName(str(ref?.label) || a.name);
/** The area a single-place look focuses: the overlay's own, else the region holding the place, else its country. */
const focusOf = (o: O, prefer: "region" | "country" = "region"): { area: Area | null; place: Place | null; ref?: AreaRef } => {
  const list = areasIn(o);
  const place = placesIn(o, 1)[0] || null;
  if (list.length) return { area: list[0].area, place, ref: list[0].ref };
  if (!place) return { area: null, place: null };
  const a = prefer === "region" ? regionAt(place.lon, place.lat) || countryAt(place.lon, place.lat) : countryAt(place.lon, place.lat);
  return { area: a, place };
};
const at30 = (s: unknown, fallback: number) => (typeof s === "number" && Number.isFinite(s) ? Math.max(0, s * 30) : fallback);
const itemAt = (o: O, i: number, fallback: number) => at30(((o.items || [])[i] as { at?: number } | undefined)?.at, fallback);
const wideOf = (W: number, H: number) => W >= H;
const fadeIn = (t: number) => clamp01(t / 7);

const Root: React.FC<{ kit: MapKit; out: number; t: number; children: React.ReactNode }> = ({ kit, out, t, children }) => (
  <AbsoluteFill style={{ background: kit.sea, opacity: fadeIn(t) * (1 - out), overflow: "hidden" }}>{children}</AbsoluteFill>
);

const Svg: React.FC<{ W: number; H: number; children: React.ReactNode }> = ({ W, H, children }) => (
  <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>{children}</svg>
);

/** The cam a globe of radius r facing `face` matches on a flat map (the same local scale at its centre). */
const globeCam = (face: XY, r: number, W: number): Cam => ({
  lon: face[0], lat: face[1], z: Math.log2((2 * Math.PI * r * Math.cos((face[1] * Math.PI) / 180)) / worldPx(0, W)),
});

const SWOOP = { name: "map-swoop", alt: ["whoosh-cinematic-for-maps", "whoosh-soft"], gain_db: -12 };
const POP = { name: "ui-pop", alt: ["pop", "pin-drop"], gain_db: -12 };
const PIN = { name: "pin-drop", alt: ["ui-pop", "pop"], gain_db: -10 };
const TICK = { name: "count-tick", alt: ["ui-tick", "tick"], gain_db: -14 };
const cue = (c: { name: string; alt: string[]; gain_db: number }, at: number) => ({ ...c, at: Math.max(0, Math.round(at)) });

// ================================================================== m2-zoom-dive
const ZoomDive: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const { t, W, H, u, kit, out } = m;
  const place = placesIn(o, 1)[0] || null;
  const list = areasIn(o);
  const pt: XY | null = place ? [place.lon, place.lat] : list[0] ? labelPoint(list[0].area) : null;
  const country = list.find((x) => x.area.kind === "country")?.area || (pt ? countryAt(pt[0], pt[1]) : null);
  const regionRef = list.find((x) => x.area.kind === "region");
  const region = regionRef?.area || (pt && place ? regionAt(pt[0], pt[1]) : null);
  const ok = !!pt && !!country;
  const cA = itemAt(o, 0, 92);                     // the country's word
  const rA = itemAt(o, 1, 150);                    // the region's word
  const sound = useLookSound(ok ? [cue(SWOOP, 0), cue(SWOOP, 52), cue(POP, cA), ...(region ? [cue(POP, rA)] : [])] : null);
  if (!ok || !pt || !country) return null;
  const wide = wideOf(W, H);
  const face0: XY = [pt[0] + 75, Math.max(-35, Math.min(35, pt[1] * 0.2))];
  const turn = cubicInOut(clamp01(t / 54));
  const face: XY = [face0[0] + (pt[0] - face0[0]) * turn, face0[1] + (pt[1] * 0.85 - face0[1]) * turn];
  const r0 = Math.min(W, H) * 0.36;
  // the dive: the globe grows until its curve is barely seen, and the flat map takes over at the very same scale
  // and centre (a short crossfade where the two projections still agree), then flies on to the country
  const DIVE = 5.5;
  const dive = clamp01((t - 46) / 24);
  const r = r0 * (1 + 0.12 * turn) * Math.pow(DIVE, cubicInOut(dive));
  const camC = fitCam(frameBox(country), W, H, 0.2, 7.5, wide ? [-0.04, 0] : [0, -0.05]);
  const handover = globeCam(face, r0 * 1.12 * DIVE, W);
  const camR = region && region.id !== country.id ? fitCam(frameBox(region), W, H, 0.24, 7.4, wide ? [-0.04, 0] : [0, -0.05]) : null;
  const stage2 = camR ? Math.max(cA + 24, rA - 18) : Infinity;
  let cam: Cam;
  if (t < 70) cam = globeCam(face, r, W);
  else if (t < stage2) cam = flyCam(handover, camC, cubicInOut(clamp01((t - 70) / 38)));
  else cam = flyCam(camC, camR!, cubicInOut(clamp01((t - stage2) / 42)));
  cam = { ...cam, z: cam.z + Math.max(0, t - (camR ? stage2 + 42 : 108)) * 0.0012 };
  const cross = clamp01((t - 64) / 6);
  const cIn = m.p(26, 18, cubicOut);
  const rIn = camR ? m.p(stage2 + 14, 20, cubicOut) : 0;
  const fills: Fill[] = [{ area: country, color: camR ? mix(kit.region, kit.land, 0.78 * rIn) : kit.region, opacity: 0.92 * cIn,
    glow: 0.6 * (1 - rIn) }];
  if (camR && region) fills.push({ area: region, color: kit.region, opacity: rIn, glow: 0.8 });
  const proj = projectionOf(cam, W, H);
  const lp = proj(labelPoint(country)) || [W / 2, H / 2];
  const rp = region ? proj(labelPoint(region)) || [W / 2, H / 2] : null;
  const pp = proj(pt) || [W / 2, H / 2];
  const cPill = m.p(cA, 14, cubicOut) * (1 - clamp01(rIn * 1.6));
  const plain = (x: string) => x.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+(prefecture|province|state|region|county|oblast|governorate)$/, "").trim();
  const showPlace = !!place && (!region || plain(shortName(place.label)) !== plain(region.name));
  const plA = camR ? stage2 + 46 : cA + 16;
  return (
    <Root kit={kit} out={out} t={t}>
      {cross < 1 ? <MapCanvas cam={cam} kit={kit} globe={{ center: [W / 2, H / 2], r, face, fills: fills.slice(0, 1) }} /> : null}
      {cross > 0 ? <MapCanvas cam={cam} kit={kit} opacity={cross} layers={{ fills, inner: rIn > 0 || cam.z > 4.5 ? country.a3 : undefined }} /> : null}
      <Svg W={W} H={H}>
        {showPlace && camR ? <Dot x={pp[0]} y={pp[1]} p={m.p(plA, 12)} kit={kit} u={u} ping={clamp01((t - plA) / 26)} /> : null}
        {showPlace && !camR ? <Dot x={pp[0]} y={pp[1]} p={m.p(plA, 12)} kit={kit} u={u} ping={clamp01((t - plA) / 26)} /> : null}
      </Svg>
      {cross > 0.6 ? <Pill x={lp[0]} y={lp[1]} text={nameOf(list.find((x) => x.area === country)?.ref, country)} kit={kit} u={u}
        p={cPill} anchor="center" size={1.15} /> : null}
      {rp && camR ? <Pill x={rp[0]} y={rp[1]} text={nameOf(regionRef?.ref, region!)} kit={kit} u={u} p={m.p(rA, 14, cubicOut)} anchor="center"
        size={1.1} /> : null}
      {showPlace ? <Pill x={pp[0]} y={pp[1]} text={shortName(place!.label)} kit={kit} u={u} p={m.p(plA + 4, 14, cubicOut)} anchor="right" dot /> : null}
      <MapTitle text={o.text} kicker={str(o.label)} kit={kit} u={u} p={m.p(10, 18)} out={0} W={W} H={H} />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-region-pulse
const RegionPulse: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const { t, W, H, u, kit, out } = m;
  const list = areasIn(o).slice(0, 3);
  const f0 = focusOf(o);
  const areas = list.length ? list : f0.area ? [{ area: f0.area, ref: f0.ref || {} }] : [];
  const ats = areas.map((x, i) => at30(x.ref.at, 14 + i * 20));
  const sound = useLookSound(areas.length ? [cue(SWOOP, 0), ...ats.map((a) => cue(POP, a + 6))] : null);
  if (!areas.length) return null;
  const wide = wideOf(W, H);
  const fig = figureFrom(o.value, o.suffix, o.prefix);
  const bias: XY = fig ? (wide ? [-0.12, 0] : [0, -0.1]) : [0, 0];
  const end = fitCam(areaBox(areas.map((x) => x.area)), W, H, 0.2, 8, bias);
  const cam = { ...end, z: end.z - 0.55 + 0.55 * cubicOut(clamp01(t / 70)) + Math.max(0, t - 70) * 0.0011 };
  const fills: Fill[] = areas.map((x, i) => ({ area: x.area, color: kit.region, opacity: m.p(ats[i], 16, cubicOut) * 0.95,
    glow: 0.5 + 0.5 * Math.max(0, Math.sin(((t - ats[i]) / 40) * Math.PI * 2)) * clamp01((t - ats[i]) / 20) }));
  const proj = projectionOf(cam, W, H);
  const country = areas[0].area.kind === "region" ? areas[0].area.a3 : undefined;
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills, inner: country, dim: 0.5 * m.p(10, 30) }} />
      <PulseRings areas={areas.map((x) => x.area)} ats={ats} t={t} proj={proj} kit={kit} u={u} W={W} H={H} />
      {areas.map((x, i) => {
        const lp = proj(labelPoint(x.area)) || [W / 2, H / 2];
        return <Pill key={x.area.id} x={lp[0]} y={lp[1]} text={nameOf(x.ref, x.area)} kit={kit} u={u} p={m.p(ats[i] + 8, 14, cubicOut)}
          anchor="center" size={1.1} />;
      })}
      {fig ? <BigFigure x={wide ? W * 0.8 : W / 2} y={wide ? H * 0.5 : H * 0.8} fig={fig} p={m.p(Math.max(...ats) + 16, 34, cubicOut)} kit={kit}
        u={u} label={str(o.label)} /> : null}
      <MapTitle text={o.text} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette />
      {sound}
    </Root>
  );
};

/** Outline copies of each area expanding from its middle and fading: the pulse, three beats. */
const PulseRings: React.FC<{ areas: Area[]; ats: number[]; t: number; proj: ReturnType<typeof projectionOf>; kit: MapKit; u: number;
  W: number; H: number }> = ({ areas, ats, t, proj, kit, u, W, H }) => {
  const id = useSvgId("m2p");
  const path = geoPath(proj);
  return (
    <Svg W={W} H={H}>
      <defs><filter id={`${id}g`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={3 * u} /></filter></defs>
      {areas.map((a, i) => {
        const d = path(a.geometry as never) || "";
        const c = proj(labelPoint(a)) || [W / 2, H / 2];
        return [0, 1, 2].map((b) => {
          const s = (t - ats[i] - 14 - b * 26) / 34;
          if (s <= 0 || s >= 1) return null;
          const k = 1 + cubicOut(s) * 0.22;
          return <path key={`${a.id}${b}`} d={d} fill="none" stroke={mix(kit.region, "#ffffff", 0.35)} strokeWidth={3 * u / k}
            opacity={(1 - s) * 0.85} filter={`url(#${id}g)`}
            transform={`translate(${c[0]} ${c[1]}) scale(${k}) translate(${-c[0]} ${-c[1]})`} />;
        });
      })}
    </Svg>
  );
};

// ================================================================== m2-relief-tilt
const ReliefTilt: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const id = useSvgId("m2t");
  const { t, W, H, u, kit, out } = m;
  const f0 = focusOf(o);
  const area = f0.area;
  const aA = at30(f0.ref?.at, 30);
  const sound = useLookSound(area ? [cue(SWOOP, 0), cue({ name: "boom-soft", alt: ["hit-deep", "impact"], gain_db: -15 }, aA + 10), cue(POP, aA + 26)] : null);
  if (!area) return null;
  const wide = wideOf(W, H);
  const end = fitCam(frameBox(area), W, H, wide ? 0.26 : 0.22, 8, [0, 0.06]);
  const tl = cubicInOut(clamp01(t / 48));
  const tilt: Tilt = { deg: 52 * tl, persp: Math.max(W, H) * 1.05 };
  const cam = { ...end, z: end.z - 0.7 + 0.7 * cubicOut(clamp01(t / 60)) + Math.max(0, t - 60) * 0.0012 };
  const rise = backOut(clamp01((t - aA) / (26 * m.T)), 1.1);
  const hMax = Math.min(W, H) * 0.055;
  const h = hMax * rise;
  const proj = projectionOf(cam, W, H);
  const country = countryAt(...labelPoint(area));
  const fills: Fill[] = [{ area, color: mix(kit.region, "#000000", 0.35), opacity: 0.9 * clamp01(rise * 2), glow: 0.2 }];
  // the block: walls (far ones first), then the top face
  const rings = ringsOf(area, proj);
  const walls: { d: string; y: number; shade: number }[] = [];
  const tops: string[] = [];
  if (h > 0.5) {
    for (const ring of rings) {
      const top = ring.map(([x, y]) => tiltPoint(x, y, h, tilt, W, H));
      const base = ring.map(([x, y]) => tiltPoint(x, y, 0, tilt, W, H));
      for (let i = 0; i < ring.length - 1; i++) {
        const [x0, y0] = ring[i], [x1, y1] = ring[i + 1];
        const nx = y1 - y0, ny = -(x1 - x0);                       // outward for clockwise screen rings
        const len = Math.hypot(nx, ny) || 1;
        if (ny / len < -0.05) continue;                             // a wall facing away (hidden by the top)
        const shade = 0.35 + 0.5 * Math.max(0, (nx * 0.45 + ny * 0.9) / len);
        walls.push({ d: `M${base[i][0]},${base[i][1]}L${base[i + 1][0]},${base[i + 1][1]}L${top[i + 1][0]},${top[i + 1][1]}L${top[i][0]},${top[i][1]}Z`,
          y: (y0 + y1) / 2, shade });
      }
      tops.push(`M${top.map((p) => `${p[0]},${p[1]}`).join("L")}Z`);
    }
    walls.sort((a, b) => a.y - b.y);
  }
  const lp = proj(labelPoint(area)) || [W / 2, H / 2];
  const pillAt = tiltPoint(lp[0], lp[1], h + 26 * u, tilt, W, H);
  const fig = figureFrom(o.value, o.suffix, o.prefix);
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} tilt={tilt} layers={{ fills, inner: area.kind === "region" ? area.a3 : country?.a3 }} />
      {/* haze over the far edge of the tilted plane */}
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${kit.sea} 0%, ${alpha(kit.sea, 0.75 * tl)} 16%, rgba(0,0,0,0) 46%)` }} />
      <Svg W={W} H={H}>
        <g opacity={clamp01((t - aA) / 9)}>
        <defs>
          <linearGradient id={`${id}top`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={mix(kit.region, "#ffffff", 0.22)} />
            <stop offset="1" stopColor={kit.region} />
          </linearGradient>
        </defs>
        {walls.map((w, i) => <path key={i} d={w.d} fill={mix(kit.region, "#000000", 1 - w.shade)} stroke={mix(kit.region, "#000000", 0.6)}
          strokeWidth={0.6 * u} />)}
        {tops.length ? <path d={tops.join("")} fill={`url(#${id}top)`} stroke={kit.regionEdge} strokeWidth={1.6 * u} fillRule="evenodd" /> : null}
        </g>
      </Svg>
      <Pill x={pillAt[0]} y={pillAt[1]} text={nameOf(f0.ref, area)} kit={kit} u={u} p={m.p(aA + 22, 14, cubicOut)} anchor="above" size={1.15} />
      {fig ? <BigFigure x={wide ? W * 0.82 : W / 2} y={wide ? H * 0.32 : H * 0.18} fig={fig} p={m.p(aA + 34, 34, cubicOut)} kit={kit} u={u} /> : null}
      <MapTitle text={o.text} kicker={str(o.label)} kit={kit} u={u} p={m.p(10, 18)} out={0} W={W} H={H} corner={wide ? "tl" : "bl"} />
      <Vignette strength={0.6} />
      {sound}
    </Root>
  );
};

/** An area's outer rings on screen (frame px), each closed, clockwise on screen; tiny islands left out. */
const ringsOf = (a: Area, proj: ReturnType<typeof projectionOf>): XY[][] => {
  const g = a.geometry as { type: string; coordinates: unknown };
  const polys = (g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : []) as number[][][][];
  const out: XY[][] = [];
  for (const poly of polys) {
    const ring = (poly[0] || []).map((p) => proj(p as XY)).filter((p): p is [number, number] => !!p);
    if (ring.length < 4) continue;
    let s = 0;
    for (let i = 0; i < ring.length - 1; i++) s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    if (Math.abs(s) < 600) continue;
    out.push(s < 0 ? ring.slice().reverse() : ring);
  }
  return out;
};

// ================================================================== m2-route
const Route: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const id = useSvgId("m2r");
  const { t, W, H, u, kit, out } = m;
  const stops = placesIn(o, 6);
  const n = stops.length;
  const arr: number[] = [];
  for (let i = 0; i < n; i++) arr.push(i === 0 ? 16 : Math.max(arr[i - 1] + 26, itemAt(o, i, 16 + i * 46)));
  const sound = useLookSound(n >= 2 ? [cue(SWOOP, 0), ...arr.slice(1).map((a) => cue(PIN, a)), cue(TICK, arr[1] - 18)] : null);
  if (n < 2) return null;
  const wide = wideOf(W, H);
  const pts = stops.map((s) => [s.lon, s.lat] as XY);
  const box = boxOf(pts, 1.2);
  const end = fitCam(box, W, H, 0.2, 7.6, wide ? [-0.1, 0] : [0, -0.12]);
  const start = { ...fitCam(boxOf([pts[0]], 1.2), W, H, 0.3, 7.6), z: Math.min(end.z + 1.3, 8) };
  const cam0 = flyCam(start, end, cubicInOut(clamp01((t - 4) / 44)));
  const cam = { ...cam0, z: cam0.z + Math.max(0, t - 48) * 0.0011 };
  const proj = projectionOf(cam, W, H);
  // the legs along great circles, sampled, and the head's progress: stop i reached on its word
  const legs = pts.slice(1).map((p, i) => {
    const ip = geoInterpolate(pts[i], p);
    return Array.from({ length: 33 }, (_, k) => ip(k / 32) as XY);
  });
  const legKm = pts.slice(1).map((p, i) => kmBetween(pts[i], p));
  const total = legKm.reduce((a, b) => a + b, 0);
  let doneKm = 0, head: XY = pts[0];
  const drawn: XY[] = [pts[0]];
  for (let i = 0; i < legs.length; i++) {
    const a = arr[i] + (i === 0 ? 8 : 4), b = arr[i + 1];
    const q = cubicInOut(clamp01((t - a) / Math.max(1, b - a)));
    if (q <= 0) break;
    const k = q * 32;
    const pts2 = legs[i].slice(0, Math.floor(k) + 1);
    const frac = k - Math.floor(k);
    const last = legs[i][Math.min(32, Math.floor(k) + 1)];
    const cur: XY = [pts2[pts2.length - 1][0] + (last[0] - pts2[pts2.length - 1][0]) * frac,
      pts2[pts2.length - 1][1] + (last[1] - pts2[pts2.length - 1][1]) * frac];
    drawn.push(...pts2.slice(1), cur);
    head = cur;
    doneKm += legKm[i] * q;
    if (q < 1) break;
  }
  const scr = drawn.map((p) => proj(p) || [0, 0]);
  const d = scr.length > 1 ? `M${scr.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L")}` : "";
  const hp = proj(head) || [W / 2, H / 2];
  const saidKm = num(o.value);
  const unit = str(o.suffix).toUpperCase().startsWith("MI") || /mile/i.test(str(o.suffix)) ? "MI"
    : str(o.suffix) ? "KM" : stops.every((s) => /,\s*(?:[A-Z]{2}|USA|United States|UK|United Kingdom)$/.test(s.label)) ? "MI" : "KM";
  const fullKm = saidKm && saidKm > 0 ? (unit === "MI" ? saidKm * 1.609344 : saidKm) : total;
  const shown = (doneKm / Math.max(1e-6, total)) * (unit === "MI" ? fullKm / 1.609344 : fullKm);
  const fig = figureOf(Math.round(unit === "MI" ? fullKm / 1.609344 : fullKm), unit);
  const figP = shown / Math.max(1e-6, unit === "MI" ? fullKm / 1.609344 : fullKm);
  const moving = t > arr[0] + 8 && t < arr[n - 1] + 4;
  const fills: Fill[] = [];
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills }} />
      <Svg W={W} H={H}>
        <defs><filter id={`${id}g`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation={5 * u} /></filter></defs>
        {d ? <path d={d} fill="none" stroke="#000" strokeOpacity={0.35} strokeWidth={9 * u} strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray={`0 ${15 * u}`} transform={`translate(${2 * u} ${3 * u})`} /> : null}
        {d ? <path d={d} fill="none" stroke={kit.route} strokeWidth={6 * u} strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray={`0 ${15 * u}`} /> : null}
        {stops.map((s, i) => {
          const sp = proj([s.lon, s.lat]) || [0, 0];
          return <Dot key={i} x={sp[0]} y={sp[1]} p={m.p(arr[i], 12)} kit={kit} u={u} ping={clamp01((t - arr[i]) / 24)} />;
        })}
        {moving ? (
          <g>
            <circle cx={hp[0]} cy={hp[1]} r={13 * u} fill={kit.pillBg} opacity={0.65} filter={`url(#${id}g)`} />
            <circle cx={hp[0]} cy={hp[1]} r={7.5 * u} fill="#ffffff" />
          </g>
        ) : null}
      </Svg>
      {stops.map((s, i) => {
        const sp = proj([s.lon, s.lat]) || [0, 0];
        const left = sp[0] > W * (wide ? 0.62 : 0.7);
        return <Pill key={i} x={sp[0]} y={sp[1]} text={shortName(s.label)} kit={kit} u={u} p={m.p(arr[i] + 3, 14, cubicOut)}
          anchor={left ? "left" : "right"} dot />;
      })}
      <BigFigure x={wide ? W * 0.84 : W / 2} y={wide ? H * 0.5 : H * 0.82} fig={fig} p={clamp01(figP) * m.p(arr[0] + 6, 10)} kit={kit} u={u}
        label={str(o.label)} />
      <MapTitle text={o.text} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-places
const Places: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const { t, W, H, u, kit, out } = m;
  const ps = placesIn(o, 8);
  const ats = ps.map((_p, i) => itemAt(o, i, 18 + i * 14));
  const sound = useLookSound(ps.length >= 2 ? [cue(SWOOP, 0), ...ats.map((a) => cue(POP, a))] : null);
  if (ps.length < 2) return null;
  const wide = wideOf(W, H);
  const pts = ps.map((p) => [p.lon, p.lat] as XY);
  const end = fitCam(boxOf(pts, 1.5), W, H, 0.2, 7.4, [0, 0.02]);
  const cam = { ...end, z: end.z - 0.45 + 0.45 * cubicOut(clamp01(t / 60)) + Math.max(0, t - 60) * 0.001 };
  const proj = projectionOf(cam, W, H);
  // the countries the places are in, lightly lit (several countries) - else their states
  const homes = new Map<string, Area>();
  for (const p of ps) {
    const c = countryAt(p.lon, p.lat);
    if (c) homes.set(c.id, c);
  }
  const fills: Fill[] = [...homes.values()].map((a) => ({ area: a, color: kit.region, opacity: 0.55 * m.p(4, 26, cubicOut), glow: 0.3 }));
  // pills: right of the dot unless that collides or runs off the frame
  const placed: { x0: number; x1: number; y0: number; y1: number }[] = [];
  const fs = 25 * u;
  const pills = ps.map((p, i) => {
    const sp = proj([p.lon, p.lat]) || [0, 0];
    const w = shortName(p.label).length * fs * 0.56 + fs * 0.9 + 16 * u;
    const opts: ("right" | "left" | "above" | "below")[] = sp[0] + w > W * 0.94 ? ["left", "above", "below", "right"] : ["right", "left", "above", "below"];
    let pick = opts[0];
    for (const a of opts) {
      const box = a === "right" ? { x0: sp[0], x1: sp[0] + w, y0: sp[1] - fs, y1: sp[1] + fs }
        : a === "left" ? { x0: sp[0] - w, x1: sp[0], y0: sp[1] - fs, y1: sp[1] + fs }
          : a === "above" ? { x0: sp[0] - w / 2, x1: sp[0] + w / 2, y0: sp[1] - 2.6 * fs, y1: sp[1] - 0.4 * fs }
            : { x0: sp[0] - w / 2, x1: sp[0] + w / 2, y0: sp[1] + 0.4 * fs, y1: sp[1] + 2.6 * fs };
      if (!placed.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0)) {
        pick = a;
        placed.push(box);
        break;
      }
    }
    return { sp, anchor: pick, i, p };
  });
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills, inner: homes.size === 1 ? [...homes.keys()][0] : undefined }} />
      <Svg W={W} H={H}>
        {pills.map(({ sp, i }) => <Dot key={i} x={sp[0]} y={sp[1]} p={m.p(ats[i], 12)} kit={kit} u={u} ping={clamp01((t - ats[i]) / 24)} />)}
      </Svg>
      {pills.map(({ sp, anchor, i, p }) => <Pill key={i} x={sp[0]} y={sp[1]} text={shortName(p.label)} kit={kit} u={u}
        p={m.p(ats[i] + 3, 14, cubicOut)} anchor={anchor} dot />)}
      <MapTitle text={o.text} kicker={str(o.label)} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} corner={wide ? "tl" : "bl"} />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-border-trace
const BorderTrace: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const id = useSvgId("m2b");
  const { t, W, H, u, kit, out } = m;
  const f0 = focusOf(o, "country");
  const area = f0.area;
  const a0 = at30(f0.ref?.at, 14);
  const sound = useLookSound(area ? [cue(SWOOP, 0), cue({ name: "marker-draw", alt: ["pen-scribble", "marker"], gain_db: -15 }, a0),
    cue(POP, a0 + 86)] : null);
  if (!area) return null;
  const end = fitCam(frameBox(area), W, H, 0.17, 8);
  const cam = { ...end, z: end.z - 0.35 + 0.35 * cubicOut(clamp01(t / 80)) + Math.max(0, t - 80) * 0.001 };
  const proj = projectionOf(cam, W, H);
  const draw = cubicInOut(clamp01((t - a0) / (80 * m.T)));
  const fill = m.p(a0 + 70, 22, cubicOut);
  const d = geoPath(proj)(area.geometry as never) || "";
  const lp = proj(labelPoint(area)) || [W / 2, H / 2];
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills: [{ area, color: kit.region, opacity: 0.88 * fill, glow: 0.3 }],
        inner: area.kind === "region" ? area.a3 : undefined, dim: 0.35 * clamp01(t / 30) }} />
      <Svg W={W} H={H}>
        <defs><filter id={`${id}g`} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={6 * u} /></filter></defs>
        <path d={d} fill="none" stroke={kit.pillBg} strokeWidth={9 * u} pathLength={1} strokeDasharray={`${draw} 1`} opacity={0.55}
          filter={`url(#${id}g)`} strokeLinejoin="round" strokeLinecap="round" />
        <path d={d} fill="none" stroke={mix(kit.pillBg, "#ffffff", 0.25)} strokeWidth={3.4 * u} pathLength={1} strokeDasharray={`${draw} 1`}
          strokeLinejoin="round" strokeLinecap="round" />
      </Svg>
      <Pill x={lp[0]} y={lp[1]} text={nameOf(f0.ref, area)} kit={kit} u={u} p={m.p(a0 + 80, 14, cubicOut)} anchor="center" size={1.15} />
      <MapTitle text={o.text} kicker={str(o.label)} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette />
      {sound}
    </Root>
  );
};

/** A value as it was said (no rounding: 1.95 stays 1.95), with its money sign and short unit. */
const said = (v: number, o: O) => {
  const f = figureOf(v, o.suffix, o.prefix);
  return `${f.prefix}${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}${f.glued}`;
};

// ================================================================== m2-choropleth
const Choropleth: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const { t, W, H, u, kit, out } = m;
  const list = areasIn(o).filter((x) => typeof x.ref.value === "number" && Number.isFinite(x.ref.value)).slice(0, 14);
  const ats = list.map((x, i) => at30(x.ref.at, 16 + i * 9));
  const sound = useLookSound(list.length >= 2 ? [cue(SWOOP, 0), ...ats.slice(0, 6).map((a) => cue(TICK, a))] : null);
  if (list.length < 2) return null;
  const wide = wideOf(W, H);
  const vals = list.map((x) => Number(x.ref.value));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const shade = (v: number) => mix(mix(kit.land, kit.region, 0.18), mix(kit.region, "#ffffff", 0.12), hi > lo ? (v - lo) / (hi - lo) : 1);
  const end = fitCam(areaBox(list.map((x) => x.area)), W, H, 0.17, 8, wide ? [-0.08, 0] : [0, -0.08]);
  const cam = { ...end, z: end.z - 0.3 + 0.3 * cubicOut(clamp01(t / 70)) + Math.max(0, t - 70) * 0.001 };
  const proj = projectionOf(cam, W, H);
  const fills: Fill[] = list.map((x, i) => ({ area: x.area, color: shade(vals[i]), opacity: 0.95 * m.p(ats[i], 14, cubicOut), glow: 0.15 }));
  // the counter: the overlay's own figure, else the latest lit area's value
  const lead = vals.indexOf(hi);
  const own = figureFrom(o.value, o.suffix, o.prefix);
  const fig = own || figureOf(hi, o.suffix, o.prefix);
  const top = list.map((x, i) => ({ x, i })).sort((a, b) => vals[b.i] - vals[a.i]).slice(0, 5);
  const inner = new Set(list.map((x) => x.area.a3));
  const lx = wide ? W * 0.055 : W * 0.08, ly = H * (wide ? 0.86 : 0.9), lw = Math.min(W * 0.26, 520 * u);
  const leg = m.p(ats[0] + 6, 20, cubicOut);
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills, inner: inner.size === 1 && list[0].area.kind === "region" ? list[0].area.a3 : undefined }} />
      {top.map(({ x, i }) => {
        const lp = proj(labelPoint(x.area)) || [0, 0];
        return <Pill key={x.area.id} x={lp[0]} y={lp[1]} text={`${nameOf(x.ref, x.area)} ${said(vals[i], o)}`} kit={kit} u={u}
          p={m.p(ats[i] + 6, 14, cubicOut)} anchor="center" size={0.85} />;
      })}
      <BigFigure x={wide ? W * 0.84 : W / 2} y={wide ? H * 0.46 : H * 0.76} fig={fig} p={m.p(ats[ats.length - 1] + 6, 40, cubicOut)}
        kit={kit} u={u} label={own ? str(o.label) : nameOf(list[lead].ref, list[lead].area)} size={0.85} />
      {/* legend */}
      <div style={{ position: "absolute", left: lx, top: ly, width: lw, opacity: leg * (1 - out), transform: `translateY(${(1 - leg) * 14 * u}px)` }}>
        <div style={{ fontFamily: kit.label, fontWeight: 700, fontSize: 20 * u, letterSpacing: "0.12em", color: kit.text, textTransform: "uppercase",
          marginBottom: 8 * u }}>{str(o.subtitle) || str(o.suffix) || "Value"}</div>
        <div style={{ height: 12 * u, borderRadius: 2 * u, background: `linear-gradient(90deg, ${shade(lo)}, ${shade(hi)})` }} />
        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: kit.numberFont, fontWeight: 700, fontSize: 19 * u,
          color: kit.muted, marginTop: 6 * u }}>
          <span>{said(lo, o)}</span>
          <span>{said(hi, o)}</span>
        </div>
      </div>
      <MapTitle text={o.text} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-compare
const Compare: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const id = useSvgId("m2c");
  const { t, W, H, u, kit, out } = m;
  const list = areasIn(o).slice(0, 2);
  const ats = list.map((x, i) => at30(x.ref.at, 14 + i * 24));
  const sound = useLookSound(list.length === 2 ? [cue(SWOOP, 0), cue(POP, ats[0] + 4), cue(POP, ats[1] + 4),
    cue({ name: "whoosh-soft", alt: ["swipe", "ui-swipe"], gain_db: -14 }, Math.max(ats[1] + 70, 130))] : null);
  if (list.length < 2) return null;
  const wide = wideOf(W, H);
  // one true scale for both: an oblique Mercator round each area's own middle (true size near the middle)
  const projs = list.map((x) => geoMercator().rotate([-x.area.centroid[0], -x.area.centroid[1]]).scale(1).translate([0, 0]));
  const geoms = list.map((x) => mainGeometry(x.area));
  const boxes = list.map((_x, i) => geoPath(projs[i]).bounds(geoms[i] as never));
  const cellW = wide ? W * 0.38 : W * 0.78, cellH = wide ? H * 0.5 : H * 0.3;
  const k = Math.min(...boxes.map((b) => Math.min(cellW / Math.max(1e-9, b[1][0] - b[0][0]), cellH / Math.max(1e-9, b[1][1] - b[0][1]))));
  const centers: XY[] = wide ? [[W * 0.29, H * 0.46], [W * 0.71, H * 0.46]] : [[W / 2, H * 0.3], [W / 2, H * 0.66]];
  const overlap = list.length === 2 ? cubicInOut(clamp01((t - Math.max(ats[1] + 70, 130)) / 34)) : 0;
  const kmArea = geoms.map((g) => geoArea(g as never) * 6371.0088 ** 2);
  const said = list.map((x) => (typeof x.ref.value === "number" ? x.ref.value : null));
  const useSaid = said.every((v) => v !== null);
  const colors = [kit.region, kit.pillBg];
  return (
    <Root kit={kit} out={out} t={t}>
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse 70% 60% at 50% 45%, ${kit.sea2}, ${kit.sea})` }} />
      <Svg W={W} H={H}>
        <defs>
          <pattern id={`${id}d`} width={28 * u} height={28 * u} patternUnits="userSpaceOnUse">
            <circle cx={2 * u} cy={2 * u} r={1.3 * u} fill="rgba(255,255,255,0.07)" />
          </pattern>
        </defs>
        <rect x={0} y={0} width={W} height={H} fill={`url(#${id}d)`} />
        {list.map((x, i) => {
          const b = boxes[i];
          const cx = (b[0][0] + b[1][0]) / 2, cy = (b[0][1] + b[1][1]) / 2;
          const into: XY = i === 1 && overlap > 0 ? [centers[1][0] + (centers[0][0] - centers[1][0]) * overlap,
            centers[1][1] + (centers[0][1] - centers[1][1]) * overlap] : centers[i];
          const p = m.p(ats[i], 22, cubicOut);
          const s = k * (0.86 + 0.14 * backOut(p, 1.2));
          const d = geoPath(projs[i])(geoms[i] as never) || "";
          return (
            <g key={i} opacity={clamp01(p * 2.5) * (i === 1 ? 1 - overlap * 0.25 : 1)}
              transform={`translate(${into[0]} ${into[1] + (1 - p) * 30 * u}) scale(${s}) translate(${-cx} ${-cy})`}>
              <path d={d} fill={colors[i]} fillOpacity={i === 1 && overlap > 0 ? 0.92 - overlap * 0.25 : 0.95}
                stroke={mix(colors[i], "#ffffff", 0.45)} strokeWidth={2 * u / s} />
            </g>
          );
        })}
      </Svg>
      {list.map((x, i) => {
        const c = centers[i];
        const by = wide ? H * 0.8 : c[1] + cellH * 0.5 + 40 * u;
        const fig = useSaid ? figureOf(Number(said[i]), o.suffix, o.prefix) : null;
        return (
          <React.Fragment key={i}>
            <Pill x={c[0]} y={fig ? by - 74 * u * (wide ? 1 : 0.8) : by} text={nameOf(x.ref, x.area)} kit={kit} u={u}
              p={m.p(ats[i] + 8, 14, cubicOut) * (1 - overlap)} anchor="center" size={1.3} />
            {fig ? <BigFigure x={c[0]} y={by} fig={fig} p={m.p(ats[i] + 10, 40, cubicOut) * (1 - overlap)} kit={kit} u={u} size={wide ? 0.62 : 0.5} /> : null}
          </React.Fragment>
        );
      })}
      {overlap > 0 && !useSaid ? (() => {
        // the shapes' own sizes (the bundled outlines, so a ratio to one decimal - never a made-up figure)
        const big = kmArea[0] >= kmArea[1] ? 0 : 1;
        const r = Math.round((kmArea[big] / Math.max(1, kmArea[1 - big])) * 10) / 10;
        const fig = { prefix: "", main: r.toFixed(1), glued: "×", unit: `the size of ${nameOf(list[1 - big].ref, list[1 - big].area)}`,
          value: r, pct: false } as ReturnType<typeof figureOf>;
        return <BigFigure x={W / 2} y={wide ? H * 0.82 : H * 0.88} fig={r >= 1.1 ? fig : { ...fig, main: "≈ 1", glued: "", value: 1,
          unit: "about the same size" }} p={m.p(Math.max(ats[1] + 70, 130) + 20, 30, cubicOut)} kit={kit} u={u} size={0.85}
          label={nameOf(list[big].ref, list[big].area)} />;
      })() : null}
      <MapTitle text={o.text} kicker={str(o.label) || "True scale"} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette strength={0.45} />
      {sound}
    </Root>
  );
};

// ================================================================== m2-radius
const Radius: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const id = useSvgId("m2d");
  const { t, W, H, u, kit, out } = m;
  const place = placesIn(o, 1)[0] || null;
  const said = num(o.value);
  const mi = /^mi|mile/i.test(str(o.suffix));
  const km = said && said > 0 ? (mi ? said * 1.609344 : said) : 0;
  const a0 = itemAt(o, 0, 16);
  const sound = useLookSound(place && km > 0 ? [cue(SWOOP, 0), cue({ name: "radar-ping", alt: ["ui-pop", "pop"], gain_db: -14 }, a0 + 4),
    cue(TICK, a0 + 10)] : null);
  if (!place || km <= 0) return null;
  const wide = wideOf(W, H);
  const deg = km / 111.2;
  const c: XY = [place.lon, place.lat];
  const circle = geoCircle().center(c).radius(deg).precision(2)();
  const box = boxOf([[c[0] - deg / Math.cos((c[1] * Math.PI) / 180), c[1] - deg], [c[0] + deg / Math.cos((c[1] * Math.PI) / 180), c[1] + deg]], 0.2);
  const end = fitCam(box, W, H, 0.3, 8.8, wide ? [-0.1, 0] : [0, -0.08]);
  const cam = { ...end, z: end.z - 0.5 + 0.5 * cubicOut(clamp01(t / 60)) + Math.max(0, t - 60) * 0.001 };
  const proj = projectionOf(cam, W, H);
  const grow = cubicOut(clamp01((t - a0) / (36 * m.T)));
  const ring = geoCircle().center(c).radius(Math.max(1e-4, deg * grow)).precision(2)();
  const path = geoPath(proj);
  const d = path(ring as never) || "";
  const cp = proj(c) || [W / 2, H / 2];
  // the cities inside the circle (white), and the nearest big ones round it for scale (faint)
  const near = cities().map((ct) => ({ ct, d: kmBetween(c, [ct.lon, ct.lat]) })).filter((x) => x.d > km * 0.08 && x.d < km * 3.2)
    .sort((a, b) => a.d - b.d);
  const inside = near.filter((x) => x.d < km * 0.96).slice(0, 4).map((x) => ({ ...x, inner: true }))
    .concat(near.filter((x) => x.d >= km * 1.08).slice(0, 3).map((x) => ({ ...x, inner: false })));
  const region = regionAt(c[0], c[1]);
  void circle;
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills: [], inner: region?.a3 }} />
      <Svg W={W} H={H}>
        <defs><filter id={`${id}g`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={8 * u} /></filter></defs>
        <path d={d} fill={alpha(kit.region, 0.32)} stroke="none" />
        <path d={d} fill="none" stroke={kit.region} strokeWidth={12 * u} opacity={0.6} filter={`url(#${id}g)`} />
        <path d={d} fill="none" stroke={mix(kit.region, "#ffffff", 0.55)} strokeWidth={2.6 * u} strokeDasharray={`${14 * u} ${9 * u}`}
          strokeDashoffset={-t * 0.6 * u} />
        {[0, 1, 2].map((b) => {
          const s = ((t - a0 - 40 - b * 22) % 66) / 66;
          if (t < a0 + 40 + b * 22) return null;
          const rr = geoCircle().center(c).radius(deg * s).precision(3)();
          return <path key={b} d={path(rr as never) || ""} fill="none" stroke={mix(kit.region, "#ffffff", 0.4)} strokeWidth={1.6 * u} opacity={(1 - s) * 0.5} />;
        })}
        {/* the radius itself: a line from the centre to the rim */}
        {(() => {
          const e = proj([c[0] + (deg * grow) / Math.cos((c[1] * Math.PI) / 180), c[1]]) || cp;
          return <line x1={cp[0]} y1={cp[1]} x2={e[0]} y2={e[1]} stroke="#ffffff" strokeWidth={2.4 * u} strokeDasharray={`0 ${10 * u}`}
            strokeLinecap="round" opacity={m.p(a0, 10)} />;
        })()}
        {inside.map(({ ct, inner }, i) => {
          const sp = proj([ct.lon, ct.lat]) || [0, 0];
          const pp = m.p(a0 + 44 + i * 8, 12) * (inner ? 1 : 0.6);
          return <g key={i} opacity={pp}><circle cx={sp[0]} cy={sp[1]} r={4.5 * u} fill="#fff" />
            <text x={sp[0] + 10 * u} y={sp[1] + 6 * u} fill="#ffffff" fontFamily={kit.label} fontWeight={700} fontSize={19 * u}
              letterSpacing="0.06em" style={{ textTransform: "uppercase" }} opacity={0.88}>{ct.name}</text></g>;
        })}
        <Dot x={cp[0]} y={cp[1]} p={m.p(4, 12)} kit={kit} u={u} />
      </Svg>
      <Pill x={cp[0]} y={cp[1]} text={shortName(place.label)} kit={kit} u={u} p={m.p(10, 14, cubicOut)} anchor="above" dot />
      <BigFigure x={wide ? W * 0.84 : W / 2} y={wide ? H * 0.5 : H * 0.84} fig={figureOf(said!, mi ? "MI" : "KM")} p={grow} kit={kit} u={u}
        label={str(o.label) || "Radius"} />
      <MapTitle text={o.text} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-flows
const Flows: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const id = useSvgId("m2f");
  const { t, W, H, u, kit, out } = m;
  const ps = placesIn(o, 7);
  const n = ps.length;
  const ats = ps.map((_p, i) => itemAt(o, i, i === 0 ? 12 : 22 + (i - 1) * 16));
  const sound = useLookSound(n >= 2 ? [cue(SWOOP, 0), ...ats.slice(1).map((a) => cue({ name: "whoosh-fast", alt: ["swoosh-text", "swipe"], gain_db: -16 }, a))] : null);
  if (n < 2) return null;
  const inward = str(o.direction).toLowerCase() === "in";
  const pts = ps.map((p) => [p.lon, p.lat] as XY);
  const end = fitCam(boxOf(pts, 2), W, H, 0.2, 7.2);
  const cam = { ...end, z: end.z - 0.4 + 0.4 * cubicOut(clamp01(t / 60)) + Math.max(0, t - 60) * 0.001 };
  const proj = projectionOf(cam, W, H);
  const sp = pts.map((p) => proj(p) || [0, 0]);
  const vals = (o.items || []).map((it) => num((it as { value?: unknown }).value));
  const vmax = Math.max(1e-9, ...vals.filter((v): v is number => v !== null));
  const hubC = countryAt(pts[0][0], pts[0][1]);
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills: hubC ? [{ area: hubC, color: kit.region, opacity: 0.8 * m.p(4, 20), glow: 0.4 }] : [] }} />
      <Svg W={W} H={H}>
        <defs>
          <filter id={`${id}g`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={4 * u} /></filter>
        </defs>
        {sp.slice(1).map((q, j) => {
          const i = j + 1;
          const [a, b] = inward ? [q, sp[0]] : [sp[0], q];
          const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
          const bend = Math.min(0.32 * len, 260 * u);
          const cx = (a[0] + b[0]) / 2 - (dy / len) * bend, cy = (a[1] + b[1]) / 2 + (dx / len) * bend;
          const d = `M${a[0]},${a[1]}Q${cx},${cy} ${b[0]},${b[1]}`;
          const q2 = cubicInOut(clamp01((t - ats[i]) / (24 * m.T)));
          if (q2 <= 0) return null;
          const w = vals[i] !== null && vals[i] !== undefined ? 2.5 + 6.5 * ((vals[i] as number) / vmax) : 4.2;
          // arrowhead along the curve's end tangent
          const tx = b[0] - cx, ty = b[1] - cy, tl = Math.hypot(tx, ty) || 1;
          const ah = (11 + w * 1.4) * u;
          const ux = tx / tl, uy = ty / tl;
          const tip: XY = [b[0] - ux * 10 * u, b[1] - uy * 10 * u];
          const arrow = `M${tip[0]},${tip[1]}L${tip[0] - ux * ah - uy * ah * 0.6},${tip[1] - uy * ah + ux * ah * 0.6}L${tip[0] - ux * ah + uy * ah * 0.6},${tip[1] - uy * ah - ux * ah * 0.6}Z`;
          return (
            <g key={i}>
              <path d={d} fill="none" stroke={kit.pillBg} strokeWidth={w * 2.2 * u} opacity={0.35} pathLength={1} strokeDasharray={`${q2} 1`}
                filter={`url(#${id}g)`} />
              <path d={d} fill="none" stroke={kit.pillBg} strokeWidth={w * u} pathLength={1} strokeDasharray={`${q2} 1`} strokeLinecap="round" />
              {q2 >= 1 ? <path d={d} fill="none" stroke="#ffffff" strokeWidth={Math.max(1.6, w * 0.45) * u} strokeLinecap="round"
                strokeDasharray={`${10 * u} ${26 * u}`} strokeDashoffset={-(t - ats[i]) * 2.2 * u} opacity={0.8} /> : null}
              <path d={arrow} fill={kit.pillBg} opacity={clamp01((q2 - 0.85) / 0.15)} />
            </g>
          );
        })}
        {sp.map((q, i) => <Dot key={i} x={q[0]} y={q[1]} p={m.p(i === 0 ? ats[0] : ats[i] + 18, 12)} kit={kit} u={u}
          color={i === 0 ? "#ffffff" : undefined} r={i === 0 ? 11 : 8} />)}
      </Svg>
      {sp.map((q, i) => <Pill key={i} x={q[0]} y={q[1]} text={shortName(ps[i].label)} kit={kit} u={u}
        p={m.p(i === 0 ? ats[0] + 4 : ats[i] + 20, 14, cubicOut)} anchor={q[0] > W * 0.7 ? "left" : "right"} dot size={i === 0 ? 1.15 : 1} />)}
      <MapTitle text={o.text} kicker={str(o.label)} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} corner="bl" />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-pin-drop
const PinDrop: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const { t, W, H, u, kit, out } = m;
  const place = placesIn(o, 1)[0] || null;
  const a0 = itemAt(o, 0, 40);
  const sound = useLookSound(place ? [cue(SWOOP, 0), cue(PIN, a0 + 12), cue(POP, a0 + 20)] : null);
  if (!place) return null;
  const c: XY = [place.lon, place.lat];
  const country = countryAt(c[0], c[1]);
  const region = regionAt(c[0], c[1]);
  const start = country ? fitCam(frameBox(country), W, H, 0.12, 7) : { lon: c[0], lat: c[1], z: 3 };
  const close = { lon: c[0], lat: c[1], z: Math.min(7.2, region ? fitCam(frameBox(region), W, H, 0.22, 7.2).z : 6) };
  const cam0 = flyCam(start, close, cubicInOut(clamp01((t - 2) / Math.max(30, a0 + 4))));
  const cam = { ...cam0, z: cam0.z + Math.max(0, t - a0 - 6) * 0.0016 };
  const proj = projectionOf(cam, W, H);
  const cp = proj(c) || [W / 2, H / 2];
  const fall = clamp01((t - a0) / 12);
  const drop = 1 - fall * fall;
  const land = t - a0 - 12;
  const squash = land > 0 && land < 14 ? Math.sin((land / 14) * Math.PI) * Math.exp(-land / 10) : 0;
  const o2 = clamp01((t - a0) / 4);
  const fills: Fill[] = region ? [{ area: region, color: kit.region, opacity: 0.5 * m.p(8, 24, cubicOut), glow: 0.4 }] : [];
  const coord = `${Math.abs(c[1]).toFixed(2)}° ${c[1] >= 0 ? "N" : "S"}  ${Math.abs(c[0]).toFixed(2)}° ${c[0] >= 0 ? "E" : "W"}`;
  const cardP = m.p(a0 + 20, 16, cubicOut);
  return (
    <Root kit={kit} out={out} t={t}>
      <MapCanvas cam={cam} kit={kit} layers={{ fills, inner: country?.a3 }} />
      <Svg W={W} H={H}>
        {[0, 1].map((b) => {
          const s = (land - b * 10) / 36;
          if (s <= 0 || s >= 1) return null;
          return <ellipse key={b} cx={cp[0]} cy={cp[1]} rx={(14 + s * 110) * u} ry={(5 + s * 40) * u} fill="none" stroke={kit.pillBg}
            strokeWidth={2.6 * u} opacity={(1 - s) * 0.85} />;
        })}
        <PinMark x={cp[0]} y={cp[1]} kit={kit} u={u} drop={drop} squash={squash} o={o2} size={1.5} />
      </Svg>
      <div style={{ position: "absolute", left: cp[0], top: cp[1] - 118 * u, transform: `translate(-50%, -100%) translateY(${(1 - cardP) * 12 * u}px)`,
        opacity: cardP * (1 - out), textAlign: "center", pointerEvents: "none" }}>
        <div style={{ display: "inline-block", background: kit.pillBg, color: kit.pillText, fontFamily: kit.label, fontWeight: 800, fontSize: 30 * u,
          letterSpacing: "0.05em", textTransform: "uppercase", padding: `${7 * u}px ${13 * u}px ${6 * u}px`, borderRadius: 4 * u, lineHeight: 1,
          whiteSpace: "nowrap", boxShadow: `0 ${4 * u}px ${16 * u}px rgba(0,0,0,0.45)` }}>{shortName(place.label)}</div>
        <div style={{ marginTop: 8 * u, fontFamily: kit.label, fontWeight: 700, fontSize: 18 * u, letterSpacing: "0.14em", color: "#ffffff",
          opacity: 0.85, whiteSpace: "nowrap", textShadow: "0 2px 8px rgba(0,0,0,0.7)" }}>{str(o.label) ? `${str(o.label).toUpperCase()} · ` : ""}{coord}</div>
      </div>
      <MapTitle text={o.text} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} corner="bl" />
      <Vignette />
      {sound}
    </Root>
  );
};

// ================================================================== m2-sat-flat
const US_BOXES = [[18, 50, -126, -65], [51, 72, -170, -129], [18, 23, -161, -154]];
const inUS = (lon: number, lat: number) => US_BOXES.some(([a, b, c, d]) => lat >= a && lat <= b && lon >= c && lon <= d);

/** Satellite imagery under a framing (NASA GIBS Blue Marble everywhere, USGS orthoimagery inside the US). */
const SatTiles: React.FC<{ cam: Cam; us: boolean; W: number; H: number }> = ({ cam, us, W, H }) => {
  const id = useSvgId("m2s");
  const zMax = us ? USGS_MAX : GIBS_MAX;
  const zc = Math.max(0, cam.z + Math.log2(W / 1920));
  const base = Math.min(zMax, Math.floor(zc));
  const scale = 2 ** (zc - base);
  const n = 2 ** base;
  const cx = ((cam.lon + 180) / 360) * n * TILE;
  const cy = mercY(cam.lat) * n * TILE;
  const size = TILE * scale;
  const left = cx - W / 2 / scale - 2, right = cx + W / 2 / scale + 2, top = cy - H / 2 / scale - 2, bottom = cy + H / 2 / scale + 2;
  const tiles: React.ReactNode[] = [];
  const under = usgsZoom(base, us);
  const lay = (z: number, gibs: boolean) => {
    const nn = 2 ** z, sc = 2 ** (zc - z), sz = TILE * sc;
    const ccx = ((cam.lon + 180) / 360) * nn * TILE, ccy = mercY(cam.lat) * nn * TILE;
    const l = ccx - W / 2 / sc - 2, r = ccx + W / 2 / sc + 2, tp = ccy - H / 2 / sc - 2, bt = ccy + H / 2 / sc + 2;
    for (let ty = Math.floor(tp / TILE); ty <= Math.floor(bt / TILE); ty++) {
      if (ty < 0 || ty >= nn) continue;
      for (let tx = Math.floor(l / TILE); tx <= Math.floor(r / TILE); tx++) {
        const wx = ((tx % nn) + nn) % nn;
        tiles.push(<ImageryTile key={`${gibs ? "g" : "u"}${z}-${tx}-${ty}`} id={id} z={z} x={wx} y={ty} us={us} under={gibs}
          left={W / 2 + (tx * TILE - ccx) * sc} top={H / 2 + (ty * TILE - ccy) * sc} size={sz} />);
      }
    }
  };
  if (under) lay(Math.min(GIBS_MAX, base), true);
  lay(base, false);
  void size; void left; void right; void top; void bottom;
  return (
    <AbsoluteFill style={{ background: "#0b1a2c", filter: "saturate(0.8) contrast(1.08) brightness(0.92)" }}>
      <TileFilters id={id} />
      {tiles}
    </AbsoluteFill>
  );
};

const SatFlat: Look = ({ overlay, accent }) => {
  const o = overlay as O;
  const m = useMap(o, accent);
  const { t, W, H, u, kit, out } = m;
  const f0 = focusOf(o);
  const place = f0.place;
  const area = f0.area;
  const pt: XY | null = place ? [place.lon, place.lat] : area ? labelPoint(area) : null;
  const a0 = itemAt(o, 0, 70);
  const sound = useLookSound(pt ? [cue(SWOOP, 0), cue({ name: "light-shimmer", alt: ["magnifier-glide", "whoosh-soft"], gain_db: -15 }, a0 - 6),
    cue(POP, a0 + 26)] : null);
  if (!pt) return null;
  const us = inUS(pt[0], pt[1]);
  const end = area ? fitCam(frameBox(area), W, H, 0.2, us ? 9 : 7.6) : { lon: pt[0], lat: pt[1], z: 6.5 };
  const cam = { ...end, z: end.z + 0.5 - 0.5 * cubicOut(clamp01(t / 90)) + Math.max(0, t - 90) * 0.0012 };
  const x = cubicInOut(clamp01((t - a0) / (26 * m.T)));
  const proj = projectionOf(cam, W, H);
  const lp = area ? proj(labelPoint(area)) || [W / 2, H / 2] : proj(pt) || [W / 2, H / 2];
  const fills: Fill[] = area ? [{ area, color: kit.region, opacity: 0.92 * m.p(a0 + 14, 20, cubicOut), glow: 0.6 }] : [];
  return (
    <Root kit={kit} out={out} t={t}>
      {x < 1 ? <SatTiles cam={cam} us={us} W={W} H={H} /> : null}
      {x > 0 ? <MapCanvas cam={cam} kit={kit} opacity={x} layers={{ fills, inner: area?.a3 }} /> : null}
      {/* the swap: a soft light band sweeping across as the picture turns into the map */}
      {x > 0 && x < 1 ? <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
        background: `linear-gradient(100deg, rgba(255,255,255,0) ${x * 120 - 30}%, rgba(255,255,255,0.18) ${x * 120 - 12}%, rgba(255,255,255,0) ${x * 120}%)` }} /> : null}
      <Pill x={lp[0]} y={lp[1]} text={area ? nameOf(f0.ref, area) : shortName(place!.label)} kit={kit} u={u} p={m.p(a0 + 22, 14, cubicOut)}
        anchor="center" size={1.15} />
      <MapTitle text={o.text} kicker={str(o.label)} kit={kit} u={u} p={m.p(8, 18)} out={0} W={W} H={H} />
      <Vignette strength={0.5} />
      {sound}
    </Root>
  );
};

void joinBox; void geoContains; void quintOut; void areaBox;

export const LOOKS: Record<string, Look> = {
  "m2-zoom-dive": guard(ZoomDive),
  "m2-region-pulse": guard(RegionPulse),
  "m2-relief-tilt": guard(ReliefTilt),
  "m2-route": guard(Route),
  "m2-places": guard(Places),
  "m2-border-trace": guard(BorderTrace),
  "m2-choropleth": guard(Choropleth),
  "m2-compare": guard(Compare),
  "m2-radius": guard(Radius),
  "m2-flows": guard(Flows),
  "m2-pin-drop": guard(PinDrop),
  "m2-sat-flat": guard(SatFlat),
};
