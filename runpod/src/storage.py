"""Supabase Storage upload + generic file download."""
import os
import mimetypes
import requests

from . import config


class StorageError(RuntimeError):
    pass


def download(url: str, dest_path: str, timeout: int = 180) -> str:
    """Stream any http(s) URL to disk. Returns the local path."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
    return dest_path


def upload_to_supabase(local_path: str, object_path: str, bucket: str = None,
                       upsert: bool = True) -> str:
    """
    Upload a file to Supabase Storage using the service-role key and return its
    public URL. `object_path` is the path *inside* the bucket,
    e.g. "projects/<id>/final.mp4".
    """
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        raise StorageError(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set on the RunPod endpoint"
        )

    bucket = bucket or config.SUPABASE_BUCKET
    base = config.SUPABASE_URL.rstrip("/")
    object_path = object_path.lstrip("/")
    endpoint = f"{base}/storage/v1/object/{bucket}/{object_path}"

    content_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    headers = {
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true" if upsert else "false",
    }

    with open(local_path, "rb") as f:
        resp = requests.post(endpoint, headers=headers, data=f, timeout=900)

    # POST 400s when the object already exists and upsert isn't honoured; retry as PUT.
    if resp.status_code >= 400 and upsert:
        with open(local_path, "rb") as f:
            resp = requests.put(endpoint, headers=headers, data=f, timeout=900)

    if resp.status_code >= 400:
        raise StorageError(
            f"Supabase upload failed ({resp.status_code}): {resp.text[:400]}"
        )

    return f"{base}/storage/v1/object/public/{bucket}/{object_path}"
