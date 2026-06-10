import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { stagger } from "../anim";

// Bottom-left progressive caption (1-5 lines), white bold sans with soft shadow.
// Lines reveal staggered; a highlighted line gets its text on a solid alert marker bar.
// Whole block fades out near the end.
export const HighlightCaption: React.FC<{
  lines: { text: string; highlight?: boolean }[];
  theme: Theme;
  durationInFrames: number;
}> = ({ lines, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  useVideoConfig();

  const outAt = durationInFrames - 12;
  const out = interpolate(frame, [outAt, outAt + 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 80,
          top: "80%",
          transform: "translateY(-50%)",
          maxWidth: 1100,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 10,
          opacity: 1 - out,
        }}
      >
        {lines.map((ln, i) => {
          const p = stagger(frame, i, { delay: 0, step: 8, dur: 8 });
          return (
            <div
              key={i}
              style={{
                opacity: p,
                transform: `translateY(${(1 - p) * 14}px)`,
              }}
            >
              <span
                style={{
                  fontFamily: theme.bodyFont,
                  fontWeight: 700,
                  fontSize: 44,
                  lineHeight: 1.3,
                  color: "#fff",
                  ...(ln.highlight
                    ? {
                        background: theme.alert,
                        padding: "4px 14px",
                        boxDecorationBreak: "clone",
                        WebkitBoxDecorationBreak: "clone",
                        textShadow: "none",
                      }
                    : {
                        textShadow: "0 3px 10px rgba(0,0,0,0.7)",
                      }),
                }}
              >
                {ln.text}
              </span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
