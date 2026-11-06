"""
The laptop kit's render engine for the Breaking News Desk style (tools/storm-desk-kit engine/render3.py + looks/build.py):
every shot its own short file, cut straight from the source clip with its crop, its logo paint-out and its graphics drawn
once, then the files joined without another encode. Nothing is encoded twice, and a re-render only draws the shots whose
spec changed (a shot's name is the hash of what it shows, on disk and in R2).

doc -> specs (build_specs) -> pieces (render_pieces, a process per shot group) -> join + base sound (draw). The master and
the pause sound stay in stormdesk.after_render, so both engines deliver the same way. Old timelines and documents this
engine cannot draw (supported()) go through Remotion as before.

All times inside a spec are the shot's own (frame 0 = its first frame), so a pause that moves later shots moves no spec.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config

ENGINE_VERSION = 1
FPS_DEFAULT = 30
W, H = 1920, 1080
SR = 48000
HOOK_DISSOLVE_FRAMES = 18          # the kit's 0.6 s: the last hook clip dissolves into the first narrated shot
PIECE_TIMEOUT = 900                # one shot may take this long before it is killed and tried again (the kit's watchdog)
PIECE_TRIES = 3
LEVEL_DB = -13.0                   # the looks' SFX: ~22% (owner 2026-11-04)
VOICE_LUFS = -16.0
MUSIC_UNDER_VOICE_DB = 15.0        # the owner's BGM (2026-11-05: soft but there), integrated, on the voice's -16
MUSIC_DUCK = 0.8                   # ... and x0.8 while he speaks (render3)
MUSIC_FADE_IN, MUSIC_FADE_OUT = 2.0, 4.0


def engine_of(doc: Optional[dict] = None, inp: Optional[dict] = None) -> str:
    """"pieces" or "remotion". A document says which engine it was planned for; a job may choose; else the setting."""
    if doc is not None:                  # a timeline keeps the engine it was planned for; an older one has Remotion's graphics
        return str((doc.get("stormDesk") or {}).get("engine") or "remotion")
    o = str(((inp or {}).get("storm_desk") or {}).get("engine") or "")
    if o in ("pieces", "remotion"):
        return o
    return "pieces" if str(getattr(config, "STORM_DESK_ENGINE", "remotion")) == "pieces" else "remotion"


def supported(doc: dict) -> str:
    """"" when this engine can draw the document, else why not (it then goes through Remotion)."""
    fps = int(doc.get("fps") or FPS_DEFAULT)
    if int(doc.get("width") or W) != W or int(doc.get("height") or H) != H:
        return "not 1920x1080"
    if fps != FPS_DEFAULT:
        return f"{fps} fps"
    if doc.get("overlays"):
        return "overlays in the timeline"
    for s in doc.get("scenes") or []:
        m = s.get("media") or {}
        if m.get("type") == "animation":
            continue                         # the quality check's last resort, a line of text: drawn as a card
        if m.get("type") not in ("video", "image"):
            return f"a {m.get('type') or 'empty'} scene"
        if not m.get("url"):
            return "a scene without media"
    from . import brandkit
    intro, _body, _outro, total = brandkit.layout(doc)
    if intro or total != int(doc.get("durationInFrames") or total):
        return "brand intro or outro"
    return ""


# --------------------------------------------------------------------------- #
# The picture of one shot (render3.vf_for)
# --------------------------------------------------------------------------- #
def vf_for(mode: str, w: int, h: int) -> str:
    """The filter from a source frame to 1920x1080. mode: full | vert | newsK@TOP (a centred crop, K of the frame from
    TOP down: drops a station's lower third, corner bug and ticker) | boxX,Y,W,H (a clip framed inside the frame) | ai."""
    upscale = h < 1000
    sharpen = ",unsharp=5:5:0.6:5:5:0.0" if upscale else ""
    if mode.startswith("box"):
        x, y, bw, bh = (float(v) for v in mode[3:].split(","))
        pre = f"crop=iw*{bw}:ih*{bh}:iw*{x}:ih*{y},"
        if bw * w / max(1.0, bh * h) >= 1.5:
            return pre + f"scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080{sharpen}"
        return (pre + "split[a][b];[a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=28:2,"
                "eq=brightness=-0.06:saturation=0.85[bg];[b]scale=-2:1080:flags=lanczos"
                f"{sharpen}[fg];[bg][fg]overlay=(W-w)/2:0")
    if mode == "vert":
        return ("split[a][b];[a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=28:2,"
                "eq=brightness=-0.06:saturation=0.85[bg];[b]scale=1135:1080:force_original_aspect_ratio=increase:"
                f"flags=lanczos,crop=1135:1080{sharpen}[fg];[bg][fg]overlay=392:0")
    if mode.startswith("news"):
        k, _, top = (mode[4:] or "0.78").partition("@")
        k_, top_ = float(k), float(top or 0.03)
        return f"crop=iw*{k_}:ih*{k_}:iw*{(1 - k_) / 2}:ih*{top_},scale=1920:1080:flags=lanczos{sharpen}"
    if mode == "ai":
        return "hqdn3d=1:1:3:3,scale=1920:1080:flags=lanczos,unsharp=5:5:0.9:5:5:0.0,unsharp=3:3:0.35:3:3:0.0"
    return f"scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080{sharpen}"


def delogo_chain(boxes: List[List[float]], w: int, h: int) -> str:
    """Small logos painted out from the pixels around them, fitted tight (owner 2026-11-05: "blur without looking like a
    blur"): delogo refuses a box touching the frame's edge, so each is held 1 px inside."""
    out = ""
    for bx, by, bw, bh in boxes or []:
        x, y = max(1, int(w * bx)), max(1, int(h * by))
        out += f"delogo=x={x}:y={y}:w={max(4, min(w - x - 2, int(w * bw)))}:h={max(4, min(h - y - 2, int(h * bh)))},"
    return out


def adjust_chain(a: Optional[dict]) -> str:
    """The editor's adjustment line (doc.adjust / scene.adjust, remotion edit/adjust.tsx): zoom, position, mirror, colour."""
    if not isinstance(a, dict) or not a:
        return ""
    out = ""
    if a.get("flip"):
        out += ",hflip"
    sc = float(a.get("scale") or 1.0)
    x, y = float(a.get("x") or 0.0), float(a.get("y") or 0.0)
    if abs(sc - 1.0) > 1e-3 or x or y:
        sc = max(1.0, sc)                   # never a smaller picture than the frame: no black edges
        out += (f",scale=iw*{sc}:ih*{sc},crop=1920:1080:"
                f"max(0\\,min(iw-1920\\,(iw-1920)/2-({x})*iw)):max(0\\,min(ih-1080\\,(ih-1080)/2-({y})*ih))")
    b, c, s = a.get("brightness"), a.get("contrast"), a.get("saturation")
    if any(v not in (None, 1, 1.0) for v in (b, c, s)):
        out += f",eq=brightness={float(b if b is not None else 1.0) - 1.0}:contrast={float(c if c is not None else 1.0)}" \
               f":saturation={float(s if s is not None else 1.0)}"
    return out


# --------------------------------------------------------------------------- #
# Specs
# --------------------------------------------------------------------------- #
def _events(doc: dict) -> List[tuple]:
    """(kind, start frame, frames, data) for the style's own graphics (doc.stormDesk, as StormDesk.tsx reads it)."""
    d = doc.get("stormDesk") or {}
    ev: List[tuple] = []
    for lt in d.get("lowerThirds") or []:
        lines = [str(x) for x in (lt.get("lines") or []) if x]
        ev.append(("lt", int(lt["startFrame"]), int(lt["durationInFrames"]), [" ".join(lines), str(lt.get("tab") or "")]))
    loc = d.get("location")
    if isinstance(loc, dict) and loc.get("place"):
        ev.append(("loc", int(loc["startFrame"]), int(loc["durationInFrames"]), [str(loc["place"]), str(loc.get("date") or "")]))
    for sb in d.get("subscribe") or []:
        ev.append(("sub", int(sb["startFrame"]), int(sb["durationInFrames"]), []))
    return ev


def _layers_at(f: int, ev: List[tuple], fps: int, fixed: List[list]) -> tuple:
    """Everything of the desk's graphics on video frame f, with a hold's frames sharing one key (render3.hold_key)."""
    out = list(fixed)
    for kind, a, n, data in ev:
        k = f - a
        if k < 0:
            continue
        if kind == "lt" and k <= n + int(0.6 * fps):
            k2 = 13 if 13 <= k <= n + 12 else k
            out.append(["lt", data[0], data[1], k2, n])
        elif kind == "loc" and k <= n + int(0.4 * fps):
            k2 = 10 if 10 <= k <= n else k
            out.append(["loc", data[0], data[1], k2, n])
        elif kind == "sub" and k <= n:
            k2 = 5 if 5 <= k <= n - 7 else k
            out.append(["sub", k2, n])
    return tuple(tuple(x) for x in out)


def _clip_mode(s: dict) -> str:
    sd = s.get("stormDesk") or {}
    if sd.get("mode"):
        return str(sd["mode"])
    return "ai" if (s.get("media") or {}).get("source") in ("ai", "generated") else "full"


def scene_spec(doc: dict, i: int, ev: Optional[List[tuple]] = None, looks: Optional[dict] = None) -> dict:
    """What shot i shows, in its own time. Two shots with one spec are one file."""
    fps = int(doc.get("fps") or FPS_DEFAULT)
    s = doc["scenes"][i]
    m = s.get("media") or {}
    f0, n = int(s["startFrame"]), int(s["durationInFrames"])
    ev = _events(doc) if ev is None else ev
    desk = doc.get("stormDesk") or {}
    fixed: List[list] = []
    if (desk.get("logo") or {}).get("url") or (desk.get("logo") or {}).get("text"):
        fixed.append(["bug"])
    if s.get("blurSides") and desk.get("sideLogo") is not False:
        fixed.append(["side"])
    cr = s.get("credit") or {}
    if cr.get("ai"):                             # no source names and no ARCHIVE tag on screen (the owner 2026-11-06)
        fixed.append(["chip", "AI ILLUSTRATION", True])
    if s.get("caption"):
        fixed.append(["cap", str(s["caption"])])
    if m.get("type") == "animation":
        fixed.append(["card", str(s.get("text") or "")[:160]])
    runs: List[list] = []                        # [frames, key] run lengths
    for k in range(n):
        key = _layers_at(f0 + k, ev, fps, fixed)
        if runs and runs[-1][1] == key:
            runs[-1][0] += 1
        else:
            runs.append([1, key])
    adj = {}
    if isinstance(doc.get("adjust"), dict):
        adj.update(doc["adjust"])
    if isinstance(s.get("adjust"), dict):
        adj.update(s["adjust"])
    spec: Dict[str, Any] = {
        "v": ENGINE_VERSION, "kind": m.get("type"), "src": str(m.get("url") or ""), "srcKey": _src_key(s), "ss": round(float(m.get("trimStart") or 0.0), 3),
        "n": n, "fps": fps, "mode": _clip_mode(s), "delogo": (s.get("stormDesk") or {}).get("delogo") or [],
        "flip": bool((s.get("stormDesk") or {}).get("flipNow")), "adjust": adj, "layers": runs,
    }
    secs = n / float(fps)
    room = float(m.get("clipSeconds") or 0.0) - spec["ss"]
    if m.get("type") == "video" and 0.05 < room < secs - 0.04:
        spec["rate"] = round(max(0.6, room / secs), 4)       # a held-over clip plays slower instead of running out
    if looks:
        spec["looks"] = looks_for_shot(looks, f0, n, fps, desk.get("statStyle"))
    tail = s.get("hookTail")
    if isinstance(tail, dict) and tail.get("src"):
        spec["dissolve"] = {**tail, "n": min(HOOK_DISSOLVE_FRAMES, n), "srcKey": os.path.basename(str(tail["src"]).split("?")[0])}
    if f0 == 0 or f0 + n >= int(doc.get("durationInFrames") or (f0 + n)):
        spec["edge"] = {"first": f0 == 0, "last": f0 + n >= int(doc.get("durationInFrames") or (f0 + n))}
    return spec


def spec_key(spec: dict) -> str:
    """A shot's name: what it shows, not which disk or link its source is on today (srcKey stands for it)."""
    x = {k: v for k, v in spec.items() if k != "src"}
    if isinstance(x.get("dissolve"), dict):
        x["dissolve"] = {k: v for k, v in x["dissolve"].items() if k != "src"}
    return hashlib.sha1(json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:20]


def _src_key(s: dict) -> str:
    sm = s.get("semanticMetadata") or {}
    return str(sm.get("assetId") or sm.get("sourceUrl") or os.path.basename(str((s.get("media") or {}).get("url") or "").split("?")[0]))


def looks_for_shot(tl: dict, f0: int, n: int, fps: int, stat_style: Optional[dict] = None) -> List[list]:
    """The looks (stormlooks.timeline) that touch this shot, in seconds from its first frame."""
    from . import stormlooks
    t0, t1 = f0 / float(fps), (f0 + n) / float(fps)
    out: List[list] = []

    def rel(x: float) -> float:
        return round(float(x) - t0, 3)
    for a, b, text in tl.get("type") or []:
        if a < t1 and b > t0:
            out.append(["type", rel(a), rel(b), text])
    for a, b, text in tl.get("stats") or []:
        if a < t1 and b > t0:
            out.append(stormlooks.stat_row(rel(a), rel(b), text, stat_style))
    for a, b, text in tl.get("places") or []:
        if a < t1 and b > t0:
            out.append(["place", rel(a), rel(b), text])
    for a, b, d, c in tl.get("stamps") or []:
        if a < t1 and b > t0:
            out.append(["stamp", rel(a), rel(b), d, c])
    for a, tb, b, title, sub in tl.get("titles") or []:
        if a < t1 and b + 0.2 > t0:
            out.append(["title", rel(a), rel(tb), rel(b), title, sub])
    for g in tl.get("graphs") or []:         # [start, end, title, [[label, shown value, number, highlighted], ...], base]
        if g[0] < t1 and g[1] > t0:
            out.append(["graph", rel(g[0]), rel(g[1]), g[2], g[3], float(g[4]) if len(g) > 4 else 0.0])
    for mp in tl.get("maps") or []:
        if mp["t0"] < t1 and mp["t1"] > t0:
            out.append(["map", rel(mp["t0"]), rel(mp["t1"]), rel(mp["pin"]), mp["lat"], mp["lon"], mp["label"],
                        mp.get("stat") or "", mp["file"], mp["meta"]])
    return out


def build_specs(doc: dict) -> List[dict]:
    ev = _events(doc)
    looks = (doc.get("stormDesk") or {}).get("looks") or None
    return [scene_spec(doc, i, ev, looks) for i in range(len(doc.get("scenes") or []))]


# --------------------------------------------------------------------------- #
# Drawing one shot (runs in its own process)
# --------------------------------------------------------------------------- #
_compose_cache: Dict[tuple, bytes] = {}


def _compose(key: tuple) -> bytes:
    from PIL import Image
    from .sdkit import gfx
    if key in _compose_cache:
        return _compose_cache[key]
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fps = float(FPS_DEFAULT)
    for L in key:
        if L[0] == "bug":
            im.alpha_composite(gfx.bug())
        elif L[0] == "side":
            lg = gfx.with_alpha(gfx.logo(150), 0.8)
            for cx in (196, 1724):
                im.alpha_composite(lg, (cx - lg.width // 2, 540 - lg.height // 2))
        elif L[0] == "chip":
            im.alpha_composite(gfx.corner_chip(L[1], L[2]))
        elif L[0] == "lt":
            x = gfx.lower_third(L[1], L[2], L[3] / fps, L[4] / fps)
            if x is not None:
                im.alpha_composite(x)
        elif L[0] == "loc":
            x = gfx.loc_tag(L[1], L[2], L[3] / fps, L[4] / fps)
            if x is not None:
                im.alpha_composite(x)
        elif L[0] == "cap":
            im.alpha_composite(_caption(L[1]))
        elif L[0] == "card":
            im.alpha_composite(_card(L[1]))
        elif L[0] == "sub":
            x = gfx.subscribe(L[1] / fps, L[2] / fps)
            if x is not None:
                im.alpha_composite(x)
    raw = im.tobytes()
    if len(_compose_cache) > 40:
        _compose_cache.clear()
    _compose_cache[key] = raw
    return raw


def _caption(text: str):
    """Small white line at the bottom left with a soft shadow: what a pause clip shows (render3.caption_img)."""
    from PIL import Image, ImageDraw, ImageFilter
    from .sdkit import gfx
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f = gfx.font(34, "SemiBold")
    d = ImageDraw.Draw(lay)
    d.text((62, 1046), text, font=f, fill=(0, 0, 0, 200), anchor="ls")
    lay = lay.filter(ImageFilter.GaussianBlur(4))
    d = ImageDraw.Draw(lay)
    d.text((60, 1044), text, font=f, fill=(255, 255, 255, 255), anchor="ls")
    return lay


def _card(text: str):
    """A line with no picture: plain white words on the dark ground (quality.text_scene's scenes, the very last resort)."""
    import textwrap
    from PIL import Image, ImageDraw
    from .sdkit import gfx
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f = gfx.font(58, "Bold")
    lines = textwrap.wrap(text, 44)[:4]
    d = ImageDraw.Draw(lay)
    y = H // 2 - 40 * len(lines)
    for ln in lines:
        d.text((W // 2, y), ln, font=f, fill=(255, 255, 255, 255), anchor="mm")
        y += 80
    return lay


def _probe_wh(path: str) -> Tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0:s=x", path], capture_output=True, text=True, timeout=120).stdout.strip()
    try:
        w, h = out.split("\n")[0].split("x")[:2]
        return int(w), int(h)
    except ValueError:
        return 1920, 1080


def _input_args(spec: dict, n: int) -> List[str]:
    if spec["kind"] == "animation":
        return ["-f", "lavfi", "-i", f"color=c=0x0B1220:s={W}x{H}:r={spec['fps']}"]
    if spec["kind"] == "image":
        return ["-loop", "1", "-framerate", str(spec["fps"]), "-i", spec["src"]]
    return ["-ss", f"{float(spec['ss']):.3f}", "-i", spec["src"]]


def _base_vf(spec: dict, w: int, h: int, n: int) -> str:
    fps = spec["fps"]
    vf = vf_for(spec.get("mode") or "full", w, h)
    if spec.get("flip"):
        vf = "hflip," + vf
    vf = delogo_chain(spec.get("delogo") or [], w, h) + vf
    rate = spec.get("rate")
    if rate:
        vf = f"setpts=PTS/{rate}," + vf
    vf += adjust_chain(spec.get("adjust"))
    # A source that runs short holds its last frame: a shot is never a frame short (the picture would drift from the words).
    vf += f",fps={fps},tpad=stop_mode=clone:stop_duration={n / float(fps) + 1:.2f},setsar=1"
    return vf


def _encoder(threads: int) -> List[str]:
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-bf", "0", "-g", str(FPS_DEFAULT), "-threads", str(threads),
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-video_track_timescale", str(FPS_DEFAULT * 512), "-an"]


def _draw_looks(fr, t: float, looks: List[list], cams: dict):
    """looks/build.py frame(): the looks over one frame, t in the shot's seconds."""
    from .sdkit import gfx, looks as L
    for x in looks:
        if x[0] == "map" and x[1] <= t < x[2]:
            _a, a, b, pin, lat, lon, label, stat, file, meta = x
            if file not in cams:
                L.META[file] = meta
                cams[file] = L.SatCam(file, file)
            beats = {"pin": pin, "stat": pin + 0.5}
            m = L.map_pin(t, cams[file], a, b, beats, lat, lon, label, stat or None)
            m.alpha_composite(gfx.bug()) if gfx.LOGO or gfx.LOGO_TEXT else None
            k = min(L.ramp(t, a, a + 0.35), 1 - L.ramp(t, b - 0.3, b))
            from PIL import Image
            fr = Image.blend(fr, m, k) if k < 1 else m
    for x in looks:
        if x[0] == "title":
            _a, a, tb, b, title, sub = x
            fr = L.chapter_title(fr, t, a, tb, b, title, sub)
            if b <= t < b + 0.2:
                fr = _dim(fr, L.ramp(t, b, b + 0.2))
    for x in looks:
        if x[0] == "type":
            L.typewriter_date(fr, t, x[1], x[2], x[3])
        elif x[0] == "stat":
            _draw_stat(fr, t, x, L)
        elif x[0] == "place":
            L.place_tag(fr, t, x[1], x[2], x[3])
        elif x[0] == "stamp":
            L.cam_stamp(fr, t, x[1], x[2], x[3], x[4])
        elif x[0] == "graph":
            L.mini_graph(fr, t, x[1], x[2], x[3], [tuple(r) for r in x[4]], base=x[5])
    return fr


def _draw_stat(fr, t: float, x: list, L: Any) -> None:
    """["stat", start, end, text, style, size px, colour]: corner by default; an older spec has only the first four."""
    style = x[4] if len(x) > 4 else "corner"
    size = int(x[5]) if len(x) > 5 else 46
    c = str(x[6]) if len(x) > 6 else ""
    color = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) if len(c) == 7 else L.RED
    if style == "center":
        L.red_stat(fr, t, x[1], x[2], x[3], size=size, color=color)
    else:
        L.corner_stat(fr, t, x[1], x[2], x[3], size=size, plate_on=style == "corner_plate", color=color)


def _dim(fr, k: float):
    import numpy as np
    from PIL import Image
    arr = np.asarray(fr.convert("RGB")).astype(np.float32) * k
    return Image.fromarray(arr.astype(np.uint8)).convert("RGBA")


def _needs_frames(spec: dict) -> bool:
    return bool(spec.get("looks") or spec.get("dissolve") or spec.get("edge"))


def _keys_in_order(spec: dict) -> List[tuple]:
    out: List[tuple] = []
    for count, key in spec["layers"]:
        out.append((int(count), tuple(tuple(x) for x in key)))
    return out


def _draw_fast(spec: dict, w: int, h: int, out: str, threads: int) -> None:
    """No look on this shot: the graphics are pasted by ffmpeg, from one PNG when they do not move, else frame by frame."""
    from PIL import Image
    n = int(spec["n"])
    vf = _base_vf(spec, w, h, n)
    keys = _keys_in_order(spec)
    inputs = _input_args(spec, n)
    plain = len(keys) == 1 and not keys[0][1]
    if plain:
        cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-vf", vf + ",format=yuv420p", "-frames:v", str(n), *_encoder(threads), out]
        subprocess.run(cmd, check=True, timeout=PIECE_TIMEOUT, capture_output=True)
        return
    fc = f"[0:v]{vf},format=rgb24[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
    if len(keys) == 1:
        png = out + ".png"
        Image.frombytes("RGBA", (W, H), _compose(keys[0][1])).save(png, compress_level=1)
        cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-loop", "1", "-framerate", str(spec["fps"]), "-i", png,
               "-filter_complex", fc, "-map", "[v]", "-frames:v", str(n), *_encoder(threads), out]
        try:
            subprocess.run(cmd, check=True, timeout=PIECE_TIMEOUT, capture_output=True)
        finally:
            if os.path.exists(png):
                os.remove(png)
        return
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(spec["fps"]),
           "-i", "-", "-filter_complex", fc, "-map", "[v]", "-frames:v", str(n), *_encoder(threads), out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for count, key in keys:
            raw = _compose(key)
            for _ in range(count):
                p.stdin.write(raw)
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read()
    if p.wait(timeout=PIECE_TIMEOUT) != 0:
        raise RuntimeError(err[-300:].decode("utf-8", "replace"))


def _tail_frames(d: dict) -> List[Any]:
    """The clip the hook ended on, played on under the first narrated shot's first 0.6 s."""
    from PIL import Image
    src = d["src"]
    w, h = _probe_wh(src)
    spec = {"kind": "video", "src": src, "ss": float(d.get("ss") or 0.0), "n": int(d["n"]), "fps": FPS_DEFAULT,
            "mode": d.get("mode") or "full", "delogo": d.get("delogo") or []}
    p = subprocess.run(["ffmpeg", "-v", "error", *_input_args(spec, spec["n"]), "-vf", _base_vf(spec, w, h, spec["n"]),
                        "-frames:v", str(spec["n"]), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, timeout=PIECE_TIMEOUT)
    size = W * H * 3
    return [Image.frombytes("RGB", (W, H), p.stdout[k * size:(k + 1) * size]).convert("RGBA")
            for k in range(len(p.stdout) // size)]


def _draw_frames(spec: dict, w: int, h: int, out: str, threads: int) -> None:
    """A shot with a look, a dissolve or a fade: every frame through Python, as looks/build.py, but only this shot's."""
    from PIL import Image
    from .sdkit import looks as L
    n, fps = int(spec["n"]), int(spec["fps"])
    vf = _base_vf(spec, w, h, n) + ",format=rgb24"
    dec = subprocess.Popen(["ffmpeg", "-v", "error", *_input_args(spec, n), "-vf", vf, "-frames:v", str(n), "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
                            "-i", "-", *_encoder(threads), out], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    size = W * H * 3
    cams: dict = {}
    looks = spec.get("looks") or []
    tail = _tail_frames(spec["dissolve"]) if spec.get("dissolve") else []
    edge = spec.get("edge") or {}
    keys = []
    for count, key in _keys_in_order(spec):
        keys.extend([key] * count)
    last_raw = None
    try:
        for i in range(n):
            raw = dec.stdout.read(size)
            if len(raw) < size:
                raw = last_raw
                if raw is None:
                    raise RuntimeError("no picture from the source")
            last_raw = raw
            t = i / float(fps)
            fr = Image.frombytes("RGB", (W, H), raw).convert("RGBA")
            if i < len(tail):                    # the hook dissolves into the first narrated shot
                fr = Image.blend(fr, tail[i], 1 - L.ease(i / max(1.0, float(len(tail)))))
            key = keys[i] if i < len(keys) else ()
            if key:
                fr.alpha_composite(Image.frombytes("RGBA", (W, H), _compose(key)))
            fr = _draw_looks(fr, t, looks, cams)
            if edge.get("first") and t < 0.3:
                fr = _dim(fr, L.ramp(t, 0, 0.3))
            if edge.get("last") and t > n / float(fps) - 0.6:
                fr = _dim(fr, 1 - L.ramp(t, n / float(fps) - 0.6, n / float(fps)))
            enc.stdin.write(fr.convert("RGB").tobytes())
        enc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        dec.kill()
    err = enc.stderr.read()
    if enc.wait(timeout=PIECE_TIMEOUT) != 0:
        raise RuntimeError(err[-300:].decode("utf-8", "replace"))


def _worker_init(logo: str, text: str) -> None:
    from .sdkit import gfx
    gfx.configure(logo, text)
    try:
        os.nice(5)                       # the handler's progress writes keep their share of the machine
    except (AttributeError, OSError):
        pass


def render_one(spec: dict, out: str, threads: int = 3) -> str:
    """Draw one shot to `out` (atomically). Raises after PIECE_TRIES failures."""
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".part.mp4"
    last = None
    for attempt in range(PIECE_TRIES):
        try:
            w, h = _probe_wh(spec["src"]) if spec["kind"] == "video" else (W, H) if spec["kind"] == "animation" else _image_wh(spec["src"])
            if _needs_frames(spec):
                _draw_frames(spec, w, h, tmp, threads)
            else:
                _draw_fast(spec, w, h, tmp, threads)
            if frames_of(tmp) != int(spec["n"]):
                raise RuntimeError(f"{frames_of(tmp)} frames, wanted {spec['n']}")
            os.replace(tmp, out)
            return out
        except Exception as e:  # noqa: BLE001 - tried again, then the job says which shot failed
            last = e
            if os.path.exists(tmp):
                os.remove(tmp)
            detail = getattr(e, "stderr", b"") or b""
            print(f"[pieces] try {attempt + 1}: {type(e).__name__}: {str(e)[:160]} "
                  f"{detail[-160:].decode('utf-8', 'replace') if isinstance(detail, bytes) else ''}", flush=True)
    raise RuntimeError(f"shot failed after {PIECE_TRIES} tries: {last}")


def _image_wh(path: str) -> Tuple[int, int]:
    from PIL import Image
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return _probe_wh(path)


def frames_of(path: str) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=120).stdout
    try:
        return int(out.strip().split("\n")[0].strip(","))
    except ValueError:
        return 0


def _job(args: tuple) -> Tuple[str, float]:
    spec, out, threads = args
    t = time.time()
    render_one(spec, out, threads)
    return out, time.time() - t


# --------------------------------------------------------------------------- #
# Many shots
# --------------------------------------------------------------------------- #
def _workers() -> Tuple[int, int]:
    """(processes, ffmpeg threads each): STORM_PIECES_WORKERS, else a third of the machine."""
    cpus = os.cpu_count() or 2
    try:
        want = int(os.environ.get("STORM_PIECES_WORKERS") or 0)
    except ValueError:
        want = 0
    procs = want or max(2, cpus // 3)
    return procs, max(1, min(4, cpus // max(1, procs)))


def localise(url: str, work: str) -> str:
    """A web link's file on this disk (one download per link); a local path as it is."""
    if not url.startswith(("http://", "https://")):
        return url
    folder = os.path.join(work, "sdsources")
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1][:6] or ".mp4"
    path = os.path.join(folder, hashlib.sha1(url.encode()).hexdigest()[:20] + ext)
    if not (os.path.isfile(path) and os.path.getsize(path) > 0):
        tmp = path + ".part"
        last = None
        for _ in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "thumbgenius-worker"})
                with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                os.replace(tmp, path)
                last = None
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2)
        if last is not None:
            raise RuntimeError(f"could not fetch a shot's source: {type(last).__name__}")
    return path


def _r2_key(scope: str, key: str) -> str:
    return f"sdpieces/{scope}/{key}.mp4"


def cache_get(scope: str, key: str, out: str) -> bool:
    """A shot an earlier render of this project drew: from R2 (a pod starts with an empty disk)."""
    if not scope or not getattr(config, "STORM_PIECES_R2", False):
        return False
    from . import r2
    try:
        if not r2.enabled():
            return False
        data = r2.get_bytes(_r2_key(scope, key), timeout=120)
    except Exception:  # noqa: BLE001 - drawn again
        return False
    if not data:
        return False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".r2", "wb") as f:
        f.write(data)
    os.replace(out + ".r2", out)
    return True


def cache_put(scope: str, key: str, path: str) -> None:
    if not scope or not getattr(config, "STORM_PIECES_R2", False):
        return
    from . import r2
    try:
        if r2.enabled():
            r2.upload(path, _r2_key(scope, key), content_type="video/mp4", deadline=time.time() + 300)
    except Exception as e:  # noqa: BLE001 - only the next re-render pays for it
        print(f"[pieces] not kept: {type(e).__name__}: {str(e)[:120]}", flush=True)


def prepare_logo(doc: dict, work: str) -> Tuple[str, str]:
    logo = (doc.get("stormDesk") or {}).get("logo") or {}
    path = ""
    if logo.get("url"):
        try:
            path = localise(str(logo["url"]), work)
        except Exception as e:  # noqa: BLE001 - the name stands in
            print(f"[pieces] logo not fetched: {type(e).__name__}", flush=True)
    return path, str(logo.get("text") or "")


LAST_RUN: Dict[str, int] = {}


def render_pieces(doc: dict, work: str, on_progress: Optional[Callable[[int, int, int], None]] = None,
                  scope: str = "") -> List[str]:
    """
    Every shot's file, in order: on disk or in R2 when its spec has not changed, else drawn now. A shot that keeps failing
    fails the render (RuntimeError names it), so a job never sits at a percentage. Returns the files.
    on_progress(done, total, reused).
    """
    folder = os.path.join(work, "sdpieces")
    os.makedirs(folder, exist_ok=True)
    specs = build_specs(doc)
    jobs, paths, reused = [], [], 0
    procs, threads = _workers()
    for sp in specs:
        sp = dict(sp)
        key = spec_key(sp)                       # named by what it shows, whatever disk or link its source is on now
        out = os.path.join(folder, key + ".mp4")
        paths.append(out)
        if os.path.isfile(out) and os.path.getsize(out) > 1000:
            reused += 1
            continue
        if cache_get(scope, key, out):
            reused += 1
            continue
        if not any(j[1] == out for j in jobs):
            # Only a shot being drawn needs its source on this disk.
            if sp["kind"] != "animation":
                sp["src"] = localise(sp["src"], work)
            if sp.get("dissolve"):
                sp["dissolve"] = {**sp["dissolve"], "src": localise(sp["dissolve"]["src"], work)}
            jobs.append((sp, out, threads))
    total = len(specs)
    LAST_RUN.update(drawn=len(jobs), reused=reused)
    if on_progress:
        on_progress(reused, total, reused)
    if not jobs:
        return paths
    logo, text = prepare_logo(doc, work)
    done = reused
    print(f"[pieces] {len(jobs)} to draw, {reused} reused, {procs} processes x {threads} threads", flush=True)
    with ProcessPoolExecutor(procs, mp_context=get_context("spawn"), initializer=_worker_init, initargs=(logo, text)) as ex:
        futs = {ex.submit(_job, j): j for j in jobs}
        for f in as_completed(futs):
            j = futs[f]
            try:
                out, _secs = f.result(timeout=PIECE_TIMEOUT * PIECE_TRIES)
            except Exception as e:
                for other in futs:
                    other.cancel()
                raise RuntimeError(f"shot {os.path.basename(j[1])} from {os.path.basename(j[0]['src'])}: {e}") from e
            done += 1
            cache_put(scope, os.path.splitext(os.path.basename(out))[0], out)
            if on_progress:
                on_progress(done, total, reused)
    return paths


def join(paths: List[str], out: str, work: str) -> str:
    """The shots end to end without another encode: every shot left render_one with one set of encoder settings."""
    lst = os.path.join(work, "sdpieces", "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines("file '" + os.path.abspath(p).replace("\\", "/").replace("'", "'\\''") + "'\n" for p in paths)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v", "-c:v", "copy",
                    "-video_track_timescale", str(FPS_DEFAULT * 512), "-movflags", "+faststart", out],
                   check=True, timeout=3600, capture_output=True)
    return out


# --------------------------------------------------------------------------- #
# The base sound: narration, music, the looks' SFX
# --------------------------------------------------------------------------- #
def _decode(src: str, af: str, seconds: Optional[float] = None, start: float = 0.0):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if seconds:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-vn", "-af", af, "-f", "s16le", "-ac", "2", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=1800).stdout
    return np.frombuffer(raw, np.int16).reshape(-1, 2).astype(np.float32) / 32768


def music_sections(doc: dict) -> List[dict]:
    """[{"url", "at" seconds, "offset" seconds into the track}], from doc.stormDesk.music (several of the owner's tracks,
    crossfaded), else the one track the job gave (doc.bgm / doc.music)."""
    d = (doc.get("stormDesk") or {}).get("music")
    if isinstance(d, list) and d:
        return [{"url": str(x["url"]), "at": float(x.get("at") or 0.0), "offset": float(x.get("offset") or 0.0)}
                for x in d if isinstance(x, dict) and x.get("url")]
    for key in ("bgm", "music"):
        m = doc.get(key)
        if isinstance(m, dict) and m.get("url"):
            return [{"url": str(m["url"]), "at": 0.0, "offset": float(m.get("startFrom") or m.get("offset") or 0.0)}]
    return []


def speech_mask(spans: List[Tuple[float, float]], n: int):
    import numpy as np
    duck = np.zeros(n, np.float32)
    for a, b in spans:
        duck[int(max(0.0, a) * SR):int(b * SR)] = 1.0
    k = int(0.35 * SR)
    # A running mean: the kit's 0.35 s swell, without a convolution over 30 million samples.
    c = np.cumsum(np.concatenate([[0.0], duck]))
    out = np.zeros(n, np.float32)
    half = k // 2
    idx0 = np.clip(np.arange(n) - half, 0, n)
    idx1 = np.clip(np.arange(n) + half, 0, n)
    out[:] = (c[idx1] - c[idx0]) / np.maximum(1, idx1 - idx0)
    return out


def music_bed(doc: dict, total: float, work: str, spans: List[Tuple[float, float]], voice_lufs: float = VOICE_LUFS):
    """The owner's music on the video's clock, MUSIC_UNDER_VOICE_DB under the voice and x0.8 while it speaks, 2 s in, 4 s out,
    3 s crossfades between sections. None without music."""
    import numpy as np
    secs = music_sections(doc)
    if not secs:
        return None
    n = int(round(total * SR))
    bed = np.zeros((n, 2), np.float32)
    target = voice_lufs - MUSIC_UNDER_VOICE_DB
    for k, sc in enumerate(secs):
        a = sc["at"]
        b = secs[k + 1]["at"] + 1.5 if k + 1 < len(secs) else total
        a0 = max(0.0, a - (1.5 if k else 0.0))
        src = localise(sc["url"], work)
        x = _decode(src, f"loudnorm=I={target}:TP=-14:LRA=11", b - a0 + 0.1, sc["offset"])
        # A track shorter than its section loops: never a bed that stops half way.
        need = int(round((b - a0) * SR))
        if 0 < len(x) < need:
            x = np.concatenate([x] * (need // len(x) + 1))
        o = int(round(a0 * SR))
        m = min(len(x), n - o, need)
        if m <= 0:
            continue
        env = np.ones(m, np.float32)
        fi, fo = int((3.0 if k else MUSIC_FADE_IN) * SR), int((3.0 if k + 1 < len(secs) else MUSIC_FADE_OUT) * SR)
        env[:min(fi, m)] = np.linspace(0, 1, min(fi, m))
        tail = min(fo, m)
        env[m - tail:] = np.minimum(env[m - tail:], np.linspace(1, 0, tail))
        bed[o:o + m] += x[:m] * env[:, None]
    duck = speech_mask(spans, n)
    return bed * (1.0 - (1.0 - MUSIC_DUCK) * duck)[:, None]


# Which sound goes with which look (looks/mix.py): file, seconds used, extra dB.
SFX = {"stat": ("hit-deep.mp3", 1.6, -6.0), "place": ("record-beep.mp3", 0.16, -6.0), "stamp": ("record-beep.mp3", 0.16, -3.0),
       "title": ("boom-soft.mp3", 1.7, 0.0), "type": ("keys-type.mp3", 0.8, 0.0), "map": ("map-whoosh.mp3", 1.5, -3.0),
       "pin": ("pin-drop.mp3", 0.45, 0.0), "pin2": ("keys-type.mp3", 0.6, -7.0), "mapstat": ("hit-deep.mp3", 1.6, -6.0)}


def sfx_cues(tl: Optional[dict]) -> List[Tuple[float, str, float, float]]:
    """(video seconds, file, seconds, dB) for the looks timeline (looks/mix.py), at the owner's level."""
    tl = tl or {}
    out: List[Tuple[float, str, float, float]] = []

    def add(t: float, key: str) -> None:
        f, trim, g = SFX[key]
        out.append((max(0.0, float(t)), f, trim, LEVEL_DB + g))
    for a, *_r in tl.get("type") or []:
        add(a, "type")
    for a, *_r in tl.get("stats") or []:
        add(a - 0.05, "stat")
    for a, *_r in tl.get("places") or []:
        add(a, "place")
    for a, *_r in tl.get("stamps") or []:
        add(a, "stamp")
    for a, *_r in tl.get("graphs") or []:
        add(a, "place")
    for a, *_r in tl.get("titles") or []:
        add(a, "title")
    for m in tl.get("maps") or []:
        add(m["t0"] - 0.08, "map")
        if m.get("pin", 1e9) < m["t1"]:
            add(m["pin"], "pin")
            add(m["pin"] + 0.1, "pin2")
        if m.get("stat"):
            add(m["pin"] + 0.5, "mapstat")
    return sorted(out)


def sfx_dir() -> str:
    return os.path.join(os.environ.get("REMOTION_DIR") or
                        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remotion"), "public", "sfx")


def sfx_track(cues: List[Tuple[float, str, float, float]], n: int):
    import numpy as np
    track = np.zeros((n, 2), np.float32)
    cache: Dict[tuple, Any] = {}
    for t, f, trim, db in cues:
        k = (f, trim)
        if k not in cache:
            p = os.path.join(sfx_dir(), f)
            if not os.path.isfile(p):
                cache[k] = None
                continue
            cache[k] = _decode(p, f"afade=t=out:st={max(0.0, trim - 0.12):.2f}:d=0.12,aresample={SR}", trim)
        x = cache[k]
        if x is None or not len(x):
            continue
        o = int(t * SR)
        m = min(len(x), n - o)
        if m > 0:
            track[o:o + m] += x[:m] * (10 ** (db / 20.0))
    return track


def base_sound(doc: dict, total: float, work: str, spans: List[Tuple[float, float]]) -> Tuple[str, dict]:
    """narration (loudnormed to -16, as the kit) + the music + the looks' SFX -> a wav; the report."""
    import numpy as np
    import wave
    n = int(round(total * SR))
    url = str((doc.get("audio") or {}).get("url") or "")
    rep: Dict[str, Any] = {}
    voice = _decode(localise(url, work), f"loudnorm=I={VOICE_LUFS}:TP=-2:LRA=9") if url else np.zeros((0, 2), np.float32)
    mix = np.zeros((n, 2), np.float32)
    m = min(n, len(voice))
    mix[:m] += voice[:m]
    bed = music_bed(doc, total, work, spans)
    if bed is not None:
        mix += bed
        rep["musicSections"] = len(music_sections(doc))
        rep["musicUnderVoiceDb"] = MUSIC_UNDER_VOICE_DB
    cues = sfx_cues((doc.get("stormDesk") or {}).get("looks"))
    if cues:
        mix += sfx_track(cues, n)
        rep["sfxCues"] = len(cues)
    path = os.path.join(work, "sd_base.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    return path, rep


def draw(doc: dict, out_path: str, work: str, report: Optional[Callable[[str, int], None]] = None, scope: str = "",
         prerender: Optional[Any] = None) -> dict:
    """The whole video: shots, join, base sound -> out_path (stormdesk.after_render masters it). Returns the timings."""
    from .stormdesk import word_spans
    t0 = time.time()
    if prerender is not None:
        prerender.wait()                         # the shots already being drawn during the checks
    fps = int(doc.get("fps") or FPS_DEFAULT)
    last = [-1]

    def on(done: int, total: int, reused: int) -> None:
        pct = 70 + int(16 * done / max(1, total))
        if report and (pct != last[0] or done == total):
            last[0] = pct
            report(f"Rendering shots {done}/{total}" + (f" ({reused} unchanged)" if reused else ""), pct)
            print(f"[pieces] {done}/{total} shots ({int(time.time() - t0)} s)", flush=True)
    paths = render_pieces(doc, work, on, scope)
    t1 = time.time()
    if report:
        report("Joining the shots", 86)
    picture = os.path.join(work, "sd_picture.mp4")
    join(paths, picture, work)
    t2 = time.time()
    total = int(doc.get("durationInFrames") or 0) / float(fps)
    if report:
        report("Mixing the sound", 88)
    wav, rep = base_sound(doc, total, work, word_spans(doc))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", picture, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "320k", "-ar", str(SR), "-movflags", "+faststart", out_path],
                   check=True, timeout=1800, capture_output=True)
    for f in (picture, wav):
        try:
            os.remove(f)
        except OSError:
            pass
    t3 = time.time()
    rep.update({"engine": "pieces", "shots": len(paths), "shotsDrawn": LAST_RUN.get("drawn"), "shotsReused": LAST_RUN.get("reused"),
                "shotsSeconds": round(t1 - t0, 1), "joinSeconds": round(t2 - t1, 1),
                "soundSeconds": round(t3 - t2, 1)})
    return rep


class Prerender:
    """The shots drawn in the background while the checks run (owner 2026-11-05): render_pieces in a thread; draw() waits for
    it and draws what the checks changed afterwards, since a changed shot has another name."""

    def __init__(self, doc: dict, work: str, scope: str = ""):
        import copy
        import threading
        self.error: Optional[str] = None
        self.started = time.time()
        snap = copy.deepcopy(doc)

        def run() -> None:
            try:
                render_pieces(snap, work, None, scope)
            except Exception as e:  # noqa: BLE001 - the real render will say
                self.error = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"[pieces] during the checks: {self.error}", flush=True)
        self.thread = threading.Thread(target=run, daemon=True, name="sd-prerender")
        self.thread.start()

    def wait(self) -> None:
        self.thread.join()
