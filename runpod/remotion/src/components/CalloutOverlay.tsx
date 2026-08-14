import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useOverlaySafeStyle, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * "Callout Overlay" — a pill that slides in from the edge to flag a fact or
 * figure while the narrator says it. Deliberately off-centre so it never fights
 * the caption track at the bottom.
 */
export const CalloutOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const enter = spring({ frame, fps, config: { damping: 200, mass: 0.6 }, durationInFrames: 14 });
  const x = interpolate(enter, [0, 1], [s(-80), 0]);
  const exit = interpolate(
    frame,
    [durationInFrames - 8, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // "12,000 people | displaced" -> big number, small label beneath
  const [head, ...rest] = overlay.text.split(/\s*\|\s*/);
  const label = rest.join(" ");

  return (
    <AbsoluteFill
      style={{
        ...safe,
        justifyContent: "center",
        alignItems: "flex-start",
        paddingLeft: "7%",
        opacity: enter * exit,
        transform: `translateX(${x}px)`,
      }}
    >
      <div
        style={{
          background: "rgba(10,10,12,0.82)",
          borderLeft: `${s(10)}px solid ${accent}`,
          borderRadius: s(14),
          padding: `${s(22)}px ${s(34)}px`,
          backdropFilter: "blur(8px)",
          boxShadow: "0 18px 50px rgba(0,0,0,0.55)",
          maxWidth: "46%",
        }}
      >
        <div
          style={{
            fontFamily: "Inter, system-ui, sans-serif",
            fontSize: s(72),
            fontWeight: 900,
            color: "#fff",
            lineHeight: 1.05,
            letterSpacing: "-0.02em",
          }}
        >
          {head}
        </div>
        {label ? (
          <div
            style={{
              fontFamily: "Inter, system-ui, sans-serif",
              fontSize: s(30),
              fontWeight: 600,
              color: accent,
              marginTop: s(6),
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            {label}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
