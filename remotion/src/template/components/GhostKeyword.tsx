import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";

// Watermark-like keyword reinforcement. Large ALL-CAPS bold white text centered in the
// lower third at low opacity (~0.16). Slow fade in, hold, slow fade out — deliberately
// subtle so it sits under the foreground rather than competing with it.
export const GhostKeyword: React.FC<{
  text: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ text, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  // Slow in (dur ~20), hold, slow out — peak opacity is intentionally faint.
  const peak = 0.16;
  const opacity = interpolate(
    frame,
    [0, 20, outAt, outAt + 12],
    [0, peak, peak, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.ease),
    }
  );

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "center",
          paddingBottom: "12%",
        }}
      >
        <div
          style={{
            opacity,
            fontFamily: theme.headerFont,
            textTransform: "uppercase",
            fontWeight: 700,
            letterSpacing: 2,
            fontSize: 120,
            lineHeight: 1.0,
            color: "#FFFFFF",
            textAlign: "center",
            maxWidth: "92%",
          }}
        >
          {text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
