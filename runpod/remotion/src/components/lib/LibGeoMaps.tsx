import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { feature } from "topojson-client";
import statesTopology from "../../data/us-states.json";
import type { GeoDoc, Overlay } from "../../types";
import { useLookSound } from "./LookSounds";
import {
  ANTON, SUBLINE, Grain, Vignette, backOut, clamp01, easeInOut, easeOut, exitOf, guard, heavy, hotOf, inOf,
  lerp, lift, rgba, textWidth, useBase, useSvgId, type Look,
} from "./proKit";

/**
 * AUTO MAPS (family "geo-"): what the narration names, drawn on real geography. The geometry is the plan's
 * (overlay.geo, built by src/automaps.py from the bundled Natural Earth / public-record geodata) - a look with
 * no geometry draws nothing. Graded imagery (USGS orthoimagery in the US, NASA Blue Marble elsewhere, the
 * tiles the satellite maps use) under a dark veil, the camera easing onto the feature, no boxes, no panels:
 *
 *   geo-river-trace   a river (or canal) draws from its source along its true course with a soft glow, the water
 *                     streaming down it, its name set along the line; dams the line named are pinned
 *   geo-reservoir     a lake or reservoir: its real outline draws and fills, the dam named is pinned with its
 *                     name, the river that feeds it runs faintly through
 *
 * Every frame is a pure function of the frame number (split renders on different machines match); a tile that
 * fails leaves its square dark and never fails the render.
 */

type Pt = [number, number];
type Geometry = { type: string; coordinates: unknown };
type Feat = { type: string; id?: string | number; geometry: Geometry | null };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };

const STATES = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features
  .filter((f) => { const id = Number(f.id); return Number.isFinite(id) && id <= 56 && id !== 2 && id !== 15; });

// ------------------------------------------------------------------ web mercator camera
const TILE = 256;
const DISPLAY = 1.5;
const GIBS_MAX = 8;
const USGS_MAX = 16;
const RAD = Math.PI / 180;
const WATER = "#59c9f5";
const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) => {
  const s = Math.sin(Math.max(-85, Math.min(85, lat)) * RAD);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};
interface Cam { mx: number; my: number; z: number }
const projector = (cam: Cam, unit: number, width: number, height: number) => {
  const s = TILE * 2 ** cam.z * unit;
  return (lon: number, lat: number): Pt => [width / 2 + (mercX(lon) - cam.mx) * s, height / 2 + (mercY(lat) - cam.my) * s];
};
const US_BOXES = [[18, 50, -126, -65], [51, 72, -170, -129], [18, 23, -161, -154]];
const inUS = (lon: number, lat: number) => US_BOXES.some(([a, b, c, d]) => lat >= a && lat <= b && lon >= c && lon <= d);
const usgsZoom = (z: number, us: boolean) => us && z > GIBS_MAX - 2;
const tileUrl = (z: number, x: number, y: number, us: boolean) => (usgsZoom(z, us)
  ? `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/${z}/${y}/${x}`
  : `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/${z}/${y}/${x}.jpeg`);

/** The imagery under a camera (as the pro maps do): USGS inside the US with a Blue Marble underlay for the sea. */
const Tiles: React.FC<{ cam: Cam; us: boolean; grade: string }> = ({ cam, us, grade }) => {
  const { kw, width, height } = useBase();
  const id = useSvgId("geot");
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
          <Img key={`${gibs ? "g" : "u"}${z}-${tx}-${ty}`} src={tileUrl(z, wx, ty, us && !gibs)} onError={() => undefined}
            maxRetries={3} delayRenderTimeoutInMilliseconds={60000}
            style={{ position: "absolute", left: width / 2 + (tx * TILE - cx) * scale, top: height / 2 + (ty * TILE - cy) * scale,
              width: Math.ceil(size) + 1, height: Math.ceil(size) + 1, opacity: o,
              filter: gibs ? `url(#${id}sea)` : usgsZoom(z, us) ? `url(#${id}nd)` : undefined }} />,
        );
      }
    }
    return out;
  };
  return (
    <AbsoluteFill style={{ background: "#0b1a2c", filter: grade }}>
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <filter id={`${id}nd`} colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  9 9 9 0 -0.1" />
        </filter>
        <filter id={`${id}sea`} colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  4 4 4 0 -0.4" />
        </filter>
      </svg>
      {under.flatMap((l) => layer(l, true))}
      {layers.flatMap((l) => layer(l, false))}
    </AbsoluteFill>
  );
};

/** The film grade: dark, cool and desaturated, so the line and the words carry the colour. */
const NIGHT = "saturate(0.55) brightness(0.52) contrast(1.18)";

// ------------------------------------------------------------------ plan: the camera for a geometry document
const geoOf = (ov: Overlay): GeoDoc | null => {
  const g = ov.geo;
  if (!g || !Array.isArray(g.bbox) || g.bbox.length !== 4 || g.bbox.some((v) => typeof v !== "number" || !Number.isFinite(v))) return null;
  const ok = (l: unknown) => Array.isArray(l) && l.length >= 2;
  const lines = (g.lines || []).filter(ok);
  const rings = (g.rings || []).filter(ok);
  const pins = (g.pins || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  if (!lines.length && !rings.length && !pins.length) return null;
  return { ...g, lines, rings, context: (g.context || []).filter(ok), pins };
};

/** The camera the document settles on: centred on its frame, zoomed so the frame fills the screen. */
export const geoCamera = (g: GeoDoc, width: number, height: number, kw: number, zCap: number) => {
  const [w, s, e, n] = g.bbox;
  const unit = DISPLAY * kw;
  const dx = Math.max(1e-7, mercX(e) - mercX(w));
  const dy = Math.max(1e-7, mercY(s) - mercY(n));
  const zFit = Math.log2(Math.min((width * 0.8) / (dx * TILE * unit), (height * 0.72) / (dy * TILE * unit)));
  const z = Math.max(2, Math.min(zCap, zFit));
  const us = inUS((w + e) / 2, (s + n) / 2);
  return { mx: (mercX(w) + mercX(e)) / 2, my: (mercY(s) + mercY(n)) / 2, z, us, unit };
};

const smoothPath = (pts: Pt[], close = false): string => {
  if (pts.length < 2) return "";
  const f = (p: Pt) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`;
  if (pts.length < 3) return `M${f(pts[0])} L${f(pts[1])}`;
  let d = `M${f(pts[0])}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const m: Pt = [(pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2];
    d += ` Q${f(pts[i])} ${f(i === pts.length - 2 && !close ? pts[i + 1] : m)}`;
  }
  return d + (close ? " Z" : "");
};

/** Cumulative length (mercator units) along lines laid end to end, and the prefix of them up to `len`. */
const lens = (lines: [number, number][][]) => lines.map((l) => {
  let t = 0;
  for (let i = 1; i < l.length; i++) t += Math.hypot(mercX(l[i][0]) - mercX(l[i - 1][0]), mercY(l[i][1]) - mercY(l[i - 1][1]));
  return t;
});
const prefix = (l: [number, number][], upTo: number): [number, number][] => {
  const out: [number, number][] = [l[0]];
  let t = 0;
  for (let i = 1; i < l.length; i++) {
    const seg = Math.hypot(mercX(l[i][0]) - mercX(l[i - 1][0]), mercY(l[i][1]) - mercY(l[i - 1][1]));
    if (t + seg >= upTo) {
      const q = seg > 0 ? (upTo - t) / seg : 0;
      out.push([lerp(l[i - 1][0], l[i][0], q), lerp(l[i - 1][1], l[i][1], q)]);
      return out;
    }
    t += seg;
    out.push(l[i]);
  }
  return out;
};

/** The state outlines, as faint context when the frame is wide. */
const States: React.FC<{ project: (lon: number, lat: number) => Pt; opacity: number }> = ({ project, opacity }) => {
  const { k } = useBase();
  if (opacity <= 0.01) return null;
  let d = "";
  for (const st of STATES) {
    const g = st.geometry;
    if (!g) continue;
    const polys = (g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? (g.coordinates as unknown[]) : []) as number[][][][];
    for (const poly of polys) for (const ring of poly) {
      d += `M${ring.map(([lon, lat]) => { const [x, y] = project(lon, lat); return `${x.toFixed(0)} ${y.toFixed(0)}`; }).join(" L")} `;
    }
  }
  return <path d={d} fill="none" stroke="rgba(190,210,235,.5)" strokeWidth={1.3 * k} opacity={opacity} />;
};

/** A pin: a white core in a ring, dropping in at `at`, with its name beside it and a soft halo (no box). */
const GeoPin: React.FC<{ x: number; y: number; label: string; at: number; accent: string; side?: 1 | -1 }> = ({ x, y, label, at, accent, side = 1 }) => {
  const { f, S, k, width } = useBase();
  const p = inOf(f, at * S, 14 * S, (t) => backOut(t, 2.0));
  if (p <= 0) return null;
  const text = label.toUpperCase();
  const size = 30 * k;
  const w = textWidth(text, SUBLINE, size, 700, 0.16);
  const right = side === 1 ? x + 30 * k + w < width - 60 * k : false;
  return (
    <g opacity={clamp01(p * 1.5)}>
      <circle cx={x} cy={y} r={(15 + 20 * (1 - clamp01(p))) * k} fill="rgba(8,10,14,.5)" stroke={accent} strokeWidth={3.5 * k}
        style={{ filter: `drop-shadow(0 0 ${9 * k}px ${rgba(accent, 0.8)})` }} />
      <circle cx={x} cy={y} r={5.5 * k * p} fill="#fff" />
      <text x={right ? x + 28 * k : x - 28 * k} y={y + size * 0.36} textAnchor={right ? "start" : "end"} fontFamily={SUBLINE} fontWeight={700}
        fontSize={size} letterSpacing={`${0.16 * size}px`} fill="#fff" stroke="rgba(0,0,0,.75)" strokeWidth={5 * k} paintOrder="stroke"
        strokeLinejoin="round">{text}</text>
    </g>
  );
};

// ================================================================== geo-river-trace
const RIVER = { push: 38, drawAt: 10, drawFrames: 56 };

const RiverTrace: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("geor");
  const g = geoOf(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(g ? [
    { name: "whoosh-soft-v2", alt: ["swoosh-text", "whoosh-soft"], at: 6, gain_db: -10 },
    { name: "ui-pop", alt: ["pop", "ui-tick"], at: 36, gain_db: -9 },
  ] : []);
  if (!g || !(g.lines || []).length) return null;
  const lines = g.lines as [number, number][][];
  const end = geoCamera(g, width, height, kw, 8.6);
  const push = inOf(f, 0, RIVER.push * S, easeInOut);
  const z = lerp(end.z - 0.85, end.z, push) + 0.07 * clamp01(f / Math.max(1, dur));
  const cam: Cam = { mx: end.mx, my: end.my, z };
  const project = projector(cam, end.unit, width, height);
  const finalProject = projector({ mx: end.mx, my: end.my, z: end.z }, end.unit, width, height);

  const canal = g.kind === "canal";
  const total = lens(lines);
  const sum = total.reduce((a, b) => a + b, 0) || 1;
  const draw = inOf(f, RIVER.drawAt * S, RIVER.drawFrames * S, easeInOut);
  let left = draw * sum;
  const drawn: [number, number][][] = [];
  let head: Pt | null = null;
  lines.forEach((l, i) => {
    if (left <= 0) return;
    const part = prefix(l, Math.min(total[i], left));
    left -= total[i];
    if (part.length >= 2) {
      drawn.push(part);
      const last = part[part.length - 1];
      head = project(last[0], last[1]);
    }
  });
  const paths = drawn.map((l) => smoothPath(l.map(([lon, lat]) => project(lon, lat))));

  // The label sits on the straightest stretch of the main line, chosen on the final camera so it never hops.
  const main = lines.reduce((a, b, i, all) => (total[all.indexOf(a)] >= total[i] ? a : b), lines[0]);
  const labelSize = 34 * k;
  const label = (g.label || g.name || "").toUpperCase();
  const lw = textWidth(label, SUBLINE, labelSize, 700, 0.3) * 1.08;
  const pxs = main.map(([lon, lat]) => finalProject(lon, lat));
  const cum: number[] = [0];
  for (let i = 1; i < pxs.length; i++) cum.push(cum[i - 1] + Math.hypot(pxs[i][0] - pxs[i - 1][0], pxs[i][1] - pxs[i - 1][1]));
  let best = { i0: 0, i1: Math.min(1, pxs.length - 1), score: 1e18 };
  const onScreen = (p: Pt) => p[0] > width * 0.1 && p[0] < width * 0.9 && p[1] > height * 0.14 && p[1] < height * 0.86;
  for (let i0 = 0; i0 < pxs.length - 1; i0++) {
    let i1 = i0 + 1;
    while (i1 < pxs.length - 1 && cum[i1] - cum[i0] < lw) i1++;
    if (cum[i1] - cum[i0] < lw * 0.9) break;
    const a = pxs[i0];
    const b = pxs[i1];
    if (![a, b, pxs[(i0 + i1) >> 1]].every(onScreen)) continue;
    let turn = 0;
    for (let i = i0 + 1; i < i1; i++) {
      const a1 = Math.atan2(pxs[i][1] - pxs[i - 1][1], pxs[i][0] - pxs[i - 1][0]);
      const a2 = Math.atan2(pxs[i + 1][1] - pxs[i][1], pxs[i + 1][0] - pxs[i][0]);
      let d = Math.abs(a2 - a1);
      if (d > Math.PI) d = 2 * Math.PI - d;
      turn += d;
    }
    const slope = Math.abs(Math.atan2(b[1] - a[1], b[0] - a[0]));
    const steep = Math.min(slope, Math.PI - slope);
    const score = turn + steep * 1.2 - (cum[i1] - cum[i0]) / (lw * 40);
    if (score < best.score) best = { i0, i1, score };
  }
  const haveLabel = best.score < 1e17 && label.length > 0;
  let labelPath = "";
  let labelAt = 40;
  if (haveLabel) {
    const win = main.slice(best.i0, best.i1 + 1).map(([lon, lat]) => project(lon, lat));
    // smooth the window (a moving average) and read it left to right
    const sm = win.map((p, i) => {
      const a = win[Math.max(0, i - 2)];
      const b = win[Math.min(win.length - 1, i + 2)];
      return [(a[0] + p[0] + b[0]) / 3, (a[1] + p[1] + b[1]) / 3] as Pt;
    });
    if (sm[sm.length - 1][0] < sm[0][0]) sm.reverse();
    labelPath = smoothPath(sm);
    // the label appears once the drawing has passed the middle of its stretch
    let along = 0;
    for (let i = 0; i < lines.length && lines[i] !== main; i++) along += total[i];
    const midIdx = (best.i0 + best.i1) >> 1;
    let t = 0;
    for (let i = 1; i <= midIdx; i++) t += Math.hypot(mercX(main[i][0]) - mercX(main[i - 1][0]), mercY(main[i][1]) - mercY(main[i - 1][1]));
    const reached = (along + t) / sum;
    // the frame at which the eased draw has covered that share of the line
    let lo = 0;
    let hi = 1;
    for (let n = 0; n < 24; n++) {
      const mid = (lo + hi) / 2;
      if (easeInOut(mid) < reached) lo = mid; else hi = mid;
    }
    labelAt = Math.max(30, RIVER.drawAt + RIVER.drawFrames * hi + 4);
  }
  const labelP = inOf(f, labelAt * S, 16 * S, easeOut);
  const settled = draw >= 1;
  const flow = !!g.flow && !canal;
  const pins = (g.pins || []).map((p) => ({ ...p, xy: project(p.lon, p.lat) }));
  const wide = clamp01((7.4 - z) / 1.2);

  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Tiles cam={cam} us={end.us} grade={NIGHT} />
        <Vignette strength={0.6} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <filter id={`${id}g`} x="-10%" y="-10%" width="120%" height="120%">
              <feGaussianBlur stdDeviation={7 * k} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            {haveLabel ? <path id={`${id}lp`} d={labelPath} /> : null}
          </defs>
          <States project={project} opacity={0.35 * wide * clamp01(f / (10 * S))} />
          {paths.map((d, i) => (
            <g key={i}>
              <path d={d} fill="none" stroke="rgba(0,0,0,.55)" strokeWidth={13 * k} strokeLinecap="round" strokeLinejoin="round" />
              <path d={d} fill="none" stroke={hot} strokeWidth={(canal ? 5 : 7) * k} strokeLinecap="round" strokeLinejoin="round"
                strokeDasharray={canal ? `${16 * k} ${11 * k}` : undefined} opacity={canal ? 0.95 : 1} filter={`url(#${id}g)`} />
              {canal ? null : <path d={d} fill="none" stroke="rgba(255,255,255,.88)" strokeWidth={2.2 * k} strokeLinecap="round"
                strokeLinejoin="round" />}
              {flow && settled ? <path d={d} fill="none" stroke="#fff" strokeWidth={3.4 * k} strokeLinecap="round"
                strokeDasharray={`${5 * k} ${46 * k}`} strokeDashoffset={-((f - (RIVER.drawAt + RIVER.drawFrames) * S) * 2.6 * k)}
                opacity={0.8 * clamp01((f - (RIVER.drawAt + RIVER.drawFrames) * S) / (10 * S))} /> : null}
            </g>
          ))}
          {head && !settled && draw > 0 ? <circle cx={(head as Pt)[0]} cy={(head as Pt)[1]} r={9 * k} fill="#fff"
            style={{ filter: `drop-shadow(0 0 ${12 * k}px ${hot})` }} /> : null}
          {haveLabel ? (
            <text fontFamily={SUBLINE} fontWeight={700} fontSize={labelSize} letterSpacing={`${0.3 * labelSize}px`} fill="#fff"
              stroke="rgba(0,0,0,.8)" strokeWidth={6 * k} paintOrder="stroke" strokeLinejoin="round" opacity={labelP}>
              <textPath href={`#${id}lp`} startOffset="50%" textAnchor="middle">
                <tspan dy={-16 * k}>{label}</tspan>
              </textPath>
            </text>
          ) : null}
          {pins.map((p, i) => <GeoPin key={i} x={p.xy[0]} y={p.xy[1]} label={p.label} at={RIVER.drawAt + 26 + i * 6} accent={hot}
            side={p.xy[0] > width * 0.62 ? -1 : 1} />)}
        </svg>
      </AbsoluteFill>
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

// ================================================================== geo-reservoir
const RES = { push: 40, outlineAt: 12, outlineFrames: 30, fillAt: 38, pin: 40, name: 48 };

const Reservoir: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("geol");
  const g = geoOf(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(g ? [
    { name: "whoosh-soft-v2", alt: ["swoosh-text", "whoosh-soft"], at: 6, gain_db: -10 },
    { name: "pin-drop", alt: ["ui-pop", "pop"], at: RES.pin, gain_db: -8 },
  ] : []);
  if (!g) return null;
  const rings = (g.rings || []) as [number, number][][];
  const context = (g.context || []) as [number, number][][];
  const pins = g.pins || [];
  const end = geoCamera(g, width, height, kw, rings.length ? 10.4 : 9.6);
  const push = inOf(f, 0, RES.push * S, easeInOut);
  const z = lerp(end.z - 1.15, end.z, push) + 0.06 * clamp01(f / Math.max(1, dur));
  const cam: Cam = { mx: end.mx, my: end.my, z };
  const project = projector(cam, end.unit, width, height);
  const outline = inOf(f, RES.outlineAt * S, RES.outlineFrames * S, easeInOut);
  const fill = inOf(f, RES.fillAt * S, 22 * S, easeOut);
  const ringD = rings.map((r) => smoothPath(r.map(([lon, lat]) => project(lon, lat)), true));
  const ctxD = context.map((l) => smoothPath(l.map(([lon, lat]) => project(lon, lat))));
  const px = pins.map((p) => ({ ...p, xy: project(p.lon, p.lat) }));
  // The lake's name: above the middle of its outline, beside the pin for a dam alone.
  const pts = rings.flat();
  const cx = pts.length ? pts.reduce((a, p) => a + p[0], 0) / pts.length : g.bbox[0] / 2 + g.bbox[2] / 2;
  const cy = pts.length ? pts.reduce((a, p) => a + p[1], 0) / pts.length : g.bbox[1] / 2 + g.bbox[3] / 2;
  const [nx, ny] = project(cx, cy);
  const nameP = inOf(f, RES.name * S, 16 * S, easeOut);
  const title = (g.label || g.name || "").toUpperCase();
  const size = Math.min(70 * k, (width * 0.7) / Math.max(6, title.length) * 1.7);
  const showTitle = rings.length > 0 && title.length > 0;
  const wide = clamp01((7.4 - z) / 1.2);

  return (
    <AbsoluteFill style={{ background: "#05080d" }}>
      {sound}
      <AbsoluteFill style={{ opacity: 1 - out }}>
        <Tiles cam={cam} us={end.us} grade={NIGHT} />
        <Vignette strength={0.6} />
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <filter id={`${id}g`} x="-10%" y="-10%" width="120%" height="120%">
              <feGaussianBlur stdDeviation={6 * k} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <States project={project} opacity={0.35 * wide * clamp01(f / (10 * S))} />
          {ctxD.map((d, i) => (
            <path key={`c${i}`} d={d} fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={2.4 * k} strokeLinecap="round"
              strokeLinejoin="round" opacity={clamp01(f / (14 * S)) * 0.85} />
          ))}
          {ringD.map((d, i) => (
            <g key={`r${i}`}>
              <path d={d} fill={rgba(WATER, 0.34 * fill)} stroke="none" />
              <path d={d} fill="none" stroke={WATER} strokeWidth={4 * k} strokeLinejoin="round" pathLength={1}
                strokeDasharray="1 1" strokeDashoffset={1 - outline} filter={`url(#${id}g)`} />
              <path d={d} fill="none" stroke="rgba(255,255,255,.85)" strokeWidth={1.8 * k} strokeLinejoin="round" pathLength={1}
                strokeDasharray="1 1" strokeDashoffset={1 - outline} />
            </g>
          ))}
          {px.map((p, i) => <GeoPin key={i} x={p.xy[0]} y={p.xy[1]} label={p.label} at={RES.pin + i * 6} accent={hot}
            side={p.xy[0] > width * 0.62 ? -1 : 1} />)}
          {showTitle ? (
            <text x={nx} y={ny - Math.max(8 * k, size * 0.2)} textAnchor="middle" fontFamily={ANTON} fontSize={size} letterSpacing={`${0.06 * size}px`}
              fill="#fff" stroke="rgba(0,0,0,.7)" strokeWidth={7 * k} paintOrder="stroke" strokeLinejoin="round" opacity={nameP}
              transform={`translate(0 ${((1 - nameP) * 10 * k).toFixed(1)})`}>{title}</text>
          ) : null}
        </svg>
        {!showTitle && title ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: height * 0.1, textAlign: "center", opacity: nameP,
            ...heavy(Math.min(66 * k, size), "#fff", 0.06), textShadow: lift(k, 0.8) }}>{title}</div>
        ) : null}
      </AbsoluteFill>
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "geo-river-trace": guard(RiverTrace),
  "geo-reservoir": guard(Reservoir),
};
