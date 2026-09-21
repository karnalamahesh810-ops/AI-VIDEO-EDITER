import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { PANEL_BG, SANS, useOverlayAnim, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * Section break. A dark band wipes across the frame, the chapter title rides
 * in behind it, and the band retracts.
 *
 * Unlike every other template this one deliberately covers the caption zone:
 * a chapter card is a beat of its own, and the narration under it is the
 * sentence that names the section, which the card is already showing.
 */
export const ChapterCard: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(20, 10);
  const s = useScale();

  // The band wipes open, holds, then closes from the same edge.
  const open = interpolate(enter, [0, 1], [0, 100]);
  const close = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [100, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const bandWidth = Math.min(open, close);
  const textIn = interpolate(enter, [0.45, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "flex-start" }}>
      <div
        style={{
          position: "relative",
          width: `${bandWidth}%`,
          background: PANEL_BG,
          borderLeft: `${s(14)}px solid ${accent}`,
          padding: `${s(34)}px ${s(56)}px`,
          overflow: "hidden",
          boxShadow: "0 24px 70px rgba(0,0,0,0.6)",
        }}
      >
        <div
          style={{
            fontFamily: SANS,
            fontSize: s(30),
            fontWeight: 700,
            letterSpacing: "0.26em",
            textTransform: "uppercase",
            color: accent,
            opacity: textIn * opacity,
            marginBottom: s(12),
            whiteSpace: "nowrap",
          }}
        >
          {overlay.subtitle || "Chapter"}
        </div>
        <div
          style={{
            fontFamily: SANS,
            fontSize: s(82),
            fontWeight: 900,
            lineHeight: 1.05,
            color: "#fff",
            letterSpacing: "-0.02em",
            opacity: textIn * opacity,
            transform: `translateX(${interpolate(textIn, [0, 1], [s(-40), 0])}px)`,
            whiteSpace: "nowrap",
          }}
        >
          {overlay.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
