import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay } from "../../types";
import { clamp01, cubicInOut } from "./ease";
import { motionClass } from "./lookClass";

/**
 * The footage under a full-screen graphic (the owner, 2026-10-05: "the clip
 * is playing and suddenly the map starts ... add a transition - smoother,
 * cooler, better"): the clip starts to push in, soften and dim a few frames
 * BEFORE the graphic arrives and keeps going while it grows in over it, so
 * the graphic comes out of the picture instead of replacing it on a cut;
 * as the graphic leaves, the clip comes back into focus and settles a few
 * frames after it is gone. All on ease-in-out curves (no first-frame jump),
 * in 30 fps frames scaled by the real rate (60 fps moves the same in seconds).
 *
 * The overlay's own wrapper (MotionWrap) fades and scales the graphic over
 * the same frames; together they are the zoom-through. Nothing here draws -
 * it only moves the clip - so there is never a flash or a black frame.
 */
export const STAGE_PRE = 7;     // the clip starts to move this many frames before the graphic
export const STAGE_IN = 12;     // ... and arrives this many frames into it
export const STAGE_OUT = 12;    // the clip starts back this many frames before the graphic ends
export const STAGE_POST = 8;    // ... and settles this many frames after
export const PUSH = 0.06;
export const SOFTEN = 14;
export const DIM = 0.45;

export type StageWindow = { from: number; to: number };

/** The frames each full-screen graphic is on screen (Body-relative). */
export const stageWindows = (overlays: Overlay[] | undefined): StageWindow[] =>
  (overlays || []).filter((ov) => ov && ov.durationInFrames > 0 && motionClass(ov) === "full")
    .map((ov) => ({ from: ov.startFrame, to: ov.startFrame + ov.durationInFrames }));

/** How far the clip is pushed under the graphics at frame f, 0..1 (the strongest window wins). */
export const stageAt = (f: number, wins: StageWindow[], S = 1): number => {
  let p = 0;
  for (const w of wins) {
    const len = w.to - w.from;
    const short = Math.min(1, len / (30 * S));
    const pre = STAGE_PRE * S * short, inF = STAGE_IN * S * short;
    const outF = STAGE_OUT * S * short, post = STAGE_POST * S * short;
    if (f < w.from - pre || f >= w.to + post) continue;
    const pin = cubicInOut(clamp01((f - (w.from - pre)) / Math.max(1, pre + inF)));
    const pout = 1 - cubicInOut(clamp01((f - (w.to - outF)) / Math.max(1, outF + post)));
    p = Math.max(p, Math.min(pin, pout));
    if (p >= 1) break;
  }
  return p;
};

export const StageFx: React.FC<{ windows: StageWindow[]; children: React.ReactNode }> = ({ windows, children }) => {
  const f = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const p = windows.length ? stageAt(f, windows, fps / 30) : 0;
  if (p <= 0.001) return <AbsoluteFill>{children}</AbsoluteFill>;
  const k = width / 1920;
  return (
    <AbsoluteFill style={{ transform: `scale(${(1 + PUSH * p).toFixed(4)})`,
      filter: `blur(${(SOFTEN * k * p).toFixed(2)}px) brightness(${(1 - DIM * p).toFixed(3)})` }}>
      {children}
    </AbsoluteFill>
  );
};
