import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useScale } from "./layout";
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
  const { frame, opacity, durationInFrames } = useOverlayAnim(10, 10);
  const s = useScale();

  const words = (overlay.text || "").split(/\s+/).filter(Boolean);
  const marked = new Set(
    (overlay.highlight || "").split(/[\s,]+/).map(norm).filter(Boolean),
  );
  // Type across the first half, then hold the finished line.
  const typeEnd = Math.max(1, Math.floor(durationInFrames * 0.5));
  const shown = Math.ceil(
    interpolate(frame, [0, typeEnd], [0, words.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", opacity }}>
      <div
        style={{
          margin: `0 0 ${s(250)}px ${s(110)}px`,
          maxWidth: "58%",
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
