"""
Avatarity (https://avatarity.dev/docs) - the owner's plan provider for AI clips and pictures (2026-10-28):
Starter plan = 2,000 Veo 3.1 Lite clips (~8 s each) and 5,000 Nano Banana pictures a month, 4 renders at a time.

    client()                     the process-wide client (None without AVATARITY_API_KEY)
    Avatarity.image(...)         one picture (sync, or the task polled) -> ImageOut(data, url, ...)
    Avatarity.video(...)         one ~8 s clip, start frame optional -> VideoOut(path, url, task_id, ...)
    Avatarity.upscale(task_id)   a finished 720p Veo clip to 1080p (1 unit)
    Avatarity.usage()            the plan's allowances {veo: {granted, used, reserved, remaining}, images: {...}}
    Provider                     the presenter-provider face (src/presenter/providers.py) AI fill speaks to

Units: a 720p clip is 1 Veo unit, a native 1080p clip 2, an upscale of a finished clip 1; every picture is 1
image. Failed tasks are not counted by Avatarity (their allowance comes back). The ledger here counts what this
process asked for and got, per video (`ledger()`), beside the plan's own numbers from /usage.

Errors (branch on the code, never the message):
  CONCURRENCY_LIMIT 429       never more than AVATARITY_CONCURRENCY (4) in flight here; a 429 waits and retries
  RATE_LIMIT_EXCEEDED 429     wait X-RateLimit-Reset seconds, retry
  IDEMPOTENT_OPERATION_IN_FLIGHT 409 / 5xx / network    retry with the same Idempotency-Key
  ALLOWANCE_EXHAUSTED / SUBSCRIPTION_REQUIRED / any 402  AllowanceError: the caller falls back to OpenRouter
  CONTENT_POLICY_VIOLATION    PolicyError: the caller rewrites the prompt once
  RENDER_TIMEOUT / INFERENCE_FAILED / UPSCALE_FAILED (task)  retried (a new key)
The key is never printed or put in an error.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

BASE = "https://avatarity.dev/v1"
VIDEO_MODELS = ("veo-3.1-lite",)
IMAGE_MODELS = ("nano-banana-pro", "nano-banana-2.1", "nano-banana-2")
PREFIX = "avatarity/"
CLIP_SECONDS = 8.0
RETRY_TASK_CODES = {"RENDER_TIMEOUT", "INFERENCE_FAILED", "UPSCALE_FAILED"}
ALLOWANCE_CODES = {"ALLOWANCE_EXHAUSTED", "SUBSCRIPTION_REQUIRED", "ALLOWANCE_NOT_ACTIVE", "RENEWAL_PAYMENT_PENDING",
                   "PAYMENT_OVERDUE", "PAYMENT_DISPUTED"}
# Appended to every prompt (the owner's test picture came back as a polaroid with a caption and a made-up date).
NO_TEXT = ("No text, captions, subtitles, logos, watermarks, signs with words, dates, timestamps, frames, borders, "
           "polaroid edges or letterboxing: one clean full-bleed photographic image.")


class AvatarityError(RuntimeError):
    def __init__(self, message: str, code: str = "", status: int = 0, retryable: bool = False):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable


class AllowanceError(AvatarityError):
    """The plan cannot pay for this (allowance used up, no plan, payment due): fall back to OpenRouter."""


class PolicyError(AvatarityError):
    """CONTENT_POLICY_VIOLATION: rewrite the prompt once."""


@dataclass
class ImageOut:
    data: bytes
    url: str
    model: str
    seconds: float
    task_id: str = ""
    ext: str = ".png"


@dataclass
class VideoOut:
    path: str
    url: str
    task_id: str
    model: str
    resolution: str
    seconds: float
    units: int = 1


@dataclass
class Ledger:
    video_units: int = 0
    clips: int = 0
    upscales: int = 0
    images: int = 0
    failed: int = 0
    policy: int = 0
    retried: int = 0
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"videoUnits": self.video_units, "clips": self.clips, "upscales": self.upscales,
                "images": self.images, "failed": self.failed, "policyRewrites": self.policy, "retried": self.retried}


def key() -> str:
    return (os.getenv("AVATARITY_API_KEY") or "").strip()


def configured() -> bool:
    return bool(key())


def is_model(model: str) -> bool:
    return str(model or "").startswith(PREFIX) or str(model or "") in VIDEO_MODELS + IMAGE_MODELS


def bare(model: str) -> str:
    m = str(model or "")
    return m[len(PREFIX):] if m.startswith(PREFIX) else m


def with_rules(prompt: str, limit: int = 1200) -> str:
    """The prompt with the no-text rule on the end, cut to the API's 1,200 characters (the rule always kept)."""
    p = " ".join(str(prompt or "").split())
    if NO_TEXT.lower()[:40] in p.lower():
        return p[:limit]
    room = limit - len(NO_TEXT) - 1
    return (p[:room].rstrip() + " " + NO_TEXT).strip()


def _code(r: requests.Response) -> str:
    try:
        return str(((r.json() or {}).get("error") or {}).get("code") or "")
    except ValueError:
        return ""


def _msg(r: requests.Response) -> str:
    try:
        e = (r.json() or {}).get("error") or {}
        return f"{e.get('code') or r.status_code}: {str(e.get('message') or '')[:200]}"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


class Avatarity:
    def __init__(self, api_key: str = "", base: str = BASE, concurrency: int = 0, session=None, sleep=time.sleep):
        self._key = api_key or key()
        self.base = base.rstrip("/")
        n = concurrency or int(os.getenv("AVATARITY_CONCURRENCY", "4") or 4)
        self.slots = threading.BoundedSemaphore(max(1, n))
        self.http = session or requests.Session()
        self.sleep = sleep
        self.ledger = Ledger()
        self.lock = threading.Lock()
        self.remaining: Dict[str, Optional[int]] = {"veo": None, "images": None}

    # ------------------------------------------------------------------ http
    def _headers(self, idem: str = "") -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        if idem:
            h["Idempotency-Key"] = idem
        return h

    def _note_remaining(self, r: requests.Response) -> None:
        for hdr, k in (("X-Avatarity-Remaining-Veo", "veo"), ("X-Avatarity-Remaining-Images", "images")):
            v = r.headers.get(hdr)
            if v is not None:
                try:
                    self.remaining[k] = int(float(v))
                except ValueError:
                    pass

    def _post(self, path: str, body: dict, idem: str, timeout: float = 180.0, tries: int = 40) -> requests.Response:
        """POST with the same Idempotency-Key through 429 / 409 / 5xx / network errors; raises the typed error."""
        delay = 4.0
        for attempt in range(tries):
            try:
                r = self.http.post(f"{self.base}{path}", headers=self._headers(idem), json=body, timeout=timeout)
            except requests.RequestException as e:
                if attempt + 1 >= tries:
                    raise AvatarityError(f"network: {type(e).__name__}", retryable=True)
                self.sleep(delay)
                delay = min(60.0, delay * 1.7)
                continue
            self._note_remaining(r)
            if r.status_code in (200, 201, 202):
                return r
            code = _code(r)
            if r.status_code == 429 or r.status_code == 409 or r.status_code >= 500:
                wait = delay
                if code == "RATE_LIMIT_EXCEEDED":
                    try:
                        wait = max(1.0, float(r.headers.get("X-RateLimit-Reset") or delay))
                    except ValueError:
                        wait = delay
                with self.lock:
                    self.ledger.retried += 1
                self.sleep(wait + random.random())
                delay = min(30.0, delay * 1.5)
                continue
            if r.status_code == 402 or code in ALLOWANCE_CODES:
                raise AllowanceError(_msg(r), code=code, status=r.status_code)
            if code == "CONTENT_POLICY_VIOLATION":
                raise PolicyError(_msg(r), code=code, status=r.status_code)
            raise AvatarityError(_msg(r), code=code, status=r.status_code)
        raise AvatarityError(f"{path}: still busy after {tries} tries", code="BUSY", retryable=True)

    def _get(self, path: str, timeout: float = 60.0) -> dict:
        delay = 3.0
        for attempt in range(6):
            try:
                r = self.http.get(f"{self.base}{path}", headers=self._headers(), timeout=timeout)
            except requests.RequestException as e:
                if attempt == 5:
                    raise AvatarityError(f"network: {type(e).__name__}", retryable=True)
                self.sleep(delay)
                delay *= 1.6
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 409) or r.status_code >= 500:
                self.sleep(delay)
                delay *= 1.6
                continue
            raise AvatarityError(_msg(r), code=_code(r), status=r.status_code)
        raise AvatarityError(f"GET {path} kept failing", retryable=True)

    def task(self, task_id: str) -> dict:
        return self._get(f"/tasks/{task_id}")

    def wait(self, task_id: str, timeout: float = 900.0, poll: float = 7.0) -> dict:
        end = time.time() + timeout
        while True:
            t = self.task(task_id)
            st = str(t.get("status") or "")
            if st in ("succeeded", "failed", "cancelled"):
                return t
            if time.time() > end:
                raise AvatarityError(f"task {task_id} still {st} after {int(timeout)} s", code="RENDER_TIMEOUT",
                                     retryable=True)
            self.sleep(poll)

    def _download(self, url: str, path: str = "") -> bytes:
        last = None
        for _ in range(4):
            try:
                r = self.http.get(url, timeout=300)
                if r.status_code == 200 and r.content:
                    if path:
                        with open(path, "wb") as fh:
                            fh.write(r.content)
                    return r.content
                last = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last = type(e).__name__
            self.sleep(3)
        raise AvatarityError(f"download failed ({last})", retryable=True)

    # ------------------------------------------------------------------ calls
    def usage(self) -> Dict[str, Any]:
        u = self._get("/usage")
        al = u.get("allowances") or {}
        for k in ("veo", "images"):
            if isinstance(al.get(k), dict) and al[k].get("remaining") is not None:
                self.remaining[k] = int(al[k]["remaining"])
        return {"plan": ((u.get("plan") or {}).get("name") or ""), "status": u.get("status"),
                "periodEnd": u.get("current_period_end"), "veo": al.get("veo") or {}, "images": al.get("images") or {},
                "concurrency": (u.get("plan") or {}).get("concurrency")}

    def image(self, prompt: str, *, model: str = "nano-banana-pro", size: str = "1376x768", seed: Optional[int] = None,
              references: Optional[List[str]] = None, idem: str = "", rules: bool = True) -> ImageOut:
        """One picture. `references`: up to 4 https links or data URIs (a character's sheet, a place)."""
        m = bare(model) or "nano-banana-pro"
        body: Dict[str, Any] = {"model": m, "prompt": with_rules(prompt) if rules else prompt[:1200], "n": 1,
                                "size": size or "1376x768"}
        refs = [u for u in (references or []) if u][:4]
        if refs:
            body["reference_images"] = refs
        if seed is not None:
            body["seed"] = int(seed)
        idem = idem or "img-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:40]
        t0 = time.time()
        with self.slots:
            r = self._post("/images/generations", body, idem)
            j = r.json()
            urls = [d.get("url") for d in (j.get("data") or []) if isinstance(d, dict) and d.get("url")]
            tid = str(j.get("task_id") or j.get("id") or "")
            if not urls and tid:
                t = self.wait(tid, timeout=600, poll=4)
                if t.get("status") != "succeeded":
                    e = t.get("error") or {}
                    code = str(e.get("code") or "")
                    with self.lock:
                        self.ledger.failed += 1
                    if code == "CONTENT_POLICY_VIOLATION":
                        raise PolicyError(f"{code}: {str(e.get('message') or '')[:160]}", code=code)
                    raise AvatarityError(f"image task {t.get('status')}: {code}", code=code,
                                         retryable=code in RETRY_TASK_CODES)
                urls = list(t.get("image_urls") or [])
        if not urls:
            raise AvatarityError("no image in the answer", retryable=True)
        data = self._download(urls[0])
        ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".webp" if data[8:12] == b"WEBP" else ".png"
        with self.lock:
            self.ledger.images += 1
            self.ledger.rows.append({"kind": "image", "model": m, "task": tid, "s": round(time.time() - t0, 1)})
        return ImageOut(data=data, url=urls[0], model=m, seconds=round(time.time() - t0, 1), task_id=tid, ext=ext)

    def video(self, prompt: str, out_path: str, *, model: str = "veo-3.1-lite", image: str = "",
              resolution: str = "720p", aspect_ratio: str = "16:9", seed: Optional[int] = None, idem: str = "",
              timeout: float = 900.0, rules: bool = True, task_retries: int = 1) -> VideoOut:
        """One ~8 s clip (its native sound is never used: the caller mutes it). `image`: the start frame."""
        m = bare(model) or "veo-3.1-lite"
        res = "1080p" if str(resolution) == "1080p" else "720p"
        body: Dict[str, Any] = {"model": m, "prompt": with_rules(prompt) if rules else prompt[:1200],
                                "aspect_ratio": aspect_ratio, "resolution": res}
        if image:
            body["image"] = image
        if seed is not None:
            body["seed"] = int(seed)
        base_idem = idem or "vid-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:40]
        t0 = time.time()
        last = ""
        for attempt in range(task_retries + 1):
            key_now = base_idem if attempt == 0 else f"{base_idem}-r{attempt}"
            with self.slots:
                r = self._post("/video/generations", body, key_now)
                tid = str(r.json().get("task_id") or r.json().get("id") or "")
                t = self.wait(tid, timeout=timeout)
            if t.get("status") == "succeeded" and t.get("video_url"):
                self._download(t["video_url"], out_path)
                units = 2 if res == "1080p" else 1
                with self.lock:
                    self.ledger.video_units += units
                    self.ledger.clips += 1
                    self.ledger.rows.append({"kind": "clip", "model": m, "res": res, "task": tid,
                                             "s": round(time.time() - t0, 1)})
                return VideoOut(path=out_path, url=t["video_url"], task_id=tid, model=m, resolution=res,
                                seconds=round(time.time() - t0, 1), units=units)
            e = t.get("error") or {}
            code = str(e.get("code") or "")
            last = f"{t.get('status')}: {code} {str(e.get('message') or '')[:120]}"
            with self.lock:
                self.ledger.failed += 1
            if code == "CONTENT_POLICY_VIOLATION":
                raise PolicyError(last, code=code)
            if code not in RETRY_TASK_CODES and code:
                break
            with self.lock:
                self.ledger.retried += 1
        raise AvatarityError(f"clip failed ({last})", retryable=True)

    def upscale(self, source_task_id: str, out_path: str, timeout: float = 900.0) -> VideoOut:
        """A finished 720p Veo clip to 1080p: the same clip, 1 unit."""
        body = {"model": "veo-3.1-lite", "prompt": "upscale", "source_task_id": source_task_id, "resolution": "1080p"}
        t0 = time.time()
        with self.slots:
            r = self._post("/video/generations", body, f"up-{source_task_id}")
            tid = str(r.json().get("task_id") or r.json().get("id") or "")
            t = self.wait(tid, timeout=timeout)
        if t.get("status") != "succeeded" or not t.get("video_url"):
            raise AvatarityError(f"upscale {t.get('status')}: {(t.get('error') or {}).get('code')}", retryable=True)
        self._download(t["video_url"], out_path)
        with self.lock:
            self.ledger.video_units += 1
            self.ledger.upscales += 1
        return VideoOut(path=out_path, url=t["video_url"], task_id=tid, model="veo-3.1-lite", resolution="1080p",
                        seconds=round(time.time() - t0, 1), units=1)


def _size_for(size: str) -> str:
    """AI fill's sizes ("1K", "2K", "") or an Avatarity size as given."""
    s = str(size or "").strip()
    if s in ("1376x768", "1024x1024", "768x1376", "1792x1024", "1024x1792"):
        return s
    return "1792x1024" if s.upper() in ("2K", "4K") else "1376x768"


def provider(fallback=None):
    """The presenter-provider face (src/presenter/providers.py): models named "avatarity/<id>" go to Avatarity,
    every other model (and every chat call: prompts, vision checks) to `fallback` (OpenRouter)."""
    from .presenter import providers as P

    class Routed(P.Provider):
        name = "avatarity+openrouter"

        def __init__(self):
            self.av = client()
            self.fb = fallback if fallback is not None else P.OpenRouter()
            self.jobs: Dict[str, str] = {}

        def available(self) -> bool:
            return bool(self.av) or self.fb.available()

        def _is_av(self, model: str) -> bool:
            return str(model or "").startswith(PREFIX)

        @staticmethod
        def _err(e: AvatarityError):
            # 402 = out of plan allowance: AI fill's _out_of_credit would stop everything, so it is a "model gone"
            # instead (status 404 + "is not available"): the chain moves on to the OpenRouter models.
            if isinstance(e, AllowanceError):
                return P.ProviderError(f"Avatarity allowance is not available ({e.code}): model is not available",
                                       status=404)
            if isinstance(e, PolicyError):
                return P.ProviderError(f"content policy: {e}", status=400, retryable=False)
            return P.ProviderError(str(e), status=e.status or 0, retryable=e.retryable)

        def image(self, req):
            if not self._is_av(req.model):
                return self.fb.image(req)
            if self.av is None:
                raise P.ProviderError("no AVATARITY_API_KEY: model is not available", status=404)
            try:
                out = self.av.image(req.prompt, model=bare(req.model), size=_size_for(req.size),
                                    references=list(req.references or []) or None)
            except AvatarityError as e:
                raise self._err(e)
            return P.ImageResult(data=out.data, ext=out.ext, cost=0.0, model=req.model, seconds=out.seconds)

        def submit_video(self, req):
            if not self._is_av(req.model):
                return self.fb.submit_video(req)
            if self.av is None:
                raise P.ProviderError("no AVATARITY_API_KEY: model is not available", status=404)
            body: Dict[str, Any] = {"model": bare(req.model), "prompt": with_rules(req.prompt),
                                    "aspect_ratio": req.aspect_ratio or "16:9",
                                    "resolution": "1080p" if req.resolution == "1080p" else "720p"}
            if req.first_frame:
                body["image"] = req.first_frame
            if req.seed is not None:
                body["seed"] = int(req.seed)
            idem = "fill-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:40]
            try:
                r = self.av._post("/video/generations", body, idem)
            except AvatarityError as e:
                raise self._err(e)
            tid = str(r.json().get("task_id") or r.json().get("id") or "")
            self.jobs[tid] = body["resolution"]
            return P.VideoJob(id=tid, model=req.model, submitted=time.time(), raw={"avatarity": True})

        def poll_video(self, job):
            if not (job.raw or {}).get("avatarity"):
                return self.fb.poll_video(job)
            try:
                t = self.av.task(job.id)
            except AvatarityError as e:
                raise self._err(e)
            st = str(t.get("status") or "")
            status = {"succeeded": "completed", "failed": "failed", "cancelled": "cancelled"}.get(st, "pending")
            err = t.get("error") or {}
            if status == "completed":
                units = 2 if self.jobs.get(job.id) == "1080p" else 1
                with self.av.lock:
                    self.av.ledger.video_units += units
                    self.av.ledger.clips += 1
            elif status == "failed":
                with self.av.lock:
                    self.av.ledger.failed += 1
            return P.VideoResult(status=status, cost=0.0, urls=[t["video_url"]] if t.get("video_url") else [],
                                 error=f"{err.get('code') or ''} {err.get('message') or ''}".strip(), raw=t)

        def download_video(self, job, result, out_path):
            if not (job.raw or {}).get("avatarity"):
                return self.fb.download_video(job, result, out_path)
            self.av._download(result.urls[0], out_path)
            return out_path

        def chat(self, model, messages, **kw):
            return self.fb.chat(model, messages, **kw)

    return Routed()


_CLIENT: Dict[str, Avatarity] = {}
_CLIENT_LOCK = threading.Lock()


def client() -> Optional[Avatarity]:
    """The process-wide client (one concurrency gate for every caller), None without a key."""
    if not configured():
        return None
    with _CLIENT_LOCK:
        c = _CLIENT.get(key())
        if c is None:
            c = _CLIENT[key()] = Avatarity()
        return c


def reset_ledger() -> None:
    c = _CLIENT.get(key())
    if c is not None:
        with c.lock:
            c.ledger = Ledger()


def ledger() -> Dict[str, Any]:
    c = _CLIENT.get(key())
    return c.ledger.as_dict() if c is not None else {}


def data_uri(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    mime = "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else "image/png" if raw[:4] == b"\x89PNG" else "image/webp"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def new_key(prefix: str = "tg") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


# Our HD upscale for 720p Veo clips (measured 2026-10-28 against Avatarity's own 1080p of the same clip,
# docs/avatarity-2026-10-28.md): light denoise, Lanczos to 1080 lines, two unsharp passes.
HD_FILTER = ("hqdn3d=1:1:3:3,scale=-2:1080:flags=lanczos+accurate_rnd,unsharp=5:5:0.9:5:5:0.0,"
             "unsharp=3:3:0.35:3:3:0,format=yuv420p")


def hd_upscale(path: str, timeout: float = 300.0) -> str:
    """A 720p clip to 1080 lines in place ("cpu"), "" when it is already 1080 or the pass failed (clip kept)."""
    import subprocess
    try:
        h = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=height", "-of", "csv=p=0", path], capture_output=True, text=True,
                               timeout=30).stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    if not h or h >= 1000:
        return ""
    tmp = path + ".hd.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", path, "-an", "-vf", HD_FILTER, "-c:v", "libx264", "-preset",
           "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if p.returncode == 0 and os.path.getsize(tmp) > 10_000:
            os.replace(tmp, path)
            return "cpu"
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        os.remove(tmp)
    except OSError:
        pass
    return ""
