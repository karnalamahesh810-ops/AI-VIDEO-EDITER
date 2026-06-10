// Shared animation helpers for all template components. Pure functions of `frame`
// (and `fps` where time-based). Animation grammar from the references: ~0.3-0.4s
// fade+small-translate ins, staggered reveals, left->right draw-ons, count-ups,
// typewriter, hard cuts. Keep ins ~8-12 frames, outs ~8-10 frames.
import { interpolate, Easing, spring } from "remotion";

export const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

// Fade + small upward translate in; optional fade/translate out at `outAt`.
export function fadeRise(
  frame: number,
  opts: { delay?: number; dur?: number; dist?: number; outAt?: number; outDur?: number } = {}
) {
  const { delay = 0, dur = 10, dist = 14, outAt, outDur = 8 } = opts;
  const inP = interpolate(frame, [delay, delay + dur], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.ease),
  });
  let out = 0;
  if (outAt != null) out = interpolate(frame, [outAt, outAt + outDur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return { opacity: inP * (1 - out), transform: `translateY(${(1 - inP) * dist}px)` };
}

// Horizontal slide-in from a side with spring settle; optional slide-out.
export function slideIn(
  frame: number, fps: number,
  opts: { side?: "left" | "right"; delay?: number; dist?: number; outAt?: number; outDur?: number } = {}
) {
  const { side = "right", delay = 0, dist = 120, outAt, outDur = 10 } = opts;
  const s = spring({ frame: frame - delay, fps, config: { damping: 18, mass: 0.8 }, durationInFrames: 18 });
  let out = 0;
  if (outAt != null) out = interpolate(frame, [outAt, outAt + outDur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const dir = side === "right" ? 1 : -1;
  const opacity = interpolate(frame, [delay, delay + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) * (1 - out);
  return { opacity, transform: `translateX(${((1 - s) + out) * dir * dist}px)` };
}

// Pop scale-in with slight overshoot (spring), optional fade-out.
export function popIn(
  frame: number, fps: number,
  opts: { delay?: number; from?: number; outAt?: number; outDur?: number } = {}
) {
  const { delay = 0, from = 0.8, outAt, outDur = 8 } = opts;
  const s = spring({ frame: frame - delay, fps, config: { damping: 12, mass: 0.6 }, durationInFrames: 16 });
  const scale = from + (1 - from) * s;
  let out = 0;
  if (outAt != null) out = interpolate(frame, [outAt, outAt + outDur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const opacity = interpolate(frame, [delay, delay + 5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) * (1 - out);
  return { opacity, transform: `scale(${scale})` };
}

// Eased count-up value.
export function countUp(frame: number, opts: { to: number; from?: number; delay?: number; dur?: number }) {
  const { to, from = 0, delay = 0, dur = 24 } = opts;
  const p = interpolate(frame, [delay, delay + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  return from + (to - from) * p;
}

// Number formatting: prefix/suffix, commas, compact K/M/B.
export function fmtNum(
  v: number,
  opts: { prefix?: string; suffix?: string; decimals?: number; commas?: boolean; compact?: boolean } = {}
) {
  const { prefix = "", suffix = "", decimals = 0, commas = true, compact = false } = opts;
  let n = v, unit = "";
  if (compact) {
    if (Math.abs(v) >= 1e9) { n = v / 1e9; unit = "B"; }
    else if (Math.abs(v) >= 1e6) { n = v / 1e6; unit = "M"; }
    else if (Math.abs(v) >= 1e3) { n = v / 1e3; unit = "K"; }
  }
  let s: string;
  if (compact) s = (Math.abs(n) < 100 && unit ? n.toFixed(1) : Math.round(n).toString());
  else s = commas ? n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : n.toFixed(decimals);
  return `${prefix}${s}${unit}${suffix}`;
}

// Draw-on progress 0..1 for stroke-dashoffset reveals (lines, arcs, circles).
export function drawOn(frame: number, opts: { delay?: number; dur?: number } = {}) {
  const { delay = 0, dur = 30 } = opts;
  return interpolate(frame, [delay, delay + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.ease) });
}

// Typewriter: visible substring + blinking cursor flag.
export function typewriter(
  frame: number, fps: number, text: string,
  opts: { delay?: number; cps?: number; cursor?: boolean } = {}
) {
  const { delay = 0, cps = 35, cursor = true } = opts;
  const elapsed = Math.max(0, (frame - delay) / fps);
  const n = Math.min(text.length, Math.floor(elapsed * cps));
  const done = n >= text.length;
  const blink = Math.floor(frame / (fps * 0.5)) % 2 === 0;
  return { text: text.slice(0, n), cursor: cursor && (!done || blink) };
}

// Per-item staggered reveal progress (bullets, bars, tiles).
export function stagger(frame: number, i: number, opts: { delay?: number; step?: number; dur?: number } = {}) {
  const { delay = 0, step = 5, dur = 8 } = opts;
  return interpolate(frame, [delay + i * step, delay + i * step + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.ease) });
}
