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

Two real products, two different house styles, both measured from finished output:

| | cuts/min | median clip | clips per 21 min |
|---|---|---|---|
| **GoMotion** (current default) | **8.7** | **7.00s** | ~197 |
| VidRush | 16.8–21.8 | 2.56–3.33s | ~430 |

The GoMotion numbers come from reading a finished 22:59 project in its editor: 197 clips,
mode exactly 7.0s across 117 of them, and **92% inside a 6.5–7.5s band**. That is a near-uniform
~7-second grid — not one visual per spoken clause, which is what the VidRush renders do and what
this worker originally copied.

The default is now the slower cut, for three reasons beyond taste. It halves the clip count for a
given runtime, which halves sourcing time and proxy bandwidth; it halves how often a
poorly-matched clip appears; and it gives each shot time to register instead of cutting away
every three seconds.

Both styles are one config change apart, and a test asserts the faster one stays reachable:

```
MIN_SCENE_SECONDS=5.0  TARGET_SCENE_SECONDS=7.0  MAX_SCENE_SECONDS=9.0   # GoMotion (default)
MIN_SCENE_SECONDS=1.4  TARGET_SCENE_SECONDS=2.6  MAX_SCENE_SECONDS=5.0   # VidRush
```

`src/transcribe.py` still cuts on sentence punctuation, then soft punctuation, then natural
breaths, then a stretch limit — the targets simply moved. Narration does not divide evenly into a
grid, so the band is wider than GoMotion's; see `tests/test_pipeline.py::Pacing`.

Note the asymmetry both references share and this worker copies: **supporting shots are short,
explanatory graphics are long.** A bar chart holds 9s and a map 8s even when the beat that
triggered them is shorter, because a chart cut early is a chart nobody can read. Durations live in
`timeline._OVERLAY_SECONDS`.

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

### How a clip is chosen (VidRush-style matching)

Reverse-engineered from VidRush's and GoMotion's own timelines. VidRush stores,
per clip, the intent, the search query, a vision model's description of what the
downloaded frames actually show, and a relevance score — and nothing on their
timeline scores below 0.70. GoMotion always searches the *named subject*
("Lake Mead"), never the idea.

Per beat:

1. **Director** writes `subject` (named place/person/thing), `intent` (what the
   camera should literally show) and a `query` that always contains the subject.
2. **Search** YouTube; title filters drop tutorials, gameplay and news desks.
3. **Scout in parallel** (`MOMENT_PARALLEL`): for the top candidates, read the
   YouTube storyboard (hover-preview thumbnails for the whole video, a few hundred
   KB), lay ~20 tiles on a numbered sheet, and ask the vision model which tile
   shows the intent. Videos with no tile at or above `VISION_MIN_SCORE` are
   dropped before any download. The sharpest storyboard is chosen by pixel width:
   format ids do not map to fixed sizes (`sb1` is 160x90 on one video, 80x45 on
   another), and an 80x45 tile once made the model "see" Hoover Dam in a river.
4. **Download** only that section, check for burned-in text, then **judge the real
   frames** — the final gate. Below 0.70, or any text/watermark/talking head, and
   the next candidate is tried.
5. Stills: web image search, then Commons/NASA/Openverse, each vision-checked.
6. Every scene carries `semanticMetadata` (intent, subject, searchQuery,
   contentDescription, relevanceScore, provider) for the editor.

Cost: roughly 2–4 vision calls per beat.

### Proxy configuration and verification

Sourcing that works on a home connection can fail from a RunPod worker because
YouTube may challenge datacenter addresses. Proxies can also be rejected.
It is not always the famous "Sign in to confirm you're not a bot": the message observed from a
worker was *"The following content is not available on this app"*, which reads like a missing
video rather than a refused client. `media.looks_blocked()` matches the whole family
(`BLOCK_SIGNS`) so the log says *blocked* instead of silently reporting "no results" — that
ambiguity is the entire reason the check exists.

Set a residential or ISP proxy:

```
YTDLP_PROXY=http://user:pass@host:10001,http://user:pass@host:10002,http://user:pass@host:10003
```

A comma-separated list is rotated round-robin per request (`media._next_proxy`) so one address
does not absorb every download and get flagged. Check what you are actually buying before
listing ports — on Decodo ISP plans the ports cycle through a small pool of static IPs, so
`:10001` and `:10004` can be the same address and listing both buys nothing.

Locally there is no RunPod endpoint to supply the variable, so `config._load_dotenv()` fills it
from a `.env` at the repo root (real environment variables still win). `.env` is gitignored;
keep proxy credentials out of the tree.

The image pins `yt-dlp[default]==2026.8.19` (including its matching EJS
package) and Node 22. Both search and download explicitly enable the Node
runtime and bound network retries. This follows the
[yt-dlp runtime setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
Changing these files does not update an already deployed RunPod image.

Verify a real download before starting a long job:

```
python scripts/check_sourcing.py --download
```

This checks an unfiltered search, downloads a three-second diagnostic excerpt,
and verifies its video stream and duration. Reports omit proxy credentials.
Add `--require-cc` to also test the worker's licence filter. The unfiltered
diagnostic does not change production sourcing policy or establish reuse rights.
Run it inside the deployed worker as well as locally; neither a provider
IP check nor a local success proves that the deployed downloader works.

The AI director uses `DIRECTOR_API_BASE`, `DIRECTOR_API_KEY`, and
`DIRECTOR_MODEL` from backend environment variables. Keep the API key out
of frontend builds and job payloads. A Kie-compatible endpoint must return
Chat Completions JSON; configuring a key alone does not validate the model.

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
| `SUPABASE_URL` | only for the fallback upload | `https://wrcucopsyqftqbkhwjag.supabase.co` |
| `SUPABASE_SERVICE_KEY` | **no** — see below | only needed when the caller does *not* pre-sign the upload |
| `SUPABASE_BUCKET` | no | default `renders`; the app uses `videos` |
| `IMAGE_API_KEY` | recommended | enables generated stills; OpenAI-compatible |
| `IMAGE_API_BASE` / `IMAGE_MODEL` | no | default OpenAI / `gpt-image-1` |
| `DIRECTOR_API_KEY` / `DIRECTOR_API_BASE` / `DIRECTOR_MODEL` | recommended | enables the AI director |
| `YTDLP_PROXY` | **yes, in production** | residential proxy for yt-dlp; one url or a comma-separated list, rotated per request. See below |
| `YTDLP_COOKIES_FILE` | no | path to a cookies.txt; helps with the same check |
| `ALLOW_YOUTUBE` / `REQUIRE_CC` | no | YouTube on; **CC-only is OFF by default** — set `REQUIRE_CC=1` for claim-free channels. Unfiltered clips carry `reviewRequired` |
| `VISION_ENABLED` / `VISION_MODEL` / `VISION_MIN_SCORE` | no | vision check on every clip/image; default `gpt-5-2` via the director's Kie key, reject below `0.70` |
| `VISION_API_KEY` / `VISION_API_BASE` | no | default to the director key/base |
| `MOMENT_SELECTION` / `MOMENT_TILES` / `MOMENT_PARALLEL` | no | pick the timestamp from YouTube storyboards; defaults on / 20 / 3 |
| `SERPER_API_KEY` | no | Google Images via Serper; keyless DuckDuckGo image search is used without it |
| `ALLOW_STOCK` | no | default off; also relaxes `timeline.validate()` |
| `WHISPER_MODEL` | no | `base` on CPU, `small`/`medium` on GPU |
| `CONTACT_EMAIL` | no | sent in the User-Agent Wikimedia and Nominatim require |

## How the app calls this worker

`supabase/functions/video-render` in the ThumbGenius app is the caller, and it uses a
**zero-secret upload path** that this worker prefers over its own credentials:

1. The edge function holds the service-role key. Before starting a job it checks the `videos`
   bucket exists and calls `createSignedUploadUrl`, so a missing bucket or bad key fails in
   milliseconds instead of after a twenty-minute render.
2. It passes `upload_url`, `video_path` and `public_url` in the job input.
3. The worker renders and `PUT`s the MP4 straight to that one-object URL.

So **the RunPod endpoint needs no Supabase credentials at all** — nothing to leak from a
serverless image, nothing to rotate. `storage.upload_to_supabase` remains as a fallback for
callers that do not pre-sign, and is what `SUPABASE_SERVICE_KEY` is for.

Inputs the app sends that this worker does not yet honour: `source: "clips"` with `own_clips`,
and `source: "channels"` with `channels`. They are recorded in `meta.warnings` rather than
silently ignored, and sourcing falls back to Creative Commons YouTube plus Commons. `gemini_key`
is likewise not used — the director is configured per endpoint via `DIRECTOR_API_*`.

The app also does not currently send `project_id`, so the worker cannot write progress back into
`video_projects`; add it to the edge function's `input` to light that up.

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
