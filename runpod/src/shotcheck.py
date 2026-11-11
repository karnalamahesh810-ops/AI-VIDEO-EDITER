"""
Free shot checks on the render machine: the laptop kit's tools/clean_fill.py clean(), the one test its audit, refill, merge
and prescreen tools all share. Three frames of a stretch, framed as the render frames them, at 640x360:

    dark      the middle of the frame under 30 of 255
    bars      black rows or columns at an edge (letterbox, pillarbox, a phone clip inside a station frame)
    pillar    both sides much softer than the middle (a blur-filled vertical clip inside the source)
    face      YuNet, a face over 0.15% of the frame (src/stormgate.py's detector, the kit's tighter refill threshold)
    person    SSDLite MobileNetV3 person boxes (torchvision's COCO model exported to ONNX), a person over 3% of the frame
    text      RapidOCR: any line of 6+ characters, or text over 0.4% of the frame

No paid call anywhere: this replaces the vision model's per-shot judging for the Breaking News Desk.

Verdicts are shared. Every stretch screened on any pod is written to the private footage-library bucket
(sdlib/v1/screened.json, {"<id>@<a>-<b>@<mode>@v1": "" | reason}), so a later video, for any customer, never screens or
downloads it again just to learn it is bad; bad ones also go to the library's rejected moments (src/stormlib.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

VERSION = "v1"
W, H = 640, 360
SPOTS = (0.05, 0.5, 0.95)               # clean_fill.py: start, middle and end (people walk in at the ends)
DARK = 30.0
FACE = 0.0015
PERSON_SCORE = 0.55
PERSON_AREA = 0.03
TEXT_AREA = 0.004
TEXT_CHARS = 6
SCREENED_KEY = "sdlib/v1/screened.json"
PERSON_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdkit", "models", "person_ssdlite.onnx")

_tls = threading.local()
_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"loaded": False, "remote": {}, "new": {}}
STATS: Dict[str, Any] = {}


def _count(key: str, n: float = 1) -> None:
    with _LOCK:
        STATS[key] = STATS.get(key, 0) + n


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #
def _person_session() -> Optional[Any]:
    s = getattr(_tls, "person", None)
    if s is not None or getattr(_tls, "person_off", False):
        return s
    try:
        import onnxruntime as ort
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 2
        opt.inter_op_num_threads = 1
        s = _tls.person = ort.InferenceSession(PERSON_MODEL, opt, providers=["CPUExecutionProvider"])
        return s
    except Exception as e:  # noqa: BLE001 - the other checks still run; the report says
        _tls.person_off = True
        with _LOCK:
            if not STATS.get("personOff"):
                STATS["personOff"] = f"{type(e).__name__}: {str(e)[:100]}"
                print(f"[shotcheck] person check off: {STATS['personOff']}", flush=True)
        return None


def person_share(im: Any) -> float:
    """Biggest confident person box as a share of the frame (BGR 640x360), 0 when none or under 3%."""
    import cv2
    import numpy as np
    s = _person_session()
    if s is None or im is None:
        return 0.0
    if im.shape[:2] != (H, W):
        im = cv2.resize(im, (W, H))
    x = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0).transpose(2, 0, 1)
    boxes, scores, labels = s.run(None, {"image": np.ascontiguousarray(x)})
    best = 0.0
    for b, sc, lb in zip(boxes, scores, labels):
        if int(lb) == 1 and float(sc) >= PERSON_SCORE:
            best = max(best, float((b[2] - b[0]) * (b[3] - b[1])) / (W * H))
    return best if best >= PERSON_AREA else 0.0


def text_reason(im: Any) -> str:
    from . import stormgate
    rows = stormgate.read_text(im)
    area = 0.0
    for box, text, conf in rows:
        t = "".join(ch for ch in str(text) if ch.isalnum())
        if conf < stormgate.OCR_MIN_CONF or len(t) < 2:
            continue
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        area += (max(xs) - min(xs)) * (max(ys) - min(ys)) / float(W * H)
        if len(str(text)) >= TEXT_CHARS:
            return f"text ({str(text)[:40]})"
    return f"text ({area * 100:.2f}% of the frame)" if area > TEXT_AREA else ""


def frame_reason(im: Any, *, face: Optional[Callable] = None, person: Optional[Callable] = None,
                 text: Optional[Callable] = None) -> str:
    """Why one frame (BGR, 640x360 as rendered) is refused, "" when clean. The kit's order: cheap pixel tests first."""
    import cv2
    if im is None:
        return "read"
    if im.shape[:2] != (H, W):
        im = cv2.resize(im, (W, H))
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    if g[60:300, 120:520].mean() < DARK:
        return "dark"
    if ((g[40:320, :40].max(axis=0) < 16).sum() > 4 or (g[40:320, -40:].max(axis=0) < 16).sum() > 4
            or (g[:30, 80:560].max(axis=1) < 16).sum() > 4 or (g[-30:, 80:560].max(axis=1) < 16).sum() > 4):
        return "bars"

    def lap(z: Any) -> float:
        return float(cv2.Laplacian(z, cv2.CV_64F).var())
    c = lap(g[40:320, 200:440]) + 1e-6
    if lap(g[40:320, :70]) < 0.12 * c and lap(g[40:320, -70:]) < 0.12 * c:
        return "pillar"
    from . import stormgate
    if float((face or stormgate.face_share)(im) or 0.0) > FACE:
        return "face"
    if float((person or person_share)(im) or 0.0) > 0:
        return "person"
    return (text or text_reason)(im)


def frames(path: str, a: float, d: float, vf: str, spots: Sequence[float] = SPOTS) -> List[Any]:
    """Frames of path at a + d * spot, through the render's own filter, at 640x360."""
    from . import stormgate
    return [stormgate._frame_at(path, a + d * k, vf, W) for k in spots]


def check(path: str, a: float, d: float, vf: str, **kw: Any) -> str:
    """"" when every frame is clean, else the first reason."""
    t0 = time.time()
    why = ""
    for fr in frames(path, a, d, vf):
        why = frame_reason(fr, **kw)
        if why:
            break
    _count("checks")
    _count("seconds", round(time.time() - t0, 3))
    if why:
        _count("refused." + why.split(" ")[0])
    return why


_FRAMES: Dict[str, str] = {}


def _crop_at(path: str, t: float) -> Optional[tuple]:
    import re
    p = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "24", "-vf", "cropdetect=24:2:0",
                        "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    got = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", p.stderr or "")
    return tuple(int(v) for v in got[-1]) if got else None


def auto_frame(path: str, dur: float = 0.0) -> str:
    """How to frame a source that is not 16:9 (the kit chooses by eye; here by its pixels), "" for a plain crop to fill:
    rect:X,Y,W,H when black bars surround a wide picture (letterbox), fit for a square / 4:3 picture (whole, blurred sides),
    vert for a vertical one."""
    if path in _FRAMES:
        return _FRAMES[path]
    out = ""
    try:
        q = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,sample_aspect_ratio:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=60)
        info = json.loads(q.stdout or "{}")
        st = (info.get("streams") or [{}])[0]
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        sar = str(st.get("sample_aspect_ratio") or "1:1")
        try:
            n_, d_ = (float(x) for x in sar.split(":"))
            sar_f = n_ / d_ if n_ > 0 and d_ > 0 else 1.0
        except ValueError:
            sar_f = 1.0
        dur = dur or float((info.get("format") or {}).get("duration") or 0.0)
        if w and h:
            boxes = [b for b in (_crop_at(path, dur * k) for k in (0.25, 0.5, 0.75)) if b] if dur > 4 else []
            if boxes:                                       # the widest box seen: a dark scene must not look letterboxed
                bw, bh = max(b[0] for b in boxes), max(b[1] for b in boxes)
                bx, by = min(b[2] for b in boxes), min(b[3] for b in boxes)
            else:
                bw, bh, bx, by = w, h, 0, 0
            aspect = bw * sar_f / max(1, bh)
            boxed = bw < 0.92 * w or bh < 0.92 * h
            if boxed and aspect >= 1.45:
                out = f"rect:{bx / w:.3f},{by / h:.3f},{bw / w:.3f},{bh / h:.3f}"
            elif not boxed and aspect < 0.9:
                out = "vert"
            elif not boxed and aspect < 1.45:
                out = "fit"
            elif not boxed and abs(sar_f - 1.0) > 0.02:
                out = "rect:0,0,1,1"                        # an anamorphic source: square pixels first
    except Exception as e:  # noqa: BLE001 - the plain crop
        print(f"[shotcheck] framing {os.path.basename(path)}: {type(e).__name__}", flush=True)
    _FRAMES[path] = out
    _count("framed." + (out.split(":")[0] if out else "fill"))
    return out


def vf_for_mode(path: str, mode: str) -> str:
    from . import stormpieces
    w, h = stormpieces._probe_wh(path)
    return stormpieces.vf_for(mode or "full", w, h)


# --------------------------------------------------------------------------- #
# The shared verdicts
# --------------------------------------------------------------------------- #
def key(vid: str, a: float, b: float, mode: str) -> str:
    v = vid[3:] if str(vid).startswith("yt:") else str(vid)
    return f"{v}@{a:.1f}-{b:.1f}@{mode or 'full'}@{VERSION}"


def _bucket() -> str:
    from . import stormlib
    return stormlib.bucket() if stormlib.enabled() else ""


def load(get: Optional[Callable[[], Optional[bytes]]] = None) -> Dict[str, str]:
    """Every verdict any pod wrote (once per process)."""
    with _LOCK:
        if _STATE["loaded"]:
            return _STATE["remote"]
    remote: Dict[str, str] = {}
    try:
        if get is not None:
            raw = get()
        elif _bucket():
            from . import r2
            raw = r2.get_bytes(SCREENED_KEY, bucket=_bucket())
        else:
            raw = None
        if raw:
            remote = {str(k): str(v) for k, v in (json.loads(raw).get("v") or {}).items()}
    except Exception as e:  # noqa: BLE001 - screened again, nothing lost
        print(f"[shotcheck] shared verdicts not read: {type(e).__name__}", flush=True)
    with _LOCK:
        _STATE.update(loaded=True, remote=remote)
        STATS["sharedVerdicts"] = len(remote)
    return remote


def known(k: str) -> Optional[str]:
    rem = load()
    with _LOCK:
        if k in _STATE["new"]:
            return _STATE["new"][k]
    return rem.get(k)


def remember(k: str, why: str) -> None:
    with _LOCK:
        _STATE["new"][k] = why


def screen(vid: str, path: str, a: float, b: float, mode: str, *, run: Optional[Callable[[], str]] = None) -> str:
    """The stretch a..b of a source, screened once for every video (start, middle, end, as clean_fill does):
    "" = clean. A verdict another pod wrote is used as it is."""
    k = key(vid, a, b, mode)
    have = known(k)
    if have is not None:
        _count("cacheHits")
        return have
    if run is None:
        d = max(0.5, (b - a) - 0.4)
        try:
            why = check(path, a + 0.2, d, vf_for_mode(path, mode))
        except Exception as e:  # noqa: BLE001 - unreadable = unusable
            why = f"error {type(e).__name__}"
    else:
        why = run()
    remember(k, why)
    return why


def flush(put: Optional[Callable[[bytes], Any]] = None, get: Optional[Callable[[], Optional[bytes]]] = None) -> int:
    """This job's new verdicts merged into the shared file. Returns how many were added."""
    with _LOCK:
        new = dict(_STATE["new"])
    if not new:
        return 0
    try:
        if put is None:
            b = _bucket()
            if not b:
                return 0
            from . import r2
            get = get or (lambda: r2.get_bytes(SCREENED_KEY, bucket=b))
            put = put or (lambda data: r2.upload_bytes(data, SCREENED_KEY, bucket=b, deadline=time.time() + 60))
        raw = get() if get else None
        have = (json.loads(raw).get("v") or {}) if raw else {}
        have.update(new)
        put(json.dumps({"v": have, "updated": int(time.time())}, separators=(",", ":")).encode())
        with _LOCK:
            _STATE["remote"].update(new)
            _STATE["new"] = {k: v for k, v in _STATE["new"].items() if k not in new}
        _count("written", len(new))
        return len(new)
    except Exception as e:  # noqa: BLE001 - the next pod screens them again
        print(f"[shotcheck] verdicts not saved: {type(e).__name__}", flush=True)
        return 0


def report() -> dict:
    with _LOCK:
        out = dict(STATS)
    out["seconds"] = round(float(out.get("seconds") or 0.0), 1)
    return out


def reset() -> None:
    with _LOCK:
        STATS.clear()
        _STATE.update(loaded=False, remote={}, new={})


def selftest() -> dict:
    """Which detectors this machine has (the image may lack OCR)."""
    from . import stormgate
    return {"faces": stormgate.faces_available(), "ocr": stormgate.ocr_available(), "person": _person_session() is not None}

