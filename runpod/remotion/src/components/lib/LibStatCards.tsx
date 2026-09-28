import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, Scrim, Tag, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";

/**
 * Stat cards & comparative numbers (family "ns-"), in the pro house style:
 * numbers roll like odometers, labels rise letter by letter out of masks and
 * drop out at the end, graphics land on expo / back-out curves, hold with a
 * slow push, and retract in the last frames instead of fading.
 *
 *   ns-times-bigger     two bars, the second grows to N times the first, "x N" rolls in
 *   ns-fraction-pie     a pie cut into `total` slices, `value` slices fly in, 3/4 rolls
 *   ns-kpi-flip-grid    up to four KPI tiles flipping in (3D) with rolling values
 *   ns-before-after     a slider line sweeps the "after" state over the "before" state
 *   ns-change-meter     (tag) a -/+ scale on the footage, a marker springs to the change
 *   ns-dual-gauge       two 270-degree dial gauges filling in turn, needles quivering
 *   ns-podium           own stage: 1-2-3 podium blocks rise under a spotlight
 *   ns-tug-of-war       a braided rope, the knot jitters then is pulled to the bigger side
 *   ns-goal-track       progress along a track to a hoisted goal flag, milestones light
 *   ns-block-stack      blocks drop and stack into a grid, the counter rolls beside
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const IN_OUT = Easing.bezier(0.65, 0, 0.35, 1);
const BACK = Easing.bezier(0.34, 1.56, 0.64, 1);
const IN = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const INK = "#0c0c0f";

// ------------------------------------------------------------------ data helpers
type Num = OverlayItem & { value: number; suffix?: string; prefix?: string };
const nums = (items?: OverlayItem[]): Num[] =>
  (Array.isArray(items) ? items : [])
    .filter((i): i is Num => Boolean(i) && typeof i.value === "number" && Number.isFinite(i.value))
    .slice(0, 12);
const str = (s: unknown): string => (typeof s === "string" ? s : "");
const cap = (s: unknown) => str(s).trim().toUpperCase();
const fmt = (v: number) => formatValue(v).text;
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
/** "%" and one-letter units hug the number ("40M"); longer units get a space ("1,040 FT"). */
const unitOf = (s: unknown): string => {
  const t = str(s).trim();
  if (!t) return "";
  return t === "%" || t.length === 1 ? t.toUpperCase() : ` ${t.toUpperCase()}`;
};
/** Deterministic 0..1 noise of an index (never Math.random). */
const rnd = (n: number) => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};
const niceCeil = (v: number) => {
  if (!(v > 0) || !Number.isFinite(v)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v - 1e-9) return m * p;
  return 10 * p;
};
const niceUnit = (v: number) => {
  if (!(v > 0) || !Number.isFinite(v)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v - 1e-9) return m * p;
  return 10 * p;
};
/** Millions and billions without a unit roll as "4.2M" (fewer digit columns, easier to read). */
const compact = (v: number, suffix: string): { v: number; suffix: string } => {
  if (str(suffix).trim()) return { v, suffix };
  const a = Math.abs(v);
  if (a >= 1e9) return { v: Math.round(v / 1e8) / 10, suffix: "B" };
  if (a >= 1e6) return { v: Math.round(v / 1e5) / 10, suffix: "M" };
  return { v, suffix };
};

// ------------------------------------------------------------------ timing helpers
/** Seconds to frames, scaled to the overlay length: a 3 s beat builds faster than a 6 s one. */
const useT = () => {
  const { fps, durationInFrames } = useVideoConfig();
  const tempo = Math.max(0.6, Math.min(1.1, durationInFrames / 150));
  return (sec: number) => Math.round(fps * sec * tempo);
};
/** The frame the exits start (text drops out of its masks, graphics retract). */
const useEnd = () => {
  const { durationInFrames } = useVideoConfig();
  return Math.max(24, durationInFrames - 14);
};
/** 0 -> 1 over the exit. */
const useOut = () => {
  const frame = useCurrentFrame();
  const end = useEnd();
  return ramp(frame, end, 11, IN);
};
/** Safety fade over the very last frames for any residue after the designed exits. */
const useFin = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return 1 - ramp(frame, durationInFrames - 5, 4);
};

// ------------------------------------------------------------------ text helpers
/** A block that rises out of its mask at `at` and leaves upward through it at the end. */
const Rise: React.FC<{ at: number; frames?: number; children: React.ReactNode; style?: React.CSSProperties;
  exitDelay?: number }> = ({ at, frames = 16, children, style, exitDelay = 0 }) => {
  const frame = useCurrentFrame();
  const end = useEnd();
  const pin = ramp(frame, at, frames);
  const pout = ramp(frame, end + exitDelay, 10, IN);
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.06em", ...style }}>
      <div style={{ transform: `translateY(${(1 - pin - pout) * 115}%)` }}>{children}</div>
    </div>
  );
};

/** Exit-only mask for helpers that animate their own entrance (Heading, Tag, LetterLine). */
const Exit: React.FC<{ children: React.ReactNode; delay?: number }> = ({ children, delay = 0 }) => {
  const frame = useCurrentFrame();
  const end = useEnd();
  const k = useK();
  const p = ramp(frame, end + delay, 10, IN);
  // -118% alone leaves a sliver of a short line inside the mask's top padding; the px term clears it.
  return (
    <div style={{ overflow: "hidden", padding: `${10 * k}px ${14 * k}px`, margin: `${-10 * k}px ${-14 * k}px` }}>
      <div style={{ transform: `translateY(calc(${(-p * 118).toFixed(3)}% - ${(p * 12 * k).toFixed(2)}px))` }}>{children}</div>
    </div>
  );
};

/**
 * A LetterLine that also leaves as a block through a mask at the exit: a long label's per-letter
 * drop (0.6 frame apart) would otherwise still be running when the overlay ends.
 */
const Line: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties; delay?: number }> =
  ({ text, at, step = 0.7, style, delay = 0 }) => (
    <Exit delay={delay}><LetterLine text={text} at={at} step={step} style={style} /></Exit>
  );

const labelCss = (k: number, size: number, color: string, spacing = "0.14em"): React.CSSProperties => ({
  fontFamily: LABEL, fontWeight: 800, fontSize: size * k, letterSpacing: spacing, color, lineHeight: 1.05,
  whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.45)",
});

// ================================================================== 1. times bigger
/** Two bars: the reference lands, then the second grows notch by notch to N times it; "x N" rolls in. */
const TimesBars: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const out = useOut();
  const fin = useFin();
  const two = nums(overlay.items).filter((i) => i.value > 0).slice(0, 2);
  if (two.length < 2) return null;
  const lo = two[0].value <= two[1].value ? two[0] : two[1];
  const hi = lo === two[0] ? two[1] : two[0];
  const ratio = hi.value / lo.value;
  if (!Number.isFinite(ratio) || ratio <= 0) return null;
  const shown = ratio >= 10 ? Math.round(ratio) : Math.round(ratio * 10) / 10;
  const suffix = unitOf(overlay.suffix || hi.suffix || lo.suffix);
  const prefix = str(overlay.prefix);
  const WB = 980 * k, BH = 56 * k;
  const unitW = Math.max(16 * k, WB / ratio);
  const aAt = T(0.3), aDur = T(0.6);
  const bAt = aAt + T(0.6), bDur = T(1.5);
  const aG = ramp(frame, aAt, aDur, IN_OUT) * (1 - out);
  const bG = ramp(frame, bAt, bDur, IN_OUT) * (1 - out);
  const head = bG * WB;
  const moving = bG > 0.01 && bG < 0.995 && out === 0;
  const ticks: number[] = [];
  if (ratio <= 16) for (let n = 1; n <= 15 && n * unitW < WB - 14 * k; n++) ticks.push(n);
  const every = ticks.length > 8 ? 2 : 1;
  const guide = ramp(frame, aAt + aDur - 4, T(0.45), IN_OUT) * (1 - out);
  const badgeAt = bAt + bDur - T(0.3);
  // Row A (label + value) above bar A, bar B right under it with the dashed "x1" guide in the empty
  // gap between the bars, row B under bar B: the guide never crosses a label. The x1, x2... counters
  // sit inside bar B's segments.
  const barA = 84 * k;
  const barB = barA + BH + 60 * k;
  const rowB = barB + BH + 14 * k;
  const H = rowB + 80 * k;
  const row = (it: Num, top: number, at: number, frames: number, hot: boolean) => (
    <div style={{ position: "absolute", left: 0, top, height: 76 * k, display: "flex", alignItems: "flex-end", gap: 26 * k }}>
      <Line text={clip(cap(it.label), 28)} at={at} step={0.8}
        style={{ ...labelCss(k, 34, hot ? accent : "rgba(255,255,255,.78)"), marginBottom: 8 * k }} />
      <Rise at={at + 3}>
        <Odometer value={it.value} at={at} frames={frames} size={66 * k} color="#fff" prefix={str(it.prefix) || prefix}
          suffix={suffix} suffixScale={0.5} suffixColor={hot ? accent : "rgba(255,255,255,.7)"} />
      </Rise>
    </div>
  );
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 40 * k, width: WB + 330 * k }}>
          {overlay.text ? <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={60} /></Exit> : null}
          <div style={{ position: "relative", width: WB + 330 * k, height: H }}>
            {row(lo, 0, aAt, aDur + T(0.3), false)}
            <div style={{ position: "absolute", left: 0, top: barA, width: unitW * aG, height: BH, borderRadius: 8 * k,
              background: "linear-gradient(90deg, #8f9199, #e8e9ec)", boxShadow: "0 10px 30px rgba(0,0,0,.35)" }} />
            <div style={{ position: "absolute", left: unitW - 1 * k, top: barA + BH + 4 * k, width: 0,
              height: (barB - barA - BH - 8 * k) * guide, borderLeft: `${2 * k}px dashed rgba(255,255,255,.55)` }} />
            <div style={{ position: "absolute", left: 0, top: barB, width: WB, height: BH, borderRadius: 8 * k, overflow: "hidden",
              background: "rgba(255,255,255,.07)", opacity: ramp(frame, bAt - 6, 8) * (1 - out) }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: head, borderRadius: 8 * k,
                background: `linear-gradient(90deg, ${accent}cc, ${accent})`, boxShadow: `0 0 ${24 * k}px ${accent}66` }} />
              {ticks.map((n) => {
                const x = n * unitW;
                const q = interpolate(head - x, [0, 14 * k], [0, 1], clamp);
                return <div key={n} style={{ position: "absolute", left: x - 1.5 * k, top: 0, bottom: 0, width: 3 * k,
                  background: "rgba(8,8,10,.6)", opacity: q }} />;
              })}
              {ticks.filter((n) => n % every === 0).map((n) => {
                // "x n" rises in the middle of segment n once the head has passed its notch.
                const q = interpolate(head - n * unitW, [0, 24 * k], [0, 1], clamp);
                return (
                  <div key={`t${n}`} style={{ position: "absolute", left: (n - 0.5) * unitW - 40 * k, width: 80 * k,
                    top: (BH - 30 * k) / 2, height: 30 * k, overflow: "hidden", textAlign: "center" }}>
                    <div style={{ transform: `translateY(${(1 - q) * 110}%)`, fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
                      lineHeight: `${30 * k}px`, color: "rgba(12,12,15,.78)" }}>×{n}</div>
                  </div>
                );
              })}
              {moving ? (
                <div style={{ position: "absolute", top: 0, bottom: 0, left: head - 130 * k, width: 130 * k,
                  background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.55))" }} />
              ) : null}
            </div>
            {row(hi, rowB, bAt, bDur, true)}
            <div style={{ position: "absolute", left: WB + 56 * k, top: barB + BH / 2 - 80 * k, display: "flex",
              flexDirection: "column", alignItems: "flex-start", gap: 2 * k, textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>
              <Rise at={badgeAt} frames={14}>
                <Odometer value={shown} at={badgeAt} frames={T(0.9)} size={150 * k} color={accent} prefix="×" />
              </Rise>
              {overlay.subtitle ? (
                <Line text={clip(cap(overlay.subtitle), 18)} at={badgeAt + 6} step={0.7}
                  style={labelCss(k, 26, "rgba(255,255,255,.75)", "0.18em")} />
              ) : null}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. fraction pie
/** "3 of 4": the pie is cut into its slices, the counted ones fly in; numerator over denominator rolls. */
const FractionPie: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const out = useOut();
  const fin = useFin();
  const value = Number(overlay.value ?? NaN);
  const pctIn = str(overlay.suffix).trim() === "%";
  let total = Number(overlay.total ?? NaN);
  if (!Number.isFinite(total) && pctIn) total = 100;
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0 || value < 0) return null;
  const v = Math.min(value, total);
  const frac = v / total;
  const discrete = Number.isInteger(total) && Number.isInteger(v) && total >= 2 && total <= 12;
  const R = 205 * k, PAD = 64 * k, S = 2 * (R + PAD), c = S / 2;
  const fillAt = T(0.4), fillDur = T(1.3);
  const g = ramp(frame, fillAt, fillDur, IN_OUT);
  const shrink = 1 - out;
  const drift = frame * 0.18 - (1 - ramp(frame, 0, T(0.9))) * 40;
  const id = `nsfp${String(overlay.startFrame ?? 0)}`;
  const A = -Math.PI / 2;
  const wedge = (a0: number, a1: number, r: number) => {
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return `M${c} ${c} L${(c + r * Math.cos(a0)).toFixed(2)} ${(c + r * Math.sin(a0)).toFixed(2)} ` +
      `A${r} ${r} 0 ${large} 1 ${(c + r * Math.cos(a1)).toFixed(2)} ${(c + r * Math.sin(a1)).toFixed(2)} Z`;
  };
  const about = (s: number, ox = 0, oy = 0) => `translate(${ox + c} ${oy + c}) scale(${Math.max(0.001, s)}) translate(${-c} ${-c})`;
  const n = discrete ? total : 0;
  const m = discrete ? v : 0;
  const stepF = m > 0 ? fillDur / m : 0;
  const slices = Array.from({ length: n }, (_, i) => {
    const a0 = A + (i / n) * Math.PI * 2;
    const a1 = A + ((i + 1) / n) * Math.PI * 2;
    const on = i < m;
    const p = on ? ramp(frame, fillAt + i * stepF, T(0.5), BACK) : 0;
    return { i, a0, a1, mid: (a0 + a1) / 2, base: ramp(frame, 2 + i * 1.5, 12), on, p, off: on ? (1 - p) * 120 * k + 7 * k : 0 };
  });
  const sweep = frac * g * shrink * Math.PI * 2;
  const rim = frac * g * shrink;
  const allTitle = lines(cap(overlay.text), 20);
  const title = allTitle.slice(0, 3);
  if (allTitle.length > 3) title[2] = `${title[2].replace(/[.,;:]$/, "")}…`;
  const pct = Math.round(frac * 100);
  const tagText = cap(overlay.subtitle) || (pctIn ? "" : `= ${pct}%`);
  // Long numerators / denominators step down so the row stays inside the safe margins.
  const digits = Math.max(fmt(v).length, fmt(total).length);
  const NUM = (digits <= 3 ? 150 : digits <= 5 ? 116 : 90) * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", alignItems: "center", gap: 70 * k }}>
          <svg width={S} height={S} style={{ overflow: "visible" }}>
            <defs>
              <radialGradient id={`${id}g`} cx={c} cy={c} r={R} gradientUnits="userSpaceOnUse">
                <stop offset="0.15" stopColor={accent} stopOpacity={0.72} />
                <stop offset="1" stopColor={accent} />
              </radialGradient>
            </defs>
            <circle cx={c} cy={c} r={R + 34 * k} fill="none" stroke="rgba(255,255,255,.28)" strokeWidth={9 * k}
              strokeDasharray={`${2.5 * k} ${11 * k}`} transform={`rotate(${drift} ${c} ${c})`}
              opacity={ramp(frame, 4, T(0.6)) * shrink} />
            {rim > 0.002 ? (
              <circle cx={c} cy={c} r={R + 34 * k} fill="none" stroke={accent} strokeWidth={9 * k} pathLength={1}
                strokeDasharray={`${rim} 2`} transform={`rotate(-90 ${c} ${c})`} />
            ) : null}
            {discrete ? (
              <>
                {slices.map((s) => (
                  <path key={`b${s.i}`} d={wedge(s.a0, s.a1, R)} transform={about(s.base * shrink)}
                    fill="rgba(255,255,255,.06)" stroke="rgba(255,255,255,.32)" strokeWidth={2 * k} strokeLinejoin="round" />
                ))}
                {slices.filter((s) => s.on && s.p > 0.001).map((s) => (
                  <path key={`f${s.i}`} d={wedge(s.a0, s.a1, R)}
                    transform={about((0.6 + 0.4 * s.p) * shrink, Math.cos(s.mid) * s.off, Math.sin(s.mid) * s.off)}
                    fill={`url(#${id}g)`} stroke={INK} strokeWidth={3 * k} strokeLinejoin="round"
                    opacity={Math.min(1, Math.max(0, s.p) * 2.5)} />
                ))}
              </>
            ) : (
              <>
                <circle cx={c} cy={c} r={Math.max(0.001, R * ramp(frame, 0, T(0.5)) * shrink)} fill="rgba(255,255,255,.06)"
                  stroke="rgba(255,255,255,.3)" strokeWidth={2 * k} />
                {sweep > 0.002 ? (sweep >= Math.PI * 2 - 0.002
                  ? <circle cx={c} cy={c} r={R} fill={`url(#${id}g)`} />
                  : <path d={wedge(A, A + sweep, R)} fill={`url(#${id}g)`} />) : null}
                {sweep > 0.002 && sweep < Math.PI * 2 - 0.01 ? (
                  <line x1={c} y1={c} x2={c + R * Math.cos(A + sweep)} y2={c + R * Math.sin(A + sweep)} stroke="#fff"
                    strokeWidth={3 * k} strokeLinecap="round" />
                ) : null}
              </>
            )}
          </svg>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 250 * k,
            textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>
            <Rise at={fillAt - 4}>
              <Odometer value={v} at={fillAt} frames={fillDur + T(0.2)} size={NUM} color={accent} />
            </Rise>
            <div style={{ width: 240 * k * ramp(frame, fillAt - 6, T(0.5), IN_OUT) * shrink, height: 8 * k, borderRadius: 4 * k,
              background: "#fff", margin: `${4 * k}px 0 ${16 * k}px`, boxShadow: "0 4px 18px rgba(0,0,0,.4)" }} />
            <Rise at={fillAt + 2}>
              <Odometer value={total} at={fillAt + 2} frames={T(0.9)} size={NUM} color="#fff" />
            </Rise>
          </div>
          {title.length || tagText ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 4 * k, maxWidth: 560 * k }}>
              {title.map((ln, i) => (
                <Line key={i} text={ln} at={T(0.2) + i * 5} step={0.7} delay={i * 1.5} style={{ fontFamily: DISPLAY,
                  fontSize: 64 * k, color: "#fff", letterSpacing: "0.03em", lineHeight: 1, whiteSpace: "nowrap",
                  textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
              ))}
              {tagText ? (
                <div style={{ marginTop: 18 * k }}>
                  <Exit><Tag text={tagText} at={fillAt + fillDur} accent={accent} size={32} /></Exit>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. KPI flip grid
/** Up to four KPI tiles that flip in on Y one after another, values rolling, a sheen crossing each. */
const KpiGrid: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const fin = useFin();
  const end = useEnd();
  const items = nums(overlay.items).slice(0, 4);
  if (items.length < 2) return null;
  const four = items.length === 4;
  const cols = four ? 2 : items.length;
  const TW = (items.length === 3 ? 470 : 560) * k;
  const TH = (four ? 250 : 272) * k;
  // Label width stays clear of the "01" index in the tile's top-right corner.
  const labelChars = items.length === 3 ? 19 : 24;
  const textChars = items.length === 3 ? 30 : 38;
  const hl = cap(overlay.highlight);
  const hlIdx = hl ? items.findIndex((i) => cap(i.label) === hl) : -1;
  const hot = hlIdx >= 0 ? hlIdx : items.reduce((mx, it, i) => (it.value > items[mx].value ? i : mx), 0);
  const numSize = (four ? 96 : 104) * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 36 * k }}>
          {overlay.text ? <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={58} center /></Exit> : null}
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, ${TW}px)`, gap: 26 * k }}>
            {items.map((it, i) => {
              const at = T(0.15) + i * T(0.2);
              const pin = ramp(frame, at, T(0.65), BACK);
              const pout = ramp(frame, end - 2 + i * 1.5, 10, IN);
              const rot = (1 - pin) * -95 + pout * 95;
              const isHot = i === hot;
              const cv = compact(it.value, str(it.suffix || overlay.suffix));
              const pre = str(it.prefix || overlay.prefix);
              const unitTxt = unitOf(cv.suffix);
              // A long figure shrinks to the tile instead of running under its edge (Bebas digit ~0.42 em).
              const chars = fmt(cv.v).length + pre.length + unitTxt.length * 0.46;
              const size = Math.min(numSize, (TW - 80 * k) / (Math.max(1, chars) * 0.42));
              const sheen = interpolate(frame, [at + T(0.55), at + T(0.55) + 20], [-130, 130], clamp);
              // Only a share gets a meter: KPIs in different units (people, states, miles) are not comparable.
              const isPct = str(it.suffix || overlay.suffix).trim() === "%";
              const meter = isPct
                ? ramp(frame, at + T(0.3), T(0.9), IN_OUT) * (1 - pout) * Math.max(0, Math.min(1, it.value / 100)) : 0;
              const visible = pin > 0.001 && pout < 0.999;
              return (
                <div key={i} style={{ position: "relative", width: TW, height: TH, borderRadius: 16 * k, overflow: "hidden",
                  transform: `perspective(${1400 * k}px) rotateY(${rot}deg)`, backfaceVisibility: "hidden",
                  opacity: visible ? 1 : 0,
                  background: "linear-gradient(155deg, rgba(40,41,48,.95) 0%, rgba(15,15,19,.94) 100%)",
                  border: `${1.5 * k}px solid ${isHot ? `${accent}aa` : "rgba(255,255,255,.12)"}`,
                  boxShadow: `0 ${24 * k}px ${60 * k}px rgba(0,0,0,.45)` }}>
                  <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 6 * k,
                    background: isHot ? accent : "rgba(255,255,255,.25)",
                    transform: `scaleY(${ramp(frame, at + 4, T(0.5))})`, transformOrigin: "50% 0%" }} />
                  <div style={{ position: "absolute", right: 26 * k, top: 24 * k, fontFamily: MONO, fontWeight: 500,
                    fontSize: 24 * k, color: "rgba(255,255,255,.38)", letterSpacing: "0.1em" }}>{String(i + 1).padStart(2, "0")}</div>
                  <div style={{ position: "absolute", left: 40 * k, right: 30 * k, top: 30 * k, display: "flex",
                    flexDirection: "column", alignItems: "flex-start", gap: 10 * k }}>
                    <LetterLine text={clip(cap(it.label), labelChars)} at={at + 5} step={0.6} outAt={end - 4}
                      style={labelCss(k, 28, "rgba(255,255,255,.78)")} />
                    <Rise at={at + 6} exitDelay={-2}>
                      <Odometer value={cv.v} at={at + 6} frames={T(1.1)} size={size} color="#fff"
                        prefix={pre} suffix={unitTxt} suffixScale={0.46}
                        suffixColor={isHot ? accent : "rgba(255,255,255,.7)"} />
                    </Rise>
                    {it.text ? (
                      <Rise at={at + 10} exitDelay={-2}>
                        <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, color: "rgba(255,255,255,.6)",
                          letterSpacing: "0.04em", whiteSpace: "nowrap" }}>{clip(str(it.text), textChars)}</span>
                      </Rise>
                    ) : null}
                  </div>
                  {isPct ? (
                    <div style={{ position: "absolute", left: 40 * k, right: 40 * k, bottom: 22 * k, height: 5 * k,
                      borderRadius: 3 * k, background: "rgba(255,255,255,.1)" }}>
                      <div style={{ width: `${meter * 100}%`, height: "100%", borderRadius: 3 * k,
                        background: isHot ? accent : "rgba(255,255,255,.75)",
                        boxShadow: isHot ? `0 0 ${12 * k}px ${accent}` : "none" }} />
                    </div>
                  ) : null}
                  <div style={{ position: "absolute", inset: 0, transform: `translateX(${sheen}%)`,
                    background: "linear-gradient(105deg, rgba(255,255,255,0) 40%, rgba(255,255,255,.12) 50%, rgba(255,255,255,0) 60%)" }} />
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. before / after slider
/** One panel, two states: a slider line sweeps across and the "after" number wipes over the "before". */
const BeforeAfter: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const out = useOut();
  const fin = useFin();
  const pair = nums(overlay.items).slice(0, 2);
  if (pair.length < 2) return null;
  const [a, b] = pair;
  const suffix = unitOf(b.suffix || a.suffix || overlay.suffix);
  const pre = (it: Num) => str(it.prefix || overlay.prefix);
  const same = b.value === a.value;
  const down = b.value < a.value;
  const col = same ? accent : down ? RED : GREEN;
  const W = 1160 * k, H = 420 * k;
  const open = ramp(frame, 0, T(0.55));
  const inset = Math.max(1 - open, out) * 50;
  const sAt = T(1.0), sDur = T(1.3);
  const s = ramp(frame, sAt, sDur, IN_OUT);
  const handle = interpolate(frame, [sAt - 8, sAt, sAt + sDur, sAt + sDur + 8], [0, 1, 1, 0], clamp);
  const done = sAt + sDur;
  const change = a.value ? ((b.value - a.value) / Math.abs(a.value)) * 100 : 0;
  const changeTxt = `${Math.abs(change) >= 10 ? Math.round(Math.abs(change)) : Math.abs(change).toFixed(1)}%`;
  const pill = ramp(frame, done + 2, 14);
  const strike = ramp(frame, done + 8, 12, IN_OUT);
  const layer = (it: Num, after: boolean) => {
    const at = after ? sAt : T(0.3);
    return (
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", gap: 6 * k,
        background: after
          ? `radial-gradient(ellipse at 30% 20%, ${col}55 0%, rgba(0,0,0,0) 60%), linear-gradient(135deg, #1e1c20, #0e0e11)`
          : `repeating-linear-gradient(45deg, rgba(255,255,255,.03) 0 ${2 * k}px, rgba(0,0,0,0) ${2 * k}px ${16 * k}px), linear-gradient(135deg, #2d2f36, #141519)`,
        clipPath: after ? `inset(0 ${(1 - s) * 100}% 0 0)` : undefined }}>
        <div style={{ position: "absolute", left: 30 * k, top: 26 * k, padding: `${6 * k}px ${14 * k}px ${5 * k}px`,
          borderRadius: 6 * k, fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.2em",
          color: after ? "#fff" : "rgba(255,255,255,.75)", background: after ? col : "transparent",
          border: after ? "none" : `${1.5 * k}px solid rgba(255,255,255,.4)`,
          clipPath: `inset(0 ${(1 - ramp(frame, at + 2, 12)) * 100}% 0 0)` }}>{after ? "AFTER" : "BEFORE"}</div>
        <LetterLine text={clip(cap(it.label), 26)} at={at + 4} step={0.8}
          style={labelCss(k, 40, after ? col : "rgba(255,255,255,.72)", "0.16em")} />
        <Rise at={at}>
          <Odometer value={it.value} at={at + 2} frames={after ? sDur + T(0.2) : T(0.9)} size={176 * k} color="#fff"
            prefix={pre(it)} suffix={suffix} suffixScale={0.4} suffixColor={after ? col : "rgba(255,255,255,.6)"} />
        </Rise>
        {after ? (
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 30 * k, display: "flex", justifyContent: "center" }}>
            <Rise at={done}>
              <span style={{ position: "relative", display: "inline-block", fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k,
                letterSpacing: "0.1em", color: "rgba(255,255,255,.62)" }}>
                WAS {pre(a)}{fmt(a.value)}{suffix}
                <span style={{ position: "absolute", left: 0, top: "48%", height: 3 * k, width: `${strike * 100}%`, background: col }} />
              </span>
            </Rise>
          </div>
        ) : null}
        {after && !same && a.value !== 0 ? (
          <div style={{ position: "absolute", right: 28 * k, top: 22 * k, display: "flex", alignItems: "center", gap: 10 * k,
            background: col, color: "#fff", fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, lineHeight: 1,
            padding: `${9 * k}px ${20 * k}px ${7 * k}px`, borderRadius: 40 * k,
            clipPath: `inset(0 ${(1 - pill) * 100}% 0 0 round ${40 * k}px)`, boxShadow: `0 0 ${24 * k}px ${col}66` }}>
            <svg width={18 * k} height={14 * k} viewBox="0 0 18 14">
              <path d={down ? "M1 1 H17 L9 13 Z" : "M1 13 H17 L9 1 Z"} fill="#fff" />
            </svg>
            {changeTxt}
          </div>
        ) : null}
      </div>
    );
  };
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 38 * k }}>
          {overlay.text ? <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={60} center /></Exit> : null}
          <div style={{ position: "relative", width: W, height: H }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: 18 * k, overflow: "hidden",
              clipPath: `inset(${inset}% 0 ${inset}% 0 round ${18 * k}px)`,
              border: `${1.5 * k}px solid rgba(255,255,255,.14)`, boxShadow: "0 30px 80px rgba(0,0,0,.5)" }}>
              {layer(a, false)}
              {layer(b, true)}
            </div>
            <div style={{ position: "absolute", left: s * W - 2 * k, top: -14 * k, height: H + 28 * k, width: 4 * k,
              background: "#fff", opacity: handle, boxShadow: `0 0 ${16 * k}px rgba(255,255,255,.75)` }} />
            <div style={{ position: "absolute", left: s * W - 36 * k, top: H / 2 - 36 * k, width: 72 * k, height: 72 * k,
              borderRadius: "50%", background: "#fff", transform: `scale(${handle})`, display: "flex", alignItems: "center",
              justifyContent: "center", boxShadow: "0 10px 30px rgba(0,0,0,.5)" }}>
              <svg width={40 * k} height={24 * k} viewBox="0 0 40 24">
                <path d="M14 4 L6 12 L14 20 M26 4 L34 12 L26 20" fill="none" stroke={INK} strokeWidth={3.5}
                  strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. change meter (tag)
/** On the footage, low-left: a -/+ scale unfolds from zero and a marker springs to the percent change. */
const ChangeMeter: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const out = useOut();
  const end = useEnd();
  const fin = useFin();
  const raw = Number(overlay.value ?? NaN);
  if (!Number.isFinite(raw)) return null;
  const dir = str(overlay.label).trim().toLowerCase();
  const v = dir === "down" && raw > 0 ? -raw : dir === "up" && raw < 0 ? -raw : raw;
  const unit = str(overlay.suffix).trim() || "%";
  const R = niceCeil(Math.max(Math.abs(v) * 1.25, unit === "%" ? 10 : 1));
  const col = v < 0 ? RED : v > 0 ? GREEN : accent;
  const MW = 820 * k, x0 = MW / 2, TY = 150 * k;
  const trackIn = ramp(frame, T(0.1), T(0.55), IN_OUT) * (1 - out);
  const mAt = T(0.6);
  const sp = spring({ frame: Math.max(0, frame - mAt), fps, config: { damping: 11, stiffness: 80, mass: 0.9 } });
  const back = ramp(frame, end - 3, 11, IN);
  const f = Math.max(-1.05, Math.min(1.05, v / R)) * sp * (1 - back);
  const mx = x0 + f * x0;
  const markerOn = ramp(frame, mAt - 6, 8) * (1 - out);
  // Hold motion once the marker has settled: a slow ping on the reading (the tag never sits dead still).
  const settleAt = mAt + T(0.9);
  const ping = frame > settleAt ? ((frame - settleAt) % 36) / 36 : 0;
  const id = `nscm${String(overlay.startFrame ?? 0)}`;
  // At 36 px a caps character is ~22 px wide: 34 of them fit the 820 px meter column (LetterLine clips).
  const title = clip(cap(overlay.text), 34);
  const kicker = clip(cap(overlay.subtitle), 36);
  const scale = [0, 0.5, 1].map((t) => {
    const val = (t * 2 - 1) * R;
    return { t, txt: `${val < 0 ? "−" : val > 0 ? "+" : ""}${fmt(Math.abs(val))}${unit === "%" ? "%" : ""}` };
  });
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * (1 - out),
        background: "radial-gradient(ellipse 70% 55% at 22% 92%, rgba(0,0,0,.66) 0%, rgba(0,0,0,.3) 50%, rgba(0,0,0,0) 78%)" }} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 96 * k, width: MW, display: "flex", flexDirection: "column",
        gap: 8 * k }}>
        {kicker ? <Line text={kicker} at={0} step={0.7} style={labelCss(k, 24, accent, "0.24em")} /> : null}
        {title ? <Line text={title} at={3} step={0.7} delay={1} style={labelCss(k, 36, "#fff", "0.1em")} /> : null}
        <div style={{ position: "relative", width: MW, height: TY + 64 * k }}>
          <svg width={MW} height={TY + 64 * k} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}l`} x1="0" x2="1" y1="0" y2="0">
                <stop offset="0" stopColor={RED} stopOpacity={0.62} />
                <stop offset="1" stopColor={RED} stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id={`${id}r`} x1="0" x2="1" y1="0" y2="0">
                <stop offset="0" stopColor={GREEN} stopOpacity={0.05} />
                <stop offset="1" stopColor={GREEN} stopOpacity={0.62} />
              </linearGradient>
            </defs>
            <g transform={`translate(${x0} 0) scale(${Math.max(0.001, trackIn)} 1) translate(${-x0} 0)`}>
              <rect x={0} y={TY - 5 * k} width={x0} height={10 * k} fill={`url(#${id}l)`} />
              <rect x={x0} y={TY - 5 * k} width={x0} height={10 * k} fill={`url(#${id}r)`} />
              {Array.from({ length: 21 }, (_, i) => {
                const x = (i / 20) * MW;
                const major = i % 5 === 0;
                const lit = (x - x0) * (mx - x0) > 0 && Math.abs(x - x0) <= Math.abs(mx - x0) + 0.5;
                return <line key={i} x1={x} x2={x} y1={TY - 12 * k} y2={TY - (major ? 34 : 22) * k}
                  stroke={lit ? col : "rgba(255,255,255,.5)"} strokeWidth={(major ? 3 : 2) * k} />;
              })}
            </g>
            <rect x={Math.min(x0, mx)} y={TY - 11 * k} width={Math.abs(mx - x0)} height={22 * k} rx={11 * k} fill={col}
              opacity={0.22 * markerOn} />
            <rect x={Math.min(x0, mx)} y={TY - 5 * k} width={Math.abs(mx - x0)} height={10 * k} fill={col} opacity={markerOn} />
            <line x1={x0} x2={x0} y1={TY - 44 * k} y2={TY + 18 * k} stroke="#fff" strokeWidth={3 * k} opacity={trackIn} />
            {ping > 0 ? (
              <circle cx={mx} cy={TY} r={10 * k + 26 * k * ping} fill="none" stroke={col} strokeWidth={3 * k}
                opacity={(1 - ping) * 0.9 * markerOn} />
            ) : null}
            <g opacity={markerOn}>
              <line x1={mx} x2={mx} y1={TY - 50 * k} y2={TY + 16 * k} stroke="#fff" strokeWidth={4 * k} strokeLinecap="round" />
              <path d={`M${mx - 13 * k} ${TY - 68 * k} L${mx + 13 * k} ${TY - 68 * k} L${mx} ${TY - 48 * k} Z`} fill="#fff" />
            </g>
          </svg>
          <div style={{ position: "absolute", left: mx - 150 * k, top: 0, width: 300 * k, display: "flex", justifyContent: "center",
            textShadow: "0 4px 18px rgba(0,0,0,.7)" }}>
            <Rise at={mAt}>
              <Odometer value={Math.abs(v)} at={mAt} frames={T(1.0)} size={70 * k} color="#fff"
                prefix={v < 0 ? "−" : v > 0 ? "+" : ""} suffix={unitOf(unit)} suffixScale={0.55} suffixColor={col} />
            </Rise>
          </div>
          {scale.map(({ t, txt }, i) => (
            <div key={i} style={{ position: "absolute", top: TY + 26 * k, width: 160 * k,
              left: t === 0 ? 0 : t === 1 ? MW - 160 * k : x0 - 80 * k, display: "flex",
              justifyContent: t === 0 ? "flex-start" : t === 1 ? "flex-end" : "center" }}>
              <Rise at={T(0.35) + i * 2}>
                <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.68)",
                  textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>{txt}</span>
              </Rise>
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 6. dual gauge
/** Two 270-degree dials side by side: arcs and needles swing up in turn, ticks light, needles quiver. */
const DualGauge: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const out = useOut();
  const fin = useFin();
  const two = nums(overlay.items).slice(0, 2);
  if (two.length < 2) return null;
  const sfxRaw = str(overlay.suffix || two[0].suffix || two[1].suffix).trim();
  const pct = sfxRaw === "%";
  const tot = Number(overlay.total ?? NaN);
  const max = pct ? 100 : Number.isFinite(tot) && tot > 0 ? tot
    : niceCeil(Math.max(Math.abs(two[0].value), Math.abs(two[1].value), 1e-9) * 1.15);
  const R = 150 * k, SW = 18 * k, S = 2 * R + 140 * k, c = S / 2;
  const A0 = (135 * Math.PI) / 180, SPAN = (270 * Math.PI) / 180;
  const px = (ang: number, r: number) => c + r * Math.cos(ang);
  const py = (ang: number, r: number) => c + r * Math.sin(ang);
  const arcD = `M${px(A0, R).toFixed(2)} ${py(A0, R).toFixed(2)} A${R} ${R} 0 1 1 ${px(A0 + SPAN, R).toFixed(2)} ${py(A0 + SPAN, R).toFixed(2)}`;
  const gauge = (it: Num, i: number) => {
    const at = T(0.3) + i * T(0.85);
    const target = Math.max(0, Math.min(1, it.value / max));
    const sp = spring({ frame: Math.max(0, frame - at), fps, config: { damping: 13, stiffness: 60, mass: 1 } });
    const g = Math.max(0, Math.min(1.02, target * sp)) * (1 - out);
    const hotG = i === 1;
    const colr = hotG ? accent : "#eceef2";
    const settle = ramp(frame, at + T(1.0), 10) * (1 - out);
    const quiver = Math.sin(frame * 0.9 + i * 2.1) * 0.004 * settle;
    const na = A0 + SPAN * Math.max(0, Math.min(1.02, g + quiver));
    // The dial face lands on a scale-up and leaves the same way (it used to hold at 70% through the end).
    const appear = ramp(frame, T(0.05) + i * 4, T(0.5)) * (1 - out);
    // The reading sits inside the dial: raw millions / billions without a unit read as 4.2M.
    const cv = compact(it.value, sfxRaw);
    return (
      <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k }}>
        <div style={{ position: "relative", width: S, height: S * 0.9 }}>
          <svg width={S} height={S} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: appear,
            transform: `scale(${0.85 + 0.15 * appear})` }}>
            <path d={arcD} fill="none" stroke="rgba(255,255,255,.12)" strokeWidth={SW} strokeLinecap="round" />
            {g > 0.003 ? (
              <>
                <path d={arcD} fill="none" stroke={colr} strokeOpacity={0.18} strokeWidth={SW * 2.2} strokeLinecap="round"
                  pathLength={1} strokeDasharray={`${g} 2`} />
                <path d={arcD} fill="none" stroke={colr} strokeWidth={SW} strokeLinecap="round" pathLength={1}
                  strokeDasharray={`${g} 2`} />
              </>
            ) : null}
            {Array.from({ length: 21 }, (_, t) => {
              const ta = A0 + SPAN * (t / 20);
              const major = t % 5 === 0;
              const lit = g >= t / 20 - 1e-6 && g > 0.003;
              return <line key={t} x1={px(ta, R + 22 * k)} y1={py(ta, R + 22 * k)} x2={px(ta, R + (major ? 44 : 34) * k)}
                y2={py(ta, R + (major ? 44 : 34) * k)} stroke={lit ? colr : "rgba(255,255,255,.3)"}
                strokeWidth={(major ? 3.5 : 2) * k} strokeLinecap="round" />;
            })}
            <line x1={c} y1={c} x2={px(na, R - 34 * k)} y2={py(na, R - 34 * k)} stroke="#fff" strokeWidth={6 * k}
              strokeLinecap="round" />
            <circle cx={c} cy={c} r={16 * k} fill={INK} stroke={colr} strokeWidth={5 * k} />
          </svg>
          <div style={{ position: "absolute", left: 0, right: 0, top: c + R * 0.3, display: "flex", justifyContent: "center",
            textShadow: "0 4px 18px rgba(0,0,0,.6)" }}>
            <Rise at={at}>
              <Odometer value={cv.v} at={at} frames={T(1.1)} size={76 * k} color="#fff" prefix={str(it.prefix || overlay.prefix)}
                suffix={unitOf(cv.suffix)} suffixScale={0.5} suffixColor={colr} />
            </Rise>
          </div>
        </div>
        <Line text={clip(cap(it.label), 22)} at={at + 4} step={0.8} delay={i * 2}
          style={labelCss(k, 34, hotG ? accent : "rgba(255,255,255,.85)", "0.14em")} />
      </div>
    );
  };
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 * k }}>
          {overlay.text ? <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={58} center /></Exit> : null}
          <div style={{ display: "flex", alignItems: "flex-start", gap: 70 * k }}>
            {gauge(two[0], 0)}
            <div style={{ width: 2 * k, height: 300 * k * ramp(frame, T(0.2), T(0.6), IN_OUT) * (1 - out),
              background: "rgba(255,255,255,.2)", alignSelf: "center" }} />
            {gauge(two[1], 1)}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. podium (own backdrop)
/** A dark stage: 3rd, 2nd, then 1st rise out of the floor; a spotlight snaps on over the winner. */
const Podium: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const end = useEnd();
  const out = useOut();
  const ranked = nums(overlay.items).slice(0, 8).sort((x, y) => y.value - x.value).slice(0, 3);
  if (ranked.length < 2) return null;
  const sfxRaw = str(overlay.suffix || ranked[0].suffix);
  const prefix = str(overlay.prefix);
  const order: number[] = ranked.length === 3 ? [1, 0, 2] : [1, 0];
  const BW = 300 * k, GAP = 24 * k, DEPTH = 30 * k, INSET = 22 * k;
  const floorY = height * 0.76;
  const cx0 = width / 2;
  const HS = [330 * k, 240 * k, 172 * k];
  const FRONT = [accent, "#dcdee3", "#8d8f97"];
  const riseAt = (r: number) => T(0.35) + (ranked.length - 1 - r) * T(0.4) + (r === 0 ? T(0.2) : 0);
  const landAt = (r: number) => riseAt(r) + T(0.45);
  const cxOf = (j: number) => cx0 + (j - (order.length - 1) / 2) * (BW + GAP);
  const geo = order.map((r, j) => {
    const h = HS[r];
    const p = ramp(frame, riseAt(r), T(0.7), BACK);
    const sink = ramp(frame, end - 2 + j * 1.5, 12, IN);
    // The figures ride their block up (tyIn) but leave through their own masks while the block sinks.
    const tyIn = (1 - p) * (h + DEPTH + 24 * k);
    const ty = tyIn + sink * (h + DEPTH + 40 * k);
    return { r, j, h, cx: cxOf(j), x: cxOf(j) - BW / 2, top: floorY - h, ty, tyIn };
  });
  const winner = geo.find((gg) => gg.r === 0);
  const spotX = winner ? winner.cx : cx0;
  const spot = ramp(frame, landAt(0) - 4, 10) * (1 - out) * (0.9 + 0.1 * Math.sin(frame / 11));
  const bg = ramp(frame, 0, 8) * (1 - ramp(frame, dur - 7, 6));
  const id = `nspd${String(overlay.startFrame ?? 0)}`;
  const burst = ramp(frame, landAt(0), T(0.7));
  const burstY = floorY - HS[0] - DEPTH - 108 * k;
  return (
    <AbsoluteFill style={{ opacity: bg }}>
      <AbsoluteFill style={{ transform: `scale(${hold})`,
        background: "radial-gradient(ellipse at 50% 36%, #25262d 0%, #121317 52%, #060607 100%)" }}>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <linearGradient id={`${id}fl`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#16171c" />
              <stop offset="1" stopColor="#040405" />
            </linearGradient>
            <linearGradient id={`${id}sp`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#fff" stopOpacity={0.17} />
              <stop offset="1" stopColor="#fff" stopOpacity={0.02} />
            </linearGradient>
            <radialGradient id={`${id}pool`}>
              <stop offset="0" stopColor="#fff" stopOpacity={0.22} />
              <stop offset="1" stopColor="#fff" stopOpacity={0} />
            </radialGradient>
            <clipPath id={`${id}floor`}><rect x={0} y={floorY} width={width} height={height - floorY} /></clipPath>
          </defs>
          <rect x={0} y={floorY} width={width} height={height - floorY} fill={`url(#${id}fl)`} />
          <g clipPath={`url(#${id}floor)`} stroke="rgba(255,255,255,.07)" strokeWidth={1.5 * k}>
            {Array.from({ length: 19 }, (_, j) => (
              <line key={`v${j}`} x1={cx0} y1={floorY - 300 * k} x2={cx0 + (j - 9) * 230 * k} y2={height} />
            ))}
            {[16, 40, 74, 120, 182].map((d) => (
              <line key={`h${d}`} x1={0} x2={width} y1={floorY + d * k} y2={floorY + d * k} />
            ))}
          </g>
          <line x1={0} x2={width} y1={floorY} y2={floorY} stroke="rgba(255,255,255,.18)" strokeWidth={2 * k} />
          <polygon points={`${spotX - 60 * k},0 ${spotX + 60 * k},0 ${spotX + 250 * k},${floorY} ${spotX - 250 * k},${floorY}`}
            fill={`url(#${id}sp)`} opacity={spot} />
          <ellipse cx={spotX} cy={floorY + 8 * k} rx={360 * k} ry={42 * k} fill={`url(#${id}pool)`} opacity={spot} />
          {Array.from({ length: 18 }, (_, i) => {
            const yy = floorY - ((rnd(i + 3) * floorY + frame * (0.5 + rnd(i + 9)) * 1.4 * k) % floorY);
            const half = 60 * k + 190 * k * (yy / floorY);
            const xx = spotX + (rnd(i) * 2 - 1) * half * 0.85;
            return <circle key={`m${i}`} cx={xx} cy={yy} r={(1.4 + rnd(i + 17) * 2.2) * k} fill="#fff"
              opacity={0.35 * spot * (0.4 + 0.6 * rnd(i + 21))} />;
          })}
        </svg>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}sh`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#000" stopOpacity={0} />
              <stop offset="1" stopColor="#000" stopOpacity={0.42} />
            </linearGradient>
            <clipPath id={`${id}above`}><rect x={0} y={0} width={width} height={floorY} /></clipPath>
          </defs>
          <g clipPath={`url(#${id}above)`}>
            {geo.map(({ r, h, x, top, ty }) => {
              const face = `${x},${top} ${x + BW},${top} ${x + BW - INSET},${top - DEPTH} ${x + INSET},${top - DEPTH}`;
              return (
                <g key={r} transform={`translate(0 ${ty})`}>
                  <polygon points={face} fill={FRONT[r]} />
                  <polygon points={face} fill="#fff" opacity={0.3} />
                  <rect x={x} y={top} width={BW} height={h} fill={FRONT[r]} />
                  <rect x={x} y={top} width={BW} height={h} fill={`url(#${id}sh)`} />
                  <line x1={x} x2={x + BW} y1={top + k} y2={top + k} stroke="rgba(255,255,255,.6)" strokeWidth={2 * k} />
                  <text x={x + BW / 2} y={top + Math.min(h * 0.72, 170 * k)} textAnchor="middle" fontFamily={DISPLAY}
                    fontSize={(r === 0 ? 150 : 118) * k} fill="rgba(0,0,0,.3)">{r + 1}</text>
                </g>
              );
            })}
          </g>
          {burst > 0 && burst < 1 ? (
            <g stroke={accent} strokeWidth={4 * k} strokeLinecap="round" opacity={1 - burst}>
              {Array.from({ length: 12 }, (_, i) => {
                const ang = (i / 12) * Math.PI * 2 + 0.26;
                const r1 = 84 * k + 110 * k * burst;
                const r2 = r1 + 36 * k * (1 - burst);
                return <line key={i} x1={spotX + Math.cos(ang) * r1} y1={burstY + Math.sin(ang) * r1 * 0.75}
                  x2={spotX + Math.cos(ang) * r2} y2={burstY + Math.sin(ang) * r2 * 0.75} />;
              })}
            </g>
          ) : null}
        </svg>
        {geo.map(({ r, h, cx, tyIn }) => {
          const it = ranked[r];
          const la = landAt(r);
          const name = clip(cap(it.label), 20);
          // Runner-up captions stay inside their own column (340 px) so they never spill onto the taller
          // winner block next to them; the winner's caption sits above everything and may be wider.
          const half = (r === 0 ? 230 : 170) * k;
          const size = r === 0 ? 34 : name.length <= 16 ? 30 : 26;
          const cv = compact(it.value, sfxRaw);
          return (
            <div key={`t${r}`} style={{ position: "absolute", left: cx - half, width: 2 * half,
              bottom: height - (floorY - h - DEPTH - 16 * k), display: "flex", flexDirection: "column", alignItems: "center",
              gap: 2 * k, transform: `translateY(${tyIn}px)`, textShadow: "0 6px 24px rgba(0,0,0,.55)" }}>
              <Rise at={la - 4}>
                <Odometer value={cv.v} at={la - 4} frames={T(1.0)} size={(r === 0 ? 100 : 74) * k}
                  color={r === 0 ? accent : "#fff"} prefix={str(it.prefix) || prefix} suffix={unitOf(cv.suffix)} suffixScale={0.5}
                  suffixColor={r === 0 ? "#fff" : "rgba(255,255,255,.7)"} />
              </Rise>
              <Line text={name} at={la + 2} step={0.7} delay={r}
                style={labelCss(k, size, r === 0 ? "#fff" : "rgba(255,255,255,.8)", "0.12em")} />
            </div>
          );
        })}
        {overlay.text ? (
          <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start", paddingTop: 96 * k }}>
            <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={62} center /></Exit>
          </AbsoluteFill>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. tug of war
/** A braided rope between two sides: the knot jitters at the centre, then is hauled toward the bigger value. */
const TugOfWar: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const out = useOut();
  const end = useEnd();
  const fin = useFin();
  const two = nums(overlay.items).filter((i) => i.value >= 0).slice(0, 2);
  if (two.length < 2) return null;
  const [a, b] = two;
  const sum = a.value + b.value;
  if (!(sum > 0)) return null;
  const sb = b.value / sum;
  const tie = Math.abs(a.value - b.value) < 1e-9;
  const bWins = b.value > a.value;
  const suffix = unitOf(overlay.suffix || a.suffix || b.suffix);
  const prefix = str(overlay.prefix);
  const W = 1300 * k, RY = 236 * k, RH = 20 * k, x0 = W / 2, reach = W * 0.4;
  const target = (sb - 0.5) * 2 * reach;
  const draw = ramp(frame, T(0.05), T(0.65), IN_OUT) * (1 - out);
  const tAt = T(0.75);
  const env = interpolate(frame, [tAt, tAt + 5, tAt + Math.max(6, T(0.9))], [0, 1, 0], clamp);
  const jitter = Math.sin((frame - tAt) * 0.8) * 30 * k * env;
  const pullAt = tAt + T(0.6);
  const sp = spring({ frame: Math.max(0, frame - pullAt), fps, config: { damping: 10, stiffness: 55, mass: 1.1 } });
  const back = ramp(frame, end - 3, 12, IN);
  const off = (jitter + target * sp) * (1 - back);
  const pos = x0 + off;
  const markOn = ramp(frame, T(0.45), T(0.4), BACK) * (1 - out);
  const dirSign = tie ? 0 : bWins ? 1 : -1;
  const share = tie ? 50 : Math.round(Math.max(sb, 1 - sb) * 100);
  const sway = Math.sin(frame * 0.2) * 4 * k;
  const anch = ramp(frame, T(0.3), T(0.4), BACK) * (1 - out);
  const id = `nstw${String(overlay.startFrame ?? 0)}`;
  const side = (it: Num, right: boolean, hot: boolean) => {
    const at = T(0.25) + (right ? 3 : 0);
    return (
      <div style={{ position: "absolute", top: 36 * k, ...(right ? { right: 0 } : { left: 0 }), display: "flex",
        flexDirection: "column", alignItems: right ? "flex-end" : "flex-start", gap: 4 * k, textShadow: "0 5px 22px rgba(0,0,0,.5)" }}>
        <Line text={clip(cap(it.label), 22)} at={at} step={0.8}
          style={labelCss(k, 34, hot ? accent : "rgba(255,255,255,.78)", "0.14em")} />
        <Rise at={at + 3}>
          <Odometer value={it.value} at={at + 3} frames={T(1.0)} size={92 * k} color={hot ? "#fff" : "rgba(255,255,255,.82)"}
            prefix={str(it.prefix) || prefix} suffix={suffix} suffixScale={0.45}
            suffixColor={hot ? accent : "rgba(255,255,255,.6)"} />
        </Rise>
      </div>
    );
  };
  const chevron = (left: boolean) => (
    <svg width={22 * k} height={34 * k} viewBox="0 0 22 34" style={{ opacity: ramp(frame, pullAt + T(0.4), 10) * (1 - out) }}>
      <path d={left ? "M17 3 L5 17 L17 31" : "M5 3 L17 17 L5 31"} fill="none" stroke={accent} strokeWidth={4.5}
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 * k }}>
          {overlay.text ? <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={60} center /></Exit> : null}
          <div style={{ position: "relative", width: W, height: 440 * k }}>
            <svg width={W} height={440 * k} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <pattern id={`${id}p`} width={14 * k} height={RH} patternUnits="userSpaceOnUse"
                  patternTransform={`translate(${off} ${RY - RH / 2}) skewX(-38)`}>
                  <rect width={14 * k} height={RH} fill="#e6e7ea" />
                  <rect width={5.5 * k} height={RH} fill="rgba(12,12,16,.34)" />
                </pattern>
                <clipPath id={`${id}c`}>
                  <rect x={x0 - draw * (x0 + 24 * k)} y={RY - 80 * k} width={Math.max(0, draw * (W + 48 * k))} height={160 * k} />
                </clipPath>
              </defs>
              <line x1={x0} x2={x0} y1={RY - 110 * k} y2={RY + 70 * k} stroke="rgba(255,255,255,.45)" strokeWidth={2 * k}
                strokeDasharray={`${6 * k} ${6 * k}`} opacity={draw} />
              {Array.from({ length: 11 }, (_, j) => {
                const x = x0 + ((j - 5) / 5) * reach;
                return <line key={j} x1={x} x2={x} y1={RY + 24 * k} y2={RY + (j === 5 ? 46 : 36) * k}
                  stroke={j === 5 ? "rgba(255,255,255,.7)" : "rgba(255,255,255,.35)"} strokeWidth={2 * k}
                  opacity={Math.abs(x - x0) <= draw * x0 + 1 ? 1 : 0} />;
              })}
              <g clipPath={`url(#${id}c)`}>
                <rect x={0} y={RY - RH / 2} width={W} height={RH} rx={RH / 2} fill={`url(#${id}p)`} />
                <rect x={0} y={RY - RH / 2 + 2 * k} width={W} height={RH * 0.28} rx={RH * 0.14} fill="rgba(255,255,255,.35)" />
                <rect x={0} y={RY + RH * 0.2} width={W} height={RH * 0.28} rx={RH * 0.14} fill="rgba(0,0,0,.3)" />
              </g>
              <rect x={-18 * k} y={RY - 64 * k} width={14 * k} height={128 * k} rx={7 * k}
                fill={!bWins && !tie ? accent : "#d9dade"}
                transform={`translate(0 ${RY}) scale(1 ${Math.max(0.001, anch)}) translate(0 ${-RY})`} />
              <rect x={W + 4 * k} y={RY - 64 * k} width={14 * k} height={128 * k} rx={7 * k}
                fill={bWins ? accent : "#d9dade"}
                transform={`translate(0 ${RY}) scale(1 ${Math.max(0.001, anch)}) translate(0 ${-RY})`} />
              <g transform={`translate(${pos} ${RY}) scale(${Math.max(0.001, markOn)})`}>
                <line x1={0} y1={0} x2={0} y2={96 * k} stroke="#fff" strokeWidth={3 * k} strokeLinecap="round" />
                <path d={`M0 ${20 * k} L${(dirSign || 1) * 60 * k} ${50 * k + sway} L0 ${82 * k} Z`} fill={accent} />
                <ellipse cx={0} cy={0} rx={13 * k} ry={21 * k} fill={INK} stroke={accent} strokeWidth={4 * k} />
              </g>
            </svg>
            {side(a, false, !bWins && !tie)}
            {side(b, true, bWins)}
            <div style={{ position: "absolute", left: pos - 160 * k, top: RY + 112 * k, width: 320 * k, display: "flex",
              justifyContent: "center", alignItems: "center", gap: 12 * k, textShadow: "0 4px 18px rgba(0,0,0,.6)" }}>
              {dirSign < 0 ? chevron(true) : null}
              <Rise at={pullAt + T(0.35)}>
                <Odometer value={share} at={pullAt + T(0.35)} frames={T(0.9)} size={64 * k} color="#fff" suffix="%"
                  suffixScale={0.5} suffixColor={accent} />
              </Rise>
              {dirSign > 0 ? chevron(false) : null}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. goal track
/** Progress to a goal: the flag hoists at the finish, a runner streaks along, milestones ping as it passes. */
const GoalTrack: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const out = useOut();
  const end = useEnd();
  const fin = useFin();
  const value = Number(overlay.value ?? NaN);
  const total = Number(overlay.total ?? NaN);
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0 || value < 0) return null;
  const p = Math.min(1, value / total);
  const reached = value >= total;
  const suffix = unitOf(overlay.suffix);
  const prefix = str(overlay.prefix);
  const W = 1220 * k, TY = 214 * k, TH = 16 * k;
  const trackIn = ramp(frame, T(0.1), T(0.6), IN_OUT) * (1 - out);
  const runAt = T(0.7), runDur = T(1.8);
  const g = ramp(frame, runAt, runDur, IN_OUT) * (1 - out);
  const gPrev = ramp(frame - 1, runAt, runDur, IN_OUT) * (1 - out);
  const hx = g * p * W;
  const speed = Math.abs(g - gPrev) * p * W;
  const hoist = ramp(frame, T(0.3), T(0.8), IN_OUT);
  const poleLen = ramp(frame, T(0.1), T(0.45), IN_OUT) * (1 - ramp(frame, end + 3, 8, IN));
  const furl = 1 - out;
  const pulse = (frame % 30) / 30;
  const id = `nsgt${String(overlay.startFrame ?? 0)}`;
  const goalTxt = `${prefix}${fmt(total)}${suffix}`;
  const FW = 116 * k * furl, FH = 68 * k;
  const fx = W + 2 * k;
  const poleTop = TY - 196 * k;
  const fy = poleTop + 4 * k + (1 - hoist) * 118 * k;
  const topPts: string[] = [];
  const botPts: string[] = [];
  for (let s = 0; s <= 10; s++) {
    const t = s / 10;
    const w = Math.sin(frame * 0.2 - t * 5.2) * 7 * k * t;
    const x = fx + t * FW;
    topPts.push(`${x.toFixed(1)} ${(fy + w).toFixed(1)}`);
    botPts.push(`${x.toFixed(1)} ${(fy + FH + w * 0.85).toFixed(1)}`);
  }
  const flagD = `M${topPts.join(" L")} L${botPts.reverse().join(" L")} Z`;
  const shadeStops = [0, 0.25, 0.5, 0.75, 1].map((t) => 0.3 * (0.5 + 0.5 * Math.sin(frame * 0.2 - t * 5.2 + Math.PI / 2)));
  const chipW = 180 * k;
  const chipLeft = Math.max(-40 * k, Math.min(hx - chipW / 2, W - chipW - 16 * k));
  const burst = reached ? ramp(frame, runAt + runDur - 2, T(0.7)) : 0;
  const bcx = fx + 58 * k, bcy = fy + FH / 2;
  const miles = [0.25, 0.5, 0.75];
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 18 * k, width: W + 140 * k }}>
          {overlay.text ? <Exit><Heading text={clip(str(overlay.text), 44)} accent={accent} size={56} /></Exit> : null}
          <div style={{ display: "flex", alignItems: "flex-end", gap: 24 * k, textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>
            <Rise at={runAt - 4}>
              <Odometer value={value} at={runAt} frames={runDur + T(0.2)} size={120 * k} color="#fff" prefix={prefix}
                suffix={suffix} suffixScale={0.45} suffixColor={accent} />
            </Rise>
            <Rise at={runAt + 4} style={{ marginBottom: 14 * k }}>
              <span style={labelCss(k, 34, "rgba(255,255,255,.72)", "0.1em")}>OF {goalTxt} GOAL</span>
            </Rise>
            {reached ? (
              <div style={{ marginBottom: 16 * k }}>
                <Exit><Tag text="GOAL REACHED" at={runAt + runDur} accent={GREEN} size={28} /></Exit>
              </div>
            ) : null}
          </div>
          <div style={{ position: "relative", width: W + 140 * k, height: TY + 86 * k }}>
            <svg width={W + 140 * k} height={TY + 86 * k} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <linearGradient id={`${id}f`} x1="0" x2="1" y1="0" y2="0">
                  <stop offset="0" stopColor={accent} stopOpacity={0.55} />
                  <stop offset="1" stopColor={accent} />
                </linearGradient>
                <linearGradient id={`${id}s`} x1="0" x2="1" y1="0" y2="0">
                  <stop offset="0" stopColor="#fff" stopOpacity={0} />
                  <stop offset="1" stopColor="#fff" stopOpacity={0.75} />
                </linearGradient>
                <linearGradient id={`${id}w`} x1="0" x2="1" y1="0" y2="0">
                  {shadeStops.map((o, i) => <stop key={i} offset={i / 4} stopColor="#000" stopOpacity={o} />)}
                </linearGradient>
              </defs>
              <rect x={0} y={TY - TH / 2} width={W * trackIn} height={TH} rx={TH / 2} fill="rgba(255,255,255,.13)" />
              {hx > 1 ? <rect x={0} y={TY - TH / 2} width={hx} height={TH} rx={TH / 2} fill={`url(#${id}f)`} /> : null}
              {speed > 0.5 * k ? (
                <rect x={hx - Math.min(220 * k, speed * 12)} y={TY - TH / 2} width={Math.min(220 * k, speed * 12)} height={TH}
                  fill={`url(#${id}s)`} />
              ) : null}
              {miles.map((m) => {
                const x = m * W;
                const passed = interpolate(hx - x, [0, 10 * k], [0, 1], clamp);
                const pr = interpolate(hx - x, [0, 150 * k], [0, 1], clamp);
                return (
                  <g key={m} opacity={interpolate(trackIn * W - x, [0, 20 * k], [0, 1], clamp)}>
                    <line x1={x} x2={x} y1={TY - 22 * k} y2={TY + 22 * k} stroke={passed > 0.5 ? accent : "rgba(255,255,255,.45)"}
                      strokeWidth={3 * k} strokeLinecap="round" />
                    {pr > 0 && pr < 1 ? (
                      <circle cx={x} cy={TY} r={10 * k + 34 * k * pr} fill="none" stroke={accent} strokeWidth={3 * k}
                        opacity={1 - pr} />
                    ) : null}
                  </g>
                );
              })}
              <circle cx={0} cy={TY} r={9 * k} fill="#fff" opacity={trackIn > 0.01 ? 1 : 0} />
              <line x1={W} x2={W} y1={TY + 12 * k} y2={TY + 12 * k - (TY + 12 * k - poleTop) * poleLen} stroke="#fff"
                strokeWidth={4 * k} strokeLinecap="round" />
              {poleLen > 0.98 ? <circle cx={W} cy={poleTop} r={6 * k} fill="#fff" /> : null}
              {hoist > 0.01 && FW > 1 ? (
                <>
                  <path d={flagD} fill={accent} />
                  <path d={flagD} fill={`url(#${id}w)`} />
                </>
              ) : null}
              {burst > 0 && burst < 1 ? (
                <g stroke={accent} strokeWidth={4 * k} strokeLinecap="round" opacity={1 - burst}>
                  {Array.from({ length: 10 }, (_, i) => {
                    const ang = (i / 10) * Math.PI * 2;
                    const r1 = 70 * k + 90 * k * burst;
                    const r2 = r1 + 30 * k * (1 - burst);
                    return <line key={i} x1={bcx + Math.cos(ang) * r1} y1={bcy + Math.sin(ang) * r1}
                      x2={bcx + Math.cos(ang) * r2} y2={bcy + Math.sin(ang) * r2} />;
                  })}
                </g>
              ) : null}
              {g > 0.002 ? (
                <>
                  <line x1={hx} x2={hx} y1={TY - 42 * k} y2={TY - 16 * k} stroke="rgba(255,255,255,.6)" strokeWidth={2 * k} />
                  <circle cx={hx} cy={TY} r={15 * k + 16 * k * pulse} fill="none" stroke={accent} strokeWidth={3 * k}
                    opacity={1 - pulse} />
                  <circle cx={hx} cy={TY} r={15 * k} fill="#fff" />
                </>
              ) : null}
            </svg>
            <div style={{ position: "absolute", left: chipLeft, top: TY - 104 * k, width: chipW, display: "flex",
              justifyContent: "center", textShadow: "0 4px 18px rgba(0,0,0,.6)" }}>
              <Rise at={runAt}>
                <Odometer value={Math.round(p * 100)} at={runAt} frames={runDur} size={56 * k} color="#fff" suffix="%"
                  suffixScale={0.5} suffixColor={accent} />
              </Rise>
            </div>
            <div style={{ position: "absolute", left: 0, top: TY + 30 * k }}>
              <Rise at={T(0.3)}>
                <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.2em",
                  color: "rgba(255,255,255,.6)" }}>START</span>
              </Rise>
            </div>
            {miles.map((m, i) => (
              <div key={m} style={{ position: "absolute", left: m * W - 50 * k, width: 100 * k, top: TY + 30 * k, display: "flex",
                justifyContent: "center" }}>
                <Rise at={T(0.35) + i * 3}>
                  <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
                    color: hx >= m * W ? "#fff" : "rgba(255,255,255,.55)" }}>{Math.round(m * 100)}%</span>
                </Rise>
              </div>
            ))}
            <div style={{ position: "absolute", right: 140 * k - 10 * k, top: TY + 26 * k, display: "flex",
              flexDirection: "column", alignItems: "flex-end", gap: 2 * k }}>
              <Rise at={T(0.5)}>
                <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.2em", color: accent }}>GOAL</span>
              </Rise>
              <Rise at={T(0.55)}>
                <span style={labelCss(k, 34, "#fff", "0.06em")}>{goalTxt}</span>
              </Rise>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. block stack
/** Blocks drop with gravity and stack into a grid (up to 50), squashing as they land; the count rolls beside. */
const BlockStack: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const hold = useHold();
  const end = useEnd();
  const out = useOut();
  const fin = useFin();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value) || value <= 0) return null;
  const tot = Number(overlay.total ?? NaN);
  const hasTot = Number.isFinite(tot) && tot > value;
  // One block per unit, the unit sized so the whole (the total when given) fits in 50 blocks: "40 of 330"
  // keeps its proportion instead of being cut off at 50 slots.
  const base = hasTot ? tot : value;
  const unit = base <= 50 ? 1 : niceUnit(base / 50);
  const n = Math.max(1, Math.min(50, Math.round(value / unit)));
  const slots = hasTot ? Math.max(n, Math.min(50, Math.round(tot / unit))) : n;
  const cols = slots <= 4 ? slots : slots <= 16 ? 4 : slots <= 30 ? 6 : 10;
  const rows = Math.ceil(slots / cols);
  const GAP = 10 * k;
  const B = Math.min(78 * k, (700 * k - (cols - 1) * GAP) / cols, (420 * k - (rows - 1) * GAP) / rows);
  const GW = cols * B + (cols - 1) * GAP, GH = rows * B + (rows - 1) * GAP;
  const DROP = 460 * k;
  const dropAt = T(0.3);
  const step = Math.max(0.6, Math.min(4, T(1.5) / n));
  const FALL = 11;
  const allIn = dropAt + (n - 1) * step + FALL;
  const sfxRaw = str(overlay.suffix);
  const suffix = unitOf(sfxRaw);
  const prefix = str(overlay.prefix);
  // Raw millions / billions without a unit read as 4.2M: the counter, the block legend and the total alike.
  const cvV = compact(value, sfxRaw);
  const cvU = compact(unit, sfxRaw);
  const cvT = compact(hasTot ? tot : 0, sfxRaw);
  const cycle = Math.max(30, T(1.8));
  const sweep = frame > allIn ? (((frame - allIn) % cycle) / cycle) * 1.6 - 0.3 : -9;
  const spanN = Math.max(1, cols + rows - 2);
  const allTitle = lines(cap(overlay.text), 20);
  const title = allTitle.slice(0, 3);
  if (allTitle.length > 3) title[2] = `${title[2].replace(/[.,;:]$/, "")}…`;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})`, opacity: fin }}>
        <div style={{ display: "flex", alignItems: "center", gap: 100 * k }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{ position: "relative", width: GW, height: DROP + GH, marginTop: -DROP, overflow: "hidden" }}>
              {Array.from({ length: slots }, (_, i) => {
                const col = i % cols;
                const rowB = Math.floor(i / cols);
                const left = col * (B + GAP);
                const top = DROP + (rows - 1 - rowB) * (B + GAP);
                const exitP = ramp(frame, end - 2 + col * 0.9, 11, IN);
                const sinkY = exitP * (GH + B + 30 * k);
                if (i >= n) {
                  const q = ramp(frame, T(0.1) + (i - n) * 0.4, 10) * (1 - exitP);
                  return <div key={i} style={{ position: "absolute", left, top, width: B, height: B, borderRadius: 8 * k,
                    border: `${2 * k}px dashed rgba(255,255,255,.24)`, opacity: q, transform: `scale(${0.7 + 0.3 * q})` }} />;
                }
                const at = dropAt + i * step;
                if (frame < at) return null;
                const t = interpolate(frame, [at, at + FALL], [0, 1], clamp);
                const y = -(1 - t * t) * DROP * 0.9;
                const sq = frame < at + FALL ? 1.05
                  : interpolate(frame, [at + FALL, at + FALL + 3, at + FALL + 8], [0.8, 1.05, 1], clamp);
                const ph = (col + (rows - 1 - rowB)) / spanN;
                const shine = Math.max(0, 1 - Math.abs(sweep - ph) * 5);
                return (
                  <div key={i} style={{ position: "absolute", left, top, width: B, height: B, borderRadius: 8 * k,
                    transform: `translateY(${y + sinkY}px) scale(${1 + (1 - sq) * 0.5}, ${sq})`, transformOrigin: "50% 100%",
                    opacity: interpolate(frame, [at, at + 3], [0, 1], clamp),
                    background: `linear-gradient(180deg, rgba(255,255,255,.32), rgba(255,255,255,0) 55%), ${accent}`,
                    boxShadow: `inset 0 0 0 ${B}px rgba(255,255,255,${(0.3 * shine).toFixed(3)}), 0 ${6 * k}px ${14 * k}px rgba(0,0,0,.35)` }} />
                );
              })}
            </div>
            <div style={{ width: GW + 60 * k, height: 4 * k, marginTop: 8 * k, background: "rgba(255,255,255,.75)",
              transform: `scaleX(${ramp(frame, 0, T(0.5), IN_OUT) * (1 - out)})` }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 12 * k, maxWidth: 620 * k,
            textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>
            {overlay.subtitle ? (
              <Line text={clip(cap(overlay.subtitle), 30)} at={2} step={0.7} style={labelCss(k, 28, accent, "0.22em")} />
            ) : null}
            <Rise at={dropAt}>
              <Odometer value={cvV.v} at={dropAt} frames={Math.max(12, Math.round(allIn - dropAt))} size={170 * k} color="#fff"
                prefix={prefix} suffix={unitOf(cvV.suffix)} suffixScale={0.45} suffixColor={accent} />
            </Rise>
            {title.map((ln, i) => (
              <Line key={i} text={ln} at={dropAt + 6 + i * 4} step={0.7} delay={1 + i * 1.5} style={{ fontFamily: DISPLAY,
                fontSize: 56 * k, color: "#fff", letterSpacing: "0.03em", lineHeight: 1, whiteSpace: "nowrap" }} />
            ))}
            {unit !== 1 || suffix !== "" ? (
              <Rise at={allIn} style={{ marginTop: 10 * k }}>
                <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
                  <div style={{ width: 24 * k, height: 24 * k, borderRadius: 5 * k, background: accent }} />
                  <span style={labelCss(k, 30, "rgba(255,255,255,.75)", "0.08em")}>= {prefix}{fmt(cvU.v)}{unitOf(cvU.suffix)}</span>
                </div>
              </Rise>
            ) : null}
            {slots > n ? (
              <Rise at={allIn + 4}>
                <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
                  <div style={{ width: 24 * k, height: 24 * k, borderRadius: 5 * k, border: `${2 * k}px dashed rgba(255,255,255,.5)`,
                    boxSizing: "border-box" }} />
                  <span style={labelCss(k, 30, "rgba(255,255,255,.75)", "0.08em")}>OF {prefix}{fmt(cvT.v)}{unitOf(cvT.suffix)}</span>
                </div>
              </Rise>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "ns-times-bigger": TimesBars,
  "ns-fraction-pie": FractionPie,
  "ns-kpi-flip-grid": KpiGrid,
  "ns-before-after": BeforeAfter,
  "ns-change-meter": ChangeMeter,
  "ns-dual-gauge": DualGauge,
  "ns-podium": Podium,
  "ns-tug-of-war": TugOfWar,
  "ns-goal-track": GoalTrack,
  "ns-block-stack": BlockStack,
};
