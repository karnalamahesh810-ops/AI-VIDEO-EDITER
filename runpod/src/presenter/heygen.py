"""
HeyGen's own API, for the cheaper presenter model: Avatar III (the owner, 2026-10-25: "let me choose HeyGen Avatar
III or Avatar IV"). OpenRouter sells Avatar IV only, so Avatar III goes straight to HeyGen - and only then: every
other paid call of the presenter (Avatar IV takes, pictures, checks) stays on OpenRouter.

Used only when a job (or its presenter) picks "avatar_iii" AND the worker has HEYGEN_API_KEY. Without the key the
job is made with Avatar IV and says so in its warnings (src/presenter/generate.py, pipeline.py, hybrid.py).

The calls (HeyGen API v3, developers.heygen.com, read 2026-10-25; v1/v2 retire on 2026-11-01):

  POST /v3/assets                    multipart, one field "file" (png/jpeg/mp3/wav, under 32 MB)
                                     -> data {asset_id, url}
  POST /v3/avatars                   {"type": "photo", "name", "file": {"type": "asset_id", "asset_id"}}
                                     -> data.avatar_item.id = the look id ($1.32 a call, once per picture)
  GET  /v3/avatars/looks/{look_id}   status pending | processing | completed | failed, supported_api_engines
  POST /v3/videos                    {"type": "avatar", "avatar_id": look, "audio_url" | "audio_asset_id",
                                      "engine": {"type": "avatar_iii"}, "resolution": "1080p",
                                      "aspect_ratio": "16:9", "fit": "cover"}  -> data {video_id, status}
  GET  /v3/videos/{video_id}         status waiting | pending | processing | completed | failed, video_url
                                     (a signed link that expires: downloaded at once), duration, failure_message

Auth: the "x-api-key" header. The key is never printed or logged.

Money: HeyGen answers no price, so a take is counted at its length x the published rate (Avatar III photo avatar
$0.99 a minute = $0.0165 a second at 720p or 1080p, billed by the second) - tiers.MODELS["heygen/avatar-iii"].
A photo avatar is made once per presenter picture and its look id is kept (on this disk and on R2 under
heygen/looks/<account>/<picture hash>.json), so the next video with that picture pays nothing for it.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from . import tiers
from .providers import Provider, ProviderError, VideoJob, VideoRequest, VideoResult

API_BASE = "https://api.heygen.com"
ENGINE = "avatar_iii"
MODEL = "heygen/avatar-iii"
LOOK_USD = 1.32                      # one photo avatar (help.heygen.com API pricing, 2026-10-19)
LOOK_WAIT_SECONDS = float(os.getenv("HEYGEN_LOOK_WAIT_SECONDS", "600") or 600)
LOOK_POLL_SECONDS = 5.0
_STATUS = {"completed": "completed", "success": "completed", "failed": "failed", "error": "failed"}


def api_key() -> str:
    return os.getenv("HEYGEN_API_KEY", "").strip()


def ready() -> bool:
    """The worker can make Avatar III takes (a HeyGen key is set)."""
    return bool(api_key())


def account_problem(err: BaseException) -> bool:
    """A HeyGen answer no retry can fix for this job: the key, the wallet, or a look Avatar III cannot animate.
    The job then goes on with Avatar IV (src/presenter/generate.py)."""
    if getattr(err, "heygen_account", False):
        return True
    status = int(getattr(err, "status", 0) or 0)
    text = str(err).lower()
    return status in (401, 402, 403) or any(w in text for w in (
        "insufficient", "balance", "quota", "credit", "payment", "unauthorized", "invalid api key", "forbidden",
        "not support"))


def _message(r: requests.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return (r.text or "")[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:300]
        if err:
            return str(err)[:300]
        return str(body.get("message") or body)[:300]
    return str(body)[:300]


class HeyGen(Provider):
    """Avatar III takes on HeyGen's API (submit / poll / download, plus the photo avatar a picture needs first)."""
    name = "heygen"

    def __init__(self, key: str = "", base: str = "", cache_dir: str = "", session: Optional[requests.Session] = None,
                 sleep: Callable[[float], None] = time.sleep, r2_cache: Optional[bool] = None):
        self._key = (key or api_key()).strip()
        self.base = (base or os.getenv("HEYGEN_API_BASE", "") or API_BASE).rstrip("/")
        self.session = session or requests.Session()
        self.sleep = sleep
        self.cache_dir = cache_dir or os.path.join(os.getenv("PRESENTER_CACHE_DIR", "").strip() or "/tmp",
                                                   "heygen_looks")
        self._r2 = r2_cache
        self._lock = threading.Lock()
        self.looks_made = 0

    def available(self) -> bool:
        return bool(self._key)

    # ------------------------------------------------------------------ http
    def _headers(self, json_body: bool = True) -> Dict[str, str]:
        h = {"x-api-key": self._key, "Accept": "application/json"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _call(self, method: str, path: str, what: str, *, body: Optional[dict] = None, files=None,
              timeout: float = 60.0, retries: int = 3) -> Dict[str, Any]:
        """One API call -> its "data" object. 429 / 5xx / a dropped connection are retried (a create call only
        when nothing could have been accepted: a timeout is never retried)."""
        if not self._key:
            raise ProviderError("no HeyGen key configured (HEYGEN_API_KEY)")
        attempt = 0
        while True:
            attempt += 1
            try:
                r = self.session.request(method, f"{self.base}{path}", headers=self._headers(files is None),
                                         json=body if files is None else None, files=files, timeout=timeout)
            except requests.ConnectionError as e:
                err = ProviderError(f"{what}: connection failed ({type(e).__name__})", retryable=True)
            except requests.Timeout as e:
                raise ProviderError(f"{what}: timed out after {int(timeout)} s", retryable=False) from e
            else:
                if r.status_code < 300:
                    try:
                        payload = r.json()
                    except ValueError as e:
                        raise ProviderError(f"{what}: the answer is not JSON", r.status_code, retryable=True) from e
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if isinstance(payload, dict) and payload.get("error") and not data:
                        raise ProviderError(f"{what}: {_message(r)}", r.status_code)
                    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})
                err = ProviderError(f"{what}: HTTP {r.status_code}: {_message(r)}", r.status_code,
                                    retryable=r.status_code in (408, 429, 500, 502, 503, 504))
                if account_problem(err):
                    err.heygen_account = True       # type: ignore[attr-defined]
            if not err.retryable or attempt >= retries:
                raise err
            self.sleep(3.0 * attempt)

    # ------------------------------------------------------------------ assets
    def upload_asset(self, path: str) -> Dict[str, str]:
        """A local picture or sound on HeyGen: {"asset_id", "url"}."""
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp3": "audio/mpeg",
                ".wav": "audio/wav", ".mp4": "video/mp4"}.get(ext, "application/octet-stream")
        with open(path, "rb") as fh:
            data = self._call("POST", "/v3/assets", f"upload {os.path.basename(path)}",
                              files={"file": (os.path.basename(path), fh, mime)}, timeout=180)
        aid = str(data.get("asset_id") or data.get("id") or "")
        if not aid:
            raise ProviderError("upload: no asset id in the answer")
        return {"asset_id": aid, "url": str(data.get("url") or "")}

    # ------------------------------------------------------------------ the photo avatar (once per picture)
    def _account(self) -> str:
        # Looks belong to a HeyGen account: a new key (another account) never reuses the old account's ids.
        return hashlib.sha256(self._key.encode("utf-8")).hexdigest()[:10]

    @staticmethod
    def picture_hash(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:24]

    def _cache_name(self, digest: str) -> str:
        return f"heygen/looks/{self._account()}/{digest}.json"

    def _r2_on(self) -> bool:
        if self._r2 is not None:
            return bool(self._r2)
        try:
            from .. import r2
            return r2.enabled()
        except Exception:  # noqa: BLE001
            return False

    def _read_cache(self, digest: str) -> Optional[Dict[str, Any]]:
        local = os.path.join(self.cache_dir, self._account(), f"{digest}.json")
        try:
            with open(local, encoding="utf-8") as fh:
                got = json.load(fh)
            if got.get("look_id"):
                return got
        except (OSError, ValueError):
            pass
        if self._r2_on():
            try:
                from .. import r2
                raw = r2.get_bytes(self._cache_name(digest), timeout=20)
                got = json.loads(raw.decode("utf-8")) if raw else None
                if isinstance(got, dict) and got.get("look_id"):
                    self._write_local(digest, got)
                    return got
            except Exception:  # noqa: BLE001 - a cache miss
                pass
        return None

    def _write_local(self, digest: str, data: Dict[str, Any]) -> None:
        folder = os.path.join(self.cache_dir, self._account())
        try:
            os.makedirs(folder, exist_ok=True)
            tmp = os.path.join(folder, f"{digest}.json.part")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, os.path.join(folder, f"{digest}.json"))
        except OSError:
            pass

    def _write_cache(self, digest: str, data: Dict[str, Any]) -> None:
        self._write_local(digest, data)
        if self._r2_on():
            try:
                from .. import r2
                r2.upload_bytes(json.dumps(data).encode("utf-8"), self._cache_name(digest),
                                content_type="application/json", deadline=time.time() + 60)
            except Exception as e:  # noqa: BLE001 - kept on this disk only
                print(f"[heygen] look cache not saved on R2: {type(e).__name__}", flush=True)

    def forget_look(self, path: str) -> None:
        """A cached look HeyGen no longer knows (deleted in the dashboard): made again next time."""
        digest = self.picture_hash(path)
        try:
            os.remove(os.path.join(self.cache_dir, self._account(), f"{digest}.json"))
        except OSError:
            pass
        if self._r2_on():
            try:
                from .. import r2
                r2.delete(self._cache_name(digest))
            except Exception:  # noqa: BLE001
                pass

    def cached_look(self, path: str) -> Optional[str]:
        """The look id already made for this exact picture, or None (making one costs LOOK_USD)."""
        got = self._read_cache(self.picture_hash(path))
        return str(got["look_id"]) if got else None

    def ensure_look(self, path: str, name: str = "ThumbGenius presenter") -> Tuple[str, bool]:
        """(look id, made now) for this picture: the cached one, else a new photo avatar (LOOK_USD, billed)."""
        digest = self.picture_hash(path)
        with self._lock:
            got = self._read_cache(digest)
            if got:
                return str(got["look_id"]), False
            asset = self.upload_asset(path)
            data = self._call("POST", "/v3/avatars", "make the photo avatar", timeout=120, retries=1,
                              body={"type": "photo", "name": name[:80],
                                    "file": {"type": "asset_id", "asset_id": asset["asset_id"]}})
            item = data.get("avatar_item") if isinstance(data.get("avatar_item"), dict) else {}
            look = str(item.get("id") or data.get("look_id") or data.get("id") or "")
            if not look:
                raise ProviderError("make the photo avatar: no look id in the answer", billed=True)
            info = self._wait_look(look)
            engines = [str(e) for e in info.get("supported_api_engines") or []]
            if engines and ENGINE not in engines:
                err = ProviderError(f"this picture's photo avatar does not support {ENGINE} (only {engines})",
                                    400, billed=True)
                err.heygen_account = True           # type: ignore[attr-defined]
                raise err
            self.looks_made += 1
            self._write_cache(digest, {"look_id": look, "engines": engines, "made": round(time.time()),
                                       "usd": LOOK_USD})
            return look, True

    def _wait_look(self, look: str) -> Dict[str, Any]:
        end = time.time() + LOOK_WAIT_SECONDS
        while True:
            info = self._call("GET", f"/v3/avatars/looks/{look}", "photo avatar status", timeout=30)
            status = str(info.get("status") or "").lower()
            if status == "completed":
                return info
            if status in ("failed", "training_failed", "moderation_failed"):
                raise ProviderError(f"the photo avatar failed: {str(info.get('error') or info.get('failure_message') or status)[:200]}",
                                    billed=True)
            if time.time() > end:
                raise ProviderError(f"the photo avatar is still {status or 'pending'} after {int(LOOK_WAIT_SECONDS)} s",
                                    retryable=False, billed=True)
            self.sleep(LOOK_POLL_SECONDS)

    # ------------------------------------------------------------------ the take
    def submit_video(self, req: VideoRequest) -> VideoJob:
        opts = (req.options or {}).get("heygen_direct") or {}
        look = str(opts.get("avatar_id") or "")
        if not look:
            raise ProviderError("no photo avatar (look id) for the take")
        body: Dict[str, Any] = {"type": "avatar", "avatar_id": look, "engine": {"type": ENGINE},
                                "resolution": req.resolution if req.resolution in ("720p", "1080p") else "1080p",
                                "aspect_ratio": req.aspect_ratio or "16:9", "fit": "cover"}
        if req.audio_url.startswith("https://"):
            body["audio_url"] = req.audio_url
        elif req.audio_file and os.path.isfile(req.audio_file):
            body["audio_asset_id"] = self.upload_asset(req.audio_file)["asset_id"]
        else:
            raise ProviderError("no voice for the take (neither an https link nor a file)")
        data = self._call("POST", "/v3/videos", f"submit {req.model}", body=body, timeout=120, retries=1)
        vid = str(data.get("video_id") or data.get("id") or "")
        if not vid:
            raise ProviderError(f"submit {req.model}: no video id in the answer")
        return VideoJob(id=vid, model=req.model, submitted=time.time(),
                        raw={"id": vid, "status": data.get("status"), "resolution": body["resolution"]})

    def poll_video(self, job: VideoJob) -> VideoResult:
        try:
            data = self._call("GET", f"/v3/videos/{job.id}", f"poll {job.model}", timeout=30, retries=1)
        except ProviderError as e:
            if e.status in (0, 408, 429, 500, 502, 503, 504):
                e.retryable = True
            raise
        raw = str(data.get("status") or "pending").lower()
        status = _STATUS.get(raw, raw)
        url = str(data.get("video_url") or "")
        seconds = 0.0
        try:
            seconds = float(data.get("duration") or 0.0)
        except (TypeError, ValueError):
            seconds = 0.0
        cost = None
        if status == "completed" and seconds > 0:
            # HeyGen bills the seconds made at the published rate (it answers no price itself).
            cost = round(seconds * tiers.usd_per_second(job.model, str(job.raw.get("resolution") or "1080p")), 6)
        elif status == "failed":
            cost = 0.0
        return VideoResult(status=status, cost=cost, urls=[url] if url else [],
                           error=str(data.get("failure_message") or data.get("failure_code") or "")[:400],
                           raw={"id": job.id, "status": raw, "duration": seconds})

    def download_video(self, job: VideoJob, result: VideoResult, out_path: str) -> str:
        last = "no link"
        urls = list(result.urls)
        for attempt in range(3):
            if not urls:
                try:
                    urls = self.poll_video(job).urls          # a fresh signed link
                except ProviderError as e:
                    last = str(e)[:120]
            for url in urls:
                try:
                    r = self.session.get(url, timeout=300)
                    if r.status_code == 200 and len(r.content) > 4000:
                        with open(out_path, "wb") as fh:
                            fh.write(r.content)
                        return out_path
                    last = f"HTTP {r.status_code}"
                except requests.RequestException as e:
                    last = type(e).__name__
            urls = []
            self.sleep(3.0 * (attempt + 1))
        raise ProviderError(f"download {job.model}: {last}", retryable=True, billed=True)

    def image(self, req):  # pragma: no cover - never routed here
        raise ProviderError("HeyGen is used for Avatar III takes only")

    def chat(self, model, messages, **kw):  # pragma: no cover - never routed here
        raise ProviderError("HeyGen is used for Avatar III takes only")


def model_report(choice: str, model: str, gen: Any = None) -> Dict[str, Any]:
    """meta.presenter.model / meta.presenterHybrid.model: {asked, used, model, provider, usdPerSecond, fallback,
    looksMade} - what the takes were really made with (`gen`: the job's Generator)."""
    used, fallback = model, ""
    if gen is not None and getattr(gen, "heygen_off", ""):
        used, fallback = "heygen/avatar-iv", str(gen.heygen_off)
    elif tiers.presenter_model_id(choice) == tiers.AVATAR_III and model != MODEL:
        fallback = "no HeyGen API key on this worker"
    return {"asked": tiers.presenter_model_id(choice) or tiers.AVATAR_IV,
            "used": tiers.AVATAR_III if used == MODEL else tiers.AVATAR_IV, "model": used,
            "provider": "heygen" if used == MODEL else "openrouter",
            "usdPerSecond": tiers.usd_per_second(used, "1080p"), "fallback": fallback,
            "looksMade": int(getattr(gen, "looks_made", 0) or 0)}


def resolve(choice: str, *, provider: Optional[Provider] = None) -> Tuple[str, Optional[Provider], str]:
    """
    (model id, the HeyGen provider or None, warning) for a presenter model choice ("avatar_iv" / "avatar_iii"):
    Avatar III needs a HeyGen key on the worker; without one the job is made with Avatar IV and the warning says so.
    `provider`: a stand-in for the tests.
    """
    cid = tiers.presenter_model_id(choice) or tiers.AVATAR_IV
    if cid != tiers.AVATAR_III:
        return tiers.PRESENTER_MODELS[tiers.AVATAR_IV]["model"], None, ""
    prov = provider if provider is not None else (HeyGen() if ready() else None)
    if prov is None or not prov.available():
        return (tiers.PRESENTER_MODELS[tiers.AVATAR_IV]["model"], None,
                "Avatar III was chosen for the presenter, but this worker has no HeyGen API key (HEYGEN_API_KEY): "
                "the presenter was made with Avatar IV ($0.05 a second) instead.")
    return MODEL, prov, ""
