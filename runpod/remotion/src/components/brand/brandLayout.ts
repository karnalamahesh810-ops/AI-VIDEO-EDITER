/**
 * The brand kit's frame arithmetic, shared by the composition's length
 * (Root.tsx), the composition itself (Main.tsx) and the editor's previews.
 *
 * A document's own `durationInFrames` is the narration's timeline: every
 * scene, overlay, caption and sound is placed in it. A brand intro plays
 * before it and an outro after it, so the video is intro + body + outro
 * frames long and the body starts `intro` frames in. The worker writes the
 * intro's and outro's frames when it renders (src/brandkit.py
 * prepare_render); a plan saved for the editor carries none, so it never
 * shifts there. src/brandkit.py layout() is this file's twin and a test
 * keeps BRAND_LIMITS equal to its constants.
 */
import type { BrandBlock, BrandClip, BrandOutroCard, TimelineProps } from "../../types";

export const BRAND_LIMITS = {
  positions: ["top-left", "top-right", "bottom-left", "bottom-right"] as const,
  defaultPosition: "top-right",
  logoSizeMin: 0.04,
  logoSizeMax: 0.3,
  logoSizeDefault: 0.1,
  logoOpacityMin: 0.1,
  logoOpacityMax: 1.0,
  logoOpacityDefault: 0.85,
  introMaxSeconds: 15,
  outroMaxSeconds: 20,
  cardMaxSeconds: 20,
};

export type WatermarkPosition = (typeof BRAND_LIMITS.positions)[number];

const httpLink = (u: unknown): u is string => typeof u === "string" && /^https?:\/\//i.test(u.trim());
/** A link the renderer may load: the web, or the worker's own asset server (localise() rewrites local files). */
const usable = (u: unknown): u is string => httpLink(u);

const frames = (f: unknown, most: number): number => {
  const n = typeof f === "number" && Number.isFinite(f) ? Math.floor(f) : 0;
  return n > 0 ? Math.min(n, most) : 0;
};

const clamp = (v: unknown, lo: number, hi: number, dflt: number): number => {
  const n = typeof v === "number" && Number.isFinite(v) ? v : dflt;
  return Math.max(lo, Math.min(hi, n));
};

/** A hex colour or undefined. */
const colour = (c: unknown): string | undefined =>
  typeof c === "string" && /^#[0-9a-fA-F]{6}$/.test(c.trim()) ? c.trim() : undefined;

/**
 * The document's brand block as the renderer may use it: unusable parts
 * left out (a bad link, no frames), numbers clamped. null when there is none.
 */
export const brandOf = (props: Pick<TimelineProps, "brand">): BrandBlock | null => {
  const b = props.brand;
  if (!b || typeof b !== "object") return null;
  const out: BrandBlock = {};
  const a1 = colour(b.accent), a2 = colour(b.accent2);
  if (a1) out.accent = a1;
  if (a2) out.accent2 = a2;
  if (typeof b.fontFamily === "string" && b.fontFamily.trim()) out.fontFamily = b.fontFamily.trim();
  const wm = b.watermark;
  if (wm && usable(wm.url)) {
    const pos = (BRAND_LIMITS.positions as readonly string[]).includes(String(wm.position))
      ? (wm.position as WatermarkPosition) : (BRAND_LIMITS.defaultPosition as WatermarkPosition);
    out.watermark = {
      url: wm.url, position: pos,
      size: clamp(wm.size, BRAND_LIMITS.logoSizeMin, BRAND_LIMITS.logoSizeMax, BRAND_LIMITS.logoSizeDefault),
      opacity: clamp(wm.opacity, BRAND_LIMITS.logoOpacityMin, BRAND_LIMITS.logoOpacityMax, BRAND_LIMITS.logoOpacityDefault),
    };
  }
  if (b.intro && usable(b.intro.url)) out.intro = { ...b.intro };
  const o = b.outro;
  if (o && o.kind === "card") out.outro = { ...(o as BrandOutroCard) };
  else if (o && o.kind === "video" && usable((o as BrandClip).url)) out.outro = { ...(o as BrandClip & { kind: "video" }) };
  return out;
};

/** (intro, body, outro, total) frames of a document's video; see the notes above. */
export const brandFrames = (props: Pick<TimelineProps, "brand" | "durationInFrames" | "fps">) => {
  const fps = Math.max(1, Math.round(Number(props.fps) || 30));
  const body = Math.max(1, Math.round(Number(props.durationInFrames) || 0));
  const b = brandOf(props);
  const intro = b?.intro ? frames(b.intro.frames, Math.round(BRAND_LIMITS.introMaxSeconds * fps)) : 0;
  const most = b?.outro?.kind === "video" ? BRAND_LIMITS.outroMaxSeconds : BRAND_LIMITS.cardMaxSeconds;
  const outro = b?.outro ? frames(b.outro.frames, Math.round(most * fps)) : 0;
  return { intro, body, outro, total: intro + body + outro };
};
