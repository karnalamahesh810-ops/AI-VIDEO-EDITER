import React from "react";
import { AbsoluteFill, random, useCurrentFrame } from "remotion";
import type { TimelineProps } from "../types";

/**
 * One film look over the whole picture track (doc.look): a light grain and a
 * soft vignette, drawn once above every scene and transition and below the
 * graphics and captions (Main.tsx). The AI presenter style uses it, when the
 * job asks for it, so a lip-synced presenter, image-to-video clips and stills
 * from three different models read as one camera.
 *
 * The grain is SVG turbulence reseeded every second frame (per frame is
 * noisier than real grain and makes the encode work harder), seeded by the
 * frame number through Remotion's deterministic random(): two renders of a
 * frame - two chunks of a split render - draw identical grain. No pictures:
 * nothing here can hold up a render.
 */
const clamp01 = (v: unknown, hi: number): number => {
  const n = typeof v === "number" && Number.isFinite(v) ? v : 0;
  return Math.max(0, Math.min(hi, n));
};

export const FilmLook: React.FC<{ look: TimelineProps["look"] }> = ({ look }) => {
  const frame = useCurrentFrame();
  if (!look || typeof look !== "object") return null;
  const grain = clamp01(look.grain, 0.2);
  const vignette = clamp01(look.vignette, 0.5);
  if (!grain && !vignette) return null;
  const seed = Math.floor(frame / 2);
  const freq = 0.74 + random(`look-grain-${seed}`) * 0.08;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {vignette > 0 ? (
        <AbsoluteFill style={{
          background: `radial-gradient(ellipse at 50% 48%, rgba(0,0,0,0) 52%, rgba(0,0,0,${vignette.toFixed(3)}) 100%)`,
        }} />
      ) : null}
      {grain > 0 ? (
        <AbsoluteFill style={{ opacity: grain, mixBlendMode: "overlay" }}>
          <svg width="100%" height="100%">
            <filter id={`look-grain-${seed}`}>
              <feTurbulence type="fractalNoise" baseFrequency={freq} numOctaves={2} seed={seed} />
            </filter>
            <rect width="100%" height="100%" filter={`url(#look-grain-${seed})`} />
          </svg>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};
