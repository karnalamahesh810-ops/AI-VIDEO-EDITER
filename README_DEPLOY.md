# Deploy the serverless video worker (scales to 10+ parallel videos)

The folder `C:\app\vidrush_style\serverless\` IS the GitHub repo. RunPod builds the
Docker image from it in their cloud (no Docker needed locally).

## 1. GitHub (one time)
1. github.com → New repository → name: `thumbgenius-worker` → **Private** → Create.
2. Upload everything in `C:\app\vidrush_style\serverless\` (web UI: "uploading an existing
   file" → drag the whole folder contents, keep the folder structure: Dockerfile and
   handler.py at the ROOT of the repo).

## 2. RunPod Serverless endpoint (one time)
1. console.runpod.io → **Serverless** → **New Endpoint** → **GitHub Repo** → connect the
   GitHub account → pick `thumbgenius-worker` (branch main, Dockerfile at root).
2. GPU type: **RTX 4090** class (or 16 vCPU CPU tier — renderer is CPU-bound).
3. **Max Workers: 10** (this is the "10 videos at once" knob — raise anytime),
   Active Workers: 0 (zero idle cost), FlashBoot ON.
4. Container disk: 25 GB.
5. Env vars:
   - `GEMINI_KEY` = (the kie key — from C:\app\vidrush_style\runtime\gemini_key.txt)
   - `SUPABASE_URL` = https://<project-ref>.supabase.co   (Lovable → project settings)
   - `SUPABASE_SERVICE_KEY` = service-role key (Supabase dashboard → API)
   - `SUPABASE_BUCKET` = videos   (create a PUBLIC bucket named "videos" in Supabase Storage)
   - `YTDLP_PROXY` = http://USER:PASS@HOST:PORT  — **required for the YouTube channels/auto
     footage path.** RunPod workers have datacenter IPs that YouTube blocks, so without a
     residential proxy the footage download fails (this is why footage runs on the laptop
     today). Leave UNSET if you only accept uploaded clips. Paste it in the RunPod console
     ONLY — never commit it to GitHub or paste it in chat.
6. Deploy → wait for the image build (~10 min first time) → note the **Endpoint ID**.

## Footage proxy (only for the YouTube channels / auto path)
A RunPod worker's datacenter IP gets blocked by YouTube, so `yt-dlp` must go through a
**residential or rotating proxy**. Pick any residential-proxy provider (e.g. a pay-as-you-go
residential plan, ~$10-15/mo at low volume), get a `http://user:pass@host:port` endpoint, and
put it in the `YTDLP_PROXY` env var above. The code already routes every yt-dlp call through
it (`pipeline_sl.py` → `PX`). Cookies are NOT used and must never be put on the worker.
Uploaded-clips jobs skip download entirely and need no proxy.

Stable API (never changes):
- POST https://api.runpod.ai/v2/<ENDPOINT_ID>/run        body {"input":{audio_url,title,channels?}}
- GET  https://api.runpod.ai/v2/<ENDPOINT_ID>/status/<job_id>
- Auth header: Authorization: Bearer <RUNPOD_API_KEY>  (create in RunPod Settings → API Keys)

## 3. Site wiring (Supabase edge function keeps keys OFF the browser)
Paste lovable_prompt_serverless.txt into Lovable chat. It tells Lovable to:
- store the audio upload in Supabase Storage and pass its public URL as audio_url
- create a `video-jobs` edge function that proxies /run + /status with the RunPod key
  held as a Supabase secret (never exposed client-side)
- poll progress and show the final video from video_url

## Scaling & cost
- 10 simultaneous Generates → 10 workers spin up → all render in parallel (~15-20 min each)
- Billing: per second of work only. ~$0.25-0.40/video. 0 idle = $0 between jobs.
- Raise Max Workers to 20/50 in the endpoint settings as users grow.
