import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import type { ChannelMarkDoc } from "../../types";
import { brandFont } from "./brandFonts";

/**
 * The channel's name as a faint watermark across the whole video (doc.channelMark, src/severe.py), the way
 * daily weather-news channels stamp their uploads: measured on Severe Weather USA (2026-10-26, the median of
 * 240 frames) - a condensed bold face, white at about a quarter opacity with a soft shadow, centred on the
 * frame, its letters ~5.6% of the frame's height and the line ~35% of its width. Drawn over the footage and
 * the graphics, under the captions; no motion (a stamp, not a look).
 */
export const ChannelMark: React.FC<{ mark: ChannelMarkDoc }> = ({ mark }) => {
  const { width, height } = useVideoConfig();
  const text = String(mark.text || "").trim().slice(0, 40);
  if (!text) return null;
  const size = Math.max(0.03, Math.min(0.1, Number(mark.size) || 0.075)) * height;
  const opacity = Math.max(0.1, Math.min(0.6, Number(mark.opacity) || 0.28));
  const x = Math.max(0.1, Math.min(0.9, Number(mark.x ?? 0.5)));
  const y = Math.max(0.1, Math.min(0.9, Number(mark.y ?? 0.5)));
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{
        position: "absolute", left: x * width, top: y * height, transform: "translate(-50%, -50%)",
        whiteSpace: "nowrap", font: `700 ${Math.round(size)}px ${brandFont(mark.font || "Oswald")}`,
        letterSpacing: Math.round(size * 0.01), color: `rgba(255,255,255,${opacity})`,
        textShadow: `0 ${Math.round(size * 0.03)}px ${Math.round(size * 0.08)}px rgba(0,0,0,${opacity * 0.6})`,
      }}>{text}</div>
    </AbsoluteFill>
  );
};
