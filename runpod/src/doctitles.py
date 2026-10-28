"""
Documentary titles (the owner, 2026-10-28): new looks, a new type pairing and real maps - never the old ml- / pack looks.

Type (OFL, assets/doctitles/fonts): Playfair Display SemiBold for act titles, Manrope for labels, numbers and names
(caps tracked ~+12 %). Sizes at 1080p: act label 30 px, act title 72 px, lower-third name 40 px / role 26 px,
numbers 96 px (never full-screen). Colour: white, one thin gold rule (#C9A227), soft shadow; no outlines, no boxes,
no yellow. Everything sits inside the title-safe area (5 % / 5 %), the same place every time (the owner's rule).
Motion: 350-400 ms ease-out (slide-up + fade, letter-spacing settle, a short rule wipe), a quick fade out.

    ActCard(label, title, seconds)                 full-frame RGBA: the shot darkened ~35 % + vignette, centred
    Number(value, caption, seconds, count_from)    lower-left figure (quick count-up) + caption
    LowerThird(name, role, seconds, quote, quote_at)  lower-left name / role (+ a quote line when it is said)
    MapScene(bbox, ...)                            opaque frame: real Natural Earth geography (states 1:10m, lakes,
                                                   rivers, relief tiles z5), a slow push, the river drawing in,
                                                   highlights and labels each landing on its own spoken word
Each look renders frame(t) -> PIL RGBA 1920x1080 for t in [0, seconds]. The worker's renderer is Remotion; these
are the reference implementation (laptop renders, proofs) until the TSX port (docs/doc-titles.md).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "doctitles")
FONTS = os.path.join(ASSETS, "fonts")
W, H = 1920, 1080
SAFE_X, SAFE_Y = 96, 54                     # title-safe: 5 % each side
GOLD = (201, 162, 39)
WHITE = (255, 255, 255)
_FONT_CACHE: Dict[Tuple[str, int, int], ImageFont.FreeTypeFont] = {}


# ------------------------------------------------------------------ type
def _font(name: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    key = (name, size, weight)
    f = _FONT_CACHE.get(key)
    if f is None:
        f = ImageFont.truetype(os.path.join(FONTS, name), size)
        try:
            f.set_variation_by_axes([weight])
        except (OSError, AttributeError):
            pass
        _FONT_CACHE[key] = f
    return f


def serif(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    return _font("PlayfairDisplay.ttf", size, weight)


def sans(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    return _font("Manrope.ttf", size, weight)


def ease(x: float) -> float:
    """Ease-out cubic on [0, 1]."""
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def fade_out(t: float, seconds: float, length: float = 0.3) -> float:
    return 1.0 if t < seconds - length else max(0.0, (seconds - t) / length)


def text_width(text: str, font: ImageFont.FreeTypeFont, tracking: float = 0.0) -> float:
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    return sum(d.textlength(ch, font=font) for ch in text) + tracking * max(0, len(text) - 1)


def draw_tracked(draw: ImageDraw.ImageDraw, xy: Tuple[float, float], text: str, font, fill, tracking: float = 0.0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def with_shadow(layer: Image.Image, strength: float = 0.55, blur: float = 6.0) -> Image.Image:
    """The layer over a soft dark shadow of itself (no outline)."""
    a = layer.split()[3]
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.putalpha(a.point(lambda v: int(v * strength)).filter(ImageFilter.GaussianBlur(blur)))
    return Image.alpha_composite(sh, layer)


_GRAD: Dict[Tuple, Image.Image] = {}


def soft_shade(box: Tuple[int, int, int, int], strength: float, blur: int = 90) -> Image.Image:
    """A faint dark glow behind a text block (never a box): full-frame RGBA."""
    key = (box, blur)
    if key not in _GRAD:
        g = Image.new("L", (W, H), 0)
        ImageDraw.Draw(g).ellipse(box, fill=110)
        _GRAD[key] = g.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.putalpha(_GRAD[key].point(lambda v: int(v * max(0.0, min(1.0, strength)))))
    return out


# ------------------------------------------------------------------ act card
@dataclass
class ActCard:
    """v2 (the owner, 2026-10-28: bolder, clearer): the shot eases ~35 % darker with a slight blur, the gold rule
    draws out from the centre (300 ms), the label fades in, the title reveals line by line with a mask wipe and a
    104 -> 100 % scale settle (450 ms ease-out), holds, then everything fades in 250 ms. Pass the shot's frame as
    `bg` (the darken and blur are of the picture itself); without it only the text layer is returned."""
    label: str                       # "ACT 2"
    title: str                       # "The Flood That Went to the Wrong Lake"
    seconds: float = 2.8
    dim: float = 0.35

    def lines(self) -> List[str]:
        f = serif(92, 800)
        if text_width(self.title, f) <= W - 2 * SAFE_X - 120:
            return [self.title]
        words = self.title.split()
        best, cut = 1e9, 1
        for k in range(1, len(words)):
            a, b = " ".join(words[:k]), " ".join(words[k:])
            d = abs(text_width(a, f) - text_width(b, f))
            if d < best:
                best, cut = d, k
        return [" ".join(words[:cut]), " ".join(words[cut:])]

    def frame(self, t: float, bg: Optional[Image.Image] = None) -> Image.Image:
        out_a = fade_out(t, self.seconds, 0.25)
        k_bg = ease(t / 0.4) * out_a
        if bg is not None:
            base = bg.convert("RGB")
            if k_bg > 0:
                soft = base.filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * (1 - self.dim)))
                base = Image.blend(base, soft, k_bg)
            img = base.convert("RGBA")
            img = Image.alpha_composite(img, _scale_alpha(_vignette(), k_bg * 0.8))
        else:
            img = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * self.dim * k_bg)))
        txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        lines = self.lines()
        tf = serif(92, 800)
        lh = 104
        block_h = 36 + 26 + lh * len(lines)
        top = (H - block_h) // 2 - 10
        # Label: ExtraBold tracked caps in a brighter gold.
        lf = sans(36, 800)
        a_lab = ease((t - 0.05) / 0.35) * out_a
        track = 36 * 0.16
        lw = text_width(self.label.upper(), lf, track)
        draw_tracked(d, ((W - lw) / 2, top), self.label.upper(), lf, GOLD2 + (int(255 * a_lab),), track)
        # The rule draws out from the centre: 3 px, 140 px wide, in 300 ms.
        rw = int(140 * ease((t - 0.05) / 0.3))
        ry = top + 36 + 14
        if rw > 1:
            d.rectangle([W // 2 - rw // 2, ry, W // 2 + rw // 2, ry + 2], fill=GOLD2 + (int(255 * out_a),))
        layer = with_shadow(txt, 0.75, 10)
        # Title lines: mask wipe left -> right + scale 104 -> 100 %, 450 ms ease-out, the second line 120 ms later.
        for i, line in enumerate(lines):
            p = ease((t - 0.15 - 0.12 * i) / 0.45)
            if p <= 0:
                continue
            tw = int(text_width(line, tf)) + 8
            tl = Image.new("RGBA", (tw + 40, lh + 40), (0, 0, 0, 0))
            ImageDraw.Draw(tl).text((20, 10), line, font=tf, fill=WHITE + (255,))
            tl = with_shadow(tl, 0.8, 10)
            mask = Image.new("L", tl.size, 0)
            ImageDraw.Draw(mask).rectangle([0, 0, int(tl.size[0] * p), tl.size[1]], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(6))
            tl.putalpha(ImageChops.multiply(tl.split()[3], mask).point(lambda v: int(v * out_a)))
            s = 1.04 - 0.04 * p
            tl = tl.resize((int(tl.size[0] * s), int(tl.size[1] * s)), Image.LANCZOS)
            y = top + 36 + 34 + i * lh - int((s - 1) * lh / 2)
            layer.alpha_composite(tl, (int((W - tl.size[0]) / 2), int(y)))
        return Image.alpha_composite(img, layer)


GOLD2 = (233, 190, 72)               # v2: a brighter gold


def _scale_alpha(im: Image.Image, k: float) -> Image.Image:
    out = im.copy()
    out.putalpha(im.split()[3].point(lambda v: int(v * max(0.0, min(1.0, k)))))
    return out


_VIG: List[Image.Image] = []


def _vignette() -> Image.Image:
    if not _VIG:
        g = Image.new("L", (W, H), 0)
        ImageDraw.Draw(g).ellipse([-W * 0.15, -H * 0.25, W * 1.15, H * 1.25], fill=255)
        g = ImageChops.invert(g.filter(ImageFilter.GaussianBlur(220))).point(lambda v: int(v * 0.55))
        v = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        v.putalpha(g)
        _VIG.append(v)
    return _VIG[0]


# ------------------------------------------------------------------ number / lower third (lower-left, same place)
BLOCK_X = SAFE_X + 24
BLOCK_BOTTOM = H - SAFE_Y - 96              # above a player's control bar


def _format_like(target: str, value: float) -> str:
    import re
    m = re.search(r"\d[\d,]*(?:\.\d+)?", target)
    if not m:
        return target
    s = m.group(0)
    dec = len(s.split(".")[1]) if "." in s else 0
    txt = f"{value:,.{dec}f}" if "," in s else f"{value:.{dec}f}"
    return target[:m.start()] + txt + target[m.end():]


def _number_of(target: str) -> Optional[float]:
    import re
    m = re.search(r"\d[\d,]*(?:\.\d+)?", target)
    return float(m.group(0).replace(",", "")) if m else None


def _legible(txt: Image.Image, top: int, a: float) -> Image.Image:
    """v2 contrast: a soft dark gradient rising from the bottom-left behind the text area (never a box) and a
    stronger, wider shadow - readable over a bright sky."""
    shade = soft_shade((-420, top - 230, 1250, H + 330), 1.25 * a, blur=110)
    out = Image.alpha_composite(shade, with_shadow(txt, 0.55, 18))
    return Image.alpha_composite(out, with_shadow(txt, 0.85, 6))


@dataclass
class Number:
    """v2: ExtraBold 124 px figure, Bold 31 px caption (3-5 words) at 85 % white; a 600 ms count-up with the gold
    rule drawing in at the same time; 350 ms slide-up + fade in, 250 ms fade out."""
    value: str                      # "1,037.16 ft", "−40%"
    caption: str                    # "Lake Mead record low"
    seconds: float = 3.0
    count_from: Optional[float] = None   # None: no count-up

    def frame(self, t: float, bg: Optional[Image.Image] = None) -> Image.Image:
        out_a = fade_out(t, self.seconds, 0.25)
        a1 = ease(t / 0.35) * out_a
        a2 = ease((t - 0.1) / 0.35) * out_a
        size = 124 if len(self.value) <= 12 else 100
        nf, cf = sans(size, 800), sans(31, 700)
        val = self.value
        target = _number_of(self.value)
        if self.count_from is not None and target is not None and t < 0.6:
            val = _format_like(self.value, self.count_from + (target - self.count_from) * ease(t / 0.6))
        txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        cap_y = BLOCK_BOTTOM - 36
        num_y = cap_y - 6 - int(size * 1.12)
        dy1, dy2 = int(24 * (1 - ease(t / 0.35))), int(24 * (1 - ease((t - 0.1) / 0.35)))
        d.text((BLOCK_X - 3, num_y + dy1), val, font=nf, fill=WHITE + (int(255 * a1),))
        d.text((BLOCK_X, cap_y + dy2), self.caption, font=cf, fill=WHITE + (int(217 * a2),))
        gw = int(88 * ease(t / 0.6))
        if gw:
            gy = num_y + int(size * 0.22) - 16 + dy1
            d.rectangle([BLOCK_X, gy, BLOCK_X + gw, gy + 2], fill=GOLD2 + (int(255 * out_a),))
        layer = _legible(txt, num_y, a1)
        return Image.alpha_composite(bg.convert("RGBA"), layer) if bg is not None else layer


@dataclass
class LowerThird:
    """v2: name Bold 52 px, role Bold 30 px tracked caps; a 350 ms slide-in + fade; name and role only."""
    name: str
    role: str
    seconds: float = 4.0

    def frame(self, t: float, bg: Optional[Image.Image] = None) -> Image.Image:
        out_a = fade_out(t, self.seconds, 0.25)
        a1 = ease(t / 0.35) * out_a
        a2 = ease((t - 0.1) / 0.35) * out_a
        txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        nf, rf = sans(52, 700), sans(30, 700)
        role_y = BLOCK_BOTTOM - 34
        name_y = role_y - 10 - 62
        dx1, dx2 = int(-36 * (1 - ease(t / 0.35))), int(-36 * (1 - ease((t - 0.1) / 0.35)))
        d.text((BLOCK_X + dx1, name_y), self.name, font=nf, fill=WHITE + (int(255 * a1),))
        draw_tracked(d, (BLOCK_X + 2 + dx2, role_y), self.role.upper(), rf, (255, 255, 255, int(222 * a2)), 30 * 0.12)
        gw = int(88 * ease(t / 0.4))
        if gw:
            d.rectangle([BLOCK_X + dx1, name_y - 16, BLOCK_X + dx1 + gw, name_y - 14], fill=GOLD2 + (int(255 * a1),))
        layer = _legible(txt, name_y, a1)
        return Image.alpha_composite(bg.convert("RGBA"), layer) if bg is not None else layer


# ------------------------------------------------------------------ maps (real geography)
def merc(lon: float, lat: float) -> Tuple[float, float]:
    x = (lon + 180.0) / 360.0
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def _decode_topo(topo: dict) -> List[dict]:
    """TopoJSON (quantized) -> [{props, rings: [[(lon, lat)...]...]}] for Polygon / MultiPolygon."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx: List[int]):
        out: List[Tuple[float, float]] = []
        for i in idx:
            seg = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
            out.extend(seg if not out else seg[1:])
        return out

    feats = []
    for obj in topo["objects"].values():
        for g in obj["geometries"]:
            polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"] if g["type"] == "MultiPolygon" else []
            rings = [ring(r) for p in polys for r in p]
            feats.append({"props": g.get("properties") or {}, "rings": rings})
    return feats


_GEO: Dict[str, object] = {}


def states(codes: Optional[Sequence[str]] = None) -> List[dict]:
    """US states + Mexican states (Natural Earth 1:10m admin-1, the maps-v2 extract in assets)."""
    if "states" not in _GEO:
        with open(os.path.join(ASSETS, "geo", "ne_admin1_na.json"), encoding="utf-8") as fh:
            _GEO["states"] = json.load(fh)
    feats = _GEO["states"]
    return [f for f in feats if codes is None or f["code"] in codes]


def lake_rings(name: str) -> List[List[Tuple[float, float]]]:
    """A lake's outline: the OpenStreetMap shape when it is in assets (Lake Mead, Powell, Mohave, Havasu - the
    Natural Earth polygon is too coarse at a regional zoom), else Natural Earth's (src/geodata/lakes.json)."""
    if "osm" not in _GEO:
        p = os.path.join(ASSETS, "geo", "osm_lakes.json")
        _GEO["osm"] = json.load(open(p, encoding="utf-8"))["lakes"] if os.path.isfile(p) else {}
    if name in _GEO["osm"]:
        return [[tuple(q) for q in r] for r in _GEO["osm"][name]]
    from . import automaps
    g = automaps.data()
    rec = g.lake(name)
    return [[tuple(p) for p in automaps.decode(r)] for r in (rec or {}).get("rings") or []]


def river_line(rid: str) -> List[Tuple[float, float]]:
    from . import automaps
    rec = automaps.data().river(rid) or {}
    pts: List[Tuple[float, float]] = []
    for line in rec.get("lines") or []:
        pts.extend(tuple(p) for p in automaps.decode(line))
    return pts


@dataclass
class Label:
    text: str
    lon: float
    lat: float
    at: float = 0.0                  # seconds after the start (its spoken word)
    kind: str = "place"              # "place" | "state" | "pin"
    dx: int = 14
    dy: int = -16


@dataclass
class MapScene:
    bbox: Tuple[float, float, float, float]          # lon0, lat0, lon1, lat1 (16:9 is fitted around it)
    seconds: float = 5.0
    lakes: Dict[str, float] = field(default_factory=dict)        # lake name -> highlight time
    # (river id, draw start, draw end, from (lon, lat), to (lon, lat)): the stretch between the two points draws in
    river: Optional[Tuple[str, float, float, Optional[Tuple[float, float]], Optional[Tuple[float, float]]]] = None
    shade_states: Dict[str, Tuple[float, Tuple[int, int, int]]] = field(default_factory=dict)  # code -> (t, rgb)
    labels: List[Label] = field(default_factory=list)
    push: float = 0.06
    focus: Optional[Tuple[float, float]] = None
    _base: Optional[Image.Image] = None

    # 2x canvas for the push
    S = 2

    def _fit(self):
        lon0, lat0, lon1, lat1 = self.bbox
        x0, y1 = merc(lon0, lat0)
        x1, y0 = merc(lon1, lat1)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        if w / h < W / H:
            w = h * W / H
        else:
            h = w * H / W
        self._view = (cx - w / 2, cy - h / 2, w, h)

    def px(self, lon: float, lat: float) -> Tuple[float, float]:
        x, y = merc(lon, lat)
        vx, vy, vw, vh = self._view
        return (x - vx) / vw * W * self.S, (y - vy) / vh * H * self.S

    def _relief(self) -> Image.Image:
        """Natural Earth relief tiles (z5, 256 px) stitched for the view, blurred: a soft terrain texture."""
        z, n = 5, 32
        vx, vy, vw, vh = self._view
        tx0, tx1 = int(vx * n), int((vx + vw) * n)
        ty0, ty1 = int(vy * n), int((vy + vh) * n)
        mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (60, 60, 60))
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                p = os.path.join(ASSETS, "geo", "relief5", f"{tx}_{ty}.jpg")
                if os.path.isfile(p):
                    mosaic.paste(Image.open(p).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
        left = (vx * n - tx0) * 256
        top = (vy * n - ty0) * 256
        crop = mosaic.crop((int(left), int(top), int(left + vw * n * 256), int(top + vh * n * 256)))
        # z5 relief is ~23 px a degree: upscaled it must stay a soft terrain texture, never a blocky one.
        return crop.resize((W * self.S, H * self.S), Image.BICUBIC).filter(ImageFilter.GaussianBlur(14))

    def _hillshade(self) -> Optional[Image.Image]:
        """Hillshade from open DEM tiles (Terrarium PNGs: AWS Terrain Tiles, SRTM-derived; DEM_DIR) at the zoom that
        fits the view, sharper than the z5 relief. None when the tiles are not there."""
        import numpy as np
        root = os.getenv("DEM_DIR") or os.path.join(ASSETS, "geo", "terrarium")
        if not os.path.isdir(root):
            return None
        vx, vy, vw, vh = self._view
        for z in (9, 8, 7):
            n = 2 ** z
            tx0, tx1, ty0, ty1 = int(vx * n), int((vx + vw) * n), int(vy * n), int((vy + vh) * n)
            names = [os.path.join(root, f"{z}_{x}_{y}.png") for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
            if all(os.path.isfile(q) for q in names) and (tx1 - tx0 + 1) * 256 <= 6000:
                break
        else:
            return None
        mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), dtype=np.float32)
        for x in range(tx0, tx1 + 1):
            for y in range(ty0, ty1 + 1):
                a = np.asarray(Image.open(os.path.join(root, f"{z}_{x}_{y}.png")).convert("RGB"), dtype=np.float32)
                mosaic[(y - ty0) * 256:(y - ty0 + 1) * 256, (x - tx0) * 256:(x - tx0 + 1) * 256] =                     a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
        lat_c = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (vy + vh / 2)))))
        cell = 40075016.0 * math.cos(math.radians(lat_c)) / (256 * n)
        gy, gx = np.gradient(mosaic, cell)
        zf = 2.2                                           # gentle exaggeration so ranges read at map scale
        slope = np.arctan(zf * np.hypot(gx, gy))
        aspect = np.arctan2(-gx, gy)
        az, alt = math.radians(315), math.radians(42)
        hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
        hs = np.clip(hs, 0, 1)
        low = mosaic <= 0
        try:
            # The sea is the below-zero ground that reaches the edge of the tiles (Death Valley and the Salton
            # basin are below sea level too, but they are land).
            from scipy import ndimage
            lab, _n = ndimage.label(low)
            edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
            low = np.isin(lab, list(edge))
        except ImportError:
            low = mosaic <= -150
        sea = low.astype(np.float32)
        left, top = (vx * n - tx0) * 256, (vy * n - ty0) * 256
        box = (int(left), int(top), int(left + vw * n * 256), int(top + vh * n * 256))
        shade = Image.fromarray((hs * 255).astype(np.uint8)).crop(box).resize((W * self.S, H * self.S), Image.LANCZOS)
        self._sea = Image.fromarray((sea * 255).astype(np.uint8)).crop(box).resize((W * self.S, H * self.S))
        self._elev = Image.fromarray(np.clip(mosaic / 3500.0 * 255, 0, 255).astype(np.uint8)).crop(box).resize(
            (W * self.S, H * self.S), Image.BILINEAR)
        return shade.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))

    def base(self) -> Image.Image:
        if self._base is not None:
            return self._base
        self._fit()
        S = self.S
        img = Image.new("RGB", (W * S, H * S), (13, 19, 24))
        hill = self._hillshade()
        if hill is not None:
            # Land straight from the DEM: a warm desert tone lit by the hillshade, a touch lighter up high.
            import numpy as np
            h = np.asarray(hill, dtype=np.float32) / 255.0
            e = np.asarray(self._elev, dtype=np.float32) / 255.0
            # v2: a satellite-style colour relief - warm low desert, red-brown plateaus, grey-green high
            # forest, pale peaks - lit by the hillshade (deep shadows, bright sun-facing slopes).
            light = 0.22 + 0.95 * h ** 1.1
            stops = np.array([0.0, 0.18, 0.36, 0.55, 0.75, 1.0])
            cols = np.array([[176, 146, 104], [168, 122, 84], [150, 98, 70], [118, 112, 84], [96, 104, 84],
                             [205, 205, 200]], dtype=np.float32)
            rgb = np.stack([np.interp(e, stops, cols[:, c]) for c in range(3)], axis=-1) * light[..., None] * 0.92
            land_img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
            img.paste(land_img, (0, 0), ImageChops.invert(self._sea))
            d = ImageDraw.Draw(img, "RGBA")
            for f in states():
                for r in f["rings"]:
                    d.line([self.px(*p) for p in r] + [self.px(*r[0])], fill=(255, 255, 255, 52), width=2)
            self._base = img
            return img
        land = Image.new("L", img.size, 0)
        dl = ImageDraw.Draw(land)
        for f in states():
            for r in f["rings"]:
                dl.polygon([self.px(*p) for p in r], fill=255)
        relief = self._relief().convert("L")
        # Land: warm dark charcoal, the relief showing through.
        # Land: a warm, muted desert tone with the relief showing through softly (contrast kept low).
        land_rgb = Image.merge("RGB", [relief.point(lambda v, o=o, k=k: int(o + v * k))
                                       for o, k in ((44, 0.36), (36, 0.30), (30, 0.24))])
        img.paste(land_rgb, (0, 0), land)
        d = ImageDraw.Draw(img, "RGBA")
        for f in states():
            for r in f["rings"]:
                d.line([self.px(*p) for p in r] + [self.px(*r[0])], fill=(255, 255, 255, 46), width=2 * S // 2 + 1)
        self._base = img
        return img

    def frame(self, t: float, bg: Optional[Image.Image] = None) -> Image.Image:
        """v2: a slight 3D tilt, a slow push, lakes filling with colour, the river drawing on with a soft glow and a
        few slow flow particles, dam dots pulsing once, bold labels with a dark halo (3-4 a map)."""
        import numpy as np
        base = self.base().copy().convert("RGBA")
        S = self.S
        over = Image.new("RGBA", base.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for code, (at, rgb) in self.shade_states.items():
            a = ease((t - at) / 0.5)
            if a <= 0:
                continue
            for f in states([code]):
                for r in f["rings"]:
                    d.polygon([self.px(*p) for p in r], fill=rgb + (int(62 * a),))
                    d.line([self.px(*p) for p in r] + [self.px(*r[0])], fill=rgb + (int(220 * a),), width=4)
        base = Image.alpha_composite(base, over)
        lk = Image.new("RGBA", base.size, (0, 0, 0, 0))
        dk = ImageDraw.Draw(lk)
        for name, at in self.lakes.items():
            a = ease((t - at) / 0.6)                       # the lake fills in with colour
            if a <= 0:
                continue
            for r in lake_rings(name):
                dk.polygon([self.px(*p) for p in r], fill=(46, 150, 205, int(255 * a)))
        base = Image.alpha_composite(base, _scale_alpha(lk.filter(ImageFilter.GaussianBlur(14)), 0.9))
        base = Image.alpha_composite(base, lk)
        if self.river:
            rid, t0, t1, frm, to = self.river
            pts = river_line(rid)
            if frm and to and pts:
                from . import automaps
                i0 = automaps.nearest_vertex([list(p) for p in pts], frm)[0]
                i1 = automaps.nearest_vertex([list(p) for p in pts], to)[0]
                pts = pts[min(i0, i1):max(i0, i1) + 1]
                if i0 > i1:
                    pts = pts[::-1]                       # draw from `from` to `to`
            k = ease((t - t0) / max(0.1, t1 - t0))
            if k > 0 and len(pts) > 1:
                xy = [self.px(*p) for p in pts]
                seg = np.hypot(np.diff([p[0] for p in xy]), np.diff([p[1] for p in xy]))
                cum = np.concatenate([[0.0], np.cumsum(seg)])
                total = float(cum[-1]) or 1.0
                upto = total * k
                n = int(np.searchsorted(cum, upto))
                drawn = xy[:max(2, n)]
                rl = Image.new("RGBA", base.size, (0, 0, 0, 0))
                ImageDraw.Draw(rl).line(drawn, fill=(150, 220, 255, 255), width=6, joint="curve")
                base = Image.alpha_composite(base, _scale_alpha(rl.filter(ImageFilter.GaussianBlur(9)), 0.95))
                base = Image.alpha_composite(base, rl)
                # Flow particles: a few soft dots drifting slowly along the drawn river.
                pl = Image.new("RGBA", base.size, (0, 0, 0, 0))
                dp = ImageDraw.Draw(pl)
                for j in range(7):
                    pos = ((j / 7.0) + 0.06 * max(0.0, t - t0)) % 1.0 * upto
                    q = int(np.searchsorted(cum, pos))
                    if 0 < q < len(xy):
                        f = (pos - cum[q - 1]) / max(1e-6, cum[q] - cum[q - 1])
                        x = xy[q - 1][0] + (xy[q][0] - xy[q - 1][0]) * f
                        y = xy[q - 1][1] + (xy[q][1] - xy[q - 1][1]) * f
                        dp.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(235, 250, 255, 230))
                base = Image.alpha_composite(base, pl.filter(ImageFilter.GaussianBlur(3)))
        # The slow push (crop of the 2x canvas).
        z = 1.0 + self.push * ease(t / max(0.1, self.seconds))
        fx, fy = self.px(*self.focus) if self.focus else (W * S / 2, H * S / 2)
        cw, ch = W * S / z, H * S / z
        x0 = min(max(0, fx - cw / 2), W * S - cw)
        y0 = min(max(0, fy - ch / 2), H * S - ch)
        flat = base.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((W, H), Image.LANCZOS)
        # A slight 3D tilt: the bottom comes closer (the plane leans back), no empty corners.
        k = TILT
        src = [(0, 0), (W, 0), (W - k * W, H), (k * W, H)]
        dst = [(0, 0), (W, 0), (W, H), (0, H)]
        frame = flat.transform((W, H), Image.PERSPECTIVE, _persp(dst, src), Image.BICUBIC)
        fwd = _homography(src, dst)

        def place(lon, lat):
            X, Y = self.px(lon, lat)
            X, Y = (X - x0) * W / cw, (Y - y0) * H / ch
            v = fwd @ np.array([X, Y, 1.0])
            return v[0] / v[2], v[1] / v[2]

        out_a = fade_out(t, self.seconds, 0.3)
        frame = Image.alpha_composite(frame, _scale_alpha(_vignette(), 0.9))
        txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d2 = ImageDraw.Draw(txt)
        dd = ImageDraw.Draw(dots)
        for lab in self.labels:
            a = ease((t - lab.at) / 0.35) * out_a
            if a <= 0:
                continue
            X, Y = place(lab.lon, lab.lat)
            dy = int(10 * (1 - ease((t - lab.at) / 0.35)))
            if lab.kind == "state":
                f = sans(28, 800)
                tw = text_width(lab.text.upper(), f, 28 * 0.16)
                draw_tracked(d2, (X - tw / 2, Y - 14 + dy), lab.text.upper(), f, (255, 255, 255, int(225 * a)),
                             28 * 0.16)
                continue
            if lab.kind == "pin":
                tp = t - lab.at                              # one pulse: a ring grows and fades
                if 0 < tp < 0.9:
                    rr = 9 + 34 * ease(tp / 0.9)
                    dd.ellipse([X - rr, Y - rr, X + rr, Y + rr], outline=GOLD2 + (int(230 * (1 - tp / 0.9)),),
                               width=3)
                r = 9
                dd.ellipse([X - r - 3, Y - r - 3, X + r + 3, Y + r + 3], fill=(255, 255, 255, int(240 * a)))
                dd.ellipse([X - r, Y - r, X + r, Y + r], fill=GOLD2 + (int(255 * a),))
            f = sans(37, 700)
            tw = text_width(lab.text, f)
            tx, ty = (X + lab.dx if lab.dx >= 0 else X + lab.dx - tw), Y + lab.dy
            if abs(lab.dx) > 40 or abs(lab.dy) > 40:
                ax = tx if lab.dx > 0 else tx + tw
                d2.line([(X + (8 if lab.dx > 0 else -8), Y + (8 if lab.dy > 0 else -8)), (ax, ty + 4)],
                        fill=(255, 255, 255, int(220 * a)), width=3)
                ty = ty - 42 if lab.dy < 0 else ty
            else:
                ty = ty - 24
            d2.text((tx, ty + dy), lab.text, font=f, fill=(255, 255, 255, int(255 * a)),
                     stroke_width=2, stroke_fill=(10, 14, 18, int(150 * a)))
        frame = Image.alpha_composite(frame, dots)
        frame = Image.alpha_composite(frame, with_shadow(txt, 0.95, 7))
        a_in = ease(t / 0.35)
        frame.putalpha(int(255 * min(a_in, out_a)))
        return Image.alpha_composite(bg.convert("RGBA"), frame) if bg is not None else frame


TILT = 0.055


def _homography(src, dst):
    """3x3 matrix mapping src points to dst points (4 pairs)."""
    import numpy as np
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
    b = [c for p in dst for c in p]
    h = np.linalg.solve(np.array(A, dtype=float), np.array(b, dtype=float))
    return np.append(h, 1.0).reshape(3, 3)


def _persp(out_pts, in_pts):
    """PIL PERSPECTIVE coefficients: for each output pixel, where to read the input."""
    m = _homography(out_pts, in_pts)
    return tuple((m / m[2, 2]).flatten()[:8])
