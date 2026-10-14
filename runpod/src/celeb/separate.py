"""
The voice stem of a clip's audio range, for speaker colouring (speakers.py).

Celebs Goat clips carry music, laughter and crowd noise under every line, which pulls two actors' voice
embeddings together (0.78-0.96 cosine on the mix). Spleeter 2-stems (Deezer, MIT licence, code and models)
through sherpa-onnx strips most of it on the CPU at ~0.04 s per audio second, so the voice embeddings are taken
on the vocals stem instead. UVR MDX-Net Voc_FT was tried too: ~25x slower and its weights carry no stated
licence, so it is not used.

The model is baked into the image at /opt/models/celeb (scripts/fetch_models.py) or fetched on first use into
models/ next to this file (never committed), checked against its SHA-256 either way.
"""
import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import threading
from typing import Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BAKED = os.getenv("CELEB_MODELS_DIR", "/opt/models/celeb")
LOCAL = os.path.join(HERE, "models")
SR = 16000                                     # what speakers.py works in
SPLEETER_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models/"
                "sherpa-onnx-spleeter-2stems-fp16.tar.bz2")
SPLEETER_FILES = {                             # name inside the archive -> SHA-256
    "vocals.fp16.onnx": "24cef84aedcd1fe87c0b743ef3370ad34dc1fabf6c9014d6128a75a538c7b668",
    "accompaniment.fp16.onnx": "d14cea55793cc531a5875f5f4da08207d1c5ab9292e8e0099a104eecb014fcc0",
}
PREFIX = "spleeter2_"                          # local file names: spleeter2_vocals.fp16.onnx, ...

_sep = None
_lock = threading.Lock()


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def model_paths() -> Optional[dict]:
    """{'vocals': path, 'accompaniment': path} of a verified copy, fetching it once if needed; None when absent."""
    for d in (BAKED, LOCAL):
        p = {n: os.path.join(d, PREFIX + n) for n in SPLEETER_FILES}
        if all(os.path.isfile(x) for x in p.values()):
            return {"vocals": p["vocals.fp16.onnx"], "accompaniment": p["accompaniment.fp16.onnx"]}
    try:
        import requests
        r = requests.get(SPLEETER_URL, timeout=300)
        r.raise_for_status()
        os.makedirs(LOCAL, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:bz2") as tar:
            for m in tar.getmembers():
                base = os.path.basename(m.name)
                if base not in SPLEETER_FILES or not m.isfile():
                    continue
                data = tar.extractfile(m).read()
                if hashlib.sha256(data).hexdigest() != SPLEETER_FILES[base]:
                    return None
                tmp = os.path.join(LOCAL, PREFIX + base + ".part")
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, os.path.join(LOCAL, PREFIX + base))
    except Exception:  # noqa: BLE001
        return None
    p = {n: os.path.join(LOCAL, PREFIX + n) for n in SPLEETER_FILES}
    if not all(os.path.isfile(x) for x in p.values()):
        return None
    return {"vocals": p["vocals.fp16.onnx"], "accompaniment": p["accompaniment.fp16.onnx"]}


def available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return model_paths() is not None


def _separator():
    global _sep
    with _lock:
        if _sep is None:
            import sherpa_onnx as so
            p = model_paths()
            if p is None:
                raise RuntimeError("spleeter model unavailable")
            _sep = so.OfflineSourceSeparation(so.OfflineSourceSeparationConfig(
                model=so.OfflineSourceSeparationModelConfig(
                    spleeter=so.OfflineSourceSeparationSpleeterModelConfig(
                        vocals=p["vocals"], accompaniment=p["accompaniment"]),
                    num_threads=max(1, min(4, os.cpu_count() or 1)))))
        return _sep


def _ffmpeg(args, data: Optional[bytes] = None) -> bytes:
    p = subprocess.run(["ffmpeg", "-v", "error", *args], input=data, capture_output=True, timeout=300)
    return p.stdout


def mix(path: str, a: float, b: float) -> np.ndarray:
    """The plain mono 16 kHz audio of [a, b) on the file's clock."""
    a = max(0.0, a)
    return np.frombuffer(_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{max(0.0, b - a):.3f}", "-i", path, "-ac", "1",
                                  "-ar", str(SR), "-f", "f32le", "-"]), np.float32)


def _cache_path(path: str, a: float, b: float) -> str:
    try:
        st = os.stat(path)
        key = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|{a:.3f}|{b:.3f}"
    except OSError:
        key = f"{os.path.abspath(path)}|{a:.3f}|{b:.3f}"
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    d = os.getenv("CELEB_VOCALS_CACHE") or os.path.join(os.path.dirname(os.path.abspath(path)), ".vocals")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.join(tempfile.gettempdir(), "celeb_vocals")
        os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{h}.npy")


def vocals(path: str, a: float, b: float) -> Optional[np.ndarray]:
    """
    Mono 16 kHz voice stem of [a, b) on the file's clock (sample 0 = time a), cached next to the source file.
    None when separation is unavailable or fails (callers then use mix()).
    """
    a = max(0.0, a)
    if b - a <= 0.05:
        return None
    cp = _cache_path(path, a, b)
    if os.path.isfile(cp):
        try:
            return np.load(cp)
        except Exception:  # noqa: BLE001
            pass
    if not available():
        return None
    try:
        raw = _ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", path, "-ac", "2", "-ar", "44100",
                       "-f", "f32le", "-"])
        x = np.frombuffer(raw, np.float32)
        if len(x) < 2 * 4410:
            return None
        x = x.reshape(-1, 2).T.copy()
        out = _separator().process(sample_rate=44100, samples=x)
        v = np.asarray(out.stems[0].data, np.float32)          # stem 0 = vocals
        v = v.mean(axis=0) if v.ndim == 2 else v
        y = np.frombuffer(_ffmpeg(["-f", "f32le", "-ar", str(out.sample_rate), "-ac", "1", "-i", "-",
                                   "-ar", str(SR), "-f", "f32le", "-"], np.ascontiguousarray(v).tobytes()),
                          np.float32)
        if not len(y):
            return None
        try:
            tmp = cp + ".part.npy"
            np.save(tmp, y)
            os.replace(tmp, cp)
        except OSError:
            pass
        return y
    except Exception:  # noqa: BLE001
        return None
