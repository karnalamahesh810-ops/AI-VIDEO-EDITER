import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";

// Bottom-left rounded-rectangle pill: bold value + accent dot separator + uppercase label.
// Grows from the left (scaleX origin-left) with a quick fade in; fades out near the end.
export const PillChyron: React.FC<{
  value: string;
  label: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ value, label, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const grow = interpolate(frame, [0, Math.round(fps * 0.3)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const outAt = durationInFrames - 12;
  const out = interpolate(frame, [outAt, outAt + 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = grow * (1 - out);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 80,
          bottom: 96,
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "16px 30px",
          borderRadius: 999,
          background: theme.panel,
          opacity: 0.9 * opacity,
          boxShadow: "0 10px 30px rgba(0,0,0,0.4)",
          transform: `scaleX(${0.7 + 0.3 * grow})`,
          transformOrigin: "left center",
        }}
      >
        <span
          style={{
            fontFamily: theme.bodyFont,
            fontWeight: 800,
            fontSize: 34,
            color: "#fff",
            letterSpacing: 0.2,
          }}
        >
          {value}
        </span>
        <span
          style={{
            flex: "0 0 auto",
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: theme.accent,
          }}
        />
        <span
          style={{
            fontFamily: theme.headerFont,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 1.2,
            fontSize: 26,
            color: theme.text,
          }}
        >
          {label}
        </span>
      </div>
    </AbsoluteFill>
  );
};
