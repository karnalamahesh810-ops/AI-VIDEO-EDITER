import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useScale } from "./layout";
import { NARROW } from "./fonts";
import type { Overlay } from "../types";

/**
 * Place/date markers, both typed in.
 *
 * Default ("tag"): VidRush's small bottom-left stamp — a red dash and
 * "Boston, July 27, 2004" — shown when footage first lands somewhere/somewhen.
 *
 * variant "title": the big spaced date card ("FEBRUARY 2" over "1961") laid
 * over desaturated footage at the start of a dated passage.
 */

function typed(text: string, frame: number, end: number): string {
  const n = Math.floor(
    interpolate(frame, [0, Math.max(1, end)], [0, text.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  return text.slice(0, n);
}

export const DateStamp: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, opacity, durationInFrames } = useOverlayAnim(8, 10);
  const s = useScale();
  const red = accent || "#d62828";
  const text = overlay.text || "";

  if (overlay.variant === "title") {
    return (
      <AbsoluteFill
        style={{
          opacity,
          justifyContent: "center",
          alignItems: "center",
          background: "rgba(0,0,0,0.25)",
        }}
      >
        <div
          style={{
            fontFamily: NARROW,
            fontWeight: 700,
            fontSize: s(96),
            letterSpacing: "0.14em",
            color: "#fff",
            textShadow: TEXT_SHADOW,
            textTransform: "uppercase",
          }}
        >
          {typed(text, frame, durationInFrames * 0.35)}
        </div>
        {overlay.subtitle ? (
          <div
            style={{
              fontFamily: NARROW,
              fontSize: s(34),
              letterSpacing: "0.5em",
              color: "rgba(255,255,255,0.8)",
              marginTop: s(8),
              textShadow: TEXT_SHADOW,
            }}
          >
            {typed(overlay.subtitle, frame - durationInFrames * 0.25, durationInFrames * 0.2)}
          </div>
        ) : null}
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", opacity }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: s(14),
          margin: `0 0 ${s(96)}px ${s(80)}px`,
          fontFamily: NARROW,
          fontWeight: 700,
          fontSize: s(36),
          color: "#fff",
          textShadow: TEXT_SHADOW,
        }}
      >
        <span style={{ width: s(34), height: s(4), background: red, display: "inline-block" }} />
        {typed(text, frame, durationInFrames * 0.3)}
      </div>
    </AbsoluteFill>
  );
};
