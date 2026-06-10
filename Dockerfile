# ThumbGenius video worker — RunPod Serverless image
# Everything baked in: node20 + chrome deps + ffmpeg + whisper model + remotion (npm installed)
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    ffmpeg curl ca-certificates gnupg unzip \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 fonts-liberation \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y -qq nodejs \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# python deps
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# bake the whisper model (no HF download at job time)
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"

# remotion project (npm install + headless chrome at BUILD time)
COPY remotion /app/remotion
WORKDIR /app/remotion
RUN npm install --no-audit --no-fund && npx remotion browser ensure

# pipeline + handler + static assets (sfx)
COPY runtime_assets /app/runtime_assets
COPY pipeline_sl.py handler.py /app/
WORKDIR /app

CMD ["python3", "-u", "handler.py"]
