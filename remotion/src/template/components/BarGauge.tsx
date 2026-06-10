import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, countUp, fmtNum } from "../anim";

const W = 1920;
const H = 1080;

// HUD vertical gauge. A glowing perspective grid recedes toward a vanishing point on a
// black (or transparent) bg. A tall narrow container outlined in glowing white holds a
// theme.alert fill bar that rises from the bottom to value% height, while a glowing %
// numeral to its right counts up in sync. Glowing label centered top, tiny grey footnote
// pinned to the very bottom. Whole scene fades out near the end.
export const BarGauge: React.FC<{
  value: number;
  suffix?: string;
  label?: string;
  footnote?: string;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ value, suffix = "%", label, footnote, fullBg = true, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  // Clamp the displayed fill to 0..100 of the container height.
  const pct = Math.max(0, Math.min(100, value));
  const fill = interpolate(frame, [12, 12 + 26], [0, pct / 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const shown = countUp(frame, { to: value, delay: 12, dur: 26 });

  // Gauge container geometry (centered).
  const gW = 168;
  const gH = 620;
  const gx = W / 2 - gW / 2;
  const gy = H / 2 - gH / 2;
  const inset = 18; // gap between the outline and the fill bar
  const barX = gx + inset;
  const barW = gW - inset * 2;
  const barMaxH = gH - inset * 2;
  const barH = barMaxH * fill;
  const barY = gy + gH - inset - barH;

  // Vanishing-point perspective grid.
  const vpX = W / 2;
  const vpY = H * 0.46;
  const horizonY = H * 0.5;

  const lbl = fadeRise(frame, { delay: 4, dur: 12, dist: 16, outAt, outDur: 10 });

  return (
    <AbsoluteFill
      style={{ background: fullBg ? "#040508" : "transparent", opacity: rootOpacity }}
    >
      {/* Glowing perspective grid. */}
      <AbsoluteFill>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height="100%"
          style={{ display: "block", overflow: "visible" }}
        >
          <defs>
            <filter id="bg-grid-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="2.2" />
            </filter>
          </defs>
          <g filter="url(#bg-grid-glow)" stroke={theme.text} strokeWidth={1.5} fill="none">
            {/* Receding floor lines bunching toward the horizon. */}
            {Array.from({ length: 10 }, (_, i) => {
              const t = i / 9;
              const y = horizonY + (H - horizonY) * (t * t);
              return (
                <line
                  key={`f${i}`}
                  x1={0}
                  y1={y}
                  x2={W}
                  y2={y}
                  opacity={0.18 * (0.35 + 0.65 * t)}
                />
              );
            })}
            {/* Radial verticals fanning from the vanishing point to the bottom edge. */}
            {Array.from({ length: 19 }, (_, i) => {
              const x = (i / 18) * W;
              return <line key={`r${i}`} x1={vpX} y1={vpY} x2={x} y2={H} opacity={0.12} />;
            })}
          </g>
        </svg>
      </AbsoluteFill>

      {/* Gauge: glowing outline, alert fill bar, and synced % readout. */}
      <AbsoluteFill>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height="100%"
          style={{ display: "block", overflow: "visible" }}
        >
          <defs>
            <filter id="gauge-white-glow" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="6" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="gauge-alert-glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="8" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Glowing white container outline. */}
          <rect
            x={gx}
            y={gy}
            width={gW}
            height={gH}
            rx={26}
            fill="none"
            stroke={theme.text}
            strokeWidth={4}
            filter="url(#gauge-white-glow)"
            opacity={lbl.opacity}
          />

          {/* Alert fill bar rising from the bottom. */}
          <rect
            x={barX}
            y={barY}
            width={barW}
            height={Math.max(0, barH)}
            rx={12}
            fill={theme.alert}
            filter="url(#gauge-alert-glow)"
            opacity={rootOpacity}
          />

          {/* Glowing % numeral to the right of the bar, tracking the fill level. */}
          <text
            x={gx + gW + 56}
            y={Math.min(gy + gH - inset, Math.max(gy + 64, barY)) + 18}
            fill={theme.alert}
            fontFamily={theme.headerFont}
            fontSize={96}
            fontWeight={800}
            textAnchor="start"
            filter="url(#gauge-alert-glow)"
            opacity={rootOpacity}
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {fmtNum(shown, { suffix, commas: false })}
          </text>
        </svg>
      </AbsoluteFill>

      {/* Glowing label centered top. */}
      {label ? (
        <div
          style={{
            position: "absolute",
            top: H * 0.1,
            left: 0,
            right: 0,
            textAlign: "center",
            fontFamily: theme.headerFont,
            fontWeight: 700,
            fontSize: 64,
            letterSpacing: 2,
            color: theme.text,
            textTransform: "uppercase",
            textShadow: `0 0 18px ${theme.text}AA, 0 0 44px ${theme.text}55`,
            opacity: lbl.opacity,
            transform: lbl.transform,
          }}
        >
          {label}
        </div>
      ) : null}

      {/* Tiny grey footnote at the very bottom. */}
      {footnote ? (
        <div
          style={{
            position: "absolute",
            bottom: 28,
            left: 0,
            right: 0,
            textAlign: "center",
            fontFamily: theme.bodyFont,
            fontSize: 22,
            color: theme.textMute,
            letterSpacing: 0.4,
            opacity: lbl.opacity,
          }}
        >
          {footnote}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
