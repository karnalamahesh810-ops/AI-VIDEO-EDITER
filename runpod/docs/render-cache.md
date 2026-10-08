# Smart re-render (render cache)

A render keeps every chunk it draws in Cloudflare R2 under a hash of everything that draws
those frames. The next render of the same project reuses every chunk whose hash did not change
and draws only the rest; the sound mix is reused when nothing audible changed, else drawn whole
from the timeline, and the loudness is always set again from the whole mix.

Code: `src/rendercache.py` (boundaries, hashes, store, clean-up), `src/fanout.py render_pod`
(reuse, drawing, joining, keeping). Tests: `tests/test_render_cache.py`.

## Chunks

`stable_chunks` cuts the video into chunks of about `POD_RENDER_CHUNK_SECONDS` (90 s), each
ending on the cleanest scene cut near that length (no transition, sound effect or overlay
entrance across it), chosen left to right. A boundary depends only on the cuts near it - never
on the video's length or the machine - so an edit never moves a boundary before it.

What an edit re-renders (measured on three real timelines, 18-23 min, 12-15 chunks):

| Edit | Chunks drawn again | Sound |
|---|---|---|
| One line's clip or picture swapped | 1 | reused |
| One look's words changed | 1 | drawn again (a look's sound can change) |
| Music level, sound effects | 0 | drawn again |
| Narration timing moved after time T | every chunk after T; every chunk before T reused | drawn again |
| Frame rate, size, grade, film look, subtitles on/off | all | - |

With subtitles on, any change of the narration's words re-renders every chunk (the cues are set
over the whole narration at once).

## What the hash covers

`picture_hash` (absolute frame positions: looks read them):

- every scene drawn in the chunk's frames (a crossfade's tail included), all fields the renderer
  reads; media by identity (a signed link without its signature, a local file by its bytes);
- what the frames borrow from other scenes: an animation's backdrop, the next scene's transition,
  a pack transition's clip over a nearby cut, the scene an overlay starts on (its `media.focus`),
  and the pictures an image look shows (`look_pictures`, Main.tsx `lookPictures` ported line for
  line and checked against the renderer under node);
- every overlay on screen in or within a second of the frames;
- subtitles (when on), the grade with its frozen median, the film look, the brand kit (the
  watermark everywhere, intro and outro only in their frames), frame size and rate;
- the renderer fingerprint and every encoder setting (`render.encoder_settings`: CRF, x264
  preset, frame format and JPEG quality, GL), so a kept chunk always joins new ones without
  re-encoding. Before the join every kept chunk's frame count and SPS/PPS are checked; one that
  differs is drawn again.

Fields the renderer never reads (`SCENE_NOT_DRAWN`, `MEDIA_NOT_DRAWN`) are left out; a test greps
`remotion/src` so the lists stay true. Anything unknown counts: a false miss costs a render, a
false hit would show the wrong picture.

`audio_hash`: the narration (the polished file by its bytes), music, beds, sound effects, every
overlay (looks carry sounds), scene timings, words and transitions, the renderer.

## Settings and job input

| Setting | Default | |
|---|---|---|
| `RENDER_CACHE` | on | the smart re-render |
| `POD_RENDER_CHUNK_SECONDS` | 90 | chunk length |
| `POD_RENDER_LOCAL_CHUNKS` | 2 | a re-render with at most this many chunks to draw draws them on its own machine (no worker woken) |
| `RENDER_CACHE_PREFIX` | `render-cache/v1/` | where entries live in `R2_BUCKET` |
| `RENDER_CACHE_KEEP_DAYS` | 14 | age the clean-up deletes after |
| `RENDER_LOCAL_CHUNKED` | off | with no workers and nothing cached, draw chunk by chunk anyway (tests, benchmarks) |
| `RENDER_IMAGE_FORMAT` / `RENDER_JPEG_QUALITY` | jpeg / 0 (=80) | the frame Chrome hands to x264 |

Job input (`render`): `render_cache` = `"on"` (default) | `"refresh"` (draw everything, keep it) |
`"off"`; `render_cache_scope` (default: the project id). The result carries `render_manifest`
(chunks, where each came from, the mix, savings, the editor's signatures) and
`costs.render` (chunks reused, frames not drawn, `savedUsd`).

## Storage and expiry

```
R2_BUCKET/render-cache/v1/<project>/c-<hash>.mp4   a chunk's picture, exactly its frames
R2_BUCKET/render-cache/v1/<project>/a-<hash>.flac  the whole mix before loudness
```

About one finished video's size per project (CRF 18 chunks + a FLAC mix). A reused entry is copied
onto itself (`touch`), which starts its age again, so age-based expiry never takes what renders
keep using.

Expiry - either:

1. **R2 lifecycle rule (recommended, set once by the owner):** Cloudflare dashboard -> R2 ->
   `thumbgenius-videos` -> Settings -> Object lifecycle rules -> Add rule: prefix
   `render-cache/`, delete objects 14 days after they were last modified. Nothing outside that
   prefix is affected.
2. **Manual clean-up:** the worker action `{"action": "render_cache_cleanup", "days": 14}` lists
   and counts (dry run); add `"dry_run": false` to delete. It only ever lists or deletes keys
   under `RENDER_CACHE_PREFIX` (it refuses any other prefix) - never `projects/` (scene media,
   finished videos). `"scope": "<project id>"` limits it to one project.
