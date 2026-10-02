# Brand kit - worker (branch worktree-agent-a4e98829f4701ddda, on thumbgenius-video-worker 852196b)

## Done
- `runpod/src/brandkit.py`: reads `input.brand_kit` (identity + picks), scopes the picks for the
  planner, enforces them after planning, writes the renderer's `doc.brand`, prepares a render
  (checks the logo, measures intro/outro, frames + levels), frame layout, quality-scan offsets.
- Wired into handler, timeline.build, treatments side paths, marks, quality, fanout (split render
  in composition frames; seams = clean cuts; never a cut inside a brand clip).
- Renderer: `remotion/src/components/brand/*`, Main.tsx (Body + brand Sequences), Root.tsx
  (intro + body + outro), types.ts BrandBlock, accentFor "accent2".
- `remotion/src/templates/editor_only.json` + `scripts/write_editor_only.py` for the app's picks grid.
- Tests: tests/test_brand_kit.py (48); full suite 1336 OK. Real Remotion render checked
  (intro, watermark, end card; split into 3 chunks at the seams, joined = 330/330 frames).

## For the lead
- Merging with the pro-looks branch: templates.py `for_cue` / `for_component` lines conflict;
  keep both checks: `not banned(t["id"]) and auto_pick(t)` (auto_pick is the same function).
- After merging registry changes, if test_the_editor_only_list_is_current fails:
  `python scripts/write_editor_only.py`.
- Deploy the image before the app sends kits (chunk workers refuse a different renderer).

Tests ONLY as: `cd runpod && SKIP_DOTENV=1 python -m unittest discover -s tests -t .`
