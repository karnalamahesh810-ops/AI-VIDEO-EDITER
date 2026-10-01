# Brand kit - worker (branch of thumbgenius-video-worker)

## Done (committed)
- `runpod/src/brandkit.py`: parse/sanitise `input.brand_kit`, picks (looks, transitions with
  nearest-transition map, pack clips, music limit + nearest genre, sfx, density),
  `prepare_input`, `scope`, `closest_look`, `enforce`, `second_colour`, `doc_brand`, `meta`,
  `layout`/`total_frames`, `prepare_render`, `body_scan`.
- Wired: handler (prepare_input before styles.apply, scope around every action, enforce at the
  end of do_plan, prepare_render in do_render, duration incl. intro/outro), timeline.build
  (brand block, kit colour replaces the pack's, accent2 on charts, transitions, pack clips,
  music), side paths (archive tag, pack chapter/lower third, one-picture swap, marks, quality
  text scene), fanout (composition frames, seams as clean cuts, no cut inside intro/outro),
  quality.classify (body_scan).
- Renderer: components/brand (Watermark, BrandVideo, EndCard, brandLayout, brandFonts),
  types.ts BrandBlock, Root.tsx duration, Main.tsx Body + brand Sequences, accentFor "accent2".
- tests/test_brand_kit.py (45 tests); full suite 1333 OK.

## Left
- A local Remotion render of a doc with intro + watermark + end card (PowerShell, not Bash) to
  look at the frames.
- After merge: copy remotion/src to the app (src/remotion) - the app branch already carries a
  copy of these files.

Run tests ONLY as: `cd runpod && SKIP_DOTENV=1 python -m unittest discover -s tests -t .`
