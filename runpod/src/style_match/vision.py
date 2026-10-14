"""
Style Match: the few cheap vision calls on top of the local measurements (2026-10-14).

Pixels say WHERE a text is, its colours, size and motion; they cannot say what it reads, what role it plays
(a caption of clip speech, a punchline pop, a name label, a date, a logo that is part of the footage) or where
the cold open ends. Two calls per reference answer that, on contact sheets the worker draws itself:

  1. elements: one tile per measured text type and mark - the frame with the element boxed in red
  2. structure: the first ~90 s every 3 s (with the transcript) + an overview across the whole video

Model: STYLE_MATCH_VISION_MODEL (default google/gemini-3.1-flash-lite, ~$0.001 a call). The pass stops at
STYLE_MATCH_MAX_USD (default $0.02 a reference). No key or no credit: the kit is built from pixels alone and
says so in its confidence.
"""
import base64
import json
import os
import re
from typing import List, Optional

import numpy as np

try:
    import cv2
except Exception:  # noqa: BLE001
    cv2 = None

MODEL = os.getenv("STYLE_MATCH_VISION_MODEL", "google/gemini-3.1-flash-lite").strip()
FALLBACK = os.getenv("STYLE_MATCH_VISION_FALLBACK", "google/gemini-2.5-flash-lite").strip()
MAX_USD = float(os.getenv("STYLE_MATCH_MAX_USD", "0.02"))

ROLES = ("caption", "pop", "name_label", "title", "label", "date", "number", "lower_third", "chapter",
         "quote", "subtitle", "logo", "source_text", "other")


class Spend:
    def __init__(self, cap: float = MAX_USD):
        self.cap, self.usd, self.calls = cap, 0.0, 0

    def ok(self) -> bool:
        return self.usd < self.cap


def _key():
    try:
        from .. import config
        base = getattr(config, "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
    except Exception:  # noqa: BLE001
        base = "https://openrouter.ai/api/v1"
    return base, os.getenv("OPENROUTER_API_KEY", "") or os.getenv("VISION_API_KEY", "")


def _jpeg(img: np.ndarray, q: int = 82) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return base64.b64encode(buf.tobytes()).decode()


def ask(prompt: str, images: List[np.ndarray], spend: Spend, max_tokens: int = 2500) -> Optional[dict]:
    base, key = _key()
    if not key or not spend.ok():
        return None
    import requests
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _jpeg(im)}} for im in images]
    for model in (MODEL, FALLBACK):
        try:
            r = requests.post(f"{base}/chat/completions", timeout=120,
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                              json={"model": model, "messages": [{"role": "user", "content": content}],
                                    "max_tokens": max_tokens, "temperature": 0.1, "usage": {"include": True},
                                    "response_format": {"type": "json_object"}})
            data = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"[style-match] vision {model} failed: {type(e).__name__}", flush=True)
            continue
        spend.calls += 1
        spend.usd += float(((data.get("usage") or {}).get("cost") or 0.0)) if isinstance(data, dict) else 0.0
        try:
            txt = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            print(f"[style-match] vision {model}: {str(data)[:160]}", flush=True)
            continue
        if isinstance(txt, list):
            txt = "".join(p.get("text", "") for p in txt if isinstance(p, dict))
        m = re.search(r"\{.*\}", txt or "", re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return None


def _tile(img: np.ndarray, box, label: str, w: int = 384, h: int = 216) -> np.ndarray:
    t = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    if box is not None:
        # green corner brackets (never a closed box: a box drawn round an arrow reads as "a box")
        x0, y0, x1, y1 = int(box[0] * w) - 4, int(box[1] * h) - 4, int(box[2] * w) + 4, int(box[3] * h) + 4
        L = max(6, min(x1 - x0, y1 - y0) // 4)
        for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            cv2.line(t, (cx, cy), (cx + dx * L, cy), (0, 255, 0), 2)
            cv2.line(t, (cx, cy), (cx, cy + dy * L), (0, 255, 0), 2)
    cv2.rectangle(t, (0, 0), (len(label) * 11 + 10, 24), (0, 0, 0), -1)
    cv2.putText(t, label, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    return t


def sheet(tiles: List[np.ndarray], cols: int) -> np.ndarray:
    h, w = tiles[0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    out = np.zeros((rows * h, cols * w, 3), np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        out[r * h:(r + 1) * h, c * w:(c + 1) * w] = t
    return out


_ELEMENTS = """You are a video editor cataloguing a YouTube video's on-screen graphics.
Each numbered tile is one frame; four green corner brackets mark one measured element (the brackets are not part of the video).
For each tile answer:
- "text": the exact text between the brackets as shown (keep capitals, quotes, * for bleeps), "" if not text
- "role": one of caption (subtitle of someone speaking), pop (big emphasised quoted word/punchline), name_label (a person's name), title, label (place/thing/date label), date, number (number card), lower_third, chapter, quote, subtitle, logo, source_text (text that is part of the filmed footage, a TV bug, sign or poster), other
- "graphic": true if an editor ADDED it on top of the footage, false if it is part of the footage/logo/the drawing itself
- for marks (tiles marked M): "mark": arrow (a drawn arrow) | circle (a drawn ring) | pointer (a small triangle) | box (a drawn rectangle outline) | not_a_mark (part of the footage: clothing, a logo, a sign), and "points_at": face | object | text | nothing
Answer JSON: {"items": [{"n": "T1", "text": "...", "role": "...", "graphic": true, "mark": null, "points_at": null}, ...]}"""


def label_elements(meas: dict, spend: Spend) -> None:
    """Fills sample["vision"] (text, role, graphic) and mark["vision"] in place: text tiles and marks in their own
    calls (16 tiles a sheet), a sheet whose answer misses tiles asked once more."""
    texts, marks = [], []
    for gi, g in enumerate(meas.get("groups") or []):
        for si, s in enumerate((g.get("samples") or [])[:2]):   # two of each type: their text and role agree or not
            if s.get("_frame") is not None:
                i = s["inst"]
                texts.append((("g", gi, si), s["_frame"], (i["x0"], i["y0"], i["x1"], i["y1"])))
    for mi, mk in enumerate(meas.get("marks") or []):
        if mk.get("_frame") is not None:
            marks.append((("m", mi, 0), mk["_frame"], (mk["x0"], mk["y0"], mk["x1"], mk["y1"])))
    for prefix, rows in (("T", texts), ("M", marks)):
        for lo in range(0, len(rows), 16):
            chunk = rows[lo:lo + 16]
            tags = [f"{prefix}{k + 1}" for k in range(len(chunk))]
            tiles = [_tile(fr, box, tag) for (_, fr, box), tag in zip(chunk, tags)]
            items = {}
            for _ in range(2):
                ans = ask(_ELEMENTS, [sheet(tiles, 4)], spend)
                items.update({str(it.get("n")): it for it in (ans or {}).get("items") or [] if isinstance(it, dict)})
                if all(t in items for t in tags) or not spend.ok():
                    break
            for (ref, _, _), tag in zip(chunk, tags):
                it = items.get(tag)
                if not it:
                    continue
                kind, a, b = ref
                if kind == "g":
                    meas["groups"][a]["samples"][b]["vision"] = it
                else:
                    meas["marks"][a]["vision"] = it


_STRUCTURE = """You are a senior YouTube editor describing another channel's edit so we can copy its STYLE (not its topic).
Image 1: the first ~90 seconds, one tile every 3 s (timestamp top-left). Image 2: frames spread across the whole video.
Transcript of the opening (seconds: words): {transcript}
Answer JSON:
{{"style_name": "2-4 words, e.g. 'celeb blooper compilation', 'cartoon history explainer'",
 "summary": "one sentence on how the edit looks and feels",
 "cold_open_end": seconds or 0 if none (a teaser clip before the narrator starts),
 "hook_end": seconds the narrator's hook/intro ends,
 "first_segment_start": seconds the first main segment starts,
 "hook_formula": "how the hook is written in one sentence (e.g. contrast: 'In the movies X... but when cameras roll Y')",
 "segment_pattern": "what one segment looks like, in order",
 "content_mix": {{"footage_clips": 0-1, "talking_head": 0-1, "cartoon": 0-1, "archival_photos": 0-1, "maps": 0-1,
                 "screenshots_documents": 0-1, "number_cards": 0-1, "title_cards": 0-1, "stock_broll": 0-1, "ai_images": 0-1}},
 "visual_devices": ["short list: e.g. blur-fill vertical clips, split screen, picture-in-picture, maps with arrows, cork board, speed lines, film grain"],
 "captions_on": "all speech" | "clip speech only (people in the footage, not the narrator)" | "narration only" | "none",
 "narration": "voice and tone in a few words",
 "music": "music bed character in a few words"}}"""


def structure(meas: dict, path: str, spend: Spend) -> Optional[dict]:
    from .measure import frames
    dur = float(meas.get("duration") or 0)
    open_tiles = []
    for t, f in frames(path, 1 / 3.0, 256, 144, 0.0, min(90.0, dur)):
        open_tiles.append(_tile(f, None, f"{t:.0f}s", 256, 144))
    over = []
    thumbs = meas.get("_thumbs") or []
    if thumbs:
        idx = np.linspace(0, len(thumbs) - 1, min(24, len(thumbs))).astype(int)
        over = [_tile(thumbs[i], None, f"{i * 2 // 60}:{(i * 2) % 60:02d}", 256, 144) for i in idx]
    if not open_tiles:
        return None
    words = meas.get("words") or []
    tx = " ".join(f"[{w['s']:.0f}] {w['w']}" if k % 8 == 0 else w["w"] for k, w in enumerate(words) if w["s"] < 90)
    imgs = [sheet(open_tiles, 6)] + ([sheet(over, 6)] if over else [])
    return ask(_STRUCTURE.format(transcript=tx[:3000] or "(none)"), imgs, spend, 1500)
