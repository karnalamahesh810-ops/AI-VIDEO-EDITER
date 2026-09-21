# ThumbGenius video worker (RunPod)

Backend for the ThumbGenius video workflow: **paste script → pick a voice or upload audio → video**.
The Lovable app is the frontend; this worker does the heavy lifting on RunPod.

```
narration audio
  └─ whisper word timings ........... transcribe.py
  └─ clause beats (VidRush pacing) ... transcribe.py   one visual per spoken clause
  └─ shot plan per beat ............. director.py      what to show + which graphic
  └─ media per beat ................. media.py         yt-dlp CC / real photos / generated
  └─ timeline document .............. timeline.py      validated before rendering
  └─ MP4 ............................ render.py        Remotion, 14 animation templates
  └─ Supabase Storage ............... storage.py
```

## Why it cuts the way it does

Pacing defaults are **measured from four VidRush reference renders** (240s sample each):

| Reference video | Cuts/min | Median shot |
|---|---|---|
| Colombia 7.4 Quake | 17.0 | 3.33s |
| 7 Cities / Yellowstone | 21.8 | 2.56s |
| Loneliest Road | 17.8 | 3.30s |
| Death Valley → Vegas | 16.8 | 3.29s |

All were 1920×1080 @ 30fps. The pattern: **one visual per spoken clause**, which lands ~3s.
`src/transcribe.py` reproduces it by cutting on sentence punctuation, then soft punctuation,
then natural breaths, then a stretch limit. The band is pinned by a test — see
`tests/test_pipeline.py::Pacing`.

Tune via env vars: `MIN_SCENE_SECONDS` (1.4), `TARGET_SCENE_SECONDS` (2.6), `MAX_SCENE_SECONDS` (5.0).

Note the asymmetry the reference renders show and this worker copies: **supporting shots are
short, explanatory graphics are long.** A bar chart holds 9s and a map 8s even when the beat
that triggered them is 2.6s, because a chart cut after 2.6s is a chart nobody can read.
Durations live in `timeline._OVERLAY_SECONDS`.

## Sourcing: no stock

| Want | Source order |
|---|---|
| footage | YouTube via yt-dlp, **Creative Commons only** |
| stills | Wikimedia Commons → Openverse → generated image |

Stock libraries have generic b-roll but not *named* real-world subjects ("Million Dollar
Highway", a specific quake). Commons does, in the public domain.

Images are ordered real-photograph-first on purpose. A generated photoreal image of an actual
news event is a fabricated depiction of something that really happened; where a real photo of
the subject exists it is both more accurate and safer. Generated frames are tagged
`source="generated"` and carry `reviewRequired`, so the editor can show which shots are
illustrations rather than records.

`require_cc` restricts YouTube to uploads published under CC BY — the only footage you may
legally re-cut and monetise. The default YouTube licence reserves every right, so anything else
is Content ID food. Turn it off only for footage you own.

Pexels/Pixabay adapters are still in `media.py` as an escape hatch behind `ALLOW_STOCK=1`;
`timeline.validate()` rejects stock sources unless that is set.

## Animation templates

Fourteen, all in `remotion/src/components/`:

`title` · `chapter` · `callout` · `typewriter` · `stat` · `bar-chart` · `comparison` ·
`map` · `quote` · `timeline` · `highlight` · `lower-third` · `arrow` · `split`

Render one of each to look at them:

```bash
python scripts/preview_overlays.py --width 1280
```

**Maps never guess.** The director may only *name* a place; `geocode.py` resolves it against
OpenStreetMap and the label drawn on screen is the gazetteer's own name for that point. If the
lookup fails the map is dropped and the scene keeps its footage. This exists because the VidRush
reference renders actually ship the bug it prevents — one map's city field reads "Santa Marta"
while its own caption reads "EPICENTER: SAN JOSE DEL PALMAR", 700km apart.

The template list lives in three places (`director.TEMPLATES`, `types.ts`, `Main.tsx`) and a test
asserts they agree — a type one side knows and another does not renders as the wrong card
silently, mid-render.

## The AI director

Optional. Set `DIRECTOR_API_BASE` / `DIRECTOR_API_KEY` / `DIRECTOR_MODEL` (any OpenAI-compatible
chat endpoint) and a model chooses each beat's search query, footage-vs-still, and graphic.
Without it a rule pass covers every beat, and `meta.planner` reports `ai`, `mixed` or `rules`
so the UI can say how much was chosen by a model.

Narration is treated as untrusted content throughout: the prompt says so, and
`director.validate_overlay()` re-validates everything the model returns before it can reach a
render. Model-supplied coordinates are discarded rather than trusted.

## Actions

| action | does | use |
|---|---|---|
| `plan` | align, segment, plan shots, source media, **publish media**, return timeline JSON | populate the editor timeline |
| `render` | take a (possibly user-edited) timeline → MP4 → Supabase | the "Render video" button |
| `build` | plan + render in one shot, media stays local | fully automatic runs |
| `health` | readiness probe | monitoring |

Two-phase `plan` → `render` is deliberate: the user sees and edits the timeline before paying for
a render. Because those are *separate serverless jobs* on possibly different workers, `plan`
uploads its sourced media to Supabase — a timeline holding local paths would already be broken by
the time the user pressed Render. `build` skips that and keeps media local, since it renders in
the same job.

### Request

```jsonc
{
  "input": {
    "action": "build",
    "project_id": "uuid",
    "title": "The Vanishing Reservoir",      // context for every search query
    "script": "optional authored script (keeps your spelling, uses whisper timing)",
    "audio_url": "https://.../narration.mp3", // required: TTS output or uploaded VO
    "bgm_url": "https://.../suspense.mp3",
    "captions": true,
    "maps": true,                             // false to disable map overlays
    "allow_youtube": true,
    "require_cc": true,
    "brand": { "accent": "#FFD400", "fontFamily": "Inter" },
    "scene_queries": { "3": "colombia earthquake rubble" }  // per-scene overrides
  }
}
```

### Response

```jsonc
{
  "ok": true,
  "video_url": "https://<proj>.supabase.co/storage/v1/object/sign/renders/...",
  "timeline": {
    "schemaVersion": 2,
    "scenes": [...], "overlays": [...],
    "meta": { "sceneCount": 312, "cutsPerMinute": 18.4, "planner": "ai",
              "sourcePolicy": "no_stock", "sources": ["youtube","wikimedia","generated"],
              "scenesWithoutMedia": 4, "scenesNeedingReview": 11, "generatedScenes": 9,
              "warnings": [...] }
  }
}
```

`meta.sources`, `scenesNeedingReview` and each scene's `media.source` / `media.license` let the
UI show where every clip came from — so you can see Content ID exposure before publishing.

## Environment variables (set on the RunPod endpoint)

| var | required | notes |
|---|---|---|
| `SUPABASE_URL` | yes | `https://wrcucopsyqftqbkhwjag.supabase.co` |
| `SUPABASE_SERVICE_KEY` | yes | service-role key — server-side only, never ship to the browser |
| `SUPABASE_BUCKET` | no | default `renders` |
| `IMAGE_API_KEY` | recommended | enables generated stills; OpenAI-compatible |
| `IMAGE_API_BASE` / `IMAGE_MODEL` | no | default OpenAI / `gpt-image-1` |
| `DIRECTOR_API_KEY` / `DIRECTOR_API_BASE` / `DIRECTOR_MODEL` | recommended | enables the AI director |
| `ALLOW_YOUTUBE` / `REQUIRE_CC` | no | both default on |
| `ALLOW_STOCK` | no | default off; also relaxes `timeline.validate()` |
| `WHISPER_MODEL` | no | `base` on CPU, `small`/`medium` on GPU |
| `CONTACT_EMAIL` | no | sent in the User-Agent Wikimedia and Nominatim require |

## Development

```bash
python -m unittest discover -s tests -t .     # 58 tests, offline, ~0.1s
python scripts/preview_overlays.py            # render every animation template
python scripts/smoke_render.py                # full pipeline -> watchable MP4
cd remotion && npx tsc --noEmit               # type-check the renderer
```

`smoke_render.py` stubs only the three external boundaries — whisper, the network and Supabase —
and runs everything else for real, including an actual Remotion render. It is the one that
catches wiring failures: a document Remotion cannot load, media Chrome cannot fetch, a scene
track that does not tile the audio.

### Why there is a local HTTP server in the render path

Remotion renders inside a Chrome page on an `http://localhost` origin, and such a page cannot
read `file://` URLs; Remotion rejects a bare filesystem path outright. Both were measured — a raw
path and a `file://` URI each fail the render, the same asset over loopback renders fine. So
`assetserver.py` serves the job directory on an ephemeral port for the duration of the render and
rewrites local references to point at it. It answers Range requests, because `OffthreadVideo`
seeks and a server that ignores Range makes video playback wrong or very slow.

## Build & deploy

CI builds the image on every push to `thumbgenius-video-worker` and pushes to GHCR
(`.github/workflows/build-worker.yml`). To build locally:

```bash
docker build -t ghcr.io/<you>/thumbgenius-video-worker:latest runpod/
```

Then on RunPod → Serverless → your endpoint: point the template at that image and set the env vars.

### Endpoint configuration

Deployed and verified on RunPod 2026-09-21.

- Template **`gjr1mh79q6`** (`thumbgenius-video-worker`) — image pinned to a commit SHA, not
  `:latest`, so a redeploy is deliberate and two concurrent CI builds cannot race over which
  image an endpoint picks up.
- Endpoint **`tuxcziwby5plod`** (`thumbgenius-worker`) — GPU (A5000 / L4 / 3090), workersMax 2,
  idleTimeout 10s, executionTimeout 3h (a 20-minute 1080p render does not fit in the 1h default).

`health` and `selftest` both pass there: all 14 templates rendered in-container, audio track
present, whisper `base` loaded in 3.1s.

Two things that cost time, recorded so they don't again:

- **Changing a template's image does not recycle a warm worker.** After repointing an existing
  endpoint, jobs kept landing on the same `workerId` still running the previous image. The giveaway
  was an error string that didn't match this codebase. `workersStandby` is settable in neither the
  REST nor the GraphQL API, so the fix is a fresh endpoint rather than fighting the old one.
- **Do not diagnose a missing image from a bare GHCR manifest probe.** Requesting only the OCI
  *index* and Docker *manifest-list* media types 404s on a single-arch image that is perfectly
  present. Include `application/vnd.oci.image.manifest.v1+json` and
  `application/vnd.docker.distribution.manifest.v2+json` in `Accept`, or you will conclude an
  image does not exist when it does. (This note exists because that is exactly what happened.)

`workersStandby: 3` on the older `ai-video-worker-v2` is still worth dropping to 0 in the console;
standby workers stay warm and bill.

### Smoke test

```bash
curl -s -X POST "https://api.runpod.ai/v2/<ENDPOINT_ID>/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":{"action":"health"}}'
```

`health` reports whether the director and image model are configured, and which source policy
is active.

## Known limits

- **Whisper mishears proper nouns.** Pass `script` and captions render your authored text on
  whisper's timing (`align_to_script`).
- **Shot-length variety is tighter than the references.** They mix 20–29% sub-2s punches with
  some 6s+ holds; this cuts more uniformly inside 2–4s.
- **A 30-minute video is ~550 scenes.** Sourcing dominates wall-clock. yt-dlp with the CC filter
  is the slow part — raise the endpoint execution timeout, and `source_workers` if the box allows.
- **Nominatim is rate-limited to ~1 req/s** by its terms of use, so maps are capped at 12 per
  video and one per 60s of narration. That is also better editing than a map every other beat.
- Remotion is free for individuals/teams ≤3; a for-profit team of 4+ needs a paid licence.
