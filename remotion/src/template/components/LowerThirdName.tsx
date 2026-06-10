import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { slideIn } from "../anim";

// Interview-style lower-third, bottom-left (~10% margins): a vertical accent bar
// (accent || theme.accent, ~6px) + the name (white bold, ~46px) on line 1 and the title
// (muted, ~28px) on line 2, on a subtle dark gradient plate. The plate slides in from the
// left; the accent bar grows vertically first. OUT slide + fade near the end.
export const LowerThirdName: React.FC<{
  name: string;
  title?: string;
  accent?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ name, title, accent, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const accentColor = accent || theme.accent;

  // Plate slides in from the left (and back out near the end).
  const plate = slideIn(frame, fps, { side: "left", delay: 0, dist: 160, outAt, outDur: 10 });

  // Accent bar grows vertically first (after the plate has begun to settle).
  const barGrow = interpolate(frame, [6, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // Text fades in just after the bar starts growing.
  const textIn = interpolate(frame, [12, 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const barH = title ? 92 : 64;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: "8%",
          bottom: "10%",
          display: "flex",
          alignItems: "stretch",
          gap: 22,
          opacity: plate.opacity,
          transform: plate.transform,
          // Subtle dark gradient plate behind the text.
          background: "linear-gradient(90deg, rgba(8,10,14,0.82) 0%, rgba(8,10,14,0.55) 70%, rgba(8,10,14,0) 100%)",
          padding: "18px 56px 18px 22px",
          borderRadius: 6,
        }}
      >
        {/* Vertical accent bar, grows from the vertical center outward. */}
        <div
          style={{
            flex: "0 0 auto",
            alignSelf: "center",
            width: 6,
            height: barH * barGrow,
            background: accentColor,
            borderRadius: 3,
            boxShadow: `0 0 14px ${accentColor}88`,
          }}
        />
        {/* Name + optional title. */}
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", opacity: textIn }}>
          <div
            style={{
              fontFamily: theme.bodyFont,
              fontWeight: 800,
              fontSize: 46,
              lineHeight: 1.1,
              color: theme.text,
              letterSpacing: 0.3,
              textShadow: "0 2px 14px rgba(0,0,0,0.6)",
            }}
          >
            {name}
          </div>
          {title ? (
            <div
              style={{
                marginTop: 6,
                fontFamily: theme.bodyFont,
                fontWeight: 500,
                fontSize: 28,
                lineHeight: 1.2,
                color: theme.textMute,
                letterSpacing: 0.4,
                textShadow: "0 2px 12px rgba(0,0,0,0.55)",
              }}
            >
              {title}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
