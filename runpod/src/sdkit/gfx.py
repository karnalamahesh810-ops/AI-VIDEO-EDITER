"""US Weather Alert graphics in the measured Global Storm Desk geometry (docs/style-refs/global-storm-desk/STYLE.md),
re-skinned with the owner's badge. Every graphic is a function of t (seconds since it started) -> RGBA 1920x1080.
  gfx.py demo   -> gfx_demo.png (all elements over a sample frame)"""
import math, os, sys
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FPS = 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Montserrat.ttf")
LOGO = ""                                            # configure(): the job's logo file; "" = a text badge or none
LOGO_TEXT = ""

NAVY_T, NAVY_B = (11, 40, 86), (5, 21, 49)          # logo box #0B2856 -> #051531
BAR_T, BAR_B = (27, 76, 160), (8, 41, 106)           # bar #1B4CA0 -> #08296A
RIM = (118, 156, 232)                                # #769CE8
RED = (222, 51, 73)                                  # divider #DE3349
TAB_T, TAB_B = (239, 62, 53), (199, 31, 26)          # tab #EF3E35 -> #C71F1A
CHIP_RED, CHIP_NAVY = (204, 35, 33), (14, 48, 118)   # #CC2321, #0E3076
PILL = (228, 48, 42)                                 # #E4302A
WHITE = (253, 253, 250)


@lru_cache(None)
def font(size, weight="ExtraBold"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def configure(logo_path="", text=""):
    """The job's logo (a local file) or, without one, its channel name on a plain badge."""
    global LOGO, LOGO_TEXT
    LOGO, LOGO_TEXT = logo_path or "", text or ""
    logo.cache_clear()
    bug.cache_clear()


@lru_cache(None)
def logo(h):
    if LOGO and os.path.isfile(LOGO):
        im = Image.open(LOGO).convert("RGBA")
        return im.resize((round(im.width * h / im.height), h), Image.LANCZOS)
    if not LOGO_TEXT:
        return Image.new("RGBA", (1, h), (0, 0, 0, 0))
    f = font(max(14, int(h * 0.42)), "ExtraBold")
    w = int(f.getlength(LOGO_TEXT)) + 12
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((6, h // 2), LOGO_TEXT, font=f, fill=WHITE + (255,), anchor="lm")
    return im


def vgrad(w, h, top, bot, alpha=255):
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        g.putpixel((0, y), tuple(round(top[i] + (bot[i] - top[i]) * k) for i in range(3)) + (alpha,))
    return g.resize((w, h))


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def with_alpha(im, k):
    if k >= 0.999:
        return im
    a = im.getchannel("A").point(lambda v: round(v * max(0.0, k)))
    out = im.copy()
    out.putalpha(a)
    return out


def shadow(layer, blur=10, strength=0.45, off=(0, 4)):
    a = layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: round(v * strength))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.putalpha(a)
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(sh, off)
    out.alpha_composite(layer)
    return out


# ------------------------------------------------------------------ logo bug (always on)
@lru_cache(None)
def bug():
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lg = with_alpha(logo(92), 0.92)
    im.alpha_composite(shadow(_pad(lg, 20), blur=8, strength=0.5), (36 - 20, 22 - 20))
    return im


def _pad(im, p):
    out = Image.new("RGBA", (im.width + 2 * p, im.height + 2 * p), (0, 0, 0, 0))
    out.alpha_composite(im, (p, p))
    return out


# ------------------------------------------------------------------ lower third
X0, Y0, Y1 = 60, 850, 999          # unit box; logo box x 60-330, bar to 1649
BOX_R, BAR_R = 330, 1649
TAB = (366, 802, 731, 849)


def wrap2(text, f, maxw):
    words = text.upper().split()
    best = [" ".join(words)]
    if f.getlength(best[0]) <= maxw:
        return best
    # the split whose longer line is shortest
    cands = []
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        cands.append((max(f.getlength(a), f.getlength(b)), [a, b]))
    return min(cands)[1]


@lru_cache(None)
def lt_parts(head, kicker):
    """Static pieces of one lower third (full size, positioned)."""
    box = vgrad(BOX_R - X0, Y1 - Y0, NAVY_T, NAVY_B)
    lg = logo(118)
    box.alpha_composite(lg, ((box.width - lg.width) // 2, (box.height - lg.height) // 2))
    bar = vgrad(BAR_R - BOX_R, Y1 - Y0, BAR_T, BAR_B, alpha=236)
    d = ImageDraw.Draw(bar)
    d.line([(0, 1), (bar.width, 1)], fill=RIM + (255,), width=3)
    # headline: 2 lines max, Montserrat ExtraBold, ~52 px caps (size 72), shrinks to fit
    size = 72
    while True:
        f = font(size)
        lines = wrap2(head, f, bar.width - 110)
        if all(f.getlength(l) <= bar.width - 110 for l in lines) or size <= 50:
            break
        size -= 2
    asc = f.getbbox("H")[3] - f.getbbox("H")[1]
    gap = 20 if len(lines) == 2 else 0
    total = asc * len(lines) + gap * (len(lines) - 1)
    y = (bar.height - total) // 2 - f.getbbox("H")[1]
    text = Image.new("RGBA", bar.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    for l in lines:
        td.text((52, y), l, font=f, fill=WHITE + (255,))
        y += asc + gap
    text = shadow(text, blur=3, strength=0.35, off=(0, 2))
    # red slanted divider over the join
    div = Image.new("RGBA", (40, Y1 - Y0), (0, 0, 0, 0))
    ImageDraw.Draw(div).polygon([(14, 0), (26, 0), (14 + 0 - 0, Y1 - Y0), (2, Y1 - Y0)], fill=RED + (255,))
    # tab: red gradient, white dot + kicker, slanted right edge
    tf = font(30)
    label = (kicker or "BREAKING NEWS").upper()
    tw = int(tf.getlength(label)) + 84
    tab = vgrad(tw, TAB[3] - TAB[1], TAB_T, TAB_B)
    m = Image.new("L", tab.size, 0)
    ImageDraw.Draw(m).polygon([(0, 0), (tw - 1, 0), (tw - 18, tab.height), (0, tab.height)], fill=255)
    tab.putalpha(m)
    tdw = ImageDraw.Draw(tab)
    tdw.ellipse((18, tab.height // 2 - 7, 32, tab.height // 2 + 7), fill=WHITE + (255,))
    tdw.text((44, tab.height // 2), label, font=tf, fill=WHITE + (255,), anchor="lm")
    return box, bar, text, div, tab


def lower_third(head, kicker, t, hold):
    """In ~12 frames (box, bar wipe, text, tab), hold, out ~8 frames (fade). hold = seconds fully on."""
    box, bar, text, div, tab = lt_parts(head, kicker)
    fr = t * FPS
    total_in = 12
    out_at = (hold + total_in / FPS) * FPS
    k_out = 1.0 - (fr - out_at) / 8 if fr > out_at else 1.0
    if k_out <= 0:
        return None
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if fr >= 0:
        im.alpha_composite(box, (X0, Y0))
    wipe = ease((fr - 2) / 6)
    if wipe > 0:
        wv = max(1, round(bar.width * wipe))
        im.alpha_composite(bar.crop((0, 0, wv, bar.height)), (BOX_R, Y0))
    if fr >= 8:
        im.alpha_composite(with_alpha(text, ease((fr - 8) / 3)), (BOX_R, Y0))
    if fr >= 1:
        im.alpha_composite(div, (BOX_R - 20, Y0))
    if fr >= 10:
        k = ease((fr - 10) / 3)
        im.alpha_composite(with_alpha(tab, k), (TAB[0] - round((1 - k) * 30), TAB[1]))
    im = shadow(im, blur=12, strength=0.35)
    return with_alpha(im, k_out)


# ------------------------------------------------------------------ location / date tag (first seconds only)
@lru_cache(None)
def tag_img(place, date):
    f = font(36)
    h = 73
    pin = Image.new("RGBA", (86, h), CHIP_RED + (255,))
    d = ImageDraw.Draw(pin)
    cx, cy = 40, 30
    d.ellipse((cx - 15, cy - 17, cx + 15, cy + 13), fill=WHITE + (255,))
    d.polygon([(cx - 13, cy + 2), (cx + 13, cy + 2), (cx, cy + 27)], fill=WHITE + (255,))
    d.ellipse((cx - 6, cy - 8, cx + 6, cy + 4), fill=CHIP_RED + (255,))
    pw = int(f.getlength(place)) + 56
    pl = Image.new("RGBA", (pw, h), CHIP_NAVY + (255,))
    ImageDraw.Draw(pl).text((26, h // 2), place, font=f, fill=WHITE + (255,), anchor="lm")
    dw = int(f.getlength(date)) + 100
    dt = Image.new("RGBA", (dw, h), CHIP_RED + (255,))
    dd = ImageDraw.Draw(dt)
    dd.rounded_rectangle((22, 20, 56, 54), radius=4, outline=WHITE + (255,), width=4)
    dd.rectangle((22, 20, 56, 30), fill=WHITE + (255,))
    for gx in (30, 39, 48):
        for gy in (37, 46):
            dd.rectangle((gx, gy, gx + 4, gy + 4), fill=WHITE + (255,))
    dd.text((72, h // 2), date, font=f, fill=WHITE + (255,), anchor="lm")
    full = Image.new("RGBA", (pin.width + pl.width + dt.width + 40, h), (0, 0, 0, 0))
    x = 0
    for part in (pin, pl, dt):
        m = Image.new("L", part.size, 0)
        ImageDraw.Draw(m).polygon([(14, 0), (part.width, 0), (part.width - 14, h), (0, h)], fill=255)
        part.putalpha(m)
        full.alpha_composite(part, (x, 0))
        x += part.width - 4
    return shadow(full, blur=8, strength=0.45)


def loc_tag(place, date, t, dur=8.5):
    k = min(ease(t / 0.3), 1.0 - max(0.0, (t - dur) / 0.3))
    if k <= 0:
        return None
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tg = tag_img(place, date)
    im.alpha_composite(with_alpha(tg, k), (196 - round((1 - k) * 24), 30))
    return im


# ------------------------------------------------------------------ subscribe pill (fixed schedule)
@lru_cache(None)
def pill_img():
    f = font(38)
    pw = int(f.getlength("SUBSCRIBE")) + 70
    im = Image.new("RGBA", (pw + 96, 80), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 4, 72, 76), fill=WHITE + (255,))
    # bell
    bx, by = 36, 40
    d.pieslice((bx - 17, by - 22, bx + 17, by + 12), 180, 360, fill=NAVY_T + (255,))
    d.rectangle((bx - 17, by - 5, bx + 17, by + 10), fill=NAVY_T + (255,))
    d.polygon([(bx - 22, by + 10), (bx + 22, by + 10), (bx + 17, by + 3), (bx - 17, by + 3)], fill=NAVY_T + (255,))
    d.ellipse((bx - 6, by + 10, bx + 6, by + 20), fill=NAVY_T + (255,))
    d.rounded_rectangle((88, 2, 88 + pw, 78), radius=38, fill=PILL + (255,))
    d.text((88 + pw // 2, 40), "SUBSCRIBE", font=f, fill=WHITE + (255,), anchor="mm")
    return shadow(_pad(im, 16), blur=8, strength=0.45)


def subscribe(t, dur=5.5):
    if t < 0 or t > dur:
        return None
    grow = ease(t / (4 / FPS)) if t < 4 / FPS else 1.0
    k = 1.0 - max(0.0, (t - (dur - 6 / FPS)) / (6 / FPS))
    p = pill_img()
    if grow < 1:
        p = p.resize((max(1, round(p.width * (0.6 + 0.4 * grow))), max(1, round(p.height * (0.6 + 0.4 * grow)))), Image.LANCZOS)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    full = pill_img()
    x = 1859 - full.width + 16 + (full.width - p.width) // 2
    y = 700 - 16 + (full.height - p.height) // 2
    im.alpha_composite(with_alpha(p, k), (x, y))
    return im


# ------------------------------------------------------------------ small chips: footage credit / AI label
@lru_cache(None)
def chip(text, ai=False):
    f = font(22, "Bold")
    w = int(f.getlength(text)) + 28
    im = Image.new("RGBA", (w, 38), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, 37), radius=6, fill=((176, 32, 30, 215) if ai else (0, 0, 0, 120)))
    d.text((14, 19), text, font=f, fill=(255, 255, 255, 235 if ai else 205), anchor="lm")
    return im


def corner_chip(text, ai=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    c = chip(text.upper(), ai)
    im.alpha_composite(c, (W - 40 - c.width, 40))
    return im


if __name__ == "__main__" and sys.argv[1:] == ["demo"]:
    bg = Image.open(os.path.join(HERE, "thumbs", "3h3i7C4KX0g", "005.jpg")).convert("RGBA").resize((W, H))
    for layer in (bug(), loc_tag("Henderson, NV", "OCT 30, 2026", 2.0), lower_third("ONE DEAD AFTER RESCUE FROM A FLOODED WASH IN HENDERSON", "BREAKING NEWS", 1.0, 11),
                  subscribe(2.0), corner_chip("Video: News 3 Las Vegas")):
        if layer is not None:
            bg.alpha_composite(layer)
    bg.convert("RGB").save(os.path.join(HERE, "gfx_demo.jpg"), quality=92)
    # animation strip of the lower third
    strip = Image.new("RGB", (6 * 640, 120), "gray")
    for i, fr in enumerate((1, 3, 6, 9, 12, 20)):
        im = Image.new("RGBA", (W, H), (60, 70, 80, 255))
        im.alpha_composite(lower_third("LAKE MEAD UP 1 FT 8 IN IN NINE DAYS", "LAKE MEAD", fr / FPS, 11))
        strip.paste(im.crop((0, 780, W, 1020)).convert("RGB").resize((640, 80)), (i * 640, 20))
    strip.save(os.path.join(HERE, "gfx_anim.jpg"))
    print("ok")
