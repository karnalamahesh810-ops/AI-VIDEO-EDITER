import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, ANTON_CAP, SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { MONTHS, MON_AP, WEEKDAYS, parseDT, parseRange, type DT } from "./LibDateTime";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import { spokenToDigits } from "./numWords";

/**
 * A date, a time or a number as clean text on the footage (the owner,
 * 2026-10-01, after the 12-minute video: "I need a cleaner date, not only
 * white - shade, clean, bold, not big, not small", "the text is super big",
 * "use the font Anton", "only a digit sound ... no punch", "better animations
 * for the counts"):
 *
 *   dt-letter-drop  the date / time words ("SEPTEMBER 29", "TUESDAY NIGHT",
 *                   "3:45 PM", "8 AM ET", "WED -> THU") in Anton caps about
 *                   55 px tall at 1080p: the letters slide up out of a mask one
 *                   by one (2 frames apart), settle, hold and drop back out in
 *                   the last 10 frames. A time is the figure with its AM/PM and
 *                   zone small beside it; the weekday, year or place follows in
 *                   small tracked Inter Tight caps.
 *   bt-count        a number: the digits roll into place like an odometer
 *                   (each column easing out, the units spinning fastest, the
 *                   columns landing left to right), commas, %, $ and K/M/B in
 *                   place, a unit word small beside the figure; what it counts
 *                   comes in under it once it lands.
 *
 * Four letterings, one per occurrence (overlay.textStyle, which the planner
 * turns; else picked from the overlay's start frame), each legible on snow and
 * on night footage alike - never a box, a band or a black stroke:
 *   clean   white with a soft dark shadow (a 1 px edge, a close and a wide
 *           shadow) and a thin amber rule
 *   shine   silver (white to steel) with one light sweep across the letters
 *   accent  the key part - the day, the time, the figure - in warm amber
 *   shade   white over a soft feathered darkening (blurred, no edges)
 *
 * Low on the left or the right at the safe margin (overlay.align), the lower
 * third, clear of the captions and never mid-frame; a full-screen scene
 * centres it. Every spoken number reads in digits ("five days" -> "5 DAYS",
 * numWords.ts). The sound is part of the look (useLookSound): a soft digital
 * tick on each letter or digit change, scheduled from the frames they move
 * on, and nothing at the landing.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
export type TextStyle = "clean" | "shine" | "accent" | "shade";
export const TEXT_STYLES: TextStyle[] = ["clean", "shine", "accent", "shade"];

// ------------------------------------------------------------------ the type
const EXIT = 10;                 // frames (at 30 fps) the look takes to leave
const WHITE = "#FFFFFF";
const AMBER = "#FFC247";
const SILVER = "linear-gradient(180deg, #FFFFFF 0%, #FFFFFF 26%, #EEF1F5 44%, #C3CAD4 64%, #E7EBF0 100%)";
const CAP_DATE = 54;             // px at 1080p: a date's or a time's cap height
const CAP_FIGURE = 60;           // a number's
const CAP_MIN = 44;              // fitting never shrinks a main line below this
const SUB_PX = 26;               // the small line (Inter Tight 700, cap ~19 px)
const SUB_TRACK = 0.16;          // its letter spacing (em)
const MAIN_TRACK = 0.012;        // Anton's (em)
// Anton in a line box of 1 em: the caps from 0.065 em to 0.924 em (the baseline).
const ANTON_TOP = 0.065;
// Inter Tight in a line box of 1 em: the caps from 0.136 em to 0.864 em.
const SUB_TOP = 0.136;
// The mask the letters move in: tight above the caps, just under the baseline (commas show), open at the sides.
const MASK = "inset(-0.02em -0.6em -0.1em -0.6em)";
const BELOW = 1.2;               // em under the line a hidden letter waits
const RISE = 8;                  // frames (30 fps) a letter takes to slide up and settle
const DIGIT_W = 0.494;           // an odometer column (Anton's digit advance)
const STEP = 1.15;               // em between two digits on a column's strip

/** Anton's advance widths (em). */
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, "0": 0.494, "1": 0.331, "2": 0.494, "3": 0.494, "4": 0.494, "5": 0.494,
  "6": 0.494, "7": 0.494, "8": 0.494, "9": 0.494, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, "%": 1.057,
  "$": 0.462, "°": 0.389, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "&": 0.52, "/": 0.405,
  "+": 0.355, "(": 0.291, ")": 0.291, "?": 0.492, "!": 0.229, "#": 0.546, "→": 0.62,
};
const advOf = (c: string) => ADV[c] ?? 0.48;
const widthEm = (s: string, track = MAIN_TRACK) => Array.from(s).reduce((a, c) => a + advOf(c) + track, 0);
/** Inter Tight 700 caps, roughly (em). */
const subEm = (s: string, track = SUB_TRACK) =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.234 : /[0-9]/.test(c) ? 0.56 : /[MW]/.test(c) ? 0.86 : /[IJ1.,:'·]/.test(c)
    ? 0.3 : 0.64) + track, 0);

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeOutQuart = (t: number) => 1 - (1 - t) ** 4;
const easeIn = (t: number) => t * t * t;
/** Ease-out with a small overshoot (about 3 %): the settle. */
const settle = (t: number, s = 0.9) => 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2;
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
/** A small stable jitter per index (tick pitches), no Math.random. */
const jitter = (i: number) => ((Math.sin(i * 12.9898 + 4.1) * 43758.5453) % 1 + 1) % 1;
const fnv = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};

/** The overlay's lettering: its textStyle, else one picked from its start frame and words. */
export const styleOf = (ov: Overlay): TextStyle => {
  const want = String(ov.textStyle || "").toLowerCase() as TextStyle;
  return TEXT_STYLES.includes(want) ? want : TEXT_STYLES[fnv(`${ov.startFrame}|${str(ov.text)}`) % TEXT_STYLES.length];
};

/** Split a line of words into two balanced lines. */
const twoLines = (s: string): string[] => {
  const words = s.split(" ");
  if (words.length < 2) return [s];
  let best = [s];
  let score = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(" ");
    const b = words.slice(i).join(" ");
    const d = Math.max(widthEm(a), widthEm(b));
    if (d < score) {
      score = d;
      best = [a, b];
    }
  }
  return best;
};

// ------------------------------------------------------------------ placement
type Align = "left" | "right" | "center";
const alignOf = (ov: Overlay): Align => {
  if (ov.fullFrame) return "center";
  const a = String(ov.align || "").toLowerCase();
  return a === "right" || a === "center" ? a : "left";
};

/**
 * The block's box: the lower third at the safe margin (6.5 % of the width in
 * from the side, its foot a quarter of the height up, clear of the captions),
 * centred on a full-screen scene. `push` is a slow drift while it holds.
 */
const Place: React.FC<{ align: Align; full: boolean; push: number; children: React.ReactNode }> =
  ({ align, full, push, children }) => {
    const { width, height } = useVideoConfig();
    const side = width * 0.065;
    const foot = height * 0.25;
    const pos: React.CSSProperties = full
      ? { left: 0, right: 0, top: 0, bottom: 0, justifyContent: "center", alignItems: "center" }
      : align === "center"
        ? { left: side, right: side, bottom: foot, alignItems: "center" }
        : align === "right"
          ? { right: side, bottom: foot, alignItems: "flex-end" }
          : { left: side, bottom: foot, alignItems: "flex-start" };
    const origin = full || align === "center" ? "50% 100%" : align === "right" ? "100% 100%" : "0% 100%";
    return (
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos,
        textAlign: align === "center" ? "center" : align, transformOrigin: origin,
        transform: `scale(${(full ? 1.3 : 1) * push})` }}>
        {children}
      </div>
    );
  };

// ------------------------------------------------------------------ lettering
/** The shadow under the letters (on a wrapper, so the mask never cuts it): an edge, a close and a wide shadow. */
const shadowOf = (style: TextStyle, k: number, light = false): string => {
  const px = (n: number) => `${(n * k).toFixed(2)}px`;
  // Enough body to hold white on snow or a white page, still no outline.
  if (light) {
    return `drop-shadow(0 0 ${px(1.2)} rgba(0,0,0,.8)) drop-shadow(0 ${px(1)} ${px(2)} rgba(0,0,0,.55)) `
      + `drop-shadow(0 ${px(2)} ${px(8)} rgba(0,0,0,.5))`;
  }
  if (style === "shade") {
    return `drop-shadow(0 0 ${px(1.2)} rgba(0,0,0,.6)) drop-shadow(0 ${px(2)} ${px(8)} rgba(0,0,0,.45))`;
  }
  return `drop-shadow(0 0 ${px(1.5)} rgba(0,0,0,.72)) drop-shadow(0 ${px(2)} ${px(3)} rgba(0,0,0,.45)) `
    + `drop-shadow(0 ${px(5)} ${px(18)} rgba(0,0,0,.5))`;
};

type Glyph = { ch: string; key?: boolean };
const glyphsOf = (s: string, key?: [number, number] | null): Glyph[] =>
  Array.from(s).map((ch, i) => ({ ch, key: Boolean(key && i >= key[0] && i < key[1]) }));

const fillOf = (style: TextStyle, g: Glyph): React.CSSProperties =>
  style === "shine"
    ? { backgroundImage: SILVER, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent",
      WebkitTextFillColor: "transparent" }
    : { color: style === "accent" && g.key ? AMBER : WHITE };

/** A bold right arrow the size of a letter (ranges), drawn rather than typed (Anton has none). */
const Arrow: React.FC<{ fill: string }> = ({ fill }) => (
  <svg width="0.62em" height="0.62em" viewBox="0 0 62 62" style={{ display: "block", overflow: "visible" }}>
    <path d="M2 25.5 H38 V36.5 H2 Z M31 11.5 L60 31 L31 50.5 Z" fill={fill} />
  </svg>
);

/**
 * One line of letters in its mask. `y(i)` is letter i's offset in em (0 in
 * place, BELOW hidden under the line); `sweep` (0-1) passes a band of light
 * across a silver line; `render(i)` may draw a letter itself (a rolling digit).
 */
const MaskLine: React.FC<{
  glyphs: Glyph[]; size: number; style: TextStyle; k: number; y: (i: number) => number; sweep?: number;
  track?: number; render?: (i: number, fill: React.CSSProperties) => React.ReactNode | null; light?: boolean;
}> = ({ glyphs, size, style, k, y, sweep = -1, track = MAIN_TRACK, render, light }) => {
  const letters = (layer: "base" | "sweep") => glyphs.map((g, i) => {
    const off = y(i);
    const box: React.CSSProperties = { display: "inline-block", verticalAlign: "top", height: "1em",
      marginRight: `${track}em`, transform: off ? `translateY(${off.toFixed(4)}em)` : undefined,
      visibility: off >= BELOW - 1e-3 ? "hidden" : undefined };
    if (g.ch === " ") return <span key={i} style={{ ...box, width: `${advOf(" ")}em` }} />;
    const fill: React.CSSProperties = layer === "sweep" ? { color: WHITE } : fillOf(style, g);
    // A letter that draws itself (a rolling digit) takes its fill onto its own glyphs.
    const own = render ? render(i, fill) : null;
    if (own) return <span key={i} style={{ ...box, position: "relative" }}>{own}</span>;
    if (g.ch === "→") {
      return (
        <span key={i} style={{ ...box, paddingTop: "0.2em", width: `${advOf("→")}em` }}>
          <Arrow fill={layer === "sweep" ? WHITE : style === "shine" ? "#E3E7ED" : style === "accent" ? AMBER : WHITE} />
        </span>
      );
    }
    return <span key={i} style={{ ...box, ...fill }}>{g.ch}</span>;
  });
  const text: React.CSSProperties = { fontFamily: ANTON, fontWeight: 400, fontSize: size, lineHeight: 1, whiteSpace: "pre",
    letterSpacing: 0 };
  return (
    <div style={{ position: "relative", ...text }}>
      <div style={{ filter: shadowOf(style, k, light) }}>
        <div style={{ clipPath: MASK }}>{letters("base")}</div>
      </div>
      {style === "shine" && sweep > 0 && sweep < 1 ? (
        <div aria-hidden style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, ...text,
          WebkitMaskImage: "linear-gradient(100deg, transparent 0%, transparent 44%, #000 50%, transparent 56%, transparent 100%)",
          maskImage: "linear-gradient(100deg, transparent 0%, transparent 44%, #000 50%, transparent 56%, transparent 100%)",
          WebkitMaskSize: "300% 100%", maskSize: "300% 100%", WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
          WebkitMaskPosition: `${(100 * (1 - sweep)).toFixed(2)}% 0`, maskPosition: `${(100 * (1 - sweep)).toFixed(2)}% 0`,
          textShadow: `0 0 ${(10 * k).toFixed(1)}px rgba(255,255,255,.55)` }}>
          <div style={{ clipPath: MASK }}>{letters("sweep")}</div>
        </div>
      ) : null}
    </div>
  );
};

/** The small line: tracked Inter Tight caps, parts parted by a dot; in from below, out with a fade. */
const SubLine: React.FC<{ parts: string[]; size: number; style: TextStyle; k: number; inAt: number; outAt: number;
  frame: number; S: number }> = ({ parts, size, style, k, inAt, outAt, frame, S }) => {
  if (!parts.length) return null;
  const p = easeOut(clamp01((frame - inAt) / (12 * S)));
  const q = easeIn(clamp01((frame - outAt) / (7 * S)));
  if (p <= 0) return null;
  const track = SUB_TRACK + 0.12 * (1 - p);
  return (
    <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1, letterSpacing: `${track.toFixed(4)}em`,
      textTransform: "uppercase", whiteSpace: "nowrap", color: "rgba(255,255,255,.96)", opacity: p * (1 - q),
      transform: `translateY(${((1 - p) * 0.55 + q * 0.4).toFixed(4)}em)`, filter: shadowOf(style, k, true) }}>
      {parts.map((s, i) => (
        <React.Fragment key={i}>
          {i ? <span style={{ display: "inline-block", width: "0.22em", height: "0.22em", borderRadius: "50%",
            margin: "0 0.62em 0 0.46em", transform: "translateY(-0.12em)", verticalAlign: "middle",
            background: style === "accent" || style === "clean" ? AMBER : "rgba(255,255,255,.8)" }} /> : null}
          <span>{s}</span>
        </React.Fragment>
      ))}
    </div>
  );
};

/** The thin amber rule of the clean lettering: it draws out from the block's edge, and back at the exit. */
const Rule: React.FC<{ width: number; align: Align; k: number; p: number }> = ({ width, align, k, p }) => (
  <div style={{ width, height: Math.max(2, 3 * k), background: AMBER, borderRadius: 2 * k,
    transform: `scaleX(${p.toFixed(4)})`, transformOrigin: align === "right" ? "100% 50%" : align === "center" ? "50% 50%" : "0% 50%",
    boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
);

/** The feathered shade behind the block: a blurred dark ellipse, no edge anywhere. */
const Shade: React.FC<{ size: number; k: number; opacity: number }> = ({ size, k, opacity }) => (
  <div style={{ position: "absolute", left: -1.1 * size, right: -1.1 * size, top: -0.8 * size, bottom: -0.8 * size,
    background: "radial-gradient(closest-side, rgba(0,0,0,.56), rgba(0,0,0,.5) 38%, rgba(0,0,0,.26) 68%, rgba(0,0,0,0) 100%)",
    filter: `blur(${(22 * k).toFixed(1)}px)`, opacity, zIndex: -1 }} />
);

/** Small tags beside a figure ("PM", "AM / ET", "MILLION"), cap-top aligned, filling the figure's cap height when two. */
const Tags: React.FC<{ tags: string[]; size: number; style: TextStyle; k: number; p: number; q: number; gap: number }> =
  ({ tags, size, style, k, p, q, gap }) => {
    if (!tags.length) return null;
    const cap = size * ANTON_CAP;
    const tagCap = tags.length > 1 ? cap * 0.41 : cap * 0.4;
    const tagPx = tagCap / SUBLINE_CAP;
    const between = tags.length > 1 ? cap - 2 * tagCap : 0;
    return (
      <div style={{ display: "flex", flexDirection: "column", marginLeft: gap, paddingTop: size * ANTON_TOP - tagPx * SUB_TOP,
        clipPath: "inset(-0.3em -0.4em -0.3em -0.4em)", filter: shadowOf(style, k, true) }}>
        {tags.map((t, i) => (
          <div key={i} style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: tagPx, lineHeight: 1, letterSpacing: "0.06em",
            color: style === "accent" ? AMBER : WHITE, marginTop: i ? between - tagPx * (1 - SUBLINE_CAP) : 0,
            opacity: clamp01(p * 1.6) * (1 - q), transform: `translateY(${((1 - p) * 0.8 + q * 0.6).toFixed(4)}em)` }}>{t}</div>
        ))}
      </div>
    );
  };

// ------------------------------------------------------------------ timing
/** Frames (at the video's rate) each letter starts sliding up, 2 frames apart (closer for a long line). */
const letterStarts = (glyphs: Glyph[], S: number, lead: number) => {
  const n = glyphs.filter((g) => g.ch !== " ").length;
  const stagger = n <= 16 ? 2 : Math.max(1, 32 / n);
  let j = 0;
  const starts = glyphs.map((g) => (g.ch === " " ? -1 : Math.round((lead + stagger * j++) * S)));
  const last = Math.max(0, ...starts) + Math.round(RISE * S);
  return { starts, last, n };
};

/** A letter's offset (em): up out of the mask with a small settle, and back down into it at the exit. */
const letterY = (frame: number, start: number, S: number, exitAt: number, exitIndex: number, exitStep: number): number => {
  if (start < 0) return 0;
  if (frame < start) return BELOW;
  const p = clamp01((frame - start) / (RISE * S));
  const e = easeIn(clamp01((frame - (exitAt + exitIndex * exitStep * S)) / (6 * S)));
  return BELOW * (1 - settle(p)) + e * BELOW;
};

/** A quiet digital tick on each letter as it settles, never two within 2 frames. */
const letterTicks = (starts: number[], S: number): SoundCue[] => {
  const cues: SoundCue[] = [];
  let last = -99;
  starts.forEach((f, i) => {
    if (f < 0) return;
    const at = f / S + 5;
    if (at - last < 2) return;
    last = at;
    cues.push({ name: "letter-tick", alt: ["ui-tick", "tick"], at, gain_db: -6 - 0.8 * jitter(i), pitch: 0.97 + 0.08 * jitter(i + 7) });
  });
  return cues;
};

// ================================================================== dt-letter-drop
export type DatePlan = {
  /** The big line. */
  main: string;
  /** The part of it the accent lettering colours (the day, the time, the year), [from, to). */
  key: [number, number] | null;
  /** Small tags beside it: a time's AM/PM and zone. */
  tags: string[];
  /** The small line: weekday, year, time, place. */
  sub: string[];
};

const PARTS = /\b(MORNING|AFTERNOON|EVENING|NIGHT|OVERNIGHT|TONIGHT|DAWN|DUSK)\b/;
const ZONE = /\b(ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|AKST|AKDT|HST|UTC|GMT|LOCAL TIME)\b/;
const clockOf = (d: DT, raw: string): { time: string; period: string } | null => {
  if (d.hour === undefined) return null;
  if (/\bNOON\b|\bMIDDAY\b/.test(raw)) return { time: "NOON", period: "" };
  if (/\bMIDNIGHT\b/.test(raw)) return { time: "MIDNIGHT", period: "" };
  const m = d.minute ?? 0;
  return { time: m ? `${d.hour}:${String(m).padStart(2, "0")}` : String(d.hour), period: d.ampm || "" };
};
const clockLine = (c: { time: string; period: string } | null) => (c ? `${c.time} ${c.period}`.trim() : "");
const keyOf = (main: string, part: string): [number, number] | null => {
  const at = part ? main.lastIndexOf(part) : -1;
  return at >= 0 ? [at, at + part.length] : null;
};
const WD3 = WEEKDAYS.map((w) => w.slice(0, 3));
const parts = (...xs: (string | undefined)[]) => xs.filter((x): x is string => Boolean(x)).slice(0, 3);

/** What the look says: the date or time big (its key part marked), AM/PM and zone small beside it, the rest small under it. */
export const datePlan = (ov: Overlay): DatePlan => {
  const text = spokenToDigits(str(ov.text));
  const raw = text.toUpperCase().replace(/[’']/g, "");
  const d = parseDT(text, spokenToDigits(str(ov.label)), ov.value);
  const place = d.place || spokenToDigits(str(ov.subtitle)).toUpperCase().slice(0, 36);
  const zone = ZONE.exec(raw)?.[1] || "";
  const rg = parseRange(text);
  if (rg) {
    const { a, b } = rg;
    if (a.month !== undefined && b.month !== undefined && a.day !== undefined && b.day !== undefined) {
      const main = a.month === b.month ? `${MONTHS[a.month]} ${a.day}-${b.day}` : `${MON_AP[a.month]} ${a.day} → ${MON_AP[b.month]} ${b.day}`;
      const year = b.year !== undefined ? String(b.year) : a.year !== undefined ? String(a.year) : "";
      return { main, key: keyOf(main, a.month === b.month ? `${a.day}-${b.day}` : "→"), tags: [], sub: parts(year, place) };
    }
    if (a.hour !== undefined && b.hour !== undefined && a.month === undefined) {
      const main = `${clockLine(clockOf(a, ""))} → ${clockLine(clockOf(b, ""))}`;
      return { main, key: keyOf(main, "→"), tags: zone ? [zone] : [], sub: parts(d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", place) };
    }
    if (a.weekday !== undefined && b.weekday !== undefined && a.month === undefined && b.month === undefined) {
      const main = `${WD3[a.weekday]} → ${WD3[b.weekday]}`;
      return { main, key: keyOf(main, "→"), tags: [], sub: parts(clockLine(clockOf(a, "")), place) };
    }
    if (a.year !== undefined && b.year !== undefined && a.month === undefined) {
      const main = `${a.year} → ${b.year}`;
      return { main, key: keyOf(main, "→"), tags: [], sub: parts(place) };
    }
  }
  const wd = d.weekday !== undefined ? WEEKDAYS[d.weekday] : "";
  const year = d.year !== undefined ? String(d.year) : "";
  const clock = clockOf(d, raw);
  const part = PARTS.exec(raw)?.[1] || "";
  if (d.month !== undefined && d.day !== undefined) {
    const main = `${MONTHS[d.month]} ${d.day}`;
    return { main, key: keyOf(main, String(d.day)), tags: [], sub: parts(wd, clockLine(clock) || part, year, place) };
  }
  if (d.month !== undefined) {
    const main = year ? `${MONTHS[d.month]} ${year}` : MONTHS[d.month];
    return { main, key: year ? keyOf(main, year) : null, tags: [], sub: parts(wd, clockLine(clock), place) };
  }
  if (d.year !== undefined && !clock) return { main: year, key: [0, year.length], tags: [], sub: parts(wd, place) };
  if (clock) {
    const tags = [clock.period, zone].filter(Boolean);
    return { main: clock.time, key: [0, clock.time.length], tags, sub: parts(wd, place) };
  }
  if (wd) {
    // "TUESDAY NIGHT": the weekday big, the part of the day said with it small under it.
    return { main: wd, key: [0, wd.length], tags: [], sub: parts(part && raw.includes(wd) ? part : "", place) };
  }
  const main = raw.slice(0, 30) || "—";
  return { main, key: null, tags: [], sub: parts(place) };
};

const DtLetterDrop: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, width, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const S = fps / 30;
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const style = styleOf(overlay);
  const plan = datePlan(overlay);
  // The main line ~54 px tall at 1080p; a long one shrinks (never under CAP_MIN), then takes two lines.
  const maxW = (align === "center" || full ? 0.66 : 0.4) * width;
  const tagRoom = (size: number) => (plan.tags.length ? size * ANTON_CAP * 0.4 / SUBLINE_CAP * 1.9 + size * 0.14 : 0);
  let lines = [plan.main];
  // A time is a figure: set at the number's height, its AM/PM and zone small beside it.
  let size = ((plan.tags.length ? CAP_FIGURE : CAP_DATE) / ANTON_CAP) * k;
  const fits = (sz: number, ls: string[]) => Math.max(...ls.map((l) => widthEm(l) * sz)) + tagRoom(sz) <= maxW;
  if (!fits(size, lines)) {
    const least = (CAP_MIN / ANTON_CAP) * k;
    const shrunk = (maxW - tagRoom(size)) / Math.max(0.5, widthEm(plan.main));
    if (shrunk >= least) size = shrunk;
    else if (plan.main.includes(" ")) {
      lines = twoLines(plan.main);
      size = Math.max(least * 0.85, Math.min(size, ...lines.map((l) => maxW / Math.max(0.5, widthEm(l)))));
    } else size = Math.max(least * 0.7, shrunk);
  }
  // Letter positions over both lines, the key part kept per line.
  let offset = 0;
  const glyphLines = lines.map((l) => {
    const at = plan.main.indexOf(l, offset);
    offset = at + l.length;
    const key: [number, number] | null = plan.key ? [plan.key[0] - at, plan.key[1] - at] : null;
    return glyphsOf(l, key);
  });
  const all = glyphLines.flat();
  const clock = letterStarts(all, S, 2);
  const exitAt = Math.max(clock.last + Math.round(8 * S), dur - Math.round(EXIT * S));
  const exitStep = Math.min(0.5, 4 / Math.max(1, clock.n));
  const sound = useLookSound(letterTicks(clock.starts, S));
  const subSize = plan.sub.length
    ? Math.max(18 * k, Math.min(SUB_PX * k, maxW / Math.max(1, subEm(plan.sub.join(" ··· ")))))
    : 0;
  const lineW = Math.max(...glyphLines.map((g) => widthEm(g.map((x) => x.ch).join("")) * size));
  const ruleP = style === "clean"
    ? easeOut(clamp01((frame - 4 * S) / (14 * S))) * (1 - easeIn(clamp01((frame - exitAt) / (7 * S)))) : 0;
  const shadeP = style === "shade" ? easeOut(clamp01(frame / (10 * S))) * (1 - easeIn(clamp01((frame - exitAt - 2 * S) / (8 * S)))) : 0;
  const tagP = easeOut(clamp01((frame - clock.last + 4 * S) / (10 * S)));
  const tagQ = easeIn(clamp01((frame - exitAt) / (6 * S)));
  const sweep = style === "shine" ? clamp01((frame - clock.last + 2 * S) / (20 * S)) : -1;
  const push = 1 + 0.01 * clamp01((frame - clock.last) / Math.max(1, exitAt - clock.last));
  let gi = 0;
  return (
    <AbsoluteFill>
      {sound}
      <Place align={align} full={full} push={push}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column",
          alignItems: align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start" }}>
          {style === "shade" ? <Shade size={size} k={k} opacity={shadeP} /> : null}
          {glyphLines.map((gl, li) => {
            const from = gi;
            gi += gl.length;
            const row = (
              <MaskLine key={li} glyphs={gl} size={size} style={style} k={k} sweep={sweep}
                y={(i) => letterY(frame, clock.starts[from + i], S, exitAt, from + i, exitStep)} />
            );
            return li === glyphLines.length - 1 && plan.tags.length ? (
              <div key={li} style={{ display: "flex", alignItems: "flex-start" }}>
                {row}
                <Tags tags={plan.tags} size={size} style={style} k={k} p={tagP} q={tagQ} gap={size * 0.14} />
              </div>
            ) : row;
          })}
          {style === "clean" ? (
            <div style={{ marginTop: size * 0.17, marginBottom: plan.sub.length ? size * 0.2 : 0 }}>
              <Rule width={Math.min(lineW, Math.max(1.9 * size * ANTON_CAP, 0.36 * lineW))} align={align} k={k} p={ruleP} />
            </div>
          ) : plan.sub.length ? <div style={{ height: size * 0.3 }} /> : null}
          <SubLine parts={plan.sub} size={subSize} style={style} k={k} inAt={clock.last - 3 * S} outAt={exitAt} frame={frame} S={S} />
        </div>
      </Place>
    </AbsoluteFill>
  );
};

// ================================================================== bt-count
const SCALES: Record<string, string> = { THOUSAND: "K", MILLION: "M", BILLION: "B", TRILLION: "T" };
export type CountPlan = {
  value: number | null; decimals: number; prefix: string;
  /** A letter in the figure itself: "M" in $1.2M, "X" in 3X. */
  inline: string;
  /** A sign set small at the figure's cap top: "%", "°". */
  top: string;
  /** A unit word small beside the figure: "MILLION", "FT", "MPH". */
  tag: string;
  label: string;
};

/** The number, how it is written and what it counts, from value / prefix / suffix / text (spoken numbers in digits). */
export const countPlan = (ov: Overlay): CountPlan => {
  let value = typeof ov.value === "number" && Number.isFinite(ov.value) ? ov.value : null;
  let label = spokenToDigits(str(ov.text)).toUpperCase();
  if (value !== null) {
    // "3 DAYS LATER" with its value 3: the figure counts, the words after it are its label.
    const lead = /^\s*\$?(-?\d[\d,]*(?:\.\d+)?)\s*/.exec(label);
    if (lead && Number(lead[1].replace(/,/g, "")) === value) label = label.slice(lead[0].length);
  }
  if (value === null) {
    // "87 YEARS OLD": the number said in the words, the rest its label.
    const m = /(-?\d[\d,]*(?:\.\d+)?)/.exec(label);
    if (m) {
      const n = Number(m[1].replace(/,/g, ""));
      if (Number.isFinite(n)) {
        value = n;
        label = (label.slice(0, m.index) + label.slice(m.index + m[1].length)).replace(/\s+/g, " ").replace(/^[\s-]+|[\s-]+$/g, "");
      }
    }
  }
  const prefix = str(ov.prefix).slice(0, 3);
  const suffix = str(ov.suffix).toUpperCase().slice(0, 12);
  let inline = "";
  let top = "";
  let tag = "";
  if (suffix === "%" || suffix === "°" || suffix === "°F" || suffix === "°C") top = suffix;
  else if (suffix === "X") inline = "X";
  else if (SCALES[suffix] && prefix === "$") inline = SCALES[suffix];
  else if (["K", "M", "B", "T", "BN", "MN"].includes(suffix) && prefix === "$") inline = suffix[0];
  else if (suffix) tag = suffix;
  const dec = value === null ? 0 : Math.min(2, (String(value).split(".")[1] || "").length);
  return { value, decimals: dec, prefix, inline, top, tag, label: label.replace(/^[·,:\s-]+/, "").slice(0, 44) };
};

const fmt = (v: number, decimals: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: true });

/** One odometer column: the digit at `pos` and the next one under it, rolling up through the window. */
const Column: React.FC<{ pos: number; fill: React.CSSProperties }> = ({ pos, fill }) => {
  const base = Math.floor(pos + 1e-6);
  const frac = Math.max(0, pos - base);
  const a = ((base % 10) + 10) % 10;
  const cell = (d: number, y: number) => (
    <span style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "1em", textAlign: "center", ...fill,
      transform: y ? `translateY(${y.toFixed(4)}em)` : undefined }}>{d}</span>
  );
  // Its own window (the line's mask only moves it): a digit leaves through the top, the next comes up from under it.
  return (
    <span style={{ position: "relative", display: "inline-block", verticalAlign: "top", width: `${DIGIT_W}em`, height: "1em",
      clipPath: "inset(0.035em -0.06em 0.03em -0.06em)" }}>
      {cell(a, -frac * STEP)}
      {frac > 0.001 ? cell((a + 1) % 10, (1 - frac) * STEP) : null}
    </span>
  );
};

const BtCount: Look = ({ overlay }) => {
  const plan = countPlan(overlay);
  return plan.value === null
    ? <CountWords overlay={overlay} words={plan.label || "—"} style={styleOf(overlay)} />
    : <CountFigure overlay={overlay} plan={plan} value={plan.value} />;
};

/** A figure rolling into place, a unit beside it, its label under it. */
const CountFigure: React.FC<{ overlay: Overlay; plan: CountPlan; value: number }> = ({ overlay, plan, value }) => {
  const frame = useCurrentFrame();
  const { fps, width, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const S = fps / 30;
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const style = styleOf(overlay);
  const maxW = (align === "center" || full ? 0.66 : 0.4) * width;

  // The figure as it lands, and which of its characters roll.
  const text = `${plan.prefix}${fmt(value, plan.decimals)}${plan.inline}`;
  const glyphs = glyphsOf(text, [0, text.length]);
  const digitAt = glyphs.map((g) => /[0-9]/.test(g.ch));
  const cols = digitAt.reduce<number[]>((a, d, i) => (d ? [...a, i] : a), []);
  const nc = cols.length;
  // Timing (30 fps): the line rises from frame 2 while the columns roll; the units land last, at C0 + CD.
  const C0 = 2;
  const CD = 28;
  const ends = cols.map((_, c) => C0 + CD - (nc - 1 - c) * 1.5);
  const travel = cols.map((i, c) => Number(glyphs[i].ch) + 10 * Math.min(3, 1 + (nc - 1 - c)));
  const posAt = (c: number, f30: number) => travel[c] * easeOutQuart(clamp01((f30 - C0) / Math.max(1, ends[c] - C0)));
  const landAt = Math.round((C0 + CD) * S);

  // Size: the figure ~60 px tall at 1080p, shrunk to fit the side (with its sign or unit beside it).
  const figEm = glyphs.reduce((a, g, i) => a + (digitAt[i] ? DIGIT_W : advOf(g.ch)) + MAIN_TRACK, 0);
  const extraEm = (plan.top ? advOf(plan.top[0]) * 0.5 + 0.06 : 0) + (plan.tag ? (subEm(plan.tag, 0.06) * 0.4 * ANTON_CAP / SUBLINE_CAP) + 0.16 : 0);
  const size = Math.max((CAP_MIN / ANTON_CAP) * k * 0.8,
    Math.min((CAP_FIGURE / ANTON_CAP) * k, maxW / Math.max(0.5, figEm + extraEm)));

  // The sound: a soft tick on each change of a column (at most one every 2 frames, rising a little), nothing at the landing.
  const cues: SoundCue[] = [];
  {
    let last = -99;
    let n = 0;
    const lastEnd = Math.max(C0 + 1, ...ends);
    for (let f = C0 + 1; f <= Math.ceil(lastEnd); f++) {
      const moved = cols.some((_, c) => Math.floor(posAt(c, f) + 1e-6) !== Math.floor(posAt(c, f - 1) + 1e-6));
      if (!moved || f - last < 2) continue;
      const p = clamp01((f - C0) / CD);
      cues.push({ name: "ui-tick", alt: ["letter-tick", "tick"], at: f, gain_db: -7 + 2 * p,
        pitch: 0.94 + 0.14 * p + 0.03 * jitter(n++) });
      last = f;
    }
  }
  const sound = useLookSound(cues);

  const exitAt = Math.max(landAt + Math.round(8 * S), dur - Math.round(EXIT * S));
  const exitStep = Math.min(0.5, 4 / Math.max(1, glyphs.length));
  // Everything rises together (a frame apart), so the count starts at once.
  const y = (i: number) => {
    const start = Math.round((C0 + i) * S);
    if (frame < start) return BELOW;
    const p = clamp01((frame - start) / (RISE * S));
    const e = easeIn(clamp01((frame - (exitAt + i * exitStep * S)) / (6 * S)));
    return BELOW * (1 - settle(p)) + e * BELOW;
  };
  const f30 = frame / S;
  const render = (i: number, fill: React.CSSProperties) => {
    const c = cols.indexOf(i);
    return c >= 0 ? <Column pos={posAt(c, f30)} fill={fill} /> : null;
  };
  const labelLines = plan.label
    ? (subEm(plan.label) * SUB_PX * k > maxW ? twoLines(plan.label) : [plan.label]) : [];
  const subSize = labelLines.length
    ? Math.max(18 * k, Math.min(SUB_PX * k, ...labelLines.map((l) => maxW / Math.max(1, subEm(l))))) : 0;
  const tagP = easeOut(clamp01((frame - landAt + 6 * S) / (10 * S)));
  const tagQ = easeIn(clamp01((frame - exitAt) / (6 * S)));
  const ruleP = style === "clean"
    ? easeOut(clamp01((frame - 6 * S) / (16 * S))) * (1 - easeIn(clamp01((frame - exitAt) / (7 * S)))) : 0;
  const shadeP = style === "shade" ? easeOut(clamp01(frame / (10 * S))) * (1 - easeIn(clamp01((frame - exitAt - 2 * S) / (8 * S)))) : 0;
  const sweep = style === "shine" ? clamp01((frame - landAt) / (20 * S)) : -1;
  const push = 1 + 0.01 * clamp01((frame - landAt) / Math.max(1, exitAt - landAt));
  const topSize = size * 0.5;
  const figW = figEm * size;
  return (
    <AbsoluteFill>
      {sound}
      <Place align={align} full={full} push={push}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column",
          alignItems: align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start" }}>
          {style === "shade" ? <Shade size={size} k={k} opacity={shadeP} /> : null}
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <MaskLine glyphs={glyphs} size={size} style={style} k={k} y={y} render={render} sweep={sweep} />
            {plan.top ? (
              <div style={{ marginLeft: size * 0.04, paddingTop: (size - topSize) * ANTON_TOP }}>
                <MaskLine glyphs={glyphsOf(plan.top, [0, plan.top.length])} size={topSize} style={style} k={k}
                  y={(i) => y(glyphs.length + i)} sweep={sweep} />
              </div>
            ) : null}
            {plan.tag ? <Tags tags={[plan.tag]} size={size} style={style} k={k} p={tagP} q={tagQ} gap={size * 0.16} /> : null}
          </div>
          {style === "clean" ? (
            <div style={{ marginTop: size * 0.17, marginBottom: labelLines.length ? size * 0.2 : 0 }}>
              <Rule width={Math.min(figW, Math.max(1.9 * size * ANTON_CAP, 0.4 * figW))} align={align} k={k} p={ruleP} />
            </div>
          ) : labelLines.length ? <div style={{ height: size * 0.28 }} /> : null}
          {labelLines.map((l, li) => (
            <div key={li} style={{ marginTop: li ? subSize * 0.42 : 0 }}>
              <SubLine parts={[l]} size={subSize} style={style} k={k} inAt={landAt - Math.round((2 - li * 3) * S)} outAt={exitAt}
                frame={frame} S={S} />
            </div>
          ))}
        </div>
      </Place>
    </AbsoluteFill>
  );
};

/** A count look given words and no number ("RECORD LOW"): the words letter by letter like a date. */
const CountWords: React.FC<{ overlay: Overlay; words: string; style: TextStyle }> = ({ overlay, words, style }) => {
  const frame = useCurrentFrame();
  const { fps, width, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const S = fps / 30;
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const maxW = (align === "center" || full ? 0.66 : 0.4) * width;
  let lines = [words];
  let size = (CAP_DATE / ANTON_CAP) * k;
  if (widthEm(words) * size > maxW) {
    lines = twoLines(words);
    size = Math.max((CAP_MIN / ANTON_CAP) * k * 0.8, Math.min(size, ...lines.map((l) => maxW / Math.max(0.5, widthEm(l)))));
  }
  const glyphLines = lines.map((l) => glyphsOf(l, [0, l.length]));
  const all = glyphLines.flat();
  const clock = letterStarts(all, S, 2);
  const exitAt = Math.max(clock.last + Math.round(8 * S), dur - Math.round(EXIT * S));
  const exitStep = Math.min(0.5, 4 / Math.max(1, clock.n));
  const sound = useLookSound(letterTicks(clock.starts, S));
  const shadeP = style === "shade" ? easeOut(clamp01(frame / (10 * S))) * (1 - easeIn(clamp01((frame - exitAt - 2 * S) / (8 * S)))) : 0;
  const ruleP = style === "clean"
    ? easeOut(clamp01((frame - 4 * S) / (14 * S))) * (1 - easeIn(clamp01((frame - exitAt) / (7 * S)))) : 0;
  const sweep = style === "shine" ? clamp01((frame - clock.last + 2 * S) / (20 * S)) : -1;
  const lineW = Math.max(...lines.map((l) => widthEm(l) * size));
  let gi = 0;
  return (
    <AbsoluteFill>
      {sound}
      <Place align={align} full={full} push={1 + 0.01 * clamp01((frame - clock.last) / Math.max(1, exitAt - clock.last))}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column",
          alignItems: align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start" }}>
          {style === "shade" ? <Shade size={size} k={k} opacity={shadeP} /> : null}
          {glyphLines.map((gl, li) => {
            const from = gi;
            gi += gl.length;
            return (
              <MaskLine key={li} glyphs={gl} size={size} style={style} k={k} sweep={sweep}
                y={(i) => letterY(frame, clock.starts[from + i], S, exitAt, from + i, exitStep)} />
            );
          })}
          {style === "clean" ? (
            <div style={{ marginTop: size * 0.17 }}>
              <Rule width={Math.min(lineW, Math.max(1.9 * size * ANTON_CAP, 0.36 * lineW))} align={align} k={k} p={ruleP} />
            </div>
          ) : null}
        </div>
      </Place>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "dt-letter-drop": DtLetterDrop,
  "bt-count": BtCount,
};
