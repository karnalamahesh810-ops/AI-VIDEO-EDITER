import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { fadeRange, useOverlaySafeStyle, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * "Minimal Type Writer Title Overlay" — characters reveal on a steady cadence
 * with a blinking caret. Used for chapter/section beats.
 */
export const TypewriterTitle: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const text = overlay.text || "";
  // A fixed, fast type-in (~0.8s) rather than 60% of the overlay's own
  // duration - at a fraction, a card that ended up spanning into a later
  // cut was still typing after the beat that triggered it had already been
  // narrated past.
  const typeFrames = Math.min(24, Math.max(1, durationInFrames - 10));
  const shown = Math.floor(
    interpolate(frame, [0, typeFrames], [0, text.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );

  const caretOn = Math.floor(frame / Math.max(1, Math.round(fps * 0.4))) % 2 === 0;
  const done = shown >= text.length;

  const fade = interpolate(
    frame,
    fadeRange(durationInFrames, 8),
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{ ...safe, justifyContent: "center", alignItems: "center", opacity: fade }}
    >
      <div
        style={{
          fontFamily: "'DejaVu Sans Mono', ui-monospace, monospace",
          fontSize: s(64),
          fontWeight: 700,
          color: "#fff",
          letterSpacing: "-0.01em",
          textShadow: "0 6px 26px rgba(0,0,0,0.9)",
          padding: "0 8%",
          textAlign: "center",
        }}
      >
        {text.slice(0, shown)}
        <span
          style={{
            color: accent,
            opacity: done && !caretOn ? 0 : caretOn ? 1 : 0.25,
          }}
        >
          |
        </span>
      </div>
    </AbsoluteFill>
  );
};
