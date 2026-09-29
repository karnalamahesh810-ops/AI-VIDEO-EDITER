import React from "react";
import { AbsoluteFill, Audio, Easing, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { geoBounds, geoContains, geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import statesTopology from "../../data/us-states.json";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay, OverlayItem } from "../../types";
import { Odometer, lines, ramp, useHold, useK } from "../pro/ProGraphics";

// The owner (2026-09-29): a look's own sounds sit at ~40% of their old level.
const IN_LOOK_SFX_SCALE = 0.4;

/**
 * Basin maps (family "bm-"): full-frame dark-navy vector maps of the United
 * States and the Colorado River Basin, drawn from the bundled state outlines
 * with d3-geo, so they render offline and the same in the editor and on the
 * worker. Built to match (and beat) the GoMotion basin graphics: the USA that
 * zooms into the seven basin states, the glowing river network, the upper /
 * lower basin split at Lees Ferry, and a single state called out to a figure.
 *
 *   bm-usa-zoom        the USA appears, a spring camera dives into the region holding the places, labels rise
 *   bm-basin-zoom      "UNITED STATES" caption, then a push onto the target states, glow, outlines drawing, pins
 *   bm-river-network   the Colorado and its tributaries trace on as glowing lines, water streaming along them
 *   bm-basin-split     upper and lower basin states in two tints, the Lees Ferry divide dashed between them
 *   bm-state-callout   the camera pushes onto one state, a callout line runs to a figure box
 *
 * Coordinates come from the gazetteer (overlay.locations); the river geometry
 * is hand-authored (no hydrography ships with the renderer). Every look draws
 * something sensible with no props at all and never throws on a missing one.
 * All motion is a pure function of the frame; no Math.random / Date.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];
type Geometry = { type: string; coordinates: unknown };
type Feat = { type: string; id?: string | number; properties?: { name?: string }; geometry: Geometry | null };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };

// ------------------------------------------------------------------ geography
const ALL_STATES = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features;
const LOWER48: Feat[] = ALL_STATES.filter((f) => {
  const id = Number(f.id);
  return Number.isFinite(id) && id <= 56 && id !== 2 && id !== 15;
});
const fc = (features: Feat[]): FeatColl => ({ type: "FeatureCollection", features });
const LOWER48_FC = fc(LOWER48);
const fips = (f: Feat) => Number(f.id);
/** The seven Colorado River Basin states: AZ, CA, CO, NV, NM, UT, WY. */
const BASIN_IDS = [4, 6, 8, 32, 35, 49, 56];
const UPPER_IDS = [8, 35, 49, 56];
const BASIN: Feat[] = LOWER48.filter((f) => BASIN_IDS.includes(fips(f)));
const BASIN_FC = fc(BASIN);
const UPPER: Feat[] = BASIN.filter((f) => UPPER_IDS.includes(fips(f)));
const LOWER: Feat[] = BASIN.filter((f) => !UPPER_IDS.includes(fips(f)));

// ------------------------------------------------------------------ constants
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const CYAN = "#53c8ff";
const SAND = "#ffb454";
const LAND = "#1a212b";
const EDGE = "#2e3845";
const BORDER = "#28313d";
const FULL: React.CSSProperties = { position: "absolute", left: 0, top: 0 };

// ------------------------------------------------------------------ small helpers
const cap = (s?: unknown) => (typeof s === "string" ? s : s === null || s === undefined ? "" : String(s)).toUpperCase();
const str = (s?: unknown) => (typeof s === "string" ? s : s === null || s === undefined ? "" : String(s));
const short = (l?: string) => (l || "").split(",")[0].trim();
const norm = (s?: string) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const lim = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

const hexRgb = (h: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i.exec((h || "").trim());
  if (!m) return [83, 200, 255];
  let s = m[1];
  if (s.length === 3) s = s.split("").map((c) => c + c).join("");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
const mix = (a: string, b: string, t: number) => {
  const A = hexRgb(a), B = hexRgb(b);
  const u = lim(t, 0, 1);
  return `#${A.map((v, i) => Math.round(v + (B[i] - v) * u).toString(16).padStart(2, "0")).join("")}`;
};
const alpha = (h: string, a: number) => {
  const [r, g, b] = hexRgb(h);
  return `rgba(${r},${g},${b},${lim(a, 0, 1).toFixed(3)})`;
};

/** Cut a string to about n characters on a word boundary, ending in an ellipsis. */
const clip = (s: string, n: number) => {
  const t = (s || "").trim();
  if (t.length <= n) return t;
  const cut = t.slice(0, Math.max(1, n - 1));
  const sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:!?-]+$/, "")}…`;
};
/** Word-wrap to at most `max` lines of about `per` characters; a cut last line ends in an ellipsis. */
const wrap = (text: string, per: number, max: number): string[] => {
  const ls = lines(text, per);
  if (ls.length <= max) return ls;
  const out = ls.slice(0, max);
  out[max - 1] = clip(`${out[max - 1]} ${ls[max]}`, per);
  return out;
};
/** A title's lines and size: it shrinks (never below 44 px or 78%) before it is cut to `max` lines. */
const fitTitle = (text: string, size: number, per: number, max: number): { ls: string[]; size: number } => {
  const floor = Math.max(44, size * 0.78);
  let s = size;
  let ls = lines(text, per);
  while (ls.length > max && s * 0.92 >= floor) {
    s *= 0.92;
    ls = lines(text, Math.round((per * size) / s));
  }
  return { size: s, ls: ls.length > max ? wrap(text, Math.round((per * size) / s), max) : ls };
};
/** A document-unique id for SVG defs, so two instances of a look never share a filter or clip. */
const useSvgId = (prefix: string) => `${prefix}${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;

/** Valid gazetteer places only: finite, in range, labels as strings. */
const placesOf = (ov: Overlay, max: number): MapLocation[] => {
  const out: MapLocation[] = [];
  for (const p of Array.isArray(ov.locations) ? ov.locations : []) {
    if (!p || typeof p !== "object") continue;
    const lat = Number(p.lat), lon = Number(p.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
    out.push({ label: str(p.label), lat, lon, kind: typeof p.kind === "string" ? p.kind : undefined });
    if (out.length >= max) break;
  }
  return out;
};
const placeKey = (ps: MapLocation[]) => ps.map((p) => `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`).join("|");
/** Items as label / value / text, tolerant of anything the plan may have put there. */
const itemsOf = (ov: Overlay): OverlayItem[] => {
  const out: OverlayItem[] = [];
  for (const it of Array.isArray(ov.items) ? ov.items : []) {
    if (!it || typeof it !== "object") continue;
    const v = Number((it as { value?: unknown }).value);
    out.push({ label: str((it as { label?: unknown }).label).trim(), value: Number.isFinite(v) ? v : undefined,
      text: typeof it.text === "string" ? it.text : undefined });
  }
  return out;
};
/** A water kind (lake, dam, reservoir) gets a ring; everything else a dot. */
const isWater = (kind?: string) => /lake|dam|reservoir|river|falls|spring/i.test(kind || "");

const contains = (f: Feat, p: MapLocation) => {
  try {
    return geoContains(f as never, [p.lon, p.lat]);
  } catch {
    return false;
  }
};
const stateOf = (p: MapLocation) => LOWER48.find((f) => contains(f, p)) || null;
const stateNamed = (name?: string) => {
  const n = norm(name);
  return n ? LOWER48.find((f) => norm(f.properties?.name) === n) || null : null;
};
/** The lon/lat box of a collection, padded, as a MultiPoint fitExtent can take. */
const paddedBox = (f: FeatColl, padLon: number, padLat: number) => {
  const [[x0, y0], [x1, y1]] = geoBounds(f as never);
  return { type: "MultiPoint", coordinates: [[x0 - padLon, y0 - padLat], [x1 + padLon, y1 + padLat]] };
};

// ------------------------------------------------------------------ polyline helpers
const cumOf = (pts: Pt[]) => {
  const c = [0];
  for (let i = 1; i < pts.length; i++) c.push(c[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return c;
};
const along = (pts: Pt[], cum: number[], run: number): { p: Pt; i: number } => {
  if (pts.length < 2) return { p: pts[0] || [0, 0], i: 0 };
  const total = cum[cum.length - 1];
  const r = Math.max(0, Math.min(total, run));
  let i = 0;
  while (i < pts.length - 2 && cum[i + 1] < r) i++;
  const seg = cum[i + 1] - cum[i] || 1;
  const t = Math.max(0, Math.min(1, (r - cum[i]) / seg));
  const a = pts[i], b = pts[i + 1];
  return { p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], i };
};
const partialD = (pts: Pt[], cum: number[], run: number) => {
  if (pts.length < 2 || run <= 0) return "";
  const h = along(pts, cum, run);
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let j = 1; j <= h.i; j++) d += ` L${pts[j][0].toFixed(1)} ${pts[j][1].toFixed(1)}`;
  return `${d} L${h.p[0].toFixed(1)} ${h.p[1].toFixed(1)}`;
};
const catmull = (p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: number): Pt => {
  const t2 = t * t, t3 = t2 * t;
  const f = (a: number, b: number, c: number, d: number) =>
    0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
  return [f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1])];
};
/** A smooth polyline through the waypoints (catmull-rom, `seg` steps per span). */
const densify = (P: Pt[], seg = 10): Pt[] => {
  if (P.length < 2) return P.slice();
  const raw: Pt[] = [];
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
    for (let s = 0; s < seg; s++) raw.push(catmull(p0, p1, p2, p3, s / seg));
  }
  raw.push(P[P.length - 1]);
  return raw;
};
/** The run (distance along the line) of the line's point nearest to p. */
const nearestRun = (pts: Pt[], cum: number[], p: Pt) => {
  let best = 0, bd = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const d = Math.hypot(pts[i][0] - p[0], pts[i][1] - p[1]);
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return cum[best] || 0;
};

// ------------------------------------------------------------------ camera
type Cam = { s: number; tx: number; ty: number };
/** A camera that shows map point c at screen point T at scale s. */
const camAt = (c: Pt, T: Pt, s: number): Cam => ({ s, tx: T[0] - c[0] * s, ty: T[1] - c[1] * s });
const toScreen = (p: Pt, cam: Cam): Pt => [p[0] * cam.s + cam.tx, p[1] * cam.s + cam.ty];
const camXf = (cam: Cam) => `translate(${cam.tx.toFixed(2)} ${cam.ty.toFixed(2)}) scale(${cam.s.toFixed(4)})`;

// ------------------------------------------------------------------ shared pieces
/** 0 -> 1 over the last 13 frames: every look leaves on it. */
const useExit = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - 13, 11, easeIn);
};

/** One short sound at a frame (a pop tick, a whoosh); nothing outside the beat. */
const Tick: React.FC<{ at: number; name?: string; volume?: number }> = ({ at, name = "pop", volume = 0.22 }) => {
  const { durationInFrames } = useVideoConfig();
  const f = Math.round(at);
  if (!Number.isFinite(f) || f < 0 || f >= durationInFrames - 2) return null;
  return (
    <Sequence from={f} layout="none">
      <Audio src={staticFile(`sfx/${name}.mp3`)} volume={Math.max(0, Math.min(1, volume * IN_LOOK_SFX_SCALE))} />
    </Sequence>
  );
};

/** A line rising out of its mask, and leaving downward through it at the end. */
const Rise: React.FC<{ at: number; frames?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 16, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, durationInFrames - 13, 10, easeIn);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.1em", ...style }}>
        <div style={{ transform: `translateY(${(1 - pin) * 112 + pout * 112}%)`, opacity: pin < 0.02 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** Letters rising out of their mask one after another, leaving on a stagger compressed to the line's length. */
const Letters: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 1, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const chars = Array.from(text);
    const outAt = durationInFrames - 13;
    const outStep = chars.length > 1 ? Math.min(0.6, 5 / (chars.length - 1)) : 0;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        {chars.map((c, i) => {
          const pin = ramp(frame, at + i * step, 12);
          const pout = ramp(frame, outAt + i * outStep, 7, easeIn);
          const y = (1 - pin) * 105 - pout * 105;
          return (
            <span key={i} style={{ display: "inline-block", transform: `translateY(${y}%)`, whiteSpace: "pre",
              opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
          );
        })}
      </div>
    );
  };

/** Kicker, accent rule, title letters, up to three lines of body; everything rises in and drops out. */
const TextBlock: React.FC<{
  kicker?: string; title?: string; body?: string; accent: string; at: number; size?: number;
  align?: "left" | "right"; chars?: number; kickerColor?: string; maxLines?: number; children?: React.ReactNode;
}> = ({ kicker, title, body, accent, at, size = 72, align = "left", chars, kickerColor, maxLines = 2, children }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const exit = useExit();
  const right = align === "right";
  const ta = right ? ("right" as const) : ("left" as const);
  const per = chars || (size >= 70 ? 16 : size >= 56 ? 20 : 24);
  const fit = fitTitle(cap(title), size, per, maxLines);
  const bl = wrap((body || "").trim(), 34, 3);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
      {kicker ? (
        <Letters text={clip(cap(kicker), 34)} at={at} step={0.45} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k,
          letterSpacing: "0.26em", color: kickerColor || accent, textAlign: ta, whiteSpace: "nowrap" }} />
      ) : null}
      <div style={{ width: ramp(frame, at + 3, 16) * (1 - exit) * 92 * k, height: 5 * k, background: accent,
        margin: `${8 * k}px 0 ${12 * k}px`, boxShadow: `0 0 ${14 * k}px ${alpha(accent, 0.6)}` }} />
      {fit.ls.map((ln, i) => (
        <Letters key={i} text={ln} at={at + 5 + i * 5} step={0.8} style={{ fontFamily: DISPLAY, fontSize: fit.size * k,
          lineHeight: 0.98, color: "#fff", letterSpacing: "0.02em", textAlign: ta, whiteSpace: "nowrap",
          textShadow: "0 6px 28px rgba(0,0,0,.6)" }} />
      ))}
      {bl.map((ln, i) => (
        <Letters key={`b${i}`} text={ln} at={at + 14 + i * 4} step={0.3} style={{ fontFamily: LABEL, fontWeight: 600,
          fontSize: 32 * k, lineHeight: 1.12, color: "rgba(255,255,255,.8)", letterSpacing: "0.02em", textAlign: ta,
          whiteSpace: "nowrap", marginTop: i ? 0 : 10 * k, textShadow: "0 3px 14px rgba(0,0,0,.7)" }} />
      ))}
      {children}
    </div>
  );
};

/** The title block in the top-left corner, only when there is something to say. */
const Title: React.FC<{ overlay: Overlay; accent: string; at?: number; bottom?: boolean }> = ({ overlay, accent, at = 2, bottom }) => {
  const k = useK();
  const text = str(overlay.text).trim(), sub = str(overlay.subtitle).trim();
  if (!text && !sub) return null;
  return (
    <div style={{ position: "absolute", left: 100 * k, top: bottom ? undefined : 92 * k, bottom: bottom ? 96 * k : undefined,
      width: 900 * k }}>
      <TextBlock kicker={text ? sub : undefined} title={text || sub} accent={accent} at={at} size={56} chars={26} />
    </div>
  );
};

/** A place name beside its point: a mono kicker over a condensed name, set on the outer side. */
const PlaceTag: React.FC<{ x: number; y: number; side: "left" | "right"; kicker: string; name: string; accent: string; at: number;
  size?: number }> = ({ x, y, side, kicker, name, accent, at, size = 34 }) => {
  const k = useK();
  const { width, height } = useVideoConfig();
  const onLeft = side === "left";
  const nl = wrap(cap(name), 18, 2);
  const estH = (30 + nl.length * (size + 4)) * k;
  const top = Math.max(90 * k, Math.min(height - 90 * k - estH, y - (26 + size * 0.5) * k));
  return (
    <div style={{ position: "absolute", top, left: onLeft ? undefined : x + 22 * k, right: onLeft ? width - x + 22 * k : undefined,
      display: "flex", flexDirection: "column", alignItems: onLeft ? "flex-end" : "flex-start" }}>
      {kicker ? (
        <Letters text={cap(kicker)} at={at} step={0.5} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 19 * k,
          letterSpacing: "0.24em", color: accent, whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.8)" }} />
      ) : null}
      {nl.map((ln, i) => (
        <Letters key={i} text={ln} at={at + 3 + i * 4} step={0.7} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
          color: "#fff", letterSpacing: "0.02em", whiteSpace: "nowrap", textAlign: onLeft ? "right" : "left",
          textShadow: "0 4px 20px rgba(0,0,0,.85)" }} />
      ))}
    </div>
  );
};

/** The dark sea every map sits on: a soft light, a fine dot screen. */
const DarkSea: React.FC<{ focus?: string }> = ({ focus = "55% 45%" }) => {
  const k = useK();
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${focus}, #142031 0%, #0a111b 50%, #04070b 100%)` }}>
      <AbsoluteFill style={{ backgroundImage: "radial-gradient(rgba(170,200,235,.10) 1px, transparent 1.5px)",
        backgroundSize: `${24 * k}px ${24 * k}px` }} />
    </AbsoluteFill>
  );
};

const Vignette: React.FC<{ strength?: number }> = ({ strength = 0.75 }) => {
  const k = useK();
  return <AbsoluteFill style={{ boxShadow: `inset 0 0 ${340 * k}px rgba(0,0,0,${strength})`, pointerEvents: "none" }} />;
};

// ------------------------------------------------------------------ river geometry (lat, lon waypoints)
type RiverDef = { name: string; parent: string | null; pts: Pt[] };
const MAINSTEM: RiverDef = { name: "Colorado River", parent: null, pts: [
  [40.47, -105.83], [40.25, -105.82], [40.06, -106.39], [39.55, -107.32], [39.06, -108.55], [38.57, -109.55],
  [38.19, -109.88], [37.87, -110.40], [36.94, -111.49], [36.86, -111.59], [36.10, -112.10], [36.02, -114.74],
  [35.17, -114.57], [34.30, -114.14], [33.61, -114.60], [32.88, -114.47], [32.69, -114.63], [32.72, -114.72], [31.85, -114.80],
] };
const TRIBUTARIES: RiverDef[] = [
  { name: "Green River", parent: null, pts: [[43.2, -109.7], [41.53, -109.47], [41.0, -109.5], [40.37, -109.34], [38.99, -110.16], [38.19, -109.88]] },
  { name: "Yampa River", parent: "Green River", pts: [[40.49, -106.83], [40.52, -107.55], [40.45, -108.5], [40.53, -108.98]] },
  { name: "San Juan River", parent: null, pts: [[37.8, -107.66], [36.73, -108.22], [37.28, -109.55], [37.15, -110.5], [37.2, -110.8]] },
  { name: "Gunnison River", parent: null, pts: [[38.55, -106.93], [38.74, -108.07], [39.06, -108.55]] },
  { name: "Little Colorado River", parent: null, pts: [[34.5, -109.4], [35.0, -110.7], [35.87, -111.41], [36.19, -111.80]] },
  { name: "Virgin River", parent: null, pts: [[37.2, -113.0], [37.1, -113.58], [36.5, -114.35]] },
  { name: "Gila River", parent: null, pts: [[32.8, -108.2], [33.4, -112.1], [32.95, -112.72], [32.7, -114.6]] },
];
const WATERS = [
  { name: "Lake Powell", lat: 37.3, lon: -110.85, kind: "lake" },
  { name: "Glen Canyon Dam", lat: 36.94, lon: -111.49, kind: "dam" },
  { name: "Lake Mead", lat: 36.2, lon: -114.4, kind: "lake" },
  { name: "Hoover Dam", lat: 36.016, lon: -114.737, kind: "dam" },
];
const LEES_FERRY: Pt = [36.86, -111.59];
/** Where the mainstem caption sits: the open lower reach above Parker, clear of every lake and dam label. */
const CAPTION_AT: Pt = [34.6, -114.35];
/** The lon/lat box of the whole river network, padded, so the rivers fill the frame (the states show around them). */
const RIVER_BOX = (() => {
  const all = [MAINSTEM, ...TRIBUTARIES].flatMap((r) => r.pts);
  const lats = all.map((p) => p[0]), lons = all.map((p) => p[1]);
  return { type: "MultiPoint", coordinates: [[Math.min(...lons) - 1.2, Math.min(...lats) - 0.7], [Math.max(...lons) + 1.2, Math.max(...lats) + 0.7]] };
})();
/** The compact's divide, drawn along the Utah / Arizona line dipping to Lees Ferry. */
const DIVIDE: Pt[] = [[37.0, -114.05], [36.86, -111.59], [37.0, -109.05]];

// ================================================================== 1 + 2. zoom maps (shared core)
/**
 * The lower 48 fade up, then the camera pushes onto the states holding the
 * places (or the seven basin states). Target states tint and glow, their
 * outlines draw on, every other state dims; as the push settles the state
 * names rise out of their masks with a pop tick each and the places pin.
 *
 *   usa    a spring camera, brighter tint, the title bottom-left (bm-usa-zoom)
 *   basin  a "UNITED STATES" caption first, an in-out push, title top-left (bm-basin-zoom)
 */
const ZoomMap: React.FC<{ overlay: Overlay; accent: string; variant: "usa" | "basin" }> = ({ overlay, accent, variant }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const hold = useHold();
  const id = useSvgId("bmz");
  const basinMode = variant === "basin";
  const places = placesOf(overlay, 8);
  const key = placeKey(places);
  const geo = React.useMemo(() => {
    const proj = geoMercator().fitExtent([[120 * k, 90 * k], [width - 120 * k, height - 80 * k]], LOWER48_FC as never);
    const path = geoPath(proj);
    const hits: Feat[] = [];
    for (const p of places) {
      const st = stateOf(p);
      if (st && !hits.includes(st)) hits.push(st);
    }
    const targets = hits.length ? hits : BASIN;
    const tfc = fc(targets);
    return {
      allD: path(LOWER48_FC as never) || "",
      targets: targets.map((f) => ({ d: path(f as never) || "", c: path.centroid(f as never) as Pt, name: f.properties?.name || "" })),
      targetsD: path(tfc as never) || "",
      b: path.bounds(tfc as never) as [Pt, Pt],
      usC: path.centroid(LOWER48_FC as never) as Pt,
      pins: places
        .map((p) => ({ p, xy: proj([p.lon, p.lat]) as Pt | null, ok: Boolean(stateOf(p)) }))
        .filter((x): x is { p: MapLocation; xy: Pt; ok: boolean } => x.ok && Array.isArray(x.xy)),
    };
  }, [key, width, height, k]);

  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, Math.round(fps * 0.5));
  const capAt = Math.round(fps * 0.3);
  const zoomAt = Math.round(fps * 0.8);
  const Z = Math.round(fps * 1.3);
  const settle = zoomAt + Z;
  const [[bx0, by0], [bx1, by1]] = geo.b;
  const ok = [bx0, by0, bx1, by1].every(Number.isFinite);
  const bw = ok ? Math.max(1, bx1 - bx0) : width, bh = ok ? Math.max(1, by1 - by0) : height;
  const sEnd = lim(Math.min((width * 0.62) / bw, (height * 0.72) / bh), 1.6, 2.6);
  const C: Pt = ok ? [(bx0 + bx1) / 2, (by0 + by1) / 2] : [width / 2, height / 2];
  const T: Pt = basinMode ? [width * 0.56, height * 0.53] : [width * 0.55, height * 0.46];
  const move = basinMode
    ? ramp(frame, zoomAt, Z, inOut)
    : frame < zoomAt ? 0 : Math.min(1, spring({ frame: frame - zoomAt, fps, config: { damping: 26, stiffness: 38, mass: 1.2 } }));
  const s = (1 + (sEnd - 1) * move) * hold * (1 - 0.1 * exit);
  const P: Pt = [C[0] + (T[0] - C[0]) * move, C[1] + (T[1] - C[1]) * move];
  const cam = camAt(C, P, s);
  const dim = ramp(frame, zoomAt - 4, 20) * vis;
  const outline = ramp(frame, zoomAt, Z, inOut);
  const glow = ramp(frame, zoomAt + 6, Math.round(fps * 0.8)) * vis;
  const tint = mix(LAND, accent, basinMode ? 0.28 : 0.4);
  const capP = ramp(frame, capAt, 12, backOut) * (1 - ramp(frame, zoomAt, 12));
  const usScr = toScreen(geo.usC, cam);
  const caption = cap(str(overlay.label) || "United States");
  const labelAt = (i: number) => settle - 8 + i * 4;

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus={`${((T[0] / width) * 100).toFixed(0)}% 50%`} />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn * (1 - 0.6 * exit) }}>
        <defs>
          <filter id={`${id}b`} x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation={(18 * k) / s} />
          </filter>
        </defs>
        <g transform={camXf(cam)}>
          <path d={geo.allD} fill={LAND} fillOpacity={1 - 0.35 * dim} stroke={EDGE} strokeOpacity={1 - 0.35 * dim}
            strokeWidth={(1 * k) / s} strokeLinejoin="round" />
          {glow > 0 ? <path d={geo.targetsD} fill={accent} opacity={0.45 * glow} filter={`url(#${id}b)`} /> : null}
          {geo.targets.map((t, i) => (
            <path key={i} d={t.d} fill={mix(LAND, tint, dim)} stroke={mix(EDGE, accent, 0.5 * dim)} strokeWidth={(1.1 * k) / s}
              strokeLinejoin="round" />
          ))}
          {geo.targets.map((t, i) => (
            <path key={`o${i}`} d={t.d} fill="none" stroke={accent} strokeWidth={(2.4 * k) / s} strokeLinejoin="round"
              pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - outline} opacity={vis} />
          ))}
        </g>
        {geo.pins.map(({ p, xy }, i) => {
          const q = toScreen(xy, cam);
          const pp = ramp(frame, settle + 2 + i * 3, 12, backOut) * vis;
          if (pp <= 0) return null;
          const water = isWater(p.kind);
          const name = clip(cap(short(p.label)), 22);
          const right = q[0] < width - 320 * k;
          return (
            <g key={i} opacity={pp}>
              {water ? (
                <circle cx={q[0]} cy={q[1]} r={10 * k * pp} fill={alpha(CYAN, 0.18)} stroke={CYAN} strokeWidth={2.2 * k} />
              ) : (
                <circle cx={q[0]} cy={q[1]} r={5.5 * k * pp} fill="#fff" stroke="#0b0e13" strokeWidth={2 * k} />
              )}
              {name ? (
                <text x={q[0] + (right ? 16 : -16) * k} y={q[1] + 7 * k} textAnchor={right ? "start" : "end"} fontFamily={MONO}
                  fontWeight={700} fontSize={19 * k} letterSpacing={`${0.12 * 19 * k}`} fill={water ? CYAN : "rgba(255,255,255,.9)"}
                  style={{ paintOrder: "stroke", stroke: "rgba(4,7,11,.85)", strokeWidth: 5 * k }}>{name}</text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <Vignette strength={0.65} />
      {basinMode && capP > 0 ? (
        <div style={{ position: "absolute", left: usScr[0], top: usScr[1], transform: `translate(-50%, -50%) scale(${capP.toFixed(3)})`,
          opacity: Math.min(1, capP * 1.5), fontFamily: MONO, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.34em",
          color: "rgba(255,255,255,.9)", whiteSpace: "nowrap", textShadow: "0 3px 16px rgba(0,0,0,.9)" }}>{caption}</div>
      ) : null}
      {geo.targets.map((t, i) => {
        const q = toScreen(t.c, cam);
        const nm = cap(t.name);
        if (!nm) return null;
        const at = labelAt(i);
        return (
          <div key={i} style={{ position: "absolute", left: q[0], top: q[1] - 16 * k, transform: "translate(-50%, 0)" }}>
            <Rise at={at} frames={14}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: (basinMode ? 26 : 28) * k, letterSpacing: "0.2em",
                color: "#fff", whiteSpace: "nowrap", textShadow: "0 2px 12px rgba(0,0,0,.9)" }}>{nm}</span>
            </Rise>
            {i < 8 ? <Tick at={at + 2} volume={0.22} /> : null}
          </div>
        );
      })}
      <Title overlay={overlay} accent={accent} bottom={!basinMode} at={basinMode ? 2 : zoomAt} />
    </AbsoluteFill>
  );
};

const UsaZoom: Look = ({ overlay, accent }) => <ZoomMap overlay={overlay} accent={accent} variant="usa" />;
const BasinZoom: Look = ({ overlay, accent }) => <ZoomMap overlay={overlay} accent={accent} variant="basin" />;

// ================================================================== 3. river network
/**
 * The seven basin states on the dark sea, then the Colorado draws itself
 * source to sea as a glowing line with bright water streaming down it. Each
 * tributary starts from its head the moment the mainstem's head passes their
 * confluence; names pop at the midpoints with a tick, lakes and dams light
 * up as the river reaches them, gazetteer places pin as the head passes.
 */
type RiverGeo = { name: string; parent: string | null; pts: Pt[]; cum: number[]; total: number; mid: Pt; conf: Pt; side: "left" | "right" | "center" };
type Sched = { start: number; dur: number };
const RiverNetwork: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const places = placesOf(overlay, 6);
  const key = placeKey(places);
  const wanted = itemsOf(overlay).map((it) => norm(it.label)).filter(Boolean);

  const geo = React.useMemo(() => {
    const proj = geoMercator().fitExtent([[480 * k, 70 * k], [width - 110 * k, height - 60 * k]], RIVER_BOX as never);
    const path = geoPath(proj);
    const pr = (lat: number, lon: number): Pt => (proj([lon, lat]) || [width / 2, height / 2]) as Pt;
    const mainPts = densify(MAINSTEM.pts.map(([la, lo]) => pr(la, lo)), 10);
    const rivers: RiverGeo[] = [MAINSTEM, ...TRIBUTARIES].map((r) => {
      const P = r.pts.map(([la, lo]) => pr(la, lo));
      const pts = densify(P, 10);
      const cum = cumOf(pts);
      const total = cum[cum.length - 1] || 1;
      // Names sit upstream of the midpoint, away from the confluence where the lakes and dams are,
      // and extend away from the mainstem (east of it they read eastward, west of it westward).
      const mid = along(pts, cum, total * 0.38).p;
      const near = mainPts.reduce((m, q) => (Math.hypot(q[0] - mid[0], q[1] - mid[1]) < Math.hypot(m[0] - mid[0], m[1] - mid[1]) ? q : m), mainPts[0]);
      const dx = mid[0] - near[0];
      const side: RiverGeo["side"] = dx > 30 * k ? "right" : dx < -30 * k ? "left" : "center";
      return { name: r.name, parent: r.parent, pts, cum, total, mid, conf: P[P.length - 1], side };
    });
    return {
      allD: path(LOWER48_FC as never) || "",
      basinD: BASIN.map((f) => path(f as never) || ""),
      rivers,
      waters: WATERS.map((w) => ({ ...w, xy: pr(w.lat, w.lon) })),
      capAt: pr(CAPTION_AT[0], CAPTION_AT[1]),
      pins: places.map((p) => ({ p, xy: pr(p.lat, p.lon) })),
    };
  }, [key, width, height, k]);

  // When each river starts drawing: the mainstem on the beat, a tributary as its parent's head passes the confluence.
  const drawAt = Math.round(fps * 0.5);
  const D = Math.round(Math.max(fps * 1.3, Math.min(fps * 2.2, durationInFrames * 0.34)));
  const TD = Math.round(fps * 0.7);
  const sched = React.useMemo(() => {
    const runOf = (s: Sched, f: number, total: number) => ramp(f, s.start, s.dur, inOut) * total;
    const frameAt = (s: Sched, total: number, dist: number) => {
      for (let f = s.start; f <= s.start + s.dur; f++) if (runOf(s, f, total) >= dist) return f;
      return s.start + s.dur;
    };
    const out: Record<string, Sched> = {};
    const main = geo.rivers[0];
    out[main.name] = { start: drawAt, dur: D };
    for (const r of geo.rivers.slice(1)) {
      const parent = geo.rivers.find((q) => q.name === r.parent && out[q.name]) || main;
      const ps = out[parent.name];
      out[r.name] = { start: frameAt(ps, parent.total, nearestRun(parent.pts, parent.cum, r.conf)), dur: TD };
    }
    const passAt = (p: Pt) => frameAt(out[main.name], main.total, nearestRun(main.pts, main.cum, p));
    return {
      by: out,
      waters: geo.waters.map((w) => passAt(w.xy)),
      pins: geo.pins.map((p) => passAt(p.xy)),
      caption: passAt(geo.capAt),
    };
  }, [geo, drawAt, D, TD]);

  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, Math.round(fps * 0.5));
  const tintP = ramp(frame, 6, 18);
  const caption = cap(str(overlay.label) || "Colorado River");
  const named = geo.rivers.slice(1).filter((r) => !wanted.length || wanted.some((w) => norm(r.name).includes(w) || w.includes(norm(r.name))));

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="58% 48%" />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn }}>
        <path d={geo.allD} fill={LAND} fillOpacity={0.75} stroke={BORDER} strokeWidth={1 * k} strokeLinejoin="round" />
        {geo.basinD.map((d, i) => (
          <path key={i} d={d} fill={mix(LAND, accent, 0.22 * tintP)} stroke={mix(BORDER, accent, 0.45 * tintP)} strokeWidth={1.2 * k}
            strokeLinejoin="round" />
        ))}
        <g opacity={vis}>
          {geo.rivers.map((r, i) => {
            const s = sched.by[r.name];
            const run = ramp(frame, s.start, s.dur, inOut) * r.total;
            if (run <= 0) return null;
            const d = partialD(r.pts, r.cum, run);
            const main = i === 0;
            const head = along(r.pts, r.cum, run).p;
            const drawing = run < r.total;
            return (
              <g key={r.name}>
                <path d={d} fill="none" stroke={alpha(accent, 0.2)} strokeWidth={(main ? 22 : 12) * k} strokeLinecap="round"
                  strokeLinejoin="round" />
                <path d={d} fill="none" stroke={CYAN} strokeWidth={(main ? 6 : 4) * k} strokeLinecap="round" strokeLinejoin="round" />
                <path d={d} fill="none" stroke="rgba(255,255,255,.75)" strokeWidth={(main ? 2 : 1.4) * k} strokeLinecap="round"
                  strokeDasharray={`${4 * k} ${24 * k}`} strokeDashoffset={-frame * 1.8 * k} />
                {drawing ? <circle cx={head[0]} cy={head[1]} r={(main ? 7 : 4.5) * k} fill="#fff" /> : null}
                {drawing && main ? (
                  <circle cx={head[0]} cy={head[1]} r={(14 + 8 * Math.abs(Math.sin(frame * 0.25))) * k} fill="none" stroke="#fff"
                    strokeOpacity={0.5} strokeWidth={2 * k} />
                ) : null}
              </g>
            );
          })}
          {geo.waters.map((w, i) => {
            const near = geo.pins.some((p) => Math.abs(p.p.lat - w.lat) < 0.35 && Math.abs(p.p.lon - w.lon) < 0.45);
            if (near) return null;
            const pp = ramp(frame, sched.waters[i], 12, backOut);
            if (pp <= 0) return null;
            const lake = w.kind === "lake";
            // Dam names read westward, off the tributaries that all join from the east.
            const right = w.xy[0] < 300 * k && !lake;
            return (
              <g key={w.name} opacity={pp}>
                {lake ? (
                  <ellipse cx={w.xy[0]} cy={w.xy[1]} rx={18 * k * pp} ry={12 * k * pp} fill={alpha(CYAN, 0.28)} stroke={CYAN}
                    strokeWidth={1.6 * k} />
                ) : (
                  <rect x={w.xy[0] - 5 * k} y={w.xy[1] - 5 * k} width={10 * k} height={10 * k} fill="#fff" stroke="#0b0e13"
                    strokeWidth={1.5 * k} transform={`rotate(45 ${w.xy[0]} ${w.xy[1]})`} />
                )}
                <text x={w.xy[0] + (lake ? 0 : right ? 14 : -14) * k} y={w.xy[1] + (lake ? -20 : 6) * k}
                  textAnchor={lake ? "middle" : right ? "start" : "end"} fontFamily={MONO} fontWeight={700} fontSize={18 * k}
                  letterSpacing={`${0.1 * 18 * k}`} fill={lake ? CYAN : "rgba(255,255,255,.85)"}
                  style={{ paintOrder: "stroke", stroke: "rgba(4,7,11,.85)", strokeWidth: 5 * k }}>{cap(w.name)}</text>
              </g>
            );
          })}
          {geo.pins.map(({ xy }, i) => {
            const pp = ramp(frame, sched.pins[i], 14, backOut);
            if (pp <= 0) return null;
            return (
              <g key={i}>
                <circle cx={xy[0]} cy={xy[1]} r={15 * k * pp} fill={alpha(accent, 0.25)} stroke={accent} strokeWidth={2.2 * k} />
                <circle cx={xy[0]} cy={xy[1]} r={6.5 * k * pp} fill="#fff" />
              </g>
            );
          })}
        </g>
      </svg>
      <Vignette strength={0.6} />
      {named.map((r, i) => {
        const s = sched.by[r.name];
        const at = s.start + Math.round(s.dur * 0.5);
        const pp = ramp(frame, at, 12, backOut) * vis;
        const tick = i < 8;
        return (
          <div key={r.name} style={{ position: "absolute", top: r.mid[1] - 22 * k,
            left: r.mid[0] + (r.side === "right" ? 12 : r.side === "left" ? -12 : 0) * k,
            transform: `translate(${r.side === "right" ? "0" : r.side === "left" ? "-100%" : "-50%"}, -50%) scale(${Math.max(0.001, pp).toFixed(3)})`,
            transformOrigin: r.side === "right" ? "0% 50%" : r.side === "left" ? "100% 50%" : "50% 50%", opacity: Math.min(1, pp * 1.5),
            fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.14em", color: "#dff4ff", whiteSpace: "nowrap",
            textShadow: "0 2px 12px rgba(0,0,0,.95), 0 0 18px rgba(83,200,255,.5)" }}>
            {cap(r.name)}
            {tick ? <Tick at={at + 1} volume={0.2} /> : null}
          </div>
        );
      })}
      <div style={{ position: "absolute", left: geo.capAt[0] + 26 * k, top: geo.capAt[1] - 18 * k }}>
        <Rise at={sched.caption}>
          <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.22em", color: "#fff",
            whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.9)" }}>{caption}</span>
        </Rise>
      </div>
      {geo.pins.map(({ p, xy }, i) => {
        const side: "left" | "right" = xy[0] > width * 0.62 ? "left" : "right";
        const kicker = p.kind ? p.kind : "Place";
        return <PlaceTag key={i} x={xy[0]} y={xy[1]} side={side} kicker={kicker} name={short(p.label) || "Place"} accent={accent}
          at={sched.pins[i] + 2} />;
      })}
      <Title overlay={overlay} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== 4. basin split
/** One half's name over the map, with the item's figure and note beneath when it carries them. */
const HalfLabel: React.FC<{ at: number; x: number; y: number; name: string; color: string; item?: OverlayItem; prefix: string; suffix: string }> =
  ({ at, x, y, name, color, item, prefix, suffix }) => {
    const k = useK();
    const { fps } = useVideoConfig();
    return (
      <div style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", display: "flex",
        flexDirection: "column", alignItems: "center" }}>
        <Rise at={at} frames={14}>
          <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.22em", color,
            whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.95)" }}>{clip(cap(name), 22)}</span>
        </Rise>
        {item && typeof item.value === "number" && Number.isFinite(item.value) ? (
          <Rise at={at + 6} frames={14}>
            <Odometer value={item.value} at={at + 6} frames={Math.round(fps * 0.8)} size={60 * k} color="#fff" prefix={prefix}
              suffix={suffix ? (suffix === "%" ? "%" : ` ${cap(suffix)}`) : ""} suffixColor={color} suffixScale={0.5} />
          </Rise>
        ) : null}
        {item?.text ? (
          <Rise at={at + 10} frames={14}>
            <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, letterSpacing: "0.04em",
              color: "rgba(255,255,255,.8)", whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.9)" }}>{clip(item.text, 30)}</span>
          </Rise>
        ) : null}
      </div>
    );
  };

/**
 * The basin states in two tints: the upper basin (CO, WY, UT, NM) in the
 * accent, the lower (AZ, NV, CA) in desert sand. The compact's dividing line
 * dashes across the Utah / Arizona border to Lees Ferry, which is marked and
 * named; both halves get a label (items[0] / items[1]) and, when the items
 * carry values, the figure beneath it.
 */
const BasinSplit: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const hold = useHold();
  const items = itemsOf(overlay);
  const geo = React.useMemo(() => {
    const proj = geoMercator().fitExtent([[520 * k, 110 * k], [width - 90 * k, height - 90 * k]], paddedBox(BASIN_FC, 1.5, 1) as never);
    const path = geoPath(proj);
    const pr = (lat: number, lon: number): Pt => (proj([lon, lat]) || [width / 2, height / 2]) as Pt;
    const divide = densify(DIVIDE.map(([la, lo]) => pr(la, lo)), 8);
    const divideCum = cumOf(divide);
    return {
      allD: path(LOWER48_FC as never) || "",
      upper: UPPER.map((f) => ({ d: path(f as never) || "", c: path.centroid(f as never) as Pt, name: f.properties?.name || "" })),
      lower: LOWER.map((f) => ({ d: path(f as never) || "", c: path.centroid(f as never) as Pt, name: f.properties?.name || "" })),
      upperC: path.centroid(fc(UPPER) as never) as Pt,
      lowerC: path.centroid(fc(LOWER) as never) as Pt,
      divide, divideCum, divideTotal: divideCum[divideCum.length - 1] || 1,
      lees: pr(LEES_FERRY[0], LEES_FERRY[1]),
    };
  }, [width, height, k]);

  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, Math.round(fps * 0.5));
  const upAt = Math.round(fps * 0.5), loAt = Math.round(fps * 1.0), lineAt = Math.round(fps * 1.4);
  const upP = ramp(frame, upAt, Math.round(fps * 0.6), inOut) * vis;
  const loP = ramp(frame, loAt, Math.round(fps * 0.6), inOut) * vis;
  const lineP = ramp(frame, lineAt, Math.round(fps * 0.7), inOut) * vis;
  const leesAt = lineAt + Math.round(fps * 0.6);
  const leesP = ramp(frame, leesAt, 12, backOut) * vis;
  const C: Pt = [width * 0.64, height * 0.52];
  const cam = camAt(C, C, hold * (1 - 0.06 * exit));
  const upName = items[0]?.label || "Upper Basin";
  const loName = items[1]?.label || "Lower Basin";
  const suffix = str(overlay.suffix).trim(), prefix = str(overlay.prefix).trim();
  const uC = toScreen(geo.upperC, cam), lC = toScreen(geo.lowerC, cam), lees = toScreen(geo.lees, cam);
  // The two label blocks, and the state names that would sit under them (those stay out).
  const uB: Pt = [uC[0], uC[1] - 40 * k], lB: Pt = [lC[0], lC[1] + 80 * k];
  const underBlock = (p: Pt) => [uB, lB].some((b) => Math.abs(p[0] - b[0]) < 230 * k && Math.abs(p[1] - b[1]) < 100 * k);

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="64% 52%" />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn }}>
        <g transform={camXf(cam)}>
          <path d={geo.allD} fill={LAND} fillOpacity={0.7} stroke={BORDER} strokeWidth={1 * k} strokeLinejoin="round" />
          {geo.upper.map((s, i) => (
            <path key={`u${i}`} d={s.d} fill={mix(LAND, accent, 0.45 * upP)} stroke={mix(BORDER, accent, 0.7 * upP)}
              strokeWidth={1.4 * k} strokeLinejoin="round" />
          ))}
          {geo.lower.map((s, i) => (
            <path key={`l${i}`} d={s.d} fill={mix(LAND, SAND, 0.42 * loP)} stroke={mix(BORDER, SAND, 0.7 * loP)}
              strokeWidth={1.4 * k} strokeLinejoin="round" />
          ))}
          {[...geo.upper, ...geo.lower].map((s, i) => {
            const p = i < geo.upper.length ? upP : loP;
            return <path key={`o${i}`} d={s.d} fill="none" stroke={i < geo.upper.length ? accent : SAND} strokeWidth={2 * k}
              strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} opacity={0.9} />;
          })}
          {lineP > 0 ? (
            <g>
              <path d={partialD(geo.divide, geo.divideCum, lineP * geo.divideTotal)} fill="none" stroke="rgba(0,0,0,.6)"
                strokeWidth={9 * k} strokeLinecap="round" strokeLinejoin="round" />
              <path d={partialD(geo.divide, geo.divideCum, lineP * geo.divideTotal)} fill="none" stroke="#fff" strokeWidth={3 * k}
                strokeLinecap="round" strokeLinejoin="round" strokeDasharray={`${12 * k} ${10 * k}`} />
            </g>
          ) : null}
          {[...geo.upper, ...geo.lower].map((s, i) => {
            const p = ramp(frame, (i < geo.upper.length ? upAt : loAt) + 10 + i * 2, 12) * vis;
            const nm = cap(s.name);
            return p > 0 && nm && !underBlock(toScreen(s.c, cam)) ? (
              <text key={`n${i}`} x={s.c[0]} y={s.c[1] + 8 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={800} fontSize={22 * k}
                letterSpacing={`${0.16 * 22 * k}`} fill="rgba(255,255,255,.7)" opacity={p}
                style={{ paintOrder: "stroke", stroke: "rgba(4,7,11,.7)", strokeWidth: 4 * k }}>{nm}</text>
            ) : null;
          })}
        </g>
        {leesP > 0 ? (
          <g opacity={leesP}>
            <circle cx={lees[0]} cy={lees[1]} r={(14 + 26 * ((frame % Math.round(fps * 1.4)) / Math.round(fps * 1.4))) * k} fill="none"
              stroke="#fff" strokeWidth={2 * k} opacity={1 - (frame % Math.round(fps * 1.4)) / Math.round(fps * 1.4)} />
            <circle cx={lees[0]} cy={lees[1]} r={8 * k * leesP} fill="#fff" stroke="#0b0e13" strokeWidth={2.5 * k} />
          </g>
        ) : null}
      </svg>
      <Vignette strength={0.6} />
      <HalfLabel at={upAt + 12} x={uB[0]} y={uB[1]} name={upName} color={mix(accent, "#ffffff", 0.35)} item={items[0]}
        prefix={prefix} suffix={suffix} />
      <HalfLabel at={loAt + 12} x={lB[0]} y={lB[1]} name={loName} color={mix(SAND, "#ffffff", 0.3)} item={items[1]}
        prefix={prefix} suffix={suffix} />
      <div style={{ position: "absolute", left: lees[0] + 22 * k, top: lees[1] + 10 * k }}>
        <Rise at={leesAt}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 20 * k, letterSpacing: "0.2em", color: "#fff",
            whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.95)" }}>LEES FERRY · THE DIVIDE</span>
        </Rise>
      </div>
      <Tick at={leesAt + 1} volume={0.2} />
      <Title overlay={overlay} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== 5. state callout
/**
 * The lower 48, then a push onto one state (the place's, or the one named by
 * overlay.label / text; Arizona by default). The state tints and its outline
 * draws on; a callout line runs from it to a glass figure box on the other
 * side of the frame: kicker, the value rolling with its unit, the text.
 */
const StateCallout: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const hold = useHold();
  const id = useSvgId("bmc");
  const place = placesOf(overlay, 1)[0];
  const lat = place ? place.lat : NaN, lon = place ? place.lon : NaN;
  const label = str(overlay.label).trim();
  const geo = React.useMemo(() => {
    const p: MapLocation | null = Number.isFinite(lat) && Number.isFinite(lon) ? { label: "", lat, lon } : null;
    const st = (p && stateOf(p)) || stateNamed(label) || stateNamed(str(overlay.text)) || LOWER48.find((f) => fips(f) === 4) || LOWER48[0];
    const proj = geoMercator().fitExtent([[120 * k, 90 * k], [width - 120 * k, height - 80 * k]], LOWER48_FC as never);
    const path = geoPath(proj);
    return {
      allD: path(LOWER48_FC as never) || "",
      hitD: path(st as never) || "",
      b: path.bounds(st as never) as [Pt, Pt],
      c: path.centroid(st as never) as Pt,
      pin: p ? ((proj([lon, lat]) || null) as Pt | null) : null,
      name: st.properties?.name || "",
    };
  }, [lat, lon, label, overlay.text, width, height, k]);

  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, Math.round(fps * 0.5));
  const zoomAt = Math.round(fps * 0.4);
  const Z = Math.round(fps * 1.2);
  const settle = zoomAt + Z;
  const [[bx0, by0], [bx1, by1]] = geo.b;
  const ok = [bx0, by0, bx1, by1, geo.c[0], geo.c[1]].every(Number.isFinite);
  const bw = ok ? Math.max(1, bx1 - bx0) : width, bh = ok ? Math.max(1, by1 - by0) : height;
  const sEnd = lim(Math.min((width * 0.4) / bw, (height * 0.62) / bh), 1.6, 3.2);
  const C: Pt = ok ? [(bx0 + bx1) / 2, (by0 + by1) / 2] : [width / 2, height / 2];
  const T: Pt = [width * 0.34, height * 0.52];
  const move = ramp(frame, zoomAt, Z, inOut);
  const s = (1 + (sEnd - 1) * move) * hold * (1 - 0.1 * exit);
  const P: Pt = [C[0] + (T[0] - C[0]) * move, C[1] + (T[1] - C[1]) * move];
  const cam = camAt(C, P, s);
  const dim = ramp(frame, zoomAt, 20) * vis;
  const outline = ramp(frame, zoomAt + 4, Math.round(fps * 0.9), inOut);
  const glow = ramp(frame, zoomAt + 10, Math.round(fps * 0.8)) * vis;
  const anchor = toScreen(geo.pin && ok ? geo.pin : geo.c, cam);
  const boxX = width * 0.58, boxY = height * 0.5;
  const boxAt = settle - 6;
  const leadP = ramp(frame, boxAt - 8, 16, inOut) * vis;
  const elbow: Pt = [boxX - 70 * k, anchor[1] < boxY ? boxY - 60 * k : boxY + 60 * k];
  const boxP = ramp(frame, boxAt, 14, backOut) * vis;
  const value = Number(overlay.value);
  const has = Number.isFinite(value);
  const suffix = str(overlay.suffix).trim(), prefix = str(overlay.prefix).trim();
  const kicker = label && norm(label) !== norm(geo.name) ? label : str(overlay.subtitle).trim() || geo.name;
  const body = str(overlay.text).trim();
  const bodyLines = wrap(body, has ? 30 : 22, has ? 2 : 3);
  const period = Math.round(fps * 1.5);
  const q = (frame % period) / period;

  // The callout line: anchor -> elbow -> box edge, drawing on as two segments.
  const seg1 = Math.hypot(elbow[0] - anchor[0], elbow[1] - anchor[1]);
  const seg2 = Math.abs(boxX - elbow[0]);
  const totalL = seg1 + seg2 || 1;
  const runL = leadP * totalL;
  const l1 = Math.min(1, runL / (seg1 || 1));
  const l2 = Math.max(0, Math.min(1, (runL - seg1) / (seg2 || 1)));
  const e1: Pt = [anchor[0] + (elbow[0] - anchor[0]) * l1, anchor[1] + (elbow[1] - anchor[1]) * l1];

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="40% 52%" />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn * (1 - 0.6 * exit) }}>
        <defs>
          <filter id={`${id}b`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation={(16 * k) / s} />
          </filter>
        </defs>
        <g transform={camXf(cam)}>
          <path d={geo.allD} fill={LAND} fillOpacity={1 - 0.4 * dim} stroke={EDGE} strokeOpacity={1 - 0.3 * dim} strokeWidth={(1 * k) / s}
            strokeLinejoin="round" />
          {glow > 0 ? <path d={geo.hitD} fill={accent} opacity={0.5 * glow} filter={`url(#${id}b)`} /> : null}
          <path d={geo.hitD} fill={mix(LAND, accent, 0.32 * dim)} stroke={mix(EDGE, accent, 0.6 * dim)} strokeWidth={(1.2 * k) / s}
            strokeLinejoin="round" />
          <path d={geo.hitD} fill="none" stroke={accent} strokeWidth={(3 * k) / s} strokeLinejoin="round" pathLength={1}
            strokeDasharray="1 1" strokeDashoffset={1 - outline} opacity={vis} />
        </g>
        {geo.pin && ok && move > 0.6 ? (
          <g opacity={vis * ramp(frame, settle - 8, 10)}>
            <circle cx={anchor[0]} cy={anchor[1]} r={(10 + 50 * q) * k} fill="none" stroke="#fff" strokeWidth={2 * k} opacity={(1 - q) * 0.8} />
            <circle cx={anchor[0]} cy={anchor[1]} r={8 * k} fill="#fff" stroke={mix(accent, "#000000", 0.35)} strokeWidth={3 * k} />
          </g>
        ) : null}
        {leadP > 0 ? (
          <g opacity={vis}>
            <path d={`M${anchor[0].toFixed(1)} ${anchor[1].toFixed(1)} L${e1[0].toFixed(1)} ${e1[1].toFixed(1)}${l2 > 0
              ? ` L${(elbow[0] + (boxX - elbow[0]) * l2).toFixed(1)} ${elbow[1].toFixed(1)}` : ""}`} fill="none" stroke="#fff"
              strokeOpacity={0.85} strokeWidth={2 * k} strokeLinecap="round" strokeLinejoin="round" />
            <circle cx={anchor[0]} cy={anchor[1]} r={5 * k} fill={accent} stroke="#fff" strokeWidth={1.5 * k} />
          </g>
        ) : null}
      </svg>
      <Vignette strength={0.65} />
      {ok ? (
        <div style={{ position: "absolute", left: toScreen(geo.c, cam)[0], top: toScreen(geo.c, cam)[1] + (geo.pin ? 26 : -14) * k,
          transform: "translate(-50%, 0)" }}>
          <Rise at={settle - 10} frames={14}>
            <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.22em", color: "#fff",
              whiteSpace: "nowrap", textShadow: "0 2px 12px rgba(0,0,0,.95)" }}>{cap(geo.name)}</span>
          </Rise>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: boxX, top: elbow[1], transform: `translate(0, -50%) scale(${Math.max(0.001, boxP).toFixed(3)})`,
        transformOrigin: "0% 50%", opacity: Math.min(1, boxP * 1.4), width: width - boxX - 100 * k, boxSizing: "border-box",
        padding: `${26 * k}px ${34 * k}px`, background: "rgba(6,12,20,.78)", border: `1px solid ${alpha(accent, 0.45)}`,
        borderLeft: `${6 * k}px solid ${accent}`, boxShadow: `0 ${18 * k}px ${50 * k}px rgba(0,0,0,.6), 0 0 ${30 * k}px ${alpha(accent, 0.18)}`,
        backdropFilter: "blur(6px)" }}>
        <Rise at={boxAt + 2}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.24em", color: accent,
            whiteSpace: "nowrap" }}>{clip(cap(kicker), 30)}</span>
        </Rise>
        {has ? (
          <Rise at={boxAt + 5} style={{ marginTop: 6 * k }}>
            <Odometer value={value} at={boxAt + 5} frames={Math.round(fps * 0.9)} size={108 * k} color="#fff" prefix={prefix}
              suffix={suffix ? (suffix === "%" ? "%" : ` ${cap(suffix)}`) : ""} suffixColor={accent} suffixScale={0.42} />
          </Rise>
        ) : null}
        {bodyLines.map((ln, i) => (
          <Rise key={i} at={boxAt + 10 + i * 4} style={{ marginTop: i ? 0 : 8 * k }}>
            <span style={{ fontFamily: has ? LABEL : DISPLAY, fontWeight: has ? 600 : 400, fontSize: (has ? 30 : 54) * k,
              lineHeight: 1.1, color: has ? "rgba(255,255,255,.82)" : "#fff", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>{has ? ln : ln.toUpperCase()}</span>
          </Rise>
        ))}
      </div>
      <Tick at={boxAt + 4} volume={0.22} />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "bm-usa-zoom": UsaZoom,
  "bm-basin-zoom": BasinZoom,
  "bm-river-network": RiverNetwork,
  "bm-basin-split": BasinSplit,
  "bm-state-callout": StateCallout,
};
