import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { geoContains, geoGraticule10, geoInterpolate, geoMercator, geoOrthographic, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import topology from "world-atlas/countries-110m.json";
import statesTopology from "../../data/us-states.json";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay, OverlayItem } from "../../types";
import { Odometer, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { CaseBackdrop } from "../pro/ProCase";

/**
 * Vector maps drawn without tiles (family "mv-"): every look draws its own
 * full-frame backdrop from the bundled world / US-state outlines, so it
 * renders offline and the same in the editor and on the worker.
 *
 *   mv-globe-spin          an orthographic globe spins to face the place, a pin drops, ripples
 *   mv-state-glow          the US state (or country) holding the place fills like a tank and glows
 *   mv-arc-flight          a great-circle arc lifts between two places, a comet rides it, distance rolls
 *   mv-impact-radius       a zone of value+suffix radius punches out around the place, sonar and dial ticks
 *   mv-choropleth-lift     states shaded by their values rise as extruded blocks, a legend needle tracks them
 *   mv-pinboard-list       numbered pins drop one by one on the map while a ranked list builds beside it
 *   mv-coordinate-hud      a cyan targeting HUD: crosshair slides in, lat/lon tick, reticle locks
 *   mv-river-draw          a meandering line flows through every place in order, water streaming along it
 *   mv-country-spotlight   the world dims while the place's country lifts off the map toward the camera
 *   mv-zoom-inset          a country map, a focus box, and the box flying out into a magnified inset
 *
 * Coordinates always come from the gazetteer (overlay.locations); nothing here
 * invents a place. All motion is a pure function of the frame.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];
type Geometry = { type: string; coordinates: unknown };
type Feat = { type: string; id?: string | number; properties?: { name?: string }; geometry: Geometry | null };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };

// ------------------------------------------------------------------ geography
const ALL_COUNTRIES = (feature(topology as never, topology.objects.countries as never) as unknown as FeatColl).features;
const WORLD: Feat[] = ALL_COUNTRIES.filter((f) => f.properties?.name !== "Antarctica");
const ALL_STATES = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features;
const LOWER48: Feat[] = ALL_STATES.filter((f) => {
  const id = Number(f.id);
  return Number.isFinite(id) && id <= 56 && id !== 2 && id !== 15;
});
const fc = (features: Feat[]): FeatColl => ({ type: "FeatureCollection", features });
const WORLD_FC = fc(WORLD);
const STATES_FC = fc(ALL_STATES);
const LOWER48_FC = fc(LOWER48);

// ------------------------------------------------------------------ constants
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expo = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const CYAN = "#53c8ff";
const LAND = "#1a212b";
const EDGE = "#2e3845";
const LOWC = "#3a4351";
const RAD = Math.PI / 180;
const US_BOXES = [[18, 50, -126, -65], [51, 72, -170, -129], [18, 23, -161, -154]];

// ------------------------------------------------------------------ small helpers
const cap = (s?: string) => (s || "").toUpperCase();
const short = (l?: string) => (l || "").split(",")[0].trim();
const norm = (s?: string) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const clampLat = (v: number) => Math.max(-84, Math.min(84, v));
const lin = (frame: number, a: number, b: number) => interpolate(frame, [a, Math.max(a + 1, b)], [0, 1], clamp);
/** Deterministic 0..1 noise from an integer (no Math.random in a render). */
const rnd = (i: number) => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
const inUS = (p: MapLocation) => US_BOXES.some(([a, b, c, d]) => p.lat >= a && p.lat <= b && p.lon >= c && p.lon <= d);
const fmtLat = (v: number, d = 4) => `${Math.abs(v).toFixed(d)}° ${v >= 0 ? "N" : "S"}`;
const fmtLon = (v: number, d = 4) => `${Math.abs(v).toFixed(d)}° ${v >= 0 ? "E" : "W"}`;
const wrapLon = (v: number) => ((((v + 180) % 360) + 360) % 360) - 180;

const hexRgb = (h: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i.exec((h || "").trim());
  if (!m) return [242, 181, 68];
  let s = m[1];
  if (s.length === 3) s = s.split("").map((c) => c + c).join("");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
const mix = (a: string, b: string, t: number) => {
  const A = hexRgb(a), B = hexRgb(b);
  const u = Math.max(0, Math.min(1, t));
  return `#${A.map((v, i) => Math.round(v + (B[i] - v) * u).toString(16).padStart(2, "0")).join("")}`;
};
const alpha = (h: string, a: number) => {
  const [r, g, b] = hexRgb(h);
  return `rgba(${r},${g},${b},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
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
/** A document-unique id for SVG defs, so two instances of a look never share a gradient or clip. */
const useSvgId = (prefix: string) => `${prefix}${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;

/** Valid gazetteer places only: finite, in range, labels as strings. */
const placesOf = (ov: Overlay, max: number): MapLocation[] => {
  const out: MapLocation[] = [];
  for (const p of Array.isArray(ov.locations) ? ov.locations : []) {
    if (!p) continue;
    const lat = Number(p.lat), lon = Number(p.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
    out.push({ label: String(p.label || ""), lat, lon, kind: p.kind });
    if (out.length >= max) break;
  }
  return out;
};
const placeKey = (ps: MapLocation[]) => ps.map((p) => `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`).join("|");

const meanLon = (ps: MapLocation[]) => {
  let sx = 0, sy = 0;
  for (const p of ps) {
    sx += Math.cos(p.lon * RAD);
    sy += Math.sin(p.lon * RAD);
  }
  return Math.abs(sx) < 1e-9 && Math.abs(sy) < 1e-9 ? 0 : Math.atan2(sy, sx) / RAD;
};

const milesBetween = (a: MapLocation, b: MapLocation) => {
  const h = Math.sin(((b.lat - a.lat) * RAD) / 2) ** 2 +
    Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(((b.lon - a.lon) * RAD) / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
};

const contains = (f: Feat, p: MapLocation) => {
  try {
    return geoContains(f as never, [p.lon, p.lat]);
  } catch {
    return false;
  }
};
const stateOf = (p: MapLocation) => ALL_STATES.find((f) => contains(f, p)) || null;
const countryOf = (p: MapLocation) => WORLD.find((f) => contains(f, p)) || null;

/** The polygon of a multipolygon that holds the place (France, not French Guiana), else the biggest. */
const ringCount = (f: Feat) => {
  const c = f.geometry?.coordinates as number[][][] | undefined;
  return c && c[0] ? c[0].length : 0;
};
const pickPart = (f: Feat, p?: MapLocation): Feat => {
  const g = f.geometry;
  if (!g || g.type !== "MultiPolygon" || !Array.isArray(g.coordinates)) return f;
  const parts: Feat[] = (g.coordinates as number[][][][]).map((c) => ({
    type: "Feature", properties: f.properties, geometry: { type: "Polygon", coordinates: c },
  }));
  if (!parts.length) return f;
  if (p) {
    const loc: MapLocation = p;
    const hit = parts.find((q) => contains(q, loc));
    if (hit) return hit;
  }
  return parts.reduce((m, q) => (ringCount(q) > ringCount(m) ? q : m), parts[0]);
};

// ------------------------------------------------------------------ polyline helpers
const cumOf = (pts: Pt[]) => {
  const c = [0];
  for (let i = 1; i < pts.length; i++) c.push(c[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return c;
};
const along = (pts: Pt[], cum: number[], run: number): { p: Pt; i: number; ang: number } => {
  if (pts.length < 2) return { p: pts[0] || [0, 0], i: 0, ang: 0 };
  const total = cum[cum.length - 1];
  const r = Math.max(0, Math.min(total, run));
  let i = 0;
  while (i < pts.length - 2 && cum[i + 1] < r) i++;
  const seg = cum[i + 1] - cum[i] || 1;
  const t = Math.max(0, Math.min(1, (r - cum[i]) / seg));
  const a = pts[i], b = pts[i + 1];
  return { p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], i, ang: Math.atan2(b[1] - a[1], b[0] - a[0]) };
};
const partialD = (pts: Pt[], cum: number[], run: number) => {
  if (pts.length < 2 || run <= 0) return "";
  const h = along(pts, cum, run);
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let j = 1; j <= h.i; j++) d += ` L${pts[j][0].toFixed(1)} ${pts[j][1].toFixed(1)}`;
  return `${d} L${h.p[0].toFixed(1)} ${h.p[1].toFixed(1)}`;
};
const polyD = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
const catmull = (p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: number): Pt => {
  const t2 = t * t, t3 = t2 * t;
  const f = (a: number, b: number, c: number, d: number) =>
    0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
  return [f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1])];
};

// ------------------------------------------------------------------ shared pieces
/** 0 -> 1 over the last 13 frames: every look leaves on it. */
const useExit = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - 13, 11, easeIn);
};

/** A line rising out of its mask, and leaving upward through it at the end. */
const Rise: React.FC<{ at: number; frames?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 16, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, durationInFrames - 13, 10, easeIn);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.1em", ...style }}>
        <div style={{ transform: `translateY(${(1 - pin) * 112 - pout * 112}%)` }}>{children}</div>
      </div>
    );
  };

/**
 * Letters rising out of their mask one after another (the house LetterLine
 * reveal), but leaving on a stagger compressed to the line's length so even a
 * long line is fully gone inside the last 13 frames. LetterLine's fixed
 * 0.6-frame exit stagger left the tail of any line over ~8 letters on screen
 * at the cut.
 */
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

/** "36.0161° N · 114.7377° W" in the mono UI face. */
const Coords: React.FC<{ lat: number; lon: number; at: number; color?: string; align?: "left" | "right" }> =
  ({ lat, lon, at, color = CYAN, align = "left" }) => {
    const k = useK();
    return (
      <Rise at={at} style={{ marginTop: 16 * k, textAlign: align }}>
        <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.14em", color, whiteSpace: "nowrap" }}>
          {fmtLat(lat)}{"  ·  "}{fmtLon(lon)}
        </span>
      </Rise>
    );
  };

/** A place name beside its point: a mono kicker over a condensed name, set on the outer side. */
const EndLabel: React.FC<{
  x: number; y: number; side: "left" | "right"; kicker: string; name: string; accent: string; at: number;
  size?: number; extra?: number; children?: React.ReactNode;
}> = ({ x, y, side, kicker, name, accent, at, size = 50, extra = 0, children }) => {
  const k = useK();
  const { width, height } = useVideoConfig();
  const onLeft = side === "left";
  const nl = wrap(cap(name), 16, 2);
  // The first name line sits level with the point; near an edge the label
  // slides along its side to stay inside the 90 px safe area.
  const estH = (36 + nl.length * (size + 4) + extra) * k;
  const top = Math.max(96 * k, Math.min(height - 96 * k - estH, y - (35 + size * 0.5) * k));
  return (
    <div style={{ position: "absolute", top, left: onLeft ? undefined : x + 30 * k,
      right: onLeft ? width - x + 30 * k : undefined, display: "flex", flexDirection: "column",
      alignItems: onLeft ? "flex-end" : "flex-start" }}>
      <Letters text={cap(kicker)} at={at} step={0.5} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
        letterSpacing: "0.24em", color: accent, whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.8)" }} />
      {nl.map((ln, i) => (
        <Letters key={i} text={ln} at={at + 3 + i * 4} step={0.7} style={{ fontFamily: DISPLAY, fontSize: size * k,
          lineHeight: 1, color: "#fff", letterSpacing: "0.02em", whiteSpace: "nowrap", textAlign: onLeft ? "right" : "left",
          textShadow: "0 4px 20px rgba(0,0,0,.85)" }} />
      ))}
      {children}
    </div>
  );
};
const labelW = (name: string, size: number, k: number) =>
  Math.max(...wrap(cap(name), 16, 2).map((l) => l.length), 4) * size * 0.43 * k + 40 * k;

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

/** A soft dark falloff behind a label column so type reads over the map. */
const SideShade: React.FC<{ side: "left" | "right"; opacity?: number }> = ({ side, opacity = 1 }) => (
  <AbsoluteFill style={{ opacity, pointerEvents: "none",
    background: `linear-gradient(${side === "left" ? 90 : 270}deg, rgba(4,6,10,.86) 0%, rgba(4,6,10,.55) 26%, rgba(4,6,10,0) 46%)` }} />
);

const FULL: React.CSSProperties = { position: "absolute", left: 0, top: 0 };
const PIN_D = "M0 0 C-5 -15 -20 -26 -20 -46 A20 20 0 1 1 20 -46 C20 -26 5 -15 0 0 Z";

// ================================================================== 1. spinning globe
/**
 * Deep space, an atmosphere rim, a lit ocean sphere. The globe spins in from
 * the west, slows onto the place and pushes in; the country tints, a pin drops
 * with a bounce, ripples roll out and a leader line runs to the name.
 */
const GlobeSpin: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const id = useSvgId("mvgl");
  const place = placesOf(overlay, 1)[0];
  const lat = place ? place.lat : 0;
  const lon = place ? place.lon : 0;
  const country = React.useMemo(() => countryOf({ label: "", lat, lon }), [lat, lon]);
  const stars = React.useMemo(() => Array.from({ length: 64 }, (_, i) => ({
    x: rnd(i * 3 + 1), y: rnd(i * 3 + 2), r: 0.6 + rnd(i * 3 + 3) * 1.7, ph: rnd(i * 5 + 7) * Math.PI * 2,
  })), []);
  if (!place) return null;

  // The spin scales with the beat so a 3 s overlay still lands its text with time to read it.
  const land = Math.round(Math.max(fps * 0.95, Math.min(fps * 1.7, durationInFrames * 0.36)));
  const spin = ramp(frame, 0, land, inOut);
  const drift = Math.max(0, frame - land) * 0.035;
  const cx = width * 0.63, cy = height * 0.5;
  const R = 340 * k * (0.9 + 0.1 * ramp(frame, 0, 24)) *
    (1 + 0.1 * ramp(frame, land - 6, durationInFrames - land, inOut));
  const proj = geoOrthographic()
    .rotate([-lon - 150 * (1 - spin) + drift, -(18 + (lat - 18) * spin), 0])
    .translate([cx, cy]).scale(R).clipAngle(90);
  const path = geoPath(proj);
  const sphere = path({ type: "Sphere" } as never) || "";
  const grat = path(geoGraticule10() as never) || "";
  const landD = path(WORLD_FC as never) || "";
  const hl = ramp(frame, land - 12, 18) * (1 - 0.5 * exit);
  const hitD = country && hl > 0 ? path(country as never) || "" : "";
  const pt = (proj([lon, lat]) || [cx, cy]) as Pt;

  const dropAt = land - 4;
  const drop = frame < dropAt ? 0 : spring({ frame: frame - dropAt, fps, config: { damping: 11, stiffness: 160, mass: 0.7 } });
  const pinS = 1.1 * k;
  const pinY = pt[1] - (1 - drop) * 240 * k - exit * 50 * k;
  const headY = pinY - 46 * pinS;
  const leadP = ramp(frame, dropAt + 10, 16) * (1 - exit);
  const leadX0 = pt[0] - 26 * pinS;
  const leadX1 = 830 * k;
  const period = Math.round(fps * 1.6);
  const cname = country?.properties?.name || "";
  const label = short(place.label) || cname;
  const kicker = overlay.subtitle || (cname && norm(cname) !== norm(label) ? cname : "Location");
  const body = overlay.text && norm(overlay.text) !== norm(label) ? overlay.text : "";
  // The kicker leads while the globe settles; the name rises as the pin lands.
  const textAt = land - 8;

  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 63% 50%, #0d1a2e 0%, #060b15 45%, #020306 100%)",
      overflow: "hidden" }}>
      <svg width={width} height={height} style={FULL}>
        <defs>
          <radialGradient id={`${id}o`} cx="38%" cy="32%" r="75%">
            <stop offset="0%" stopColor="#1f4a7c" />
            <stop offset="55%" stopColor="#0d2544" />
            <stop offset="100%" stopColor="#040b18" />
          </radialGradient>
          <radialGradient id={`${id}s`} cx="36%" cy="30%" r="78%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity={0.14} />
            <stop offset="50%" stopColor="#000000" stopOpacity={0} />
            <stop offset="100%" stopColor="#000000" stopOpacity={0.62} />
          </radialGradient>
          <radialGradient id={`${id}a`} cx="50%" cy="50%" r="50%">
            <stop offset="80%" stopColor="#5fb4ff" stopOpacity={0} />
            <stop offset="86.5%" stopColor="#5fb4ff" stopOpacity={0.42} />
            <stop offset="100%" stopColor="#5fb4ff" stopOpacity={0} />
          </radialGradient>
        </defs>
        {stars.map((s, i) => (
          <circle key={i} cx={s.x * width} cy={s.y * height} r={s.r * k} fill="#dfeaff"
            opacity={0.2 + 0.45 * (0.5 + 0.5 * Math.sin(frame * 0.07 + s.ph))} />
        ))}
        <circle cx={cx} cy={cy} r={R * 1.16} fill={`url(#${id}a)`} />
        <path d={sphere} fill={`url(#${id}o)`} />
        <path d={grat} fill="none" stroke="rgba(150,200,255,.13)" strokeWidth={1 * k} />
        <path d={landD} fill="#2b3b50" stroke="#4d6582" strokeWidth={0.8 * k} strokeLinejoin="round" />
        {hitD ? (
          <path d={hitD} fill={accent} fillOpacity={0.88 * hl} stroke="#fff" strokeOpacity={hl} strokeWidth={1.6 * k}
            strokeLinejoin="round" />
        ) : null}
        <path d={sphere} fill={`url(#${id}s)`} />
        <path d={sphere} fill="none" stroke="rgba(160,210,255,.35)" strokeWidth={1.5 * k} />
        {frame >= dropAt + 8 ? [0, 1, 2].map((j) => {
          const f0 = frame - (dropAt + 8) - j * (period / 3);
          if (f0 < 0) return null;
          const q = (f0 % period) / period;
          return <ellipse key={j} cx={pt[0]} cy={pt[1]} rx={(10 + 110 * q) * k} ry={(10 + 110 * q) * 0.9 * k} fill="none"
            stroke={accent} strokeWidth={3 * k} opacity={(1 - q) * 0.85 * (1 - exit)} />;
        }) : null}
        {leadP > 0 ? (
          <g opacity={1 - exit}>
            <line x1={leadX0} y1={headY} x2={leadX0 + (leadX1 - leadX0) * leadP} y2={headY} stroke="rgba(255,255,255,.8)"
              strokeWidth={1.6 * k} />
            <circle cx={leadX0 + (leadX1 - leadX0) * leadP} cy={headY} r={4.5 * k * leadP} fill={accent} />
          </g>
        ) : null}
        {frame >= dropAt ? (
          <g opacity={(1 - exit) * ramp(frame, dropAt, 4)}>
            <ellipse cx={pt[0]} cy={pt[1]} rx={15 * k * drop} ry={5 * k * drop} fill="rgba(0,0,0,.5)" />
            <g transform={`translate(${pt[0].toFixed(1)} ${pinY.toFixed(1)}) scale(${pinS.toFixed(4)})`}>
              <path d={PIN_D} fill={accent} stroke="#fff" strokeWidth={2.4} strokeLinejoin="round" />
              <circle cx={0} cy={-46} r={7.5} fill="#0b0e13" />
            </g>
          </g>
        ) : null}
      </svg>
      <Vignette strength={0.6} />
      <div style={{ position: "absolute", left: 110 * k, top: cy - 46 * pinS - 96 * k, width: 700 * k }}>
        <TextBlock kicker={kicker} title={label} body={body} accent={accent} at={textAt} size={80}>
          <Coords lat={place.lat} lon={place.lon} at={textAt + 16} />
        </TextBlock>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. state glow
/**
 * A dark US map. The camera eases toward the state holding the place, its
 * outline draws on, then it fills from the bottom like a tank (a wavy
 * surface with a bright crest) and glows while the rest of the map dims.
 * Outside the US the same move runs on the country.
 */
const StateGlow: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const id = useSvgId("mvsg");
  const place = placesOf(overlay, 1)[0];
  const lat = place ? place.lat : NaN;
  const lon = place ? place.lon : NaN;
  const geo = React.useMemo(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    const p: MapLocation = { label: "", lat, lon };
    const st = stateOf(p);
    const hit = st || countryOf(p);
    if (!hit) return null;
    const part = pickPart(hit, p);
    const lower = Boolean(st && LOWER48.includes(st));
    const proj = geoMercator();
    if (lower) proj.fitExtent([[170 * k, 140 * k], [width - 170 * k, height - 110 * k]], LOWER48_FC as never);
    else proj.rotate([-lon, 0]).fitExtent([[width * 0.3, height * 0.26], [width * 0.7, height * 0.74]], part as never);
    const path = geoPath(proj);
    return {
      ctxD: path(WORLD_FC as never) || "",
      baseD: st ? path((lower ? LOWER48_FC : STATES_FC) as never) || "" : "",
      hitD: path(hit as never) || "",
      b: path.bounds(part as never) as [Pt, Pt],
      fb: path.bounds((st ? hit : part) as never) as [Pt, Pt],
      c: path.centroid(part as never) as Pt,
      pin: (proj([lon, lat]) || [width / 2, height / 2]) as Pt,
      name: hit.properties?.name || "",
      us: Boolean(st),
    };
  }, [lat, lon, width, height, k]);
  if (!place || !geo || !Number.isFinite(geo.c[0]) || !Number.isFinite(geo.b[0][0])) return null;

  const bw = Math.max(1, geo.b[1][0] - geo.b[0][0]), bh = Math.max(1, geo.b[1][1] - geo.b[0][1]);
  const sEnd = Math.max(1, Math.min(2.6, (height * 0.5) / bh, (width * 0.34) / bw));
  const labelLeft = geo.c[0] >= width / 2;
  const T: Pt = [labelLeft ? width * 0.67 : width * 0.33, height * 0.52];
  const settle = Math.round(fps * 1.7);
  const move = 0.9 * ramp(frame, 4, settle, inOut) + 0.1 * lin(frame, settle, durationInFrames);
  const s = 1 + (sEnd - 1) * move;
  const Px = geo.c[0] + (T[0] - geo.c[0]) * move, Py = geo.c[1] + (T[1] - geo.c[1]) * move;
  const tx = Px - geo.c[0] * s, ty = Py - geo.c[1] * s;
  const mapIn = ramp(frame, 0, 18);
  const outline = ramp(frame, 6, Math.round(fps * 0.7), inOut);
  const fillAt = Math.round(fps * 0.55);
  const fillP = ramp(frame, fillAt, Math.round(fps * 0.8), inOut);
  const dim = ramp(frame, fillAt - 4, 20);
  const vis = 1 - exit;

  // The liquid: a wavy surface rising through the state's box.
  const [[fx0, fy0], [fx1, fy1]] = geo.fb;
  const fw = Math.max(1, fx1 - fx0), fh = Math.max(1, fy1 - fy0);
  const amp = (7 * k) / s;
  const level = fy1 - fh * 1.08 * fillP;
  let wave = `M${(fx0 - 20).toFixed(1)} ${(fy1 + 20).toFixed(1)}`;
  let crest = "";
  for (let j = 0; j <= 28; j++) {
    const x = fx0 - 20 + ((fw + 40) * j) / 28;
    const y = level + Math.sin(j * 0.85 + frame * 0.3) * amp + Math.sin(j * 0.37 - frame * 0.17) * amp * 0.6;
    wave += ` L${x.toFixed(1)} ${y.toFixed(1)}`;
    crest += `${crest ? " L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }
  wave += ` L${(fx1 + 20).toFixed(1)} ${(fy1 + 20).toFixed(1)} Z`;

  const pin: Pt = [geo.pin[0] * s + tx, geo.pin[1] * s + ty];
  const pinP = ramp(frame, fillAt + Math.round(fps * 0.6), 14, backOut) * vis;
  const period = Math.round(fps * 1.4);
  const q = (frame % period) / period;
  const placeName = short(place.label);
  const kicker = overlay.subtitle || (placeName && norm(placeName) !== norm(geo.name) ? placeName : geo.us ? "U.S. state" : "Country");

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus={`${((T[0] / width) * 100).toFixed(0)}% 52%`} />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn }}>
        <defs>
          <filter id={`${id}b`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation={(16 * k) / s} />
          </filter>
          <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={mix(accent, "#ffffff", 0.22)} />
            <stop offset="100%" stopColor={mix(accent, "#000000", 0.25)} />
          </linearGradient>
          <clipPath id={`${id}w`}><path d={wave} /></clipPath>
          <clipPath id={`${id}h`}><path d={geo.hitD} /></clipPath>
        </defs>
        <g transform={`translate(${tx.toFixed(2)} ${ty.toFixed(2)}) scale(${s.toFixed(4)})`}>
          <path d={geo.ctxD} fill={geo.us ? "#11161d" : LAND} fillOpacity={geo.us ? 1 : 1 - 0.45 * dim}
            stroke={geo.us ? "#212833" : EDGE} strokeWidth={(1 * k) / s} strokeLinejoin="round" />
          {geo.baseD ? (
            <path d={geo.baseD} fill={LAND} fillOpacity={1 - 0.45 * dim} stroke={EDGE} strokeWidth={(1.1 * k) / s}
              strokeLinejoin="round" />
          ) : null}
          <path d={geo.hitD} fill={accent} opacity={0.6 * fillP * vis} filter={`url(#${id}b)`} />
          <path d={geo.hitD} fill={LAND} />
          <path d={geo.hitD} fill={`url(#${id}f)`} clipPath={`url(#${id}w)`} opacity={1 - 0.55 * exit} />
          {fillP > 0 && fillP < 1 ? (
            <path d={crest} fill="none" stroke="#fff" strokeOpacity={0.8} strokeWidth={(2.2 * k) / s} clipPath={`url(#${id}h)`} />
          ) : null}
          <path d={geo.hitD} fill="none" stroke={accent} strokeWidth={(3 * k) / s} strokeLinejoin="round" pathLength={1}
            strokeDasharray="1 1" strokeDashoffset={1 - outline} opacity={vis} />
          <path d={geo.hitD} fill="none" stroke="#fff" strokeOpacity={0.85 * fillP * vis} strokeWidth={(1.3 * k) / s}
            strokeLinejoin="round" />
        </g>
        {pinP > 0 ? (
          <g>
            <circle cx={pin[0]} cy={pin[1]} r={(12 + 60 * q) * k} fill="none" stroke="#fff" strokeWidth={2 * k}
              opacity={(1 - q) * 0.8 * pinP} />
            <circle cx={pin[0]} cy={pin[1]} r={9 * k * pinP} fill="#fff" stroke={mix(accent, "#000000", 0.35)} strokeWidth={3 * k} />
          </g>
        ) : null}
      </svg>
      <SideShade side={labelLeft ? "left" : "right"} opacity={ramp(frame, fillAt - 8, 16) * (1 - 0.6 * exit)} />
      <Vignette />
      <div style={{ position: "absolute", top: 0, bottom: 0, left: labelLeft ? 100 * k : undefined,
        right: labelLeft ? undefined : 100 * k, width: 720 * k, display: "flex", flexDirection: "column",
        justifyContent: "center", alignItems: labelLeft ? "flex-start" : "flex-end" }}>
        <TextBlock kicker={kicker} title={geo.name} body={overlay.text} accent={accent} at={fillAt - 4} size={84}
          align={labelLeft ? "left" : "right"}>
          <Coords lat={place.lat} lon={place.lon} at={fillAt + 18} align={labelLeft ? "left" : "right"} />
        </TextBlock>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. arc flight
/**
 * Two places on a dark world map. A great-circle arc lifts off the first and
 * draws to the second with a comet head and fading trail; its true ground
 * track shows as a faint dotted line beneath; the distance rolls at the
 * apex; the destination bursts when the head lands.
 */
const ArcFlight: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const hold = useHold();
  const places = placesOf(overlay, 2);
  const key = placeKey(places);
  const hasTitle = Boolean(overlay.text || overlay.subtitle);
  const geo = React.useMemo(() => {
    if (places.length < 2) return null;
    const [a, b] = places;
    const ip = geoInterpolate([a.lon, a.lat], [b.lon, b.lat]);
    const N = 80;
    const gc = Array.from({ length: N + 1 }, (_, i) => ip(i / N) as Pt);
    // Antipodal endpoints have no single great circle (the interpolator returns NaN).
    if (!gc.every((g) => Number.isFinite(g[0]) && Number.isFinite(g[1]))) return null;
    const cLon = meanLon(places);
    const cLat = (a.lat + b.lat) / 2;
    // A polar route's track is flattened at 80 degrees (Mercator has no pole) and
    // the whole of it is framed, so the arc never leaves the picture.
    const track: Pt[] = gc.map((g) => [g[0], Math.max(-80, Math.min(80, g[1]))]);
    const fitPts: Pt[] = [...track, [cLon - 16, clampLat(cLat - 9)], [cLon + 16, clampLat(cLat + 9)]];
    // The top band is left to the title, the bottom to the destination's name.
    const proj = geoMercator().rotate([-cLon, 0]).fitExtent([[340 * k, 330 * k], [width - 340 * k, height - 210 * k]],
      { type: "MultiPoint", coordinates: fitPts } as never);
    const path = geoPath(proj);
    const ground = track.map((g) => (proj(g) || [width / 2, height / 2]) as Pt);
    const A = ground[0], B = ground[N];
    const chord = Math.hypot(B[0] - A[0], B[1] - A[1]) || 1;
    let nx = -(B[1] - A[1]) / chord, ny = (B[0] - A[0]) / chord;
    if (ny > 0) {
      nx = -nx;
      ny = -ny;
    }
    // The bow keeps every lifted point inside the frame and clear of the title band.
    let room = Infinity;
    ground.forEach((g, i) => {
      const s = Math.sin((Math.PI * i) / N);
      if (s < 0.05) return;
      const yMin = hasTitle && g[0] < 820 * k ? 300 * k : 120 * k;
      if (nx > 1e-6) room = Math.min(room, (width - 110 * k - g[0]) / (nx * s));
      if (nx < -1e-6) room = Math.min(room, (g[0] - 110 * k) / (-nx * s));
      if (ny < -1e-6) room = Math.min(room, (g[1] - yMin) / (-ny * s));
    });
    const lift = Math.max(0, Math.min(250 * k, chord * 0.3, room));
    const arc = ground.map((g, i) => {
      const l = Math.sin((Math.PI * i) / N) * lift;
      return [g[0] + nx * l, g[1] + ny * l] as Pt;
    });
    return {
      landD: path(WORLD_FC as never) || "",
      statesD: places.every(inUS) ? path(LOWER48_FC as never) || "" : "",
      groundD: polyD(ground), arc, cum: cumOf(arc), A, B, miles: milesBetween(a, b), nx, ny,
    };
  }, [key, width, height, k, hasTitle]);
  if (!geo || places.length < 2) return null;

  const drawAt = Math.round(fps * 0.45);
  const D = Math.round(Math.max(fps * 0.9, Math.min(fps * 1.9, durationInFrames * 0.34)));
  const d = ramp(frame, drawAt, D, inOut);
  const total = geo.cum[geo.cum.length - 1] || 1;
  const run = d * total;
  const head = along(geo.arc, geo.cum, run).p;
  const arrive = drawAt + D;
  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, 16);
  const C: Pt = [width / 2, height / 2];
  const sc = (p: Pt): Pt => [C[0] + (p[0] - C[0]) * hold, C[1] + (p[1] - C[1]) * hold];
  const A = sc(geo.A), B = sc(geo.B);
  const aP = ramp(frame, 6, 14, backOut) * vis;
  const bP = ramp(frame, arrive - 2, 14, backOut) * vis;
  const period = Math.round(fps * 1.5);

  const raw = Number(overlay.value ?? NaN);
  const has = Number.isFinite(raw);
  const km = /^(km|kms|kilomet)/i.test((overlay.suffix || "").trim());
  const shown = has ? raw : Math.round(km ? geo.miles * 1.609344 : geo.miles);
  const unit = has ? (overlay.suffix ? ` ${cap(overlay.suffix)}` : "") : km ? " KM" : " MI";
  const caption = has ? cap(overlay.label || "") : "Great-circle distance";
  const apex = sc(geo.arc[Math.floor(geo.arc.length / 2)]);
  // A mostly east-west arc bows up: the figure sits over its apex. A north-south
  // one bows sideways: the figure sits beside the apex, on the outside of the
  // bow unless that side runs out of frame. Either way it stays in the safe area.
  const sideways = Math.abs(geo.nx) > Math.abs(geo.ny);
  // Over the apex means over both end labels too (a short hop keeps them close).
  const aboveY = Math.min(apex[1], A[1] - 64 * k, B[1] - 64 * k) - 150 * k;
  const above = aboveY >= (hasTitle ? 300 : 110) * k;
  const boxW = 490 * k;
  const fitsRight = apex[0] + 44 * k + boxW <= width - 90 * k;
  const fitsLeft = apex[0] - 44 * k - boxW >= 90 * k;
  const goRight = geo.nx > 0 ? fitsRight || !fitsLeft : !fitsLeft && fitsRight;
  const sideTop = Math.max(96 * k, Math.min(height - 220 * k, apex[1] - 70 * k));
  const numBox: React.CSSProperties = sideways
    ? { top: sideTop, left: goRight ? apex[0] + 44 * k : undefined,
      right: goRight ? undefined : width - apex[0] + 44 * k, alignItems: goRight ? "flex-start" : "flex-end" }
    : { left: Math.max(90 * k, Math.min(width - 730 * k, apex[0] - 320 * k)), width: 640 * k, alignItems: "center",
      top: above ? aboveY : Math.min(height - 220 * k, Math.max(A[1], B[1]) + 60 * k) };

  const nameA = short(places[0].label) || "Origin", nameB = short(places[1].label) || "Destination";
  let sideA: "left" | "right" = geo.A[0] <= geo.B[0] ? "left" : "right";
  let sideB: "left" | "right" = sideA === "left" ? "right" : "left";
  if (sideA === "left" && A[0] - labelW(nameA, 50, k) < 90 * k) sideA = "right";
  if (sideA === "right" && A[0] + labelW(nameA, 50, k) > width - 90 * k) sideA = "left";
  if (sideB === "left" && B[0] - labelW(nameB, 50, k) < 90 * k) sideB = "right";
  if (sideB === "right" && B[0] + labelW(nameB, 50, k) > width - 90 * k) sideB = "left";

  const trail: React.ReactNode[] = [];
  if (d > 0 && d < 1) {
    for (let j = 13; j >= 0; j--) {
      const r = run - j * 9 * k;
      if (r < 0) continue;
      const p = along(geo.arc, geo.cum, r).p;
      trail.push(<circle key={j} cx={p[0]} cy={p[1]} r={(6.5 - j * 0.4) * k} fill={j === 0 ? "#fff" : accent}
        opacity={(1 - j / 14) * 0.9} />);
    }
  }

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="50% 48%" />
      <svg width={width} height={height} style={FULL}>
        <g opacity={mapIn} transform={`translate(${C[0]} ${C[1]}) scale(${hold.toFixed(4)}) translate(${-C[0]} ${-C[1]})`}>
          <path d={geo.landD} fill={LAND} stroke={EDGE} strokeWidth={1 * k} strokeLinejoin="round" />
          {geo.statesD ? <path d={geo.statesD} fill="none" stroke="#28313d" strokeWidth={0.8 * k} /> : null}
          <path d={geo.groundD} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth={2 * k} strokeLinecap="round"
            strokeDasharray={`${0.1} ${9 * k}`} opacity={ramp(frame, drawAt, 14) * vis} />
          <g opacity={vis}>
            <path d={partialD(geo.arc, geo.cum, run)} fill="none" stroke={alpha(accent, 0.22)} strokeWidth={16 * k}
              strokeLinecap="round" strokeLinejoin="round" />
            <path d={partialD(geo.arc, geo.cum, run)} fill="none" stroke={accent} strokeWidth={4.5 * k}
              strokeLinecap="round" strokeLinejoin="round" />
            {trail}
            {d > 0 && d < 1 ? (
              <circle cx={head[0]} cy={head[1]} r={16 * k} fill="none" stroke="#fff" strokeOpacity={0.5} strokeWidth={2 * k} />
            ) : null}
          </g>
        </g>
        {aP > 0 ? (
          <g>
            <circle cx={A[0]} cy={A[1]} r={18 * k * aP} fill="none" stroke={accent} strokeWidth={2.5 * k} />
            <circle cx={A[0]} cy={A[1]} r={8 * k * aP} fill="#fff" />
          </g>
        ) : null}
        {bP > 0 ? (
          <g>
            {[0, 1, 2].map((j) => {
              const qq = ramp(frame, arrive + j * 5, 24);
              return qq > 0 && qq < 1 ? <circle key={j} cx={B[0]} cy={B[1]} r={(12 + 90 * qq) * k} fill="none" stroke={accent}
                strokeWidth={3 * k} opacity={(1 - qq) * vis} /> : null;
            })}
            {frame > arrive + 16 ? (() => {
              const qq = ((frame - arrive - 16) % period) / period;
              return <circle cx={B[0]} cy={B[1]} r={(14 + 40 * qq) * k} fill="none" stroke={accent} strokeWidth={2 * k}
                opacity={(1 - qq) * 0.7 * vis} />;
            })() : null}
            <circle cx={B[0]} cy={B[1]} r={20 * k * bP} fill={alpha(accent, 0.25)} stroke={accent} strokeWidth={2.5 * k} />
            <circle cx={B[0]} cy={B[1]} r={8 * k * bP} fill="#fff" />
          </g>
        ) : null}
      </svg>
      <Vignette />
      <EndLabel x={A[0]} y={A[1]} side={sideA} kicker="From" name={nameA} accent={accent} at={8} />
      <EndLabel x={B[0]} y={B[1]} side={sideB} kicker="To" name={nameB} accent={accent} at={arrive - 8} />
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", gap: 2 * k, ...numBox }}>
        {caption ? (
          <Rise at={drawAt + 4}>
            <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.24em",
              color: "rgba(255,255,255,.75)", whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.8)" }}>
              {clip(cap(caption), 24)}</span>
          </Rise>
        ) : null}
        <Rise at={drawAt}>
          <Odometer value={shown} at={drawAt} frames={D} size={78 * k} color="#fff" prefix={has ? overlay.prefix || "" : ""}
            suffix={unit} suffixColor={accent} suffixScale={0.5} />
        </Rise>
      </div>
      {overlay.text || overlay.subtitle ? (
        <div style={{ position: "absolute", left: 100 * k, top: 92 * k, width: 900 * k }}>
          <TextBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} at={2} size={56} chars={26} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 4. impact radius
/**
 * A zone punched out around the place at its real radius (value + suffix,
 * miles by default): the disc snaps open with an expo ease, the land inside
 * it tints, a range dial of ticks writes itself around the edge and turns,
 * sonar rings keep running out to the boundary, the radius is measured.
 */
const ImpactRadius: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const id = useSvgId("mvir");
  const place = placesOf(overlay, 1)[0];
  const raw = Number(overlay.value ?? NaN);
  const has = Number.isFinite(raw) && raw > 0;
  const suffix = (overlay.suffix || "").trim();
  const km = /^(km|kms|kilomet)/i.test(suffix);
  const miles = has ? (km ? raw / 1.609344 : raw) : 40;
  const lat = place ? place.lat : NaN;
  const lon = place ? place.lon : NaN;
  const geo = React.useMemo(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    const rDeg = Math.max(0.02, Math.min(18, miles / 69.05));
    const H = Math.max(rDeg * 2.3, 0.9);
    const Hl = Math.min(170, (H * 1.78) / Math.max(0.15, Math.cos(lat * RAD)));
    const proj = geoMercator().rotate([-lon, 0]).fitExtent([[0, 0], [width, height]],
      { type: "MultiPoint", coordinates: [[lon - Hl, clampLat(lat - H)], [lon + Hl, clampLat(lat + H)]] } as never);
    const T: Pt = [width * 0.6, height * 0.53];
    const pl = clampLat(lat); // Mercator has no pole: project at most 84 degrees
    const c0 = proj([lon, pl]) || T;
    const tr = proj.translate();
    proj.translate([tr[0] + T[0] - c0[0], tr[1] + T[1] - c0[1]]);
    const path = geoPath(proj);
    const c = (proj([lon, pl]) || T) as Pt;
    const e = proj([lon, clampLat(pl + rDeg)]) || [c[0], c[1] - 100 * k];
    const rp = Math.max(36 * k, Math.min(height * 0.36, Math.abs(c[1] - e[1])));
    return {
      landD: path(WORLD_FC as never) || "",
      statesD: inUS({ label: "", lat, lon }) ? path(STATES_FC as never) || "" : "",
      c, rp,
    };
  }, [lat, lon, miles, width, height, k]);
  if (!place || !geo) return null;

  const vis = 1 - exit;
  const { c, rp } = geo;
  const openAt = Math.round(fps * 0.35);
  const g = ramp(frame, openAt, Math.round(fps * 0.75), expo) * (1 - 0.25 * exit);
  const R = rp * g;
  const tickP = ramp(frame, openAt + 8, 22);
  const rot = frame * 0.12;
  const period = Math.round(fps * 1.5);
  const sonarAt = openAt + Math.round(fps * 0.6);
  const th = -35 * RAD;
  const lineP = ramp(frame, openAt + Math.round(fps * 0.55), 14) * vis;
  const E: Pt = [c[0] + Math.cos(th) * rp, c[1] + Math.sin(th) * rp];
  const numAt = openAt + Math.round(fps * 0.6);
  const mapIn = ramp(frame, 0, 16);
  const unit = cap(suffix || "mi");

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="60% 53%" />
      <svg width={width} height={height} style={FULL}>
        <defs>
          <clipPath id={`${id}c`}><circle cx={c[0]} cy={c[1]} r={Math.max(0.1, R)} /></clipPath>
          <radialGradient id={`${id}g`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={accent} stopOpacity={0.04} />
            <stop offset="70%" stopColor={accent} stopOpacity={0.12} />
            <stop offset="100%" stopColor={accent} stopOpacity={0.32} />
          </radialGradient>
        </defs>
        <g opacity={mapIn}>
          <path d={geo.landD} fill={LAND} stroke={EDGE} strokeWidth={1.1 * k} strokeLinejoin="round" />
          {geo.statesD ? <path d={geo.statesD} fill="none" stroke="#2a3441" strokeWidth={1 * k} /> : null}
          <g clipPath={`url(#${id}c)`} opacity={vis}>
            <path d={geo.landD} fill={mix(LAND, accent, 0.3)} stroke={alpha(accent, 0.5)} strokeWidth={1.1 * k} />
            {geo.statesD ? <path d={geo.statesD} fill="none" stroke={alpha(accent, 0.45)} strokeWidth={1 * k} /> : null}
          </g>
        </g>
        <g opacity={vis}>
          {R > 0.5 ? (
            <>
              <circle cx={c[0]} cy={c[1]} r={R} fill={`url(#${id}g)`} />
              <circle cx={c[0]} cy={c[1]} r={R} fill="none" stroke={alpha(accent, 0.25)} strokeWidth={12 * k} />
              <circle cx={c[0]} cy={c[1]} r={R} fill="none" stroke={accent} strokeWidth={3 * k} />
            </>
          ) : null}
          {frame >= sonarAt ? [0, 1, 2].map((j) => {
            const f0 = frame - sonarAt - j * (period / 3);
            if (f0 < 0) return null;
            const qq = (f0 % period) / period;
            return <circle key={j} cx={c[0]} cy={c[1]} r={rp * qq} fill="none" stroke={accent} strokeWidth={2 * k}
              opacity={(1 - qq) * 0.5} />;
          }) : null}
          {Array.from({ length: 72 }, (_, i) => {
            if (i / 72 > tickP) return null;
            const a = (i * 5 + rot) * RAD;
            const major = i % 6 === 0;
            const r0 = rp + 12 * k, r1 = rp + (major ? 30 : 20) * k;
            return <line key={i} x1={c[0] + Math.cos(a) * r0} y1={c[1] + Math.sin(a) * r0} x2={c[0] + Math.cos(a) * r1}
              y2={c[1] + Math.sin(a) * r1} stroke={major ? "rgba(255,255,255,.85)" : alpha(accent, 0.6)}
              strokeWidth={(major ? 2.2 : 1.4) * k} />;
          })}
          <g opacity={ramp(frame, openAt + 4, 12)}>
            <line x1={c[0] - rp * 0.4} y1={c[1]} x2={c[0] + rp * 0.4} y2={c[1]} stroke="rgba(255,255,255,.4)"
              strokeWidth={1.2 * k} strokeDasharray={`${6 * k} ${6 * k}`} />
            <line x1={c[0]} y1={c[1] - rp * 0.4} x2={c[0]} y2={c[1] + rp * 0.4} stroke="rgba(255,255,255,.4)"
              strokeWidth={1.2 * k} strokeDasharray={`${6 * k} ${6 * k}`} />
          </g>
          {lineP > 0 ? (
            <g>
              <line x1={c[0]} y1={c[1]} x2={c[0] + (E[0] - c[0]) * lineP} y2={c[1] + (E[1] - c[1]) * lineP} stroke="#fff"
                strokeWidth={2.4 * k} />
              {lineP > 0.97 ? (
                <line x1={E[0] - Math.sin(th) * 12 * k} y1={E[1] + Math.cos(th) * 12 * k} x2={E[0] + Math.sin(th) * 12 * k}
                  y2={E[1] - Math.cos(th) * 12 * k} stroke="#fff" strokeWidth={2.4 * k} />
              ) : null}
            </g>
          ) : null}
          <circle cx={c[0]} cy={c[1]} r={16 * k * ramp(frame, openAt, 12, backOut)} fill="none" stroke={accent} strokeWidth={3 * k} />
          <circle cx={c[0]} cy={c[1]} r={7 * k * ramp(frame, openAt, 12, backOut)} fill="#fff" />
        </g>
      </svg>
      <SideShade side="left" opacity={ramp(frame, openAt - 6, 16) * (1 - 0.6 * exit)} />
      <Vignette />
      {has ? (
        <div style={{ position: "absolute", left: E[0] + 44 * k, top: E[1] - 124 * k, display: "flex", flexDirection: "column",
          alignItems: "flex-start" }}>
          <Rise at={numAt + 2}>
            <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.24em",
              color: "rgba(255,255,255,.75)", textShadow: "0 2px 10px rgba(0,0,0,.8)" }}>RADIUS</span>
          </Rise>
          <Rise at={numAt}>
            <Odometer value={raw} at={numAt} frames={Math.round(fps * 1.0)} size={76 * k} color="#fff"
              suffix={` ${unit}`} suffixColor={accent} suffixScale={0.5} />
          </Rise>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 100 * k, top: 0, bottom: 0, width: 640 * k, display: "flex",
        flexDirection: "column", justifyContent: "center" }}>
        <TextBlock kicker={overlay.subtitle || "Affected area"} title={short(place.label)} body={overlay.text} accent={accent}
          at={openAt} size={74}>
          <Coords lat={place.lat} lon={place.lon} at={openAt + 18} />
        </TextBlock>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. choropleth lift
type Shade = { d: string; c: Pt; v: number; t: number; name: string; idx: number };

/**
 * Several states (or countries) shaded by their values. In narration order
 * each one lights and rises off the map as an extruded block, taller for a
 * bigger value, its value rolling on top, while a needle on the legend
 * travels to that value.
 */
const ChoroplethLift: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const hold = useHold();
  const places = placesOf(overlay, 6);
  const items: OverlayItem[] = (Array.isArray(overlay.items) ? overlay.items : []).filter((i): i is OverlayItem => Boolean(i));
  const key = `${placeKey(places)}#${items.map((i) => `${i.label}:${i.value}`).join("|")}`;
  const geo = React.useMemo(() => {
    if (!places.length) return null;
    const us = places.every((p) => Boolean(stateOf(p)));
    const shapes = us ? ALL_STATES : WORLD;
    const used = new Set<Feat>();
    const raw: { f: Feat; part: Feat; v: number; name: string; idx: number }[] = [];
    places.forEach((p, i) => {
      const f = shapes.find((x) => contains(x, p));
      if (!f || used.has(f)) return;
      const nm = f.properties?.name || short(p.label);
      const it = items.find((x) => {
        const n = norm(x.label);
        return Boolean(n) && (n === norm(short(p.label)) || n === norm(nm));
      }) || items[i];
      const v = Number(it?.value);
      if (!Number.isFinite(v)) return;
      used.add(f);
      raw.push({ f, part: pickPart(f, p), v, name: nm, idx: raw.length });
    });
    if (!raw.length) return null;
    const lower = us && raw.every((r) => LOWER48.includes(r.f));
    // Frame the lit shapes with some context, never tighter than a region.
    const [padLon, padLat, minLon, minLat] = us ? [3, 2, 12, 7] : [7, 4.5, 20, 12];
    const cl = meanLon(places);
    const cLat = places.reduce((a, p) => a + p.lat, 0) / places.length;
    const pads: Pt[] = [[cl - minLon, clampLat(cLat - minLat)], [cl + minLon, clampLat(cLat + minLat)]];
    places.forEach((p) => pads.push([p.lon - padLon, clampLat(p.lat - padLat)], [p.lon + padLon, clampLat(p.lat + padLat)]));
    // Below the title band, above the legend.
    const ext: [Pt, Pt] = [[190 * k, 290 * k], [width - 190 * k, height - 240 * k]];
    const proj = geoMercator().rotate([-cl, 0]).fitExtent(ext, {
      type: "FeatureCollection",
      features: [...raw.map((r) => r.part), { type: "Feature", properties: {}, geometry: { type: "MultiPoint", coordinates: pads } }],
    } as never);
    const path = geoPath(proj);
    const vals = raw.map((r) => r.v);
    const vmin = Math.min(...vals), vmax = Math.max(...vals);
    const shades: Shade[] = raw.map((r) => ({
      d: path(r.f as never) || "", c: path.centroid(r.part as never) as Pt, v: r.v,
      t: vmax > vmin ? (r.v - vmin) / (vmax - vmin) : 1, name: r.name, idx: r.idx,
    }));
    return {
      ctxD: path(WORLD_FC as never) || "",
      baseD: us ? path((lower ? LOWER48_FC : STATES_FC) as never) || "" : "",
      us, shades, vmin, vmax,
    };
  }, [key, width, height, k]);
  if (!geo) return null;

  const n = geo.shades.length;
  const at0 = Math.round(fps * 0.55);
  const step = Math.max(5, Math.min(Math.round(fps * 0.45), Math.floor((durationInFrames - at0 - fps * 1.0 - 14) / Math.max(1, n))));
  const suffix = overlay.suffix || (items[0] as OverlayItem & { suffix?: string } | undefined)?.suffix || "";
  const prefix = overlay.prefix || (items[0] as OverlayItem & { prefix?: string } | undefined)?.prefix || "";
  const mapIn = ramp(frame, 0, 18);
  const vis = 1 - exit;
  const C: Pt = [width / 2, height / 2];
  const scr = (p: Pt): Pt => [C[0] + (p[0] - C[0]) * hold, C[1] + (p[1] - C[1]) * hold];
  const lift = (i: number) => ramp(frame, at0 + i * step, 18, backOut) * (1 - exit);
  const height0 = (sh: Shade) => (6 + 26 * sh.t) * k;
  const drawOrder = [...geo.shades].sort((a, b) => a.c[1] - b.c[1]);
  let needle = 0;
  geo.shades.forEach((sh, i) => {
    needle += (sh.t - (i ? geo.shades[i - 1].t : 0)) * ramp(frame, at0 + i * step, 16);
  });
  const LW = 640 * k;
  const barP = ramp(frame, Math.round(fps * 0.3), 18, inOut) * vis;
  const fmtV = (v: number) => `${prefix}${Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(1)}${suffix}`;

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="50% 45%" />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn }}>
        <g transform={`translate(${C[0]} ${C[1] + (1 - mapIn) * 16 * k}) scale(${hold.toFixed(4)}) translate(${-C[0]} ${-C[1]})`}>
          <path d={geo.ctxD} fill={geo.us ? "#11161d" : LAND} stroke={geo.us ? "#212833" : EDGE} strokeWidth={1 * k}
            strokeLinejoin="round" />
          {geo.baseD ? <path d={geo.baseD} fill={LAND} stroke={EDGE} strokeWidth={1.1 * k} strokeLinejoin="round" /> : null}
          {drawOrder.map((sh) => {
            const L = lift(sh.idx);
            const on = ramp(frame, at0 + sh.idx * step, 10);
            if (on <= 0) return null;
            const h = height0(sh) * L;
            const col = mix(LOWC, accent, 0.18 + 0.82 * sh.t);
            const side = mix(col, "#000000", 0.5);
            const layers = Math.max(2, Math.min(10, Math.ceil(h / (3 * k))));
            return (
              <g key={sh.idx} opacity={on * (1 - 0.5 * exit)}>
                <path d={sh.d} fill="#000" fillOpacity={0.4 * Math.min(1, L)} transform={`translate(${5 * k} ${7 * k})`} />
                {Array.from({ length: layers }, (_, j) => (
                  <path key={j} d={sh.d} fill={side} transform={`translate(0 ${(-h * j) / layers})`} />
                ))}
                <path d={sh.d} fill={col} stroke="#fff" strokeOpacity={0.85} strokeWidth={1.4 * k} strokeLinejoin="round"
                  transform={`translate(0 ${-h})`} />
              </g>
            );
          })}
        </g>
      </svg>
      <Vignette />
      {geo.shades.map((sh) => {
        const at = at0 + sh.idx * step;
        const p = scr([sh.c[0], sh.c[1] - height0(sh) * lift(sh.idx)]);
        if (!Number.isFinite(p[0])) return null;
        return (
          <div key={sh.idx} style={{ position: "absolute", left: p[0] - 160 * k, width: 320 * k, top: p[1] - 44 * k,
            display: "flex", flexDirection: "column", alignItems: "center", textShadow: "0 3px 12px rgba(0,0,0,.85)" }}>
            <Rise at={at + 5}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.12em", color: "#fff",
                whiteSpace: "nowrap" }}>{clip(cap(sh.name), 18)}</span>
            </Rise>
            <Rise at={at + 3}>
              <Odometer value={sh.v} at={at + 3} frames={Math.round(fps * 0.8)} size={44 * k} color="#fff" prefix={prefix}
                suffix={suffix} suffixScale={0.55} />
            </Rise>
          </div>
        );
      })}
      {overlay.text || overlay.subtitle ? (
        <div style={{ position: "absolute", left: 100 * k, top: 92 * k, width: 1000 * k }}>
          <TextBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} at={2} size={58} chars={28} />
        </div>
      ) : null}
      {geo.vmax > geo.vmin ? (
      <div style={{ position: "absolute", left: (width - LW) / 2, top: height - 200 * k, width: LW }}>
        {overlay.label ? (
          <Letters text={clip(cap(overlay.label), 34)} at={Math.round(fps * 0.3)} step={0.5} style={{ fontFamily: MONO,
            fontWeight: 700, fontSize: 24 * k, lineHeight: 1.3, letterSpacing: "0.2em", color: "rgba(255,255,255,.7)",
            marginBottom: 10 * k, whiteSpace: "nowrap", textAlign: "center" }} />
        ) : null}
        <div style={{ position: "relative", height: 14 * k, borderRadius: 7 * k,
          background: `linear-gradient(90deg, ${mix(LOWC, accent, 0.18)}, ${accent})`,
          clipPath: `inset(0 ${(1 - barP) * 100}% 0 0 round ${7 * k}px)`, boxShadow: `0 0 ${18 * k}px ${alpha(accent, 0.35)}` }} />
        {/* The needle's tip rests on the bar (label row: 24 px x 1.3 + mask pad + 10 px gap). */}
        <div style={{ position: "absolute", left: needle * LW - 9 * k, top: (overlay.label ? 44 - 13 : -13) * k,
          width: 18 * k, height: 34 * k, opacity: ramp(frame, at0, 8) * vis }}>
          <div style={{ width: 0, height: 0, borderLeft: `${9 * k}px solid transparent`, borderRight: `${9 * k}px solid transparent`,
            borderTop: `${11 * k}px solid #fff` }} />
          <div style={{ width: 2 * k, height: 20 * k, background: "#fff", marginLeft: 8 * k }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12 * k }}>
          <Rise at={Math.round(fps * 0.4)}>
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, color: "rgba(255,255,255,.7)" }}>{fmtV(geo.vmin)}</span>
          </Rise>
          <Rise at={Math.round(fps * 0.45)}>
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, color: accent }}>{fmtV(geo.vmax)}</span>
          </Rise>
        </div>
      </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 6. pinboard list
/**
 * Up to six places. Numbered badge pins fall onto the map one after another
 * with a bounce and a ground ripple; at the same beat the matching row of the
 * list on the left rises out of its mask and takes the accent highlight.
 */
const PinboardList: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const hold = useHold();
  const places = placesOf(overlay, 6);
  const key = placeKey(places);
  const geo = React.useMemo(() => {
    if (!places.length) return null;
    const us = places.every((p) => inUS(p) && p.lon > -130 && p.lat < 50);
    const padLon = us ? 4 : 10, padLat = us ? 2.5 : 6;
    const pts: Pt[] = [];
    places.forEach((p) => pts.push([p.lon - padLon, clampLat(p.lat - padLat)], [p.lon + padLon, clampLat(p.lat + padLat)]));
    const proj = geoMercator().rotate([-meanLon(places), 0]).fitExtent([[900 * k, 250 * k], [width - 150 * k, height - 140 * k]],
      { type: "MultiPoint", coordinates: pts } as never);
    const path = geoPath(proj);
    const P = places.map((p) => (proj([p.lon, clampLat(p.lat)]) || [width * 0.7, height * 0.5]) as Pt);
    const stems = P.map((p, i) => {
      let near = 0;
      for (let j = 0; j < i; j++) if (Math.hypot(P[j][0] - p[0], P[j][1] - p[1]) < 62 * k) near++;
      return (36 + near * 46) * k;
    });
    return { landD: path(WORLD_FC as never) || "", statesD: us ? path(STATES_FC as never) || "" : "", P, stems };
  }, [key, width, height, k]);
  if (!geo || !places.length) return null;

  const n = places.length;
  const at0 = Math.round(fps * 0.45);
  const step = Math.max(6, Math.min(Math.round(fps * 0.5), Math.floor((durationInFrames - at0 - fps * 1.1 - 14) / n)));
  const items: OverlayItem[] = (Array.isArray(overlay.items) ? overlay.items : []).filter((i): i is OverlayItem => Boolean(i));
  // Each row's note: the item named like the place, else the item in the same position.
  const itemFor = (p: MapLocation, i: number): OverlayItem | undefined =>
    items.find((it) => Boolean(norm(it.label)) && norm(it.label) === norm(short(p.label))) || items[i];
  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, 16);
  const C: Pt = [width * 0.68, height * 0.52];
  const big = n <= 4;

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="68% 50%" />
      <svg width={width} height={height} style={{ ...FULL, opacity: mapIn }}>
        <g transform={`translate(${C[0]} ${C[1]}) scale(${hold.toFixed(4)}) translate(${-C[0]} ${-C[1]})`}>
          <path d={geo.landD} fill={LAND} stroke={EDGE} strokeWidth={1 * k} strokeLinejoin="round" />
          {geo.statesD ? <path d={geo.statesD} fill="none" stroke="#2a3441" strokeWidth={0.9 * k} /> : null}
          {geo.P.map(([x, y], i) => {
            const at = at0 + i * step;
            if (frame < at) return null;
            const drop = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 170, mass: 0.7 } });
            const stem = geo.stems[i];
            const hitQ = ramp(frame, at + 7, 20);
            const active = i === n - 1 ? 1 : 1 - ramp(frame, at + step, 8);
            const pulse = 1 + 0.12 * active * Math.max(0, Math.sin((frame - at) * 0.12)) * (frame - at < fps * 1.2 ? 1 : 0);
            const off = -(1 - drop) * 200 * k - exit * 30 * k;
            return (
              <g key={i} opacity={vis * ramp(frame, at, 4)}>
                <ellipse cx={x} cy={y} rx={12 * k * drop} ry={4 * k * drop} fill="rgba(0,0,0,.55)" />
                {hitQ > 0 && hitQ < 1 ? (
                  <ellipse cx={x} cy={y} rx={(8 + 46 * hitQ) * k} ry={(8 + 46 * hitQ) * 0.45 * k} fill="none" stroke={accent}
                    strokeWidth={2.5 * k} opacity={1 - hitQ} />
                ) : null}
                <g transform={`translate(0 ${off.toFixed(1)})`}>
                  <line x1={x} y1={y} x2={x} y2={y - stem} stroke="#fff" strokeWidth={2.5 * k} />
                  <circle cx={x} cy={y} r={3.5 * k} fill="#fff" />
                  <g transform={`translate(${x.toFixed(1)} ${(y - stem).toFixed(1)}) scale(${pulse.toFixed(3)})`}>
                    {active > 0.5 ? <circle r={34 * k} fill={alpha(accent, 0.22)} /> : null}
                    <circle r={24 * k} fill={active > 0.5 ? accent : mix(accent, "#1a212b", 0.35)} stroke="#fff" strokeWidth={3 * k} />
                    <text x={0} y={2 * k} textAnchor="middle" dominantBaseline="central" fontFamily={DISPLAY} fontSize={30 * k}
                      fill="#0c0f14">{i + 1}</text>
                  </g>
                </g>
              </g>
            );
          })}
        </g>
      </svg>
      <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(4,6,10,.95) 0%, rgba(4,6,10,.82) 30%, rgba(4,6,10,0) 50%)" }} />
      <Vignette strength={0.6} />
      <div style={{ position: "absolute", left: 100 * k, top: 0, bottom: 0, width: 700 * k, display: "flex",
        flexDirection: "column", justifyContent: "center" }}>
        {overlay.text || overlay.subtitle ? (
          <TextBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} at={0} size={58} chars={22} />
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: (big ? 14 : 8) * k,
          marginTop: (overlay.text || overlay.subtitle ? 34 : 0) * k }}>
          {places.map((p, i) => {
            const at = at0 + i * step;
            const act = (i === n - 1 ? ramp(frame, at, 8) : ramp(frame, at, 8) * (1 - ramp(frame, at + step, 8))) * vis;
            const it = itemFor(p, i);
            const name = short(p.label) || `Place ${i + 1}`;
            const sub = (it ? String(it.text || (norm(it.label) !== norm(name) ? it.label || "" : "")) : "").trim();
            return (
              <div key={i} style={{ position: "relative", display: "flex", alignItems: "center", gap: 22 * k,
                padding: `${(big ? 8 : 5) * k}px ${16 * k}px` }}>
                <div style={{ position: "absolute", inset: 0, opacity: act,
                  background: `linear-gradient(90deg, ${alpha(accent, 0.2)}, ${alpha(accent, 0)} 85%)`,
                  borderLeft: `${4 * k}px solid ${accent}` }} />
                <Rise at={at}>
                  <span style={{ fontFamily: DISPLAY, fontSize: (big ? 52 : 44) * k, lineHeight: 1, display: "inline-block",
                    color: act > 0.5 ? accent : "rgba(255,255,255,.45)", minWidth: 56 * k }}>{String(i + 1).padStart(2, "0")}</span>
                </Rise>
                <div style={{ position: "relative", display: "flex", flexDirection: "column" }}>
                  <Letters text={clip(cap(name), 24)} at={at + 2} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800,
                    fontSize: (big ? 40 : 34) * k, letterSpacing: "0.05em", color: "#fff", lineHeight: 1.05, whiteSpace: "nowrap" }} />
                  {sub ? (
                    <Rise at={at + 6}>
                      <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: (big ? 27 : 24) * k, letterSpacing: "0.04em",
                        color: "rgba(255,255,255,.66)", whiteSpace: "nowrap" }}>{clip(sub, 40)}</span>
                    </Rise>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 7. coordinate HUD
/**
 * A cyan targeting screen: a scan line sweeps the grid, a full-frame
 * crosshair slides onto the place while the lat/lon readouts tick toward its
 * coordinates and the map zooms in; the reticle closes, turns square and
 * locks in the accent with a flash, then the name comes up beside it.
 */
const CoordHud: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const id = useSvgId("mvhud");
  const place = placesOf(overlay, 1)[0];
  const lat = place ? place.lat : NaN;
  const lon = place ? place.lon : NaN;
  const geo = React.useMemo(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    const T: Pt = [width * 0.5, height * 0.5];
    const proj = geoMercator().rotate([-lon, 0]).fitExtent([[0, 0], [width, height]],
      { type: "MultiPoint", coordinates: [[lon - 34, clampLat(lat - 17)], [lon + 34, clampLat(lat + 17)]] } as never);
    const c0 = proj([lon, clampLat(lat)]) || T;
    const tr = proj.translate();
    proj.translate([tr[0] + T[0] - c0[0], tr[1] + T[1] - c0[1]]);
    const path = geoPath(proj);
    return {
      T,
      landD: path(WORLD_FC as never) || "",
      statesD: inUS({ label: "", lat, lon }) ? path(STATES_FC as never) || "" : "",
      gratD: path(geoGraticule10() as never) || "",
    };
  }, [lat, lon, width, height]);
  if (!place || !geo) return null;

  const { T } = geo;
  const vis = 1 - exit;
  const seed = Math.round(Math.abs(lat * 97 + lon * 13));
  const lockAt = Math.round(Math.max(fps * 0.9, Math.min(fps * 1.6, durationInFrames * 0.36)));
  const mv = ramp(frame, 6, lockAt - 6, inOut);
  const S: Pt = [
    width * (rnd(seed + 4) > 0.5 ? 0.16 + 0.14 * rnd(seed) : 0.7 + 0.14 * rnd(seed)),
    height * (rnd(seed + 5) > 0.5 ? 0.2 + 0.14 * rnd(seed + 1) : 0.66 + 0.14 * rnd(seed + 1)),
  ];
  const X = S[0] + (T[0] - S[0]) * mv, Y = S[1] + (T[1] - S[1]) * mv;
  const dLat = (S[1] < T[1] ? 1 : -1) * (5 + 7 * rnd(seed + 2));
  const dLon = (S[0] < T[0] ? -1 : 1) * (8 + 12 * rnd(seed + 3));
  const curLat = Math.max(-89.9999, Math.min(89.9999, lat + dLat * (1 - mv)));
  const curLon = wrapLon(lon + dLon * (1 - mv));
  const z = 1 + 1.6 * ramp(frame, Math.round(fps * 0.2), lockAt, inOut) + 0.2 * lin(frame, lockAt + 10, durationInFrames);
  const lockE = ramp(frame, lockAt - 10, 16);
  const lockP = ramp(frame, lockAt, 12, backOut);
  const locked = frame >= lockAt;
  const hs = (110 - 56 * lockE) * k;
  const rot = (1 - lockE) * 45;
  const ret = locked ? accent : CYAN;
  const flash = ramp(frame, lockAt, 18);
  const sweep = ramp(frame, 0, Math.round(fps * 1.2), inOut);
  const gap = 46 * k;
  const lineOp = (0.6 - 0.35 * lockE) * vis;
  const G = 96 * k;
  const cols = Math.ceil(width / G), rows = Math.ceil(height / G);
  const L = 26 * k;
  const brackets = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy], i) => {
    const bx = X + sx * hs * (locked ? 1 + 0.08 * (1 - lockP) : 1), by = Y + sy * hs;
    return <path key={i} d={`M${bx - sx * L} ${by} L${bx} ${by} L${bx} ${by - sy * L}`} fill="none" stroke={ret}
      strokeWidth={3 * k} strokeLinecap="square" />;
  });
  const status = locked ? "LOCKED" : `ACQUIRING${".".repeat(1 + (Math.floor(frame / 6) % 3))}`;
  const chrome = 56 * k;
  const corner = (x: number, y: number, sx: number, sy: number, i: number) => (
    <path key={`c${i}`} d={`M${x + sx * chrome} ${y} L${x} ${y} L${x} ${y + sy * chrome}`} fill="none"
      stroke={alpha(CYAN, 0.55)} strokeWidth={2 * k} />
  );
  const labelRight = T[0] + 96 * k + 700 * k < width - 60 * k;

  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, #0a1826 0%, #050d15 55%, #020508 100%)",
      overflow: "hidden" }}>
      <svg width={width} height={height} style={FULL}>
        <g transform={`translate(${T[0]} ${T[1]}) scale(${z.toFixed(4)}) translate(${-T[0]} ${-T[1]})`}
          opacity={ramp(frame, 0, 14)}>
          <path d={geo.gratD} fill="none" stroke={alpha(CYAN, 0.1)} strokeWidth={(1 * k) / z} />
          <path d={geo.landD} fill="#0a141e" stroke={alpha(CYAN, 0.45)} strokeWidth={(1.3 * k) / z} strokeLinejoin="round" />
          {geo.statesD ? <path d={geo.statesD} fill="none" stroke={alpha(CYAN, 0.2)} strokeWidth={(1 * k) / z} /> : null}
        </g>
        {Array.from({ length: cols + 1 }, (_, i) => (
          <line key={`v${i}`} x1={i * G} y1={0} x2={i * G} y2={height} stroke={alpha(CYAN, i % 4 === 0 ? 0.1 : 0.05)}
            strokeWidth={1 * k} />
        ))}
        {Array.from({ length: rows + 1 }, (_, i) => (
          <line key={`h${i}`} x1={0} y1={i * G} x2={width} y2={i * G} stroke={alpha(CYAN, i % 4 === 0 ? 0.1 : 0.05)}
            strokeWidth={1 * k} />
        ))}
        {corner(60 * k, 60 * k, 1, 1, 0)}
        {corner(width - 60 * k, 60 * k, -1, 1, 1)}
        {corner(60 * k, height - 60 * k, 1, -1, 2)}
        {corner(width - 60 * k, height - 60 * k, -1, -1, 3)}
        {sweep < 1 ? (
          <g>
            <rect x={0} y={sweep * height - 140 * k} width={width} height={140 * k} fill={`url(#${id})`} />
            <line x1={0} y1={sweep * height} x2={width} y2={sweep * height} stroke={alpha(CYAN, 0.85)} strokeWidth={2 * k} />
          </g>
        ) : null}
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CYAN} stopOpacity={0} />
            <stop offset="100%" stopColor={CYAN} stopOpacity={0.16} />
          </linearGradient>
        </defs>
        <g opacity={lineOp}>
          <line x1={0} y1={Y} x2={Math.max(0, X - gap)} y2={Y} stroke={CYAN} strokeWidth={1.4 * k} />
          <line x1={X + gap} y1={Y} x2={width} y2={Y} stroke={CYAN} strokeWidth={1.4 * k} opacity={1 - 0.85 * lockE} />
          <line x1={X} y1={0} x2={X} y2={Math.max(0, Y - gap)} stroke={CYAN} strokeWidth={1.4 * k} />
          <line x1={X} y1={Y + gap} x2={X} y2={height} stroke={CYAN} strokeWidth={1.4 * k} />
        </g>
        <g opacity={vis * ramp(frame, 4, 10)} transform={`rotate(${rot.toFixed(2)} ${X.toFixed(1)} ${Y.toFixed(1)})`}>
          {brackets}
        </g>
        {locked ? (
          <g opacity={vis}>
            <circle cx={X} cy={Y} r={(52 + 150 * flash) * k} fill="none" stroke={accent} strokeWidth={3 * k} opacity={1 - flash} />
            <circle cx={X} cy={Y} r={6 * k * lockP} fill={accent} />
          </g>
        ) : (
          <circle cx={X} cy={Y} r={3 * k} fill={CYAN} opacity={vis} />
        )}
      </svg>
      <Vignette strength={0.7} />
      {/* Readouts ride the crosshair lines, kept inside the 90 px safe area. */}
      <div style={{ position: "absolute", left: 96 * k, top: Math.max(96 * k, Math.min(height - 150 * k, Y - 40 * k)) }}>
        <Rise at={4}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.14em", color: "#dff4ff",
            whiteSpace: "nowrap" }}><span style={{ color: CYAN }}>LAT </span>{fmtLat(curLat)}</span>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: Math.max(96 * k, Math.min(X + 14 * k, width - 420 * k)), top: 96 * k }}>
        <Rise at={6}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.14em", color: "#dff4ff",
            whiteSpace: "nowrap" }}><span style={{ color: CYAN }}>LON </span>{fmtLon(curLon)}</span>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: 96 * k, bottom: 96 * k }}>
        <Rise at={8}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.22em",
            color: locked ? accent : CYAN, whiteSpace: "nowrap" }}>● {status}</span>
        </Rise>
      </div>
      <div style={{ position: "absolute", right: 96 * k, bottom: 96 * k }}>
        <Rise at={10}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.22em", color: CYAN,
            whiteSpace: "nowrap" }}>ZOOM {z.toFixed(2)}×</span>
        </Rise>
      </div>
      <div style={{ position: "absolute", top: T[1] - 150 * k, left: labelRight ? T[0] + 96 * k : undefined,
        right: labelRight ? undefined : width - T[0] + 96 * k, width: 700 * k }}>
        <TextBlock kicker={overlay.subtitle || "Location confirmed"} title={short(place.label)} body={overlay.text} accent={accent}
          at={lockAt + 2} size={64} kickerColor={CYAN} align={labelRight ? "left" : "right"}>
          <Coords lat={place.lat} lon={place.lon} at={lockAt + 16} align={labelRight ? "left" : "right"} />
        </TextBlock>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. river draw
/**
 * A route or river through every place in order, on the dark dotted-ridge
 * desk with the land as frosted glass. The line meanders as it draws, a glow
 * beneath it, bright dashes streaming downstream along it; waypoints pop as
 * the head passes, the start and end are named, the figure rolls at the end.
 */
const RiverDraw: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const places = placesOf(overlay, 8);
  const key = placeKey(places);
  const geo = React.useMemo(() => {
    if (places.length < 2) return null;
    const pads: Pt[] = [];
    places.forEach((p) => pads.push([p.lon - 2.5, clampLat(p.lat - 1.6)], [p.lon + 2.5, clampLat(p.lat + 1.6)]));
    // Below the title band; the end label (and its figure) keeps the bottom band.
    const proj = geoMercator().rotate([-meanLon(places), 0]).fitExtent([[300 * k, 330 * k], [width - 300 * k, height - 220 * k]],
      { type: "MultiPoint", coordinates: pads } as never);
    const path = geoPath(proj);
    const P = places.map((p) => (proj([p.lon, clampLat(p.lat)]) || [width / 2, height / 2]) as Pt);
    const SEG = 20;
    const raw: Pt[] = [];
    for (let i = 0; i < P.length - 1; i++) {
      const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
      for (let s = 0; s < SEG; s++) raw.push(catmull(p0, p1, p2, p3, s / SEG));
    }
    raw.push(P[P.length - 1]);
    const c0 = cumOf(raw);
    const tot = c0[c0.length - 1] || 1;
    const pts = raw.map((p, j) => {
      const a = raw[Math.max(0, j - 1)], b = raw[Math.min(raw.length - 1, j + 1)];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const len = Math.hypot(dx, dy) || 1;
      const w = Math.sin((c0[j] / (116 * k)) * Math.PI * 2 + 0.7) * 5 * k * Math.sin(Math.PI * (c0[j] / tot));
      return [p[0] - (dy / len) * w, p[1] + (dx / len) * w] as Pt;
    });
    const cum = cumOf(pts);
    const W = P.map((_, i) => pts[Math.min(pts.length - 1, i * SEG)]);
    const wp = P.map((_, i) => cum[Math.min(pts.length - 1, i * SEG)]);
    return {
      landD: path(WORLD_FC as never) || "",
      statesD: places.every(inUS) ? path(STATES_FC as never) || "" : "",
      pts, cum, W, wp,
    };
  }, [key, width, height, k]);
  if (!geo || places.length < 2) return null;

  const vis = 1 - exit;
  const drawAt = Math.round(fps * 0.45);
  const D = Math.round(Math.max(fps * 1.0, Math.min(fps * 2.3, durationInFrames * 0.4)));
  const d = ramp(frame, drawAt, D, inOut);
  const total = geo.cum[geo.cum.length - 1] || 1;
  const run = d * total;
  const riverD = partialD(geo.pts, geo.cum, run);
  const head = along(geo.pts, geo.cum, run).p;
  const arrive = drawAt + D;
  const period = Math.round(fps * 1.4);
  const n = geo.W.length;
  const first = geo.W[0], last = geo.W[n - 1];
  const nameA = short(places[0].label) || "Start", nameB = short(places[n - 1].label) || "End";
  let sideA: "left" | "right" = geo.W[1][0] - first[0] > 0 ? "left" : "right";
  let sideB: "left" | "right" = last[0] - geo.W[n - 2][0] > 0 ? "right" : "left";
  if (sideA === "left" && first[0] - labelW(nameA, 50, k) < 90 * k) sideA = "right";
  if (sideA === "right" && first[0] + labelW(nameA, 50, k) > width - 90 * k) sideA = "left";
  if (sideB === "left" && last[0] - labelW(nameB, 50, k) < 90 * k) sideB = "right";
  if (sideB === "right" && last[0] + labelW(nameB, 50, k) > width - 90 * k) sideB = "left";
  const value = Number(overlay.value ?? NaN);

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <CaseBackdrop tone="dark" seed={6} />
      <svg width={width} height={height} style={{ ...FULL, opacity: ramp(frame, 0, 16) }}>
        <path d={geo.landD} fill="rgba(8,20,38,.62)" stroke="rgba(134,204,255,.38)" strokeWidth={1.1 * k} strokeLinejoin="round" />
        {geo.statesD ? <path d={geo.statesD} fill="none" stroke="rgba(134,204,255,.18)" strokeWidth={0.9 * k} /> : null}
        <g opacity={vis}>
          <path d={riverD} fill="none" stroke={alpha(accent, 0.2)} strokeWidth={22 * k} strokeLinecap="round" strokeLinejoin="round" />
          <path d={riverD} fill="none" stroke={accent} strokeWidth={6.5 * k} strokeLinecap="round" strokeLinejoin="round" />
          <path d={riverD} fill="none" stroke="rgba(255,255,255,.65)" strokeWidth={2.2 * k} strokeLinecap="round"
            strokeDasharray={`${4 * k} ${24 * k}`} strokeDashoffset={-frame * 1.8 * k} />
          {geo.W.map((w, i) => {
            // The source pops as the draw starts; every other point as the head reaches it.
            const qq = i === 0 ? ramp(frame, drawAt - 6, 12)
              : d > 0 ? Math.max(0, Math.min(1, (run - geo.wp[i]) / (30 * k) + 1)) : 0;
            if (qq <= 0) return null;
            const s = backOut(qq);
            const end = i === 0 || i === n - 1;
            return (
              <g key={i}>
                <circle cx={w[0]} cy={w[1]} r={(end ? 15 : 11) * k * s} fill={alpha(accent, 0.25)} stroke={accent} strokeWidth={2.2 * k} />
                <circle cx={w[0]} cy={w[1]} r={(end ? 7 : 5) * k * s} fill="#fff" />
              </g>
            );
          })}
          {d > 0 && d < 1 ? (
            <g>
              <circle cx={head[0]} cy={head[1]} r={(14 + 10 * Math.abs(Math.sin(frame * 0.25))) * k} fill="none" stroke="#fff"
                strokeOpacity={0.55} strokeWidth={2 * k} />
              <circle cx={head[0]} cy={head[1]} r={7 * k} fill="#fff" />
            </g>
          ) : null}
          {frame > arrive ? [0, 1].map((j) => {
            const f0 = frame - arrive - j * (period / 2);
            if (f0 < 0) return null;
            const qq = (f0 % period) / period;
            return <circle key={j} cx={last[0]} cy={last[1]} r={(15 + 60 * qq) * k} fill="none" stroke={accent}
              strokeWidth={2.4 * k} opacity={1 - qq} />;
          }) : null}
        </g>
      </svg>
      <Vignette strength={0.55} />
      <EndLabel x={first[0]} y={first[1]} side={sideA} kicker="Start" name={nameA} accent={accent} at={drawAt - 4} />
      <EndLabel x={last[0]} y={last[1]} side={sideB} kicker="End" name={nameB} accent={accent} at={arrive - 10}
        extra={Number.isFinite(value) ? 72 : 0}>
        {Number.isFinite(value) ? (
          <Rise at={arrive - 2} style={{ marginTop: 6 * k }}>
            <Odometer value={value} at={arrive - 2} frames={Math.round(fps * 0.8)} size={58 * k} color={accent}
              prefix={overlay.prefix || ""} suffix={overlay.suffix ? ` ${cap(overlay.suffix)}` : ""} suffixScale={0.5} />
          </Rise>
        ) : null}
      </EndLabel>
      {overlay.text || overlay.subtitle ? (
        <div style={{ position: "absolute", left: 100 * k, top: 92 * k, width: 900 * k }}>
          <TextBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} at={2} size={56} chars={26} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 9. country spotlight
/**
 * The world map, then the rest of it dims under a spotlight while the
 * country holding the place lifts off the sheet: it rises toward the camera
 * with a 3D tilt and a growing shadow, leaving its dashed hole behind, and
 * settles large and floating. At the end it drops back into its hole.
 */
const CountrySpotlight: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const id = useSvgId("mvcs");
  const place = placesOf(overlay, 1)[0];
  const lat = place ? place.lat : NaN;
  const lon = place ? place.lon : NaN;
  const geo = React.useMemo(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    const p: MapLocation = { label: "", lat, lon };
    const hit = countryOf(p);
    const proj = geoMercator().rotate([-lon, 0]).fitExtent([[40 * k, 70 * k], [width - 40 * k, height - 40 * k]],
      { type: "MultiPoint", coordinates: [[lon - 179, -52], [lon + 179, 76]] } as never);
    const path = geoPath(proj);
    const part = hit ? pickPart(hit, p) : null;
    return {
      landD: path(WORLD_FC as never) || "",
      partD: part ? path(part as never) || "" : "",
      b: part ? (path.bounds(part as never) as [Pt, Pt]) : null,
      c: part ? (path.centroid(part as never) as Pt) : null,
      pin: (proj([lon, clampLat(lat)]) || [width / 2, height / 2]) as Pt,
      name: hit?.properties?.name || "",
    };
  }, [lat, lon, width, height, k]);
  if (!place || !geo) return null;

  const vis = 1 - exit;
  const liftAt = Math.round(fps * 0.35);
  const Lin = ramp(frame, liftAt, Math.round(fps * 1.0), inOut);
  const L = Lin * (1 - exit);
  const dimP = ramp(frame, liftAt - 4, 18) * vis;
  const T: Pt = [width * 0.66, height * 0.53];
  const ok = Boolean(geo.b && geo.c && geo.partD && Number.isFinite(geo.c[0]) && Number.isFinite(geo.b[0][0]));
  const c: Pt = ok && geo.c ? geo.c : geo.pin;
  const bw = ok && geo.b ? Math.max(1, geo.b[1][0] - geo.b[0][0]) : 1;
  const bh = ok && geo.b ? Math.max(1, geo.b[1][1] - geo.b[0][1]) : 1;
  const S = ok ? Math.max(1.15, Math.min(9, (height * 0.56) / bh, (width * 0.4) / bw)) : 1;
  const sc = 1 + (S - 1) * L;
  const float = Math.sin((frame / fps) * 1.6) * 5 * k * L;
  const P: Pt = [c[0] + (T[0] - c[0]) * L, c[1] + (T[1] - c[1]) * L + float];
  const tx = P[0] - c[0] * sc, ty = P[1] - c[1] * sc;
  const tiltX = Math.sin(Math.PI * L) * 16, tiltY = -Math.sin(Math.PI * L) * 10;
  const pinAt = liftAt + Math.round(fps * 0.95);
  const pinP = ramp(frame, pinAt, 14, backOut) * vis;
  const pinScr: Pt = ok ? [geo.pin[0] * sc + tx, geo.pin[1] * sc + ty] : geo.pin;
  const period = Math.round(fps * 1.5);
  const q = (frame % period) / period;
  const label = short(place.label);
  const title = geo.name || label;
  const kicker = overlay.subtitle || (label && norm(label) !== norm(title) ? label : "Country");

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="50% 50%" />
      <svg width={width} height={height} style={{ ...FULL, opacity: ramp(frame, 0, 16) }}>
        <path d={geo.landD} fill={LAND} stroke={EDGE} strokeWidth={1 * k} strokeLinejoin="round" />
        {ok ? (
          <path d={geo.partD} fill="#05070a" stroke={alpha(accent, 0.6)} strokeWidth={1.4 * k}
            strokeDasharray={`${5 * k} ${5 * k}`} opacity={Math.min(1, L * 3)} />
        ) : null}
        <rect x={0} y={0} width={width} height={height} fill="rgba(2,4,7,.62)" opacity={dimP} />
      </svg>
      <AbsoluteFill style={{ opacity: dimP,
        background: `radial-gradient(circle at ${T[0]}px ${T[1]}px, ${alpha(accent, 0.2)} 0%, ${alpha(accent, 0.06)} 22%, transparent 45%)` }} />
      {ok ? (
        <AbsoluteFill style={{ transform: `perspective(${1600 * k}px) rotateX(${tiltX.toFixed(2)}deg) rotateY(${tiltY.toFixed(2)}deg)`,
          transformOrigin: `${P[0].toFixed(1)}px ${P[1].toFixed(1)}px`,
          filter: `drop-shadow(0 ${(8 + 40 * L) * k}px ${(10 + 26 * L) * k}px rgba(0,0,0,.7)) drop-shadow(0 0 ${18 * k}px ${alpha(accent, 0.45 * L)})` }}>
          <svg width={width} height={height} style={FULL}>
            <defs>
              <linearGradient id={`${id}g`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor={mix(accent, "#ffffff", 0.35)} />
                <stop offset="55%" stopColor={accent} />
                <stop offset="100%" stopColor={mix(accent, "#000000", 0.22)} />
              </linearGradient>
            </defs>
            <g transform={`translate(${tx.toFixed(2)} ${ty.toFixed(2)}) scale(${sc.toFixed(4)})`}>
              <path d={geo.partD} fill={`url(#${id}g)`} fillOpacity={0.35 + 0.65 * Math.min(1, Lin * 2)} stroke="#fff"
                strokeWidth={(2 * k) / sc} strokeLinejoin="round" />
            </g>
          </svg>
        </AbsoluteFill>
      ) : null}
      <svg width={width} height={height} style={FULL}>
        {pinP > 0 ? (
          <g>
            <circle cx={pinScr[0]} cy={pinScr[1]} r={(12 + 56 * q) * k} fill="none" stroke="#fff" strokeWidth={2 * k}
              opacity={(1 - q) * 0.85 * pinP} />
            <circle cx={pinScr[0]} cy={pinScr[1]} r={9 * k * pinP} fill="#fff" stroke="#0c0f14" strokeWidth={3 * k} />
          </g>
        ) : null}
      </svg>
      <Vignette strength={0.7} />
      <div style={{ position: "absolute", left: 100 * k, top: 0, bottom: 0, width: 640 * k, display: "flex",
        flexDirection: "column", justifyContent: "center" }}>
        <TextBlock kicker={kicker} title={title} body={overlay.text} accent={accent} at={liftAt + 6} size={80} chars={14}>
          <Coords lat={place.lat} lon={place.lon} at={liftAt + 22} />
        </TextBlock>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. zoom box inset
/**
 * Two projections. The country (or the lower 48) on the left, its outline
 * drawing on; a focus box draws around the place; then the box itself flies
 * out and grows into a large inset on the right, a true magnification of
 * the box with a fine lat/lon grid, a scale bar and a pin dropping on the
 * place. At the end the inset shrinks back into its box.
 */
const ZoomInset: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const id = useSvgId("mvzi");
  const place = placesOf(overlay, 1)[0];
  const lat = place ? place.lat : NaN;
  const lon = place ? place.lon : NaN;
  const IW = 680 * k, IH = 520 * k;
  const IX = width - 100 * k - IW, IY = 250 * k;
  const BW = 104 * k, BH = (BW * IH) / IW;
  const geo = React.useMemo(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    const p: MapLocation = { label: "", lat, lon };
    const st = stateOf(p);
    const lower = Boolean(st && LOWER48.includes(st));
    const hit = countryOf(p);
    const outline = hit ? pickPart(hit, p) : null;
    const focus = lower ? (LOWER48_FC as unknown) : outline ? (outline as unknown)
      : { type: "MultiPoint", coordinates: [[lon - 15, clampLat(lat - 9)], [lon + 15, clampLat(lat + 9)]] };
    // Left half, below the title band.
    const main = geoMercator().rotate([-lon, 0]).fitExtent([[110 * k, 300 * k], [960 * k, 960 * k]], focus as never);
    const mpath = geoPath(main);
    const pl = clampLat(lat); // Mercator has no pole: project at most 84 degrees
    const m = (main([lon, pl]) || [535 * k, 600 * k]) as Pt;
    const Z = IW / BW;
    const inset = geoMercator().rotate(main.rotate()).scale(main.scale() * Z).translate([0, 0]);
    const q0 = inset([lon, pl]) || [0, 0];
    inset.translate([IW / 2 - q0[0], IH / 2 - q0[1]]).clipExtent([[-20, -20], [IW + 20, IH + 20]]);
    const ipath = geoPath(inset);
    // A fine lat/lon grid over the inset, labelled on its edges.
    const grid: { x?: number; y?: number; lab: string }[] = [];
    const tl = inset.invert ? inset.invert([0, 0]) : null;
    const br = inset.invert ? inset.invert([IW, IH]) : null;
    if (tl && br) {
      let lon0 = tl[0], lon1 = br[0];
      if (lon1 < lon0) lon1 += 360;
      const span = Math.max(1e-6, lon1 - lon0);
      const stepD = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20].find((s) => span / s <= 6) || 20;
      const dec = stepD >= 1 ? (Number.isInteger(stepD) ? 0 : 1) : stepD >= 0.5 || stepD === 0.1 || stepD === 0.2 ? 1 : 2;
      for (let L = Math.ceil(lon0 / stepD) * stepD; L <= lon1 && grid.length < 14; L += stepD) {
        const x = inset([L, pl]);
        if (x && x[0] > 24 && x[0] < IW - 24) grid.push({ x: x[0], lab: fmtLon(wrapLon(L), dec) });
      }
      for (let La = Math.ceil(br[1] / stepD) * stepD; La <= tl[1] && grid.length < 28; La += stepD) {
        const y = inset([lon, La]);
        if (y && y[1] > 24 && y[1] < IH - 24) grid.push({ y: y[1], lab: fmtLat(La, dec) });
      }
    }
    // A scale bar of a round number of miles, about 150px long.
    const e1 = inset([lon + 1, pl]), e0 = inset([lon, pl]);
    const pxPerDeg = e1 && e0 ? Math.abs(e1[0] - e0[0]) : 0;
    const milesPerPx = pxPerDeg > 0 ? (69.17 * Math.cos(pl * RAD)) / pxPerDeg : 0;
    let barMiles = 0, barPx = 0;
    if (milesPerPx > 0 && Number.isFinite(milesPerPx)) {
      const target = 150 * k * milesPerPx;
      const pw = Math.pow(10, Math.floor(Math.log10(target)));
      barMiles = ([1, 2, 5, 10].map((mm) => mm * pw).filter((v) => v <= target).pop() || pw);
      barPx = barMiles / milesPerPx;
    }
    return {
      worldM: mpath(WORLD_FC as never) || "",
      statesM: st ? mpath((lower ? LOWER48_FC : STATES_FC) as never) || "" : "",
      outlineM: outline ? mpath(outline as never) || "" : "",
      worldI: ipath(WORLD_FC as never) || "",
      statesI: st ? ipath(STATES_FC as never) || "" : "",
      m, Z, grid, barMiles, barPx,
      region: st ? st.properties?.name || "" : hit?.properties?.name || "",
    };
  }, [lat, lon, width, height, k, IW, IH, BW]);
  if (!place || !geo) return null;

  const vis = 1 - exit;
  const mapIn = ramp(frame, 0, 16);
  const outlineP = ramp(frame, 4, Math.round(fps * 0.8), inOut);
  const boxAt = Math.round(fps * 0.5);
  const boxP = ramp(frame, boxAt, 14, inOut);
  const growAt = boxAt + 12;
  const growF = Math.round(fps * 0.7);
  const g = ramp(frame, growAt, growF, expo) * (1 - ramp(frame, durationInFrames - 14, 12, inOut));
  const bx = geo.m[0] - BW / 2, by = geo.m[1] - BH / 2;
  const rx = bx + (IX - bx) * g, ry = by + (IY - by) * g;
  const rs = (BW + (IW - BW) * g) / IW;
  const rw = IW * rs, rh = IH * rs;
  const pinAt = growAt + growF - 4;
  const drop = frame < pinAt ? 0 : spring({ frame: frame - pinAt, fps, config: { damping: 12, stiffness: 170, mass: 0.7 } });
  const period = Math.round(fps * 1.5);
  const q = (frame % period) / period;
  const fadeEdge = 1130 * k;
  const title = overlay.text || geo.region || short(place.label);

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkSea focus="35% 55%" />
      <svg width={width} height={height} style={FULL}>
        <defs>
          <linearGradient id={`${id}mg`} x1={0} y1={0} x2={width} y2={0} gradientUnits="userSpaceOnUse">
            <stop offset={((fadeEdge - 140 * k) / width).toFixed(3)} stopColor="#fff" />
            <stop offset={(fadeEdge / width).toFixed(3)} stopColor="#000" />
          </linearGradient>
          <mask id={`${id}m`}><rect x={0} y={0} width={width} height={height} fill={`url(#${id}mg)`} /></mask>
          <clipPath id={`${id}c`}><rect x={0} y={0} width={IW} height={IH} /></clipPath>
        </defs>
        <g mask={`url(#${id}m)`} opacity={mapIn}>
          <path d={geo.worldM} fill="#141a22" stroke="#232b36" strokeWidth={1 * k} strokeLinejoin="round" />
          {geo.outlineM ? <path d={geo.outlineM} fill="#1f2833" /> : null}
          {geo.statesM ? <path d={geo.statesM} fill="none" stroke="#35404e" strokeWidth={1 * k} /> : null}
          {geo.outlineM ? (
            <path d={geo.outlineM} fill="none" stroke="rgba(255,255,255,.85)" strokeWidth={2 * k} strokeLinejoin="round"
              pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - outlineP} opacity={vis} />
          ) : null}
        </g>
        <rect x={bx} y={by} width={BW} height={BH} fill={alpha(accent, 0.1 * boxP)} stroke={accent} strokeWidth={2.5 * k}
          pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - boxP} opacity={vis} />
        {g > 0.01 ? (
          <g>
            <line x1={bx + BW} y1={by} x2={rx} y2={ry} stroke="rgba(255,255,255,.55)" strokeWidth={1.5 * k}
              strokeDasharray={`${6 * k} ${5 * k}`} />
            <line x1={bx + BW} y1={by + BH} x2={rx} y2={ry + rh} stroke="rgba(255,255,255,.55)" strokeWidth={1.5 * k}
              strokeDasharray={`${6 * k} ${5 * k}`} />
            <g transform={`translate(${rx.toFixed(2)} ${ry.toFixed(2)}) scale(${rs.toFixed(4)})`} opacity={Math.min(1, g * 6)}>
              <g clipPath={`url(#${id}c)`}>
                <rect x={0} y={0} width={IW} height={IH} fill="#0b1118" />
                <path d={geo.worldI} fill="#1c2531" stroke="#3a4757" strokeWidth={1.4 * k} strokeLinejoin="round" />
                {geo.statesI ? <path d={geo.statesI} fill="none" stroke="#4a5869" strokeWidth={1.4 * k} /> : null}
                {geo.grid.map((gl, i) => gl.x !== undefined ? (
                  <g key={i}>
                    <line x1={gl.x} y1={0} x2={gl.x} y2={IH} stroke="rgba(83,200,255,.14)" strokeWidth={1 * k} />
                    <text x={gl.x + 6 * k} y={26 * k} fontFamily={MONO} fontWeight={500} fontSize={20 * k}
                      fill="rgba(200,230,255,.62)">{gl.lab}</text>
                  </g>
                ) : (
                  <g key={i}>
                    <line x1={0} y1={gl.y} x2={IW} y2={gl.y} stroke="rgba(83,200,255,.14)" strokeWidth={1 * k} />
                    <text x={10 * k} y={(gl.y || 0) - 7 * k} fontFamily={MONO} fontWeight={500} fontSize={20 * k}
                      fill="rgba(200,230,255,.62)">{gl.lab}</text>
                  </g>
                ))}
                {geo.barPx > 0 ? (
                  <g>
                    <line x1={IW - 30 * k - geo.barPx} y1={IH - 30 * k} x2={IW - 30 * k} y2={IH - 30 * k} stroke="#fff" strokeWidth={2.5 * k} />
                    <line x1={IW - 30 * k - geo.barPx} y1={IH - 38 * k} x2={IW - 30 * k - geo.barPx} y2={IH - 22 * k} stroke="#fff"
                      strokeWidth={2.5 * k} />
                    <line x1={IW - 30 * k} y1={IH - 38 * k} x2={IW - 30 * k} y2={IH - 22 * k} stroke="#fff" strokeWidth={2.5 * k} />
                    <text x={IW - 30 * k} y={IH - 48 * k} textAnchor="end" fontFamily={MONO} fontWeight={700} fontSize={22 * k}
                      fill="#fff">{geo.barMiles.toLocaleString("en-US")} MI</text>
                  </g>
                ) : null}
                {frame >= pinAt ? (
                  <g opacity={vis * ramp(frame, pinAt, 4)}>
                    <circle cx={IW / 2} cy={IH / 2} r={(12 + 70 * q) * k} fill="none" stroke={accent} strokeWidth={2.5 * k}
                      opacity={(1 - q) * 0.8} />
                    <ellipse cx={IW / 2} cy={IH / 2} rx={13 * k * drop} ry={4.5 * k * drop} fill="rgba(0,0,0,.55)" />
                    <g transform={`translate(${IW / 2} ${(IH / 2 - (1 - drop) * 160 * k).toFixed(1)}) scale(${(1.05 * k).toFixed(4)})`}>
                      <path d={PIN_D} fill={accent} stroke="#fff" strokeWidth={2.4} strokeLinejoin="round" />
                      <circle cx={0} cy={-46} r={7.5} fill="#0b0e13" />
                    </g>
                  </g>
                ) : null}
              </g>
            </g>
            <rect x={rx} y={ry} width={rw} height={rh} fill="none" stroke="#fff" strokeWidth={2.5 * k} />
          </g>
        ) : null}
      </svg>
      <Vignette strength={0.6} />
      <div style={{ position: "absolute", left: IX, top: IY - 38 * k, width: IW, display: "flex", justifyContent: "space-between" }}>
        <Rise at={growAt + growF - 6}>
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.2em", color: accent,
            whiteSpace: "nowrap" }}>DETAIL · {geo.Z.toFixed(1)}×</span>
        </Rise>
        <Rise at={growAt + growF - 2}>
          <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.08em", color: "rgba(255,255,255,.7)",
            whiteSpace: "nowrap" }}>{fmtLat(place.lat, 2)} · {fmtLon(place.lon, 2)}</span>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: IX, top: IY + IH + 22 * k, width: IW }}>
        <Letters text={clip(cap(short(place.label)), 22)} at={pinAt} step={0.7} style={{ fontFamily: DISPLAY,
          fontSize: 58 * k, lineHeight: 1, color: "#fff", letterSpacing: "0.02em", whiteSpace: "nowrap",
          textShadow: "0 4px 20px rgba(0,0,0,.8)" }} />
      </div>
      <div style={{ position: "absolute", left: 100 * k, top: 92 * k, width: 900 * k }}>
        <TextBlock kicker={overlay.subtitle} title={title} accent={accent} at={2} size={56} chars={26} />
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "mv-globe-spin": GlobeSpin,
  "mv-state-glow": StateGlow,
  "mv-arc-flight": ArcFlight,
  "mv-impact-radius": ImpactRadius,
  "mv-choropleth-lift": ChoroplethLift,
  "mv-pinboard-list": PinboardList,
  "mv-coordinate-hud": CoordHud,
  "mv-river-draw": RiverDraw,
  "mv-country-spotlight": CountrySpotlight,
  "mv-zoom-inset": ZoomInset,
};
