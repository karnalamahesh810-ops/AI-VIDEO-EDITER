"""Serve a render's work directory plus a JSON index, for the live preview page.

`python -m http.server` is almost enough, but its autoindex carries no
timestamps, so the preview page cannot tell this run's clips from the hundred
left behind by previous runs in the same directory - which is exactly the
question you open the preview to answer. This adds /index.json with name, size
and mtime so the page can show only what the current run has sourced, newest
first.

    python scripts/preview_server.py out/make [--port 8899]
"""
import argparse
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

MEDIA = (".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0].rstrip("/") == "/index.json":
            return self._index()
        return super().do_GET()

    def _index(self):
        root = self.directory
        items = []
        try:
            for name in os.listdir(root):
                if not name.lower().endswith(MEDIA) or name == "video.mp4":
                    continue
                try:
                    st = os.stat(os.path.join(root, name))
                except OSError:
                    continue
                items.append({"name": name, "size": st.st_size,
                              "mtime": int(st.st_mtime)})
        except OSError:
            pass
        items.sort(key=lambda i: -i["mtime"])
        body = json.dumps(items).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep the console for the pipeline's own output
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--port", type=int, default=8899)
    a = ap.parse_args()
    d = os.path.abspath(a.directory)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port),
                              partial(Handler, directory=d))
    print(f"preview: http://127.0.0.1:{a.port}/preview.html  (serving {d})",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
