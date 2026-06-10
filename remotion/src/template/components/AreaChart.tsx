import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { Theme } from "../theme";
import { fadeRise, drawOn } from "../anim";

// Single-series area chart. Same dark panel / faint grid / white axes as LineChart, but
// with a filled gradient area under the curve (linearGradient from color@0.5 down to
// transparent). The line draws on left->right via stroke-dashoffset; the area fades up
// after the line lands. No markers. Renders full-bg or as a centered glass panel over
// transparent b-roll. Optional bold white title up top; fades out near the end.
export const AreaChart: React.FC<{
  title?: string;
  points: number[];
  xLabels?: string[];
  yLabel?: string;
  color?: string;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, points, xLabels, yLabel, color, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  // Panel geometry inside the 1920x1080 design (mirrors LineChart).
  const PW = fullBg ? 1920 : 1200;
  const PH = fullBg ? 1080 : 680;
  const padL = 120;
  const padR = 70;
  const padT = title ? 120 : 90;
  const padB = 110;
  const plotW = PW - padL - padR;
  const plotH = PH - padT - padB;
  const x0 = padL;
  const y0 = PH - padB; // baseline (bottom of plot)
  const yTop = padT;

  const lineColor = color || theme.chartA;

  // Domain with a little headroom/footroom so the curve doesn't kiss the edges.
  const rawMin = points.length ? Math.min(...points) : 0;
  const rawMax = points.length ? Math.max(...points) : 1;
  const span = rawMax - rawMin || 1;
  const minV = rawMin - span * 0.08;
  const maxV = rawMax + span * 0.08;
  const range = maxV - minV || 1;

  const n = points.length;
  const sx = (i: number) => x0 + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const sy = (v: number) => y0 - ((v - minV) / range) * plotH;

  // Catmull-Rom -> cubic bezier smoothing (same as LineChart).
  const buildLine = (pts: number[]): string => {
    const m = pts.length;
    if (m === 0) return "";
    const P = pts.map((v, i) => ({ x: sx(i), y: sy(v) }));
    if (m === 1) return `M ${P[0].x} ${P[0].y}`;
    let d = `M ${P[0].x} ${P[0].y}`;
    for (let i = 0; i < m - 1; i++) {
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

  const lineD = buildLine(points);
  // Close the line down to the baseline and back to the start for the fill.
  const areaD =
    n > 0
      ? `${lineD} L ${sx(n - 1)} ${y0} L ${sx(0)} ${y0} Z`
      : "";

  const gridYs = Array.from({ length: 5 }, (_, i) => yTop + (i / 4) * plotH);
  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });
  const titleA = fadeRise(frame, { delay: 4, dur: 12, dist: 14, outAt, outDur: 10 });

  // Line draws on first; area fades up once the line is mostly drawn.
  const lineDraw = drawOn(frame, { delay: 12, dur: 60 });
  const dashLen = (plotW + plotH) * 2.2;
  const areaFade =
    interpolate(frame, [48, 72], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }) * axisA.opacity;

  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Unique gradient id so multiple instances don't collide.
  const gradId = `areaGrad-${lineColor.replace(/[^a-zA-Z0-9]/g, "")}-${Math.round(plotW)}`;

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
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity={0.5} />
              <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
            </linearGradient>
          </defs>

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

          {/* Filled gradient area under the curve, fades up after the line. */}
          {areaD ? (
            <path d={areaD} fill={`url(#${gradId})`} opacity={areaFade * fadeOut} />
          ) : null}

          {/* White axes */}
          <line x1={x0} y1={yTop} x2={x0} y2={y0} stroke={theme.text} strokeWidth={2} opacity={axisA.opacity} />
          <line x1={x0} y1={y0} x2={x0 + plotW} y2={y0} stroke={theme.text} strokeWidth={2} opacity={axisA.opacity} />

          {/* Curve line, draws on left->right via stroke-dashoffset. */}
          {lineD ? (
            <path
              d={lineD}
              fill="none"
              stroke={lineColor}
              strokeWidth={4}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray={dashLen}
              strokeDashoffset={dashLen * (1 - lineDraw)}
              opacity={fadeOut}
            />
          ) : null}

          {/* X tick labels */}
          {xLabels &&
            xLabels.map((lab, i) => (
              <text
                key={`x${i}`}
                x={sx(Math.min(i, Math.max(0, n - 1)))}
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

          {/* Title */}
          {title ? (
            <text
              x={PW / 2}
              y={56}
              fill={theme.text}
              fontFamily={theme.bodyFont}
              fontSize={40}
              fontWeight={700}
              textAnchor="middle"
              opacity={titleA.opacity}
            >
              {title}
            </text>
          ) : null}
        </svg>
      </div>
    </AbsoluteFill>
  );
};
