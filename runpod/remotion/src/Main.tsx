import React from "react";
import { AbsoluteFill, Audio, Sequence } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { Captions } from "./components/Captions";
import { TitleOverlay } from "./components/TitleOverlay";
import type { TimelineProps } from "./types";

export const Main: React.FC<TimelineProps> = (props) => {
  const { scenes, overlays, audio, bgm, captions } = props;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Visual track — one clip per spoken clause */}
      {scenes.map((scene) => (
        <Sequence
          key={scene.id}
          from={scene.startFrame}
          durationInFrames={scene.durationInFrames}
        >
          <SceneClip scene={scene} />
        </Sequence>
      ))}

      {/* Caption track, burned in over everything */}
      {captions.enabled &&
        scenes.map((scene) => (
          <Sequence
            key={`cap-${scene.id}`}
            from={scene.startFrame}
            durationInFrames={scene.durationInFrames}
          >
            <Captions scene={scene} style={captions} />
          </Sequence>
        ))}

      {/* Overlay track */}
      {overlays.map((ov, i) => (
        <Sequence
          key={`ov-${i}`}
          from={ov.startFrame}
          durationInFrames={ov.durationInFrames}
        >
          <TitleOverlay overlay={ov} accent={captions.accent} />
        </Sequence>
      ))}

      {/* Audio: narration drives the whole timeline; bgm sits well under it */}
      {audio.url ? <Audio src={audio.url} volume={audio.volume ?? 1} /> : null}
      {bgm?.url ? <Audio src={bgm.url} volume={bgm.volume ?? 0.12} loop /> : null}
    </AbsoluteFill>
  );
};
