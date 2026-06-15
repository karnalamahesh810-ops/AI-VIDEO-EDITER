import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "../theme";
import { fadeRise, slideIn } from "../anim";

// News-style lower-third alert: an accent kicker tag, a bold headline, and a muted
// body line, left-aligned low in frame behind a soft bottom scrim with a left accent
// bar. Matches the references' "USGS: Second Blast Stronger / USGS confirms..." cards.
export const NewsLowerThird: React.FC<{
  kicker?: string;
  headline: string;
  body?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ kicker, headline, body, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const bar = slideIn(frame, fps, { side: "left", delay: 0, dist: 60, outAt, outDur: 10 });
  const h = fadeRise(frame, { delay: 4, dur: 12, dist: 14, outAt, outDur: 10 });
  const b = fadeRise(frame, { delay: 9, dur: 12, dist: 12, outAt, outDur: 10 });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* soft bottom scrim for legibility */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: "42%",
          background: "linear-gradient(to top, rgba(0,0,0,.62), rgba(0,0,0,0))",
          opacity: bar.opacity,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 90,
          bottom: 110,
          maxWidth: 1180,
          opacity: bar.opacity,
          transform: bar.transform,
          paddingLeft: 26,
          borderLeft: `6px solid ${theme.accent2}`,
        }}
      >
        {kicker ? (
          <div
            style={{
              display: "inline-block",
              background: theme.alert,
              color: "#fff",
              fontFamily: theme.headerFont,
              fontWeight: 800,
              textTransform: "uppercase",
              letterSpacing: 1.5,
              fontSize: 22,
              padding: "5px 12px",
              marginBottom: 12,
              borderRadius: 3,
            }}
          >
            {kicker}
          </div>
        ) : null}
        <div
          style={{
            opacity: h.opacity,
            transform: h.transform,
            fontFamily: theme.bodyFont,
            fontWeight: 800,
            fontSize: 58,
            lineHeight: 1.08,
            color: "#fff",
            textShadow: "0 3px 16px rgba(0,0,0,.7)",
            maxWidth: 1080,
          }}
        >
          {headline}
        </div>
        {body ? (
          <div
            style={{
              opacity: b.opacity,
              transform: b.transform,
              marginTop: 12,
              fontFamily: theme.bodyFont,
              fontWeight: 500,
              fontSize: 30,
              lineHeight: 1.35,
              color: "rgba(255,255,255,.88)",
              textShadow: "0 2px 10px rgba(0,0,0,.7)",
              maxWidth: 1000,
            }}
          >
            {body}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
