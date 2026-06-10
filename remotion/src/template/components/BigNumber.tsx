import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "../theme";
import { popIn, countUp, fmtNum } from "../anim";

// Huge hero numeral for a single dramatic stat. Black-weight, centered or top-left,
// optional count-up and label. Optional radial vignette ("scrim") for contrast over
// busy b-roll. Pops in, fades out.
export const BigNumber: React.FC<{
  value: number;
  prefix?: string;
  suffix?: string;
  compact?: boolean;
  decimals?: number;
  label?: string;
  align?: "center" | "tl";
  size?: number;
  countup?: boolean;
  scrim?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({
  value,
  prefix,
  suffix,
  compact = false,
  decimals = 0,
  label,
  align = "center",
  size = 220,
  countup = false,
  scrim = false,
  theme,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const shown = countup ? countUp(frame, { to: value, delay: 0, dur: 26 }) : value;
  const text = fmtNum(shown, { prefix, suffix, decimals, compact });

  const p = popIn(frame, fps, { delay: 0, from: 0.9, outAt, outDur: 10 });

  const isTL = align === "tl";
  const box: React.CSSProperties = isTL
    ? { top: "10%", left: "8%", alignItems: "flex-start", textAlign: "left" }
    : { inset: 0, justifyContent: "center", alignItems: "center", textAlign: "center" };

  const labelSize = Math.round(size * 0.3);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {scrim ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: p.opacity,
            background: isTL
              ? "radial-gradient(closest-side at 24% 22%, rgba(0,0,0,.6), rgba(0,0,0,0) 60%)"
              : "radial-gradient(closest-side at 50% 50%, rgba(0,0,0,.6), rgba(0,0,0,0) 62%)",
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          ...box,
          display: "flex",
          flexDirection: "column",
          opacity: p.opacity,
          transform: p.transform,
        }}
      >
        <div
          style={{
            fontFamily: theme.bodyFont,
            fontWeight: 800,
            fontSize: size,
            lineHeight: 0.95,
            color: theme.text,
            letterSpacing: -1,
            fontVariantNumeric: "tabular-nums",
            textShadow: "0 2px 18px rgba(0,0,0,.55), 0 8px 60px rgba(0,0,0,.4)",
          }}
        >
          {text}
        </div>
        {label ? (
          <div
            style={{
              fontFamily: theme.bodyFont,
              fontWeight: 600,
              fontSize: labelSize,
              color: theme.textMute,
              marginTop: Math.round(size * 0.06),
              letterSpacing: 0.5,
              textShadow: "0 2px 12px rgba(0,0,0,.5)",
            }}
          >
            {label}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
