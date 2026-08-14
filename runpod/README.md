# ThumbGenius video worker (RunPod)

Backend for the ThumbGenius video workflow: **paste script → pick a voice or upload audio → video**.
The Lovable app is the frontend; this worker does the heavy lifting on RunPod.

```
audio ──► whisper word timings ──► clause segments ──► media per segment ──► Remotion ──► Supabase Storage
                                   (one visual per                (yt-dlp / stock /
                                    spoken clause)                 wikimedia)
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
then natural breaths, then a stretch limit — tuned to land in that same band
(verified: 17.7–21.0 cuts/min, median 2.98–3.36s).

Tune via env vars: `MIN_SCENE_SECONDS` (1.4), `TARGET_SCENE_SECONDS` (2.6), `MAX_SCENE_SECONDS` (5.0).

## Actions

| action | does | use |
|---|---|---|
| `plan` | align audio, segment, source media, return timeline JSON — **no render** | populate the editor timeline |
| `render` | take a (possibly user-edited) timeline → MP4 → Supabase | the "Render video" button |
| `build` | plan + render in one shot | fully automatic runs |
| `health` | readiness probe | monitoring |

Two-phase `plan` → `render` is deliberate: the user sees and edits the timeline before paying for a render.

### Request

```jsonc
{
  "input": {
    "action": "build",
    "project_id": "uuid",
    "script": "optional authored script (keeps your spelling, uses whisper timing)",
    "audio_url": "https://.../narration.mp3",   // required: TTS output or uploaded VO
    "bgm_url": "https://.../suspense.mp3",
    "prefer": "stock",          // or "youtube" to try yt-dlp first
    "allow_youtube": true,
    "captions": true,
    "title_overlay": "MISSING: 1,000s",
    "brand": { "accent": "#FFD400", "fontFamily": "Inter" },
    "scene_queries": { "3": "colombia earthquake rubble" }  // per-scene overrides
  }
}
```

### Response

```jsonc
{
  "ok": true,
  "video_url": "https://<proj>.supabase.co/storage/v1/object/public/renders/projects/<id>/final.mp4",
  "timeline": { "scenes": [...], "meta": { "sceneCount": 312, "cutsPerMinute": 18.4,
                "sources": ["pexels","wikimedia","youtube"], "scenesWithoutMedia": 4 } }
}
```

`meta.sources` and each scene's `media.source` / `media.license` let the UI show where every
clip came from — so you can see Content ID exposure before publishing.

## Media sourcing order

Default `prefer="stock"`: **pexels → pixabay → wikimedia → openverse → youtube**.

YouTube is last on purpose — footage taken from other creators' uploads can attract Content ID
claims on a monetised channel. Set `prefer: "youtube"` to flip it, or `allow_youtube: false` to
exclude it entirely.

**Wikimedia/Openverse matter most for documentary work.** Stock libraries have generic b-roll but
not named real-world subjects ("Million Dollar Highway", a specific quake). Commons does, in the
public domain.

## Environment variables (set on the RunPod endpoint)

| var | required | notes |
|---|---|---|
| `SUPABASE_URL` | yes | `https://wrcucopsyqftqbkhwjag.supabase.co` |
| `SUPABASE_SERVICE_KEY` | yes | service-role key — server-side only, never ship to the browser |
| `SUPABASE_BUCKET` | no | default `renders`; create it and make it public |
| `PEXELS_API_KEY` | recommended | free |
| `PIXABAY_API_KEY` | recommended | free |
| `WHISPER_MODEL` | no | `base` on CPU, `small`/`medium` on GPU |
| `TARGET_SCENE_SECONDS` | no | pacing knob |

## Build & deploy

```bash
docker build -t ghcr.io/<you>/thumbgenius-video:latest runpod/
docker push ghcr.io/<you>/thumbgenius-video:latest
```

Then on RunPod → Serverless → your endpoint: point the template at that image and set the env vars.

### ⚠️ Fix this first — your endpoints cannot run

All four existing endpoints are configured with **`maxWorkers: 0`**, so no worker can ever start
and every job queues forever. This matches the job history (`ai-video-worker-v2`: 0 completed /
9 failed; `AI-VIDEO-EDITER`: 0 completed / 6 failed).

Set **Max Workers ≥ 1** in the endpoint settings. Also review `workersStandby: 3` — standby workers
stay warm and bill continuously; `0` or `1` is saner while testing on a $9.95 balance.

### Smoke test

```bash
curl -s -X POST "https://api.runpod.ai/v2/<ENDPOINT_ID>/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":{"action":"health"}}'
```

## Known limits

- **Whisper mishears proper nouns.** Pass `script` and captions render your authored text on
  whisper's timing (`align_to_script`).
- **Shot-length variety is tighter than the references.** They mix 20–29% sub-2s punches with some
  6s+ holds; this cuts more uniformly inside 2–4s. Add jitter to `segment_words` if you want that texture.
- **A 17-minute video is ~300+ scenes.** Sourcing dominates wall-clock; raise the endpoint execution
  timeout and consider caching assets per query.
- Remotion is free for individuals/teams ≤3; a for-profit team of 4+ needs a paid licence.
