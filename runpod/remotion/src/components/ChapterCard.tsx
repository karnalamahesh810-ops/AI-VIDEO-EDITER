import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { useOverlayAnim, useScale } from "./layout";
import { INTER } from "./fonts";
import { Rule, Words, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * Section break. A dark band wipes across from the left, a letter-spaced
 * kicker ("CHAPTER TWO") lands, the title rises word by word out of a blur,
 * and an accent rule draws under it; the band retracts at the end.
 *
 * Deliberately covers the caption zone: a chapter card is a beat of its own.
 */
export const ChapterCard: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, enter, opacity, durationInFrames, fps } = useOverlayAnim(20, 10);
  const s = useScale();
  const drift = useDrift(6);
  const open = interpolate(enter, [0, 1], [0, 88]);
  const close = interpolate(frame, [durationInFrames - 12, durationInFrames], [88, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const bandWidth = Math.min(open, close);
  const kicker = run(frame, fps * 0.25, fps * 0.4);
  const rule = run(frame, fps * 0.7, fps * 0.7);
  const words = (overlay.text || "").split(/\s+/).filter(Boolean).length;
  const size = words > 6 ? 80 : words > 3 ? 96 : 112;

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "flex-start" }}>
      <div style={{ position: "relative", width: `${bandWidth}%`, overflow: "hidden",
        background: "linear-gradient(90deg, rgba(8,8,11,0.94) 0%, rgba(10,10,14,0.86) 70%, rgba(10,10,14,0) 100%)",
        borderLeft: `${s(16)}px solid ${accent}`, padding: `${s(54)}px ${s(80)}px ${s(50)}px ${s(64)}px`,
        boxShadow: "0 30px 90px rgba(0,0,0,0.6)" }}>
        <div style={{ transform: drift }}>
          <div style={{ fontFamily: INTER, fontSize: s(30), fontWeight: 800, letterSpacing: "0.34em", textTransform: "uppercase",
            color: accent, opacity: kicker * opacity, marginBottom: s(18), whiteSpace: "nowrap",
            transform: `translateX(${(1 - kicker) * s(-30)}px)` }}>
            {overlay.subtitle || "Chapter"}
          </div>
          <div style={{ fontFamily: INTER, fontSize: s(size), fontWeight: 900, lineHeight: 1.06, color: "#fff",
            letterSpacing: "-0.025em", opacity, maxWidth: s(1200) }}>
            <Words text={overlay.text} at={Math.round(fps * 0.35)} step={4} rise={40} />
          </div>
          <Rule p={rule} width={s(320)} height={s(6)} color={accent} style={{ marginTop: s(28), opacity }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
