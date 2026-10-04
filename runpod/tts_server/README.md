# ThumbGenius voice endpoint (free voices)

Script -> video needs a narration. Premium voices are made in the app and reach
the video worker as `audio_url`. This folder is the **free** path: our own
text-to-speech endpoint on a RunPod GPU, billed by the second it runs and not
by the character.

| Engine | What it is | Licence | When |
|---|---|---|---|
| **Kokoro-82M** | small, fast, 50+ built-in voices (`af_heart`, `am_michael`, `bm_george` ...) | Apache-2.0 (weights and code) | always on |
| **Chatterbox** | clones a voice from a 10-30 s sample; about real time | MIT (weights and code) | only in an image built with `WITH_CHATTERBOX=1` |

**Status (2026-10-04): written and tested offline only.** The image has not
been built and no model has been run on a GPU yet - see "First deploy" below.

## Files

| File | Job |
|---|---|
| `engines.py` | loads the models, voices one request (`speak`), encodes the answer |
| `server.py` | FastAPI: `POST /v1/audio/speech`, `GET /health`, `/ping`, `/v1/audio/voices` |
| `rp_handler.py` | the same engines as a RunPod queue (serverless) worker |
| `fetch_models.py` | image build: downloads the models at pinned revisions |
| `Dockerfile`, `requirements*.txt` | the GPU image |

## The API

```
POST /v1/audio/speech
{"model": "kokoro", "voice": "af_heart", "input": "Lake Mead is falling.",
 "response_format": "flac", "speed": 1.0}
-> the audio (wav, flac, mp3, opus, aac or pcm), headers X-Audio-Seconds, X-Gpu-Seconds
```

- `model`: `kokoro` (also answers to OpenAI's `tts-1`) or `chatterbox`.
- `voice` (Kokoro): one name, or `af_heart,af_bella` for an even blend. OpenAI's
  names (`alloy`, `onyx` ...) are mapped to the nearest Kokoro voice.
- Chatterbox only: `reference_audio` (a link, a `data:` URI or bare base64 of a
  10-30 s sample; without it the built-in voice speaks), `exaggeration` (0.5),
  `cfg_weight` (0.5), `temperature` (0.8). `speed` is applied by time-stretching.
- Errors use OpenAI's shape. A request that can never work (unknown voice,
  Chatterbox not in the image, a sample that is not audio) is a 400; the queue
  handler answers `{"refused": "why"}` so the worker does not retry it.
- Limits: `input` up to 6,000 characters (`TTS_MAX_INPUT_CHARS`; the worker sends
  1,500), at most 4 blended voices, a request body up to `TTS_MAX_BODY_BYTES`
  (~41 MB, a 413 past it; RunPod's own limit is 10 MB on `/run`, 20 MB on `/runsync`).
- A voice sample link must resolve to public internet addresses only (never
  this machine or a private network; every redirect is checked again), and a
  sample is decoded as a plain audio file only - never as a list or playlist
  that names other files.

On a RunPod **queue** endpoint the same fields go in `{"input": {...}}` to
`/runsync`, and the audio comes back as `output.audio_base64`.

## Licences and what they ask of us

| Part | Licence | Note |
|---|---|---|
| Kokoro-82M weights, `kokoro` library, `misaki` (text to phonemes) | Apache-2.0 | commercial use allowed; keep the notice |
| Chatterbox weights and `chatterbox-tts` | MIT | commercial use allowed; keep the notice |
| `resemble-perth` (inside Chatterbox) | MIT | every Chatterbox output carries an inaudible watermark |
| spaCy and `en_core_web_sm` | MIT | |
| espeak-ng (apt), and `phonemizer-fork` + `espeakng-loader` (pulled in by `misaki[en]`) | GPL-3.0 | Kokoro's fallback for words its dictionary does not know; fine to run on our own endpoint, and the audio it makes is ours. Do not hand the image to others without the GPL notice and sources |
| `pykakasi` (pulled in by `chatterbox-tts`, Chatterbox image only) | GPL-3.0 | same as above; `gradio` (Apache-2.0) comes along too |
| PyTorch | BSD-3 | |
| FastAPI, uvicorn | MIT / BSD-3 | |
| ffmpeg (Debian build) | GPL/LGPL | separate program |

**Voice cloning rule:** only clone a voice the owner has the right to use (his
own, or with the speaker's written consent). A cloned voice of a real person
without consent is a legal and a YouTube-policy problem, not a technical one.

This is a summary for the team, not legal advice.

## Models are pinned

`fetch_models.py` downloads at image build, never at request time:

| Model | Repository | Revision (2026-10-04) |
|---|---|---|
| Kokoro-82M | `hexgrad/Kokoro-82M` | `f3ff3571791e39611d31c381e3a41a3af07b4987` |
| Chatterbox | `ResembleAI/chatterbox` | `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18` |

Python packages: `kokoro==0.9.4`, `misaki[en]==0.9.4`, `chatterbox-tts==0.1.7`
(which itself pins `torch==2.6.0`, the base image's version). After the first
good build, run `pip freeze` in the image and commit it as `requirements.lock`
so every later build is identical.

Checked 2026-10-04 against the Hugging Face API at the pinned revisions: both
repositories are public and ungated, Kokoro's card says `apache-2.0`, Chatterbox's
`mit`; the files fetched are exactly `config.json`, `kokoro-v1_0.pth` and the 54
`voices/*.pt` packs, and `ve`/`t3_cfg`/`s3gen.safetensors`, `tokenizer.json`,
`conds.pt` (what `chatterbox-tts` 0.1.7's `from_local` reads). Not yet built:
`chatterbox-tts` 0.1.7 also pins `transformers==5.2.0`, `numpy<2` and
`gradio==6.8.0`, so the Chatterbox image must be smoke-tested with **both**
engines (Kokoro imports transformers' ALBERT) before it is used.

## First deploy

1. **Build and push** (from this folder; needs Docker and a registry):
   ```
   docker build -t <registry>/thumbgenius-tts:kokoro .
   docker build -t <registry>/thumbgenius-tts:chatterbox --build-arg WITH_CHATTERBOX=1 .
   docker push <registry>/thumbgenius-tts:kokoro
   ```
   If the build stops at `fetch_models.py` with a 404, a revision above is wrong
   or was removed: look up the current one on the model's page and pass
   `--build-arg KOKORO_REVISION=<sha>`.
2. **Smoke test on any machine with the image** (CPU works for Kokoro, slowly):
   ```
   docker run --rm -p 8000:8000 -e TTS_SERVE=http <registry>/thumbgenius-tts:kokoro
   curl -s localhost:8000/health
   curl -s localhost:8000/v1/audio/speech -H "Content-Type: application/json" \
     -d '{"model":"kokoro","voice":"af_heart","input":"Lake Mead is falling.","response_format":"mp3"}' -o test.mp3
   ```
   Listen to `test.mp3`. With the Chatterbox image, repeat with
   `"model":"chatterbox"` and a `reference_audio` link.
3. **RunPod serverless endpoint** (queue type):
   - GPU: Kokoro needs under 2 GB of GPU memory - the 16 GB tier (A4000 / A4500 /
     RTX 4000 / RTX 2000, $0.58/h) is enough, with 24 GB (L4 / A5000 / 3090, $0.69/h)
     as a second choice for availability. Chatterbox: 24 GB (3090 / A5000; the L4 is
     slow for it) or the 4090 tier ($1.10/h, about twice as fast).
   - Container disk 20 GB; no network volume needed (the models are in the image).
   - Max workers 4 (the video worker voices 4 parts at once), min workers 0,
     idle timeout 5 s, FlashBoot on.
   - **The account has 10 workers across all endpoints**, and on 2026-09-28 the
     video endpoint (`tuxcziwby5plod`) had all 10: lower its max to 6-8 (only while
     no job runs) or have RunPod raise the quota first, or this endpoint cannot be
     created with any workers.
   - **Leave "Container Start Command" empty** - a template's start command
     overrides the image's and the handler never starts.
   - Environment: nothing required. Optional: `TTS_PRELOAD=kokoro,chatterbox`,
     `TTS_DEFAULT_VOICE`, `WITH_CHATTERBOX=0` to switch Chatterbox off.
4. **Point the video worker at it** (its endpoint's environment):
   ```
   TTS_API_BASE=https://api.runpod.ai/v2/<voice endpoint id>
   TTS_API_KEY=<a RunPod API key>
   ```
   The worker's `/health` then shows `"freeVoice": {"configured": true, ...}`.

Instead of a queue endpoint the image can serve HTTP (`TTS_SERVE=http`) on a GPU
pod or a RunPod load-balancing endpoint; then `TTS_API_BASE` is that address
and `TTS_API_MODE=openai`. Set `TTS_SERVER_KEY` on the server and the same
value as the worker's `TTS_API_KEY` when nothing else guards the port.

## Video worker settings (`runpod/src/config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `TTS_API_BASE` | empty = off | the voice endpoint; without it a script-only job is refused with a clear message |
| `TTS_API_KEY` | empty | sent as `Authorization: Bearer` |
| `TTS_API_MODE` | `auto` | `runpod` for `api.runpod.ai/v2/<id>`, else `openai`; or force one |
| `TTS_MODEL` | `kokoro` | or `chatterbox` |
| `TTS_VOICE` | `af_heart` | Kokoro voice |
| `TTS_SPEED` | `1.0` | 0.5-2.0 |
| `TTS_REFERENCE_AUDIO` | empty | voice sample (link or file) for Chatterbox cloning; never sent with a Kokoro model (the endpoint would refuse every part) |
| `TTS_FIELDS`, `TTS_EXTRA` | empty | JSON: rename request fields / add fields, for another server |
| `TTS_FORMAT` | `flac` | what each part comes back as |
| `TTS_OUTPUT_FORMAT` | `mp3` | what the narration is stored as (128 kbit/s, 44.1 kHz mono) |
| `TTS_CHUNK_CHARS` | `1500` | longest part, cut at sentence ends |
| `TTS_WORKERS` | `4` | parts voiced at once |
| `TTS_TIMEOUT` | `600` | seconds per part (a cold worker loads its model first) |
| `TTS_RETRIES` | `3` | extra attempts per part |
| `TTS_TOTAL_SECONDS` | `1800` | the whole narration, every part, retry and cold start; past it the jobs still running are cancelled and the video stops with a plain message (0 = no limit) |
| `TTS_GAP_SECONDS` | `0.3` | the breath between two parts |
| `TTS_LUFS` | `0` = -20 | narration loudness (the worker's own narration level) |
| `TTS_MAX_CHARS` | `120000` | longest script (about two hours) |

A job may override the voice: `tts_voice`, `tts_model`, `tts_speed`,
`tts_reference_audio` (a link only).

## What a job looks like

```
{"action": "build", "project_id": "...", "title": "...",
 "script": "Lake Mead is falling. ...",          <- and NO audio_url
 "tts_voice": "am_michael"}
```

The worker reports "Making the narration (free voice)", stores the narration on
Cloudflare R2 (`projects/<id>/audio/narration-<token>.mp3`), continues exactly
as with an uploaded voice-over (whisper still measures the word timings), and
returns `audio_url` and `narration` (voice, seconds, loudness) in its result
and in `timeline.meta`.

## Cost - an ESTIMATE, not a measurement

RunPod serverless (flex) on their price page, 2026-10-04: 16 GB $0.58/h ($0.00016/s),
24 GB (A5000 / L4 / 3090) $0.69/h ($0.00019/s), 24 GB 4090 $1.10/h. Start-up and the
5 s idle are billed too. The video worker (16 vCPU, ~$0.58/h) waits while the voice works.

| 20-minute narration (~18,000 characters, 12-13 parts) | GPU time (estimate) | Cost (estimate) |
|---|---|---|
| Kokoro | ~25-35 s of voicing (about 50x real time) + up to 4 cold starts of ~25 s + idle | **about 1-3 cents** |
| Chatterbox | ~10-20 minutes of voicing (about real time, spread over 4 workers) + cold starts | **about 15-30 cents** |

Nobody has measured these on our endpoint yet. The worker counts
`tts.seconds` (priced at an estimated $0.000025 per narration second, the
Kokoro case) and `tts.gpu_seconds` (what the endpoint reported, not priced);
after the first real narrations, compare the two with RunPod's bill and
correct `tts.seconds` in the price table (`PRICES` or the app's
`provider_prices`). With Chatterbox use about $0.0002.
