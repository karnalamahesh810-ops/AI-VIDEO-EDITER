import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useScale } from "./layout";
import { INTER, NARROW } from "./fonts";
import { Rule, Shade, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * Place/date markers, both typed in.
 *
 * Default ("tag"): VidRush's bottom-left stamp — an accent dash and
 * "Boston, July 27, 2004" — shown when footage first lands somewhere/somewhen.
 *
 * variant "title": the big spaced date card ("FEBRUARY 2" over "1961") laid
 * over a shaded frame at the start of a dated passage, with rules that draw
 * in from both sides.
 */

function typed(text: string, frame: number, end: number): string {
  const n = Math.floor(interpolate(frame, [0, Math.max(1, end)], [0, text.length],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  return text.slice(0, n);
}

export const DateStamp: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, opacity, durationInFrames, fps } = useOverlayAnim(8, 10);
  const s = useScale();
  const drift = useDrift(6);
  const red = accent || "#d62828";
  const text = overlay.text || "";

  if (overlay.variant === "title") {
    const rule = run(frame, fps * 0.3, fps * 0.8);
    return (
      <AbsoluteFill style={{ opacity, justifyContent: "center", alignItems: "center" }}>
        <Shade p={run(frame, 0, fps * 0.4)} strength={0.5} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", transform: drift }}>
          <div style={{ display: "flex", alignItems: "center", gap: s(30) }}>
            <Rule p={rule} width={s(220)} height={s(5)} color={red} style={{ transformOrigin: "right center" }} />
            <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(124), letterSpacing: "0.16em", color: "#fff",
              textShadow: TEXT_SHADOW, textTransform: "uppercase", lineHeight: 1 }}>
              {typed(text, frame, Math.min(durationInFrames * 0.35, fps * 1.2))}
            </div>
            <Rule p={rule} width={s(220)} height={s(5)} color={red} />
          </div>
          {overlay.subtitle ? (
            <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: s(38), letterSpacing: "0.5em", color: "rgba(255,255,255,0.85)",
              marginTop: s(22), textShadow: TEXT_SHADOW, textTransform: "uppercase" }}>
              {typed(overlay.subtitle, frame - durationInFrames * 0.25, durationInFrames * 0.2)}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    );
  }

  const p = run(frame, 0, fps * 0.4);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", opacity }}>
      <div style={{ display: "flex", alignItems: "center", gap: s(20), margin: `0 0 ${s(96)}px ${s(96)}px`,
        opacity: p, transform: `translateX(${(1 - p) * s(-30)}px)`, fontFamily: NARROW, fontWeight: 700, fontSize: s(52),
        letterSpacing: "0.04em", color: "#fff", textShadow: TEXT_SHADOW, textTransform: "uppercase" }}>
        <span style={{ width: s(54), height: s(6), background: red, display: "inline-block", boxShadow: `0 0 ${s(12)}px ${red}` }} />
        {typed(text, frame, Math.min(durationInFrames * 0.3, fps * 1.0))}
      </div>
    </AbsoluteFill>
  );
};
