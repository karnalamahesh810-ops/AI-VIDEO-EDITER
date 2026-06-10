import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Theme } from "../theme";
import { fadeRise } from "../anim";

// Workhorse lower-third headline. White bold lines sitting low in frame over a soft
// dark scrim (no solid bar), revealing one-by-one with a small fade+rise stagger.
export const LowerThirdTitle: React.FC<{
  lines: string[];
  align?: "center" | "left";
  yPct?: number;
  size?: number;
  theme: Theme;
  durationInFrames: number;
}> = ({ lines, align = "center", yPct = 76, size = 52, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const isLeft = align === "left";

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          top: `${yPct}%`,
          left: isLeft ? "8%" : 0,
          right: isLeft ? "8%" : 0,
          transform: "translateY(-50%)",
          display: "flex",
          flexDirection: "column",
          alignItems: isLeft ? "flex-start" : "center",
          textAlign: isLeft ? "left" : "center",
          // Soft dark scrim behind the text (radial, no hard edges).
          padding: "12px 0",
        }}
      >
        {lines.map((line, i) => {
          const a = fadeRise(frame, { delay: i * 4, dur: 12, dist: 16, outAt, outDur: 10 });
          return (
            <div
              key={i}
              style={{
                opacity: a.opacity,
                transform: a.transform,
                fontFamily: theme.bodyFont,
                fontWeight: 700,
                fontSize: size,
                lineHeight: 1.14,
                color: theme.text,
                letterSpacing: 0.2,
                maxWidth: "84%",
                textShadow:
                  "0 2px 18px rgba(0,0,0,.55), 0 0 36px rgba(0,0,0,.45), 0 1px 2px rgba(0,0,0,.7)",
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
