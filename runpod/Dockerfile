# ThumbGenius video worker — yt-dlp + ffmpeg + faster-whisper + Remotion
# Single image: Python handler drives a Node/Remotion renderer.
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    NODE_VERSION=20 \
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
    && rm -rf /var/lib/apt/lists/*

# --- node --------------------------------------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- python deps -------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- remotion (install deps first for layer caching) -------------------------
COPY remotion/package.json remotion/
RUN cd remotion && npm install --no-audit --no-fund

COPY remotion/ remotion/
# Pre-download the headless browser so the first render isn't a cold 60s stall.
RUN cd remotion && npx remotion browser ensure || true

# --- app ---------------------------------------------------------------------
COPY handler.py .
COPY src/ src/

RUN mkdir -p ${WORK_DIR}

CMD ["python", "-u", "handler.py"]
