"""
The voice engine: Resemble AI Chatterbox (MIT) in three flavours, each able to
clone a voice from a short sample.

  en     Chatterbox (English, 0.5B Llama backbone): expressiveness
         ("exaggeration") and pacing ("cfg") controls. The default.
  mtl    Chatterbox Multilingual V3 (23 languages, same controls).
  turbo  Chatterbox Turbo (English, 350M, one-pass / 2-step decoder): fastest,
         no expressiveness control, conditions on 15 s of the sample.

ModelHost = one process's models: one TTS model on the GPU at a time (a switch
unloads the other) plus Whisper base.en for the read-back check. Every piece
(see textnorm.plan_chunks) is generated, trimmed and checked: its length
against the words in it, and (English) a Whisper transcript against the text.
A piece that came out wrong (a skipped phrase, babble, a long silence, a
truncated end) is made again with another seed, up to `max_attempts`, and the
best take is kept. Chatterbox's token loop is launch-bound (small kernels,
batch 1), so one copy leaves most of a GPU idle: ReplicaPool runs several
copies in their own processes on the same GPU and hands the pieces of a part
to whichever copy is free.
"""
from __future__ import annotations

import copy
import multiprocessing as mp
import os
import queue
import random
import subprocess
import time
import traceback
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

import numpy as np

from audio import trim
from textnorm import expected_seconds, word_error_rate, words_for_compare

MODELS_DIR = os.environ.get("TTS_MODELS_DIR", "/models")
SR = 24000
MODEL_NAMES = ("en", "mtl", "turbo")

DEFAULTS = {
    "en": {"exaggeration": 0.5, "cfg": 0.5, "temperature": 0.8, "repetition_penalty": 1.2, "min_p": 0.05, "top_p": 1.0},
    "mtl": {"exaggeration": 0.5, "cfg": 0.5, "temperature": 0.8, "repetition_penalty": 1.2, "min_p": 0.05, "top_p": 1.0},
    "turbo": {"temperature": 0.8, "repetition_penalty": 1.2, "top_p": 0.95, "top_k": 1000},
}


def seed_all(seed: int) -> None:
    import torch
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class ModelHost:
    def __init__(self, device: str = "cuda", want_asr: bool = True):
        self.device = device
        self.want_asr = want_asr
        self.name: Optional[str] = None
        self.model = None
        self.builtin = None
        self.conds: "OrderedDict[tuple, object]" = OrderedDict()
        self.asr = None
        self.asr_fe = None
        self.asr_tok = None
        self.load_seconds: Dict[str, float] = {}

    # -- models ---------------------------------------------------------------------------------
    def load(self, name: str):
        if name not in MODEL_NAMES:
            raise ValueError(f"unknown model {name!r}")
        if self.name == name and self.model is not None:
            return self.model
        import torch
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        if self.model is not None:
            self.model = None
            self.builtin = None
            self.conds.clear()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        t0 = time.time()
        if name == "en":
            from chatterbox.tts import ChatterboxTTS
            m = ChatterboxTTS.from_local(f"{MODELS_DIR}/chatterbox", self.device)
        elif name == "mtl":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            m = ChatterboxMultilingualTTS.from_local(f"{MODELS_DIR}/chatterbox", self.device, t3_model="v3")
        else:
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            m = ChatterboxTurboTTS.from_local(f"{MODELS_DIR}/chatterbox-turbo", self.device)
        self.builtin = copy.deepcopy(m.conds) if m.conds is not None else None
        # Every output carries Resemble's imperceptible Perth watermark (kept on purpose: cloned
        # voices stay identifiable as AI). Its network defaults to the CPU; on the GPU it costs
        # nothing noticeable per piece.
        if self.device.startswith("cuda"):
            try:
                import perth
                m.watermarker = perth.PerthImplicitWatermarker(device=self.device)
            except Exception:  # noqa: BLE001 - the CPU watermarker stays
                pass
        self.model, self.name = m, name
        self.load_seconds[name] = round(time.time() - t0, 2)
        return m

    def conds_for(self, voice_key: str, ref_path: Optional[str], exaggeration: float):
        k = (self.name, voice_key)
        if k in self.conds:
            self.conds.move_to_end(k)
            return self.conds[k]
        m = self.model
        if not ref_path:
            if self.builtin is None:
                raise ValueError("this model has no built-in voice; send a voice sample")
            c = copy.deepcopy(self.builtin)
        else:
            if self.name == "turbo":
                m.prepare_conditionals(ref_path, exaggeration=0.0, norm_loudness=True)
            else:
                m.prepare_conditionals(ref_path, exaggeration=exaggeration)
            c = m.conds
        self.conds[k] = c
        while len(self.conds) > 24:
            self.conds.popitem(last=False)
        return c

    # -- one take of one piece ----------------------------------------------------------------
    def generate(self, text: str, voice_key: str, ref_path: Optional[str], p: dict, lang: str, seed: int) -> np.ndarray:
        import torch
        m = self.model
        m.conds = self.conds_for(voice_key, ref_path, float(p.get("exaggeration", 0.5)))
        seed_all(seed)
        with torch.inference_mode():
            if self.name == "en":
                wav = m.generate(text, exaggeration=float(p["exaggeration"]), cfg_weight=float(p["cfg"]),
                                 temperature=float(p["temperature"]), repetition_penalty=float(p["repetition_penalty"]),
                                 min_p=float(p["min_p"]), top_p=float(p["top_p"]))
            elif self.name == "mtl":
                wav = m.generate(text, language_id=lang, exaggeration=float(p["exaggeration"]), cfg_weight=float(p["cfg"]),
                                 temperature=float(p["temperature"]), repetition_penalty=float(p["repetition_penalty"]),
                                 min_p=float(p["min_p"]), top_p=float(p["top_p"]))
            else:
                wav = m.generate(text, temperature=float(p["temperature"]), top_p=float(p.get("top_p", 0.95)),
                                 top_k=int(p.get("top_k", 1000)), repetition_penalty=float(p["repetition_penalty"]),
                                 norm_loudness=True)
        return wav.squeeze(0).float().cpu().numpy().astype(np.float32)

    # -- read-back check ---------------------------------------------------------------------
    def transcribe(self, wav: np.ndarray, sr: int) -> Optional[str]:
        if not self.want_asr:
            return None
        import torch
        if self.asr is None:
            from transformers import WhisperFeatureExtractor, WhisperForConditionalGeneration, WhisperTokenizer
            d = f"{MODELS_DIR}/whisper-base.en"
            self.asr_fe = WhisperFeatureExtractor.from_pretrained(d)
            self.asr_tok = WhisperTokenizer.from_pretrained(d)
            self.asr = WhisperForConditionalGeneration.from_pretrained(d).to(self.device).half().eval()
        import librosa
        y = librosa.resample(wav.astype(np.float32), orig_sr=sr, target_sr=16000)[: 16000 * 30]
        feats = self.asr_fe(y, sampling_rate=16000, return_tensors="pt").input_features.to(self.device).half()
        with torch.inference_mode():
            ids = self.asr.generate(feats, max_new_tokens=220)
        return self.asr_tok.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def check(self, text: str, wav: np.ndarray, lang: str, use_asr: bool) -> dict:
        dur = len(wav) / SR
        exp = max(0.6, expected_seconds(text))
        ratio = dur / exp
        heard, wer = None, None
        if use_asr and (lang or "en").startswith("en"):
            try:
                heard = self.transcribe(wav, SR)
                wer = round(word_error_rate(words_for_compare(text), words_for_compare(heard or "")), 3)
            except Exception as e:  # noqa: BLE001 - a broken check never blocks the voice-over
                heard = f"(check failed: {type(e).__name__})"
        bad = ratio > 1.85 or ratio < 0.5 or dur > 38.5 or (wer is not None and wer > 0.2)
        score = (wer or 0.0) + max(0.0, ratio - 1.5) + 2 * max(0.0, 0.65 - ratio)
        return {"seconds": round(dur, 2), "expected": round(exp, 2), "ratio": round(ratio, 2), "wer": wer,
                "heard": heard, "ok": not bad, "score": round(score, 3)}

    def run_chunk(self, t: dict) -> dict:
        self.load(t["model"])
        best = None
        tries = []
        for a in range(max(1, int(t.get("max_attempts", 3)))):
            seed = int(t["seed"]) + a * 7919
            t0 = time.time()
            wav = self.generate(t["text"], t["voice_key"], t.get("ref_path"), t["params"], t.get("lang", "en"), seed)
            gen = time.time() - t0
            # Chatterbox's last token decodes to a few ms of noise (the multilingual model drops it itself).
            wav = trim(wav, SR, cut_end=0.0 if self.name == "mtl" else 0.02)
            # Checked against the words as written when the model read a respelling (check_text).
            chk = self.check(t.get("check_text") or t["text"], wav, t.get("lang", "en"), bool(t.get("validate", True)))
            chk.update({"gen_seconds": round(gen, 2), "seed": seed})
            tries.append(chk)
            if best is None or chk["score"] < best[1]["score"]:
                best = (wav, chk)
            if chk["ok"]:
                break
        wav, chk = best
        return {"wav": wav, "check": chk, "attempts": len(tries),
                "gen_seconds": round(sum(c["gen_seconds"] for c in tries), 2),
                "tries": [{k: v for k, v in c.items() if k != "heard"} for c in tries]}

    def similarity(self, ref_path: str, wav: np.ndarray) -> Optional[float]:
        """Cosine similarity of voice-encoder embeddings: sample vs generated (same voice ~0.8+)."""
        try:
            import librosa
            from audio import load_any
            ref = load_any(ref_path, sr=16000)
            out = librosa.resample(wav.astype(np.float32), orig_sr=SR, target_sr=16000)
            ve = self.model.ve
            a = np.asarray(ve.embeds_from_wavs([ref], sample_rate=16000)).mean(0)
            b = np.asarray(ve.embeds_from_wavs([out], sample_rate=16000)).mean(0)
            return round(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)), 4)
        except Exception:  # noqa: BLE001
            return None

    def handle(self, task: dict) -> dict:
        op = task.get("op", "chunk")
        if op == "chunk":
            return self.run_chunk(task)
        if op == "similarity":
            self.load(task["model"])
            return {"similarity": self.similarity(task["ref_path"], task["wav"])}
        if op == "load":
            self.load(task["model"])
            return {"loaded": self.name, "load_seconds": self.load_seconds}
        raise ValueError(f"unknown op {op!r}")


# ---------------------------------------------------------------------------------------------
# Several copies on one GPU

def make_host(device: str, want_asr: bool):
    """The engine this image runs: TTS_ENGINE=qwen (Qwen3-TTS) or chatterbox (default)."""
    if os.environ.get("TTS_ENGINE", "chatterbox").lower() == "qwen":
        from engine_qwen import QwenHost
        return QwenHost(device, want_asr)
    return ModelHost(device, want_asr)


def _replica_main(idx: int, tasks, results, device: str, want_asr: bool, preload: Optional[str]) -> None:
    os.environ["TTS_REPLICA"] = str(idx)
    host = make_host(device, want_asr)
    try:
        if preload:
            host.load(preload)
            if want_asr:
                host.transcribe(np.zeros(SR, dtype=np.float32), SR)  # loads the speech recognizer too
        results.put(("ready", idx, {"load_seconds": host.load_seconds}))
    except Exception as e:  # noqa: BLE001
        results.put(("broken", idx, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}"))
        return
    while True:
        item = tasks.get()
        if item is None:
            break
        tid, task = item
        try:
            results.put(("done", tid, host.handle(task)))
        except Exception as e:  # noqa: BLE001
            results.put(("fail", tid, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}"))


def gpu_memory_gb() -> float:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        return float(out[0]) / 1024.0 if out else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def gpu_name() -> str:
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                              text=True, timeout=20).stdout.strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return ""


def auto_replicas() -> int:
    want = os.environ.get("TTS_REPLICAS", "auto").strip().lower()
    cap = int(os.environ.get("TTS_MAX_REPLICAS", "4"))
    if want not in ("", "auto"):
        return max(0, min(int(want), 8))
    gb = gpu_memory_gb()
    if gb <= 0:
        return 1
    per = float(os.environ.get("TTS_GB_PER_REPLICA", "4.8"))
    return max(1, min(cap, int((gb - 1.5) // per)))


class ReplicaPool:
    """N model processes on one GPU sharing a task queue (0 = run in this process)."""

    def __init__(self, n: int, device: str = "cuda", want_asr: bool = True, preload: Optional[str] = "en"):
        self.n = n
        self.device = device
        self.want_asr = want_asr
        self.preload = preload
        self.ctx = mp.get_context("spawn")
        self.tasks = self.ctx.Queue() if n else None
        self.results = self.ctx.Queue() if n else None
        self.procs: List = []
        self.ready: Dict[int, dict] = {}
        self.broken: Dict[int, str] = {}
        self.local = make_host(device, want_asr) if n == 0 else None
        self.started_at = time.time()
        self.ready_seconds = None
        self._tid = 0

    def start(self, wait_s: float = 600.0) -> None:
        if self.n == 0:
            if self.preload:
                self.local.load(self.preload)
            self.ready_seconds = round(time.time() - self.started_at, 2)
            return
        for i in range(self.n):
            p = self.ctx.Process(target=_replica_main, args=(i, self.tasks, self.results, self.device, self.want_asr, self.preload),
                                 daemon=True)
            p.start()
            self.procs.append(p)
        end = time.time() + wait_s
        while len(self.ready) + len(self.broken) < self.n and time.time() < end:
            try:
                kind, idx, info = self.results.get(timeout=5)
            except queue.Empty:
                continue
            (self.ready if kind == "ready" else self.broken)[idx] = info
        self.ready_seconds = round(time.time() - self.started_at, 2)
        if not self.ready:
            raise RuntimeError("no model replica started: " + "; ".join(str(v)[:300] for v in self.broken.values()))

    def alive(self) -> int:
        return sum(1 for p in self.procs if p.is_alive()) if self.n else 1

    def heal(self) -> bool:
        """A replica that died (e.g. a CUDA crash) is replaced before the next job. True if any was."""
        if self.n == 0:
            return False
        dead = [i for i, p in enumerate(self.procs) if not p.is_alive()]
        for i in dead:
            p = self.ctx.Process(target=_replica_main, args=(i, self.tasks, self.results, self.device, self.want_asr, self.preload),
                                 daemon=True)
            p.start()
            self.procs[i] = p
            self.ready.pop(i, None)
        if dead:
            end = time.time() + 300
            waiting = set(dead)
            while waiting and time.time() < end:
                try:
                    kind, idx, info = self.results.get(timeout=5)
                except queue.Empty:
                    continue
                if kind in ("ready", "broken") and idx in waiting:
                    waiting.discard(idx)
                    (self.ready if kind == "ready" else self.broken)[idx] = info
        return bool(dead)

    def _drain(self) -> None:
        """Pieces of a failed job still waiting are dropped, so the next job does not queue behind them."""
        while True:
            try:
                self.tasks.get_nowait()
            except Exception:  # noqa: BLE001 - queue.Empty (or a closed queue)
                return

    def run(self, tasks: List[dict], on_done: Optional[Callable[[int, int], None]] = None, timeout_s: float = 900.0) -> List[dict]:
        """Every task's result, in order. Raises on the first failure."""
        if self.n == 0:
            out = []
            for i, t in enumerate(tasks):
                out.append(self.local.handle(t))
                if on_done:
                    on_done(i + 1, len(tasks))
            return out
        if not self.alive():
            raise RuntimeError("all model replicas have stopped")
        ids = []
        for t in tasks:
            self._tid += 1
            ids.append(self._tid)
            self.tasks.put((self._tid, t))
        got: Dict[int, dict] = {}
        end = time.time() + timeout_s
        while len(got) < len(ids):
            if time.time() > end:
                raise TimeoutError(f"{len(ids) - len(got)} piece(s) did not finish in time")
            try:
                kind, tid, info = self.results.get(timeout=5)
            except queue.Empty:
                if any(not p.is_alive() for p in self.procs):
                    # Its piece will never come back; the app restarts the part once.
                    raise RuntimeError("a model replica stopped while working")
                continue
            if tid not in ids:
                continue  # a stale answer from an earlier, failed job
            if kind == "fail":
                self._drain()
                raise RuntimeError(info)
            got[tid] = info
            if on_done:
                on_done(len(got), len(ids))
        return [got[i] for i in ids]
