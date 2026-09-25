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
# Candidates no model could judge at all (all attempts failed, or no frames):
# kept unscored, so the job result reports how many reached the timeline that way.
_UNJUDGED = {"n": 0}

_SYSTEM = (
    "You check whether a video clip or photo is usable B-roll for one line of a "
    "documentary narration. You are shown frames from the candidate. Describe "
    "literally what is visible, then score how well it fits the INTENT.\n"
    "First check every NAMED thing in the INTENT - a person, a place, a year or era. "
    "These are hard limits, not preferences:\n"
    "- A named PERSON: above 0.7 only if the frames plausibly show THAT person (a "
    "recognisable public figure, or a period photo consistent with who they are). "
    "A different person, an anonymous stand-in, a stock model, a wedding or family "
    "photo of strangers: at most 0.3.\n"
    "- A named PLACE: footage recognisably from somewhere else (another city, country, "
    "landscape or architecture - Berlin for a line about Honolulu): at most 0.3.\n"
    "- A YEAR or ERA: footage clearly from another era (1940s film for a 1970s line, "
    "modern HD streets, cars or phones for a line about the past): at most 0.4.\n"
    "Then: 0.9-1.0 clearly shows the intended subject; 0.7-0.89 consistent with every "
    "named person, place and era and shows what the line is about; 0.4-0.69 loosely "
    "related; below 0.4 wrong. Never reward mood alone.\n"
    "- AI-GENERATED or fake: an AI image or AI video (over-smooth skin, glossy "
    "uncanny faces, warped hands or text, impossible architecture, a 'historical' "
    "scene rendered like a video game or a painting) shown as a real person, place, "
    "event or era: at most 0.2 - a documentary shows the real thing. A Hollywood "
    "movie scene, a TV show, stock actors posing and music videos: at most 0.3. "
    "But an era-accurate documentary reconstruction of an unfilmed private moment "
    "(a 1970s bedroom, hands typing a 1960s file) is fine when the INTENT asks for "
    "reconstruction footage and no face is presented as the named person.\n"
    "Score 0 and set has_text_or_watermark true if the frames show a lyric video, "
    "glitch art or corrupted/blocky frames, or a screen "
    "recording, software UI, a video game, a news desk or presenter talking to "
    "camera, a thumbnail/title card, burned-in subtitles, a channel logo, a "
    "stock-photo watermark, a product listing or poster for sale, a website "
    "screenshot, or a meme or collage with text. Small incidental real-world text "
    "(a street sign) is fine.\n"
    "STORY is the whole video's subject. A shot that contradicts it (another "
    "person, another event, another era) is wrong even if it fits the line's "
    "words. For an abstract line (a feeling, a decision, a record), era-accurate "
    "footage of the ACTION in the story's setting - hands on a typewriter for a "
    "1960s file, airmail letters for letters, an archive box for a record - is "
    "what a documentary editor uses: 0.7-0.85. Modern generic stock for a "
    "historical story: at most 0.4.\n"
    "Separately rate quality 0-1 as documentary footage, whatever the subject: sharp, "
    "stable, well lit, well composed, filling a 16:9 frame, with motion or visual "
    "interest is high; blurry, blocky compression, shaky, very dark, a vertical phone "
    "video with bars or blur down the sides, or a flat uninteresting frame is low.\n"
    "Reply with JSON only: {\"description\": str, \"score\": number, \"quality\": number, "
    "\"has_text_or_watermark\": bool, \"is_talking_head\": bool}"
)

# Added for a beat of a news, weather or disaster story. Without it "clearly fits
# the topic ... even if not the exact subject" scored any flooded street 0.7+ for
# a line about one particular flood, which is how random footage passed.
_EVENT_RULE = (
    "\nTHIS LINE IS ABOUT ONE SPECIFIC REAL EVENT at a real place, named in the "
    "INTENT. Footage of the same kind of thing somewhere else is the wrong shot. "
    "Score instead: 0.9-1.0 recognisably that event or place (matching landmarks, "
    "signage, terrain, river, architecture); 0.7-0.89 consistent with that place and "
    "event with nothing contradicting it; below 0.7 generic or stock-looking footage, "
    "or anything from another country, climate, season or era than the one named. "
    "A news outlet's aerial or on-the-ground footage of the event is ideal; the news "
    "desk or a reporter talking to camera is still a talking head."
)


# Kie shares one balance across vision, the director and image generation.
# When it answers "402 Credits insufficient" every later call fails the same
# way: a 362-scene job made 2,631 failed calls after its balance ran out.
_OUT_OF_CREDITS = {"hit": False}


def is_credit_error(code, msg: str = "") -> bool:
    return code == 402 or "credits insufficient" in str(msg or "").lower()


def note_out_of_credits() -> None:
    with _LOCK:
        _OUT_OF_CREDITS["hit"] = True


def out_of_credits() -> bool:
    return _OUT_OF_CREDITS["hit"]


OUT_OF_CREDITS_MESSAGE = (
    "The AI account (Kie) is out of credits, so shots could not be planned or "
    "checked and the video would be random clips. Top up the Kie account whose "
    "key is set on the RunPod endpoint (DIRECTOR_API_KEY), then run it again.")


class OutOfCredits(RuntimeError):
    """The AI account ran dry and REQUIRE_AI is on: stop the job, say why."""


def require_credits() -> None:
    if config.REQUIRE_AI and ai_exhausted():
        raise OutOfCredits(OUT_OF_CREDITS_MESSAGE)


def fallback_configured() -> bool:
    return bool(config.AI_FALLBACK_API_BASE and config.AI_FALLBACK_API_KEY
                and config.AI_FALLBACK_VISION_MODEL)


def ai_exhausted() -> bool:
    """The main AI account is out of credits and there is no backup provider."""
    return _OUT_OF_CREDITS["hit"] and not fallback_configured()


def enabled() -> bool:
    main = bool(config.VISION_API_KEY) and not _OUT_OF_CREDITS["hit"]
    return bool(config.VISION_ENABLED and (main or fallback_configured()))


def calls_made() -> int:
    return _CALLS["n"]


def reset() -> None:
    with _LOCK:
        _CACHE.clear()
        _CALLS["n"] = 0
        _FAILS["n"] = 0
        _UNJUDGED["n"] = 0
        _OUT_OF_CREDITS["hit"] = False
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
                "unjudged": _UNJUDGED["n"],
                "outOfCredits": _OUT_OF_CREDITS["hit"],
                "recentErrors": list(_ERRORS)}


def _ask_once(model: str, messages: list, max_tokens: int, url: str = "",
              key: str = "", main: bool = True) -> Tuple[Optional[str], bool]:
    """(text, retryable): one call to one model; retryable when the failure was transient."""
    try:
        r = requests.post(
            url or _endpoint(model),
            headers={"Authorization": f"Bearer {key or config.VISION_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "max_tokens": max_tokens, "stream": False,
                  **({"reasoning_effort": config.VISION_REASONING_EFFORT}
                     if config.VISION_REASONING_EFFORT and model.startswith("gpt-")
                     else {})},
            timeout=90)
    except requests.RequestException as e:
        _fail(model, f"request failed: {type(e).__name__}")
        return None, True
    try:
        body = r.json()
    except ValueError:
        _fail(model, f"HTTP {r.status_code}, not JSON: {r.text[:120]!r}")
        return None, r.status_code >= 500 or r.status_code == 429
    # Kie wraps failures in a 200: {"code": 422, "msg": ...}.
    if isinstance(body, dict) and isinstance(body.get("code"), int) and body["code"] >= 400:
        _fail(model, f"code {body['code']}: {str(body.get('msg') or '')[:150]}")
        if is_credit_error(body["code"], body.get("msg")):
            if main:
                note_out_of_credits()
            return None, False
        return None, body["code"] >= 500 or body["code"] == 429
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        _fail(model, f"HTTP {r.status_code}, no choices: {json.dumps(body)[:150]}")
        return None, r.status_code >= 500
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if not (text or "").strip():
        # Reasoning models can spend max_tokens thinking and return nothing.
        _fail(model, "empty answer")
        return None, False
    return text, False


def _ask(messages: list, max_tokens: int) -> Tuple[Optional[str], str]:
    """
    First model that answers: (text, model). (None, "") when none did.

    A transient failure (timeout, HTTP/Kie 5xx, 429) is retried once on the
    same model before moving on. Kie's gpt-5-2 answers "code 500: Server
    exception, please try again later" in bursts - 116 of 609 calls on one
    real job - and moving straight on meant a burst on the fallback too left
    clips on the timeline that no model had ever looked at.
    """
    routes = [(m, "", "", True) for m in [config.VISION_MODEL] + list(config.VISION_FALLBACK_MODELS)
              if m and config.VISION_API_KEY]
    if fallback_configured():
        routes.append((config.AI_FALLBACK_VISION_MODEL,
                       f"{config.AI_FALLBACK_API_BASE}/chat/completions",
                       config.AI_FALLBACK_API_KEY, False))
    for model, url, key, main in routes:
        if main and _OUT_OF_CREDITS["hit"]:
            continue
        for attempt in range(1 + config.VISION_RETRIES):
            if attempt:
                time.sleep(config.VISION_RETRY_WAIT)
            text, retryable = _ask_once(model, messages, max_tokens, url, key, main)
            if text:
                return text, model
            if not retryable:
                break
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
    try:
        quality = max(0.0, min(1.0, float(data["quality"])))
    except (KeyError, TypeError, ValueError):
        quality = None      # not rated: unknown, never a reason to reject
    return {
        "description": str(data.get("description") or "")[:600],
        "score": max(0.0, min(1.0, score)),
        "quality": quality,
        "has_text_or_watermark": bool(data.get("has_text_or_watermark")),
        "is_talking_head": bool(data.get("is_talking_head")),
    }


# One line describing the whole video (who, what, when, where), set once per
# job from the director's story brief and shown with every judgement.
_STORY = {"line": ""}


def set_story(brief: Optional[dict]) -> None:
    """Give the judge the whole-story brief; None or {} clears it."""
    b = brief or {}
    cast = [c.get("name") for c in (b.get("cast") or []) if c.get("name")]
    people = cast or list(b.get("people") or [])
    parts = [b.get("summary") or b.get("event") or "",
             f"people: {', '.join(people[:5])}" if people else "",
             f"places: {', '.join((b.get('places') or [])[:4])}" if b.get("places") else "",
             f"year: {b.get('year')}" if b.get("year") else "",
             f"kind: {b.get('kind')}" if b.get("kind") else ""]
    _STORY["line"] = " | ".join(p for p in parts if p)[:500]


def judge(path: str, intent: str, context: str = "", event: bool = False) -> Optional[dict]:
    """
    Verdict for one candidate file, or None when no model could be reached.

    None means "unknown", not "bad": the caller keeps its pre-vision behaviour
    rather than rejecting every clip because an API is down. `event`: the beat
    belongs to a news/weather/disaster story, so the footage must be of that
    specific event and place, not the same kind of thing elsewhere.
    """
    if not enabled() or not path or not os.path.exists(path):
        return None
    key = f"{_fingerprint(path)}|{int(event)}|{intent}|{_STORY['line'][:80]}"
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]

    frames = sample_frames(path, config.VISION_FRAMES)
    if not frames:
        _fail("ffmpeg", f"no frames from {os.path.basename(path)}")
        with _LOCK:
            _UNJUDGED["n"] += 1
        return None

    content = [{"type": "text", "text":
                (f"STORY: {_STORY['line']}\n" if _STORY["line"] else "")
                + f"INTENT: {intent}\nNARRATION: {context}\n"
                f"These are {len(frames)} frames from the candidate."}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{f}"}} for f in frames]
    messages = [{"role": "system", "content": _SYSTEM + (_EVENT_RULE if event else "")},
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
        else:
            _UNJUDGED["n"] += 1
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
    quality = verdict.get("quality")
    if quality is not None and quality < config.VISION_MIN_QUALITY:
        return False
    return verdict["score"] >= config.VISION_MIN_SCORE


def appeal(relevance: Optional[float], quality: Optional[float]) -> float:
    """
    How strongly a clip that already passed would open or carry a beat.

    Relevance leads - the right subject in fair footage beats a gorgeous wrong
    one - and quality breaks near-ties. Unrated quality counts as middling.
    """
    return (relevance or 0.0) + 0.5 * (0.5 if quality is None else quality)


_PICK_SYSTEM = (
    "You pick B-roll for one line of a documentary narration. You are shown a "
    "numbered grid of thumbnails taken across one YouTube video (numbers in the "
    "top-left of each tile). Choose the single tile that best SHOWS the intent. "
    "Never choose a tile showing a presenter talking to camera, a title card, "
    "on-screen text, a graphic, a map or a logo unless the intent asks for it.\n"
    "Scoring: 0.9-1.0 the tile clearly shows the intended subject; 0.7-0.89 is "
    "consistent with every person, place and era the intent names; below 0.7 nothing "
    "in the grid really fits. A tile from a different named place, person or era "
    "than the intent's is never a match, however well it fits the mood.\n"
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
            {"type": "text", "text": (f"STORY: {_STORY['line']}\n" if _STORY["line"] else "")
             + f"INTENT: {intent}\nNARRATION: {context}\n"
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
