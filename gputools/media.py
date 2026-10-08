"""
ffmpeg / ffprobe around the engines: probe a clip, decode it to RGB frames, encode frames back to an H.264 MP4
(with the source's sound), and the audio steps of the music bed (loudness, fades, MP3). No torch here.

Colour: frames are decoded with the source's own matrix (its tag; untagged = BT.601 under 720 lines, else
BT.709) and every output is written and tagged BT.709, limited range - an upscaled SD clip keeps its colours
next to the HD footage.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, Iterator, Optional

import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
# x264 preset of every output: the GPU waits while the CPU encodes ("medium" took 18 s for an 8 s 1080p clip on
# the A40 pod's 7.6 vCPUs, half the GPU time); "veryfast" at CRF 17 is ~3x faster for a slightly bigger file.
PRESET = os.environ.get("GPUTOOLS_X264_PRESET", "veryfast")
_NVENC: Dict[str, bool] = {}


def nvenc_ok() -> bool:
    """The GPU's H.264 encoder works here (checked once: ffmpeg built with it and the driver's libnvidia-encode
    mounted - RunPod mounts it even with NVIDIA_DRIVER_CAPABILITIES=compute,utility). GPUTOOLS_NVENC=0 turns it
    off (x264 then)."""
    if "ok" not in _NVENC:
        ok = False
        if os.environ.get("GPUTOOLS_NVENC", "1") != "0":
            try:
                p = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
                                    "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=60)
                ok = p.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        _NVENC["ok"] = ok
    return _NVENC["ok"]
_MATRIX = {"bt709": "bt709", "bt470bg": "bt601", "smpte170m": "bt601", "bt601": "bt601",
           "bt2020nc": "bt2020", "bt2020c": "bt2020", "fcc": "fcc", "smpte240m": "smpte240m"}


def _ratio(s: str, default: float = 0.0) -> float:
    try:
        a, _, b = str(s or "").partition("/")
        return float(a) / float(b or 1) if float(b or 1) else default
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def probe(path: str) -> Dict:
    """{w, h, fps, frames, seconds, audio, matrix, range, rotation} of a media file."""
    # -show_streams / -show_format (not -show_entries): the side-data section is named differently across ffprobe
    # versions, and an unknown name fails the whole query (ffprobe 4.4 printed nothing at all).
    p = subprocess.run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(p.stdout or "{}")
    except ValueError:
        d = {}
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
    fps = _ratio(v.get("avg_frame_rate")) or _ratio(v.get("r_frame_rate")) or 30.0
    seconds = float(v.get("duration") or (d.get("format") or {}).get("duration") or 0.0)
    try:
        frames = int(v.get("nb_frames") or 0)
    except (TypeError, ValueError):
        frames = 0
    if frames <= 0 and seconds > 0:
        frames = int(round(seconds * fps))
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = rot or int(float((v.get("tags") or {}).get("rotate") or 0))
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {"w": w, "h": h, "fps": round(fps, 4), "frames": frames, "seconds": round(seconds, 3), "audio": a,
            "matrix": _MATRIX.get(str(v.get("color_space") or ""), ""), "range": str(v.get("color_range") or ""),
            "rotation": rot}


def in_matrix(info: Dict) -> str:
    return info.get("matrix") or ("bt601" if min(info.get("w") or 0, info.get("h") or 0) < 720 else "bt709")


def decode(path: str, info: Dict, start: float = 0.0, seconds: float = 0.0, size=None) -> Iterator[np.ndarray]:
    """The clip's frames as HxWx3 uint8 RGB at its own average frame rate (constant: a variable-rate upload is
    evened out, a constant one comes through frame for frame), optionally scaled to `size` (w, h) with Lanczos."""
    w, h = (size or (info["w"], info["h"]))
    if int(w or 0) <= 0 or int(h or 0) <= 0:
        raise ValueError(f"no picture size to decode {os.path.basename(path)} at")
    rng = "full" if info.get("range") in ("pc", "jpeg", "full") else "tv"
    # Same size: only the YUV -> RGB conversion (bilinear chroma; Lanczos cost the RIFE path ~0.7 s per clip second
    # on the CPU while the GPU waited). Another size: Lanczos.
    same = (int(w), int(h)) == (int(info["w"]), int(info["h"]))
    flags = "bilinear" if same else "lanczos+accurate_rnd"
    vf = (f"fps=fps={float(info.get('fps') or 30.0):.6f},"
          f"scale={w}:{h}:flags={flags}:in_color_matrix={in_matrix(info)}:in_range={rng},"
          f"format=rgb24")
    cmd = [FFMPEG, "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if seconds > 0:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-map", "0:v:0", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=w * h * 3 * 4)
    size_b = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size_b)
            if len(buf) < size_b:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait(timeout=60)


class Encoder:
    """RGB frames in -> H.264 MP4 out (yuv420p, BT.709 tagged), the source's sound copied in when asked."""

    def __init__(self, out_path: str, w: int, h: int, fps: float, crf: int = 17, preset: str = PRESET,
                 audio_from: str = "", audio_start: float = 0.0, audio_seconds: float = 0.0,
                 video_seconds: float = 0.0):
        """`video_seconds`: the picture's length (frames / fps) - the sound is padded or cut to it, so a clip
        never loses a frame to a shorter sound track."""
        self.out_path, self.w, self.h = out_path, int(w), int(h)
        self.tmp = out_path + ".part.mp4"
        cmd = [FFMPEG, "-v", "error", "-y", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{self.w}x{self.h}", "-r", f"{fps:.6f}", "-i", "-"]
        if audio_from:
            if audio_start > 0:
                cmd += ["-ss", f"{audio_start:.3f}"]
            if audio_seconds > 0:
                cmd += ["-t", f"{audio_seconds:.3f}"]
            cmd += ["-i", audio_from, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "160k", "-af", "apad"]
            if video_seconds > 0:
                cmd += ["-t", f"{video_seconds:.3f}"]
        if nvenc_ok():
            # The GPU's own encoder: the CPU (a few vCPUs on a serverless GPU worker) no longer paces the job.
            # CQ a little above the x264 CRF: an intermediate the renderer encodes again (at CQ 18 / 60 M the test
            # clips came out ~3x x264's size - slower to hand back through R2).
            codec = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(int(crf) + 3),
                     "-b:v", "0", "-maxrate", "30M", "-bufsize", "60M"]
        else:
            codec = ["-c:v", "libx264", "-preset", preset, "-crf", str(int(crf))]
        cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", *codec,
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                "-movflags", "+faststart", self.tmp]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.frames = 0

    def write(self, rgb: np.ndarray) -> None:
        if rgb.shape[0] != self.h or rgb.shape[1] != self.w:
            raise ValueError(f"frame {rgb.shape[1]}x{rgb.shape[0]} != {self.w}x{self.h}")
        self.proc.stdin.write(np.ascontiguousarray(rgb, dtype=np.uint8).tobytes())
        self.frames += 1

    def close(self) -> str:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
        rc = self.proc.wait(timeout=600)
        if rc != 0 or not os.path.isfile(self.tmp) or os.path.getsize(self.tmp) < 2000:
            raise RuntimeError(f"encode failed ({rc}): {err[-300:]}")
        os.replace(self.tmp, self.out_path)
        return self.out_path

    def abort(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass
        try:
            os.remove(self.tmp)
        except OSError:
            pass


# ------------------------------------------------------------------ audio (the music bed)
def loudness(path: str, pre: str = "", target: float = -27.0) -> Dict[str, float]:
    """EBU R128 integrated loudness / true peak / LRA of an audio file after the filters `pre` (ffmpeg loudnorm,
    measure only)."""
    af = (pre + "," if pre else "") + f"loudnorm=I={target:.1f}:TP=-2:LRA=11:print_format=json"
    p = subprocess.run([FFMPEG, "-v", "info", "-nostdin", "-i", path, "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr or "", re.S)
    if not m:
        raise RuntimeError("loudness measure failed: " + (p.stderr or "")[-200:])
    d = json.loads(m.group(0))
    return {k: float(d[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def finish_music(src: str, out_mp3: str, seconds: float, lufs: float, fade_in: float, fade_out: float,
                 carve_db: float = 0.0) -> Dict:
    """The generated bed cut to `seconds`, faded in and out, the narration's band carved by `carve_db` (a wide
    dip at 2.2 kHz: the music makes room for the voice, as an editor's EQ would), brought to `lufs` integrated
    (two-pass loudnorm on exactly that, linear: no pumping) under a -2 dBTP ceiling, as a 192 kb/s 44.1 kHz
    stereo MP3."""
    fo_start = max(0.0, seconds - fade_out)
    pre = (f"atrim=0:{seconds:.3f},asetpts=PTS-STARTPTS,"
           f"afade=t=in:st=0:d={fade_in:.2f},afade=t=out:st={fo_start:.3f}:d={fade_out:.2f}")
    if carve_db > 0:
        pre += f",equalizer=f=2200:t=q:w=0.8:g={-abs(carve_db):.1f}"
    m = loudness(src, pre, lufs)
    chain = (pre + ","
             f"loudnorm=I={lufs:.1f}:TP=-2:LRA=11:measured_I={m['input_i']:.2f}:measured_TP={m['input_tp']:.2f}:"
             f"measured_LRA={m['input_lra']:.2f}:measured_thresh={m['input_thresh']:.2f}:"
             f"offset={m['target_offset']:.2f}:linear=true,aresample=44100")
    tmp = out_mp3 + ".part.mp3"
    p = subprocess.run([FFMPEG, "-v", "error", "-y", "-nostdin", "-i", src, "-af", chain, "-ac", "2",
                        "-c:a", "libmp3lame", "-b:a", "192k", tmp], capture_output=True, text=True, timeout=600)
    if p.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("music finish failed: " + (p.stderr or "")[-300:])
    os.replace(tmp, out_mp3)
    after = loudness(out_mp3)
    return {"lufs": round(after["input_i"], 1), "true_peak": round(after["input_tp"], 1),
            "lra": round(after["input_lra"], 1), "raw_lufs": round(m["input_i"], 1)}


def music_end(path: str, below_peak_db: float = 40.0) -> float:
    """Where the music really ends: the last 50 ms window within `below_peak_db` of the loudest one (+0.5 s).
    ACE-Step writes a whole piece into the length it is given - an ending, then ~5-7 s of near silence at
    70 s - and a bed must not go quiet under the last lines."""
    p = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-i", path, "-f", "f32le", "-ac", "1", "-ar", "8000", "-"],
                       capture_output=True, timeout=300)
    x = np.frombuffer(p.stdout, np.float32)
    if x.size < 800:
        return 0.0
    win = 400                                                  # 50 ms at 8 kHz
    n = x.size // win
    rms = np.sqrt(np.mean(x[:n * win].reshape(n, win) ** 2, axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    loud = np.nonzero(db > db.max() - below_peak_db)[0]
    if loud.size == 0:
        return 0.0
    return min(x.size / 8000.0, (loud[-1] + 1) * win / 8000.0 + 0.5)


def duration(path: str) -> float:
    p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=60)
    try:
        return float((p.stdout or "0").strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0.0


def first_frame(path: str, out_jpg: str, at: float = 1.0) -> Optional[str]:
    p = subprocess.run([FFMPEG, "-v", "error", "-y", "-nostdin", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
                        "-q:v", "3", out_jpg], capture_output=True, timeout=60)
    return out_jpg if p.returncode == 0 and os.path.isfile(out_jpg) else None
