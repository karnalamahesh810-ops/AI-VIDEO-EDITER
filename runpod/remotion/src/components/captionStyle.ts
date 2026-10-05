import type React from "react";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadGeist } from "@remotion/google-fonts/Geist";
import { loadFont as loadSourceSerif } from "@remotion/google-fonts/SourceSerif4";
import { loadFont as loadBarlowCondensed } from "@remotion/google-fonts/BarlowCondensed";
import type { CaptionStyleDef } from "../templates";

/**
 * The subtitle styles' typefaces and how a style's data becomes CSS.
 *
 * Every face comes from @remotion/google-fonts like the rest of the
 * renderer's type (components/fonts.ts), so the editor's Player and the
 * render draw the same letters. A face is fetched the first time a style
 * that uses it is drawn (loadFont holds the frame until it is in), so a
 * video with captions off loads none of them.
 */
type Loader = (style: "normal", options: { weights: string[]; subsets: "latin"[] }) => { fontFamily: string };

export const CAPTION_FONTS: Record<string, { load: Loader; fallback: string }> = {
  inter: { load: loadInter as unknown as Loader, fallback: "Helvetica, Arial, sans-serif" },
  geist: { load: loadGeist as unknown as Loader, fallback: "Inter, Helvetica, Arial, sans-serif" },
  "source-serif": { load: loadSourceSerif as unknown as Loader, fallback: "Georgia, 'Times New Roman', serif" },
  "barlow-condensed": { load: loadBarlowCondensed as unknown as Loader, fallback: "'Arial Narrow', Arial, sans-serif" },
};

const loaded = new Map<string, string>();

/** The CSS font stack for a style's face at its weight, loading it on first use. */
export function captionFont(font: string, weight: number): string {
  const key = `${font}:${weight}`;
  const have = loaded.get(key);
  if (have) return have;
  const def = CAPTION_FONTS[font] || CAPTION_FONTS.inter;
  let stack = def.fallback;
  try {
    const { fontFamily } = def.load("normal", { weights: [String(weight)], subsets: ["latin"] });
    stack = `${fontFamily}, ${def.fallback}`;
  } catch {
    // A weight the face does not have: its fallback stack draws instead of failing the render.
  }
  loaded.set(key, stack);
  return stack;
}

/** The text's shadow (and a thin outline drawn with it), sized to the frame. */
export function textShadow(style: CaptionStyleDef, unit: number): string {
  const px = (v: number) => `${Math.round(v * unit * 10) / 10}px`;
  const layers: string[] = [];
  if (style.outline > 0) {
    // A thin outline as eight hard shadows round the letters (no stroke eating into the glyphs).
    const o = style.outline;
    const d = o * 0.7071;
    for (const [x, y] of [[o, 0], [-o, 0], [0, o], [0, -o], [d, d], [-d, d], [d, -d], [-d, -d]]) {
      layers.push(`${px(x)} ${px(y)} 0 rgba(0,0,0,0.88)`);
    }
  }
  if (style.shadow === "soft") {
    // A tight dark edge (holds white letters on a white shirt, snow or sky), a close drop and a wide
    // soft one - still a shadow, not an outline.
    layers.push(`0 0 ${px(1.5)} rgba(0,0,0,0.9)`, `0 0 ${px(4)} rgba(0,0,0,0.55)`,
      `0 ${px(2)} ${px(4)} rgba(0,0,0,0.75)`, `0 ${px(3)} ${px(16)} rgba(0,0,0,0.5)`);
  } else if (style.shadow === "subtle") {
    layers.push(`0 0 ${px(1.2)} rgba(0,0,0,0.75)`, `0 ${px(1)} ${px(3)} rgba(0,0,0,0.7)`,
      `0 0 ${px(12)} rgba(0,0,0,0.4)`);
  }
  return layers.length ? layers.join(", ") : "none";
}

/** #RGB / #RRGGBB -> [r, g, b], or null. */
export function hexRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((hex || "").trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** The spoken word's colour in a highlighting style: white with a share of the accent in it. */
export function highlightColor(accent: string, share = 0.42): [number, number, number] {
  const a = hexRgb(accent) || [255, 212, 0];
  return a.map((v) => Math.round(255 + (v - 255) * share)) as [number, number, number];
}

export const rgba = (c: [number, number, number], alpha: number) => `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;

/** The base text style every line shares. */
export function textStyle(style: CaptionStyleDef, unit: number): React.CSSProperties {
  return {
    fontFamily: captionFont(style.font, style.weight),
    fontWeight: style.weight,
    fontSize: style.size * unit,
    lineHeight: style.lineHeight,
    letterSpacing: `${style.letterSpacing}em`,
    color: style.color,
    textShadow: textShadow(style, unit),
    whiteSpace: "pre",
    fontKerning: "normal",
    fontFeatureSettings: "\"kern\" 1, \"liga\" 1",
  };
}
