"""The narration polish (src/voicepolish.py): what it decides, what it does, and that it can only skip."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, voicepolish as vp

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def _stats(**over):
    """A clean narration's measurements (the Lake Powell voice), with overrides."""
    base = {"rate": 44100, "channels": 2, "seconds": 1087.5, "lufs": -22.2, "lra": 3.3, "tp": -1.4,
            "noiseFloor": -63.2, "floorReliable": True, "snr": 41.0, "vowelDb": -26.0, "rumble": -31.7,
            "sibilance": -11.9, "humProminence": None, "humHz": None, "humHarmonics": []}
    base.update(over)
    return base


def _steps(stats):
    return [s["step"] for s in vp.plan(stats)["steps"]]


class Decisions(unittest.TestCase):
    def test_a_clean_recording_is_never_denoised(self):
        plan = vp.plan(_stats())
        self.assertNotIn("denoise", _steps(_stats()))
        self.assertIn("clean", plan["skipped"]["denoise"])
        self.assertNotIn("deess", _steps(_stats()))
        self.assertNotIn("level", _steps(_stats()))

    def test_noise_close_to_the_voice_is_taken_down_harder_the_closer_it_is(self):
        mild = next(s for s in vp.plan(_stats(noiseFloor=-56.7, snr=34.4))["steps"] if s["step"] == "denoise")
        bad = next(s for s in vp.plan(_stats(noiseFloor=-41.0, snr=18.5))["steps"] if s["step"] == "denoise")
        self.assertGreater(bad["reduction"], mild["reduction"])
        self.assertLessEqual(bad["reduction"], 20.0)
        self.assertEqual(mild["floor"], -56.7)

    def test_without_pauses_the_room_is_unknown_and_left_alone(self):
        plan = vp.plan(_stats(noiseFloor=-45.0, snr=23.0, floorReliable=False))
        self.assertNotIn("denoise", [s["step"] for s in plan["steps"]])
        self.assertIn("pauses", plan["skipped"]["denoise"])

    def test_an_inaudible_floor_is_clean_whatever_the_voice_level(self):
        self.assertNotIn("denoise", _steps(_stats(lufs=-40.0, noiseFloor=-75.0, snr=35.0)))

    def test_harsh_esses_are_de_essed_natural_ones_are_not(self):
        self.assertIn("deess", _steps(_stats(sibilance=-4.2)))
        self.assertNotIn("deess", _steps(_stats(sibilance=-9.9)))
        deess = next(s for s in vp.plan(_stats(sibilance=-4.2))["steps"] if s["step"] == "deess")
        self.assertAlmostEqual(deess["thresholdDb"], -26.0 + vp.SIBILANCE_TARGET_DB)

    def test_rumble_and_hum_get_the_high_pass_and_hum_harmonics_get_notches(self):
        self.assertIn("highpass", _steps(_stats(rumble=-11.8)))
        self.assertNotIn("highpass", _steps(_stats(rumble=-31.7)))
        plan = vp.plan(_stats(humProminence=18.0, humHz=60, humHarmonics=[1, 2, 3]))
        self.assertEqual([s["step"] for s in plan["steps"]][:2], ["highpass", "dehum"])
        self.assertIn("equalizer=f=120:t=q:w=16:g=-18", plan["chain"])
        self.assertIn("equalizer=f=180:t=q:w=16:g=-18", plan["chain"])

    def test_peaks_and_level_drift(self):
        self.assertIn("compress", _steps(_stats(tp=-1.4)))
        self.assertNotIn("compress", _steps(_stats(tp=-9.0)))
        self.assertIn("level", _steps(_stats(lra=11.9)))
        self.assertNotIn("level", _steps(_stats(lra=3.3)))

    def test_the_de_esser_is_split_band(self):
        plan = vp.plan(_stats(sibilance=-3.0))
        graph, last = vp._graph(plan["chain"], plan["stats"])
        self.assertIn("acrossover=split=5000", graph)
        self.assertIn("amix=inputs=2", graph)
        self.assertTrue(graph.endswith(f"[{last}]"))


def _make(path, noise_amp, seconds=14):
    """A voice-like signal (band-limited noise in phrases, 40% pauses) over a room of pink noise."""
    voice = (f"anoisesrc=d={seconds}:c=white:a=0.3:r=44100:s=11,bandpass=f=1000:w=1500,"
             "volume='if(gt(sin(2*PI*0.7*t),-0.2),1,0)':eval=frame")
    room = f"anoisesrc=d={seconds}:c=pink:a={noise_amp}:r=44100:s=5"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", voice, "-f", "lavfi", "-i", room,
                    "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0,volume=2,"
                    "aformat=channel_layouts=stereo[o]", "-map", "[o]", "-c:a", "pcm_s16le", path], check=True)
    return path


@unittest.skipUnless(shutil.which("ffmpeg") and HAVE_NUMPY, "needs ffmpeg and numpy")
class Polish(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_noisy_room_is_cleaned_in_time_at_the_same_loudness_and_length(self):
        src = _make(os.path.join(self.dir, "noisy.wav"), 0.006)
        stats = vp.analyze(src)
        self.assertTrue(stats["floorReliable"])
        self.assertLess(stats["snr"], vp.CLEAN_SNR_DB)
        dst = os.path.join(self.dir, "clean.flac")
        rep = vp.polish(src, dst, timeout=120)
        self.assertTrue(rep["applied"], rep.get("why"))
        self.assertIn("denoise", [s["step"] for s in rep["steps"]])
        after = vp.analyze(dst)
        self.assertLess(after["noiseFloor"], stats["noiseFloor"] - 4.0)
        self.assertAlmostEqual(after["lufs"], stats["lufs"], delta=vp.LOUDNESS_TOLERANCE)
        self.assertAlmostEqual(vp.probe(dst)["seconds"], vp.probe(src)["seconds"], delta=0.01)
        # The denoiser's own delay was measured and put back: the words did not move.
        self.assertLessEqual(vp.alignment(src, dst), vp.ALIGN_TOLERANCE_S)

    def test_a_clean_recording_keeps_its_room(self):
        src = _make(os.path.join(self.dir, "clean.wav"), 0.00005)
        stats = vp.analyze(src)
        self.assertNotIn("denoise", [s["step"] for s in vp.plan(stats)["steps"]])

    def test_any_failure_keeps_the_original_narration(self):
        src = _make(os.path.join(self.dir, "noisy.wav"), 0.006)
        doc = {"audio": {"url": src, "volume": 1.0}, "meta": {}}
        with mock.patch.object(config, "VOICE_POLISH", True), \
                mock.patch.object(vp, "_ffmpeg_ok", return_value=(False, "boom")):
            rep = vp.for_render(doc, self.dir)
        self.assertFalse(rep["applied"])
        self.assertEqual(doc["audio"]["url"], src)
        self.assertFalse(doc["meta"]["voicePolish"]["applied"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "narration.polished.flac")))

    def test_a_timing_change_is_refused(self):
        src = _make(os.path.join(self.dir, "noisy.wav"), 0.006)
        with mock.patch.object(vp, "alignment", return_value=0.004):
            rep = vp.polish(src, os.path.join(self.dir, "out.flac"), timeout=120)
        self.assertFalse(rep["applied"])
        self.assertIn("moved", rep["why"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out.flac")))

    def test_the_render_reads_the_cleaned_copy(self):
        src = _make(os.path.join(self.dir, "noisy.wav"), 0.006)
        doc = {"audio": {"url": src, "volume": 1.0}, "meta": {}}
        with mock.patch.object(config, "VOICE_POLISH", True):
            rep = vp.for_render(doc, self.dir)
        self.assertTrue(rep["applied"], rep.get("why"))
        self.assertEqual(doc["audio"]["url"], os.path.join(self.dir, "narration.polished.flac"))
        self.assertTrue(os.path.isfile(doc["audio"]["url"]))
        self.assertEqual(doc["meta"]["voicePolish"]["version"], vp.VERSION)


class Switches(unittest.TestCase):
    def test_off_switch_and_per_video_opt_out_leave_the_narration(self):
        for flag, audio in ((False, {"url": "/x/n.mp3"}), (True, {"url": "/x/n.mp3", "polish": False})):
            doc = {"audio": dict(audio), "meta": {}}
            with mock.patch.object(config, "VOICE_POLISH", flag), \
                    mock.patch.object(vp, "polish", side_effect=AssertionError("must not run")):
                rep = vp.for_render(doc, tempfile.gettempdir())
            self.assertFalse(rep["applied"])
            self.assertEqual(doc["audio"]["url"], "/x/n.mp3")

    def test_a_narration_that_cannot_be_fetched_is_left_to_the_renderer(self):
        doc = {"audio": {"url": "https://example.invalid/n.mp3"}, "meta": {}}
        with mock.patch.object(config, "VOICE_POLISH", True), \
                mock.patch("src.storage.download", side_effect=OSError("offline")):
            rep = vp.for_render(doc, tempfile.gettempdir())
        self.assertFalse(rep["applied"])
        self.assertEqual(doc["audio"]["url"], "https://example.invalid/n.mp3")


if __name__ == "__main__":
    unittest.main()
