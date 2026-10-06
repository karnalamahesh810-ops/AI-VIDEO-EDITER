# ThumbGenius voice - RunPod serverless GPU worker (Resemble AI Chatterbox, MIT).
# Weights are baked in (no network volume, no download at start): a worker is
# ready as soon as the models are in GPU memory.
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TQDM_DISABLE=1 \
    TOKENIZERS_PARALLELISM=false \
    TTS_MODELS_DIR=/models

# ffmpeg: decoding samples (mp3/m4a/webm), rubberband tempo, MP3 encoding.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Weights first (own layers, ~10 GB): they change least, so code/dependency
# changes never re-download them.
RUN pip install "huggingface_hub>=1.3,<2.0"
COPY download_models.py ./
RUN python download_models.py en
RUN python download_models.py mtl
RUN python download_models.py turbo
RUN python download_models.py asr

COPY requirements.txt constraints.txt ./
RUN pip install -c constraints.txt torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124 \
    && pip install -c constraints.txt -r requirements.txt \
    && pip install --no-deps -c constraints.txt \
       "chatterbox-tts @ https://github.com/resemble-ai/chatterbox/archive/5de7a54aa4e5e2baadb0182dde554908b48b85c2.tar.gz" \
    && python -c "import torch, torchaudio, transformers, diffusers, perth, librosa, s3tokenizer, runpod; \
from chatterbox.tts import ChatterboxTTS; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; \
from chatterbox.tts_turbo import ChatterboxTurboTTS; \
print('torch', torch.__version__, 'transformers', transformers.__version__, 'imports ok')"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY *.py ./
COPY tests/ tests/
RUN python -m unittest discover -s tests -t . -v

# RunPod serverless ignores WORKDIR for the handler: absolute path.
CMD ["python", "-u", "/app/handler.py"]
