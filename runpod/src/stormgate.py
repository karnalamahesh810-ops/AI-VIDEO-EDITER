"""
The Breaking News Desk's shot gates (the laptop kit's tools/autofix.py, textcheck.py, faces.py and facescan.py) and its one rule
for shots with nothing to show.

Before the render: OCR text and a face check on every narrated shot, framed as the render frames it. A shot that fails has
that moment rejected for every later video and is placed again, up to AUTOFIX_ROUNDS times. After the pieces are drawn: the
face check again, twice a second over each piece, because three review frames miss a reporter who walks in. Pause clips and
hook clips are exempt: real people talk there on purpose. AI shots are exempt too (nothing here can swap them for less).

No empty scenes, ever: ensure_media walks every shot with no media down one ladder, in this order, and a build that still has
one fails (EmptyShots) instead of delivering. Never a colour or a text card.

    spare bank -> footage library -> other moments of already-approved originals -> the shot beside it running on (checked)
    -> AI fill (off under the free checks unless a job asks) -> the previous shot held

Thresholds are the kit's, measured on the same frame sizes: 3 frames at 320 px wide for OCR (text over 0.4% of the frame or a
line of 6 characters), faces on those frames at 640 px, a face over 0.4% of the frame is a person on camera.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MAX_FACE = 0.004                # a face over this share of the frame: a person on camera, not someone small in a wide shot
OCR_AREA = 0.004                # readable text over this share of the frame ...
OCR_MINCH = 6                   # ... or any line this long (tools/textcheck.py)
OCR_MIN_CONF = 0.6
FRAMES_AT = (0.2, 0.5, 0.8)     # tools/framegrab.py
FRAME_W = 320
AUTOFIX_ROUNDS = 3
# The kit's full clean() (dark, bars, pillarbox, faces, people, text; src/shotcheck.py) instead of faces + text only.
FULL_CHECKS = os.getenv("STORM_FULL_CHECKS", "1").strip().lower() not in ("0", "false", "off", "no")
FACESCAN_ROUNDS = 2
PROMO_STEP = 1.5                # seconds between the pictures tried for a hook clip whose own has a promo on it
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdkit", "models", "face_yunet.onnx")

_tls = threading.local()
_OCR_STATE: Dict[str, Any] = {}
_OCR_LOCK = threading.Lock()


class EmptyShots(RuntimeError):
    """A Breaking News Desk video still has shots with nothing to show: it fails with this instead of delivering."""
    code = "empty_shots"

    def __init__(self, shots: Sequence[dict], stage: str = "plan"):
        self.shots = list(shots)
        self.stage = stage
        where = ", ".join(f"{r.get('at')} s" for r in self.shots[:6])
        more = f" and {len(self.shots) - 6} more" if len(self.shots) > 6 else ""
        super().__init__(f"empty_shots: {len(self.shots)} shot(s) have no footage after every fallback ({where}{more}). "
                         "No video was delivered. Add footage to the library or lower the number of lines, then start it again.")


# --------------------------------------------------------------------------- #
# Faces
# --------------------------------------------------------------------------- #
def _detector():
    import cv2
    det = getattr(_tls, "det", None)
    if det is None:
        cv2.setNumThreads(2)
        det = _tls.det = cv2.FaceDetectorYN.create(MODEL, "", (320, 180), 0.7, 0.3, 50)
    return det


def face_share(im: Any) -> float:
    """Biggest face in a picture (BGR array) as a share of the frame (tools/faces.py)."""
    import cv2
    if im is None or not getattr(im, "size", 0):
        return 0.0
    h, w = im.shape[:2]
    if w < 640:                 # small faces need the extra pixels
        im = cv2.resize(im, (640, int(h * 640 / w)))
    elif w > 960:
        im = cv2.resize(im, (960, int(h * 960 / w)))
    h, w = im.shape[:2]
    det = _detector()
    det.setInputSize((w, h))
    _, found = det.detect(im)
    if found is None:
        return 0.0
    return float(max(f[2] * f[3] for f in found) / float(w * h))


def faces_available() -> bool:
    try:
        _detector()
        return True
    except Exception as e:  # noqa: BLE001 - no check rather than no video; the report says
        print(f"[gate] face check off: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def _ocr() -> Optional[Any]:
    """This thread's reader (a frame takes ~0.5 s; the gate reads with up to 4 threads), None when OCR is not installed."""
    reader = getattr(_tls, "ocr", None)
    if reader is not None:
        return reader
    if _OCR_STATE.get("off"):
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR
        # Two threads per reader: onnxruntime otherwise sizes its pool by the HOST's cores (128 on a RunPod CPU
        # machine, 8 of them ours) - 60+ spinning threads per reader, pinning errors in the log.
        reader = _tls.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        return reader
    except Exception as e:  # noqa: BLE001 - the edge-based check stands in
        with _OCR_LOCK:
            if not _OCR_STATE.get("off"):
                print(f"[gate] OCR off: {type(e).__name__}: {str(e)[:120]}", flush=True)
            _OCR_STATE["off"] = True
        return None


def ocr_available() -> bool:
    return _ocr() is not None


def read_text(im: Any) -> List[tuple]:
    """[(box, text, confidence)] of a picture (BGR array): [] when nothing reads, or without OCR."""
    reader = _ocr()
    if reader is None:
        return []
    res, _ = reader(im)
    return [(box, text, float(conf)) for box, text, conf in (res or [])]


def text_verdict(rows: Sequence[tuple], w: int, h: int) -> Tuple[bool, float, str]:
    """(flagged, area, what it reads) on one frame, by tools/textcheck.py's rule."""
    area, words = 0.0, []
    for box, text, conf in rows:
        if conf < OCR_MIN_CONF or len(re.sub(r"\W", "", str(text))) < 2:
            continue
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        area += (max(xs) - min(xs)) * (max(ys) - min(ys)) / float(max(1, w * h))
        words.append(str(text))
    return (area > OCR_AREA or any(len(t) >= OCR_MINCH for t in words)), round(area, 4), " | ".join(words)[:120]


# --------------------------------------------------------------------------- #
# Frames, as the render frames them
# --------------------------------------------------------------------------- #
def _frame_at(path: str, t: float, vf: str, w: int = FRAME_W) -> Any:
    import numpy as np
    h = int(round(w * 9 / 16))
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1", "-vf",
                        f"{vf},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, timeout=120)
    size = w * h * 3
    if p.returncode != 0 or len(p.stdout) < size:
        return None
    return np.frombuffer(p.stdout[:size], np.uint8).reshape(h, w, 3)


def scene_vf(scene: dict, path: str) -> str:
    from . import stormpieces
    sd = scene.get("stormDesk") or {}
    w, h = stormpieces._probe_wh(path)
    return stormpieces.delogo_chain(sd.get("delogo") or [], w, h) + stormpieces.vf_for(stormpieces._clip_mode(scene), w, h)


def shot_frames(scene: dict, fps: int, spots: Sequence[float] = FRAMES_AT, width: int = FRAME_W, at: Optional[float] = None) -> List[Any]:
    """The shot's frames at `spots` of its length, cropped and painted as the render does. `at`: its picture from another
    second of the clip (a hook clip's picture search)."""
    m = scene.get("media") or {}
    path = str(m.get("url") or "")
    if not path or (path.startswith(("http://", "https://")) and m.get("type") != "video"):
        return []
    secs = int(scene["durationInFrames"]) / float(fps)
    start = float(m.get("trimStart") or 0.0) if at is None else float(at)
    try:
        vf = scene_vf(scene, path)
    except Exception:  # noqa: BLE001
        vf = "scale=1920:1080"
    out = []
    for k in spots:
        fr = _frame_at(path, start + secs * k, vf, width)
        if fr is not None:
            out.append(fr)
    return out


def narrated(scene: dict) -> bool:
    """A shot under the narration: the gates apply. Pause and hook clips and AI shots are exempt."""
    from . import stormdesk
    m = scene.get("media") or {}
    return m.get("type") == "video" and bool(m.get("url")) and not scene.get("natSound") and not scene.get("openClip") \
        and not stormdesk.is_ai(scene)


def check_frames(frames: Sequence[Any], *, ocr: Optional[Callable] = None, face: Optional[Callable] = None) -> str:
    """Why these frames are refused, "" when they pass: a person on camera, or text."""
    ocr = ocr or read_text
    face = face or face_share
    worst = 0.0
    for fr in frames:
        worst = max(worst, float(face(fr) or 0.0))
    if worst > MAX_FACE:
        return f"a person on camera (face {worst * 100:.2f}% of the frame)"
    best = (False, 0.0, "")
    for fr in frames:
        h, w = fr.shape[:2]
        got = text_verdict(ocr(fr), w, h)
        if got[0] and got[1] >= best[1]:
            best = got
    if best[0]:
        return f"text in the frame ({best[1] * 100:.2f}%: {best[2][:60]})"
    return ""


def fallback_text(frames: Sequence[Any]) -> str:
    """Without OCR on this machine: the edge-based reading (stormdesk.text_verdict)."""
    from . import stormdesk
    if not frames:
        return ""
    try:
        v = stormdesk.text_verdict([fr[..., ::-1] for fr in frames], 1080)
    except Exception:  # noqa: BLE001
        return ""
    return f"text in the frame ({v.get('why') or 'edges'})" if v.get("action") != "keep" else ""


# --------------------------------------------------------------------------- #
# The automatic loop before the render (tools/autofix.py)
# --------------------------------------------------------------------------- #
def scan_shots(doc: dict, cache: Dict[tuple, str], *, frames: Optional[Callable] = None, check: Optional[Callable] = None) -> List[Tuple[dict, str]]:
    """[(scene, why refused)] over the narrated shots; a shot already read is not read again."""
    fps = int(doc.get("fps") or 30)
    if FULL_CHECKS:
        from . import shotcheck
        frames = frames or (lambda s: shot_frames(s, fps, spots=shotcheck.SPOTS, width=shotcheck.W))
    frames = frames or (lambda s: shot_frames(s, fps))
    check = check or _default_check

    def key(s: dict) -> tuple:
        m = s.get("media") or {}
        return (str(m.get("url")), round(float(m.get("trimStart") or 0.0), 2), int(s["durationInFrames"]),
                str((s.get("stormDesk") or {}).get("mode") or ""))

    def one(s: dict) -> Tuple[dict, str]:
        k = key(s)
        if k in cache:
            return s, cache[k]
        fr = frames(s)
        why = check(fr) if fr else ""
        cache[k] = why
        return s, why
    todo = [s for s in doc.get("scenes") or [] if narrated(s) and not s.get("userPicked")]
    if not todo:
        return []
    with ThreadPoolExecutor(max(1, min(4, os.cpu_count() or 2))) as ex:
        rows = list(ex.map(one, todo))
    return [(s, why) for s, why in rows if why]


def _default_check(frames: Sequence[Any]) -> str:
    if FULL_CHECKS:
        return _full_check(frames)
    if ocr_available():
        return check_frames(frames)
    return check_frames(frames, ocr=lambda _f: []) or fallback_text(frames)


def _full_check(frames: Sequence[Any]) -> str:
    """The kit's clean() on the shot as rendered (src/shotcheck.py): dark, black bars, a blurred pillarbox, a face, a person,
    text. Without OCR on the machine the edge reading stands in for the text part."""
    from . import shotcheck
    text = None if ocr_available() else (lambda fr: fallback_text([fr]))
    for fr in frames:
        why = shotcheck.frame_reason(fr, text=text)
        if why:
            return {"face": "a person on camera (face)", "person": "a person on camera (body)"}.get(why, why)
    return ""


def _label(why: str) -> str:
    w = str(why or "")
    if w.startswith("a person"):
        return "person"
    for k in ("dark", "bars", "pillar", "read", "error"):
        if w.startswith(k):
            return k
    return "text"


def clear_scene(scene: dict, why: str) -> None:
    """The shot has nothing to show now: the ladder fills it; it keeps what it had in case nothing else exists."""
    if scene.get("media"):
        scene["_wasMedia"] = {"media": scene.get("media"), "semanticMetadata": scene.get("semanticMetadata"),
                              "stormDesk": scene.get("stormDesk"), "why": why}
    scene["media"] = {}
    scene.pop("hookTail", None)


def restore_flagged(doc: dict) -> List[dict]:
    """A shot the ladder could fill with nothing keeps the picture it had, marked for review. Returns their rows."""
    fps = int(doc.get("fps") or 30)
    rows = []
    for s in doc.get("scenes") or []:
        was = s.pop("_wasMedia", None)
        if not was:
            continue
        if (s.get("media") or {}).get("url"):
            continue
        s["media"] = was["media"]
        s["semanticMetadata"] = was["semanticMetadata"]
        if was.get("stormDesk") is not None:
            s["stormDesk"] = was["stormDesk"]
        s["reviewRequired"] = True
        s["reviewReason"] = str(was.get("why") or "")[:160]
        s["stormDeskIssue"] = "gate"
        rows.append({"at": round(int(s["startFrame"]) / float(fps), 1), "why": str(was.get("why") or "")[:160]})
    return rows


def forget_was(doc: dict) -> None:
    for s in doc.get("scenes") or []:
        s.pop("_wasMedia", None)


def autofix(doc: dict, inp: dict, work: str, *, rounds: int = AUTOFIX_ROUNDS, frames: Optional[Callable] = None,
            check: Optional[Callable] = None, fill: Optional[Callable] = None, reject: Optional[Callable] = None) -> dict:
    """Round after round: read the narrated shots, reject the moments that fail, place those shots again. Stops when clean or
    when nothing is left to place. A shot left with nothing keeps its picture and says so."""
    from . import stormdesk, stormlib
    fps = int(doc.get("fps") or 30)
    reject = reject or (lambda vid, a, b, why: stormlib.remember_bad(vid, a, b))
    fill = fill or (lambda: ensure_media(doc, inp, work, allow_hold=False))
    rep: Dict[str, Any] = {"ocr": "rapidocr" if check or ocr_available() else "edges",
                           "faces": bool(check) or faces_available(), "rounds": 0, "rejected": 0, "byReason": {}}
    cache: Dict[tuple, str] = {}
    for r in range(rounds):
        hits = scan_shots(doc, cache, frames=frames, check=check)
        rep["rounds"] = r + 1
        if not hits:
            break
        for s, why in hits:
            mo = stormdesk.moment(s, fps)
            if mo:
                reject(mo[0], mo[1], mo[2], why)
            label = _label(why)
            rep["byReason"][label] = rep["byReason"].get(label, 0) + 1
            rep["rejected"] += 1
            clear_scene(s, why)
        fill()
    # What is left flagged goes to the last rung (a hold), else keeps its own picture and says so.
    if any(s.get("_wasMedia") and not has_picture(s) for s in doc.get("scenes") or []):
        try:
            rep["held"] = _rung_hold(doc)
        except Exception as e:  # noqa: BLE001
            print(f"[gate] hold: {type(e).__name__}: {str(e)[:160]}", flush=True)
        left = restore_flagged(doc)
        if left:
            rep["stillFlagged"] = left
    forget_was(doc)
    return rep


# --------------------------------------------------------------------------- #
# The check on the drawn pieces (tools/facescan.py)
# --------------------------------------------------------------------------- #
def piece_faces(path: str, *, read: Optional[Callable] = None, face: Optional[Callable] = None) -> float:
    """The biggest face over a drawn piece, twice a second at 640 px."""
    import numpy as np
    face = face or face_share
    if read is not None:
        return max([float(face(f) or 0.0) for f in read(path)] + [0.0])
    w, h = 640, 360
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps=2,scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                       capture_output=True, timeout=300)
    size = w * h * 3
    best = 0.0
    for k in range(len(p.stdout) // size):
        best = max(best, float(face(np.frombuffer(p.stdout, np.uint8, size, k * size).reshape(h, w, 3))))
    return best


def facescan(doc: dict, inp: dict, paths: Sequence[str], work: str, *, scan: Optional[Callable] = None,
             fill: Optional[Callable] = None, reject: Optional[Callable] = None, change: bool = True) -> List[dict]:
    """Narrated pieces with a person on camera: their moments rejected, the shots placed again. Returns one row per shot;
    the caller draws the changed shots and looks once more. doc is changed in place. paths: one file per scene. change False
    only reports (a render of a timeline someone edited: the editor's choices are never swapped behind their back)."""
    from . import stormdesk, stormlib
    fps = int(doc.get("fps") or 30)
    scan = scan or piece_faces
    reject = reject or (lambda vid, a, b, why: stormlib.remember_bad(vid, a, b))
    fill = fill or (lambda: ensure_media(doc, inp, work, allow_hold=False))
    scenes = doc.get("scenes") or []

    def one(k: int) -> Tuple[int, float]:
        return k, float(scan(paths[k]))
    todo = [k for k, s in enumerate(scenes) if k < len(paths) and narrated(s) and not s.get("userPicked")]
    with ThreadPoolExecutor(max(1, min(4, os.cpu_count() or 2))) as ex:
        got = list(ex.map(one, todo))
    rows = []
    for k, best in got:
        if best <= MAX_FACE:
            continue
        s = scenes[k]
        why = f"a person on camera in the drawn shot (face {best * 100:.2f}% of the frame)"
        rows.append({"at": round(int(s["startFrame"]) / float(fps), 1), "face": round(best, 4)})
        if not change:
            continue
        mo = stormdesk.moment(s, fps)
        if mo:
            reject(mo[0], mo[1], mo[2], why)
        clear_scene(s, why)
    if rows and change:
        fill()
        left = restore_flagged(doc)
        forget_was(doc)
        if left:
            rows.append({"stillFlagged": left})
    return rows


# --------------------------------------------------------------------------- #
# A hook clip's picture (the kit's audio_in + the QR code and logo the laptop let through)
# --------------------------------------------------------------------------- #
def _qr(fr: Any) -> bool:
    import cv2
    try:
        found, _pts = cv2.QRCodeDetector().detect(fr)
        return bool(found)
    except Exception:  # noqa: BLE001
        return False


def _logo_card(fr: Any) -> bool:
    """A logo or a title card, no words needed (the CBS eye): the picture's kind by CLIP when the model is here, and a frame
    that is mostly one flat colour."""
    import numpy as np
    grey = fr.mean(axis=2)
    if float((np.abs(grey - np.median(grey)) < 10).mean()) > 0.80:
        return True
    try:
        from PIL import Image
        from . import localvision
        if not localvision.available():
            return False
        kinds = localvision.classify(localvision.embed_images([Image.fromarray(fr[..., ::-1])])[0])
        return max(kinds, key=kinds.get) in ("logo", "slide", "text")
    except Exception:  # noqa: BLE001 - the words and the QR check stand
        return False


def promo_reason(frames: Sequence[Any], *, ocr: Optional[Callable] = None, qr: Optional[Callable] = None,
                 logo: Optional[Callable] = None) -> str:
    """Why these frames are a promo or carry big text: a QR code, words, a logo or title card. "" = a clean picture."""
    ocr = ocr or read_text
    qr = qr or _qr
    logo = logo or _logo_card
    for fr in frames:
        if qr(fr):
            return "a QR code"
        h, w = fr.shape[:2]
        got = text_verdict(ocr(fr), w, h)
        if got[0]:
            return f"big text ({got[2][:50]})"
        if logo(fr):
            return "a logo or title card"
    return ""


def hook_pictures(doc: dict, *, frames_at: Optional[Callable] = None, reason: Optional[Callable] = None) -> List[dict]:
    """Every hook clip's picture checked: one with a promo or big text takes another stretch of its own clip while its sound
    stays where it was (media.audioIn). Returns one row per clip acted on; "clean": False = no clean stretch in this clip."""
    fps = int(doc.get("fps") or 30)
    reason = reason or promo_reason
    rows = []
    for i, s in enumerate(doc.get("scenes") or []):
        if not s.get("openClip"):
            continue
        m = s.get("media") or {}
        if m.get("type") != "video" or not m.get("url"):
            continue
        read = frames_at or (lambda sc, at: shot_frames(sc, fps, at=at))
        here = float(m.get("trimStart") or 0.0)
        why = reason(read(s, here))
        if not why:
            continue
        secs = int(s["durationInFrames"]) / float(fps)
        room = float(m.get("clipSeconds") or 0.0)
        at, found = 0.0, None
        tries = 0
        while at + secs <= room - 0.05 and tries < 14:
            if abs(at - here) >= 1.0:
                tries += 1
                if not reason(read(s, at)):
                    found = at
                    break
            at += PROMO_STEP
        row: Dict[str, Any] = {"shot": i, "why": why, "clean": found is not None}
        if found is not None:
            if not isinstance(m.get("audioIn"), (int, float)):
                m["audioIn"] = round(here, 3)
            m["trimStart"] = round(found, 3)
            row["picture"], row["audioIn"] = m["trimStart"], m["audioIn"]
        else:
            s["reviewRequired"] = True
            s["reviewReason"] = f"hook clip: {why}"
            s["stormDeskIssue"] = "hook picture"
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# No empty scenes, ever
# --------------------------------------------------------------------------- #
def has_picture(scene: dict) -> bool:
    """A real picture to show. A text card counts as nothing here (the pieces engine would only draw words on a colour)."""
    m = scene.get("media") or {}
    return m.get("type") in ("video", "image") and bool(str(m.get("url") or "").strip())


def empty_scenes(doc: dict) -> List[dict]:
    return [s for s in doc.get("scenes") or [] if not has_picture(s)]


def empty_rows(doc: dict) -> List[dict]:
    fps = int(doc.get("fps") or 30)
    return [{"id": s.get("id"), "at": round(int(s.get("startFrame") or 0) / float(fps), 1),
             "seconds": round(int(s.get("durationInFrames") or 0) / float(fps), 1), "text": str(s.get("text") or "")[:80]}
            for s in empty_scenes(doc)]


def _scene_job(doc: dict, i: int) -> dict:
    fps = int(doc.get("fps") or 30)
    s = doc["scenes"][i]
    sm = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
    return {"index": i, "intent": sm.get("intent") or s.get("intent") or "", "context": s.get("text") or "",
            "query": s.get("query") or sm.get("searchQuery") or "", "subject": sm.get("subject") or "",
            "place": " ".join(str(p) for p in (sm.get("locations") or []) if p),
            "seconds": int(s.get("durationInFrames") or 0) / float(fps), "visual_type": "footage"}


def apply_asset(scene: dict, asset: Any, why: str = "") -> None:
    """A placed clip (a MediaAsset of the source bank's kind, its file cut exactly) on a scene that had nothing."""
    moment = dict(getattr(asset, "moment", None) or {})
    a = float(moment.get("start") or 0.0)
    vid = str(getattr(asset, "url", "") or "")
    m = re.search(r"v=([A-Za-z0-9_-]{11})", vid)
    src = "yt:" + m.group(1) if m else vid
    sm = scene.get("semanticMetadata") if isinstance(scene.get("semanticMetadata"), dict) else {}
    keep = {k: v for k, v in sm.items() if k not in ("channel", "uploadDate", "pageUrl", "reupload", "moment", "sourceUrl", "assetId")}
    keep.update({"channel": str(getattr(asset, "channel", "") or "")[:80], "sourceUrl": f"https://www.youtube.com/watch?v={src[3:]}&t={int(a)}" if m else vid,
                 "moment": {"start": round(a, 2)}, "assetId": f"{src}@{int(a)}", "provider": "youtube",
                 "contentDescription": str(getattr(asset, "content_description", "") or "")[:300], "replacedStill": why or "empty"})
    up = str(getattr(asset, "upload_date", "") or "")
    if re.fullmatch(r"\d{8}", up):
        keep["uploadDate"] = up
    scene["media"] = {"type": "video", "url": str(getattr(asset, "local_path", "")), "source": "youtube",
                      "attribution": str(getattr(asset, "attribution", "") or "")[:300],
                      "license": str(getattr(asset, "license", "") or ""),
                      "clipSeconds": round(float(getattr(asset, "duration", 0.0) or 0.0), 3)}
    scene["semanticMetadata"] = keep
    scene["visualType"] = "footage"
    scene["motion"] = "none"
    scene.pop("reviewRequired", None)
    scene.pop("_wasMedia", None)
    sd = scene.get("stormDesk") if isinstance(scene.get("stormDesk"), dict) else {}
    scene["stormDesk"] = {k: v for k, v in sd.items() if k not in ("mode", "delogo", "cropped")}


def _rung_spare(doc: dict) -> int:
    from . import stormdesk
    return int(stormdesk.replace_stills(doc, reuse=False, hold=False, only_empty=True).get("replaced") or 0)


def _rung_library(doc: dict, inp: dict, work: str) -> int:
    from . import stormlib
    jobs = [_scene_job(doc, i) for i, s in enumerate(doc["scenes"]) if not has_picture(s)]
    got = stormlib.fill_scenes(jobs, work, inp=inp) if jobs else {}
    for i, asset in got.items():
        apply_asset(doc["scenes"][i], asset, "footage library")
    return len(got)


def _rung_originals(doc: dict, work: str) -> int:
    from . import srcbank, stormdesk
    n = 0
    jobs = [_scene_job(doc, i) for i, s in enumerate(doc["scenes"]) if not has_picture(s)]
    if jobs:
        for i, asset in srcbank.fill_gaps(jobs, {j["index"]: None for j in jobs}, work).items():
            apply_asset(doc["scenes"][i], asset, "another moment of a reviewed source")
            n += 1
    if empty_scenes(doc):
        n += int(stormdesk.replace_stills(doc, spare=False, hold=False, only_empty=True, near=True).get("replaced") or 0)
    return n


def _rung_stretch(doc: dict, *, check: Optional[Callable[[str, float, float, str], str]] = None,
                  cut: Optional[Callable[[str, float, float], str]] = None) -> int:
    """The kit's tools/merge_clean.py: an empty narrated shot shows its neighbour's take running on (the moment right after the
    shot before it, or right before the shot after it), only when those frames pass the free checks and no earlier video or
    other shot used them. Same source, continuous frames: the cut does not show. Never next to a pause or hook clip."""
    from types import SimpleNamespace
    from . import filters, shotcheck, stormdesk
    fps = int(doc.get("fps") or 30)
    scenes = sorted(doc.get("scenes") or [], key=lambda x: int(x["startFrame"]))
    check = check or (lambda path, a, d, mode: shotcheck.check(path, a, d, shotcheck.vf_for_mode(path, mode)))
    cut = cut or (lambda path, a, d: filters.trim_clip(path, a, d))
    taken: Dict[str, List[Tuple[float, float]]] = {}
    for x in scenes:
        mo = stormdesk.moment(x, fps)
        if mo:
            taken.setdefault(mo[0], []).append((mo[1], mo[2]))
    led = stormdesk.JOB_LEDGER

    def free(vid: str, a: float, b: float) -> bool:
        if any(min(b, q) - max(a, p) > 0.05 for p, q in taken.get(vid, [])):
            return False
        return not (led is not None and led.used(vid, a, b))
    n = 0
    for k, s in enumerate(scenes):
        if has_picture(s) or s.get("natSound") or s.get("openClip"):
            continue
        d = int(s["durationInFrames"]) / float(fps)
        for side in (-1, 1):
            j = k + side
            if not (0 <= j < len(scenes)):
                continue
            o = scenes[j]
            if o.get("natSound") or o.get("openClip") or stormdesk.is_ai(o) or (o.get("media") or {}).get("type") != "video":
                continue
            mo = stormdesk.moment(o, fps)
            if not mo:
                continue
            vid, a0, b0 = mo
            path = stormdesk._source_file(vid[3:])
            if not path:
                continue
            a = b0 if side < 0 else a0 - d
            if a < 0 or not free(vid, a, a + d):
                continue
            mode = str((o.get("stormDesk") or {}).get("mode") or "full")
            if check(path, a, d, mode):
                continue
            clip = cut(path, a, d)
            if not clip:
                continue
            sm = o.get("semanticMetadata") if isinstance(o.get("semanticMetadata"), dict) else {}
            asset = SimpleNamespace(moment={"start": a}, url=f"https://www.youtube.com/watch?v={vid[3:]}", local_path=clip,
                                    channel=sm.get("channel") or "", duration=d, attribution=(o.get("media") or {}).get("attribution") or "",
                                    license=(o.get("media") or {}).get("license") or "", content_description=sm.get("contentDescription") or "",
                                    upload_date=sm.get("uploadDate") or "")
            apply_asset(s, asset, "the shot beside it running on")
            if mode != "full":
                s.setdefault("stormDesk", {})["mode"] = mode
            taken.setdefault(vid, []).append((a, a + d))
            n += 1
            break
    return n


def _rung_ai(doc: dict, inp: dict, work: str) -> int:
    """AI pictures for what is left (Avatarity, then OpenRouter), the job's own ai_fill block or a small one of the style's own."""
    from . import aifill, config, stormdesk
    # Paid pictures: off by default under the free checks (config.STORM_FREE); a job asks with ai_fill_empty true.
    if stormdesk.options(inp).get("ai_fill_empty", not getattr(config, "STORM_FREE", False)) is False:
        return 0
    todo = empty_scenes(doc)
    if not todo:
        return 0
    if not aifill.enabled():
        cap = max(1, min(len(todo), int(getattr(config, "STORM_EMPTY_AI_MAX", 12))))
        aifill.start({**inp, "ai_fill": {"enabled": True, "max_pictures": cap, "max_clips": 0, "provider": "avatarity",
                                         "openrouter_fallback": True}}, work=work,
                     project_id=str(inp.get("project_id") or ""), job_id=str(inp.get("_job_id") or ""))
    if not aifill.enabled():
        return 0
    before = len(todo)
    aifill.set_story((doc.get("meta") or {}).get("story") or {})
    aifill.fill_doc(doc, work=work, story=(doc.get("meta") or {}).get("story") or {}, only=todo, label="the empty-shot ladder")
    return before - len(empty_scenes(doc))


def _rung_hold(doc: dict) -> int:
    from . import stormdesk
    return int(stormdesk.replace_stills(doc, spare=False, reuse=False, hold=True, only_empty=True).get("held") or 0)


def ensure_media(doc: dict, inp: dict, work: str, *, allow_hold: bool = True, rungs: Optional[Dict[str, Callable[[], int]]] = None) -> dict:
    """Every shot with no picture down the ladder: {"before", "left", "<rung>": filled}. A rung that fails is reported and the
    next one runs; holding is the very last step. Never raises (assert_no_empty is what fails a video)."""
    before = len(empty_scenes(doc))
    rep: Dict[str, Any] = {"before": before}
    if not before:
        rep["left"] = 0
        return rep
    # A text card is nothing to show: the ladder treats it as the empty shot it is.
    for s in empty_scenes(doc):
        if (s.get("media") or {}).get("type") == "animation":
            s["media"] = {}
    ladder: List[Tuple[str, Callable[[], int]]] = list((rungs or {
        "spare": lambda: _rung_spare(doc),
        "library": lambda: _rung_library(doc, inp, work),
        "originals": lambda: _rung_originals(doc, work),
        "stretch": lambda: _rung_stretch(doc),
        "ai": lambda: _rung_ai(doc, inp, work),
        "hold": lambda: _rung_hold(doc),
    }).items())
    for name, rung in ladder:
        if name == "hold" and not allow_hold:
            continue
        if not empty_scenes(doc):
            break
        try:
            rep[name] = int(rung() or 0)
        except Exception as e:  # noqa: BLE001 - the next rung
            rep[name] = 0
            rep.setdefault("errors", []).append(f"{name}: {type(e).__name__}: {str(e)[:160]}")
            print(f"[gate] ladder, {name}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    rep["left"] = len(empty_scenes(doc))
    print(f"[gate] empty shots: {json.dumps(rep)[:300]}", flush=True)
    return rep


def assert_no_empty(doc: dict, stage: str = "plan") -> None:
    """A video with a shot that has nothing to show never ships. Raises EmptyShots."""
    rows = empty_rows(doc)
    if rows:
        raise EmptyShots(rows, stage)
