import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { PANEL_BG, PANEL_SHADOW, SANS, useOverlayAnim, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * Name strip — "Her name is / Daniela Largo", the character-introduction
 * treatment from the reference renders.
 *
 * This is the one overlay that lives low in the frame, so it sits just above
 * the caption safe zone rather than inside it: a lower third floating at the
 * vertical centre is not a lower third.
 */
export const LowerThird: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { enter, opacity } = useOverlayAnim(18, 10);
  const s = useScale();

  const slide = interpolate(enter, [0, 1], [-100, 0]);
  const barGrow = interpolate(enter, [0.3, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "flex-start",
        // Clear of the caption strip, which starts around 26% from the bottom.
        paddingBottom: "30%",
        paddingLeft: "7%",
        opacity,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "stretch",
          transform: `translateX(${slide}%)`,
          boxShadow: PANEL_SHADOW,
          borderRadius: s(10),
          overflow: "hidden",
        }}
      >
        <div style={{ width: s(10), background: accent, transform: `scaleY(${barGrow})` }} />
        <div style={{ background: PANEL_BG, padding: `${s(20)}px ${s(38)}px` }}>
          {overlay.subtitle ? (
            <div
              style={{
                fontFamily: SANS,
                fontSize: s(26),
                fontWeight: 700,
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: accent,
                marginBottom: s(6),
              }}
            >
              {overlay.subtitle}
            </div>
          ) : null}
          <div
            style={{
              fontFamily: SANS,
              fontSize: s(64),
              fontWeight: 900,
              lineHeight: 1.05,
              color: "#fff",
              letterSpacing: "-0.02em",
            }}
          >
            {overlay.text}
          </div>
          {overlay.label ? (
            <div
              style={{
                fontFamily: SANS,
                fontSize: s(28),
                fontWeight: 500,
                color: "rgba(255,255,255,0.75)",
                marginTop: s(8),
              }}
            >
              {overlay.label}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
