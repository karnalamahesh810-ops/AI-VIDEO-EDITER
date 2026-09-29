"""
Local vision: CLIP (ViT-B/16, ONNX, CPU) checks for candidate clips and photos.

Gemini reads a scene the way an editor does, but it is remote: it answers
"high demand" for minutes at a time and every call costs time. This model runs
in-process in ~70 ms a frame and is good at what an editor spots at a glance:

* the wrong KIND of picture - a slide, a page of text, a cartoon, a video game,
  a logo - which never belongs in a documentary cut;
* a portrait on a line about a place (a Supreme Court justice for "Montrose");
* how well the frames match the line at all (cosine similarity to the intent).

It is the first pass on every candidate (hard rejects never reach Gemini) and
the judge of last resort when no remote model answers.
"""
from __future__ import annotations

import base64
import io
import os
import threading
from typing import Dict, List, Optional

from . import config

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with faster-whisper
    np = None

_MEAN = (0.48145466, 0.4578275, 0.40821073)
_STD = (0.26862954, 0.26130258, 0.27577711)
_SIZE = 224

# Zero-shot classes: several phrasings each, probabilities summed per class.
CLASSES: Dict[str, List[str]] = {
    "photo": ["a photograph of a real place", "a news photograph", "an aerial photograph of a landscape",
              "a photograph of a building", "a photograph of a street", "a video frame of real footage"],
    "person": ["a portrait photograph of a person", "a photo of a politician speaking",
               "a close-up of a person's face"],
    "slide": ["a screenshot of a presentation slide", "a powerpoint slide with bullet points",
              "an infographic with lots of text"],
    "text": ["a page of printed text", "a screenshot of a website article", "a scanned document"],
    "map": ["a map", "a satellite map of a region"],
    "chart": ["a chart or graph", "a bar chart"],
    "logo": ["a logo on a plain background", "an icon"],
    "render": ["a video game screenshot", "a cartoon illustration", "a 3d render", "clip art"],
}
# Kinds that never belong in a cut unless the line asks for them.
_BAD_KINDS = ("slide", "text", "render", "logo")

_LOCK = threading.Lock()
# Sixteen sourcing threads each running a 4-thread inference would thrash the
# CPU; a few at a time keeps every check fast.
_RUN = threading.BoundedSemaphore(max(1, int(os.getenv("LOCAL_VISION_CONCURRENCY", "3"))))
_STATE: Dict[str, object] = {"loaded": False, "error": ""}
_TEXT_CACHE: Dict[str, "np.ndarray"] = {}
STATS = {"checked": 0, "rejected": 0, "decided": 0, "seconds": 0.0}


def available() -> bool:
    """The model files are present and the runtime imports (checked once)."""
    if not config.LOCAL_VISION_ENABLED or np is None:
        return False
    _load()
    return bool(_STATE.get("vision"))


def _load() -> None:
    if _STATE["loaded"]:
        return
    with _LOCK:
        if _STATE["loaded"]:
            return
        _STATE["loaded"] = True
        d = config.LOCAL_VISION_DIR
        vis = os.path.join(d, "onnx", "vision_model_quantized.onnx")
        txt = os.path.join(d, "onnx", "text_model_quantized.onnx")
        tok = os.path.join(d, "tokenizer.json")
        if not all(os.path.isfile(p) for p in (vis, txt, tok)):
            _STATE["error"] = f"no model in {d}"
            return
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, config.LOCAL_VISION_THREADS)
            _STATE["text"] = ort.InferenceSession(txt, opts, providers=["CPUExecutionProvider"])
            _STATE["tok"] = Tokenizer.from_file(tok)
            _STATE["vision"] = ort.InferenceSession(vis, opts, providers=["CPUExecutionProvider"])
            print(f"[localvision] CLIP loaded from {d}", flush=True)
        except Exception as e:  # noqa: BLE001 - a missing runtime just turns this off
            _STATE["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            _STATE.pop("vision", None)
            print(f"[localvision] off: {_STATE['error']}", flush=True)


def _prep(image) -> "np.ndarray":
    """PIL image -> normalized CHW float32 (shortest side 224, centre crop)."""
    from PIL import Image
    im = image.convert("RGB")
    w, h = im.size
    s = _SIZE / max(1, min(w, h))
    im = im.resize((max(_SIZE, round(w * s)), max(_SIZE, round(h * s))), Image.BICUBIC)
    w, h = im.size
    left, top = (w - _SIZE) // 2, (h - _SIZE) // 2
    im = im.crop((left, top, left + _SIZE, top + _SIZE))
    a = np.asarray(im, np.float32) / 255.0
    a = (a - np.array(_MEAN, np.float32)) / np.array(_STD, np.float32)
    return a.transpose(2, 0, 1)


def _norm(v: "np.ndarray") -> "np.ndarray":
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-8)


def embed_texts(texts: List[str]) -> "np.ndarray":
    """Unit-length text embeddings, cached per string."""
    out = []
    for t in texts:
        t = (t or "").strip()[:300]
        with _LOCK:
            hit = _TEXT_CACHE.get(t)
        if hit is None:
            ids = _STATE["tok"].encode(t).ids[:77]
            hit = _norm(_STATE["text"].run(None, {"input_ids": np.array([ids], np.int64)})[0][0])
            with _LOCK:
                if len(_TEXT_CACHE) > 4000:
                    _TEXT_CACHE.clear()
                _TEXT_CACHE[t] = hit
        out.append(hit)
    return np.stack(out)


def embed_images(images: list) -> "np.ndarray":
    """Unit-length embeddings for PIL images (batched)."""
    batch = np.stack([_prep(im) for im in images])
    parts = [_STATE["vision"].run(None, {"pixel_values": batch[i:i + 8]})[0]
             for i in range(0, len(batch), 8)]
    return _norm(np.concatenate(parts))


def _class_prompts():
    labels, prompts = [], []
    for k, ps in CLASSES.items():
        for p in ps:
            labels.append(k)
            prompts.append(p)
    return labels, prompts


def classify(emb: "np.ndarray") -> Dict[str, float]:
    """Mean class probabilities over the frames' embeddings."""
    labels, prompts = _class_prompts()
    logits = 100.0 * emb @ embed_texts(prompts).T
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    out: Dict[str, float] = {k: 0.0 for k in CLASSES}
    for j, lab in enumerate(labels):
        out[lab] += float(p[:, j].mean())
    return out


def _frames_from_b64(frames_b64: List[str]) -> list:
    from PIL import Image
    ims = []
    for f in frames_b64:
        try:
            ims.append(Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB"))
        except Exception:  # noqa: BLE001 - a broken frame is skipped
            continue
    return ims


def _intent_prompts(intent: str, subject: str = "") -> List[str]:
    intent = (intent or "").strip().rstrip(".")[:200]
    out = [f"a photo of {intent}", f"footage of {intent}"]
    if subject and subject.lower() not in intent.lower():
        out.append(f"a photo of {subject}")
    return out


def check(path: str = "", intent: str = "", subject_type: str = "", subject: str = "",
          frames_b64: Optional[List[str]] = None, wants: str = "") -> Optional[dict]:
    """
    Local verdict for one candidate, or None when the model is unavailable.

    {"kind": top class, "classes": {...}, "relevance": cosine to the intent,
     "reject": reason or "", "is_person": bool}
    `wants`: "map", "chart" or "document" when the line asks for that kind.
    """
    if not available():
        return None
    import time
    t0 = time.time()
    if frames_b64 is None:
        from . import vision
        frames_b64 = vision.sample_frames(path, config.VISION_FRAMES)
    images = _frames_from_b64(frames_b64 or [])
    if not images:
        return None
    try:
        with _RUN:
            emb = embed_images(images)
            classes = classify(emb)
            relevance = 0.0
            if intent:
                rel = emb @ embed_texts(_intent_prompts(intent, subject)).T
                relevance = float(rel.max(axis=1).mean())
    except Exception as e:  # noqa: BLE001 - a model error never blocks a clip
        print(f"[localvision] check failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    kind = max(classes, key=classes.get)
    reject = _reject_reason(classes, subject_type, wants)
    with _LOCK:
        STATS["checked"] += 1
        STATS["rejected"] += 1 if reject else 0
        STATS["seconds"] += time.time() - t0
    return {"kind": kind, "classes": {k: round(v, 3) for k, v in classes.items()},
            "relevance": round(relevance, 4), "reject": reject,
            "is_person": classes["person"] >= 0.5}


def _reject_reason(classes: Dict[str, float], subject_type: str, wants: str) -> str:
    share = config.LOCAL_VISION_REJECT_SHARE
    allowed = set()
    if wants in ("document", "chart", "map") or subject_type == "document":
        allowed |= {"slide", "text", "chart", "map"}
    for bad in _BAD_KINDS:
        if bad not in allowed and classes.get(bad, 0.0) >= share:
            return {"slide": "a presentation slide", "text": "a page of text",
                    "render": "a cartoon, game or 3D render", "logo": "a logo or icon"}[bad]
    # Slide + text together (an article screenshot often splits between them).
    if not allowed and classes["slide"] + classes["text"] >= share + 0.05:
        return "a slide or text screenshot"
    if subject_type in ("place", "event", "object") and classes["person"] >= share + 0.08:
        return "a portrait on a line about a place"
    return ""


def _tile_score(relevance: float) -> float:
    """Cosine to the 0-1 scale the remote tile rater uses, with the local
    relevance floor landing on VISION_MIN_SCORE."""
    return max(0.0, min(1.0, config.VISION_MIN_SCORE
                        + (relevance - config.LOCAL_VISION_MIN_RELEVANCE) * 4.0))


def rate_sheet(sheet_b64: str, count: int, intent: str, subject_type: str = "") -> Optional[List[dict]]:
    """
    Rate every tile of a numbered storyboard sheet (src/moments.py: a grid of
    5 columns) against the intent, in the shape vision.rate_tiles returns:
    [{"tile": 1-based, "score": 0-1, "description": str}]. None when the
    model is unavailable. Used when every remote model failed, so a clip still
    gets its best moment instead of a fixed grab point.
    """
    if not available() or not intent or count < 1:
        return None
    try:
        from PIL import Image
        sheet = Image.open(io.BytesIO(base64.b64decode(sheet_b64))).convert("RGB")
        cols = 5 if count >= 5 else count
        rows = (count + cols - 1) // cols
        tw, th = sheet.width // cols, sheet.height // rows
        tiles = []
        for n in range(count):
            r, c = divmod(n, cols)
            # Skip the tile number's black box in the top-left corner.
            tiles.append(sheet.crop((c * tw + 30, r * th + 22, c * tw + tw, r * th + th)))
        with _RUN:
            emb = embed_images(tiles)
            rel = (emb @ embed_texts(_intent_prompts(intent)).T).max(axis=1)
            labels, prompts = _class_prompts()
            logits = 100.0 * emb @ embed_texts(prompts).T
    except Exception as e:  # noqa: BLE001
        print(f"[localvision] sheet failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    out = []
    for n in range(count):
        z = logits[n] - logits[n].max()
        p = np.exp(z)
        p /= p.sum()
        classes = {k: 0.0 for k in CLASSES}
        for j, lab in enumerate(labels):
            classes[lab] += float(p[j])
        kind = max(classes, key=classes.get)
        bad = _reject_reason(classes, subject_type, "")
        score = 0.0 if bad else _tile_score(float(rel[n]))
        out.append({"tile": n + 1, "score": round(score, 3),
                    "description": f"local check: {bad or kind} (relevance {float(rel[n]):.3f})"})
    with _LOCK:
        STATS["decided"] += 1
    return out


def as_verdict(local: dict, intent_ok: bool) -> dict:
    """The local result in vision.judge()'s verdict shape (for the gate's
    bookkeeping when no remote model answered)."""
    rel = local.get("relevance", 0.0)
    floor = config.LOCAL_VISION_MIN_RELEVANCE
    # Map cosine (~0.15 off-topic .. ~0.32 exact) onto the 0..1 score scale
    # around the remote floor, so a local keep ranks below a strong Gemini keep.
    score = max(0.0, min(1.0, config.VISION_MIN_SCORE + (rel - floor) * 4.0))
    if not intent_ok:
        score = min(score, config.VISION_MIN_SCORE - 0.05)
    return {"description": f"local check: {local.get('kind')} (relevance {rel:.3f})",
            "score": round(score, 3), "quality": None,
            "has_text_or_watermark": local.get("kind") in ("slide", "text"),
            "is_talking_head": False, "specificity": "", "model": "local-clip"}


def stats() -> dict:
    with _LOCK:
        return dict(STATS, available=bool(_STATE.get("vision")), error=_STATE.get("error", ""))
