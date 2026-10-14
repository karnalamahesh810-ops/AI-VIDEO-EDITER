"""
Narration for the celeb style: one request per narration block to our own voice server (Qwen3-TTS,
langversion.VoiceServer), so every block is its own file and needs no alignment. Each block is
levelled to the narration target (-16 LUFS) with 0.15 s of room at its end.
"""
import base64
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import requests

from .. import langversion

R2 = "https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev"
# The app's built-in narrators (app _shared/ownTts.ts OWN_PRESETS): reference audio we generated + its transcript.
PRESETS: Dict[str, dict] = {
    "doc-male": {"url": f"{R2}/tts/voices/doc-male-v1-9bc6d9daf1c0.wav",
                 "text": "Every great river has a story. This one begins high in the mountains, where the snow melts "
                         "each spring and gathers into streams. For thousands of years, it carved its way through "
                         "stone, patiently, one grain of sand at a time."},
    "energetic": {"url": f"{R2}/tts/voices/energetic-v1-a5e1879071b6.wav",
                  "text": "Here's the crazy part. In just one weekend, the river jumped twelve feet, and almost "
                          "nobody saw it coming! So what actually happened? Let's break it down, step by step, "
                          "because the answer is wild."},
}
TARGET_LUFS = -16.0
TAIL = 0.15


def level(src: str, dst: str, target: float = TARGET_LUFS, tail: float = TAIL) -> str:
    """Loudness-normalise to `target` LUFS (true peak -1.5) and pad `tail` s of silence; 48 kHz stereo wav."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af",
                    f"loudnorm=I={target}:TP=-1.5:LRA=11,apad=pad_dur={tail}", "-ar", "48000", "-ac", "2", dst],
                   check=True, timeout=300)
    return dst


def cache_key(text: str, ref: dict, speed: float) -> str:
    import hashlib
    return hashlib.sha1(f"{text}|{ref.get('url', '')}|{speed:.3f}".encode()).hexdigest()[:12]


def body(text: str, voice: dict, seed: int, speed: float = 1.0) -> dict:
    return {"action": "tts", "text": text, "language": "en", "voice": voice, "seed": int(seed),
            "speed": round(float(speed), 3), "pause": 0.4, "format": "mp3", "return": "url",
            "tail_pause": 0.0, "validate": True, "max_attempts": 2}


def synthesize(texts: List[str], work: str, *, voice: str = "doc-male", speed: float = 1.0, seed: int = 7,
               server: Optional[langversion.VoiceServer] = None, parallel: int = 3) -> List[str]:
    """One levelled wav per narration block, in order."""
    os.makedirs(work, exist_ok=True)
    server = server or langversion.VoiceServer()
    ref = voice if isinstance(voice, dict) else PRESETS.get(str(voice), PRESETS["doc-male"])

    def one(i: int) -> str:
        done = os.path.join(work, f"narr_{cache_key(texts[i], ref, speed)}.wav")
        if os.path.isfile(done) and os.path.getsize(done) > 1000:      # same line, same voice: reuse it
            return done
        out = server.voice(body(texts[i], ref, seed + i, speed), timeout=420)
        raw = os.path.join(work, f"narr_{cache_key(texts[i], ref, speed)}.mp3")
        if out.get("audio_url"):
            r = requests.get(out["audio_url"], timeout=120)
            r.raise_for_status()
            with open(raw, "wb") as fh:
                fh.write(r.content)
        elif out.get("audio_b64"):
            with open(raw, "wb") as fh:
                fh.write(base64.b64decode(out["audio_b64"]))
        else:
            raise RuntimeError("the voice job finished without audio")
        return level(raw, done)

    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(texts)))) as pool:
        return list(pool.map(one, range(len(texts))))
