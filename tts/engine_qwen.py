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

import functools
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

# Read-back clips per Whisper call, and pieces per generate call (a longer list runs in slices).
ASR_BATCH = int(os.environ.get("TTS_ASR_BATCH", "16"))
# Pieces one generate call may take, by the card's memory when not set (measured 2026-10-19 on an RTX A4000,
# 16 GB: 93 pieces of a 24 s owner clone peaked at 13.1 GB). An out-of-memory batch is halved and made again.
MAX_BATCH = int(os.environ.get("TTS_MAX_BATCH", "0"))


def auto_max_batch(vram_gb: float) -> int:
    if MAX_BATCH > 0:
        return MAX_BATCH
    if vram_gb <= 0:
        return 16
    if vram_gb < 15:
        return 32
    if vram_gb < 19:
        return 96
    if vram_gb < 30:
        return 160
    return 256
# Pieces per codec-decoder call (its memory grows with the batch; see QwenHost._decode_in_groups).
DECODE_BATCH = max(1, int(os.environ.get("TTS_DECODE_BATCH", "4")))

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
        self._max_batch: Optional[int] = None

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
        self._decode_in_groups()
        if os.environ.get("TTS_SLIM_HIDDEN", "1") != "0":
            self._slim_hidden_states()
        return self.model

    def _slim_hidden_states(self) -> None:
        """
        The talker hands every layer's hidden states back at every step, and generate() keeps them all
        (~85 MB a piece), while Qwen3TTS.generate only reads the last layer's last position and the codec
        ids. Keeping just those is exact (the same numbers reach the same code) and frees most of the
        memory a batch needs, so a card holds about twice the pieces.
        """
        talker = getattr(getattr(self.model, "model", None), "talker", None)
        if talker is None or getattr(talker, "_tg_slim", False):
            return
        orig = talker.forward

        @functools.wraps(orig)  # generate() reads the signature to check its keyword arguments
        def forward(*args, **kwargs):
            out = orig(*args, **kwargs)
            hs = getattr(out, "hidden_states", None)
            if isinstance(hs, tuple) and len(hs) == 2 and isinstance(hs[0], (tuple, list)) and hs[0]:
                out.hidden_states = ((hs[0][-1][:, -1:],), hs[1])
            return out

        talker.forward = forward
        talker._tg_slim = True

    def _decode_in_groups(self) -> None:
        """
        The codec decoder turns codes into audio for a whole batch at once, and its activations grow with
        the batch (32 pieces = out of memory on a 16 GB card, while generating them needs far less). Decoding
        DECODE_BATCH pieces at a time gives each piece the same audio (each one is decoded on its own codes;
        only the padding to the batch's longest piece changes) and lets far bigger batches generate.
        """
        st = getattr(getattr(self.model, "model", None), "speech_tokenizer", None)
        if st is None or getattr(st, "_tg_grouped", False):
            return
        orig = st.decode

        def decode(encoded):
            if isinstance(encoded, list) and len(encoded) > DECODE_BATCH:
                wavs, fs = [], None
                for s in range(0, len(encoded), DECODE_BATCH):
                    w, fs = orig(encoded[s: s + DECODE_BATCH])
                    wavs += list(w)
                return wavs, fs
            return orig(encoded)

        st.decode = decode
        st._tg_grouped = True

    # -- speech recognition (reference transcripts + read-back check) -------------------------
    def _load_asr(self):
        if self.asr is None:
            import torch
            from transformers import WhisperFeatureExtractor, WhisperForConditionalGeneration, WhisperTokenizer
            self.asr_fe = WhisperFeatureExtractor.from_pretrained(WHISPER_DIR)
            self.asr_tok = WhisperTokenizer.from_pretrained(WHISPER_DIR)
            self.asr = WhisperForConditionalGeneration.from_pretrained(WHISPER_DIR, torch_dtype=torch.float16).to(self.device).eval()

    def transcribe(self, wav: np.ndarray, sr: int, lang: str = "en") -> str:
        return self.transcribe_many([wav], sr, lang)[0]

    def transcribe_many(self, wavs: List[np.ndarray], sr: int, lang: str = "en", batch: int = 0) -> List[str]:
        """Whisper on several clips at once. Whisper pads every clip to its 30 s window anyway, so a batch
        reads each clip as one at a time would; it only saves the per-call overhead."""
        import torch
        import librosa
        self._load_asr()
        batch = max(1, batch or ASR_BATCH)
        ys = [librosa.resample(np.asarray(w, np.float32), orig_sr=sr, target_sr=16000)[: 16000 * 30] for w in wavs]
        out: List[str] = []
        for s in range(0, len(ys), batch):
            group = ys[s: s + batch]
            feats = self.asr_fe(group, sampling_rate=16000, return_tensors="pt").input_features.to(self.device, torch.float16)
            with torch.inference_mode():
                ids = self.asr.generate(feats, language=lang or "en", task="transcribe", max_new_tokens=220)
            out += [t.strip() for t in self.asr_tok.batch_decode(ids, skip_special_tokens=True)]
        return out

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
        return self.check_many([text], [wav], lang, use_asr)[0]

    def check_many(self, texts: List[str], wavs: List[np.ndarray], lang: str, use_asr: bool) -> List[dict]:
        """Length + Whisper read-back check for each piece (the same rule as before, read back in batches)."""
        heard: List[Optional[str]] = [None] * len(texts)
        if use_asr and lang == "en" and texts:
            try:
                heard = list(self.transcribe_many(wavs, self.sr, "en"))
            except Exception:  # noqa: BLE001 - a broken check never blocks the voice-over
                heard = [None] * len(texts)
        out = []
        for text, wav, h in zip(texts, wavs, heard):
            dur = len(wav) / self.sr
            exp = max(0.6, expected_seconds(text))
            ratio = dur / exp
            wer = None
            if h is not None:
                try:
                    wer = round(word_error_rate(words_for_compare(text), words_for_compare(h)), 3)
                except Exception:  # noqa: BLE001
                    wer = None
            bad = ratio > 1.85 or ratio < 0.5 or (wer is not None and wer > 0.2)
            score = (wer or 0.0) + max(0.0, ratio - 1.5) + 2 * max(0.0, 0.65 - ratio)
            out.append({"seconds": round(dur, 2), "ratio": round(ratio, 2), "wer": wer, "ok": not bad, "score": round(score, 3)})
        return out

    def max_batch(self) -> int:
        if self._max_batch is None:
            gb = 0.0
            try:
                import torch
                if torch.cuda.is_available():
                    gb = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
            except Exception:  # noqa: BLE001
                gb = 0.0
            self._max_batch = auto_max_batch(gb)
        return self._max_batch

    def _generate(self, texts: List[str], prompts: list, language: str, p: dict):
        """One generate call; a batch that runs out of GPU memory is halved and made again (smaller from then on)."""
        try:
            import torch
            oom = torch.OutOfMemoryError
        except Exception:  # noqa: BLE001 - no torch (the unit tests' fake model)
            torch, oom = None, MemoryError
        try:
            return self.model.generate_voice_clone(text=texts, language=[language] * len(texts), voice_clone_prompt=prompts, **p)
        except oom:
            if len(texts) <= 1:
                raise
        if torch is not None:
            torch.cuda.empty_cache()
        half = (len(texts) + 1) // 2
        self._max_batch = max(1, min(self.max_batch(), half))
        print(f"[tts] out of GPU memory at {len(texts)} pieces; batches of {self._max_batch} from now on", flush=True)
        wa, sr = self._generate(texts[:half], prompts[:half], language, p)
        wb, sr = self._generate(texts[half:], prompts[half:], language, p)
        return list(wa) + list(wb), sr

    # -- parts -------------------------------------------------------------------------------
    def run_part(self, t: dict) -> dict:
        return self.run_parts([t])[0]

    @staticmethod
    def _params(t: dict) -> dict:
        p = dict(DEFAULTS)
        p.update({k: v for k, v in (t.get("params") or {}).items() if k in DEFAULTS})
        return p

    @classmethod
    def group_key(cls, t: dict) -> tuple:
        """Parts that may share one batch: same language, check and sampling settings (those are per batch)."""
        return (t.get("lang", "en"), bool(t.get("validate", True)), int(t.get("max_attempts", 3)),
                tuple(sorted(cls._params(t).items())))

    def run_parts(self, tasks: List[dict]) -> List[dict]:
        """
        Several parts as one batch. The parts of a script reach a worker together (handler concurrency);
        their pieces are generated together, so the GPU makes many pieces in about the time it made a few
        (a step costs nearly the same for 4 or 40 sequences). Per piece nothing changes: the same model,
        voice prompt, sampling settings and read-back check, and the same retry rounds (a new seed for the
        pieces that came out wrong). Parts with different settings never share a batch; different voices
        may (every piece carries its own voice prompt).
        """
        self.load()
        results: List[Optional[dict]] = [None] * len(tasks)
        groups: "OrderedDict[tuple, List[int]]" = OrderedDict()
        for k, t in enumerate(tasks):
            groups.setdefault(self.group_key(t), []).append(k)
        for idxs in groups.values():
            for k, r in zip(idxs, self._run_group([tasks[k] for k in idxs])):
                results[k] = r
        return results  # type: ignore[return-value]

    def _run_group(self, tasks: List[dict]) -> List[dict]:
        t0 = tasks[0]
        lang = t0.get("lang", "en")
        language = LANG_NAMES.get(lang, "English")
        p = self._params(t0)
        validate = bool(t0.get("validate", True))
        rounds = max(1, int(t0.get("max_attempts", 3)))
        owner: List[int] = []  # task index of each piece
        texts: List[str] = []
        checks: List[str] = []
        prompts: list = []
        for k, t in enumerate(tasks):
            tx: List[str] = t["texts"]
            ck: List[str] = t.get("check_texts") or tx
            if len(ck) != len(tx):
                ck = tx
            pr = self.prompt_for(t["voice_key"], t["ref_path"], t.get("ref_text"))
            pr = pr if isinstance(pr, list) else [pr]
            for i in range(len(tx)):
                owner.append(k)
                texts.append(tx[i])
                checks.append(ck[i])
                prompts.append(pr[0])
        n = len(texts)
        best: List[Optional[tuple]] = [None] * n
        attempts = [0] * n
        gen_total = 0.0
        todo = list(range(n))
        cap = max(1, self.max_batch())
        for rnd in range(rounds):
            if not todo:
                break
            seed_all(int(t0["seed"]) + rnd * 7919)
            still = []
            for s in range(0, len(todo), cap):
                sub = todo[s: s + cap]
                ts = time.time()
                wavs, sr = self._generate([texts[j] for j in sub], [prompts[j] for j in sub], language, p)
                gen_total += time.time() - ts
                self.sr = sr
                ws = [trim(np.asarray(w, np.float32).reshape(-1), sr) for w in wavs]
                for j, w, chk in zip(sub, ws, self.check_many([checks[j] for j in sub], ws, lang, validate)):
                    attempts[j] += 1
                    if best[j] is None or chk["score"] < best[j][1]["score"]:
                        best[j] = (w, chk)
                    if not chk["ok"]:
                        still.append(j)
            todo = still
        share = gen_total / max(1, n)
        out = []
        for k in range(len(tasks)):
            js = [j for j in range(n) if owner[j] == k]
            out.append({"wavs": [best[j][0] for j in js], "checks": [best[j][1] for j in js],
                        "attempts": [attempts[j] for j in js], "gen_seconds": round(share * len(js), 2), "sr": self.sr,
                        "batch_pieces": n, "batch_parts": len(tasks)})
        return out

    def handle(self, task: dict) -> dict:
        op = task.get("op", "part")
        if op == "part":
            return self.run_part(task)
        if op == "parts":
            return {"results": self.run_parts(task["tasks"])}
        if op == "load":
            self.load()
            return {"loaded": "qwen", "load_seconds": self.load_seconds}
        if op == "similarity":
            return {"similarity": None}
        raise ValueError(f"unknown op {op!r}")
