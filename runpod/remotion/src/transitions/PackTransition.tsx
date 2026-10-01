import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import type { Scene } from "../types";
import { PACK_CLIPS, packClipName, packSpan, packVolume } from "./packLevels";

export { PACK_CLIPS, PACK_PREFIX, isPackTransition, packClipName, packGain, packSpan, packUnderDb, packVolume } from "./packLevels";
export type { PackClip } from "./packLevels";

/**
 * The owner's overlay transition pack (public/transitions/mlt<N>.mp4, the
 * Mr.YTR pack, 2026-10-01): film burns, light leaks, white flashes, film
 * strips, glitches and streaks shot on black, each with its own sound.
 *
 * A scene whose transition is "pack:<name>" enters on a HARD cut and the clip
 * is laid full-frame over that cut with a SCREEN blend (its black is
 * transparent), placed so its most covered frame (transitions_meta.json
 * peakFrame) is the first frame of the new scene: the flash hides the cut.
 *
 * The clip plays its own sound, levelled against the narration like every
 * other sound (the owner, 2026-10-01: the pack's sounds stood over the
 * voice): its measured loudest moment sits 6 dB under doc.meta.voiceLufs, a
 * glitch clip 9 (packLevels.ts packGain), never above 1 (the clip as
 * recorded). The planner stores that gain on the scene (transitionGain,
 * src/timeline.py pack_gain); this never plays it louder than the ceiling,
 * the editor's sound switch (sfxEnabled false) mutes it, and its master level
 * (sfxVolume) can only turn it down.
 *
 * src/timeline.py (plan_pack_transitions) decides where they go.
 */

/**
 * Every pack transition of the document, drawn over the scenes (under the
 * captions and graphics). `volume` is the master: 0 mutes, 1 plays each
 * clip at its level against the voice (`voiceLufs`), and never higher.
 */
export const PackTransitions: React.FC<{
  scenes: Scene[];
  fps: number;
  durationInFrames: number;
  volume: number;
  voiceLufs?: unknown;
  premountFor?: number;
}> = ({ scenes, fps, durationInFrames, volume, voiceLufs, premountFor }) => {
  return (
    <>
      {scenes.map((scene, i) => {
        const name = i > 0 ? packClipName(scene.transition) : null;
        if (!name) return null;
        const { from, length } = packSpan(name, scene.startFrame, fps);
        // A clip that would start before the video does keeps its timing by
        // skipping its head; one that would run past the end stops with it.
        const skip = from < 0 ? -from : 0;
        const end = Math.min(durationInFrames, from + length);
        const frames = end - (from + skip);
        if (frames <= 0) return null;
        const level = packVolume(scene, voiceLufs, volume);
        return (
          <Sequence key={`pack-${scene.id}`} name={`transition ${name}`} from={from + skip}
            durationInFrames={frames} premountFor={premountFor}>
            <AbsoluteFill style={{ mixBlendMode: "screen", pointerEvents: "none" }}>
              <OffthreadVideo src={staticFile(PACK_CLIPS[name].file)} trimBefore={skip || undefined}
                volume={level} muted={level <= 0}
                style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </>
  );
};
