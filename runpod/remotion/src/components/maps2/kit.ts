/**
 * The brand kit a maps-v2 look draws with: the sea, the land, the focus region's fill, the label pills, the
 * figures and the type - one design system per channel, so every map of a video matches ("branded, never random").
 *
 * The kits are the Smart Editor's (feature/smart-editor, components/smart/brandKits.ts and src/brandkits.py: royal,
 * noir, bulletin, atlas - same ids, same colours; tests/test_maps_v2.py keeps the copies equal). A look reads its
 * overlay's `kit` (set by the planner from the job's / channel's smart_kit, else the video style), and the brand
 * accent: a channel's own accent colours the pills (its second colour, when set, the region).
 * Default (no kit, no brand accent): royal - the owner's PointShift reference (dark relief, blue region, gold pills).
 */
import { DISPLAY, GROTESK, INTER, KINETIC, MONO, NARROW } from "../fonts";

export interface MapKit {
  id: string;
  sea: string;
  sea2: string;
  land: string;
  landEdge: string;
  border: string;
  region: string;
  regionEdge: string;
  pillBg: string;
  pillText: string;
  accent: string;
  text: string;
  number: string;
  muted: string;
  route: string;
  title: string;
  numberFont: string;
  label: string;
  body: string;
  titleWeight: number;
  /** Multiplies the entrance durations (1 = as designed). */
  tempo: number;
}

type KitRow = { bg: string; bg2: string; primary: string; secondary: string; region: string; text: string; number: string;
  muted: string; pillBg: string; pillText: string; title: string; num: string; label: string; body: string; weight: number;
  tempo: number };

/** The Smart Editor's kits (colours + font tokens), as they are there. */
export const KITS: Record<string, KitRow> = {
  royal: { bg: "#1a1aa8", bg2: "#0b0b5e", primary: "#f2b630", secondary: "#5b5bf0", region: "#4b4bdf", text: "#ffffff",
    number: "#ffffff", muted: "#c9cbe8", pillBg: "#f2b630", pillText: "#141414", title: "narrow", num: "grotesk",
    label: "narrow", body: "inter", weight: 800, tempo: 1.0 },
  noir: { bg: "#15171c", bg2: "#060708", primary: "#e8b64c", secondary: "#8fa3b8", region: "#c9973a", text: "#ffffff",
    number: "#ffffff", muted: "#b9bcc4", pillBg: "#e8b64c", pillText: "#111111", title: "grotesk", num: "grotesk",
    label: "narrow", body: "inter", weight: 800, tempo: 1.1 },
  bulletin: { bg: "#1b1d22", bg2: "#0c0d10", primary: "#e5484d", secondary: "#f5f5f5", region: "#e5484d", text: "#ffffff",
    number: "#ffffff", muted: "#c3c6cc", pillBg: "#e5484d", pillText: "#ffffff", title: "kinetic", num: "grotesk",
    label: "narrow", body: "inter", weight: 900, tempo: 0.85 },
  atlas: { bg: "#0d3b45", bg2: "#06191e", primary: "#f4d35e", secondary: "#2ec4b6", region: "#2ec4b6", text: "#ffffff",
    number: "#ffffff", muted: "#bfd8dc", pillBg: "#f4d35e", pillText: "#10282d", title: "grotesk", num: "mono",
    label: "narrow", body: "inter", weight: 800, tempo: 1.0 },
};

const FONT: Record<string, string> = { narrow: NARROW, grotesk: GROTESK, kinetic: KINETIC, mono: MONO, inter: INTER,
  display: DISPLAY };

const hex = (c: string) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(c || "").trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
export const mix = (a: string, b: string, t: number) => {
  const x = hex(a), y = hex(b);
  if (!x || !y) return a;
  const c = x.map((v, i) => Math.round(v + (y[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
};
export const alpha = (c: string, a: number) => {
  const x = hex(c);
  return x ? `rgba(${x[0]},${x[1]},${x[2]},${a})` : c;
};
/** Relative luminance 0..1. */
export const lum = (c: string) => {
  const x = hex(c);
  if (!x) return 0.5;
  const l = x.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
};

/** The worker's unset accent (a hard yellow): never a brand colour. */
const isBrandAccent = (c: string) => !!hex(c) && !/^#?ffd400$/i.test(String(c).trim());

/**
 * The kit for an overlay: its `kit` id when known, else royal; a brand accent (not the unset default) takes the
 * pills (and the route), the overlay's `accent2` (the brand's second colour) the region.
 */
export const kitFor = (overlay: { kit?: unknown; accent2?: unknown }, accent: string): MapKit => {
  const id = typeof overlay.kit === "string" && KITS[overlay.kit] ? overlay.kit : "royal";
  const r = KITS[id];
  const own = typeof overlay.kit === "string" && !!KITS[overlay.kit];
  const pillBg = !own && isBrandAccent(accent) ? accent : r.pillBg;
  const pillText = lum(pillBg) > 0.42 ? "#141414" : "#ffffff";
  const region = typeof overlay.accent2 === "string" && hex(overlay.accent2) ? overlay.accent2 : r.region;
  // The map's own colours: a near-black sea from the kit's deep tone, a neutral relief grey for the land.
  // (the reference's sea is a near-neutral black: only a trace of the kit's deep tone)
  const sea = mix(r.bg2, "#09090c", 0.86);
  return {
    id,
    sea,
    sea2: mix(r.bg2, "#17181d", 0.8),
    land: mix("#6e7076", r.bg, 0.12),
    landEdge: "rgba(255,255,255,0.20)",
    border: "rgba(14,15,18,0.55)",
    region,
    regionEdge: mix(region, "#ffffff", 0.45),
    pillBg,
    pillText: own ? r.pillText : pillText,
    accent: pillBg,
    text: r.text,
    number: r.number,
    muted: r.muted,
    route: "#ffffff",
    title: FONT[r.title] || NARROW,
    numberFont: FONT[r.num] || GROTESK,
    label: FONT[r.label] || NARROW,
    body: FONT[r.body] || INTER,
    titleWeight: r.weight,
    tempo: r.tempo,
  };
};
