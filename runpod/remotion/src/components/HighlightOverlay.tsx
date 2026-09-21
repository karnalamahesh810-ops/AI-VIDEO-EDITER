import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { SANS, growth, useOverlayAnim, useOverlaySafeStyle, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * A line of text with a marker sweeping across it, as if highlighted by hand.
 *
 * The sweep is a background layer behind the words rather than a semi-opaque
 * box in front: drawn in front, accent-coloured text over accent-coloured
 * marker becomes unreadable exactly as the sweep passes each word.
 */
export const HighlightOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(14, 10);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  // Start the sweep once the text has settled, finish by two-thirds through.
  const sweep = growth(frame - 8, Math.floor(durationInFrames * 0.45));

  return (
    <AbsoluteFill
      style={{ ...safe, justifyContent: "center", alignItems: "center", opacity }}
    >
      <div
        style={{
          position: "relative",
          maxWidth: "74%",
          padding: `${s(14)}px ${s(26)}px`,
          transform: `translateY(${interpolate(enter, [0, 1], [s(28), 0])}px)`,
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            top: s(10),
            bottom: s(10),
            width: `${sweep * 100}%`,
            background: accent,
            opacity: 0.9,
            borderRadius: s(6),
            // Slight skew keeps it feeling drawn rather than boxed.
            transform: "skewX(-3deg)",
          }}
        />
        <div
          style={{
            position: "relative",
            fontFamily: SANS,
            fontSize: s(56),
            fontWeight: 900,
            lineHeight: 1.22,
            textAlign: "center",
            letterSpacing: "-0.015em",
            // Flip to dark once the marker is mostly behind the words.
            color: sweep > 0.55 ? "#0a0a0c" : "#fff",
            textShadow: sweep > 0.55 ? "none" : "0 4px 18px rgba(0,0,0,0.85)",
          }}
        >
          {overlay.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
