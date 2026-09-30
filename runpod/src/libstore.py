"""
The footage library's own storage box (Cloudflare R2) and its quality gate.

The owner (2026-09-30): "a separate storage box for a library of images and
videos that we can keep building and using; remove any bad video clips from
the library; quality first." The library lives in the R2 bucket
R2_LIBRARY_BUCKET ("thumbgenius-library"), read through its public domain:

    clips/<id>-<token>.mp4        approved video clips
    images/<id>-<token>.jpg       approved photos (never a generated image)
    thumbs/<id>-<token>.jpg       320 px thumbnails for the Library page
    embeddings/<id>-<token>.json  CLIP ViT-B/16 embedding + fingerprints

The token is an HMAC of the asset id under the R2 secret: the same asset
always lands on the same key (a re-run overwrites, never duplicates) and a
link cannot be guessed from a YouTube id. The app's footage_library table
stays the catalogue: storage_bucket "r2:<bucket>", storage_path = key.

check() is the gate every clip or photo passes before it is kept, and that
old rows are checked against when they are moved here (library.maintain).
A clip is bad when it is short, small, vertical or framed on a blurred copy
of itself, mostly black, frozen, letterboxed, a slideshow of stills, covered
by burned-in graphics, soft, off its own subject (local CLIP), or a
perceptual-hash duplicate of a clip the library already keeps. Everything is
measured on the file, with ffmpeg, numpy and the local CLIP model - no
network, no paid model.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from . import config, r2

MODEL = "clip-vit-base-patch16"
STILL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
FRAMES = 8                  # samples per clip (every check reads the same eight)
W, H = 400, 224             # sample size: CLIP's 224 on the short side, ~16:9


# --------------------------------------------------------------------------- #
# Where things live
# --------------------------------------------------------------------------- #

def enabled() -> bool:
    """The library bucket is configured: new clips go there, old rows move there."""
    return r2.library_enabled()


def bucket_ref() -> str:
    return f"r2:{config.R2_LIBRARY_BUCKET}"


def is_r2_ref(bucket: str) -> bool:
    return str(bucket or "").startswith("r2:")


def public_base_for(bucket: str) -> str:
    """The public domain of a bucket this worker knows ("" when it does not)."""
    name = bucket[3:] if is_r2_ref(bucket) else str(bucket or "")
    if name and name == config.R2_LIBRARY_BUCKET:
        return config.R2_LIBRARY_PUBLIC_BASE
    if name and name == config.R2_BUCKET:
        return config.R2_PUBLIC_BASE
    return ""


def url_for(bucket: str, key: str) -> str:
    """The public URL of `key` in an r2:<bucket>, or the key itself when it is a URL."""
    if not key:
        return ""
    if key.startswith("http"):
        return key
    base = public_base_for(bucket)
    return r2.public_url(key, base) if base and is_r2_ref(bucket) else ""


def safe_id(identity: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", identity or "")[:80]


def _token(ident: str) -> str:
    secret = (config.R2_SECRET_ACCESS_KEY or config.R2_ACCOUNT_ID or "thumbgenius").encode("utf-8")
    return hmac.new(secret, ("library:" + ident).encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def key_for(folder: str, ident: str, ext: str) -> str:
    return f"{config.R2_LIBRARY_PREFIX}{folder}/{safe_id(ident)}-{_token(ident)}{ext}"


def put_file(path: str, key: str, content_type: str = "", deadline: float = 0.0) -> str:
    return r2.upload(path, key, content_type=content_type or r2.content_type(path),
                     deadline=deadline or time.time() + 300, bucket=config.R2_LIBRARY_BUCKET,
                     base=config.R2_LIBRARY_PUBLIC_BASE, cache_control=r2.IMMUTABLE)


def put_json(obj: dict, key: str, deadline: float = 0.0) -> str:
    return r2.upload_bytes(json.dumps(obj, separators=(",", ":")).encode("utf-8"), key,
                           content_type="application/json", deadline=deadline or time.time() + 120,
                           bucket=config.R2_LIBRARY_BUCKET, base=config.R2_LIBRARY_PUBLIC_BASE,
                           cache_control="public, max-age=86400")


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Reading the file
# --------------------------------------------------------------------------- #

def tools() -> bool:
    """ffmpeg, ffprobe and numpy are here (without them nothing is judged)."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def is_still(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in STILL_EXTS


def probe(path: str) -> dict:
    """{"width", "height", "seconds", "codec", "ok"} as displayed (rotation applied)."""
    out = {"width": 0, "height": 0, "seconds": 0.0, "codec": "", "ok": False}
    if is_still(path):
        try:
            from PIL import Image
            with Image.open(path) as im:
                out.update(width=im.size[0], height=im.size[1], codec=(im.format or "").lower(), ok=True)
        except Exception:  # noqa: BLE001 - unreadable
            pass
        return out
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,codec_name:stream_side_data=rotation:format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=30)
        data = json.loads(p.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return out
    streams = data.get("streams") or []
    if not streams:
        return out
    st = streams[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    rot = 0
    for sd in st.get("side_data_list") or []:
        try:
            rot = int(float(sd.get("rotation") or 0))
        except (TypeError, ValueError):
            pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    try:
        secs = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        secs = 0.0
    out.update(width=w, height=h, seconds=round(secs, 2), codec=str(st.get("codec_name") or ""),
               ok=bool(w and h and st.get("codec_name")))
    return out


def frames(path: str, n: int = FRAMES, seconds: float = 0.0) -> list:
    """`n` evenly spaced RGB frames (H x W x 3 uint8), [] when unreadable."""
    try:
        import numpy as np
    except ImportError:
        return []
    if is_still(path):
        vf, count = f"scale={W}:{H}", 1
    else:
        secs = seconds or probe(path)["seconds"]
        rate = f"{n}/{secs:.3f}" if secs > 0.5 else "4"
        vf, count = f"fps={rate},scale={W}:{H}", n
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", vf, "-frames:v", str(count),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return []
    size = W * H * 3
    buf = p.stdout or b""
    return [np.frombuffer(buf[i * size:(i + 1) * size], dtype=np.uint8).reshape(H, W, 3)
            for i in range(len(buf) // size)]


def _gray(rgb):
    import numpy as np
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32)


# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #

def dhash(gray) -> Optional[int]:
    """64-bit difference hash of a grey frame; None for a flat frame (its bits are noise)."""
    import numpy as np
    from PIL import Image
    if float(gray.std()) < 6.0:
        return None
    small = np.asarray(Image.fromarray(gray.astype(np.uint8)).resize((9, 8), Image.BILINEAR), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def signature(grays: list) -> List[Optional[int]]:
    """Hashes of the frames at ~20%, 50% and 80% of the clip (one for a photo)."""
    if not grays:
        return []
    if len(grays) < 3:
        return [dhash(grays[len(grays) // 2])]
    n = len(grays)
    return [dhash(grays[i]) for i in sorted({n // 5, n // 2, (4 * n) // 5})]


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def hex_hashes(sig: Iterable[Optional[int]]) -> List[Optional[str]]:
    return [None if h is None else f"{h:016x}" for h in sig]


def parse_hashes(raw) -> List[Optional[int]]:
    out: List[Optional[int]] = []
    for h in raw if isinstance(raw, list) else []:
        try:
            out.append(None if h is None else int(str(h), 16))
        except ValueError:
            out.append(None)
    return out


def duplicate_of(sig: List[Optional[int]], known: Dict[str, List[Optional[int]]],
                 bits: Optional[int] = None) -> str:
    """The id of a known item `sig` looks the same as, or ""."""
    bits = config.LIBRARY_DUP_BITS if bits is None else bits
    mine = [h for h in sig if h is not None]
    if not mine:
        return ""
    need = min(2, len(mine))
    for ident, other in known.items():
        theirs = [h for h in other or [] if h is not None]
        if not theirs:
            continue
        hits = sum(1 for h in mine if min(hamming(h, t) for t in theirs) <= bits)
        if hits >= need:
            return ident
    return ""


# --------------------------------------------------------------------------- #
# Pixel measures (all on the 400x224 samples)
# --------------------------------------------------------------------------- #

def _laplacian_var(g) -> float:
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def sharpness(grays: list) -> float:
    """Median Laplacian variance: low = soft everywhere (a blown-up small upload)."""
    vals = sorted(_laplacian_var(g) for g in grays if float(g.mean()) >= 26)
    return vals[len(vals) // 2] if vals else 0.0


def motion(grays: list) -> List[float]:
    """Mean absolute change between consecutive samples."""
    import numpy as np
    return [float(np.abs(a - b).mean()) for a, b in zip(grays, grays[1:])]


def bars(grays: list) -> tuple:
    """
    (top+bottom, left+right) share of the frame that is black bars in every
    frame - letterbox and pillarbox. Dark frames (a fade) are ignored.
    """
    lit = [g for g in grays if float(g.mean()) >= 20]
    if not lit:
        return 0.0, 0.0

    def run(dark) -> int:
        n = 0
        for d in dark:
            if not d:
                break
            n += 1
        return n

    tb, lr = [], []
    for g in lit:
        rows = (g.mean(axis=1) < 20) & (g.std(axis=1) < 8)
        cols = (g.mean(axis=0) < 20) & (g.std(axis=0) < 8)
        tb.append(run(rows) + run(rows[::-1]))
        lr.append(run(cols) + run(cols[::-1]))
    h, w = lit[0].shape
    return min(tb) / h, min(lr) / w


def framed(grays: list) -> bool:
    """
    A vertical clip framed on a blurred copy of itself (upscale.frame_vertical,
    or a news compilation that did the same): a sharp middle band between two
    featureless blurred sides, with the band's straight edges at the same
    mirrored columns in every frame. It measures 1920x1080, so only the
    pixels tell.
    """
    import numpy as np
    lit = [g for g in grays if float(g.mean()) >= 20]
    if len(lit) < 2:
        return False
    hits, lefts = 0, []
    for g in lit:
        h, w = g.shape
        side = max(8, int(w * 0.12))
        centre = _laplacian_var(g[:, int(w * 0.40):int(w * 0.60)])
        sides = (_laplacian_var(g[:, :side]) + _laplacian_var(g[:, w - side:])) / 2
        colgrad = np.abs(np.diff(g, axis=1)).mean(axis=0)            # w - 1 columns
        lo, hi = int(w * 0.15), int(w * 0.42)
        xl = lo + int(np.argmax(colgrad[lo:hi]))
        xr = (w - 1) - hi + int(np.argmax(colgrad[(w - 1) - hi:(w - 1) - lo]))
        base = float(np.median(colgrad)) + 1e-3
        edge = min(colgrad[xl], colgrad[xr]) / base
        if centre > 20 and sides < 0.2 * centre and abs(xl - ((w - 2) - xr)) <= 3 and edge >= 2.5:
            hits += 1
            lefts.append(xl)
    return hits >= max(2, int(len(lit) * 0.6)) and (max(lefts) - min(lefts) <= 4)


def graphics_share(grays: list) -> float:
    """
    Share of the frame under burned-in graphics - lower thirds, tickers,
    captions, a title card - measured as blocks that are edge-dense yet do not
    change while the rest of the picture moves. A camera that does not move
    cannot separate the two, so a still scene reads 0 (CLIP's text/slide
    class covers text-heavy frames there).
    """
    import numpy as np
    if len(grays) < 3:
        return 0.0
    stack = np.stack(grays).astype(np.float32)
    n, h, w = stack.shape
    bh, bw = 16, 20
    rows, cols = h // bh, w // bw
    change = np.abs(np.diff(stack, axis=0)).mean(axis=0)[:rows * bh, :cols * bw]
    change = change.reshape(rows, bh, cols, bw).mean(axis=(1, 3))
    moving = float(np.median(change))
    if moving < 2.0:
        return 0.0
    gx = np.abs(np.diff(stack, axis=2))[:, :h - 1, :w - 1] > 40
    gy = np.abs(np.diff(stack, axis=1))[:, :h - 1, :w - 1] > 40
    edges = (gx | gy).mean(axis=0)
    edges = np.pad(edges, ((0, 1), (0, 1)))[:rows * bh, :cols * bw].reshape(rows, bh, cols, bw).mean(axis=(1, 3))
    graphic = (edges > 0.10) & (change < max(0.8, 0.2 * moving))
    return float(graphic.mean())


def text_bands(grays: list) -> float:
    """
    Share of the frame height under lines of burned-in text: thin bands of
    rows dense with sharp vertical strokes that do not change between samples
    (a news lower third, a ticker, a caption), each padded to the box around
    it. Works on a still camera, where graphics_share cannot tell a banner
    from the scene; tall textured regions (a building's windows) are not text
    lines and do not count. Measured on the real library: news standups
    0.08-0.23, landscape and drone footage 0.
    """
    import numpy as np
    if len(grays) < 2:
        return 0.0
    stack = np.stack(grays).astype(np.float32)
    med = np.median(stack, axis=0)
    h, w = med.shape
    strokes = (np.abs(np.diff(med, axis=1)) > 40) & (stack.std(axis=0)[:, :-1] < 4.0)
    texty = list(strokes.sum(axis=1) > w * 0.10) + [False]
    runs, start = [], None
    for y, t in enumerate(texty):
        if t and start is None:
            start = y
        elif not t and start is not None:
            if runs and start - runs[-1][1] <= 3:
                runs[-1] = (runs[-1][0], y)
            else:
                runs.append((start, y))
            start = None
    cover = np.zeros(h, dtype=bool)
    for a, b in runs:
        if 3 <= b - a <= int(h * 0.08):
            pad = max(2, (b - a) // 2)
            cover[max(0, a - pad):min(h, b + pad)] = True
    return float(cover.mean())


def warm() -> bool:
    """
    Load the local CLIP model in this thread before a pool starts: a thread
    that calls it while another is still loading it is told it is missing.
    """
    try:
        from . import localvision
        return localvision.available()
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Local CLIP
# --------------------------------------------------------------------------- #

def own_prompts(subject: str = "", event: str = "") -> List[str]:
    s = " ".join(str(subject or "").split())[:120]
    e = " ".join(str(event or "").replace("/", " ").split())[:80]
    out = []
    if s:
        out += [f"a photo of {s}", f"footage of {s}"]
    if e:
        out += [f"footage of {e}", f"a photo of {e} in {s}" if s else f"a photo of {e}"]
    return out


def clip_facts(rgbs: list, subject: str = "", event: str = "") -> Optional[dict]:
    """{"embedding", "relevance", "classes"} from the local CLIP model, None without it."""
    if not rgbs:
        return None
    try:
        from . import localvision
        if not localvision.available():
            return None
        import numpy as np
        from PIL import Image
        images = [Image.fromarray(f) for f in rgbs]
        texts = own_prompts(subject, event)
        with localvision._RUN:                  # the CPU is shared with sourcing
            emb = localvision.embed_images(images)
            classes = localvision.classify(emb)
            rel = (float((emb @ localvision.embed_texts(texts).T).max(axis=1).mean())
                   if texts else None)
        mean = emb.mean(axis=0)
        mean = mean / max(float(np.linalg.norm(mean)), 1e-8)
        return {"embedding": [round(float(x), 5) for x in mean], "relevance": rel,
                "classes": {k: round(float(v), 3) for k, v in classes.items()}}
    except Exception as e:  # noqa: BLE001 - a model error never removes a clip
        print(f"[libstore] CLIP failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #

@dataclass
class Verdict:
    ok: bool = True
    reasons: List[str] = field(default_factory=list)
    checked: bool = False               # False = the tools were missing; nothing was judged
    kind: str = "video"
    width: int = 0
    height: int = 0
    seconds: float = 0.0
    hashes: List[Optional[int]] = field(default_factory=list)
    embedding: Optional[list] = None
    relevance: Optional[float] = None
    measures: Dict[str, object] = field(default_factory=dict)

    def bad(self, reason: str) -> None:
        self.ok = False
        if reason not in self.reasons:
            self.reasons.append(reason)

    def summary(self) -> dict:
        """What the row keeps (analysis.check): the verdict and the numbers behind it."""
        out = {"v": 1, "at": now_iso(), "ok": self.ok, "reasons": list(self.reasons),
               "width": self.width, "height": self.height, "seconds": self.seconds}
        if self.relevance is not None:
            out["clipRelevance"] = round(self.relevance, 4)
        out.update({k: v for k, v in self.measures.items() if k != "classes"})
        return out


def check(path: str, kind: str = "video", subject: str = "", event: str = "",
          known: Optional[Dict[str, List[Optional[int]]]] = None, clip: bool = True) -> Verdict:
    """
    Judge one file for the library. `known` = {asset id: hashes} of what the
    library already keeps, for the duplicate rule. Without ffmpeg/numpy the
    verdict is ok and unchecked (a missing tool never removes a clip).
    """
    v = Verdict(kind=kind)
    if not tools():
        return v
    v.checked = True
    info = probe(path)
    v.width, v.height, v.seconds = info["width"], info["height"], info["seconds"]
    if not info["ok"]:
        v.bad("unreadable file")
        return v
    long_side, short_side = max(v.width, v.height), min(v.width, v.height)
    if kind == "image":
        if long_side < config.LIBRARY_IMAGE_MIN_SIDE:
            v.bad(f"small photo ({v.width}x{v.height})")
    else:
        if v.seconds < config.LIBRARY_MIN_SECONDS:
            v.bad(f"too short ({v.seconds:.1f}s)")
        if v.width < v.height * 1.2:
            v.bad(f"vertical or square ({v.width}x{v.height})")
        elif v.width < config.LIBRARY_MIN_WIDTH or v.height < config.LIBRARY_MIN_HEIGHT:
            v.bad(f"below 720p ({v.width}x{v.height})")
    if not v.ok:
        return v                        # the file itself disqualifies it: no need to decode it
    rgbs = frames(path, seconds=v.seconds)
    if not rgbs:
        v.bad("no readable frames")
        return v
    grays = [_gray(f) for f in rgbs]
    dark = sum(1 for g in grays if float(g.mean()) < 26)
    if dark >= max(1 if kind == "image" else 2, len(grays) // 2):
        v.bad("mostly black")
    sharp = sharpness(grays)
    v.measures["sharpness"] = round(sharp, 1)
    if dark < len(grays) and sharp < config.LIBRARY_MIN_SHARPNESS:
        v.bad(f"soft or blurry (sharpness {sharp:.0f})")
    if kind == "image":
        from . import filters
        if filters.text_page_still(path):
            v.bad("a page of text or a slide")
    else:
        moves = motion(grays)
        v.measures["motion"] = round(max(moves), 2) if moves else 0.0
        if moves and max(moves) < 1.2:
            v.bad("frozen frame")
        elif moves:
            static = sum(1 for d in moves if d < 0.8) / len(moves)
            cuts = sum(1 for d in moves if d > 20)
            if static >= 0.6 and cuts >= 1:
                v.bad("slideshow of stills")
            elif static >= 0.85:
                v.bad("still image, no motion")
        tb, lr = bars(grays)
        v.measures["bars"] = [round(tb, 3), round(lr, 3)]
        if tb >= config.LIBRARY_MAX_BARS:
            v.bad("letterboxed (black bars)")
        elif lr >= config.LIBRARY_MAX_BARS:
            v.bad("pillarboxed (black bars)")
        if framed(grays):
            v.bad("vertical video framed on a blurred copy")
        moving, lines = graphics_share(grays), text_bands(grays)
        v.measures["graphics"], v.measures["textBands"] = round(moving, 3), round(lines, 3)
        share = max(moving, lines)
        if share > config.LIBRARY_MAX_TEXT_SHARE:
            v.bad(f"burned-in text or graphics over {share:.0%} of the frame")
    v.hashes = signature(grays)
    facts = clip_facts(rgbs, subject, event) if clip else None
    if facts:
        v.embedding = facts["embedding"]
        v.relevance = facts["relevance"]
        classes = facts["classes"]
        v.measures["classes"] = classes
        v.measures["kindClass"] = max(classes, key=classes.get)
        if classes.get("slide", 0) + classes.get("text", 0) >= 0.5:
            v.bad("mostly text or a slide")
        elif classes.get("render", 0) >= 0.6:
            v.bad("a cartoon, game or 3D render")
        if v.relevance is not None and v.relevance < config.LIBRARY_MIN_CLIP_RELEVANCE:
            v.bad(f"does not show its subject (CLIP {v.relevance:.3f})")
    if known:
        dup = duplicate_of(v.hashes, known)
        if dup:
            v.bad(f"duplicate of {dup}")
            v.measures["duplicateOf"] = dup
    return v


# --------------------------------------------------------------------------- #
# Keeping one item
# --------------------------------------------------------------------------- #

def thumbnail(path: str, out: str, seconds: float = 0.0) -> str:
    """A 320 px JPEG from the middle of a clip (or of a photo), "" on failure."""
    seek = [] if is_still(path) or not seconds else ["-ss", f"{seconds / 2:.2f}"]
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *seek, "-i", path, "-frames:v", "1",
                        "-vf", "scale=320:-2", "-q:v", "5", out], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""


def as_jpeg(path: str, out: str) -> str:
    """A photo as an RGB JPEG (web images arrive as WebP, PNG, AVIF named .jpg)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.convert("RGB").save(out, "JPEG", quality=90)
        return out
    except Exception:  # noqa: BLE001
        return ""


def store(path: str, ident: str, kind: str, verdict: Verdict, meta: Optional[dict] = None,
          deadline: float = 0.0) -> dict:
    """
    Upload one checked clip or photo, its thumbnail and its embedding sidecar.
    Returns the row fields: storage_bucket/storage_path/thumbnail_path and the
    analysis additions (publicUrl, thumbUrl, embeddingKey, phash, check).
    Raises when the file itself cannot be uploaded; a failed thumbnail or
    sidecar only leaves that part out.
    """
    deadline = deadline or time.time() + 300
    tmp = tempfile.mkdtemp(prefix="libstore_")
    try:
        if kind == "image":
            src = as_jpeg(path, os.path.join(tmp, "photo.jpg")) or path
            key = key_for("images", ident, ".jpg")
            url = put_file(src, key, "image/jpeg", deadline)
        else:
            src = path
            key = key_for("clips", ident, ".mp4")
            url = put_file(src, key, "video/mp4", deadline)
        fields = {"storage_bucket": bucket_ref(), "storage_path": key, "thumbnail_path": None,
                  "analysis": {"publicUrl": url, "phash": hex_hashes(verdict.hashes),
                               "check": verdict.summary()}}
        if verdict.relevance is not None:
            fields["analysis"]["clipRelevance"] = round(verdict.relevance, 4)
        thumb = thumbnail(src, os.path.join(tmp, "thumb.jpg"), verdict.seconds)
        if thumb:
            tkey = key_for("thumbs", ident, ".jpg")
            try:
                fields["analysis"]["thumbUrl"] = put_file(thumb, tkey, "image/jpeg", deadline)
                fields["thumbnail_path"] = tkey
            except Exception as e:  # noqa: BLE001 - a missing thumbnail is cosmetic
                print(f"[libstore] thumbnail of {ident} not saved: {str(e)[:100]}", flush=True)
        if verdict.embedding:
            ekey = key_for("embeddings", ident, ".json")
            side = {"v": 1, "id": ident, "kind": kind, "model": MODEL, "dim": len(verdict.embedding),
                    "embedding": verdict.embedding, "phash": hex_hashes(verdict.hashes),
                    "created": now_iso(), **(meta or {})}
            try:
                put_json(side, ekey, deadline)
                fields["analysis"]["embeddingKey"] = ekey
            except Exception as e:  # noqa: BLE001 - search falls back to the text fields
                print(f"[libstore] embedding of {ident} not saved: {str(e)[:100]}", flush=True)
        return fields
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
