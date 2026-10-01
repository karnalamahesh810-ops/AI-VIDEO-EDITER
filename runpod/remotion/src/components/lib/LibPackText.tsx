import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, ANTON_CAP, SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { useK } from "../pro/ProGraphics";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";

/**
 * Pack D: text emphasis and news lines (the owner's design rules,
 * 2026-10-01): a clean, premium news / documentary channel. White Anton caps
 * with a soft dark shadow (never a stroke, a box or a band), the key word in
 * amber, a thin amber rule or a faint feathered shade at most; the main line
 * about 50 px cap height at 1080p (40-60), the small line Inter Tight tracked
 * caps about 19 px (18-24); words or lines rise out of a clean mask with a
 * small settle and drop back into it over the last 11 frames; 96 px safe
 * margins; a long line measures itself and shrinks, then takes two lines,
 * then ends on an ellipsis. The sound is part of each look (useLookSound,
 * scheduled from its own frames): a text swoosh or a soft whoosh on an
 * entrance, a soft letter tick per word for a word-by-word reveal, the marker
 * underline for the sweep, a UI pop per bullet, a paper slide for the quote -
 * never an impact, a punch, a slam, a boom or a hit.
 *
 *   txt-key-phrase       a phrase on up to two lines low at the side, a thin amber rule beside it, the key word warming to amber
 *   txt-quote-line       a quote on up to two lines under a large faint quote mark, the attribution after a short amber rule
 *   txt-headline-words   a headline rising word by word (a tick each), the key word in amber, a short rule under it
 *   txt-breaking-tag     "BREAKING" in amber tracked caps with a thin amber rule drawing out, the headline under it
 *   txt-question         "SO WHY IS THIS HAPPENING?" word by word (a tick each), the question mark in amber
 *   txt-bullet-trio      three short lines, staggered, an amber dot popping in before each
 *   txt-what-we-know     a title over a thin rule, then three numbered items one by one
 *   txt-mini-timeline    three points on a thin line: the date above each, what happened under it
 *   txt-before-after     "BEFORE" over the left half, "AFTER" over the right (a split), each over its rule
 *   txt-underline-sweep  a phrase, then an amber underline sweeping under its key words, which turn amber
 *   txt-kicker-headline  a small kicker after a short amber rule, the headline under it
 *   txt-chapter-minimal  centred small caps between two thin rules, the chapter title under them
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Align = "left" | "right" | "center";
/** A word of a main line: `key` in amber, `glue` sits against the word before it (a question mark). */
type W = { t: string; key: boolean; glue?: boolean };

// ------------------------------------------------------------------ the type
const WHITE = "#FFFFFF";
const AMBER = "#F5B400";
const EXIT = 11;                 // frames (30 fps) the look takes to leave
const RISE = 9;                  // frames a word or a line takes to rise and settle
const BELOW = 1.2;               // em under the line a hidden word waits
const TRACK = 0.012;             // Anton's letter spacing (em)
const SPACE = 0.234;             // Anton's word space (em)
const CAP = 50;                  // px at 1080p: a main line's cap height
const CAP_MIN = 40;              // fitting never shrinks a main line below this before it trims
const SUB_CAP = 19;              // the small line's cap height
const SUB_MIN = 18;
const SUB_TRACK = 0.16;          // its letter spacing (em)
const ANTON_TOP = 0.065;         // Anton in a line box of 1 em: the caps from 0.065 em to 0.924 em
const SAFE = 96;                 // px at 1080p: the safe margin
// The mask a word moves in: room above the caps for the settle, just under the baseline, open at the sides.
const MASK = "inset(-0.3em -0.6em -0.12em -0.6em)";

/** Anton's advance widths (em). */
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, "0": 0.494, "1": 0.331, "2": 0.494, "3": 0.494, "4": 0.494, "5": 0.494,
  "6": 0.494, "7": 0.494, "8": 0.494, "9": 0.494, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, ";": 0.242,
  "%": 1.057, "$": 0.462, "°": 0.389, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "’": 0.214,
  '"': 0.36, "&": 0.52, "/": 0.405, "+": 0.355, "(": 0.291, ")": 0.291, "?": 0.492, "!": 0.229, "#": 0.546, "…": 0.62,
};
const wEm = (s: string) => Array.from(s).reduce((a, c) => a + (ADV[c] ?? 0.48) + TRACK, 0);
const lineEm = (ws: W[]) => ws.reduce((a, w, i) => a + wEm(w.t) + (i && !w.glue ? SPACE : 0), 0);
/** Inter Tight 700 caps, roughly (em). */
const subEm = (s: string, track = SUB_TRACK) =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.234 : /[0-9]/.test(c) ? 0.56 : /[MW]/.test(c) ? 0.86
    : /[IJ1.,:;'’·]/.test(c) ? 0.3 : 0.64) + track, 0);

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeIn = (t: number) => t * t * t;
/** Ease-out with a small overshoot (about 3 %): the settle. */
const settle = (t: number, s = 0.9) => 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2;
const ramp = (f: number, at: number, len: number) => clamp01((f - at) / Math.max(0.001, len));
/** A small stable jitter per index (tick pitches), no Math.random. */
const jitter = (i: number) => ((Math.sin(i * 12.9898 + 4.1) * 43758.5453) % 1 + 1) % 1;
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
const caps = (v: unknown) => str(v).replace(/[‘’`]/g, "'").replace(/[“”]/g, '"').toUpperCase();
const hex = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
/** Between two #rrggbb colours. */
const mix = (a: string, b: string, t: number) => {
  if (t <= 0) return a;
  if (t >= 1) return b;
  const [x, y] = [hex(a), hex(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
};

/** The soft dark shadow under white letters (on a wrapper, so the mask never cuts it): an edge, a close and a wide one. */
const shadowCss = (k: number, small = false) => {
  const px = (n: number) => `${(n * k).toFixed(2)}px`;
  return small
    ? `drop-shadow(0 0 ${px(1.2)} rgba(0,0,0,.8)) drop-shadow(0 ${px(1)} ${px(2)} rgba(0,0,0,.55)) drop-shadow(0 ${px(2)} ${px(8)} rgba(0,0,0,.5))`
    : `drop-shadow(0 0 ${px(1.5)} rgba(0,0,0,.72)) drop-shadow(0 ${px(2)} ${px(3)} rgba(0,0,0,.45)) `
      + `drop-shadow(0 ${px(5)} ${px(18)} rgba(0,0,0,.5))`;
};

// ------------------------------------------------------------------ words
const STOP = new Set(["THE", "AND", "BUT", "FOR", "WITH", "FROM", "THAT", "THIS", "HAVE", "HAS", "HAD", "BEEN", "WERE",
  "WAS", "ARE", "THEY", "THEIR", "THEM", "WHAT", "WHEN", "WHERE", "WHICH", "WHO", "WHY", "HOW", "WOULD", "COULD",
  "SHOULD", "ABOUT", "AFTER", "BEFORE", "INTO", "ONTO", "OVER", "UNDER", "THAN", "THEN", "THERE", "THESE", "THOSE",
  "WILL", "YOUR", "OUR", "ITS", "IT'S", "JUST", "ONLY", "ALSO", "EVEN", "STILL", "VERY", "MORE", "MOST", "SOME",
  "SAID", "SAYS", "BEING", "DOES", "DID", "NOT", "NOW", "YOU", "WE", "IS", "OF", "TO", "IN", "ON", "AT", "A", "AN"]);
const bare = (w: string) => w.replace(/[^A-Z0-9%$'&-]/g, "");
const wordsOf = (v: unknown) => caps(v).split(" ").filter(Boolean);

/** Words with their key marked: the highlight's words, else (auto) the longest word that carries meaning. */
const keyed = (words: string[], highlight: string, auto = true): W[] => {
  const out: W[] = words.map((t) => ({ t, key: false }));
  const hw = wordsOf(highlight).map(bare).filter(Boolean);
  const bw = words.map(bare);
  if (hw.length) {
    for (let i = 0; i + hw.length <= bw.length; i++) {
      if (hw.every((h, j) => bw[i + j] === h)) {
        for (let j = 0; j < hw.length; j++) out[i + j].key = true;
        return out;
      }
    }
    let any = false;
    bw.forEach((b, i) => {
      if (hw.includes(b) && !STOP.has(b)) {
        out[i].key = true;
        any = true;
      }
    });
    if (any) return out;
  }
  if (!auto) return out;
  let best = -1;
  let len = 3;
  bw.forEach((b, i) => {
    if (!STOP.has(b) && b.length > len) {
      best = i;
      len = b.length;
    }
  });
  if (best >= 0) out[best].key = true;
  return out;
};

/** A trailing question mark as its own amber glyph against the word before it. */
const withQuestionMark = (ws: W[]): W[] => {
  const last = ws[ws.length - 1];
  if (!last || !/\?$/.test(last.t) || last.t.length < 2) return ws;
  return [...ws.slice(0, -1), { ...last, t: last.t.slice(0, -1) }, { t: "?", key: true, glue: true }];
};

type Fit = { lines: W[][]; size: number };
/** Two balanced lines (never broken before a glued glyph). */
const balance = (ws: W[]): W[][] => {
  let best: W[][] = [ws];
  let score = Infinity;
  for (let i = 1; i < ws.length; i++) {
    if (ws[i].glue) continue;
    const a = ws.slice(0, i);
    const b = ws.slice(i);
    const d = Math.max(lineEm(a), lineEm(b));
    if (d < score) {
      score = d;
      best = [a, b];
    }
  }
  return best;
};

/**
 * A main line measured into `maxW`: one line at the cap height when it fits,
 * shrunk a little before it breaks, two balanced lines next, and past the
 * least cap height the last words give way to an ellipsis.
 */
const fitWords = (ws: W[], maxW: number, k: number, cap = CAP, capMin = CAP_MIN, maxLines = 2): Fit => {
  const sz = (c: number) => (c / ANTON_CAP) * k;
  const full = sz(cap);
  if (!ws.length) return { lines: [], size: full };
  const one = maxW / Math.max(0.3, lineEm(ws));
  if (one >= full) return { lines: [ws], size: full };
  if (one >= sz(cap * 0.86) || maxLines < 2 || ws.filter((w) => !w.glue).length < 2) {
    return { lines: [ws], size: Math.max(one, sz(capMin) * 0.7) };
  }
  for (let n = ws.length; n >= 2; n--) {
    const cut = n === ws.length ? ws
      : [...ws.slice(0, n - 1), { ...ws[n - 1], t: `${ws[n - 1].t.replace(/[,.;:!-]+$/, "")}…` }];
    const lines = balance(cut);
    const s = Math.min(full, maxW / Math.max(0.3, ...lines.map(lineEm)));
    if (s >= sz(capMin) || n === 2) return { lines, size: Math.max(s, sz(capMin) * 0.7) };
  }
  return { lines: [ws], size: Math.max(one, sz(capMin) * 0.7) };
};

/** The small line's size: its cap height, shrunk to fit, never under SUB_MIN (it ends on an ellipsis then). */
const subSize = (s: string, maxW: number, k: number, cap = SUB_CAP, track = SUB_TRACK) =>
  Math.max((SUB_MIN / SUBLINE_CAP) * k, Math.min((cap / SUBLINE_CAP) * k, maxW / Math.max(1, subEm(s, track))));

/** Short items: the overlay's items, else its text cut at bars, semicolons, bullets or line breaks (commas for short parts). */
const partsOf = (ov: Overlay, max: number, useText = true): { label: string; text: string }[] => {
  const its: OverlayItem[] = Array.isArray(ov.items) ? ov.items : [];
  const from = its.map((it) => ({
    label: caps(it && it.label),
    text: caps(it && it.text) || (it && typeof it.value === "number" && Number.isFinite(it.value) ? String(it.value) : ""),
  })).filter((p) => p.label || p.text);
  if (from.length || !useText) return from.slice(0, max);
  const raw = str(ov.text);
  let bits = raw.split(/\s*(?:\||;|\n|•|·)\s*/).map((b) => b.trim()).filter(Boolean);
  if (bits.length < 2) {
    const commas = raw.split(/\s*,\s*(?:and\s+|or\s+)?/i).map((b) => b.trim()).filter(Boolean);
    if (commas.length >= 2 && commas.length <= max && commas.every((c) => c.split(" ").length <= 6)) bits = commas;
  }
  return bits.slice(0, max).map((b) => ({ label: caps(b), text: "" }));
};

// ------------------------------------------------------------------ placement
const alignOf = (ov: Overlay, dflt: Align): Align => {
  if (ov.fullFrame) return "center";
  const a = String(ov.align || "").toLowerCase();
  return a === "left" || a === "right" || a === "center" ? a : dflt;
};
const flexOf = (a: Align) => (a === "right" ? "flex-end" : a === "center" ? "center" : "flex-start");
/** The room a block may take: a side of the lower third, or the middle of the frame. */
const roomFor = (width: number, height: number, align: Align, full: boolean, side = 0.44) =>
  (height > width ? 0.84 : align === "center" || full ? 0.72 : side) * width;
const safeOf = (width: number, height: number) => SAFE * (Math.min(width, height) / 1080);

/**
 * The block on the frame: low at the side or the centre of the lower third
 * (its foot a quarter of the height up, clear of the captions) at the 96 px
 * safe margin; `mid` centres it in the frame; a full-screen scene centres it
 * larger. `push` is a slow drift while it holds.
 */
const Stage: React.FC<{ align: Align; full?: boolean; mid?: boolean; push?: number; children: React.ReactNode }> =
  ({ align, full = false, mid = false, push = 1, children }) => {
    const { width, height } = useVideoConfig();
    const m = safeOf(width, height);
    const foot = height * 0.25;
    const centred = full || mid;
    const pos: React.CSSProperties = centred
      ? { left: m, right: m, top: m, bottom: m, justifyContent: "center", alignItems: full ? "center" : flexOf(align) }
      : align === "center"
        ? { left: m, right: m, bottom: foot, alignItems: "center" }
        : align === "right"
          ? { right: m, bottom: foot, alignItems: "flex-end" }
          : { left: m, bottom: foot, alignItems: "flex-start" };
    const origin = centred ? "50% 50%" : align === "center" ? "50% 100%" : align === "right" ? "100% 100%" : "0% 100%";
    return (
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos, textAlign: align,
        transformOrigin: origin, transform: `scale(${((full ? 1.2 : 1) * push).toFixed(5)})` }}>
        {children}
      </div>
    );
  };

// ------------------------------------------------------------------ pieces
/**
 * Main lines of Anton caps, each in its mask. `y(li, wi)` is a word's offset
 * in em (0 in place, BELOW hidden under its line); `fill` its colour; `ghost`
 * draws on an unmasked copy of the line laid out the same (the underline).
 */
const MainLines: React.FC<{
  lines: W[][]; size: number; k: number; align: Align; y: (li: number, wi: number) => number;
  fill?: (li: number, wi: number, w: W) => string; gap?: number;
  ghost?: (li: number, wi: number, w: W) => React.ReactNode;
}> = ({ lines, size, k, align, y, fill, gap = 0.16, ghost }) => {
  const gapAfter = (ws: W[], wi: number) => (wi >= ws.length - 1 ? 0 : ws[wi + 1].glue ? 0.03 : SPACE);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: flexOf(align), fontFamily: ANTON, fontWeight: 400,
      fontSize: size, lineHeight: 1, letterSpacing: `${TRACK}em`, whiteSpace: "pre" }}>
      {lines.map((ws, li) => (
        <div key={li} style={{ position: "relative", marginTop: li ? `${gap}em` : 0 }}>
          <div style={{ filter: shadowCss(k) }}>
            <div style={{ clipPath: MASK, display: "flex" }}>
              {ws.map((w, wi) => {
                const off = y(li, wi);
                return (
                  <span key={wi} style={{ display: "inline-block", height: "1em", marginRight: `${gapAfter(ws, wi)}em`,
                    color: fill ? fill(li, wi, w) : w.key ? AMBER : WHITE,
                    transform: off ? `translateY(${off.toFixed(4)}em)` : undefined,
                    visibility: off >= BELOW - 1e-3 ? "hidden" : undefined }}>{w.t}</span>
                );
              })}
            </div>
          </div>
          {ghost ? (
            <div aria-hidden style={{ position: "absolute", left: 0, top: 0, display: "flex", color: "transparent",
              filter: `drop-shadow(0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.55))` }}>
              {ws.map((w, wi) => (
                <span key={wi} style={{ position: "relative", display: "inline-block", height: "1em",
                  marginRight: `${gapAfter(ws, wi)}em` }}>{w.t}{ghost(li, wi, w)}</span>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
};

/** The small line: Inter Tight tracked caps, in from below, out with a fade; an ellipsis if it runs past `maxW`. */
const Small: React.FC<{ text: string; size: number; k: number; p: number; q: number; color?: string; track?: number;
  weight?: number; maxW?: number }> = ({ text, size, k, p, q, color = "rgba(255,255,255,.94)", track = SUB_TRACK,
  weight = 700, maxW }) => {
  if (!text || p <= 0) return null;
  return (
    <div style={{ fontFamily: SUBLINE, fontWeight: weight, fontSize: size, lineHeight: 1.1,
      letterSpacing: `${(track + 0.1 * (1 - p)).toFixed(4)}em`, textTransform: "uppercase", whiteSpace: "nowrap",
      maxWidth: maxW, overflow: maxW ? "hidden" : undefined, textOverflow: maxW ? "ellipsis" : undefined, color,
      opacity: p * (1 - q), transform: `translateY(${((1 - p) * 0.5 + q * 0.4).toFixed(4)}em)`, filter: shadowCss(k, true) }}>
      {text}
    </div>
  );
};

/** A thin rule drawing out from `origin` (p 0-1). */
const Rule: React.FC<{ w: number; k: number; p: number; origin?: string; color?: string }> =
  ({ w, k, p, origin = "0% 50%", color = AMBER }) => (
    <div style={{ width: w, height: Math.max(2, 3 * k), background: color, borderRadius: 2 * k, opacity: p > 0.001 ? 1 : 0,
      transform: `scaleX(${clamp01(p).toFixed(4)})`, transformOrigin: origin,
      boxShadow: `0 ${(1 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
  );

/** A faint feathered shade behind a block: a blurred dark ellipse, no edge anywhere. */
const Shade: React.FC<{ k: number; o: number; x?: number; y?: number }> = ({ k, o, x = 80, y = 56 }) => (o > 0.001 ? (
  <div style={{ position: "absolute", left: -x * k, right: -x * k, top: -y * k, bottom: -y * k, zIndex: -1, pointerEvents: "none",
    background: "radial-gradient(closest-side, rgba(0,0,0,.40), rgba(0,0,0,.32) 45%, rgba(0,0,0,.14) 75%, rgba(0,0,0,0) 100%)",
    filter: `blur(${(18 * k).toFixed(1)}px)`, opacity: o }} />
) : null);

// ------------------------------------------------------------------ timing
/** The look's clock in 30-fps frames: now, its length, and where its 11-frame exit starts. */
const useClock = () => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const S = fps / 30;
  const dur = durationInFrames / S;
  return { f: frame / S, dur, out: Math.max(dur * 0.6, dur - EXIT), width, height, k };
};
/** A unit's offset (em): up out of its mask with a small settle from `start`, back down into it from `outAt`. */
const riseY = (f: number, start: number, outAt: number) => {
  if (f < start) return BELOW;
  const p = clamp01((f - start) / RISE);
  const e = easeIn(clamp01((f - outAt) / 7));
  return BELOW * (1 - settle(p)) + e * BELOW;
};
/** Frames between units so the last has landed by `by`: at most `step`, at least 1. */
const stepFor = (n: number, lead: number, step: number, by: number) =>
  (n <= 1 ? step : Math.max(1, Math.min(step, (by - lead - RISE) / (n - 1))));
/** The exit's stagger, so the last unit is under before the end. */
const exitStagger = (n: number, dur: number, outAt: number) =>
  (n <= 1 ? 0 : Math.max(0, Math.min(1.5, (dur - outAt - 7) / (n - 1))));
/** A slow drift while it holds. */
const pushOf = (f: number, from: number, outAt: number) => 1 + 0.01 * clamp01((f - from) / Math.max(1, outAt - from));
const r1 = (x: number) => Math.round(x * 10) / 10;
/** A soft letter tick on each word as it rises, never two within 2 frames. */
const wordTicks = (starts: number[], gain = -6): SoundCue[] => {
  const cues: SoundCue[] = [];
  let last = -99;
  starts.forEach((s, i) => {
    const at = r1(s + 3);
    if (at - last < 2) return;
    last = at;
    cues.push({ name: "letter-tick", alt: ["ui-tick", "tick"], at, gain_db: r1(gain - 0.8 * jitter(i)),
      pitch: r1((0.96 + 0.08 * jitter(i + 5)) * 100) / 100 });
  });
  return cues;
};
const SWOOSH = (at: number, gain_db = -4, pitch?: number): SoundCue =>
  ({ name: "swoosh-text", alt: ["whoosh-soft-v2", "whoosh-soft"], at: r1(at), gain_db, ...(pitch ? { pitch } : {}) });
const WHOOSH = (at: number, gain_db = -6): SoundCue =>
  ({ name: "whoosh-soft-v2", alt: ["whoosh-soft"], at: r1(at), align: "start", gain_db });
const POP = (at: number, i: number, gain_db = -3): SoundCue =>
  ({ name: "ui-pop", alt: ["pop"], at: r1(at), gain_db, pitch: r1((0.98 + 0.05 * i) * 100) / 100 });

/** Words rising one by one: their starts, when the last has landed, the exit's stagger. */
const wordClock = (n: number, lead: number, step: number, dur: number, outAt: number) => {
  const st = stepFor(n, lead, step, Math.max(lead + RISE + 2, dur * 0.45));
  const starts = Array.from({ length: n }, (_, i) => lead + i * st);
  return { starts, landed: (starts[n - 1] ?? lead) + RISE, ex: exitStagger(n, dur, outAt) };
};

// ================================================================== 1 txt-key-phrase
const TxtKeyPhrase: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const side = align !== "center";
  const room = roomFor(width, height, align, full, 0.42);
  const fit = fitWords(keyed(wordsOf(overlay.text), str(overlay.highlight)), room - (side ? 20 * k : 0), k);
  const n = fit.lines.length;
  const starts = fit.lines.map((_, li) => 3 + li * 5);
  const landed = (starts[n - 1] ?? 3) + RISE;
  const ex = exitStagger(n, dur, out);
  const sub = caps(overlay.subtitle) || caps(overlay.label);
  const sound = useLookSound(n ? [SWOOSH(4)] : []);
  if (!n) return null;
  const size = fit.size;
  const keyP = easeOut(ramp(f, landed - 2, 9));
  const ruleP = easeOut(ramp(f, 0, 12)) * (1 - easeIn(ramp(f, out + 2, 8)));
  const ruleW = Math.max(2, 3 * k);
  const subPx = sub ? subSize(sub, room, k) : 0;
  const lineW = Math.max(...fit.lines.map(lineEm)) * size;
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: align === "right" ? "row-reverse" : "row",
          alignItems: "stretch" }}>
          <Shade k={k} o={0.75 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          {side ? (
            <div style={{ width: ruleW, paddingTop: size * ANTON_TOP, paddingBottom: sub ? subPx * 0.12 : size * 0.07,
              [align === "right" ? "marginLeft" : "marginRight"]: Math.max(14 * k, size * 0.3) }}>
              <div style={{ width: "100%", height: "100%", background: AMBER, borderRadius: ruleW, transform: `scaleY(${ruleP.toFixed(4)})`,
                transformOrigin: "50% 100%", boxShadow: `0 0 ${(4 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
            </div>
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
            <MainLines lines={fit.lines} size={size} k={k} align={align}
              y={(li) => riseY(f, starts[li], out + li * ex)} fill={(_li, _wi, w) => (w.key ? mix(WHITE, AMBER, keyP) : WHITE)} />
            {sub ? (
              <div style={{ marginTop: size * 0.3 }}>
                <Small text={sub} size={subPx} k={k} p={easeOut(ramp(f, landed - 1, 10))} q={easeIn(ramp(f, out, 7))} maxW={room} />
              </div>
            ) : null}
            {!side ? (
              <div style={{ marginTop: size * 0.24 }}>
                <Rule w={Math.min(lineW, Math.max(2.2 * CAP * k, 0.3 * lineW))} k={k} p={ruleP} origin="50% 50%" />
              </div>
            ) : null}
          </div>
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 2 txt-quote-line
/** An opening quote mark, drawn (two filled "6" shapes) so it never depends on a font's glyph. */
const QuoteMark: React.FC<{ h: number; color: string; opacity: number; scale: number }> = ({ h, color, opacity, scale }) => (
  <svg width={h * 1.21} height={h} viewBox="0 0 68 56" style={{ display: "block", overflow: "visible", opacity,
    transform: `scale(${scale.toFixed(4)})`, transformOrigin: "0% 100%" }}>
    <path fill={color} d="M0 41 C0 22 9 7 26 0 L29 6 C20 11 15.5 18 15 26 C23.5 26.5 30 33 30 41 C30 49.5 23.3 56 15 56 C6.7 56 0 49.5 0 41 Z" />
    <path fill={color} d="M38 41 C38 22 47 7 64 0 L67 6 C58 11 53.5 18 53 26 C61.5 26.5 68 33 68 41 C68 49.5 61.3 56 53 56 C44.7 56 38 49.5 38 41 Z" />
  </svg>
);

const TxtQuoteLine: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.56);
  const said = caps(overlay.text).replace(/^["'\s]+|["'\s]+$/g, "");
  const fit = fitWords(keyed(said.split(" ").filter(Boolean), str(overlay.highlight), false), room, k, 46, 36);
  const n = fit.lines.length;
  const starts = fit.lines.map((_, li) => 6 + li * 6);
  const landed = (starts[n - 1] ?? 6) + RISE;
  const ex = exitStagger(n, dur, out);
  const who = caps(overlay.label);
  const role = caps(overlay.subtitle);
  const sound = useLookSound(n ? [{ name: "paper-slide-v2", alt: ["paper-slide"], at: 6, gain_db: -3 }] : []);
  if (!n) return null;
  const size = fit.size;
  const capPx = size * ANTON_CAP;
  const markP = easeOut(ramp(f, 0, 12));
  const markQ = easeIn(ramp(f, out + 1, 8));
  const attr = [who, role].filter(Boolean).join("  ·  ");
  const attrPx = attr ? subSize(attr, room - 48 * k, k) : 0;
  const attrP = easeOut(ramp(f, landed - 1, 10));
  const attrQ = easeIn(ramp(f, out, 7));
  // The mark about two cap heights tall, mostly above the first line (its tail just behind the caps).
  const markH = capPx * 2;
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align),
          paddingTop: markH * 0.9 }}>
          <Shade k={k} o={0.8 * markP * (1 - markQ)} x={90} y={60} />
          <div style={{ position: "absolute", top: 0, ...(align === "right" ? { right: size * 0.02 } : align === "center"
            ? { left: "50%", marginLeft: -markH * 0.6 } : { left: -size * 0.05 }) }}>
            <QuoteMark h={markH} color={AMBER} opacity={0.34 * markP * (1 - markQ)} scale={0.92 + 0.08 * markP} />
          </div>
          <MainLines lines={fit.lines} size={size} k={k} align={align} y={(li) => riseY(f, starts[li], out + li * ex)} />
          {attr ? (
            <div style={{ display: "flex", alignItems: "center", marginTop: size * 0.34,
              flexDirection: align === "right" ? "row-reverse" : "row" }}>
              <div style={{ [align === "right" ? "marginLeft" : "marginRight"]: 14 * k }}>
                <Rule w={30 * k} k={k} p={attrP * (1 - attrQ)} origin={align === "right" ? "100% 50%" : "0% 50%"} />
              </div>
              <Small text={attr} size={attrPx} k={k} p={attrP} q={attrQ} maxW={room - 48 * k} />
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 3 txt-headline-words
const TxtHeadlineWords: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.46);
  const fit = fitWords(keyed(wordsOf(overlay.text), str(overlay.highlight)), room, k, 52);
  const flat = fit.lines.flat();
  const clock = wordClock(flat.length, 2, 4, dur, out);
  const sound = useLookSound(wordTicks(clock.starts));
  if (!flat.length) return null;
  const size = fit.size;
  const index = (li: number, wi: number) => fit.lines.slice(0, li).reduce((a, l) => a + l.length, 0) + wi;
  const sub = caps(overlay.subtitle);
  const lineW = Math.max(...fit.lines.map(lineEm)) * size;
  const ruleP = easeOut(ramp(f, clock.landed - 3, 12)) * (1 - easeIn(ramp(f, out, 8)));
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, clock.landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.7 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          <MainLines lines={fit.lines} size={size} k={k} align={align}
            y={(li, wi) => { const i = index(li, wi); return riseY(f, clock.starts[i], out + i * Math.min(clock.ex, 0.6)); }} />
          <div style={{ marginTop: size * 0.22, marginBottom: sub ? size * 0.2 : 0 }}>
            <Rule w={Math.min(lineW, Math.max(2 * CAP * k, 0.28 * lineW))} k={k} p={ruleP}
              origin={align === "right" ? "100% 50%" : align === "center" ? "50% 50%" : "0% 50%"} />
          </div>
          {sub ? <Small text={sub} size={subSize(sub, room, k)} k={k} p={easeOut(ramp(f, clock.landed, 10))}
            q={easeIn(ramp(f, out, 7))} maxW={room} /> : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 4 txt-breaking-tag
const TxtBreakingTag: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.46);
  const tag = caps(overlay.label) || "BREAKING";
  const fit = fitWords(keyed(wordsOf(overlay.text), str(overlay.highlight), false), room, k, 48);
  const n = fit.lines.length;
  const starts = fit.lines.map((_, li) => 9 + li * 5);
  const landed = n ? starts[n - 1] + RISE : 16;
  const ex = exitStagger(n, dur, out);
  const sound = useLookSound([WHOOSH(0, -7), ...(n ? [SWOOSH(10, -5)] : [])]);
  const size = fit.size;
  const tagPx = subSize(tag, room * 0.5, k, 21, 0.24);
  const tagP = easeOut(ramp(f, 1, 9));
  const tagQ = easeIn(ramp(f, out + 2, 7));
  const lineW = n ? Math.max(...fit.lines.map(lineEm)) * size : 0;
  const tagW = subEm(tag, 0.24) * tagPx;
  const ruleW = Math.max(3 * CAP * k, lineW - tagW - 18 * k);
  const ruleP = easeOut(ramp(f, 3, 14)) * (1 - easeIn(ramp(f, out, 8)));
  const right = align === "right";
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.7 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          <div style={{ display: "flex", alignItems: "center", flexDirection: right ? "row-reverse" : "row",
            marginBottom: n ? size * 0.3 : 0 }}>
            <div style={{ clipPath: right ? `inset(-0.4em -0.4em -0.4em ${((1 - tagP) * 100).toFixed(2)}%)`
              : `inset(-0.4em ${((1 - tagP) * 100).toFixed(2)}% -0.4em -0.4em)` }}>
              <Small text={tag} size={tagPx} k={k} p={1} q={tagQ} color={AMBER} track={0.24} />
            </div>
            <div style={{ [right ? "marginRight" : "marginLeft"]: 18 * k }}>
              <Rule w={ruleW} k={k} p={ruleP} origin={right ? "100% 50%" : "0% 50%"} />
            </div>
          </div>
          {n ? <MainLines lines={fit.lines} size={size} k={k} align={align} y={(li) => riseY(f, starts[li], out + li * ex)} /> : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 5 txt-question
const TxtQuestion: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "center");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.46);
  const fit = fitWords(withQuestionMark(keyed(wordsOf(overlay.text), str(overlay.highlight), false)), room, k, 52);
  const flat = fit.lines.flat();
  const units = flat.filter((w) => !w.glue).length;
  const clock = wordClock(units, 2, 4, dur, out);
  // A glued question mark rises a frame after its word.
  const startOf: number[] = [];
  let u = -1;
  flat.forEach((w) => {
    if (!w.glue) u++;
    startOf.push(w.glue ? clock.starts[Math.max(0, u)] + 2 : clock.starts[u]);
  });
  const sound = useLookSound(wordTicks(clock.starts));
  if (!flat.length) return null;
  const size = fit.size;
  const index = (li: number, wi: number) => fit.lines.slice(0, li).reduce((a, l) => a + l.length, 0) + wi;
  const lineW = Math.max(...fit.lines.map(lineEm)) * size;
  const landed = Math.max(...startOf) + RISE;
  const ruleP = easeOut(ramp(f, landed - 2, 12)) * (1 - easeIn(ramp(f, out, 8)));
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.75 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          <MainLines lines={fit.lines} size={size} k={k} align={align}
            y={(li, wi) => { const i = index(li, wi); return riseY(f, startOf[i], out + i * Math.min(clock.ex, 0.5)); }} />
          <div style={{ marginTop: size * 0.24 }}>
            <Rule w={Math.min(lineW, Math.max(2.4 * CAP * k, 0.24 * lineW))} k={k} p={ruleP}
              origin={align === "right" ? "100% 50%" : align === "center" ? "50% 50%" : "0% 50%"} />
          </div>
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 6 txt-bullet-trio
const TxtBulletTrio: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.46);
  const items = partsOf(overlay, 3).map((p) => [p.label, p.text].filter(Boolean).join(" · "));
  const dotRoom = 40 * k;
  // One size for the three lines: each fits on one line, the longest sets it.
  const fits = items.map((t) => fitWords(keyed(t.split(" ").filter(Boolean), "", false), room - dotRoom, k, 40, 30, 1));
  const size = fits.length ? Math.min(...fits.map((x) => x.size)) : (40 / ANTON_CAP) * k;
  const n = items.length;
  const step = stepFor(n, 3, 8, Math.max(14, dur * 0.42));
  const starts = items.map((_, i) => 3 + i * step);
  const landed = (starts[n - 1] ?? 3) + RISE;
  const ex = exitStagger(n, dur, out);
  const sound = useLookSound(starts.map((s, i) => POP(s + 2, i)));
  if (!n) return null;
  const dotD = Math.max(7, size * 0.2);
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.75 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          {fits.map((fit, i) => {
            const dotIn = settle(clamp01((f - starts[i]) / 7), 1.6);
            const dotOut = 1 - easeIn(ramp(f, out + i * ex, 6));
            return (
              <div key={i} style={{ display: "flex", flexDirection: align === "right" ? "row-reverse" : "row",
                alignItems: "flex-start", marginTop: i ? size * 0.42 : 0 }}>
                <div style={{ width: dotD, height: dotD, borderRadius: "50%", background: AMBER, flex: "none",
                  marginTop: size * (ANTON_TOP + ANTON_CAP / 2) - dotD / 2,
                  [align === "right" ? "marginLeft" : "marginRight"]: Math.max(14 * k, size * 0.36),
                  transform: `scale(${Math.max(0, f >= starts[i] ? dotIn * dotOut : 0).toFixed(4)})`,
                  boxShadow: `0 ${(1 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,.5)` }} />
                <MainLines lines={fit.lines.slice(0, 1).map((l) => l.map((w) => ({ ...w })))} size={size} k={k} align="left"
                  y={() => riseY(f, starts[i] + 1, out + i * ex)} />
              </div>
            );
          })}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 7 txt-what-we-know
/** One small-caps item row in its own mask: an amber index, then the words. */
const ItemRow: React.FC<{ idx: string; text: string; size: number; k: number; y: number; o: number; maxW: number }> =
  ({ idx, text, size, k, y, o, maxW }) => (
    <div style={{ filter: shadowCss(k, true), opacity: o }}>
      <div style={{ clipPath: "inset(-0.3em -0.6em -0.18em -0.6em)", display: "flex", alignItems: "baseline",
        fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1.1, textTransform: "uppercase", whiteSpace: "nowrap",
        transform: y ? `translateY(${y.toFixed(4)}em)` : undefined }}>
        <span style={{ color: AMBER, letterSpacing: "0.1em", marginRight: "0.75em" }}>{idx}</span>
        <span style={{ color: "rgba(255,255,255,.96)", letterSpacing: "0.07em", maxWidth: maxW, overflow: "hidden",
          textOverflow: "ellipsis" }}>{text}</span>
      </div>
    </div>
  );

const TxtWhatWeKnow: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.44);
  const hasItems = Array.isArray(overlay.items) && overlay.items.length > 0;
  const title = caps(overlay.label) || (hasItems ? caps(overlay.text) : "") || "WHAT WE KNOW";
  const items = partsOf(overlay, 3).map((p) => [p.label, p.text].filter(Boolean).join(" · "));
  const fit = fitWords(keyed(title.split(" ").filter(Boolean), "", false), room, k, 44, 34, 1);
  const n = items.length;
  const step = stepFor(n, 13, 7, Math.max(22, dur * 0.48));
  const starts = items.map((_, i) => 13 + i * step);
  const landed = (starts[n - 1] ?? 10) + RISE;
  const ex = exitStagger(n + 1, dur, out);
  const sound = useLookSound([WHOOSH(0, -7), ...starts.map((s, i) => POP(s + 2, i))]);
  const size = fit.size;
  const idxEm = subEm("00", 0.1) + 0.75;
  const itemPx = n ? Math.max((15 / SUBLINE_CAP) * k, Math.min((22 / SUBLINE_CAP) * k,
    ...items.map((t) => (room - 4 * k) / Math.max(1, subEm(t, 0.07) + idxEm)))) : 0;
  const titleW = lineEm(fit.lines[0] || []) * size;
  const ruleP = easeOut(ramp(f, 4, 14)) * (1 - easeIn(ramp(f, out + 1, 8)));
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.8 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          <MainLines lines={fit.lines.slice(0, 1)} size={size} k={k} align={align} y={() => riseY(f, 2, out)} />
          <div style={{ marginTop: size * 0.2, marginBottom: n ? size * 0.36 : 0 }}>
            <Rule w={Math.max(titleW, 3 * CAP * k)} k={k} p={ruleP}
              origin={align === "right" ? "100% 50%" : align === "center" ? "50% 50%" : "0% 50%"} />
          </div>
          {items.map((t, i) => {
            const p = clamp01((f - starts[i]) / RISE);
            const e = easeIn(ramp(f, out + (i + 1) * ex, 7));
            const y = f < starts[i] ? BELOW : BELOW * (1 - settle(p)) + e * BELOW;
            return (
              <div key={i} style={{ marginTop: i ? itemPx * 0.62 : 0 }}>
                <ItemRow idx={String(i + 1).padStart(2, "0")} text={t} size={itemPx} k={k} y={y}
                  o={f < starts[i] ? 0 : 1} maxW={room - idxEm * itemPx} />
              </div>
            );
          })}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 8 txt-mini-timeline
const DATEISH = /^((?:\d{4}s?|'\d\d|(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*\.?(?:\s+\d{1,2})?(?:,?\s+\d{4})?|\d{1,2}(?::\d{2})?\s?(?:AM|PM)|DAY\s+\d+))\b[\s:,—–-]*/;
/** The points: items (label = when, text = what), else the text cut into parts, each led by its date. */
const pointsOf = (ov: Overlay): { when: string; what: string }[] => {
  const its: OverlayItem[] = Array.isArray(ov.items) ? ov.items : [];
  const fromItems = its.map((it) => {
    const label = caps(it && it.label);
    const text = caps(it && it.text);
    const value = it && typeof it.value === "number" && Number.isFinite(it.value) ? String(it.value) : "";
    if (label && (text || value)) return { when: DATEISH.test(label) || !value ? label : value, what: text || (DATEISH.test(label) ? "" : label) };
    const m = DATEISH.exec(label);
    return m ? { when: m[1], what: label.slice(m[0].length) } : { when: value, what: label };
  }).filter((p) => p.when || p.what);
  if (fromItems.length) return fromItems.slice(0, 4);
  return partsOf(ov, 4).map((p) => {
    const m = DATEISH.exec(p.label);
    return m ? { when: m[1].trim(), what: p.label.slice(m[0].length).trim() } : { when: "", what: p.label };
  });
};

const TxtMiniTimeline: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "center");
  const full = Boolean(overlay.fullFrame);
  const pts = pointsOf(overlay);
  const n = pts.length;
  const W = Math.min(roomFor(width, height, "center", full), Math.max(1, n) * 400 * k);
  const colW = W / Math.max(1, n);
  const lineLen = Math.min(18, Math.max(8, dur * 0.3));
  const hits = pts.map((_, i) => 2 + lineLen * ((i + 0.5) / n));
  const landed = (hits[n - 1] ?? 2) + RISE + 3;
  const ex = exitStagger(n, dur, out);
  const sound = useLookSound(n ? [WHOOSH(2, -8), ...hits.map((h, i) => POP(h + 1, i, -4))] : []);
  if (!n) return null;
  const labelFits = pts.map((p) => fitWords(keyed(p.when.split(" ").filter(Boolean), "", false), colW * 0.9, k, 40, 28, 1));
  const labelSize = Math.min(...labelFits.map((x) => x.size));
  const capPx = (18 / SUBLINE_CAP) * k;
  const dotD = Math.max(8, 12 * k);
  const lineP = easeOut(ramp(f, 2, lineLen)) * (1 - easeIn(ramp(f, out + 2, 8)));
  const anyWhen = pts.some((p) => p.when);
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", width: W }}>
          <Shade k={k} o={0.8 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          {anyWhen ? (
            <div style={{ display: "flex", marginBottom: labelSize * 0.26 }}>
              {pts.map((p, i) => (
                <div key={i} style={{ width: colW, display: "flex", justifyContent: "center" }}>
                  {p.when ? (
                    <MainLines lines={labelFits[i].lines.slice(0, 1)} size={labelSize} k={k} align="center"
                      fill={(_li, _wi) => (i === n - 1 ? AMBER : WHITE)} y={() => riseY(f, hits[i], out + i * ex)} />
                  ) : <div style={{ height: labelSize }} />}
                </div>
              ))}
            </div>
          ) : null}
          <div style={{ position: "relative", height: dotD }}>
            <div style={{ position: "absolute", left: 0, right: 0, top: dotD / 2 - Math.max(1, 1.5 * k), height: Math.max(2, 3 * k),
              background: "rgba(255,255,255,.82)", borderRadius: 2 * k, transform: `scaleX(${lineP.toFixed(4)})`,
              transformOrigin: "0% 50%", boxShadow: `0 ${(1 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,.5)` }} />
            {pts.map((_, i) => {
              const s = f < hits[i] ? 0 : settle(clamp01((f - hits[i]) / 6), 1.6) * (1 - easeIn(ramp(f, out + i * ex, 6)));
              return (
                <div key={i} style={{ position: "absolute", top: 0, left: colW * (i + 0.5) - dotD / 2, width: dotD, height: dotD,
                  borderRadius: "50%", background: i === n - 1 ? AMBER : WHITE, transform: `scale(${Math.max(0, s).toFixed(4)})`,
                  boxShadow: `0 ${(1 * k).toFixed(1)}px ${(5 * k).toFixed(1)}px rgba(0,0,0,.55)` }} />
              );
            })}
          </div>
          <div style={{ display: "flex", marginTop: capPx * 0.75 }}>
            {pts.map((p, i) => {
              const pIn = easeOut(ramp(f, hits[i] + 3, 10));
              const q = easeIn(ramp(f, out + i * ex, 7));
              return (
                <div key={i} style={{ width: colW, display: "flex", justifyContent: "center" }}>
                  <div style={{ maxWidth: colW * 0.88, fontFamily: SUBLINE, fontWeight: 700, fontSize: capPx, lineHeight: 1.22,
                    letterSpacing: "0.1em", textTransform: "uppercase", textAlign: "center", color: "rgba(255,255,255,.94)",
                    maxHeight: "2.5em", overflow: "hidden", opacity: pIn * (1 - q),
                    transform: `translateY(${((1 - pIn) * 0.5 + q * 0.4).toFixed(4)}em)`, filter: shadowCss(k, true) }}>
                    {p.what}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 9 txt-before-after
const TxtBeforeAfter: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const parts = partsOf(overlay, 2);
  const its = Array.isArray(overlay.items) && overlay.items.length > 0;
  const labels = [0, 1].map((i) => (parts[i] && parts[i].label) || (i ? "AFTER" : "BEFORE"));
  const subs = str(overlay.subtitle).split(/\s*\|\s*/);
  const notes = [0, 1].map((i) => (its && parts[i] ? parts[i].text : "") || caps(subs[i] || ""));
  const starts = [2, 9];
  const sound = useLookSound([SWOOSH(3, -4), SWOOSH(10, -5, 1.06)]);
  const m = safeOf(width, height);
  const across = width >= height;
  const half = across ? width / 2 : width;
  const room = half - 2 * m;
  const fits = labels.map((l) => fitWords(keyed(l.split(" ").filter(Boolean), "", false), room, k, 46, 32, 1));
  const size = Math.min(...fits.map((x) => x.size));
  const ex = 1.5;
  return (
    <AbsoluteFill>
      {sound}
      {fits.map((fit, i) => {
        const lineW = lineEm(fit.lines[0] || []) * size;
        const ruleP = easeOut(ramp(f, starts[i] + 3, 12)) * (1 - easeIn(ramp(f, out + i * ex, 7)));
        const pos: React.CSSProperties = across ? { left: i * half + m, top: m } : { left: m, top: i * (height / 2) + m };
        return (
          <div key={i} style={{ position: "absolute", ...pos, display: "flex", flexDirection: "column", alignItems: "flex-start",
            transform: `scale(${pushOf(f, starts[1] + RISE, out).toFixed(5)})`, transformOrigin: "0% 0%" }}>
            <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
              <Shade k={k} o={0.7 * easeOut(ramp(f, starts[i], 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} x={60} y={44} />
              <MainLines lines={fit.lines.slice(0, 1)} size={size} k={k} align="left" fill={() => WHITE}
                y={() => riseY(f, starts[i], out + i * ex)} />
              <div style={{ marginTop: size * 0.2, marginBottom: notes[i] ? size * 0.22 : 0 }}>
                <Rule w={Math.max(lineW, 2.2 * CAP * k)} k={k} p={ruleP} color={i ? AMBER : "rgba(255,255,255,.85)"} />
              </div>
              {notes[i] ? <Small text={notes[i]} size={subSize(notes[i], room, k)} k={k} p={easeOut(ramp(f, starts[i] + 6, 10))}
                q={easeIn(ramp(f, out + i * ex, 7))} maxW={room} /> : null}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// ================================================================== 10 txt-underline-sweep
const TxtUnderlineSweep: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.46);
  const fit = fitWords(keyed(wordsOf(overlay.text), str(overlay.highlight)), room, k, 52);
  const n = fit.lines.length;
  const starts = fit.lines.map((_, li) => 3 + li * 5);
  const landed = (starts[n - 1] ?? 3) + RISE;
  const sweepAt = landed + 2;
  const sweepLen = Math.min(14, Math.max(8, dur * 0.12));
  const ex = exitStagger(n, dur, out);
  const sound = useLookSound(n ? [SWOOSH(4), { name: "marker-underline", alt: ["marker-draw", "marker"], at: r1(sweepAt),
    align: "start", gain_db: -2 }] : []);
  if (!n) return null;
  const size = fit.size;
  // The key words in reading order, each a share of the sweep by its width (the space to a key neighbour included).
  const spans: { li: number; wi: number; a: number; b: number; joins: boolean }[] = [];
  let total = 0;
  fit.lines.forEach((ws, li) => ws.forEach((w, wi) => {
    if (!w.key) return;
    const joins = wi < ws.length - 1 && ws[wi + 1].key;
    const len = wEm(w.t) + (joins ? (ws[wi + 1].glue ? 0.03 : SPACE) : 0);
    spans.push({ li, wi, a: total, b: total + len, joins });
    total += len;
  }));
  const sweep = easeOut(ramp(f, sweepAt, sweepLen)) * total;
  // At the exit the underline runs back the way it came (before the words drop); the words stay amber.
  const reach = Math.min(sweep, total * (1 - easeIn(ramp(f, out - 1, 6))));
  const shareOf = (li: number, wi: number) => {
    const s = spans.find((x) => x.li === li && x.wi === wi);
    const part = (v: number) => (s ? clamp01((v - s.a) / Math.max(0.001, s.b - s.a)) : 0);
    return s ? { p: part(reach), lit: part(sweep), joins: s.joins, len: s.b - s.a } : null;
  };
  const thick = Math.max(3, 0.075 * size);
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.7 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          <MainLines lines={fit.lines} size={size} k={k} align={align} gap={0.3}
            y={(li) => riseY(f, starts[li], out + 3 + li * ex)}
            fill={(li, wi, w) => { const s = w.key ? shareOf(li, wi) : null; return s ? mix(WHITE, AMBER, clamp01(s.lit * 1.4)) : WHITE; }}
            ghost={(li, wi, w) => {
              const s = w.key ? shareOf(li, wi) : null;
              if (!s || s.p <= 0) return null;
              // One run under consecutive key words: square where it joins a neighbour, round only at its two ends.
              const fromLeft = wi > 0 && fit.lines[li][wi - 1].key;
              const r = `${(thick / 2).toFixed(2)}px`;
              const l = fromLeft ? "0" : r;
              const e = s.joins ? "0" : r;
              return (
                <span style={{ position: "absolute", left: 0, top: "1.03em", height: thick, background: AMBER,
                  width: s.joins ? `calc(100% + ${(s.len - wEm(w.t) + 0.02).toFixed(4)}em)` : "100%",
                  borderRadius: `${l} ${e} ${e} ${l}`, transform: `scaleX(${s.p.toFixed(4)})`, transformOrigin: "0% 50%" }} />
              );
            }} />
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 11 txt-kicker-headline
const TxtKickerHeadline: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const align = alignOf(overlay, "left");
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, align, full, 0.46);
  let kicker = caps(overlay.label) || caps(overlay.subtitle);
  let head = str(overlay.text);
  if (!kicker) {
    // "The investigation: where the water went" - the words before the colon are the kicker.
    const m = /^([^:—]{3,32})[:—]\s+(.{3,})$/.exec(head);
    if (m) {
      kicker = caps(m[1]);
      head = m[2];
    }
  }
  const fit = fitWords(keyed(wordsOf(head), str(overlay.highlight)), room, k, 52);
  const n = fit.lines.length;
  const starts = fit.lines.map((_, li) => 9 + li * 5);
  const landed = (starts[n - 1] ?? 9) + RISE;
  const ex = exitStagger(n, dur, out);
  const sound = useLookSound(n ? [WHOOSH(0, -7), SWOOSH(10, -4)] : []);
  if (!n) return null;
  const size = fit.size;
  const kPx = kicker ? subSize(kicker, room - 60 * k, k, 20, 0.2) : 0;
  const kP = easeOut(ramp(f, 3, 10));
  const kQ = easeIn(ramp(f, out + 2, 7));
  const ruleP = easeOut(ramp(f, 0, 9)) * (1 - easeIn(ramp(f, out + 1, 7)));
  const right = align === "right";
  return (
    <AbsoluteFill>
      {sound}
      <Stage align={align} full={full} push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: flexOf(align) }}>
          <Shade k={k} o={0.7 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} />
          <div style={{ display: "flex", alignItems: "center", flexDirection: right ? "row-reverse" : "row", marginBottom: size * 0.26 }}>
            <Rule w={34 * k} k={k} p={ruleP} origin={right ? "100% 50%" : "0% 50%"} />
            {kicker ? (
              <div style={{ [right ? "marginRight" : "marginLeft"]: 14 * k,
                clipPath: right ? `inset(-0.4em -0.4em -0.4em ${((1 - kP) * 100).toFixed(2)}%)`
                  : `inset(-0.4em ${((1 - kP) * 100).toFixed(2)}% -0.4em -0.4em)` }}>
                <Small text={kicker} size={kPx} k={k} p={1} q={kQ} track={0.2} maxW={room - 60 * k} />
              </div>
            ) : null}
          </div>
          <MainLines lines={fit.lines} size={size} k={k} align={align} y={(li) => riseY(f, starts[li], out + li * ex)} />
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== 12 txt-chapter-minimal
const NUMBER_WORDS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE"];
const TxtChapterMinimal: Look = ({ overlay }) => {
  const { f, dur, out, width, height, k } = useClock();
  const full = Boolean(overlay.fullFrame);
  const room = roomFor(width, height, "center", full);
  const v = typeof overlay.value === "number" && Number.isFinite(overlay.value) ? Math.round(overlay.value) : null;
  const label = caps(overlay.label) || (v !== null && v > 0 ? `CHAPTER ${NUMBER_WORDS[v - 1] || v}` : "");
  const fit = fitWords(keyed(wordsOf(overlay.text), str(overlay.highlight), false), room, k, 52);
  const n = fit.lines.length;
  const starts = fit.lines.map((_, li) => 7 + li * 5);
  const landed = (starts[n - 1] ?? 7) + RISE;
  const ex = exitStagger(n, dur, out);
  const sub = caps(overlay.subtitle);
  const sound = useLookSound(n || label ? [WHOOSH(0, -6), ...(n ? [SWOOSH(8, -5)] : [])] : []);
  if (!n && !label) return null;
  const size = fit.size;
  const lPx = label ? subSize(label, room * 0.6, k, 19, 0.32) : 0;
  const lP = easeOut(ramp(f, 2, 10));
  const lQ = easeIn(ramp(f, out + 2, 7));
  const ruleP = easeOut(ramp(f, 1, 14)) * (1 - easeIn(ramp(f, out + 1, 8)));
  const ruleW = Math.max(40 * k, 1.5 * CAP * k);
  return (
    <AbsoluteFill>
      {sound}
      <Stage align="center" full={full} mid push={pushOf(f, landed, out)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Shade k={k} o={0.8 * easeOut(ramp(f, 0, 10)) * (1 - easeIn(ramp(f, out + 2, 8)))} x={110} y={70} />
          <div style={{ display: "flex", alignItems: "center", marginBottom: n ? size * 0.3 : 0 }}>
            <Rule w={ruleW} k={k} p={ruleP} origin="100% 50%" color="rgba(255,255,255,.85)" />
            {label ? (
              <div style={{ margin: `0 ${(18 * k).toFixed(1)}px` }}>
                <Small text={label} size={lPx} k={k} p={lP} q={lQ} track={0.32} color={AMBER} />
              </div>
            ) : <div style={{ width: 10 * k }} />}
            <Rule w={ruleW} k={k} p={ruleP} origin="0% 50%" color="rgba(255,255,255,.85)" />
          </div>
          {n ? <MainLines lines={fit.lines} size={size} k={k} align="center" y={(li) => riseY(f, starts[li], out + li * ex)} /> : null}
          {sub ? (
            <div style={{ marginTop: size * 0.3 }}>
              <Small text={sub} size={subSize(sub, room, k)} k={k} p={easeOut(ramp(f, landed - 1, 10))} q={easeIn(ramp(f, out, 7))}
                maxW={room} />
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "txt-key-phrase": TxtKeyPhrase,
  "txt-quote-line": TxtQuoteLine,
  "txt-headline-words": TxtHeadlineWords,
  "txt-breaking-tag": TxtBreakingTag,
  "txt-question": TxtQuestion,
  "txt-bullet-trio": TxtBulletTrio,
  "txt-what-we-know": TxtWhatWeKnow,
  "txt-mini-timeline": TxtMiniTimeline,
  "txt-before-after": TxtBeforeAfter,
  "txt-underline-sweep": TxtUnderlineSweep,
  "txt-kicker-headline": TxtKickerHeadline,
  "txt-chapter-minimal": TxtChapterMinimal,
};
