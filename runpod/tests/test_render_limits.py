"""
How long a render may run and what a failed one says (src/render.py):
the time limit follows the frames and the machine (it was a flat 5400 s, which
killed a 29-minute video at 55% on one 16-vCPU worker, 2026-10-03), a hung
render is stopped, and the error is plain words - never the command line,
never a storage error page's raw HTML (2026-10-04).
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from src import config, render

R2_404 = """Error: Received a status code of 404 while downloading file https://pub-abc.r2.dev/projects/15eb/media/s0012-a1b2c3.mp4.
The response body was:
---
<!DOCTYPE html>
<html lang="en"><head><title>404 Not Found</title><style>body{color:#0055DC}</style></head>
<body><svg viewBox="0 0 10 10"><path d="M0 0L10 10" stroke=#0055DC stroke-width=2 /></svg><h1>Object not found</h1>
---
    at readFile (/app/remotion/node_modules/@remotion/renderer/dist/assets/read-file.js:60:15)
"""


class Limits(unittest.TestCase):
    def _on(self, cpus=16, **over):
        vals = {"RENDER_CPUS": cpus, "RENDER_FPS_PER_TAB": 0.45, "RENDER_TIMEOUT_FACTOR": 1.5,
                "RENDER_TIMEOUT_BASE_SECONDS": 600, "RENDER_TIMEOUT_MIN_SECONDS": 1800,
                "RENDER_TIMEOUT_MAX_SECONDS": 14400}
        vals.update(over)
        return mock.patch.multiple(config, **vals)

    def test_the_limit_follows_the_frames(self):
        with self._on():
            short = render.render_timeout(900, 12)             # a 30 s chunk
            chunk = render.render_timeout(5200, 12)            # a tenth of the 29-minute video
            whole = render.render_timeout(30000, 12)           # a 16-minute video on one machine
        self.assertEqual(short, 1800)                          # never under the floor
        self.assertGreater(chunk, short)
        self.assertGreater(whole, 5400)                        # the old flat limit was too short for it
        self.assertGreater(whole, chunk)

    def test_the_29_minute_video_gets_longer_than_it_really_took(self):
        # 52,000 frames at the measured ~7 frames a second is 2 h 04 min; the old 5400 s cut it at 55%.
        with self._on():
            limit = render.render_timeout(52000, 12)
        self.assertGreater(limit, 52000 / 7.0)
        self.assertLessEqual(limit, 14400)

    def test_the_limit_has_an_upper_bound(self):
        with self._on():
            self.assertEqual(render.render_timeout(500000, 12), 14400)
        with self._on(RENDER_TIMEOUT_MAX_SECONDS=7200):
            self.assertEqual(render.render_timeout(500000, 12), 7200)

    def test_the_limit_follows_the_machine(self):
        with self._on(cpus=16):
            small = render.render_timeout(30000, 12)
        with self._on(cpus=32):
            big = render.render_timeout(30000, 24)
        with self._on(cpus=4):
            tiny = render.render_timeout(30000, 12)            # 12 tabs asked for, 4 CPUs to run them
            self.assertEqual(render.frames_per_second(12), 4 * 0.45)
        self.assertLess(big, small)
        self.assertGreater(tiny, small)

    def test_cpus_come_from_the_container_not_the_host(self):
        with mock.patch.object(config, "RENDER_CPUS", 0), mock.patch.object(render.os, "cpu_count", return_value=128), \
                mock.patch.object(render, "_cgroup_cpus", return_value=16.0), \
                mock.patch.object(render.os, "sched_getaffinity", return_value=set(range(128)), create=True):
            self.assertEqual(render.cpus(), 16)
        with mock.patch.object(config, "RENDER_CPUS", 8):
            self.assertEqual(render.cpus(), 8)

    def test_frame_count_is_the_range_or_the_whole_video(self):
        doc = {"fps": 30, "durationInFrames": 3000, "scenes": []}
        self.assertEqual(render.frame_count(doc, (600, 899)), 300)
        self.assertEqual(render.frame_count(doc), 3000)
        doc["brand"] = {"intro": {"kind": "card", "frames": 90}}
        self.assertEqual(render.frame_count(doc), 3090)


class RenderCall(unittest.TestCase):
    DOC = {"fps": 30, "durationInFrames": 52000, "scenes": [], "overlays": []}

    def test_a_render_gets_its_scaled_limit_not_5400(self):
        seen = {}

        def fake_run(argv, **kw):
            seen["timeout"] = kw.get("timeout")
            with open(argv[argv.index("Main") + 1], "wb") as fh:
                fh.write(b"x")
            return mock.Mock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(render.subprocess, "run", fake_run), \
                mock.patch.object(config, "RENDER_CPUS", 16):
            render.render(dict(self.DOC), os.path.join(d, "v.mp4"), concurrency=12)
            whole = seen["timeout"]
            render.render(dict(self.DOC), os.path.join(d, "c.mp4"), concurrency=12, frames=(0, 5199))
            chunk = seen["timeout"]
            render.render(dict(self.DOC), os.path.join(d, "t.mp4"), concurrency=12, timeout=77)
            self.assertEqual(seen["timeout"], 77)              # a caller's own limit still wins
        self.assertEqual(whole, render.render_timeout(52000, 12))
        self.assertGreater(whole, 5400)
        self.assertLess(chunk, whole)

    def test_a_render_out_of_time_says_so_in_plain_words(self):
        def fake_run(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(render.subprocess, "run", fake_run), \
                mock.patch.object(config, "RENDER_CPUS", 16):
            with self.assertRaises(render.RenderTimeout) as cm:
                render.render(dict(self.DOC), os.path.join(d, "v.mp4"), concurrency=12)
        text = str(cm.exception)
        self.assertIn("ran out of time", text)
        self.assertIn("this one machine", text)
        self.assertIn("52000 frames", text)
        self.assertNotIn("--concurrency", text)                # never the command line
        self.assertNotIn("remotion-cli", text)
        self.assertIsInstance(cm.exception, render.RenderError)

    def test_a_failed_render_never_reports_raw_html(self):
        def fake_run(argv, **kw):
            return mock.Mock(returncode=1, stdout="", stderr=R2_404)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(render.subprocess, "run", fake_run):
            with self.assertRaises(render.RenderError) as cm:
                render.render(dict(self.DOC), os.path.join(d, "v.mp4"))
        text = str(cm.exception)
        for junk in ("<path", "<svg", "<html", "DOCTYPE", "#0055DC", "stroke"):
            self.assertNotIn(junk, text)
        self.assertIn("1 file the video needs was not found in storage (404)", text)
        self.assertIn("deleted from storage?", text)
        # The link itself stays: the quality check repairs the scene a render error names.
        self.assertIn("https://pub-abc.r2.dev/projects/15eb/media/s0012-a1b2c3.mp4", text)
        self.assertLess(text.index("not found in storage"), 200)   # said first: the app keeps 800 characters


class PlainError(unittest.TestCase):
    def test_a_page_whose_start_was_cut_off_goes_too(self):
        text = render.plain_error('x\n<path d="M0 0" stroke=#0055DC>\n</svg></body></html>\nError: boom')
        self.assertNotIn("stroke", text)
        self.assertIn("Error: boom", text)
        self.assertIn("error page", text)

    def test_every_status_is_counted_with_its_files(self):
        raw = "\n".join(f"Error: Received a status code of 404 while downloading file https://pub.r2.dev/p/m/s{i}.mp4."
                        for i in range(5))
        raw += "\nError: Received a status code of 429 while downloading file https://pub.r2.dev/p/m/t.jpg."
        text = render.plain_error(raw)
        self.assertIn("5 files the video needs were not found in storage (404)", text)
        self.assertIn("and 2 more", text)
        self.assertIn("1 file the video needs was refused for too many requests (429)", text)

    def test_a_frame_number_beside_a_link_is_not_a_status(self):
        text = render.plain_error("Error: could not decode frame 404 of https://pub.r2.dev/p/m/s1.mp4")
        self.assertTrue(text.startswith("Error: could not decode"))

    def test_an_ordinary_error_is_left_alone_and_signed_tokens_are_not_put_first(self):
        self.assertEqual(render.plain_error("TypeError: x is not a function\n    at Foo"),
                         "TypeError: x is not a function\n at Foo")
        text = render.plain_error("Received a status code of 403 while downloading file "
                                  "https://sb.example/storage/v1/object/sign/video-media/p/a.mp4?token=SECRET.")
        self.assertNotIn("SECRET", text.split("link?")[0])     # the lead names the file, never its token
        self.assertIn("sb.example/.../a.mp4", text.split("link?")[0])


class Watcher(unittest.TestCase):
    def test_a_silent_render_past_its_limit_is_stopped(self):
        # It used to be checked only when a line arrived: a hung render printed none.
        started = time.time()
        with mock.patch.object(config, "REMOTION_DIR", tempfile.mkdtemp()):
            with self.assertRaises(render._Stopped) as cm:
                render._run_streaming([sys.executable, "-c", "import time; time.sleep(60)"], 1, None)
        self.assertEqual(cm.exception.why, "timeout")
        self.assertLess(time.time() - started, 20)

    def test_a_render_that_stops_making_progress_is_stopped(self):
        code = "import sys, time; print('Rendered 10/100'); sys.stdout.flush(); time.sleep(60)"
        got = []
        started = time.time()
        with mock.patch.object(config, "REMOTION_DIR", tempfile.mkdtemp()):
            with self.assertRaises(render._Stopped) as cm:
                render._run_streaming([sys.executable, "-c", code], 600, got.append, stall=2)
        self.assertEqual(cm.exception.why, "stall")
        self.assertAlmostEqual(cm.exception.frac, 0.08)
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0], 0.08)
        self.assertLess(time.time() - started, 25)

    def test_the_stall_error_says_how_far_it_got(self):
        text = render._out_of_time(52000, 14400, 5400, 0.55, stalled=True, quiet=900)
        self.assertIn("stopped making progress", text)
        self.assertIn("55% done", text)
        text = render._out_of_time(52000, 14400, 5400, 0.55)
        self.assertIn("55% done after 1 h 30 min", text)
        self.assertIn("the limit was 4 h 00 min", text)


if __name__ == "__main__":
    unittest.main()
