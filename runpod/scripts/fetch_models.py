"""
Bake the local models into the image (run once at docker build).

* CLIP ViT-B/16, int8 ONNX (Xenova's transformers.js export, MIT) for
  src/localvision.py - ~150 MB.
* Real-ESRGAN general x4v3, ONNX (Qualcomm AI Hub release, BSD-3 model) for
  src/upscale.py - ~5 MB.

Every file is pinned to a revision and checked against its SHA-256; a
mismatch fails the build rather than shipping an unknown model.
"""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/opt/models"

CLIP_REPO = "Xenova/clip-vit-base-patch16"
CLIP_REV = "342fdf2f67aded64d138ff074745fb4a5d2bba5f"
CLIP_FILES = {
    "onnx/vision_model_quantized.onnx": "44eece4fe5fe4e0359a88268a327adf758633a1aade3917690b952bef1501f96",
    "onnx/text_model_quantized.onnx": "9106b51e6c663a56b99182ec617c2b3d53577b037e7e24a7717eb78048a0c97a",
    "tokenizer.json": "72ed5c96db5729294468543e4bc75fce14ca63f58e37300290189ba1c1e52b85",
}
ESRGAN_URL = ("https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/"
              "real_esrgan_general_x4v3/releases/v0.63.0/real_esrgan_general_x4v3-onnx-float.zip")
ESRGAN_ZIP_SHA = "a468eb143dee386191c81b6c6d1791575f304e5c0802eea4da04afdebd95d4e4"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "thumbgenius-build/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main() -> None:
    clip_dir = os.path.join(ROOT, "clip-vit-base-patch16")
    for name, want in CLIP_FILES.items():
        data = get(f"https://huggingface.co/{CLIP_REPO}/resolve/{CLIP_REV}/{name}")
        if sha(data) != want:
            raise SystemExit(f"checksum mismatch for {name}")
        dest = os.path.join(clip_dir, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        print(f"clip {name}: {len(data) // 1_000_000} MB")

    data = get(ESRGAN_URL)
    if sha(data) != ESRGAN_ZIP_SHA:
        raise SystemExit("checksum mismatch for the Real-ESRGAN release")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base.endswith((".onnx", ".data")):
                with open(os.path.join(ROOT, base), "wb") as fh:
                    fh.write(z.read(member))
                print(f"esrgan {base}")


if __name__ == "__main__":
    main()
