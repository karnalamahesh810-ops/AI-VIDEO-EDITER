"""
Bakes the GPU tools' weights into the image (run in the Dockerfile; the worker runs with HF_HUB_OFFLINE=1):

  flashvsr  JunhaoZhuang/FlashVSR-v1.1 (Apache-2.0): the tiny pipeline's DiT (stored as bf16: the pipeline runs
            in bf16 anyway; halves 5.7 GB), LQ_proj_in.ckpt, TCDecoder.ckpt          -> /models/FlashVSR-v1.1
  rife      Practical-RIFE 4.25 (MIT): flownet.pkl from the release zip on the author's Google Drive (the link in
            the Practical-RIFE README), checked against its SHA-256                    -> /models/rife-4.25
  acestep   ACE-Step/Ace-Step1.5 (MIT): the turbo DiT, VAE, Qwen3-Embedding text encoder; the 5 Hz LM named by
            ACESTEP_LM (default acestep-5Hz-lm-1.7B from the main repo; acestep-5Hz-lm-0.6B from its own repo)
                                                                                       -> /models/acestep
  textdet   PaddleOCR PP-OCRv4 text detector (Apache-2.0) as RapidOCR ships it in ONNX (rapidocr-onnxruntime
            1.4.4 wheel on PyPI, Apache-2.0), checked against its SHA-256 - the HD boost's text guard
                                                                                       -> /models/ppocr

    python download_models.py flashvsr|rife|acestep|textdet|all
"""
import hashlib
import io
import os
import sys
import zipfile

MODELS = os.environ.get("MODELS_DIR", "/models")
RIFE_ZIP_ID = "1ZKjcbmt1hypiFprJPIKW0Tt0lr_2i7bg"              # RIFEv4.25_0919.zip
RIFE_ZIP_SHA256 = "e63d481b7ae5d4a4e6ad7ac5b410ff78f3bf7be3b51b2e38ca8152747abde5b4"
TEXTDET_MEMBER = "rapidocr_onnxruntime/models/ch_PP-OCRv4_det_infer.onnx"
TEXTDET_SHA256 = "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9"


def flashvsr():
    import torch
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file, save_file
    dst = os.path.join(MODELS, "FlashVSR-v1.1")
    os.makedirs(dst, exist_ok=True)
    for f in ("LQ_proj_in.ckpt", "TCDecoder.ckpt"):
        p = hf_hub_download("JunhaoZhuang/FlashVSR-v1.1", f, local_dir=dst)
        print(f, os.path.getsize(p), flush=True)
    name = "diffusion_pytorch_model_streaming_dmd.safetensors"
    p = hf_hub_download("JunhaoZhuang/FlashVSR-v1.1", name, local_dir=os.path.join(dst, "_fp32"))
    sd = load_file(p)
    sd = {k: (v.to(torch.bfloat16) if v.is_floating_point() else v) for k, v in sd.items()}
    save_file(sd, os.path.join(dst, name))
    os.remove(p)
    for root, dirs, files in os.walk(os.path.join(dst, "_fp32"), topdown=False):
        for f in files:
            os.remove(os.path.join(root, f))
        for d in dirs:
            os.rmdir(os.path.join(root, d))
    os.rmdir(os.path.join(dst, "_fp32"))
    print(name, "(bf16)", os.path.getsize(os.path.join(dst, name)), flush=True)


def rife():
    import requests
    r = requests.get("https://drive.usercontent.google.com/download",
                     params={"id": RIFE_ZIP_ID, "export": "download", "confirm": "t"}, timeout=600)
    if r.status_code != 200 or hashlib.sha256(r.content).hexdigest() != RIFE_ZIP_SHA256:
        raise SystemExit(f"RIFE 4.25 zip: HTTP {r.status_code}, {len(r.content)} bytes, sha256 mismatch or missing")
    dst = os.path.join(MODELS, "rife-4.25")
    os.makedirs(dst, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        open(os.path.join(dst, "flownet.pkl"), "wb").write(z.read("train_log/flownet.pkl"))
    print("flownet.pkl", os.path.getsize(os.path.join(dst, "flownet.pkl")), flush=True)


def acestep():
    from huggingface_hub import snapshot_download
    dst = os.path.join(MODELS, "acestep")
    lm = os.environ.get("ACESTEP_LM", "acestep-5Hz-lm-1.7B")
    skip = [] if lm == "acestep-5Hz-lm-1.7B" else ["acestep-5Hz-lm-1.7B/*"]
    snapshot_download("ACE-Step/Ace-Step1.5", local_dir=dst, ignore_patterns=skip or None)
    if lm != "acestep-5Hz-lm-1.7B":
        snapshot_download(f"ACE-Step/{lm}", local_dir=os.path.join(dst, lm))
    for name in sorted(os.listdir(dst)):
        print("acestep:", name, flush=True)


def textdet():
    import requests
    # the wheel's own address from PyPI's JSON API (uv venvs have no pip), then only the detector is taken from it
    meta = requests.get("https://pypi.org/pypi/rapidocr-onnxruntime/1.4.4/json", timeout=60).json()
    url = next(u["url"] for u in meta["urls"] if u["filename"].endswith("-py3-none-any.whl"))
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        data = z.read(TEXTDET_MEMBER)
    if hashlib.sha256(data).hexdigest() != TEXTDET_SHA256:
        raise SystemExit("PP-OCRv4 detector: sha256 mismatch")
    dst = os.path.join(MODELS, "ppocr")
    os.makedirs(dst, exist_ok=True)
    open(os.path.join(dst, "ch_PP-OCRv4_det_infer.onnx"), "wb").write(data)
    print("ch_PP-OCRv4_det_infer.onnx", len(data), flush=True)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    for step in (("flashvsr", flashvsr), ("rife", rife), ("acestep", acestep), ("textdet", textdet)):
        if what in (step[0], "all"):
            step[1]()
