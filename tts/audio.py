"""
Audio helpers for the TTS worker: numpy in, numpy out; ffmpeg for decoding,
tempo and encoding. No torch here.

* load_any()        any audio file/bytes -> mono float32 at a given rate (ffmpeg).
* clean_reference() a voice sample made ready for cloning: mono 24 kHz, edges
                    trimmed, long pauses shortened (the model conditions on the
                    first seconds, so they should be speech), rumble filtered,
                    a light denoise, -20 LUFS, at most ~40 s.
* trim()            the silence a model leaves around a piece, kept tight but
                    never clipping a soft start or the decay of the last word.
* stitch()          pieces joined with exact pauses (no crossfades: a 6 ms
                    fade at each edge only stops clicks).
* finish()          tempo (rubberband, else atempo), loudness to -16 LUFS,
                    a -1 dBFS limiter, MP3 44.1 kHz 128 kbps mono or WAV.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from typing import List, Optional, Tuple

import numpy as np

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _run(args: List[str], data: Optional[bytes] = None, timeout: int = 300) -> bytes:
    p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", *args], input=data,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + p.stderr.decode("utf-8", "replace")[-400:])
    return p.stdout


@lru_cache(maxsize=1)
def has_filter(name: str) -> bool:
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30).stdout
        return any(line.split()[1:2] == [name] for line in out.splitlines() if len(line.split()) > 1)
    except Exception:  # noqa: BLE001
        return False


def load_any(src, sr: int = 24000, max_seconds: Optional[float] = None) -> np.ndarray:
    """Decode a path or bytes (any format ffmpeg reads) to mono float32 at `sr`."""
    args = []
    data = None
    if isinstance(src, (bytes, bytearray)):
        args += ["-i", "pipe:0"]
        data = bytes(src)
    else:
        args += ["-i", str(src)]
    if max_seconds:
        args += ["-t", f"{max_seconds:.2f}"]
    args += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"]
    raw = _run(args, data=data)
    return np.frombuffer(raw, dtype=np.float32).copy()


def frame_db(x: np.ndarray, sr: int, hop_s: float = 0.01) -> np.ndarray:
    hop = max(1, int(hop_s * sr))
    n = len(x) // hop
    if n == 0:
        return np.array([-120.0])
    fr = x[: n * hop].reshape(n, hop)
    return 20 * np.log10(np.sqrt((fr.astype(np.float64) ** 2).mean(1) + 1e-12) + 1e-12)


def trim(x: np.ndarray, sr: int, rel_db: float = 42.0, floor_db: float = -58.0,
         keep_head: float = 0.03, keep_tail: float = 0.09, cut_end: float = 0.0) -> np.ndarray:
    """Cut the silence before the first and after the last sound (breaths are sounds and stay)."""
    if cut_end > 0 and len(x) > int(cut_end * sr) * 4:
        x = x[: len(x) - int(cut_end * sr)]
    db = frame_db(x, sr)
    if not len(x):
        return x
    thr = max(floor_db, float(db.max()) - rel_db)
    loud = np.nonzero(db > thr)[0]
    if not len(loud):
        return x[:0]
    hop = int(0.01 * sr)
    a = max(0, loud[0] * hop - int(keep_head * sr))
    b = min(len(x), (loud[-1] + 1) * hop + int(keep_tail * sr))
    return x[a:b]


def fade(x: np.ndarray, sr: int, ms: float = 6.0) -> np.ndarray:
    n = min(len(x) // 2, int(sr * ms / 1000))
    if n <= 1:
        return x
    y = x.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def stitch(pieces: List[Tuple[np.ndarray, float]], sr: int, lead: float = 0.05) -> np.ndarray:
    """[(audio, pause_after_seconds)] -> one track: a short lead-in, each piece, its pause."""
    out = [np.zeros(int(lead * sr), dtype=np.float32)]
    for audio, pause in pieces:
        if len(audio):
            out.append(fade(audio.astype(np.float32), sr))
        if pause > 0:
            out.append(np.zeros(int(pause * sr), dtype=np.float32))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def shorten_pauses(x: np.ndarray, sr: int, longest: float = 0.45, keep: float = 0.3,
                   rel_db: float = 35.0) -> np.ndarray:
    """Pauses longer than `longest` inside a sample cut down to `keep` (speech kept as is)."""
    db = frame_db(x, sr)
    if not len(x) or len(db) < 3:
        return x
    thr = max(-60.0, float(np.percentile(db, 95)) - rel_db)
    act = db > thr
    hop = int(0.01 * sr)
    keepmask = np.ones(len(act), bool)
    i = 0
    while i < len(act):
        if act[i]:
            i += 1
            continue
        j = i
        while j < len(act) and not act[j]:
            j += 1
        if i == 0 or j == len(act):
            keepmask[i:j] = False
        elif (j - i) * 0.01 > longest:
            edge = int(keep / 2 / 0.01)
            keepmask[i + edge: j - edge] = False
        i = j
    frames = [x[k * hop:(k + 1) * hop] for k in range(len(act)) if keepmask[k]]
    tail = x[len(act) * hop:] if act[-1] else np.zeros(0, np.float32)
    return np.concatenate(frames + [tail]).astype(np.float32) if frames else x


def loudness(x: np.ndarray, sr: int) -> Optional[float]:
    try:
        import pyloudnorm as pyln  # chatterbox dependency
        if len(x) < sr * 0.5:
            return None
        v = float(pyln.Meter(sr).integrated_loudness(x.astype(np.float64)))
        return v if np.isfinite(v) else None
    except Exception:  # noqa: BLE001
        return None


def gain_to(x: np.ndarray, sr: int, target_lufs: float, max_gain_db: float = 24.0) -> np.ndarray:
    cur = loudness(x, sr)
    if cur is None:
        peak = float(np.abs(x).max() or 1.0)
        return (x * (0.5 / peak)).astype(np.float32)
    g = max(-max_gain_db, min(max_gain_db, target_lufs - cur))
    return (x * (10 ** (g / 20))).astype(np.float32)


def clean_reference(src, out_path: str, sr: int = 24000, max_seconds: float = 40.0) -> dict:
    """A voice sample ready for cloning, written to `out_path` (16-bit WAV). Returns facts about it."""
    x = load_any(src, sr=sr, max_seconds=180)
    raw_seconds = len(x) / sr
    x = trim(x, sr, rel_db=40.0, keep_head=0.02, keep_tail=0.05)
    x = shorten_pauses(x, sr)
    x = x[: int(max_seconds * sr)]
    if len(x) < sr * 3:
        raise ValueError("The voice sample has less than 3 seconds of speech.")
    filt = "highpass=f=70"
    if has_filter("afftdn"):
        filt += ",afftdn=nr=6:nf=-50:tn=1"
    y = np.frombuffer(_run(["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-af", filt,
                            "-f", "f32le", "pipe:1"], data=x.astype(np.float32).tobytes()), dtype=np.float32).copy()
    y = gain_to(y, sr, -20.0)
    peak = float(np.abs(y).max() or 0.0)
    if peak > 0.89:
        y = (y * (0.89 / peak)).astype(np.float32)
    write_wav(out_path, y, sr)
    return {"seconds": round(len(y) / sr, 2), "raw_seconds": round(raw_seconds, 2), "path": out_path}


def write_wav(path: str, x: np.ndarray, sr: int) -> None:
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    import struct
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data" + struct.pack("<I", len(pcm)) + pcm)


def tempo_filter(speed: float) -> str:
    if abs(speed - 1.0) < 0.01:
        return ""
    if has_filter("rubberband"):
        return f"rubberband=tempo={speed:.3f}:pitchq=quality:window=standard"
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def finish(x: np.ndarray, sr: int, out_path: str, fmt: str = "mp3", speed: float = 1.0,
           target_lufs: float = -16.0) -> dict:
    """Tempo, loudness, limiter and encoding. Returns {"seconds", "bytes", "path", "lufs"}."""
    x = gain_to(x, sr, target_lufs)
    filters = [f for f in [tempo_filter(speed)] if f]
    out_sr = 44100 if fmt == "mp3" else sr
    filters.append(f"aresample={out_sr}")
    if has_filter("alimiter"):
        filters.append("alimiter=limit=0.891:attack=4:release=60:level=disabled")
    args = ["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-af", ",".join(filters), "-ac", "1"]
    if fmt == "mp3":
        args += ["-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-id3v2_version", "0", "-write_xing", "1", "-y", out_path]
    elif fmt == "wav":
        args += ["-c:a", "pcm_s16le", "-ar", str(out_sr), "-y", out_path]
    else:
        raise ValueError(f"unknown format {fmt}")
    _run(args, data=x.astype(np.float32).tobytes(), timeout=600)
    seconds = len(x) / sr / max(0.25, speed)
    return {"seconds": round(seconds, 2), "bytes": os.path.getsize(out_path), "path": out_path,
            "lufs": target_lufs}


def transform_voice(x: np.ndarray, sr: int, pitch: float = 1.0, formant: float = 1.0) -> np.ndarray:
    """
    A different-sounding voice from one sample (used only to make our own preset voices):
    `formant` scales the vocal-tract size (and pitch with it, via a resample), `pitch` then moves
    the pitch alone (rubberband, formants preserved). 1.0 = unchanged.
    """
    y = x.astype(np.float32)
    if abs(formant - 1.0) > 0.005:
        r = formant
        y = np.frombuffer(_run(["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-af",
                                f"asetrate={int(sr * r)},aresample={sr},atempo={1 / r:.5f}", "-f", "f32le", "pipe:1"],
                               data=y.tobytes()), dtype=np.float32).copy()
    if abs(pitch - 1.0) > 0.005 and has_filter("rubberband"):
        y = np.frombuffer(_run(["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-af",
                                f"rubberband=pitch={pitch:.4f}:formant=preserved:pitchq=quality", "-f", "f32le", "pipe:1"],
                               data=y.tobytes()), dtype=np.float32).copy()
    return y


def f0_median(x: np.ndarray, sr: int) -> Optional[float]:
    """Median pitch of voiced frames in Hz (male ~85-150, female ~165-255)."""
    try:
        import librosa
        y = librosa.resample(x.astype(np.float32), orig_sr=sr, target_sr=16000)
        f0 = librosa.yin(y, fmin=60, fmax=400, sr=16000, frame_length=1024)
        db = frame_db(y, 16000, hop_s=256 / 16000)
        n = min(len(f0), len(db))
        voiced = f0[:n][db[:n] > (db.max() - 30)]
        voiced = voiced[(voiced > 62) & (voiced < 395)]
        return round(float(np.median(voiced)), 1) if len(voiced) else None
    except Exception:  # noqa: BLE001
        return None


def temp_path(suffix: str) -> str:
    fd, p = tempfile.mkstemp(suffix=suffix, dir=os.environ.get("TTS_TMP", "/tmp"))
    os.close(fd)
    return p
