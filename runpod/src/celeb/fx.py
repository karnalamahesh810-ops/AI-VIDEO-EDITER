"""
The Celebs Goat on-screen elements, drawn to match the measured references (docs/style-refs/celeb-elements.md).

Every element is a function of time: `Element.draw(t)` returns (RGBA image, x, y) or None. `composite()` runs
the base video through Python once, pasting the active elements on each frame, and re-encodes it.
Elements that sit on a person carry `track`: one face per frame (faces.track, the local YuNet detector), so a
circle, pointer or arrow follows the head the way the references' do.

Measured on the 720p references (fractions of the frame HEIGHT H; pixel sampling in celeb-elements.md):
  type         Komika Axis (KOMIKAX.ttf, the owner's installed copy; CELEB_FONT overrides). Bangers @130 % is the
               fallback where Komika is not installed (Linux workers until the licence is settled).
  pop text     fill #FFFF00, black line 0.3 %, then a dark olive band (#7D7608) out to 1.55 % with a 0.5 % feather;
               per-letter pop, 1-frame stagger; slow grow to 112 %
  circle       ring #FDFE00 2.1 % thick, orange-yellow glow (#FFC800) ~2.8 %; radius 0.94 x the face box height,
               centred on the face; drawn on clockwise from 7 o'clock in 0.6 s
  pointer      solid triangle #FFFC00 (down, above the head) / #FF0000 (right, beside the face), 8.6 % tall,
               tip 4 % above the head; enters 125 % -> 100 % in 3 frames; follows the head
  red arrow    #FF0000 with a #990000 extruded right side (1.2 %), 2 px dark line, 32 % long, head 64 % of the length
               wide, shaft 30 %; leans 21 deg (tip up-left), tip just under the chin; scale per frame
               0.22 .47 .70 .89 1.04 1.10 1.077 1.049 1.026 1.008 1.0 (r2op 13.55-13.89), no wobble, out on the cut
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
_KOMIKA = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", "KOMIKAX.ttf"),
           r"C:\Windows\Fonts\KOMIKAX.ttf", os.path.join(HERE, "fonts", "KOMIKAX.ttf")]
FONT = os.environ.get("CELEB_FONT") or next((f for f in _KOMIKA if os.path.isfile(f)),
                                            os.path.join(HERE, "fonts", "Bangers-Regular.ttf"))
XSCALE = 1.0 if "komika" in os.path.basename(FONT).lower() else 1.3
W, H, FPS = 1920, 1080, 30
YELLOW = (255, 255, 0, 255)
CAPTION_YELLOW = (252, 255, 4, 255)
POP_BAND = (116, 105, 0, 255)
RING = (253, 254, 0, 255)
RING_GLOW = (255, 200, 0, 255)
POINTER_YELLOW = (255, 252, 0, 255)
GREEN = (60, 230, 60, 255)
RED = (255, 0, 0, 255)
RED_SIDE = (153, 0, 0, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
ARROW_SCALE = (0.22, 0.47, 0.70, 0.89, 1.04, 1.10, 1.077, 1.049, 1.026, 1.008, 1.0)


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
    adv = int(round(f.getlength(ch) * XSCALE))       # the references use the font's own spacing
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
    track: Optional[list] = None          # one face per frame ({cx, cy, w, h} fractions) or None

    def active(self, t: float) -> bool:
        return self.start <= t < self.start + self.dur

    def face(self, t: float) -> Optional[dict]:
        if not self.track:
            return None
        k = min(len(self.track) - 1, max(0, int(t * FPS)))
        return self.track[k] or next((f for f in self.track[k::-1] if f), None)

    def draw(self, t: float):            # -> (Image, x, y) | None ; t = seconds since the element began
        raise NotImplementedError


def grow_round(alpha: Image.Image, r: float) -> Image.Image:
    """The alpha grown by r px with ROUND joins (blur, then threshold at the r contour)."""
    if r <= 0:
        return alpha
    sigma = max(0.5, r / 1.86)
    return alpha.filter(ImageFilter.GaussianBlur(sigma)).point(lambda v: 255 if v > 8 else int(v * 30))


def banded(canvas: Image.Image, band_px: float, feather_px: float, color=POP_BAND, line_px: float = 2.0,
           line_color=(50, 46, 0, 255), band_alpha: float = 0.92) -> Image.Image:
    """
    The reference pop outline, outside in (pixel-sampled, u 288.95 / r 18.3):
      a soft falloff -> an olive band (#746900 at 88 %) -> a thin dark line -> the yellow fill.
    All grown with round joins.
    """
    m = int(band_px + feather_px * 3 + line_px + 4)
    big = Image.new("RGBA", (canvas.width + 2 * m, canvas.height + 2 * m), (0, 0, 0, 0))
    big.alpha_composite(canvas, (m, m))
    a = big.getchannel("A")
    band = grow_round(a, line_px + band_px)
    if feather_px:
        band = band.filter(ImageFilter.GaussianBlur(feather_px))
    band = band.point(lambda v: int(v * band_alpha))
    out = Image.new("RGBA", big.size, color[:3] + (0,))
    out.putalpha(band)
    line = Image.new("RGBA", big.size, line_color[:3] + (0,))
    line.putalpha(grow_round(a, line_px))
    out.alpha_composite(line)
    out.alpha_composite(big)
    return out


@dataclass
class Pop(Element):
    """Quoted punchline / laugh text near the speaker: per-letter pop, then a slow grow; hard cut out."""
    text: str = ""
    cx: float = 0.5                      # anchor (fraction of frame) = centre of the text
    cy: float = 0.6
    tilt: float = 0.0
    color: tuple = YELLOW
    stroke_color: tuple = BLACK
    cap: float = 0.092                   # MOTHERF*** M 71 px of 720 at +10 % grow, Komika cap

    def __post_init__(self):
        cap = int(H * self.cap)
        self._glyphs, self._w, self._h = word_layout(self.text, cap, self.color, 0, self.stroke_color)
        self._line = H * 0.0021                      # ~1.5 px at 720p
        self._band = H * 0.012                       # olive plateau (ref: ~9 px at 720p incl. the line)
        self._feather = H * 0.0015                   # short soft edge (ref: ~3-4 px at 720p)

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
        band = POP_BAND if self.color == YELLOW else ((40, 90, 40, 255) if self.color == GREEN else WHITE)
        im = banded(canvas, self._band, self._feather, band, self._line)
        grow = 1.0 + 0.12 * min(1.0, t / max(0.5, self.dur))
        if grow != 1.0 or self.tilt:
            im = im.resize((int(im.width * grow), int(im.height * grow)), Image.BILINEAR)
            if self.tilt:
                im = im.rotate(self.tilt, resample=Image.BICUBIC, expand=True)
        fc = self.face(t)
        cx, cy = (fc["cx"], min(0.76, fc["cy"] + fc["h"] * 0.78)) if fc else (self.cx, self.cy)
        x = int(cx * W - im.width / 2)
        y = int(cy * H - im.height / 2)
        x = max(10, min(W - im.width - 10, x))
        return im, x, y


@dataclass
class NameLabel(Element):
    """White comic name under a person: letters rise and rotate into place one by one."""
    text: str = ""
    cx: float = 0.3
    y: float = 0.905                     # centre line (fraction of H)

    def __post_init__(self):
        cap = int(H * 0.074)                 # ref: white 53 px of 720
        self._stroke = cap * 0.19            # black outer stroke, round joins (8.5-10 px at 720p)
        self._glyphs, self._w, self._h = word_layout(self.text, cap, WHITE, 0, BLACK)

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
        # reference (u 736.3): a black outer stroke with round joins, 16 % of the cap height, and a near-hard
        # black drop shadow ~7 % of the cap straight down (the black reaches 12 px under the letters at 720p)
        pad = int(self._stroke) + 12
        big = Image.new("RGBA", (canvas.width + 2 * pad, canvas.height + 2 * pad), (0, 0, 0, 0))
        big.alpha_composite(canvas, (pad, pad))
        a = big.getchannel("A")
        stroke = grow_round(a, self._stroke)
        out = Image.new("RGBA", big.size, (0, 0, 0, 0))
        drop = int(round(self._stroke * 0.45))
        sh = Image.new("RGBA", big.size, (0, 0, 0, 0))
        sh.putalpha(stroke.filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: int(v * 0.9)))
        out.alpha_composite(sh, (0, drop))
        st = Image.new("RGBA", big.size, (0, 0, 0, 0))
        st.putalpha(stroke)
        out.alpha_composite(st)
        out.alpha_composite(big)
        fc = self.face(0.0)
        x = int((fc["cx"] if fc else self.cx) * W - out.width / 2)
        x = max(int(W * 0.03), min(W - out.width - int(W * 0.03), x))
        return out, x, int(self.y * H - out.height / 2)


@dataclass
class Circle(Element):
    """A ring (#FDFE00, 2.1 % thick, orange-yellow glow) drawn on clockwise around the tracked face."""
    cx: float = 0.5
    cy: float = 0.4
    r: float = 0.18                      # radius, fraction of H (when there is no track)
    draw_s: float = 0.6

    def draw(self, t):
        fc = self.face(t)
        cx, cy, r = (fc["cx"], fc["cy"], fc["h"] * 0.94) if fc else (self.cx, self.cy, self.r)
        R = int(r * H)
        sw = max(8, int(round(H * 0.021)))
        g = max(8, int(round(H * 0.028)))
        m = sw + 3 * g
        size = 2 * (R + m)
        sweep = 360.0 * ease_out(t / self.draw_s)
        if sweep < 1:
            return None
        start = 120.0                     # 7 o'clock; PIL angles run clockwise from 3 o'clock
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(im).arc([m - sw // 2, m - sw // 2, size - m + sw // 2, size - m + sw // 2], start,
                               start + sweep, fill=RING, width=sw)
        im = glow(im, RING_GLOW, g // 2, 1.25)
        return im, int(cx * W - im.width / 2), int(cy * H - im.height / 2)


@dataclass
class Pointer(Element):
    """A solid flat triangle that follows a head: yellow pointing down above it, or red pointing right beside it."""
    cx: float = 0.5
    cy: float = 0.2                      # the tip (when there is no track)
    direction: str = "down"
    color: tuple = POINTER_YELLOW
    size: float = 0.086

    def draw(self, t):
        f = t * FPS
        k = 1.25 if f < 1 else (1.1 if f < 2 else 1.0)       # measured: 88 -> 69 -> 73 px (u 564.65-565.2)
        s = int(self.size * H * k)
        w = int(s * 1.18)
        im = Image.new("RGBA", (w + 4, w + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        fc = self.face(t)
        if self.direction == "down":
            tx, ty = (fc["cx"], fc["cy"] - fc["h"] / 2 - 0.04) if fc else (self.cx, self.cy)
            d.polygon([(2, 2), (w + 2, 2), (w / 2 + 2, s + 2)], fill=self.color)
            return im, int(tx * W - im.width / 2), int(ty * H - s - 2)
        tx, ty = (fc["cx"] - fc["w"] / 2 - 0.03, fc["cy"]) if fc else (self.cx, self.cy)
        d.polygon([(2, 2), (s + 2, w / 2 + 2), (2, w + 2)], fill=self.color)
        return im, int(tx * W - s - 2), int(ty * H - im.height / 2)


@dataclass
class Arrow3D(Element):
    """The reference's red 3D arrow: flat #FF0000 face, #990000 extruded right side, pointing up at a face."""
    tip_x: float = 0.5
    tip_y: float = 0.5
    size: float = 0.32                   # length, fraction of H
    angle: float = 21.0                  # leans so the tip is up-left of the tail

    def draw(self, t):
        f = int(t * FPS)
        k = ARROW_SCALE[min(f, len(ARROW_SCALE) - 1)]
        fc = self.face(min(t, 0.4))      # placed on the face as it settles (r2op 13.92: John's face box)
        if fc:   # measured: tip 0.27 face-widths right of the face centre, 0.22 face-heights under the chin,
                 # length 1.03 face-heights (233 px for a 226 px face at 720p)
            tip_x, tip_y = fc["cx"] + fc["w"] * 0.27 * (W and 1), fc["cy"] + fc["h"] * 0.72
            L = max(0.18, min(0.42, fc["h"] * 1.03)) * H
        else:
            tip_x, tip_y = self.tip_x, self.tip_y
            L = self.size * H
        hw, sw_, hl = 0.32 * L, 0.15 * L, 0.42 * L   # head 64 %, shaft 30 % of the length (reference)
        pts = [(0, 0), (hw, hl), (sw_, hl), (sw_, L), (-sw_, L), (-sw_, hl), (-hw, hl)]
        a = math.radians(-self.angle)
        rot = [(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for x, y in pts]
        cxl = sum(p[0] for p in rot) / len(rot)
        cyl = sum(p[1] for p in rot) / len(rot)
        sc = [((x - cxl) * k, (y - cyl) * k) for x, y in rot]           # scaled about its centre (measured)
        dep = H * 0.012 * k
        size = int(L * 1.7)
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        o = size / 2
        d.polygon([(x + o + dep, y + o + dep * 0.35) for x, y in sc], fill=RED_SIDE)
        d.polygon([(x + o, y + o) for x, y in sc], fill=RED, outline=(40, 0, 0, 255))
        tip_c = (rot[0][0] - cxl, rot[0][1] - cyl)                      # the k=1 tip lands on (tip_x, tip_y)
        cx = tip_x * W - tip_c[0]
        cy = tip_y * H - tip_c[1]
        return im, int(cx - o), int(cy - o)


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
        fc = self.face(t)
        cx, cy = ((fc["cx"], fc["cy"]) if fc else (self.cx, self.cy))
        cx, cy = cx * W, cy * H
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
