import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { INTER, LABEL } from "../fonts";
import { useK } from "./ProGraphics";

/**
 * The design kit the rebuilt looks share (the owner, 2026-09-30: "every
 * animation cleaner, cinematic, like a $1000-5000 human editor made it").
 *
 * One design language across the looks that ride on footage:
 *  - dark glass plates (a blurred, darkened window on the picture, a hairline
 *    edge, a soft long shadow), an accent edge that draws, one light sweep;
 *  - bold condensed caps for labels (Barlow Condensed 800), Inter 800 tabular
 *    figures for numbers, Inter 600-700 for sentences - never below 26 px at
 *    1080p for anything the viewer must read (a phone shows 1080p at a third);
 *  - kickers on a solid accent chip, never thin tracked colour on the footage;
 *  - 96 px safe margins at 1080p, the bottom 26 % left to the captions;
 *  - entrances on expo-out with 3-5 frame staggers, masks and wipes rather
 *    than fades, and a clean 12-frame exit in which every element leaves.
 *
 * Text is measured (em widths per face) and fitted: it shrinks, then wraps
 * to balanced lines, then ellipsises - it never runs off the frame.
 */

export const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
export const EASE = {
  out: Easing.bezier(0.16, 1, 0.3, 1),
  in: Easing.bezier(0.7, 0, 0.84, 0),
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  back: Easing.bezier(0.34, 1.56, 0.64, 1),
  softBack: Easing.bezier(0.3, 1.3, 0.5, 1),
  count: Easing.bezier(0.25, 0.85, 0.3, 1),
};

/** 0 -> 1 from `at` over `frames`. */
export const tween = (frame: number, at: number, frames: number, ease = EASE.out) =>
  interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], { ...clamp, easing: ease });

/** 0 while the look holds, easing to 1 over its last `frames` frames. */
export const useExit = (frames = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return tween(frame, Math.max(0, durationInFrames - frames - 1), frames, EASE.in);
};

// ------------------------------------------------------------------ colour
const rgbOf = (c: string): [number, number, number] | null => {
  const s = (c || "").trim();
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (m) {
    const h = m[1].length === 3 ? m[1].split("").map((x) => x + x).join("") : m[1];
    const v = parseInt(h, 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }
  const r = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(s);
  return r ? [Number(r[1]), Number(r[2]), Number(r[3])] : null;
};
const hex = (c: number[]) => `#${c.map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, "0")).join("")}`;
export const alpha = (c: string, a: number): string => {
  const v = rgbOf(c) || [230, 57, 70];
  return `rgba(${v[0]},${v[1]},${v[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
};
export const mix = (a: string, b: string, t: number): string => {
  const x = rgbOf(a) || [230, 57, 70];
  const y = rgbOf(b) || [255, 255, 255];
  return hex(x.map((v, i) => v + (y[i] - v) * Math.max(0, Math.min(1, t))));
};
export const luma = (c: string): number => {
  const v = rgbOf(c);
  return v ? (0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]) / 255 : 0.5;
};
/** The accent as a colour for text and glows on dark glass: a grey or white accent becomes warm yellow, a dark one lifts. */
export const bright = (accent: string): string => {
  const c = rgbOf(accent);
  if (!c) return "#FFC83D";
  const max = Math.max(...c), min = Math.min(...c);
  if (max === 0 || (max - min) / max < 0.18) return "#FFC83D";
  let out = hex(c);
  for (let i = 0; i < 6 && luma(out) < 0.32; i++) out = mix(out, "#ffffff", 0.16);
  return out;
};
/** Ink for text on a fill: near-black on light fills, white on dark ones. */
export const inkOn = (fill: string): string => (luma(fill) > 0.58 ? "#0b0d11" : "#ffffff");

export const INK = "#0b0d11";
export const PAPER = "#f3f1ea";
export const SOFT = "rgba(255,255,255,.78)";
export const GLASS = "linear-gradient(135deg, rgba(20,23,31,.88) 0%, rgba(11,13,18,.80) 100%)";
export const SHADOW = "0 22px 60px rgba(0,0,0,.48), 0 4px 14px rgba(0,0,0,.28)";
export const TEXT_SHADOW = "0 2px 4px rgba(0,0,0,.45), 0 8px 28px rgba(0,0,0,.55)";

// ------------------------------------------------------------------ measuring
/** A face's width relative to Inter Bold (monospace advance when `mono`). */
export type Face = { w: number; mono?: number };
export const F = {
  inter: { w: 1.0 } as Face,
  interHeavy: { w: 1.03 } as Face,
  label: { w: 0.70 } as Face,        // Barlow Condensed 700-800 (calibrated on caps against the real font)
  display: { w: 0.62 } as Face,      // Bebas Neue (caps only)
  narrow: { w: 0.81 } as Face,       // Oswald 700
  serif: { w: 1.05 } as Face,
  mono: { w: 1, mono: 0.6 } as Face,
};
const charEm = (c: string): number => {
  if (c === " ") return 0.27;
  if (/[.,:;!'|]/.test(c)) return 0.28;
  if (/[iIlj]/.test(c)) return 0.3;
  if (/[ftr1J()"]/.test(c)) return 0.42;
  if (/[mwMW@%&]/.test(c)) return 0.92;
  if (/[A-Z]/.test(c)) return 0.66;
  if (/[0-9$]/.test(c)) return 0.64;
  return 0.58;
};
/** Width of `s` in em of its font size, with `tracking` em of letter spacing per character. */
export const measure = (s: string, face: Face, tracking = 0): number => {
  const chars = Array.from(s || "");
  const body = face.mono ? chars.length * face.mono : chars.reduce((a, c) => a + charEm(c), 0) * face.w * 1.04;
  return body + tracking * chars.length;
};
const greedy = (words: string[], limit: number, w: (s: string) => number): string[] => {
  const out: string[] = [];
  let cur = "";
  for (const wd of words) {
    const cand = cur ? `${cur} ${wd}` : wd;
    if (cur && w(cand) > limit) {
      out.push(cur);
      cur = wd;
    } else cur = cand;
  }
  if (cur) out.push(cur);
  return out;
};
export type Fit = { lines: string[]; size: number };
/**
 * Lines and a size (px) so no line is wider than `maxW` px: start at `base`,
 * wrap into at most `maxLines` balanced lines, shrink toward `min`; past that
 * the last line ends in an ellipsis. Never wider than the room.
 */
export const fit = (text: string, face: Face, base: number, min: number, maxW: number, maxLines = 2,
  tracking = 0): Fit => {
  const words = (text || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (!words.length) return { lines: [], size: base };
  const w = (s: string) => measure(s, face, tracking);
  const longest = Math.max(...words.map(w));
  let size = Math.min(base, maxW / Math.max(0.01, longest));
  const floor = Math.min(min, size);
  for (;;) {
    const limit = maxW / size;
    const ls = greedy(words, limit, w);
    if (ls.length <= maxLines) {
      if (ls.length === 1) return { lines: ls, size };
      let lo = longest, hi = limit;
      for (let i = 0; i < 14; i++) {
        const mid = (lo + hi) / 2;
        if (greedy(words, mid, w).length <= ls.length) hi = mid;
        else lo = mid;
      }
      return { lines: greedy(words, hi, w), size };
    }
    if (size <= floor + 0.01) {
      const out = ls.slice(0, maxLines);
      let last = out[maxLines - 1];
      while (last.includes(" ") && w(`${last}…`) > limit) last = last.slice(0, last.lastIndexOf(" "));
      out[maxLines - 1] = `${last.replace(/[\s,;:.\-–—]+$/, "")}…`;
      return { lines: out, size };
    }
    size = Math.max(floor, size * 0.95);
  }
};
/** The widest line of a fit, in px. */
export const widthOf = (f: Fit, face: Face, tracking = 0): number =>
  Math.max(0, ...f.lines.map((l) => measure(l, face, tracking))) * f.size;

// ------------------------------------------------------------------ text helpers
export const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
export const caps = (v: unknown): string => str(v).toUpperCase();

// ------------------------------------------------------------------ numbers
export type Num = { value: number; from: number; dec: number; grouping: boolean; prefix: string; unit: string };
const WORD_UNIT: Record<string, string> = { K: "THOUSAND", M: "MILLION", MN: "MILLION", B: "BILLION", BN: "BILLION", T: "TRILLION" };
const decimalsOf = (v: number): number => {
  if (Number.isInteger(v)) return 0;
  const frac = (v.toFixed(6).split(".")[1] || "").replace(/0+$/, "");
  return Math.min(Math.abs(v) >= 100 ? 1 : 2, frac.length);
};
export const fmtNum = (v: number, dec: number, grouping: boolean) =>
  (Number.isFinite(v) ? v : 0).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: grouping });
/** A figure as drawn: value, prefix and unit ("%", "FT", "MILLION"); years never get a comma or count from zero. */
export const numOf = (ov: { value?: unknown; prefix?: unknown; suffix?: unknown }, words = false): Num | null => {
  let value = typeof ov.value === "number" ? ov.value
    : typeof ov.value === "string" && ov.value.trim() ? Number(ov.value.replace(/[,\s]/g, "")) : NaN;
  if (!Number.isFinite(value)) return null;
  let prefix = str(ov.prefix);
  const suffix = str(ov.suffix);
  const money = prefix.includes("$") || /^(usd|dollars?)$/i.test(suffix);
  let unit = suffix === "%" ? "%" : suffix;
  const up = suffix.toUpperCase();
  if (money) {
    if (!prefix) prefix = "$";
    unit = WORD_UNIT[up] || (/^(USD|DOLLARS?)$/.test(up) ? "" : up);
    if (!unit && Math.abs(value) >= 1e9) {
      value = Math.round(value / 1e7) / 100;
      unit = "BILLION";
    } else if (!unit && Math.abs(value) >= 1e6) {
      value = Math.round(value / 1e4) / 100;
      unit = "MILLION";
    }
  } else if (words && WORD_UNIT[up]) {
    unit = WORD_UNIT[up];
  } else if (unit && unit !== "%") {
    unit = unit.toUpperCase();
  }
  const year = Number.isInteger(value) && value >= 1500 && value <= 2100 && !prefix && !unit;
  return { value, from: year ? value - 40 : 0, dec: decimalsOf(value), grouping: !year, prefix, unit };
};

/**
 * A counting figure: the finished number laid out invisibly to hold the
 * width, the running count drawn over it right-aligned (nothing shuffles).
 */
export const Count: React.FC<{ n: Num; p: number; style?: React.CSSProperties }> = ({ n, p, style }) => {
  const cur = n.from + (n.value - n.from) * Math.max(0, Math.min(1, p));
  return (
    <span style={{ position: "relative", display: "inline-block", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums",
      fontFeatureSettings: '"tnum" 1', ...style }}>
      <span style={{ visibility: "hidden" }}>{fmtNum(n.value, n.dec, n.grouping)}</span>
      <span style={{ position: "absolute", right: 0, top: 0 }}>{fmtNum(p >= 1 ? n.value : cur, n.dec, n.grouping)}</span>
    </span>
  );
};
/** The figure's width in em (Inter 800 tabular) with its prefix and unit. */
export const figureEm = (n: Num, unitScale = 0.42): number => {
  let em = 0;
  for (const c of fmtNum(n.value, n.dec, n.grouping)) em += /\d/.test(c) ? 0.64 : c === "," || c === "." ? 0.28 : 0.6;
  if (n.prefix) em += 0.62 * 0.62 * n.prefix.length + 0.04;
  if (n.unit === "%") em += 0.55 * 0.8;
  else if (n.unit) em += 0.12 + measure(n.unit, F.label, 0.04) * unitScale;
  return em;
};

// ------------------------------------------------------------------ pieces
/** A line that rises out of its mask at `at` and, as `q` goes to 1, drops back into it. */
export const Rise: React.FC<{ at: number; q?: number; frames?: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ at, q = 0, frames = 16, children, style }) => {
    const frame = useCurrentFrame();
    const p = tween(frame, at, frames);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.12em", marginBottom: "-0.12em", ...style }}>
        <div style={{ transform: `translateY(${((1 - p) * 108 + q * 108).toFixed(2)}%)`, opacity: p > 0.002 ? 1 : 0 }}>{children}</div>
      </div>
    );
  };

/** One soft light band crossing its (overflow-hidden) parent between `at` and `at + frames`. */
export const Sweep: React.FC<{ at: number; frames?: number; strength?: number }> = ({ at, frames = 20, strength = 0.22 }) => {
  const frame = useCurrentFrame();
  const p = tween(frame, at, frames, EASE.inOut);
  if (p <= 0 || p >= 1) return null;
  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden", borderRadius: "inherit" }}>
      <div style={{ position: "absolute", top: "-50%", bottom: "-50%", width: "38%", left: `${-45 + p * 150}%`,
        transform: "rotate(18deg)", mixBlendMode: "screen",
        background: `linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,${strength}) 50%, rgba(255,255,255,0) 100%)` }} />
    </div>
  );
};

/** A solid accent chip with caps in the ink that reads on it (the kicker every look uses), wiping open at `at`. */
export const Chip: React.FC<{ text: string; at: number; accent: string; size?: number; q?: number; dark?: boolean;
  style?: React.CSSProperties }> = ({ text, at, accent, size = 26, q = 0, dark, style }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const p = tween(frame, at, 12) * (1 - q);
  if (!text) return null;
  const fill = dark ? "rgba(10,12,16,.86)" : accent;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 10 * k, background: fill,
      color: dark ? bright(accent) : inkOn(accent), fontFamily: LABEL, fontWeight: 800, fontSize: size * k, lineHeight: 1,
      letterSpacing: "0.16em", textTransform: "uppercase", padding: `${8 * k}px ${14 * k}px ${7 * k}px ${16 * k}px`,
      borderRadius: 4 * k, whiteSpace: "nowrap", clipPath: `inset(0 ${((1 - p) * 100).toFixed(2)}% 0 0)`,
      boxShadow: "0 8px 24px rgba(0,0,0,.35)", ...style }}>
      {text}
    </div>
  );
};

/**
 * A dark glass plate: blurred picture behind it, a hairline edge, a soft long
 * shadow, an optional accent edge (left or top) that draws with `p`. `p`
 * (0..1) wipes it open from the left.
 */
export const Plate: React.FC<{ p: number; accent?: string; edge?: "left" | "top" | "right" | "none"; radius?: number;
  style?: React.CSSProperties; sweepAt?: number; children?: React.ReactNode; tone?: "dark" | "paper"; from?: "left" | "right" }> =
  ({ p, accent, edge = "left", radius = 10, style, sweepAt, children, tone = "dark", from = "left" }) => {
    const k = useK();
    const paper = tone === "paper";
    const e = Math.max(0, Math.min(1, p));
    const cut = ((1 - e) * 100).toFixed(2);
    const clip = from === "left" ? `inset(0 ${cut}% 0 0 round ${radius * k}px)` : `inset(0 0 0 ${cut}% round ${radius * k}px)`;
    return (
      <div style={{ position: "relative", borderRadius: radius * k, overflow: "hidden",
        background: paper ? `linear-gradient(180deg, #faf8f3 0%, ${PAPER} 100%)` : GLASS,
        backdropFilter: paper ? undefined : "blur(14px) saturate(1.1)", WebkitBackdropFilter: paper ? undefined : "blur(14px) saturate(1.1)",
        boxShadow: `${SHADOW}, inset 0 1px 0 ${paper ? "rgba(255,255,255,.9)" : "rgba(255,255,255,.07)"}`,
        border: paper ? "1px solid rgba(0,0,0,.06)" : "1px solid rgba(255,255,255,.09)",
        clipPath: clip, ...style }}>
        {accent && (edge === "left" || edge === "right") ? (
          <div style={{ position: "absolute", [edge]: 0, top: 0, bottom: 0, width: 6 * k, background: accent,
            transform: `scaleY(${e})`, transformOrigin: "50% 0" }} />
        ) : null}
        {accent && edge === "top" ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 5 * k, background: accent,
            transform: `scaleX(${e})`, transformOrigin: "0 50%" }} />
        ) : null}
        {children}
        {sweepAt !== undefined ? <Sweep at={sweepAt} strength={paper ? 0.5 : 0.16} /> : null}
      </div>
    );
  };

/**
 * The owner's text language (2026-09-30: "NO background layout, ONLY TEXT ...
 * on the sides"; 2026-10-01: a soft black shadow instead of the black stroke):
 * no plate, pill, band or box behind words that ride on footage - the letters
 * carry a soft dark shadow, legible on bright sky and on night footage alike.
 * `size` is the font size in px; the shadow scales with it.
 */
export const outline = (size: number, color = "#fff", k = 1): React.CSSProperties => {
  // 2026-10-01 (the owner: "the stroke is not great - use a shadow instead of the stroke"):
  // no outline any more, a soft black shadow in three layers - a tight edge, a close
  // shadow and a wide soft one - scaled with the type, legible on snow and on night.
  const e = Math.max(1, Math.min(2.2 * k, size * 0.02));
  const near = Math.max(2 * k, size * 0.035);
  const far = Math.max(10 * k, size * 0.24);
  return {
    color,
    textShadow: `0 0 ${e.toFixed(1)}px rgba(0,0,0,.75), 0 ${(near * 0.6).toFixed(1)}px ${near.toFixed(1)}px rgba(0,0,0,.5), `
      + `0 ${(near * 1.4).toFixed(1)}px ${far.toFixed(1)}px rgba(0,0,0,.5)`,
  } as React.CSSProperties;
};
/** Bold condensed caps with the outline (Barlow Condensed 800): the house display type for text on footage. */
export const boldCaps = (size: number, color = "#fff", k = 1, tracking = 0.02): React.CSSProperties => ({
  fontFamily: LABEL, fontWeight: 800, fontSize: size, lineHeight: 1.02, letterSpacing: `${tracking}em`,
  textTransform: "uppercase", whiteSpace: "nowrap", ...outline(size, color, k),
});

/** Sentence text in the house style (Inter 700, tight), for plates. */
export const sentence = (size: number, color = "#fff"): React.CSSProperties => ({
  fontFamily: INTER, fontWeight: 700, fontSize: size, lineHeight: 1.16, color, letterSpacing: "-0.01em",
});
/** Label caps in the house style (Barlow Condensed 800). */
export const labelCaps = (size: number, color = "#fff", tracking = 0.04): React.CSSProperties => ({
  fontFamily: LABEL, fontWeight: 800, fontSize: size, lineHeight: 1.04, color, letterSpacing: `${tracking}em`,
  textTransform: "uppercase", whiteSpace: "nowrap",
});
