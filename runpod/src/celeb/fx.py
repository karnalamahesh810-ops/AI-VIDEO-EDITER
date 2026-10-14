"""
The Celebs Goat on-screen elements, drawn to match the measured references (docs/style-refs/celeb-elements.md).

Every element is a function of time: `Element.draw(t)` returns (RGBA image, x, y) or None. `composite()` runs
the base video through Python once, pasting the active elements on each frame, and re-encodes it.

Sizes below are fractions of the frame HEIGHT (H), measured on the 720p references:
  pop text     cap 7 %, yellow #FFFF00, black stroke ~0.55 %, yellow glow ~1.4 %, per-letter pop 1-frame stagger
  name label   cap 6 %, white, black stroke + soft shadow, per-letter rise + rotate
  circle       stroke 1.1 %, yellow + glow, drawn on clockwise from 7 o'clock in 0.6 s (ease-out)
  pointer      solid triangle 3.5 % (yellow, down) / 6 % (red, right), small bob
  red arrow    chunky 3D arrow ~12 %, grows in 0.2 s, wobbles
  title card   poster 32 % with white border + shadow, scale-in 0.2 s, title wipes out of it, 2.6 s
  speed lines  manga radial lines at the frame edge, re-drawn every 2 frames
The face is Komika Axis in the references; Bangers (OFL) stretched to 130 % width is the closest free match.
"""
import math
import os
import random
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.environ.get("CELEB_FONT") or os.path.join(HERE, "fonts", "Bangers-Regular.ttf")
XSCALE = 1.0 if "komika" in os.path.basename(FONT).lower() else 1.3
W, H, FPS = 1920, 1080, 30
YELLOW = (255, 255, 0, 255)
CAPTION_YELLOW = (252, 255, 4, 255)
GREEN = (60, 230, 60, 255)
RED = (255, 20, 20, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)


# ------------------------------------------------------------------ type
@lru_cache(maxsize=64)
def font_for_cap(cap_px: int) -> ImageFont.FreeTypeFont:
    """The font size whose capital height is cap_px."""
    probe = ImageFont.truetype(FONT, 100)
    b = probe.getbbox("H")
    cap100 = max(1, b[3] - b[1])
    return ImageFont.truetype(FONT, max(6, int(round(100 * cap_px / cap100))))


@lru_cache(maxsize=512)
def glyph(ch: str, cap_px: int, fill: tuple, stroke: int, stroke_fill: tuple) -> Tuple[Image.Image, int, int]:
    """One character with its stroke, stretched to the reference width. Returns (image, advance, baseline_y)."""
    f = font_for_cap(cap_px)
    pad = stroke + 4
    l, t, r, b = f.getbbox(ch, stroke_width=stroke)
    w, h = max(1, r - l + 2 * pad), max(1, b - t + 2 * pad)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - l, pad - t), ch, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    if XSCALE != 1.0:
        im = im.resize((max(1, int(w * XSCALE)), h), Image.LANCZOS)
    adv = int(round(f.getlength(ch) * XSCALE)) + max(1, cap_px // 40)
    return im, adv, pad - t


def word_layout(text: str, cap_px: int, fill, stroke: int, stroke_fill) -> Tuple[List[Tuple[Image.Image, int, int]], int, int]:
    """[(glyph image, x, y)] for a line, plus its width and height."""
    out, x, top = [], 0, 0
    items = [glyph(c, cap_px, fill, stroke, stroke_fill) for c in text]
    base = max(b for _, _, b in items) if items else 0
    for (im, adv, b), c in zip(items, text):
        out.append((im, x, base - b))
        x += adv
    w = max((x0 + im.width for im, x0, _ in out), default=1)
    h = max((y0 + im.height for im, _, y0 in out), default=1)
    return out, w, h


def text_image(text: str, cap_px: int, fill=WHITE, stroke: int = 0, stroke_fill=BLACK) -> Image.Image:
    glyphs, w, h = word_layout(text, cap_px, fill, stroke, stroke_fill)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for g, x, y in glyphs:
        im.alpha_composite(g, (x, y))
    return im


def glow(im: Image.Image, color: tuple, radius: int, strength: float = 1.6) -> Image.Image:
    """A coloured outer glow behind `im` (same size + margin)."""
    m = radius * 2
    big = Image.new("RGBA", (im.width + 2 * m, im.height + 2 * m), (0, 0, 0, 0))
    big.alpha_composite(im, (m, m))
    a = big.getchannel("A").filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(radius))
    a = a.point(lambda v: min(255, int(v * strength)))
    g = Image.new("RGBA", big.size, color[:3] + (0,))
    g.putalpha(a)
    g.alpha_composite(big)
    return g


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _pop_scale(frames_in: float) -> float:
    """Per-glyph pop: 0.45 -> 1.15 -> 1.0 over three frames."""
    if frames_in < 0:
        return 0.0
    if frames_in < 1:
        return 0.45 + 0.7 * frames_in
    if frames_in < 2:
        return 1.15 - 0.15 * (frames_in - 1)
    return 1.0


# ------------------------------------------------------------------ elements
@dataclass
class Element:
    kind: str
    start: float
    dur: float

    def active(self, t: float) -> bool:
        return self.start <= t < self.start + self.dur

    def draw(self, t: float):            # -> (Image, x, y) | None ; t = seconds since the element began
        raise NotImplementedError


@dataclass
class Pop(Element):
    """Quoted punchline / laugh text near the speaker: per-letter pop, then a slow grow; hard cut out."""
    text: str = ""
    cx: float = 0.5                      # anchor (fraction of frame) = centre of the text
    cy: float = 0.6
    tilt: float = 0.0
    color: tuple = YELLOW
    stroke_color: tuple = BLACK
    cap: float = 0.07

    def __post_init__(self):
        cap = int(H * self.cap)
        stroke = max(3, int(H * 0.0055))
        glyph_color = self.color
        self._glyphs, self._w, self._h = word_layout(self.text, cap, glyph_color, stroke, self.stroke_color)
        self._glow_r = max(6, int(H * 0.012))

    def draw(self, t):
        f = t * FPS
        canvas = Image.new("RGBA", (self._w + 40, self._h + 40), (0, 0, 0, 0))
        for i, (g, x, y) in enumerate(self._glyphs):
            s = _pop_scale(f - i * 1.0)
            if s <= 0:
                continue
            gw, gh = max(1, int(g.width * s)), max(1, int(g.height * s))
            gs = g.resize((gw, gh), Image.BILINEAR) if s != 1.0 else g
            drop = int((1.0 - min(1.0, s)) * 0.25 * g.height) if s < 1 else 0
            canvas.alpha_composite(gs, (20 + x + (g.width - gw) // 2, 20 + y + (g.height - gh) // 2 - drop))
        im = glow(canvas, self.color, self._glow_r) if self.color != RED else glow(canvas, WHITE, self._glow_r // 2, 1.0)
        grow = 1.0 + 0.12 * min(1.0, t / max(0.5, self.dur))
        if grow != 1.0 or self.tilt:
            im = im.resize((int(im.width * grow), int(im.height * grow)), Image.BILINEAR)
            if self.tilt:
                im = im.rotate(self.tilt, resample=Image.BICUBIC, expand=True)
        x = int(self.cx * W - im.width / 2)
        y = int(self.cy * H - im.height / 2)
        x = max(10, min(W - im.width - 10, x))
        return im, x, y


@dataclass
class NameLabel(Element):
    """White comic name under a person: letters rise and rotate into place one by one."""
    text: str = ""
    cx: float = 0.3
    y: float = 0.905                     # centre line (fraction of H)

    def __post_init__(self):
        cap = int(H * (0.06 if XSCALE == 1.0 else 0.068))   # Bangers reads smaller than Komika at one cap height
        stroke = max(3, int(H * 0.0055))
        self._glyphs, self._w, self._h = word_layout(self.text, cap, WHITE, stroke, BLACK)

    def draw(self, t):
        f = t * FPS
        canvas = Image.new("RGBA", (self._w + 60, self._h + 80), (0, 0, 0, 0))
        for i, (g, x, y) in enumerate(self._glyphs):
            p = (f - i * 0.9) / 4.0                 # 4 frames per letter, 0.9-frame stagger
            if p <= 0:
                continue
            e = ease_out(p)
            rise = int((1 - e) * self._h * 0.6)
            ang = (1 - e) * -22
            gg = g.rotate(ang, resample=Image.BICUBIC, expand=True) if ang else g
            if e < 1:
                gg = gg.copy()
                gg.putalpha(gg.getchannel("A").point(lambda v, e=e: int(v * min(1.0, 0.3 + e))))
            canvas.alpha_composite(gg, (30 + x - (gg.width - g.width) // 2, 30 + y + rise - (gg.height - g.height) // 2))
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sh.putalpha(canvas.getchannel("A").filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.6)))
        out = Image.new("RGBA", (canvas.width + 6, canvas.height + 6), (0, 0, 0, 0))
        out.alpha_composite(sh, (6, 6))
        out.alpha_composite(canvas, (0, 0))
        x = int(self.cx * W - out.width / 2)
        x = max(int(W * 0.03), min(W - out.width - int(W * 0.03), x))
        return out, x, int(self.y * H - out.height / 2)


@dataclass
class Circle(Element):
    """A glowing yellow ring drawn on clockwise around a face."""
    cx: float = 0.5
    cy: float = 0.4
    r: float = 0.18                      # radius, fraction of H
    draw_s: float = 0.6

    def draw(self, t):
        R = int(self.r * H)
        sw = max(8, int(H * 0.015))
        m = sw * 4
        size = 2 * (R + m)
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        sweep = 360.0 * ease_out(t / self.draw_s)
        if sweep < 1:
            return None
        start = 120.0                     # 7 o'clock; PIL angles run clockwise from 3 o'clock
        ImageDraw.Draw(im).arc([m, m, size - m, size - m], start, start + sweep, fill=YELLOW, width=sw)
        im = glow(im, YELLOW, max(6, int(sw * 0.8)), 1.8)
        return im, int(self.cx * W - im.width / 2), int(self.cy * H - im.height / 2)


@dataclass
class Pointer(Element):
    """A solid flat triangle above a head (down, yellow) or beside a face (right, red); small bob."""
    cx: float = 0.5
    cy: float = 0.2                      # the tip
    direction: str = "down"
    color: tuple = YELLOW
    size: float = 0.035

    def draw(self, t):
        s = int(self.size * H) * _pop_scale(t * FPS)
        if s < 2:
            return None
        bob = 0.006 * H * math.sin(2 * math.pi * 2.2 * t)
        w = int(s * 1.15)
        im = Image.new("RGBA", (w + 4, w + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if self.direction == "down":
            d.polygon([(2, 2), (w + 2, 2), (w / 2 + 2, s + 2)], fill=self.color)
            return im, int(self.cx * W - im.width / 2), int(self.cy * H - s - 2 + bob)
        d.polygon([(2, 2), (s + 2, w / 2 + 2), (2, w + 2)], fill=self.color)          # pointing right
        return im, int(self.cx * W - s - 2 + bob), int(self.cy * H - im.height / 2)


@dataclass
class Arrow3D(Element):
    """A chunky red arrow with a darker extruded side, pointing up-left at a face from below-right."""
    tip_x: float = 0.5
    tip_y: float = 0.5
    size: float = 0.13
    angle: float = 35.0                  # degrees from straight up, leaning so it comes from the lower right

    def draw(self, t):
        g = 0.3 + 0.7 * ease_out(t / 0.2)
        L = int(self.size * H * g)
        if L < 8:
            return None
        hw, sw_ = L * 0.42, L * 0.17   # head half-width, shaft half-width
        pts = [(0, 0), (hw, L * 0.45), (sw_, L * 0.45), (sw_, L), (-sw_, L), (-sw_, L * 0.45), (-hw, L * 0.45)]
        pad = L
        im = Image.new("RGBA", (3 * L, 3 * L), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        ox, oy = pad + L * 0.5, pad * 0.5
        dep = max(3, int(L * 0.08))
        d.polygon([(x + ox + dep, y + oy + dep) for x, y in pts], fill=(150, 0, 0, 255))
        d.polygon([(x + ox, y + oy) for x, y in pts], fill=(235, 25, 25, 255))
        wob = 4 * math.sin(2 * math.pi * 3 * t)
        im = im.rotate(self.angle + wob, center=(ox, oy), resample=Image.BICUBIC)
        return im, int(self.tip_x * W - ox), int(self.tip_y * H - oy)


@dataclass
class SpeedLines(Element):
    """Manga radial lines from the frame edge towards a face (black + a few white), re-drawn every 2 frames."""
    cx: float = 0.5
    cy: float = 0.45
    seed: int = 1

    def draw(self, t):
        k = int(t * FPS) // 2
        rnd = random.Random(self.seed * 1000 + k)
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        cx, cy = self.cx * W, self.cy * H
        far = math.hypot(W, H)
        for i in range(90):
            a = rnd.uniform(0, 2 * math.pi)
            inner = rnd.uniform(0.36, 0.52) * H
            spread = rnd.uniform(0.004, 0.012)
            col = (255, 255, 255, 230) if rnd.random() < 0.25 else (0, 0, 0, 235)
            p1 = (cx + math.cos(a - spread) * far, cy + math.sin(a - spread) * far)
            p2 = (cx + math.cos(a + spread) * far, cy + math.sin(a + spread) * far)
            p0 = (cx + math.cos(a) * inner, cy + math.sin(a) * inner)
            d.polygon([p0, p1, p2], fill=col)
        return im, 0, 0


@dataclass
class TitleCard(Element):
    """Film poster bottom-right that scales in, then the title wipes out of it to the left; reverse to exit."""
    poster: str = ""
    title: str = ""
    subtitle: str = ""
    year: str = ""

    def __post_init__(self):
        ph = int(H * 0.32)
        p = Image.open(self.poster).convert("RGBA")
        p = p.resize((int(p.width * ph / p.height), ph), Image.LANCZOS)
        b = max(4, int(H * 0.0055))
        card = Image.new("RGBA", (p.width + 2 * b, p.height + 2 * b), WHITE)
        card.alpha_composite(p, (b, b))
        sh = Image.new("RGBA", (card.width + 30, card.height + 30), (0, 0, 0, 0))
        sh.putalpha(Image.new("L", sh.size, 0))
        mask = Image.new("L", sh.size, 0)
        ImageDraw.Draw(mask).rectangle([15, 15, 15 + card.width, 15 + card.height], fill=170)
        sh.putalpha(mask.filter(ImageFilter.GaussianBlur(8)))
        sh.alpha_composite(card, (9, 9))
        self._card = sh
        cap = int(H * 0.07)
        self._t1 = text_image(self.title.upper(), cap, WHITE, max(3, int(H * 0.005)), BLACK)
        self._t2 = text_image(self.subtitle.upper(), int(cap * 0.82), (205, 205, 205, 255), max(2, int(H * 0.003)), (60, 60, 60, 255)) if self.subtitle else None
        self._t3 = text_image(self.year, int(H * 0.025), WHITE, 2, BLACK) if self.year else None
        tw = max(self._t1.width, self._t2.width if self._t2 else 0) + 30
        th = self._t1.height + (self._t2.height + 6 if self._t2 else 0) + (self._t3.height if self._t3 else 0)
        block = Image.new("RGBA", (tw + 20, th + 20), (0, 0, 0, 0))
        y = 10
        block.alpha_composite(self._t1, (block.width - self._t1.width - 10, y))
        y += self._t1.height + 4
        if self._t2:
            bar = Image.new("RGBA", (block.width - 4, self._t2.height + 4), (110, 110, 110, 190))
            block.alpha_composite(bar, (4, y - 2))
            block.alpha_composite(self._t2, (block.width - self._t2.width - 10, y))
            y += self._t2.height + 6
        if self._t3:
            block.alpha_composite(self._t3, (block.width - self._t3.width - 10, y))
        self._block = block
        self._x = W - int(W * 0.03) - self._card.width
        self._y = H - int(H * 0.10) - self._card.height

    def draw(self, t):
        left = self.dur - t
        # poster scale: in over 0.2 s (overshoot), out over the last 0.2 s
        if t < 0.2:
            s = 1.05 * ease_out(t / 0.2) if t < 0.15 else 1.05 - 0.05 * (t - 0.15) / 0.05
        elif left < 0.2:
            s = max(0.0, left / 0.2)
        else:
            s = 1.0
        reveal = ease_out((t - 0.2) / 0.4) if left > 0.65 else ease_out((left - 0.2) / 0.45)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if reveal > 0:
            bw = int(self._block.width * reveal)
            if bw > 0:
                part = self._block.crop((self._block.width - bw, 0, self._block.width, self._block.height))
                bx = self._x - bw
                by = self._y + self._card.height // 2 - self._block.height // 2
                frame.alpha_composite(part, (max(0, bx), by))
        if s > 0.02:
            cw, ch = max(1, int(self._card.width * s)), max(1, int(self._card.height * s))
            c = self._card.resize((cw, ch), Image.BILINEAR)
            frame.alpha_composite(c, (self._x + (self._card.width - cw) // 2, self._y + (self._card.height - ch) // 2))
        box = frame.getbbox()
        if not box:
            return None
        return frame.crop(box), box[0], box[1]


# ------------------------------------------------------------------ compositor
def composite(base: str, elements: Sequence[Element], dst: str, *, audio: str = "", crf: int = 19,
              progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Base video (1920x1080, FPS) + elements -> dst, frame by frame. Audio is muxed from `audio` (or base)."""
    n = int(round(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                        "csv=p=0", base], capture_output=True, text=True).stdout or 0) * FPS))
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", base, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", audio or base, "-map", "0:v", "-map", "1:a?",
                            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", dst],
                           stdin=subprocess.PIPE)
    els = sorted(elements, key=lambda e: e.start)
    size = W * H * 3
    i = 0
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        t = i / FPS
        act = [e for e in els if e.active(t)]
        if act:
            fr = Image.frombuffer("RGB", (W, H), buf, "raw", "RGB", 0, 1).convert("RGBA")
            for e in act:
                got = e.draw(t - e.start)
                if got:
                    im, x, y = got
                    _paste(fr, im, x, y)
            buf = fr.convert("RGB").tobytes()
        enc.stdin.write(buf)
        i += 1
        if progress and i % 300 == 0:
            progress(i, n)
    enc.stdin.close()
    enc.wait()
    dec.wait()
    if enc.returncode != 0:
        raise RuntimeError("composite encode failed")
    return dst


def _paste(fr: Image.Image, im: Image.Image, x: int, y: int) -> None:
    """alpha_composite that tolerates elements partly outside the frame."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + im.width), min(H, y + im.height)
    if x1 <= x0 or y1 <= y0:
        return
    part = im.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    fr.alpha_composite(part, (x0, y0))
