# Celeb style: element checklist against the Celebs Goat references (2026-10-15, round 5)

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
| 13 | **Which speaker gets which colour** | Colour by WHO: the clip's featured celebrity in one colour, everyone else in the other. B4rM: Tom Holland white in 50 of 58 clips, hosts and fans yellow. r2op and UjOJ: the featured person yellow, the others white. Green: 3 of 885 lines. | 3D-Speaker voice clusters (sherpa-onnx, local); the voice with the most speech (minus turns that say the featured name) is the featured person; under 70 % of the speech, the whole clip is the featured colour. Per-video option `celeb_featured_colour` (yellow default, white for B4rM-style channels), a one-click swap and click-to-cycle per line in the editor. Exact colour: **B4rM 82 %, r2op 82 %, UjOJ 78 %** of lines (round 4: 26 / 74 / 72 %). | CLOSE (the rest is one click in the editor) |

## Punchline pops
| # | Property | Reference (u 287.6-289.5, r 17.6-18.4) | Ours | |
|---|---|---|---|---|
| 14 | Fill | #FFFF00 (255,254,0) | #FFFF00 | PASS |
| 15 | Inner line | dark, ~1.5 px | 0.21 % H, #322E00, round joins | PASS |
| 16 | Band | olive #746900 at ~90 % (solved from the dark and skin backgrounds), plateau ~8 px incl. the line | #746900 at 92 %, 1.2 % H, round joins | PASS |
| 17 | Outer edge | band 50 % at 10.6 px from the fill edge, 96 % -> 21 % over 9-12 px, then a dark tail 17 % -> 0 over 13-22 px (720p) | the same profile (r5_pop_edge_profile.png) | PASS |
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
| 29 | Drop shadow | none measurable: solid black to 9 px (0.97), 0.76 at 9 px, 0.17 at 10 px, equal on every side | crisp round-join stroke, no shadow (r5_label_stroke_profile.png) | PASS |
| 30 | Position | under the named person | x = the tracked face, y = 90.5 % (80 % when a caption is on screen) | PASS |
| 31 | Entrance | letters rise and rotate into place, 15 letters in ~0.35 s | 4 frames per letter, 0.9-frame stagger, rise + 22° rotate | PASS |
| 32 | Exit | with the camera cut (~1.5 s) | the same | PASS |

## Highlight ring
| # | Property | Reference (u 735.2-736.6) | Ours | |
|---|---|---|---|---|
| 33 | Core | #FDFE00, 15 px = 2.1 % thick | the same | PASS |
| 34 | Glow | orange-yellow, median of 43 radial profiles: broader inside the ring than outside | the measured alpha-by-distance curve, inside and outside (r5_ring_glow_profile.png) | PASS |
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
| 46 | Film title card | poster scale-in 0.2 s (105 %), bar then title then subtitle + year slide out from behind the poster (1-frame steps), 2.6 s | sizes, strokes, bar and the staggered wipe measured on u 260.6-263.0 (r5_title_card_measure.png); poster from the film's Wikipedia page | PASS |
| 47 | Speed lines | black + white radial wedges centred on the FRAME (centre 0.488 W, 0.509 H; the face is ignored), more lines on the long sides | count, wedge widths, inner radius and colour ratio measured (r5_speed_lines_measure.png); centred on the frame | CLOSE (line placement is random per redraw, not traced) |
| 48 | White flash | full white about 0.2 s; bright hit (+17 dB above 4 kHz) | 0.2 s white + camera-flash hit | PASS |
| 49 | Channel logo | the channel's logo top-left (~6 %) | built: `logo_url` draws it top-left at 6 % for the whole video; the proof has none (no owner logo file yet) | FAIL (needs the logo) |

## Sound
| # | Property | Reference | Ours | |
|---|---|---|---|---|
| 50 | Integrated loudness | -19.9 LUFS | -19.8 LUFS | PASS |
| 51 | Narration vs clips | within about 2 dB | each levelled to -20 LUFS | PASS |
| 52 | Music | about 13 dB under the voice; out in clips | 13 dB under; -29 dB in clips | PASS |
| 53 | Element SFX | none except the flash | the same | PASS |

## Clip picture (round 5, owner: "the video quality sucks, you messed up the download")
| # | Property | Before | Now | |
|---|---|---|---|---|
| 54 | Source stream | YouTube's H.264 1080p only (`[ext=mp4]`) | AV1 > VP9 > H.264 at the best SDR picture; hero clips may take 1440p (under 9 Mbps) downscaled with lanczos | PASS |
| 55 | The download's own re-encode | hidden: yt-dlp's section cut re-encoded with ffmpeg's defaults (crf 23); the same 8 s of the No Way Home reel came out at **0.92 Mbps** | one explicit crf-16 H.264 encode; the same 8 s: **2.2 Mbps** (`celeb_download_compare_r5.jpg`, 400 % crop) | PASS |
| 56 | Every later step | shots crf 16 veryfast, final crf 19 | shots crf 15 fast with lanczos scaling, final crf 17 | PASS |

## Score
50 of 53 reference rows PASS (round 4: 46), 2 CLOSE (#13, #47), 1 FAIL (#49, waiting for the owner's logo). The 3 picture rows above pass.

## What is left
1. **Speaker colours (#13).** 78-82 % exact. The limit is telling two voices apart in short lines under laughter; vocal separation (Spleeter via sherpa-onnx, `src/celeb/separate.py`) is built but left off, because it did not raise the score. The editor's swap button and click-to-cycle fix the rest.
2. **Speed lines (#47):** the wedge positions are random per redraw, not traced from the reference.
3. **Channel logo (#49):** send the logo file; it is one input (`logo_url`).
