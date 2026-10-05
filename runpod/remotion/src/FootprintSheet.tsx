import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { renderOverlay } from "./Main";
import { CaptionsOn } from "./components/layout";
import type { Overlay, Scene } from "./types";

/**
 * A measuring sheet, not a video: every look drawn alone on a transparent
 * frame at a few moments of its run (`samples` frames per look), so
 * scripts/build_caption_footprints.py can record which part of the frame
 * each one covers (data/caption_footprints.json) - the subtitles keep clear
 * of it (components/captionPlace.ts). Drawn with the captions on, as a look
 * that moves out of their way when they are (the source tag) is then placed.
 */
export type FootprintSheetProps = {
  looks: { id: string; overlay: Overlay; at: number[] }[];
  samples: number;
  /** A stand-in picture for the looks that show one. */
  scenes: Scene[];
  accent: string;
};

export const FootprintSheet: React.FC<FootprintSheetProps> = ({ looks, samples, scenes, accent }) => {
  const frame = useCurrentFrame();
  const n = Math.max(1, samples);
  const look = looks[Math.floor(frame / n)];
  if (!look) return null;
  const at = look.at[frame % n] ?? 0;
  // The look's own run placed so that this frame is its frame `at`.
  return (
    <AbsoluteFill>
      <CaptionsOn.Provider value>
        <Sequence key={look.id} from={frame - at} durationInFrames={Math.max(at + 1, look.overlay.durationInFrames)}>
          {renderOverlay(look.overlay, accent, scenes, null)}
        </Sequence>
      </CaptionsOn.Provider>
    </AbsoluteFill>
  );
};
