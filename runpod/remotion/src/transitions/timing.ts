import type { SceneTransition } from "../types";

/**
 * How a cut transition is laid out in time.
 *
 * A real editor's transition straddles the cut: the outgoing shot starts to
 * bloom / blur / whip a few frames BEFORE the cut and the incoming shot
 * settles over a few frames after it. Scenes are separate Sequences that tile
 * the narration, so each side draws its own half: the incoming scene plays the
 * `in` half from its frame 0 (the cut), the outgoing scene plays the `out`
 * half over its last frames (SceneClip is told the next scene's transition).
 *
 * The frame of the cut (incoming frame 0) is where the visual hit lands, which
 * is where src/timeline.py puts the sound's loudest point.
 */
export interface TransitionTiming {
  /** Frames drawn at the end of the outgoing scene, before the cut. */
  out: number;
  /** Frames drawn at the start of the incoming scene, from the cut. */
  in: number;
}

/** Transitions drawn by this module (TransitionFrame). The older entrances stay in SceneEffects. */
export const CUT_TRANSITIONS: Record<string, TransitionTiming> = {
  flash: { out: 4, in: 7 },
  "chromatic-flash": { out: 4, in: 8 },
  glitch: { out: 3, in: 8 },
  "vhs-glitch": { out: 3, in: 10 },
  "film-burn": { out: 6, in: 14 },
  "light-leak": { out: 8, in: 16 },
  "whip-pan": { out: 5, in: 7 },
  "zoom-punch": { out: 4, in: 10 },
  "shake-cut": { out: 0, in: 10 },
  "blur-dissolve": { out: 7, in: 10 },
  "luma-fade": { out: 8, in: 11 },
  // Looks pack 3 (2026-10-08): a clean band of light through the cut, and a gentle whip.
  "light-sweep": { out: 6, in: 12 },
  "soft-whip": { out: 5, in: 9 },
};

export const isCutTransition = (t?: SceneTransition | string | null): boolean =>
  Boolean(t && Object.prototype.hasOwnProperty.call(CUT_TRANSITIONS, t));

export interface TransitionState {
  name: string;
  /** Frames relative to the cut: -1 is the last outgoing frame, 0 the first incoming frame. */
  rel: number;
  side: "out" | "in";
  /** Length of this side's window after clamping to the scene. */
  len: number;
  /** 0..1 progress through this side's window. */
  p: number;
  /** Strength of the effect, 1 on the cut, easing to 0 at both ends of the transition. */
  e: number;
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
export const easeInQuad = (t: number) => t * t;
export const easeOutCubic = (t: number) => 1 - Math.pow(1 - clamp01(t), 3);
export const easeInOutSine = (t: number) => -(Math.cos(Math.PI * clamp01(t)) - 1) / 2;

/**
 * Which transition half (if any) is active on this frame of a scene.
 * Windows are clamped so a short scene is never all transition: the incoming
 * half takes at most 45% of the scene, the outgoing half at most 35%, and the
 * two never overlap.
 */
export const transitionState = (
  inT: SceneTransition | undefined,
  outT: SceneTransition | undefined,
  frame: number,
  durationInFrames: number,
): TransitionState | null => {
  const dur = Math.max(1, Math.floor(durationInFrames));
  if (inT && isCutTransition(inT)) {
    const t = CUT_TRANSITIONS[inT];
    const len = Math.min(t.in, Math.max(2, Math.floor(dur * 0.45)));
    if (frame >= 0 && frame < len) {
      const p = len > 1 ? frame / (len - 1) : 1;
      return { name: inT, rel: frame, side: "in", len, p, e: 1 - clamp01(frame / len) };
    }
  }
  if (outT && isCutTransition(outT)) {
    const t = CUT_TRANSITIONS[outT];
    const inLen = inT && isCutTransition(inT) ? Math.min(CUT_TRANSITIONS[inT].in, Math.floor(dur * 0.45)) : 0;
    const len = Math.max(0, Math.min(t.out, Math.floor(dur * 0.35), dur - inLen - 1));
    const rel = frame - dur;  // -len .. -1
    if (len > 0 && rel >= -len && rel < 0) {
      const p = (rel + len + 1) / (len + 1);   // (0, 1): approaches 1 at the cut
      return { name: outT, rel, side: "out", len, p, e: p };
    }
  }
  return null;
};

/** Stable small hash of a string (scene id, url) for per-scene variation. */
export const hashStr = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};
