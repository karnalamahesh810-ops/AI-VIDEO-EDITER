import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useOverlaySafeStyle, useScale } from "./layout";
import { INTER, SERIF, SERIF_ITALIC } from "./fonts";
import { Rule, Shade, Words, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * Pull quote. An oversized accent quotation mark lands first, the line rises
 * word by word in italic serif, then the attribution draws in under a rule.
 * `label` or `subtitle` is the speaker.
 */
export const QuoteOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, enter, opacity, fps } = useOverlayAnim(20, 12);
  const s = useScale();
  const safe = useOverlaySafeStyle();
  const drift = useDrift(8);
  const body = (overlay.text || "").replace(/^["“”']+|["“”']+$/g, "");
  const who = overlay.label || overlay.subtitle || "";
  const words = body.split(/\s+/).filter(Boolean).length;
  const size = words > 18 ? 56 : words > 10 ? 66 : 78;
  const attr = run(frame, fps * 0.4 + words * 3, fps * 0.5);

  return (
    <AbsoluteFill style={{ ...safe, justifyContent: "center", alignItems: "center", opacity }}>
      <Shade p={enter} strength={0.6} />
      <div style={{ maxWidth: "70%", position: "relative", transform: drift, padding: `0 ${s(40)}px` }}>
        <div style={{ position: "absolute", left: s(-30), top: s(-120), fontFamily: SERIF, fontSize: s(340), lineHeight: 1,
          color: accent, opacity: 0.9 * enter, transform: `scale(${interpolate(enter, [0, 1], [1.8, 1])})`,
          transformOrigin: "left top", textShadow: "0 10px 40px rgba(0,0,0,.6)" }}>“</div>
        <div style={{ position: "relative", fontFamily: SERIF_ITALIC, fontStyle: "italic", fontSize: s(size), lineHeight: 1.28,
          color: "#fff", textShadow: TEXT_SHADOW, paddingLeft: s(60) }}>
          <Words text={body} at={Math.round(fps * 0.25)} step={3} rise={34} />
        </div>
        {who ? (
          <div style={{ display: "flex", alignItems: "center", gap: s(18), marginTop: s(30), paddingLeft: s(60), opacity: attr }}>
            <Rule p={attr} width={s(90)} height={s(4)} color={accent} />
            <span style={{ fontFamily: INTER, fontSize: s(30), fontWeight: 700, letterSpacing: "0.18em",
              textTransform: "uppercase", color: "rgba(255,255,255,0.88)" }}>{who}</span>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
