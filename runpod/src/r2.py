"""
Cloudflare R2 (S3 API, SigV4, no SDK): finished videos, scene media and the
footage library.

Lovable storage capped each file at 2 GB (a 23-minute render was squeezed
to fit, and one upload failed outright) and bills every download; R2 has no
egress fees and a 5 GB single-PUT limit. Two buckets:

* R2_BUCKET (thumbgenius-videos): finished videos and each project's scene
  media, previews and thumbnails. Object names end in a random token
  (`tokened`), so links are unguessable.
* R2_LIBRARY_BUCKET (thumbgenius-library): the footage library - approved
  clips and photos kept for later videos, their thumbnails and CLIP
  embeddings (src/libstore.py).

Both are read through their public r2.dev (or custom) domain. Configured by
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET,
R2_PUBLIC_BASE, R2_LIBRARY_BUCKET and R2_LIBRARY_PUBLIC_BASE. Every helper
takes `bucket`/`base`; left out, they mean the videos bucket.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import mimetypes
import os
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

from . import config

MAX_SINGLE_PUT = 4_900 * 1024 * 1024        # R2 accepts up to 5 GiB in one PUT
# Tokened objects never change under their name: browsers may keep them.
IMMUTABLE = "public, max-age=31536000, immutable"
_SAFE = "/-_.~"


def _creds() -> bool:
    return bool(config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_SECRET_ACCESS_KEY)


def enabled() -> bool:
    """The videos bucket (finished videos, scene media) is configured."""
    return bool(_creds() and config.R2_BUCKET and config.R2_PUBLIC_BASE)


def library_enabled() -> bool:
    """The footage library's own bucket is configured (src/libstore.py)."""
    return bool(_creds() and getattr(config, "R2_LIBRARY_BUCKET", "")
                and getattr(config, "R2_LIBRARY_PUBLIC_BASE", ""))


def _endpoint() -> str:
    return f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _query_string(query: Optional[dict]) -> str:
    """SigV4 canonical query: names and values URI-encoded, sorted by name."""
    if not query:
        return ""
    enc = lambda s: urllib.parse.quote(str(s), safe="-_.~")  # noqa: E731
    return "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(query.items()))


def _auth_headers(method: str, key: str, headers: dict, payload_hash: str,
                  now: Optional[datetime.datetime] = None, bucket: str = "",
                  query: Optional[dict] = None) -> dict:
    """SigV4 headers for one request to a bucket (region "auto", service s3)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    host = urllib.parse.urlparse(_endpoint()).netloc
    path = "/" + urllib.parse.quote(f"{bucket or config.R2_BUCKET}/{key}", safe=_SAFE)
    signed = {k.lower(): str(v).strip() for k, v in headers.items()}
    signed.update({"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date})
    names = sorted(signed)
    canonical = "\n".join([method, path, _query_string(query),
                           "".join(f"{n}:{signed[n]}\n" for n in names),
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


def _object_url(key: str, bucket: str = "") -> str:
    return f"{_endpoint()}/{bucket or config.R2_BUCKET}/{urllib.parse.quote(key, safe=_SAFE)}"


def public_url(key: str, base: str = "") -> str:
    return (base or config.R2_PUBLIC_BASE).rstrip("/") + "/" + urllib.parse.quote(key, safe=_SAFE)


def tokened(key: str) -> str:
    """`key` with a random token before its extension: an unguessable, link-only name."""
    stem, ext = os.path.splitext(key)
    return f"{stem}-{uuid.uuid4().hex[:12]}{ext}"


def content_type(path: str, default: str = "application/octet-stream") -> str:
    ext = os.path.splitext(path or "")[1].lower()
    return {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
            ".json": "application/json"}.get(ext) or mimetypes.guess_type(path or "")[0] or default


def _put(key: str, body, size: int, content_type: str, bucket: str, cache_control: str,
         deadline: float, reopen=None) -> None:
    """One PUT, retried on network errors, 5xx and 429 until `deadline`."""
    attempt, last = 0, None
    while True:
        attempt += 1
        try:
            hdrs = {"content-type": content_type, "content-length": str(size)}
            if cache_control:
                hdrs["cache-control"] = cache_control
            headers = _auth_headers("PUT", key, hdrs, "UNSIGNED-PAYLOAD", bucket=bucket)
            data = reopen() if reopen else body
            try:
                r = requests.put(_object_url(key, bucket), data=data, headers=headers, timeout=(20, 1800))
            finally:
                if reopen and hasattr(data, "close"):
                    data.close()
            if r.status_code in (200, 201):
                return
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
        if time.time() + 5 * attempt > deadline:
            break
        time.sleep(min(30, 5 * attempt))
    raise RuntimeError(f"R2 upload failed after {attempt} attempt(s): {last}")


def upload(path: str, key: str, content_type: str = "video/mp4", deadline: float = 0.0,
           bucket: str = "", base: str = "", cache_control: str = "") -> str:
    """PUT a local file to a bucket and return its public URL. Retries
    transient failures (network, 5xx, 429) until `deadline`."""
    size = os.path.getsize(path)
    if size > MAX_SINGLE_PUT:
        raise RuntimeError(f"{size / 1e9:.1f} GB is over R2's single-upload limit")
    _put(key, None, size, content_type, bucket, cache_control, deadline or time.time() + 600,
         reopen=lambda: open(path, "rb"))
    return public_url(key, base)


def upload_bytes(data: bytes, key: str, content_type: str = "application/json", deadline: float = 0.0,
                 bucket: str = "", base: str = "", cache_control: str = "") -> str:
    """PUT a small in-memory object (a JSON sidecar) and return its public URL."""
    _put(key, data, len(data), content_type, bucket, cache_control, deadline or time.time() + 120)
    return public_url(key, base)


def head(key: str, bucket: str = "") -> Optional[dict]:
    """{"size", "etag", "type"} of an object, None when it does not exist."""
    headers = _auth_headers("HEAD", key, {}, hashlib.sha256(b"").hexdigest(), bucket=bucket)
    # Uncompressed: with gzip allowed Cloudflare drops Content-Length (size 0).
    headers["Accept-Encoding"] = "identity"
    r = requests.head(_object_url(key, bucket), headers=headers, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"R2 HEAD {key}: HTTP {r.status_code}")
    etag = r.headers.get("ETag", "")
    return {"size": int(r.headers.get("Content-Length") or 0),
            "etag": (etag[2:] if etag.startswith("W/") else etag).strip('"'),
            "type": r.headers.get("Content-Type", "")}


def get_bytes(key: str, bucket: str = "", timeout: int = 60) -> Optional[bytes]:
    """An object's bytes through the S3 API (no public domain needed); None when missing."""
    headers = _auth_headers("GET", key, {}, hashlib.sha256(b"").hexdigest(), bucket=bucket)
    r = requests.get(_object_url(key, bucket), headers=headers, timeout=timeout)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"R2 GET {key}: HTTP {r.status_code}")
    return r.content


def list_keys(prefix: str = "", bucket: str = "", limit: int = 10000) -> List[dict]:
    """[{"key", "size"}] under `prefix` (ListObjectsV2, paged)."""
    out: List[dict] = []
    token = ""
    while len(out) < limit:
        query = {"list-type": "2", "prefix": prefix, "max-keys": str(min(1000, limit - len(out)))}
        if token:
            query["continuation-token"] = token
        headers = _auth_headers("GET", "", {}, hashlib.sha256(b"").hexdigest(), bucket=bucket, query=query)
        r = requests.get(f"{_endpoint()}/{bucket or config.R2_BUCKET}/?{_query_string(query)}",
                         headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"R2 list {prefix!r}: HTTP {r.status_code}: {r.text[:200]}")
        root = ET.fromstring(r.content)
        ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
        for c in root.findall(f"{ns}Contents"):
            out.append({"key": c.findtext(f"{ns}Key") or "", "size": int(c.findtext(f"{ns}Size") or 0)})
        token = root.findtext(f"{ns}NextContinuationToken") or ""
        if (root.findtext(f"{ns}IsTruncated") or "").lower() != "true" or not token:
            break
    return out[:limit]


def delete(key: str, bucket: str = "") -> bool:
    headers = _auth_headers("DELETE", key, {}, hashlib.sha256(b"").hexdigest(), bucket=bucket)
    r = requests.delete(_object_url(key, bucket), headers=headers, timeout=60)
    return r.status_code in (200, 204)
