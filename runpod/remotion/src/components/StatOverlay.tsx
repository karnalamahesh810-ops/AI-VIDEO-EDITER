import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import {
  PANEL_BG, PANEL_SHADOW, SANS, formatNumber,
  growth, useOverlayAnim, useOverlaySafeStyle, useScale,
} from "./layout";
import type { Overlay } from "../types";

/**
 * One number, counted up.
 *
 * The count-up runs over the first half of the clip so the final figure holds
 * on screen — a counter still spinning when the cut arrives leaves the viewer
 * with no number at all. The value itself is copied from the narration by the
 * director and validated as finite before it reaches here.
 */
export const StatOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(18, 10);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const target = Number.isFinite(overlay.value as number) ? (overlay.value as number) : 0;
  const shown = target * growth(frame, Math.floor(durationInFrames * 0.5));

  return (
    <AbsoluteFill
      style={{
        ...safe,
        justifyContent: "center",
        alignItems: "center",
        opacity,
        transform: `scale(${interpolate(enter, [0, 1], [0.92, 1])})`,
      }}
    >
      <div
        style={{
          background: PANEL_BG,
          borderRadius: s(22),
          borderTop: `${s(8)}px solid ${accent}`,
          padding: `${s(36)}px ${s(64)}px`,
          textAlign: "center",
          boxShadow: PANEL_SHADOW,
          backdropFilter: "blur(10px)",
        }}
      >
        <div
          style={{
            fontFamily: SANS,
            fontSize: s(150),
            fontWeight: 900,
            lineHeight: 1,
            color: "#fff",
            letterSpacing: "-0.035em",
            // Tabular figures stop the box jittering as digits change width.
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {formatNumber(shown)}
          {overlay.suffix ? (
            <span style={{ color: accent, fontSize: s(80) }}>{overlay.suffix}</span>
          ) : null}
        </div>
        {overlay.text ? (
          <div
            style={{
              fontFamily: SANS,
              fontSize: s(34),
              fontWeight: 600,
              color: "rgba(255,255,255,0.86)",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              marginTop: s(14),
            }}
          >
            {overlay.text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
