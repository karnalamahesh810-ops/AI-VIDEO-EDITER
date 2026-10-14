"""
The celeb style, built the way the references are built (docs/style-refs/celeb-elements.md):

  cold open (one clip, own audio) -> hook narration over a fast laugh montage with pops / speed lines / an
  arrow -> white flash -> [bridge sentence over the film's own footage (+ title card when the film changes),
  the clip's picture leading its sound] -> clip with its own audio, captions, name label + circle, pointer,
  pops on swears and laughs -> white flash -> ... -> outro line.

Script blocks come from script.parse(): narr, clip, montage ([MONTAGE: id@a-b ...]) and flash ([FLASH]).
Sources are local files of the clips' videos with whisper words and shot cuts (`Source`).
Output: base video (shots + flashes), the mix (clips and narration at -20 LUFS, the reference's level), then
every element composited frame by frame (fx.composite).
"""
import json
import math
import os
import random
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import faces as F
from . import fx
from .compose import duration, lufs

W, H, FPS = fx.W, fx.H, fx.FPS
TARGET_LUFS = -20.0          # refs: whole video -19.9 LUFS, narration -20.6..-22, clips -18..-23
MUSIC_UNDER_VOICE = -13.0    # dB under the narration (refs: -36..-39 dBFS gaps vs voice p50 -24)
MUSIC_IN_CLIP = -29.0        # dB under the narration inside clips (refs: floor ~-50 dBFS -> music out)
J_LEAD = 1.2                 # the next clip's picture under the end of its bridge
FLASH = 0.2
SWEAR = re.compile(r"(?i)\b(mother)?f(u|\*)[c*]?[k*]\w*|\bsh[i*]t\w*|\bbitch\w*")
UNCENSORED = re.compile(r"(?i)fuck|shit|bitch")


@dataclass
class Source:
    id: str
    path: str
    words: List[dict]
    cuts: List[float]
    dur: float = 0.0

    def words_in(self, a: float, b: float) -> List[dict]:
        return [w for w in self.words if a - 0.05 <= w["start"] < b - 0.05]


@dataclass
class Shot:
    kind: str                     # clip | broll | montage | flash
    at: float
    dur: float
    src: str = ""
    src_in: float = 0.0


@dataclass
class Sound:
    kind: str                     # narr | clip | sfx | bleep
    at: float
    path: str = ""
    src_in: float = 0.0
    dur: float = 0.0
    mutes: List[Tuple[float, float]] = field(default_factory=list)   # clip-relative spans to bleep


@dataclass
class Mark:
    """An element waiting for its face: kind name|pop|point|speed|arrow|title, at output time `at`."""
    kind: str
    at: float
    dur: float
    text: str = ""
    hint: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Timeline:
    shots: List[Shot] = field(default_factory=list)
    sounds: List[Sound] = field(default_factory=list)
    marks: List[Mark] = field(default_factory=list)
    captions: List[Tuple[float, float, str]] = field(default_factory=list)
    clip_spans: List[Tuple[float, float]] = field(default_factory=list)
    narr_spans: List[Tuple[float, float]] = field(default_factory=list)
    cuts: List[float] = field(default_factory=list)       # every picture change on the output clock
    log: List[dict] = field(default_factory=list)          # rights log: source, in, out
    total: float = 0.0


# ------------------------------------------------------------------ helpers
def spec(raw: str) -> Tuple[str, float, str]:
    """'"TEXT"@3.2@left' / 'NAME@0.3@center' / '@0@right' -> (text, seconds, hint)."""
    parts = raw.split("@")
    text = parts[0].strip().strip('"').strip("“”")
    rest = [x.strip() for x in parts[1:] if x.strip()]
    nums = [x for x in rest if re.fullmatch(r"-?\d+(\.\d+)?", x)]
    t = float(nums[0]) if nums else 0.0
    hint = next((x for x in rest if x not in nums), "")
    return text, t, hint


def starred(word: str) -> str:
    """Caption / pop spelling of a swear: F***, F***ING, MOTHERF***ER, SH**."""
    w = word
    w = re.sub(r"(?i)fuck", "F***", w)
    w = re.sub(r"(?i)shit", "SH**", w)
    w = re.sub(r"(?i)bitch", "BIT**", w)
    return w


def caption_phrases(words: Sequence[dict], a: float, b: float, cuts: Sequence[float], offset: float,
                    max_words: int = 5) -> List[Tuple[float, float, str]]:
    """Clip speech as caption phrases (1-5 words), broken at punctuation, pauses and camera cuts; instant."""
    ws = [w for w in words if a - 0.05 <= w["start"] < b - 0.1 and str(w["text"]).strip()]
    out, cur = [], []

    def flush():
        if cur:
            text = " ".join(starred(str(w["text"]).strip()) for w in cur)
            out.append([cur[0]["start"], cur[-1]["end"], re.sub(r"(\w) -(\w)", r"\1-\2", text)])

    for w in ws:
        cut_between = cur and any(cur[-1]["start"] < c <= w["start"] + 0.05 for c in cuts)
        if cur and (w["start"] - cur[-1]["end"] > 0.5 or len(cur) >= max_words or cut_between):
            flush()
            cur = []
        cur.append(w)
        if str(w["text"]).strip()[-1:] in ".?!" and len(cur) >= 1:
            flush()
            cur = []
    flush()
    res = []
    for k, (s, e, t) in enumerate(out):
        nxt = out[k + 1][0] if k + 1 < len(out) else b
        e = min(max(e + 0.25, s + 0.6), nxt, b)              # readable: at least 0.6 s, never past the next
        res.append((round(s - a + offset, 3), round(e - a + offset, 3), t.upper().strip(",")))
    return res


def content_crop(path: str, a: float, b: float, _cache: Dict = {}) -> str:
    """ffmpeg crop for a letterboxed range (black bars measured on 3 frames), '' when full frame."""
    key = (path, round(a, 1), round(b, 1))
    if key in _cache:
        return _cache[key]
    import numpy as np
    tops, bots, w0, h0 = [], [], 0, 0
    for t in (a + (b - a) * k for k in (0.2, 0.5, 0.8)):
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf",
                            "scale=480:-2", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
        if not p.stdout:
            continue
        h0 = len(p.stdout) // 480
        g = np.frombuffer(p.stdout[:480 * h0], np.uint8).reshape(h0, 480)
        rows = g.mean(axis=1)
        lit = np.nonzero(rows > 18)[0]
        if len(lit):
            tops.append(lit[0])
            bots.append(lit[-1] + 1)
    res = ""
    if tops and h0:
        top, bot = min(tops), max(bots)
        if top > h0 * 0.02 or bot < h0 * 0.98:
            res = f"crop=iw:ih*{(bot - top) / h0:.4f}:0:ih*{top / h0:.4f}"
    _cache[key] = res
    return res


# ------------------------------------------------------------------ the timeline
def build(blocks: Sequence, narr_paths: Sequence[str], sources: Dict[str, Source], *, seed: int = 7) -> Timeline:
    tl = Timeline()
    rnd = random.Random(seed)
    t = 0.0
    used: Dict[str, List[Tuple[float, float]]] = {}
    for b in blocks:
        if b.kind == "clip" and b.video_id in sources:
            used.setdefault(b.video_id, []).append((b.start - 0.5, b.end + 0.5))
    narr_k = 0
    montage: List[str] = []
    film_now = ""
    cursor: Dict[str, float] = {}
    led = set()

    def add_flash():
        nonlocal t
        tl.shots.append(Shot("flash", t, FLASH))
        tl.sounds.append(Sound("sfx", max(0.0, t - 0.03)))
        tl.cuts.append(t)
        t += FLASH
        tl.cuts.append(t)

    def broll(src: Source, need: float) -> List[Tuple[float, float]]:
        """Shots of the clip's own film footage outside every used clip, within single source shots."""
        cuts = [0.0] + src.cuts + [src.dur]
        spans = []
        for x, y in zip(cuts, cuts[1:]):
            x, y = x + 0.25, y - 0.25
            if y - x < 1.0 or x < 3.0 or y > src.dur - 6.0:
                continue
            if any(not (y <= u0 or x >= u1) for u0, u1 in used.get(src.id, [])):
                continue
            spans.append((x, y))
        rnd.shuffle(spans)
        out, left = [], need
        for x, y in spans * 3:
            if left <= 0.05:
                break
            d = min(left if left < 3.2 else rnd.uniform(1.6, 2.6), y - x)
            if left - d < 0.9 and left - d > 0.05:
                d = left if left <= y - x else d - 0.9
            start = cursor.get(f"{src.id}{x}", x)
            if start + d > y:
                start = x
            out.append((start, d))
            cursor[f"{src.id}{x}"] = start + d
            left -= d
        if left > 0.05 and out:                      # stretch the last one if spans ran short
            s0, d0 = out[-1]
            out[-1] = (s0, d0 + left)
        return out

    for i, b in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if b.kind == "montage":
            montage = list(b.shots)
            continue
        if b.kind == "flash":
            add_flash()
            continue
        if b.kind == "narr":
            path = narr_paths[narr_k]
            narr_k += 1
            dur = duration(path)
            tl.sounds.append(Sound("narr", t, path, 0.0, dur))
            tl.narr_spans.append((t, t + dur))
            clip_next = nxt if nxt is not None and nxt.kind == "clip" and nxt.video_id in sources else None
            lead = min(J_LEAD, dur * 0.35) if clip_next else 0.0
            fill = dur - lead
            at = t
            if clip_next and clip_next.film and clip_next.film != film_now:
                title, sub, year = (list(map(str.strip, clip_next.film.split("/"))) + ["", "", ""])[:3]
                tl.marks.append(Mark("title", t + 0.3, min(2.6, max(1.8, dur - 0.4)), title,
                                     extra={"subtitle": sub, "year": year}))
                film_now = clip_next.film
            if montage:
                k = 0
                while fill - (at - t) > 0.05:
                    sid, rng, opts = _montage_item(montage[k % len(montage)])
                    a0, a1 = rng
                    d = min(a1 - a0, fill - (at - t))
                    if fill - (at - t) - d < 0.35:
                        d = fill - (at - t)
                    tl.shots.append(Shot("montage", at, d, sources[sid].path, a0))
                    tl.cuts.append(at)
                    for o in opts:
                        if o.startswith("pop="):
                            text, _, hint = spec(o[4:])
                            tl.marks.append(Mark("pop", at, d, text, hint or "laughing"))
                        elif o in ("speed", "arrow"):
                            tl.marks.append(Mark(o, at, min(d, 1.0), hint="laughing"))
                    at += d
                    k += 1
                montage = []
            else:
                src = sources.get(clip_next.video_id) if clip_next else None
                if src is None:                      # the outro: footage from every source
                    pool = list(sources.values())
                    pieces = []
                    left = fill
                    while left > 0.05:
                        s = pool[len(pieces) % len(pool)]
                        got = broll(s, min(left, 2.2))
                        if not got:
                            break
                        pieces += [(s, a, d) for a, d in got]
                        left -= sum(d for _, d in got)
                else:
                    pieces = [(src, a, d) for a, d in broll(src, fill)]
                for s, a, d in pieces:
                    tl.shots.append(Shot("broll", at, d, s.path, a))
                    tl.cuts.append(at)
                    at += d
            if clip_next and lead > 0:
                src = sources[clip_next.video_id]
                tl.shots.append(Shot("clip", t + fill, lead + (clip_next.end - clip_next.start), src.path,
                                     clip_next.start - lead))
                tl.cuts.append(t + fill)
                led.add(i + 1)
            t += dur
            continue
        if b.kind != "clip" or b.video_id not in sources:
            continue
        src = sources[b.video_id]
        length = b.end - b.start
        if i not in led:
            tl.shots.append(Shot("clip", t, length, src.path, b.start))
            tl.cuts.append(t)
        tl.cuts += [t + c - b.start for c in src.cuts if b.start < c < b.end]
        mutes = [(w["start"] - b.start - 0.03, w["end"] - b.start + 0.03) for w in src.words_in(b.start, b.end)
                 if UNCENSORED.search(str(w["text"]))]
        tl.sounds.append(Sound("clip", t, src.path, b.start, length, mutes=mutes))
        from . import speakers                       # the reference colours captions by speaker
        tl.captions += speakers.colour_phrases(src.path, b.start, caption_phrases(src.words, b.start, b.end,
                                                                                  src.cuts, t), t, src.cuts)
        tl.clip_spans.append((t, t + length))
        tl.log.append({"video": b.video_id, "url": f"https://www.youtube.com/watch?v={b.video_id}",
                       "in": round(b.start, 2), "out": round(b.end, 2), "at": round(t, 2)})
        popped = []
        for raw in b.names:
            text, s, hint = spec(raw)
            tl.marks.append(Mark("name", t + s, 1.9, text, hint))
        for raw in b.points:
            _, s, hint = spec(raw)
            tl.marks.append(Mark("point", t + s, 1.6, "", hint))
        for raw in b.pops:
            text, s, hint = spec(raw)
            tl.marks.append(Mark("pop", t + s, 1.4, text, hint))
            popped.append(t + s)
        for w in src.words_in(b.start, b.end):           # the references pop every swear, starred
            if SWEAR.search(str(w["text"])):
                at = t + w["start"] - b.start
                if all(abs(at - p) > 2.5 for p in popped):
                    word = re.sub(r"[^\w*']", "", starred(str(w["text"]))).upper()
                    tl.marks.append(Mark("pop", at, 1.3, f'"{word}"', "speaker"))
                    popped.append(at)
        t += length
        if nxt is not None and nxt.kind == "narr":
            add_flash()
    tl.total = round(t, 3)
    tl.shots.sort(key=lambda s: s.at)
    tl.cuts = sorted(set(round(c, 3) for c in tl.cuts))
    return tl


def _montage_item(item: str) -> Tuple[str, Tuple[float, float], List[str]]:
    """'XG_CimbpVMQ@42.3-43.3 pop="HA HA HA"@left speed' -> (id, (a, b), options)."""
    head, _, rest = item.partition(" ")
    sid, _, rng = head.partition("@")
    a, _, b = rng.partition("-")
    opts = re.findall(r'pop="[^"]*"(?:@\w+)?|speed|arrow', rest)
    return sid, (float(a), float(b)), opts


# ------------------------------------------------------------------ render: picture
def render_shot(s: Shot, dst: str) -> str:
    n = max(1, round((s.at + s.dur) * FPS) - round(s.at * FPS))
    if s.kind == "flash":
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=white:s={W}x{H}:r={FPS}"]
        vf = "format=yuv420p"
    else:
        crop = content_crop(s.src, s.src_in, s.src_in + s.dur)
        vf = (crop + "," if crop else "") + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}," \
                                            f"fps={FPS},setsar=1,format=yuv420p"
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{s.src_in:.3f}", "-i", s.src]
    subprocess.run(cmd + ["-vf", vf, "-an", "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast",
                          "-crf", "16", "-pix_fmt", "yuv420p", dst], check=True, timeout=600)
    return dst


def render_base(tl: Timeline, work: str) -> str:
    os.makedirs(work, exist_ok=True)
    paths = [os.path.join(work, f"shot_{k:03d}.mp4") for k in range(len(tl.shots))]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda kv: render_shot(*kv), zip(tl.shots, paths)))
    with open(os.path.join(work, "shots.txt"), "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{os.path.basename(p)}'\n" for p in paths)
    base = os.path.join(work, "base.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "shots.txt", "-c", "copy",
                    "base.mp4"], cwd=work, check=True, timeout=600)
    return base


# ------------------------------------------------------------------ render: sound
def _gain_expr(points: Sequence[Tuple[float, float]]) -> str:
    expr = f"{points[-1][1]:.4f}"
    for (x0, g0), (x1, g1) in reversed(list(zip(points, points[1:]))):
        if x1 - x0 < 1e-3:
            continue
        expr = f"if(lt(t,{x1:.3f}),{g0:.4f}+({g1:.4f}-{g0:.4f})*(t-{x0:.3f})/{x1 - x0:.3f},{expr})"
    return expr


def music_points(tl: Timeline) -> List[Tuple[float, float]]:
    hi, lo = 10 ** (MUSIC_UNDER_VOICE / 20), 10 ** (MUSIC_IN_CLIP / 20)
    pts = [(0.0, lo)]
    for a, b in tl.clip_spans:
        pts += [(max(0.0, a - 0.3), hi), (a, lo), (b, lo), (b + 0.5, hi)]
    pts.append((tl.total, hi))
    pts.sort()
    out = []
    for x, g in pts:
        if out and x <= out[-1][0] + 1e-3:
            out[-1] = (out[-1][0], g)
            continue
        out.append((x, g))
    return out


def mix(tl: Timeline, work: str, music: str = "", sfx: str = "") -> str:
    inputs, chains, labels = [], [], []
    n = 0
    for s in tl.sounds:
        if s.kind == "sfx":
            if not (sfx and os.path.isfile(sfx)):
                continue
            inputs += ["-i", sfx]
            have = lufs(sfx) or -20.0
            g = TARGET_LUFS + 2.0 - have
            ms = int(round(s.at * 1000))
            chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={g:.2f}dB,adelay={ms}|{ms}[a{n}]")
            labels.append(f"[a{n}]")
        else:
            inputs += ["-ss", f"{s.src_in:.3f}", "-t", f"{s.dur:.3f}", "-i", s.path]
            have = lufs(s.path, s.src_in, s.dur)
            g = max(-15.0, min(15.0, TARGET_LUFS - have)) if have is not None else 0.0
            f = ""
            if s.kind == "clip":
                f = f",afade=t=in:d=0.06,afade=t=out:st={max(0.0, s.dur - 0.06):.3f}:d=0.06"
                for a, b in s.mutes:
                    f += f",volume=0:enable='between(t,{max(0, a):.3f},{b:.3f})'"
            ms = int(round(s.at * 1000))
            chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                          f"volume={g:.2f}dB{f},adelay={ms}|{ms}[a{n}]")
            labels.append(f"[a{n}]")
            for a, b in s.mutes:                       # the bleep the references' sources carry
                n += 1
                inputs += ["-f", "lavfi", "-t", f"{b - a:.3f}", "-i", "sine=frequency=1000:sample_rate=48000"]
                bm = int(round((s.at + max(0.0, a)) * 1000))
                chains.append(f"[{n}:a]aformat=channel_layouts=stereo,volume=0.18,adelay={bm}|{bm}[a{n}]")
                labels.append(f"[a{n}]")
        n += 1
    if music and os.path.isfile(music):
        have = lufs(music, 0, 60) or -27.0
        inputs += ["-stream_loop", "-1", "-i", music]
        base_gain = TARGET_LUFS - have
        chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{tl.total:.3f},"
                      f"volume={base_gain:.2f}dB,volume='{_gain_expr(music_points(tl))}':eval=frame,"
                      f"afade=t=out:st={max(0.0, tl.total - 2):.3f}:d=2[mu]")
        labels.append("[mu]")
    labels = [l for l in labels if l]
    graph = ";".join(chains) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest," \
                               f"atrim=0:{tl.total:.3f},alimiter=limit=0.89:level=false[out]"
    gpath = os.path.join(work, "mix_graph.txt")
    with open(gpath, "w", encoding="utf-8") as fh:
        fh.write(graph)
    dst = os.path.join(work, "mix.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-/filter_complex", gpath, "-map", "[out]", "-ar", "48000",
                    "-ac", "2", dst], check=True, timeout=1800)
    return dst


# ------------------------------------------------------------------ elements
class Caption(fx.Element):
    """The clip caption: yellow comic caps on an opaque black box (radius 1.7 %), bottom centre; instant."""

    def __init__(self, start: float, dur: float, text: str, colour: tuple = fx.CAPTION_YELLOW):
        super().__init__("caption", start, dur)
        cap = int(H * 0.0375)               # ref: 27 px of 720, Komika, no stroke
        t = fx.text_image(text, cap, colour, 0, colour)
        pad = int(H * 0.038)
        bh = int(H * 0.108)
        box = fx.Image.new("RGBA", (t.width + 2 * pad, bh), (0, 0, 0, 0))
        fx.ImageDraw.Draw(box).rounded_rectangle([0, 0, box.width - 1, bh - 1], radius=int(H * 0.017), fill=(0, 0, 0, 255))
        box.alpha_composite(t, (pad, (bh - t.height) // 2 + 1))
        self._im = box
        self._xy = ((W - box.width) // 2, int(H * 0.986) - bh)

    def draw(self, t):
        return self._im, self._xy[0], self._xy[1]


def _next_cut(cuts: Sequence[float], t: float) -> float:
    return next((c for c in cuts if c > t + 0.05), 1e9)


def elements(tl: Timeline, base: str, posters: Dict[str, str]) -> List[fx.Element]:
    """Marks -> positioned elements: faces looked up on the rendered base at each mark's frame."""
    out: List[fx.Element] = [Caption(c[0], c[1] - c[0], c[2], *(c[3:4] or [])) for c in tl.captions if c[1] - c[0] > 0.1]
    rnd = random.Random(11)

    def caption_at(t0: float, t1: float) -> bool:
        return any(c[0] < t1 and c[1] > t0 for c in tl.captions)

    for m in tl.marks:
        end = min(m.at + m.dur, _next_cut(tl.cuts, m.at))        # elements leave on the next camera cut
        dur = end - m.at
        if m.kind != "title" and dur < 0.5:                        # too close to a cut to read: leave it out
            continue
        if m.kind == "title":
            p = posters.get(m.text + " " + m.extra.get("subtitle", ""), "")
            if p:
                out.append(fx.TitleCard("title", m.at, m.dur, poster=p, title=m.text,
                                        subtitle=m.extra.get("subtitle", ""), year=m.extra.get("year", "")))
            continue
        hint = m.hint if m.hint in ("left", "right", "center") else "largest"
        if F.local_available():                       # free, frame-by-frame: the element follows the head
            track = F.track(base, m.at, m.at + dur, hint)
        else:                                         # fallback: one vision call, a still position
            one = F.pick(F.faces(base, m.at + 0.12), m.hint)
            track = [one] if one else None
        if not track or not any(track):
            if m.kind in ("name", "point", "arrow"):  # an element on a person needs the person: leave it out
                continue
            track = None
        if m.kind == "name":
            out.append(fx.Circle("circle", m.at + 0.05, dur - 0.05, track=track[1:] if track else None))
            y = 0.80 if caption_at(m.at, m.at + dur) else 0.905
            out.append(fx.NameLabel("name", m.at, dur, text=m.text, y=y, track=track))
        elif m.kind == "pop":
            out.append(fx.Pop("pop", m.at, dur, text=m.text if m.text.startswith('"') else f'"{m.text}"',
                              tilt=rnd.uniform(-5, 5), track=track))
        elif m.kind == "point":
            out.append(fx.Pointer("point", m.at, min(dur, 1.6), track=track))
        elif m.kind == "speed":
            out.append(fx.SpeedLines("speed", m.at, dur, seed=int(m.at * 10), track=track))
        elif m.kind == "arrow":
            out.append(fx.Arrow3D("arrow", m.at, min(dur, 1.0), track=track))
    return out
