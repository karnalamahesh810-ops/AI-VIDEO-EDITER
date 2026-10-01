# Brand kit - worker (branch of thumbgenius-video-worker)

## Done
- `runpod/src/brandkit.py`: parse/sanitise `input.brand_kit` (colours, font, caption style,
  watermark, intro, outro, picks), picks helpers (looks, transitions + nearest-transition map,
  pack clips, music limit + nearest genre), `prepare_input`, `scope`, `closest_look`,
  `enforce` (post-plan swap/drop, animation scenes -> gapfill last resort), `second_colour`,
  `doc_brand`, `meta`, `layout`/`total_frames`, `prepare_render` (fetch + check + ffprobe +
  loudness of brand files), `body_scan` (quality scan offsets).
- `templates.py`: `banned()` honours the kit's allowed looks (ContextVar), `only()`,
  `banned_always()`, `auto_pick()`; `for_cue`/`for_component` use `banned()`.
- `treatments.py`: `keep_clear(corner)` so compact figures avoid the watermark corner.

## Left
1. Wire it: handler (`brandkit.prepare_input` before `styles.apply`; `scope` around
   plan/build/resource/render; `enforce` + `doc.meta.brandKit` at the end of `do_plan`;
   `prepare_render` in `do_render`; result duration = `brandkit.total_frames`).
2. `timeline.build`: `doc["brand"] = doc_brand(kit)`, pack theme -> "accent" when the kit has a
   colour, `second_colour`, `limit_transitions`, pack clips limited (`plan_pack_transitions`
   allowed set), `_bgm_for` uses `music_limit`/`pick_music`.
3. Side paths: `_archive_tag` fallback, `_from_hint` chapter/lowerThird, marks, quality TEXT_LOOKS.
4. fanout: `chunk_cuts`/`plan_chunks`/`chunk_hash`/`_localize`/`render`/`render_pod` in
   composition frames (intro offset, intro end + outro start as clean cuts).
5. quality.classify: `body_scan` first.
6. Remotion: types.ts BrandBlock, Root.tsx duration (+intro+outro), Main.tsx body Sequence +
   Watermark + BrandIntro + BrandOutro (components/brand/*), `accentFor` "accent2".
7. Tests (picks honoured, empty picks safe, intro/outro timing, watermark props, TS/Py contract).

Run tests ONLY as: `cd runpod && SKIP_DOTENV=1 python -m unittest discover -s tests -t .`
