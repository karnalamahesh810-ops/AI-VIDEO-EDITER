import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, ANTON_CAP, SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import { ordinalNumber, spokenToDigits } from "./numWords";

/**
 * PACK B - numbers and stats on the footage (the owner, 2026-10-01: clean,
 * premium, a high-end news channel; no stroke, no box - a soft dark shadow and
 * at most a feathered shade; not big - the figure's caps 48-72 px at 1080p, the
 * label 20-26 px tracked caps; white and amber; always digits; smooth
 * odometer counts; clean exits; the sound built in and soft):
 *
 *   num-lower-third   the figure with what it counts beside it on its baseline,
 *                     an amber kicker over it and a hairline under it
 *   num-percent-line  a percent counting up while a thin amber line fills its track
 *   num-rainfall      "4.5 INCHES" with a small vector cloud, drops falling from it
 *   num-wind-gauge    "60 MPH / GUSTS" beside a minimal dial, its needle sweeping
 *   num-big-figure    "90,000" large (caps 72 px), its label under it, the last word amber
 *   num-versus        two figures "22%  VS  45%", each with its label, the second amber
 *   num-trend-arrow   a figure with a small amber arrow up (or down: the planner's
 *                     label "down", a negative value, "fell"/"dropped" in the words)
 *   num-rank          "#1" rolling down to its place, the label beside it on a hairline
 *   num-split-stat    "3 DEAD · 12 MISSING": up to three figures with their words
 *   num-water-level   "8.9 FT" beside a staff gauge: the water line rises, a dashed
 *                     amber flood-stage mark (overlay.total or "flood stage N" said)
 *   num-temperature   "102°F" beside a slim thermometer (amber hot, ice cold)
 *   num-money         "$1.2 BILLION": the $ small and amber, the scale word beside
 *   num-step-of       "3 OF 5": the digit steps up as the segments light one by one
 *
 * Every figure rolls like the bold count's odometer (LibBoldText bt-count: the
 * columns ease out and land left to right); the glyphs rise out of a mask and
 * drop back into it at the exit. Low on the left or the right at the safe
 * margin (overlay.align), the lower third, clear of the captions; a full-screen
 * scene centres it. Values come from value / prefix / suffix / total / items,
 * else from the words (spoken numbers in digits, numWords.ts); a look with no
 * number shows its words. The sound is scheduled from the frames the digits
 * move on (useLookSound): a soft tick per change (never two within 2 frames)
 * and a soft count-final click where the figure lands - never a hit.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Align = "left" | "right" | "center";

// ------------------------------------------------------------------ the type
const WHITE = "#FFFFFF";
const AMBER = "#F5B400";
const ICE = "#D9EEFF";
const TRACK_FILL = "rgba(255,255,255,.28)";   // a line's or a dial's empty track
const EXIT = 10;                 // 30-fps frames the look takes to leave
const LABEL_PX = 25;             // the label (Inter Tight 700 caps, cap ~18 px at 1080p)
const LABEL_TRACK = 0.15;
const MAIN_TRACK = 0.012;
const ANTON_TOP = 0.065;         // Anton in a 1 em line box: caps from 0.065 em to the baseline at 0.924 em
const ANTON_BASE = 0.924;
const SUB_TOP = 0.136;           // Inter Tight: caps from 0.136 em to the baseline at 0.864 em
const SUB_BASE = 0.864;
const MASK = "inset(-0.02em -0.6em -0.1em -0.6em)";
const BELOW = 1.2;               // em under the line a hidden glyph waits
const RISE = 8;                  // frames a glyph takes to rise and settle
const DIGIT_W = 0.494;           // an odometer column (Anton's digit advance)
const STEP = 1.15;               // em between two digits on a column's strip

/** Anton's advance widths (em). */
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, "%": 1.057,
  $: 0.462, "°": 0.389, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "&": 0.52, "/": 0.405,
  "+": 0.355, "(": 0.291, ")": 0.291, "?": 0.492, "!": 0.229, "#": 0.546,
};
const advOf = (c: string) => (/[0-9]/.test(c) ? DIGIT_W : ADV[c] ?? 0.48);
const widthEm = (s: string, track = MAIN_TRACK) => Array.from(s).reduce((a, c) => a + advOf(c) + track, 0);
/** Inter Tight 700 caps, roughly (em). */
const subEm = (s: string, track = LABEL_TRACK) =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.234 : /[0-9]/.test(c) ? 0.56 : /[MW]/.test(c) ? 0.86
    : /[IJ1.,:'·]/.test(c) ? 0.3 : 0.64) + track, 0);

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeOutQuart = (t: number) => 1 - (1 - t) ** 4;
const easeIn = (t: number) => t * t * t;
/** Ease-out with a small overshoot: the settle. */
const settle = (t: number, s = 0.9) => 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2;
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
const numOf = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && /^\s*-?[\d,]*\.?\d+\s*$/.test(v)) {
    const n = Number(v.replace(/[,\s]/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
};
/** A small stable jitter per index (tick pitches), no Math.random. */
const jitter = (i: number) => ((Math.sin(i * 12.9898 + 4.1) * 43758.5453) % 1 + 1) % 1;
const px = (n: number, k: number) => `${(n * k).toFixed(2)}px`;
const trimEnds = (s: string) => s.replace(/\s+/g, " ").replace(/^[\s,.:;·\-–—&]+|[\s,.:;·\-–—&]+$/g, "").trim();

/** Split a line of words into two balanced lines. */
const twoLines = (s: string, em: (x: string) => number = subEm): string[] => {
  const words = s.split(" ");
  if (words.length < 2) return [s];
  let best = [s];
  let score = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(" ");
    const b = words.slice(i).join(" ");
    const d = Math.max(em(a), em(b));
    if (d < score) {
      score = d;
      best = [a, b];
    }
  }
  return best;
};

// ------------------------------------------------------------------ the numbers
type Unit = { pre: string; top: string; tag: string; scale: string };
const NO_UNIT: Unit = { pre: "", top: "", tag: "", scale: "" };
const SCALE_X: Record<string, number> = { THOUSAND: 1e3, MILLION: 1e6, BILLION: 1e9, TRILLION: 1e12 };
const SCALE_LETTER: Record<string, string> = { K: "THOUSAND", M: "MILLION", MN: "MILLION", B: "BILLION", BN: "BILLION",
  T: "TRILLION" };

/** A unit as the looks write it: a sign at the cap top (%, °F), a word beside (FT, MPH), a scale (BILLION), a $ before. */
const unitOf = (raw: string, money = false): Unit => {
  const u = raw.toUpperCase().replace(/\s+/g, " ").replace(/\.$/, "").trim();
  if (!u) return NO_UNIT;
  if (u === "%" || /^PER ?CENT$|^PCT$/.test(u)) return { ...NO_UNIT, top: "%" };
  if (/^°\s?F$|^DEGREES? (F|FAHRENHEIT)$|^FAHRENHEIT$/.test(u)) return { ...NO_UNIT, top: "°F" };
  if (/^°\s?C$|^DEGREES? (C|CELSIUS)$|^CELSIUS$/.test(u)) return { ...NO_UNIT, top: "°C" };
  if (u === "°" || /^DEGREES?$/.test(u)) return { ...NO_UNIT, top: "°" };
  if (/^(USD|DOLLARS?|\$)$/.test(u)) return { ...NO_UNIT, pre: "$" };
  if (SCALE_X[u]) return { ...NO_UNIT, scale: u };
  if (money && SCALE_LETTER[u]) return { ...NO_UNIT, scale: SCALE_LETTER[u] };
  if (/^(FT|FEET|FOOT)$/.test(u)) return { ...NO_UNIT, tag: "FT" };
  if (/^(IN|INCH|INCHES|")$/.test(u)) return { ...NO_UNIT, tag: "INCHES" };
  if (/^(MPH|MILES (PER|AN) HOUR)$/.test(u)) return { ...NO_UNIT, tag: "MPH" };
  if (/^(KM\/?H|KPH|KMH)$/.test(u)) return { ...NO_UNIT, tag: "KM/H" };
  return { ...NO_UNIT, tag: u.slice(0, 10) };
};
const mergeUnit = (mine: Unit, said: Unit): Unit => ({
  pre: mine.pre || said.pre, top: mine.top || said.top, tag: mine.tag || said.tag, scale: mine.scale || said.scale,
});

/** A number in the words, with a $ / # before it and its unit after it. */
const NUM_RX = /(\$|#|\bNO\.\s?|\bNUMBER\s)?((?:(?<![A-Z0-9])-)?\d[\d,]*(?:\.\d+)?)(?:(K|M|MN|B|BN)\b|\s?(%|°\s?[FC]?(?![A-Z])|PER ?CENT\b|DEGREES?(?:\s(?:F|C|FAHRENHEIT|CELSIUS)\b)?|FEET\b|FOOT\b|FT\b|INCHES\b|INCH\b|MPH\b|MILES (?:PER|AN) HOUR\b|KM\/H\b|KPH\b|THOUSAND\b|MILLION\b|BILLION\b|TRILLION\b))?/;

type Fig = {
  value: number | null;
  decimals: number;
  unit: Unit;
  /** What the figure counts (caps), the number taken out of the words. */
  label: string;
  /** A second line: the subtitle, or the label field when it is not the planner's "up" / "down". */
  extra: string;
  /** The words in caps as given (spoken numbers in digits). */
  words: string;
};

const decimalsOf = (raw: string) => Math.min(2, (raw.split(".")[1] || "").length);
const cut = (s: string, a: number, b: number) => trimEnds(`${s.slice(0, a)} ${s.slice(b)}`);

/** The figure of an overlay: its value, how it is written and what it counts. */
const figureOf = (ov: Overlay, money = false): Fig => {
  const words = spokenToDigits(str(ov.text)).toUpperCase().replace(/[’]/g, "'");
  let value = numOf(ov.value);
  let decimals = value === null ? 0 : decimalsOf(String(value));
  const pre0 = str(ov.prefix).slice(0, 2);
  let unit = unitOf(str(ov.suffix), money || pre0 === "$");
  if (pre0) unit = { ...unit, pre: pre0 === "$" ? "$" : unit.pre };
  let label = words;
  const m = NUM_RX.exec(words);
  if (m) {
    const n = Number(m[2].replace(/,/g, ""));
    const said = unitOf(m[3] || m[4] || "", money || m[1] === "$" || unit.pre === "$");
    const sign: Unit = { ...said, pre: said.pre || (m[1] === "$" ? "$" : "") };
    if (Number.isFinite(n)) {
      const scaled = said.scale ? n * SCALE_X[said.scale] : n;
      const same = value !== null && (Math.abs(n - value) < 1e-9 || Math.abs(scaled - value) <= 1e-6 * Math.max(1, Math.abs(value)));
      if (value === null) {
        value = n;
        decimals = decimalsOf(m[2]);
      }
      if (value === n || same) {
        unit = mergeUnit(unit, sign);
        label = cut(words, m.index, m.index + m[0].length);
      }
    }
  }
  const lab = str(ov.label).toUpperCase();
  const extra = trimEnds(spokenToDigits(str(ov.subtitle) || (/^(UP|DOWN)$/.test(lab) ? "" : lab)).toUpperCase()).slice(0, 40);
  return { value, decimals, unit, label: trimEnds(label).slice(0, 44), extra: extra === trimEnds(label) ? "" : extra, words };
};

const group = (w: string) => w.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
/** 90000 -> "90,000", 8.9 -> "8.9", 22 -> "22". */
const fmt = (v: number, decimals: number): string => {
  const fixed = Math.abs(v).toFixed(Math.max(0, Math.min(2, decimals)));
  const [w, f] = fixed.split(".");
  return `${v < 0 ? "-" : ""}${group(w)}${f ? `.${f}` : ""}`;
};
/** Up to two decimals, the trailing zeros dropped: 1.20 -> "1.2". */
const decimalsFor = (v: number) => {
  const s = (Math.round(Math.abs(v) * 100) / 100).toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return decimalsOf(s);
};

// ------------------------------------------------------------------ the odometer
type Roll = { cols: number[]; from: number[]; to: number[]; c0: number; ends: number[] };

/**
 * A figure's odometer (as the bold count's): every digit column runs on a
 * 0-9 strip easing out, the columns landing left to right 1.5 frames apart,
 * the last at c0 + cd; `down` runs the strip backwards from the 9s (a rank).
 */
const rollOf = (text: string, c0: number, cd: number, down = false): Roll => {
  const chars = Array.from(text);
  const cols: number[] = [];
  chars.forEach((c, i) => {
    if (/[0-9]/.test(c)) cols.push(i);
  });
  const nc = cols.length;
  const ends = cols.map((_, c) => c0 + cd - (nc - 1 - c) * 1.5);
  const from: number[] = [];
  const to: number[] = [];
  cols.forEach((i, c) => {
    const d = Number(chars[i]);
    const laps = Math.min(3, 1 + (nc - 1 - c));
    from.push(down ? 10 * laps + 9 : 0);
    to.push(down ? d : d + 10 * laps);
  });
  return { cols, from, to, c0, ends };
};
const posAt = (r: Roll, c: number, f: number) =>
  r.from[c] + (r.to[c] - r.from[c]) * easeOutQuart(clamp01((f - r.c0) / Math.max(1, r.ends[c] - r.c0)));
const landOf = (r: Roll) => (r.ends.length ? Math.max(...r.ends) : r.c0);
const rollPos = (r: Roll, f: number) => (i: number) => {
  const c = r.cols.indexOf(i);
  return c >= 0 ? posAt(r, c, f) : null;
};

/** A soft tick on each change of any column (never two within `gap` frames, rising a little), none in the 2 frames before a landing. */
const rollTicks = (rolls: Roll[], lands: number[], gap = 2): SoundCue[] => {
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
    cues.push({ name: "ui-tick", alt: ["letter-tick", "tick"], at: f, gain_db: -8 + 2 * p,
      pitch: 0.94 + 0.14 * p + 0.03 * jitter(n++) });
    last = f;
  }
  return cues;
};
/** The soft click where a figure lands (count-final; never an impact). */
const landClicks = (lands: number[]): SoundCue[] => {
  const out: SoundCue[] = [];
  [...lands].sort((a, b) => a - b).forEach((l) => {
    const at = Math.round(l);
    if (!out.length || at - out[out.length - 1].at >= 6) out.push({ name: "count-final", alt: ["ui-click", "tick"], at, gain_db: -3 });
  });
  return out;
};

// ------------------------------------------------------------------ timing and place
type Clock = { f: number; S: number; k: number; width: number; height: number; end: number; exit: number };
/** The look's time in 30-fps frames (f), its exit EXIT frames before its end. */
const useClock = (): Clock => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const S = fps / 30;
  const end = durationInFrames / S;
  return { f: frame / S, S, k, width, height, end, exit: Math.max(end * 0.5, end - EXIT) };
};

const alignOf = (ov: Overlay): Align => {
  if (ov.fullFrame) return "center";
  const a = String(ov.align || "").toLowerCase();
  return a === "right" || a === "center" ? a : "left";
};
const itemsAlign = (a: Align) => (a === "right" ? "flex-end" : a === "center" ? "center" : "flex-start");
const maxWOf = (t: Clock, a: Align, full: boolean) => (a === "center" || full ? 0.66 : 0.42) * t.width;

/** The soft dark drop shadows under the letters (no edge line, no stroke). */
const shadow = (k: number, light = false) => (light
  ? `drop-shadow(0 0 ${px(1, k)} rgba(0,0,0,.45)) drop-shadow(0 ${px(2, k)} ${px(6, k)} rgba(0,0,0,.42))`
  : `drop-shadow(0 0 ${px(1.2, k)} rgba(0,0,0,.5)) drop-shadow(0 ${px(2, k)} ${px(3, k)} rgba(0,0,0,.34)) `
    + `drop-shadow(0 ${px(5, k)} ${px(16, k)} rgba(0,0,0,.4))`);

/**
 * The block in the lower third at the safe margin (6.5 % of the width in, its
 * foot a quarter of the height up), centred on a full-screen scene, behind it
 * a feathered shade (no edge anywhere), a slow push while it holds.
 */
const Block: React.FC<{ t: Clock; align: Align; full: boolean; land: number; shade?: number; children: React.ReactNode }> =
  ({ t, align, full, land, shade = 1, children }) => {
    const side = Math.max(t.width * 0.065, 96 * t.k);
    const foot = t.height * 0.25;
    const pos: React.CSSProperties = full
      ? { left: 0, right: 0, top: 0, bottom: 0, justifyContent: "center", alignItems: "center" }
      : align === "center"
        ? { left: side, right: side, bottom: foot, alignItems: "center" }
        : align === "right"
          ? { right: side, bottom: foot, alignItems: "flex-end" }
          : { left: side, bottom: foot, alignItems: "flex-start" };
    const origin = full || align === "center" ? "50% 100%" : align === "right" ? "100% 100%" : "0% 100%";
    const push = 1 + 0.012 * clamp01((t.f - land) / Math.max(1, t.exit - land));
    const shadeP = easeOut(clamp01(t.f / 10)) * (1 - easeIn(clamp01((t.f - t.exit - 2) / 8)));
    return (
      <AbsoluteFill>
        <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos,
          transformOrigin: origin, transform: `scale(${((full ? 1.3 : 1) * push).toFixed(5)})` }}>
          <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: itemsAlign(align),
            textAlign: align }}>
            {shade > 0 ? (
              <div style={{ position: "absolute", left: "-16%", right: "-16%", top: "-34%", bottom: "-36%", zIndex: -1,
                background: "radial-gradient(closest-side, rgba(0,0,0,.44), rgba(0,0,0,.3) 50%, rgba(0,0,0,.1) 78%, rgba(0,0,0,0) 100%)",
                filter: `blur(${(18 * t.k).toFixed(1)}px)`, opacity: shadeP * shade }} />
            ) : null}
            {children}
          </div>
        </div>
      </AbsoluteFill>
    );
  };

// ------------------------------------------------------------------ lettering
/** One odometer column: the digit at `pos` and the next one under it, rolling through the window. */
const Column: React.FC<{ pos: number; color: string }> = ({ pos, color }) => {
  const base = Math.floor(pos + 1e-6);
  const frac = Math.max(0, pos - base);
  const a = ((base % 10) + 10) % 10;
  const cell = (d: number, y: number) => (
    <span style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "1em", textAlign: "center", color,
      transform: y ? `translateY(${y.toFixed(4)}em)` : undefined }}>{d}</span>
  );
  return (
    <span style={{ position: "relative", display: "inline-block", width: `${DIGIT_W}em`, height: "1em" }}>
      {cell(a, -frac * STEP)}
      {frac > 0.001 ? cell((a + 1) % 10, (1 - frac) * STEP) : null}
    </span>
  );
};

/** A glyph's offset (em): up out of the mask with a small settle from `start`, back down into it at the exit. */
const glyphY = (t: Clock, start: number, exitIndex: number, exitStep: number) => {
  if (t.f < start) return BELOW;
  const p = clamp01((t.f - start) / RISE);
  const e = easeIn(clamp01((t.f - (t.exit + exitIndex * exitStep)) / 6));
  return BELOW * (1 - settle(p)) + e * BELOW;
};

/**
 * A line of Anton glyphs in its mask, each rising in a frame after the one
 * before (from `enter`) and dropping back at the exit; `pos(i)` rolls glyph i
 * as an odometer column.
 */
const Glyphs: React.FC<{
  text: string; size: number; t: Clock; enter: number; color?: string | ((i: number) => string);
  pos?: (i: number) => number | null; exitFrom?: number; light?: boolean; stagger?: number;
}> = ({ text, size, t, enter, color = WHITE, pos, exitFrom = 0, light, stagger = 1 }) => {
  const chars = Array.from(text);
  const exitStep = Math.min(0.5, 4 / Math.max(1, chars.length));
  return (
    <div style={{ position: "relative", fontFamily: ANTON, fontWeight: 400, fontSize: size, lineHeight: 1, whiteSpace: "pre",
      letterSpacing: 0 }}>
      <div style={{ filter: shadow(t.k, light) }}>
        <div style={{ clipPath: MASK }}>
          {chars.map((ch, i) => {
            const off = glyphY(t, enter + i * stagger, exitFrom + i, exitStep);
            const fill = typeof color === "function" ? color(i) : color;
            const box: React.CSSProperties = { display: "inline-block", verticalAlign: "top", height: "1em",
              marginRight: `${MAIN_TRACK}em`, transform: off ? `translateY(${off.toFixed(4)}em)` : undefined,
              visibility: off >= BELOW - 1e-3 ? "hidden" : undefined };
            if (ch === " ") return <span key={i} style={{ ...box, width: `${ADV[" "]}em` }} />;
            const p = pos ? pos(i) : null;
            if (p !== null) return <span key={i} style={{ ...box, position: "relative" }}><Column pos={p} color={fill} /></span>;
            return <span key={i} style={{ ...box, color: fill }}>{ch}</span>;
          })}
        </div>
      </div>
    </div>
  );
};

type Part = { text: string; color?: string };
/** The label: tracked Inter Tight caps, parts parted by an amber dot; in from below as its tracking closes, out with a fade. */
const Label: React.FC<{ parts: Array<string | Part>; size: number; t: Clock; inAt: number; track?: number }> =
  ({ parts, size, t, inAt, track = LABEL_TRACK }) => {
    const ps = parts.map((p) => (typeof p === "string" ? { text: p } : p)).filter((p) => p.text);
    if (!ps.length || !(size > 0)) return null;
    const p = easeOut(clamp01((t.f - inAt) / 12));
    const q = easeIn(clamp01((t.f - t.exit) / 7));
    return (
      <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1,
        letterSpacing: `${(track + 0.1 * (1 - p)).toFixed(4)}em`, textTransform: "uppercase", whiteSpace: "nowrap",
        color: "rgba(255,255,255,.96)", opacity: p * (1 - q), transform: `translateY(${((1 - p) * 0.5 + q * 0.4).toFixed(4)}em)`,
        filter: shadow(t.k, true) }}>
        {ps.map((x, i) => (
          <React.Fragment key={i}>
            {i ? <span style={{ display: "inline-block", width: "0.22em", height: "0.22em", borderRadius: "50%",
              margin: "0 0.6em 0 0.44em", transform: "translateY(-0.12em)", verticalAlign: "middle", background: AMBER }} /> : null}
            <span style={x.color ? { color: x.color } : undefined}>{x.text}</span>
          </React.Fragment>
        ))}
      </div>
    );
  };

/** Unit words beside a figure ("MPH" / "GUSTS"), cap-top aligned, two of them filling its cap height. */
const Tags: React.FC<{ tags: string[]; size: number; t: Clock; inAt: number; gap: number; colors?: string[] }> =
  ({ tags, size, t, inAt, gap, colors }) => {
    if (!tags.length) return null;
    const cap = size * ANTON_CAP;
    const tagCap = tags.length > 1 ? cap * 0.41 : cap * 0.4;
    const tagPx = tagCap / SUBLINE_CAP;
    const between = tags.length > 1 ? cap - 2 * tagCap : 0;
    const p = easeOut(clamp01((t.f - inAt) / 10));
    const q = easeIn(clamp01((t.f - t.exit) / 6));
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", textAlign: "left", marginLeft: gap,
        paddingTop: size * ANTON_TOP - tagPx * SUB_TOP, filter: shadow(t.k, true) }}>
        {tags.map((x, i) => (
          <div key={i} style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: tagPx, lineHeight: 1, letterSpacing: "0.06em",
            whiteSpace: "nowrap", color: (colors && colors[i]) || WHITE, marginTop: i ? between - tagPx * (1 - SUBLINE_CAP) : 0,
            opacity: clamp01(p * 1.6) * (1 - q), transform: `translateY(${((1 - p) * 0.8 + q * 0.6).toFixed(4)}em)` }}>{x}</div>
        ))}
      </div>
    );
  };
const tagsEm = (tags: string[]) => (tags.length
  ? Math.max(...tags.map((x) => subEm(x, 0.06))) * (ANTON_CAP * 0.41) / SUBLINE_CAP + 0.16 : 0);

/** A figure with its signs and units: a small sign before it at the cap top ($, #), one after it (%, °F), unit words beside. */
type StatSpec = { fig: string; size: number; pos?: (i: number) => number | null; pre?: string; top?: string; tags?: string[];
  color?: string; signColor?: string; tagColors?: string[]; enter?: number; tagIn?: number; exitFrom?: number };
const statEm = (s: Omit<StatSpec, "size">) => widthEm(s.fig) + (s.pre ? widthEm(s.pre) * 0.5 + 0.03 : 0)
  + (s.top ? widthEm(s.top) * 0.5 + 0.04 : 0) + tagsEm(s.tags || []);
const Stat: React.FC<{ s: StatSpec; t: Clock }> = ({ s, t }) => {
  const enter = s.enter ?? 2;
  const small = s.size * 0.5;
  const n = Array.from(s.fig).length;
  const ex = s.exitFrom ?? 0;
  return (
    <div style={{ display: "flex", alignItems: "flex-start" }}>
      {s.pre ? (
        <div style={{ marginRight: s.size * 0.03, paddingTop: (s.size - small) * ANTON_TOP }}>
          <Glyphs text={s.pre} size={small} t={t} enter={enter} color={s.signColor ?? AMBER} exitFrom={ex} />
        </div>
      ) : null}
      <Glyphs text={s.fig} size={s.size} t={t} enter={enter + (s.pre ? 1 : 0)} pos={s.pos} color={s.color ?? WHITE}
        exitFrom={ex + (s.pre ? 1 : 0)} />
      {s.top ? (
        <div style={{ marginLeft: s.size * 0.04, paddingTop: (s.size - small) * ANTON_TOP }}>
          <Glyphs text={s.top} size={small} t={t} enter={enter + Math.min(6, n)} color={s.signColor ?? WHITE} exitFrom={ex + n} />
        </div>
      ) : null}
      {s.tags && s.tags.length ? (
        <Tags tags={s.tags} size={s.size} t={t} inAt={s.tagIn ?? 18} gap={s.size * 0.16} colors={s.tagColors} />
      ) : null}
    </div>
  );
};

/** The figure's size: caps `cap` px at 1080p, shrunk to fit `em` wide in maxW (never under 72 %). */
const sizeFor = (cap: number, t: Clock, em: number, maxW: number) =>
  Math.max((cap / ANTON_CAP) * t.k * 0.72, Math.min((cap / ANTON_CAP) * t.k, maxW / Math.max(0.5, em)));
/** The label's size and lines: 25 px, two lines when long, never under 20 px. */
const labelFor = (text: string, t: Clock, maxW: number, allowTwo = true): { size: number; lines: string[] } => {
  if (!text) return { size: 0, lines: [] };
  const base = LABEL_PX * t.k;
  const lines = allowTwo && subEm(text) * base > maxW ? twoLines(text) : [text];
  const size = Math.max(20 * t.k, Math.min(base, ...lines.map((l) => maxW / Math.max(1, subEm(l)))));
  return { size, lines };
};

/** A thin line: the track draws out from the block's edge, back at the exit. */
const lineIn = (t: Clock, at = 3, frames = 14) =>
  easeOut(clamp01((t.f - at) / frames)) * (1 - easeIn(clamp01((t.f - t.exit) / 8)));

// ================================================================== a look with no number: its words
const WordsOnly: React.FC<{ overlay: Overlay; words: string; sub?: string }> = ({ overlay, words, sub }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const text = (words || "—").slice(0, 40);
  let lines = [text];
  let size = (52 / ANTON_CAP) * t.k;
  if (widthEm(text) * size > maxW) {
    lines = twoLines(text, (s) => widthEm(s));
    size = Math.max((40 / ANTON_CAP) * t.k, Math.min(size, ...lines.map((l) => maxW / Math.max(0.5, widthEm(l)))));
  }
  const total = lines.reduce((a, l) => a + Array.from(l).length, 0);
  const cues: SoundCue[] = [];
  {
    let last = -99;
    let at = 0;
    for (let i = 0; i < total && cues.length < 10; i++) {
      at = 2 + i + 5;
      if (at - last < 2) continue;
      last = at;
      cues.push({ name: "letter-tick", alt: ["ui-tick", "tick"], at, gain_db: -7 - 0.8 * jitter(i), pitch: 0.97 + 0.08 * jitter(i + 7) });
    }
  }
  const sound = useLookSound(cues);
  const lab = labelFor(sub || "", t, maxW, false);
  let from = 0;
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={2 + total + RISE}>
        {lines.map((l, li) => {
          const at = from;
          from += Array.from(l).length;
          return <Glyphs key={li} text={l} size={size} t={t} enter={2 + at} exitFrom={at} />;
        })}
        {lab.lines.length ? <div style={{ marginTop: size * 0.26 }}><Label parts={lab.lines} size={lab.size} t={t} inAt={2 + total} /></div> : null}
      </Block>
    </>
  );
};

/** The figure as a statistic: its text, sign before, sign after, unit words. */
const statText = (f: Fig) => ({
  fig: fmt(f.value ?? 0, f.decimals),
  pre: f.unit.pre === "$" ? "$" : "",
  top: f.unit.top,
  tags: [f.unit.scale || f.unit.tag].filter(Boolean),
});

// ================================================================== num-lower-third
const NumLowerThird: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <LowerThird overlay={overlay} f={f} />;
};
const LowerThird: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const st = statText(f);
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 28);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const words = f.label || f.extra;
  const kicker = f.label ? f.extra : "";
  const lpx = LABEL_PX * t.k;
  const lines = words ? (subEm(words) > 15 ? twoLines(words) : [words]) : [];
  const labEm = lines.length ? Math.max(...lines.map((l) => subEm(l))) * lpx : 0;
  const size = sizeFor(52, t, statEm(st) + (labEm ? 0.22 : 0), Math.max(maxW * 0.45, maxW - labEm));
  const figW = statEm(st) * size;
  const rowW = figW + (labEm ? size * 0.22 + labEm : 0);
  const ruleP = lineIn(t, 4, 18);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        {kicker ? (
          <div style={{ marginBottom: size * 0.2 }}>
            <Label parts={[{ text: kicker, color: AMBER }]} size={Math.max(18 * t.k, lpx * 0.82)} t={t} inAt={3} track={0.2} />
          </div>
        ) : null}
        <div style={{ display: "flex", alignItems: "flex-end", flexDirection: align === "right" ? "row-reverse" : "row" }}>
          <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 2 }} t={t} />
          {lines.length ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: itemsAlign(align),
              marginLeft: align === "right" ? 0 : size * 0.22, marginRight: align === "right" ? size * 0.22 : 0,
              marginBottom: size * (1 - ANTON_BASE) - lpx * (1 - SUB_BASE) }}>
              {lines.map((l, i) => (
                <div key={i} style={{ marginTop: i ? lpx * 0.3 : 0 }}>
                  <Label parts={[l]} size={lpx} t={t} inAt={land - 8 + 3 * i} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
        <div style={{ marginTop: size * 0.2, width: Math.min(maxW, rowW * 1.12), height: Math.max(2, 2.5 * t.k),
          transform: `scaleX(${ruleP.toFixed(4)})`, transformOrigin: align === "right" ? "100% 50%" : align === "center" ? "50% 50%" : "0% 50%",
          background: align === "right"
            ? `linear-gradient(270deg, ${AMBER} 0, ${AMBER} ${(size * 0.9).toFixed(0)}px, rgba(255,255,255,.7) ${(size * 0.9 + 1).toFixed(0)}px, rgba(255,255,255,0) 100%)`
            : `linear-gradient(90deg, ${AMBER} 0, ${AMBER} ${(size * 0.9).toFixed(0)}px, rgba(255,255,255,.7) ${(size * 0.9 + 1).toFixed(0)}px, rgba(255,255,255,0) 100%)`,
          borderRadius: 2 * t.k, filter: `drop-shadow(0 ${px(1, t.k)} ${px(3, t.k)} rgba(0,0,0,.45))` }} />
      </Block>
    </>
  );
};

// ================================================================== num-percent-line
const NumPercentLine: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <PercentLine overlay={overlay} f={f} />;
};
const PercentLine: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const st = { ...statText(f), top: f.unit.top || (f.unit.tag ? "" : "%") };
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 30);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const size = sizeFor(60, t, statEm(st), maxW);
  const lineW = Math.min(maxW, Math.max(statEm(st) * size * 2.3, 340 * t.k));
  const share = clamp01((f.value ?? 0) / 100);
  const fill = share * easeOutQuart(clamp01((t.f - C0) / Math.max(1, land - C0)));
  const p = lineIn(t, 2, 14);
  const h = Math.max(2, 3 * t.k);
  const lab = labelFor([f.label, f.extra].filter(Boolean).join(" · "), t, maxW);
  // The share always fills left to right (a right-aligned block keeps its line at the right margin).
  const side = (x: number): React.CSSProperties => ({ left: x });
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <Stat s={{ ...st, size, pos: rollPos(roll, t.f) }} t={t} />
        <div style={{ position: "relative", marginTop: size * 0.2, width: lineW, height: h * 4,
          opacity: clamp01(p * 3), transform: `scaleX(${p.toFixed(4)})`, transformOrigin: "0% 50%",
          filter: `drop-shadow(0 ${px(1, t.k)} ${px(3, t.k)} rgba(0,0,0,.5))` }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: h * 1.5, height: h, borderRadius: h, background: TRACK_FILL }} />
          {[0.25, 0.5, 0.75].map((x) => (
            <div key={x} style={{ position: "absolute", ...side(lineW * x - 0.5), top: 0, width: Math.max(1, t.k),
              height: h * 1.2, background: "rgba(255,255,255,.45)" }} />
          ))}
          <div style={{ position: "absolute", ...side(0), top: h * 1.5, height: h, borderRadius: h,
            width: lineW * fill, background: AMBER }} />
          {fill > 0.003 ? (
            <div style={{ position: "absolute", ...side(lineW * fill - h * 1.25), top: h * 0.75, width: h * 2.5,
              height: h * 2.5, borderRadius: "50%", background: WHITE, boxShadow: `0 0 ${px(8, t.k)} rgba(245,180,0,.8)` }} />
          ) : null}
        </div>
        {lab.lines.map((l, i) => (
          <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.18 }}>
            <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
          </div>
        ))}
      </Block>
    </>
  );
};

// ================================================================== num-rainfall
const NumRainfall: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <Rainfall overlay={overlay} f={f} />;
};
/** A small cloud (one shape, filled) with drops falling from it on a loop. */
const RainIcon: React.FC<{ h: number; t: Clock }> = ({ h, t }) => {
  const inP = easeOut(clamp01((t.f - 2) / 12));
  const out = 1 - easeIn(clamp01((t.f - t.exit) / 7));
  const drops = [26, 48, 70].map((x, i) => {
    const ph = (((t.f - 6 + i * 7) / 21) % 1 + 1) % 1;
    const live = t.f >= 6 + i * 3 ? 1 : 0;
    const y = 58 + 34 * ph;
    const o = live * clamp01(ph / 0.18) * clamp01((1 - ph) / 0.35);
    return (
      <path key={i} transform={`translate(${(x - 4 * ph).toFixed(2)} ${y.toFixed(2)}) rotate(14)`} opacity={o.toFixed(3)} fill={ICE}
        d="M0 -8 C2.6 -3.4 5.2 0 5.2 3 A5.2 5.2 0 1 1 -5.2 3 C-5.2 0 -2.6 -3.4 0 -8 Z" />
    );
  });
  return (
    <svg width={h * 1.1} height={h} viewBox="0 0 100 92" style={{ display: "block", overflow: "visible", opacity: inP * out,
      transform: `translateY(${((1 - inP) * 0.12 * h).toFixed(2)}px) scale(${(0.9 + 0.1 * inP).toFixed(4)})`,
      filter: shadow(t.k, true) }}>
      <g fill={WHITE}>
        <circle cx="32" cy="34" r="15" />
        <circle cx="53" cy="24" r="20" />
        <circle cx="73" cy="36" r="13" />
        <rect x="17" y="32" width="70" height="18" rx="9" />
      </g>
      {drops}
    </svg>
  );
};
const Rainfall: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const unit = f.unit.tag || "INCHES";
  // "4.5 inches of rain": the planner's noun RAIN reads OF RAIN beside the unit.
  const noun = /^(RAIN|RAINFALL)$/.test(f.label) ? "OF RAIN" : f.label;
  const short = noun && noun.length <= 9 && (noun === "OF RAIN" || !noun.includes(" ")) ? noun : "";
  const st = { ...statText(f), top: "", tags: short ? [unit, short] : [unit] };
  const C0 = 5;
  const roll = rollOf(st.fig, C0, 28);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const iconEm = 1.0 * ANTON_CAP * 1.1 + 0.2;
  const size = sizeFor(60, t, statEm(st) + iconEm, maxW);
  const lab = labelFor([short ? "" : f.label, f.extra].filter(Boolean).join(" · "), t, maxW);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginRight: size * 0.2, paddingTop: size * ANTON_TOP - size * ANTON_CAP * 0.04 }}>
            <RainIcon h={size * ANTON_CAP * 1.0} t={t} />
          </div>
          <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 3, tagColors: [WHITE, AMBER] }} t={t} />
        </div>
        {lab.lines.map((l, i) => (
          <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.26 }}>
            <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
          </div>
        ))}
      </Block>
    </>
  );
};

// ================================================================== num-wind-gauge
const NumWindGauge: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <WindGauge overlay={overlay} f={f} />;
};
/** The scale's top: the first round mark a little over the value. */
const niceMax = (v: number) => {
  const want = Math.max(1e-6, Math.abs(v) * 1.15);
  const mag = 10 ** Math.floor(Math.log10(want));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= want) return m * mag;
  return 10 * mag;
};
const polar = (cx: number, cy: number, r: number, deg: number) => {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};
const arcPath = (cx: number, cy: number, r: number, a0: number, a1: number) => {
  const [x0, y0] = polar(cx, cy, r, a0);
  const [x1, y1] = polar(cx, cy, r, a1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
};
/** A minimal dial: a 240-degree track, the amber arc and a needle sweeping to the share, a small flutter once it lands. */
const Dial: React.FC<{ d: number; share: number; t: Clock; c0: number; land: number }> = ({ d, share, t, c0, land }) => {
  const A0 = 150;
  const SWEEP = 240;
  const p = lineIn(t, 2, 12);
  const prog = easeOutQuart(clamp01((t.f - c0) / Math.max(1, land - c0)));
  const after = t.f - land;
  const flutter = after > 0 ? 1.6 * Math.sin(after * 0.9) * Math.exp(-after / 14) : 0;
  const a = A0 + SWEEP * clamp01(share) * prog + flutter;
  const [nx, ny] = polar(50, 52, 31, a);
  return (
    <svg width={d} height={d * 0.8} viewBox="0 6 100 80" style={{ display: "block", overflow: "visible", opacity: clamp01(p * 2),
      transform: `scale(${(0.92 + 0.08 * p).toFixed(4)})`, filter: shadow(t.k, true) }}>
      <path d={arcPath(50, 52, 42, A0, A0 + SWEEP)} fill="none" stroke={TRACK_FILL} strokeWidth={5} strokeLinecap="round"
        strokeDasharray={`${(SWEEP / 360) * 2 * Math.PI * 42 * p} 999`} />
      {[0, 0.25, 0.5, 0.75, 1].map((x) => {
        const [x0, y0] = polar(50, 52, 32.5, A0 + SWEEP * x);
        const [x1, y1] = polar(50, 52, 36, A0 + SWEEP * x);
        return <line key={x} x1={x0} y1={y0} x2={x1} y2={y1} stroke="rgba(255,255,255,.6)" strokeWidth={2.2} strokeLinecap="round"
          opacity={p} />;
      })}
      {a - A0 > 0.5 ? <path d={arcPath(50, 52, 42, A0, a)} fill="none" stroke={AMBER} strokeWidth={5} strokeLinecap="round" /> : null}
      <line x1={50} y1={52} x2={nx} y2={ny} stroke={WHITE} strokeWidth={3.6} strokeLinecap="round" opacity={p} />
      <circle cx={50} cy={52} r={5.5} fill={WHITE} opacity={p} />
      <circle cx={50} cy={52} r={2.4} fill={AMBER} opacity={p} />
    </svg>
  );
};
const WindGauge: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  // "60 miles per hour" reaches the planner as a length in miles: on a wind dial it is a speed.
  const unit = !f.unit.tag || /^(MI|MILES?)$/.test(f.unit.tag) ? "MPH" : f.unit.tag;
  const gust = /\bGUST/.test(`${f.words} ${f.extra}`);
  const short = gust ? "GUSTS" : f.label && f.label.length <= 9 && !f.label.includes(" ") ? f.label : "";
  const rest = gust ? trimEnds(f.label.replace(/\b(WIND\s+)?GUSTS?\b/g, "")) : short ? "" : f.label;
  const st = { ...statText(f), top: "", tags: short ? [unit, short] : [unit] };
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 30);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const dialEm = ANTON_CAP * 1.6 + 0.22;
  const size = sizeFor(60, t, statEm(st) + dialEm, maxW);
  const d = size * ANTON_CAP * 1.6;
  const lab = labelFor([rest, f.extra].filter(Boolean).join(" · "), t, maxW);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginRight: size * 0.22, marginTop: size * (ANTON_TOP + ANTON_CAP / 2) - d * 0.4 - size * 0.02 }}>
            <Dial d={d} share={(f.value ?? 0) / niceMax(f.value ?? 0)} t={t} c0={C0} land={land} />
          </div>
          <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 3, tagColors: [WHITE, AMBER] }} t={t} />
        </div>
        {lab.lines.map((l, i) => (
          <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.24 }}>
            <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
          </div>
        ))}
      </Block>
    </>
  );
};

// ================================================================== num-big-figure
const NumBigFigure: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <BigFigure overlay={overlay} f={f} />;
};
const BigFigure: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const st = statText(f);
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 32);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const size = sizeFor(72, t, statEm(st), maxW);
  const words = f.label || f.extra;
  const lab = labelFor(words, t, maxW);
  // The last word of what it counts in amber ("WITHOUT POWER"), the rest white.
  const partsOf = (line: string, last: boolean): Part[] => {
    const ws = line.split(" ");
    if (!last || (ws.length < 2 && lab.lines.length < 2)) return [{ text: line }];
    const head = ws.slice(0, -1).join(" ");
    return [...(head ? [{ text: `${head} ` }] : []), { text: ws[ws.length - 1], color: AMBER }];
  };
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <Stat s={{ ...st, size, pos: rollPos(roll, t.f) }} t={t} />
        {lab.lines.map((l, i) => (
          <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.22 }}>
            <TwoTone parts={partsOf(l, i === lab.lines.length - 1)} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
          </div>
        ))}
        {f.label && f.extra ? (
          <div style={{ marginTop: lab.size * 0.55 }}>
            <Label parts={[f.extra]} size={lab.size * 0.84} t={t} inAt={land} />
          </div>
        ) : null}
      </Block>
    </>
  );
};
/** A label line whose parts sit side by side (no dot between them), each in its own colour. */
const TwoTone: React.FC<{ parts: Part[]; size: number; t: Clock; inAt: number }> = ({ parts, size, t, inAt }) => {
  const p = easeOut(clamp01((t.f - inAt) / 12));
  const q = easeIn(clamp01((t.f - t.exit) / 7));
  return (
    <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1, whiteSpace: "pre",
      letterSpacing: `${(LABEL_TRACK + 0.1 * (1 - p)).toFixed(4)}em`, textTransform: "uppercase", color: "rgba(255,255,255,.96)",
      opacity: p * (1 - q), transform: `translateY(${((1 - p) * 0.5 + q * 0.4).toFixed(4)}em)`, filter: shadow(t.k, true) }}>
      {parts.map((x, i) => <span key={i} style={x.color ? { color: x.color } : undefined}>{x.text}</span>)}
    </div>
  );
};

// ================================================================== num-versus
type Side = { value: number; decimals: number; unit: Unit; label: string };
/** Two figures to compare: the overlay's first two items with values, else the first two numbers in its words. */
const sidesOf = (ov: Overlay): { sides: Side[]; label: string } => {
  const items = Array.isArray(ov.items) ? ov.items : [];
  const out: Side[] = [];
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const v = numOf((it as { value?: unknown }).value);
    if (v === null) continue;
    const extra = it as unknown as { suffix?: unknown; prefix?: unknown };
    const unit = mergeUnit(unitOf(str(extra.suffix) || str(ov.suffix), str(extra.prefix || ov.prefix) === "$"),
      { ...NO_UNIT, pre: str(extra.prefix || ov.prefix) === "$" ? "$" : "" });
    out.push({ value: v, decimals: decimalsOf(String(v)), unit, label: spokenToDigits(str(it.label)).toUpperCase().slice(0, 18) });
    if (out.length === 2) break;
  }
  const words = spokenToDigits(str(ov.text)).toUpperCase();
  if (out.length === 2) return { sides: out, label: trimEnds(words).slice(0, 44) };
  const found: Side[] = [];
  let rest = words;
  const rx = new RegExp(NUM_RX.source, "g");
  const spans: [number, number][] = [];
  for (const m of Array.from(words.matchAll(rx))) {
    const n = Number(m[2].replace(/,/g, ""));
    if (!Number.isFinite(n)) continue;
    const unit = unitOf(m[3] || m[4] || "", m[1] === "$");
    found.push({ value: n, decimals: decimalsOf(m[2]), unit: { ...unit, pre: unit.pre || (m[1] === "$" ? "$" : "") }, label: "" });
    spans.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
    if (found.length === 2) break;
  }
  if (found.length === 2) {
    // A unit said once ("22 vs 45 percent") is both sides'.
    const top = found[0].unit.top || found[1].unit.top;
    const tag = found[0].unit.tag || found[1].unit.tag;
    found.forEach((s) => {
      if (!s.unit.top && !s.unit.tag && !s.unit.scale) s.unit = { ...s.unit, top, tag: top ? "" : tag };
    });
    for (const [a, b] of spans.reverse()) rest = `${rest.slice(0, a)} ${rest.slice(b)}`;
    rest = trimEnds(rest.replace(/\b(VS\.?|VERSUS|COMPARED (TO|WITH)|AGAINST|AND|TO|FROM)\b/g, " ").replace(/\s+/g, " "));
    return { sides: found, label: (str(ov.label) ? trimEnds(spokenToDigits(str(ov.label)).toUpperCase()) : rest).slice(0, 44) };
  }
  return { sides: [], label: "" };
};
const NumVersus: Look = ({ overlay }) => {
  const plan = sidesOf(overlay);
  if (plan.sides.length < 2) {
    const f = figureOf(overlay);
    return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <BigFigure overlay={overlay} f={f} />;
  }
  return <Versus overlay={overlay} sides={plan.sides} label={plan.label} />;
};
const Versus: React.FC<{ overlay: Overlay; sides: Side[]; label: string }> = ({ overlay, sides, label }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const sts = sides.map((s) => ({ fig: fmt(s.value, s.decimals), pre: s.unit.pre === "$" ? "$" : "", top: s.unit.top,
    tags: [s.unit.scale || s.unit.tag].filter(Boolean) }));
  const rolls = [rollOf(sts[0].fig, 4, 24), rollOf(sts[1].fig, 12, 26)];
  const lands = rolls.map(landOf);
  const sound = useLookSound([...rollTicks(rolls, lands), ...landClicks(lands)]);
  const vsPx = 20 * t.k;
  const em = statEm(sts[0]) + statEm(sts[1]) + 0.9 + (subEm("VS", 0.2) * vsPx) / ((56 / ANTON_CAP) * t.k);
  const size = sizeFor(56, t, em, maxW);
  const sideLab = 21 * t.k;
  const lab = labelFor(label, t, maxW, false);
  const vsP = easeOut(clamp01((t.f - 10) / 10)) * (1 - easeIn(clamp01((t.f - t.exit) / 6)));
  const side = (i: number) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
      <Stat s={{ ...sts[i], size, pos: rollPos(rolls[i], t.f), enter: 2 + 8 * i, color: i ? AMBER : WHITE,
        signColor: i ? AMBER : WHITE, tagColors: [i ? AMBER : WHITE], exitFrom: 4 * i, tagIn: lands[i] - 6 }} t={t} />
      {sides[i].label ? (
        <div style={{ marginTop: size * 0.16 }}>
          <Label parts={[sides[i].label]} size={sideLab} t={t} inAt={lands[i] - 6} />
        </div>
      ) : null}
    </div>
  );
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={lands[1]}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          {side(0)}
          <div style={{ margin: `0 ${size * 0.4}px`, paddingTop: size * (ANTON_TOP + ANTON_CAP / 2) - vsPx * (SUB_TOP + SUBLINE_CAP / 2),
            fontFamily: SUBLINE, fontWeight: 700, fontSize: vsPx, lineHeight: 1, letterSpacing: "0.2em", color: AMBER,
            opacity: vsP, transform: `translateY(${((1 - vsP) * 0.4).toFixed(3)}em)`, filter: shadow(t.k, true) }}>VS</div>
          {side(1)}
        </div>
        {lab.lines.length ? (
          <div style={{ marginTop: size * 0.3 }}>
            <Label parts={lab.lines} size={lab.size} t={t} inAt={lands[1] - 2} />
          </div>
        ) : null}
      </Block>
    </>
  );
};

// ================================================================== num-trend-arrow
const DOWN_WORDS = /\b(DOWN|DROP\w*|FELL|FALL\w*|DECLIN\w*|DECREAS\w*|LOWER|LESS|LOSS|LOST|SHR[AU]NK|CUT|SANK|SUNK|PLUNG\w*|SLID|DIPP?ED)\b/;
const NumTrendArrow: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <TrendArrow overlay={overlay} f={f} />;
};
/** A small filled arrow (head and stem), drawn rather than typed. */
const Arrow: React.FC<{ h: number; down: boolean; t: Clock; land: number }> = ({ h, down, t, land }) => {
  const p = easeOut(clamp01((t.f - 8) / 12));
  const q = easeIn(clamp01((t.f - t.exit) / 6));
  const nudge = Math.sin(Math.PI * clamp01((t.f - land + 2) / 9)) * 0.1;
  const dir = down ? 1 : -1;
  const y = (1 - p) * 0.45 * -dir + nudge * dir + q * 0.4 * -dir;
  return (
    <svg width={h * 0.8} height={h} viewBox="0 0 40 50" style={{ display: "block", overflow: "visible", opacity: p * (1 - q),
      transform: `translateY(${(y * h).toFixed(2)}px) rotate(${down ? 180 : 0}deg)`, filter: shadow(t.k, true) }}>
      <path d="M20 0 L40 22 L27.5 22 L27.5 50 L12.5 50 L12.5 22 L0 22 Z" fill={AMBER} />
    </svg>
  );
};
const TrendArrow: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const lab0 = str(overlay.label).toUpperCase();
  const down = lab0 === "DOWN" || (lab0 !== "UP" && ((f.value ?? 0) < 0 || DOWN_WORDS.test(f.words)));
  const g: Fig = { ...f, value: Math.abs(f.value ?? 0) };
  const st = statText(g);
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 30);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const size = sizeFor(62, t, statEm(st) + ANTON_CAP * 0.62 * 0.8 + 0.16, maxW);
  const ah = size * ANTON_CAP * 0.62;
  const lab = labelFor([f.label, f.extra].filter(Boolean).join(" · "), t, maxW);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginRight: size * 0.14, marginTop: size * (ANTON_TOP + ANTON_CAP / 2) - ah / 2 }}>
            <Arrow h={ah} down={down} t={t} land={land} />
          </div>
          <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 2 }} t={t} />
        </div>
        {lab.lines.map((l, i) => (
          <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.24 }}>
            <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
          </div>
        ))}
      </Block>
    </>
  );
};

// ================================================================== num-rank
const RANK_RX = /(?:#\s?|\bNO\.\s?|\bNUMBER\s)(\d{1,3})\b|\b(\d{1,3})(?:ST|ND|RD|TH)\b/;
const ORD_RX = /\b(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\b/;
/** The rank (#1) and what it ranks, from value or the words ("#1", "No. 1", "number one", "first", "3rd"). */
const rankOf = (ov: Overlay): { rank: number | null; label: string; extra: string } => {
  const words = spokenToDigits(str(ov.text)).toUpperCase();
  let rank = numOf(ov.value);
  let label = words;
  const m = RANK_RX.exec(words);
  if (m) {
    const n = Number(m[1] || m[2]);
    if (rank === null || rank === n) {
      rank = n;
      label = cut(words, m.index, m.index + m[0].length);
    }
  } else {
    const o = ORD_RX.exec(words);
    const n = o ? ordinalNumber(o[1].toLowerCase()) : null;
    if (o && n !== null && (rank === null || rank === n)) {
      rank = n;
      label = cut(words, o.index, o.index + o[0].length);
    }
  }
  if (rank !== null) rank = Math.max(0, Math.round(Math.abs(rank)));
  const extra = trimEnds(spokenToDigits(str(ov.subtitle) || str(ov.label)).toUpperCase()).slice(0, 40);
  return { rank, label: trimEnds(label.replace(/^(THE|IS|AS)\s+/, "")).slice(0, 44), extra };
};
const NumRank: Look = ({ overlay }) => {
  const r = rankOf(overlay);
  return r.rank === null ? <WordsOnly overlay={overlay} words={r.label || r.extra} /> : <Rank overlay={overlay} rank={r.rank}
    label={r.label || r.extra} extra={r.label ? r.extra : ""} />;
};
const Rank: React.FC<{ overlay: Overlay; rank: number; label: string; extra: string }> = ({ overlay, rank, label, extra }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const fig = String(rank);
  const C0 = 4;
  const roll = rollOf(fig, C0, 26, true);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const lpx = LABEL_PX * t.k;
  const lines = label ? (subEm(label) > 14 ? twoLines(label) : [label]) : [];
  const labW = lines.length ? Math.max(...lines.map((l) => subEm(l))) * lpx : 0;
  const st = { fig, pre: "#" };
  const size = sizeFor(64, t, statEm(st) + 0.5, Math.max(maxW * 0.4, maxW - labW));
  const cap = size * ANTON_CAP;
  const ruleP = easeOut(clamp01((t.f - 10) / 12)) * (1 - easeIn(clamp01((t.f - t.exit) / 7)));
  const gap = lines.length > 1 ? cap - 2 * lpx * SUBLINE_CAP : 0;
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 2 }} t={t} />
          {lines.length ? (
            <>
              <div style={{ margin: `${size * ANTON_TOP}px ${size * 0.2}px 0 ${size * 0.24}px`, width: Math.max(2, 2.5 * t.k), height: cap,
                background: AMBER, transform: `scaleY(${ruleP.toFixed(4)})`, transformOrigin: "50% 0%", borderRadius: 2 * t.k,
                filter: `drop-shadow(0 ${px(1, t.k)} ${px(3, t.k)} rgba(0,0,0,.45))` }} />
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start",
                paddingTop: lines.length > 1 ? size * ANTON_TOP - lpx * SUB_TOP
                  : size * (ANTON_TOP + ANTON_CAP / 2) - lpx * (SUB_TOP + SUBLINE_CAP / 2) }}>
                {lines.map((l, i) => (
                  <div key={i} style={{ marginTop: i ? gap - lpx * (1 - SUBLINE_CAP) : 0 }}>
                    <Label parts={[l]} size={lpx} t={t} inAt={land - 10 + 3 * i} />
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>
        {extra ? (
          <div style={{ marginTop: size * 0.22 }}>
            <Label parts={[extra]} size={lpx * 0.84} t={t} inAt={land} />
          </div>
        ) : null}
      </Block>
    </>
  );
};

// ================================================================== num-split-stat
type Pair = { value: number; decimals: number; pre: string; top: string; word: string };
const STOP = new Set(["AND", "OR", "WITH", "IN", "OF", "FROM", "TO", "WHILE", "BUT", "AS", "THE", "AT", "ON", "BY"]);
/** The figures of a split stat: the items with values, else every "N WORD" in the words (up to three). */
const pairsOf = (ov: Overlay): { pairs: Pair[]; label: string } => {
  const out: Pair[] = [];
  for (const it of Array.isArray(ov.items) ? ov.items : []) {
    if (!it || typeof it !== "object") continue;
    const v = numOf((it as { value?: unknown }).value);
    if (v === null) continue;
    const ex = it as unknown as { suffix?: unknown; prefix?: unknown };
    const u = unitOf(str(ex.suffix));
    out.push({ value: v, decimals: decimalsOf(String(v)), pre: str(ex.prefix) === "$" ? "$" : "", top: u.top,
      word: spokenToDigits(str(it.label)).toUpperCase().slice(0, 14) });
    if (out.length === 3) break;
  }
  const words = spokenToDigits(str(ov.text)).toUpperCase();
  const extra = trimEnds(spokenToDigits(str(ov.subtitle) || str(ov.label)).toUpperCase()).slice(0, 40);
  if (out.length) return { pairs: out, label: extra || (out.length > 1 ? trimEnds(words).slice(0, 44) : "") };
  const rx = /(\$?)(\d[\d,]*(?:\.\d+)?)\s*(%)?\s*((?:[A-Z][A-Z'\-]*)(?:\s+[A-Z][A-Z'\-]*)?)?/g;
  let rest = words;
  const spans: [number, number][] = [];
  for (const m of Array.from(words.matchAll(rx))) {
    const n = Number(m[2].replace(/,/g, ""));
    if (!Number.isFinite(n)) continue;
    let ws = (m[4] || "").split(" ").filter(Boolean);
    const stop = ws.findIndex((w) => STOP.has(w));
    if (stop >= 0) ws = ws.slice(0, stop);
    out.push({ value: n, decimals: decimalsOf(m[2]), pre: m[1] ? "$" : "", top: m[3] ? "%" : "", word: ws.join(" ").slice(0, 14) });
    const at = m.index ?? 0;
    spans.push([at, at + m[0].length - (m[4] || "").length + ws.join(" ").length]);
    if (out.length === 3) break;
  }
  const v = numOf(ov.value);
  if (!out.length && v !== null) {
    out.push({ value: v, decimals: decimalsOf(String(v)), pre: str(ov.prefix) === "$" ? "$" : "", top: unitOf(str(ov.suffix)).top,
      word: trimEnds(words).split(" ").slice(0, 2).join(" ").slice(0, 14) });
    return { pairs: out, label: extra };
  }
  for (const [a, b] of spans.reverse()) rest = `${rest.slice(0, a)} ${rest.slice(b)}`;
  rest = trimEnds(rest.replace(/\b(AND|WITH|PLUS)\b/g, " "));
  return { pairs: out, label: extra || rest.slice(0, 44) };
};
const NumSplitStat: Look = ({ overlay }) => {
  const plan = pairsOf(overlay);
  if (!plan.pairs.length) {
    const words = spokenToDigits(str(overlay.text)).toUpperCase();
    return <WordsOnly overlay={overlay} words={trimEnds(words)} />;
  }
  return <SplitStat overlay={overlay} pairs={plan.pairs} label={plan.label} />;
};
const SplitStat: React.FC<{ overlay: Overlay; pairs: Pair[]; label: string }> = ({ overlay, pairs, label }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const figs = pairs.map((p) => fmt(p.value, p.decimals));
  const rolls = figs.map((s, i) => rollOf(s, 4 + 8 * i, 24));
  const lands = rolls.map(landOf);
  const sound = useLookSound([...rollTicks(rolls, lands), ...landClicks(lands)]);
  const wordPx = (cap: number) => (cap * ANTON_CAP * 0.42) / SUBLINE_CAP;
  const base = (54 / ANTON_CAP) * t.k;
  const em = pairs.reduce((a, p, i) => a + statEm({ fig: figs[i], pre: p.pre, top: p.top })
    + (p.word ? 0.16 + (subEm(p.word, 0.08) * wordPx(base)) / base : 0) + (i ? 0.75 : 0), 0);
  const size = sizeFor(54, t, em, maxW);
  const wpx = wordPx(size);
  const lab = labelFor(label, t, maxW, false);
  const dotP = (i: number) => easeOut(clamp01((t.f - lands[i - 1] + 4) / 8)) * (1 - easeIn(clamp01((t.f - t.exit) / 6)));
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={lands[lands.length - 1]}>
        <div style={{ display: "flex", alignItems: "flex-end" }}>
          {pairs.map((p, i) => (
            <React.Fragment key={i}>
              {i ? (
                <div style={{ alignSelf: "flex-start", marginLeft: size * 0.3, marginRight: size * 0.3,
                  // A middle dot: centred on the words' caps, on the figures' baseline.
                  marginTop: size * ANTON_BASE - (wpx * SUBLINE_CAP) / 2 - size * 0.05,
                  width: size * 0.1, height: size * 0.1, borderRadius: "50%", background: AMBER, opacity: dotP(i),
                  transform: `scale(${(0.4 + 0.6 * dotP(i)).toFixed(3)})`, filter: shadow(t.k, true) }} />
              ) : null}
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <Stat s={{ fig: figs[i], pre: p.pre, top: p.top, size, pos: rollPos(rolls[i], t.f), enter: 2 + 8 * i, exitFrom: 3 * i,
                  color: i === pairs.length - 1 && pairs.length > 1 ? WHITE : WHITE }} t={t} />
                {p.word ? (
                  <div style={{ marginLeft: size * 0.16, marginBottom: size * (1 - ANTON_BASE) - wpx * (1 - SUB_BASE) }}>
                    <Label parts={[{ text: p.word, color: i ? AMBER : WHITE }]} size={wpx} t={t} inAt={lands[i] - 7} track={0.08} />
                  </div>
                ) : null}
              </div>
            </React.Fragment>
          ))}
        </div>
        {lab.lines.length ? (
          <div style={{ marginTop: size * 0.26 }}>
            <Label parts={lab.lines} size={lab.size} t={t} inAt={lands[lands.length - 1] - 2} />
          </div>
        ) : null}
      </Block>
    </>
  );
};

// ================================================================== num-water-level
const FLOOD_RX = /FLOOD STAGE(?:\s(?:IS|OF|AT))?\s(\d+(?:\.\d+)?)/;
const NumWaterLevel: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <WaterLevel overlay={overlay} f={f} />;
};
/** A staff gauge: a scale with ticks, the water rising to the level, a dashed amber flood-stage mark. */
const Gauge: React.FC<{ w: number; h: number; value: number; flood: number | null; top: number; t: Clock; c0: number; land: number }> =
  ({ w, h, value, flood, top, t, c0, land }) => {
    const p = lineIn(t, 2, 12);
    const prog = easeOutQuart(clamp01((t.f - c0) / Math.max(1, land - c0)));
    const yOf = (v: number) => h - clamp01(v / top) * h;
    const level = yOf(value * prog);
    const k = t.k;
    const sw = Math.max(1.5, 2 * k);
    const steps = 5;
    const amp = 1.4 * k;
    const ph = t.f * 0.22;
    let wave = `M0 ${(level + amp * Math.sin(ph)).toFixed(2)}`;
    for (let i = 1; i <= 12; i++) {
      const x = (w * i) / 12;
      wave += ` L${x.toFixed(2)} ${(level + amp * Math.sin(ph + i * 0.9)).toFixed(2)}`;
    }
    const fy = flood !== null ? yOf(flood) : 0;
    const crossed = flood !== null && value * prog >= flood;
    return (
      <svg width={w * 1.25} height={h} viewBox={`0 0 ${(w * 1.25).toFixed(2)} ${h.toFixed(2)}`}
        style={{ display: "block", overflow: "visible", opacity: clamp01(p * 2), filter: shadow(k, true) }}>
        <defs>
          <linearGradient id="nb-water" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={ICE} stopOpacity={0.42} />
            <stop offset="1" stopColor={ICE} stopOpacity={0.06} />
          </linearGradient>
        </defs>
        <rect x={sw} y={level} width={w - sw} height={Math.max(0, h - level)} fill="url(#nb-water)" />
        <line x1={sw / 2} y1={h * (1 - p)} x2={sw / 2} y2={h} stroke="rgba(255,255,255,.75)" strokeWidth={sw} />
        {Array.from({ length: steps + 1 }, (_, i) => {
          const y = h - (h * i) / steps;
          return <line key={i} x1={sw} y1={y} x2={sw + w * (i % steps === 0 ? 0.32 : 0.2)} y2={y} stroke="rgba(255,255,255,.55)"
            strokeWidth={Math.max(1, 1.5 * k)} opacity={p} />;
        })}
        <path d={wave} fill="none" stroke={WHITE} strokeWidth={sw} strokeLinejoin="round" opacity={prog > 0.01 ? 1 : 0} />
        {flood !== null ? (
          <line x1={0} y1={fy} x2={w * 1.25 * p} y2={fy} stroke={AMBER} strokeWidth={sw}
            strokeDasharray={`${(5 * k).toFixed(2)} ${(3.5 * k).toFixed(2)}`} opacity={crossed ? 1 : 0.85} />
        ) : null}
      </svg>
    );
  };
const WaterLevel: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const unit = f.unit.tag || "FT";
  const all = `${f.words} ${spokenToDigits(str(overlay.subtitle)).toUpperCase()} ${str(overlay.label).toUpperCase()}`;
  const said = FLOOD_RX.exec(all);
  // The flood stage said, else the overlay's total when a flood is named (a total alone may be a capacity).
  const flood = said ? Number(said[1]) : /\bFLOOD/.test(all) ? numOf(overlay.total) : null;
  const value = f.value ?? 0;
  const st = { ...statText(f), top: "", tags: [unit] };
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 30);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const size = sizeFor(60, t, statEm(st) + ANTON_CAP * 1.0 + 0.3, maxW);
  const unsay = (s: string) => trimEnds(s.replace(new RegExp(`${FLOOD_RX.source}(?:\\s?(?:FT|FEET|FOOT|M))?`), "")
    .replace(/\bFLOOD STAGE\b/, ""));
  const label = unsay(f.label || "");
  const floodPart: Part | null = flood !== null && Number.isFinite(flood)
    ? { text: `FLOOD STAGE ${fmt(flood, decimalsFor(flood))} ${unit}`, color: AMBER } : null;
  const extra = unsay(f.extra);
  const lpx = Math.max(20 * t.k, Math.min(LABEL_PX * t.k, maxW / Math.max(1, subEm([label, floodPart ? floodPart.text : ""]
    .filter(Boolean).join(" · ")))));
  const parts: Part[] = [label ? { text: label } : null, floodPart, !label && extra ? { text: extra } : null]
    .filter((p): p is Part => Boolean(p));
  const gw = size * ANTON_CAP * 0.72;
  const gh = size * ANTON_CAP + size * 0.24 + (parts.length ? lpx * SUBLINE_CAP : 0);
  const top = niceMax(Math.max(value, flood ?? 0) * 1.12);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginTop: size * ANTON_TOP, marginRight: size * 0.18 }}>
            <Gauge w={gw} h={gh} value={value} flood={flood !== null && Number.isFinite(flood) ? flood : null} top={top} t={t} c0={C0}
              land={land} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 3 }} t={t} />
            {parts.length ? (
              <div style={{ marginTop: size * 0.24 - size * (1 - ANTON_BASE) - lpx * SUB_TOP }}>
                <Label parts={parts} size={lpx} t={t} inAt={land - 6} />
              </div>
            ) : null}
          </div>
        </div>
      </Block>
    </>
  );
};

// ================================================================== num-temperature
const NumTemperature: Look = ({ overlay }) => {
  const f = figureOf(overlay);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <Temperature overlay={overlay} f={f} />;
};
/** A slim thermometer: the track, the bulb and the column rising to the reading (amber hot, ice cold, white between). */
const Thermo: React.FC<{ h: number; share: number; color: string; t: Clock; c0: number; land: number }> = ({ h, share, color, t, c0, land }) => {
  const p = lineIn(t, 2, 12);
  const prog = easeOutQuart(clamp01((t.f - c0) / Math.max(1, land - c0)));
  const k = t.k;
  const tw = Math.max(4, 7 * k);
  const bulb = Math.max(9, 17 * k);
  const w = bulb + 2;
  const cx = w / 2;
  const tubeTop = tw / 2;
  const tubeBot = h - bulb * 0.75;
  const len = tubeBot - tubeTop;
  const fillTop = tubeBot - len * clamp01(share) * prog;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w.toFixed(2)} ${h.toFixed(2)}`} style={{ display: "block", overflow: "visible",
      opacity: clamp01(p * 2), filter: shadow(k, true) }}>
      <rect x={cx - tw / 2} y={tubeTop - tw / 2} width={tw} height={len + tw} rx={tw / 2} fill={TRACK_FILL} />
      <rect x={cx - tw / 2} y={fillTop} width={tw} height={Math.max(0, tubeBot - fillTop + tw / 2)} rx={tw / 2} fill={color} />
      <circle cx={cx} cy={h - bulb / 2} r={bulb / 2} fill={color} opacity={0.4 + 0.6 * p} />
    </svg>
  );
};
const Temperature: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  const celsius = f.unit.top === "°C" || /\bCELSIUS\b|°C/.test(`${f.words} ${str(overlay.suffix).toUpperCase()}`);
  const top = celsius ? "°C" : f.unit.top === "°" || !f.unit.top ? "°F" : f.unit.top;
  const value = f.value ?? 0;
  const st = { ...statText(f), top, tags: [] as string[] };
  const C0 = 4;
  const roll = rollOf(st.fig, C0, 30);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const size = sizeFor(62, t, statEm(st) + 0.5, maxW);
  const [lo, hi] = celsius ? [-30, 50] : [-20, 120];
  const share = Math.max(0.05, clamp01((value - lo) / (hi - lo)));
  const hot = celsius ? value >= 32 : value >= 90;
  const cold = celsius ? value <= 0 : value <= 32;
  const color = hot ? AMBER : cold ? ICE : WHITE;
  const lab = labelFor([f.label, f.extra].filter(Boolean).join(" · "), t, maxW);
  const th = size * ANTON_CAP + size * 0.26
    + (lab.lines.length ? lab.size * SUBLINE_CAP + (lab.lines.length - 1) * lab.size * 1.42 : 0);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginTop: size * ANTON_TOP - 2 * t.k, marginRight: size * 0.2 }}>
            <Thermo h={th} share={share} color={color} t={t} c0={C0} land={land} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <Stat s={{ ...st, size, pos: rollPos(roll, t.f), enter: 3, signColor: hot ? AMBER : WHITE }} t={t} />
            {lab.lines.map((l, i) => (
              <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.26 - size * (1 - ANTON_BASE) - lab.size * SUB_TOP }}>
                <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
              </div>
            ))}
          </div>
        </div>
      </Block>
    </>
  );
};

// ================================================================== num-money
const NumMoney: Look = ({ overlay }) => {
  const f = figureOf(overlay, true);
  return f.value === null ? <WordsOnly overlay={overlay} words={f.label || f.extra} /> : <Money overlay={overlay} f={f} />;
};
const Money: React.FC<{ overlay: Overlay; f: Fig }> = ({ overlay, f }) => {
  const t = useClock();
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = maxWOf(t, align, full);
  // $1,200,000,000 -> $1.2 BILLION; a figure already scaled keeps its word.
  let value = f.value ?? 0;
  let scale = f.unit.scale;
  if (scale && Math.abs(value) >= SCALE_X[scale]) value /= SCALE_X[scale];
  if (!scale) {
    for (const s of ["TRILLION", "BILLION", "MILLION"]) {
      if (Math.abs(value) >= SCALE_X[s]) {
        value /= SCALE_X[s];
        scale = s;
        break;
      }
    }
  }
  const decimals = scale ? decimalsFor(value) : Math.min(2, f.decimals);
  const fig = fmt(value, decimals);
  const label = f.label || f.extra;
  const short = scale && label && label.length <= 12 && label.split(" ").length <= 2 ? label : "";
  const tags = [scale, short].filter(Boolean);
  const st = { fig, pre: "$", top: "", tags };
  const C0 = 4;
  const roll = rollOf(fig, C0, 30);
  const land = landOf(roll);
  const sound = useLookSound([...rollTicks([roll], [land]), ...landClicks([land])]);
  const size = sizeFor(62, t, statEm(st), maxW);
  const lab = labelFor([short ? "" : label, f.label && f.extra ? f.extra : ""].filter(Boolean).join(" · "), t, maxW);
  return (
    <>
      {sound}
      <Block t={t} align={align} full={full} land={land}>
        <Stat s={{ ...st, size, pos: rollPos(roll, t.f), tagColors: [WHITE, AMBER] }} t={t} />
        {lab.lines.map((l, i) => (
          <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.24 }}>
            <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
          </div>
        ))}
      </Block>
    </>
  );
};

// ================================================================== num-step-of
const OF_RX = /(\d{1,4})\s*(?:OF|OUT OF|\/|IN)\s*(\d{1,4})\b/;
/** "3 of 5": the count, the whole, the word between and what it counts. */
const stepOf = (ov: Overlay): { n: number | null; m: number | null; word: string; label: string; extra: string } => {
  const words = spokenToDigits(str(ov.text)).toUpperCase();
  let n = numOf(ov.value);
  let m = numOf(ov.total);
  let label = words;
  let word = "OF";
  const hit = OF_RX.exec(words);
  if (hit) {
    const a = Number(hit[1]);
    const b = Number(hit[2]);
    if (n === null || n === a) {
      n = a;
      if (m === null) m = b;
      word = /\bIN\b/.test(hit[0]) ? "IN" : "OF";
      label = cut(words, hit.index, hit.index + hit[0].length);
    }
  } else if (n === null) {
    const f = figureOf(ov);
    n = f.value;
    label = f.label;
  } else {
    const lead = new RegExp(`^\\s*${String(n).replace(".", "\\.")}\\b`).exec(words);
    if (lead) label = cut(words, 0, lead[0].length);
  }
  if (n !== null) n = Math.round(n);
  if (m !== null) m = Math.round(m);
  const extra = trimEnds(spokenToDigits(str(ov.subtitle) || str(ov.label)).toUpperCase()).slice(0, 40);
  return { n, m, word, label: trimEnds(label.replace(/^(ARE|WERE|IS|OF)\s+/, "")).slice(0, 44), extra };
};
const NumStepOf: Look = ({ overlay }) => {
  const s = stepOf(overlay);
  return s.n === null ? <WordsOnly overlay={overlay} words={s.label || s.extra} />
    : <StepOf overlay={overlay} n={s.n} m={s.m} word={s.word} label={s.label || s.extra} extra={s.label ? s.extra : ""} />;
};
const StepOf: React.FC<{ overlay: Overlay; n: number; m: number | null; word: string; label: string; extra: string }> =
  ({ overlay, n, m, word, label, extra }) => {
    const t = useClock();
    const align = alignOf(overlay);
    const full = Boolean(overlay.fullFrame);
    const maxW = maxWOf(t, align, full);
    const fig = fmt(n, 0);
    const steps = n >= 1 && n <= 9 && m !== null && m >= n && m <= 12;
    const segs = m !== null && m >= 1 && m <= 12 && n <= m ? m : 0;
    const S0 = 8;
    const GAP = 7;
    const stepAt = (i: number) => S0 + GAP * (i - 1);          // step i (1..n) starts rolling
    const roll = rollOf(fig, 4, 28);
    const land = steps ? stepAt(n) + 6 : landOf(roll);
    // A step counter: the digit rolls up one at each step (a tick each), the segment lights with it.
    const stepPos = (i: number): number | null => {
      if (!steps) return rollPos(roll, t.f)(i);
      if (i !== 0) return null;
      let cur = 0;                                            // the last step started
      for (let s = 1; s <= n; s++) if (t.f >= stepAt(s)) cur = s;
      return cur ? cur - 1 + easeOut(clamp01((t.f - stepAt(cur)) / 6)) : 0;
    };
    const cues: SoundCue[] = steps
      ? Array.from({ length: n }, (_, j) => ({ name: "ui-tick", alt: ["letter-tick", "tick"], at: stepAt(j + 1) + 2,
        gain_db: -7 + (2 * j) / Math.max(1, n), pitch: 0.95 + 0.04 * j }) as SoundCue).filter((c) => c.at < land - 2)
      : rollTicks([roll], [land]);
    const sound = useLookSound([...cues, ...landClicks([land])]);
    const ofText = m !== null ? `${word} ${fmt(m, 0)}` : "";
    const ofSize = (s: number) => s * 0.46;
    const size = sizeFor(64, t, widthEm(fig) + (ofText ? 0.18 + widthEm(ofText) * 0.46 : 0), maxW);
    const k = t.k;
    const rowW = widthEm(fig) * size + (ofText ? size * 0.18 + widthEm(ofText) * ofSize(size) : 0);
    const segGap = 6 * k;
    const segW = segs ? Math.max(12 * k, Math.min(36 * k, (Math.max(rowW, 180 * k) - (segs - 1) * segGap) / segs)) : 0;
    const segH = Math.max(3, 4 * k);
    const lit = (i: number) => steps
      ? (i < n ? easeOut(clamp01((t.f - stepAt(i + 1) - 1) / 6)) : 0)
      : clamp01(n * easeOutQuart(clamp01((t.f - 4) / Math.max(1, land - 4))) - i);
    const segIn = lineIn(t, 2, 12);
    const lab = labelFor([label, extra].filter(Boolean).join(" · "), t, maxW);
    return (
      <>
        {sound}
        <Block t={t} align={align} full={full} land={land}>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <Glyphs text={fig} size={size} t={t} enter={2} pos={stepPos} />
            {ofText ? (
              <div style={{ marginLeft: size * 0.18, marginBottom: size * (1 - ANTON_BASE) - ofSize(size) * (1 - ANTON_BASE) }}>
                <Glyphs text={ofText} size={ofSize(size)} t={t} enter={5} color="rgba(255,255,255,.8)" exitFrom={2} />
              </div>
            ) : null}
          </div>
          {segs ? (
            <div style={{ display: "flex", marginTop: size * 0.2, gap: segGap, filter: `drop-shadow(0 ${px(1, k)} ${px(3, k)} rgba(0,0,0,.5))` }}>
              {Array.from({ length: segs }, (_, i) => (
                <div key={i} style={{ position: "relative", width: segW, height: segH, borderRadius: segH,
                  background: TRACK_FILL, opacity: clamp01(segIn * 2 - i * 0.08),
                  transform: `scaleX(${clamp01(segIn * 1.6 - i * 0.06).toFixed(4)})`, transformOrigin: "0% 50%", overflow: "hidden" }}>
                  <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "100%", background: AMBER, borderRadius: segH,
                    transform: `scaleX(${lit(i).toFixed(4)})`, transformOrigin: "0% 50%" }} />
                </div>
              ))}
            </div>
          ) : null}
          {lab.lines.map((l, i) => (
            <div key={i} style={{ marginTop: i ? lab.size * 0.42 : size * 0.22 }}>
              <Label parts={[l]} size={lab.size} t={t} inAt={land - 6 + 3 * i} />
            </div>
          ))}
        </Block>
      </>
    );
  };

export const LOOKS: Record<string, Look> = {
  "num-lower-third": NumLowerThird,
  "num-percent-line": NumPercentLine,
  "num-rainfall": NumRainfall,
  "num-wind-gauge": NumWindGauge,
  "num-big-figure": NumBigFigure,
  "num-versus": NumVersus,
  "num-trend-arrow": NumTrendArrow,
  "num-rank": NumRank,
  "num-split-stat": NumSplitStat,
  "num-water-level": NumWaterLevel,
  "num-temperature": NumTemperature,
  "num-money": NumMoney,
  "num-step-of": NumStepOf,
};
