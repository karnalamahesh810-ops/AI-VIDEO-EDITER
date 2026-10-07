"""
Where the AI presenter style's paid calls go: one small interface, so a second
provider (Algrow's REST API, HeyGen direct, fal) can be added without
touching the pipeline.

    Provider.submit_video(VideoRequest) -> VideoJob        async: returns at once
    Provider.poll_video(VideoJob)       -> VideoResult     status, cost, links
    Provider.download_video(job, result, path)             the finished file
    Provider.image(ImageRequest)        -> ImageResult     a still (bytes) and its cost
    Provider.chat(model, messages, ...) -> ChatResult      text (JSON) and its cost

OpenRouter is the only one wired (the owner, 2026-10-07: no Kie anywhere,
OpenRouter only): /api/v1/videos for the presenter (heygen/avatar-iv: one
picture + our audio window) and the image-to-video b-roll, chat completions
with image output for the stills, chat completions for the planner and the
checks. Its key comes from the worker's existing configuration - the
director's or vision's OpenRouter key, or OPENROUTER_API_KEY - and is never
printed or logged. Every answer's usage.cost is the money counted.

Gotchas measured on the prototype (2026-10-07): an audio reference must be an
https link ("Only HTTPS URLs are allowed" for a data: URL), a picture may be a
data: URL or a link; Avatar IV clips come back at 25 fps, as long as the audio.
"""
from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .. import config

TERMINAL = ("completed", "failed", "cancelled", "expired")


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int = 0, retryable: bool = False, billed: bool = False):
        super().__init__(message)
        self.status, self.retryable, self.billed = status, retryable, billed


@dataclass
class VideoRequest:
    model: str
    prompt: str = ""
    resolution: str = ""
    aspect_ratio: str = "16:9"
    duration: Optional[int] = None
    first_frame: str = ""                     # i2v: the start picture (https link or data: URL)
    images: List[str] = field(default_factory=list)   # input references (avatar: the presenter framing)
    audio_url: str = ""                       # avatar: the voice window, https only
    generate_audio: Optional[bool] = None
    options: Dict[str, Any] = field(default_factory=dict)   # provider passthrough ({"heygen": {...}})
    seed: Optional[int] = None

    def body(self) -> Dict[str, Any]:
        b: Dict[str, Any] = {"model": self.model}
        if self.prompt:
            b["prompt"] = self.prompt
        if self.resolution:
            b["resolution"] = self.resolution
        if self.aspect_ratio:
            b["aspect_ratio"] = self.aspect_ratio
        if self.duration:
            b["duration"] = int(self.duration)
        refs = [{"type": "image_url", "image_url": {"url": u}} for u in self.images if u]
        if self.audio_url:
            refs.append({"type": "audio_url", "audio_url": {"url": self.audio_url}})
        if refs:
            b["input_references"] = refs
        if self.first_frame:
            b["frame_images"] = [{"type": "image_url", "frame_type": "first_frame",
                                  "image_url": {"url": self.first_frame}}]
        if self.generate_audio is not None:
            b["generate_audio"] = bool(self.generate_audio)
        if self.options:
            b["provider"] = {"options": self.options}
        if self.seed is not None:
            b["seed"] = int(self.seed)
        return b


@dataclass
class VideoJob:
    id: str
    model: str
    submitted: float
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    status: str
    cost: Optional[float] = None
    urls: List[str] = field(default_factory=list)
    error: str = ""
    seconds: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageRequest:
    model: str
    prompt: str
    size: str = "2K"
    aspect_ratio: str = "16:9"
    references: List[str] = field(default_factory=list)   # https links or data: URLs


@dataclass
class ImageResult:
    data: bytes
    ext: str
    cost: Optional[float]
    model: str
    seconds: float
    text: str = ""


@dataclass
class ChatResult:
    text: str
    cost: Optional[float]
    model: str
    seconds: float
    raw: Dict[str, Any] = field(default_factory=dict)


class Provider:
    """The interface. Subclasses implement the calls; wait_video is shared."""
    name = "base"

    def available(self) -> bool:
        return False

    def submit_video(self, req: VideoRequest) -> VideoJob:
        raise NotImplementedError

    def poll_video(self, job: VideoJob) -> VideoResult:
        raise NotImplementedError

    def download_video(self, job: VideoJob, result: VideoResult, out_path: str) -> str:
        raise NotImplementedError

    def image(self, req: ImageRequest) -> ImageResult:
        raise NotImplementedError

    def chat(self, model: str, messages: List[dict], *, json_mode: bool = True, max_tokens: int = 4000,
             reasoning_effort: str = "", timeout: float = 180.0) -> ChatResult:
        raise NotImplementedError

    def wait_video(self, job: VideoJob, *, timeout: float = 900.0, poll: float = 10.0,
                   on_status: Optional[Callable[[str], None]] = None, sleep=time.sleep) -> VideoResult:
        """Poll until the job is done (or `timeout`): a transient poll error is retried, never fatal."""
        end = time.time() + timeout
        last, errors = "", 0
        while True:
            try:
                res = self.poll_video(job)
                errors = 0
            except ProviderError as e:
                errors += 1
                if not e.retryable or errors > 6:
                    raise
                res = VideoResult(status=last or "pending")
            if res.status != last and on_status:
                on_status(res.status)
            last = res.status
            if res.status in TERMINAL:
                res.seconds = round(time.time() - job.submitted, 1)
                return res
            if time.time() > end:
                raise ProviderError(f"{job.model} job still {last or 'pending'} after {int(timeout)} s", retryable=True)
            sleep(poll)


def _data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def data_url_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".wav": "audio/wav", ".mp3": "audio/mpeg"}.get(ext, "image/jpeg")
    with open(path, "rb") as fh:
        return _data_url(fh.read(), mime)


def openrouter_key() -> str:
    """The worker's OpenRouter key: OPENROUTER_API_KEY, else the director's, vision's or images' when they are OpenRouter."""
    own = os.getenv("OPENROUTER_API_KEY", "").strip()
    if own:
        return own
    for base, key in ((config.DIRECTOR_API_BASE, config.DIRECTOR_API_KEY), (config.VISION_API_BASE, config.VISION_API_KEY),
                      (config.IMAGE_API_BASE, config.IMAGE_API_KEY)):
        if key and "openrouter.ai" in str(base or ""):
            return key
    return ""


def _err_text(r: requests.Response) -> str:
    try:
        body = r.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:400]
        return str(err or body)[:400]
    except ValueError:
        return (r.text or "")[:400]


class OpenRouter(Provider):
    name = "openrouter"

    def __init__(self, key: str = "", base: str = ""):
        self._key = key or openrouter_key()
        self.base = (base or config.OPENROUTER_API_BASE).rstrip("/")
        self.session = requests.Session()
        # Every pool of the generator (presenter, clips, stills, checks) shares this session: room for all.
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=48)
        self.session.mount("https://", adapter)

    def available(self) -> bool:
        return bool(self._key)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                "HTTP-Referer": "https://thumbgenius.app", "X-Title": "ThumbGenius AI presenter"}

    def _post(self, path: str, body: dict, timeout: float) -> requests.Response:
        try:
            return self.session.post(f"{self.base}{path}", headers=self._headers(), json=body, timeout=timeout)
        except requests.ConnectionError as e:
            raise ProviderError(f"connection failed: {type(e).__name__}", retryable=True) from e
        except requests.Timeout as e:
            # The request may have been accepted: never retried blindly (a paid job could run twice).
            raise ProviderError(f"timed out after {int(timeout)} s", retryable=False) from e

    @staticmethod
    def _check(r: requests.Response, what: str) -> dict:
        if r.status_code in (200, 201, 202):
            try:
                body = r.json()
            except ValueError as e:
                raise ProviderError(f"{what}: answer is not JSON", r.status_code, retryable=True) from e
            if isinstance(body, dict) and body.get("error") and not body.get("choices") and not body.get("id"):
                raise ProviderError(f"{what}: {str(body.get('error'))[:300]}", r.status_code, retryable=False)
            return body if isinstance(body, dict) else {}
        retry = r.status_code in (408, 429, 500, 502, 503, 504)
        raise ProviderError(f"{what}: HTTP {r.status_code}: {_err_text(r)}", r.status_code, retryable=retry)

    # -------------------------------------------------------------- video
    def submit_video(self, req: VideoRequest) -> VideoJob:
        if not self._key:
            raise ProviderError("no OpenRouter key configured")
        attempt = 0
        while True:
            attempt += 1
            try:
                r = self._post("/videos", req.body(), timeout=120)
                body = self._check(r, f"submit {req.model}")
                break
            except ProviderError as e:
                if not e.retryable or attempt >= 3:
                    raise
                time.sleep(4 * attempt)
        jid = str(body.get("id") or "")
        if not jid:
            raise ProviderError(f"submit {req.model}: no job id in the answer")
        return VideoJob(id=jid, model=req.model, submitted=time.time(),
                        raw={k: body.get(k) for k in ("id", "generation_id", "status")})

    def poll_video(self, job: VideoJob) -> VideoResult:
        try:
            r = self.session.get(f"{self.base}/videos/{job.id}", headers=self._headers(), timeout=60)
        except requests.RequestException as e:
            raise ProviderError(f"poll: {type(e).__name__}", retryable=True) from e
        body = self._check(r, f"poll {job.model}")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        cost = usage.get("cost")
        try:
            cost = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost = None
        return VideoResult(status=str(body.get("status") or "pending"), cost=cost,
                           urls=[u for u in body.get("unsigned_urls") or [] if isinstance(u, str)],
                           error=str(body.get("error") or "")[:400],
                           raw={k: body.get(k) for k in ("id", "generation_id", "status")})

    def download_video(self, job: VideoJob, result: VideoResult, out_path: str) -> str:
        last = ""
        for attempt in range(3):
            try:
                r = self.session.get(f"{self.base}/videos/{job.id}/content", params={"index": 0},
                                     headers=self._headers(), timeout=300)
                if r.status_code == 200 and len(r.content) > 4000:
                    with open(out_path, "wb") as fh:
                        fh.write(r.content)
                    return out_path
                last = f"HTTP {r.status_code}"
                for url in result.urls:
                    hdrs = self._headers() if "openrouter.ai" in url else None
                    r2 = self.session.get(url, headers=hdrs, timeout=300)
                    if r2.status_code == 200 and len(r2.content) > 4000:
                        with open(out_path, "wb") as fh:
                            fh.write(r2.content)
                        return out_path
                    last = f"link HTTP {r2.status_code}"
            except requests.RequestException as e:
                last = type(e).__name__
            time.sleep(3 * (attempt + 1))
        raise ProviderError(f"download {job.model}: {last}", retryable=True, billed=True)

    # -------------------------------------------------------------- stills
    def image(self, req: ImageRequest) -> ImageResult:
        if not self._key:
            raise ProviderError("no OpenRouter key configured")
        content: List[dict] = [{"type": "text", "text": req.prompt}]
        for ref in req.references:
            content.append({"type": "image_url", "image_url": {"url": ref}})
        body = {"model": req.model, "messages": [{"role": "user", "content": content}],
                "modalities": ["image", "text"], "stream": False, "usage": {"include": True},
                "image_config": {k: v for k, v in (("aspect_ratio", req.aspect_ratio), ("image_size", req.size)) if v}}
        t0 = time.time()
        r = self._post("/chat/completions", body, timeout=300)
        data = self._check(r, f"image {req.model}")
        cost = (data.get("usage") or {}).get("cost") if isinstance(data.get("usage"), dict) else None
        try:
            cost = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost = None
        choice = (data.get("choices") or [{}])[0] or {}
        msg = choice.get("message") or {}
        for part in msg.get("images") or []:
            url = ((part or {}).get("image_url") or {}).get("url") if isinstance(part, dict) else None
            if not url:
                continue
            m = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", url, re.S)
            if m:
                raw = base64.b64decode(m.group(3))
                ext = {"image/png": ".png", "image/webp": ".webp"}.get(m.group(1) or "", ".jpg")
            else:
                g = self.session.get(url, timeout=120)
                if g.status_code != 200:
                    continue
                raw, ext = g.content, os.path.splitext(url.split("?")[0])[1] or ".png"
            if len(raw) > 2000:
                return ImageResult(data=raw, ext=ext, cost=cost, model=req.model, seconds=round(time.time() - t0, 1),
                                   text=str(msg.get("content") or "")[:200])
        why = f"finish={choice.get('finish_reason')}/{choice.get('native_finish_reason')}"
        raise ProviderError(f"image {req.model}: no picture ({why}; {str(msg.get('content') or '')[:160]})",
                            retryable=True, billed=cost is not None and cost > 0)

    # -------------------------------------------------------------- text
    def chat(self, model: str, messages: List[dict], *, json_mode: bool = True, max_tokens: int = 4000,
             reasoning_effort: str = "", timeout: float = 180.0) -> ChatResult:
        if not self._key:
            raise ProviderError("no OpenRouter key configured")
        body: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": int(max_tokens),
                                "usage": {"include": True}, "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        t0 = time.time()
        r = self._post("/chat/completions", body, timeout=timeout)
        data = self._check(r, f"chat {model}")
        cost = (data.get("usage") or {}).get("cost") if isinstance(data.get("usage"), dict) else None
        try:
            cost = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost = None
        msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        text = msg.get("content") or ""
        if isinstance(text, list):
            text = "".join(str(p.get("text") or "") for p in text if isinstance(p, dict))
        return ChatResult(text=str(text), cost=cost, model=model, seconds=round(time.time() - t0, 1),
                          raw={"usage": data.get("usage")})


class AlgrowREST(Provider):
    """
    A slot for Algrow's REST API (not wired into the worker yet). To add it:
    implement submit_video / poll_video / download_video against its
    generate_video job endpoints (submit returns a job id; poll until it is
    done; the result carries a file link), image() against its image
    generation, read its key from ALGROW_API_KEY, and map its credits to USD
    for the budget guard (credits_used x the plan's $/credit). Select it with
    PRESENTER_PROVIDER=algrow. Until then it reports itself unavailable and the
    pipeline stays on OpenRouter.
    """
    name = "algrow"

    def available(self) -> bool:
        return False


_PROVIDERS = {"openrouter": OpenRouter, "algrow": AlgrowREST}


def get(name: str = "") -> Provider:
    """The configured provider (PRESENTER_PROVIDER, default openrouter); OpenRouter when that one is not available."""
    wanted = (name or os.getenv("PRESENTER_PROVIDER", "openrouter")).strip().lower()
    cls = _PROVIDERS.get(wanted, OpenRouter)
    prov = cls()
    if not prov.available() and cls is not OpenRouter:
        print(f"[presenter] provider '{wanted}' is not available; using OpenRouter", flush=True)
        prov = OpenRouter()
    return prov


def names() -> Tuple[str, ...]:
    return tuple(_PROVIDERS)
