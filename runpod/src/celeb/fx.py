"""
The Celebs Goat on-screen elements, drawn to match the measured references (docs/style-refs/celeb-elements.md).

Every element is a function of time: `Element.draw(t)` returns (RGBA image, x, y) or None. `composite()` runs
the base video through Python once, pasting the active elements on each frame, and re-encodes it.
Elements that sit on a person carry `track`: one face per frame (faces.track, the local YuNet detector), so a
circle, pointer or arrow follows the head the way the references' do.

Measured on the 720p references (fractions of the frame HEIGHT H; pixel sampling in celeb-elements.md):
  type         Komika Axis (KOMIKAX.ttf, the owner's installed copy; CELEB_FONT overrides). Bangers @130 % is the
               fallback where Komika is not installed (Linux workers until the licence is settled).
  pop text     fill #FFFF00, dark line 0.3 %, then an opaque dark band (#201E00) whose 50 % edge is 1.47 % out,
               lit by a yellow glow of the letters (blur 1.1 %, gain 1.07: olive near the letters, dark at the
               edge), plus a soft dark tail 0.5 x blur 0.83 %; per-letter pop, 1-frame stagger; slow grow to 112 %
  circle       ring #FDFE00 2.1 % thick, orange-yellow glow (#FFD600) at 64 % next to the core fading to 0 at
               6 % on both sides (a touch broader inside); radius 0.94 x the face box height, centred on the face;
               drawn on clockwise from 7 o'clock in 0.6 s
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
POP_BAND = (116, 105, 0, 255)            # the band's average look where letters are close (kept for other colours)
POP_DARK = (32, 30, 0, 255)              # r5: the band itself, solved from the dark (u 288.95) and skin (r 18.3) refs
POP_GLOW = (255, 240, 0, 255)            # r5: the yellow that lights the band near the letters (G/R 0.91-0.99)
RING = (253, 254, 0, 255)
RING_GLOW = (255, 214, 0, 255)           # r5: (160,137,8) next to the core over (31,27,7) -> #FFD600 at ~58 %
# r5 ring glow: alpha by distance from the ring core's edge (px at 720p), median of 43 radial profiles, u 736.3
_GLOW_D = (0.0, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 14.5, 16.5, 18.5, 20.5, 22.5, 24.5, 26.5, 28.5, 30.5, 32.5, 34.5,
           36.5, 38.5, 40.5, 43.0)
_GLOW_OUT = (0.62, 0.576, 0.509, 0.462, 0.427, 0.393, 0.357, 0.327, 0.292, 0.262, 0.227, 0.197, 0.166, 0.138, 0.116,
             0.093, 0.077, 0.054, 0.035, 0.019, 0.010, 0.0)
_GLOW_IN = (0.64, 0.593, 0.526, 0.476, 0.442, 0.413, 0.380, 0.345, 0.311, 0.276, 0.244, 0.213, 0.178, 0.146, 0.120,
            0.093, 0.075, 0.053, 0.039, 0.021, 0.013, 0.0)
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


def grow_exact(alpha: Image.Image, r: float) -> Image.Image:
    """The alpha grown by r px with round joins and a 1 px anti-aliased edge (Euclidean distance; OpenCV)."""
    if r <= 0:
        return alpha
    try:
        import cv2
    except Exception:  # noqa: BLE001 - no OpenCV: the blur-threshold grow (a softer ~2 px edge)
        return grow_round(alpha, r)
    a = np.asarray(alpha, np.uint8)
    d = cv2.distanceTransform((a < 128).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) - 0.5
    g = np.clip((r + 0.5 - d) * 255.0, 0, 255)
    return Image.fromarray(np.maximum(g, a).astype(np.uint8), "L")


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


def lit_band(canvas: Image.Image, band_px: float, feather_px: float, tail_px: float, tail_alpha: float,
             glow_px: float, glow_gain: float, dark=POP_DARK, glow_color=YELLOW, line_px: float = 2.0,
             line_color=(50, 46, 0, 255)) -> Image.Image:
    """
    The reference pop outline as measured in r5 (u 288.95, r 18.3, u 287.6 "OMG"), outside in:
      a soft dark tail (tail_alpha x the band blurred by tail_px) -> an opaque dark band (#201E00) lit by a yellow
      glow of the letters (gain x the fill blurred by glow_px: olive between letters, dark at the outer edge;
      the glow also lifts a dark background a little past the band) -> a thin dark line -> the fill.
    """
    m = int(band_px + 2.5 * max(tail_px, glow_px) + line_px + 2)      # past 2.5 sigma both blurs are < 1 level
    big = Image.new("RGBA", (canvas.width + 2 * m, canvas.height + 2 * m), (0, 0, 0, 0))
    big.alpha_composite(canvas, (m, m))
    a = big.getchannel("A")
    band = grow_exact(a, line_px + band_px)
    if feather_px:
        band = band.filter(ImageFilter.GaussianBlur(feather_px))
    b = np.asarray(band, np.float32) / 255.0
    tail = np.asarray(band.filter(ImageFilter.GaussianBlur(tail_px)), np.float32) * (tail_alpha / 255.0)
    ad = 1.0 - (1.0 - b) * (1.0 - tail)
    g = np.clip(np.asarray(a.filter(ImageFilter.GaussianBlur(glow_px)), np.float32) * (glow_gain / 255.0), 0, 1)
    at = ad + g * (1.0 - ad)
    D = np.array(dark[:3], np.float32)
    Y = np.array(glow_color[:3], np.float32)
    rgb = (D[None, None] * (ad * (1.0 - g))[..., None] + Y[None, None] * g[..., None]) / np.maximum(at, 1e-6)[..., None]
    arr = np.dstack([np.clip(rgb + 0.5, 0, 255), np.clip(at * 255.0 + 0.5, 0, 255)]).astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")
    line = Image.new("RGBA", big.size, line_color[:3] + (0,))
    line.putalpha(grow_exact(a, line_px))
    out.alpha_composite(line)
    out.alpha_composite(big)
    return out


def scale_rotate(im: Image.Image, k: float, deg: float) -> Image.Image:
    """Scale by k and rotate deg counter-clockwise about the centre in ONE bilinear resample (expanded canvas)."""
    w, h = im.size
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    ow = max(1, int(math.ceil(k * (w * abs(c) + h * abs(s)))))
    oh = max(1, int(math.ceil(k * (w * abs(s) + h * abs(c)))))
    a, b, d, e = c / k, -s / k, s / k, c / k                  # output -> input (inverse of the forward map)
    ox, oy, ix, iy = ow / 2.0, oh / 2.0, w / 2.0, h / 2.0
    return im.transform((ow, oh), Image.AFFINE, (a, b, ix - a * ox - b * oy, d, e, iy - d * ox - e * oy),
                        resample=Image.BILINEAR)


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
        self._line = H * 0.0028                      # r5: ~2 px at 720p
        # r5 (px at 720p, measured from the yellow fill's edge): band 50 % at 10.6, 96 % -> 21 % over d 9-12,
        # then a dark tail 17 % -> 0 over d 13-22; glow of the letters ~ 0.14 at d 9 -> 0 at d 23
        self._band = H * 0.0092
        self._feather = 0.0
        self._tail, self._tail_a = H * 0.011, 0.55
        self._glow, self._gain = H * 0.014, 0.93
        self._settled = None                         # the outline is static once every glyph has landed

    def _outlined(self, f: float) -> Image.Image:
        canvas = Image.new("RGBA", (self._w + 40, self._h + 40), (0, 0, 0, 0))
        for i, (g, x, y) in enumerate(self._glyphs):
            s = _pop_scale(f - i * 1.0)
            if s <= 0:
                continue
            gw, gh = max(1, int(g.width * s)), max(1, int(g.height * s))
            gs = g.resize((gw, gh), Image.BILINEAR) if s != 1.0 else g
            drop = int((1.0 - min(1.0, s)) * 0.25 * g.height) if s < 1 else 0
            canvas.alpha_composite(gs, (20 + x + (g.width - gw) // 2, 20 + y + (g.height - gh) // 2 - drop))
        if self.color == YELLOW:
            return lit_band(canvas, self._band, self._feather, self._tail, self._tail_a, self._glow, self._gain,
                            glow_color=POP_GLOW, line_px=self._line)
        band = (40, 90, 40, 255) if self.color == GREEN else WHITE
        return banded(canvas, H * 0.012, H * 0.0015, band, self._line)

    def draw(self, t):
        f = t * FPS
        if f >= len(self._glyphs) + 2:
            if self._settled is None:
                self._settled = self._outlined(f)
            im = self._settled
        else:
            im = self._outlined(f)
        grow = 1.0 + 0.12 * min(1.0, t / max(0.5, self.dur))
        if grow != 1.0 or self.tilt:
            im = scale_rotate(im, grow, self.tilt)
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
        # r5 (u 736.3, px at 720p from the white's edge): solid black to d 9 (0.97), 0.76 at d 9, 0.17 at d 10 on
        # every side (below = above = left = right); nothing measurable beyond (< 0.03): no drop shadow
        self._stroke = cap * 0.161
        self._glyphs, self._w, self._h = word_layout(self.text, cap, WHITE, 0, BLACK)
        self._settled = None

    def draw(self, t):
        f = t * FPS
        if f >= (len(self._glyphs) - 1) * 0.9 + 4.0:
            if self._settled is None:
                self._settled = self._stroked(f)
            out = self._settled
        else:
            out = self._stroked(f)
        fc = self.face(0.0)
        x = int((fc["cx"] if fc else self.cx) * W - out.width / 2)
        x = max(int(W * 0.03), min(W - out.width - int(W * 0.03), x))
        return out, x, int(self.y * H - out.height / 2)

    def _stroked(self, f: float) -> Image.Image:
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
        # a black outer stroke with round joins and a crisp edge, the same width on every side
        pad = int(self._stroke) + 12
        big = Image.new("RGBA", (canvas.width + 2 * pad, canvas.height + 2 * pad), (0, 0, 0, 0))
        big.alpha_composite(canvas, (pad, pad))
        out = Image.new("RGBA", big.size, (0, 0, 0, 0))
        out.putalpha(grow_exact(big.getchannel("A"), self._stroke))
        out.alpha_composite(big)
        return out


RING_HALF = 0.0104                       # half the core: 15 px of 720 thick
RING_START = 120.0                       # 7 o'clock; angles run clockwise from 3 o'clock (image y is down)


@lru_cache(maxsize=4)
def _ring_geom(R: int):
    """Pixel geometry of the annulus a ring of radius R (px) can touch: flat indices, offsets, radius, angle."""
    hw = RING_HALF * H
    m = int(math.ceil(hw + _GLOW_D[-1] * H / 720.0)) + 2
    size = 2 * (R + m)
    c = size / 2.0 - 0.5
    yy, xx = np.mgrid[0:size, 0:size]
    dx = (xx - c).astype(np.float32)
    dy = (yy - c).astype(np.float32)
    r = np.hypot(dx, dy)
    idx = np.flatnonzero(np.abs(r - R) <= m)
    dx, dy, r = dx.ravel()[idx], dy.ravel()[idx], r.ravel()[idx]
    theta = np.degrees(np.arctan2(dy, dx)) % 360.0
    return size, idx, dx, dy, r, theta


def _ring_rgba(R: int, sweep: float, start: float = RING_START) -> Image.Image:
    """The ring core + its glow as one RGBA, from the signed distance to the drawn arc (butt ends, as measured)."""
    size, idx, dx, dy, r, theta = _ring_geom(R)
    hw = RING_HALF * H
    if sweep >= 360.0:
        sd = np.abs(r - R) - hw
    else:
        within = ((theta - start) % 360.0) <= sweep
        sd = np.empty_like(r)
        sd[within] = np.abs(r[within] - R) - hw
        o = ~within
        best = None
        for phi in (math.radians(start), math.radians(start + sweep)):
            s = dx[o] * math.cos(phi) + dy[o] * math.sin(phi)
            tt = -dx[o] * math.sin(phi) + dy[o] * math.cos(phi)
            d = np.hypot(tt, np.maximum(0.0, np.abs(s - R) - hw))
            best = d if best is None else np.minimum(best, d)
        sd[o] = best
    cov = np.clip(0.5 - sd, 0.0, 1.0)
    d720 = np.maximum(sd, 0.0) * (720.0 / H)
    g = np.where(r < R, np.interp(d720, _GLOW_D, _GLOW_IN), np.interp(d720, _GLOW_D, _GLOW_OUT))
    a = cov + (1.0 - cov) * g
    ring = np.array(RING[:3], np.float32)
    gl = np.array(RING_GLOW[:3], np.float32)
    rgb = (ring[None] * cov[:, None] + gl[None] * (g * (1.0 - cov))[:, None]) / np.maximum(a, 1e-6)[:, None]
    out = np.zeros((size * size, 4), np.uint8)
    out[idx, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    out[idx, 3] = np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out.reshape(size, size, 4), "RGBA")


@lru_cache(maxsize=12)
def _ring_full(R: int) -> Image.Image:
    return _ring_rgba(R, 360.0)


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
        R = max(8, int(round(r * H / 2.0)) * 2)          # 2 px buckets: the full ring is cached per radius
        sweep = 360.0 * ease_out(t / self.draw_s)
        if sweep < 1:
            return None
        im = _ring_full(R) if sweep >= 359.95 else _ring_rgba(R, sweep)
        return im, int(round(cx * W - im.width / 2)), int(round(cy * H - im.height / 2))


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
    """
    Manga speed lines round the frame edge (r5, r2op 12 s): ~32 light wedges converging on the frame centre,
    widest at the frame edge, tips 58-95 % of the way out. Re-drawn every 2 frames.
    Measured at 720p: centre (624, 367) = 0.488 W, 0.509 H (the face was 100 px left: the lines ignore it);
    25 lines on the 78 % of the border not covered by the person/logo -> ~32 round the frame; perpendicular base
    width 8-19 px (median 11.5 = 1.6 % H); tips at 290-620 px (0.58-0.95 of the ray to the edge); colour
    (60,59,63) over the (8,7,12) curtain = white at 21 %; no dark lines are visible on that black background.
    """
    cx: float = 0.488
    cy: float = 0.509
    seed: int = 1
    count: int = 32
    alpha: float = 0.21
    on_face: bool = False                # True: converge on the tracked face instead of the frame centre

    def draw(self, t):
        k = int(t * FPS) // 2
        cache = self.__dict__.setdefault("_cache", {})
        if k in cache:
            return cache[k], 0, 0
        rnd = random.Random(self.seed * 1000 + k)
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        fc = self.face(t) if self.on_face else None
        cx, cy = ((fc["cx"], fc["cy"]) if fc else (self.cx, self.cy))
        cx, cy = cx * W, cy * H
        col = (255, 255, 255, int(round(255 * self.alpha)))
        for _ in range(self.count):
            # spread evenly along the frame's border (the reference has more lines on the long sides)
            u = rnd.uniform(0, 2 * (W + H))
            bx, by = ((u, 0) if u < W else (W, u - W) if u < W + H else (W - (u - W - H), H) if u < 2 * W + H
                      else (0, H - (u - 2 * W - H)))
            n = max(1e-6, math.hypot(bx - cx, by - cy))
            ux, uy = (bx - cx) / n, (by - cy) / n
            ex = (W - cx) / ux if ux > 1e-6 else (-cx / ux if ux < -1e-6 else 1e9)
            ey = (H - cy) / uy if uy > 1e-6 else (-cy / uy if uy < -1e-6 else 1e9)
            e = min(ex, ey)                                     # centre -> frame edge along this ray
            tip = e * rnd.uniform(0.58, 0.95)
            half = H * rnd.uniform(0.008, 0.024) / 2            # half the base width, at the frame edge
            far = e * 1.15                                      # run past the edge so the base is not cut short
            hf = half * (far - tip) / max(1.0, e - tip)
            p0 = (cx + ux * tip, cy + uy * tip)
            p1 = (cx + ux * far - uy * hf, cy + uy * far + ux * hf)
            p2 = (cx + ux * far + uy * hf, cy + uy * far - ux * hf)
            d.polygon([p0, p1, p2], fill=col)
        cache.clear()
        cache[k] = im
        return im, 0, 0


# Film title card (r5, u 260.6-263.0; px at 720p -> fractions of H):
TC_POSTER_H = 0.3167                     # poster picture 228 px tall
TC_BORDER = 0.0047                       # white border 3.4 px
TC_OUTLINE = 0.0014                      # then a 1 px black line
TC_MARGIN_R, TC_MARGIN_B = 0.0403, 0.0417   # outer edge 29 px from the right, 30 px from the bottom
TC_SHADOW = (0.0083, 0.0097, 0.70)       # offset down-right 6 px, blur 7 px, 70 %: shows right/bottom only
TC_CAP = 0.0563                          # AVENGERS: white rows 40.5 px, 242 px wide
TC_SUB_CAP = 0.0572                      # AGE OF ULTRON: outline 42.5 px tall, 366 px wide
TC_YEAR_CAP = 0.0199                     # 2015: 14 px
TC_BAR = (107, 116, 134, 255)            # #6B7485, opaque (the same over pink, blue and dark backgrounds)
TC_BAR_H = 0.0701                        # 50.5 px
TC_BAR_TOP = 0.2007                      # bar top 144.5 px under the poster's outer top
TC_GAP_TEXT = 0.0111                     # text right edge 8 px left of the poster
TC_GAP_TITLE = 0.0132                    # title baseline 9.5 px above the bar
TC_GAP_YEAR = 0.0097                     # year top 7 px under the bar
TC_BAR_LEAD = 0.0083                     # the bar starts 6 px left of the subtitle
TC_SUB_LINE = 0.0028                     # subtitle: hollow letters, white outline 2 px


def _alpha_box(im: Image.Image) -> Tuple[int, int, int, int]:
    return im.getchannel("A").point(lambda v: 255 if v > 96 else 0).getbbox() or (0, 0, im.width, im.height)


def _white_box(im: Image.Image) -> Tuple[int, int, int, int]:
    """The box of the white letters only (the references were measured on their white pixels)."""
    a = np.asarray(im)
    ys, xs = np.nonzero((a[..., :3].min(-1) > 215) & (a[..., 3] > 200))
    if not len(xs):
        return _alpha_box(im)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _edged(text: str, cap: int, r: float, opacity: float, blur: float) -> Image.Image:
    """White text with a faint dark edge (r px grown, `opacity` black, softened by `blur`)."""
    t = text_image(text, cap, WHITE, 0)
    p = int(r + 3 * blur + 3)
    big = Image.new("RGBA", (t.width + 2 * p, t.height + 2 * p), (0, 0, 0, 0))
    big.alpha_composite(t, (p, p))
    e = grow_exact(big.getchannel("A"), r)
    if blur:
        e = e.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new("RGBA", big.size, (0, 0, 0, 0))
    out.putalpha(e.point(lambda v: int(v * opacity)))
    out.alpha_composite(big)
    return out


def _hollow(text: str, cap: int, line: float) -> Image.Image:
    """Hollow letters: a white outline `line` px wide centred on the glyph edge, a faint dark fringe outside it."""
    t = text_image(text, cap, WHITE, 0)
    p = int(line + 4)
    a = Image.new("L", (t.width + 2 * p, t.height + 2 * p), 0)
    a.paste(t.getchannel("A"), (p, p))
    outer = grow_exact(a, line / 2)
    inner = Image.eval(grow_exact(Image.eval(a, lambda v: 255 - v), line / 2), lambda v: 255 - v)
    o16 = np.asarray(outer, np.int16)
    ring = np.clip(o16 - np.asarray(inner, np.int16), 0, 255).astype(np.uint8)
    fringe = np.asarray(grow_exact(a, line / 2 + 1.0), np.float32) * 0.18
    out = Image.new("RGBA", a.size, (0, 0, 0, 0))
    out.putalpha(Image.fromarray(np.clip(fringe - o16, 0, 255).astype(np.uint8)))
    white = Image.new("RGBA", a.size, (255, 255, 255, 0))
    white.putalpha(Image.fromarray(ring))
    out.alpha_composite(white)
    return out


def _paste_into(dst: Image.Image, im: Image.Image, x: int, y: int) -> None:
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.width, x + im.width), min(dst.height, y + im.height)
    if x1 > x0 and y1 > y0:
        dst.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


@dataclass
class TitleCard(Element):
    """Film poster bottom-right that scales in, then the title slides out of it to the left over a grey bar."""
    poster: str = ""
    title: str = ""
    subtitle: str = ""
    year: str = ""

    def __post_init__(self):
        ph = int(round(H * TC_POSTER_H))
        p = Image.open(self.poster).convert("RGBA")
        p = p.resize((max(1, int(round(p.width * ph / p.height))), ph), Image.LANCZOS)
        b = max(2, int(round(H * TC_BORDER)))
        o = max(1, int(round(H * TC_OUTLINE)))
        cw, ch = p.width + 2 * (b + o), p.height + 2 * (b + o)
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 235))
        ImageDraw.Draw(card).rectangle([o, o, cw - 1 - o, ch - 1 - o], fill=WHITE)
        card.alpha_composite(p, (b + o, b + o))
        off, blur, op = int(round(H * TC_SHADOW[0])), H * TC_SHADOW[1], TC_SHADOW[2]
        pad = int(3 * blur) + off + 2
        sh = Image.new("RGBA", (cw + 2 * pad, ch + 2 * pad), (0, 0, 0, 0))
        mask = Image.new("L", sh.size, 0)
        ImageDraw.Draw(mask).rectangle([pad + off, pad + off, pad + off + cw - 1, pad + off + ch - 1],
                                       fill=int(255 * op))
        sh.putalpha(mask.filter(ImageFilter.GaussianBlur(blur)))
        sh.alpha_composite(card, (pad, pad))
        self._card, self._pad = sh, pad
        self._cx0 = W - int(round(H * TC_MARGIN_R)) - cw          # the card's outer left / top edge
        self._cy0 = H - int(round(H * TC_MARGIN_B)) - ch
        # the text, right-aligned against the poster (frame coordinates)
        cap = int(round(H * TC_CAP))
        right = self._cx0 - int(round(H * TC_GAP_TEXT))
        bar_top = self._cy0 + int(round(H * TC_BAR_TOP))
        bar_h = int(round(H * TC_BAR_H))
        # each line slides out from behind the poster on its own; u 260.7 (mid-wipe): bar 24 % out, title 12 %,
        # subtitle not yet -> bar first, the title ~1 frame later, the subtitle and year ~2 frames later
        parts = []                                                 # (image, x, y, lag in s)
        t1 = _edged(self.title.upper(), cap, H * 0.0016, 0.5, H * 0.0012)     # a faint dark edge: 0.2, 0.16, 0.06
        l1, _, r1, b1 = _white_box(t1)
        parts.append((t1, right - r1, bar_top - int(round(H * TC_GAP_TITLE)) - b1, 1.0 / FPS))
        left = right - (r1 - l1)
        if self.subtitle:
            t2 = _hollow(self.subtitle.upper(), int(round(H * TC_SUB_CAP)), H * TC_SUB_LINE)
            l2, tp2, r2, _ = _white_box(t2)
            parts.append((t2, right - r2, bar_top + int(round(H * 0.0014)) - tp2, 2.0 / FPS))
            left = min(left, right - (r2 - l2))
        if self.year:
            t3 = _edged(self.year, int(round(H * TC_YEAR_CAP)), H * 0.0021, 0.5, H * 0.0012)   # 0.32 0.23 0.12
            _, tp3, r3, _ = _white_box(t3)
            parts.append((t3, right - r3, bar_top + bar_h + int(round(H * TC_GAP_YEAR)) - tp3, 2.0 / FPS))
        self._bar = (left - int(round(H * TC_BAR_LEAD)), bar_top, self._cx0 + 2, bar_top + bar_h) if self.subtitle else None
        self._lines = parts
        self._tx0 = min(x for _, x, _, _ in parts)
        self._ty0 = min(y for _, _, y, _ in parts)

    def _progress(self, t: float, lag: float) -> float:
        left = self.dur - t
        if left > 0.65:
            return ease_out((t - 0.2 - lag) / 0.4)
        return ease_out((left - 0.2 - lag) / 0.45)

    def draw(self, t):
        left = self.dur - t
        # poster scale: in over 0.2 s (105 % overshoot), out over the last 0.2 s
        if t < 0.2:
            s = 1.05 * ease_out(t / 0.2) if t < 0.15 else 1.05 - 0.05 * (t - 0.15) / 0.05
        elif left < 0.2:
            s = max(0.0, left / 0.2)
        else:
            s = 1.0
        bar_p = self._progress(t, 0.0)
        X0 = min(self._tx0, self._bar[0] if self._bar else W, self._cx0 - self._pad)
        Y0 = min(self._ty0, self._bar[1] if self._bar else H, self._cy0 - self._pad)
        frame = Image.new("RGBA", (W - X0, H - Y0), (0, 0, 0, 0))
        if self._bar and bar_p > 0:
            bx0, by0, bx1, by1 = self._bar
            bw = int(round((bx1 - bx0) * bar_p))
            if bw > 0:
                ImageDraw.Draw(frame).rectangle([bx1 - bw - X0, by0 - Y0, bx1 - 1 - X0, by1 - 1 - Y0], fill=TC_BAR)
        for im, x, y, lag in self._lines:
            p = self._progress(t, lag)
            if p <= 0:
                continue
            travel = self._cx0 - x                                   # fully hidden: its left edge at the poster
            shift = int(round((1.0 - p) * travel))
            vis = min(im.width, self._cx0 - (x + shift))             # the part already out from behind the poster
            if vis > 0:
                _paste_into(frame, im.crop((0, 0, vis, im.height)), x + shift - X0, y - Y0)
        if s > 0.02:
            cw, ch = max(1, int(self._card.width * s)), max(1, int(self._card.height * s))
            c = self._card.resize((cw, ch), Image.BILINEAR) if s != 1.0 else self._card
            _paste_into(frame, c, self._cx0 - self._pad + (self._card.width - cw) // 2 - X0,
                        self._cy0 - self._pad + (self._card.height - ch) // 2 - Y0)
        box = frame.getbbox()
        if not box:
            return None
        return frame.crop(box), box[0] + X0, box[1] + Y0


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
