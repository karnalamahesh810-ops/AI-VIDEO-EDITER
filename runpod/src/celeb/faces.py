"""
Face boxes for placing the celeb elements (circle, name label, pointer, pop, arrow): one cheap vision call per
anchor frame through OpenRouter (Gemini returns [ymin, xmin, ymax, xmax] on a 0-1000 grid). Cached per
(file, time). No identification: the script says WHO; the call only says WHERE the faces are and which one
is talking or laughing, and `pick()` chooses by the script's hint (left / right / center / speaker / largest).
"""
import base64
import json
import os
import re
import subprocess
import threading
from typing import Dict, List, Optional

import requests

MODEL = os.environ.get("CELEB_FACE_MODEL", "google/gemini-2.5-flash")
_cache: Dict[str, List[dict]] = {}
_lock = threading.Lock()
spent = {"calls": 0, "usd": 0.0}

PROMPT = ("Find every clearly visible human face in this film frame. Reply with JSON only: "
          '{"faces":[{"box":[ymin,xmin,ymax,xmax],"talking":true|false,"laughing":true|false}]} '
          "with the box on a 0-1000 grid over the whole image. Empty list if none.")


def _key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "")
    if k:
        return k
    try:
        from .. import langversion
        return langversion._openrouter_key()
    except Exception:  # noqa: BLE001
        return ""


def frame_jpeg(path: str, t: float, crop: str = "") -> bytes:
    vf = (f"{crop}," if crop else "") + "scale=768:-2"
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", vf,
                        "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"], capture_output=True, timeout=60)
    return p.stdout


def faces(path: str, t: float, crop: str = "", http=requests) -> List[dict]:
    """[{cx, cy, w, h, talking, laughing}] as fractions of the (cropped) frame; [] when the call fails."""
    ck = f"{os.path.basename(path)}|{os.path.getsize(path) if os.path.isfile(path) else 0}|{t:.2f}|{crop}"
    with _lock:
        _load_disk()
        if ck in _cache:
            return _cache[ck]
    img = frame_jpeg(path, t, crop)
    out: List[dict] = []
    key = _key()
    if img and key:
        body = {"model": MODEL, "max_tokens": 400, "temperature": 0,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}]}],
                "usage": {"include": True}}
        try:
            r = http.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=60,
                          headers={"Authorization": f"Bearer {key}"})
            data = r.json()
            spent["calls"] += 1
            spent["usd"] += float(((data.get("usage") or {}).get("cost")) or 0)
            text = data["choices"][0]["message"]["content"] or ""
            out = parse(text)
        except Exception as e:  # noqa: BLE001
            print(f"[celeb] face call failed: {type(e).__name__}", flush=True)
    with _lock:
        _cache[ck] = out
        _save_disk()
    return out


_disk_loaded = [False]


def _cache_file() -> str:
    """A JSON cache of answered frames (CELEB_FACE_CACHE): a re-render never pays for the same frame twice."""
    return os.environ.get("CELEB_FACE_CACHE", "")


def _load_disk() -> None:
    f = _cache_file()
    if _disk_loaded[0] or not f:
        return
    _disk_loaded[0] = True
    try:
        with open(f, encoding="utf-8") as fh:
            _cache.update(json.load(fh))
    except (OSError, ValueError):
        pass


def _save_disk() -> None:
    f = _cache_file()
    if not f:
        return
    try:
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(_cache, fh)
    except OSError:
        pass


def parse(text: str) -> List[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    res = []
    for f in data.get("faces") or []:
        b = f.get("box") or []
        if len(b) != 4:
            continue
        y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) / 1000.0 for v in b]
        if x1 <= x0 or y1 <= y0:
            continue
        res.append({"cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "w": x1 - x0, "h": y1 - y0,
                    "talking": bool(f.get("talking")), "laughing": bool(f.get("laughing"))})
    res.sort(key=lambda f: f["cx"])
    return res


def pick(found: List[dict], hint: str = "") -> Optional[dict]:
    """The face a script hint means: left / right / center / speaker / laugher / largest (default)."""
    if not found:
        return None
    hint = (hint or "").lower()
    if hint == "left":
        return found[0]
    if hint == "right":
        return found[-1]
    if hint == "center":
        return min(found, key=lambda f: abs(f["cx"] - 0.5))
    if hint in ("speaker", "talking"):
        talk = [f for f in found if f["talking"]]
        if talk:
            return max(talk, key=lambda f: f["h"])
    if hint in ("laugher", "laughing"):
        lau = [f for f in found if f["laughing"]]
        if lau:
            return max(lau, key=lambda f: f["h"])
    return max(found, key=lambda f: f["w"] * f["h"])
