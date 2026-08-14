import { useVideoConfig } from "remotion";

/**
 * Layout constants shared by every overlay and the caption track.
 *
 * Two rules learned from looking at rendered frames:
 *  1. Font sizes must scale with the composition, not be fixed px. Hardcoded
 *     sizes look correct at 1080p and absurd at 640px or vertical.
 *  2. The bottom strip belongs to captions. Overlays that ignore it render
 *     straight through the subtitles and both become unreadable.
 */

/** Fraction of the frame height reserved at the bottom for captions. */
export const CAPTION_SAFE_ZONE = 0.26;

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
