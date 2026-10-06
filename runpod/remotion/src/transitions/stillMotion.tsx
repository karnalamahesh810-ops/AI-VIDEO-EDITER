import React from "react";
import { AbsoluteFill, Easing, interpolate } from "remotion";
import type { Box, Motion } from "../types";
import { hashStr } from "./timing";
import { aimGlide, aimOrigin, centreRange } from "../components/reframe";
import { BlurredHold, SafeImg } from "../components/motion/safePicture";

/**
 * How a still photograph moves while it is on screen: the moves a
 * documentary editor makes by hand, all slow and eased (no linear drift that
 * starts and stops dead):
 *
 *   zoom-in / zoom-out      a slow centred push or pull
 *   pan-left / pan-right    a lateral glide at a fixed crop
 *   reveal-left / -right    slides in from a side while settling from close
 *   push-rotate             a push with a slight turn
 *   push-offcenter          a slow push toward a point off centre (a face, a detail)
 *   pull-back               starts tight on a detail and pulls back to reveal the frame
 *   drift-diagonal          a gentle diagonal drift at a fixed crop
 *   parallax                a sharp, slightly smaller print drifting over a blurred copy of itself
 *   rotate-settle           arrives a few degrees off and settles level, then keeps pushing
 *
 * The motion is chosen per scene by src/timeline.py (_IMAGE_MOTIONS), so two
 * stills in a row never share a move. Video clips never get any of this.
 *
 * Aimed (`subject`, src/reframe.py: the face or main object of the picture,
 * frame shares): the push, pull, turn or glide goes toward the subject
 * instead of the centre or a hashed point, and keeps it inside the frame
 * wherever the move's scale allows. Without a subject every move is exactly
 * what it was.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const smooth = Easing.bezier(0.45, 0.05, 0.55, 0.95);     // ease-in-out, gentle at both ends
const settle = Easing.bezier(0.16, 1, 0.3, 1);            // fast then very soft landing

/** Off-centre focus points an editor would push toward (rule-of-thirds-ish). */
const FOCUS = [
  [34, 36], [66, 36], [38, 58], [62, 58], [50, 34], [30, 48], [70, 48],
];

export const stillTransform = (
  motion: Motion | undefined,
  frame: number,
  durationInFrames: number,
  fps: number,
  seedKey: string,
  subject?: Box,
): { transform: string; transformOrigin?: string } => {
  const dur = Math.max(1, durationInFrames);
  const p = interpolate(frame, [0, dur], [0, 1], clamp);
  const sp = smooth(p);
  const h = hashStr(seedKey || "still");
  // Aimed: scale about the point that keeps the subject in frame up to the
  // move's largest scale. A move that also turns keeps its pivot within 20%
  // of the centre: a turn about a point near an edge would show a corner of
  // background.
  const origin = (maxScale: number, limit = 0.5): string | undefined => {
    if (!subject) return undefined;
    const [ox, oy] = aimOrigin(subject, maxScale);
    const lim = (v: number) => 0.5 + Math.max(-limit, Math.min(limit, v - 0.5));
    return `${(lim(ox) * 100).toFixed(2)}% ${(lim(oy) * 100).toFixed(2)}%`;
  };
  const shift = (cx: number, cy: number) => `translate(${((0.5 - cx) * 100).toFixed(3)}%, ${((0.5 - cy) * 100).toFixed(3)}%)`;
  switch (motion) {
    case "zoom-in":
      return { transform: `scale(${(1.04 + sp * 0.11).toFixed(4)})`, transformOrigin: origin(1.15) };
    case "zoom-out":
      return { transform: `scale(${(1.16 - sp * 0.11).toFixed(4)})`, transformOrigin: origin(1.16) };
    case "pan-left":
    case "pan-right": {
      if (subject) {
        // The glide goes toward the subject and ends as near it as the
        // 1.15x window allows, holding it in frame the whole way.
        const win = 1 / 1.15;
        const [a, b] = aimGlide(subject.x, subject.x + subject.w, win, 0.064, motion === "pan-left" ? 1 : -1);
        const [vlo, vhi] = centreRange(subject.y, subject.y + subject.h, win);
        return { transform: `scale(1.15) ${shift(interpolate(sp, [0, 1], [a, b]), Math.min(vhi, Math.max(vlo, 0.5)))}` };
      }
      return { transform: `scale(1.15) translateX(${interpolate(sp, [0, 1], motion === "pan-left" ? [3.2, -3.2] : [-3.2, 3.2]).toFixed(3)}%)` };
    }
    case "reveal-left":
    case "reveal-right": {
      // Aimed, it slides in from the side the subject is on, so the subject
      // is in the first frame instead of arriving last, and it settles with
      // the subject held in frame. The pivot leans toward the subject only as
      // far as the 12% slide allows without a strip of background at the
      // start: a slide in from the left needs the pivot at 37.5% or right of it.
      const c = subject ? subject.x + subject.w / 2 : 0.5;
      const side = c > 0.55 ? -1 : c < 0.45 ? 1 : motion === "reveal-left" ? -1 : 1;
      const e = interpolate(frame, [0, Math.round(fps * 1.0)], [0, 1], { ...clamp, easing: settle });
      let pivot: string | undefined;
      if (subject) {
        const [ox, oy] = aimOrigin(subject, 1.16);
        const x = side > 0 ? Math.max(0.375, ox) : Math.min(0.625, ox);
        pivot = `${(x * 100).toFixed(2)}% ${(oy * 100).toFixed(2)}%`;
      }
      return { transform: `translateX(${((1 - e) * side * 12).toFixed(3)}%) scale(${(1.32 - 0.22 * e + sp * 0.06).toFixed(4)})`,
        transformOrigin: pivot };
    }
    case "push-rotate":
      return { transform: `scale(${(1.08 + sp * 0.1).toFixed(4)}) rotate(${interpolate(sp, [0, 1], [-1.4, 0.6]).toFixed(3)}deg)`,
        transformOrigin: origin(1.21, 0.2) };
    case "push-offcenter": {
      const [fx, fy] = FOCUS[h % FOCUS.length];
      return { transform: `scale(${(1.03 + sp * 0.19).toFixed(4)})`, transformOrigin: origin(1.22) ?? `${fx}% ${fy}%` };
    }
    case "pull-back": {
      const [fx, fy] = FOCUS[(h >>> 3) % FOCUS.length];
      // Most of the reveal happens in the first 70% of the shot, then it rests.
      const e = interpolate(frame, [0, Math.max(2, Math.round(dur * 0.7))], [0, 1], { ...clamp, easing: settle });
      return { transform: `scale(${(1.38 - 0.3 * e - 0.02 * sp).toFixed(4)})`, transformOrigin: origin(1.38) ?? `${fx}% ${fy}%` };
    }
    case "drift-diagonal": {
      const sx = h % 2 ? 1 : -1;
      const sy = (h >>> 1) % 2 ? 1 : -1;
      const scale = (1.13 + sp * 0.03).toFixed(4);
      if (subject) {
        // Toward the subject on both axes; held in the 1.16x window, and the
        // 1.13x window kept inside the picture.
        const [ax, bx] = aimGlide(subject.x, subject.x + subject.w, 1 / 1.16, 0.052, -sx, 1 / 1.13);
        const [ay, by] = aimGlide(subject.y, subject.y + subject.h, 1 / 1.16, 0.036, -sy, 1 / 1.13);
        return { transform: `scale(${scale}) ${shift(interpolate(sp, [0, 1], [ax, bx]), interpolate(sp, [0, 1], [ay, by]))}` };
      }
      const x = interpolate(sp, [0, 1], [-2.6 * sx, 2.6 * sx]);
      const y = interpolate(sp, [0, 1], [-1.8 * sy, 1.8 * sy]);
      return { transform: `scale(${scale}) translate(${x.toFixed(3)}%, ${y.toFixed(3)}%)` };
    }
    case "rotate-settle": {
      const dir = h % 2 ? 1 : -1;
      const e = interpolate(frame, [0, Math.round(fps * 1.4)], [0, 1], { ...clamp, easing: settle });
      return { transform: `rotate(${(dir * 2.4 * (1 - e)).toFixed(3)}deg) scale(${(1.17 - 0.08 * e + sp * 0.05).toFixed(4)})`,
        transformOrigin: origin(1.21, 0.2) };
    }
    case "parallax":
      // Drawn by StillPicture as two layers; this is the back layer's move.
      return { transform: `scale(${(1.22 + sp * 0.06).toFixed(4)}) translateX(${interpolate(sp, [0, 1], [2, -2]).toFixed(3)}%)` };
    default:
      return { transform: "scale(1.06)", transformOrigin: origin(1.06) };
  }
};

/**
 * A still photo filling the frame with its motion. `filter` is the scene's
 * grade + effect (+ nothing else), applied to every layer of the picture.
 * A picture that cannot be drawn never stops the render: `fallbackStill` (the
 * shot before it) is drawn blurred instead (components/motion/safePicture.tsx).
 */
export const StillPicture: React.FC<{
  src: string;
  motion: Motion | undefined;
  frame: number;
  durationInFrames: number;
  fps: number;
  width: number;
  filter?: string;
  /** The picture's subject (frame shares, components/reframe.ts resolveAim): the motion is aimed at it. */
  subject?: Box;
  /** Drawn blurred instead when `src` cannot be drawn (the shot before it; the first of several that can be). */
  fallbackStill?: string | string[];
}> = ({ src, motion, frame, durationInFrames, fps, width, filter, subject, fallbackStill }) => {
  const k = width / 1920;
  const move = stillTransform(motion, frame, durationInFrames, fps, src, subject);
  const hold = <BlurredHold still={fallbackStill} />;
  if (motion === "parallax") {
    const p = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
    const sp = smooth(p);
    const dir = hashStr(src) % 2 ? 1 : -1;
    // The front print drifts against the back layer and a little faster: the
    // depth cue. It keeps its own shape (contain), so a portrait stays whole.
    const front = `translateX(${(dir * interpolate(sp, [0, 1], [-1.6, 1.6])).toFixed(3)}%) scale(${(0.99 + sp * 0.05).toFixed(4)})`;
    return (
      <AbsoluteFill>
        <SafeImg src={src} fallback={hold} style={{ width: "100%", height: "100%", objectFit: "cover", transform: move.transform,
          filter: [filter, `blur(${(26 * k).toFixed(1)}px) brightness(0.62) saturate(1.1)`].filter(Boolean).join(" ") }} />
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <SafeImg src={src} fallback={null} style={{ width: "84%", height: "84%", objectFit: "contain", transform: front,
            filter: [filter, `drop-shadow(0 ${(22 * k).toFixed(1)}px ${(36 * k).toFixed(1)}px rgba(0,0,0,0.55))`].filter(Boolean).join(" ") }} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  return (
    <SafeImg src={src} fallback={hold} style={{ width: "100%", height: "100%", objectFit: "cover",
      transform: move.transform, transformOrigin: move.transformOrigin, filter: filter || undefined }} />
  );
};
