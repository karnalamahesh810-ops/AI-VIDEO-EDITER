/**
 * The fonts a brand kit may choose: the typefaces this renderer already loads
 * (components/fonts.ts), by the family name @remotion/google-fonts registers.
 * The captions take the name itself (Captions.tsx); the brand's own cards use
 * the full stack below. src/brandkit.py FONTS is the same list (a test keeps
 * them equal); the app's Brand Kit page offers exactly these.
 */
import {
  ANTON, CINZEL, DISPLAY, HAND, INTER, LABEL, MARKER, MONO, NARROW, SERIF_HEAVY, SUBLINE, TYPEWRITER,
} from "../fonts";

export const BRAND_FONTS: Record<string, string> = {
  "Inter": INTER,
  "Inter Tight": SUBLINE,
  "Oswald": NARROW,
  "Anton": ANTON,
  "Bebas Neue": DISPLAY,
  "Barlow Condensed": LABEL,
  "Playfair Display": SERIF_HEAVY,
  "Cinzel": CINZEL,
  "Courier Prime": TYPEWRITER,
  "JetBrains Mono": MONO,
  "Caveat": HAND,
  "Permanent Marker": MARKER,
};

/** The CSS font stack for a brand font name; Inter for anything else. */
export const brandFont = (name?: string | null): string => BRAND_FONTS[String(name || "")] || INTER;
