"""Dark Horizon looks (W8rbNGHAENI, measured 2026-11-04) rebuilt for the Storm Desk style.
Text: VCR typewriter date, camcorder date/time stamp, red glowing stat, red glowing chapter title + fade to black,
place tag with a blinking red dot, radio-style waveform with red typed subtitles.
Maps: tilted green relief with red lahar paths drawing on + zone fill + label; satellite pan to a pin with a typed label
and a yellow dashed line from the summit; dark satellite with a red dotted ring and real quakes popping in time order.
Extra: film grain + flicker + vignette on archive footage."""
import json, math, os, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
RED = (238, 30, 30)
GLOW = 0.38                      # strength of the coloured text glow (1.0 = the reference's heavy glow)
F_VT = os.path.join(HERE, "fonts", "VT323-Regular.ttf")
F_AR = os.path.join(HERE, "fonts", "Arimo.ttf")
F_MI = os.path.join(HERE, "fonts", "Michroma-Regular.ttf")
_fc = {}


def font(path, size, bold=False):
    k = (path, size, bold)
    if k not in _fc:
        f = ImageFont.truetype(path, size)
        if bold:
            f.set_variation_by_name("Bold")
        _fc[k] = f
    return _fc[k]


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ramp(t, a, b):
    return min(1.0, max(0.0, (t - a) / max(1e-6, b - a)))


def fade(t, t0, t1, fi=0.25, fo=0.3):
    return min(ramp(t, t0, t0 + fi), 1 - ramp(t, t1 - fo, t1))


def alpha(im, k):
    if k >= 0.999:
        return im
    a = np.asarray(im).copy()
    a[..., 3] = (a[..., 3].astype(np.float32) * max(0.0, k)).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


_tc = {}


def text_layer(text, fnt, fill, glow=None, glow_r=10, glow_k=1.0, shadow=0.0, pad=40):
    """Tight RGBA image of text with an optional coloured glow and a dark soft shadow."""
    k = (text, id(fnt), fill, glow, glow_r, glow_k, shadow)
    if k in _tc:
        return _tc[k]
    x0, y0, x1, y1 = fnt.getbbox(text)
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).text((pad - x0, pad - y0), text, font=fnt, fill=255)
    if shadow:
        sh = m.filter(ImageFilter.GaussianBlur(max(3, glow_r // 2)))
        base.alpha_composite(Image.merge("RGBA", [Image.new("L", (w, h), 0)] * 3 + [sh.point(lambda v: int(v * shadow))]), (0, 3))
    if glow and sum(glow) > 120:
        # owner, 2026-11-04: the coloured glow was too strong - keep a soft halo only
        glow_r, glow_k = max(3, int(glow_r * 0.55)), glow_k * GLOW
    if glow:
        g = m.filter(ImageFilter.GaussianBlur(glow_r))
        gl = Image.merge("RGBA", [Image.new("L", (w, h), c) for c in glow] + [g.point(lambda v: min(255, int(v * 1.6 * glow_k)))])
        base.alpha_composite(gl)
    base.alpha_composite(Image.merge("RGBA", [Image.new("L", (w, h), c) for c in fill] + [m]))
    _tc[k] = (base, pad)
    return _tc[k]


def put(frame, layer, x, y, a=1.0, anchor="c"):
    im, pad = layer
    if anchor == "c":
        x, y = x - im.width // 2, y - im.height // 2
    elif anchor == "l":
        x, y = x - pad, y - pad
    frame.alpha_composite(alpha(im, a), (int(x), int(y)))


# ------------------------------------------------------------------ text looks
def typewriter_date(fr, t, t0, t1, text):
    """Red VCR date, centred, typed in one character at a time (0:01 of the reference)."""
    n = len(text)
    k = int(min(n, max(0, (t - t0) / 0.055)))
    if k <= 0 or t > t1:
        return
    a = 1 - ramp(t, t1 - 0.35, t1)
    full = text_layer(text, font(F_VT, 78), RED, glow=(255, 40, 40), glow_r=6, glow_k=0.45, shadow=0.75)
    part = text_layer(text[:k], font(F_VT, 78), RED, glow=(255, 40, 40), glow_r=6, glow_k=0.45, shadow=0.75)
    x = W // 2 - full[0].width // 2
    put(fr, part, x + full[1], 470, a, anchor="l")


def cam_stamp(fr, t, t0, t1, date, clock, seed=7):
    """Camcorder date/time, red VCR font, top-left under the logo (4:01 of the reference); flickers, then fades."""
    if not (t0 <= t < t1):
        return
    rnd = random.Random(int(t * 30) * 31 + seed)
    a = (0.55 if rnd.random() < 0.06 else 1.0) * (1 - ramp(t, t1 - 0.4, t1))
    dl = text_layer(date, font(F_VT, 58), RED, shadow=0.9, glow=(255, 40, 40), glow_r=4, glow_k=0.35)
    cl = text_layer(clock, font(F_VT, 100), RED, shadow=0.9, glow=(255, 40, 40), glow_r=5, glow_k=0.35)
    put(fr, dl, W - 48 - (dl[0].width - 2 * dl[1]), 30, a, "l")
    put(fr, cl, W - 48 - (cl[0].width - 2 * cl[1]), 78, a, "l")


def place_tag(fr, t, t0, t1, text):
    """White techno place name with a blinking red REC dot, top-left under the logo (8:04 of the reference)."""
    if not (t0 <= t < t1):
        return
    a = fade(t, t0, t1, 0.2, 0.3)
    lay = text_layer(text, font(F_MI, 30), (250, 250, 250), shadow=0.8, glow_r=6)
    put(fr, lay, 84, 140, a, "l")
    if int((t - t0) * 2) % 2 == 0:
        d = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        ImageDraw.Draw(d).ellipse((8, 8, 32, 32), fill=(235, 25, 25, 255))
        fr.alpha_composite(alpha(d, a), (40, 140 + 8))


def _back(x):
    """Ease-out with a small overshoot: things arrive and settle instead of just appearing."""
    x = max(0.0, min(1.0, x)); c = 1.25
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def red_stat(fr, t, t0, t1, text, y=470, size=104):
    """Big red bold number with a soft glow. Lands on its word with a small settle, keeps drifting so it is never
    frozen, and leaves by lifting and fading (owner 2026-11-05: no static open or close)."""
    if not (t0 <= t < t1):
        return
    lay = text_layer(text, font(F_AR, size, True), RED, glow=(255, 30, 30), glow_r=14, glow_k=0.9, shadow=0.55)
    k_in = _back((t - t0) / 0.32); k_out = ease(ramp(t, t1 - 0.28, t1))
    zoom = (0.86 + 0.14 * k_in) * (1 + 0.012 * (t - t0))
    im, pad = lay
    lay = (im.resize((max(1, int(im.width * zoom)), max(1, int(im.height * zoom))), Image.BILINEAR), pad)
    put(fr, lay, W // 2, y - int(26 * k_out), min(1.0, ramp(t, t0, t0 + 0.14)) * (1 - k_out))


def chapter_title(fr, t, t0, t_black, t1, title, sub):
    """Glowing red title over dimming footage, footage goes to black, title fades (1:37 of the reference)."""
    if not (t0 <= t < t1):
        return fr
    arr = np.asarray(fr.convert("RGB")).astype(np.float32)
    dim = 1 - 0.35 * ramp(t, t0, t0 + 0.8)
    dim *= 1 - ramp(t, t_black, t_black + 0.4)
    out = Image.fromarray((arr * dim).astype(np.uint8)).convert("RGBA")
    a = ramp(t, t0, t0 + 0.8) * (1 - ramp(t, t1 - 0.4, t1))
    put(out, text_layer(title, font(F_AR, 118, True), RED, glow=(255, 25, 25), glow_r=18, glow_k=1.0), W // 2, 500, a)
    put(out, text_layer(sub, font(F_VT, 54), RED, glow=(255, 25, 25), glow_r=8, glow_k=0.7), W // 2, 590, a)
    return out


# ------------------------------------------------------------------ radio waveform
class Wave:
    """Envelope of the narration for the radio-style waveform (0:19 of the reference)."""

    def __init__(self, wav_path, offset):
        import wave
        w = wave.open(wav_path)
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
        if w.getnchannels() == 2:
            x = x.reshape(-1, 2).mean(1)
        self.sr, self.x, self.offset = sr, x / 32768.0, offset
        hop = sr // 200                                   # 5 ms
        n = len(self.x) // hop
        self.env = np.sqrt((self.x[:n * hop].reshape(n, hop) ** 2).mean(1))
        self.env /= max(1e-6, np.percentile(self.env, 99.5))

    def at(self, tv):
        i = int((tv - self.offset) * 200)
        return float(self.env[i]) if 0 <= i < len(self.env) else 0.0


def radio(fr, t, t0, t1, wave, lines):
    """Darkened footage + red waveform in the centre + red typed subtitle lines at the bottom."""
    if not (t0 <= t < t1):
        return fr
    k = fade(t, t0, t1, 0.25, 0.25)
    arr = np.asarray(fr.convert("RGB")).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    out = arr * (1 - 0.66 * k)
    out = Image.fromarray(out.clip(0, 255).astype(np.uint8)).convert("RGBA")
    vig = _vignette(0.75)
    out = Image.fromarray((np.asarray(out.convert("RGB")).astype(np.float32) * (1 - k + k * vig[..., None])).astype(np.uint8)).convert("RGBA")
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    x0, x1, yc = 700, 1240, 520
    d.line((x0, yc, x1, yc), fill=RED + (255,), width=3)
    n = 150
    for i in range(n):
        e = wave.at(t - i * 0.012) * (1.0 - 0.55 * i / n)
        hgt = 6 + e * (210 if i < 3 else 120)
        x = x0 + i * (x1 - x0) / n
        d.line((x, yc - hgt / 2, x, yc + hgt / 2), fill=RED + (255,), width=3 if i < 3 else 2)
    g = lay.filter(ImageFilter.GaussianBlur(9))
    out.alpha_composite(alpha(g, k * 0.5))
    out.alpha_composite(alpha(lay, k))
    for (a, b, text) in lines:
        if a <= t < b:
            n = int(min(len(text), max(1, (t - a) / 0.03)))
            full = text_layer(text, font(F_VT, 52), RED, glow=(255, 30, 30), glow_r=5, glow_k=0.5, shadow=0.6)
            part = text_layer(text[:n], font(F_VT, 52), RED, glow=(255, 30, 30), glow_r=5, glow_k=0.5, shadow=0.6)
            put(out, part, W // 2 - full[0].width // 2 + full[1], 905, k, "l")
    return out


# ------------------------------------------------------------------ archive film look
_vig = {}


def _vignette(strength):
    if strength not in _vig:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / math.sqrt(2)
        _vig[strength] = (1 - strength * np.clip(r - 0.25, 0, 1) ** 1.6 / 0.75 ** 1.6).astype(np.float32)
    return _vig[strength]


_grain = None


def film(fr, t):
    """Grain, a light brightness flicker and a vignette for archive shots (reference: every archive shot)."""
    global _grain
    if _grain is None:
        rs = np.random.RandomState(3)
        _grain = [rs.normal(0, 11, (H // 2, W // 2)).astype(np.float32) for _ in range(6)]
    arr = np.asarray(fr.convert("RGB")).astype(np.float32)
    g = _grain[int(t * 24) % 6]
    g = np.repeat(np.repeat(g, 2, 0), 2, 1)
    fl = 1 + 0.035 * math.sin(t * 37.0) * math.sin(t * 13.0)
    out = (arr * fl + g[..., None]) * _vignette(0.55)[..., None]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8)).convert("RGBA")


# ------------------------------------------------------------------ maps
META = json.load(open(os.path.join(HERE, "meta.json"))) if os.path.exists(os.path.join(HERE, "meta.json")) else {}


def merc(lat, lon, z):
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def grade_sat(im):
    a = np.asarray(im).astype(np.float32) / 255
    lum = a.mean(-1, keepdims=True)
    a = lum + (a - lum) * 0.8
    a = (a - 0.45) * 1.18 + 0.45
    a = a * np.array([0.86, 0.92, 0.84]) * 0.82
    return Image.fromarray((a.clip(0, 1) * 255).astype(np.uint8))


class SatCam:
    """A pyramid of a graded satellite mosaic, rendered at any centre/scale with a bilinear affine warp."""

    def __init__(self, png, key, wide=None):
        m = META[key]
        self.z, self.ox, self.oy = m["z"], m["ox"], m["oy"]
        base = grade_sat(Image.open(os.path.join(HERE, png)).convert("RGB"))
        self.levels = [(1.0, base)]
        for f in (0.5, 0.25):
            self.levels.append((f, base.resize((int(base.width * f), int(base.height * f)), Image.LANCZOS)))
        # a coarser, wider mosaic (one zoom level down) for views that run past the edges of this one
        self.wide = None
        if wide:
            mw = META[wide[1]]
            wb = grade_sat(Image.open(os.path.join(HERE, wide[0])).convert("RGB"))
            f = 2 ** (mw["z"] - self.z)
            self.wide = (f, wb, mw["ox"] - self.ox * f, mw["oy"] - self.oy * f)

    def px(self, lat, lon):
        x, y = merc(lat, lon, self.z)
        return x - self.ox, y - self.oy

    def render(self, cx, cy, s):
        f, im = next(((f, im) for f, im in self.levels if s / f >= 0.72), self.levels[-1])
        k = s / f
        hw, hh = W / 2 / s, H / 2 / s
        bw, bh = self.levels[0][1].size
        if self.wide and (cx - hw < 0 or cy - hh < 0 or cx + hw > bw or cy + hh > bh):
            f, im, dx, dy = self.wide            # same coords, scaled by f and shifted into the wide mosaic
            k = s / f
            data = (1 / k, 0, cx * f - dx - W / 2 / k, 0, 1 / k, cy * f - dy - H / 2 / k)
        else:
            data = (1 / k, 0, cx * f - W / 2 / k, 0, 1 / k, cy * f - H / 2 / k)
        out = im.transform((W, H), Image.AFFINE, data, resample=Image.BILINEAR)
        arr = np.asarray(out).astype(np.float32) * _vignette(0.6)[..., None]
        return Image.fromarray(arr.astype(np.uint8)).convert("RGBA")

    @staticmethod
    def to_screen(x, y, cx, cy, s):
        return (x - cx) * s + W / 2, (y - cy) * s + H / 2


def pin(fr, x, y, a=1.0):
    p = Image.new("RGBA", (40, 50), (0, 0, 0, 0))
    d = ImageDraw.Draw(p)
    d.polygon([(6, 10), (34, 10), (20, 44)], fill=(232, 22, 22, 255))
    d.ellipse((5, 0, 35, 26), fill=(232, 22, 22, 255))
    d.ellipse((15, 8, 25, 18), fill=(120, 0, 0, 255))
    fr.alpha_composite(alpha(p, a), (int(x - 20), int(y - 46)))


def label_white(text, size=34):
    return text_layer(text, font(F_AR, size, True), (255, 255, 255), glow=(10, 10, 10), glow_r=9, glow_k=0.9)


def dashed(d, p0, p1, k, color, width=7, dash=22, gap=14):
    L = math.dist(p0, p1)
    if L < 1:
        return
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    s = 0.0
    while s < L * k:
        e = min(s + dash, L * k)
        d.line((p0[0] + ux * s, p0[1] + uy * s, p0[0] + ux * e, p0[1] + uy * e), fill=color, width=width)
        s += dash + gap


def map_orting(t, cam, t0, t1, beats):
    """Satellite: start on the summit, pan to Orting, pin + typed label, yellow dashed line from the crater (0:29/4:31)."""
    sx, sy = cam.px(46.8529, -121.7604)
    ox, oy = cam.px(47.0979, -122.2043)
    end_c = ((sx + ox) / 2, (sy + oy) / 2 - 10)
    k = ease(ramp(t, beats["pan0"], beats["pan1"]))
    cx = sx + (end_c[0] - sx) * k
    cy = sy + (end_c[1] - sy) * k
    s = 0.95 + (0.355 - 0.95) * k + 0.012 * ramp(t, beats["pan1"], t1)
    fr = cam.render(cx, cy, s)
    d_s = SatCam.to_screen(sx, sy, cx, cy, s)
    d_o = SatCam.to_screen(ox, oy, cx, cy, s)
    # crater label (red glow, like the reference's "Mt. St. Helens" at the crater)
    a_c = ramp(t, t0 + 0.15, t0 + 0.5)
    put(fr, text_layer("Mount Rainier", font(F_AR, 36, True), (255, 210, 210), glow=(255, 20, 20), glow_r=10, glow_k=1.0),
        d_s[0], d_s[1] + 40, a_c)
    # dashed line from the crater to the pin
    kl = ease(ramp(t, beats["line0"], beats["line1"]))
    if kl > 0:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(lay)
        dashed(dd, d_s, d_o, kl, (0, 0, 0, 150), width=11)
        dashed(dd, d_s, d_o, kl, (250, 222, 40, 255), width=7)
        fr.alpha_composite(lay)
    # pin + typed label
    if t >= beats["pin"]:
        drop = 1 - ease(ramp(t, beats["pin"], beats["pin"] + 0.25))
        pin(fr, d_o[0], d_o[1] - 40 * drop, 1 - drop * 0.6)
        txt = "Orting, WA"
        n = int(min(len(txt), (t - beats["pin"]) / 0.06))
        if n > 0:
            full = label_white(txt)
            put(fr, label_white(txt[:n]), d_o[0] - full[0].width // 2 + full[1], d_o[1] - 104, 1, "l")
    if t >= beats["min"]:
        mx, my = (d_s[0] + d_o[0]) / 2, (d_s[1] + d_o[1]) / 2
        lay = text_layer("40 MIN", font(F_AR, 64, True), RED, glow=(255, 25, 25), glow_r=12, glow_k=0.9, shadow=0.7)
        put(fr, lay, mx + 150, my - 10, ramp(t, beats["min"], beats["min"] + 0.25))
    return fr


class QuakeMap:
    def __init__(self, cam, quakes_json, t_first, t_mid, t_end, date_mid_ms, date_end_ms):
        self.cam = cam
        q = json.load(open(quakes_json))["features"]
        q = sorted(q, key=lambda f: f["properties"]["time"])
        self.q = [(f["properties"]["time"], *cam.px(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]),
                   f["properties"]["mag"] or 0.5) for f in q if f["properties"]["time"] <= date_end_ms]
        self.t0q = self.q[0][0]
        self.tf, self.tm, self.te = t_first, t_mid, t_end
        self.dm, self.de = date_mid_ms, date_end_ms

    def vt(self, ms):
        """video time a quake pops: the first two days fill t_first..t_mid, the rest t_mid..t_end"""
        if ms <= self.dm:
            return self.tf + (self.tm - self.tf) * (ms - self.t0q) / (self.dm - self.t0q)
        return self.tm + (self.te - self.tm) * (ms - self.dm) / (self.de - self.dm)

    def ms_at(self, t):
        if t <= self.tm:
            return self.t0q + (self.dm - self.t0q) * ramp(t, self.tf, self.tm)
        return self.dm + (self.de - self.dm) * ramp(t, self.tm, self.te)

    def frame(self, t, t0, t1, beats):
        cam = self.cam
        sx, sy = cam.px(46.8529, -121.7604)
        s = 0.92 + 0.08 * ramp(t, t0, t1)
        fr = cam.render(sx, sy + 20, s)
        arr = np.asarray(fr.convert("RGB")).astype(np.float32) * 0.62
        fr = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        # red dotted ring, ~4 km round the summit, drawing on
        kr = ease(ramp(t, beats["ring0"], beats["ring1"]))
        cxs, cys = SatCam.to_screen(sx, sy, sx, sy + 20, s)
        R = 2200 / (156543.03 * math.cos(math.radians(46.85)) / 2 ** cam.z) * s
        for i in range(int(90 * kr)):
            a0 = -90 + i * 4
            d.arc((cxs - R, cys - R, cxs + R, cys + R), a0, a0 + 2.2, fill=(235, 30, 30, 230), width=5)
        for (ms, x, y, mag) in self.q:
            tv = self.vt(ms)
            if tv > t:
                continue
            X, Y = SatCam.to_screen(x, y, sx, sy + 20, s)
            age = t - tv
            r = 1.6 + max(0.0, mag) * 1.7 + 7 * max(0.0, 1 - age / 0.25)
            d.ellipse((X - r, Y - r, X + r, Y + r), fill=(255, 40, 30, 235))
        g = lay.filter(ImageFilter.GaussianBlur(6))
        fr.alpha_composite(alpha(g, 0.55))
        fr.alpha_composite(lay)
        # ticking camcorder date
        import datetime
        day = datetime.datetime.utcfromtimestamp(self.ms_at(t) / 1000 - 7 * 3600)
        put(fr, text_layer(day.strftime("%m-%d-%Y"), font(F_VT, 54), RED, shadow=0.7, glow=(255, 40, 40), glow_r=4, glow_k=0.35),
            44, 128, 1.0, "l")
        n = sum(1 for q in self.q if self.vt(q[0]) <= t)
        if t >= beats["sum"]:
            put(fr, text_layer("1,350+ QUAKES", font(F_AR, 88, True), RED, glow=(255, 25, 25), glow_r=14, glow_k=0.9, shadow=0.7),
                W // 2, 900, ramp(t, beats["sum"], beats["sum"] + 0.25))
        return fr, n


class LaharMap:
    """Tilted green relief, red lahar paths drawing down the valleys from the summit, then a zone fill (15:10)."""

    def __init__(self):
        m = META["dem11"]
        relief = Image.open(os.path.join(HERE, "relief.png")).convert("RGB")
        dem = np.load(os.path.join(HERE, "dem_z11.npy"))
        # smoother sea edge than the coarse source data
        water = Image.fromarray(((dem <= 0.5) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5)).point(lambda v: 255 if v > 128 else 0)
        sea = Image.new("RGB", relief.size, (64, 112, 160))
        relief = Image.composite(sea, relief, water)
        self.crop = (60, 0, 2040, 1960)                      # dem_z11 px
        S = 2
        x0, y0, x1, y1 = self.crop
        self.board = relief.crop(self.crop).resize(((x1 - x0) * S, (y1 - y0) * S), Image.BICUBIC).filter(ImageFilter.UnsharpMask(2, 60, 2))
        self.S, self.ox, self.oy, self.z = S, m["ox"], m["oy"], m["z"]
        paths = json.load(open(os.path.join(HERE, "paths.json")))
        self.paths = [[((x - x0) * S, (y - y0) * S) for x, y in p] for p in paths]
        self.cum = []
        for p in self.paths:
            seg = [math.dist(p[i], p[i + 1]) for i in range(len(p) - 1)]
            self.cum.append(np.concatenate([[0], np.cumsum(seg)]))
        self.Lmax = max(c[-1] for c in self.cum)
        zone = Image.new("L", self.board.size, 0)
        dz = ImageDraw.Draw(zone)
        for p in self.paths:
            dz.line(p, fill=255, width=70, joint="curve")
        self.zone = zone.filter(ImageFilter.GaussianBlur(6))

    def bxy(self, lat, lon):
        x, y = merc(lat, lon, self.z)
        return ((x - self.ox) - self.crop[0]) * self.S, ((y - self.oy) - self.crop[1]) * self.S

    def H(self, t, t0, t1, center=(46.935, -121.99)):
        """screen corners -> board quad (a tilted view looking north-west, slowly pushing in)."""
        k = ramp(t, t0, t1)
        cx, cy = self.bxy(*center)
        cx += -50 * k
        cy += -30 * k
        z = 1.0 - 0.06 * k
        wt, wb, dt, db = 1750 * z, 1080 * z, 1020 * z, 760 * z
        src = [(0, 0), (W, 0), (W, H), (0, H)]
        dst = [(cx - wt, cy - dt), (cx + wt, cy - dt), (cx + wb, cy + db), (cx - wb, cy + db)]
        A = []
        for (x, y), (u, v) in zip(src, dst):
            A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
            A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
        A = np.array(A, np.float64)
        _, _, vt = np.linalg.svd(A)
        Hm = vt[-1].reshape(3, 3)
        return Hm / Hm[2, 2]

    def near(self, lat, lon):
        """(path index, point index) of the traced path that passes closest to a place"""
        bx, by = self.bxy(lat, lon)
        best = (1e18, 0, 0)
        for i, p in enumerate(self.paths):
            a = np.asarray(p)
            d = np.hypot(a[:, 0] - bx, a[:, 1] - by)
            j = int(np.argmin(d))
            best = min(best, (float(d[j]), i, j))
        return best[1], best[2]

    def frame(self, t, t0, t1, beats, only=None, big=("80,000 PEOPLE", 47.0979, -122.2043), timer=None, stamp=None,
              center=(46.935, -121.99)):
        """only: {path index: last point index} to draw just those flows (None = every valley, with the zone fill);
        big: red label (text, lat, lon) placed beside that place; timer: (t_start, t_end, minutes) VCR countdown
        beside Orting; stamp: VCR line top-right (e.g. '5,600 YEARS AGO')."""
        Hm = self.H(t, t0, t1, center)
        board = self.board.convert("RGBA")
        lay = Image.new("RGBA", board.size, (0, 0, 0, 0))
        kz = ramp(t, beats["fill0"], beats["fill1"]) if "fill0" in beats else 0
        if kz > 0:
            fill = Image.merge("RGBA", [Image.new("L", board.size, c) for c in (228, 92, 64)] + [self.zone.point(lambda v: int(v * 0.42 * kz))])
            lay.alpha_composite(fill)
        kp = ramp(t, beats["draw0"], beats["draw1"])
        dl = ImageDraw.Draw(lay)
        for i, (p, c) in enumerate(zip(self.paths, self.cum)):
            if only is not None and i not in only:
                continue
            last = only[i] if only is not None else len(p) - 1
            Lend = c[last] if only is not None else self.Lmax
            n = min(last, int(np.searchsorted(c, Lend * ease(kp))))
            if n >= 1:
                dl.line(p[:n + 1], fill=(225, 18, 18, 255), width=11 if only is not None else 9, joint="curve")
        glow = lay.filter(ImageFilter.GaussianBlur(4))
        board.alpha_composite(alpha(glow, 0.4))
        board.alpha_composite(lay)
        coeffs = tuple(Hm.flatten()[:8])
        fr = board.transform((W, H), Image.PERSPECTIVE, coeffs, resample=Image.BILINEAR)
        bg = Image.new("RGBA", (W, H), (20, 30, 24, 255))
        bg.alpha_composite(fr)
        arr = np.asarray(bg.convert("RGB")).astype(np.float32) * _vignette(0.5)[..., None]
        fr = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
        Hi = np.linalg.inv(Hm)

        def scr(lat, lon):
            bx, by = self.bxy(lat, lon)
            v = Hi @ np.array([bx, by, 1.0])
            return v[0] / v[2], v[1] / v[2]
        for name, (la, lo) in {"Orting": (47.0979, -122.2043), "Puyallup": (47.1854, -122.2929),
                               "Enumclaw": (47.2043, -121.9915)}.items():
            X, Y = scr(la, lo)
            if not (70 < Y < H - 70 and 60 < X < W - 220):
                continue
            d = ImageDraw.Draw(fr)
            d.ellipse((X - 7, Y - 7, X + 7, Y + 7), fill=(255, 255, 255, 255), outline=(30, 30, 30, 255), width=2)
            put(fr, label_white(name, 30), X + 12, Y - 26, ramp(t, t0 + 0.2, t0 + 0.6), "l")
        X, Y = scr(46.8529, -121.7604)
        put(fr, text_layer("Mount Rainier", font(F_AR, 30, True), (255, 215, 215), glow=(255, 20, 20), glow_r=10), X, Y + 40,
            ramp(t, t0 + 0.2, t0 + 0.6))
        if big and t >= beats["label"]:
            X, Y = scr(big[1], big[2])
            lay_b = text_layer(big[0], font(F_AR, 84, True), RED, glow=(255, 30, 30), glow_r=14, glow_k=0.9, shadow=0.75)
            lw = lay_b[0].width - 2 * lay_b[1]
            X, Y = min(max(X + 170, lw / 2 + 40), W - lw / 2 - 40), min(max(Y + 110, 150), H - 150)
            put(fr, lay_b, X, Y, ramp(t, beats["label"], beats["label"] + 0.25))
        if timer and t >= timer[0]:
            k = ease(ramp(t, timer[0], timer[1]))
            secs = int(round(k * timer[2] * 60))
            X, Y = scr(47.0979, -122.2043)
            put(fr, text_layer(f"{secs // 60:02d}:{secs % 60:02d}", font(F_VT, 120), RED, glow=(255, 40, 40), glow_r=6, glow_k=0.5,
                               shadow=0.9), min(X + 260, W - 220), max(Y + 20, 120), 1.0)
        if stamp and t >= t0 + 0.3:
            sl = text_layer(stamp, font(F_VT, 64), RED, glow=(255, 40, 40), glow_r=4, glow_k=0.35, shadow=0.9)
            put(fr, sl, W - 48 - (sl[0].width - 2 * sl[1]), 40, ramp(t, t0 + 0.3, t0 + 0.5), "l")
        return fr


def map_summit(t, cam, t0, t1, beats, label="Columbia Crest", stat="-21 FT OF ICE"):
    """Satellite push onto the summit, pin drop + typed label, red stat under it (the pin look on a single place)."""
    sx, sy = cam.px(46.8529, -121.7604)
    k = ease(ramp(t, t0, t1))
    s = 0.62 + 0.30 * k
    fr = cam.render(sx, sy - 60, s)
    X, Y = SatCam.to_screen(sx, sy, sx, sy - 60, s)
    if t >= beats["pin"]:
        drop = 1 - ease(ramp(t, beats["pin"], beats["pin"] + 0.25))
        pin(fr, X, Y - 40 * drop, 1 - drop * 0.6)
        n = int(min(len(label), (t - beats["pin"]) / 0.06))
        if n > 0:
            full = label_white(label, 38)
            put(fr, label_white(label[:n], 38), X - full[0].width // 2 + full[1], Y - 110, 1, "l")
    if t >= beats["stat"]:
        put(fr, text_layer(stat, font(F_AR, 84, True), RED, glow=(255, 25, 25), glow_r=12, glow_k=0.9, shadow=0.8),
            X, Y + 150, ramp(t, beats["stat"], beats["stat"] + 0.25))
    return fr


def map_pin(t, cam, t0, t1, beats, lat, lon, label, stat=None, s0=0.62, s1=0.92, lift=60):
    """Satellite push onto any place: pin drop + typed white label, red stat under it (the summit look, anywhere)."""
    sx, sy = cam.px(lat, lon)
    k = ease(ramp(t, t0, t1))
    s = s0 + (s1 - s0) * k
    fr = cam.render(sx, sy - lift, s)
    X, Y = SatCam.to_screen(sx, sy, sx, sy - lift, s)
    if t >= beats["pin"]:
        drop = 1 - ease(ramp(t, beats["pin"], beats["pin"] + 0.25))
        pin(fr, X, Y - 40 * drop, 1 - drop * 0.6)
        n = int(min(len(label), (t - beats["pin"]) / 0.06))
        if n > 0:
            full = label_white(label, 38)
            put(fr, label_white(label[:n], 38), X - full[0].width // 2 + full[1], Y - 110, 1, "l")
    if stat and t >= beats["stat"]:
        put(fr, text_layer(stat, font(F_AR, 84, True), RED, glow=(255, 25, 25), glow_r=12, glow_k=0.9, shadow=0.8),
            X, Y + 150, ramp(t, beats["stat"], beats["stat"] + 0.25))
    return fr


def map_marinas(t, cam, t0, t1, pins, view=(36.25, -114.55, 0.47, 0.51)):
    """Dark satellite of all of Lake Mead; each marina pin drops on its word with a typed white name and a tag:
    red 'CLOSED <year>' for the ones the water left behind, white 'OPEN' for the ones still running.
    pins: [(t_appear, lat, lon, name, tag, closed, side)]  side n/s/e/w = where the name + tag sit (no overlaps)"""
    lat, lon, s0, s1 = view
    cx, cy = cam.px(lat, lon)
    s = s0 + (s1 - s0) * ease(ramp(t, t0, t1))
    fr = cam.render(cx, cy, s)
    arr = np.asarray(fr.convert("RGB")).astype(np.float32) * 0.74
    fr = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
    for (ta, la, lo, name, tag, closed, side) in pins:
        if t < ta:
            continue
        x, y = SatCam.to_screen(*cam.px(la, lo), cx, cy, s)
        drop = 1 - ease(ramp(t, ta, ta + 0.25))
        if closed:
            pin(fr, x, y - 36 * drop, 1 - drop * 0.6)
        else:
            d = ImageDraw.Draw(fr)
            r = 11
            d.ellipse((x - r, y - r - 30 * drop, x + r, y + r - 30 * drop), fill=(255, 255, 255, 255), outline=(20, 20, 20, 255), width=3)
        full = label_white(name, 30)
        nw, nh = full[0].width - 2 * full[1], full[0].height - 2 * full[1]
        tg = text_layer(tag, font(F_AR, 26, True), RED if closed else (255, 255, 255), shadow=0.9, glow=(10, 10, 10), glow_r=6, glow_k=0.6) if tag else None
        tw = (tg[0].width - 2 * tg[1]) if tg else 0
        if side == "w":
            nx, ny = x - 30 - nw, y - 48
        elif side == "sw":
            nx, ny = x - 30 - nw, y + 4
        elif side == "e":
            nx, ny = x + 30, y - 48
        elif side == "s":
            nx, ny = x - nw / 2, y + 22
        else:
            nx, ny = x - nw / 2, y - 92
        ty = ny + nh + 8
        tx = nx + (nw - tw) / 2 if side in ("n", "s") else (nx + nw - tw if side in ("w", "sw") else nx)
        n = int(min(len(name), (t - ta) / 0.05))
        if n > 0:
            put(fr, label_white(name[:n], 30), nx, ny, 1, "l")
        if tg and t >= ta + 0.45:
            put(fr, tg, tx, ty, ramp(t, ta + 0.45, ta + 0.7), "l")
    return fr


def mini_graph(fr, t, t0, t1, title, rows, x=1180, y=120, w=640, h=320, base=0.0):
    """A small graph over the clip (owner 2026-11-05: short, the clip keeps playing). The panel slides in and settles,
    bars grow one after another, the numbers count up, and it slides back out. About 4 s on screen."""
    if not (t0 <= t < t1):
        return
    from PIL import ImageDraw as _D
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = _D.Draw(lay)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 18, fill=(6, 12, 24, 215), outline=(255, 255, 255, 40), width=2)
    d.text((26, 18), title, font=font(F_AR, 34, True), fill=(255, 255, 255, 255))
    hi = max(r[2] for r in rows); span = max(1e-6, hi - base)
    n = len(rows); rh = (h - 90) / n
    for i, (lab, val, v, hot) in enumerate(rows):
        k = _back((t - t0 - 0.3 - i * 0.28) / 0.55) if t > t0 + 0.3 + i * 0.28 else 0.0
        yy = 78 + i * rh
        d.text((26, yy + 6), lab, font=font(F_AR, 26), fill=(205, 214, 228, 255))
        bx = 210; full = w - bx - 190
        bw = max(0, int(full * (v - base) / span * k))
        if bw > 4:
            d.rounded_rectangle((bx, yy + 4, bx + bw, yy + rh - 12), 6, fill=(255, 48, 48, 255) if hot else (120, 140, 170, 255))
        if k > 0.02:
            num = "".join(c for c in val if c.isdigit() or c == ".")
            shown = val
            if num and k < 1:
                cur = v * min(1.0, k) if base == 0 else base + (v - base) * min(1.0, k)
                shown = (f"{cur:,.2f}" if "." in num else f"{int(cur):,}") + val[val.rfind(" "):]
            d.text((bx + bw + 12, yy + 6), shown, font=font(F_AR, 28, True), fill=(255, 255, 255, 255))
    k_in = _back((t - t0) / 0.42); k_out = ease(ramp(t, t1 - 0.32, t1))
    off = int((1 - k_in) * 90 + k_out * 90)
    a = min(1.0, ramp(t, t0, t0 + 0.18)) * (1 - k_out)
    fr.alpha_composite(alpha(lay, a), (max(0, min(fr.width - w, x + off)), y))
