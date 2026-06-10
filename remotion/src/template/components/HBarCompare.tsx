import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, countUp, fmtNum, stagger } from "../anim";

const W = 1920;
const H = 1080;

// Horizontal bar comparison. Bars grow left->right from a shared left baseline,
// staggered top->bottom (~6 frames apart). Each row has a category label to the LEFT
// of its bar and a count-up value pinned at the bar's right end. Normal bars use
// chartA; the spotlight bar uses chartB/accent2. Renders on a dark theme.panel (fullBg)
// or as a transparent glass panel over b-roll. Optional bold white title up top.
export const HBarCompare: React.FC<{
  title?: string;
  bars: { label: string; value: number; spotlight?: boolean }[];
  valueFmt?: { prefix?: string; suffix?: string; compact?: boolean };
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, bars, valueFmt, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const PW = fullBg ? 1920 : 1280;
  const PH = fullBg ? 1080 : 720;
  const padX = fullBg ? 120 : 70;
  const padTop = title ? 150 : 90;
  const padBottom = 90;
  // Row geometry: label gutter on the left, then the bar track to the right.
  const labelW = 360;
  const valueW = 180; // reserved space so the value never clips the panel edge
  const trackX = padX + labelW;
  const trackW = PW - trackX - padX - valueW;

  const n = Math.max(1, bars.length);
  const maxVal = Math.max(1, ...bars.map((b) => b.value));
  const niceMax = maxVal * 1.08;

  const areaH = PH - padTop - padBottom;
  const slot = areaH / n;
  const barH = Math.min(72, slot * 0.56);

  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });
  const titleA = fadeRise(frame, { delay: 4, dur: 12, dist: 14, outAt, outDur: 10 });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

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

          {/* Left baseline the bars grow from. */}
          <line
            x1={trackX}
            x2={trackX}
            y1={padTop}
            y2={PH - padBottom}
            stroke={theme.text}
            strokeWidth={2}
            opacity={0.6 * axisA.opacity}
          />

          {/* Bars */}
          {bars.map((b, i) => {
            const cy = padTop + slot * i + slot / 2;
            const by = cy - barH / 2;
            const targetW = (b.value / niceMax) * trackW;
            const grow = interpolate(
              frame,
              [16 + i * 6, 16 + i * 6 + 18],
              [0, 1],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
            );
            const w = targetW * grow;
            const fill = b.spotlight
              ? theme.chartB || theme.accent2
              : theme.chartA || theme.accent;

            // Value label tracks the growing right end; counts up as the bar lands.
            const labelDelay = 16 + i * 6 + 10;
            const valNow = countUp(frame, { to: b.value, delay: labelDelay, dur: 18 });
            const labA = stagger(frame, i, { delay: labelDelay, step: 0, dur: 10 });

            return (
              <g key={`b${i}`}>
                {/* Category label, left of the baseline. */}
                <text
                  x={trackX - 24}
                  y={cy}
                  fill={theme.text}
                  fontFamily={theme.bodyFont}
                  fontSize={30}
                  fontWeight={b.spotlight ? 700 : 600}
                  textAnchor="end"
                  dominantBaseline="central"
                  opacity={axisA.opacity}
                >
                  {b.label}
                </text>

                {/* Bar grows left->right from the baseline. */}
                <rect
                  x={trackX}
                  y={by}
                  width={Math.max(0, w)}
                  height={barH}
                  rx={8}
                  fill={fill}
                  opacity={axisA.opacity}
                />

                {/* Value label pinned just past the bar's right end. */}
                <text
                  x={trackX + Math.max(0, w) + 18}
                  y={cy}
                  fill={theme.text}
                  fontFamily={theme.bodyFont}
                  fontSize={30}
                  fontWeight={700}
                  textAnchor="start"
                  dominantBaseline="central"
                  opacity={labA * fadeOut}
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {fmtNum(valNow, {
                    prefix: valueFmt?.prefix,
                    suffix: valueFmt?.suffix,
                    compact: valueFmt?.compact,
                  })}
                </text>
              </g>
            );
          })}

          {/* Optional bold white title, top-left of the panel. */}
          {title ? (
            <text
              x={padX}
              y={84}
              fill={theme.text}
              fontFamily={theme.bodyFont}
              fontSize={46}
              fontWeight={800}
              textAnchor="start"
              opacity={titleA.opacity}
              style={{ letterSpacing: 0.5 }}
            >
              {title}
            </text>
          ) : null}
        </svg>
      </div>
    </AbsoluteFill>
  );
};
