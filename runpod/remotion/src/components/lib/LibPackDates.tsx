import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, ANTON_CAP, SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { MONTHS, MON_AP, WEEKDAYS, parseDT, parseRange, type DT } from "./LibDateTime";
import { spokenToDigits } from "./numWords";

/**
 * PACK A - dates and times as clean text on the footage (family "dtx"; the
 * owner's rules, 2026-10-01: premium news lettering, no stroke, no box, not
 * big; white with an amber key; digits always; 2-frame stagger reveals, a
 * small settle, a hold and an 11-frame exit; 96 px safe margins). Anton for
 * the line that carries it (cap 44-64 px at 1080p), Inter Tight tracked caps
 * for the small line (20-26 px), a soft dark shadow and, behind each block, a
 * feathered shade so it reads on snow and on night footage alike.
 *
 *   dtx-time-stamp     TOP-LEFT     "3:45 PM ET": an amber tick, the time, AM/PM + zone stacked small
 *   dtx-date-top       TOP-CENTER   "SEPTEMBER 26": letters rise centre-out, the day in amber, a hairline under
 *   dtx-date-place     BOTTOM-LEFT  "SATURDAY · ATLANTIC CITY": one dateline, an amber dot between
 *   dtx-date-range     LOWER-LEFT   "SEP 26 → SEP 28": the first end, an amber arrow drawing, the second end; "3 DAYS"
 *   dtx-day-marker     TOP-RIGHT    "DAY 3": the figure rolls up to its value in amber
 *   dtx-time-of-day    LOWER-LEFT   "TONIGHT 8 PM" / "TOMORROW MORNING": the key part warms to amber as it lands
 *   dtx-lead-time      LOWER-RIGHT  "NEXT 72 HOURS": the figure counts up, a hairline window fills under it
 *   dtx-updated-stamp  TOP-LEFT     "UPDATED 6:00 AM": a small stamp, an amber dot
 *   dtx-week-strip     LOWER-CENTER MON..SUN in small caps, an amber underline slides to the day
 *   dtx-weekday-stack  BOTTOM-RIGHT the weekday small in amber over the date
 *   dtx-year-marker    LOWER-LEFT   "1937": the digits rise one by one, an amber line runs out to a node
 *   dtx-relative-tag   TOP-LEFT     "LAST NIGHT" / "THIS MORNING": an amber dash, the words
 *   dtx-clock-live     TOP-RIGHT    a clock time with a tiny pulsing live dot (no box)
 *
 * Every motion runs on fixed frames (30 fps, scaled to the video's rate), so
 * each look's built-in sound (scripts/look_sounds.json, played by
 * LookSounds) lands on what it hears: soft letter ticks, a text swoosh, a
 * count roll - never a hit. The words are read robustly (parseDT /
 * parseRange, spoken numbers in digits); nothing missing ever throws: a look
 * with nothing it understands prints its words.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type CSS = React.CSSProperties;

// ------------------------------------------------------------------ the type
const WHITE = "#FFFFFF";
const AMBER = "#F5B400";
const LIVE = "#FF3B30";
const EXIT = 11;                 // frames (30 fps) the look takes to leave
const BELOW = 1.15;              // em under the line a hidden letter waits
const RISE = 9;                  // frames a letter takes to rise and settle
const TRACK = 0.016;             // Anton's letter spacing (em)
const SUB_TRACK = 0.16;          // the small line's (em)
const SUB_PX = 24;               // the small line's size at 1080p
const DIGIT_W = 0.494;           // an Anton digit cell (em)
const STEP = 1.15;               // em between two figures on a rolling strip
const MASK = "inset(-0.06em -0.6em -0.1em -0.6em)";
const ANTON_TOP = 0.065;         // Anton's cap top in a 1-em line box
const SUB_TOP = 0.136;           // Inter Tight's
const CAP_MID = 0.4945;          // Anton's cap middle in a 1-em line box

/** Anton's advance widths (em). */
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, "0": 0.494, "1": 0.331, "2": 0.494, "3": 0.494, "4": 0.494, "5": 0.494,
  "6": 0.494, "7": 0.494, "8": 0.494, "9": 0.494, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, "%": 1.057,
  "$": 0.462, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "&": 0.52, "/": 0.405, "#": 0.546,
  "•": 0.62,
};
const advOf = (c: string) => ADV[c] ?? 0.48;
const widthEm = (s: string) => Array.from(s).reduce((a, c) => a + advOf(c) + TRACK, 0);
/** Inter Tight 700 caps, roughly (em). */
const subEm = (s: string, track = SUB_TRACK) =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.234 : /[0-9]/.test(c) ? 0.56 : /[MW]/.test(c) ? 0.86
    : /[IJ1.,:'·]/.test(c) ? 0.3 : 0.64) + track, 0);

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeIn = (t: number) => t * t * t;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
/** Ease-out with a small overshoot (about 3 %): the settle. */
const settle = (t: number, s = 0.9) => 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2;
/** White to the amber key (0-1). */
const warmColor = (t: number) => {
  const p = clamp01(t);
  return `rgb(${Math.round(255 - 10 * p)},${Math.round(255 - 75 * p)},${Math.round(255 - 255 * p)})`;
};

// ------------------------------------------------------------------ reading the words
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
/** Upper case, spoken numbers in digits ("day three" -> "DAY 3"), never throwing. */
const up = (v: unknown): string => {
  const s = str(v);
  let out = s;
  try {
    out = spokenToDigits(s);
  } catch {
    out = s;
  }
  return out.toUpperCase().replace(/[’']/g, "").replace(/\s+/g, " ").trim();
};
/** At most n characters, cut at a word. */
const clip = (s: string, n: number) => {
  if (s.length <= n) return s;
  const cut = s.slice(0, n).replace(/\s+\S*$/, "").trim();
  return cut || s.slice(0, n);
};
const safeDT = (text: string, label?: unknown, value?: unknown): DT => {
  try {
    return parseDT(text, up(label), value);
  } catch {
    return {};
  }
};
const safeRange = (text: string) => {
  try {
    return parseRange(text);
  } catch {
    return null;
  }
};
const ZONE_RX = /\b(ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|AKST|AKDT|HST|UTC|GMT)\b/;
const zoneOf = (raw: string) => ZONE_RX.exec(raw)?.[1] || "";
const two = (n: number) => String(Math.max(0, Math.floor(n))).padStart(2, "0");
/** "8:00", "3:45" (a stamp always shows its minutes). */
const hmFull = (d: DT) => (d.hour === undefined ? "" : `${d.hour}:${two(d.minute ?? 0)}`);
/** "8", "8:30" (a spoken time: "8 PM"). */
const hmShort = (d: DT) => (d.hour === undefined ? "" : d.minute ? `${d.hour}:${two(d.minute)}` : String(d.hour));
const clockWords = (d: DT) => `${hmShort(d)} ${d.ampm || ""}`.trim();
const wdOf = (d: DT) => (d.weekday !== undefined ? WEEKDAYS[d.weekday] ?? "" : "");
const MON3 = MONTHS.map((m) => m.slice(0, 3));
const WD3 = WEEKDAYS.map((w) => w.slice(0, 3));
const placeOf = (ov: Overlay, d: DT) => clip((d.place || up(ov.subtitle)).replace(/[.,;:]+$/, ""), 28);
const hasDay = (d: DT) => d.month !== undefined && d.day !== undefined;
/** Julian day number (no Date object: renders stay deterministic). */
const jdn = (y: number, m0: number, d: number) => {
  const a = m0 < 2 ? 1 : 0;
  const yy = y + 4800 - a;
  const mm = m0 + 1 + 12 * a - 3;
  return d + Math.floor((153 * mm + 2) / 5) + 365 * yy + Math.floor(yy / 4) - Math.floor(yy / 100) + Math.floor(yy / 400) - 32045;
};
const minutesOf = (d: DT) => (((d.hour ?? 0) % 12) + (d.ampm === "PM" ? 12 : 0)) * 60 + (d.minute ?? 0);
const keyAtEnd = (main: string, part: string): [number, number] | null => {
  const at = part ? main.lastIndexOf(part) : -1;
  return at >= 0 ? [at, at + part.length] : null;
};

// ------------------------------------------------------------------ timing
type G = { ch: string; amber?: boolean };
const glyphsOf = (s: string, amber?: [number, number] | null): G[] =>
  Array.from(s).map((ch, i) => ({ ch, amber: Boolean(amber && i >= amber[0] && i < amber[1]) }));

type Clock = { starts: number[]; first: number; last: number };
/**
 * When each letter starts rising (video frames): `lead` frames in (30 fps),
 * `step` apart - closer for a long line so it never spreads past `spread` -
 * left to right, or from the middle out.
 */
const stagger = (g: G[], S: number, lead: number, step = 2, spread = 12, center = false): Clock => {
  const n = g.filter((x) => x.ch !== " ").length;
  const mid = (n - 1) / 2;
  const st = n > 1 ? Math.min(step, spread / Math.max(1, center ? mid : n - 1)) : 0;
  let j = 0;
  const starts = g.map((x) => {
    if (x.ch === " ") return -1;
    const r = center ? Math.abs(j - mid) : j;
    j += 1;
    return Math.round((lead + st * r) * S);
  });
  const on = starts.filter((s) => s >= 0);
  const first = on.length ? Math.min(...on) : Math.round(lead * S);
  const lastStart = on.length ? Math.max(...on) : Math.round(lead * S);
  return { starts, first, last: lastStart + Math.round(RISE * S) };
};

/** A letter's offset (em): up out of its mask with a small settle, back down into it at the exit. */
const glyphY = (f: number, start: number, S: number, exitAt: number, i: number): number => {
  if (start < 0) return 0;
  if (f < start) return BELOW;
  const p = clamp01((f - start) / (RISE * S));
  const e = easeIn(clamp01((f - exitAt - Math.min(i, 8) * 0.5 * S) / (6 * S)));
  return BELOW * (1 - settle(p)) + e * BELOW;
};
const exitOf = (last: number, dur: number, S: number) => Math.max(last + Math.round(6 * S), dur - Math.round(EXIT * S));
const inOf = (f: number, at: number, frames: number) => easeOut(clamp01((f - at) / Math.max(1, frames)));
const outOf = (f: number, exitAt: number, frames: number) => easeIn(clamp01((f - exitAt) / Math.max(1, frames)));
const featherOf = (f: number, S: number, exitAt: number) => inOf(f, 0, 10 * S) * (1 - outOf(f, exitAt + 2 * S, 8 * S));
const pushOf = (f: number, settled: number, exitAt: number) => 1 + 0.008 * clamp01((f - settled) / Math.max(1, exitAt - settled));

/** The main line's size (px) from its cap height at 1080p, shrunk to fit (never under minCap). */
const fit = (em: number, cap: number, minCap: number, maxW: number, k: number) =>
  Math.max((minCap / ANTON_CAP) * k, Math.min((cap / ANTON_CAP) * k, maxW / Math.max(0.5, em)));
const subFit = (parts: string[], maxW: number, k: number) =>
  Math.max(18 * k, Math.min(SUB_PX * k, maxW / Math.max(1, subEm(parts.join(" · ")) + 0.3 * Math.max(0, parts.length - 1))));

// ------------------------------------------------------------------ drawing
/** The soft dark shadow (on a wrapper, so a mask never cuts it): no stroke, no box. */
const shadow = (k: number) =>
  `drop-shadow(0 ${(2 * k).toFixed(2)}px ${(5 * k).toFixed(2)}px rgba(0,0,0,.55)) `
  + `drop-shadow(0 ${(1 * k).toFixed(2)}px ${(1 * k).toFixed(2)}px rgba(0,0,0,.6))`;

type Spot = "tl" | "tc" | "tr" | "bl" | "br" | "l3" | "c3" | "r3";
/**
 * Where a block sits: a corner at the 96 px safe margin (at 1080p), or the
 * lower third (its foot a quarter of the height up, clear of the captions);
 * a full-screen scene centres it. `push` is a slow drift while it holds.
 */
const Anchor: React.FC<{ spot: Spot; full?: boolean; push?: number; children: React.ReactNode }> =
  ({ spot, full, push = 1, children }) => {
    const { width, height } = useVideoConfig();
    const m = 96 * (width / 1920);
    const foot = height * 0.25;
    const h = full ? "c" : spot === "tl" || spot === "bl" || spot === "l3" ? "l" : spot === "tr" || spot === "br" || spot === "r3" ? "r" : "c";
    const top = !full && spot[0] === "t";
    const pos: CSS = full
      ? { left: 0, right: 0, top: 0, bottom: 0, justifyContent: "center" }
      : {
        ...(h === "l" ? { left: m } : h === "r" ? { right: m } : { left: m, right: m }),
        ...(top ? { top: m } : spot === "bl" || spot === "br" ? { bottom: m } : { bottom: foot }),
      };
    return (
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos,
        alignItems: h === "l" ? "flex-start" : h === "r" ? "flex-end" : "center",
        textAlign: h === "l" ? "left" : h === "r" ? "right" : "center",
        transformOrigin: `${h === "l" ? "0%" : h === "r" ? "100%" : "50%"} ${top ? "0%" : "100%"}`,
        transform: `scale(${((full ? 1.3 : 1) * push).toFixed(4)})` }}>
        {children}
      </div>
    );
  };

/** A block of lines (its own stacking context, so the shade sits under it). */
const Block: React.FC<{ align: "l" | "r" | "c"; children: React.ReactNode }> = ({ align, children }) => (
  <div style={{ position: "relative", isolation: "isolate", display: "flex", flexDirection: "column",
    alignItems: align === "l" ? "flex-start" : align === "r" ? "flex-end" : "center" }}>
    {children}
  </div>
);

/** The feathered shade behind a block: a blurred dark ellipse, no edge anywhere. */
const Feather: React.FC<{ k: number; o: number; x?: number; y?: number }> = ({ k, o, x = 120, y = 64 }) => (o > 0.001 ? (
  <div style={{ position: "absolute", left: -x * k, right: -x * k, top: -y * k, bottom: -y * k, zIndex: -1, opacity: o,
    background: "radial-gradient(closest-side, rgba(0,0,0,.42), rgba(0,0,0,.27) 48%, rgba(0,0,0,.09) 78%, rgba(0,0,0,0) 100%)",
    filter: `blur(${(12 * k).toFixed(1)}px)`, pointerEvents: "none" }} />
) : null);

/**
 * One Anton line in its mask. `y(i)` is letter i's offset in em; amber
 * letters take `warm` (0 white - 1 amber); `cells` sets digits in equal
 * cells; `render(i)` may draw a letter itself (a rolling figure).
 */
const Line: React.FC<{
  g: G[]; size: number; k: number; y: (i: number) => number; warm?: number; cells?: boolean;
  render?: (i: number, color: string) => React.ReactNode | null; dim?: (i: number) => number;
}> = ({ g, size, k, y, warm = 1, cells, render, dim }) => (
  <div style={{ filter: shadow(k) }}>
    <div style={{ clipPath: MASK, fontFamily: ANTON, fontWeight: 400, fontSize: size, lineHeight: 1, whiteSpace: "pre",
      letterSpacing: 0, height: "1em" }}>
      {g.map((x, i) => {
        const off = y(i);
        const box: CSS = { display: "inline-block", verticalAlign: "top", height: "1em", marginRight: `${TRACK}em`,
          transform: off ? `translateY(${off.toFixed(4)}em)` : undefined, visibility: off >= BELOW - 1e-3 ? "hidden" : undefined,
          opacity: dim ? dim(i) : undefined };
        if (x.ch === " ") return <span key={i} style={{ ...box, width: `${advOf(" ")}em` }} />;
        const color = x.amber ? warmColor(warm) : WHITE;
        const own = render ? render(i, color) : null;
        if (own) return <span key={i} style={{ ...box, position: "relative" }}>{own}</span>;
        if (x.ch === "•") {
          return (
            <span key={i} style={{ ...box, position: "relative", width: `${advOf("•")}em` }}>
              <span style={{ position: "absolute", left: "0.225em", top: `${(CAP_MID - 0.085).toFixed(4)}em`, width: "0.17em",
                height: "0.17em", borderRadius: "50%", background: AMBER }} />
            </span>
          );
        }
        if (cells && /[0-9]/.test(x.ch)) {
          return <span key={i} style={{ ...box, width: `${DIGIT_W}em`, textAlign: "center", color }}>{x.ch}</span>;
        }
        return <span key={i} style={{ ...box, color }}>{x.ch}</span>;
      })}
    </div>
  </div>
);

/** The small line: tracked Inter Tight caps, parts parted by a small amber dot. */
const Parts: React.FC<{ parts: string[]; size: number; k: number; color?: string; dot?: string; track?: number; right?: boolean }> =
  ({ parts, size, k, color = "rgba(255,255,255,.95)", dot = AMBER, track = SUB_TRACK, right }) => (
    <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1, letterSpacing: `${track.toFixed(4)}em`,
      textTransform: "uppercase", whiteSpace: "nowrap", color, filter: shadow(k * 0.85),
      marginRight: right ? `${(-track).toFixed(4)}em` : undefined }}>
      {parts.map((s, i) => (
        <React.Fragment key={i}>
          {i ? <span style={{ display: "inline-block", width: "0.24em", height: "0.24em", borderRadius: "50%",
            margin: "0 0.62em 0 0.46em", verticalAlign: "middle", transform: "translateY(-0.1em)", background: dot }} /> : null}
          <span>{s}</span>
        </React.Fragment>
      ))}
    </div>
  );

/** Fade-blur in (rising a little) and out; it keeps its room while hidden, so nothing jumps. */
const Fade: React.FC<{ f: number; at: number; out: number; S: number; k: number; rise?: number; children: React.ReactNode;
  style?: CSS }> = ({ f, at, out, S, k, rise = 10, children, style }) => {
  const p = inOf(f, at, 11 * S);
  const q = outOf(f, out, 8 * S);
  const blur = (1 - p) * 6 * k + q * 4 * k;
  return (
    <div style={{ opacity: p * (1 - q), filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined,
      transform: `translateY(${((1 - p) * rise * k).toFixed(2)}px)`, ...style }}>
      {children}
    </div>
  );
};

/** AM/PM and a zone small beside a figure, stacked to its cap height, the first in amber. */
const Tags: React.FC<{ tags: string[]; size: number; k: number; p: number; q: number; amberFirst?: boolean }> =
  ({ tags, size, k, p, q, amberFirst }) => {
    if (!tags.length) return null;
    const cap = size * ANTON_CAP;
    const tagCap = cap * (tags.length > 1 ? 0.41 : 0.42);
    const px = tagCap / SUBLINE_CAP;
    const between = tags.length > 1 ? cap - 2 * tagCap : 0;
    const blur = (1 - p) * 4 * k + q * 3 * k;
    return (
      <div style={{ display: "flex", flexDirection: "column", marginLeft: size * 0.12, paddingTop: size * ANTON_TOP - px * SUB_TOP,
        filter: `${shadow(k * 0.85)}${blur > 0.05 ? ` blur(${blur.toFixed(2)}px)` : ""}`, opacity: clamp01(p * 1.4) * (1 - q) }}>
        {tags.map((t, i) => (
          <div key={i} style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: px, lineHeight: 1, letterSpacing: "0.06em",
            color: i === 0 && amberFirst ? AMBER : WHITE, marginTop: i ? between - px * (1 - SUBLINE_CAP) : 0,
            transform: `translateY(${((1 - p) * 0.6).toFixed(4)}em)` }}>{t}</div>
        ))}
      </div>
    );
  };

/** A figure rolling up a strip to its value (the next one comes in from below). */
const Roll: React.FC<{ from: number; to: number; p: number; color: string }> = ({ from, to, p, color }) => {
  const vals: string[] = [];
  for (let v = from; v <= to; v++) vals.push(String(v));
  const w = Math.max(0.3, widthEm(String(to)) - TRACK);
  const at = (vals.length - 1) * clamp01(p);
  return (
    <span style={{ display: "inline-block", position: "relative", width: `${w.toFixed(4)}em`, height: "1em", verticalAlign: "top" }}>
      {vals.map((v, j) => {
        const y = (j - at) * STEP;
        if (Math.abs(y) > 1.3) return null;
        return (
          <span key={j} style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center", color, whiteSpace: "pre",
            transform: y ? `translateY(${y.toFixed(4)}em)` : undefined }}>{v}</span>
        );
      })}
    </span>
  );
};

/** The base every look reads: frame, rate scale (30 fps = 1), size scale, frame size, length. */
const useBase = () => {
  const f = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  return { f, S: fps / 30, k, width, height, dur: durationInFrames };
};

// ================================================================== dtx-time-stamp
/** "3:45 PM ET", "8:00 AM": the time with minutes, AM/PM and zone stacked small beside it; weekday / place under. */
export const timeStampPlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const timed = d.hour !== undefined;
  const date = hasDay(d) ? `${MON_AP[d.month as number]} ${d.day}` : "";
  return {
    main: timed ? hmFull(d) : clip(raw || "—", 14),
    tags: timed ? [d.ampm || "", zoneOf(raw)].filter(Boolean) : [],
    sub: [wdOf(d) || date, placeOf(ov, d)].filter(Boolean).slice(0, 2),
  };
};

const DtxTimeStamp: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = timeStampPlan(overlay);
  const g = glyphsOf(plan.main);
  const maxW = 0.4 * width;
  const size = fit(widthEm(plan.main) + (plan.tags.length ? 1.0 : 0), 54, 40, maxW, k);
  const c = stagger(g, S, 4, 2, 8);
  const exitAt = exitOf(c.last, dur, S);
  const bar = inOf(f, 2 * S, 9 * S);
  const barOut = outOf(f, exitAt, 8 * S);
  const barW = Math.max(2, 4 * k);
  const gap = 16 * k;
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="tl" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <div style={{ width: barW, height: size * ANTON_CAP, marginTop: size * ANTON_TOP, marginRight: gap, background: AMBER,
              borderRadius: barW / 2, transformOrigin: barOut > 0 ? "50% 100%" : "50% 0%",
              transform: `scaleY(${(bar * (1 - barOut)).toFixed(4)})`, boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
            <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
            <Tags tags={plan.tags} size={size} k={k} p={inOf(f, c.last - 4 * S, 10 * S)} q={outOf(f, exitAt, 6 * S)} amberFirst />
          </div>
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.24, marginLeft: barW + gap }}>
              <Parts parts={plan.sub} size={subSize} k={k} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-date-top
/** "SEPTEMBER 26" (the day amber), "SEPTEMBER 26–28", "MARCH 2026", "1937", "SATURDAY", "3:45 PM"; weekday / year / place under. */
export const dateTopPlan = (ov: Overlay): { main: string; key: [number, number] | null; sub: string[] } => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const year = d.year !== undefined ? String(d.year) : "";
  const place = placeOf(ov, d);
  const done = (main: string, key: [number, number] | null, sub: string[]) =>
    ({ main, key, sub: sub.filter(Boolean).slice(0, 2) });
  const rg = safeRange(raw);
  if (rg && rg.a.month !== undefined && rg.a.month === rg.b.month && rg.a.day !== undefined && rg.b.day !== undefined) {
    const days = `${rg.a.day}–${rg.b.day}`;
    const main = `${MONTHS[rg.a.month]} ${days}`;
    const y = rg.b.year ?? rg.a.year;
    return done(main, keyAtEnd(main, days), [y !== undefined ? String(y) : "", place]);
  }
  if (hasDay(d)) {
    const main = `${MONTHS[d.month as number]} ${d.day}`;
    return done(main, keyAtEnd(main, String(d.day)), [wdOf(d), year, place]);
  }
  if (d.month !== undefined) {
    const main = year ? `${MONTHS[d.month]} ${year}` : MONTHS[d.month];
    return done(main, year ? keyAtEnd(main, year) : null, [wdOf(d), place]);
  }
  if (d.year !== undefined) return done(year, [0, year.length], [wdOf(d), place]);
  if (d.weekday !== undefined) return done(wdOf(d), null, [d.hour !== undefined ? clockWords(d) : "", place]);
  if (d.hour !== undefined) {
    const main = clockWords(d);
    return done(main, [0, main.length], [place]);
  }
  return done(clip(raw || "—", 20), null, [place]);
};

const DtxDateTop: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = dateTopPlan(overlay);
  const g = glyphsOf(plan.main, plan.key);
  const maxW = 0.6 * width;
  const size = fit(widthEm(plan.main), 52, 40, maxW, k);
  const c = stagger(g, S, 3, 2, 10, true);
  const exitAt = exitOf(c.last, dur, S);
  const rule = inOf(f, c.last - 7 * S, 12 * S) * (1 - outOf(f, exitAt, 7 * S));
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="tc" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="c">
          <Feather k={k} o={featherOf(f, S, exitAt)} x={140} />
          <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
          <div style={{ width: 46 * k, height: Math.max(2, 3 * k), marginTop: size * 0.2, marginBottom: plan.sub.length ? size * 0.2 : 0,
            background: AMBER, borderRadius: 2 * k, transform: `scaleX(${rule.toFixed(4)})`,
            boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 3 * S} out={exitAt} S={S} k={k}>
              <Parts parts={plan.sub} size={subSize} k={k} track={0.2} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-date-place
/** "SATURDAY · ATLANTIC CITY": the date part, an amber dot, the place, one line; the full date small under it. */
export const datePlacePlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const bits = raw.split(/\s*[·•|]\s*|\s+[-–—]\s+/).map((s) => s.trim()).filter(Boolean);
  const isDate = (s: string) => {
    const x = safeDT(s);
    return x.weekday !== undefined || x.month !== undefined || x.year !== undefined || x.hour !== undefined;
  };
  let datePart = raw;
  let place = "";
  if (bits.length >= 2) {
    const di = Math.max(0, bits.findIndex(isDate));
    datePart = bits[di];
    place = bits.filter((_, i) => i !== di).join(", ");
  }
  const d = safeDT(datePart, ov.label, ov.value);
  if (!place) place = placeOf(ov, d);
  const wd = wdOf(d);
  const year = d.year !== undefined ? String(d.year) : "";
  const full = hasDay(d) ? `${MONTHS[d.month as number]} ${d.day}${year ? `, ${year}` : ""}` : "";
  let main: string;
  let sub: string[] = [];
  if (wd) {
    main = wd;
    sub = [full || year];
  } else if (hasDay(d)) {
    main = `${MONTHS[d.month as number]} ${d.day}`;
    sub = [year];
  } else if (d.month !== undefined) main = year ? `${MONTHS[d.month]} ${year}` : MONTHS[d.month];
  else if (d.year !== undefined) main = year;
  else if (d.hour !== undefined) main = clockWords(d);
  else main = clip(datePart || "—", 18);
  return { main, place: clip(place.replace(/[.,;:]+$/, ""), 26), sub: sub.filter(Boolean) };
};

const DtxDatePlace: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = datePlacePlan(overlay);
  const text = plan.place ? `${plan.main} • ${plan.place}` : plan.main;
  const g = glyphsOf(text);
  const maxW = 0.5 * width;
  const size = fit(widthEm(text), 44, 34, maxW, k);
  const c = stagger(g, S, 3, 2, 16);
  const exitAt = exitOf(c.last, dur, S);
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="bl" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt)} y={56} />
          <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 3 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.3 }}>
              <Parts parts={plan.sub} size={subSize} k={k} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-date-range
/** "SEP 26 → SEP 28" (+ "3 DAYS"), "1983 → 2026" (+ "43 YEARS"), "3 PM → 5 PM", "MONDAY → WEDNESDAY". */
export const rangePlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const d0 = safeDT(raw, ov.label, ov.value);
  const rg = safeRange(raw);
  let a = "";
  let b = "";
  let span = "";
  let year = "";
  if (rg) {
    const { a: x, b: y } = rg;
    if (hasDay(x) && hasDay(y)) {
      a = `${MON3[x.month as number]} ${x.day}`;
      b = `${MON3[y.month as number]} ${y.day}`;
      const ya = x.year ?? y.year ?? 2001;
      const yb = y.year ?? ya;
      let n = jdn(yb, y.month as number, y.day as number) - jdn(ya, x.month as number, x.day as number);
      if (n < 0 && y.year === undefined) n = jdn(yb + 1, y.month as number, y.day as number) - jdn(ya, x.month as number, x.day as number);
      if (n > 0 && n < 400) span = `${n + 1} DAYS`;
      const yy = y.year ?? x.year;
      year = yy !== undefined ? String(yy) : "";
    } else if (x.year !== undefined && y.year !== undefined && x.month === undefined && y.month === undefined) {
      a = String(x.year);
      b = String(y.year);
      const n = y.year - x.year;
      if (n > 0) span = `${n} YEAR${n === 1 ? "" : "S"}`;
    } else if (x.month !== undefined && y.month !== undefined) {
      const both = x.year !== undefined && y.year !== undefined && x.year !== y.year;
      a = both ? `${MON3[x.month]} ${x.year}` : MONTHS[x.month];
      b = both ? `${MON3[y.month]} ${y.year}` : MONTHS[y.month];
      if (!both && (y.year ?? x.year) !== undefined) year = String(y.year ?? x.year);
    } else if (x.hour !== undefined && y.hour !== undefined) {
      a = clockWords(x);
      b = clockWords(y);
      const mins = (minutesOf(y) - minutesOf(x) + 1440) % 1440;
      if (mins > 0 && mins % 60 === 0) span = `${mins / 60} HOUR${mins === 60 ? "" : "S"}`;
    } else if (x.weekday !== undefined && y.weekday !== undefined) {
      a = WEEKDAYS[x.weekday];
      b = WEEKDAYS[y.weekday];
      if (widthEm(a) + widthEm(b) > 9) {
        a = WD3[x.weekday];
        b = WD3[y.weekday];
      }
      const n = ((y.weekday - x.weekday + 7) % 7) + 1;
      if (n > 1) span = `${n} DAYS`;
    }
  }
  if (!a || !b) {
    const parts = raw.replace(/^FROM\s+/, "")
      .split(/\s*(?:→|->|=>|–|—)\s*|\s+-\s+|\s+(?:TO|THROUGH|THRU|UNTIL|TILL)\s+/).map((s) => s.trim()).filter(Boolean);
    if (parts.length >= 2) {
      a = clip(parts[0], 14);
      b = clip(parts[parts.length - 1], 14);
    } else {
      a = clip(raw || "—", 20);
      b = "";
    }
  }
  return { a, b, sub: [span, year, placeOf(ov, d0)].filter(Boolean).slice(0, 2) };
};

/** The range's arrow: an amber shaft drawing left to right, its head closing at the end. */
const RangeArrow: React.FC<{ size: number; p: number; q: number; k: number }> = ({ size, p, q, k }) => (
  <div style={{ width: size * 0.9, height: size, margin: `0 ${size * 0.17}px 0 ${size * 0.15}px`, filter: shadow(k),
    opacity: p > 0.02 ? 1 - q : 0 }}>
    <svg width={size * 0.9} height={size} viewBox="0 0 90 100" style={{ display: "block", overflow: "visible" }}>
      <path d={`M6 ${CAP_MID * 100} H80`} stroke={AMBER} strokeWidth={7} strokeLinecap="round" fill="none" pathLength={1}
        strokeDasharray="1 1" strokeDashoffset={(1 - clamp01(p)).toFixed(4)} />
      <path d={`M64 ${CAP_MID * 100 - 15} L82 ${CAP_MID * 100} L64 ${CAP_MID * 100 + 15}`} stroke={AMBER} strokeWidth={7}
        strokeLinecap="round" strokeLinejoin="round" fill="none" opacity={clamp01((p - 0.65) / 0.3)} />
    </svg>
  </div>
);

const DtxDateRange: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = rangePlan(overlay);
  const ga = glyphsOf(plan.a);
  const gb = glyphsOf(plan.b);
  const maxW = 0.5 * width;
  const size = fit(widthEm(plan.a) + (plan.b ? 1.22 + widthEm(plan.b) : 0), 52, 38, maxW, k);
  const ca = stagger(ga, S, 2, 2, 8);
  const arrowAt = ca.last - 7 * S;
  const cb = stagger(gb, S, arrowAt / S + 5, 2, 8);
  const last = plan.b ? cb.last : ca.last;
  const exitAt = exitOf(last, dur, S);
  const na = ga.length;
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="l3" full={Boolean(overlay.fullFrame)} push={pushOf(f, last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <Line g={ga} size={size} k={k} y={(i) => glyphY(f, ca.starts[i], S, exitAt, i)} />
            {plan.b ? (
              <>
                <RangeArrow size={size} k={k} p={easeInOut(clamp01((f - arrowAt) / (10 * S)))} q={outOf(f, exitAt + 2 * S, 6 * S)} />
                <Line g={gb} size={size} k={k} y={(i) => glyphY(f, cb.starts[i], S, exitAt, na + i)} />
              </>
            ) : null}
          </div>
          {plan.sub.length ? (
            <Fade f={f} at={last - 3 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.3 }}>
              <Parts parts={plan.sub} size={subSize} k={k} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-day-marker
const ORDINALS: Record<string, number> = { FIRST: 1, SECOND: 2, THIRD: 3, FOURTH: 4, FIFTH: 5, SIXTH: 6, SEVENTH: 7, EIGHTH: 8,
  NINTH: 9, TENTH: 10, ELEVENTH: 11, TWELFTH: 12 };
const UNIT = "(DAY|WEEK|NIGHT|HOUR|MONTH|YEAR|ROUND|STAGE|PHASE|PART)";
// A figure still in words after the unit ("DAY THREE OF THE SEARCH": spokenToDigits keeps a bare number before a
// word that is no unit), up to ninety-nine.
const CARDINALS: Record<string, number> = { ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5, SIX: 6, SEVEN: 7, EIGHT: 8, NINE: 9,
  TEN: 10, ELEVEN: 11, TWELVE: 12, THIRTEEN: 13, FOURTEEN: 14, FIFTEEN: 15, SIXTEEN: 16, SEVENTEEN: 17, EIGHTEEN: 18,
  NINETEEN: 19, TWENTY: 20, THIRTY: 30, FORTY: 40, FIFTY: 50, SIXTY: 60, SEVENTY: 70, EIGHTY: 80, NINETY: 90 };
const UNITS_W = "ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE";
const CARD_W = `((?:TWENTY|THIRTY|FORTY|FIFTY|SIXTY|SEVENTY|EIGHTY|NINETY)(?:[\\s-](?:${UNITS_W}))?|ELEVEN|TWELVE|THIRTEEN|`
  + `FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TEN|${UNITS_W})`;
const cardinalOf = (w: string) => w.split(/[\s-]+/).reduce((a, x) => a + (CARDINALS[x] ?? 0), 0);
/** "DAY 3", "day three", "the third day", "3RD DAY", "WEEK 2" -> the word and its figure; the rest of the line under it. */
export const dayPlan = (ov: Overlay): { word: string; n: number | null; sub: string; raw: string } => {
  const raw = up(ov.text);
  let word = "DAY";
  let n: number | null = null;
  let rest = raw;
  const tries: [RegExp, (m: RegExpExecArray) => void][] = [
    [new RegExp(`\\b${UNIT}\\s*(?:NO\\.?|#)?\\s*(\\d{1,4})\\b`), (m) => { word = m[1]; n = Number(m[2]); }],
    [new RegExp(`\\b(\\d{1,4})(?:ST|ND|RD|TH)\\s+${UNIT}\\b`), (m) => { n = Number(m[1]); word = m[2]; }],
    [new RegExp(`\\b(${Object.keys(ORDINALS).join("|")})\\s+${UNIT}\\b`), (m) => { n = ORDINALS[m[1]] ?? null; word = m[2]; }],
    [new RegExp(`\\b${UNIT}\\s+${CARD_W}\\b`), (m) => { word = m[1]; n = cardinalOf(m[2]) || null; }],
  ];
  for (const [rx, take] of tries) {
    const m = rx.exec(raw);
    if (m) {
      take(m);
      rest = (raw.slice(0, m.index) + " " + raw.slice(m.index + m[0].length)).replace(/^\s*(THE|ON|BY)\s+/, " ");
      break;
    }
  }
  if (n === null && typeof ov.value === "number" && Number.isFinite(ov.value) && ov.value >= 0 && ov.value < 10000) {
    n = Math.round(ov.value);
  }
  const extra = rest.replace(/\s+/g, " ").replace(/^[\s,·:-]+|[\s,·:-]+$/g, "").trim();
  const sub = clip(up(ov.label) || up(ov.subtitle) || (n !== null ? extra : ""), 30);
  return { word, n, sub, raw };
};

const DtxDayMarker: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = dayPlan(overlay);
  const n = plan.n;
  const text = n !== null ? `${plan.word} #` : clip(plan.raw || "—", 14);
  const g = glyphsOf(text, n !== null ? [text.length - 1, text.length] : null);
  const maxW = 0.36 * width;
  const em = n !== null ? widthEm(`${plan.word} ${n}`) : widthEm(text);
  const size = fit(em, 54, 40, maxW, k);
  const c = stagger(g, S, 3, 2, 8);
  const exitAt = exitOf(c.last + Math.round(5 * S), dur, S);
  const numAt = c.starts[g.length - 1];
  const from = n !== null ? Math.max(0, n - Math.min(n, 4)) : 0;
  const roll = easeOut(clamp01((f - numAt) / (14 * S)));
  const subSize = plan.sub ? subFit([plan.sub], maxW, k) : 0;
  return (
    <AbsoluteFill>
      <Anchor spot="tr" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="r">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)}
            render={(i, color) => (n !== null && i === g.length - 1 ? <Roll from={from} to={n} p={roll} color={color} /> : null)} />
          {plan.sub ? (
            <Fade f={f} at={c.last - 1 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.26 }}>
              <Parts parts={[plan.sub]} size={subSize} k={k} right />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-time-of-day
const DAY_PARTS = /\b(MORNING|AFTERNOON|EVENING|NIGHT|OVERNIGHT|TONIGHT|TODAY|TOMORROW|DAWN|DUSK|NOON|MIDNIGHT|MIDDAY|SUNRISE|SUNSET)\b/g;
/** "TONIGHT 8 PM" (the time amber), "TOMORROW MORNING" (the part of the day amber); a place or weekday under it. */
export const timeOfDayPlan = (ov: Overlay): { main: string; key: [number, number] | null; sub: string[] } => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const named = /\b(NOON|MIDNIGHT|MIDDAY)\b/.test(raw);
  const words = raw
    .replace(/\b\d{1,2}(?::[0-5]\d)?(?::[0-5]\d)?\s*[AP]\.?\s?M\b\.?/g, " ")
    .replace(/\b(?:[01]?\d|2[0-3]):[0-5]\d\b/g, " ")
    .replace(ZONE_RX, " ")
    .replace(/\s+/g, " ")
    .replace(/\s+(AT|BY|AROUND|ABOUT)$/, "")
    .trim();
  const time = d.hour !== undefined && !named ? clockWords(d) : "";
  const head = clip(words, time ? 16 : 24);
  const main = (time ? `${head} ${time}` : head).trim() || "—";
  let key: [number, number] | null = time ? keyAtEnd(main, time) : null;
  if (!key) {
    const parts = Array.from(main.matchAll(DAY_PARTS));
    const lastPart = parts.length ? parts[parts.length - 1] : null;
    key = lastPart && lastPart.index !== undefined ? [lastPart.index, lastPart.index + lastPart[0].length]
      : main.includes(" ") ? keyAtEnd(main, main.split(" ").slice(-1)[0]) : [0, main.length];
  }
  const wd = wdOf(d);
  return { main, key, sub: [wd && !main.includes(wd) ? wd : "", placeOf(ov, d)].filter(Boolean).slice(0, 2) };
};

const DtxTimeOfDay: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = timeOfDayPlan(overlay);
  const g = glyphsOf(plan.main, plan.key);
  const maxW = 0.42 * width;
  const size = fit(widthEm(plan.main), 54, 40, maxW, k);
  const c = stagger(g, S, 3, 2, 12);
  const exitAt = exitOf(c.last, dur, S);
  const warm = inOf(f, c.last - 3 * S, 10 * S);
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="l3" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <Line g={g} size={size} k={k} warm={warm} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.3 }}>
              <Parts parts={plan.sub} size={subSize} k={k} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-lead-time
const LEAD_RX = /\b(?:(IN|NEXT|WITHIN|OVER|FOR|LAST|PAST|ABOUT|ONLY|JUST)\s+)?(?:THE\s+)?(?:(NEXT|LAST|PAST)\s+)?(\d+(?:\.\d+)?)\s*-?\s*(SECONDS?|MINUTES?|HOURS?|DAYS?|NIGHTS?|WEEKS?|MONTHS?|YEARS?)\b/;
/** "IN 48 HOURS", "over the next seventy-two hours", "WITHIN 3 DAYS": the lead word, the figure, its unit, the rest. */
export const leadPlan = (ov: Overlay): { lead: string; n: number | null; unit: string; sub: string; raw: string } => {
  const raw = up(ov.text);
  const m = LEAD_RX.exec(raw);
  if (!m) {
    const v = typeof ov.value === "number" && Number.isFinite(ov.value) ? ov.value : null;
    return { lead: "", n: v, unit: v !== null ? up(ov.suffix) || "HOURS" : "", sub: clip(up(ov.label) || up(ov.subtitle), 30), raw };
  }
  const first = m[1] || "";
  const lead = m[2] || (first === "OVER" || first === "FOR" ? "" : first) || (first ? "NEXT" : "");
  const n = Number(m[3]);
  let unit = m[4];
  if (n === 1 && unit.endsWith("S")) unit = unit.slice(0, -1);
  if (n !== 1 && !unit.endsWith("S")) unit = `${unit}S`;
  const rest = raw.slice(m.index + m[0].length).replace(/^[\s,·:-]+/, "").trim();
  return { lead, n: Number.isFinite(n) ? n : null, unit, sub: clip(rest || up(ov.label) || up(ov.subtitle), 30), raw };
};

const DtxLeadTime: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = leadPlan(overlay);
  const n = plan.n;
  const whole = n !== null && Number.isInteger(n) && n >= 0 && n < 1e6;
  const fig = n === null ? "" : whole ? String(n) : String(Math.round(n * 100) / 100);
  const text = n === null ? clip(plan.raw || "—", 18) : `${fig} ${plan.unit}`.trim();
  const g = glyphsOf(text, n !== null ? [0, fig.length] : null);
  const maxW = 0.42 * width;
  const size = fit(widthEm(text), 56, 40, maxW, k);
  const lead = Math.round(5 * S);
  const c = stagger(g, S, 5, 2, 10);
  const exitAt = exitOf(c.last + Math.round(10 * S), dur, S);
  // The figure counts up from 0 between frames 6 and 24 (30 fps), in equal digit cells.
  const p = easeOut(clamp01((f - 6 * S) / (18 * S)));
  const shown = whole && n !== null ? String(Math.round(n * p)).padStart(fig.length, " ") : fig;
  const lineW = (n !== null && whole ? fig.length * (DIGIT_W + TRACK) + widthEm(` ${plan.unit}`) : widthEm(text)) * size;
  const base = inOf(f, c.last - 4 * S, 8 * S) * (1 - outOf(f, exitAt, 7 * S));
  const fill = easeInOut(clamp01((f - c.last) / (20 * S)));
  const subSize = plan.sub ? subFit([plan.sub], maxW, k) : 0;
  const leadSize = Math.max(18 * k, Math.min(SUB_PX * k, size * 0.4));
  return (
    <AbsoluteFill>
      <Anchor spot="r3" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="r">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          {plan.lead ? (
            <Fade f={f} at={Math.max(0, lead - 3 * S)} out={exitAt} S={S} k={k} style={{ marginBottom: size * 0.16 }}>
              <Parts parts={[plan.lead]} size={leadSize} k={k} track={0.24} right />
            </Fade>
          ) : null}
          <Line g={g} size={size} k={k} cells={whole} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)}
            render={(i, color) => (whole && i < fig.length ? (
              <span style={{ display: "inline-block", width: `${DIGIT_W}em`, textAlign: "center", color }}>
                {shown[i] === " " ? " " : shown[i]}
              </span>
            ) : null)} />
          <div style={{ position: "relative", width: lineW, height: Math.max(2, 3 * k), marginTop: size * 0.2, opacity: base,
            borderRadius: 2 * k, background: "rgba(255,255,255,.34)", boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.35)` }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(fill * 100).toFixed(2)}%`, background: AMBER,
              borderRadius: 2 * k }} />
          </div>
          {plan.sub ? (
            <Fade f={f} at={c.last + 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.24 }}>
              <Parts parts={[plan.sub]} size={subSize} k={k} right />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-updated-stamp
const VERB_RX = /^(LAST UPDATED|UPDATED|AS OF|CURRENT AS OF|PUBLISHED|REPORTED|ISSUED|VALID UNTIL|VALID|EFFECTIVE|RELEASED|POSTED)\b/;
/** "UPDATED 6:00 AM" (+ zone), "AS OF 9:30 PM ET", "ISSUED SEPT 26": the verb small, the time in Anton. */
export const updatedPlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const vm = VERB_RX.exec(raw);
  const verb = vm ? vm[1] : "UPDATED";
  const rest = vm ? raw.slice(vm[0].length).trim() : raw;
  const d = safeDT(rest, ov.label, ov.value);
  if (d.hour !== undefined) return { verb, main: hmFull(d), tags: [d.ampm || "", zoneOf(raw)].filter(Boolean) };
  if (hasDay(d)) return { verb, main: `${MON_AP[d.month as number]} ${d.day}`, tags: [] as string[] };
  return { verb, main: clip(rest || "—", 14), tags: [] as string[] };
};

const DtxUpdatedStamp: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = updatedPlan(overlay);
  const g = glyphsOf(plan.main);
  const verbPx = 21 * k;
  const size = fit(widthEm(plan.main), 30, 26, 0.3 * width, k);
  const c = stagger(g, S, 8, 2, 8);
  const exitAt = exitOf(c.last, dur, S);
  const dot = settle(clamp01((f - 2 * S) / (8 * S))) * (1 - outOf(f, exitAt, 6 * S));
  const tagP = inOf(f, c.last - 4 * S, 9 * S);
  const tagQ = outOf(f, exitAt, 6 * S);
  const dotPx = 9 * k;
  return (
    <AbsoluteFill>
      <Anchor spot="tl" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt) * 0.85} x={90} y={44} />
          <div style={{ display: "flex", alignItems: "center" }}>
            <div style={{ width: dotPx, height: dotPx, borderRadius: "50%", background: AMBER, marginRight: 12 * k,
              transform: `scale(${Math.max(0, dot).toFixed(4)})`, boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.5)` }} />
            <Fade f={f} at={4 * S} out={exitAt} S={S} k={k} rise={0} style={{ marginRight: 14 * k }}>
              <Parts parts={[plan.verb]} size={verbPx} k={k} color="rgba(255,255,255,.86)" track={0.2} />
            </Fade>
            <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
            {plan.tags.length ? (
              <div style={{ marginLeft: size * 0.16, opacity: clamp01(tagP * 1.4) * (1 - tagQ),
                transform: `translateY(${((1 - tagP) * 6 * k).toFixed(2)}px)`, filter: shadow(k * 0.85) }}>
                <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: verbPx, letterSpacing: "0.08em", color: AMBER }}>{plan.tags[0]}</span>
                {plan.tags[1] ? <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: verbPx, letterSpacing: "0.08em",
                  color: WHITE, marginLeft: "0.4em" }}>{plan.tags[1]}</span> : null}
              </div>
            ) : null}
          </div>
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-week-strip
const WEEK = [1, 2, 3, 4, 5, 6, 0];      // MON..SUN as WEEKDAYS indices
/** The day to mark (from a weekday, or a full date's weekday) and the date said with it. */
export const weekPlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const at = d.weekday !== undefined ? WEEK.indexOf(d.weekday) : -1;
  const title = hasDay(d) ? `${MONTHS[d.month as number]} ${d.day}` : at < 0 ? clip(raw, 20) : "";
  return { at, title };
};

const DtxWeekStrip: Look = ({ overlay }) => {
  const { f, S, k, dur } = useBase();
  const plan = weekPlan(overlay);
  const gt = glyphsOf(plan.title);
  const tSize = (40 / ANTON_CAP) * k;
  const ct = stagger(gt, S, 2, 2, 8, true);
  // Fixed frames (the built-in sound lands on them): the days from 10, 2 apart; the underline slides 26-38.
  const daysAt = WEEK.map((_, i) => Math.round((10 + 2 * i) * S));
  const slideAt = daysAt[6] + Math.round(4 * S);
  const landAt = slideAt + Math.round(12 * S);
  const exitAt = exitOf(landAt + Math.round(4 * S), dur, S);
  const px = SUB_PX * k;
  const cellW = px * 3.3;
  const slide = easeInOut(clamp01((f - slideAt) / (12 * S)));
  const uOn = inOf(f, slideAt - 3 * S, 5 * S) * (1 - outOf(f, exitAt, 6 * S));
  const target = Math.max(0, plan.at);
  const ux = cellW * target * slide;
  const warm = inOf(f, landAt - 2 * S, 8 * S);
  return (
    <AbsoluteFill>
      <Anchor spot="c3" full={Boolean(overlay.fullFrame)} push={pushOf(f, landAt, exitAt)}>
        <Block align="c">
          <Feather k={k} o={featherOf(f, S, exitAt)} x={110} y={56} />
          {plan.title ? (
            <div style={{ marginBottom: tSize * 0.32 }}>
              <Line g={gt} size={tSize} k={k} y={(i) => glyphY(f, ct.starts[i], S, exitAt, i)} />
            </div>
          ) : null}
          <div style={{ position: "relative", display: "flex" }}>
            {WEEK.map((w, i) => {
              const p = inOf(f, daysAt[i], 10 * S);
              const q = outOf(f, exitAt + Math.min(i, 6) * 0.5 * S, 7 * S);
              const hot = i === plan.at;
              const blur = (1 - p) * 5 * k + q * 3 * k;
              return (
                <div key={w} style={{ width: cellW, textAlign: "center", fontFamily: SUBLINE, fontWeight: 700, fontSize: px, lineHeight: 1,
                  letterSpacing: "0.16em", textIndent: "0.16em", whiteSpace: "nowrap",
                  color: hot && warm > 0.02 ? warmColor(warm) : "rgba(255,255,255,.74)", opacity: p * (1 - q),
                  filter: `${shadow(k * 0.85)}${blur > 0.05 ? ` blur(${blur.toFixed(2)}px)` : ""}`,
                  transform: `translateY(${((1 - p) * 8 * k).toFixed(2)}px)` }}>
                  {WD3[w]}
                </div>
              );
            })}
            {plan.at >= 0 ? (
              <div style={{ position: "absolute", left: cellW * 0.25, top: px * 1.45, width: cellW * 0.5, height: Math.max(2, 3 * k),
                borderRadius: 2 * k, background: AMBER, opacity: uOn, transform: `translateX(${ux.toFixed(2)}px)`,
                boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
            ) : null}
          </div>
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-weekday-stack
/** The weekday (small, amber) over the date (Anton); the year or place small under it. */
export const stackPlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const year = d.year !== undefined ? String(d.year) : "";
  let main: string;
  if (hasDay(d)) main = `${MONTHS[d.month as number]} ${d.day}`;
  else if (d.month !== undefined) main = MONTHS[d.month];
  else if (d.year !== undefined) main = year;
  else if (d.hour !== undefined) main = clockWords(d);
  else main = clip(raw || "—", 18);
  const wd = wdOf(d);
  return { wd: main === wd ? "" : wd, main, sub: [main === year ? "" : year, placeOf(ov, d)].filter(Boolean).slice(0, 2) };
};

const DtxWeekdayStack: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = stackPlan(overlay);
  const g = glyphsOf(plan.main);
  const maxW = 0.42 * width;
  const size = fit(widthEm(plan.main), 52, 40, maxW, k);
  const c = stagger(g, S, 6, 2, 10);
  const exitAt = exitOf(c.last, dur, S);
  const wdP = inOf(f, 2 * S, 12 * S);
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="br" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="r">
          <Feather k={k} o={featherOf(f, S, exitAt)} y={56} />
          {plan.wd ? (
            <Fade f={f} at={2 * S} out={exitAt} S={S} k={k} style={{ marginBottom: size * 0.2 }}>
              <Parts parts={[plan.wd]} size={SUB_PX * k} k={k} color={AMBER} track={0.22 + 0.1 * (1 - wdP)} right />
            </Fade>
          ) : null}
          <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.26 }}>
              <Parts parts={plan.sub} size={subSize} k={k} color="rgba(255,255,255,.88)" right />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-year-marker
/** "1937", "May 6, 1937", "the 1930s": the year (or decade) big; the day and the place small under it. */
export const yearPlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const decade = /\b(1\d{3}|20\d{2})S\b/.exec(raw)?.[0] || "";
  const any = /\b(1\d{3}|20\d{2})\b/.exec(raw)?.[1] || "";
  const main = decade || (d.year !== undefined ? String(d.year) : any) || clip(raw || "—", 10);
  const day = hasDay(d) ? `${MON_AP[d.month as number]} ${d.day}` : d.month !== undefined ? MONTHS[d.month] : "";
  return { main, sub: [day, placeOf(ov, d)].filter(Boolean).slice(0, 2) };
};

const DtxYearMarker: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = yearPlan(overlay);
  const g = glyphsOf(plan.main);
  const maxW = 0.36 * width;
  const size = fit(widthEm(plan.main), 62, 44, maxW, k);
  const c = stagger(g, S, 3, 3, 12);
  const lineAt = c.last - 7 * S;
  const lineEnd = lineAt + 16 * S;
  const exitAt = exitOf(lineEnd, dur, S);
  const draw = easeInOut(clamp01((f - lineAt) / (16 * S)));
  const lineQ = outOf(f, exitAt, 7 * S);
  const node = settle(clamp01((f - lineEnd + 2 * S) / (8 * S))) * (1 - lineQ);
  const lineW = size * 2.6;
  const th = Math.max(2, 3 * k);
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="l3" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
            <div style={{ position: "relative", width: lineW, height: size, marginLeft: size * 0.2, filter: shadow(k * 0.85) }}>
              <div style={{ position: "absolute", left: 0, top: size * CAP_MID - th / 2, width: lineW, height: th, borderRadius: th,
                background: `linear-gradient(90deg, ${AMBER}, rgba(245,180,0,.85))`, transformOrigin: "0% 50%",
                transform: `scaleX(${draw.toFixed(4)})`, opacity: 1 - lineQ }} />
              <div style={{ position: "absolute", left: lineW - 5 * k, top: size * CAP_MID - 5 * k, width: 10 * k, height: 10 * k,
                borderRadius: "50%", background: AMBER, transform: `scale(${Math.max(0, node).toFixed(4)})` }} />
            </div>
          </div>
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.26 }}>
              <Parts parts={plan.sub} size={subSize} k={k} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-relative-tag
const REL_RX = new RegExp("\\b(LAST NIGHT|LAST WEEK|LAST MONTH|LAST YEAR|LAST WEEKEND|THIS MORNING|THIS AFTERNOON|THIS EVENING|"
  + "THIS WEEK|THIS WEEKEND|EARLIER TODAY|EARLIER THIS WEEK|LATER TODAY|LATER TONIGHT|YESTERDAY (?:MORNING|AFTERNOON|EVENING)|"
  + "YESTERDAY|OVERNIGHT|TONIGHT|TODAY|TOMORROW (?:MORNING|AFTERNOON|EVENING|NIGHT)|TOMORROW|MOMENTS AGO|MINUTES AGO|"
  + "\\d+ (?:MINUTES?|HOURS?|DAYS?|WEEKS?|MONTHS?|YEARS?) (?:AGO|EARLIER|LATER|BEFORE|AFTER))\\b");
/** "LAST NIGHT", "THIS MORNING", "2 DAYS AGO" (from a longer line too); the time or place said with it small under it. */
export const relativePlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const m = REL_RX.exec(raw);
  const main = m ? m[1] : clip(raw || "—", 20);
  const d = safeDT(raw, ov.label, ov.value);
  return { main, sub: [d.hour !== undefined ? clockWords(d) : "", placeOf(ov, d)].filter(Boolean).slice(0, 2) };
};

const DtxRelativeTag: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = relativePlan(overlay);
  const g = glyphsOf(plan.main);
  const maxW = 0.4 * width;
  const size = fit(widthEm(plan.main) + 0.9, 48, 38, maxW, k);
  const c = stagger(g, S, 5, 2, 10);
  const exitAt = exitOf(c.last, dur, S);
  const dash = inOf(f, 2 * S, 9 * S) * (1 - outOf(f, exitAt, 7 * S));
  const dashW = size * 0.62;
  const gap = size * 0.24;
  const subSize = subFit(plan.sub, maxW, k);
  return (
    <AbsoluteFill>
      <Anchor spot="tl" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="l">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <div style={{ width: dashW, height: Math.max(2, 4 * k), marginTop: size * CAP_MID - Math.max(2, 4 * k) / 2, marginRight: gap,
              borderRadius: 3 * k, background: AMBER, transformOrigin: "0% 50%", transform: `scaleX(${dash.toFixed(4)})`,
              boxShadow: `0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,.45)` }} />
            <Line g={g} size={size} k={k} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
          </div>
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.26, marginLeft: dashW + gap }}>
              <Parts parts={plan.sub} size={subSize} k={k} />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

// ================================================================== dtx-clock-live
/** A clock time with minutes, AM/PM and zone small beside it; the place or weekday under it. */
export const livePlan = (ov: Overlay) => {
  const raw = up(ov.text);
  const d = safeDT(raw, ov.label, ov.value);
  const timed = d.hour !== undefined;
  return {
    main: timed ? hmFull(d) : clip(raw || "—", 12),
    tags: timed ? [d.ampm || "", zoneOf(raw)].filter(Boolean) : [],
    sub: [placeOf(ov, d) || wdOf(d)].filter(Boolean),
  };
};

const DtxClockLive: Look = ({ overlay }) => {
  const { f, S, k, width, dur } = useBase();
  const plan = livePlan(overlay);
  const g = glyphsOf(plan.main);
  const maxW = 0.34 * width;
  const size = fit(widthEm(plan.main) + (plan.tags.length ? 1.0 : 0) + 0.5, 46, 38, maxW, k);
  const c = stagger(g, S, 5, 2, 8);
  const exitAt = exitOf(c.last, dur, S);
  const dotIn = settle(clamp01((f - 2 * S) / (8 * S))) * (1 - outOf(f, exitAt, 6 * S));
  const beat = 30 * S;
  const ph = f > c.last ? ((f - c.last) % beat) / beat : -1;
  const ring = ph >= 0 && ph < 0.8 ? ph / 0.8 : -1;
  const colon = plan.main.indexOf(":");
  const dim = (i: number) => (i === colon && ph >= 0.55 ? 0.42 : 1);
  const dotPx = size * 0.2;
  const subSize = plan.sub.length ? subFit(plan.sub, maxW, k) : 0;
  return (
    <AbsoluteFill>
      <Anchor spot="tr" full={Boolean(overlay.fullFrame)} push={pushOf(f, c.last, exitAt)}>
        <Block align="r">
          <Feather k={k} o={featherOf(f, S, exitAt)} />
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <div style={{ position: "relative", width: dotPx, height: dotPx, marginTop: size * CAP_MID - dotPx / 2, marginRight: size * 0.24,
              transform: `scale(${Math.max(0, dotIn).toFixed(4)})` }}>
              {ring >= 0 ? (
                <div style={{ position: "absolute", left: 0, top: 0, width: dotPx, height: dotPx, borderRadius: "50%", background: LIVE,
                  opacity: 0.55 * (1 - ring), transform: `scale(${(1 + 1.6 * easeOut(ring)).toFixed(4)})` }} />
              ) : null}
              <div style={{ position: "absolute", left: 0, top: 0, width: dotPx, height: dotPx, borderRadius: "50%", background: LIVE,
                boxShadow: `0 0 ${(6 * k).toFixed(1)}px rgba(255,59,48,.55), 0 ${(1 * k).toFixed(1)}px ${(2 * k).toFixed(1)}px rgba(0,0,0,.5)` }} />
            </div>
            <Line g={g} size={size} k={k} dim={dim} y={(i) => glyphY(f, c.starts[i], S, exitAt, i)} />
            <Tags tags={plan.tags} size={size} k={k} p={inOf(f, c.last - 4 * S, 10 * S)} q={outOf(f, exitAt, 6 * S)} />
          </div>
          {plan.sub.length ? (
            <Fade f={f} at={c.last - 2 * S} out={exitAt} S={S} k={k} style={{ marginTop: size * 0.26 }}>
              <Parts parts={plan.sub} size={subSize} k={k} right />
            </Fade>
          ) : null}
        </Block>
      </Anchor>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "dtx-time-stamp": DtxTimeStamp,
  "dtx-date-top": DtxDateTop,
  "dtx-date-place": DtxDatePlace,
  "dtx-date-range": DtxDateRange,
  "dtx-day-marker": DtxDayMarker,
  "dtx-time-of-day": DtxTimeOfDay,
  "dtx-lead-time": DtxLeadTime,
  "dtx-updated-stamp": DtxUpdatedStamp,
  "dtx-week-strip": DtxWeekStrip,
  "dtx-weekday-stack": DtxWeekdayStack,
  "dtx-year-marker": DtxYearMarker,
  "dtx-relative-tag": DtxRelativeTag,
  "dtx-clock-live": DtxClockLive,
};
