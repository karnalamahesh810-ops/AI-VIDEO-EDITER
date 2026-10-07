import type { TimelineProps } from "../types";

/**
 * A Short's frame (src/shorts.py plans it, Short.tsx draws it): where the long video's 16:9 picture - its
 * "stage" - sits in the 9:16 frame at every frame. Pure arithmetic (no React), so a node test
 * (tests/test_shorts.py) checks exactly what the render does.
 *
 *   crop    the stage fills the frame's height; a window of it as wide as the frame shows, centred on
 *           the subject (cx: the window's centre, a share of the stage's width)
 *   fit     the whole stage in a band across the frame (BAND_CENTER), over a blurred copy of the shot:
 *           nothing of it is cut off (a graphic, a news clip's logo, lettering in the picture)
 *   native  a vertical source drawn straight into the frame (Short.tsx draws it over the stage)
 *
 * On a cut the framing snaps to the next shot's; inside a shot (a graphic comes in) it eases over the
 * span's `ease` frames: the picture pulls back to show the graphic, and pushes in again after it.
 */

export type FrameMode = "crop" | "fit" | "native";

export interface FrameSpan {
  from: number;
  to: number;
  mode: FrameMode;
  /** The crop window's centre, a share of the stage's width (0-1). */
  cx: number;
  /** Frames this span takes to ease in from the one before it (0 = it snaps, as on a cut). */
  ease?: number;
  /** The stage scene it frames (an index into stage.scenes). */
  scene?: number;
  why?: string;
  /** NATIVE: the shot's own file, drawn straight into the frame (the stage plays a copy of it). */
  media?: { type: "video" | "image"; url: string; clipSeconds?: number; thumbnail?: string } | null;
}

export interface ShortHook {
  text: string;
  kicker?: string;
  /** Frames the hook stays up from the start. */
  frames: number;
}

export interface ShortWord {
  text: string;
  /** Seconds from the Short's own start. */
  start: number;
  end: number;
}

export interface ShortProps {
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  /** The long video's document cut to the moment, at 1920x1080: Main draws it. */
  stage: TimelineProps;
  framing: FrameSpan[];
  captions: { enabled: boolean; words: ShortWord[]; accent?: string } | null;
  hook: ShortHook | null;
  accent?: string;
  /** (A composition's props are a record: Remotion's Composition takes Record<string, unknown>.) */
  [key: string]: unknown;
}

/** Where things sit, as shares of the frame's height. */
export const BAND_CENTER = 0.43;
export const CAPTION_CENTER = 0.69;
export const HOOK_TOP = 0.1;

export const STAGE_W = 1920;
export const STAGE_H = 1080;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** The fitted band: the whole stage across the frame's width, centred on BAND_CENTER. */
export const bandRect = (W: number, H: number): Rect => {
  const h = (W * STAGE_H) / STAGE_W;
  return { x: 0, y: Math.round(BAND_CENTER * H - h / 2), w: W, h };
};

/** Where the whole stage is drawn (px of the frame) for one framing. Native draws the stage as a crop. */
export const stageRect = (mode: FrameMode, cx: number, W: number, H: number): Rect => {
  if (mode === "fit") return bandRect(W, H);
  const h = H;
  const w = (H * STAGE_W) / STAGE_H;
  const x = clamp(W / 2 - clamp(cx, 0, 1) * w, W - w, 0);
  return { x, y: 0, w, h };
};

/** A smooth ease, no overshoot (the picture never bounces). */
export const easeInOut = (t: number): number => {
  const x = clamp(t, 0, 1);
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
};

export interface View {
  rect: Rect;
  /** 0-1: how far the frame is in FIT (the backdrop shows, the band's shadow). */
  fit: number;
  /** 0-1: how far a native shot covers the frame. */
  native: number;
  /** The span at this frame (null before the first). */
  span: FrameSpan | null;
  index: number;
}

/** The span a frame is in (the last one whose `from` it has reached). */
export const spanIndexAt = (spans: FrameSpan[], frame: number): number => {
  let lo = 0;
  let hi = spans.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (spans[mid].from <= frame) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
};

/** The frame's view: its span's framing, eased from the span before over the span's first `ease` frames. */
export const viewAt = (spans: FrameSpan[], frame: number, W: number, H: number): View => {
  const i = Math.max(0, spanIndexAt(spans, frame));
  const span = spans[i] || null;
  if (!span) return { rect: stageRect("crop", 0.5, W, H), fit: 0, native: 0, span: null, index: -1 };
  const own = stageRect(span.mode, span.cx, W, H);
  const fit = span.mode === "fit" ? 1 : 0;
  const native = span.mode === "native" ? 1 : 0;
  const ease = Math.max(0, Math.round(span.ease || 0));
  const prev = i > 0 ? spans[i - 1] : null;
  const into = frame - span.from;
  if (!prev || ease <= 0 || into >= ease) return { rect: own, fit, native, span, index: i };
  const t = easeInOut((into + 1) / (ease + 1));
  const before = stageRect(prev.mode, prev.cx, W, H);
  return {
    rect: { x: lerp(before.x, own.x, t), y: lerp(before.y, own.y, t), w: lerp(before.w, own.w, t), h: lerp(before.h, own.h, t) },
    fit: lerp(prev.mode === "fit" ? 1 : 0, fit, t),
    native: lerp(prev.mode === "native" ? 1 : 0, native, t),
    span,
    index: i,
  };
};

/** The scenes (indices) some span shows in FIT, and in NATIVE: only those mount a backdrop or a native shot. */
export const scenesIn = (spans: FrameSpan[], mode: FrameMode): Set<number> => {
  const out = new Set<number>();
  for (const s of spans) if (s.mode === mode && typeof s.scene === "number") out.add(s.scene);
  return out;
};

/** The hook's font size (px) for its length: long lines step down so they keep to three lines. */
export const hookSize = (text: string, W: number): number => {
  const n = (text || "").length;
  const share = n > 60 ? 0.058 : n > 46 ? 0.064 : 0.071;
  return Math.round(W * share);
};
