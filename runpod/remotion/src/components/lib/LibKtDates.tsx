import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay } from "../../types";
import { GROTESK, GROTESK_CAP, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoOut, motionBlur, prog } from "../motion/ease";
import { guard, rgba, type Look } from "./proKit";
import { num, str } from "./proFormat";
import { Glint, WHITE, blockAt, fitLines, isRight, softShadow, widthOf, zoneFor, type DirSpec, type Zone } from "./typeKit";
import { useLook } from "./LibKinetic";
import scale from "./typeScale.json";

/**
 * THE DATE FAMILY (2026-10-06): every date, year and time the narration says,
 * shown clearly - the owner on his Obama video: "When dates are mentioned it
 * barely shows them. We need a PERFECT SIZE - not big, not small. The white one
 * with the line is not great. Check out better date looks ... perfect ones,
 * not full-screen ones, perfectly matched."
 *
 *   kt-date        DATE STAMP   top left: a glass chip, the kicker over the date as said, its letters
 *                               rising and its figures rolling into place, under it a thin bar of the
 *                               year that fills to the day (the dot is the date) with the year at its end
 *   kt-date-card   CALENDAR     top left: a desk-calendar page (the month on its band, the day big) that
 *                               riffles two pages over its binding and lands on the day, the kicker and the
 *                               year rolling in on a glass tab beside it
 *   kt-date-line   TIMELINE     top left: a glass card, the year counting while a dot slides along a short
 *                               timeline from the year the story was in (or in from the left) to the year
 *                               said; a second year said a beat later slides it on
 *   kt-date-badge  LOWER THIRD  low left: a glass lower third with an accent edge, the kicker ("THE
 *                               NIGHT OF", a weekday, the place) over "Nov 24, 1982"
 *   kt-year        YEAR COUNTER top left: the year in glass slots, each digit rolling like an odometer from
 *                               the year the story was in (or a few steps below), the kicker on a glass tab
 *   kt-time        TIME COUNTER top left: a clock time in the same slots ("3:00" and its AM / PM)
 *   kt-time-clock  CLOCK        top left: a clock face whose hands sweep round to the time, the time set
 *                               beside it on a glass tab
 *
 * One size rule (typeScale.json "dateLine" and friends): the main date line is
 * a headline - capitals 6 % of the frame height (a font of 8.2 %, 89 px at
 * 1080p), its kicker 2.5 %, the block 17-30 % of the frame width: readable on
 * a phone, never a takeover. One accent (the brand kit's, else the direction's
 * gold / red / amber); white bold grotesk, tabular figures; frosted glass
 * instead of outlines or yellow fills. Each kind keeps one home (the owner's
 * same-place rule), mirrored to the calm side by the planner (src/lookplace.py)
 * or off a face / a logo / lettering (overlay.avoid). Entries of 12-20 frames
 * on expo / back curves, a gentle idle, the exit mirrored in the last 12.
 * Nothing is drawn that the narration did not say (no computed weekday).
 */

// ------------------------------------------------------------------ the date as said
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_RX = /\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?(?:\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\b)?/i;
const YEAR_RX = /\b(1[0-9]\d\d|20\d\d)\b/;

export interface DateParts {
  month: number | null;
  day: number | null;
  year: number | null;
}

const yearOf = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && n >= 1000 && n <= 2999 && Number.isInteger(n) ? n : null;
};

/** The month, day and year an overlay says: text "August 21" (or "AUGUST 21, 2026"), subtitle "2026", value 2026. */
export const dateParts = (ov: Overlay): DateParts => {
  const text = str(ov.text);
  const m = MONTH_RX.exec(text);
  let month: number | null = null;
  let day: number | null = null;
  if (m) {
    const key = m[1].slice(0, 3).toLowerCase();
    month = MON3.findIndex((x) => x.toLowerCase() === key);
    if (month < 0) month = null;
    const d = m[2] ? Number(m[2]) : NaN;
    day = Number.isFinite(d) && d >= 1 && d <= 31 ? d : null;
  }
  const sub = str(ov.subtitle);
  const inText = YEAR_RX.exec(text);
  const year = (/^\d{4}$/.test(sub) ? yearOf(sub) : null) ?? yearOf(ov.value) ?? (inText ? yearOf(inText[1]) : null);
  return { month, day: month === null ? null : day, year };
};

const leap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
/** Where the date falls in its year, 0..1 (a month alone: its middle). */
export const yearShare = (d: DateParts): number | null => {
  if (d.month === null) return null;
  const feb = d.year !== null && leap(d.year) ? 29 : 28;
  const days = MONTH_DAYS.map((n, i) => (i === 1 ? feb : n));
  const before = days.slice(0, d.month).reduce((a, b) => a + b, 0);
  const total = days.reduce((a, b) => a + b, 0);
  const inMonth = d.day !== null ? Math.min(d.day, days[d.month]) - 0.5 : days[d.month] / 2;
  return clamp01((before + inMonth) / total);
};

/**
 * The years of a timeline / a counter in the order said - items [{label, value, at?}], else total (from) + value.
 * `at`: the second (from the look's start) each later year is said - the look moves on to it then (NaN: at once);
 * `labels`: what is written under each point ("Aug 4, 1961" for a date said, else the year).
 */
const yearsOf = (ov: Overlay): { years: number[]; at: number[]; labels: string[] } => {
  const items = Array.isArray(ov.items) ? ov.items : [];
  const years: number[] = [];
  const at: number[] = [];
  const labels: string[] = [];
  for (const it of items) {
    const y = yearOf(it?.value) ?? yearOf(it?.label);
    if (y === null) continue;
    years.push(y);
    const a = num((it as { at?: unknown })?.at);
    at.push(a !== null && a >= 0 ? a : NaN);
    const lab = str(it?.label);
    labels.push(lab && lab.length <= 16 ? lab.toUpperCase() : String(y));
  }
  if (!years.length) {
    const y = yearOf(ov.value) ?? dateParts(ov).year;
    const from = yearOf(ov.total);
    if (from !== null && y !== null && from !== y) {
      years.push(from, y);
      at.push(NaN, NaN);
      labels.push(String(from), String(y));
    } else if (y !== null) {
      years.push(y);
      at.push(NaN);
      labels.push(String(y));
    }
  }
  return { years: years.slice(-3), at: at.slice(-3), labels: labels.slice(-3) };
};
/** A year said a beat later moves the look on when it is said (an item with its own second). */
const phased = (at: number[]) => at.length > 1 && Number.isFinite(at[at.length - 1]);

// ------------------------------------------------------------------ sizes
/** The size unit: the frame height, or the width's 16:9 height on a tall frame (a short keeps the proportions). */
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
type ScaleKey = "dateLine" | "dateKicker" | "dateSmall" | "dateDay" | "counter";
const capShare = (key: ScaleKey) => (scale[key] as { share: number }).share;
const leastShare = (key: ScaleKey) => ((scale[key] as { least?: number }).least ?? capShare(key));
/** Font px whose capitals stand the role's share of the unit (fontScale applied). */
const fontFor = (key: ScaleKey, U: number, ks: number, cap = GROTESK_CAP) => (capShare(key) * U * ks) / cap;
const BLOCK = scale.dateBlock;
const maxBlockW = (W: number, H: number) => (W >= H ? BLOCK.maxW : 0.64) * W;
const minBlockW = (W: number, H: number) => (W >= H ? BLOCK.minW : 0.4) * W;

/** The width a RiseLine draws: each character on its own (no kerning pairs), its own width, tracking after each. */
export const riseWidth = (text: string, font: string, size: number, weight: number, tracking = -0.012) =>
  Array.from(text).reduce((a, ch) => a + widthOf(ch, font, size, weight) + tracking * size, 0);

// ------------------------------------------------------------------ surfaces
const GLASS_TOP = "rgba(26,29,36,0.74)";
const GLASS_BOTTOM = "rgba(10,12,16,0.82)";
export const HAIRLINE = "rgba(255,255,255,0.12)";
export const SOFT = "rgba(250,250,247,0.86)";
export const DIM = "rgba(250,250,247,0.62)";

/**
 * Frosted glass: the footage under it blurred and darkened, a hairline edge, a
 * soft drop shadow - never an outline or a yellow fill. It opens from its
 * anchored side (p 0..1) and closes back into it on the exit.
 */
export const Glass: React.FC<{ x: number; y: number; w: number; h: number; k: number; p: number; out: number;
  right?: boolean; radius?: number; edge?: string; edgeP?: number; children?: React.ReactNode }> =
  ({ x, y, w, h, k, p, out, right = false, radius = 16, edge, edgeP = 1, children }) => {
    const open = clamp01(p) * (1 - cubicIn(clamp01(out * 1.25 - 0.2)));
    const hide = (1 - open) * 100;
    const blur = (16 * k).toFixed(1);
    const rr = radius * k;
    return (
      <>
        {/* the shadow under it (outside the clip) */}
        <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: rr, opacity: clamp01(p) * (1 - out) * 0.9,
          boxShadow: `0 ${(18 * k).toFixed(1)}px ${(46 * k).toFixed(1)}px rgba(0,0,0,0.42), 0 ${(3 * k).toFixed(1)}px ${(10 * k).toFixed(1)}px rgba(0,0,0,0.25)`,
          clipPath: `inset(-${(80 * k).toFixed(0)}px ${right ? -80 * k : (hide / 100) * w - 80 * k}px -${(80 * k).toFixed(0)}px ${right ? (hide / 100) * w - 80 * k : -80 * k}px)` }} />
        <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: rr, overflow: "hidden",
          clipPath: `inset(0 ${right ? 0 : hide.toFixed(2)}% 0 ${right ? hide.toFixed(2) : 0}% round ${rr.toFixed(1)}px)`,
          opacity: clamp01(p * 2.2) * (1 - out * 0.5) }}>
          <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${GLASS_TOP} 0%, ${GLASS_BOTTOM} 100%)`,
            backdropFilter: `blur(${blur}px) saturate(1.12)`, WebkitBackdropFilter: `blur(${blur}px) saturate(1.12)`,
            boxShadow: `inset 0 ${(1 * k).toFixed(1)}px 0 rgba(255,255,255,0.08), inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${HAIRLINE}`,
            borderRadius: rr }} />
          {edge ? (
            <div style={{ position: "absolute", top: 0, bottom: 0, [right ? "right" : "left"]: 0, width: 6 * k,
              background: `linear-gradient(180deg, ${rgba(edge, 1)} 0%, ${rgba(edge, 0.82)} 100%)`,
              transformOrigin: "top", transform: `scaleY(${clamp01(edgeP).toFixed(4)})`,
              boxShadow: `0 0 ${(14 * k).toFixed(1)}px ${rgba(edge, 0.55)}` }} />
          ) : null}
          {children}
        </div>
      </>
    );
  };

/** Small tracked capitals (a kicker, a month on a band, a year at a bar's end), tracking in from wide. */
export const Caps: React.FC<{ text: string; size: number; color: string; at: number; out: number; align?: "left" | "right" | "center";
  tracking?: number; weight?: number; k: number; shadow?: boolean }> =
  ({ text, size, color, at, out, align = "left", tracking = 0.2, weight = 700, k, shadow = true }) => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    const S = fps / 30;
    const e = prog(f, at, 18, S, expoOut);
    const o = prog(f, at, 10, S, cubicOut) * (1 - clamp01(out * 1.6));
    return (
      <div style={{ fontFamily: SUBLINE, fontWeight: weight, fontSize: size, lineHeight: 1, color, whiteSpace: "nowrap",
        textTransform: "uppercase", letterSpacing: `${(tracking + 0.3 * (1 - e) + 0.12 * out).toFixed(4)}em`, opacity: o,
        filter: o < 0.999 ? `blur(${((1 - e) * 3 + out * 3).toFixed(2)}px)` : undefined, textAlign: align,
        textShadow: shadow ? softShadow(k, 0.45) : undefined }}>{text}</div>
    );
  };
export const capsWidth = (text: string, size: number, tracking = 0.2, weight = 700) => widthOf(text.toUpperCase(), SUBLINE, size, weight, tracking);

// ------------------------------------------------------------------ rolling figures
/**
 * One digit wheel: it turns `steps` places (an odometer: the ones wheel of 1982 -> 2008 turns 26, the
 * thousands one) and lands on `to`, with a touch of motion blur while it runs and a small settle.
 */
const Wheel: React.FC<{ to: number; steps: number; at: number; len: number; size: number; h: number; font: string;
  weight: number; color: string; k: number; out: number; fade?: boolean; tabular?: boolean }> =
  ({ to, steps, at, len, size, h, font, weight, color, k, out, fade = true, tabular = true }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const S = fps / 30;
  const ease = (u: number) => 1 - (1 - u) ** 4;
  const e = prog(f, at, len, S, ease);
  const e1 = prog(f + S, at, len, S, ease);
  const n = Math.abs(steps);
  const dirn = steps >= 0 ? 1 : -1;
  // the wheel's position in cells from its start (0) to its landing (n), never past it
  const pos = Math.min(n, n * e);
  const blur = motionBlur((e1 - e) * n * h, k, 5);
  const base = Math.min(n, Math.floor(pos));
  const frac = pos - base;
  // a small settle as it lands: the wheel springs a few % past its stop and back
  const land = at + len;
  const u = clamp01((f / S - land + 2) / 9);
  const settle = f / S > land - 2 ? Math.sin(u * Math.PI) * (1 - u) * 0.07 * h * dirn : 0;
  const digitAt = (c: number) => (((to - dirn * (n - c)) % 10) + 10) % 10;
  const cell = (c: number, off: number) => (
    <div key={c} style={{ position: "absolute", left: 0, right: 0, height: h, top: off, display: "flex", alignItems: "center",
      justifyContent: "center" }}>{digitAt(c)}</div>
  );
  return (
    <div style={{ position: "relative", width: "100%", height: h, overflow: "hidden", fontFamily: font, fontWeight: weight,
      fontSize: size, lineHeight: 1, color, fontVariantNumeric: tabular ? "tabular-nums" : "normal",
      fontFeatureSettings: tabular ? '"tnum" 1' : '"tnum" 0', filter: blur ? `blur(${(blur * 0.7).toFixed(2)}px)` : undefined,
      opacity: (fade ? prog(f, at - 3, 8, S, cubicOut) : 1) * (1 - clamp01(out * 1.4)),
      transform: `translateY(${(out * 0.18 * h - settle).toFixed(2)}px)` }}>
      {/* rolling up (forward) the next digit comes from below; backward, from above */}
      {cell(base, -frac * h * dirn)}
      {base < n ? cell(base + 1, (1 - frac) * h * dirn) : null}
    </div>
  );
};

/** How far each wheel of a counter turns from `from` to `to` (true odometer steps, the fast ones capped). */
export const wheelSteps = (from: string, to: string): number[] => {
  const a = Number(from), b = Number(to);
  const n = to.length;
  if (!Number.isFinite(a) || !Number.isFinite(b) || from.length !== n) return Array.from(to, (_c, i) => 3 + i);
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    const p = 10 ** (n - 1 - i);
    let s = Math.floor(b / p) - Math.floor(a / p);
    if (Math.abs(s) > 30) s = Math.sign(s) * (20 + (Math.abs(s) % 10));
    out.push(s);
  }
  return out;
};

/** A line of type whose letters rise out of a mask one after another, its figures rolling in on wheels. */
export const RiseLine: React.FC<{ text: string; size: number; font: string; weight: number; color?: string; at: number; out: number;
  tracking?: number; k: number; gap?: number; colorOf?: (i: number) => string | undefined; roll?: boolean }> =
  ({ text, size, font, weight, color = WHITE, at, out, tracking = -0.012, k, gap = 1.1, colorOf, roll = true }) => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    const S = fps / 30;
    const chars = Array.from(text);
    const n = chars.length;
    const h = size * 1.2;
    let digitRun = 0;
    return (
      <div style={{ display: "flex", alignItems: "flex-end", whiteSpace: "pre", height: h, fontFamily: font, fontWeight: weight,
        fontSize: size, lineHeight: `${h}px`, letterSpacing: `${tracking}em`, color, fontVariantNumeric: "tabular-nums",
        fontFeatureSettings: '"tnum" 1', textShadow: softShadow(k, 0.5) }}>
        {chars.map((ch, i) => {
          const c = colorOf?.(i) ?? color;
          const t0 = at + i * gap;
          const x = clamp01(out * 1.3 - ((n - 1 - i) / Math.max(1, n)) * 0.3);
          if (roll && /\d/.test(ch)) {
            // a figure in a line of words keeps its own width ("21", never "2 1"): its wheel rolls in that slot
            digitRun += 1;
            const w = widthOf(ch, font, size, weight) + tracking * size;
            return (
              <div key={i} style={{ position: "relative", width: w, height: h, color: c }}>
                <Wheel to={Number(ch)} steps={2 + digitRun} at={t0} len={16 + digitRun * 2} size={size} h={h} font={font}
                  weight={weight} color={c} k={k} out={x} tabular={false} />
              </div>
            );
          }
          digitRun = 0;
          const e = prog(f, t0, 15, S, expoOut);
          const e1 = prog(f + S, t0, 15, S, expoOut);
          const y = (1 - e) * 100 + cubicIn(x) * 100;
          const v = (e1 - e) * h;
          return (
            <div key={i} style={{ position: "relative", height: h, overflow: "hidden", color: c }}>
              <span style={{ display: "inline-block", transform: `translateY(${y.toFixed(2)}%)`,
                filter: motionBlur(v, k) ? `blur(${(motionBlur(v, k) * 0.5).toFixed(2)}px)` : undefined }}>{ch}</span>
            </div>
          );
        })}
      </div>
    );
  };

// ------------------------------------------------------------------ shared frame
const useDates = (overlay: Overlay, accent: string) => {
  const L = useLook(overlay, accent);
  const U = unitOf(L.W, L.H);
  return { ...L, U };
};

const caseOf = (dir: DirSpec, s: string) => (dir.upper ? s.toUpperCase() : s);
const monthWords = (d: DateParts, short = false) =>
  d.month === null ? "" : `${short ? MON3[d.month] : MONTHS[d.month]}${d.day !== null ? ` ${d.day}` : ""}`;

/** The kicker a date look sets: the label as planned ("FRIDAY", "THE NIGHT OF", "NAIROBI"), short. */
const kickerOf = (ov: Overlay) => {
  const k = str(ov.label).toUpperCase();
  return k.length <= 30 ? k : "";
};
const kickerColor = (dir: DirSpec, hot: string) => (dir.id === "doc" ? SOFT : hot);

// ================================================================== kt-date (the date stamp)
const Stamp: Look = (props) => {
  const { overlay, accent } = props;
  const { f, S, k, W, H, U, dir, hot, out, ks } = useDates(overlay, accent);
  const d = dateParts(overlay);
  // a year said alone (an older plan's year-only date) is the year counter
  if (d.month === null) return d.year !== null ? <YearCounter {...props} /> : null;
  const main = caseOf(dir, monthWords(d));
  const share = yearShare(d);
  const year = d.year !== null ? String(d.year) : "";
  const kicker = kickerOf(overlay);
  const kSize = fontFor("dateKicker", U, ks);
  const sSize = fontFor("dateSmall", U, ks);
  const size0 = fontFor("dateLine", U, ks, dir.cap);
  const padX = 0.34 * size0, padT = 0.26 * size0, padB = 0.3 * size0;
  const least = (leastShare("dateLine") * U * ks) / dir.cap;
  let size = size0;
  while (size > least && riseWidth(main, dir.font, size, 800) > maxBlockW(W, H) - padX * 2) size *= 0.97;
  const lineW = riseWidth(main, dir.font, size, 800);
  const lineH = size * 1.2;
  const head = kicker ? kSize + 0.2 * size : 0;
  const barRow = Math.max(sSize, 12 * k);
  const yW = year ? capsWidth(year, sSize, 0.06, 800) : 0;
  const innerW = Math.max(lineW, minBlockW(W, H) - padX * 2, yW + 150 * k, kicker ? capsWidth(kicker, kSize) : 0);
  const w = innerW + padX * 2;
  const h = padT + head + lineH + 0.28 * size + barRow + padB;
  const zone = zoneFor(overlay, "upper-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  const open = prog(f, 0, 14, S, expoOut);
  // the bar: its track draws, then the fill and the dot run to the day
  const track = prog(f, 12, 14, S, expoOut) * (1 - clamp01(out * 1.5));
  const run = prog(f, 16, 24, S, cubicInOut);
  const land = 16 + 24;
  const pulse = clamp01((f / S - land) / 6) * (1 - clamp01((f / S - land - 6) / 20));
  const barW = innerW - (yW ? yW + 20 * k : 0);
  const thick = Math.max(2, 4 * k);
  const dotR = 7.5 * k;
  const along = (share ?? 0) * barW * run;
  return (
    <AbsoluteFill>
      <Glass x={r.x} y={r.y} w={w} h={h} k={k} p={open} out={out} right={anchor}>
        <div style={{ position: "absolute", left: padX, right: padX, top: padT, display: "flex", flexDirection: "column",
          alignItems: right ? "flex-end" : "flex-start" }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 0.2 * size }}>
              <Caps text={kicker} size={kSize} color={kickerColor(dir, hot)} at={4} out={out} k={k} align={right ? "right" : "left"} />
            </div>
          ) : null}
          <RiseLine text={main} size={size} font={dir.font} weight={800} at={6} out={out} k={k} />
        </div>
        <div style={{ position: "absolute", left: padX, right: padX, top: padT + head + lineH + 0.28 * size, height: barRow,
          display: "flex", alignItems: "center", gap: 20 * k, flexDirection: right ? "row-reverse" : "row" }}>
          <div style={{ position: "relative", width: barW, height: barRow, flex: "none" }}>
            {/* the year: a track with a tick at every month's start, the fill and the dot to the day */}
            <div style={{ position: "absolute", left: 0, right: 0, top: barRow / 2 - thick / 2, height: thick, borderRadius: thick,
              background: "rgba(255,255,255,0.22)", transformOrigin: right ? "right" : "left", transform: `scaleX(${track.toFixed(4)})` }} />
            {Array.from({ length: 13 }, (_, i) => {
              const x = (i / 12) * barW;
              const on = prog(f, 14 + i * 0.8, 8, S, cubicOut) * (1 - clamp01(out * 1.5));
              const tall = i % 3 === 0 ? 0.95 : 0.55;
              return <div key={i} style={{ position: "absolute", [right ? "right" : "left"]: x - 0.75 * k, width: Math.max(1, 1.5 * k),
                top: barRow / 2 - (barRow * tall) / 2, height: barRow * tall, borderRadius: k,
                background: i % 3 === 0 ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.3)", opacity: on }} />;
            })}
            <div style={{ position: "absolute", [right ? "right" : "left"]: 0, top: barRow / 2 - thick / 2, height: thick,
              width: Math.max(0, along) * (1 - clamp01(out * 1.5)), borderRadius: thick,
              background: `linear-gradient(90deg, ${rgba(hot, 0.7)}, ${hot})`, boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${rgba(hot, 0.5)}`,
              overflow: "hidden" }}>
              <Glint p={(f / S - land) / 18} />
            </div>
            <div style={{ position: "absolute", [right ? "right" : "left"]: along - dotR, top: barRow / 2 - dotR,
              width: dotR * 2, height: dotR * 2, borderRadius: "50%", background: WHITE,
              boxShadow: `0 0 0 ${(3 * k).toFixed(1)}px ${rgba(hot, 0.95)}, 0 0 ${((14 + 16 * pulse) * k).toFixed(1)}px ${rgba(hot, 0.7 + 0.3 * pulse)}`,
              opacity: prog(f, 15, 6, S, cubicOut) * (1 - clamp01(out * 1.6)),
              transform: `scale(${(1 + 0.35 * pulse).toFixed(4)})` }} />
          </div>
          {year ? (
            <div style={{ width: yW, flex: "none" }}>
              <Caps text={year} size={sSize} color={WHITE} at={18} out={out} k={k} tracking={0.06} weight={800} align={right ? "left" : "right"} />
            </div>
          ) : null}
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-date-card (the calendar)
/** One calendar page body: the day big in charcoal on warm paper. */
const PageBody: React.FC<{ day: number | string; w: number; h: number; size: number; shade?: number }> =
  ({ day, w, h, size, shade = 0 }) => (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, background: "linear-gradient(180deg, #FBFAF7 0%, #E9E5DD 100%)",
      display: "flex", alignItems: "center", justifyContent: "center", fontFamily: GROTESK, fontWeight: 800, fontSize: size,
      lineHeight: 1, color: "#16181D", letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums",
      fontFeatureSettings: '"tnum" 1', paddingTop: size * 0.04, boxSizing: "border-box" }}>
      {day}
      {shade > 0 ? <div style={{ position: "absolute", inset: 0, background: `rgba(10,12,16,${shade.toFixed(3)})` }} /> : null}
    </div>
  );

const Card: Look = (props) => {
  const { overlay, accent } = props;
  const { f, S, k, W, H, U, dir, hot, out, ks } = useDates(overlay, accent);
  const d = dateParts(overlay);
  if (d.month === null || d.day === null) return <Stamp {...props} />;
  const kicker = kickerOf(overlay);
  const year = d.year !== null ? String(d.year) : "";
  const dSize = fontFor("dateDay", U, ks);
  const yearSize = fontFor("dateLine", U, ks, dir.cap);
  const kSize = fontFor("dateKicker", U, ks);
  const cw = dSize * 1.5, ch = dSize * 1.62;
  const band = ch * 0.27;
  const body = ch - band;
  // the glass tab the kicker and the year sit on: it runs out from behind the card
  const tabPadL = 0.36 * yearSize, tabPadR = 0.4 * yearSize;
  const yW = year ? riseWidth(year, dir.font, yearSize, 800) : 0;
  const kW = kicker ? capsWidth(kicker, kSize) : 0;
  // without a year the month is said in full on the tab ("August"), so the card never stands alone
  const word = year ? "" : MONTHS[d.month];
  const wW = word ? riseWidth(caseOf(dir, word), dir.font, yearSize, 800) : 0;
  const colW = Math.max(yW, kW, wW);
  const tabH = Math.min(ch * 0.86, (kicker ? kSize + 0.2 * yearSize : 0) + yearSize * 1.2 + 0.5 * yearSize);
  const w = cw + tabPadL + colW + tabPadR;
  const zone = zoneFor(overlay, "upper-left", w, ch, W, H) as Zone;
  const r = blockAt(zone, w, ch, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  const cardX = right ? r.x + r.w - cw : r.x;
  const tabX = right ? r.x : cardX + cw * 0.55;
  const tabW = w - cw * 0.55;
  const tabY = r.y + (ch - tabH) / 2 + band * 0.22;
  // the card drops into place, two pages riffle over the binding, the day lands; the tab slides out after
  const enter = prog(f, 0, 14, S, (u) => backOut(u, 1.2));
  const o = prog(f, 0, 8, S, cubicOut) * (1 - clamp01(out * 1.4));
  // two blank pages riffle away over the binding (never a day the narration did not say), the day under them
  const pages = [{ n: 1, p: prog(f, 8, 8, S, cubicIn) }, { n: 2, p: prog(f, 4, 8, S, cubicIn) }];
  const land = 8 + 8;
  const settleS = 1 + 0.03 * Math.sin(clamp01((f / S - land) / 10) * Math.PI);
  const tabOpen = prog(f, 8, 16, S, expoOut);
  const ringW = 8 * k, ringH = 20 * k;
  const colLeft = right ? r.x + tabPadR : cardX + cw + tabPadL;
  return (
    <AbsoluteFill>
      <Glass x={tabX} y={tabY} w={tabW} h={tabH} k={k} p={tabOpen} out={out} right={right} radius={14}>
        <div style={{ position: "absolute", left: colLeft - tabX, top: 0, width: colW, height: tabH, display: "flex",
          flexDirection: "column", justifyContent: "center", alignItems: right ? "flex-end" : "flex-start" }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 0.2 * yearSize }}>
              <Caps text={kicker} size={kSize} color={kickerColor(dir, hot)} at={12} out={out} k={k} align={right ? "right" : "left"} />
            </div>
          ) : null}
          <RiseLine text={year || caseOf(dir, word)} size={yearSize} font={dir.font} weight={800} at={14} out={out} k={k} />
        </div>
      </Glass>
      <div style={{ position: "absolute", left: cardX, top: r.y, width: cw, height: ch, opacity: o,
        transform: `translateY(${((1 - enter) * -18 * k - out * 10 * k).toFixed(2)}px) scale(${((0.94 + 0.06 * enter) * settleS).toFixed(4)})`,
        transformOrigin: "50% 0%" }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 14 * k, boxShadow: `0 ${(20 * k).toFixed(1)}px ${(44 * k).toFixed(1)}px rgba(0,0,0,0.45)` }} />
        <div style={{ position: "absolute", inset: 0, borderRadius: 14 * k, overflow: "hidden" }}>
          {/* the band: the month in white capitals on charcoal */}
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: band, background: "linear-gradient(180deg, #1F232A 0%, #14171C 100%)",
            display: "flex", alignItems: "center", justifyContent: "center", paddingTop: band * 0.1, boxSizing: "border-box" }}>
            <div style={{ fontFamily: SUBLINE, fontWeight: 800, fontSize: band * 0.42, lineHeight: 1, letterSpacing: "0.22em",
              marginLeft: "0.22em", color: WHITE }}>{MON3[d.month].toUpperCase()}</div>
          </div>
          {/* the day under the pages that riffle away */}
          <div style={{ position: "absolute", left: 0, top: band, width: cw, height: body, perspective: 900 * k }}>
            <PageBody day={d.day} w={cw} h={body} size={dSize} />
            {pages.map(({ n, p }) => (p >= 1 ? null : (
              <div key={n} style={{ position: "absolute", inset: 0, transformOrigin: "50% 0%", backfaceVisibility: "hidden",
                transform: `rotateX(${(p * 100).toFixed(2)}deg)` }}>
                <PageBody day="" w={cw} h={body} size={dSize} shade={0.12 + 0.35 * p} />
              </div>
            )))}
            {/* the crease under the binding */}
            <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 10 * k,
              background: "linear-gradient(180deg, rgba(0,0,0,0.22), rgba(0,0,0,0))" }} />
          </div>
        </div>
        {/* the binding: two rings in the accent */}
        {[0.3, 0.7].map((x) => (
          <div key={x} style={{ position: "absolute", left: cw * x - ringW / 2, top: -ringH * 0.45, width: ringW, height: ringH,
            borderRadius: ringW, background: `linear-gradient(180deg, ${hot}, ${rgba(hot, 0.8)})`,
            boxShadow: `0 ${(2 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,0.4)` }} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-date-line (the timeline marker)
const niceStep = (span: number) => (span <= 14 ? 1 : span <= 40 ? 5 : span <= 140 ? 10 : span <= 350 ? 25 : 50);

const TimelineLook: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, U, dir, hot, out, ks } = useDates(overlay, accent);
  const { years, at, labels } = yearsOf(overlay);
  if (!years.length) return null;
  const d = dateParts(overlay);
  const target = years[years.length - 1];
  const first = years.length > 1 ? years[0] : null;
  const lo0 = Math.min(...years), hi0 = Math.max(...years);
  const span = Math.max(1, hi0 - lo0);
  const pad = first === null ? 0 : Math.max(1, Math.round(span * 0.14));
  const lo = first === null ? target - 10 : lo0 - pad;
  const hi = first === null ? target + 2 : hi0 + pad;
  const step = niceStep(hi - lo);
  const yearSize = fontFor("dateLine", U, ks, dir.cap);
  const kSize = fontFor("dateKicker", U, ks);
  const sSize = fontFor("dateSmall", U, ks) * 0.86;
  const label = (d.month !== null ? monthWords(d).toUpperCase() : "") || kickerOf(overlay);
  const padX = 0.36 * yearSize, padT = 0.28 * yearSize, padB = 0.3 * yearSize;
  const cardW = Math.max(minBlockW(W, H) * 1.18, Math.min(maxBlockW(W, H), 0.25 * W), capsWidth(label, kSize) + padX * 2);
  const axisW = cardW - padX * 2;
  const head = label ? kSize + 0.18 * yearSize : 0;
  const tickH = 18 * k;
  // the years under the axis (the one the story came from and the one said) only when there are two
  const under = first !== null ? sSize + 12 * k : 0;
  const yearH = yearSize * 1.2;
  const cardH = padT + head + yearH + 0.22 * yearSize + tickH + under + padB;
  const zone = zoneFor(overlay, "upper-left", cardW, cardH, W, H) as Zone;
  const r = blockAt(zone, cardW, cardH, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  const open = prog(f, 0, 14, S, expoOut);
  const draw = prog(f, 4, 18, S, expoOut) * (1 - clamp01(out * 1.4));
  const xOf = (y: number) => ((y - lo) / Math.max(1, hi - lo)) * axisW;
  // the dot: in from the left end (or the year the story was in) to the year, then on to a later point
  const startYear = first ?? lo;
  const legs: { from: number; to: number; start: number }[] = [];
  if (years.length === 1) legs.push({ from: startYear, to: target, start: 10 });
  else {
    let t = 10;
    for (let i = 1; i < years.length; i++) {
      const said = at[i];
      const start = Number.isFinite(said) ? Math.max(t, said * 30) : t;
      legs.push({ from: years[i - 1], to: years[i], start });
      t = start + 30;
    }
  }
  const LEG = 26;
  let shownYear = first ?? target;
  let x = xOf(startYear);
  let reached = 0;
  for (const leg of legs) {
    if (f / S < leg.start) break;
    const p = prog(f, leg.start, LEG, S, cubicInOut);
    shownYear = Math.round(leg.from + (leg.to - leg.from) * p);
    x = xOf(leg.from + (leg.to - leg.from) * p);
    if (p >= 1) reached += 1;
  }
  if (first === null && f / S < 10) shownYear = target;
  const land = legs.length ? legs[legs.length - 1].start + LEG : 36;
  const pulse = clamp01((f / S - land) / 6) * (1 - clamp01((f / S - land - 6) / 22));
  const axisY = padT + head + yearH + 0.22 * yearSize;
  const ticks: number[] = [];
  for (let y = Math.ceil(lo / step) * step; y <= hi; y += step) ticks.push(y);
  const startX = xOf(startYear);
  const mirror = (v: number) => (right ? axisW - v : v);
  return (
    <AbsoluteFill>
      <Glass x={r.x} y={r.y} w={cardW} h={cardH} k={k} p={open} out={out} right={anchor}>
        <div style={{ position: "absolute", left: padX, top: 0, width: axisW, height: cardH }}>
          <div style={{ position: "absolute", top: padT, left: 0, right: 0, display: "flex", flexDirection: "column",
            alignItems: right ? "flex-end" : "flex-start" }}>
            {label ? (
              <div style={{ height: kSize, marginBottom: 0.18 * yearSize }}>
                <Caps text={label} size={kSize} color={kickerColor(dir, hot)} at={6} out={out} k={k} align={right ? "right" : "left"} />
              </div>
            ) : null}
            {/* the year, counting while the dot slides */}
            <div style={{ height: yearH, display: "flex", alignItems: "center", fontFamily: dir.font, fontWeight: 800, fontSize: yearSize,
              lineHeight: 1, color: WHITE, letterSpacing: "-0.01em", fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1',
              textShadow: softShadow(k, 0.5), whiteSpace: "nowrap", opacity: prog(f, 6, 8, S, cubicOut) * (1 - clamp01(out * 1.5)),
              transform: `translateY(${((1 - prog(f, 6, 14, S, expoOut)) * 0.25 * yearSize + out * 10 * k).toFixed(2)}px) scale(${(1 + 0.04 * pulse).toFixed(4)})`,
              transformOrigin: right ? "100% 70%" : "0% 70%" }}>
              {String(shownYear)}
            </div>
          </div>
          {/* the axis: a tick at every step (taller every fifth), the travelled part in the accent */}
          <div style={{ position: "absolute", left: 0, width: axisW, top: axisY, height: tickH }}>
            <div style={{ position: "absolute", left: 0, right: 0, top: tickH / 2 - 1.25 * k, height: Math.max(1, 2.5 * k), borderRadius: 2 * k,
              background: "linear-gradient(90deg, rgba(255,255,255,0.10), rgba(255,255,255,0.36) 10%, rgba(255,255,255,0.36) 90%, rgba(255,255,255,0.10))",
              transformOrigin: right ? "right" : "left", transform: `scaleX(${draw.toFixed(4)})` }} />
            {ticks.map((y, i) => {
              const tx = mirror(xOf(y));
              const major = step === 1 ? y % 5 === 0 : y % (step * 2) === 0;
              const tOn = prog(f, 6 + (right ? ticks.length - 1 - i : i) * (14 / Math.max(1, ticks.length)), 8, S, cubicOut)
                * (1 - clamp01(out * 1.5));
              const hh = major ? tickH : tickH * 0.5;
              return <div key={y} style={{ position: "absolute", left: tx - 0.9 * k, top: (tickH - hh) / 2, width: Math.max(1, 1.8 * k),
                height: hh, borderRadius: k, background: major ? "rgba(255,255,255,0.62)" : "rgba(255,255,255,0.34)", opacity: tOn }} />;
            })}
            {/* the travelled part */}
            <div style={{ position: "absolute", top: tickH / 2 - 2 * k, height: Math.max(2, 4 * k), borderRadius: 2 * k,
              left: Math.min(mirror(startX), mirror(x)), width: Math.abs(x - startX) * (1 - clamp01(out * 1.5)),
              background: `linear-gradient(90deg, ${rgba(hot, 0.75)}, ${hot})`, boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${rgba(hot, 0.55)}`,
              opacity: prog(f, 10, 6, S, cubicOut) }} />
            {/* the point the story came from, and any point passed */}
            {first !== null ? (
              <div style={{ position: "absolute", left: mirror(startX) - 6 * k, top: tickH / 2 - 6 * k, width: 12 * k, height: 12 * k,
                borderRadius: "50%", border: `${(2.5 * k).toFixed(1)}px solid ${hot}`, boxSizing: "border-box",
                background: "rgba(10,12,16,0.92)", opacity: prog(f, 10, 8, S, cubicOut) * (1 - clamp01(out * 1.5)) }} />
            ) : null}
            {years.slice(1, -1).map((y, i) => (reached > i ? (
              <div key={`p${i}`} style={{ position: "absolute", left: mirror(xOf(y)) - 5 * k, top: tickH / 2 - 5 * k, width: 10 * k,
                height: 10 * k, borderRadius: "50%", background: rgba(hot, 0.9), opacity: 1 - clamp01(out * 1.5) }} />
            ) : null))}
            {/* the dot */}
            <div style={{ position: "absolute", left: mirror(x) - 10 * k, top: tickH / 2 - 10 * k, width: 20 * k, height: 20 * k,
              borderRadius: "50%", background: WHITE,
              boxShadow: `0 0 0 ${(4 * k).toFixed(1)}px ${hot}, 0 0 ${((16 + 18 * pulse) * k).toFixed(1)}px ${rgba(hot, 0.8)}`,
              opacity: prog(f, 9, 6, S, cubicOut) * (1 - clamp01(out * 1.6)), transform: `scale(${(1 + 0.3 * pulse).toFixed(4)})` }} />
          </div>
          {/* the years under the axis: where the story came from (said), and the year the dot lands on */}
          {first !== null ? (() => {
            // each point's label under it ("AUG 4, 1961" for a date said, else the year), kept inside the card
            const lab = (i: number) => labels[i] || String(years[i]);
            const place = (x0: number, text: string) => {
              const w = capsWidth(text, sSize, 0.04, 800);
              return Math.max(0, Math.min(axisW - w, x0 - w / 2));
            };
            const firstLab = lab(0);
            const lastLab = lab(years.length - 1);
            return (
              <>
                <div style={{ position: "absolute", top: axisY + tickH + 8 * k, left: place(mirror(startX), firstLab) }}>
                  <Caps text={firstLab} size={sSize} color={DIM} at={12} out={out} k={k} tracking={0.04} weight={700} />
                </div>
                {years.slice(1, -1).map((y, i) => (reached > i ? (
                  <div key={`l${i}`} style={{ position: "absolute", top: axisY + tickH + 8 * k, left: place(mirror(xOf(y)), lab(i + 1)) }}>
                    <Caps text={lab(i + 1)} size={sSize} color={DIM} at={0} out={out} k={k} tracking={0.04} weight={700} />
                  </div>
                ) : null))}
                <div style={{ position: "absolute", top: axisY + tickH + 8 * k, left: place(mirror(xOf(target)), lastLab),
                  opacity: clamp01((f / S - land + 4) / 8) }}>
                  <Caps text={lastLab} size={sSize} color={WHITE} at={land - 4} out={out} k={k} tracking={0.04} weight={800} />
                </div>
              </>
            );
          })() : null}
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-date-badge (the lower third)
const Badge: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, U, dir, hot, out, ks } = useDates(overlay, accent);
  const d = dateParts(overlay);
  const kicker = kickerOf(overlay);
  const year = d.year !== null ? String(d.year) : "";
  // "Nov 24, 1982" (a month and its day, short), "November 1982", "1982"
  const head = d.month !== null ? monthWords(d, d.day !== null) : "";
  const text = head ? `${head}${year ? (d.day !== null ? `, ${year}` : ` ${year}`) : ""}` : year;
  if (!text) return null;
  const main = caseOf(dir, text);
  const yearFrom = year && head ? main.length - year.length : -1;
  const size0 = fontFor("dateLine", U, ks, dir.cap);
  const kSize = fontFor("dateKicker", U, ks);
  const edgeW = 6 * k;
  const padL = edgeW + 0.32 * size0, padR = 0.38 * size0, padT = 0.26 * size0, padB = 0.2 * size0;
  const least = (leastShare("dateLine") * U * ks) / dir.cap;
  let size = size0;
  while (size > least && riseWidth(main, dir.font, size, 800) > maxBlockW(W, H) - padL - padR) size *= 0.97;
  const lineW = riseWidth(main, dir.font, size, 800);
  const lineH = size * 1.2;
  const head2 = kicker ? kSize + 0.18 * size : 0;
  const innerW = Math.max(lineW, kicker ? capsWidth(kicker, kSize) : 0, minBlockW(W, H) - padL - padR);
  const w = innerW + padL + padR;
  const h = padT + head2 + lineH + padB;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  const edgeP = prog(f, 0, 10, S, expoOut) * (1 - clamp01(out * 1.5));
  const open = prog(f, 3, 15, S, expoOut);
  return (
    <AbsoluteFill>
      <Glass x={r.x} y={r.y} w={w} h={h} k={k} p={Math.max(open, edgeP * 0.08)} out={out} right={right} radius={10} edge={hot} edgeP={edgeP}>
        <div style={{ position: "absolute", left: right ? padR : padL, right: right ? padL : padR, top: padT, display: "flex",
          flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 0.18 * size }}>
              <Caps text={kicker} size={kSize} color={kickerColor(dir, hot)} at={7} out={out} k={k} align={right ? "right" : "left"} />
            </div>
          ) : null}
          <RiseLine text={main} size={size} font={dir.font} weight={800} at={9} out={out} k={k}
            colorOf={(i) => (yearFrom >= 0 && i >= yearFrom ? hot : undefined)} />
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== counters: kt-year, kt-time
/**
 * Glass slots with a wheel in each: a year (from the year the story was in) or a clock time. `later`: years said
 * a beat after it - the wheels roll on to each when it is said (its frame), the slots flashing as they land.
 */
const Slots: React.FC<{ chars: string; from?: string; size: number; font: string; at: number; out: number; k: number;
  hot: string; tail?: string; later?: { chars: string; at: number }[] }> =
  ({ chars, from, size, font, at, out, k, hot, tail = "", later = [] }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const S = fps / 30;
  const list = Array.from(chars);
  const digits = list.filter((c) => /\d/.test(c)).join("");
  const steps = from && from.length === digits.length ? wheelSteps(from, digits) : Array.from(digits, (_c, i) => 2 + i);
  // the later phases: each digit's steps from the year before it, and when its wheel starts
  const phases = later.filter((p) => p.chars.length === digits.length).map((p, n, arr) => ({
    digits: p.chars, at: p.at, steps: wheelSteps(n === 0 ? digits : arr[n - 1].chars, p.chars),
  }));
  const slotW = widthOf("0", font, size, 800) * 1.34;
  const slotH = size * 1.3;
  const gap = 0.09 * size;
  let di = -1;
  const n = list.length + (tail ? 1 : 0);
  const slot = (key: string | number, i: number, w: number, inner: React.ReactNode, flash = 0) => {
    const pop = prog(f, at + i * 1.6, 12, S, (u) => backOut(u, 1.3));
    const xo = clamp01(out * 1.3 - ((n - 1 - i) / Math.max(1, n)) * 0.3);
    return (
      <div key={key} style={{ position: "relative", width: w, height: slotH, borderRadius: 10 * k, flex: "none",
        opacity: clamp01(pop * 1.4) * (1 - xo), transform: `scale(${(0.86 + 0.14 * pop).toFixed(4)}) translateY(${(xo * 8 * k).toFixed(2)}px)` }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 10 * k, overflow: "hidden",
          background: "linear-gradient(180deg, rgba(32,35,42,0.80) 0%, rgba(12,14,18,0.88) 50%, rgba(22,25,30,0.84) 100%)",
          backdropFilter: `blur(${(14 * k).toFixed(1)}px)`, WebkitBackdropFilter: `blur(${(14 * k).toFixed(1)}px)`,
          boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${flash > 0 ? rgba(hot, 0.35 + 0.5 * flash) : HAIRLINE}, `
            + `0 ${(12 * k).toFixed(1)}px ${(28 * k).toFixed(1)}px rgba(0,0,0,0.38), 0 0 ${(18 * flash * k).toFixed(1)}px ${rgba(hot, 0.45 * flash)}` }}>
          {inner}
        </div>
      </div>
    );
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap }}>
      {list.map((c, i) => {
        if (!/\d/.test(c)) {
          return (
            <div key={i} style={{ fontFamily: font, fontWeight: 800, fontSize: size, lineHeight: 1, color: "rgba(250,250,247,0.92)",
              width: widthOf(c, font, size, 800) * 1.1, textAlign: "center", marginTop: -0.08 * size, flex: "none",
              textShadow: softShadow(k, 0.6), opacity: prog(f, at + 6, 8, S, cubicOut) * (1 - clamp01(out * 1.5)) }}>{c}</div>
          );
        }
        di += 1;
        // the phase this wheel is in: the first roll, else the last later year whose roll has begun
        let s = steps[di] ?? 2 + di;
        let t0 = at + 2 + di * 1.5;
        let to = Number(c);
        let first = true;
        for (const p of phases) {
          const pt = p.at + di * 1.5;
          if (f / S >= pt - 1) {
            s = p.steps[di];
            t0 = pt;
            to = Number(p.digits[di]);
            first = false;
          }
        }
        const len = 20 + Math.min(6, Math.abs(s) * 0.2) + di * 1.5;
        const landF = t0 + len;
        const flash = s === 0 && !first ? 0 : clamp01((f / S - landF) / 4) * (1 - clamp01((f / S - landF - 4) / 16));
        const xo = clamp01(out * 1.3 - ((n - 1 - i) / Math.max(1, n)) * 0.3);
        return slot(i, i, slotW, (
          <>
            {/* the wheel's window: a crease across the middle like a mechanical counter */}
            <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: Math.max(1, k), background: "rgba(0,0,0,0.35)", zIndex: 2 }} />
            <div style={{ position: "absolute", left: 0, right: 0, top: (slotH - size * 1.12) / 2 + size * 0.02, height: size * 1.12 }}>
              <Wheel key={first ? "w0" : `w${t0}`} to={to} steps={s} at={t0} len={len} size={size} h={size * 1.12} font={font}
                weight={800} color={WHITE} k={k} out={xo} fade={first} />
            </div>
            <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: "34%", background: "linear-gradient(180deg, rgba(8,9,12,0.55), rgba(8,9,12,0))", zIndex: 1 }} />
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "34%", background: "linear-gradient(0deg, rgba(8,9,12,0.55), rgba(8,9,12,0))", zIndex: 1 }} />
          </>
        ), flash);
      })}
      {tail ? slot("tail", list.length, widthOf(tail, SUBLINE, size * 0.42, 800, 0.06) + size * 0.5, (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Caps text={tail} size={size * 0.42} color={hot} at={at + 18} out={out} k={k} tracking={0.06} weight={800} align="center" />
        </div>
      )) : null}
    </div>
  );
};

const slotsWidth = (chars: string, font: string, size: number, tail = "") => {
  const list = Array.from(chars);
  const slotW = widthOf("0", font, size, 800) * 1.34;
  const gap = 0.09 * size;
  const tw = tail ? widthOf(tail, SUBLINE, size * 0.42, 800, 0.06) + size * 0.5 + gap : 0;
  return list.reduce((a, c) => a + (/\d/.test(c) ? slotW : widthOf(c, font, size, 800) * 1.1), 0) + gap * Math.max(0, list.length - 1) + tw;
};

/** The kicker over a counter, on a small glass tab of its own (legible on a bright sky). */
const KickerTab: React.FC<{ parts: { text: string; color: string }[]; size: number; k: number; out: number; at: number;
  right: boolean }> = ({ parts, size, k, out, at, right }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const S = fps / 30;
  const padX = 0.6 * size, padY = 0.42 * size;
  const gap = 0.7 * size;
  const w = parts.reduce((a, p) => a + capsWidth(p.text, size), 0) + gap * Math.max(0, parts.length - 1) + padX * 2;
  const h = size + padY * 2;
  const open = prog(f, at, 14, S, expoOut);
  return (
    <div style={{ position: "relative", width: w, height: h }}>
      <Glass x={0} y={0} w={w} h={h} k={k} p={open} out={out} right={right} radius={8}>
        <div style={{ position: "absolute", left: padX, right: padX, top: padY, display: "flex", gap, flexDirection: right ? "row-reverse" : "row" }}>
          {parts.map((p, i) => <Caps key={i} text={p.text} size={size} color={p.color} at={at + 2 + i * 3} out={out} k={k} shadow={false} />)}
        </div>
      </Glass>
    </div>
  );
};

const YearCounter: Look = ({ overlay, accent }) => {
  const { k, W, H, U, dir, hot, out, ks } = useDates(overlay, accent);
  const { years, at } = yearsOf(overlay);
  if (!years.length) return null;
  // two (or three) years said a beat apart: the first rolls in, the wheels roll on to each later one as it is said;
  // else a jump: from the year the story was in to the year said
  const steps = phased(at);
  const year = String(steps ? years[0] : years[years.length - 1]);
  const later = steps ? years.slice(1).map((y, i) => ({ chars: String(y), at: (Number.isFinite(at[i + 1]) ? at[i + 1] : 1) * 30 })) : [];
  const from = !steps && years.length > 1 ? String(years[years.length - 2]) : "";
  const kicker = kickerOf(overlay);
  const kSize = fontFor("dateKicker", U, ks);
  const size = fontFor("counter", U, ks);
  const font = GROTESK;
  const sw = slotsWidth(year, font, size);
  const parts = [...(kicker ? [{ text: kicker, color: kickerColor(dir, hot) }] : []),
    ...(from ? [{ text: `from ${from}`, color: DIM }] : [])];
  const tabH = parts.length ? kSize * 1.84 + 0.14 * size : 0;
  const tabW = parts.length ? parts.reduce((a, p) => a + capsWidth(p.text, kSize), 0) + 0.7 * kSize * (parts.length - 1) + 1.2 * kSize : 0;
  const w = Math.max(sw, tabW);
  const h = tabH + size * 1.3;
  const zone = zoneFor(overlay, "upper-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: r.x, top: r.y, width: r.w, display: "flex", flexDirection: "column",
        alignItems: right ? "flex-end" : "flex-start", gap: 0.14 * size }}>
        {parts.length ? <KickerTab parts={parts} size={kSize} k={k} out={out} at={0} right={right} /> : null}
        <Slots chars={year} from={from} size={size} font={font} at={4} out={out} k={k} hot={hot} later={later} />
      </div>
    </AbsoluteFill>
  );
};

/** A clock time as said ("3 AM", "3:45 PM", "21:40", "12:00 AM"): the digits, and AM / PM. */
export const clockOf = (s: string): { digits: string; ampm: string } | null => {
  const m = /^\s*(\d{1,2})(?::([0-5]\d))?\s*([AP])\.?\s?M\.?\s*$/i.exec(s) || /^\s*(\d{1,2}):([0-5]\d)\s*$/.exec(s);
  if (!m) return null;
  const h = Number(m[1]);
  if (!(h >= 0 && h <= 23)) return null;
  return { digits: `${h}:${m[2] || "00"}`, ampm: m[3] ? `${m[3].toUpperCase()}M` : "" };
};

const TimeCounter: Look = ({ overlay, accent }) => {
  const { k, W, H, U, dir, hot, out, ks, f, S } = useDates(overlay, accent);
  const raw = str(overlay.text);
  const t = clockOf(raw);
  const kicker = kickerOf(overlay);
  const kSize = fontFor("dateKicker", U, ks);
  const size = fontFor("counter", U, ks);
  const font = GROTESK;
  if (!t) {
    // a time said in words ("Dawn", "That evening"): the words on a glass chip like the stamp's
    const words = caseOf(dir, raw);
    if (!words) return null;
    const lineSize = fontFor("dateLine", U, ks, dir.cap);
    const fit = fitLines(words, dir.font, 800, lineSize, lineSize * 0.8, maxBlockW(W, H) - lineSize * 0.7, 1, -0.012);
    if (!fit) return null;
    const padX = 0.34 * fit.size, padT = 0.26 * fit.size;
    const lw = riseWidth(fit.lines[0], dir.font, fit.size, 800);
    const head = kicker ? kSize + 0.2 * fit.size : 0;
    const cw = Math.max(lw, minBlockW(W, H) - padX * 2, kicker ? capsWidth(kicker, kSize) : 0) + padX * 2;
    const chh = padT + head + fit.size * 1.2 + 0.3 * fit.size;
    const zone = zoneFor(overlay, "upper-left", cw, chh, W, H) as Zone;
    const r = blockAt(zone, cw, chh, W, H);
    const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
    const open = prog(f, 0, 14, S, expoOut);
    return (
      <AbsoluteFill>
        <Glass x={r.x} y={r.y} w={cw} h={chh} k={k} p={open} out={out} right={right}>
          <div style={{ position: "absolute", left: padX, right: padX, top: padT, display: "flex", flexDirection: "column",
            alignItems: right ? "flex-end" : "flex-start" }}>
            {kicker ? (
              <div style={{ height: kSize, marginBottom: 0.2 * fit.size }}>
                <Caps text={kicker} size={kSize} color={kickerColor(dir, hot)} at={4} out={out} k={k} />
              </div>
            ) : null}
            <RiseLine text={fit.lines[0]} size={fit.size} font={dir.font} weight={800} at={6} out={out} k={k} />
          </div>
        </Glass>
      </AbsoluteFill>
    );
  }
  const sw = slotsWidth(t.digits, font, size, t.ampm);
  const parts = kicker ? [{ text: kicker, color: kickerColor(dir, hot) }] : [];
  const tabH = parts.length ? kSize * 1.84 + 0.14 * size : 0;
  const w = Math.max(sw, parts.length ? capsWidth(kicker, kSize) + 1.2 * kSize : 0);
  const h = tabH + size * 1.3;
  const zone = zoneFor(overlay, "upper-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: r.x, top: r.y, width: r.w, display: "flex", flexDirection: "column",
        alignItems: right ? "flex-end" : "flex-start", gap: 0.14 * size }}>
        {parts.length ? <KickerTab parts={parts} size={kSize} k={k} out={out} at={0} right={right} /> : null}
        <Slots chars={t.digits} size={size} font={font} at={4} out={out} k={k} hot={hot} tail={t.ampm} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-time-clock (the clock face)
const ClockLook: Look = (props) => {
  const { overlay, accent } = props;
  const { f, S, k, W, H, U, dir, hot, out, ks } = useDates(overlay, accent);
  const t = clockOf(str(overlay.text));
  if (!t) return <TimeCounter {...props} />;
  const [hh, mm] = t.digits.split(":").map(Number);
  const kicker = kickerOf(overlay);
  const D = scale.clock.diameter * U * ks;
  const R = D / 2;
  const lineSize = fontFor("dateLine", U, ks, dir.cap);
  const kSize = fontFor("dateKicker", U, ks);
  const apSize = lineSize * 0.4;
  const digitsW = riseWidth(t.digits, dir.font, lineSize, 800);
  const timeW = digitsW + (t.ampm ? 0.16 * lineSize + capsWidth(t.ampm, apSize, 0.06, 800) : 0);
  const colW = Math.max(timeW, kicker ? capsWidth(kicker, kSize) : 0);
  const tabPadL = 0.36 * lineSize, tabPadR = 0.4 * lineSize;
  const tabH = Math.min(D * 0.84, (kicker ? kSize + 0.18 * lineSize : 0) + lineSize * 1.2 + 0.46 * lineSize);
  const w = D + tabPadL + colW + tabPadR;
  const zone = zoneFor(overlay, "upper-left", w, D, W, H) as Zone;
  const r = blockAt(zone, w, D, W, H);
  const right = false;                    // the inside reads left to right on either side
  const anchor = isRight(zone);
  const faceX = right ? r.x + r.w - D : r.x;
  const tabX = right ? r.x : faceX + D * 0.5;
  const tabW = w - D * 0.5;
  const tabY = r.y + (D - tabH) / 2;
  const colLeft = right ? r.x + tabPadR : faceX + D + tabPadL;
  const enter = prog(f, 0, 16, S, (u) => backOut(u, 1.4));
  const o = prog(f, 0, 8, S, cubicOut) * (1 - clamp01(out * 1.3));
  const sweep = prog(f, 10, 30, S, cubicInOut);
  const land = 40;
  const pulse = clamp01((f / S - land) / 5) * (1 - clamp01((f / S - land - 5) / 20));
  const minuteA = (mm * 6 + 720) * sweep;
  const hourA = ((hh % 12) * 30 + mm * 0.5) * sweep;
  const hand = (len: number, wd: number, a: number, color: string) => (
    <div style={{ position: "absolute", left: R - wd / 2, top: R - len, width: wd, height: len + wd * 0.8, borderRadius: wd,
      background: color, transformOrigin: `50% ${len}px`, transform: `rotate(${a.toFixed(2)}deg)`,
      boxShadow: `0 ${(2 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,0.35)` }} />
  );
  return (
    <AbsoluteFill>
      <Glass x={tabX} y={tabY} w={tabW} h={tabH} k={k} p={prog(f, 8, 16, S, expoOut)} out={out} right={right} radius={14}>
        <div style={{ position: "absolute", left: colLeft - tabX, top: 0, width: colW, height: tabH, display: "flex",
          flexDirection: "column", justifyContent: "center", alignItems: right ? "flex-end" : "flex-start" }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 0.18 * lineSize }}>
              <Caps text={kicker} size={kSize} color={kickerColor(dir, hot)} at={10} out={out} k={k} align={right ? "right" : "left"} />
            </div>
          ) : null}
          <div style={{ display: "flex", alignItems: "flex-end", gap: 0.16 * lineSize, flexDirection: right ? "row-reverse" : "row" }}>
            <RiseLine text={t.digits} size={lineSize} font={dir.font} weight={800} at={12} out={out} k={k} />
            {t.ampm ? (
              <div style={{ marginBottom: 0.3 * lineSize }}>
                <Caps text={t.ampm} size={apSize} color={hot} at={24} out={out} k={k} tracking={0.06} weight={800} />
              </div>
            ) : null}
          </div>
        </div>
      </Glass>
      <div style={{ position: "absolute", left: faceX, top: r.y, width: D, height: D, opacity: o,
        transform: `scale(${(0.82 + 0.18 * enter + 0.03 * pulse).toFixed(4)})` }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: "50%", overflow: "hidden",
          background: "radial-gradient(circle at 50% 38%, rgba(36,40,48,0.86) 0%, rgba(10,12,16,0.92) 72%)",
          backdropFilter: `blur(${(16 * k).toFixed(1)}px)`, WebkitBackdropFilter: `blur(${(16 * k).toFixed(1)}px)`,
          boxShadow: `inset 0 0 0 ${(1.5 * k).toFixed(1)}px rgba(255,255,255,0.16), 0 ${(16 * k).toFixed(1)}px ${(40 * k).toFixed(1)}px rgba(0,0,0,0.45)` }} />
        <svg width={D} height={D} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <circle cx={R} cy={R} r={R - 3 * k} fill="none" stroke={hot} strokeWidth={2.5 * k} pathLength={1} strokeDasharray="1 1"
            strokeDashoffset={1 - prog(f, 4, 22, S, cubicInOut)} transform={`rotate(-90 ${R} ${R})`} opacity={0.9 * (1 - out)} />
          {Array.from({ length: 12 }, (_, i) => {
            const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
            const big = i % 3 === 0;
            const r0 = R - (big ? 0.2 : 0.14) * D * 0.5 - 8 * k, r1 = R - 9 * k;
            const on = prog(f, 4 + i * 1.2, 8, S, cubicOut);
            return <line key={i} x1={R + r0 * Math.cos(a)} y1={R + r0 * Math.sin(a)} x2={R + r1 * Math.cos(a)} y2={R + r1 * Math.sin(a)}
              stroke={big ? WHITE : "rgba(255,255,255,0.5)"} strokeWidth={(big ? 3.5 : 2) * k} strokeLinecap="round" opacity={on} />;
          })}
        </svg>
        {hand(R * 0.5, 7 * k, hourA, WHITE)}
        {hand(R * 0.74, 4.5 * k, minuteA, "rgba(250,250,247,0.92)")}
        <div style={{ position: "absolute", left: R - 7 * k, top: R - 7 * k, width: 14 * k, height: 14 * k, borderRadius: "50%",
          background: hot, boxShadow: `0 0 ${((8 + 14 * pulse) * k).toFixed(1)}px ${rgba(hot, 0.8)}` }} />
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-date": guard(Stamp),
  "kt-date-card": guard(Card),
  "kt-date-line": guard(TimelineLook),
  "kt-date-badge": guard(Badge),
  "kt-year": guard(YearCounter),
  "kt-time": guard(TimeCounter),
  "kt-time-clock": guard(ClockLook),
};
