"""
Build-time download of the model weights into the image (no network at run
time, no network volume): python download_models.py en|mtl|turbo|asr

Pinned revisions, so a rebuild never picks up different weights silently.
Licences: ResembleAI/chatterbox and ResembleAI/chatterbox-turbo MIT;
openai/whisper-base.en Apache-2.0.
"""
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from huggingface_hub import hf_hub_download  # noqa: E402

ROOT = os.environ.get("TTS_MODELS_DIR", "/models")
CB, CB_REV = "ResembleAI/chatterbox", "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
TURBO, TURBO_REV = "ResembleAI/chatterbox-turbo", "749d1c1a46eb10492095d68fbcf55691ccf137cd"
WHISPER, WHISPER_REV = "openai/whisper-base.en", "911407f4214e0e1d82085af863093ec0b66f9cd6"

SETS = {
    "en": (CB, CB_REV, "chatterbox", ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]),
    "mtl": (CB, CB_REV, "chatterbox", ["ve.pt", "t3_mtl23ls_v3.safetensors", "s3gen.pt",
                                       "grapheme_mtl_merged_expanded_v1.json", "Cangjie5_TC.json", "conds.pt"]),
    "turbo": (TURBO, TURBO_REV, "chatterbox-turbo", ["ve.safetensors", "t3_turbo_v1.safetensors", "s3gen_meanflow.safetensors",
                                                     "conds.pt", "added_tokens.json", "merges.txt", "special_tokens_map.json",
                                                     "tokenizer_config.json", "vocab.json", "t3_turbo_v1.yaml"]),
    "asr": (WHISPER, WHISPER_REV, "whisper-base.en", ["config.json", "generation_config.json", "model.safetensors",
                                                     "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json",
                                                     "vocab.json", "merges.txt", "normalizer.json", "special_tokens_map.json",
                                                     "added_tokens.json"]),
}


def main(names):
    for name in names:
        repo, rev, sub, files = SETS[name]
        dest = os.path.join(ROOT, sub)
        os.makedirs(dest, exist_ok=True)
        for f in files:
            p = hf_hub_download(repo_id=repo, filename=f, revision=rev, local_dir=dest)
            print(f"{name}: {f} {os.path.getsize(p) / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or list(SETS))
