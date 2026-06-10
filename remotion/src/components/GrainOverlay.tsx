import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";

// Film dust/grain + light-leak overlay (OVERLAY.mp4) blended via `screen`, so only the
// bright specks/streaks show over the footage. Loops across the whole timeline.
// opacity is tunable; keep it subtle (~0.15-0.28).
export const GrainOverlay: React.FC<{ opacity?: number; src?: string }> = ({
  opacity = 0.2,
  src = "fx/grain.mp4",
}) => {
  return (
    <AbsoluteFill style={{ mixBlendMode: "screen", opacity, pointerEvents: "none" }}>
      <OffthreadVideo
        src={staticFile(src)}
        muted
        loop
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
};
