import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, formatNumber, growth, useOverlayAnim, useScale } from "./layout";
import { INTER, NARROW, SERIF } from "./fonts";
import { Rule, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * VidRush's most frequent graphics: tags that ride ON the footage while it
 * keeps playing, rather than cards that replace it. Read off real frames,
 * rebuilt at broadcast scale:
 *
 *   stat-tag    "107 • DEGREES", "1,000 • FEET HIGH" - a glass pill in a corner
 *   label-boxes "ENGINE PLANTS" / "EMPLOYER FIRST" - one or two glass boxes
 *               over the shot, optionally joined by a dashed connector
 *   ring-stat   a ring filling to "75%" with a label pill under it
 *   bullets     three or four serif points beside the footage, one by one
 *
 * Every one leaves the footage full screen: at most a soft local shade
 * behind the text, never a backdrop.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

function appear(frame: number, at: number, frames: number) {
  return interpolate(frame, [at, at + frames], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
}

const GLASS = "linear-gradient(135deg, rgba(16,16,20,0.88) 0%, rgba(10,10,13,0.72) 100%)";

/** "107 • DEGREES" in a corner: the number counts up, the unit types on. */
export const StatTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const drift = useDrift(5);
  const value = overlay.value ?? 0;
  const shown = value * growth(frame, fps * 0.9);
  const unit = (overlay.text || "").toUpperCase();
  const typedUnit = unit.slice(0, Math.floor(unit.length * appear(frame, fps * 0.3, fps * 0.5)));
  const corner = overlay.variant || "bottom-left";
  const top = corner.startsWith("top");
  const right = corner.endsWith("right");
  const p = run(frame, 0, fps * 0.45);
  const slide = (1 - p) * s(60) * (right ? 1 : -1);
  const col = accent || "#d62828";

  return (
    <AbsoluteFill style={{ opacity }}>
      <div
        style={{
          position: "absolute",
          [top ? "top" : "bottom"]: top ? s(90) : "29%",
          [right ? "right" : "left"]: s(96),
          transform: `translateX(${slide}px) ${drift}`,
          opacity: p,
          display: "flex",
          alignItems: "center",
          gap: s(22),
          padding: `${s(20)}px ${s(44)}px ${s(20)}px ${s(34)}px`,
          borderRadius: s(60),
          background: GLASS,
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255,255,255,0.1)",
          boxShadow: "0 18px 50px rgba(0,0,0,0.5)",
          fontFamily: INTER,
          color: "#f4efe6",
        }}
      >
        <span style={{ fontSize: s(66), fontWeight: 800, color: "#fff", letterSpacing: "-0.02em" }}>
          {formatNumber(shown)}
          {overlay.suffix || ""}
        </span>
        <span style={{ width: s(16), height: s(16), borderRadius: "50%", background: col, boxShadow: `0 0 ${s(14)}px ${col}` }} />
        <span style={{ fontFamily: NARROW, fontSize: s(56), fontWeight: 700, letterSpacing: "0.1em" }}>{typedUnit}</span>
      </div>
    </AbsoluteFill>
  );
};

/** One or two glass boxes naming what is in the shot, an accent bar on top of each. */
export const LabelBoxes: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, exit } = useOverlayAnim(8, 10);
  const s = useScale();
  const labels = (overlay.items || [])
    .map((it) => (it.label || it.text || "").toUpperCase())
    .filter(Boolean)
    .slice(0, 2);
  const subs = (overlay.items || []).map((it) => (it.label && it.text ? it.text : "")).slice(0, 2);
  if (!labels.length && overlay.text) labels.push(overlay.text.toUpperCase());
  const pair = labels.length > 1;
  const xs = pair ? [27, 73] : [50];
  const linked = pair && overlay.variant !== "plain";
  const box = s(440);
  const line = run(frame, fps * 0.55, fps * 0.45);
  const col = accent || "#d62828";

  return (
    <AbsoluteFill style={{ opacity: exit }}>
      {linked ? (
        <div
          style={{
            position: "absolute",
            top: "44%",
            left: `calc(${xs[0]}% + ${box / 2}px)`,
            width: `calc(${(xs[1] - xs[0]) * line}% - ${box * line}px)`,
            borderTop: `${s(4)}px dashed rgba(255,255,255,0.9)`,
          }}
        />
      ) : null}
      {labels.map((label, i) => {
        const p = run(frame, i * fps * 0.35, fps * 0.4);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: "44%",
              left: `${xs[i]}%`,
              width: box,
              minHeight: box * 0.78,
              transform: `translate(-50%, -50%) scale(${0.88 + 0.12 * p})`,
              opacity: p,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              padding: s(30),
              boxSizing: "border-box",
              background: GLASS,
              backdropFilter: "blur(12px)",
              border: "1px solid rgba(255,255,255,0.14)",
              borderTop: `${s(10)}px solid ${col}`,
              borderRadius: s(16),
              boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
              fontFamily: NARROW,
              fontWeight: 700,
              fontSize: s(label.length > 16 ? 56 : 72),
              lineHeight: 1.14,
              letterSpacing: "0.05em",
              color: "#fff",
              textShadow: TEXT_SHADOW,
            }}
          >
            {label}
            {subs[i] ? (
              <div style={{ fontFamily: INTER, fontWeight: 500, fontSize: s(30), color: "rgba(255,255,255,.75)", marginTop: s(12),
                letterSpacing: "0.04em", textTransform: "none" }}>{subs[i]}</div>
            ) : null}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

/** A ring filling to a percentage, the label in a pill underneath. */
export const RingStat: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const pct = Math.max(0, Math.min(100, overlay.value ?? 0));
  const fill = pct * growth(frame, fps * 1.1);
  const r = s(250);
  const stroke = s(46);
  const c = 2 * Math.PI * r;
  const size = 2 * r + stroke * 2;
  const label = (overlay.text || "").toUpperCase();
  const pill = appear(frame, fps * 0.6, fps * 0.35);
  const col = accent || "#e53935";

  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "relative", width: size, height: size, marginTop: -s(60) }}>
        <svg width={size} height={size} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <filter id="ringGlow"><feGaussianBlur stdDeviation={s(6)} result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          </defs>
          <circle cx={size / 2} cy={size / 2} r={r + stroke / 2 + s(6)} fill="rgba(0,0,0,0.45)" />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth={stroke} />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={`${(c * fill) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} filter="url(#ringGlow)" />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: s(124), lineHeight: 1, color: "#fff", textShadow: TEXT_SHADOW, letterSpacing: "-0.03em" }}>
            {Math.round(fill)}<span style={{ fontSize: s(64), color: col }}>%</span>
          </div>
        </div>
      </div>
      {label ? (
        <div style={{ marginTop: s(28), opacity: pill, transform: `translateY(${(1 - pill) * s(16)}px)`,
          padding: `${s(12)}px ${s(34)}px`, borderRadius: s(12), background: "#f7f4ee", color: "#111",
          fontFamily: INTER, fontWeight: 800, fontSize: s(44), letterSpacing: "0.12em",
          boxShadow: "0 14px 40px rgba(0,0,0,.4)" }}>
          {label}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** Three or four short points beside the footage, revealed one at a time. */
export const Bullets: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, durationInFrames, exit } = useOverlayAnim(8, 10);
  const s = useScale();
  const items = (overlay.items || [])
    .map((it) => it.text || it.label || "")
    .filter(Boolean)
    .slice(0, 4);
  const step = Math.min(fps * 0.7, (durationInFrames * 0.55) / Math.max(1, items.length));
  const shade = appear(frame, 0, fps * 0.3);
  const col = accent || "#d62828";
  const title = overlay.text && overlay.text !== items[0] ? overlay.text.toUpperCase() : "";

  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <AbsoluteFill style={{ opacity: shade,
        background: "linear-gradient(to left, rgba(0,0,0,0.78) 0%, rgba(0,0,0,0.5) 40%, rgba(0,0,0,0) 65%)" }} />
      <div style={{ position: "absolute", right: s(110), top: "50%", transform: "translateY(-50%)", width: "40%",
        display: "flex", flexDirection: "column", gap: s(26) }}>
        {title ? (
          <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: s(30), letterSpacing: "0.26em", color: col,
            opacity: shade, marginBottom: s(6) }}>
            {title}
            <Rule p={shade} width={s(120)} height={s(4)} color={col} style={{ marginTop: s(10) }} />
          </div>
        ) : null}
        {items.map((text, i) => {
          const p = run(frame, fps * 0.2 + i * step, fps * 0.4);
          return (
            <div key={i} style={{ opacity: p, transform: `translateX(${(1 - p) * s(40)}px)`,
              filter: p < 1 ? `blur(${(1 - p) * 8}px)` : undefined, display: "flex", alignItems: "baseline", gap: s(22),
              fontFamily: SERIF, fontSize: s(54), lineHeight: 1.22, color: "#fff", textShadow: TEXT_SHADOW }}>
              <span style={{ width: s(18), height: s(18), borderRadius: "50%", background: col, flexShrink: 0,
                boxShadow: `0 0 ${s(14)}px ${col}`, transform: "translateY(-0.35em)" }} />
              <span>{text}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

