# Avatarity AI visuals (2026-10-28)

The owner bought the Avatarity Starter plan ($30/month): 2,000 Veo 3.1 Lite clips (~8 s), 5,000 Nano Banana
pictures, 4 renders at a time. Avatarity is now the AI provider for AI clips and pictures; OpenRouter stays the
fallback and an option. App contract: `docs/ai-visuals-contract.md` in the app repo (branch `feature/avatarity`).

## Pieces

- `src/avatarity.py` - the client (key `AVATARITY_API_KEY`, never printed): images (sync or polled task), clips
  (start frame optional), the 1080p upscale of a finished clip (`source_task_id`), `/usage`; one 4-slot gate per
  process; `Idempotency-Key` on every POST (a restarted run re-attaches to the same task, no double spend); 429
  CONCURRENCY_LIMIT / RATE_LIMIT_EXCEEDED wait and retry; 402 / ALLOWANCE_* -> `AllowanceError` (AI fill moves on
  to the OpenRouter chain and says so in `fallbacks`); CONTENT_POLICY_VIOLATION -> `PolicyError`; RENDER_TIMEOUT /
  INFERENCE_FAILED / UPSCALE_FAILED retried. Every prompt ends with the no-text rule (the owner's first test picture
  came back as a polaroid with a caption and a made-up date). `provider()` is the presenter-provider face AI fill
  speaks to: models named `avatarity/<id>` go to Avatarity, everything else (and every chat / vision check) to
  OpenRouter. `hd_upscale()` = our 720p -> 1080 pass.
- `src/aifill.py` - the block takes `provider`, `image_model`, `video_model`, `resolution`, unit caps; with a key the
  chains start with `avatarity/nano-banana-pro` (2K) and `avatarity/veo-3.1-lite` (720p); Avatarity calls cost $0
  in the USD budget (it still covers OpenRouter prompts, checks and fallbacks) and are capped in units; Veo clips
  cover lines up to 7.5 s; user / editor prompts (`prompts`, `semanticMetadata.aiPrompt`) win over the prompt
  model; look presets + style notes; `meta.aiFill.usage` (units used, plan remaining, OpenRouter $).
- `src/aivisuals.py` - `visual_source: "ai"` (the whole video from AI): no footage search at all (handler.do_plan
  skips pools / search / rescue / runner-ups / ladder / stills-to-clips), 3.2-7 s shots, AI fill in "full" mode
  (every line a picture; `clip_pct` of the screen time animated from those pictures, spread over the video by
  error diffusion), `meta.aiVisuals`, the AI disclosure first in `meta.warnings`; `regenerate()` for the editor's
  Regenerate picture / clip (`resource` modes `ai_image` / `ai_clip` with `ai_prompt`).

## 720p + our upscale vs native 1080p (measured, 2 clips, 4 units)

Each clip was made at 720p (1 unit) and then upscaled by Avatarity to 1080p from the same task (1 unit), so the
content is identical. Our pass on the 720p file vs Avatarity's 1080p:

| clip | SSIM ours vs theirs | sharpness (Laplacian var) theirs / ours v1 / ours v2 |
|---|---|---|
| dam aerial | 0.877 | 865 / 219 / 400 |
| outlet spray | 0.879 | 812 / 229 / - |

Avatarity's 1080p is crisper (about 2x the edge energy of our tuned pass) but also crunchier: concrete gets an
over-sharpened, painted texture. At YouTube 1080p bitrates the difference shows only at 100 % crops. **Default:
720p + our HD upscale (v2 filter: denoise, Lanczos, unsharp 0.9 + 0.35) at 1 unit a clip; "1080p (2 units)" stays a
per-video setting** for hero shots. Crops: scratchpad `hoover_ai/rescmp/cmp0b.png`.

## Laptop proof (Hoover Dam, the owner's own 12:05 voiceover)

Prompts and the visual bible were written by Claude (no prompt model); pictures Nano Banana Pro, clips Veo 3.1 Lite
image-to-video from the approved picture where one exists, text-to-video for the rest (the owner capped pictures
at ~65); every clip reviewed on a frame strip, the first 0.4 s and last 0.25 s trimmed; clean cuts, a 0.5 s
crossfade only at the 8 act changes, no graphics or text; rendered with the system ffmpeg (no Remotion), plus a
Premiere (FCP7 XML) project. Scripts: session scratchpad `hoover_ai/`.
