# Look & sound features: status (agent worktree agent-a3ebf96ceb0986600)

Branch base: origin/thumbgenius-video-worker @ 852196b. Baseline suite: 1288 tests OK (8 skipped), 92 s
(`cd runpod && SKIP_DOTENV=1 python -m unittest discover -s tests -t .`).

## Done (WIP, not yet wired into the render)
- `runpod/src/voicepolish.py`: narration analysis (loudness/LRA/true peak via ebur128, per-frame noise
  floor with a pause-cluster reliability check, rumble, sibilance) in ~5 s for an 18-minute narration;
  `plan()` picks steps (highpass / afftdn denoise / split-band de-ess / gentle compression / dynaudnorm
  leveling), `polish()` runs them, matches the original loudness, verifies length, loudness, peaks and
  timing (cross-correlation lag <= 1 ms), and keeps the original on any failure. `for_render(doc, work)`
  points doc.audio.url at the cleaned FLAC and writes doc.meta.voicePolish.
- `runpod/src/config.py`: VOICE_POLISH (default on), VOICE_POLISH_SECONDS.
- Calibration (scratchpad `polish/`): Lake Powell narration = -22.2 LUFS, LRA 3.3, TP -1.4, noise floor
  -63 dBFS (41 dB under the voice: clean, denoise skipped). Degraded copies (noisy, harsh, rumble, uneven,
  cheapmic) trigger the right steps once the thresholds below are tuned.

## Left
1. voicepolish: hum detection as tonal 50/60 Hz peaks (`humProminence`, plus notches on harmonics);
   select speech frames by the 300-3000 Hz band; run `polish()` on the variants + Lake Powell, record
   before/after (noise floor, SNR, sibilance, LRA, lag); call `voicepolish.for_render` in
   handler.do_render after `_preflight_media` (before `_draw`); tests (tests/test_voice_polish.py).
2. Grade: `doc.grade` {preset, strength}; per-scene tone stats measured at plan time (and for scenes
   without them at render, budgeted); SVG feColorMatrix/feComponentTransfer filter per scene in
   SceneClip (sRGB, no crushed blacks); presets neutral / documentary / warm-doc / cool-news / archival;
   include grade + tone in fanout.chunk_hash; before/after sheet from the Lake Powell media.
3. Ambience + risers: procedurally synthesized loopable beds in remotion/public/sfx (amb-*.mp3,
   sfx_meta.json both copies, LICENSE.txt note); planner (scene words/visuals -> one bed at a time,
   fades across cuts, none on graphics-only scenes, ducked under speech); risers (sfx rows kind "riser")
   before the strongest reveals; `doc.ambience` {enabled, level, beds}; config flags.
