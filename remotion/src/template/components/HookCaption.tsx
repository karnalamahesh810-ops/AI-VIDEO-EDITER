import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { popIn } from "../anim";

// Intro VO subtitle, lower-left. 2-4 white bold rounded-sans lines with a soft shadow;
// a solid red (theme.alert) square caret "▮" leads the FIRST line. If `keyword` is given
// and appears in a line, that occurrence is rendered ALL-CAPS in theme.accent2. Lines
// reveal with a quick fade+pop, staggered ~5 frames. Whole block fades out near the end.
export const HookCaption: React.FC<{
  lines: string[];
  keyword?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ lines, keyword, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const out = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Split a line around the (case-insensitive) keyword, emphasizing the matched span.
  const renderLine = (text: string): React.ReactNode => {
    if (!keyword) return text;
    const idx = text.toLowerCase().indexOf(keyword.toLowerCase());
    if (idx < 0) return text;
    const before = text.slice(0, idx);
    const match = text.slice(idx, idx + keyword.length);
    const after = text.slice(idx + keyword.length);
    return (
      <>
        {before}
        <span style={{ color: theme.accent2, textTransform: "uppercase", fontWeight: 800 }}>
          {match}
        </span>
        {after}
      </>
    );
  };

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 80,
          bottom: 120,
          maxWidth: 1180,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 8,
          opacity: out,
        }}
      >
        {lines.map((line, i) => {
          const a = popIn(frame, fps, { delay: i * 5, from: 0.9 });
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 14,
                opacity: a.opacity,
                transform: a.transform,
                transformOrigin: "left center",
              }}
            >
              {i === 0 ? (
                <span
                  style={{
                    color: theme.alert,
                    fontSize: "0.8em",
                    lineHeight: 1,
                    fontFamily: theme.bodyFont,
                  }}
                >
                  ▮
                </span>
              ) : null}
              <span
                style={{
                  fontFamily: theme.bodyFont,
                  fontWeight: 700,
                  fontSize: 46,
                  lineHeight: 1.28,
                  color: "#FFFFFF",
                  textShadow: "0 3px 12px rgba(0,0,0,.7), 0 1px 2px rgba(0,0,0,.6)",
                }}
              >
                {renderLine(line)}
              </span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
