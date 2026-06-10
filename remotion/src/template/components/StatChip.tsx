import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "../theme";
import { popIn, countUp, fmtNum } from "../anim";

// "Taped percentage": a big bold value framed by two slightly-rotated dark tape strips
// (above and below), with a small uppercase label underneath. Lower-center. The tape
// strips pop in from center; the number counts up.
export const StatChip: React.FC<{
  value: number;
  prefix?: string;
  suffix?: string;
  label?: string;
  countup?: boolean;
  compact?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ value, prefix, suffix, label, countup = false, compact = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const shown = countup ? countUp(frame, { to: value, delay: 4, dur: 26 }) : value;
  const text = fmtNum(shown, { prefix, suffix, compact });

  const tapeTop = popIn(frame, fps, { delay: 0, from: 0.2, outAt, outDur: 10 });
  const tapeBot = popIn(frame, fps, { delay: 3, from: 0.2, outAt, outDur: 10 });
  const num = popIn(frame, fps, { delay: 6, from: 0.85, outAt, outDur: 10 });

  const TAPE = "#14181c";

  // A rough dark tape strip. `rot` is the static skew; popIn supplies scale+opacity.
  const tape = (rot: number, anim: { opacity: number; transform: string }, w: number): React.CSSProperties => ({
    width: w,
    height: 26,
    background: TAPE,
    opacity: anim.opacity * 0.94,
    transform: `rotate(${rot}deg) ${anim.transform}`,
    borderRadius: 2,
    boxShadow: "0 6px 22px rgba(0,0,0,.45)",
  });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: "14%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        {/* top tape, slightly rotated -2deg */}
        <div style={tape(-2, tapeTop, 360)} />
        <div
          style={{
            opacity: num.opacity,
            transform: num.transform,
            fontFamily: theme.bodyFont,
            fontWeight: 800,
            fontSize: 132,
            lineHeight: 1,
            color: theme.text,
            letterSpacing: -1,
            margin: "10px 0",
            fontVariantNumeric: "tabular-nums",
            textShadow: "0 2px 18px rgba(0,0,0,.55), 0 6px 40px rgba(0,0,0,.45)",
          }}
        >
          {text}
        </div>
        {/* bottom tape, slightly rotated +1.5deg */}
        <div style={tape(1.5, tapeBot, 320)} />
        {label ? (
          <div
            style={{
              opacity: num.opacity,
              fontFamily: theme.bodyFont,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: 2,
              fontSize: 26,
              color: theme.textMute,
              marginTop: 16,
              textShadow: "0 2px 14px rgba(0,0,0,.55)",
            }}
          >
            {label}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
