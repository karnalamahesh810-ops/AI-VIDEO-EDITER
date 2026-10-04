"""
The voices behind the endpoint: text in, audio out.

Kokoro-82M (Apache-2.0) is always on: small, far faster than real time on a
24 GB card, with its built-in voices (af_heart, am_michael, bm_george ...).
Chatterbox (MIT, Resemble AI) is on when the image was built with it
(WITH_CHATTERBOX=1): about real time, and it speaks in a voice cloned from a
10-30 s sample (`reference_audio`: a link, a data: URI or bare base64).

Both models are read from MODELS_DIR, where fetch_models.py put them at image
build at pinned revisions - nothing is downloaded when a request arrives.
torch, kokoro and chatterbox are imported only when a model is loaded, so
this file (and its tests) can be read on a machine with none of them.

`speak(request)` is the one entry point, shared by the HTTP server
(server.py) and the RunPod queue handler (rp_handler.py). A request that can
never work - an unknown voice, an engine that is off, a sample that is not
audio - raises Refused, which callers answer without a retry; anything else
is a failure worth asking again.
"""
from __future__ import annotations

import base64
import glob
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import wave
from typing import Any, Dict, List, Optional, Tuple

MODELS_DIR = os.getenv("MODELS_DIR", "/opt/models")
KOKORO_DIR = os.path.join(MODELS_DIR, "kokoro")
CHATTERBOX_DIR = os.path.join(MODELS_DIR, "chatterbox")
KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_RATE = 24000
DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "af_heart").strip() or "af_heart"
# One request: OpenAI's own limit is 4,096 characters; the worker sends 1,500.
MAX_INPUT_CHARS = int(os.getenv("TTS_MAX_INPUT_CHARS", "6000"))
# Chatterbox writes at most ~40 s in one go: longer text is voiced sentence by
# sentence in pieces of at most this many characters, a short breath between.
CHATTERBOX_PIECE_CHARS = int(os.getenv("CHATTERBOX_PIECE_CHARS", "280"))
CHATTERBOX_GAP_SECONDS = 0.15
REFERENCE_MAX_BYTES = 30 * 1024 * 1024
REFERENCE_MIN_SECONDS = 3.0
REFERENCE_KEEP_SECONDS = 30
REFERENCE_DIR = os.getenv("TTS_REFERENCE_DIR", os.path.join(tempfile.gettempdir(), "tts_refs"))
# A voice sample is read as a plain audio file and nothing else: ffmpeg would
# otherwise follow an ffconcat list or a playlist "sample" to other files on
# this machine (or other addresses). Demuxer names, as `ffmpeg -demuxers` prints them.
SAMPLE_FORMATS = "wav,w64,mp3,flac,ogg,mov,matroska,aac,aiff,caf,asf"
REFERENCE_MAX_REDIRECTS = 3
# Kokoro blends at most this many voices ("af_heart,af_bella"); a longer list is refused.
MAX_BLEND = 4

# OpenAI's voice names, for clients that only know those.
OPENAI_VOICES = {"alloy": "af_alloy", "echo": "am_echo", "fable": "bm_fable", "onyx": "am_onyx",
                 "nova": "af_nova", "shimmer": "af_heart"}
_VOICE_NAME = re.compile(r"[a-z]{2}_[a-z0-9]+")

# One generation at a time: both models share the one GPU.
_GPU = threading.Lock()


class Refused(ValueError):
    """A request that can never work. Callers answer it as the client's mistake and never retry it."""


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def chatterbox_enabled() -> bool:
    """Built with Chatterbox (its weights are in the image) and not switched off for this endpoint."""
    return _flag("WITH_CHATTERBOX") and os.path.isfile(os.path.join(CHATTERBOX_DIR, "t3_cfg.safetensors"))


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


# --------------------------------------------------------------------------- #
# Kokoro
# --------------------------------------------------------------------------- #

class Kokoro:
    name = "kokoro"

    def __init__(self) -> None:
        self.model = None
        self.device = ""
        self.pipelines: Dict[str, Any] = {}

    def voices(self) -> List[str]:
        return sorted(os.path.splitext(os.path.basename(p))[0]
                      for p in glob.glob(os.path.join(KOKORO_DIR, "voices", "*.pt")))

    def load(self) -> None:
        if self.model is not None:
            return
        from kokoro import KModel
        self.device = _device()
        # Local files: no hub call, so the revision the image was built with is the one that speaks.
        self.model = KModel(repo_id=KOKORO_REPO, config=os.path.join(KOKORO_DIR, "config.json"),
                            model=os.path.join(KOKORO_DIR, "kokoro-v1_0.pth")).to(self.device).eval()

    def _pipeline(self, lang: str):
        if lang not in self.pipelines:
            from kokoro import KPipeline
            try:
                self.pipelines[lang] = KPipeline(lang_code=lang, repo_id=KOKORO_REPO, model=self.model)
            except Exception as e:  # noqa: BLE001 - a language whose G2P is not in this image
                raise Refused(f"voices of language '{lang}' are not installed on this endpoint "
                              f"({type(e).__name__})") from None
        return self.pipelines[lang]

    def resolve(self, voice: Optional[str]) -> List[str]:
        """The voice(s) a request means: one name, or up to MAX_BLEND joined by "," for an even blend."""
        raw = str(voice or DEFAULT_VOICE)
        if len(raw) > 40 * MAX_BLEND:
            raise Refused(f"voice is {len(raw)} characters; name one voice, or blend up to {MAX_BLEND}")
        names = [OPENAI_VOICES.get(v, v) for v in (p.strip().lower() for p in raw.split(",")) if v]
        if len(names) > MAX_BLEND:
            raise Refused(f"{len(names)} voices to blend; at most {MAX_BLEND}")
        names = names or [DEFAULT_VOICE]
        have = set(self.voices())
        for n in names:
            if not _VOICE_NAME.fullmatch(n) or n not in have:
                raise Refused(f"unknown voice '{n[:40]}'; see GET /v1/audio/voices")
        return names

    def synthesize(self, text: str, voice: Optional[str], speed: float):
        import numpy as np
        import torch
        names = self.resolve(voice)
        if names[0][0] not in "ab":
            # Kokoro cuts long English itself; its other languages read one
            # line at a time, so each sentence goes on a line of its own.
            text = "\n".join(split_pieces(text, 300))
        with _GPU:
            self.load()
            # A voice's first letter is its language (a American, b British, e Spanish ...).
            pipeline = self._pipeline(names[0][0])
            packs = ",".join(os.path.join(KOKORO_DIR, "voices", f"{n}.pt") for n in names)
            parts = []
            with torch.inference_mode():
                for result in pipeline(text, voice=packs, speed=speed, split_pattern=r"\n+"):
                    if result.audio is not None:
                        parts.append(result.audio.detach().cpu().numpy().reshape(-1))
        if not parts:
            raise RuntimeError("Kokoro produced no audio")
        return np.concatenate(parts).astype("float32"), KOKORO_RATE, ",".join(names)


# --------------------------------------------------------------------------- #
# Chatterbox
# --------------------------------------------------------------------------- #

_ABBREV = {"mr", "mrs", "ms", "dr", "st", "sr", "jr", "vs", "prof", "gen", "gov", "sen", "rep", "lt", "col",
           "capt", "sgt", "mt", "ft", "no", "inc", "ltd", "co", "corp", "etc", "approx", "est", "fig", "dept"}
_SENT_END = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+)")
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)$")
_INITIALS = re.compile(r"(?:[a-z]\.)*[a-z]")


def _pack(pieces: List[str], limit: int) -> List[str]:
    out, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur} {piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


def split_pieces(text: str, limit: Optional[int] = None) -> List[str]:
    """
    Text in pieces of at most `limit` characters for a model that writes one
    short passage at a time: whole sentences together, a sentence that is too
    long cut at its commas, then between words. Every word kept, in order.
    """
    limit = max(40, int(limit or CHATTERBOX_PIECE_CHARS))
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    sentences, start = [], 0
    for m in _SENT_END.finditer(text):
        word = _LAST_WORD.search(text[:m.start(1)])
        w = word.group(1).lower() if word else ""
        if m.group(1) == "." and (w in _ABBREV or _INITIALS.fullmatch(w)):
            continue                                # "Dr. Smith", "the U.S. Bureau"
        sentences.append(text[start:m.end(1)])
        start = m.end()
    if text[start:]:
        sentences.append(text[start:])
    pieces: List[str] = []
    for s in sentences:
        if len(s) <= limit:
            pieces.append(s)
            continue
        for clause in re.split(r"(?<=[,;:—–])\s+", s):
            words = [w[i:i + limit] for w in clause.split(" ") for i in range(0, len(w), limit)]
            pieces.extend([clause] if len(clause) <= limit else _pack(words, limit))
    return _pack(pieces, limit)


class Chatterbox:
    name = "chatterbox"

    def __init__(self) -> None:
        self.model = None
        self.device = ""
        self.default_voice = None                   # the built-in voice's conditioning (conds.pt)
        self.cloned: Dict[str, Any] = {}            # sample path -> its conditioning, made once

    def load(self) -> None:
        if self.model is not None:
            return
        from chatterbox.tts import ChatterboxTTS
        self.device = _device()
        self.model = ChatterboxTTS.from_local(CHATTERBOX_DIR, self.device)
        self.default_voice = self.model.conds

    def synthesize(self, text: str, reference: str, exaggeration: float, cfg_weight: float, temperature: float):
        import numpy as np
        import torch
        pieces = split_pieces(text)
        with _GPU:
            self.load()
            rate = int(self.model.sr)
            # The voice is set once for the whole request (and kept for the next
            # part of the same narration); a request without a sample gets the
            # built-in voice back, never the last customer's clone.
            if reference:
                if reference not in self.cloned:
                    self.model.prepare_conditionals(reference, exaggeration=exaggeration)
                    if len(self.cloned) >= 8:
                        self.cloned.pop(next(iter(self.cloned)))
                    self.cloned[reference] = self.model.conds
                self.model.conds = self.cloned[reference]
            else:
                if self.default_voice is None:
                    raise Refused("this endpoint has no built-in Chatterbox voice; send reference_audio")
                self.model.conds = self.default_voice
            gap = np.zeros(int(rate * CHATTERBOX_GAP_SECONDS), dtype="float32")
            parts: List[Any] = []
            with torch.inference_mode():
                for i, piece in enumerate(pieces):
                    wav = self.model.generate(piece, exaggeration=exaggeration, cfg_weight=cfg_weight,
                                              temperature=temperature)
                    if i:
                        parts.append(gap)
                    parts.append(wav.detach().cpu().numpy().reshape(-1).astype("float32"))
        if not parts:
            raise RuntimeError("Chatterbox produced no audio")
        return np.concatenate(parts), rate, ("cloned" if reference else "default")


KOKORO = Kokoro()
CHATTERBOX = Chatterbox()


# --------------------------------------------------------------------------- #
# The voice sample
# --------------------------------------------------------------------------- #

def _public_address(url: str) -> bool:
    """
    The link's host is on the public internet: every address it resolves to
    is global - never this machine, a private network or a cloud's metadata
    service. A name that does not resolve right now is a RuntimeError (worth
    another try), not a refusal.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise RuntimeError(f"the voice sample's host cannot be resolved ({type(e).__name__})") from None
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return False
    return bool(infos)


def _fetch(url: str) -> bytes:
    """
    A voice sample by link: public addresses only, every redirect checked
    again (at most REFERENCE_MAX_REDIRECTS), at most REFERENCE_MAX_BYTES read.
    """
    import requests
    for _hop in range(REFERENCE_MAX_REDIRECTS + 1):
        if not _public_address(url):
            raise Refused("the voice sample link must point at a public internet address")
        try:
            with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urllib.parse.urljoin(url, r.headers["location"])
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    # The sample's host is busy or down for a moment: worth another try.
                    raise RuntimeError(f"the voice sample could not be downloaded (HTTP {r.status_code})")
                if r.status_code >= 300:
                    raise Refused(f"the voice sample could not be downloaded (HTTP {r.status_code})")
                data = bytearray()
                for block in r.iter_content(chunk_size=1 << 20):
                    data += block
                    if len(data) > REFERENCE_MAX_BYTES:
                        raise Refused("the voice sample is too large (30 MB at most; 10-30 s is all that is used)")
                return bytes(data)
        except requests.RequestException as e:
            # The link may be down for a moment: a failure worth another try, not a refusal.
            raise RuntimeError(f"the voice sample could not be downloaded ({type(e).__name__})") from None
    raise Refused(f"the voice sample link redirects more than {REFERENCE_MAX_REDIRECTS} times")


def reference_file(value: str) -> str:
    """
    A voice sample - a link, a data: URI or bare base64 - as a clean mono WAV
    on this disk (its first 30 s; Chatterbox listens to about 10). Kept by
    content, so the thirteen parts of one narration decode it once.
    """
    value = str(value or "").strip()
    if not value:
        return ""
    os.makedirs(REFERENCE_DIR, exist_ok=True)
    key = hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()[:32]
    wav = os.path.join(REFERENCE_DIR, f"{key}.wav")
    if os.path.isfile(wav) and os.path.getsize(wav) > 44:
        return wav
    if re.match(r"https?://", value):
        data = _fetch(value)
    else:
        try:
            data = base64.b64decode(value.split(",", 1)[1] if value.startswith("data:") else value, validate=False)
        except (ValueError, IndexError):
            data = b""
        if len(data) > REFERENCE_MAX_BYTES:
            raise Refused("the voice sample is too large (30 MB at most; 10-30 s is all that is used)")
    if len(data) < 1000:
        raise Refused("the voice sample is empty or not audio")
    # File names of this request's own: the parts of one narration arrive
    # together with the same new sample and must never write over each other.
    fd, raw = tempfile.mkstemp(prefix=f"{key}.", suffix=".src", dir=REFERENCE_DIR)
    tmp = raw[:-len(".src")] + ".tmp.wav"
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # Read as a plain audio file only (SAMPLE_FORMATS): never as a list or
        # playlist that names other files or addresses.
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y",
                            "-protocol_whitelist", "file", "-format_whitelist", SAMPLE_FORMATS, "-i", raw, "-vn",
                            "-ac", "1", "-ar", "24000", "-t", str(REFERENCE_KEEP_SECONDS), "-c:a", "pcm_s16le",
                            tmp], capture_output=True, timeout=120)
        if p.returncode != 0 or not os.path.isfile(tmp):
            raise Refused("the voice sample cannot be read as audio")
        with wave.open(tmp, "rb") as w:
            seconds = w.getnframes() / float(w.getframerate() or 1)
        if seconds < REFERENCE_MIN_SECONDS:
            raise Refused(f"the voice sample is only {seconds:.1f} s long; 10-30 s of clear speech works best")
        os.replace(tmp, wav)
    finally:
        for path in (raw, tmp):
            try:
                os.remove(path)
            except OSError:
                pass
    return wav


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #

# response_format -> (ffmpeg codec arguments, ffmpeg muxer, Content-Type)
FORMATS = {"wav": (["-c:a", "pcm_s16le"], "wav", "audio/wav"),
           "flac": (["-c:a", "flac"], "flac", "audio/flac"),
           "mp3": (["-c:a", "libmp3lame", "-b:a", "128k"], "mp3", "audio/mpeg"),
           "opus": (["-c:a", "libopus", "-b:a", "64k"], "ogg", "audio/ogg"),
           "aac": (["-c:a", "aac", "-b:a", "128k"], "adts", "audio/aac"),
           "pcm": (["-c:a", "pcm_s16le"], "s16le", "audio/pcm")}


def encode(samples, rate: int, fmt: str, tempo: float = 1.0) -> Tuple[bytes, str]:
    """
    Mono float samples as a complete file in `fmt` (and its Content-Type).
    Through a real file, not a pipe: a FLAC or WAV written to a pipe has no
    length in its header, and the worker measures every part it receives.
    `tempo` speeds the speech up or down without changing its pitch.
    """
    import numpy as np
    if fmt not in FORMATS:
        raise Refused(f"response_format '{str(fmt)[:20]}' is not supported ({', '.join(FORMATS)})")
    pcm = (np.clip(np.asarray(samples, dtype="float32").reshape(-1), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    codec, muxer, kind = FORMATS[fmt]
    steady = abs(float(tempo) - 1.0) < 0.01
    if steady and fmt == "pcm":
        return pcm, kind
    if steady and fmt == "wav":
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(rate))
            w.writeframes(pcm)
        return buf.getvalue(), kind
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, f"speech.{muxer}")
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y",
               "-f", "s16le", "-ar", str(int(rate)), "-ac", "1", "-i", "pipe:0"]
        if not steady:
            cmd += ["-af", f"atempo={max(0.5, min(2.0, float(tempo))):.3f}"]
        cmd += [*codec, "-f", muxer, out]
        p = subprocess.run(cmd, input=pcm, capture_output=True, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg could not write {fmt}: {p.stderr.decode('utf-8', 'replace')[-200:]}")
        with open(out, "rb") as f:
            return f.read(), kind


# --------------------------------------------------------------------------- #
# One request
# --------------------------------------------------------------------------- #

_MODEL_NAMES = {"": "kokoro", "kokoro": "kokoro", "kokoro-82m": "kokoro", "tts-1": "kokoro", "tts-1-hd": "kokoro",
                "chatterbox": "chatterbox", "chatterbox-tts": "chatterbox"}


def _number(req: dict, key: str, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(req.get(key, default))))
    except (TypeError, ValueError):
        return default


def speak(req: Dict[str, Any]) -> Dict[str, Any]:
    """
    OpenAI's speech request ({model, voice, input, response_format, speed},
    plus reference_audio / exaggeration / cfg_weight / temperature for
    Chatterbox) -> {"audio" (bytes), "content_type", "format", "seconds",
    "sample_rate", "gpu_seconds", "model", "voice"}.
    """
    if not isinstance(req, dict):
        raise Refused("the request must be a JSON object")
    text = str(req.get("input") if req.get("input") is not None else req.get("text") or "").strip()
    if not text:
        raise Refused("input is empty: there is nothing to say")
    if len(text) > MAX_INPUT_CHARS:
        raise Refused(f"input is {len(text)} characters; one request takes up to {MAX_INPUT_CHARS}")
    model = _MODEL_NAMES.get(str(req.get("model") or "").strip().lower())
    if model is None:
        raise Refused(f"unknown model '{str(req.get('model'))[:40]}' (kokoro, chatterbox)")
    fmt = str(req.get("response_format") or "mp3").strip().lower()
    if fmt not in FORMATS:
        raise Refused(f"response_format '{fmt[:20]}' is not supported ({', '.join(FORMATS)})")
    speed = _number(req, "speed", 1.0, 0.5, 2.0)
    sample = str(req.get("reference_audio") or "").strip()
    started = time.perf_counter()
    if model == "chatterbox":
        if not chatterbox_enabled():
            raise Refused("Chatterbox is not enabled on this endpoint (build the image with WITH_CHATTERBOX=1)")
        samples, rate, voice = CHATTERBOX.synthesize(
            text, reference_file(sample), exaggeration=_number(req, "exaggeration", 0.5, 0.0, 2.0),
            cfg_weight=_number(req, "cfg_weight", 0.5, 0.0, 1.0), temperature=_number(req, "temperature", 0.8, 0.05, 2.0))
        tempo = speed                               # Chatterbox has no speed of its own
    else:
        if sample:
            raise Refused("a voice sample needs model 'chatterbox'; Kokoro speaks in its built-in voices only")
        samples, rate, voice = KOKORO.synthesize(text, req.get("voice"), speed)
        tempo = 1.0
    gpu_seconds = time.perf_counter() - started
    audio, kind = encode(samples, rate, fmt, tempo)
    return {"audio": audio, "content_type": kind, "format": fmt,
            "seconds": round(len(samples) / float(rate) / tempo, 3), "sample_rate": int(rate),
            "gpu_seconds": round(gpu_seconds, 3), "model": model, "voice": voice}


def preload() -> None:
    """Load what TTS_PRELOAD names (default: kokoro) before the first request, so it is not the slow one."""
    names = [n.strip().lower() for n in os.getenv("TTS_PRELOAD", "kokoro").split(",") if n.strip()]
    with _GPU:
        if "kokoro" in names:
            KOKORO.load()
        if "chatterbox" in names and chatterbox_enabled():
            CHATTERBOX.load()


def revisions() -> Dict[str, Any]:
    """Which model revisions this image was built with (fetch_models.py writes them down)."""
    try:
        with open(os.path.join(MODELS_DIR, "MANIFEST.json"), encoding="utf-8") as f:
            data = json.load(f)
        return {k: v.get("revision") for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def health() -> Dict[str, Any]:
    return {"ok": True,
            "device": KOKORO.device or CHATTERBOX.device or "not loaded yet",
            "engines": {"kokoro": {"loaded": KOKORO.model is not None, "voices": len(KOKORO.voices())},
                        "chatterbox": {"enabled": chatterbox_enabled(), "loaded": CHATTERBOX.model is not None}},
            "defaultVoice": DEFAULT_VOICE, "formats": sorted(FORMATS), "revisions": revisions()}
