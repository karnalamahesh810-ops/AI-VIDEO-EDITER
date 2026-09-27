import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { fadeRange, useOverlaySafeStyle, useScale } from "./layout";
import { INTER, NARROW, SERIF_ITALIC } from "./fonts";
import { Rule, Shade, Words, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * Kinetic title (the "typewriter" slot in the registry, no longer typed):
 * a letter-spaced kicker lands, the line rises out of a blur word by word in
 * condensed display caps, an accent rule draws under it, and the block keeps
 * a slow drift while it holds. A question (text ending in "?") is set in
 * italic serif with an accent question mark.
 */
export const TypewriterTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const s = useScale();
  const safe = useOverlaySafeStyle();
  const drift = useDrift(8);

  const text = overlay.text || "";
  const question = /\?\s*$/.test(text);
  const body = question ? text.replace(/\?\s*$/, "") : text;
  const words = body.split(/\s+/).filter(Boolean).length;
  const size = question ? (words > 10 ? 64 : 80) : words > 12 ? 72 : words > 6 ? 92 : 116;
  const shade = run(frame, 0, fps * 0.4);
  const kicker = run(frame, fps * 0.1, fps * 0.4);
  const rule = run(frame, fps * 0.35 + words * 3, fps * 0.7);
  const fade = interpolate(frame, fadeRange(durationInFrames, 8), [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ ...safe, justifyContent: "center", alignItems: "center", opacity: fade }}>
      <Shade p={shade} strength={0.5} />
      <div style={{ maxWidth: "84%", transform: drift, display: "flex", alignItems: "stretch", gap: s(34) }}>
        <div style={{ width: s(12), background: accent, transform: `scaleY(${kicker})`, transformOrigin: "top", borderRadius: s(4), flexShrink: 0 }} />
        <div>
          {question || overlay.subtitle ? (
            <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: s(28), letterSpacing: "0.34em",
              textTransform: "uppercase", color: accent, marginBottom: s(18), opacity: kicker,
              transform: `translateX(${(1 - kicker) * s(-20)}px)` }}>
              {overlay.subtitle || "The question"}
            </div>
          ) : null}
          <div style={{ fontFamily: question ? SERIF_ITALIC : NARROW, fontStyle: question ? "italic" : "normal",
            fontWeight: 700, fontSize: s(size), lineHeight: question ? 1.22 : 1.06, color: "#fff",
            textTransform: question ? "none" : "uppercase", letterSpacing: question ? "0.01em" : "0.02em",
            textShadow: "0 8px 30px rgba(0,0,0,0.85)" }}>
            <Words text={body} at={Math.round(fps * 0.2)} step={3} rise={44} />
            {question ? (
              <span style={{ color: accent, opacity: run(frame, fps * 0.2 + words * 3, fps * 0.3), display: "inline-block",
                transform: `scale(${0.6 + 0.4 * run(frame, fps * 0.2 + words * 3, fps * 0.3)})` }}>?</span>
            ) : null}
          </div>
          <Rule p={rule} width={s(300)} height={s(6)} color={accent} style={{ marginTop: s(26) }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
