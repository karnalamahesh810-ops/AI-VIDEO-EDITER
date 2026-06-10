import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
  staticFile,
} from "remotion";
import { Theme } from "../theme";
import { fadeRise, drawOn } from "../anim";

const W = 1920;
const H = 1080;

// Satellite-look map highlight: full-frame map (image or dark placeholder) with a
// slow ken-burns push, a red stroked circle that draws on around the target then
// subtly pulses, and a bottom-left bold label that fades up.
export const MapHighlight: React.FC<{
  mapSrc?: string;
  target: { x: number; y: number; r: number };
  label: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ mapSrc, target, label, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const cx = target.x * W;
  const cy = target.y * H;
  const r = target.r;
  const circ = 2 * Math.PI * r;

  const drawStart = 14;
  const drawDur = 50;
  const draw = drawOn(frame, { delay: drawStart, dur: drawDur });
  const drawn = frame >= drawStart + drawDur;

  // Subtle pulse after the circle completes (scales the stroked ring slightly).
  const pulseT = (frame - (drawStart + drawDur)) / fps;
  const pulse = drawn ? 1 + 0.04 * Math.sin(pulseT * Math.PI * 1.4) : 1;

  // Ken-burns push.
  const kb = interpolate(frame, [0, durationInFrames], [1.04, 1.12], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });

  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  const ringOut = interpolate(frame, [outAt, outAt + 10], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const labelA = fadeRise(frame, { delay: drawStart + drawDur - 14, dur: 14, dist: 18, outAt, outDur: 10 });

  return (
    <AbsoluteFill style={{ background: theme.bg, opacity: rootOpacity }}>
      {/* Map layer (image or placeholder), ken-burns */}
      <AbsoluteFill style={{ transform: `scale(${kb})`, transformOrigin: "center center" }}>
        {mapSrc ? (
          <img
            src={staticFile(mapSrc)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "saturate(0.8)",
            }}
            alt=""
          />
        ) : (
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block" }}>
            <defs>
              <radialGradient id="mh-sat" cx="50%" cy="45%" r="75%">
                <stop offset="0%" stopColor="#243042" />
                <stop offset="60%" stopColor="#151D29" />
                <stop offset="100%" stopColor="#0B0F16" />
              </radialGradient>
            </defs>
            <rect x={0} y={0} width={W} height={H} fill="url(#mh-sat)" />
            {/* Faint grid */}
            {Array.from({ length: 13 }, (_, i) => (
              <line
                key={`v${i}`}
                x1={(i / 12) * W}
                y1={0}
                x2={(i / 12) * W}
                y2={H}
                stroke="#FFFFFF"
                strokeWidth={1}
                opacity={0.05}
              />
            ))}
            {Array.from({ length: 8 }, (_, i) => (
              <line
                key={`h${i}`}
                x1={0}
                y1={(i / 7) * H}
                x2={W}
                y2={(i / 7) * H}
                stroke="#FFFFFF"
                strokeWidth={1}
                opacity={0.05}
              />
            ))}
          </svg>
        )}
      </AbsoluteFill>

      {/* Overlay: highlight ring (screen space, unscaled) */}
      <AbsoluteFill>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block", overflow: "visible" }}>
          <g
            style={{
              transform: `scale(${pulse})`,
              transformOrigin: `${cx}px ${cy}px`,
            }}
          >
            <circle
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={theme.alert}
              strokeWidth={5}
              strokeLinecap="round"
              strokeDasharray={circ}
              strokeDashoffset={circ * (1 - draw)}
              transform={`rotate(-90 ${cx} ${cy})`}
              opacity={ringOut}
              style={{ filter: "drop-shadow(0 2px 8px rgba(0,0,0,.55))" }}
            />
          </g>
        </svg>
      </AbsoluteFill>

      {/* Bottom-left label */}
      <div
        style={{
          position: "absolute",
          left: "6%",
          bottom: "8%",
          opacity: labelA.opacity,
          transform: labelA.transform,
          fontFamily: theme.bodyFont,
          fontWeight: 700,
          fontSize: 58,
          color: theme.text,
          letterSpacing: 0.3,
          textShadow: "0 2px 18px rgba(0,0,0,.6), 0 0 28px rgba(0,0,0,.45)",
          maxWidth: "70%",
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
