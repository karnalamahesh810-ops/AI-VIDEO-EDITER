import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Callouts and annotations that ride ON the footage (family "co-"). Each one
 * points at something in the shot (overlay.anchor, normalized 0..1, when the
 * visual review supplied it; a designed default spot otherwise), keeps the
 * picture visible and only shades locally behind its words.
 *
 *   co-circle-pulse        a marker loop draws round the subject, then pulses
 *   co-draw-arrow          a pigtail arrow draws from the label to the point
 *   co-bracket-label       a measured bracket grows beside a region, value rolls
 *   co-target-lock         a reticle hunts, snaps to lock, coordinates decode
 *   co-measure-line        a dimension line with ticks and arrows, value rolls
 *   co-ripple-pointer      a drop lands, water ripples spread, a leader label
 *   co-speech-bubble       typing dots morph into a clean quote bubble
 *   co-scribble-underline  a marker scribble boils under the key word
 *   co-spotlight           a searchlight finds the subject, the rest goes dark
 *   co-chip-stack          fact chips swing down one by one on a connector
 *
 * Text rises in letter by letter out of a mask and drops out at the end;
 * strokes draw on and retract; everything leaves in the last ~12 frames.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = { x: number; y: number };
type Box = { x0: number; x1: number; y0: number; y1: number };
type Item = OverlayItem & { suffix?: string; prefix?: string };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const INOUT = Easing.bezier(0.65, 0, 0.35, 1);
const BACK = Easing.bezier(0.34, 1.56, 0.64, 1);
const IN = Easing.bezier(0.7, 0, 0.84, 0);
const PEN = Easing.bezier(0.45, 0, 0.2, 1);
const CYAN = "#53c8ff";
const INK = "#111318";
const TS = "0 4px 22px rgba(0,0,0,.62), 0 1px 3px rgba(0,0,0,.55)";
const SHADOW_STROKE = "rgba(0,0,0,.34)";

// ------------------------------------------------------------------ helpers
const clean = (s?: string) => (s || "").replace(/\s+/g, " ").trim();
const cap = (s?: string) => clean(s).toUpperCase();
const short = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

/** Deterministic 0..1 noise of a number (never Math.random). */
const rnd = (n: number) => {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
const seedOf = (s: string) => {
  let h = 17;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 99991;
  return h;
};
const finite = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
/** "FT" -> " FT", "%" -> "%". */
const sfx = (s?: string) => {
  const t = (s || "").trim();
  if (!t) return "";
  return /^[%°'"]/.test(t) ? t : ` ${t}`;
};

/** A normalized point (anchor / labelPosition) in pixels, kept inside a safe box. */
const spot = (p: Pt | undefined, def: Pt, W: number, H: number, box: Box): Pt => {
  const ok = !!p && Number.isFinite(p.x) && Number.isFinite(p.y);
  const nx = ok ? (p as Pt).x : def.x;
  const ny = ok ? (p as Pt).y : def.y;
  return { x: Math.min(box.x1, Math.max(box.x0, nx)) * W, y: Math.min(box.y1, Math.max(box.y0, ny)) * H };
};

/** Approximate width of condensed caps (Bebas / Barlow) at `px`. */
const estW = (t: string, px: number, spacing = 0.03) => {
  let w = 0;
  for (const c of t) {
    w += (c === " " ? 0.2 : /[IJ1.,:;'!|]/.test(c) ? 0.22 : /[MW]/.test(c) ? 0.55 : 0.42) + spacing;
  }
  return w * px;
};

/** Wrap text into `room` px, trying each size; the last size truncates with an ellipsis. */
const fit = (text: string, room: number, sizes: number[], em: number, k: number, maxLines: number, maxChars: number) => {
  for (const s of sizes) {
    const per = Math.max(6, Math.min(maxChars, Math.floor(room / Math.max(1, em * s * k))));
    const ls = lines(text, per);
    if (ls.length <= maxLines) return { ls, size: s };
  }
  const s = sizes[sizes.length - 1];
  const per = Math.max(6, Math.min(maxChars + 8, Math.floor(room / Math.max(1, em * s * k))));
  const all = lines(text, per);
  const ls = all.slice(0, maxLines);
  if (all.length > maxLines && ls.length) ls[ls.length - 1] = `${ls[ls.length - 1].replace(/[.,;:]$/, "")}…`;
  return { ls, size: s };
};

/** Stroke props showing the stretch [from, to] of a path drawn with pathLength={1}. */
const seg = (from: number, to: number) => {
  const a = Math.max(0, Math.min(1, from));
  const b = Math.max(0, Math.min(1, to));
  const len = b - a;
  return { strokeDasharray: `${Math.max(0.0001, len)} 4`, strokeDashoffset: -a, strokeOpacity: len > 0.002 ? 1 : 0 };
};

/** 0 -> 1 over the last ~12 frames: the graphic's exit. */
const useExit = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - 13, 11, IN);
};

/** A soft local shade behind words (never a full-frame darkening). */
const Shade: React.FC<{ x: number; y: number; rx: number; ry: number; a?: number }> = ({ x, y, rx, ry, a = 0.42 }) => {
  const frame = useCurrentFrame();
  const out = useExit();
  return (
    <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * (1 - out),
      background: `radial-gradient(${Math.round(rx)}px ${Math.round(ry)}px at ${Math.round(x)}px ${Math.round(y)}px, ` +
        `rgba(0,0,0,${a}) 0%, rgba(0,0,0,${(a * 0.55).toFixed(3)}) 45%, rgba(0,0,0,0) 100%)` }} />
  );
};

/**
 * Letters rising out of a mask one by one (dir 1) or dropping in from above
 * (dir -1), leaving the other way at the end. Inline, so words can sit in a row.
 */
const Letters: React.FC<{ text: string; at: number; step?: number; dir?: 1 | -1; style?: React.CSSProperties }> =
  ({ text, at, step = 0.7, dir = 1, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = durationInFrames - 14;
    return (
      <span style={{ display: "inline-block", overflow: "hidden", whiteSpace: "nowrap", verticalAlign: "top",
        padding: "0.04em 0 0.08em", ...style }}>
        {Array.from(text).map((c, i) => {
          const pin = ramp(frame, at + i * step, 12);
          const pout = ramp(frame, end + i * 0.6, 9, IN);
          const y = dir * ((1 - pin) * 108 - pout * 108);
          return (
            <span key={i} style={{ display: "inline-block", whiteSpace: "pre", transform: `translateY(${y}%)`,
              opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
          );
        })}
      </span>
    );
  };

/** Any block (a rolling number) sliding up out of a mask, and out again at the end. */
const Reveal: React.FC<{ at: number; frames?: number; dir?: 1 | -1; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 16, dir = 1, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, durationInFrames - 14, 10, IN);
    return (
      <div style={{ overflow: "hidden", padding: "0.02em 0 0.06em", ...style }}>
        <div style={{ transform: `translateY(${dir * ((1 - pin) * 112 - pout * 112)}%)` }}>{children}</div>
      </div>
    );
  };

const kickerStyle = (k: number, accent: string, align: "left" | "right" | "center" = "left"): React.CSSProperties => ({
  fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.24em", color: accent, textShadow: TS,
  whiteSpace: "nowrap", textAlign: align,
});
const titleStyle = (k: number, size: number, align: "left" | "right" | "center" = "left"): React.CSSProperties => ({
  fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1, color: "#fff", letterSpacing: "0.03em", textShadow: TS,
  whiteSpace: "nowrap", textAlign: align,
});

// ================================================================== 1. circle pulse
/**
 * A marker loop draws round the subject (a little more than one turn, so its
 * ends overlap like a real pen stroke), bumps as it closes, then sends out
 * soft pulse rings; the label rises beside it on a short tick.
 */
const CirclePulse: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const out = useExit();
  const text = cap(overlay.text);
  if (!text) return null;
  const sub = cap(overlay.subtitle);
  const c = spot(overlay.anchor, { x: 0.38, y: 0.46 }, width, height, { x0: 0.16, x1: 0.84, y0: 0.24, y1: 0.72 });
  const seed = seedOf(text);
  const rx = 160 * k, ry = 112 * k;
  const tilt = -13 + rnd(seed) * 9;
  const a0 = -2.25 + rnd(seed + 3) * 0.5;
  let d = "";
  for (let i = 0; i <= 96; i++) {
    const t = i / 96;
    const a = a0 + t * Math.PI * 2 * 1.13;
    const w = 1 + 0.03 * Math.sin(a * 3 + seed) + 0.016 * Math.sin(a * 7 + seed * 0.37) + 0.075 * t;
    d += `${i ? "L" : "M"}${(Math.cos(a) * rx * w).toFixed(1)} ${(Math.sin(a) * ry * w).toFixed(1)} `;
  }
  const drawF = Math.round(fps * 0.6);
  const draw = ramp(frame, 3, drawF, PEN);
  const closed = 3 + drawF;
  const pop = interpolate(frame, [closed - 4, closed + 2, closed + 12], [1, 1.05, 1], clamp);
  const period = Math.round(fps * 1.3);
  const edge = rx * 1.14 + 22 * k;
  const tickL = 54 * k, gapL = 18 * k;
  const roomR = width - 90 * k - (c.x + edge + tickL + gapL);
  const roomL = c.x - edge - tickL - gapL - 90 * k;
  const onRight = roomR >= roomL;
  const { ls, size } = fit(text, Math.min(620 * k, Math.max(roomR, roomL)), [66, 54], 0.44, k, 2, 18);
  const labelAt = Math.round(fps * 0.4);
  const tick = ramp(frame, labelAt - 4, 14) * (1 - out);
  const x0 = c.x + (onRight ? edge : -edge);
  const x1 = x0 + (onRight ? tickL : -tickL) * tick;
  const lx = x0 + (onRight ? tickL + gapL : -(tickL + gapL));
  const textW = Math.max(...ls.map((l) => estW(l, size * k)));
  const align = onRight ? "left" : "right";
  return (
    <AbsoluteFill>
      <Shade x={lx + (onRight ? textW / 2 : -textW / 2)} y={c.y} rx={textW * 0.8 + 180 * k} ry={220 * k} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <g transform={`translate(${c.x} ${c.y}) rotate(${tilt}) scale(${pop * hold})`}>
          {[0, 1].map((j) => {
            const t0 = closed + j * Math.round(period / 2);
            if (frame < t0) return null;
            const ph = ((frame - t0) % period) / period;
            const s = 1.06 + 0.5 * (1 - Math.pow(1 - ph, 3));
            return (
              <ellipse key={j} cx={0} cy={0} rx={rx * s} ry={ry * s} fill="none" stroke={accent}
                strokeWidth={(3.5 * (1 - ph) + 1) * k} strokeOpacity={(1 - ph) * 0.55 * (1 - out)} />
            );
          })}
          <path d={d} fill="none" stroke={SHADOW_STROKE} strokeWidth={12 * k} strokeLinecap="round" strokeLinejoin="round"
            pathLength={1} transform={`translate(${2 * k} ${4 * k})`} {...seg(out, draw)} />
          <path d={d} fill="none" stroke={accent} strokeWidth={7.5 * k} strokeLinecap="round" strokeLinejoin="round"
            pathLength={1} {...seg(out, draw)} />
        </g>
        <line x1={x0} y1={c.y} x2={x1} y2={c.y} stroke="#fff" strokeWidth={3 * k} strokeLinecap="round"
          strokeOpacity={tick > 0.01 ? 0.9 : 0} />
      </svg>
      <div style={{ position: "absolute", top: c.y, left: onRight ? lx : undefined, right: onRight ? undefined : width - lx,
        transform: "translateY(-50%)", display: "flex", flexDirection: "column", alignItems: onRight ? "flex-start" : "flex-end",
        gap: 2 * k }}>
        {sub ? <LetterLine text={sub} at={labelAt} step={0.6} style={kickerStyle(k, accent, align)} /> : null}
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={labelAt + 3 + i * 4} step={0.8} style={titleStyle(k, size, align)} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. draw arrow label
/**
 * The label rises first; then an arrow draws out of it on a bowed curve with a
 * pigtail loop, its head flicks open at the end and a ring bursts on the point.
 */
const DrawArrow: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const text = cap(overlay.text);
  if (!text) return null;
  const sub = cap(overlay.subtitle);
  const T = spot(overlay.anchor, { x: 0.64, y: 0.38 }, width, height, { x0: 0.12, x1: 0.88, y0: 0.16, y1: 0.8 });
  const tx = T.x / width, ty = T.y / height;
  const below = ty < 0.5;
  const toLeft = tx > 0.5;
  const L = spot(overlay.labelPosition, { x: toLeft ? tx - 0.4 : tx + 0.1, y: below ? ty + 0.22 : ty - 0.34 }, width, height,
    { x0: 0.07, x1: 0.62, y0: 0.14, y1: 0.7 });
  const room = Math.min(640 * k, width - 90 * k - L.x);
  const { ls, size } = fit(text, room, [62, 52], 0.44, k, 2, 20);
  const bh = (sub ? 40 * k : 0) + ls.length * size * k * 1.02;
  const textW = Math.min(room, Math.max(...ls.map((l) => estW(l, size * k))));
  const S: Pt = { x: L.x + textW * (toLeft ? 0.7 : 0.2), y: below ? L.y - 20 * k : L.y + bh + 24 * k };
  // A quadratic bowing upward, ending a little short of the point.
  const vx = T.x - S.x, vy = T.y - S.y;
  const len = Math.max(1, Math.hypot(vx, vy));
  let nx = -vy / len, ny = vx / len;
  if (ny > 0) { nx = -nx; ny = -ny; }
  const C: Pt = { x: S.x + vx * 0.5 + nx * len * 0.24, y: S.y + vy * 0.5 + ny * len * 0.24 };
  const el = Math.max(1, Math.hypot(T.x - C.x, T.y - C.y));
  const E: Pt = { x: T.x - ((T.x - C.x) / el) * 30 * k, y: T.y - ((T.y - C.y) / el) * 30 * k };
  const loopOn = len > 220 * k;
  const R = Math.min(42 * k, len * 0.075);
  const la = 0.26, lb = 0.44, N = 140;
  const pts: Pt[] = [];
  for (let i = 0; i <= N; i++) {
    const t = i / N, mt = 1 - t;
    let x = mt * mt * S.x + 2 * mt * t * C.x + t * t * E.x;
    let y = mt * mt * S.y + 2 * mt * t * C.y + t * t * E.y;
    if (loopOn && t > la && t < lb) {
      // A pigtail: a full turn tangent to the curve, bulging to its outer side.
      const dx = 2 * mt * (C.x - S.x) + 2 * t * (E.x - C.x);
      const dy = 2 * mt * (C.y - S.y) + 2 * t * (E.y - C.y);
      const dl = Math.max(1e-6, Math.hypot(dx, dy));
      const ux = dx / dl, uy = dy / dl;
      let qx = -uy, qy = ux;
      if (qx * nx + qy * ny < 0) { qx = -qx; qy = -qy; }
      const ang = ((t - la) / (lb - la)) * Math.PI * 2;
      x += R * (Math.sin(ang) * ux + (1 - Math.cos(ang)) * qx);
      y += R * (Math.sin(ang) * uy + (1 - Math.cos(ang)) * qy);
    }
    pts.push({ x, y });
  }
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const pe = pts[N], pb = pts[N - 3];
  const hl = Math.max(1e-6, Math.hypot(pe.x - pb.x, pe.y - pb.y));
  const hx = (pe.x - pb.x) / hl, hy = (pe.y - pb.y) / hl;
  const wing = (sg: number): Pt => {
    const a = (sg * 150 * Math.PI) / 180;
    const cs = Math.cos(a), sn = Math.sin(a);
    return { x: pe.x + (hx * cs - hy * sn) * 30 * k, y: pe.y + (hx * sn + hy * cs) * 30 * k };
  };
  const labelAt = 2;
  const bodyAt = 9;
  const bodyF = Math.round(fps * 0.62);
  const body = ramp(frame, bodyAt, bodyF, PEN);
  const hitAt = bodyAt + bodyF - 2;
  const head = ramp(frame, hitAt - 2, 8) * (1 - out);
  const burst = ramp(frame, hitAt, 18);
  const dot = ramp(frame, hitAt, 10, BACK) * (1 - out);
  const per = Math.round(fps * 1.4);
  const ph = frame > hitAt + 18 ? ((frame - hitAt - 18) % per) / per : -1;
  return (
    <AbsoluteFill>
      <Shade x={L.x + textW / 2} y={L.y + bh / 2} rx={textW * 0.9 + 160 * k} ry={bh + 120 * k} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <path d={d} fill="none" stroke={SHADOW_STROKE} strokeWidth={10 * k} strokeLinecap="round" strokeLinejoin="round"
          pathLength={1} transform={`translate(${2 * k} ${3 * k})`} {...seg(out, body)} />
        <path d={d} fill="none" stroke={accent} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round"
          pathLength={1} {...seg(out, body)} />
        {[-1, 1].map((sg) => {
          const w = wing(sg);
          return (
            <path key={sg} d={`M${pe.x} ${pe.y} L${w.x} ${w.y}`} fill="none" stroke={accent} strokeWidth={6 * k}
              strokeLinecap="round" pathLength={1} {...seg(0, head)} />
          );
        })}
        <circle cx={T.x} cy={T.y} r={(10 + 46 * burst) * k} fill="none" stroke={accent} strokeWidth={(3 * (1 - burst) + 0.5) * k}
          strokeOpacity={burst > 0 && burst < 1 ? 1 - burst : 0} />
        {ph >= 0 ? (
          <circle cx={T.x} cy={T.y} r={(10 + 24 * ph) * k} fill="none" stroke="#fff" strokeWidth={2 * k}
            strokeOpacity={(1 - ph) * 0.55 * (1 - out)} />
        ) : null}
        <circle cx={T.x} cy={T.y} r={Math.max(0, 7 * k * dot)} fill={accent} stroke="#fff" strokeWidth={2.5 * k}
          strokeOpacity={dot > 0.05 ? 1 : 0} />
      </svg>
      <div style={{ position: "absolute", left: L.x, top: L.y, display: "flex", flexDirection: "column", gap: 2 * k }}>
        {sub ? <LetterLine text={sub} at={labelAt} step={0.6} style={kickerStyle(k, accent)} /> : null}
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={labelAt + 3 + i * 4} step={0.8} style={titleStyle(k, size)} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. bracket label
/**
 * A square bracket grows out from its centre beside a region, fine ruler
 * ticks appearing as it passes, a faint accent wash over the region; the
 * label (and, given one, a rolling value) steps out from its centre notch.
 */
const BracketLabel: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const text = cap(overlay.text);
  const value = finite(overlay.value);
  if (!text && value === null) return null;
  const sub = cap(overlay.subtitle);
  const B = spot(overlay.anchor, { x: 0.56, y: 0.47 }, width, height, { x0: 0.2, x1: 0.8, y0: 0.3, y1: 0.64 });
  const labelRight = B.x <= width * 0.6;
  const sd = labelRight ? 1 : -1;
  const ad = -sd;
  const Hb = 400 * k;
  const g = ramp(frame, 2, Math.round(fps * 0.55), INOUT) * (1 - out);
  const half = (Hb / 2) * g;
  const armIn = ramp(frame, Math.round(fps * 0.42), 10) * (1 - out);
  const arm = 44 * k * armIn;
  const notch = ramp(frame, Math.round(fps * 0.5), 10) * (1 - out);
  const top = B.y - half, bot = B.y + half;
  const bracket = `M${B.x + ad * arm} ${top} L${B.x} ${top} L${B.x} ${bot} L${B.x + ad * arm} ${bot}`;
  const ticks = Array.from({ length: 9 }, (_, i) => -Hb / 2 + ((i + 1) * Hb) / 10).filter((o) => Math.abs(o) < half - 4 * k);
  const settle = Math.round(fps * 0.8);
  const per = Math.round(fps * 1.8);
  const ph = frame > settle ? ((frame - settle) % per) / per : -1;
  const sy = top + (bot - top) * Math.max(0, ph);
  const gid = `co-br-${overlay.startFrame}`;
  const lx = B.x + sd * 50 * k;
  const room = Math.min(640 * k, labelRight ? width - 90 * k - lx : lx - 90 * k);
  const tx = value !== null ? fit(text, room, [34, 30], 0.52, k, 2, 30) : fit(text, room, [64, 54], 0.44, k, 2, 20);
  const at = Math.round(fps * 0.45);
  const align = labelRight ? "left" : "right";
  const textW = Math.min(room, Math.max(260 * k, ...tx.ls.map((l) => estW(l, tx.size * k))));
  return (
    <AbsoluteFill>
      <Shade x={lx + (sd * textW) / 2} y={B.y} rx={textW * 0.8 + 160 * k} ry={260 * k} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs>
          <linearGradient id={gid} x1={ad < 0 ? 1 : 0} y1={0} x2={ad < 0 ? 0 : 1} y2={0}>
            <stop offset="0%" stopColor={accent} stopOpacity={0.2} />
            <stop offset="100%" stopColor={accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <rect x={ad < 0 ? B.x - 230 * k : B.x} y={top} width={230 * k} height={Math.max(0, bot - top)} fill={`url(#${gid})`}
          opacity={armIn} />
        {ticks.map((o, i) => (
          <line key={i} x1={B.x} x2={B.x + ad * (i % 2 === 0 ? 12 : 20) * k} y1={B.y + o} y2={B.y + o}
            stroke="#fff" strokeOpacity={0.55} strokeWidth={2 * k} />
        ))}
        <path d={bracket} fill="none" stroke={SHADOW_STROKE} strokeWidth={9 * k} strokeLinecap="square" strokeLinejoin="miter"
          transform={`translate(${2 * k} ${3 * k})`} opacity={g > 0.01 ? 1 : 0} />
        <path d={bracket} fill="none" stroke="#fff" strokeWidth={5 * k} strokeLinecap="square" strokeLinejoin="miter"
          opacity={g > 0.01 ? 1 : 0} />
        <line x1={B.x} y1={B.y} x2={B.x + sd * 30 * k * notch} y2={B.y} stroke={accent} strokeWidth={5 * k}
          strokeOpacity={notch > 0.01 ? 1 : 0} />
        {ph >= 0 ? (
          <line x1={B.x} x2={B.x} y1={Math.max(top, sy - 28 * k)} y2={Math.min(bot, sy + 28 * k)} stroke={accent}
            strokeWidth={5 * k} strokeOpacity={Math.sin(ph * Math.PI) * 0.95 * (1 - out)} />
        ) : null}
      </svg>
      <div style={{ position: "absolute", top: B.y, left: labelRight ? lx : undefined, right: labelRight ? undefined : width - lx,
        transform: "translateY(-50%)", display: "flex", flexDirection: "column", alignItems: labelRight ? "flex-start" : "flex-end",
        gap: 4 * k }}>
        {sub ? <LetterLine text={sub} at={at} step={0.6} style={kickerStyle(k, accent, align)} /> : null}
        {value !== null ? (
          <Reveal at={at + 2}>
            <Odometer value={value} at={at + 2} frames={Math.round(fps * 1.1)} size={104 * k} color="#fff"
              prefix={overlay.prefix || ""} suffix={sfx(overlay.suffix)} suffixScale={0.45} suffixColor={accent} />
          </Reveal>
        ) : null}
        {tx.ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={at + 6 + i * 4} step={0.7} style={value !== null
            ? { fontFamily: LABEL, fontWeight: 800, fontSize: tx.size * k, letterSpacing: "0.1em", color: "rgba(255,255,255,.94)",
              textShadow: TS, whiteSpace: "nowrap", textAlign: align, lineHeight: 1.05 }
            : titleStyle(k, tx.size, align)} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. target lock
const arc = (cx: number, cy: number, r: number, a1: number, a2: number) => {
  const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
  const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
  return `M${x1.toFixed(1)} ${y1.toFixed(1)} A${r.toFixed(1)} ${r.toFixed(1)} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
};

/**
 * A reticle hunts across the subject (big, turned 45 degrees, jumping between
 * seeded guesses), settles, snaps shut and blinks in the accent: locked.
 * Crosshair lines shoot out, a range ring turns, the status flips to
 * TARGET LOCKED and the coordinates decode digit by digit.
 */
const TargetLock: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const loc = (overlay.locations || []).find((l) => !!l && Number.isFinite(l.lat) && Number.isFinite(l.lon));
  const text = cap(overlay.text) || cap(loc ? loc.label : "");
  if (!text) return null;
  const sub = cap(overlay.subtitle);
  const T = spot(overlay.anchor, { x: 0.44, y: 0.44 }, width, height, { x0: 0.18, x1: 0.82, y0: 0.26, y1: 0.7 });
  const seed = seedOf(text);
  const lockAt = Math.round(fps * 0.95);
  const s = 100 * k;
  const search = ramp(frame, 0, lockAt, Easing.bezier(0.3, 0, 0.25, 1));
  const q = Math.floor(frame / 5);
  const u = (frame % 5) / 5;
  const sm = u * u * (3 - 2 * u);
  const amp = Math.pow(1 - search, 1.3) * 130 * k;
  const jit = (o: number) => ((rnd(seed + q * 7 + o) - 0.5) * (1 - sm) + (rnd(seed + (q + 1) * 7 + o) - 0.5) * sm) * 2 * amp;
  const locked = frame >= lockAt;
  const jx = locked ? 0 : jit(0);
  const jy = locked ? 0 : jit(3) * 0.6;
  const sc = locked ? interpolate(frame, [lockAt, lockAt + 3, lockAt + 10], [1, 0.88, 1], clamp)
    : interpolate(search, [0, 1], [2.2, 1]);
  const rot = (1 - search) * 45;
  const blink = locked && frame < lockAt + 10 ? ((frame - lockAt) % 4 < 2 ? 1 : 0.2) : 1;
  const col = locked ? accent : "#fff";
  const vis = ramp(frame, 0, 6) * (1 - out) * blink;
  const arm = 34 * k;
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]]
    .map(([cx, cy]) => `M${cx * s} ${cy * s - cy * arm} L${cx * s} ${cy * s} L${cx * s - cx * arm} ${cy * s}`).join(" ");
  const inner = `M0 ${-s} L0 ${-s + 16 * k} M${s} 0 L${s - 16 * k} 0 M0 ${s} L0 ${s - 16 * k} M${-s} 0 L${-s + 16 * k} 0`;
  const cl = ramp(frame, lockAt, 14) * (1 - out);
  const reach = 150 * k;
  const ringOn = ramp(frame, lockAt + 2, 12) * (1 - out);
  const rr = s * 1.55;
  const flash = ramp(frame, lockAt, 16);
  const onRight = T.x < width * 0.6;
  const sd = onRight ? 1 : -1;
  const rx0 = T.x + sd * (s + 12 * k + reach + 16 * k);
  const room = Math.min(560 * k, onRight ? width - 90 * k - rx0 : rx0 - 90 * k);
  const { ls, size } = fit(text, room, [46, 38], 0.5, k, 2, 22);
  const align = onRight ? "left" : "right";
  const status = locked ? "● TARGET LOCKED" : `SCANNING${".".repeat(Math.floor(frame / 5) % 4)}`;
  const coord = loc
    ? `${Math.abs(loc.lat).toFixed(4)}°${loc.lat >= 0 ? "N" : "S"}  ${Math.abs(loc.lon).toFixed(4)}°${loc.lon >= 0 ? "E" : "W"}`
    : "";
  const settleAt = lockAt + 16;
  const decoded = coord.split("")
    .map((ch, i) => (/\d/.test(ch) && frame < settleAt + i * 0.7 ? String(Math.floor(rnd(frame * 13 + i * 7) * 10)) : ch))
    .join("");
  const foot = coord ? decoded : sub;
  const mono: React.CSSProperties = { fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.16em",
    textShadow: TS, textAlign: align };
  return (
    <AbsoluteFill>
      <Shade x={rx0 + sd * 180 * k} y={T.y} rx={420 * k} ry={200 * k} a={0.38} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <circle cx={T.x} cy={T.y} r={rr} fill="none" stroke={CYAN} strokeWidth={2 * k}
          strokeDasharray={`${2 * k} ${10 * k}`} strokeOpacity={0.55 * ringOn} transform={`rotate(${frame * 0.6} ${T.x} ${T.y})`} />
        {[0, 1].map((j) => {
          const a1 = (-frame * 1.4 + j * 180) * (Math.PI / 180);
          return (
            <path key={j} d={arc(T.x, T.y, rr + 12 * k, a1, a1 + 0.6)} fill="none" stroke={accent} strokeWidth={4 * k}
              strokeLinecap="round" strokeOpacity={0.9 * ringOn} />
          );
        })}
        <circle cx={T.x} cy={T.y} r={s * (1.1 + 1.2 * flash)} fill="none" stroke={accent} strokeWidth={3 * k}
          strokeOpacity={flash > 0 && flash < 1 ? 1 - flash : 0} />
        {[[-1, 0], [1, 0], [0, -1], [0, 1]].map(([dx, dy], i) => {
          const r0 = s + 12 * k;
          const r1 = r0 + reach * (dy ? 0.6 : 1) * cl;
          return (
            <line key={i} x1={T.x + dx * r0} y1={T.y + dy * r0} x2={T.x + dx * r1} y2={T.y + dy * r1} stroke={CYAN}
              strokeWidth={1.8 * k} strokeOpacity={cl > 0.01 ? 0.85 : 0} />
          );
        })}
        <g transform={`translate(${T.x + jx} ${T.y + jy}) rotate(${rot}) scale(${sc * (1 + out * 0.7)})`} opacity={vis}>
          <path d={corners} fill="none" stroke="rgba(0,0,0,.35)" strokeWidth={8 * k} strokeLinecap="square" />
          <path d={corners} fill="none" stroke={col} strokeWidth={4.5 * k} strokeLinecap="square" />
          <path d={inner} fill="none" stroke={col} strokeWidth={2 * k} strokeOpacity={0.85} />
          <circle cx={0} cy={0} r={2.6 * k} fill={col} />
        </g>
      </svg>
      <div style={{ position: "absolute", bottom: height - (T.y - 10 * k), left: onRight ? rx0 : undefined,
        right: onRight ? undefined : width - rx0 }}>
        <Letters key={locked ? "lock" : "scan"} text={status} at={locked ? lockAt : 2} step={0.5}
          style={{ ...mono, color: locked ? accent : "rgba(255,255,255,.85)" }} />
      </div>
      <div style={{ position: "absolute", top: T.y + 12 * k, left: onRight ? rx0 : undefined,
        right: onRight ? undefined : width - rx0, display: "flex", flexDirection: "column",
        alignItems: onRight ? "flex-start" : "flex-end", gap: 6 * k }}>
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={lockAt + 3 + i * 4} step={0.7} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: size * k, lineHeight: 1.02, letterSpacing: "0.06em", color: "#fff", textShadow: TS, whiteSpace: "nowrap",
            textAlign: align }} />
        ))}
        {foot ? <Letters text={foot} at={lockAt + 8} step={0.4} style={{ ...mono, color: "rgba(255,255,255,.78)" }} /> : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. measure line
/**
 * A dimension line: end ticks snap in, dashed witness lines reach toward the
 * object, the line shoots out from the centre with arrowheads riding its ends,
 * the value rolls above it (beside it when vertical) and a laser dot keeps
 * sweeping along. overlay.label "vertical" / "height" / "depth" stands it up.
 */
const MeasureLine: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const value = finite(overlay.value);
  const text = cap(overlay.text);
  if (value === null && !text) return null;
  const vertical = /^(vertical|height|depth|up|down|tall|deep)$/.test((overlay.label || "").trim().toLowerCase());
  const C = spot(overlay.anchor, vertical ? { x: 0.4, y: 0.48 } : { x: 0.5, y: 0.52 }, width, height,
    vertical ? { x0: 0.14, x1: 0.6, y0: 0.4, y1: 0.58 } : { x0: 0.3, x1: 0.7, y0: 0.3, y1: 0.7 });
  const half = vertical
    ? Math.max(120 * k, Math.min(290 * k, C.y - 120 * k, height - C.y - 160 * k))
    : Math.max(200 * k, Math.min(500 * k, C.x - 110 * k, width - C.x - 110 * k));
  const ux = vertical ? 0 : 1, uy = vertical ? 1 : 0;
  const nx = vertical ? -1 : 0, ny = vertical ? 0 : 1;
  const tk = ramp(frame, 2, 12, BACK) * (1 - out);
  const drawF = Math.round(fps * 0.65);
  const g = ramp(frame, 6, drawF, INOUT) * (1 - out);
  const wv = ramp(frame, 4, 18) * (1 - out);
  const ext = half * g;
  const ends: Pt[] = [{ x: C.x - ux * half, y: C.y - uy * half }, { x: C.x + ux * half, y: C.y + uy * half }];
  const a1: Pt = { x: C.x - ux * ext, y: C.y - uy * ext };
  const b1: Pt = { x: C.x + ux * ext, y: C.y + uy * ext };
  const headPts = (tip: Pt, dx: number, dy: number) => {
    const bx = tip.x - dx * 20 * k, by = tip.y - dy * 20 * k;
    return `${tip.x},${tip.y} ${bx - dy * 9 * k},${by + dx * 9 * k} ${bx + dy * 9 * k},${by - dx * 9 * k}`;
  };
  const minor = Array.from({ length: 15 }, (_, i) => i + 1).filter((i) => Math.abs(-half + (i * 2 * half) / 16) <= ext);
  const done = 6 + drawF;
  const per = Math.round(fps * 1.6);
  const ph = frame > done + 4 ? ((frame - done - 4) % per) / per : -1;
  const scanPos = -half + 2 * half * Math.max(0, ph);
  const at = 10;
  const roomV = Math.min(560 * k, width - 90 * k - (C.x + 40 * k));
  const roomH = Math.max(360 * k, 2 * half - 40 * k);
  // With a value the text is a small caps label; without one it is the title itself.
  const tx = value !== null
    ? fit(text, vertical ? roomV : roomH, [32, 28], 0.52, k, 2, 34)
    : fit(text, vertical ? roomV : roomH, [60, 50], 0.44, k, 2, 22);
  const labelStyle = (align: "left" | "center"): React.CSSProperties => ({ fontFamily: LABEL, fontWeight: 800,
    fontSize: tx.size * k, letterSpacing: "0.16em", color: "rgba(255,255,255,.92)", textShadow: TS, whiteSpace: "nowrap",
    textAlign: align, lineHeight: 1.05 });
  const number = value !== null ? (
    <Reveal at={at}>
      <Odometer value={value} at={at} frames={Math.round(fps * 1.1)} size={96 * k} color="#fff" prefix={overlay.prefix || ""}
        suffix={sfx(overlay.suffix)} suffixScale={0.48} suffixColor={accent} />
    </Reveal>
  ) : null;
  return (
    <AbsoluteFill>
      <Shade x={vertical ? C.x + 220 * k : C.x} y={C.y} rx={vertical ? 460 * k : half + 160 * k} ry={vertical ? half + 80 * k : 220 * k}
        a={0.36} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {ends.map((e, i) => (
          <g key={i}>
            <line x1={e.x + nx * 30 * k} y1={e.y + ny * 30 * k} x2={e.x + nx * (30 + 110 * wv) * k} y2={e.y + ny * (30 + 110 * wv) * k}
              stroke="#fff" strokeOpacity={wv > 0.01 ? 0.55 : 0} strokeWidth={2 * k} strokeDasharray={`${6 * k} ${7 * k}`} />
            <line x1={e.x - nx * 24 * k * tk} y1={e.y - ny * 24 * k * tk} x2={e.x + nx * 24 * k * tk} y2={e.y + ny * 24 * k * tk}
              stroke="#fff" strokeWidth={4 * k} strokeLinecap="round" strokeOpacity={tk > 0.01 ? 1 : 0} />
          </g>
        ))}
        {minor.map((i) => {
          const o = -half + (i * 2 * half) / 16;
          const L = (i % 4 === 0 ? 16 : 9) * k;
          return (
            <line key={i} x1={C.x + ux * o} y1={C.y + uy * o} x2={C.x + ux * o + nx * L} y2={C.y + uy * o + ny * L}
              stroke="#fff" strokeOpacity={0.5} strokeWidth={1.6 * k} />
          );
        })}
        <line x1={a1.x + 2 * k} y1={a1.y + 3 * k} x2={b1.x + 2 * k} y2={b1.y + 3 * k} stroke={SHADOW_STROKE} strokeWidth={7 * k}
          strokeOpacity={ext > 2 ? 1 : 0} />
        <line x1={a1.x} y1={a1.y} x2={b1.x} y2={b1.y} stroke="#fff" strokeWidth={3.5 * k} strokeOpacity={ext > 2 ? 1 : 0} />
        {ext > 24 * k ? (
          <>
            <polygon points={headPts(a1, -ux, -uy)} fill={accent} />
            <polygon points={headPts(b1, ux, uy)} fill={accent} />
          </>
        ) : null}
        {ph >= 0 ? (
          <circle cx={C.x + ux * scanPos} cy={C.y + uy * scanPos} r={5 * k} fill={accent}
            opacity={Math.sin(ph * Math.PI) * (1 - out)} />
        ) : null}
      </svg>
      {vertical ? (
        <div style={{ position: "absolute", left: C.x + 40 * k, top: C.y, transform: "translateY(-50%)", display: "flex",
          flexDirection: "column", alignItems: "flex-start", gap: 6 * k }}>
          {number}
          {tx.ls.map((ln, i) => (
            <LetterLine key={i} text={ln} at={at + 8 + i * 4} step={0.6}
              style={value !== null ? labelStyle("left") : titleStyle(k, tx.size)} />
          ))}
        </div>
      ) : (
        <>
          <div style={{ position: "absolute", left: C.x, bottom: height - C.y + 16 * k, transform: "translateX(-50%)",
            display: "flex", flexDirection: "column", alignItems: "center" }}>
            {number ?? tx.ls.map((ln, i) => (
              <LetterLine key={i} text={ln} at={at + i * 4} step={0.7} style={titleStyle(k, tx.size, "center")} />
            ))}
          </div>
          {value !== null && tx.ls.length ? (
            <div style={{ position: "absolute", left: C.x, top: C.y + 24 * k, transform: "translateX(-50%)", display: "flex",
              flexDirection: "column", alignItems: "center", gap: 2 * k }}>
              {tx.ls.map((ln, i) => (
                <LetterLine key={i} text={ln} at={at + 8 + i * 4} step={0.6} style={labelStyle("center")} />
              ))}
            </div>
          ) : null}
        </>
      )}
    </AbsoluteFill>
  );
};

// ================================================================== 6. ripple pointer
/**
 * A drop falls onto the point, squashes into a marker dot and sends water
 * ripples across the surface (flattened ellipses, a first burst then a slow
 * rhythm); a leader line climbs to an elbow and runs out under the label, the
 * title rising above the line and the subtitle dropping in below it.
 */
const RipplePointer: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const text = cap(overlay.text);
  if (!text) return null;
  const sub = cap(overlay.subtitle);
  const P = spot(overlay.anchor, { x: 0.42, y: 0.64 }, width, height, { x0: 0.12, x1: 0.88, y0: 0.42, y1: 0.8 });
  const onRight = P.x < width * 0.58;
  const sd = onRight ? 1 : -1;
  const land = 9;
  const E: Pt = { x: P.x + sd * 92 * k, y: P.y - 176 * k };
  const room = Math.min(600 * k, onRight ? width - 90 * k - E.x - 14 * k : E.x - 14 * k - 90 * k);
  const { ls, size } = fit(text, room, [52, 44], 0.44, k, 2, 24);
  const tw = Math.max(...ls.map((l) => estW(l, size * k)), sub ? estW(sub, 28 * k, 0.2) : 0);
  const segW = Math.min(room + 14 * k, Math.max(240 * k, tw + 40 * k));
  const H2: Pt = { x: E.x + sd * segW, y: E.y };
  const fall = ramp(frame, 0, land, Easing.bezier(0.55, 0, 1, 0.45));
  const falling = frame < land;
  const dropY = P.y - 160 * k * (1 - fall);
  const sqx = interpolate(frame, [land, land + 3, land + 10], [1.7, 0.85, 1], clamp);
  const sqy = interpolate(frame, [land, land + 3, land + 10], [0.45, 1.15, 1], clamp);
  const starts: number[] = [land, land + 7, land + 15];
  for (let m = 0; m < 30; m++) {
    const s0 = land + 46 + m * 26;
    if (s0 > durationInFrames - 18) break;
    starts.push(s0);
  }
  const life = 42;
  const dl = Math.max(1, Math.hypot(E.x - P.x, E.y - P.y));
  const St: Pt = { x: P.x + ((E.x - P.x) / dl) * 18 * k, y: P.y + ((E.y - P.y) / dl) * 18 * k };
  const leader = `M${St.x} ${St.y} L${E.x} ${E.y} L${H2.x} ${H2.y}`;
  const lp = ramp(frame, land + 5, 18, INOUT) * (1 - out);
  const endDot = ramp(frame, land + 20, 8, BACK) * (1 - out);
  const align = onRight ? "left" : "right";
  const tAt = land + 14;
  return (
    <AbsoluteFill>
      <Shade x={E.x + (sd * segW) / 2} y={E.y} rx={segW * 0.75 + 120 * k} ry={200 * k} a={0.38} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {starts.map((s0, j) => {
          const age = frame - s0;
          if (age < 0 || age >= life) return null;
          const p = age / life;
          const e = 1 - Math.pow(1 - p, 2.2);
          const big = j < 3 ? 1 - j * 0.16 : 0.72;
          const r = (14 + 190 * e * big) * k;
          return (
            <ellipse key={j} cx={P.x} cy={P.y} rx={r} ry={r * 0.34} fill="none" stroke={j === 0 ? accent : "#fff"}
              strokeWidth={(3.4 * (1 - p) + 0.8) * k} strokeOpacity={(1 - p) * 0.85 * (1 - out)} />
          );
        })}
        <path d={leader} fill="none" stroke={SHADOW_STROKE} strokeWidth={7 * k} strokeLinejoin="round" strokeLinecap="round"
          pathLength={1} transform={`translate(${2 * k} ${3 * k})`} {...seg(0, lp)} />
        <path d={leader} fill="none" stroke="#fff" strokeWidth={3.5 * k} strokeLinejoin="round" strokeLinecap="round"
          pathLength={1} {...seg(0, lp)} />
        <circle cx={H2.x} cy={H2.y} r={Math.max(0, 5 * k * endDot)} fill="#fff" />
        {falling ? (
          <ellipse cx={P.x} cy={dropY} rx={6 * k} ry={13 * k} fill={accent} opacity={ramp(frame, 0, 3)} />
        ) : (
          <ellipse cx={P.x} cy={P.y} rx={Math.max(0, 10 * k * sqx * (1 - out))} ry={Math.max(0, 10 * k * sqy * (1 - out))}
            fill={accent} stroke="#fff" strokeWidth={2.5 * k} />
        )}
      </svg>
      <div style={{ position: "absolute", bottom: height - (E.y - 8 * k), left: onRight ? E.x + 14 * k : undefined,
        right: onRight ? undefined : width - (E.x - 14 * k), display: "flex", flexDirection: "column",
        alignItems: onRight ? "flex-start" : "flex-end" }}>
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={tAt + i * 4} step={0.7} style={titleStyle(k, size, align)} />
        ))}
      </div>
      {sub ? (
        <div style={{ position: "absolute", top: E.y + 10 * k, left: onRight ? E.x + 14 * k : undefined,
          right: onRight ? undefined : width - (E.x - 14 * k) }}>
          <Letters text={sub} at={tAt + 6} step={0.55} dir={-1} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k,
            letterSpacing: "0.2em", color: "rgba(255,255,255,.86)", textShadow: TS }} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 7. speech bubble
/**
 * A minimal quote bubble: a small bubble with three typing dots springs out
 * of the speaker, then morphs open to the full message; the words rise in
 * line by line behind an accent bar, the speaker's name above. At the end the
 * words drop out and the bubble shrinks back into the speaker.
 */
const SpeechBubble: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const raw = clean(overlay.text).replace(/^["“”'‘’]+|["“”'‘’]+$/g, "");
  if (!raw) return null;
  const who = cap(overlay.label || overlay.subtitle);
  const S = spot(overlay.anchor, { x: 0.36, y: 0.52 }, width, height, { x0: 0.12, x1: 0.88, y0: 0.42, y1: 0.8 });
  const onRight = S.x < width * 0.56;
  const sd = onRight ? 1 : -1;
  const bx = S.x + sd * 46 * k;
  const by = S.y - 74 * k;
  const padX = 30 * k, padY = 22 * k, barW = 6 * k, inset = 16 * k + barW + 14 * k;
  const room = Math.min(640 * k, (onRight ? width - 90 * k - bx : bx - 90 * k) - inset - padX);
  const { ls, size } = fit(raw, room, [44, 38], 0.45, k, 3, 30);
  const lh = size * k * 1.16;
  const tw = Math.min(room, Math.max(...ls.map((l) => l.length)) * 0.45 * size * k * 1.06);
  const bw = Math.max(200 * k, tw + inset + padX);
  const bh = ls.length * lh + 2 * padY;
  const pop = spring({ frame: frame - 2, fps, config: { damping: 13, stiffness: 200, mass: 0.6 } });
  const m0 = Math.round(fps * 0.55);
  const morph = ramp(frame, m0, 14);
  const w = interpolate(morph, [0, 1], [118 * k, bw]);
  const h = interpolate(morph, [0, 1], [62 * k, bh]);
  const sc = pop * (1 - out);
  const tip: Pt = { x: S.x + sd * 8 * k, y: S.y - 14 * k };
  const bob = Math.sin((frame / fps) * Math.PI * 0.9) * 4 * k * morph;
  const b1 = bx + sd * 24 * k, b2 = bx + sd * 64 * k, yb = by - 6 * k;
  const tail = `M${b1} ${yb} C${b1} ${by + 22 * k} ${tip.x + sd * 14 * k} ${tip.y - 12 * k} ${tip.x} ${tip.y} ` +
    `C${tip.x + sd * 34 * k} ${tip.y - 4 * k} ${b2} ${by + 12 * k} ${b2} ${yb} Z`;
  const dotsOp = (1 - ramp(frame, m0 - 2, 6)) * (frame > 4 ? 1 : 0);
  const side: React.CSSProperties = onRight ? { left: bx } : { right: width - bx };
  return (
    <AbsoluteFill style={{ transform: `translateY(${bob}px) scale(${sc})`, transformOrigin: `${tip.x}px ${tip.y}px` }}>
      <div style={{ position: "absolute", ...side, bottom: height - by, width: w, height: h,
        borderRadius: Math.min(26 * k, h / 2), background: "#fff", boxShadow: "0 18px 44px rgba(0,0,0,.34)" }}>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          gap: 9 * k, opacity: dotsOp }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ width: 12 * k, height: 12 * k, borderRadius: "50%", background: "#2a2c33",
              transform: `translateY(${-Math.max(0, Math.sin((frame / fps) * Math.PI * 3.2 - i * 0.8)) * 7 * k}px)` }} />
          ))}
        </div>
        <div style={{ position: "absolute", left: 16 * k, top: padY, bottom: padY, width: barW, borderRadius: 3 * k,
          background: accent, transform: `scaleY(${morph})`, transformOrigin: "50% 100%" }} />
        <div style={{ position: "absolute", left: inset, bottom: padY, display: "flex", flexDirection: "column" }}>
          {ls.map((ln, i) => (
            <LetterLine key={i} text={ln} at={m0 + 7 + i * 4} step={0.45} style={{ fontFamily: LABEL, fontWeight: 700,
              fontSize: size * k, lineHeight: 1.08, color: INK, whiteSpace: "nowrap", letterSpacing: "0.01em" }} />
          ))}
        </div>
      </div>
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible",
        filter: "drop-shadow(0 6px 8px rgba(0,0,0,.18))" }}>
        <path d={tail} fill="#fff" />
      </svg>
      {who ? (
        <div style={{ position: "absolute", ...side, bottom: height - (by - bh - 12 * k) }}>
          <LetterLine text={`— ${who}`} at={m0 + 10} step={0.6} style={{ ...kickerStyle(k, accent, onRight ? "left" : "right"),
            fontSize: 26 * k, letterSpacing: "0.2em" }} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 8. scribble underline
/** A three-pass marker scribble that draws on, then "boils" (a hand-drawn line boil) while it holds. */
const Scribble: React.FC<{ w: number; top: number; at: number; accent: string; seed: number }> = ({ w, top, at, accent, seed }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const drawF = Math.round(fps * 0.55);
  const draw = ramp(frame, at, drawF, PEN);
  const boil = frame >= at + drawF ? Math.floor(frame / 4) : 0;
  const W = w * 1.1;
  let d = "";
  for (let j = 0; j < 3; j++) {
    const xa = W * 0.03 * j, xb = W * (1 - 0.04 * j);
    for (let i = 0; i <= 18; i++) {
      const u = i / 18;
      const xu = j % 2 === 0 ? u : 1 - u;
      const x = xa + (xb - xa) * xu;
      const y = (8 + j * 9) * k - xu * 7 * k + Math.sin(xu * 8 + seed + j * 2.1) * 2.4 * k
        + (rnd(seed + j * 131 + i * 7 + boil * 17) - 0.5) * 1.8 * k;
      d += `${d ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)} `;
    }
  }
  return (
    <svg width={W} height={50 * k} style={{ position: "absolute", left: -w * 0.05, top, overflow: "visible" }}>
      <path d={d} fill="none" stroke={accent} strokeWidth={15 * k} strokeLinecap="round" strokeLinejoin="round" opacity={0.28}
        pathLength={1} {...seg(out, draw)} />
      <path d={d} fill="none" stroke={accent} strokeWidth={8.5 * k} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} {...seg(out, draw)} />
    </svg>
  );
};

/**
 * A short statement in big condensed caps, letter by letter; then a marker
 * scribble tears back and forth under the key word (overlay.highlight, else
 * the longest word) and keeps a subtle line boil while it holds.
 */
const ScribbleUnderline: Look = ({ overlay, accent }) => {
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const text = cap(overlay.text);
  if (!text) return null;
  const sub = cap(overlay.subtitle);
  const a = overlay.anchor;
  const hasA = !!a && Number.isFinite(a.x) && Number.isFinite(a.y);
  const pos = hasA ? spot(a, { x: 0, y: 0 }, width, height, { x0: 0.06, x1: 0.55, y0: 0.14, y1: 0.6 })
    : { x: 110 * k, y: height * 0.5 };
  const room = Math.min(1150 * k, width - 90 * k - pos.x);
  const { ls, size } = fit(text, room, [80, 66], 0.44, k, 2, 22);
  const px = size * k;
  const norm = (w: string) => w.replace(/[^A-Z0-9']/g, "");
  const words = ls.map((l) => l.split(" ").filter(Boolean));
  const hi = new Set(cap(overlay.highlight).split(/[\s,]+/).map(norm).filter(Boolean));
  let hot: [number, number] = [-1, -1];
  let best = 0;
  words.forEach((ws, li) => ws.forEach((w, wi) => {
    if (hot[0] < 0 && hi.has(norm(w))) hot = [li, wi];
  }));
  if (hot[0] < 0) {
    words.forEach((ws, li) => ws.forEach((w, wi) => {
      const n = norm(w).length;
      if (n > best) { best = n; hot = [li, wi]; }
    }));
  }
  const offsets = words.map((ws) => {
    let acc = 0;
    return ws.map((w) => { const o = acc; acc += w.length + 1; return o; });
  });
  const at0 = 4;
  const scribAt = at0 + Math.round(fps * 0.4);
  const blockW = Math.max(...ls.map((l) => estW(l, px)));
  const blockH = ls.length * px * 1.12 + (sub ? 80 * k : 40 * k);
  return (
    <AbsoluteFill>
      <Shade x={pos.x + blockW * 0.45} y={pos.y + blockH / 2} rx={blockW * 0.85 + 200 * k} ry={blockH + 140 * k} a={0.4} />
      <div style={{ position: "absolute", left: pos.x, top: pos.y, display: "flex", flexDirection: "column",
        alignItems: "flex-start" }}>
        {words.map((ws, li) => (
          <div key={li} style={{ whiteSpace: "nowrap", fontFamily: DISPLAY, fontSize: px, lineHeight: 1, color: "#fff",
            letterSpacing: "0.03em", textShadow: TS }}>
            {ws.map((w, wi) => {
              const isHot = hot[0] === li && hot[1] === wi;
              return (
                <span key={wi} style={{ position: "relative", display: "inline-block",
                  marginRight: wi < ws.length - 1 ? "0.24em" : 0 }}>
                  <Letters text={w} at={at0 + li * 4 + offsets[li][wi] * 0.7} step={0.7} />
                  {isHot ? <Scribble w={estW(w, px)} top={px * 0.9} at={scribAt} accent={accent} seed={seedOf(w)} /> : null}
                </span>
              );
            })}
          </div>
        ))}
        {sub ? (
          <div style={{ marginTop: 34 * k }}>
            <LetterLine text={sub} at={scribAt + 6} step={0.5} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k,
              letterSpacing: "0.2em", color: "rgba(255,255,255,.86)", textShadow: TS, whiteSpace: "nowrap" }} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 9. spotlight vignette
/**
 * A searchlight: the frame dims and loses its colour while a soft pool of
 * light sweeps in from off the subject, tightens onto it and breathes; an
 * accent ring draws round the pool and the label steps out on an elbow line.
 * At the end the iris opens back to the full picture.
 */
const Spotlight: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const text = cap(overlay.text);
  if (!text) return null;
  const sub = cap(overlay.subtitle);
  const C = spot(overlay.anchor, { x: 0.4, y: 0.46 }, width, height, { x0: 0.2, x1: 0.8, y0: 0.3, y1: 0.68 });
  const seed = seedOf(text);
  const R = 220 * k;
  const travel = ramp(frame, 2, Math.round(fps * 0.9), Easing.bezier(0.33, 0, 0.15, 1));
  const ox = (rnd(seed) > 0.5 ? 1 : -1) * (190 + rnd(seed + 1) * 110) * k;
  const oy = (rnd(seed + 2) - 0.5) * 170 * k;
  const breathe = 1 + 0.02 * Math.sin((frame / fps) * Math.PI * 1.1);
  const x = C.x + ox * (1 - travel), y = C.y + oy * (1 - travel);
  const r = interpolate(travel, [0, 1], [R * 2.1, R]) * breathe * (1 + out * 2.4);
  const dark = ramp(frame, 0, 14) * (1 - out);
  const a = 0.76 * dark;
  const gx = Math.round(x), gy = Math.round(y);
  const bg = `radial-gradient(circle ${Math.round(r * 1.5)}px at ${gx}px ${gy}px, rgba(0,0,0,0) 0px, ` +
    `rgba(0,0,0,0) ${Math.round(r * 0.72)}px, rgba(0,0,0,${(a * 0.6).toFixed(3)}) ${Math.round(r * 1.02)}px, ` +
    `rgba(0,0,0,${a.toFixed(3)}) ${Math.round(r * 1.5)}px)`;
  const mask = `radial-gradient(circle ${Math.round(r * 1.3)}px at ${gx}px ${gy}px, transparent ${Math.round(r * 0.8)}px, ` +
    `black ${Math.round(r * 1.2)}px)`;
  const ringD = ramp(frame, Math.round(fps * 0.75), 20, INOUT);
  const onRight = width - C.x >= C.x;
  const sd = onRight ? 1 : -1;
  const ang = (-24 * Math.PI) / 180;
  const q0: Pt = { x: C.x + sd * Math.cos(ang) * R * 1.08, y: C.y + Math.sin(ang) * R * 1.08 };
  const q1: Pt = { x: q0.x + sd * 56 * k, y: q0.y - 26 * k };
  const q2: Pt = { x: q1.x + sd * 40 * k, y: q1.y };
  const cp = ramp(frame, Math.round(fps * 0.9), 12, INOUT) * (1 - out);
  const lx = q2.x + sd * 16 * k;
  const room = Math.min(600 * k, onRight ? width - 90 * k - lx : lx - 90 * k);
  const { ls, size } = fit(text, room, [64, 52], 0.44, k, 2, 20);
  const labelAt = Math.round(fps * 0.85);
  const align = onRight ? "left" : "right";
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ backdropFilter: "grayscale(0.85)", WebkitBackdropFilter: "grayscale(0.85)",
        maskImage: mask, WebkitMaskImage: mask, opacity: dark }} />
      <AbsoluteFill style={{ background: bg }} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <circle cx={x} cy={y} r={r * 1.03} fill="none" stroke={accent} strokeWidth={2.6 * k} pathLength={1}
          transform={`rotate(-90 ${x} ${y})`} {...seg(out, ringD)} />
        <circle cx={x} cy={y} r={r * 1.1} fill="none" stroke="#fff" strokeWidth={1.6 * k} strokeDasharray={`${2 * k} ${12 * k}`}
          strokeOpacity={0.4 * ramp(frame, Math.round(fps * 0.9), 12) * (1 - out)} transform={`rotate(${frame * 0.4} ${x} ${y})`} />
        <path d={`M${q0.x} ${q0.y} L${q1.x} ${q1.y} L${q2.x} ${q2.y}`} fill="none" stroke="#fff" strokeWidth={3 * k}
          strokeLinecap="round" strokeLinejoin="round" pathLength={1} {...seg(0, cp)} />
        <circle cx={q0.x} cy={q0.y} r={Math.max(0, 5 * k * ramp(frame, Math.round(fps * 0.9), 8, BACK) * (1 - out))} fill={accent} />
      </svg>
      <div style={{ position: "absolute", top: q2.y, left: onRight ? lx : undefined, right: onRight ? undefined : width - lx,
        transform: "translateY(-50%)", display: "flex", flexDirection: "column", alignItems: onRight ? "flex-start" : "flex-end",
        gap: 2 * k }}>
        {sub ? <LetterLine text={sub} at={labelAt} step={0.6} style={kickerStyle(k, accent, align)} /> : null}
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={labelAt + 3 + i * 4} step={0.8} style={titleStyle(k, size, align)} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. info chip stack
type Chip = { key: string; num: number | null; val: string; prefix: string; suffix: string };

/**
 * A connector climbs from a dot on the subject to a joint, a spine drops from
 * it, and two or three white fact chips swing down off the spine one after
 * another (hinged at the top, a springy 3D swing); numbers roll inside them.
 * At the end the chips fold back up in reverse and the connector retracts.
 */
const ChipStack: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const toChip = (it: Item): Chip | null => {
    if (!it || typeof it !== "object") return null;
    const v = finite(it.value);
    const label = short(cap(it.label), 18);
    const txt = short(cap(it.text), 24);
    if (v !== null) return { key: label, num: v, val: "", prefix: it.prefix || "", suffix: sfx(it.suffix) };
    if (txt) return { key: label, num: null, val: txt, prefix: "", suffix: "" };
    if (label) return { key: "", num: null, val: label, prefix: "", suffix: "" };
    return null;
  };
  const chips = ((overlay.items || []) as Item[]).map(toChip).filter((c): c is Chip => c !== null).slice(0, 3);
  if (!chips.length) return null;
  const n = chips.length;
  const title = cap(overlay.text);
  const P = spot(overlay.anchor, { x: 0.36, y: 0.66 }, width, height, { x0: 0.12, x1: 0.84, y0: 0.46, y1: 0.8 });
  const onRight = P.x < width * 0.56;
  const sd = onRight ? 1 : -1;
  const CH = 62 * k, GAP = 14 * k;
  const J: Pt = { x: P.x + sd * 120 * k, y: P.y - 250 * k };
  const spineLen = (n - 1) * (CH + GAP);
  const exitC = ramp(frame, durationInFrames - 10, 8, IN);
  const conn = ramp(frame, 5, 13, INOUT) * (1 - exitC);
  const spineP = ramp(frame, 16, 6 + n * 5, INOUT) * (1 - exitC);
  const dl = Math.max(1, Math.hypot(J.x - P.x, J.y - P.y));
  const St: Pt = { x: P.x + ((J.x - P.x) / dl) * 16 * k, y: P.y + ((J.y - P.y) / dl) * 16 * k };
  const dotP = ramp(frame, 0, 10, BACK) * (1 - exitC);
  const per = Math.round(fps * 1.3);
  const ph = frame > 10 ? ((frame - 10) % per) / per : -1;
  const side = (x: number): React.CSSProperties => (onRight ? { left: x } : { right: width - x });
  const chipX = J.x + sd * 22 * k;
  return (
    <AbsoluteFill>
      <Shade x={J.x + sd * 220 * k} y={J.y + spineLen / 2} rx={560 * k} ry={spineLen / 2 + 220 * k} a={0.34} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <path d={`M${St.x} ${St.y} L${J.x} ${J.y}`} fill="none" stroke="#fff" strokeWidth={3 * k} strokeLinecap="round"
          pathLength={1} {...seg(0, conn)} />
        <line x1={J.x} y1={J.y} x2={J.x} y2={J.y + spineLen * spineP} stroke="#fff" strokeWidth={3 * k}
          strokeOpacity={spineP > 0.01 && spineLen > 0 ? 1 : 0} />
        {chips.map((_, i) => {
          const at = 17 + i * Math.round(fps * 0.22);
          const p = ramp(frame, at, 8, BACK) * (1 - exitC);
          const cy = J.y + i * (CH + GAP);
          return (
            <g key={i}>
              <line x1={J.x} y1={cy} x2={J.x + sd * 22 * k * Math.min(1, p)} y2={cy} stroke="#fff" strokeWidth={3 * k}
                strokeOpacity={p > 0.01 ? 1 : 0} />
              <circle cx={J.x} cy={cy} r={Math.max(0, 5.5 * k * p)} fill={i === 0 ? accent : "#fff"} />
            </g>
          );
        })}
        {ph >= 0 ? (
          <circle cx={P.x} cy={P.y} r={(8 + 24 * ph) * k} fill="none" stroke={accent} strokeWidth={2.5 * k}
            strokeOpacity={(1 - ph) * 0.6 * (1 - exitC)} />
        ) : null}
        <circle cx={P.x} cy={P.y} r={Math.max(0, 8 * k * dotP)} fill={accent} stroke="#fff" strokeWidth={2.5 * k}
          strokeOpacity={dotP > 0.05 ? 1 : 0} />
      </svg>
      {title ? (
        <div style={{ position: "absolute", ...side(chipX), bottom: height - (J.y - CH / 2 - 12 * k) }}>
          <LetterLine text={title} at={12} step={0.6} style={{ ...kickerStyle(k, accent, onRight ? "left" : "right") }} />
        </div>
      ) : null}
      {chips.map((c, i) => {
        const at = 17 + i * Math.round(fps * 0.22);
        const sp = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 170, mass: 0.7 } });
        const fold = ramp(frame, durationInFrames - 15 + (n - 1 - i) * 2, 8, IN);
        const rot = (1 - sp) * -96 - fold * 96;
        const cy = J.y + i * (CH + GAP);
        return (
          <div key={i} style={{ position: "absolute", ...side(chipX), top: cy - CH / 2, height: CH, display: "flex",
            alignItems: "center", gap: 14 * k, padding: `0 ${22 * k}px 0 ${18 * k}px`, background: "#fff", borderRadius: 10 * k,
            boxShadow: "0 14px 34px rgba(0,0,0,.34)", whiteSpace: "nowrap",
            borderLeft: onRight ? `${5 * k}px solid ${accent}` : undefined,
            borderRight: onRight ? undefined : `${5 * k}px solid ${accent}`,
            transform: `perspective(${900 * k}px) rotateX(${rot}deg)`, transformOrigin: "50% 0%", backfaceVisibility: "hidden",
            opacity: frame < at ? 0 : 1 }}>
            {c.key ? (
              <>
                <Letters text={c.key} at={at + 3} step={0.5} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                  letterSpacing: "0.14em", color: "#6c6f78" }} />
                <div style={{ width: 1.5 * k, height: 26 * k, background: "#d5d6db" }} />
              </>
            ) : null}
            {c.num !== null ? (
              <Reveal at={at + 5} frames={12}>
                <Odometer value={c.num} at={at + 5} frames={Math.round(fps * 0.9)} size={42 * k} color={INK} prefix={c.prefix}
                  suffix={c.suffix} suffixScale={0.62} />
              </Reveal>
            ) : (
              <Letters text={c.val} at={at + 5} step={0.5} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k,
                letterSpacing: "0.04em", color: INK }} />
            )}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "co-circle-pulse": CirclePulse,
  "co-draw-arrow": DrawArrow,
  "co-bracket-label": BracketLabel,
  "co-target-lock": TargetLock,
  "co-measure-line": MeasureLine,
  "co-ripple-pointer": RipplePointer,
  "co-speech-bubble": SpeechBubble,
  "co-scribble-underline": ScribbleUnderline,
  "co-spotlight": Spotlight,
  "co-chip-stack": ChipStack,
};
