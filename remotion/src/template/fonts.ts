// Load the reference fonts once (side-effect import). Family names match the
// stacks in theme.ts ("Oswald", "Anton", "Montserrat", "Inter").
import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";

// loadFont()'s first positional arg is the STYLE (not options) in @remotion/google-fonts
// 4.x — call with no args to load the default style with all weights (safe + complete).
loadOswald();
loadMontserrat();
loadInter();
loadAnton();
