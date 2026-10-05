/**
 * The fonts a brand kit may choose: the typefaces this renderer already loads
 * (components/fonts.ts), by the family name @remotion/google-fonts registers.
 * The captions take the name itself (Captions.tsx); the brand's own cards use
 * the full stack below. src/brandkit.py FONTS is the same list (a test keeps
 * them equal); the app's Brand Kit page offers exactly these.
 */
import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadMarker } from "@remotion/google-fonts/PermanentMarker";
import { loadFont as loadJetBrains } from "@remotion/google-fonts/JetBrainsMono";
import {
  ANTON, CINZEL, DISPLAY, INTER, LABEL, SERIF_HEAVY, SUBLINE, TYPEWRITER,
} from "../fonts";

// The looks no longer use these four faces (components/fonts.ts, 2026-10-05), but a brand kit
// may still name them for its captions and cards: they load here, for the kit that asks.
const latin = { subsets: ["latin" as const] };
const OSWALD = `${loadOswald("normal", { ...latin, weights: ["500", "700"] }).fontFamily}, 'Arial Narrow', sans-serif`;
const CAVEAT = `${loadCaveat("normal", { ...latin, weights: ["600", "700"] }).fontFamily}, cursive`;
const PERMANENT_MARKER = `${loadMarker("normal", { ...latin, weights: ["400"] }).fontFamily}, cursive`;
const JETBRAINS = `${loadJetBrains("normal", { ...latin, weights: ["500", "700"] }).fontFamily}, monospace`;

export const BRAND_FONTS: Record<string, string> = {
  "Inter": INTER,
  "Inter Tight": SUBLINE,
  "Oswald": OSWALD,
  "Anton": ANTON,
  "Bebas Neue": DISPLAY,
  "Barlow Condensed": LABEL,
  "Playfair Display": SERIF_HEAVY,
  "Cinzel": CINZEL,
  "Courier Prime": TYPEWRITER,
  "JetBrains Mono": JETBRAINS,
  "Caveat": CAVEAT,
  "Permanent Marker": PERMANENT_MARKER,
};

/** The CSS font stack for a brand font name; Inter for anything else. */
export const brandFont = (name?: string | null): string => BRAND_FONTS[String(name || "")] || INTER;
