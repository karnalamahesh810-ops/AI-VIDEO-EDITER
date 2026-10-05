import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay } from "../../types";
import { Odometer, Scrim, Tag, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Icons & pictograms with numbers (family "ic-"): ten looks where a drawn icon
 * carries the figure, each with its own motion hook, in the pro house style
 * (condensed caps rising out of masks and dropping out at the end, odometer
 * numbers, accent + white + near-black; red only for fire, cyan only for water
 * and electric arcs).
 *
 * The owner: a single number rides ON the playing footage as a compact
 * overlay, it does not replace the picture. So nine of the ten are corner tags
 * (low left or low right) with only a soft local shade under them; the house
 * grid, a share of homes that needs its whole pictogram, is the one data card.
 *
 *   ic-drop-fill      (tag, low left) a droplet falls into a water-drop icon,
 *                     which fills to the share with a live surface and bubbles
 *   ic-house-grid     (card) houses land in a diagonal wave; the counted share
 *                     switches on in a scattered order, each with a flicker
 *   ic-traffic-queue  (tag, low left) cars brake into a two-lane queue on a short
 *                     road under the rolling count; the jam creeps, then clears
 *   ic-dollar-pulse   (tag, low left) a coin badge beats like a heart; an ECG
 *                     trace carries every beat out under the amount
 *   ic-calendar-tear  (tag, low right) a tear-off pad: pages rip away and blow
 *                     off into the picture until the day count is left on top
 *   ic-hourglass      (tag, low right) an hourglass flips over and its sand runs
 *                     beside the time figure
 *   ic-power-bolt     (tag, low left) a lightning bolt charges up from its tip
 *                     with crackling arcs, flashes full, then hums with current
 *   ic-fire-flicker   (tag, low left) a living flame throwing embers; a burn
 *                     line runs under the area figure as it rolls
 *   ic-crowd-swell    (tag, low right) a crowd gathers outward from the centre,
 *                     row behind row, each figure flashing in as the count rolls
 *   ic-factory-smoke  (tag, low right) a factory rises from its ground line, the
 *                     windows light and the chimneys puff smoke into the picture
 *
 * Every size is 1080p-referenced and multiplied by k. Deterministic: every
 * "random" value comes from rnd(index), never Math.random.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const RED = "#ff3b30";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
/** The flame's warm gold: fire stays fire whatever the theme accent is. */
const FLAME = "#ffb238";

// ------------------------------------------------------------------ data helpers
const S = (v: unknown): string =>
  typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const cap = (v: unknown): string => S(v).trim().toUpperCase();
const num = (v: unknown): number => {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") return Number(v.replace(/[,\s]/g, ""));
  return NaN;
};
const clamp01 = (v: number): number => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0);
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
/** Deterministic 0..1 noise of an index. */
const rnd = (i: number): number => {
  const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
/** A hex colour with an alpha byte; anything that is not a hex colour is returned unchanged. */
const alpha = (c: string, a: number): string => {
  const h = (c || "").trim();
  const byte = Math.round(clamp01(a) * 255).toString(16).padStart(2, "0");
  if (/^#[0-9a-f]{6}$/i.test(h)) return `${h}${byte}`;
  if (/^#[0-9a-f]{3}$/i.test(h)) return `#${h[1]}${h[1]}${h[2]}${h[2]}${h[3]}${h[3]}${byte}`;
  return h || "#F2B544";
};
/** A near-white accent (the "white" theme) needs the dark tag, or white text vanishes on it. */
const isLight = (c: string): boolean => {
  const m = /^#?([0-9a-f]{6})$/i.exec((c || "").trim());
  if (!m) return false;
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.72;
};
/**
 * The owner's text language (2026-09-30: "NO background layout, ONLY TEXT: bold
 * white text with a black stroke"): the letters carry a black outline painted
 * under the fill and a soft shadow, so they read on bright sky and night alike.
 * Inherited by every glyph inside (the odometer's digits too).
 */
const outline = (size: number, k: number): React.CSSProperties => ({
  WebkitTextStroke: `${Math.max(4.5 * k, Math.min(12 * k, size * 0.1)).toFixed(2)}px #000`, paintOrder: "stroke fill",
  textShadow: `0 ${3 * k}px ${4 * k}px rgba(0,0,0,.35), 0 ${8 * k}px ${24 * k}px rgba(0,0,0,.5)`,
} as React.CSSProperties);
const fmt = (v: number): string => formatValue(v).text;
const f1 = (v: number): string => (Number.isFinite(v) ? v.toFixed(1) : "0");
/** Two significant digits ("each figure is about 44,000", not 44,127). */
const round2 = (v: number): number => {
  if (!Number.isFinite(v) || v <= 0) return 0;
  const p = Math.pow(10, Math.max(0, Math.floor(Math.log10(v)) - 1));
  return Math.round(v / p) * p;
};

/** Short units ride the number ("%", "M", "GW"); words sit beside it in condensed caps ("ACRES"). */
const splitUnit = (suffix: string): { short: string; word: string } => {
  const s = (suffix || "").trim();
  if (!s) return { short: "", word: "" };
  if (s.length <= 3 && !/\s/.test(s)) return { short: s, word: "" };
  const m = /^([KMBT])\s+(.+)$/i.exec(s);
  if (m) return { short: m[1].toUpperCase(), word: m[2].toUpperCase() };
  return { short: "", word: s.toUpperCase() };
};
/** A raw count in the millions or billions reads as "2.5" + "M". */
const magnitude = (v: number, short: string): { v: number; short: string } => {
  if (short) return { v, short };
  const a = Math.abs(v);
  if (a >= 1e9) return { v: Math.round(v / 1e8) / 10, short: "B" };
  if (a >= 1e6) return { v: Math.round(v / 1e5) / 10, short: "M" };
  return { v, short };
};
const big = (v: number): string => {
  const m = magnitude(v, "");
  return `${fmt(m.v)}${m.short}`;
};
/** "2.2" with the unit "M PEOPLE" is 2,200,000 people. */
const MULT: Record<string, number> = { K: 1e3, M: 1e6, B: 1e9, T: 1e12 };

/** A share of a whole: "%" is out of 100, `total` is "out of"; frac null for a bare figure. */
type Share = { value: number; frac: number | null; total: number };
const shareOf = (ov: Overlay): Share | null => {
  const value = num(ov.value);
  if (!Number.isFinite(value)) return null;
  const pct = S(ov.suffix).trim() === "%";
  const total = num(ov.total);
  const based = !pct && Number.isFinite(total) && total > 0;
  const frac = pct ? value / 100 : based ? value / total : null;
  return { value, frac: frac === null ? null : clamp01(frac), total: based ? total : NaN };
};

// ------------------------------------------------------------------ timing helpers
/** Seconds to frames, scaled to the overlay length: a 3 s beat builds faster than a 6 s one. */
const useT = () => {
  const { fps, durationInFrames } = useVideoConfig();
  const tempo = Math.max(0.6, Math.min(1.1, durationInFrames / 150));
  return (sec: number): number => Math.round(fps * sec * tempo);
};

/** 0 while the graphic holds, easing to 1 over the last frames (the graphics' exit). */
const useExit = (frames = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - frames - 2, frames, expoIn);
};

/** A safety fade over the very last frames for any residue after the designed exits. */
const useFin = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return 1 - ramp(frame, durationInFrames - 4, 3);
};

// ------------------------------------------------------------------ text helpers
/**
 * LetterLine's reveal (letters rise out of a mask one after another, then drop
 * out at the end) with the exit stagger fitted to the line, so even a long line
 * has left by the cut. Never wraps: callers break lines with lines().
 */
const Letters: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 0.7, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    if (!text) return null;
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
            <span key={i} style={{ display: "inline-block", transform: `translateY(${y.toFixed(2)}%)`, whiteSpace: "pre",
              opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
          );
        })}
      </div>
    );
  };

/** Up to `max` wrapped lines, each rising letter by letter; the last one gets an ellipsis when cut. */
const Lines: React.FC<{ text: string; chars: number; max: number; at: number; gap?: number;
  align?: "left" | "center" | "right"; style: React.CSSProperties }> =
  ({ text, chars, max, at, gap = 4, align = "left", style }) => {
    const all = lines(text, chars);
    if (!all.length) return null;
    const ls = all.slice(0, max);
    if (all.length > max) ls[ls.length - 1] = `${ls[ls.length - 1].replace(/[\s.,;:\-–—]+$/, "")}…`;
    return (
      <div style={{ display: "flex", flexDirection: "column",
        alignItems: align === "center" ? "center" : align === "right" ? "flex-end" : "flex-start" }}>
        {ls.map((ln, i) => (
          <Letters key={i} text={ln} at={at + i * gap} step={0.6} style={{ textAlign: align, ...style }} />
        ))}
      </div>
    );
  };

/** A block rising out of its mask (pin 0 -> 1) and leaving upward through it (pout 0 -> 1). */
const MaskIO: React.FC<{ pin: number; pout: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ pin, pout, children, style }) => (
    <div style={{ overflow: "hidden", paddingBottom: "0.04em", ...style }}>
      <div style={{ transform: `translateY(${(((1 - pin) - pout) * 112).toFixed(2)}%)` }}>{children}</div>
    </div>
  );

/** The accent Tag (it wipes open), wiping shut from the left at the end. */
const TagOut: React.FC<{ text: string; at: number; accent: string; size?: number }> =
  ({ text, at, accent, size = 30 }) => {
    const exit = useExit();
    if (!text) return null;
    return (
      <div style={{ display: "inline-flex",
        clipPath: exit > 0.001 ? `inset(0 0 0 ${(exit * 100).toFixed(2)}%)` : undefined }}>
        <Tag text={text} at={at} accent={accent} size={size} dark={isLight(accent)} />
      </div>
    );
  };

/** What the figure counts: one or two lines of outlined bold caps (no tag box). */
const Caption: React.FC<{ text: string; at: number; accent: string; align?: "left" | "center" | "right";
  size?: number; chars?: number }> = ({ text, at, align = "left", size = 32, chars = 30 }) => {
  const k = useK();
  const t = cap(text);
  if (!t) return null;
  // At least 44 px at 1080p: a phone shows the frame at a third of that.
  const px = Math.max(44, size * 1.45);
  const per = Math.max(10, Math.round((chars * size) / px * 1.15));
  return (
    <Lines text={t} chars={per} max={3} at={at} align={align} style={{ fontFamily: LABEL, fontWeight: 800,
      fontSize: px * k, letterSpacing: "0.03em", color: "#fff", lineHeight: 1.04, ...outline(px * k, k) }} />
  );
};

/** A small caps kicker in the accent, letter by letter, cut to `max` characters (it never wraps). */
const Kicker: React.FC<{ text: string; accent: string; at?: number; size?: number; max?: number;
  align?: "left" | "center" | "right" }> = ({ text, accent, at = 0, size = 26, max = 34, align = "left" }) => {
    const k = useK();
    const t = clip(cap(text), max);
    if (!t) return null;
    return (
      <Letters text={t} at={at} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: Math.max(34, size * 1.3) * k,
        letterSpacing: "0.1em", color: accent, textAlign: align, lineHeight: 1.1, ...outline(Math.max(34, size * 1.3) * k, k) }} />
    );
  };

/** A small mono readout ("OF 10,000"), sliding up out of its mask and leaving through it. */
const Readout: React.FC<{ text: string; at: number; color?: string; size?: number }> =
  ({ text, at, color = "rgba(255,255,255,.7)", size = 24 }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const exit = useExit();
    if (!text) return null;
    return (
      <MaskIO pin={ramp(frame, at, 14)} pout={exit}>
        <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: Math.max(32, size * 1.3) * k, letterSpacing: "0.06em",
          color, whiteSpace: "nowrap", lineHeight: 1.2, ...outline(Math.max(32, size * 1.3) * k, k) }}>{text}</span>
      </MaskIO>
    );
  };

/**
 * The figure: prefix, rolling digits and a short unit ("%", "M", "GW") on one
 * line, a unit word ("ACRES") beside it; rises out of its mask, leaves upward.
 */
const Figure: React.FC<{ value: number; at: number; frames: number; size: number; accent: string; prefix?: string;
  suffix?: string; color?: string; align?: "left" | "center" | "right"; wordColor?: string }> =
  ({ value, at, frames, size, accent, prefix = "", suffix = "", color = "#fff", align = "left", wordColor }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const exit = useExit();
    const u = splitUnit(suffix);
    const m = magnitude(value, u.short);
    const wordPx = Math.max(26 * k, Math.min(40 * k, size * 0.3));
    return (
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12 * k, ...outline(size * 0.62, k),
        justifyContent: align === "center" ? "center" : align === "right" ? "flex-end" : "flex-start" }}>
        <MaskIO pin={ramp(frame, at - 6, 14)} pout={exit}>
          <Odometer value={m.v} at={at} frames={frames} size={size} color={color} prefix={prefix.trim()} suffix={m.short}
            suffixColor={accent} suffixScale={m.short === "%" ? 0.5 : 0.44} />
        </MaskIO>
        {u.word ? (
          <MaskIO pin={ramp(frame, at + 8, 14)} pout={exit} style={{ marginBottom: size * 0.1 }}>
            <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: wordPx * 1.25, lineHeight: 1,
              letterSpacing: "0.06em", color: wordColor || accent, whiteSpace: "nowrap", ...outline(wordPx * 1.25, k) }}>{u.word}</span>
          </MaskIO>
        ) : null}
      </div>
    );
  };

/**
 * The soft local shade under a corner tag: a radial gradient centred on the
 * tag (x/y in % of the frame), never a full-frame darkening. None full screen.
 */
const Shade: React.FC<{ ov: Overlay; x: number; y: number; rx?: number; ry?: number; exit: number }> =
  ({ ov, x, y, rx = 50, ry = 50, exit }) => {
    const frame = useCurrentFrame();
    if (ov.fullFrame) return null;
    return (
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * (1 - exit), background:
        `radial-gradient(ellipse ${rx}% ${ry}% at ${x}% ${y}%, rgba(0,0,0,.34) 0%, rgba(0,0,0,.14) 45%, rgba(0,0,0,0) 76%)` }} />
    );
  };

// ================================================================== 1. drop fill (tag, low left)
/** A water drop in a 200 x 280 box: the point at the top, a round bulb below. */
const DROP = "M100 6 C122 52 184 116 184 190 A84 84 0 1 1 16 190 C16 116 78 52 100 6 Z";
const DROP_FLOOR = 272;
const DROP_TOP = 8;

/** A sine surface from x0 to x1 (an open polyline). */
const wavePts = (y: number, amp: number, ph: number, wl: number, x0: number, x1: number): string => {
  let d = "";
  for (let x = x0; x <= x1 + 0.01; x += 8) {
    d += `${d ? " L" : "M"}${f1(x)} ${(y + Math.sin((x / wl) * Math.PI * 2 + ph) * amp).toFixed(2)}`;
  }
  return d;
};
/** The same surface closed down to `bottom`: a band of water. */
const waveBand = (y: number, amp: number, ph: number, wl: number, x0: number, x1: number, bottom: number): string =>
  `${wavePts(y, amp, ph, wl, x0, x1)} L${f1(x1)} ${bottom} L${f1(x0)} ${bottom} Z`;

/**
 * Low left on the footage: a water-drop icon draws on, a droplet falls in
 * through its tip and splashes, then the drop fills to the share (a live
 * double surface, rising bubbles) while an accent marker climbs the gauge
 * beside it and the percentage rolls. A bare figure (no % and no total) fills
 * the drop whole without the gauge. Exit: the water drains, the outline
 * undraws, the words drop out.
 */
const DropFill: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const sh = shareOf(overlay);
  if (!sh) return null;
  const gauge = sh.frac !== null;
  const target = sh.frac === null ? 1 : sh.frac;
  const s = (214 * k) / 280;
  const VW = gauge ? 250 : 204;
  const id = `icdrop${overlay.startFrame}`;
  const fallAt = T(0.2);
  const hit = fallAt + 12;
  const fillF = T(1.45);
  const draw = ramp(frame, 0, 18, inOut) * (1 - exit);
  const level = target * ramp(frame, hit, fillF, inOut) * (1 - exit);
  const surf = DROP_FLOOR - level * (DROP_FLOOR - DROP_TOP);
  const settle = ramp(frame, hit + fillF - 10, 30);
  const amp = 1.3 + 3.2 * (1 - settle);
  const ph = (frame / fps) * 3.4;
  const fall = interpolate(frame, [fallAt, hit], [0, 1], { ...clamp, easing: Easing.in(Easing.quad) });
  const dropBottom = -90 + (DROP_FLOOR - 4 + 90) * fall;
  const splash = interpolate(frame, [hit, hit + 20], [0, 1], clamp);
  const ringY = Math.min(DROP_FLOOR - 3, surf);
  const depth = DROP_FLOOR - surf;
  const tot = Number.isFinite(sh.total) ? magnitude(sh.total, "") : null;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={14} y={89} exit={exit} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 112 * k, display: "flex", alignItems: "center",
        gap: 30 * k }}>
        <svg width={VW * s} height={280 * s} viewBox={`0 0 ${VW} 280`} style={{ overflow: "visible", display: "block",
          transform: `scale(${(1 - 0.06 * exit).toFixed(4)})` }}>
          <defs>
            <clipPath id={`${id}c`}><path d={DROP} /></clipPath>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#9be3ff" />
              <stop offset="0.4" stopColor={CYAN} />
              <stop offset="1" stopColor="#0a3566" />
            </linearGradient>
            <radialGradient id={`${id}h`} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor={CYAN} stopOpacity={0.3} />
              <stop offset="1" stopColor={CYAN} stopOpacity={0} />
            </radialGradient>
          </defs>
          <ellipse cx={100} cy={186} rx={150} ry={150} fill={`url(#${id}h)`} opacity={draw * (0.35 + 0.65 * level)} />
          <path d={DROP} fill="rgba(8,10,14,.38)" opacity={draw} />
          <g clipPath={`url(#${id}c)`}>
            {level > 0.002 ? (
              <g>
                <path d={waveBand(surf - 2, amp * 0.75, ph * 0.8 + 2.1, 96, -8, 208, 290)} fill={CYAN} opacity={0.32} />
                <path d={waveBand(surf, amp, ph, 128, -8, 208, 290)} fill={`url(#${id}w)`} />
                <path d={wavePts(surf, amp, ph, 128, -8, 208)} fill="none" stroke="rgba(255,255,255,.8)" strokeWidth={1.5} />
                {depth > 26 ? [0, 1, 2, 3, 4].map((i) => {
                  const per = Math.round(fps * (1.2 + rnd(i + 1) * 0.9));
                  const t = ((frame + Math.round(rnd(i + 11) * per)) % per) / per;
                  const x = 58 + rnd(i + 21) * 84 + Math.sin(t * 7 + i) * 3;
                  const y = DROP_FLOOR - 6 - t * (depth - 12);
                  return <circle key={i} cx={x} cy={y} r={1.5 + rnd(i + 31) * 2.4} fill="none"
                    stroke="rgba(255,255,255,.7)" strokeWidth={0.9} opacity={(1 - t) * 0.8} />;
                }) : null}
              </g>
            ) : null}
            {splash > 0 && splash < 1 ? [0, 1].map((i) => {
              const q = clamp01(splash * 1.25 - i * 0.25);
              const rx = 6 + 64 * q;
              return <ellipse key={i} cx={100} cy={ringY} rx={rx} ry={rx * 0.2} fill="none" stroke="#fff"
                strokeWidth={1.6} opacity={(1 - q) * 0.9} />;
            }) : null}
          </g>
          <path d="M50 150 C44 176 48 212 68 234" fill="none" stroke="#fff" strokeOpacity={0.32} strokeWidth={6}
            strokeLinecap="round" opacity={ramp(frame, 14, 14) * (1 - exit)} />
          <path d={DROP} fill="none" stroke="#fff" strokeWidth={3.4} strokeLinejoin="round" pathLength={1}
            strokeDasharray="1" strokeDashoffset={1 - draw} />
          {frame >= fallAt && frame < hit ? (
            <path d={DROP} transform={`translate(${100 - 11} ${f1(dropBottom - 30.1)}) scale(0.11)`} fill={CYAN} />
          ) : null}
          {splash > 0 && splash < 1 ? [-1, -0.4, 0.45, 1].map((dir, i) => {
            const h = 4 * (30 + i * 4) * splash * (1 - splash);
            return <circle key={`s${i}`} cx={100 + dir * 30 * splash} cy={ringY - 3 - h} r={2.6 * (1 - splash * 0.5)}
              fill="#bfefff" opacity={1 - splash} />;
          }) : null}
          {gauge ? (
            <g opacity={ramp(frame, 8, 14) * (1 - exit)}>
              <line x1={214} x2={214} y1={DROP_TOP} y2={DROP_FLOOR} stroke="rgba(255,255,255,.3)" strokeWidth={1.4} />
              {[0, 0.25, 0.5, 0.75, 1].map((t) => {
                const y = DROP_FLOOR - t * (DROP_FLOOR - DROP_TOP);
                return <line key={t} x1={t === 0.5 ? 204 : 208} x2={214} y1={y} y2={y} stroke="rgba(255,255,255,.6)"
                  strokeWidth={1.4} />;
              })}
              <path d={`M216 ${surf.toFixed(2)} L228 ${(surf - 6).toFixed(2)} L228 ${(surf + 6).toFixed(2)} Z`} fill={accent} />
              <line x1={228} x2={242} y1={surf} y2={surf} stroke={accent} strokeWidth={2} />
            </g>
          ) : null}
        </svg>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 * k, maxWidth: 620 * k }}>
          <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.1)} />
          <Figure value={sh.value} at={hit} frames={T(1.3)} size={128 * k} accent={accent}
            prefix={S(overlay.prefix)} suffix={S(overlay.suffix)} />
          {tot ? <Readout text={`OF ${fmt(tot.v)}${tot.short}`} at={hit + 10} /> : null}
          <Caption text={S(overlay.text)} at={hit + T(0.45)} accent={accent} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. house grid (card)
/** A house in a 64 x 60 box: roof, walls and chimney as lines; the lit body; two windows and a door. */
const HOUSE_LINE = "M3 29 L32 6 L61 29 M10 24 V56 H54 V24 M44 15.5 V8 H50 V20.3";
const HOUSE_BODY = "M10 24 L32 7.5 L54 24 V56 H10 Z";
const HOUSE_LIGHTS = "M16 31 h10 v9 h-10 Z M38 31 h10 v9 h-10 Z M27 43 h10 v13 h-10 Z";

/**
 * A data card: up to forty house icons land row by row in a diagonal wave on
 * street lines; then the counted share switches on in a fixed scattered order,
 * each house flickering on (windows, door and a warm halo in the accent) while
 * the count rolls: "1 IN 3" (the grid is sized to a multiple of 3), "30%" or
 * "2,400 OF 10,000", with a legend of what one house stands for. Exit: the
 * lights go out, the houses drop away, the words leave through their masks.
 */
const HouseGrid: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  const total = num(overlay.total);
  const suffix = S(overlay.suffix).trim();
  if (!Number.isFinite(value) || value < 0) return null;
  const pct = suffix === "%";
  const based = !pct && Number.isFinite(total) && total > 0;
  // "1 in 3": whole numbers of a small total get a grid that is an exact multiple of the total.
  const ratio = based && total <= 20 && Number.isInteger(value) && Number.isInteger(total) && value <= total;
  const perT = ratio ? Math.max(1, Math.floor(40 / total)) : 0;
  const N = ratio ? total * perT : 40;
  const COLS = N % 10 === 0 ? 10 : ([12, 9, 8, 11, 13, 7].find((c) => N % c === 0) ?? 10);
  const ROWS = Math.ceil(N / COLS);
  // A bare count (no share) lights the whole street.
  const frac = clamp01(pct ? value / 100 : based ? value / total : 1);
  const lit = ratio ? Math.min(N, value * perT) : frac > 0 ? Math.max(1, Math.min(N, Math.round(frac * N))) : 0;
  const cg = 16 * k;
  const rg = (ROWS > 4 ? 22 : 30) * k;
  const hw = Math.min(76, (904 - (COLS - 1) * 16) / COLS) * k;
  const hh = hw * (60 / 64);
  const GW = COLS * hw + (COLS - 1) * cg;
  const GH = ROWS * hh + (ROWS - 1) * rg + 10 * k;
  const hs = hw / 64;
  const order = Array.from({ length: N }, (_, i) => i).sort((a, b) => rnd(a * 3.7 + 11) - rnd(b * 3.7 + 11));
  const rank: number[] = new Array<number>(N).fill(0);
  order.forEach((h, j) => { rank[h] = j; });
  const lightAt = T(0.8);
  const lightSpan = T(1.15);
  const off = ramp(frame, dur - 21, 7);
  const outStep = Math.min(0.45, 4 / Math.max(1, ROWS - 1 + COLS - 1));
  const word = splitUnit(suffix).word;
  const per = based ? total / N : pct ? 100 / N : 0;
  const legend = based && !ratio && per >= 2 ? `1 HOUSE ≈ ${fmt(round2(per))}${word ? ` ${word}` : ""}`
    : pct ? `1 HOUSE = ${fmt(per)}%` : "";
  const id = `ichouse${overlay.startFrame}`;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 84 * k }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 14 * k, width: 480 * k }}>
            <Kicker text={S(overlay.subtitle)} accent={accent} at={2} size={26} max={24} />
            {ratio ? (
              <div style={{ display: "flex", alignItems: "flex-end", gap: 20 * k }}>
                <MaskIO pin={ramp(frame, lightAt - 6, 14)} pout={exit}>
                  <Odometer value={value} at={lightAt} frames={lightSpan} size={168 * k} color={accent} />
                </MaskIO>
                <MaskIO pin={ramp(frame, lightAt, 14)} pout={exit} style={{ marginBottom: 20 * k }}>
                  <span style={{ display: "block", fontFamily: DISPLAY, fontSize: 80 * k, lineHeight: 1,
                    color: "rgba(255,255,255,.72)" }}>IN</span>
                </MaskIO>
                <MaskIO pin={ramp(frame, lightAt + 4, 14)} pout={exit}>
                  <Odometer value={total} at={lightAt + 4} frames={lightSpan} size={168 * k} color="#fff" />
                </MaskIO>
              </div>
            ) : (
              <Figure value={value} at={lightAt} frames={lightSpan} size={168 * k} accent={accent}
                prefix={S(overlay.prefix)} suffix={suffix} />
            )}
            {based && !ratio ? <Readout text={`OF ${big(total)}`} at={lightAt + 12} /> : null}
            <Caption text={S(overlay.text)} at={lightAt + 16} accent={accent} size={34} chars={24} />
            {legend ? <Readout text={legend} at={lightAt + 22} color={alpha(accent, 0.92)} /> : null}
          </div>
          <svg width={GW} height={GH} style={{ overflow: "visible", display: "block" }}>
            <defs>
              <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5">
                <stop offset="0" stopColor={accent} stopOpacity={0.5} />
                <stop offset="1" stopColor={accent} stopOpacity={0} />
              </radialGradient>
            </defs>
            {Array.from({ length: ROWS }, (_, r) => {
              const y = r * (hh + rg) + hh + 4 * k;
              const w = (GW + 28 * k) * ramp(frame, 2 + r * 3, 20, inOut) * (1 - exit);
              return <line key={`st${r}`} x1={-14 * k} x2={-14 * k + w} y1={y} y2={y} stroke="rgba(255,255,255,.16)"
                strokeWidth={2 * k} />;
            })}
            {Array.from({ length: N }, (_, i) => {
              const r = Math.floor(i / COLS);
              const c = i % COLS;
              const x = c * (hw + cg);
              const y = r * (hh + rg);
              const p = ramp(frame, 3 + (r + c) * 1.2, 12, backOut);
              const q = ramp(frame, dur - 15 + (r + c) * outStep, 9, expoIn);
              const on = rank[i] < lit;
              const tj = lightAt + (lit > 1 ? (rank[i] / (lit - 1)) * lightSpan : 0);
              const b = on ? interpolate(frame, [tj, tj + 2, tj + 3, tj + 6], [0, 1, 0.3, 1], clamp) * (1 - off) : 0;
              const sc = Math.max(0.001, (0.72 + 0.28 * p) * (1 - 0.35 * q));
              const dy = (1 - Math.min(1, p)) * 22 * k + q * 26 * k;
              const tr = `translate(${f1(x + hw / 2)} ${f1(y + hh + dy)}) scale(${sc.toFixed(3)}) ` +
                `translate(${f1(-hw / 2)} ${f1(-hh)}) scale(${hs.toFixed(4)})`;
              return (
                <g key={i} opacity={Math.min(1, p * 1.6) * (1 - q)}>
                  {b > 0.02 ? <circle cx={x + hw / 2} cy={y + hh * 0.6} r={hw * 0.85} fill={`url(#${id}g)`}
                    opacity={b * 0.8} /> : null}
                  <g transform={tr}>
                    {b > 0.02 ? <path d={HOUSE_BODY} fill={accent} fillOpacity={0.16 * b} /> : null}
                    <path d={HOUSE_LIGHTS} fill={b > 0.02 ? accent : "rgba(255,255,255,.1)"}
                      fillOpacity={b > 0.02 ? 0.25 + 0.75 * b : 1} />
                    <path d={HOUSE_LINE} fill="none" stroke={on && b > 0.5 ? "#fff" : "rgba(255,255,255,.4)"}
                      strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
                  </g>
                </g>
              );
            })}
          </svg>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. traffic queue (tag, low left)
/** A sedan in a 120 x 48 box, facing left: body, side glass, tyres, hubs. */
const CAR_BODY = "M4 36 Q4 27 12 26 L27 24 L41 12 Q45 9 51 9 H79 Q85 9 89 13 L101 24 L110 25.5 Q117 27 117 33 V37 " +
  "Q117 40 114 40 H7 Q4 40 4 37 Z";
const CAR_GLASS = "M31 24 L43 13.5 Q46 11.5 50 11.5 H62 V24 Z M66 11.5 H78 Q83 11.5 86 14.5 L95 24 H66 Z";
const CAR_TYRES = "M19.5 40 a8.5 8.5 0 1 0 17 0 a8.5 8.5 0 1 0 -17 0 Z M85.5 40 a8.5 8.5 0 1 0 17 0 a8.5 8.5 0 1 0 -17 0 Z";
const CAR_HUBS = "M25 40 a3 3 0 1 0 6 0 a3 3 0 1 0 -6 0 Z M91 40 a3 3 0 1 0 6 0 a3 3 0 1 0 -6 0 Z";
const CAR_FRONT = ["#eef0f4", "#d3d6dc", "#aeb2bb"];
const CAR_BACK = ["#a9adb6", "#8f939d", "#767a84"];

/**
 * Low left on the footage: the count rolls above a short two-lane road whose
 * ends fade into the picture. Cars race in from the right with speed streaks
 * and brake into a queue at the stop line, each dipping its nose, flaring its
 * accent tail lamps and nudging the car ahead; once the queue is full it
 * creeps up a car-nose, lamps dimming and flaring again. Exit: the jam clears,
 * front cars first, out through the fade.
 */
const TrafficQueue: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  if (!Number.isFinite(value) || value < 0) return null;
  const id = `ictraffic${overlay.startFrame}`;
  const RW = 880 * k;
  const RH = 172 * k;
  const TRAVEL = Math.max(14, T(0.75));
  type Lane = { n: number; x0: number; gap: number; sc: number; base: number; at: number; step: number; tones: string[] };
  const lanes: Lane[] = [
    { n: 7, x0: 76 * k, gap: 94 * k, sc: 0.68 * k, base: 80 * k, at: T(0.3), step: Math.max(2, T(0.13)), tones: CAR_BACK },
    { n: 6, x0: 64 * k, gap: 118 * k, sc: 0.86 * k, base: 156 * k, at: T(0.18), step: Math.max(2, T(0.15)), tones: CAR_FRONT },
  ];
  const lastArrive = Math.max(...lanes.map((L) => L.at + (L.n - 1) * L.step)) + TRAVEL;
  const creepAt = lastArrive + T(0.55);
  const dash = ramp(frame, 0, 24, inOut) * (1 - exit);
  const cars: React.ReactNode[] = [];
  const streaks: React.ReactNode[] = [];
  lanes.forEach((L, li) => {
    const cw = 120 * L.sc;
    const arrive = (i: number): number => L.at + i * L.step;
    const stopOf = (i: number): number => arrive(i) + Math.round(TRAVEL * 0.5);
    const xAt = (i: number, f: number): number => {
      const slot = L.x0 + i * L.gap;
      const start = RW + 40 * k;
      let x = start + (slot - start) * ramp(f, arrive(i), TRAVEL);
      if (i < L.n - 1) {
        // The car behind stops: this one is nudged forward a touch.
        const s2 = stopOf(i + 1);
        x -= interpolate(f, [s2, s2 + 3, s2 + 12], [0, 1, 0], clamp) * 5 * k;
      }
      x -= ramp(f, creepAt + i * 3, 14, inOut) * 9 * k;
      const q = ramp(f, dur - 16 + i * 0.5, 12, expoIn);
      return x - q * (slot + cw + 60 * k);
    };
    for (let i = 0; i < L.n; i++) {
      const a = arrive(i);
      if (frame < a) continue;
      const x = xAt(i, frame);
      const v = Math.abs(x - xAt(i, frame - 1));
      const st = stopOf(i);
      const dip = interpolate(frame, [st - 2, st + 3, st + 14], [0, 1, 0], clamp);
      const cs = creepAt + i * 3;
      const b0 = interpolate(frame, [st - 6, st, st + 28], [0, 1, 0.45], clamp);
      const b1 = interpolate(frame, [cs, cs + 2, cs + 12, cs + 15, cs + 32], [0.45, 0.12, 0.12, 1, 0.45], clamp);
      const brake = (frame < cs ? b0 : b1) * (1 - exit);
      const top = L.base - 48 * L.sc;
      const tone = L.tones[Math.floor(rnd(li * 31 + i * 7 + 3) * L.tones.length) % L.tones.length];
      if (v > 4 * k) {
        const len = Math.min(240 * k, v * 2.4);
        const o = Math.min(0.6, v / (60 * k));
        [0.34, 0.66].forEach((t, j) => {
          const y = top + 44 * L.sc * t;
          streaks.push(
            <line key={`s${li}-${i}-${j}`} x1={x + cw + 6 * k} x2={x + cw + 6 * k + len * (j ? 0.7 : 1)} y1={y} y2={y}
              stroke="#fff" strokeOpacity={o} strokeWidth={2 * k} strokeLinecap="round" />,
          );
        });
      }
      cars.push(
        <g key={`c${li}-${i}`} transform={`translate(${f1(x)} ${f1(top)}) rotate(${(-2.2 * dip).toFixed(2)} ` +
          `${f1(cw * 0.2)} ${f1(48 * L.sc)}) scale(${L.sc.toFixed(4)})`}>
          {brake > 0.02 ? <circle cx={114.5} cy={30.5} r={9 + 9 * brake} fill={`url(#${id}l)`} opacity={brake} /> : null}
          <path d={CAR_BODY} fill={tone} />
          <path d={CAR_GLASS} fill="rgba(12,12,15,.82)" />
          <path d={CAR_TYRES} fill={INK} stroke="rgba(255,255,255,.8)" strokeWidth={2} />
          <path d={CAR_HUBS} fill="#b9bdc6" />
          <path d="M4.5 29 h5 v3.2 h-5 Z" fill="#fff" opacity={0.9} />
          <path d="M112 28.5 h5 v4 h-5 Z" fill={accent} opacity={0.35 + 0.65 * brake} />
        </g>,
      );
    }
  });
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={24} y={88} rx={60} ry={52} exit={exit} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 96 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start", gap: 10 * k }}>
        <Kicker text={S(overlay.subtitle)} accent={accent} at={2} />
        <div style={{ display: "flex", alignItems: "flex-end", gap: 28 * k }}>
          <Figure value={value} at={T(0.25)} frames={Math.max(20, lastArrive - T(0.25))} size={116 * k} accent={accent}
            prefix={S(overlay.prefix)} suffix={S(overlay.suffix)} />
          <div style={{ marginBottom: 12 * k, maxWidth: 440 * k }}>
            <Caption text={S(overlay.text)} at={T(0.7)} accent={accent} size={30} chars={26} />
          </div>
        </div>
        <svg width={RW} height={RH} style={{ display: "block", overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}f`} gradientUnits="userSpaceOnUse" x1={0} y1={0} x2={RW} y2={0}>
              <stop offset="0" stopColor="#fff" stopOpacity={0} />
              <stop offset="0.035" stopColor="#fff" stopOpacity={1} />
              <stop offset="0.88" stopColor="#fff" stopOpacity={1} />
              <stop offset="1" stopColor="#fff" stopOpacity={0} />
            </linearGradient>
            <mask id={`${id}m`} maskUnits="userSpaceOnUse" x={0} y={-30 * k} width={RW} height={RH + 60 * k}>
              <rect x={0} y={-30 * k} width={RW} height={RH + 60 * k} fill={`url(#${id}f)`} />
            </mask>
            <radialGradient id={`${id}l`} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor={accent} stopOpacity={0.85} />
              <stop offset="1" stopColor={accent} stopOpacity={0} />
            </radialGradient>
          </defs>
          <g mask={`url(#${id}m)`}>
            <rect x={0} y={24 * k} width={RW} height={140 * k} fill="rgba(14,15,20,.58)"
              opacity={ramp(frame, 0, 12) * (1 - exit)} />
            <line x1={0} x2={RW * dash} y1={24 * k} y2={24 * k} stroke="rgba(255,255,255,.62)" strokeWidth={2.5 * k} />
            <line x1={0} x2={RW * dash} y1={164 * k} y2={164 * k} stroke="rgba(255,255,255,.62)" strokeWidth={2.5 * k} />
            <line x1={0} x2={RW * dash} y1={92 * k} y2={92 * k} stroke="rgba(255,255,255,.42)" strokeWidth={2.5 * k}
              strokeDasharray={`${30 * k} ${22 * k}`} />
            <line x1={48 * k} x2={48 * k} y1={26 * k} y2={26 * k + 136 * k * ramp(frame, 6, 16, inOut) * (1 - exit)}
              stroke="#fff" strokeOpacity={0.85} strokeWidth={4 * k} />
            {streaks}
            {cars}
          </g>
        </svg>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. dollar pulse (tag, low left)
/** One heartbeat of an ECG trace over a unit width, y negative upward. */
const ECG: [number, number][] = [[0, 0], [0.16, 0], [0.21, -0.1], [0.26, 0], [0.32, 0], [0.35, 0.14], [0.39, -1],
  [0.43, 0.34], [0.47, 0], [0.57, 0], [0.65, -0.22], [0.73, 0], [1, 0]];

/**
 * Low left on the footage: a dark coin badge with the currency sign pops in,
 * its accent rim drawing round, then beats like a heart (a double thump, a
 * ring and a glow each beat); an ECG trace draws out under the amount and
 * every beat runs along it as an accent pulse while the money rolls.
 */
const DollarPulse: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  if (!Number.isFinite(value)) return null;
  const id = `icpulse${overlay.startFrame}`;
  const rawPrefix = S(overlay.prefix).trim();
  const prefix = rawPrefix || "$";
  const glyph = Array.from(rawPrefix).length === 1 ? rawPrefix : "$";
  const period = Math.round(fps * 1.05);
  const beatAt = T(0.4);
  const beating = frame >= beatAt;
  const ph = beating ? ((frame - beatAt) % period) / period : 0;
  const bump = (x: number, c: number, w: number): number => (x >= c && x <= c + w ? Math.sin(((x - c) / w) * Math.PI) : 0);
  const thump = beating ? bump(ph, 0, 0.13) + 0.6 * bump(ph, 0.19, 0.12) : 0;
  const pop = ramp(frame, 0, 16, backOut);
  const badge = Math.max(0.001, pop * (1 + 0.1 * thump) * (1 - 0.4 * exit));
  const rim = ramp(frame, 2, 18, inOut) * (1 - exit);
  const B = 150 * k;
  const TW = 540 * k;
  const TH = 76 * k;
  const base = 46 * k;
  const amp = 34 * k;
  const beats = 3;
  const pts: string[] = [];
  for (let b = 0; b < beats; b++) {
    for (const [x, y] of ECG) pts.push(`${f1((b + x) * (TW / beats))} ${f1(base + y * amp)}`);
  }
  const trace = `M${pts.join(" L")}`;
  const drawAt = T(0.25);
  const drawF = T(0.75);
  const draw = ramp(frame, drawAt, drawF, inOut) * (1 - exit);
  const running = frame >= drawAt + drawF && exit < 0.4;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={16} y={87} exit={exit} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 128 * k, display: "flex", alignItems: "center", gap: 30 * k }}>
        <svg width={B} height={B} viewBox="0 0 150 150" style={{ overflow: "visible", display: "block" }}>
          <defs>
            <radialGradient id={`${id}d`} cx="0.5" cy="0.36" r="0.64">
              <stop offset="0" stopColor="#2a2a31" />
              <stop offset="1" stopColor="#0d0d10" />
            </radialGradient>
            <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor={accent} stopOpacity={0.55} />
              <stop offset="1" stopColor={accent} stopOpacity={0} />
            </radialGradient>
          </defs>
          <circle cx={75} cy={75} r={118} fill={`url(#${id}g)`}
            opacity={(0.3 + 0.7 * thump) * Math.min(1, pop) * (1 - exit)} />
          {beating ? (
            <circle cx={75} cy={75} r={58 + 48 * ph} fill="none" stroke={accent} strokeWidth={2.6 * (1 - ph)}
              opacity={(1 - ph) * 0.8 * (1 - exit)} />
          ) : null}
          <g transform={`translate(75 75) scale(${badge.toFixed(4)}) translate(-75 -75)`}>
            <circle cx={75} cy={75} r={57} fill={`url(#${id}d)`} />
            <circle cx={75} cy={75} r={64} fill="none" stroke={accent} strokeWidth={4.5} pathLength={1} strokeDasharray="1"
              strokeDashoffset={1 - rim} transform="rotate(-90 75 75)" />
            <circle cx={75} cy={75} r={50} fill="none" stroke="rgba(255,255,255,.2)" strokeWidth={1.5} />
            <text x={75} y={105} textAnchor="middle" fontFamily={DISPLAY} fontSize={86} fill={accent}>{glyph}</text>
          </g>
        </svg>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 * k }}>
          <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.2)} />
          <Figure value={value} at={T(0.3)} frames={T(1.2)} size={118 * k} accent={accent} prefix={prefix}
            suffix={S(overlay.suffix)} />
          <svg width={TW} height={TH} style={{ overflow: "visible", display: "block" }}>
            <line x1={0} x2={TW * draw} y1={base} y2={base} stroke="rgba(255,255,255,.14)" strokeWidth={1.5 * k} />
            <path d={trace} fill="none" stroke="rgba(255,255,255,.82)" strokeWidth={2.6 * k} strokeLinejoin="round"
              strokeLinecap="round" pathLength={1} strokeDasharray="1" strokeDashoffset={1 - draw} />
            {running ? (
              <g>
                <path d={trace} fill="none" stroke={accent} strokeOpacity={0.3} strokeWidth={11 * k} strokeLinecap="round"
                  strokeLinejoin="round" pathLength={1} strokeDasharray="0.1 2" strokeDashoffset={0.1 - ph * 1.1} />
                <path d={trace} fill="none" stroke={accent} strokeWidth={4 * k} strokeLinecap="round" strokeLinejoin="round"
                  pathLength={1} strokeDasharray="0.07 2" strokeDashoffset={0.07 - ph * 1.07} />
              </g>
            ) : null}
          </svg>
          <Caption text={S(overlay.text)} at={T(0.65)} accent={accent} size={32} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. calendar tear (tag, low right)
const TIME_UNIT = /^(DAYS?|NIGHTS?|WEEKS?|MONTHS?|YEARS?|HOURS?)$/;

/** "48 DAYS" is also "about 7 weeks": the conversion shown under the words. */
const convert = (v: number, unit: string): string => {
  const u = unit.replace(/S$/, "");
  const one = (x: number): string => (Math.abs(x) >= 10 || Number.isInteger(x) ? String(Math.round(x)) : x.toFixed(1));
  if ((u === "DAY" || u === "NIGHT") && v >= 730) return `≈ ${one(v / 365.25)} YEARS`;
  if ((u === "DAY" || u === "NIGHT") && v >= 14) return `≈ ${one(v / 7)} WEEKS`;
  if (u === "HOUR" && v >= 48) return `≈ ${one(v / 24)} DAYS`;
  if (u === "WEEK" && v >= 9) return `≈ ${one((v * 7) / 30.44)} MONTHS`;
  if (u === "MONTH" && v >= 24) return `≈ ${one(v / 12)} YEARS`;
  return "";
};

/** The ragged strip a torn page leaves under the binding (a CSS polygon). */
const tornEdge = (seed: number): string => {
  const pts: string[] = ["0% 0%", "100% 0%"];
  const n = 22;
  for (let i = n; i >= 0; i--) pts.push(`${((i / n) * 100).toFixed(1)}% ${(30 + rnd(seed + i * 1.7) * 70).toFixed(1)}%`);
  return `polygon(${pts.join(", ")})`;
};

/**
 * Low right on the footage: a tear-off day pad rises in; its pages are ripped
 * off one after another (each peels from its corner, then blows off up and
 * away into the picture, turning in 3D), slow, fast, slow, the numbers
 * jumping like days flying by, until the count is left on top with an accent
 * underline. A ragged stub stays under the binding and the pad thins as pages
 * go. Beside it, what the days were, and the count in weeks or years.
 */
const CalendarTear: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  const rawUnit = cap(overlay.suffix);
  if (!Number.isFinite(value) || value < 0 || value >= 1e7) return null;
  if (rawUnit && !TIME_UNIT.test(rawUnit)) return null;
  const unit = rawUnit || (value === 1 ? "DAY" : "DAYS");
  const whole = Math.round(value);
  const J = Math.max(0, Math.min(11, whole - 1));
  const vals: number[] = [];
  for (let j = 0; j < J; j++) {
    let v = Math.round(1 + (whole - 1) * Math.pow(j / Math.max(1, J), 1.35));
    if (j > 0 && v <= vals[j - 1]) v = vals[j - 1] + 1;
    vals.push(v);
  }
  const D = 16;
  const tearAt = T(0.6);
  const span = Math.max(0, Math.min(T(1.45), dur - 30 - D - tearAt));
  const g = (u: number): number => u + 0.12 * Math.sin(2 * Math.PI * u);
  const tAt = (j: number): number => tearAt + (J > 1 ? g(j / (J - 1)) * span : 0);
  let started = 0;
  for (let j = 0; j < J; j++) if (frame >= tAt(j)) started = j + 1;
  const lastDone = J > 0 ? tAt(J - 1) + D : tearAt;
  const PW = 206 * k;
  const HH = 42 * k;
  const PH = 196 * k;
  const pin = ramp(frame, 0, 18);
  const flutter = 0.05 + 0.04 * Math.sin(frame / 9);
  const labelOf = (j: number): string => (j >= J ? fmt(value) : fmt(vals[j]));

  const page = (j: number, style: React.CSSProperties, curl: number): React.ReactNode => {
    const label = labelOf(j);
    const pageUnit = label === "1" ? unit.replace(/S$/, "") : unit;
    const fs = Math.min(124 * k, (PW * 0.82) / Math.max(1, label.length * 0.46));
    const bar = j >= J ? ramp(frame, lastDone - 4, 14) * (1 - exit) * 110 * k : 0;
    return (
      <div key={`p${j}`} style={{ position: "absolute", left: 0, top: HH, width: PW, height: PH,
        borderRadius: `0 0 ${12 * k}px ${12 * k}px`, overflow: "hidden", transformOrigin: "100% 0",
        background: "linear-gradient(180deg, #fbfaf6 0%, #f1eee6 70%, #e2ded3 100%)", display: "flex",
        flexDirection: "column", alignItems: "center", justifyContent: "center", ...style }}>
        <div style={{ position: "absolute", left: 12 * k, right: 12 * k, top: 10 * k,
          borderTop: `${2.5 * k}px dotted rgba(0,0,0,.2)` }} />
        <span style={{ fontFamily: DISPLAY, fontSize: fs, lineHeight: 0.9, color: "#15151a", marginTop: 16 * k }}>{label}</span>
        <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.3em",
          color: "rgba(21,21,26,.55)", marginRight: -0.3 * 24 * k }}>{pageUnit}</span>
        <div style={{ width: bar, height: 5 * k, background: accent, marginTop: 10 * k }} />
        {curl > 0 ? (
          <div style={{ position: "absolute", inset: 0, opacity: curl,
            background: "linear-gradient(135deg, rgba(0,0,0,0) 50%, rgba(0,0,0,.18) 100%)" }} />
        ) : null}
      </div>
    );
  };

  // Pages in flight, the latest torn underneath the earlier ones.
  const flying: React.ReactNode[] = [];
  for (let j = J - 1; j >= 0; j--) {
    const p = (frame - tAt(j)) / D;
    if (p < 0 || p >= 1) continue;
    const u = clamp01(p / 0.3);
    const v = clamp01((p - 0.2) / 0.8);
    const tx = -v * 400 * k;
    const ty = (-v * 250 + v * v * 170 + u * 6) * k;
    flying.push(page(j, {
      transform: `translate(${tx.toFixed(1)}px, ${ty.toFixed(1)}px) rotate(${(10 * u + 26 * v).toFixed(2)}deg) ` +
        `rotateY(${(-50 * v).toFixed(2)}deg)`,
      opacity: 1 - clamp01((v - 0.62) / 0.38),
      boxShadow: `0 ${(20 * k * (u + v)).toFixed(1)}px ${50 * k}px rgba(0,0,0,${(0.22 + 0.2 * u).toFixed(2)})`,
    }, u));
  }
  const stack = Math.max(0, Math.min(3, J - started));
  const conv = convert(value, unit);
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={82} y={87} exit={exit} />
      <div style={{ position: "absolute", right: 110 * k, bottom: 118 * k, display: "flex", alignItems: "center", gap: 40 * k }}>
        <div style={{ position: "relative", width: PW, height: HH + PH + 16 * k, perspective: 1200 * k, flexShrink: 0,
          opacity: Math.min(1, pin * 2) * (1 - exit),
          transform: `translateY(${(((1 - pin) * 60 + exit * 40 + Math.sin(frame / 40) * 2) * k).toFixed(2)}px) ` +
            `rotate(${((1 - pin) * -4).toFixed(2)}deg) scale(${(1 - 0.08 * exit).toFixed(4)})` }}>
          {Array.from({ length: stack }, (_, i) => (
            <div key={`u${i}`} style={{ position: "absolute", left: 0, top: HH + (stack - i) * 4 * k, width: PW, height: PH,
              borderRadius: `0 0 ${12 * k}px ${12 * k}px`, background: i === 0 ? "#cfcbc1" : "#dcd8ce",
              boxShadow: "0 10px 30px rgba(0,0,0,.35)" }} />
          ))}
          {page(Math.min(started, J), { boxShadow: stack ? "none" : "0 10px 30px rgba(0,0,0,.35)" }, flutter)}
          {frame >= tAt(0) + 3 && J > 0 ? (
            <div style={{ position: "absolute", left: 0, top: HH, width: PW, height: 16 * k, background: "#f4f1ea",
              clipPath: tornEdge(3) }} />
          ) : null}
          <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: HH, borderRadius: `${12 * k}px ${12 * k}px 0 0`,
            background: "linear-gradient(180deg, #26262d 0%, #131317 100%)", boxShadow: "0 8px 24px rgba(0,0,0,.35)" }}>
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 6 * k, background: accent }} />
            {[0.26, 0.74].map((x) => (
              <div key={x} style={{ position: "absolute", left: PW * x - 13 * k, top: -11 * k, width: 26 * k, height: 26 * k,
                borderRadius: "50%", border: `${4.5 * k}px solid #cfd2d8`, background: INK, boxSizing: "border-box" }} />
            ))}
          </div>
          {flying}
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 * k, maxWidth: 540 * k }}>
          <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.15)} />
          <Lines text={cap(overlay.text)} chars={17} max={3} at={T(0.3)} style={{ fontFamily: DISPLAY, fontSize: 56 * k,
            lineHeight: 1, color: "#fff", letterSpacing: "0.03em", textShadow: "0 6px 26px rgba(0,0,0,.55)" }} />
          {conv ? <Readout text={conv} at={Math.round(lastDone) - 2} color={alpha(accent, 0.95)} /> : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 6. hourglass (tag, low right)
/** An hourglass glass in a 120 x 200 box: two bulbs meeting at the neck (y 100). */
const GLASS = "M28 20 H92 C92 58 64 84 63 100 C64 116 92 142 92 180 H28 C28 142 56 116 57 100 C56 84 28 58 28 20 Z";

/**
 * Low right on the footage: an hourglass pops in upside down and flips over
 * with an overshoot; its sand then runs for the whole hold (a funnel dip in
 * the top, a falling stream of grains, a mound growing below) beside the time
 * figure. With no figure it carries the words alone. Exit: it tips away and
 * shrinks while the words drop out.
 */
const Hourglass: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  const hasValue = Number.isFinite(value);
  const text = S(overlay.text);
  if (!hasValue && !cap(text)) return null;
  const id = `ichour${overlay.startFrame}`;
  const H = 236 * k;
  const W = H * 0.6;
  const pop = ramp(frame, 0, 12, backOut);
  const flipF = Math.max(12, T(0.75));
  const flip = ramp(frame, 3, flipF, backOut);
  const rot = 180 * (1 - flip) + 150 * exit;
  const sc = Math.max(0.001, (0.6 + 0.4 * Math.min(1.2, pop)) * (1 - 0.45 * exit));
  const flowAt = 3 + flipF;
  const sand = interpolate(frame, [flowAt, Math.max(flowAt + 1, dur - 16)], [0, 0.86], clamp);
  const flowing = frame >= flowAt && exit < 0.05;
  const topY = 30 + 68 * sand;
  const dipY = Math.min(100, topY + 4 + 10 * Math.min(1, sand * 3));
  const mound = 44 * Math.pow(sand, 0.8);
  const edge = mound * 0.3;
  const mid = 180 - edge - (mound - edge) * 0.5;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={84} y={86} exit={exit} />
      <div style={{ position: "absolute", right: 110 * k, bottom: 130 * k, display: "flex", alignItems: "center", gap: 36 * k }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 * k, maxWidth: 620 * k }}>
          <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.25)} align="right" />
          {hasValue ? (
            <>
              <Figure value={value} at={T(0.45)} frames={T(1.1)} size={124 * k} accent={accent}
                prefix={S(overlay.prefix)} suffix={S(overlay.suffix)} align="right" />
              <Caption text={text} at={T(0.8)} accent={accent} align="right" size={32} />
            </>
          ) : (
            <Lines text={cap(text)} chars={18} max={3} at={T(0.3)} align="right" style={{ fontFamily: DISPLAY,
              fontSize: 62 * k, lineHeight: 1, color: "#fff", letterSpacing: "0.03em",
              textShadow: "0 6px 26px rgba(0,0,0,.55)" }} />
          )}
        </div>
        <svg width={W} height={H} viewBox="0 0 120 200" style={{ overflow: "visible", display: "block" }}>
          <defs>
            <clipPath id={`${id}c`}><path d={GLASS} /></clipPath>
            <linearGradient id={`${id}m`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#f3f3f6" />
              <stop offset="1" stopColor="#a4a8b1" />
            </linearGradient>
            <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor={accent} stopOpacity={0.4} />
              <stop offset="1" stopColor={accent} stopOpacity={0} />
            </radialGradient>
          </defs>
          <g transform={`translate(60 100) rotate(${rot.toFixed(2)}) scale(${sc.toFixed(4)}) translate(-60 -100)`}
            opacity={Math.min(1, pop * 2) * (1 - exit)}>
            <circle cx={60} cy={100} r={100} fill={`url(#${id}g)`} />
            <path d={GLASS} fill="rgba(8,10,14,.3)" />
            <g clipPath={`url(#${id}c)`}>
              <path d={`M0 ${f1(topY)} L38 ${f1(topY)} L60 ${f1(dipY)} L82 ${f1(topY)} L120 ${f1(topY)} L120 100 L0 100 Z`}
                fill={accent} />
              <path d={`M20 ${f1(topY)} L38 ${f1(topY)} L60 ${f1(dipY)} L82 ${f1(topY)} L100 ${f1(topY)}`} fill="none"
                stroke="#fff" strokeOpacity={0.35} strokeWidth={1.2} />
              {mound > 0.5 ? (
                <path d={`M0 180 L0 ${f1(180 - edge)} Q30 ${f1(mid)} 60 ${f1(180 - mound)} Q90 ${f1(mid)} 120 ${f1(180 - edge)} L120 180 Z`}
                  fill={accent} />
              ) : null}
              {flowing ? (
                <g>
                  <line x1={60} x2={60} y1={dipY - 1} y2={180 - mound} stroke={accent} strokeWidth={1.8} />
                  <line x1={60} x2={60} y1={dipY - 1} y2={180 - mound} stroke="#fff" strokeOpacity={0.55} strokeWidth={1.1}
                    strokeDasharray="1.5 5" strokeDashoffset={-frame * 2.2} />
                </g>
              ) : null}
            </g>
            <path d="M36 30 C36 52 46 70 54 84" fill="none" stroke="#fff" strokeOpacity={0.35} strokeWidth={3}
              strokeLinecap="round" />
            <path d={GLASS} fill="none" stroke="rgba(255,255,255,.9)" strokeWidth={2.2} strokeLinejoin="round" />
            <rect x={16} y={20} width={5} height={160} rx={2} fill="rgba(255,255,255,.55)" />
            <rect x={99} y={20} width={5} height={160} rx={2} fill="rgba(255,255,255,.55)" />
            <rect x={10} y={6} width={100} height={14} rx={4} fill={`url(#${id}m)`} />
            <rect x={10} y={180} width={100} height={14} rx={4} fill={`url(#${id}m)`} />
            <rect x={10} y={16.6} width={100} height={2.4} fill={accent} />
            <rect x={10} y={181} width={100} height={2.4} fill={accent} />
          </g>
        </svg>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 7. power bolt (tag, low left)
/** A lightning bolt in a 120 x 200 box, the tip at the bottom. */
const BOLT = "M74 4 L20 112 H58 L42 196 L104 80 H66 L88 4 Z";
const BOLT_TOP = 4;
const BOLT_BOT = 196;
/** The bolt's spine: its x at height y, where the arcs leave from. */
const boltX = (y: number): number => (y < 96 ? 81 - ((y - 4) / 92) * 19 : 62 - ((y - 96) / 100) * 20);

/** A jagged electric arc from (x0, y0) to (x1, y1): `n` kinks jittered by a seed (a new shape every other frame). */
const arcPath = (x0: number, y0: number, x1: number, y1: number, seed: number, n = 5, jag = 7): string => {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  let d = `M${f1(x0)} ${f1(y0)}`;
  for (let i = 1; i < n; i++) {
    const t = i / n;
    const o = (rnd(seed + i * 3.1) - 0.5) * 2 * jag;
    d += ` L${f1(x0 + dx * t + nx * o)} ${f1(y0 + dy * t + ny * o)}`;
  }
  return `${d} L${f1(x1)} ${f1(y1)}`;
};

/**
 * Low left on the footage, a compact power readout: a lightning-bolt icon
 * draws on beside the figure and charges up from its tip (an accent fill with
 * a bright front, crackling arcs jumping off it) while the power figure rolls;
 * when full it flashes white, throws a ring and a burst of rays, then hums: a
 * glow breathing, a band of current running up it, an arc now and then.
 * Exit: the charge drains, the outline undraws, the words drop out.
 */
const PowerBolt: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  if (!Number.isFinite(value)) return null;
  const id = `icbolt${overlay.startFrame}`;
  const H = 156 * k;
  const W = H * 0.6;
  const pop = ramp(frame, 0, 14, backOut);
  const draw = ramp(frame, 0, 16, inOut) * (1 - exit);
  const chargeAt = T(0.3);
  const chargeF = Math.max(12, T(1.25));
  const fullAt = chargeAt + chargeF;
  const charge = ramp(frame, chargeAt, chargeF, inOut);
  const level = charge * (1 - exit);
  const frontY = BOLT_BOT - level * (BOLT_BOT - BOLT_TOP);
  const charging = charge > 0.02 && charge < 0.985 && exit === 0;
  const flash = interpolate(frame, [fullAt, fullAt + 2, fullAt + 12], [0, 1, 0], clamp);
  const ring = frame >= fullAt ? clamp01((frame - fullAt) / 20) : 0;
  const hum = frame >= fullAt ? 0.5 + 0.5 * Math.sin((frame - fullAt) * 0.2) : 0;
  const seed = Math.floor(frame / 2) * 17;
  const arcs: { key: string; d: string }[] = [];
  if (charging) {
    const cx = boltX(frontY);
    [0, 1].forEach((j) => {
      if ((Math.floor(frame / 2) + j) % 3 === 0) return;
      const dir = j === 0 ? -1 : 1;
      arcs.push({ key: `c${j}`, d: arcPath(cx + dir * 10, frontY, cx + dir * (36 + rnd(seed + j) * 16),
        frontY + (rnd(seed + j + 5) - 0.5) * 34, seed + j * 7) });
    });
  }
  const per = Math.max(8, Math.round(fps * 0.85));
  const since = frame - fullAt - 16;
  if (since >= 0 && since % per < 4 && exit < 0.05) {
    const j = Math.floor(since / per);
    const y = 30 + rnd(j * 3.3 + 1) * 140;
    const cx = boltX(y);
    const dir = rnd(j * 5.1 + 2) > 0.5 ? 1 : -1;
    arcs.push({ key: `h${j}`, d: arcPath(cx + dir * 10, y, cx + dir * (40 + rnd(j + 9) * 14), y - 18 + rnd(j + 4) * 36,
      seed + 91) });
  }
  // A band of current running up the full bolt while it holds.
  const cyc = Math.max(10, Math.round(fps * 1.3));
  const cur = frame > fullAt + 12 && exit < 0.05 ? ((frame - fullAt - 12) % cyc) / cyc : -1;
  const sc = Math.max(0.001, Math.min(1.15, pop) * (1 - 0.3 * exit));
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={14} y={88} exit={exit} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 122 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start", gap: 12 * k }}>
        <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.15)} />
        <div style={{ display: "flex", alignItems: "center", gap: 26 * k }}>
          <svg width={W} height={H} viewBox="0 0 120 200" style={{ overflow: "visible", display: "block" }}>
            <defs>
              <clipPath id={`${id}c`}><path d={BOLT} /></clipPath>
              <linearGradient id={`${id}f`} x1="0" y1="1" x2="0" y2="0">
                <stop offset="0" stopColor={accent} />
                <stop offset="0.75" stopColor={accent} />
                <stop offset="1" stopColor="#fff6d8" />
              </linearGradient>
              <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5">
                <stop offset="0" stopColor={accent} stopOpacity={0.55} />
                <stop offset="1" stopColor={accent} stopOpacity={0} />
              </radialGradient>
            </defs>
            <g transform={`translate(60 100) scale(${sc.toFixed(4)}) translate(-60 -100)`}>
              <circle cx={60} cy={100} r={108} fill={`url(#${id}g)`}
                opacity={(0.18 + 0.4 * level + 0.35 * flash + 0.12 * hum) * Math.min(1, pop) * (1 - exit)} />
              {ring > 0 && ring < 1 ? (
                <circle cx={60} cy={100} r={70 + 80 * ring} fill="none" stroke={accent} strokeWidth={3 * (1 - ring)}
                  opacity={(1 - ring) * 0.9} />
              ) : null}
              {ring > 0 && ring < 1 ? [0, 1, 2, 3, 4, 5, 6, 7].map((i) => {
                const a = ((i * 45 + 22.5) * Math.PI) / 180;
                const r0 = 64 + 30 * ring;
                const r1 = 78 + 50 * ring;
                return <line key={`r${i}`} x1={60 + Math.cos(a) * r0} y1={100 + Math.sin(a) * r0}
                  x2={60 + Math.cos(a) * r1} y2={100 + Math.sin(a) * r1} stroke="#fff" strokeWidth={2.4}
                  strokeLinecap="round" opacity={1 - ring} />;
              }) : null}
              <path d={BOLT} fill="rgba(8,10,14,.45)" opacity={Math.min(1, pop)} />
              <g clipPath={`url(#${id}c)`}>
                {level > 0.002 ? (
                  <rect x={0} y={frontY} width={120} height={BOLT_BOT - frontY + 6} fill={`url(#${id}f)`} />
                ) : null}
                {charging ? <line x1={0} x2={120} y1={frontY} y2={frontY} stroke="#fff" strokeWidth={2.2} /> : null}
                {cur >= 0 ? (
                  <rect x={0} y={BOLT_BOT - cur * (BOLT_BOT - BOLT_TOP + 30)} width={120} height={22} fill="#fff"
                    opacity={0.3 * Math.sin(cur * Math.PI)} />
                ) : null}
                {flash > 0.01 ? <rect x={0} y={0} width={120} height={200} fill="#fff" opacity={flash} /> : null}
              </g>
              <path d={BOLT} fill="none" stroke="#fff" strokeWidth={3.2} strokeLinejoin="round" pathLength={1}
                strokeDasharray="1" strokeDashoffset={1 - draw} />
              {arcs.map((a) => (
                <g key={a.key}>
                  <path d={a.d} fill="none" stroke={CYAN} strokeOpacity={0.4} strokeWidth={5} strokeLinecap="round"
                    strokeLinejoin="round" />
                  <path d={a.d} fill="none" stroke="#f2fbff" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
                </g>
              ))}
            </g>
          </svg>
          <Figure value={value} at={chargeAt} frames={chargeF} size={128 * k} accent={accent}
            prefix={S(overlay.prefix)} suffix={S(overlay.suffix)} />
        </div>
        <Caption text={S(overlay.text)} at={chargeAt + T(0.55)} accent={accent} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. fire flicker (tag, low left)
/** The flame's outer layer in a 120 x 160 box (base at y 154): three tongues, each swaying on its own sines. */
const outerFlame = (t: number): string => {
  const tx = 62 + 5 * Math.sin(t * 9.1) + 2.5 * Math.sin(t * 15.3);
  const ty = 8 + 5 * Math.sin(t * 11.7 + 1.1);
  const lx = 32 + 3 * Math.sin(t * 12.3 + 2);
  const ly = 52 + 6 * Math.sin(t * 8.3 + 0.4);
  const rx = 98 + 2.5 * Math.sin(t * 10.1 + 2.7);
  const ry = 44 + 6 * Math.sin(t * 13.9 + 0.9);
  const b = 2 * Math.sin(t * 7.3);
  return `M60 154 C${f1(28 - b)} 154 ${f1(14 - b)} 130 ${f1(17 - b)} 104 ` +
    `C20 84 ${f1(lx - 4)} ${f1(ly + 16)} ${f1(lx)} ${f1(ly)} ` +
    `C${f1(lx + 7)} ${f1(ly + 12)} 44 70 48 74 ` +
    `C46 52 ${f1(tx - 12)} ${f1(ty + 26)} ${f1(tx)} ${f1(ty)} ` +
    `C${f1(tx + 10)} ${f1(ty + 24)} 80 44 84 62 ` +
    `C${f1(rx - 6)} ${f1(ry + 12)} ${f1(rx - 2)} ${f1(ry + 2)} ${f1(rx)} ${f1(ry)} ` +
    `C${f1(108 + b)} 70 ${f1(108 + b)} 92 ${f1(104 + b)} 110 ` +
    `C${f1(100 + b)} 136 88 154 60 154 Z`;
};
/** The flame's middle layer: one tip and a small side tongue. */
const midFlame = (t: number): string => {
  const tx = 60 + 4 * Math.sin(t * 10.3 + 0.5);
  const ty = 46 + 5 * Math.sin(t * 12.9 + 2.2);
  const sx = 84 + 3 * Math.sin(t * 9.7 + 1.3);
  const sy = 78 + 5 * Math.sin(t * 11.1);
  return `M60 150 C38 150 30 134 32 118 C34 102 44 92 50 80 ` +
    `C52 70 ${f1(tx - 8)} ${f1(ty + 16)} ${f1(tx)} ${f1(ty)} ` +
    `C${f1(tx + 8)} ${f1(ty + 20)} 72 90 76 98 ` +
    `C${f1(sx - 3)} ${f1(sy + 8)} ${f1(sx)} ${f1(sy + 2)} ${f1(sx)} ${f1(sy)} ` +
    `C94 100 94 118 90 128 C86 142 76 150 60 150 Z`;
};
/** The white-hot core. */
const coreFlame = (t: number): string => {
  const tx = 60 + 3 * Math.sin(t * 13.1 + 1.7);
  const ty = 94 + 4 * Math.sin(t * 15.7);
  return `M60 148 C49 148 45 139 46 129 C47 119 ${f1(tx - 6)} ${f1(ty + 14)} ${f1(tx)} ${f1(ty)} ` +
    `C${f1(tx + 6)} ${f1(ty + 14)} 74 119 74 129 C74 140 70 148 60 148 Z`;
};

/**
 * Low left on the footage: a spark flashes on a ground line and a flame
 * springs up from it, three layers (red tongues, gold body, white core)
 * licking on their own rhythms while embers rise and sway off it and a warm
 * glow breathes behind. Beside it the area figure rolls, and a burn line runs
 * under it (charred red behind a bright spark head), then smoulders. Exit: the
 * flame sinks into the ground line, the words drop out.
 */
const FireFlicker: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  if (!Number.isFinite(value)) return null;
  const id = `icfire${overlay.startFrame}`;
  const H = 200 * k;
  const W = H * 0.75;
  const t = frame / fps;
  const igniteAt = T(0.12) + 4;
  const grow = ramp(frame, igniteAt, T(0.55), backOut);
  const size = Math.max(0.001, Math.min(1.12, grow) * (1 - exit));
  const flick = 0.5 + 0.5 * Math.sin(t * 17.3) * Math.sin(t * 7.1 + 0.8);
  const spark = interpolate(frame, [igniteAt - 4, igniteAt, igniteAt + 8], [0, 1, 0], clamp);
  const ground = ramp(frame, 0, 14, inOut) * (1 - exit);
  const embers: React.ReactNode[] = [];
  if (frame >= igniteAt + 4 && exit < 0.6) {
    for (let i = 0; i < 9; i++) {
      const life = Math.round(fps * (1.1 + rnd(i + 3) * 0.9));
      const off = Math.round(rnd(i + 17) * life);
      const age = ((frame - igniteAt - 4 + off) % life) / life;
      const x = 60 + (rnd(i + 29) - 0.5) * 56 + Math.sin(age * 6 + i) * 9 * age;
      const y = 70 - age * (110 + rnd(i + 41) * 70);
      const r = (1.3 + rnd(i + 53) * 1.9) * (1 - age * 0.6);
      const o = (age < 0.12 ? age / 0.12 : 1 - (age - 0.12) / 0.88) * Math.min(1, grow) * (1 - exit);
      embers.push(<circle key={`e${i}`} cx={x} cy={y} r={r} fill={i % 3 === 0 ? "#fff3cf" : FLAME} opacity={o} />);
    }
  }
  const LW = 380 * k;
  const burnAt = T(0.35);
  const burnF = Math.max(12, T(1.4));
  const bp = ramp(frame, burnAt, burnF, inOut);
  const burning = bp > 0.005 && bp < 0.995 && exit === 0;
  const smoulder = 0.78 + 0.22 * Math.sin(t * 9.3) * Math.sin(t * 5.1);
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={15} y={87} exit={exit} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 112 * k, display: "flex", alignItems: "flex-end", gap: 30 * k }}>
        <svg width={W} height={H} viewBox="0 0 120 160" style={{ overflow: "visible", display: "block" }}>
          <defs>
            <linearGradient id={`${id}o`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0.1" stopColor={RED} />
              <stop offset="1" stopColor={FLAME} />
            </linearGradient>
            <linearGradient id={`${id}m`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={FLAME} />
              <stop offset="1" stopColor="#ffe3a0" />
            </linearGradient>
            <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor={FLAME} stopOpacity={0.5} />
              <stop offset="1" stopColor={RED} stopOpacity={0} />
            </radialGradient>
          </defs>
          <ellipse cx={60} cy={102} rx={92} ry={110} fill={`url(#${id}g)`}
            opacity={(0.45 + 0.3 * flick) * Math.min(1, grow) * (1 - exit)} />
          {spark > 0.01 ? <circle cx={60} cy={150} r={8 + 14 * spark} fill="#fff6dc" opacity={spark} /> : null}
          <g transform={`translate(60 154) scale(${size.toFixed(4)}) translate(-60 -154)`}>
            <path d={outerFlame(t)} fill={`url(#${id}o)`} />
            <path d={midFlame(t)} fill={`url(#${id}m)`} />
            <path d={coreFlame(t)} fill="#fff6dc" opacity={0.92} />
          </g>
          <line x1={60 - 46 * ground} x2={60 + 46 * ground} y1={156} y2={156} stroke="#fff" strokeOpacity={0.7}
            strokeWidth={2.6} strokeLinecap="round" />
          {embers}
        </svg>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 * k, maxWidth: 640 * k,
          marginBottom: 4 * k }}>
          <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.15)} />
          <Figure value={value} at={burnAt} frames={burnF} size={120 * k} accent={accent}
            prefix={S(overlay.prefix)} suffix={S(overlay.suffix)} />
          <svg width={LW} height={24 * k} style={{ display: "block", overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}b`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor={RED} stopOpacity={0.35} />
                <stop offset="0.8" stopColor={RED} />
                <stop offset="1" stopColor={FLAME} />
              </linearGradient>
            </defs>
            <line x1={0} x2={LW * ramp(frame, 4, 16, inOut) * (1 - exit)} y1={12 * k} y2={12 * k}
              stroke="rgba(255,255,255,.24)" strokeWidth={3 * k} />
            {bp > 0.005 ? (
              <rect x={0} y={10.5 * k} width={Math.max(0.5, LW * bp * (1 - exit))} height={3 * k} fill={`url(#${id}b)`}
                opacity={burning ? 1 : smoulder} />
            ) : null}
            {burning ? (
              <g>
                <circle cx={LW * bp} cy={12 * k} r={12 * k} fill={`url(#${id}g)`} />
                <circle cx={LW * bp} cy={12 * k} r={3.4 * k} fill="#fff6dc" />
              </g>
            ) : null}
          </svg>
          <Caption text={S(overlay.text)} at={burnAt + T(0.5)} accent={accent} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 9. crowd swell (tag, low right)
/** A person's bust in a 20 x 30 box (the head is a circle at 10, 8.5). */
const BUST = "M1 30 C1 21 4.5 16.5 10 16.5 C15.5 16.5 19 21 19 30 Z";
/** Back row to front row: smaller and dimmer behind, the front row nearly white. */
const CROWD_ROWS = [
  { n: 14, sc: 0.74, base: 66, tone: "#9aa0a8" },
  { n: 13, sc: 0.83, base: 90, tone: "#b9bec5" },
  { n: 12, sc: 0.92, base: 116, tone: "#dcdfe3" },
  { n: 11, sc: 1.0, base: 144, tone: "#ffffff" },
];

/**
 * Low right on the footage: the head count rolls while a crowd of fifty
 * people pictograms gathers under it, front-centre first and spreading
 * outward and back row by row, each figure popping up with an accent flash;
 * then the crowd shifts on its feet. Fewer than fifty people are drawn one
 * figure each; more get a legend of what one figure stands for. Exit: the
 * crowd thins from the edges in, the words drop out.
 */
const CrowdSwell: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  if (!Number.isFinite(value) || value < 0) return null;
  const suffix = S(overlay.suffix).trim();
  const pct = suffix === "%";
  const unit = splitUnit(suffix);
  const mult = MULT[unit.short.toUpperCase()];
  const count = pct ? value : value * (typeof mult === "number" ? mult : 1);
  const CW = 500 * k;
  const CH = 146 * k;
  const U = 1.8 * k;
  type Person = { x: number; base: number; sc: number; row: number; tone: string; rank: number };
  const people: Person[] = [];
  CROWD_ROWS.forEach((R, r) => {
    const sp = CW / R.n;
    for (let c = 0; c < R.n; c++) {
      const x = (c + 0.5) * sp + (r % 2 ? 0.12 : -0.12) * sp + (rnd(r * 17 + c * 3.3) - 0.5) * 6 * k;
      people.push({ x, base: R.base * k, sc: R.sc, row: r, tone: R.tone, rank: 0 });
    }
  });
  const n = people.length;
  // The swell: front-centre first, spreading outward and back.
  const keyOf = people.map((p, i) => (Math.abs(p.x - CW / 2) / (CW / 2)) * 0.8 + (3 - p.row) * 0.14 + rnd(i * 2.1 + 5) * 0.12);
  people.map((_, i) => i).sort((a, b) => keyOf[a] - keyOf[b]).forEach((pi, j) => { people[pi].rank = j; });
  const shown = pct ? Math.round(clamp01(value / 100) * n)
    : count >= n ? n : Math.max(count > 0 ? 1 : 0, Math.round(count));
  const swellAt = T(0.3);
  const swellF = Math.max(12, T(1.35));
  const outStep = 4 / Math.max(1, shown - 1);
  const word = unit.word || "PEOPLE";
  const perFig = !pct && count > n ? round2(count / n) : 0;
  const legend = pct ? `EACH FIGURE = ${fmt(100 / n)}%` : perFig >= 2 ? `EACH FIGURE ≈ ${big(perFig)} ${word}` : "";
  const groundW = ramp(frame, 2, 18, inOut) * (1 - exit);
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={80} y={86} rx={50} ry={54} exit={exit} />
      <div style={{ position: "absolute", right: 110 * k, bottom: 104 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 8 * k }}>
        <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.1)} align="right" />
        <div style={{ display: "flex", alignItems: "flex-end", gap: 26 * k }}>
          <div style={{ marginBottom: 12 * k, maxWidth: 400 * k }}>
            <Caption text={S(overlay.text)} at={swellAt + T(0.5)} accent={accent} align="right" size={30} chars={24} />
          </div>
          <Figure value={value} at={swellAt} frames={swellF} size={150 * k} accent={accent} prefix={S(overlay.prefix)}
            suffix={suffix} align="right" />
        </div>
        <svg width={CW} height={CH} style={{ display: "block", overflow: "visible" }}>
          <line x1={CW - CW * groundW} x2={CW} y1={CH - k} y2={CH - k} stroke="rgba(255,255,255,.35)" strokeWidth={2 * k} />
          {people.map((P, i) => {
            if (P.rank >= shown) return null;
            const at = swellAt + (shown > 1 ? (P.rank / (shown - 1)) * swellF : 0);
            const p = ramp(frame, at, 12, backOut);
            if (p <= 0.001) return null;
            const fl = interpolate(frame, [at, at + 3, at + 12], [0, 1, 0], clamp);
            const q = ramp(frame, dur - 16 + (shown - 1 - P.rank) * outStep, 10, expoIn);
            if (q >= 0.999) return null;
            const sz = U * P.sc * Math.max(0.001, Math.min(1.15, p) * (1 - 0.6 * q));
            const bob = Math.sin(frame * 0.11 + i * 1.9) * 1.2 * k;
            const lift = (1 - Math.min(1, p)) * 10 * k + q * 8 * k;
            const col = fl > 0.3 ? accent : P.tone;
            return (
              <g key={i} opacity={1 - q}
                transform={`translate(${f1(P.x - 10 * sz)} ${f1(P.base - 30 * sz + bob + lift)}) scale(${sz.toFixed(4)})`}>
                {/* a black outline under each figure, so the crowd reads on bright footage */}
                <circle cx={10} cy={8.5} r={5.6} fill="#000" stroke="#000" strokeWidth={2.6} />
                <path d={BUST} fill="#000" stroke="#000" strokeWidth={2.6} strokeLinejoin="round" />
                <circle cx={10} cy={8.5} r={5.6} fill={col} />
                <path d={BUST} fill={col} />
              </g>
            );
          })}
        </svg>
        {legend ? <Readout text={legend} at={swellAt + T(0.9)} color={alpha(accent, 0.92)} /> : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. factory smoke (tag, low right)
/** A factory in a 260 x 190 box on a ground line at y 182: a sawtooth roof over a long hall. */
const FACTORY = "M14 182 V112 L56 88 V112 L98 88 V112 L140 88 V112 H246 V182 Z";
const CHIMNEYS: { x: number; w: number; top: number }[] = [{ x: 164, w: 22, top: 30 }, { x: 206, w: 18, top: 56 }];

/**
 * Low right on the footage: a ground line draws, a factory (line icon) rises
 * out of it, its chimneys pop up after, its windows flicker on in the accent
 * one by one, then the chimneys puff soft smoke that swells, rises and drifts
 * off to the left into the picture, while the emission figure rolls beside
 * it. Exit: the smoke thins, the factory sinks back into the ground line.
 */
const FactorySmoke: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const exit = useExit();
  const fin = useFin();
  const value = num(overlay.value);
  if (!Number.isFinite(value)) return null;
  const id = `icsmoke${overlay.startFrame}`;
  const FW = 250 * k;
  const s = FW / 260;
  const ground = ramp(frame, 0, 16, inOut) * (1 - exit);
  const rise = ramp(frame, 4, T(0.55)) * (1 - exit);
  const winAt = T(0.55);
  const smokeAt = T(0.7);
  const env = ramp(frame, smokeAt, 12) * (1 - exit);
  const puffs: React.ReactNode[] = [];
  CHIMNEYS.forEach((C, ci) => {
    const life = Math.round(fps * (ci ? 2.1 : 2.5));
    const NP = 7;
    const cx = C.x + C.w / 2;
    for (let j = 0; j < NP; j++) {
      const born = smokeAt + ci * 5 + (j * life) / NP;
      if (frame < born) continue;
      const age = ((frame - born) % life) / life;
      const x = cx - age * 64 - age * age * 44 + Math.sin(age * 5 + j * 1.3 + ci) * 5;
      const y = C.top - 4 - age * (ci ? 140 : 168);
      const r = (ci ? 8 : 10) + age * (ci ? 26 : 34);
      const o = Math.min(1, age / 0.12) * Math.pow(1 - age, 1.4) * 0.8 * env;
      if (o < 0.01) continue;
      puffs.push(<circle key={`p${ci}-${j}`} cx={x} cy={y} r={r} fill={`url(#${id}s)`} opacity={o} />);
    }
  });
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Shade ov={overlay} x={80} y={87} rx={52} ry={54} exit={exit} />
      <div style={{ position: "absolute", right: 110 * k, bottom: 112 * k, display: "flex", alignItems: "flex-end", gap: 34 * k }}>
        <svg width={FW} height={190 * s} viewBox="0 0 260 190" style={{ overflow: "visible", display: "block" }}>
          <defs>
            <radialGradient id={`${id}s`} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor="#e6e7ec" stopOpacity={0.85} />
              <stop offset="0.6" stopColor="#c9cbd2" stopOpacity={0.42} />
              <stop offset="1" stopColor="#b8bac2" stopOpacity={0} />
            </radialGradient>
            <clipPath id={`${id}c`}><rect x={-60} y={-400} width={380} height={582} /></clipPath>
          </defs>
          {puffs}
          <g clipPath={`url(#${id}c)`}>
            <g transform={`translate(0 ${f1((1 - rise) * 110)})`}>
              {CHIMNEYS.map((C, i) => {
                const cp = ramp(frame, 8 + i * 3, T(0.5), backOut);
                return (
                  <g key={`ch${i}`} opacity={Math.min(1, cp * 3)} transform={`translate(0 ${f1((1 - Math.min(1.1, cp)) * 90)})`}>
                    <rect x={C.x} y={C.top} width={C.w} height={114 - C.top} fill="rgba(12,12,15,.78)" stroke="#fff"
                      strokeWidth={2.4} strokeLinejoin="round" />
                    <rect x={C.x + 1.2} y={C.top + 8} width={C.w - 2.4} height={5} fill={accent} />
                  </g>
                );
              })}
              <path d={FACTORY} fill="rgba(12,12,15,.8)" stroke="#fff" strokeWidth={2.6} strokeLinejoin="round" />
              {Array.from({ length: 8 }, (_, j) => {
                const la = winAt + j * 2;
                const b = interpolate(frame, [la, la + 2, la + 3, la + 5], [0, 1, 0.4, 1], clamp) * (1 - exit);
                const glow = 0.86 + 0.14 * Math.sin(frame * 0.27 + j * 2.1);
                return <rect key={`w${j}`} x={26 + j * 27.5} y={138} width={14} height={18} rx={1.5}
                  fill={b > 0.02 ? accent : "rgba(255,255,255,.12)"} fillOpacity={b > 0.02 ? (0.2 + 0.8 * b) * glow : 1} />;
              })}
            </g>
          </g>
          <line x1={130 - 136 * ground} x2={130 + 136 * ground} y1={182} y2={182} stroke="#fff" strokeWidth={2.6}
            strokeLinecap="round" />
        </svg>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 * k, maxWidth: 560 * k,
          marginBottom: 6 * k }}>
          <Kicker text={S(overlay.subtitle)} accent={accent} at={T(0.2)} />
          <Figure value={value} at={T(0.5)} frames={T(1.3)} size={120 * k} accent={accent} prefix={S(overlay.prefix)}
            suffix={S(overlay.suffix)} />
          <Caption text={S(overlay.text)} at={T(0.9)} accent={accent} size={30} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "ic-drop-fill": DropFill,
  "ic-house-grid": HouseGrid,
  "ic-traffic-queue": TrafficQueue,
  "ic-dollar-pulse": DollarPulse,
  "ic-calendar-tear": CalendarTear,
  "ic-hourglass": Hourglass,
  "ic-power-bolt": PowerBolt,
  "ic-fire-flicker": FireFlicker,
  "ic-crowd-swell": CrowdSwell,
  "ic-factory-smoke": FactorySmoke,
};
