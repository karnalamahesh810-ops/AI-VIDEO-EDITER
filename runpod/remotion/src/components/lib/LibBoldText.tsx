import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { MONTHS, MON_AP, WEEKDAYS, parseDT, parseRange, type DT } from "./LibDateTime";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";

/**
 * Bold text and nothing else (the owner, 2026-09-30: "NO background layout,
 * ONLY TEXT: the date in white BOLD, on the sides, with a black stroke").
 *
 *   dt-letter-drop  the date / time words ("WEDNESDAY", "SEPTEMBER 30",
 *                   "TUESDAY NIGHT", "3:45 PM", "WED -> THU") in huge white
 *                   condensed caps with a black outline and a soft shadow:
 *                   the letters drop in one by one, each landing with a
 *                   small squash, a crisp tick as each lands and a deep hit
 *                   on the last; the weekday / year / time / place follows in
 *                   a smaller outlined line
 *   bt-count        a number the same way: huge outlined digits counting up
 *                   to the figure (90,000 / 22% / $1.2M), a digit tick on
 *                   every change (at most one every 2 frames, rising a little)
 *                   and a hit as it lands, the words it counts beside or under
 *
 * No box, band or panel behind the words: the outline (paint order: the
 * black stroke drawn in a layer UNDER the white letters, so they stay fat)
 * and a soft dark shadow carry them over any footage, bright or dark.
 * overlay.align places them low on the left, the right or the centre, above
 * the captions' bottom quarter; a full-screen scene centres them.
 *
 * The sound is part of the look (useLookSound): the cues are scheduled from
 * the same frames the letters and digits land on, so they can never drift.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const EXIT = 12;
const WHITE = "#FFFFFF";
const INK = "#000000";

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeIn = (t: number) => t * t * t;
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
/** A small stable jitter per index (tick pitches), no Math.random. */
const jitter = (i: number) => ((Math.sin(i * 12.9898 + 4.1) * 43758.5453) % 1 + 1) % 1;

// ------------------------------------------------------------------ measuring
/** Bebas Neue advance widths in em (a little generous, so nothing clips). */
const bebasEm = (c: string): number =>
  c === " " ? 0.2 : c === "→" ? 0.7 : /[IJ1]/.test(c) ? (c === "I" ? 0.2 : 0.3) : /[MW]/.test(c) ? 0.56
    : /[-]/.test(c) ? 0.28 : /[:.,·]/.test(c) ? 0.2 : c === "%" ? 0.62 : c === "$" ? 0.42 : 0.42;
/** Barlow Condensed 800 caps in em. */
const barlowEm = (c: string): number =>
  c === " " ? 0.22 : /[IJ1]/.test(c) ? 0.26 : /[MW]/.test(c) ? 0.72 : /[:.,·]/.test(c) ? 0.2 : 0.52;
const widthEm = (s: string, em: (c: string) => number, track: number) =>
  [...s].reduce((a, c) => a + em(c) + track, 0);

/** Split a line of words into two balanced lines. */
const twoLines = (s: string): string[] => {
  const words = s.split(" ");
  if (words.length < 2) return [s];
  let best = [s];
  let score = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(" ");
    const b = words.slice(i).join(" ");
    const d = Math.max(a.length, b.length);
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
  const a = String((ov as Overlay & { align?: string }).align || "").toLowerCase();
  if (ov.fullFrame) return "center";
  return a === "right" || a === "center" ? a : "left";
};

/** The block's box: low on a side or the centre, clear of the captions' bottom quarter. */
const Place: React.FC<{ align: Align; full?: boolean; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ align, full, style, children }) => {
    const { width, height } = useVideoConfig();
    const u = width / 1920;
    const side = 104 * u;
    const pos: React.CSSProperties = full
      ? { left: 0, right: 0, top: 0, bottom: 0, justifyContent: "center", alignItems: "center" }
      : align === "center"
        ? { left: side, right: side, bottom: height * 0.26, alignItems: "center" }
        : align === "right"
          ? { right: side, bottom: height * 0.26, alignItems: "flex-end" }
          : { left: side, bottom: height * 0.26, alignItems: "flex-start" };
    return (
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos,
        textAlign: align === "center" ? "center" : align, ...style }}>
        {children}
      </div>
    );
  };

// ------------------------------------------------------------------ outlined letters
type Glyph = { ch: string; space?: boolean; arrow?: boolean };
const glyphsOf = (s: string): Glyph[] =>
  [...s].map((ch) => (ch === "→" ? { ch, arrow: true } : ch === " " ? { ch, space: true } : { ch }));

/** A bold right arrow the size of a letter (ranges), outlined like the letters. */
const Arrow: React.FC<{ size: number; layer: "stroke" | "fill"; stroke: number }> = ({ size, layer, stroke }) => {
  const w = size * 0.62;
  const h = size * 0.46;
  const sw = (stroke * 2 * 62) / w;   // the stroke in viewBox units
  return (
    <svg width={w} height={h} viewBox="0 0 62 46" style={{ overflow: "visible", display: "block" }}>
      <path d="M2 17.5 H38 V28.5 H2 Z M31 3.5 L60 23 L31 42.5 Z" fill={layer === "fill" ? WHITE : INK}
        stroke={layer === "stroke" ? INK : "none"} strokeWidth={layer === "stroke" ? sw : 0} strokeLinejoin="round" />
    </svg>
  );
};

/**
 * One line of outlined letters: every letter drawn twice, a black stroked
 * copy in a layer under a white copy (so the outline never eats into a
 * neighbour or thins the letter), each letter moved by `motion`. The line
 * is a slot (`slot`): letters slide in and out through its top and bottom
 * edges instead of fading, so a letter is never a grey ghost of itself.
 */
const OutlinedLine: React.FC<{
  glyphs: Glyph[]; size: number; font: string; weight: number; track: number; stroke: number; shadow: number;
  motion: (i: number) => React.CSSProperties; tabular?: boolean; slot?: boolean;
}> = ({ glyphs, size, font, weight, track, stroke, shadow, motion, tabular, slot = true }) => {
  const row = (layer: "stroke" | "fill") => glyphs.map((g, i) => {
    if (g.space) return <span key={i} style={{ display: "inline-block", width: `${0.13 + track}em` }} />;
    const m = motion(i);
    const base: React.CSSProperties = { display: "inline-block", marginRight: `${track}em`, transformOrigin: "50% 88%",
      ...m };
    if (g.arrow) {
      return (
        <span key={i} style={{ ...base, verticalAlign: "top", paddingTop: `${0.25}em`, height: "1em" }}>
          <Arrow size={size} layer={layer} stroke={stroke} />
        </span>
      );
    }
    return (
      <span key={i} style={{ ...base, color: layer === "fill" ? WHITE : INK,
        WebkitTextStroke: layer === "stroke" ? `${(stroke * 2).toFixed(2)}px ${INK}` : undefined }}>{g.ch}</span>
    );
  });
  const text: React.CSSProperties = { fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1,
    whiteSpace: "pre", paddingTop: font === DISPLAY ? "0.06em" : 0, fontVariantNumeric: tabular ? "tabular-nums" : undefined };
  return (
    <div style={{ position: "relative", ...text,
      // The slot: open to the sides (outline and shadow), closed just above and below the letters.
      clipPath: slot ? "inset(-0.12em -0.4em -0.04em -0.4em)" : undefined }}>
      <div style={{ filter: `drop-shadow(0 ${(shadow * 0.35).toFixed(2)}px ${(shadow * 0.7).toFixed(2)}px rgba(0,0,0,.62)) `
        + `drop-shadow(0 ${(shadow * 0.2).toFixed(2)}px ${(shadow * 1.8).toFixed(2)}px rgba(0,0,0,.38))` }}>{row("stroke")}</div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, ...text, paddingTop: text.paddingTop }}>
        {row("fill")}
      </div>
    </div>
  );
};

// ------------------------------------------------------------------ timing
/** Frames (at the video's rate) each letter starts falling and lands on the baseline. */
const letterClock = (glyphs: Glyph[], fps: number, lead: number) => {
  const S = fps / 30;
  const n = glyphs.filter((g) => !g.space).length;
  const stagger = n <= 5 ? 3 : n <= 10 ? 2.5 : n <= 16 ? 2 : Math.max(1.25, 34 / Math.max(1, n));
  const fall = Math.round(5 * S);
  let j = 0;
  const starts = glyphs.map((g) => (g.space ? -1 : Math.round((lead + stagger * j++) * S)));
  const lands = starts.map((s) => (s < 0 ? -1 : s + fall));
  const last = Math.max(fall, ...lands);
  return { starts, lands, fall, last, S };
};

/** How far a letter hides above or below the slot. */
const OUT = 1.1;

/**
 * A letter falling into its slot from above (gravity: slow, then fast),
 * landing on its frame with a squash that springs back; at the exit it
 * sinks out through the bottom of the slot, `exitStep` frames after the
 * letter before it.
 */
const dropMotion = (frame: number, start: number, land: number, S: number, exitAt: number, exitIndex: number,
  exitStep: number): React.CSSProperties => {
  if (start < 0) return {};
  if (frame < start) return { visibility: "hidden" };
  const p = clamp01((frame - start) / Math.max(1, land - start));
  const y = -OUT * (1 - easeIn(p));
  const t = (frame - land) / S;
  const sq = t < 0 ? 0 : Math.exp(-t / 1.7) * Math.cos(t * 1.3);
  const stretch = t < 0 ? 0.08 * p * p : 0;
  const e = easeIn(clamp01((frame - (exitAt + exitIndex * exitStep * S)) / (6 * S)));
  return {
    transform: `translateY(${(y + e * OUT).toFixed(4)}em) scale(${(1 + 0.07 * sq - stretch * 0.4).toFixed(4)}, `
      + `${(1 - 0.14 * sq + stretch).toFixed(4)})`,
  };
};

/** A letter rising into its slot from below (the smaller lines), and sinking back out of it at the exit. */
const riseMotion = (frame: number, start: number, S: number, exitAt: number): React.CSSProperties => {
  if (frame < start) return { visibility: "hidden" };
  const p = easeOut(clamp01((frame - start) / (6 * S)));
  const e = easeIn(clamp01((frame - exitAt) / (6 * S)));
  return { transform: `translateY(${((1 - p) * OUT + e * OUT).toFixed(4)}em)` };
};

/** The hit's punch on the whole block: a small bump and a short decaying shake. */
const punchAt = (frame: number, at: number, S: number, u: number) => {
  const t = (frame - at) / S;
  if (t < 0 || t > 16) return { scale: 1, x: 0, y: 0 };
  const bump = t < 0 ? 0 : (t / 2) * Math.exp(1 - t / 2);
  const decay = Math.exp(-t / 3.2);
  return { scale: 1 + 0.03 * bump, x: Math.sin(t * 2.7 + 0.5) * 3.2 * u * decay, y: Math.cos(t * 3.4) * 2.2 * u * decay };
};

// ================================================================== dt-letter-drop
type DatePlan = { main: string; sub: string };

/** The sub line's outline: ~3.5 px on a 60 px line, thinner as it gets smaller. */
const subStroke0 = (px: number, k: number) => 3.6 * (px / (60 * k || 1));

const PARTS = /\b(MORNING|AFTERNOON|EVENING|NIGHT|OVERNIGHT)\b/;
const clockOf = (d: DT, raw: string): string => {
  if (d.hour === undefined) return "";
  if (/\bNOON\b|\bMIDDAY\b/.test(raw)) return "NOON";
  if (/\bMIDNIGHT\b/.test(raw)) return "MIDNIGHT";
  const m = d.minute ?? 0;
  return m ? `${d.hour}:${String(m).padStart(2, "0")} ${d.ampm || ""}`.trim() : `${d.hour} ${d.ampm || ""}`.trim();
};
const join = (...xs: (string | undefined)[]) => xs.filter((x) => !!x).slice(0, 3).join("  ·  ");
const WD3 = WEEKDAYS.map((w) => w.slice(0, 3));

/** What the look says: the date words big, the rest (weekday, year, time, place) small. */
export const datePlan = (ov: Overlay): DatePlan => {
  const raw = str(ov.text).toUpperCase().replace(/[’']/g, "");
  const d = parseDT(ov.text, ov.label, ov.value);
  const place = d.place || str(ov.subtitle).toUpperCase().slice(0, 36);
  const rg = parseRange(ov.text);
  if (rg) {
    const { a, b } = rg;
    if (a.month !== undefined && b.month !== undefined && a.day !== undefined && b.day !== undefined) {
      const main = a.month === b.month ? `${MONTHS[a.month]} ${a.day}-${b.day}` : `${MON_AP[a.month]} ${a.day} → ${MON_AP[b.month]} ${b.day}`;
      return { main, sub: join(b.year !== undefined ? String(b.year) : a.year !== undefined ? String(a.year) : "", place) };
    }
    if (a.hour !== undefined && b.hour !== undefined && a.month === undefined) {
      return { main: `${clockOf(a, "")} → ${clockOf(b, "")}`, sub: join(d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", place) };
    }
    if (a.weekday !== undefined && b.weekday !== undefined && a.month === undefined && b.month === undefined) {
      return { main: `${WD3[a.weekday]} → ${WD3[b.weekday]}`, sub: join(clockOf(a, ""), place) };
    }
    if (a.year !== undefined && b.year !== undefined && a.month === undefined) return { main: `${a.year} → ${b.year}`, sub: place };
  }
  const wd = d.weekday !== undefined ? WEEKDAYS[d.weekday] : "";
  const year = d.year !== undefined ? String(d.year) : "";
  const clock = clockOf(d, raw);
  if (d.month !== undefined && d.day !== undefined) return { main: `${MONTHS[d.month]} ${d.day}`, sub: join(wd, clock, year, place) };
  if (d.month !== undefined) return { main: year ? `${MONTHS[d.month]} ${year}` : MONTHS[d.month], sub: join(wd, clock, place) };
  if (d.year !== undefined) return { main: year, sub: join(wd, clock, place) };
  if (clock) return { main: clock, sub: join(wd, place) };
  if (wd) {
    // "TUESDAY NIGHT": the weekday with the part of the day said with it.
    const part = PARTS.exec(raw);
    return { main: part && raw.includes(wd) ? `${wd} ${part[1]}` : wd, sub: place };
  }
  return { main: raw.slice(0, 30) || "—", sub: place };
};

const DtLetterDrop: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, width, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const u = width / 1920;
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const plan = datePlan(overlay);
  // The main line as large as it fits: the side of the frame, or the width of the centre.
  const maxW = (align === "center" || full ? 1600 : 1080) * u;
  const TRACK = 0.02;
  let lines = [plan.main];
  let size = Math.min(212 * k, maxW / Math.max(0.5, widthEm(plan.main, bebasEm, TRACK)));
  if (size < 118 * k && plan.main.includes(" ")) {
    lines = twoLines(plan.main);
    size = Math.min(190 * k, ...lines.map((l) => maxW / Math.max(0.5, widthEm(l, bebasEm, TRACK))));
  }
  const glyphLines = lines.map(glyphsOf);
  const all = glyphLines.flat();
  const clock = letterClock(all, fps, 3);
  const S = clock.S;
  const exitAt = Math.max(clock.last + 4 * S, dur - EXIT * S);
  // The letters sink out one after another, the last gone by the look's final frame.
  const exitStep = Math.min(0.7, 5 / Math.max(1, all.length));
  const hit = clock.last;
  // The sub line: smaller outlined caps, fitted to the main line's width (at least a readable size).
  const subSize = plan.sub ? Math.max(40 * k, Math.min(62 * k, size * 0.33,
    Math.max(maxW, size * widthEm(lines[0], bebasEm, TRACK)) / Math.max(0.5, widthEm(plan.sub, barlowEm, 0.08)))) : 0;
  const stroke = Math.max(3.2, Math.min(6, 5.6 * (size / (200 * k)))) * k;
  const subStroke = Math.max(2.4, Math.min(4, subStroke0(subSize, k))) * k;
  // Its sound, from the frames the letters land on: a quiet tick as each lands
  // (never two within 2 frames), the date slam on the last (the deep hit its stand-in).
  const cues: SoundCue[] = [];
  let lastTick = -99;
  clock.lands.forEach((f, i) => {
    if (f < 0 || f >= hit) return;
    const f30 = f / S;
    if (f30 - lastTick < 2) return;
    lastTick = f30;
    // The sound designer's letter-by-letter recipe: a letter tick at -6 dB, the date slam on the landing.
    cues.push({ name: "letter-tick", alt: ["ui-tick", "tick"], at: f30, gain_db: -6, pitch: 0.95 + 0.1 * jitter(i) });
  });
  cues.push({ name: "date-slam", alt: ["hit-deep"], at: hit / S, fixed: true });
  const sound = useLookSound(cues);
  const pk = punchAt(frame, hit, S, u);
  const hold = 1 + 0.028 * clamp01((frame - hit) / Math.max(1, exitAt - hit));
  const origin = align === "right" ? "100% 100%" : align === "center" || full ? "50% 100%" : "0% 100%";
  const subAt = hit + 3 * S;
  let gi = 0;
  return (
    <AbsoluteFill>
      {sound}
      <Place align={align} full={full} style={{ transformOrigin: origin,
        transform: `translate(${pk.x.toFixed(2)}px, ${pk.y.toFixed(2)}px) scale(${(pk.scale * hold).toFixed(4)})` }}>
        {glyphLines.map((gl, li) => {
          const offset = gi;
          gi += gl.length;
          return (
            <OutlinedLine key={li} glyphs={gl} size={size} font={DISPLAY} weight={400} track={TRACK} stroke={stroke}
              shadow={16 * k} motion={(i) => dropMotion(frame, clock.starts[offset + i], clock.lands[offset + i], S, exitAt,
                offset + i, exitStep)} />
          );
        })}
        {plan.sub ? (
          <div style={{ marginTop: size * 0.06 }}>
            <OutlinedLine glyphs={glyphsOf(plan.sub)} size={subSize} font={LABEL} weight={800} track={0.08} stroke={subStroke}
              shadow={10 * k} motion={(i) => riseMotion(frame, subAt + i * 0.6 * S, S, exitAt - 2 * S)} />
          </div>
        ) : null}
      </Place>
    </AbsoluteFill>
  );
};

// ================================================================== bt-count
const SCALES: Record<string, string> = { THOUSAND: "K", MILLION: "M", BILLION: "B", TRILLION: "T" };
type CountPlan = { value: number | null; decimals: number; prefix: string; unit: string; unitSmall: boolean; label: string };

/** The number, how it is written and what it counts, from value / prefix / suffix / text (an age from the words). */
export const countPlan = (ov: Overlay): CountPlan => {
  let value = typeof ov.value === "number" && Number.isFinite(ov.value) ? ov.value : null;
  let label = str(ov.text).toUpperCase();
  if (value !== null) {
    // "3 DAYS LATER" with its value 3: the figure counts, the words after it are its label.
    const lead = /^\s*\$?(-?\d[\d,]*(?:\.\d+)?)\s+/.exec(label);
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
  let unit = suffix;
  let unitSmall = false;
  if (suffix === "%" || suffix === "°" || suffix === "X") unitSmall = false;
  else if (SCALES[suffix] && prefix === "$") unit = SCALES[suffix];
  else if (suffix) unitSmall = true;
  const dec = value === null ? 0 : Math.min(2, (String(value).split(".")[1] || "").length);
  return { value, decimals: dec, prefix, unit, unitSmall, label: label.slice(0, 44) };
};

const fmt = (v: number, decimals: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: true });

const BtCount: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, width, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const u = width / 1920;
  const S = fps / 30;
  const align = alignOf(overlay);
  const full = Boolean(overlay.fullFrame);
  const plan = countPlan(overlay);
  const C0 = Math.round(5 * S);
  const CD = Math.round(36 * S);
  const landAt = C0 + CD;
  const shown = (f: number): string => {
    if (plan.value === null) return "";
    const e = easeOut(clamp01((f - C0) / CD));
    return fmt(f >= landAt ? plan.value : plan.value * e, plan.decimals);
  };
  const finalText = plan.value === null ? "" : fmt(plan.value, plan.decimals);
  // The whole figure as it will read, for fitting: prefix, digits, unit.
  const bigText = `${plan.prefix}${finalText}${plan.unitSmall ? "" : plan.unit}`;
  const maxW = (align === "center" || full ? 1500 : 1000) * u;
  const unitEm = plan.unitSmall ? widthEm(plan.unit, barlowEm, 0.06) * 0.4 + 0.12 : 0;
  const size = plan.value === null
    ? Math.min(150 * k, maxW / Math.max(0.5, widthEm(plan.label || "—", bebasEm, 0.02)))
    : Math.min(280 * k, maxW / Math.max(0.5, widthEm(bigText, bebasEm, 0.01) + unitEm));
  const stroke = Math.max(3.4, Math.min(6.2, 5.8 * (size / (220 * k)))) * k;
  // The label beside a short figure, else under it.
  // (A unit word already rides beside the figure: then the label goes under it.)
  const beside = plan.value !== null && bigText.length <= 4 && plan.label.length > 0 && plan.label.length <= 26
    && !(plan.unitSmall && plan.unit) && align !== "center" && !full;
  const labelLines = plan.label ? (plan.label.length > 22 ? twoLines(plan.label) : [plan.label]) : [];
  const labelSize = plan.value === null ? 0 : Math.max(38 * k, Math.min(beside ? 70 * k : 64 * k, size * (beside ? 0.3 : 0.27)));
  // Its sound, from the displayed number: a digit tick on each change (at most
  // one every 2 frames, rising a little), the landing hit on the final figure.
  const cues: SoundCue[] = [];
  if (plan.value !== null) {
    let prev = shown(C0 - 1);
    let last = -99;
    let n = 0;
    for (let f = C0; f < landAt; f++) {
      const s = shown(f);
      if (s !== prev && f - last >= 2 * S) {
        const p = (f - C0) / CD;
        cues.push({ name: "ui-tick", alt: ["tick"], at: f / S, gain_db: -6.5 + 3 * p, pitch: 0.92 + 0.2 * p + 0.03 * jitter(n++) });
        last = f;
      }
      prev = s;
    }
    cues.push({ name: "count-final", alt: ["boom-soft", "hit-deep"], at: landAt / S });
  } else {
    cues.push({ name: "swoosh-text", alt: ["whoosh-soft"], at: 8 });
  }
  const sound = useLookSound(cues);
  const exitAt = Math.max(landAt + 4 * S, dur - EXIT * S);
  const pk = plan.value === null ? { scale: 1, x: 0, y: 0 } : punchAt(frame, landAt, S, u);
  const hold = 1 + 0.025 * clamp01((frame - landAt) / Math.max(1, exitAt - landAt));
  const inP = easeOut(clamp01(frame / (6 * S)));
  const origin = align === "right" ? "100% 100%" : align === "center" || full ? "50% 100%" : "0% 100%";
  const now = plan.value === null ? "" : `${plan.prefix}${shown(frame)}${plan.unitSmall ? "" : plan.unit}`;
  // Digits rise into the slot as one block (the count is the motion), then sink out in a wave.
  const digitMotion = (i: number): React.CSSProperties => {
    const e = easeIn(clamp01((frame - (exitAt + i * 0.6 * S)) / (6 * S)));
    return { transform: `translateY(${((1 - inP) * OUT + e * OUT).toFixed(4)}em)` };
  };
  const labelAt = C0 + 6 * S;
  const anchor: React.CSSProperties = align === "right" ? { right: 0 } : align === "center" || full
    ? { left: 0, right: 0, display: "flex", justifyContent: "center" } : { left: 0 };
  const number = plan.value === null ? null : (
    <div style={{ display: "flex", alignItems: "flex-end", gap: size * 0.05 }}>
      {/* The final figure's width is kept while it counts, so the block never jumps. */}
      <div style={{ position: "relative" }}>
        <div style={{ visibility: "hidden" }}>
          <OutlinedLine glyphs={glyphsOf(bigText)} size={size} font={DISPLAY} weight={400} track={0.01} stroke={stroke}
            shadow={0} motion={() => ({})} tabular slot={false} />
        </div>
        <div style={{ position: "absolute", top: 0, ...anchor }}>
          <OutlinedLine glyphs={glyphsOf(now)} size={size} font={DISPLAY} weight={400} track={0.01} stroke={stroke}
            shadow={18 * k} motion={digitMotion} tabular />
        </div>
      </div>
      {plan.unitSmall && plan.unit ? (
        <div style={{ paddingBottom: size * 0.1 }}>
          <OutlinedLine glyphs={glyphsOf(plan.unit)} size={size * 0.4} font={LABEL} weight={800} track={0.06}
            stroke={Math.max(2.6 * k, stroke * 0.62)} shadow={10 * k} motion={(i) => riseMotion(frame, C0 + (3 + i) * S, S, exitAt)} />
        </div>
      ) : null}
    </div>
  );
  const label = labelLines.length && plan.value !== null ? (
    <div style={{ display: "flex", flexDirection: "column", alignItems: align === "right" ? "flex-end" : align === "center" || full ? "center" : "flex-start",
      gap: labelSize * 0.08, ...(beside ? { paddingBottom: size * 0.12 } : { marginTop: size * 0.02 }) }}>
      {labelLines.map((l, li) => (
        <OutlinedLine key={li} glyphs={glyphsOf(l)} size={labelSize} font={LABEL} weight={800} track={0.06}
          stroke={Math.max(2.4 * k, 3.6 * (labelSize / (60 * k)) * k)} shadow={10 * k}
          motion={(i) => riseMotion(frame, labelAt + (li * 4 + i * 0.5) * S, S, exitAt - 2 * S)} />
      ))}
    </div>
  ) : null;
  const words = plan.value === null ? (
    <OutlinedLine glyphs={glyphsOf(plan.label || "—")} size={size} font={DISPLAY} weight={400} track={0.02} stroke={stroke}
      shadow={16 * k} motion={(i) => riseMotion(frame, i * 0.8 * S, S, exitAt)} />
  ) : null;
  return (
    <AbsoluteFill>
      {sound}
      <Place align={align} full={full} style={{ transformOrigin: origin,
        transform: `translate(${pk.x.toFixed(2)}px, ${pk.y.toFixed(2)}px) scale(${(pk.scale * hold).toFixed(4)})` }}>
        {words}
        {number ? (
          beside ? (
            <div style={{ display: "flex", flexDirection: align === "right" ? "row-reverse" : "row", alignItems: "flex-end",
              gap: size * 0.12 }}>
              {number}
              {label}
            </div>
          ) : (
            <>
              {number}
              {label}
            </>
          )
        ) : null}
      </Place>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "dt-letter-drop": DtLetterDrop,
  "bt-count": BtCount,
};
