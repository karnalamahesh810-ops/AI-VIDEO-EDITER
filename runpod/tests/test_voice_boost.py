"""
The editor's voice boost (doc.audio.boostDb, its Voice slider over 100%) in the
render (src/voicepolish.py boost_for_render): the narration made louder with a
true-peak limiter, so a boost never clips; the music and sounds are left as
they were; any failure keeps the narration; no volume over 1 reaches Remotion;
and a spread render's workers get the boosted file.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, fanout, voicepolish as vp  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

CEILING = config.VOICE_BOOST_CEILING_DBTP
# A real narration (bench/README.md): -19.9 LUFS, its peaks at -0.3 dBFS - a boost has to be limited.
BENCH = os.path.join(ROOT, "bench", "audio", "lake_mead.mp3")


def _voice(path, seconds=14, gain_db=0.0):
    """A quiet voice-like narration (band-limited noise in phrases, pauses between; ~-54 LUFS) at 44.1 kHz stereo."""
    voice = (f"anoisesrc=d={seconds}:c=white:a=0.3:r=44100:s=11,bandpass=f=1000:w=1500,"
             "volume='if(gt(sin(2*PI*0.7*t),-0.2),1,0)':eval=frame")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", voice, "-af",
                    f"volume={2 * 10 ** (gain_db / 20):.4f},aformat=channel_layouts=stereo", "-c:a", "pcm_s16le",
                    path], check=True)
    return path


@unittest.skipUnless(shutil.which("ffmpeg") and HAVE_NUMPY, "needs ffmpeg and numpy")
class Boost(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    @unittest.skipUnless(os.path.isfile(BENCH), "needs the bench narration")
    def test_six_db_on_a_real_narration_is_louder_and_its_peaks_stay_under_the_ceiling(self):
        before = vp.loudness(BENCH)
        self.assertGreater(before["tp"], CEILING)               # its peaks are over the ceiling already
        dst = os.path.join(self.dir, "b.flac")
        rep = vp.boost(BENCH, dst, 6.0, timeout=120)
        self.assertTrue(rep["applied"], rep.get("why"))
        after = vp.loudness(dst)
        gain = after["lufs"] - before["lufs"]
        self.assertGreater(gain, 2.0)
        self.assertLess(gain, 6.0)                              # by up to the boost: the limiter holds the loud syllables
        self.assertLessEqual(after["tp"], CEILING + vp.BOOST_PEAK_TOLERANCE_DB)
        self.assertEqual(rep["after"]["tp"], after["tp"])
        info, got = vp.probe(BENCH), vp.probe(dst)
        self.assertEqual((got["rate"], got["channels"]), (info["rate"], info["channels"]))
        self.assertAlmostEqual(got["seconds"], info["seconds"], delta=0.01)
        self.assertLessEqual(vp.alignment(BENCH, dst), vp.ALIGN_TOLERANCE_S)   # every word where it was

    def test_a_quiet_narration_gains_the_whole_boost(self):
        src = _voice(os.path.join(self.dir, "n.wav"))
        rep = vp.boost(src, os.path.join(self.dir, "b.flac"), 6.0, timeout=120)
        self.assertTrue(rep["applied"], rep.get("why"))
        self.assertAlmostEqual(rep["gainLu"], 6.0, delta=0.1)   # nothing near the ceiling: the limiter never acts
        self.assertLessEqual(rep["after"]["tp"], CEILING)

    def test_without_the_limiters_delay_compensation_the_delay_is_taken_out(self):
        # An ffmpeg older than 5.1 has no alimiter latency option: its look-ahead delay is measured instead.
        src = _voice(os.path.join(self.dir, "n.wav"))
        real = vp._ffmpeg_ok

        def old_ffmpeg(argv, timeout):
            if any("latency=1" in a for a in argv):
                return False, "[Parsed_alimiter_2] Option 'latency' not found"
            return real(argv, timeout)
        with mock.patch.object(vp, "_ffmpeg_ok", side_effect=old_ffmpeg):
            rep = vp.boost(src, os.path.join(self.dir, "b.flac"), 4.0, timeout=120)
        self.assertTrue(rep["applied"], rep.get("why"))
        self.assertLessEqual(vp.alignment(src, os.path.join(self.dir, "b.flac")), vp.ALIGN_TOLERANCE_S)

    def test_the_render_reads_the_boosted_copy(self):
        src = _voice(os.path.join(self.dir, "n.wav"))
        doc = {"audio": {"url": src, "volume": 1, "boostDb": 6.02}, "meta": {"voiceLufs": -20.0}}
        rep = vp.boost_for_render(doc, self.dir)
        self.assertTrue(rep["applied"], rep.get("why"))
        self.assertEqual(doc["audio"]["url"], os.path.join(self.dir, "narration.boosted.flac"))
        self.assertNotIn("boostDb", doc["audio"])              # never applied twice
        self.assertEqual(doc["audio"]["volume"], 1)
        self.assertTrue(doc["meta"]["voiceBoost"]["applied"])
        self.assertEqual(doc["meta"]["voiceLufs"], -20.0)      # the sounds stay levelled against the voice as it was
        self.assertEqual(vp.boost_for_render(doc, self.dir)["db"], 0.0)

    def test_any_failure_keeps_the_original_narration(self):
        src = _voice(os.path.join(self.dir, "n.wav"))
        doc = {"audio": {"url": src, "boostDb": 6}, "meta": {}}
        with mock.patch.object(vp, "_ffmpeg_ok", return_value=(False, "boom")):
            rep = vp.boost_for_render(doc, self.dir)
        self.assertFalse(rep["applied"])
        self.assertIn("boom", rep["why"])
        self.assertEqual(doc["audio"]["url"], src)
        self.assertFalse(doc["meta"]["voiceBoost"]["applied"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "narration.boosted.flac")))

    def test_a_result_that_would_clip_is_refused(self):
        src = _voice(os.path.join(self.dir, "n.wav"))
        real = vp.loudness

        def loud(path, timeout=300):
            got = real(path, timeout)
            return dict(got, tp=0.4) if path.endswith(".flac") else got
        with mock.patch.object(vp, "loudness", side_effect=loud):
            rep = vp.boost(src, os.path.join(self.dir, "b.flac"), 6.0, timeout=120)
        self.assertFalse(rep["applied"])
        self.assertIn("peaks", rep["why"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "b.flac")))

    def test_a_spread_render_publishes_the_boosted_file_to_its_workers(self):
        src = _voice(os.path.join(self.dir, "n.wav"))
        doc = {"audio": {"url": src, "boostDb": 3.0}, "meta": {}, "scenes": [], "overlays": []}
        vp.boost_for_render(doc, self.dir)
        published = [path for _m, field, path in fanout.local_refs(doc) if field == "url"]
        self.assertEqual(published, [os.path.join(self.dir, "narration.boosted.flac")])


class Switches(unittest.TestCase):
    def test_no_boost_leaves_the_narration_untouched(self):
        for audio in ({"url": "/x/n.mp3"}, {"url": "/x/n.mp3", "boostDb": 0}, {"url": "/x/n.mp3", "boostDb": 0.01},
                      {"url": "/x/n.mp3", "boostDb": None}, {"url": "/x/n.mp3", "boostDb": True},
                      {"url": "/x/n.mp3", "boostDb": "loud"}, {"url": "/x/n.mp3", "boostDb": -3}):
            doc = {"audio": dict(audio), "meta": {}}
            with mock.patch.object(vp, "boost", side_effect=AssertionError("must not run")), \
                    mock.patch.object(vp, "_source", side_effect=AssertionError("nothing to fetch")):
                rep = vp.boost_for_render(doc, tempfile.gettempdir())
            self.assertFalse(rep["applied"])
            self.assertEqual(doc["audio"]["url"], "/x/n.mp3")
            self.assertNotIn("voiceBoost", doc["meta"])
        self.assertEqual(vp.boost_for_render({"audio": None, "meta": {}}, tempfile.gettempdir())["db"], 0.0)

    def test_the_boost_is_held_to_the_sliders_200_percent(self):
        self.assertEqual(vp.boost_db({"boostDb": 20}), vp.BOOST_MAX_DB)
        self.assertEqual(vp.boost_db({"boostDb": "4.5"}), 4.5)
        self.assertEqual(vp.boost_db({"boostDb": float("nan")}), 0.0)

    def test_no_volume_over_1_reaches_the_renderer(self):
        for given, held in ((1.4, 1.0), (-0.2, 0.0), ("0.8", 0.8)):
            doc = {"audio": {"url": "/x/n.mp3", "volume": given}, "meta": {}}
            rep = vp.boost_for_render(doc, tempfile.gettempdir())
            self.assertEqual(doc["audio"]["volume"], held)
            self.assertEqual(rep["volumeClamped"], given)
            self.assertEqual(doc["meta"]["voiceBoost"]["volume"], held)
        doc = {"audio": {"url": "/x/n.mp3", "volume": "loud"}, "meta": {}}
        vp.boost_for_render(doc, tempfile.gettempdir())
        self.assertNotIn("volume", doc["audio"])                    # the renderer's own 1
        doc = {"audio": {"url": "/x/n.mp3", "volume": 0.7}, "meta": {}}
        vp.boost_for_render(doc, tempfile.gettempdir())
        self.assertEqual(doc["audio"]["volume"], 0.7)
        self.assertNotIn("voiceBoost", doc["meta"])

    def test_a_narration_that_cannot_be_fetched_is_left_to_the_renderer(self):
        doc = {"audio": {"url": "https://example.invalid/n.mp3", "boostDb": 6}, "meta": {}}
        with mock.patch("src.storage.download", side_effect=OSError("offline")):
            rep = vp.boost_for_render(doc, tempfile.gettempdir())
        self.assertFalse(rep["applied"])
        self.assertEqual(doc["audio"]["url"], "https://example.invalid/n.mp3")


@unittest.skipUnless(shutil.which("ffmpeg") and HAVE_NUMPY, "needs ffmpeg and numpy")
class InTheRender(unittest.TestCase):
    """do_render boosts after the polish and before the draw, whichever way the video is drawn."""

    def test_the_spread_render_gets_the_boosted_narration_and_no_volume_over_1(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        narration = _voice(os.path.join(work, "narration.wav"))
        doc = {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 300, "meta": {"sceneCount": 1},
               "audio": {"url": narration, "volume": 1.5, "boostDb": 6.02}, "overlays": [], "sfx": [],
               "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 300, "text": "x", "words": [],
                           "media": {"type": "video", "url": "https://pub.example/media/s0.mp4",
                                     "clipSeconds": 10.0}}]}
        seen = {}

        def spread(d, out, **kw):
            seen["audio"] = dict(d["audio"])
            seen["published"] = [p for _m, f, p in fanout.local_refs(d) if f == "url"]
            with open(out, "wb") as fh:
                fh.write(b"final")
            return True

        def report(step, pct=None, **kw):
            pass
        report.job = {"id": "rp-1"}
        with mock.patch.object(handler.fanout, "pod_render_enabled", return_value=True), \
                mock.patch.object(handler.fanout, "render_pod", side_effect=spread), \
                mock.patch.object(handler.timeline, "drop_invalid_overlays"), \
                mock.patch.object(handler.timeline, "validate"), \
                mock.patch.object(handler.timeline, "relevel_to_voice"), \
                mock.patch.object(handler, "_preflight_media", return_value=0), \
                mock.patch.object(handler, "_sanitize_stills"), \
                mock.patch.object(handler, "_sign_supabase_urls"), \
                mock.patch.object(handler.voicepolish, "for_render", return_value={}), \
                mock.patch.object(handler.grade, "prepare", return_value={}), \
                mock.patch.object(handler.ambience, "clean"), \
                mock.patch.object(handler.renderer, "render", side_effect=AssertionError("not on one machine")), \
                mock.patch.object(handler.r2, "enabled", return_value=True), \
                mock.patch.object(config, "QUALITY_SCAN", False), \
                mock.patch.object(handler, "_keep_render"):
            handler.do_render(doc, {"return_video": True, "_job_id": "rp-1"}, work, report, split=True)
        boosted = os.path.join(work, "narration.boosted.flac")
        self.assertEqual(seen["audio"]["url"], boosted)
        self.assertEqual(seen["audio"]["volume"], 1.0)
        self.assertIn(boosted, seen["published"])
        self.assertTrue(doc["meta"]["voiceBoost"]["applied"])


if __name__ == "__main__":
    unittest.main()
