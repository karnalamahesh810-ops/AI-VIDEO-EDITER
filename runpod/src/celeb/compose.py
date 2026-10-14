"""
An ffmpeg renderer for a celeb plan (plan.Plan): one encode per shot, then one pass that concatenates,
burns the captions/labels (ASS, Bangers comic face) and muxes the mix.

The look (owner's "clean" version of Celebs Goat):
  * clip captions only on clip speech: yellow comic caps on a black rounded pill, bottom centre (y ~ 92 %)
  * the show / person label bottom-left, white comic caps with a drop shadow and a yellow bar, ~2.8 s
  * a slow 100 -> 104 % push-in over every clip (no jump zooms); b-roll as is (no grade, no Ken Burns)
  * a 0.2 s white flash with a shutter between segments
Mix: narration and every clip levelled to -16 LUFS (measured, then a fixed gain + limiter, so a laugh is
not pumped); clip audio carries 60 ms fades; music at the owner's 0.5 x 0.8 under narration and x0.18 in clips.
"""
import json
import os
import re
import shutil
import subprocess
from typing import List, Optional, Sequence, Tuple

from . import plan as P

W, H, FPS = 1920, 1080, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Bangers-Regular.ttf")
FONT_NAME = "Bangers"
CAPTION_SIZE, LABEL_SIZE = 54, 84
YELLOW = "&H001AE5FF"           # #FFE51A in ASS BGR
TARGET_LUFS = -16.0
MUSIC_LUFS = -27.0              # the bundled beds' level (timeline.BGM_LUFS), so MUSIC_LEVEL means the same


def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 900) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-600:]}")
    return p


def duration(path: str) -> float:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(p.stdout.strip() or 0)


def lufs(path: str, start: float = 0.0, dur: float = 0.0) -> Optional[float]:
    """Integrated loudness of a file's audio (or a part of it)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-i", path]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr)
    try:
        v = float(json.loads(m.group(0))["input_i"]) if m else None
    except (ValueError, KeyError):
        return None
    return v if v is not None and v > -70 else None


# ------------------------------------------------------------------ captions (ASS)
def _ts(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _text_width(text: str, size: int) -> float:
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(FONT, size)
        b = f.getbbox(text)
        return float(b[2] - b[0])
    except Exception:  # noqa: BLE001 - no PIL/font: a fair estimate
        return 0.5 * size * len(text)


def _pill(w: float, h: float, r: float) -> str:
    """An ASS drawing of a rounded rectangle w x h (radius r), origin top-left."""
    k = r * 0.45
    return (f"m {r:.0f} 0 l {w - r:.0f} 0 b {w - k:.0f} 0 {w:.0f} {k:.0f} {w:.0f} {r:.0f} "
            f"l {w:.0f} {h - r:.0f} b {w:.0f} {h - k:.0f} {w - k:.0f} {h:.0f} {w - r:.0f} {h:.0f} "
            f"l {r:.0f} {h:.0f} b {k:.0f} {h:.0f} 0 {h - k:.0f} 0 {h - r:.0f} "
            f"l 0 {r:.0f} b 0 {k:.0f} {k:.0f} 0 {r:.0f} 0")


def _clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", "", text)                 # [Laughter]
    text = re.sub(r"(\w) -(\w)", r"\1-\2", text)          # whisper's "Spider -Man"
    return re.sub(r"\s+", " ", text.replace("{", "(").replace("}", ")")).strip()


def ass(p: P.Plan) -> str:
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{FONT_NAME},{CAPTION_SIZE},{YELLOW},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,1.5,0,"
            "1,0,0,5,0,0,0,1\n"
            f"Style: Box,{FONT_NAME},{CAPTION_SIZE},&H26000000,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,"
            "1,0,0,7,0,0,0,1\n"
            f"Style: Label,{FONT_NAME},{LABEL_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,2,0,"
            "1,0,5,1,0,0,0,1\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    cy = int(H * 0.92)
    for a, b, text in p.captions:
        text = _clean(text)
        if not text or b - a < 0.15:
            continue
        w = _text_width(text, CAPTION_SIZE) * 1.03 + 44
        h = CAPTION_SIZE * 1.25
        x0, y0 = (W - w) / 2, cy - h / 2
        ev.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Box,,0,0,0,,{{\\pos({x0:.0f},{y0:.0f})\\p1}}{_pill(w, h, h / 2)}{{\\p0}}")
        ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{\\pos({W / 2:.0f},{cy + 2})}}{text}")
    for a, b, text in p.labels:
        x, y = 104, int(H * 0.80)
        bar = f"m 0 0 l 12 0 l 12 {LABEL_SIZE} l 0 {LABEL_SIZE}"
        ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Label,,0,0,0,,{{\\fad(120,200)\\move({x - 70},{y},{x - 30},{y},0,180)"
                  f"\\an1\\bord0\\shad0\\1c&H0025D5FF&\\p1}}{bar}{{\\p0}}")
        ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Label,,0,0,0,,{{\\fad(120,200)\\move({x - 40},{y + 4},{x},{y + 4},0,180)"
                  f"\\an1\\i1}}{_clean(text)}")
    return head + "\n".join(ev) + "\n"


# ------------------------------------------------------------------ video
def _frames(a: float, b: float) -> int:
    return max(1, round(b * FPS) - round(a * FPS))


def render_shot(s: P.Shot, dst: str) -> str:
    n = _frames(s.at, s.at + s.dur)
    if s.kind == "flash":
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=white:s={W}x{H}:r={FPS}",
              "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dst])
        return dst
    cover = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if s.push:
        span = max(0.5, s.dur)
        zoom = f"scale=w='trunc({W}*(1+0.04*t/{span:.3f})/2)*2':h=-2:eval=frame,crop={W}:{H}"
        vf = f"{cover},setpts=PTS-STARTPTS,{zoom},fps={FPS},setsar=1,format=yuv420p"
    else:
        vf = f"{cover},fps={FPS},setsar=1,format=yuv420p"
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s.src_in:.3f}", "-i", s.src, "-vf", vf, "-an",
          "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", dst])
    return dst


# ------------------------------------------------------------------ audio
def _gain_expr(points: Sequence[Tuple[float, float]]) -> str:
    """A piecewise-linear gain over t as one ffmpeg expression."""
    expr = f"{points[-1][1]}"
    for (x0, g0), (x1, g1) in reversed(list(zip(points, points[1:]))):
        if x1 - x0 < 1e-3:
            continue
        seg = f"({g0}+({g1}-{g0})*(t-{x0})/({x1 - x0:.3f}))"
        expr = f"if(lt(t,{x1}),{seg},{expr})"
    return expr


def mix(p: P.Plan, work: str, music: str = "", sfx: str = "", sfx_level: float = 0.4) -> str:
    """The final stereo mix (wav) on the plan's clock."""
    inputs, chains, labels = [], [], []
    for k, s in enumerate(p.sounds):
        inputs += ["-ss", f"{s.src_in:.3f}"] + (["-t", f"{s.dur:.3f}"] if s.dur else []) + ["-i", s.path]
        gain = 0.0
        if s.kind in ("clip", "cold"):
            have = lufs(s.path, s.src_in, s.dur)
            gain = (TARGET_LUFS - have) if have is not None else 0.0
            gain = max(-12.0, min(12.0, gain))
        fade = ""
        if s.kind == "cold":                               # an excerpt: its own 60 ms edges
            fade = f",afade=t=in:d=0.06,afade=t=out:st={max(0.0, s.dur - 0.06):.3f}:d=0.06"
        ms = int(round(s.at * 1000))
        chains.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain:.2f}dB{fade},"
                      f"adelay={ms}|{ms}[s{k}]")
        labels.append(f"[s{k}]")
    n = len(p.sounds)
    if sfx and os.path.isfile(sfx):
        for j, at in enumerate(p.flashes):
            inputs += ["-i", sfx]
            ms = int(round(max(0.0, at - 0.03) * 1000))
            chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={sfx_level},"
                          f"adelay={ms}|{ms}[f{j}]")
            labels.append(f"[f{j}]")
            n += 1
    if music and os.path.isfile(music):
        have = lufs(music, 0, 60) or MUSIC_LUFS
        inputs += ["-stream_loop", "-1", "-i", music]
        g = _gain_expr(P.music_gain_points(p))
        chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{p.total:.3f},"
                      f"volume={MUSIC_LUFS - have:.2f}dB,volume='{g}':eval=frame,"
                      f"afade=t=out:st={max(0.0, p.total - 1.5):.3f}:d=1.5[mu]")
        labels.append("[mu]")
        n += 1
    graph = ";".join(chains) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest," \
                               f"atrim=0:{p.total:.3f},alimiter=limit=0.95[out]"
    dst = os.path.join(work, "mix.wav")
    script = os.path.join(work, "mix_graph.txt")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(graph)
    _run(["ffmpeg", "-y", "-v", "error", *inputs, "-/filter_complex", script, "-map", "[out]",
          "-ar", "48000", "-ac", "2", dst], timeout=1200)
    return dst


# ------------------------------------------------------------------ the whole render
def render(p: P.Plan, work: str, out: str, *, music: str = "", sfx: str = "") -> str:
    os.makedirs(work, exist_ok=True)
    parts = []
    for k, s in enumerate(p.shots):
        parts.append(render_shot(s, os.path.join(work, f"shot_{k:03d}.mp4")))
    with open(os.path.join(work, "shots.txt"), "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{os.path.basename(x)}'\n" for x in parts)
    fonts = os.path.join(work, "fonts")
    os.makedirs(fonts, exist_ok=True)
    shutil.copy(FONT, fonts)
    with open(os.path.join(work, "captions.ass"), "w", encoding="utf-8") as fh:
        fh.write(ass(p))
    audio = mix(p, work, music, sfx)
    # Relative names inside `work`: the subtitles filter's own escaping of Windows paths is fragile.
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "shots.txt", "-i", os.path.basename(audio),
          "-vf", "subtitles=captions.ass:fontsdir=fonts", "-map", "0:v", "-map", "1:a",
          "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", os.path.abspath(out)],
         cwd=work, timeout=1800)
    return out


def phone_copy(src: str, dst: str, max_mb: float = 24.0) -> str:
    """A 720p copy under max_mb (bitrate from the length)."""
    secs = duration(src)
    kbps = int(max(600, (max_mb * 8192 / max(1.0, secs)) - 128) * 0.92)
    _run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "medium",
          "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k",
          "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst])
    return dst
