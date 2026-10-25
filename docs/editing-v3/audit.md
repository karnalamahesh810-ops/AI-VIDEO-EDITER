# Editing v3: what makes a top edit, and where ours falls short (2026-10-25)

Scope: the automatic edit the worker makes (pacing, cuts, graphics, moves, sound). Sourcing quality (which clip is
found) is out of scope here except where it shows up as an editing symptom.

## 1. References measured

| Ref | Channel / niche | Views | How measured |
|---|---|---|---|
| `_Er7ORveNME` "The Slow, Painful, Greedy Death Of Angry Birds" | SunnyV2, business / internet story | 5.8 M | first 240 s at 360p, word-timed auto captions, 10 fps cut detector, contact sheets |
| `QpNJcAEI-Ts` "The Nazi Brothers Who Started Rival Shoe Companies" | MagnatesMedia, business history | 1.7 M | same |
| `CbUjuwhQPKs` "The Search For D. B. Cooper" | LEMMiNO, true crime / mystery | 24.5 M | same |
| 7 x Celebs Goat / SpideyParker (docs/style-refs/*/measure.json) | celeb compilation, fandom essay | 0.02-3.3 M | full length, earlier measurement |
| GTA 6 driving essay (docs/style-refs/gta6_driving/catalogue.md) | gaming essay | - | full, earlier catalogue |
| Nor'easter news compilation (memory: news-compilation-reference) | weather news | - | 340 labelled shots, earlier |

Samples are kept only in the session scratchpad (`ev3/refs/`), never in the repo. The cut detector
(`ev3/measure_ref.py`: colour-histogram + mean-difference at 10 fps) was calibrated on `6BQN3KQ9v0E`, whose cuts were
labelled before: 18 of its 20 labelled cuts in the first minute found, no false ones. On two more labelled refs it
counts 142 vs 104 and 88 vs 110 cuts in 240 s, so treat its counts as +-35 %; the comparisons below use the same
detector on our videos.

### Measured numbers (first 240 s)

| | SunnyV2 | Magnates | LEMMiNO | Ours: Mount Rainier (news_compilation) | Ours: "It rises 867 feet" (documentary) |
|---|---|---|---|---|---|
| visual changes / min, 0-30 s | 20 | 18 | 0 (one continuous animated scene) | 14 | 18 |
| visual changes / min, after 120 s | 15 | 11 | 1 | 16 | 16.5 |
| shots under 2 s | 53 % | 47 % | 0 % | 30 % (mostly dissolve halves) | 22 % |
| time in shots over 8 s | 52 % | 68 % | 99 % | 24 % | 0 % |
| shot length p10 / median / p90 | 0.3 / 1.75 / 10.2 s | 0.3 / 2.2 / 13.6 s | long takes | 0.3 / 4.3 / 7.6 s | 0.4 / 3.9 / 6.3 s |
| cuts on a word start (chance) | 92 % (80 %) | 78 % (71 %) | - | - | - |

Whole-video numbers for ours, from the saved timelines:

| | Mount Rainier b6cef117 (20.5 min) | Documentary 4a94f419 (15.4 min) |
|---|---|---|
| shots | 169, 8.2 / min | 198, 12.9 / min |
| shot p10 / median / p90 / max | 4.3 / 6.1 / 12.2 / 18.0 s | 3.0 / 4.4 / 6.6 / 8.8 s |
| time in shots over 10 s | 403 s = 33 % (29 shots) | 0 |
| stills on screen | 770 s = 63 % (median hold 7.6 s) | 621 s = 67 % |
| cuts per minute, by minute | 12, 8, 10, 10, 9, 9, 8, 10, 6, 5, 4, 5, 10 ... | 12-14 every minute (flat) |
| first 30 s | 6 shots (5 s each: no faster than the body) | 7 shots (same as body) |
| graphics | 38 = 1.9 / min; gaps of 78 s and 93 s with none | 60 = 3.9 / min |
| random texture effects on clips | 46 scenes (colour-shift 16, light-leaks 15, film-flicker 8, dust 7) | 46 scenes |
| emphasis moves (punch-ins on a word) | 0 | 0 |
| sounds | 21, all on Smart Editor graphics; nothing else | (not measured: DB quota) |

### What the references do (contact sheets `ev3/refs/*/sheet_hook.jpg`, `sheet_mid.jpg`)

- **Something changes on the spoken word every 2-5 s.** It is a cut (SunnyV2, Magnates), a label or highlight that
  appears exactly as the word is said (LEMMiNO: name tags pop on each name, quote text with the key words in red;
  SunnyV2: article lines highlighted as they are read), or a camera move inside a designed scene. LEMMiNO barely cuts
  (1 cut / min) yet is never static.
- **Bimodal rhythm, not a metronome.** Half the shots are under 2 s (bursts on lists, names, montages) and the long
  holds are carried by motion or a graphic building. Ours sit in one narrow band (4-7 s) every minute.
- **The hook is denser.** 18-20 changes / min in the first 30 s against 11-15 later. Ours is flat (or slower).
- **Nothing sits still.** Every still and document is pushed or slid (SunnyV2 pushes every screenshot; Magnates
  composites cut-outs with parallax). A still held 15-18 s with one slow move does not exist in any reference.
- **One type system, one accent.** LEMMiNO: one mono face, red as the only accent. SunnyV2: one condensed face for
  dates/quotes, highlight colour per video. Magnates: one bold grotesk.
- **Texture is a whole-video grade, never per clip.** No reference adds a light leak, flicker or hue wobble to
  one random modern clip.
- **Transitions are rare and motivated** (Magnates: a paper tear into a flashback, fire into a disaster beat).
  The smooth-cuts branch (b46aabc) already covers this; this work leaves transitions alone.

## 2. The rubric

Each item is scored 0-10 by a judge from frames and the timeline numbers; the measurable targets come from the
references above.

| # | Item | Target (measured) | How we measure it |
|---|---|---|---|
| R1 | Pacing and shot variety | no shot over ~8 s without motion or a build; shots under 2.5 s present (10-20 %); p90/p10 spread >= 3 | timeline shot list |
| R2 | Hook density | first 30 s at least 1.3x the body's visual changes | events / min 0-30 s vs rest |
| R3 | Cuts on words | cuts land just before a word start, preferably after a pause | cut vs word starts |
| R4 | B-roll matches the words | the named thing on screen when named | (sourcing; not changed here) |
| R5 | Graphics land on their word, readable, on brand | appear on the word (+-0.3 s), never two figures at once, no label overlapping a number, one type system | overlay timing vs words, frame check |
| R6 | Emphasis moves | a punch-in or push on key words (figures, superlatives, turns), 1-3 / min, never mechanical | keyframes on emphasis words |
| R7 | Transitions smooth and motivated | (fix/smooth-cuts) | - |
| R8 | Sound design | a hit or soft whoosh under each graphic entrance and each move, under the voice at the owner's levels (SFX 0.4, music 0.5) | sfx rows vs events |
| R9 | Pattern interrupts | something new at least every 20-40 s (graphic, move, change of picture type) | longest gap between events |
| R10 | Colour and texture consistency | one grade; no per-clip hue wobble, flicker or leak on modern footage | scene effects |
| R11 | Text restraint | no repeated caption of the same fact; text only for what is said | duplicate text within 4 min |

## 3. Top gaps, ranked by viewer impact

1. **Static long holds (R1, R9).** In the Mount Rainier video, 33 % of the runtime sits in shots over 10 s, and
   stills take 63 % of the screen. Minutes 9-11 run at 4-5 cuts / min with stills held 15-18 s each (556-672 s:
   seven stills in a row). The shot cap could not find other footage ("refused 97", "held 41"), so it held.
   Viewers leave at stalls like these; no reference holds a still past ~8 s without building it.
2. **No emphasis on the words that matter (R6, R2).** Zero punch-ins or pushes timed to a word in 20 minutes. Figures,
   superlatives and turns ("but", "never", "forever") pass with the picture unchanged unless a graphic happens to
   be planned. The hook is no denser than the body.
3. **Duplicate and colliding graphics (R5).** About 6 of 38 graphics draw a figure that a full-screen number scene
   already shows on the same frames: "9,000" twice at 316 s, "40 MINUTES" against "~34" at 760 s, 913 s, 921 s,
   1180-1189 s. kt-number's unit overlaps its last digit ("14,410FT" at 1169 s): its box is sized by an estimated
   text width that under-measures heavy faces.
4. **Repeated text (R11).** "ALERT: NORMAL" is shown four times (536, 712, 854, 1139 s) and adds nothing after the first.
5. **Unmotivated per-clip texture (R10).** 46 of 169 scenes get a random colour-shift (an 8 degree hue wobble that
   fights the grade), light leak, flicker or dust on modern drone footage, cycled the way VidRush does it. It breaks
   colour consistency and reads as a template.
6. **Long gaps with nothing new (R9).** No graphic for 78 s (132-210 s) or 93 s (536-629 s), and no other event
   (a move or a picture-type change) in between.
7. **Sound design is fine on graphics, absent elsewhere (R8).** Every look carries its own built-in sound
   (lookSoundPlan) and the 21 sfx rows sit on the Smart Editor graphics, all under the voice at the owner's 0.4. With
   no moves there is nothing else to hear; a new move needs its own soft sound (the owner's Premiere rule: a whoosh
   on every zoom).
8. **Text cards over the empty lines.** 8 red sentence cards (37 s) where sourcing found nothing. That is a
   sourcing outcome (fix/empty-spots, live d99e296), so it is not changed here.

## 4. What this branch builds (feature/editing-v3)

All in one pass, `src/editing.py`, after the graphics, grade, reframe and living photos are placed, with no network
and no AI calls (cost 0). Every change has a flag, default ON, and `EDITING_V3=0` (or job `"editing_v3": false`)
leaves the plan exactly as before.

| Flag | Fixes gap | What it does |
|---|---|---|
| `EDIT_V3_SPLIT_HOLDS` | 1 | A still held past the limit becomes 2-3 shots of the same photo cut on word boundaries (a pause or sentence end first), each later shot a detail framing aimed at the subject (the documentary "several shots from one photograph"). A long clip with spare footage continues forward in the file instead (a chain, no crop). |
| `EDIT_V3_HOOK_PACE` | 2 | The same split with a lower limit (5 s) in the first 30 s, so the hook cuts faster than the body. |
| `EDIT_V3_PUNCHES` | 2 | A punch-in (scale 1 to ~1.08 in 0.28 s, expoOut, held to the cut, motion blur) on the strongest emphasis word of a line: a figure, a superlative, a turn. 1-3 per minute, at least 7 s apart (4 s in the hook), never near a graphic's entrance, never on a clip a style keeps uncropped. Written as the editor's own keyframes, so the web editor can change or delete each one. |
| `EDIT_V3_INTERRUPTS` | 6 | No window longer than 30 s without an event: the best word in a quiet window gets a punch. |
| `EDIT_V3_PUNCH_SOUND` | 7 | A soft whoosh under each punch, through the same voice-relative levels as every other sound (SFX master 0.4 applies). |
| `EDIT_V3_HYGIENE` | 3, 4 | A graphic that sits over a full-screen graphic scene is dropped; a caption repeating an earlier one within 4 minutes is dropped. |
| `EDIT_V3_CLEAN_EFFECTS` | 5 | No colour-shift, light leak, flicker or dust on a clip unless the scene is treated as film / vintage / archival. |
| (renderer fix) | 3 | kt-number sizes its digit box from the real rendered text, so a unit never overlaps the last digit. |

Results, judge scores and the demo are in section 5 (filled in after the build).
