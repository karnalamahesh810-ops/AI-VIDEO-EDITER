import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useOverlaySafeStyle, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * The "Multi Font Title Overlay" look from the reference renders: a stacked
 * headline where the payload line is accent-coloured and larger, springing in
 * from below and settling.
 */
export const TitleOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });
  const y = interpolate(enter, [0, 1], [s(60), 0]);
  const exit = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // First line is the setup, remainder is the payload.
  const parts = overlay.text.split(/\s*[:|]\s*/);
  const lead = parts.length > 1 ? parts[0] : "";
  const punch = parts.length > 1 ? parts.slice(1).join(" ") : overlay.text;

  return (
    <AbsoluteFill
      style={{
        ...safe,
        justifyContent: "center",
        alignItems: "center",
        opacity: enter * exit,
        transform: `translateY(${y}px)`,
      }}
    >
      <div style={{ textAlign: "center", padding: "0 6%" }}>
        {lead ? (
          <div
            style={{
              fontFamily: "Inter, system-ui, sans-serif",
              fontSize: s(46),
              fontWeight: 600,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "#fff",
              opacity: 0.9,
              marginBottom: s(10),
              textShadow: "0 4px 20px rgba(0,0,0,0.9)",
            }}
          >
            {lead}
          </div>
        ) : null}
        <div
          style={{
            fontFamily: "Inter, system-ui, sans-serif",
            fontSize: s(108),
            fontWeight: 900,
            lineHeight: 1.02,
            color: accent,
            textShadow: "0 6px 28px rgba(0,0,0,0.92)",
            letterSpacing: "-0.02em",
          }}
        >
          {punch}
        </div>
      </div>
    </AbsoluteFill>
  );
};
