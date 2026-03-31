import React from "react";
import { Composition } from "remotion";
import { USAMapComposition } from "./compositions/USAMapComposition";
import { TOTAL_FRAMES, FPS } from "./data/topStates";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="USAMapAnimation"
        component={USAMapComposition}
        durationInFrames={TOTAL_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{}}
      />
    </>
  );
};
