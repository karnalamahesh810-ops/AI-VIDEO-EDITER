"""
Style Match font library + font matching (2026-10-14).

The library is free, commercial-safe type only: Google Fonts families (SIL OFL 1.1, Roboto Apache 2.0), the same
families the renderer loads through @remotion/google-fonts (remotion/src/components/smart/styleFonts.ts keeps the
same list; tests/test_style_match.py checks it). A family's TTF is fetched once from the Google Fonts CSS API and
cached under STYLE_FONT_DIR (the image can bake it with scripts/fetch_style_fonts.py).

    match(mask, text) -> [{"family", "weight", "class", "score", "stretch", "slant"} ...] best first

How the match works: the measured glyphs (a binary mask of the text's fill colour, already level) are compared
with the same words set in every library face at the same cap height. Each candidate is tried with a horizontal
stretch (the reference's width / ours, 0.7-1.5: a 130 % Bangers is how Komika Axis is matched) and a few slants
(the faux italic of comic faces); the score is the best overlap (IoU) after a small shift search. A family that
needs a large stretch is penalised a little, so an exact face beats a distorted near-miss.
"""
import math
import os
import re
import threading
from typing import Dict, List, Optional

try:
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

# family, weight, class, licence.  Classes let the kit say what KIND of face it is when the score is low.
LIBRARY = [
    ("Bangers", 400, "comic", "OFL"), ("Luckiest Guy", 400, "comic", "OFL"), ("Titan One", 400, "comic", "OFL"),
    ("Bowlby One", 400, "comic", "OFL"), ("Lilita One", 400, "comic", "OFL"), ("Chewy", 400, "comic", "OFL"),
    ("Bungee", 400, "display", "OFL"), ("Fredoka", 700, "rounded", "OFL"), ("Baloo 2", 800, "rounded", "OFL"),
    ("Montserrat", 800, "geometric", "OFL"), ("Montserrat", 900, "geometric", "OFL"),
    ("Poppins", 700, "geometric", "OFL"), ("Poppins", 900, "geometric", "OFL"), ("Nunito", 900, "rounded", "OFL"),
    ("Rubik", 800, "geometric", "OFL"), ("Raleway", 800, "geometric", "OFL"),
    ("Inter", 800, "grotesk", "OFL"), ("Roboto", 900, "grotesk", "Apache-2.0"), ("Archivo Black", 400, "grotesk", "OFL"),
    ("Work Sans", 800, "grotesk", "OFL"), ("Open Sans", 800, "grotesk", "OFL"),
    ("Oswald", 700, "condensed", "OFL"), ("Anton", 400, "condensed", "OFL"), ("Bebas Neue", 400, "condensed", "OFL"),
    ("Barlow Condensed", 800, "condensed", "OFL"), ("Teko", 600, "condensed", "OFL"),
    ("Fjalla One", 400, "condensed", "OFL"), ("League Gothic", 400, "condensed", "OFL"),
    ("Playfair Display", 800, "serif", "OFL"), ("Merriweather", 900, "serif", "OFL"), ("Lora", 700, "serif", "OFL"),
    ("Source Serif 4", 700, "serif", "OFL"), ("Cinzel", 700, "serif", "OFL"), ("DM Serif Display", 400, "serif", "OFL"),
    ("Abril Fatface", 400, "serif", "OFL"), ("Roboto Slab", 800, "slab", "OFL"), ("Arvo", 700, "slab", "OFL"),
    ("JetBrains Mono", 800, "mono", "OFL"), ("Courier Prime", 700, "mono", "OFL"), ("Space Mono", 700, "mono", "OFL"),
    ("Permanent Marker", 400, "hand", "OFL"), ("Caveat", 700, "hand", "OFL"), ("Rubik Mono One", 400, "display", "OFL"),
    ("Russo One", 400, "display", "OFL"), ("Black Ops One", 400, "display", "OFL"),
]
DEFAULT = ("Montserrat", 800)
FONT_DIR = os.getenv("STYLE_FONT_DIR", "/opt/style_fonts")
_LOCK = threading.Lock()


def key(family: str, weight: int) -> str:
    return f"{re.sub(r'[^A-Za-z0-9]+', '', family)}-{int(weight)}"


def info(family: str) -> Optional[dict]:
    for f, w, c, lic in LIBRARY:
        if f.lower() == str(family or "").lower():
            return {"family": f, "weight": w, "class": c, "licence": lic}
    return None


def path(family: str, weight: int, fetch: bool = True) -> Optional[str]:
    """The cached TTF of one library face (fetched from Google Fonts on first use); None when unavailable."""
    p = os.path.join(FONT_DIR, key(family, weight) + ".ttf")
    if os.path.isfile(p) and os.path.getsize(p) > 1000:
        return p
    if not fetch:
        return None
    with _LOCK:
        if os.path.isfile(p) and os.path.getsize(p) > 1000:
            return p
        try:
            import requests
            fam = family.replace(" ", "+")
            css = requests.get(f"https://fonts.googleapis.com/css2?family={fam}:wght@{int(weight)}", timeout=30,
                               headers={"User-Agent": "thumbgenius-style-match/1.0"}).text
            m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css)
            if not m:
                return None
            data = requests.get(m.group(1), timeout=60).content
            if len(data) < 1000:
                return None
            os.makedirs(FONT_DIR, exist_ok=True)
            tmp = p + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, p)
            return p
        except Exception as e:  # noqa: BLE001 - a missing face is skipped, never fatal
            print(f"[style-match] font {family} {weight} not fetched: {type(e).__name__}", flush=True)
            return None


# ------------------------------------------------------------------ rendering + comparison
def render_mask(text: str, family: str, weight: int, cap_px: int = 56, slant: float = 0.0):
    """The words in one face as a tight binary mask, scaled so its CAP height is cap_px (None when unavailable)."""
    from PIL import Image, ImageDraw, ImageFont
    p = path(family, weight)
    if not p or np is None:
        return None
    try:
        probe = ImageFont.truetype(p, 200)
        bb = probe.getbbox("H")
        cap = max(1, bb[3] - bb[1])
        font = ImageFont.truetype(p, max(8, int(round(200 * cap_px / cap))))
    except Exception:  # noqa: BLE001
        return None
    l, t, r, b = font.getbbox(text)
    if r - l < 2 or b - t < 2:
        return None
    pad = cap_px
    img = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    ImageDraw.Draw(img).text((pad - l, pad - t), text, fill=255, font=font)
    if abs(slant) > 0.5:
        import math
        k = math.tan(math.radians(slant))
        img = img.transform(img.size, Image.AFFINE, (1, k, -k * img.size[1] / 2, 0, 1, 0), Image.BILINEAR)
    a = np.asarray(img) > 127
    return _tight(a)


def _tight(a):
    ys, xs = np.where(a)
    if not len(xs):
        return None
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _resize_mask(a, w: int, h: int):
    from PIL import Image
    im = Image.fromarray((a * 255).astype("uint8")).resize((max(1, w), max(1, h)), Image.BILINEAR)
    return np.asarray(im) > 127


def _weight_like(m, ref):
    """The candidate thickened or thinned (3x3 steps) to the reference's ink share: shapes are compared, not the
    stroke weight (a measured outline or a heavier cut of the same face must not change the winner)."""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return m
    want = ref.mean()
    best, err = m, abs(m.mean() - want)
    k = np.ones((3, 3), np.uint8)
    for it in (1, 2, 3):
        for op in (cv2.erode, cv2.dilate):
            c = op(m.astype(np.uint8), k, iterations=it) > 0
            e = abs(c.mean() - want)
            if e < err:
                best, err = c, e
    return best


def iou_shift(a, b, shift: int = 3) -> float:
    """Best IoU of two same-size-ish masks over small shifts (b moves)."""
    h, w = max(a.shape[0], b.shape[0]) + 2 * shift, max(a.shape[1], b.shape[1]) + 2 * shift
    A = np.zeros((h, w), bool)
    A[shift:shift + a.shape[0], shift:shift + a.shape[1]] = a
    best = 0.0
    for dy in range(0, 2 * shift + 1, 1):
        for dx in range(0, 2 * shift + 1, 1):
            B = np.zeros((h, w), bool)
            hh, ww = min(b.shape[0], h - dy), min(b.shape[1], w - dx)
            B[dy:dy + hh, dx:dx + ww] = b[:hh, :ww]
            inter = np.logical_and(A, B).sum()
            uni = np.logical_or(A, B).sum()
            if uni:
                best = max(best, inter / uni)
    return float(best)


_GLYPHS: Dict[tuple, object] = {}


def _glyph(ch: str, family: str, weight: int, slant: float):
    k = (ch, family, weight, slant)
    if k not in _GLYPHS:
        _GLYPHS[k] = render_mask(ch, family, weight, cap_px=64, slant=slant)
    return _GLYPHS[k]


def ref_glyphs(mask) -> List:
    """The measured letters, left to right (punctuation and dots dropped by height)."""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return []
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    comps = [(st[i][0], st[i][1], st[i][2], st[i][3], i) for i in range(1, n) if st[i][4] >= 4]
    if not comps:
        return []
    hmax = max(c[3] for c in comps)
    comps = sorted([c for c in comps if c[3] >= 0.5 * hmax], key=lambda c: c[0])
    return [(lab[y:y + h, x:x + w] == i) for x, y, w, h, i in comps]


def match_glyphs(mask, text: str, top: int = 3, slants=(0.0, -8.0, 8.0)) -> List[dict]:
    """Letter by letter: each measured letter against the same letter in each face (spacing and tracking do not
    matter, only the letter shapes and their width / height). Empty when the letters cannot be paired."""
    chars = [c for c in str(text) if c.isalnum()]
    refs = ref_glyphs(mask)
    if len(chars) < 2 or len(refs) != len(chars):
        return []
    S = 40
    rows = []
    for fam, wt, cls, lic in LIBRARY:
        for sl in slants:
            ious, ratios = [], []
            for ch, rg in zip(chars, refs):
                g = _glyph(ch, fam, wt, sl)
                if g is None or rg.shape[0] < 4:
                    continue
                ratios.append((rg.shape[1] / rg.shape[0]) / max(1e-3, g.shape[1] / g.shape[0]))
                a = _resize_mask(rg, S, S)
                b = _weight_like(_resize_mask(g, S, S), a)
                inter, uni = np.logical_and(a, b).sum(), np.logical_or(a, b).sum()
                ious.append(inter / uni if uni else 0.0)
            if len(ious) < max(2, len(chars) // 2):
                continue
            stretch = float(np.median(ratios))
            spread = float(np.std(np.log(np.maximum(1e-3, ratios))))     # one stretch fits all letters?
            sc = float(np.mean(ious)) * (1 - 0.5 * max(0.0, abs(stretch - 1) - 0.12)) * (1 - min(0.5, spread))
            rows.append({"family": fam, "weight": wt, "class": cls, "licence": lic, "score": round(sc, 3),
                         "stretch": round(stretch, 2), "slant": sl, "mode": "letters"})
    best: Dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: -r["score"]):
        best.setdefault(key(r["family"], r["weight"]), r)
    return sorted(best.values(), key=lambda r: -r["score"])[:top]


def match(mask, text: str, top: int = 3, families: Optional[List[str]] = None, slants=(0.0, -8.0, 8.0)) -> List[dict]:
    """Rank the library against a measured glyph mask of `text` (upright, tight). Empty when nothing to compare."""
    if np is None or mask is None or not str(text or "").strip():
        return []
    mask = _tight(np.asarray(mask, bool))
    if mask is None or mask.shape[0] < 8:
        return []
    if not families:
        line = pick_line(text, mask.shape[1] / mask.shape[0])
        got = match_glyphs(mask, line, top, slants) if line else []
        if got:
            return got
    H = 48
    sc = H / mask.shape[0]
    ref = _resize_mask(mask, int(round(mask.shape[1] * sc)), H)
    text = pick_line(text, ref.shape[1] / H)
    if not text:
        return []
    rows = []
    for fam, wt, cls, lic in LIBRARY:
        if families and fam not in families:
            continue
        for sl in slants:
            m = render_mask(text, fam, wt, cap_px=64, slant=sl)
            if m is None:
                continue
            # ours at the same full height (caps + any descender, like the measured mask), then stretched to width
            ours_w = m.shape[1] * H / m.shape[0]
            stretch = ref.shape[1] / max(1.0, ours_w)
            if not 0.6 <= stretch <= 1.6:
                continue
            ours = _resize_mask(m, ref.shape[1], H)
            s = iou_shift(ref, ours, 2)
            s *= 1.0 - 0.35 * max(0.0, abs(stretch - 1.0) - 0.08)
            rows.append({"family": fam, "weight": wt, "class": cls, "licence": lic, "score": round(s, 3),
                         "stretch": round(stretch, 2), "slant": sl})
    best: Dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: -r["score"]):
        best.setdefault(key(r["family"], r["weight"]), r)
    return sorted(best.values(), key=lambda r: -r["score"])[:top]


def pick_line(text: str, aspect: float) -> str:
    """The part of a read text that the measured mask holds: one of its lines (or the whole), by width/height."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in str(text).split("\n") if ln.strip()]
    cands = [" ".join(lines)] + lines
    for ln in lines:                  # the measured line may be part of a line: a run of its words
        ws = ln.split()[:8]
        cands += [r for r in (" ".join(ws[i:j]) for i in range(len(ws)) for j in range(i + 1, len(ws) + 1))
                  if len(r) * 2 >= len(ln)]          # at least half the line: a lone word of a sign never fits
    best, err = "", 9.0
    for c in dict.fromkeys(c for c in cands if c):
        a = _aspect(c)
        if a is None:
            continue
        e = abs(math.log(max(1e-3, a / max(1e-3, aspect))))
        if e < err:
            best, err = c, e
    return best if err < 0.45 else ""


_ASPECTS: Dict[str, Optional[float]] = {}


def _aspect(text: str) -> Optional[float]:
    if text not in _ASPECTS:
        m = render_mask(text, DEFAULT[0], DEFAULT[1], 48)
        _ASPECTS[text] = None if m is None else m.shape[1] / m.shape[0]
    return _ASPECTS[text]


_CAPS: Dict[str, float] = {}


def cap_ratio(family: str, weight: int) -> float:
    """A face's cap height as a share of its em (the renderer's font-size): ~0.70 for most, more for comic faces."""
    k = key(family, weight)
    if k not in _CAPS:
        r = 0.72
        p = path(family, weight)
        if p:
            try:
                from PIL import ImageFont
                bb = ImageFont.truetype(p, 1000).getbbox("H")
                r = max(0.4, min(1.0, (bb[3] - bb[1]) / 1000.0))
            except Exception:  # noqa: BLE001
                pass
        _CAPS[k] = r
    return _CAPS[k]


def prefetch(families: Optional[List[str]] = None) -> int:
    n = 0
    for fam, wt, _, _ in LIBRARY:
        if (not families or fam in families) and path(fam, wt):
            n += 1
    return n
