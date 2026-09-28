import React from "react";
import { AbsoluteFill, Easing, interpolate, interpolateColors, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay } from "../../types";
import { Odometer, Scrim, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Counters & gauges (family "nc-"): ten number instruments, each with its own
 * mechanical motion hook, in the pro house style (condensed type, accent +
 * white + near-black, letters rising out of masks and dropping out at the end).
 *
 *   nc-speedo-gauge      a 220° speedometer: ticks sweep on, the needle springs
 *                        to the value with a settle wobble, the figure rolls
 *   nc-led-counter       a seven-segment LED panel: CRT power-on, segment
 *                        self-test ("888"), count-up with glow, power-off
 *   nc-flip-clock        split-flap cards clatter through the digits and land
 *   nc-countdown-dial    a ring charges full then drains back to the value,
 *                        the bezel ticks dim as it passes, the figure counts down
 *   nc-battery           a battery charges full then drains to the percent,
 *                        colour shifting green > accent > red, low-power pulse
 *   nc-thermometer       glass thermometer: mercury springs up the degree scale,
 *                        the reading rides the top of the column
 *   nc-population-clock  (tag) a live counter: lands like an odometer then keeps
 *                        ticking up, LIVE dot and data pulse
 *   nc-burst-number      the figure slams in with a flash, shockwave rings and a
 *                        radial particle burst, embers drift while it holds
 *   nc-segment-meter     20 slanted segments light in sequence past the value,
 *                        fall back, and a peak-hold segment drops after them
 *   nc-stopwatch         analog stopwatch: crown clicks, the hand sweeps, the
 *                        chrono readout runs and stops on the duration
 *
 * Every size is 1080p-referenced and multiplied by k. Deterministic: all
 * "random" values come from rnd(index). Text uses Letters (LetterLine's
 * reveal with an exit fitted to the line length, so long lines are gone by
 * the last frame) and Head (the chart heading whose accent bar also leaves).
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";

// ------------------------------------------------------------------ helpers
const S = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const cap = (v: unknown) => S(v).toUpperCase();
const num = (v: unknown): number => {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") return Number(v.replace(/,/g, ""));
  return NaN;
};
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
/** Deterministic 0..1 noise from an index (never Math.random). */
const rnd = (i: number) => {
  const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
const pad2 = (n: number) => String(Math.max(0, Math.floor(n))).padStart(2, "0");
const mix = (t: number, stops: number[], colors: string[]): string => {
  const tt = Math.max(stops[0], Math.min(stops[stops.length - 1], Number.isFinite(t) ? t : 0));
  try {
    return interpolateColors(tt, stops, colors);
  } catch (_e) {
    return colors[colors.length - 1];
  }
};
const decOf = (v: number) => (Math.abs(v) >= 100 || Number.isInteger(v) ? 0 : 1);
const fmtN = (v: number, decimals: number, grouping = true) =>
  (Number.isFinite(v) ? v : 0).toLocaleString("en-US", { minimumFractionDigits: decimals,
    maximumFractionDigits: decimals, useGrouping: grouping });
const compact = (v: number): string => {
  const a = Math.abs(v);
  const f = (x: number, u: string) => `${Number.isInteger(x) ? x : x.toFixed(1)}${u}`;
  if (a >= 1e9) return f(Math.round(v / 1e8) / 10, "B");
  if (a >= 1e6) return f(Math.round(v / 1e5) / 10, "M");
  if (a >= 1e4) return f(Math.round(v / 1e2) / 10, "K");
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
};
const niceCeil = (v: number) => {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v - 1e-9) return m * p;
  return 10 * p;
};
const niceStep = (span: number, target: number) => {
  const raw = Math.max(1e-9, span / target);
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw - 1e-9) return m * p;
  return 10 * p;
};

/** A share of a whole: "%" is out of 100, `total` is "out of", otherwise a nice max above the value. */
type Scale = { value: number; frac: number; max: number; pct: boolean; based: boolean };
const scaleOf = (ov: Overlay): Scale | null => {
  const value = num(ov.value);
  if (!Number.isFinite(value)) return null;
  const pct = S(ov.suffix).trim() === "%";
  const total = num(ov.total);
  const hasTotal = !pct && Number.isFinite(total) && total > 0;
  const max = pct ? 100 : hasTotal ? total : niceCeil(Math.abs(value) * 1.25);
  return { value, frac: clamp01(value / max), max, pct, based: pct || hasTotal };
};

/** 0 while the graphic holds, easing to 1 over the last ~12 frames. */
const useExit = (frames = 11) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - frames - 3, frames, expoIn);
};

/** A block that rises out of its mask (pin 0 -> 1) and leaves upward through it (pout 0 -> 1). */
const MaskIO: React.FC<{ pin: number; pout: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ pin, pout, children, style }) => (
    <div style={{ overflow: "hidden", paddingBottom: "0.04em", ...style }}>
      <div style={{ transform: `translateY(${((1 - pin) - pout) * 112}%)` }}>{children}</div>
    </div>
  );

/**
 * LetterLine's reveal: letters rise out of a mask one after another and drop out at the end. The exit
 * stagger shrinks with the line length (4 frames across the whole line at most), so even a 40-letter
 * line has fully left by the last frame; LetterLine's fixed 0.6-frame stagger left long lines' tails
 * on screen at the cut.
 */
const Letters: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 1, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const chars = Array.from(text);
    const outStep = Math.min(0.6, 4 / Math.max(1, chars.length - 1));
    const end = durationInFrames - 15;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", whiteSpace: "nowrap", ...style }}>
        {chars.map((c, i) => {
          const pin = ramp(frame, at + i * step, 12);
          const pout = ramp(frame, end + i * outStep, 9, expoIn);
          const y = (1 - pin) * 105 - pout * 105;
          return (
            <span key={i} style={{ display: "inline-block", transform: `translateY(${y}%)`, whiteSpace: "pre",
              opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
          );
        })}
      </div>
    );
  };

/** One line of at most about `n` characters, cut at a word with an ellipsis (subtitles never wrap). */
const oneLine = (text: string, n: number): string => {
  const ls = lines(text.trim(), n);
  if (!ls.length) return "";
  const first = ls[0].length > n + 6 ? ls[0].slice(0, n) : ls[0];
  return ls.length > 1 || first !== ls[0] ? `${first.replace(/[\s.,;:\-–—]+$/, "")}…` : first;
};

/** Up to `max` wrapped lines, each rising letter by letter (and dropping out at the end). */
const TextLines: React.FC<{ text?: string; chars: number; max: number; at: number; style: React.CSSProperties;
  align?: "center" | "left" }> = ({ text, chars, max, at, style, align = "center" }) => {
  const t = (text || "").trim();
  if (!t) return null;
  const all = lines(t, chars);
  const ls = all.slice(0, max);
  if (all.length > max && ls.length) ls[ls.length - 1] = `${ls[ls.length - 1].replace(/[\s.,;:\-–—]+$/, "")}…`;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: align === "center" ? "center" : "flex-start" }}>
      {ls.map((ln, i) => (
        <Letters key={i} text={ln} at={at + i * 4} step={0.6} style={{ textAlign: align, ...style }} />
      ))}
    </div>
  );
};

/**
 * The house chart heading (ProCharts Heading: DISPLAY letters over a short accent bar), centred, cut
 * to one line, with the bar retracting on `exit` (Heading's bar never left and popped off at the cut).
 */
const Head: React.FC<{ text: string; accent: string; size: number; exit: number; at?: number }> =
  ({ text, accent, size, exit, at = 0 }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const t = oneLine(cap(text), Math.round(2600 / size));
    if (!t) return null;
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 * k }}>
        <Letters text={t} at={at} step={0.7} style={{ fontFamily: DISPLAY, fontSize: size * k, color: "#fff",
          letterSpacing: "0.04em", lineHeight: 1, textAlign: "center", textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
        <div style={{ width: ramp(frame, at + 4, 16) * 110 * k * (1 - exit), height: 5 * k, background: accent }} />
      </div>
    );
  };

const polar = (cx: number, cy: number, r: number, deg: number): [number, number] => {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};
/** An SVG arc from a0 to a1 degrees (0 = 3 o'clock, clockwise). */
const arcPath = (cx: number, cy: number, r: number, a0: number, a1: number): string => {
  const sweep = a1 - a0;
  if (Math.abs(sweep) < 0.05) return "";
  if (Math.abs(sweep) >= 359.95) {
    const [x0, y0] = polar(cx, cy, r, a0);
    const [xm, ym] = polar(cx, cy, r, a0 + 180);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 1 1 ${xm.toFixed(2)} ${ym.toFixed(2)} ` +
      `A${r} ${r} 0 1 1 ${x0.toFixed(2)} ${y0.toFixed(2)}`;
  }
  const [x0, y0] = polar(cx, cy, r, a0);
  const [x1, y1] = polar(cx, cy, r, a1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${Math.abs(sweep) > 180 ? 1 : 0} ${sweep > 0 ? 1 : 0} ` +
    `${x1.toFixed(2)} ${y1.toFixed(2)}`;
};

// ================================================================== 1. speedometer
/** A 220° dial: ticks sweep on, the needle springs to the value and settles with a live wobble. */
const SpeedoGauge: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const sc = scaleOf(overlay);
  if (!sc) return null;
  const { value, frac, max, pct, based } = sc;
  const R = 280 * k;
  const W = 2 * R + 80 * k;
  const cx = W / 2;
  const cy = 34 * k + R;
  const A0 = 160;
  const SWP = 220;
  const H = cy + R * Math.sin(Math.PI / 9) + 28 * k;
  const at = Math.round(fps * 0.4);
  const sp = spring({ frame: Math.max(0, frame - at), fps, config: { damping: 11, stiffness: 62, mass: 1 } });
  const settled = ramp(frame, at + Math.round(fps * 1.5), 20);
  const jitter = settled * (0.004 * Math.sin(frame * 0.83) + 0.0025 * Math.sin(frame * 2.1 + 1));
  const n = Math.max(0, Math.min(1.025, sp * frac + jitter)) * (1 - exit);
  const needleDeg = A0 + SWP * n;
  const draw = ramp(frame, 0, Math.round(fps * 0.6), inOut) * (1 - exit);
  const trackEnd = A0 + SWP * draw;
  const bandR = R - 6 * k;
  const needleO = ramp(frame, at - 8, 8);
  const capS = ramp(frame, at - 8, 12, backOut);
  const L = R - 44 * k;
  const tail = 50 * k;
  const hwN = (x: number) => 6.5 * k - 4.9 * k * ((x + tail) / (L + tail));
  const tipFrom = L * 0.58;
  const pts1 = `${cx - tail},${cy - hwN(-tail)} ${cx + L},${cy - hwN(L)} ${cx + L},${cy + hwN(L)} ${cx - tail},${cy + hwN(-tail)}`;
  const pts2 = `${cx + tipFrom},${cy - hwN(tipFrom) - 0.5 * k} ${cx + L},${cy - hwN(L)} ${cx + L},${cy + hwN(L)} ` +
    `${cx + tipFrom},${cy + hwN(tipFrom) + 0.5 * k}`;
  const suf = S(overlay.suffix).trim();
  const unit = suf ? ` ${cap(suf)}` : "";
  const suffix = pct ? "%" : based ? `/${compact(max)}${suf.length <= 4 ? unit : ""}` : suf.length <= 10 ? unit : "";
  const prefix = S(overlay.prefix).trim();
  // The readout sits in the dial's open bottom, between the "0" and max labels: keep it under ~260px wide.
  const nChars = formatValue(value).text.length + prefix.length * 0.7 + suffix.length * 0.5;
  const NSZ = Math.min(118, 260 / (0.42 * Math.max(2.5, nChars))) * k;
  const fadeAll = 1 - ramp(frame, dur - 6, 5);
  const labelAt = (i: number) => (pct ? i % 8 === 0 : i === 0 || i === 20 || i === 40);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16 * k,
        transform: `scale(${hold})` }}>
        {S(overlay.subtitle) ? (
          <div style={{ marginBottom: 8 * k }}><Head text={S(overlay.subtitle)} accent={accent} size={54} exit={exit} /></div>
        ) : null}
        <div style={{ position: "relative", width: W, height: H, opacity: fadeAll,
          transform: `scale(${0.9 + 0.1 * ramp(frame, 0, 20)})` }}>
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <path d={arcPath(cx, cy, R + 12 * k, A0, trackEnd)} fill="none" stroke="rgba(255,255,255,.3)" strokeWidth={2 * k} />
            <path d={arcPath(cx, cy, bandR, A0, trackEnd)} fill="none" stroke="rgba(255,255,255,.09)" strokeWidth={14 * k} />
            {n > 0.002 ? (
              <path d={arcPath(cx, cy, bandR, A0, needleDeg)} fill="none" stroke={accent} strokeWidth={14 * k}
                style={{ filter: `drop-shadow(0 0 ${12 * k}px ${accent})` }} />
            ) : null}
            {Array.from({ length: 41 }, (_, i) => {
              const t = i / 40;
              const major = i % 4 === 0;
              const deg = A0 + SWP * t;
              const [x1, y1] = polar(cx, cy, R - 24 * k, deg);
              const [x2, y2] = polar(cx, cy, R - (major ? 50 : 36) * k, deg);
              const o = ramp(frame, 3 + i * 0.5, 8) * (1 - ramp(frame, dur - 16 + (40 - i) * 0.15, 6));
              const lit = n > 0.002 && t <= n + 0.001;
              const [lx, ly] = polar(cx, cy, R - 82 * k, deg);
              return (
                <g key={i} opacity={o}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={lit ? "#fff" : "rgba(255,255,255,.34)"}
                    strokeWidth={(major ? 4 : 2) * k} strokeLinecap="round" />
                  {labelAt(i) ? (
                    <text x={lx} y={ly} textAnchor="middle" dominantBaseline="central" fontFamily={LABEL} fontWeight={700}
                      fontSize={26 * k} fill={lit ? "#fff" : "rgba(255,255,255,.55)"}>
                      {pct ? String(Math.round(t * 100)) : compact(max * t)}
                    </text>
                  ) : null}
                </g>
              );
            })}
            <g opacity={needleO} transform={`rotate(${needleDeg} ${cx} ${cy})`}>
              <line x1={cx - tail} y1={cy} x2={cx + L} y2={cy} stroke={accent} strokeOpacity={0.2} strokeWidth={18 * k}
                strokeLinecap="round" />
              <polygon points={pts1} fill="#fff" />
              <polygon points={pts2} fill={accent} />
            </g>
            <circle cx={cx} cy={cy} r={Math.max(0, 26 * k * capS)} fill={INK} stroke={accent} strokeWidth={5 * k} />
            <circle cx={cx} cy={cy} r={Math.max(0, 7 * k * capS)} fill="#fff" />
          </svg>
        </div>
        <MaskIO pin={ramp(frame, at - 2, 16)} pout={exit} style={{ marginTop: -70 * k }}>
          <Odometer value={value} at={at} frames={Math.round(fps * 1.4)} size={NSZ} color="#fff"
            prefix={prefix} suffix={suffix} suffixColor={accent} suffixScale={0.5} />
        </MaskIO>
        <TextLines text={cap(overlay.text)} chars={34} max={2} at={at + 14} style={{ fontFamily: LABEL, fontWeight: 800,
          fontSize: 34 * k, letterSpacing: "0.18em", color: "rgba(255,255,255,.88)", lineHeight: 1.1 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. LED counter
const SEG_ON: Record<string, string> = {
  "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg",
  "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "",
};
const SEG_KEYS = ["a", "b", "c", "d", "e", "f", "g"];
const ptsStr = (p: [number, number][]) => p.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
/** The seven hexagonal segments of one digit cell (w x h, segment thickness t, joint gap g). */
const segShapes = (w: number, h: number, t: number, g: number): Record<string, string> => {
  const hz = (y: number): string => {
    const x1 = t / 2 + g;
    const x2 = w - t / 2 - g;
    return ptsStr([[x1, y], [x1 + t / 2, y - t / 2], [x2 - t / 2, y - t / 2], [x2, y], [x2 - t / 2, y + t / 2],
      [x1 + t / 2, y + t / 2]]);
  };
  const vt = (x: number, y1: number, y2: number): string =>
    ptsStr([[x, y1], [x + t / 2, y1 + t / 2], [x + t / 2, y2 - t / 2], [x, y2], [x - t / 2, y2 - t / 2],
      [x - t / 2, y1 + t / 2]]);
  return {
    a: hz(t / 2), g: hz(h / 2), d: hz(h - t / 2),
    f: vt(t / 2, t / 2 + g, h / 2 - g), b: vt(w - t / 2, t / 2 + g, h / 2 - g),
    e: vt(t / 2, h / 2 + g, h - t / 2 - g), c: vt(w - t / 2, h / 2 + g, h - t / 2 - g),
  };
};

/** A seven-segment panel: CRT power-on line, "888" self-test, glowing count-up, segments power off right to left. */
const LedCounter: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const raw = num(overlay.value);
  if (!Number.isFinite(raw)) return null;
  let v = Math.abs(raw);
  let suffix = S(overlay.suffix).trim();
  if (v >= 1e9) {
    // Ten digits do not fit the panel: billions with one decimal, the unit kept after the "B".
    v = Math.round(v / 1e8) / 10;
    suffix = suffix ? `B ${suffix}` : "B";
  }
  if (v >= 1e9) return null;
  const dec = decOf(v);
  const p10 = Math.pow(10, dec);
  const N = Math.round(v * p10);
  const intDigits = String(Math.floor(N / p10)).length;
  const cells = intDigits + dec;
  const DH = (cells > 7 ? 136 : cells > 5 ? 156 : 172) * k;
  const DW = DH * 0.55;
  const T = DH * 0.13;
  const GAP = DH * 0.15;
  const SEPW = DH * 0.15;
  const shapes = segShapes(DW, DH, T, DH * 0.016);
  const testAt = Math.round(fps * 0.42);
  const countAt = testAt + 9;
  const countF = Math.round(fps * 1.5);
  const cp = ramp(frame, countAt, countF, Easing.bezier(0.22, 0.6, 0.3, 1));
  const cur = Math.round(N * cp);
  const curStr = String(cur).padStart(dec + 1, "0").padStart(cells, " ");
  const mode = frame < testAt ? "off" : frame < testAt + 4 ? "test" : frame < countAt ? "off" : "count";
  const chars = Array.from({ length: cells }, (_, i) => {
    if (frame >= dur - 16 + (cells - 1 - i) * 1.1) return " ";
    if (mode === "test") return "8";
    if (mode === "off") return " ";
    return curStr[i] || " ";
  });
  const xs: number[] = [];
  const seps: { x: number; on: boolean }[] = [];
  let x = 0;
  for (let i = 0; i < cells; i++) {
    xs.push(x);
    x += DW;
    if (i === cells - 1) break;
    const isDp = dec > 0 && i === intDigits - 1;
    const isComma = i < intDigits - 1 && (intDigits - 1 - i) % 3 === 0;
    if (isDp || isComma) {
      seps.push({ x: x + GAP * 0.5 + SEPW * 0.5 - T * 0.45, on: chars[i] !== " " });
      x += GAP + SEPW;
    } else {
      x += GAP;
    }
  }
  const skew = DH * 0.12;
  const svgW = x + skew + 8 * k;
  const land = countAt + Math.round(countF * 0.72);
  const flash = interpolate(frame, [land - 6, land, land + 14], [0, 1, 0], clamp);
  const flick = 0.93 + 0.07 * Math.sin(frame * 1.7) * Math.sin(frame * 0.37 + 0.5);
  const ox = ramp(frame, 0, 9);
  const oy = ramp(frame, 7, 11);
  const cyE = ramp(frame, dur - 9, 5, expoIn);
  const cxE = ramp(frame, dur - 5, 4, expoIn);
  const openY = Math.max(0.018, oy * (1 - cyE));
  const openX = ox * (1 - cxE);
  const insY = 50 * (1 - openY);
  const insX = 50 * (1 - openX);
  const lineO = openX > 0.01 ? clamp01((0.3 - openY) / 0.25) : 0;
  const sheen = interpolate(frame, [land - 4, land + 22], [-130, 130], clamp);
  const bars = mode !== "count" ? 0 : cp < 0.999 ? (Math.floor(frame / 3) % 4) + 1 : 4;
  const prefix = `${raw < 0 ? "−" : ""}${S(overlay.prefix).trim()}`;
  // The header (mono subtitle + signal bars) needs room even over a one-digit figure: JetBrains Mono
  // advances 0.6em, +0.26em tracking, at 24px = ~20.7px a letter, plus the bars and a gap.
  const sub = oneLine(cap(overlay.subtitle), 30);
  const minW = sub ? (Array.from(sub).length * 20.7 + 80) * k : 0;
  const segBox = (sx: number, i: number) => (
    <rect key={`s${i}`} x={sx} y={DH - T * 0.9} width={T * 0.9} height={T * 0.9} />
  );
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 34 * k,
        transform: `scale(${hold})` }}>
        <div style={{ position: "relative", transform: `scale(${0.94 + 0.06 * ramp(frame, 0, 18)})` }}>
          <div style={{ position: "relative", padding: `${82 * k}px ${64 * k}px ${54 * k}px`, borderRadius: 22 * k,
            background: "linear-gradient(180deg, #16171c 0%, #0a0a0d 100%)", border: `${2 * k}px solid rgba(255,255,255,.13)`,
            boxShadow: `inset 0 0 ${60 * k}px rgba(0,0,0,.9), inset 0 ${2 * k}px 0 rgba(255,255,255,.06)`,
            clipPath: `inset(${insY}% ${insX}% ${insY}% ${insX}% round ${22 * k}px)`, overflow: "hidden",
            display: "flex", justifyContent: "center", minWidth: minW || undefined }}>
            <div style={{ position: "absolute", left: 64 * k, right: 64 * k, top: 26 * k, display: "flex",
              justifyContent: "space-between", alignItems: "center" }}>
              {sub ? (
                <Letters text={sub} at={10} step={0.5} style={{ fontFamily: MONO, fontWeight: 500,
                  fontSize: 24 * k, letterSpacing: "0.26em", color: "rgba(255,255,255,.55)" }} />
              ) : <div />}
              <div style={{ display: "flex", gap: 5 * k, alignItems: "flex-end" }}>
                {[0, 1, 2, 3].map((b) => (
                  <div key={b} style={{ width: 7 * k, height: (10 + b * 5) * k, borderRadius: 2 * k,
                    background: b < bars ? accent : "rgba(255,255,255,.12)",
                    boxShadow: b < bars ? `0 0 ${8 * k}px ${accent}` : "none" }} />
                ))}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 20 * k }}>
              {prefix ? (
                <Letters text={prefix} at={countAt} style={{ fontFamily: DISPLAY, fontSize: DH * 0.5, lineHeight: 1,
                  color: accent }} />
              ) : null}
              <svg width={svgW} height={DH + 4 * k} style={{ overflow: "visible", display: "block" }}>
                <g transform={`translate(${skew} 0) skewX(-7)`}>
                  <g fill={accent} opacity={0.075}>
                    {xs.map((cx, i) => {
                      const lit = SEG_ON[chars[i]] || "";
                      return (
                        <g key={i} transform={`translate(${cx} 0)`}>
                          {SEG_KEYS.map((s) => (lit.includes(s) ? null : <polygon key={s} points={shapes[s]} />))}
                        </g>
                      );
                    })}
                    {seps.map((s, i) => (s.on ? null : segBox(s.x, i)))}
                  </g>
                  <g fill={accent} opacity={flick} style={{ filter: `drop-shadow(0 0 ${(7 + 12 * flash) * k}px ${accent})` }}>
                    {xs.map((cx, i) => {
                      const lit = SEG_ON[chars[i]] || "";
                      if (!lit) return null;
                      return (
                        <g key={i} transform={`translate(${cx} 0)`}>
                          {SEG_KEYS.map((s) => (lit.includes(s) ? <polygon key={s} points={shapes[s]} /> : null))}
                        </g>
                      );
                    })}
                    {seps.map((s, i) => (s.on ? segBox(s.x, i) : null))}
                  </g>
                </g>
              </svg>
              {suffix ? (
                <Letters text={oneLine(cap(suffix), 16)} at={land - 4} style={{ fontFamily: DISPLAY, fontSize: DH * 0.4,
                  lineHeight: 1, color: accent, letterSpacing: "0.04em" }} />
              ) : null}
            </div>
            <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
              background: `repeating-linear-gradient(180deg, rgba(0,0,0,.24) 0px, rgba(0,0,0,.24) ${2 * k}px, ` +
                `rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${5 * k}px)` }} />
            <div style={{ position: "absolute", inset: 0, pointerEvents: "none", transform: `translateX(${sheen}%)`,
              background: "linear-gradient(105deg, rgba(255,255,255,0) 38%, rgba(255,255,255,.09) 50%, rgba(255,255,255,0) 62%)" }} />
          </div>
          {lineO > 0 ? (
            <div style={{ position: "absolute", left: `${insX}%`, right: `${insX}%`, top: "50%", height: 3 * k,
              marginTop: -1.5 * k, background: "#fff", opacity: lineO,
              boxShadow: `0 0 ${14 * k}px ${accent}, 0 0 ${4 * k}px #fff` }} />
          ) : null}
        </div>
        <TextLines text={cap(overlay.text)} chars={34} max={2} at={Math.round(fps * 0.7)} style={{ fontFamily: LABEL,
          fontWeight: 800, fontSize: 36 * k, letterSpacing: "0.14em", color: "rgba(255,255,255,.9)", lineHeight: 1.1 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. split-flap
const FlapHalf: React.FC<{ ch: string; w: number; h: number; top: boolean; color: string; size: number;
  style?: React.CSSProperties; shade?: number }> = ({ ch, w, h, top, color, size, style, shade = 0 }) => {
  const k = useK();
  const g = 1.5 * k;
  const r = 10 * k;
  return (
    <div style={{ position: "absolute", left: 0, top: top ? 0 : h / 2 + g, width: w, height: h / 2 - g, overflow: "hidden",
      borderRadius: top ? `${r}px ${r}px ${2 * k}px ${2 * k}px` : `${2 * k}px ${2 * k}px ${r}px ${r}px`,
      background: top ? "linear-gradient(180deg, #2b2c32 0%, #212228 100%)" : "linear-gradient(180deg, #1d1e23 0%, #141519 100%)",
      backfaceVisibility: "hidden", ...style }}>
      <div style={{ position: "absolute", left: 0, top: top ? 0 : -(h / 2 + g), width: w, height: h, lineHeight: `${h}px`,
        textAlign: "center", fontFamily: DISPLAY, fontSize: size, color, whiteSpace: "nowrap" }}>{ch}</div>
      {shade > 0.001 ? <div style={{ position: "absolute", inset: 0, background: `rgba(0,0,0,${shade.toFixed(3)})` }} /> : null}
    </div>
  );
};

/** One split-flap card: the top flap falls (0 -> 0.5), the bottom flap lands (0.5 -> 1). */
const FlapCard: React.FC<{ cur: string; nxt: string; phase: number; w: number; h: number; color: string; size: number }> =
  ({ cur, nxt, phase, w, h, color, size }) => {
    const k = useK();
    const flipping = phase > 0.001 && phase < 0.999;
    return (
      <div style={{ position: "relative", width: w, height: h, perspective: 900 * k, borderRadius: 10 * k,
        boxShadow: "0 18px 40px rgba(0,0,0,.45)" }}>
        <FlapHalf ch={flipping ? nxt : cur} w={w} h={h} top color={color} size={size} />
        <FlapHalf ch={cur} w={w} h={h} top={false} color={color} size={size} />
        {flipping && phase < 0.5 ? (
          <FlapHalf ch={cur} w={w} h={h} top color={color} size={size} shade={phase * 0.9}
            style={{ transform: `rotateX(${-phase * 180}deg)`, transformOrigin: "50% 100%" }} />
        ) : null}
        {flipping && phase >= 0.5 ? (
          <FlapHalf ch={nxt} w={w} h={h} top={false} color={color} size={size} shade={(1 - phase) * 0.7}
            style={{ transform: `rotateX(${(1 - phase) * 180}deg)`, transformOrigin: "50% 0%" }} />
        ) : null}
        <div style={{ position: "absolute", left: 0, right: 0, top: h / 2 - 1.5 * k, height: 3 * k, background: "#07070a" }} />
        <div style={{ position: "absolute", left: -2 * k, top: h / 2 - 7 * k, width: 5 * k, height: 14 * k, borderRadius: 2 * k,
          background: "#45464e" }} />
        <div style={{ position: "absolute", right: -2 * k, top: h / 2 - 7 * k, width: 5 * k, height: 14 * k, borderRadius: 2 * k,
          background: "#45464e" }} />
      </div>
    );
  };

type FlipCell = { kind: "digit" | "sep" | "text"; ch: string; di: number; role?: "pre" | "suf" };

/** Split-flap cards clatter through a full cycle, slow down and land on the figure; they tip back to exit. */
const FlipCounter: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const raw = num(overlay.value);
  if (!Number.isFinite(raw)) return null;
  let v = Math.abs(raw);
  let suffix = S(overlay.suffix).trim();
  if (v >= 1e10 && !suffix) {
    v = Math.round(v / 1e8) / 10;
    suffix = "B";
  }
  const year = Number.isInteger(v) && v >= 1500 && v <= 2100 && !suffix;
  const text = formatValue(v, !year).text;
  const digitCount = (text.match(/\d/g) || []).length;
  if (!digitCount || digitCount > 10) return null;
  const prefix = `${raw < 0 ? "−" : ""}${S(overlay.prefix).trim()}`;
  const CH = (digitCount > 7 ? 138 : digitCount > 5 ? 160 : 186) * k;
  const CW = CH * 0.64;
  const cells: FlipCell[] = [];
  if (prefix && prefix.length <= 2) cells.push({ kind: "text", ch: prefix, di: -1, role: "pre" });
  let di = 0;
  for (const c of Array.from(text)) {
    if (/\d/.test(c)) cells.push({ kind: "digit", ch: c, di: di++ });
    else cells.push({ kind: "sep", ch: c, di: -1 });
  }
  const sufCard = suffix && suffix.length <= 3 ? cap(suffix) : "";
  if (sufCard) cells.push({ kind: "text", ch: sufCard, di: -1, role: "suf" });
  const sufText = suffix && !sufCard ? cap(suffix) : "";
  const preText = prefix && prefix.length > 2 ? cap(prefix) : "";
  const stagger = digitCount > 6 ? 1.5 : 3;
  const flipF = Math.round(fps * 1.25);
  const start0 = Math.round(fps * 0.35);
  const lastLand = start0 + (digitCount - 1) * stagger + flipF;
  const rowW = cells.reduce((a, c) => a + (c.kind === "sep" ? CH * 0.16 : c.kind === "text"
    ? CW * (c.ch.length === 1 ? 0.9 : 0.55 + 0.42 * c.ch.length) : CW) + 10 * k, 0);
  // The cards tip back in turn; the stagger shrinks with the count so the last one is down by dur - 2.
  const outStagger = Math.min(0.9, 5 / Math.max(1, cells.length - 1));
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 22 * k,
        transform: `scale(${hold})` }}>
        {S(overlay.subtitle) ? (
          <div style={{ marginBottom: 14 * k }}><Head text={S(overlay.subtitle)} accent={accent} size={52} exit={exit} /></div>
        ) : null}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 10 * k, perspective: 1400 * k }}>
          {preText ? (
            <Letters text={oneLine(preText, 8)} at={start0} style={{ fontFamily: DISPLAY, fontSize: CH * 0.5, lineHeight: 1,
              color: accent, marginRight: 8 * k }} />
          ) : null}
          {cells.map((c, ci) => {
            const enter = ramp(frame, ci * 2, 14, backOut);
            const out = ramp(frame, dur - 16 + ci * outStagger, 9, expoIn);
            const wrap: React.CSSProperties = {
              transform: `translateY(${(1 - enter) * 50 * k}px) rotateX(${out * 92}deg)`, transformOrigin: "50% 100%",
              opacity: Math.min(1, Math.max(0, enter) * 1.6) * (out > 0.97 ? 0 : 1),
            };
            if (c.kind === "sep") {
              return (
                <div key={ci} style={{ ...wrap, width: CH * 0.16, textAlign: "center", fontFamily: DISPLAY, fontSize: CH * 0.5,
                  lineHeight: 1, color: "rgba(255,255,255,.72)", marginBottom: CH * 0.02 }}>{c.ch}</div>
              );
            }
            if (c.kind === "text") {
              const tAt = c.role === "pre" ? start0 : lastLand - 6;
              const tp = ramp(frame, tAt, 7, Easing.linear);
              const w = CW * (c.ch.length === 1 ? 0.9 : 0.55 + 0.42 * c.ch.length);
              return (
                <div key={ci} style={wrap}>
                  <FlapCard cur={tp >= 1 ? c.ch : ""} nxt={c.ch} phase={tp >= 1 ? 0 : tp} w={w} h={CH} color={accent}
                    size={CH * (c.ch.length > 1 ? 0.62 : 0.8)} />
                </div>
              );
            }
            const d = Number(c.ch);
            const st = start0 + c.di * stagger;
            const flips = d + 10;
            const p = flips * ramp(frame, st, flipF, Easing.bezier(0.33, 0.05, 0.22, 1));
            const idx = Math.min(flips, Math.floor(p));
            const phase = idx >= flips ? 0 : p - idx;
            return (
              <div key={ci} style={wrap}>
                <FlapCard cur={String(idx % 10)} nxt={String((idx + 1) % 10)} phase={phase} w={CW} h={CH} color="#f4f4f4"
                  size={CH * 0.84} />
              </div>
            );
          })}
          {sufText ? (
            <Letters text={oneLine(sufText, 15)} at={lastLand - 4} style={{ fontFamily: DISPLAY, fontSize: CH * 0.42,
              lineHeight: 1, color: accent, marginLeft: 10 * k, letterSpacing: "0.04em" }} />
          ) : null}
        </div>
        <div style={{ width: rowW, height: 34 * k, marginTop: -16 * k, opacity: ramp(frame, 4, 14) * (1 - ramp(frame, dur - 8, 6)),
          background: "radial-gradient(ellipse at 50% 0%, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 70%)" }} />
        <TextLines text={cap(overlay.text)} chars={36} max={2} at={Math.round(fps * 0.8)} style={{ fontFamily: LABEL,
          fontWeight: 800, fontSize: 36 * k, letterSpacing: "0.16em", color: "rgba(255,255,255,.9)", lineHeight: 1.1 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. countdown dial
/** A ring charges full, then drains backwards to the value; bezel ticks dim as it passes; the figure counts down. */
const CountdownDial: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const sc = scaleOf(overlay);
  if (!sc) return null;
  const { value, frac, max, pct, based } = sc;
  const R = 222 * k;
  const SW = 20 * k;
  const SZ = 2 * R + 150 * k;
  const c = SZ / 2;
  const drainAt = Math.round(fps * 0.8);
  const drainF = Math.round(fps * 1.5);
  const full = ramp(frame, 3, Math.round(fps * 0.55), inOut);
  const drain = ramp(frame, drainAt, drainF, inOut);
  const f = full * (1 - drain * (1 - frac)) * (1 - exit);
  const end = -90 + 360 * f;
  const pulseP = Math.round(fps * 0.9);
  const pulse = (frame % pulseP) / pulseP;
  const suffix = pct ? "%" : S(overlay.suffix).trim();
  const prefix = S(overlay.prefix).trim();
  const dec = decOf(value);
  const shown = based ? max - (max - value) * drain : value;
  const widest = fmtN(based ? Math.max(max, value) : value, dec);
  const nChars = widest.length + prefix.length * 0.7 + suffix.length * 0.5;
  const NSZ = Math.min(132, 330 / (0.42 * Math.max(2.5, nChars))) * k;
  const lostO = 0.5 * ramp(frame, drainAt, 12) * (1 - exit);
  const [hx, hy] = polar(c, c, R, end);
  // Kept inside the ring's ~350px inner circle: a big total is compacted, a long unit dropped.
  const ofMax = max >= 1e4 ? compact(max) : fmtN(max, decOf(max));
  const ofText = pct ? "OF 100%" : based ? `OF ${ofMax}${suffix && suffix.length <= 5 ? ` ${cap(suffix)}` : ""}` : "";
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 14 * k,
        transform: `scale(${hold})` }}>
        {S(overlay.subtitle) ? <Head text={S(overlay.subtitle)} accent={accent} size={52} exit={exit} /> : null}
        <div style={{ position: "relative", width: SZ, height: SZ, transform: `scale(${0.88 + 0.12 * ramp(frame, 0, 20)})` }}>
          <svg width={SZ} height={SZ} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <circle cx={c} cy={c} r={R} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth={SW}
              opacity={ramp(frame, 0, 10) * (1 - exit)} />
            {lostO > 0.01 && f < 0.999 ? (
              <path d={arcPath(c, c, R, end, 270)} fill="none" stroke={RED} strokeOpacity={lostO} strokeWidth={6 * k}
                strokeDasharray={`${3 * k} ${7 * k}`} />
            ) : null}
            {f > 0.002 ? (
              <path d={arcPath(c, c, R, -90, end)} fill="none" stroke={accent} strokeWidth={SW} strokeLinecap="round"
                style={{ filter: `drop-shadow(0 0 ${14 * k}px ${accent}aa)` }} />
            ) : null}
            {Array.from({ length: 60 }, (_, i) => {
              const deg = -90 + i * 6;
              const major = i % 5 === 0;
              const [x1, y1] = polar(c, c, R + 26 * k, deg);
              const [x2, y2] = polar(c, c, R + (major ? 52 : 38) * k, deg);
              const on = i / 60 < f - 0.0001;
              const o = ramp(frame, 2 + i * 0.3, 8) * (1 - ramp(frame, dur - 15 + (59 - i) * 0.12, 6));
              return (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={on ? "#fff" : "rgba(255,255,255,.22)"}
                  strokeWidth={(major ? 4 : 2) * k} strokeLinecap="round" opacity={o} />
              );
            })}
            <circle cx={c} cy={c} r={R - 46 * k} fill="none" stroke="rgba(255,255,255,.16)" strokeWidth={2 * k}
              strokeDasharray={`${1.5 * k} ${9 * k}`} transform={`rotate(${frame * 0.4} ${c} ${c})`}
              opacity={ramp(frame, 6, 12) * (1 - exit)} />
            {f > 0.01 ? (
              <g>
                <circle cx={hx} cy={hy} r={SW * (0.6 + pulse * 1.3)} fill="none" stroke={accent} strokeWidth={2.5 * k}
                  opacity={(1 - pulse) * 0.9} />
                <circle cx={hx} cy={hy} r={SW * 0.42} fill="#fff" />
              </g>
            ) : null}
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", gap: 6 * k }}>
            {based ? (
              <Letters text="REMAINING" at={drainAt - 6} step={0.5} style={{ fontFamily: MONO, fontWeight: 500,
                fontSize: 24 * k, letterSpacing: "0.32em", color: "rgba(255,255,255,.55)", marginLeft: "0.32em" }} />
            ) : null}
            <MaskIO pin={ramp(frame, Math.round(fps * 0.45), 16)} pout={exit}>
              {based ? (
                <div style={{ display: "flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: NSZ, lineHeight: 1,
                  color: "#fff", fontVariantNumeric: "tabular-nums" }}>
                  {prefix ? <span style={{ fontSize: NSZ * 0.55, marginTop: NSZ * 0.07, color: accent }}>{prefix}</span> : null}
                  <span>{fmtN(shown, dec)}</span>
                  {suffix ? (
                    <span style={{ fontSize: NSZ * 0.45, marginTop: NSZ * 0.07, marginLeft: NSZ * 0.03, color: accent }}>
                      {cap(suffix)}</span>
                  ) : null}
                </div>
              ) : (
                <Odometer value={value} at={drainAt} frames={drainF} size={NSZ} color="#fff" prefix={prefix}
                  suffix={suffix ? ` ${cap(suffix)}` : ""} suffixColor={accent} suffixScale={0.45} />
              )}
            </MaskIO>
            {ofText ? (
              <Letters text={ofText} at={drainAt} step={0.5} style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k,
                letterSpacing: "0.22em", color: "rgba(255,255,255,.5)" }} />
            ) : null}
          </div>
        </div>
        <TextLines text={cap(overlay.text)} chars={34} max={2} at={drainAt + 8} style={{ fontFamily: LABEL, fontWeight: 800,
          fontSize: 34 * k, letterSpacing: "0.16em", color: "rgba(255,255,255,.9)", lineHeight: 1.1 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. battery
/** A battery outline draws on, charges full, then drains to the percent, shifting green > accent > red. */
const BatteryLevel: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const sc = scaleOf(overlay);
  if (!sc) return null;
  const { value, max, pct, based } = sc;
  let frac = sc.frac;
  if (!based) {
    // No "%" and no total: a bare 0-100 figure reads as a charge; a figure with another unit ("50 FT") does not.
    const unit = S(overlay.suffix).trim();
    if (unit && !/^(pct|percent|per ?cent)$/i.test(unit)) return null;
    if (value >= 0 && value <= 100) frac = value / 100;
    else return null;
  }
  const charging = /^(up|charg|rise|gain|grow)/i.test(S(overlay.label).trim());
  const at = Math.round(fps * 0.75);
  const F = Math.round(fps * 1.5);
  const g = ramp(frame, at, F, inOut);
  const pre = ramp(frame, Math.round(fps * 0.2), Math.round(fps * 0.45), inOut);
  const lvlHold = clamp01(charging ? frac * g : pre * (1 - (1 - frac) * g));
  const level = lvlHold * (1 - exit);
  const col = mix(lvlHold, [0, 0.2, 0.5, 0.8, 1], [RED, RED, accent, GREEN, GREEN]);
  const BW = 520 * k;
  const BH = 232 * k;
  const RX = 42 * k;
  const NUBW = 26 * k;
  const NUBH = 92 * k;
  const o = 10 * k;
  const IP = 16 * k;
  const ix = o + IP;
  const iy = o + IP;
  const iw = BW - 2 * IP;
  const ih = BH - 2 * IP;
  const irx = RX - IP * 0.8;
  const svgW = o + BW + NUBW + 14 * k;
  const svgH = BH + 2 * o;
  const draw = ramp(frame, 0, Math.round(fps * 0.55), inOut) * (1 - exit);
  const nub = ramp(frame, Math.round(fps * 0.4), 12, backOut) * (1 - exit);
  const low = !charging && frac <= 0.25;
  const warn = low ? ramp(frame, at + F - 8, 10) * (0.5 + 0.5 * Math.sin(frame * 0.32)) * (1 - exit) : 0;
  const stroke = warn > 0 ? mix(warn, [0, 1], ["#f2f2f2", RED]) : "#f2f2f2";
  const fw = iw * clamp01(level);
  const span = iw + 280 * k;
  const sheenX = ix - 140 * k + ((frame * 7 * k) % span);
  const id = `ncbat${overlay.startFrame}`;
  const bw = 96 * k;
  const bh = 150 * k;
  const bolt = [[0.58, 0], [0.12, 0.56], [0.44, 0.56], [0.34, 1], [0.86, 0.4], [0.54, 0.4], [0.7, 0]]
    .map(([px, py]) => `${(o + BW / 2 - bw / 2 + px * bw).toFixed(1)},${(o + BH / 2 - bh / 2 + py * bh).toFixed(1)}`).join(" ");
  const boltO = charging ? ramp(frame, at, 12) * (0.75 + 0.25 * Math.sin(frame * 0.25)) * (1 - exit) : 0;
  const NS = 176 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 40 * k,
        transform: `scale(${hold})` }}>
        {S(overlay.subtitle) ? <Head text={S(overlay.subtitle)} accent={accent} size={52} exit={exit} /> : null}
        <div style={{ display: "flex", alignItems: "center", gap: 80 * k }}>
          <svg width={svgW} height={svgH} style={{ overflow: "visible", display: "block" }}>
            <defs>
              <clipPath id={`${id}c`}><rect x={ix} y={iy} width={iw} height={ih} rx={irx} /></clipPath>
              <clipPath id={`${id}f`}><rect x={ix} y={iy} width={Math.max(0, fw)} height={ih} /></clipPath>
              <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor="#fff" stopOpacity={0} />
                <stop offset="0.5" stopColor="#fff" stopOpacity={0.32} />
                <stop offset="1" stopColor="#fff" stopOpacity={0} />
              </linearGradient>
              <linearGradient id={`${id}v`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#fff" stopOpacity={0.3} />
                <stop offset="0.45" stopColor="#fff" stopOpacity={0.04} />
                <stop offset="1" stopColor="#000" stopOpacity={0.2} />
              </linearGradient>
            </defs>
            {warn > 0 ? (
              <rect x={o} y={o} width={BW} height={BH} rx={RX} fill="none" stroke={RED} strokeOpacity={0.28 * warn}
                strokeWidth={30 * k} />
            ) : null}
            <rect x={o} y={o} width={BW} height={BH} rx={RX} fill="rgba(255,255,255,.05)" opacity={draw} />
            <g style={{ filter: fw > 2 * k ? `drop-shadow(0 0 ${16 * k}px ${col})` : undefined }}>
              <g clipPath={`url(#${id}c)`}>
                <rect x={ix} y={iy} width={Math.max(0, fw)} height={ih} fill={col} />
                <rect x={ix} y={iy} width={Math.max(0, fw)} height={ih} fill={`url(#${id}v)`} />
                {fw > 20 * k ? (
                  <g clipPath={`url(#${id}f)`}>
                    <rect x={sheenX} y={iy} width={140 * k} height={ih} fill={`url(#${id}s)`} />
                  </g>
                ) : null}
                {fw > 2 * k ? (
                  <line x1={ix + fw} x2={ix + fw} y1={iy} y2={iy + ih} stroke="#fff" strokeOpacity={0.75} strokeWidth={3 * k} />
                ) : null}
              </g>
            </g>
            {[0.25, 0.5, 0.75].map((t) => (
              <line key={t} x1={ix + iw * t} x2={ix + iw * t} y1={iy + 12 * k} y2={iy + ih - 12 * k} stroke="rgba(0,0,0,.32)"
                strokeWidth={4 * k} opacity={draw} />
            ))}
            <rect x={o} y={o} width={BW} height={BH} rx={RX} fill="none" stroke={stroke} strokeWidth={9 * k} pathLength={1}
              strokeDasharray="1" strokeDashoffset={1 - draw} />
            <rect x={o + BW + 6 * k} y={o + BH / 2 - NUBH / 2} width={Math.max(0, NUBW * nub)} height={NUBH} rx={8 * k}
              fill={stroke} />
            {boltO > 0 ? <polygon points={bolt} fill="#fff" stroke={INK} strokeWidth={5 * k} strokeLinejoin="round"
              opacity={boltO} /> : null}
          </svg>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 12 * k, maxWidth: 560 * k }}>
            <MaskIO pin={ramp(frame, at - 10, 16)} pout={exit}>
              <div style={{ display: "flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: NS, lineHeight: 1,
                color: "#fff", fontVariantNumeric: "tabular-nums" }}>
                <span>{Math.round(lvlHold * 100)}</span>
                <span style={{ fontSize: NS * 0.5, marginTop: NS * 0.07, marginLeft: 6 * k, color: col }}>%</span>
              </div>
            </MaskIO>
            {based && !pct ? (
              <Letters text={`${fmtN(value, decOf(value))} OF ${fmtN(max, decOf(max))}`} at={at} step={0.5}
                style={{ fontFamily: MONO, fontWeight: 500, fontSize: 26 * k, letterSpacing: "0.18em", color: "rgba(255,255,255,.6)" }} />
            ) : null}
            <TextLines text={cap(overlay.text)} chars={22} max={2} at={at + 10} align="left" style={{ fontFamily: LABEL,
              fontWeight: 800, fontSize: 38 * k, letterSpacing: "0.1em", color: "rgba(255,255,255,.9)", lineHeight: 1.05 }} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. thermometer
/** A glass thermometer: mercury springs up a degree scale, shifting cool > accent > hot, the reading riding its top. */
const Thermometer: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const value = num(overlay.value);
  if (!Number.isFinite(value)) return null;
  const rawSuf = S(overlay.suffix).trim();
  const unit = rawSuf.replace(/°|º|degrees?|deg/gi, "").trim().toUpperCase();
  const isF = unit === "F";
  const isC = unit === "C";
  const suf = isF ? "°F" : isC ? "°C" : rawSuf;
  let lo: number;
  let hi: number;
  if (isF) {
    lo = Math.min(0, value - 10);
    hi = Math.max(120, value + 10);
  } else if (isC) {
    lo = Math.min(-10, value - 5);
    hi = Math.max(50, value + 5);
  } else {
    lo = Math.min(0, value * 1.25);
    hi = Math.max(value * 1.25, 1);
  }
  const step = niceStep(hi - lo, 6);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  if (!(hi > lo) || (hi - lo) / step > 12) return null;
  const TH = 500 * k;
  const TW = 58 * k;
  const BR = 54 * k;
  const MW = 24 * k;
  const MBR = 38 * k;
  const tx = 150 * k;
  const top = 30 * k;
  const hw = TW / 2;
  const yi = Math.sqrt(BR * BR - hw * hw);
  const by = top + TH + yi;
  const svgW = tx + hw + 70 * k;
  const svgH = by + BR + 16 * k;
  const yTop = top + 44 * k;
  const yBot = top + TH - 26 * k;
  const yOf = (t: number) => yBot - ((t - lo) / (hi - lo)) * (yBot - yTop);
  const at = Math.round(fps * 0.5);
  const sp = spring({ frame: Math.max(0, frame - at), fps, config: { damping: 10, stiffness: 48, mass: 1 } });
  const curHold = lo + (value - lo) * Math.min(1.03, sp);
  const cur = lo + (curHold - lo) * (1 - exit);
  const lf = clamp01((curHold - lo) / (hi - lo));
  const col = mix(lf, [0, 0.42, 0.72, 1], [CYAN, accent, RED, RED]);
  const my = yOf(cur);
  const draw = ramp(frame, 0, Math.round(fps * 0.6), inOut) * (1 - exit);
  const hot = (value - lo) / (hi - lo) > 0.72;
  const glowP = hot ? ramp(frame, at + Math.round(fps * 0.8), 14) * (0.75 + 0.25 * Math.sin(frame * 0.2)) * (1 - exit) : 0;
  const nTicks = Math.round(((hi - lo) / step) * 5);
  const dec = decOf(value);
  const id = `ncth${overlay.startFrame}`;
  const glass = `M${tx - hw} ${by - yi} V${top + hw} A${hw} ${hw} 0 0 1 ${tx + hw} ${top + hw} V${by - yi} ` +
    `A${BR} ${BR} 0 1 1 ${tx - hw} ${by - yi} Z`;
  const ptr = ramp(frame, at - 4, 12);
  const RS = 112 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 70 * k }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 14 * k, width: 600 * k }}>
            {S(overlay.subtitle) ? (
              <Letters text={oneLine(cap(overlay.subtitle), 26)} at={4} step={0.6} style={{ fontFamily: LABEL,
                fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.24em", color: accent }} />
            ) : null}
            <div style={{ width: ramp(frame, 6, 16) * 110 * k * (1 - exit), height: 5 * k, background: accent }} />
            <TextLines text={cap(overlay.text)} chars={18} max={3} at={8} align="left" style={{ fontFamily: DISPLAY,
              fontSize: 66 * k, lineHeight: 1, color: "#fff", letterSpacing: "0.02em", textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
          </div>
          <div style={{ position: "relative", width: svgW + 430 * k, height: svgH, opacity: 1 - ramp(frame, dur - 5, 4),
            transform: `translateY(${(1 - ramp(frame, 0, 18)) * 30 * k}px)` }}>
            <svg width={svgW} height={svgH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <radialGradient id={`${id}g`}>
                  <stop offset="0" stopColor={RED} stopOpacity={0.55} />
                  <stop offset="1" stopColor={RED} stopOpacity={0} />
                </radialGradient>
                <clipPath id={`${id}c`}><path d={glass} /></clipPath>
              </defs>
              {glowP > 0 ? <circle cx={tx} cy={by} r={BR * 2.6} fill={`url(#${id}g)`} opacity={glowP} /> : null}
              <path d={glass} fill="rgba(255,255,255,.07)" opacity={draw} />
              <rect x={tx - MW / 2 - 3 * k} y={top + 12 * k} width={MW + 6 * k} height={by - top - 12 * k} rx={(MW + 6 * k) / 2}
                fill="rgba(0,0,0,.4)" opacity={draw} />
              <g clipPath={`url(#${id}c)`} opacity={ramp(frame, 6, 10)}>
                <rect x={tx - MW / 2} y={my} width={MW} height={Math.max(0, by - my)} rx={MW / 2} fill={col} />
                <rect x={tx - MW / 2 + 4 * k} y={my + 6 * k} width={5 * k} height={Math.max(0, by - my - 40 * k)} rx={2.5 * k}
                  fill="#fff" opacity={0.35} />
                <circle cx={tx} cy={by} r={MBR} fill={col} />
              </g>
              <path d={glass} fill="none" stroke="rgba(255,255,255,.88)" strokeWidth={4 * k} pathLength={1}
                strokeDasharray="1" strokeDashoffset={1 - draw} />
              <line x1={tx - hw + 11 * k} x2={tx - hw + 11 * k} y1={top + hw} y2={by - yi - 12 * k} stroke="#fff"
                strokeOpacity={0.22 * draw} strokeWidth={5 * k} strokeLinecap="round" />
              <ellipse cx={tx - BR * 0.36} cy={by - BR * 0.34} rx={BR * 0.16} ry={BR * 0.26} fill="#fff" opacity={0.4 * draw}
                transform={`rotate(-32 ${tx - BR * 0.36} ${by - BR * 0.34})`} />
              {Array.from({ length: nTicks + 1 }, (_, i) => {
                const tv = lo + (i * step) / 5;
                const y = yOf(tv);
                const major = i % 5 === 0;
                const op = ramp(frame, 4 + i * 0.7, 8) * (1 - ramp(frame, dur - 15 + (nTicks - i) * 0.2, 6));
                const passed = tv <= cur + 1e-9;
                return (
                  <g key={i} opacity={op}>
                    <line x1={tx - hw - 10 * k} x2={tx - hw - (major ? 40 : 24) * k} y1={y} y2={y}
                      stroke={passed ? "#fff" : "rgba(255,255,255,.45)"} strokeWidth={(major ? 3.5 : 2) * k} strokeLinecap="round" />
                    {major ? (
                      <text x={tx - hw - 52 * k} y={y} textAnchor="end" dominantBaseline="central" fontFamily={LABEL}
                        fontWeight={700} fontSize={26 * k} fill={passed ? "#fff" : "rgba(255,255,255,.6)"}>
                        {`${fmtN(tv, Number.isInteger(tv) ? 0 : 1)}${isF || isC ? "°" : ""}`}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </svg>
            <div style={{ position: "absolute", left: tx + hw + 14 * k, top: my - RS / 2, display: "flex", alignItems: "center",
              gap: 14 * k, opacity: 1 - exit }}>
              <svg width={46 * k} height={20 * k} style={{ overflow: "visible", display: "block", transform: `scaleX(${ptr})`,
                transformOrigin: "0 50%" }}>
                <path d={`M0 ${10 * k} L${15 * k} ${2 * k} L${15 * k} ${18 * k} Z`} fill={col} />
                <line x1={13 * k} x2={46 * k} y1={10 * k} y2={10 * k} stroke={col} strokeWidth={3 * k} />
              </svg>
              <MaskIO pin={ramp(frame, at - 4, 14)} pout={exit}>
                <div style={{ display: "flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: RS, lineHeight: 1,
                  color: "#fff", textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>
                  <span>{fmtN(curHold, dec)}</span>
                  {suf ? <span style={{ fontSize: RS * 0.46, marginTop: RS * 0.07, marginLeft: 6 * k, color: col }}>{suf}</span> : null}
                </div>
              </MaskIO>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. population clock (tag)
/** Lower-left on the footage: the figure lands like an odometer, then keeps ticking up live. */
const PopulationClock: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const raw = num(overlay.value);
  if (!Number.isFinite(raw) || raw < 1 || raw >= 1e13) return null;
  const value = Math.round(raw);
  // Ticks per second while live: ~3/s at 8.1 billion, close to the real net growth of the world population
  // (~2.5 people a second), so the "LIVE" readout is not visibly invented; 1/s for smaller counts.
  const rate = value >= 1e9 ? Math.max(1, Math.min(6, Math.round(value / 3.2e9))) : 1;
  const maxV = value + Math.ceil((rate * dur) / fps) + 1;
  const nd = String(maxV).length;
  const size = (nd > 10 ? 100 : nd > 7 ? 118 : 132) * k;
  const at = Math.round(fps * 0.4);
  const L = Math.round(fps * 1.0);
  const liveAt = at + Math.ceil((nd - 1) * 1.5) + L;
  const live = frame >= liveAt;
  const V = value + (rate * Math.max(0, frame - liveAt)) / fps;
  const base = Math.floor(V);
  const trans = interpolate(V - base, [0.35, 0.95], [0, 1], { ...clamp, easing: expoOut });
  const shownLen = String(live ? base : value).length;
  const cols = Array.from({ length: nd }, (_, j) => {
    const ri = nd - 1 - j;
    const pw = Math.pow(10, ri);
    let pos: number;
    if (!live) {
      const d = Math.floor(value / pw) % 10;
      pos = ramp(frame, at + ri * 1.5, L) * ((1 + Math.min(3, ri)) * 10 + d);
    } else {
      const d = Math.floor(base / pw) % 10;
      const carry = ri === 0 || base % pw === pw - 1;
      pos = d + (carry ? trans : 0);
    }
    return { ri, pos, visible: ri < shownLen, comma: ri > 0 && ri % 3 === 0 };
  });
  const blink = 0.5 + 0.5 * Math.sin(frame * 0.25);
  const ringP = (frame % fps) / fps;
  const sweep = live ? ((frame - liveAt) % fps) / fps : 0;
  const full = Boolean(overlay.fullFrame);
  return (
    <AbsoluteFill>
      {!full ? (
        <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * (1 - exit),
          background: "radial-gradient(ellipse 70% 60% at 10% 92%, rgba(0,0,0,.66) 0%, rgba(0,0,0,.34) 42%, rgba(0,0,0,0) 72%)" }} />
      ) : null}
      <div style={{ position: "absolute", left: 110 * k, bottom: 118 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start", gap: 8 * k, transform: `translateY(${exit * 16 * k}px)` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
          <div style={{ position: "relative", width: 16 * k, height: 16 * k,
            transform: `scale(${Math.max(0, ramp(frame, 2, 12, backOut) * (1 - exit))})` }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: CYAN, opacity: 0.6 + 0.4 * blink,
              boxShadow: `0 0 ${10 * k}px ${CYAN}` }} />
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `${2 * k}px solid ${CYAN}`,
              transform: `scale(${1 + ringP * 1.8})`, opacity: 1 - ringP }} />
          </div>
          <Letters text="LIVE" at={3} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.3em",
            color: CYAN }} />
          {S(overlay.subtitle) ? (
            <>
              <div style={{ width: 2 * k, height: 26 * k * ramp(frame, 6, 10) * (1 - exit), background: "rgba(255,255,255,.4)" }} />
              <Letters text={oneLine(cap(overlay.subtitle), 32)} at={6} step={0.6} style={{ fontFamily: LABEL,
                fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.18em", color: "#fff",
                textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
            </>
          ) : null}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 18 * k }}>
          <div style={{ width: 6 * k, height: size * 0.9 * ramp(frame, at - 6, 14) * (1 - exit), background: accent,
            boxShadow: `0 0 ${14 * k}px ${accent}88` }} />
          <MaskIO pin={ramp(frame, at - 4, 14)} pout={exit}>
            <div style={{ display: "flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: size, lineHeight: 1,
              color: "#fff", letterSpacing: "0.01em", textShadow: "0 6px 26px rgba(0,0,0,.45)" }}>
              {cols.map((c) => (c.visible ? (
                <React.Fragment key={c.ri}>
                  <span style={{ display: "inline-block", height: size, overflow: "hidden" }}>
                    <span style={{ display: "flex", flexDirection: "column", transform: `translateY(${-(c.pos % 10) * size}px)` }}>
                      {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0].map((d, q) => (
                        <span key={q} style={{ height: size, display: "block" }}>{d}</span>
                      ))}
                    </span>
                  </span>
                  {c.comma ? <span style={{ color: "rgba(255,255,255,.55)" }}>,</span> : null}
                </React.Fragment>
              ) : null))}
            </div>
          </MaskIO>
        </div>
        <div style={{ position: "relative", alignSelf: "stretch", height: 2 * k, background: "rgba(255,255,255,.16)",
          overflow: "hidden", transform: `scaleX(${ramp(frame, at, 18) * (1 - exit)})`, transformOrigin: "0 50%" }}>
          {live ? (
            <div style={{ position: "absolute", top: 0, bottom: 0, width: 160 * k, left: `${sweep * 100}%`,
              transform: "translateX(-100%)", background: `linear-gradient(90deg, rgba(83,200,255,0), ${CYAN})` }} />
          ) : null}
        </div>
        <TextLines text={S(overlay.text)} chars={40} max={2} at={at + 12} align="left" style={{ fontFamily: LABEL,
          fontWeight: 600, fontSize: 32 * k, letterSpacing: "0.04em", color: "rgba(255,255,255,.9)", lineHeight: 1.1,
          textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. burst number
/** The figure slams in: anticipation ring, flash, camera shake, two shockwaves, a radial spark burst, drifting embers. */
const BurstNumber: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const value = num(overlay.value);
  if (!Number.isFinite(value)) return null;
  const suffix = S(overlay.suffix).trim();
  const prefix = S(overlay.prefix).trim();
  const year = Number.isInteger(value) && value >= 1500 && value <= 2100 && !suffix;
  const txt = formatValue(value, !year).text;
  const len = prefix.length * 0.7 + txt.length + suffix.length * 0.6;
  const size = Math.max(110, Math.min(200, 1250 / (0.42 * Math.max(3, len)))) * k;
  const I = Math.round(fps * 0.5);
  const since = frame - I;
  const cx = width / 2;
  const cy = height / 2;
  const slam = interpolate(frame, [I - 5, I, I + 4, I + 10], [2.5, 0.93, 1.035, 1], clamp);
  const slamO = interpolate(frame, [I - 5, I - 2], [0, 1], clamp);
  const blur = interpolate(frame, [I - 5, I], [12, 0], clamp) * k;
  const shake = since >= 0 ? 15 * k * Math.exp(-since / 3.5) : 0;
  const dx = shake * Math.sin(since * 2.4);
  const dy = shake * Math.cos(since * 3.1);
  const flash = interpolate(frame, [I - 1, I, I + 9], [0, 0.5, 0], clamp);
  const r1 = ramp(frame, I, 22);
  const r2 = ramp(frame, I + 3, 26);
  const pre = interpolate(frame, [0, I], [0, 1], { ...clamp, easing: Easing.bezier(0.55, 0, 1, 0.45) });
  const preO = interpolate(frame, [0, 6, I - 3, I], [0, 0.75, 0.75, 0], clamp);
  const glow = ramp(frame, I, 14) * (0.85 + 0.15 * Math.sin(frame * 0.14)) * (1 - exit);
  const EY = 0.82;
  const streaksIn = Array.from({ length: 12 }, (_, i) => {
    const a = (i / 12) * Math.PI * 2 + 0.26;
    const q = interpolate(frame, [I - 12, I], [0, 1], { ...clamp, easing: Easing.bezier(0.55, 0, 1, 0.45) });
    const op = interpolate(frame, [I - 12, I - 8, I - 1, I], [0, 0.7, 0.7, 0], clamp);
    if (op <= 0) return null;
    const r0 = 560 * k * (1 - q) + 70 * k;
    const ln = (50 + 90 * q) * k;
    return (
      <line key={`in${i}`} x1={cx + Math.cos(a) * r0} y1={cy + Math.sin(a) * r0 * EY} x2={cx + Math.cos(a) * (r0 + ln)}
        y2={cy + Math.sin(a) * (r0 + ln) * EY} stroke="#fff" strokeOpacity={op} strokeWidth={2.5 * k} strokeLinecap="round" />
    );
  });
  const sparks = Array.from({ length: 34 }, (_, i) => {
    if (since < 0) return null;
    const a = (i / 34) * Math.PI * 2 + (rnd(i) - 0.5) * 0.4;
    const dist = (240 + rnd(i + 7) * 560) * k;
    const life = 18 + Math.round(rnd(i + 13) * 16);
    const t = interpolate(frame, [I, I + life], [0, 1], clamp);
    if (t >= 1) return null;
    const q = ramp(frame, I, life);
    const r = 60 * k + dist * q;
    const fall = 50 * k * t * t * rnd(i + 5);
    const hx = cx + Math.cos(a) * r;
    const hy = cy + Math.sin(a) * r * EY + fall;
    const colr = i % 3 === 0 ? "#fff" : accent;
    const op = (1 - t) * (1 - exit);
    if (i % 4 === 0) {
      return <circle key={`p${i}`} cx={hx} cy={hy} r={(3 + rnd(i + 11) * 4) * k * (1 - t * 0.5)} fill={colr} opacity={op} />;
    }
    const ln = (16 + 110 * (1 - q)) * k * (0.6 + rnd(i + 3) * 0.8);
    return (
      <line key={`p${i}`} x1={hx - Math.cos(a) * ln} y1={hy - Math.sin(a) * ln * EY} x2={hx} y2={hy} stroke={colr}
        strokeWidth={(2 + rnd(i + 9) * 3) * k} strokeLinecap="round" opacity={op} />
    );
  });
  const embers = Array.from({ length: 12 }, (_, i) => {
    if (since < 8) return null;
    const range = 380 * k;
    const spd = (18 + rnd(i + 41) * 26) * k;
    const ph = ((((since / fps) * spd + rnd(i + 42) * range) % range) + range) % range / range;
    const x0 = cx + (rnd(i + 40) - 0.5) * 1000 * k + Math.sin(frame * 0.03 + i) * 12 * k;
    const y = cy + 190 * k - ph * range;
    const op = Math.sin(Math.PI * ph) * ramp(frame, I + 8 + i, 14) * (1 - exit) * (0.35 + 0.35 * (0.5 + 0.5 * Math.sin(frame * 0.2 + i)));
    return <circle key={`e${i}`} cx={x0} cy={y} r={(2 + rnd(i + 43) * 2.5) * k} fill={accent} opacity={op} />;
  });
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ opacity: glow,
        background: `radial-gradient(ellipse 34% 26% at 50% 50%, ${accent}44 0%, ${accent}00 100%)` }} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
        {preO > 0 ? (
          <circle cx={cx} cy={cy} r={Math.max(0, (480 - 440 * pre) * k)} fill="none" stroke={accent} strokeWidth={3 * k}
            opacity={preO} />
        ) : null}
        {streaksIn}
        {since >= 0 && r1 < 1 ? (
          <circle cx={cx} cy={cy} r={(80 + 660 * r1) * k} fill="none" stroke="#fff" strokeWidth={(1 + 12 * (1 - r1)) * k}
            opacity={(1 - r1) * 0.9} />
        ) : null}
        {since >= 3 && r2 < 1 ? (
          <circle cx={cx} cy={cy} r={(60 + 470 * r2) * k} fill="none" stroke={accent} strokeWidth={(1 + 8 * (1 - r2)) * k}
            opacity={1 - r2} />
        ) : null}
        {sparks}
        {embers}
      </svg>
      {flash > 0 ? (
        <AbsoluteFill style={{ opacity: flash,
          background: "radial-gradient(circle at 50% 50%, rgba(255,255,255,.9) 0%, rgba(255,255,255,0) 45%)" }} />
      ) : null}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16 * k,
        transform: `scale(${hold})` }}>
        {S(overlay.subtitle) ? (
          <Letters text={oneLine(cap(overlay.subtitle), 44)} at={I + 6} step={0.6} style={{ fontFamily: LABEL,
            fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.3em", color: accent, marginLeft: "0.3em" }} />
        ) : null}
        <div style={{ transform: `translate(${dx}px, ${dy}px) scale(${slam})`, opacity: slamO,
          filter: blur > 0.3 ? `blur(${blur}px)` : undefined }}>
          <MaskIO pin={1} pout={exit}>
            <div style={{ display: "flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: size, lineHeight: 1,
              color: "#fff", letterSpacing: "0.01em", textShadow: `0 0 ${36 * k}px ${accent}66` }}>
              {prefix ? <span style={{ fontSize: size * 0.6, marginTop: size * 0.08, marginRight: size * 0.03, color: accent }}>
                {prefix}</span> : null}
              <span>{`${value < 0 ? "−" : ""}${txt.replace("-", "")}`}</span>
              {suffix ? <span style={{ fontSize: size * 0.55, marginTop: size * 0.06, marginLeft: size * 0.04, color: accent }}>
                {cap(suffix)}</span> : null}
            </div>
          </MaskIO>
        </div>
        <div style={{ width: ramp(frame, I + 8, 16) * 240 * k * (1 - exit), height: 4 * k, background: accent,
          boxShadow: `0 0 ${12 * k}px ${accent}` }} />
        <TextLines text={cap(overlay.text)} chars={32} max={2} at={I + 12} style={{ fontFamily: LABEL, fontWeight: 700,
          fontSize: 38 * k, letterSpacing: "0.12em", color: "rgba(255,255,255,.92)", lineHeight: 1.1 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. segmented meter
/** Twenty slanted segments light in sequence past the value, fall back to it; a white peak-hold segment drops after. */
const SegmentMeter: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const sc = scaleOf(overlay);
  if (!sc) return null;
  const { value, frac, max, pct, based } = sc;
  const NS = 20;
  const tgt = frac * NS;
  const A = Math.round(fps * 0.45);
  const upF = Math.round(fps * 0.9);
  const setF = Math.round(fps * 0.45);
  const peakV = Math.min(NS, tgt + 2.5);
  const up = ramp(frame, A, upF, inOut) * peakV;
  const settle = ramp(frame, A + upF, setF, expoOut);
  const base = frame < A + upF ? up : peakV + (tgt - peakV) * settle;
  const settled = ramp(frame, A + upF + setF, 12);
  const wob = settled * 0.16 * Math.sin(frame * 0.33) * Math.sin(frame * 0.07 + 1);
  const off = ramp(frame, dur - 15, 11, inOut);
  const Lv = Math.max(0, (base + wob) * (1 - off));
  const holdEnd = A + upF + Math.round(fps * 0.7);
  const pf = ramp(frame, holdEnd, Math.round(fps * 0.4), expoIn);
  const peak = frame < A + upF ? up : peakV + (tgt - peakV) * pf;
  const peakIdx = Math.ceil(peak - 0.001) - 1;
  const SWd = 44 * k;
  const GP = 14 * k;
  const MH = 250 * k;
  const MW = NS * SWd + (NS - 1) * GP;
  const suf = S(overlay.suffix).trim();
  const unit = suf ? ` ${cap(suf)}` : "";
  const suffix = pct ? "%" : based ? `/${compact(max)}${suf.length <= 4 ? unit : ""}` : suf.length <= 10 ? unit : "";
  const prefix = S(overlay.prefix).trim();
  // The readout shares the header row with the title column (<= 56% of the meter): keep it under ~440px.
  const nChars = formatValue(value).text.length + prefix.length * 0.7 + suffix.length * 0.5;
  const OS = Math.min(150, 440 / (0.42 * Math.max(2.5, nChars))) * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ width: MW, display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 36 * k }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 * k, maxWidth: MW * 0.56 }}>
              {S(overlay.subtitle) ? (
                <Letters text={oneLine(cap(overlay.subtitle), 28)} at={2} step={0.6} style={{ fontFamily: LABEL,
                  fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.24em", color: accent }} />
              ) : null}
              <TextLines text={cap(overlay.text)} chars={22} max={2} at={6} align="left" style={{ fontFamily: DISPLAY,
                fontSize: 60 * k, lineHeight: 1, color: "#fff", letterSpacing: "0.02em", textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
            </div>
            <MaskIO pin={ramp(frame, A - 4, 14)} pout={exit}>
              <Odometer value={value} at={A} frames={upF + setF} size={OS} color="#fff" prefix={prefix}
                suffix={suffix} suffixColor={accent} suffixScale={0.5} />
            </MaskIO>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: GP, height: MH, transform: "skewX(-12deg)",
            transformOrigin: "50% 100%" }}>
            {Array.from({ length: NS }, (_, i) => {
              const h = (0.4 + 0.6 * (i / (NS - 1))) * MH;
              const lit = clamp01(Lv - i);
              const on = lit > 0.001;
              const edge = on ? clamp01(1 - Math.abs(Lv - (i + 0.6)) / 1.3) : 0;
              const isPeak = off < 0.01 && i === peakIdx && lit < 0.35 && frame >= A && peak > 0.05;
              const appear = ramp(frame, 2 + i * 0.8, 12, backOut);
              // Exit: the housings fold down right to left, chasing the light as it drains back (all gone by dur - 2).
              const fold = ramp(frame, dur - 14 + (NS - 1 - i) * 0.25, 7, expoIn);
              return (
                <div key={i} style={{ position: "relative", width: SWd, height: h,
                  transform: `scaleY(${Math.max(0, appear * (1 - fold))})`,
                  transformOrigin: "50% 100%", borderRadius: 5 * k, background: "rgba(255,255,255,.06)",
                  boxShadow: `inset 0 0 0 ${1.5 * k}px rgba(255,255,255,.13)` }}>
                  {on || isPeak ? (
                    <div style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, borderRadius: 5 * k,
                      background: on ? accent : "#fff", opacity: on ? 0.3 + 0.7 * lit : 0.85,
                      boxShadow: on ? `0 0 ${(12 + 22 * edge) * k}px ${accent}${edge > 0.3 ? "dd" : "77"}`
                        : `0 0 ${14 * k}px rgba(255,255,255,.7)` }} />
                  ) : null}
                  {edge > 0.05 ? (
                    <div style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, borderRadius: 5 * k,
                      background: "#fff", opacity: edge * 0.5 }} />
                  ) : null}
                </div>
              );
            })}
          </div>
          <div style={{ width: MW * ramp(frame, 0, 20, inOut) * (1 - off), height: 2 * k, marginTop: 12 * k,
            background: "rgba(255,255,255,.3)" }} />
          <div style={{ position: "relative", width: MW, height: 40 * k, marginTop: 10 * k }}>
            {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
              <div key={i} style={{ position: "absolute", top: 0, left: t * MW,
                transform: `translateX(${t === 0 ? 0 : t === 1 ? -100 : -50}%)` }}>
                <MaskIO pin={ramp(frame, 8 + i * 3, 12)} pout={exit}>
                  <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.5)" }}>
                    {pct ? `${Math.round(t * 100)}%` : compact(max * t)}
                  </span>
                </MaskIO>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. stopwatch
/** An analog stopwatch: the crown clicks, the hand sweeps, the chrono readout runs and stops on the duration. */
const Stopwatch: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const value = num(overlay.value);
  if (!Number.isFinite(value) || value < 0 || value > 1e7) return null;
  const u = S(overlay.suffix).toLowerCase().replace(/\./g, "").trim();
  const mode = /^(s|sec|secs|second|seconds)$/.test(u) ? "sec" : /^(min|mins|minute|minutes)$/.test(u) ? "min"
    : /^(h|hr|hrs|hour|hours)$/.test(u) ? "hr" : "other";
  const at = Math.round(fps * 0.5);
  const F = Math.round(fps * 1.7);
  const p = ramp(frame, at, F, Easing.bezier(0.3, 0, 0.12, 1));
  const stopAt = at + Math.round(F * 0.78);
  let mainVal: number;
  let subVal: number;
  let subPer: number;
  if (mode === "sec") {
    mainVal = value;
    subVal = value / 60;
    subPer = 30;
  } else if (mode === "min") {
    mainVal = value;
    subVal = value / 60;
    subPer = 12;
  } else if (mode === "hr") {
    mainVal = value * 60;
    subVal = value;
    subPer = 12;
  } else {
    mainVal = 120 + (value % 60);
    subVal = mainVal / 60;
    subPer = 30;
  }
  const revs = mainVal / 60;
  const shownRevs = revs > 3 ? 3 + (revs % 1) : revs;
  const mainDeg = 360 * shownRevs * p;
  const subDeg = 360 * (subVal / subPer) * p;
  const T = value * p;
  let readout = "";
  let units: string[] = [];
  if (mode === "sec" && value < 3600) {
    const cs = Math.round(T * 100); // whole centiseconds: (12.29 * 100) % 100 floors to 28
    readout = `${pad2(cs / 6000)}:${pad2((cs / 100) % 60)}.${pad2(cs % 100)}`;
    units = ["MIN", "SEC", "1/100"];
  } else if (mode !== "other") {
    const secs = mode === "sec" ? T : mode === "min" ? T * 60 : T * 3600;
    readout = `${pad2(secs / 3600)}:${pad2((secs % 3600) / 60)}:${pad2(secs % 60)}`;
    units = ["HR", "MIN", "SEC"];
  }
  const RW = 196 * k;
  const crown = 60 * k;
  const W = 2 * RW + 60 * k;
  const H = 2 * RW + crown + 24 * k;
  const cx = W / 2;
  const cy = crown + RW + 8 * k;
  const press = (interpolate(frame, [at - 5, at - 2, at + 3], [0, 1, 0], clamp) +
    interpolate(frame, [stopAt - 3, stopAt, stopAt + 5], [0, 1, 0], clamp)) * 9 * k;
  const sf = interpolate(frame, [stopAt, stopAt + 3, stopAt + 16], [0, 1, 0], clamp);
  const rp = ramp(frame, stopAt, 20);
  const wIn = ramp(frame, 0, 18, backOut);
  const id = `ncsw${overlay.startFrame}`;
  const arcDeg = mainDeg >= 359.9 ? (mainDeg % 360 < 0.5 ? 359.9 : mainDeg % 360) : mainDeg;
  const sx = cx;
  const sy = cy + 58 * k;
  const [shx, shy] = polar(sx, sy, 22 * k, -90 + subDeg);
  const RS = 84 * k;
  const cw = RS * 0.6;
  const metal = `url(#${id}m)`;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column",
        transform: `scale(${hold})` }}>
        <div style={{ opacity: Math.min(1, ramp(frame, 0, 8)) * (1 - exit),
          transform: `scale(${(0.82 + 0.18 * wIn) * (1 - 0.1 * exit)}) rotate(${(1 - ramp(frame, 0, 20)) * -14 + exit * 10}deg)` }}>
          <svg width={W} height={H} style={{ overflow: "visible", display: "block" }}>
            <defs>
              <linearGradient id={`${id}m`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#f4f4f6" />
                <stop offset="0.5" stopColor="#8e9097" />
                <stop offset="1" stopColor="#d9dadf" />
              </linearGradient>
              <radialGradient id={`${id}f`} cx="0.5" cy="0.45" r="0.6">
                <stop offset="0" stopColor="#1d1e24" />
                <stop offset="1" stopColor="#0a0a0d" />
              </radialGradient>
              <clipPath id={`${id}c`}><circle cx={cx} cy={cy} r={RW - 12 * k} /></clipPath>
            </defs>
            <rect x={cx - 13 * k} y={crown * 0.45 + press} width={26 * k} height={crown * 0.7} fill={metal} />
            <rect x={cx - 36 * k} y={6 * k + press} width={72 * k} height={26 * k} rx={8 * k} fill={metal} />
            <g transform={`rotate(42 ${cx} ${cy})`}>
              <rect x={cx - 11 * k} y={cy - RW - 24 * k} width={22 * k} height={30 * k} rx={5 * k} fill={metal} />
            </g>
            {rp > 0 && rp < 1 ? (
              <circle cx={cx} cy={cy} r={RW + (8 + 70 * rp) * k} fill="none" stroke={accent} strokeWidth={3 * k}
                opacity={(1 - rp) * 0.8} />
            ) : null}
            <circle cx={cx} cy={cy} r={RW} fill={metal} />
            <circle cx={cx} cy={cy} r={RW - 12 * k} fill={`url(#${id}f)`} />
            {mainDeg > 0.5 ? (
              <path d={arcPath(cx, cy, RW - 100 * k, -90, -90 + arcDeg)} fill="none" stroke={accent} strokeOpacity={0.4}
                strokeWidth={8 * k} strokeLinecap="round" />
            ) : null}
            {Array.from({ length: 60 }, (_, i) => {
              const deg = -90 + i * 6;
              const major = i % 5 === 0;
              const [x1, y1] = polar(cx, cy, RW - 24 * k, deg);
              const [x2, y2] = polar(cx, cy, RW - (major ? 44 : 33) * k, deg);
              return (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={major ? "#fff" : "rgba(255,255,255,.5)"}
                  strokeWidth={(major ? 3.5 : 1.8) * k} strokeLinecap="round" opacity={ramp(frame, 4 + i * 0.25, 8)} />
              );
            })}
            {Array.from({ length: 12 }, (_, i) => {
              const [nx, ny] = polar(cx, cy, RW - 70 * k, -90 + (i + 1) * 30);
              return (
                <text key={`n${i}`} x={nx} y={ny} textAnchor="middle" dominantBaseline="central" fontFamily={LABEL}
                  fontWeight={700} fontSize={24 * k} fill="rgba(255,255,255,.78)" opacity={ramp(frame, 8 + i * 1.2, 10)}>
                  {(i + 1) * 5}
                </text>
              );
            })}
            <circle cx={sx} cy={sy} r={28 * k} fill="rgba(255,255,255,.03)" stroke="rgba(255,255,255,.35)" strokeWidth={2 * k} />
            {Array.from({ length: 12 }, (_, i) => {
              const [x1, y1] = polar(sx, sy, 26 * k, -90 + i * 30);
              const [x2, y2] = polar(sx, sy, (i % 3 === 0 ? 18 : 22) * k, -90 + i * 30);
              return <line key={`st${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,.55)" strokeWidth={1.6 * k} />;
            })}
            <line x1={sx} y1={sy} x2={shx} y2={shy} stroke="#fff" strokeWidth={3 * k} strokeLinecap="round" />
            <circle cx={sx} cy={sy} r={4 * k} fill="#fff" />
            <g transform={`rotate(${mainDeg} ${cx} ${cy})`}>
              <line x1={cx} y1={cy + 36 * k} x2={cx} y2={cy - RW + 34 * k} stroke={accent} strokeOpacity={0.22}
                strokeWidth={14 * k} strokeLinecap="round" />
              <line x1={cx} y1={cy + 36 * k} x2={cx} y2={cy - RW + 34 * k} stroke={accent} strokeWidth={4.5 * k}
                strokeLinecap="round" />
              <circle cx={cx} cy={cy + 36 * k} r={8 * k} fill={accent} />
            </g>
            <circle cx={cx} cy={cy} r={13 * k} fill={accent} />
            <circle cx={cx} cy={cy} r={5 * k} fill={INK} />
            <g clipPath={`url(#${id}c)`}>
              <ellipse cx={cx - RW * 0.3} cy={cy - RW * 0.42} rx={RW * 0.62} ry={RW * 0.3} fill="rgba(255,255,255,.05)"
                transform={`rotate(-28 ${cx - RW * 0.3} ${cy - RW * 0.42})`} />
            </g>
          </svg>
        </div>
        <div style={{ height: 18 * k }} />
        {mode !== "other" ? (
          <MaskIO pin={ramp(frame, at - 6, 14)} pout={exit}>
            <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: RS, lineHeight: 1, whiteSpace: "pre",
              color: mix(sf, [0, 1], ["#ffffff", accent]), textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>{readout}</div>
          </MaskIO>
        ) : (
          <MaskIO pin={ramp(frame, at - 6, 14)} pout={exit}>
            <Odometer value={value} at={at} frames={F} size={120 * k} color="#fff" suffix={u ? ` ${cap(overlay.suffix)}` : ""}
              suffixScale={0.4} suffixColor={accent} />
          </MaskIO>
        )}
        {units.length ? (
          <MaskIO pin={ramp(frame, at, 14)} pout={exit} style={{ marginTop: 8 * k }}>
            <div style={{ display: "flex" }}>
              {units.map((un, i) => (
                <React.Fragment key={un}>
                  {i > 0 ? <div style={{ width: cw }} /> : null}
                  <div style={{ width: 2 * cw, textAlign: "center", fontFamily: MONO, fontWeight: 500, fontSize: 24 * k,
                    letterSpacing: "0.12em", color: "rgba(255,255,255,.45)" }}>{un}</div>
                </React.Fragment>
              ))}
            </div>
          </MaskIO>
        ) : null}
        <div style={{ height: 14 * k }} />
        <TextLines text={cap(overlay.text)} chars={36} max={2} at={at + 12} style={{ fontFamily: LABEL, fontWeight: 800,
          fontSize: 34 * k, letterSpacing: "0.16em", color: "rgba(255,255,255,.9)", lineHeight: 1.1 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "nc-speedo-gauge": SpeedoGauge,
  "nc-led-counter": LedCounter,
  "nc-flip-clock": FlipCounter,
  "nc-countdown-dial": CountdownDial,
  "nc-battery": BatteryLevel,
  "nc-thermometer": Thermometer,
  "nc-population-clock": PopulationClock,
  "nc-burst-number": BurstNumber,
  "nc-segment-meter": SegmentMeter,
  "nc-stopwatch": Stopwatch,
};
