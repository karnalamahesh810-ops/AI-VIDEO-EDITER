import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL, MONO } from "../fonts";
import type { Overlay } from "../../types";
import { lines, ramp, useK } from "../pro/ProGraphics";

/**
 * Dates and times (family "dt-"): bold, clean cards in one strong palette
 * (deep navy, warm yellow, white; red only for the calendar's marker circle
 * and the camera REC dot), so a date always reads at a glance.
 *
 *   dt-clean-card      navy card: the month in a yellow block, the day counting up big, year and weekday beside it
 *   dt-calendar-page   a month page flips down and the day is circled with a red marker
 *   dt-stamp-bar       a lower-left bar "THURSDAY • SEPT 25, 2026" revealed by a sliding yellow block
 *   dt-clock-time      an analog clock whose hands spin to the time, the digital time big beside it
 *   dt-rec-stamp       a camera timestamp top-right, blinking REC dot, running seconds, viewfinder corners
 *   dt-date-slam       a full-width band: yellow then navy wipe, the date's numerals slam in with a shake
 *   dt-timeline-tick   a thin month (or year) ruler slides in and a marker drops on the date with its label
 *   dt-countdown-days  "3 DAYS LATER" / "48 HOURS": the number counts up, a time bar fills
 *   dt-bold-headline   the date as a huge bold headline slammed onto a colour block with a small
 *                      shake, the weekday above it, the year / place under it; ranges as
 *                      "TUESDAY → THURSDAY" or "SEPT 28 → OCT 2"
 *   dt-big-stack       stacked bold type left of centre: the day number huge, the month in a
 *                      solid bar, the weekday / year small; punches in
 *
 * overlay.text is read robustly: "SEPTEMBER 25, 2026", "SEPT. 25", "MARCH 2026",
 * "3:45 PM", "SEPTEMBER 25, 2026 · 3:45 PM", "9/25/2026", "2026-09-25",
 * "noon", "15:45"; overlay.label is a weekday or a place; overlay.value may
 * carry a year. Anything unparseable still draws as a clean text card, never a
 * crash. Sizes are final pixels at 1080p (these looks draw at scale 1.0);
 * nothing is larger than 140 px except the two bold looks, whose date is the
 * headline itself (up to 214 px, the stack's day 330 px). Every look leaves
 * in its last 12 frames. No
 * sound is played here (the timeline sound lands on the look's sfx_at).
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const softBack = Easing.bezier(0.3, 1.25, 0.5, 1);
const EXIT = 12;
const NAVY = "#0B1F3A";
const NAVY_2 = "#12294B";
const YELLOW = "#FFC83D";
const INK = "#0A0F1A";
const RED = "#E5202A";

// ------------------------------------------------------------------ parsing
const MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
  "NOVEMBER", "DECEMBER"];
const MON3 = MONTHS.map((m) => m.slice(0, 3));
/** Newsroom abbreviations: short months spelled out, the rest cut (SEPT, not SEP.). */
const MON_AP = ["JAN", "FEB", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUG", "SEPT", "OCT", "NOV", "DEC"];
const WEEKDAYS = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"];

const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();
const num = (v: unknown): number => (typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN);
const leap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const monthDays = (y: number, m: number) => [31, leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m] || 31;
/** Day of the week, 0 = Sunday (Sakamoto; no Date object, so renders stay deterministic). */
const weekdayOf = (y: number, m: number, d: number): number => {
  const t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4];
  const Y = m < 2 ? y - 1 : y;
  return (((Y + Math.floor(Y / 4) - Math.floor(Y / 100) + Math.floor(Y / 400) + t[m] + d) % 7) + 7) % 7;
};
const monthOf = (tok: string): number => (tok.length >= 3 && /^[A-Z]+$/.test(tok) ? MONTHS.findIndex((m) => m.startsWith(tok)) : -1);
const weekdayTok = (tok: string): number =>
  tok.length >= 3 && /^[A-Z]+$/.test(tok) ? WEEKDAYS.findIndex((w) => w.startsWith(tok) || tok === `${w}S`) : -1;

export type DT = {
  month?: number; day?: number; year?: number;
  hour?: number; minute?: number; ampm?: "AM" | "PM";
  weekday?: number; place?: string;
};

/** Everything a date/time look needs from overlay.text / label / value. Never throws. */
export const parseDT = (textIn: unknown, labelIn?: unknown, valueIn?: unknown): DT => {
  const out: DT = {};
  let s = ` ${str(textIn).toUpperCase().replace(/[’']/g, "")} `;
  // Time of day.
  if (/\bNOON\b|\bMIDDAY\b/.test(s)) {
    out.hour = 12; out.minute = 0; out.ampm = "PM";
    s = s.replace(/\bNOON\b|\bMIDDAY\b/, " ");
  } else if (/\bMIDNIGHT\b/.test(s)) {
    out.hour = 12; out.minute = 0; out.ampm = "AM";
    s = s.replace(/\bMIDNIGHT\b/, " ");
  }
  if (out.hour === undefined) {
    const m12 = /(^|[^\d:])(\d{1,2})(?::([0-5]\d))?(?::[0-5]\d)?\s*([AP])\.?\s?M\b\.?/.exec(s);
    if (m12 && Number(m12[2]) >= 1 && Number(m12[2]) <= 12) {
      out.hour = Number(m12[2]);
      out.minute = m12[3] ? Number(m12[3]) : 0;
      out.ampm = m12[4] === "A" ? "AM" : "PM";
      s = s.replace(m12[0], `${m12[1]} `);
    } else {
      const m24 = /(^|[^\d])([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?!\d)/.exec(s);
      if (m24) {
        const h = Number(m24[2]);
        out.hour = h % 12 === 0 ? 12 : h % 12;
        out.minute = Number(m24[3]);
        out.ampm = h >= 12 ? "PM" : "AM";
        s = s.replace(m24[0], `${m24[1]} `);
      }
    }
  }
  // Numeric dates.
  const iso = /\b(\d{4})-(\d{1,2})-(\d{1,2})\b/.exec(s);
  const us = /\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b/.exec(s);
  if (iso && Number(iso[2]) >= 1 && Number(iso[2]) <= 12) {
    out.year = Number(iso[1]); out.month = Number(iso[2]) - 1; out.day = Number(iso[3]);
    s = s.replace(iso[0], " ");
  } else if (us && Number(us[1]) >= 1 && Number(us[1]) <= 12) {
    const y = Number(us[3]);
    out.month = Number(us[1]) - 1; out.day = Number(us[2]);
    out.year = us[3].length === 2 ? (y < 50 ? 2000 + y : 1900 + y) : y;
    s = s.replace(us[0], " ");
  }
  const toks = s.split(/[^A-Z0-9]+/).filter(Boolean);
  let monthAt = -1;
  if (out.month === undefined) {
    monthAt = toks.findIndex((t) => monthOf(t) >= 0);
    if (monthAt >= 0) out.month = monthOf(toks[monthAt]);
  }
  for (const t of toks) {
    const w = weekdayTok(t);
    if (w >= 0) {
      out.weekday = w;
      break;
    }
  }
  if (out.year === undefined) {
    const years = toks.filter((t) => /^\d{4}$/.test(t)).map(Number).filter((n) => n >= 1000 && n <= 2999);
    if (years.length) out.year = years[years.length - 1];
  }
  if (out.day === undefined && out.month !== undefined) {
    const dayOf = (t?: string) => {
      const m = /^(\d{1,2})(ST|ND|RD|TH)?$/.exec(t || "");
      const d = m ? Number(m[1]) : NaN;
      return d >= 1 && d <= 31 ? d : NaN;
    };
    let d = NaN;
    if (monthAt >= 0) d = Number.isFinite(dayOf(toks[monthAt + 1])) ? dayOf(toks[monthAt + 1]) : dayOf(toks[monthAt - 1]);
    if (!Number.isFinite(d)) {
      const any = toks.map(dayOf).find((x) => Number.isFinite(x));
      if (any !== undefined) d = any;
    }
    if (Number.isFinite(d)) out.day = d;
  }
  if (out.year === undefined) {
    const v = num(valueIn);
    if (Number.isFinite(v) && v >= 1000 && v <= 2999) out.year = Math.round(v);
  }
  if (out.month !== undefined && out.day !== undefined) out.day = Math.min(out.day, monthDays(out.year ?? 2001, out.month));
  const label = str(labelIn).toUpperCase();
  if (label) {
    const lw = weekdayTok(label.replace(/[^A-Z]/g, ""));
    if (lw >= 0) out.weekday = out.weekday ?? lw;
    else if (label !== str(textIn).toUpperCase()) out.place = label.slice(0, 40);
  }
  if (out.weekday === undefined && out.year !== undefined && out.month !== undefined && out.day !== undefined) {
    out.weekday = weekdayOf(out.year, out.month, out.day);
  }
  return out;
};

const hasDate = (d: DT) => d.month !== undefined || d.year !== undefined;
const hasTime = (d: DT) => d.hour !== undefined;
const two = (n: number) => String(Math.max(0, Math.floor(n))).padStart(2, "0");
const timeStr = (d: DT): string => (hasTime(d) ? `${d.hour}:${two(d.minute ?? 0)}` : "");
/** "SEPT 25, 2026", "MARCH 2026", "SEPT 25", "2026" (empty when there is no date). */
const dateLine = (d: DT, names = MON_AP): string => {
  const m = d.month !== undefined ? names[d.month] : "";
  if (m && d.day !== undefined) return d.year !== undefined ? `${m} ${d.day}, ${d.year}` : `${m} ${d.day}`;
  if (m) return d.year !== undefined ? `${m} ${d.year}` : m;
  return d.year !== undefined ? String(d.year) : "";
};

// ------------------------------------------------------------------ shared
const useOut = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - EXIT, EXIT, expoIn);
};
const usePx = () => {
  const k = useK();
  return (n: number) => n * k;
};
/** A soft darkening under a date card (never on a full-screen scene). */
const Shade: React.FC<{ ov: Overlay; background: string; out: number }> = ({ ov, background, out }) => {
  const frame = useCurrentFrame();
  if (ov.fullFrame) return null;
  return <AbsoluteFill style={{ background, opacity: ramp(frame, 0, 12) * (1 - out) }} />;
};
/** An integer counting from `from` to `to` between two frames, easing out (never jittering). */
const countTo = (frame: number, a: number, b: number, from: number, to: number): number =>
  // Quadratic ease-out: it slows into the value but reaches it on frame b
  // (an expo curve sat one short of the value for a third of the count).
  Math.round(interpolate(frame, [a, b], [from, to], { ...clamp, easing: Easing.out(Easing.quad) }));
/** Width of an uppercase label in px (LABEL ~0.5em a letter, Bebas ~0.42em). */
const labelW = (s: string, size: number, font: "label" | "display" | "inter" | "mono" = "label", tracking = 0) =>
  s.length * size * ({ label: 0.52, display: 0.43, inter: 0.7, mono: 0.6 }[font] + tracking);

// ================================================================== dt-clean-card
/**
 * A bold navy date card: the month in a solid yellow block, the day huge on
 * the left counting up to its value and landing with a small punch on frame
 * 28 (sfx_at), the year and weekday beside it; the place (label) under the card.
 */
const DtCleanCard: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  const text = str(overlay.text).toUpperCase();
  const pin = ramp(frame, 0, 14, expoOut);
  const settle = 28;
  const punch = interpolate(frame, [settle, settle + 4, settle + 10], [1, 1.07, 1], { ...clamp, easing: inOut });
  const monthIn = ramp(frame, 6, 12, expoOut);
  const yearIn = ramp(frame, 10, 12, expoOut);
  const wdIn = ramp(frame, 15, 12, expoOut);
  const big = px(140);
  let bigText = "";
  let digits = 2;
  const side: React.ReactNode[] = [];
  const monthBlock = (name: string) => (
    <div key="m" style={{ alignSelf: "flex-start", background: YELLOW, color: NAVY, fontFamily: LABEL, fontWeight: 800,
      fontSize: px(46), lineHeight: 1.1, letterSpacing: "0.06em", padding: `${4 * u}px ${18 * u}px`,
      clipPath: `inset(0 ${((1 - monthIn) * 100).toFixed(2)}% 0 0)` }}>{name}</div>
  );
  if (d.month !== undefined && d.day !== undefined) {
    bigText = String(countTo(frame, 8, settle, 1, d.day));
    digits = String(d.day).length;
    side.push(monthBlock(MONTHS[d.month]));
    if (d.year !== undefined) {
      side.push(<div key="y" style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(60), lineHeight: 1.05, color: "#fff",
        letterSpacing: "0.04em", opacity: yearIn, transform: `translateY(${((1 - yearIn) * 14 * u).toFixed(2)}px)` }}>{d.year}</div>);
    }
  } else if (d.year !== undefined) {
    bigText = String(countTo(frame, 8, settle, d.year - 24, d.year));
    digits = 4;
    if (d.month !== undefined) side.push(monthBlock(MONTHS[d.month]));
  } else if (hasTime(d)) {
    bigText = timeStr(d);
    digits = bigText.length - 0.5;
  }
  const extra = [d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", hasTime(d) && bigText !== timeStr(d) ? `${timeStr(d)} ${d.ampm}` : "",
    hasTime(d) && bigText === timeStr(d) ? d.ampm || "" : ""].filter(Boolean).join("  ·  ");
  if (extra) {
    side.push(<div key="w" style={{ fontFamily: LABEL, fontWeight: 700, fontSize: px(32), color: YELLOW, letterSpacing: "0.2em",
      opacity: wdIn, marginTop: 4 * u }}>{extra}</div>);
  }
  const plain = !bigText;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 58% 56% at 50% 50%, rgba(0,0,0,.46) 0%, rgba(0,0,0,.3) 70%, rgba(0,0,0,.22) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 34 * u, background: NAVY, borderRadius: 18 * u,
          padding: `${26 * u}px ${46 * u}px ${26 * u}px ${40 * u}px`, boxShadow: `0 ${26 * u}px ${70 * u}px rgba(0,0,0,.5)`,
          borderTop: `${4 * u}px solid ${YELLOW}`, opacity: pin,
          transform: `translateY(${((1 - pin) * 40 * u + out * 24 * u).toFixed(2)}px) scale(${(0.94 + 0.06 * pin).toFixed(4)})` }}>
          {plain ? (
            <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(text.length > 22 ? 56 : 72), color: "#fff",
              letterSpacing: "0.04em", maxWidth: width * 0.6, textAlign: "center", lineHeight: 1.1 }}>{text.slice(0, 60)}</div>
          ) : (
            <div style={{ fontFamily: DISPLAY, fontSize: big, lineHeight: 0.9, color: "#fff", minWidth: `${(digits * 0.43).toFixed(2)}em`,
              textAlign: "center", fontVariantNumeric: "tabular-nums", paddingTop: "0.06em",
              transform: `scale(${punch.toFixed(4)})`, opacity: ramp(frame, 6, 6) }}>{bigText}</div>
          )}
          {!plain && side.length ? (
            <>
              <div style={{ width: Math.max(2, 2 * u), alignSelf: "stretch", background: "rgba(255,255,255,.2)" }} />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 * u }}>{side}</div>
            </>
          ) : null}
        </div>
        {d.place ? (
          <div style={{ marginTop: 22 * u, display: "flex", alignItems: "center", gap: 14 * u, opacity: ramp(frame, 18, 12) * (1 - out),
            fontFamily: LABEL, fontWeight: 700, fontSize: px(32), letterSpacing: "0.2em", color: "#fff",
            textShadow: "0 2px 12px rgba(0,0,0,.7)" }}>
            <div style={{ width: 12 * u, height: 12 * u, borderRadius: "50%", background: YELLOW }} />
            {d.place}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== dt-calendar-page
/** A hand-drawn marker loop around a box (a little more than one turn, uneven). */
const loopPath = (cx: number, cy: number, rx: number, ry: number, seed: number): string => {
  const pts: string[] = [];
  const n = 60;
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const a = (-110 + t * 395) * (Math.PI / 180);
    const wob = 1 + 0.05 * Math.sin(t * 9 + seed) + (t > 0.85 ? (t - 0.85) * 0.5 : 0);
    pts.push(`${(cx + Math.cos(a) * rx * wob).toFixed(2)} ${(cy + Math.sin(a) * ry * wob).toFixed(2)}`);
  }
  return `M ${pts.join(" L ")}`;
};

/**
 * A calendar month page flips down from its binding, the grid laid out from
 * the real first weekday; a red marker circles the day (frame 22, sfx_at),
 * then the full date settles under the page.
 */
const DtCalendarPage: Look = (props) => {
  const { overlay } = props;
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  if (d.month === undefined) return <DtCleanCard {...props} />;
  const year = d.year ?? 2026;
  const first = weekdayOf(year, d.month, 1);
  const days = monthDays(year, d.month);
  const rows = Math.ceil((first + days) / 7);
  const W = px(520);
  const pad = 22 * u;
  const col = (W - pad * 2) / 7;
  const rowH = px(56);
  const headH = px(92);
  const wkH = px(44);
  const H = headH + wkH + rows * rowH + pad * 1.4;
  const flip = ramp(frame, 0, 18, softBack);
  const circle = ramp(frame, 20, 14, inOut);
  const caption = ramp(frame, 30, 12, expoOut);
  const cells: React.ReactNode[] = [];
  let target: [number, number] | null = null;
  for (let i = 0; i < days; i++) {
    const idx = first + i;
    const r = Math.floor(idx / 7);
    const c = idx % 7;
    const x = pad + c * col;
    const y = headH + wkH + r * rowH;
    const isT = d.day === i + 1;
    if (isT) target = [x + col / 2, y + rowH / 2];
    cells.push(
      <div key={i} style={{ position: "absolute", left: x, top: y, width: col, height: rowH, display: "flex", alignItems: "center",
        justifyContent: "center", fontFamily: INTER, fontWeight: isT ? 800 : 700, fontSize: px(isT ? 30 : 26),
        color: isT ? NAVY : c === 0 || c === 6 ? "#8b93a1" : "#2b3444" }}>{i + 1}</div>,
    );
  }
  const seed = (d.day ?? 1) * 1.7;
  const full = [d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", dateLine(d, MONTHS)].filter(Boolean).join("  ·  ");
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 50% 60% at 50% 50%, rgba(0,0,0,.45) 0%, rgba(0,0,0,.28) 70%, rgba(0,0,0,.2) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column",
        transform: `translateY(${(out * 30 * u - height * 0.02).toFixed(2)}px)` }}>
        <div style={{ perspective: 1800 * u }}>
          <div style={{ position: "relative", width: W, height: H, transformOrigin: "50% 0%",
            transform: `rotateX(${((1 - flip) * -100).toFixed(3)}deg)`, opacity: ramp(frame, 0, 4, Easing.linear) }}>
            <div style={{ position: "absolute", inset: 0, background: "#FBFAF6", borderRadius: 14 * u, overflow: "hidden",
              boxShadow: `0 ${24 * u}px ${60 * u}px rgba(0,0,0,.5)` }}>
              <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: headH, background: NAVY, display: "flex",
                alignItems: "center", justifyContent: "space-between", padding: `${10 * u}px ${30 * u}px 0` }}>
                <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(46), letterSpacing: "0.08em", color: "#fff" }}>
                  {MONTHS[d.month]}
                </div>
                {d.year !== undefined ? (
                  <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: px(40), letterSpacing: "0.06em", color: YELLOW }}>{d.year}</div>
                ) : null}
              </div>
              {["S", "M", "T", "W", "T", "F", "S"].map((w, i) => (
                <div key={i} style={{ position: "absolute", left: pad + i * col, top: headH + 6 * u, width: col, height: wkH,
                  display: "flex", alignItems: "center", justifyContent: "center", fontFamily: INTER, fontWeight: 800,
                  fontSize: px(22), color: i === 0 || i === 6 ? "#b0b6c0" : "#6b7382" }}>{w}</div>
              ))}
              <div style={{ position: "absolute", left: pad, right: pad, top: headH + wkH, height: 2 * u, background: "#e4e2dc" }} />
              {cells}
            </div>
            {[0.24, 0.76].map((f) => (
              <div key={f} style={{ position: "absolute", left: W * f - 9 * u, top: -18 * u, width: 18 * u, height: 42 * u,
                borderRadius: 9 * u, background: "linear-gradient(90deg, #2a3140, #5b6475, #2a3140)",
                boxShadow: "0 2px 4px rgba(0,0,0,.4)" }} />
            ))}
            <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              {target ? (
                <path d={loopPath(target[0], target[1], col * 0.62, rowH * 0.58, seed)} fill="none" stroke={RED}
                  strokeWidth={Math.max(4, 7 * u)} strokeLinecap="round" strokeLinejoin="round" pathLength={1}
                  strokeDasharray="1" strokeDashoffset={(1 - circle).toFixed(4)} opacity={0.92} />
              ) : (
                <path d={loopPath(30 * u + labelW(MONTHS[d.month], px(46), "label", 0.08) / 2, headH / 2 + 5 * u,
                  labelW(MONTHS[d.month], px(46), "label", 0.08) / 2 + 22 * u, headH * 0.36, 2)} fill="none" stroke={YELLOW}
                  strokeWidth={Math.max(3, 5 * u)} strokeLinecap="round" pathLength={1} strokeDasharray="1"
                  strokeDashoffset={(1 - circle).toFixed(4)} />
              )}
            </svg>
          </div>
        </div>
        {full ? (
          <div style={{ marginTop: 30 * u, background: NAVY, color: "#fff", fontFamily: LABEL, fontWeight: 700, fontSize: px(34),
            letterSpacing: "0.12em", padding: `${8 * u}px ${24 * u}px`, borderLeft: `${6 * u}px solid ${YELLOW}`, opacity: caption,
            transform: `translateY(${((1 - caption) * 16 * u).toFixed(2)}px)`, boxShadow: `0 ${12 * u}px ${30 * u}px rgba(0,0,0,.4)` }}>
            {full}{d.place ? <span style={{ color: YELLOW }}>{`  ·  ${d.place}`}</span> : null}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== dt-stamp-bar
/**
 * A lower-left date bar, "THURSDAY • SEPT 25, 2026", revealed by a yellow
 * block that sweeps across it and slides off (frame 6, sfx_at); the place
 * (label) sits under it. It wipes away to the left at the end.
 */
const DtStampBar: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  const date = dateLine(d);
  const time = hasTime(d) ? `${timeStr(d)} ${d.ampm}` : "";
  const wd = d.weekday !== undefined ? WEEKDAYS[d.weekday] : "";
  const fallback = !date && !time ? str(overlay.text).toUpperCase().slice(0, 40) : "";
  const parts: { t: string; c: string }[] = [];
  if (wd) parts.push({ t: wd, c: YELLOW });
  if (date) parts.push({ t: date, c: "#fff" });
  if (time) parts.push({ t: time, c: "#fff" });
  if (fallback) parts.push({ t: fallback, c: "#fff" });
  const size = px(46);
  const p1 = ramp(frame, 0, 9, expoOut);
  const p2 = ramp(frame, 8, 10, inOut);
  const slide = ramp(frame, 8, 14, expoOut);
  const placeIn = ramp(frame, 16, 12, expoOut);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 110 * u, bottom: 190 * u, clipPath: `inset(-30% ${(out * 100).toFixed(2)}% -60% 0)` }}>
        <div style={{ position: "relative", display: "inline-block" }}>
          <div style={{ background: NAVY, clipPath: `inset(0 ${((1 - p1) * 100).toFixed(2)}% 0 0)`, height: px(80),
            boxShadow: `0 ${12 * u}px ${34 * u}px rgba(0,0,0,.42)`, display: "flex", alignItems: "center",
            borderLeft: `${10 * u}px solid ${YELLOW}`, padding: `0 ${34 * u}px 0 ${26 * u}px`, overflow: "hidden" }}>
            <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: size, letterSpacing: "0.05em", whiteSpace: "pre",
              transform: `translateX(${((1 - slide) * 40 * u).toFixed(2)}px)`, opacity: slide }}>
              {parts.map((p, i) => (
                <React.Fragment key={i}>
                  {i ? <span style={{ color: YELLOW, opacity: 0.9 }}>{"  •  "}</span> : null}
                  <span style={{ color: p.c }}>{p.t}</span>
                </React.Fragment>
              ))}
            </div>
          </div>
          <div style={{ position: "absolute", top: 0, bottom: 0, left: `${(p2 * 100).toFixed(3)}%`,
            width: `${(Math.max(0, p1 - p2) * 100).toFixed(3)}%`, background: YELLOW }} />
        </div>
        {d.place ? (
          <div>
            <div style={{ display: "inline-block", background: "#fff", color: NAVY, fontFamily: LABEL, fontWeight: 700, fontSize: px(32),
              letterSpacing: "0.14em", padding: `${4 * u}px ${20 * u}px`, marginLeft: 10 * u,
              boxShadow: `0 ${8 * u}px ${24 * u}px rgba(0,0,0,.35)`,
              clipPath: `inset(0 ${((1 - placeIn) * 100).toFixed(2)}% 0 0)` }}>{d.place}</div>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== dt-clock-time
/**
 * An analog clock whose hands spin round and stop on the time (frame 30,
 * sfx_at) with the second hand sweeping on, and the digital time big beside
 * it with AM/PM in a yellow block; weekday, date or place under it.
 */
const DtClockTime: Look = (props) => {
  const { overlay } = props;
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  if (!hasTime(d)) return <DtCleanCard {...props} />;
  const hour = d.hour ?? 12;
  const minute = d.minute ?? 0;
  const stop = 30;
  const q = interpolate(frame, [4, stop], [0, 1], { ...clamp, easing: Easing.bezier(0.22, 1.06, 0.36, 1) });
  const minA = (720 + minute * 6) * q;
  const hourA = ((hour % 12) * 30 + minute * 0.5) * q;
  const secA = frame > stop ? (frame - stop) * 1.2 : 0;
  const D = px(270);
  const R = D / 2;
  const pin = ramp(frame, 0, 14, expoOut);
  const dig = ramp(frame, 10, 14, expoOut);
  const sub = [d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", dateLine(d), d.place || ""].filter(Boolean).join("  ·  ");
  const hand = (angle: number, len: number, w: number, color: string, tail = 0.12) => (
    <line x1={R - Math.sin((angle * Math.PI) / 180) * len * tail} y1={R + Math.cos((angle * Math.PI) / 180) * len * tail}
      x2={R + Math.sin((angle * Math.PI) / 180) * len} y2={R - Math.cos((angle * Math.PI) / 180) * len}
      stroke={color} strokeWidth={w} strokeLinecap="round" />
  );
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="linear-gradient(90deg, rgba(0,0,0,.42) 0%, rgba(0,0,0,.26) 42%, rgba(0,0,0,0) 72%)" />
      <div style={{ position: "absolute", left: 130 * u, top: height * 0.5, display: "flex", alignItems: "center", gap: 44 * u,
        transform: `translateY(-50%) translateX(${((1 - pin) * -40 * u + out * -30 * u).toFixed(2)}px)`,
        background: `linear-gradient(180deg, ${NAVY_2} 0%, ${NAVY} 100%)`, borderRadius: 22 * u, borderTop: `${4 * u}px solid ${YELLOW}`,
        padding: `${30 * u}px ${54 * u}px ${30 * u}px ${34 * u}px`, boxShadow: `0 ${26 * u}px ${70 * u}px rgba(0,0,0,.5)`,
        opacity: pin }}>
        <svg width={D} height={D} style={{ overflow: "visible", transform: `scale(${(0.85 + 0.15 * pin).toFixed(4)}) rotate(${((1 - pin) * -20).toFixed(2)}deg)`,
          filter: `drop-shadow(0 ${8 * u}px ${18 * u}px rgba(0,0,0,.45))` }}>
          <circle cx={R} cy={R} r={R - 5 * u} fill="#F8F7F3" stroke={NAVY} strokeWidth={10 * u} />
          {Array.from({ length: 60 }).map((_, i) => {
            const a = (i * 6 * Math.PI) / 180;
            const major = i % 5 === 0;
            const r1 = R - 18 * u;
            const r0 = r1 - (major ? (i % 15 === 0 ? 22 : 15) : 6) * u;
            return (
              <line key={i} x1={R + Math.sin(a) * r0} y1={R - Math.cos(a) * r0} x2={R + Math.sin(a) * r1} y2={R - Math.cos(a) * r1}
                stroke={major ? NAVY : "#9aa3b2"} strokeWidth={(major ? (i % 15 === 0 ? 5 : 3.5) : 1.6) * u} strokeLinecap="round" />
            );
          })}
          {hand(hourA, R * 0.5, 10 * u, NAVY)}
          {hand(minA, R * 0.74, 6.5 * u, NAVY)}
          {frame > stop - 2 ? hand(secA, R * 0.8, 2.6 * u, "#E0A100", 0.2) : null}
          <circle cx={R} cy={R} r={9 * u} fill={YELLOW} stroke={NAVY} strokeWidth={3 * u} />
        </svg>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 * u }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 16 * u, overflow: "hidden", paddingBottom: 4 * u }}>
            <div style={{ fontFamily: DISPLAY, fontSize: px(140), lineHeight: 0.92, color: "#fff", letterSpacing: "0.02em",
              transform: `translateY(${((1 - dig) * 105).toFixed(2)}%)`, textShadow: "0 6px 24px rgba(0,0,0,.45)",
              fontVariantNumeric: "tabular-nums", paddingTop: "0.04em" }}>{timeStr(d)}</div>
            <div style={{ marginTop: px(18), background: YELLOW, color: NAVY, fontFamily: LABEL, fontWeight: 800, fontSize: px(42),
              lineHeight: 1.1, padding: `${2 * u}px ${12 * u}px`, letterSpacing: "0.04em",
              clipPath: `inset(0 ${((1 - ramp(frame, 18, 10, expoOut)) * 100).toFixed(2)}% 0 0)` }}>{d.ampm}</div>
          </div>
          {sub ? (
            <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: px(34), letterSpacing: "0.18em", color: YELLOW,
              opacity: ramp(frame, 20, 12) }}>{sub}</div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== dt-rec-stamp
/**
 * A camcorder on-screen display: thin viewfinder corners, a blinking red REC
 * dot and a monospace timestamp top-right, "SEP 25 2026  03:45:07 PM", the
 * seconds running. It clicks on at frame 3 (sfx_at) and blinks off at the end.
 */
const DtRecStamp: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  const on = 3;
  const flick = frame < on ? 0 : frame < on + 1 ? 1 : frame < on + 2 ? 0.35 : 1;
  const secs = Math.floor(Math.max(0, frame - on) / 30) % 60;
  const date = d.month !== undefined
    ? [MON3[d.month], d.day !== undefined ? two(d.day) : "", d.year !== undefined ? String(d.year) : ""].filter(Boolean).join(" ")
    : d.year !== undefined ? String(d.year) : "";
  const time = hasTime(d) ? `${two(d.hour ?? 0)}:${two(d.minute ?? 0)}:${two(secs)} ${d.ampm}` : "";
  const line = [date, time].filter(Boolean).join("  ") || str(overlay.text).toUpperCase().slice(0, 30);
  const blink = frame % 30 < 18;
  const size = px(34);
  const inset = 96 * u;
  const arm = 70 * u;
  const thick = Math.max(2, 3 * u);
  const corner = (key: string, pos: React.CSSProperties, bt: boolean, bl: boolean) => (
    <div key={key} style={{ position: "absolute", width: arm, height: arm * 0.7, ...pos,
      borderTop: bt ? `${thick}px solid rgba(255,255,255,.85)` : undefined,
      borderBottom: !bt ? `${thick}px solid rgba(255,255,255,.85)` : undefined,
      borderLeft: bl ? `${thick}px solid rgba(255,255,255,.85)` : undefined,
      borderRight: !bl ? `${thick}px solid rgba(255,255,255,.85)` : undefined }} />
  );
  return (
    <AbsoluteFill style={{ opacity: flick * (1 - out) }}>
      {overlay.fullFrame ? null : (
        <AbsoluteFill style={{ background: "radial-gradient(ellipse 36% 24% at 86% 12%, rgba(0,0,0,.42) 0%, rgba(0,0,0,.2) 60%, rgba(0,0,0,0) 100%)" }} />
      )}
      <AbsoluteFill style={{ filter: "drop-shadow(0 1px 3px rgba(0,0,0,.8))" }}>
      {corner("tl", { left: inset, top: inset }, true, true)}
      {corner("tr", { right: inset, top: inset }, true, false)}
      {corner("bl", { left: inset, bottom: inset }, false, true)}
      {corner("br", { right: inset, bottom: inset }, false, false)}
      <div style={{ position: "absolute", right: inset + 34 * u, top: inset + 26 * u, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 10 * u, fontFamily: MONO, fontWeight: 700, fontSize: size, color: "#fff",
        letterSpacing: "0.04em", whiteSpace: "pre" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 * u }}>
          <div style={{ width: size * 0.62, height: size * 0.62, borderRadius: "50%", background: "#FF2D2D", opacity: blink ? 1 : 0.12,
            boxShadow: blink ? "0 0 12px rgba(255,45,45,.8)" : undefined }} />
          <div>REC</div>
        </div>
        <div>{line}</div>
        {d.place ? <div style={{ fontSize: px(28), color: "rgba(255,255,255,.85)" }}>{d.place}</div> : null}
      </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== dt-date-slam
/**
 * A full-width band across the middle: a yellow wipe, then navy over it; the
 * month, day and year slam down one after another with a small shake (the
 * day lands on frame 18, sfx_at). The band wipes off to the right at the end.
 */
const DtDateSlam: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  type Tok = { t: string; font: "label" | "display"; color: string; size: number; outline?: boolean };
  const toks: Tok[] = [];
  if (d.month !== undefined) toks.push({ t: MONTHS[d.month], font: "label", color: YELLOW, size: 92 });
  if (d.day !== undefined) toks.push({ t: String(d.day), font: "display", color: "#fff", size: 140 });
  if (d.year !== undefined) toks.push({ t: String(d.year), font: "display", color: "#fff", size: 140, outline: d.day !== undefined });
  if (hasTime(d)) {
    toks.push({ t: timeStr(d), font: "display", color: "#fff", size: 140 });
    toks.push({ t: d.ampm || "", font: "label", color: YELLOW, size: 64 });
  }
  if (!toks.length) toks.push({ t: str(overlay.text).toUpperCase().slice(0, 28) || "—", font: "label", color: "#fff", size: 92 });
  const gap = 34 * u;
  const natural = toks.reduce((a, t) => a + labelW(t.t, px(t.size), t.font, t.font === "label" ? 0.04 : 0.02), 0) + gap * (toks.length - 1);
  const fit = Math.min(1, (width * 0.84) / Math.max(1, natural));
  const starts = toks.map((_, i) => 8 + i * 4);
  let sx = 0;
  let sy = 0;
  for (const s of starts) {
    const t = frame - (s + 5);
    if (t >= 0 && t < 12) {
      const amp = 8 * u * Math.exp(-t / 3.2);
      sx += Math.sin(t * 2.4 + s) * amp;
      sy += Math.cos(t * 3.1 + s) * amp * 0.6;
    }
  }
  const w1 = ramp(frame, 0, 8, expoOut);
  const w2 = ramp(frame, 3, 9, expoOut);
  const bandH = px(260);
  const sub = [d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", d.place || ""].filter(Boolean).join("  ·  ");
  return (
    <AbsoluteFill style={{ clipPath: `inset(0 0 0 ${(out * 100).toFixed(2)}%)` }}>
      <Shade ov={overlay} out={out} background="rgba(0,0,0,.28)" />
      <div style={{ position: "absolute", left: 0, right: 0, top: height / 2 - bandH / 2, height: bandH,
        transform: `translate(${sx.toFixed(2)}px, ${sy.toFixed(2)}px)` }}>
        <div style={{ position: "absolute", inset: 0, background: YELLOW, clipPath: `inset(0 ${((1 - w1) * 100).toFixed(2)}% 0 0)` }} />
        <div style={{ position: "absolute", left: 0, right: 0, top: 9 * u, bottom: 9 * u, background: NAVY,
          clipPath: `inset(0 ${((1 - w2) * 100).toFixed(2)}% 0 0)`, boxShadow: "inset 0 0 80px rgba(0,0,0,.35)" }} />
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap, transform: `scale(${fit.toFixed(4)})` }}>
            {toks.map((t, i) => {
              const s = starts[i];
              const sc = interpolate(frame, [s, s + 5, s + 9], [1.9, 0.97, 1], { ...clamp, easing: Easing.bezier(0.5, 0, 0.75, 0) });
              const o = interpolate(frame, [s, s + 2], [0, 1], clamp);
              const blur = interpolate(frame, [s, s + 5], [10, 0], clamp);
              return (
                <div key={i} style={{ fontFamily: t.font === "label" ? LABEL : DISPLAY, fontWeight: t.font === "label" ? 800 : 400,
                  fontSize: px(t.size), lineHeight: 1, letterSpacing: t.font === "label" ? "0.04em" : "0.02em",
                  color: t.outline ? "transparent" : t.color, WebkitTextStroke: t.outline ? `${Math.max(2, 3 * u).toFixed(2)}px ${t.color}` : undefined,
                  opacity: o, transform: `scale(${sc.toFixed(4)})`, filter: blur > 0.1 ? `blur(${blur.toFixed(2)}px)` : undefined,
                  textShadow: "0 6px 20px rgba(0,0,0,.35)", paddingTop: t.font === "display" ? "0.05em" : 0 }}>{t.t}</div>
              );
            })}
          </div>
          {sub ? (
            <div style={{ marginTop: 6 * u, fontFamily: LABEL, fontWeight: 700, fontSize: px(32), letterSpacing: "0.3em",
              color: "rgba(255,255,255,.88)", opacity: ramp(frame, 24, 10) }}>{sub}</div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== dt-timeline-tick
/**
 * A thin month ruler (a year ruler when only the year is known) slides in
 * from the right and decelerates; a marker drops onto the exact date (frame
 * 22, sfx_at) with its label card, and the month's tick label turns yellow.
 */
const DtTimelineTick: Look = (props) => {
  const { overlay } = props;
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const d = parseDT(overlay.text, overlay.label, overlay.value);
  if (!hasDate(d)) return <DtCleanCard {...props} />;
  const byMonth = d.month !== undefined;
  const S = byMonth ? 230 * u : 280 * u;
  const y0 = height * 0.7;
  const slide = ramp(frame, 0, 24, expoOut);
  const offset = (1 - slide) * 760 * u + out * -200 * u;
  const cx = width / 2;
  // Target position (in ruler units from the target period's start).
  let tIdx = 0;
  let frac = 0.5;
  const labels: { i: number; text: string; sub?: string }[] = [];
  if (byMonth) {
    const yr = d.year ?? 2026;
    tIdx = yr * 12 + (d.month as number);
    frac = d.day !== undefined ? (d.day - 0.5) / monthDays(yr, d.month as number) : 0.5;
    for (let i = tIdx - 6; i <= tIdx + 6; i++) {
      const m = ((i % 12) + 12) % 12;
      labels.push({ i, text: MON3[m], sub: m === 0 ? String(Math.floor(i / 12)) : undefined });
    }
  } else {
    tIdx = d.year as number;
    for (let i = tIdx - 5; i <= tIdx + 5; i++) labels.push({ i, text: String(i) });
  }
  const xOf = (i: number, f = 0) => cx + (i - tIdx + f - frac) * S + offset;
  const minor = byMonth ? 4 : 4;
  const drop = ramp(frame, 12, 10, backOut);
  const landed = frame >= 22;
  const cardIn = ramp(frame, 18, 12, expoOut);
  const date = dateLine(d);
  const sub = [d.weekday !== undefined ? WEEKDAYS[d.weekday] : "", d.place || ""].filter(Boolean).join("  ·  ");
  const stem = 120 * u;
  const lineColor = "rgba(255,255,255,.82)";
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="linear-gradient(180deg, rgba(0,0,0,0) 40%, rgba(0,0,0,.35) 62%, rgba(0,0,0,.5) 80%, rgba(0,0,0,.3) 100%)" />
      <AbsoluteFill style={{ WebkitMaskImage: "linear-gradient(90deg, transparent 3%, #000 16%, #000 84%, transparent 97%)",
        maskImage: "linear-gradient(90deg, transparent 3%, #000 16%, #000 84%, transparent 97%)" }}>
        {overlay.fullFrame ? null : (
          <div style={{ position: "absolute", left: 0, right: 0, top: y0 - 46 * u, height: 120 * u, opacity: ramp(frame, 0, 10),
            background: "linear-gradient(180deg, rgba(8,14,26,0) 0%, rgba(8,14,26,.62) 30%, rgba(8,14,26,.62) 72%, rgba(8,14,26,0) 100%)" }} />
        )}
        <div style={{ position: "absolute", left: 0, right: 0, top: y0, height: Math.max(2, 3 * u), background: lineColor,
          opacity: ramp(frame, 0, 8) }} />
        {labels.map((l) => {
          const x = xOf(l.i);
          const isT = l.i === tIdx;
          return (
            <React.Fragment key={l.i}>
              <div style={{ position: "absolute", left: x - 1.5 * u, top: y0 - 16 * u, width: Math.max(2, 3 * u), height: 32 * u,
                background: lineColor }} />
              {Array.from({ length: minor - 1 }).map((_, j) => (
                <div key={j} style={{ position: "absolute", left: xOf(l.i, (j + 1) / minor) - 1 * u, top: y0 - 8 * u,
                  width: Math.max(1, 2 * u), height: 16 * u, background: "rgba(255,255,255,.5)" }} />
              ))}
              <div style={{ position: "absolute", left: x + 10 * u, top: y0 + 18 * u, fontFamily: LABEL, fontWeight: 700,
                fontSize: px(30), letterSpacing: "0.1em", color: isT && landed ? YELLOW : "rgba(255,255,255,.78)",
                textShadow: "0 2px 8px rgba(0,0,0,.6)" }}>
                {l.text}
                {l.sub ? <span style={{ marginLeft: 10 * u, color: "rgba(255,255,255,.55)" }}>{l.sub}</span> : null}
              </div>
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
      <div style={{ position: "absolute", left: cx, top: y0, opacity: ramp(frame, 12, 4, Easing.linear),
        transform: `translateY(${((1 - drop) * -90 * u).toFixed(2)}px)` }}>
        <div style={{ position: "absolute", left: -1.5 * u, top: -stem, width: Math.max(2, 3 * u), height: stem, background: YELLOW }} />
        <div style={{ position: "absolute", left: -13 * u, top: -13 * u, width: 26 * u, height: 26 * u, borderRadius: "50%",
          background: YELLOW, border: `${4 * u}px solid ${NAVY}`, boxSizing: "border-box",
          boxShadow: landed ? `0 0 0 ${(ramp(frame, 22, 16) * 26 * u).toFixed(2)}px rgba(255,200,61,${(0.4 * (1 - ramp(frame, 22, 16))).toFixed(3)})` : undefined }} />
        <div style={{ position: "absolute", left: 0, bottom: stem - 4 * u, transform: `translateX(-50%) translateY(${((1 - cardIn) * 16 * u).toFixed(2)}px)`,
          opacity: cardIn, background: NAVY, borderTop: `${4 * u}px solid ${YELLOW}`, padding: `${10 * u}px ${24 * u}px ${12 * u}px`,
          boxShadow: `0 ${12 * u}px ${30 * u}px rgba(0,0,0,.45)`, whiteSpace: "pre", textAlign: "center" }}>
          <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(44), letterSpacing: "0.05em", color: "#fff", lineHeight: 1.1 }}>{date}</div>
          {sub ? <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: px(28), letterSpacing: "0.18em", color: YELLOW }}>{sub}</div> : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== dt-countdown-days
const WORDS: Record<string, number> = {
  A: 1, AN: 1, ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5, SIX: 6, SEVEN: 7, EIGHT: 8, NINE: 9, TEN: 10, ELEVEN: 11,
  TWELVE: 12, THIRTEEN: 13, FOURTEEN: 14, FIFTEEN: 15, TWENTY: 20, THIRTY: 30, FORTY: 40, FORTY_EIGHT: 48, FIFTY: 50,
  SEVENTY_TWO: 72, HUNDRED: 100,
};
type Span = { n: number; unit: string; tail: string };
/** "3 DAYS LATER", "48 HOURS", "TWO WEEKS EARLIER", "72-HOUR" -> number, unit, tail. */
export const parseSpan = (textIn: unknown): Span | null => {
  const s = str(textIn).toUpperCase().replace(/FORTY[- ]EIGHT/g, "FORTY_EIGHT").replace(/SEVENTY[- ]TWO/g, "SEVENTY_TWO");
  const m = /(\d+(?:[.,]\d+)?|[A-Z_]+)\s*-?\s*(SECONDS?|MINUTES?|HOURS?|DAYS?|NIGHTS?|WEEKS?|MONTHS?|YEARS?|DECADES?)\b\s*(LATER|EARLIER|BEFORE|AFTER|AGO|ON|OF\s+[A-Z]+)?/.exec(s);
  if (!m) return null;
  const n = /^\d/.test(m[1]) ? Number(m[1].replace(",", ".")) : WORDS[m[1]];
  if (!Number.isFinite(n) || n <= 0 || n > 100000) return null;
  let unit = m[2];
  if (n !== 1 && !unit.endsWith("S")) unit = `${unit}S`;
  if (n === 1 && unit.endsWith("S")) unit = unit.slice(0, -1);
  return { n, unit, tail: (m[3] || "").slice(0, 16) };
};

/**
 * "3 DAYS LATER" / "48 HOURS": the number counts up in yellow, the unit and
 * the word after it stacked beside it in white, a time bar filling under
 * them with one tick per unit (up to 12). Anything else falls back to the
 * date card.
 */
const DtCountdownDays: Look = (props) => {
  const { overlay } = props;
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const span = parseSpan(overlay.text);
  if (!span) return <DtCleanCard {...props} />;
  const whole = Number.isInteger(span.n);
  const shown = whole ? String(countTo(frame, 6, 26, 0, span.n)) : String(span.n);
  const final = String(span.n);
  const pin = ramp(frame, 0, 16, expoOut);
  const bar = ramp(frame, 8, 24, inOut);
  const ticks = whole ? Math.min(12, Math.max(2, span.n)) : 4;
  const barW = 560 * u;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 55% 50% at 50% 50%, rgba(0,0,0,.45) 0%, rgba(0,0,0,.3) 70%, rgba(0,0,0,.22) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", opacity: pin,
        transform: `translateY(${((1 - pin) * 50 * u + out * 20 * u).toFixed(2)}px) scale(${(0.96 + 0.04 * pin).toFixed(4)})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", background: `linear-gradient(180deg, ${NAVY_2} 0%, ${NAVY} 100%)`,
          borderRadius: 22 * u, borderTop: `${4 * u}px solid ${YELLOW}`, padding: `${34 * u}px ${60 * u}px ${40 * u}px`,
          boxShadow: `0 ${26 * u}px ${70 * u}px rgba(0,0,0,.5)` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 30 * u }}>
          <div style={{ fontFamily: DISPLAY, fontSize: px(140), lineHeight: 0.9, color: YELLOW, fontVariantNumeric: "tabular-nums",
            minWidth: `${(final.length * 0.43).toFixed(2)}em`, textAlign: "right", paddingTop: "0.05em",
            textShadow: "0 8px 30px rgba(0,0,0,.45)" }}>{shown}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 * u }}>
            <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(72), lineHeight: 1, color: "#fff", letterSpacing: "0.06em",
              textShadow: "0 6px 24px rgba(0,0,0,.45)" }}>{span.unit}</div>
            {span.tail ? (
              <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: px(42), lineHeight: 1.1, color: "rgba(255,255,255,.86)",
                letterSpacing: "0.32em", opacity: ramp(frame, 10, 12) }}>{span.tail}</div>
            ) : null}
          </div>
        </div>
        <div style={{ position: "relative", width: barW, height: Math.max(3, 5 * u), marginTop: 28 * u, background: "rgba(255,255,255,.22)",
          borderRadius: 3 * u }}>
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(bar * 100).toFixed(2)}%`, background: YELLOW,
            borderRadius: 3 * u }} />
          {Array.from({ length: ticks + 1 }).map((_, i) => (
            <div key={i} style={{ position: "absolute", left: (barW * i) / ticks - 1 * u, top: -8 * u, width: Math.max(2, 2 * u),
              height: 20 * u, background: bar >= i / ticks ? YELLOW : "rgba(255,255,255,.35)" }} />
          ))}
        </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== bold dates (shared)
const WD3 = WEEKDAYS.map((w) => w.slice(0, 3));
type Range = { a: DT; b: DT };

const dayTok = (t: string): number => {
  const m = /^(\d{1,2})(ST|ND|RD|TH)?$/.exec(t || "");
  const d = m ? Number(m[1]) : NaN;
  return d >= 1 && d <= 31 ? d : NaN;
};
/** "time" for a clock time alone, "cal" for anything on the calendar, "" for nothing. */
const kindOf = (d: DT): "time" | "cal" | "" =>
  d.month !== undefined || d.year !== undefined || d.weekday !== undefined ? "cal" : hasTime(d) ? "time" : "";
const finishRange = (a: DT, b: DT): Range => {
  for (const x of [a, b]) {
    if (x.year !== undefined && x.month !== undefined && x.day !== undefined) {
      x.day = Math.min(x.day, monthDays(x.year, x.month));
      if (x.weekday === undefined) x.weekday = weekdayOf(x.year, x.month, x.day);
    }
  }
  return { a, b };
};

/**
 * The two ends of a range in the text, else null: "TUESDAY → THURSDAY",
 * "Monday through Friday", "TUE-THU", "Sept 28 - Oct 2", "SEPTEMBER 28-30,
 * 2026", "28-30 September", "1983 to 2026", "3 PM - 5 PM". A date and a time
 * ("SEPT 25 – 3:45 PM") is not a range. Never throws.
 */
export const parseRange = (textIn: unknown): Range | null => {
  const raw = ` ${str(textIn).toUpperCase().replace(/[’']/g, "")} `;
  if (!raw.trim()) return null;
  const yearIn = (s: string): number | undefined => {
    const m = /\b(1\d{3}|2\d{3})\b/.exec(s);
    return m ? Number(m[1]) : undefined;
  };
  const SEP = "(?:-|–|—|→|->|\\bTO\\b|\\bTHROUGH\\b|\\bTHRU\\b|\\bUNTIL\\b|\\bTILL?\\b|\\bAND\\b)";
  // Days of one month: "SEPT 28-30", "SEPTEMBER 28 TO 30, 2026".
  let m = new RegExp(`\\b([A-Z]{3,9})\\.?\\s+(\\d{1,2})(?:ST|ND|RD|TH)?\\s*${SEP}\\s*(\\d{1,2})(?:ST|ND|RD|TH)?\\b(?!\\s*[:/.]\\d|\\s*[AP]\\.?M\\b)`).exec(raw);
  if (m && monthOf(m[1]) >= 0) {
    const mo = monthOf(m[1]);
    const d1 = Number(m[2]), d2 = Number(m[3]);
    if (d1 >= 1 && d1 <= 31 && d2 >= 1 && d2 <= 31 && d1 !== d2) {
      const y = yearIn(raw);
      return finishRange({ month: mo, day: d1, year: y }, { month: mo, day: d2, year: y });
    }
  }
  // "28-30 SEPTEMBER".
  m = /\b(\d{1,2})(?:ST|ND|RD|TH)?\s*(?:-|–|—)\s*(\d{1,2})(?:ST|ND|RD|TH)?\s+([A-Z]{3,9})\b/.exec(raw);
  if (m && monthOf(m[3]) >= 0 && Number(m[1]) !== Number(m[2]) && Number(m[1]) <= 31 && Number(m[2]) <= 31) {
    const mo = monthOf(m[3]);
    const y = yearIn(raw);
    return finishRange({ month: mo, day: Number(m[1]), year: y }, { month: mo, day: Number(m[2]), year: y });
  }
  // Two years: "1983-2026", "1983 TO 2026".
  m = new RegExp(`\\b(1\\d{3}|2\\d{3})\\s*${SEP}\\s*(1\\d{3}|2\\d{3})\\b`).exec(raw);
  if (m && m[1] !== m[2]) return { a: { year: Number(m[1]) }, b: { year: Number(m[2]) } };
  // Anything else around an arrow, a spaced dash, a dash between weekdays or a word.
  const s = raw
    .replace(/\b([A-Z]{3,9})\.?-([A-Z]{3,9})\b/g, (all, x: string, y: string) => (weekdayTok(x) >= 0 && weekdayTok(y) >= 0 ? `${x} → ${y}` : all))
    .replace(/\s*(?:→|->|=>|–|—)\s*/g, " → ")
    .replace(/\s+-\s+/g, " → ")
    .replace(/\b(?:TO|THROUGH|THRU|UNTIL|TILL|TIL)\b/g, " → ")
    .replace(/^\s*FROM\s+/, " ");
  const parts = s.split("→").map((p) => p.trim()).filter(Boolean);
  if (parts.length !== 2) return null;
  const a = parseDT(parts[0]);
  const b = parseDT(parts[1]);
  if (b.month === undefined && b.day === undefined && a.month !== undefined) {
    const dd = dayTok(parts[1].split(/[^A-Z0-9]+/).filter(Boolean)[0] || "");
    if (Number.isFinite(dd)) b.day = dd;
  }
  if (b.month === undefined && b.day !== undefined && a.month !== undefined) b.month = a.month;
  if (b.year === undefined && a.year !== undefined && b.month !== undefined) b.year = a.year;
  if (a.year === undefined && b.year !== undefined && a.month !== undefined) a.year = b.year;
  const ka = kindOf(a), kb = kindOf(b);
  if (!ka || ka !== kb) return null;
  if (JSON.stringify(a) === JSON.stringify(b)) return null;
  return finishRange(a, b);
};

const joinSub = (...xs: (string | undefined)[]) => xs.filter((x) => !!x).join("  ·  ");
const clockOf = (d: DT) => (hasTime(d) ? `${timeStr(d)} ${d.ampm}` : "");
/** The shortest clear name of one end of a range. */
const endName = (d: DT): string => {
  if (d.month !== undefined && d.day !== undefined) return `${MON_AP[d.month]} ${d.day}`;
  if (d.month !== undefined) return d.year !== undefined ? `${MON_AP[d.month]} ${d.year}` : MONTHS[d.month];
  if (d.year !== undefined) return String(d.year);
  if (d.weekday !== undefined) return WEEKDAYS[d.weekday];
  return clockOf(d);
};
const placeOf = (ov: Overlay, d: DT): string => d.place || str(ov.subtitle).toUpperCase().slice(0, 40);
const yearOf = (...ds: DT[]): string => {
  const y = ds.find((x) => x.year !== undefined)?.year;
  return y !== undefined ? String(y) : "";
};

/** Bebas Neue at `px`: advance widths in em by glyph class (a little generous, so nothing clips). */
const displayW = (t: string, px: number, track = 0.01): number => {
  let w = 0;
  for (const c of t) {
    w += (c === " " ? 0.19 : /[I]/.test(c) ? 0.2 : /[J1]/.test(c) ? 0.3 : /[MW]/.test(c) ? 0.58 : /[-]/.test(c) ? 0.28
      : /[:.,]/.test(c) ? 0.18 : 0.415) + track;
  }
  return w * px;
};
const ARROW_EM = 0.62;
const GAP_EM = 0.2;
/** Width of a headline line of pieces joined by arrows, at `px`. */
const piecesW = (parts: string[], px: number): number =>
  parts.reduce((a, p) => a + displayW(p, px), 0) + Math.max(0, parts.length - 1) * (ARROW_EM + 2 * GAP_EM) * px;

/** A bold geometric arrow between the two ends of a range, in the text's colour. */
const RangeArrow: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size * ARROW_EM} height={size * 0.46} viewBox="0 0 62 46" style={{ display: "block", overflow: "visible", flex: "none",
    marginTop: size * 0.02 }}>
    <path d="M1 23 H42" stroke={color} strokeWidth={8.5} />
    <path d="M33 5.5 L61 23 L33 40.5 Z" fill={color} />
  </svg>
);

/** One headline line in Bebas Neue: the pieces with an arrow between (a range) or just the one. */
const Pieces: React.FC<{ parts: string[]; size: number; color: string; shadow?: string }> = ({ parts, size, color, shadow }) => (
  <div style={{ display: "flex", alignItems: "center", gap: size * GAP_EM }}>
    {parts.map((p, i) => (
      <React.Fragment key={i}>
        {i ? <RangeArrow size={size} color={color} /> : null}
        <div style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 0.84, paddingTop: "0.08em", letterSpacing: "0.01em", color,
          whiteSpace: "nowrap", textShadow: shadow }}>{p}</div>
      </React.Fragment>
    ))}
  </div>
);

/** A line sliding up out of its mask as p goes 0 -> 1, and down out of it as out goes 0 -> 1. */
const MaskRise: React.FC<{ p: number; out: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ p, out, children, style }) => (
  <div style={{ overflow: "hidden", padding: "0.1em 0.2em 0.12em", margin: "-0.1em -0.2em -0.12em", ...style }}>
    <div style={{ transform: `translateY(${((1 - p) * 110 + out * 110).toFixed(2)}%)`, opacity: p > 0.002 ? 1 : 0 }}>{children}</div>
  </div>
);

/** Ink or white, whichever reads on `bg` (the block colour). */
const onColor = (bg: string): string => {
  const h = (bg || "").replace("#", "");
  const n = /^[0-9a-f]{6}$/i.test(h) ? parseInt(h, 16) : 0xffc83d;
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 150 ? INK : "#fff";
};
/** The yellow of the date looks, or the theme's colour when one is set on the overlay. */
const blockColour = (ov: Overlay, accent: string) => (ov.theme ? accent : YELLOW);

/** A decaying camera shake after a hit at frame `at`: [x px, y px, degrees]. */
const shakeAt = (frame: number, at: number, amp: number): [number, number, number] => {
  const t = frame - at;
  if (t < 0 || t > 18) return [0, 0, 0];
  const e = Math.exp(-t / 3.4);
  return [Math.sin(t * 2.6 + 0.4) * amp * e, Math.cos(t * 3.3) * amp * 0.7 * e, Math.sin(t * 2.1) * 0.35 * e];
};

// ================================================================== dt-bold-headline
type Headline = { top: string[]; main: string[][]; sub: string };
/** What the headline says: a small top line (the weekday), the date on the block, a line under it (year, time, place). */
const headlineOf = (ov: Overlay): Headline => {
  const d = parseDT(ov.text, ov.label, ov.value);
  const place = placeOf(ov, d);
  const rg = parseRange(ov.text);
  if (rg) {
    const { a, b } = rg;
    const wds = a.weekday !== undefined && b.weekday !== undefined ? [WEEKDAYS[a.weekday], WEEKDAYS[b.weekday]] : [];
    if (a.month !== undefined && b.month !== undefined && a.day !== undefined && b.day !== undefined) {
      const same = a.month === b.month && a.year === b.year;
      return {
        top: wds,
        main: [same ? [`${MONTHS[a.month]} ${a.day}-${b.day}`] : [`${MON_AP[a.month]} ${a.day}`, `${MON_AP[b.month]} ${b.day}`]],
        sub: joinSub(yearOf(b, a), place),
      };
    }
    if (kindOf(a) === "time") return { top: d.weekday !== undefined ? [WEEKDAYS[d.weekday]] : [], main: [[clockOf(a), clockOf(b)]], sub: place };
    if (a.month === undefined && b.month === undefined && a.year === undefined && b.year === undefined && wds.length) {
      return { top: [], main: [wds], sub: joinSub(clockOf(a), place) };
    }
    return { top: [], main: [[endName(a), endName(b)]], sub: place };
  }
  const wd = d.weekday !== undefined ? WEEKDAYS[d.weekday] : "";
  const year = d.year !== undefined ? String(d.year) : "";
  if (d.month !== undefined && d.day !== undefined) return { top: wd ? [wd] : [], main: [[`${MONTHS[d.month]} ${d.day}`]], sub: joinSub(year, clockOf(d), place) };
  if (d.month !== undefined) return { top: wd ? [wd] : [], main: [[year ? `${MONTHS[d.month]} ${year}` : MONTHS[d.month]]], sub: joinSub(clockOf(d), place) };
  if (d.year !== undefined) return { top: wd ? [wd] : [], main: [[year]], sub: joinSub(clockOf(d), place) };
  // A time is the news when there is no calendar date: "3:45 PM" on the block, the weekday over it.
  if (hasTime(d)) return { top: wd ? [wd] : [], main: [[clockOf(d)]], sub: place };
  if (wd) return { top: [], main: [[wd]], sub: place };
  // Words ("TOMORROW NIGHT", "THIS WEEKEND"): the words themselves, up to two stacked lines.
  const words = str(ov.text).toUpperCase().slice(0, 48);
  const ls = words.length > 16 ? lines(words, Math.max(10, Math.ceil(words.length / 2) + 2)).slice(0, 2) : [words || "—"];
  return { top: [], main: ls.map((l) => [l]), sub: place };
};

/**
 * The date as a huge bold headline: the date slams onto a strong colour
 * block (yellow; the theme's colour when set), falling from above the frame
 * with a motion blur and landing on frame 11 (sfx_at) with a small camera
 * shake; the weekday rises above it and the year / time / place line under
 * it. Ranges read "TUESDAY → THURSDAY", "SEPT 28 → OCT 2" or "SEPTEMBER
 * 28-30". At the exit the block wipes away and the lines drop out.
 */
const DtBoldHeadline: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, durationInFrames: dur } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const plan = headlineOf(overlay);
  const block = blockColour(overlay, accent);
  const ink = onColor(block);
  const maxW = 1480 * u;
  const pad = 0.3;
  const mainSize = Math.min(px(214), ...plan.main.map((l) => maxW / Math.max(1, piecesW(l, 1) + 2 * pad)));
  const topSize = plan.top.length ? Math.min(mainSize * 0.64, px(140), maxW / Math.max(1, piecesW(plan.top, 1))) : 0;
  const SLAM = 11;
  const fall = interpolate(frame, [3, SLAM], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const sc = frame < SLAM ? 1.6 - 0.6 * fall : interpolate(frame, [SLAM, SLAM + 3, SLAM + 10], [1, 0.972, 1], { ...clamp, easing: inOut });
  const blur = frame < SLAM ? 9 * u * fall * fall : 0;
  const rotB = frame < SLAM ? -6 + 4.4 * fall : -1.6;
  const [sx, sy, sr] = shakeAt(frame, SLAM, 12 * u);
  const hold = interpolate(frame, [SLAM, Math.max(SLAM + 1, dur)], [1, 1.035], clamp);
  const topIn = ramp(frame, SLAM + 1, 14);
  const subIn = ramp(frame, SLAM + 7, 14);
  const lineOut = ramp(frame, dur - EXIT - 2, EXIT - 2, expoIn);
  const wipe = ramp(frame, dur - EXIT, EXIT - 1, expoIn);
  const shadow = "0 6px 30px rgba(0,0,0,.55)";
  return (
    <AbsoluteFill>
      <Shade ov={overlay} out={out}
        background="radial-gradient(ellipse 72% 64% at 50% 50%, rgba(0,0,0,.62) 0%, rgba(0,0,0,.46) 60%, rgba(0,0,0,.34) 100%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center",
        transform: `translate(${sx.toFixed(2)}px, ${sy.toFixed(2)}px) rotate(${sr.toFixed(3)}deg) scale(${hold.toFixed(4)})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {plan.top.length ? (
            <MaskRise p={topIn} out={lineOut} style={{ marginBottom: mainSize * 0.1 }}>
              <Pieces parts={plan.top} size={topSize} color="#fff" shadow={shadow} />
            </MaskRise>
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: mainSize * 0.08,
            transform: `rotate(${rotB.toFixed(3)}deg) scale(${sc.toFixed(4)})`, opacity: ramp(frame, 3, 2, Easing.linear),
            filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined,
            clipPath: `inset(-30% -30% -30% ${(wipe * 100).toFixed(2)}%)` }}>
            {plan.main.map((l, i) => (
              <div key={i} style={{ background: block, padding: `${mainSize * 0.07}px ${mainSize * pad}px ${mainSize * 0.03}px`,
                boxShadow: `0 ${22 * u}px ${56 * u}px rgba(0,0,0,.45), 0 ${4 * u}px ${10 * u}px rgba(0,0,0,.3)` }}>
                <Pieces parts={l} size={mainSize} color={ink} />
              </div>
            ))}
          </div>
          {plan.sub ? (
            <MaskRise p={subIn} out={lineOut} style={{ marginTop: 30 * u }}>
              <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(42), letterSpacing: "0.26em", paddingLeft: "0.26em",
                color: "rgba(255,255,255,.95)", textShadow: "0 3px 16px rgba(0,0,0,.7)", whiteSpace: "nowrap" }}>{plan.sub}</div>
            </MaskRise>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== dt-big-stack
type StackPlan = { big: string; bar: string; small: string };
/** The stack: the most specific part huge (the day), the next in the bar (the month), the rest small. */
const stackOf = (ov: Overlay): StackPlan => {
  const d = parseDT(ov.text, ov.label, ov.value);
  const place = placeOf(ov, d);
  const rg = parseRange(ov.text);
  if (rg) {
    const { a, b } = rg;
    const wdr = a.weekday !== undefined && b.weekday !== undefined ? `${WD3[a.weekday]} - ${WD3[b.weekday]}` : "";
    if (a.month !== undefined && b.month !== undefined && a.day !== undefined && b.day !== undefined) {
      const bar = a.month === b.month ? MONTHS[a.month] : `${MON3[a.month]} - ${MON3[b.month]}`;
      return { big: `${a.day}-${b.day}`, bar, small: joinSub(wdr, yearOf(b, a), place) };
    }
    if (kindOf(a) === "time") return { big: timeStr(a), bar: `TO ${clockOf(b)}`, small: joinSub(a.ampm, place) };
    if (a.year !== undefined && b.year !== undefined && a.month === undefined && b.month === undefined) {
      return { big: String(a.year), bar: `TO ${b.year}`, small: place };
    }
    if (a.weekday !== undefined && b.weekday !== undefined && a.month === undefined && b.month === undefined) {
      return { big: `${WD3[a.weekday]}-${WD3[b.weekday]}`, bar: place || "", small: joinSub(clockOf(a)) };
    }
    return { big: endName(a), bar: `TO ${endName(b)}`, small: place };
  }
  const wd = d.weekday !== undefined ? WEEKDAYS[d.weekday] : "";
  const year = d.year !== undefined ? String(d.year) : "";
  if (d.month !== undefined && d.day !== undefined) return { big: String(d.day), bar: MONTHS[d.month], small: joinSub(wd, year, clockOf(d), place) };
  if (d.month !== undefined) return { big: MONTHS[d.month], bar: year, small: joinSub(wd, clockOf(d), place) };
  if (d.year !== undefined) return { big: year, bar: place, small: joinSub(wd, clockOf(d)) };
  if (wd) return { big: wd, bar: clockOf(d), small: place };
  if (hasTime(d)) return { big: timeStr(d), bar: d.ampm || "", small: place };
  return { big: str(ov.text).toUpperCase().slice(0, 18) || "—", bar: "", small: place };
};

/**
 * Stacked bold typography, left of centre: the day number huge, the month
 * in a solid colour bar the width of the stack, the weekday / year / place
 * small and letter-spaced under it. The stack punches in from larger with a
 * motion blur and lands on frame 8 (sfx_at) with a small bump; the bar wipes
 * open behind it; at the exit the bar wipes shut and the stack slides off.
 */
const DtBigStack: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, durationInFrames: dur } = useVideoConfig();
  const px = usePx();
  const u = width / 1920;
  const out = useOut();
  const plan = stackOf(overlay);
  const block = blockColour(overlay, accent);
  const ink = onColor(block);
  const barSize = px(plan.bar.length > 14 ? 62 : 78);
  // The number as wide as the month bar where it can be (a lockup), 330-440 px, never wider than 860 px.
  const barW = plan.bar ? plan.bar.length * barSize * 0.6 + barSize * 0.6 : 0;
  const bigW1 = Math.max(0.5, displayW(plan.big, 1));
  const bigSize = Math.min((860 * u) / bigW1, Math.max(px(330), Math.min(px(440), barW / bigW1)));
  const HIT = 8;
  const pin = ramp(frame, 0, HIT, Easing.bezier(0.3, 0.6, 0.35, 1));
  const sc = frame < HIT ? 1.34 - 0.34 * pin : interpolate(frame, [HIT, HIT + 3, HIT + 9], [1, 0.978, 1], { ...clamp, easing: inOut });
  const blur = frame < HIT ? 10 * u * (1 - pin) : 0;
  const bar = ramp(frame, 5, 10, expoOut) * (1 - ramp(frame, dur - EXIT - 2, 8, expoIn));
  const smallIn = ramp(frame, HIT + 4, 14);
  const hold = interpolate(frame, [HIT, Math.max(HIT + 1, dur)], [1, 1.03], clamp);
  const leave = ramp(frame, dur - EXIT + 2, EXIT - 2, expoIn);
  return (
    <AbsoluteFill>
      <Shade ov={overlay} out={out}
        background="linear-gradient(90deg, rgba(0,0,0,.7) 0%, rgba(0,0,0,.52) 34%, rgba(0,0,0,.18) 64%, rgba(0,0,0,.04) 86%)" />
      <div style={{ position: "absolute", left: 150 * u, top: "50%", opacity: ramp(frame, 0, 3, Easing.linear) * (1 - leave),
        transform: `translateY(-50%) translateX(${(-leave * 60 * u).toFixed(2)}px) scale(${(sc * hold).toFixed(4)})`, transformOrigin: "0% 50%",
        filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined }}>
        <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "stretch" }}>
          <div style={{ fontFamily: DISPLAY, fontSize: bigSize, lineHeight: 0.8, paddingTop: "0.075em", marginBottom: bigSize * 0.035,
            marginLeft: "-0.03em", letterSpacing: "0.005em", color: "#fff", whiteSpace: "nowrap",
            textShadow: "0 10px 40px rgba(0,0,0,.45)" }}>{plan.big}</div>
          {plan.bar ? (
            <div style={{ background: block, color: ink, fontFamily: LABEL, fontWeight: 800, fontSize: barSize, lineHeight: 1,
              letterSpacing: "0.07em", padding: `${barSize * 0.16}px ${barSize * 0.3}px ${barSize * 0.1}px`, whiteSpace: "nowrap",
              clipPath: `inset(0 ${((1 - bar) * 100).toFixed(2)}% 0 0)`, boxShadow: `0 ${14 * u}px ${34 * u}px rgba(0,0,0,.4)` }}>{plan.bar}</div>
          ) : (
            <div style={{ height: 18 * u, background: block, clipPath: `inset(0 ${((1 - bar) * 100).toFixed(2)}% 0 0)` }} />
          )}
        </div>
        {plan.small ? (
            <MaskRise p={smallIn} out={0} style={{ marginTop: 22 * u }}>
              <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: px(38), letterSpacing: "0.24em", color: "rgba(255,255,255,.94)",
                whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.7)" }}>{plan.small}</div>
            </MaskRise>
          ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "dt-clean-card": DtCleanCard,
  "dt-calendar-page": DtCalendarPage,
  "dt-stamp-bar": DtStampBar,
  "dt-clock-time": DtClockTime,
  "dt-rec-stamp": DtRecStamp,
  "dt-date-slam": DtDateSlam,
  "dt-timeline-tick": DtTimelineTick,
  "dt-countdown-days": DtCountdownDays,
  "dt-bold-headline": DtBoldHeadline,
  "dt-big-stack": DtBigStack,
};
