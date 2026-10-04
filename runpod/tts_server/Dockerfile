# ThumbGenius voice endpoint - Kokoro (Apache-2.0), optionally Chatterbox (MIT).
# A separate, GPU image: the video worker (../Dockerfile) stays CPU-only and
# calls this one over HTTP (TTS_API_BASE). Build from this folder:
#
#   docker build -t <registry>/thumbgenius-tts:kokoro .
#   docker build -t <registry>/thumbgenius-tts:chatterbox --build-arg WITH_CHATTERBOX=1 .
#
# Base: PyTorch 2.6.0 + CUDA 12.4 runtime, Python 3.11 (Chatterbox pins torch
# 2.6.0; Kokoro needs Python < 3.13). The tag's linux/amd64 digest on
# 2026-10-04 was sha256:77f17f843507062875ce8be2a6f76aa6aa3df7f9ef1e31d9d7432f4b0f563dee.
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ARG WITH_CHATTERBOX=0
ARG KOKORO_REVISION=
ARG CHATTERBOX_REVISION=

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODELS_DIR=/opt/models \
    WITH_CHATTERBOX=${WITH_CHATTERBOX}

# ffmpeg: the answer's format (flac, mp3 ...) and reading a voice sample.
# espeak-ng: Kokoro's fallback for words its dictionary does not know.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg espeak-ng ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- python deps (own layer) -------------------------------------------------
COPY requirements.txt requirements-chatterbox.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_CHATTERBOX" = "1" ]; then pip install -r requirements-chatterbox.txt; fi
# Kokoro's English front end reads spaCy's small English model; fetched here
# (the version that matches the installed spaCy) so nothing is at run time.
RUN python -m spacy download en_core_web_sm

# --- models (own layer, pinned revisions: fetch_models.py) --------------------
COPY fetch_models.py .
RUN KOKORO_REVISION=${KOKORO_REVISION} CHATTERBOX_REVISION=${CHATTERBOX_REVISION} python fetch_models.py

# From here on nothing may reach for the hub: what is in the image is what speaks.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# --- app ---------------------------------------------------------------------
COPY engines.py server.py rp_handler.py ./

# A RunPod queue endpoint by default (rp_handler.py). TTS_SERVE=http runs the
# OpenAI-compatible HTTP server instead (a pod, or a RunPod load-balancing
# endpoint: /ping is its health check, PORT its port).
ENV TTS_SERVE=runpod \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "if [ \"$TTS_SERVE\" = \"http\" ]; then exec uvicorn server:app --host 0.0.0.0 --port \"$PORT\"; else exec python -u rp_handler.py; fi"]
