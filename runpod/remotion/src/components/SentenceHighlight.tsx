import React from "react";
import { AbsoluteFill } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useOverlaySafeStyle, useScale } from "./layout";
import { NARROW, SERIF_ITALIC } from "./fonts";
import { Rule, Words, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * "Sentence Highlight": the thesis of a passage, bottom left, rising out of a
 * blur word by word; the words that carry it (`overlay.highlight`, comma or
 * space separated) get an accent box that wipes open a beat after they land,
 * set in italic serif. A vertical accent bar grows beside the block.
 */
function norm(w: string): string {
  return w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
}

export const SentenceHighlight: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, opacity, fps } = useOverlayAnim(10, 10);
  const s = useScale();
  const safe = useOverlaySafeStyle();
  const drift = useDrift(6);
  const text = overlay.text || "";
  const marked = new Set((overlay.highlight || "").split(/[\s,]+/).map(norm).filter(Boolean));
  const bar = run(frame, 0, fps * 0.5);
  const words = text.split(/\s+/).filter(Boolean).length;
  const step = Math.max(2, Math.min(4, Math.round((fps * 1.4) / Math.max(1, words))));
  const size = words > 16 ? 56 : words > 10 ? 64 : 74;

  return (
    <AbsoluteFill style={{ ...safe, justifyContent: "flex-end", opacity,
      background: "linear-gradient(to top, rgba(0,0,0,.55) 0%, rgba(0,0,0,.25) 30%, rgba(0,0,0,0) 60%)" }}>
      <div style={{ display: "flex", alignItems: "stretch", gap: s(28), margin: `0 0 ${s(90)}px ${s(80)}px`,
        maxWidth: "62%", transform: drift }}>
        <div style={{ width: s(10), background: accent, transform: `scaleY(${bar})`, transformOrigin: "bottom",
          borderRadius: s(4), flexShrink: 0 }} />
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(size), lineHeight: 1.32, color: "#fff",
          textShadow: TEXT_SHADOW, textTransform: "none" }}>
          <Words text={text} at={Math.round(fps * 0.15)} step={step} mark={marked} accent={accent}
            markStyle={{ fontFamily: SERIF_ITALIC, fontStyle: "italic", fontWeight: 700, padding: "0 0.16em", color: "#fff" }} />
          <Rule p={run(frame, fps * 0.3 + words * step, fps * 0.5)} width="28%" height={s(4)} color="rgba(255,255,255,.7)"
            style={{ marginTop: s(18) }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
