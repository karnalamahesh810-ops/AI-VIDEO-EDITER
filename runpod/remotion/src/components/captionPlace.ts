/**
 * Where a subtitle cue sits: bottom centre (or lower left), ~9% above the
 * bottom edge - moved up, for that whole cue, when a graphic occupies that
 * part of the frame at any moment the cue is on screen, so the subtitles and
 * a lower third or a corner figure never sit on each other. A subtitle never
 * moves while it is on screen; a cue that cannot clear a graphic low in the
 * frame goes to the top (as broadcast subtitles do over burned-in text), and
 * where nothing is clear it stays where it would overlap least.
 *
 * What a graphic covers comes from data/caption_footprints.json: every look,
 * drawn once at its own size and place (scripts/build_caption_footprints.py),
 * as a grid of the cells it ever puts something in. An overlay's placement
 * (MotionWrap: a named position and a scale) moves and shrinks that grid the
 * same way the renderer moves the look.
 *
 * Pure functions, no React or Remotion (tests/test_captions.py runs them).
 */

/** A rectangle in shares of the frame (0..1), top-left x0/y0. */
export interface Rect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** A graphic on screen over frames [from, to), covering `rects`. */
export interface Obstacle {
  from: number;
  to: number;
  rects: Rect[];
  /** What it is, for the record (a template id, "watermark"). */
  what?: string;
}

export interface FootprintData {
  version: number;
  /** Columns and rows of every look's grid. */
  grid: [number, number];
  /** Template id -> its rows' hex bitmasks, 8 digits a row, top row first (bit c = column c, lowest bit the left edge). */
  looks: Record<string, string>;
}

/** The named positions an overlay may be moved to (components/MotionWrap.tsx POSITION_SHIFT). */
export const POSITION_SHIFT: Record<string, [number, number]> = {
  "top-left": [-0.22, -0.22], top: [0, -0.22], "top-right": [0.22, -0.22],
  center: [0, 0], "bottom-left": [-0.22, 0.22], bottom: [0, 0.22], "bottom-right": [0.22, 0.22],
};

/** The cells of a footprint as rectangles: each row's runs of set cells. */
export function footprintRects(mask: string | undefined, grid: [number, number]): Rect[] {
  if (!mask) return [];
  const [cols, nrows] = grid;
  const digits = Math.ceil(cols / 4);
  const rows: string[] = [];
  for (let i = 0; i + digits <= mask.length; i += digits) rows.push(mask.slice(i, i + digits));
  const out: Rect[] = [];
  // Bit c of a row: hex digit floor(c/4) counted from the right, bit c%4 of it.
  const bit = (hex: string, c: number): boolean => {
    const i = hex.length - 1 - (c >> 2);
    return i >= 0 && ((parseInt(hex[i], 16) >> (c & 3)) & 1) === 1;
  };
  rows.forEach((hex, r) => {
    if (r >= nrows) return;
    let runStart = -1;
    for (let c = 0; c <= cols; c++) {
      const on = c < cols && bit(hex || "0", c);
      if (on && runStart < 0) runStart = c;
      if (!on && runStart >= 0) {
        out.push({ x0: runStart / cols, x1: c / cols, y0: r / nrows, y1: (r + 1) / nrows });
        runStart = -1;
      }
    }
  });
  return out;
}

/**
 * A look's rectangles as the renderer places it: MotionWrap scales the whole
 * frame-sized graphic about the frame's centre and shifts it by a share of
 * the frame (translate(dx*W, dy*H) scale(s)).
 */
export function placeRects(rects: Rect[], position?: string, scale?: number): Rect[] {
  const shift = position && position !== "auto" ? POSITION_SHIFT[position] : undefined;
  const s = typeof scale === "number" && scale > 0 ? scale : 1;
  if (!shift && s === 1) return rects;
  const [dx, dy] = shift || [0, 0];
  const f = (v: number, d: number) => 0.5 + s * (v - 0.5) + d;
  return rects.map((r) => ({ x0: f(r.x0, dx), x1: f(r.x1, dx), y0: f(r.y0, dy), y1: f(r.y1, dy) }));
}

/** What a look covers when it has no measured footprint: a tag moved to a bottom position sits in that corner. */
export function guessRects(position?: string, scale?: number): Rect[] {
  if (!position || !position.startsWith("bottom")) return [];
  const s = typeof scale === "number" && scale > 0 ? Math.min(1, scale) : 1;
  const w = 0.34 * s;
  const h = 0.2 * s;
  const x0 = position === "bottom-left" ? 0.04 : position === "bottom-right" ? 0.96 - w : 0.5 - w / 2;
  return [{ x0, x1: x0 + w, y0: 0.94 - h, y1: 0.94 }];
}

const overlap = (a: Rect, b: Rect): number => {
  const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
  const h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
  return w > 0 && h > 0 ? w * h : 0;
};

const covered = (box: Rect, rects: Rect[]): number => rects.reduce((sum, r) => sum + overlap(box, r), 0);

export interface CueBox {
  /** Left and right edge (shares of the width). */
  x0: number;
  x1: number;
  /** Height (share of the frame height). */
  h: number;
  /** Where its bottom edge sits when nothing is in the way (share of the height from the top). */
  y1: number;
}

export interface Placement {
  /** The cue's bottom edge (share of the height from the top). */
  y1: number;
  mode: "default" | "lifted" | "top";
}

/** Clear space kept between a subtitle and a graphic (share of the height). */
export const CLEARANCE = 0.018;
/** A lifted subtitle's top edge stays below this (share of the height): it belongs to the lower part. */
export const LIFT_LIMIT = 0.42;
/** A subtitle sent to the top sits this far below the top edge. */
export const TOP_MARGIN = 0.07;

/**
 * Where one cue goes, given every rectangle a graphic covers while it is on
 * screen: where it belongs if that is clear; else just above the graphics in
 * its way (repeatedly, while it stays in the lower part of the frame); else at
 * the top if that is clear; else wherever it overlaps least.
 */
export function placeCue(box: CueBox, rects: Rect[]): Placement {
  const at = (y1: number): Rect => ({ x0: box.x0, x1: box.x1, y0: y1 - box.h - CLEARANCE, y1: y1 + CLEARANCE });
  if (!rects.length || covered(at(box.y1), rects) === 0) return { y1: box.y1, mode: "default" };
  let y1 = box.y1;
  for (let i = 0; i < 8; i++) {
    const zone = at(y1);
    const hits = rects.filter((r) => overlap(zone, r) > 0);
    if (!hits.length) return { y1, mode: "lifted" };
    y1 = Math.min(...hits.map((r) => r.y0)) - CLEARANCE;
    if (y1 - box.h < LIFT_LIMIT) break;
  }
  const top = TOP_MARGIN + box.h;
  const atTop = covered(at(top), rects);
  if (atTop === 0) return { y1: top, mode: "top" };
  // Nowhere clear (a full-screen card): where it belongs, unless the top is clearly freer -
  // never parked mid-frame in a spot that overlaps anyway.
  return atTop < covered(at(box.y1), rects) * 0.5 ? { y1: top, mode: "top" } : { y1: box.y1, mode: "default" };
}

/** The rectangles of every obstacle on screen at some moment of frames [from, to). */
export function rectsDuring(obstacles: Obstacle[], from: number, to: number): Rect[] {
  const out: Rect[] = [];
  for (const o of obstacles) {
    if (o.from < to && o.to > from) out.push(...o.rects);
  }
  return out;
}
