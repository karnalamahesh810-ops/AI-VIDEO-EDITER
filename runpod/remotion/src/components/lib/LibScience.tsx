import React from "react";
import { AbsoluteFill, Easing, interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, Scrim, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";

/**
 * Science & explainer diagrams (family "sc-"): ten water and climate
 * explainers in the pro house style. Condensed caps rise out of masks and
 * leave the same way, every diagram lands inside 0.3-0.7 s on expo /
 * back-out curves, holds with one live detail (flowing water, orbiting
 * electrons, a drifting cloud, ripples) and exits in the last ~12 frames.
 * Water is the house cyan family, red only for loss / danger, green only for
 * a rise, the accent for the idea the narration is on.
 *
 *   sc-water-cycle       own backdrop: a line-art landscape; evaporation,
 *                        condensation, precipitation and collection arrows
 *                        draw in turn, then a droplet keeps circling the loop
 *   sc-aquifer-drop      own backdrop: the ground is cut open layer by layer;
 *                        the water table sinks by the value while a cone of
 *                        depression forms round the pumping well
 *   sc-pipe-flow         own backdrop: a blueprint pipeline; the valve wheel
 *                        spins open, water floods the pipe past its stations,
 *                        a turbine meter spins up and reads the flow rate
 *   sc-molecule-orbit    a ball-and-stick molecule (H2O, CO2, CH4...) swings
 *                        into 3D, bonds snap on, electrons orbit, the formula
 *                        rises glyph by glyph with real subscripts
 *   sc-cause-chain       hexagon nodes linked by arrows: a spark runs down the
 *                        chain and ignites each consequence in turn
 *   sc-reservoir-levels  valley-shaped basins fill to their share of capacity
 *                        with a decaying slosh; the low ones read in red
 *   sc-warming-stripes   own backdrop: climate stripes grow up behind a
 *                        scanning year playhead, the warming figure rolls in
 *   sc-rain-gauges       graduated glass gauges: drops fall into the funnels,
 *                        the columns rise, each reading riding its meniscus
 *   sc-dam-level         own backdrop: a dam in section; the reservoir falls to
 *                        the level, leaving the bathtub ring, and the intakes
 *                        flip to EXPOSED as the water passes them
 *   sc-heat-sun          (tag) a sun top right: rays turning, heat rings
 *                        rippling out gold to red, the temperature rolling
 *
 * Diagrams are drawn in a 1920x1080 viewBox (so their strokes scale with the
 * frame); HTML text is placed with k. Deterministic: every "random" value is
 * rnd(index), never Math.random or the clock.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];
type V3 = [number, number, number];
type Row = { label: string; text: string; value: number; suffix: string; prefix: string };
type Num = { label: string; value: number; text?: string; suffix?: string; prefix?: string };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
const FULL = "0 0 1920 1080";

// ------------------------------------------------------------------ data helpers
/** A number from a number or a numeric string ("27%", "1,234", "−8"). */
const toNum = (raw: unknown): number => {
  if (typeof raw === "number") return raw;
  if (typeof raw === "string") {
    const m = /-?\d[\d,]*(?:\.\d+)?|-?\.\d+/.exec(raw.replace(/−/g, "-"));
    return m ? Number(m[0].replace(/,/g, "")) : NaN;
  }
  return NaN;
};
const str = (v: unknown): string =>
  typeof v === "string" ? v.trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const cap = (s?: string) => (s || "").toUpperCase();
const fmt = (v: number) => formatValue(v).text;
/** The unit as drawn after a number: "%" and degrees tight, a word after a space. */
const tail = (s?: string) => {
  const u = (s || "").trim();
  return !u ? "" : u === "%" || u.startsWith("°") ? u : ` ${u}`;
};

/** Items with a label or a text (their value NaN when they carry none), at most `max`. */
const rows = (items: OverlayItem[] | undefined, max: number): Row[] => {
  const out: Row[] = [];
  if (!Array.isArray(items)) return out;
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const ex = it as OverlayItem & { suffix?: unknown; prefix?: unknown };
    const label = str(it.label);
    const text = str(it.text);
    const raw: unknown = (it as { value?: unknown }).value;
    const value = raw === null || raw === undefined || raw === "" ? NaN : toNum(raw);
    if (!label && !text && !Number.isFinite(value)) continue;
    out.push({ label: label || text, text: label ? text : "", value, suffix: str(ex.suffix), prefix: str(ex.prefix) });
    if (out.length >= max) break;
  }
  return out;
};
/** The items that carry a finite value, at most `max` of them. */
const nums = (items: OverlayItem[] | undefined, max: number): Num[] =>
  rows(items, 1000).filter((r) => Number.isFinite(r.value)).slice(0, max).map((r) => ({
    label: r.label, value: r.value, text: r.text || undefined, suffix: r.suffix || undefined, prefix: r.prefix || undefined,
  }));
/** The item the narration points at (overlay.highlight), or -1. */
const pickHot = (labels: string[], h?: string): number => {
  const q = (h || "").trim().toLowerCase();
  if (!q) return -1;
  const exact = labels.findIndex((l) => l.toLowerCase() === q);
  if (exact >= 0) return exact;
  return labels.findIndex((l) => l.length > 0 && (l.toLowerCase().includes(q) || q.includes(l.toLowerCase())));
};
/** A seeded 0..1: a pure function of the index. */
const rnd = (i: number) => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};
/** Lines of about `chars` characters, at most `max`, the last one ellipsed when cut. */
const wrap = (text: string, chars: number, max: number): string[] => {
  const all = lines(text, chars);
  const out = all.slice(0, max);
  if (all.length > max && out.length) out[out.length - 1] = `${out[out.length - 1].replace(/[.,;:!?]$/, "")}…`;
  return out;
};
const niceStep = (raw: number) => {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw - 1e-12) return m * p;
  return 10 * p;
};
/** A round axis around [lo, hi] with about `count` steps. */
const niceScale = (lo: number, hi: number, count: number) => {
  let a = Math.min(lo, hi), b = Math.max(lo, hi);
  if (!Number.isFinite(a) || !Number.isFinite(b)) { a = 0; b = 1; }
  if (b - a < 1e-9) b = a + (Math.abs(a) || 1);
  const step = niceStep((b - a) / count);
  const min = Math.floor(a / step + 1e-9) * step;
  let max = Math.ceil(b / step - 1e-9) * step;
  if (max <= min) max = min + step;
  const ticks: number[] = [];
  for (let i = 0; i <= 24; i++) {
    const t = min + i * step;
    if (t > max + step * 1e-6) break;
    ticks.push(Math.round(t * 1e6) / 1e6);
  }
  return { min, max, step, ticks };
};
const fmtTick = (v: number, step: number) => {
  const d = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};
/** interpolateColors that never throws on an odd accent string. */
const colorAt = (q: number, stops: number[], colors: string[]): string => {
  try {
    return interpolateColors(q, stops, colors);
  } catch {
    return colors[colors.length - 1];
  }
};
const mixC = (a: string, b: string, q: number) => colorAt(q, [0, 1], [a, b]);

// ------------------------------------------------------------------ geometry helpers
type Poly = { pts: Pt[]; cum: number[]; len: number };
const poly = (pts: Pt[]): Poly => {
  const cum: number[] = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  return { pts, cum, len: cum[cum.length - 1] || 1 };
};
/** The point at share u (0..1) of a polyline's length, with the heading there. */
const along = (p: Poly, u: number): { x: number; y: number; a: number } => {
  const s = Math.max(0, Math.min(1, u)) * p.len;
  let i = 1;
  while (i < p.pts.length - 1 && p.cum[i] < s) i++;
  const s0 = p.cum[i - 1], s1 = p.cum[i];
  const q = s1 > s0 ? (s - s0) / (s1 - s0) : 0;
  const [x0, y0] = p.pts[i - 1];
  const [x1, y1] = p.pts[i];
  return { x: x0 + (x1 - x0) * q, y: y0 + (y1 - y0) * q, a: Math.atan2(y1 - y0, x1 - x0) };
};
const dOf = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
const closed = (pts: Pt[]) => `${dOf(pts)} Z`;
const bez = (p0: Pt, p1: Pt, p2: Pt, p3: Pt, n = 36): Pt[] => {
  const out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t;
    out.push([
      u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
      u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    ]);
  }
  return out;
};
/** A filled arrowhead with its tip at (x, y), pointing along angle a. */
const headD = (x: number, y: number, a: number, size: number) => {
  const bx = x - Math.cos(a) * size, by = y - Math.sin(a) * size;
  const nx = -Math.sin(a) * size * 0.6, ny = Math.cos(a) * size * 0.6;
  return `M${x.toFixed(1)} ${y.toFixed(1)} L${(bx + nx).toFixed(1)} ${(by + ny).toFixed(1)} ` +
    `L${(bx - nx).toFixed(1)} ${(by - ny).toFixed(1)} Z`;
};
/** A falling drop centred on (x, y). */
const dropD = (x0: number, y0: number) => {
  const x = Number(x0.toFixed(1)), y = Number(y0.toFixed(1));
  return `M${x} ${y - 13} C${x + 5} ${y - 4} ${x + 8} ${y + 2} ${x} ${y + 9} C${x - 8} ${y + 2} ${x - 5} ${y - 4} ${x} ${y - 13} Z`;
};

// ------------------------------------------------------------------ timing
/** 0 while the look holds, 1 once it has gone: the last ~12 frames, accelerating. */
const useExit = (len = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - len - 1, len, expoIn);
};
/** An own backdrop: always there as a full-screen scene, eased in and out over footage. */
const useBackdrop = (ov: Overlay): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  if (ov.fullFrame) return 1;
  return ramp(frame, 0, 8) * (1 - ramp(frame, durationInFrames - 10, 9, inOut));
};

// ------------------------------------------------------------------ shared pieces
/** A line rising out of its mask at `at`, and rising away out of it at the end. */
const Rise: React.FC<{ at: number; frames?: number; out?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 14, out = 0, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, durationInFrames - 14 + Math.max(0, Math.min(4, out)), 9, expoIn);
    const y = (1 - pin) * 112 - pout * 112;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        <div style={{ transform: `translateY(${y}%)`, opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** Kicker + one or two title lines, letters rising in and out, an accent rule that retracts. */
const TitleBlock: React.FC<{ kicker?: string; title?: string; accent: string; size?: number; chars?: number; max?: number;
  at?: number; center?: boolean }> = ({ kicker, title, accent, size = 58, chars = 26, max = 2, at = 0, center }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const ex = useExit();
  const ls = wrap(cap(title), chars, max);
  const kk = cap(kicker).trim();
  if (!ls.length && !kk) return null;
  const align = center ? "center" : "left";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: center ? "center" : "flex-start", gap: 4 * k }}>
      {kk ? (
        <LetterLine text={kk} at={at} step={0.5} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 25 * k,
          letterSpacing: "0.26em", color: accent, textAlign: align, textShadow: "0 2px 12px rgba(0,0,0,.6)" }} />
      ) : null}
      {ls.map((ln, i) => (
        <LetterLine key={i} text={ln} at={at + 3 + i * 4} step={0.6} style={{ fontFamily: DISPLAY, fontSize: size * k,
          lineHeight: 1, color: "#fff", letterSpacing: "0.03em", textAlign: align, textShadow: "0 6px 26px rgba(0,0,0,.55)" }} />
      ))}
      <div style={{ width: `${ramp(frame, at + 8, 16) * (1 - ex) * 110 * k}px`, height: 5 * k, background: accent,
        marginTop: 8 * k }} />
    </div>
  );
};

/** A data card's heading: the house Heading, or kicker + two lines when it runs long. */
const CardTitle: React.FC<{ text?: string; kicker?: string; accent: string; size?: number; max?: number }> =
  ({ text, kicker, accent, size = 54, max = 2 }) => {
    const tt = (text || "").trim();
    const kk = (kicker || "").trim();
    if (!tt && !kk) return null;
    if (!kk && tt.length <= 40) return <Heading text={tt} accent={accent} size={size} center />;
    return <TitleBlock kicker={kk} title={tt} accent={accent} size={size} chars={36} max={max} center />;
  };

// ================================================================== 1. water cycle
const STAGES = ["Evaporation", "Condensation", "Precipitation", "Collection"];
const WC_BACK: Pt[] = [[0, 735], [0, 560], [90, 520], [200, 560], [330, 450], [470, 520], [600, 470], [740, 560],
  [880, 640], [1000, 735]];
const WC_FRONT: Pt[] = [[0, 735], [0, 640], [150, 600], [300, 500], [420, 420], [540, 500], [640, 470], [780, 580],
  [920, 660], [1080, 735]];
const WC_SNOW: Pt[][] = [
  [[378, 448], [420, 420], [462, 448], [449, 445], [437, 457], [423, 446], [409, 458], [394, 447]],
  [[610, 479], [640, 470], [665, 490], [654, 487], [645, 495], [634, 484], [621, 490]],
];
const WC_PUFFS: [number, number, number][] = [[-120, 12, 58], [-35, -30, 82], [78, -4, 68], [160, 26, 44], [-190, 36, 30]];
/** Where each stage's label sits (1080p): the anchor x, the top y, and which edge x is. */
const WC_LABELS: { x: number; y: number; align: "left" | "right" | "center" }[] = [
  { x: 1830, y: 560, align: "right" },
  { x: 1190, y: 150, align: "center" },
  { x: 420, y: 296, align: "right" },
  { x: 890, y: 808, align: "center" },
];

/**
 * The water cycle on its own designed landscape: mountains rise, the sea line
 * draws, then the four stages arrive in turn (vapour arrows rising off the sea,
 * an arc carrying it to the cloud as the cloud puffs out, rain falling on the
 * peaks, the river and an arrow running back to the sea). Once the loop is
 * complete two glowing droplets keep travelling round it. items[0..3] rename
 * the stages (and show a value under each when they carry one).
 */
const WaterCycle: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const t = frame / fps;
  const id = `scwc${overlay.startFrame}`;
  const its = rows(overlay.items, 4);
  const names = STAGES.map((s, i) => cap((its[i] && its[i].label) || s));

  const evap = [1300, 1430, 1560].map((x0, j) => {
    const yEnd = j === 1 ? 440 : 474;
    const pts: Pt[] = [];
    for (let s = 0; s <= 24; s++) {
      const q = s / 24;
      pts.push([x0 + 11 * Math.sin(q * Math.PI * 3 + j * 1.3), 716 - (716 - yEnd) * q]);
    }
    return poly(pts);
  });
  const cond = poly(bez([1430, 404], [1420, 300], [1180, 222], [905, 262]));
  const prec = poly([[500, 390], [500, 548]]);
  const coll = poly(bez([600, 652], [720, 760], [980, 812], [1380, 772]));
  const loop = [evap[1], cond, prec, coll];
  const river = poly([...bez([560, 572], [610, 640], [700, 610], [760, 670], 20),
    ...bez([760, 670], [820, 730], [930, 748], [1086, 742], 24).slice(1)]);
  const riverD = dOf(river.pts);

  const T0 = Math.round(fps * 0.45);
  const step = Math.max(8, Math.min(Math.round(fps * 0.6), Math.floor((dur - T0 - 34) / 4)));
  const T = [0, 1, 2, 3].map((i) => T0 + i * step);
  const drawF = Math.max(10, Math.round(step * 1.3));
  const loopAt = T[3] + drawF;
  const period = Math.round(fps * 3.2);
  const loopOn = ramp(frame, loopAt, 10) * (1 - ex);
  const drift = interpolate(frame, [0, Math.max(1, dur)], [0, 24], clamp);
  const cloudAt = T[1] + Math.round(drawF * 0.5);
  const puff = (j: number) => ramp(frame, cloudAt + j * 2, 14, backOut) * (1 - ramp(frame, dur - 13 + j, 9, expoIn));
  const rainOn = ramp(frame, T[2], 8) * (1 - ex);
  const riverP = ramp(frame, T[3] - 4, drawF + 6, inOut);
  const flowOn = ramp(frame, T[3] + drawF, 10) * (1 - ex);
  const backIn = ramp(frame, 0, 24);
  const frontIn = ramp(frame, 3, 24);
  const sunIn = ramp(frame, 5, 22);
  const seaIn = ramp(frame, 2, 22, inOut);
  const CX = 640 + drift, CY = 300;

  const rain = Array.from({ length: 16 }, (_, i) => {
    const P = 16 + Math.round(rnd(i * 3 + 1) * 8);
    const u = ((frame + rnd(i * 5 + 2) * P) % P) / P;
    return { x: 548 + rnd(i * 7 + 3) * 262 + drift * 0.6, y: 374 + u * 206,
      o: (0.35 + 0.45 * rnd(i * 11 + 4)) * Math.max(0, Math.min(1, u * 6, (1 - u) * 5)) };
  });
  const shimmer = Array.from({ length: 9 }, (_, i) => {
    const y = 752 + rnd(i * 17 + 6) * 250;
    const x0 = 1110 + (y - 735) * 0.32;
    const span = 1900 - x0;
    return { x: x0 + ((rnd(i * 13 + 5) * span + frame * (0.25 + rnd(i + 9) * 0.35)) % span), y,
      w: 24 + rnd(i * 19 + 7) * 46, o: 0.1 + 0.2 * (0.5 + 0.5 * Math.sin(t * 2 + i)) };
  });
  const drops = [0, 2].map((off) => {
    const u = ((((frame - loopAt) / period) * 4 + off) % 4 + 4) % 4;
    const seg = Math.min(3, Math.floor(u));
    const local = u - seg;
    const fade = Math.max(0, Math.min(1, local / 0.1, (1 - local) / 0.1));
    return { head: along(loop[seg], local), trail: [1, 2, 3].map((j) => along(loop[seg], Math.max(0, local - j * 0.035))),
      o: loopOn * fade };
  });
  const vapor = evap.flatMap((p, j) => [0, 0.5].map((o) => along(p, (t * 0.42 + o + j * 0.21) % 1)));
  const vaporOn = ramp(frame, T[0] + drawF, 12) * (1 - ex);
  const ridge = WC_FRONT.slice(1, -1);

  return (
    <AbsoluteFill style={{ opacity: bg, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, #03070d 0%, #081524 52%, #0d2133 68%, #07111b 100%)" }} />
      <AbsoluteFill style={{ transform: `translateY(${ex * 36 * k}px) scale(${hold})`, transformOrigin: "50% 60%" }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice"
          style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#1a2839" /><stop offset="100%" stopColor="#0d1620" />
            </linearGradient>
            <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2b3b50" /><stop offset="100%" stopColor="#111a25" />
            </linearGradient>
            <linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#14608f" /><stop offset="45%" stopColor="#0b3656" />
              <stop offset="100%" stopColor="#051624" />
            </linearGradient>
            <linearGradient id={`${id}l`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#152131" /><stop offset="100%" stopColor="#080d14" />
            </linearGradient>
            <linearGradient id={`${id}c`} gradientUnits="userSpaceOnUse" x1={0} y1={CY - 112} x2={0} y2={CY + 62}>
              <stop offset="0%" stopColor="#ffffff" /><stop offset="100%" stopColor="#b3c2d2" />
            </linearGradient>
            <radialGradient id={`${id}g`} cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={accent} stopOpacity={0.5} /><stop offset="100%" stopColor={accent} stopOpacity={0} />
            </radialGradient>
          </defs>
          <g opacity={sunIn} transform={`translate(0 ${((1 - sunIn) * 60).toFixed(1)})`}>
            <circle cx={1660} cy={190} r={170 + 8 * Math.sin(t * 1.6)} fill={`url(#${id}g)`} />
            <circle cx={1660} cy={190} r={54} fill={accent} />
            <circle cx={1660} cy={190} r={54} fill="none" stroke="#fff" strokeOpacity={0.35} strokeWidth={3} />
          </g>
          <path d={closed(WC_BACK)} fill={`url(#${id}b)`} transform={`translate(0 ${((1 - backIn) * 90).toFixed(1)})`} />
          <g transform={`translate(0 ${((1 - frontIn) * 70).toFixed(1)})`}>
            <path d={closed(WC_FRONT)} fill={`url(#${id}f)`} />
            <path d={dOf(ridge)} fill="none" stroke="#fff" strokeOpacity={0.14} strokeWidth={2} strokeLinejoin="round" />
            {WC_SNOW.map((s, i) => <path key={i} d={closed(s)} fill="#dfe8f1" opacity={0.85} />)}
          </g>
          <path d="M0 735 L1080 735 L1190 1080 L0 1080 Z" fill={`url(#${id}l)`} />
          <path d="M1080 735 L1920 735 L1920 1080 L1190 1080 Z" fill={`url(#${id}s)`} />
          <line x1={1080} x2={1080 + 840 * seaIn} y1={735} y2={735} stroke={CYAN} strokeOpacity={0.6} strokeWidth={2.5} />
          {shimmer.map((s, i) => (
            <line key={i} x1={s.x} x2={s.x + s.w} y1={s.y} y2={s.y} stroke="#bfe9ff" strokeOpacity={s.o * seaIn}
              strokeWidth={2} strokeLinecap="round" />
          ))}
          <g opacity={riverP > 0.002 ? 1 : 0}>
            <path d={riverD} fill="none" stroke={CYAN} strokeOpacity={0.2} strokeWidth={15} strokeLinecap="round"
              pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - riverP} />
            <path d={riverD} fill="none" stroke={CYAN} strokeOpacity={0.9} strokeWidth={5} strokeLinecap="round"
              pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - riverP} />
          </g>
          <path d={riverD} fill="none" stroke="#fff" strokeOpacity={0.55 * flowOn} strokeWidth={2.5} strokeLinecap="round"
            strokeDasharray="8 26" strokeDashoffset={-frame * 2.2} />
          <g opacity={rainOn}>
            {rain.map((r, i) => (
              <line key={i} x1={r.x + 5} y1={r.y - 24} x2={r.x} y2={r.y} stroke="#cdeeff" strokeOpacity={r.o}
                strokeWidth={2.2} strokeLinecap="round" />
            ))}
          </g>
          {WC_PUFFS.map(([dx, dy, r], j) => {
            const p = puff(j);
            return p > 0.01 ? <circle key={j} cx={CX + dx} cy={CY + dy} r={r * p} fill={`url(#${id}c)`} /> : null;
          })}
          {puff(2) > 0.01 ? (
            <rect x={CX - 205 * puff(2)} y={CY + 14} width={410 * puff(2)} height={48} rx={24} fill={`url(#${id}c)`} />
          ) : null}
          {evap.map((p, j) => {
            const q = ramp(frame, T[0] + j * 3, drawF, inOut) * (1 - ex);
            const hd = along(p, q);
            const main = j === 1;
            return (
              <g key={j} opacity={q > 0.02 ? 1 : 0}>
                <path d={dOf(p.pts)} fill="none" stroke="#eaf3fa" strokeOpacity={main ? 0.95 : 0.6} strokeWidth={main ? 4 : 3}
                  strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - q} />
                <path d={headD(hd.x, hd.y, hd.a, main ? 18 : 14)} fill="#eaf3fa" fillOpacity={main ? 0.95 : 0.6} />
              </g>
            );
          })}
          {[cond, prec, coll].map((p, i) => {
            const q = ramp(frame, T[i + 1], drawF, inOut) * (1 - ex);
            const hd = along(p, q);
            return (
              <g key={i} opacity={q > 0.02 ? 1 : 0}>
                <path d={dOf(p.pts)} fill="none" stroke="#eaf3fa" strokeOpacity={0.95} strokeWidth={4} strokeLinecap="round"
                  pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - q} />
                <path d={headD(hd.x, hd.y, hd.a, 18)} fill="#eaf3fa" />
              </g>
            );
          })}
          {vapor.map((v, i) => <circle key={i} cx={v.x} cy={v.y} r={3.2} fill="#dff4ff" opacity={vaporOn * 0.7} />)}
          {drops.map((d, i) => (
            <g key={i} opacity={d.o}>
              {d.trail.map((q, j) => <circle key={j} cx={q.x} cy={q.y} r={6 - j * 1.4} fill={CYAN} opacity={0.5 - j * 0.13} />)}
              <circle cx={d.head.x} cy={d.head.y} r={16} fill={CYAN} opacity={0.3} />
              <circle cx={d.head.x} cy={d.head.y} r={6.5} fill="#fff" />
            </g>
          ))}
        </svg>
        {WC_LABELS.map((l, i) => {
          const r = its[i];
          const hasV = Boolean(r) && Number.isFinite(r.value);
          const at = T[i] + 6;
          return (
            <div key={i} style={{ position: "absolute", left: l.x * k, top: l.y * k,
              transform: l.align === "right" ? "translateX(-100%)" : l.align === "center" ? "translateX(-50%)" : undefined,
              display: "flex", flexDirection: "column",
              alignItems: l.align === "right" ? "flex-end" : l.align === "center" ? "center" : "flex-start" }}>
              <Rise at={at}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 * k, whiteSpace: "nowrap" }}>
                  <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 19 * k, color: accent, letterSpacing: "0.08em" }}>
                    {`0${i + 1}`}</span>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, color: "#fff", letterSpacing: "0.08em",
                    textShadow: "0 3px 14px rgba(0,0,0,.65)" }}>{names[i]}</span>
                </div>
              </Rise>
              {hasV ? (
                <Rise at={at + 5} out={1}>
                  <Odometer value={r.value} at={at + 5} frames={Math.round(fps * 0.9)} size={40 * k} color="#fff"
                    prefix={r.prefix} suffix={tail(r.suffix || str(overlay.suffix))} suffixScale={0.5}
                    suffixColor="rgba(255,255,255,.72)" />
                </Rise>
              ) : null}
            </div>
          );
        })}
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 90 * k, top: 76 * k }}>
        <TitleBlock kicker={overlay.subtitle} title={overlay.text || "The water cycle"} accent={accent} size={60} chars={24} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. aquifer drop
/**
 * The ground in section. A bright cut line sweeps down and reveals the strata
 * (topsoil, clay, the aquifer's gravel, bedrock); the saturated aquifer glows
 * cyan below the water table (the hydrologist's ▽ on it). The table then sinks
 * by the value (label "up": rises), the lost band hatched red behind it, a
 * cone of depression deepening round the well while pumped water streams up
 * the casing; a dimension bracket measures the drop and the figure rolls
 * beside it. items[0] / items[1] name the old and new levels ("1950", "TODAY").
 */
const AquiferDrop: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const value = Math.abs(toNum(overlay.value));
  if (!Number.isFinite(value) || value === 0) return null;
  const t = frame / fps;
  const id = `scaq${overlay.startFrame}`;
  const dirWord = str(overlay.label).toLowerCase();
  const up = dirWord === "up";
  const col = up ? GREEN : RED;
  const suffix = str(overlay.suffix);
  const caption = dirWord === "up" || dirWord === "down" || !dirWord ? (up ? "Water table rise" : "Water table drop")
    : str(overlay.label);
  const its = rows(overlay.items, 2);
  const thenL = cap((its[0] && its[0].label) || "Then");
  const nowL = cap((its[1] && its[1].label) || "Now");
  const sub = str(overlay.subtitle);
  const layerName = /aquifer/i.test(sub) && sub.length <= 28 ? cap(sub) : "AQUIFER";

  const SURF = 300;
  const XS: number[] = Array.from({ length: 50 }, (_, i) => -20 + i * 40);
  const wob = (x: number, base: number, a: number, f: number, ph: number) =>
    base + a * Math.sin(x / f + ph) + a * 0.45 * Math.sin(x / (f * 0.37) + ph * 1.7);
  const surf = (x: number) => wob(x, SURF, 5, 210, 0.4);
  const b1 = (x: number) => wob(x, 372, 6, 180, 1.1);
  const b2 = (x: number) => wob(x, 462, 8, 240, 2.3);
  const b3 = (x: number) => wob(x, 880, 10, 260, 0.7);
  const edge = (f: (x: number) => number) => XS.map((x, i) => `${i ? "L" : "M"}${x} ${f(x).toFixed(1)}`).join(" ");
  const back = (f: (x: number) => number) => XS.slice().reverse().map((x) => `L${x} ${f(x).toFixed(1)}`).join(" ");
  const band = (top: (x: number) => number, bot: (x: number) => number) => `${edge(top)} ${back(bot)} Z`;
  const floor = () => 1100;

  const Y_OLD = 548;
  const dropPx = interpolate(Math.log10(Math.max(1, value)), [0, 3], [120, 250], clamp);
  const startY = up ? Y_OLD + dropPx : Y_OLD;
  const endY = up ? Y_OLD : Y_OLD + dropPx;
  const dropAt = Math.round(fps * 0.85);
  const dropF = Math.round(Math.max(fps * 1.0, Math.min(fps * 1.7, dur * 0.4)));
  const g = ramp(frame, dropAt, dropF, inOut);
  const level = startY + (endY - startY) * g;
  const pump = ramp(frame, Math.round(fps * 0.5), Math.round(fps * 2.2), inOut) * (1 - ex);
  const WELL = 1150;
  const cone = (x: number) => 52 * pump * Math.exp(-Math.pow((x - WELL) / 170, 2));
  const table = (x: number) => level + cone(x) + 2.4 * Math.sin(x / 55 + t * 3.2);
  const XT: number[] = Array.from({ length: 99 }, (_, i) => -20 + i * 20);
  const tableD = XT.map((x, i) => `${i ? "L" : "M"}${x} ${table(x).toFixed(1)}`).join(" ");
  const satD = `${tableD} ${back(b3)} Z`;
  const lostD = `M-20 ${startY} H1940 ${XT.slice().reverse().map((x) => `L${x} ${table(x).toFixed(1)}`).join(" ")} Z`;
  const cut = ramp(frame, 2, 22, expoOut);
  const cutY = SURF - 12 + (1100 - SURF) * cut * (1 - ex);
  const cutOn = (cut > 0.01 && cut < 0.985) || (ex > 0.01 && ex < 0.99);
  const wellBot = Math.min(858, Math.max(startY, endY) + 118);
  const atWell = Math.max(SURF, table(WELL));
  const oldOn = ramp(frame, dropAt, 10);
  const nowOn = interpolate(g, [0.12, 0.3], [0, 1], clamp);
  const BX = 1480;
  const yA = Math.min(startY, level), yB = Math.max(startY, level);
  const midY = (startY + endY) / 2;
  const numText = fmt(value);
  const numSize = numText.length <= 3 ? 120 : numText.length <= 5 ? 100 : 84;
  const crops = Array.from({ length: 34 }, (_, i) => 150 + i * 24).map((x) => {
    const y = surf(x) - 1;
    const h = 12 + rnd(x) * 7;
    return `M${x} ${y.toFixed(1)} L${x - 5} ${(y - h * 0.75).toFixed(1)} M${x} ${y.toFixed(1)} L${x + 5} ` +
      `${(y - h * 0.75).toFixed(1)} M${x} ${y.toFixed(1)} L${x} ${(y - h).toFixed(1)}`;
  }).join(" ");
  const tri = (x: number, y: number) => `M${x - 15} ${y - 30} L${x + 15} ${y - 30} L${x} ${y - 5} Z`;
  const bars = (x: number, y: number) => `M${x - 12} ${y + 8} H${x + 12} M${x - 6} ${y + 15} H${x + 6}`;
  const layerLabel = (text: string, y: number) => (
    <text x={96} y={y} fontFamily={MONO} fontSize={17} letterSpacing={3.5} fill="#fff" fillOpacity={0.5}>{text}</text>
  );

  return (
    <AbsoluteFill style={{ opacity: bg, overflow: "hidden" }}>
      <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
        <defs>
          <linearGradient id={`${id}k`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#03060b" /><stop offset="100%" stopColor="#0d1a29" />
          </linearGradient>
          <linearGradient id={`${id}w`} gradientUnits="userSpaceOnUse" x1={0} y1={level} x2={0} y2={880}>
            <stop offset="0%" stopColor={CYAN} stopOpacity={0.46} /><stop offset="100%" stopColor="#1d6aa3" stopOpacity={0.3} />
          </linearGradient>
          <pattern id={`${id}p1`} width={14} height={14} patternUnits="userSpaceOnUse">
            <circle cx={3} cy={4} r={1.3} fill="#fff" fillOpacity={0.14} />
            <circle cx={10} cy={11} r={1} fill="#fff" fillOpacity={0.1} />
          </pattern>
          <pattern id={`${id}p2`} width={36} height={14} patternUnits="userSpaceOnUse">
            <line x1={2} x2={20} y1={5} y2={5} stroke="#fff" strokeOpacity={0.1} strokeWidth={2} />
            <line x1={20} x2={34} y1={12} y2={12} stroke="#fff" strokeOpacity={0.07} strokeWidth={2} />
          </pattern>
          <pattern id={`${id}p3`} width={30} height={26} patternUnits="userSpaceOnUse">
            <circle cx={7} cy={7} r={4.5} fill="none" stroke="#fff" strokeOpacity={0.13} strokeWidth={1.5} />
            <circle cx={21} cy={18} r={3} fill="none" stroke="#fff" strokeOpacity={0.11} strokeWidth={1.5} />
            <circle cx={24} cy={5} r={1.6} fill="#fff" fillOpacity={0.1} />
          </pattern>
          <pattern id={`${id}p4`} width={18} height={18} patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
            <line x1={0} y1={0} x2={0} y2={18} stroke="#fff" strokeOpacity={0.07} strokeWidth={3} />
          </pattern>
          <pattern id={`${id}h`} width={12} height={12} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1={0} y1={0} x2={0} y2={12} stroke={col} strokeOpacity={0.38} strokeWidth={3} />
          </pattern>
          <clipPath id={`${id}c`}><rect x={-40} y={0} width={2000} height={Math.max(0, cutY)} /></clipPath>
        </defs>
        <rect x={0} y={0} width={1920} height={SURF + 30} fill={`url(#${id}k)`} />
        <rect x={0} y={SURF - 10} width={1920} height={800} fill="#0a0b0e" />
        <path d={crops} fill="none" stroke="#6d7a58" strokeOpacity={0.85} strokeWidth={2} strokeLinecap="round" />
        <g clipPath={`url(#${id}c)`}>
          <path d={band(surf, b1)} fill="#2d241d" />
          <path d={band(surf, b1)} fill={`url(#${id}p1)`} />
          <path d={band(b1, b2)} fill="#3b3129" />
          <path d={band(b1, b2)} fill={`url(#${id}p2)`} />
          <path d={band(b2, b3)} fill="#433829" />
          <path d={band(b2, b3)} fill={`url(#${id}p3)`} />
          <path d={satD} fill={`url(#${id}w)`} />
          <path d={band(b3, floor)} fill="#16171b" />
          <path d={band(b3, floor)} fill={`url(#${id}p4)`} />
          {[b1, b2, b3].map((f, i) => (
            <path key={i} d={edge(f)} fill="none" stroke="#fff" strokeOpacity={0.12} strokeWidth={2} />
          ))}
          {!up ? <path d={lostD} fill={`url(#${id}h)`} opacity={interpolate(g, [0.03, 0.2], [0, 1], clamp)} /> : null}
          <g opacity={oldOn}>
            <line x1={40} x2={1880} y1={startY} y2={startY} stroke="#fff" strokeOpacity={0.6} strokeWidth={2.5}
              strokeDasharray="12 10" />
            <path d={tri(330, startY)} fill="none" stroke="#fff" strokeOpacity={0.75} strokeWidth={2.5} strokeLinejoin="round" />
            <path d={bars(330, startY)} stroke="#fff" strokeOpacity={0.75} strokeWidth={2.5} />
            <text x={356} y={startY - 12} fontFamily={MONO} fontWeight={700} fontSize={18} letterSpacing={3} fill="#fff"
              fillOpacity={0.75}>{thenL}</text>
          </g>
          <path d={tableD} fill="none" stroke={CYAN} strokeWidth={3} />
          <g opacity={nowOn}>
            <path d={tri(330, table(330))} fill={CYAN} />
            <path d={bars(330, table(330))} stroke={CYAN} strokeWidth={2.5} />
            <text x={356} y={table(330) - 12} fontFamily={MONO} fontWeight={700} fontSize={18} letterSpacing={3}
              fill={CYAN}>{nowL}</text>
          </g>
          <line x1={WELL} x2={WELL} y1={SURF - 2} y2={wellBot} stroke="#8995a2" strokeWidth={18} />
          <line x1={WELL} x2={WELL} y1={SURF - 2} y2={wellBot} stroke="#0a0f14" strokeWidth={9} />
          <line x1={WELL} x2={WELL} y1={atWell} y2={wellBot} stroke={CYAN} strokeWidth={7} />
          <path d={`M${WELL} ${wellBot - 4} V${SURF}`} fill="none" stroke="#e8f7ff" strokeOpacity={0.85 * pump} strokeWidth={4}
            strokeDasharray="7 15" strokeDashoffset={-frame * 3.4} />
          {Array.from({ length: 6 }, (_, i) => (
            <line key={i} x1={WELL - 10} x2={WELL + 10} y1={wellBot - 12 - i * 11} y2={wellBot - 12 - i * 11} stroke="#0a0f14"
              strokeWidth={3} />
          ))}
          {layerLabel("TOPSOIL", 346)}
          {layerLabel("CLAY", 426)}
          {layerLabel(layerName, 508)}
          {layerLabel("BEDROCK", 962)}
          <g opacity={interpolate(g, [0.05, 0.2], [0, 1], clamp)}>
            <line x1={BX} x2={BX} y1={yA} y2={yB} stroke={col} strokeWidth={3} />
            <line x1={BX - 14} x2={BX + 14} y1={startY} y2={startY} stroke="#fff" strokeOpacity={0.7} strokeWidth={3} />
            <line x1={BX - 14} x2={BX + 14} y1={level} y2={level} stroke={col} strokeWidth={3} />
            <path d={headD(BX, level, up ? -Math.PI / 2 : Math.PI / 2, 14)} fill={col} />
          </g>
        </g>
        <path d={edge(surf)} fill="none" stroke="#fff" strokeOpacity={0.32} strokeWidth={2} />
        <line x1={WELL} x2={WELL + 160} y1={SURF - 8} y2={SURF - 8} stroke="#8995a2" strokeWidth={12} />
        <path d={`M${WELL} ${SURF} V${SURF - 8} H${WELL + 160}`} fill="none" stroke="#e8f7ff" strokeOpacity={0.85 * pump}
          strokeWidth={4} strokeDasharray="7 15" strokeDashoffset={-frame * 3.4} />
        <path d={`M${WELL - 46} ${SURF - 50} L${WELL} ${SURF - 72} L${WELL + 46} ${SURF - 50} Z`} fill="#1c242d" stroke="#6c7a88"
          strokeWidth={2} strokeLinejoin="round" />
        <rect x={WELL - 40} y={SURF - 52} width={80} height={48} rx={3} fill="#26303b" stroke="#6c7a88" strokeWidth={2} />
        {cutOn ? (
          <g>
            <line x1={0} x2={1920} y1={cutY} y2={cutY} stroke={CYAN} strokeOpacity={0.18} strokeWidth={16} />
            <line x1={0} x2={1920} y1={cutY} y2={cutY} stroke="#eafaff" strokeOpacity={0.9} strokeWidth={2.5} />
          </g>
        ) : null}
      </svg>
      <div style={{ position: "absolute", left: 1522 * k, top: (midY - 70) * k, display: "flex", flexDirection: "column",
        gap: 6 * k }}>
        <Rise at={dropAt - 2} frames={12}>
          <Odometer value={value} at={dropAt} frames={dropF} size={numSize * k} color="#fff" prefix={up ? "+" : "−"}
            suffix={tail(suffix)} suffixScale={0.4} suffixColor={col} />
        </Rise>
        <Rise at={dropAt + 10}>
          <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.14em",
            color: "#fff", whiteSpace: "nowrap", textShadow: "0 3px 12px rgba(0,0,0,.7)" }}>{cap(caption)}</span>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: 90 * k, top: 70 * k }}>
        <TitleBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} size={56} chars={30} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. pipe flow
type Seg =
  | { kind: "L"; x0: number; y0: number; x1: number; y1: number; len: number }
  | { kind: "A"; cx: number; cy: number; r: number; a0: number; da: number; len: number; x1: number; y1: number; sweep: number };

/** An orthogonal polyline with its corners rounded to radius r, as straight and quarter-arc segments. */
const route = (pts: Pt[], r: number): Seg[] => {
  const out: Seg[] = [];
  let cur: Pt = pts[0];
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i], prev = pts[i - 1];
    const lin = Math.hypot(p[0] - prev[0], p[1] - prev[1]) || 1;
    const din: Pt = [(p[0] - prev[0]) / lin, (p[1] - prev[1]) / lin];
    if (i < pts.length - 1) {
      const nx = pts[i + 1];
      const lout = Math.hypot(nx[0] - p[0], nx[1] - p[1]) || 1;
      const dout: Pt = [(nx[0] - p[0]) / lout, (nx[1] - p[1]) / lout];
      const s: Pt = [p[0] - din[0] * r, p[1] - din[1] * r];
      const e: Pt = [p[0] + dout[0] * r, p[1] + dout[1] * r];
      out.push({ kind: "L", x0: cur[0], y0: cur[1], x1: s[0], y1: s[1], len: Math.hypot(s[0] - cur[0], s[1] - cur[1]) });
      const cx = s[0] + dout[0] * r, cy = s[1] + dout[1] * r;
      const cross = din[0] * dout[1] - din[1] * dout[0];
      out.push({ kind: "A", cx, cy, r, a0: Math.atan2(s[1] - cy, s[0] - cx), da: cross > 0 ? Math.PI / 2 : -Math.PI / 2,
        len: (Math.PI / 2) * r, x1: e[0], y1: e[1], sweep: cross > 0 ? 1 : 0 });
      cur = e;
    } else {
      out.push({ kind: "L", x0: cur[0], y0: cur[1], x1: p[0], y1: p[1], len: Math.hypot(p[0] - cur[0], p[1] - cur[1]) });
    }
  }
  return out;
};
const routeD = (segs: Seg[]) => segs.map((s, i) => (s.kind === "L"
  ? `${i === 0 ? `M${s.x0} ${s.y0} ` : ""}L${s.x1.toFixed(1)} ${s.y1.toFixed(1)}`
  : `A${s.r} ${s.r} 0 0 ${s.sweep} ${s.x1.toFixed(1)} ${s.y1.toFixed(1)}`)).join(" ");
/** The point `dist` along the route, with the heading of the pipe there. */
const routeAt = (segs: Seg[], dist: number): { x: number; y: number; a: number } => {
  let rest = Math.max(0, dist);
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (rest <= s.len || i === segs.length - 1) {
      const q = s.len > 0 ? Math.min(1, rest / s.len) : 0;
      if (s.kind === "L") return { x: s.x0 + (s.x1 - s.x0) * q, y: s.y0 + (s.y1 - s.y0) * q, a: Math.atan2(s.y1 - s.y0, s.x1 - s.x0) };
      const ang = s.a0 + s.da * q;
      return { x: s.cx + s.r * Math.cos(ang), y: s.cy + s.r * Math.sin(ang), a: ang + (s.da > 0 ? Math.PI / 2 : -Math.PI / 2) };
    }
    rest -= s.len;
  }
  return { x: 0, y: 0, a: 0 };
};

const PIPE = route([[-60, 430], [560, 430], [560, 730], [1360, 730], [1360, 500], [1980, 500]], 80);
const PIPE_D = routeD(PIPE);
const PIPE_L = PIPE.reduce((a, s) => a + s.len, 0);
const pipeS = (seg: number, off: number) => PIPE.slice(0, seg).reduce((a, s) => a + s.len, 0) + off;
const PIPE_METER = pipeS(4, 320);
const PIPE_FLANGES: { x: number; y: number; h: boolean }[] = [];
PIPE.forEach((s, i) => {
  if (s.kind !== "A") return;
  const prev = PIPE[i - 1], next = PIPE[i + 1];
  if (prev && prev.kind === "L") PIPE_FLANGES.push({ x: prev.x1, y: prev.y1, h: Math.abs(prev.x1 - prev.x0) > Math.abs(prev.y1 - prev.y0) });
  if (next && next.kind === "L") PIPE_FLANGES.push({ x: next.x0, y: next.y0, h: Math.abs(next.x1 - next.x0) > Math.abs(next.y1 - next.y0) });
});
/** Station slots along the pipe: where the marker sits, its leader, and where its label goes. */
const PIPE_ST: { s: number; lead: [number, number, number, number]; box: (k: number) => React.CSSProperties }[] = [
  { s: pipeS(0, 210), lead: [150, 413, 150, 392],
    box: (k) => ({ left: 110 * k, bottom: (1080 - 386) * k, alignItems: "flex-start" }) },
  { s: pipeS(2, 80), lead: [544, 590, 520, 590],
    box: (k) => ({ left: 512 * k, top: 590 * k, transform: "translate(-100%, -50%)", alignItems: "flex-end" }) },
  { s: pipeS(6, 35), lead: [1376, 615, 1400, 615],
    box: (k) => ({ left: 1408 * k, top: 615 * k, transform: "translateY(-50%)", alignItems: "flex-start" }) },
  { s: pipeS(8, 250), lead: [1690, 484, 1690, 462],
    box: (k) => ({ left: 1690 * k, bottom: (1080 - 456) * k, transform: "translateX(-50%)", alignItems: "center" }) },
];
const PIPE_SLOTS: number[][] = [[], [3], [0, 3], [0, 2, 3], [0, 1, 2, 3]];

/**
 * A pipeline on a blueprint. The pipe draws on, the gate valve's wheel spins
 * it open and water floods the empty pipe from the left, a bright front
 * leading it; each station (items: label, text) lights with a ping as the
 * water reaches it. When the water reaches the inline turbine meter its rotor
 * spins up and the flow rate (value + suffix, label as caption) rolls above
 * it; streaks keep running through the pipe while it holds.
 */
const PipeFlow: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const value = toNum(overlay.value);
  const hasV = Number.isFinite(value);
  const stations = rows(overlay.items, 4);
  if (!hasV && stations.length < 2) return null;
  const suffix = str(overlay.suffix);
  const build = ramp(frame, 0, 18, inOut);
  const fit = ramp(frame, 8, 12);
  const valveAt = Math.round(fps * 0.3);
  const open = ramp(frame, valveAt, Math.round(fps * 0.55), inOut);
  const flowAt = Math.round(fps * 0.55);
  const flowF = Math.round(Math.max(fps * 1.1, Math.min(fps * 1.8, dur * 0.42)));
  const frontAt = (f: number) => PIPE_L * ramp(f, flowAt, flowF, inOut);
  const front = frontAt(frame);
  const reach = (s: number) => {
    for (let f = flowAt; f <= flowAt + flowF; f++) if (frontAt(f) >= s) return f;
    return flowAt + flowF;
  };
  const meterAt = reach(PIPE_METER);
  const spin = frame - meterAt;
  const rotor = spin <= 0 ? 0 : spin < 20 ? (16 * spin * spin) / 40 : 16 * (10 + spin - 20);
  const whirl = interpolate(spin, [0, 20], [0, 1], clamp);
  const slots = PIPE_SLOTS[Math.min(4, stations.length)];
  const head = routeAt(PIPE, front);
  const flowing = front > 1 && front < PIPE_L - 1;
  const grid = (frame * 0.35) % 40;
  const readAt = meterAt + 4;
  const VX = 400, VY = 430, MX = 960, MY = 730;

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bg }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #0d2238 0%, #081627 55%, #030a14 100%)" }} />
        <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(83,200,255,.06) 1px, transparent 1px), " +
          "linear-gradient(90deg, rgba(83,200,255,.06) 1px, transparent 1px)", backgroundSize: `${40 * k}px ${40 * k}px`,
          backgroundPosition: `${grid * k}px ${grid * 0.5 * k}px` }} />
        <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(83,200,255,.1) 1px, transparent 1px), " +
          "linear-gradient(90deg, rgba(83,200,255,.1) 1px, transparent 1px)", backgroundSize: `${200 * k}px ${200 * k}px`,
          backgroundPosition: `${grid * k}px ${grid * 0.5 * k}px` }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.7)` }} />
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <rect x={40} y={40} width={1840} height={1000} fill="none" stroke={CYAN} strokeOpacity={0.16} strokeWidth={1.5} />
          <path d="M40 80 V40 H80 M1840 40 H1880 V80 M1880 1000 V1040 H1840 M80 1040 H40 V1000" fill="none" stroke={CYAN}
            strokeOpacity={0.5} strokeWidth={2.5} />
          <text x={1860} y={1026} textAnchor="end" fontFamily={MONO} fontSize={15} letterSpacing={3} fill={CYAN}
            fillOpacity={0.5}>SCHEMATIC · NOT TO SCALE</text>
        </svg>
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - ex, transform: `translateY(${ex * 24 * k}px) scale(${hold})` }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <g opacity={build > 0.002 ? 1 : 0}>
            <path d={PIPE_D} fill="none" stroke="#000" strokeOpacity={0.45} strokeWidth={66} transform="translate(0 12)"
              pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - build} />
            <path d={PIPE_D} fill="none" stroke="#46505c" strokeWidth={58} pathLength={1} strokeDasharray="1 1"
              strokeDashoffset={1 - build} />
            <path d={PIPE_D} fill="none" stroke="#6f7b88" strokeWidth={50} pathLength={1} strokeDasharray="1 1"
              strokeDashoffset={1 - build} />
            <path d={PIPE_D} fill="none" stroke="#07111b" strokeWidth={38} pathLength={1} strokeDasharray="1 1"
              strokeDashoffset={1 - build} />
          </g>
          {front > 0.5 ? (
            <g>
              <path d={PIPE_D} fill="none" stroke="#1b80c4" strokeWidth={32} />
              <path d={PIPE_D} fill="none" stroke="#8fe0ff" strokeOpacity={0.45} strokeWidth={9} />
              <path d={PIPE_D} fill="none" stroke="#fff" strokeOpacity={0.6} strokeWidth={4.5} strokeDasharray="12 34"
                strokeDashoffset={-frame * 7} />
              <path d={PIPE_D} fill="none" stroke="#07111b" strokeWidth={39}
                strokeDasharray={`0.01 ${Math.max(0.01, front).toFixed(1)} ${(PIPE_L + 40).toFixed(0)} 1`} />
            </g>
          ) : null}
          {flowing ? (
            <g>
              <circle cx={head.x} cy={head.y} r={30} fill={CYAN} opacity={0.28} />
              <circle cx={head.x} cy={head.y} r={9} fill="#fff" />
            </g>
          ) : null}
          <g opacity={fit}>
            {PIPE_FLANGES.map((f, i) => (
              <rect key={i} x={f.h ? f.x - 7 : f.x - 36} y={f.h ? f.y - 36 : f.y - 7} width={f.h ? 14 : 72} height={f.h ? 72 : 14}
                rx={2} fill="#7d8996" stroke="#20262d" strokeWidth={2} />
            ))}
            <path d={`M${VX - 32} ${VY - 32} L${VX - 32} ${VY + 32} L${VX} ${VY} Z M${VX + 32} ${VY - 32} L${VX + 32} ${VY + 32} ` +
              `L${VX} ${VY} Z`} fill="#0d1a27" stroke="#a9bccd" strokeWidth={3} strokeLinejoin="round" />
            <line x1={VX} x2={VX} y1={VY - 26} y2={VY - 70} stroke="#a9bccd" strokeWidth={4} />
            <g transform={`rotate(${(open * 540).toFixed(1)} ${VX} ${VY - 90})`}>
              <circle cx={VX} cy={VY - 90} r={22} fill="none" stroke="#a9bccd" strokeWidth={4} />
              <path d={`M${VX - 22} ${VY - 90} H${VX + 22} M${VX} ${VY - 112} V${VY - 68}`} stroke="#a9bccd" strokeWidth={3} />
            </g>
            <rect x={MX - 58} y={MY - 44} width={116} height={88} rx={18} fill="#132131" stroke="#a9bccd" strokeWidth={3} />
            <circle cx={MX} cy={MY} r={27} fill="#04101a" stroke={CYAN} strokeWidth={2.5} />
            <circle cx={MX} cy={MY} r={21} fill="none" stroke="#fff" strokeOpacity={0.2 * whirl} strokeWidth={6} />
            {[0, 1, 2].map((j) => {
              const a = ((rotor + j * 120) * Math.PI) / 180;
              return <line key={j} x1={MX} y1={MY} x2={MX + 21 * Math.cos(a)} y2={MY + 21 * Math.sin(a)} stroke="#e8f7ff"
                strokeWidth={4} strokeLinecap="round" />;
            })}
            <circle cx={MX} cy={MY} r={5} fill={CYAN} />
          </g>
          {hasV ? (
            <line x1={MX} x2={MX} y1={MY - 46} y2={MY - 68} stroke={CYAN} strokeWidth={2} opacity={ramp(frame, meterAt, 8)} />
          ) : null}
          {slots.map((si, j) => {
            const st = PIPE_ST[si];
            const p = routeAt(PIPE, st.s);
            const rf = reach(st.s);
            const lit = frame >= rf;
            const q = ramp(frame, rf, 18, expoOut);
            const [x1, y1, x2, y2] = st.lead;
            return (
              <g key={j} opacity={fit}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#a9bccd" strokeOpacity={0.8 * ramp(frame, rf, 8)} strokeWidth={2} />
                {lit && q < 0.99 ? <circle cx={p.x} cy={p.y} r={18 + 34 * q} fill="none" stroke={CYAN} strokeWidth={3} opacity={1 - q} /> : null}
                <circle cx={p.x} cy={p.y} r={15} fill={lit ? CYAN : "#0b1622"} stroke={lit ? "#e8f7ff" : "#a9bccd"} strokeWidth={3} />
              </g>
            );
          })}
        </svg>
        {slots.map((si, j) => {
          const st = PIPE_ST[si];
          const row = stations[j];
          const rf = reach(st.s);
          const detail = [row.text, Number.isFinite(row.value) ? `${row.prefix}${fmt(row.value)}${tail(row.suffix)}` : ""]
            .filter(Boolean).join(" · ");
          const ls = wrap(cap(row.label), 16, 2);
          return (
            <div key={j} style={{ position: "absolute", display: "flex", flexDirection: "column", ...st.box(k) }}>
              {ls.map((ln, i) => (
                <Rise key={i} at={rf + 2 + i * 2}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.06em",
                    lineHeight: 1.05, color: "#fff", whiteSpace: "nowrap", textShadow: "0 3px 12px rgba(0,0,0,.6)" }}>{ln}</span>
                </Rise>
              ))}
              {detail ? (
                <Rise at={rf + 6} out={1}>
                  <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 18 * k, letterSpacing: "0.14em",
                    color: "rgba(190,225,255,.75)", whiteSpace: "nowrap" }}>{cap(detail)}</span>
                </Rise>
              ) : null}
            </div>
          );
        })}
        {hasV ? (
          <div style={{ position: "absolute", left: MX * k, bottom: (1080 - 660) * k, transform: "translateX(-50%)",
            display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k }}>
            <Rise at={readAt}>
              <span style={{ display: "block", fontFamily: MONO, fontWeight: 700, fontSize: 20 * k, letterSpacing: "0.3em",
                color: CYAN, whiteSpace: "nowrap" }}>{cap(str(overlay.label) || "Flow rate")}</span>
            </Rise>
            <Rise at={readAt} frames={12}>
              <Odometer value={value} at={readAt} frames={Math.round(fps * 1.1)} size={100 * k} color="#fff"
                prefix={str(overlay.prefix)} suffix={tail(suffix)} suffixScale={0.34} suffixColor={accent} />
            </Rise>
          </div>
        ) : null}
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 90 * k, top: 76 * k }}>
        <TitleBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} size={56} chars={30} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. molecule orbit
const ELEMENTS = new Set(["H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
  "K", "Ca", "Ti", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "As", "Se", "Br", "Kr", "Sr", "Ag", "Cd", "Sn", "I", "Xe",
  "Cs", "Ba", "Pt", "Au", "Hg", "Pb", "Rn", "Ra", "U"]);
const SUBSCRIPTS = "₀₁₂₃₄₅₆₇₈₉";
/** Measured bond angles, shown only for the molecules they belong to. */
const BOND_ANGLES: Record<string, number> = { H2O: 104.5, H2S: 92.1, O3: 116.8, SO2: 119, NO2: 134.1, OF2: 103.1,
  CO2: 180, CH4: 109.5, NH3: 107.8, CCl4: 109.5, SiH4: 109.5 };

/** "H2O" or "H₂O" -> the normalised formula and its atoms; null when it is not a chemical formula. */
const parseFormula = (raw: string): { s: string; atoms: { el: string; n: number }[] } | null => {
  let s = "";
  for (const ch of raw.trim()) {
    const d = SUBSCRIPTS.indexOf(ch);
    s += d >= 0 ? String(d) : ch;
  }
  if (!s || s.length > 14 || !/^(?:[A-Z][a-z]?\d{0,2})+$/.test(s)) return null;
  const atoms: { el: string; n: number }[] = [];
  const re = /([A-Z][a-z]?)(\d{0,2})/g;
  let m: RegExpExecArray | null = re.exec(s);
  while (m) {
    const el = m[1];
    if (!ELEMENTS.has(el)) return null;
    const n = m[2] ? Number(m[2]) : 1;
    if (!(n >= 1)) return null;
    const same = atoms.find((a) => a.el === el);
    if (same) same.n += n;
    else atoms.push({ el, n });
    m = re.exec(s);
  }
  return atoms.length ? { s, atoms } : null;
};
const unit3 = (v: V3): V3 => {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};
/** Bond directions round the central atom: bent / linear pairs, a pyramid, a tetrahedron, an octahedron. */
const bondDirs = (n: number, bent: number | null): V3[] => {
  if (n <= 1) return [[1, 0, 0]];
  if (n === 2) {
    if (bent !== null && bent < 179) {
      const h = (bent / 2) * (Math.PI / 180);
      return [[Math.sin(h), Math.cos(h), 0], [-Math.sin(h), Math.cos(h), 0]];
    }
    return [[1, 0, 0], [-1, 0, 0]];
  }
  if (n === 3) {
    return [0, 1, 2].map((i): V3 => {
      const a = Math.PI / 2 + (i * 2 * Math.PI) / 3;
      return unit3([Math.cos(a) * 0.94, 0.34, Math.sin(a) * 0.94]);
    });
  }
  if (n === 4) {
    const q = 1 / Math.sqrt(3);
    return [[q, q, q], [q, -q, -q], [-q, q, -q], [-q, -q, q]];
  }
  const oct: V3[] = [[1, 0, 0], [-1, 0, 0], [0, -1, 0], [0, 1, 0], [0, 0, 1], [0, 0, -1]];
  return oct.slice(0, n);
};
const rot3 = (v: V3, yaw: number, pitch: number): V3 => {
  const x1 = v[0] * Math.cos(yaw) + v[2] * Math.sin(yaw);
  const z1 = -v[0] * Math.sin(yaw) + v[2] * Math.cos(yaw);
  return [x1, v[1] * Math.cos(pitch) - z1 * Math.sin(pitch), v[1] * Math.sin(pitch) + z1 * Math.cos(pitch)];
};

/** A formula whose glyphs rise out of a mask one by one (digits as subscripts) and leave the same way. */
const FormulaLine: React.FC<{ glyphs: { ch: string; sub: boolean }[]; at: number; size: number; color: string; subColor: string }> =
  ({ glyphs, at, size, color, subColor }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = durationInFrames - 14;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.1em", display: "flex", alignItems: "flex-start", fontFamily: DISPLAY,
        fontSize: size, lineHeight: 1, color, letterSpacing: "0.02em" }}>
        {glyphs.map((g, i) => {
          const pin = ramp(frame, at + i * 2, 14);
          const pout = ramp(frame, end + i * 0.6, 9, expoIn);
          const y = (1 - pin) * 110 - pout * 110;
          return (
            <span key={i} style={{ display: "inline-block", transform: `translateY(${y}%)`, opacity: pin < 0.02 || pout > 0.98 ? 0 : 1,
              fontSize: g.sub ? size * 0.5 : size, color: g.sub ? subColor : color, marginTop: g.sub ? size * 0.5 : 0 }}>{g.ch}</span>
          );
        })}
      </div>
    );
  };

/**
 * A molecule built from the formula in overlay.label (or one found in the
 * text): the central atom pops, its partners fly in from depth and their bonds
 * snap on while the model swings into 3D; three tilted electron orbits draw on
 * and electrons whip round them, passing in front of and behind the atoms.
 * For a bent molecule with a known angle (H2O 104.5°) the angle arc draws in.
 * Without a formula it is an atom: a nucleus with the same orbits. The formula
 * rises glyph by glyph beside it with a kicker, the text and one fact.
 */
const MoleculeOrbit: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const t = frame / fps;
  let f = parseFormula(str(overlay.label));
  if (!f) {
    for (const w of str(overlay.text).split(/[\s,.;:()]+/)) {
      if (!/\d/.test(w)) continue;
      const p = parseFormula(w);
      if (p) { f = p; break; }
    }
  }
  const title = str(overlay.text);
  const kicker = str(overlay.subtitle);
  const bigWord = f ? "" : cap(str(overlay.label)).slice(0, 12);
  if (!f && !title && !bigWord) return null;
  const id = `scmo${overlay.startFrame}`;
  const count = f ? f.atoms.reduce((a, b) => a + b.n, 0) : 0;
  const molecule = f !== null && count >= 2 && count <= 7;
  let centerEl = "";
  const sats: string[] = [];
  if (f && molecule) {
    let ci = f.atoms.findIndex((a) => a.n === 1 && a.el !== "H");
    if (ci < 0) ci = f.atoms.findIndex((a) => a.el !== "H");
    if (ci < 0) ci = 0;
    centerEl = f.atoms[ci].el;
    f.atoms.forEach((a, i) => {
      for (let j = 0; j < (i === ci ? a.n - 1 : a.n); j++) sats.push(a.el);
    });
  }
  const angle: number | undefined = f && f.s in BOND_ANGLES ? BOND_ANGLES[f.s] : undefined;
  const bent = sats.length === 2 && angle !== undefined ? angle
    : sats.length === 2 && (centerEl === "O" || centerEl === "S") ? 105 : sats.length === 2 && centerEl === "N" ? 120 : null;
  const dirs = bondDirs(sats.length, bent);
  const MX = 640, MY = 540;
  const yaw = -1.3 * (1 - ramp(frame, 0, 40)) + 0.5 * Math.sin(t * 0.8);
  const pitch = 0.3;
  const rC = centerEl === "H" ? 56 : 84;
  const proj = (v: V3) => {
    const s = 900 / (900 - v[2]);
    return { x: MX + v[0] * s, y: MY + v[1] * s, s, z: v[2] };
  };
  const exI = (i: number) => ramp(frame, dur - 14 + i, 10, expoIn);
  const satAt = (i: number) => 10 + i * 4;
  const satP = sats.map((el, i) => {
    const rS = el === "H" ? 50 : 76;
    const land = ramp(frame, satAt(i), 20);
    const out = exI(i);
    const dist = (rC + rS + 62) * (1 + 1.5 * (1 - land) + 1.2 * out);
    const d = dirs[i];
    const p = proj(rot3([d[0] * dist, d[1] * dist, d[2] * dist], yaw + (1 - land) * 0.9, pitch));
    return { el, rS, x: p.x, y: p.y, s: p.s, z: p.z, o: Math.min(1, land * 1.6) * (1 - out),
      bond: ramp(frame, satAt(i) + 12, 10) * (1 - out) };
  });
  const cIn = ramp(frame, 4, 16, backOut) * (1 - exI(sats.length));
  const gradOf = (el: string, center: boolean) => (el === "H" ? `url(#${id}h)` : center ? `url(#${id}c)` : `url(#${id}x)`);
  type SatP = (typeof satP)[number];
  const bondEl = (p: SatP, key: string) => {
    const bx = MX + (p.x - MX) * p.bond, by = MY + (p.y - MY) * p.bond;
    return p.bond > 0.01 ? (
      <g key={key}>
        <line x1={MX} y1={MY} x2={bx} y2={by} stroke="#0b0e13" strokeWidth={24 * p.s} strokeLinecap="round" />
        <line x1={MX} y1={MY} x2={bx} y2={by} stroke="#d5dbe2" strokeWidth={15 * p.s} strokeLinecap="round" />
      </g>
    ) : null;
  };
  const atomEl = (el: string, x: number, y: number, r: number, o: number, center: boolean, key: string) => (
    r > 0.5 ? (
      <g key={key} opacity={o}>
        <circle cx={x} cy={y} r={r} fill={gradOf(el, center)} />
        <circle cx={x} cy={y} r={r} fill="none" stroke="#000" strokeOpacity={0.35} strokeWidth={2} />
        <text x={x} y={y} textAnchor="middle" dominantBaseline="central" fontFamily={LABEL} fontWeight={800}
          fontSize={r * 0.72} fill={INK} fillOpacity={0.8}>{el}</text>
      </g>
    ) : null
  );
  const ORB = [{ tilt: -22, sp: 1.6, ph: 0 }, { tilt: 38, sp: 2.1, ph: 2.1 }, { tilt: 98, sp: 2.7, ph: 4.2 }];
  const RX = 340, RY = 104;
  const orbIn = (i: number) => ramp(frame, 2 + i * 4, 22, inOut) * (1 - ramp(frame, dur - 13 + i * 2, 10, expoIn));
  const eOn = ramp(frame, 16, 10) * (1 - ex);
  const electron = (i: number, lag: number) => {
    const o = ORB[i];
    const th = (t * Math.PI * 2) / o.sp + o.ph - lag;
    const a = ((o.tilt + t * 6) * Math.PI) / 180;
    const ex0 = RX * Math.cos(th), ey0 = RY * Math.sin(th);
    return { x: MX + ex0 * Math.cos(a) - ey0 * Math.sin(a), y: MY + ex0 * Math.sin(a) + ey0 * Math.cos(a), front: Math.sin(th) > 0 };
  };
  const electrons = (front: boolean) => ORB.map((_, i) => {
    const e = electron(i, 0);
    if (e.front !== front) return null;
    return (
      <g key={i} opacity={eOn * (front ? 1 : 0.5) * orbIn(i)}>
        {[1, 2, 3].map((j) => {
          const q = electron(i, j * 0.16);
          return <circle key={j} cx={q.x} cy={q.y} r={6 - j * 1.2} fill={CYAN} opacity={0.5 - j * 0.13} />;
        })}
        <circle cx={e.x} cy={e.y} r={front ? 12 : 9} fill={CYAN} opacity={0.3} />
        <circle cx={e.x} cy={e.y} r={front ? 5.5 : 4.5} fill="#fff" />
      </g>
    );
  });
  const nucleus = Array.from({ length: 7 }, (_, i) => {
    const a = (i - 1) * (Math.PI / 3);
    const v: V3 = i === 0 ? [0, 0, 0] : [30 * Math.cos(a), 30 * Math.sin(a), 18 * Math.sin(3 * a + 0.5)];
    const j: V3 = [v[0] + Math.sin(t * 7 + i) * 1.5, v[1] + Math.cos(t * 6 + i * 2) * 1.5, v[2]];
    const p = proj(rot3(j, yaw, pitch));
    return { ...p, i };
  }).sort((a, b) => a.z - b.z);
  const arcOn = molecule && sats.length === 2 && angle !== undefined && angle < 179;
  let arcD = "";
  let arcMid = { x: MX, y: MY };
  if (arcOn) {
    const u1 = rot3(dirs[0], yaw, pitch), u2 = rot3(dirs[1], yaw, pitch);
    const dot = Math.max(-1, Math.min(1, u1[0] * u2[0] + u1[1] * u2[1] + u1[2] * u2[2]));
    const om = Math.acos(dot);
    const AR = rC + 34;
    const pts: Pt[] = Array.from({ length: 17 }, (_, j) => {
      const q = j / 16;
      const w1 = Math.sin((1 - q) * om) / Math.max(1e-6, Math.sin(om)), w2 = Math.sin(q * om) / Math.max(1e-6, Math.sin(om));
      const p = proj([(u1[0] * w1 + u2[0] * w2) * AR, (u1[1] * w1 + u2[1] * w2) * AR, (u1[2] * w1 + u2[2] * w2) * AR]);
      return [p.x, p.y];
    });
    arcD = dOf(pts);
    const mid = unit3([u1[0] + u2[0], u1[1] + u2[1], u1[2] + u2[2]]);
    const mp = proj([mid[0] * (AR + 44), mid[1] * (AR + 44), mid[2] * (AR + 44)]);
    arcMid = { x: mp.x, y: mp.y };
  }
  const arcP = ramp(frame, satAt(1) + 24, 16, inOut) * (1 - ex);
  const backSats = satP.filter((p) => p.z < 0).sort((a, b) => a.z - b.z);
  const frontSats = satP.filter((p) => p.z >= 0).sort((a, b) => a.z - b.z);
  const glyphs = f ? Array.from(f.s).map((ch) => ({ ch, sub: /\d/.test(ch) })) : [];
  const fSize = glyphs.length <= 4 ? 180 : glyphs.length <= 7 ? 150 : 118;
  const titleLines = wrap(cap(title), 24, 3);
  const fact = molecule
    ? angle !== undefined ? `BOND ANGLE ${angle}°` : `${count} ATOMS · ${sats.length} BONDS`
    : f ? (count === 1 ? "ELEMENT" : `${count} ATOMS`) : "";

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - ex }}><Scrim ov={overlay} /></AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <radialGradient id={`${id}h`} cx="35%" cy="30%" r="75%">
              <stop offset="0%" stopColor="#ffffff" /><stop offset="55%" stopColor="#dfe4ea" /><stop offset="100%" stopColor="#8f99a6" />
            </radialGradient>
            <radialGradient id={`${id}c`} cx="35%" cy="30%" r="75%">
              <stop offset="0%" stopColor={mixC(accent, "#ffffff", 0.65)} /><stop offset="55%" stopColor={accent} />
              <stop offset="100%" stopColor={mixC(accent, "#000000", 0.55)} />
            </radialGradient>
            <radialGradient id={`${id}x`} cx="35%" cy="30%" r="75%">
              <stop offset="0%" stopColor="#e6f6ff" /><stop offset="55%" stopColor="#7fb9d9" /><stop offset="100%" stopColor="#2c5470" />
            </radialGradient>
            <radialGradient id={`${id}glow`} cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={accent} stopOpacity={0.22} /><stop offset="100%" stopColor={accent} stopOpacity={0} />
            </radialGradient>
          </defs>
          <circle cx={MX} cy={MY} r={330} fill={`url(#${id}glow)`} opacity={cIn} />
          {ORB.map((o, i) => (
            <ellipse key={i} cx={MX} cy={MY} rx={RX} ry={RY} fill="none" stroke="#fff" strokeOpacity={0.3} strokeWidth={2}
              transform={`rotate(${(o.tilt + t * 6).toFixed(2)} ${MX} ${MY})`} pathLength={1} strokeDasharray="1 1"
              strokeDashoffset={1 - orbIn(i)} opacity={orbIn(i) > 0.002 ? 1 : 0} />
          ))}
          {electrons(false)}
          {molecule ? (
            <g>
              {backSats.map((p, i) => bondEl(p, `bb${i}`))}
              {backSats.map((p, i) => atomEl(p.el, p.x, p.y, p.rS * p.s, p.o, false, `ba${i}`))}
              {atomEl(centerEl, MX, MY, rC * cIn, 1, centerEl !== "H", "c")}
              {arcOn && arcP > 0.002 ? (
                <g>
                  <path d={arcD} fill="none" stroke={accent} strokeWidth={3} pathLength={1} strokeDasharray="1 1"
                    strokeDashoffset={1 - arcP} />
                  <text x={arcMid.x} y={arcMid.y} textAnchor="middle" dominantBaseline="central" fontFamily={MONO} fontWeight={700}
                    fontSize={22} fill={accent} opacity={arcP}>{`${angle}°`}</text>
                </g>
              ) : null}
              {frontSats.map((p, i) => bondEl(p, `fb${i}`))}
              {frontSats.map((p, i) => atomEl(p.el, p.x, p.y, p.rS * p.s, p.o, false, `fa${i}`))}
            </g>
          ) : (
            <g>
              {nucleus.map((p) => atomEl(p.i % 2 ? "" : "", p.x, p.y, 26 * p.s * cIn, 1, p.i % 2 === 0, `n${p.i}`))}
            </g>
          )}
          {electrons(true)}
        </svg>
        <div style={{ position: "absolute", left: 1130 * k, top: 0, bottom: 0, width: 700 * k, display: "flex",
          flexDirection: "column", justifyContent: "center", gap: 10 * k }}>
          {kicker ? (
            <LetterLine text={cap(kicker)} at={6} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
              letterSpacing: "0.24em", color: accent }} />
          ) : null}
          {f ? (
            <FormulaLine glyphs={glyphs} at={10} size={fSize * k} color="#fff" subColor={accent} />
          ) : bigWord ? (
            <LetterLine text={bigWord} at={10} style={{ fontFamily: DISPLAY, fontSize: 150 * k, lineHeight: 1, color: "#fff",
              letterSpacing: "0.03em" }} />
          ) : null}
          <div style={{ width: `${ramp(frame, 18, 16) * (1 - ex) * 120 * k}px`, height: 5 * k, background: accent }} />
          {titleLines.map((ln, i) => (
            <LetterLine key={i} text={ln} at={20 + i * 4} step={0.5} style={{ fontFamily: LABEL, fontWeight: 700,
              fontSize: 42 * k, color: "#fff", letterSpacing: "0.04em", lineHeight: 1.1 }} />
          ))}
          {fact ? (
            <Rise at={34}>
              <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 20 * k, letterSpacing: "0.18em",
                color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{fact}</span>
            </Rise>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. cause chain
const hexD = (x: number, y: number, r: number) => `${Array.from({ length: 6 }, (_, i) => {
  const a = (Math.PI / 3) * i;
  return `${i ? "L" : "M"}${(x + r * Math.cos(a)).toFixed(1)} ${(y + r * Math.sin(a)).toFixed(1)}`;
}).join(" ")} Z`;

/**
 * Two to five consequences as hexagon nodes in a row, dashed links between
 * them. The outlines draw on, then a spark leaves the first node (CAUSE) and
 * runs down each link, the lit line growing behind it; when it arrives the
 * arrowhead snaps on and the next node ignites (fills with the accent, a
 * hexagonal shock ring, its number flipping to ink, its label rising) until
 * the last one (EFFECT). While it holds, small pulses keep running the chain.
 */
const CauseChain: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const rs = rows(overlay.items, 5);
  if (rs.length < 2) return null;
  const t = frame / fps;
  const id = `sccc${overlay.startFrame}`;
  const n = rs.length;
  const S = Math.min(420, 1500 / (n - 1));
  const R = n >= 5 ? 64 : 74;
  const HH = R * 0.866;
  const CY = 548;
  const xs = rs.map((_, i) => 960 + (i - (n - 1) / 2) * S);
  const T0 = Math.round(fps * 0.6);
  const step = Math.max(9, Math.min(Math.round(fps * 0.62), Math.floor((dur * 0.45) / (n - 1))));
  const ign = (i: number) => T0 + i * step;
  const allLit = ign(n - 1) + 14;
  const exI = (i: number) => ramp(frame, dur - 14 + i * 1.2, 10, expoIn);
  const LW = Math.min(S - 30, 360);

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - ex }}><Scrim ov={overlay} /></AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}g`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor={mixC(accent, "#ffffff", 0.35)} /><stop offset="100%" stopColor={accent} />
            </linearGradient>
          </defs>
          {xs.slice(0, -1).map((x, i) => {
            const x1 = x + R + 16, x2 = xs[i + 1] - R - 16;
            const base = ramp(frame, 8 + i * 3, 14) * (1 - exI(i));
            const sp = ramp(frame, ign(i) + 2, Math.max(4, step - 2), inOut);
            const back = exI(i);
            const litFrom = x1 + (x2 - x1) * back;
            const litTo = x1 + (x2 - x1) * sp;
            const arrow = ramp(frame, ign(i + 1) - 2, 8, backOut) * (1 - back);
            const cur = frame > allLit ? (((frame - allLit) / (fps * 0.9)) + i * 0.3) % 1 : -1;
            return (
              <g key={i}>
                <line x1={x1} x2={x2 - 10} y1={CY} y2={CY} stroke="#fff" strokeOpacity={0.24 * base} strokeWidth={3}
                  strokeDasharray="6 9" />
                {litTo > litFrom + 1 ? (
                  <line x1={litFrom} x2={Math.min(litTo, x2 - 12)} y1={CY} y2={CY} stroke={accent} strokeWidth={5}
                    strokeLinecap="round" />
                ) : null}
                {arrow > 0.01 ? <path d={headD(x2, CY, 0, 20 * arrow)} fill={accent} /> : null}
                {sp > 0.01 && sp < 0.99 ? (
                  <g>
                    <circle cx={litTo} cy={CY} r={18} fill={accent} opacity={0.3} />
                    <circle cx={litTo} cy={CY} r={7} fill="#fff" />
                  </g>
                ) : null}
                {cur >= 0 && back < 0.01 ? (
                  <circle cx={x1 + (x2 - x1 - 20) * cur} cy={CY} r={4} fill="#fff" opacity={0.85 * Math.sin(cur * Math.PI)} />
                ) : null}
              </g>
            );
          })}
          {xs.map((x, i) => {
            const draw = ramp(frame, 3 + i * 3, 16, inOut);
            const lit = ramp(frame, ign(i), 10);
            const shock = ramp(frame, ign(i), 20, expoOut);
            const e = exI(i);
            const breathe = 1 + (frame > allLit ? 0.018 * Math.sin(t * 2.4 + i) : 0);
            const sc = (1 - 0.55 * e) * breathe;
            return (
              <g key={i} opacity={1 - e}
                transform={`translate(${x} ${CY}) rotate(${(e * 30).toFixed(1)}) scale(${sc.toFixed(4)}) translate(${-x} ${-CY})`}>
                <path d={hexD(x, CY, R)} fill="#fff" fillOpacity={0.05} />
                <path d={hexD(x, CY, R)} fill={`url(#${id}g)`} opacity={lit} />
                <path d={hexD(x, CY, R)} fill="none" stroke={lit > 0.5 ? accent : "rgba(255,255,255,.55)"} strokeWidth={3}
                  strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw}
                  opacity={draw > 0.002 ? 1 : 0} />
                {shock > 0.01 && shock < 0.99 ? (
                  <path d={hexD(x, CY, R * (1 + 0.7 * shock))} fill="none" stroke={accent} strokeWidth={3} opacity={1 - shock} />
                ) : null}
              </g>
            );
          })}
        </svg>
        {xs.map((x, i) => {
          const lit = ramp(frame, ign(i), 10);
          return (
            <div key={i} style={{ position: "absolute", left: (x - R) * k, top: (CY - HH) * k, width: 2 * R * k, height: 2 * HH * k,
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Rise at={4 + i * 3}>
                <span style={{ display: "block", fontFamily: DISPLAY, fontSize: R * 0.8 * k, lineHeight: 1, letterSpacing: "0.02em",
                  color: lit > 0.5 ? INK : "rgba(255,255,255,.6)" }}>{String(i + 1).padStart(2, "0")}</span>
              </Rise>
            </div>
          );
        })}
        {[0, n - 1].map((i, j) => (
          <div key={`tag${j}`} style={{ position: "absolute", left: xs[i] * k, bottom: (1080 - (CY - HH - 22)) * k,
            transform: "translateX(-50%)" }}>
            <Rise at={ign(i) + 2}>
              <span style={{ display: "block", fontFamily: MONO, fontWeight: 700, fontSize: 18 * k, letterSpacing: "0.32em",
                color: j ? accent : "rgba(255,255,255,.75)", whiteSpace: "nowrap" }}>{j ? "EFFECT" : "CAUSE"}</span>
            </Rise>
          </div>
        ))}
        {rs.map((r, i) => {
          const at = ign(i) + 3;
          const ls = wrap(cap(r.label), n >= 5 ? 14 : 16, 2);
          const ts = r.text ? wrap(r.text, n >= 5 ? 22 : 26, 3) : [];
          return (
            <div key={`l${i}`} style={{ position: "absolute", left: (xs[i] - LW / 2) * k, width: LW * k, top: (CY + HH + 30) * k,
              display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 2 * k }}>
              {ls.map((ln, j) => (
                <Rise key={j} at={at + j * 2}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: (n >= 5 ? 28 : 32) * k,
                    letterSpacing: "0.05em", lineHeight: 1.05, color: i === n - 1 ? accent : "#fff", whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              ))}
              {ts.map((ln, j) => (
                <Rise key={`t${j}`} at={at + 4 + j * 2} out={1}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: (n >= 5 ? 22 : 24) * k,
                    lineHeight: 1.15, color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              ))}
            </div>
          );
        })}
        <div style={{ position: "absolute", left: 0, right: 0, top: 170 * k, display: "flex", justifyContent: "center" }}>
          <CardTitle text={overlay.text} kicker={overlay.subtitle} accent={accent} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. reservoir levels
/**
 * Reservoirs as valley cross-sections carved side by side into a ground slab.
 * The outlines draw on, then each basin fills to its share of capacity (the
 * level solved for area, so 50% sits above half depth, as in a real valley)
 * with a slosh that dies away; the percentage rolls above each, turning red
 * below 30%. Values are percentages, or shares of overlay.total, or else
 * relative to the largest. With a single value it draws one wide basin.
 */
const ReservoirLevels: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  let items = nums(overlay.items, 5);
  const v0 = toNum(overlay.value);
  if (items.length < 2 && Number.isFinite(v0)) {
    items = [{ label: str(overlay.label), value: v0, suffix: str(overlay.suffix) || undefined }];
  }
  if (!items.length) return null;
  const id = `scrl${overlay.startFrame}`;
  const n = items.length;
  const total = toNum(overlay.total);
  const sufOf = (it: Num) => (it.suffix || str(overlay.suffix)).trim();
  const isPct = items.some((it) => sufOf(it) === "%")
    || (items.every((it) => !sufOf(it)) && items.every((it) => it.value >= 0 && it.value <= 100));
  const byTotal = Number.isFinite(total) && total > 0;
  const maxV = Math.max(...items.map((it) => it.value), 1e-9);
  const frac = (v: number) => Math.max(0, Math.min(1, byTotal ? v / total : isPct ? v / 100 : (v / maxV) * 0.9));
  const danger = (v: number) => (byTotal || isPct) && frac(v) < 0.3;
  const hot = pickHot(items.map((i) => i.label), overlay.highlight);
  const GAP = 70;
  const TW = Math.min(n === 1 ? 560 : 340, (1500 - GAP * (n - 1)) / n);
  const BW = TW * 0.34;
  const D = n === 1 ? 330 : 300;
  const RIM = 500, BOT = RIM + D;
  const rowW = n * TW + (n - 1) * GAP;
  const x0 = 960 - rowW / 2;
  const cxs = items.map((_, i) => x0 + TW / 2 + i * (TW + GAP));
  const basin = (cx: number, close: boolean) => {
    const L = cx - TW / 2, Rr = cx + TW / 2, bl = cx - BW / 2, br = cx + BW / 2;
    return `M${L.toFixed(1)} ${RIM} C${(L + TW * 0.1).toFixed(1)} ${RIM + D * 0.55} ${(bl - TW * 0.06).toFixed(1)} ${BOT} ` +
      `${(bl + BW * 0.2).toFixed(1)} ${BOT} L${(br - BW * 0.2).toFixed(1)} ${BOT} C${(br + TW * 0.06).toFixed(1)} ${BOT} ` +
      `${(Rr - TW * 0.1).toFixed(1)} ${RIM + D * 0.55} ${Rr.toFixed(1)} ${RIM}${close ? " Z" : ""}`;
  };
  const levelY = (f: number) => {
    const a = (TW - BW) / (2 * D), b = BW, c = (f * (BW + TW) * D) / 2;
    const h = a > 1e-6 ? (-b + Math.sqrt(b * b + 4 * a * c)) / (2 * a) : c / b;
    return BOT - Math.max(0, Math.min(D, h));
  };
  const surfPts = (cx: number, y: number, amp: number, ph: number): Pt[] => Array.from({ length: 17 }, (_, j) => {
    const x = cx - TW / 2 - 8 + ((TW + 16) * j) / 16;
    return [x, y + amp * Math.sin((j / 16) * Math.PI * 2 * 1.3 + ph)];
  });
  const at = (i: number) => Math.round(fps * 0.45) + i * Math.round(fps * 0.16);
  const fillF = Math.round(Math.max(fps * 0.9, Math.min(fps * 1.4, dur * 0.35)));
  const exI = (i: number) => ramp(frame, dur - 14 + i * 1.5, 10, expoIn);
  const land = ramp(frame, 0, 16);
  const edges = [x0 - 70, ...cxs.flatMap((cx) => [cx - TW / 2, cx + TW / 2]), x0 + rowW + 70];
  let edgeD = "";
  for (let j = 0; j + 1 < edges.length; j += 2) edgeD += `M${edges[j].toFixed(1)} ${RIM} H${edges[j + 1].toFixed(1)} `;
  const NS = n === 1 ? 110 : 84;

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - ex }}><Scrim ov={overlay} /></AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5cc9ff" /><stop offset="100%" stopColor="#0b3f78" />
            </linearGradient>
            {cxs.map((cx, i) => <clipPath key={i} id={`${id}c${i}`}><path d={basin(cx, true)} /></clipPath>)}
          </defs>
          <g opacity={land * (1 - ex)}>
            <path d={`M${(x0 - 70).toFixed(1)} ${RIM} H${(x0 + rowW + 70).toFixed(1)} V${BOT + 46} H${(x0 - 70).toFixed(1)} Z ` +
              cxs.map((cx) => basin(cx, true)).join(" ")} fill="#fff" fillOpacity={0.06} fillRule="evenodd" />
            <path d={edgeD} fill="none" stroke="#fff" strokeOpacity={0.45} strokeWidth={2} />
            <text x={cxs[0] - TW / 2} y={RIM - 12} fontFamily={MONO} fontSize={16} letterSpacing={3} fill="#fff"
              fillOpacity={0.55}>FULL POOL</text>
          </g>
          {cxs.map((cx, i) => {
            const e = exI(i);
            const fp = ramp(frame, at(i), fillF, inOut) * (1 - e);
            const f = frac(items[i].value) * fp;
            const y = levelY(f);
            const since = frame - (at(i) + fillF * 0.55);
            const amp = frame < at(i) ? 0 : 2.5 + 9 * Math.exp(-Math.max(0, since) / 12);
            const ph = frame / 5 + i * 1.7;
            const draw = ramp(frame, 2 + i * 3, 18, inOut) * (1 - e);
            const pts = surfPts(cx, y, amp, ph);
            return (
              <g key={i}>
                <path d={basin(cx, true)} fill="#000" fillOpacity={0.35 * land * (1 - e)} />
                {f > 0.001 ? (
                  <g clipPath={`url(#${id}c${i})`}>
                    <path d={`${dOf(pts)} L${(cx + TW / 2 + 8).toFixed(1)} ${BOT + 12} L${(cx - TW / 2 - 8).toFixed(1)} ${BOT + 12} Z`}
                      fill={`url(#${id}w)`} opacity={0.95} />
                    <path d={dOf(pts)} fill="none" stroke="#dff6ff" strokeOpacity={0.75} strokeWidth={3} />
                  </g>
                ) : null}
                <path d={basin(cx, false)} fill="none" stroke={i === hot ? accent : "#fff"} strokeOpacity={i === hot ? 1 : 0.6}
                  strokeWidth={3} strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw}
                  opacity={draw > 0.002 ? 1 : 0} />
                <line x1={cx - TW / 2} x2={cx - TW / 2 + TW * draw} y1={RIM} y2={RIM} stroke="#fff" strokeOpacity={0.45}
                  strokeWidth={2} strokeDasharray="10 8" />
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const dng = danger(it.value);
          return (
            <div key={i} style={{ position: "absolute", left: (cxs[i] - 200) * k, width: 400 * k, top: (RIM - NS - 28) * k,
              display: "flex", justifyContent: "center" }}>
              <Rise at={at(i) - 2} frames={12}>
                <Odometer value={it.value} at={at(i)} frames={fillF} size={NS * k} color={dng ? RED : "#fff"}
                  prefix={it.prefix || str(overlay.prefix)} suffix={tail(sufOf(it))} suffixScale={0.5}
                  suffixColor={dng ? RED : accent} />
              </Rise>
            </div>
          );
        })}
        {items.map((it, i) => {
          const a = at(i) + 6;
          const ls = it.label ? wrap(cap(it.label), Math.max(8, Math.floor(TW / 16)), 2) : [];
          const BWD = TW + GAP - 10;
          return (
            <div key={`l${i}`} style={{ position: "absolute", left: (cxs[i] - BWD / 2) * k, width: BWD * k, top: (BOT + 24) * k,
              display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
              {ls.map((ln, j) => (
                <Rise key={j} at={a + j * 2}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.06em",
                    lineHeight: 1.05, color: i === hot ? accent : "#fff", whiteSpace: "nowrap" }}>{ln}</span>
                </Rise>
              ))}
              {it.text ? (
                <Rise at={a + 5} out={1}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 22 * k, letterSpacing: "0.1em",
                    color: "rgba(255,255,255,.65)", whiteSpace: "nowrap" }}>{cap(it.text)}</span>
                </Rise>
              ) : null}
            </div>
          );
        })}
        <div style={{ position: "absolute", left: 0, right: 0, top: 140 * k, display: "flex", justifyContent: "center" }}>
          <CardTitle text={overlay.text} kicker={overlay.subtitle} accent={accent} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. warming stripes
const yearOf = (s: string): number => {
  const m = /^\s*(1[5-9]\d\d|20\d\d|2100)\s*$/.exec(s);
  return m ? Number(m[1]) : NaN;
};

/**
 * The "show your stripes" graphic as a full-frame backdrop: one stripe per
 * year (items, interpolated when few, or a warming curve built from the
 * value), deep blue through white to red. The stripes grow up out of the axis
 * behind a scanning playhead with a light at its edge that reads out the year;
 * a soft sheen passes while it holds; the stripes drop back in a wave at the
 * end. The footer carries the title and the figure (value, "+" and a degree
 * sign for an anomaly). A series that is not a temperature is drawn in the
 * accent from dark to light instead of blue to red.
 */
const WarmingStripes: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const its = nums(overlay.items, 600);
  const v = toNum(overlay.value);
  let series: number[] = [];
  let y0 = NaN, y1 = NaN;
  let synth = false;
  if (its.length >= 8) {
    series = its.map((i) => i.value);
    y0 = yearOf(its[0].label);
    y1 = yearOf(its[its.length - 1].label);
  } else if (its.length >= 3) {
    const yrs = its.map((i) => yearOf(i.label));
    const span = yrs[yrs.length - 1] - yrs[0];
    const byYear = yrs.every((y, i) => Number.isFinite(y) && (i === 0 || y > yrs[i - 1])) && span >= 8 && span <= 400;
    if (byYear) {
      for (let y = yrs[0]; y <= yrs[yrs.length - 1]; y++) {
        let j = 0;
        while (j < yrs.length - 2 && yrs[j + 1] < y) j++;
        const q = Math.max(0, Math.min(1, (y - yrs[j]) / Math.max(1, yrs[j + 1] - yrs[j])));
        series.push(its[j].value + (its[j + 1].value - its[j].value) * q);
      }
      y0 = yrs[0];
      y1 = yrs[yrs.length - 1];
    } else {
      for (let j = 0; j < its.length - 1; j++) {
        for (let s = 0; s < 12; s++) series.push(its[j].value + ((its[j + 1].value - its[j].value) * s) / 12);
      }
      series.push(its[its.length - 1].value);
    }
  } else if (Number.isFinite(v) && v !== 0) {
    synth = true;
    const N0 = 80;
    for (let i = 0; i < N0; i++) {
      const q = i / (N0 - 1);
      const noise = (rnd(i + 17) - 0.5) * 0.36 * Math.abs(v) * (0.6 + 0.4 * q);
      series.push(i === N0 - 1 ? v : -0.3 * v + 1.3 * v * Math.pow(q, 2.1) + noise);
    }
  }
  if (!Number.isFinite(y0) || !Number.isFinite(y1)) {
    const ys = `${str(overlay.subtitle)} ${str(overlay.label)}`.match(/\b(1[5-9]\d\d|20\d\d)\b/g);
    if (ys && ys.length >= 2) {
      y0 = Number(ys[0]);
      y1 = Number(ys[ys.length - 1]);
    }
  }
  if (series.length < 8) return null;
  const MAXS = 120;
  if (series.length > MAXS) {
    const out: number[] = [];
    for (let b = 0; b < MAXS; b++) {
      const a0 = Math.floor((b * series.length) / MAXS);
      const a1 = Math.max(a0 + 1, Math.floor(((b + 1) * series.length) / MAXS));
      let s = 0;
      for (let j = a0; j < a1; j++) s += series[j];
      out.push(s / (a1 - a0));
    }
    series = out;
  }
  const N = series.length;
  const id = `scws${overlay.startFrame}`;
  const suffix = str(overlay.suffix) || (its.find((i) => i.suffix)?.suffix ?? "");
  const ctx = `${suffix} ${str(overlay.text)} ${str(overlay.subtitle)} ${str(overlay.label)}`.toLowerCase();
  const temp = synth || /°|temp|warm|heat|hot|climat|degree|celsius|fahrenheit/.test(ctx) || /^[cf]$/i.test(suffix);
  const lo = Math.min(...series), hi = Math.max(...series);
  const anomaly = synth || (lo < 0 && hi > 0);
  const center = anomaly ? 0 : series.reduce((a, b) => a + b, 0) / N;
  const spread = Math.max(1e-9, ...series.map((s) => Math.abs(s - center)));
  const cols = series.map((s) => (temp
    ? colorAt(Math.max(-1, Math.min(1, (s - center) / spread)), [-1, -0.5, 0, 0.5, 1],
      ["#0a2c5e", "#2f7fc4", "#e9edf0", RED, "#6d0a0a"])
    : colorAt((s - lo) / Math.max(1e-9, hi - lo), [0, 0.55, 1], ["#15171c", accent, "#f7f3ea"])));
  const shown = Number.isFinite(v) ? v : its.length ? its[its.length - 1].value : series[N - 1];
  const unit = temp ? suffix || "°" : suffix;
  const dirWord = str(overlay.label).toLowerCase();
  const caption = dirWord === "up" || dirWord === "down" ? "" : str(overlay.label);

  const SH = 752;
  const sw = 1920 / N;
  const sweepAt = Math.round(fps * 0.3);
  const sweepF = Math.round(Math.max(fps * 0.9, Math.min(fps * 1.7, dur * 0.34)));
  const prog = interpolate(frame, [sweepAt, sweepAt + sweepF], [0, 1], clamp);
  const grow = (i: number) => ramp(frame, sweepAt + (i / N) * sweepF, 12, expoOut);
  const shrink = (i: number) => ramp(frame, dur - 15 + (i / N) * 5, 9, expoIn);
  const headX = prog * 1920;
  const headOn = ramp(frame, sweepAt, 6) * (1 - ramp(frame, sweepAt + sweepF - 2, 10));
  const years = Number.isFinite(y0) && Number.isFinite(y1) && y1 > y0;
  const curYear = years ? Math.round(y0 + (y1 - y0) * prog) : NaN;
  const sweepEnd = sweepAt + sweepF;
  const sheen = frame > sweepEnd + 6 ? (((frame - sweepEnd - 6) / (fps * 2.6)) % 1) * 2400 - 300 : -1000;
  const xOfYear = (y: number) => ((y - y0) / Math.max(1, y1 - y0)) * (1920 - sw) + sw / 2;
  const ticks = years ? niceScale(y0, y1, 6).ticks.filter((y) => y > y0 && y < y1 && xOfYear(y) > 190 && xOfYear(y) < 1730) : [];
  const axisOn = ramp(frame, sweepEnd - 6, 12) * (1 - ex);

  return (
    <AbsoluteFill style={{ opacity: bg, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "#050608" }} />
      <AbsoluteFill style={{ transform: `scale(${hold})`, transformOrigin: "50% 70%" }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}lead`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#fff" stopOpacity={0} /><stop offset="100%" stopColor="#fff" stopOpacity={0.45} />
            </linearGradient>
            <linearGradient id={`${id}sh`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#fff" stopOpacity={0} /><stop offset="50%" stopColor="#fff" stopOpacity={0.14} />
              <stop offset="100%" stopColor="#fff" stopOpacity={0} />
            </linearGradient>
          </defs>
          {series.map((_, i) => {
            const h = SH * grow(i) * (1 - shrink(i));
            return h > 0.5 ? <rect key={i} x={i * sw} y={SH - h} width={sw + 0.8} height={h} fill={cols[i]} /> : null;
          })}
          <rect x={sheen} y={0} width={260} height={SH} fill={`url(#${id}sh)`} opacity={1 - ex} />
          <g opacity={headOn}>
            <rect x={headX - 90} y={0} width={90} height={SH} fill={`url(#${id}lead)`} />
            <line x1={headX} x2={headX} y1={0} y2={SH} stroke="#fff" strokeWidth={2.5} />
          </g>
        </svg>
      </AbsoluteFill>
      <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
        <defs>
          <linearGradient id={`${id}ft`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0b0c10" /><stop offset="100%" stopColor="#030304" />
          </linearGradient>
        </defs>
        <rect x={0} y={SH} width={1920} height={1080 - SH} fill={`url(#${id}ft)`} />
        <line x1={0} x2={1920} y1={SH} y2={SH} stroke="#fff" strokeOpacity={0.4} strokeWidth={2} />
        <g opacity={axisOn}>
          {ticks.map((y, i) => (
            <g key={i}>
              <line x1={xOfYear(y)} x2={xOfYear(y)} y1={SH} y2={SH + 12} stroke="#fff" strokeOpacity={0.5} strokeWidth={2} />
              <text x={xOfYear(y)} y={SH + 36} textAnchor="middle" fontFamily={MONO} fontSize={19} fill="#fff"
                fillOpacity={0.55}>{String(y)}</text>
            </g>
          ))}
          {years ? (
            <g>
              <text x={90} y={SH + 36} fontFamily={MONO} fontWeight={700} fontSize={19} fill="#fff" fillOpacity={0.85}>{String(y0)}</text>
              <text x={1830} y={SH + 36} textAnchor="end" fontFamily={MONO} fontWeight={700} fontSize={19} fill="#fff"
                fillOpacity={0.85}>{String(y1)}</text>
            </g>
          ) : null}
        </g>
      </svg>
      {years && headOn > 0.01 ? (
        <div style={{ position: "absolute", left: Math.max(90, Math.min(1690, headX - 64)) * k, top: (SH - 62) * k,
          opacity: headOn, fontFamily: MONO, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.08em", color: "#fff",
          textShadow: "0 2px 12px rgba(0,0,0,.75)" }}>{String(curYear)}</div>
      ) : null}
      <div style={{ position: "absolute", left: 90 * k, top: (SH + 62) * k }}>
        <TitleBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} size={52} chars={34} at={sweepEnd - 12} />
      </div>
      <div style={{ position: "absolute", right: 90 * k, top: (SH + 56) * k, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 4 * k }}>
        {caption ? (
          <Rise at={sweepEnd - 6}>
            <span style={{ display: "block", fontFamily: MONO, fontWeight: 700, fontSize: 19 * k, letterSpacing: "0.24em",
              color: "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>{cap(caption)}</span>
          </Rise>
        ) : null}
        <Rise at={sweepEnd - 8} frames={12}>
          <Odometer value={shown} at={sweepEnd - 6} frames={Math.round(fps * 1.1)} size={132 * k} color="#fff"
            prefix={anomaly && shown > 0 ? "+" : ""} suffix={tail(unit)} suffixScale={0.46} suffixColor={temp ? RED : accent} />
        </Rise>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. rain gauges
/**
 * Two to five graduated glass rain gauges land in a row. Drops fall into each
 * funnel (a streak above each) and every landing sends a ripple across the
 * water as the column rises to its value on the shared scale; the reading
 * rolls and rides the meniscus on the gauge's right. The narrated one
 * (overlay.highlight) is outlined in the accent. The water drains at the end.
 */
const RainGauges: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const items = nums(overlay.items, 5).map((i) => ({ ...i, value: Math.max(0, i.value) }));
  if (items.length < 2) return null;
  const id = `scrg${overlay.startFrame}`;
  const n = items.length;
  const suffix = str(overlay.suffix) || (items.find((i) => i.suffix)?.suffix ?? "");
  const maxV = Math.max(...items.map((i) => i.value), 1e-9);
  const sc = niceScale(0, maxV * 1.04, 5);
  const hot = pickHot(items.map((i) => i.label), overlay.highlight);
  const TW = 88, TH = 390, TOP = 452, BOTY = TOP + TH, FUN = 62;
  const S = Math.min(320, 1320 / n);
  const cxs = items.map((_, i) => 960 + (i - (n - 1) / 2) * S);
  const at = (i: number) => Math.round(fps * 0.5) + i * Math.round(fps * 0.2);
  const fillF = Math.round(Math.max(fps * 1.0, Math.min(fps * 1.5, dur * 0.38)));
  const exI = (i: number) => ramp(frame, dur - 14 + i, 10, expoIn);
  const P = 13;
  const yStart = TOP - FUN - 180, yEnd = TOP - FUN + 8;
  const yOfV = (v: number) => BOTY - 6 - (v / sc.max) * (TH - 16);
  const levelOf = (i: number) => {
    const fp = ramp(frame, at(i), fillF, inOut) * (1 - exI(i));
    return BOTY - 6 - (items[i].value / sc.max) * (TH - 16) * fp;
  };
  const tickD = (cx: number) => {
    let d = "";
    const minor = sc.step / 2;
    for (let j = 0; j <= 40; j++) {
      const v = j * minor;
      if (v > sc.max + 1e-9) break;
      const len = j % 2 === 0 ? 22 : 12;
      const y = yOfV(v);
      d += `M${(cx + TW / 2 - 5 - len).toFixed(1)} ${y.toFixed(1)} H${(cx + TW / 2 - 5).toFixed(1)} `;
    }
    return d;
  };
  const rainOf = (i: number) => {
    const cx = cxs[i];
    const endF = at(i) + fillF - 4;
    const out: { x: number; y: number; o: number }[] = [];
    let last = -1e9;
    for (let j = 0; j < 4; j++) {
      const t0 = at(i) - 10 + (j * P) / 4;
      const rel = frame - t0;
      if (rel < 0) continue;
      const m = Math.floor(rel / P);
      const u = (rel - m * P) / P;
      if (t0 + (m + 1) * P <= endF) {
        out.push({ x: cx + (rnd(i * 31 + j * 7 + m * 3) - 0.5) * 96, y: yStart + (yEnd - yStart) * u * u,
          o: Math.min(1, u * 5) * (1 - ex) });
      }
      const prevLand = t0 + m * P;
      if (m >= 1 && prevLand <= endF + 1) last = Math.max(last, prevLand);
    }
    return { out, since: frame - last };
  };
  const scaleOn = ramp(frame, 6, 14) * (1 - ex);

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - ex }}><Scrim ov={overlay} /></AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#63cfff" /><stop offset="100%" stopColor="#0b3f78" />
            </linearGradient>
            {cxs.map((cx, i) => (
              <clipPath key={i} id={`${id}c${i}`}>
                <rect x={cx - TW / 2 + 1.5} y={TOP} width={TW - 3} height={TH} rx={15} />
              </clipPath>
            ))}
          </defs>
          <g opacity={scaleOn}>
            {sc.ticks.map((v, i) => (
              <text key={i} x={cxs[0] - TW / 2 - 16} y={yOfV(v) + 6} textAnchor="end" fontFamily={MONO} fontSize={18} fill="#fff"
                fillOpacity={0.6}>{fmtTick(v, sc.step)}</text>
            ))}
            {suffix ? (
              <text x={cxs[0] - TW / 2 - 16} y={TOP - 22} textAnchor="end" fontFamily={MONO} fontWeight={700} fontSize={16}
                letterSpacing={3} fill={CYAN}>{cap(suffix)}</text>
            ) : null}
            <line x1={cxs[0] - S / 2} x2={cxs[n - 1] + S / 2} y1={BOTY + 14} y2={BOTY + 14} stroke="#fff" strokeOpacity={0.5}
              strokeWidth={2} />
          </g>
          {cxs.map((cx, i) => {
            const tp = ramp(frame, 2 + i * 3, 16);
            const e = exI(i);
            const yL = levelOf(i);
            const rain = rainOf(i);
            const q = rain.since >= 0 && rain.since < 9 ? rain.since / 9 : -1;
            const hi = i === hot;
            return (
              <g key={i} opacity={tp * (1 - e)} transform={`translate(0 ${((1 - tp) * 50 + e * 40).toFixed(1)})`}>
                {rain.out.map((d, j) => (
                  <g key={j} opacity={d.o}>
                    <line x1={d.x} x2={d.x} y1={d.y - 34} y2={d.y - 15} stroke="#bfeaff" strokeOpacity={0.35} strokeWidth={2}
                      strokeLinecap="round" />
                    <path d={dropD(d.x, d.y)} fill="#a8e6ff" />
                  </g>
                ))}
                <path d={`M${cx - 78} ${TOP - FUN} L${cx + 78} ${TOP - FUN} L${cx + TW / 2 - 4} ${TOP + 2} L${cx - TW / 2 + 4} ${TOP + 2} Z`}
                  fill="#fff" fillOpacity={0.07} stroke="#fff" strokeOpacity={0.7} strokeWidth={3} strokeLinejoin="round" />
                <ellipse cx={cx} cy={TOP - FUN} rx={78} ry={7} fill="none" stroke="#fff" strokeOpacity={0.7} strokeWidth={2.5} />
                <rect x={cx - TW / 2} y={TOP} width={TW} height={TH} rx={16} fill="#fff" fillOpacity={0.05} />
                <g clipPath={`url(#${id}c${i})`}>
                  <rect x={cx - TW / 2} y={yL} width={TW} height={Math.max(0, BOTY - yL + 4)} fill={`url(#${id}w)`} />
                  <ellipse cx={cx} cy={yL} rx={TW / 2 - 3} ry={5} fill="#c8f0ff" opacity={yL < BOTY - 8 ? 0.85 : 0} />
                  {q >= 0 ? (
                    <ellipse cx={cx} cy={yL} rx={6 + (TW / 2 - 12) * q} ry={2 + 3 * q} fill="none" stroke="#fff" strokeWidth={2}
                      opacity={1 - q} />
                  ) : null}
                </g>
                <path d={tickD(cx)} stroke="#fff" strokeOpacity={0.5} strokeWidth={2} />
                <rect x={cx - TW / 2} y={TOP} width={TW} height={TH} rx={16} fill="none" stroke={hi ? accent : "#fff"}
                  strokeOpacity={hi ? 1 : 0.62} strokeWidth={3} />
                <line x1={cx - TW / 2 + 14} x2={cx - TW / 2 + 14} y1={TOP + 20} y2={BOTY - 20} stroke="#fff" strokeOpacity={0.22}
                  strokeWidth={6} strokeLinecap="round" />
                <rect x={cx - TW / 2 - 18} y={BOTY - 2} width={TW + 36} height={16} rx={5} fill="#2a2f37" stroke="#fff"
                  strokeOpacity={0.3} strokeWidth={2} />
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const tp = ramp(frame, 2 + i * 3, 16);
          return (
            <div key={i} style={{ position: "absolute", left: (cxs[i] + TW / 2 + 14) * k,
              top: (levelOf(i) - 30 + (1 - tp) * 50) * k }}>
              <Rise at={at(i)} frames={10}>
                <Odometer value={it.value} at={at(i)} frames={fillF} size={54 * k} color={i === hot ? accent : "#fff"}
                  prefix={it.prefix || str(overlay.prefix)} suffix={tail(it.suffix || suffix)} suffixScale={0.42}
                  suffixColor="rgba(255,255,255,.7)" />
              </Rise>
            </div>
          );
        })}
        {items.map((it, i) => {
          const a = at(i) + 4;
          const BWD = Math.max(150, S - 16);
          return (
            <div key={`l${i}`} style={{ position: "absolute", left: (cxs[i] - BWD / 2) * k, width: BWD * k, top: (BOTY + 34) * k,
              display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
              {it.label ? (
                <Rise at={a}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.06em",
                    color: i === hot ? accent : "#fff", whiteSpace: "nowrap" }}>{cap(it.label)}</span>
                </Rise>
              ) : null}
              {it.text ? (
                <Rise at={a + 4} out={1}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 22 * k, letterSpacing: "0.1em",
                    color: "rgba(255,255,255,.65)", whiteSpace: "nowrap" }}>{cap(it.text)}</span>
                </Rise>
              ) : null}
            </div>
          );
        })}
        <div style={{ position: "absolute", left: 0, right: 0, top: 92 * k, display: "flex", justifyContent: "center" }}>
          <CardTitle text={overlay.text} kicker={overlay.subtitle} accent={accent} size={52} max={1} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. dam level
const DAM_ROCK: Pt[] = [[0, 170], [130, 178], [190, 262], [176, 382], [222, 500], [204, 640], [250, 780], [236, 900],
  [262, 960], [420, 990], [700, 982], [900, 996], [1080, 1004], [1080, 1080], [0, 1080]];
const DAM_FAR: Pt[] = [[1920, 150], [1800, 172], [1744, 320], [1782, 520], [1722, 720], [1760, 900], [1742, 1004], [1920, 1004]];
const DAM_BODY = "M1078 296 L1156 296 L1156 350 C1186 520 1300 800 1452 1004 L1078 1004 Z";

/**
 * A dam and its reservoir in section on a canyon backdrop, an elevation scale
 * up the left wall. The reservoir starts at full pool (overlay.total) and
 * falls to the level (value + suffix), a pale bathtub ring appearing on the
 * rock above it; each intake (items: label, value) flips from SUBMERGED to
 * EXPOSED in red with a flash as the surface passes it, a "dead pool" item is
 * drawn as a red dashed floor. The elevation rolls top right and the distance
 * below full pool wipes in under it. Without a full pool the water rises to
 * the level instead.
 */
const DamLevel: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const value = toNum(overlay.value);
  if (!Number.isFinite(value)) return null;
  const t = frame / fps;
  const id = `scdl${overlay.startFrame}`;
  const total = toNum(overlay.total);
  const hasFull = Number.isFinite(total) && total > value;
  const marks = nums(overlay.items, 4);
  const suffix = str(overlay.suffix);
  const caption = str(overlay.label) || "Water level";
  const allV = [value, ...(hasFull ? [total] : []), ...marks.map((m) => m.value)];
  const dMin = Math.min(...allV), dMax = Math.max(...allV);
  const lone = dMax - dMin < Math.max(1e-9, Math.abs(dMax) * 0.05);
  const sc = lone
    ? niceScale(Math.min(0, value * 1.2), Math.max(0, value) * 1.3 || 1, 6)
    : niceScale(dMin - (dMax - dMin) * 0.22, dMax + (dMax - dMin) * 0.1, 6);
  const Y_TOP = 330, Y_BOT = 985;
  const yOf = (e: number) => Y_BOT - ((e - sc.min) / Math.max(1e-9, sc.max - sc.min)) * (Y_BOT - Y_TOP);
  const startE = hasFull ? total : sc.min;
  const lvAt = Math.round(fps * 0.7);
  const lvF = Math.round(Math.max(fps * 1.0, Math.min(fps * 1.8, dur * 0.42)));
  const elevAt = (f: number) => startE + (value - startE) * ramp(f, lvAt, lvF, inOut);
  const elev = elevAt(frame);
  const yL = yOf(elev);
  const crossAt = (e: number): number => {
    for (let f = lvAt; f <= lvAt + lvF; f++) {
      const el = elevAt(f);
      if ((startE > value && el < e) || (startE < value && el > e)) return f;
    }
    return -1;
  };
  const rockIn = ramp(frame, 0, 22);
  const damIn = ramp(frame, 3, 24);
  const waterIn = ramp(frame, 6, 14);
  const surf: Pt[] = Array.from({ length: 32 }, (_, i) => {
    const x = 150 + (930 * i) / 31;
    return [x, yL + 3 * Math.sin(x / 38 + t * 3) * waterIn];
  });
  const intakes = marks.filter((m) => !/dead/i.test(m.label));
  const dead = marks.find((m) => /dead/i.test(m.label));
  const slots = intakes.map((m) => ({ m, y: yOf(m.value), ly: yOf(m.value) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < slots.length; i++) slots[i].ly = Math.max(slots[i].ly, slots[i - 1].ly + 58);
  const chipP = hasFull ? ramp(frame, lvAt + lvF - 6, 14) * (1 - ex) : 0;
  const scaleOn = ramp(frame, 6, 14) * (1 - ex);

  return (
    <AbsoluteFill style={{ opacity: bg, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, #04070c 0%, #0c1520 55%, #0a1119 100%)" }} />
      <AbsoluteFill style={{ transform: `translateY(${ex * 30 * k}px) scale(${hold})`, transformOrigin: "50% 70%" }}>
        <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2a8fcf" /><stop offset="100%" stopColor="#06243d" />
            </linearGradient>
            <linearGradient id={`${id}r`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#15181d" /><stop offset="100%" stopColor="#262b33" />
            </linearGradient>
            <linearGradient id={`${id}d`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#c9ccd0" /><stop offset="45%" stopColor="#a4a9af" /><stop offset="100%" stopColor="#6f757c" />
            </linearGradient>
            <pattern id={`${id}j`} width={400} height={56} patternUnits="userSpaceOnUse">
              <line x1={0} x2={400} y1={55} y2={55} stroke="#000" strokeOpacity={0.12} strokeWidth={2} />
            </pattern>
            <clipPath id={`${id}rc`}><path d={closed(DAM_ROCK)} /></clipPath>
          </defs>
          <path d={closed(DAM_FAR)} fill="#11151b" opacity={rockIn} />
          <path d="M1078 1004 L1920 1012 L1920 1080 L1078 1080 Z" fill="#181b21" />
          <path d="M1440 1000 L1920 1000 L1920 1044 L1440 1036 Z" fill="#0c3a5c" opacity={waterIn} />
          <path d="M1452 1020 H1920" stroke="#fff" strokeOpacity={0.35 * waterIn} strokeWidth={2.5} strokeDasharray="16 26"
            strokeDashoffset={-frame * 3} />
          <g opacity={damIn}>
            <rect x={1462} y={902} width={216} height={10} fill="#3b434d" />
            <rect x={1470} y={910} width={200} height={90} fill="#2b3139" stroke="#5e6773" strokeWidth={2} />
            <path d="M1490 934 h16 v24 h-16 Z M1528 934 h16 v24 h-16 Z M1566 934 h16 v24 h-16 Z M1604 934 h16 v24 h-16 Z M1642 934 h16 v24 h-16 Z"
              fill={CYAN} fillOpacity={0.35} />
          </g>
          <path d={`${dOf(surf)} L1080 1004 L150 1004 Z`} fill={`url(#${id}w)`} opacity={waterIn} />
          <path d={dOf(surf)} fill="none" stroke="#bfe9ff" strokeOpacity={0.7 * waterIn} strokeWidth={2.5} />
          <g transform={`translate(${((1 - rockIn) * -160).toFixed(1)} 0)`}>
            <path d={closed(DAM_ROCK)} fill={`url(#${id}r)`} />
            {hasFull ? (
              <rect x={0} y={yOf(total)} width={1080} height={Math.max(0, yL - yOf(total))} fill="#e2dccf" opacity={0.5 * waterIn}
                clipPath={`url(#${id}rc)`} />
            ) : null}
          </g>
          <g opacity={damIn} transform={`translate(0 ${((1 - damIn) * 140).toFixed(1)})`}>
            <path d={DAM_BODY} fill={`url(#${id}d)`} />
            <path d={DAM_BODY} fill={`url(#${id}j)`} />
            <line x1={1078} x2={1078} y1={296} y2={1004} stroke="#000" strokeOpacity={0.35} strokeWidth={3} />
            <rect x={1072} y={288} width={90} height={9} fill="#6f757c" />
            <line x1={1070} x2={1164} y1={282} y2={282} stroke="#d7dade" strokeWidth={3} />
          </g>
          {hasFull ? (
            <g opacity={ramp(frame, 10, 12) * (1 - ex)}>
              <line x1={250} x2={1076} y1={yOf(total)} y2={yOf(total)} stroke="#fff" strokeOpacity={0.5} strokeWidth={2}
                strokeDasharray="10 8" />
            </g>
          ) : null}
          {dead ? (
            <g opacity={ramp(frame, 16, 12) * (1 - ex)}>
              <line x1={250} x2={1076} y1={yOf(dead.value)} y2={yOf(dead.value)} stroke={RED} strokeOpacity={0.85}
                strokeWidth={2.5} strokeDasharray="12 9" />
            </g>
          ) : null}
          {slots.map(({ m, y, ly }, i) => {
            const expo = elev < m.value;
            const cf = crossAt(m.value);
            const fl = cf >= 0 ? ramp(frame, cf, 18, expoOut) : 0;
            const on = ramp(frame, 12 + i * 3, 12) * (1 - ex);
            return (
              <g key={i} opacity={on}>
                <path d={`M1040 ${y.toFixed(1)} H760 L722 ${ly.toFixed(1)}`} fill="none" stroke="#fff" strokeOpacity={0.5}
                  strokeWidth={2} strokeDasharray="6 8" />
                <rect x={1046} y={y - 16} width={34} height={32} rx={3} fill="#37404a" stroke={expo ? RED : "#aab3bd"} strokeWidth={2} />
                <path d={`M1054 ${y - 10} V${y + 10} M1063 ${y - 10} V${y + 10} M1072 ${y - 10} V${y + 10}`} stroke="#aab3bd"
                  strokeWidth={1.5} />
                {fl > 0 && fl < 1 ? (
                  <circle cx={1063} cy={y} r={20 + 46 * fl} fill="none" stroke={expo ? RED : CYAN} strokeWidth={3} opacity={1 - fl} />
                ) : null}
              </g>
            );
          })}
          <g opacity={scaleOn}>
            <line x1={196} x2={196} y1={Y_TOP} y2={Y_BOT} stroke="#fff" strokeOpacity={0.5} strokeWidth={2} />
            {sc.ticks.map((v, i) => (
              <g key={i}>
                <line x1={176} x2={196} y1={yOf(v)} y2={yOf(v)} stroke="#fff" strokeOpacity={0.6} strokeWidth={2} />
                <text x={168} y={yOf(v) + 6} textAnchor="end" fontFamily={MONO} fontSize={17} fill="#fff" fillOpacity={0.72}>
                  {fmtTick(v, sc.step)}</text>
              </g>
            ))}
            {suffix ? (
              <text x={168} y={Y_TOP - 24} textAnchor="end" fontFamily={MONO} fontWeight={700} fontSize={16} letterSpacing={3}
                fill={CYAN}>{cap(suffix)}</text>
            ) : null}
            <path d={`M204 ${yL.toFixed(1)} L222 ${(yL - 9).toFixed(1)} L222 ${(yL + 9).toFixed(1)} Z`} fill={CYAN} />
            <line x1={222} x2={262} y1={yL} y2={yL} stroke={CYAN} strokeWidth={2} strokeDasharray="4 4" />
          </g>
        </svg>
        {slots.map(({ m, ly }, i) => {
          const expo = elev < m.value;
          return (
            <div key={i} style={{ position: "absolute", left: 712 * k, top: ly * k, transform: "translate(-100%, -50%)",
              display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
              <Rise at={14 + i * 3}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.08em",
                  color: expo ? RED : "#fff", whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>
                  {cap(m.label) || "INTAKE"}</span>
              </Rise>
              <Rise at={18 + i * 3} out={1}>
                <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 17 * k, letterSpacing: "0.12em",
                  color: "rgba(255,255,255,.75)", whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>
                  {`${fmt(m.value)}${cap(tail(suffix))}`}
                  <span style={{ color: expo ? RED : CYAN }}>{expo ? " · EXPOSED" : " · SUBMERGED"}</span>
                </span>
              </Rise>
            </div>
          );
        })}
        {dead ? (
          <div style={{ position: "absolute", left: 272 * k, bottom: (1080 - yOf(dead.value) + 8) * k }}>
            <Rise at={18}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.1em",
                color: RED, whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>
                {`${cap(dead.label)} · ${fmt(dead.value)}${cap(tail(suffix))}`}</span>
            </Rise>
          </div>
        ) : null}
        {hasFull ? (
          <div style={{ position: "absolute", left: 272 * k, bottom: (1080 - yOf(total) + 8) * k }}>
            <Rise at={12}>
              <span style={{ display: "block", fontFamily: MONO, fontWeight: 700, fontSize: 17 * k, letterSpacing: "0.2em",
                color: "rgba(255,255,255,.75)", whiteSpace: "nowrap" }}>{`FULL POOL · ${fmt(total)}${cap(tail(suffix))}`}</span>
            </Rise>
          </div>
        ) : null}
      </AbsoluteFill>
      <div style={{ position: "absolute", right: 90 * k, top: 86 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 8 * k }}>
        <Rise at={8}>
          <span style={{ display: "block", fontFamily: MONO, fontWeight: 700, fontSize: 20 * k, letterSpacing: "0.26em",
            color: CYAN, whiteSpace: "nowrap" }}>{cap(caption)}</span>
        </Rise>
        <Rise at={lvAt - 4} frames={12}>
          <Odometer value={value} at={lvAt} frames={lvF} size={128 * k} color="#fff" suffix={tail(suffix)} suffixScale={0.36}
            suffixColor={accent} prefix={str(overlay.prefix)} />
        </Rise>
        {hasFull ? (
          <div style={{ clipPath: `inset(0 0 0 ${((1 - chipP) * 100).toFixed(1)}%)`, background: RED, color: "#fff",
            fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.08em", lineHeight: 1,
            padding: `${9 * k}px ${18 * k}px ${7 * k}px`, borderRadius: 6 * k, whiteSpace: "nowrap",
            boxShadow: `0 ${10 * k}px ${26 * k}px rgba(0,0,0,.35)` }}>
            {`▼ ${fmt(total - value)}${cap(tail(suffix))} BELOW FULL`}
          </div>
        ) : null}
      </div>
      <div style={{ position: "absolute", left: 90 * k, top: 70 * k }}>
        <TitleBlock kicker={overlay.subtitle} title={overlay.text} accent={accent} size={58} chars={26} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. heat sun (tag)
/**
 * A tag for heat over the footage, top right: a sun pops in and turns its
 * rays (long and short, breathing), wobbling heat rings ripple out from it and
 * shift from gold to red as they fade. Beside it, right-aligned, a pulsing red
 * dot and the warning (subtitle), the temperature rolling (a bare number or
 * "degrees" gets a degree sign, "F" / "C" become °F / °C), a shimmering heat
 * line under it and the place (text). Only a local gradient darkens the
 * picture. Not a temperature -> nothing.
 */
const HeatSun: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const ex = useExit();
  const value = toNum(overlay.value);
  const rawSuf = str(overlay.suffix);
  const temp = !rawSuf || /°|^[fc]$|^deg|fahrenheit|celsius/i.test(rawSuf);
  if (!Number.isFinite(value) || !temp) return null;
  const t = frame / fps;
  const id = `schs${overlay.startFrame}`;
  const suffix = !rawSuf || /^deg/i.test(rawSuf) ? "°" : /^[fc]$/i.test(rawSuf) ? `°${rawSuf.toUpperCase()}`
    : /fahrenheit/i.test(rawSuf) ? "°F" : /celsius/i.test(rawSuf) ? "°C" : rawSuf;
  const SX = 1726, SY = 196;
  const sunIn = ramp(frame, 0, 16, backOut);
  const sunScale = Math.max(0, sunIn * (1 - 0.35 * ex));
  const ringsOn = ramp(frame, 10, 12) * (1 - ex);
  const RP = fps * 1.5;
  const rings = [0, 1, 2].map((j) => {
    const u = ((((frame - 10) / RP + j / 3) % 1) + 1) % 1;
    const r0 = 78 + (230 - 78) * u;
    const amp = 6 * (1 - u * 0.5);
    let d = "";
    for (let s = 0; s <= 48; s++) {
      const a = (s / 48) * Math.PI * 2;
      const r = r0 + amp * Math.sin(a * 7 + t * 3 + j * 2);
      d += `${s ? "L" : "M"}${(SX + r * Math.cos(a)).toFixed(1)} ${(SY + r * Math.sin(a)).toFixed(1)}`;
    }
    return { d: `${d} Z`, u };
  });
  const place = wrap(cap(str(overlay.text)), 24, 2);
  const kicker = cap(str(overlay.subtitle));
  const wave = ramp(frame, 14, 16, inOut) * (1 - ex);
  let waveD = "";
  for (let s = 0; s <= 40; s++) {
    const x = (s / 40) * 320;
    waveD += `${s ? "L" : "M"}${x.toFixed(1)} ${(8 + 5 * Math.sin(x / 22 - t * 6)).toFixed(1)}`;
  }
  const dot = 0.55 + 0.45 * Math.sin(t * 6);

  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 1000 * k, top: -80 * k, width: 1000 * k, height: 600 * k,
        opacity: ramp(frame, 0, 10) * (1 - ex),
        background: "radial-gradient(ellipse at 66% 44%, rgba(0,0,0,.55) 0%, rgba(0,0,0,.28) 45%, rgba(0,0,0,0) 72%)" }} />
      <svg width={width} height={height} viewBox={FULL} preserveAspectRatio="xMidYMid slice"
        style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <radialGradient id={`${id}d`} cx="40%" cy="38%" r="65%">
            <stop offset="0%" stopColor="#fff7df" /><stop offset="55%" stopColor={accent} />
            <stop offset="100%" stopColor={mixC(accent, RED, 0.45)} />
          </radialGradient>
          <radialGradient id={`${id}g`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={accent} stopOpacity={0.45} /><stop offset="100%" stopColor={accent} stopOpacity={0} />
          </radialGradient>
        </defs>
        {rings.map((r, j) => (
          <path key={j} d={r.d} fill="none" stroke={mixC(accent, RED, r.u)} strokeWidth={3}
            opacity={ringsOn * (1 - r.u) * 0.85 * Math.min(1, r.u / 0.08)} />
        ))}
        <g opacity={1 - ex} transform={`translate(${SX} ${SY}) scale(${sunScale.toFixed(4)}) translate(${-SX} ${-SY})`}>
          <circle cx={SX} cy={SY} r={120 + 6 * Math.sin(t * 2)} fill={`url(#${id}g)`} />
          <g transform={`rotate(${(t * 12).toFixed(2)} ${SX} ${SY})`}>
            {Array.from({ length: 16 }, (_, i) => {
              const a = (i / 16) * Math.PI * 2;
              const grow = ramp(frame, 4 + i * 0.6, 10);
              const r1 = 72;
              const r2 = r1 + (16 + (i % 2 ? 0 : 12) + 5 * Math.sin(t * 4 + i)) * grow;
              return <line key={i} x1={SX + r1 * Math.cos(a)} y1={SY + r1 * Math.sin(a)} x2={SX + r2 * Math.cos(a)}
                y2={SY + r2 * Math.sin(a)} stroke={accent} strokeWidth={6} strokeLinecap="round" opacity={grow > 0.02 ? 0.92 : 0} />;
            })}
          </g>
          <circle cx={SX} cy={SY} r={58} fill={`url(#${id}d)`} />
          <circle cx={SX} cy={SY} r={58} fill="none" stroke="#fff" strokeOpacity={0.35} strokeWidth={2.5} />
        </g>
      </svg>
      <div style={{ position: "absolute", right: (1920 - SX + 140) * k, top: 104 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 4 * k }}>
        {kicker ? (
          <Rise at={4}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k, whiteSpace: "nowrap" }}>
              <span style={{ width: 11 * k, height: 11 * k, borderRadius: "50%", background: RED, opacity: dot,
                boxShadow: `0 0 ${12 * k}px ${RED}` }} />
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.22em", color: "#fff",
                textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>{kicker}</span>
            </div>
          </Rise>
        ) : null}
        <Rise at={6} frames={12}>
          <Odometer value={value} at={8} frames={Math.round(fps * 1.1)} size={124 * k} color="#fff" suffix={suffix}
            suffixScale={0.5} suffixColor={accent} />
        </Rise>
        <svg width={320 * k} height={16 * k} viewBox="0 0 320 16" style={{ overflow: "visible",
          clipPath: `inset(0 0 0 ${((1 - wave) * 100).toFixed(1)}%)` }}>
          <defs>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={accent} stopOpacity={0} /><stop offset="40%" stopColor={accent} />
              <stop offset="100%" stopColor={RED} />
            </linearGradient>
          </defs>
          <path d={waveD} fill="none" stroke={`url(#${id}w)`} strokeWidth={3} strokeLinecap="round" />
        </svg>
        {place.map((ln, i) => (
          <LetterLine key={i} text={ln} at={12 + i * 3} step={0.6} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k,
            letterSpacing: "0.1em", color: "#fff", textAlign: "right", textShadow: "0 3px 12px rgba(0,0,0,.7)" }} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "sc-water-cycle": WaterCycle,
  "sc-aquifer-drop": AquiferDrop,
  "sc-pipe-flow": PipeFlow,
  "sc-molecule-orbit": MoleculeOrbit,
  "sc-cause-chain": CauseChain,
  "sc-reservoir-levels": ReservoirLevels,
  "sc-warming-stripes": WarmingStripes,
  "sc-rain-gauges": RainGauges,
  "sc-dam-level": DamLevel,
  "sc-heat-sun": HeatSun,
};
