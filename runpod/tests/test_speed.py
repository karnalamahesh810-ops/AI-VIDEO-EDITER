"""
Render speed and the sound's timing (src/render.py, 2026-10-01).

* every h264 render asks x264 for RENDER_X264_PRESET (veryfast: 2.3x the
  encode speed of Remotion's default at the same picture quality);
* the sound is rendered as lossless WAV beside a picture-only MP4 and joined
  by render.finalize, which sets the loudness and encodes AAC once - and puts
  the sound exactly on frame 0 (Remotion's ADTS AAC played 42.7 ms late);
* renders use a pre-built Remotion bundle (render.ensure_bundle), built once
  per machine and code version, falling back to bundling from source.
"""
import array
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import handler
from src import config, render


def _argv(**kw):
    """The Remotion command line render() builds (Remotion itself is not run)."""
    seen = {}

    def fake_run(argv, **_):
        seen["argv"] = argv
        out = argv[argv.index("Main") + 1]
        with open(out, "wb") as f:
            f.write(b"x")
        for a in argv:
            if a.startswith("--separate-audio-to="):
                with open(a.split("=", 1)[1], "wb") as f:
                    f.write(b"RIFF")
        return mock.Mock(returncode=0, stdout="", stderr="")

    with tempfile.TemporaryDirectory() as d, mock.patch.object(render.subprocess, "run", fake_run), \
            mock.patch.object(render, "ensure_bundle", return_value=kw.pop("bundle", "")), \
            mock.patch.object(render.templates, "sfx_files", return_value=set()):
        if kw.pop("with_audio", False):
            kw["audio_to"] = os.path.join(d, "mix.wav")
        render.render({"fps": 30, "scenes": [], "overlays": []}, os.path.join(d, "v.mp4"), **kw)
    return seen["argv"]


class X264Preset(unittest.TestCase):
    def test_video_renders_ask_for_the_preset_and_sound_renders_do_not(self):
        with mock.patch.object(config, "RENDER_X264_PRESET", "veryfast"):
            self.assertIn("--x264-preset=veryfast", _argv())
            self.assertIn("--x264-preset=veryfast", _argv(frames=(0, 29), muted=True))   # a chunk
            self.assertFalse([a for a in _argv(codec="wav") if a.startswith("--x264-preset")])
            self.assertFalse([a for a in _argv(codec="aac") if a.startswith("--x264-preset")])

    def test_an_unknown_or_empty_preset_leaves_remotions_default(self):
        for value in ("", "turbo", "medium; rm -rf /"):
            with mock.patch.object(config, "RENDER_X264_PRESET", value):
                self.assertFalse([a for a in _argv() if a.startswith("--x264-preset")], value)
        with mock.patch.object(config, "RENDER_X264_PRESET", "Faster"):
            self.assertIn("--x264-preset=faster", _argv())

    def test_the_default_is_veryfast(self):
        if "RENDER_X264_PRESET" not in os.environ:
            self.assertEqual(config.RENDER_X264_PRESET, "veryfast")
            self.assertEqual(render.x264_preset(), "veryfast")


class SeparateSound(unittest.TestCase):
    def test_the_sound_goes_to_a_wav_beside_a_picture_only_render(self):
        argv = _argv(with_audio=True)
        sep = [a for a in argv if a.startswith("--separate-audio-to=")]
        self.assertEqual(len(sep), 1)
        self.assertTrue(sep[0].endswith("mix.wav"))
        self.assertTrue(os.path.isabs(sep[0].split("=", 1)[1]))
        # A document with no sound still yields a (silent) track.
        self.assertIn("--enforce-audio-track", argv)

    def test_no_separate_sound_for_silent_chunks_or_sound_renders(self):
        for kw in ({"muted": True, "frames": (0, 9)}, {"codec": "wav"}):
            argv = _argv(with_audio=True, **kw)
            self.assertFalse([a for a in argv if a.startswith("--separate-audio-to")], kw)

    def test_a_render_that_wrote_no_sound_is_an_error(self):
        def fake_run(argv, **_):
            out = argv[argv.index("Main") + 1]
            with open(out, "wb") as f:
                f.write(b"x")
            return mock.Mock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(render.subprocess, "run", fake_run), \
                mock.patch.object(render, "ensure_bundle", return_value=""), \
                mock.patch.object(render.templates, "sfx_files", return_value=set()):
            with self.assertRaises(render.RenderError):
                render.render({"scenes": []}, os.path.join(d, "v.mp4"), audio_to=os.path.join(d, "a.wav"))


class Bundle(unittest.TestCase):
    def setUp(self):
        render._FINGERPRINTS.clear()
        render._BUNDLE_FAILED.clear()

    def tearDown(self):
        render._FINGERPRINTS.clear()
        render._BUNDLE_FAILED.clear()

    def _project(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "src", "components"))
        os.makedirs(os.path.join(root, "public", "sfx"))
        with open(os.path.join(root, "src", "index.ts"), "w") as f:
            f.write("registerRoot(Root);")
        with open(os.path.join(root, "src", "components", "A.tsx"), "w") as f:
            f.write("export const A = 1;")
        with open(os.path.join(root, "public", "sfx", "boom.mp3"), "wb") as f:
            f.write(b"\0" * 100)
        return root

    def test_render_uses_the_prebuilt_bundle_when_there_is_one(self):
        argv = _argv(bundle="/tmp/remotion-bundles/abc")
        self.assertEqual(argv[argv.index("render") + 1], "/tmp/remotion-bundles/abc")
        argv = _argv(bundle="")
        self.assertEqual(argv[argv.index("render") + 1], "src/index.ts")

    def test_the_fingerprint_follows_the_code_and_the_sound_files(self):
        root = self._project()
        a = render.renderer_fingerprint(root)
        render._FINGERPRINTS.clear()
        self.assertEqual(render.renderer_fingerprint(root), a)
        with open(os.path.join(root, "src", "components", "A.tsx"), "w") as f:
            f.write("export const A = 2;")
        render._FINGERPRINTS.clear()
        b = render.renderer_fingerprint(root)
        self.assertNotEqual(a, b)
        with open(os.path.join(root, "public", "sfx", "new.mp3"), "wb") as f:
            f.write(b"\0")
        render._FINGERPRINTS.clear()
        self.assertNotEqual(render.renderer_fingerprint(root), b)

    def test_built_once_then_reused_and_a_failure_falls_back_to_source(self):
        root = self._project()
        base = tempfile.mkdtemp()
        calls = []

        def build(argv, **kw):
            calls.append(argv)
            out = argv[argv.index("--out-dir") + 1]
            with open(os.path.join(out, "index.html"), "w") as f:
                f.write("<html>")
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(config, "REMOTION_DIR", root), mock.patch.object(config, "RENDER_PREBUNDLE", True), \
                mock.patch.object(config, "RENDER_BUNDLE_DIR", base), \
                mock.patch.object(render.subprocess, "run", side_effect=build):
            first = render.ensure_bundle()
            second = render.ensure_bundle()
        self.assertEqual(first, second)
        self.assertTrue(os.path.isfile(os.path.join(first, "index.html")))
        self.assertEqual(os.path.basename(first), render.renderer_fingerprint(root))
        self.assertEqual(len(calls), 1)
        self.assertIn("bundle", calls[0])

        render._FINGERPRINTS.clear()
        with open(os.path.join(root, "src", "components", "A.tsx"), "w") as f:
            f.write("export const A = 3;")                       # new code: a new bundle is needed
        with mock.patch.object(config, "REMOTION_DIR", root), mock.patch.object(config, "RENDER_PREBUNDLE", True), \
                mock.patch.object(config, "RENDER_BUNDLE_DIR", base), \
                mock.patch.object(render.subprocess, "run",
                                  return_value=mock.Mock(returncode=1, stdout="", stderr="webpack error")) as run:
            self.assertEqual(render.ensure_bundle(), "")
            self.assertEqual(render.ensure_bundle(), "")             # not retried in this process
            self.assertEqual(run.call_count, 1)

    def test_off_or_no_project_means_no_bundle(self):
        with mock.patch.object(config, "RENDER_PREBUNDLE", False):
            self.assertEqual(render.ensure_bundle(), "")
        with mock.patch.object(config, "RENDER_PREBUNDLE", True), \
                mock.patch.object(config, "REMOTION_DIR", tempfile.mkdtemp()):
            self.assertEqual(render.ensure_bundle(), "")


def _beep_onset_ms(path: str, rate: int = 48000) -> float:
    """Where the first sound over -30 dBFS starts after decoding (edit lists applied)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", str(rate),
                        "-f", "s16le", "-"], capture_output=True)
    pcm = array.array("h")
    pcm.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    thr = int(32767 * 10 ** (-30 / 20))
    first = next((i for i, v in enumerate(pcm) if abs(v) > thr), None)
    return first * 1000.0 / rate if first is not None else -1.0


def _streams(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,nb_frames,duration",
                          "-of", "json", path], capture_output=True, text=True).stdout
    return {s["codec_type"]: s for s in json.loads(out or "{}").get("streams", [])}


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class Finalize(unittest.TestCase):
    def _inputs(self, d, level="0.2"):
        picture = os.path.join(d, "picture.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4",
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", picture], check=True)
        wav = os.path.join(d, "mix.wav")
        # Quiet pink noise under a loud 50 ms beep starting at exactly 1.000 s.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "aevalsrc='if(between(t,1,1.05),0.9*sin(2*PI*1000*t),0)':s=48000:d=4",
                        "-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:a=0.004:r=48000",
                        "-filter_complex", f"[0:a][1:a]amix=inputs=2:normalize=0,volume={level}",
                        "-ac", "2", "-c:a", "pcm_s16le", wav], check=True)
        return picture, wav

    def test_the_sound_starts_on_frame_zero_and_the_picture_is_copied(self):
        d = tempfile.mkdtemp()
        picture, wav = self._inputs(d)
        out = os.path.join(d, "final.mp4")
        info = render.finalize(picture, wav, out, target=0)          # no loudness change: timing only
        self.assertFalse(info["gainApplied"])
        self.assertAlmostEqual(_beep_onset_ms(wav), 1000.0, delta=1.0)
        self.assertAlmostEqual(_beep_onset_ms(out), 1000.0, delta=5.0)  # AAC frame jitter; the bug was 42.7 ms
        s = _streams(out)
        self.assertEqual(s["audio"]["codec_name"], "aac")
        self.assertEqual(s["video"]["codec_name"], "h264")
        self.assertEqual(s["video"].get("nb_frames"), _streams(picture)["video"].get("nb_frames"))
        # The sound lasts as long as the picture (not 53 ms longer).
        self.assertAlmostEqual(float(s["audio"]["duration"]), float(s["video"]["duration"]), delta=0.03)

    def test_loudness_is_set_in_the_same_pass_without_moving_the_sound(self):
        d = tempfile.mkdtemp()
        picture, wav = self._inputs(d, level="0.05")
        out = os.path.join(d, "final.mp4")
        info = render.finalize(picture, wav, out, target=-14.0)
        self.assertTrue(info["gainApplied"])
        self.assertLess(info["lufsIn"], -20)
        self.assertAlmostEqual(_beep_onset_ms(out), 1000.0, delta=5.0)  # AAC frame jitter; the bug was 42.7 ms

    def test_a_broken_sound_file_fails_loudly(self):
        d = tempfile.mkdtemp()
        picture, _wav = self._inputs(d)
        bad = os.path.join(d, "bad.wav")
        with open(bad, "wb") as f:
            f.write(b"not a wav")
        with self.assertRaises(render.RenderError):
            render.finalize(picture, bad, os.path.join(d, "final.mp4"), target=-14.0)


class DoRenderJoinsOnce(unittest.TestCase):
    def _doc(self):
        return {"fps": 30, "width": 320, "height": 180, "durationInFrames": 60, "meta": {"sceneCount": 1},
                "audio": {"url": "", "volume": 1}, "scenes": [], "overlays": []}

    def _run(self, separate):
        calls = {}

        def fake_render(doc, path, **kw):
            calls["render"] = (path, kw)
            with open(path, "wb") as f:
                f.write(b"video")
            if kw.get("audio_to"):
                with open(kw["audio_to"], "wb") as f:
                    f.write(b"RIFF")
            return path

        def fake_finalize(video, audio, out, **kw):
            calls["finalize"] = (video, audio, out)
            with open(out, "wb") as f:
                f.write(b"final")
            return {}
        work = tempfile.mkdtemp()
        with mock.patch.object(config, "RENDER_SEPARATE_AUDIO", separate), \
                mock.patch.object(handler.timeline, "drop_invalid_overlays"), \
                mock.patch.object(handler.timeline, "validate"), \
                mock.patch.object(handler, "_preflight_media", return_value=0), \
                mock.patch.object(handler, "_sanitize_stills"), \
                mock.patch.object(handler, "_sign_supabase_urls"), \
                mock.patch.object(handler.renderer, "render", side_effect=fake_render), \
                mock.patch.object(handler.renderer, "finalize", side_effect=fake_finalize), \
                mock.patch.object(handler.renderer, "normalize_loudness", return_value=False) as loud, \
                mock.patch.object(handler.r2, "enabled", return_value=True), \
                mock.patch.object(handler, "_keep_render"):
            out = handler.do_render(self._doc(), {"return_video": True}, work, lambda *a, **k: None)
        return calls, loud, out, work

    def test_the_picture_and_the_sound_are_joined_once_with_the_loudness(self):
        calls, loud, out, work = self._run(True)
        path, kw = calls["render"]
        self.assertTrue(kw.get("audio_to", "").endswith(".wav"))
        self.assertEqual(calls["finalize"][0], path)
        self.assertEqual(calls["finalize"][2], os.path.join(work, "final.mp4"))
        loud.assert_not_called()                 # no second pass over the finished file
        self.assertFalse(os.path.exists(path))  # the picture-only copy is gone
        self.assertEqual(out["uploadedVia"], "inline")

    def test_the_old_path_stays_behind_the_switch(self):
        calls, loud, _out, work = self._run(False)
        path, kw = calls["render"]
        self.assertEqual(path, os.path.join(work, "final.mp4"))
        self.assertNotIn("audio_to", kw)
        self.assertNotIn("finalize", calls)
        loud.assert_called_once()


if __name__ == "__main__":
    unittest.main()
