# ThumbGenius video worker — yt-dlp + ffmpeg + faster-whisper + Remotion
# Single image: Python handler drives a Node/Remotion renderer.
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    NODE_VERSION=22 \
    REMOTION_DIR=/app/remotion \
    WORK_DIR=/tmp/work

# --- system deps -------------------------------------------------------------
# ffmpeg: trimming/concat/audio. The rest are Chrome headless deps for Remotion.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg xz-utils git \
      ffmpeg fonts-liberation fonts-dejavu-core \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
      libpango-1.0-0 libcairo2 libatspi2.0-0 \
      libjpeg62-turbo libgif7 librsvg2-2 \
    && rm -rf /var/lib/apt/lists/*

# --- node --------------------------------------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- YouTube PO-token server (bgutil) ----------------------------------------
# YouTube answers datacenter IPs - every RunPod machine - with "Sign in to
# confirm you're not a bot" unless the request carries a proof-of-origin
# token. This server mints them; yt-dlp's bgutil plugin (requirements.txt)
# fetches one per request. Started by scripts/start.sh. Pinned commit.
RUN git init /opt/bgutil \
    && cd /opt/bgutil \
    && git fetch --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider 2d758ea29ae5c65886bdf56c42ebbdfe17d78bbb \
    && git checkout FETCH_HEAD \
    && cd server && npm ci --no-audit --no-fund && npx tsc \
    && rm -rf /opt/bgutil/.git

WORKDIR /app

# --- python deps -------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- local models ------------------------------------------------------------
# CLIP (local vision checks, src/localvision.py), Real-ESRGAN (photo
# upscaling, src/upscale.py), YuNet + U2-Net-p (src/reframe.py) and
# Depth-Anything-V2-Small (living photos, src/living.py; Apache-2.0):
# pinned + checksummed, ~260 MB, own layer.
COPY scripts/fetch_models.py /tmp/fetch_models.py
RUN python /tmp/fetch_models.py /opt/models && rm /tmp/fetch_models.py

# --- remotion (install deps first for layer caching) -------------------------
COPY remotion/package.json remotion/
RUN cd remotion && npm install --no-audit --no-fund

COPY remotion/ remotion/
# Pre-download the headless browser so the first render isn't a cold 60s stall.
RUN cd remotion && npx remotion browser ensure || true

# --- app ---------------------------------------------------------------------
COPY handler.py .
COPY src/ src/
# Tests and the overlay preview are a few KB and make the image able to check
# itself: `python -m unittest discover -s tests -t .` inside a running worker.
COPY tests/ tests/
COPY scripts/ scripts/
# The seven benchmark narrations (bench/README.md): ~2.5 MB, so a benchmark
# run needs no upload and no credentials (audio_url "bench://<case>").
COPY bench/ bench/

# The Remotion project bundled once, here (src/render.py ensure_bundle), so no
# render pays webpack and the 140 MB public/ copy at run time. Named by a hash
# of remotion/src, so a stale bundle is never used; if this step fails, the
# first render builds it instead.
ENV RENDER_BUNDLE_DIR=/opt/remotion-bundles
RUN python -c "from src import render; print('bundle:', render.ensure_bundle() or 'built at the first render instead')" || true

RUN mkdir -p ${WORK_DIR}

CMD ["sh", "scripts/start.sh"]
