import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { useOverlayAnim, useScale } from "./layout";
import { INTER, NARROW } from "./fonts";
import { run } from "./kinetic";
import type { Overlay } from "../types";

/**
 * Broadcast name strip, low left. The plate wipes open from its accent bar,
 * the name lands in condensed caps, the role slides in under it, and a light
 * sweep crosses the plate once as it settles.
 */
export const LowerThird: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, opacity, fps } = useOverlayAnim(18, 10);
  const s = useScale();
  const bar = run(frame, 0, fps * 0.35);
  const wipe = run(frame, fps * 0.12, fps * 0.55);
  const name = run(frame, fps * 0.3, fps * 0.5);
  const role = run(frame, fps * 0.5, fps * 0.5);
  const sweep = interpolate(frame, [fps * 0.6, fps * 1.5], [-40, 140], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const big = (overlay.text || "").length > 22 ? 58 : 74;

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "flex-start", paddingBottom: "29%", paddingLeft: "6%", opacity }}>
      <div style={{ display: "flex", alignItems: "stretch", filter: "drop-shadow(0 22px 50px rgba(0,0,0,0.6))" }}>
        <div style={{ width: s(14), background: accent, transform: `scaleY(${bar})`, transformOrigin: "bottom",
          borderRadius: `${s(6)}px 0 0 ${s(6)}px` }} />
        <div style={{ position: "relative", overflow: "hidden", clipPath: `inset(0 ${(1 - wipe) * 100}% 0 0)`,
          background: "linear-gradient(90deg, rgba(10,10,13,0.92) 0%, rgba(14,14,18,0.78) 100%)",
          backdropFilter: "blur(12px)", padding: `${s(22)}px ${s(56)}px ${s(24)}px ${s(40)}px`,
          borderRadius: `0 ${s(14)}px ${s(14)}px 0`, border: "1px solid rgba(255,255,255,0.08)", borderLeft: "none" }}>
          <div style={{ position: "absolute", top: 0, bottom: 0, left: `${sweep}%`, width: "18%",
            background: "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.14) 50%, rgba(255,255,255,0) 100%)",
            transform: "skewX(-18deg)", pointerEvents: "none" }} />
          {overlay.subtitle ? (
            <div style={{ fontFamily: INTER, fontSize: s(24), fontWeight: 700, letterSpacing: "0.26em", textTransform: "uppercase",
              color: accent, marginBottom: s(8), opacity: role, transform: `translateX(${(1 - role) * s(-24)}px)` }}>
              {overlay.subtitle}
            </div>
          ) : null}
          <div style={{ fontFamily: NARROW, fontSize: s(big), fontWeight: 700, lineHeight: 1.02, color: "#fff",
            letterSpacing: "0.02em", textTransform: "uppercase", opacity: name,
            transform: `translateY(${(1 - name) * s(18)}px)`, filter: name < 1 ? `blur(${(1 - name) * 8}px)` : undefined }}>
            {overlay.text}
          </div>
          {overlay.label ? (
            <div style={{ fontFamily: INTER, fontSize: s(28), fontWeight: 500, color: "rgba(255,255,255,0.8)", marginTop: s(8),
              opacity: role, transform: `translateX(${(1 - role) * s(-24)}px)` }}>
              {overlay.label}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
