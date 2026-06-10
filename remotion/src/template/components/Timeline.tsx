import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";
import { Theme } from "../theme";
import { fadeRise, popIn } from "../anim";

const W = 1920;
const H = 1080;

// Horizontal timeline scrubber. A thin white axis sits at vertical center with evenly
// spaced tick marks. A theme.accent playhead bar springs horizontally from the left to
// the activeIndex tick; a rounded dark chip (accent outline) carrying `label` pops in
// above it. Small muted tick labels sit under each tick. Fades out near the end.
export const Timeline: React.FC<{
  ticks: string[];
  activeIndex: number;
  label: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ ticks, activeIndex, label, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
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

  // Axis geometry.
  const axisY = H / 2;
  const padX = 220;
  const x0 = padX;
  const x1 = W - padX;
  const span = x1 - x0;

  const n = Math.max(1, ticks.length);
  const tickX = (i: number) => (n <= 1 ? (x0 + x1) / 2 : x0 + (i / (n - 1)) * span);

  // Clamp the target index into range, then spring the playhead toward it.
  const idx = Math.max(0, Math.min(n - 1, activeIndex));
  const s = spring({ frame: frame - 8, fps, config: { damping: 18, mass: 0.9 }, durationInFrames: 26 });
  const startX = x0;
  const targetX = tickX(idx);
  const headX = startX + (targetX - startX) * s;

  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });
  // Chip pop: take the spring scale out of popIn so we can compose it with the centering
  // translate in a single transform string.
  const chip = popIn(frame, fps, { delay: 16, from: 0.7, outAt, outDur: 10 });
  const chipScale = chip.transform.replace("scale(", "").replace(")", "");

  const playW = 8;
  const playH = 150;
  const tickH = 26;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: rootOpacity }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        style={{ display: "block", overflow: "visible" }}
      >
        {/* Thin white horizontal axis. */}
        <line
          x1={x0}
          y1={axisY}
          x2={x1}
          y2={axisY}
          stroke={theme.text}
          strokeWidth={2}
          opacity={axisA.opacity}
        />

        {/* Evenly spaced tick marks + muted labels under each. */}
        {ticks.map((t, i) => {
          const x = tickX(i);
          return (
            <g key={`t${i}`}>
              <line
                x1={x}
                y1={axisY - tickH / 2}
                x2={x}
                y2={axisY + tickH / 2}
                stroke={theme.text}
                strokeWidth={2}
                opacity={0.7 * axisA.opacity}
              />
              <text
                x={x}
                y={axisY + tickH / 2 + 40}
                fill={theme.textMute}
                fontFamily={theme.bodyFont}
                fontSize={24}
                textAnchor="middle"
                opacity={axisA.opacity}
              >
                {t}
              </text>
            </g>
          );
        })}

        {/* Accent playhead bar sliding to the active tick. */}
        <rect
          x={headX - playW / 2}
          y={axisY - playH / 2}
          width={playW}
          height={playH}
          rx={4}
          fill={theme.accent}
          opacity={axisA.opacity}
          style={{ filter: `drop-shadow(0 0 12px ${theme.accent})` }}
        />
      </svg>

      {/* Rounded label chip popping in above the playhead. */}
      <div
        style={{
          position: "absolute",
          left: (headX / W) * 100 + "%",
          top: ((axisY - playH / 2) / H) * 100 + "%",
          transformOrigin: "center bottom",
          transform: `translate(-50%, -130%) scale(${chipScale})`,
          background: theme.panel,
          border: `2px solid ${theme.accent}`,
          borderRadius: 999,
          padding: "12px 28px",
          color: theme.text,
          fontFamily: theme.bodyFont,
          fontWeight: 700,
          fontSize: 30,
          whiteSpace: "nowrap",
          boxShadow: "0 10px 28px rgba(0,0,0,0.5)",
          opacity: chip.opacity,
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
