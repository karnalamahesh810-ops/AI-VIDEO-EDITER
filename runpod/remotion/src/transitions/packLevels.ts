/**
 * The owner's overlay transition pack as data (no React, no Remotion), so the
 * renderer, the editor's Player and a node test read the same arithmetic:
 * which clip a scene names, where it plays around its cut, and how loud its
 * own sound is. PackTransition.tsx draws it; src/timeline.py is the Python twin
 * (pack_name, _pack_span, pack_under_db, pack_gain) and
 * tests/test_sound_under_voice.py runs this file against it.
 *
 * Loudness (the owner, 2026-10-01: the pack's sounds stood over the voice):
 * each clip's loudest 400 ms is measured (transitions_meta.json "lufs"), and
 * its gain puts that moment capUnder dB under the narration's measured
 * loudness (doc.meta.voiceLufs), a glitch clip capUnderCategory.glitch -
 * never above 1 (the clip as recorded).
 */
import type { Scene } from "../types";
// Measured with the files (public/transitions); src/timeline.py reads the same copy.
import packMeta from "../data/transitions_meta.json";
import { SOUND_DATA, num, voiceLevel, type SoundData } from "../components/lib/lookSoundPlan";

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
  /** The clip sound's loudest 400 ms (LUFS) and its sample peak (dBFS), measured. */
  lufs?: number;
  peakDb?: number;
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

/** dB under the voice a pack clip's loudest moment sits: the sound ceiling, a glitch clip the glitches'. */
export const packUnderDb = (name: string, data: SoundData = SOUND_DATA): number => {
  const L = data.levels;
  const glitch = L.capUnderCategory?.glitch;
  return PACK_CLIPS[name]?.character === "glitch" && typeof glitch === "number" ? Math.max(L.capUnder, glitch) : L.capUnder;
};

/**
 * The gain of a pack clip's own sound against this voice (doc.meta.voiceLufs):
 * its loudest moment packUnderDb under the voice, never above 1. A clip not
 * measured counts as a matched sound file (refLufs).
 */
export const packGain = (name: string, voiceLufs: unknown, data: SoundData = SOUND_DATA): number => {
  if (!Object.prototype.hasOwnProperty.call(PACK_CLIPS, name)) return 0;
  const lufs = num(PACK_CLIPS[name].lufs);
  const loud = lufs === null ? data.levels.refLufs : lufs;
  return Math.min(1, 10 ** ((voiceLevel(voiceLufs, data) - packUnderDb(name, data) - loud) / 20));
};

/**
 * The level a scene's pack clip plays at: the planned transitionGain (else
 * the ceiling), never above packGain for this voice, times the master
 * (0 muted .. 1; it can only turn the clip down), never above 1.
 */
export const packVolume = (scene: Pick<Scene, "transition" | "transitionGain">, voiceLufs: unknown,
  master: number, data: SoundData = SOUND_DATA): number => {
  const name = packClipName(scene.transition);
  if (!name) return 0;
  const ceiling = packGain(name, voiceLufs, data);
  const asked = num(scene.transitionGain);
  const gain = asked !== null && asked >= 0 ? Math.min(asked, ceiling) : ceiling;
  const m = Math.max(0, Math.min(1, Number.isFinite(master) ? master : 1));
  return Math.max(0, Math.min(1, gain * m));
};
