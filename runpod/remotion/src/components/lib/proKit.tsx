import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadNewsreader } from "@remotion/google-fonts/Newsreader";
import { loadFont as loadInstrument } from "@remotion/google-fonts/InstrumentSerif";
import { loadFont as loadSignature } from "@remotion/google-fonts/MrsSaintDelafield";
import { ANTON, HAND, INTER, MONO, SERIF, SUBLINE, TYPEWRITER } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { bright } from "../pro/Kit";

/**
 * The shared kit of the pro looks (LibDataPro "dx-", LibMapsPro "mx-",
 * LibDocsPro "kx-"), built to read like a top documentary editor's graphics:
 *
 *  - type: Anton for the figures and words that carry a line, Inter Tight
 *    600-700 in tracked caps for the small line under them (the owner's pair,
 *    2026-10-01), Newsreader for print (articles, reports, letters), Instrument
 *    Serif for quotes and definitions, Caveat for a hand, Mrs Saint Delafield
 *    for a signature; nothing the viewer must read under 24 px at 1080p;
 *  - one accent per video (the overlay's theme colour), everything else
 *    white, ink, paper and glass;
 *  - over footage a look always brings its own scrim or plate (legible on snow
 *    and on night footage); a full-screen look sits on a cinematic veil;
 *  - motion: expo-out entrances under 0.8 s with 3-5 frame staggers, a clear
 *    hit frame (the registry's sfxAt), a slow drift while it holds, and a
 *    clean 12-frame exit in which every element leaves;
 *  - text is measured in the browser (canvas, the real fonts) and fitted:
 *    it shrinks, wraps to balanced lines, then ends in an ellipsis - it never
 *    runs off the frame.
 *
 * Every look is wrapped in an error boundary: a malformed document draws
 * nothing for that look, it never fails the render.
 */

const latin = { subsets: ["latin" as const] };
/** Newsreader: the news text face (articles, reports, memos, letters). */
export const NEWS = `${loadNewsreader("normal", { ...latin, weights: ["400", "600", "700"] }).fontFamily}, ${SERIF}`;
export const NEWS_ITALIC = `${loadNewsreader("italic", { ...latin, weights: ["400"] }).fontFamily}, ${SERIF}`;
/** Instrument Serif: quotes, definitions, the elegant display line. */
export const DISPLAY_SERIF = `${loadInstrument("normal", { ...latin, weights: ["400"] }).fontFamily}, ${SERIF}`;
export const DISPLAY_SERIF_ITALIC = `${loadInstrument("italic", { ...latin, weights: ["400"] }).fontFamily}, ${SERIF}`;
/** A real signature hand. */
export const SIGNATURE = `${loadSignature("normal", { ...latin, weights: ["400"] }).fontFamily}, cursive`;
export { ANTON, HAND, INTER, MONO, SUBLINE, TYPEWRITER };

export type Look = React.FC<{ overlay: Overlay; accent: string }>;
export type CSS = React.CSSProperties;

// ------------------------------------------------------------------ easing
export const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const easeOut = (t: number) => 1 - (1 - clamp01(t)) ** 3;
export const easeOutQuart = (t: number) => 1 - (1 - clamp01(t)) ** 4;
export const expoOut = (t: number) => (t >= 1 ? 1 : t <= 0 ? 0 : 1 - 2 ** (-10 * t));
export const easeIn = (t: number) => clamp01(t) ** 3;
export const easeInOut = (t: number) => {
  const x = clamp01(t);
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
};
export const sineInOut = (t: number) => -(Math.cos(Math.PI * clamp01(t)) - 1) / 2;
/** Ease-out with a small overshoot (`s` 1.0 about 10 %), for a settle. */
export const backOut = (t: number, s = 1.2) => {
  const x = clamp01(t) - 1;
  return 1 + (s + 1) * x * x * x + s * x * x;
};
/** 0 -> 1 from `at` over `frames`, eased (expo-out by default). */
export const inOf = (f: number, at: number, frames: number, ease: (t: number) => number = expoOut) =>
  ease(clamp01((f - at) / Math.max(1, frames)));
/** 0 -> 1 over an exit, eased in (a soft start, a quick leave). */
export const outOf = (f: number, at: number, frames: number) => clamp01((f - at) / Math.max(1, frames)) ** 2;

/** The base every look reads: frame, the rate scale (30 fps = 1), the size scale, the frame scale, size, length. */
export const useBase = () => {
  const f = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  return { f, fps, S: fps / 30, k, kw: width / 1920, width, height, dur: durationInFrames };
};

/** The exit, 0 while the look holds and 1 at its last frame: `frames` (30 fps) long, never more than a third of the look. */
export const exitOf = (f: number, dur: number, S: number, frames = 12) => {
  const n = Math.max(2, Math.min(Math.round(frames * S), Math.floor(dur / 3)));
  return outOf(f, dur - n, n);
};

/** A deterministic 0..1 from an integer (no Math.random in a render). */
export const rnd = (i: number) => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
/** A stable hash of a string. */
export const hash = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};

/** A document-unique id for SVG defs, so two instances never share a gradient, filter or clip. */
export const useSvgId = (prefix: string) => `${prefix}${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;

/** The accent as a colour for text and glows on dark (a grey or white accent becomes warm yellow). */
export const hotOf = (accent: string) => bright(accent || "#FFC83D");

// ------------------------------------------------------------------ colour
const rgbOf = (c: string): [number, number, number] => {
  const s = (c || "").trim();
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (m) {
    const h = m[1].length === 3 ? m[1].split("").map((x) => x + x).join("") : m[1];
    const v = parseInt(h, 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }
  const r = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(s);
  return r ? [Number(r[1]), Number(r[2]), Number(r[3])] : [255, 200, 61];
};
export const rgba = (c: string, a: number) => {
  const [r, g, b] = rgbOf(c);
  return `rgba(${r},${g},${b},${clamp01(a).toFixed(3)})`;
};
export const mixHex = (a: string, b: string, t: number) => {
  const x = rgbOf(a);
  const y = rgbOf(b);
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * clamp01(t)).toString(16).padStart(2, "0")).join("")}`;
};

// ------------------------------------------------------------------ measuring
let ctx2d: CanvasRenderingContext2D | null | undefined;
const canvas = (): CanvasRenderingContext2D | null => {
  if (ctx2d !== undefined) return ctx2d;
  try {
    ctx2d = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  } catch {
    ctx2d = null;
  }
  return ctx2d;
};

/** Rough em widths when there is no canvas (a node test): per face. */
const ESTIMATE: [RegExp, number][] = [
  [/Anton/i, 0.47], [/Instrument/i, 0.43], [/Newsreader/i, 0.47], [/Mrs Saint/i, 0.36], [/Caveat/i, 0.4],
  [/Courier|JetBrains|Mono/i, 0.6], [/Inter Tight/i, 0.56], [/Inter/i, 0.58],
];

/**
 * The width in px of `text` set in `font` (a CSS family stack) at `size` px:
 * measured in the browser with the real font, estimated without one.
 * `tracking` is letter spacing in em.
 */
export const textWidth = (text: string, font: string, size: number, weight: number | string = 400, tracking = 0,
  italic = false): number => {
  const t = text || "";
  const c = canvas();
  let w: number;
  if (c) {
    c.font = `${italic ? "italic " : ""}${weight} ${size}px ${font}`;
    w = c.measureText(t).width;
  } else {
    const em = ESTIMATE.find(([rx]) => rx.test(font))?.[1] ?? 0.55;
    w = Array.from(t).reduce((a, ch) => a + (ch === " " ? 0.26 : /[ilI.,:;'!|]/.test(ch) ? 0.28 : /[MW@%]/.test(ch) ? 0.9
      : /[A-Z0-9]/.test(ch) ? em * 1.12 : em), 0) * size;
  }
  return w + tracking * size * Math.max(0, Array.from(t).length - 1);
};

export interface Face {
  font: string;
  weight?: number | string;
  tracking?: number;
  italic?: boolean;
}

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

/** Words wrapped into lines no wider than `maxW` at `size`, balanced (the shortest width that keeps the line count). */
export const wrap = (text: string, face: Face, size: number, maxW: number): string[] => {
  const words = (text || "").split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const w = (s: string) => textWidth(s, face.font, size, face.weight ?? 400, face.tracking ?? 0, face.italic);
  const first = greedy(words, maxW, w);
  if (first.length <= 1) return first;
  let lo = maxW * 0.45;
  let hi = maxW;
  let best = first;
  for (let i = 0; i < 12; i++) {
    const mid = (lo + hi) / 2;
    const got = greedy(words, mid, w);
    if (got.length <= first.length) {
      best = got;
      hi = mid;
    } else lo = mid;
  }
  return best;
};

export interface Fitted {
  lines: string[];
  size: number;
  width: number;
}

/**
 * The largest size from `max` down to `min` at which `text` wraps into at most
 * `maxLines` lines no wider than `maxW`; at `min` the last line is cut at a
 * word and ends in an ellipsis. `width` is the widest line's width.
 */
export const fit = (text: string, face: Face, maxW: number, max: number, min: number, maxLines = 2): Fitted => {
  const t = (text || "").trim();
  const w = (s: string, size: number) => textWidth(s, face.font, size, face.weight ?? 400, face.tracking ?? 0, face.italic);
  if (!t) return { lines: [], size: max, width: 0 };
  for (let size = max; size >= min - 0.01; size *= 0.94) {
    const ls = wrap(t, face, size, maxW);
    if (ls.length <= maxLines && ls.every((l) => w(l, size) <= maxW + 0.5)) {
      return { lines: ls, size, width: Math.max(...ls.map((l) => w(l, size))) };
    }
  }
  const size = min;
  const ls = wrap(t, face, size, maxW);
  const out = ls.slice(0, maxLines);
  if (ls.length > maxLines || (out.length && w(out[out.length - 1], size) > maxW)) {
    let last = out[out.length - 1] || "";
    while (last.includes(" ") && w(`${last}…`, size) > maxW) last = last.replace(/\s+\S+$/, "");
    while (last.length > 1 && w(`${last}…`, size) > maxW) last = last.slice(0, -1);
    out[out.length - 1] = `${last.replace(/[\s,.;:!?-]+$/, "")}…`;
  }
  return { lines: out, size, width: Math.max(0, ...out.map((l) => w(l, size))) };
};

// ------------------------------------------------------------------ the boundary
class Boundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    // A look that cannot draw this document draws nothing; the video renders on.
    console.warn("[pro look] draws nothing:", error instanceof Error ? error.message : String(error));
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/** A look that draws nothing rather than failing the render, whatever the document holds. */
export const guard = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) => (overlay && typeof overlay === "object"
    ? <Boundary><Inner overlay={overlay} accent={accent || "#FFC83D"} /></Boundary> : null);
  return Guarded;
};

// ------------------------------------------------------------------ surfaces
/**
 * A fine static film grain (the same on every frame, so nothing shimmers),
 * at `opacity`: it takes the flat digital edge off a full-screen graphic.
 */
export const Grain: React.FC<{ opacity?: number; seed?: number; blend?: CSS["mixBlendMode"] }> =
  ({ opacity = 0.06, seed = 3, blend = "overlay" }) => {
    const id = useSvgId("grain");
    return (
      <AbsoluteFill style={{ opacity, mixBlendMode: blend, pointerEvents: "none" }}>
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
          <filter id={id} x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency={0.9} numOctaves={2} seed={seed} stitchTiles="stitch" />
            <feColorMatrix type="saturate" values="0" />
          </filter>
          <rect width="100%" height="100%" filter={`url(#${id})`} />
        </svg>
      </AbsoluteFill>
    );
  };

/** A soft vignette at `strength` (the edges darker, the middle clear). */
export const Vignette: React.FC<{ strength?: number; opacity?: number }> = ({ strength = 0.6, opacity = 1 }) => (
  <AbsoluteFill style={{ opacity, pointerEvents: "none",
    background: `radial-gradient(ellipse 75% 70% at 50% 48%, rgba(0,0,0,0) 45%, rgba(0,0,0,${strength}) 100%)` }} />
);

/**
 * What a full-screen data look sits on. On a full-screen moment (fullFrame:
 * the blurred still of the clip is already under it) a cinematic veil that
 * keeps a hint of the picture; riding on footage, the footage blurred and
 * darkened through the glass. `p` fades it in, the exit fades it out.
 */
export const Stage: React.FC<{ ov: Overlay; p: number; tone?: number }> = ({ ov, p, tone = 1 }) => {
  const { k } = useBase();
  const full = Boolean(ov.fullFrame);
  return (
    <AbsoluteFill style={{ opacity: clamp01(p) }}>
      {full ? null : (
        <AbsoluteFill style={{ backdropFilter: `blur(${(22 * k).toFixed(1)}px) saturate(0.7) brightness(${(0.62 - 0.12 * tone).toFixed(2)})`,
          WebkitBackdropFilter: `blur(${(22 * k).toFixed(1)}px) saturate(0.7) brightness(${(0.62 - 0.12 * tone).toFixed(2)})` }} />
      )}
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 85% 80% at 50% 45%, rgba(7,9,13,${(0.42 * tone).toFixed(2)}) 0%, `
        + `rgba(5,6,9,${(0.7 * tone).toFixed(2)}) 70%, rgba(3,4,6,${Math.min(0.92, 0.86 * tone).toFixed(2)}) 100%)` }} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

/**
 * A soft pool of shade behind words or a figure riding on footage: no edge,
 * no box - a feathered darkening that makes white legible on snow.
 */
export const Pool: React.FC<{ x: number; y: number; w: number; h: number; p: number; strength?: number }> =
  ({ x, y, w, h, p, strength = 0.62 }) => (
    <div style={{ position: "absolute", left: x - w / 2, top: y - h / 2, width: w, height: h, opacity: clamp01(p),
      pointerEvents: "none", background: `radial-gradient(ellipse 50% 50% at 50% 50%, rgba(0,0,0,${strength}) 0%, `
        + `rgba(0,0,0,${(strength * 0.55).toFixed(3)}) 45%, rgba(0,0,0,0) 100%)` }} />
  );

/** A text shadow that holds white type on any picture without a stroke. */
export const lift = (k: number, o = 0.6) =>
  `0 ${(1 * k).toFixed(1)}px ${(2 * k).toFixed(1)}px rgba(0,0,0,${(o * 0.9).toFixed(2)}), `
  + `0 ${(4 * k).toFixed(1)}px ${(18 * k).toFixed(1)}px rgba(0,0,0,${o.toFixed(2)})`;

/** Small tracked caps (Inter Tight 700): the line under a figure, a kicker, an axis label. */
export const caps = (size: number, color = "#fff", tracking = 0.14): CSS => ({
  fontFamily: SUBLINE, fontWeight: 700, fontSize: size, letterSpacing: `${tracking}em`, textTransform: "uppercase",
  color, lineHeight: 1, whiteSpace: "nowrap",
});

/** Anton for a figure or a word that carries the line. */
export const heavy = (size: number, color = "#fff", tracking = 0.01): CSS => ({
  fontFamily: ANTON, fontWeight: 400, fontSize: size, letterSpacing: `${tracking}em`, color, lineHeight: 1,
  whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums",
});
