"""
Serve the job's downloaded media to headless Chrome over loopback HTTP.

Remotion renders inside a Chrome page loaded from http://localhost, and a
page on an http origin cannot read file:// URLs — Chrome blocks it, and
Remotion rejects a bare filesystem path outright. Both were measured, not
assumed: a raw Windows path and a file:// URI each fail the render, while the
same asset served over loopback renders correctly.

The alternative, copying every asset into Remotion's public/ directory, would
mean duplicating gigabytes per job. Serving the work directory in place costs
nothing and disappears with the job.

Range requests are supported deliberately. OffthreadVideo seeks within a clip,
and Chrome issues a Range request to do it; a server that answers every range
with the whole file (as SimpleHTTPRequestHandler does) makes video playback
either wrong or extremely slow.
"""
import functools
import http.server
import os
import posixpath
import re
import shutil
import socketserver
import threading
import urllib.parse
from typing import Optional
from urllib.request import url2pathname

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static file handler with byte-range support and no request logging."""

    def log_message(self, *args):  # noqa: D102 - one line per asset is noise
        pass

    def translate_path(self, path: str) -> str:
        # SimpleHTTPRequestHandler's own version resolves against the process
        # CWD on some versions; this keeps everything inside `directory`.
        path = urllib.parse.urlparse(path).path
        path = urllib.parse.unquote(path)
        parts = [p for p in posixpath.normpath(path).split("/")
                 if p and p not in (os.curdir, os.pardir)]
        return os.path.join(self.directory, *parts)

    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404, "Not Found")
            return None

        size = os.path.getsize(path)
        ctype = self.guess_type(path)
        rng = _RANGE.match(self.headers.get("Range", "") or "")
        if not rng:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return open(path, "rb")

        start_s, end_s = rng.groups()
        if start_s:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        else:
            # "bytes=-500" means the final 500 bytes.
            start = max(0, size - int(end_s or 0))
            end = size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return _Slice(f, end - start + 1)


class _Slice:
    """A read-limited view of a file, so copyfile stops at the range end."""

    def __init__(self, fh, remaining: int):
        self._fh = fh
        self._remaining = remaining

    def read(self, amount: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        if amount is None or amount < 0:
            amount = self._remaining
        data = self._fh.read(min(amount, self._remaining))
        self._remaining -= len(data)
        return data

    def close(self):
        self._fh.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class AssetServer:
    """
    Loopback file server for one render, used as a context manager.

    `url_for(path)` returns the URL Chrome should fetch for a local file,
    copying it into the served tree first if it lives somewhere else (a
    background track outside the work directory, say, or an asset on another
    Windows drive where a relative path cannot be formed at all).
    """

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._extra = os.path.join(self.root, "_extra")
        self._httpd: Optional[_Server] = None
        self.port = 0

    def __enter__(self) -> "AssetServer":
        handler = functools.partial(_Handler, directory=self.root)
        # Port 0 lets the OS pick a free one; several workers can share a box.
        self._httpd = _Server(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        return False

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url_for(self, local_path: str) -> str:
        absolute = os.path.abspath(local_path)
        try:
            rel = os.path.relpath(absolute, self.root)
            outside = rel.startswith("..")
        except ValueError:
            outside = True  # different drive on Windows
        if outside:
            os.makedirs(self._extra, exist_ok=True)
            dest = os.path.join(self._extra, os.path.basename(absolute))
            if not os.path.exists(dest):
                shutil.copy2(absolute, dest)
            rel = os.path.relpath(dest, self.root)
        quoted = "/".join(urllib.parse.quote(part)
                          for part in rel.replace("\\", "/").split("/"))
        return f"{self.base}/{quoted}"


def is_local(url: str) -> bool:
    """True when this looks like a filesystem path rather than a fetchable URL."""
    if not url:
        return False
    lowered = url.lower()
    if lowered.startswith(("http://", "https://", "data:", "blob:")):
        return False
    # file:// is a path too — Chrome refuses it from an http origin.
    if lowered.startswith("file://"):
        return True
    return True


def localise(doc: dict, server: AssetServer) -> dict:
    """
    Rewrite every local media reference in a timeline to a served URL.

    Mutates and returns the document. Paths that do not exist on disk are left
    alone so the renderer reports a missing asset rather than a 404 from here.
    """
    def fix(url: str) -> str:
        if not is_local(url):
            return url
        if url.lower().startswith("file://"):
            # url2pathname gets this right on both platforms: "/C:/a/b.png"
            # becomes "C:\a\b.png" on Windows and "/tmp/a.mp4" keeps its
            # leading slash on Linux, which naive slicing does not.
            path = url2pathname(urllib.parse.urlparse(url).path)
        else:
            path = url
        return server.url_for(path) if os.path.isfile(path) else url

    for key in ("audio", "bgm"):
        track = doc.get(key) or {}
        if isinstance(track, dict) and track.get("url"):
            track["url"] = fix(track["url"])
    for scene in doc.get("scenes", []):
        media = scene.get("media") or {}
        if media.get("url"):
            media["url"] = fix(media["url"])
    for overlay in doc.get("overlays", []):
        for media in (overlay.get("media") or []):
            if isinstance(media, dict) and media.get("url"):
                media["url"] = fix(media["url"])
    return doc
