import { loadFont as loadCourierPrime } from "@remotion/google-fonts/CourierPrime";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadBebas } from "@remotion/google-fonts/BebasNeue";
import { loadFont as loadBarlowCondensed } from "@remotion/google-fonts/BarlowCondensed";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadInterTight } from "@remotion/google-fonts/InterTight";
import { loadFont as loadCinzel } from "@remotion/google-fonts/Cinzel";
import { loadFont as loadSourceSerif } from "@remotion/google-fonts/SourceSerif4";
import { loadFont as loadGeistMono } from "@remotion/google-fonts/GeistMono";

/**
 * The composition's typefaces, loaded the same way in the RunPod render and in
 * the editor's in-browser Player, so the preview and the export are the same
 * picture. System fonts (Liberation, DejaVu) exist in the worker image but not
 * on a creator's machine, which made every preview a slightly different video.
 *
 * One type system for every text, number, date and name look (the owner,
 * 2026-10-05: "the font is not great ... we need bold and clear and better
 * fonts"). Five faces, each with one job:
 *
 *   ANTON            heavy condensed display: the words and figures that carry a line
 *   DISPLAY          Bebas Neue: condensed caps for titles and big numbers on cards
 *   LABEL / NARROW   Barlow Condensed 500-800: labels, kickers, tags, chart text
 *   INTER / SUBLINE  Inter and Inter Tight 600-800: sentences and small tracked lines
 *   SERIF            Source Serif 4: quotes, documents, the documentary voice
 *   MONO             Geist Mono: timestamps, coordinates, records
 *
 * Retired (cheap-looking at 1080p over footage): Oswald 500 (now Barlow
 * Condensed, NARROW), Caveat handwriting (HAND is Barlow Condensed italic),
 * Permanent Marker (MARKER is Anton), JetBrains Mono (MONO is Geist Mono) and
 * Playfair Display's thin roman for quotes (SERIF is Source Serif 4). The
 * names stay, so every look that imported them changes with this file.
 * Kept for their own looks: Courier Prime (typed documents), Cinzel and
 * Playfair 700/900 (the VidRush date looks the owner approved).
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
export const INTER = `${loadInter("normal", { ...latin, weights: ["400", "600", "700", "800"] }).fontFamily}, system-ui, sans-serif`;

// The "pro" graphics (components/pro): Bebas Neue for big numbers and titles,
// Barlow Condensed for labels and tags.
export const DISPLAY = `${loadBebas("normal", { ...latin, weights: ["400"] }).fontFamily}, Impact, sans-serif`;
export const LABEL = `${BARLOW_C}, 'Arial Narrow', sans-serif`;

// The white text on footage (the owner, 2026-10-01: "use the font Anton ... cleaner,
// not big, not small"; picked over Bebas Neue, Oswald, Barlow Condensed, Montserrat
// and Inter Tight on a side-by-side sheet): Anton for the words and figures that
// carry the line, Inter Tight 600-700 in tracked caps for the small line under
// them. Each loader holds the render until its font is in (delayRender), and the
// stack falls back to the condensed faces above while it loads in a preview.
export const ANTON = `${loadAnton("normal", { ...latin, weights: ["400"] }).fontFamily}, ${DISPLAY}`;
export const SUBLINE = `${loadInterTight("normal", { ...latin, weights: ["600", "700"] }).fontFamily}, ${INTER}`;
/** Anton's cap height and its line metrics (em; units per em 2048: caps 1760, ascender 2409, descender 674). */
export const ANTON_CAP = 0.859;
/** Inter Tight's cap height (em). */
export const SUBLINE_CAP = 0.728;

// The VidRush date looks (components/lib/LibPackVR): Cinzel caps for the serif
// date on its band, Playfair Display 700/900 for the gold time card and its
// label, Inter 600 for the year that counts along the line.
export const CINZEL = `${loadCinzel("normal", { ...latin, weights: ["400"] }).fontFamily}, ${SERIF}`;
export const SERIF_HEAVY = `${loadPlayfair("normal", { ...latin, weights: ["700", "900"] }).fontFamily}, Georgia, serif`;
export const INTER_SEMI = INTER;

// The case-file graphics (components/pro/ProCase) and the editor's notes: a clean
// condensed italic for notes (was Caveat handwriting), the heavy display face for
// the big words (was Permanent Marker), Geist Mono for window chrome and records.
export const HAND = `${BARLOW_C_ITALIC}, ${BARLOW_C}, 'Arial Narrow', sans-serif`;
export const MARKER = ANTON;
export const MONO = `${loadGeistMono("normal", { ...latin, weights: ["500", "600", "700"] }).fontFamily}, ui-monospace, monospace`;

/** Source Serif 4 at the weights the quote and document looks use (400 body, 600-700 headlines). */
export const DOC_SERIF = SERIF;
