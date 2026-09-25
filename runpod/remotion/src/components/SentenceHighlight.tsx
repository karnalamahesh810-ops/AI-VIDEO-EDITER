import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useOverlaySafeStyle, useScale } from "./layout";
import { NARROW, SERIF_ITALIC } from "./fonts";
import type { Overlay } from "../types";

/**
 * "Sentence Highlight Text Overlay" — VidRush's most-used text animation.
 *
 * The key sentence of a passage types in word by word, bottom left, and the
 * words that carry it ("America saw a REUNION. The record reveals a GOODBYE.")
 * sit in a red box in italic serif. `overlay.highlight` lists those words
 * (comma or space separated); matching ignores case and punctuation.
 */

function norm(w: string): string {
  return w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
}

export const SentenceHighlight: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, opacity, fps, durationInFrames } = useOverlayAnim(10, 10);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const words = (overlay.text || "").split(/\s+/).filter(Boolean);
  const marked = new Set(
    (overlay.highlight || "").split(/[\s,]+/).map(norm).filter(Boolean),
  );
  // A fixed, fast type-in (~0.5s) regardless of how long the card then holds
  // - it used to take half the card's OWN duration, which read fine when a
  // beat ran ~7s but left the text still assembling well after a ~3s beat's
  // narration had already moved on to the next line.
  const typeEnd = Math.max(1, Math.min(fps * 2, durationInFrames * .45));
  const shown = Math.ceil(
    interpolate(frame, [0, typeEnd], [0, words.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );

  return (
    <AbsoluteFill
      style={{
        ...safe,
        justifyContent: "flex-end",
        opacity,
        // Readability without dimming the footage: a soft shade only in the
        // lower-left where the text sits. A full-frame 36% scrim here made
        // every card read as "low light".
        background:
          "radial-gradient(ellipse at 18% 82%, rgba(0,0,0,.42) 0%, rgba(0,0,0,0) 55%)",
      }}
    >
      <div
        style={{
          margin: `0 0 ${s(110)}px ${s(76)}px`,
          maxWidth: "48%",
          fontFamily: NARROW,
          fontWeight: 700,
          fontSize: s(54),
          lineHeight: 1.45,
          color: "#fff",
          textShadow: TEXT_SHADOW,
        }}
      >
        {words.slice(0, shown).map((w, i) => {
          const hot = marked.has(norm(w));
          return (
            <span key={i} style={{ marginRight: "0.28em", display: "inline-block" }}>
              {hot ? (
                <span
                  style={{
                    background: accent || "#d62828",
                    fontFamily: SERIF_ITALIC,
                    fontStyle: "italic",
                    fontWeight: 700,
                    padding: "0 0.18em",
                    textShadow: "none",
                  }}
                >
                  {w}
                </span>
              ) : (
                w
              )}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
