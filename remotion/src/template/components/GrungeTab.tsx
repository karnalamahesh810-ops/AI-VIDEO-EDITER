import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { countUp, fmtNum } from "../anim";

// Bottom-left grunge stat: a dark torn/rough tab behind a HUGE condensed number
// (white->grey gradient text overflowing the tab top) with a small muted label.
// Tab grows from the left, number counts up; fades out near the end.
export const GrungeTab: React.FC<{
  value: number;
  prefix?: string;
  suffix?: string;
  compact?: boolean;
  label: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ value, prefix, suffix, compact, label, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const grow = interpolate(frame, [0, Math.round(fps * 0.35)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const outAt = durationInFrames - 12;
  const out = interpolate(frame, [outAt, outAt + 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = 1 - out;

  const n = countUp(frame, { to: value, delay: 4, dur: 26 });
  const display = fmtNum(n, { prefix, suffix, compact, decimals: 0 });

  // Irregular torn edge for the dark tab.
  const tornClip =
    "polygon(0% 6%, 3% 0%, 38% 3%, 70% 0%, 97% 2%, 100% 8%, 99% 94%, 96% 100%, 64% 97%, 30% 100%, 4% 98%, 0% 92%)";

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 80,
          bottom: 90,
          opacity,
          transform: `scaleX(${0.6 + 0.4 * grow})`,
          transformOrigin: "left bottom",
        }}
      >
        {/* Dark torn tab. */}
        <div
          style={{
            position: "relative",
            background: "rgba(20,34,47,0.88)",
            clipPath: tornClip,
            padding: "60px 40px 22px",
            minWidth: 360,
          }}
        >
          {/* HUGE number overflowing the tab top. */}
          <div
            style={{
              position: "absolute",
              left: 36,
              top: -42,
              fontFamily: theme.headerFont,
              fontWeight: 700,
              fontSize: 150,
              lineHeight: 1,
              letterSpacing: -1,
              backgroundImage: "linear-gradient(180deg, #FFFFFF 35%, #9AA0A6 100%)",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              WebkitTextFillColor: "transparent",
              color: "transparent",
              textShadow: "0 6px 18px rgba(0,0,0,0.5)",
              whiteSpace: "nowrap",
            }}
          >
            {display}
          </div>
          {/* Muted label. */}
          <div
            style={{
              fontFamily: theme.headerFont,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: 1.2,
              fontSize: 24,
              color: theme.textMute,
            }}
          >
            {label}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
