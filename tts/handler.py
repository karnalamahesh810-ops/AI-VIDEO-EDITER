"""
ThumbGenius voice - RunPod serverless handler.

Input (job["input"]):
  action      "tts" (default) | "health"
  text        the part to voice (the app sends a long script in parts of ~1-2 minutes)
  model       "en" (default) | "mtl" | "turbo"
  language    ISO code, default "en" (other languages use the multilingual model)
  voice       {"builtin": true}                       the model's own voice
              {"url": "https://...", "key": "..."}    a sample to clone (any audio format)
              {"b64": "...", "key": "..."}            the same, inline (private samples)
  exaggeration, cfg, temperature                       expressiveness / pacing / variety
  speed       0.8-1.2 tempo (pitch kept), default 1
  pause       pause scale between sentences, default 1 ("tight" 0.75, "relaxed" 1.3)
  seed        one per take, so every part of a script sounds the same
  validate    Whisper read-back check + retry (English), default true
  format      "mp3" (44.1 kHz 128 kbps mono, default) | "wav"
  return      "url" (R2 upload, default) | "b64"
  tail_pause  silence after the last piece (default: the piece's own pause)
  analyze     add speaker similarity (vs the sample) and median pitch to the answer

Output: {"ok", "audio_url"|"audio_b64", "seconds", "format", "chunks", "retries",
         "wall_seconds", "rtf", "model", "replicas", "checks", ...}
"""
from __future__ import annotations

import base64
import hashlib
import os
import random
import re
import time
import uuid

import numpy as np

BOOT = time.time()

import audio  # noqa: E402
import r2  # noqa: E402
from engine import DEFAULTS, MODEL_NAMES, SR, ReplicaPool, auto_replicas, gpu_memory_gb, gpu_name  # noqa: E402
from textnorm import normalize, plan_chunks  # noqa: E402

VOICE_DIR = os.environ.get("TTS_VOICE_DIR", "/tmp/tts_voices")
MAX_TEXT = int(os.environ.get("TTS_MAX_TEXT", "8000"))
MAX_SAMPLE_BYTES = 25 * 1024 * 1024
DEFAULT_MODEL = os.environ.get("TTS_DEFAULT_MODEL", "en")
POOL: ReplicaPool = None  # type: ignore
_voice_info: dict = {}


def _clamp(v, lo, hi, d):
    try:
        f = float(v)
        return min(hi, max(lo, f)) if np.isfinite(f) else d
    except (TypeError, ValueError):
        return d


def pick_model(name, lang: str) -> str:
    lang = (lang or "en").lower()
    if not lang.startswith("en"):
        return "mtl"
    return name if name in MODEL_NAMES else DEFAULT_MODEL


def resolve_voice(v: dict):
    """(cache key, cleaned sample path or None for the built-in voice, facts)."""
    v = v or {}
    data = None
    if v.get("b64"):
        data = base64.b64decode(v["b64"])
    elif v.get("url"):
        url = str(v["url"])
        if not url.startswith("https://"):
            raise ValueError("voice url must be https")
        import requests
        with requests.get(url, timeout=(10, 60), stream=True) as r:
            r.raise_for_status()
            buf = bytearray()
            for block in r.iter_content(1 << 16):
                buf += block
                if len(buf) > MAX_SAMPLE_BYTES:
                    raise ValueError("voice sample is over 25 MB")
            data = bytes(buf)
    if data is None:
        return "builtin", None, {}
    if len(data) > MAX_SAMPLE_BYTES:
        raise ValueError("voice sample is over 25 MB")
    sha = hashlib.sha256(data).hexdigest()[:20]
    key = re.sub(r"[^A-Za-z0-9:_.-]", "", str(v.get("key") or "ref"))[:80] + ":" + sha
    os.makedirs(VOICE_DIR, exist_ok=True)
    path = os.path.join(VOICE_DIR, f"{sha}.wav")
    if not os.path.exists(path):
        _voice_info[sha] = audio.clean_reference(data, path)
    return key, path, _voice_info.get(sha, {})


def tts(inp: dict, job_id: str, progress) -> dict:
    t0 = time.time()
    text = str(inp.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "no text"}
    if len(text) > MAX_TEXT:
        return {"ok": False, "error": f"text is over {MAX_TEXT} characters; send it in parts"}
    lang = str(inp.get("language") or "en").lower()[:5]
    model = pick_model(inp.get("model"), lang)
    params = dict(DEFAULTS[model])
    for k in ("exaggeration", "cfg", "temperature"):
        if k in inp and k in params:
            lo, hi = {"exaggeration": (0.0, 2.0), "cfg": (0.0, 1.0), "temperature": (0.05, 1.5)}[k]
            params[k] = _clamp(inp[k], lo, hi, params[k])
    speed = _clamp(inp.get("speed", 1.0), 0.7, 1.3, 1.0)
    pause = inp.get("pause", 1.0)
    pause = {"tight": 0.75, "natural": 1.0, "relaxed": 1.3}.get(pause, pause) if isinstance(pause, str) else pause
    pause = _clamp(pause, 0.4, 2.0, 1.0)
    seed = int(inp.get("seed") or random.randint(1, 2 ** 31 - 1)) % (2 ** 31)
    validate = bool(inp.get("validate", True))
    attempts = int(_clamp(inp.get("max_attempts", 3), 1, 4, 3))
    fmt = "wav" if inp.get("format") == "wav" else "mp3"

    voice_key, ref_path, ref_info = resolve_voice(inp.get("voice") or {})
    t_voice = time.time() - t0

    spoken = normalize(text, lang)
    chunks = plan_chunks(spoken, max_chars=int(_clamp(inp.get("chunk_chars", 280), 120, 400, 280)), pause_scale=pause)
    if not chunks:
        return {"ok": False, "error": "nothing to read after cleaning the text"}
    tasks = [{"op": "chunk", "model": model, "voice_key": voice_key, "ref_path": ref_path, "text": c.text,
              "params": params, "seed": seed + i * 101, "validate": validate, "max_attempts": attempts, "lang": lang}
             for i, c in enumerate(chunks)]

    def on_done(done, total):
        try:
            progress({"stage": "voicing", "done": done, "total": total})
        except Exception:  # noqa: BLE001
            pass

    POOL.heal()
    t_gen = time.time()
    results = POOL.run(tasks, on_done)
    t_gen = time.time() - t_gen

    rng = random.Random(seed)
    pieces = []
    for i, (c, r) in enumerate(zip(chunks, results)):
        gap = c.pause * rng.uniform(0.9, 1.12)
        if i == len(chunks) - 1 and inp.get("tail_pause") is not None:
            gap = _clamp(inp.get("tail_pause"), 0.0, 3.0, gap)
        pieces.append((r["wav"], gap))
    track = audio.stitch(pieces, SR)

    out_path = audio.temp_path("." + fmt)
    fin = audio.finish(track, SR, out_path, fmt=fmt, speed=speed)
    answer = {
        "ok": True, "format": fmt, "seconds": fin["seconds"], "bytes": fin["bytes"], "model": model,
        "language": lang, "voice_key": voice_key.split(":")[0], "chunks": len(chunks),
        "retries": sum(r["attempts"] - 1 for r in results), "seed": seed,
        "replicas": POOL.n or 1, "gen_seconds": round(sum(r["gen_seconds"] for r in results), 2),
        "voicing_seconds": round(t_gen, 2), "voice_seconds": round(t_voice, 2),
        "checks": [{"wer": r["check"]["wer"], "ratio": r["check"]["ratio"], "attempts": r["attempts"],
                    "seconds": r["check"]["seconds"]} for r in results],
    }
    if ref_info:
        answer["sample_seconds"] = ref_info.get("seconds")
    if inp.get("analyze"):
        answer["heard"] = [r["check"].get("heard") for r in results]
        answer["texts"] = [c.text for c in chunks]
        answer["f0_hz"] = audio.f0_median(track, SR)
        if ref_path:
            sim = POOL.run([{"op": "similarity", "model": model, "ref_path": ref_path, "wav": track}])[0]
            answer["similarity"] = sim.get("similarity")

    want_b64 = inp.get("return") == "b64" or not r2.enabled()
    if want_b64:
        if fin["bytes"] > 9 * 1024 * 1024:
            return {"ok": False, "error": "audio too large to return inline; configure R2"}
        with open(out_path, "rb") as f:
            answer["audio_b64"] = base64.b64encode(f.read()).decode("ascii")
    else:
        key = f"tts/out/{re.sub(r'[^A-Za-z0-9_-]', '', job_id) or uuid.uuid4().hex}.{fmt}"
        answer["audio_url"] = r2.upload_file(out_path, key, "audio/mpeg" if fmt == "mp3" else "audio/wav")
        answer["key"] = key
    try:
        os.remove(out_path)
    except OSError:
        pass
    answer["wall_seconds"] = round(time.time() - t0, 2)
    answer["rtf"] = round(answer["wall_seconds"] / max(0.1, answer["seconds"]), 3)
    return answer


def health() -> dict:
    return {
        "ok": True, "gpu": gpu_name(), "vram_gb": round(gpu_memory_gb(), 1), "replicas": POOL.n or 1,
        "replicas_alive": POOL.alive(), "replicas_ready": len(POOL.ready) if POOL.n else 1,
        "broken": {k: str(v)[:400] for k, v in POOL.broken.items()}, "ready_seconds": POOL.ready_seconds,
        "boot_to_ready_seconds": round((POOL.started_at - BOOT) + (POOL.ready_seconds or 0), 2),
        "default_model": DEFAULT_MODEL, "load_seconds": {k: v.get("load_seconds") for k, v in POOL.ready.items()},
        "r2": r2.enabled(), "rubberband": audio.has_filter("rubberband"), "afftdn": audio.has_filter("afftdn"),
        "models_on_disk": sorted(os.listdir(os.environ.get("TTS_MODELS_DIR", "/models"))),
        "uptime_seconds": round(time.time() - BOOT, 1),
    }


def handler(job):
    inp = job.get("input") or {}
    action = inp.get("action", "tts")
    try:
        if action == "health":
            return health()
        if action == "tts":
            import runpod
            return tts(inp, str(job.get("id") or ""), lambda d: runpod.serverless.progress_update(job, d))
        return {"ok": False, "error": f"unknown action {action!r}"}
    except Exception as e:  # noqa: BLE001 - the app shows a plain message; details stay in the logs
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


if __name__ == "__main__":
    import runpod
    n = auto_replicas()
    POOL = ReplicaPool(n, want_asr=os.environ.get("TTS_VALIDATE", "1") != "0", preload=DEFAULT_MODEL)
    POOL.start()
    print(f"[tts] ready: {n} replica(s), default model {DEFAULT_MODEL}, {POOL.ready_seconds}s", flush=True)
    runpod.serverless.start({"handler": handler})
