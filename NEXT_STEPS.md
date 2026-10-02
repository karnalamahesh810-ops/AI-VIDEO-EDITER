# Look & sound features: status (agent worktree agent-a3ebf96ceb0986600)

Branch base: origin/thumbgenius-video-worker @ 852196b. Suite: `cd runpod && SKIP_DOTENV=1 python -m unittest
discover -s tests -t .` (offline): 1334 tests OK (5 skipped). Evidence lives in the session scratchpad
(`polish/`, `grade/`). Nothing pushed or deployed.

## Done (committed)
- Narration polish (`src/voicepolish.py`, handler.do_render). VOICE_POLISH on.
- One grade per video (`src/grade.py`, `remotion/src/components/gradeMath.ts`, `Grade.tsx`, SceneClip,
  fanout.chunk_hash). GRADE on (documentary). Sheet: `grade/grade_sheet_documentary.jpg`.
- Ambience beds + soft riser (`scripts/build_ambience.py`, `src/ambience.py`,
  `remotion/src/components/ambienceMix.ts`, Main.tsx). AMBIENCE and RISERS off by default.

## For the owner
- Listen to `polish/amb_render/ab_60_without.mp3` vs `ab_60_with.mp3` (Lake Powell 1:00-2:00, the
  planner's own beds and riser). If better: set AMBIENCE=1 and RISERS=1 on the endpoint, or try one job with
  `"config": {"AMBIENCE": 1, "RISERS": 1}`. Too quiet: the document's `ambience.level` 2 (= +6 dB).
- The app's editor does not show `doc.grade` or `doc.ambience` yet (they ride along in scene_data).
