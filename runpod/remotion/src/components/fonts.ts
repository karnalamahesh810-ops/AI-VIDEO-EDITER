import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadCourierPrime } from "@remotion/google-fonts/CourierPrime";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";

/**
 * The composition's typefaces, loaded the same way in the RunPod render and in
 * the editor's in-browser Player, so the preview and the export are the same
 * picture. System fonts (Liberation, DejaVu) exist in the worker image but not
 * on a creator's machine, which made every preview a slightly different video.
 *
 * Chosen to match VidRush's exports: a condensed sans for sentence text and
 * date stamps, a typewriter face for document cards, an italic serif for the
 * highlighted words, Inter for captions.
 */
const latin = { subsets: ["latin" as const] };

export const NARROW = `${loadOswald("normal", { ...latin, weights: ["500", "700"] }).fontFamily}, 'Arial Narrow', sans-serif`;
export const TYPEWRITER = `${loadCourierPrime("normal", { ...latin, weights: ["400", "700"] }).fontFamily}, 'Courier New', monospace`;
export const SERIF_ITALIC = `${loadPlayfair("italic", { ...latin, weights: ["700"] }).fontFamily}, Georgia, serif`;
export const SERIF = `${loadPlayfair("normal", { ...latin, weights: ["400"] }).fontFamily}, Georgia, serif`;
export const INTER = `${loadInter("normal", { ...latin, weights: ["400", "700", "800"] }).fontFamily}, system-ui, sans-serif`;
