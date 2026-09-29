"""The owner: keep a pod up until the video is safe, and get the render to the laptop too."""
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from src import config, podfetch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import pod_job  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Serving(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.port = _free_port()
        self.state = podfetch.start(self.dir, "t0ken", self.port)
        self.base = f"http://127.0.0.1:{self.port}/t0ken"

    def tearDown(self):
        self.state.stop()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()

    def test_status_before_and_after_the_render_is_kept(self):
        code, _h, body = self.get("/status")
        self.assertEqual((code, json.loads(body)["ready"]), (200, False))
        open(os.path.join(self.dir, "final.mp4"), "wb").write(b"0123456789")
        body = json.loads(self.get("/status")[2])
        self.assertEqual((body["ready"], body["size"], body["state"]), (True, 10, "working"))

    def test_the_file_whole_and_by_range(self):
        open(os.path.join(self.dir, "final.mp4"), "wb").write(b"0123456789")
        self.assertEqual(self.get("/final.mp4")[2], b"0123456789")
        code, headers, body = self.get("/final.mp4", {"Range": "bytes=4-"})
        self.assertEqual((code, body, headers["Content-Range"]), (206, b"456789", "bytes 4-9/10"))
        self.assertEqual(self.get("/final.mp4", {"Range": "bytes=2-3"})[2], b"23")

    def test_a_wrong_token_or_path_is_not_found(self):
        for url in (f"http://127.0.0.1:{self.port}/nope/status", self.base + "/../x", self.base + "/other"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(url, timeout=10)
            self.assertEqual(e.exception.code, 404)

    def test_the_laptop_confirms_only_the_full_size(self):
        open(os.path.join(self.dir, "final.mp4"), "wb").write(b"0123456789")
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/fetched?bytes=5")
        self.assertFalse(self.state.laptop_has_it())
        self.assertEqual(self.get("/fetched?bytes=10")[0], 200)
        self.assertTrue(self.state.laptop_has_it())


class StopOnlyWhenSafe(unittest.TestCase):
    def test_a_video_not_saved_but_kept_keeps_the_pod_up(self):
        self.assertEqual(pod_job.after_job(False, True, lambda: True, 5, sleep=lambda s: None), "stay")

    def test_a_saved_video_waits_for_the_laptop_then_stops(self):
        calls = iter([False, False, True])
        waited = []
        got = pod_job.after_job(True, True, lambda: next(calls), 60, sleep=waited.append)
        self.assertEqual((got, len(waited)), ("stop", 2))

    def test_nothing_kept_stops(self):
        self.assertEqual(pod_job.after_job(False, False, None, 5), "stop")
        self.assertEqual(pod_job.after_job(True, False, None, 5), "stop")


class PodWritesTheResultItself(unittest.TestCase):
    """The handler's terminal write moved the row off "rendering"; the broker then refused
    pod_job's own write, and the pod read the video as not safe and stayed up forever."""

    def _run(self, render):
        import handler
        from tests.test_pipeline import build_doc
        doc = build_doc(n=3, seconds=3.0)
        with mock.patch.object(handler, "do_plan", return_value=doc), \
                mock.patch.object(handler, "_require_youtube"), \
                mock.patch.object(handler, "do_render", side_effect=render), \
                mock.patch.object(handler, "publish_media"), \
                mock.patch.object(handler.storage, "patch_project") as patch:
            out = handler.handler({"id": "pod-1", "input": {"action": "build", "project_id": "p1",
                                                            "_caller_writes_result": True}})
        finals = [c for c in patch.call_args_list if (c.args[1] if len(c.args) > 1 else {}).get("status") in ("done", "failed")]
        return out, finals

    def test_no_terminal_write_on_success(self):
        out, finals = self._run(lambda d, inp, work, report, split=False: {
            "video_url": "https://v", "object_path": "p", "bucket": "renders", "duration": 9})
        self.assertTrue(out["ok"])
        self.assertEqual(finals, [])

    def test_no_terminal_write_on_failure(self):
        def boom(*a, **k):
            raise RuntimeError("upload refused")
        out, finals = self._run(boom)
        self.assertFalse(out["ok"])
        self.assertEqual(finals, [])


class KeepTheRender(unittest.TestCase):
    def test_the_finished_video_is_copied_out_of_the_work_directory(self):
        import handler
        src = os.path.join(tempfile.mkdtemp(), "final.mp4")
        open(src, "wb").write(b"video")
        keep = tempfile.mkdtemp()
        with mock.patch.object(config, "RENDER_KEEP_DIR", keep):
            handler._keep_render(src)
        self.assertEqual(open(os.path.join(keep, "final.mp4"), "rb").read(), b"video")
        self.assertFalse(os.path.exists(os.path.join(keep, "final.mp4.part")))

    def test_off_when_not_a_pod(self):
        import handler
        with mock.patch.object(config, "RENDER_KEEP_DIR", ""):
            handler._keep_render(__file__)       # nothing happens, nothing raises


if __name__ == "__main__":
    unittest.main()
