import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Layout and motion constants shared by every overlay and the caption track.
 *
 * Three rules learned from looking at rendered frames:
 *  1. Font sizes must scale with the composition, not be fixed px. Hardcoded
 *     sizes look correct at 1080p and absurd at 640px or vertical.
 *  2. The bottom strip belongs to captions. Overlays that ignore it render
 *     straight through the subtitles and both become unreadable.
 *  3. Every overlay enters and leaves the same way. Mixed easing across
 *     fourteen templates reads as fourteen different videos.
 */

/** Fraction of the frame height reserved at the bottom for captions. */
export const CAPTION_SAFE_ZONE = 0.26;

/** Panel fill used by every overlay that needs a readable surface. */
export const PANEL_BG = "rgba(10,10,12,0.82)";
export const PANEL_SHADOW = "0 18px 50px rgba(0,0,0,0.55)";
export const TEXT_SHADOW = "0 4px 20px rgba(0,0,0,0.9)";
export const SANS = "Inter, system-ui, -apple-system, sans-serif";
export const MONO = "'DejaVu Sans Mono', ui-monospace, monospace";

/** Scale a 1080p-referenced size to the current composition. */
export function useScale() {
  const { width } = useVideoConfig();
  const k = width / 1920;
  return (sizeAt1080p: number) => Math.round(sizeAt1080p * k);
}

/**
 * Padding that keeps overlay content clear of the caption strip, so overlays
 * sit in the upper region instead of on top of the subtitles.
 */
export function useOverlaySafeStyle(): React.CSSProperties {
  const { height } = useVideoConfig();
  return { paddingBottom: Math.round(height * CAPTION_SAFE_ZONE) };
}

/**
 * The shared entrance/exit for an overlay.
 *
 * `enter` springs 0 -> 1 for sliding and scaling; `opacity` folds in the exit
 * fade so a component can usually just spread it onto the root element. Exit
 * is clamped against the clip length so a very short overlay still fades out
 * instead of being cut mid-frame.
 */
export function useOverlayAnim(enterFrames = 16, exitFrames = 10) {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const enter = spring({
    frame,
    fps,
    config: { damping: 200 },
    durationInFrames: Math.min(enterFrames, Math.max(1, durationInFrames - 1)),
  });
  const out = Math.min(exitFrames, Math.max(1, Math.floor(durationInFrames / 3)));
  const exit = interpolate(
    frame,
    [durationInFrames - out, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return { frame, enter, exit, opacity: enter * exit, durationInFrames, fps };
}

/**
 * Progress 0 -> 1 across the first `frames` frames, eased.
 *
 * Used by anything that grows or counts: bars, rings, counters. Kept separate
 * from the spring so charts settle without the spring's slight overshoot,
 * which on a bar chart reads as the data moving.
 *
 * Deliberately NOT a hook and not named like one: charts call it once per bar
 * inside a map(), which a real hook could not do.
 */
export function growth(frame: number, frames: number) {
  return interpolate(frame, [0, Math.max(1, frames)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
}

/**
 * A strictly increasing four-point fade range: [in-start, in-end, out-start, end].
 *
 * The obvious spelling, `[0, FADE, durationInFrames - FADE, durationInFrames]`,
 * stops being monotonic as soon as a clip is shorter than 2*FADE frames, and
 * Remotion's interpolate() throws "inputRange must be strictly monotonically
 * increasing" — a crash mid-render, not a visual glitch. Rounding in the
 * timeline can legitimately produce a one-frame scene, so every fade goes
 * through here.
 */
export function fadeRange(
  durationInFrames: number,
  fade = 6
): [number, number, number, number] {
  const f = Math.min(fade, Math.max(1, Math.floor(durationInFrames / 3)));
  const outStart = Math.max(f + 1, durationInFrames - f);
  return [0, f, outStart, Math.max(outStart + 1, durationInFrames)];
}

/**
 * Format a number the way a broadcast graphic would.
 *
 * Thousands separators, and at most one decimal place — a counter animating
 * through 14 significant figures is noise.
 */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "";
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  return rounded.toLocaleString("en-US");
}
