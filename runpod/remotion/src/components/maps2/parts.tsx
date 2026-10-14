/**
 * The maps-v2 marks, one grammar for every look (the owner's PointShift reference, measured off sheet_1.jpg at
 * 2400 x 1080): a small condensed uppercase label on a solid kit-gold pill (cap height ~1.3 % of the frame,
 * radius ~3 px, dark text), a figure in heavy white grotesk with its unit in small tracked caps under it, white
 * dotted route lines, a clean dot marker with a ring. Every entrance is eased (kit tempo), never linear.
 */
import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { backOut, clamp01, cubicInOut, cubicOut, expoOut, exitProg, quintOut } from "../motion/ease";
import { countText, figureOf, str, type Figure as Fig } from "../lib/proFormat";
import { alpha, mix, type MapKit } from "./kit";
import type { Overlay } from "../../types";
import { kitFor } from "./kit";

export { backOut, clamp01, cubicInOut, cubicOut, expoOut, quintOut };

/** Frame, timing and kit of a maps-v2 look. t(f) is "30 fps frames", so 60 fps renders run the same moves. */
export const useMap = (overlay: Overlay, accent: string) => {
  const f = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const S = fps / 30;
  const kit = kitFor(overlay as never, accent);
  const T = kit.tempo / Math.max(0.5, Math.min(2, Number(overlay.speed) || 1));
  const t = f / S;                                  // 30 fps frames since the look began
  const u = Math.min(W, H) / 1080;                  // type unit (vertical frames too)
  const out = exitProg(f, dur, 14, S);
  const tEnd = dur / S;
  /** progress of a move starting at frame `at` (30 fps frames) lasting `len` (scaled by the kit tempo) */
  const p = (at: number, len: number, ease: (x: number) => number = quintOut) => ease(clamp01((t - at) / Math.max(1, len * T)));
  /** a part's own moment: items[i].at seconds (its word), else the fallback frame */
  const atOf = (i: number, fallback: number) => {
    const it = (overlay.items || [])[i] as { at?: number } | undefined;
    const s = it && typeof it.at === "number" && Number.isFinite(it.at) ? it.at : null;
    return s === null ? fallback : Math.max(0, s * 30);
  };
  return { f, t, S, W, H, u, kit, out, dur, tEnd, p, atOf, T, fps };
};

// ------------------------------------------------------------------ the pill
export const Pill: React.FC<{ x: number; y: number; text: string; kit: MapKit; u: number; p: number; out?: number;
  anchor?: "left" | "right" | "center" | "above" | "below"; size?: number; dot?: boolean }> =
  ({ x, y, text, kit, u, p, out = 0, anchor = "right", size = 1, dot = false }) => {
    if (!text || p <= 0) return null;
    const fs = 25 * u * size;
    const gap = (dot ? 16 : 0) * u * size;
    const tf = anchor === "left" ? `translate(calc(-100% - ${gap}px), -50%)`
      : anchor === "right" ? `translate(${gap}px, -50%)`
        : anchor === "above" ? `translate(-50%, calc(-100% - ${gap + 8 * u}px))`
          : anchor === "below" ? `translate(-50%, ${gap + 8 * u}px)` : "translate(-50%, -50%)";
    const k = backOut(clamp01(p), 1.4);
    const o = clamp01(p * 2.2) * (1 - out);
    return (
      <div style={{ position: "absolute", left: x, top: y, transform: tf, opacity: o, pointerEvents: "none" }}>
        <div style={{ transform: `scale(${0.55 + 0.45 * k})`, transformOrigin: anchor === "left" ? "100% 50%" : anchor === "right" ? "0% 50%" : "50% 50%",
          background: kit.pillBg, color: kit.pillText, fontFamily: kit.label, fontWeight: 800, fontSize: fs,
          lineHeight: 1, letterSpacing: "0.045em", textTransform: "uppercase", padding: `${fs * 0.24}px ${fs * 0.42}px ${fs * 0.2}px`,
          borderRadius: 3.5 * u * size, whiteSpace: "nowrap", boxShadow: `0 ${4 * u}px ${14 * u}px rgba(0,0,0,0.45)` }}>
          {text}
        </div>
      </div>
    );
  };

// ------------------------------------------------------------------ the figure (number over its unit)
export const BigFigure: React.FC<{ x: number; y: number; fig: Fig | null; p: number; kit: MapKit; u: number; out?: number;
  align?: "left" | "right" | "center"; label?: string; size?: number; from?: number }> =
  ({ x, y, fig, p, kit, u, out = 0, align = "center", label = "", size = 1, from = 0 }) => {
    if (!fig || p <= 0) return null;
    const o = clamp01(p * 3) * (1 - out);
    const fs = 118 * u * size;
    const tf = align === "left" ? "translate(0, -50%)" : align === "right" ? "translate(-100%, -50%)" : "translate(-50%, -50%)";
    const unit = fig.unit || "";
    return (
      <div style={{ position: "absolute", left: x, top: y, transform: tf, opacity: o, textAlign: align, pointerEvents: "none",
        filter: `drop-shadow(0 ${6 * u}px ${18 * u}px rgba(0,0,0,0.55))` }}>
        {label ? (
          <div style={{ display: "inline-block", marginBottom: 10 * u * size, background: kit.pillBg, color: kit.pillText, fontFamily: kit.label,
            fontWeight: 800, fontSize: 22 * u * size, letterSpacing: "0.05em", textTransform: "uppercase", padding: `${5 * u}px ${9 * u}px`,
            borderRadius: 3 * u, lineHeight: 1 }}>{label}</div>
        ) : null}
        <div style={{ fontFamily: kit.numberFont, fontWeight: 800, fontSize: fs, lineHeight: 0.92, color: kit.number,
          letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap",
          transform: `translateY(${(1 - p) * 26 * u}px)` }}>
          {fig.prefix}{countText(fig, p, from)}{fig.glued}
        </div>
        {unit ? (
          <div style={{ fontFamily: kit.label, fontWeight: 700, fontSize: fs * 0.25, letterSpacing: "0.16em", color: kit.text,
            marginTop: fs * 0.08, textTransform: "uppercase", opacity: clamp01(p * 1.6 - 0.4) }}>{unit}</div>
        ) : null}
      </div>
    );
  };

/** A figure from an overlay's value / suffix / prefix (null when it has none). */
export const figureFrom = (value: unknown, suffix?: unknown, prefix?: unknown): Fig | null => {
  const v = typeof value === "number" ? value : Number(String(value ?? "").replace(/,/g, ""));
  return Number.isFinite(v) && String(value ?? "") !== "" ? figureOf(v, suffix, prefix) : null;
};

// ------------------------------------------------------------------ markers
/** A place's dot: white core, kit ring, one soft ping when it lands. */
export const Dot: React.FC<{ x: number; y: number; p: number; kit: MapKit; u: number; out?: number; ping?: number;
  color?: string; r?: number }> = ({ x, y, p, kit, u, out = 0, ping = 0, color, r = 9 }) => {
    if (p <= 0) return null;
    const c = color || kit.pillBg;
    const k = backOut(clamp01(p), 1.6);
    const R = r * u * k;
    return (
      <g opacity={(1 - out) * clamp01(p * 3)}>
        {ping > 0 && ping < 1 ? <circle cx={x} cy={y} r={R + ping * 46 * u} fill="none" stroke={c} strokeWidth={2.4 * u}
          opacity={(1 - ping) * 0.9} /> : null}
        <circle cx={x} cy={y} r={R * 1.9} fill={alpha(c, 0.22)} />
        <circle cx={x} cy={y} r={R} fill={c} stroke="#ffffff" strokeWidth={2.6 * u} />
      </g>
    );
  };

/** A map pin (teardrop) whose tip is at (x, y); h: how far above its tip it is (the drop), squash on landing. */
export const PinMark: React.FC<{ x: number; y: number; kit: MapKit; u: number; drop: number; squash: number; o: number;
  size?: number }> = ({ x, y, kit, u, drop, squash, o, size = 1 }) => {
    const s = 34 * u * size;
    const lift = drop * 260 * u;
    const sy = 1 - squash * 0.18, sx = 1 + squash * 0.12;
    return (
      <g opacity={o}>
        <ellipse cx={x} cy={y + 2 * u} rx={s * 0.55 * (1 - drop * 0.6)} ry={s * 0.16 * (1 - drop * 0.6)} fill="rgba(0,0,0,0.5)" />
        <g transform={`translate(${x} ${y - lift}) scale(${sx} ${sy})`}>
          <path d={`M0 0 C ${-s * 0.18} ${-s * 0.55} ${-s * 0.62} ${-s * 0.82} ${-s * 0.62} ${-s * 1.28} A ${s * 0.62} ${s * 0.62} 0 1 1 ${s * 0.62} ${-s * 1.28} C ${s * 0.62} ${-s * 0.82} ${s * 0.18} ${-s * 0.55} 0 0 Z`}
            fill={kit.pillBg} stroke={mix(kit.pillBg, "#000000", 0.35)} strokeWidth={1.4 * u} />
          <circle cx={0} cy={-s * 1.28} r={s * 0.26} fill="#ffffff" />
        </g>
      </g>
    );
  };

// ------------------------------------------------------------------ a title in the kit (kicker pill + title)
export const MapTitle: React.FC<{ text?: string; kicker?: string; kit: MapKit; u: number; p: number; out: number; W: number;
  H: number; corner?: "tl" | "bl" }> = ({ text, kicker, kit, u, p, out, W, H, corner = "tl" }) => {
    const title = str(text);
    if ((!title && !kicker) || p <= 0) return null;
    const o = clamp01(p * 2) * (1 - out);
    const pos: React.CSSProperties = corner === "tl" ? { left: 0.055 * W, top: 0.075 * H } : { left: 0.055 * W, bottom: 0.1 * H };
    return (
      <div style={{ position: "absolute", ...pos, opacity: o, transform: `translateY(${(1 - p) * 18 * u}px)`, maxWidth: W * 0.46,
        pointerEvents: "none" }}>
        {kicker ? (
          <div style={{ display: "inline-block", background: kit.pillBg, color: kit.pillText, fontFamily: kit.label, fontWeight: 800,
            fontSize: (title ? 21 : 30) * u, letterSpacing: "0.06em", textTransform: "uppercase",
            padding: title ? `${5 * u}px ${9 * u}px` : `${7 * u}px ${13 * u}px ${6 * u}px`, borderRadius: (title ? 3 : 4) * u,
            lineHeight: 1, marginBottom: 12 * u }}>{kicker}</div>
        ) : null}
        {title ? (
          <div style={{ fontFamily: kit.title, fontWeight: kit.titleWeight, fontSize: 64 * u, lineHeight: 0.98, color: kit.text,
            textTransform: "uppercase", letterSpacing: "0.005em", textShadow: `0 ${4 * u}px ${20 * u}px rgba(0,0,0,0.6)` }}>{title}</div>
        ) : null}
      </div>
    );
  };

/** The finish over every map: a soft vignette (the reference's dark corners). */
export const Vignette: React.FC<{ strength?: number }> = ({ strength = 0.55 }) => (
  <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
    background: `radial-gradient(ellipse 80% 75% at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,${strength}) 100%)` }} />
);

/** "Kerala, India" -> "Kerala". */
export const shortName = (label: string) => str(label).split(",")[0].trim();
