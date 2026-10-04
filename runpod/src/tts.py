"""
Script -> narration: the voice-over made from the script by a free voice.

The owner's flow (2026-08-14): "just paste script, select voice over or
directly upload audio, and make video". Until now the worker only took the
finished audio: premium voices are made in the app and arrive as audio_url.
This is the free path. The script goes to a voice endpoint of our own
(runpod/tts_server: Kokoro, Apache-2.0; Chatterbox, MIT, which clones a
voice from a 10-30 s sample), billed by the GPU second and not by the
character, and comes back as one narration file:

  * the script is cleaned of what is never read aloud (markdown marks,
    [stage directions], a "NARRATOR:" label);
  * it is cut into parts of at most TTS_CHUNK_CHARS characters, always at
    a sentence end - a part cut mid-sentence is read with the wrong melody
    - and at a paragraph end where one is near;
  * TTS_WORKERS parts are voiced at once; a part is asked again after a
    network error, a 5xx, a 429 or a worker that died, and also when its
    audio is far too short for its text (a model that stopped early): the
    narration is refused rather than shipped with words missing;
  * the whole narration - every part, every retry, every wait for a cold
    GPU - has TTS_TOTAL_SECONDS: past it the parts still running are
    cancelled and the job stops with a plain message, never running on
    into the job's own time limit;
  * the parts are joined in script order with ffmpeg, a short breath
    between them, and the whole file is brought to the loudness the
    worker's narrations sit at and its sounds are planned against
    (sfxplan.VOICE_LUFS_DEFAULT) with ONE steady gain, held under the
    peaks - no compressor, so the voice is never pumped.

Two wire formats, told apart by TTS_API_BASE (TTS_API_MODE forces one):

  openai  POST {base}/v1/audio/speech  {model, voice, input, response_format,
          speed}; the answer's body is the audio.
  runpod  a RunPod queue endpoint (https://api.runpod.ai/v2/<id>): the same
          fields as {"input": {...}} to /runsync, then /status while a cold
          worker loads its model; the audio comes back base64.

Whisper still runs on the result (handler.do_plan): the word timings every
cut and caption lands on are measured from the audio, never assumed from
the script. No message here ever carries the endpoint's key.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as _WaitedTooLong
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from . import config, costs, sfxplan, voicepolish

_FFMPEG = "ffmpeg"
JOIN_RATE = 44100                 # Hz: every part is brought to one rate (mono) before the join
TRUE_PEAK_MAX = -1.0              # dBFS: the gain never lifts the loudest peak over this
LEVEL_TOLERANCE = 0.2             # LU: a finished file this far off the target is written once more
POLL_SECONDS = 2.0                # between two looks at a RunPod job that is still running
# A chunk closes at a paragraph end once it is this full: the breath between
# two parts then falls where the script itself pauses.
PARAGRAPH_FILL = 0.6
# Nobody narrates faster than this many characters a second (a documentary
# voice reads 14-17): audio shorter than its text allows means the model
# stopped early. Only judged on a part long enough for the rate to mean something.
MAX_CHARS_PER_SECOND = 32.0
MIN_CHARS_TO_JUDGE = 80
# The model names the voice endpoint answers with Kokoro (tts_server/engines.py
# _MODEL_NAMES): built-in voices only, never a voice sample.
KOKORO_MODELS = {"kokoro", "kokoro-82m", "tts-1", "tts-1-hd"}


def _sleep(seconds: float, stop: Optional[threading.Event] = None) -> None:
    """Wait, but not past the moment the narration is given up (tests replace it)."""
    if stop is not None:
        stop.wait(seconds)
    else:
        time.sleep(seconds)


def _stopped(stop: Optional[threading.Event]) -> bool:
    return stop is not None and stop.is_set()


class TtsError(RuntimeError):
    """The narration could not be made. The message is written for the owner."""


class NotConfigured(TtsError):
    """A script-only job on a worker without a voice endpoint."""


class _Again(Exception):
    """A failure worth asking again: the network, a 5xx, a cold or dead worker, cut-off audio."""


class _TimeUp(TtsError):
    """The narration's own time (TTS_TOTAL_SECONDS) ran out while a part was still being asked for."""


def _left(deadline: float) -> float:
    """Seconds until `deadline` (epoch seconds); unlimited without one."""
    return deadline - time.time() if deadline else float("inf")


# --------------------------------------------------------------------------- #
# When
# --------------------------------------------------------------------------- #

def configured() -> bool:
    return bool(config.TTS_API_BASE)


def wanted(inp: Optional[dict]) -> bool:
    """A job that brings a script and no narration: its voice-over is ours to make."""
    inp = inp or {}
    if inp.get("audio_url") or inp.get("audio_path"):
        return False
    return isinstance(inp.get("script"), str) and bool(inp["script"].strip())


def mode() -> str:
    """ "runpod" (queue endpoint: /runsync, base64 audio) or "openai" (/v1/audio/speech)."""
    if config.TTS_API_MODE in ("openai", "runpod"):
        return config.TTS_API_MODE
    return "runpod" if re.search(r"api\.runpod\.ai/v2/[^/]+$", config.TTS_API_BASE or "") else "openai"


def status() -> Dict[str, Any]:
    """For the health check: can this worker voice a script, and with what (never the address or the key)."""
    if not configured():
        return {"configured": False}
    return {"configured": True, "mode": mode(), "model": config.TTS_MODEL, "voice": config.TTS_VOICE,
            "key": bool(config.TTS_API_KEY), "cloning": bool(config.TTS_REFERENCE_AUDIO)}


def target_lufs() -> float:
    v = float(config.TTS_LUFS or 0.0)
    return v if -60.0 < v < 0.0 else sfxplan.VOICE_LUFS_DEFAULT


def options(inp: Optional[dict] = None) -> Dict[str, Any]:
    """
    The voice of one job: tts_model, tts_voice, tts_speed and
    tts_reference_audio from the input, else the endpoint's settings. A job
    may only name a voice sample by link - never a file on this worker.
    """
    inp = inp or {}

    def text(key: str, default: str) -> str:
        v = inp.get(key)
        return v.strip()[:120] if isinstance(v, str) and v.strip() else default
    try:
        speed = float(inp.get("tts_speed") or config.TTS_SPEED or 1.0)
    except (TypeError, ValueError):
        speed = float(config.TTS_SPEED or 1.0)
    model = text("tts_model", config.TTS_MODEL or "kokoro")
    ref = inp.get("tts_reference_audio")
    if not (isinstance(ref, str) and re.match(r"https?://", ref.strip())):
        # The worker's own sample is for the voice that clones: sent along with
        # Kokoro it would make the endpoint refuse every part of the narration.
        ref = "" if model.lower() in KOKORO_MODELS else config.TTS_REFERENCE_AUDIO
    return {"model": model,
            "voice": text("tts_voice", config.TTS_VOICE or "af_heart"),
            "speed": round(max(0.5, min(2.0, speed)), 3),
            "reference": str(ref or "").strip(),
            # Raw pcm has no header: its length could never be measured (every part would "fail").
            "format": config.TTS_FORMAT if config.TTS_FORMAT in _EXT and config.TTS_FORMAT != "pcm" else "flac"}


# --------------------------------------------------------------------------- #
# The script: what is read aloud, and where it may be cut
# --------------------------------------------------------------------------- #

_LINK = re.compile(r"\[([^\[\]\n]+)\]\(\s*https?://[^)\s]+\s*\)")          # [text](link) -> text
_DIRECTION = re.compile(r"\[[^\[\]\n]{0,200}\]")                           # [MUSIC], [B-ROLL: the dam]
_LABEL = re.compile(r"^(?:narrator|narration|voice[ -]?over|v\.?o\.?)\s*:\s*", re.I)       # NARRATOR: ...
_HEADING = re.compile(r"^#{1,6}\s*")
_BULLET = re.compile(r"^(?:[-*•]\s+)")
_RULE = re.compile(r"^[-*_=~\s]{3,}$")                                     # --- and friends


def clean_script(script: str) -> str:
    """
    The script as it is read aloud, one paragraph per line: markdown marks,
    [stage directions] and a leading "NARRATOR:" label are dropped (a voice
    would read "asterisk asterisk" or "music" out loud), spaces are tidied.
    The words themselves are never changed.
    """
    lines = []
    for raw in str(script or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.replace(chr(0xA0), " ").replace("\t", " ").strip()
        if not line or _RULE.match(line):
            continue
        line = _HEADING.sub("", line)
        line = _BULLET.sub("", line)
        line = _LINK.sub(r"\1", line)
        line = _DIRECTION.sub(" ", line)
        line = _LABEL.sub("", line.strip())
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", line)      # *emphasis*
        line = re.sub(r"(?<!\w)_(?=\S)|(?<=\S)_(?!\w)", "", line)            # _emphasis_
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+([,.;:!?])(?=\s|$)", r"\1", line)                 # "word ." after a direction
        if line:
            lines.append(line)
    return "\n".join(lines)


# After these a full stop does not end a sentence. Being generous is safe: a
# missed sentence end only makes two sentences travel together.
_ABBREV = {"mr", "mrs", "ms", "dr", "st", "sr", "jr", "vs", "prof", "gen", "gov", "sen", "rep", "lt", "col",
           "capt", "sgt", "cmdr", "mt", "ft", "no", "inc", "ltd", "co", "corp", "etc", "approx", "est", "fig",
           "dept", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
_INITIALS = re.compile(r"(?:[a-z]\.)*[a-z]")                                # j   u.s   e.g   a.m
_SENT_END = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+)")
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)$")
_CLAUSE = re.compile(r"(?<=[,;:—–])\s+")
_CLOSED = re.compile(r"[.!?…:;,—–][\"'”’)\]]*$")      # the line ends on a mark of its own


def _abbreviation(line: str, at: int, mark: str) -> bool:
    if not mark.startswith(".") or mark.startswith(".."):
        return False
    m = _LAST_WORD.search(line[:at])
    if not m:
        return False
    word = m.group(1).lower()
    return word in _ABBREV or bool(_INITIALS.fullmatch(word))


def _sentences(text: str) -> List[Tuple[str, bool]]:
    """(sentence, it ends a paragraph) in reading order. A line break always ends a sentence."""
    out: List[List[Any]] = []
    for line in str(text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        start, before = 0, len(out)
        for m in _SENT_END.finditer(line):
            mark = m.group(1)
            if _abbreviation(line, m.start(1), mark):
                continue
            if (mark.startswith("..") or mark.startswith("…")) and line[m.end():m.end() + 1].islower():
                continue                            # "nobody knows... but the numbers": a pause, not an end
            out.append([line[start:m.end(1)].strip(), False])
            start = m.end()
        tail = line[start:].strip()
        if tail:
            # A line that just stops (a heading, a list item) still ends: without
            # a mark the voice would run it into the next line without a breath.
            out.append([tail if _CLOSED.search(tail) else tail + ".", False])
        if len(out) > before:
            out[-1][1] = True
    return [(s, bool(p)) for s, p in out if s]


def split_sentences(text: str) -> List[str]:
    return [s for s, _ in _sentences(text)]


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


def _split_long(sentence: str, limit: int) -> List[str]:
    """One sentence longer than a part may be: cut at its commas, then between words."""
    pieces: List[str] = []
    for clause in _CLAUSE.split(sentence):
        if len(clause) <= limit:
            pieces.append(clause)
            continue
        words: List[str] = []
        for w in clause.split(" "):
            # A "word" longer than a whole part (a pasted link) is cut where it must be.
            words.extend(w[i:i + limit] for i in range(0, len(w), limit))
        pieces.extend(_pack(words, limit))
    return _pack(pieces, limit)


def chunk_script(text: str, max_chars: Optional[int] = None) -> List[str]:
    """
    The script in parts of at most `max_chars` characters, in order, every
    word kept. A part ends at a sentence end (a sentence that is itself too
    long is cut at a comma, then between words), and at a paragraph end once
    it is PARAGRAPH_FILL full.
    """
    limit = max(40, int(max_chars or config.TTS_CHUNK_CHARS or 1500))
    chunks: List[str] = []
    cur: List[str] = []
    size = 0

    def flush() -> None:
        nonlocal cur, size
        if cur:
            chunks.append(" ".join(cur))
        cur, size = [], 0
    for sentence, paragraph_end in _sentences(text):
        for piece in ([sentence] if len(sentence) <= limit else _split_long(sentence, limit)):
            if cur and size + 1 + len(piece) > limit:
                flush()
            size += len(piece) + (1 if cur else 0)
            cur.append(piece)
        if paragraph_end and size >= PARAGRAPH_FILL * limit:
            flush()
    flush()
    return chunks


# --------------------------------------------------------------------------- #
# One part: the request
# --------------------------------------------------------------------------- #

_EXT = {"flac": "flac", "wav": "wav", "mp3": "mp3", "opus": "opus", "aac": "aac", "pcm": "pcm"}
_REF_CACHE: Dict[str, str] = {}


def _json_env(raw: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _reference_value(ref: str) -> str:
    """The voice sample as the endpoint takes it: a link as it is, a local file as a data URI."""
    ref = str(ref or "").strip()
    if not ref:
        return ""
    if re.match(r"https?://", ref):
        return ref
    if ref not in _REF_CACHE:
        try:
            with open(ref, "rb") as f:
                data = f.read()
            kind = os.path.splitext(ref)[1].lstrip(".").lower() or "wav"
            _REF_CACHE[ref] = f"data:audio/{kind};base64," + base64.b64encode(data).decode("ascii")
        except OSError as e:
            raise TtsError(f"the voice sample (TTS_REFERENCE_AUDIO) cannot be read: {type(e).__name__}") from None
    return _REF_CACHE[ref]


def request_body(text: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    """One part's request: OpenAI's speech fields, the voice sample, TTS_EXTRA, renamed by TTS_FIELDS."""
    body: Dict[str, Any] = {"model": opts["model"], "voice": opts["voice"], "input": text,
                            "response_format": opts["format"], "speed": opts["speed"]}
    ref = _reference_value(opts.get("reference") or "")
    if ref:
        body["reference_audio"] = ref
    body.update(_json_env(config.TTS_EXTRA))
    names = {k: v for k, v in _json_env(config.TTS_FIELDS).items() if isinstance(v, str) and v}
    return {names.get(k, k): v for k, v in body.items()}


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {config.TTS_API_KEY}"} if config.TTS_API_KEY else {}


def _error_text(r) -> str:
    try:
        data = r.json()
    except ValueError:
        return str(getattr(r, "text", "") or "")[:200]
    if isinstance(data, dict):
        err = data.get("error") if data.get("error") is not None else data.get("detail", data.get("message"))
        if isinstance(err, dict):
            err = err.get("message") or err
        return str(err if err is not None else data)[:200]
    return str(data)[:200]


def _check_status(r) -> None:
    code = int(r.status_code)
    if code < 400:
        return
    if code in (408, 425, 429) or code >= 500:
        raise _Again(f"the voice endpoint answered HTTP {code}: {_error_text(r)}")
    if code in (401, 403):
        raise TtsError(f"the voice endpoint refused the key (HTTP {code}); check TTS_API_KEY")
    raise TtsError(f"the voice endpoint refused the request (HTTP {code}): {_error_text(r)}")


def _num(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _request_openai(body: dict, timeout: float, stop: Optional[threading.Event] = None) -> Tuple[bytes, dict]:
    base = config.TTS_API_BASE
    url = base + ("/audio/speech" if base.endswith("/v1") else "/v1/audio/speech")
    try:
        r = requests.post(url, json=body, headers=_headers(), timeout=(20, timeout))
    except requests.RequestException as e:
        raise _Again(f"the voice endpoint did not answer ({type(e).__name__})") from None
    _check_status(r)
    kind = (r.headers.get("Content-Type") or "").lower()
    data = r.content or b""
    if "json" in kind or kind.startswith("text/") or len(data) < 64:
        raise _Again(f"the voice endpoint answered without audio ({kind or 'no content type'})")
    return data, {"gpu_seconds": _num(r.headers.get("X-Gpu-Seconds"))}


def _cancel(job_id: str) -> None:
    try:
        requests.post(f"{config.TTS_API_BASE}/cancel/{job_id}", headers=_headers(), timeout=(10, 20))
    except requests.RequestException:
        pass


def _request_runpod(body: dict, timeout: float, stop: Optional[threading.Event] = None) -> Tuple[bytes, dict]:
    """
    /runsync answers within ~90 s; a cold worker (the image starting, the
    model going onto the GPU) or a long Chatterbox part takes longer, so a
    job that is still queued or running is followed on /status until
    `timeout`, then cancelled - a part given up must not keep a GPU busy.
    """
    base, deadline = config.TTS_API_BASE, time.time() + timeout
    try:
        r = requests.post(f"{base}/runsync", json={"input": body}, headers=_headers(), timeout=(20, 150))
    except requests.RequestException as e:
        raise _Again(f"the voice endpoint did not answer ({type(e).__name__})") from None
    while True:
        _check_status(r)
        try:
            data = r.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise _Again("the voice endpoint answered with something that is not a job")
        status = str(data.get("status") or "").upper()
        if status == "COMPLETED":
            break
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise _Again(f"the voice job {status.lower().replace('_', ' ')}: {str(data.get('error') or '')[:160]}")
        job_id = str(data.get("id") or "")
        if not job_id:
            raise _Again("the voice endpoint answered without a job id")
        if time.time() >= deadline or _stopped(stop):
            _cancel(job_id)
            raise _Again(f"no audio within {int(timeout)} s")
        while True:
            _sleep(POLL_SECONDS, stop)
            try:
                r = requests.get(f"{base}/status/{job_id}", headers=_headers(), timeout=(20, 60))
            except requests.RequestException:
                r = None
            if r is not None and not (r.status_code == 429 or r.status_code >= 500):
                break
            if time.time() >= deadline or _stopped(stop):
                _cancel(job_id)
                raise _Again(f"no audio within {int(timeout)} s")
    out = data.get("output")
    if not isinstance(out, dict):
        raise _Again("the voice endpoint finished without audio")
    if out.get("refused"):
        # The server's "this request can never work" (an unknown voice, an engine that is off).
        raise TtsError(f"the voice endpoint refused the request: {str(out['refused'])[:200]}")
    try:
        audio = base64.b64decode(str(out.get("audio_base64") or ""))
    except (ValueError, TypeError):
        audio = b""
    if len(audio) < 64:
        raise _Again("the voice endpoint finished without audio")
    return audio, {"gpu_seconds": _num(out.get("gpu_seconds")) or _num(data.get("executionTime")) / 1000.0}


def _seconds(path: str) -> float:
    return float(voicepolish.probe(path).get("seconds") or 0.0)


def least_seconds(text: str, speed: float = 1.0) -> float:
    """The shortest this text can honestly be spoken in; 0 for a part too short to judge."""
    chars = len(text or "")
    if chars < MIN_CHARS_TO_JUDGE:
        return 0.0
    return chars / (MAX_CHARS_PER_SECOND * max(0.5, float(speed or 1.0)))


def voice_part(index: int, total: int, text: str, stem: str, opts: Dict[str, Any],
               stop: Optional[threading.Event] = None, deadline: float = 0.0) -> Dict[str, Any]:
    """
    One part voiced and on disk: {"path", "seconds", "gpu_seconds", "attempts"};
    TtsError when it cannot be. `stop` is the narration's own "given up" flag:
    once another part has failed for good, this one stops asking. `deadline`
    (epoch seconds, 0 = none) is the whole narration's: no attempt starts
    after it and none waits longer than what is left of it.
    """
    body = request_body(text, opts)
    ask = _request_runpod if mode() == "runpod" else _request_openai
    path = f"{stem}.{_EXT.get(opts['format'], 'flac')}"
    retries, last = max(0, int(config.TTS_RETRIES)), ""
    for attempt in range(1, retries + 2):
        if _stopped(stop):
            raise TtsError("stopped: another part of the narration failed")
        left = _left(deadline)
        if left <= 1.0:
            raise _TimeUp(f"part {index + 1} of {total} was not voiced in time"
                          + (f" ({last[:160]})" if last else ""))
        try:
            audio, info = ask(body, min(float(config.TTS_TIMEOUT), left), stop)
            with open(path, "wb") as f:
                f.write(audio)
            seconds = _seconds(path)
            if seconds <= 0:
                raise _Again("the audio that came back cannot be read")
            if seconds < least_seconds(text, opts["speed"]):
                raise _Again(f"the voice stopped early ({seconds:.1f} s of audio for {len(text)} characters)")
            return {"path": path, "seconds": seconds, "gpu_seconds": _num(info.get("gpu_seconds")),
                    "attempts": attempt}
        except _Again as e:
            last = str(e)
            print(f"[tts] part {index + 1}/{total}, attempt {attempt}: {last[:180]}", flush=True)
            if attempt <= retries and not _stopped(stop):
                _sleep(max(0.0, min(20.0, 2.0 * attempt * attempt, _left(deadline) - 1.0)), stop)
    raise TtsError(f"part {index + 1} of {total} could not be voiced after {retries + 1} attempts: {last[:240]}")


# --------------------------------------------------------------------------- #
# The join
# --------------------------------------------------------------------------- #

def _run(argv: List[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def _ffmpeg(argv: List[str], timeout: float, what: str) -> None:
    try:
        p = _run([_FFMPEG, "-hide_banner", "-nostats", "-y", *argv], timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TtsError(f"ffmpeg could not {what}: {type(e).__name__}") from None
    if p.returncode != 0:
        raise TtsError(f"ffmpeg could not {what}: {(p.stderr or '').strip()[-240:]}")


def _loudness(path: str) -> Dict[str, Optional[float]]:
    return voicepolish.loudness(path)


_ENCODE = {"mp3": ["-c:a", "libmp3lame", "-b:a", "128k"], "wav": ["-c:a", "pcm_s16le"],
           "flac": ["-c:a", "flac"], "m4a": ["-c:a", "aac", "-b:a", "128k"]}


def output_format() -> str:
    return config.TTS_OUTPUT_FORMAT if config.TTS_OUTPUT_FORMAT in _ENCODE else "mp3"


def steady_gain(lufs: Optional[float], peak: Optional[float], target: float) -> float:
    """dB to bring a measured narration to `target`, never lifting its loudest peak over TRUE_PEAK_MAX."""
    if lufs is None or lufs <= -70.0:
        return 0.0                              # silence or unmeasured: leave it as it is
    gain = target - lufs
    if peak is not None:
        gain = min(gain, TRUE_PEAK_MAX - peak)
    return round(max(-30.0, min(30.0, gain)), 2)


def join(parts: List[str], dest: str, *, gap: Optional[float] = None, target: Optional[float] = None,
         timeout: float = 900.0) -> Dict[str, Any]:
    """
    The parts, in the order given, as one narration at `dest`: each brought
    to one sample rate and mono with `gap` seconds of quiet after it (not
    after the last), joined sample-exact, measured (EBU R128), then encoded
    once with one steady gain to `target` LUFS.
    """
    if not parts:
        raise TtsError("there is nothing to join")
    gap = max(0.0, float(config.TTS_GAP_SECONDS if gap is None else gap))
    target = target_lufs() if target is None else float(target)
    stem = os.path.splitext(dest)[0]
    even, listing, joined = [], f"{stem}.parts.txt", f"{stem}.joined.wav"
    try:
        for i, part in enumerate(parts):
            wav = f"{stem}.part{i:03d}.wav"
            chain = f"aresample={JOIN_RATE},aformat=sample_fmts=s16:channel_layouts=mono"
            if gap > 0 and i < len(parts) - 1:
                chain += f",apad=pad_dur={gap:.3f}"
            _ffmpeg(["-i", part, "-vn", "-af", chain, "-ar", str(JOIN_RATE), "-ac", "1", "-c:a", "pcm_s16le", wav],
                    timeout, f"read part {i + 1}")
            even.append(wav)
        with open(listing, "w", encoding="utf-8") as f:
            for wav in even:
                name = wav.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{name}'\n")
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", listing, "-c:a", "pcm_s16le", joined], timeout,
                "join the parts")

        def write(db: float) -> Dict[str, Optional[float]]:
            _ffmpeg(["-i", joined, "-vn", "-af", f"volume={db:.2f}dB", "-ar", str(JOIN_RATE), "-ac", "1",
                     *_ENCODE[output_format()], dest], timeout, "write the narration")
            return _loudness(dest)
        measured = _loudness(joined)
        source = measured.get("lufs")
        gain = steady_gain(source, measured.get("tp"), target)
        final = write(gain)
        # The encoder has a level of its own (LAME writes an MP3 ~0.5 dB under
        # what it was given, and can push a peak over): the finished file is
        # measured, and written once more when it missed by an audible step.
        miss = steady_gain(final.get("lufs"), final.get("tp"), target) if source is not None and source > -70.0 else 0.0
        if abs(miss) >= LEVEL_TOLERANCE and abs(gain + miss) <= 30.0:
            gain = round(gain + miss, 2)
            final = write(gain)
    finally:
        for path in even + [listing, joined]:
            try:
                os.remove(path)
            except OSError:
                pass
    return {"path": dest, "seconds": round(_seconds(dest), 2), "parts": len(parts),
            "targetLufs": target, "gainDb": gain, "lufs": final.get("lufs"), "peakDb": final.get("tp"),
            "sourceLufs": measured.get("lufs")}


# --------------------------------------------------------------------------- #
# The whole narration
# --------------------------------------------------------------------------- #

def synthesize(script: str, work: str, *, opts: Optional[Dict[str, Any]] = None,
               on_progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """
    The script as one narration file in `work`. Returns what was made:
    {"path", "text" (the words as voiced, for the captions), "seconds",
    "chars", "parts", "voice", "model", "speed", "cloned", "lufs", "gainDb",
    "gpuSeconds", "tookSeconds", "mode"}. `on_progress(done, total)` after
    every part. Raises NotConfigured or TtsError; never returns a narration
    with a part missing.
    """
    if not configured():
        raise NotConfigured(
            "This video was started from a script, but the free voice is not set up on this worker "
            "(TTS_API_BASE is empty). Add a voiceover in the app, or point TTS_API_BASE and TTS_API_KEY "
            "at the voice endpoint (runpod/tts_server).")
    opts = dict(opts or options())
    text = clean_script(script)
    if not text:
        raise TtsError("The script has no words to read aloud.")
    if len(text) > int(config.TTS_MAX_CHARS):
        raise TtsError(f"The script is {len(text):,} characters; the free voice takes up to "
                       f"{int(config.TTS_MAX_CHARS):,} (TTS_MAX_CHARS).")
    chunks = chunk_script(text, config.TTS_CHUNK_CHARS)
    total = len(chunks)
    os.makedirs(work, exist_ok=True)
    started = time.time()
    # The whole narration's time: a slow or GPU-starved endpoint ends the job
    # here with a plain message instead of in the job's own time limit.
    budget = max(0.0, float(config.TTS_TOTAL_SECONDS or 0.0))
    deadline = started + budget if budget else 0.0
    print(f"[tts] {len(text)} characters in {total} part(s), {opts['model']}/{opts['voice']}"
          f"{' (cloned voice)' if opts['reference'] else ''}, {mode()} endpoint", flush=True)
    results: List[Optional[Dict[str, Any]]] = [None] * total
    stop = threading.Event()        # this narration's own: set once a part has failed for good
    pool = ThreadPoolExecutor(max_workers=max(1, min(int(config.TTS_WORKERS), total)), thread_name_prefix="tts")
    done = 0
    try:
        futures = {pool.submit(voice_part, i, total, chunk, os.path.join(work, f"part-{i:03d}"), opts, stop,
                               deadline): i
                   for i, chunk in enumerate(chunks)}
        for fut in as_completed(futures, timeout=max(0.0, _left(deadline)) if deadline else None):
            results[futures[fut]] = fut.result()        # the first failure ends the narration
            done += 1
            if on_progress:
                try:
                    on_progress(done, total)
                except Exception:  # noqa: BLE001 - progress must never cost the narration
                    pass
    except (_WaitedTooLong, _TimeUp) as e:
        stop.set()                                      # running parts cancel their jobs, queued ones never start
        took = f"{budget / 60:.0f} minutes" if budget >= 120 else f"{budget:.0f} seconds"
        print(f"[tts] out of time after {took}: {done} of {total} part(s) made"
              f"{f' ({e})' if str(e) else ''}", flush=True)
        raise TtsError(
            f"The free voice did not finish the narration in time: {done} of {total} parts were made in "
            f"{took} (TTS_TOTAL_SECONDS). The voice endpoint is too slow or has no free GPU; try again "
            "later, or add a voiceover in the app.") from None
    except BaseException:
        stop.set()                                      # running parts stop asking, queued ones never start
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    dest = os.path.join(work, f"narration.{output_format()}")
    joined = join([r["path"] for r in results], dest)
    seconds = float(joined["seconds"] or 0.0) or sum(r["seconds"] for r in results)
    gpu = sum(r["gpu_seconds"] for r in results)
    # The price is per second of narration made (an estimate, costs.DEFAULT_PRICES);
    # the GPU seconds the endpoint reported ride along to calibrate it.
    costs.record("tts.seconds", seconds)
    if gpu > 0:
        costs.record("tts.gpu_seconds", gpu)
    out = {"path": dest, "text": " ".join(chunks), "seconds": round(seconds, 2), "chars": len(text),
           "parts": total, "voice": opts["voice"], "model": opts["model"], "speed": opts["speed"],
           "cloned": bool(opts["reference"]), "lufs": joined["lufs"], "gainDb": joined["gainDb"],
           "peakDb": joined["peakDb"], "retries": sum(r["attempts"] - 1 for r in results),
           "gpuSeconds": round(gpu, 1), "tookSeconds": round(time.time() - started, 1), "mode": mode()}
    print(f"[tts] narration {out['seconds']:.0f} s from {total} part(s) in {out['tookSeconds']:.0f} s "
          f"({out['lufs']} LUFS, gain {out['gainDb']:+.1f} dB)", flush=True)
    return out
