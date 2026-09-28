import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, Scrim, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";

/**
 * Charts II (family "cb-"): ten data cards in the pro look. Every one starts
 * on the Scrim (footage darkened behind it, nothing when full frame), rises
 * its heading letter by letter, builds its geometry on expo / in-out curves,
 * holds with a slow push and one live detail, and drops its text out and
 * fades its geometry in the last ~12 frames.
 *
 *   cb-twin-lines     two smooth series drawing together behind a linked
 *                     scanner, the gap between them shaded, end values rolling
 *   cb-step-chart     a stepped line drawing; a flag unfurls (and waves) with
 *                     the value at every step, the change in a pill
 *   cb-range-bars     min-max bars growing out of their centre, the two end
 *                     values riding the dots outward
 *   cb-stream         a streamgraph: layered ribbons inflating one after the
 *                     other behind a playhead that reads out the year
 *   cb-donut-legend   a multi-slice ring swept clockwise by a comet, legend
 *                     rows rolling their values as their slice is reached
 *   cb-treemap        squarified tiles cut in by a glowing knife edge, the
 *                     biggest in the accent with a sheen
 *   cb-flow-split     one flow pouring left to right and splitting into
 *                     branches (sankey-lite), streaks running inside
 *   cb-scatter        bubbles flying out of the centre onto a 2D grid, a
 *                     ripple on landing, a trend line and a crosshair readout
 *   cb-slope          then / now columns, each item's line drawing across in
 *                     green (up) or red (down), a spark on the biggest mover
 *   cb-radar          a spider web drawing on, the value polygon springing
 *                     out to the values, a radar beam sweeping the web
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Num = OverlayItem & { value: number; suffix?: string; prefix?: string };
type Pt = [number, number];

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const accel = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
const GREYS = ["#f2f2f4", "#b9bbc3", "#8a8d97", "#62656f", "#474a53"];

// ------------------------------------------------------------------ data helpers
/** A text field as a string (a number is spelled out; anything else is ""). */
const str = (s: unknown): string =>
  typeof s === "string" ? s : typeof s === "number" && Number.isFinite(s) ? String(s) : "";
const cap = (s?: unknown): string => str(s).toUpperCase();
/** The items array, or an empty one when the field is missing or malformed. */
const arr = <T,>(v: T[] | undefined | null): T[] => (Array.isArray(v) ? v : []);
const fmt = (v: number): string => formatValue(v).text;
const f1 = (v: number): string => (Number.isFinite(v) ? v.toFixed(1) : "0");

/** Every number in a string: "12, 30; 8" -> [12, 30, 8]; "1,200" stays 1200. */
const numbersIn = (s: unknown): number[] => {
  if (typeof s === "number") return Number.isFinite(s) ? [s] : [];
  if (typeof s !== "string") return [];
  const out: number[] = [];
  for (const tok of s.split(/[;|]|,\s+|\s+/)) {
    const m = /[-−]?\d[\d,]*(?:\.\d+)?/.exec(tok);
    if (!m) continue;
    const v = Number(m[0].replace(/,/g, "").replace("−", "-"));
    if (Number.isFinite(v)) out.push(v);
  }
  return out;
};
const firstNum = (s: unknown): number => {
  const n = numbersIn(s);
  return n.length ? n[0] : NaN;
};
const toNum = (v: unknown): number =>
  typeof v === "number" ? (Number.isFinite(v) ? v : NaN) : typeof v === "string" ? firstNum(v) : NaN;

const nums = (items?: OverlayItem[]): Num[] => {
  const out: Num[] = [];
  for (const it of arr(items)) {
    if (!it || typeof it !== "object") continue;
    const v = toNum(it.value as unknown);
    if (!Number.isFinite(v)) continue;
    out.push({ ...(it as Num), label: str(it.label), value: v });
  }
  return out;
};

/** "Demand vs Supply", "A | B", "A, B" -> names. */
const splitNames = (s: unknown, commas: boolean): string[] =>
  str(s)
    .split(commas ? /\s+vs\.?\s+|\s*[|;,]\s*/i : /\s+vs\.?\s+|\s*[|;]\s*/i)
    .map((x) => x.trim())
    .filter(Boolean);

/** Odometer / text suffix: "%" and K/M/B/T tight, words after a space. */
const odoSuf = (s?: unknown): string => {
  const u = str(s).trim();
  return !u ? "" : /^(%|[KMBT])$/i.test(u) ? u : ` ${u}`;
};
const withUnit = (v: number, prefix?: unknown, suffix?: unknown): string => `${str(prefix)}${fmt(v)}${odoSuf(suffix)}`;
const digitCount = (vs: number[]): number => vs.reduce((a, v) => a + fmt(v).replace(/\D/g, "").length, 0);
const short = (v: number): string => {
  const a = Math.abs(v);
  const one = (x: number) => String(Math.round(x * 10) / 10);
  if (a >= 1e9) return `${one(v / 1e9)}B`;
  if (a >= 1e6) return `${one(v / 1e6)}M`;
  if (a >= 1e4) return `${one(v / 1e3)}K`;
  return formatValue(Math.round(v * 100) / 100).text;
};
/** The most balanced word wrap of `t` into at most `n` lines. */
const wrapInto = (t: string, n: number): string[] => {
  if (n <= 1) return [t];
  for (let c = Math.ceil(t.length / n); c <= t.length; c++) {
    const ls = lines(t, c);
    if (ls.length <= n) return ls;
  }
  return [t];
};
/**
 * A label wrapped into at most `maxLines` lines at the largest size (up to
 * `max`) whose longest line fits `width`; `em` is the face's average advance
 * per character, letter spacing included. Never below 85% of `min`.
 */
const fitText = (text: string, width: number, max: number, min: number, maxLines = 1, em = 0.56) => {
  const t = text.trim();
  let out = { ls: [t], size: max };
  for (let n = 1; n <= Math.max(1, maxLines); n++) {
    const ls = wrapInto(t, n);
    const longest = Math.max(1, ...ls.map((l) => l.length));
    out = { ls, size: Math.min(max, width / (longest * em)) };
    if (out.size >= min) return out;
  }
  return { ls: out.ls, size: Math.max(min * 0.85, out.size) };
};
/** Deterministic 0..1 from a seed (never Math.random). */
const rand = (seed: number): number => {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

// ------------------------------------------------------------------ scales
const niceStep = (span: number, n: number): number => {
  const raw = Math.abs(span) / Math.max(1, n);
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
};
type Scale = { min: number; max: number; ticks: number[] };
const niceScale = (lo: number, hi: number, n = 4): Scale => {
  let a = Number.isFinite(lo) ? lo : 0;
  let b = Number.isFinite(hi) ? hi : 1;
  if (b < a) {
    const s = a;
    a = b;
    b = s;
  }
  if (b - a < 1e-9) {
    const pad = Math.abs(a) * 0.1 || 1;
    a -= pad;
    b += pad;
  }
  const step = niceStep(b - a, n);
  const min = Math.floor(a / step + 1e-9) * step;
  let max = Math.ceil(b / step - 1e-9) * step;
  if (max <= min) max = min + step;
  const ticks: number[] = [];
  for (let i = 0; i <= 12; i++) {
    const v = min + i * step;
    if (v > max + step * 1e-6) break;
    ticks.push(Math.round(v / step) * step);
  }
  return { min, max, ticks };
};
const niceTop = (v: number): number => {
  if (!(v > 0)) return 1;
  const st = niceStep(v, 4);
  return Math.ceil(v / st - 1e-9) * st;
};

/** Monotone cubic (Fritsch-Carlson) through points with ascending x: no overshoot. */
const monotone = (xs: number[], ys: number[]): ((x: number) => number) => {
  const n = xs.length;
  if (n < 2) return () => (n ? ys[0] : 0);
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i] || 1));
  const m: number[] = new Array<number>(n).fill(0);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i], b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const tt = 3 / Math.sqrt(s);
      m[i] = tt * a * d[i];
      m[i + 1] = tt * b * d[i];
    }
  }
  return (x: number) => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 0;
    while (i < n - 2 && x > xs[i + 1]) i++;
    const h = xs[i + 1] - xs[i] || 1;
    const u = (x - xs[i]) / h;
    const u2 = u * u, u3 = u2 * u;
    return (2 * u3 - 3 * u2 + 1) * ys[i] + (u3 - 2 * u2 + u) * h * m[i] + (-2 * u3 + 3 * u2) * ys[i + 1] + (u3 - u2) * h * m[i + 1];
  };
};

/** A sampled curve as an SVG path ("M.. L.." or, continuing a shape, "L.. L.."). */
const curvePath = (f: (x: number) => number, x0: number, x1: number, steps: number, move = true): string => {
  let out = "";
  for (let s = 0; s <= steps; s++) {
    const x = x0 + ((x1 - x0) * s) / steps;
    out += `${s === 0 && move ? "M" : "L"}${f1(x)} ${f1(f(x))} `;
  }
  return out;
};

/** Push label centres apart to at least `gap`, kept inside lo..hi where possible. */
const spread = (ys: number[], gap: number, lo: number, hi: number): number[] => {
  const idx = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  const out = idx.map((o) => o.y);
  for (let j = 1; j < out.length; j++) if (out[j] - out[j - 1] < gap) out[j] = out[j - 1] + gap;
  if (out.length && out[out.length - 1] > hi) out[out.length - 1] = hi;
  for (let j = out.length - 2; j >= 0; j--) if (out[j + 1] - out[j] < gap) out[j] = out[j + 1] - gap;
  if (out.length && out[0] < lo) {
    const sh = lo - out[0];
    for (let j = 0; j < out.length; j++) out[j] += sh;
  }
  const res = new Array<number>(ys.length).fill(0);
  idx.forEach((o, j) => {
    res[o.i] = out[j];
  });
  return res;
};

/** The first frame at which an eased ramp from `at` over `n` frames reaches `target`. */
const frameWhen = (at: number, n: number, ease: (x: number) => number, target: number): number => {
  for (let f = 0; f <= n; f++) if (ease(f / Math.max(1, n)) >= target - 1e-6) return at + f;
  return at + n;
};

// ------------------------------------------------------------------ shared pieces
/** Seconds to frames; a short overlay (under 4 s) builds a little faster so it still holds. */
const useTiming = () => {
  const { fps, durationInFrames } = useVideoConfig();
  const sp = durationInFrames < 120 ? Math.max(0.72, durationInFrames / 120) : 1;
  return (sec: number): number => Math.max(1, Math.round(fps * sec * sp));
};

/** 0 -> 1 over the last 12 frames. */
const useExit = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - 12, 11, accel);
};

/** A line rising out of its mask at `at` and leaving upward through it at the end. */
const Rise: React.FC<{ at: number; children: React.ReactNode; style?: React.CSSProperties; outDelay?: number }> =
  ({ at, children, style, outDelay = 0 }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, 14);
    const pout = ramp(frame, durationInFrames - 14 + Math.min(3, Math.max(0, outDelay)), 9, accel);
    const y = (1 - pin) * 112 - pout * 112;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.06em", ...style }}>
        <div style={{ transform: `translateY(${y}%)`, opacity: pin < 0.01 || pout > 0.99 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** Scrim, centred, the slow push while it holds, and the exit (sink + fade). */
const Stage: React.FC<{ ov: Overlay; children: React.ReactNode }> = ({ ov, children }) => {
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  return (
    <AbsoluteFill>
      <Scrim ov={ov} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center",
          transform: `translateY(${exit * 26 * k}px) scale(${hold - exit * 0.035})`, opacity: 1 - exit }}>
          {children}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * The heading's lines for `width` (1080p px) of room: a title too long for one
 * line breaks into two smaller lines by words, and the kicker into two, so
 * neither can wrap mid-word (LetterLine's letters are inline blocks) or run
 * off the frame. `height` is its 1080p height, for looks that budget for it.
 */
const headLayout = (ov: Overlay, size: number, width: number) => {
  const title = cap(str(ov.text).trim());
  const kicker = cap(str(ov.subtitle).trim());
  const small = Math.max(44, Math.round(size * 0.86));
  const oneLine = title.length <= Math.floor(width / (size * 0.46));
  const ls = !title ? [] : oneLine ? [title] : lines(title, Math.max(10, Math.floor(width / (small * 0.46)))).slice(0, 2);
  const ks = kicker ? lines(kicker, Math.max(10, Math.floor(width / (26 * 0.74)))).slice(0, 2) : [];
  const height = ks.length * 37 + (ls.length === 1 ? size * 1.08 + 15 : ls.length * small * 1.08 + 15);
  return { ls, ks, small, height };
};

/** Kicker (subtitle) in the accent, then the chart heading, laid out by headLayout. */
const Head: React.FC<{ ov: Overlay; accent: string; center?: boolean; size?: number; width?: number }> =
  ({ ov, accent, center, size = 56, width = 1100 }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const exit = useExit();
    const { ls, ks, small } = headLayout(ov, size, width);
    if (!ls.length && !ks.length) return null;
    const align = center ? "center" : "flex-start";
    const textAlign = center ? "center" : "left";
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: align, gap: 6 * k, flexShrink: 0 }}>
        {ks.map((l, i) => (
          <LetterLine key={`k${i}`} text={l} at={i * 4} step={0.4} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
            letterSpacing: "0.3em", color: accent, lineHeight: 1.1, textAlign, whiteSpace: "nowrap" }} />
        ))}
        {ls.length === 1 ? (
          <Heading text={ls[0]} accent={accent} at={2} size={size} center={center} />
        ) : ls.length > 1 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: align }}>
            {ls.map((l, i) => (
              <LetterLine key={i} text={l} at={2 + i * 5} step={0.6} style={{ fontFamily: DISPLAY, fontSize: small * k,
                color: "#fff", letterSpacing: "0.04em", lineHeight: 1, textAlign, whiteSpace: "nowrap",
                textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
            ))}
            <div style={{ width: `${ramp(frame, 8, 16) * (1 - exit) * 110 * k}px`, height: 5 * k, background: accent,
              marginTop: 10 * k }} />
          </div>
        ) : null}
      </div>
    );
  };

/** The change first -> last in a green / red pill that pops in. */
const Chip: React.FC<{ from: number; to: number; at: number; size?: number }> = ({ from, to, at, size = 34 }) => {
  const frame = useCurrentFrame();
  const k = useK();
  if (!Number.isFinite(from) || !Number.isFinite(to) || from === 0) return null;
  const pct = ((to - from) / Math.abs(from)) * 100;
  const flat = Math.abs(pct) < 0.05;
  const down = pct < 0;
  const col = flat ? "#8a8d97" : down ? RED : GREEN;
  const p = ramp(frame, at, 14, backOut);
  const txt = `${Math.abs(pct) >= 10 ? Math.round(Math.abs(pct)) : Math.abs(pct).toFixed(1)}%`;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 8 * k, background: col, color: "#fff", fontFamily: LABEL,
      fontWeight: 800, fontSize: size * k, lineHeight: 1, letterSpacing: "0.04em", padding: `${9 * k}px ${22 * k}px ${7 * k}px`,
      borderRadius: 60 * k, boxShadow: `0 0 ${22 * k}px ${col}66`, transform: `scale(${p})`, opacity: Math.min(1, p * 2),
      whiteSpace: "nowrap" }}>
      <span style={{ fontSize: size * 0.6 * k }}>{flat ? "=" : down ? "▼" : "▲"}</span>
      <Rise at={at + 3}>{txt}</Rise>
    </div>
  );
};

// ================================================================== 1. twin lines
/** Two series (items[].value and items[].text) drawing together, the gap between them shaded. */
const TwinLines: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const rows = arr(overlay.items)
    .map((it) => ({ label: cap(it?.label), a: toNum(it?.value), b: firstNum(it?.text) }))
    .filter((r) => Number.isFinite(r.a) && Number.isFinite(r.b))
    .slice(0, 10);
  if (rows.length < 2) return null;
  const n = rows.length;
  const names = splitNames(overlay.label, true);
  const nameA = cap(names[0]), nameB = cap(names[1]);
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix);
  const W = 1080 * k, H = 430 * k, padT = 20 * k;
  const all = rows.flatMap((r) => [r.a, r.b]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const zero = lo >= 0 && lo <= hi * 0.5;
  const sc = niceScale(zero ? 0 : lo - (hi - lo) * 0.12, hi + (hi - lo) * 0.04, 4);
  const X = (i: number) => (i / (n - 1)) * W;
  const Y = (v: number) => padT + (1 - (v - sc.min) / (sc.max - sc.min)) * (H - padT);
  const xs = rows.map((_, i) => X(i));
  const fa = monotone(xs, rows.map((r) => Y(r.a)));
  const fb = monotone(xs, rows.map((r) => Y(r.b)));
  const pathA = curvePath(fa, 0, W, 96);
  const pathB = curvePath(fb, 0, W, 96);
  const band = `${pathA} ${curvePath(fb, W, 0, 96, false)} Z`;
  const drawAt = t(0.4), drawN = t(1.7);
  const d = ramp(frame, drawAt, drawN, inOut);
  const hx = d * W;
  const done = drawAt + drawN;
  const id = `cbtw${overlay.startFrame}`;
  const endA = fa(W), endB = fb(W);
  const [lyA, lyB] = spread([endA, endB], 104 * k, -10 * k, H + 10 * k);
  const cyc = t(1.3);
  const pulse = frame >= done ? ((frame - done) % cyc) / cyc : 0;
  const lastRow = rows[n - 1];
  const gap = Math.abs(lastRow.a - lastRow.b);
  const midY = (endA + endB) / 2;
  // The GAP readout sits between the lines at the right end (about W-200..W-40
  // across, midY-48..midY+42 down): shown only where both curves clear it.
  const away = (x: number) => Math.abs(fa(x) - midY) > 54 * k && Math.abs(fb(x) - midY) > 54 * k;
  const showGap = gap > 0 && Math.abs(endA - endB) > 130 * k && [40, 110, 180, 250].every((dx) => away(W - dx * k));
  const showBracket = gap > 0 && Math.abs(endA - endB) > 60 * k;
  const br = ramp(frame, done, t(0.45), inOut);
  const showX = (i: number) => n <= 7 || (n - 1 - i) % 2 === 0;
  const ends = [
    { y: endA, ly: lyA, col: accent, name: nameA, v: lastRow.a },
    { y: endB, ly: lyB, col: CYAN, name: nameB, v: lastRow.b },
  ];
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 40 * k, paddingLeft: 110 * k, paddingRight: 300 * k }}>
        <Head ov={overlay} accent={accent} width={1080} />
        <div style={{ position: "relative", width: W, height: H + 60 * k }}>
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <clipPath id={`${id}c`}>
                <rect x={-30 * k} y={-80 * k} width={Math.max(0, hx + 30 * k)} height={H + 160 * k} />
              </clipPath>
              <linearGradient id={`${id}g`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#ffffff" stopOpacity={0.02} />
                <stop offset="100%" stopColor="#ffffff" stopOpacity={0.13} />
              </linearGradient>
            </defs>
            {sc.ticks.map((g, i) => (
              <line key={`g${i}`} x1={0} x2={W * ramp(frame, 2 + i * 2, 18, inOut)} y1={Y(g)} y2={Y(g)}
                stroke="rgba(255,255,255,.12)" strokeWidth={1.5 * k} strokeDasharray={`${6 * k} ${8 * k}`} />
            ))}
            <line x1={0} x2={W * ramp(frame, 0, 18, inOut)} y1={H} y2={H} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
            <g clipPath={`url(#${id}c)`}>
              <path d={band} fill={`url(#${id}g)`} />
              <path d={pathB} fill="none" stroke={CYAN} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round" />
              <path d={pathA} fill="none" stroke={accent} strokeWidth={7 * k} strokeLinecap="round" strokeLinejoin="round"
                style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}99)` }} />
            </g>
            {rows.map((r, i) => {
              const q = interpolate(hx - X(i), [-1, 24 * k], [0, 1], clamp);
              if (q <= 0 || i === n - 1) return null;
              return (
                <g key={`p${i}`}>
                  <circle cx={X(i)} cy={Y(r.a)} r={6.5 * k * q} fill={INK} stroke={accent} strokeWidth={3 * k} />
                  <circle cx={X(i)} cy={Y(r.b)} r={6 * k * q} fill={INK} stroke={CYAN} strokeWidth={3 * k} />
                </g>
              );
            })}
            {d > 0 && d < 1 ? (
              <g>
                <line x1={hx} x2={hx} y1={fa(hx)} y2={fb(hx)} stroke="rgba(255,255,255,.5)" strokeWidth={2 * k}
                  strokeDasharray={`${4 * k} ${5 * k}`} />
                <circle cx={hx} cy={fa(hx)} r={21 * k} fill={accent} fillOpacity={0.26} />
                <circle cx={hx} cy={fb(hx)} r={18 * k} fill={CYAN} fillOpacity={0.22} />
                <circle cx={hx} cy={fa(hx)} r={10 * k} fill="#fff" />
                <circle cx={hx} cy={fb(hx)} r={9 * k} fill="#fff" />
              </g>
            ) : null}
            {showBracket && br > 0 ? (
              <line x1={W - 18 * k} x2={W - 18 * k} y1={midY + (endA - midY) * br} y2={midY + (endB - midY) * br}
                stroke="rgba(255,255,255,.8)" strokeWidth={2.5 * k} strokeDasharray={`${5 * k} ${5 * k}`} />
            ) : null}
            {frame >= done - 2 ? ends.map((e, i) => (
              <g key={`d${i}`}>
                <path d={`M${f1(W + 14 * k)} ${f1(e.y)} L${f1(W + 34 * k)} ${f1(e.ly)}`} stroke={e.col} strokeWidth={2 * k}
                  opacity={ramp(frame, done, 10)} fill="none" />
                <circle cx={W} cy={e.y} r={(12 + 24 * pulse) * k} fill="none" stroke={e.col} strokeWidth={3 * k}
                  opacity={(1 - pulse) * 0.9} />
                <circle cx={W} cy={e.y} r={10 * k} fill={e.col} stroke={INK} strokeWidth={3 * k} />
              </g>
            )) : null}
          </svg>
          {sc.ticks.map((g, i) => (
            <Rise key={`y${i}`} at={2 + i * 2} style={{ position: "absolute", left: -110 * k, width: 90 * k, top: Y(g) - 17 * k,
              textAlign: "right", fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, color: "rgba(255,255,255,.55)" }}>
              {short(g)}{suffix.trim() === "%" ? "%" : ""}
            </Rise>
          ))}
          {rows.map((r, i) => (showX(i) ? (
            <Rise key={`x${i}`} at={frameWhen(drawAt, drawN, inOut, i / (n - 1))} style={{ position: "absolute",
              left: X(i) - 90 * k, width: 180 * k, top: H + 16 * k, textAlign: "center", fontFamily: LABEL, fontWeight: 700,
              fontSize: 28 * k, letterSpacing: "0.08em", color: "rgba(255,255,255,.8)", whiteSpace: "nowrap" }}>{r.label}</Rise>
          ) : null))}
          {ends.map((e, i) => (
            <div key={`e${i}`} style={{ position: "absolute", left: W + 40 * k, top: e.ly - (e.name ? 50 : 34) * k,
              display: "flex", flexDirection: "column", gap: 2 * k }}>
              {e.name ? (
                <Rise at={done - 6 + i * 3} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.16em",
                  color: e.col, whiteSpace: "nowrap" }}>{e.name}</Rise>
              ) : null}
              <Rise at={done - 8 + i * 3}>
                <Odometer value={e.v} at={done - 8 + i * 3} frames={t(0.9)} size={66 * k} color="#fff" prefix={prefix}
                  suffix={odoSuf(suffix)} suffixScale={0.5} suffixColor={e.col} />
              </Rise>
            </div>
          ))}
          {showGap ? (
            <div style={{ position: "absolute", left: W - 340 * k, width: 300 * k, top: midY - 44 * k, textAlign: "right" }}>
              <Rise at={done + 4} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.24em",
                color: "rgba(255,255,255,.6)" }}>GAP</Rise>
              <Rise at={done + 7} style={{ fontFamily: DISPLAY, fontSize: 52 * k, color: "#fff", lineHeight: 1,
                whiteSpace: "nowrap" }}>{withUnit(gap, prefix, suffix)}</Rise>
            </div>
          ) : null}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 2. step chart
/** A stepped line drawing; at every step a flag pole rises and a value flag unfurls and waves. */
const StepChart: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const t = useTiming();
  const pts = nums(overlay.items).slice(0, 7);
  if (pts.length < 2) return null;
  const n = pts.length;
  const last = pts[n - 1];
  const prefix = str(overlay.prefix) || str(last.prefix);
  const unitTxt = (str(overlay.suffix) || str(last.suffix)).trim();
  const W = 1240 * k, H = 480 * k, padT = 160 * k;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const zero = lo >= 0 && lo <= hi * 0.5;
  const sc = niceScale(zero ? 0 : lo - (hi - lo) * 0.3, hi, 3);
  const Y = (v: number) => padT + (1 - (v - sc.min) / (sc.max - sc.min)) * (H - padT);
  const sw = W / n;
  type Seg = { x0: number; y0: number; x1: number; y1: number; len: number; c0: number };
  const segs: Seg[] = [];
  const stepStart: number[] = [];
  let cum = 0;
  for (let i = 0; i < n; i++) {
    const y = Y(pts[i].value);
    stepStart.push(cum);
    segs.push({ x0: i * sw, y0: y, x1: (i + 1) * sw, y1: y, len: sw, c0: cum });
    cum += sw;
    if (i < n - 1) {
      const y2 = Y(pts[i + 1].value);
      const l = Math.abs(y2 - y);
      if (l > 0.01) {
        segs.push({ x0: (i + 1) * sw, y0: y, x1: (i + 1) * sw, y1: y2, len: l, c0: cum });
        cum += l;
      }
    }
  }
  const total = Math.max(1, cum);
  const path = `M0 ${f1(segs[0].y0)} ` + segs.map((s) => `L${f1(s.x1)} ${f1(s.y1)}`).join(" ");
  const area = `${path} L${f1(W)} ${f1(H)} L0 ${f1(H)} Z`;
  const drawAt = t(0.35), drawN = t(0.55 + 0.2 * n);
  const d = ramp(frame, drawAt, drawN, inOut);
  const run = d * total;
  let hx = 0, hy = segs[0].y0;
  for (const s of segs) {
    if (run <= s.c0 + s.len) {
      const f = s.len ? Math.max(0, run - s.c0) / s.len : 1;
      hx = s.x0 + (s.x1 - s.x0) * f;
      hy = s.y0 + (s.y1 - s.y0) * f;
      break;
    }
    hx = s.x1;
    hy = s.y1;
  }
  const done = drawAt + drawN;
  const flagAt = stepStart.map((c) => frameWhen(drawAt, drawN, inOut, Math.min(1, (c + 24 * k) / total)));
  const fw = Math.min(sw - 48 * k, 180 * k), fh = 56 * k, poleH = 104 * k;
  const id = `cbst${overlay.startFrame}`;
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 24 * k, paddingLeft: 100 * k }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", width: W, gap: 30 * k }}>
          <Head ov={overlay} accent={accent} width={1040} />
          <Chip from={pts[0].value} to={last.value} at={done} />
        </div>
        <div style={{ position: "relative", width: W, height: H + 56 * k }}>
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accent} stopOpacity={0.34} />
                <stop offset="100%" stopColor={accent} stopOpacity={0.02} />
              </linearGradient>
              <clipPath id={`${id}c`}><rect x={0} y={0} width={Math.max(0, hx)} height={H + 4 * k} /></clipPath>
            </defs>
            {sc.ticks.map((g, i) => (
              <line key={`g${i}`} x1={0} x2={W * ramp(frame, 2 + i * 2, 18, inOut)} y1={Y(g)} y2={Y(g)}
                stroke="rgba(255,255,255,.12)" strokeWidth={1.5 * k} strokeDasharray={`${6 * k} ${8 * k}`} />
            ))}
            {pts.map((_, i) => (i > 0 ? (
              <line key={`s${i}`} x1={i * sw} x2={i * sw} y1={H} y2={H - 14 * k} stroke="rgba(255,255,255,.5)"
                strokeWidth={2 * k} opacity={ramp(frame, 4 + i * 2, 10)} />
            ) : null))}
            <line x1={0} x2={W * ramp(frame, 0, 18, inOut)} y1={H} y2={H} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
            <path d={area} fill={`url(#${id}g)`} clipPath={`url(#${id}c)`} />
            <path d={path} fill="none" stroke={accent} strokeWidth={6 * k} strokeLinejoin="round" strokeLinecap="round"
              strokeDasharray={`${total} ${total}`} strokeDashoffset={total * (1 - d)} opacity={d > 0 ? 1 : 0}
              style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}99)` }} />
            {d > 0 && d < 1 ? <circle cx={hx} cy={hy} r={10 * k} fill="#fff" /> : null}
          </svg>
          {sc.ticks.map((g, i) => (
            <Rise key={`y${i}`} at={2 + i * 2} style={{ position: "absolute", left: -100 * k, width: 82 * k, top: Y(g) - 17 * k,
              textAlign: "right", fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, color: "rgba(255,255,255,.55)" }}>
              {prefix}{short(g)}{unitTxt === "%" ? "%" : ""}
            </Rise>
          ))}
          {pts.map((p, i) => {
            const a0 = flagAt[i];
            const pole = ramp(frame, a0, 10);
            const unf = ramp(frame, a0 + 5, 16, backOut);
            const settle = ramp(frame, a0 + 12, 24);
            const wave = Math.sin(((frame + i * 9) / fps) * Math.PI * 2 * 0.55) * 2.2 * settle;
            const y = Y(p.value);
            const px = i * sw + 22 * k;
            const hot = i === n - 1;
            const txt = `${str(p.prefix) || prefix}${fmt(p.value)}`;
            const len = txt.length + (unitTxt ? unitTxt.length * 0.6 + 0.5 : 0);
            const fs = Math.max(20 * k, Math.min(40 * k, (fw - 44 * k) / (len * 0.44)));
            return (
              <React.Fragment key={`f${i}`}>
                <div style={{ position: "absolute", left: px - 1.5 * k, top: y - poleH * pole, width: 3 * k, height: poleH * pole,
                  background: "rgba(255,255,255,.85)" }} />
                <div style={{ position: "absolute", left: px - 6 * k, top: y - 6 * k, width: 12 * k, height: 12 * k,
                  borderRadius: "50%", background: hot ? accent : "#fff", transform: `scale(${ramp(frame, a0, 10, backOut)})` }} />
                <div style={{ position: "absolute", left: px, top: y - poleH, width: fw, height: fh, transformOrigin: "0% 50%",
                  transform: `scaleX(${unf}) skewY(${wave}deg)`, opacity: unf > 0.01 ? 1 : 0,
                  background: hot ? accent : "#f4f4f6", clipPath: "polygon(0 0, 100% 0, 90% 50%, 100% 100%, 0 100%)",
                  display: "flex", alignItems: "center", paddingLeft: 14 * k, boxSizing: "border-box" }}>
                  <Rise at={a0 + 9} style={{ fontFamily: DISPLAY, fontSize: fs, color: INK, lineHeight: 1, whiteSpace: "nowrap" }}>
                    {txt}{unitTxt ? <span style={{ fontSize: fs * 0.6, marginLeft: 4 * k }}>{unitTxt}</span> : null}
                  </Rise>
                </div>
                <Rise at={a0 + 2} style={{ position: "absolute", left: i * sw, width: sw, top: H + 14 * k, textAlign: "center",
                  fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.08em",
                  color: hot ? accent : "rgba(255,255,255,.8)", whiteSpace: "nowrap" }}>{cap(p.label)}</Rise>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 3. range bars
/** Min-max ranges (value = min, text = max): bars grow out of their centre, the end values riding the dots. */
const RangeBars: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const rows = arr(overlay.items)
    .map((it) => {
      const a = toNum(it?.value), b = firstNum(it?.text);
      return { label: cap(it?.label), lo: Math.min(a, b), hi: Math.max(a, b) };
    })
    .filter((r) => Number.isFinite(r.lo) && Number.isFinite(r.hi))
    .slice(0, 6);
  if (!rows.length) return null;
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix).trim();
  const allLo = Math.min(...rows.map((r) => r.lo)), allHi = Math.max(...rows.map((r) => r.hi));
  const zero = allLo >= 0 && allLo <= allHi * 0.4;
  const sc = niceScale(zero ? 0 : allLo - (allHi - allLo) * 0.1, allHi, 5);
  const LW = 290 * k, GAP = 44 * k, TW = 980 * k;
  const RH = (rows.length > 4 ? 88 : 104) * k;
  const axisH = 50 * k, bodyH = rows.length * RH;
  const BH = 14 * k;
  const X = (v: number) => ((v - sc.min) / (sc.max - sc.min)) * TW;
  const widest = rows.reduce((m, r, i) => (r.hi - r.lo > rows[m].hi - rows[m].lo ? i : m), 0);
  const decimals = rows.some((r) => !Number.isInteger(r.lo) || !Number.isInteger(r.hi));
  const show = (v: number) => withUnit(decimals ? Math.round(v * 10) / 10 : Math.round(v), prefix, suffix);
  const grid = ramp(frame, 2, t(0.8), inOut);
  const cyc = t(1.2);
  const id = `cbrb${overlay.startFrame}`;
  const geo = rows.map((r, i) => {
    const at = t(0.35) + i * t(0.14);
    const g = ramp(frame, at + 4, t(0.85), inOut);
    const xm = (X(r.lo) + X(r.hi)) / 2;
    const x1 = xm + (X(r.lo) - xm) * g, x2 = xm + (X(r.hi) - xm) * g;
    const vm = (r.lo + r.hi) / 2;
    const yc = i * RH + RH * 0.64;
    const dot = ramp(frame, at + 2, 12, backOut);
    return { at, g, x1, x2, vm, yc, dot, doneAt: at + 4 + t(0.85) };
  });
  const lastTick = sc.ticks.length - 1;
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 28 * k, width: LW + GAP + TW + 120 * k }}>
        <Head ov={overlay} accent={accent} width={1400} />
        <div style={{ position: "relative", height: axisH + bodyH }}>
          {sc.ticks.map((g, i) => (
            <Rise key={`t${i}`} at={2 + i * 2} style={{ position: "absolute", left: LW + GAP + X(g) - 80 * k, width: 160 * k, top: 0,
              textAlign: "center", fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, color: "rgba(255,255,255,.55)",
              whiteSpace: "nowrap" }}>
              {prefix}{short(g)}{suffix === "%" ? "%" : i === lastTick ? odoSuf(suffix) : ""}
            </Rise>
          ))}
          <svg width={TW} height={bodyH} style={{ position: "absolute", left: LW + GAP, top: axisH, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}g`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#ffffff" stopOpacity={0.55} />
                <stop offset="100%" stopColor={accent} stopOpacity={1} />
              </linearGradient>
            </defs>
            {sc.ticks.map((g, i) => (
              <line key={`g${i}`} x1={X(g)} x2={X(g)} y1={0} y2={bodyH * grid} stroke="rgba(255,255,255,.1)" strokeWidth={1.5 * k}
                strokeDasharray={`${5 * k} ${7 * k}`} />
            ))}
            {geo.map((q, i) => {
              const hot = i === widest;
              const pulse = hot && frame > q.doneAt ? ((frame - q.doneAt) % cyc) / cyc : -1;
              return (
                <g key={`r${i}`}>
                  <line x1={0} x2={TW * ramp(frame, q.at - 4, t(0.6), inOut)} y1={q.yc} y2={q.yc} stroke="rgba(255,255,255,.12)"
                    strokeWidth={2 * k} />
                  {q.g > 0 ? (
                    <rect x={q.x1} y={q.yc - BH / 2} width={Math.max(0.5, q.x2 - q.x1)} height={BH} rx={BH / 2}
                      fill={`url(#${id}g)`} />
                  ) : null}
                  {pulse >= 0 ? (
                    <circle cx={q.x2} cy={q.yc} r={(14 + 22 * pulse) * k} fill="none" stroke={accent} strokeWidth={3 * k}
                      opacity={1 - pulse} />
                  ) : null}
                  <circle cx={q.x1} cy={q.yc} r={11 * k * q.dot} fill={INK} stroke="#fff" strokeWidth={4 * k} />
                  <circle cx={q.x2} cy={q.yc} r={13 * k * q.dot} fill={accent} stroke={INK} strokeWidth={3 * k} />
                </g>
              );
            })}
          </svg>
          {rows.map((r, i) => {
            const q = geo[i];
            const y = axisH + q.yc;
            const hot = i === widest;
            // Long names take two lines rather than shrinking below the label size.
            const lab = fitText(r.label, LW, 34 * k, 24 * k, 2, 0.58);
            const blockH = lab.ls.length * lab.size * 1.11;
            return (
              <React.Fragment key={`l${i}`}>
                <div style={{ position: "absolute", left: 0, width: LW, top: y - blockH / 2 + 1 * k }}>
                  {lab.ls.map((l, j) => (
                    <Rise key={`n${j}`} at={q.at + j * 2} style={{ textAlign: "right", fontFamily: LABEL, fontWeight: 800,
                      fontSize: lab.size, letterSpacing: "0.06em", lineHeight: 1.05, color: hot ? accent : "#fff",
                      whiteSpace: "nowrap" }}>{l}</Rise>
                  ))}
                </div>
                <Rise at={q.at + 6} style={{ position: "absolute", left: LW + GAP + q.x1 - 228 * k, width: 216 * k, top: y - 62 * k,
                  textAlign: "right", fontFamily: DISPLAY, fontSize: 36 * k, color: "rgba(255,255,255,.72)", lineHeight: 1.05,
                  fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{show(q.vm + (r.lo - q.vm) * q.g)}</Rise>
                <Rise at={q.at + 6} style={{ position: "absolute", left: LW + GAP + q.x2 + 12 * k, width: 216 * k, top: y - 64 * k,
                  textAlign: "left", fontFamily: DISPLAY, fontSize: 40 * k, color: hot ? accent : "#fff", lineHeight: 1.05,
                  fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{show(q.vm + (r.hi - q.vm) * q.g)}</Rise>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 4. stacked stream
/**
 * A streamgraph: items are the years (label), each with its layer values
 * (value, then the numbers in text); layer names from label ("Farms, Cities").
 */
const Stream: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const cols = arr(overlay.items)
    .map((it) => {
      const head = toNum(it?.value);
      const rest = numbersIn(it?.text);
      const v = Number.isFinite(head) ? [head, ...rest] : rest;
      return { label: cap(it?.label), v: v.map((x) => Math.max(0, x)) };
    })
    .filter((c) => c.v.length > 0)
    .slice(0, 10);
  if (cols.length < 3) return null;
  const n = cols.length;
  const L = Math.max(1, Math.min(5, Math.max(...cols.map((c) => c.v.length))));
  const vals = cols.map((c) => Array.from({ length: L }, (_, j) => (j < c.v.length && Number.isFinite(c.v[j]) ? c.v[j] : 0)));
  const totals = vals.map((r) => r.reduce((a, b) => a + b, 0));
  const maxT = Math.max(...totals);
  if (!(maxT > 0)) return null;
  const names = splitNames(overlay.label, true);
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix);
  const W = 1200 * k, H = 460 * k, cy = H / 2;
  // Layer names sit under their values, fitted to the 228px the right margin keeps for them.
  const nameOf = Array.from({ length: L }, (_, j) => {
    const s = (lines(cap(names[j]), 22)[0] || "").trim();
    return s ? { text: s, size: fitText(s, 228 * k, 24 * k, 20 * k, 1, 0.6).size } : null;
  });
  const named = nameOf.some(Boolean);
  const unit = (H * 0.86) / maxT;
  const X = (i: number) => (i / (n - 1)) * W;
  const xs = cols.map((_, i) => X(i));
  const thF = Array.from({ length: L }, (_, j) => monotone(xs, vals.map((r) => r[j] * unit)));
  const growAt = t(0.3);
  const g = Array.from({ length: L }, (_, j) => ramp(frame, growAt + j * t(0.16), t(0.9), backOut));
  const S = 64;
  const edges: Pt[][] = Array.from({ length: L + 1 }, () => [] as Pt[]);
  for (let s = 0; s <= S; s++) {
    const x = (W * s) / S;
    const th = thF.map((f, j) => Math.max(0, f(x)) * g[j]);
    const T = th.reduce((a, b) => a + b, 0);
    let y = cy - T / 2;
    for (let j = 0; j <= L; j++) {
      edges[j].push([x, y]);
      if (j < L) y += th[j];
    }
  }
  const trace = (p: Pt[], move: boolean) => p.map((q, i) => `${i === 0 && move ? "M" : "L"}${f1(q[0])} ${f1(q[1])}`).join(" ");
  const layer = (j: number) => `${trace(edges[j], true)} ${trace(edges[j + 1].slice().reverse(), false)} Z`;
  const lastV = vals[n - 1];
  const hero = lastV.reduce((m, v, j) => (v > lastV[m] ? j : m), 0);
  let gi = 0;
  const colors = lastV.map((_, j) => (j === hero ? accent : GREYS[gi++ % GREYS.length]));
  const Tn = lastV.reduce((a, b) => a + b, 0) * unit;
  let yy = cy - Tn / 2;
  const endMid = lastV.map((v) => {
    const m = yy + (v * unit) / 2;
    yy += v * unit;
    return m;
  });
  const endY = spread(endMid, (named ? 76 : 50) * k, 12 * k, H - (named ? 22 : 12) * k);
  const sweepAt = t(0.25), sweepN = t(1.7);
  const sweep = ramp(frame, sweepAt, sweepN, inOut);
  const px = sweep * W;
  const ph = interpolate(sweep, [0, 0.03, 0.95, 1], [0, 1, 1, 0], clamp);
  // The year readout wipes open from its centre and shuts again as the playhead parks.
  const tagP = ramp(frame, sweepAt, 10) * (1 - ramp(frame, sweepAt + sweepN - 10, 9, accel));
  const cur = cols[Math.max(0, Math.min(n - 1, Math.round(sweep * (n - 1))))].label;
  const endAt = sweepAt + sweepN - 6;
  const lead = ramp(frame, endAt, 12);
  const id = `cbsa${overlay.startFrame}`;
  const showX = (i: number) => n <= 7 || (n - 1 - i) % 2 === 0;
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 84 * k, paddingRight: 290 * k }}>
        <Head ov={overlay} accent={accent} width={1200} />
        <div style={{ position: "relative", width: W, height: H + 56 * k }}>
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <clipPath id={`${id}c`}>
                <rect x={-4 * k} y={-80 * k} width={Math.max(0, px + 4 * k)} height={H + 160 * k} />
              </clipPath>
            </defs>
            {xs.map((x, i) => (
              <line key={`v${i}`} x1={x} x2={x} y1={0} y2={H} stroke="rgba(255,255,255,.07)" strokeWidth={1.5 * k}
                opacity={ramp(frame, 2 + i, 12)} />
            ))}
            <line x1={0} x2={W * ramp(frame, 0, t(0.6), inOut)} y1={cy} y2={cy} stroke="rgba(255,255,255,.2)"
              strokeWidth={1.5 * k} strokeDasharray={`${6 * k} ${8 * k}`} />
            <g clipPath={`url(#${id}c)`}>
              {colors.map((c, j) => (
                <path key={`l${j}`} d={layer(j)} fill={c} fillOpacity={j === hero ? 0.96 : 0.86} stroke={INK}
                  strokeWidth={2 * k} strokeLinejoin="round" />
              ))}
            </g>
            {ph > 0 ? (
              <line x1={px} x2={px} y1={-28 * k} y2={H + 6 * k} stroke="#fff" strokeWidth={2.5 * k} opacity={ph}
                style={{ filter: `drop-shadow(0 0 ${8 * k}px #ffffff)` }} />
            ) : null}
            {lead > 0 ? endY.map((y, j) => (lastV[j] > 0 ? (
              <path key={`k${j}`} d={`M${f1(W + 6 * k)} ${f1((edges[j][S][1] + edges[j + 1][S][1]) / 2)} L${f1(W + 26 * k)} ${f1(y)}`}
                stroke="rgba(255,255,255,.45)" strokeWidth={1.5 * k} fill="none" opacity={lead} />
            ) : null)) : null}
          </svg>
          {tagP > 0.001 ? (
            <div style={{ position: "absolute", left: px - 90 * k, width: 180 * k, top: -74 * k, display: "flex",
              justifyContent: "center" }}>
              <div style={{ background: accent, color: INK, fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
                padding: `${5 * k}px ${12 * k}px`, borderRadius: 4 * k, letterSpacing: "0.04em", whiteSpace: "nowrap",
                clipPath: `inset(0 ${(1 - tagP) * 50}% 0 ${(1 - tagP) * 50}% round ${4 * k}px)` }}>{cur}</div>
            </div>
          ) : null}
          {cols.map((c, i) => (showX(i) ? (
            <Rise key={`x${i}`} at={frameWhen(sweepAt, sweepN, inOut, i / (n - 1))} style={{ position: "absolute",
              left: X(i) - 90 * k, width: 180 * k, top: H + 14 * k, textAlign: "center", fontFamily: LABEL, fontWeight: 700,
              fontSize: 28 * k, letterSpacing: "0.08em", color: "rgba(255,255,255,.8)", whiteSpace: "nowrap" }}>{c.label}</Rise>
          ) : null))}
          {endY.map((y, j) => {
            if (!(lastV[j] > 0)) return null;
            const nm = nameOf[j];
            return (
              <div key={`e${j}`} style={{ position: "absolute", left: W + 34 * k, top: y - 22 * k, display: "flex",
                alignItems: "flex-start", gap: 12 * k }}>
                <div style={{ width: 14 * k, height: 14 * k, borderRadius: 3 * k, background: colors[j], flexShrink: 0,
                  marginTop: 15 * k, transform: `scale(${ramp(frame, endAt + j * 3, 12, backOut)})` }} />
                <div style={{ display: "flex", flexDirection: "column" }}>
                  <Rise at={endAt + j * 3} style={{ fontFamily: DISPLAY, fontSize: 42 * k, color: j === hero ? accent : "#fff",
                    lineHeight: 1.05, whiteSpace: "nowrap" }}>{withUnit(lastV[j], prefix, suffix)}</Rise>
                  {nm ? (
                    <Rise at={endAt + j * 3 + 2} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: nm.size,
                      letterSpacing: "0.12em", lineHeight: 1.15, color: "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>
                      {nm.text}
                    </Rise>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 5. donut + legend
/** A multi-slice ring swept clockwise by a comet; the legend rows roll their values as their slice is reached. */
const DonutLegend: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const items = nums(overlay.items).filter((i) => i.value > 0).slice(0, 6);
  if (items.length < 2) return null;
  const sum = items.reduce((a, i) => a + i.value, 0);
  const hero = items.reduce((m, it, i) => (it.value > items[m].value ? i : m), 0);
  let gi = 0;
  const cols = items.map((_, i) => (i === hero ? accent : GREYS[gi++ % GREYS.length]));
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix);
  const pctUnit = suffix.trim() === "%";
  // Percentages are already shares of 100: the ring is 100 (a remainder stays
  // an empty track) and the centre shows the leader's own figure, so the ring,
  // the centre and the legend always agree. Other units are shares of the sum.
  const ringTotal = pctUnit && sum <= 100.5 ? 100 : sum;
  const R = 190 * k, S = 62 * k, B = 2 * R + S + 110 * k, cx = B / 2, cy = B / 2;
  const C = 2 * Math.PI * R;
  const gapPx = 6 * k;
  const gapDeg = (gapPx / C) * 360;
  const sweepAt = t(0.3), sweepN = t(1.5);
  const sw = ramp(frame, sweepAt, sweepN, inOut);
  const done = sweepAt + sweepN;
  const pop = ramp(frame, done + 2, 16, backOut);
  let acc = 0;
  const arcs = items.map((it) => {
    const s0 = acc / ringTotal;
    acc += it.value;
    return { s0, len: it.value / ringTotal };
  });
  const rowAt = arcs.map((a) => frameWhen(sweepAt, sweepN, inOut, a.s0 + 0.002));
  const heroShare = pctUnit ? items[hero].value : (items[hero].value / sum) * 100;
  const heroPct = heroShare >= 10 ? Math.round(heroShare) : Math.round(heroShare * 10) / 10;
  const roll = digitCount(items.map((i) => i.value)) <= 14;
  const LCW = 700 * k;
  const valW = Math.max(...items.map((it) => (str(it.prefix) || prefix).length + fmt(it.value).length)) * 0.42 * 54 * k
    + odoSuf(suffix).length * 0.42 * 27 * k + 8 * k;
  const labAvail = Math.max(160 * k, LCW - 56 * k - valW);
  const cAt = sweepAt + Math.round(sweepN * 0.45);
  const dialR = R + S / 2 + 24 * k;
  const dialC = 2 * Math.PI * dialR;
  const innerR = R - S / 2 - 16 * k;
  const innerC = 2 * Math.PI * innerR;
  const ca = sw * Math.PI * 2 - Math.PI / 2;
  const rowH = (items.length > 4 ? 76 : 88) * k;
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", alignItems: "center", gap: 80 * k }}>
        <div style={{ position: "relative", width: B, height: B }}>
          <svg width={B} height={B} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <circle cx={cx} cy={cy} r={dialR} fill="none" stroke="rgba(255,255,255,.24)" strokeWidth={10 * k}
              strokeDasharray={`${2 * k} ${dialC / 90 - 2 * k}`} transform={`rotate(${frame * 0.12} ${cx} ${cy})`}
              opacity={ramp(frame, 0, 14)} />
            <circle cx={cx} cy={cy} r={R} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth={S} opacity={ramp(frame, 0, 10)} />
            {arcs.map((a, i) => {
              const vis = Math.max(0, Math.min(a.len, sw - a.s0));
              const len = vis * C - gapPx;
              if (len <= 0) return null;
              const isHero = i === hero;
              const mid = (a.s0 + a.len / 2) * Math.PI * 2 - Math.PI / 2;
              const off = isHero ? pop * 16 * k : 0;
              return (
                <circle key={`a${i}`} cx={cx} cy={cy} r={R} fill="none" stroke={cols[i]} strokeWidth={S + (isHero ? pop * 10 * k : 0)}
                  strokeDasharray={`${len} ${C}`}
                  transform={`translate(${f1(Math.cos(mid) * off)} ${f1(Math.sin(mid) * off)}) rotate(${a.s0 * 360 - 90 + gapDeg / 2} ${cx} ${cy})`}
                  style={isHero ? { filter: `drop-shadow(0 0 ${16 * k}px ${accent}77)` } : undefined} />
              );
            })}
            <circle cx={cx} cy={cy} r={innerR} fill="none" stroke="rgba(255,255,255,.22)" strokeWidth={2 * k}
              strokeDasharray={`${sw * innerC} ${innerC}`} transform={`rotate(-90 ${cx} ${cy})`} />
            {sw > 0.001 && sw < 0.999 ? (
              <g>
                <circle cx={cx + Math.cos(ca) * R} cy={cy + Math.sin(ca) * R} r={24 * k} fill="#fff" fillOpacity={0.16} />
                <circle cx={cx + Math.cos(ca) * R} cy={cy + Math.sin(ca) * R} r={10 * k} fill="#fff" />
              </g>
            ) : null}
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", gap: 4 * k }}>
            <Rise at={cAt}>
              <Odometer value={heroPct} at={cAt} frames={t(1.0)} size={104 * k} color="#fff" suffix="%" suffixColor={accent}
                suffixScale={0.5} />
            </Rise>
            {lines(cap(items[hero].label), 14).slice(0, 2).map((l, i) => (
              <Rise key={`h${i}`} at={cAt + 6 + i * 2} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                letterSpacing: "0.16em", color: "rgba(255,255,255,.75)", textAlign: "center", lineHeight: 1.1,
                whiteSpace: "nowrap" }}>{l}</Rise>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 24 * k, width: LCW }}>
          <Head ov={overlay} accent={accent} size={52} width={700} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            {items.map((it, i) => {
              const at = rowAt[i];
              const isHero = i === hero;
              const share = (it.value / sum) * 100;
              const col = isHero ? accent : "#fff";
              const name = cap(it.label);
              const ns = fitText(name, labAvail, 32 * k, 24 * k, 1, 0.56).size;
              const pre = str(it.prefix) || prefix;
              return (
                <div key={`r${i}`} style={{ position: "relative", height: rowH, display: "flex", alignItems: "center", gap: 18 * k }}>
                  <div style={{ width: 20 * k, height: 20 * k, borderRadius: 5 * k, background: cols[i], flexShrink: 0,
                    transform: `scale(${ramp(frame, at, 12, backOut)})` }} />
                  <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
                    <Rise at={at + 1} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: ns, letterSpacing: "0.08em",
                      color: isHero ? accent : "#fff", whiteSpace: "nowrap", lineHeight: 1.1 }}>{name}</Rise>
                    {!pctUnit ? (
                      <Rise at={at + 4} style={{ fontFamily: MONO, fontWeight: 500, fontSize: 20 * k, letterSpacing: "0.06em",
                        color: "rgba(255,255,255,.6)", whiteSpace: "nowrap" }}>
                        {share >= 10 ? Math.round(share) : share.toFixed(1)}% OF TOTAL
                      </Rise>
                    ) : null}
                  </div>
                  <Rise at={at + 2} style={{ flexShrink: 0 }}>
                    {roll ? (
                      <Odometer value={it.value} at={at + 2} frames={t(0.8)} size={54 * k} color={col} prefix={pre}
                        suffix={odoSuf(suffix)} suffixScale={0.5} />
                    ) : (
                      <span style={{ fontFamily: DISPLAY, fontSize: 54 * k, color: col, lineHeight: 1, whiteSpace: "nowrap" }}>
                        {withUnit(it.value, pre, suffix)}</span>
                    )}
                  </Rise>
                  <div style={{ position: "absolute", left: 0, bottom: 0, height: 1.5 * k, background: "rgba(255,255,255,.16)",
                    width: `${ramp(frame, at, t(0.5), inOut) * 100}%` }} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 6. treemap
type Cell = { x: number; y: number; w: number; h: number; dir: "v" | "h" };
const worst = (row: number[], side: number): number => {
  const s = row.reduce((a, b) => a + b, 0);
  const mx = Math.max(...row), mn = Math.min(...row);
  const s2 = s * s, w2 = side * side;
  return Math.max((w2 * mx) / Math.max(1e-9, s2), s2 / Math.max(1e-9, w2 * mn));
};
/** Squarified treemap (Bruls et al.): areas sorted descending into near-square cells. */
const squarify = (areas: number[], box: { x: number; y: number; w: number; h: number }): Cell[] => {
  const out: Cell[] = [];
  let { x, y, w, h } = box;
  let i = 0;
  while (i < areas.length) {
    const side = Math.max(1e-6, Math.min(w, h));
    const row: number[] = [areas[i]];
    let j = i + 1;
    while (j < areas.length && worst([...row, areas[j]], side) <= worst(row, side)) {
      row.push(areas[j]);
      j++;
    }
    const s = row.reduce((a, b) => a + b, 0);
    if (w >= h) {
      const cw = Math.min(w, s / Math.max(1e-6, h));
      let yy = y;
      for (const a of row) {
        const ch = a / Math.max(1e-6, cw);
        out.push({ x, y: yy, w: cw, h: ch, dir: "v" });
        yy += ch;
      }
      x += cw;
      w -= cw;
    } else {
      const rh = Math.min(h, s / Math.max(1e-6, w));
      let xx = x;
      for (const a of row) {
        const cw2 = a / Math.max(1e-6, rh);
        out.push({ x: xx, y, w: cw2, h: rh, dir: "h" });
        xx += cw2;
      }
      y += rh;
      h -= rh;
    }
    i = j;
  }
  return out;
};

/** A still value set the way the Odometer sets it: the number, then the unit small and raised. */
const Val: React.FC<{ num: string; unit: string; size: number; color: string }> = ({ num, unit, size, color }) => (
  <span style={{ display: "inline-flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: size, color, lineHeight: 1,
    whiteSpace: "nowrap" }}>
    {num}
    {unit ? <span style={{ fontSize: size * 0.42, marginLeft: size * 0.04, marginTop: size * 0.06 }}>{unit}</span> : null}
  </span>
);

/** Tiles sized by value, cut in one after another by a glowing knife edge; the biggest in the accent. */
const Treemap: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const items = nums(overlay.items).filter((i) => i.value > 0).sort((a, b) => b.value - a.value).slice(0, 7);
  if (items.length < 2) return null;
  const W = 1300 * k, H = 540 * k, G = 8 * k;
  const sum = items.reduce((a, i) => a + i.value, 0);
  const cells = squarify(items.map((i) => (i.value / sum) * W * H), { x: 0, y: 0, w: W, h: H });
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix);
  const unit = odoSuf(suffix);
  const pctUnit = suffix.trim() === "%";
  const glass = [0.2, 0.16, 0.13, 0.1, 0.08];
  const tileAt = (i: number) => t(0.3) + i * t(0.13);
  // What each tile can hold, sized so nothing is clipped: name (one or two
  // lines by words), value (unit at 0.42 of the number) and share when big;
  // name and value when mid. A tile whose name cannot be set at 22px or more
  // stays clean and is listed in the footnote under the map instead.
  const plan = cells.map((c, i) => {
    const it = items[i];
    const w = Math.max(0, c.w - G), h = Math.max(0, c.h - G);
    const name = cap(it.label);
    const num = `${str(it.prefix) || prefix}${fmt(it.value)}`;
    const valEm = num.length * 0.42 + unit.length * 0.42 * 0.42;
    if (w >= 170 * k && h >= 120 * k) {
      const maxN = Math.max(24 * k, Math.min(34 * k, Math.min(w, h) * 0.12));
      const lab = fitText(name, w - 40 * k, maxN, 22 * k, h >= 200 * k ? 2 : 1, 0.6);
      const labH = lab.ls.length * lab.size * 1.2;
      const vSize = Math.max(28 * k, Math.min(118 * k, Math.min(w, h) * 0.34, (w - 40 * k - (pctUnit ? 0 : 64 * k)) / valEm,
        h - 16 * k - labH - 26 * k));
      if (lab.size >= 22 * k) return { kind: "big" as const, name, ls: lab.ls, num, vSize, nSize: lab.size };
    }
    if (w >= 90 * k && h >= 84 * k) {
      const lab = fitText(name, w - 24 * k, 26 * k, 22 * k, h >= 116 * k ? 2 : 1, 0.58);
      const vSize = Math.min(34 * k, (w - 24 * k) / valEm);
      if (lab.size >= 22 * k && vSize >= 22 * k) return { kind: "mid" as const, name, ls: lab.ls, num, vSize, nSize: lab.size };
    }
    return { kind: "none" as const, name, ls: [name], num, vSize: 0, nSize: 0 };
  });
  const rest = plan.map((p, i) => ({ p, i })).filter((q) => q.p.kind === "none").slice(0, 5);
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 30 * k, width: W }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 30 * k }}>
          <Head ov={overlay} accent={accent} width={1050} />
          {!pctUnit ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 * k }}>
              <Rise at={t(0.3)} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.24em",
                color: "rgba(255,255,255,.6)" }}>TOTAL</Rise>
              <Rise at={t(0.3) + 2}>
                <Odometer value={sum} at={t(0.3) + 2} frames={t(1.1)} size={64 * k} color="#fff" prefix={prefix}
                  suffix={odoSuf(suffix)} suffixScale={0.45} suffixColor={accent} />
              </Rise>
            </div>
          ) : null}
        </div>
        <div style={{ position: "relative", width: W, height: H }}>
          {cells.map((c, i) => {
            const it = items[i];
            const pl = plan[i];
            if (!it || !pl) return null;
            const at = tileAt(i);
            const p = ramp(frame, at, t(0.55), inOut);
            const w = Math.max(0, c.w - G), h = Math.max(0, c.h - G);
            const hero = i === 0, second = i === 1;
            const light = hero || second;
            const bg = hero ? `linear-gradient(135deg, ${accent} 0%, ${accent}c8 100%)`
              : second ? "linear-gradient(135deg, #f4f4f6 0%, #d6d7dc 100%)"
                : `rgba(255,255,255,${glass[Math.min(glass.length - 1, i - 2)]})`;
            const ink = light ? INK : "#fff";
            const clip = c.dir === "v" ? `inset(0 ${(1 - p) * 100}% 0 0)` : `inset(0 0 ${(1 - p) * 100}% 0)`;
            const big = pl.kind === "big";
            const mid = pl.kind === "mid";
            const vSize = pl.vSize;
            const nSize = pl.nSize;
            const share = (it.value / sum) * 100;
            const tAt = at + t(0.28);
            const knife = p > 0.001 && p < 0.999;
            const sheen = hero ? ramp(frame, at + t(0.9), t(1.0), inOut) : 0;
            return (
              <div key={`c${i}`} style={{ position: "absolute", left: c.x + G / 2, top: c.y + G / 2, width: w, height: h,
                clipPath: clip, background: bg, border: light ? "none" : `${1.5 * k}px solid rgba(255,255,255,.2)`,
                borderRadius: 6 * k, overflow: "hidden", boxSizing: "border-box" }}>
                {hero && sheen > 0 && sheen < 1 ? (
                  <div style={{ position: "absolute", top: 0, bottom: 0, left: `${-45 + sheen * 190}%`, width: "35%",
                    background: "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.38) 50%, rgba(255,255,255,0) 100%)",
                    transform: "skewX(-18deg)" }} />
                ) : null}
                {knife ? (
                  <div style={{ position: "absolute", background: "#fff", boxShadow: `0 0 ${14 * k}px #ffffff`,
                    ...(c.dir === "v"
                      ? { left: `calc(${p * 100}% - ${4 * k}px)`, top: 0, bottom: 0, width: 4 * k }
                      : { top: `calc(${p * 100}% - ${4 * k}px)`, left: 0, right: 0, height: 4 * k }) }} />
                ) : null}
                {big ? (
                  <>
                    <div style={{ position: "absolute", left: 20 * k, top: 16 * k, right: 20 * k }}>
                      {pl.ls.map((l, j) => (
                        <Rise key={`n${j}`} at={tAt + j * 2} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: nSize,
                          letterSpacing: "0.1em", lineHeight: 1.12, color: ink, whiteSpace: "nowrap" }}>{l}</Rise>
                      ))}
                    </div>
                    <div style={{ position: "absolute", left: 20 * k, right: 20 * k, bottom: 12 * k, display: "flex",
                      alignItems: "flex-end", justifyContent: "space-between", gap: 10 * k }}>
                      <Rise at={tAt + 3}>
                        {i < 2 ? (
                          <Odometer value={it.value} at={tAt + 3} frames={t(1.0)} size={vSize} color={ink}
                            prefix={str(it.prefix) || prefix} suffix={unit} suffixScale={0.42} />
                        ) : (
                          <Val num={pl.num} unit={unit} size={vSize} color={ink} />
                        )}
                      </Rise>
                      {!pctUnit ? (
                        <Rise at={tAt + 6} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
                          color: light ? "rgba(12,12,15,.7)" : "rgba(255,255,255,.7)", whiteSpace: "nowrap",
                          marginBottom: 6 * k, flexShrink: 0 }}>
                          {share >= 10 ? Math.round(share) : share.toFixed(1)}%
                        </Rise>
                      ) : null}
                    </div>
                  </>
                ) : mid ? (
                  <>
                    <div style={{ position: "absolute", left: 12 * k, top: 10 * k, right: 10 * k }}>
                      {pl.ls.map((l, j) => (
                        <Rise key={`n${j}`} at={tAt + j * 2} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: nSize,
                          letterSpacing: "0.08em", lineHeight: 1.12, color: ink, whiteSpace: "nowrap" }}>{l}</Rise>
                      ))}
                    </div>
                    <Rise at={tAt + 3} style={{ position: "absolute", left: 12 * k, bottom: 8 * k }}>
                      <Val num={pl.num} unit={unit} size={vSize} color={ink} />
                    </Rise>
                  </>
                ) : null}
              </div>
            );
          })}
        </div>
        {rest.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", columnGap: 30 * k, rowGap: 6 * k,
            marginTop: -12 * k }}>
            {rest.map((q, j) => (
              <Rise key={`f${j}`} at={tileAt(q.i) + t(0.3)} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                letterSpacing: "0.08em", color: "rgba(255,255,255,.62)", whiteSpace: "nowrap", lineHeight: 1.15 }}>
                <span style={{ display: "inline-block", width: 12 * k, height: 12 * k, borderRadius: 2 * k, marginRight: 10 * k,
                  background: "rgba(255,255,255,.32)", border: `${1.5 * k}px solid rgba(255,255,255,.4)` }} />
                {q.p.name}
                <span style={{ color: "#fff", marginLeft: 10 * k }}>{`${q.p.num}${unit}`}</span>
              </Rise>
            ))}
          </div>
        ) : null}
      </div>
    </Stage>
  );
};

// ================================================================== 7. flow split
type Band = { s0: number; s1: number; t0: number; t1: number; h: number };

/** One flow (label, value) pouring left to right and splitting into branches sized by item values. */
const FlowSplit: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const items = nums(overlay.items).filter((i) => i.value > 0).sort((a, b) => b.value - a.value).slice(0, 6);
  if (items.length < 2) return null;
  const n = items.length;
  const sum = items.reduce((a, i) => a + i.value, 0);
  const prefix = str(overlay.prefix) || str(items[0].prefix);
  const suffix = str(overlay.suffix) || str(items[0].suffix);
  const ov = toNum(overlay.value);
  const srcVal = Number.isFinite(ov) && ov > 0 ? ov : sum;
  const srcName = (lines(cap(str(overlay.label).trim()), 30)[0] || "").trim();
  const TOP = 124 * k, H = 480 * k;
  const SN = 18 * k, TR = 290 * k, XT = 840 * k, NW = 16 * k;
  const PW = XT + NW + 420 * k;
  const gapT = (n > 4 ? 22 : 30) * k;
  const avail = H - gapT * (n - 1);
  const unit = avail / sum;
  const sy0 = TOP + (H - avail) / 2;
  const mx = (TR + XT) / 2;
  let sAcc = sy0, tAcc = TOP;
  const bands: Band[] = items.map((it) => {
    const h = it.value * unit;
    const b = { s0: sAcc, s1: sAcc + h, t0: tAcc, t1: tAcc + h, h };
    sAcc += h;
    tAcc += h + gapT;
    return b;
  });
  const ribbon = (b: Band) =>
    `M${f1(SN)} ${f1(b.s0)} L${f1(TR)} ${f1(b.s0)} C${f1(mx)} ${f1(b.s0)} ${f1(mx)} ${f1(b.t0)} ${f1(XT)} ${f1(b.t0)} ` +
    `L${f1(XT)} ${f1(b.t1)} C${f1(mx)} ${f1(b.t1)} ${f1(mx)} ${f1(b.s1)} ${f1(TR)} ${f1(b.s1)} L${f1(SN)} ${f1(b.s1)} Z`;
  const centre = (b: Band) => {
    const c = (b.s0 + b.s1) / 2, tc = (b.t0 + b.t1) / 2;
    return `M${f1(SN)} ${f1(c)} L${f1(TR)} ${f1(c)} C${f1(mx)} ${f1(c)} ${f1(mx)} ${f1(tc)} ${f1(XT)} ${f1(tc)}`;
  };
  const sweepAt = t(0.3), sweepN = t(1.5);
  const sweep = ramp(frame, sweepAt, sweepN, inOut);
  const clipW = SN + sweep * (XT + NW - SN) + 2 * k;
  const nodeAt = frameWhen(sweepAt, sweepN, inOut, 0.97);
  // Each branch label (value line + name line) is ~82px tall: keep centres 84px apart.
  const labelY = spread(bands.map((b) => (b.t0 + b.t1) / 2), 84 * k, TOP, TOP + H - 16 * k);
  const roll = digitCount(items.map((i) => i.value)) <= 14;
  const flowOn = ramp(frame, sweepAt + t(0.5), t(0.6));
  const srcGrow = ramp(frame, 2, t(0.5), inOut);
  const colOf = (i: number) => (i === 0 ? accent : "#ffffff");
  const id = `cbfs${overlay.startFrame}`;
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 * k, width: PW }}>
        <Head ov={overlay} accent={accent} width={1270} />
        <div style={{ position: "relative", width: PW, height: TOP + H }}>
          <svg width={PW} height={TOP + H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <clipPath id={`${id}c`}><rect x={-2 * k} y={0} width={Math.max(0, clipW)} height={TOP + H + 40 * k} /></clipPath>
              {items.map((_, i) => (
                <linearGradient key={`g${i}`} id={`${id}g${i}`} x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#ffffff" stopOpacity={0.2} />
                  <stop offset="40%" stopColor={colOf(i)} stopOpacity={i === 0 ? 0.45 : 0.22} />
                  <stop offset="100%" stopColor={colOf(i)} stopOpacity={i === 0 ? 0.95 : Math.max(0.3, 0.62 - i * 0.07)} />
                </linearGradient>
              ))}
            </defs>
            <g clipPath={`url(#${id}c)`}>
              {bands.map((b, i) => (
                <path key={`r${i}`} d={ribbon(b)} fill={`url(#${id}g${i})`} stroke="rgba(12,12,15,.55)" strokeWidth={1.5 * k} />
              ))}
              {flowOn > 0 ? bands.map((b, i) => (b.h > 16 * k ? (
                <path key={`f${i}`} d={centre(b)} fill="none" stroke="#fff" strokeOpacity={0.45 * flowOn}
                  strokeWidth={Math.max(1.5 * k, Math.min(5 * k, b.h * 0.08))} strokeLinecap="round"
                  strokeDasharray={`${16 * k} ${34 * k}`} strokeDashoffset={-frame * 4.5 * k} />
              ) : null)) : null}
            </g>
            <rect x={0} y={sy0 + avail / 2 - (avail / 2) * srcGrow} width={SN} height={avail * srcGrow} rx={4 * k} fill="#fff" />
            {bands.map((b, i) => {
              const gN = ramp(frame, nodeAt + i * 2, 12, backOut);
              const m = (b.t0 + b.t1) / 2;
              const off = Math.abs(labelY[i] - m) > 3 * k;
              return (
                <g key={`n${i}`}>
                  {gN > 0 ? (
                    <rect x={XT} y={m - (b.h / 2) * gN} width={NW} height={Math.max(0, b.h * gN)} rx={3 * k}
                      fill={i === 0 ? accent : "#fff"} />
                  ) : null}
                  {off ? (
                    <path d={`M${f1(XT + NW + 4 * k)} ${f1(m)} L${f1(XT + NW + 36 * k)} ${f1(labelY[i])}`} fill="none"
                      stroke="rgba(255,255,255,.4)" strokeWidth={1.5 * k} opacity={ramp(frame, nodeAt + i * 3, 10)} />
                  ) : null}
                </g>
              );
            })}
          </svg>
          <div style={{ position: "absolute", left: 0, top: TOP - 116 * k, display: "flex", flexDirection: "column", gap: 2 * k }}>
            {srcName ? (
              <Rise at={4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.22em", color: accent,
                whiteSpace: "nowrap" }}>{srcName}</Rise>
            ) : null}
            <Rise at={6}>
              <Odometer value={srcVal} at={6} frames={t(1.0)} size={66 * k} color="#fff" prefix={prefix} suffix={odoSuf(suffix)}
                suffixScale={0.45} suffixColor={accent} />
            </Rise>
          </div>
          {items.map((it, i) => {
            const la = nodeAt + 2 + i * 3;
            const share = (it.value / sum) * 100;
            const col = i === 0 ? accent : "#fff";
            const pre = str(it.prefix) || prefix;
            const name = cap(it.label);
            const ns = fitText(name, 370 * k, 26 * k, 22 * k, 1, 0.6).size;
            return (
              <div key={`l${i}`} style={{ position: "absolute", left: XT + NW + 44 * k, top: labelY[i] - 41 * k, display: "flex",
                flexDirection: "column" }}>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 12 * k }}>
                  <Rise at={la}>
                    {roll ? (
                      <Odometer value={it.value} at={la} frames={t(0.8)} size={48 * k} color={col} prefix={pre}
                        suffix={odoSuf(suffix)} suffixScale={0.5} />
                    ) : (
                      <span style={{ fontFamily: DISPLAY, fontSize: 48 * k, color: col, lineHeight: 1, whiteSpace: "nowrap" }}>
                        {withUnit(it.value, pre, suffix)}</span>
                    )}
                  </Rise>
                  <Rise at={la + 3} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                    color: i === 0 ? accent : "rgba(255,255,255,.6)", whiteSpace: "nowrap" }}>
                    {share >= 10 ? Math.round(share) : share.toFixed(1)}%
                  </Rise>
                </div>
                <Rise at={la + 2} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: ns, letterSpacing: "0.1em",
                  color: "rgba(255,255,255,.88)", whiteSpace: "nowrap" }}>{name}</Rise>
              </div>
            );
          })}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 8. scatter bubbles
/** Points (value = x, first number in text = y, optional second = size) flying out onto a grid. */
const Scatter: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const pts = arr(overlay.items)
    .map((it) => {
      const nn = numbersIn(it?.text);
      return { label: cap(it?.label), x: toNum(it?.value), y: nn.length ? nn[0] : NaN, s: nn.length > 1 ? nn[1] : NaN };
    })
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
    .slice(0, 8);
  if (pts.length < 2) return null;
  const n = pts.length;
  const axisNames = splitNames(overlay.label, false);
  const xName = cap(axisNames[0]), yName = cap(axisNames[1]);
  const W = 1100 * k, H = 500 * k;
  const xv = pts.map((p) => p.x), yv = pts.map((p) => p.y);
  const xlo = Math.min(...xv), xhi = Math.max(...xv), ylo = Math.min(...yv), yhi = Math.max(...yv);
  const padX = (xhi - xlo) * 0.1 || Math.abs(xhi) * 0.2 || 1;
  const padY = (yhi - ylo) * 0.12 || Math.abs(yhi) * 0.2 || 1;
  const sx = niceScale(xlo >= 0 && xlo <= xhi * 0.3 ? 0 : xlo - padX, xhi + padX, 5);
  const sy = niceScale(ylo >= 0 && ylo <= yhi * 0.3 ? 0 : ylo - padY, yhi + padY, 4);
  const X = (v: number) => ((v - sx.min) / (sx.max - sx.min)) * W;
  const Y = (v: number) => H - ((v - sy.min) / (sy.max - sy.min)) * H;
  const hasS = pts.every((p) => Number.isFinite(p.s) && p.s > 0);
  const maxS = hasS ? Math.max(...pts.map((p) => p.s)) : 1;
  const hl = str(overlay.highlight).trim().toLowerCase();
  let hero = hl ? pts.findIndex((p) => p.label.toLowerCase().includes(hl)) : -1;
  if (hero < 0) hero = pts.reduce((m, p, i) => (p.y > pts[m].y ? i : m), 0);
  const rad = (i: number) => (hasS ? 14 + 40 * Math.sqrt(pts[i].s / maxS) : i === hero ? 22 : 15) * k;
  const flyAt = (i: number) => t(0.35) + i * t(0.08);
  const flyN = t(0.75);
  const landAt = (i: number) => flyAt(i) + Math.round(flyN * 0.35);
  const allLanded = flyAt(n - 1) + Math.round(flyN * 0.6);
  let trend: { a: Pt; b: Pt } | null = null;
  if (n >= 3) {
    const mxv = xv.reduce((a, b) => a + b, 0) / n, myv = yv.reduce((a, b) => a + b, 0) / n;
    let sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) {
      sxx += (xv[i] - mxv) ** 2;
      sxy += (xv[i] - mxv) * (yv[i] - myv);
    }
    if (sxx > 0) {
      const slope = sxy / sxx, icpt = myv - slope * mxv;
      trend = { a: [X(sx.min), Y(slope * sx.min + icpt)], b: [X(sx.max), Y(slope * sx.max + icpt)] };
    }
  }
  const tp = ramp(frame, allLanded, t(0.8), inOut);
  const cross = ramp(frame, allLanded + t(0.2), t(0.5), inOut);
  const chipP = ramp(frame, allLanded + t(0.55), 12);
  const hp = pts[hero];
  const hx = X(hp.x), hy = Y(hp.y), hr = rad(hero);
  const cyc = t(1.4);
  const order = pts.map((_, i) => i).sort((a, b) => (a === hero ? 1 : b === hero ? -1 : rad(b) - rad(a)));
  const id = `cbsc${overlay.startFrame}`;
  const grow = ramp(frame, 0, t(0.5), inOut);
  // Labels placed without collisions: the highlighted point first, then every
  // other point tries right, left, above, below and the four diagonals, and
  // stays unlabelled rather than sit on a bubble or on another label.
  type Spot = { x0: number; y0: number; x1: number; y1: number; align: "left" | "right" | "center" };
  type Rect = { x0: number; y0: number; x1: number; y1: number };
  const hits = (a: Rect, b: Rect): boolean => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  const bub: Rect[] = pts.map((p, i) => {
    const ex = X(p.x), ey = Y(p.y), r = rad(i) + 3 * k;
    return { x0: ex - r, y0: ey - r, x1: ex + r, y1: ey + r };
  });
  const taken: Spot[] = [];
  const place = (i: number, w: number, h: number): Spot | null => {
    const ex = X(pts[i].x), ey = Y(pts[i].y), r = rad(i), g = 10 * k, dg = r * 0.72 + 4 * k;
    const cands: [number, number, Spot["align"]][] = [
      [ex + r + g, ey - h / 2, "left"], [ex - r - g - w, ey - h / 2, "right"],
      [ex - w / 2, ey - r - 6 * k - h, "center"], [ex - w / 2, ey + r + 6 * k, "center"],
      [ex + dg, ey - dg - h, "left"], [ex + dg, ey + dg, "left"],
      [ex - dg - w, ey - dg - h, "right"], [ex - dg - w, ey + dg, "right"],
    ];
    for (const [x0, y0, align] of cands) {
      const s: Spot = { x0, y0, x1: x0 + w, y1: y0 + h, align };
      if (s.x0 < 6 * k || s.x1 > W + 30 * k || s.y0 < -8 * k || s.y1 > H - 4 * k) continue;
      if (taken.some((o) => hits(s, o)) || bub.some((b, j) => j !== i && hits(s, b))) continue;
      taken.push(s);
      return s;
    }
    return null;
  };
  const coords = `${fmt(hp.x)} · ${fmt(hp.y)}`;
  const heroW = Math.max(hp.label.length * 0.6 * 34 * k, coords.length * 0.62 * 20 * k) + 6 * k;
  const heroH = 70 * k;
  let heroSpot = place(hero, heroW, heroH);
  if (!heroSpot) {
    const right = hx + hr + 16 * k + heroW <= W + 30 * k;
    const x0 = right ? hx + hr + 16 * k : hx - hr - 16 * k - heroW;
    heroSpot = { x0, y0: hy - heroH / 2, x1: x0 + heroW, y1: hy + heroH / 2, align: right ? "left" : "right" };
    taken.push(heroSpot);
  }
  const spots = pts.map((p, i) => (i === hero ? null : place(i, p.label.length * 0.56 * 24 * k + 8 * k, 30 * k)));
  const posOf = (s: Spot): React.CSSProperties =>
    s.align === "left" ? { left: s.x0, top: s.y0 }
      : s.align === "right" ? { right: W - s.x1, top: s.y0 }
        : { left: (s.x0 + s.x1) / 2, top: s.y0, transform: "translateX(-50%)" };
  const hs: Spot = heroSpot;
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 74 * k, paddingLeft: 110 * k, paddingRight: 40 * k }}>
        <Head ov={overlay} accent={accent} width={1100} />
        <div style={{ position: "relative", width: W, height: H + 90 * k }}>
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs><clipPath id={`${id}c`}><rect x={0} y={0} width={W} height={H} /></clipPath></defs>
            {sx.ticks.map((v, i) => (
              <line key={`gx${i}`} x1={X(v)} x2={X(v)} y1={H} y2={H - H * ramp(frame, 2 + i * 2, t(0.6), inOut)}
                stroke="rgba(255,255,255,.09)" strokeWidth={1.5 * k} />
            ))}
            {sy.ticks.map((v, i) => (
              <line key={`gy${i}`} x1={0} x2={W * ramp(frame, 2 + i * 2, t(0.6), inOut)} y1={Y(v)} y2={Y(v)}
                stroke="rgba(255,255,255,.09)" strokeWidth={1.5 * k} />
            ))}
            <line x1={0} x2={0} y1={H} y2={H - H * grow} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
            <line x1={0} x2={W * grow} y1={H} y2={H} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
            {trend && tp > 0 ? (
              <line clipPath={`url(#${id}c)`} x1={trend.a[0]} y1={trend.a[1]} x2={trend.a[0] + (trend.b[0] - trend.a[0]) * tp}
                y2={trend.a[1] + (trend.b[1] - trend.a[1]) * tp} stroke="rgba(255,255,255,.55)" strokeWidth={3 * k}
                strokeDasharray={`${12 * k} ${10 * k}`} strokeLinecap="round" />
            ) : null}
            {cross > 0 ? (
              <g>
                <line x1={hx} y1={hy} x2={hx} y2={hy + (H - hy) * cross} stroke={accent} strokeWidth={2.5 * k}
                  strokeDasharray={`${6 * k} ${6 * k}`} />
                <line x1={hx} y1={hy} x2={hx - hx * cross} y2={hy} stroke={accent} strokeWidth={2.5 * k}
                  strokeDasharray={`${6 * k} ${6 * k}`} />
              </g>
            ) : null}
            {order.map((i) => {
              const p = pts[i];
              const q = ramp(frame, flyAt(i), flyN);
              const s2 = ramp(frame, flyAt(i), t(0.45), backOut);
              if (s2 <= 0) return null;
              const ex = X(p.x), ey = Y(p.y);
              const dx = ex - W / 2, dy = ey - H / 2;
              const len = Math.hypot(dx, dy) || 1;
              const arc = (rand(i + 3) - 0.5) * 240 * k * Math.sin(q * Math.PI);
              const bx = W / 2 + dx * q + (-dy / len) * arc;
              const by = H / 2 + dy * q + (dx / len) * arc;
              const r = rad(i);
              const isHero = i === hero;
              const rp = interpolate(frame, [landAt(i), landAt(i) + 20], [0, 1], clamp);
              const pulse = isHero && frame > allLanded ? ((frame - allLanded) % cyc) / cyc : -1;
              return (
                <g key={`b${i}`}>
                  {rp > 0 && rp < 1 ? (
                    <circle cx={ex} cy={ey} r={r + 36 * k * rp} fill="none" stroke={isHero ? accent : "#fff"} strokeWidth={2.5 * k}
                      opacity={1 - rp} />
                  ) : null}
                  {pulse >= 0 ? (
                    <circle cx={ex} cy={ey} r={r + 30 * k * pulse} fill="none" stroke={accent} strokeWidth={3 * k} opacity={1 - pulse} />
                  ) : null}
                  <circle cx={bx} cy={by} r={r * s2} fill={isHero ? accent : "#ffffff"} fillOpacity={isHero ? 1 : hasS ? 0.72 : 0.9}
                    stroke={INK} strokeWidth={2.5 * k}
                    style={isHero ? { filter: `drop-shadow(0 0 ${14 * k}px ${accent})` } : undefined} />
                </g>
              );
            })}
          </svg>
          {sx.ticks.map((v, i) => (
            <Rise key={`tx${i}`} at={2 + i * 2} style={{ position: "absolute", left: X(v) - 60 * k, width: 120 * k, top: H + 14 * k,
              textAlign: "center", fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, color: "rgba(255,255,255,.55)" }}>
              {short(v)}
            </Rise>
          ))}
          {sy.ticks.map((v, i) => (
            <Rise key={`ty${i}`} at={2 + i * 2} style={{ position: "absolute", left: -100 * k, width: 84 * k, top: Y(v) - 15 * k,
              textAlign: "right", fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, color: "rgba(255,255,255,.55)" }}>
              {short(v)}
            </Rise>
          ))}
          {xName ? (
            <Rise at={6} style={{ position: "absolute", right: 0, top: H + 52 * k, fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
              letterSpacing: "0.16em", color: "rgba(255,255,255,.75)", whiteSpace: "nowrap" }}>
              <span style={{ display: "inline-block", width: 18 * k, height: 4 * k, background: accent, marginRight: 10 * k,
                verticalAlign: "middle" }} />{xName}
            </Rise>
          ) : null}
          {yName ? (
            <Rise at={4} style={{ position: "absolute", left: 0, top: -50 * k, fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
              letterSpacing: "0.16em", color: "rgba(255,255,255,.75)", whiteSpace: "nowrap" }}>
              <span style={{ display: "inline-block", width: 4 * k, height: 18 * k, background: accent, marginRight: 10 * k,
                verticalAlign: "middle" }} />{yName}
            </Rise>
          ) : null}
          {pts.map((p, i) => {
            const s = spots[i];
            if (i === hero || !s) return null;
            return (
              <Rise key={`l${i}`} at={landAt(i)} style={{ position: "absolute", ...posOf(s), textAlign: s.align,
                fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.06em", color: "rgba(255,255,255,.85)",
                whiteSpace: "nowrap", lineHeight: 1.2, textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>{p.label}</Rise>
            );
          })}
          <div style={{ position: "absolute", ...posOf(hs), display: "flex", flexDirection: "column",
            alignItems: hs.align === "left" ? "flex-start" : hs.align === "right" ? "flex-end" : "center", gap: 2 * k }}>
            <Rise at={landAt(hero) + 4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.08em",
              color: accent, whiteSpace: "nowrap", lineHeight: 1.2, textShadow: "0 2px 12px rgba(0,0,0,.7)" }}>{hp.label}</Rise>
            <Rise at={landAt(hero) + 8} style={{ fontFamily: MONO, fontWeight: 500, fontSize: 20 * k, color: "rgba(255,255,255,.85)",
              whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>{coords}</Rise>
          </div>
          {chipP > 0 ? (
            <>
              <div style={{ position: "absolute", left: hx - 80 * k, width: 160 * k, top: H + 10 * k, display: "flex",
                justifyContent: "center" }}>
                <div style={{ clipPath: `inset(0 ${(1 - chipP) * 100}% 0 0)`, background: accent, color: INK, fontFamily: MONO,
                  fontWeight: 700, fontSize: 20 * k, padding: `${4 * k}px ${10 * k}px`, borderRadius: 4 * k, whiteSpace: "nowrap" }}>
                  <Rise at={allLanded + t(0.55)}>{fmt(hp.x)}</Rise>
                </div>
              </div>
              <div style={{ position: "absolute", left: -150 * k, width: 140 * k, top: hy - 17 * k, display: "flex",
                justifyContent: "flex-end" }}>
                <div style={{ clipPath: `inset(0 0 0 ${(1 - chipP) * 100}%)`, background: accent, color: INK, fontFamily: MONO,
                  fontWeight: 700, fontSize: 20 * k, padding: `${4 * k}px ${10 * k}px`, borderRadius: 4 * k, whiteSpace: "nowrap" }}>
                  <Rise at={allLanded + t(0.55)}>{fmt(hp.y)}</Rise>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 9. slope chart
/** Then (value) / now (text) columns; each item's line draws across, green up, red down. */
const Slope: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const t = useTiming();
  const rows = arr(overlay.items)
    .map((it) => ({ label: cap(it?.label), a: toNum(it?.value), b: firstNum(it?.text) }))
    .filter((r) => Number.isFinite(r.a) && Number.isFinite(r.b))
    .slice(0, 6);
  if (!rows.length) return null;
  const names = splitNames(overlay.label, true);
  const leftName = cap(names[0] || "Then"), rightName = cap(names[1] || "Now");
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix);
  const LW = 420 * k, MW = 540 * k, RW = 400 * k, H = 480 * k, pad = 24 * k;
  const all = rows.flatMap((r) => [r.a, r.b]);
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9) {
    lo -= 1;
    hi += 1;
  }
  const Y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad);
  const xL = LW, xR = LW + MW;
  const pct = rows.map((r) => (r.a !== 0 ? ((r.b - r.a) / Math.abs(r.a)) * 100 : 0));
  const hero = pct.reduce((m, p, i) => (Math.abs(p) > Math.abs(pct[m]) ? i : m), 0);
  const at = (i: number) => t(0.4) + i * t(0.16);
  const lineN = t(0.6);
  const lyA = spread(rows.map((r) => Y(r.a)), 56 * k, 0, H);
  const lyB = spread(rows.map((r) => Y(r.b)), 56 * k, 0, H);
  const axis = ramp(frame, 0, t(0.5), inOut);
  const heroDone = at(hero) + 6 + lineN;
  const cyc = t(1.5);
  const spark = frame > heroDone + 6 ? ((frame - heroDone - 6) % cyc) / cyc : -1;
  const changeTxt = (i: number) => {
    const r = rows[i];
    if (r.a === 0) return withUnit(Math.abs(r.b - r.a), prefix, suffix);
    const p = Math.abs(pct[i]);
    return `${p >= 10 ? Math.round(p) : p.toFixed(1)}%`;
  };
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 110 * k }}>
        <Head ov={overlay} accent={accent} center width={1360} />
        <div style={{ position: "relative", width: LW + MW + RW, height: H }}>
          <Rise at={2} style={{ position: "absolute", left: xL - 160 * k, width: 320 * k, top: -84 * k, textAlign: "center",
            fontFamily: DISPLAY, fontSize: 48 * k, letterSpacing: "0.06em", color: "rgba(255,255,255,.75)", whiteSpace: "nowrap" }}>
            {leftName}
          </Rise>
          <Rise at={6} style={{ position: "absolute", left: xR - 160 * k, width: 320 * k, top: -84 * k, textAlign: "center",
            fontFamily: DISPLAY, fontSize: 48 * k, letterSpacing: "0.06em", color: accent, whiteSpace: "nowrap" }}>
            {rightName}
          </Rise>
          <svg width={LW + MW + RW} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <line x1={xL} x2={xL} y1={0} y2={H * axis} stroke="rgba(255,255,255,.35)" strokeWidth={3 * k} />
            <line x1={xR} x2={xR} y1={0} y2={H * axis} stroke="rgba(255,255,255,.35)" strokeWidth={3 * k} />
            {rows.map((r, i) => {
              const a0 = at(i);
              const lp = ramp(frame, a0 + 6, lineN, inOut);
              const flat = r.b === r.a;
              const col = flat ? "#b9bbc3" : r.b > r.a ? GREEN : RED;
              const y1 = Y(r.a), y2 = Y(r.b);
              const hx = xL + (xR - xL) * lp, hy = y1 + (y2 - y1) * lp;
              const dotL = ramp(frame, a0, 12, backOut);
              const landF = a0 + 6 + lineN - 3;
              const dotR = ramp(frame, landF, 12, backOut);
              const rp = interpolate(frame, [landF, landF + 18], [0, 1], clamp);
              const isHero = i === hero;
              return (
                <g key={`r${i}`}>
                  {Math.abs(lyA[i] - y1) > 4 * k ? (
                    <path d={`M${f1(xL - 14 * k)} ${f1(y1)} L${f1(xL - 32 * k)} ${f1(lyA[i])}`} fill="none"
                      stroke="rgba(255,255,255,.4)" strokeWidth={1.5 * k} opacity={dotL > 0 ? 1 : 0} />
                  ) : null}
                  {Math.abs(lyB[i] - y2) > 4 * k ? (
                    <path d={`M${f1(xR + 14 * k)} ${f1(y2)} L${f1(xR + 32 * k)} ${f1(lyB[i])}`} fill="none"
                      stroke="rgba(255,255,255,.4)" strokeWidth={1.5 * k} opacity={dotR > 0 ? 1 : 0} />
                  ) : null}
                  {lp > 0 ? (
                    <line x1={xL} y1={y1} x2={hx} y2={hy} stroke={col} strokeWidth={(isHero ? 6 : 4) * k} strokeLinecap="round"
                      opacity={isHero ? 1 : 0.85} style={isHero ? { filter: `drop-shadow(0 0 ${10 * k}px ${col}aa)` } : undefined} />
                  ) : null}
                  {isHero && spark >= 0 ? (
                    <path d={`M${f1(xL)} ${f1(y1)} L${f1(xR)} ${f1(y2)}`} pathLength={1} fill="none" stroke="#fff"
                      strokeWidth={4 * k} strokeLinecap="round" strokeDasharray="0.07 1.3" strokeDashoffset={0.07 - spark * 1.14} />
                  ) : null}
                  <circle cx={xL} cy={y1} r={9 * k * dotL} fill={INK} stroke="#fff" strokeWidth={3.5 * k} />
                  {lp > 0 && lp < 1 ? <circle cx={hx} cy={hy} r={8 * k} fill="#fff" /> : null}
                  {rp > 0 && rp < 1 ? (
                    <circle cx={xR} cy={y2} r={(10 + 26 * rp) * k} fill="none" stroke={col} strokeWidth={3 * k} opacity={1 - rp} />
                  ) : null}
                  <circle cx={xR} cy={y2} r={11 * k * dotR} fill={col} stroke={INK} strokeWidth={3 * k} />
                </g>
              );
            })}
          </svg>
          {rows.map((r, i) => {
            const a0 = at(i);
            const land = a0 + 6 + lineN - 3;
            const flat = r.b === r.a;
            const up = r.b > r.a;
            const col = flat ? "#b9bbc3" : up ? GREEN : RED;
            const va = withUnit(r.a, prefix, suffix);
            // The name gets what the left column leaves after the value (Bebas ~0.42em a character).
            const ns = fitText(r.label, Math.max(120 * k, xL - 38 * k - 16 * k - va.length * 0.42 * 44 * k), 28 * k, 22 * k, 1, 0.58).size;
            return (
              <React.Fragment key={`l${i}`}>
                <div style={{ position: "absolute", left: 0, width: xL - 38 * k, top: lyA[i] - 26 * k, display: "flex",
                  justifyContent: "flex-end", alignItems: "center", gap: 16 * k }}>
                  <Rise at={a0 + 2} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: ns, letterSpacing: "0.08em",
                    color: i === hero ? "#fff" : "rgba(255,255,255,.75)", whiteSpace: "nowrap", minWidth: 0 }}>{r.label}</Rise>
                  <Rise at={a0} style={{ fontFamily: DISPLAY, fontSize: 44 * k, color: "#fff", lineHeight: 1.05, whiteSpace: "nowrap",
                    flexShrink: 0 }}>
                    {va}
                  </Rise>
                </div>
                <div style={{ position: "absolute", left: xR + 38 * k, top: lyB[i] - 26 * k, display: "flex", alignItems: "center",
                  gap: 14 * k }}>
                  <Rise at={land} style={{ fontFamily: DISPLAY, fontSize: 44 * k, color: "#fff", lineHeight: 1.05, whiteSpace: "nowrap" }}>
                    {withUnit(r.b, prefix, suffix)}
                  </Rise>
                  <Rise at={land + 3} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.04em",
                    color: col, whiteSpace: "nowrap" }}>
                    {flat ? "= 0%" : `${up ? "▲" : "▼"} ${changeTxt(i)}`}
                  </Rise>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </Stage>
  );
};

// ================================================================== 10. radar
/** A spider web (3-8 axes) drawing on, the value polygon springing out, an optional dashed reference (text), a beam sweeping. */
const Radar: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const t = useTiming();
  const axes = nums(overlay.items).filter((a) => a.value >= 0).slice(0, 8);
  if (axes.length < 3) return null;
  const n = axes.length;
  const refs = axes.map((a) => firstNum(a.text));
  const hasRef = refs.every((v) => Number.isFinite(v) && v >= 0);
  const suffix = str(overlay.suffix);
  const prefix = str(overlay.prefix);
  const peak = Math.max(...axes.map((a) => a.value), ...(hasRef ? refs : [0]));
  const tot = toNum(overlay.total);
  const max = Number.isFinite(tot) && tot > 0 ? tot : suffix.trim() === "%" && peak <= 100 ? 100 : niceTop(peak);
  // Heading + web + legend stay inside ~820px so the card holds the 90px safe
  // margins; a heading of three or four lines takes its room from the web.
  const R = (headLayout(overlay, 56, 1100).height > 150 ? 192 : 215) * k, PX = 250 * k, PY = 100 * k;
  const BW = 2 * R + 2 * PX, BH = 2 * R + 2 * PY, cx = BW / 2, cy = BH / 2;
  const ang = (i: number) => -Math.PI / 2 + (i * Math.PI * 2) / n;
  const P = (i: number, r: number): Pt => [cx + Math.cos(ang(i)) * r, cy + Math.sin(ang(i)) * r];
  const shape = (rs: number[]) =>
    rs.map((r, i) => {
      const p = P(i, r);
      return `${i ? "L" : "M"}${f1(p[0])} ${f1(p[1])}`;
    }).join(" ") + " Z";
  const polyAt = t(0.6), polyN = t(0.85);
  const settle = ramp(frame, polyAt + polyN, t(0.6));
  const hero = axes.reduce((m, a, i) => (a.value > axes[m].value ? i : m), 0);
  const rv = axes.map((a, i) => {
    const g = ramp(frame, polyAt + i * t(0.05), polyN, backOut);
    const br = 1 + 0.014 * Math.sin((frame / fps) * Math.PI * 2 * 0.4 + i * 1.3) * settle;
    return R * Math.min(1.12, a.value / max) * g * br;
  });
  const refG = ramp(frame, t(0.4), t(0.9), inOut);
  const refR = hasRef ? refs.map((v) => R * Math.min(1.12, v / max) * refG) : [];
  const beamAt = polyAt + polyN + t(0.2);
  const beamDeg = -90 + Math.max(0, frame - beamAt) * 2.2;
  const beamO = ramp(frame, beamAt, 14);
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const wedge = (a0: number, a1: number) =>
    `M${f1(cx)} ${f1(cy)} L${f1(cx + Math.cos(rad(a0)) * R)} ${f1(cy + Math.sin(rad(a0)) * R)} ` +
    `A${f1(R)} ${f1(R)} 0 0 1 ${f1(cx + Math.cos(rad(a1)) * R)} ${f1(cy + Math.sin(rad(a1)) * R)} Z`;
  const names = splitNames(overlay.label, true);
  const heroDone = polyAt + hero * t(0.05) + polyN;
  const cyc = t(1.3);
  const pulse = frame > heroDone ? ((frame - heroDone) % cyc) / cyc : -1;
  const hp = P(hero, rv[hero]);
  const id = `cbrd${overlay.startFrame}`;
  const outer = shape(axes.map(() => R));
  return (
    <Stage ov={overlay}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 28 * k }}>
        <Head ov={overlay} accent={accent} center width={1100} />
        <div style={{ position: "relative", width: BW, height: BH }}>
          <svg width={BW} height={BH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs><clipPath id={`${id}w`}><path d={outer} /></clipPath></defs>
            {[1, 2, 3, 4].map((q) => (
              <path key={`g${q}`} d={shape(axes.map(() => (R * q) / 4))} fill="none"
                stroke={q === 4 ? "rgba(255,255,255,.4)" : "rgba(255,255,255,.14)"} strokeWidth={(q === 4 ? 2.5 : 1.5) * k}
                pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ramp(frame, 2 + q * 3, t(0.7), inOut)} />
            ))}
            {axes.map((_, i) => {
              const e = P(i, R * ramp(frame, 4 + i * 2, t(0.5), inOut));
              return <line key={`s${i}`} x1={cx} y1={cy} x2={e[0]} y2={e[1]} stroke="rgba(255,255,255,.2)" strokeWidth={1.5 * k} />;
            })}
            {beamO > 0 ? (
              <g opacity={beamO} clipPath={`url(#${id}w)`}>
                {[0, 1, 2].map((w) => (
                  <path key={`w${w}`} d={wedge(beamDeg - (w + 1) * 12, beamDeg - w * 12)} fill={accent}
                    fillOpacity={[0.12, 0.065, 0.03][w]} />
                ))}
                <line x1={cx} y1={cy} x2={cx + Math.cos(rad(beamDeg)) * R} y2={cy + Math.sin(rad(beamDeg)) * R} stroke={accent}
                  strokeOpacity={0.55} strokeWidth={2 * k} />
              </g>
            ) : null}
            {hasRef && refG > 0 ? (
              <path d={shape(refR)} fill="rgba(255,255,255,.06)" stroke="rgba(255,255,255,.75)" strokeWidth={2.5 * k}
                strokeDasharray={`${8 * k} ${7 * k}`} strokeLinejoin="round" />
            ) : null}
            <path d={shape(rv)} fill={accent} fillOpacity={0.24} stroke={accent} strokeWidth={4 * k} strokeLinejoin="round"
              opacity={rv.some((r) => r > 0.5) ? 1 : 0} style={{ filter: `drop-shadow(0 0 ${12 * k}px ${accent}88)` }} />
            {pulse >= 0 ? (
              <circle cx={hp[0]} cy={hp[1]} r={(10 + 24 * pulse) * k} fill="none" stroke={accent} strokeWidth={3 * k}
                opacity={1 - pulse} />
            ) : null}
            {rv.map((r, i) => {
              const p = P(i, r);
              const on = ramp(frame, polyAt + i * t(0.05) + 4, 10, backOut);
              return (
                <circle key={`d${i}`} cx={p[0]} cy={p[1]} r={(i === hero ? 9 : 7) * k * on} fill={INK} stroke={accent}
                  strokeWidth={3.5 * k} />
              );
            })}
          </svg>
          {[1, 2, 3, 4].map((q) => (
            <Rise key={`v${q}`} at={6 + q * 3} style={{ position: "absolute", left: cx + 10 * k, top: cy - (R * q) / 4 - 25 * k,
              fontFamily: MONO, fontWeight: 500, fontSize: 20 * k, color: "rgba(255,255,255,.55)", whiteSpace: "nowrap" }}>
              {short((max * q) / 4)}
            </Rise>
          ))}
          {axes.map((a, i) => {
            const [lx, ly] = P(i, R + 30 * k);
            const c = Math.cos(ang(i)), s = Math.sin(ang(i));
            const LWd = 240 * k, LH = 78 * k;
            const left = c > 0.25 ? lx : c < -0.25 ? lx - LWd : lx - LWd / 2;
            const top = s < -0.25 ? ly - LH : s > 0.25 ? ly : ly - LH / 2;
            const align: "left" | "right" | "center" = c > 0.25 ? "left" : c < -0.25 ? "right" : "center";
            const la = polyAt + i * t(0.05) + t(0.25);
            const isHero = i === hero;
            const name = cap(a.label);
            const ns = fitText(name, LWd, 26 * k, 20 * k, 1, 0.58).size;
            return (
              <div key={`l${i}`} style={{ position: "absolute", left, top, width: LWd, height: LH, display: "flex",
                flexDirection: "column", justifyContent: s < -0.25 ? "flex-end" : s > 0.25 ? "flex-start" : "center",
                textAlign: align }}>
                <Rise at={la} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: ns, letterSpacing: "0.08em",
                  color: "rgba(255,255,255,.85)", whiteSpace: "nowrap", lineHeight: 1.1 }}>{name}</Rise>
                <Rise at={la + 3} style={{ fontFamily: DISPLAY, fontSize: 42 * k, color: isHero ? accent : "#fff", lineHeight: 1.02,
                  whiteSpace: "nowrap" }}>{withUnit(a.value, str(a.prefix) || prefix, suffix)}</Rise>
              </div>
            );
          })}
        </div>
        {hasRef ? (
          <div style={{ display: "flex", alignItems: "center", gap: 44 * k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
              <div style={{ width: 34 * k * ramp(frame, polyAt, 12), height: 6 * k, background: accent }} />
              <Rise at={polyAt} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.14em",
                color: "#fff", whiteSpace: "nowrap" }}>{cap(names[0] || "Now")}</Rise>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
              <div style={{ width: 34 * k * ramp(frame, polyAt + 3, 12), height: 0,
                borderTop: `${3 * k}px dashed rgba(255,255,255,.8)` }} />
              <Rise at={polyAt + 3} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.14em",
                color: "rgba(255,255,255,.75)", whiteSpace: "nowrap" }}>{cap(names[1] || "Before")}</Rise>
            </div>
          </div>
        ) : null}
      </div>
    </Stage>
  );
};

export const LOOKS: Record<string, Look> = {
  "cb-twin-lines": TwinLines,
  "cb-step-chart": StepChart,
  "cb-range-bars": RangeBars,
  "cb-stream": Stream,
  "cb-donut-legend": DonutLegend,
  "cb-treemap": Treemap,
  "cb-flow-split": FlowSplit,
  "cb-scatter": Scatter,
  "cb-slope": Slope,
  "cb-radar": Radar,
};
