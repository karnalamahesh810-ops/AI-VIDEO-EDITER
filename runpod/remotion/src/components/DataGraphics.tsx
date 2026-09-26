import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, formatNumber, useOverlayAnim, useScale } from "./layout";
import { INTER, SERIF, SERIF_ITALIC, TYPEWRITER } from "./fonts";
import type { Overlay } from "../types";

/**
 * VidRush's data and sequence graphics, read off their exports:
 *   line-chart      a line drawing itself under a caps title
 *   path-steps      a red curve through numbered stops ("1 Cambridge", "2 ...")
 *   progress-steps  dots along a rule, the last one lit, "A -> B" under it
 *   span            two dated tags joined by a dotted rule, the span above
 *   icon-pop        one pictogram in a ring popping in, a caption under it
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const ease = (frame: number, at: number, frames: number) =>
  interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
const SHADE = "rgba(8,9,12,0.82)";

export const LineChart: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const pts = (overlay.items || []).filter((i) => typeof i.value === "number").slice(0, 12);
  const W = 1400, H = 520;
  const vals = pts.map((p) => p.value as number);
  const lo = Math.min(0, ...vals), hi = Math.max(...vals, 1);
  const xy = pts.map((p, i) => [
    (i / Math.max(1, pts.length - 1)) * W,
    H - (((p.value as number) - lo) / (hi - lo || 1)) * H,
  ]);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const draw = ease(frame, fps * 0.3, fps * 1.4);
  const last = pts[pts.length - 1];
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center" }}>
      <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: s(40), letterSpacing: "0.06em",
        color: "#fff", textTransform: "uppercase", marginBottom: s(40) }}>{overlay.text}</div>
      <svg width={s(W + 80)} height={s(H + 80)} viewBox={`-40 -40 ${W + 80} ${H + 80}`}>
        <line x1={0} y1={H} x2={W} y2={H} stroke="rgba(255,255,255,.35)" strokeWidth={2} />
        <line x1={0} y1={0} x2={0} y2={H} stroke="rgba(255,255,255,.2)" strokeWidth={2} />
        <path d={d} fill="none" stroke={accent || "#d62828"} strokeWidth={6} strokeLinejoin="round"
          pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
        {pts.map((p, i) => (
          <text key={i} x={xy[i][0]} y={H + 34} fill="rgba(255,255,255,.7)" fontSize={24}
            fontFamily={INTER} textAnchor="middle" opacity={ease(frame, fps * 0.2 + i * 2, 6)}>
            {p.label}
          </text>
        ))}
        {last && draw > 0.98 ? (
          <text x={xy[xy.length - 1][0]} y={xy[xy.length - 1][1] - 18} fill="#fff" fontSize={40}
            fontFamily={SERIF_ITALIC} textAnchor="end">
            {formatNumber(last.value as number)}{overlay.suffix || ""}
          </text>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};

export const PathSteps: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity, durationInFrames } = useOverlayAnim(10, 10);
  const s = useScale();
  const items = (overlay.items || []).slice(0, 4);
  const n = Math.max(2, items.length);
  // A loose S through the frame, like their hand-drawn red route.
  const stops = Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    return [220 + t * 1480, i % 2 ? 330 : 760];
  });
  const d = stops.map(([x, y], i) => {
    if (!i) return `M ${x} ${y}`;
    const [px, py] = stops[i - 1];
    return `C ${px + 320} ${py}, ${x - 320} ${y}, ${x} ${y}`;
  }).join(" ");
  const draw = ease(frame, fps * 0.2, Math.min(fps * 1.6, durationInFrames * 0.6));
  return (
    <AbsoluteFill style={{ opacity, background: "radial-gradient(ellipse at 50% 50%, rgba(40,6,6,.78), rgba(5,5,6,.9))" }}>
      {overlay.text ? (
        <div style={{ position: "absolute", top: s(70), width: "100%", textAlign: "center", fontFamily: SERIF,
          fontSize: s(84), color: "#fff", textShadow: TEXT_SHADOW, textTransform: "uppercase" }}>{overlay.text}</div>
      ) : null}
      <svg width="100%" height="100%" viewBox="0 0 1920 1080" style={{ position: "absolute", inset: 0 }}>
        <path d={d} fill="none" stroke={accent || "#d62828"} strokeWidth={4} pathLength={1}
          strokeDasharray={1} strokeDashoffset={1 - draw} />
        {stops.map(([x, y], i) => {
          const on = ease(frame, fps * 0.2 + (i / (n - 1)) * Math.min(fps * 1.6, durationInFrames * 0.6), 5);
          return (
            <g key={i} opacity={on}>
              <circle cx={x} cy={y} r={20} fill={accent || "#e53935"} />
              <circle cx={x} cy={y} r={34} fill={accent || "#e53935"} opacity={0.25} />
              <text x={i === n - 1 ? x - 44 : x + 44} y={y - 30} fill="#fff" fontFamily={SERIF_ITALIC}
                fontSize={72} textAnchor={i === n - 1 ? "end" : "start"}>{i + 1}</text>
              <text x={i === n - 1 ? x - 44 : x + 44} y={y + 30} fill="rgba(255,255,255,.92)"
                fontFamily={SERIF} fontSize={42} textAnchor={i === n - 1 ? "end" : "start"}>
                {items[i]?.label || items[i]?.text || ""}
              </text>
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};

export const ProgressSteps: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const items = (overlay.items || []).slice(0, 4);
  const n = Math.max(2, items.length);
  const panel = ease(frame, 0, fps * 0.35);
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center" }}>
      <div style={{ marginLeft: s(90), width: "52%", padding: s(46), transform: `translateX(${(1 - panel) * -s(40)}px)`,
        background: "#ecebe6", backgroundImage:
          "linear-gradient(rgba(0,0,0,.07) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,.07) 1px, transparent 1px)",
        backgroundSize: `${s(34)}px ${s(34)}px`, boxShadow: "0 18px 50px rgba(0,0,0,.45)" }}>
        <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: s(40), color: "#111", textAlign: "center" }}>
          {overlay.text}
        </div>
        <div style={{ position: "relative", height: s(60), margin: `${s(26)}px ${s(60)}px` }}>
          <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: s(4), background: "#111" }} />
          {Array.from({ length: n }, (_, i) => {
            const on = ease(frame, fps * 0.3 + i * fps * 0.35, 6);
            const lit = i === n - 1;
            return (
              <div key={i} style={{ position: "absolute", top: "50%", left: `${(i / (n - 1)) * 100}%`,
                width: s(34), height: s(34), borderRadius: "50%", transform: `translate(-50%,-50%) scale(${on})`,
                background: lit ? "#f5d000" : "#111" }} />
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: s(24),
          fontFamily: INTER, fontSize: s(36), color: "#111" }}>
          {items.map((it, i) => (
            <React.Fragment key={i}>
              {i ? <span style={{ opacity: ease(frame, fps * 0.3 + i * fps * 0.35, 6) }}>⟶</span> : null}
              <span style={{ opacity: ease(frame, fps * 0.3 + i * fps * 0.35, 6) }}>{it.label || it.text}</span>
            </React.Fragment>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const Span: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const [a, b] = [overlay.items?.[0], overlay.items?.[1]];
  const rule = ease(frame, fps * 0.3, fps * 0.8);
  const tag = (it: typeof a, side: "left" | "right", at: number) => (
    <div style={{ position: "absolute", [side]: "12%", top: "44%", opacity: ease(frame, at, 6),
      transform: "translateY(-50%)", textAlign: side === "left" ? "left" : "right" }}>
      <div style={{ display: "inline-block", background: "#f4f1ea", color: "#111", fontFamily: TYPEWRITER,
        fontWeight: 700, fontSize: s(36), padding: `${s(4)}px ${s(14)}px` }}>{it?.label}</div>
      <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: s(28), color: accent || "#e05a2a",
        marginTop: s(12), textTransform: "uppercase" }}>{it?.text}</div>
    </div>
  );
  return (
    <AbsoluteFill style={{ opacity, background: "rgba(6,7,9,.72)", backgroundImage:
      "linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px)",
      backgroundSize: `${s(60)}px ${s(60)}px` }}>
      <div style={{ position: "absolute", top: "30%", width: "100%", textAlign: "center", fontFamily: TYPEWRITER,
        fontWeight: 700, fontSize: s(64), color: "#fff", opacity: ease(frame, fps * 0.9, 8) }}>{overlay.text}</div>
      <div style={{ position: "absolute", top: "44%", left: "14%", width: `${72 * rule}%`,
        borderTop: `${s(3)}px dotted rgba(255,255,255,.75)` }} />
      {tag(a, "left", fps * 0.2)}
      {tag(b, "right", fps * 0.9)}
    </AbsoluteFill>
  );
};

/** Simple line pictograms, drawn in-house so no icon font or network is needed. */
export const ICONS: Record<string, string> = {
  fuel: "M14 10h26v44H14z M14 26h26 M40 18l10 8v22a4 4 0 0 1-8 0V36h-2",
  water: "M32 8C22 24 16 32 16 40a16 16 0 0 0 32 0c0-8-6-16-16-32z",
  home: "M10 30L32 12l22 18 M16 26v28h32V26 M27 54V40h10v14",
  warning: "M32 8L58 54H6z M32 24v14 M32 44v4",
  fire: "M32 56c-12 0-18-8-18-18 0-10 8-14 10-24 6 6 8 10 8 16 4-2 6-6 6-10 6 6 12 12 12 20 0 10-6 16-18 16z",
  car: "M8 40l6-14h36l6 14v10H8z M18 50v4 M46 50v4 M8 40h48",
  money: "M8 18h48v28H8z M32 24a8 8 0 1 0 0 16 8 8 0 1 0 0-16",
  school: "M4 24L32 12l28 12-28 12z M14 28v14c10 8 26 8 36 0V28",
  hospital: "M12 12h40v40H12z M32 20v24 M20 32h24",
  phone: "M22 6h20v52H22z M30 50h4",
  clock: "M32 8a24 24 0 1 0 0 48 24 24 0 1 0 0-48 M32 18v14l10 6",
  thermometer: "M28 8h8v30a10 10 0 1 1-8 0z",
  document: "M16 6h22l10 10v42H16z M38 6v10h10 M22 28h20 M22 36h20 M22 44h14",
  people: "M22 24a7 7 0 1 0 0-.1 M42 24a7 7 0 1 0 0-.1 M10 50c2-10 22-10 24 0 M30 50c2-10 22-10 24 0",
};

export const IconPop: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const icon = ICONS[overlay.variant || ""] || ICONS.warning;
  const pop = ease(frame, 0, fps * 0.35);
  const ring = ease(frame, fps * 0.1, fps * 0.6);
  const size = s(240);
  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center",
      background: "radial-gradient(circle at 50% 46%, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 38%)" }}>
      <div style={{ position: "relative", width: size, height: size, transform: `scale(${0.7 + 0.3 * pop})` }}>
        <svg width={size} height={size} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0 }}>
          <circle cx={50} cy={50} r={46} fill="rgba(20,20,22,.55)" stroke="rgba(255,255,255,.85)"
            strokeWidth={2} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ring} />
          <g transform="translate(18 18) scale(1.0)">
            <path d={icon} fill="none" stroke="#fff" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" />
          </g>
        </svg>
        <div style={{ position: "absolute", right: -s(6), bottom: s(20), width: s(26), height: s(26),
          borderRadius: "50%", background: accent || "#d62828", opacity: ring }} />
      </div>
      {overlay.text ? (
        <div style={{ marginTop: s(26), fontFamily: TYPEWRITER, fontWeight: 700, fontSize: s(46), color: "#fff",
          textShadow: TEXT_SHADOW, textTransform: "uppercase", opacity: ease(frame, fps * 0.3, 8) }}>
          {overlay.text}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const ICON_NAMES = Object.keys(ICONS);
