"""
Style Match: reference-vs-ours stills (2026-10-14).

For each element of a kit: the reference frame with its element (left) and the frame just BEFORE the element
appeared with OUR element drawn from the kit at the same place (right), labelled with the kit's confidence. The
drawing here is a PIL mirror of the renderer's text look (font, stretch, cap height, fill, stroke, glow band,
shadow, box, tilt) - quick enough for the worker, no browser needed.

    stills(video, meas, kit, out_dir) -> [{"element", "path", "confidence"}]
    draw_text(img, el, text, x, y) -> img    (also used by the proof scripts)
"""
import math
import os
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import fonts, measure


def _rgb(h: str, a: int = 255):
    h = str(h or "#000000").lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def text_layer(el: dict, text: str, H: int) -> Optional[Image.Image]:
    """One text element as an RGBA image (tight, before tilt) at frame height H."""
    t = el["text"]
    f = t.get("font") or {}
    p = fonts.path(f.get("family") or fonts.DEFAULT[0], f.get("weight") or fonts.DEFAULT[1])
    if not p:
        return None
    if t.get("case") == "upper":
        text = text.upper()
    cap = max(6.0, t["size"] * H)
    probe = ImageFont.truetype(p, 200)
    bb = probe.getbbox("H")
    font = ImageFont.truetype(p, max(6, int(round(200 * cap / max(1, bb[3] - bb[1])))))
    sw = int(round((t.get("stroke") or {}).get("width", 0) * H))
    gw = int(round((t.get("glow") or {}).get("width", 0) * H))
    pad = int(cap * 0.8) + sw + gw + 8
    l, tp, r, b = font.getbbox(text)
    W0, H0 = r - l + 2 * pad, b - tp + 2 * pad
    org = (pad - l, pad - tp)
    layer = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))
    if t.get("shadow"):
        sh = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))
        o = max(1, int(t["shadow"]["offset"] * H))
        ImageDraw.Draw(sh).text((org[0] + o, org[1] + o), text, font=font, fill=(0, 0, 0, int(255 * t["shadow"]["strength"])),
                                stroke_width=sw, stroke_fill=(0, 0, 0, 255))
        layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(max(1, o))))
    if gw:
        g = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))
        ImageDraw.Draw(g).text(org, text, font=font, fill=_rgb(t["glow"]["color"]), stroke_width=sw + gw,
                               stroke_fill=_rgb(t["glow"]["color"]))
        layer = Image.alpha_composite(layer, g.filter(ImageFilter.GaussianBlur(max(1, gw // 3))))
    ImageDraw.Draw(layer).text(org, text, font=font, fill=_rgb(t["fill"]), stroke_width=sw,
                               stroke_fill=_rgb((t.get("stroke") or {}).get("color") or "#000000"))
    st = float(f.get("stretch") or 1.0)
    if abs(st - 1) > 0.02:
        layer = layer.resize((max(1, int(layer.width * st)), layer.height), Image.BICUBIC)
    sl = float(f.get("slant") or 0)
    if abs(sl) > 0.5:
        k = math.tan(math.radians(sl))
        layer = layer.transform(layer.size, Image.AFFINE, (1, k, -k * layer.height / 2, 0, 1, 0), Image.BICUBIC)
    bbox = layer.getbbox()
    if bbox:
        layer = layer.crop(bbox)
    bx = t.get("box")
    if bx:
        px, py = int(bx["padX"] * H), int(bx["padY"] * H)
        bh = int((bx.get("height") or 0) * H)
        hh = max(layer.height + 2 * py, bh)
        box = Image.new("RGBA", (layer.width + 2 * px, hh), (0, 0, 0, 0))
        ImageDraw.Draw(box).rounded_rectangle((0, 0, box.width - 1, box.height - 1), radius=int(bx["radius"] * H),
                                              fill=_rgb(bx["color"], int(255 * bx.get("opacity", 1))))
        box.alpha_composite(layer, (px, (hh - layer.height) // 2))
        layer = box
    return layer


def draw_text(img: Image.Image, el: dict, text: str, x: float, y: float, tilt: float = 0.0,
              scale: float = 1.0) -> Image.Image:
    """Our element on a frame, centred at (x, y) shares of the frame."""
    layer = text_layer(el, text, img.height)
    if layer is None:
        return img
    if abs(scale - 1) > 0.01:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BICUBIC)
    if abs(tilt) > 0.3:
        layer = layer.rotate(tilt, Image.BICUBIC, expand=True)
    out = img.convert("RGBA")
    out.alpha_composite(layer, (int(x * img.width - layer.width / 2), int(y * img.height - layer.height / 2)))
    return out.convert("RGB")


def draw_mark(img: Image.Image, m: dict, box) -> Image.Image:
    """A ring / arrow / pointer from the kit inside box (x0, y0, x1, y1 shares)."""
    W, H = img.size
    x0, y0, x1, y1 = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    c = _rgb(m.get("color") or "#FF0000")
    if m["kind"] == "circle":
        w = max(3, int((m.get("strokeW") or 0.02) * H))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((x0, y0, x1, y1), outline=c, width=w * 2)
        lay = Image.alpha_composite(lay, glow.filter(ImageFilter.GaussianBlur(w)))
        ImageDraw.Draw(lay).ellipse((x0, y0, x1, y1), outline=c, width=w)
    elif m["kind"] == "pointer":
        d.polygon([(x0, y0), (x1, y0), ((x0 + x1) / 2, y1)], fill=c)
    else:   # arrow pointing up-left at the face, with a darker extruded side
        L, Wd = y1 - y0, (x1 - x0)
        pts = [(0.5, 0.0), (1.0, 0.45), (0.66, 0.45), (0.66, 1.0), (0.34, 1.0), (0.34, 0.45), (0.0, 0.45)]
        P = [(x0 + px * Wd, y0 + py * L) for px, py in pts]
        dark = tuple(int(v * 0.6) for v in c[:3]) + (255,)
        e = max(2, int(0.012 * H))
        d.polygon([(px + e, py) for px, py in P], fill=dark)
        d.polygon(P, fill=c)
    out = img.convert("RGBA")
    out.alpha_composite(lay)
    return out.convert("RGB")


def _label(img: Image.Image, txt: str) -> Image.Image:
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype(fonts.path("Inter", 800) or "", 22)
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    d.rectangle((0, 0, img.width, 34), fill=(0, 0, 0))
    d.text((10, 5), txt, font=f, fill=(255, 255, 255))
    return img


def pair(ref: np.ndarray, clean: np.ndarray, el: dict, text: str, inst: dict, conf, name: str) -> Image.Image:
    H = 720
    a = Image.fromarray(ref[..., ::-1]).resize((1280, H))
    b = Image.fromarray(clean[..., ::-1]).resize((1280, H))
    x, y = (inst["x0"] + inst["x1"]) / 2, (inst["y0"] + inst["y1"]) / 2
    if el["text"].get("box") and el["position"].get("y"):
        y = el["position"]["y"]
    b = draw_text(b, el, text, x, y, el.get("tilt", {}).get("median", 0.0))
    _label(a, f"REFERENCE  {name}")
    _label(b, f"OURS (from the kit)  confidence {conf}")
    out = Image.new("RGB", (2560, H))
    out.paste(a, (0, 0))
    out.paste(b, (1280, 0))
    return out


def stills(path: str, meas: dict, kit: dict, out_dir: str, limit: int = 8) -> List[dict]:
    os.makedirs(out_dir, exist_ok=True)
    pr = meas.get("probe") or measure.probe(path)
    W, H = pr["width"], pr["height"]
    rows = []
    by_text = {}
    for g in meas.get("groups") or []:
        for s in g.get("samples") or []:
            tx = (s.get("vision") or {}).get("text")
            if tx:
                by_text[(round(s["inst"]["t0"], 2))] = (s, tx)
    for el in (kit.get("elements") or [])[:limit]:
        ex = next((x for x in el.get("examples") or [] if round(x["t"], 2) in by_text), None)
        if not ex:
            continue
        s, tx = by_text[round(ex["t"], 2)]
        inst = s["inst"]
        ref = measure.frame_at(path, (inst["t0"] + inst["t1"]) / 2, W, H)
        clean = measure.frame_at(path, max(0.0, inst["t0"] - 0.25), W, H)
        if ref is None or clean is None:
            continue
        img = pair(ref, clean, el, tx, inst, el["confidence"].get("overall"), el["name"])
        p = os.path.join(out_dir, f"{el['id']}.jpg")
        img.save(p, quality=88)
        rows.append({"element": el["id"], "path": p, "confidence": el["confidence"].get("overall")})
    for m in (kit.get("marks") or [])[:3]:
        src = next((x for x in meas.get("marks") or [] if f"{(x.get('vision') or {}).get('mark') or x['shape']}" in m["id"]), None)
        if not src:
            continue
        ref = measure.frame_at(path, (src["t0"] + src["t1"]) / 2, W, H)
        clean = measure.frame_at(path, max(0.0, src["t0"] - 0.25), W, H)
        if ref is None or clean is None:
            continue
        a = _label(Image.fromarray(ref[..., ::-1]).resize((1280, 720)), f"REFERENCE  {m['kind']}")
        b = _label(draw_mark(Image.fromarray(clean[..., ::-1]).resize((1280, 720)), m,
                             (src["x0"], src["y0"], src["x1"], src["y1"])), f"OURS  confidence {m['confidence']['overall']}")
        out = Image.new("RGB", (2560, 720))
        out.paste(a, (0, 0))
        out.paste(b, (1280, 0))
        p = os.path.join(out_dir, f"mark-{m['id']}.jpg")
        out.save(p, quality=88)
        rows.append({"element": m["id"], "path": p, "confidence": m["confidence"]["overall"]})
    return rows
