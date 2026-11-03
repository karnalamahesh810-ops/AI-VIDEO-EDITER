import React from "react";
import { AbsoluteFill } from "remotion";

/**
 * The editor's adjustment line (every style): one set of adjustments for ALL clips at once (doc.adjust), each clip
 * free to set its own (scene.adjust; a key the clip sets wins). Drawn as a transform and a colour filter over the
 * scene's picture layer; absent / neutral = nothing changes (every timeline made before it).
 */
export interface Adjust {
  /** 1 = as is (0.5 - 2). */
  scale?: number;
  /** Shift in % of the frame (-50 .. 50). */
  x?: number;
  y?: number;
  flip?: boolean;
  /** 1 = as is (0.5 - 1.5). */
  brightness?: number;
  contrast?: number;
  /** 1 = as is (0 - 2). */
  saturation?: number;
  /** Force the blurred-sides fill on / off for clips that are not 16:9 (absent = as the clip decides). */
  blurFill?: boolean;
}

const num = (v: unknown, lo: number, hi: number): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : undefined;

/** The adjustment a clip is drawn with: the video's, with every key the clip sets of its own on top. */
export function mergeAdjust(video?: Adjust | null, clip?: Adjust | null): Adjust {
  const out: Adjust = {};
  for (const src of [video, clip]) {
    if (!src || typeof src !== "object") continue;
    for (const [k, v] of Object.entries(src)) {
      if (v !== undefined && v !== null) (out as Record<string, unknown>)[k] = v;
    }
  }
  return out;
}

/** CSS for an adjustment, or null when it changes nothing. */
export function adjustStyle(a: Adjust): React.CSSProperties | null {
  const scale = num(a.scale, 0.5, 2) ?? 1;
  const x = num(a.x, -50, 50) ?? 0;
  const y = num(a.y, -50, 50) ?? 0;
  const b = num(a.brightness, 0.5, 1.5) ?? 1;
  const c = num(a.contrast, 0.5, 1.5) ?? 1;
  const s = num(a.saturation, 0, 2) ?? 1;
  const flip = a.flip === true;
  const moves = scale !== 1 || x !== 0 || y !== 0 || flip;
  const colours = b !== 1 || c !== 1 || s !== 1;
  if (!moves && !colours) return null;
  const style: React.CSSProperties = {};
  if (moves) {
    style.transform = `translate(${x}%, ${y}%) scale(${flip ? -scale : scale}, ${scale})`;
    style.transformOrigin = "50% 50%";
  }
  if (colours) style.filter = `brightness(${b}) contrast(${c}) saturate(${s})`;
  return style;
}

/** A scene's picture under the video's and the clip's adjustments. */
export const Adjusted: React.FC<{ video?: Adjust | null; clip?: Adjust | null; children: React.ReactNode }> = (
  { video, clip, children }) => {
  const style = adjustStyle(mergeAdjust(video, clip));
  if (!style) return <>{children}</>;
  return <AbsoluteFill style={{ overflow: "hidden" }}><AbsoluteFill style={style}>{children}</AbsoluteFill></AbsoluteFill>;
};
