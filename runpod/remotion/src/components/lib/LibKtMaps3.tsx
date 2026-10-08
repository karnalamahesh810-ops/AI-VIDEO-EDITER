import React from "react";
import { AbsoluteFill } from "remotion";
import { geoCentroid, geoContains, geoGraticule, geoMercator, geoPath } from "d3-geo";
import { GROTESK, GROTESK_CAP, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicInOut, cubicOut, expoOut, idle, lerp, prog } from "../motion/ease";
import { Grain, guard, hash, rgba, useSvgId, type Look } from "./proKit";
import { countText, distanceText, figureOf, milesBetween, num, placeName, placesOf, str, unitOf as unitWord } from "./proFormat";
import { SOFT_WHITE, WHITE, softShadow, widthOf } from "./typeKit";
import { useLook } from "./LibKinetic";
import { Caps, DIM, Glass, RiseLine, capsWidth, riseWidth } from "./LibKtDates";
import { STATES, WORLD, inUS, type Feat } from "./LibKtMaps";
import { useLookSound } from "./LookSounds";
import { placeRect, rect, type Rect } from "./annoKit";
import scale from "./typeScale.json";

/**
 * LOOKS PACK 3, its maps (2026-10-08; LibKtPack3.tsx has the data on the footage). The places come from the
 * gazetteer's coordinates only (overlay.locations: src/geocode.py, never a model's guess) or, for the states,
 * their names; drawn on the bundled outlines (the US states, else the world's countries) in the dark map of
 * the locator (LibKtMaps.tsx) - no tiles, no network, nothing that can stop a render:
 *
 *   kt-route    ROUTE         two to six places in order: the camera starts close on the first and eases out as
 *                             a line draws from stop to stop with a bright head - reaching each stop on its word
 *                             (items[].at), the stop ringing and its name opening on glass - the distance (as
 *                             said, else the straight-line miles) counting in a tag; then water-like light flows
 *                             along it
 *   kt-storm    STORM TRACK   a storm's path: the forecast cone widening along it, the storm (a turning spiral,
 *                             the way storms turn in that hemisphere) travelling the track, each position's time
 *                             as said opening as it passes, the storm's name and strength on a glass tag
 *   kt-totals   TOTALS MAP    values by place (rain, snow, heat, wind): each place's value opening on glass over
 *                             its dot on its word, counting; once all are in, the highest takes the accent
 *   kt-regions  STATES        the states (or countries) a line names: each lights up as it is said - its face
 *                             filling with the accent, its outline drawing, its name rising - while a counter
 *                             counts them
 *
 * The owner, 2026-10-05: zoom-ins with circles and rings, smooth eased motion; the type system of every kt-
 * look (white bold grotesk, one accent, glass).
 */

const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
const capFont = (sh: number, U: number, ks: number, cap = GROTESK_CAP) => (sh * U * ks) / cap;
type P3 = Record<string, { share?: number }>;
const PACK3 = (scale as unknown as { pack3: P3 }).pack3;
const share = (key: string) => PACK3[key]?.share ?? 0.02;
const saidAt = (at: number | null, fallback: number) => (at !== null && Number.isFinite(at) && at >= 0
  ? Math.max(2, at * 30 - 1) : fallback);

type XY = [number, number];

// ------------------------------------------------------------------ geometry
/** A smooth curve through points (Catmull-Rom as cubic Béziers), `per` samples a segment; stop i is sample i*per. */
const throughPoints = (pts: XY[], per = 18): XY[] => {
  if (pts.length < 2) return pts.slice();
  const out: XY[] = [pts[0]];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1: XY = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2: XY = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    for (let s = 1; s <= per; s++) {
      const t = s / per, u = 1 - t;
      out.push([u * u * u * p1[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * p2[0],
        u * u * u * p1[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * p2[1]]);
    }
  }
  return out;
};
/** Two places joined by a gentle bow (a straight line reads as a ruler, not a journey). */
const bowed = (a: XY, b: XY, bow: number, per = 36): XY[] => {
  const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const c: XY = [mx - (dy / len) * bow * len, my + (dx / len) * bow * len];
  return Array.from({ length: per + 1 }, (_v, i) => {
    const t = i / per, u = 1 - t;
    return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]] as XY;
  });
};
const cumulative = (poly: XY[]): number[] => {
  const out = [0];
  for (let i = 1; i < poly.length; i++) out.push(out[i - 1] + Math.hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1]));
  return out;
};
/** The point `frac` of the way along a polyline, and its heading (radians). */
const along = (poly: XY[], cum: number[], frac: number): { p: XY; a: number } => {
  const total = cum[cum.length - 1] || 1;
  const want = clamp01(frac) * total;
  let i = 1;
  while (i < cum.length - 1 && cum[i] < want) i++;
  const a = poly[i - 1], b = poly[i];
  const seg = Math.max(1e-9, cum[i] - cum[i - 1]);
  const u = clamp01((want - cum[i - 1]) / seg);
  return { p: [lerp(a[0], b[0], u), lerp(a[1], b[1], u)], a: Math.atan2(b[1] - a[1], b[0] - a[0]) };
};
const polyD = (poly: XY[]) => poly.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
/** The polyline up to `frac` of its length. */
const upTo = (poly: XY[], cum: number[], frac: number): XY[] => {
  const total = cum[cum.length - 1] || 1;
  const want = clamp01(frac) * total;
  const out: XY[] = [poly[0]];
  for (let i = 1; i < poly.length; i++) {
    if (cum[i] <= want) out.push(poly[i]);
    else {
      out.push(along(poly, cum, frac).p);
      break;
    }
  }
  return out;
};

/** A Mercator projection framing the points in `box`, never closer than `minDeg` degrees of latitude across. */
const framing = (pts: XY[], box: [XY, XY], minDeg = 2.2) => {
  const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
  const cx = (Math.min(...lons) + Math.max(...lons)) / 2, cy = (Math.min(...lats) + Math.max(...lats)) / 2;
  const hy = Math.max((Math.max(...lats) - Math.min(...lats)) / 2, minDeg / 2);
  const hx = Math.max((Math.max(...lons) - Math.min(...lons)) / 2, (minDeg / 2) / Math.max(0.25, Math.cos((cy * Math.PI) / 180)));
  const mp = { type: "MultiPoint", coordinates: [[cx - hx, cy - hy], [cx + hx, cy + hy], ...pts] };
  return geoMercator().fitExtent(box as never, mp as never);
};

/** The camera: the map point under the frame's centre (m) and the zoom (z) over the fitted map. */
interface Cam { z: number; m: XY }
const onScreen = (p: XY, cam: Cam, C: XY): XY => [(p[0] - cam.m[0]) * cam.z + C[0], (p[1] - cam.m[1]) * cam.z + C[1]];

// ------------------------------------------------------------------ the dark map
/**
 * The dark map every pack-3 map stands on (the locator's palette): the land, its borders, a faint graticule,
 * moved by the camera as one layer (strokes keep their width); `lit` gives a feature's highlight 0..1 (its face
 * toward the accent, a glow and a white edge drawing on).
 */
const DarkMap: React.FC<{ geo: Feat[]; path: (g: Feat) => string; grat: string; cam: Cam; C: XY; W: number; H: number;
  k: number; hot: string; o: number; lit?: (g: Feat) => number; home?: Set<Feat>; homeP?: number; glowId: string }> =
  ({ geo, path, grat, cam, C, W, H, k, hot, o, lit, home, homeP = 1, glowId }) => (
    <AbsoluteFill style={{ opacity: o, background: "radial-gradient(ellipse 90% 80% at 45% 50%, #0a1018 0%, #05080d 62%, #030407 100%)" }}>
      <AbsoluteFill style={{ transformOrigin: "0 0",
        transform: `translate(${C[0].toFixed(1)}px, ${C[1].toFixed(1)}px) scale(${cam.z.toFixed(5)}) translate(${(-cam.m[0]).toFixed(1)}px, ${(-cam.m[1]).toFixed(1)}px)` }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <filter id={glowId} x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation={7} /></filter>
          </defs>
          <path d={grat} fill="none" stroke="rgba(150,175,205,0.07)" strokeWidth={1.2 * k} vectorEffect="non-scaling-stroke" />
          {geo.map((g, i) => {
            const l = lit ? lit(g) : 0;
            const h = home && home.has(g) ? homeP : 0;
            const v = Math.max(l, h * 0.7);
            return <path key={`f${i}`} d={path(g)} fill={v > 0 ? `rgb(${Math.round(lerp(23, 36, v))},${Math.round(lerp(34, 53, v))},${Math.round(lerp(49, 78, v))})` : "#172231"} />;
          })}
          {lit ? geo.map((g, i) => {
            const l = lit(g);
            return l > 0 ? <path key={`t${i}`} d={path(g)} fill={rgba(hot, 0.13 * l)} /> : null;
          }) : null}
          {geo.map((g, i) => {
            const l = Math.max(lit ? lit(g) : 0, home && home.has(g) ? homeP * 0.55 : 0);
            return l > 0 ? <path key={`g${i}`} d={path(g)} fill="none" stroke={rgba(hot, 0.5 * l)} strokeWidth={9 * k}
              vectorEffect="non-scaling-stroke" filter={`url(#${glowId})`} /> : null;
          })}
          {geo.map((g, i) => <path key={`s${i}`} d={path(g)} fill="none" stroke="#4f6480" strokeWidth={1.4 * k}
            vectorEffect="non-scaling-stroke" />)}
          {geo.map((g, i) => {
            const l = lit ? lit(g) : 0;
            const h = home && home.has(g) ? homeP : 0;
            if (l > 0) {
              return <path key={`e${i}`} d={path(g)} fill="none" stroke={rgba(hot, 0.95)} strokeWidth={2.4 * k}
                vectorEffect="non-scaling-stroke" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - l} />;
            }
            return h > 0 ? <path key={`e${i}`} d={path(g)} fill="none" stroke={rgba(hot, 0.55 * h)} strokeWidth={1.8 * k}
              vectorEffect="non-scaling-stroke" /> : null;
          })}
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );

/**
 * The names of the land round the marks, faint and widely tracked (the locator's), each at its middle when that
 * is on screen and clear of the marks and the tags (`blockers`).
 */
const MapNames: React.FC<{ geo: Feat[]; proj: (p: [number, number]) => [number, number] | null; cam: Cam; C: XY; W: number;
  H: number; k: number; size: number; o: number; blockers: Rect[]; skip?: Set<Feat> }> =
  ({ geo, proj, cam, C, W, H, k, size, o, blockers, skip }) => {
    if (o <= 0.01) return null;
    const placed: Rect[] = [];
    return (
      <AbsoluteFill style={{ opacity: o, pointerEvents: "none" }}>
        {geo.map((g, i) => {
          if (skip && skip.has(g)) return null;
          let c: XY | null = null;
          try {
            c = proj(geoCentroid(g as never) as [number, number]) as XY | null;
          } catch {
            c = null;
          }
          if (!c) return null;
          const p = onScreen(c, cam, C);
          const name = String(g.properties?.name || "").toUpperCase();
          if (!name || p[0] < 0.07 * W || p[0] > 0.93 * W || p[1] < 0.08 * H || p[1] > 0.92 * H) return null;
          const w = widthOf(name, SUBLINE, size, 700, 0.3);
          const r = rect(p[0] - w / 2 - 10 * k, p[1] - size, w + 20 * k, size * 2);
          if ([...blockers, ...placed].some((b) => r.x < b.x + b.w && r.x + r.w > b.x && r.y < b.y + b.h && r.y + r.h > b.y)) return null;
          placed.push(r);
          return (
            <div key={i} style={{ position: "absolute", left: p[0], top: p[1], transform: "translate(-50%, -50%)", fontFamily: SUBLINE,
              fontWeight: 700, fontSize: size, letterSpacing: "0.3em", color: "rgba(196,210,228,0.62)", whiteSpace: "nowrap" }}>{name}</div>
          );
        })}
      </AbsoluteFill>
    );
  };

/** The outlines the places are in (their states, else their countries). */
const homesOf = (geo: Feat[], pts: [number, number][]): Set<Feat> => {
  const out = new Set<Feat>();
  for (const p of pts) {
    for (const g of geo) {
      try {
        if (geoContains(g as never, p)) {
          out.add(g);
          break;
        }
      } catch {
        // a malformed outline: skip it
      }
    }
  }
  return out;
};

/**
 * Where a name sits wholly inside its own outline (a centroid label can cross a border: CALIFORNIA's centre sits
 * near Nevada): the nearest spot around the centroid where the label's corners and edge middles all fall inside
 * the shape, else the spot with the most of them inside. In the map's own (camera-free) projection; kept per
 * outline, label size and framing, so it is worked out once, not every frame.
 */
const LABEL_SPOT = new Map<string, XY>();
const labelSpot = (g: Feat, key: string, proj: { (p: [number, number]): [number, number] | null;
  invert?: (p: [number, number]) => [number, number] | null }, w: number, h: number): XY | null => {
  const hit = LABEL_SPOT.get(key);
  if (hit) return hit;
  const c = proj(geoCentroid(g as never) as [number, number]);
  if (!c) return null;
  const inside = (x: number, y: number) => {
    const ll = proj.invert ? proj.invert([x, y]) : null;
    if (!ll) return false;
    try {
      return geoContains(g as never, ll);
    } catch {
      return false;
    }
  };
  const probes = (x: number, y: number) => [[-0.5, -0.5], [0, -0.5], [0.5, -0.5], [0.5, 0], [0.5, 0.5], [0, 0.5], [-0.5, 0.5], [-0.5, 0]]
    .reduce((n, [u, v]) => n + (inside(x + u * w, y + v * h) ? 1 : 0), 0);
  const steps: XY[] = [];
  for (const dy of [0, -0.6, 0.6, -1.2, 1.2, -1.8, 1.8, -2.6, 2.6]) {
    for (const dx of [0, -0.15, 0.15, -0.3, 0.3, -0.45, 0.45, -0.6, 0.6]) steps.push([dx * w, dy * h]);
  }
  steps.sort((a, b) => Math.hypot(a[0], a[1] * 1.6) - Math.hypot(b[0], b[1] * 1.6));
  let best: XY = c, bestN = -1;
  for (const [dx, dy] of steps) {
    const n = probes(c[0] + dx, c[1] + dy);
    if (n > bestN) {
      best = [c[0] + dx, c[1] + dy];
      bestN = n;
      if (n === 8) break;
    }
  }
  if (LABEL_SPOT.size > 400) LABEL_SPOT.clear();
  LABEL_SPOT.set(key, best);
  return best;
};

/** The finish over every map: a fine static grain and a soft vignette. */
const Finish: React.FC = () => (
  <>
    <Grain opacity={0.05} />
    <AbsoluteFill style={{ pointerEvents: "none", background: "radial-gradient(ellipse 75% 70% at 45% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.5) 100%)" }} />
  </>
);

/** A glass title tag top left: the kicker in the accent, the title rising, an optional line under it. */
const TitleTag: React.FC<{ kicker: string; title: string; sub?: string; U: number; ks: number; k: number; W: number; H: number;
  hot: string; at: number; out: number; f: number; S: number }> = ({ kicker, title, sub, U, ks, k, W, H, hot, at, out, f, S }) => {
  if (!kicker && !title) return null;
  const kSize = capFont(share("kicker"), U, ks);
  let tSize = capFont(share("mapTitle"), U, ks);
  const sSize = capFont(share("small"), U, ks);
  const up = title.toUpperCase();
  while (title && tSize > capFont(share("mapTitle"), U, ks) * 0.74 && riseWidth(up, GROTESK, tSize, 800, 0.01) > 0.4 * W) tSize *= 0.96;
  const padX = 22 * k, padY = 16 * k;
  const w = Math.max(title ? riseWidth(up, GROTESK, tSize, 800, 0.01) : 0, kicker ? capsWidth(kicker, kSize) : 0,
    sub ? capsWidth(sub, sSize, 0.14) : 0) + padX * 2;
  const h = padY * 2 + (kicker ? kSize : 0) + (kicker && title ? 0.3 * tSize : 0) + (title ? tSize * 1.2 : 0) + (sub ? 10 * k + sSize : 0);
  return (
    <Glass x={0.068 * W} y={0.09 * H} w={w} h={h} k={k} p={prog(f, at, 16, S, expoOut)} out={out} radius={14}>
      <div style={{ position: "absolute", left: padX, top: padY }}>
        {kicker ? (
          <div style={{ height: kSize, marginBottom: title ? 0.3 * tSize : 0 }}>
            <Caps text={kicker} size={kSize} color={hot} at={at + 3} out={out} k={k} />
          </div>
        ) : null}
        {title ? <RiseLine text={up} size={tSize} font={GROTESK} weight={800} at={at + 5} out={out} k={k} tracking={0.01} /> : null}
        {sub ? (
          <div style={{ height: sSize, marginTop: 10 * k }}>
            <Caps text={sub} size={sSize} color="rgba(250,250,247,0.82)" at={at + 10} out={out} k={k} tracking={0.14} />
          </div>
        ) : null}
      </div>
    </Glass>
  );
};

/** Where a label goes round its point: the first of eight spots clear of the blockers and the frame's margin. */
const spotFor = (P: XY, w: number, h: number, gap: number, blockers: Rect[], W: number, H: number, prefer = 0): Rect => {
  const spots: XY[] = [[1, -1], [1, 0], [1, 1], [-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1]];
  const rot = spots.slice(prefer % spots.length).concat(spots.slice(0, prefer % spots.length));
  const cands = rot.map(([dx, dy]) => {
    const x = dx > 0 ? P[0] + gap : dx < 0 ? P[0] - gap - w : P[0] - w / 2;
    const y = dy > 0 ? P[1] + gap * 0.6 : dy < 0 ? P[1] - gap * 0.6 - h : P[1] - h / 2;
    return rect(x, y, w, h);
  });
  return placeRect(cands, blockers, W, H, 0.05 * W, 6);
};

/** Blockers for labels: little boxes along a screen polyline (every few samples). */
const lineBlocks = (poly: XY[], r: number, every = 3): Rect[] => poly.filter((_p, i) => i % every === 0)
  .map((p) => rect(p[0] - r, p[1] - r, r * 2, r * 2));

// ================================================================== kt-route
/**
 * Two to six places in order (a river's course, a canal, a supply route, an evacuation route), on the dark
 * map framed on all of them. The camera starts close on the first stop - its dot and its name already there -
 * and eases out as the route draws from stop to stop in the accent with a soft glow and a bright head; the
 * head reaches each stop on its word (items[].at; else at an even pace over 26-84 frames): the stop's ring
 * draws and pings once and its name opens on glass beside it. A glass tag counts the distance with the head
 * (the distance as said, else the straight-line miles between the stops). Then light flows along the route
 * while it holds.
 */
const Route: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const glowId = useSvgId("ktrtglow");
  const stops = placesOf(overlay.locations, 6);
  const n = stops.length;
  const given = Array.isArray(overlay.items) ? overlay.items : [];
  const C: XY = [W / 2, H / 2];
  const geo = n >= 2 ? (stops.every(inUS) ? STATES : WORLD) : [];
  const proj = n >= 2 ? framing(stops.map((s) => [s.lon, s.lat] as XY), [[0.14 * W, 0.2 * H], [0.86 * W, 0.84 * H]]) : null;
  const base: XY[] = proj ? stops.map((s) => proj([s.lon, s.lat]) as XY) : [];
  const per = 18;
  const poly = n === 2 ? bowed(base[0], base[1], (hash(`${stops[0].label}|${stops[1].label}`) % 2 ? 1 : -1) * 0.14, 36)
    : n > 2 ? throughPoints(base, per) : [];
  const cum = poly.length ? cumulative(poly) : [0];
  const total = cum[cum.length - 1] || 1;
  const stopFrac = base.map((_p, i) => (n === 2 ? i : (cum[Math.min(cum.length - 1, i * per)] || 0) / total));
  const t0 = 12;
  const L = Math.min(84, 26 + 16 * (n - 1));
  const arrive: number[] = base.map((_p, i) => {
    if (i === 0) return t0;
    const at = num((given[i] as { at?: unknown } | undefined)?.at);
    return saidAt(at, t0 + L * stopFrac[i]);
  });
  for (let i = 1; i < n; i++) arrive[i] = Math.max(arrive[i], arrive[i - 1] + 10);
  const sound = useLookSound(n >= 2 ? [{ name: "map-swoop", alt: ["whoosh-soft-v2", "whoosh-soft"], at: 0, gain_db: -12 },
    ...arrive.slice(1).map((a) => ({ name: "pin-drop", alt: ["ui-pop", "pop"], at: Math.round(a), gain_db: -11 }))] : null);
  if (n < 2 || !proj) return null;
  const path = geoPath(proj as never);
  const t = f / S;
  // the head: between two stops on their own ease, holding a beat on each
  let frac = 0;
  if (t >= arrive[n - 1]) frac = 1;
  else if (t > arrive[0]) {
    let i = 0;
    while (i < n - 2 && t >= arrive[i + 1]) i++;
    const u = cubicInOut(clamp01((t - arrive[i]) / Math.max(1, arrive[i + 1] - arrive[i])));
    frac = lerp(stopFrac[i], stopFrac[i + 1], u);
  }
  const drawn = arrive[n - 1];
  // the camera: close on the first stop, out to the whole route as it draws, then a slow creep
  const camP = prog(f, 4, Math.max(20, drawn - 4), S, cubicInOut);
  const z0 = 1.42;
  const creep = 1 + 0.03 * idle(f, drawn * S, dur);
  const cam: Cam = { z: Math.exp(lerp(Math.log(z0), 0, camP)) * creep, m: [lerp(base[0][0], C[0], camP), lerp(base[0][1], C[1], camP)] };
  const scr = poly.map((p) => onScreen(p, cam, C));
  const pts = base.map((p) => onScreen(p, cam, C));
  const U = unitOf(W, H);
  const xo = 1 - clamp01(out * 1.4);
  const o = prog(f, 0, 10, S, cubicOut) * (1 - clamp01(out * 1.2));
  const head = along(scr, cum.map((c) => c * cam.z), frac).p;
  const lineW = Math.max(3.5, 5.2 * k);
  // labels: each stop's name on glass, on the side clear of the route (chosen once, on the landed framing)
  const nSize = capFont(share("stopName"), U, ks);
  const names = stops.map((s, i) => (str((given[i] as { label?: unknown } | undefined)?.label) || placeName(s.label).name || s.label)
    .toUpperCase());
  const finalCam: Cam = { z: 1, m: C };
  const finalScr = poly.map((p) => onScreen(p, finalCam, C));
  const placed: Rect[] = [];
  const blocks = [...lineBlocks(finalScr, 14 * k), ...base.map((p) => rect(p[0] - 16 * k, p[1] - 16 * k, 32 * k, 32 * k)),
    rect(0, 0, 0.5 * W, 0.24 * H), rect(0, 0.78 * H, 0.42 * W, 0.22 * H)];
  const chipW = names.map((nm) => riseWidth(nm, GROTESK, nSize, 800, 0.02) + 28 * k);
  const chipH = nSize * 1.2 + 20 * k;
  const offsets = base.map((p, i) => {
    const r = spotFor(p, chipW[i], chipH, 22 * k, [...blocks, ...placed], W, H, hash(names[i]) % 8);
    placed.push(r);
    return [r.x - p[0], r.y - p[1]] as XY;
  });
  // the distance: as said, else the straight-line miles along the stops
  let miles = 0;
  for (let i = 1; i < n; i++) miles += milesBetween(stops[i - 1], stops[i]);
  const said = num(overlay.value);
  const unit = unitWord(overlay.suffix);
  const dist = distanceText(miles, said, unit);
  const distVal = said !== null && said > 0 && (unit === "MI" || unit === "KM") ? said : (miles < 10 ? Math.round(miles * 10) / 10 : Math.round(miles));
  const distUnit = said !== null && said > 0 && (unit === "MI" || unit === "KM") ? unit : "MI";
  const count = clamp01(frac);
  const flowP = t > drawn + 8 ? ((t - drawn - 8) % 54) / 54 : -1;
  const kicker = (str(overlay.label) || "Route").toUpperCase();
  const title = str(overlay.text);
  const dSize = capFont(share("counter"), U, ks);
  const dk = capFont(share("kicker"), U, ks);
  const homes = homesOf(geo, stops.map((s) => [s.lon, s.lat] as [number, number]));
  const chipsNow = pts.map((p, i) => rect(p[0] + offsets[i][0], p[1] + offsets[i][1], chipW[i], chipH));
  const marks = pts.map((p) => rect(p[0] - 18 * k, p[1] - 18 * k, 36 * k, 36 * k));
  const tags = [rect(0, 0, 0.5 * W, 0.22 * H), rect(0, 0.74 * H, 0.42 * W, 0.26 * H)];
  return (
    <AbsoluteFill>
      {sound}
      <DarkMap geo={geo} path={(g) => path(g as never) || ""} grat={path(geoGraticule().step([2, 2])() as never) || ""} cam={cam}
        C={C} W={W} H={H} k={k} hot={hot} o={o} glowId={glowId} home={homes} homeP={prog(f, 8, 30, S, cubicOut) * xo} />
      <MapNames geo={geo} proj={(p) => proj(p) as [number, number] | null} cam={cam} C={C} W={W} H={H} k={k}
        size={capFont(share("small"), U, ks)} o={prog(f, 16, 26, S, cubicOut) * xo * 0.9} blockers={[...chipsNow, ...marks, ...tags,
          ...lineBlocks(scr, 16 * k, 4)]} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: xo }}>
        {/* the route: a soft glow under a crisp accent line, drawn to the head */}
        <path d={polyD(scr)} fill="none" stroke={rgba(hot, 0.35)} strokeWidth={lineW * 3.2} strokeLinecap="round" strokeLinejoin="round"
          pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - frac} style={{ filter: `blur(${(6 * k).toFixed(1)}px)` }} />
        <path d={polyD(scr)} fill="none" stroke={hot} strokeWidth={lineW} strokeLinecap="round" strokeLinejoin="round"
          pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - frac} />
        {flowP >= 0 ? (
          <path d={polyD(scr)} fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth={lineW * 0.55} strokeLinecap="round"
            pathLength={1} strokeDasharray="0.07 0.93" strokeDashoffset={1 - flowP} />
        ) : null}
        {pts.map((p, i) => {
          const arr = i === 0 ? t0 - 8 : arrive[i];
          const dot = prog(f, arr, 10, S, (u) => backOut(u, 1.7)) * xo;
          const ring = prog(f, arr, 14, S, cubicInOut) * xo;
          const ping = clamp01((t - arr) / 30);
          const end = i === 0 || i === n - 1;
          const r = (end ? 13 : 10) * k;
          return (
            <g key={i}>
              {ping > 0 && ping < 1 ? <circle cx={p[0]} cy={p[1]} r={r * (1 + 1.8 * cubicOut(ping))} fill="none" stroke={hot}
                strokeWidth={2 * k} opacity={(1 - ping) * 0.7} /> : null}
              <circle cx={p[0]} cy={p[1]} r={r + 6 * k} fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth={Math.max(1.5, 2 * k)}
                pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ring} transform={`rotate(-90 ${p[0]} ${p[1]})`} />
              <circle cx={p[0]} cy={p[1]} r={Math.max(0, r * 0.62 * dot)} fill={end ? hot : "#fff"} stroke="#fff" strokeWidth={Math.max(0, 2.4 * k * dot)} />
            </g>
          );
        })}
        {frac > 0.002 && frac < 0.998 && out <= 0 ? (
          <g>
            <circle cx={head[0]} cy={head[1]} r={16 * k} fill={rgba(hot, 0.28)} />
            <circle cx={head[0]} cy={head[1]} r={6.5 * k} fill="#fff" stroke={hot} strokeWidth={3 * k} />
          </g>
        ) : null}
      </svg>
      {pts.map((p, i) => {
        const at = i === 0 ? t0 - 4 : arrive[i] + 2;
        const open = prog(f, at, 14, S, expoOut);
        if (open <= 0.001) return null;
        return (
          <Glass key={i} x={p[0] + offsets[i][0]} y={p[1] + offsets[i][1]} w={chipW[i]} h={chipH} k={k} p={open} out={out}
            right={offsets[i][0] < 0} radius={10}>
            <div style={{ position: "absolute", left: 14 * k, top: 10 * k }}>
              <RiseLine text={names[i]} size={nSize} font={GROTESK} weight={800} at={at + 2} out={out} k={k} tracking={0.02} gap={0.8} />
            </div>
          </Glass>
        );
      })}
      {dist ? (
        <Glass x={0.068 * W} y={0.82 * H - dSize * 1.9} w={Math.max(capsWidth(kicker, dk), widthOf(`${countText(figureOf(distVal), 1)} ${distUnit}`, GROTESK, dSize, 800)) + 44 * k}
          h={dk + dSize * 1.25 + 34 * k} k={k} p={prog(f, 6, 16, S, expoOut)} out={out} radius={14}>
          <div style={{ position: "absolute", left: 22 * k, top: 14 * k }}>
            <div style={{ height: dk, marginBottom: 8 * k }}><Caps text={kicker} size={dk} color={hot} at={9} out={out} k={k} /></div>
            <div style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: dSize, lineHeight: 1.1, color: WHITE, whiteSpace: "nowrap",
              fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', textShadow: softShadow(k, 0.4),
              opacity: prog(f, 10, 10, S, cubicOut) * xo }}>
              {countText(figureOf(distVal), count)}
              <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: dSize * 0.42, letterSpacing: "0.1em", color: SOFT_WHITE,
                marginLeft: 10 * k }}>{distUnit}</span>
            </div>
          </div>
        </Glass>
      ) : null}
      {title ? <TitleTag kicker="" title={title} U={U} ks={ks} k={k} W={W} H={H} hot={hot} at={4} out={out} f={f} S={S} /> : null}
      <Finish />
    </AbsoluteFill>
  );
};

// ================================================================== kt-storm
/** A storm's spiral (two arms round an eye), r its outer radius, drawn at the origin. */
const spiral = (r: number) => {
  // one hooked arm: out of the eye's side, round over the top to its tip, back in along its inner edge (the
  // weather map's storm symbol is two of them, half a turn apart, round a ringed eye)
  const e = r * 0.24;
  const ro = r * 0.66, ri = r * 0.5;
  const f = (v: number) => v.toFixed(2);
  const arm = `M${f(e)},0 A${f(ro)},${f(ro)} 0 0 0 ${f(-r * 0.18)},${f(-r * 0.98)} A${f(ri)},${f(ri)} 0 0 1 0,${f(-e)} Z`;
  return { e, arm };
};

/**
 * A storm moving through the places it reaches, in order (locations), each with its time as said (items[i].label:
 * "TUE 8 PM", "WEDNESDAY MORNING") - else the place's name alone. On the dark map framed on the track: the
 * forecast cone widens along the path (frames 6-34), then the storm - a spiral turning the way storms turn in
 * that hemisphere - travels it, reaching each position on its word (items[].at), the track solid behind it and
 * dashed ahead; each position's dot opens its time and place on glass as the storm passes. The storm's name and
 * strength (as said) sit on a glass tag top left.
 */
const Storm: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const glowId = useSvgId("ktstglow");
  const coneId = useSvgId("ktstcone");
  const track = placesOf(overlay.locations, 6);
  const n = track.length;
  const given = Array.isArray(overlay.items) ? overlay.items : [];
  const C: XY = [W / 2, H / 2];
  const geo = n >= 2 ? (track.every(inUS) ? STATES : WORLD) : [];
  const proj = n >= 2 ? framing(track.map((s) => [s.lon, s.lat] as XY), [[0.16 * W, 0.22 * H], [0.84 * W, 0.84 * H]], 3.2) : null;
  const base: XY[] = proj ? track.map((s) => proj([s.lon, s.lat]) as XY) : [];
  const per = 18;
  const poly = n === 2 ? bowed(base[0], base[1], 0.08, 36) : n > 2 ? throughPoints(base, per) : [];
  const cum = poly.length ? cumulative(poly) : [0];
  const total = cum[cum.length - 1] || 1;
  const stopFrac = base.map((_p, i) => (n === 2 ? i : (cum[Math.min(cum.length - 1, i * per)] || 0) / total));
  const t0 = 30;
  const L = Math.min(96, 34 + 18 * (n - 1));
  const arrive: number[] = base.map((_p, i) => {
    if (i === 0) return t0;
    const at = num((given[i] as { at?: unknown } | undefined)?.at);
    return saidAt(at, t0 + L * stopFrac[i]);
  });
  for (let i = 1; i < n; i++) arrive[i] = Math.max(arrive[i], arrive[i - 1] + 12);
  const sound = useLookSound(n >= 2 ? [{ name: "map-swoop", alt: ["whoosh-soft-v2", "whoosh-soft"], at: 0, gain_db: -12 },
    ...arrive.map((a) => ({ name: "radar-ping", alt: ["ui-tick", "tick"], at: Math.round(a), gain_db: -14 }))] : null);
  if (n < 2 || !proj) return null;
  const path = geoPath(proj as never);
  const t = f / S;
  let frac = 0;
  if (t >= arrive[n - 1]) frac = 1;
  else if (t > arrive[0]) {
    let i = 0;
    while (i < n - 2 && t >= arrive[i + 1]) i++;
    frac = lerp(stopFrac[i], stopFrac[i + 1], clamp01((t - arrive[i]) / Math.max(1, arrive[i + 1] - arrive[i])));
  }
  const end = arrive[n - 1];
  const camP = prog(f, 0, 40, S, cubicOut);
  const cam: Cam = { z: (1.08 - 0.08 * camP) * (1 + 0.03 * idle(f, end * S, dur)), m: C };
  const scr = poly.map((p) => onScreen(p, cam, C));
  const scum = cum.map((c) => c * cam.z);
  const pts = base.map((p) => onScreen(p, cam, C));
  const U = unitOf(W, H);
  const xo = 1 - clamp01(out * 1.4);
  const o = prog(f, 0, 10, S, cubicOut) * (1 - clamp01(out * 1.2));
  // the cone: half-width growing along the track, revealed from the start
  const coneP = prog(f, 6, 28, S, cubicInOut) * xo;
  const w0 = 0.012 * U, w1 = 0.085 * U;
  const leftSide: XY[] = [], rightSide: XY[] = [];
  const upToCone = upTo(scr, scum, coneP);
  const ccum = cumulative(upToCone);
  const ctotal = scum[scum.length - 1] || 1;
  upToCone.forEach((p, i) => {
    const a = upToCone[Math.max(0, i - 1)], b = upToCone[Math.min(upToCone.length - 1, i + 1)];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    const s = ccum[i] / ctotal;
    const w = lerp(w0, w1, s);
    leftSide.push([p[0] - (dy / len) * w, p[1] + (dx / len) * w]);
    rightSide.push([p[0] + (dy / len) * w, p[1] - (dx / len) * w]);
  });
  const capR = lerp(w0, w1, (ccum[ccum.length - 1] || 0) / ctotal);
  const coneD = upToCone.length > 1 ? `${polyD(leftSide)} A${capR.toFixed(1)},${capR.toFixed(1)} 0 0 0 ${rightSide[rightSide.length - 1][0].toFixed(1)},${rightSide[rightSide.length - 1][1].toFixed(1)} `
    + `${polyD([...rightSide].reverse()).replace(/^M/, "L")} Z` : "";
  const at = along(scr, scum, frac);
  const R = 0.042 * U * ks;
  const north = (track[0].lat + track[n - 1].lat) / 2 >= 0;
  const spin = (north ? -1 : 1) * t * 7.5;
  const arrived = prog(f, t0 - 12, 12, S, (u) => backOut(u, 1.6)) * xo;
  const sp = spiral(R);
  const behind = upTo(scr, scum, frac);
  const sSize = capFont(share("small"), U, ks);
  const tSize = capFont(share("stopName"), U, ks);
  const labels = track.map((s, i) => {
    const time = str((given[i] as { label?: unknown } | undefined)?.label);
    const place = (placeName(s.label).name || s.label).toUpperCase();
    return { time: time.toUpperCase(), place };
  });
  const placed: Rect[] = [];
  const finalScr = poly.map((p) => onScreen(p, { z: 1, m: C }, C));
  const blocks = [...lineBlocks(finalScr, w1 * 0.7, 2), rect(0, 0, 0.5 * W, 0.26 * H)];
  const chipSize = labels.map((l) => {
    const w = Math.max(l.time ? riseWidth(l.time, GROTESK, tSize, 800, 0.02) : 0, capsWidth(l.place, sSize, 0.14)) + 26 * k;
    const h = (l.time ? tSize * 1.2 + 6 * k : 0) + sSize + 20 * k;
    return [w, h] as XY;
  });
  const offsets = base.map((p, i) => {
    const r = spotFor(p, chipSize[i][0], chipSize[i][1], w1 * 0.75 + 10 * k, [...blocks, ...placed], W, H, i % 2 ? 4 : 0);
    placed.push(r);
    return [r.x - p[0], r.y - p[1]] as XY;
  });
  const name = str(overlay.text);
  const strength = str(overlay.subtitle);
  const kicker = (str(overlay.label) || "Storm track").toUpperCase();
  const chipsNow = pts.map((p, i) => rect(p[0] + offsets[i][0], p[1] + offsets[i][1], chipSize[i][0], chipSize[i][1]));
  return (
    <AbsoluteFill>
      {sound}
      <DarkMap geo={geo} path={(g) => path(g as never) || ""} grat={path(geoGraticule().step([2, 2])() as never) || ""} cam={cam}
        C={C} W={W} H={H} k={k} hot={hot} o={o} glowId={glowId} />
      <MapNames geo={geo} proj={(p) => proj(p) as [number, number] | null} cam={cam} C={C} W={W} H={H} k={k}
        size={capFont(share("small"), U, ks)} o={prog(f, 12, 26, S, cubicOut) * xo * 0.9}
        blockers={[...chipsNow, rect(0, 0, 0.5 * W, 0.26 * H), ...lineBlocks(scr, w1 * 0.8, 2)]} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <radialGradient id={coneId} cx="50%" cy="50%" r="70%">
            <stop offset="0%" stopColor="rgba(255,255,255,0.16)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0.06)" />
          </radialGradient>
        </defs>
        {coneD ? (
          <path d={coneD} fill={`url(#${coneId})`} stroke="rgba(255,255,255,0.42)" strokeWidth={Math.max(1, 1.6 * k)}
            strokeDasharray={`${7 * k} ${6 * k}`} opacity={clamp01(coneP * 2)} />
        ) : null}
        {/* the track: dashed ahead (the forecast), solid behind the storm */}
        <path d={polyD(scr)} fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth={Math.max(1.5, 2.2 * k)} strokeLinecap="round"
          strokeDasharray={`${3 * k} ${9 * k}`} opacity={coneP} />
        {behind.length > 1 ? <path d={polyD(behind)} fill="none" stroke="#fff" strokeWidth={Math.max(2.5, 3.4 * k)} strokeLinecap="round"
          strokeLinejoin="round" opacity={xo} style={{ filter: `drop-shadow(0 0 ${(5 * k).toFixed(1)}px rgba(0,0,0,0.6))` }} /> : null}
        {pts.map((p, i) => {
          const pass = prog(f, arrive[i], 10, S, (u) => backOut(u, 1.6)) * xo;
          const pre = prog(f, 10 + i * 3, 12, S, cubicOut) * xo;
          return (
            <g key={i}>
              <circle cx={p[0]} cy={p[1]} r={5.5 * k} fill={pass > 0 ? "#fff" : "rgba(255,255,255,0.35)"} opacity={Math.max(pre * 0.8, pass)} />
              {pass > 0 ? <circle cx={p[0]} cy={p[1]} r={(5.5 + 5 * pass) * k} fill="none" stroke={hot} strokeWidth={2.2 * k} opacity={pass} /> : null}
            </g>
          );
        })}
        {/* the storm */}
        <g transform={`translate(${at.p[0].toFixed(1)} ${at.p[1].toFixed(1)}) scale(${arrived.toFixed(4)})`}>
          <circle r={R * 1.7} fill={rgba(hot, 0.18)} style={{ filter: `blur(${(10 * k).toFixed(1)}px)` }} />
          <g transform={`rotate(${spin.toFixed(2)})`} style={{ filter: `drop-shadow(0 0 ${(6 * k).toFixed(1)}px ${rgba(hot, 0.8)})` }}>
            {/* (the arms trail the turn: counter-clockwise in the north) */}
            <g transform={north ? "scale(-1,1)" : undefined}>
              <path d={sp.arm} fill="#fff" />
              <path d={sp.arm} fill="#fff" transform="rotate(180)" />
            </g>
            <circle r={sp.e} fill="none" stroke="#fff" strokeWidth={Math.max(2, 2.6 * k)} />
          </g>
          <circle r={sp.e * 0.42} fill={hot} />
        </g>
      </svg>
      {pts.map((p, i) => {
        const open = prog(f, arrive[i] + 3, 14, S, expoOut);
        if (open <= 0.001) return null;
        const l = labels[i];
        return (
          <Glass key={i} x={p[0] + offsets[i][0]} y={p[1] + offsets[i][1]} w={chipSize[i][0]} h={chipSize[i][1]} k={k} p={open}
            out={out} right={offsets[i][0] < 0} radius={10}>
            <div style={{ position: "absolute", left: 13 * k, top: 10 * k }}>
              {l.time ? (
                <div style={{ marginBottom: 6 * k }}>
                  <RiseLine text={l.time} size={tSize} font={GROTESK} weight={800} at={arrive[i] + 5} out={out} k={k} tracking={0.02} gap={0.8} />
                </div>
              ) : null}
              <div style={{ height: sSize }}>
                <Caps text={l.place} size={sSize} color={l.time ? DIM : "rgba(250,250,247,0.92)"} at={arrive[i] + 7} out={out} k={k} tracking={0.14} />
              </div>
            </div>
          </Glass>
        );
      })}
      <TitleTag kicker={kicker} title={name} sub={strength} U={U} ks={ks} k={k} W={W} H={H} hot={hot} at={4} out={out} f={f} S={S} />
      <Finish />
    </AbsoluteFill>
  );
};

// ================================================================== kt-totals
/**
 * A value by place (rain, snow, heat, wind - items[i] goes with locations[i]: its value, the second it is said),
 * on the dark map framed on the places: each place's dot drops in and its value opens on glass beside it on its
 * word, counting up (with the unit small after it and the place under it); once all are in, the highest takes
 * the accent - its glass edged, its dot ringed once. The title and the unit sit on a glass tag top left.
 */
const Totals: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const glowId = useSvgId("kttoglow");
  const places = placesOf(overlay.locations, 6);
  const given = Array.isArray(overlay.items) ? overlay.items : [];
  const rows = places.map((p, i) => ({ p, value: num(given[i]?.value), at: num((given[i] as { at?: unknown } | undefined)?.at),
    name: (str(given[i]?.label) || placeName(p.label).name || p.label).toUpperCase() }));
  const ok = rows.length >= 2 && rows.every((r) => r.value !== null);
  const lands = rows.map((r, i) => saidAt(r.at, 14 + i * 7));
  const sound = useLookSound(ok ? [{ name: "map-swoop", alt: ["whoosh-soft-v2", "whoosh-soft"], at: 0, gain_db: -12 },
    ...lands.map((a) => ({ name: "ui-pop", alt: ["pop", "ui-tick"], at: Math.round(a + 2), gain_db: -11 }))] : null);
  if (!ok) return null;
  const n = rows.length;
  const C: XY = [W / 2, H / 2];
  const geo = places.every(inUS) ? STATES : WORLD;
  const proj = framing(places.map((s) => [s.lon, s.lat] as XY), [[0.16 * W, 0.26 * H], [0.84 * W, 0.86 * H]], 2.6);
  const path = geoPath(proj as never);
  const base = places.map((s) => proj([s.lon, s.lat]) as XY);
  const t = f / S;
  const camP = prog(f, 0, 36, S, cubicOut);
  const cam: Cam = { z: (1.07 - 0.07 * camP) * (1 + 0.035 * idle(f, 40 * S, dur)), m: C };
  const pts = base.map((p) => onScreen(p, cam, C));
  const U = unitOf(W, H);
  const xo = 1 - clamp01(out * 1.4);
  const o = prog(f, 0, 10, S, cubicOut) * (1 - clamp01(out * 1.2));
  const suffix = overlay.suffix, prefix = overlay.prefix;
  const vSize = capFont(share("chipValue"), U, ks);
  const sSize = capFont(share("small"), U, ks);
  const fig0 = figureOf(rows[0].value as number, suffix, prefix);
  const uw = fig0.unit && fig0.unit.length <= 4 ? fig0.unit : "";
  const chip = rows.map((r) => {
    const fg = figureOf(r.value as number, suffix, prefix);
    const vw = widthOf(`${fg.prefix}${fg.main}${fg.glued}`, GROTESK, vSize, 800) + (uw ? 8 * k + widthOf(uw, SUBLINE, vSize * 0.42, 700, 0.1) : 0);
    return [Math.max(vw, capsWidth(r.name, sSize, 0.14)) + 28 * k, vSize * 1.12 + 8 * k + sSize + 22 * k] as XY;
  });
  const placed: Rect[] = [];
  const blocks = [...base.map((p) => rect(p[0] - 14 * k, p[1] - 14 * k, 28 * k, 28 * k)), rect(0, 0, 0.5 * W, 0.26 * H)];
  const offsets = base.map((p, i) => {
    const r = spotFor(p, chip[i][0], chip[i][1], 16 * k, [...blocks, ...placed], W, H, 6);
    placed.push(r);
    return [r.x - p[0], r.y - p[1]] as XY;
  });
  const maxV = Math.max(...rows.map((r) => r.value as number));
  const top = rows.findIndex((r) => r.value === maxV);
  const allIn = Math.max(...lands) + 18;
  const lead = prog(f, allIn, 14, S, cubicOut) * xo;
  const ring = clamp01((t - allIn) / 28);
  const homes = homesOf(geo, places.map((s) => [s.lon, s.lat] as [number, number]));
  const chipsNow = pts.map((p, i) => rect(p[0] + offsets[i][0], p[1] + offsets[i][1], chip[i][0], chip[i][1]));
  return (
    <AbsoluteFill>
      {sound}
      <DarkMap geo={geo} path={(g) => path(g as never) || ""} grat={path(geoGraticule().step([2, 2])() as never) || ""} cam={cam}
        C={C} W={W} H={H} k={k} hot={hot} o={o} glowId={glowId} home={homes} homeP={prog(f, 6, 26, S, cubicOut) * xo} />
      <MapNames geo={geo} proj={(p) => proj(p) as [number, number] | null} cam={cam} C={C} W={W} H={H} k={k}
        size={capFont(share("small"), U, ks)} o={prog(f, 10, 24, S, cubicOut) * xo * 0.9}
        blockers={[...chipsNow, ...pts.map((p) => rect(p[0] - 16 * k, p[1] - 16 * k, 32 * k, 32 * k)), rect(0, 0, 0.5 * W, 0.28 * H)]} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: xo }}>
        {pts.map((p, i) => {
          const drop = prog(f, lands[i], 12, S, (u) => backOut(u, 1.8));
          const isTop = i === top;
          return (
            <g key={i}>
              {isTop && ring > 0 && ring < 1 ? <circle cx={p[0]} cy={p[1]} r={(9 + 24 * cubicOut(ring)) * k} fill="none" stroke={hot}
                strokeWidth={2.2 * k} opacity={1 - ring} /> : null}
              <circle cx={p[0]} cy={p[1] - (1 - drop) * 12 * k} r={Math.max(0, 7 * k * drop)} fill={isTop && lead > 0 ? hot : "#fff"}
                stroke={isTop && lead > 0 ? "#fff" : hot} strokeWidth={2.6 * k * drop} />
            </g>
          );
        })}
      </svg>
      {pts.map((p, i) => {
        const open = prog(f, lands[i] + 1, 14, S, expoOut);
        if (open <= 0.001) return null;
        const r = rows[i];
        const cnt = prog(f, lands[i] + 2, 18, S, expoOut);
        const fg = figureOf(r.value as number, suffix, prefix);
        const isTop = i === top && lead > 0;
        return (
          <React.Fragment key={i}>
            <Glass x={p[0] + offsets[i][0]} y={p[1] + offsets[i][1]} w={chip[i][0]} h={chip[i][1]} k={k} p={open} out={out}
              right={offsets[i][0] < 0} radius={10} edge={isTop ? hot : undefined} edgeP={lead}>
              <div style={{ position: "absolute", left: 14 * k + (isTop ? 4 * k : 0), top: 11 * k }}>
                <div style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: vSize, lineHeight: 1.12, color: WHITE, whiteSpace: "nowrap",
                  fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', textShadow: softShadow(k, 0.4),
                  opacity: clamp01(open * 1.6) }}>
                  {`${fg.prefix}${countText(fg, cnt)}${fg.glued}`}
                  {uw ? <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: vSize * 0.42, letterSpacing: "0.1em",
                    color: SOFT_WHITE, marginLeft: 8 * k }}>{uw}</span> : null}
                </div>
                <div style={{ height: sSize, marginTop: 8 * k }}>
                  <Caps text={r.name} size={sSize} color={isTop ? hot : DIM} at={lands[i] + 5} out={out} k={k} tracking={0.14} />
                </div>
              </div>
            </Glass>
          </React.Fragment>
        );
      })}
      <TitleTag kicker={str(overlay.label).toUpperCase()} title={str(overlay.text)} sub={str(overlay.subtitle)} U={U} ks={ks} k={k}
        W={W} H={H} hot={hot} at={4} out={out} f={f} S={S} />
      <Finish />
    </AbsoluteFill>
  );
};

// ================================================================== kt-regions
const norm = (s: string) => s.toLowerCase().replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim().replace(/^the /, "");
const ALIAS: Record<string, string> = { "washington dc": "district of columbia", "dc": "district of columbia",
  "usa": "united states of america", "united states": "united states of america", "us": "united states of america",
  "america": "united states of america", "uk": "united kingdom", "britain": "united kingdom" };
/** The outline a name stands for: a US state first, else a country. */
const featureNamed = (name: string): { g: Feat; us: boolean } | null => {
  const n = ALIAS[norm(name)] || norm(name);
  if (!n) return null;
  const st = STATES.find((x) => norm(String(x.properties?.name || "")) === n);
  if (st) return { g: st, us: true };
  const c = WORLD.find((x) => norm(String(x.properties?.name || "")) === n);
  return c ? { g: c, us: false } : null;
};
/** The lower 48 for the framing: Alaska and Hawaii (and the territories) would stretch the view to nothing. */
const FAR = new Set(["alaska", "hawaii", "puerto rico", "guam", "american samoa", "united states virgin islands",
  "commonwealth of the northern mariana islands"]);

/**
 * The states (or countries) a line names (items: each name and the second it is said), on the dark map framed
 * on them: every one lights up on its word - its face filling toward the accent with a soft glow, a white edge
 * drawing round it, its name rising at its middle - while a glass counter counts them ("7 STATES"). The camera
 * settles in as the first lights and creeps while it holds; a title (text) on a glass tag top left.
 */
const Regions: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const glowId = useSvgId("ktrgglow");
  const raw = (Array.isArray(overlay.items) ? overlay.items : []).map((it) => ({ name: str(it?.label),
    at: num((it as { at?: unknown } | undefined)?.at) })).filter((x) => x.name).slice(0, 12);
  const found = raw.map((x) => ({ ...x, hit: featureNamed(x.name) })).filter((x) => x.hit) as
    { name: string; at: number | null; hit: { g: Feat; us: boolean } }[];
  const usAll = found.length > 0 && found.every((x) => x.hit.us);
  const list = found.filter((x, i) => (usAll ? x.hit.us : !x.hit.us) && found.findIndex((y) => y.hit.g === x.hit.g) === i);
  const lights = list.map((x, i) => saidAt(x.at, 14 + i * 9));
  const sound = useLookSound(list.length >= 2 ? [{ name: "map-swoop", alt: ["whoosh-soft-v2", "whoosh-soft"], at: 0, gain_db: -12 },
    ...lights.map((a) => ({ name: "ui-tick", alt: ["tick"], at: Math.round(a + 2), gain_db: -10 }))] : null);
  if (list.length < 2) return null;
  const C: XY = [W / 2, H / 2];
  const geo = usAll ? STATES : WORLD;
  const frameOn = list.filter((x) => !FAR.has(norm(x.name)));
  const fc = { type: "FeatureCollection", features: (frameOn.length ? frameOn : list).map((x) => x.hit.g) };
  const proj = geoMercator().fitExtent([[0.12 * W, 0.16 * H], [0.88 * W, 0.84 * H]] as never, fc as never);
  const framing = `${W}x${H}:${(frameOn.length ? frameOn : list).map((x) => x.name).join(",")}`;
  const path = geoPath(proj as never);
  const t = f / S;
  const camP = prog(f, 0, 44, S, cubicOut);
  const cam: Cam = { z: (1.1 - 0.1 * camP) * (1 + 0.03 * idle(f, 50 * S, dur)), m: C };
  const U = unitOf(W, H);
  const xo = 1 - clamp01(out * 1.4);
  const o = prog(f, 0, 10, S, cubicOut) * (1 - clamp01(out * 1.2));
  const litOf = new Map<Feat, number>();
  list.forEach((x, i) => litOf.set(x.hit.g, prog(f, lights[i], 16, S, cubicInOut) * xo));
  const nSize = capFont(share("stateName"), U, ks);
  const count = list.filter((_x, i) => t >= lights[i]).length;
  const unit = (str(overlay.suffix) || (usAll ? (count === 1 ? "state" : "states") : (count === 1 ? "country" : "countries"))).toUpperCase();
  const cSize = capFont(share("counter"), U, ks);
  const ck = capFont(share("kicker"), U, ks);
  const lastLight = Math.max(...lights);
  const countW = widthOf(String(list.length), GROTESK, cSize, 800) + 12 * k + widthOf(unit, SUBLINE, cSize * 0.42, 700, 0.1);
  return (
    <AbsoluteFill>
      {sound}
      <DarkMap geo={geo} path={(g) => path(g as never) || ""} grat={path(geoGraticule().step(usAll ? [2, 2] : [10, 10])() as never) || ""}
        cam={cam} C={C} W={W} H={H} k={k} hot={hot} o={o} glowId={glowId} lit={(g) => litOf.get(g) || 0} />
      <MapNames geo={geo} proj={(p) => proj(p) as [number, number] | null} cam={cam} C={C} W={W} H={H} k={k}
        size={capFont(share("small"), U, ks) * 0.92} o={prog(f, 10, 26, S, cubicOut) * xo * 0.7} skip={new Set(list.map((x) => x.hit.g))}
        blockers={[rect(0, 0, 0.5 * W, 0.24 * H), rect(0, 0.74 * H, 0.4 * W, 0.26 * H)]} />
      {list.map((x, i) => {
        const label = x.name.toUpperCase();
        const w = capsWidth(label, nSize, 0.12) + 10 * k;
        // the name inside its own outline (worked out at the settled framing, then carried by the camera)
        const c = labelSpot(x.hit.g, `${framing}|${x.name}|${Math.round(w)}|${Math.round(nSize)}`,
          proj as never, w + 8 * k, nSize * 1.3);
        if (!c) return null;
        const p = onScreen(c, cam, C);
        const a = prog(f, lights[i] + 4, 14, S, expoOut);
        if (a <= 0.001 || p[0] < 0.04 * W || p[0] > 0.96 * W || p[1] < 0.06 * H || p[1] > 0.94 * H) return null;
        return (
          <div key={i} style={{ position: "absolute", left: p[0] - w / 2, top: p[1] - nSize * 0.7, width: w, textAlign: "center",
            opacity: xo }}>
            <div style={{ overflow: "hidden", height: nSize * 1.3 }}>
              <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: nSize, letterSpacing: "0.12em", color: WHITE,
                lineHeight: 1.3, whiteSpace: "nowrap", textShadow: softShadow(k, 0.7),
                transform: `translateY(${((1 - a) * 100).toFixed(2)}%)` }}>{label}</div>
            </div>
          </div>
        );
      })}
      <Glass x={0.068 * W} y={0.82 * H - cSize * 1.9} w={Math.max(countW, capsWidth("Named", ck)) + 44 * k} h={cSize * 1.3 + 28 * k}
        k={k} p={prog(f, lights[0], 16, S, expoOut)} out={out} radius={14}>
        <div style={{ position: "absolute", left: 22 * k, top: 14 * k, display: "flex", alignItems: "baseline", gap: 12 * k }}>
          <div style={{ position: "relative", height: cSize * 1.12, overflow: "hidden", minWidth: widthOf(String(list.length), GROTESK, cSize, 800) }}>
            {Array.from({ length: list.length }, (_v, j) => {
              const into = prog(f, lights[j], 10, S, expoOut);
              const away = j + 1 < list.length ? prog(f, lights[j + 1], 10, S, expoOut) : 0;
              if (into <= 0 || away >= 1) return null;
              return (
                <div key={j} style={{ position: "absolute", left: 0, top: 0, fontFamily: GROTESK, fontWeight: 800, fontSize: cSize,
                  lineHeight: 1.12, color: j === list.length - 1 && t >= lastLight + 8 ? hot : WHITE, whiteSpace: "nowrap",
                  fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', textShadow: softShadow(k, 0.4),
                  transform: `translateY(${((1 - into) * 100 - away * 100).toFixed(2)}%)`, opacity: xo }}>{j + 1}</div>
              );
            })}
          </div>
          <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: cSize * 0.42, letterSpacing: "0.1em", color: SOFT_WHITE,
            whiteSpace: "nowrap", opacity: prog(f, lights[0] + 4, 12, S, cubicOut) * xo }}>{unit}</div>
        </div>
      </Glass>
      <TitleTag kicker={str(overlay.label).toUpperCase()} title={str(overlay.text)} U={U} ks={ks} k={k} W={W} H={H} hot={hot} at={4}
        out={out} f={f} S={S} />
      <Finish />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-route": guard(Route),
  "kt-storm": guard(Storm),
  "kt-totals": guard(Totals),
  "kt-regions": guard(Regions),
};

