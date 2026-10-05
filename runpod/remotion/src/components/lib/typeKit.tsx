import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Box, Overlay } from "../../types";
import { GROTESK, GROTESK_CAP, INTER, KINETIC, KINETIC_CAP, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoInOut, expoOut, lerp, motionBlur, prog, quintOut }
  from "../motion/ease";
import scale from "./typeScale.json";

/**
 * THE TYPE AND MOTION SYSTEM of the on-screen words and figures (the owner,
 * 2026-10-05: "I don't want this style" - the big yellow condensed word with a
 * thick outline - "it looks cheap, like a CapCut font"; "better animated text,
 * better colours, better bold - Adobe After Effects kind of thing").
 *
 * Three directions, one per video (overlay.typeStyle, from the brand kit or
 * the video style; the planner sets it on every look):
 *
 *   editorial  "Editorial gold" (the default): Inter Tight 700 in white, a
 *              small tracked kicker in the accent (a refined gold), a thin
 *              rule; words arrive with a focus pull, one after another;
 *   doc        "Netflix doc": Inter Tight 800 in white, a thin accent bar
 *              (a clean red) that draws on; lines slide up from behind a mask;
 *   kinetic    "Modern kinetic": Archivo 800 caps, an accent box that wipes
 *              across and leaves the words behind it, a charcoal box backing.
 *
 * Shared by all three: white / off-white type, ONE accent (the brand kit's
 * when it has one), a soft shade or a slim blurred panel behind the words
 * instead of an outline, tabular figures, sizes from one scale relative to
 * the frame height (typeScale.json), safe margins and a home place per kind
 * of look (the owner's same-place rule), mirrored only when the picture there
 * holds a face, a logo or lettering.
 *
 * Motion presets (After Effects style, all eased, 30/60 fps safe):
 *   mask   lines slide up from behind a line (expo-out, 2-frame word stagger)
 *   focus  words come into focus one by one (blur to sharp, a small rise)
 *   rise   words rise with a slight overshoot (back-out)
 *   track  letters condense into place (tracking-in)
 *   box    an accent box wipes across and the words are left behind it
 *   chars  characters arrive one by one (short words and figures)
 * each with a matching exit; figures roll up with a scale settle on landing,
 * fast moves get a touch of motion blur, and one light sweep crosses the
 * accent on its landing.
 */

export type Direction = "editorial" | "doc" | "kinetic";
export type Preset = "mask" | "focus" | "rise" | "track" | "box" | "chars";

export interface DirSpec {
  id: Direction;
  name: string;
  font: string;
  weight: number;
  cap: number;
  tracking: number;
  upper: boolean;
  /** The accent when the overlay has no theme and the brand kit none. */
  accent: string;
  reveal: Preset;
  backing: "soft" | "box";
}

export const DIRECTIONS: Record<Direction, DirSpec> = {
  editorial: { id: "editorial", name: "Editorial gold", font: GROTESK, weight: 700, cap: GROTESK_CAP, tracking: -0.012,
    upper: false, accent: "#F2B544", reveal: "focus", backing: "soft" },
  doc: { id: "doc", name: "Netflix doc", font: GROTESK, weight: 800, cap: GROTESK_CAP, tracking: -0.015, upper: false,
    accent: "#E5484D", reveal: "mask", backing: "soft" },
  kinetic: { id: "kinetic", name: "Modern kinetic", font: KINETIC, weight: 800, cap: KINETIC_CAP, tracking: -0.005,
    upper: true, accent: "#FFB224", reveal: "box", backing: "box" },
};
export const DEFAULT_DIRECTION: Direction = "editorial";
const ALIASES: Record<string, Direction> = {
  editorial: "editorial", gold: "editorial", b: "editorial", doc: "doc", netflix: "doc", documentary: "doc", a: "doc",
  kinetic: "kinetic", modern: "kinetic", c: "kinetic",
};
export const directionOf = (ov: Overlay): DirSpec =>
  DIRECTIONS[ALIASES[String((ov as { typeStyle?: string }).typeStyle || "").toLowerCase()] || DEFAULT_DIRECTION];

export const WHITE = "#FAFAF7";
export const SOFT_WHITE = "rgba(250,250,247,0.82)";
export const CHARCOAL = "rgba(12,14,18,0.76)";
export const INK = "#0b0d11";

// ------------------------------------------------------------------ sizes
type Role = keyof typeof scale;
const roleShare = (role: Role): number => {
  const r = scale[role] as { share?: number };
  return typeof r?.share === "number" ? r.share : 0.04;
};
/** The font size (px) whose capitals stand `share` of the frame height in a face of cap height `cap` (em). */
export const sizeFor = (role: Role, H: number, cap = GROTESK_CAP, ks = 1) => (roleShare(role) * H * ks) / cap;
export const HERO = scale.hero;
export const UNIT_OF_HERO = scale.unit.ofHero;
export const SAFE = scale.safe;

/** The editor's text size (overlay.fontScale), else as designed. */
export const fontScaleOf = (ov: Overlay) =>
  typeof ov.fontScale === "number" && ov.fontScale > 0 ? Math.max(0.6, Math.min(1.8, ov.fontScale)) : 1;

// ------------------------------------------------------------------ measuring
let ctx: CanvasRenderingContext2D | null | undefined;
const canvas = () => {
  if (ctx !== undefined) return ctx;
  try {
    ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  } catch {
    ctx = null;
  }
  return ctx;
};
/** Width (px) of a line of type, measured with the real font in the browser (an estimate without one). */
export const widthOf = (text: string, font: string, size: number, weight: number, tracking = 0): number => {
  const c = canvas();
  const t = text || "";
  let w: number;
  if (c) {
    c.font = `${weight} ${size}px ${font}`;
    w = c.measureText(t).width;
  } else {
    w = Array.from(t).reduce((a, ch) => a + (ch === " " ? 0.25 : /[il.,:;'!|1]/.test(ch) ? 0.3 : /[MW%@]/.test(ch) ? 0.92
      : /[A-Z0-9]/.test(ch) ? 0.66 : 0.55), 0) * size;
  }
  return w + tracking * size * Math.max(0, Array.from(t).length - 1);
};

/** Words wrapped into at most `maxLines` balanced lines no wider than maxW, shrinking from `size` to `least`. */
export const fitLines = (text: string, font: string, weight: number, size: number, least: number, maxW: number,
  maxLines = 2, tracking = 0): { lines: string[]; size: number; width: number } | null => {
  const words = (text || "").split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  for (let s = size; s >= least - 0.01; s *= 0.95) {
    const w = (x: string) => widthOf(x, font, s, weight, tracking);
    if (words.some((wd) => w(wd) > maxW)) continue;
    // the fewest lines, then the most balanced split
    for (let n = 1; n <= maxLines; n++) {
      const lines = balance(words, n, w);
      if (lines && lines.every((l) => w(l) <= maxW)) return { lines, size: s, width: Math.max(...lines.map(w)) };
    }
  }
  return null;
};

const balance = (words: string[], n: number, w: (s: string) => number): string[] | null => {
  if (n === 1) return [words.join(" ")];
  if (words.length < n) return null;
  let best: string[] | null = null;
  let score = Infinity;
  const go = (from: number, left: number, acc: string[]) => {
    if (left === 1) {
      const lines = [...acc, words.slice(from).join(" ")];
      const ws = lines.map(w);
      const s = Math.max(...ws) - Math.min(...ws) * 0.5;
      if (s < score) {
        score = s;
        best = lines;
      }
      return;
    }
    for (let i = from + 1; i <= words.length - (left - 1); i++) go(i, left - 1, [...acc, words.slice(from, i).join(" ")]);
  };
  go(0, n, []);
  return best;
};

// ------------------------------------------------------------------ places
export type Zone = "lower-left" | "lower-right" | "upper-left" | "upper-right" | "left-panel" | "right-panel";
export const MIRROR: Record<string, Zone> = {
  "lower-left": "lower-right", "lower-right": "lower-left", "upper-left": "upper-right", "upper-right": "upper-left",
  "left-panel": "right-panel", "right-panel": "left-panel",
};
export const isRight = (z: Zone) => z.endsWith("right");
export const isUpper = (z: Zone) => z.startsWith("upper");

/** A block's rectangle (px) at a zone: anchored to the safe corner, w x h. */
export const blockAt = (zone: Zone, w: number, h: number, W: number, H: number) => {
  const mx = SAFE.x * W;
  const x = isRight(zone) ? W - mx - w : mx;
  const y = isUpper(zone) ? SAFE.top * H : zone.endsWith("panel") ? (H - h) / 2 : H - SAFE.bottom * H - h;
  return { x, y, w, h };
};

const overlap = (a: { x: number; y: number; w: number; h: number }, b: Box, W: number, H: number) => {
  const bx = b.x * W, by = b.y * H, bw = b.w * W, bh = b.h * H;
  const ox = Math.min(a.x + a.w, bx + bw) - Math.max(a.x, bx);
  const oy = Math.min(a.y + a.h, by + bh) - Math.max(a.y, by);
  return ox > 0 && oy > 0 ? ox * oy : 0;
};

/**
 * The zone a block goes to: the planner's (overlay.zone, chosen from the
 * calm of the picture), else the look's home; mirrored when the home holds a
 * face, a logo or lettering of the picture (overlay.avoid) and the mirror is
 * clearer; never moved for nothing (the same-place rule).
 */
export const zoneFor = (ov: Overlay, home: Zone, w: number, h: number, W: number, H: number): Zone => {
  const own = String((ov as { zone?: string }).zone || "");
  const start: Zone = (MIRROR[own] ? own : home) as Zone;
  const avoid = Array.isArray(ov.avoid) ? ov.avoid : [];
  if (!avoid.length) return start;
  const hit = (z: Zone) => avoid.reduce((a, b) => a + overlap(blockAt(z, w, h, W, H), b, W, H), 0);
  const here = hit(start);
  if (here <= 0) return start;
  const there = hit(MIRROR[start]);
  return there < here * 0.5 ? MIRROR[start] : start;
};

// ------------------------------------------------------------------ backings
/**
 * A soft shade behind words on the footage: a feathered darkening toward the
 * frame's corner, no edge and no box - white type reads on snow and on sky.
 */
export const SoftBacking: React.FC<{ rect: { x: number; y: number; w: number; h: number }; p: number; right?: boolean;
  strength?: number }> = ({ rect, p, right = false, strength = 0.62 }) => {
  const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
  const w = rect.w * 1.9 + 260, h = rect.h * 2.4 + 200;
  return (
    <div style={{ position: "absolute", left: cx - w / 2 + (right ? 40 : -40), top: cy - h / 2, width: w, height: h,
      opacity: clamp01(p), pointerEvents: "none",
      background: `radial-gradient(ellipse 50% 50% at 50% 50%, rgba(4,5,8,${strength}) 0%, rgba(4,5,8,${(strength * 0.6).toFixed(3)}) 42%, rgba(4,5,8,0) 100%)` }} />
  );
};

/**
 * A slim panel at the side of the frame for busy footage (a detailed map,
 * a crowd): the picture behind it blurred and darkened, fading into the
 * picture toward the middle - words never float over a busy picture.
 */
export const PanelBacking: React.FC<{ right?: boolean; p: number; widthShare?: number }> = ({ right = false, p, widthShare = 0.44 }) => {
  const { width: W } = useVideoConfig();
  const k = W / 1920;
  const q = clamp01(p);
  const dir = right ? "270deg" : "90deg";
  const mask = `linear-gradient(${dir}, #000 0%, #000 55%, rgba(0,0,0,0.6) 78%, transparent 100%)`;
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: q,
      transform: `translateX(${((1 - expoOut(q)) * (right ? 40 : -40) * k).toFixed(1)}px)` }}>
      <div style={{ position: "absolute", top: 0, bottom: 0, [right ? "right" : "left"]: 0, width: `${widthShare * 100}%`,
        backdropFilter: `blur(${(18 * k).toFixed(1)}px) saturate(0.8)`, WebkitBackdropFilter: `blur(${(18 * k).toFixed(1)}px) saturate(0.8)`,
        background: `linear-gradient(${dir}, rgba(8,10,14,0.80) 0%, rgba(8,10,14,0.62) 60%, rgba(8,10,14,0) 100%)`,
        WebkitMaskImage: mask, maskImage: mask }} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ the light sweep
/** One light sweep across a box (a glint on an accent bar or a figure), at progress p 0..1. */
export const Glint: React.FC<{ p: number; color?: string; width?: number }> = ({ p, color = "rgba(255,255,255,0.85)", width = 0.35 }) => {
  if (p <= 0 || p >= 1) return null;
  const x = lerp(-60, 160, cubicInOut(p));
  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none", mixBlendMode: "screen", overflow: "hidden",
      background: `linear-gradient(105deg, transparent ${x - width * 100}%, ${color} ${x}%, transparent ${x + width * 100}%)` }} />
  );
};

// ------------------------------------------------------------------ kinetic lines
export interface KTiming {
  /** The frame (30 fps) the line starts to arrive, and how long each word takes. */
  at: number;
  gap?: number;
  len?: number;
}

const wordsOf = (s: string) => s.split(/(\s+)/).filter((x) => x.length);

/**
 * One line of kinetic type: the words of `text` arriving by `preset`, each
 * starting `gap` frames after the one before, and leaving in the look's last
 * frames (`out`: 0 holding, 1 gone) by the mirrored move. Drawn as inline
 * words (so the line wraps nowhere: one line is one line).
 */
export const KineticLine: React.FC<{
  text: string; font: string; weight: number; size: number; color?: string; tracking?: number; upper?: boolean;
  preset: Preset; timing: KTiming; out: number; align?: "left" | "right"; shadow?: string; tabular?: boolean;
  accent?: string; style?: React.CSSProperties;
}> = ({ text, font, weight, size, color = WHITE, tracking = 0, upper = false, preset, timing, out, align = "left",
  shadow, tabular = false, accent = "#F2B544", style }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const S = fps / 30;
  const t = upper ? text.toUpperCase() : text;
  const gap = timing.gap ?? (preset === "chars" ? 1.2 : preset === "focus" ? 3 : 2);
  const len = timing.len ?? (preset === "focus" ? 16 : preset === "track" ? 20 : 15);
  const base: React.CSSProperties = {
    fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1.04, letterSpacing: `${tracking}em`, color,
    whiteSpace: "pre", fontVariantNumeric: tabular ? "tabular-nums" : undefined,
    fontFeatureSettings: tabular ? '"tnum" 1' : undefined, textShadow: shadow, display: "block",
    textAlign: align, ...style,
  };
  const exitOp = 1 - out;
  if (preset === "track") {
    const e = prog(f, timing.at, len, S, expoOut);
    const o = prog(f, timing.at, 12, S, cubicOut);
    return (
      <div style={{ ...base, letterSpacing: `${(tracking + 0.34 * (1 - e) + 0.08 * out).toFixed(4)}em`,
        opacity: o * exitOp, filter: `blur(${((1 - o) * 4 + out * 4).toFixed(2)}px)` }}>{t}</div>
    );
  }
  if (preset === "box") {
    // The accent box wipes over the line's width (9 frames), holds 2, and wipes off to the right (10),
    // leaving the words; on the exit it wipes back over them and away.
    const a = prog(f, timing.at, 9, S, expoOut);
    const b = prog(f, timing.at + 11, 10, S, expoInOut);
    const covered = f >= (timing.at + 9) * S;
    const ex1 = clamp01(out * 2);
    const ex2 = clamp01(out * 2 - 1);
    const boxL = out > 0 ? 0 : b;
    const boxR = out > 0 ? 1 - ex1 : 1 - a;
    const showText = covered && !(out > 0 && ex1 >= 1);
    return (
      <div style={{ position: "relative", display: "inline-block", ...style }}>
        <div style={{ ...base, opacity: showText ? 1 : 0, display: "inline-block" }}>{t}</div>
        {boxR < 1 && boxL < 1 && !(out > 0 && ex2 >= 1) ? (
          <div style={{ position: "absolute", top: "6%", bottom: "2%", left: `${(out > 0 ? ex2 : boxL) * 100}%`,
            right: `${(out > 0 ? 1 - ex1 : boxR) * 100}%`, background: accent }} />
        ) : null}
      </div>
    );
  }
  const parts = preset === "chars" ? Array.from(t) : wordsOf(t);
  let n = 0;
  return (
    <div style={{ ...base, overflow: preset === "mask" ? "hidden" : undefined,
      paddingBottom: preset === "mask" ? size * 0.12 : undefined, marginBottom: preset === "mask" ? -size * 0.12 : undefined }}>
      {parts.map((w, i) => {
        if (/^\s+$/.test(w)) return <span key={i}>{w}</span>;
        const j = n++;
        const total = parts.filter((x) => !/^\s+$/.test(x)).length;
        let st: React.CSSProperties = {};
        if (preset === "mask") {
          const e = prog(f, timing.at + j * gap, len, S, expoOut);
          const e1 = prog(f + S, timing.at + j * gap, len, S, expoOut);
          const x = clamp01(out * 1.3 - ((total - 1 - j) / Math.max(1, total)) * 0.3);
          const y = (1 - e) * 105 - cubicIn(x) * 105;
          const v = (e1 - e) * size;
          st = { transform: `translateY(${y.toFixed(2)}%)`, filter: motionBlur(v) ? `blur(${(motionBlur(v) * 0.6).toFixed(2)}px)` : undefined };
        } else if (preset === "focus") {
          const e = prog(f, timing.at + j * gap, len, S, cubicOut);
          const x = clamp01(out * 1.4 - (j / Math.max(1, total)) * 0.4);
          st = { opacity: e * (1 - x), filter: `blur(${((1 - e) * 10 + x * 6).toFixed(2)}px)`,
            transform: `translateY(${((1 - e) * 0.22 - x * 0.12).toFixed(3)}em) scale(${(1.04 - 0.04 * e).toFixed(4)})` };
        } else if (preset === "rise") {
          const e = prog(f, timing.at + j * gap, len, S, (u) => backOut(u, 1.25));
          const o = prog(f, timing.at + j * gap, 8, S, cubicOut);
          const x = clamp01(out * 1.3 - (j / Math.max(1, total)) * 0.3);
          st = { opacity: o * (1 - x), transform: `translateY(${((1 - e) * 0.55 - cubicIn(x) * 0.3).toFixed(3)}em)` };
        } else {
          // chars
          const e = prog(f, timing.at + j * gap, len, S, quintOut);
          const x = clamp01(out * 1.3 - (j / Math.max(1, total)) * 0.3);
          st = { opacity: clamp01(e * 1.5) * (1 - x), filter: `blur(${((1 - e) * 6 + x * 4).toFixed(2)}px)`,
            transform: `translateY(${((1 - e) * 0.35).toFixed(3)}em)` };
        }
        return <span key={i} style={{ display: "inline-block", willChange: "transform", ...st }}>{w}</span>;
      })}
    </div>
  );
};

// ------------------------------------------------------------------ figures
/** A figure counting up to its value (expo-out), "from" 0 or a start, with its final decimals. */
export const countUp = (value: number, p: number, from = 0): number => from + (value - from) * clamp01(p);

/** The scale settle on a figure's landing: 1.04 -> 1 on a back-out over 12 frames from `land`. */
export const settle = (f: number, land: number, S = 1) => {
  if (f < land * S) return 1;
  const e = prog(f, land, 12, S, (u) => backOut(u, 1.6));
  return 1.045 - 0.045 * e;
};

/** Format a number for the screen: 60,000 · 760,000 · 1.25M · 2.8M · 27 · 4.5 (decimals as said, at most 2). */
export const formatFigure = (v: number, decimals?: number): { main: string; glued: string } => {
  const a = Math.abs(v);
  const d = (x: number) => (decimals !== undefined ? decimals : Number.isInteger(x) ? 0 : Math.min(2, (String(x).split(".")[1] || "").length));
  if (a >= 1e9) return { main: trimZeros((v / 1e9).toFixed(Math.min(2, d(v / 1e9)))), glued: "B" };
  if (a >= 1e6) return { main: trimZeros((v / 1e6).toFixed(Math.min(2, d(v / 1e6)))), glued: "M" };
  const dd = d(v);
  return { main: v.toLocaleString("en-US", { minimumFractionDigits: dd, maximumFractionDigits: dd }), glued: "" };
};
const trimZeros = (s: string) => (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s);

/** A figure partway through its count, formatted like the final one (the same decimals and scale letter). */
export const figureAt = (value: number, p: number, from = 0): string => {
  const final = formatFigure(value);
  const dec = (final.main.split(".")[1] || "").length;
  const scaleBy = final.glued === "B" ? 1e9 : final.glued === "M" ? 1e6 : 1;
  const v = countUp(value, p, from) / scaleBy;
  if (p >= 1) return final.main;
  return scaleBy > 1 ? v.toFixed(dec) : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
};

/** A text shadow that holds white type on any picture without an outline. */
export const softShadow = (k: number, o = 0.55) =>
  `0 ${(1.5 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,${(o * 0.8).toFixed(2)}), `
  + `0 ${(6 * k).toFixed(1)}px ${(26 * k).toFixed(1)}px rgba(0,0,0,${o.toFixed(2)})`;

/** Small tracked caps: kickers, labels, units. */
export const kickerStyle = (size: number, color: string, tracking = 0.2): React.CSSProperties => ({
  fontFamily: SUBLINE, fontWeight: 700, fontSize: size, letterSpacing: `${tracking}em`, textTransform: "uppercase",
  color, lineHeight: 1, whiteSpace: "nowrap",
});

export const contextStyle = (size: number, color = SOFT_WHITE): React.CSSProperties => ({
  fontFamily: INTER, fontWeight: 600, fontSize: size, lineHeight: 1.2, color, whiteSpace: "nowrap",
});

export { clamp01, cubicIn, cubicInOut, cubicOut, expoOut, prog };
