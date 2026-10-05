import type { CaptionStyleDef } from "../templates";
import type { CueBox } from "./captionPlace";
import type { Cue } from "./captionCues";

/**
 * A subtitle style's measurements on a given frame: its size unit, line
 * length, the gap under it, a cue's box. Pure (no fonts, no React), shared
 * by the drawing (Captions.tsx) and the placement plan (captionPlan.ts).
 */

/** One size unit: 1 at 1080 lines, smaller frames scale down (the shorter side, so vertical video too). */
export const unitFor = (width: number, height: number) => Math.min(width, height) / 1080;

/** Characters per line: the style's on a landscape frame, fewer across a vertical one. */
export const lineCharsFor = (style: CaptionStyleDef, width: number, height: number) =>
  height > width ? Math.min(style.lineChars, 32) : style.lineChars;

/** The gap under the subtitles (share of the height): the style's, higher on a vertical frame (above the phone UI). */
export const bottomFor = (style: CaptionStyleDef, width: number, height: number) =>
  height > width ? Math.max(style.bottom, 0.2) : style.bottom;

/** Padding inside a line's box (em): vertical, horizontal. */
export const BOX_PAD: [number, number] = [0.12, 0.42];
/** Space between two boxed lines (em). */
export const BOX_GAP = 0.14;
/** Left edge of a left-aligned style (share of the width): the title-safe margin. */
export const LEFT_EDGE = 0.07;

/** The band's padding above and below the text (px). */
export const bandPad = (style: CaptionStyleDef, height: number) => Math.round(0.016 * height + style.size * 0.1);

/** The band's height (px): two lines and its padding, whatever the cue (a band that changed size would jump). */
export const bandHeight = (style: CaptionStyleDef, width: number, height: number) =>
  Math.round(2 * style.lineHeight * style.size * unitFor(width, height) + 2 * bandPad(style, height));

/** A cue's box on the frame where it belongs (captionPlace.ts moves it clear of graphics). */
export function cueBox(cue: Pick<Cue, "lines" | "width">, style: CaptionStyleDef, width: number, height: number,
  position?: string): CueBox {
  const unit = unitFor(width, height);
  const font = style.size * unit;
  const lines = cue.lines.length;
  const boxed = style.background === "box" || style.background === "band";
  const textW = cue.width * (style.charWidth + style.letterSpacing) * font + (boxed ? 2 * BOX_PAD[1] * font : 0);
  const textH = lines * style.lineHeight * font
    + (boxed ? lines * 2 * BOX_PAD[0] * font + (lines - 1) * BOX_GAP * font : 0);
  const w = Math.min(0.92, textW / width);
  const h = textH / height;
  const x0 = style.align === "left" ? LEFT_EDGE : 0.5 - w / 2;
  const y1 = position === "center" ? 0.5 + h / 2
    : style.background === "band" ? 1 - bandPad(style, height) / height
      : 1 - bottomFor(style, width, height);
  return { x0, x1: x0 + w, h, y1 };
}
