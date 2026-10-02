import type React from "react";
import { Easing, interpolate } from "remotion";
import type { Box, Scene } from "../types";

/**
 * Smart reframing, drawn (src/reframe.py plans it).
 *
 * A move is two viewports of the frame - `from` and `to`, shares of the
 * frame as the scene shows it without a move (x/y the top-left corner) -
 * and the picture is scaled and shifted so the viewport fills the frame.
 * It is one CSS transform computed from the frame number and the scene's
 * length only, so every machine of a split render draws the same pixels.
 *
 * Where a move comes from, first match wins:
 *   scene.reframe "off" / false   the editor's "no move here"
 *   scene.reframe {from, to}      the editor's own move
 *   scene.media.reframe           the worker's plan for THIS picture: bound to
 *                                 it by media.source (a merge that swapped the
 *                                 file keeps old fields; its source changes),
 *                                 and planned for this frame's aspect
 * A still's media.reframe may hold only `subject`: the still keeps its own
 * motion, aimed at that box (stillMotion.tsx).
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
/** The stills' gentle ease in and out (stillMotion.tsx `smooth`); src/reframe.py bezier() mirrors it. */
export const REFRAME_EASE = Easing.bezier(0.45, 0.05, 0.55, 0.95);

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A usable box: finite, positive size, (almost) inside the frame. */
export const validBox = (b: unknown): b is Box => {
  if (!b || typeof b !== "object") return false;
  const { x, y, w, h } = b as Box;
  if (![x, y, w, h].every(finite)) return false;
  return w > 0.05 && h > 0.05 && w <= 1.0001 && h <= 1.0001 && x >= -0.0001 && y >= -0.0001
    && x + w <= 1.0001 && y + h <= 1.0001;
};

export interface Move {
  from: Box;
  to: Box;
  /** The scene length the move was planned for (s): a shorter scene gets a shorter move, never a faster one. */
  seconds?: number;
}

/** The move a scene's media should make, or null for none. */
export const resolveMove = (scene: Scene, aspect: number): Move | null => {
  const own = scene.reframe;
  if (own === "off" || own === false) return null;
  if (own && typeof own === "object" && validBox(own.from) && validBox(own.to)) {
    return { from: own.from, to: own.to };
  }
  const plan = scene.media?.reframe;
  if (!plan || typeof plan !== "object" || !validBox(plan.from) || !validBox(plan.to)) return null;
  if (plan.source !== undefined && plan.source !== (scene.media?.source ?? "")) return null;
  if (finite(plan.aspect) && Math.abs(plan.aspect - aspect) > 0.01) return null;
  return { from: plan.from, to: plan.to, seconds: finite(plan.seconds) ? plan.seconds : undefined };
};

/** The subject a still's own motion is aimed at, or undefined (centre / its hashed point, as before). */
export const resolveAim = (scene: Scene, aspect: number): Box | undefined => {
  const own = scene.reframe;
  if (own === "off" || own === false) return undefined;
  const plan = scene.media?.reframe;
  if (!plan || typeof plan !== "object" || !validBox(plan.subject)) return undefined;
  if (plan.source !== undefined && plan.source !== (scene.media?.source ?? "")) return undefined;
  if (finite(plan.aspect) && Math.abs(plan.aspect - aspect) > 0.01) return undefined;
  return plan.subject;
};

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const lerpBox = (a: Box, b: Box, t: number): Box => ({
  x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), w: lerp(a.w, b.w, t), h: lerp(a.h, b.h, t),
});

/**
 * The viewport at a frame of the scene. A scene the editor shortened plays
 * only part of the planned travel, measured from the wider end (a push
 * still starts on the full frame, a pull still ends on it), so the move is
 * never faster than planned.
 */
export const viewportAt = (move: Move, frame: number, durationInFrames: number, fps: number): Box => {
  const dur = Math.max(1, durationInFrames);
  const e = REFRAME_EASE(interpolate(frame, [0, dur], [0, 1], clamp));
  let { from, to } = move;
  if (move.seconds && move.seconds > 0) {
    const k = Math.min(1, dur / fps / move.seconds);
    if (k < 1) {
      if (from.w >= to.w) to = lerpBox(from, to, k);
      else from = lerpBox(to, from, k);
    }
  }
  return lerpBox(from, to, e);
};

/**
 * The CSS that makes `view` fill the frame: scale about the top-left corner,
 * after shifting the viewport's corner there. A box that is not the frame's
 * shape is covered by the square (in frame shares) around its centre.
 */
export const viewportStyle = (view: Box): React.CSSProperties => {
  const side = Math.min(1, Math.max(0.05, view.w, view.h));
  const cx = view.x + view.w / 2;
  const cy = view.y + view.h / 2;
  const x = Math.min(1 - side, Math.max(0, cx - side / 2));
  const y = Math.min(1 - side, Math.max(0, cy - side / 2));
  return {
    transformOrigin: "0 0",
    transform: `scale(${(1 / side).toFixed(5)}) translate(${(-x * 100).toFixed(4)}%, ${(-y * 100).toFixed(4)}%)`,
  };
};

export const reframeStyle = (move: Move, frame: number, durationInFrames: number, fps: number): React.CSSProperties =>
  viewportStyle(viewportAt(move, frame, durationInFrames, fps));

/**
 * The transform origin (shares of the picture) that keeps `subject` inside a
 * picture scaled up to `maxScale` about it, as close to the subject's centre
 * as that allows: scaling about a point keeps that point still, so the push
 * goes toward the subject and never slides it out of the frame.
 */
export const aimOrigin = (subject: Box, maxScale: number): [number, number] => {
  const u = 1 - 1 / Math.max(1.0001, maxScale);
  const axis = (a0: number, a1: number): number => {
    const c = (a0 + a1) / 2;
    const lo = Math.max(0, (a1 - 1 + u) / u);
    const hi = Math.min(1, a0 / u);
    return lo <= hi ? Math.min(hi, Math.max(lo, c)) : Math.min(1, Math.max(0, c));
  };
  return [axis(subject.x, subject.x + subject.w), axis(subject.y, subject.y + subject.h)];
};

/**
 * For a lateral move with a window `win` wide (a share of the picture):
 * where its centre may be so the window holds a0..a1 and - at its widest,
 * `outer` - stays inside the picture. [lo, hi], or the closest single point
 * when nothing can (the subject is wider than the window).
 */
export const centreRange = (a0: number, a1: number, win: number, outer: number = win): [number, number] => {
  const half = win / 2;
  const edge = Math.max(win, outer) / 2;
  const lo = Math.max(edge, a1 - half);
  const hi = Math.min(1 - edge, a0 + half);
  if (lo <= hi) return [lo, hi];
  const c = Math.min(1 - edge, Math.max(edge, (a0 + a1) / 2));
  return [c, c];
};

/**
 * A lateral glide of the window centre toward the subject: [start, end]
 * centres, `travel` apart where there is room, ending as close to the
 * subject's centre as the window allows. `dir` breaks the tie for a centred
 * subject (the motion's own direction).
 */
export const aimGlide = (a0: number, a1: number, win: number, travel: number, dir: number,
  outer: number = win): [number, number] => {
  const [lo, hi] = centreRange(a0, a1, win, outer);
  const c = (a0 + a1) / 2;
  const d = Math.abs(c - 0.5) > 0.03 ? Math.sign(c - 0.5) : dir >= 0 ? 1 : -1;
  const t = Math.min(travel, hi - lo);
  let end = Math.min(hi, Math.max(lo, c));
  let start = end - d * t;
  if (start < lo) { start = lo; end = lo + t; }
  if (start > hi) { start = hi; end = hi - t; }
  return [start, end];
};
