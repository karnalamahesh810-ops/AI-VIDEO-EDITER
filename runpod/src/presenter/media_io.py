"""
ffmpeg work for the AI presenter style: cutting the voice into shot windows,
trimming generated clips to their scenes (sound off), sampling frames for the
checks, finding frozen or black stretches, and measuring how far a returned
clip's own lip-sync audio sits from the window we sent (so the cut is
frame-exact against the master voice track, the only sound of the video).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List, Optional

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")


class MediaError(RuntimeError):
    pass


def _run(args: List[str], timeout: float = 300.0) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise MediaError(f"{os.path.basename(args[0])}: {type(e).__name__}") from e
    return p


def probe(path: str) -> Dict[str, float]:
    """{"duration", "width", "height", "fps", "audio": 0/1, "video": 0/1} of a media file (zeros when unreadable)."""
    out = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "audio": 0, "video": 0}
    if not path or not os.path.isfile(path):
        return out
    p = _run([FFPROBE, "-v", "error", "-show_entries",
              "format=duration:stream=codec_type,width,height,avg_frame_rate", "-of", "json", path], timeout=60)
    try:
        data = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        return out
    try:
        out["duration"] = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        pass
    for s in data.get("streams") or []:
        if s.get("codec_type") == "video" and not out["video"]:
            out["video"] = 1
            out["width"], out["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
            num, _, den = str(s.get("avg_frame_rate") or "0/1").partition("/")
            try:
                out["fps"] = float(num) / float(den or 1) if float(den or 1) else 0.0
            except ValueError:
                pass
        elif s.get("codec_type") == "audio":
            out["audio"] = 1
    return out


def duration(path: str) -> float:
    return float(probe(path)["duration"])


def to_wav(src: str, out: str, rate: int = 24000) -> str:
    """The narration as mono PCM WAV (what the windows are cut from)."""
    p = _run([FFMPEG, "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", out], 600)
    if p.returncode != 0 or not os.path.isfile(out):
        raise MediaError(f"narration not decodable: {p.stderr.decode('utf-8', 'replace')[-200:]}")
    return out


def cut_window(src_wav: str, start: float, end: float, out: str, *, pad_before: float, pad_after: float,
               total: float, rate: int = 24000) -> Dict[str, float]:
    """
    The voice from `start - pad_before` to `end + pad_after` as its own WAV. A
    window that reaches past the narration's start or end is padded with
    silence instead, so the clip's time `lead` (= pad_before) is always the
    scene's first frame. Returns {"path", "from", "to", "lead", "seconds"}.
    """
    want_a, want_b = start - pad_before, end + pad_after
    a, b = max(0.0, want_a), min(float(total), want_b)
    if b - a < 0.2:
        raise MediaError(f"window {start:.2f}-{end:.2f} s is empty")
    pre_ms = int(round(max(0.0, a - want_a) * 1000))
    post = max(0.0, want_b - b)
    chain = []
    if pre_ms > 0:
        chain.append(f"adelay={pre_ms}:all=1")
    if post > 0.001:
        chain.append(f"apad=pad_dur={post:.3f}")
    args = [FFMPEG, "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src_wav]
    if chain:
        args += ["-af", ",".join(chain)]
    args += ["-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", out]
    p = _run(args, 120)
    if p.returncode != 0 or not os.path.isfile(out):
        raise MediaError(f"window not cut: {p.stderr.decode('utf-8', 'replace')[-200:]}")
    return {"path": out, "from": round(want_a, 3), "to": round(want_b, 3), "lead": round(pad_before, 3),
            "seconds": round(want_b - want_a, 3)}


def trim(src: str, out: str, offset: float, seconds: float, *, mute: bool = True, crf: int = 17,
         max_width: int = 1920) -> str:
    """`seconds` of `src` from `offset` (frame-exact: re-encoded), sound removed, at most `max_width` wide."""
    args = [FFMPEG, "-v", "error", "-y", "-ss", f"{max(0.0, offset):.3f}", "-i", src, "-t", f"{seconds:.3f}",
            "-map", "0:v:0", "-vf", f"scale='min({max_width},iw)':-2:flags=lanczos,setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"]
    if mute:
        args.append("-an")
    else:
        args += ["-map", "0:a?", "-c:a", "aac", "-b:a", "160k"]
    args.append(out)
    p = _run(args, 600)
    if p.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) < 2000:
        raise MediaError(f"clip not trimmed: {p.stderr.decode('utf-8', 'replace')[-240:]}")
    return out


def frames(path: str, times: List[float], out_dir: str, stem: str, width: int = 640) -> List[str]:
    """JPEG frames of a clip at `times` (seconds; clamped inside the clip). Missing ones are left out."""
    os.makedirs(out_dir, exist_ok=True)
    dur = duration(path)
    got = []
    for i, t in enumerate(times):
        t = max(0.0, min(float(t), max(0.0, dur - 0.08)))
        out = os.path.join(out_dir, f"{stem}_{i}.jpg")
        p = _run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                  "-vf", f"scale={width}:-2", "-q:v", "3", out], 60)
        if p.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 500:
            got.append(out)
    return got


_FREEZE = re.compile(r"freeze_duration:\s*([\d.]+)")
_BLACK = re.compile(r"black_duration:\s*([\d.]+)")


def freeze_black(path: str, freeze_min: float = 1.2, black_min: float = 0.4) -> Dict[str, float]:
    """Seconds of frozen picture (frames that do not change) and of black picture in a clip."""
    p = _run([FFMPEG, "-v", "info", "-i", path, "-vf",
              f"freezedetect=n=-60dB:d={freeze_min},blackdetect=d={black_min}:pix_th=0.08",
              "-an", "-f", "null", "-"], 300)
    err = p.stderr.decode("utf-8", "replace")
    return {"frozen": round(sum(float(x) for x in _FREEZE.findall(err)), 2),
            "black": round(sum(float(x) for x in _BLACK.findall(err)), 2)}


def _pcm(path: str, rate: int, seconds: float) -> Optional["object"]:
    import numpy as np
    p = _run([FFMPEG, "-v", "error", "-i", path, "-t", f"{seconds:.2f}", "-map", "0:a:0", "-ac", "1",
              "-ar", str(rate), "-f", "f32le", "-"], 120)
    if p.returncode != 0 or not p.stdout:
        return None
    return np.frombuffer(p.stdout, dtype=np.float32)


def audio_lag(clip: str, ref_wav: str, max_lag: float = 0.6, rate: int = 16000) -> Optional[float]:
    """
    How much later (seconds, + = later) the speech in `clip`'s own audio sits
    than in `ref_wav`, from the cross-correlation of their loudness envelopes
    (10 ms steps). None when the clip has no audio or the match is too weak to trust.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    ref_s = duration(ref_wav)
    a = _pcm(ref_wav, rate, ref_s + 1.0)
    b = _pcm(clip, rate, ref_s + 1.0)
    if a is None or b is None or len(a) < rate or len(b) < rate:
        return None
    hop = rate // 100

    def env(x):
        n = len(x) // hop
        e = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
        e = np.log(e + 1e-4)
        return (e - e.mean()) / (e.std() + 1e-9)

    ea, eb = env(a), env(b)
    n = min(len(ea), len(eb))
    ea, eb = ea[:n], eb[:n]
    k = int(max_lag * 100)
    best, best_lag = -1e9, 0
    for lag in range(-k, k + 1):
        if lag >= 0:
            x, y = ea[: n - lag], eb[lag:]
        else:
            x, y = ea[-lag:], eb[: n + lag]
        if len(x) < 50:
            continue
        c = float(np.dot(x, y) / len(x))
        if c > best:
            best, best_lag = c, lag
    if best < 0.35:
        return None
    return round(best_lag / 100.0, 3)


def still_size(path: str) -> tuple:
    """(width, height) of a picture that decodes; raises MediaError otherwise."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            return im.size
    except Exception as e:  # noqa: BLE001 - any decode failure is "not a picture"
        raise MediaError(f"picture does not decode: {type(e).__name__}") from e


def to_jpeg(src: str, out: str, *, width: int = 0, height: int = 0, quality: int = 92) -> str:
    """A picture as an RGB JPEG; with width and height, centre-cropped to that aspect and resized to them."""
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        if width and height:
            w, h = im.size
            want = width / height
            if abs(w / h - want) > 0.01:
                if w / h > want:
                    nw = int(round(h * want))
                    im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
                else:
                    nh = int(round(w / want))
                    im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
            if im.size != (width, height):
                im = im.resize((width, height), Image.LANCZOS)
        elif width and im.size[0] > width:
            im = im.resize((width, int(round(im.size[1] * width / im.size[0]))), Image.LANCZOS)
        im.save(out, "JPEG", quality=quality, optimize=True)
    return out


def sheet(paths: List[str], out: str, height: int = 360) -> str:
    """Pictures side by side in one JPEG (a vision check's contact strip)."""
    from PIL import Image
    ims = []
    for p in paths:
        with Image.open(p) as im:
            im = im.convert("RGB")
            ims.append(im.resize((max(1, int(im.size[0] * height / im.size[1])), height), Image.LANCZOS))
    if not ims:
        raise MediaError("no frames for the sheet")
    w = sum(i.size[0] for i in ims) + 8 * (len(ims) - 1)
    canvas = Image.new("RGB", (w, height), (0, 0, 0))
    x = 0
    for im in ims:
        canvas.paste(im, (x, 0))
        x += im.size[0] + 8
    canvas.save(out, "JPEG", quality=88)
    return out
