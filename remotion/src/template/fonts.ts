// Load the reference fonts once (side-effect import). Family names match the
// stacks in theme.ts ("Oswald", "Anton", "Montserrat", "Inter").
import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";

loadOswald({ weights: ["400", "500", "600", "700"] });
loadMontserrat({ weights: ["400", "600", "700", "800"] });
loadInter({ weights: ["400", "600", "700"] });
loadAnton();
