# Motion polish (2026-10-18): catalogue first, then the rebuild

**Why.** The owner judged Motion Library pack 2 (32 `ml-*` looks, ef5a9fe) "okay but vague, needs a lot of
improvement". He liked the donut / percentage chart and the date / timeline looks. Those two are the bar.
The rest read generic next to his reference channels.

This file is the catalogue the rebuild was built from. The proof sheets are in `docs/motion-polish/`.

## 1. Reference catalogue

The sources are:

- **PointShift branded explainer:** `docs/smart-editor/ref/sheet_1.jpg`, sheet_2, 60 tiles at 240x135.
- **Celebs Goat:** `docs/style-refs/celeb-elements.md` and `celeb-compilation-STYLE.md`, measured frame by frame.
- **Agent Flappy labels:** `docs/style-refs/kqTsZAmbByU/style_spec.md`, measured at 60 fps.
- **SpideyParker fandom essays:** `docs/style-refs/fandom-essay-STYLE.md`.
- **VidRush exports:** `runpod/docs/vidrush-graphics.md`.

Sizes are a share of the frame height.

### Type

| Element | Reference | Measure |
|---|---|---|
| Hero title | PointShift "BURJ KHALIFA" | Condensed heavy caps (Bebas / Barlow Condensed 800 class) in **gold** on royal blue. Two lines fill **~60%** of the height, each line's cap height **~27%**. Tight leading **~0.9**, tracking ~0. |
| Hero figure | PointShift "130 / KM", "$1.5B", "90%" | White geometric extra-bold. Figure cap height **18-22%**, unit in small caps under it at **~35%** of the figure size, tracking +0.1em. |
| Label pill | PointShift "STRAIT OF HORMUZ", "TAIWAN" | Gold fill, dark text, condensed caps **~3-4%**, tracking +0.08em, square-ish corners. Sits beside its subject, never on it. |
| Bottom label | Agent Flappy | Montserrat ExtraBold class, white, thin dark outline plus a short hard shadow. Text band **8.3%**, centred at **85%** height. |
| Punchline pop | Celebs Goat | Caps at **6.5-7.5%**, a 3-4 px stroke at 720p. Placed **on the speaker**, tilted ±6°. |
| Lower third | SpideyParker | Small-caps role over a serif name on a colour bar. |
| Chapter card | SpideyParker | White bold sans on black. |
| Typewriter | VidRush | Typewriter memo boxes, a thin red rule under a short serif line. |

**What these share:** one heavy face per graphic; the big words at 2-4x the size of the small words; small words in tracked caps (+0.08 to +0.16em) and a muted colour; one accent colour used on one thing.

### Motion

| Element | Reference | Measure |
|---|---|---|
| Number card | Agent Flappy | Slides in from the right in **~0.1 s**, ease-out expo, motion blur, a ~3° tilt that settles. **No bounce, no scale pop.** |
| Labels | Agent Flappy | On in **1 frame** (21% exactly on a cut). Off in 1 frame, or a whip of **~0.07 s**. Hold median **2.4 s**. |
| Letter pop | Celebs Goat | Per letter: each glyph scales 0 → 115% → 100% over 3 frames, 1-frame stagger, ~0.35 s for a word. Then a slow grow of ~12% over the hold. This is the comedy register, and only that. |
| Ring | Celebs Goat | Drawn on clockwise in **0.6 s**, ease-out; a hard cut off. |
| Builds | PointShift | Smooth eased builds. The tower draws upward, logos join one by one, the waffle fills, map labels wipe in. Every element arrives on its own beat, never all at once. |

**Rule distilled:** small, fast entrances, slow holds that keep living (a drift or a slow grow), and exits faster than entrances.

### Transitions

- **Celebs Goat:** about 95% hard cuts, plus a white flash of ~0.2 s between segments. No glitch, film burn or light leak.
- **SpideyParker:** white flashes and dips to black at chapter breaks.
- **VidRush:** about one real transition per four cuts (film-burn, light-leak, whip, flash, glitch), rotated so neighbours never match.
- **Lesson:** a transition must read as a crafted film effect (a real light leak, real paper), never as a coloured blob, and it must be short.

## 2. Why the donut and the timeline work (the bar)

Proof frames of both: `docs/motion-polish/bar_donut_timeline.jpg`.

1. **Hierarchy.** One hero figure, large: the donut's centre figure is 0.55 of the ring radius, bold, with tabular figures. Under it sits a small tracked-caps label in the accent. Everything else is small and muted.
2. **One accent on one thing.** The slice or date being talked about is gold. The others are muted tones of the kit.
3. **Structure first, data on its word.** The ring's ghost track and the timeline's dim rail appear first. Each slice or date then lights on its spoken time (`itemAt`). The viewer reads in step with the voice.
4. **A ghost state that lights up.** Unlit dates sit at 35% opacity and become white plus accent when said. The page is calm and readable at every moment.
5. **Consistent furniture.** Every chart title has a short accent rule above it, tracked condensed caps, and a full scrim of 0.55-0.6, so the chart owns its moment.
6. **Counting.** Figures count up with the build, which gives motion with meaning.
7. **No gimmicks.** Flat fills, a soft shadow, no bounce on things that only appear.

## 3. Ranking the 32 pack 2 looks

**Frequency** is how often a planner can pick the look.

- The free rules director (`quickDirector`, app `src/lib/smartEdit.ts`) runs on every Smart edit. Its rotation lists are:
  - hook: 8 looks, every video;
  - contrast: 5 looks, on "But / However / Yet ..." lines, very common;
  - quote: 2 looks;
  - section transition: 7 looks, about one a minute;
  - one-trigger looks: time jump, tech, secret, verdict, correction, countdown, then-and-now, document, post, message.
- The AI director can pick any look from its `use` notes.
- No worker planner picks the pack 2 looks: `src/gaming.py` uses only `ml-gm-*`.

**Generic** is a 1-5 score from the before stills (`docs/motion-polish/before_*.jpg`, plus `docs/motion-pack-2/motion-pack-2-sheet.jpg`). 5 is most generic.

| Look | Picked by | Frequency | Generic | Notes | Rebuilt |
|---|---|---|---|---|---|
| ml-title-wipe | hook rotation | high | 5 | Thin condensed type at 12% of the width; the caret bar floats off the line | **yes** |
| ml-title-stack | hook rotation | high | 4 | Scale 1.9 → 1 "slam" (a bare scale pop) and a 14 px blur; no furniture | **yes** |
| ml-title-extrude | hook rotation | high | 5 | A 42° swing from 0.62 scale; muddy gold extrusion; reads cheap | **yes** |
| ml-title-slice | contrast rotation | high | 5 | Halves travel 40% of the width and are unreadable for 0.6 s; small single line | **yes** |
| ml-em-swoosh | contrast rotation | high | 3 | Fine idea; slow 0.55 s rise, small type | **yes** |
| ml-co-quote | quote rotation | medium | 5 | 3% type in a small glass box at the bottom; fake initials avatar | **yes** |
| ml-tr-blocks | transition rotation | medium | 5 | Random blue / yellow squares at full saturation | **yes** |
| ml-tr-ink | transition rotation | medium | 5 | Lumpy black blots | **yes** |
| ml-tr-tear | transition rotation | medium | 4 | A flat teal sheet with a zigzag edge | **yes** |
| ml-tr-burn | time-jump trigger | medium (history, biography) | 5 | Orange blobs over everything | **yes** |
| ml-em-stamp | verdict trigger | medium | 4 | Thin outlined stamp blurred over the claim | **yes** |
| ml-co-document | document trigger | medium | 3 | Plain but legible page; push-in works | no (next) |
| ml-title-redact | secret trigger | low-medium | 3 | Reads as intended | no |
| ml-tr-glitch | tech trigger | low-medium | 4 | Crude, but tech-only | no (next) |
| ml-em-strike | correction trigger | low | 3 | | no |
| ml-em-countdown | countdown trigger | low | 2 | | no |
| ml-data-split | then-and-now trigger | low | 2 | | no |
| ml-co-post | post trigger | low | 3 | | no |
| ml-co-phone | message trigger | low | 2 | | no |
| ml-co-browser | AI director only | low | 3 | | no |
| ml-data-donut | AI director only | low | **1 (bar)** | | no |
| ml-data-timeline | AI director only | low | **1 (bar)** | | no |
| ml-data-race / line / grid / ladder | AI director only | low | 2 | Chart family, same furniture as the bar | no |
| ml-co-lens / sticky / polaroid | AI director only | low | 2-4 | | no |
| ml-em-scribble / looparrow | AI director only | low | 2-3 | | no |
| ml-title-cardflip | AI director only | low | 3 | | no |

**Rebuilt: 11 looks.** These are the 4 hook / contrast titles, the 3 contrast / quote / verdict looks and the 4 rotation transitions. They are what almost every Smart-edited video shows.

## 4. Rules the rebuild keeps

- **Typography.**
  - Big text uses tight tracking (-0.02 to -0.03em) and line height 0.88-0.92.
  - Small text uses tracked caps (+0.12 to +0.16em) in a muted colour or the accent.
  - Big text is 3-4x the size of the small text.
- **Entrances.**
  - ≤ 300 ms per unit (word, line or element), staggered 30-80 ms, or on the spoken word when `wordAt` / `itemAt` is known.
  - The curve is expoOut / quintOut.
  - No scale-from-0. No back-out overshoot on anything that only appears.
  - The only hit allowed is the stamp: a physical impact that settles in 140 ms without undershoot.
- **Exits.** 0.28 s instead of 0.42 s, so they are faster than the entrances.
- **Depth.** A soft drop shadow, a shallow extrusion (7 steps, a dark tint of the accent rather than a muddy accent) and gentle 3D settles (≤ 18°). Glass and a scrim only where the type needs it.
- **Accent.** One accent per graphic, on one word, one rule or one badge.
- **Legible at 480p.**
  - The smallest text is 0.03 of the height: 14 px at 480p.
  - Titles are 0.09-0.2 of the height.
  - Every look keeps a scrim (directional for side placement, vignette for centre).
- **Subjects.**
  - An `ml-*` look on `position: auto` now reads the scene's avoid boxes (`components/motion/avoid.ts`: faces, logos, burned-in text) and takes the side of the frame that keeps its words off them.
  - Before this, `ml-*` overlays skipped the avoid step in `Main.renderOverlay`.
- **Timing.**
  - Every word still lands on its spoken time: the graphics-timing rule.
  - The registry's sound hits stay at the moment they hit:
    - the stack's first line at about 0.1-0.4 s;
    - the slice's join at about 0.5-0.8 s;
    - the extrude's settle at about 1.0 s;
    - the stamp at the last word + 0.45 s;
    - the swoosh on the last word.
- **Contract.** Same ids, same params (text, sub, kicker, value, items, wordAt, position, seed, speed, scale) and the same layer kinds, so the planner, the registry and the editor are unchanged.
