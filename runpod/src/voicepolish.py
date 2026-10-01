"""
Narration polish: the voice-over cleaned once, before the render.

Creators record on whatever they have: a laptop mic in a kitchen, a USB mic
under a fan. A documentary voice is dry, steady and quiet between words. This
module measures the narration and fixes only what it finds, with ffmpeg:

  * rumble / hum   - a 70 Hz high-pass (2 poles), when there is energy under
                     the voice (a desk, traffic, mains hum in the pauses);
  * room noise     - afftdn (FFT denoise) at a strength set by how far the
                     noise floor sits under the voice, only when it is close
                     enough to hear: a clean recording (the floor 38 dB or
                     more under the voice, or too few pauses to measure it)
                     is never denoised;
  * harsh esses    - a split-band de-esser (only the band above 5 kHz is
                     compressed, and only on its loud moments), when the
                     sibilant frames are hot against the voice's body;
  * peaks          - gentle 2.5:1 compression of the loudest syllables only
                     (threshold 9 dB over the voice's loudness), when the
                     peaks stand far over the voice;
  * level drift    - a slow leveller (dynaudnorm, 15 s window), when the
                     voice wanders in level across the video (a loudness
                     range over 7.5 LU).

The cleaned narration keeps the original's integrated loudness (a final
gain matches it to 0.1 dB, never over -0.5 dBFS true peak), its sample rate,
channels and length: every sound and the music were levelled against the
measured voice (meta.voiceLufs) and every cut against its word timings, so
neither may move. None of the filters adds latency; the result is checked
for it (the cleaned and original signals line up within 1 ms), for its
length, loudness and peaks. Any failure, a timeout or a check that does not
pass keeps the original narration: the polish can only skip, never break a
render. The result is lossless FLAC beside the job's other files; the render
reads it like any local file (a split render publishes it with the scenes).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from . import config

# Bumped when the chain changes, so a report says which chain made a file.
VERSION = 1

ANALYSIS_RATE = 24000          # Hz: the analysis decode (the sibilance band reaches 10 kHz)
FRAME = 1024                   # samples per analysis frame, ~43 ms at 24 kHz
SILENT_DB = -95.0              # a frame this quiet is digital silence, not room noise
MIN_FRAMES = 200               # under ~9 s of audio nothing is decided

# The bands (Hz) the analysis compares.
LF_BAND = (20.0, 70.0)         # rumble, handling noise, mains hum
CORE_BAND = (300.0, 3000.0)    # the body of the voice
SIB_BAND = (4500.0, 10000.0)   # esses

# Decisions (dB unless noted). A recording is clean when its noise floor sits
# CLEAN_SNR_DB or more under its loudness (ACX, the audiobook standard: a
# floor of -60 dB under speech at -18 to -23 dB RMS, i.e. about 37-42 dB).
CLEAN_SNR_DB = 38.0
FLOOR_MIN_DB = -72.0           # a floor under this is inaudible whatever the voice level
FLOOR_CLUSTER_DB = 6.0         # pauses: p15 within this of p5 among the non-silent frames
# Under 70 Hz a voice only leaks (the Lake Powell narration: -31 dB against
# its body); a desk, traffic or handling noise brings it within 20 dB.
RUMBLE_DB = -20.0
# Mains hum: a 50 or 60 Hz line (or its harmonics) standing this far over the
# noise around it in the pauses.
HUM_PROMINENCE_DB = 10.0
# The loudest esses (p95 of the sibilant band against the voice's body in the
# speech frames): natural speech sits near -4 dB (Lake Powell -3.6), a voice
# with a harsh 7 kHz presence (+9 dB) near +19.
SIBILANCE_DB = 6.0
PEAK_PLR_DB = 15.0             # true peak this far over the loudness: tame the peaks
LEVEL_LRA_LU = 7.5             # loudness range over this: level the drift

HIGHPASS_HZ = 70.0
DEESS_SPLIT_HZ = 5000.0
COMPRESS_OVER_DB = 9.0         # compression starts this far over the integrated loudness
COMPRESS_RATIO = 2.5
TRUE_PEAK_MAX = -0.5           # dBFS, after the final gain
LOUDNESS_TOLERANCE = 0.5       # LU between the original and the cleaned narration
ALIGN_TOLERANCE_S = 0.001      # seconds of lag allowed between them

_FFMPEG = "ffmpeg"


# --------------------------------------------------------------------------- #
# Measuring
# --------------------------------------------------------------------------- #

def _run(argv: List[str], timeout: float, binary: bool = False) -> subprocess.CompletedProcess:
    if binary:
        return subprocess.run(argv, capture_output=True, timeout=timeout)
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def probe(path: str, timeout: float = 60) -> Dict[str, Any]:
    """{"rate", "channels", "seconds", "codec"} of the first audio stream, {} when unreadable."""
    try:
        p = _run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                  "stream=sample_rate,channels,codec_name:format=duration", "-of", "json", path], timeout)
        data = json.loads(p.stdout or "{}")
        st = (data.get("streams") or [{}])[0]
        return {"rate": int(st.get("sample_rate") or 0), "channels": int(st.get("channels") or 0),
                "codec": str(st.get("codec_name") or ""),
                "seconds": float((data.get("format") or {}).get("duration") or 0.0)}
    except (OSError, ValueError, subprocess.TimeoutExpired, IndexError, TypeError):
        return {}


_I = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
_LRA = re.compile(r"LRA:\s*(-?\d+(?:\.\d+)?)\s*LU\b")
_PEAK = re.compile(r"Peak:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dBFS")


def loudness(path: str, timeout: float = 300) -> Dict[str, Optional[float]]:
    """{"lufs", "lra", "tp"}: integrated loudness, loudness range and true peak (ffmpeg ebur128)."""
    out: Dict[str, Optional[float]] = {"lufs": None, "lra": None, "tp": None}
    for af in ("ebur128=framelog=quiet:peak=true", "ebur128=peak=true"):
        try:
            p = _run([_FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", af, "-f", "null", "-"],
                     timeout)
        except (OSError, subprocess.TimeoutExpired):
            return out
        err = p.stderr or ""
        if "Summary" not in err:
            continue
        summary = err[err.rfind("Summary"):]
        for key, rx in (("lufs", _I), ("lra", _LRA), ("tp", _PEAK)):
            m = rx.search(summary)
            if m:
                v = float(m.group(1)) if m.group(1) != "-inf" else -200.0
                out[key] = v if math.isfinite(v) else None
        return out
    return out


def _frames(path: str, timeout: float):
    """The narration as mono 24 kHz analysis frames: yields float arrays of FRAME samples."""
    import numpy as np
    proc = subprocess.Popen([_FFMPEG, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(ANALYSIS_RATE),
                             "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    block = FRAME * 2 * 256
    rest = b""
    try:
        while True:
            chunk = proc.stdout.read(block)
            if not chunk:
                break
            if time.time() > deadline:
                raise TimeoutError("narration analysis took too long")
            data = rest + chunk
            usable = len(data) - len(data) % (FRAME * 2)
            rest = data[usable:]
            if usable:
                yield np.frombuffer(data[:usable], dtype="<i2").astype(np.float32).reshape(-1, FRAME) / 32768.0
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def frame_stats(path: str, timeout: float = 300) -> Optional[Dict[str, Any]]:
    """
    Per-frame level and band energies of the narration: {"rms", "lf", "core",
    "sib", "full"} as numpy arrays (dB), or None when numpy or the decode is
    not available.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    window = np.hanning(FRAME).astype(np.float32)
    freqs = np.fft.rfftfreq(FRAME, 1.0 / ANALYSIS_RATE)

    def band(lo, hi):
        return (freqs >= lo) & (freqs < hi)
    lf, core, sib = band(*LF_BAND), band(*CORE_BAND), band(*SIB_BAND)
    full = band(20.0, ANALYSIS_RATE / 2.0)
    parts: Dict[str, list] = {"rms": [], "lf": [], "core": [], "sib": [], "full": []}
    tiny = 1e-20
    try:
        for frames in _frames(path, timeout):
            parts["rms"].append(10.0 * np.log10(np.mean(frames ** 2, axis=1) + tiny))
            power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
            for key, sel in (("lf", lf), ("core", core), ("sib", sib), ("full", full)):
                parts[key].append(10.0 * np.log10(power[:, sel].sum(axis=1) + tiny))
    except (OSError, TimeoutError, ValueError):
        return None
    if not parts["rms"]:
        return None
    return {k: np.concatenate(v) for k, v in parts.items()}


def analyze(path: str, timeout: float = 300) -> Optional[Dict[str, Any]]:
    """
    What the narration needs: its loudness, noise floor and the signs of
    rumble, hum and harsh esses (see the module notes). None when it cannot
    be measured (the polish is then skipped).
    """
    import numpy as np
    info = probe(path)
    if not info.get("rate") or not info.get("channels"):
        return None
    loud = loudness(path, timeout)
    if loud.get("lufs") is None or loud["lufs"] < -60:
        return None
    fs = frame_stats(path, timeout)
    if fs is None or len(fs["rms"]) < MIN_FRAMES:
        return None
    rms = fs["rms"]
    lufs = float(loud["lufs"])
    live = rms > SILENT_DB
    stats: Dict[str, Any] = {"rate": info["rate"], "channels": info["channels"], "seconds": round(info["seconds"], 3),
                             "lufs": round(lufs, 2), "lra": loud.get("lra"), "tp": loud.get("tp")}
    floor = None
    reliable = False
    if live.sum() >= MIN_FRAMES:
        lows = rms[live]
        p5, p15 = float(np.percentile(lows, 5)), float(np.percentile(lows, 15))
        floor = p5
        # Pauses are a tight cluster of equally quiet frames; without them the
        # quietest frames are soft speech and say nothing about the room.
        reliable = (p15 - p5) <= FLOOR_CLUSTER_DB
        stats["floorSpread"] = round(p15 - p5, 1)
    stats["noiseFloor"] = round(floor, 1) if floor is not None else None
    stats["floorReliable"] = bool(reliable)
    stats["snr"] = round(lufs - floor, 1) if floor is not None else None
    stats["silentShare"] = round(float(1.0 - live.mean()), 3)
    speech = rms > lufs - 10.0
    if speech.sum() >= 20:
        stats["rumble"] = round(float(np.median(fs["lf"][speech] - fs["core"][speech])), 1)
        ratio = fs["sib"][speech] - fs["core"][speech]
        stats["sibilance"] = round(float(np.percentile(ratio, 95)), 1)
        stats["sibilantShare"] = round(float((ratio > 0).mean()), 3)
    else:
        stats["rumble"] = stats["sibilance"] = stats["sibilantShare"] = None
    if floor is not None and reliable:
        quiet = live & (rms <= floor + 6.0)
        if quiet.sum() >= 10:
            stats["hum"] = round(float(np.median(fs["lf"][quiet] - fs["full"][quiet])), 1)
    stats.setdefault("hum", None)
    return stats


# --------------------------------------------------------------------------- #
# Deciding
# --------------------------------------------------------------------------- #

def _lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def plan(stats: Dict[str, Any]) -> Dict[str, Any]:
    """
    The steps this narration gets, each with its reason, and the ffmpeg
    filter chain: {"steps": [{"step", "why", ...}], "filter": str, "skipped": {step: why}}.
    """
    steps: List[Dict[str, Any]] = []
    skipped: Dict[str, str] = {}
    filters: List[str] = []
    lufs = float(stats["lufs"])

    rumble, hum = stats.get("rumble"), stats.get("humProminence")
    if (rumble is not None and rumble > RUMBLE_DB) or (hum is not None and hum > HUM_PROMINENCE_DB
                                                         and (stats.get("noiseFloor") or -200) > FLOOR_MIN_DB):
        why = (f"energy under {int(LF_BAND[1])} Hz {rumble:.0f} dB against the voice" if rumble is not None
               and rumble > RUMBLE_DB else f"mains hum in the pauses ({hum:.0f} dB over the room)")
        steps.append({"step": "highpass", "why": why, "hz": HIGHPASS_HZ})
        filters.append(f"highpass=f={HIGHPASS_HZ:g}")
    else:
        skipped["highpass"] = "no rumble or hum"

    floor, snr = stats.get("noiseFloor"), stats.get("snr")
    if not stats.get("floorReliable") or floor is None:
        skipped["denoise"] = "too few pauses to measure the room (left as recorded)"
    elif floor <= FLOOR_MIN_DB or snr >= CLEAN_SNR_DB:
        skipped["denoise"] = f"clean: noise floor {floor:.0f} dBFS, {snr:.0f} dB under the voice"
    else:
        # The closer the noise, the more it is taken down: 8 dB at the edge of
        # clean, up to 18 dB for a floor only 20 dB under the voice.
        nr = max(6.0, min(18.0, 8.0 + (CLEAN_SNR_DB - snr) * 0.6))
        nf = max(-80.0, min(-20.0, floor))
        steps.append({"step": "denoise", "why": f"noise floor {floor:.0f} dBFS, only {snr:.0f} dB under the voice",
                      "reduction": round(nr, 1), "floor": round(nf, 1)})
        filters.append(f"afftdn=nr={nr:.1f}:nf={nf:.1f}:tn=1")

    sib = stats.get("sibilance")
    if sib is not None and sib > SIBILANCE_DB:
        # The high band is compressed above the level its loudest esses reach
        # minus a few dB: ordinary consonants pass, a hissing 's' comes down.
        over = sib - SIBILANCE_DB
        ratio = max(2.0, min(5.0, 2.0 + over * 0.4))
        steps.append({"step": "deess", "why": f"esses {sib:+.0f} dB against the voice's body", "ratio": round(ratio, 1)})
        filters.append("__DEESS__")
        stats = dict(stats, _deess_ratio=ratio)
    else:
        skipped["deess"] = "esses in proportion" if sib is not None else "not measured"

    tp, lra = stats.get("tp"), stats.get("lra")
    if tp is not None and tp - lufs > PEAK_PLR_DB:
        thr = min(0.9, _lin(lufs + COMPRESS_OVER_DB))
        steps.append({"step": "compress", "why": f"peaks {tp - lufs:.0f} dB over the voice", "ratio": COMPRESS_RATIO,
                      "thresholdDb": round(lufs + COMPRESS_OVER_DB, 1)})
        filters.append(f"acompressor=threshold={thr:.6f}:ratio={COMPRESS_RATIO:g}:attack=8:release=150:knee=2.5:makeup=1")
    else:
        skipped["compress"] = "peaks in proportion" if tp is not None else "not measured"

    if lra is not None and lra > LEVEL_LRA_LU:
        steps.append({"step": "level", "why": f"level wanders {lra:.1f} LU across the narration"})
        filters.append("dynaudnorm=f=500:g=31:p=0.9:m=4:r=0:c=0:b=0:s=0")
    else:
        skipped["level"] = f"steady ({lra:.1f} LU)" if lra is not None else "not measured"

    return {"steps": steps, "skipped": skipped, "chain": filters, "stats": stats}


def _graph(chain: List[str], stats: Dict[str, Any]) -> Tuple[str, str]:
    """The ffmpeg -filter_complex graph for a planned chain (the de-esser is a split-band one)."""
    parts: List[str] = []
    label = "0:a"
    n = 0
    for f in chain:
        n += 1
        out = f"p{n}"
        if f == "__DEESS__":
            ratio = float(stats.get("_deess_ratio") or 3.0)
            # Its loudest esses reach about lufs + sibilance (dB) in the band;
            # the compressor starts 6 dB under that.
            thr = min(0.5, _lin(float(stats["lufs"]) + float(stats.get("sibilance") or 0.0) - 6.0))
            parts.append(f"[{label}]acrossover=split={DEESS_SPLIT_HZ:g}[lo{n}][hi{n}]")
            parts.append(f"[hi{n}]acompressor=threshold={thr:.6f}:ratio={ratio:.2f}:attack=1:release=60:"
                         f"knee=2:makeup=1[hc{n}]")
            # amix halves two inputs; the volume puts the bands back at unity.
            parts.append(f"[lo{n}][hc{n}]amix=inputs=2:duration=first:dropout_transition=0,volume=2[{out}]")
        else:
            parts.append(f"[{label}]{f}[{out}]")
        label = out
    return ";".join(parts), label


# --------------------------------------------------------------------------- #
# Doing
# --------------------------------------------------------------------------- #

def _ffmpeg_ok(argv: List[str], timeout: float) -> Tuple[bool, str]:
    try:
        p = _run(argv, timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, type(e).__name__
    return p.returncode == 0, (p.stderr or "")[-300:]


def alignment(a: str, b: str, timeout: float = 120) -> Optional[float]:
    """
    The lag (seconds) of `b` against `a`, the worst of three 4-second windows
    (cross-correlation within +-50 ms); None when it cannot be measured.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    seconds = probe(a).get("seconds") or 0.0
    if seconds < 6.0:
        return None
    worst = 0.0
    found = False
    for frac in (0.2, 0.5, 0.8):
        start = max(0.0, seconds * frac - 2.0)
        sigs = []
        for path in (a, b):
            try:
                p = _run([_FFMPEG, "-v", "error", "-ss", f"{start:.3f}", "-i", path, "-t", "4", "-ac", "1",
                          "-ar", str(ANALYSIS_RATE), "-f", "f32le", "-"], timeout, binary=True)
            except (OSError, subprocess.TimeoutExpired):
                return None
            sigs.append(np.frombuffer(p.stdout, dtype="<f4"))
        n = min(len(sigs[0]), len(sigs[1]))
        if n < ANALYSIS_RATE:
            continue
        x, y = sigs[0][:n], sigs[1][:n]
        if float(np.sqrt(np.mean(x ** 2))) < 1e-4:
            continue                                    # a pause: nothing to line up
        size = 1 << int(math.ceil(math.log2(2 * n)))
        corr = np.fft.irfft(np.fft.rfft(y, size) * np.conj(np.fft.rfft(x, size)), size)
        span = int(0.05 * ANALYSIS_RATE)
        lags = np.concatenate([corr[-span:], corr[:span + 1]])
        lag = int(np.argmax(lags)) - span
        worst = max(worst, abs(lag) / ANALYSIS_RATE)
        found = True
    return worst if found else None


def polish(src: str, dst: str, *, stats: Optional[Dict[str, Any]] = None,
           timeout: Optional[float] = None) -> Dict[str, Any]:
    """
    Clean `src` into `dst` (FLAC). Returns the report: {"applied": bool, "steps",
    "skipped", "before", "after", "why"}; `dst` exists only when applied.
    """
    started = time.time()
    budget = float(timeout if timeout is not None else config.VOICE_POLISH_SECONDS)

    def left() -> float:
        return max(5.0, budget - (time.time() - started))
    report: Dict[str, Any] = {"applied": False, "version": VERSION}
    try:
        stats = stats or analyze(src, timeout=left())
    except Exception as e:  # noqa: BLE001 - measured or skipped
        report["why"] = f"not measured ({type(e).__name__})"
        return report
    if not stats:
        report["why"] = "the narration could not be measured"
        return report
    decided = plan(stats)
    report["before"] = {k: v for k, v in stats.items() if not k.startswith("_")}
    report["steps"] = decided["steps"]
    report["skipped"] = decided["skipped"]
    if not decided["chain"]:
        report["why"] = "nothing to fix"
        return report
    graph, last = _graph(decided["chain"], decided["stats"])
    tmp = dst + ".work.flac"
    for leftover in (tmp, dst):
        if os.path.exists(leftover):
            os.remove(leftover)
    fmt = ["-ar", str(stats["rate"]), "-ac", str(stats["channels"]), "-c:a", "flac", "-sample_fmt", "s16"]
    try:
        ok, err = _ffmpeg_ok([_FFMPEG, "-hide_banner", "-v", "error", "-y", "-i", src, "-filter_complex", graph,
                              "-map", f"[{last}]", *fmt, tmp], left())
        if not ok or not os.path.isfile(tmp):
            report["why"] = f"the filters failed: {err.strip()[-160:]}"
            return report
        mid = loudness(tmp, left())
        if mid.get("lufs") is None or mid.get("tp") is None:
            report["why"] = "the cleaned narration could not be measured"
            return report
        # The original's loudness back, never over the true-peak ceiling.
        gain = float(stats["lufs"]) - float(mid["lufs"])
        gain = min(gain, TRUE_PEAK_MAX - float(mid["tp"]))
        if abs(gain) >= 0.05:
            ok, err = _ffmpeg_ok([_FFMPEG, "-hide_banner", "-v", "error", "-y", "-i", tmp, "-af",
                                  f"volume={gain:.2f}dB", *fmt, dst], left())
            if not ok or not os.path.isfile(dst):
                report["why"] = f"the level match failed: {err.strip()[-160:]}"
                return report
        else:
            os.replace(tmp, dst)
        after = loudness(dst, left())
        report["gainDb"] = round(gain, 2)
        why = _verify(src, dst, stats, after, left())
        if why:
            report["why"] = why
            if os.path.exists(dst):
                os.remove(dst)
            return report
        try:
            post = analyze(dst, timeout=left()) or {}
        except Exception:  # noqa: BLE001 - only the report misses it
            post = {}
        report["after"] = {k: post.get(k, after.get(k)) for k in
                           ("lufs", "lra", "tp", "noiseFloor", "snr", "rumble", "sibilance", "hum")}
        report["applied"] = True
        report["why"] = ", ".join(s["step"] for s in decided["steps"])
        return report
    except Exception as e:  # noqa: BLE001 - the original narration stays
        report["why"] = f"failed ({type(e).__name__}: {str(e)[:120]})"
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        return report
    finally:
        report["seconds"] = round(time.time() - started, 1)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _verify(src: str, dst: str, stats: Dict[str, Any], after: Dict[str, Optional[float]], timeout: float) -> str:
    """'' when the cleaned narration can stand in for the original, else why not."""
    got = probe(dst)
    if not got.get("seconds"):
        return "the cleaned narration does not read back"
    if abs(got["seconds"] - float(stats["seconds"])) > 0.05:
        return f"the length changed ({stats['seconds']:.2f} s -> {got['seconds']:.2f} s)"
    if after.get("lufs") is None or abs(float(after["lufs"]) - float(stats["lufs"])) > LOUDNESS_TOLERANCE:
        return f"the loudness moved ({stats['lufs']} -> {after.get('lufs')} LUFS)"
    if after.get("tp") is not None and float(after["tp"]) > TRUE_PEAK_MAX + 0.3:
        return f"the peaks reach {after['tp']} dBFS"
    lag = alignment(src, dst, timeout)
    if lag is None:
        return "the timing could not be checked"
    if lag > ALIGN_TOLERANCE_S:
        return f"the voice moved {lag * 1000:.1f} ms"
    return ""


# --------------------------------------------------------------------------- #
# The render's narration
# --------------------------------------------------------------------------- #

def _source(doc: Dict[str, Any], work: str, inp: Optional[Dict[str, Any]]) -> str:
    """The narration as a file on this disk (downloaded once into `work`), or ''."""
    from . import storage, timeline
    url = str(((doc.get("audio") or {}) if isinstance(doc.get("audio"), dict) else {}).get("url") or "")
    if not url:
        return ""
    local = timeline.narration_file(url, inp or {})
    if local:
        return local
    if not url.startswith(("http://", "https://")):
        return ""
    ext = os.path.splitext(url.split("?", 1)[0])[1][:6] or ".audio"
    dest = os.path.join(work, f"narration.source{ext}")
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    return storage.download(url, dest, timeout=int(config.VOICE_POLISH_SECONDS))


def for_render(doc: Dict[str, Any], work: str, inp: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Before the render: the narration cleaned once and the document pointed at
    the cleaned copy (doc.audio.url, a file in `work`). The report lands in
    doc.meta.voicePolish. Off with VOICE_POLISH=0 or a document whose
    audio.polish is false. Never raises; any failure keeps the original.
    """
    report: Dict[str, Any] = {"applied": False, "version": VERSION}
    audio = doc.get("audio") if isinstance(doc.get("audio"), dict) else None
    if not config.VOICE_POLISH:
        report["why"] = "off (VOICE_POLISH=0)"
    elif audio is None or not audio.get("url"):
        report["why"] = "no narration"
    elif audio.get("polish") is False:
        report["why"] = "off for this video"
    elif not shutil.which(_FFMPEG):
        report["why"] = "ffmpeg is missing"
    else:
        try:
            src = _source(doc, work, inp)
        except Exception as e:  # noqa: BLE001 - the render reads the link itself
            src = ""
            report["why"] = f"the narration could not be fetched ({type(e).__name__})"
        if src:
            dst = os.path.join(work, "narration.polished.flac")
            report = polish(src, dst)
            if report.get("applied") and os.path.isfile(dst):
                audio["url"] = dst
        elif "why" not in report:
            report["why"] = "the narration is not a file or a link"
    if isinstance(doc.get("meta"), dict):
        doc["meta"]["voicePolish"] = report
    steps = ", ".join(s["step"] for s in report.get("steps") or []) or "none"
    print(f"[voice] polish {'applied' if report.get('applied') else 'skipped'} ({report.get('why', '')}); "
          f"steps: {steps}", flush=True)
    return report
