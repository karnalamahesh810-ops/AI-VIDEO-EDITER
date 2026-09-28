import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Timelines & history looks (family "tl-"), in the pro house style: condensed
 * caps rising out of masks and dropping out at the end, numbers rolling like
 * odometers, graphics landing on expo / back-out curves and holding with a
 * slow push.
 *
 *   tl-year-scroller        a ruler of years racing sideways under a glass lens
 *                           and clicking into place on the target year
 *   tl-vertical-milestones  a spine drawing down the frame, milestone cards
 *                           wiping out of it left and right
 *   tl-era-bands            eras as staggered bands on a time axis, a "now"
 *                           marker sweeping across and painting them
 *   tl-calendar-flip        a desk calendar flipping its pages over the
 *                           binding to the date, the date circled in marker
 *   tl-time-passing         a clock whose hands whirl with a motion trail and
 *                           settle, "20 YEARS LATER" beside it
 *   tl-decade-grid          a grid of decades, a selector racing round it like
 *                           a roulette and landing, the decade opening into
 *                           its ten years
 *   tl-curved-path          events on the bends of a winding road, a glowing
 *                           line drawing through them
 *   tl-years-later          a cinematic time-jump card: an iris opening from a
 *                           hairline, fast-forward streaks, the number rolling
 *   tl-date-stamp-circle    a round rubber ink stamp slamming onto the footage
 *                           with a splash, the date printed in rough ink
 *   tl-then-now-years       two year cards flipping in (3D), an arrow crossing
 *                           the decades between them, the span counting up
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const accelIn = Easing.bezier(0.7, 0, 0.84, 0);
const INK = "#0c0c0f";
/**
 * Text shadow for text inside a mask (LetterLine / Rise clip with overflow hidden): tight enough to fade
 * out inside the box, where a wide soft shadow would be cut into a hard-edged dark rectangle.
 */
const SHADOW = "0 2px 8px rgba(0,0,0,.45)";

/** A text field as a string: planner data sometimes carries a year as a number, and that must not crash. */
const str = (s: unknown): string =>
  typeof s === "string" ? s : typeof s === "number" && Number.isFinite(s) ? String(s) : "";
const cap = (s: unknown) => str(s).toUpperCase().trim();
/** At most `n` characters, cut at a word boundary (a single over-long word is hard-cut). */
const clip = (s: string, n: number) => (s.length <= n ? s : (lines(s, n)[0] || s).slice(0, n));
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const c01 = (v: number) => Math.max(0, Math.min(1, v));
const mod = (v: number, m: number) => ((v % m) + m) % m;
/** Deterministic 0..1 noise of an index (never Math.random: every render must match). */
const rnd = (n: number) => {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
/**
 * The frame a LetterLine of `text` must start leaving so its last letter is gone by `end` (LetterLine
 * staggers the exit 0.6 frame per letter, 9 frames each). Callers keep lines short with clip()/lines().
 */
const outFor = (end: number, text: string) => end - 12 - Math.ceil(Math.max(0, Array.from(text).length - 1) * 0.6);

/** A block that rises out of its mask and, at the end, leaves upward through it. */
const Rise: React.FC<{ at: number; outAt?: number; frames?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, outAt, frames = 16, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = outAt ?? durationInFrames - 13;
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, end, 10, accelIn);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.06em", ...style }}>
        <div style={{ transform: `translateY(${(1 - pin) * 112 - pout * 112}%)` }}>{children}</div>
      </div>
    );
  };

/**
 * A chart heading in the house style (ProCharts Heading's look): Bebas letters rise in one by one and
 * drop out so the last one is gone before the cut, the accent bar draws under them and retracts. Long
 * titles step down in size (never under 44 px) and are cut at a word so they stay on one line.
 */
const Title: React.FC<{ text?: string; accent: string; center?: boolean; size?: number; at?: number; maxW?: number }> =
  ({ text, accent, center, size = 58, at = 0, maxW = 1400 }) => {
    const frame = useCurrentFrame();
    const { durationInFrames: dur } = useVideoConfig();
    const k = useK();
    const t = clip(cap(text), 42);
    if (!t) return null;
    const fs = Math.max(44, Math.min(size, maxW / Math.max(1, t.length * 0.44)));
    const bar = ramp(frame, at + 4, 16) * (1 - ramp(frame, dur - 12, 9, accelIn));
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: center ? "center" : "flex-start", gap: 10 * k }}>
        <LetterLine text={t} at={at} step={0.7} outAt={outFor(dur - 2, t)} style={{ fontFamily: DISPLAY, fontSize: fs * k,
          color: "#fff", letterSpacing: "0.04em", lineHeight: 1, whiteSpace: "nowrap", textAlign: center ? "center" : "left",
          textShadow: SHADOW }} />
        <div style={{ width: 110 * k * bar, height: 5 * k, background: accent }} />
      </div>
    );
  };

type Ev = { label: string; text: string; value?: number };
const events = (items: OverlayItem[] | undefined, max: number): Ev[] =>
  (Array.isArray(items) ? items : [])
    .filter((i) => Boolean(i) && str(i.label).trim().length > 0)
    .slice(0, max)
    .map((i) => ({ label: str(i.label).trim(), text: str(i.text).trim(), value: fin(i.value) ? i.value : undefined }));

// ------------------------------------------------------------------ dates
const MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
  "NOVEMBER", "DECEMBER"];
const WEEKDAYS = ["SATURDAY", "SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"];
const leap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const monthDays = (y: number, m: number) => [31, leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m];
/** Day of the week (Zeller's congruence, Gregorian) - no Date object, so renders stay deterministic. */
const weekday = (y: number, m: number, d: number) => {
  let Y = y;
  let M = m + 1;
  if (M < 3) {
    M += 12;
    Y -= 1;
  }
  const K = mod(Y, 100);
  const J = Math.floor(Y / 100);
  const h = mod(d + Math.floor((13 * (M + 1)) / 5) + K + Math.floor(K / 4) + Math.floor(J / 4) + 5 * J, 7);
  return WEEKDAYS[h];
};
const shiftDay = (y: number, m: number, d: number, delta: number): [number, number, number] => {
  let Y = y;
  let M = m;
  let D = d + delta;
  while (D < 1) {
    M -= 1;
    if (M < 0) {
      M = 11;
      Y -= 1;
    }
    D += monthDays(Y, M);
  }
  while (D > monthDays(Y, M)) {
    D -= monthDays(Y, M);
    M += 1;
    if (M > 11) {
      M = 0;
      Y += 1;
    }
  }
  return [Y, M, D];
};
type DateParts = { year?: number; month?: number; day?: number };
/** "March 1936", "March 3, 1936", "3 Mar 1936", "1936" -> parts; the value is the fallback year. */
const parseDate = (raw: string, fallbackYear?: number): DateParts => {
  const up = (raw || "").toUpperCase();
  const out: DateParts = {};
  for (const w of up.split(/[^A-Z]+/)) {
    if (w.length < 3) continue;
    const m = MONTHS.findIndex((name) => name.startsWith(w));
    if (m >= 0) {
      out.month = m;
      break;
    }
  }
  const toks = up.match(/\d+/g) || [];
  const years = toks.map(Number).filter((n) => n >= 100 && n <= 2999);
  if (years.length) out.year = years[years.length - 1];
  else if (fin(fallbackYear) && fallbackYear >= 100 && fallbackYear <= 2999) out.year = Math.round(fallbackYear);
  const dayTok = toks.find((t) => t.length <= 2 && Number(t) >= 1 && Number(t) <= 31);
  if (dayTok !== undefined && out.month !== undefined) out.day = Math.min(Number(dayTok), monthDays(out.year ?? 2001, out.month));
  return out;
};

// ================================================================== 1. year scroller
/**
 * A ruler of years racing sideways (quarter ticks, decades brighter) under a
 * glass lens that magnifies them; it decelerates, clicks into the target year
 * with a small detent wobble, the year turns accent and is underlined. At the
 * end the ruler whooshes on and the lens shrinks away.
 */
const YearScroller: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  // The year is the value; failing that, a year written in the text ("... in 1936").
  const rawV = Number(overlay.value ?? NaN);
  const raw = Number.isFinite(rawV) ? rawV : parseDate(str(overlay.text)).year ?? NaN;
  if (!Number.isFinite(raw) || Math.abs(raw) > 9999) return null;
  const year = Math.round(raw);
  const from = year - 64;
  const at = 6;
  const travel = Math.round(Math.min(fps * 1.7, dur * 0.45));
  const land = at + travel;
  const ease = Easing.bezier(0.6, 0, 0.1, 1);
  const posAt = (f: number) => {
    const e = ramp(f, at, travel, ease);
    const d = f - land;
    const wob = d > 0 ? 0.16 * Math.exp(-d / 4) * Math.sin(d * 1.15) : 0;
    const lv = ramp(f, dur - 13, 12, accelIn);
    return from + (year - from) * e - wob + lv * lv * 18;
  };
  const pos = posAt(frame);
  const speed = Math.abs(pos - posAt(frame - 1));
  const locked = frame >= land - 1;
  const leave = ramp(frame, dur - 13, 12, accelIn);
  const stripIn = ramp(frame, 0, 22);
  const lensIn = ramp(frame, 3, 18, backOut);
  const pulse = interpolate(frame, [land - 2, land + 4, land + 24], [0, 1, 0.3], clamp);
  const underline = ramp(frame, land, 14) * (1 - leave);

  const W = 1560 * k, SH = 150 * k, SP = 118 * k, cx = W / 2;
  const LW = 400 * k, LH = 270 * k, MSP = SP * 2.4;
  const base = Math.floor(pos);
  const half = Math.ceil(cx / SP) + 1;
  const tickY = SH * 0.5;
  let ticks = "";
  const labels: { y: number; x: number }[] = [];
  for (let y = base - half; y <= base + half; y++) {
    for (let q = 0; q < 4; q++) {
      const x = cx + (y + q / 4 - pos) * SP;
      if (x < -SP || x > W + SP) continue;
      const h = q ? 10 * k : (mod(y, 10) === 0 ? 42 : mod(y, 5) === 0 ? 30 : 20) * k;
      ticks += `M${x.toFixed(1)} ${tickY.toFixed(1)}v${(-h).toFixed(1)}`;
    }
    labels.push({ y, x: cx + (y - pos) * SP });
  }
  let mticks = "";
  const lensYears: { y: number; x: number }[] = [];
  for (let y = base - 2; y <= base + 3; y++) {
    for (let q = 0; q < 4; q++) {
      const x = LW / 2 + (y + q / 4 - pos) * MSP;
      if (x < -20 * k || x > LW + 20 * k) continue;
      mticks += `M${x.toFixed(1)} ${LH.toFixed(1)}v${(-(q ? 14 : 30) * k).toFixed(1)}`;
    }
    const x = LW / 2 + (y - pos) * MSP;
    if (x > -LW * 0.7 && x < LW * 1.7) lensYears.push({ y, x });
  }
  // The small ruler is cut out under the lens, which shows the magnified copy.
  const hole0 = ((W - LW) / 2 / W) * 100, hole1 = 100 - hole0;
  const mask = `linear-gradient(90deg, transparent 0%, #000 16%, #000 ${(hole0 - 2).toFixed(2)}%, transparent ${(hole0 + 1).toFixed(2)}%, ` +
    `transparent ${(hole1 - 1).toFixed(2)}%, #000 ${(hole1 + 2).toFixed(2)}%, #000 84%, transparent 100%)`;
  const kicker = clip(cap(overlay.subtitle), 40);
  const caption = lines(cap(overlay.text), 30).slice(0, 2);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 30 * k,
        transform: `scale(${hold})` }}>
        {kicker ? (
          <LetterLine text={kicker} at={2} step={0.6} outAt={outFor(dur, kicker)} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: 30 * k, letterSpacing: "0.32em", paddingLeft: "0.32em", color: accent, textAlign: "center",
            whiteSpace: "nowrap" }} />
        ) : null}
        <div style={{ position: "relative", width: W, height: LH }}>
          <div style={{ position: "absolute", left: 0, top: (LH - SH) / 2, width: W, height: SH, opacity: 1 - leave,
            clipPath: `inset(0 ${(1 - stripIn) * 50}% 0 ${(1 - stripIn) * 50}%)`, WebkitMaskImage: mask, maskImage: mask }}>
            <svg width={W} height={SH} style={{ position: "absolute", left: 0, top: 0 }}>
              <line x1={0} x2={W} y1={tickY} y2={tickY} stroke="rgba(255,255,255,.3)" strokeWidth={2 * k} />
              <path d={ticks} fill="none" stroke="rgba(255,255,255,.72)" strokeWidth={2 * k} />
              {labels.map(({ y, x }) => (
                <text key={y} x={x} y={tickY + 46 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={700}
                  fontSize={30 * k} fill={mod(y, 10) === 0 ? "rgba(255,255,255,.95)" : "rgba(255,255,255,.5)"}>{y}</text>
              ))}
            </svg>
          </div>
          <div style={{ position: "absolute", left: (W - LW) / 2, top: 0, width: LW, height: LH, borderRadius: 22 * k,
            overflow: "hidden", boxSizing: "border-box", border: `${2 * k}px solid rgba(255,255,255,.5)`,
            background: "linear-gradient(180deg, rgba(255,255,255,.14) 0%, rgba(255,255,255,.04) 55%, rgba(255,255,255,.09) 100%)",
            boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.5), 0 0 ${64 * k * pulse}px ${accent}90`,
            opacity: Math.min(1, lensIn * 1.6) * (1 - leave),
            transform: `scale(${(0.7 + 0.3 * lensIn) * (1 - 0.12 * leave)})` }}>
            <div style={{ position: "absolute", left: 0, top: 0, width: LW, height: LH,
              filter: speed > 0.05 ? `blur(${(Math.min(10, speed * 4) * k).toFixed(2)}px)` : undefined }}>
              {lensYears.map(({ y, x }) => {
                const hot = y === year;
                return (
                  <div key={y} style={{ position: "absolute", left: x, top: LH * 0.44, transform: "translate(-50%, -50%)",
                    fontFamily: DISPLAY, fontSize: 150 * k, lineHeight: 1, whiteSpace: "nowrap", letterSpacing: "0.02em",
                    color: hot ? (locked ? accent : "#fff") : "rgba(255,255,255,.4)",
                    textShadow: "0 8px 30px rgba(0,0,0,.45)" }}>{y}</div>
                );
              })}
              <svg width={LW} height={LH} style={{ position: "absolute", left: 0, top: 0 }}>
                <path d={mticks} fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={3 * k} />
              </svg>
            </div>
            <div style={{ position: "absolute", left: LW / 2 - 90 * k * underline, top: LH * 0.44 + 70 * k,
              width: 180 * k * underline, height: 5 * k, background: accent }} />
            <div style={{ position: "absolute", left: LW / 2 - 1.5 * k, top: 0, width: 3 * k, height: 24 * k, background: accent }} />
            <div style={{ position: "absolute", left: 0, top: 0, width: LW, height: LH,
              background: "linear-gradient(115deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,0) 34%)" }} />
          </div>
        </div>
        {caption.length ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 * k }}>
            {caption.map((ln, i) => (
              <LetterLine key={i} text={ln} at={12 + i * 4} step={0.7} outAt={outFor(dur, ln)} style={{ fontFamily: DISPLAY,
                fontSize: 64 * k, lineHeight: 1, color: "#fff", letterSpacing: "0.03em", textAlign: "center",
                whiteSpace: "nowrap", textShadow: SHADOW }} />
            ))}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. vertical milestones
/**
 * A spine draws down the middle of the frame, a glowing tip leading; as it
 * passes each milestone the node pops accent with a ring, a connector shoots
 * out and the card wipes out of the spine, alternating left and right. At the
 * end the cards fold back into the spine and it retracts upward.
 */
const Milestones: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const evs = events(overlay.items, 5);
  if (evs.length < 2) return null;
  const n = evs.length;
  const hasTitle = Boolean(cap(overlay.text));
  const top = (hasTitle ? 250 : 140) * k;
  // The last card (and the hold push) stays above the 90 px bottom margin.
  const bottom = 958 * k;
  const cx = width / 2;
  const step = (bottom - top) / n;
  const yOf = (i: number) => top + step * (i + 0.5);
  const drawAt = 8;
  const drawFrames = Math.round(Math.min(fps * (0.45 + 0.3 * n), dur * 0.5));
  const drawFn = (f: number) => ramp(f, drawAt, drawFrames, inOut);
  const d = drawFn(frame);
  const reach = (y: number) => {
    const frac = (y - top) / (bottom - top);
    for (let f = drawAt; f <= drawAt + drawFrames; f++) if (drawFn(f) >= frac) return f;
    return drawAt + drawFrames;
  };
  const ats = evs.map((_, i) => reach(yOf(i)));
  const retract = ramp(frame, dur - 12, 10, accelIn);
  const len = (bottom - top) * d * (1 - retract);
  const drawing = d > 0.001 && d < 0.999;
  const CW = 600 * k, OFF = 64 * k, NODE = 30 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {hasTitle ? (
          <div style={{ position: "absolute", top: 104 * k, left: 0, right: 0 }}>
            <Title text={overlay.text} accent={accent} center size={60} />
          </div>
        ) : null}
        <div style={{ position: "absolute", left: cx - 1 * k, top, width: 2 * k, height: bottom - top,
          backgroundImage: `repeating-linear-gradient(180deg, rgba(255,255,255,.24) 0px, rgba(255,255,255,.24) ${6 * k}px, transparent ${6 * k}px, transparent ${14 * k}px)`,
          opacity: ramp(frame, 0, 12) * (1 - retract) }} />
        <div style={{ position: "absolute", left: cx - 2.5 * k, top, width: 5 * k, height: len, borderRadius: 3 * k,
          background: "linear-gradient(180deg, rgba(255,255,255,.35), #fff)", boxShadow: `0 0 ${16 * k}px rgba(255,255,255,.35)` }} />
        {drawing ? (
          <div style={{ position: "absolute", left: cx - 9 * k, top: top + len - 9 * k, width: 18 * k, height: 18 * k,
            borderRadius: "50%", background: "#fff", boxShadow: `0 0 ${26 * k}px ${accent}, 0 0 ${8 * k}px #fff` }} />
        ) : null}
        {evs.map((ev, i) => {
          const y = yOf(i);
          const left = i % 2 === 0;
          const at = ats[i];
          const shut = ramp(frame, dur - 16 + (n - 1 - i), 10, accelIn);
          const p = ramp(frame, at + 2, 16) * (1 - shut);
          const pop = ramp(frame, at - 1, 14, backOut) * (1 - shut);
          const ring = ramp(frame, at, 18);
          const txt = lines(ev.text, 36).slice(0, 2);
          const tOut = dur - 21 + (n - 1 - i);
          const edge = `${4 * k}px solid ${accent}`;
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", top: y - 1.5 * k, left: left ? cx - OFF : cx, width: OFF, height: 3 * k,
                background: accent, transform: `scaleX(${p})`, transformOrigin: left ? "right" : "left" }} />
              {ring > 0 && ring < 1 ? (
                <div style={{ position: "absolute", left: cx - NODE / 2, top: y - NODE / 2, width: NODE, height: NODE,
                  borderRadius: "50%", border: `${3 * k}px solid ${accent}`, boxSizing: "border-box",
                  transform: `scale(${1 + ring * 1.8})`, opacity: 1 - ring }} />
              ) : null}
              <div style={{ position: "absolute", left: cx - NODE / 2, top: y - NODE / 2, width: NODE, height: NODE,
                borderRadius: "50%", boxSizing: "border-box", border: `${4 * k}px solid #fff`,
                background: pop > 0.5 ? accent : INK, transform: `scale(${pop})`, boxShadow: `0 0 ${22 * k}px ${accent}` }} />
              <div style={{ position: "absolute", top: y, width: CW, transform: "translateY(-50%)",
                left: left ? undefined : cx + OFF, right: left ? width - (cx - OFF) : undefined }}>
                <div style={{ clipPath: left ? `inset(0 0 0 ${(1 - p) * 100}%)` : `inset(0 ${(1 - p) * 100}% 0 0)`,
                  padding: `${16 * k}px ${30 * k}px ${18 * k}px`, textAlign: left ? "right" : "left",
                  background: `linear-gradient(${left ? 270 : 90}deg, rgba(255,255,255,.14) 0%, rgba(255,255,255,.04) 60%, rgba(255,255,255,0) 100%)`,
                  borderRight: left ? edge : undefined, borderLeft: left ? undefined : edge }}>
                  <Rise at={at + 6} outAt={tOut}>
                    <span style={{ fontFamily: DISPLAY, fontSize: 60 * k, lineHeight: 1, color: accent, letterSpacing: "0.03em",
                      whiteSpace: "nowrap" }}>{clip(cap(ev.label), 18)}</span>
                  </Rise>
                  {txt.map((ln, j) => (
                    <Rise key={j} at={at + 10 + j * 3} outAt={tOut - 1}>
                      <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, lineHeight: 1.12,
                        color: "rgba(255,255,255,.9)" }}>{ln}</span>
                    </Rise>
                  ))}
                </div>
              </div>
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. era bands
/**
 * Eras as bands staggered down a time axis (each from its start year to the
 * next era), wiping in one after another. A "now" marker with a year readout
 * then sweeps left to right, painting each band as it crosses it: the era it
 * is in glows accent, the ones behind it turn white.
 */
const EraBands: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const eras = events(overlay.items, 12)
    .filter((e) => e.value !== undefined)
    .map((e) => ({ label: e.label, start: e.value as number }))
    .sort((a, b) => a.start - b.start)
    .slice(0, 5);
  if (eras.length < 2) return null;
  const first = eras[0].start;
  const last = eras[eras.length - 1].start;
  if (!(last > first)) return null;
  const v = overlay.value, tot = overlay.total;
  const gapAvg = (last - first) / (eras.length - 1);
  const end = fin(v) && v > last ? v : fin(tot) && tot > last ? tot : last + Math.max(1, Math.round(gapAvg));
  const n = eras.length;
  const W = 1480 * k, RH = 64 * k, RG = 14 * k;
  const X = (y: number) => ((y - first) / (end - first)) * W;
  const bandsH = n * RH + (n - 1) * RG;
  const axisY = bandsH + 30 * k;
  const at0 = Math.round(fps * 0.3);
  const sweepAt = at0 + n * 5 + 10;
  const sweepFrames = Math.round(Math.min(fps * 2, dur * 0.42));
  const sw = ramp(frame, sweepAt, sweepFrames, inOut);
  const mYear = first + (end - first) * sw;
  const mx = X(mYear);
  const mOn = ramp(frame, sweepAt - 8, 12);
  const leave = ramp(frame, dur - 13, 11, accelIn);
  const spanY = end - first;
  const stepY = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000].find((s) => spanY / s <= 8) ?? 10000;
  const tickYears: number[] = [];
  for (let y = Math.ceil(first / stepY) * stepY; y <= end + 1e-9 && tickYears.length < 12; y += stepY) tickYears.push(y);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ width: W, display: "flex", flexDirection: "column", gap: 96 * k }}>
          <Title text={overlay.text} accent={accent} size={56} />
          <div style={{ position: "relative", width: W, height: axisY + 64 * k }}>
            {eras.map((e, i) => {
              const s = e.start;
              const en = i < n - 1 ? eras[i + 1].start : end;
              const x0 = X(s);
              const bw = Math.max(2 * k, X(en) - x0);
              const at = at0 + i * 5;
              const g = ramp(frame, at, 18, inOut);
              const shut = ramp(frame, dur - 15 + (n - 1 - i), 10, accelIn);
              const sc = g * (1 - shut);
              const fillW = sw > 0 ? Math.max(0, Math.min(bw, mx - x0)) : 0;
              const active = sw > 0 && mYear >= s && (mYear < en || i === n - 1);
              const rowTop = i * (RH + RG);
              const label = clip(cap(e.label), 24);
              const estW = label.length * 18 * k + 44 * k;
              const inside = bw > Math.max(250 * k, estW + 30 * k);
              const outsideLeft = !inside && x0 + bw + estW + 16 * k > W;
              const inkOn = active && fillW > estW;
              return (
                <React.Fragment key={i}>
                  <div style={{ position: "absolute", left: x0, top: rowTop, width: bw, height: RH, borderRadius: 6 * k,
                    overflow: "hidden", boxSizing: "border-box", background: "rgba(255,255,255,.09)",
                    border: `${1.5 * k}px solid rgba(255,255,255,.16)`,
                    clipPath: sc < 0.999 ? `inset(0 ${(1 - sc) * 100}% 0 0)` : undefined,
                    boxShadow: active ? `0 0 ${30 * k}px ${accent}55` : "none" }}>
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: fillW,
                      background: active ? `linear-gradient(90deg, ${accent}c0, ${accent})` : "rgba(255,255,255,.26)" }} />
                    {inside ? (
                      <div style={{ position: "absolute", left: 22 * k, right: 18 * k, top: 0, bottom: 0, display: "flex",
                        alignItems: "center", justifyContent: "space-between" }}>
                        <LetterLine text={label} at={at + 8} step={0.6} outAt={outFor(dur - 4, label)} style={{
                          fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.1em", whiteSpace: "nowrap",
                          flexShrink: 0, color: inkOn ? INK : "#fff" }} />
                        {bw > estW + 150 * k ? (
                          <LetterLine text={String(Math.round(s))} at={at + 12} outAt={dur - 22} style={{ fontFamily: MONO,
                            fontWeight: 500, fontSize: 24 * k, color: active && fillW > bw - 20 * k ? INK : "rgba(255,255,255,.6)" }} />
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  {!inside ? (
                    <div style={{ position: "absolute", top: rowTop, height: RH, display: "flex", alignItems: "center",
                      left: outsideLeft ? undefined : x0 + bw + 16 * k, right: outsideLeft ? W - x0 + 16 * k : undefined }}>
                      <LetterLine text={label} at={at + 8} step={0.6} outAt={outFor(dur - 4, label)} style={{
                        fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.1em", whiteSpace: "nowrap",
                        color: active ? accent : "#fff" }} />
                    </div>
                  ) : null}
                </React.Fragment>
              );
            })}
            <div style={{ position: "absolute", left: 0, top: axisY, width: W, height: 3 * k, background: "rgba(255,255,255,.7)",
              transform: `scaleX(${ramp(frame, 2, 20, inOut) * (1 - leave)})`, transformOrigin: "left" }} />
            {tickYears.map((y, j) => (
              <div key={j} style={{ position: "absolute", left: X(y) - 70 * k, width: 140 * k, top: axisY, display: "flex",
                flexDirection: "column", alignItems: "center" }}>
                <div style={{ width: 2 * k, height: 14 * k, background: "rgba(255,255,255,.7)",
                  transform: `scaleY(${ramp(frame, 6 + j * 2, 12) * (1 - leave)})`, transformOrigin: "top" }} />
                <Rise at={8 + j * 2} outAt={dur - 16} style={{ marginTop: 6 * k }}>
                  <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.6)" }}>
                    {Math.round(y)}</span>
                </Rise>
              </div>
            ))}
            <div style={{ position: "absolute", left: mx - 1.5 * k, top: -24 * k, width: 3 * k, height: axisY + 40 * k,
              background: accent, boxShadow: `0 0 ${14 * k}px ${accent}`, opacity: mOn * (1 - leave),
              transform: `scaleY(${mOn * (1 - leave)})`, transformOrigin: "top" }} />
            {mOn > 0 ? (
              <div style={{ position: "absolute", left: mx, top: -26 * k, transform: "translate(-50%, -100%)" }}>
                <Rise at={sweepAt - 8} frames={14} outAt={dur - 15}>
                  <div style={{ background: accent, color: INK, fontFamily: MONO, fontWeight: 700, fontSize: 28 * k,
                    padding: `${6 * k}px ${14 * k}px`, borderRadius: 6 * k, letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
                    {Math.round(mYear)}</div>
                </Rise>
              </div>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. calendar flip
type CalPage = { head: string; big: string; foot: string; size: number };

/** A hand-drawn marker loop (overshooting its start, drifting outward) around a centre. */
const loopPath = (cx: number, cy: number, rx: number, ry: number, seed: number) => {
  let d = "";
  const N = 44;
  for (let i = 0; i <= N; i++) {
    const a = -0.6 + ((Math.PI * 2 + 0.95) * i) / N;
    const wob = 1 + 0.045 * Math.sin(a * 3 + seed) + 0.03 * Math.cos(a * 5 + seed * 2);
    const grow = 1 + 0.07 * (i / N);
    d += `${i ? "L" : "M"}${(cx + rx * wob * grow * Math.cos(a)).toFixed(1)} ${(cy + ry * wob * grow * Math.sin(a)).toFixed(1)}`;
  }
  return d;
};

const CalendarPage: React.FC<{ page: CalPage; accent: string; w: number; h: number; mark: number; seed: number }> =
  ({ page, accent, w, h, mark, seed }) => {
    const k = useK();
    const HEAD = 100 * k, FOOT = 62 * k;
    const bodyH = h - HEAD - FOOT;
    const textW = page.big.length * page.size * k * 0.44;
    const rx = Math.min(w / 2 - 16 * k, textW / 2 + 40 * k);
    const ry = Math.min(bodyH / 2 - 8 * k, page.size * k * 0.42 + 18 * k);
    return (
      <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, overflow: "hidden",
        borderRadius: `0 0 ${8 * k}px ${8 * k}px`, background: "linear-gradient(180deg, #f8f6f0 0%, #ebe7dd 100%)" }}>
        <div style={{ height: HEAD, display: "flex", alignItems: "center", justifyContent: "center", boxSizing: "border-box",
          background: "linear-gradient(180deg, #1c1c21 0%, #0f0f13 100%)", borderBottom: `${5 * k}px solid ${accent}` }}>
          <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 40 * k, letterSpacing: "0.3em", marginLeft: "0.3em",
            color: "#fff" }}>{page.head}</span>
        </div>
        <div style={{ position: "absolute", left: 0, top: HEAD, width: w, height: bodyH, display: "flex", alignItems: "center",
          justifyContent: "center" }}>
          <span style={{ fontFamily: DISPLAY, fontSize: page.size * k, lineHeight: 1, color: "#141417", letterSpacing: "0.02em",
            marginTop: 12 * k }}>{page.big}</span>
          {mark > 0 ? (
            <svg width={w} height={bodyH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <path d={loopPath(w / 2, bodyH / 2 + 6 * k, rx, ry, seed)} fill="none" stroke={accent} strokeWidth={6 * k}
                strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - mark} />
            </svg>
          ) : null}
        </div>
        <div style={{ position: "absolute", left: 0, bottom: 0, width: w, height: FOOT, display: "flex", alignItems: "center",
          justifyContent: "center", boxSizing: "border-box", borderTop: `${1.5 * k}px dashed rgba(0,0,0,.16)` }}>
          <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.2em", color: "#6a6a72" }}>
            {page.foot}</span>
        </div>
      </div>
    );
  };

/**
 * A desk calendar rises in (tilting up out of perspective) and flips its
 * pages over the binding, fast then slowing, from eleven pages back to the
 * date: days (with the weekday) for "March 3, 1936", months for "March 1936",
 * years for "1936". The last page settles and the date is circled in marker.
 */
const CalendarFlip: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const dp = parseDate(str(overlay.text), overlay.value);
  if (dp.year === undefined) return null;
  const Y = dp.year;
  const N = 12;
  const pages: CalPage[] = [];
  for (let i = 0; i < N; i++) {
    const back = N - 1 - i;
    if (dp.month !== undefined && dp.day !== undefined) {
      const [yy, mm, dd] = shiftDay(Y, dp.month, dp.day, -back);
      pages.push({ head: MONTHS[mm], big: String(dd), foot: `${weekday(yy, mm, dd)} · ${yy}`, size: 200 });
    } else if (dp.month !== undefined) {
      const t = Y * 12 + dp.month - back;
      const yy = Math.floor(t / 12);
      const mm = t - yy * 12;
      const name = MONTHS[mm];
      pages.push({ head: String(yy), big: name, foot: `${monthDays(yy, mm)} DAYS`,
        size: Math.max(90, Math.min(170, 820 / name.length)) });
    } else {
      const yy = Y - back;
      pages.push({ head: `${Math.floor(yy / 10) * 10}S`, big: String(yy), foot: `${leap(yy) ? 366 : 365} DAYS`, size: 190 });
    }
  }
  const flipAt = 12;
  const flipFrames = Math.round(Math.min(fps * 1.9, dur * 0.45));
  const p = ramp(frame, flipAt, flipFrames, Easing.bezier(0.3, 0.05, 0.15, 1)) * (N - 1);
  const cur = Math.min(N - 1, Math.floor(p + 1e-6));
  const angle = cur >= N - 1 ? 0 : (p - cur) * 180;
  const landAt = flipAt + flipFrames;
  const mark = ramp(frame, landAt - 2, 16, inOut);
  const enter = ramp(frame, 0, 22);
  const leave = ramp(frame, dur - 13, 11, accelIn);
  const PW = 520 * k, PH = 560 * k;
  const shade = Math.sin((angle * Math.PI) / 180);
  // The caption rises in while the pages flip, so it has time to be read before it leaves.
  const caption = lines(cap(overlay.subtitle) || cap(overlay.label), 34).slice(0, 2);
  const capAt = Math.min(landAt - 4, Math.round(fps * 0.8));
  const seed = mod(overlay.startFrame || 0, 13);
  const round = `0 0 ${8 * k}px ${8 * k}px`;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 64 * k,
        transform: `scale(${hold})` }}>
        <div style={{ perspective: 1600 * k, marginTop: 40 * k }}>
          <div style={{ position: "relative", width: PW, height: PH, opacity: Math.min(1, enter * 1.6) * (1 - leave),
            transform: `translateY(${(1 - enter) * 90 * k + leave * 150 * k}px) rotateX(${(1 - enter) * 26}deg) rotate(${leave * -6}deg)` }}>
            <div style={{ position: "absolute", left: -22 * k, right: -22 * k, top: -30 * k, bottom: -30 * k, borderRadius: 14 * k,
              background: "linear-gradient(180deg, #212127 0%, #111115 100%)", border: `${1.5 * k}px solid rgba(255,255,255,.08)`,
              boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.6)` }} />
            {[3, 2, 1].map((j) => (
              <div key={j} style={{ position: "absolute", left: j * 2 * k, right: j * 2 * k, top: 0, bottom: -j * 5 * k,
                borderRadius: round, background: j % 2 ? "#d8d4ca" : "#e6e2d8" }} />
            ))}
            <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, perspective: 1800 * k }}>
              {cur < N - 1 ? (
                <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH }}>
                  <CalendarPage page={pages[cur + 1]} accent={accent} w={PW} h={PH} mark={cur + 1 === N - 1 ? mark : 0} seed={seed} />
                  <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, borderRadius: round,
                    background: `linear-gradient(180deg, rgba(0,0,0,${(0.38 * shade).toFixed(3)}) 0%, rgba(0,0,0,0) 50%)` }} />
                </div>
              ) : null}
              {angle <= 90 ? (
                <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, transformOrigin: "50% 0%",
                  transform: `rotateX(${angle}deg)` }}>
                  <CalendarPage page={pages[cur]} accent={accent} w={PW} h={PH} mark={cur === N - 1 ? mark : 0} seed={seed} />
                  <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, borderRadius: round,
                    background: `rgba(0,0,0,${((angle / 90) * 0.3).toFixed(3)})` }} />
                </div>
              ) : null}
            </div>
            <div style={{ position: "absolute", left: -30 * k, right: -30 * k, top: -44 * k, height: 50 * k, borderRadius: 10 * k,
              background: "linear-gradient(180deg, #37373f 0%, #16161b 100%)", boxShadow: "0 8px 20px rgba(0,0,0,.45)" }} />
            {[0.24, 0.76].map((fx) => (
              <div key={fx} style={{ position: "absolute", left: PW * fx - 12 * k, top: -62 * k, width: 24 * k, height: 80 * k,
                borderRadius: 12 * k, boxSizing: "border-box", border: `${5 * k}px solid #cfd0d6`,
                boxShadow: "0 3px 6px rgba(0,0,0,.4)" }} />
            ))}
            {angle > 90 ? (
              // Past vertical the page's back swings up OVER the binding, so it is drawn after the binding and rings.
              <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, perspective: 1800 * k }}>
                <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, transformOrigin: "50% 0%",
                  transform: `rotateX(${angle}deg)`, borderRadius: round, background: "linear-gradient(0deg, #d4d0c6, #ebe7de)",
                  boxShadow: "0 0 18px rgba(0,0,0,.25)", opacity: 1 - c01((angle - 150) / 30) }} />
              </div>
            ) : null}
          </div>
        </div>
        {caption.length ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k }}>
            {caption.map((ln, i) => (
              <LetterLine key={i} text={ln} at={capAt + i * 5} step={0.6} outAt={outFor(dur, ln)} style={{ fontFamily: LABEL,
                fontWeight: 800, fontSize: 38 * k, letterSpacing: "0.2em", paddingLeft: "0.2em", color: "#fff",
                textAlign: "center", whiteSpace: "nowrap", textShadow: SHADOW }} />
            ))}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. time passing clock
/**
 * A minimal clock face: the hands whirl round many times with an accent
 * motion trail fanning behind the minute hand, the rim filling with the
 * years, then brake hard and settle with a small wobble. Beside it the number
 * rolls and "YEARS / LATER" rise in, a line of context under them.
 */
const TimeClock: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value) || value <= 0 || value > 1e6) return null;
  const unit = clip(cap(overlay.suffix), 10) || "YEARS";
  const word = clip(cap(overlay.label), 10) || "LATER";
  const at = 6;
  const spin = Math.round(Math.min(fps * 1.9, dur * 0.45));
  const turns = Math.max(4, Math.min(12, Math.round(3 + Math.log10(value + 1) * 4)));
  const ease = Easing.bezier(0.45, 0, 0.12, 1);
  const minuteAt = (f: number) => {
    const e = ramp(f, at, spin, ease);
    const d = f - (at + spin);
    const wob = d > 0 ? 7 * Math.exp(-d / 4) * Math.sin(d * 1.25) : 0;
    return -turns * 360 * (1 - e) + wob;
  };
  const mA = minuteAt(frame);
  const hA = 300 + mA / 12;
  const speed = Math.abs(mA - minuteAt(frame - 1));
  const trail = Math.min(300, speed * 2.4);
  const prog = ramp(frame, at, spin, ease);
  const enter = ramp(frame, 0, 18, backOut);
  const leave = ramp(frame, dur - 13, 11, accelIn);
  const D = 430 * k;
  const pt = (a: number, r: number) => {
    const t = (a * Math.PI) / 180;
    return `${(100 + r * Math.sin(t)).toFixed(2)} ${(100 - r * Math.cos(t)).toFixed(2)}`;
  };
  let minor = "";
  let major = "";
  for (let i = 0; i < 60; i++) {
    const a = i * 6;
    if (i % 5) minor += `M${pt(a, 85)}L${pt(a, 90)}`;
    else major += `M${pt(a, 77)}L${pt(a, 90)}`;
  }
  const wedges = trail > 2
    ? Array.from({ length: 10 }, (_, j) => {
      const a1 = mA - (trail * j) / 10;
      const a0 = mA - (trail * (j + 1)) / 10;
      return { d: `M100 100L${pt(a0, 80)}A80 80 0 0 1 ${pt(a1, 80)}Z`, o: 0.34 * (1 - j / 10) };
    })
    : [];
  const gid = `tlc${overlay.startFrame || 0}`;
  const caption = lines(str(overlay.text), 40).slice(0, 2);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 90 * k }}>
          <div style={{ width: D, height: D, opacity: Math.min(1, enter * 1.4) * (1 - leave),
            transform: `scale(${(0.6 + 0.4 * enter) * (1 - 0.18 * leave)}) rotate(${(1 - enter) * -30 + leave * 20}deg)` }}>
            <svg width={D} height={D} viewBox="0 0 200 200" style={{ overflow: "visible" }}>
              <defs>
                <radialGradient id={gid} cx="50%" cy="40%" r="62%">
                  <stop offset="0%" stopColor="#2a2b31" stopOpacity={0.88} />
                  <stop offset="100%" stopColor="#0a0a0d" stopOpacity={0.92} />
                </radialGradient>
              </defs>
              <circle cx={100} cy={100} r={97} fill={`url(#${gid})`} stroke="rgba(255,255,255,.85)" strokeWidth={2} />
              <circle cx={100} cy={100} r={97} fill="none" stroke={accent} strokeWidth={3.4} pathLength={1}
                strokeDasharray={`${prog.toFixed(4)} 1`} transform="rotate(-90 100 100)" />
              <path d={minor} stroke="rgba(255,255,255,.42)" strokeWidth={1} />
              <path d={major} stroke="#fff" strokeWidth={2.6} />
              {wedges.map((w, j) => <path key={j} d={w.d} fill={accent} fillOpacity={w.o} />)}
              <g transform={`rotate(${hA.toFixed(2)} 100 100)`}>
                <line x1={100} y1={110} x2={100} y2={52} stroke="#fff" strokeWidth={5.5} strokeLinecap="round" />
              </g>
              <g transform={`rotate(${mA.toFixed(2)} 100 100)`}>
                <line x1={100} y1={114} x2={100} y2={23} stroke={accent} strokeWidth={3.2} strokeLinecap="round" />
              </g>
              <circle cx={100} cy={100} r={6.5} fill="#fff" />
              <circle cx={100} cy={100} r={2.6} fill={accent} />
            </svg>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 * k, maxWidth: 900 * k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 30 * k }}>
              <Rise at={at} frames={14} outAt={dur - 17}>
                <Odometer value={value} at={at} frames={spin} size={190 * k} color="#fff" prefix={overlay.prefix || ""} />
              </Rise>
              <div style={{ display: "flex", flexDirection: "column" }}>
                <LetterLine text={unit} at={at + 8} step={0.8} outAt={outFor(dur, unit) - 2} style={{ fontFamily: DISPLAY,
                  fontSize: 86 * k, lineHeight: 0.95, color: accent, letterSpacing: "0.04em", whiteSpace: "nowrap" }} />
                <LetterLine text={word} at={at + 14} step={0.8} outAt={outFor(dur, word)} style={{ fontFamily: DISPLAY,
                  fontSize: 86 * k, lineHeight: 0.95, color: "#fff", letterSpacing: "0.04em", whiteSpace: "nowrap" }} />
              </div>
            </div>
            <div style={{ width: ramp(frame, at + spin * 0.5, 18) * (1 - leave) * 340 * k, height: 5 * k, background: accent }} />
            {caption.map((ln, i) => (
              <LetterLine key={i} text={ln} at={at + Math.round(spin * 0.6) + i * 4} step={0.5} outAt={outFor(dur, ln)}
                style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 36 * k, lineHeight: 1.1, color: "rgba(255,255,255,.88)",
                  whiteSpace: "nowrap", textShadow: SHADOW }} />
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. decade grid
/**
 * Twelve decades in two rows pop in on a diagonal wave. An accent selector
 * races round them like a roulette wheel (each cell it passes flares), slows
 * and lands on the decade of the year; the cell fills with the accent and a
 * zoom cone opens from it onto the decade's ten years, the year itself lit.
 */
const DecadeGrid: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const rawV = Number(overlay.value ?? NaN);
  const raw = Number.isFinite(rawV) ? rawV : parseDate(str(overlay.text)).year ?? NaN;
  if (!Number.isFinite(raw) || raw < 100 || raw > 2500) return null;
  const year = Math.round(raw);
  const dec = Math.floor(year / 10) * 10;
  // Twelve decades ending up to fifty years after the target (never far past today): the target is always on row 2.
  const endDec = Math.min(dec + 50, Math.max(dec, 2020));
  const startDec = endDec - 110;
  const target = (dec - startDec) / 10;
  const COLS = 6, CW = 214 * k, CH = 146 * k, G = 16 * k;
  const gridW = COLS * CW + (COLS - 1) * G;
  const gridH = 2 * CH + G;
  const cell = (i: number) => ({ x: (i % COLS) * (CW + G), y: Math.floor(i / COLS) * (CH + G) });
  const H = 12 + target;
  const hopAt = Math.round(fps * 0.55);
  const hopSpan = Math.round(Math.min(fps * 1.8, dur * 0.36));
  const tHop = (i: number) => hopAt + hopSpan * Math.pow(i / H, 1.7);
  let h = -1;
  for (let i = 0; i <= H; i++) if (tHop(i) <= frame) h = i;
  const landAt = tHop(H);
  const locked = frame >= landAt;
  const lastVisit = (j: number) => {
    let lv = -1;
    for (let i = 0; i <= h; i++) if (i % 12 === j) lv = tHop(i);
    return lv;
  };
  let sx = 0;
  let sy = 0;
  if (h >= 0) {
    const a = cell(h === 0 ? 0 : (h - 1) % 12);
    const b = cell(h % 12);
    const mv = h === 0 ? 1 : ramp(frame, tHop(h), 2);
    sx = a.x + (b.x - a.x) * mv;
    sy = a.y + (b.y - a.y) * mv;
  }
  const leave = ramp(frame, dur - 13, 11, accelIn);
  const settle = c01((frame - landAt) / 10);
  const pr = ramp(frame, landAt, 16);
  const tc = cell(target);
  const CHW = 112 * k, CHG = 12 * k;
  const chipsW = 10 * CHW + 9 * CHG;
  const chipsTop = gridH + 96 * k;
  const chipsLeft = (gridW - chipsW) / 2;
  const conn = ramp(frame, landAt + 2, 14, inOut) * (1 - leave);
  const coneTop = chipsTop - 8 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 44 * k,
        transform: `scale(${hold})` }}>
        <Title text={overlay.text} accent={accent} center size={58} />
        <div style={{ position: "relative", width: gridW, height: chipsTop + 56 * k }}>
          {locked ? (
            <svg width={gridW} height={chipsTop} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <path d={`M${tc.x} ${gridH} L${tc.x + CW} ${gridH} L${chipsLeft + chipsW} ${coneTop} L${chipsLeft} ${coneTop} Z`}
                fill={accent} fillOpacity={0.12 * conn} />
              <path d={`M${tc.x} ${gridH} L${chipsLeft} ${coneTop}`} stroke={accent} strokeOpacity={0.8} strokeWidth={2 * k}
                fill="none" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - conn} />
              <path d={`M${tc.x + CW} ${gridH} L${chipsLeft + chipsW} ${coneTop}`} stroke={accent} strokeOpacity={0.8}
                strokeWidth={2 * k} fill="none" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - conn} />
            </svg>
          ) : null}
          {Array.from({ length: 12 }, (_, i) => {
            const d = startDec + i * 10;
            const { x, y } = cell(i);
            const col = i % COLS, row = Math.floor(i / COLS);
            const inP = ramp(frame, 4 + (col + row) * 2, 16, backOut);
            const outQ = ramp(frame, dur - 15 + (col + row) * 0.7, 9, accelIn);
            const lv = lastVisit(i);
            const flash = lv >= 0 ? 1 - c01((frame - lv) / 10) : 0;
            const isT = i === target;
            const fill = isT ? ramp(frame, landAt, 12) : 0;
            return (
              <div key={i} style={{ position: "absolute", left: x, top: y, width: CW, height: CH, borderRadius: 10 * k,
                overflow: "hidden", boxSizing: "border-box", border: `${1.5 * k}px solid rgba(255,255,255,${(0.16 + 0.5 * flash).toFixed(3)})`,
                background: `rgba(255,255,255,${(0.045 + 0.12 * flash).toFixed(3)})`,
                transform: `scale(${(0.85 + 0.15 * inP) * (1 - 0.15 * outQ)})`, opacity: Math.min(1, inP * 1.5) * (1 - outQ) }}>
                <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${fill * 100}%`,
                  background: `linear-gradient(180deg, ${accent} 0%, ${accent}d0 100%)` }} />
                <div style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", display: "flex",
                  alignItems: "center", justifyContent: "center" }}>
                  <Rise at={6 + (col + row) * 2} outAt={dur - 18 + (col + row) * 0.7}>
                    <span style={{ fontFamily: DISPLAY, fontSize: 68 * k, lineHeight: 1, letterSpacing: "0.02em",
                      color: isT && fill > 0.5 ? INK : `rgba(255,255,255,${(0.55 + 0.45 * flash).toFixed(3)})` }}>
                      {d}<span style={{ fontSize: 40 * k }}>S</span></span>
                  </Rise>
                </div>
              </div>
            );
          })}
          {h >= 0 ? (
            <div style={{ position: "absolute", left: sx - 6 * k, top: sy - 6 * k, width: CW + 12 * k, height: CH + 12 * k,
              borderRadius: 14 * k, boxSizing: "border-box", border: `${4 * k}px solid ${accent}`,
              boxShadow: `0 0 ${28 * k}px ${accent}99, inset 0 0 ${18 * k}px ${accent}44`, opacity: 1 - leave,
              transform: `scale(${locked ? 1 + 0.06 * Math.sin(settle * Math.PI) : 1})` }} />
          ) : null}
          {locked && pr < 1 ? (
            <div style={{ position: "absolute", left: tc.x, top: tc.y, width: CW, height: CH, borderRadius: 14 * k,
              boxSizing: "border-box", border: `${3 * k}px solid ${accent}`, transform: `scale(${1 + 0.3 * pr})`,
              opacity: 0.8 * (1 - pr) }} />
          ) : null}
          {Array.from({ length: 10 }, (_, j) => {
            const yr = dec + j;
            const hot = yr === year;
            const at = Math.round(landAt + 4 + j * 1.4);
            return (
              <div key={j} style={{ position: "absolute", left: chipsLeft + j * (CHW + CHG), top: chipsTop, width: CHW }}>
                <Rise at={at} frames={14} outAt={dur - 18 + Math.floor(j / 3)}>
                  <div style={{ height: 50 * k, display: "flex", alignItems: "center", justifyContent: "center",
                    borderRadius: 8 * k, boxSizing: "border-box", background: hot ? accent : "rgba(255,255,255,.06)",
                    border: hot ? "none" : `${1.5 * k}px solid rgba(255,255,255,.14)`, fontFamily: MONO, fontWeight: 700,
                    fontSize: 24 * k, color: hot ? INK : "rgba(255,255,255,.55)" }}>{yr}</div>
                </Rise>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. curved path events
/**
 * A winding road across the frame (a faint track and a dotted centre line)
 * that bends through every event: even events sit on a crest with their label
 * above, odd ones in a dip with their label below, so the road always falls
 * away from a label and never runs through its text. A glowing accent line
 * draws along it with a bright head, the camera drifting after it and settling
 * back; each node pops with a ring as the head passes and its year and line
 * rise out of masks. At the end the line erases toward its end and the nodes
 * shrink away.
 */
const CurvedPath: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const evs = events(overlay.items, 6);
  if (evs.length < 2) return null;
  const n = evs.length;
  // Road parameter u: event i sits at u = i (cos(pi*i) = +-1, a crest or a dip), with a short lead-in and lead-out.
  const uA = -0.42, uB = n - 1 + 0.42;
  const xA = 170 * k, xB = width - 170 * k, cy = 578 * k, A = 128 * k;
  const X = (u: number) => xA + ((u - uA) / (uB - uA)) * (xB - xA);
  const Y = (u: number) => cy - A * Math.cos(Math.PI * u);
  const N = 24 * n + 12;
  const P: [number, number][] = [];
  for (let j = 0; j <= N; j++) {
    const u = uA + ((uB - uA) * j) / N;
    P.push([X(u), Y(u)]);
  }
  const cum: number[] = [0];
  for (let j = 1; j <= N; j++) cum.push(cum[j - 1] + Math.hypot(P[j][0] - P[j - 1][0], P[j][1] - P[j - 1][1]));
  const L = cum[N] || 1;
  const pointAt = (s: number): [number, number] => {
    const ss = Math.max(0, Math.min(L, s));
    let j = 1;
    while (j < N && cum[j] < ss) j++;
    const seg = cum[j] - cum[j - 1] || 1;
    const u = (ss - cum[j - 1]) / seg;
    return [P[j - 1][0] + (P[j][0] - P[j - 1][0]) * u, P[j - 1][1] + (P[j][1] - P[j - 1][1]) * u];
  };
  const nodeS = evs.map((_, i) => {
    const tt = ((i - uA) / (uB - uA)) * N;
    const j = Math.max(0, Math.min(N - 1, Math.floor(tt)));
    return cum[j] + (cum[j + 1] - cum[j]) * (tt - j);
  });
  const drawAt = 8;
  const drawFrames = Math.round(Math.min(fps * (1.1 + 0.28 * n), dur * 0.55));
  const drawFn = (f: number) => ramp(f, drawAt, drawFrames, inOut);
  const dd = drawFn(frame);
  const erase = ramp(frame, dur - 14, 12, accelIn);
  const a = erase * L;
  const b = dd * L;
  const reach = (s: number) => {
    const fr = s / L;
    for (let f = drawAt; f <= drawAt + drawFrames; f++) if (drawFn(f) >= fr) return f;
    return drawAt + drawFrames;
  };
  const ats = nodeS.map(reach);
  const [hx, hy] = pointAt(b);
  // The camera drifts after the head while it draws, then eases back to centre for the hold.
  const pan = -(hx - width / 2) * 0.025 * (1 - ramp(frame, drawAt + drawFrames, 36, inOut));
  const path = P.map((p, j) => `${j ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
  const track = ramp(frame, 0, 14) * (1 - erase);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      {cap(overlay.text) ? (
        <div style={{ position: "absolute", left: 110 * k, top: 90 * k }}>
          <Title text={overlay.text} accent={accent} size={60} />
        </div>
      ) : null}
      <AbsoluteFill style={{ transform: `translateX(${pan.toFixed(2)}px) scale(${hold})` }}>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <path d={path} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth={26 * k} strokeLinecap="round"
            strokeLinejoin="round" opacity={track} />
          <path d={path} fill="none" stroke="rgba(255,255,255,.42)" strokeWidth={3 * k} strokeLinecap="round"
            strokeDasharray={`0.1 ${12 * k}`} opacity={track} />
          {b - a > 0.5 ? (
            <path d={path} fill="none" stroke={accent} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round"
              strokeDasharray={`${(b - a).toFixed(1)} ${(L * 2).toFixed(1)}`} strokeDashoffset={-a}
              style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}aa)` }} />
          ) : null}
          {nodeS.map((_, i) => {
            const x = X(i), y = Y(i);
            const pop = ramp(frame, ats[i] - 1, 14, backOut);
            const gone = ramp(frame, dur - 14 + Math.min(i, 4), 9, accelIn);
            const ring = ramp(frame, ats[i], 20);
            const r = 13 * k * pop * (1 - gone);
            return (
              <g key={i}>
                {ring > 0 && ring < 1 ? (
                  <circle cx={x} cy={y} r={13 * k + 30 * k * ring} fill="none" stroke={accent} strokeWidth={3 * k}
                    opacity={1 - ring} />
                ) : null}
                {r > 0.2 ? <circle cx={x} cy={y} r={r} fill={pop > 0.6 ? accent : INK} stroke="#fff" strokeWidth={4 * k} /> : null}
              </g>
            );
          })}
          {dd > 0.001 && dd < 0.999 ? (
            <g>
              <circle cx={hx} cy={hy} r={20 * k} fill={accent} opacity={0.28} />
              <circle cx={hx} cy={hy} r={9 * k} fill="#fff" />
            </g>
          ) : null}
        </svg>
        {evs.map((ev, i) => {
          const x = X(i), y = Y(i);
          // Crest events label above, dip events below: the road bends away from the text on both sides.
          const above = i % 2 === 0;
          // Label centres kept in so the 290 px boxes clear the 90 px safe margin even with the hold push.
          const lx = Math.max(290 * k, Math.min(width - 290 * k, x));
          const txt = lines(ev.text, 24).slice(0, 2);
          const tOut = dur - 20 + Math.min(i, 5);
          return (
            <div key={i} style={{ position: "absolute", left: lx, top: above ? y - 40 * k : y + 40 * k, width: 290 * k,
              transform: `translate(-50%, ${above ? "-100%" : "0"})`, display: "flex", flexDirection: "column",
              alignItems: "center", textAlign: "center" }}>
              <Rise at={ats[i] + 3} outAt={tOut}>
                <span style={{ fontFamily: DISPLAY, fontSize: 54 * k, lineHeight: 1, color: accent, letterSpacing: "0.03em",
                  whiteSpace: "nowrap", textShadow: SHADOW }}>{clip(cap(ev.label), 14)}</span>
              </Rise>
              {txt.map((ln, j) => (
                <Rise key={j} at={ats[i] + 7 + j * 3} outAt={tOut}>
                  <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 28 * k, lineHeight: 1.12,
                    color: "rgba(255,255,255,.92)", textShadow: SHADOW }}>{ln}</span>
                </Rise>
              ))}
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. years-later card
/**
 * The time-jump card, own backdrop: a hairline flashes across the middle and
 * the frame irises open from it onto a deep graphite set with letterbox bars
 * and scanlines. Fast-forward streaks rush past while the number rolls, fading
 * as it settles; "YEARS LATER" rises in with its tracking tightening; the
 * card collapses back into the hairline at the end.
 */
const YearsLater: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value) || value <= 0 || value > 1e6) return null;
  const unit = clip(cap(overlay.suffix), 10) || "YEARS";
  const word = clip(cap(overlay.label), 10) || "LATER";
  const sub = clip(cap(overlay.subtitle), 36);
  const caption = lines(cap(overlay.text), 40).slice(0, 2);
  const open = ramp(frame, 5, 13);
  const close = ramp(frame, dur - 13, 9, accelIn);
  const vis = open * (1 - close);
  const lineW = ramp(frame, 0, 9) * (1 - ramp(frame, dur - 5, 5, accelIn));
  const rollAt = 12;
  const rollFrames = Math.round(Math.min(fps * 1.6, dur * 0.4));
  const eAt = (f: number) => ramp(f, rollAt, rollFrames);
  const e = eAt(frame);
  const vel = (e - eAt(frame - 1)) * rollFrames;
  const bars = ramp(frame, 6, 18);
  const track = 0.2 + 0.7 * (1 - ramp(frame, rollAt + 4, 40));
  const textEnd = dur - 12;
  const rule = ramp(frame, 14, 20) * (1 - close);
  const inset = ((1 - vis) * 50).toFixed(3);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ clipPath: `inset(${inset}% 0 ${inset}% 0)`, overflow: "hidden",
        background: "radial-gradient(ellipse at 50% 46%, #1f2127 0%, #0e0f12 52%, #050506 100%)" }}>
        <AbsoluteFill style={{ opacity: 0.55 + 0.45 * c01(vel / 3),
          background: `radial-gradient(ellipse ${900 * k}px ${440 * k}px at 50% 50%, ${accent}33 0%, ${accent}00 70%)` }} />
        {Array.from({ length: 18 }, (_, i) => {
          const depth = 0.4 + 0.9 * rnd(i * 3 + 1);
          const len = (220 + 560 * rnd(i * 3 + 2)) * k;
          const y = height * (0.18 + 0.64 * rnd(i * 3 + 3));
          const span = width + len;
          const x = width - ((e * depth * width * 4 + rnd(i * 5 + 7) * span) % span);
          const o = c01(vel / 2.2) * (0.12 + 0.3 * depth);
          if (o < 0.01) return null;
          return (
            <div key={i} style={{ position: "absolute", left: x, top: y, width: len, height: (1 + 2 * depth) * k,
              borderRadius: 2 * k, background: `linear-gradient(90deg, rgba(255,255,255,${o.toFixed(3)}), rgba(255,255,255,0))` }} />
          );
        })}
        <AbsoluteFill style={{ backgroundImage:
          "repeating-linear-gradient(0deg, rgba(255,255,255,.025) 0px, rgba(255,255,255,.025) 1px, transparent 1px, transparent 4px)" }} />
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 96 * k * bars, background: "#000" }} />
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 96 * k * bars, background: "#000" }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16 * k,
          transform: `scale(${hold})` }}>
          {sub ? (
            <div style={{ display: "flex", alignItems: "center", gap: 26 * k }}>
              <div style={{ width: 150 * k * rule, height: 2 * k, background: `linear-gradient(90deg, rgba(255,255,255,0), ${accent})` }} />
              <LetterLine text={sub} at={14} step={0.6} outAt={outFor(textEnd, sub)} style={{ fontFamily: MONO, fontWeight: 500,
                fontSize: 26 * k, letterSpacing: "0.3em", marginLeft: "0.3em", color: "rgba(255,255,255,.75)" }} />
              <div style={{ width: 150 * k * rule, height: 2 * k, background: `linear-gradient(90deg, ${accent}, rgba(255,255,255,0))` }} />
            </div>
          ) : null}
          <Rise at={rollAt - 2} frames={14} outAt={textEnd - 14}>
            <Odometer value={value} at={rollAt} frames={rollFrames} size={200 * k} color="#fff" prefix={overlay.prefix || ""} />
          </Rise>
          <div style={{ display: "flex", alignItems: "center" }}>
            <LetterLine text={unit} at={rollAt + 10} step={0.9} outAt={outFor(textEnd, unit + word)} style={{ fontFamily: LABEL,
              fontWeight: 800, fontSize: 48 * k, letterSpacing: `${track.toFixed(3)}em`, color: accent }} />
            <div style={{ width: (track + 0.3) * 48 * k }} />
            <LetterLine text={word} at={rollAt + 16} step={0.9} outAt={outFor(textEnd, word)} style={{ fontFamily: LABEL,
              fontWeight: 800, fontSize: 48 * k, letterSpacing: `${track.toFixed(3)}em`, color: "#fff" }} />
          </div>
          {caption.length ? (
            <div style={{ marginTop: 18 * k, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k }}>
              {caption.map((ln, i) => (
                <LetterLine key={i} text={ln} at={rollAt + 26 + i * 5} step={0.5} outAt={outFor(textEnd, ln)} style={{
                  fontFamily: LABEL, fontWeight: 600, fontSize: 32 * k, letterSpacing: "0.14em", color: "rgba(255,255,255,.66)",
                  textAlign: "center", whiteSpace: "nowrap" }} />
              ))}
            </div>
          ) : null}
        </AbsoluteFill>
      </AbsoluteFill>
      <div style={{ position: "absolute", left: (width * (1 - lineW)) / 2, top: height / 2 - 1 * k, width: width * lineW,
        height: 2 * k, opacity: c01(1.25 - vis * 1.25), boxShadow: `0 0 ${18 * k}px ${accent}`,
        background: `linear-gradient(90deg, rgba(255,255,255,0), ${accent} 30%, #fff 50%, ${accent} 70%, rgba(255,255,255,0))` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 9. date stamp circle
/**
 * The rough-ink texture: a mask with seeded speckle holes (thicker near the
 * rim, where a real stamp starves of ink), a few scratches and uneven
 * pressure fading one side. Built as an SVG data URI, deterministic per seed.
 */
const stampMask = (seed: number) => {
  const f = (v: number) => v.toFixed(2);
  let holes = "";
  for (let i = 0; i < 120; i++) {
    const rim = i < 60;
    const a = rnd(seed + i * 3.1) * Math.PI * 2;
    const r = rim ? 83 + 16 * rnd(seed + i * 5.7) : 97 * Math.sqrt(rnd(seed + i * 7.3));
    const x = 100 + r * Math.cos(a);
    const y = 100 + r * Math.sin(a);
    const rr = 0.45 + (rim ? 2.6 : 1.7) * Math.pow(rnd(seed + i * 11.9), 2);
    holes += `M${f(x - rr)} ${f(y)}a${f(rr)} ${f(rr)} 0 1 0 ${f(2 * rr)} 0a${f(rr)} ${f(rr)} 0 1 0 ${f(-2 * rr)} 0`;
  }
  for (let i = 0; i < 6; i++) {
    const a = rnd(seed + i * 13.7) * Math.PI;
    const x = 40 + 120 * rnd(seed + i * 17.3);
    const y = 40 + 120 * rnd(seed + i * 19.1);
    const len = 14 + 26 * rnd(seed + i * 23.9);
    const dx = Math.cos(a) * len, dy = Math.sin(a) * len;
    const nx = -Math.sin(a) * 0.7, ny = Math.cos(a) * 0.7;
    holes += `M${f(x)} ${f(y)}l${f(dx)} ${f(dy)}l${f(nx)} ${f(ny)}l${f(-dx)} ${f(-dy)}Z`;
  }
  const svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>" +
    "<stop offset='0' stop-color='#000'/><stop offset='.55' stop-color='#000' stop-opacity='.93'/>" +
    "<stop offset='1' stop-color='#000' stop-opacity='.6'/></linearGradient></defs>" +
    `<path fill='url(#g)' fill-rule='evenodd' d='M-20 -20H220V220H-20Z${holes}'/></svg>`;
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`;
};

const starPath = (cx: number, cy: number, r: number) => {
  let d = "";
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 ? r * 0.42 : r;
    d += `${i ? "L" : "M"}${(cx + rr * Math.cos(a)).toFixed(2)} ${(cy + rr * Math.sin(a)).toFixed(2)}`;
  }
  return `${d}Z`;
};

/**
 * A round rubber stamp drops onto the footage top right (spinning in from
 * large, accelerating like it is pressed), hits with a squash, a small shake,
 * an ink ring and splatter; its ring text and the date print letter by
 * letter in rough ink. At the end the letters fade off and the stamp lifts.
 */
const InkStamp: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur, width } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const dp = parseDate(str(overlay.text), overlay.value);
  if (dp.year === undefined) return null;
  const year = dp.year;
  const month = dp.month !== undefined ? MONTHS[dp.month] : "";
  const head = month ? (dp.day !== undefined ? `${month.slice(0, 3)} ${dp.day}` : month) : "";
  // Ring text shrinks to fit its arc; these lengths keep it at 24 px or more at 1080p.
  const topText = clip(cap(overlay.subtitle), 22) || "ARCHIVE RECORD";
  const botText = clip(cap(overlay.label), 16) || "RECEIVED";
  const S = 380 * k;
  const left = width - 120 * k - S;
  const top = 100 * k;
  const land = 10;
  const fall = ramp(frame, 0, land, Easing.bezier(0.55, 0, 1, 0.45));
  const dt = frame - land;
  const squash = dt >= 0 ? 1 - 0.06 * Math.exp(-dt / 3) * Math.cos(dt * 0.9) : 1;
  const shakeAmp = dt >= 0 ? 12 * k * Math.exp(-dt / 3) : 0;
  const sx = (rnd(dt * 2 + 1) - 0.5) * shakeAmp;
  const sy = (rnd(dt * 2 + 2) - 0.5) * shakeAmp;
  const lift = ramp(frame, dur - 12, 10, accelIn);
  const sc = (2.3 - 1.3 * fall) * squash * (1 + 0.22 * lift) * hold;
  const rot = -36 + 24 * fall + 7 * lift;
  const op = ramp(frame, 0, 4) * (1 - lift);
  const splash = ramp(frame, land, 16);
  const id = `tls${overlay.startFrame || 0}`;
  const mask = stampMask(mod(overlay.startFrame || 0, 97));
  const fsTop = Math.min(14, 205 / Math.max(1, topText.length * 0.74));
  const fsBot = Math.min(14, 150 / Math.max(1, botText.length * 0.74));
  const star = ramp(frame, land + 4, 8) * (1 - ramp(frame, dur - 16, 6));
  const ring = (text: string, at0: number) => Array.from(text).map((c, i, arr) => {
    const on = ramp(frame, at0 + i * 0.55, 4);
    const off = ramp(frame, dur - 18 + (arr.length - i) * 0.25, 4);
    return <tspan key={i} fillOpacity={on * (1 - off)}>{c}</tspan>;
  });
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 10) * (1 - lift),
        background: `radial-gradient(circle ${560 * k}px at ${left + S / 2}px ${top + S / 2}px, rgba(0,0,0,.5) 0%, rgba(0,0,0,.22) 45%, rgba(0,0,0,0) 100%)` }} />
      {dt >= 0 ? (
        <div style={{ position: "absolute", left, top, width: S, height: S, opacity: 1 - lift }}>
          <div style={{ position: "absolute", left: 0, top: 0, width: S, height: S, borderRadius: "50%", boxSizing: "border-box",
            border: `${3 * k}px solid ${accent}`, transform: `scale(${1 + 0.45 * splash})`, opacity: 0.55 * (1 - splash) }} />
          {Array.from({ length: 9 }, (_, i) => {
            const a = rnd(i * 4.3 + 1) * Math.PI * 2;
            const dist = (S / 2) * (1.02 + 0.3 * rnd(i * 4.3 + 2)) * ramp(frame, land, 10, expoOut);
            const r = (3 + 7 * rnd(i * 4.3 + 3)) * k;
            return (
              <div key={i} style={{ position: "absolute", left: S / 2 + Math.cos(a) * dist - r, top: S / 2 + Math.sin(a) * dist - r,
                width: 2 * r, height: 2 * r, borderRadius: "50%", background: accent, opacity: 0.85 }} />
            );
          })}
        </div>
      ) : null}
      <div style={{ position: "absolute", left, top, width: S, height: S, opacity: op,
        transform: `translate(${sx.toFixed(2)}px, ${sy.toFixed(2)}px) rotate(${rot.toFixed(2)}deg) scale(${sc.toFixed(4)})`,
        WebkitMaskImage: mask, maskImage: mask, WebkitMaskSize: "100% 100%", maskSize: "100% 100%" }}>
        <svg width={S} height={S} viewBox="0 0 200 200" style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <path id={`${id}t`} d="M30 100 A70 70 0 0 1 170 100" />
            <path id={`${id}b`} d="M20 100 A80 80 0 0 0 180 100" />
          </defs>
          <circle cx={100} cy={100} r={95} fill="none" stroke={accent} strokeWidth={6} />
          <circle cx={100} cy={100} r={86} fill="none" stroke={accent} strokeWidth={1.6} />
          <circle cx={100} cy={100} r={58} fill="none" stroke={accent} strokeWidth={1.6} />
          <text fontFamily={LABEL} fontWeight={800} fontSize={fsTop} letterSpacing={fsTop * 0.18} fill={accent}
            textAnchor="middle" style={{ whiteSpace: "pre" }}>
            <textPath href={`#${id}t`} startOffset="50%">{ring(topText, land + 2)}</textPath>
          </text>
          <text fontFamily={LABEL} fontWeight={800} fontSize={fsBot} letterSpacing={fsBot * 0.18} fill={accent}
            textAnchor="middle" style={{ whiteSpace: "pre" }}>
            <textPath href={`#${id}b`} startOffset="50%">{ring(botText, land + 6)}</textPath>
          </text>
          <path d={starPath(27, 100, 5.5)} fill={accent} fillOpacity={star} />
          <path d={starPath(173, 100, 5.5)} fill={accent} fillOpacity={star} />
        </svg>
        <div style={{ position: "absolute", left: 0, top: 0, width: S, height: S, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", paddingTop: 6 * k, boxSizing: "border-box" }}>
          {head ? (
            <LetterLine text={head} at={land + 3} step={0.6} outAt={dur - 22} style={{ fontFamily: LABEL, fontWeight: 800,
              fontSize: (head.length > 7 ? 24 : 30) * k, letterSpacing: "0.2em", marginLeft: "0.2em", lineHeight: 1, color: accent }} />
          ) : null}
          <LetterLine text={String(year)} at={land + 5} step={1.2} outAt={dur - 20} style={{ fontFamily: DISPLAY,
            fontSize: 100 * k, lineHeight: 0.92, color: accent, letterSpacing: "0.02em" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. then vs now years
/** One year card: flips in on a 3D hinge (rotateY), its year rolling, and flips away at the end. */
const YearBlock: React.FC<{ label: string; year: number; at: number; outAt: number; hot: boolean; accent: string }> =
  ({ label, year, at, outAt, hot, accent }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const p = ramp(frame, at, 22, expoOut);
    const q = ramp(frame, outAt, 11, accelIn);
    const rot = (1 - p) * -96 + q * 96;
    const BW = 420 * k, BH = 320 * k, C = 30 * k, T = 4 * k;
    const edge = `${T}px solid ${hot ? accent : "rgba(255,255,255,.85)"}`;
    const corners: React.CSSProperties[] = [
      { left: -T / 2, top: -T / 2, borderLeft: edge, borderTop: edge },
      { right: -T / 2, top: -T / 2, borderRight: edge, borderTop: edge },
      { left: -T / 2, bottom: -T / 2, borderLeft: edge, borderBottom: edge },
      { right: -T / 2, bottom: -T / 2, borderRight: edge, borderBottom: edge },
    ];
    return (
      <div style={{ perspective: 1400 * k }}>
        <div style={{ position: "relative", width: BW, height: BH, transform: `rotateY(${rot.toFixed(2)}deg)`,
          opacity: p > 0.01 && q < 0.99 ? 1 : 0, backfaceVisibility: "hidden", borderRadius: 6 * k, boxSizing: "border-box",
          background: hot ? `linear-gradient(160deg, ${accent}2e 0%, rgba(14,14,18,.55) 70%)`
            : "linear-gradient(160deg, rgba(255,255,255,.1) 0%, rgba(14,14,18,.5) 70%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.16)`, boxShadow: `0 ${30 * k}px ${70 * k}px rgba(0,0,0,.45)`,
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6 * k }}>
          {corners.map((c, i) => <div key={i} style={{ position: "absolute", width: C, height: C, ...c }} />)}
          <LetterLine text={label} at={at + 8} step={0.8} outAt={outAt - 10} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: 34 * k, letterSpacing: "0.3em", marginLeft: "0.3em", color: hot ? accent : "rgba(255,255,255,.7)" }} />
          <Odometer value={year} at={at + 2} frames={26} size={170 * k} color={hot ? "#fff" : "rgba(255,255,255,.85)"}
            grouping={false} />
        </div>
      </div>
    );
  };

/**
 * THEN and NOW: the first year card flips in, an accent arrow crosses the
 * gap ticking off every decade (the ticks pop as the head passes) while the
 * elapsed span rolls up above it, and the second card flips in as the arrow
 * arrives. At the end the cards flip away and the arrow retracts into NOW.
 */
const ThenNowYears: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const its = (Array.isArray(overlay.items) ? overlay.items : []).filter((i) => Boolean(i) && fin(i.value));
  const v = overlay.value, tot = overlay.total;
  let A: { label: string; year: number } | null = null;
  let B: { label: string; year: number } | null = null;
  if (its.length >= 2) {
    A = { label: clip(cap(its[0].label), 12) || "THEN", year: Math.round(Number(its[0].value)) };
    B = { label: clip(cap(its[1].label), 12) || "NOW", year: Math.round(Number(its[1].value)) };
  } else if (fin(v) && fin(tot)) {
    A = { label: "THEN", year: Math.round(v) };
    B = { label: "NOW", year: Math.round(tot) };
  } else {
    const ys = (str(overlay.text).match(/\b\d{3,4}\b/g) || []).map(Number);
    if (ys.length >= 2) {
      A = { label: "THEN", year: ys[0] };
      B = { label: "NOW", year: ys[1] };
    }
  }
  if (!A || !B) return null;
  const a = A, b = B;
  if (!Number.isFinite(a.year) || !Number.isFinite(b.year) || Math.abs(a.year) > 9999 || Math.abs(b.year) > 9999) return null;
  const span = Math.abs(b.year - a.year);
  if (span <= 0 || span > 5000) return null;
  const unit = clip(cap(overlay.suffix), 10) || (span === 1 ? "YEAR" : "YEARS");
  const MW = 560 * k, LY = 36 * k;
  const drawAt = 18;
  const drawFrames = Math.round(Math.min(fps * 1.4, dur * 0.35));
  const dr = ramp(frame, drawAt, drawFrames, inOut);
  const retract = ramp(frame, dur - 15, 11, accelIn);
  const xs = MW * retract;
  const tip = MW * dr;
  const stepY = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000].find((s) => span / s <= 20) ?? 1000;
  const lo = Math.min(a.year, b.year);
  const ticks: { x: number; major: boolean }[] = [];
  for (let y = Math.ceil(lo / stepY) * stepY; y < lo + span && ticks.length < 24; y += stepY) {
    if (y <= lo) continue;
    ticks.push({ x: (Math.abs(y - a.year) / span) * MW, major: mod(y, stepY * 2) === 0 });
  }
  const bAt = drawAt + drawFrames - 8;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 56 * k,
        transform: `scale(${hold})` }}>
        <Title text={overlay.text} accent={accent} center size={60} />
        <div style={{ display: "flex", alignItems: "center", gap: 34 * k }}>
          <YearBlock label={a.label} year={a.year} at={4} outAt={dur - 14} hot={false} accent={accent} />
          <div style={{ width: MW, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 * k }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 16 * k }}>
              <Rise at={drawAt} frames={14} outAt={dur - 19}>
                <Odometer value={span} at={drawAt} frames={drawFrames} size={118 * k} color={accent} />
              </Rise>
              <LetterLine text={unit} at={drawAt + 6} step={0.8} outAt={outFor(dur - 4, unit)} style={{ fontFamily: LABEL,
                fontWeight: 800, fontSize: 40 * k, letterSpacing: "0.22em", color: "#fff", paddingBottom: 16 * k }} />
            </div>
            <svg width={MW} height={LY * 2} style={{ overflow: "visible" }}>
              <line x1={0} x2={MW} y1={LY} y2={LY} stroke="rgba(255,255,255,.2)" strokeWidth={2 * k}
                strokeDasharray={`${4 * k} ${8 * k}`} opacity={ramp(frame, 4, 12) * (1 - retract)} />
              {ticks.map((t, i) => {
                const q = c01((tip - t.x) / (30 * k));
                const pop = q <= 0 ? 0 : interpolate(q, [0, 0.6, 1], [0, 1.3, 1], clamp);
                const hh = (t.major ? 18 : 10) * k * pop * (t.x >= xs ? 1 : 0);
                return hh > 0.1 ? (
                  <line key={i} x1={t.x} x2={t.x} y1={LY - hh} y2={LY + hh} stroke={t.major ? "#fff" : "rgba(255,255,255,.6)"}
                    strokeWidth={2.5 * k} strokeLinecap="round" />
                ) : null;
              })}
              {tip - xs > 12 * k ? (
                <g>
                  <line x1={xs} x2={tip - 8 * k} y1={LY} y2={LY} stroke={accent} strokeWidth={6 * k} strokeLinecap="round" />
                  <path d={`M${tip - 22 * k} ${LY - 16 * k} L${tip + 4 * k} ${LY} L${tip - 22 * k} ${LY + 16 * k}`} fill="none"
                    stroke={accent} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round" />
                </g>
              ) : null}
            </svg>
          </div>
          <YearBlock label={b.label} year={b.year} at={bAt} outAt={dur - 12} hot accent={accent} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "tl-year-scroller": YearScroller,
  "tl-vertical-milestones": Milestones,
  "tl-era-bands": EraBands,
  "tl-calendar-flip": CalendarFlip,
  "tl-time-passing": TimeClock,
  "tl-decade-grid": DecadeGrid,
  "tl-curved-path": CurvedPath,
  "tl-years-later": YearsLater,
  "tl-date-stamp-circle": InkStamp,
  "tl-then-now-years": ThenNowYears,
};
