import React from "react";
import { Composition } from "remotion";
import { Main } from "./Main";
import type { TimelineProps } from "./types";

const fallback: TimelineProps = {
  fps: 30,
  width: 1920,
  height: 1080,
  durationInFrames: 300,
  audio: { url: "", volume: 1 },
  bgm: null,
  captions: { enabled: true, position: "bottom", accent: "#FFD400", fontFamily: "Inter" },
  scenes: [],
  overlays: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Main"
      component={Main}
      durationInFrames={fallback.durationInFrames}
      fps={fallback.fps}
      width={fallback.width}
      height={fallback.height}
      defaultProps={fallback}
      // Dimensions and length come from the props document the worker writes,
      // so one composition serves every video length and aspect ratio.
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, props.durationInFrames),
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
  );
};
