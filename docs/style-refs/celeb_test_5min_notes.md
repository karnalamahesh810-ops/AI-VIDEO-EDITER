# Celeb style, 5-minute test (2026-10-14): Spider-Man bloopers

## Files
- `celeb_test_5min.mp4`: 4:34, 1080p30, -19.8 LUFS (the reference is -19.9).
- `celeb_test_5min_phone.mp4`: 720p, 23 MB.
- `celeb_ref_vs_ours_20s.mp4`: Celebs Goat on the left, ours on the right. It shows 5 elements: pop, name label + circle, film title card, hook montage, captions.
- `celeb_test_5min_script.txt`: the script, written by Claude (no paid model was used for any text).
- `celeb-elements.md` + `celeb-elements/`: the element catalogue the build follows.

## Structure (as in the references)
1. **Cold open:** 10.4 s of the best moment ("I'm Spider-Man." / "F\*\*\*ing knew it.") with its caption, a starred pop and the bleep.
2. **Hook:** 2 sentences, about 13 s, over a fast laugh montage (0.8-1.0 s shots) with "HA HA HA" / "OMG..." pops, speed lines and a red 3D arrow. Then a white flash.
3. **Body:** 16 bloopers, each preceded by a one-sentence bridge over that film's own footage.
   - The clip's picture leads its sound by 1.2 s.
   - Each blooper plays with its own audio.
   - A white flash and camera hit follow every blooper.
   - A film title card (poster scale-in, then the title wipes out of it) appears at each new film: Far From Home, No Way Home, Brand New Day.
4. **Outro:** one line.

## Sources: official studio reels only, all 1080p
None of these sources has a third-party watermark or burned-in captions. Letterbox bars are cropped automatically.
- **QteOt8XAbIY:** Sony Pictures at Home, "SPIDER-MAN: FAR FROM HOME – Full Official Gag Reel".
- **XG_CimbpVMQ:** the official Spider-Man channel, "Gag Reel | Spider-Man: No Way Home". The reel's own bleeps are kept.
- **zDkwGerxWfE:** JoBlo Behind-the-Scenes, "SPIDER-MAN: BRAND NEW DAY Bloopers, Gag Reel (2026)". It is studio material, and our tool bleeps the uncensored swears.
- **Rejected:**
  - The Infinity War reel (rYG04EYvP08): it has burned-in timecode text.
  - Fan compilations: watermarks or re-edits.

## Rights log (source in → out, place in our video)
| Video | Source | In-out (s) | Length | In ours |
|---|---|---|---|---|
| zDkwGerxWfE | https://www.youtube.com/watch?v=zDkwGerxWfE | 15.00-25.40 | 10.4 s | 0.0 (cold open) |
| QteOt8XAbIY | https://www.youtube.com/watch?v=QteOt8XAbIY | 67.40-87.40 | 20.0 s | 23.7 |
| QteOt8XAbIY | same | 138.95-148.80 | 9.9 s | 48.1 |
| QteOt8XAbIY | same | 185.20-192.69 | 7.5 s | 61.7 |
| XG_CimbpVMQ | https://www.youtube.com/watch?v=XG_CimbpVMQ | 12.10-23.00 | 10.9 s | 74.3 |
| XG_CimbpVMQ | same | 84.35-95.58 | 11.2 s | 87.4 |
| XG_CimbpVMQ | same | 32.50-41.36 | 8.9 s | 101.5 |
| XG_CimbpVMQ | same | 71.30-79.90 | 8.6 s | 113.6 |
| XG_CimbpVMQ | same | 105.25-117.30 | 12.0 s | 125.8 |
| XG_CimbpVMQ | same | 126.27-143.85 | 17.6 s | 141.3 |
| XG_CimbpVMQ | same | 41.60-52.42 | 10.8 s | 162.5 |
| XG_CimbpVMQ | same | 166.43-174.58 | 8.2 s | 177.1 |
| XG_CimbpVMQ | same | 183.20-202.40 | 19.2 s | 189.0 |
| zDkwGerxWfE | same as above | 4.00-25.40 | 21.4 s | 213.5 |
| zDkwGerxWfE | same | 38.42-46.16 | 7.7 s | 238.7 |
| zDkwGerxWfE | same | 70.35-90.50 | 20.2 s | 249.2 |

The hook montage also uses 0.8-1.0 s laugh shots from XG_CimbpVMQ and QteOt8XAbIY.

## How the clips were checked
- Every in and out point sits on a source shot cut, outside the reel's own white flashes, and on whole sentences (from the whisper word times).
- Every element's frame was looked at in grids: name circles land on the right face; I removed names where the person's face is hidden.
- Loudness was measured with ebur128 per section:
  - narration -19.7 to -19.9 LUFS;
  - clips -19.6 to -21.4 LUFS;
  - music 13 dB under the voice, 29 dB under inside clips.
- The 1 kHz bleep is confirmed in the spectrum at the uncensored word.

## Simplified for this test
- **Montage, names and pops come from the script.**
  - The laugh shots, name/pop times and hints (left/right/center) are written in the script.
  - Swear pops are automatic.
  - Faces come from one cheap vision call per element, about $0.0007.
  - Fully automatic picks (laugh detection, deciding who to name) are the next step.
- **Clips were cut from local copies.**
  - The full official reels (about 3-4 min each) were downloaded once, and whisper ran on them locally.
  - The worker's quote finder (search → captions → window download) was proven in the 1-minute test and was not re-run here.
- **The font is a stand-in.** Bangers is stretched to 130% to look like Komika Axis. Dropping the real Komika Axis file (freeware) into `src/celeb/fonts/` and setting `CELEB_FONT` switches to it.
- **Music.** Our AI "uplifting" bed. A playful bed would fit better.
- **Missing details.** No channel logo, no pixelation of network bugs (none appear in these sources), no poster pop-up on spoken film names.

## Cost
| Item | Cost |
|---|---|
| RunPod TTS, 17 lines (13, then 4 more; cached by text) | about 800 GPU-s, about $0.15. Mostly cold starts; the real work was 166 s. |
| OpenRouter face boxes, 95 calls over 4 renders | about $0.07 in total, now cached to disk so a re-render costs $0 |
| Rendering | local (base about 70 s, composite about 290 s for 4.5 min) |

**Per finished video:** about $0.04/min TTS when warm, plus $0.004/min of face calls, plus CPU render. This needs no LLM.
