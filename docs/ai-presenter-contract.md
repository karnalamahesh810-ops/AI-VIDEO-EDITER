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

## 10. Hybrid: the presenter inside any footage style (worker branch `feature/presenter-hybrid`)

Any style but `ai_presenter` (`documentary`, `news_compilation`, ...) takes an optional `presenter` block. The build stays the normal one: real YouTube clips and real web pictures, found and judged line by line. The presenter is cut in on a few lines. **Nothing else is generated:** no AI pictures, no AI clips and no kit sets, not even as fallbacks. Code: `runpod/src/presenter/hybrid.py`.

```json
"presenter": {
  "presenter_id": "hollis",
  "presenter_kit": { "...": "the kit, section 2 (the app's workerKit)" },
  "share": 0.14,
  "level": "medium",
  "split_screen": true,
  "budget_usd": 1.07
}
```

| Field | Values | Default | Notes |
|---|---|---|---|
| `presenter_id` / `presenter_kit` | as in sections 1-2 | | The inline kit wins. `catalogue` / `catalogue_url` / `base_url` are read too. A block with no usable kit fails the job before anything is spent. |
| `share` | 0.02-0.30 | 0.14 | Share of the running time: `0.08` light, `0.14` medium. |
| `level` | `light` / `medium` | | A label. A level sent alone sets its share. |
| `split_screen` | bool | `true` | About a third of the middle appearances are 50/50: the presenter left, **that line's real clip or picture** right. Never the hook or the close. |
| `budget_usd` | dollars | narration s × share × $0.05 × 1.5 (never under every planned take once more) | A hard cap on the presenter's OpenRouter calls. The plan is trimmed to fit first, keeping room for one retry of its dearest take: the latest middle appearance goes first, then the close, then the hook. A take refused or failed past it: the line gets footage. |
| `enabled` | `false` | | Switches a block off. |

Without the block nothing changes: tests prove the timeline is byte-for-byte that of 68205fc.

**What the presenter says on camera:**
- The hook's first sentence (up to 9 s).
- Chapter openings ("Now, ...", "Here is the part ...", the brief's section starts).
- A beat whenever the footage has run ~40 s without one, while the share allows.
- The close.
- A line about the presenter ("My name is Hollis Reed": their name was the line's subject) is theirs to say first.
- Each appearance is 3.5-7.5 s of whole lines, with at least 10 s of footage between appearances.
- Never a line the plan gave a graphic, except the opening sentence and the sign-off (the hint gives way). A named person's or a document's line only as a split; such a line keeps the opening or the close on footage (`meta.presenterHybrid.log` says why).

**How the presenter shots are made:**
- One `heygen/avatar-iv` take per appearance, from its narration window, made beside the footage search.
- The take is cut frame-exact into one clip per line, so the editor keeps every line as its own scene.
- Checks (frozen, black, the face against the master). The retry uses the other framing.
- A failed take sends its lines back to the footage search after the main search, in a box of their own (150 s + 30 s a line, `PRESENTER_HYBRID_RETRY_SECONDS`), then the usual fills. The build waits for the takes at most 900 s after its search (`PRESENTER_HYBRID_WAIT_SECONDS`); a later take is not used.
- Full-screen presenter lines are never searched. Split lines are.
- The presenter's name never goes into a footage search (a made-up person: the laptop test's search for "Hollis Reed" found a real Hollis in a court case). It leaves every shot's query, fallbacks and subject.

**Around the presenter:**
- No look, graphic, data look, date, mark, source tag or sound effect over a presenter scene. A look running in from the footage before ends at the cut.
- Hard cuts in and out.
- No effect, film treatment, move or reframe on the presenter.
- The quality gate, the hook check, the AI review, hold-overs, re-cut, re-clip, restore, the clip library and the cross-video ledger all leave presenter scenes alone. The real half of a split is recorded like any shown footage.
- Replace Clip refuses a presenter scene (section 8).
- The job runs with `IMAGE_MAX_PER_VIDEO 0`, `PREFER_GENERATED_IMAGES false`, `GENERATED_IMAGES_IN_HOOK false` and `HOOK_TEASER false`, whatever its config says. Its Replace Clip and render jobs get the same.

**In the timeline:**
- **Presenter scenes:**
  - `media.source` is `"ai-presenter"` (a clip cut to its line, muted).
  - `effect`, `treatment` and `motion` are `"none"`; `reframe` is `"off"`; `transition` is `"none"`.
  - `semanticMetadata.shotKind` is `"presenter"`, plus `role` and `presenter {kit, name, framing, lag, take, lines, window, mode: "hybrid"}`.
  - Also `generated` and `originalUrl` (the whole take on R2).
- **Split scenes:**
  - Also `frame: "split"` and `media.split {type, url, source, motion, focusX, assetId, sourceUrl, moment, clipSeconds, attribution, license}`. This is the REAL half; it is published to R2 with the scene media, and without R2 the split goes and the presenter stays full-screen.
  - Also `semanticMetadata.split {query, relevanceScore, contentDescription, real: true}`.
- **`meta.presenterHybrid`:**
  - `mode`, `kit`, `share`, `shareOfTime`, `splitScreen`;
  - `planned[]`, `overBudget[]`, `made[]`, `fellBack[{id, lines, why}]`, `searchedAfter[]`;
  - `screen {seconds, share, scenes, splitScenes, appearances}`;
  - `costs {presenterUsd, checksUsd, totalUsd}`, `budget`, `estimate`;
  - `swept {trimmed, dropped, sfx}`, `log`, `disclosure`, `warnings`.
- **`meta.warnings[0]`** is the disclosure line, when the presenter appears.
- **`meta.costs`** carries the `presenter` category as in section 3.

**Estimate:** `presenter_info.hybrid`.
- Its fields: `{shares, defaultShare, usdPerPresenterSecond, normalBuildPerMinute, byShare.light|medium."10"|"15"|"20" {usd, parts, presenterSeconds, billedSeconds, appearances, formula}, disclosure}`.
- The formula: the normal footage build (~$0.11/min) + presenter seconds × $0.05. Each take is billed 0.9 s over its screen time, and ~10% need a retake. Face checks are added; the vision of unsearched lines is taken off.

| Share | 10 min | 15 min | 20 min |
|---|---|---|---|
| light (0.08) | $4.17 | $6.26 | $8.34 |
| medium (0.14) | $6.48 | $9.71 | $12.95 |

**The app Player** needs the same `frame: "split"` drawing as section 8, with a video right half (`media.split.type: "video"`).
