import React from "react";
import { AbsoluteFill, Easing, Img, interpolate } from "remotion";
import type { Motion } from "../types";
import { hashStr } from "./timing";

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
): { transform: string; transformOrigin?: string } => {
  const dur = Math.max(1, durationInFrames);
  const p = interpolate(frame, [0, dur], [0, 1], clamp);
  const sp = smooth(p);
  const h = hashStr(seedKey || "still");
  switch (motion) {
    case "zoom-in":
      return { transform: `scale(${(1.04 + sp * 0.11).toFixed(4)})` };
    case "zoom-out":
      return { transform: `scale(${(1.16 - sp * 0.11).toFixed(4)})` };
    case "pan-left":
      return { transform: `scale(1.15) translateX(${interpolate(sp, [0, 1], [3.2, -3.2]).toFixed(3)}%)` };
    case "pan-right":
      return { transform: `scale(1.15) translateX(${interpolate(sp, [0, 1], [-3.2, 3.2]).toFixed(3)}%)` };
    case "reveal-left":
    case "reveal-right": {
      const side = motion === "reveal-left" ? -1 : 1;
      const e = interpolate(frame, [0, Math.round(fps * 1.0)], [0, 1], { ...clamp, easing: settle });
      return { transform: `translateX(${((1 - e) * side * 12).toFixed(3)}%) scale(${(1.32 - 0.22 * e + sp * 0.06).toFixed(4)})` };
    }
    case "push-rotate":
      return { transform: `scale(${(1.08 + sp * 0.1).toFixed(4)}) rotate(${interpolate(sp, [0, 1], [-1.4, 0.6]).toFixed(3)}deg)` };
    case "push-offcenter": {
      const [fx, fy] = FOCUS[h % FOCUS.length];
      return { transform: `scale(${(1.03 + sp * 0.19).toFixed(4)})`, transformOrigin: `${fx}% ${fy}%` };
    }
    case "pull-back": {
      const [fx, fy] = FOCUS[(h >>> 3) % FOCUS.length];
      // Most of the reveal happens in the first 70% of the shot, then it rests.
      const e = interpolate(frame, [0, Math.max(2, Math.round(dur * 0.7))], [0, 1], { ...clamp, easing: settle });
      return { transform: `scale(${(1.38 - 0.3 * e - 0.02 * sp).toFixed(4)})`, transformOrigin: `${fx}% ${fy}%` };
    }
    case "drift-diagonal": {
      const sx = h % 2 ? 1 : -1;
      const sy = (h >>> 1) % 2 ? 1 : -1;
      const x = interpolate(sp, [0, 1], [-2.6 * sx, 2.6 * sx]);
      const y = interpolate(sp, [0, 1], [-1.8 * sy, 1.8 * sy]);
      return { transform: `scale(${(1.13 + sp * 0.03).toFixed(4)}) translate(${x.toFixed(3)}%, ${y.toFixed(3)}%)` };
    }
    case "rotate-settle": {
      const dir = h % 2 ? 1 : -1;
      const e = interpolate(frame, [0, Math.round(fps * 1.4)], [0, 1], { ...clamp, easing: settle });
      return { transform: `rotate(${(dir * 2.4 * (1 - e)).toFixed(3)}deg) scale(${(1.17 - 0.08 * e + sp * 0.05).toFixed(4)})` };
    }
    case "parallax":
      // Drawn by StillPicture as two layers; this is the back layer's move.
      return { transform: `scale(${(1.22 + sp * 0.06).toFixed(4)}) translateX(${interpolate(sp, [0, 1], [2, -2]).toFixed(3)}%)` };
    default:
      return { transform: "scale(1.06)" };
  }
};

/**
 * A still photo filling the frame with its motion. `filter` is the scene's
 * grade + effect (+ nothing else), applied to every layer of the picture.
 */
export const StillPicture: React.FC<{
  src: string;
  motion: Motion | undefined;
  frame: number;
  durationInFrames: number;
  fps: number;
  width: number;
  filter?: string;
}> = ({ src, motion, frame, durationInFrames, fps, width, filter }) => {
  const k = width / 1920;
  const move = stillTransform(motion, frame, durationInFrames, fps, src);
  if (motion === "parallax") {
    const p = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
    const sp = smooth(p);
    const dir = hashStr(src) % 2 ? 1 : -1;
    // The front print drifts against the back layer and a little faster: the
    // depth cue. It keeps its own shape (contain), so a portrait stays whole.
    const front = `translateX(${(dir * interpolate(sp, [0, 1], [-1.6, 1.6])).toFixed(3)}%) scale(${(0.99 + sp * 0.05).toFixed(4)})`;
    return (
      <AbsoluteFill>
        <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover", transform: move.transform,
          filter: [filter, `blur(${(26 * k).toFixed(1)}px) brightness(0.62) saturate(1.1)`].filter(Boolean).join(" ") }} />
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <Img src={src} style={{ width: "84%", height: "84%", objectFit: "contain", transform: front,
            filter: [filter, `drop-shadow(0 ${(22 * k).toFixed(1)}px ${(36 * k).toFixed(1)}px rgba(0,0,0,0.55))`].filter(Boolean).join(" ") }} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  return (
    <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover",
      transform: move.transform, transformOrigin: move.transformOrigin, filter: filter || undefined }} />
  );
};
