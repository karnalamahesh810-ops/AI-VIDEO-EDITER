"""
Qwen3-TTS engine (Qwen/Qwen3-TTS-12Hz-1.7B-Base, Apache-2.0) - the ThumbGenius voice
since the 2026-10-07 bake-off (closest to the owner's real voice of the fast
models, most natural by UTMOS, ~3x faster than the others because a whole part
is generated as one batch).

Cloning is "in-context": the model continues from the reference audio AND its
transcript, which keeps accent and delivery (Chatterbox's speaker-embedding
cloning flattened both). Presets come with their transcript; a clone's sample
is transcribed here once (Whisper large-v3-turbo) and cached by its hash.

QwenHost has the same shape as engine.ModelHost, so handler.py and the
replica pool work unchanged; its unit of work is a whole part ("op": "part"):
every piece in one batch, each checked (length + Whisper read-back), and the
pieces that came out wrong are made again together with a new seed.
"""
from __future__ import annotations

import os
import random
import time
from collections import OrderedDict
from typing import Dict, List, Optional

import numpy as np

from audio import load_any, trim
from textnorm import expected_seconds, word_error_rate, words_for_compare

MODELS_DIR = os.environ.get("TTS_MODELS_DIR", "/models")
QWEN_DIR = f"{MODELS_DIR}/qwen3-tts-1.7b-base"
WHISPER_DIR = f"{MODELS_DIR}/whisper-large-v3-turbo"

LANG_NAMES = {"en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German", "fr": "French",
              "ru": "Russian", "pt": "Portuguese", "es": "Spanish", "it": "Italian"}

DEFAULTS = {"temperature": 0.9, "top_p": 1.0, "top_k": 50, "repetition_penalty": 1.05}


def seed_all(seed: int) -> None:
    import torch
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class QwenHost:
    def __init__(self, device: str = "cuda", want_asr: bool = True):
        self.device = device
        self.want_asr = want_asr
        self.model = None
        self.name: Optional[str] = None
        self.prompts: "OrderedDict[str, object]" = OrderedDict()
        self.ref_texts: Dict[str, str] = {}
        self.asr = None
        self.asr_fe = None
        self.asr_tok = None
        self.sr = 24000
        self.load_seconds: Dict[str, float] = {}

    def load(self, name: str = "qwen"):
        if self.model is not None:
            return self.model
        import torch
        from qwen_tts import Qwen3TTSModel
        t0 = time.time()
        self.model = Qwen3TTSModel.from_pretrained(QWEN_DIR, device_map=self.device, dtype=torch.bfloat16,
                                                   attn_implementation="sdpa")
        self.name = "qwen"
        self.load_seconds["qwen"] = round(time.time() - t0, 2)
        return self.model

    # -- speech recognition (reference transcripts + read-back check) -------------------------
    def transcribe(self, wav: np.ndarray, sr: int, lang: str = "en") -> str:
        import torch
        if self.asr is None:
            from transformers import WhisperFeatureExtractor, WhisperForConditionalGeneration, WhisperTokenizer
            self.asr_fe = WhisperFeatureExtractor.from_pretrained(WHISPER_DIR)
            self.asr_tok = WhisperTokenizer.from_pretrained(WHISPER_DIR)
            self.asr = WhisperForConditionalGeneration.from_pretrained(WHISPER_DIR, torch_dtype=torch.float16).to(self.device).eval()
        import librosa
        y = librosa.resample(np.asarray(wav, np.float32), orig_sr=sr, target_sr=16000)[: 16000 * 30]
        feats = self.asr_fe(y, sampling_rate=16000, return_tensors="pt").input_features.to(self.device, torch.float16)
        with torch.inference_mode():
            ids = self.asr.generate(feats, language=lang or "en", task="transcribe", max_new_tokens=220)
        return self.asr_tok.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def ref_text_for(self, voice_key: str, ref_path: str, given: Optional[str]) -> str:
        if given:
            return given
        if voice_key not in self.ref_texts:
            y = load_any(ref_path, sr=16000)
            self.ref_texts[voice_key] = self.transcribe(y, 16000, "en")
        return self.ref_texts[voice_key]

    def prompt_for(self, voice_key: str, ref_path: str, ref_text: Optional[str]):
        if voice_key in self.prompts:
            self.prompts.move_to_end(voice_key)
            return self.prompts[voice_key]
        from textnorm import normalize
        text = normalize(self.ref_text_for(voice_key, ref_path, ref_text), "en")
        p = self.model.create_voice_clone_prompt(ref_audio=ref_path, ref_text=text, x_vector_only_mode=False)
        self.prompts[voice_key] = p
        while len(self.prompts) > 32:
            self.prompts.popitem(last=False)
        return p

    def check(self, text: str, wav: np.ndarray, lang: str, use_asr: bool) -> dict:
        dur = len(wav) / self.sr
        exp = max(0.6, expected_seconds(text))
        ratio = dur / exp
        wer = None
        if use_asr and lang == "en":
            try:
                heard = self.transcribe(wav, self.sr, "en")
                wer = round(word_error_rate(words_for_compare(text), words_for_compare(heard)), 3)
            except Exception:  # noqa: BLE001 - a broken check never blocks the voice-over
                wer = None
        bad = ratio > 1.85 or ratio < 0.5 or (wer is not None and wer > 0.2)
        score = (wer or 0.0) + max(0.0, ratio - 1.5) + 2 * max(0.0, 0.65 - ratio)
        return {"seconds": round(dur, 2), "ratio": round(ratio, 2), "wer": wer, "ok": not bad, "score": round(score, 3)}

    # -- a whole part ------------------------------------------------------------------------
    def run_part(self, t: dict) -> dict:
        self.load()
        texts: List[str] = t["texts"]
        # What each piece is checked against: the words as written where the model read a respelling
        # from the channel's pronunciation list (handler / textnorm.protect_pronunciations).
        checks: List[str] = t.get("check_texts") or texts
        if len(checks) != len(texts):
            checks = texts
        lang = t.get("lang", "en")
        language = LANG_NAMES.get(lang, "English")
        prompt = self.prompt_for(t["voice_key"], t["ref_path"], t.get("ref_text"))
        p = dict(DEFAULTS)
        p.update({k: v for k, v in (t.get("params") or {}).items() if k in DEFAULTS})
        best: List[Optional[tuple]] = [None] * len(texts)
        todo = list(range(len(texts)))
        attempts = [0] * len(texts)
        gen_total = 0.0
        for rnd in range(max(1, int(t.get("max_attempts", 3)))):
            if not todo:
                break
            seed_all(int(t["seed"]) + rnd * 7919)
            t0 = time.time()
            wavs, sr = self.model.generate_voice_clone(text=[texts[i] for i in todo], language=[language] * len(todo),
                                                       voice_clone_prompt=prompt, **p)
            gen_total += time.time() - t0
            self.sr = sr
            still = []
            for i, w in zip(todo, wavs):
                attempts[i] += 1
                w = trim(np.asarray(w, np.float32).reshape(-1), sr)
                chk = self.check(checks[i], w, lang, bool(t.get("validate", True)))
                if best[i] is None or chk["score"] < best[i][1]["score"]:
                    best[i] = (w, chk)
                if not chk["ok"]:
                    still.append(i)
            todo = still
        return {"wavs": [b[0] for b in best], "checks": [b[1] for b in best], "attempts": attempts,
                "gen_seconds": round(gen_total, 2), "sr": self.sr}

    def handle(self, task: dict) -> dict:
        op = task.get("op", "part")
        if op == "part":
            return self.run_part(task)
        if op == "load":
            self.load()
            return {"loaded": "qwen", "load_seconds": self.load_seconds}
        if op == "similarity":
            return {"similarity": None}
        raise ValueError(f"unknown op {op!r}")
