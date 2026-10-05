"""
Bake the local models into the image (run once at docker build).

* CLIP ViT-B/16, int8 ONNX (Xenova's transformers.js export, MIT) for
  src/localvision.py - ~150 MB.
* Real-ESRGAN general x4v3, ONNX (Qualcomm AI Hub release, BSD-3 model) for
  src/upscale.py - ~5 MB.
* YuNet face detector 2023mar, ONNX (OpenCV Zoo on Hugging Face, MIT) and
  U2-Net-p salient-object maps, ONNX (U-2-Net, Apache-2.0; the export rembg
  publishes) for src/reframe.py - 0.2 MB + 4.6 MB.
* Depth-Anything-V2-Small, fp32 ONNX (onnx-community's transformers.js
  export of depth-anything/Depth-Anything-V2-Small, Apache-2.0) for
  src/living.py - ~99 MB. Only the Small model: Depth-Anything-V2 Base and
  Large are CC-BY-NC (non-commercial) and must never be baked in.

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
# Smart reframing (src/reframe.py): faces, then the main object.
REFRAME_FILES = {
    "face_detection_yunet_2023mar.onnx": (
        "https://huggingface.co/opencv/face_detection_yunet/resolve/3cc26e7f1014a5ee5d74a42acee58bafc9d0a310/"
        "face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "u2netp.onnx": (
        "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
        "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"),
}
# Living photos (src/living.py): relative depth of a still. Apache-2.0 (the Small model only).
DEPTH_REPO = "onnx-community/depth-anything-v2-small"
DEPTH_REV = "4472b7362082ad9968fee890ca0f1e5aca36b93d"
DEPTH_FILE = ("onnx/model.onnx", "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c")
DEPTH_DEST = os.path.join("depth-anything-v2-small", "model.onnx")


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

    for name, (url, want) in REFRAME_FILES.items():
        data = get(url)
        if sha(data) != want:
            raise SystemExit(f"checksum mismatch for {name}")
        with open(os.path.join(ROOT, name), "wb") as fh:
            fh.write(data)
        print(f"reframe {name}: {len(data) // 1000} KB")

    name, want = DEPTH_FILE
    data = get(f"https://huggingface.co/{DEPTH_REPO}/resolve/{DEPTH_REV}/{name}")
    if sha(data) != want:
        raise SystemExit(f"checksum mismatch for {DEPTH_REPO}/{name}")
    dest = os.path.join(ROOT, DEPTH_DEST)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(data)
    print(f"depth {DEPTH_DEST}: {len(data) // 1_000_000} MB")


if __name__ == "__main__":
    main()
