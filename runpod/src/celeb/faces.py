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


# ------------------------------------------------------------------ local detector + tracker (no paid calls)
_YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "face_detection_yunet_2023mar.onnx")
_det = None


def local_available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return os.path.isfile(_YUNET)


def _detector(w: int, h: int):
    global _det
    import cv2
    if _det is None:
        _det = cv2.FaceDetectorYN.create(_YUNET, "", (w, h), 0.6, 0.3, 50)
    _det.setInputSize((w, h))
    return _det


def detect_rgb(frame, w: int, h: int) -> List[dict]:
    """Faces in one RGB frame (numpy HxWx3) as fractions: {cx, cy, w, h, score}."""
    import cv2
    _, found = _detector(w, h).detect(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    out = []
    for f in (found if found is not None else []):
        x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
        out.append({"cx": (x + fw / 2) / w, "cy": (y + fh / 2) / h, "w": fw / w, "h": fh / h, "score": score,
                    "talking": False, "laughing": False})
    out.sort(key=lambda f: f["cx"])
    return out


def track(path: str, t0: float, t1: float, hint: str = "", fps: float = 30.0, width: int = 960) -> List[Optional[dict]]:
    """
    The hinted face followed frame by frame over [t0, t1) of a video: one entry per frame (None where lost),
    smoothed so circles and arrows glide with the head instead of jittering.
    """
    import numpy as np
    n = max(1, int(round((t1 - t0) * fps)))
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", path, "-frames:v", str(n), "-vf",
                        f"scale={width}:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=300)
    raw = p.stdout
    if not raw:
        return [None] * n
    h = len(raw) // (width * 3 * n) if n else 0
    # the decoder may return fewer frames than asked near a file's end
    h = h or 1
    size = width * h * 3
    frames = [np.frombuffer(raw[k * size:(k + 1) * size], np.uint8).reshape(h, width, 3)
              for k in range(min(n, len(raw) // size))]
    seq: List[Optional[dict]] = []
    cur: Optional[dict] = None
    for k, fr in enumerate(frames):
        found = detect_rgb(fr, width, h)
        if cur is None:
            cur = pick(found, hint) if found else None
            seq.append(dict(cur) if cur else None)
            continue
        best = min(found, key=lambda f: (f["cx"] - cur["cx"]) ** 2 + (f["cy"] - cur["cy"]) ** 2, default=None)
        if best and abs(best["cx"] - cur["cx"]) < 0.12 and abs(best["cy"] - cur["cy"]) < 0.15:
            a = 0.45                                  # light smoothing: follows the head, drops detector jitter
            cur = {key: (cur[key] * (1 - a) + best[key] * a) if isinstance(best.get(key), float) else best[key]
                   for key in best}
        seq.append(dict(cur) if cur else None)
    seq += [seq[-1] if seq else None] * (n - len(seq))
    return seq
