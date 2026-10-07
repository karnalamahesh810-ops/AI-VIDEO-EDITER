# AI presenter style: the worker's job contract (2026-10-07)

Worker branch `feature/ai-presenter` (code: `runpod/src/presenter/`). The app sends the same RunPod job it sends today (`video-v2` → `/run`); this style adds a few input fields and a few output fields. Nothing else in the job flow changes: progress, cancel, `job_progress`, the project row writes, R2 storage and the editor document all work as for every other style.

## 1. Job input

```json
{
  "action": "build",
  "video_style": "ai_presenter",
  "tier": "budget",
  "presenter_id": "ruth",
  "presenter_catalogue_url": "https://pub-…r2.dev/presenters/catalogue.json",
  "script": "Stop keeping your potatoes and onions in the same basket. …",
  "audio_url": "https://…/narration.mp3",
  "title": "NEVER Store Potatoes and Onions Together Again",
  "project_id": "…"
}
```

| Field | Values | Default | Notes |
|---|---|---|---|
| `action` | `plan` / `build` | `build` | `plan` returns the timeline for the editor; `build` also renders. |
| `video_style` | `ai_presenter` | | Aliases: `AI presenter`, `presenter`, `ai-avatar`. Sets the style's config (no YouTube search, no graphics planner). |
| `tier` | `budget` (alias `reference`), `standard`, `premium` | `budget` | Shares and models in section 5. |
| `presenter_id` | a kit id: `ruth`, `hollis`, `rosa`, `gideon`, `leo` | | Looked up in the catalogue the job brings, else the worker's. |
| `presenter_kit` | a kit object (section 2) | | Instead of an id + catalogue: the app's `presenters` row as it is. |
| `presenter_catalogue` / `presenter_catalogue_url` | a catalogue object / an https link to one | | Any of the layouts in section 2. A catalogue served by link resolves relative picture paths next to itself. |
| `presenter_base_url` | `https://pub-…r2.dev/presenters/` | | Relative picture paths (`ruth/ruth_master.png`) become links under it. Same as a catalogue's own `base_url`. |
| `audio_url` (+ `audio_bucket`) | the narration | | Uploaded voice, or the app's TTS preset output. The presenter lip-syncs to exactly this track. |
| `script` | the authored text | | Strongly recommended: shots and prompts read as written, beats cut on its punctuation. Without `audio_url`, the worker voices it with its own TTS: `tts_model`, `tts_voice`, `tts_speed`, `tts_reference_audio` (https sample to clone), as today. |
| `words` | `[{"text","start","end"}]` | whisper | Optional word timings, if the app already has them. |
| `look` | `none` / `warm` | `none` | `warm`: one warm grade + light grain and vignette over all pictures. Off by default (the reference videos use none). |
| `lower_third` | bool | `false` | Presenter's name low-left on first appearance (clean white type, small gold rule). |
| `captions` | bool | `false` | Clean white captions (the references have none). |
| `dissolves` | 0-1 | `0` | Share of b-roll-to-b-roll joins that dissolve (never into/out of the presenter). |
| `bgm` / `bgm_url` / `bgm_genre` | | off | Music only when asked: no bundled bed suits a talking head. |
| `presenter_budget_usd` | dollars | 1.5 × estimate | Hard cap on OpenRouter spend for the job; past it, shots fall back to free stills. |
| `presenter_config` | tier overrides | | A/B one job: `{"ai_video_share": 0.25, "video_models": [["minimax/hailuo-3-max","768p"]]}`. |

Everything else (`title`, `project_id`, `language`, `media_bucket`, `upload_url`, `width`/`height`/`fps`, brand kit) works as today.

## 2. Presenter kits

The kits agent's layout (`presenter_kits_2026-10-07/catalogue.json`) is read as it is:

```json
{"base_url": "https://pub-…r2.dev/presenters/",
 "presenters": [{
   "id": "ruth", "display_name": "Ruth Calder", "bio": "…", "room": "…", "wardrobe": "…", "camera": "…",
   "images": {"master": "ruth/ruth_master.png",
              "framings": {"closeup": "ruth/ruth_closeup.png", "wide": "…", "three_quarter": "…"},
              "sets": {"set_plate": "…", "set_wide": "…"}, "task": "ruth/ruth_task.png"},
   "voice": {"label": "Southern grandmother cook", "recommended_speed": 0.82}}]}
```

- **Pictures must be links.** On RunPod the worker has no local kit files. Either absolute https links, or relative paths plus `base_url` / `presenter_base_url`. The app's R2 copies at `presenters/<id>/<file>` fit this directly.
- **Fields read:** `id`; `display_name` or `name`; `title` (the lower third's second line, optional); `bio` or `persona` (the presenter-in-action prompts); `wardrobe`; `from_behind` (optional: how they look from behind, used for any back view in b-roll); `room` (the style bible's place); `camera` (contains "selfie" → handheld avatar motion); `images.master`; `images.framings`; `images.sets`; `images.task`; `voice`.
- **Optional:** `avatar {prompt, motion_prompt, expressiveness}`, `grade`, and per framing `face_x` (0-1, where the face sits across the frame: the split screen crops on it; default 0.5).
- **How the pictures are used:**
  - The master opens the video; the chest-up `closeup` is the second camera. The `wide` and `three_quarter` framings are only used when a shot is retried.
  - The master is the reference for every b-roll still that shows the presenter (Nano Banana Pro).
  - The `sets` and `task` pictures are free fallbacks for a still that fails its checks, each used at most once.
- Every picture is cropped to 16:9 (1920×1080) before the avatar call. The master should already show the person on the set.

## 3. What comes back

`plan` / `build` return what they return today (`timeline`, `costs`, `events`; `build` adds `video_url`, `duration`, `quality`). In the timeline:

- **Scenes:**
  - `media.source` is `ai-presenter`, `ai-video`, `ai-image` or `kit-set`. Presenter clips are muted and trimmed to their scene; the narration is the only sound.
  - `frame: "split"` with `media.split = {type, url, motion, focusX}`: the presenter on the left, the line's picture on the right (about a third of the presenter's appearances after the opening).
  - `semanticMetadata`:
    - `shotKind` (presenter / ai_video / picture) and `role` (hook, chapter, why, close, body);
    - `generated {model, usd, url, attempts, fallback, checks}`;
    - `originalUrl` (the generated original on R2);
    - for presenter scenes, `presenter {kit, name, framing, lag, window}`.
  - `reviewRequired: true` with a `reviewReason` on any scene that fell back.
- **`doc.grade`** is `null` and `doc.look` is absent unless `look: "warm"`.
- **`meta.presenter`:**
  - `tier`, `kit`, `planner`, `bible`;
  - `planned` and `final` (shares, cuts per minute, presenter shot lengths);
  - `shots[]` (each with its asset), `fallbacks`, `empty`;
  - `costs {presenterUsd, aiVideoUsd, imagesUsd, checksUsd, plannerUsd, totalUsd, calls}`, `budget`, `estimate`;
  - `checks`, `storage`, `disclosure`, `seconds`, `log`.
- **`meta.costs`** (the job ledger) adds the `presenter` and `aivideo` categories. Its units include `presenter.seconds`, `presenter.screen_seconds`, `aivideo.seconds` and `aivideo.screen_seconds`. Every price is OpenRouter's own `usage.cost`.
- **`meta.warnings[0]`** is the YouTube disclosure line (section 6).

## 4. The style card: tiers, estimates, kits, script preset

Send `{"action": "presenter_info"}`. It makes no paid call and writes nothing. The answer:

| Key | What |
|---|---|
| `defaultTier` | the tier a job gets when it names none |
| `tiers` | shares and models per tier |
| `estimate.tiers.<tier>.byMinutes."10"\|"15"\|"20"` | `{usd, parts, counts, makeMinutes, models}` per length |
| `kits` | the worker's own catalogue (empty unless `PRESENTER_KITS_URL` is set) |
| `script` | the script preset (section 7) |
| `disclosure` | the line the app shows (section 6) |

Current numbers:

| Tier | Mix (presenter / AI clips / stills) | 10 min | 15 min | 20 min | 20 min = |
|---|---|---|---|---|---|
| `budget` (reference) | 14% / 15% / 71% | $15.45 | $23.17 | $30.89 | 213 stills, 40 clips, 2.8 min presenter |
| `standard` | 15% / 25% / 60% | $27.53 | $41.29 | $55.04 | 180 stills, 67 clips, 3.0 min presenter |
| `premium` | 18% / 40% / 42% | $68.61 | $102.90 | $137.20 | 126 stills, 107 clips, 3.6 min presenter |

- Making a 15-minute video takes about 30-47 minutes.
- The 90-second laptop test cost $3.38 on OpenRouter: the budget mix on 2K stills and 1080p clips, the planner and the checks included.

## 5. Tiers (configuration, `src/presenter/tiers.py`)

| Tier | Presenter | AI clips | Stills | Presenter in b-roll |
|---|---|---|---|---|
| `budget` | Avatar IV 1080p, 14% | Seedance 1.5 Pro 720p → Veo 3.1 Lite, 15% | Nano Banana 2.1 1K → Nano Banana 2 | 15% of b-roll, Nano Banana Pro + master |
| `standard` | Avatar IV 1080p, 15% | Seedance 1.5 Pro 1080p → MiniMax H3 Max 768p → Veo 3.1 Lite, 25% | Nano Banana 2.1 2K | 20% |
| `premium` | Avatar IV 1080p, 18% | MiniMax H3 2K → Wan 3.0 1080p → H3 Max, 40% | Nano Banana Pro 2K | 25% |

- In every tier, a third of the presenter's appearances are split screens.
- The tiers can be overridden by the `PRESENTER_TIERS` environment variable (JSON) or by a job's `presenter_config`.

## 6. Disclosure (show it with the download)

The video shows a realistic AI-generated person and scenes:
- Tick "Altered or synthetic content" in YouTube Studio when uploading.
- If the app ever uploads through the API, set `status.containsSyntheticMedia = true`.
- Keep the presenter off medical, financial and legal advice.

## 7. Script preset (for the app's script generation)

`presenter_info.script` (`src/presenter/script_preset.py`): the reference channels' template.

1. A story opening.
2. Name, age, county.
3. A numbered list with the secret saved for last.
4. An optional one-time plug (the user's own product or link).
5. Ask for the viewer's county in the comments.
6. A next-video tease and a sign-off motto.

Write it in the first person, with no contractions, at about 175 words a minute.

## 8. Editor notes

- **Replace Clip** on a presenter scene is refused with a plain message: its lips follow the voice. On b-roll scenes it searches as today. Regenerating one shot is phase 2.
- **The editor's Player** needs the renderer additions to preview this style:
  - `remotion/src/components/SceneClip.tsx`: the `frame: "split"` layout, and `ClipVideo` (`media.html5`);
  - `components/FilmLook.tsx` and its line in `Main.tsx` (`doc.look`);
  - the `types.ts` fields.

## 9. Worker deploy (not done)

- **Nothing new is required.** The OpenRouter key comes from the worker's existing settings (the director's or vision's OpenRouter key, or `OPENROUTER_API_KEY`), and R2 is as today.
- **Optional settings:**

  | Setting | What |
  |---|---|
  | `PRESENTER_KITS_URL` | a catalogue link for the worker's own kit list |
  | `PRESENTER_BUDGET_USD` | a default cap |
  | `PRESENTER_DIRECTOR_MODEL` | the planner model (default `openai/gpt-5.2`) |
  | `PRESENTER_CHECK_MODEL` | the check model (default `google/gemini-2.5-flash`) |
  | `PRESENTER_TIERS` | tier overrides (JSON) |
  | `PRESENTER_PARALLEL`, `PRESENTER_VIDEO_PARALLEL`, `PRESENTER_IMAGE_PARALLEL` | how many calls run at once |

- **No Kie anywhere.** Every call goes to OpenRouter. `providers.AlgrowREST` is the slot for an Algrow provider (`PRESENTER_PROVIDER=algrow`).
