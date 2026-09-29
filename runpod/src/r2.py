"""
Cloudflare R2 for finished videos (S3 API, SigV4, no SDK).

Lovable storage capped each file at 2 GB (a 23-minute render was squeezed
to fit, and one upload failed outright) and bills every download; R2 has no
egress fees and a 5 GB single-PUT limit. The final video goes here first and
the app plays it from the bucket's public address - each object's name ends
in a random token, so links are unguessable - with Lovable storage as the
fallback when R2 is not configured or refuses.

Configured by R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_BUCKET and R2_PUBLIC_BASE (the bucket's r2.dev or custom domain).
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Optional

import requests

from . import config

MAX_SINGLE_PUT = 4_900 * 1024 * 1024        # R2 accepts up to 5 GiB in one PUT


def enabled() -> bool:
    return bool(config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_SECRET_ACCESS_KEY
                and config.R2_BUCKET and config.R2_PUBLIC_BASE)


def _endpoint() -> str:
    return f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _auth_headers(method: str, key: str, headers: dict, payload_hash: str,
                  now: Optional[datetime.datetime] = None) -> dict:
    """SigV4 headers for one request to the bucket (region "auto", service s3)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    host = urllib.parse.urlparse(_endpoint()).netloc
    path = "/" + urllib.parse.quote(f"{config.R2_BUCKET}/{key}", safe="/-_.~")
    signed = {k.lower(): str(v).strip() for k, v in headers.items()}
    signed.update({"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date})
    names = sorted(signed)
    canonical = "\n".join([method, path, "", "".join(f"{n}:{signed[n]}\n" for n in names),
                           ";".join(names), payload_hash])
    scope = f"{day}/auto/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    k = _sign(("AWS4" + config.R2_SECRET_ACCESS_KEY).encode("utf-8"), day)
    for part in ("auto", "s3", "aws4_request"):
        k = _sign(k, part)
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    out = {n: signed[n] for n in names if n != "host"}
    out["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={config.R2_ACCESS_KEY_ID}/{scope}, "
                            f"SignedHeaders={';'.join(names)}, Signature={sig}")
    return out


def public_url(key: str) -> str:
    return config.R2_PUBLIC_BASE.rstrip("/") + "/" + urllib.parse.quote(key, safe="/-_.~")


def upload(path: str, key: str, content_type: str = "video/mp4", deadline: float = 0.0) -> str:
    """PUT a local file to the bucket and return its public URL. Retries
    transient failures (network, 5xx, 429) until `deadline`."""
    size = os.path.getsize(path)
    if size > MAX_SINGLE_PUT:
        raise RuntimeError(f"{size / 1e9:.1f} GB is over R2's single-upload limit")
    deadline = deadline or time.time() + 600
    attempt, last = 0, None
    while True:
        attempt += 1
        try:
            headers = _auth_headers("PUT", key, {"content-type": content_type, "content-length": str(size)},
                                    "UNSIGNED-PAYLOAD")
            with open(path, "rb") as fh:
                r = requests.put(f"{_endpoint()}/{config.R2_BUCKET}/{urllib.parse.quote(key, safe='/-_.~')}",
                                 data=fh, headers=headers, timeout=(20, 1800))
            if r.status_code in (200, 201):
                return public_url(key)
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
        if time.time() + 5 * attempt > deadline:
            break
        time.sleep(min(30, 5 * attempt))
    raise RuntimeError(f"R2 upload failed after {attempt} attempt(s): {last}")


def delete(key: str) -> bool:
    headers = _auth_headers("DELETE", key, {}, hashlib.sha256(b"").hexdigest())
    r = requests.delete(f"{_endpoint()}/{config.R2_BUCKET}/{urllib.parse.quote(key, safe='/-_.~')}",
                        headers=headers, timeout=60)
    return r.status_code in (200, 204)
