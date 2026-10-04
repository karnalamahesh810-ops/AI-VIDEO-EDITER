"""
A video whose own media is gone from storage (src/quality.py MediaMissing,
Gate.explain, Gate.recover; handler._raise_explained).

2026-10-04: a project's scene media was deleted from Cloudflare R2 while it
rendered. The render failed and the project's error message was a raw 404
page ("...<path d=... stroke=#0055DC..."). The rules now:
  * most of the scenes' files unreadable before the render -> nothing is
    drawn and nothing is "repaired" into text cards: a plain error;
  * a render that fails -> every file is asked once more; what is gone is
    the error (how many scenes, which, storage's answer), never raw HTML;
  * a few files gone -> repaired and drawn once more, as before.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, events, gapfill, quality, render  # noqa: E402

HTML_404 = ("Error: Received a status code of 404 while downloading file https://cdn.example/p/media/s0001.mp4.\n"
            "The response body was:\n---\n<!DOCTYPE html><html><head><title>404 Not Found</title></head><body>"
            '<svg><path d="M0 0L9 9" stroke=#0055DC /></svg></body></html>\n---\n')


class Resp:
    def __init__(self, code=206, total=5_000_000):
        self.status_code = code
        self.headers = {"Content-Range": f"bytes 0-4095/{total}", "Content-Type": "video/mp4"}
        self.content = b""

    def iter_content(self, n):
        yield b"\x00\x00\x00\x18ftypisom" + bytes(200)

    def close(self):
        pass


def _doc(n, url=lambda i: f"https://cdn.example/p/media/s{i:04d}.mp4", narration=""):
    scenes = [{"id": f"s{i:04d}", "startFrame": i * 90, "durationInFrames": 90, "text": f"line {i} about the lake",
               "transition": "none", "motion": "none", "words": [],
               "media": {"type": "video", "url": url(i), "source": "youtube", "clipSeconds": 4.0},
               "semanticMetadata": {"subject": "Lake Powell"}} for i in range(n)]
    return {"fps": 30, "width": 640, "height": 360, "durationInFrames": n * 90, "bgm": None,
            "audio": {"url": narration, "volume": 1} if narration else None,
            "captions": {"enabled": False}, "scenes": scenes, "overlays": [], "meta": {"warnings": []}}


def _settings():
    return mock.patch.multiple(config, QUALITY_HTTP_TIMEOUT=2, QUALITY_AUDIT_SECONDS=60, ANIMATION_FILL=False,
                               QUALITY_REPAIR_GENERATED=False, QUALITY_MISSING_SHARE=0.3, QUALITY_MISSING_MIN=3)


def _storage(dead=lambda url: True, code=404):
    """requests.get as the gate uses it: `dead(url)` links answer `code`, the rest are fine."""
    def get(url, **kw):
        if dead(url):
            if isinstance(code, Exception):
                raise code
            return Resp(code)
        return Resp(206)
    return mock.patch.object(quality.requests, "get", side_effect=get)


class BeforeTheRender(unittest.TestCase):
    def setUp(self):
        events.start_job("gone-test", "")
        quality.reset()
        gapfill.reset()

    def tearDown(self):
        quality.reset()
        gapfill.reset()

    def test_a_video_whose_media_was_deleted_stops_before_a_frame_is_drawn(self):
        doc = _doc(200)
        with _settings(), _storage(), mock.patch.object(quality.time, "sleep"):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            with self.assertRaises(quality.MediaMissing) as cm:
                gate.before_render()
        text = str(cm.exception)
        self.assertIn("200 of 200 scenes' clips and pictures are missing from storage", text)
        self.assertIn("HTTP 404", text)
        self.assertIn("deleted from storage?", text)
        self.assertIn("scene 1 (cdn.example/.../s0000.mp4)", text)
        self.assertIn("and 197 more", text)
        self.assertIn("Nothing was rendered", text)
        self.assertLess(len(text), 800)                              # the app keeps 800 characters
        # Nothing was "repaired": no scene turned into a text card or a held shot.
        self.assertEqual(len(doc["scenes"]), 200)
        self.assertTrue(all(s["media"]["type"] == "video" and s["media"]["url"] for s in doc["scenes"]))
        self.assertTrue(any(e["event"] == "media_missing" and e["level"] == "error" for e in events._EVENTS))

    def test_just_over_the_share_stops_and_a_few_broken_scenes_are_still_repaired(self):
        doc = _doc(10)
        with _settings(), _storage(lambda u: u.endswith(("s0001.mp4", "s0004.mp4"))), \
                mock.patch.object(quality.time, "sleep"):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()                                     # 2 of 10: repaired, as before
        self.assertEqual(gate.found["unreachable"], 2)
        self.assertEqual(gate.fixed["held"] + gate.fixed["text"] + gate.fixed["graphic"], 2)
        self.assertNotIn("https://cdn.example/p/media/s0001.mp4", [s["media"].get("url") for s in doc["scenes"]])
        doc = _doc(10)
        with _settings(), _storage(lambda u: u.endswith(("s0001.mp4", "s0004.mp4", "s0006.mp4", "s0008.mp4"))), \
                mock.patch.object(quality.time, "sleep"):
            with self.assertRaises(quality.MediaMissing) as cm:
                quality.Gate(doc, tempfile.mkdtemp()).before_render()   # 4 of 10
        self.assertIn("4 of 10 scenes", str(cm.exception))

    def test_a_short_video_with_two_dead_links_is_repaired_not_stopped(self):
        doc = _doc(4)
        with _settings(), _storage(lambda u: u.endswith(("s0001.mp4", "s0002.mp4"))), \
                mock.patch.object(quality.time, "sleep"):
            quality.Gate(doc, tempfile.mkdtemp()).before_render()    # 50%, but under QUALITY_MISSING_MIN

    def test_storage_that_is_down_says_try_again_not_deleted(self):
        doc = _doc(10)
        with _settings(), _storage(code=quality.requests.Timeout()), mock.patch.object(quality.time, "sleep"):
            with self.assertRaises(quality.MediaMissing) as cm:
                quality.Gate(doc, tempfile.mkdtemp()).before_render()
        text = str(cm.exception)
        self.assertIn("could not be read from storage right now", text)
        self.assertIn("try again in a few minutes", text)
        self.assertNotIn("deleted", text)
        doc = _doc(10)
        with _settings(), _storage(code=403), mock.patch.object(quality.time, "sleep"):
            with self.assertRaises(quality.MediaMissing) as cm:
                quality.Gate(doc, tempfile.mkdtemp()).before_render()
        self.assertIn("refused by storage", str(cm.exception))

    def test_files_that_were_never_saved_are_still_re_sourced_until_most_are_gone(self):
        # An upload outage leaves a dead machine's paths in the timeline: the
        # ladder re-sources them (test_quality's outage regression) - but a
        # video that is mostly such paths is not turned into text cards.
        dead = lambda i: (os.path.join(tempfile.gettempdir(), "dead-pod", f"s{i:04d}.mp4")  # noqa: E731
                          if i % 2 else f"https://cdn.example/p/media/s{i:04d}.mp4")
        doc = _doc(10, url=dead)
        with _settings(), _storage(lambda u: False):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()                                     # 5 of 10 unsaved: repaired
        self.assertEqual(gate.found["unreachable"], 5)
        doc = _doc(10, url=lambda i: os.path.join(tempfile.gettempdir(), "dead-pod", f"s{i:04d}.mp4")
                   if i < 8 else f"https://cdn.example/p/media/s{i:04d}.mp4")
        with _settings(), _storage(lambda u: False):
            with self.assertRaises(quality.MediaMissing) as cm:
                quality.Gate(doc, tempfile.mkdtemp()).before_render()
        self.assertIn("8 of 10 scenes' clips and pictures were never saved to storage", str(cm.exception))

    def test_the_rule_can_be_switched_off(self):
        doc = _doc(10)
        with _settings(), mock.patch.object(config, "QUALITY_MISSING_SHARE", 0), _storage(), \
                mock.patch.object(quality.time, "sleep"):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertEqual(gate.found["unreachable"], 10)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class AfterAFailedRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.media = tempfile.mkdtemp(prefix="gone_media_")
        cls.clean = os.path.join(cls.media, "clean.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                        "-f", "lavfi", "-i", "sine=f=300:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.clean], check=True, capture_output=True)
        cls.narration = os.path.join(cls.media, "vo.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=1", cls.narration],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        events.start_job("gone-render", "")
        quality.reset()
        gapfill.reset()

    def tearDown(self):
        quality.reset()
        gapfill.reset()

    def _run(self, doc, outputs, dead_after):
        """do_render with a fake renderer; storage answers 404 for `dead_after(url)` once the first render ran."""
        state = {"renders": 0}

        def fake_render(d, path, **kw):
            state["renders"] += 1
            out = outputs[min(state["renders"], len(outputs)) - 1]
            if isinstance(out, Exception):
                raise out
            shutil.copy(out, path)
            return path

        def get(url, **kw):
            return Resp(404) if state["renders"] and dead_after(url) else Resp(206)
        work = tempfile.mkdtemp()
        with _settings(), mock.patch.object(config, "RENDER_SEPARATE_AUDIO", False), \
                mock.patch.object(config, "QUALITY_SCAN", False), \
                mock.patch.object(quality.requests, "get", side_effect=get), \
                mock.patch.object(quality.time, "sleep"), \
                mock.patch.object(handler.renderer, "render", side_effect=fake_render), \
                mock.patch.object(handler.renderer, "normalize_loudness", return_value=False), \
                mock.patch.object(handler.timeline, "relevel_to_voice"), \
                mock.patch.object(handler.grade, "prepare", return_value={}), \
                mock.patch.object(handler.voicepolish, "for_render", return_value={}), \
                mock.patch.object(handler, "_keep_render"), \
                mock.patch.object(handler.r2, "enabled", return_value=False):
            try:
                out = handler.do_render(doc, {"return_video": True}, work, lambda *a, **k: None)
            finally:
                state["gate"] = quality.LAST.get("gate")
        return out, state

    def test_media_deleted_mid_render_is_the_error_in_plain_words_never_html(self):
        doc = _doc(12, narration=self.narration)
        with self.assertRaises(Exception) as cm:
            self._run(doc, [render.RenderError("remotion render failed (exit 1): " + HTML_404)], lambda u: True)
        text = str(cm.exception)
        self.assertIsInstance(cm.exception, quality.MediaMissing)
        self.assertIn("The render failed: 12 of 12 scenes' clips and pictures are missing from storage", text)
        self.assertIn("deleted from storage?", text)
        for junk in ("<path", "<svg", "<html", "stroke", "#0055DC"):
            self.assertNotIn(junk, text)
        self.assertTrue(all(s["media"]["type"] == "video" for s in doc["scenes"]))    # not turned into text cards

    def test_one_file_gone_mid_render_is_repaired_and_drawn_once_more(self):
        # The error names nothing (a chunk worker's "exit 1"): what is gone is found by asking.
        doc = _doc(12, narration=self.narration)
        out, state = self._run(doc, [render.RenderError("remotion render failed (exit 1): the worker died"),
                                     self.clean], lambda u: u.endswith("s0005.mp4"))
        self.assertEqual(state["renders"], 2)
        self.assertNotIn("https://cdn.example/p/media/s0005.mp4", [s["media"].get("url") for s in doc["scenes"]])
        self.assertTrue(out["quality"]["render"]["afterFailure"])
        self.assertEqual(out["quality"]["found"]["render"], 1)

    def test_a_second_failure_over_missing_files_is_explained_too(self):
        doc = _doc(12, narration=self.narration)
        with self.assertRaises(render.RenderError) as cm:
            self._run(doc, [render.RenderError("remotion render failed (exit 1): boom"),
                            render.RenderError("remotion render failed (exit 1): " + HTML_404)],
                      lambda u: u.endswith(("s0005.mp4", "s0001.mp4")))
        text = str(cm.exception)
        # The first failure repaired both scenes; the second render failed anyway and nothing is gone
        # now, so the renderer's own (cleaned) error stands.
        self.assertNotIn("<svg", text)
        self.assertNotIn("stroke", text)

    def test_a_failure_with_every_file_still_there_keeps_the_renders_own_error(self):
        doc = _doc(6, narration=self.narration)
        with self.assertRaises(render.RenderError) as cm:
            self._run(doc, [render.RenderError("remotion render failed (exit 1): out of memory")], lambda u: False)
        self.assertIn("out of memory", str(cm.exception))


class Explain(unittest.TestCase):
    def setUp(self):
        events.start_job("gone-explain", "")

    def test_scenes_gone_are_counted_and_named(self):
        doc = _doc(10)
        with _settings(), _storage(lambda u: u.endswith(("s0002.mp4", "s0007.mp4"))), \
                mock.patch.object(quality.time, "sleep"):
            text = quality.Gate(doc, tempfile.mkdtemp()).explain(RuntimeError("x"))
        self.assertIn("The render failed: 2 of 10 scenes' clips and pictures are missing from storage", text)
        self.assertIn("scene 3 (cdn.example/.../s0002.mp4)", text)
        self.assertIn("scene 8 (cdn.example/.../s0007.mp4)", text)

    def test_other_files_gone_are_said_too_and_nothing_gone_says_nothing(self):
        doc = _doc(4, narration="https://sb.example/vo.mp3")
        with _settings(), _storage(lambda u: "vo.mp3" in u), mock.patch.object(quality.time, "sleep"):
            text = quality.Gate(doc, tempfile.mkdtemp()).explain()
        self.assertIn("1 file the video needs cannot be read from storage", text)
        self.assertIn("vo.mp3", text)
        with _settings(), _storage(lambda u: False):
            self.assertEqual(quality.Gate(_doc(4), tempfile.mkdtemp()).explain(), "")

    def test_a_check_that_breaks_never_hides_the_renders_error(self):
        gate = quality.Gate(_doc(4), tempfile.mkdtemp())
        with mock.patch.object(gate, "_gone_now", side_effect=RuntimeError("a bug")):
            self.assertEqual(gate.explain(), "")
        err = render.RenderError("the real reason")
        with mock.patch.object(gate, "explain", side_effect=RuntimeError("a bug")):
            with self.assertRaises(render.RenderError) as cm:
                handler._raise_explained(err, gate)
        self.assertIs(cm.exception, err)


if __name__ == "__main__":
    unittest.main()
