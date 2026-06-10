import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { popIn, typewriter } from "../anim";

// Centered white tweet card (~900px) on a solid colored backdrop. Header row: a circular
// avatar (bgColor fill, white letter), a bold dark handle and a muted timestamp. Below,
// the tweet body types in after the card pops in with a slight overshoot. Fades out near
// the end.
export const TweetCard: React.FC<{
  handle: string;
  time: string;
  body: string;
  avatarLetter?: string;
  bgColor?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ handle, time, body, avatarLetter, bgColor = "#8186C4", theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Card pops in with overshoot; body types after the card has settled.
  const card = popIn(frame, fps, { delay: 0, from: 0.82, outAt, outDur: 12 });
  const tw = typewriter(frame, fps, body, { delay: 14, cps: 38, cursor: true });

  const letter = (avatarLetter ?? (handle.replace(/^@/, "").charAt(0) || "?")).toUpperCase();

  return (
    <AbsoluteFill
      style={{
        background: bgColor,
        opacity: fadeOut,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: 900,
          background: "#FFFFFF",
          borderRadius: 28,
          padding: "44px 48px",
          boxShadow: "0 30px 80px rgba(0,0,0,0.32)",
          opacity: card.opacity,
          transform: card.transform,
        }}
      >
        {/* Header row: avatar + handle + timestamp. */}
        <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
          <div
            style={{
              width: 86,
              height: 86,
              borderRadius: "50%",
              background: bgColor,
              flex: "0 0 auto",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#FFFFFF",
              fontFamily: theme.bodyFont,
              fontWeight: 800,
              fontSize: 44,
            }}
          >
            {letter}
          </div>
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
            <div
              style={{
                fontFamily: theme.bodyFont,
                fontWeight: 800,
                fontSize: 38,
                color: "#15202B",
              }}
            >
              {handle}
            </div>
            <div
              style={{
                fontFamily: theme.bodyFont,
                fontWeight: 500,
                fontSize: 26,
                color: "#5B7083",
                marginTop: 4,
              }}
            >
              {time}
            </div>
          </div>
        </div>

        {/* Tweet body that types in. */}
        <div
          style={{
            marginTop: 30,
            fontFamily: theme.bodyFont,
            fontWeight: 500,
            fontSize: 42,
            lineHeight: 1.4,
            color: "#15202B",
            minHeight: 42 * 1.4,
          }}
        >
          {tw.text}
          {tw.cursor ? (
            <span style={{ color: "#15202B", fontWeight: 400 }}>|</span>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
