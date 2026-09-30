import React from "react";
import { Audio, Sequence, staticFile } from "remotion";
import { scheduleCues, type LookMode, type ScheduleContext, type ScheduledSound, type SoundCue } from "./lookSoundPlan";

/**
 * Sound that belongs to the animation (the owner, 2026-09-30: "the
 * animation needs its specific sound BUILT IN - not us adding sounds on the
 * timeline"). Main.tsx gives every overlay and every full-screen animation
 * scene a LookSoundScope: the look's length, the narration's loudness, the
 * pack's intensity, the overlay's soundGain trim, the document's sfxVolume,
 * the typing take, and whether the look may sound at all (the sound track
 * on, not silenced in the editor, not the weaker of two looks landing
 * together). Inside it:
 *
 *   <LookSounds cues={...} />   plays a registry design (Main renders it for
 *                               every look whose sounds are data)
 *   useLookSound(cues)          a look that knows its own timing (letters
 *                               landing, digits changing) schedules its cues
 *                               from its real animation frames and places the
 *                               returned node in its JSX (LibBoldText)
 *
 * Both clip every sound to the look (never ringing past its last frame; a
 * cut sound fades) and set it against the voice (lookSoundPlan.ts). Looks
 * whose components play their own <Audio> (LibSpeakers, LibPersist,
 * LibChartsC, LibBasinMap: registry defaults.ownSound) are left alone.
 * Outside a scope (a look drawn by itself) both are silent.
 */

export interface LookSoundScope extends ScheduleContext {
  /** False: this look stays silent (sounds off, silenced in the editor, or it lost a clash). */
  on: boolean;
  mode: LookMode;
}

export const LookSoundContext = React.createContext<LookSoundScope | null>(null);

/** The scheduled sounds as audio, each in its own sequence inside the look's. */
export const SoundNodes: React.FC<{ sounds: readonly ScheduledSound[] }> = ({ sounds }) => (
  <>
    {sounds.map((s, i) => {
      const volume = s.fade > 0
        // Fades over its last frames (counted across every pass of a loop: "extend").
        ? (f: number) => s.volume * Math.max(0, Math.min(1, (s.frames - f) / s.fade))
        : s.volume;
      return (
        <Sequence key={`${i}-${s.name}-${s.from}`} from={s.from} durationInFrames={Math.max(1, s.frames)} layout="none"
          showInTimeline={false}>
          <Audio src={staticFile(`sfx/${s.name}.mp3`)} volume={volume} trimBefore={s.trim || undefined}
            loop={s.loop || undefined} loopVolumeCurveBehavior="extend" showInTimeline={false}
            toneFrequency={s.pitch !== 1 ? s.pitch : undefined} />
        </Sequence>
      );
    })}
  </>
);

const useScheduled = (cues: readonly SoundCue[] | undefined | null): ScheduledSound[] => {
  const scope = React.useContext(LookSoundContext);
  // Keyed by content: a look re-renders every frame with a fresh cue array.
  const key = cues ? JSON.stringify(cues) : "";
  return React.useMemo(
    () => (scope && scope.on && cues && cues.length ? scheduleCues(cues, scope) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scope, key]);
};

/** A registry sound design, played for the look in scope. */
export const LookSounds: React.FC<{ cues: readonly SoundCue[] | undefined | null }> = ({ cues }) => {
  const sounds = useScheduled(cues);
  return sounds.length ? <SoundNodes sounds={sounds} /> : null;
};

/**
 * For a look that schedules its own cues from its animation (cue frames at
 * 30 fps from the look's first frame, like the registry's): returns the
 * audio to place anywhere in its JSX.
 */
export const useLookSound = (cues: readonly SoundCue[] | undefined | null): React.ReactNode => {
  const sounds = useScheduled(cues);
  return sounds.length ? <SoundNodes sounds={sounds} /> : null;
};
