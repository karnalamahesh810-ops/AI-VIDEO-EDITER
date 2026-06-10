import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { Theme } from "../theme";
import { fadeRise, drawOn, stagger } from "../anim";

// SVG donut breakdown. Each slice is a stroke-arc on a shared circle, sized by its
// share of the total; slices draw on sequentially (clockwise from 12 o'clock) via
// stroke-dasharray/offset, staggered. A legend to the right lists a color dot + label
// + percentage, fading in with each slice. Default slice colors cycle through the
// theme. Renders full-bg (solid theme.bg) or as a translucent glass panel over b-roll.
// Optional bold white title up top; fades out near the end.
export const PieBreakdown: React.FC<{
  title?: string;
  slices: { label: string; value: number; color?: string }[];
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, slices, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const PW = fullBg ? 1920 : 1320;
  const PH = fullBg ? 1080 : 760;

  // Donut geometry: ring lives on the left half, legend on the right.
  const radius = 210;
  const stroke = 46;
  const circ = 2 * Math.PI * radius;
  const cx = fullBg ? 620 : 400;
  const cy = PH / 2 + (title ? 28 : 0);

  const palette = [theme.accent, theme.chartB, theme.accent2, theme.alert, theme.textMute];

  const total = Math.max(
    1e-6,
    slices.reduce((sum, s) => sum + Math.max(0, s.value), 0)
  );

  // Precompute each slice's fractional share and cumulative start fraction.
  let cursor = 0;
  const arcs = slices.map((s, i) => {
    const frac = Math.max(0, s.value) / total;
    const startFrac = cursor;
    cursor += frac;
    return {
      ...s,
      frac,
      startFrac,
      pct: Math.round(frac * 100),
      color: s.color || palette[i % palette.length],
    };
  });

  // Each slice draws on after the previous one (sequential), ~16f apart.
  const SLICE_DELAY = 8;
  const SLICE_STEP = 16;
  const SLICE_DUR = 18;

  const titleA = fadeRise(frame, { delay: 0, dur: 12, dist: 16, outAt, outDur: 10 });
  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Legend column geometry (HTML overlay positioned over the SVG's right half).
  const legendLeftPct = ((cx + radius + 90) / PW) * 100;

  const panelStyle: React.CSSProperties = fullBg
    ? { position: "absolute", inset: 0 }
    : {
        position: "absolute",
        left: "50%",
        top: "50%",
        transform: "translate(-50%, -50%)",
        width: PW,
        height: PH,
      };

  return (
    <AbsoluteFill style={{ ...(fullBg ? { background: theme.bg } : {}), pointerEvents: "none" }}>
      <div style={panelStyle}>
        <svg
          viewBox={`0 0 ${PW} ${PH}`}
          width="100%"
          height="100%"
          style={{ display: "block", overflow: "visible" }}
        >
          {/* Panel background: solid dark when full-bg, translucent glass over b-roll. */}
          <rect
            x={0}
            y={0}
            width={PW}
            height={PH}
            rx={fullBg ? 0 : 22}
            fill={theme.panel}
            opacity={fullBg ? 1 : 0.82 * axisA.opacity}
          />

          {/* Faint full background track ring under the slices. */}
          <circle
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke={theme.textMute}
            strokeWidth={stroke}
            opacity={0.12 * axisA.opacity}
          />

          {/* Slice arcs. Rotate the whole group -90deg so slice 0 starts at 12 o'clock. */}
          <g transform={`rotate(-90 ${cx} ${cy})`}>
            {arcs.map((a, i) => {
              const arcLen = a.frac * circ;
              const grow = drawOn(frame, {
                delay: SLICE_DELAY + i * SLICE_STEP,
                dur: SLICE_DUR,
              });
              const shownLen = arcLen * grow;
              // Position this slice's start at its cumulative offset around the ring.
              const startOffset = a.startFrac * circ;
              return (
                <circle
                  key={`sl${i}`}
                  cx={cx}
                  cy={cy}
                  r={radius}
                  fill="none"
                  stroke={a.color}
                  strokeWidth={stroke}
                  // dasharray: [visible arc, rest of circle hidden]
                  strokeDasharray={`${shownLen} ${circ - shownLen}`}
                  // negative offset shifts the dash start forward around the circle
                  strokeDashoffset={-startOffset}
                  opacity={fadeOut}
                />
              );
            })}
          </g>

          {/* Optional bold white title, top-center of the panel. */}
          {title ? (
            <text
              x={PW / 2}
              y={64}
              fill={theme.text}
              fontFamily={theme.bodyFont}
              fontSize={46}
              fontWeight={800}
              textAnchor="middle"
              opacity={titleA.opacity}
              style={{ letterSpacing: 0.5 }}
            >
              {title}
            </text>
          ) : null}
        </svg>

        {/* Legend overlay: color dot + label + percentage, one row per slice. */}
        <div
          style={{
            position: "absolute",
            left: legendLeftPct + "%",
            top: "50%",
            transform: "translateY(-50%)",
            display: "flex",
            flexDirection: "column",
            gap: 26,
            opacity: fadeOut,
          }}
        >
          {arcs.map((a, i) => {
            const legP = stagger(frame, i, {
              delay: SLICE_DELAY + 6,
              step: SLICE_STEP,
              dur: 10,
            });
            return (
              <div
                key={`lg${i}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 20,
                  opacity: legP,
                  transform: `translateX(${(1 - legP) * 18}px)`,
                }}
              >
                <div
                  style={{
                    flex: "0 0 auto",
                    width: 30,
                    height: 30,
                    borderRadius: 8,
                    background: a.color,
                  }}
                />
                <div
                  style={{
                    fontFamily: theme.bodyFont,
                    fontWeight: 700,
                    fontSize: 38,
                    color: theme.text,
                    lineHeight: 1.1,
                  }}
                >
                  {a.label}
                </div>
                <div
                  style={{
                    fontFamily: theme.bodyFont,
                    fontWeight: 800,
                    fontSize: 38,
                    color: theme.textMute,
                    marginLeft: "auto",
                    paddingLeft: 18,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {a.pct}%
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
