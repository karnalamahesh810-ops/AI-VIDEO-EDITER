"""
Cloudflare R2 upload for the GPU tools worker (S3 API, SigV4, no SDK) - a copy of
the lip-sync worker's (lipsync/r2.py, itself tts/r2.py), the same scheme as runpod/src/r2.py, reading the same env names:
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_BASE.
Never logs or returns a secret.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import time
import urllib.parse

import requests

_SAFE = "/-_.~"
IMMUTABLE = "public, max-age=31536000, immutable"


def _env(k: str) -> str:
    return os.environ.get(k, "").strip()


def enabled() -> bool:
    return all(_env(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE"))


def _endpoint() -> str:
    return f"https://{_env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _headers(method: str, key: str, headers: dict, payload_hash: str) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    host = urllib.parse.urlparse(_endpoint()).netloc
    path = "/" + urllib.parse.quote(f"{_env('R2_BUCKET')}/{key}", safe=_SAFE)
    signed = {k.lower(): str(v).strip() for k, v in headers.items()}
    signed.update({"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date})
    names = sorted(signed)
    canonical = "\n".join([method, path, "", "".join(f"{n}:{signed[n]}\n" for n in names), ";".join(names), payload_hash])
    scope = f"{day}/auto/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    k = _sign(("AWS4" + _env("R2_SECRET_ACCESS_KEY")).encode("utf-8"), day)
    for part in ("auto", "s3", "aws4_request"):
        k = _sign(k, part)
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    out = {n: signed[n] for n in names if n != "host"}
    out["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={_env('R2_ACCESS_KEY_ID')}/{scope}, "
                            f"SignedHeaders={';'.join(names)}, Signature={sig}")
    return out


def public_url(key: str) -> str:
    return _env("R2_PUBLIC_BASE").rstrip("/") + "/" + urllib.parse.quote(key, safe=_SAFE)


def upload_file(path: str, key: str, content_type: str, deadline_s: float = 120.0) -> str:
    """PUT a local file, retried on network errors / 5xx / 429; returns its public URL."""
    size = os.path.getsize(path)
    end = time.time() + deadline_s
    attempt, last = 0, ""
    while True:
        attempt += 1
        try:
            hdrs = {"content-type": content_type, "content-length": str(size), "cache-control": IMMUTABLE}
            with open(path, "rb") as f:
                r = requests.put(f"{_endpoint()}/{_env('R2_BUCKET')}/{urllib.parse.quote(key, safe=_SAFE)}",
                                 data=f, headers=_headers("PUT", key, hdrs, "UNSIGNED-PAYLOAD"), timeout=(15, 300))
            if r.status_code in (200, 201):
                return public_url(key)
            last = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            last = type(e).__name__
        if time.time() + 2 * attempt > end:
            break
        time.sleep(min(10, 2 * attempt))
    raise RuntimeError(f"R2 upload failed after {attempt} attempt(s): {last}")


def exists(key: str) -> bool:
    try:
        h = _headers("HEAD", key, {}, hashlib.sha256(b"").hexdigest())
        h["Accept-Encoding"] = "identity"
        r = requests.head(f"{_endpoint()}/{_env('R2_BUCKET')}/{urllib.parse.quote(key, safe=_SAFE)}", headers=h, timeout=20)
        return r.status_code == 200
    except requests.RequestException:
        return False
