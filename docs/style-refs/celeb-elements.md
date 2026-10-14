# Celebs Goat: element catalogue (measured 2026-10-14)

**Sources:** the 5 refs in this folder, all 1280x720 at 29.97 fps.

**Method:**
- A colour scan of every ref at 6 fps (yellow, red and white masks) to find events: `scratchpad/celeb2/scan.py` and `events.py`.
- Frame-by-frame grids (1 frame = 33 ms) on the events.
- Pixel measurements on full-resolution frames.
- ebur128 loudness, and a >4 kHz band check for SFX.

Example frames are in `celeb-elements/` (u_ = UjOJ Avengers bloopers, r_ = r2op Blunt & Krasinski).

Sizes are given as % of frame HEIGHT unless marked "of width". "720p px" means a size on the 1280x720 ref.

## 0. The one typeface
Everything is set in **Komika Axis**: a comic, slanted, round-terminal caps face (the round "G" with a spur, the open "S").
- **Closest free match:** Bangers (OFL), stretched to 130% width with a 1 px self-colour stroke. Side-by-side: `scratchpad/celeb2/fontcmp2.png`.
- Plain Bangers is too condensed. Luckiest Guy and Titan One are too bulky.
- Komika Axis itself is freeware (Apostrophic Labs). The owner can drop the real file in if he wants an exact match.

## 1. Clip captions (on clip speech only, never on narration)
| | Value |
|---|---|
| Box | **Pure black (#000000), 100% opaque**, radius about 12 px at 720p (1.7%) |
| Box size | 78 px tall at 720p (**10.8%**). It hugs the text with about 27 px (3.8%) of padding on every side. |
| Position | Bottom-centre. Box bottom about 10 px from the frame edge, box centre at y = **93%**. |
| Text | Yellow **#FCFF04** (252,255,4), Komika caps. Cap height 25 px = **3.5%**. No stroke, no glow. |
| Green variant | Same box with **green** text, for a second speaker or the cold-open lines ("I'M FROM LONDON, ENGLAND"). |
| Chunking | 1-6 words, a phrase at a time, cut at camera changes ("GOODNESS", "PLAYING MARY POPPINS?"). |
| Motion | **None.** It appears and disappears on a hard cut, with no fade, slide or scale. |
| How often | On most clip speech. Captions are on screen for 12-53% of each video (bloopers less, since much of it is laughing). |

## 2. Punchline pop (quoted big text)
**Examples:** "MOTHERF\*\*\*", "OMG...", "HA HA HA", "FU\*\*", "I LOVE TO DANCE, YEAH", "BECAUSE IT'S", "LONDON, ENGLAND".

| | Value |
|---|---|
| Look | Yellow **#FFFF00** caps in curly quotes. 3-4 px black stroke at 720p. A **yellow outer glow** of about 10 px. |
| Size | Cap height 45-55 px = **6.5-7.5%**. A line runs 30-55% of the frame width. |
| Position | **On the speaker:** just under the chin or beside the mouth, never at a fixed spot. Slightly tilted, -6° to +6°. |
| Entrance | **Per-letter pop, left to right.** Each glyph scales 0 → about 115% → 100% over 3 frames, with a 1-frame stagger. A 10-letter word is complete in about **0.35-0.4 s** (287.58 → 287.95 s). |
| Hold | The whole word keeps **growing slowly**, about 100 → 112% over the hold, with a slight drift ("HA HA HA" 17.9 → 18.4). |
| Exit | A hard cut, usually with the shot change. |
| Length | **1.0-2.0 s.** |
| Trigger | The punchline or swear **as it is said** (the text = the words heard, swears starred), or the laugh itself ("HA HA HA", "OMG..."). Speech-synced word pops in cold opens ("I'M FROM" → "LONDON, ENGLAND") pop word by word in time with the words. |
| How often | About 1 per 20-40 s in story videos. Denser in cold opens and hook montages: 4 in the first 20 s of r2op. |
| Variants | Green with a black stroke for the other person's line ("SUPPOSE I'LL HAVE TO", u_pop_green_second_speaker). Red "\*???\*" with a white stroke for confusion over a head (r_red_question_marks). Green "\*??\*" doodles beside a head (r_green_marks). |

## 3. Name label
**Example:** "JAKE GYLLENHAAL" (u_name_circle).

| | Value |
|---|---|
| Look | **White** Komika caps, 3-4 px black stroke and a soft dark drop shadow. No box. |
| Size | Cap height 44 px = **6%**. |
| Position | Bottom, **under the person named** (x follows the face). About y 87-94%. |
| Entrance | **Per-letter pop with a bounce.** Letters rise from below and rotate into place one by one, 1-frame stagger. About 0.35 s for 15 letters (735.13 → 735.47). |
| Hold and exit | Holds about 1.5 s, then a hard cut at the next shot change. |
| Trigger | The **first time a person appears** in a segment, or a cameo ("JAKE GYLLENHAAL" at the first shot of a Mysterio blooper). Show labels ("AVENGERS" small at the bottom, u 20.3 s) start a blooper from a new film. |
| Pairing | Almost always with the **highlight circle**. |

## 4. Highlight circle
| | Value |
|---|---|
| Look | A yellow **#FFFF00** ring. Stroke about 8 px at 720p (**1.1%**), plus a yellow glow of about 6 px. No fill. |
| Size | Diameter about 2.2x the face height, so the head and hair fit inside. |
| Entrance | **Drawn on.** The arc sweeps clockwise from about 7 o'clock and closes in about **0.6 s** (735.20 → 735.87). Ease-out. |
| Exit | A hard cut with the name label (about 1.4 s after the circle closes). |
| Trigger | Naming someone, or "look who it is". |

## 5. Pointer triangles
| | Value |
|---|---|
| Look | A solid, flat triangle with no stroke: **yellow #FFE600** pointing down, or **red #FF1010** pointing down or right. |
| Size | About 3.5% (yellow) to 6% (red, right-pointing). |
| Position | **Above the head** of the person about to mess up (down-pointer), or **beside the face** (right-pointer). |
| Motion | Appears at the shot start, **tracks the head**, and has a small bob. Lasts 1.5-2.0 s. |
| Trigger | Start of a blooper: "watch this person". |
| How often | About 1 per 2-3 min. |

## 6. Red 3D arrow
r_red_3d_arrow, r2op 13.6 s.

| | Value |
|---|---|
| Look | A chunky **red arrow** with a darker red side (fake 3D). About 12% tall. |
| Position | Points at a face or object from below or from the side. |
| Entrance | **Grows** from about 30% to 100% in 6 frames (0.2 s), then a slight wobble. |
| Length | About 1 s. |
| Trigger | In hook montages and on "look at his face" moments. |

## 7. Image pop-ups
**A. Film title card** (u_title_card_entering, UjOJ 260.6-263.0, bottom-right):
- **Poster** with a 4 px white border and a drop shadow. About 32% tall, at about 12.5% of width from the right edge.
  - It scales from 0 to about 105% and settles at 100% over about 6 frames (0.2 s).
- Then a **grey bar wipes left** out of the poster and reveals the title:
  - the main title "AVENGERS" in white Komika with a black stroke, about 7%;
  - the subtitle "AGE OF ULTRON" in grey with an outline, about 7%;
  - the year "2015" in small white, about 2.5%.
  - The wipe takes about 0.4 s.
- It holds about 1.4 s.
- The exit is the reverse: the text wipes back into the poster, then the poster shrinks to 0. Total about **2.6 s**.
- **Trigger:** the first blooper from a new film.

**B. Poster card** (u_poster_card, r_poster_redframe):
- A small poster (about 25% tall) with rounded corners and a white border (Avengers) or **red border** (Mary Poppins). Bottom-left or bottom-right.
- It **slides up** from below the frame and settles, with a slight tilt.
- It lasts about 2 s.
- **Trigger:** a film named in the clip speech ("…playing Mary Poppins?").

## 8. Speed lines
r_speed_lines, r2op 12 s, 17 s, 20 s.
- Black-and-white manga radial lines at the frame edges around a laughing face. Each lasts 0.7-1.0 s, often with a pop on top.
- Used in hook montages and on big laughs.

## 9. Flash, whip, framing
- **White flash:**
  - Full white for 2-6 frames (about 0.2 s). Peak luma is 255.
  - **Where it goes:**
    - in story compilations: once, between the hook montage and the first clip (r2op 24.8 s);
    - in blooper reels: between bloopers (JIM5 14, UjOJ 10, cGhj 3 at 6 fps), denser at the end.
  - **SFX:** a short bright camera or shutter hit, +17 dB in the >4 kHz band. It is the only element with a clear SFX.
- **Whip pan:** motion-blur between two clips, rare.
- **Digital punch-in** on the reacting face: a 1.3-1.6x jump cut with no animation.
- **Coloured border:** a cyan frame about 3% inset on one segment in r2op. Rare.
- **Split screen:** a thin red divider for video calls (B4rM). **Blur-fill** for vertical clips.
- **Logos:** the channel's own logo top-left (about 6%, here a faint goat). Network bugs are pixelated.

## 10. Sound
- **Loudness:** the whole video is about **-20 LUFS** integrated (UjOJ -19.9). Narration -20.6 to -22 LUFS. Clips -18 to -23 LUFS. Narration and clips are matched within about 2 dB.
- **Music:** a quiet bed about 13 dB under the narration (gap floor -36 to -39 dBFS vs voice p50 -24). **Out or nearly out inside clips** (floor -50).
- **SFX:**
  - **None measurable** on pops, labels, circles, arrows or posters: no >4 kHz transient at their onsets.
  - The laughs in the clips are the "SFX".
  - Only the white flash has a hit.

## 11. Pacing and structure
| Part | What the references do |
|---|---|
| **Cold open** | 6-10 s of ONE clip, the funniest moment, loaded with elements: captions, 2-4 pops, a "\*???\*" mark. r2op 0-10.5 s, UjOJ 0-8.4 s, B4rM 0-6 s. |
| **Hook** | **2-3 short sentences, 11-15 s**, over a **fast montage** (0.4-1.0 s shots) of laughing faces or the film's epic shots, with pops, speed lines and arrows on it. A **contrast formula**: "In the movies, the Avengers face the greatest threats… **But** when the cameras start rolling, even Marvel's mightiest heroes forget how to keep a straight face." It restates the title promise, does not explain, and goes straight to clip 1. |
| **Body** | Clip 1 starts by 20-25 s. |
| **Story video bridges** | One sentence, 4-6 s ("And during Jimmy Kimmel's acting class, Emily and John delivered…"). |
| **Blooper video segments** | One narrator line over the film's own shots + a film title card → the blooper with its own audio → a flash → the next. |
| **Clip choice** | Visible breaking (laughing, corpsing), swears (starred), slips, props failing, cast pranking each other, and cameos. Cut in on the setup line and out about 1-2 s into the laugh. Bloopers run 4-15 s. Story clips run 12-31 s. |
| **Shot pace** | Median 1.6-1.9 s. First 60 s at 35-42 cuts/min. |


## 12. Round 3 re-measurements (2026-10-14, pixel sampling + local face detector)
Faces were measured with YuNet (OpenCV DNN, local and free) on the same reference frames.

- **Font.** It is confirmed as Komika Axis. The owner's installed `KOMIKAX.ttf` carries this name table: "© 1999-2001 WolfBainX & Apostrophic Labs. All rights reserved", fsType 0 (installable).
  - The file has no licence text embedded.
  - Apostrophic Labs distributes it as freeware, but that readme is not in the file.
  - The font is NOT committed. The laptop renders use the installed copy. A Linux worker needs the owner to confirm the licence and place the file (`CELEB_FONT`). Otherwise it falls back to Bangers.
- **Pop text** (u 288.95 "MOTHERF\*\*\*", r 18.3 "HA HA HA"). There is no bright glow. The layers are:
  - fill #FFFF00 (255,254,0);
  - a thin black line (~2 px at 720p, 0.3 %);
  - a dark olive band #7D7608 → #79720A, about 11 px at 720p (1.5 %), with a ~3-4 px soft outer edge. Over a dark background it reads as a "yellow glow"; over skin it reads as a dark outline.
- **Name label.** White, with a thin black line and a soft dark drop shadow. It is 52 px tall incl. the line at 720p (7.2 %).
- **Circle** (u 736.3). The ring core is #FDFE00, **15 px at 720p (2.1 %)**. The outer glow is orange-yellow (163,133,4 just outside), fading over ~20 px (2.8 %).
  - Ring radius = 0.94 × the face box height (YuNet face 210×289 px, ring diameter 542 px).
  - The ring is centred on the face.
- **Yellow pointer** (u 564.65-565.5). Solid #FFFC00, 73×62 px at 720p (**8.6 % tall**).
  - The tip sits ~30 px (4 %) above the face box top.
  - It follows the head frame by frame.
  - Entrance: 88 px → 69 → 73 (125 % → 95 % → 100 % over 3 frames). There is no bob of its own.
- **Red 3D arrow** (r 13.55-13.89). Flat #FF0000, with a #990000 extruded right side 7-10 px (1.2 %).
  - Size: 233 px long at 720p (32 %); head 64 % of the length wide, shaft 30 %.
  - It leans 21° (tip up-left) and points at the face from the chest; the tip sits just under the chin and never covers the face.
  - Scale per frame (sqrt of mask area): 0.22, 0.47, 0.70, 0.89, 1.04, **1.10**, 1.077, 1.049, 1.026, 1.008, 1.0. It grows about its centre (the centre drifts < 6 px).
  - No wobble after it settles. It goes out on the camera cut (0.87 s).
