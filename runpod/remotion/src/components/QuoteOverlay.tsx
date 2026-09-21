import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { SANS, TEXT_SHADOW, useOverlayAnim, useOverlaySafeStyle, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * Pull quote. A large opening mark, the line itself, and an attribution rule.
 *
 * The quotation mark scales in from oversized rather than fading, which reads
 * as "someone is being quoted" before the viewer has read a word.
 */
export const QuoteOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { enter, opacity } = useOverlayAnim(20, 12);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  // Strip any quote marks already in the text; the graphic supplies its own.
  const body = overlay.text.replace(/^["“”']+|["“”']+$/g, "");

  return (
    <AbsoluteFill
      style={{ ...safe, justifyContent: "center", alignItems: "center", opacity }}
    >
      <div style={{ maxWidth: "72%", padding: `0 ${s(40)}px`, textAlign: "center" }}>
        <div
          style={{
            fontFamily: "Georgia, 'Times New Roman', serif",
            fontSize: s(150),
            lineHeight: 0.6,
            color: accent,
            opacity: 0.85,
            transform: `scale(${interpolate(enter, [0, 1], [2.2, 1])})`,
            marginBottom: s(18),
          }}
        >
          “
        </div>
        <div
          style={{
            fontFamily: "Georgia, 'Times New Roman', serif",
            fontStyle: "italic",
            fontSize: s(58),
            fontWeight: 500,
            lineHeight: 1.3,
            color: "#fff",
            textShadow: TEXT_SHADOW,
            transform: `translateY(${interpolate(enter, [0, 1], [s(24), 0])}px)`,
          }}
        >
          {body}
        </div>
        {overlay.subtitle ? (
          <div
            style={{
              marginTop: s(26),
              display: "inline-flex",
              alignItems: "center",
              gap: s(14),
            }}
          >
            <span style={{ width: s(54), height: s(3), background: accent }} />
            <span
              style={{
                fontFamily: SANS,
                fontSize: s(28),
                fontWeight: 700,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: "rgba(255,255,255,0.82)",
              }}
            >
              {overlay.subtitle}
            </span>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
