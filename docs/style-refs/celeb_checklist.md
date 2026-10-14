# Celeb style: element checklist against the Celebs Goat references (2026-10-14, round 4)

**How each item was measured:**
- Numbers are px on the 1280x720 references (and % of frame height H), sampled pixel by pixel from the reference frames in `celeb-elements/`.
- "Ours" is the code in `runpod/src/celeb/fx.py` and `reel.py`, compared with `scripts/celeb/zoom_compare.py`.
- The visual proof is `celeb_zoom_compare_400.png` (reference left, ours right, 400 %).

**Verdicts:**
- **PASS:** matches within about 1 px at 720p, or within 1 frame.
- **CLOSE:** the same look, with a small difference still visible at 400 %.
- **FAIL:** not done, or wrong.

## Font
| # | Property | Reference | Ours | |
|---|---|---|---|---|
| 1 | Typeface for ALL text (captions, pops, labels, title cards) | Komika Axis | Komika Axis (`KOMIKAX.ttf`, the owner's installed copy) | PASS |
| 2 | Letter spacing | the font's own | the font's own (the extra tracking was removed) | PASS |

## Clip captions
| # | Property | Reference | Ours | |
|---|---|---|---|---|
| 3 | Box | #000000, 100 % opaque | the same | PASS |
| 4 | Box height | 78 px = 10.8 % | 10.8 % | PASS |
| 5 | Padding | 27 px = 3.8 % on every side | 3.8 % | PASS |
| 6 | Corner radius | ~12 px = 1.7 % | 1.7 % | PASS |
| 7 | Position | box bottom 10 px above the frame edge, centred | bottom at 98.6 %, centred | PASS |
| 8 | Text size | cap 27 px = 3.75 % | 3.75 % | PASS |
| 9 | Text colours | yellow #FCFF04; white #FFFFFF for another speaker; green #31FF03 rare (r2op cold open) | the same three colours | PASS |
| 10 | Stroke / glow | none | none | PASS |
| 11 | Motion | hard cut in and out, no fade | the same | PASS |
| 12 | Chunking | 1-6 words; breaks at punctuation, pauses and camera cuts | the same | PASS |
| 13 | **Which speaker gets which colour** | B4rM: the featured celebrity (Tom) white, the hosts and fans yellow. UjOJ: first voice yellow, second white. r2op: John yellow, Emily green in the cold open; otherwise mostly yellow. | Local diarization: WeSpeaker ResNet34 via sherpa-onnx, free, CC BY 4.0. Grouped by speaker turn and colour-coded by order of voice. **Accuracy is low on these clips**: music and laughter sit under every line, so two actors score 0.78-0.96 cosine. On B4rM, exact colour agreement is 17-20 of 47 lines. | **FAIL (accuracy)** |

## Punchline pops
| # | Property | Reference (u 287.6-289.5, r 17.6-18.4) | Ours | |
|---|---|---|---|---|
| 14 | Fill | #FFFF00 (255,254,0) | #FFFF00 | PASS |
| 15 | Inner line | dark, ~1.5 px | 0.21 % H, #322E00, round joins | PASS |
| 16 | Band | olive #746900 at ~90 % (solved from the dark and skin backgrounds), plateau ~8 px incl. the line | #746900 at 92 %, 1.2 % H, round joins | PASS |
| 17 | Outer edge | soft, ~3-5 px to zero | 0.15 % H Gaussian | CLOSE (ours is a touch softer) |
| 18 | Size | "M" 71 px tall at +10 % grow; word width/height 7.8 | cap 9.2 % H; width/height 7.72 | PASS |
| 19 | Position | under the speaker's chin, follows them | YuNet face track, centre 0.78 face-heights below the face centre, kept above the captions | PASS |
| 20 | Tilt | about -6° to +6° | random ±5° | PASS |
| 21 | Entrance | one glyph per frame, each about 3 frames small → big → settle; 12 glyphs in 0.37 s | 1-frame stagger, scale 0.45 → 1.15 → 1.0 over 3 frames | PASS |
| 22 | Hold | the word grows ~10 % over ~1.3 s | +12 % over the element | PASS |
| 23 | Exit | hard cut on the camera cut | ends on the next cut (dropped if under 0.5 s) | PASS |
| 24 | Sound | none measurable (>4 kHz band flat at onset) | none | PASS |
| 25 | When | swears (starred) and laughs; 1 per 20-40 s, denser in hooks | auto on every swear word; script `pop=` for laughs | PASS |

## Name label
| # | Property | Reference (u 735.1-736.7) | Ours | |
|---|---|---|---|---|
| 26 | Fill | #FFFFFF | #FFFFFF | PASS |
| 27 | Size | white rows 53 px = 7.4 % | cap 7.4 % | PASS |
| 28 | Black outer stroke | 8.5-10 px at 720p (16-19 % of the cap), round joins | 19 % of the cap, round joins | PASS |
| 29 | Drop shadow | black reaches 12 px under the letters (stroke + ~3-4 px drop) | stroke grown 45 %, offset down, 90 % opacity | CLOSE |
| 30 | Position | under the named person | x = the tracked face, y = 90.5 % (80 % when a caption is on screen) | PASS |
| 31 | Entrance | letters rise and rotate into place, 15 letters in ~0.35 s | 4 frames per letter, 0.9-frame stagger, rise + 22° rotate | PASS |
| 32 | Exit | with the camera cut (~1.5 s) | the same | PASS |

## Highlight ring
| # | Property | Reference (u 735.2-736.6) | Ours | |
|---|---|---|---|---|
| 33 | Core | #FDFE00, 15 px = 2.1 % thick | the same | PASS |
| 34 | Glow | orange-yellow (163,133,4 just outside), ~20 px falloff, both sides | #FFC800, 2.8 % falloff | CLOSE (the reference glow is a little broader inside the ring) |
| 35 | Radius / centre | 0.94 × the face-box height; centre about 0.1 face-widths left of the face centre (head turning) | 0.94 × the face height, centred on the tracked face | PASS |
| 36 | Draw-on | clockwise from 7 o'clock, closes in 0.6 s, ease-out | the same | PASS |
| 37 | Tracking | follows the head | YuNet frame by frame, smoothed | PASS |

## Pointer triangle
| # | Property | Reference (u 564.65-565.5) | Ours | |
|---|---|---|---|---|
| 38 | Colour / size | #FFFC00, 73×62 px = 8.6 % tall | the same | PASS |
| 39 | Position | tip 30 px (4 %) above the face box | the same, tracked | PASS |
| 40 | Entrance | 88 → 69 → 73 px (125 % → 95 % → 100 %) | 125 % → 110 % → 100 % | PASS |

## Red 3D arrow
| # | Property | Reference (r 13.55-14.42) | Ours | |
|---|---|---|---|---|
| 41 | Colours | face #FF0000, extruded right side #990000, 7-10 px | the same, 1.2 % H | PASS |
| 42 | Shape | length 233 px = 1.03 face-heights, head 64 %, shaft 30 %, lean 21° | the same | PASS |
| 43 | Placement | tip 0.27 face-widths right of the face centre, 0.22 face-heights under the chin; never on the face | the same | PASS |
| 44 | Entrance | scale per frame 0.22 .47 .70 .89 1.04 1.10 1.077 1.049 1.026 1.008 1.0, about its centre | the same curve | PASS |
| 45 | Hold / exit | no wobble, out on the cut (0.87 s) | the same | PASS |

## Other elements
| # | Property | Reference | Ours | |
|---|---|---|---|---|
| 46 | Film title card | poster scale-in 0.2 s (105 % overshoot), title wipes out left in 0.4 s, 2.6 s total, white main title + grey outlined subtitle on a grey bar + small year | the same structure and timing | CLOSE (subtitle outline weight not pixel-matched) |
| 47 | Speed lines | black + white radial lines at the edges, 0.7-1 s | the same, re-drawn every 2 frames | CLOSE (line count and width not measured) |
| 48 | White flash | full white about 0.2 s; bright hit (+17 dB above 4 kHz) | 0.2 s white + camera-flash hit | PASS |
| 49 | Channel logo | the channel's logo top-left (~6 %) | not added (needs the owner's logo) | FAIL |

## Sound
| # | Property | Reference | Ours | |
|---|---|---|---|---|
| 50 | Integrated loudness | -19.9 LUFS | -19.8 LUFS | PASS |
| 51 | Narration vs clips | within about 2 dB | each levelled to -20 LUFS | PASS |
| 52 | Music | about 13 dB under the voice; out in clips | 13 dB under; -29 dB in clips | PASS |
| 53 | Element SFX | none except the flash | the same | PASS |

## What is left
1. **Speaker colours (#13).** This needs a stronger diarizer: vocal separation first (Demucs), then pyannote 3.1 (MIT; the HF model needs a free token and accepting its terms), on the GPU worker. A cheap alternative is to let the owner click a caption to flip its colour in the editor.
2. **Ring glow (#34), pop edge (#17) and label shadow (#29):** a last fine-tune at 400 %.
3. **Title card (#46) and speed lines (#47):** measure the remaining numbers.
4. **Channel logo (#49):** needs the owner's logo file.
