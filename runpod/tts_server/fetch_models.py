"""
Image build step: fetch the voice models at pinned revisions into MODELS_DIR.

Run once by the Dockerfile, never at request time. A revision is a commit of
the model repository on Hugging Face, so the files an image speaks with are
the files it was built with - a model updated upstream changes nothing until
the pin below is changed on purpose.

    Kokoro-82M   hexgrad/Kokoro-82M      Apache-2.0   weights + every voice pack (~360 MB)
    Chatterbox   ResembleAI/chatterbox   MIT          only with WITH_CHATTERBOX=1 (~3 GB)

The revisions can be overridden at build (--build-arg KOKORO_REVISION=...).
MANIFEST.json records what was fetched (repo, revision, file sizes); the
server's /health shows the revisions.
"""
import json
import os
import sys

MODELS_DIR = os.getenv("MODELS_DIR", "/opt/models")

# Pinned 2026-10-04 (the head of each repository's main branch that day).
MODELS = {
    "kokoro": {
        "repo": "hexgrad/Kokoro-82M",
        "revision": os.getenv("KOKORO_REVISION") or "f3ff3571791e39611d31c381e3a41a3af07b4987",
        "license": "Apache-2.0",
        "files": ["config.json", "kokoro-v1_0.pth", "voices/*.pt"],
        "need": ["config.json", "kokoro-v1_0.pth", "voices/af_heart.pt"],
    },
    "chatterbox": {
        "repo": "ResembleAI/chatterbox",
        "revision": os.getenv("CHATTERBOX_REVISION") or "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18",
        "license": "MIT",
        # Exactly what ChatterboxTTS.from_local reads (the English model).
        "files": ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"],
        "need": ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json"],
    },
}


def wanted() -> list:
    on = os.getenv("WITH_CHATTERBOX", "0").strip().lower() in {"1", "true", "yes", "on"}
    return ["kokoro"] + (["chatterbox"] if on else [])


def fetch(name: str) -> dict:
    from huggingface_hub import snapshot_download
    spec = MODELS[name]
    dest = os.path.join(MODELS_DIR, name)
    snapshot_download(repo_id=spec["repo"], revision=spec["revision"], allow_patterns=spec["files"],
                      local_dir=dest)
    missing = [f for f in spec["need"] if not os.path.isfile(os.path.join(dest, f))]
    if missing:
        raise SystemExit(f"{name}: {spec['repo']}@{spec['revision']} did not deliver {missing}")
    sizes = {}
    for root, _dirs, files in os.walk(dest):
        if ".cache" in root:
            continue
        for f in files:
            path = os.path.join(root, f)
            sizes[os.path.relpath(path, dest).replace("\\", "/")] = os.path.getsize(path)
    print(f"[models] {name}: {spec['repo']}@{spec['revision'][:12]} "
          f"{len(sizes)} files, {sum(sizes.values()) / 1e6:.0f} MB", flush=True)
    return {"repo": spec["repo"], "revision": spec["revision"], "license": spec["license"], "files": sizes}


def main() -> int:
    os.makedirs(MODELS_DIR, exist_ok=True)
    manifest = {name: fetch(name) for name in wanted()}
    with open(os.path.join(MODELS_DIR, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
