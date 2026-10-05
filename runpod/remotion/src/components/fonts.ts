import { loadFont as loadCourierPrime } from "@remotion/google-fonts/CourierPrime";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadBarlowCondensed } from "@remotion/google-fonts/BarlowCondensed";
import { getInfo as interTightInfo, loadFont as loadInterTight } from "@remotion/google-fonts/InterTight";
import { loadFont as loadArchivo } from "@remotion/google-fonts/Archivo";
import { continueRender, delayRender } from "remotion";
import { loadFont as loadCinzel } from "@remotion/google-fonts/Cinzel";
import { loadFont as loadSourceSerif } from "@remotion/google-fonts/SourceSerif4";
import { loadFont as loadGeistMono } from "@remotion/google-fonts/GeistMono";

/**
 * The composition's typefaces, loaded the same way in the RunPod render and in
 * the editor's in-browser Player, so the preview and the export are the same
 * picture. System fonts (Liberation, DejaVu) exist in the worker image but not
 * on a creator's machine, which made every preview a slightly different video.
 *
 * ONE premium type system for every look (the owner, 2026-10-05: "I don't want
 * this style" - the big yellow condensed word with a thick outline - and "the
 * fonts of the other ones are also not great ... better bold, Adobe After
 * Effects kind of thing"). The poster faces are gone from every look: Anton,
 * Bebas Neue and Permanent Marker. In their place:
 *
 *   GROTESK          Inter Tight 500-900: the display grotesk - headlines, key
 *                    words, names, figures (tabular), dates. The new looks set
 *                    its weight themselves (components/lib/typeKit.tsx).
 *   ANTON / DISPLAY  the same face pinned at ExtraBold ("TG Display": any weight
 *   / MARKER         asked for draws 800): the older looks that set Anton or
 *                    Bebas at weight 400 keep their layout code and now letter
 *                    in the bold grotesk, not a condensed poster face.
 *   KINETIC          Archivo 600-900: the "modern kinetic" direction's display
 *                    (box reveals), only where that direction is chosen.
 *   LABEL / NARROW   Barlow Condensed 500-800: the condensed companion for the
 *                    tight labels of charts, maps and tags (never a headline).
 *   INTER / SUBLINE  Inter and Inter Tight 600-800: sentences, kickers, small
 *                    tracked caps.
 *   SERIF            Source Serif 4: quotes and documents (print).
 *   MONO             Geist Mono: timestamps, coordinates, records.
 *
 * Kept for their own looks only: Courier Prime (typed documents), Cinzel and
 * Playfair 700/900 (the VidRush date looks, no longer picked by the planner).
 * A brand kit that names Anton, Bebas Neue, Oswald, Caveat, Permanent Marker or
 * JetBrains Mono still gets that face for its own cards (brand/brandFonts.ts).
 */
const latin = { subsets: ["latin" as const] };

const BARLOW_C = loadBarlowCondensed("normal", { ...latin, weights: ["500", "600", "700", "800"] }).fontFamily;
const BARLOW_C_ITALIC = loadBarlowCondensed("italic", { ...latin, weights: ["600", "700"] }).fontFamily;
const SOURCE_SERIF = loadSourceSerif("normal", { ...latin, weights: ["400", "600", "700"] }).fontFamily;
const SOURCE_SERIF_ITALIC = loadSourceSerif("italic", { ...latin, weights: ["400", "600", "700"] }).fontFamily;

/** Labels, kickers and sentence text in condensed caps (was Oswald 500/700). */
export const NARROW = `${BARLOW_C}, 'Arial Narrow', sans-serif`;
export const TYPEWRITER = `${loadCourierPrime("normal", { ...latin, weights: ["400", "700"] }).fontFamily}, 'Courier New', monospace`;
/** The documentary serif's italic: highlighted words in a quote (was Playfair Display italic 700). */
export const SERIF_ITALIC = `${SOURCE_SERIF_ITALIC}, Georgia, serif`;
/** The documentary serif: quotes and documents (was Playfair Display 400). */
export const SERIF = `${SOURCE_SERIF}, Georgia, serif`;
export const INTER = `${loadInter("normal", { ...latin, weights: ["400", "500", "600", "700", "800"] }).fontFamily}, system-ui, sans-serif`;

/** The display grotesk at every weight the new looks set (500-900): Inter Tight. */
const INTER_TIGHT = loadInterTight("normal", { ...latin, weights: ["500", "600", "700", "800", "900"] }).fontFamily;
export const GROTESK = `${INTER_TIGHT}, ${INTER}`;
/** The "modern kinetic" direction's display: Archivo 600-900. */
export const KINETIC = `${loadArchivo("normal", { ...latin, weights: ["600", "700", "800", "900"] }).fontFamily}, ${GROTESK}`;

/**
 * The grotesk pinned at one weight under its own family name: every weight a
 * look asks for draws `weight` (the @font-face weight is that one value, so the
 * variable font's wght axis is clamped to it). The older looks set the poster
 * faces at weight 400; with this they letter in ExtraBold Inter Tight without
 * touching their code. Held by delayRender until loaded, like the Google fonts.
 */
const pinned = (family: string, weight: string): string => {
  try {
    if (typeof FontFace === "undefined" || typeof document === "undefined") return family;
    const info = interTightInfo();
    const files = ((info.fonts as Record<string, Record<string, Record<string, string>>>).normal || {})[weight] || {};
    for (const subset of ["latin", "latin-ext"]) {
      const url = files[subset];
      if (!url) continue;
      const face = new FontFace(family, `url(${url}) format('woff2')`,
        { weight, style: "normal", unicodeRange: (info.unicodeRanges as Record<string, string>)[subset] });
      document.fonts.add(face);
      const handle = delayRender(`Loading font ${family} (${subset})`, { timeoutInMilliseconds: 60000 });
      face.load().then(() => continueRender(handle)).catch((e: unknown) => {
        console.warn(`[fonts] ${family} did not load: ${e instanceof Error ? e.message : String(e)}`);
        continueRender(handle);
      });
    }
  } catch (e) {
    console.warn(`[fonts] ${family}: ${e instanceof Error ? e.message : String(e)}`);
  }
  return family;
};
const TG_DISPLAY = pinned("TG Display", "800");

// The "pro" graphics (components/pro) and every older look that set Bebas Neue: the
// pinned grotesk; Barlow Condensed for their labels and tags.
export const DISPLAY = `'${TG_DISPLAY}', ${GROTESK}, sans-serif`;
export const LABEL = `${BARLOW_C}, 'Arial Narrow', sans-serif`;

// The words and figures that carry a line in the older looks (was Anton, the
// owner's 2026-10-01 pick, retired 2026-10-05 with the poster style): the
// pinned ExtraBold grotesk; Inter Tight 600-700 in tracked caps under them.
export const ANTON = DISPLAY;
export const SUBLINE = `${INTER_TIGHT}, ${INTER}`;
/** The display face's cap height (em): Inter Tight's capitals are 1490 of 2048 units (Anton's were 0.859). */
export const ANTON_CAP = 0.727;
/** Inter Tight's cap height (em). */
export const SUBLINE_CAP = 0.728;
/** The display grotesk's cap height (em), for the new looks' size rules. */
export const GROTESK_CAP = 0.727;
/** Archivo's cap height (em). */
export const KINETIC_CAP = 0.718;

// The VidRush date looks (components/lib/LibPackVR): Cinzel caps for the serif
// date on its band, Playfair Display 700/900 for the gold time card and its
// label, Inter 600 for the year that counts along the line.
export const CINZEL = `${loadCinzel("normal", { ...latin, weights: ["400"] }).fontFamily}, ${SERIF}`;
export const SERIF_HEAVY = `${loadPlayfair("normal", { ...latin, weights: ["700", "900"] }).fontFamily}, Georgia, serif`;
export const INTER_SEMI = INTER;

// The case-file graphics (components/pro/ProCase) and the editor's notes: a clean
// condensed italic for notes (was Caveat handwriting), the bold grotesk for the big
// words (was Permanent Marker), Geist Mono for window chrome and records.
export const HAND = `${BARLOW_C_ITALIC}, ${BARLOW_C}, 'Arial Narrow', sans-serif`;
export const MARKER = DISPLAY;
export const MONO = `${loadGeistMono("normal", { ...latin, weights: ["500", "600", "700"] }).fontFamily}, ui-monospace, monospace`;

/** Source Serif 4 at the weights the quote and document looks use (400 body, 600-700 headlines). */
export const DOC_SERIF = SERIF;
