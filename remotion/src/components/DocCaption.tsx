import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate } from "remotion";

// Clean documentary caption: white bold, subtle dark plate + shadow, bottom-center,
// fades in/out with the spoken sentence.
export const DocCaption: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const op = interpolate(
    frame,
    [0, 6, durationInFrames - 6, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return (
    <div
      style={{
        position: "absolute",
        bottom: "7.5%",
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        padding: "0 9%",
        opacity: op,
      }}
    >
      <div
        style={{
          fontFamily: "Arial, Helvetica, sans-serif",
          fontWeight: 700,
          fontSize: 44,
          lineHeight: 1.25,
          color: "#ffffff",
          textAlign: "center",
          textShadow: "0 2px 10px rgba(0,0,0,0.95)",
          background: "rgba(0,0,0,0.34)",
          padding: "10px 24px",
          borderRadius: 12,
          maxWidth: "92%",
        }}
      >
        {text}
      </div>
    </div>
  );
};
