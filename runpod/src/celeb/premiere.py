"""
"Export to Premiere": the celeb edit as a Final Cut Pro 7 XML (xmeml v4), which Premiere Pro imports
(File > Import) into an editable sequence.
  V1  every picture shot as its own clip (conformed 1080p30 media with 1 s handles, so cuts can be trimmed)
  V2  the graphics (captions, pops, labels, circles, arrows, title cards, speed lines) as ONE ProRes 4444 alpha
      clip per element group, so they stay on top and can be moved, nudged or deleted
  A1  narration lines   A2  clip audio (own sound, levelled; bleeps as their own clips on A4)
  A3  music bed with the duck keyframes   A4  flash hits + bleeps
Levels are the mix's own gains (Audio Levels, linear), so the edit sounds like our render.
The worker runs on Linux and cannot drive Premiere; this file is what the app hands the owner.
"""
import os
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from . import fx
from .compose import lufs

FPS = 30
W, H = fx.W, fx.H


def _url(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    return "file://localhost/" + p.replace(" ", "%20").lstrip("/")


def _rate() -> str:
    return f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"


class _Files:
    def __init__(self):
        self.ids: Dict[str, str] = {}

    def ref(self, path: str, frames: int, video: bool, audio: bool, ch: int = 2) -> str:
        if path in self.ids:
            return f'<file id="{self.ids[path]}"/>'
        fid = f"file-{len(self.ids) + 1}"
        self.ids[path] = fid
        media = ""
        if video:
            media += (f"<video><samplecharacteristics>{_rate()}<width>{W}</width><height>{H}</height>"
                      "<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></video>")
        if audio:
            media += (f"<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate>"
                      f"</samplecharacteristics><channelcount>{ch}</channelcount></audio>")
        return (f'<file id="{fid}"><name>{escape(os.path.basename(path))}</name><pathurl>{_url(path)}</pathurl>'
                f"{_rate()}<duration>{frames}</duration><media>{media}</media></file>")


def _level(gain_db: float, keys: Optional[Sequence[Tuple[int, float]]] = None) -> str:
    """Audio Levels filter: linear gain (Premiere caps at +15 dB)."""
    g = 10 ** (max(-60.0, min(15.0, gain_db)) / 20)
    kf = "".join(f"<keyframe><when>{w}</when><value>{v:.5f}</value></keyframe>" for w, v in (keys or []))
    return ("<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid>"
            "<effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype><mediatype>audio</mediatype>"
            f"<parameter><parameterid>level</parameterid><name>Level</name><valuemin>0</valuemin><valuemax>5.6234</valuemax>"
            f"<value>{g:.5f}</value>{kf}</parameter></effect></filter>")


def _clip(cid: str, name: str, start: int, end: int, cin: int, file_xml: str, extra: str = "",
          link: str = "") -> str:
    return (f'<clipitem id="{cid}"><name>{escape(name)}</name>{_rate()}<start>{start}</start><end>{end}</end>'
            f"<in>{cin}</in><out>{cin + end - start}</out>{file_xml}{extra}{link}</clipitem>")


def _run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True, timeout=900, capture_output=True)


def media_with_handles(src: str, src_in: float, dur: float, dst: str, crop: str, handle: float = 1.0) -> Tuple[str, int]:
    """A conformed 1080p30 copy of a shot with up to `handle` s either side; returns (path, handle frames used)."""
    pre = min(handle, max(0.0, src_in))
    vf = (crop + "," if crop else "") + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1"
    if not os.path.isfile(dst):
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{src_in - pre:.3f}", "-t", f"{dur + pre + handle:.3f}", "-i", src,
              "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-an", dst])
    return dst, int(round(pre * FPS))


def audio_with_handles(src: str, src_in: float, dur: float, dst: str, handle: float = 1.0,
                       mutes: Sequence[Tuple[float, float]] = ()) -> Tuple[str, int]:
    """The clip's sound with handles; `mutes` (seconds from src_in) are silenced for the bleep clips."""
    pre = min(handle, max(0.0, src_in))
    af = ",".join(f"volume=0:enable='between(t,{m0 + pre:.3f},{m1 + pre:.3f})'" for m0, m1 in mutes) or "anull"
    if not os.path.isfile(dst):
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{src_in - pre:.3f}", "-t", f"{dur + pre + handle:.3f}", "-i", src,
              "-vn", "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", dst])
    return dst, int(round(pre * FPS))


def overlay_alpha(elements: Sequence[fx.Element], t0: float, t1: float, dst: str) -> str:
    """The graphics of [t0, t1) on a transparent 1080p30 canvas, ProRes 4444 with alpha (Premiere reads it)."""
    from PIL import Image
    n = int(round((t1 - t0) * FPS))
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                            "-vendor", "apl0", dst], stdin=subprocess.PIPE)
    els = [e for e in elements if e.start < t1 and e.start + e.dur > t0]
    blank = bytes(W * H * 4)
    for i in range(n):
        t = t0 + i / FPS
        act = [e for e in els if e.active(t)]
        if not act:
            enc.stdin.write(blank)
            continue
        fr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for e in act:
            got = e.draw(t - e.start)
            if got:
                fx._paste(fr, *got)
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    enc.wait()
    return dst


def export(tl, elements: Sequence[fx.Element], out_dir: str, *, t0: float = 0.0, t1: Optional[float] = None,
           music: str = "", sfx: str = "", name: str = "Celeb edit", target_lufs: float = -20.0,
           music_points=None) -> str:
    """Write <out_dir>/<name>.xml + its media for the section [t0, t1) of a reel.Timeline."""
    from .reel import content_crop
    t1 = tl.total if t1 is None else min(t1, tl.total)
    media = os.path.join(out_dir, "media")
    os.makedirs(media, exist_ok=True)
    files = _Files()
    F = lambda s: int(round(s * FPS))           # noqa: E731
    seq_len = F(t1 - t0)
    v1, v2, a1, a2, a3, a4 = [], [], [], [], [], []
    white = os.path.join(media, "flash_white.mp4")
    if not os.path.isfile(white):
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=white:s={W}x{H}:r={FPS}:d=2", "-c:v", "libx264",
              "-pix_fmt", "yuv420p", white])
    k = 0
    for s in tl.shots:
        if s.at + s.dur <= t0 or s.at >= t1:
            continue
        a, b = max(s.at, t0), min(s.at + s.dur, t1)
        k += 1
        if s.kind == "flash":
            v1.append(_clip(f"v1-{k}", "FLASH", F(a - t0), F(b - t0), 0, files.ref(white, 60, True, False)))
            continue
        crop = content_crop(s.src, s.src_in, s.src_in + s.dur)
        path, h = media_with_handles(s.src, s.src_in + (a - s.at), b - a,
                                     os.path.join(media, f"shot_{k:03d}.mp4"), crop)
        frames = F(b - a) + h + FPS
        v1.append(_clip(f"v1-{k}", f"{s.kind} {os.path.basename(s.src)[3:14]} @{s.src_in:.2f}", F(a - t0), F(b - t0), h,
                        files.ref(path, frames, True, False)))
    ov = overlay_alpha(elements, t0, t1, os.path.join(media, "graphics_alpha.mov"))
    v2.append(_clip("v2-1", "GRAPHICS (captions, pops, labels, circles, arrows, titles)", 0, seq_len, 0,
                    files.ref(ov, seq_len, True, False)))
    k = 0
    for s in tl.sounds:
        if s.kind == "sfx" or s.at >= t1 or s.at + max(s.dur, 0.3) <= t0:
            continue
        a, b = max(s.at, t0), min(s.at + s.dur, t1)
        k += 1
        have = lufs(s.path, s.src_in, s.dur)
        gain = (target_lufs - have) if have is not None else 0.0
        shift = a - s.at
        mutes = [(m0 - shift, m1 - shift) for m0, m1 in (getattr(s, "mutes", []) or [])]
        path, h = audio_with_handles(s.path, s.src_in + shift, b - a, os.path.join(media, f"{s.kind}_{k:03d}.wav"),
                                     mutes=mutes)
        item = _clip(f"a-{s.kind}-{k}", f"{s.kind} {os.path.basename(s.path)[:24]}", F(a - t0), F(b - t0), h,
                     files.ref(path, F(b - a) + h + FPS, False, True), _level(gain))
        (a1 if s.kind == "narr" else a2).append(item)
        for j, (m0, m1) in enumerate(getattr(s, "mutes", []) or []):
            bleep = os.path.join(media, f"bleep_{k}_{j}.wav")
            _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=1000:sample_rate=48000:duration={m1 - m0:.3f}",
                  "-ac", "2", bleep])
            bs = s.at + max(0.0, m0)
            if t0 <= bs < t1:
                a4.append(_clip(f"a-bleep-{k}-{j}", "BLEEP", F(bs - t0), F(bs - t0) + F(m1 - m0), 0,
                                files.ref(bleep, F(m1 - m0) + 2, False, True), _level(-15)))
    if sfx and os.path.isfile(sfx):
        for j, at in enumerate(c for c in tl.cuts if any(abs(c - sh.at) < 1e-3 and sh.kind == "flash" for sh in tl.shots)):
            if t0 <= at < t1:
                have = lufs(sfx) or -20.0
                a4.append(_clip(f"a-sfx-{j}", "FLASH HIT", F(at - t0), F(at - t0) + 15, 0,
                                files.ref(sfx, 15, False, True), _level(target_lufs + 2 - have)))
    if music and os.path.isfile(music):
        mus = os.path.join(media, "music_bed.wav")
        _run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", music, "-t", f"{t1:.3f}", "-ar", "48000", "-ac", "2", mus])
        have = lufs(music, 0, 60) or -27.0
        base = 10 ** (max(-60.0, min(15.0, target_lufs - have)) / 20)
        keys = [(F(x - t0), g * base) for x, g in (music_points or []) if t0 <= x <= t1]
        a3.append(_clip("a-music", "MUSIC BED", 0, seq_len, F(t0), files.ref(mus, F(t1), False, True),
                        _level(target_lufs - have, keys)))

    def track(items: List[str]) -> str:
        return "<track>" + "".join(items) + "</track>"

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="sequence-1">'
           f"<name>{escape(name)}</name><duration>{seq_len}</duration>{_rate()}"
           "<timecode><string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>"
           f"<media><video><format><samplecharacteristics>{_rate()}<width>{W}</width><height>{H}</height>"
           "<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics></format>"
           f"{track(v1)}{track(v2)}</video><audio>{track(a1)}{track(a2)}{track(a3)}{track(a4)}</audio></media>"
           "</sequence></xmeml>\n")
    dst = os.path.join(out_dir, f"{name}.xml")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return dst
