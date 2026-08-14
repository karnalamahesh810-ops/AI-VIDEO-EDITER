import React from "react";
import {
  AbsoluteFill, Img, OffthreadVideo, interpolate,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import type { Scene } from "../types";

/**
 * One visual for one spoken clause.
 *
 * Stills get Ken Burns so they never feel frozen; video plays straight because
 * the footage supplies its own motion. Both fade in briefly at the cut.
 */
export const SceneClip: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const { media, motion } = scene;

  const FADE = 6;
  const opacity = interpolate(
    frame,
    [0, FADE, Math.max(FADE + 1, durationInFrames - FADE), durationInFrames],
    [0, 1, 1, scene.transition === "fade" ? 0 : 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const progress = durationInFrames > 1 ? frame / durationInFrames : 0;

  // Slow, steady drift. Overshooting scale keeps pans from exposing edges.
  let transform = "scale(1.06)";
  if (motion === "zoom-in") {
    transform = `scale(${1.04 + progress * 0.1})`;
  } else if (motion === "zoom-out") {
    transform = `scale(${1.16 - progress * 0.1})`;
  } else if (motion === "pan-left") {
    transform = `scale(1.16) translateX(${interpolate(progress, [0, 1], [3, -3])}%)`;
  } else if (motion === "pan-right") {
    transform = `scale(1.16) translateX(${interpolate(progress, [0, 1], [-3, 3])}%)`;
  }

  if (media.type === "color" || !media.url) {
    return <AbsoluteFill style={{ backgroundColor: "#0b0b0d", opacity }} />;
  }

  const fill: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform,
  };

  return (
    <AbsoluteFill style={{ opacity, overflow: "hidden", backgroundColor: "#000" }}>
      {media.type === "video" ? (
        <OffthreadVideo src={media.url} style={fill} muted />
      ) : (
        <Img src={media.url} style={fill} />
      )}
    </AbsoluteFill>
  );
};
