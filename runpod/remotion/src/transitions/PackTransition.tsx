import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import type { Scene } from "../types";
// Measured with the files (public/transitions); src/timeline.py reads the same copy.
import packMeta from "../data/transitions_meta.json";

/**
 * The owner's overlay transition pack (public/transitions/mlt<N>.mp4, the
 * Mr.YTR pack, 2026-10-01): film burns, light leaks, white flashes, film
 * strips, glitches and streaks shot on black, each with its own sound.
 *
 * A scene whose transition is "pack:<name>" enters on a HARD cut and the clip
 * is laid full-frame over that cut with a SCREEN blend (its black is
 * transparent), placed so its most covered frame (transitions_meta.json
 * peakFrame) is the first frame of the new scene: the flash hides the cut.
 * The clip's own sound plays at its original level - the owner's rule is that
 * the pack's sound is never changed or lowered by the mix. Only the editor's
 * sound switch (sfxEnabled false) mutes it, and its master level can only turn
 * it down, never above the original.
 *
 * src/timeline.py (plan_pack_transitions) decides where they go.
 */
export interface PackClip {
  file: string;
  character: string;
  fps: number;
  frames: number;
  duration: number;
  /** The clip's frame that lands on the cut (the first frame of the new scene). */
  peakFrame: number;
  /** peakFrame in seconds. */
  peak: number;
  audioPeak: number;
}

export const PACK_PREFIX = "pack:";

export const PACK_CLIPS: Record<string, PackClip> =
  (packMeta as unknown as { transitions: Record<string, PackClip> }).transitions;

/** The pack clip a scene transition names ("pack:mlt5" -> "mlt5"), or null. */
export const packClipName = (t?: string | null): string | null => {
  if (typeof t !== "string" || !t.startsWith(PACK_PREFIX)) return null;
  const name = t.slice(PACK_PREFIX.length);
  return Object.prototype.hasOwnProperty.call(PACK_CLIPS, name) ? name : null;
};

export const isPackTransition = (t?: string | null): boolean => packClipName(t) !== null;

/** Where a pack clip plays around a cut, in composition frames: its first frame and its length. */
export const packSpan = (name: string, cut: number, fps: number): { from: number; length: number } => {
  const m = PACK_CLIPS[name];
  const same = Math.abs(m.fps - fps) < 1e-6;
  const lead = same ? m.peakFrame : Math.round(m.peak * fps);
  const length = same ? m.frames : Math.max(1, Math.floor(m.duration * fps));
  return { from: cut - lead, length };
};

/**
 * Every pack transition of the document, drawn over the scenes (under the
 * captions and graphics). `volume` is the clip's own sound: 1 = as recorded.
 */
export const PackTransitions: React.FC<{
  scenes: Scene[];
  fps: number;
  durationInFrames: number;
  volume: number;
  premountFor?: number;
}> = ({ scenes, fps, durationInFrames, volume, premountFor }) => {
  const level = Math.max(0, Math.min(1, Number.isFinite(volume) ? volume : 1));
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
