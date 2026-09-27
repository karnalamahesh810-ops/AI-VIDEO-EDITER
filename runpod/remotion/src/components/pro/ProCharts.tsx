import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, Scrim, Tag, formatValue, ramp, useHold, useK } from "./ProGraphics";

/**
 * More charts, numbers and comparisons in the pro look (the owner: "more
 * charts and numbers animations and comparisons"). Same rules as
 * ProGraphics: numbers roll like odometers, headings rise letter by letter,
 * fills run on an ease-in-out after the numbers start, everything is sized
 * small enough to sit on footage and uses the blurred full-screen layout only
 * when the beat is a data scene.
 *
 *   ProLine     a line (or area) chart drawing through a series, the last
 *               value rolling at its end and the change in a pill
 *   ProShares   shares of a whole: a stacked 100% bar, or a pie
 *   ProRatio    "1 in 4": a row of people, the counted ones lit
 *   ProMeasure  a height or depth on a ruler: the level drops or rises
 *   ProRank     ranked rows, bars growing, the leader in the accent
 *   ProColumns  three or four values as columns of stacking tiles
 *   ProVersus   two values on two panels with a VS badge and the ratio
 *   ProDelta    before above after, an arrow and the change between
 *   ProBubbles  two or three quantities as circles drawn to scale
 *   ProTank     a percentage as a tank of water filling to its level
 *   ProPie      a percentage as a pie slice sweeping out
 *   ProSpark    a rise or a fall as a trend line racing across the frame
 *   ProStack    money as stacks of bills landing
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const RED = "#ff3b30";
const GREEN = "#27d17f";

type Num = OverlayItem & { value: number; suffix?: string; prefix?: string };
const nums = (items?: OverlayItem[]): Num[] =>
  (items || []).filter((i) => typeof i.value === "number" && Number.isFinite(i.value)) as Num[];
const fmt = (v: number) => formatValue(v).text;
const cap = (s?: string) => (s || "").toUpperCase();

/** A chart heading: its letters rise in (and drop out at the end), an accent bar beneath. */
export const Heading: React.FC<{ text?: string; accent: string; at?: number; size?: number; center?: boolean }> =
  ({ text, accent, at = 0, size = 58, center }) => {
    const frame = useCurrentFrame();
    const k = useK();
    if (!text) return null;
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: center ? "center" : "flex-start", gap: 10 * k }}>
        <LetterLine text={cap(text)} at={at} step={0.7} style={{ fontFamily: DISPLAY, fontSize: size * k, color: "#fff",
          letterSpacing: "0.04em", lineHeight: 1, textAlign: center ? "center" : "left",
          textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
        <div style={{ width: `${ramp(frame, at + 4, 16) * 110 * k}px`, height: 5 * k, background: accent }} />
      </div>
    );
  };

/** A small pill: the change between two values ("▼ 71%"). */
const DeltaPill: React.FC<{ from: number; to: number; at: number; size?: number; points?: boolean; unit?: string }> =
  ({ from, to, at, size = 40, points, unit = "" }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const down = to < from;
    const col = down ? RED : GREEN;
    const p = ramp(frame, at, 14, backOut);
    const pct = from ? ((to - from) / Math.abs(from)) * 100 : 0;
    const txt = points ? `${fmt(Math.abs(to - from))}${unit}`
      : `${Math.abs(pct) >= 10 ? Math.round(Math.abs(pct)) : Math.abs(pct).toFixed(1)}%`;
    return (
      <div style={{ display: "inline-flex", alignItems: "center", gap: 10 * k, background: col, color: "#fff",
        fontFamily: LABEL, fontWeight: 800, fontSize: size * k, letterSpacing: "0.04em", lineHeight: 1,
        padding: `${9 * k}px ${22 * k}px ${7 * k}px`, borderRadius: 60 * k, boxShadow: `0 0 ${24 * k}px ${col}77`,
        transform: `scale(${p})`, opacity: Math.min(1, p * 2), whiteSpace: "nowrap" }}>
        <span style={{ fontSize: size * 0.62 * k }}>{down ? "▼" : "▲"}</span>{txt}
      </div>
    );
  };

/** A round number at or above / below v (1, 2, 2.5, 5 x 10^n). */
const niceCeil = (v: number) => {
  if (v <= 0) return 0;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v - 1e-9) return m * p;
  return 10 * p;
};
const niceFloor = (v: number) => {
  if (v <= 0) return 0;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const ms = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8].filter((m) => m * p <= v + 1e-9);
  return (ms.length ? ms[ms.length - 1] : 1) * p;
};

// ================================================================== line / area
/** A series through time: the line draws point to point, each value pops as the head passes. */
export const ProLine: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const pts = nums(overlay.items).slice(0, 8);
  if (pts.length < 2) return null;
  const area = overlay.variant === "area" || overlay.type === "area-chart";
  const suffix = overlay.suffix || pts[pts.length - 1].suffix || "";
  const prefix = overlay.prefix || pts[pts.length - 1].prefix || "";
  const W = 1240 * k, H = 470 * k, padT = 90 * k;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const pctScale = suffix === "%" && hi <= 100 && lo >= 0;
  const base = lo >= 0 && lo / Math.max(hi, 1e-9) < 0.55 ? 0 : niceFloor(lo - span * 0.3);
  const top = pctScale ? Math.min(100, niceCeil(hi * 1.08)) : niceCeil(base + (hi - base) * 1.08);
  const X = (i: number) => (i / (pts.length - 1)) * W;
  const Y = (v: number) => padT + (1 - (v - base) / Math.max(1e-9, top - base)) * (H - padT);
  const P = pts.map((p, i) => [X(i), Y(p.value)] as [number, number]);
  const seg = P.slice(1).map((p, i) => Math.hypot(p[0] - P[i][0], p[1] - P[i][1]));
  const cum = [0];
  seg.forEach((l) => cum.push(cum[cum.length - 1] + l));
  const total = cum[cum.length - 1] || 1;
  const drawAt = Math.round(fps * 0.4);
  const drawFrames = Math.round(fps * (1.1 + 0.18 * pts.length));
  const d = ramp(frame, drawAt, drawFrames, inOut);
  const run = d * total;
  let hx = P[0][0], hy = P[0][1];
  for (let i = 0; i < seg.length; i++) {
    if (run <= cum[i + 1]) {
      const t = seg[i] ? (run - cum[i]) / seg[i] : 1;
      hx = P[i][0] + (P[i + 1][0] - P[i][0]) * t;
      hy = P[i][1] + (P[i + 1][1] - P[i][1]) * t;
      break;
    }
    hx = P[i + 1][0];
    hy = P[i + 1][1];
  }
  const passed = (i: number) => interpolate(run - cum[i], [-1, total * 0.05], [0, 1], clamp);
  const path = P.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const fill = `${path} L${W} ${H} L0 ${H} Z`;
  const last = pts[pts.length - 1];
  const first = pts[0];
  const done = drawAt + drawFrames;
  const id = `pl${overlay.startFrame}`;
  const grid = [0.25, 0.5, 0.75, 1].map((t) => base + (top - base) * t);
  const tick = (g: number) => (Math.abs(g) >= 100 || Number.isInteger(g) ? fmt(Math.round(g)) : fmt(Math.round(g * 10) / 10));
  const pulse = (frame % Math.round(fps * 1.2)) / Math.round(fps * 1.2);
  const down = last.value < first.value;
  const endX = P[P.length - 1][0], endY = P[P.length - 1][1];
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ position: "relative", width: W, display: "flex", flexDirection: "column", gap: 26 * k }}>
          <Heading text={overlay.text} accent={accent} />
          <div style={{ position: "relative", width: W, height: H + 60 * k }}>
            <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={accent} stopOpacity={area ? 0.55 : 0.26} />
                  <stop offset="100%" stopColor={accent} stopOpacity={0} />
                </linearGradient>
                <clipPath id={`${id}c`}><rect x={-20 * k} y={-40 * k} width={hx + 20 * k} height={H + 80 * k} /></clipPath>
              </defs>
              {grid.map((g, i) => (
                <g key={i} opacity={ramp(frame, 2 + i * 2, 12)}>
                  <line x1={0} x2={W} y1={Y(g)} y2={Y(g)} stroke="rgba(255,255,255,.13)" strokeWidth={1.5 * k}
                    strokeDasharray={`${6 * k} ${8 * k}`} />
                  <text x={-18 * k} y={Y(g) + 9 * k} textAnchor="end" fontFamily={LABEL} fontWeight={600}
                    fontSize={26 * k} fill="rgba(255,255,255,.55)">{tick(g)}{suffix === "%" ? "%" : ""}</text>
                </g>
              ))}
              <line x1={0} x2={W * ramp(frame, 0, 18, inOut)} y1={H} y2={H} stroke="rgba(255,255,255,.75)" strokeWidth={3 * k} />
              <path d={fill} fill={`url(#${id}g)`} clipPath={`url(#${id}c)`} />
              <path d={path} fill="none" stroke={accent} strokeWidth={7 * k} strokeLinejoin="round" strokeLinecap="round"
                strokeDasharray={`${total} ${total}`} strokeDashoffset={total * (1 - d)}
                style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}aa)` }} />
              {P.map(([x, y], i) => {
                const q = passed(i);
                return (
                  <g key={i} opacity={q > 0 ? 1 : 0}>
                    <line x1={x} x2={x} y1={y} y2={H} stroke="rgba(255,255,255,.18)" strokeWidth={2 * k}
                      strokeDasharray={`${4 * k} ${6 * k}`} opacity={q} />
                    <circle cx={x} cy={y} r={10 * k * interpolate(q, [0, 0.6, 1], [0, 1.35, 1])} fill="#0d0d10"
                      stroke={i === P.length - 1 ? accent : "#fff"} strokeWidth={4.5 * k} />
                  </g>
                );
              })}
              {d > 0 && d < 1 ? (
                <g>
                  <circle cx={hx} cy={hy} r={(14 + 26 * pulse) * k} fill="none" stroke={accent} strokeWidth={3 * k} opacity={1 - pulse} />
                  <circle cx={hx} cy={hy} r={11 * k} fill="#fff" style={{ filter: `drop-shadow(0 0 ${12 * k}px ${accent})` }} />
                </g>
              ) : null}
            </svg>
            {P.slice(0, -1).map(([x, y], i) => {
              const q = passed(i);
              return (
                <div key={i} style={{ position: "absolute", left: x - 90 * k, width: 180 * k, top: y - 58 * k, textAlign: "center",
                  fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, color: "#fff", opacity: q,
                  transform: `translateY(${(1 - q) * 14 * k}px)`, textShadow: "0 3px 12px rgba(0,0,0,.8)" }}>
                  {pts[i].prefix || prefix}{fmt(pts[i].value)}{suffix === "%" ? "%" : ""}
                </div>
              );
            })}
            <div style={{ position: "absolute", left: Math.min(W - 60 * k, endX) - 330 * k, width: 360 * k,
              top: endY > H * 0.45 ? endY - 170 * k : endY + 30 * k, display: "flex", flexDirection: "column", alignItems: "flex-end",
              gap: 8 * k, opacity: ramp(frame, done - 10, 10) }}>
              <Odometer value={last.value} at={done - 10} frames={Math.round(fps * 0.9)} size={96 * k} color="#fff"
                prefix={last.prefix || prefix} suffix={suffix} suffixColor={accent} suffixScale={0.5} />
              <DeltaPill from={first.value} to={last.value} at={done + 2} size={34} />
            </div>
            {pts.map((p, i) => (
              <div key={i} style={{ position: "absolute", left: X(i) - 110 * k, width: 220 * k, top: H + 16 * k, textAlign: "center",
                fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.08em",
                color: passed(i) > 0.5 ? "#fff" : "rgba(255,255,255,.5)", opacity: ramp(frame, 4 + i * 3, 12) }}>
                {cap(p.label)}
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== shares
const SHARE_COLORS = (accent: string) => [accent, "#f1f1f1", "#8f9199", "#4d5059", "#2ec4b6", "#6b4de6"];

/** Parts of a whole: a stacked bar filling segment by segment, or (variant "pie") a pie. */
export const ProShares: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  let items = nums(overlay.items).filter((i) => i.value > 0).slice(0, 5);
  if (!items.length) return null;
  const sum = items.reduce((a, i) => a + i.value, 0);
  if (sum < 99 && sum > 0) items = [...items, { label: "Other", value: Math.round((100 - sum) * 10) / 10 } as Num];
  const totalV = items.reduce((a, i) => a + i.value, 0) || 1;
  const colors = SHARE_COLORS(accent);
  const step = Math.round(fps * 0.42);
  const at0 = Math.round(fps * 0.35);
  const g = (i: number) => ramp(frame, at0 + i * step, Math.round(fps * 0.6), inOut);

  if (overlay.variant === "pie") {
    const R = 230 * k;
    const S = 2 * R + 120 * k;
    const cx = S / 2, cy = S / 2;
    let acc = 0;
    const arcs = items.map((it, i) => {
      const a0 = (acc / totalV) * Math.PI * 2 - Math.PI / 2;
      acc += it.value;
      const a1full = (acc / totalV) * Math.PI * 2 - Math.PI / 2;
      const a1 = a0 + (a1full - a0) * g(i);
      const mid = (a0 + a1full) / 2;
      const pop = i === 0 ? ramp(frame, at0 + items.length * step + 4, 14, backOut) * 18 * k : 0;
      const ox = Math.cos(mid) * pop, oy = Math.sin(mid) * pop;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      const whole = a1 - a0 >= Math.PI * 2 - 1e-3;
      const dPath = g(i) <= 0.001 ? "" : whole
        ? `M${cx} ${cy - R} A${R} ${R} 0 1 1 ${cx - 0.01} ${cy - R} Z`
        : `M${cx + ox} ${cy + oy} L${cx + ox + R * Math.cos(a0)} ${cy + oy + R * Math.sin(a0)} ` +
          `A${R} ${R} 0 ${large} 1 ${cx + ox + R * Math.cos(a1)} ${cy + oy + R * Math.sin(a1)} Z`;
      return { i, dPath };
    });
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 70 * k }}>
            <svg width={S} height={S} style={{ overflow: "visible", filter: "drop-shadow(0 20px 40px rgba(0,0,0,.45))" }}>
              <circle cx={cx} cy={cy} r={R} fill="rgba(255,255,255,.08)" opacity={ramp(frame, 0, 10)} />
              {arcs.map(({ dPath, i }) => (dPath ? <path key={i} d={dPath} fill={colors[i % colors.length]}
                stroke="#0c0c0f" strokeWidth={4 * k} strokeLinejoin="round" /> : null))}
            </svg>
            <div style={{ display: "flex", flexDirection: "column", gap: 22 * k, minWidth: 420 * k }}>
              <Heading text={overlay.text} accent={accent} size={52} />
              {items.map((it, i) => {
                const at = at0 + i * step;
                return (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 18 * k, opacity: ramp(frame, at, 10),
                    transform: `translateX(${(1 - ramp(frame, at, 14)) * 30 * k}px)` }}>
                    <div style={{ width: 26 * k, height: 26 * k, borderRadius: 6 * k, background: colors[i % colors.length] }} />
                    <Odometer value={it.value} at={at} frames={Math.round(fps * 0.8)} size={i === 0 ? 86 * k : 58 * k}
                      color={i === 0 ? accent : "#fff"} suffix="%" suffixScale={0.5} />
                    <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: (i === 0 ? 38 : 32) * k, color: "#fff",
                      letterSpacing: "0.06em" }}>{cap(it.label)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  const W = 1380 * k, BH = 84 * k;
  let left = 0;
  const segs = items.map((it, i) => {
    const w = (it.value / totalV) * W;
    const s = { it, i, x: left, w };
    left += w;
    return s;
  });
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ width: W, display: "flex", flexDirection: "column", gap: 34 * k }}>
          <Heading text={overlay.text} accent={accent} />
          <div style={{ position: "relative", width: W, height: BH + 260 * k }}>
            <div style={{ position: "absolute", left: 0, top: 150 * k, width: W, height: BH, borderRadius: 14 * k,
              background: "rgba(255,255,255,.08)", overflow: "hidden", opacity: ramp(frame, 0, 10),
              boxShadow: "inset 0 2px 12px rgba(0,0,0,.45)" }}>
              {segs.map(({ i, x, w }) => (
                <div key={i} style={{ position: "absolute", left: x, top: 0, bottom: 0, width: w * g(i),
                  background: colors[i % colors.length], borderRight: g(i) > 0.02 ? `${3 * k}px solid #0c0c0f` : "none" }} />
              ))}
            </div>
            {segs.map(({ it, i, x, w }) => {
              const above = i % 2 === 0 || w > 260 * k;
              const at = at0 + i * step;
              const q = ramp(frame, at + 6, 14);
              return (
                <div key={i} style={{ position: "absolute", left: x, width: Math.max(w, 200 * k),
                  top: above ? 0 : 150 * k + BH + 16 * k, display: "flex", flexDirection: "column", alignItems: "flex-start",
                  gap: 4 * k, opacity: q, transform: `translateY(${(1 - q) * (above ? 16 : -16) * k}px)` }}>
                  {above ? (
                    <>
                      <Odometer value={it.value} at={at} frames={Math.round(fps * 0.8)} size={(i === 0 ? 92 : 64) * k}
                        color={i === 0 ? accent : "#fff"} suffix="%" suffixScale={0.5} />
                      <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, color: "rgba(255,255,255,.88)",
                        letterSpacing: "0.08em", whiteSpace: "nowrap" }}>{cap(it.label)}</span>
                    </>
                  ) : (
                    <>
                      <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, color: "rgba(255,255,255,.88)",
                        letterSpacing: "0.08em", whiteSpace: "nowrap" }}>{cap(it.label)}</span>
                      <Odometer value={it.value} at={at} frames={Math.round(fps * 0.8)} size={60 * k} color="#fff"
                        suffix="%" suffixScale={0.5} />
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ratio
const Person: React.FC<{ size: number; color: string; glow?: string }> = ({ size, color, glow }) => (
  <svg width={size * 0.42} height={size} viewBox="0 0 42 100" style={{ overflow: "visible", display: "block",
    filter: glow ? `drop-shadow(0 0 ${size * 0.08}px ${glow})` : undefined }}>
    <circle cx="21" cy="13" r="11" fill={color} />
    <path d="M7 36 Q7 28 15 28 H27 Q35 28 35 36 V60 Q35 64 31 64 H30 V95 Q30 99 26 99 H24 Q22 99 22 95 V68 H20 V95 Q20 99 18 99 H16 Q12 99 12 95 V64 H11 Q7 64 7 60 Z"
      fill={color} />
  </svg>
);

/** "1 in 4": people pop in, the counted ones light up, the ratio rolls. */
export const ProRatio: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const pct = (overlay.suffix || "").trim() === "%";
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const total = Math.round(Number(overlay.total ?? (pct ? 10 : NaN)));
  if (!Number.isFinite(total) || total < 2 || total > 100) return null;
  const lit = Math.max(0, Math.min(total, Math.round(pct ? value / 10 : value)));
  const small = total > 20;
  const cols = small ? 10 : total > 10 ? Math.ceil(total / 2) : total;
  const size = (small ? 62 : total > 10 ? 118 : total > 6 ? 150 : 180) * k;
  const popAt = Math.round(fps * 0.2);
  const litAt = popAt + Math.min(total, 30) * 2 + Math.round(fps * 0.25);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 44 * k,
        transform: `scale(${hold})` }}>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, auto)`, columnGap: (small ? 12 : 26) * k,
          rowGap: (small ? 14 : 22) * k, alignItems: "end" }}>
          {Array.from({ length: total }, (_, i) => {
            const p = ramp(frame, popAt + Math.min(i, 30) * 2, 12, backOut);
            const on = i < lit;
            const q = on ? ramp(frame, litAt + i * 3, 10) : 0;
            const jump = on ? interpolate(frame, [litAt + i * 3, litAt + i * 3 + 6, litAt + i * 3 + 14], [0, -14 * k, 0], clamp) : 0;
            const col = on && q > 0.5 ? accent : "rgba(255,255,255,.28)";
            return (
              <div key={i} style={{ transform: `translateY(${jump}px) scale(${p})`, transformOrigin: "50% 100%",
                opacity: Math.min(1, p) }}>
                <Person size={size} color={col} glow={on && q > 0.5 ? accent : undefined} />
              </div>
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 20 * k, opacity: ramp(frame, litAt - 6, 10) }}>
          <Odometer value={pct ? value : lit} at={litAt - 6} frames={Math.round(fps * 0.8)} size={150 * k} color={accent}
            suffix={pct ? "%" : ""} suffixScale={0.5} />
          {!pct ? (
            <>
              <span style={{ fontFamily: DISPLAY, fontSize: 84 * k, color: "rgba(255,255,255,.75)" }}>IN</span>
              <Odometer value={total} at={litAt - 2} frames={Math.round(fps * 0.8)} size={150 * k} color="#fff" />
            </>
          ) : null}
        </div>
        <Tag text={cap(overlay.text)} at={litAt + 6} accent={accent} size={32} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== measure
const niceMax = (v: number) => {
  const target = Math.abs(v) * 1.3 || 1;
  const p = Math.pow(10, Math.floor(Math.log10(target)));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= target) return m * p;
  return 10 * p;
};

/** A height or a depth on a ruler: the level falls (or rises) by the amount, the lost band hatched. */
export const ProMeasure: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Math.abs(Number(overlay.value ?? NaN));
  if (!Number.isFinite(value) || value === 0) return null;
  const dir = (overlay.label || "").toLowerCase();
  const down = dir === "down";
  const up = dir === "up";
  const unit = overlay.suffix || "";
  const max = niceMax(value);
  const H = 540 * k, RW = 150 * k;
  const yOf = (v: number) => H - (v / max) * H;
  const moveAt = Math.round(fps * 0.45);
  const g = ramp(frame, moveAt, Math.round(fps * 1.4), inOut);
  const from = down ? value : 0;
  const to = down ? 0 : value;
  const level = from + (to - from) * g;
  const col = down ? RED : up ? GREEN : accent;
  const ticks = Array.from({ length: 21 }, (_, i) => (max / 20) * i);
  const id = `pm${overlay.startFrame}`;
  const bandTop = yOf(Math.max(from, level)), bandBot = yOf(Math.min(from, level));
  const arrowOn = g > 0.08 ? 1 : 0;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 90 * k }}>
          <div style={{ position: "relative", width: RW + 330 * k, height: H, opacity: ramp(frame, 0, 10) }}>
            <svg width={RW + 330 * k} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <pattern id={`${id}h`} width={16 * k} height={16 * k} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <line x1={0} y1={0} x2={0} y2={16 * k} stroke={col} strokeWidth={5 * k} strokeOpacity={0.45} />
                </pattern>
              </defs>
              <rect x={0} y={0} width={RW} height={H} rx={10 * k} fill="rgba(10,10,14,.55)" stroke="rgba(255,255,255,.55)"
                strokeWidth={3 * k} />
              {ticks.map((t, i) => {
                const major = i % 5 === 0;
                return (
                  <g key={i} opacity={ramp(frame, 2 + i, 8)}>
                    <line x1={RW - (major ? 60 : 30) * k} x2={RW} y1={yOf(t)} y2={yOf(t)} stroke="rgba(255,255,255,.8)"
                      strokeWidth={(major ? 3.5 : 2) * k} />
                    {major ? <text x={RW - 72 * k} y={yOf(t) + 10 * k} textAnchor="end" fontFamily={LABEL} fontWeight={700}
                      fontSize={28 * k} fill="rgba(255,255,255,.8)">{fmt(t)}</text> : null}
                  </g>
                );
              })}
              {down || up ? (
                <>
                  <rect x={RW + 10 * k} y={bandTop} width={300 * k} height={Math.max(0, bandBot - bandTop)} fill={`url(#${id}h)`} />
                  <line x1={RW + 10 * k} x2={RW + 310 * k} y1={yOf(from)} y2={yOf(from)} stroke="rgba(255,255,255,.55)"
                    strokeWidth={3 * k} strokeDasharray={`${10 * k} ${8 * k}`} />
                  <line x1={0} x2={RW + 310 * k} y1={yOf(level)} y2={yOf(level)} stroke={col} strokeWidth={7 * k}
                    style={{ filter: `drop-shadow(0 0 ${12 * k}px ${col})` }} />
                  <path d={`M${RW + 250 * k} ${yOf(from)} V${yOf(level) + (down ? -14 : 14) * k}`} stroke="#fff"
                    strokeWidth={5 * k} opacity={arrowOn} />
                  <path d={down
                    ? `M${RW + 236 * k} ${yOf(level) - 20 * k} L${RW + 250 * k} ${yOf(level) - 2 * k} L${RW + 264 * k} ${yOf(level) - 20 * k}`
                    : `M${RW + 236 * k} ${yOf(level) + 20 * k} L${RW + 250 * k} ${yOf(level) + 2 * k} L${RW + 264 * k} ${yOf(level) + 20 * k}`}
                    fill="none" stroke="#fff" strokeWidth={5 * k} strokeLinejoin="round" opacity={arrowOn} />
                </>
              ) : (
                <rect x={RW + 70 * k} y={yOf(level)} width={120 * k} height={H - yOf(level)} rx={8 * k}
                  fill={accent} style={{ filter: `drop-shadow(0 0 ${18 * k}px ${accent}88)` }} />
              )}
            </svg>
            <div style={{ position: "absolute", left: 0, top: -54 * k, width: RW, textAlign: "center", fontFamily: LABEL,
              fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.14em", color: "rgba(255,255,255,.75)" }}>{unit}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 * k, maxWidth: 640 * k }}>
            {overlay.subtitle ? (
              <LetterLine text={cap(overlay.subtitle)} at={2} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k,
                letterSpacing: "0.22em", color: accent }} />
            ) : null}
            <Odometer value={value} at={moveAt} frames={Math.round(fps * 1.3)} size={190 * k} color="#fff"
              prefix={down ? "−" : up ? "+" : ""} suffix={unit ? ` ${unit}` : ""} suffixScale={0.36} suffixColor={col} />
            <Tag text={cap(overlay.text)} at={moveAt + 18} accent={col} size={32} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ranking
/** Ranked rows: number, name, a bar growing to its value; the leader in the accent. */
export const ProRank: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const items = nums(overlay.items).slice(0, 6).sort((a, b) => b.value - a.value);
  if (items.length < 2) return null;
  const max = Math.max(...items.map((i) => i.value), 1e-9);
  const suffix = overlay.suffix || items[0].suffix || "";
  const prefix = overlay.prefix || items[0].prefix || "";
  const BW = 760 * k, RH = (items.length > 4 ? 70 : 84) * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 30 * k }}>
          <Heading text={overlay.text} accent={accent} />
          <div style={{ display: "flex", flexDirection: "column", gap: 16 * k }}>
            {items.map((it, i) => {
              const at = Math.round(fps * 0.25) + i * 5;
              const q = ramp(frame, at, 14);
              const gr = ramp(frame, at + 6, Math.round(fps * 1.0), inOut);
              const lead = i === 0;
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 22 * k, height: RH, opacity: q,
                  transform: `translateX(${(1 - q) * -40 * k}px)` }}>
                  <span style={{ width: 90 * k, fontFamily: DISPLAY, fontSize: RH * 0.86, color: lead ? accent : "rgba(255,255,255,.5)",
                    textAlign: "right" }}>{String(i + 1).padStart(2, "0")}</span>
                  <span style={{ width: 330 * k, fontFamily: LABEL, fontWeight: 800, fontSize: RH * 0.46, color: "#fff",
                    letterSpacing: "0.06em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{cap(it.label)}</span>
                  <div style={{ position: "relative", width: BW, height: RH * 0.56, borderRadius: 8 * k, background: "rgba(255,255,255,.08)" }}>
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${gr * (it.value / max) * 100}%`,
                      borderRadius: 8 * k,
                      background: lead ? `linear-gradient(90deg, ${accent}bb, ${accent})` : "linear-gradient(90deg, #9a9aa2, #e9e9ee)",
                      boxShadow: lead ? `0 0 ${20 * k}px ${accent}77` : "none" }} />
                    <div style={{ position: "absolute", left: `calc(${gr * (it.value / max) * 100}% + ${14 * k}px)`, top: "50%",
                      transform: "translateY(-50%)" }}>
                      <Odometer value={it.value} at={at + 6} frames={Math.round(fps * 1.0)} size={RH * 0.62}
                        color={lead ? accent : "#fff"} prefix={it.prefix || prefix} suffix={suffix === "%" ? "%" : ""} suffixScale={0.6} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== columns of tiles
/** Three or four values as columns of tiles stacking up, the biggest in the accent. */
export const ProColumns: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const items = nums(overlay.items).slice(0, 4);
  if (items.length < 2) return null;
  const max = Math.max(...items.map((i) => i.value), 1e-9);
  const hi = items.reduce((m, it, i) => (it.value > items[m].value ? i : m), 0);
  const TILE = 50 * k, GAP = 8 * k, ROWS = 9;
  const suffix = overlay.suffix || items[0].suffix || "";
  const prefix = overlay.prefix || items[0].prefix || "";
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 34 * k }}>
          <Heading text={overlay.text} accent={accent} center />
          <div style={{ display: "flex", alignItems: "flex-end", gap: 80 * k }}>
            {items.map((it, i) => {
              const n = Math.max(1, Math.round((it.value / max) * ROWS));
              const at = Math.round(fps * 0.3) + i * 6;
              const hot = i === hi;
              const w = 2 * TILE + GAP;
              return (
                <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 * k, width: 300 * k }}>
                  <Odometer value={it.value} at={at + n * 2} frames={Math.round(fps * 0.9)} size={78 * k}
                    color={hot ? accent : "#fff"} prefix={it.prefix || prefix}
                    suffix={suffix ? (suffix === "%" ? "%" : ` ${suffix}`) : ""} suffixScale={0.5} />
                  <div style={{ display: "flex", flexDirection: "column-reverse", gap: GAP, width: w, height: ROWS * (TILE + GAP) }}>
                    {Array.from({ length: n }, (_, t) => {
                      const p = ramp(frame, at + t * 3, 10, backOut);
                      return (
                        <div key={t} style={{ display: "flex", gap: GAP, opacity: Math.min(1, p * 1.5),
                          transform: `translateY(${(1 - p) * -40 * k}px)` }}>
                          {[0, 1].map((c) => (
                            <div key={c} style={{ width: TILE, height: TILE, borderRadius: 8 * k,
                              background: hot ? accent : "rgba(255,255,255,.85)",
                              boxShadow: hot ? `0 0 ${14 * k}px ${accent}66` : "none" }} />
                          ))}
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ width: w + 60 * k, height: 4 * k, background: "rgba(255,255,255,.7)" }} />
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, color: hot ? accent : "#fff",
                    letterSpacing: "0.08em", textAlign: "center", opacity: ramp(frame, at, 12) }}>{cap(it.label)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== versus
/** Two values on two panels sliding in from their sides, a VS badge, the ratio between. */
export const ProVersus: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const [a, b] = nums(overlay.items);
  if (!a || !b) return null;
  const suffix = (b.suffix || a.suffix || overlay.suffix || "").trim();
  const inA = ramp(frame, 0, 16), inB = ramp(frame, 4, 16);
  const vs = ramp(frame, 12, 14, backOut);
  const flash = interpolate(frame, [12, 26], [0, 1], clamp);
  const big = Math.max(Math.abs(a.value), Math.abs(b.value));
  const small = Math.min(Math.abs(a.value), Math.abs(b.value)) || 1e-9;
  const ratio = big / small;
  const bBigger = Math.abs(b.value) >= Math.abs(a.value);
  const panel = (it: Num, side: "l" | "r", p: number, hot: boolean) => (
    <div style={{ width: 620 * k, height: 400 * k, display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", gap: 16 * k, borderRadius: 22 * k,
      background: hot ? `linear-gradient(160deg, ${accent}40, rgba(14,14,18,.82) 70%)`
        : "linear-gradient(160deg, rgba(255,255,255,.1), rgba(14,14,18,.82) 70%)",
      border: `${2 * k}px solid ${hot ? accent : "rgba(255,255,255,.25)"}`, backdropFilter: "blur(10px)",
      boxShadow: hot ? `0 30px 80px rgba(0,0,0,.5), 0 0 ${40 * k}px ${accent}33` : "0 30px 80px rgba(0,0,0,.5)",
      opacity: p, transform: `translateX(${(1 - p) * (side === "l" ? -140 : 140) * k}px)` }}>
      <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 40 * k, letterSpacing: "0.16em",
        color: hot ? accent : "rgba(255,255,255,.8)" }}>{cap(it.label)}</span>
      <Odometer value={it.value} at={side === "l" ? 8 : 12} frames={Math.round(fps * 1.1)} size={140 * k} color="#fff"
        prefix={it.prefix || overlay.prefix || ""} suffix={suffix ? (suffix === "%" ? "%" : ` ${suffix}`) : ""} suffixScale={0.4}
        suffixColor={hot ? accent : "rgba(255,255,255,.75)"} />
    </div>
  );
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 40 * k }}>
        <Heading text={overlay.text} accent={accent} center />
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 120 * k }}>
          {panel(a, "l", inA, !bBigger)}
          {panel(b, "r", inB, bBigger)}
          <div style={{ position: "absolute", left: "50%", top: "50%", width: 150 * k, height: 150 * k,
            transform: `translate(-50%, -50%) scale(${vs})`, borderRadius: "50%", background: "#0d0d10",
            border: `${5 * k}px solid ${accent}`, display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: `0 0 ${40 * k}px ${accent}88` }}>
            <span style={{ fontFamily: DISPLAY, fontSize: 74 * k, color: "#fff", marginTop: 6 * k }}>VS</span>
          </div>
          <div style={{ position: "absolute", left: "50%", top: "50%", width: 150 * k, height: 150 * k, borderRadius: "50%",
            transform: `translate(-50%, -50%) scale(${1 + flash * 1.6})`, border: `${4 * k}px solid ${accent}`,
            opacity: (1 - flash) * (flash > 0 ? 1 : 0) }} />
          {ratio >= 1.25 && Number.isFinite(ratio) ? (
            <div style={{ position: "absolute", left: "50%", top: `calc(50% + ${118 * k}px)`, transform: "translateX(-50%)",
              opacity: ramp(frame, Math.round(fps * 1.3), 12) }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 * k, background: accent, color: "#0c0c0f",
                fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k, padding: `${6 * k}px ${18 * k}px ${4 * k}px`,
                borderRadius: 40 * k, whiteSpace: "nowrap" }}>
                {!bBigger ? "◀ " : ""}{ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}×{bBigger ? " ▶" : ""}
              </div>
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== delta
/** Before above after: the first value small, an arrow drawing down, the change in a pill, the new value big. */
export const ProDelta: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const [a, b] = nums(overlay.items);
  if (!a || !b) return null;
  const suffix = (b.suffix || a.suffix || overlay.suffix || "").trim();
  const suf = suffix ? (suffix === "%" ? "%" : ` ${suffix}`) : "";
  const down = b.value < a.value;
  const col = down ? RED : GREEN;
  const arrow = ramp(frame, Math.round(fps * 0.7), 16, inOut);
  const points = suffix === "%";
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 80 * k }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 * k }}>
            {overlay.text ? <Heading text={overlay.text} accent={accent} size={48} /> : null}
            <div style={{ display: "flex", alignItems: "baseline", gap: 22 * k, marginTop: 18 * k, opacity: ramp(frame, 2, 12) }}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k, letterSpacing: "0.14em",
                color: "rgba(255,255,255,.6)", minWidth: 150 * k }}>{cap(a.label)}</span>
              <Odometer value={a.value} at={4} frames={Math.round(fps * 0.9)} size={96 * k} color="rgba(255,255,255,.72)"
                prefix={a.prefix || overlay.prefix || ""} suffix={suf} suffixScale={0.45} />
            </div>
            <svg width={120 * k} height={120 * k} viewBox="0 0 60 60" style={{ marginLeft: 170 * k }}>
              <path d="M30 4 V50 M16 38 L30 54 L44 38" fill="none" stroke={col} strokeWidth={6} strokeLinecap="round"
                strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - arrow}
                style={{ filter: `drop-shadow(0 0 6px ${col})` }} />
            </svg>
            <div style={{ display: "flex", alignItems: "baseline", gap: 22 * k, opacity: ramp(frame, Math.round(fps * 0.9), 12) }}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 40 * k, letterSpacing: "0.14em", color: accent,
                minWidth: 150 * k }}>{cap(b.label)}</span>
              <Odometer value={b.value} at={Math.round(fps * 0.9)} frames={Math.round(fps * 1.1)} size={170 * k} color="#fff"
                prefix={b.prefix || overlay.prefix || ""} suffix={suf} suffixScale={0.42} suffixColor={accent} />
            </div>
          </div>
          <DeltaPill from={a.value} to={b.value} at={Math.round(fps * 1.6)} size={58} points={points} unit={points ? " PTS" : ""} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== bubbles
/** Quantities as circles drawn to scale (area), growing in turn, the ratio between them. */
export const ProBubbles: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const items = nums(overlay.items).filter((i) => i.value > 0).slice(0, 3);
  if (items.length < 2) return null;
  const max = Math.max(...items.map((i) => i.value));
  const min = Math.min(...items.map((i) => i.value));
  const RMAX = 240 * k;
  const suffix = overlay.suffix || items[0].suffix || "";
  const hi = items.findIndex((i) => i.value === max);
  const ratio = max / min;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 30 * k,
        transform: `scale(${hold})` }}>
        <Heading text={overlay.text} accent={accent} center />
        <div style={{ display: "flex", alignItems: "flex-end", gap: 70 * k }}>
          {items.map((it, i) => {
            const r = Math.max(16 * k, RMAX * Math.sqrt(it.value / max));
            const at = Math.round(fps * 0.3) + i * 8;
            const p = ramp(frame, at, 20, backOut);
            const hot = i === hi;
            const inside = r > 95 * k;
            const numSize = Math.max(44 * k, Math.min(100 * k, r * 0.5));
            return (
              <React.Fragment key={i}>
                {i === 1 && items.length === 2 && ratio >= 1.5 ? (
                  <div style={{ alignSelf: "center", fontFamily: DISPLAY, fontSize: 90 * k, color: accent,
                    opacity: ramp(frame, at + 16, 12), marginBottom: 60 * k }}>×{ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}</div>
                ) : null}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 * k }}>
                  {!inside ? (
                    <Odometer value={it.value} at={at + 4} frames={Math.round(fps * 0.9)} size={62 * k} color={hot ? accent : "#fff"}
                      prefix={it.prefix || overlay.prefix || ""} suffix={suffix ? ` ${suffix}` : ""} suffixScale={0.45} />
                  ) : null}
                  <div style={{ width: 2 * r, height: 2 * r, borderRadius: "50%", transform: `scale(${p})`, transformOrigin: "50% 100%",
                    background: hot ? `radial-gradient(circle at 35% 30%, ${accent}, ${accent}aa 70%)`
                      : "radial-gradient(circle at 35% 30%, #ffffff, #b8b8bf 75%)",
                    boxShadow: hot ? `0 0 ${50 * k}px ${accent}66` : "0 20px 50px rgba(0,0,0,.45)", display: "flex",
                    alignItems: "center", justifyContent: "center" }}>
                    {inside ? (
                      <Odometer value={it.value} at={at + 4} frames={Math.round(fps * 0.9)} size={numSize} color="#0c0c0f"
                        prefix={it.prefix || overlay.prefix || ""} suffix={suffix ? ` ${suffix}` : ""} suffixScale={0.42} />
                    ) : null}
                  </div>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.1em",
                    color: hot ? accent : "#fff", opacity: ramp(frame, at + 6, 12) }}>{cap(it.label)}</span>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== tank
/** A percentage as a tank of water filling to its level, the surface rippling. */
export const ProTank: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const pct = Math.max(0, Math.min(100, value));
  const W = 340 * k, H = 480 * k;
  const numAt = Math.round(fps * 0.3);
  const lvl = ramp(frame, numAt, Math.round(fps * 1.6), inOut) * pct / 100;
  const surface = H - lvl * H;
  const amp = 9 * k, wl = 180 * k;
  const wave = (phase: number, a: number) => {
    let dd = `M0 ${surface}`;
    for (let x = 0; x <= W + 1; x += 12 * k) {
      dd += ` L${x.toFixed(1)} ${(surface + Math.sin((x / wl) * Math.PI * 2 + phase) * a).toFixed(1)}`;
    }
    return `${dd} L${W} ${H} L0 ${H} Z`;
  };
  const ph = (frame / fps) * 2.4;
  const id = `pt${overlay.startFrame}`;
  const title = cap(overlay.subtitle);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 34 * k,
        transform: `scale(${hold})` }}>
        {title ? <Heading text={title} accent={accent} center size={52} /> : null}
        <div style={{ display: "flex", alignItems: "center", gap: 80 * k }}>
          <div style={{ position: "relative", width: W + 110 * k, height: H, opacity: ramp(frame, 0, 10) }}>
            <svg width={W + 110 * k} height={H} style={{ overflow: "visible" }}>
              <defs>
                <clipPath id={`${id}c`}><rect x={0} y={0} width={W} height={H} rx={26 * k} /></clipPath>
                <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#5cc2ff" />
                  <stop offset="100%" stopColor="#0b3f78" />
                </linearGradient>
              </defs>
              <rect x={0} y={0} width={W} height={H} rx={26 * k} fill="rgba(8,12,18,.55)" />
              <g clipPath={`url(#${id}c)`}>
                <path d={wave(ph + 1.7, amp * 0.8)} fill="#2d86d6" opacity={0.55} />
                <path d={wave(ph, amp)} fill={`url(#${id}w)`} />
                {[0.2, 0.45, 0.7, 0.85].map((fx, i) => {
                  const t = ((frame / fps) * 0.35 + i * 0.27) % 1;
                  const by = H - t * lvl * H;
                  return lvl > 0.05 ? <circle key={i} cx={fx * W} cy={by} r={(4 + i) * k} fill="rgba(255,255,255,.35)" opacity={1 - t} /> : null;
                })}
              </g>
              <rect x={0} y={0} width={W} height={H} rx={26 * k} fill="none" stroke="rgba(255,255,255,.9)" strokeWidth={5 * k} />
              <rect x={14 * k} y={18 * k} width={10 * k} height={H - 36 * k} rx={5 * k} fill="rgba(255,255,255,.18)" />
              {[25, 50, 75, 100].map((t) => (
                <g key={t} opacity={ramp(frame, 4, 12)}>
                  <line x1={W} x2={W + 26 * k} y1={H - (t / 100) * H} y2={H - (t / 100) * H} stroke="rgba(255,255,255,.75)" strokeWidth={3 * k} />
                  <text x={W + 34 * k} y={H - (t / 100) * H + 9 * k} fontFamily={LABEL} fontWeight={700} fontSize={26 * k}
                    fill="rgba(255,255,255,.7)">{t === 100 ? "FULL" : `${t}%`}</text>
                </g>
              ))}
              <line x1={-18 * k} x2={W + 18 * k} y1={surface} y2={surface} stroke="#fff" strokeWidth={3 * k}
                strokeDasharray={`${10 * k} ${8 * k}`} opacity={ramp(frame, numAt + 20, 10)} />
            </svg>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 * k }}>
            <Odometer value={value} at={numAt} frames={Math.round(fps * 1.5)} size={190 * k} color="#fff" suffix="%"
              suffixColor={accent} suffixScale={0.5} />
            <Tag text={cap(overlay.text)} at={numAt + 16} accent={accent} size={32} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== pie
/** A percentage as a pie: the slice sweeps round, then eases out of the pie. */
export const ProPie: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const pct = Math.max(0, Math.min(100, value)) / 100;
  const R = 210 * k, S = 2 * R + 80 * k, cx = S / 2, cy = S / 2;
  const numAt = Math.round(fps * 0.3);
  const g = ramp(frame, numAt, Math.round(fps * 1.2), inOut) * pct;
  const a0 = -Math.PI / 2, a1 = a0 + g * Math.PI * 2;
  const mid = a0 + pct * Math.PI;
  const pop = ramp(frame, numAt + Math.round(fps * 1.2), 14, backOut) * 22 * k;
  const ox = Math.cos(mid) * pop, oy = Math.sin(mid) * pop;
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const slice = g <= 0.001 || g >= 0.999 ? "" :
    `M${cx + ox} ${cy + oy} L${cx + ox + R * Math.cos(a0)} ${cy + oy + R * Math.sin(a0)} ` +
    `A${R} ${R} 0 ${large} 1 ${cx + ox + R * Math.cos(a1)} ${cy + oy + R * Math.sin(a1)} Z`;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 80 * k }}>
          <svg width={S} height={S} style={{ overflow: "visible", opacity: ramp(frame, 0, 10) }}>
            <circle cx={cx} cy={cy} r={R} fill="rgba(255,255,255,.14)" stroke="rgba(255,255,255,.5)" strokeWidth={3 * k} />
            {[0, 0.25, 0.5, 0.75].map((t) => (
              <line key={t} x1={cx} y1={cy} x2={cx + R * Math.cos(-Math.PI / 2 + t * Math.PI * 2)}
                y2={cy + R * Math.sin(-Math.PI / 2 + t * Math.PI * 2)} stroke="rgba(255,255,255,.15)" strokeWidth={2 * k} />
            ))}
            {g >= 0.999 ? <circle cx={cx} cy={cy} r={R} fill={accent} /> : null}
            {slice ? <path d={slice} fill={accent} stroke="#0c0c0f" strokeWidth={4 * k} strokeLinejoin="round"
              style={{ filter: `drop-shadow(0 0 ${22 * k}px ${accent}88)` }} /> : null}
          </svg>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 * k }}>
            {overlay.subtitle ? <Heading text={overlay.subtitle} accent={accent} size={46} /> : null}
            <Odometer value={value} at={numAt} frames={Math.round(fps * 1.3)} size={190 * k} color="#fff" suffix="%"
              suffixColor={accent} suffixScale={0.5} />
            <Tag text={cap(overlay.text)} at={numAt + 16} accent={accent} size={32} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== spark
const jag = (seed: number, n: number): number[] => {
  let s = Math.floor(Math.abs(Math.sin(seed * 12.9898) * 43758.5453) * 233280) % 233280;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    s = (s * 9301 + 49297) % 233280;
    out.push(s / 233280);
  }
  return out;
};

/** A rise or a fall: a trend line races across the frame behind the amount, red down, green up. */
export const ProSpark: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const down = (overlay.label || "").toLowerCase() !== "up";
  const col = down ? RED : GREEN;
  const N = 16;
  const r = jag(value + 7, N);
  const x0 = width * 0.06, x1 = width * 0.94;
  const yTop = height * 0.32, yBot = height * 0.82;
  const pts = r.map((q, i) => {
    const t = i / (N - 1);
    const trend = down ? yTop + (yBot - yTop) * t : yBot - (yBot - yTop) * t;
    const noise = (q - 0.5) * (height * 0.12) * (i === 0 || i === N - 1 ? 0 : 1);
    return [x0 + (x1 - x0) * t, trend + noise] as [number, number];
  });
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const d = ramp(frame, 2, Math.round(fps * 1.5), inOut);
  const idx = Math.min(N - 2, Math.floor(d * (N - 1)));
  const f = Math.min(1, d * (N - 1) - idx);
  const hx = pts[idx][0] + (pts[idx + 1][0] - pts[idx][0]) * f;
  const hy = pts[idx][1] + (pts[idx + 1][1] - pts[idx][1]) * f;
  const id = `ps${overlay.startFrame}`;
  const numAt = Math.round(fps * 0.35);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={col} stopOpacity={0.35} />
            <stop offset="100%" stopColor={col} stopOpacity={0} />
          </linearGradient>
          <clipPath id={`${id}c`}><rect x={0} y={0} width={Math.max(0, hx)} height={height} /></clipPath>
        </defs>
        <path d={`${path} L${x1} ${height} L${x0} ${height} Z`} fill={`url(#${id}g)`} clipPath={`url(#${id}c)`} />
        <path d={path} fill="none" stroke={col} strokeWidth={8 * k} strokeLinejoin="round" strokeLinecap="round"
          pathLength={1} strokeDasharray={1} strokeDashoffset={1 - d} style={{ filter: `drop-shadow(0 0 ${14 * k}px ${col})` }} />
        <circle cx={hx} cy={hy} r={13 * k} fill="#fff" style={{ filter: `drop-shadow(0 0 ${14 * k}px ${col})` }} />
      </svg>
      <AbsoluteFill style={{ alignItems: down ? "flex-end" : "flex-start", justifyContent: "flex-start",
        padding: `${height * 0.1}px ${width * 0.08}px` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: down ? "flex-end" : "flex-start", gap: 14 * k,
          padding: `${18 * k}px ${30 * k}px`, borderRadius: 18 * k, background: "rgba(10,10,13,.55)", backdropFilter: "blur(8px)" }}>
          <Odometer value={Math.abs(value)} at={numAt} frames={Math.round(fps * 1.2)} size={160 * k} color="#fff"
            prefix={down ? "−" : "+"} suffix={overlay.suffix ? (overlay.suffix === "%" ? "%" : ` ${overlay.suffix}`) : ""}
            suffixColor={col} suffixScale={0.42} />
          <Tag text={cap(overlay.text)} at={numAt + 16} accent={col} size={32} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== money stack
const Bill: React.FC<{ w: number; h: number }> = ({ w, h }) => (
  <svg width={w} height={h} viewBox="0 0 200 60" style={{ display: "block" }}>
    <rect x="1" y="1" width="198" height="58" rx="4" fill="#2f7d4f" stroke="#a9dcb9" strokeWidth="2.5" />
    <rect x="10" y="9" width="180" height="42" rx="3" fill="none" stroke="#82c79a" strokeWidth="1.5" strokeDasharray="4 3" />
    <circle cx="100" cy="30" r="16" fill="#3f9a63" stroke="#a9dcb9" strokeWidth="2" />
    <text x="100" y="38" textAnchor="middle" fontSize="24" fontWeight="800" fill="#e8f7ec" fontFamily="Arial">$</text>
    <rect x="1" y="52" width="198" height="7" rx="2" fill="#1f5c38" />
  </svg>
);

const UNIT_WORD: Record<string, string> = { K: "THOUSAND", M: "MILLION", B: "BILLION", T: "TRILLION" };
const UNIT_MAG: Record<string, number> = { K: 3, M: 6, B: 9, T: 12 };

/** Money: bundles of bills drop onto stacks, the amount rolls beside them. */
export const ProStack: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const unit = (overlay.suffix || "").toUpperCase().trim();
  const log = Math.log10(Math.max(1, Math.abs(value))) + (UNIT_MAG[unit] || 0);
  const bundles = Math.max(4, Math.min(21, Math.round(log * 2)));
  const cols = 3;
  const BW = 200 * k, BH = 56 * k;
  const perCol = Math.ceil(bundles / cols);
  const numAt = Math.round(fps * 0.3);
  const word = UNIT_WORD[unit] || "";
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 90 * k }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 22 * k }}>
            {Array.from({ length: cols }, (_, c) => (
              <div key={c} style={{ display: "flex", flexDirection: "column-reverse", gap: 3 * k }}>
                {Array.from({ length: Math.max(0, Math.min(perCol, bundles - c * perCol)) }, (_, b) => {
                  const at = numAt + (b * cols + c) * 2;
                  const p = ramp(frame, at, 12, backOut);
                  return (
                    <div key={b} style={{ transform: `translateY(${(1 - Math.min(1, p)) * -260 * k}px) rotate(${((b + c) % 3 - 1) * 1.2}deg)`,
                      opacity: p > 0.01 ? 1 : 0, filter: "drop-shadow(0 6px 10px rgba(0,0,0,.45))" }}>
                      <Bill w={BW} h={BH} />
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 * k, marginBottom: 20 * k }}>
            <Odometer value={value} at={numAt} frames={Math.round(fps * 1.4)} size={170 * k} color="#fff"
              prefix={overlay.prefix || "$"} suffix={word ? "" : unit} />
            {word ? (
              <LetterLine text={word} at={numAt + 10} style={{ fontFamily: DISPLAY, fontSize: 84 * k, color: accent,
                letterSpacing: "0.06em", lineHeight: 1 }} />
            ) : null}
            <Tag text={cap(overlay.text)} at={numAt + 18} accent={accent} size={32} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
