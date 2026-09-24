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
    return <AbsoluteFill style={{ backgroundColor: "#0b0b0d" }} />;
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
