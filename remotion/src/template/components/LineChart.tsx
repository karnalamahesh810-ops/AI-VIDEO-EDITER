import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { Theme } from "../theme";
import { fadeRise, drawOn } from "../anim";

// Animated multi-series line chart. Dark navy panel, faint grid, white axes.
// Each series draws on left->right via stroke-dashoffset; series staggered ~10f.
// Renders either full-bg or as a centered glass panel over transparent b-roll.
export const LineChart: React.FC<{
  title: string;
  series: { points: number[]; color?: string }[];
  xLabels?: string[];
  yLabel?: string;
  xLabel?: string;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, series, xLabels, yLabel, xLabel, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  // Panel geometry inside the 1920x1080 design.
  const PW = fullBg ? 1920 : 1200;
  const PH = fullBg ? 1080 : 680;
  const padL = 120;
  const padR = 70;
  const padT = 120;
  const padB = 110;
  const plotW = PW - padL - padR;
  const plotH = PH - padT - padB;
  const x0 = padL;
  const y0 = PH - padB; // baseline (bottom of plot)
  const yTop = padT;

  // Domain across every series.
  const allVals = series.flatMap((s) => s.points);
  const rawMin = allVals.length ? Math.min(...allVals) : 0;
  const rawMax = allVals.length ? Math.max(...allVals) : 1;
  const span = rawMax - rawMin || 1;
  const minV = rawMin - span * 0.08;
  const maxV = rawMax + span * 0.08;
  const range = maxV - minV || 1;

  const maxLen = Math.max(1, ...series.map((s) => s.points.length));
  const sx = (i: number, n: number) => x0 + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const sy = (v: number) => y0 - ((v - minV) / range) * plotH;

  // Catmull-Rom -> cubic bezier smoothing for a monotone-ish curve.
  const buildPath = (pts: number[]): string => {
    const n = pts.length;
    if (n === 0) return "";
    const P = pts.map((v, i) => ({ x: sx(i, n), y: sy(v) }));
    if (n === 1) return `M ${P[0].x} ${P[0].y}`;
    let d = `M ${P[0].x} ${P[0].y}`;
    for (let i = 0; i < n - 1; i++) {
      const p0 = P[i - 1] || P[i];
      const p1 = P[i];
      const p2 = P[i + 1];
      const p3 = P[i + 2] || p2;
      const c1x = p1.x + (p2.x - p0.x) / 6;
      const c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6;
      const c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C ${c1x} ${c1y} ${c2x} ${c2y} ${p2.x} ${p2.y}`;
    }
    return d;
  };

  // Horizontal grid lines (5 divisions).
  const gridYs = Array.from({ length: 5 }, (_, i) => yTop + (i / 4) * plotH);
  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });
  // A generous dash length covering any curved path so the reveal fully hides it.
  const dashLen = (plotW + plotH) * 2.2;

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
    <AbsoluteFill style={{ ...(fullBg ? { background: theme.bg } : {}) }}>
      <div style={panelStyle}>
        <svg
          viewBox={`0 0 ${PW} ${PH}`}
          width="100%"
          height="100%"
          style={{ display: "block", overflow: "visible" }}
        >
          {/* Panel background */}
          <rect
            x={0}
            y={0}
            width={PW}
            height={PH}
            rx={fullBg ? 0 : 22}
            fill={theme.panel}
            opacity={fullBg ? 1 : 0.8}
          />

          {/* Faint horizontal grid */}
          {gridYs.map((gy, i) => (
            <line
              key={`g${i}`}
              x1={x0}
              x2={x0 + plotW}
              y1={gy}
              y2={gy}
              stroke={theme.textMute}
              strokeWidth={1}
              opacity={0.14 * axisA.opacity}
            />
          ))}

          {/* White axes */}
          <line
            x1={x0}
            y1={yTop}
            x2={x0}
            y2={y0}
            stroke={theme.text}
            strokeWidth={2}
            opacity={axisA.opacity}
          />
          <line
            x1={x0}
            y1={y0}
            x2={x0 + plotW}
            y2={y0}
            stroke={theme.text}
            strokeWidth={2}
            opacity={axisA.opacity}
          />

          {/* Series polylines, draw-on left->right, staggered */}
          {series.map((s, si) => {
            const d = buildPath(s.points);
            const p = drawOn(frame, { delay: 12 + si * 10, dur: 60 });
            const color = s.color || (si === 0 ? theme.chartA : theme.chartB);
            const lineOut = interpolate(
              frame,
              [outAt, outAt + 10],
              [1, 0],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
            );
            return (
              <path
                key={`s${si}`}
                d={d}
                fill="none"
                stroke={color}
                strokeWidth={4}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={dashLen}
                strokeDashoffset={dashLen * (1 - p)}
                opacity={lineOut}
              />
            );
          })}

          {/* X tick labels */}
          {xLabels &&
            xLabels.map((lab, i) => (
              <text
                key={`x${i}`}
                x={sx(i, Math.max(maxLen, xLabels.length))}
                y={y0 + 34}
                fill={theme.textMute}
                fontFamily={theme.bodyFont}
                fontSize={22}
                textAnchor="middle"
                opacity={axisA.opacity}
              >
                {lab}
              </text>
            ))}

          {/* Y axis label, rotated -90 */}
          {yLabel && (
            <text
              x={36}
              y={yTop + plotH / 2}
              fill={theme.textMute}
              fontFamily={theme.bodyFont}
              fontSize={24}
              textAnchor="middle"
              transform={`rotate(-90 36 ${yTop + plotH / 2})`}
              opacity={axisA.opacity}
            >
              {yLabel}
            </text>
          )}

          {/* X axis label */}
          {xLabel && (
            <text
              x={x0 + plotW / 2}
              y={PH - 32}
              fill={theme.textMute}
              fontFamily={theme.bodyFont}
              fontSize={24}
              textAnchor="middle"
              opacity={axisA.opacity}
            >
              {xLabel}
            </text>
          )}

          {/* Title */}
          <text
            x={PW / 2}
            y={56}
            fill={theme.text}
            fontFamily={theme.bodyFont}
            fontSize={40}
            fontWeight={700}
            textAnchor="middle"
            opacity={axisA.opacity}
          >
            {title}
          </text>
        </svg>
      </div>
    </AbsoluteFill>
  );
};
