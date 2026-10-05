/** Colour themes an overlay can ask for instead of the brand accent (overlays.tsx THEMES; no imports, no cycles). */
// One accent per graphic, on white type and near-black panels (the owner, 2026-10-05: "some fonts, the
// colours ... not great"): a clean warm gold for the documentary packs (was a dull ochre, #d6a83c), a
// clear crimson, and the cool accents a step brighter so they read on dark footage.
export const THEMES: Record<string, string> = {
  gold: "#F2B544", red: "#E5484D", teal: "#2DD4BF", blue: "#4C9AFF", white: "#F5F3EE", amber: "#FFB224",
};
