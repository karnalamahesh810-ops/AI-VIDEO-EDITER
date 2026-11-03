"""
What a clip's own sound is (the storm desk style's "clip sound under the voice", src/stormdesk.py): natural
sound (water, wind, rain, engines, sirens, a crowd), speech, music, or silence - read from the clip file alone,
no model call that costs anything:

  * silent   - no sound stream, or the gated level under SILENT_DB;
  * speech   - Silero voice activity (bundled with faster-whisper) over SPEECH_VAD of the clip, confirmed by the
               worker's own whisper model (a segment it believes is speech: no_speech_prob under 0.6 and real
               words) when the voice activity alone is not sure;
  * music    - held tones (spectral peaks well over the spectrum around them that stay on their bin for
               ~130 ms, unlike a siren's sweep, speech's glides or the noise of water and wind), with a lower bar
               when the upload's title says drone / "4K" / relaxing / cinematic (those nearly always carry a
               soundtrack);
  * nature   - everything else with sound.

Only "nature" plays under the narration by default; speech and music stay silent (the owner, 2026-11-03). The
pauses keep their own rules (stormdesk.make_pauses: music never, an eyewitness reacting is fine).
classify() never raises: anything it cannot read is "unknown", which never plays under the voice.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, Optional

SR = 16000
SILENT_DB = -50.0           # gated RMS below this = silence (the pause check's -50 dB mean volume)
SPEECH_VAD = 0.35           # share of the clip Silero calls speech that counts as talking, unconfirmed
SPEECH_MAYBE = 0.12         # ... and from this share whisper is asked to confirm
MUSIC_AT = 0.5
PEAK_DB = 13.0              # a tone: this far over the median of the spectrum around it

# Upload titles that nearly always carry a soundtrack over the picture (the hand-made videos' music sources were
# all drone / 4K travel uploads: tools/storm-desk/henderson/render.py MUSIC_SRC).
_MUSIC_TITLE = re.compile(
    r"\b(music|song|soundtrack|relax(?:ing)?|cinematic|ambient music|lo-?fi|piano|beats?|remix|lyrics?|"
    r"drone|aerial|fpv|4k|8k|uhd|60 ?fps|travel (?:film|video)|by drone|bird'?s.eye|hyperlapse)\b", re.I)
_SPEECH_TITLE = re.compile(r"\b(interview|press conference|briefing|speaks|says|explains|podcast|reacts?|"
                           r"reaction|news ?cast|anchor|reporter|live report|update)\b", re.I)


def read_mono(path: str, start: float = 0.0, seconds: float = 0.0, sr: int = SR):
    """The clip's sound as mono float32 at `sr` (numpy), or None (no sound stream / unreadable)."""
    try:
        import numpy as np
    except ImportError:
        return None
    cmd = ["ffmpeg", "-v", "error", *(["-ss", f"{max(0.0, start):.3f}"] if start > 0 else []), "-i", str(path),
           *(["-t", f"{seconds:.3f}"] if seconds > 0 else []), "-vn", "-map", "0:a:0?", "-ac", "1", "-ar", str(sr),
           "-f", "s16le", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    except Exception:  # noqa: BLE001
        return None
    if len(raw) < sr // 5 * 2:          # under 0.2 s of sound: none
        return None
    return np.frombuffer(raw[: len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768.0


def level_db(x) -> float:
    """Gated RMS (dBFS): the loudest 70% of 50 ms blocks, so a clip's own pauses do not pull it down."""
    import numpy as np
    if x is None or not len(x):
        return -120.0
    n = max(1, int(0.05 * SR))
    k = len(x) // n
    if k < 1:
        return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))
    blocks = np.sqrt(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1))
    blocks = np.sort(blocks)[int(k * 0.3):] if k >= 4 else blocks
    return float(20 * np.log10(np.sqrt(np.mean(blocks ** 2)) + 1e-9))


def music_score(x, title_prior: bool = False) -> Dict[str, float]:
    """
    0..1 how musical a clip's sound is (>= MUSIC_AT = music), from its spectrum in 100-5000 Hz: spectral peaks
    standing PEAK_DB over the median of the spectrum around them (a tone; the broadband noise of water, rain and wind has almost
    none) and how many of those stay on their bin (+-1) for the next four frames, ~130 ms (held notes; a
    siren sweeps, speech glides). Calibrated on the Henderson / Sedona sources (2026-11-03, 47 clips): the owner's
    music uploads hold a tone in 0.29-0.97 of their frames, the clips with neither speech nor music in at most
    0.011 (a station's raw flood video, the water ambience the owner used in the pauses: 0.0). A soundtrack
    title (drone / 4K / relaxing ...) lowers the bar. Returns the parts too.
    """
    import numpy as np
    n, hop = 2048, 512
    if x is None or len(x) < n * 6:
        return {"music": 0.0, "held": 0.0, "peaks": 0.0}
    win = np.hanning(n).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * win
    P = (np.abs(np.fft.rfft(frames, axis=1)) ** 2).astype(np.float64)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    P = P[:, (freqs >= 100) & (freqs <= 5000)] + 1e-12
    # The spectrum around each bin: the median of the 25 bins around it (a chord's other notes do not lift it).
    k = 25
    padded = np.pad(P, ((0, 0), (k // 2, k // 2)), mode="edge")
    local = np.median(np.lib.stride_tricks.sliding_window_view(padded, k, axis=1), axis=2)
    L = 10 * np.log10(P)
    peak = (L - 10 * np.log10(local) > PEAK_DB) & (L >= np.roll(L, 1, 1)) & (L >= np.roll(L, -1, 1))
    total = P.sum(axis=1)
    loud = total > np.percentile(total, 25)
    if loud.sum() < 6:
        return {"music": 0.0, "held": 0.0, "peaks": 0.0}
    pp = peak.astype(np.float32)
    near = np.maximum(np.maximum(np.roll(pp, 1, 1), pp), np.roll(pp, -1, 1))
    kept = (pp[:-4] * near[1:-3] * near[2:-2] * near[3:-1] * near[4:]).sum(axis=1)
    held = float(np.mean(kept[loud[:-4]] >= 1)) if loud[:-4].any() else 0.0
    peaks = float(np.mean(peak.sum(axis=1)[loud]))
    need_held = 0.06 if title_prior else 0.10
    music = 0.5 * min(held / need_held, 2.0) * min(1.0, peaks / 0.8)
    return {"music": round(max(0.0, min(1.0, music)), 3), "held": round(held, 3), "peaks": round(peaks, 2)}


def speech_share(x) -> float:
    """Share of the clip Silero voice activity calls speech (0..1); 0 when the detector is missing."""
    if x is None or not len(x):
        return 0.0
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        ts = get_speech_timestamps(x, VadOptions(threshold=0.5, min_speech_duration_ms=250,
                                                 min_silence_duration_ms=300, speech_pad_ms=100))
    except Exception:  # noqa: BLE001 - no detector: nothing called speech here
        return 0.0
    got = sum(max(0, int(t["end"]) - int(t["start"])) for t in ts)
    return round(min(1.0, got / float(len(x))), 3)


def whisper_says_speech(x) -> Optional[bool]:
    """The worker's own whisper model on the clip: True when it hears words it believes (None = not run)."""
    try:
        from . import transcribe
        model = transcribe._load_model()
        segs, _info = model.transcribe(x, vad_filter=True, beam_size=1, condition_on_previous_text=False)
        words = 0
        for s in segs:
            if float(getattr(s, "no_speech_prob", 1.0)) < 0.6 and float(getattr(s, "avg_logprob", -9.0)) > -1.0:
                words += len(re.findall(r"[A-Za-z']{2,}", str(getattr(s, "text", "") or "")))
        return words >= 3
    except Exception:  # noqa: BLE001
        return None


def classify(path: str, start: float = 0.0, seconds: float = 0.0, title: str = "", confirm: bool = True,
             x=None) -> Dict[str, Any]:
    """{"kind": nature | speech | music | silent | unknown, "speech", "music", "db"} for the clip's
    [start, start + seconds] (0 = to its end). `title`: the upload's title (a soundtrack prior)."""
    try:
        if x is None:
            x = read_mono(path, start, seconds)
        if x is None:
            return {"kind": "silent", "db": -120.0, "speech": 0.0, "music": 0.0, "why": "no sound stream"}
        db = round(level_db(x), 1)
        if db < SILENT_DB:
            return {"kind": "silent", "db": db, "speech": 0.0, "music": 0.0}
        sp = speech_share(x)
        mu = music_score(x, title_prior=bool(_MUSIC_TITLE.search(title or "")))
        music = mu["music"]
        out = {"db": db, "speech": sp, "music": music, "parts": mu}
        talking = sp >= SPEECH_VAD
        if not talking and sp >= SPEECH_MAYBE and confirm:
            heard = whisper_says_speech(x)
            talking = bool(heard)
            out["whisper"] = heard
        elif talking and _SPEECH_TITLE.search(title or ""):
            out["titleSpeech"] = True
        if talking and mu["held"] >= 0.35 and mu["peaks"] >= 5.0:
            out["kind"] = "music"                       # sung or a voice over a soundtrack: both stay silent
        elif talking:
            out["kind"] = "speech"
        elif music >= MUSIC_AT:
            out["kind"] = "music"
        else:
            out["kind"] = "nature"
        return out
    except Exception as e:  # noqa: BLE001 - never plays under the voice
        return {"kind": "unknown", "why": f"{type(e).__name__}: {str(e)[:80]}"}


def plays_under_voice(scene: dict, mode: str) -> bool:
    """The mix rule (the editor's switches): a clip's own true / false wins; otherwise it plays only in
    "ambient" mode and only when its sound is natural. Pause clips are not narration shots (always their own)."""
    if scene.get("natSound"):
        return False
    own = scene.get("clipSound")
    if own is True or own is False:
        return bool(own)
    if str(mode or "").lower() != "ambient":
        return False
    ca = ((scene.get("media") or {}).get("clipAudio") or {})
    return isinstance(ca, dict) and ca.get("kind") == "nature"
