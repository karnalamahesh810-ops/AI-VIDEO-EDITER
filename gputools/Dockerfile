# ThumbGenius GPU tools - RunPod serverless GPU worker (endpoint "thumbgenius-gpu-tools"; the video worker's client
# is runpod/src/gputools.py). Three tools in one image, each loaded on its first job:
#   FlashVSR v1.1 (Apache-2.0) + Block-Sparse-Attention (BSD-3)  - clips under 720 lines -> 1080 lines
#   RIFE 4.25 / Practical-RIFE (MIT)                               - real 60 fps
#   ACE-Step 1.5 (MIT, code and weights)                           - a music bed made for each video
# One torch for all three: ACE-Step 1.5's locked environment (Python 3.11, torch 2.10 / CUDA 12.8, flash-attn
# 2.8.3). Needs a driver for CUDA >= 12.8 (the endpoint's allowed CUDA versions). Ampere / Ada GPUs (sm_80-89):
# Block-Sparse-Attention is built for sm_80 (+PTX); exclude Blackwell MIG slices from the endpoint's GPU list.
# Feasibility on an A40 (VRAM, speed, quality): gpu_tools_test/notes.md.

ARG ACE_COMMIT=ca1e85fe9430179831e6bc6be790c332190a3866
ARG FLASHVSR_COMMIT=cf910c6
ARG BSA_COMMIT=49d6c39
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.23

# ---- stage 1: the Block-Sparse-Attention wheel, compiled against the runtime's torch: FlashVSR's one kernel, sm_80 ----
FROM ${UV_IMAGE} AS uv
FROM nvidia/cuda:12.8.1-devel-ubuntu22.04 AS bsa
ARG BSA_COMMIT
ENV DEBIAN_FRONTEND=noninteractive UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/uvpython
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential ninja-build \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
RUN uv venv /opt/build --python 3.11 \
    && uv pip install --python /opt/build/bin/python torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --python /opt/build/bin/python packaging ninja psutil wheel "setuptools<72"
RUN git clone https://github.com/mit-han-lab/Block-Sparse-Attention.git /src/bsa \
    && cd /src/bsa && git checkout ${BSA_COMMIT} && git submodule update --init csrc/cutlass
COPY bsa_flashvsr_only.py /src/
# One kernel (forward, bf16, head dim 128) + the API: one nvcc job peaks near 8-9 GB (GitHub's runners have 16 GB)
RUN cd /src/bsa && /opt/build/bin/python /src/bsa_flashvsr_only.py \
    && CUDA_HOME=/usr/local/cuda BLOCK_SPARSE_ATTN_CUDA_ARCHS=80 BLOCK_SPARSE_ATTN_FORCE_BUILD=TRUE MAX_JOBS=2 \
       NVCC_THREADS=2 /opt/build/bin/python setup.py bdist_wheel -d /wheels \
    && ls -la /wheels

# ---- stage 2: the worker ----
FROM python:3.11-slim-bookworm
ARG ACE_COMMIT
ARG FLASHVSR_COMMIT
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TQDM_DISABLE=1 \
    TOKENIZERS_PARALLELISM=false \
    MODELS_DIR=/models \
    FLASHVSR_DIR=/opt/FlashVSR \
    FLASHVSR_MODELS=/models/FlashVSR-v1.1 \
    RIFE_MODEL=/models/rife-4.25/flownet.pkl \
    ACESTEP_DIR=/opt/ACE-Step-1.5 \
    ACESTEP_CHECKPOINTS_DIR=/models/acestep \
    ACESTEP_LM=acestep-5Hz-lm-1.7B \
    TEXT_DET_MODEL=/models/ppocr/ch_PP-OCRv4_det_infer.onnx \
    FLASHVSR_PIPELINE=tiny

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git ca-certificates libgl1 libglib2.0-0 \
    libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv

# ACE-Step 1.5 at the commit tested on 2026-10-09, in its own locked environment = the venv every tool runs in
RUN git clone https://github.com/ace-step/ACE-Step-1.5.git /opt/ACE-Step-1.5 \
    && cd /opt/ACE-Step-1.5 && git checkout ${ACE_COMMIT} && rm -rf .git \
    && UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev --python /usr/local/bin/python3.11 \
    && rm -rf /root/.cache/uv
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH

# FlashVSR v1.1's code (used from its folder: its setup.py needs pkg_resources, its pins are torch 2.6-era) and
# what its imports need on top of ACE-Step's environment; the Block-Sparse-Attention wheel from stage 1.
RUN git clone https://github.com/OpenImagingLab/FlashVSR.git /opt/FlashVSR \
    && cd /opt/FlashVSR && git checkout ${FLASHVSR_COMMIT} && rm -rf .git examples/WanVSR/inputs \
    && uv pip install imageio imageio-ffmpeg opencv-python-headless ftfy sentencepiece "protobuf<5" runpod==1.7.7 \
       "requests>=2.31" "onnxruntime>=1.20,<1.24" && rm -rf /root/.cache/uv
COPY --from=bsa /wheels/ /tmp/wheels/
RUN uv pip install /tmp/wheels/block_sparse_attn-*.whl && rm -rf /tmp/wheels /root/.cache/uv

# Weights in their own layers (~14 GB): FlashVSR (bf16), RIFE 4.25, ACE-Step 1.5, the PP-OCRv4 text detector
WORKDIR /app
COPY download_models.py ./
RUN python download_models.py flashvsr
RUN python download_models.py rife
RUN python download_models.py acestep && rm -rf /root/.cache/huggingface
RUN python download_models.py textdet

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY *.py ./
COPY tests/ tests/
# The pure helpers' tests, and every module imports (a missing package fails the build here, not on a GPU).
RUN python -m unittest discover -s tests -t . -v && python smoke_imports.py

CMD ["python", "-u", "/app/handler.py"]
