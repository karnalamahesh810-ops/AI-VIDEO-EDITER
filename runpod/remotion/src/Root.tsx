import React from "react";
import { Composition } from "remotion";
import { Main } from "./Main";
import { FootprintSheet, type FootprintSheetProps } from "./FootprintSheet";
import { brandFrames } from "./components/brand/brandLayout";
import type { TimelineProps } from "./types";

const sheet: FootprintSheetProps = { looks: [], samples: 4, scenes: [], accent: "#FFD400" };

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
    <>
    <Composition
      id="Main"
      component={Main}
      durationInFrames={fallback.durationInFrames}
      fps={fallback.fps}
      width={fallback.width}
      height={fallback.height}
      defaultProps={fallback}
      // Dimensions and length come from the props document the worker writes,
      // so one composition serves every video length and aspect ratio. A
      // brand kit's intro and outro play around the narration's timeline.
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, brandFrames(props).total),
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
    {/* Not a video: every look on a transparent frame, measured for the subtitles to keep clear of
        (scripts/build_caption_footprints.py -> data/caption_footprints.json). It runs a look's length
        past its last sample (never drawn: the script renders only the sampled frames), because a
        Sequence is cut at the composition's end - the last looks would otherwise be measured mid-exit,
        fading, and a short --only run would measure every look that way. */}
    <Composition
      id="CaptionFootprints"
      component={FootprintSheet}
      durationInFrames={1}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={sheet}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, props.looks.length * props.samples
          + Math.max(0, ...props.looks.map((l) => l.overlay.durationInFrames || 0))),
      })}
    />
    </>
  );
};
