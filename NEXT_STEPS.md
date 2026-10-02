# Look & sound features: status (agent worktree agent-a3ebf96ceb0986600)

Branch base: origin/thumbgenius-video-worker @ 852196b. Suite: `cd runpod && SKIP_DOTENV=1 python -m unittest
discover -s tests -t .` (offline). Evidence files live in the session scratchpad (`polish/`, `grade/`).

## Done (committed)
- Narration polish (`src/voicepolish.py`, handler.do_render): measured, conditional ffmpeg chain; Lake Powell
  is clean (denoise skipped), gets high-pass + gentle compression; timing within 0.04 ms. VOICE_POLISH on.
- Grade (`src/grade.py`, `remotion/src/components/gradeMath.ts`, `Grade.tsx`, SceneClip): per-scene tone
  measured at plan/Replace Clip/render, medians frozen in doc.grade, documentary look; before/after sheet
  `grade/grade_sheet_documentary.jpg`. GRADE on.
- Ambience beds + soft riser: `scripts/build_ambience.py` (9 procedural seamless 60 s loops + riser-soft),
  `src/ambience.py` (planner), `remotion/src/components/ambienceMix.ts` + Main.tsx (renderer).

## Left / to check
- Ambience/risers default: needs the owner's ears (A/B files in `polish/amb_render/ab_*.mp3`).
- Render-level checks of the beds (level vs voice, split-render join, loop seam): `polish/amb_render.py`.
