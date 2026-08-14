import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { useOverlaySafeStyle, useScale } from "./layout";
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
  // Finish typing by ~60% of the overlay so the finished line can breathe.
  const typeFrames = Math.max(1, Math.floor(durationInFrames * 0.6));
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
    [0, 5, durationInFrames - 8, durationInFrames],
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
