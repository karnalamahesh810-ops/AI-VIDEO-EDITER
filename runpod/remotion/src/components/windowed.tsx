import React from "react";
import { useCurrentFrame } from "remotion";

/**
 * Only the timeline items near the playhead are mounted (Editor v2, 2026-10-14).
 *
 * A long video has hundreds of scenes, graphics and sounds, each in its own <Sequence>. Remotion re-renders
 * EVERY mounted Sequence on every frame (each reads the timeline context), even the ones far from the
 * playhead that draw nothing: on a 294-scene, 29-minute document that was ~50 ms of React work a frame in the
 * editor's Player (playback at ~25 fps with long tasks) and the same waste in every rendered frame.
 *
 * Windowed mounts the items whose span meets a window of `bucket` frames around the current frame (plus
 * `lead` frames ahead, so a clip still premounts and loads before its first frame). The window only moves
 * when the frame crosses into the next bucket, so between moves this component returns the SAME element
 * array and React skips it. Deterministic: frame N always mounts the same items, in the worker's render and
 * in the Player, so a render is unchanged; a short document (<= `minItems`) mounts everything as before.
 */
export type WindowItem = { from: number; frames: number; node: React.ReactNode };

export const Windowed: React.FC<{ items: WindowItem[]; lead: number; bucket: number; minItems?: number }> = ({ items, lead, bucket, minItems = 40 }) => {
  const frame = useCurrentFrame();
  const size = Math.max(1, Math.round(bucket));
  const b = Math.floor(Math.max(0, frame) / size);
  const all = items.length <= minItems;
  return React.useMemo(() => {
    if (all) return <>{items.map((it) => it.node)}</>;
    const lo = b * size;
    const hi = lo + size + Math.max(0, lead);
    return <>{items.filter((it) => it.node != null && it.from <= hi && it.from + it.frames > lo).map((it) => it.node)}</>;
  }, [items, b, size, lead, all]);
};
