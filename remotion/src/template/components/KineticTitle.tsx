import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Theme } from "../theme";
import { fadeRise } from "../anim";

// Full-screen chapter title. Giant condensed ALL-CAPS lines, vertically centered,
// revealing line-by-line. A subtle bottom-up dark gradient keeps it legible over
// any b-roll.
export const KineticTitle: React.FC<{
  lines: string[];
  align?: "left" | "center";
  size?: number;
  theme: Theme;
  durationInFrames: number;
}> = ({ lines, align = "center", size = 110, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;
  const isLeft = align === "left";

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Legibility gradient: darkest at the bottom, fading up. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(to top, rgba(0,0,0,.62) 0%, rgba(0,0,0,.30) 38%, rgba(0,0,0,0) 70%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: isLeft ? "flex-start" : "center",
          textAlign: isLeft ? "left" : "center",
          padding: isLeft ? "0 8%" : "0 6%",
        }}
      >
        {lines.map((line, i) => {
          const a = fadeRise(frame, { delay: i * 6, dur: 14, dist: 18, outAt, outDur: 10 });
          return (
            <div
              key={i}
              style={{
                opacity: a.opacity,
                transform: a.transform,
                fontFamily: theme.headerFont,
                textTransform: "uppercase",
                fontWeight: 700,
                letterSpacing: 1,
                fontSize: size,
                lineHeight: 0.98,
                color: theme.text,
                textShadow: "0 2px 18px rgba(0,0,0,.55), 0 4px 40px rgba(0,0,0,.4)",
              }}
            >
              {line}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
