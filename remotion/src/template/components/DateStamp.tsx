import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "../theme";
import { fadeRise, typewriter } from "../anim";

// Documentary date stamp. Bold day/month line over a smaller, dimmer year. No box.
// Corner-anchored with comfortable margins; optional typewriter reveal on the day.
export const DateStamp: React.FC<{
  day: string;
  year: string;
  pos?: "bl" | "tl" | "tc";
  typed?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ day, year, pos = "bl", typed = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const a = fadeRise(frame, { delay: 0, dur: 10, dist: 8, outAt, outDur: 10 });

  const tw = typewriter(frame, fps, day, { delay: 2, cps: 18, cursor: true });
  const dayText = typed ? tw.text : day;
  const showCursor = typed && tw.cursor;

  const anchor: React.CSSProperties = (() => {
    if (pos === "tl") return { top: "6%", left: "6%", textAlign: "left", alignItems: "flex-start" };
    if (pos === "tc")
      return { top: "6%", left: 0, right: 0, textAlign: "center", alignItems: "center" };
    // "bl"
    return { bottom: "6%", left: "6%", textAlign: "left", alignItems: "flex-start" };
  })();

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          display: "flex",
          flexDirection: "column",
          opacity: a.opacity,
          transform: a.transform,
          ...anchor,
        }}
      >
        <div
          style={{
            fontFamily: theme.bodyFont,
            fontWeight: 700,
            fontSize: 48,
            color: theme.text,
            lineHeight: 1.05,
            textShadow: "0 2px 18px rgba(0,0,0,.55)",
          }}
        >
          {dayText}
          {showCursor ? <span style={{ opacity: 0.85 }}>|</span> : null}
        </div>
        <div
          style={{
            fontFamily: theme.bodyFont,
            fontWeight: 500,
            fontSize: 24,
            color: theme.text,
            opacity: 0.8,
            marginTop: 4,
            letterSpacing: 0.5,
            textShadow: "0 2px 18px rgba(0,0,0,.55)",
          }}
        >
          {year}
        </div>
      </div>
    </AbsoluteFill>
  );
};
