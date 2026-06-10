import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { countUp, fmtNum, drawOn, popIn } from "../anim";

const W = 1920;
const H = 1080;

// Centered donut/ring stat. A faint background track ring sits under a theme.accent
// progress ring that fills clockwise from 12 o'clock to (value/100) of the circle via
// stroke-dashoffset (draw-on duration scales with the value). The big bold % numeral
// in the center counts up to value; a smaller muted label sits beneath. Renders on a
// dark theme.bg (fullBg) or transparent over b-roll. Pops in, fades out near the end.
export const DonutStat: React.FC<{
  value: number;
  suffix?: string;
  label?: string;
  trackColor?: string;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ value, suffix = "%", label, trackColor, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const cx = W / 2;
  const cy = H / 2;
  const radius = 220;
  const stroke = 36;
  const circ = 2 * Math.PI * radius;

  // Clamp progress to 0..1 of the circle; draw-on duration scales with magnitude
  // (bigger arcs take a touch longer) so the fill feels proportional.
  const frac = Math.max(0, Math.min(1, value / 100));
  const drawDur = Math.round(20 + frac * 24);
  const prog = drawOn(frame, { delay: 8, dur: drawDur }) * frac;

  const shown = countUp(frame, { to: value, delay: 8, dur: drawDur });

  // Whole-group pop-in + fade-out near the end.
  const pop = popIn(frame, fps, { delay: 0, from: 0.88, outAt, outDur: 10 });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const track = trackColor || theme.textMute;

  return (
    <AbsoluteFill
      style={{ ...(fullBg ? { background: theme.bg } : {}), pointerEvents: "none" }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: pop.opacity,
          transform: pop.transform,
        }}
      >
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height="100%"
          style={{ display: "block", overflow: "visible" }}
        >
          {/* Rotate the whole ring -90deg so the progress arc starts at 12 o'clock. */}
          <g transform={`rotate(-90 ${cx} ${cy})`}>
            {/* Faint background track ring. */}
            <circle
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke={track}
              strokeWidth={stroke}
              opacity={0.18}
            />
            {/* Accent progress ring, fills clockwise via stroke-dashoffset. */}
            <circle
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke={theme.accent}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={circ}
              strokeDashoffset={circ * (1 - prog)}
              opacity={fadeOut}
            />
          </g>
        </svg>

        {/* Centered readout: big count-up % numeral + smaller muted label beneath. */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          <div
            style={{
              fontFamily: theme.headerFont,
              fontWeight: 800,
              fontSize: 168,
              lineHeight: 0.95,
              color: theme.text,
              letterSpacing: -1,
              fontVariantNumeric: "tabular-nums",
              textShadow: "0 2px 18px rgba(0,0,0,.5)",
              opacity: fadeOut,
            }}
          >
            {fmtNum(shown, { suffix, commas: false })}
          </div>
          {label ? (
            <div
              style={{
                fontFamily: theme.bodyFont,
                fontWeight: 600,
                fontSize: 44,
                color: theme.textMute,
                marginTop: 18,
                letterSpacing: 0.5,
                textShadow: "0 2px 12px rgba(0,0,0,.45)",
                opacity: fadeOut,
              }}
            >
              {label}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
