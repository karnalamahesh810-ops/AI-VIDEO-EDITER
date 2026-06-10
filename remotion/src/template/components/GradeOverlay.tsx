import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Theme } from "../theme";

const W = 1920;
const H = 1080;

// Cinematic LOOK layer to sit ON TOP of b-roll (pointerEvents none). Three stacked
// passes: (a) a radial-gradient vignette darkening the corners; (b) an animated film
// grain via an inline SVG feTurbulence (fractalNoise) painted into a full-frame rect at
// low opacity with mixBlendMode "overlay" — the turbulence seed advances every 2 frames
// so the grain shimmers; (c) an optional tint color as a low-opacity full-frame overlay
// in "soft-light". This is a constant look layer, so opacity stays ~1 throughout (no out).
export const GradeOverlay: React.FC<{
  vignette?: number;
  grain?: number;
  tint?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ vignette = 0.45, grain = 0.08, tint, theme, durationInFrames }) => {
  const frame = useCurrentFrame();

  // Reference theme + durationInFrames so the shared signature stays consistent across
  // the template (no-op here: this is a constant overlay with no theme color or timing).
  void theme;
  void durationInFrames;

  // Shimmer the grain by advancing the turbulence seed every 2 frames.
  const seed = Math.floor(frame / 2);
  // Unique filter id per seed so Remotion re-renders the turbulence each step.
  const grainFilterId = `grade-grain-${seed}`;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* (a) Radial vignette: transparent center -> dark corners. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 42%, rgba(0,0,0,${vignette}) 100%)`,
        }}
      />

      {/* (b) Animated film grain via feTurbulence, blended "overlay". */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        preserveAspectRatio="none"
        style={{
          position: "absolute",
          inset: 0,
          display: "block",
          opacity: grain,
          mixBlendMode: "overlay",
        }}
      >
        <defs>
          <filter id={grainFilterId} x="0%" y="0%" width="100%" height="100%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.9"
              numOctaves={2}
              seed={seed}
              stitchTiles="stitch"
              result="noise"
            />
            {/* Desaturate the noise to grayscale grain. */}
            <feColorMatrix in="noise" type="saturate" values="0" />
          </filter>
        </defs>
        <rect x={0} y={0} width={W} height={H} filter={`url(#${grainFilterId})`} />
      </svg>

      {/* (c) Optional color tint, blended "soft-light". */}
      {tint ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: tint,
            opacity: 0.22,
            mixBlendMode: "soft-light",
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};
