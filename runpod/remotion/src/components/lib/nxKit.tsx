import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadSourceSerif } from "@remotion/google-fonts/SourceSerif4";
import { ANTON, ANTON_CAP, SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import type { SoundCue } from "./lookSoundPlan";

/**
 * The shared pieces of the nx- number looks (LibNumbersPro.tsx) and the tx-
 * text looks (LibTextPro.tsx): one type system, one motion language, one
 * place per look.
 *
 *   type     Anton for the figure or the words that carry the line, Inter
 *            Tight 600-700 tracked caps for the small lines, Playfair Display
 *            (regular and italic) for sentences, quotes and context lines;
 *            white with the video's one accent (overlay theme, else the
 *            brand's), never a stroke - a soft dark shadow and at most a
 *            feathered shade.
 *   motion   30-fps frames from the look's first frame (the planner lands it on
 *            the spoken word); glyphs rise out of a mask with a small settle and
 *            drop back into it, figures roll on odometer columns that land left
 *            to right with a vertical motion blur; every look leaves in its last
 *            EXIT frames.
 *   sound    scheduled from the real frames (useLookSound): a soft tick when a
 *            digit changes (never two within 2 frames), a soft click where a
 *            figure lands - a number only ever ticks, never a punch.
 *   place    the lower third at the 96 px safe margin (its foot a quarter of the
 *            height up, clear of the captions) unless a look says otherwise.
 */

export type Look = React.FC<{ overlay: Overlay; accent: string }>;
export type CSS = React.CSSProperties;

// ------------------------------------------------------------------ fonts
const latin = { subsets: ["latin" as const] };
/** Source Serif 4, the documentary serif of the type system (components/fonts.ts; was Playfair Display). */
export const SERIF_TEXT = `${loadSourceSerif("normal", { ...latin, weights: ["400", "500", "600", "700"] }).fontFamily}, Georgia, serif`;
export const SERIF_ITAL = `${loadSourceSerif("italic", { ...latin, weights: ["400", "500", "700"] }).fontFamily}, Georgia, serif`;
export { ANTON, ANTON_CAP, SUBLINE, SUBLINE_CAP };
/** Source Serif 4's cap height and x-height (em). */
export const SERIF_CAP = 0.670;
export const SERIF_X = 0.475;

// ------------------------------------------------------------------ numbers and words
export const clamp01 = (x: number): number => (!Number.isFinite(x) ? 0 : x < 0 ? 0 : x > 1 ? 1 : x);
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
export const easeOut = (t: number): number => 1 - (1 - clamp01(t)) ** 3;
export const easeOutQuart = (t: number): number => 1 - (1 - clamp01(t)) ** 4;
export const easeIn = (t: number): number => clamp01(t) ** 3;
export const easeInOut = (t: number): number => {
  const x = clamp01(t);
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
};
export const expoOut = (t: number): number => (t >= 1 ? 1 : 1 - 2 ** (-10 * clamp01(t)));
/** Ease-out with a small overshoot (about 3 %): the settle. */
export const settle = (t: number, s = 0.9): number => {
  const x = clamp01(t);
  return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2;
};
/** 0 -> 1 from `at` over `len` frames on `ease`. */
export const prog = (f: number, at: number, len: number, ease: (t: number) => number = easeOut): number =>
  ease(clamp01((f - at) / Math.max(0.001, len)));
/** A small stable jitter per index (tick pitches), never Math.random. */
export const jitter = (i: number): number => ((Math.sin(i * 12.9898 + 4.1) * 43758.5453) % 1 + 1) % 1;
export const px = (n: number): string => `${n.toFixed(2)}px`;

// ------------------------------------------------------------------ colour
type RGB = [number, number, number];
export const toRgb = (c: string): RGB => {
  const s = (c || "").trim().replace(/^#/, "");
  let hex = "";
  if (/^[0-9a-f]{6}$/i.test(s)) hex = s;
  else if (/^[0-9a-f]{3}$/i.test(s)) hex = s.split("").map((x) => x + x).join("");
  const m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec((c || "").trim());
  if (!hex && m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const n = hex ? parseInt(hex, 16) : 0xf2b544;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
export const rgba = (c: string, a: number): string => {
  const [r, g, b] = toRgb(c);
  return `rgba(${r},${g},${b},${a})`;
};
export const mix = (a: string, b: string, t: number): string => {
  const x = toRgb(a);
  const y = toRgb(b);
  const f = (i: number) => Math.round(x[i] + (y[i] - x[i]) * clamp01(t));
  return `rgb(${f(0)},${f(1)},${f(2)})`;
};
export const luma = (c: string): number => {
  const [r, g, b] = toRgb(c);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
};
/** The accent as a colour that reads on a dark picture (a navy is lifted toward white, a red only a touch). */
export const readable = (accent: string): string => {
  const l = luma(accent);
  return l < 0.2 ? mix(accent, "#ffffff", 0.55) : l < 0.32 ? mix(accent, "#ffffff", 0.18) : mix(accent, "#000000", 0);
};
/** Ink that reads on an accent fill: near-black on a light accent, white on a dark one. */
export const inkOn = (fill: string): string => (luma(fill) > 0.5 ? "#141414" : "#ffffff");

export const WHITE = "#FFFFFF";
export const SOFT = "rgba(255,255,255,.78)";
export const FAINT = "rgba(255,255,255,.5)";
export const CREAM = "#F4EEE2";

// ------------------------------------------------------------------ time and place
export const EXIT = 10;
export type Clock = {
  /** The look's frame at 30 fps. */
  f: number;
  /** Video frames per 30-fps frame. */
  S: number;
  /** Type scale (1080p px times the editor's text size). */
  k: number;
  /** Frame scale (1080p px), for places and margins. */
  kw: number;
  width: number;
  height: number;
  /** The look's length and the frame its exit starts on (30 fps). */
  end: number;
  exit: number;
};
export const useClock = (exitFrames = EXIT): Clock => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const S = fps / 30;
  const end = durationInFrames / S;
  const kw = Math.min(width, height * (16 / 9)) / 1920;
  return { f: frame / S, S, k, kw, width, height, end, exit: Math.max(end * 0.55, end - exitFrames) };
};
/** 1 while the look holds, easing to 0 over its exit. */
export const outOf = (t: Clock, len = 8, delay = 0): number => 1 - easeIn(clamp01((t.f - t.exit - delay) / Math.max(1, len)));
/** The safe margin (px). */
export const safeOf = (t: Clock): number => 96 * t.kw;

export type Place = "lower-left" | "lower-right" | "center" | "mid-left" | "full";
/**
 * A block on the frame: the lower third at the safe margin (its foot a
 * quarter of the height up), the middle of the frame, or the middle left;
 * `push` a slow drift while it holds.
 */
export const Stage: React.FC<{ t: Clock; place: Place; push?: number; children: React.ReactNode; style?: CSS }> =
  ({ t, place, push = 1, children, style }) => {
    const m = safeOf(t);
    const foot = t.height * 0.25;
    const pos: CSS = place === "lower-left" ? { left: m, bottom: foot, alignItems: "flex-start" }
      : place === "lower-right" ? { right: m, bottom: foot, alignItems: "flex-end" }
        : place === "mid-left" ? { left: m * 1.35, top: 0, bottom: 0, justifyContent: "center", alignItems: "flex-start" }
          : { left: m, right: m, top: m, bottom: m, justifyContent: "center", alignItems: "center" };
    const origin = place === "lower-left" ? "0% 100%" : place === "lower-right" ? "100% 100%"
      : place === "mid-left" ? "0% 50%" : "50% 50%";
    return (
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos, transformOrigin: origin,
        transform: push !== 1 ? `scale(${push.toFixed(5)})` : undefined, ...style }}>
        {children}
      </div>
    );
  };
/** The slow push a block makes while it holds (1 -> 1 + amount from `from` to the exit). */
export const pushOf = (t: Clock, from: number, amount = 0.012): number =>
  1 + amount * clamp01((t.f - from) / Math.max(1, t.exit - from));

/**
 * A feathered shade behind a block: a blurred dark ellipse, no edge anywhere,
 * dark enough under the words that white reads on pale rock and sky.
 */
export const Shade: React.FC<{ t: Clock; o: number; x?: number; y?: number; strength?: number }> =
  ({ t, o, x = 130, y = 90, strength = 1 }) => (o > 0.001 ? (
    <div style={{ position: "absolute", left: -x * t.kw, right: -x * t.kw, top: -y * t.kw, bottom: -y * t.kw, zIndex: -1,
      pointerEvents: "none", opacity: clamp01(o),
      background: `radial-gradient(closest-side, rgba(0,0,0,${(0.62 * strength).toFixed(3)}), rgba(0,0,0,${(0.5 * strength).toFixed(3)}) 52%, `
        + `rgba(0,0,0,${(0.2 * strength).toFixed(3)}) 80%, rgba(0,0,0,0) 100%)`,
      filter: `blur(${(20 * t.kw).toFixed(1)}px)` }} />
  ) : null);

/**
 * The lower corner darkened under a block in the lower third, the way a
 * colourist would lift the words off the picture: one wide soft ellipse from
 * the corner, no edge, no blob over the sky.
 */
export const CornerShade: React.FC<{ o: number; side?: "left" | "right"; strength?: number }> =
  ({ o, side = "left", strength = 1 }) => (o > 0.001 ? (
    <AbsoluteFill style={{ opacity: clamp01(o), pointerEvents: "none",
      background: `radial-gradient(ellipse 78% 66% at ${side === "left" ? "3%" : "97%"} 86%, rgba(0,0,0,${(0.66 * strength).toFixed(3)}) 0%, `
        + `rgba(0,0,0,${(0.48 * strength).toFixed(3)}) 32%, rgba(0,0,0,${(0.2 * strength).toFixed(3)}) 62%, rgba(0,0,0,0) 100%)` }} />
  ) : null);

/** A full-frame darkening for words in the middle of the picture (edges darker than the centre). */
export const Vignette: React.FC<{ o: number; centre?: number; edge?: number; at?: string }> =
  ({ o, centre = 0.32, edge = 0.62, at = "50% 50%" }) => (o > 0.001 ? (
    <AbsoluteFill style={{ opacity: clamp01(o), pointerEvents: "none",
      background: `radial-gradient(ellipse 75% 70% at ${at}, rgba(0,0,0,${centre}) 0%, rgba(0,0,0,${(centre + edge) / 2}) 60%, rgba(0,0,0,${edge}) 100%)` }} />
  ) : null);

/** The soft dark shadow under white letters (on a wrapper, so a mask never cuts it). */
export const shadow = (k: number, small = false): string => (small
  ? `drop-shadow(0 0 ${px(1.1 * k)} rgba(0,0,0,.7)) drop-shadow(0 ${px(1 * k)} ${px(2 * k)} rgba(0,0,0,.5)) drop-shadow(0 ${px(2 * k)} ${px(8 * k)} rgba(0,0,0,.45))`
  : `drop-shadow(0 0 ${px(1.4 * k)} rgba(0,0,0,.6)) drop-shadow(0 ${px(2 * k)} ${px(3 * k)} rgba(0,0,0,.4)) `
    + `drop-shadow(0 ${px(5 * k)} ${px(18 * k)} rgba(0,0,0,.45))`);

// ------------------------------------------------------------------ type metrics
export const ANTON_TOP = 0.065;        // Anton in a 1 em line box: caps from 0.065 em to the baseline at 0.924 em
export const ANTON_BASE = 0.924;
export const SUB_TOP = 0.136;          // Inter Tight: caps from 0.136 em to the baseline at 0.864 em
export const SUB_BASE = 0.864;
export const ANTON_TRACK = 0.012;
/** Anton's advance widths (em). */
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, ";": 0.242, "%": 1.057,
  $: 0.462, "°": 0.389, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "’": 0.214, '"': 0.36, "&": 0.52,
  "/": 0.405, "+": 0.355, "(": 0.291, ")": 0.291, "?": 0.492, "!": 0.229, "#": 0.546, "…": 0.62,
};
/** An odometer column: Anton's digit advance. */
export const DIGIT_W = 0.494;
export const antonEm = (s: string, track = ANTON_TRACK): number =>
  Array.from(s).reduce((a, c) => a + (/[0-9]/.test(c) ? DIGIT_W : ADV[c.toUpperCase()] ?? 0.48) + track, 0);
/** Inter Tight 600-700 caps, roughly (em), with `track` em of letter spacing. */
export const subEm = (s: string, track = 0.16): number =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.234 : /[0-9]/.test(c) ? 0.58 : /[MW@]/.test(c) ? 0.86
    : /[IJ1.,:;'’·|!]/.test(c) ? 0.3 : 0.65) + track, 0);
/** Playfair Display, roughly (em): lower case, capitals, figures. `italic` narrower. */
export const serifEm = (s: string, italic = false): number =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.25 : /[a-z]/.test(c) ? (/[mw]/.test(c) ? 0.8 : /[ijlft]/.test(c) ? 0.3 : 0.5)
    : /[A-Z]/.test(c) ? (/[MW]/.test(c) ? 0.92 : /[IJ]/.test(c) ? 0.36 : 0.68) : /[0-9]/.test(c) ? 0.56 : 0.28), 0) * (italic ? 0.93 : 1);

/** Words into lines no wider than `room` (em of a width function), the lines balanced. */
export const wrapBalanced = (words: string[], room: number, width: (s: string) => number, maxLines = 3): string[] => {
  const greedy = (r: number): string[] => {
    const out: string[] = [];
    let cur = "";
    for (const w of words) {
      const next = cur ? `${cur} ${w}` : w;
      if (cur && width(next) > r) {
        out.push(cur);
        cur = w;
      } else cur = next;
    }
    if (cur) out.push(cur);
    return out;
  };
  let lines = greedy(room);
  if (lines.length < 2) return lines;
  const n = Math.min(lines.length, maxLines);
  // Narrow the room while the line count holds: the lines come out even.
  for (let r = room * 0.97; r > room * 0.4; r *= 0.97) {
    const b = greedy(r);
    if (b.length > n || b.some((l) => width(l) > r + 1e-6 && l.includes(" "))) break;
    lines = b;
  }
  return lines;
};

// ------------------------------------------------------------------ the odometer
/** A figure's odometer: every digit column runs on a 0-9 strip easing out, the columns landing left to right. */
export type Roll = { cols: number[]; from: number[]; to: number[]; c0: number; ends: number[] };
export const rollOf = (text: string, c0: number, cd: number, down = false, gap = 1.6): Roll => {
  const chars = Array.from(text);
  const cols: number[] = [];
  chars.forEach((c, i) => {
    if (/[0-9]/.test(c)) cols.push(i);
  });
  const nc = cols.length;
  const ends = cols.map((_, c) => c0 + cd - (nc - 1 - c) * gap);
  const from: number[] = [];
  const to: number[] = [];
  cols.forEach((i, c) => {
    const d = Number(chars[i]);
    const laps = 1 + Math.min(2, c);
    from.push(down ? 10 * laps + 9 : 0);
    to.push(down ? d : d + 10 * laps);
  });
  return { cols, from, to, c0, ends };
};
export const posAt = (r: Roll, c: number, f: number): number =>
  r.from[c] + (r.to[c] - r.from[c]) * easeOutQuart(clamp01((f - r.c0) / Math.max(1, r.ends[c] - r.c0)));
export const landOf = (r: Roll): number => (r.ends.length ? Math.max(...r.ends) : r.c0);
/** Digits a column passes per frame at f (its motion blur). */
export const speedAt = (r: Roll, c: number, f: number): number => Math.abs(posAt(r, c, f + 0.5) - posAt(r, c, f - 0.5));

/** A soft tick on each change of any column (never two within `gap` frames, rising a little), none just before a landing. */
export const rollTicks = (rolls: Roll[], lands: number[], gap = 2, gain = -8): SoundCue[] => {
  const live = rolls.filter((r) => r.cols.length);
  if (!live.length) return [];
  const start = Math.min(...live.map((r) => r.c0));
  const end = Math.ceil(Math.max(...live.map(landOf)));
  const cues: SoundCue[] = [];
  let last = -99;
  let n = 0;
  for (let f = start + 1; f <= end; f++) {
    const moved = live.some((r) => r.cols.some((_, c) => Math.floor(posAt(r, c, f) + 1e-6) !== Math.floor(posAt(r, c, f - 1) + 1e-6)));
    if (!moved || f - last < gap || lands.some((l) => f > l - 2 && f <= l + 1)) continue;
    const p = clamp01((f - start) / Math.max(1, end - start));
    cues.push({ name: "ui-tick", alt: ["letter-tick", "tick"], at: f, gain_db: gain + 2 * p, pitch: 0.94 + 0.14 * p + 0.03 * jitter(n++) });
    last = f;
  }
  return cues;
};
/** The soft click where a figure lands (count-final; never an impact). */
export const landClicks = (lands: number[], gain = -3): SoundCue[] => {
  const out: SoundCue[] = [];
  [...lands].sort((a, b) => a - b).forEach((l) => {
    const at = Math.round(l);
    if (!out.length || at - out[out.length - 1].at >= 6) out.push({ name: "count-final", alt: ["ui-click", "tick"], at, gain_db: gain });
  });
  return out;
};
/** A very soft tick per word as words land (letter ticks, never two within 3 frames). */
export const wordTicks = (ats: number[], gain = -10, most = 10): SoundCue[] => {
  const out: SoundCue[] = [];
  let last = -99;
  ats.forEach((a, i) => {
    const at = Math.round(a);
    if (at - last < 3 || out.length >= most) return;
    out.push({ name: "letter-tick", alt: ["ui-tick", "tick"], at, gain_db: gain - jitter(i), pitch: 0.96 + 0.08 * jitter(i + 5) });
    last = at;
  });
  return out;
};

/** A unique, CSS-safe id for an SVG filter or gradient. */
export const useSvgId = (prefix: string): string => `${prefix}${React.useId().replace(/[^A-Za-z0-9_-]/g, "")}`;

/** Vertical motion-blur filters (four strengths) for rolling columns; reference them with blurRef(id, speed). */
export const BlurDefs: React.FC<{ id: string; k: number }> = ({ id, k }) => (
  <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
    <defs>
      {[1, 2, 3, 4].map((i) => (
        <filter key={i} id={`${id}-${i}`} x="-10%" y="-60%" width="120%" height="220%">
          <feGaussianBlur stdDeviation={`0 ${(i * i * 0.9 * k + 0.4).toFixed(2)}`} />
        </filter>
      ))}
    </defs>
  </svg>
);
export const blurRef = (id: string, speed: number): string | undefined => {
  const lvl = speed > 1.6 ? 4 : speed > 0.9 ? 3 : speed > 0.45 ? 2 : speed > 0.2 ? 1 : 0;
  return lvl ? `url(#${id}-${lvl})` : undefined;
};

/** The window a rolling column shows its digits through: the line box, its top and bottom edges feathered. */
const DRUM = "linear-gradient(180deg, transparent 0%, #000 7%, #000 93%, transparent 100%)";
/**
 * One odometer column: the digit at `pos` and the next under it rolling
 * through a window exactly one line tall (the digits next on the drum never
 * show), the strip blurred along its travel while it is fast (`blur`).
 */
export const Column: React.FC<{ pos: number; color: string; step?: number; blur?: string }> = ({ pos, color, step = 1.12, blur }) => {
  const base = Math.floor(pos + 1e-6);
  const frac = Math.max(0, pos - base);
  const a = ((base % 10) + 10) % 10;
  const cell = (d: number, y: number) => (
    <span style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "1em", textAlign: "center", color,
      transform: y ? `translateY(${y.toFixed(4)}em)` : undefined }}>{d}</span>
  );
  const moving = frac > 0.001;
  return (
    <span style={{ position: "relative", display: "inline-block", width: `${DIGIT_W}em`, height: "1em", overflow: "hidden",
      maskImage: moving ? DRUM : undefined, WebkitMaskImage: moving ? DRUM : undefined } as CSS}>
      <span style={{ position: "absolute", inset: 0, filter: blur }}>
        {cell(a, -frac * step)}
        {moving ? cell((a + 1) % 10, (1 - frac) * step) : null}
      </span>
    </span>
  );
};

/** The mask a glyph rises in: room above the caps for the settle, just under the baseline, open at the sides. */
export const MASK = "inset(-0.25em -0.6em -0.1em -0.6em)";
const BELOW = 1.2;
const RISE = 8;
/** A glyph's offset (em): up out of the mask with a small settle from `start`, back down into it at the exit. */
export const glyphY = (t: Clock, start: number, exitAt: number): number => {
  if (t.f < start) return BELOW;
  const p = clamp01((t.f - start) / RISE);
  const e = easeIn(clamp01((t.f - exitAt) / 6));
  return BELOW * (1 - settle(p)) + e * BELOW;
};

/**
 * A line of Anton glyphs in its mask, each rising a frame after the one
 * before (from `enter`) and dropping back at the exit; `pos(i)` rolls glyph
 * i as an odometer column; `blur(i)` its motion blur.
 */
export const Glyphs: React.FC<{
  text: string; size: number; t: Clock; enter: number; color?: string | ((i: number) => string);
  pos?: (i: number) => number | null; blur?: (i: number) => string | undefined; exitFrom?: number; stagger?: number;
  shadowed?: boolean; style?: CSS;
}> = ({ text, size, t, enter, color = WHITE, pos, blur, exitFrom = 0, stagger = 1, shadowed = true, style }) => {
  const chars = Array.from(text);
  const exitStep = Math.min(0.5, 4 / Math.max(1, chars.length));
  return (
    <div style={{ position: "relative", fontFamily: ANTON, fontWeight: 400, fontSize: size, lineHeight: 1, whiteSpace: "pre",
      letterSpacing: 0, ...style }}>
      <div style={{ filter: shadowed ? shadow(t.k) : undefined }}>
        <div style={{ clipPath: MASK, display: "flex" }}>
          {chars.map((ch, i) => {
            const off = glyphY(t, enter + i * stagger, t.exit + (exitFrom + i) * exitStep);
            const fill = typeof color === "function" ? color(i) : color;
            const box: CSS = { display: "inline-block", height: "1em", marginRight: `${ANTON_TRACK}em`,
              transform: off ? `translateY(${off.toFixed(4)}em)` : undefined, visibility: off >= BELOW - 1e-3 ? "hidden" : undefined };
            if (ch === " ") return <span key={i} style={{ ...box, width: `${ADV[" "]}em` }} />;
            const p = pos ? pos(i) : null;
            if (p !== null) return <span key={i} style={{ ...box, position: "relative" }}><Column pos={p} color={fill} blur={blur ? blur(i) : undefined} /></span>;
            return <span key={i} style={{ ...box, color: fill }}>{ch}</span>;
          })}
        </div>
      </div>
    </div>
  );
};

/** A small line of Inter Tight tracked caps: in from below as its tracking closes, out with a fade. */
export const Caps: React.FC<{ text: string; size: number; t: Clock; at: number; color?: string; track?: number; weight?: number;
  style?: CSS; len?: number }> = ({ text, size, t, at, color = "rgba(255,255,255,.95)", track = 0.16, weight = 700, style, len = 12 }) => {
  if (!text) return null;
  const p = prog(t.f, at, len);
  const q = 1 - outOf(t, 7);
  return (
    <div style={{ fontFamily: SUBLINE, fontWeight: weight, fontSize: size, lineHeight: 1, whiteSpace: "nowrap",
      letterSpacing: `${(track + 0.12 * (1 - p)).toFixed(4)}em`, textTransform: "uppercase", color,
      opacity: p * (1 - q), transform: `translateY(${((1 - p) * 0.45 + q * 0.4).toFixed(4)}em)`, filter: shadow(t.k, true), ...style }}>
      {text}
    </div>
  );
};

/** A figure's parts as drawn: its digits rolling, a small sign before it ($) and after it (%, °F) at the cap top, its unit words. */
export type FigSpec = { fig: string; pre?: string; top?: string; tag?: string };
/** The unit words beside a figure: one line, or two stacked (a scale and a unit, "MILLION ACRE-FEET"). */
const tagLines = (tag: string): string[] => {
  const ws = (tag || "").split(" ").filter(Boolean);
  return ws.length === 2 && ws[0].length + ws[1].length > 10 ? ws : ws.length ? [ws.join(" ")] : [];
};
/** The unit words' size as a share of the figure's. */
export const TAG_ONE = 0.46;
export const TAG_TWO = 0.43;
/** The figure row's width in em of its size. */
export const figEm = (s: FigSpec): number => {
  const tl = tagLines(s.tag || "");
  return antonEm(s.fig) + (s.pre ? antonEm(s.pre) * 0.55 + 0.04 : 0) + (s.top ? antonEm(s.top) * 0.5 + 0.05 : 0)
    + (tl.length ? 0.16 + Math.max(...tl.map((x) => antonEm(x, 0.03))) * (tl.length > 1 ? TAG_TWO : TAG_ONE) : 0);
};

/**
 * A figure: the $ small at the cap top, the digits rolling (pos), the sign
 * after it at the cap top (%, °F), the unit words beside it in Anton on the
 * figure's baseline ("3,517 FT", "40 MILLION"; a scale and a unit stacked to
 * the figure's cap height). The unit words rise in as the count lands.
 */
export const Figure: React.FC<{
  s: FigSpec; size: number; t: Clock; roll?: Roll; blurId?: string; enter?: number; color?: string; signColor?: string;
  tagColor?: string; tagAt?: number; exitFrom?: number;
  /** A column's position other than the roll's (a slot reel's bounce); the roll still times the blur and the landing. */
  posFn?: (i: number) => number | null;
  /** More motion blur than the roll's speed gives (slot reels). */
  blurBoost?: number;
}> = ({ s, size, t, roll, blurId, enter = 2, color = WHITE, signColor = WHITE, tagColor = WHITE, tagAt, exitFrom = 0, posFn,
  blurBoost = 1 }) => {
  const small = size * 0.52;
  const n = Array.from(s.fig).length;
  const pos = posFn || (roll ? (i: number) => {
    const c = roll.cols.indexOf(i);
    return c >= 0 ? posAt(roll, c, t.f) : null;
  } : undefined);
  const blur = roll && blurId ? (i: number) => {
    const c = roll.cols.indexOf(i);
    return c >= 0 ? blurRef(blurId, speedAt(roll, c, t.f) * blurBoost) : undefined;
  } : undefined;
  const tl = tagLines(s.tag || "");
  const ts = size * (tl.length > 1 ? TAG_TWO : TAG_ONE);
  const tagIn = tagAt ?? (roll ? landOf(roll) - 7 : enter + 8);
  // Two stacked words span the figure's caps; one word sits on its baseline.
  const tagTop = tl.length > 1 ? size * ANTON_TOP - ts * ANTON_TOP : size * ANTON_BASE - ts * ANTON_BASE;
  const gap2 = size * ANTON_CAP - 2 * ts * ANTON_CAP;
  return (
    <div style={{ display: "flex", alignItems: "flex-start" }}>
      {s.pre ? (
        <div style={{ marginRight: size * 0.03, paddingTop: (size - small) * ANTON_TOP }}>
          <Glyphs text={s.pre} size={small} t={t} enter={enter} color={signColor} exitFrom={exitFrom} />
        </div>
      ) : null}
      <Glyphs text={s.fig} size={size} t={t} enter={enter + (s.pre ? 1 : 0)} pos={pos} blur={blur} color={color}
        exitFrom={exitFrom + (s.pre ? 1 : 0)} />
      {s.top ? (
        <div style={{ marginLeft: size * 0.05, paddingTop: (size - small) * ANTON_TOP }}>
          <Glyphs text={s.top} size={small} t={t} enter={enter + Math.min(6, n)} color={signColor} exitFrom={exitFrom + n} />
        </div>
      ) : null}
      {tl.length ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", marginLeft: size * 0.16, paddingTop: tagTop }}>
          {tl.map((x, i) => (
            <div key={i} style={{ marginTop: i ? gap2 - ts * (1 - ANTON_CAP) : 0 }}>
              <Glyphs text={x} size={ts} t={t} enter={tagIn + i * 2} color={tagColor} stagger={0.35} exitFrom={exitFrom + n + i} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

/** The figure's size: its caps `cap` px at 1080p, shrunk to fit `em` wide in maxW (never under 70 %). */
export const sizeFor = (cap: number, t: Clock, em: number, maxW: number): number =>
  Math.max((cap / ANTON_CAP) * t.k * 0.7, Math.min((cap / ANTON_CAP) * t.k, maxW / Math.max(0.5, em)));

/** Serif words revealed one by one (blur 5 -> 0, a small rise, a fade), laid out by the browser and balanced. */
export const SerifWords: React.FC<{
  words: string[]; t: Clock; at: number; step: number; size: number; italic?: boolean; weight?: number; color?: string;
  maxW: number; align?: "left" | "center"; lineHeight?: number; len?: number;
  styleOf?: (i: number) => CSS | undefined; out?: number;
}> = ({ words, t, at, step, size, italic = false, weight = 400, color = WHITE, maxW, align = "left", lineHeight = 1.18, len = 9,
  styleOf, out = 1 }) => (
  <div style={{ fontFamily: italic ? SERIF_ITAL : SERIF_TEXT, fontVariantNumeric: "lining-nums", fontStyle: italic ? "italic" : "normal", fontWeight: weight,
    fontSize: size, lineHeight, color, maxWidth: maxW, textAlign: align, textWrap: "balance", filter: shadow(t.k),
    opacity: out } as CSS}>
    {words.map((w, i) => {
      const p = prog(t.f, at + i * step, len);
      const blur = (1 - p) * 5 * t.k;
      return (
        <React.Fragment key={i}>
          <span style={{ display: "inline-block", opacity: p, transform: p < 1 ? `translateY(${((1 - p) * 0.22).toFixed(4)}em)` : undefined,
            filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined, ...(styleOf ? styleOf(i) : {}) }}>{w}</span>
          {i < words.length - 1 ? " " : null}
        </React.Fragment>
      );
    })}
  </div>
);
