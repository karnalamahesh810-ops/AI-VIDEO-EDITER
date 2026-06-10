import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, countUp, fmtNum, stagger } from "../anim";

// Animated vertical bar chart. Bars grow up from a baseline, staggered left->right;
// value labels count up above each bar as it lands. Spotlight bar uses chartB/accent2.
// Renders full-bg or as a centered glass panel over transparent b-roll.
export const BarChart: React.FC<{
  title: string;
  bars: { label: string; value: number; spotlight?: boolean }[];
  yLabel?: string;
  valueFmt?: { prefix?: string; suffix?: string; compact?: boolean };
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, bars, yLabel, valueFmt, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const PW = fullBg ? 1920 : 1200;
  const PH = fullBg ? 1080 : 680;
  const padL = 120;
  const padR = 70;
  const padT = 130;
  const padB = 110;
  const plotW = PW - padL - padR;
  const plotH = PH - padT - padB;
  const x0 = padL;
  const y0 = PH - padB; // baseline
  const yTop = padT;

  const n = Math.max(1, bars.length);
  const maxVal = Math.max(1, ...bars.map((b) => b.value));
  const niceMax = maxVal * 1.12;

  // Bar layout: even slots, bar ~62% of slot width.
  const slot = plotW / n;
  const barW = slot * 0.62;

  const gridYs = Array.from({ length: 5 }, (_, i) => yTop + (i / 4) * plotH);
  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });

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
          <line x1={x0} y1={yTop} x2={x0} y2={y0} stroke={theme.text} strokeWidth={2} opacity={axisA.opacity} />
          <line x1={x0} y1={y0} x2={x0 + plotW} y2={y0} stroke={theme.text} strokeWidth={2} opacity={axisA.opacity} />

          {/* Bars */}
          {bars.map((b, i) => {
            const cx = x0 + slot * i + slot / 2;
            const bx = cx - barW / 2;
            const targetH = (b.value / niceMax) * plotH;
            const grow = interpolate(
              frame,
              [16 + i * 6, 16 + i * 6 + 18],
              [0, 1],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
            );
            const h = targetH * grow;
            const by = y0 - h;
            const fill = b.spotlight
              ? theme.chartB || theme.accent2
              : theme.chartA || theme.accent;

            // Value label appears as the bar lands.
            const labelDelay = 16 + i * 6 + 12;
            const valNow = countUp(frame, { to: b.value, delay: labelDelay, dur: 18 });
            const labA = stagger(frame, i, { delay: labelDelay, step: 0, dur: 10 });
            const labOut = interpolate(frame, [outAt, outAt + 10], [1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });

            return (
              <g key={`b${i}`}>
                <rect
                  x={bx}
                  y={by}
                  width={barW}
                  height={Math.max(0, h)}
                  rx={6}
                  fill={fill}
                  opacity={axisA.opacity}
                />
                {/* Value label above bar */}
                <text
                  x={cx}
                  y={by - 16}
                  fill={theme.text}
                  fontFamily={theme.bodyFont}
                  fontSize={28}
                  fontWeight={700}
                  textAnchor="middle"
                  opacity={labA * labOut}
                >
                  {fmtNum(valNow, {
                    prefix: valueFmt?.prefix,
                    suffix: valueFmt?.suffix,
                    compact: valueFmt?.compact,
                  })}
                </text>
                {/* Category label below baseline */}
                <text
                  x={cx}
                  y={y0 + 36}
                  fill={theme.textMute}
                  fontFamily={theme.bodyFont}
                  fontSize={22}
                  textAnchor="middle"
                  opacity={axisA.opacity}
                >
                  {b.label}
                </text>
              </g>
            );
          })}

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
          <text
            x={PW / 2}
            y={60}
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
