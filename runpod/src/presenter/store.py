"""
Where the AI presenter style keeps what it paid for.

Store: every generated asset goes to Cloudflare R2 the moment it is
downloaded (projects/<id>/presenter/... - jobs/<job>/presenter/... with no
project), under a link-only name, the way the worker keeps scene media
(handler._put_scene_file: public link, never expires). A render that fails
later never loses a paid clip. The provider-facing inputs (voice windows,
start frames: OpenRouter fetches audio only from https links) go under
.../presenter/inputs/ and are deleted when the job ends - only the keys this
job wrote, one by one, never a prefix.

Cache: a paid call's request (model, prompt, settings, the hashes of the
files it sends) names its result. A hit - on this disk (PRESENTER_CACHE_DIR,
default the job's own folder) or in the project's R2 cache folder - returns
the file instead of paying again: a re-run of a failed job, or of one shot,
costs nothing for what was already made.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .. import config, r2


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:24]


class Store:
    def __init__(self, project_id: str = "", job_id: str = "", enabled: Optional[bool] = None):
        base = f"projects/{project_id}" if project_id else f"jobs/{job_id or 'adhoc'}"
        self.prefix = f"{base}/presenter"
        self.enabled = r2.enabled() if enabled is None else bool(enabled)
        self._lock = threading.Lock()
        self.temp_keys: List[str] = []
        self.kept = 0

    def put(self, local: str, name: str, temp: bool = False, content_type: str = "") -> str:
        """The file's public R2 link ("" when R2 is off or the upload failed: the caller decides)."""
        if not self.enabled or not os.path.isfile(local):
            return ""
        folder = "inputs" if temp else "assets"
        key = r2.tokened(f"{self.prefix}/{folder}/{name}")
        ctype = content_type or {".wav": "audio/wav", ".mp3": "audio/mpeg"}.get(
            os.path.splitext(local)[1].lower()) or r2.content_type(local)
        try:
            url = r2.upload(local, key, content_type=ctype, deadline=time.time() + config.R2_MEDIA_UPLOAD_SECONDS,
                            cache_control="" if temp else r2.IMMUTABLE)
        except Exception as e:  # noqa: BLE001 - the asset stays on this disk
            print(f"[presenter] R2 upload of {name} failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return ""
        with self._lock:
            if temp:
                self.temp_keys.append(key)
            else:
                self.kept += 1
        return url

    def put_json(self, data: dict, name: str) -> str:
        if not self.enabled:
            return ""
        try:
            return r2.upload_bytes(json.dumps(data).encode("utf-8"), f"{self.prefix}/{name}",
                                   content_type="application/json", deadline=time.time() + 60)
        except Exception as e:  # noqa: BLE001
            print(f"[presenter] R2 write of {name} failed: {type(e).__name__}", flush=True)
            return ""

    def get_json(self, name: str) -> Optional[dict]:
        if not self.enabled:
            return None
        try:
            raw = r2.get_bytes(f"{self.prefix}/{name}", timeout=20)
            return json.loads(raw.decode("utf-8")) if raw else None
        except Exception:  # noqa: BLE001 - a cache miss
            return None

    def cleanup(self) -> int:
        """Delete the temporary inputs this job uploaded (each key it wrote, nothing else)."""
        with self._lock:
            keys, self.temp_keys = list(self.temp_keys), []
        gone = 0
        for key in keys:
            if not key.startswith(f"{self.prefix}/inputs/"):
                continue
            try:
                gone += 1 if r2.delete(key) else 0
            except Exception:  # noqa: BLE001 - a leftover input is only storage
                pass
        return gone


class Cache:
    def __init__(self, folder: str, store: Optional[Store] = None):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.store = store
        self.hits = 0

    @staticmethod
    def key(payload: Dict[str, Any], files: Optional[List[str]] = None) -> str:
        body = dict(payload)
        body["_files"] = [file_hash(f) for f in files or [] if f and os.path.isfile(f)]
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:32]

    def get(self, key: str, out_path: str) -> Optional[dict]:
        """A cached result copied to out_path ({..meta}), or None."""
        meta_path = os.path.join(self.folder, f"{key}.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                src = os.path.join(self.folder, meta.get("file") or "")
                if os.path.isfile(src) and os.path.getsize(src) > 1000:
                    shutil.copyfile(src, out_path)
                    self.hits += 1
                    return dict(meta, cached="disk")
            except (OSError, ValueError):
                pass
        if self.store is not None:
            meta = self.store.get_json(f"cache/{key}.json")
            if meta and str(meta.get("url") or "").startswith("http"):
                try:
                    r = requests.get(meta["url"], timeout=300)
                    if r.status_code == 200 and len(r.content) > 1000:
                        with open(out_path, "wb") as fh:
                            fh.write(r.content)
                        self.hits += 1
                        return dict(meta, cached="r2")
                except requests.RequestException:
                    pass
        return None

    def put(self, key: str, path: str, meta: Dict[str, Any]) -> None:
        ext = os.path.splitext(path)[1] or ".bin"
        name = f"{key}{ext}"
        try:
            shutil.copyfile(path, os.path.join(self.folder, name))
            with open(os.path.join(self.folder, f"{key}.json"), "w", encoding="utf-8") as fh:
                json.dump(dict(meta, file=name), fh)
        except OSError:
            pass
        if self.store is not None and str(meta.get("url") or "").startswith("http"):
            self.store.put_json(dict(meta), f"cache/{key}.json")
