/**
 * Brand kits for the Smart Editor (2026-10-14): ONE design system per channel, so every graphic of a video
 * shares its palette, type, label style, number + unit style, map colours, easing and timing - "branded, not
 * random" (the owner, after a PointShift reference: royal blue, gold condensed titles, white figures with
 * small caps units, gold pill labels, smooth eased builds).
 *
 * A motion spec names its kit (spec.kit) and refers to its tokens instead of raw values: a colour "$primary",
 * "$secondary", "$region", "$bg", "$bg2", "$text", "$number", "$muted", "$pillBg", "$pillText"; a font
 * "$title", "$number", "$label", "$body"; an easing "$ease" / "$easeSoft". The same table lives in
 * src/brandkits.py (a test keeps them equal).
 */
export interface BrandKit {
  id: string;
  name: string;
  colors: Record<"bg" | "bg2" | "primary" | "secondary" | "region" | "text" | "number" | "muted" | "pillBg" | "pillText", string>;
  fonts: Record<"title" | "number" | "label" | "body", string>;
  /** Title weight and tracking (em). */
  titleWeight: number;
  titleTracking: number;
  ease: string;
  easeSoft: string;
  /** Multiplies every entrance duration (1 = the grammar's own). */
  tempo: number;
}

export const KITS: Record<string, BrandKit> = {
  royal: {
    id: "royal", name: "Royal explainer",
    colors: { bg: "#1a1aa8", bg2: "#0b0b5e", primary: "#f2b630", secondary: "#5b5bf0", region: "#4b4bdf",
      text: "#ffffff", number: "#ffffff", muted: "#c9cbe8", pillBg: "#f2b630", pillText: "#141414" },
    fonts: { title: "narrow", number: "grotesk", label: "narrow", body: "inter" },
    titleWeight: 800, titleTracking: 0.0, ease: "quintOut", easeSoft: "inOut", tempo: 1.0,
  },
  noir: {
    id: "noir", name: "Documentary noir",
    colors: { bg: "#15171c", bg2: "#060708", primary: "#e8b64c", secondary: "#8fa3b8", region: "#c9973a",
      text: "#ffffff", number: "#ffffff", muted: "#b9bcc4", pillBg: "#e8b64c", pillText: "#111111" },
    fonts: { title: "grotesk", number: "grotesk", label: "narrow", body: "inter" },
    titleWeight: 800, titleTracking: -0.01, ease: "expoOut", easeSoft: "inOut", tempo: 1.1,
  },
  bulletin: {
    id: "bulletin", name: "News bulletin",
    colors: { bg: "#1b1d22", bg2: "#0c0d10", primary: "#e5484d", secondary: "#f5f5f5", region: "#e5484d",
      text: "#ffffff", number: "#ffffff", muted: "#c3c6cc", pillBg: "#e5484d", pillText: "#ffffff" },
    fonts: { title: "kinetic", number: "grotesk", label: "narrow", body: "inter" },
    titleWeight: 900, titleTracking: -0.015, ease: "expoOut", easeSoft: "out", tempo: 0.85,
  },
  atlas: {
    id: "atlas", name: "Atlas teal",
    colors: { bg: "#0d3b45", bg2: "#06191e", primary: "#f4d35e", secondary: "#2ec4b6", region: "#2ec4b6",
      text: "#ffffff", number: "#ffffff", muted: "#bfd8dc", pillBg: "#f4d35e", pillText: "#10282d" },
    fonts: { title: "grotesk", number: "mono", label: "narrow", body: "inter" },
    titleWeight: 800, titleTracking: 0.0, ease: "quintOut", easeSoft: "inOut", tempo: 1.0,
  },
};

export const kitOf = (id: unknown): BrandKit => KITS[typeof id === "string" ? id : ""] || KITS.noir;

/** A colour value with its kit token resolved ("$primary" -> the kit's hex); anything else unchanged. */
export const kitColor = (v: unknown, kit: BrandKit): unknown =>
  typeof v === "string" && v.startsWith("$") ? (kit.colors as Record<string, string>)[v.slice(1)] ?? v : v;

export const kitFont = (v: unknown, kit: BrandKit): unknown =>
  typeof v === "string" && v.startsWith("$") ? (kit.fonts as Record<string, string>)[v.slice(1)] ?? v : v;

export const kitEase = (v: unknown, kit: BrandKit): unknown =>
  v === "$ease" ? kit.ease : v === "$easeSoft" ? kit.easeSoft : v;
