import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, formatNumber, growth, useOverlayAnim, useScale } from "./layout";
import { SERIF, SERIF_ITALIC, TYPEWRITER } from "./fonts";
import type { Overlay } from "../types";

/**
 * VidRush's most frequent graphics, measured across four of their exports:
 * small tags that ride ON the footage while it keeps playing, rather than
 * cards that replace it. Read off real frames:
 *
 *   stat-tag    "107 • DEGREES", "1,000 • FEET HIGH" - a dark pill in a corner
 *   label-boxes "ENGINE PLANTS" / "EMPLOYER FIRST" - one or two dark glass
 *               boxes over the shot, optionally joined by a dashed line
 *   ring-stat   a donut filling to "75%" with a label pill under it
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

/** "107 • DEGREES" in a corner: the number counts up, the unit types on. */
export const StatTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const value = overlay.value ?? 0;
  const shown = value * growth(frame, fps * 0.8);
  const unit = (overlay.text || "").toUpperCase();
  const typedUnit = unit.slice(0, Math.floor(unit.length * appear(frame, fps * 0.25, fps * 0.5)));
  const corner = overlay.variant || "bottom-left";
  const top = corner.startsWith("top");
  const right = corner.endsWith("right");
  const slide = (1 - appear(frame, 0, fps * 0.35)) * s(40) * (right ? 1 : -1);

  return (
    <AbsoluteFill style={{ opacity }}>
      <div
        style={{
          position: "absolute",
          [top ? "top" : "bottom"]: s(72),
          [right ? "right" : "left"]: s(84),
          transform: `translateX(${slide}px)`,
          display: "flex",
          alignItems: "center",
          gap: s(18),
          padding: `${s(18)}px ${s(38)}px`,
          borderRadius: s(40),
          background: "rgba(22,18,16,0.78)",
          boxShadow: "0 10px 30px rgba(0,0,0,0.45)",
          fontFamily: TYPEWRITER,
          color: "#f4efe6",
        }}
      >
        <span style={{ fontSize: s(52), fontWeight: 700 }}>
          {formatNumber(shown)}
          {overlay.suffix || ""}
        </span>
        <span
          style={{
            width: s(14),
            height: s(14),
            borderRadius: "50%",
            background: accent || "#d62828",
          }}
        />
        <span style={{ fontSize: s(46), fontWeight: 700, letterSpacing: "0.06em" }}>
          {typedUnit}
        </span>
      </div>
    </AbsoluteFill>
  );
};

/** One or two dark glass boxes naming what is in the shot. */
export const LabelBoxes: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, exit } = useOverlayAnim(8, 10);
  const s = useScale();
  const labels = (overlay.items || [])
    .map((it) => (it.label || it.text || "").toUpperCase())
    .filter(Boolean)
    .slice(0, 2);
  if (!labels.length && overlay.text) labels.push(overlay.text.toUpperCase());
  const pair = labels.length > 1;
  const xs = pair ? [27, 73] : [50];
  const linked = pair && overlay.variant === "linked";
  const box = s(400);
  const line = appear(frame, fps * 0.5, fps * 0.4);

  return (
    <AbsoluteFill style={{ opacity: exit }}>
      {linked ? (
        <div
          style={{
            position: "absolute",
            top: "42%",
            left: `calc(${xs[0]}% + ${box / 2}px)`,
            width: `calc(${(xs[1] - xs[0]) * line}% - ${box * line}px)`,
            borderTop: `${s(3)}px dashed rgba(255,255,255,0.85)`,
          }}
        />
      ) : null}
      {labels.map((label, i) => {
        const p = appear(frame, i * fps * 0.35, fps * 0.3);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: "42%",
              left: `${xs[i]}%`,
              width: box,
              height: box,
              transform: `translate(-50%, -50%) scale(${0.9 + 0.1 * p})`,
              opacity: p,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              padding: s(24),
              boxSizing: "border-box",
              background: "rgba(18,18,20,0.62)",
              border: `${s(2)}px solid rgba(255,255,255,0.8)`,
              fontFamily: TYPEWRITER,
              fontWeight: 700,
              fontSize: s(label.length > 16 ? 48 : 58),
              lineHeight: 1.2,
              color: "#fff",
              textShadow: TEXT_SHADOW,
            }}
          >
            {label}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

/** A donut filling to a percentage, the label in a pill underneath. */
export const RingStat: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const pct = Math.max(0, Math.min(100, overlay.value ?? 0));
  const fill = pct * growth(frame, fps * 1.0);
  const r = s(240);
  const stroke = s(52);
  const c = 2 * Math.PI * r;
  const size = 2 * r + stroke * 2;
  const label = (overlay.text || "").toUpperCase();
  const pill = appear(frame, fps * 0.6, fps * 0.35);

  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "relative", width: size, height: size, marginTop: -s(60) }}>
        <svg width={size} height={size} style={{ position: "absolute", inset: 0 }}>
          <circle cx={size / 2} cy={size / 2} r={r + stroke / 2 + s(4)} fill="rgba(0,0,0,0.35)" />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke="rgba(15,15,15,0.85)" strokeWidth={stroke} />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke={accent || "#e53935"} strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={`${(c * fill) / 100} ${c}`}
            transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        </svg>
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: SERIF_ITALIC,
            fontSize: s(104),
            color: "#fff",
            textShadow: TEXT_SHADOW,
          }}
        >
          {Math.round(fill)}%
        </div>
      </div>
      {label ? (
        <div
          style={{
            marginTop: s(24),
            opacity: pill,
            transform: `translateY(${(1 - pill) * s(16)}px)`,
            padding: `${s(10)}px ${s(26)}px`,
            borderRadius: s(10),
            background: "#f7f4ee",
            color: "#111",
            fontFamily: TYPEWRITER,
            fontWeight: 700,
            fontSize: s(42),
            letterSpacing: "0.04em",
          }}
        >
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

  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <AbsoluteFill
        style={{
          opacity: shade,
          background: "linear-gradient(to left, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.45) 38%, rgba(0,0,0,0) 62%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: s(110),
          top: "50%",
          transform: "translateY(-50%)",
          width: "36%",
          display: "flex",
          flexDirection: "column",
          gap: s(20),
        }}
      >
        {items.map((text, i) => {
          const p = appear(frame, fps * 0.2 + i * step, fps * 0.35);
          return (
            <div
              key={i}
              style={{
                opacity: p,
                transform: `translateX(${(1 - p) * s(30)}px)`,
                display: "flex",
                alignItems: "baseline",
                gap: s(16),
                fontFamily: SERIF,
                fontSize: s(42),
                lineHeight: 1.25,
                color: "#fff",
                textShadow: TEXT_SHADOW,
              }}
            >
              <span style={{ color: accent || "#d62828", fontSize: s(30) }}>●</span>
              <span>{text}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
