import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { CINZEL, INTER_SEMI, SERIF_HEAVY, TYPEWRITER } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import { spokenToDigits } from "./numWords";

/**
 * PACK VR - the date, time and caption text rebuilt to match VidRush's
 * exports (the owner, 2026-10-01; reference boards in the QA scratchpad).
 * The owner's rules: a look sits in the SAME place every time (no corner
 * hopping), it shows only what the narration said (no computed weekday, no
 * extra day), clean faces that are not too big, sounds under the voice.
 *
 *   vr-date-hero      CENTRED      "23 September" over "2026": letters fade in left to right
 *                                  (blur 4 -> 0, 6 px rise, 1.2 frames apart), the year 6 frames
 *                                  later. theme "typewriter": white Courier Prime Bold, a crimson
 *                                  marker wipes in behind line 1; theme "serif": Cinzel caps on a
 *                                  full-width dark band, thin dashes either side.
 *   vr-time-card      TOP-LEFT     a rounded card (left 64, top 56 at 1080p) whose digits type in
 *                                  one every 3 frames; a black label strip drops in under it.
 *                                  Crimson striped + Courier (typewriter) or flat gold + Playfair 900 (serif).
 *   vr-caption-typed  BOTTOM-LEFT  "Parker Dam, 1938" types in cream Courier Prime (x 96, baseline 960),
 *                                  2 frames a letter, a thin cursor blinking after it.
 *   vr-year-line      CENTRED      a thin line, a glowing dot slides from its right end to the centre
 *                                  while the year under it counts from `total` (2026) to `value`.
 *
 * Every look schedules its own sound from its real frames (useLookSound;
 * the registry carries the same design for the planner): a soft whoosh on
 * the date's reveal and the marker's draw (typewriter only), the keys as
 * the time types, a clean typewriter under the caption, a gentle count and
 * one tick on the year's landing - levels from look_sounds.json's rules,
 * never louder than the dtx date looks.
 *
 * theme: "typewriter" / "red" / anything else -> the red typewriter look;
 * "serif" / "gold" -> the gold serif look. (The registry's theme enum has
 * no "typewriter"/"serif", so a planner that resolves through it passes
 * "red" / "gold"; a style pack whose theme is gold gets the serif look.)
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type CSS = React.CSSProperties;
type Theme = "typewriter" | "serif";

// ------------------------------------------------------------------ the faces (em, measured in Chrome)
/** cap: cap height; top: the cap top below the top of a line-height-1 box. */
type Metric = { cap: number; top: number };
const CP: Metric = { cap: 0.578, top: 0.1415 };      // Courier Prime Bold (every advance 0.6 em)
const CZ: Metric = { cap: 0.703, top: 0.099 };       // Cinzel 400
const PF: Metric = { cap: 0.719, top: 0.1965 };      // Playfair Display 700/900
const IN: Metric = { cap: 0.734, top: 0.13 };        // Inter 600
const CP_ADV = 0.6;
const CP_DESC = 0.203;                               // Courier Prime's descender ("p", "y")
/** A word space in the big typewriter date (Courier's own 0.6 em cell reads as a gap there). */
const CP_SPACE = 0.36;
/** A colon cell in typewriter figures ("9:08", not "9 : 08"): its 0.6 em cell taken in on both sides. */
const CP_COLON_IN = 0.13;
/** Cinzel 400 advances (em); caps only. */
const CZ_ADV: Record<string, number> = {
  A: 0.712, B: 0.586, C: 0.76, D: 0.807, E: 0.577, F: 0.541, G: 0.798, H: 0.813, I: 0.338, J: 0.324, K: 0.657,
  L: 0.562, M: 0.931, N: 0.841, O: 0.838, P: 0.577, Q: 0.837, R: 0.677, S: 0.475, T: 0.618, U: 0.785, V: 0.74,
  W: 0.982, X: 0.662, Y: 0.661, Z: 0.651, "0": 0.596, "1": 0.344, "2": 0.553, "3": 0.503, "4": 0.583, "5": 0.498,
  "6": 0.56, "7": 0.502, "8": 0.552, "9": 0.56, " ": 0.25, ".": 0.179, ",": 0.185, ":": 0.179, "'": 0.17, "-": 0.38,
  "–": 0.5, "—": 0.8, "/": 0.406, "&": 0.646,
};
const czEm = (s: string, track: number) => Array.from(s).reduce((a, c) => a + (CZ_ADV[c] ?? 0.66) + track, 0);

const WHITE = "#FFFFFF";
const WARM = "#F3EEE4";
const CREAM = "#EFE6D2";
const MARKER = "#D21F3C";
const CARD_RED = "#D7263D";
const CARD_RED_DARK = "#BD2136";      // 12 % darker
const CARD_GOLD = "#F2C94C";
const INK = "#141414";
const STRIP = "#0E0E0E";
const DASH = "rgba(226,172,104,.92)";

// ------------------------------------------------------------------ small helpers
const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeIn = (t: number) => t * t * t;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const inOf = (f: number, at: number, frames: number) => easeOut(clamp01((f - at) / Math.max(1, frames)));
const outOf = (f: number, at: number, frames: number) => easeIn(clamp01((f - at) / Math.max(1, frames)));

const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
/** Spoken numbers in digits ("September twenty-third" -> "September 23"), never throwing. */
const digits = (s: string): string => {
  try {
    return spokenToDigits(s).replace(/\s+/g, " ").trim();
  } catch {
    return s;
  }
};
/** At most n characters, cut at a word, never ending on a dangling small word or a comma ("..., BEFORE THE"). */
const SMALL_TAIL = /[\s,;:\-–—]+(?:the|a|an|of|in|at|on|and|or|to|for|by|with|from|before|after|near)?$/i;
const clip = (s: string, n: number) => {
  if (s.length <= n) return s;
  let cut = s.slice(0, n).replace(/\s+\S*$/, "").trim();
  for (let i = 0; i < 4 && SMALL_TAIL.test(cut); i++) cut = cut.replace(SMALL_TAIL, "").trim();
  return cut || s.slice(0, n);
};
/** "SEPTEMBER 23" -> "September 23", "23RD SEPT." -> "23rd Sept." */
const titleCase = (s: string) => s.toLowerCase().replace(/(^|[\s\-/(])([a-z])/g, (_m, a: string, b: string) => a + b.toUpperCase());
const num = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};
/** A whole year (1-9999) from a number, else null. */
const yearOf = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && n >= 1 && n < 10000 ? Math.round(n) : null;
};
const YEAR_RX = /\b(1[0-9]\d\d|20\d\d|2100)\b/;

export const themeOf = (ov: Overlay): Theme => {
  const t = str(ov.theme).toLowerCase();
  return t === "serif" || t === "gold" ? "serif" : "typewriter";
};

/** The base every look reads: frame, rate scale (30 fps = 1), size scale, frame scale, frame size, length. */
const useBase = () => {
  const f = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  return { f, S: fps / 30, k, kw: width / 1920, width, height, dur: durationInFrames };
};

/** The soft dark shadow: no stroke, no box. */
const shadow = (k: number, o = 0.55) =>
  `drop-shadow(0 ${(2 * k).toFixed(2)}px ${(6 * k).toFixed(2)}px rgba(0,0,0,${o})) `
  + `drop-shadow(0 ${(1 * k).toFixed(2)}px ${(1.5 * k).toFixed(2)}px rgba(0,0,0,${(o * 0.8).toFixed(2)}))`;

/**
 * One line of text in a box exactly its cap height tall, the caps filling
 * it (descenders hang below): boxes then line up on the caps, not on the
 * font's line metrics. `track` letter-spacing (em), its trailing space taken back.
 */
const CapLine: React.FC<{ font: string; m: Metric; size: number; weight: number; color?: string; track?: number;
  style?: CSS; inner?: CSS; children: React.ReactNode }> = ({ font, m, size, weight, color, track = 0, style, inner, children }) => (
  <div style={{ height: size * m.cap, whiteSpace: "pre", ...style }}>
    <div style={{ position: "relative", top: -size * m.top, fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1,
      letterSpacing: track ? `${track}em` : 0, marginRight: track ? `${-track}em` : undefined, color, ...inner }}>
      {children}
    </div>
  </div>
);

/**
 * A very light rough-ink edge for the typewriter face (VidRush's type is
 * slightly worn): a fixed turbulence displacing the glyph edges by at most
 * 0.6 px, the same on every frame so nothing shimmers.
 */
const useInk = (k: number): { id: string; node: React.ReactNode } => {
  const raw = React.useId();
  const id = `vr-ink-${raw.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const scale = Math.min(0.6, 0.6 * k);
  return {
    id,
    node: (
      <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
        <filter id={id} x="-2%" y="-10%" width="104%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency={0.75} numOctaves={2} seed={7} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={scale} xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
    ),
  };
};

/** A letter fading in: blur 4 -> 0 px, 6 px rise, over 8 frames (30 fps) from its start. */
const letterStyle = (f: number, start: number, S: number, k: number): CSS => {
  const p = inOf(f, start, 8 * S);
  const blur = (1 - p) * 4 * k;
  return { display: "inline-block", opacity: p, transform: p < 1 ? `translateY(${((1 - p) * 6 * k).toFixed(2)}px)` : undefined,
    filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined };
};

// ================================================================== vr-date-hero
/** Line 1 as said ("September 23" title case / "SEPTEMBER 23" caps), the year under it (subtitle, else a trailing year). */
export const heroPlan = (ov: Overlay, theme: Theme = themeOf(ov)) => {
  let main = digits(str(ov.text));
  let year = digits(str(ov.subtitle));
  const tail = /^(.*?\S)[,\s]+((?:1[0-9]|20)\d\d|2100)$/.exec(main);
  if (tail && (!year || year === tail[2])) {
    main = tail[1];
    year = tail[2];
  }
  main = clip(main.replace(/[,;:\s]+$/, ""), 24) || "—";
  year = clip(year, 12);
  const cased = (s: string) => (theme === "serif" ? s.toUpperCase() : titleCase(s));
  return { main: cased(main), year: cased(year) };
};

const LEAD = 2;            // the first letter starts (30 fps)
const LETTER_STEP = 1.2;   // frames between two letters
const MARKER_AT = 26;      // the marker wipes in from here ...
const MARKER_FRAMES = 10;  // ... over this long

const VrDateHero: Look = ({ overlay }) => {
  const { f, S, k, width, height, dur } = useBase();
  const theme = themeOf(overlay);
  const serif = theme === "serif";
  const plan = heroPlan(overlay, theme);
  const ink = useInk(k);
  const chars = Array.from(plan.main);
  // Letter starts (video frames), spaces take no time.
  let j = 0;
  const starts = chars.map((c) => (c === " " ? -1 : Math.round((LEAD + LETTER_STEP * j++) * S)));
  const lastStart = Math.max(Math.round(LEAD * S), ...starts);
  const yearAt = lastStart + Math.round(6 * S);
  const exitAt = dur - Math.round(10 * S);
  const out = 1 - outOf(f, exitAt, 10 * S);

  // Sizes: line 1's cap height at 1080p, shrunk to 66 % of the frame's width; the year at 52 %.
  const track1 = serif ? 0.06 : 0;
  const em1 = serif ? czEm(plan.main, track1) - track1
    : chars.reduce((a, c) => a + (c === " " ? CP_SPACE : CP_ADV), 0);
  const m = serif ? CZ : CP;
  const size1 = Math.min(((serif ? 64 : 92) / m.cap) * k, (0.66 * width) / Math.max(1, em1));
  const size2 = size1 * 0.52;
  const cap1 = size1 * m.cap;
  const cap2 = size2 * m.cap;
  const track2 = serif ? 0.12 : 0;
  const font = serif ? CINZEL : TYPEWRITER;
  const weight = serif ? 400 : 700;
  const color = serif ? WARM : WHITE;
  // The marker (typewriter): from a little over the caps to just under the descenders.
  const padX = 0.18 * size1;
  const padTop = 0.13 * size1;
  const padBot = 0.08 * size1;
  // Line 1's baseline to the year's cap top: below the marker or the band, with a little air.
  const band = 1.9 * cap1;
  const gap = !plan.year ? 0 : serif ? band / 2 - cap1 / 2 + 0.55 * cap2 : CP_DESC * size1 + padBot + 0.32 * cap2;
  const blockH = cap1 + (plan.year ? gap + cap2 : 0);
  const top1 = height / 2 - blockH / 2;
  const top2 = top1 + cap1 + gap;
  const textW = em1 * size1;

  const markerP = easeInOut(clamp01((f - MARKER_AT * S) / (MARKER_FRAMES * S)));
  const bandP = inOf(f, 0, 8 * S);
  const dashP = easeInOut(clamp01((f - (lastStart + 4 * S)) / (10 * S)));
  const yearStyle = letterStyle(f, yearAt, S, k);

  const cues: SoundCue[] = [{ name: "whoosh-soft-v2", alt: ["whoosh-soft", "swoosh-text"], at: LEAD + 4, gain_db: -4 }];
  if (!serif) cues.push({ name: "marker-underline", alt: ["marker-draw", "marker"], at: MARKER_AT, align: "start", gain_db: -6 });
  const sound = useLookSound(cues);

  const row: CSS = { position: "absolute", left: 0, right: 0, display: "flex", justifyContent: "center" };
  return (
    <AbsoluteFill style={{ opacity: out }}>
      {sound}
      {!serif ? ink.node : null}
      {serif ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: top1 + cap1 / 2 - band / 2, height: band,
          background: "rgba(18,12,8,.55)", opacity: bandP }} />
      ) : (
        <div style={{ position: "absolute", left: (width - textW) / 2 - padX, width: textW + 2 * padX, top: top1 - padTop,
          height: cap1 + CP_DESC * size1 + padTop + padBot, background: MARKER, opacity: markerP > 0 ? 1 : 0,
          clipPath: `inset(0 ${((1 - markerP) * 100).toFixed(2)}% 0 0)`,
          boxShadow: `0 ${(2 * k).toFixed(1)}px ${(8 * k).toFixed(1)}px rgba(0,0,0,.25)` }} />
      )}
      {serif ? (
        // Thin dashes either side of line 1, drawing outward once the letters are in.
        [-1, 1].map((side) => (
          <div key={side} style={{ position: "absolute", top: top1 + cap1 / 2 - Math.max(1.5, 2 * k) / 2,
            left: side < 0 ? width / 2 - textW / 2 - 0.62 * cap1 - 1.25 * cap1 : width / 2 + textW / 2 + 0.62 * cap1,
            width: 1.25 * cap1, height: Math.max(1.5, 2 * k), background: DASH, boxShadow: "0 1px 2px rgba(0,0,0,.35)",
            transformOrigin: side < 0 ? "100% 50%" : "0% 50%", transform: `scaleX(${dashP.toFixed(4)})` }} />
        ))
      ) : null}
      <div style={{ ...row, top: top1 }}>
        <div style={{ filter: `${!serif ? `url(#${ink.id}) ` : ""}${shadow(k, serif ? 0.5 : 0.6)}` }}>
          <CapLine font={font} m={m} size={size1} weight={weight} color={color} track={track1}>
            {chars.map((c, i) => (starts[i] < 0 && !serif
              ? <span key={i} style={{ display: "inline-block", width: `${CP_SPACE}em` }} />
              : <span key={i} style={starts[i] < 0 ? undefined : letterStyle(f, starts[i], S, k)}>{c}</span>))}
          </CapLine>
        </div>
      </div>
      {plan.year ? (
        <div style={{ ...row, top: top2 }}>
          <div style={{ filter: `${!serif ? `url(#${ink.id}) ` : ""}${shadow(k, serif ? 0.5 : 0.6)}` }}>
            <div style={yearStyle}>
              <CapLine font={font} m={m} size={size2} weight={weight} color={color} track={track2}>{plan.year}</CapLine>
            </div>
          </div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== vr-time-card
/** "9:08 AM" -> the figures big and "AM" (with a zone said after it) small; "21:40" whole; the label strip from subtitle. */
export const timeCardPlan = (ov: Overlay) => {
  const raw = digits(str(ov.text));
  const m = /^(.*?\d)\s*([AaPp])\.?\s?[Mm]\b\.?\s*(.*)$/.exec(raw);
  let fig = raw;
  let tail = "";
  if (m) {
    fig = m[1].trim();
    tail = [`${m[2].toUpperCase()}M`, clip(m[3].toUpperCase(), 5)].filter(Boolean).join(" ");
  }
  return { fig: clip(fig, 12) || "—", tail, label: clip(digits(str(ov.subtitle)).toUpperCase(), 34) };
};

const TYPE_AT = 6;         // the first figure types here (30 fps) ...
const TYPE_STEP = 3;       // ... then one every 3 frames

const VrTimeCard: Look = ({ overlay }) => {
  const { f, S, k, kw, dur } = useBase();
  const serif = themeOf(overlay) === "serif";
  const plan = timeCardPlan(overlay);
  const full = plan.tail ? `${plan.fig} ${plan.tail}` : plan.fig;
  const chars = Array.from(full);
  const nBig = Array.from(plan.fig).length;
  let j = 0;
  const at = chars.map((c) => (c === " " ? -1 : TYPE_AT + TYPE_STEP * j++));
  const lastAt = Math.max(TYPE_AT, ...at);
  const shown = (i: number) => (at[i] < 0 ? f >= Math.round((at[i - 1] ?? 0) * S) : f >= Math.round(at[i] * S));
  const exitAt = dur - Math.round(8 * S);
  const out = 1 - outOf(f, exitAt, 8 * S);
  const cardP = inOf(f, 0, 6 * S);
  const stripP = inOf(f, (lastAt + 4) * S, 6 * S);

  const m = serif ? PF : CP;
  const size = (50 / m.cap) * k;
  const cap = size * m.cap;
  const padX = 22 * k;
  const cardH = cap + 2 * (cap * 0.55);
  const font = serif ? SERIF_HEAVY : TYPEWRITER;
  const stripFont = serif ? SERIF_HEAVY : TYPEWRITER;
  const stripM = serif ? PF : CP;
  const stripSize = 17 * k;
  const stripH = 28 * k;
  const background = serif ? CARD_GOLD
    : `repeating-linear-gradient(45deg, ${CARD_RED} 0px, ${CARD_RED} ${(6 * k).toFixed(2)}px, ${CARD_RED_DARK} ${(6 * k).toFixed(2)}px, ${CARD_RED_DARK} ${(12 * k).toFixed(2)}px)`;

  // The keys: the recording's first stroke falls ~6 frames in, then about one every 3 - one per figure.
  const sound = useLookSound([{ name: "keys-type", alt: ["keys-laptop", "keys"], at: Math.max(0, TYPE_AT - 6), align: "start",
    until: lastAt + 2, gain_db: -4 }]);

  return (
    <AbsoluteFill style={{ opacity: out }}>
      {sound}
      <div style={{ position: "absolute", left: 64 * kw, top: 56 * kw }}>
        <div style={{ position: "relative", display: "inline-block" }}>
          <div style={{ display: "inline-flex", alignItems: "center", height: cardH, padding: `0 ${padX}px`, borderRadius: 10 * k,
            background, opacity: cardP, transformOrigin: "0% 0%", transform: `scale(${(0.92 + 0.08 * cardP).toFixed(4)})`,
            boxShadow: `0 ${(3 * k).toFixed(1)}px ${(10 * k).toFixed(1)}px rgba(0,0,0,.35)` }}>
            <CapLine font={font} m={m} size={size} weight={serif ? 900 : 700} color={INK}
              inner={{ fontVariantNumeric: "lining-nums tabular-nums" }}>
              {chars.map((c, i) => (
                <span key={i} style={{ visibility: shown(i) ? "visible" : "hidden", fontSize: i >= nBig ? "0.5em" : undefined,
                  ...(!serif && (c === ":" || c === ".") ? { margin: `0 ${-CP_COLON_IN}em` } : {}) }}>{c}</span>
              ))}
            </CapLine>
          </div>
          {plan.label ? (
            <div style={{ position: "absolute", left: 0, right: 0, top: cardH - 6 * k, display: "flex", justifyContent: "safe center",
              opacity: stripP, transform: `translateY(${((1 - stripP) * -8 * k).toFixed(2)}px)` }}>
              <div style={{ height: stripH, padding: `0 ${12 * k}px`, borderRadius: 4 * k, background: STRIP, display: "flex",
                alignItems: "center", boxShadow: `0 ${(2 * k).toFixed(1)}px ${(6 * k).toFixed(1)}px rgba(0,0,0,.3)` }}>
                <CapLine font={stripFont} m={stripM} size={stripSize} weight={700} color={WHITE} track={0.04}
                  inner={{ fontVariantNumeric: "lining-nums" }}>{plan.label}</CapLine>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== vr-caption-typed
/** The caption as said ("Parker Dam, 1938"), at most about 42 characters (cut at a word). */
export const captionPlan = (ov: Overlay) => clip(digits(str(ov.text)), 44) || "—";

const CAPTION_AT = 6;      // typing starts here (the typing contract: 2 frames a letter, 1 past 48)

const VrCaptionTyped: Look = ({ overlay }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const text = captionPlan(overlay);
  const chars = Array.from(text);
  const per = chars.length <= 48 ? 2 : 1;
  const typedEnd = CAPTION_AT + per * chars.length;             // 30 fps
  const n = Math.max(0, Math.min(chars.length, Math.floor((f / S - CAPTION_AT) / per) + 1));
  const exitAt = dur - Math.round(10 * S);
  const out = 1 - outOf(f, exitAt, 10 * S);
  const left = 96 * kw;
  const size = Math.min((34 / CP.cap) * k, (width - 2 * left) / Math.max(1, chars.length * CP_ADV));
  const cap = size * CP.cap;
  const baseline = height - 120 * kw;
  // The cursor: solid while it types, blinking (5 on, 5 off) for 20 frames after, then gone.
  const after = f / S - typedEnd;
  const cursorOn = f / S >= CAPTION_AT - 2 && (after < 0 || (after < 20 && Math.floor(after / 5) % 2 === 0));
  const shade = inOf(f, 0, 8 * S);

  const sound = useLookSound([{ name: "typewriter-clean", alt: ["typewriter", "keys"], at: Math.max(0, CAPTION_AT - 1),
    align: "start", until: typedEnd, gain_db: -5 }]);

  return (
    <AbsoluteFill style={{ opacity: out }}>
      {sound}
      <div style={{ position: "absolute", left: 0, bottom: 0, width: "62%", height: "46%", opacity: shade,
        background: "radial-gradient(ellipse 100% 100% at 0% 100%, rgba(0,0,0,.52) 0%, rgba(0,0,0,.3) 38%, rgba(0,0,0,.1) 62%, rgba(0,0,0,0) 80%)" }} />
      <div style={{ position: "absolute", left, top: baseline - cap, filter: shadow(k, 0.65) }}>
        <div style={{ position: "relative" }}>
          <CapLine font={TYPEWRITER} m={CP} size={size} weight={700} color={CREAM}>{chars.slice(0, n).join("")}</CapLine>
          {cursorOn ? (
            <div style={{ position: "absolute", left: (n * CP_ADV + 0.05) * size, top: -0.08 * cap, width: Math.max(2, 2.6 * k),
              height: cap * 1.16, background: CREAM }} />
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== vr-year-line
/** From `total` (default 2026) to `value` (else the year in the words); `label` small under it once it lands. */
export const yearLinePlan = (ov: Overlay) => {
  const words = digits(str(ov.text));
  const said = YEAR_RX.exec(words);
  const to = yearOf(ov.value) ?? (said ? Number(said[1]) : null);
  const from = yearOf(ov.total) ?? 2026;
  return { from, to, text: to === null ? clip(words, 24) : "", label: clip(digits(str(ov.label)).toUpperCase(), 36) };
};

const SLIDE_AT = 8;        // the dot leaves the right end here ...
const SLIDE_FRAMES = 40;   // ... and reaches the centre this much later

const VrYearLine: Look = ({ overlay }) => {
  const { f, S, k, width, height, dur } = useBase();
  const plan = yearLinePlan(overlay);
  const exitAt = dur - Math.round(10 * S);
  const out = 1 - outOf(f, exitAt, 10 * S);
  const lineW = Math.min(1100 * k, width * 0.86);
  const lineIn = inOf(f, 0, 8 * S);
  const p = plan.to === null ? 1 : easeInOut(clamp01((f - SLIDE_AT * S) / (SLIDE_FRAMES * S)));
  const cx = width / 2;
  const cy = height / 2;
  const x = cx + (1 - p) * (lineW / 2 - 8 * k);
  const dot = 12 * k;
  const year = plan.to === null ? plan.text : String(Math.round(plan.from + (plan.to - plan.from) * p));
  const landed = SLIDE_AT + SLIDE_FRAMES;
  const yearSize = 30 * k;
  const labelSize = 18 * k;
  const labelP = inOf(f, (landed + 2) * S, 10 * S);

  const cues: SoundCue[] = plan.to === null || plan.to === plan.from ? []
    : [{ name: "count-tick", alt: ["count-roll", "ui-tick"], at: SLIDE_AT, align: "start", until: landed - 1, gain_db: -8 },
      { name: "letter-tick", alt: ["ui-tick", "tick"], at: landed, gain_db: -6 }];
  const sound = useLookSound(cues);

  return (
    <AbsoluteFill style={{ opacity: out }}>
      {sound}
      <div style={{ position: "absolute", left: cx - lineW / 2, top: cy - Math.max(1, 1 * k), width: lineW, height: Math.max(2, 2 * k),
        opacity: lineIn, background: "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.55) 22%, "
          + "rgba(255,255,255,.55) 78%, rgba(255,255,255,0) 100%)", filter: `drop-shadow(0 ${(1 * k).toFixed(1)}px ${(2 * k).toFixed(1)}px rgba(0,0,0,.35))` }} />
      <div style={{ position: "absolute", left: x - dot / 2, top: cy - dot / 2, width: dot, height: dot, borderRadius: "50%",
        background: WHITE, opacity: lineIn,
        boxShadow: `0 0 ${(6 * k).toFixed(1)}px ${(2 * k).toFixed(1)}px rgba(255,255,255,.8), 0 0 ${(22 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(255,255,255,.45)` }} />
      <div style={{ position: "absolute", left: x - 300 * k, width: 600 * k, top: cy + 20 * k, display: "flex", flexDirection: "column",
        alignItems: "center", opacity: inOf(f, 3 * S, 8 * S), filter: shadow(k, 0.5) }}>
        <CapLine font={INTER_SEMI} m={IN} size={yearSize} weight={600} color={WHITE} track={0.02}
          inner={{ fontVariantNumeric: "tabular-nums" }}>{year}</CapLine>
      </div>
      {plan.label ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: cy + 20 * k + yearSize * IN.cap + 16 * k, display: "flex",
          justifyContent: "center", opacity: labelP, transform: `translateY(${((1 - labelP) * 4 * k).toFixed(2)}px)`, filter: shadow(k, 0.5) }}>
          <CapLine font={INTER_SEMI} m={IN} size={labelSize} weight={600} color="rgba(255,255,255,.7)" track={0.12}>{plan.label}</CapLine>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "vr-date-hero": VrDateHero,
  "vr-time-card": VrTimeCard,
  "vr-caption-typed": VrCaptionTyped,
  "vr-year-line": VrYearLine,
};
