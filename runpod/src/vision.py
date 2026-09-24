"""
Vision verification: look at a sourced clip and decide whether it shows the beat.

Everything upstream of this judges a candidate by its *title*. A title is what
the uploader wanted you to click, not what is in the frames — which is how a
Premiere Pro screen recording titled "Epic TRAILER TEXT Animation" landed in a
documentary. Reading VidRush's own timeline shows how they avoid it: every clip
carries a `contentDescription` written by a vision model after the download, a
`relevanceScore` comparing that description with what the shot was supposed to
show, and nothing on the timeline scores below 0.70. This is that step.

One call per candidate, three frames per call. The model returns what it
actually sees, a 0-1 relevance score against the intent, and a hard flag for
other people's text or watermarks (channel bugs, news tickers, burned-in
subtitles, stock watermarks) — which the pixel heuristics in media.py only
partly catch.

Verdicts are cached by file content, so re-sourcing a scene never pays twice
for the same candidate.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import requests

from . import config

_CACHE: Dict[str, dict] = {}
_LOCK = threading.Lock()
_CALLS = {"n": 0}
# Why recent model calls failed. A failed call returns None and the clip is
# kept unjudged, which is invisible in the timeline; the worker reports these
# so a broken key or model shows up in the job result instead of as bad clips.
_ERRORS: deque = deque(maxlen=8)
_FAILS = {"n": 0}

_SYSTEM = (
    "You check whether a video clip or photo is usable B-roll for one line of a "
    "documentary narration. You are shown frames from the candidate. Describe "
    "literally what is visible, then score how well it fits the INTENT.\n"
    "Scoring: 0.9-1.0 shows the intended subject or an unmistakable stand-in; "
    "0.7-0.89 clearly fits the topic, era and mood even if not the exact subject; "
    "0.4-0.69 loosely related; below 0.4 wrong subject.\n"
    "Score 0 and set has_text_or_watermark true if the frames show a screen "
    "recording, software UI, a video game, a news desk or presenter talking to "
    "camera, a thumbnail/title card, burned-in subtitles, a channel logo, or a "
    "stock-photo watermark. Small incidental real-world text (a street sign) is fine.\n"
    "Reply with JSON only: {\"description\": str, \"score\": number, "
    "\"has_text_or_watermark\": bool, \"is_talking_head\": bool}"
)


def enabled() -> bool:
    return bool(config.VISION_ENABLED and config.VISION_API_KEY)


def calls_made() -> int:
    return _CALLS["n"]


def reset() -> None:
    with _LOCK:
        _CACHE.clear()
        _CALLS["n"] = 0
        _FAILS["n"] = 0
        _ERRORS.clear()


def _fail(model: str, why: str) -> None:
    with _LOCK:
        _FAILS["n"] += 1
        _ERRORS.append(f"{model}: {why}"[:240])


def stats() -> dict:
    """Calls, failures and the latest failure reasons, for the job result."""
    with _LOCK:
        return {"enabled": enabled(), "model": config.VISION_MODEL,
                "calls": _CALLS["n"], "failures": _FAILS["n"],
                "recentErrors": list(_ERRORS)}


def _ask(messages: list, max_tokens: int) -> Tuple[Optional[str], str]:
    """First model that answers: (text, model). (None, "") when none did."""
    for model in [config.VISION_MODEL] + list(config.VISION_FALLBACK_MODELS):
        if not model:
            continue
        try:
            r = requests.post(
                _endpoint(model),
                headers={"Authorization": f"Bearer {config.VISION_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": model, "messages": messages,
                      "max_tokens": max_tokens, "stream": False,
                      **({"reasoning_effort": config.VISION_REASONING_EFFORT}
                         if config.VISION_REASONING_EFFORT and model.startswith("gpt-")
                         else {})},
                timeout=90)
        except requests.RequestException as e:
            _fail(model, f"request failed: {type(e).__name__}")
            continue
        try:
            body = r.json()
        except ValueError:
            _fail(model, f"HTTP {r.status_code}, not JSON: {r.text[:120]!r}")
            continue
        # Kie wraps failures in a 200: {"code": 422, "msg": ...}.
        if isinstance(body, dict) and isinstance(body.get("code"), int) and body["code"] >= 400:
            _fail(model, f"code {body['code']}: {str(body.get('msg') or '')[:150]}")
            continue
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            _fail(model, f"HTTP {r.status_code}, no choices: {json.dumps(body)[:150]}")
            continue
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        if not (text or "").strip():
            # Reasoning models can spend max_tokens thinking and return nothing.
            _fail(model, "empty answer")
            continue
        return text, model
    return None, ""


def probe() -> dict:
    """One tiny real call, for the health action: is vision reachable here?"""
    if not enabled():
        return {"ok": False, "error": "no VISION_API_KEY / DIRECTOR_API_KEY"}
    try:
        import io as _io
        from PIL import Image
        buf = _io.BytesIO()
        Image.new("RGB", (160, 90), (40, 110, 200)).save(buf, "JPEG")
        img = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"could not build test image: {e}"}
    t = time.time()
    text, model = _ask([{"role": "user", "content": [
        {"type": "text", "text": 'What colour is this image? Reply JSON {"colour": str}'},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]}], 400)
    out = {"ok": bool(text), "model": model, "seconds": round(time.time() - t, 1),
           "answer": (text or "")[:80]}
    if not text:
        out["recentErrors"] = list(_ERRORS)
    return out


def _fingerprint(path: str) -> str:
    h = hashlib.sha1()
    try:
        st = os.stat(path)
        h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
        with open(path, "rb") as fh:
            h.update(fh.read(1 << 16))
    except OSError:
        h.update(path.encode())
    return h.hexdigest()


def sample_frames(path: str, count: int = 3, width: int = 512) -> List[str]:
    """`count` evenly spaced JPEG frames as base64 strings. [] when unreadable."""
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        # A still: one downscaled copy is enough.
        cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={width}:-2",
               "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        return [base64.b64encode(p.stdout).decode()] if p.stdout else []

    dur = _duration(path)
    if not dur:
        return []
    frames = []
    for frac in [(i + 1) / (count + 1) for i in range(count)]:
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{dur * frac:.2f}", "-i", path,
               "-frames:v", "1", "-vf", f"scale={width}:-2",
               "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if p.stdout:
            frames.append(base64.b64encode(p.stdout).decode())
    return frames


def _duration(path: str) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float((p.stdout or "0").strip() or 0)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0.0


def _endpoint(model: str) -> str:
    base = config.VISION_API_BASE.rstrip("/")
    # Kie routes each model on its own path: /{model}/v1/chat/completions.
    if "kie.ai" in base:
        return f"https://api.kie.ai/{model}/v1/chat/completions"
    return f"{base}/chat/completions"


def _parse(text: str) -> Optional[dict]:
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    return {
        "description": str(data.get("description") or "")[:600],
        "score": max(0.0, min(1.0, score)),
        "has_text_or_watermark": bool(data.get("has_text_or_watermark")),
        "is_talking_head": bool(data.get("is_talking_head")),
    }


def judge(path: str, intent: str, context: str = "") -> Optional[dict]:
    """
    Verdict for one candidate file, or None when no model could be reached.

    None means "unknown", not "bad": the caller keeps its pre-vision behaviour
    rather than rejecting every clip because an API is down.
    """
    if not enabled() or not path or not os.path.exists(path):
        return None
    key = f"{_fingerprint(path)}|{intent}"
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]

    frames = sample_frames(path, config.VISION_FRAMES)
    if not frames:
        _fail("ffmpeg", f"no frames from {os.path.basename(path)}")
        return None

    content = [{"type": "text", "text":
                f"INTENT: {intent}\nNARRATION: {context}\n"
                f"These are {len(frames)} frames from the candidate."}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{f}"}} for f in frames]
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": content}]

    text, model = _ask(messages, 400)
    verdict = _parse(text) if text else None
    if verdict:
        verdict["model"] = model
    elif text:
        _fail(model, f"unparseable verdict: {text[:120]!r}")

    with _LOCK:
        _CALLS["n"] += 1
        if verdict:
            _CACHE[key] = verdict
    return verdict


def acceptable(verdict: Optional[dict], allow_people: bool = False) -> bool:
    """
    Pass/fail for a verdict. Unknown (None) passes — see judge().

    allow_people: the line is about a named person, so a portrait or that
    person speaking is the right shot, not a talking-head reject. The score
    still has to clear the floor, which is what checks it is the RIGHT person
    doing the right thing.
    """
    if verdict is None:
        return True
    if verdict["has_text_or_watermark"]:
        return False
    if verdict["is_talking_head"] and not allow_people:
        return False
    return verdict["score"] >= config.VISION_MIN_SCORE


_PICK_SYSTEM = (
    "You pick B-roll for one line of a documentary narration. You are shown a "
    "numbered grid of thumbnails taken across one YouTube video (numbers in the "
    "top-left of each tile). Choose the single tile that best SHOWS the intent. "
    "Never choose a tile showing a presenter talking to camera, a title card, "
    "on-screen text, a graphic, a map or a logo unless the intent asks for it.\n"
    "Scoring: 0.9-1.0 the tile clearly shows the intended subject; 0.7-0.89 fits "
    "the topic, era and mood; below 0.7 nothing in the grid really fits.\n"
    "The tiles are small, low-resolution thumbnails. Only score above 0.7 when you "
    "can actually make out the subject. If a tile is too blurry to identify, do not "
    "guess from the video's topic - score it low. A wrong pick costs a download.\n"
    "Reply with JSON only: {\"tile\": int, \"score\": number, \"description\": str}"
)


def pick_tile(sheet_b64: str, count: int, intent: str, context: str = "") -> Optional[dict]:
    """Best tile number (1-based) on a storyboard contact sheet, or None."""
    if not enabled():
        return None
    messages = [
        {"role": "system", "content": _PICK_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": f"INTENT: {intent}\nNARRATION: {context}\n"
                                     f"There are {count} tiles, numbered 1-{count}."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sheet_b64}"}},
        ]},
    ]
    text, model = _ask(messages, 400)
    with _LOCK:
        _CALLS["n"] += 1
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        data = json.loads(m.group(0)) if m else {}
        tile = int(data.get("tile"))
        score = max(0.0, min(1.0, float(data.get("score", 0))))
    except (ValueError, TypeError):
        _fail(model, f"unparseable tile pick: {text[:120]!r}")
        return None
    return {"tile": tile, "score": score,
            "description": str(data.get("description") or "")[:400], "model": model}
