/**
 * Style Match fonts (2026-10-14): the free, commercial-safe library a Style Kit's font match picks from
 * (src/style_match/fonts.py LIBRARY - tests/test_style_match.py keeps the two lists equal). A motion-spec text
 * layer names one as font "lib:<Family>". Each family is loaded on first use only (loadFont holds the frame
 * until it is in), so a video pays for the faces its kit uses, not the whole library.
 */
import { loadFont as loadBangers } from "@remotion/google-fonts/Bangers";
import { loadFont as loadLuckiestGuy } from "@remotion/google-fonts/LuckiestGuy";
import { loadFont as loadTitanOne } from "@remotion/google-fonts/TitanOne";
import { loadFont as loadBowlbyOne } from "@remotion/google-fonts/BowlbyOne";
import { loadFont as loadLilitaOne } from "@remotion/google-fonts/LilitaOne";
import { loadFont as loadChewy } from "@remotion/google-fonts/Chewy";
import { loadFont as loadBungee } from "@remotion/google-fonts/Bungee";
import { loadFont as loadFredoka } from "@remotion/google-fonts/Fredoka";
import { loadFont as loadBaloo2 } from "@remotion/google-fonts/Baloo2";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadPoppins } from "@remotion/google-fonts/Poppins";
import { loadFont as loadNunito } from "@remotion/google-fonts/Nunito";
import { loadFont as loadRubik } from "@remotion/google-fonts/Rubik";
import { loadFont as loadRaleway } from "@remotion/google-fonts/Raleway";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadRoboto } from "@remotion/google-fonts/Roboto";
import { loadFont as loadArchivoBlack } from "@remotion/google-fonts/ArchivoBlack";
import { loadFont as loadWorkSans } from "@remotion/google-fonts/WorkSans";
import { loadFont as loadOpenSans } from "@remotion/google-fonts/OpenSans";
import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadBebasNeue } from "@remotion/google-fonts/BebasNeue";
import { loadFont as loadBarlowCondensed } from "@remotion/google-fonts/BarlowCondensed";
import { loadFont as loadTeko } from "@remotion/google-fonts/Teko";
import { loadFont as loadFjallaOne } from "@remotion/google-fonts/FjallaOne";
import { loadFont as loadLeagueGothic } from "@remotion/google-fonts/LeagueGothic";
import { loadFont as loadPlayfairDisplay } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadMerriweather } from "@remotion/google-fonts/Merriweather";
import { loadFont as loadLora } from "@remotion/google-fonts/Lora";
import { loadFont as loadSourceSerif4 } from "@remotion/google-fonts/SourceSerif4";
import { loadFont as loadCinzel } from "@remotion/google-fonts/Cinzel";
import { loadFont as loadDMSerifDisplay } from "@remotion/google-fonts/DMSerifDisplay";
import { loadFont as loadAbrilFatface } from "@remotion/google-fonts/AbrilFatface";
import { loadFont as loadRobotoSlab } from "@remotion/google-fonts/RobotoSlab";
import { loadFont as loadArvo } from "@remotion/google-fonts/Arvo";
import { loadFont as loadJetBrainsMono } from "@remotion/google-fonts/JetBrainsMono";
import { loadFont as loadCourierPrime } from "@remotion/google-fonts/CourierPrime";
import { loadFont as loadSpaceMono } from "@remotion/google-fonts/SpaceMono";
import { loadFont as loadPermanentMarker } from "@remotion/google-fonts/PermanentMarker";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadRubikMonoOne } from "@remotion/google-fonts/RubikMonoOne";
import { loadFont as loadRussoOne } from "@remotion/google-fonts/RussoOne";
import { loadFont as loadBlackOpsOne } from "@remotion/google-fonts/BlackOpsOne";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Loader = (style?: any, options?: any) => { fontFamily: string };

export const STYLE_FONTS: Record<string, { load: Loader; weights: string[]; fallback: string }> = {
  "Bangers": { load: loadBangers as Loader, weights: ['400'], fallback: "sans-serif" },
  "Luckiest Guy": { load: loadLuckiestGuy as Loader, weights: ['400'], fallback: "sans-serif" },
  "Titan One": { load: loadTitanOne as Loader, weights: ['400'], fallback: "sans-serif" },
  "Bowlby One": { load: loadBowlbyOne as Loader, weights: ['400'], fallback: "sans-serif" },
  "Lilita One": { load: loadLilitaOne as Loader, weights: ['400'], fallback: "sans-serif" },
  "Chewy": { load: loadChewy as Loader, weights: ['400'], fallback: "sans-serif" },
  "Bungee": { load: loadBungee as Loader, weights: ['400'], fallback: "sans-serif" },
  "Fredoka": { load: loadFredoka as Loader, weights: ['700'], fallback: "sans-serif" },
  "Baloo 2": { load: loadBaloo2 as Loader, weights: ['800'], fallback: "sans-serif" },
  "Montserrat": { load: loadMontserrat as Loader, weights: ['800', '900'], fallback: "sans-serif" },
  "Poppins": { load: loadPoppins as Loader, weights: ['700', '900'], fallback: "sans-serif" },
  "Nunito": { load: loadNunito as Loader, weights: ['900'], fallback: "sans-serif" },
  "Rubik": { load: loadRubik as Loader, weights: ['800'], fallback: "sans-serif" },
  "Raleway": { load: loadRaleway as Loader, weights: ['800'], fallback: "sans-serif" },
  "Inter": { load: loadInter as Loader, weights: ['800'], fallback: "sans-serif" },
  "Roboto": { load: loadRoboto as Loader, weights: ['900'], fallback: "sans-serif" },
  "Archivo Black": { load: loadArchivoBlack as Loader, weights: ['400'], fallback: "sans-serif" },
  "Work Sans": { load: loadWorkSans as Loader, weights: ['800'], fallback: "sans-serif" },
  "Open Sans": { load: loadOpenSans as Loader, weights: ['800'], fallback: "sans-serif" },
  "Oswald": { load: loadOswald as Loader, weights: ['700'], fallback: "sans-serif" },
  "Anton": { load: loadAnton as Loader, weights: ['400'], fallback: "sans-serif" },
  "Bebas Neue": { load: loadBebasNeue as Loader, weights: ['400'], fallback: "sans-serif" },
  "Barlow Condensed": { load: loadBarlowCondensed as Loader, weights: ['800'], fallback: "sans-serif" },
  "Teko": { load: loadTeko as Loader, weights: ['600'], fallback: "sans-serif" },
  "Fjalla One": { load: loadFjallaOne as Loader, weights: ['400'], fallback: "sans-serif" },
  "League Gothic": { load: loadLeagueGothic as Loader, weights: ['400'], fallback: "sans-serif" },
  "Playfair Display": { load: loadPlayfairDisplay as Loader, weights: ['800'], fallback: "serif" },
  "Merriweather": { load: loadMerriweather as Loader, weights: ['900'], fallback: "serif" },
  "Lora": { load: loadLora as Loader, weights: ['700'], fallback: "serif" },
  "Source Serif 4": { load: loadSourceSerif4 as Loader, weights: ['700'], fallback: "serif" },
  "Cinzel": { load: loadCinzel as Loader, weights: ['700'], fallback: "serif" },
  "DM Serif Display": { load: loadDMSerifDisplay as Loader, weights: ['400'], fallback: "serif" },
  "Abril Fatface": { load: loadAbrilFatface as Loader, weights: ['400'], fallback: "serif" },
  "Roboto Slab": { load: loadRobotoSlab as Loader, weights: ['800'], fallback: "serif" },
  "Arvo": { load: loadArvo as Loader, weights: ['700'], fallback: "serif" },
  "JetBrains Mono": { load: loadJetBrainsMono as Loader, weights: ['800'], fallback: "monospace" },
  "Courier Prime": { load: loadCourierPrime as Loader, weights: ['700'], fallback: "monospace" },
  "Space Mono": { load: loadSpaceMono as Loader, weights: ['700'], fallback: "monospace" },
  "Permanent Marker": { load: loadPermanentMarker as Loader, weights: ['400'], fallback: "cursive" },
  "Caveat": { load: loadCaveat as Loader, weights: ['700'], fallback: "cursive" },
  "Rubik Mono One": { load: loadRubikMonoOne as Loader, weights: ['400'], fallback: "monospace" },
  "Russo One": { load: loadRussoOne as Loader, weights: ['400'], fallback: "sans-serif" },
  "Black Ops One": { load: loadBlackOpsOne as Loader, weights: ['400'], fallback: "sans-serif" },
};

const loaded: Record<string, string> = {};

/** The CSS family stack of a library face ("lib:Bangers" or "Bangers"), loading it once; null when unknown. */
export const styleFont = (name: string | undefined): string | null => {
  if (!name) return null;
  const fam = name.startsWith("lib:") ? name.slice(4) : name;
  const f = STYLE_FONTS[fam];
  if (!f) return null;
  if (!loaded[fam]) {
    try {
      const r = f.load("normal", { subsets: ["latin"], weights: f.weights });
      loaded[fam] = `${r.fontFamily}, ${f.fallback}`;
    } catch {
      loaded[fam] = `'${fam}', ${f.fallback}`;
    }
  }
  return loaded[fam];
};
