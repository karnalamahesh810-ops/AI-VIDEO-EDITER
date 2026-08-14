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


def patch_project(project_id: str, fields: dict) -> bool:
    """
    Write progress/status straight into public.video_projects.

    This is what removes the need for any intermediate API server: the worker
    reports its own progress into the database with the service-role key, and
    the app just watches the row. Failures here are logged, never fatal — a
    dropped progress ping must not kill a render.
    """
    if not project_id or not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return False
    url = f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/video_projects?id=eq.{project_id}"
    try:
        r = requests.patch(
            url,
            headers={
                "apikey": config.SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=fields,
            timeout=30,
        )
        if r.status_code >= 400:
            print(f"[storage] patch_project {r.status_code}: {r.text[:200]}", flush=True)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[storage] patch_project failed: {e}", flush=True)
        return False


def signed_url(object_path: str, bucket: str = None, expires_in: int = 3600) -> str:
    """
    Sign a private-bucket object so the worker can download it.

    The `video-audio` bucket is private, so uploaded voiceovers are not
    reachable by plain public URL.
    """
    bucket = bucket or config.SUPABASE_BUCKET
    base = config.SUPABASE_URL.rstrip("/")
    r = requests.post(
        f"{base}/storage/v1/object/sign/{bucket}/{object_path.lstrip('/')}",
        headers={
            "apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        },
        json={"expiresIn": expires_in},
        timeout=30,
    )
    r.raise_for_status()
    return base + "/storage/v1" + r.json()["signedURL"]


def resolve_audio(url_or_path: str, bucket: str = "video-audio") -> str:
    """
    Accept either a full URL or a storage object path and return something
    downloadable. Private-bucket objects get signed on the way through.
    """
    if not url_or_path:
        return ""
    if url_or_path.startswith("http"):
        # A public-URL form pointing at a private bucket will 400 on download;
        # re-sign it from the object path instead.
        marker = "/storage/v1/object/public/"
        if marker in url_or_path:
            tail = url_or_path.split(marker, 1)[1]
            b, _, obj = tail.partition("/")
            try:
                return signed_url(obj, bucket=b)
            except Exception:
                return url_or_path
        return url_or_path
    return signed_url(url_or_path, bucket=bucket)


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
