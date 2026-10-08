"""
Image build check (no GPU on the build machine): every module the three engines import is installed. A module
whose CUDA library needs the GPU driver (libcuda.so.1) cannot load without one - that alone is accepted;
anything else missing fails the build.
"""
import importlib
import os
import sys

sys.path[:0] = [os.environ.get("FLASHVSR_DIR", "/opt/FlashVSR"),
                os.path.join(os.environ.get("FLASHVSR_DIR", "/opt/FlashVSR"), "examples", "WanVSR"),
                os.environ.get("ACESTEP_DIR", "/opt/ACE-Step-1.5")]

MODULES = ["torch", "runpod", "requests", "numpy", "onnxruntime", "plan", "media", "r2", "rife_net", "textguard",
           "handler",
           "diffsynth", "utils.utils", "utils.TCDecoder", "block_sparse_attn",
           "acestep.handler", "acestep.llm_inference", "acestep.inference", "nanovllm", "flash_attn"]
bad = []
for name in MODULES:
    try:
        importlib.import_module(name)
        print("ok", name, flush=True)
    except ImportError as e:
        if "libcuda.so" in str(e):
            print("ok (needs the GPU driver)", name, flush=True)
        else:
            bad.append(f"{name}: {e}")
for f in ("/models/FlashVSR-v1.1/diffusion_pytorch_model_streaming_dmd.safetensors",
          "/models/FlashVSR-v1.1/LQ_proj_in.ckpt", "/models/FlashVSR-v1.1/TCDecoder.ckpt",
          os.environ.get("RIFE_MODEL", "/models/rife-4.25/flownet.pkl"),
          os.environ.get("TEXT_DET_MODEL", "/models/ppocr/ch_PP-OCRv4_det_infer.onnx")):
    if not os.path.isfile(f):
        bad.append(f"missing weights {f}")
if bad:
    raise SystemExit("smoke imports failed:\n  " + "\n  ".join(bad))
print("all imports ok")
