"""
400 % zoom comparison: each reference element next to ours, ours drawn over the SAME reference background at
the same position and size.
  python scripts/celeb/zoom_compare.py [<refs dir>] [<out.jpg>]

Backgrounds for "ours": the reference shot just before the element (u_before_circle, r_before_arrow) where one
exists; otherwise the reference frame itself with the element painted out (OpenCV inpaint), so the comparison is
on the same picture. Ours is drawn at 1080p on the background scaled up, then scaled back to the 720p reference.
Rows (r5): ring 100 % + glow 400 %, pop edge on dark / skin / dark-2 at 400 %, name label + its under-side
at 400 %, film title card 100 % + text at 400 %, speed lines 50 % + one wedge at 400 %, red arrow, pointer.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.celeb import fx  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REF = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "..", "docs", "style-refs", "celeb-elements")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REF, "..", "celeb_zoom_compare_400_r5.jpg")
S = 720 / fx.H                          # ours (1080) -> reference scale (720)
MAGENTA = (255, 0, 255)


def load(name):
    return Image.open(os.path.join(REF, name)).convert("RGB")


def painted_out(name, mask_fn, grow=6):
    """The reference frame with an element removed (mask_fn(rgb int array) -> bool mask), by inpainting."""
    import cv2
    im = load(name)
    a = np.asarray(im).astype(int)
    m = mask_fn(a).astype(np.uint8) * 255
    m = cv2.dilate(m, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
    bgr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    out = cv2.inpaint(bgr, m, 9, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def yellow(a):
    return (a[..., 0] > 140) & (a[..., 1] > 120) & (a[..., 2] < 110)


def over(bg720, items):
    """Draw [(image, x, y)] (1080p coordinates) over a 720p background; returns the 720p result."""
    big = bg720.resize((fx.W, fx.H), Image.LANCZOS).convert("RGBA")
    for im, x, y in items:
        fx._paste(big, im, int(x), int(y))
    return big.convert("RGB").resize(bg720.size, Image.LANCZOS)


def fill_box(im, kind):
    a = np.asarray(im).astype(int)
    if kind == "yellow":
        m = (a[..., 0] > 200) & (a[..., 1] > 200) & (a[..., 2] < 90) & (a[..., 3] > 200)
    else:
        m = (a[..., :3].min(-1) > 215) & (a[..., 3] > 200)
    ys, xs = np.nonzero(m)
    return xs.min(), ys.min(), xs.max(), ys.max()


def aligned(im, kind, ref_box):
    """(im, x, y) placing im's fill box centre on the reference fill box centre (720p box -> 1080p)."""
    x0, y0, x1, y1 = fill_box(im, kind)
    rx = (ref_box[0] + ref_box[2]) / 2 / S
    ry = (ref_box[1] + ref_box[3]) / 2 / S
    return im, rx - (x0 + x1) / 2, ry - (y0 + y1) / 2


def row(ref_im, ours_im, label, z=4):
    a = ref_im.resize((int(ref_im.width * z), int(ref_im.height * z)), Image.NEAREST)
    b = ours_im.resize((int(ours_im.width * z), int(ours_im.height * z)), Image.NEAREST)
    r = Image.new("RGB", (a.width + b.width + 30, max(a.height, b.height) + 34), MAGENTA)
    r.paste(a, (0, 34))
    r.paste(b, (a.width + 30, 34))
    d = ImageDraw.Draw(r)
    d.text((6, 6), f"REFERENCE  {label}  ({int(z * 100)} %)", fill=(255, 255, 255))
    d.text((a.width + 36, 6), "OURS (r5)", fill=(255, 255, 255))
    return r


def both(ref_full, ours_full, box, label, z=4):
    return row(ref_full.crop(box), ours_full.crop(box), label, z)


def faced(bg_name):
    from src.celeb import faces
    bg = load(bg_name)
    big = bg.resize((fx.W, fx.H), Image.LANCZOS)
    f = faces.detect_rgb(np.array(big), fx.W, fx.H)
    return bg, faces.pick(f, "largest")


def ring_rows():
    ref = load("u_name_circle.jpg")
    # (1) tracked: the ring as the pipeline places it, on the shot before the reference's ring appears
    bg, face = faced("u_before_circle.jpg")
    c = fx.Circle("c", 0, 2, track=[face] * 90)
    tracked = over(bg, [c.draw(1.5)])
    # (2) same geometry as the reference ring (centre 395.5, 209.3, radius 265 at 720p) on the same shot
    c2 = fx.Circle("c", 0, 2, cx=395.5 / 1280, cy=209.3 / 720, r=265.0 / 720)
    same = over(bg, [c2.draw(1.5)])
    return [both(ref, tracked, (60, 0, 740, 520), "ring, placed by the face tracker", 0.5),
            both(ref, same, (100, 150, 230, 290), "ring edge + glow, left side", 4),
            both(ref, same, (180, 380, 330, 480), "ring edge + glow, lower left", 4)]


def pop_rows():
    out = []
    cases = [("u_pop_motherf.jpg", '"MOTHERF***"', (390, 472, 1039, 557), "pop on dark", (385, 455, 625, 575)),
             ("r_pop_hahaha.jpg", '"HA HA HA"', (281, 449, 737, 528), "pop on skin", (270, 430, 520, 545)),
             ("u_pop_omg.jpg", '"OMG..."', (644, 488, 999, 573), "pop on dark 2", (636, 470, 860, 590))]
    for name, text, ref_box, label, crop in cases:
        ref = load(name)
        bg = painted_out(name, lambda a, b=ref_box: _in_box(yellow(a) | _band(a), b, 26), grow=3)
        p = fx.Pop("p", 0, 1.4, text=text)
        im, _, _ = p.draw(1.25)
        ours = over(bg, [aligned(im, "yellow", ref_box)])
        out.append(both(ref, ours, crop, label + " (whole word)", 2))
        cx, cy = crop[0] + 20, (ref_box[1] + ref_box[3]) // 2
        out.append(both(ref, ours, (cx - 25, cy - 52, cx + 115, cy + 52), label + ": outer edge", 4))
    return out


def _band(a):
    """Dark-olive / dark outline pixels (to paint out with the pop)."""
    return (a[..., 2] < 40) & (a[..., 0] - a[..., 2] > 25)


def _in_box(m, box, pad):
    out = np.zeros_like(m)
    x0, y0, x1, y1 = box
    out[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
    return m | out


def label_rows():
    ref = load("u_name_circle.jpg")
    ref_box = (364, 626, 904, 678)
    bg = painted_out("u_name_circle.jpg", lambda a: _in_box(np.zeros(a.shape[:2], bool), ref_box, 14), grow=1)
    n = fx.NameLabel("n", 0, 2, text="JAKE GYLLENHAAL")
    im, _, _ = n.draw(1.5)
    ours = over(bg, [aligned(im, "white", ref_box)])
    return [both(ref, ours, (355, 610, 615, 700), "name label", 2),
            both(ref, ours, (360, 655, 520, 700), "name label under-side (stroke + shadow)", 4)]


def title_rows():
    ref = load("u_title_card_pointer.jpg")
    poster = os.path.join(os.environ.get("TEMP", "."), "celeb_r5_poster.png")
    ref.crop((1064, 458, 1247, 686)).save(poster)          # the reference's own poster picture
    box = (660, 440, 1280, 712)
    bg = painted_out("u_title_card_pointer.jpg",
                     lambda a: _in_box(np.zeros(a.shape[:2], bool), (676, 446, 1262, 702), 0), grow=1)
    tc = fx.TitleCard("t", 0, 2.6, poster=poster, title="Avengers", subtitle="Age of Ultron", year="2015")
    ours = over(bg, [tc.draw(1.3)])
    return [both(ref, ours, box, "film title card (settled)", 1),
            both(ref, ours, (800, 540, 960, 615), "title + subtitle", 4),
            both(ref, ours, (950, 595, 1075, 675), "subtitle end, bar, year, poster edge", 4),
            both(ref, ours, (1180, 640, 1275, 712), "poster border + shadow", 4)]


def speed_rows():
    ref = load("r_speed_lines.jpg")

    def lines(a):
        L = a.mean(-1)
        sat = a.max(-1) - a.min(-1)
        m = (L > 32) & (sat < 22)
        m[80:720, 360:960] = False                     # keep the person
        m[0:120, 0:130] = False                        # and the logo
        return m
    bg = painted_out("r_speed_lines.jpg", lines, grow=3)
    s = fx.SpeedLines("s", 0, 0.8, seed=3)
    drawn = s.draw(0.1)
    ours = over(bg, [drawn])
    # our lines fall at random angles: compare a wedge of ours that also meets the left edge
    a = np.asarray(drawn[0].getchannel("A"))[:, 6]
    ys = [int(y * S) for y in np.nonzero(a[int(140 / S):int(600 / S)])[0] + int(140 / S)] or [235]
    y = ys[len(ys) // 2]
    return [both(ref, ours, (0, 0, 1280, 720), "speed lines (ours: frame-centred, 32 lines, white 21 %)", 0.5),
            row(ref.crop((0, 180, 260, 290)), ours.crop((0, y - 55, 260, y + 55)),
                "speed lines, one wedge at the left edge (ours: the nearest of our wedges)", 2)]


def arrow_rows():
    ref = load("r_red_3d_arrow_settled.jpg")
    bg, face = faced("r_before_arrow.jpg")
    ours = over(bg, [fx.Arrow3D("a", 0, 1.0, track=[face] * 40).draw(0.4)])
    return [both(ref, ours, (520, 200, 860, 640), "red 3D arrow (regression check)", 0.75),
            both(ref, ours, (700, 480, 800, 560), "arrow side", 4)]


def pointer_rows():
    ref = load("u_title_card_pointer.jpg")
    ref_box = (788, 101, 883, 185)
    bg = painted_out("u_title_card_pointer.jpg",
                     lambda a: _in_box(np.zeros(a.shape[:2], bool), ref_box, 14), grow=1)
    p = fx.Pointer("p", 0, 1.6, cx=(ref_box[0] + ref_box[2]) / 2 / 1280, cy=ref_box[3] / 720)
    ours = over(bg, [p.draw(0.5)])
    return [both(ref, ours, (740, 60, 940, 230), "yellow pointer (regression check; this instance is 84 px tall)", 2)]


def main():
    rows = ring_rows() + pop_rows() + label_rows() + title_rows() + speed_rows() + arrow_rows() + pointer_rows()
    w = max(r.width for r in rows)
    out = Image.new("RGB", (w, sum(r.height for r in rows) + 6 * len(rows)), MAGENTA)
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + 6
    out.save(OUT, quality=82, optimize=True)
    print(os.path.abspath(OUT), out.size, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
