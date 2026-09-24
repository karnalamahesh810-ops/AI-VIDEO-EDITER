import React from "react";
import {
  AbsoluteFill, Img, OffthreadVideo, interpolate,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import { FilmLayer, cssFilterFor } from "./FilmLayer";
import { EffectLayer, TransitionLayer, effectFilter, entranceStyle } from "./SceneEffects";
import type { Scene } from "../types";

/**
 * One visual for one spoken clause.
 *
 * Cuts are hard by default. The previous version faded every scene in from
 * black over six frames, so every cut dipped to black — which reads as a
 * slideshow, not an edit. Transitions now happen only where the timeline asks
 * for one (see SceneEffects), and every clip carries one effect so borrowed
 * footage still feels designed.
 */
export const SceneClip: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const { media, motion, treatment, transition, effect } = scene;

  const progress = durationInFrames > 1 ? frame / durationInFrames : 0;

  // Slow, steady drift. Overshooting scale keeps pans from exposing edges.
  let transform = "scale(1.06)";
  if (motion === "zoom-in" || effect === "ken-burns") {
    transform = `scale(${1.04 + progress * 0.1})`;
  } else if (motion === "zoom-out") {
    transform = `scale(${1.16 - progress * 0.1})`;
  } else if (motion === "pan-left") {
    transform = `scale(1.16) translateX(${interpolate(progress, [0, 1], [3, -3])}%)`;
  } else if (motion === "pan-right") {
    transform = `scale(1.16) translateX(${interpolate(progress, [0, 1], [-3, 3])}%)`;
  }

  if (media.type === "color" || !media.url) {
    // No clip and no image for this beat. Never a flat black hole: a subtle
    // dark gradient reads as a deliberately quiet background rather than a
    // broken frame, and lets a fallback text overlay (see
    // handler._fill_missing_media) actually sit on something.
    return (
      <AbsoluteFill
        style={{
          background: "radial-gradient(ellipse at 50% 40%, #1b1c22 0%, #0a0a0d 75%)",
        }}
      />
    );
  }

  const entrance = entranceStyle(transition, frame);
  const filters = [cssFilterFor(treatment), effectFilter(effect, frame), entrance.filter]
    .filter((f) => f && f !== "none")
    .join(" ");

  const fill: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform,
    filter: filters || undefined,
  };

  if (scene.frame === "inset") {
    // VidRush's framing for archival photos, documents and low-resolution or
    // 4:3 footage: the media keeps its own shape, inset with a shadow on a
    // grainy deep-green field, instead of being cropped or upscaled to fill
    // 16:9. It is what makes a 320x240 newsreel look intentional.
    const inset: React.CSSProperties = {
      maxWidth: "74%",
      maxHeight: "80%",
      width: "auto",
      height: "auto",
      boxShadow: "0 22px 60px rgba(0,0,0,0.6)",
      transform: `scale(${1 + progress * 0.05})`,
      filter: filters || undefined,
    };
    return (
      <AbsoluteFill
        style={{
          background: "radial-gradient(ellipse at 50% 45%, #145c46 0%, #0b3a2c 70%, #072a20 100%)",
          justifyContent: "center",
          alignItems: "center",
          overflow: "hidden",
        }}
      >
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: 0.22 }}>
          <filter id={`grain-${scene.id}`}>
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={frame % 7} />
          </filter>
          <rect width="100%" height="100%" filter={`url(#grain-${scene.id})`} />
        </svg>
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
            opacity: entrance.opacity ?? 1,
            transform: entrance.transform,
          }}
        >
          {media.type === "video" ? (
            <OffthreadVideo src={media.url} style={inset} muted />
          ) : (
            <Img src={media.url} style={inset} />
          )}
        </AbsoluteFill>
        <FilmLayer treatment={treatment} />
        <TransitionLayer transition={transition} />
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#000" }}>
      <AbsoluteFill
        style={{
          opacity: entrance.opacity ?? 1,
          transform: entrance.transform,
        }}
      >
        {media.type === "video" ? (
          <OffthreadVideo src={media.url} style={fill} muted />
        ) : (
          <Img src={media.url} style={fill} />
        )}
      </AbsoluteFill>
      <EffectLayer effect={effect} durationInFrames={durationInFrames} />
      <FilmLayer treatment={treatment} />
      <TransitionLayer transition={transition} />
    </AbsoluteFill>
  );
};
