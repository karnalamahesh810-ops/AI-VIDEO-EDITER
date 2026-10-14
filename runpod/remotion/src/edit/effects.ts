/**
 * A clip's effects stack, mask and motion blur (Editor v2, the After-Effects layer): the contract and its
 * cleaning, pure, shared by the renderer (ClipFx.tsx), the editor's panel and the worker (src/clipfx.py does
 * the same cleaning in Python; a test runs both).
 *
 *   scene.effects    [{ type, value, on? }] - drawn in order on the clip, after its look (grade, treatment,
 *                    effect). Each type's value range and default are in EFFECTS below; on: false = skipped.
 *   scene.mask       { shape: "rect" | "ellipse" | "roundrect", x, y, w, h, feather, invert?, radius? } -
 *                    x / y the top-left, w / h the size, shares of the frame; feather a share of the frame's
 *                    shorter side, centred on the edge; radius (roundrect) a share of the shorter side.
 *                    Outside it the video's black shows; invert: the clip outside, black inside.
 *   scene.motionBlur true (a 180-degree shutter, 0.5) or a shutter 0..1: a blur along the keyframed move.
 * Bad values are dropped or held to range, never an error; an old document draws exactly as before.
 */
import { cleanKeyframes, type ClipKeyframes } from "./keyframes";

export type EffectType = "brightness" | "contrast" | "saturation" | "temperature" | "tint" | "exposure" | "blur"
  | "sharpen" | "glow" | "grain" | "vignette" | "chromatic" | "lut-warm" | "lut-cool" | "bw";

export interface ClipEffect { type: EffectType; value: number; on?: boolean }

export interface EffectSpec { label: string; min: number; max: number; def: number; step: number;
  /** How the value is shown: a signed percentage, a percentage, or stops. */
  unit: "signed" | "pct" | "stops" }

/** Every effect: its name in the editor, its range and the value a new one starts at. */
export const EFFECTS: Record<EffectType, EffectSpec> = {
  brightness: { label: "Brightness", min: -1, max: 1, def: 0.15, step: 0.01, unit: "signed" },
  contrast: { label: "Contrast", min: -1, max: 1, def: 0.2, step: 0.01, unit: "signed" },
  saturation: { label: "Saturation", min: -1, max: 1, def: 0.3, step: 0.01, unit: "signed" },
  temperature: { label: "Temperature", min: -1, max: 1, def: 0.3, step: 0.01, unit: "signed" },
  tint: { label: "Tint", min: -1, max: 1, def: 0.2, step: 0.01, unit: "signed" },
  exposure: { label: "Exposure", min: -3, max: 3, def: 0.5, step: 0.05, unit: "stops" },
  blur: { label: "Blur", min: 0, max: 1, def: 0.2, step: 0.01, unit: "pct" },
  sharpen: { label: "Sharpen", min: 0, max: 1, def: 0.4, step: 0.01, unit: "pct" },
  glow: { label: "Glow", min: 0, max: 1, def: 0.4, step: 0.01, unit: "pct" },
  grain: { label: "Film grain", min: 0, max: 1, def: 0.35, step: 0.01, unit: "pct" },
  vignette: { label: "Vignette", min: 0, max: 1, def: 0.5, step: 0.01, unit: "pct" },
  chromatic: { label: "Colour split", min: 0, max: 1, def: 0.3, step: 0.01, unit: "pct" },
  "lut-warm": { label: "Warm look", min: 0, max: 1, def: 1, step: 0.01, unit: "pct" },
  "lut-cool": { label: "Cool look", min: 0, max: 1, def: 1, step: 0.01, unit: "pct" },
  bw: { label: "Black & white", min: 0, max: 1, def: 1, step: 0.01, unit: "pct" },
};
export const EFFECT_TYPES = Object.keys(EFFECTS) as EffectType[];
/** The most effects one clip keeps. */
export const MAX_EFFECTS = 24;

export type MaskShape = "rect" | "ellipse" | "roundrect";
export const MASK_SHAPES: MaskShape[] = ["rect", "ellipse", "roundrect"];
export interface ClipMask { shape: MaskShape; x: number; y: number; w: number; h: number; feather: number; invert?: boolean; radius?: number }

/** The shutter `motionBlur: true` means (a 180-degree shutter). */
export const DEFAULT_SHUTTER = 0.5;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** The stack cleaned: known types, values held to range, `on` kept only when it is a true/false. */
export const cleanEffects = (raw: unknown): ClipEffect[] | null => {
  if (!Array.isArray(raw)) return null;
  const out: ClipEffect[] = [];
  for (const e of raw) {
    if (!e || typeof e !== "object") continue;
    const type = (e as ClipEffect).type;
    const spec = typeof type === "string" && Object.prototype.hasOwnProperty.call(EFFECTS, type) ? EFFECTS[type] : null;
    const value = num((e as ClipEffect).value);
    if (!spec || value === null) continue;
    const fx: ClipEffect = { type, value: clamp(value, spec.min, spec.max) };
    if (typeof (e as ClipEffect).on === "boolean") fx.on = (e as ClipEffect).on;
    out.push(fx);
    if (out.length >= MAX_EFFECTS) break;
  }
  return out.length ? out : null;
};

/** The mask cleaned, or null (an unknown shape or a size that is not a number above 0 drops it). */
export const cleanMask = (raw: unknown): ClipMask | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const m = raw as Record<string, unknown>;
  const shape = m.shape;
  if (typeof shape !== "string" || !(MASK_SHAPES as string[]).includes(shape)) return null;
  const x = num(m.x), y = num(m.y), w = num(m.w), h = num(m.h);
  if (x === null || y === null || w === null || h === null || w <= 0 || h <= 0) return null;
  const feather = num(m.feather);
  const out: ClipMask = { shape: shape as MaskShape, x: clamp(x, -1, 2), y: clamp(y, -1, 2), w: Math.min(w, 3), h: Math.min(h, 3),
    feather: feather === null ? 0 : clamp(feather, 0, 1) };
  if (typeof m.invert === "boolean") out.invert = m.invert;
  const radius = num(m.radius);
  if (radius !== null) out.radius = clamp(radius, 0, 0.5);
  return out;
};

/** The shutter (0..1) of a motion blur, or null for none. */
export const cleanMotionBlur = (raw: unknown): number | null => {
  if (raw === true) return DEFAULT_SHUTTER;
  const v = num(raw);
  if (v === null || v <= 0) return null;
  return Math.min(1, v);
};

export interface ClipFxSpec { keyframes?: ClipKeyframes; effects?: ClipEffect[]; mask?: ClipMask; motionBlur?: number }

/** A scene's (or layer's) keyframes, effects, mask and motion blur, cleaned; null when it has none. */
export const cleanClipFx = (scene: { keyframes?: unknown; effects?: unknown; mask?: unknown; motionBlur?: unknown } | null | undefined): ClipFxSpec | null => {
  if (!scene) return null;
  const out: ClipFxSpec = {};
  const kf = cleanKeyframes(scene.keyframes);
  if (kf) out.keyframes = kf;
  const fx = cleanEffects(scene.effects);
  if (fx) out.effects = fx;
  const mask = cleanMask(scene.mask);
  if (mask) out.mask = mask;
  const mb = cleanMotionBlur(scene.motionBlur);
  if (mb !== null) out.motionBlur = mb;
  return Object.keys(out).length ? out : null;
};

/** The effects that draw something (on, and not at their no-op value). */
export const liveEffects = (effects: ClipEffect[] | null | undefined): ClipEffect[] =>
  (effects || []).filter((e) => e.on !== false && e.value !== 0);

/** True for an effect drawn through an SVG filter (url(#...)) rather than a CSS filter function or a layer. */
export const svgEffect = (type: EffectType, still: boolean): boolean =>
  type === "temperature" || type === "tint" || type === "sharpen" || type === "chromatic" || type === "lut-warm"
  || type === "lut-cool" || (type === "glow" && !still);

/**
 * The CSS filter list of the stack, in order: CSS functions where they exist (GPU-composited in Chrome),
 * url(#id-i) for the SVG ones (ClipFx defines them), nothing for the layers (grain, vignette, a still's glow).
 * `scale` is the frame's height over 1080 (blur and colour split are sized in pixels at 1080 lines).
 */
export const filterOf = (effects: ClipEffect[], idPrefix: string, scale: number, still: boolean): string => {
  const parts: string[] = [];
  effects.forEach((e, i) => {
    if (e.on === false || e.value === 0) return;
    const v = e.value;
    switch (e.type) {
      case "brightness": parts.push(`brightness(${r4(1 + v)})`); break;
      case "contrast": parts.push(`contrast(${r4(1 + v)})`); break;
      case "saturation": parts.push(`saturate(${r4(1 + v)})`); break;
      case "exposure": parts.push(`brightness(${r4(Math.pow(2, v))})`); break;
      case "blur": parts.push(`blur(${r4(v * 30 * scale)}px)`); break;
      case "bw": parts.push(`grayscale(${r4(v)})`); break;
      default: if (svgEffect(e.type, still)) parts.push(`url(#${idPrefix}-${i})`);
    }
  });
  return parts.join(" ");
};

const r4 = (v: number) => Math.round(v * 10000) / 10000;

/** A 4x5 colour matrix (feColorMatrix values) for a colour effect at value v. */
export const colourMatrix = (type: EffectType, v: number): number[] => {
  const id = [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0];
  const mix = (m: number[], s: number) => id.map((a, i) => r4(a + (m[i] - a) * s));
  switch (type) {
    case "temperature": return [1 + 0.2 * v, 0, 0, 0, 0.02 * v, 0, 1 + 0.03 * v, 0, 0, 0, 0, 0, 1 - 0.2 * v, 0, -0.02 * v, 0, 0, 0, 1, 0].map(r4);
    case "tint": return [1 + 0.06 * v, 0, 0, 0, 0, 0, 1 - 0.14 * v, 0, 0, 0, 0, 0, 1 + 0.06 * v, 0, 0, 0, 0, 0, 1, 0].map(r4);
    // Teal-and-orange warm and a cool blue look: fixed matrices, blended with the identity by the value.
    case "lut-warm": return mix([1.1, 0.06, -0.04, 0, 0.02, 0.02, 1.0, -0.02, 0, 0.01, -0.06, 0.02, 0.86, 0, 0.0, 0, 0, 0, 1, 0], v);
    case "lut-cool": return mix([0.9, 0.02, 0.04, 0, -0.01, 0.0, 1.0, 0.05, 0, 0.0, 0.02, 0.08, 1.1, 0, 0.03, 0, 0, 0, 1, 0], v);
    default: return id;
  }
};

/** How strongly the unsharp mask adds back the detail at value v (picture + a x (picture - blur)). */
export const unsharpAmount = (v: number): number => r4(v * 1.6);

/** True for a clip whose stack blurs it on purpose (the worker's sharpness check leaves such a clip alone). */
export const blursOnPurpose = (effects: ClipEffect[] | null | undefined): boolean =>
  liveEffects(effects).some((e) => e.type === "blur" && e.value >= 0.05);
