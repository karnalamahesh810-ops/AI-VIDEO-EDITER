"""
The owner's two thumbnail looks in 4K (the kit's tools/thumbs4k.py): 3840x2160, under YouTube's 2 MB.
  own  a red italic EXCLUSIVE tab + a white bar with huge black Anton words (his reference layout)
  new  a navy frame, the logo box, a red BREAKING NEWS tab, a white box with navy heavy caps ending in "!"
The picture is one realistic scene for the story (Avatarity's Nano Banana Pro on his plan first, OpenRouter behind it), upscaled.
Headlines say only what the narration says: ALERT, RISING, WARNING, never an event that did not happen. Never fails a video.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdkit", "fonts")
ANTON = os.path.join(FONTS, "Anton.ttf")
ARIMO = os.path.join(FONTS, "Arimo.ttf")
MONT = os.path.join(FONTS, "Montserrat.ttf")
S = 3
W, H = 1280 * S, 720 * S
RED = (226, 30, 36)
NAVY = (11, 41, 79)
MAX_BYTES = 2_000_000


def mont(size: int, weight: str = "Black") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(MONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # noqa: BLE001
        pass
    return f


def _bold_italic(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(ARIMO, size)
    try:
        f.set_variation_by_name("Bold")
    except Exception:  # noqa: BLE001
        pass
    return f


def scene(im: Image.Image) -> Image.Image:
    """The picture at 3840x2160: filled, a touch more colour and contrast, sharpened."""
    bg = im.convert("RGB")
    s = max(W / bg.width, H / bg.height)
    bg = bg.resize((round(bg.width * s), round(bg.height * s)), Image.LANCZOS)
    x, y = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((x, y, x + W, y + H))
    bg = ImageEnhance.Contrast(ImageEnhance.Color(bg).enhance(1.15)).enhance(1.07)
    return bg.filter(ImageFilter.UnsharpMask(2 * S, 60, 2))


def save(im: Image.Image, path: str) -> str:
    """YouTube takes thumbnails up to 2 MB: the 4K file stays under that."""
    for q in (95, 92, 90, 88, 85, 82, 80, 76, 72):
        im.save(path, quality=q, subsampling=0 if q >= 90 else 2, optimize=True)
        if os.path.getsize(path) <= MAX_BYTES:
            break
    return path


def own(picture: Image.Image, head: str, path: str) -> str:
    im = scene(picture)
    d = ImageDraw.Draw(im)
    bar = (14 * S, 586 * S, 1264 * S, 708 * S)
    d.rectangle(bar, fill="white", outline=(20, 20, 20), width=3 * S)
    bh = bar[3] - bar[1]
    size = 200 * S
    while True:
        fa = ImageFont.truetype(ANTON, size)
        x0, y0, x1, y1 = fa.getbbox(head)
        if ((y1 - y0) <= bh * 0.80 and (x1 - x0) <= bar[2] - bar[0] - 50 * S) or size < 40:
            break
        size -= 4
    d.text((bar[0] + 24 * S - x0, bar[1] + (bh - (y1 - y0)) // 2 - y0), head, font=fa, fill="black")
    ft = _bold_italic(46 * S)
    tw = int(ft.getlength("EXCLUSIVE")) + 30 * S
    d.rectangle((14 * S, 531 * S, 14 * S + tw, 586 * S), fill=RED)
    # The tab's words lean: the bundled font has no italic of its own.
    lay = Image.new("RGBA", (tw, 55 * S), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((tw // 2, 28 * S), "EXCLUSIVE", font=ft, fill=(255, 255, 255, 255), anchor="mm")
    lean = lay.transform(lay.size, Image.AFFINE, (1, 0.2, -0.1 * lay.height, 0, 1, 0), resample=Image.BICUBIC)
    im.paste(lean, (14 * S, 531 * S), lean)
    return save(im, path)


def new(picture: Image.Image, head: str, path: str, logo: Optional[str] = None) -> str:
    im = scene(picture).convert("RGBA")
    d = ImageDraw.Draw(im)
    fw = 10 * S
    d.rectangle((0, 0, W - 1, H - 1), outline=NAVY + (255,), width=fw)
    if logo and os.path.isfile(logo):
        lg = Image.open(logo).convert("RGBA")
        lh = 92 * S
        lg = lg.resize((round(lg.width * lh / lg.height), lh), Image.LANCZOS)
        box = (fw, fw + 14 * S, fw + lg.width + 34 * S, fw + 14 * S + lh + 26 * S)
        d.rectangle(box, fill=NAVY + (255,))
        im.alpha_composite(lg, (box[0] + 17 * S, box[1] + 13 * S))
    f = mont(84 * S)
    while f.getlength(head) > W - 150 * S and f.size > 50 * S:
        f = mont(f.size - 4)
    tw = int(f.getlength(head))
    bh = f.size + 36 * S
    bx0, by1 = 24 * S, H - 28 * S
    bx1, by0 = bx0 + tw + 52 * S, by1 - bh
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((bx0 + 6 * S, by0 + 8 * S, bx1 + 6 * S, by1 + 8 * S), fill=(0, 0, 0, 120))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8 * S)))
    d = ImageDraw.Draw(im)
    d.rectangle((bx0, by0, bx1, by1), fill=(255, 255, 255, 255), outline=NAVY + (255,), width=6 * S)
    d.text((bx0 + 26 * S, (by0 + by1) // 2 + 2 * S), head, font=f, fill=NAVY + (255,), anchor="lm")
    tf = mont(30 * S, "ExtraBold")
    label = "BREAKING NEWS"
    tw2 = int(tf.getlength(label)) + 44 * S
    th = 48 * S
    tab = Image.new("RGBA", (tw2 + 20 * S, th), (0, 0, 0, 0))
    ImageDraw.Draw(tab).polygon([(0, 0), (tw2 + 20 * S, 0), (tw2, th), (0, th)], fill=RED + (255,))
    ImageDraw.Draw(tab).text((20 * S, th // 2), label, font=tf, fill=(255, 255, 255, 255), anchor="lm")
    im.alpha_composite(tab, (bx0, by0 - th + 2 * S))
    return save(im.convert("RGB"), path)


_ASK = ("You plan a YouTube thumbnail for a news video. From the title and the narration only, answer JSON: {\"own\": 2-3 huge "
        "words in CAPITALS, \"new\": 2-5 words in CAPITALS ending in \"!\", \"picture\": one sentence describing a realistic news photo "
        "of the main subject and place, the whole landmark in frame, dramatic; for a flood or water story, massive flood waves taller than the landmark}. Headlines must be truthful: ALERT, RISING, WARNING "
        "and numbers the narration says; never claim something happened that did not. No text in the picture.")


def rule_plan(title: str, places: List[str]) -> Dict[str, str]:
    place = (str(places[0]).split(",")[0] if places else "").upper()
    words = [w for w in re.findall(r"[A-Z0-9'-]+", str(title or "").upper()) if len(w) > 2][:3]
    head = (place + " ALERT") if place else " ".join(words) or "BREAKING NEWS"
    return {"own": head[:24], "new": head[:32].rstrip("!") + "!",
            "picture": f"A realistic news photograph of {place.title() or title}, dramatic weather, the whole landmark in frame."}


def plan(title: str, said: str, places: List[str], ask: Optional[Callable] = None) -> Dict[str, str]:
    out = rule_plan(title, places)
    if ask:
        try:
            raw = ask(_ASK, {"title": str(title)[:200], "places": places[:4], "narration": str(said)[:1500]})
            got = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            spoken = str(title) + " " + str(said)
            for k, lim in (("own", 24), ("new", 34), ("picture", 400)):
                v = str(got.get(k) or "").strip()
                if v and len(v) <= lim and (k == "picture" or all(d in spoken for d in re.findall(r"\d[\d,.]*", v))):
                    out[k] = v
            if not out["new"].endswith("!"):
                out["new"] += "!"
        except Exception as e:  # noqa: BLE001 - the rules' words stand
            print(f"[thumbs] headline by rule: {type(e).__name__}: {str(e)[:120]}", flush=True)
    return out


def picture(prompt: str, draw: Optional[Callable[[str], Any]] = None) -> Optional[Image.Image]:
    """The scene: `draw(prompt)` -> PIL image or bytes; by default Avatarity, then OpenRouter."""
    if draw is not None:
        got = draw(prompt)
        return Image.open(io.BytesIO(got)) if isinstance(got, (bytes, bytearray)) else got
    from . import avatarity, config
    if avatarity.configured():
        try:
            out = avatarity.client().image(prompt, model=config.AVATARITY_IMAGE_MODEL, size="1792x1024")
            if out and out.data:
                return Image.open(io.BytesIO(out.data))
        except Exception as e:  # noqa: BLE001 - OpenRouter behind it
            print(f"[thumbs] Avatarity: {type(e).__name__}: {str(e)[:160]}", flush=True)
    key = os.environ.get("IMAGE_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or getattr(config, "DIRECTOR_API_KEY", "")
    if not key or os.environ.get("STORM_THUMB_OPENROUTER") == "0":     # (a 4K picture there costs about $0.14)
        return None
    import requests
    r = requests.post(config.OPENROUTER_API_BASE + "/chat/completions", timeout=400, headers={"Authorization": "Bearer " + key},
                      json={"model": os.environ.get("STORM_THUMB_MODEL") or "google/gemini-3-pro-image-preview",
                            "modalities": ["image", "text"], "image_config": {"aspect_ratio": "16:9", "image_size": "4K"},
                            "messages": [{"role": "user", "content": prompt}]})
    j = r.json()
    url = j["choices"][0]["message"]["images"][0]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def make(doc: dict, inp: dict, work: str, ask: Optional[Callable] = None, upload: Optional[Callable[[str, str], str]] = None,
         draw: Optional[Callable[[str], Any]] = None, logo: str = "") -> dict:
    """Both 4K thumbnails for this video: {"own": url or path, "new": ..., "headlines": {...}} or {"error": ...}."""
    try:
        brief = (doc.get("meta") or {}).get("story") or {}
        said = " ".join(str(s.get("text") or "") for s in (doc.get("scenes") or [])[:50])
        p = plan(str(inp.get("title") or ""), said, list(brief.get("places") or []), ask)
        im = picture(p["picture"], draw)
        if im is None:
            return {"error": "no picture", "headlines": p}
        out_own = own(im, p["own"], os.path.join(work, "thumb_own_4k.jpg"))
        out_new = new(im, p["new"], os.path.join(work, "thumb_new_4k.jpg"), logo)
        res: Dict[str, Any] = {"headlines": {"own": p["own"], "new": p["new"]}, "own": out_own, "new": out_new}
        if upload is not None:
            res["own"] = upload(out_own, "thumb_own_4k.jpg") or out_own
            res["new"] = upload(out_new, "thumb_new_4k.jpg") or out_new
        return res
    except Exception as e:  # noqa: BLE001 - the video ships without them and says so
        print(f"[thumbs] {type(e).__name__}: {str(e)[:200]}", flush=True)
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
