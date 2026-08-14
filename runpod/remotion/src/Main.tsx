import React from "react";
import { AbsoluteFill, Audio, Sequence } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { Captions } from "./components/Captions";
import { TitleOverlay } from "./components/TitleOverlay";
import { CalloutOverlay } from "./components/CalloutOverlay";
import { TypewriterTitle } from "./components/TypewriterTitle";
import { SplitScreen } from "./components/SplitScreen";
import type { Overlay, TimelineProps } from "./types";

/** Route an overlay to its effect. Unknown types fall back to the title card. */
const renderOverlay = (ov: Overlay, accent: string) => {
  switch (ov.type) {
    case "callout":
      return <CalloutOverlay overlay={ov} accent={accent} />;
    case "typewriter":
      return <TypewriterTitle overlay={ov} accent={accent} />;
    case "split":
      return ov.media && ov.media.length >= 2 ? (
        <SplitScreen top={ov.media[0]} bottom={ov.media[1]} accent={accent} />
      ) : null;
    default:
      return <TitleOverlay overlay={ov} accent={accent} />;
  }
};

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
          {renderOverlay(ov, captions.accent)}
        </Sequence>
      ))}

      {/* Audio: narration drives the whole timeline; bgm sits well under it */}
      {audio.url ? <Audio src={audio.url} volume={audio.volume ?? 1} /> : null}
      {bgm?.url ? <Audio src={bgm.url} volume={bgm.volume ?? 0.12} loop /> : null}
    </AbsoluteFill>
  );
};
