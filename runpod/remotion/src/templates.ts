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
}

export interface Registry {
  version: number;
  categories: string[];
  templates: TemplateDef[];
  imageTreatments: { id: string; name: string; motion: string; treatment: string; effect: string; description: string }[];
  transitions: { id: string; name: string; value: string; duration: number; use: string }[];
  sfx: Record<string, { file: string; volume: number }>;
  stylePacks: Record<string, Record<string, unknown>>;
  captionStyles: Record<string, { name: string; weight: number; size: number; background: string; emphasis: string }>;
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
export const resolveOverlay = (ov: Overlay): Overlay => {
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

export const captionStyle = (name?: string) =>
  REGISTRY.captionStyles[name || "documentary"] || REGISTRY.captionStyles.documentary;

export const byCategory = (category: string) => REGISTRY.templates.filter((t) => t.category === category);
