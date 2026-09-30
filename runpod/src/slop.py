"""
AI slop and not-footage: what a real-footage edit must never show.

The owner (2026-09-30, the Texas test render): "this is AI slop clip" at 0:18 -
a vertical AI-generated scene from another channel (men at a table with
peaches in a decaying courthouse) - and at 0:37 an AI oil-painting street
beside a YouTuber talking to camera with a SUBSCRIBE bell and karaoke captions
"A HUNDRED-YEAR FLOOD". The same test showed TV weather presenters in front of
radar walls, an anchor desk, a storm chaser's live stream with a face cam and a
QR code, and TV forecast maps. A real-footage style shows none of these.

Layers, cheapest first; each rejects on its own:

1. metadata  - a title, channel, description or tag that names an AI generator
               or AI story ("AI generated", "#ai", Sora, Veo, Midjourney, Runway,
               Kling...): metadata_reason().
2. pixels    - a still with a slow pan or zoom and nothing moving inside it, or a
               slideshow of such stills: the residual after the best global
               zoom + shift between frames is flat (still_measure). And another
               creator's burned-in captions: big text bands low in the frame that
               change from frame to frame, unlike a news chyron's fixed banner
               (caption_bands).
3. local CLIP - frames closer to "an AI generated image", "a digital painting",
               "an oil painting", "concept art" than to "a photograph", "news
               footage", "security camera footage" (checked on the whole frame
               and on each half, so a painting beside a talking head is found);
               and the kind of shot: a TV weather presenter, an anchor desk, a
               TV weather map or live-stream screen, against real footage
               (clip_verdict).
4. the judge - src/vision.py asks the vision model "ai_generated" and "studio"
               (a presenter, anchor, streamer or YouTuber, a subscribe button,
               creator captions) and rejects either outright.

check_file() runs 1-3 on a downloaded candidate (videos and photos); the
thresholds were set on the Texas test render's frames (scratchpad ws_slop).
Nothing here raises: an unreadable file or a missing model is "no finding".
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, List, Optional

from . import config

# --------------------------------------------------------------------------- #
# 1. Metadata
# --------------------------------------------------------------------------- #

_AI_TERMS = re.compile(
    r"(?:\bai[- ]?(?:generated|generation|video|videos|story|stories|art|artwork|film|movie|animation|"
    r"animated|short|shorts|image|images|photo|photos|picture|pictures|slop|cinematic|music video|"
    r"created|made|creation|tool|render|rendered|visuali[sz]ation|simulation|recreation|footage)\b|"
    r"\bmade with ai\b|\bcreated (?:with|using|by) ai\b|\bgenerated (?:with|using|by) ai\b|"
    r"#ai\b|#aiart\b|#aivideo\b|#aigenerated\b|#sora\d?\b|#veo\d?\b|#midjourney\b|#kling\w*|"
    r"\b(?:openai )?sora(?: ?2| ai)\b|\bopenai sora\b|\b(?:google )?veo ?[23]\b|\bgoogle veo\b|\bmidjourney\b|"
    r"\brunway ?(?:ml|gen[- ]?\d|ai)\b|\bkling ?(?:ai|\d(?:\.\d)?)\b|"
    r"\bhailuo\b|\bminimax\b|\bpika ?labs?\b|\bpika ?(?:1|2)\.\d\b|\bluma ?(?:ai|dream machine)\b|"
    r"\bdream machine\b|\bstable ?diffusion\b|\bleonardo ?ai\b|\bdall[- ·]?e\b|\bflux ?(?:1|\.1|pro|dev|ai)\b|"
    r"\bgrok imagine\b|\bseedance\b|\bpixverse\b|\bhunyuan ?video\b|\bwan ?2\.\d\b|"
    r"\bideogram\b|\bnightcafe\b|\bopenart\b|\bcivitai\b|\blexica\b|\bplayground ?ai\b|"
    r"\btext[- ]to[- ]video\b|\bimage[- ]to[- ]video\b|\bdeepfake\b|\bfaceswap\b|\bcgi\b|\b3d animation\b|"
    r"\bgta ?(?:v|5|6)?\b|\bgame ?play\b|\bunreal engine\b|\bbeamng\b|\bteardown\b|\bsimulat(?:ion|or)\b)",
    re.I)
# Hosts of AI picture galleries and prompt sites (image search results).
_AI_HOSTS = ("lexica.art", "openart.ai", "civitai.com", "midjourney.com", "nightcafe.studio", "playgroundai.com",
             "pixai.art", "tensor.art", "seaart.ai", "leonardo.ai", "ideogram.ai", "krea.ai", "starryai.com",
             "dreamstudio.ai", "craiyon.com", "artbreeder.com", "deepai.org", "pixlr.com/image-generator",
             "freepik.com/premium-ai", "freepik.com/free-ai", "stock.adobe.com/generative")


def metadata_reason(*texts) -> str:
    """Why a candidate's words give it away as AI-made or a game ("" = nothing found)."""
    blob = " ".join(str(t or "") for t in texts if t)
    if not blob:
        return ""
    if ai_host(blob):
        return "an AI picture site"
    m = _AI_TERMS.search(re.sub(r"https?://\S+", " ", blob))       # words, not URL paths ("cgi-bin")
    return f"AI-made or a game ({m.group(0).strip()[:30]})" if m else ""


def ai_host(*urls) -> bool:
    """A link to an AI picture gallery or prompt site."""
    low = " ".join(str(u or "") for u in urls).lower()
    return any(h in low for h in _AI_HOSTS)


# --------------------------------------------------------------------------- #
# 2. Pixels: a still with a pan or zoom, a slideshow, frozen
# --------------------------------------------------------------------------- #

STILL_W, STILL_H = 128, 72
_SCALES = tuple(round(0.94 + 0.01 * i, 3) for i in range(13))       # 0.94 .. 1.06
_SHIFTS = range(-3, 4)
# Frames about 1 s apart, blurred, compared after the best global zoom +
# shift: what is left is what moves INSIDE the picture. Measured
# (scratchpad ws_slop): real phone and news clips of the reference channel
# 2.2-60 (median ~6, 2 of 60 under 2.5); a photo with a smooth zoom or pan 0.4-1.5
# (one textured photo 3.7); a held photo 0-0.2.
STILL_RESIDUAL = 1.9
FROZEN_RAW = 0.5
# A pair this different even after alignment is a cut (a slideshow's next photo, a fast pan).
CUT_RAW, CUT_RESIDUAL = 22.0, 12.0


def _blur(a):
    """3x3 box blur: compares the picture, not interpolation noise."""
    import numpy as np
    p = np.pad(a, 1, mode="edge")
    return sum(p[dy:dy + a.shape[0], dx:dx + a.shape[1]] for dy in range(3) for dx in range(3)) / 9.0


def _zoom(img, s: float):
    """`img` scaled by `s` about its centre (bilinear), same size."""
    import numpy as np
    if s == 1.0:
        return img
    h, w = img.shape
    ys = (np.arange(h) - (h - 1) / 2.0) / s + (h - 1) / 2.0
    xs = (np.arange(w) - (w - 1) / 2.0) / s + (w - 1) / 2.0
    ys = np.clip(ys, 0, h - 1)
    xs = np.clip(xs, 0, w - 1)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    top = img[y0][:, x0] * (1 - fx) + img[y0][:, x1] * fx
    bot = img[y1][:, x0] * (1 - fx) + img[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def _aligned_residual(a, b) -> float:
    """The smallest mean |a - T(b)| over zooms of +/-6% and shifts of +/-3 px (the frame's middle only)."""
    import numpy as np
    h, w = a.shape
    m = 6
    core = a[m:h - m, m:w - m]
    best = float("inf")
    for s in _SCALES:
        z = _zoom(b, s)
        for dy in _SHIFTS:
            for dx in _SHIFTS:
                cand = z[m + dy:h - m + dy, m + dx:w - m + dx]
                if cand.shape != core.shape:
                    continue
                d = float(np.abs(core - cand).mean())
                if d < best:
                    best = d
    return best


def still_measure(grays: list) -> Optional[dict]:
    """
    {"raw", "residual", "cuts", "pairs", "still"} over frames about a second
    apart (grey, any size - resized to 128x72 and blurred): the median change
    between frames, the median change left after the best global zoom +
    shift, and how many pairs are cuts. `still` = nothing moves inside the
    picture in most pairs: a photo held, zoomed or panned, or a slideshow of
    them. Fast real motion (most pairs past the cut limits) is not a still.
    None for fewer than 3 frames.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    if not grays or len(grays) < 3:
        return None
    small = []
    for g in grays:
        a = np.asarray(g, dtype=np.float32)
        if a.shape != (STILL_H, STILL_W):
            a = np.asarray(Image.fromarray(a.clip(0, 255).astype(np.uint8)).resize((STILL_W, STILL_H),
                                                                                  Image.BILINEAR),
                           dtype=np.float32)
        small.append(_blur(a))
    raws, residuals, cuts = [], [], 0
    for a, b in zip(small, small[1:]):
        raw = float(np.abs(a - b).mean())
        if raw < FROZEN_RAW:
            raws.append(raw)
            residuals.append(raw)
            continue
        res = _aligned_residual(a, b)
        if raw >= CUT_RAW and res >= CUT_RESIDUAL:
            cuts += 1
            continue
        raws.append(raw)
        residuals.append(res)
    pairs = len(small) - 1
    if not residuals or len(residuals) < 0.5 * pairs:
        # Mostly big changes: fast real motion (or cuts too quick to tell) - not a still.
        return {"raw": round(sorted(raws)[len(raws) // 2], 2) if raws else 0.0, "residual": 0.0, "cuts": cuts,
                "pairs": len(residuals), "still": False}
    residuals.sort()
    raws.sort()
    med_res = residuals[len(residuals) // 2]
    med_raw = raws[len(raws) // 2]
    return {"raw": round(med_raw, 2), "residual": round(med_res, 2), "cuts": cuts, "pairs": len(residuals),
            "still": med_res < STILL_RESIDUAL}


def _gray_frames(path: str, n: int = 8, w: int = STILL_W, h: int = STILL_H) -> list:
    try:
        from .filters import _gray_frames as frames
        return frames(path, n, w, h)
    except Exception:  # noqa: BLE001
        return []


def still_verdict(path: str) -> str:
    """"a still with a slow pan or zoom" / "a slideshow of stills" / "a frozen picture", or ""."""
    if not path or not os.path.isfile(path) or os.path.splitext(path)[1].lower() in (
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"):
        return ""
    seconds = 0.0
    try:
        from .filters import _video_seconds
        seconds = _video_seconds(path)
    except Exception:  # noqa: BLE001
        pass
    n = max(3, min(8, int(seconds) + 1)) if seconds else 5            # about one frame a second
    m = still_measure(_gray_frames(path, n))
    if not m or not m["still"]:
        return ""
    if m["cuts"]:
        return "a slideshow of stills"
    return "a frozen picture" if m["raw"] < FROZEN_RAW else "a still with a slow pan or zoom"


# --------------------------------------------------------------------------- #
# 2b. Pixels: another creator's burned-in captions
# --------------------------------------------------------------------------- #

def _text_rows(g) -> list:
    import numpy as np
    edges = np.abs(np.diff(g.astype(np.int16), axis=1)) > 48
    per_row = edges.sum(axis=1)
    return [i for i, c in enumerate(per_row) if c > g.shape[1] * 0.08]


def _bands(rows: list, gap: int = 2) -> List[tuple]:
    out: List[tuple] = []
    for r in rows:
        if out and r - out[-1][1] <= gap:
            out[-1] = (out[-1][0], r)
        else:
            out.append((r, r))
    return out


def _caption_band(g) -> Optional[dict]:
    """
    The frame's largest caption-like text band, or None: a band of text rows
    between 35% and 90% of the height, at least 3.5% of it tall, centred
    (a creator's captions sit in the middle; a chyron hugs the left, a ticker
    runs the full width) and 25-85% of the width wide.
    """
    import numpy as np
    h, w = g.shape
    rows = [r for r in _text_rows(g) if 0.35 * h <= r <= 0.90 * h]
    best = None
    for a, b in _bands(rows):
        tall = (b - a + 1) / h
        if tall < 0.035:
            continue
        edges = np.abs(np.diff(g[a:b + 1].astype(np.int16), axis=1)) > 48
        cols = np.where(edges.sum(axis=0) >= 2)[0]
        if not len(cols):
            continue
        x0, x1 = int(cols.min()), int(cols.max())
        extent, mid = (x1 - x0) / w, (x0 + x1) / 2.0 / w
        if not (0.25 <= extent <= 0.85 and abs(mid - 0.5) <= 0.15):
            continue
        if best is None or tall > best["tall"]:
            best = {"a": a, "b": b, "tall": tall, "centre": (a + b) / 2.0 / h, "x0": x0 / w, "x1": x1 / w}
    return best


def caption_bands(grays: list) -> dict:
    """
    {"frames", "big", "changing", "n"}: how many frames carry a caption-like
    band (_caption_band), how many of those are big title captions (6%+ of the
    height, above the lower quarter where news banners sit), and how many
    consecutive pairs show the band's words changing - its width moves as
    karaoke words come and go while the rest of the picture holds, unlike a
    chyron's fixed box.
    """
    import numpy as np
    out = {"frames": 0, "big": 0, "changing": 0, "n": len(grays or [])}
    found = []
    for g in grays or []:
        band = _caption_band(np.asarray(g, dtype=np.float32))
        found.append(band)
        if band:
            out["frames"] += 1
            out["big"] += 1 if band["tall"] >= 0.06 and band["centre"] < 0.75 else 0
    for g0, g1, f0, f1 in zip(grays or [], (grays or [])[1:], found, found[1:]):
        if not (f0 and f1):
            continue
        a, b = min(f0["a"], f1["a"]), max(f0["b"], f1["b"])
        x0 = np.asarray(g0, dtype=np.float32)
        x1 = np.asarray(g1, dtype=np.float32)
        band = float(np.abs(x0[a:b + 1] - x1[a:b + 1]).mean())
        rest = float(np.abs(x0 - x1).mean())
        moved = abs(f0["x0"] - f1["x0"]) + abs(f0["x1"] - f1["x1"])
        if band > max(6.0, 1.5 * rest) and moved > 0.08:
            out["changing"] += 1
    return out


def captions_verdict(path: str) -> str:
    """"another creator's burned-in captions" when a clip carries them, else ""."""
    if not path or not os.path.isfile(path):
        return ""
    grays = _gray_frames(path, 6, 320, 180)
    if len(grays) < 3:
        return ""
    c = caption_bands(grays)
    need = max(2, len(grays) // 2)
    if c["frames"] >= need and (c["changing"] >= 1 or c["big"] >= need):
        return "another creator's burned-in captions"
    return ""


# --------------------------------------------------------------------------- #
# 3. Local CLIP: painted / generated pictures, and what kind of shot it is
# --------------------------------------------------------------------------- #

ART = ["an AI generated image", "a digital painting", "an oil painting", "an illustration", "concept art",
       "a hyperrealistic 3d render", "digital art", "a painting with visible brush strokes"]
PHOTO = ["a photograph", "a real photo taken with a phone", "a frame from a real video", "news footage",
         "security camera footage", "drone footage", "an amateur video"]
LAYOUT: Dict[str, List[str]] = {
    "studio": ["a TV weather presenter standing in front of a weather map", "a news anchor in a television studio",
               "a meteorologist pointing at a radar map"],
    "creator": ["a person talking to the camera in a room", "a youtuber with a subscribe button",
                "a split screen with a person talking on one side", "a webcam face in the corner of the screen"],
    "tvmap": ["a TV weather map graphic", "a weather radar map on television",
              "a live stream screen with a radar map"],
    "footage": ["real footage filmed outdoors", "a phone video of a street", "aerial drone footage of a town",
                "a video frame of real news footage", "a press conference", "a photograph of a place"],
}
# Median over the sampled frames; set on the Texas test render (ws_slop):
# painted/generated 0.5-0.9 on the frame or one half, real 0.01-0.2.
ART_SHARE = 0.55
# Studio, TV-map and stream frames score footage 0.00-0.05, real 0.12+.
FOOTAGE_FLOOR = 0.10
NOT_FOOTAGE_SHARE = 0.75


def _softmax_share(emb, pos: List[str], neg: List[str]):
    import numpy as np
    from . import localvision
    t = localvision.embed_texts(list(pos) + list(neg))
    logits = 100.0 * emb @ t.T
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    return p[:, :len(pos)].sum(axis=1)


def _layout_shares(emb) -> Dict[str, "object"]:
    import numpy as np
    from . import localvision
    names, texts, labels = list(LAYOUT), [], []
    for k in names:
        for p in LAYOUT[k]:
            texts.append(p)
            labels.append(k)
    logits = 100.0 * emb @ localvision.embed_texts(texts).T
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    return {k: p[:, [j for j, lab in enumerate(labels) if lab == k]].sum(axis=1) for k in names}


def _rgb_frames(path: str, n: int = 3) -> list:
    """`n` PIL frames across a clip (one for a photo), or []."""
    try:
        from PIL import Image
    except ImportError:
        return []
    if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"):
        try:
            with Image.open(path) as im:
                return [im.convert("RGB")]
        except Exception:  # noqa: BLE001
            return []
    try:
        from . import vision
        import base64
        import io
        out = []
        for f in vision.sample_frames(path, n) or []:
            try:
                out.append(Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB"))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def clip_verdict(images: list, allow_people: bool = False, allow_maps: bool = False) -> Optional[dict]:
    """
    {"art", "studio", "creator", "tvmap", "footage", "reject"} from the local
    CLIP model over PIL frames (medians over the frames; "art" is each
    frame's highest of the whole frame and its two halves), or None without
    the model. `allow_people`: a line about a named person (their press
    conference or interview is the shot). `allow_maps`: the line wants a map.
    """
    if not images:
        return None
    try:
        from . import localvision
        if not localvision.available():
            return None
        import numpy as np
        crops = []
        for im in images:
            w, h = im.size
            crops += [im, im.crop((0, 0, w // 2, h)), im.crop((w // 2, 0, w, h))]
        with localvision._RUN:
            emb = localvision.embed_images(crops)
            art = _softmax_share(emb, ART, PHOTO).reshape(len(images), 3).max(axis=1)
            lay = _layout_shares(emb.reshape(len(images), 3, -1)[:, 0, :])
    except Exception as e:  # noqa: BLE001 - a model error never rejects a clip
        print(f"[slop] CLIP check failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    med = {k: float(np.median(v)) for k, v in lay.items()}
    out = {"art": round(float(np.median(art)), 3), **{k: round(v, 3) for k, v in med.items()}, "reject": ""}
    if out["art"] >= ART_SHARE:
        out["reject"] = "an AI-generated or painted picture"
    elif med["footage"] < FOOTAGE_FLOOR:
        studio = med["studio"] + med["creator"]
        if not allow_people and studio >= 0.5:
            out["reject"] = "a TV studio, presenter or talking head"
        elif not allow_maps and med["tvmap"] >= 0.5 and med["tvmap"] + studio >= NOT_FOOTAGE_SHARE:
            out["reject"] = "a TV weather map or live-stream screen"
    return out


# --------------------------------------------------------------------------- #
# All of it, for one downloaded candidate
# --------------------------------------------------------------------------- #

def enabled() -> bool:
    return bool(getattr(config, "AI_SLOP_FILTER", True))


def check_file(path: str, kind: str = "video", allow_people: bool = False, allow_maps: bool = False,
               footage: bool = True) -> str:
    """
    Why a downloaded clip or photo must not be used ("" = keep): generated or
    painted, a still passed off as footage (for a footage beat), another
    creator's captions, a studio / presenter / stream / TV-map shot.
    """
    if not enabled() or not path or not os.path.isfile(path):
        return ""
    if kind == "video":
        why = still_verdict(path) if footage else ""
        if why:
            return why
        why = captions_verdict(path)
        if why:
            return why
    v = clip_verdict(_rgb_frames(path, 3), allow_people=allow_people, allow_maps=allow_maps)
    return (v or {}).get("reject") or ""
