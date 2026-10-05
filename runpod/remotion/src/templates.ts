/**
 * The renderer's view of the template registry (templates/registry.json):
 * the same file the planner (src/templates.py) and the editor read.
 *
 * `resolveOverlay` fills an overlay's missing fields from its template so a
 * document that names only a template (as the editor does when the user
 * picks one) draws exactly as the planner's fully resolved one would, and so
 * a customised entrance, exit, placement or theme is honoured everywhere.
 */
import registry from "./templates/registry.json";
import type { Overlay } from "./types";
import { remapRetired } from "./legacyLooks";

export interface TemplateDef {
  id: string;
  name: string;
  category: string;
  component: string;
  description: string;
  kind: string;
  emphasis: string;
  props: Record<string, { type: string; label: string; options?: string[]; min?: number; max?: number; default?: unknown }>;
  defaults: { duration: number; entrance: string; exit: string; variant?: string; theme?: string; sfx?: { name: string; volume: number } };
  variants: { style: string[]; entrance: string[]; exit: string[] };
  cues: string[];
  tags: string[];
  /** false: the planner never picks this look on its own (it waits for the owner's approval); the editor still offers it. */
  autoPick?: boolean;
  /** true: a look the owner retired (legacyLooks.ts): never picked, hidden from the look picker, drawn as its replacement. */
  retired?: boolean;
}

export interface Registry {
  version: number;
  categories: string[];
  templates: TemplateDef[];
  imageTreatments: { id: string; name: string; motion: string; treatment: string; effect: string; description: string }[];
  transitions: { id: string; name: string; value: string; duration: number; use: string }[];
  sfx: Record<string, { file: string; volume: number }>;
  stylePacks: Record<string, Record<string, unknown>>;
  captionStyles: Record<string, CaptionStyleDef>;
  /** The style a video's captions get until the user picks one. */
  captionStyleDefault: string;
  /** Older style ids (documentary, news, modern, case) -> the style each now draws as. */
  captionStyleAliases: Record<string, string>;
  musicMoods: Record<string, number>;
  entrances: string[];
  exits: string[];
  positions: string[];
}

export const REGISTRY = registry as unknown as Registry;
export const TEMPLATES: Record<string, TemplateDef> = Object.fromEntries(
  REGISTRY.templates.map((t) => [t.id, t]),
);

export const templateFor = (id?: string): TemplateDef | undefined => (id ? TEMPLATES[id] : undefined);

/** An overlay with its template's defaults filled in where the document left them out. */
export const resolveOverlay = (raw: Overlay): Overlay => {
  // A retired look (the outlined condensed words, the boxed stack) is drawn as its clean replacement (legacyLooks.ts).
  const ov = remapRetired(raw);
  const t = templateFor(ov.template);
  if (!t) return ov;
  const out: Overlay = { ...ov };
  if (!out.type) out.type = t.component as Overlay["type"];
  if (!out.motion) out.motion = t.defaults.entrance;
  if (!out.exit) out.exit = t.defaults.exit;
  if (!out.variant && t.defaults.variant) out.variant = t.defaults.variant;
  if (!out.theme && t.defaults.theme && t.defaults.theme !== "accent") out.theme = t.defaults.theme;
  return out;
};

/**
 * A subtitle style (scripts/build_registry.py CAPTION_STYLES): every style is
 * data, drawn by components/Captions.tsx. Sizes are pixels at 1080 lines.
 */
export interface CaptionStyleDef {
  name: string;
  description: string;
  /** A key of components/captionStyle.ts CAPTION_FONTS. */
  font: string;
  weight: number;
  size: number;
  lineHeight: number;
  /** em */
  letterSpacing: number;
  color: string;
  shadow: "soft" | "subtle" | "none" | string;
  /** A thin dark outline, pixels at 1080 lines (0: none). */
  outline: number;
  /** "box": a dark box behind each line; "band": a dark band along the bottom of the frame. */
  background: "none" | "box" | "band" | string;
  boxColor: string;
  radius: number;
  align: "center" | "left" | string;
  /** "word": the word being spoken is brighter and tinted with the accent. */
  highlight: "none" | "word" | string;
  /** The other words' brightness when highlighting (1 = as bright). */
  dim: number;
  /** Characters per line. */
  lineChars: number;
  /** The face's average letter width (em), for the box estimate. */
  charWidth: number;
  /** The gap under the subtitle, a share of the frame height. */
  bottom: number;
}

/** The style id a name draws as: a style as it is, an older id as its closest new style, else the default (Netflix). */
export const captionStyleId = (name?: string): string => {
  const key = String(name || "").trim().toLowerCase().replace(/[-\s]/g, "_");
  if (REGISTRY.captionStyles[key]) return key;
  const alias = REGISTRY.captionStyleAliases?.[key];
  if (alias && REGISTRY.captionStyles[alias]) return alias;
  return REGISTRY.captionStyleDefault;
};

export const captionStyle = (name?: string): CaptionStyleDef => REGISTRY.captionStyles[captionStyleId(name)];

export const byCategory = (category: string) => REGISTRY.templates.filter((t) => t.category === category);
