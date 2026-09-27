import os
import tempfile
import unittest
from unittest import mock

from src import config, render


class RenderCommand(unittest.TestCase):
    """The Remotion command line the worker builds, without running Remotion."""

    def _capture(self, **kw):
        seen = {}

        def fake_run(argv, **_):
            seen["argv"] = argv
            out = argv[argv.index("Main") + 1]
            with open(out, "wb") as f:
                f.write(b"x")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as d, mock.patch.object(render.subprocess, "run", fake_run):
            render.render({"fps": 30, "scenes": [], "overlays": []}, os.path.join(d, "v.mp4"), **kw)
        return seen["argv"]

    def test_render_waits_long_enough_for_map_tiles(self):
        argv = self._capture()
        # A satellite map fetches public tiles while rendering; Remotion's 30 s
        # default killed a render on one slow tile.
        self.assertIn(f"--timeout={config.RENDER_DELAY_TIMEOUT_MS}", argv)
        self.assertGreaterEqual(config.RENDER_DELAY_TIMEOUT_MS, 90000)
        self.assertIn(f"--offthreadvideo-video-threads={config.RENDER_VIDEO_THREADS}", argv)

    def test_chunk_and_audio_flags(self):
        argv = self._capture(frames=(30, 59), muted=True)
        self.assertIn("--frames=30-59", argv)
        self.assertIn("--muted", argv)
        argv = self._capture(codec="aac")
        self.assertIn("--codec=aac", argv)


class SplitAndProgress(unittest.TestCase):
    def test_animation_scenes_do_not_keep_a_render_on_one_worker(self):
        import handler
        doc = {"scenes": [{"media": {"type": "animation", "url": "", "source": "template"}},
                          {"media": {"type": "video", "url": "https://x/y.mp4"}},
                          {"media": {"type": "color", "url": ""}}], "overlays": []}
        self.assertTrue(handler._all_remote(doc))
        doc["scenes"].append({"media": {"type": "video", "url": "/tmp/local.mp4"}})
        self.assertFalse(handler._all_remote(doc))

    def test_bundling_is_not_render_progress(self):
        self.assertIsNone(render._render_progress("Bundling 100%"))
        self.assertAlmostEqual(render._render_progress("Rendered 50/100, time remaining: 1m"), 0.4)


if __name__ == "__main__":
    unittest.main()
