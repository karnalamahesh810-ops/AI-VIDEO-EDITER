import { captionStyle, resolveOverlay } from "../templates";
import type { CaptionStyleDef } from "../templates";
import type { Overlay, TimelineProps } from "../types";
import footprintData from "../data/caption_footprints.json";
import { buildCues, cueFrames, narrationWords, type FrameCue } from "./captionCues";
import { footprintRects, guessRects, placeCue, placeRects, rectsDuring, type FootprintData, type Obstacle,
  type Placement, type Rect } from "./captionPlace";
import { cueBox, lineCharsFor } from "./captionLayout";

/**
 * The subtitles of a whole video, planned once (Captions.tsx draws them):
 * the style, every phrase cue in frames, where each cue sits clear of the
 * graphics on screen with it, and the letterbox band's runs. Pure - no React,
 * no fonts - so tests/test_captions.py runs it under node.
 */

const FOOTPRINTS = footprintData as unknown as FootprintData;
/** A letterbox band stays up through a pause shorter than this (seconds) rather than blink. */
const BAND_HOLD = 1.2;

type PlanInput = Pick<TimelineProps, "scenes" | "overlays" | "overlaysEnabled" | "brand" | "captions">;

/** The footprint key of an overlay: its template, or a library look's id from its variant. */
export const lookKey = (ov: Partial<Overlay>): string => {
  if (ov.template) return ov.template;
  if (ov.type === "motion" && ov.variant) return `LIB_${ov.variant.toUpperCase().replace(/-/g, "_")}`;
  return "";
};

/** A look's measured footprint as rectangles, or null when it was never measured. */
export const footprintOf = (key: string, data: FootprintData = FOOTPRINTS): Rect[] | null => {
  const mask = key ? data.looks[key] : undefined;
  return mask ? footprintRects(mask, data.grid) : null;
};

/**
 * Every graphic the subtitles must keep clear of, with the frames it is on
 * screen: the overlays (as MotionWrap places them; a full-screen one as
 * drawn), the full-screen animation scenes, and the brand kit's corner logo.
 */
export function captionObstacles(props: Omit<PlanInput, "captions">, width: number, height: number,
  data: FootprintData = FOOTPRINTS): Obstacle[] {
  const out: Obstacle[] = [];
  if (props.overlaysEnabled !== false) {
    for (const raw of props.overlays || []) {
      const ov = resolveOverlay(raw);
      const key = lookKey(ov);
      const own = footprintOf(key, data);
      const rects = own
        ? (ov.backdrop === "blur" ? own : placeRects(own, ov.position, ov.scale))
        : guessRects(ov.position, ov.scale);
      if (rects.length) {
        out.push({ from: ov.startFrame, to: ov.startFrame + ov.durationInFrames, rects, what: key || ov.type });
      }
    }
  }
  for (const sc of props.scenes || []) {
    const anim = sc.media?.type === "animation" ? sc.animation : undefined;
    if (!anim) continue;
    const key = lookKey(resolveOverlay({ ...(anim as Overlay) }));
    const rects = footprintOf(key, data);
    if (rects && rects.length) out.push({ from: sc.startFrame, to: sc.startFrame + sc.durationInFrames, rects, what: key });
  }
  const mark = props.brand?.watermark;
  if (mark && mark.url && typeof mark.size === "number" && String(mark.position || "").startsWith("bottom")) {
    // components/brand/BrandLayers.tsx: a square of `size` x the width, 2.8% / 4.5% in from the edges.
    const w = Math.max(0.04, Math.min(0.3, mark.size));
    const h = (w * width) / height;
    const x0 = mark.position.endsWith("left") ? 0.028 : 1 - 0.028 - w;
    out.push({ from: -Infinity, to: Infinity, rects: [{ x0, x1: x0 + w, y0: 1 - 0.045 - h, y1: 1 - 0.045 }],
      what: "watermark" });
  }
  return out;
}

export interface CaptionPlan {
  style: CaptionStyleDef;
  cues: FrameCue[];
  places: Placement[];
  /** Letterbox: the runs of frames its band is up, [from, to). */
  bands: [number, number][];
}

/** The subtitles of a whole video: the style, its cues in frames and where each one sits. */
export function planCaptions(props: PlanInput, fps: number, width: number, height: number,
  data: FootprintData = FOOTPRINTS): CaptionPlan {
  const style = captionStyle(props.captions?.style);
  const { words, shots } = narrationWords(props.scenes || [], fps);
  const cues = cueFrames(buildCues(words, { maxLineChars: lineCharsFor(style, width, height), shotChanges: shots, fps }),
    fps);
  const obstacles = captionObstacles(props, width, height, data);
  const places = cues.map((c) => placeCue(cueBox(c, style, width, height, props.captions?.position),
    rectsDuring(obstacles, c.from, c.to)));
  const bands: [number, number][] = [];
  if (style.background === "band") {
    const hold = Math.round(BAND_HOLD * fps);
    cues.forEach((c, i) => {
      if (places[i].mode !== "default") return;
      const last = bands[bands.length - 1];
      if (last && c.from - last[1] <= hold) last[1] = c.to;
      else bands.push([c.from, c.to]);
    });
  }
  return { style, cues, places, bands };
}
