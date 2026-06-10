import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { popIn, drawOn } from "../anim";

const W = 1920;
const H = 1080;

// Arrow callout: a small dark label pill at (fromX,fromY) pops in; then a colored arrow
// (line in color || theme.alert, ~5px, with an SVG marker arrowhead) draws from the label
// toward the target (toX,toY) via stroke-dashoffset; a small pulsing dot lands at the
// target when the arrow completes. Overlay (transparent bg), fades out near the end.
export const ArrowCallout: React.FC<{
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  label: string;
  color?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ fromX, fromY, toX, toY, label, color, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const stroke = color || theme.alert;

  // Absolute coords from 0..1 fractions.
  const fx = fromX * W;
  const fy = fromY * H;
  const tx = toX * W;
  const ty = toY * H;

  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  // Pill pops first; arrow draws after; dot pulses once the arrow lands.
  const pill = popIn(frame, fps, { delay: 4, from: 0.6, outAt, outDur: 10 });
  const pillScale = pill.transform.replace("scale(", "").replace(")", "");

  const arrowStart = 16;
  const arrowDur = 22;
  const draw = drawOn(frame, { delay: arrowStart, dur: arrowDur });
  const landed = frame >= arrowStart + arrowDur;

  // Shorten the line endpoints so it starts at the pill edge and stops short of the
  // target (leaving room for the arrowhead + the pulsing dot).
  const dx = tx - fx;
  const dy = ty - fy;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const startGap = 26; // clear the pill
  const endGap = 16; // clear the target dot
  const sx = fx + ux * startGap;
  const sy = fy + uy * startGap;
  const ex = tx - ux * endGap;
  const ey = ty - uy * endGap;
  const lineLen = Math.hypot(ex - sx, ey - sy);

  // Pulsing dot at the target after landing.
  const pulseT = landed ? (frame - (arrowStart + arrowDur)) / fps : 0;
  const pulse = 1 + 0.18 * Math.sin(pulseT * Math.PI * 2);
  const dotR = 12;
  const headId = "ac-head";

  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: rootOpacity }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        style={{ display: "block", overflow: "visible" }}
      >
        <defs>
          <marker
            id={headId}
            viewBox="0 0 10 10"
            refX={7}
            refY={5}
            markerWidth={6}
            markerHeight={6}
            orient="auto-start-reverse"
            markerUnits="strokeWidth"
          >
            <path d="M 0 0 L 10 5 L 0 10 L 3 5 Z" fill={stroke} />
          </marker>
        </defs>

        {/* Arrow line drawing on; arrowhead only once essentially drawn. */}
        <line
          x1={sx}
          y1={sy}
          x2={ex}
          y2={ey}
          stroke={stroke}
          strokeWidth={5}
          strokeLinecap="round"
          strokeDasharray={lineLen}
          strokeDashoffset={lineLen * (1 - draw)}
          markerEnd={landed ? `url(#${headId})` : undefined}
          style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,.45))" }}
        />

        {/* Pulsing target dot once the arrow lands. */}
        {landed ? (
          <g style={{ transform: `scale(${pulse})`, transformOrigin: `${tx}px ${ty}px` }}>
            <circle cx={tx} cy={ty} r={dotR + 6} fill={stroke} opacity={0.25} />
            <circle cx={tx} cy={ty} r={dotR} fill={stroke} stroke="#FFFFFF" strokeWidth={2.5} />
          </g>
        ) : null}
      </svg>

      {/* Dark label pill at the origin. */}
      <div
        style={{
          position: "absolute",
          left: `${fromX * 100}%`,
          top: `${fromY * 100}%`,
          transform: `translate(-50%, -50%) scale(${pillScale})`,
          transformOrigin: "center center",
          opacity: pill.opacity,
          background: "#0E0E0E",
          color: "#FFFFFF",
          fontFamily: theme.bodyFont,
          fontWeight: 700,
          fontSize: 30,
          letterSpacing: 0.3,
          padding: "12px 24px",
          borderRadius: 999,
          whiteSpace: "nowrap",
          boxShadow: "0 10px 28px rgba(0,0,0,0.5)",
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
