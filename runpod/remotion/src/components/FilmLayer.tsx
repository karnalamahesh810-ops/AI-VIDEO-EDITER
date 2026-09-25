import React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame } from "remotion";
import type { Treatment } from "../types";

/**
 * The look applied to a scene's footage.
 *
 * Sourced footage arrives from a hundred different cameras, decades and
 * upload qualities, so cutting it together raw reads as a scrapbook. A single
 * grade over the whole video is what makes a set of borrowed clips feel shot
 * for one film — and a heavier one is how a documentary signals "this part is
 * the past" without saying so.
 *
 * Grain is SVG turbulence rather than an asset: it costs no download, and
 * reseeding it per frame is what stops it looking like a static dirty lens.
 * `random()` is Remotion's deterministic PRNG, so two renders of the same
 * frame are identical — grain that differs between renders would defeat
 * caching and make any visual diff useless.
 *
 * This list is half a contract: it must match TREATMENTS in src/director.py,
 * and a test asserts they agree.
 */

export const cssFilterFor = (t: Treatment | undefined): string => {
  switch (t) {
    // Deliberately light. The first version stacked contrast, a brightness
    // cut and a heavy vignette, and real renders read as "low light" -
    // VidRush's own exports are clean, bright, full-colour footage.
    case "film":
      return "saturate(1.03)";
    case "vintage":
      return "sepia(0.22) saturate(0.92) brightness(1.04)";
    case "archival":
      return "grayscale(0.85) contrast(1.05) brightness(1.06)";
    default:
      return "none";
  }
};

const GRAIN_OPACITY: Record<string, number> = {
  film: 0.03,
  vintage: 0.06,
  archival: 0.09,
};

// Was 0.24 / 0.42 / 0.5 - the main reason footage looked dark.
const VIGNETTE: Record<string, number> = {
  film: 0,
  vintage: 0.14,
  archival: 0.18,
};

export const FilmLayer: React.FC<{ treatment?: Treatment }> = ({ treatment }) => {
  const frame = useCurrentFrame();
  if (!treatment || treatment === "none") return null;

  const grain = GRAIN_OPACITY[treatment] ?? 0;
  const vignette = VIGNETTE[treatment] ?? 0;
  // Reseed a few times a second: per-frame is noisier than real grain and
  // makes the encode work harder for no visible gain.
  const seed = Math.floor(frame / 2);
  const baseFrequency = 0.72 + random(`g${seed}`) * 0.1;

  // Archival gets an occasional bright flicker and a hair of gate weave, which
  // is what actually reads as projected film rather than a grey filter.
  const flicker =
    treatment === "archival"
      ? interpolate(random(`f${seed}`), [0, 1], [0.94, 1.06])
      : 1;
  const weave =
    treatment === "archival" ? interpolate(random(`w${seed}`), [0, 1], [-0.12, 0.12]) : 0;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", transform: `translateY(${weave}%)` }}>
      {vignette > 0 && (
        <AbsoluteFill
          style={{
            background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 46%, rgba(0,0,0,${vignette}) 100%)`,
          }}
        />
      )}

      {treatment === "vintage" && (
        <AbsoluteFill
          style={{
            background:
              "linear-gradient(115deg, rgba(255,196,110,0.10) 0%, rgba(255,150,60,0) 42%)",
            mixBlendMode: "screen",
          }}
        />
      )}

      {flicker !== 1 && (
        <AbsoluteFill
          style={{
            backgroundColor: "#fff",
            opacity: Math.max(0, (flicker - 1) * 0.5),
            mixBlendMode: "overlay",
          }}
        />
      )}

      {grain > 0 && (
        <AbsoluteFill style={{ opacity: grain, mixBlendMode: "overlay" }}>
          <svg width="100%" height="100%">
            <filter id={`grain-${seed}`}>
              <feTurbulence
                type="fractalNoise"
                baseFrequency={baseFrequency}
                numOctaves={2}
                seed={seed}
              />
            </filter>
            <rect width="100%" height="100%" filter={`url(#grain-${seed})`} />
          </svg>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
