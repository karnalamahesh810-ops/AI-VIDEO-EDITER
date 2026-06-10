import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { slideIn, fadeRise } from "../anim";

// Chapter divider. A full-frame dark scrim keeps text legible over whatever b-roll sits
// behind it. A giant ALL-CAPS condensed headline lives in the lower-left third (or
// centered) and slides in from the left; a smaller mixed-case subtitle (e.g.
// "Layer 3 — Detection", em-dash preserved) rises in just after. Whole block fades out.
export const SectionTitle: React.FC<{
  headline: string;
  subtitle?: string;
  align?: "left" | "center";
  theme: Theme;
  durationInFrames: number;
}> = ({ headline, subtitle, align = "left", theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;
  const isLeft = align === "left";

  // Scrim fades out a touch before the text so it never lingers as a flat wash.
  const scrim = interpolate(frame, [0, 10, outAt, outAt + 12], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const head = slideIn(frame, fps, { side: "left", delay: 0, dist: 140, outAt, outDur: 12 });
  const sub = fadeRise(frame, { delay: 6, dur: 12, dist: 16, outAt, outDur: 10 });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Full-frame dark scrim for legibility over any background. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(0,0,0,.45)",
          opacity: scrim,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: isLeft ? "flex-end" : "center",
          alignItems: isLeft ? "flex-start" : "center",
          textAlign: isLeft ? "left" : "center",
          padding: isLeft ? "0 8% 22% 8%" : "0 6%",
        }}
      >
        <div
          style={{
            opacity: head.opacity,
            transform: head.transform,
            fontFamily: theme.headerFont,
            textTransform: "uppercase",
            fontWeight: 700,
            letterSpacing: 1,
            fontSize: 84,
            lineHeight: 1.0,
            color: "#FFFFFF",
            maxWidth: "88%",
            textShadow: "0 2px 18px rgba(0,0,0,.55), 0 4px 40px rgba(0,0,0,.4)",
          }}
        >
          {headline}
        </div>
        {subtitle ? (
          <div
            style={{
              opacity: sub.opacity * 0.85,
              transform: sub.transform,
              marginTop: 18,
              fontFamily: theme.bodyFont,
              fontWeight: 500,
              fontSize: 34,
              lineHeight: 1.25,
              color: "#FFFFFF",
              maxWidth: "80%",
              textShadow: "0 2px 12px rgba(0,0,0,.6)",
            }}
          >
            {subtitle}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
