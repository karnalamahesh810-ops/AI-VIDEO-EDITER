"""
Hand a pod's finished render straight to the owner's laptop, through RunPod's
HTTP proxy (https://<pod id>-<port>.proxy.runpod.net), before and independent of
the upload to the app.

On 2026-09-28 a 22-minute render was lost at the last step: the app's storage
refused the file, the pod stopped itself, and a stopped pod's disk is wiped.
The owner asked for the video to reach the laptop too, and for the pod to stay
up until the video is safe. This serves one directory's final.mp4 under a
secret token:

    GET /<token>/status     {"state", "error", "ready", "size", "fetched"}
    GET /<token>/final.mp4  the file (Range requests, so a download can resume)
    GET /<token>/fetched?bytes=N   the laptop has all N bytes

Anything else, or a wrong token, is a 404. Standard library only.
"""
import http.server
import json
import os
import threading
import urllib.parse
from typing import Optional

CHUNK = 1024 * 1024


class FetchState:
    """What the pod reports, and whether the laptop has the file."""

    def __init__(self, directory: str, token: str):
        self.directory = directory
        self.token = token
        self.job = {"state": "working", "error": ""}
        self.fetched_bytes = 0
        self.lock = threading.Lock()
        self.server: Optional[http.server.ThreadingHTTPServer] = None

    @property
    def final(self) -> str:
        return os.path.join(self.directory, "final.mp4")

    def size(self) -> int:
        try:
            return os.path.getsize(self.final)
        except OSError:
            return 0

    def set_job(self, state: str, error: str = "") -> None:
        with self.lock:
            self.job = {"state": state, "error": str(error or "")[:500]}

    def laptop_has_it(self) -> bool:
        size = self.size()
        with self.lock:
            return size > 0 and self.fetched_bytes == size

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def _handler(state: FetchState):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "podfetch"

        def log_message(self, fmt, *args):  # noqa: D401 - quiet: the proxy polls often
            return

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - http.server's name
            url = urllib.parse.urlsplit(self.path)
            parts = [p for p in url.path.split("/") if p]
            if len(parts) != 2 or not state.token or parts[0] != state.token:
                self._send(404, b"{}")
                return
            name = parts[1]
            if name == "status":
                size = state.size()
                with state.lock:
                    body = dict(state.job, ready=size > 0, size=size, fetched=state.fetched_bytes)
                self._send(200, json.dumps(body).encode())
            elif name == "final.mp4":
                self._file()
            elif name == "fetched":
                got = urllib.parse.parse_qs(url.query).get("bytes", ["0"])[0]
                size = state.size()
                ok = got.isdigit() and size > 0 and int(got) == size
                if ok:
                    with state.lock:
                        state.fetched_bytes = size
                self._send(200 if ok else 409, json.dumps({"ok": ok, "size": size}).encode())
            else:
                self._send(404, b"{}")

        def _file(self) -> None:
            path = state.final
            try:
                size = os.path.getsize(path)
                fh = open(path, "rb")
            except OSError:
                self._send(404, b"{}")
                return
            with fh:
                start, end = 0, size - 1
                rng = self.headers.get("Range", "")
                if rng.startswith("bytes="):
                    a, _, b = rng[6:].split(",")[0].partition("-")
                    try:
                        if a:
                            start = int(a)
                            end = int(b) if b else size - 1
                        elif b:
                            start = max(0, size - int(b))
                    except ValueError:
                        start, end = 0, size - 1
                    if start >= size or start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    end = min(end, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                length = end - start + 1
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(CHUNK, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

    return Handler


def start(directory: str, token: str, port: int = 8888) -> FetchState:
    """Serve `directory`/final.mp4 under `token` on 0.0.0.0:`port`, in a daemon thread."""
    os.makedirs(directory, exist_ok=True)
    state = FetchState(directory, token)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), _handler(state))
    server.daemon_threads = True
    state.server = server
    threading.Thread(target=server.serve_forever, name="podfetch", daemon=True).start()
    return state
