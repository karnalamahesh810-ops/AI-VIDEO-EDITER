# Render smart 2 (2026-10-18)

Branch `feature/render-smart-2` = `thumbgenius-video-worker` (b0c8cc7) + the unmerged
`feature/render-smart` (2026-10-09, 8 commits, builder died at the usage limit) + the fixes below.
Not deployed. Design notes of the cache itself: `docs/render-cache.md`.

## What the 2026-10-09 branch was

A "smart re-render": every chunk of a spread render is kept in R2 under a hash of everything that
draws its frames (`src/rendercache.py`); the next render of the same project downloads unchanged
chunks and draws only the rest. The sound is kept per chunk too (slices joined sample-exactly, the
loudness always set again from the whole mix). Plus: stills cleaned 8 at a time, stills' move seeded
by the scene id, PNG / JPEG-quality frame options, per-chunk timings, a render manifest for the app,
a dry-run-by-default clean-up action.

It was functionally complete (its 118 tests passed after the merge), but not safe to switch on:

1. **False hit on replaced clips (fixed).** A web link counted by its text alone. Scene media live
   under `projects/<id>/media/<scene id>.<ext>`: a replaced clip or a rebuilt project ("Start
   fresh": ids restart at s0000) keeps the same link with a different file, so a re-render could
   reuse the OLD picture. Now every web link counts with what its server says of the file (ETag,
   size, Last-Modified: one HEAD per distinct link, 16 at a time, GET of byte 0 when a HEAD is
   refused). A link no server describes gets a value no other render repeats: never reused.
2. **It changed every spread render, even with nothing cached (fixed).** Chunks became fixed
   ~90 s pieces instead of `POD_RENDER_CHUNKS` (12) evened over the video. On a 5-minute video that
   is 3 chunks instead of 10 (render step ~3x slower). Now the old plan is used whenever the cache
   is off; the 90 s pieces only with the cache on.
3. **The cache was ON by default (changed to OFF)** - see "Turning it on".
4. **A push of any `feature/render-*` branch built a GHCR image (removed).** The tag fix stays: a
   by-hand (workflow_dispatch) build of a feature branch is tagged with its sha only, never `:latest`.

Conflicts with what merged since (celeb, gaming, editor v2, smart editor, maps v2, style match,
quality gate, sourcing yield): one, in `handler.py` (the `style_match` and `render_cache_cleanup`
actions side by side). Checked against today's renderer: editor v2 clip fields (keyframes, effects,
masks, speed, in-points), smart-editor specs and their camera windows, `ml-*` library looks and
`wordAt`, the Windowed mounting, ripple-cut narration (`audio.keep`), the `kit` field - all are
inside the hash (tests below). The celeb style renders through its own ffmpeg path and never
reaches the cache. Main.tsx `lookPictures` still matches its Python port (node test, passes).

## What it speeds up

| | Today | With render-smart-2 |
|---|---|---|
| Stills cleaned before the first frame (every render, always on) | one by one, ~1-1.5 min for ~100-120 stills | 8 at a time, each picture once: ~10-20 s |
| Re-render after a one-clip or one-text edit, 15-min video (cache on) | all ~27,000 frames on pod + workers (~4-5 min drawing, ~$0.30-0.35 of worker time) | 1 chunk (~2,700 frames) drawn on the pod alone, 9 downloaded: ~2-3.5 min drawing, ~$0.03-0.04 |
| Music / music level / narration file change (cache on) | full render | no picture drawn; the sound alone (one audio-only pass), then join |
| Narration timing moved at minute T (cache on) | full render | chunks before T reused, after T drawn |
| Frame rate, size, grade, film look, captions, brand kit change | full render | full render (every key changes) |

**Expected minutes saved, 15-min video:** every render ~1 min (still cleaning). A re-render after
a small editor change: a further ~1-2 min of wall time and ~85-90% of the render step's machine
cost (~$0.30 saved per re-render, no helper workers woken for 1-2 chunks). The pod's boot, quality
gate, join, loudness and upload (~3.5 min) are unchanged, so a small re-render goes from ~8 min to
~5.5-6.5 min end to end. First renders with the cache on: same total machine time, chunk count 10
instead of 12; on today's 6-worker endpoint the drawing takes about the same (2 waves either way,
+/- 1 min).

Storage: about one finished video per project (~1.2 GB for 15 min at CRF 21) plus ~11 MB/min of
WAV slices, in `R2_BUCKET/render-cache/v1/<project>/` - ~$0.02/project-month at R2 prices.

## Flags and job input

| Setting | Default | |
|---|---|---|
| `RENDER_CACHE` | **off** | the smart re-render; off = chunks and render exactly as today |
| `POD_RENDER_CHUNK_SECONDS` | 90 | chunk length with the cache on |
| `POD_RENDER_LOCAL_CHUNKS` | 2 | a re-render drawing at most this many chunks draws them on the pod alone |
| `RENDER_CACHE_PREFIX` | `render-cache/v1/` | where entries live (clean-up refuses any other prefix) |
| `RENDER_CACHE_KEEP_DAYS` | 14 | age the clean-up deletes after (a reused entry's age restarts) |
| `RENDER_CACHE_HEAD_WORKERS` / `_HEAD_TIMEOUT` | 16 / 10 s | asking each web link's server about its file |
| `RENDER_LOCAL_CHUNKED` | off | no workers and nothing cached: chunk by chunk anyway (benchmarks) |
| `RENDER_IMAGE_FORMAT` | jpeg | `png` = lossless frames into x264 |
| `RENDER_JPEG_QUALITY` | 0 (= Remotion's 80) | 1-100 |

Job input (`render`): `render_cache` `"on"` (default) / `"refresh"` (draw all, keep) / `"off"`;
`render_cache_scope` (default: the project id). The master flag must be on for any of it.
Worker action `{"action": "render_cache_cleanup", "days": 14}` counts old entries; add
`"dry_run": false` to delete (only under `render-cache/`).

Always on after deploy (no flag): parallel still cleaning; stills' and living photos' move seeded
by the scene id (same move on every machine and render - a crossfade across a chunk seam no longer
jumps; the move direction of some stills differs from today's renders); per-render stats reset;
`render_manifest` v2 in render/build results (chunks, sources, and the editor signatures of the
timeline as sent); chunk workers report draw seconds and fps; `health` shows `renderCache`.
Renderer fingerprint changes, so chunk workers on the old image refuse chunks of a new pod (the
pod draws them) until the endpoint rolls.

## Risks

- **A wrong (old) picture** if the renderer reads something the hash leaves out. Guards: unknown
  fields count; `TrueToTheRenderer` greps `remotion/src` for every field left out; the cross-scene
  reads (image looks, backdrops, `media.focus` under a look, crossfade tails, pack transitions,
  stage moves) are ported and tested; web links count by their file. A future look that reads
  another scene's data must be added to `_look_closure` (bump `HASH_VERSION`).
- Some picture looks (LibPhotoEditor / LibPhotosA / LibPhotosPro*) pick a random variant from the
  served link (a loopback port that changes every render). A re-drawn chunk can show another
  variant than the first render did, and a look running across a chunk seam drawn by two different
  renders can switch variant mid-look - already true today across two machines of one spread render.
- First render with the cache on: fixed 90 s chunks (see above); a 5-min video gets 3 chunks.
- Storage grows until cleaned: needs the R2 lifecycle rule or the clean-up action (owner decision).

## Owner decisions

1. Turn `RENDER_CACHE` on after the check below (pod env first, then the template).
2. Expiry: an R2 lifecycle rule on prefix `render-cache/` (14 days) - deletes data, so your yes -
   or a scheduled `render_cache_cleanup` run.
3. Frame quality: the 2026-10-09 measurement said JPEG-80 frames lose 1.6 dB PSNR against PNG at the
   same CRF. `RENDER_JPEG_QUALITY=95` or `RENDER_IMAGE_FORMAT=png` should look better; their render
   time cost was never measured - worth a 60-s bench before switching.
4. App: copy the seed change (`SceneClip.tsx`, `stillMotion.tsx`, `livingPhoto.tsx`) into the app's
   `src/remotion` mirror so the editor preview pans stills like the render. The manifest's `sig`
   block is for an app re-render estimate that was never built.

## Verify after deploy

1. `{"action": "health"}`: `renderCache.on` false; renders behave as before (events
   `render/spread_render` with the usual chunk count).
2. Test with the cache on for ONE pod only (per-pod env `RENDER_CACHE=1`, no template change):
   render a project twice unchanged. Second run log: `[render-cache] N of N chunks reused`,
   `costs.render.reused = N`, `framesDrawn 0`. The two videos' picture streams must match frame by
   frame: `ffmpeg -i a.mp4 -map 0:v -f framemd5 a.md5` (same for b) and diff.
3. Replace one clip in the editor (same storage key), re-render: exactly one chunk drawn, and the
   NEW clip is in the video. Then render the same timeline with `render_cache: "refresh"` and
   compare: kept chunks byte-identical frames (framemd5), the drawn chunk PSNR >= 45 dB
   (`ffmpeg -i a.mp4 -i b.mp4 -lavfi psnr -f null -`).
4. Change the music volume: no chunk drawn, one sound pass; the loudness reads the same as a full render's.
5. `{"action": "render_cache_cleanup"}` (dry run) lists the project's entries under `render-cache/v1/`.

## Tests

`SKIP_DOTENV=1 python -m unittest discover -s tests -t .` from `runpod/`. New in
`tests/test_render_cache.py`: `LinksDescribed` (a new file under the same link redraws, an
undescribed link never hits, signed links asked once, HEAD/GET fallback), `KeysCoverWhatDraws`
(fps, size, captions, brand kit, `kit`, unknown fields, editor v2 clip fields, smart-spec and
`ml-*` graphics, ripple-cut narration, renderer fingerprint, flags off by default), and `Reuse`
cases for a replaced clip, an undescribed link and the cache-off chunk plan. The LookPicturesPort
test needs `remotion/node_modules` (esbuild).
