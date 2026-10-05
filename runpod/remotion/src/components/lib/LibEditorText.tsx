import React from "react";
import { AbsoluteFill, Easing, interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadSourceSerif } from "@remotion/google-fonts/SourceSerif4";
import { DISPLAY, HAND, INTER, LABEL, MONO, NARROW, SERIF } from "../fonts";
import type { Overlay } from "../../types";
import { ramp, useK } from "../pro/ProGraphics";

/**
 * Editor text (family "ed-"): the on-screen words a human documentary editor
 * sets, each with its own typography and move, so a video never shows the
 * same text look every thirty seconds.
 *
 *   ed-type-clean        typed letter by letter on a soft dark strip, low-left; the key word warms afterwards
 *   ed-type-terminal     monospace typing on a frosted glass card with a window dot row (records, facts)
 *   ed-word-by-word      a centred kinetic caption, one word at a time, the key word glowing in the accent
 *   ed-marker-highlight  a white paper strip, a yellow highlighter sweeping across the key words
 *   ed-blur-in           cinematic letter-spaced title: letters un-blur while the tracking tightens
 *   ed-split-reveal      two lines slide in from opposite sides behind masks, a short accent bar between
 *   ed-box-stack         2-4 words in yellow / white boxes, stacked with an offset, popping in
 *   ed-news-clipping     a newspaper headline clipping with a torn edge sliding in rotated and settling
 *   ed-glass-caption     a frosted glass pill with an icon, bottom centre
 *   ed-outline-fill      a big outline title filling with colour left to right
 *   ed-side-note         a handwritten editor's note with a drawn arrow pointing into the frame
 *   ed-quote-type        a serif quote typed letter by letter, soft quote marks, the attribution after
 *   ed-question          a question in large clean type, the "?" drawn in the accent
 *   ed-alert-bar         a clean warning bar (amber, red for life-threatening words), the icon pulsing
 *
 * Typing contract (shared with the sound planner, src/sfxplan.py): typing
 * starts at frame TYPE_START = 6 of the overlay and reveals one character
 * every framesPerChar(text) frames (2 when the text is 48 characters or
 * fewer, else 1), so it ends at frame 6 + framesPerChar * length. A blinking
 * caret shows while it types.
 *
 * Sizes are the final pixel size at 1080p with the text families' default
 * scale (1.2, Main.tsx textScale); long text shrinks and wraps to at most three
 * lines instead of clipping. Every look leaves in its last 12 frames. No sound
 * is played here: the timeline sound is planned on the look's "sfx_at" frame.
 * Deterministic: no Math.random or Date.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

// The heavy documentary serif (Source Serif 4 800; was Playfair Display 800): headlines on newsprint, typed quotes.
const PLAYFAIR_HEAVY = `${loadSourceSerif("normal", { subsets: ["latin"], weights: ["800"] }).fontFamily}, Georgia, serif`;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const softBack = Easing.bezier(0.3, 1.35, 0.5, 1);
const EXIT = 12;
const INK = "#111317";
const YELLOW = "#FFC83D";
const PAPER = "#F7F5EF";
const DEFAULT_SCALE = 1.2;

// ------------------------------------------------------------------ typing contract
export const TYPE_START = 6;
/** Frames per typed character: 2 for text of 48 characters or fewer, else 1. */
export const framesPerChar = (raw: string): number => ((raw || "").length <= 48 ? 2 : 1);
/** The frame typing ends on (exclusive): TYPE_START + framesPerChar * length. */
export const typingEnds = (raw: string): number => TYPE_START + framesPerChar(raw) * (raw || "").length;
/** Characters on screen at `frame` for a text whose raw form is `raw` (at most `total`). */
export const typedAt = (frame: number, raw: string, total: number): number =>
  frame < TYPE_START ? 0 : Math.max(0, Math.min(total, Math.floor((frame - TYPE_START) / framesPerChar(raw)) + 1));

// ------------------------------------------------------------------ helpers
/** A text prop as a clean one-line string (numbers allowed, anything else empty). */
export const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
const raw = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const norm = (w: string): string => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");

/** Deterministic 0..1 noise from an integer. */
const rnd = (i: number): number => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
const seedOf = (s: string): number => {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 100003;
  return h;
};

export const rgbOf = (hex: string): [number, number, number] | null => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((hex || "").trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  const v = parseInt(h, 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
};
const toHex = (c: number[]): string => `#${c.map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, "0")).join("")}`;
export const alpha = (hex: string, a: number): string => {
  const c = rgbOf(hex) || [255, 200, 61];
  return `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
};
export const lum = (hex: string): number => {
  const c = rgbOf(hex);
  return c ? (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255 : 0.5;
};
const mix = (a: string, b: string, t: number): string => {
  const x = rgbOf(a) || [255, 200, 61];
  const y = rgbOf(b) || [255, 255, 255];
  return toHex(x.map((v, i) => v + (y[i] - v) * t));
};
/**
 * The accent as a colour that reads on dark footage: a near-white or grey
 * accent becomes the warm yellow (a key word must visibly change colour), a
 * dark one is lifted toward white.
 */
export const vivid = (accent: string): string => {
  const c = rgbOf(accent);
  if (!c) return YELLOW;
  const max = Math.max(...c);
  const min = Math.min(...c);
  const sat = max === 0 ? 0 : (max - min) / max;
  if (sat < 0.18) return YELLOW;
  let out = toHex(c);
  for (let i = 0; i < 6 && lum(out) < 0.5; i++) out = mix(out, "#ffffff", 0.18);
  return out;
};
/** Near-black on a light colour, white on a dark one. */
export const readableOn = (hex: string): string => (lum(hex) > 0.55 ? INK : "#ffffff");

const STOP = new Set(["the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "but", "is", "are", "was",
  "were", "be", "been", "it", "its", "this", "that", "these", "those", "with", "from", "by", "as", "into", "than",
  "then", "they", "their", "there", "have", "has", "had", "not", "no", "will", "would", "could", "should", "can",
  "just", "about", "what", "when", "where", "which", "who", "why", "how", "we", "our", "you", "your", "he", "she",
  "his", "her", "them", "so", "if", "all", "more", "most", "very", "only", "still", "actually", "simply", "really",
  "already", "almost", "nearly", "around", "because", "before", "after", "during", "other", "every", "being", "going",
  "through", "while", "again", "until", "since", "there's", "it's", "that's", "didn't", "don't", "wasn't", "never"]);

/**
 * The words to mark: the highlight prop's words that are in the text, else the
 * longest content word (and, in a longer line, the next-longest too).
 */
export const keyWords = (text: string, highlight?: string, many = false): Set<string> => {
  const inText = text.split(" ").map(norm).filter(Boolean);
  const given = str(highlight).split(/[\s,]+/).map(norm).filter((w) => w && inText.indexOf(w) >= 0);
  if (given.length) return new Set(given);
  const content = inText.filter((w) => !STOP.has(w) && w.length >= 4);
  const ranked = [...content].sort((a, b) => b.length - a.length);
  const out = new Set<string>();
  if (ranked[0] && ranked[0].length >= 5) out.add(ranked[0]);
  if (many && inText.length >= 6 && ranked[1] && ranked[1].length >= 5) out.add(ranked[1]);
  if (!out.size && ranked[0]) out.add(ranked[0]);
  return out;
};

// ------------------------------------------------------------------ measuring and fitting
/** A typeface's width relative to Inter Bold (its mono advance when fixed). */
export type Face = { w: number; mono?: number };
export const F_INTER = { w: 1.0 };
export const F_INTER_HEAVY = { w: 1.04 };
export const F_LABEL = { w: 0.74 };
export const F_DISPLAY = { w: 0.62 };
export const F_NARROW = { w: 0.76 };
export const F_SERIF = { w: 0.98 };
export const F_SERIF_HEAVY = { w: 1.04 };
export const F_HAND = { w: 0.74 };
export const F_MONO = { w: 1, mono: 0.6 };

const charEm = (c: string): number => {
  if (c === " ") return 0.27;
  if (/[.,:;!'|]/.test(c)) return 0.27;
  if (/[iIlj]/.test(c)) return 0.3;
  if (/[ftr1J()"]/.test(c)) return 0.42;
  if (/[mwMW@%&]/.test(c)) return 0.92;
  if (/[A-Z]/.test(c)) return 0.72;
  if (/[0-9$]/.test(c)) return 0.64;
  return 0.58;
};
/** Width of `s` in em for a face, with `tracking` em of letter spacing per character. */
export const measure = (s: string, face: Face, tracking = 0): number => {
  const chars = Array.from(s);
  const body = face.mono ? chars.length * face.mono : chars.reduce((a, c) => a + charEm(c), 0) * face.w * 1.03;
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
 * Lines and a font size (px) for `text` so no line is wider than `maxW` px:
 * start at `base`, wrap to at most `maxLines` evenly balanced lines, shrink
 * toward `min` when it does not fit; past that the last line ends in an
 * ellipsis (never clipped by the frame).
 */
export const fitText = (text: string, face: Face, base: number, min: number, maxW: number, maxLines = 3,
  tracking = 0, balance = true): Fit => {
  const words = text.split(" ").filter(Boolean);
  if (!words.length) return { lines: [], size: base };
  const w = (s: string) => measure(s, face, tracking);
  const longest = Math.max(...words.map(w));
  let size = Math.min(base, maxW / Math.max(0.01, longest));
  const floor = Math.min(min, size);
  for (;;) {
    const limit = maxW / size;
    const ls = greedy(words, limit, w);
    if (ls.length <= maxLines) {
      if (!balance || ls.length === 1) return { lines: ls, size };
      let lo = longest;
      let hi = limit;
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

// ------------------------------------------------------------------ shared pieces
/** 0 while the graphic holds, easing to 1 over its last EXIT frames. */
export const useOut = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - EXIT, EXIT, expoIn);
};
/** Final pixels for a 1080p size, honouring the editor's text-size setting (KScale). */
const usePx = () => {
  const k = useK();
  return (n: number) => (n / DEFAULT_SCALE) * k;
};

/** A blinking typing caret (inline, zero width so the line never shifts). */
const Caret: React.FC<{ color: string; on: boolean }> = ({ color, on }) => (
  <span style={{ display: "inline-block", width: 0, height: "0.95em", verticalAlign: "-0.12em", position: "relative" }}>
    <span style={{ position: "absolute", left: "0.05em", top: 0, bottom: 0, width: "0.075em", minWidth: 2,
      background: color, opacity: on ? 1 : 0, borderRadius: 1 }} />
  </span>
);

/**
 * Lines typed character by character: `shown` characters of the text they
 * were cut from (one space between lines counts as a character), the rest
 * laid out but hidden so nothing shifts; the caret sits after the last
 * character typed. `colorOf` colours a whole word (typed part only).
 */
const TypedLines: React.FC<{ lines: string[]; shown: number; caret: boolean; caretColor: string;
  colorOf?: (word: string) => React.CSSProperties | undefined; lineStyle?: React.CSSProperties }> =
  ({ lines: ls, shown, caret, caretColor, colorOf, lineStyle }) => {
    const frame = useCurrentFrame();
    const blinkOn = frame % 16 < 10;
    let offset = 0;
    let caretLine = 0;
    const starts = ls.map((l) => {
      const s = offset;
      offset += l.length + 1;
      return s;
    });
    starts.forEach((s, i) => {
      if (s <= shown) caretLine = i;
    });
    return (
      <>
        {ls.map((line, i) => {
          const visible = Math.max(0, Math.min(line.length, shown - starts[i]));
          const parts: React.ReactNode[] = [];
          let placed = !(caret && i === caretLine);
          let pos = 0;
          const words = line.split(" ");
          words.forEach((wd, j) => {
            const a = pos;
            const b = pos + wd.length;
            const vis = Math.max(0, Math.min(wd.length, visible - a));
            const st = colorOf ? colorOf(wd) : undefined;
            if (vis > 0) parts.push(<span key={`t${j}`} style={st}>{wd.slice(0, vis)}</span>);
            if (!placed && visible >= a && visible <= b) {
              parts.push(<Caret key="caret" color={caretColor} on={blinkOn} />);
              placed = true;
            }
            if (vis < wd.length) parts.push(<span key={`h${j}`} style={{ ...st, visibility: "hidden" }}>{wd.slice(vis)}</span>);
            if (j < words.length - 1) {
              parts.push(<span key={`s${j}`} style={visible > b ? undefined : { visibility: "hidden" }}> </span>);
            }
            pos = b + 1;
          });
          return <div key={i} style={{ whiteSpace: "pre", ...lineStyle }}>{parts}</div>;
        })}
      </>
    );
  };

/** Soft full-frame shading (never on a full-screen scene, which has its own backdrop). */
const Shade: React.FC<{ ov: Overlay; background: string; at?: number; out: number }> = ({ ov, background, at = 0, out }) => {
  const frame = useCurrentFrame();
  if (ov.fullFrame) return null;
  return <AbsoluteFill style={{ background, opacity: ramp(frame, at, 12) * (1 - out) }} />;
};

// ================================================================== ed-type-clean
/**
 * Typed letter by letter in a clean sans on a soft dark gradient strip,
 * low-left, a caret blinking while it types; once typed, the key word warms
 * into the accent. Also drives the built-in "typewriter" overlay.
 */
export const EdTypeClean: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const rawText = raw(overlay.text);
  const text = str(overlay.text);
  if (!text) return null;
  const kicker = str(overlay.label).toUpperCase();
  // The owner (2026-09-30): no strip or box behind the words - bold white letters with a black outline.
  const { lines: ls, size } = fitText(text, F_INTER_HEAVY, px(84), px(52), width * 0.64, 3);
  const shown = typedAt(frame, rawText, text.length);
  const done = typingEnds(rawText);
  const keys = keyWords(text, overlay.highlight);
  const hot = vivid(accent);
  const shift = ramp(frame, done + 2, 12, inOut);
  const keyCol = interpolateColors(shift, [0, 1], ["#ffffff", hot]);
  const lineH = size * 1.18;
  const kickPx = px(44);
  const kickH = kicker ? kickPx * 1.4 : 0;
  const blockH = ls.length * lineH + kickH;
  const left = 124 * u;
  const bottom = 300 * u;
  const barIn = ramp(frame, 2, 14);
  const stroke = (s: number): React.CSSProperties => ({
    WebkitTextStroke: `${Math.max(4.5 * u, Math.min(12 * u, s * 0.1)).toFixed(2)}px #000`, paintOrder: "stroke fill",
    textShadow: `0 ${3 * u}px ${4 * u}px rgba(0,0,0,.35), 0 ${8 * u}px ${26 * u}px rgba(0,0,0,.5)`,
  } as React.CSSProperties);
  return (
    <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(out * 14 * u).toFixed(2)}px)` }}>
      <div style={{ position: "absolute", left: left - 26 * u, bottom, width: Math.max(4, 8 * u), height: blockH,
        background: hot, transform: `scaleY(${barIn})`, transformOrigin: "bottom", borderRadius: 2 * u,
        boxShadow: `0 0 0 ${2.5 * u}px #000, 0 0 ${14 * u}px ${hot}` }} />
      <div style={{ position: "absolute", left, bottom, fontFamily: INTER, fontWeight: 800, fontSize: size, letterSpacing: "-0.01em",
        lineHeight: `${lineH}px`, color: "#fff", ...stroke(size) }}>
        {kicker ? (
          <div style={{ fontFamily: LABEL, fontSize: kickPx, lineHeight: 1.4, fontWeight: 800, letterSpacing: "0.12em", color: hot,
            ...stroke(kickPx), opacity: ramp(frame, 2, 10), transform: `translateY(${((1 - ramp(frame, 2, 12)) * 10).toFixed(2)}px)` }}>
            {kicker}
          </div>
        ) : null}
        <TypedLines lines={ls} shown={shown} caret={frame < done + 30} caretColor={hot}
          colorOf={(w) => (keys.has(norm(w)) ? { color: keyCol } : undefined)} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-type-terminal
/**
 * Monospace typing on a frosted dark glass card with a small window dot row
 * and a record label: for records, figures and facts. A prompt in the accent
 * leads the line; the caret blinks after it is typed.
 */
const EdTypeTerminal: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const rawText = raw(overlay.text);
  const text = str(overlay.text);
  if (!text) return null;
  const label = (str(overlay.label) || "RECORD").toUpperCase().slice(0, 28);
  const hot = vivid(accent);
  const maxW = width * 0.52;
  const { lines: ls, size } = fitText(text, F_MONO, px(44), px(32), maxW, 3);
  const shown = typedAt(frame, rawText, text.length);
  const done = typingEnds(rawText);
  const lineH = size * 1.42;
  const textW = Math.max(...ls.map((l) => measure(l, F_MONO))) * size;
  const padX = 38 * u;
  const promptW = size * 1.2;
  const cardW = Math.max(520 * u, textW + promptW + padX * 2 + size * 1.1);
  const headH = px(56);
  const cardH = headH + ls.length * lineH + 44 * u;
  const pin = ramp(frame, 0, 14);
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="linear-gradient(90deg, rgba(0,0,0,.42) 0%, rgba(0,0,0,.22) 45%, rgba(0,0,0,0) 70%)" />
      <div style={{ position: "absolute", left: 120 * u, top: height * 0.5 - cardH / 2, width: cardW, height: cardH,
        opacity: pin, transform: `translateY(${((1 - pin) * 26 * u + out * 16 * u).toFixed(2)}px) scale(${(0.97 + 0.03 * pin).toFixed(4)})`,
        transformOrigin: "left center", borderRadius: 18 * u, overflow: "hidden",
        background: "rgba(13,16,22,.72)", backdropFilter: "blur(18px) saturate(1.15)", WebkitBackdropFilter: "blur(18px) saturate(1.15)",
        border: "1px solid rgba(255,255,255,.14)", boxShadow: `0 ${24 * u}px ${60 * u}px rgba(0,0,0,.45)` }}>
        <div style={{ height: headH, display: "flex", alignItems: "center", gap: 12 * u, padding: `0 ${padX}px`,
          borderBottom: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.035)" }}>
          {["#ff5f57", "#febc2e", "#28c840"].map((c, i) => (
            <div key={c} style={{ width: 14 * u, height: 14 * u, borderRadius: "50%", background: c,
              opacity: 0.9 * ramp(frame, 3 + i * 2, 8) }} />
          ))}
          <div style={{ marginLeft: 14 * u, fontFamily: MONO, fontWeight: 500, fontSize: px(28), letterSpacing: "0.12em",
            color: "rgba(232,237,242,.62)", opacity: ramp(frame, 6, 10) }}>{label}</div>
        </div>
        <div style={{ display: "flex", padding: `${22 * u}px ${padX}px`, fontFamily: MONO, fontWeight: 500,
          fontSize: size, lineHeight: `${lineH}px`, color: "#E8EDF2" }}>
          <div style={{ width: promptW, color: hot, fontWeight: 700, flex: "none" }}>{">"}</div>
          <div>
            <TypedLines lines={ls} shown={shown} caret={frame < done + 40} caretColor={hot} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-word-by-word
/**
 * A centred kinetic caption: the words land one at a time (a small rise and
 * settle), the key word in the accent with a soft glow.
 */
const EdWordByWord: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames: dur } = useVideoConfig();
  const px = usePx();
  const out = useOut();
  const text = str(overlay.text);
  if (!text) return null;
  const hot = vivid(accent);
  const keys = keyWords(text, overlay.highlight);
  // Big, outlined, no dark pool behind (the owner: bold white text with a black stroke).
  const { lines: ls, size } = fitText(text.toUpperCase(), F_LABEL, px(120), px(72), width * 0.78, 2, 0.01);
  const sw = Math.max(5 * (width / 1920), Math.min(13 * (width / 1920), size * 0.1));
  const total = ls.reduce((a, l) => a + l.split(" ").length, 0);
  const step = Math.max(2, Math.min(5, Math.floor((Math.min(dur, 120) * 0.45) / Math.max(1, total))));
  let idx = 0;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 62% 34% at 50% 58%, rgba(0,0,0,.22) 0%, rgba(0,0,0,.1) 55%, rgba(0,0,0,0) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", paddingTop: height * 0.1 }}>
        {ls.map((line, i) => (
          <div key={i} style={{ display: "flex", gap: size * 0.22, fontFamily: LABEL, fontWeight: 800, fontSize: size,
            lineHeight: 1.04, color: "#fff", letterSpacing: "0.01em", WebkitTextStroke: `${sw.toFixed(2)}px #000`,
            paintOrder: "stroke fill" } as React.CSSProperties}>
            {line.split(" ").map((w, j) => {
              const at = 3 + idx * step;
              idx += 1;
              const p = ramp(frame, at, 9, softBack);
              const o = ramp(frame, at, 4, Easing.linear);
              const isKey = keys.has(norm(w));
              return (
                <span key={j} style={{ display: "inline-block", opacity: o * (1 - out * 0.4),
                  transform: `translateY(${((1 - p) * size * 0.34 - out * size * 0.2).toFixed(2)}px) scale(${(0.86 + 0.14 * p).toFixed(4)})`,
                  filter: p < 0.98 ? `blur(${((1 - Math.min(1, p)) * 6).toFixed(2)}px)` : undefined,
                  color: isKey ? hot : "#fff",
                  // (no coloured glow round the key word: it smudged on busy footage - 2026-10-05)
                  textShadow: "0 4px 6px rgba(0,0,0,.35), 0 10px 30px rgba(0,0,0,.5)" }}>{w}</span>
              );
            })}
          </div>
        ))}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ed-marker-highlight
/**
 * A clean white paper strip, low-left, dark ink; a translucent yellow
 * highlighter sweeps across the key words in reading order (no underline, no red).
 */
const EdMarkerHighlight: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text);
  if (!text) return null;
  const keys = keyWords(text, overlay.highlight, true);
  const { lines: ls, size } = fitText(text, F_INTER, px(52), px(38), width * 0.5, 3);
  const pad = 34 * u;
  const lineH = size * 1.3;
  const textW = Math.max(...ls.map((l) => measure(l, F_INTER))) * size;
  // Key words in reading order, each with its share of the sweep.
  const order: string[] = [];
  ls.forEach((l, i) => l.split(" ").forEach((w, j) => {
    if (keys.has(norm(w))) order.push(`${i}:${j}`);
  }));
  const sweepAt = 16;
  const per = order.length ? Math.max(6, Math.round(16 / order.length)) : 0;
  const pin = ramp(frame, 0, 14);
  const tilt = interpolate(pin, [0, 1], [-3.2, -1.1]);
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <div style={{ position: "absolute", left: 120 * u, bottom: 190 * u, background: PAPER, padding: `${pad * 0.7}px ${pad}px`,
        borderRadius: 6 * u, boxShadow: `0 ${16 * u}px ${40 * u}px rgba(0,0,0,.38), 0 ${2 * u}px ${4 * u}px rgba(0,0,0,.2)`,
        opacity: ramp(frame, 0, 6),
        transform: `translateY(${((1 - pin) * 40 * u + out * 30 * u).toFixed(2)}px) rotate(${(tilt - out * 1.5).toFixed(3)}deg)`,
        transformOrigin: "left bottom", minWidth: textW * 0.6 }}>
        {ls.map((l, i) => (
          <div key={i} style={{ fontFamily: INTER, fontWeight: 700, fontSize: size, lineHeight: `${lineH}px`, color: INK,
            whiteSpace: "pre" }}>
            {l.split(" ").map((w, j, arr) => {
              const k = order.indexOf(`${i}:${j}`);
              const nextKey = order.indexOf(`${i}:${j + 1}`) >= 0;
              const p = k >= 0 ? ramp(frame, sweepAt + k * per, per + 2, inOut) : 0;
              return (
                <React.Fragment key={j}>
                  <span style={{ position: "relative", display: "inline-block" }}>
                    {k >= 0 ? (
                      <span style={{ position: "absolute", left: "-0.1em", right: nextKey ? "-0.36em" : "-0.1em", top: "0.2em",
                        bottom: "0.04em", background: "rgba(255,221,64,.9)", borderRadius: "0.14em 0.3em 0.2em 0.26em",
                        transform: `scaleX(${p.toFixed(4)}) skewX(-6deg)`, transformOrigin: "left center" }} />
                    ) : null}
                    <span style={{ position: "relative" }}>{w}</span>
                  </span>
                  {j < arr.length - 1 ? " " : null}
                </React.Fragment>
              );
            })}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-blur-in
/**
 * A cinematic letter-spaced title: letters come out of a blur from the centre
 * outward while the tracking tightens; a thin rule grows under it, an
 * optional small line (label/subtitle) fades in beneath.
 */
const EdBlurIn: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const sub = (str(overlay.label) || str(overlay.subtitle)).toUpperCase();
  const words = text.split(" ").length;
  const track = 0.16;
  const { lines: ls, size } = fitText(text, F_NARROW, px(words <= 4 ? 110 : 80), px(58), width * 0.74, 2, track);
  const widest = Math.max(...ls.map((l) => measure(l, F_NARROW, track))) * size;
  const n = Math.max(...ls.map((l) => l.length));
  const extra = Math.max(0, Math.min(0.5, (width * 0.94 - widest) / Math.max(1, n * size)));
  const t = ramp(frame, 0, 28, expoOut);
  const spacing = track + extra * (1 - t);
  const rule = ramp(frame, 12, 20, inOut);
  const tail = ramp(frame, 18, 14);
  return (
    <AbsoluteFill style={{ opacity: 1 - out, filter: out > 0.01 ? `blur(${(out * 8).toFixed(2)}px)` : undefined }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 64% 42% at 50% 50%, rgba(0,0,0,.62) 0%, rgba(0,0,0,.36) 60%, rgba(0,0,0,.12) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
        {ls.map((line, li) => {
          const chars = Array.from(line);
          const mid = (chars.length - 1) / 2;
          return (
            <div key={li} style={{ fontFamily: NARROW, fontWeight: 500, fontSize: size, lineHeight: 1.12, color: "#fff",
              letterSpacing: `${spacing.toFixed(4)}em`, marginRight: `-${spacing.toFixed(4)}em`, whiteSpace: "pre",
              textShadow: "0 4px 26px rgba(0,0,0,.5)" }}>
              {chars.map((c, i) => {
                const at = 1 + Math.abs(i - mid) * (10 / Math.max(1, mid)) * 0.9 + li * 3;
                const p = ramp(frame, at, 16, expoOut);
                return (
                  <span key={i} style={{ opacity: p, filter: p < 0.99 ? `blur(${((1 - p) * 14 * u).toFixed(2)}px)` : undefined }}>{c}</span>
                );
              })}
            </div>
          );
        })}
        <div style={{ width: widest * 0.5 * rule, height: Math.max(2, 2 * u), background: "rgba(255,255,255,.85)",
          marginTop: size * 0.22 }} />
        {sub ? (
          <div style={{ marginTop: size * 0.22, fontFamily: INTER, fontWeight: 700, fontSize: px(30), letterSpacing: "0.32em",
            marginRight: "-0.32em", color: "rgba(255,255,255,.86)", opacity: tail,
            transform: `translateY(${((1 - tail) * 10 * u).toFixed(2)}px)` }}>{sub}</div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ed-split-reveal
/** Split a line into two halves of similar length (by words). */
const halves = (text: string): [string, string] => {
  const words = text.split(" ").filter(Boolean);
  if (words.length < 2) return [text, ""];
  let best = 1;
  let bestD = Infinity;
  for (let i = 1; i < words.length; i++) {
    const d = Math.abs(words.slice(0, i).join(" ").length - words.slice(i).join(" ").length);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return [words.slice(0, best).join(" ").replace(/[,;:]+$/, ""), words.slice(best).join(" ")];
};

/**
 * Two lines slide in from opposite sides behind their masks and meet; a short
 * accent bar grows between them. They slide back out the way they came.
 */
const EdSplitReveal: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const [a, b0] = halves(text);
  const b = b0 || str(overlay.label).toUpperCase();
  const hot = vivid(accent);
  const maxW = width * 0.76;
  const fa = fitText(a, F_LABEL, px(96), px(56), maxW, 1, 0.02, false);
  const fb = b ? fitText(b, F_LABEL, px(96), px(56), maxW, 1, 0.02, false) : { lines: [], size: fa.size };
  const size = Math.min(fa.size, fb.size);
  const la = fitText(a, F_LABEL, size, size * 0.8, maxW, 2, 0.02).lines;
  const lb = b ? fitText(b, F_LABEL, size, size * 0.8, maxW, 2, 0.02).lines : [];
  const pa = ramp(frame, 2, 14, expoOut);
  const pb = ramp(frame, 4, 14, expoOut);
  const bar = ramp(frame, 6, 12, inOut);
  const line = (ls: string[], p: number, dir: number, weight: number, color: string) => (
    <div style={{ overflow: "hidden", padding: `0 ${10 * u}px`, paddingBottom: "0.04em" }}>
      <div style={{ transform: `translateX(${(dir * ((1 - p) * 104 + out * 104)).toFixed(3)}%)` }}>
        {ls.map((l, i) => (
          <div key={i} style={{ fontFamily: LABEL, fontWeight: weight, fontSize: size, lineHeight: 1.02, letterSpacing: "0.02em",
            color, textAlign: "center", whiteSpace: "pre", textShadow: "0 6px 24px rgba(0,0,0,.4)" }}>{l}</div>
        ))}
      </div>
    </div>
  );
  return (
    <AbsoluteFill style={{ opacity: 1 - out * 0.6 }}>
      <Shade ov={overlay} out={out}
        background="linear-gradient(180deg, rgba(0,0,0,0) 20%, rgba(0,0,0,.58) 40%, rgba(0,0,0,.58) 60%, rgba(0,0,0,0) 80%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
        {line(la, pa, -1, 800, "#fff")}
        <div style={{ width: 120 * u, height: Math.max(4, 7 * u), background: hot, margin: `${size * 0.14}px 0`,
          transform: `scaleX(${(bar * (1 - out)).toFixed(4)})`, borderRadius: 3 * u }} />
        {lb.length ? line(lb, pb, 1, 700, "rgba(255,255,255,.94)") : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ed-box-stack
/**
 * A title as 2-4 stack units of similar length ("THE WELLS" / "RAN DRY"):
 * about one unit per 9 characters, split so the longest unit is as short as
 * possible.
 */
const stackUnits = (text: string): string[] => {
  const words = text.split(" ").filter(Boolean);
  if (words.length <= 1) return words;
  const n = Math.max(2, Math.min(4, words.length, Math.round(text.length / 9)));
  const w = (x: string) => x.length;
  let lo = Math.max(...words.map(w));
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (greedy(words, mid, w).length <= n) hi = mid;
    else lo = mid + 1;
  }
  return greedy(words, lo, w);
};

/**
 * 2-4 words in solid boxes, stacked with an offset: a warm yellow box with
 * black type, then a white box with black type, popping in with an overshoot.
 */
const EdBoxStack: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames: dur } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const units = stackUnits(text);
  const words = text.split(" ").length;
  const base = words <= 4 ? px(104) : units.length >= 4 ? px(74) : px(86);
  const maxW = width * 0.58;
  const size = Math.max(px(52), Math.min(base, ...units.map((s) => maxW / Math.max(0.01, measure(s, F_LABEL, 0.01)))));
  const boxH = size * 1.14;
  const stackH = units.length * boxH;
  const top = height * 0.5 - stackH / 2;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 120 * u, top }}>
        {units.map((unit, i) => {
          const at = 2 + i * 5;
          const p = ramp(frame, at, 12, backOut);
          const o = ramp(frame, at, 3, Easing.linear);
          const x = ramp(frame, dur - EXIT + (units.length - 1 - i) * 2, 9, expoIn);
          const yellow = i % 2 === 0;
          return (
            <div key={i} style={{ marginLeft: i * 40 * u, marginTop: i ? -2 * u : 0, display: "flex" }}>
              <div style={{ background: yellow ? YELLOW : "#ffffff", color: INK, fontFamily: LABEL, fontWeight: 800,
                fontSize: size, lineHeight: `${boxH}px`, height: boxH, padding: `0 ${size * 0.2}px`, letterSpacing: "0.01em",
                whiteSpace: "pre", opacity: o * (1 - x), boxShadow: `0 ${10 * u}px ${26 * u}px rgba(0,0,0,.3)`,
                transform: `scale(${Math.max(0, 0.55 + 0.45 * p).toFixed(4)}, ${Math.max(0, (0.55 + 0.45 * p) * (1 - x)).toFixed(4)}) rotate(${((1 - p) * (yellow ? -4 : 4)).toFixed(3)}deg)`,
                transformOrigin: "left center" }}>{unit}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-news-clipping
const NOISE = `url("data:image/svg+xml;utf8,${encodeURIComponent(
  "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(#n)' opacity='0.1'/></svg>",
)}")`;

/** A torn top and bottom edge as a clip-path polygon (deterministic from the seed). */
const tornEdge = (seed: number): string => {
  const n = 34;
  const top: string[] = [];
  const bot: string[] = [];
  for (let i = 0; i <= n; i++) {
    const x = (i / n) * 100;
    top.push(`${x.toFixed(2)}% ${(0.3 + rnd(seed + i) * 2.2).toFixed(2)}%`);
    bot.push(`${(100 - x).toFixed(2)}% ${(99.7 - rnd(seed + 97 + i) * 2.6).toFixed(2)}%`);
  }
  return `polygon(${[...top, ...bot].join(", ")})`;
};

/**
 * A newspaper headline clipping: serif headline on textured newsprint with a
 * double rule and a small dateline, torn top and bottom edges; it slides in
 * rotated from below and settles at a slight angle.
 */
const EdNewsClipping: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text);
  if (!text) return null;
  const dateline = (str(overlay.label) || str(overlay.subtitle)).toUpperCase().slice(0, 48);
  const { lines: ls, size } = fitText(text, F_SERIF_HEAVY, px(66), px(44), width * 0.44, 3);
  const textW = Math.max(...ls.map((l) => measure(l, F_SERIF_HEAVY))) * size;
  const w = Math.max(560 * u, textW + 110 * u);
  const seed = seedOf(text);
  const p = ramp(frame, 0, 16, softBack);
  const rot = interpolate(p, [0, 1], [9, -2.2]);
  const x = (1 - p) * 180 * u;
  const y = (1 - p) * 320 * u + out * 60 * u;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 50% 50% at 50% 50%, rgba(0,0,0,.46) 0%, rgba(0,0,0,.26) 70%, rgba(0,0,0,.14) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ filter: `drop-shadow(0 ${18 * u}px ${24 * u}px rgba(0,0,0,.45))`, opacity: ramp(frame, 0, 5),
          transform: `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) rotate(${(rot + out * 3).toFixed(3)}deg)` }}>
          <div style={{ width: w, clipPath: tornEdge(seed), backgroundColor: "#EFE9DC", backgroundImage: NOISE,
            padding: `${44 * u}px ${55 * u}px ${48 * u}px` }}>
            <div style={{ borderTop: `${3 * u}px solid #1d1b18`, borderBottom: `${1 * u}px solid #1d1b18`, height: 5 * u,
              marginBottom: 14 * u }} />
            {dateline ? (
              <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: px(28), letterSpacing: "0.14em", color: "#5a544b",
                marginBottom: 10 * u }}>{dateline}</div>
            ) : null}
            {ls.map((l, i) => (
              <div key={i} style={{ fontFamily: PLAYFAIR_HEAVY, fontWeight: 800, fontSize: size, lineHeight: 1.1, color: "#15130f",
                whiteSpace: "pre" }}>{l}</div>
            ))}
            <div style={{ display: "flex", gap: 14 * u, marginTop: 20 * u }}>
              {[0.9, 0.72, 0.8].map((f, i) => (
                <div key={i} style={{ flex: 1, height: 7 * u, background: "rgba(30,27,23,.16)", width: `${f * 100}%` }} />
              ))}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ed-glass-caption
/**
 * A frosted glass pill bottom-centre with a small info icon in the accent and
 * the line of text revealed left to right: a modern caption for a fact.
 */
const EdGlassCaption: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text);
  if (!text) return null;
  const hot = vivid(accent);
  const { lines: ls, size } = fitText(text, F_INTER, px(44), px(34), width * 0.6, 2);
  const icon = size * 1.12;
  const p = ramp(frame, 2, 14, expoOut);
  const ip = ramp(frame, 7, 12, backOut);
  const reveal = ramp(frame, 8, 16, inOut);
  const two = ls.length > 1;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 170 * u, display: "flex", justifyContent: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 22 * u, padding: `${18 * u}px ${40 * u}px ${18 * u}px ${20 * u}px`,
          borderRadius: two ? 34 * u : 999, background: "rgba(22,24,30,.5)", border: "1px solid rgba(255,255,255,.2)",
          backdropFilter: "blur(16px) saturate(1.2)", WebkitBackdropFilter: "blur(16px) saturate(1.2)",
          boxShadow: `0 ${14 * u}px ${40 * u}px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.12)`,
          opacity: p, filter: p < 0.98 ? `blur(${((1 - p) * 8).toFixed(2)}px)` : undefined,
          transform: `translateY(${((1 - p) * 34 * u + out * 20 * u).toFixed(2)}px) scale(${(0.95 + 0.05 * p).toFixed(4)})` }}>
          <svg width={icon} height={icon} viewBox="0 0 40 40" style={{ flex: "none", transform: `scale(${ip.toFixed(4)})` }}>
            <circle cx="20" cy="20" r="19" fill={hot} />
            <circle cx="20" cy="12.4" r="2.6" fill={readableOn(hot)} />
            <rect x="17.6" y="17" width="4.8" height="13" rx="2.2" fill={readableOn(hot)} />
          </svg>
          <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: size, lineHeight: 1.26, color: "#fff",
            WebkitMaskImage: `linear-gradient(90deg, #000 ${(reveal * 120 - 20).toFixed(1)}%, transparent ${(reveal * 120).toFixed(1)}%)`,
            maskImage: `linear-gradient(90deg, #000 ${(reveal * 120 - 20).toFixed(1)}%, transparent ${(reveal * 120).toFixed(1)}%)` }}>
            {ls.map((l, i) => <div key={i} style={{ whiteSpace: "pre" }}>{l}</div>)}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-outline-fill
/**
 * A big outlined title that fills with colour left to right behind a soft
 * glowing front, then holds; the fill lands on frame 36 (sfx_at).
 */
const EdOutlineFill: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const out = useOut();
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const hot = vivid(accent);
  const words = text.split(" ").length;
  const base = words <= 2 ? px(136) : words <= 4 ? px(118) : px(92);
  const { lines: ls, size } = fitText(text, F_DISPLAY, base, px(64), width * 0.78, words <= 4 ? 2 : 3, 0.03);
  const fill = ramp(frame, 8, 28, inOut);
  const pin = ramp(frame, 0, 12);
  const fillColor = mix(hot, "#ffffff", 0.18);
  const glint = fill > 0.01 && fill < 0.99;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 60% 40% at 50% 50%, rgba(0,0,0,.66) 0%, rgba(0,0,0,.38) 58%, rgba(0,0,0,.1) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center",
        transform: `scale(${(1.05 - 0.05 * pin + out * 0.04).toFixed(4)})`, opacity: pin }}>
        <div style={{ position: "relative", fontFamily: DISPLAY, fontSize: size, lineHeight: 1, letterSpacing: "0.03em",
          textAlign: "center" }}>
          <div style={{ color: "transparent", WebkitTextStroke: `${Math.max(1.5, size * 0.022).toFixed(2)}px rgba(255,255,255,.92)` }}>
            {ls.map((l, i) => <div key={i} style={{ whiteSpace: "pre" }}>{l}</div>)}
          </div>
          <div style={{ position: "absolute", inset: 0, color: fillColor, clipPath: `inset(-5% ${((1 - fill) * 100).toFixed(3)}% -5% -1%)`,
            textShadow: `0 ${size * 0.05}px ${size * 0.3}px rgba(0,0,0,.35)` }}>
            {ls.map((l, i) => <div key={i} style={{ whiteSpace: "pre" }}>{l}</div>)}
          </div>
          {glint ? (
            <div style={{ position: "absolute", top: "-4%", bottom: "-4%", left: `${(fill * 100).toFixed(3)}%`, width: size * 0.12,
              transform: "translateX(-50%)", background: `linear-gradient(90deg, transparent, ${alpha(fillColor, 0.75)}, transparent)`,
              filter: `blur(${(size * 0.04).toFixed(2)}px)` }} />
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ed-side-note
/**
 * A small editor's annotation in handwriting, upper right, written on left to
 * right, with a hand-drawn arrow curving down into the frame.
 */
const EdSideNote: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text);
  if (!text) return null;
  const hot = vivid(accent);
  const { lines: ls, size } = fitText(text, F_HAND, px(66), px(48), width * 0.3, 3);
  const textW = Math.max(...ls.map((l) => measure(l, F_HAND))) * size;
  const lineH = size * 1.08;
  const right = 150 * u;
  const top = 150 * u;
  const draw = ramp(frame, 4, 14, inOut);
  const chars = ls.reduce((a, l) => a + l.length, 0);
  const write = ramp(frame, 8, Math.max(12, Math.min(26, chars * 0.7)), Easing.linear);
  // The arrow: from under the note's left edge, curving down-left into the frame.
  const aw = 300 * u;
  const ah = 230 * u;
  const x0 = aw - 20 * u;
  const y0 = 16 * u;
  const x3 = 26 * u;
  const y3 = ah - 22 * u;
  const c1 = [aw * 0.62, 10 * u];
  const c2 = [aw * 0.18, ah * 0.3];
  const dx = x3 - c2[0];
  const dy = y3 - c2[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const head = 30 * u;
  const rot = (a: number): [number, number] => [-(ux * Math.cos(a) - uy * Math.sin(a)) * head, -(ux * Math.sin(a) + uy * Math.cos(a)) * head];
  const h1 = rot(0.5);
  const h2 = rot(-0.5);
  const headP = ramp(frame, 15, 6, inOut);
  const stroke = Math.max(4, 7 * u);
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      {overlay.fullFrame ? null : (
        <AbsoluteFill style={{ opacity: ramp(frame, 0, 12),
          background: "radial-gradient(ellipse 34% 30% at 80% 22%, rgba(0,0,0,.5) 0%, rgba(0,0,0,.26) 55%, rgba(0,0,0,0) 100%)" }} />
      )}
      <div style={{ position: "absolute", right, top, width: textW + 10 * u }}>
        <div style={{ fontFamily: HAND, fontWeight: 700, fontSize: size, lineHeight: `${lineH}px`, color: "#fff",
          textShadow: "0 2px 10px rgba(0,0,0,.75), 0 0 3px rgba(0,0,0,.6)" }}>
          {ls.map((l, i) => {
            const before = ls.slice(0, i).reduce((a, x) => a + x.length, 0) / Math.max(1, chars);
            const share = l.length / Math.max(1, chars);
            const lp = Math.max(0, Math.min(1, (write - before) / Math.max(0.01, share)));
            return (
              <div key={i} style={{ whiteSpace: "pre",
                WebkitMaskImage: `linear-gradient(90deg, #000 ${(lp * 110 - 10).toFixed(1)}%, transparent ${(lp * 110).toFixed(1)}%)`,
                maskImage: `linear-gradient(90deg, #000 ${(lp * 110 - 10).toFixed(1)}%, transparent ${(lp * 110).toFixed(1)}%)` }}>{l}</div>
            );
          })}
        </div>
        <svg width={aw} height={ah} style={{ position: "absolute", left: -aw + 40 * u, top: ls.length * lineH - 6 * u, overflow: "visible",
          filter: "drop-shadow(0 2px 5px rgba(0,0,0,.7))" }}>
          <path d={`M ${x0} ${y0} C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${x3} ${y3}`} fill="none" stroke={hot}
            strokeWidth={stroke} strokeLinecap="round" pathLength={1} strokeDasharray="1" strokeDashoffset={(1 - draw).toFixed(4)} />
          <path d={`M ${x3 + h1[0] * headP} ${y3 + h1[1] * headP} L ${x3} ${y3} L ${x3 + h2[0] * headP} ${y3 + h2[1] * headP}`}
            fill="none" stroke={hot} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" opacity={headP > 0.02 ? 1 : 0} />
        </svg>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-quote-type
const QUOTES = /^[\s"'“”‘’«»]+|[\s"'“”‘’«»]+$/g;

/**
 * A serif quotation typed letter by letter (the typing contract), large soft
 * quote marks behind it, then an accent dash and the attribution (label).
 */
const EdQuoteType: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const rawText = raw(overlay.text);
  const full = str(overlay.text);
  const lead = (/^[\s"'“”‘’«»]+/.exec(full) || [""])[0].length;
  const text = full.replace(QUOTES, "");
  if (!text) return null;
  const who = (str(overlay.label) || str(overlay.subtitle)).toUpperCase().slice(0, 60);
  const hot = vivid(accent);
  // Heavy serif with a black outline (the owner: bold text that reads on any footage), never a thin light serif.
  let fit = fitText(text, F_SERIF_HEAVY, px(70), px(48), width * 0.64, 3);
  if (/…$/.test(fit.lines[fit.lines.length - 1] || "")) fit = fitText(text, F_SERIF_HEAVY, px(48), px(42), width * 0.68, 4);
  const { lines: ls, size } = fit;
  const shown = Math.max(0, Math.min(text.length, typedAt(frame, rawText, full.length) - lead));
  const done = typingEnds(rawText);
  const lineH = size * 1.26;
  const sw = (s2: number) => Math.max(4.5 * u, Math.min(11 * u, s2 * 0.09));
  const blockH = ls.length * lineH;
  const left = 170 * u;
  const top = height * 0.5 - blockH / 2 - (who ? 30 * u : 0);
  const marks = ramp(frame, 0, 16);
  const tail = ramp(frame, done + 4, 14);
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="linear-gradient(90deg, rgba(0,0,0,.5) 0%, rgba(0,0,0,.34) 40%, rgba(0,0,0,.08) 75%, rgba(0,0,0,0) 100%)" />
      <div style={{ position: "absolute", left: left - 70 * u, top: top - 150 * u, fontFamily: PLAYFAIR_HEAVY, fontWeight: 800,
        fontSize: 300 * u, lineHeight: 1, color: hot, opacity: marks, WebkitTextStroke: `${(6 * u).toFixed(2)}px #000`,
        paintOrder: "stroke fill", textShadow: `0 ${10 * u}px ${30 * u}px rgba(0,0,0,.45)`,
        transform: `translateY(${((1 - marks) * 30 * u).toFixed(2)}px) scale(${(0.8 + 0.2 * marks).toFixed(4)})` } as React.CSSProperties}>“</div>
      <div style={{ position: "absolute", left, top, fontFamily: PLAYFAIR_HEAVY, fontWeight: 800, fontSize: size, lineHeight: `${lineH}px`,
        color: "#fff", WebkitTextStroke: `${sw(size).toFixed(2)}px #000`, paintOrder: "stroke fill",
        textShadow: `0 ${3 * u}px ${4 * u}px rgba(0,0,0,.35), 0 ${8 * u}px ${26 * u}px rgba(0,0,0,.5)` } as React.CSSProperties}>
        <TypedLines lines={ls} shown={shown} caret={frame < done + 24} caretColor={hot} />
        {who ? (
          <div style={{ display: "flex", alignItems: "center", gap: 18 * u, marginTop: 26 * u, opacity: tail,
            transform: `translateX(${((1 - tail) * -16 * u).toFixed(2)}px)` }}>
            <div style={{ width: 56 * u, height: Math.max(4, 8 * u), background: hot, borderRadius: 2 * u,
              boxShadow: `0 0 0 ${2.5 * u}px #000` }} />
            <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(44), letterSpacing: "0.1em", color: "#fff",
              WebkitTextStroke: `${sw(px(44)).toFixed(2)}px #000`, paintOrder: "stroke fill" } as React.CSSProperties}>{who}</div>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ed-question
/**
 * The narration's question in large clean type, rising word by word, then a
 * big question mark drawn beside it in the accent; its dot lands on frame 26
 * (sfx_at, the ding).
 */
const EdQuestion: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text).replace(/[?？]+\s*$/, "").trim();
  if (!text) return null;
  const hot = vivid(accent);
  const { lines: ls, size } = fitText(text, F_INTER_HEAVY, px(70), px(46), width * 0.56, 3);
  const total = ls.reduce((a, l) => a + l.split(" ").length, 0);
  const step = total > 1 ? Math.min(3, 10 / (total - 1)) : 0;
  const lineH = size * 1.14;
  const qh = Math.max(size * 2.6, ls.length * lineH * 1.05);
  const qw = qh * 0.62;
  const draw = ramp(frame, 12, 13, inOut);
  const dot = ramp(frame, 24, 8, backOut);
  let idx = 0;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 62% 42% at 50% 50%, rgba(0,0,0,.64) 0%, rgba(0,0,0,.38) 58%, rgba(0,0,0,.1) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center",
        transform: `translateY(${(out * -16 * u).toFixed(2)}px)` }}>
        <div style={{ display: "flex", alignItems: "center", gap: size * 0.45 }}>
          <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: `${lineH}px`, color: "#fff" }}>
            {ls.map((l, i) => (
              <div key={i} style={{ display: "flex", gap: size * 0.25 }}>
                {l.split(" ").map((w, j) => {
                  const at = 2 + idx * step;
                  idx += 1;
                  const p = ramp(frame, at, 12, expoOut);
                  return (
                    <span key={j} style={{ display: "inline-block", overflow: "hidden", paddingBottom: "0.06em" }}>
                      <span style={{ display: "inline-block", transform: `translateY(${((1 - p) * 105).toFixed(2)}%)`,
                        textShadow: "0 4px 20px rgba(0,0,0,.5)" }}>{w}</span>
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
          <svg width={qw} height={qh} viewBox="0 0 100 160" style={{ flex: "none", overflow: "visible",
            filter: `drop-shadow(0 4px 14px rgba(0,0,0,.45)) drop-shadow(0 0 18px ${alpha(hot, 0.35)})` }}>
            <path d="M 18 46 C 18 12, 82 6, 82 44 C 82 70, 50 70, 50 100 L 50 110" fill="none" stroke={hot} strokeWidth={21}
              strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1"
              strokeDashoffset={(1 - draw).toFixed(4)} />
            <circle cx="50" cy="142" r={13 * dot} fill={hot} />
          </svg>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ed-alert-bar
const SEVERE = /\b(EMERGENCY|EVACUAT\w*|DANGER\w*|DEADLY|FATAL|LIFE[- ]THREATENING|EXTREME|CATASTROPH\w*|DEATH|KILLED)\b/i;

/**
 * A clean warning bar, upper left: an amber icon cell (red for
 * life-threatening words) drops in and its triangle pulses, the dark bar
 * wipes out of it and the text slides in behind a mask.
 */
const EdAlertBar: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, durationInFrames: dur } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const kicker = str(overlay.label).toUpperCase().slice(0, 30);
  const tone = SEVERE.test(text) ? "#E5202A" : "#FFB020";
  const { lines: ls, size } = fitText(text, F_INTER_HEAVY, px(46), px(34), width * 0.6, 2, 0.03);
  const lineH = size * 1.2;
  const barH = Math.max(px(96), ls.length * lineH + 40 * u);
  const cell = barH;
  const textW = Math.max(...ls.map((l) => measure(l, F_INTER_HEAVY, 0.03))) * size;
  const barW = textW + 76 * u;
  const drop = ramp(frame, 2, 9, backOut);
  const wipe = ramp(frame, 8, 12, expoOut);
  const slide = ramp(frame, 11, 12, expoOut);
  const pulse = frame > 12 ? 0.5 - 0.5 * Math.cos(((frame - 12) / 26) * Math.PI * 2) : 0;
  const ring = frame > 10 ? ((frame - 10) % 26) / 26 : 0;
  const x = ramp(frame, dur - EXIT, EXIT, expoIn);
  return (
    <AbsoluteFill style={{ opacity: 1 - out * 0.3 }}>
      <div style={{ position: "absolute", left: 110 * u, top: 120 * u }}>
        {kicker ? (
          <div style={{ display: "inline-block", fontFamily: INTER, fontWeight: 800, fontSize: px(28), letterSpacing: "0.16em",
            color: readableOn(tone), background: tone, padding: `${4 * u}px ${14 * u}px`, marginBottom: 8 * u,
            opacity: ramp(frame, 12, 10) * (1 - x), clipPath: `inset(0 ${((1 - ramp(frame, 12, 12, expoOut)) * 100).toFixed(2)}% 0 0)` }}>{kicker}</div>
        ) : null}
        <div style={{ display: "flex", height: barH, clipPath: `inset(-40% ${(x * 100).toFixed(2)}% -40% 0)` }}>
          <div style={{ width: cell, height: barH, background: tone, position: "relative", flex: "none", zIndex: 2,
            transform: `translateY(${((1 - drop) * -40 * u).toFixed(2)}px) scale(${(0.8 + 0.2 * drop).toFixed(4)})`,
            opacity: ramp(frame, 2, 4, Easing.linear), boxShadow: `0 ${10 * u}px ${30 * u}px rgba(0,0,0,.35)` }}>
            <div style={{ position: "absolute", inset: 0, border: `${3 * u}px solid ${tone}`, opacity: (1 - ring) * 0.8,
              transform: `scale(${(1 + ring * 0.5).toFixed(4)})` }} />
            <svg viewBox="0 0 100 100" width={cell} height={cell} style={{ transform: `scale(${(1 + pulse * 0.07).toFixed(4)})` }}>
              <path d="M 50 18 L 84 78 L 16 78 Z" fill="none" stroke={INK} strokeWidth={8} strokeLinejoin="round" />
              <rect x="46" y="38" width="8" height="22" rx="3.5" fill={INK} />
              <circle cx="50" cy="68" r="4.6" fill={INK} />
            </svg>
          </div>
          <div style={{ width: barW, height: barH, background: "rgba(14,16,20,.9)", borderTop: `${Math.max(3, 4 * u)}px solid ${tone}`,
            boxSizing: "border-box", overflow: "hidden", clipPath: `inset(0 ${((1 - wipe) * 100).toFixed(2)}% 0 0)`,
            display: "flex", flexDirection: "column", justifyContent: "center", padding: `0 ${38 * u}px`,
            boxShadow: `0 ${10 * u}px ${30 * u}px rgba(0,0,0,.35)` }}>
            {ls.map((l, i) => (
              <div key={i} style={{ fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: `${lineH}px`, letterSpacing: "0.03em",
                color: "#fff", whiteSpace: "pre", opacity: slide,
                transform: `translateX(${((1 - slide) * -40 * u).toFixed(2)}px)` }}>{l}</div>
            ))}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "ed-type-clean": EdTypeClean,
  "ed-type-terminal": EdTypeTerminal,
  "ed-word-by-word": EdWordByWord,
  "ed-marker-highlight": EdMarkerHighlight,
  "ed-blur-in": EdBlurIn,
  "ed-split-reveal": EdSplitReveal,
  "ed-box-stack": EdBoxStack,
  "ed-news-clipping": EdNewsClipping,
  "ed-glass-caption": EdGlassCaption,
  "ed-outline-fill": EdOutlineFill,
  "ed-side-note": EdSideNote,
  "ed-quote-type": EdQuoteType,
  "ed-question": EdQuestion,
  "ed-alert-bar": EdAlertBar,
};
