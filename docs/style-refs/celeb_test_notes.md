# Celeb compilation: 1-minute test (2026-10-14)

## Files
- `celeb_test_1min.mp4`: generated voice (our Qwen3 TTS, preset doc-male), 60.5 s at 1080p30.
- `celeb_test_1min_phone.mp4`: 720p, 22 MB.
- `celeb_test_1min_uploaded_vo.mp4`: the same script with an "uploaded" voice-over.
  - The upload was a single take (energetic preset). It included one quote read aloud by mistake.
  - The tool aligned the take to the script, cut it at the clip spots and dropped the stray quote.
- `celeb_test_script.txt`: the script as the owner would paste it.
- Code: worker branch `feature/celeb-style`, worktree `C:\ThumGenius-celeb`, `runpod/src/celeb/`. Not deployed.

## Clips used (rights log)
Both clips were found by the tool. Each sits inside narration.

| # | Source | In → out | Length | How it was found |
|---|---|---|---|---|
| 1 | Jimmy Kimmel Live, "Cast of Avengers: Infinity War Reveals Least Trustworthy Avenger": https://www.youtube.com/watch?v=eIp7PYuAu0k | 2:14.08 → 2:26.24 | 12.2 s | Search from who + show + quote. Captions matched at 0.97, whisper at 1.00. |
| 2 | The Tonight Show, "Instant Spoilers with Tom Holland": https://www.youtube.com/watch?v=cocE4mUbc7A | 0:44.42 → 0:55.98 | 11.6 s | The URL was pasted in the script with no times. Captions found the quote. |

The cold open (7.2 s) comes from clip 2. B-roll during narration comes from the same two videos, from footage just around each moment.

The quotes were verified in the real captions: "I was reading what I thought was a fake script, because it was like Spider-Man's in space … it was real", and "I realized I just read out the title of the film".

## What is real (the worker code)
- **Script parser.** `[CLIP: who | "quote" | where | 12-20s | label=… | cold=1]`, or `url=… start=… end=…`.
- **Quote finder.**
  - YouTube search through our proxies, with official shows ranked first.
  - json3 caption word times and a fuzzy quote match.
  - A download of only a padded window, with audio. Footage downloads are silent, so a new `audio=True` option was added to `ytdlp._yt_fetch`.
  - Whisper word times inside that window.
  - The in point snaps to the setup sentence. When a moment is too short, it grows by whole sentences towards 12 s: forward when the speaker runs straight on, back to the setup otherwise.
  - The out point is the end of the sentence plus the laugh tail. The tail never runs into the next word.
- **J-cut.** The clip's picture starts 2.5 s before the narrator stops, muted, with its label. The clip's own sound starts about 0.19 s after the narrator's last word.
- **Mix.**
  - Narration and every clip are measured and set to -16 LUFS. The short-term level across the whole video holds at -15 to -17.
  - 60 ms fades on clip audio.
  - Music at 0.5 × 0.8 under narration and 0.5 × 0.18 inside clips, with a 0.3 s ramp down and a 0.5 s ramp up.
- **Look.**
  - Yellow comic captions (Bangers, OFL) on a black rounded pill, on clip speech only.
  - A white comic label bottom-left with a yellow bar.
  - A 100→104% push-in over each clip.
  - A 0.2 s white flash with a shutter at 40%, after the cold open and between segments.
  - No pops.
- **Uploaded voice-over.** Whisper, then difflib alignment to the narration blocks, then cuts snapped to silences.
- **Tests.** 10 offline tests in `tests/test_celeb.py`.

## What is simplified (for this test only)
- **Rendering.** The render is ffmpeg (`src/celeb/compose.py`), not Remotion or the app editor. Wiring the style into timeline.py and the editor is next.
- **No face check yet.** No vision call was made. Both clips were checked by eye.
- **Music.** Our own AI "uplifting" bed from the GPU-tools test. A playful bed would fit the style better.
- **Missing details.** No channel logo, no pixelation of network bugs (the "abc" bug is visible), no vertical blur-fill (both sources are landscape), and no punchline pop.
- **Captions clash with the source.** Fallon's video has its own burned-in captions and scoreboard bar, and our pill sits on top of them. The fix is to detect burned captions and lift ours.
- **B-roll.** It comes only from the clip's own source video. There is no wider celebrity montage (red carpet and so on), so with only 2 sources the outro reuses footage.

## Cost
| Item | Generated-voice video | Upload proof |
|---|---|---|
| TTS on RunPod | 186 GPU-s, about $0.04, mostly cold start (3 jobs, 58 s of real work) | 160 GPU-s, about $0.03 |
| OpenRouter | $0 (no LLM or vision calls) | $0 |

Downloads were about 60 MB through proxy #2 and up. Whisper, the render (about 30 s per minute) and the phone copy ran locally.

**In production:**
- about $0.01–0.04 TTS per minute of video (narration is about 50% of this test; about 20% in a full-length video);
- about $0.003 CPU render per minute;
- about $0.001 per face-check candidate once that is built.

**Total spent:** RunPod about $0.07, OpenRouter $0.
