import React, { useMemo } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { geoMercator, geoPath } from "d3-geo";
import type { GeoProjection } from "d3-geo";
import { feature } from "topojson-client";
import topology from "world-atlas/countries-110m.json";
import statesTopology from "../../data/us-states.json";
import { DISPLAY, INTER, LABEL, MONO, NARROW } from "../fonts";
import type { MapLocation, Overlay, OverlayItem } from "../../types";
import { Odometer, Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";

/**
 * Alerts, weather and news (family "al-"): broadcast alert graphics kept
 * compact and tasteful - no full-width red bands, red only where it means
 * danger, cyan for radar/UI data, the accent for structure.
 *
 *   al-breaking-flag    (tag)  a red broadcast tab in the corner; BREAKING and then the
 *                              headline fold out of it on 3D hinges, and fold back at the end
 *   al-alert-toast      (tag)  a frosted notification springs in top-right: the app icon
 *                              rings, title and message rise, a timer bar drains to the exit
 *   al-siren-badge      (tag)  a siren emblem low-left, its strobe double-flashing while a red
 *                              beam sweeps round across the footage, the label letter by letter
 *   al-warning-polygon  (card) a radar map: a scan line reveals the echoes, the warning
 *                              polygon draws itself and hatches in, the warning type beside it
 *   al-severity-meter   (card) a 1-5 staircase builds, a charge climbs it and lights the
 *                              level, the level number rolls, its name rises
 *   al-countdown-timer  (card) a mono countdown in glass cells ticking in real time, every
 *                              changed digit rolling, a red pulse on each second
 *   al-live-tag         (tag)  a LIVE chip with a beating dot, the place, the local time
 *                              ticking by the second
 *   al-emergency-stamp  (card) a proclamation on the desk; the DECLARED stamp slams down,
 *                              the camera shakes, ink specks and dust burst out
 *   al-slim-ticker      (tag)  a slim dark-glass ticker low on the frame crawling the
 *                              sentence (and further items) behind an accent chip
 *   al-storm-track      (card) a vector coastline; the cone and the dashed track draw across
 *                              it behind a spinning storm symbol, the category rolls
 *
 * Every look reads only the overlay's own data, is a pure function of the
 * frame (seeded noise, never Math.random or the clock) and leaves in its
 * last ~12 frames.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];

// ------------------------------------------------------------------ constants
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expo = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
const GOLD = "#d6a83c";
const STAMP_RED = "#d8262e";

// ------------------------------------------------------------------ small helpers
const str = (v: unknown): string =>
  typeof v === "string" ? v.replace(/\s+/g, " ").trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const cap = (v: unknown): string => str(v).toUpperCase();
const num = (v: unknown): number => {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim()) return Number(v.replace(/[,\s]/g, ""));
  return NaN;
};
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, Math.max(1, n - 1)).trimEnd()}…` : s);
/** Word-wrapped lines, at most `max`; a cut-off last line ends in an ellipsis rather than silently dropping words. */
const fitLines = (text: string, chars: number, max: number): string[] => {
  const all = lines(text, chars);
  if (all.length <= max) return all;
  const out = all.slice(0, max);
  out[max - 1] = `${out[max - 1].replace(/[\s,.;:–—-]+$/, "")}…`;
  return out;
};
const short = (s: string): string => s.split(",")[0].trim();
/** Deterministic 0..1 noise from a number (no Math.random in a render). */
const rnd = (i: number): number => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
const hash = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) % 9973;
};
const lin = (x: number, a: number, b: number): number => interpolate(x, [a, Math.max(a + 1e-6, b)], [0, 1], clamp);
const beat = (p: number): number => 0.5 + 0.5 * Math.cos(p * Math.PI * 2);
const itemsOf = (ov: Overlay): OverlayItem[] =>
  Array.isArray(ov.items) ? ov.items.filter((i) => Boolean(i) && typeof i === "object") : [];

const hexRgb = (c: string): [number, number, number] | null => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((c || "").trim());
  if (!m) return null;
  let s = m[1];
  if (s.length === 3) s = s.split("").map((ch) => ch + ch).join("");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
const safeAccent = (c: string): string => (hexRgb(c) ? c.trim() : GOLD);
const rgba = (c: string, a: number): string => {
  const v = hexRgb(c) || [214, 168, 60];
  return `rgba(${v[0]},${v[1]},${v[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
};
/** Ink that reads on a colour: near-black on light accents (gold), white on dark ones. */
const inkOn = (c: string): string => {
  const v = hexRgb(c) || [214, 168, 60];
  return (0.299 * v[0] + 0.587 * v[1] + 0.114 * v[2]) / 255 > 0.58 ? INK : "#ffffff";
};

const useClock = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const dur = Math.max(2, durationInFrames);
  return { frame, fps, dur, width, height, outAt: Math.max(1, dur - 13) };
};

/**
 * Letters rising out of a mask one after another, and leaving the same way
 * (upward, in turn) so that the last one is gone by the final frame.
 */
const Letters: React.FC<{ text: string; at: number; step?: number; outAt?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 0.8, outAt, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const chars = Array.from(text);
    const end = Math.min(outAt ?? durationInFrames - 13, durationInFrames - 9);
    const outStep = Math.min(0.6, Math.max(0, durationInFrames - 9 - end) / Math.max(1, chars.length));
    return (
      <div style={{ overflow: "hidden", whiteSpace: "nowrap", paddingBottom: "0.1em", marginBottom: "-0.1em", ...style }}>
        {chars.map((c, i) => {
          const pin = ramp(frame, at + i * step, 12);
          const pout = ramp(frame, end + i * outStep, 8, easeIn);
          return (
            <span key={i} style={{ display: "inline-block", whiteSpace: "pre",
              transform: `translateY(${(1 - pin) * 108 - pout * 108}%)`, opacity: pin < 0.01 || pout > 0.99 ? 0 : 1 }}>
              {c}
            </span>
          );
        })}
      </div>
    );
  };

/** A line (or any block) rising out of its mask, leaving upward through it at the end. */
const Rise: React.FC<{ at: number; outAt?: number; frames?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, outAt, frames = 16, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = Math.min(outAt ?? durationInFrames - 13, durationInFrames - 10);
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, end, 9, easeIn);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        <div style={{ transform: `translateY(${(1 - pin) * 112 - pout * 112}%)` }}>{children}</div>
      </div>
    );
  };

/** A soft local gradient behind a tag, so it reads on bright footage without darkening the picture. */
const Shade: React.FC<{ bg: string; outAt: number }> = ({ bg, outAt }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ background: bg, opacity: ramp(frame, 0, 12) * (1 - ramp(frame, outAt + 2, 10)) }} />;
};

/** An own-backdrop card over footage fades in and out quickly; as a full-screen scene it simply is the frame. */
const backdropAlpha = (ov: Overlay, frame: number, dur: number): number =>
  ov.fullFrame ? 1 : ramp(frame, 0, 8) * (1 - ramp(frame, dur - 7, 6, easeIn));

type RollCh = { cur: string; old: string; p: number };
/**
 * A string whose changed characters roll: for each position, how far the new
 * character has slid in since it last changed (looking back `back` frames).
 */
const rollChars = (fmt: (f: number) => string, frame: number, back: number): RollCh[] => {
  const now = fmt(frame);
  const hist: string[] = [];
  for (let b = 1; b <= back; b++) hist.push(fmt(frame - b));
  return Array.from(now).map((ch, i) => {
    for (let b = 0; b < back; b++) {
      const prev = hist[b];
      if (prev.length !== now.length) break;
      if (prev[i] !== ch) return { cur: ch, old: prev[i], p: expo((b + 1) / (back + 1)) };
    }
    return { cur: ch, old: ch, p: 1 };
  });
};

// ------------------------------------------------------------------ geography
type Geometry = { type: string; coordinates: unknown };
type Feat = { type: string; id?: string | number; properties?: { name?: string }; geometry: Geometry | null };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };

const WORLD: Feat[] = (feature(topology as never, topology.objects.countries as never) as unknown as FeatColl).features
  .filter((f) => f.properties?.name !== "Antarctica");
const STATES: Feat[] = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features;
const US_NAME = "United States of America";
const US_BOXES = [[18, 50, -126, -65], [51, 72, -170, -129], [18, 23, -161, -154]];
const inUS = (p: MapLocation): boolean => US_BOXES.some(([a, b, c, d]) => p.lat >= a && p.lat <= b && p.lon >= c && p.lon <= d);

/** Valid gazetteer places only: finite and inside the Mercator range. */
const placesOf = (ov: Overlay, max: number): MapLocation[] => {
  const out: MapLocation[] = [];
  for (const p of Array.isArray(ov.locations) ? ov.locations : []) {
    if (!p || typeof p !== "object") continue;
    const lat = Number(p.lat), lon = Number(p.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 84 || Math.abs(lon) > 360) continue;
    out.push({ label: str(p.label), lat, lon, kind: typeof p.kind === "string" ? p.kind : undefined });
    if (out.length >= max) break;
  }
  return out;
};

/** The shapes that fall inside the frame, clipped to it, as SVG path strings. */
const shapesIn = (feats: Feat[], proj: GeoProjection, W: number, H: number): string[] => {
  const path = geoPath(proj);
  const out: string[] = [];
  for (const f of feats) {
    try {
      const b = path.bounds(f as never);
      if (!b.every((q) => Number.isFinite(q[0]) && Number.isFinite(q[1]))) continue;
      if (b[1][0] < -40 || b[0][0] > W + 40 || b[1][1] < -40 || b[0][1] > H + 40) continue;
      const d = path(f as never);
      if (d) out.push(d);
    } catch {
      // a shape the projection cannot draw is left out
    }
  }
  return out;
};

const latLabel = (v: number): string => `${Math.abs(Math.round(v))}°${v < 0 ? "S" : "N"}`;
const lonLabel = (v: number): string => {
  const n = ((((v + 180) % 360) + 360) % 360) - 180;
  return `${Math.abs(Math.round(n))}°${n < 0 ? "W" : "E"}`;
};

// ================================================================== 1. breaking flag
/**
 * A red broadcast tab pops in the top-left corner; the white BREAKING panel
 * swings out of it on a hinge, then the dark headline panel swings out of
 * that one (each shaded while it is turned away). At the end they fold back
 * in reverse and the tab closes.
 */
const BreakingFlag: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const head = str(overlay.text);
  if (!head) return null;
  const word = clip(cap(overlay.label) || "BREAKING", 14);
  const sub = clip(cap(overlay.subtitle), 46);
  const upper = head.toUpperCase();
  const long = upper.length > 40;
  const hl = fitLines(upper, long ? 36 : 60, 2);
  const H = 70 * k;
  const hs = (long ? 34 : 40) * k;
  const tab = ramp(frame, 0, 12, backOut) * (1 - ramp(frame, outAt + 7, 6, easeIn));
  const angA = -104 * Math.max(1 - ramp(frame, 5, 16), ramp(frame, outAt + 4, 8, easeIn));
  const angB = -104 * Math.max(1 - ramp(frame, 13, 18), ramp(frame, outAt + 1, 8, easeIn));
  const shade = (a: number) => Math.min(1, Math.abs(a) / 90) * 0.72;
  const period = Math.max(1, Math.round(fps * 1.1));
  const ph = (frame % period) / period;
  const sheen = ramp(frame, 30, 22, inOut);
  const rule = ramp(frame, 24, 20) * (1 - ramp(frame, outAt, 8));
  const drift = Math.sin(frame / (fps * 1.7)) * 2 * k;
  return (
    <AbsoluteFill>
      <Shade outAt={outAt}
        bg="radial-gradient(ellipse 48% 40% at 0% 0%, rgba(0,0,0,.5) 0%, rgba(0,0,0,.18) 55%, rgba(0,0,0,0) 100%)" />
      <div style={{ position: "absolute", left: 90 * k, top: 84 * k + drift, display: "flex", alignItems: "flex-start",
        perspective: 1400 * k }}>
        <div style={{ width: H, height: H, flexShrink: 0, background: RED, display: "flex", alignItems: "center",
          justifyContent: "center", borderRadius: `${8 * k}px 0 0 ${8 * k}px`, transform: `scale(${Math.max(0, tab)})`,
          boxShadow: `0 ${10 * k}px ${28 * k}px rgba(0,0,0,.35)` }}>
          <svg width={40 * k} height={40 * k} viewBox="0 0 40 40">
            <circle cx="20" cy="20" r="4.4" fill="#fff" />
            <path d="M13.5 12.5 A10 10 0 0 0 13.5 27.5 M26.5 12.5 A10 10 0 0 1 26.5 27.5" fill="none" stroke="#fff"
              strokeWidth="3" strokeLinecap="round" opacity={0.3 + 0.7 * beat(ph)} />
            <path d="M8.5 6.5 A18 18 0 0 0 8.5 33.5 M31.5 6.5 A18 18 0 0 1 31.5 33.5" fill="none" stroke="#fff"
              strokeWidth="3" strokeLinecap="round" opacity={0.3 + 0.7 * beat(ph - 0.2)} />
          </svg>
        </div>
        <div style={{ position: "relative", height: H, transformOrigin: "0% 50%", transformStyle: "preserve-3d",
          transform: `rotateY(${angA}deg)`, opacity: angA < -95 ? 0 : 1 }}>
          <div style={{ position: "relative", height: H, overflow: "hidden", display: "flex", alignItems: "center",
            padding: `0 ${26 * k}px`, background: "linear-gradient(180deg, #ffffff 0%, #e8e8e5 100%)" }}>
            <Letters text={word} at={10} step={1.1} outAt={outAt + 2} style={{ fontFamily: DISPLAY, fontSize: 50 * k,
              lineHeight: 1, letterSpacing: "0.06em", color: INK, paddingTop: 5 * k }} />
            <div style={{ position: "absolute", top: 0, bottom: 0, left: `${-45 + sheen * 190}%`, width: "35%",
              background: "linear-gradient(100deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.9) 50%, rgba(255,255,255,0) 100%)",
              opacity: sheen > 0 && sheen < 1 ? 1 : 0 }} />
            <div style={{ position: "absolute", inset: 0, background: "#000", opacity: shade(angA) }} />
          </div>
          <div style={{ position: "absolute", left: "100%", top: 0, width: "max-content", transformOrigin: "0% 50%",
            transform: `rotateY(${angB}deg)`, opacity: angB < -95 ? 0 : 1 }}>
            <div style={{ position: "relative", minHeight: H, boxSizing: "border-box", display: "flex", flexDirection: "column",
              justifyContent: "center", padding: `${10 * k}px ${48 * k}px ${10 * k}px ${24 * k}px`,
              background: "linear-gradient(180deg, rgba(26,26,30,.95) 0%, rgba(10,10,12,.9) 100%)",
              clipPath: `polygon(0 0, 100% 0, calc(100% - ${24 * k}px) 100%, 0 100%)` }}>
              <div style={{ position: "absolute", left: 0, top: 0, height: 3 * k, width: `${rule * 100}%`, background: acc }} />
              {hl.map((ln, i) => (
                <Rise key={i} at={20 + i * 4} outAt={outAt + i}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: hs, lineHeight: 1.06, color: "#fff",
                    letterSpacing: "0.03em", whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              ))}
              {sub ? (
                <Rise at={28} outAt={outAt} style={{ marginTop: 3 * k }}>
                  <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 17 * k, letterSpacing: "0.2em", color: acc,
                    whiteSpace: "nowrap" }}>{sub}</span>
                </Rise>
              ) : null}
              <div style={{ position: "absolute", inset: 0, background: "#000", opacity: shade(angB) }} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. alert toast
type IconKind = "drop" | "flame" | "storm" | "quake" | "bell";
const iconFor = (s: string): IconKind => {
  const t = s.toLowerCase();
  if (/flood|water|rain|dam\b|river|tsunami|drought|reservoir|well\b|aquifer|levee|boil/.test(t)) return "drop";
  if (/fire|heat|burn|smoke|blaze/.test(t)) return "flame";
  if (/storm|hurricane|wind|tornado|cyclone|typhoon|blizzard/.test(t)) return "storm";
  if (/quake|seismic|tremor/.test(t)) return "quake";
  return "bell";
};

const Glyph: React.FC<{ kind: IconKind; size: number; color: string }> = ({ kind, size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: "block", overflow: "visible" }}>
    {kind === "drop" ? (
      <path d="M12 2.6C12 2.6 5.2 10.4 5.2 15a6.8 6.8 0 0 0 13.6 0C18.8 10.4 12 2.6 12 2.6z" fill={color} />
    ) : kind === "flame" ? (
      <path d="M12.6 2.4c.6 3.6 5 5.6 5 10.9a5.6 5.6 0 0 1-11.2 0c0-2.8 1.4-4.5 2.6-5.9.2 1.9 1 3.1 2.2 3.7-.4-3.4.5-6.2 1.4-8.7z"
        fill={color} />
    ) : kind === "storm" ? (
      <g fill={color}>
        <path d="M9.3 8.4C7.8 5.2 4.2 4.2 2.4 5.8C5 5.4 7.4 6.8 8.1 9.6z" />
        <path d="M14.7 15.6C16.2 18.8 19.8 19.8 21.6 18.2C19 18.6 16.6 17.2 15.9 14.4z" />
        <circle cx="12" cy="12" r="3.9" fill="none" stroke={color} strokeWidth="2.4" />
      </g>
    ) : kind === "quake" ? (
      <path d="M2 12.5h4l2-6 3.2 12 2.4-9 1.8 5.5 1.3-2.5H22" fill="none" stroke={color} strokeWidth="2.4"
        strokeLinecap="round" strokeLinejoin="round" />
    ) : (
      <g fill={color}>
        <path d="M12 3.2a1.4 1.4 0 0 1 1.4 1.4v.7a6.2 6.2 0 0 1 4.8 6v3.9l1.8 2.4H4l1.8-2.4v-3.9a6.2 6.2 0 0 1 4.8-6v-.7A1.4 1.4 0 0 1 12 3.2z" />
        <path d="M9.8 19.2h4.4a2.2 2.2 0 0 1-4.4 0z" />
      </g>
    )}
  </svg>
);

/**
 * A push alert: a frosted card springs in from the right edge (a ghost of an
 * earlier alert stacked behind it), the app icon pops and rings, title and
 * message rise line by line, a timer bar drains until it slides away.
 */
const AlertToast: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const title = str(overlay.text);
  if (!title) return null;
  const body = str(overlay.subtitle) || str(overlay.body);
  const app = clip(cap(overlay.label) || "EMERGENCY ALERT", 26);
  const kind = iconFor(`${title} ${body} ${app}`);
  const W = 640 * k;
  const tl = fitLines(title, 26, 2);
  const bl = fitLines(body, 38, 3);
  const travel = W + 160 * k;
  const x = (1 - ramp(frame, 0, 20, backOut)) * travel + ramp(frame, outAt + 3, 10, easeIn) * travel;
  const ghost = ramp(frame, 6, 18) * (1 - ramp(frame, outAt + 1, 9, easeIn));
  const pop = ramp(frame, 8, 14, backOut);
  const t = frame - 18;
  const wiggle = t > 0 ? Math.sin(t * 1.25) * 15 * Math.exp(-t / 9) : 0;
  const timer = 1 - lin(frame, 20, outAt + 2);
  const float = Math.sin(frame / (fps * 1.5)) * 3 * k;
  return (
    <AbsoluteFill>
      <Shade outAt={outAt}
        bg="radial-gradient(ellipse 44% 42% at 100% 0%, rgba(0,0,0,.42) 0%, rgba(0,0,0,.14) 55%, rgba(0,0,0,0) 100%)" />
      <div style={{ position: "absolute", right: 90 * k, top: 80 * k + float, width: W, transform: `translateX(${x}px)` }}>
        <div style={{ position: "absolute", left: 24 * k, right: 24 * k, top: 20 * k, bottom: -16 * k, borderRadius: 24 * k,
          background: "rgba(34,35,40,.62)", border: `${1 * k}px solid rgba(255,255,255,.1)`, opacity: ghost,
          transform: `translateY(${(1 - ghost) * -16 * k}px)` }} />
        <div style={{ position: "relative", overflow: "hidden", borderRadius: 26 * k,
          padding: `${20 * k}px ${26 * k}px ${26 * k}px`,
          background: "linear-gradient(180deg, rgba(46,48,54,.82) 0%, rgba(24,25,29,.8) 100%)",
          backdropFilter: "blur(22px) saturate(1.3)", WebkitBackdropFilter: "blur(22px) saturate(1.3)",
          border: `${1.2 * k}px solid rgba(255,255,255,.16)`,
          boxShadow: `0 ${26 * k}px ${64 * k}px rgba(0,0,0,.45), inset 0 ${1 * k}px 0 rgba(255,255,255,.14)` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
            <div style={{ width: 46 * k, height: 46 * k, flexShrink: 0, borderRadius: 12 * k, display: "flex",
              alignItems: "center", justifyContent: "center",
              background: `linear-gradient(160deg, ${rgba(acc, 1)} 0%, ${rgba(acc, 0.72)} 100%)`,
              boxShadow: `0 ${6 * k}px ${16 * k}px ${rgba(acc, 0.35)}`,
              transform: `scale(${Math.max(0, pop * (1 - ramp(frame, outAt + 2, 8, easeIn)))}) rotate(${wiggle}deg)` }}>
              <Glyph kind={kind} size={28 * k} color={inkOn(acc)} />
            </div>
            <Letters text={app} at={10} step={0.5} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
              letterSpacing: "0.16em", color: "rgba(255,255,255,.72)" }} />
            <div style={{ flex: 1 }} />
            <Rise at={14}>
              <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 20 * k, color: "rgba(255,255,255,.5)" }}>now</span>
            </Rise>
          </div>
          <div style={{ marginTop: 14 * k }}>
            {tl.map((ln, i) => (
              <Rise key={i} at={16 + i * 3}>
                <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 32 * k, lineHeight: 1.2, color: "#fff",
                  whiteSpace: "nowrap" }}>{ln}</span>
              </Rise>
            ))}
          </div>
          {bl.length ? (
            <div style={{ marginTop: 6 * k }}>
              {bl.map((ln, i) => (
                <Rise key={i} at={22 + i * 3}>
                  <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 26 * k, lineHeight: 1.32,
                    color: "rgba(255,255,255,.78)", whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              ))}
            </div>
          ) : null}
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 4 * k, background: "rgba(255,255,255,.08)" }}>
            <div style={{ height: "100%", width: `${timer * 100}%`, background: acc,
              boxShadow: `0 0 ${10 * k}px ${rgba(acc, 0.8)}` }} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. siren badge
/**
 * A siren emblem low-left: the ring draws, the dome glows and double-flashes
 * like a strobe, wail rings spread, and a two-lamp red beam sweeps round
 * across the footage. The kicker, the label (letter by letter) and a line of
 * context sit beside it.
 */
const SirenBadge: Look = ({ overlay, accent }) => {
  const { frame, outAt, height } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const text = cap(overlay.text);
  if (!text) return null;
  const kicker = clip(cap(overlay.label) || "ALERT", 30);
  const sub = clip(str(overlay.subtitle), 60);
  const id = `al-siren-${overlay.startFrame}`;
  const D = 150 * k;
  const cx = 90 * k + D / 2;
  const cy = height - 150 * k - D / 2;
  const pop = ramp(frame, 0, 16, backOut);
  const gone = ramp(frame, outAt + 5, 8, easeIn);
  const ring = ramp(frame, 4, 18, inOut);
  const beamOn = ramp(frame, 10, 16) * (1 - ramp(frame, outAt, 10));
  const spin = frame * 7.5;
  const st = frame % 24;
  const strobe = st < 3 || (st >= 6 && st < 9) ? 1 : 0;
  const glow = Math.max(strobe, 0.35 + 0.25 * Math.sin(frame / 2.4));
  const wail = (off: number) => (frame < 10 + off ? -1 : ((frame - 10 - off) % 30) / 30);
  const size = text.length > 20 ? 58 : 70;
  const tl = fitLines(text, 22, 2);
  const B = 2800 * k;
  const beam = "rgba(255,59,48,0) 0deg, rgba(255,59,48,.3) 14deg, rgba(255,110,90,.12) 30deg, rgba(255,59,48,0) 46deg, " +
    "rgba(255,59,48,0) 180deg, rgba(255,59,48,.3) 194deg, rgba(255,110,90,.12) 210deg, rgba(255,59,48,0) 226deg, " +
    "rgba(255,59,48,0) 360deg";
  const fade = "radial-gradient(circle, rgba(0,0,0,.95) 4%, rgba(0,0,0,.45) 24%, rgba(0,0,0,0) 46%)";
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <Shade outAt={outAt}
        bg="radial-gradient(ellipse 48% 52% at 0% 100%, rgba(0,0,0,.55) 0%, rgba(0,0,0,.2) 55%, rgba(0,0,0,0) 100%)" />
      <div style={{ position: "absolute", left: cx - B / 2, top: cy - B / 2, width: B, height: B, borderRadius: "50%",
        opacity: beamOn, mixBlendMode: "screen", background: `conic-gradient(from ${spin}deg, ${beam})`,
        maskImage: fade, WebkitMaskImage: fade }} />
      <div style={{ position: "absolute", left: cx - D / 2, top: cy - D / 2, width: D, height: D,
        transform: `scale(${Math.max(0, pop * (1 - gone))}) rotate(${(1 - pop) * -50 + gone * 35}deg)` }}>
        <svg width={D} height={D} viewBox="0 0 100 100" style={{ overflow: "visible" }}>
          <defs>
            <radialGradient id={`${id}g`}>
              <stop offset="0%" stopColor="#ff6a5c" stopOpacity={0.95} />
              <stop offset="55%" stopColor={RED} stopOpacity={0.35} />
              <stop offset="100%" stopColor={RED} stopOpacity={0} />
            </radialGradient>
            <linearGradient id={`${id}d`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ff8a7e" />
              <stop offset="100%" stopColor="#d91f16" />
            </linearGradient>
          </defs>
          {[0, 15].map((off) => {
            const w = wail(off);
            return w < 0 ? null : (
              <circle key={off} cx="50" cy="50" r={49 + 34 * w} fill="none" stroke={RED} strokeWidth={2.2 * (1 - w) + 0.6}
                opacity={(1 - w) * 0.85 * beamOn} />
            );
          })}
          <circle cx="50" cy="50" r="48" fill="rgba(12,12,15,.84)" />
          <circle cx="50" cy="54" r="40" fill={`url(#${id}g)`} opacity={glow} />
          <circle cx="50" cy="50" r="48" fill="none" stroke="#fff" strokeWidth="2.6" pathLength={1} strokeDasharray={1}
            strokeDashoffset={1 - ring} transform="rotate(-90 50 50)" />
          {[-160, -125, -90, -55, -20].map((a) => {
            const r = (a * Math.PI) / 180;
            return (
              <line key={a} x1={50 + Math.cos(r) * 22} y1={52 + Math.sin(r) * 22} x2={50 + Math.cos(r) * 30}
                y2={52 + Math.sin(r) * 30} stroke="#fff" strokeWidth="3" strokeLinecap="round" opacity={strobe} />
            );
          })}
          <path d="M35 66 V53 A15 15 0 0 1 65 53 V66 Z" fill={`url(#${id}d)`} />
          <path d="M35 66 V53 A15 15 0 0 1 65 53 V66 Z" fill="#fff" opacity={strobe * 0.35} />
          <path d="M40 53 A10 10 0 0 1 47 43.6" fill="none" stroke="rgba(255,255,255,.75)" strokeWidth="3" strokeLinecap="round" />
          <rect x="29" y="66" width="42" height="9" rx="2.5" fill="#fff" />
        </svg>
      </div>
      <div style={{ position: "absolute", left: cx + D / 2 + 34 * k, top: cy, transform: "translateY(-50%)",
        display: "flex", flexDirection: "column", gap: 4 * k }}>
        <Letters text={kicker} at={10} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k,
          letterSpacing: "0.32em", color: RED, textShadow: "0 2px 10px rgba(0,0,0,.6)" }} />
        {tl.map((ln, i) => (
          <Letters key={i} text={ln} at={14 + i * 5} step={0.9} outAt={outAt + 1 + i} style={{ fontFamily: DISPLAY,
            fontSize: size * k, lineHeight: 1, color: "#fff", letterSpacing: "0.03em", textShadow: "0 6px 26px rgba(0,0,0,.55)" }} />
        ))}
        {sub ? (
          <Rise at={24} style={{ marginTop: 4 * k }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 12 * k, fontFamily: LABEL, fontWeight: 600,
              fontSize: 30 * k, color: "rgba(255,255,255,.86)", whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.7)" }}>
              <span style={{ display: "inline-block", width: 26 * k, height: 3 * k, background: acc, flexShrink: 0 }} />
              {sub}
            </span>
          </Rise>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. warning polygon
const TYPE_WORD = /^(WARNING|WATCH|ADVISORY|EMERGENCY|ALERT|STATEMENT)$/;
const TYPE_IN = /\b(WARNING|WATCH|ADVISORY|EMERGENCY|ALERT|STATEMENT)\b/;

/** Warnings and emergencies in red, watches in the accent, advisories in cyan. */
const toneFor = (t: string, acc: string): string => {
  if (/\bWATCH\b/.test(t)) return acc;
  if (/\b(ADVISORY|STATEMENT|OUTLOOK)\b/.test(t)) return CYAN;
  return RED;
};

type AreaMap = { land: string[]; gridX: { v: number; label: string }[]; gridY: { v: number; label: string }[];
  pxPerMile: number; us: boolean };

/** A county-scale map round the place (state lines in the US, countries elsewhere), the place at 34% / 54%. */
const buildAreaMap = (p: MapLocation, W: number, H: number, k: number): AreaMap => {
  const us = inUS(p);
  const pxPerDeg = (us ? 150 : 58) * k;
  const proj = geoMercator().rotate([-p.lon, 0]).center([0, p.lat]).scale((pxPerDeg * 180) / Math.PI)
    .translate([W * 0.34, H * 0.54]).clipExtent([[-40, -40], [W + 40, H + 40]]);
  const land = us
    ? [...shapesIn(WORLD.filter((f) => f.properties?.name !== US_NAME), proj, W, H), ...shapesIn(STATES, proj, W, H)]
    : shapesIn(WORLD, proj, W, H);
  const step = us ? 1 : 2;
  const span = Math.ceil(W / pxPerDeg) + step;
  const gridX: { v: number; label: string }[] = [];
  const gridY: { v: number; label: string }[] = [];
  for (let g = Math.floor((p.lon - span) / step) * step; g <= p.lon + span; g += step) {
    const q = proj([g, p.lat]);
    if (q && q[0] > 30 * k && q[0] < W - 30 * k) gridX.push({ v: q[0], label: lonLabel(g) });
  }
  for (let g = Math.floor((p.lat - span) / step) * step; g <= p.lat + span; g += step) {
    if (Math.abs(g) > 80) continue;
    const q = proj([p.lon, g]);
    if (q && q[1] > 30 * k && q[1] < H - 30 * k) gridY.push({ v: q[1], label: latLabel(g) });
  }
  return { land, gridX, gridY, pxPerMile: pxPerDeg / 69, us };
};

/** A soft closed blob (a radar echo) through seeded points. */
const blobPath = (cx: number, cy: number, r: number, seed: number): string => {
  const n = 9;
  const pts: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const rr = r * (0.72 + 0.5 * rnd(seed * 13 + i));
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.78]);
  }
  const mid = (a: Pt, b: Pt): Pt => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const s = mid(pts[n - 1], pts[0]);
  let d = `M${s[0].toFixed(1)} ${s[1].toFixed(1)}`;
  for (let i = 0; i < n; i++) {
    const e = mid(pts[i], pts[(i + 1) % n]);
    d += ` Q${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)} ${e[0].toFixed(1)} ${e[1].toFixed(1)}`;
  }
  return `${d} Z`;
};

/**
 * A storm-based warning on a radar map: a scan line sweeps and reveals the
 * echoes drifting with the storm, the straight-edged warning polygon draws
 * itself vertex by vertex, hatches in and pulses, a motion arrow shows where
 * it is heading; the warning type, its end time and the areas stack beside.
 */
const WarningPolygon: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, outAt, width, height } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const place: MapLocation | undefined = placesOf(overlay, 1)[0];
  const pkey = place ? `${place.lat.toFixed(4)},${place.lon.toFixed(4)}` : "";
  const map = useMemo(() => (place ? buildAreaMap(place, width, height, k) : null), [pkey, width, height, k]);
  const title = cap(overlay.text);
  if (!title) return null;
  const tone = toneFor(title, acc);
  const words = title.split(" ").filter(Boolean);
  const lastWord = words[words.length - 1] || "";
  const keyed = words.length > 1 && TYPE_WORD.test(lastWord);
  const typeLines = keyed ? [...fitLines(words.slice(0, -1).join(" "), 16, 2), lastWord] : fitLines(title, 16, 3);
  const until = clip(cap(overlay.subtitle), 34);
  const issuer = clip(cap(overlay.label), 44);
  const areas = itemsOf(overlay).map((it) => ({ label: clip(cap(it.label), 24), note: clip(str(it.text), 22) }))
    .filter((a) => a.label).slice(0, 4);
  const seed = hash(title + pkey);
  const id = `al-wp-${overlay.startFrame}`;
  const px = width * 0.34, py = height * 0.54;
  const theta = -0.3 - rnd(seed) * 0.7;
  const R = 205 * k;
  const verts: Pt[] = Array.from({ length: 6 }, (_, i): Pt => {
    const a = theta + (i / 6) * Math.PI * 2 + (rnd(seed + i + 1) - 0.5) * 0.4;
    const r = R * (1 + 0.5 * Math.cos(a - theta)) * (0.82 + 0.3 * rnd(seed + i + 11));
    return [px + Math.cos(a) * r, py + Math.sin(a) * r * 0.86];
  });
  const polyD = `${verts.map((v, i) => `${i ? "L" : "M"}${v[0].toFixed(1)} ${v[1].toFixed(1)}`).join(" ")} Z`;
  const segs = verts.map((v, i) => Math.hypot(verts[(i + 1) % 6][0] - v[0], verts[(i + 1) % 6][1] - v[1]));
  const perim = segs.reduce((a, b) => a + b, 0) || 1;
  const cum: number[] = [0];
  segs.forEach((s) => cum.push(cum[cum.length - 1] + s));
  const scan = interpolate(frame, [4, 36], [-0.12 * width, 1.08 * width], { ...clamp, easing: inOut });
  const drawAt = 28, drawLen = 26;
  const draw = ramp(frame, drawAt, drawLen, inOut) * (1 - ramp(frame, outAt + 1, 10, easeIn));
  const fillIn = ramp(frame, drawAt + drawLen - 4, 16) * (1 - ramp(frame, outAt, 8));
  const arrow = ramp(frame, drawAt + drawLen + 6, 18, inOut) * (1 - ramp(frame, outAt, 8));
  const pin = ramp(frame, 18, 14, backOut) * (1 - ramp(frame, outAt + 4, 8, easeIn));
  const rings = ramp(frame, 12, 26, inOut) * (1 - ramp(frame, outAt, 8));
  const corners = ramp(frame, 4, 14) * (1 - ramp(frame, outAt + 2, 8));
  const bgA = backdropAlpha(overlay, frame, dur);
  const push = 1 + 0.06 * lin(frame, 0, dur);
  const drift = lin(frame, 0, dur) * 26 * k;
  const pulse = 0.5 + 0.5 * Math.sin(frame / (fps * 0.28));
  const sonar = (frame % 45) / 45;
  const echoes = Array.from({ length: 7 }, (_, i) => {
    const a = theta + (rnd(seed + i * 3) - 0.5) * 2.2;
    const dist = (0.15 + rnd(seed + i * 5) * 0.85) * 240 * k;
    return { x: px + Math.cos(a) * dist - Math.cos(theta) * 60 * k, y: py + Math.sin(a) * dist * 0.8,
      r: (70 + rnd(seed + i * 7) * 120) * k, core: i % 3 === 0, seed: seed + i * 17 };
  });
  const ringMiles = map ? (map.us ? [50, 100] : [150, 300]) : [];
  const grid = map ? map.gridX.map((g) => g.v) : Array.from({ length: 17 }, (_, i) => (i + 0.5) * 120 * k);
  const gridH = map ? map.gridY.map((g) => g.v) : Array.from({ length: 9 }, (_, i) => (i + 0.5) * 120 * k);
  const a0: Pt = [px + Math.cos(theta) * 60 * k, py + Math.sin(theta) * 60 * k];
  const a1: Pt = [px + Math.cos(theta) * 230 * k, py + Math.sin(theta) * 230 * k];
  const h1: Pt = [a1[0] - Math.cos(theta - 0.5) * 24 * k, a1[1] - Math.sin(theta - 0.5) * 24 * k];
  const h2: Pt = [a1[0] - Math.cos(theta + 0.5) * 24 * k, a1[1] - Math.sin(theta + 0.5) * 24 * k];
  const placeName = place ? clip(cap(short(place.label)), 24) : "";
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bgA,
        background: "radial-gradient(ellipse 80% 70% at 34% 54%, #0f1d2e 0%, #0a1420 55%, #050a11 100%)" }} />
      <AbsoluteFill style={{ opacity: bgA, transform: `scale(${push})`, transformOrigin: `${px}px ${py}px` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <radialGradient id={`${id}e`}>
              <stop offset="0%" stopColor={CYAN} stopOpacity={0.5} />
              <stop offset="70%" stopColor={CYAN} stopOpacity={0.15} />
              <stop offset="100%" stopColor={CYAN} stopOpacity={0} />
            </radialGradient>
            <radialGradient id={`${id}c`}>
              <stop offset="0%" stopColor="#e8f7ff" stopOpacity={0.75} />
              <stop offset="60%" stopColor={CYAN} stopOpacity={0.35} />
              <stop offset="100%" stopColor={CYAN} stopOpacity={0} />
            </radialGradient>
            <pattern id={`${id}h`} width={16 * k} height={16 * k} patternUnits="userSpaceOnUse"
              patternTransform={`rotate(45) translate(${(frame * 0.5 * k).toFixed(2)} 0)`}>
              <rect width={6 * k} height={16 * k} fill={tone} fillOpacity={0.34} />
            </pattern>
            <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={CYAN} stopOpacity={0} />
              <stop offset="100%" stopColor={CYAN} stopOpacity={0.16} />
            </linearGradient>
          </defs>
          {grid.map((x, i) => (
            <line key={`gx${i}`} x1={x} x2={x} y1={0} y2={height} stroke="rgba(140,185,235,.09)" strokeWidth={1.2 * k} />
          ))}
          {gridH.map((y, i) => (
            <line key={`gy${i}`} x1={0} x2={width} y1={y} y2={y} stroke="rgba(140,185,235,.09)" strokeWidth={1.2 * k} />
          ))}
          {map ? map.land.map((d, i) => (
            <path key={`l${i}`} d={d} fill="#15212f" stroke="#33465d" strokeWidth={1.4 * k} strokeLinejoin="round" />
          )) : null}
          {map ? map.gridX.map((g, i) => (
            <text key={`tx${i}`} x={g.v + 8 * k} y={62 * k} fontFamily={MONO} fontWeight={500} fontSize={15 * k}
              fill="rgba(170,205,240,.45)">{g.label}</text>
          )) : null}
          {map ? map.gridY.map((g, i) => (
            <text key={`ty${i}`} x={62 * k} y={g.v - 8 * k} fontFamily={MONO} fontWeight={500} fontSize={15 * k}
              fill="rgba(170,205,240,.45)">{g.label}</text>
          )) : null}
          <g transform={`translate(${Math.cos(theta) * drift} ${Math.sin(theta) * drift})`}>
            {echoes.map((e, i) => (
              <g key={i} opacity={lin(scan, e.x - e.r, e.x + e.r) * (1 - ramp(frame, outAt, 10))}>
                <path d={blobPath(e.x, e.y, e.r, e.seed)} fill={`url(#${id}e)`} />
                {e.core ? <path d={blobPath(e.x + e.r * 0.1, e.y, e.r * 0.45, e.seed + 50)} fill={`url(#${id}c)`} /> : null}
              </g>
            ))}
          </g>
          {map ? ringMiles.map((m, i) => {
            const r = m * map.pxPerMile;
            return (
              <g key={`r${i}`} opacity={rings}>
                <circle cx={px} cy={py} r={r} fill="none" stroke="rgba(255,255,255,.22)" strokeWidth={1.6 * k}
                  strokeDasharray={`${6 * k} ${7 * k}`} />
                <text x={px + r * 0.72 + 6 * k} y={py - r * 0.72} fontFamily={MONO} fontWeight={700} fontSize={14 * k}
                  fill="rgba(255,255,255,.5)">{`${m} MI`}</text>
              </g>
            );
          }) : null}
          {frame >= 4 && frame <= 38 ? (
            <g>
              <rect x={scan - 240 * k} y={0} width={240 * k} height={height} fill={`url(#${id}s)`} />
              <line x1={scan} x2={scan} y1={0} y2={height} stroke={CYAN} strokeWidth={2 * k} opacity={0.8} />
            </g>
          ) : null}
          <path d={polyD} fill={rgba(tone, 0.08)} opacity={fillIn} />
          <path d={polyD} fill={`url(#${id}h)`} opacity={fillIn} />
          <path d={polyD} fill="none" stroke={tone} strokeWidth={14 * k} strokeOpacity={0.18} strokeLinejoin="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
          <path d={polyD} fill="none" stroke={tone} strokeWidth={4.5 * k} strokeLinejoin="round" pathLength={1}
            strokeDasharray={1} strokeDashoffset={1 - draw} opacity={0.82 + 0.18 * pulse} />
          {verts.map((v, i) => (
            <rect key={`v${i}`} x={v[0] - 5 * k} y={v[1] - 5 * k} width={10 * k} height={10 * k} fill="#fff"
              opacity={draw > 0.002 && draw >= cum[i] / perim - 0.002 ? 1 : 0} />
          ))}
          <path d={`M${a0[0]} ${a0[1]} L${a1[0]} ${a1[1]}`} stroke="#fff" strokeWidth={4 * k} strokeLinecap="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - arrow} opacity={0.9} />
          <path d={`M${h1[0]} ${h1[1]} L${a1[0]} ${a1[1]} L${h2[0]} ${h2[1]}`} fill="none" stroke="#fff" strokeWidth={4 * k}
            strokeLinecap="round" strokeLinejoin="round" opacity={arrow > 0.95 ? 0.9 : 0} />
          {place ? (
            <g opacity={Math.min(1, Math.max(0, pin))}>
              <circle cx={px} cy={py} r={(9 + 46 * sonar) * k} fill="none" stroke="#fff" strokeWidth={2 * k} opacity={1 - sonar} />
              <circle cx={px} cy={py} r={9 * k * Math.max(0, pin)} fill="#fff" stroke={INK} strokeWidth={2 * k} />
            </g>
          ) : null}
        </svg>
        {placeName ? (
          <div style={{ position: "absolute", left: px - 340 * k, top: py + 16 * k, width: 320 * k, textAlign: "right" }}>
            <Rise at={24}>
              <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.1em", color: "#fff",
                whiteSpace: "nowrap", textShadow: "0 2px 12px rgba(0,0,0,.9)" }}>{placeName}</span>
            </Rise>
          </div>
        ) : null}
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: bgA,
        background: "linear-gradient(90deg, rgba(5,9,15,0) 48%, rgba(5,9,15,.72) 60%, rgba(5,9,15,.9) 100%)" }} />
      <AbsoluteFill style={{ opacity: bgA, boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.6)` }} />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        {[[1, 1], [-1, 1], [1, -1], [-1, -1]].map(([dx, dy], i) => {
          const x = dx > 0 ? 48 * k : width - 48 * k;
          const y = dy > 0 ? 48 * k : height - 48 * k;
          const L = 42 * k;
          return (
            <path key={i} d={`M${x} ${y + dy * L} L${x} ${y} L${x + dx * L} ${y}`} fill="none"
              stroke="rgba(255,255,255,.35)" strokeWidth={2 * k} opacity={corners * bgA} />
          );
        })}
      </svg>
      <div style={{ position: "absolute", left: 1170 * k, width: 660 * k, top: 0, bottom: 0, display: "flex",
        flexDirection: "column", justifyContent: "center", gap: 10 * k }}>
        {issuer ? (
          <Letters text={issuer} at={8} step={0.35} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 18 * k,
            letterSpacing: "0.2em", color: "rgba(210,225,240,.66)" }} />
        ) : null}
        <div style={{ height: 2 * k, width: `${ramp(frame, 10, 20) * (1 - ramp(frame, outAt, 10)) * 100}%`,
          background: rgba(tone, 0.8), margin: `${4 * k}px 0 ${10 * k}px` }} />
        {typeLines.map((ln, i) => {
          const hot = keyed ? i === typeLines.length - 1 : TYPE_IN.test(ln);
          return (
            <Letters key={i} text={ln} at={14 + i * 5} step={0.8} outAt={outAt + i} style={{ fontFamily: DISPLAY,
              fontSize: 84 * k, lineHeight: 0.98, letterSpacing: "0.03em", color: hot ? tone : "#fff" }} />
          );
        })}
        {until ? (
          <Rise at={34} style={{ marginTop: 10 * k }}>
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 36 * k, letterSpacing: "0.08em", color: "#fff",
              whiteSpace: "nowrap" }}>{until}</span>
          </Rise>
        ) : null}
        {areas.length ? (
          <div style={{ marginTop: 16 * k, display: "flex", flexDirection: "column", gap: 6 * k }}>
            {areas.map((a, i) => (
              <Rise key={i} at={44 + i * 5}>
                <div style={{ display: "flex", alignItems: "center", gap: 14 * k, whiteSpace: "nowrap" }}>
                  <span style={{ display: "inline-block", width: 12 * k, height: 12 * k, background: tone, flexShrink: 0 }} />
                  <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, color: "rgba(255,255,255,.92)",
                    letterSpacing: "0.04em" }}>{a.label}</span>
                  {a.note ? (
                    <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, color: "rgba(255,255,255,.55)" }}>
                      {a.note}</span>
                  ) : null}
                </div>
              </Rise>
            ))}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. severity meter
const LEVEL_NAMES = ["LOW", "MODERATE", "HIGH", "SEVERE", "EXTREME"];

/**
 * A level on a 1-5 scale: a staircase of blocks springs up, a charge climbs
 * it (each step flashing as it lights) under a sliding pointer, the level's
 * block fills and breathes - red when the level is in the top of the scale -
 * while the level number rolls and its name rises beside it.
 */
const SeverityMeter: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const v = num(overlay.value);
  if (!Number.isFinite(v)) return null;
  const tot = Math.round(num(overlay.total));
  const N = Number.isFinite(tot) && tot >= 3 && tot <= 7 ? tot : 5;
  const level = Math.max(1, Math.min(N, Math.round(v)));
  const items = itemsOf(overlay);
  const nameOf = (i: number): string => {
    const it = items[i];
    const own = it ? clip(cap(it.label || it.text), 16) : "";
    return own || (N === 5 ? LEVEL_NAMES[i] : `LEVEL ${i + 1}`);
  };
  const tone = level / N >= 0.7 ? RED : acc;
  const BW = (N > 5 ? 118 : 146) * k, GAP = 18 * k, HMIN = 84 * k, HMAX = 320 * k;
  const hOf = (i: number) => HMIN + (HMAX - HMIN) * (i / (N - 1));
  const buildAt = 8, chargeAt = 28, step = 6;
  const activeAt = chargeAt + (level - 1) * step;
  const travel = interpolate(frame, [chargeAt - 2, activeAt + 2], [0, level - 1], { ...clamp, easing: inOut });
  const ptrIn = ramp(frame, chargeAt - 6, 10, backOut) * (1 - ramp(frame, outAt, 8, easeIn));
  const bob = Math.sin(frame / (fps * 0.3)) * 4 * k;
  const W = N * BW + (N - 1) * GAP;
  const ptrX = travel * (BW + GAP) + BW / 2;
  const hPtr = HMIN + (HMAX - HMIN) * (travel / (N - 1));
  const sub = str(overlay.subtitle);
  const unit = clip(cap(overlay.label) || "LEVEL", 20);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 34 * k }}>
          {str(overlay.text) ? (
            <Rise at={0} frames={1} outAt={outAt + 3}>
              <Heading text={str(overlay.text)} accent={acc} size={56} />
            </Rise>
          ) : null}
          <div style={{ display: "flex", alignItems: "flex-end", gap: 90 * k }}>
            <div style={{ position: "relative", width: W }}>
              <div style={{ position: "absolute", left: ptrX - 16 * k, top: HMAX - hPtr - 46 * k + bob, width: 32 * k,
                height: 26 * k, transform: `scale(${Math.max(0, ptrIn)})`, opacity: ptrIn > 0.01 ? 1 : 0 }}>
                <svg width={32 * k} height={26 * k} viewBox="0 0 32 26" style={{ display: "block" }}>
                  <path d="M2 2 H30 L16 24 Z" fill="#fff" />
                </svg>
              </div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: GAP, height: HMAX }}>
                {Array.from({ length: N }, (_, i) => {
                  const rise = ramp(frame, buildAt + i * 3, 14, backOut);
                  const fall = ramp(frame, outAt + (N - 1 - i), 8, easeIn);
                  const lit = i < level;
                  const at = chargeAt + i * step;
                  const on = lit ? ramp(frame, at, 8) : 0;
                  const flash = lit ? interpolate(frame, [at, at + 2, at + 12], [0, 1, 0], clamp) : 0;
                  const active = i === level - 1;
                  const fillH = active ? ramp(frame, at, 16, inOut) : on;
                  const col = active ? tone : "#ffffff";
                  const alpha = active ? 1 : 0.22 + 0.4 * ((i + 1) / level);
                  const breathe = active ? 0.5 + 0.5 * Math.sin((frame - at) / (fps * 0.32)) : 0;
                  const period = Math.max(1, Math.round(fps * 1.6));
                  const shimmer = active ? ((((frame - at) % period) + period) % period) / period : 0;
                  return (
                    <div key={i} style={{ position: "relative", width: BW, height: hOf(i), boxSizing: "border-box",
                      overflow: "hidden", borderRadius: `${8 * k}px ${8 * k}px ${3 * k}px ${3 * k}px`,
                      transform: `scaleY(${Math.max(0, rise * (1 - fall))})`, transformOrigin: "50% 100%",
                      background: "rgba(255,255,255,.05)",
                      border: `${2 * k}px solid ${on > 0.5 ? rgba(col, active ? 0.95 : 0.55) : "rgba(255,255,255,.24)"}`,
                      boxShadow: active && on > 0 ? `0 0 ${(26 + 22 * breathe) * k}px ${rgba(tone, 0.5 * on)}` : "none" }}>
                      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${fillH * 100}%`,
                        background: `linear-gradient(180deg, ${rgba(col, alpha)} 0%, ${rgba(col, alpha * 0.72)} 100%)` }} />
                      {active && on > 0.9 ? (
                        <div style={{ position: "absolute", left: 0, right: 0, height: "30%", bottom: `${-30 + shimmer * 130}%`,
                          background: "linear-gradient(0deg, rgba(255,255,255,0), rgba(255,255,255,.28), rgba(255,255,255,0))" }} />
                      ) : null}
                      <div style={{ position: "absolute", inset: 0, background: "#fff", opacity: flash * 0.85 }} />
                    </div>
                  );
                })}
              </div>
              <div style={{ display: "flex", gap: GAP, marginTop: 14 * k }}>
                {Array.from({ length: N }, (_, i) => {
                  const active = i === level - 1;
                  const lit = i < level;
                  return (
                    <div key={i} style={{ width: BW, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 * k }}>
                      <Rise at={buildAt + 6 + i * 3}>
                        <span style={{ fontFamily: DISPLAY, fontSize: 46 * k, lineHeight: 1,
                          color: active ? tone : lit ? "#fff" : "rgba(255,255,255,.4)" }}>{i + 1}</span>
                      </Rise>
                      <Rise at={buildAt + 8 + i * 3} style={{ width: BW + GAP * 0.8, textAlign: "center" }}>
                        <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 21 * k, lineHeight: 1.1,
                          letterSpacing: "0.12em", color: active ? "#fff" : "rgba(255,255,255,.5)" }}>{nameOf(i)}</span>
                      </Rise>
                    </div>
                  );
                })}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 * k, minWidth: 360 * k, paddingBottom: 44 * k }}>
              <Rise at={chargeAt - 8}>
                <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.34em",
                  color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{unit}</span>
              </Rise>
              <Rise at={chargeAt - 4} outAt={outAt + 1}>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 12 * k }}>
                  <Odometer value={level} at={chargeAt} frames={Math.max(16, activeAt - chargeAt + 14)} size={190 * k}
                    color={tone} />
                  <span style={{ fontFamily: DISPLAY, fontSize: 76 * k, lineHeight: 1, color: "rgba(255,255,255,.4)",
                    marginBottom: 14 * k }}>/{N}</span>
                </div>
              </Rise>
              <Letters text={nameOf(level - 1)} at={activeAt + 8} step={1} outAt={outAt + 2} style={{ fontFamily: DISPLAY,
                fontSize: 70 * k, lineHeight: 1, letterSpacing: "0.04em", color: "#fff" }} />
              {sub ? fitLines(sub, 30, 2).map((ln, i) => (
                <Rise key={i} at={activeAt + 14 + i * 3} style={{ marginTop: i ? 0 : 6 * k }}>
                  <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 28 * k, color: "rgba(255,255,255,.75)",
                    whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              )) : null}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. countdown timer
type ClockSpec = { total: number; mode: "days" | "hms" | "ms"; dayW: number };
type Group = { digits: string; label: string };

const UNIT_SECONDS: Record<string, number> = {
  s: 1, sec: 1, secs: 1, second: 1, seconds: 1,
  min: 60, mins: 60, minute: 60, minutes: 60,
  h: 3600, hr: 3600, hrs: 3600, hour: 3600, hours: 3600,
  d: 86400, day: 86400, days: 86400,
  wk: 604800, wks: 604800, week: 604800, weeks: 604800,
};
const CLOCK_RE = /\b(\d{1,3}):([0-5]\d)(?::([0-5]\d))?\b/;
const SPAN_RE = /(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b/i;

/** The time left: value + a time suffix (seconds when none), else "72 hours" / "04:59" in the words. */
const parseClock = (ov: Overlay): ClockSpec | null => {
  let total = NaN;
  let unit = 1;
  const v = num(ov.value);
  if (Number.isFinite(v) && v > 0) {
    const suf = str(ov.suffix).toLowerCase().replace(/[^a-z]/g, "");
    const u = suf ? UNIT_SECONDS[suf] : 1;
    if (!u) return null;
    total = v * u;
    unit = u;
  } else {
    for (const s of [str(ov.label), str(ov.text), str(ov.subtitle)]) {
      const c = CLOCK_RE.exec(s);
      if (c) {
        const a = Number(c[1]), b = Number(c[2]);
        total = c[3] !== undefined ? a * 3600 + b * 60 + Number(c[3]) : a * 60 + b;
        unit = c[3] !== undefined ? 3600 : 1;
        break;
      }
      const m = SPAN_RE.exec(s);
      if (m) {
        const u = UNIT_SECONDS[m[2].toLowerCase()];
        if (u) {
          total = Number(m[1]) * u;
          unit = u;
          break;
        }
      }
    }
  }
  if (!Number.isFinite(total) || total <= 0 || total > 999 * 86400) return null;
  total = Math.round(total * 10) / 10;
  const mode: ClockSpec["mode"] = unit >= 86400 || total >= 100 * 3600 ? "days" : unit >= 3600 || total >= 3600 ? "hms" : "ms";
  return { total, mode, dayW: Math.max(2, String(Math.floor(total / 86400)).length) };
};

const pad = (n: number, w: number): string => String(Math.max(0, Math.floor(n))).padStart(w, "0");
const clockGroups = (r: number, c: ClockSpec): Group[] => {
  if (c.mode === "ms") {
    const t = Math.max(0, Math.floor(r * 10 + 1e-6));
    const s = Math.floor(t / 10);
    return [{ digits: pad(Math.floor(s / 60), 2), label: "MIN" }, { digits: pad(s % 60, 2), label: "SEC" },
      { digits: String(t % 10), label: "" }];
  }
  const s = Math.max(0, Math.ceil(r - 1e-6));
  const hms: Group[] = [
    { digits: pad(c.mode === "days" ? Math.floor(s / 3600) % 24 : Math.floor(s / 3600), 2), label: "HRS" },
    { digits: pad(Math.floor(s / 60) % 60, 2), label: "MIN" },
    { digits: pad(s % 60, 2), label: "SEC" },
  ];
  return c.mode === "days" ? [{ digits: pad(Math.floor(s / 86400), c.dayW), label: "DAYS" }, ...hms] : hms;
};

/**
 * Time running out: mono digits in glass cells rise in, then tick in real
 * time from the value - each changed digit rolls up out of its cell, the
 * colons blink, a red pulse runs under the row on every second, and the last
 * ten seconds turn red.
 */
const CountdownTimer: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const spec = parseClock(overlay);
  if (!spec) return null;
  const startF = Math.round(fps * 0.7);
  const remain = (f: number) => spec.total - Math.max(0, f - startF) / fps;
  const flat = (f: number) => clockGroups(remain(Math.max(0, f)), spec).map((g) => g.digits).join("");
  const groups = clockGroups(remain(frame), spec);
  const roll = rollChars(flat, frame, 6);
  const offs = groups.map((_, gi) => groups.slice(0, gi).reduce((a, g) => a + g.digits.length, 0));
  const nDigits = roll.length;
  const size = (nDigits <= 5 ? 168 : nDigits <= 7 ? 140 : nDigits <= 8 ? 124 : 108) * k;
  const cellW = size * 0.72, cellH = size * 1.18;
  const hot = remain(frame) <= 10;
  const running = frame >= startF;
  const ph = running ? ((frame - startF) % fps) / fps : 0;
  const blink = running && ph >= 0.5 ? 0.25 : 1;
  const rawLabel = str(overlay.label);
  const kicker = clip(rawLabel && !CLOCK_RE.test(rawLabel) && !SPAN_RE.test(rawLabel) ? rawLabel.toUpperCase() : "COUNTDOWN", 28);
  const rawText = str(overlay.text);
  const caption = /^[\d\s:.]+$/.test(rawText) ? "" : rawText.toUpperCase();
  const capLines = fitLines(caption, 26, 2);
  const sub = clip(str(overlay.subtitle), 60);
  const dot = ramp(frame, 2, 10, backOut) * (1 - ramp(frame, outAt, 8, easeIn));
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 * k }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
            <div style={{ width: 14 * k, height: 14 * k, borderRadius: "50%", background: RED,
              transform: `scale(${Math.max(0, dot)})`, opacity: running && ph >= 0.5 ? 0.35 : 1,
              boxShadow: `0 0 ${12 * k}px ${rgba(RED, 0.9)}` }} />
            <Letters text={kicker} at={4} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
              letterSpacing: "0.34em", color: "rgba(255,255,255,.86)" }} />
          </div>
          <div style={{ position: "relative", display: "flex", alignItems: "flex-start", gap: 12 * k }}>
            {groups.map((g, gi) => (
              <React.Fragment key={gi}>
                {gi > 0 ? (
                  <div style={{ height: cellH, display: "flex", alignItems: "center", fontFamily: MONO, fontWeight: 700,
                    fontSize: size * 0.6, lineHeight: 1, color: acc,
                    opacity: spec.mode === "ms" && gi === groups.length - 1 ? 1 : blink,
                    transform: `scaleY(${Math.max(0, ramp(frame, 10 + gi * 3, 10) * (1 - ramp(frame, outAt + 2, 8, easeIn)))})` }}>
                    {spec.mode === "ms" && gi === groups.length - 1 ? "." : ":"}
                  </div>
                ) : null}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 * k }}>
                  <div style={{ display: "flex", gap: 8 * k }}>
                    {Array.from(g.digits).map((_, j) => {
                      const i = offs[gi] + j;
                      const r: RollCh | undefined = roll[i];
                      const cin = ramp(frame, 6 + i * 2, 12);
                      const cout = ramp(frame, outAt + i * 0.5, 8, easeIn);
                      const face: React.CSSProperties = { position: "absolute", inset: 0, display: "flex", alignItems: "center",
                        justifyContent: "center", fontFamily: MONO, fontWeight: 700, fontSize: size, lineHeight: 1,
                        color: hot ? RED : "#fff" };
                      return (
                        <div key={j} style={{ position: "relative", width: cellW, height: cellH, overflow: "hidden",
                          borderRadius: 12 * k, boxSizing: "border-box", border: `${1.5 * k}px solid rgba(255,255,255,.16)`,
                          background: "linear-gradient(180deg, rgba(255,255,255,.1) 0%, rgba(255,255,255,.03) 100%)",
                          boxShadow: `0 ${14 * k}px ${40 * k}px rgba(0,0,0,.35), inset 0 ${1 * k}px 0 rgba(255,255,255,.12)`,
                          transform: `scaleY(${Math.max(0, Math.min(1, cin * 1.2) * (1 - cout))})` }}>
                          {r && r.p < 1 ? <div style={{ ...face, transform: `translateY(${-r.p * 100}%)` }}>{r.old}</div> : null}
                          <div style={{ ...face,
                            transform: `translateY(${(r ? 1 - r.p : 0) * 100 + (1 - cin) * 110 - cout * 110}%)` }}>
                            {r ? r.cur : ""}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  {g.label ? (
                    <Rise at={14 + gi * 3}>
                      <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.32em",
                        color: "rgba(255,255,255,.55)" }}>{g.label}</span>
                    </Rise>
                  ) : null}
                </div>
              </React.Fragment>
            ))}
            {running ? (
              <div style={{ position: "absolute", left: "50%", top: cellH + 5 * k, height: 2 * k,
                width: `${(0.2 + 0.8 * expo(ph)) * 100}%`, transform: "translateX(-50%)",
                background: `linear-gradient(90deg, ${rgba(RED, 0)} 0%, ${RED} 50%, ${rgba(RED, 0)} 100%)`,
                opacity: (1 - ph) * (1 - ramp(frame, outAt, 8)) }} />
            ) : null}
          </div>
          {capLines.map((ln, i) => (
            <Letters key={i} text={ln} at={20 + i * 5} step={0.8} outAt={outAt + i} style={{ fontFamily: DISPLAY,
              fontSize: 60 * k, lineHeight: 1, letterSpacing: "0.04em", color: "#fff", marginTop: i ? -10 * k : 0 }} />
          ))}
          {sub ? (
            <Rise at={28}>
              <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 28 * k, color: "rgba(255,255,255,.72)",
                whiteSpace: "nowrap" }}>{sub}</span>
            </Rise>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. live tag
type Wall = { secs: number; h12: boolean; zone: string };
const WALL_RE = /^\s*(\d{1,2})[:.](\d{2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*([a-z]{2,5})?\s*$/i;

/** "9:41 AM CDT" / "21:05" -> seconds since midnight; missing seconds come from a seed. */
const parseWall = (s: string, seed: number): Wall | null => {
  const m = WALL_RE.exec(s);
  if (!m) return null;
  let h = Number(m[1]);
  const mi = Number(m[2]);
  const se = m[3] !== undefined ? Number(m[3]) : 6 + (seed % 48);
  const ap = (m[4] || "").toLowerCase().replace(/\./g, "");
  if (mi > 59 || se > 59) return null;
  if (ap) {
    if (h < 1 || h > 12) return null;
    h = (h % 12) + (ap === "pm" ? 12 : 0);
  } else if (h > 23) {
    return null;
  }
  return { secs: h * 3600 + mi * 60 + se, h12: Boolean(ap), zone: (m[5] || "").toUpperCase() };
};
const wallText = (w: Wall, add: number): string => {
  const t = (((w.secs + add) % 86400) + 86400) % 86400;
  const H = Math.floor(t / 3600), M = Math.floor(t / 60) % 60, S = t % 60;
  const hh = w.h12 ? String(H % 12 || 12) : String(H).padStart(2, "0");
  return `${hh}:${String(M).padStart(2, "0")}:${String(S).padStart(2, "0")}${w.h12 ? (H >= 12 ? " PM" : " AM") : ""}` +
    `${w.zone ? ` ${w.zone}` : ""}`;
};

/**
 * A live bug top-right: a white LIVE chip wipes open with a beating red dot,
 * a divider draws, the place rises letter by letter over an accent rule and
 * the local time ticks by the second, each changed digit rolling.
 */
const LiveTag: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const where = clip(cap(overlay.text), 30);
  if (!where) return null;
  const rawTime = str(overlay.label);
  const wall = parseWall(rawTime, hash(where));
  const fixed = wall ? "" : clip(cap(rawTime), 26);
  const sub = clip(cap(overlay.subtitle), 34);
  const chipIn = ramp(frame, 0, 14);
  const chipPop = ramp(frame, 0, 16, backOut);
  const chipOut = ramp(frame, outAt + 6, 7, easeIn);
  const divider = ramp(frame, 8, 12) * (1 - ramp(frame, outAt + 3, 8, easeIn));
  const rule = ramp(frame, 18, 18) * (1 - ramp(frame, outAt + 1, 8, easeIn));
  const bp = (frame % Math.max(1, Math.round(fps))) / Math.max(1, Math.round(fps));
  const chars = wall ? rollChars((f) => wallText(wall, Math.floor(Math.max(0, f) / fps)), frame, 5) : [];
  return (
    <AbsoluteFill>
      <Shade outAt={outAt}
        bg="radial-gradient(ellipse 46% 36% at 100% 0%, rgba(0,0,0,.46) 0%, rgba(0,0,0,.16) 55%, rgba(0,0,0,0) 100%)" />
      <div style={{ position: "absolute", right: 90 * k, top: 86 * k, display: "flex", alignItems: "center", gap: 20 * k }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 * k, padding: `${8 * k}px ${16 * k}px ${7 * k}px ${13 * k}px`,
          borderRadius: 8 * k, background: "#f4f4f1", boxShadow: `0 ${8 * k}px ${24 * k}px rgba(0,0,0,.35)`,
          clipPath: `inset(0 ${(1 - chipIn) * 100}% 0 ${chipOut * 100}% round ${8 * k}px)`,
          transform: `scale(${0.86 + 0.14 * chipPop})`, transformOrigin: "0% 50%" }}>
          <div style={{ position: "relative", width: 16 * k, height: 16 * k, flexShrink: 0 }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `${2 * k}px solid ${RED}`,
              transform: `scale(${1 + bp * 1.2})`, opacity: (1 - bp) * 0.9 }} />
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: RED,
              transform: `scale(${0.8 + 0.2 * beat(bp)})`, boxShadow: `0 0 ${10 * k}px ${rgba(RED, 0.75)}` }} />
          </div>
          <Letters text="LIVE" at={4} step={1.5} outAt={outAt + 2} style={{ fontFamily: DISPLAY, fontSize: 38 * k, lineHeight: 1,
            letterSpacing: "0.1em", color: INK, paddingTop: 3 * k }} />
        </div>
        <div style={{ width: 2 * k, height: 60 * k, background: "rgba(255,255,255,.6)", transform: `scaleY(${Math.max(0, divider)})` }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 5 * k, textShadow: "0 3px 14px rgba(0,0,0,.6)" }}>
          <Letters text={where} at={10} step={0.7} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k, lineHeight: 1.05,
            letterSpacing: "0.06em", color: "#fff" }} />
          <div style={{ height: 2 * k, width: `${rule * 100}%`, background: acc }} />
          {wall || fixed || sub ? (
            <Rise at={18}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 * k, fontFamily: MONO, fontWeight: 700,
                fontSize: 22 * k, letterSpacing: "0.08em", whiteSpace: "nowrap" }}>
                {wall ? (
                  <span style={{ display: "inline-flex", color: acc }}>
                    {chars.map((r, i) => (
                      <span key={i} style={{ position: "relative", display: "inline-block", overflow: "hidden", whiteSpace: "pre" }}>
                        <span style={{ display: "inline-block", transform: `translateY(${(1 - r.p) * 100}%)` }}>{r.cur}</span>
                        {r.p < 1 ? (
                          <span style={{ position: "absolute", left: 0, top: 0, transform: `translateY(${-r.p * 100}%)` }}>{r.old}</span>
                        ) : null}
                      </span>
                    ))}
                  </span>
                ) : fixed ? <span style={{ color: acc }}>{fixed}</span> : null}
                {sub ? <span style={{ color: "rgba(255,255,255,.72)" }}>{wall || fixed ? `· ${sub}` : sub}</span> : null}
              </div>
            </Rise>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. emergency stamp
const starPath = (cx: number, cy: number, R: number, r: number, n: number): string => {
  let d = "";
  for (let i = 0; i < n * 2; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / n;
    const rr = i % 2 === 0 ? R : r;
    d += `${i ? "L" : "M"}${(cx + Math.cos(a) * rr).toFixed(2)} ${(cy + Math.sin(a) * rr).toFixed(2)}`;
  }
  return `${d}Z`;
};

/**
 * A proclamation slides up onto a dark desk (a seal drawing itself, the
 * title letter by letter, the text beneath); the DECLARED stamp drops from
 * above with its shadow and slams down - the camera shakes, the ink bleeds a
 * little, specks spray and dust puffs out - a double impression ghosts in,
 * the signature writes itself. At the end the sheet slides away.
 */
const EmergencyStamp: Look = ({ overlay }) => {
  const { frame, fps, dur, outAt, width } = useClock();
  const k = useK();
  const title = cap(overlay.text);
  if (!title) return null;
  const hl = cap(overlay.highlight);
  const word = hl && hl.length <= 12 && hl.split(" ").length <= 2 ? hl : "DECLARED";
  const date = clip(cap(overlay.subtitle), 24);
  const issuer = clip(cap(overlay.label), 40);
  const body = str(overlay.body);
  const id = `al-st-${overlay.startFrame}`;
  const seed = hash(title + word);
  const fi = Math.round(fps * 1.05);
  const since = frame - fi;
  const hit = since >= 0;
  const bgA = backdropAlpha(overlay, frame, dur);
  const shake = hit ? Math.exp(-since / 4.5) : 0;
  const sx = Math.sin(since * 2.9) * 11 * k * shake;
  const sy = Math.cos(since * 3.7) * 8 * k * shake;
  const push = 1 + 0.05 * lin(frame, 0, dur);
  const land = ramp(frame, 0, 18);
  const leave = ramp(frame, outAt + 2, 11, easeIn);
  const SW = 1180 * k, SH = 1200 * k, SX = (width - SW) / 2, SY = 64 * k;
  const scx = SW * 0.62, scy = 610 * k;
  const STW = 700 * k, STH = 276 * k;
  const fall = ramp(frame, fi - 9, 9, easeIn);
  const stampScale = hit ? 1 - 0.03 * Math.sin(Math.PI * lin(frame, fi, fi + 6)) : 2.3 - 1.3 * fall;
  const stampO = hit ? 0.93 : Math.min(1, fall * 2.4) * 0.6;
  const bleed = hit ? ramp(frame, fi, 10) : 0;
  const ring = lin(frame, fi, fi + 10);
  const seal = ramp(frame, 2, 22, inOut);
  const rules = ramp(frame, 8, 20);
  const sig = ramp(frame, fi + 10, 22, inOut);
  const tl = fitLines(title, 20, 2);
  const bodyL = fitLines(body, 60, 3);
  const top = title.length <= 24 ? title : "EMERGENCY";
  const sealText = `${issuer || "OFFICIAL RECORD"} • `.repeat(4).slice(0, 36);
  const wordY = date ? 196 : 214;
  const stampBody = (ghost: boolean) => (
    <g mask={`url(#${id}m)`} opacity={ghost ? 0.14 : 1} transform={ghost ? "translate(4 3)" : undefined}>
      <rect x={8} y={8} width={684} height={260} rx={16} fill="none" stroke={STAMP_RED} strokeWidth={10 + bleed * 1.4} />
      <rect x={25} y={25} width={650} height={226} rx={8} fill="none" stroke={STAMP_RED} strokeWidth={3 + bleed * 0.8} />
      <line x1={64} x2={636} y1={90} y2={90} stroke={STAMP_RED} strokeWidth={3} />
      <text x={350} y={74} textAnchor="middle" fill={STAMP_RED} fontFamily={LABEL} fontWeight={800} fontSize={38}
        letterSpacing={5} textLength={Math.min(560, top.length * 25)} lengthAdjust="spacingAndGlyphs">{top}</text>
      <text x={350} y={wordY} textAnchor="middle" fill={STAMP_RED} stroke={STAMP_RED} strokeWidth={bleed * 1.6}
        fontFamily={DISPLAY} fontSize={128} letterSpacing={6} textLength={Math.min(600, word.length * 72)}
        lengthAdjust="spacingAndGlyphs">{word}</text>
      {date ? (
        <>
          <line x1={64} x2={636} y1={212} y2={212} stroke={STAMP_RED} strokeWidth={3} />
          <text x={350} y={246} textAnchor="middle" fill={STAMP_RED} fontFamily={MONO} fontWeight={700} fontSize={27}
            letterSpacing={4} textLength={Math.min(540, date.length * 21)} lengthAdjust="spacingAndGlyphs">{date}</text>
        </>
      ) : null}
    </g>
  );
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bgA,
        background: "radial-gradient(ellipse 75% 65% at 50% 38%, #2c2d32 0%, #16171a 55%, #08080a 100%)" }} />
      <AbsoluteFill style={{ opacity: bgA,
        background: "radial-gradient(ellipse 40% 30% at 50% 12%, rgba(255,255,255,.06) 0%, rgba(255,255,255,0) 100%)" }} />
      <AbsoluteFill style={{ opacity: bgA, transform: `translate(${sx}px, ${sy}px) scale(${push})`,
        transformOrigin: `${SX + scx}px ${SY + scy}px` }}>
        <div style={{ position: "absolute", left: SX, top: SY, width: SW, height: SH, boxSizing: "border-box",
          padding: `${72 * k}px ${100 * k}px`,
          transform: `translateY(${(1 - land) * 140 * k + leave * 1300 * k}px) rotate(${-1.4 - (1 - land) * 2 + leave * 5}deg)`,
          background: `radial-gradient(rgba(0,0,0,.035) ${1 * k}px, transparent ${1.4 * k}px) 0 0 / ${6 * k}px ${6 * k}px, ` +
            "linear-gradient(180deg, #f7f5ef 0%, #ebe8df 100%)",
          boxShadow: `0 ${40 * k}px ${100 * k}px rgba(0,0,0,.55)` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 28 * k }}>
            <svg width={118 * k} height={118 * k} viewBox="0 0 120 120" style={{ flexShrink: 0 }}>
              <defs>
                <path id={`${id}arc`} d="M60 60 m-44 0 a44 44 0 1 1 88 0 a44 44 0 1 1 -88 0" />
              </defs>
              <circle cx="60" cy="60" r="56" fill="none" stroke="#1d2530" strokeWidth="3" pathLength={1} strokeDasharray={1}
                strokeDashoffset={1 - seal} />
              <circle cx="60" cy="60" r="33" fill="none" stroke="#1d2530" strokeWidth="1.5" pathLength={1} strokeDasharray={1}
                strokeDashoffset={1 - seal} />
              <text fontFamily={MONO} fontWeight={700} fontSize="9.5" letterSpacing="1.6" fill="#1d2530" opacity={seal}>
                <textPath href={`#${id}arc`}>{sealText}</textPath>
              </text>
              <path d={starPath(60, 60, 22, 9, 5)} fill="#1d2530" opacity={seal}
                transform={`rotate(${(1 - seal) * -90} 60 60)`} />
            </svg>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 * k }}>
              {issuer ? (
                <Letters text={issuer} at={4} step={0.4} style={{ fontFamily: NARROW, fontWeight: 700, fontSize: 26 * k,
                  letterSpacing: "0.16em", color: "#1b2129" }} />
              ) : null}
              <Letters text={date ? `ISSUED ${date}` : "OFFICIAL NOTICE"} at={8} step={0.4} style={{ fontFamily: MONO,
                fontWeight: 500, fontSize: 16 * k, letterSpacing: "0.24em", color: "#6b7480" }} />
            </div>
          </div>
          <div style={{ marginTop: 26 * k, width: `${rules * 100}%` }}>
            <div style={{ height: 4 * k, background: "#1d2530" }} />
            <div style={{ height: 1.5 * k, background: "#1d2530", marginTop: 5 * k }} />
          </div>
          <div style={{ marginTop: 40 * k }}>
            {tl.map((ln, i) => (
              <Letters key={i} text={ln} at={10 + i * 5} step={0.8} outAt={outAt + i} style={{ fontFamily: NARROW, fontWeight: 700,
                fontSize: 80 * k, lineHeight: 1.04, letterSpacing: "0.01em", color: "#12161c" }} />
            ))}
          </div>
          {bodyL.length ? (
            <div style={{ marginTop: 22 * k }}>
              {bodyL.map((ln, i) => (
                <Rise key={i} at={18 + i * 3}>
                  <span style={{ fontFamily: INTER, fontWeight: 500, fontSize: 26 * k, lineHeight: 1.5, color: "#2b3038",
                    whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              ))}
            </div>
          ) : null}
          <div style={{ marginTop: 18 * k }}>
            {[96, 91, 98, 84, 93, 88, 70].map((w, i) => (
              <div key={i} style={{ height: 12 * k, width: `${w * ramp(frame, 14 + i * 2, 14)}%`, background: "rgba(40,48,60,.16)",
                borderRadius: 3 * k, margin: `${16 * k}px 0` }} />
            ))}
          </div>
          <div style={{ position: "absolute", left: 100 * k, top: 890 * k, width: 330 * k }}>
            <svg width={320 * k} height={110 * k} viewBox="0 0 320 110" style={{ display: "block" }}>
              <path d="M10 78 C 26 40, 40 20, 50 44 S 58 92, 76 62 S 102 14, 118 48 S 132 86, 150 58 C 160 42, 172 30, 180 50 S 200 78, 216 52 S 244 36, 262 48 L 300 40"
                fill="none" stroke="#1f2a44" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" pathLength={1}
                strokeDasharray={1} strokeDashoffset={1 - sig} />
              <line x1={6} x2={310} y1={98} y2={98} stroke="#39414c" strokeWidth={1.5} opacity={rules} />
            </svg>
            <Rise at={fi + 12} style={{ marginTop: 6 * k }}>
              <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 13 * k, letterSpacing: "0.24em", color: "#6b7480",
                whiteSpace: "nowrap" }}>AUTHORIZED SIGNATURE</span>
            </Rise>
          </div>
          <div style={{ position: "absolute", left: scx - STW / 2, top: scy - STH / 2, width: STW, height: STH,
            transform: `rotate(-8deg) scale(${stampScale})`, opacity: stampO, mixBlendMode: "multiply" }}>
            {!hit && fall > 0 ? (
              <div style={{ position: "absolute", inset: 0, borderRadius: 18 * k, background: "rgba(0,0,0,.28)",
                filter: `blur(${(10 + 26 * (1 - fall)) * k}px)`,
                transform: `translate(${(1 - fall) * 50 * k}px, ${(1 - fall) * 70 * k}px)` }} />
            ) : null}
            <svg width={STW} height={STH} viewBox="0 0 700 276" style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <mask id={`${id}m`} maskUnits="userSpaceOnUse" x={-20} y={-20} width={740} height={316}>
                  <rect x={-20} y={-20} width={740} height={316} fill="#fff" />
                  {Array.from({ length: 46 }, (_, i) => (
                    <circle key={i} cx={rnd(seed + i * 3) * 700} cy={rnd(seed + i * 3 + 1) * 276}
                      r={0.8 + rnd(seed + i * 3 + 2) * 4.4} fill="#000" />
                  ))}
                  {Array.from({ length: 6 }, (_, i) => {
                    const x = rnd(seed + 300 + i) * 600 + 30, y = rnd(seed + 320 + i) * 240 + 18;
                    return (
                      <line key={`s${i}`} x1={x} y1={y} x2={x + 40 + rnd(seed + 340 + i) * 120}
                        y2={y + (rnd(seed + 360 + i) - 0.5) * 16} stroke="#000" strokeWidth={1 + rnd(seed + 380 + i) * 2.2}
                        strokeLinecap="round" opacity={0.75} />
                    );
                  })}
                </mask>
              </defs>
              {hit ? stampBody(true) : null}
              {stampBody(false)}
              {hit ? Array.from({ length: 16 }, (_, i) => {
                const a = rnd(seed + 500 + i) * Math.PI * 2;
                const out = (10 + rnd(seed + 520 + i) * 46) * ramp(frame, fi, 6);
                return (
                  <circle key={`p${i}`} cx={350 + Math.cos(a) * (360 + out)} cy={138 + Math.sin(a) * (150 + out * 0.6)}
                    r={1.2 + rnd(seed + 540 + i) * 3.6} fill={STAMP_RED} opacity={0.85} />
                );
              }) : null}
            </svg>
          </div>
          {hit && since <= 34 ? (
            <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <radialGradient id={`${id}d`}>
                  <stop offset="0%" stopColor="#6e6252" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#6e6252" stopOpacity={0} />
                </radialGradient>
              </defs>
              {Array.from({ length: 14 }, (_, i) => {
                const a = (i / 14) * Math.PI * 2 + rnd(seed + 600 + i) * 0.4;
                const q = ramp(frame, fi, 26 + rnd(seed + 620 + i) * 8);
                const bx = scx + Math.cos(a) * STW * 0.5, by = scy + Math.sin(a) * STH * 0.55;
                const d2 = (40 + rnd(seed + 640 + i) * 80) * k * q;
                return (
                  <circle key={i} cx={bx + Math.cos(a) * d2} cy={by + Math.sin(a) * d2 * 0.6 - q * 20 * k} r={(16 + 50 * q) * k}
                    fill={`url(#${id}d)`} opacity={(1 - q) * 0.9} />
                );
              })}
              <ellipse cx={scx} cy={scy} rx={STW * 0.55 * (1 + 0.35 * ring)} ry={STH * 0.62 * (1 + 0.35 * ring)} fill="none"
                stroke="rgba(40,30,20,.3)" strokeWidth={4 * k * (1 - ring)} opacity={1 - ring}
                transform={`rotate(-8 ${scx} ${scy})`} />
            </svg>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. slim ticker
/**
 * A slim dark-glass ticker low on the frame (inset, never a red band): the
 * accent chip springs up, the bar extends out of it with the sentence already
 * crawling, a light runs along its top edge; at the end the bar retracts into
 * the chip, taking the text with it.
 */
const SlimTicker: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const main = str(overlay.text);
  if (!main) return null;
  const extra = itemsOf(overlay).map((it) => str(it.text) || str(it.label)).filter(Boolean).slice(0, 4);
  const chip = clip(cap(overlay.label) || "ALERT", 14);
  const clock = clip(cap(overlay.subtitle), 22);
  const ink = inkOn(acc);
  const H = 60 * k;
  const seq = [main, ...extra].map((s) => clip(s, 160));
  const chars = seq.join(" ").length;
  const speed = Math.max(120, Math.min(240, (chars * 15) / 6.5)) * k;
  const crawl = (Math.max(0, frame - 8) / fps) * speed;
  const open = ramp(frame, 6, 18);
  const close = ramp(frame, outAt + 1, 10, easeIn);
  const chipIn = ramp(frame, 0, 12, backOut);
  const chipOut = ramp(frame, outAt + 8, 5, easeIn);
  const period = Math.max(1, Math.round(fps * 0.9));
  const ph = (frame % period) / period;
  const sweep = ((frame / (fps * 2.6)) % 1) * 130 - 25;
  const loop = [...seq, ...seq, ...seq];
  const edge = `linear-gradient(90deg, transparent 0px, #000 ${36 * k}px, #000 calc(100% - ${56 * k}px), transparent 100%)`;
  return (
    <AbsoluteFill>
      <Shade outAt={outAt} bg="linear-gradient(0deg, rgba(0,0,0,.4) 0%, rgba(0,0,0,.12) 16%, rgba(0,0,0,0) 28%)" />
      <div style={{ position: "absolute", left: 90 * k, right: 90 * k, bottom: 90 * k, height: H, display: "flex" }}>
        <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 10 * k,
          padding: `0 ${20 * k}px 0 ${18 * k}px`, background: acc, borderRadius: `${10 * k}px 0 0 ${10 * k}px`,
          transform: `scaleY(${Math.max(0, chipIn * (1 - chipOut))})`, transformOrigin: "50% 100%",
          boxShadow: `0 ${10 * k}px ${26 * k}px rgba(0,0,0,.35)` }}>
          <svg width={22 * k} height={16 * k} viewBox="0 0 22 16" style={{ flexShrink: 0 }}>
            {[0, 1].map((c) => (
              <path key={c} d={`M${2 + c * 8} 2 L${8 + c * 8} 8 L${2 + c * 8} 14`} fill="none" stroke={ink} strokeWidth="2.6"
                strokeLinecap="round" strokeLinejoin="round" opacity={0.35 + 0.65 * beat(ph - c * 0.25)} />
            ))}
          </svg>
          <Letters text={chip} at={6} step={0.8} outAt={outAt + 4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 27 * k,
            letterSpacing: "0.2em", color: ink, paddingTop: 2 * k }} />
        </div>
        <div style={{ position: "relative", flex: 1, display: "flex", alignItems: "stretch", overflow: "hidden",
          borderRadius: `0 ${10 * k}px ${10 * k}px 0`, background: "rgba(11,12,15,.74)",
          backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
          borderTop: `${1 * k}px solid rgba(255,255,255,.1)`, borderRight: `${1 * k}px solid rgba(255,255,255,.1)`,
          borderBottom: `${1 * k}px solid rgba(255,255,255,.1)`,
          clipPath: `inset(0 ${Math.max(1 - open, close) * 100}% 0 0)` }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 2 * k, background: "rgba(255,255,255,.07)" }} />
          <div style={{ position: "absolute", top: 0, height: 2 * k, width: "22%", left: `${sweep}%`,
            background: `linear-gradient(90deg, ${rgba(acc, 0)} 0%, ${acc} 50%, ${rgba(acc, 0)} 100%)` }} />
          <div style={{ position: "relative", flex: 1, overflow: "hidden", maskImage: edge, WebkitMaskImage: edge }}>
            <div style={{ position: "absolute", top: 0, bottom: 0, left: "42%", display: "flex", alignItems: "center",
              whiteSpace: "nowrap", transform: `translateX(${-crawl}px)` }}>
              {loop.map((s, i) => (
                <React.Fragment key={i}>
                  <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 31 * k, color: "#fff", letterSpacing: "0.02em",
                    paddingTop: 2 * k }}>{s}</span>
                  <span style={{ display: "inline-block", flexShrink: 0, width: 9 * k, height: 9 * k, margin: `0 ${30 * k}px`,
                    background: acc, transform: "rotate(45deg)" }} />
                </React.Fragment>
              ))}
            </div>
          </div>
          {clock ? (
            <div style={{ display: "flex", alignItems: "center", padding: `0 ${22 * k}px`,
              borderLeft: `${1 * k}px solid rgba(255,255,255,.14)` }}>
              <Rise at={14}>
                <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 21 * k, letterSpacing: "0.12em",
                  color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{clock}</span>
              </Rise>
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. storm track
const STORM_RE = /hurricane|typhoon|cyclone|tropical|storm/i;

type StormMap = { land: string[]; P: Pt[]; gx: { v: number; label: string }[]; gy: { v: number; label: string }[];
  south: boolean };

/** The track's places on a Mercator map fitted round them (date-line safe), coasts and state lines inside the frame. */
const buildStormMap = (pts: MapLocation[], W: number, H: number): StormMap | null => {
  if (pts.length < 2) return null;
  const lons: number[] = [];
  pts.forEach((p, i) => {
    let lon = p.lon;
    if (i > 0) {
      while (lon - lons[i - 1] > 180) lon -= 360;
      while (lon - lons[i - 1] < -180) lon += 360;
    }
    lons.push(lon);
  });
  const lats = pts.map((p) => p.lat);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const padLon = Math.max(3.5, (maxLon - minLon) * 0.4);
  const padLat = Math.max(2.5, (maxLat - minLat) * 0.4);
  const cLon = (minLon + maxLon) / 2;
  const box = { type: "MultiPoint", coordinates: [[minLon - padLon, Math.max(-80, minLat - padLat)],
    [maxLon + padLon, Math.min(80, maxLat + padLat)]] };
  let proj: GeoProjection;
  try {
    proj = geoMercator().rotate([-cLon, 0]).fitExtent([[W * 0.1, H * 0.2], [W * 0.9, H * 0.86]], box as never)
      .clipExtent([[-60, -60], [W + 60, H + 60]]);
  } catch {
    return null;
  }
  const P: Pt[] = [];
  for (let i = 0; i < pts.length; i++) {
    const q = proj([lons[i], pts[i].lat]);
    if (!q || !Number.isFinite(q[0]) || !Number.isFinite(q[1])) return null;
    P.push([q[0], q[1]]);
  }
  const states = shapesIn(STATES, proj, W, H);
  const world = shapesIn(states.length ? WORLD.filter((f) => f.properties?.name !== US_NAME) : WORLD, proj, W, H);
  const gx: { v: number; label: string }[] = [];
  const gy: { v: number; label: string }[] = [];
  const midLat = (minLat + maxLat) / 2;
  for (let g = Math.floor((minLon - padLon - 40) / 5) * 5; g <= maxLon + padLon + 40; g += 5) {
    const q = proj([g, midLat]);
    if (q && q[0] > 24 && q[0] < W - 24) gx.push({ v: q[0], label: lonLabel(g) });
  }
  for (let g = Math.max(-80, Math.floor((minLat - padLat - 30) / 5) * 5); g <= Math.min(80, maxLat + padLat + 30); g += 5) {
    const q = proj([cLon, g]);
    if (q && q[1] > 24 && q[1] < H - 24) gy.push({ v: q[1], label: latLabel(g) });
  }
  return { land: [...world, ...states], P, gx, gy, south: midLat < 0 };
};

/** A Catmull-Rom curve through the points, S samples per segment. */
const catmull = (P: Pt[], S: number): Pt[] => {
  const out: Pt[] = [];
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
    for (let s = 0; s < S; s++) {
      const t = s / S, t2 = t * t, t3 = t2 * t;
      const f = (a: number, b: number, c: number, d: number) =>
        0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      out.push([f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1])]);
    }
  }
  out.push(P[P.length - 1]);
  return out;
};

const tangentAt = (pts: Pt[], i: number): Pt => {
  const n = pts.length;
  let a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)];
  let dx = b[0] - a[0], dy = b[1] - a[1];
  if (Math.hypot(dx, dy) < 1e-6) {
    a = pts[Math.max(0, i - 2)];
    b = pts[Math.min(n - 1, i + 2)];
    dx = b[0] - a[0];
    dy = b[1] - a[1];
  }
  const L = Math.hypot(dx, dy) || 1;
  return [dx / L, dy / L];
};

/** The cone of uncertainty along a partial track: widening with distance, a round cap at the head. */
const conePath = (pts: Pt[], radii: number[]): string => {
  const n = pts.length;
  if (n < 2) return "";
  const left: Pt[] = [];
  const right: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const [tx, ty] = tangentAt(pts, i);
    const r = radii[i];
    left.push([pts[i][0] - ty * r, pts[i][1] + tx * r]);
    right.push([pts[i][0] + ty * r, pts[i][1] - tx * r]);
  }
  const [tx, ty] = tangentAt(pts, n - 1);
  const r = radii[n - 1];
  const aN = Math.atan2(tx, -ty);
  const capPts: Pt[] = [];
  for (let s = 1; s < 12; s++) {
    const a = aN - (Math.PI * s) / 12;
    capPts.push([pts[n - 1][0] + Math.cos(a) * r, pts[n - 1][1] + Math.sin(a) * r]);
  }
  const ringPts = [...left, ...capPts, ...right.reverse()];
  return `${ringPts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ")} Z`;
};

/** The hurricane symbol: a ring and two swept arms, s = arm reach in px. */
const Hurricane: React.FC<{ s: number; color: string }> = ({ s, color }) => {
  const arm = `M${-0.12 * s} ${-0.34 * s} C${0.2 * s} ${-0.98 * s} ${0.86 * s} ${-0.98 * s} ${1.08 * s} ${-0.52 * s} ` +
    `C${0.76 * s} ${-0.72 * s} ${0.38 * s} ${-0.62 * s} ${0.28 * s} ${-0.2 * s} Z`;
  return (
    <g>
      <circle r={0.3 * s} fill="none" stroke={color} strokeWidth={0.14 * s} />
      <path d={arm} fill={color} />
      <path d={arm} fill={color} transform="rotate(180)" />
    </g>
  );
};

/**
 * A storm (or any threat) moving over a vector coastline: the widening cone
 * and the dashed track draw from the first place to the last behind the
 * storm symbol, spinning the way storms turn in that hemisphere; each place
 * pops as it is passed, its label rising outside the cone; the category rolls
 * in a badge and the landfall place pulses when the track arrives.
 */
const StormTrack: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, outAt, width, height } = useClock();
  const k = useK();
  const acc = safeAccent(accent);
  const pts = placesOf(overlay, 6);
  const key = pts.map((p) => `${p.lat.toFixed(3)},${p.lon.toFixed(3)}`).join("|");
  const map = useMemo(() => buildStormMap(pts, width, height), [key, width, height]);
  const samples = useMemo(() => (map ? catmull(map.P, 16) : []), [map]);
  if (!map || samples.length < 2) return null;
  const S = 16;
  const P = map.P;
  const name = cap(overlay.text);
  const catRaw = Math.round(num(overlay.value));
  const cat = Number.isFinite(catRaw) && catRaw >= 1 && catRaw <= 5 ? catRaw : 0;
  const storm = cat > 0 || STORM_RE.test(`${str(overlay.text)} ${str(overlay.subtitle)} ${str(overlay.label)}`);
  const kicker = clip(cap(overlay.subtitle) || (storm ? "FORECAST TRACK" : "PROJECTED PATH"), 32);
  const letter = cat >= 3 ? "M" : cat >= 1 ? "H" : "S";
  const items = itemsOf(overlay);
  const landfall = clip(cap(overlay.label), 14);
  const labelOf = (i: number): string => {
    const it = items[i];
    const own = it ? clip(cap(it.label || it.text), 18) : "";
    const base = own || clip(cap(short(pts[i] ? pts[i].label : "")), 18);
    return i === P.length - 1 && landfall ? `${landfall} · ${base}` : base;
  };
  const cum: number[] = [0];
  for (let i = 1; i < samples.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(samples[i][0] - samples[i - 1][0], samples[i][1] - samples[i - 1][1]));
  }
  const total = cum[cum.length - 1] || 1;
  const drawAt = 18;
  const drawFrames = Math.max(24, Math.min(Math.round(fps * 2.4), dur - drawAt - 40));
  const d = ramp(frame, drawAt, drawFrames, inOut);
  const headLen = d * total;
  let j = 0;
  while (j < samples.length - 2 && cum[j + 1] <= headLen) j++;
  const segLen = cum[j + 1] - cum[j] || 1;
  const tt = Math.max(0, Math.min(1, (headLen - cum[j]) / segLen));
  const head: Pt = [samples[j][0] + (samples[j + 1][0] - samples[j][0]) * tt, samples[j][1] + (samples[j + 1][1] - samples[j][1]) * tt];
  const part: Pt[] = samples.slice(0, j + 1);
  const partLen: number[] = cum.slice(0, j + 1);
  if (Math.hypot(head[0] - samples[j][0], head[1] - samples[j][1]) > 0.5) {
    part.push(head);
    partLen.push(headLen);
  }
  const rMin = 7 * k, rMax = 104 * k;
  const radius = (len: number) => rMin + (rMax - rMin) * (len / total);
  const cone = part.length >= 2 ? conePath(part, partLen.map(radius)) : "";
  const track = part.length >= 2 ? part.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ") : "";
  const pointLen = P.map((_, i) => cum[Math.min(cum.length - 1, i * S)]);
  const layer = 1 - ramp(frame, outAt + 2, 10);
  const labelsOut = ramp(frame, outAt + 1, 9, easeIn);
  const bgA = backdropAlpha(overlay, frame, dur);
  const push = 1 + 0.05 * lin(frame, 0, dur);
  const xs = P.map((p) => p[0]), ys = P.map((p) => p[1]);
  const midX = (Math.min(...xs) + Math.max(...xs)) / 2, midY = (Math.min(...ys) + Math.max(...ys)) / 2;
  const spin = (map.south ? 1 : -1) * frame * 9;
  const pulse = 0.5 + 0.5 * Math.sin(frame / (fps * 0.25));
  const arriveAt = drawAt + drawFrames;
  const landQ = frame >= arriveAt ? ((frame - arriveAt) % 36) / 36 : -1;
  const badge = ramp(frame, 16, 14, backOut) * (1 - ramp(frame, outAt + 6, 7, easeIn));
  const id = `al-stk-${overlay.startFrame}`;
  const last = P[P.length - 1];
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bgA,
        background: "radial-gradient(ellipse 80% 70% at 50% 45%, #10243b 0%, #0a1829 55%, #050c16 100%)" }} />
      <AbsoluteFill style={{ opacity: bgA, transform: `scale(${push})`, transformOrigin: `${midX}px ${midY}px` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <radialGradient id={`${id}g`}>
              <stop offset="0%" stopColor={RED} stopOpacity={0.55} />
              <stop offset="60%" stopColor={RED} stopOpacity={0.14} />
              <stop offset="100%" stopColor={RED} stopOpacity={0} />
            </radialGradient>
          </defs>
          {map.gx.map((g, i) => (
            <line key={`x${i}`} x1={g.v} x2={g.v} y1={0} y2={height} stroke="rgba(140,185,235,.08)" strokeWidth={1.2 * k} />
          ))}
          {map.gy.map((g, i) => (
            <line key={`y${i}`} x1={0} x2={width} y1={g.v} y2={g.v} stroke="rgba(140,185,235,.08)" strokeWidth={1.2 * k} />
          ))}
          {map.land.map((dd, i) => (
            <path key={`l${i}`} d={dd} fill="#1a2433" stroke="#3a4e66" strokeWidth={1.3 * k} strokeLinejoin="round" />
          ))}
          {map.gy.map((g, i) => (
            <text key={`ty${i}`} x={width - 36 * k} y={g.v - 6 * k} textAnchor="end" fontFamily={MONO} fontWeight={500}
              fontSize={15 * k} fill="rgba(170,205,240,.42)">{g.label}</text>
          ))}
          {map.gx.filter((g) => g.v > 600 * k).map((g, i) => (
            <text key={`tx${i}`} x={g.v + 6 * k} y={height - 34 * k} fontFamily={MONO} fontWeight={500} fontSize={15 * k}
              fill="rgba(170,205,240,.42)">{g.label}</text>
          ))}
          <g opacity={layer}>
            {cone ? (
              <path d={cone} fill="rgba(255,255,255,.13)" stroke="rgba(255,255,255,.78)" strokeWidth={2.4 * k}
                strokeLinejoin="round" />
            ) : null}
            {track ? (
              <path d={track} fill="none" stroke="#fff" strokeWidth={3.6 * k} strokeDasharray={`${14 * k} ${10 * k}`}
                strokeLinecap="round" strokeLinejoin="round" />
            ) : null}
            {landQ >= 0 ? (
              <circle cx={last[0]} cy={last[1]} r={(16 + 56 * landQ) * k} fill="none" stroke={RED} strokeWidth={3 * k}
                opacity={1 - landQ} />
            ) : null}
            {P.map((p, i) => {
              const q = interpolate(headLen - pointLen[i], [-1, total * 0.03 + 1], [0, 1], clamp);
              if (q <= 0) return null;
              const sc = q >= 1 ? 1 : backOut(q);
              return (
                <g key={`p${i}`} transform={`translate(${p[0]} ${p[1]}) scale(${sc})`}>
                  <circle r={15 * k} fill="#0b0f15" stroke="#fff" strokeWidth={3 * k} />
                  {storm ? (
                    <text y={7 * k} textAnchor="middle" fontFamily={DISPLAY} fontSize={21 * k} fill="#fff">{letter}</text>
                  ) : (
                    <circle r={5 * k} fill={RED} />
                  )}
                </g>
              );
            })}
            <circle cx={head[0]} cy={head[1]} r={80 * k} fill={`url(#${id}g)`} opacity={0.7 + 0.3 * pulse} />
            {storm ? (
              <g transform={`translate(${head[0]} ${head[1]}) rotate(${spin}) scale(${map.south ? -1 : 1} 1)`}>
                <Hurricane s={42 * k} color="#fff" />
              </g>
            ) : (
              <g>
                <circle cx={head[0]} cy={head[1]} r={(14 + 30 * ((frame % 30) / 30)) * k} fill="none" stroke={RED}
                  strokeWidth={2.5 * k} opacity={1 - (frame % 30) / 30} />
                <circle cx={head[0]} cy={head[1]} r={12 * k} fill={RED} stroke="#fff" strokeWidth={3 * k} />
              </g>
            )}
          </g>
        </svg>
        {P.map((p, i) => {
          const q = interpolate(headLen - pointLen[i], [-1, total * 0.03 + 1], [0, 1], clamp);
          const si = Math.min(samples.length - 1, i * S);
          const t = tangentAt(samples, si);
          let nx = -t[1], ny = t[0];
          if (ny > 0) {
            nx = -nx;
            ny = -ny;
          }
          const off = radius(pointLen[i]) + 30 * k;
          const lx = p[0] + nx * off, ly = p[1] + ny * off;
          const toRight = nx >= -0.15;
          const text = labelOf(i);
          if (!text) return null;
          return (
            <div key={`t${i}`} style={{ position: "absolute", left: toRight ? lx : lx - 440 * k, top: ly - 18 * k, width: 440 * k,
              textAlign: toRight ? "left" : "right", overflow: "hidden", paddingBottom: 4 * k }}>
              <span style={{ display: "inline-block", transform: `translateY(${(1 - q) * 110 - labelsOut * 110}%)`,
                fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.1em", whiteSpace: "nowrap",
                color: i === P.length - 1 ? "#fff" : "rgba(255,255,255,.86)", textShadow: "0 2px 10px rgba(0,0,0,.95)" }}>
                {text}
              </span>
            </div>
          );
        })}
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: bgA, boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.62)` }} />
      <div style={{ position: "absolute", left: 90 * k, top: 76 * k, display: "flex", flexDirection: "column", gap: 6 * k }}>
        <Letters text={kicker} at={4} step={0.5} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k,
          letterSpacing: "0.3em", color: acc, textShadow: "0 2px 10px rgba(0,0,0,.6)" }} />
        {name ? fitLines(name, 24, 2).map((ln, i) => (
          <Letters key={i} text={ln} at={8 + i * 5} step={0.8} outAt={outAt + 1 + i} style={{ fontFamily: DISPLAY,
            fontSize: 82 * k, lineHeight: 0.98, color: "#fff", letterSpacing: "0.03em", textShadow: "0 6px 24px rgba(0,0,0,.5)" }} />
        )) : null}
      </div>
      {storm && cat ? (
        <div style={{ position: "absolute", right: 90 * k, top: 76 * k, width: 230 * k, boxSizing: "border-box",
          padding: `${16 * k}px 0 ${10 * k}px`, borderRadius: 18 * k, display: "flex", flexDirection: "column",
          alignItems: "center", background: "rgba(10,14,20,.72)", border: `${2 * k}px solid ${rgba(RED, 0.85)}`,
          boxShadow: `0 0 ${(24 + 14 * pulse) * k}px ${rgba(RED, 0.35)}`, transform: `scale(${Math.max(0, badge)})` }}>
          <Rise at={20}>
            <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 22 * k, letterSpacing: "0.3em",
              color: "rgba(255,255,255,.75)" }}>CATEGORY</span>
          </Rise>
          <Rise at={22} outAt={outAt + 1}>
            <Odometer value={cat} at={24} frames={26} size={104 * k} color={RED} />
          </Rise>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 90 * k, bottom: 80 * k, display: "flex", flexDirection: "column", gap: 10 * k }}>
        <Rise at={30}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
            <span style={{ display: "inline-block", width: 40 * k, height: 20 * k, borderRadius: 10 * k, boxSizing: "border-box",
              background: "rgba(255,255,255,.16)", border: `${2 * k}px solid rgba(255,255,255,.75)` }} />
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.16em",
              color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{storm ? "POTENTIAL TRACK AREA" : "POTENTIAL IMPACT AREA"}</span>
          </div>
        </Rise>
        <Rise at={34}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
            <svg width={40 * k} height={8 * k} style={{ display: "block" }}>
              <line x1={2 * k} x2={38 * k} y1={4 * k} y2={4 * k} stroke="#fff" strokeWidth={3 * k}
                strokeDasharray={`${9 * k} ${6 * k}`} strokeLinecap="round" />
            </svg>
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.16em",
              color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{storm ? "FORECAST TRACK" : "PROJECTED PATH"}</span>
          </div>
        </Rise>
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "al-breaking-flag": BreakingFlag,
  "al-alert-toast": AlertToast,
  "al-siren-badge": SirenBadge,
  "al-warning-polygon": WarningPolygon,
  "al-severity-meter": SeverityMeter,
  "al-countdown-timer": CountdownTimer,
  "al-live-tag": LiveTag,
  "al-emergency-stamp": EmergencyStamp,
  "al-slim-ticker": SlimTicker,
  "al-storm-track": StormTrack,
};
