"""
400 % zoom comparison: the reference element next to ours, rendered at the same size on the same background.
  python scripts/celeb/zoom_compare.py <refs dir> <out.png>
Rows: pop text (dark bg), pop text (skin bg), name label, caption, ring, red arrow.
Each row: reference crop | ours, both at 720p scale, zoomed 4x (nearest), plus a column profile printout.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.celeb import fx  # noqa: E402

REF = sys.argv[1] if len(sys.argv) > 1 else r"C:\ThumGenius\docs\style-refs\celeb-elements"
OUT = sys.argv[2] if len(sys.argv) > 2 else "zoom_compare.png"
S = 720 / fx.H                          # ours (1080) -> reference scale (720)


def ref(name, box):
    return Image.open(os.path.join(REF, name)).convert("RGB").crop(box)


def ours_on(bg_rgb, size, draw_fn):
    """Our element drawn at 1080p on a flat background of the reference's colour, then scaled to 720p."""
    W, H = int(size[0] / S), int(size[1] / S)
    canvas = Image.new("RGBA", (W, H), tuple(bg_rgb) + (255,))
    im, x, y = draw_fn(W, H)
    canvas.alpha_composite(im, (x, y))
    return canvas.convert("RGB").resize(size, Image.LANCZOS)


def pop_fn(text, t=1.0, cap=None):
    def f(W, H):
        p = fx.Pop("p", 0, 1.4, text=text, **({"cap": cap} if cap else {}))
        im, _, _ = p.draw(t)
        return im, 10, (H - im.height) // 2
    return f


def name_fn(text):
    def f(W, H):
        n = fx.NameLabel("n", 0, 2, text=text)
        im, _, _ = n.draw(1.5)
        return im, 10, (H - im.height) // 2
    return f


def caption_fn(text, colour=None):
    from src.celeb.reel import Caption
    def f(W, H):
        c = Caption(0, 1, text, colour) if colour else Caption(0, 1, text)
        return c._im, 10, (H - c._im.height) // 2
    return f


def row(ref_im, ours_im, label):
    z = 4
    a = ref_im.resize((ref_im.width * z, ref_im.height * z), Image.NEAREST)
    b = ours_im.resize((ours_im.width * z, ours_im.height * z), Image.NEAREST)
    r = Image.new("RGB", (a.width + b.width + 30, max(a.height, b.height) + 40), (255, 0, 255))
    r.paste(a, (0, 40))
    r.paste(b, (a.width + 30, 40))
    d = ImageDraw.Draw(r)
    d.text((6, 8), "REFERENCE  " + label, fill=(255, 255, 255))
    d.text((a.width + 36, 8), "OURS", fill=(255, 255, 255))
    return r


def on_frame(before_png, element, t):
    from src.celeb import faces
    bg = Image.open(os.path.join(REF, before_png)).convert("RGB")
    big = bg.resize((fx.W, fx.H), Image.LANCZOS).convert("RGBA")
    f = faces.detect_rgb(np.array(big.convert("RGB")), fx.W, fx.H)
    face = faces.pick(f, "largest")
    element.track = [face] * 90
    im, x, y = element.draw(t)
    fx._paste(big, im, x, y)
    return big.convert("RGB").resize(bg.size, Image.LANCZOS), face


def overlay_rows():
    out = []
    ref_ring = Image.open(os.path.join(REF, "u_name_circle.png")).convert("RGB")
    ours_ring, _ = on_frame("u_before_circle.png", fx.Circle("c", 0, 2), 1.5)
    out.append(row(ref_ring.crop((60, 0, 740, 520)).resize((340, 260)), ours_ring.crop((60, 0, 740, 520)).resize((340, 260)),
                   "ring 100% (2x shown)"))
    out.append(row(ref_ring.crop((100, 200, 220, 300)), ours_ring.crop((100, 200, 220, 300)), "ring edge + glow 400%"))
    ref_arrow = Image.open(os.path.join(REF, "r_red_3d_arrow_settled.png")).convert("RGB")
    ours_arrow, _ = on_frame("r_before_arrow.png", fx.Arrow3D("a", 0, 1.0), 0.4)
    out.append(row(ref_arrow.crop((520, 200, 860, 640)).resize((255, 330)), ours_arrow.crop((520, 200, 860, 640)).resize((255, 330)),
                   "red arrow 100% (scaled)"))
    out.append(row(ref_arrow.crop((700, 480, 800, 560)), ours_arrow.crop((700, 480, 800, 560)), "arrow side 400%"))
    return out


def main():
    rows = []
    # pop on dark: ref u_pop_motherf 380-560 x 450-590 ; bg sampled top-left of the crop
    r1 = ref("u_pop_motherf.png", (385, 455, 625, 575))
    rows.append(row(r1, ours_on(np.array(r1)[3, 3], r1.size, pop_fn('"MOTHERF***"', 1.25)), "pop on dark"))
    r2 = ref("r_pop_hahaha.png", (270, 430, 520, 545))
    rows.append(row(r2, ours_on(np.array(r2)[5, 125], r2.size, pop_fn('"HA HA HA"', 1.25)), "pop on skin"))
    r3 = ref("u_name_circle.png", (355, 610, 615, 700))
    rows.append(row(r3, ours_on((20, 18, 10), r3.size, name_fn("JAKE GYLLENHAAL")), "name label"))
    r4 = ref("u_caption_pill.png", (300, 625, 560, 715))
    rows.append(row(r4, ours_on(np.array(r4)[2, 2], r4.size, caption_fn("YOU GONNA HAVE A GAG REEL ON THIS?")), "caption"))
    r5 = ref("b_caption_white.png", (420, 625, 700, 715))
    rows.append(row(r5, ours_on(np.array(r5)[2, 2], r5.size, caption_fn("I KNOW THAT, JIMMY", (255, 255, 255, 255))),
                    "caption, 2nd speaker = white (B4rM 89 s: Tom answers Kimmel)"))
    # ring and arrow: ours drawn on the SAME shot a few frames before the reference's element appears,
    # placed by the local face detector; full element at 100 % + a 400 % crop of the edge
    rows += overlay_rows()
    w = max(r.width for r in rows)
    out = Image.new("RGB", (w, sum(r.height for r in rows)), (255, 0, 255))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height
    out.save(OUT)
    print(OUT, out.size)


if __name__ == "__main__":
    main()
