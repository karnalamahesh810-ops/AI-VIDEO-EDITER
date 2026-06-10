import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { fadeRise, slideIn } from "../anim";

// Vertical ranked "countdown" list (right-of-center). Each row pairs a big condensed
// rank numeral "#3" (accent) with a white label and an optional accent2 value pinned
// right. Rows slide in from the right, staggered ~7 frames, lowest rank first so the
// list builds up to #1 (the climax lands last). Optional bold white title up top.
// Sits over transparent b-roll; whole group fades out near the end.
export const CountdownList: React.FC<{
  title?: string;
  items: { rank: number; label: string; value?: string }[];
  theme: Theme;
  durationInFrames: number;
}> = ({ title, items, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Build to #1: reveal lowest rank first (largest number), #1 lands last.
  const ordered = [...items].sort((a, b) => b.rank - a.rank);

  const titleA = fadeRise(frame, { delay: 0, dur: 12, dist: 16, outAt, outDur: 10 });

  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: fadeOut }}>
      <div
        style={{
          position: "absolute",
          right: 120,
          top: "50%",
          transform: "translateY(-50%)",
          width: 880,
          display: "flex",
          flexDirection: "column",
          alignItems: "stretch",
        }}
      >
        {/* Optional bold white title on top. */}
        {title ? (
          <div
            style={{
              opacity: titleA.opacity,
              transform: titleA.transform,
              fontFamily: theme.bodyFont,
              fontWeight: 800,
              fontSize: 52,
              color: theme.text,
              letterSpacing: 0.5,
              marginBottom: 30,
              textShadow: "0 2px 18px rgba(0,0,0,0.6)",
            }}
          >
            {title}
          </div>
        ) : null}

        {ordered.map((it, i) => {
          // i=0 is the lowest rank (revealed first); #1 is last.
          const row = slideIn(frame, fps, {
            side: "right",
            delay: 8 + i * 7,
            dist: 160,
            outAt,
            outDur: 10,
          });
          return (
            <div
              key={`${it.rank}-${i}`}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 26,
                padding: "12px 0",
                opacity: row.opacity,
                transform: row.transform,
              }}
            >
              {/* Big rank numeral "#3". */}
              <div
                style={{
                  flex: "0 0 auto",
                  fontFamily: theme.headerFont,
                  fontWeight: 800,
                  fontSize: 84,
                  lineHeight: 0.9,
                  color: theme.accent,
                  letterSpacing: -1,
                  minWidth: 150,
                  textShadow: "0 2px 14px rgba(0,0,0,0.55)",
                }}
              >
                #{it.rank}
              </div>

              {/* Label fills the middle. */}
              <div
                style={{
                  flex: "1 1 auto",
                  fontFamily: theme.bodyFont,
                  fontWeight: 700,
                  fontSize: 46,
                  lineHeight: 1.1,
                  color: theme.text,
                  textShadow: "0 2px 14px rgba(0,0,0,0.6)",
                }}
              >
                {it.label}
              </div>

              {/* Optional value pinned right. */}
              {it.value ? (
                <div
                  style={{
                    flex: "0 0 auto",
                    fontFamily: theme.bodyFont,
                    fontWeight: 800,
                    fontSize: 44,
                    color: theme.accent2,
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    textShadow: "0 2px 14px rgba(0,0,0,0.55)",
                  }}
                >
                  {it.value}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
