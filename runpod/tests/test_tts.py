"""Script -> narration (src/tts.py): the parts, their order, the join, the price, and the switch in the pipeline.

Offline: every request and (but for one class) every ffmpeg call is a stub.
"""
import base64
import contextlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from src import config, costs, media, pools, sfxplan, tts
from src.media import MediaAsset
from src.transcribe import Segment

SENTENCES = [f"Sentence number {i} tells one more plain fact about the falling lake." for i in range(60)]
SCRIPT = " ".join(SENTENCES)


def configured(**over):
    """The worker's voice settings for one test (an OpenAI-compatible endpoint unless told otherwise)."""
    values = {"TTS_API_BASE": "https://voice.example", "TTS_API_KEY": "k-test-123", "TTS_API_MODE": "auto",
              "TTS_MODEL": "kokoro", "TTS_VOICE": "af_heart", "TTS_SPEED": 1.0, "TTS_REFERENCE_AUDIO": "",
              "TTS_FIELDS": "", "TTS_EXTRA": "", "TTS_FORMAT": "flac", "TTS_OUTPUT_FORMAT": "mp3",
              "TTS_CHUNK_CHARS": 1500, "TTS_WORKERS": 4, "TTS_TIMEOUT": 600.0, "TTS_RETRIES": 3,
              "TTS_GAP_SECONDS": 0.3, "TTS_LUFS": 0.0, "TTS_MAX_CHARS": 120000}
    values.update(over)
    return mock.patch.multiple(config, **values)


class Answer:
    """A requests response, as much of one as the client reads."""

    def __init__(self, status=200, content=b"", data=None, headers=None):
        self.status_code = status
        self.content = content
        self._data = data
        self.headers = headers if headers is not None else ({"Content-Type": "audio/flac"} if content else
                                                           {"Content-Type": "application/json"})
        self.text = "" if data is None else str(data)

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


AUDIO = b"fLaC" + b"\0" * 400


class Chunking(unittest.TestCase):
    def test_parts_end_at_sentence_ends_and_stay_under_the_limit(self):
        parts = tts.chunk_script(SCRIPT, 300)
        self.assertGreater(len(parts), 10)
        self.assertTrue(all(len(p) <= 300 for p in parts))
        self.assertTrue(all(p.endswith(".") for p in parts))
        self.assertTrue(all(p.startswith("Sentence number") for p in parts))     # never cut inside a sentence

    def test_every_word_is_kept_in_order(self):
        for limit in (120, 300, 1500):
            self.assertEqual(" ".join(tts.chunk_script(SCRIPT, limit)), SCRIPT)

    def test_a_twenty_minute_script_is_cut_into_parts_of_at_most_1500_characters(self):
        script = " ".join(SENTENCES * 5)                      # ~20,000 characters, about 20 minutes
        with configured():
            parts = tts.chunk_script(script)
        self.assertTrue(all(len(p) <= 1500 for p in parts))
        self.assertGreaterEqual(len(parts), len(script) // 1500)
        self.assertLessEqual(len(parts), len(script) // 1500 + 2)   # full parts, not a hundred small ones
        self.assertEqual(" ".join(parts), script)

    def test_abbreviations_initials_and_decimals_do_not_end_a_sentence(self):
        got = tts.split_sentences('Dr. Smith of the U.S. Bureau measured 3.5 million acre-feet. "It is gone." '
                                  "Mr. J. Powell agreed at 9 a.m. on Tuesday! Was he right?")
        self.assertEqual(got, ["Dr. Smith of the U.S. Bureau measured 3.5 million acre-feet.", '"It is gone."',
                               "Mr. J. Powell agreed at 9 a.m. on Tuesday!", "Was he right?"])

    def test_an_ellipsis_inside_a_sentence_is_a_pause_not_an_end(self):
        self.assertEqual(tts.split_sentences("Nobody knows... but the numbers are clear. The lake... It is gone."),
                         ["Nobody knows... but the numbers are clear.", "The lake...", "It is gone."])

    def test_a_sentence_longer_than_a_part_is_cut_at_its_commas_then_between_words(self):
        clauses = ", ".join(f"clause {i} runs on about the river and the dam" for i in range(12)) + "."
        parts = tts.chunk_script(clauses, 120)
        self.assertTrue(all(len(p) <= 120 for p in parts))
        self.assertTrue(all(p.endswith((",", ".")) for p in parts))               # cut at commas
        self.assertEqual(" ".join(parts), clauses)
        words = " ".join(["word"] * 100) + "."
        parts = tts.chunk_script(words, 60)
        self.assertTrue(all(len(p) <= 60 for p in parts))
        self.assertEqual(" ".join(parts), words)                                   # no comma: between words

    def test_a_part_closes_at_a_paragraph_end_once_it_is_nearly_full(self):
        a = " ".join(SENTENCES[:3])            # ~200 characters
        b = " ".join(SENTENCES[3:6])
        parts = tts.chunk_script(a + "\n\n" + b, 300)
        self.assertEqual(parts, [a, b])        # 200 of 300 is over PARAGRAPH_FILL: the part ends with the paragraph
        short = SENTENCES[0] + "\n" + SENTENCES[1]
        self.assertEqual(tts.chunk_script(short, 300), [SENTENCES[0] + " " + SENTENCES[1]])

    def test_what_is_never_read_aloud_is_dropped_and_the_words_stay(self):
        script = ("# The Lake That Vanished\n\n[MUSIC: low drone]\nNARRATOR: Lake Mead is **falling** fast "
                  "[B-ROLL: the bathtub ring] .\n\n---\n- First, the _river_\n* Second, see [the report](https://x.example/r)\n")
        clean = tts.clean_script(script)
        self.assertEqual(clean.split("\n"), ["The Lake That Vanished", "Lake Mead is falling fast.",
                                             "First, the river", "Second, see the report"])
        # A line that just stops gets a full stop, so the voice breathes before the next one.
        self.assertEqual(tts.chunk_script(clean, 1500),
                         ["The Lake That Vanished. Lake Mead is falling fast. First, the river. "
                          "Second, see the report."])

    def test_a_script_of_only_directions_has_nothing_to_read(self):
        self.assertEqual(tts.clean_script("[MUSIC]\n\n   \n[FADE OUT]"), "")
        self.assertEqual(tts.chunk_script(""), [])


class Requests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        tts._REF_CACHE.clear()
        self.sleeps = []
        p = mock.patch.object(tts, "_sleep", side_effect=lambda seconds, stop=None: self.sleeps.append(seconds))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(tts, "_seconds", return_value=30.0)
        p.start()
        self.addCleanup(p.stop)

    def part(self, text="A short line.", **opts):
        return tts.voice_part(0, 1, text, os.path.join(self.dir, "part-000"), {**tts.options(), **opts})

    def test_the_openai_request_carries_the_speech_fields_and_the_key(self):
        with configured(), mock.patch.object(tts.requests, "post", return_value=Answer(
                content=AUDIO, headers={"Content-Type": "audio/flac", "X-Gpu-Seconds": "1.5"})) as post:
            got = self.part("Lake Mead is falling.")
        self.assertEqual(post.call_args.args[0], "https://voice.example/v1/audio/speech")
        self.assertEqual(post.call_args.kwargs["json"],
                         {"model": "kokoro", "voice": "af_heart", "input": "Lake Mead is falling.",
                          "response_format": "flac", "speed": 1.0})
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer k-test-123"})
        self.assertEqual(got["path"], os.path.join(self.dir, "part-000.flac"))
        with open(got["path"], "rb") as f:
            self.assertEqual(f.read(), AUDIO)
        self.assertEqual((got["seconds"], got["gpu_seconds"], got["attempts"]), (30.0, 1.5, 1))

    def test_a_base_that_already_ends_in_v1_is_not_doubled(self):
        with configured(TTS_API_BASE="https://voice.example/v1"), \
                mock.patch.object(tts.requests, "post", return_value=Answer(content=AUDIO)) as post:
            self.part()
        self.assertEqual(post.call_args.args[0], "https://voice.example/v1/audio/speech")

    def test_field_names_are_configurable_and_extra_fields_ride_along(self):
        with configured(TTS_REFERENCE_AUDIO="https://files.example/me.wav", TTS_MODEL="chatterbox",
                        TTS_FIELDS='{"reference_audio": "speaker_wav", "input": "text"}',
                        TTS_EXTRA='{"exaggeration": 0.4}'):
            body = tts.request_body("Hello.", tts.options())
        self.assertEqual(body, {"model": "chatterbox", "voice": "af_heart", "text": "Hello.",
                                "response_format": "flac", "speed": 1.0,
                                "speaker_wav": "https://files.example/me.wav", "exaggeration": 0.4})

    def test_a_voice_sample_on_this_disk_is_sent_as_data(self):
        sample = os.path.join(self.dir, "me.wav")
        with open(sample, "wb") as f:
            f.write(b"RIFFsample")
        with configured(TTS_REFERENCE_AUDIO=sample):
            body = tts.request_body("Hello.", tts.options())
        self.assertEqual(body["reference_audio"], "data:audio/wav;base64," + base64.b64encode(b"RIFFsample").decode())
        with configured(TTS_REFERENCE_AUDIO=os.path.join(self.dir, "gone.wav")):
            with self.assertRaises(tts.TtsError) as ctx:
                tts.request_body("Hello.", tts.options())
        self.assertIn("TTS_REFERENCE_AUDIO", str(ctx.exception))

    def test_a_job_picks_its_voice_but_never_a_file_on_the_worker(self):
        with configured(TTS_REFERENCE_AUDIO=""):
            opts = tts.options({"tts_voice": " am_michael ", "tts_model": "chatterbox", "tts_speed": "9",
                                "tts_reference_audio": "/etc/passwd"})
            self.assertEqual((opts["voice"], opts["model"], opts["speed"], opts["reference"]),
                             ("am_michael", "chatterbox", 2.0, ""))
            opts = tts.options({"tts_reference_audio": "https://files.example/owner.wav", "tts_speed": "oops"})
            self.assertEqual((opts["voice"], opts["speed"], opts["reference"]),
                             ("af_heart", 1.0, "https://files.example/owner.wav"))

    def test_a_runpod_address_uses_runsync_and_follows_the_job_until_it_is_done(self):
        b64 = base64.b64encode(AUDIO).decode()
        with configured(TTS_API_BASE="https://api.runpod.ai/v2/abc123"), \
                mock.patch.object(tts.requests, "post", return_value=Answer(
                    data={"id": "sync-1", "status": "IN_QUEUE"})) as post, \
                mock.patch.object(tts.requests, "get", side_effect=[
                    Answer(status=502, data={}), Answer(data={"id": "sync-1", "status": "IN_PROGRESS"}),
                    Answer(data={"id": "sync-1", "status": "COMPLETED", "executionTime": 4200,
                                 "output": {"audio_base64": b64, "format": "flac"}})]) as get:
            self.assertEqual(tts.mode(), "runpod")
            got = self.part("Lake Mead is falling.")
        self.assertEqual(post.call_args.args[0], "https://api.runpod.ai/v2/abc123/runsync")
        self.assertEqual(post.call_args.kwargs["json"]["input"]["input"], "Lake Mead is falling.")
        self.assertEqual([c.args[0] for c in get.call_args_list], ["https://api.runpod.ai/v2/abc123/status/sync-1"] * 3)
        with open(got["path"], "rb") as f:
            self.assertEqual(f.read(), AUDIO)
        self.assertEqual(got["gpu_seconds"], 4.2)                    # RunPod's own execution time
        self.assertEqual(self.sleeps, [tts.POLL_SECONDS] * 3)

    def test_a_request_the_server_can_never_serve_is_not_asked_again(self):
        with configured(TTS_API_BASE="https://api.runpod.ai/v2/abc123"), \
                mock.patch.object(tts.requests, "post", return_value=Answer(
                    data={"id": "s", "status": "COMPLETED", "output": {"refused": "unknown voice 'zz_nobody'"}})) as post:
            with self.assertRaises(tts.TtsError) as ctx:
                self.part()
        self.assertEqual(post.call_count, 1)
        self.assertIn("unknown voice", str(ctx.exception))
        with configured(), mock.patch.object(tts.requests, "post", return_value=Answer(
                status=422, data={"detail": "voice not found"})) as post:
            with self.assertRaises(tts.TtsError) as ctx:
                self.part()
        self.assertEqual(post.call_count, 1)
        self.assertIn("voice not found", str(ctx.exception))

    def test_a_dead_worker_or_a_busy_server_is_asked_again(self):
        b64 = base64.b64encode(AUDIO).decode()
        with configured(TTS_API_BASE="https://api.runpod.ai/v2/abc123"), \
                mock.patch.object(tts.requests, "post", side_effect=[
                    Answer(data={"id": "a", "status": "FAILED", "error": "worker exited"}),
                    Answer(data={"id": "b", "status": "COMPLETED", "output": {"audio_base64": b64}})]):
            self.assertEqual(self.part()["attempts"], 2)
        with configured(), mock.patch.object(tts.requests, "post", side_effect=[
                tts.requests.ConnectionError("reset"), Answer(status=503, data={"error": "loading"}),
                Answer(content=AUDIO)]):
            self.assertEqual(self.part()["attempts"], 3)
        self.assertEqual(self.sleeps, [2.0, 2.0, 8.0])               # backing off between attempts

    def test_a_wrong_key_stops_at_once_and_never_shows_the_key(self):
        with configured(), mock.patch.object(tts.requests, "post", return_value=Answer(
                status=401, data={"error": "unauthorized"})) as post:
            with self.assertRaises(tts.TtsError) as ctx:
                self.part()
        self.assertEqual(post.call_count, 1)
        self.assertIn("TTS_API_KEY", str(ctx.exception))
        self.assertNotIn("k-test-123", str(ctx.exception))

    def test_a_part_that_never_works_fails_by_its_number(self):
        with configured(TTS_RETRIES=2), mock.patch.object(tts.requests, "post", return_value=Answer(
                status=500, data={"error": "CUDA out of memory"})) as post:
            with self.assertRaises(tts.TtsError) as ctx:
                tts.voice_part(4, 9, "A short line.", os.path.join(self.dir, "part-004"), tts.options())
        self.assertEqual(post.call_count, 3)
        self.assertIn("part 5 of 9", str(ctx.exception))
        self.assertIn("CUDA out of memory", str(ctx.exception))

    def test_audio_far_too_short_for_its_text_is_a_voice_that_stopped_early(self):
        text = " ".join(SENTENCES[:10])                               # ~680 characters: 40+ s spoken
        self.assertGreater(tts.least_seconds(text), 20.0)
        self.assertEqual(tts.least_seconds("Yes."), 0.0)              # too short to judge
        with configured(TTS_RETRIES=1), mock.patch.object(tts, "_seconds", side_effect=[4.0, 44.0]), \
                mock.patch.object(tts.requests, "post", return_value=Answer(content=AUDIO)) as post:
            got = self.part(text)
        self.assertEqual((post.call_count, got["attempts"], got["seconds"]), (2, 2, 44.0))
        with configured(TTS_RETRIES=1), mock.patch.object(tts, "_seconds", return_value=4.0), \
                mock.patch.object(tts.requests, "post", return_value=Answer(content=AUDIO)):
            with self.assertRaises(tts.TtsError) as ctx:
                self.part(text)
        self.assertIn("stopped early", str(ctx.exception))

    def test_an_error_page_instead_of_audio_is_not_saved_as_a_narration(self):
        with configured(TTS_RETRIES=0), mock.patch.object(tts.requests, "post", return_value=Answer(
                content=b"<html>" + b"x" * 300, headers={"Content-Type": "text/html"})):
            with self.assertRaises(tts.TtsError) as ctx:
                self.part()
        self.assertIn("without audio", str(ctx.exception))

    def test_a_runpod_job_that_outlives_its_time_is_cancelled(self):
        with configured(TTS_API_BASE="https://api.runpod.ai/v2/abc123", TTS_RETRIES=0, TTS_TIMEOUT=0.0), \
                mock.patch.object(tts.requests, "post", return_value=Answer(
                    data={"id": "slow-1", "status": "IN_QUEUE"})) as post:
            with self.assertRaises(tts.TtsError):
                self.part()
        self.assertEqual([c.args[0] for c in post.call_args_list],
                         ["https://api.runpod.ai/v2/abc123/runsync", "https://api.runpod.ai/v2/abc123/cancel/slow-1"])

    def test_no_attempt_waits_longer_than_the_narration_has_left(self):
        with configured(TTS_TIMEOUT=600.0), mock.patch.object(tts.requests, "post", return_value=Answer(
                content=AUDIO)) as post:
            tts.voice_part(0, 1, "A short line.", os.path.join(self.dir, "part-000"), tts.options(),
                           deadline=time.time() + 100.0)
        read_timeout = post.call_args.kwargs["timeout"][1]
        self.assertLessEqual(read_timeout, 100.0)                     # what is left, not TTS_TIMEOUT
        self.assertGreater(read_timeout, 90.0)
        # Backing off never sleeps past the narration's end.
        with configured(TTS_RETRIES=2), mock.patch.object(tts.requests, "post", return_value=Answer(
                status=503, data={"error": "loading"})):
            with self.assertRaises(tts.TtsError):
                tts.voice_part(0, 1, "A short line.", os.path.join(self.dir, "part-000"), tts.options(),
                               deadline=time.time() + 6.0)
        self.assertEqual(self.sleeps[0], 2.0)
        self.assertLessEqual(self.sleeps[1], 5.0)                     # not the 8 s of the second back-off
        self.assertGreater(self.sleeps[1], 4.0)
        # Nothing left: the part is not even asked for.
        with configured(), mock.patch.object(tts.requests, "post") as post:
            with self.assertRaises(tts.TtsError) as ctx:
                tts.voice_part(2, 9, "A short line.", os.path.join(self.dir, "part-002"), tts.options(),
                               deadline=time.time() + 0.5)
        post.assert_not_called()
        self.assertIn("part 3 of 9 was not voiced in time", str(ctx.exception))

    def test_a_raw_pcm_answer_is_never_asked_for(self):
        with configured(TTS_FORMAT="pcm"):
            self.assertEqual(tts.options()["format"], "flac")      # pcm has no header: its length cannot be measured
        with configured(TTS_FORMAT="mp3"):
            self.assertEqual(tts.options()["format"], "mp3")


class WholeNarration(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        costs.reset()

    def _join(self, seen):
        def join(parts, dest, **kw):
            seen["joined"] = list(parts)
            with open(dest, "wb") as f:
                for p in parts:
                    with open(p, "rb") as src:
                        f.write(src.read())
            return {"path": dest, "seconds": 1200.0, "parts": len(parts), "targetLufs": -20.0, "gainDb": 2.5,
                    "lufs": -20.0, "peakDb": -4.0, "sourceLufs": -22.5}
        return join

    def test_parts_are_voiced_four_at_a_time_and_joined_in_script_order(self):
        script = " ".join(SENTENCES)                      # 60 sentences
        lock, live, peak, seen = threading.Lock(), [0], [0], {}

        def post(url, json=None, **kw):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            n = int(json["input"].split("Sentence number ")[1].split(" ")[0])
            time.sleep(0.03 if n < 20 else 0.0)           # the first parts answer LAST
            with lock:
                live[0] -= 1
            return Answer(content=json["input"].encode() + b"|" + b"\0" * 64)
        progress = []
        with configured(TTS_CHUNK_CHARS=300), mock.patch.object(tts.requests, "post", side_effect=post), \
                mock.patch.object(tts, "_seconds", return_value=20.0), \
                mock.patch.object(tts, "join", side_effect=self._join(seen)):
            out = tts.synthesize(script, self.dir, on_progress=lambda d, t: progress.append((d, t)))
        chunks = tts.chunk_script(script, 300)
        self.assertGreater(len(chunks), 8)
        self.assertEqual(seen["joined"], [os.path.join(self.dir, f"part-{i:03d}.flac") for i in range(len(chunks))])
        with open(out["path"], "rb") as f:
            said = [p.decode() for p in f.read().replace(b"\0", b"").split(b"|") if p]
        self.assertEqual(said, chunks)                    # the audio follows the script, not the finish order
        self.assertEqual(out["text"], script)
        self.assertLessEqual(peak[0], 4)
        self.assertGreaterEqual(peak[0], 2)
        self.assertEqual(progress[-1], (len(chunks), len(chunks)))
        self.assertEqual([d for d, _ in progress], list(range(1, len(chunks) + 1)))
        self.assertEqual((out["parts"], out["chars"], out["voice"], out["model"], out["cloned"]),
                         (len(chunks), len(script), "af_heart", "kokoro", False))

    def test_the_narration_is_counted_in_seconds_and_priced_as_tts(self):
        seen = {}
        with configured(), mock.patch.object(tts.requests, "post", return_value=Answer(
                content=AUDIO, headers={"Content-Type": "audio/flac", "X-Gpu-Seconds": "6.5"})), \
                mock.patch.object(tts, "_seconds", return_value=100.0), \
                mock.patch.object(tts, "join", side_effect=self._join(seen)):
            out = tts.synthesize(" ".join(SENTENCES * 2), self.dir)
        s = costs.summary(worker_seconds=0)
        self.assertEqual(s["units"]["tts.seconds"], 1200)                       # the joined narration's length
        self.assertEqual(s["units"]["tts.gpu_seconds"], 6.5 * out["parts"])     # what the endpoint reported
        self.assertAlmostEqual(s["tts"], 1200 * costs.DEFAULT_PRICES["tts.seconds"], places=4)
        self.assertLess(s["tts"], 0.10)                                         # cents, not dollars
        self.assertEqual(s["total"], s["tts"])
        costs.reset({"tts.seconds": 0.0002})                                    # the app's price table wins
        costs.record("tts.seconds", 1200)
        self.assertAlmostEqual(costs.summary(worker_seconds=0)["tts"], 0.24)

    def test_without_an_endpoint_a_script_is_refused_in_plain_words_and_nothing_is_called(self):
        with configured(TTS_API_BASE=""), mock.patch.object(tts.requests, "post") as post:
            self.assertFalse(tts.configured())
            self.assertEqual(tts.status(), {"configured": False})
            with self.assertRaises(tts.NotConfigured) as ctx:
                tts.synthesize(SCRIPT, self.dir)
        post.assert_not_called()
        self.assertIn("TTS_API_BASE", str(ctx.exception))
        self.assertIn("free voice is not set up", str(ctx.exception))
        self.assertEqual(costs.summary(0)["units"], {})

    def test_one_part_that_cannot_be_voiced_fails_the_whole_narration(self):
        def post(url, json=None, **kw):
            if "number 30 " in json["input"]:
                return Answer(status=400, data={"error": {"message": "text rejected"}})
            return Answer(content=AUDIO)
        with configured(TTS_CHUNK_CHARS=300), mock.patch.object(tts.requests, "post", side_effect=post), \
                mock.patch.object(tts, "_seconds", return_value=20.0), \
                mock.patch.object(tts, "join") as join:
            with self.assertRaises(tts.TtsError) as ctx:
                tts.synthesize(SCRIPT, self.dir)
        join.assert_not_called()                          # never a narration with a hole in it
        self.assertIn("text rejected", str(ctx.exception))
        self.assertNotIn("tts.seconds", costs.summary(0)["units"])

    def test_an_empty_or_endless_script_is_refused_before_any_request(self):
        with configured(TTS_MAX_CHARS=500), mock.patch.object(tts.requests, "post") as post:
            with self.assertRaises(tts.TtsError) as empty:
                tts.synthesize("[MUSIC]\n", self.dir)
            with self.assertRaises(tts.TtsError) as endless:
                tts.synthesize(SCRIPT, self.dir)
        post.assert_not_called()
        self.assertIn("no words", str(empty.exception))
        self.assertIn("TTS_MAX_CHARS", str(endless.exception))

    def test_a_narration_that_outlives_its_time_stops_in_plain_words_and_cancels_its_jobs(self):
        """No GPU ever takes the jobs: the whole narration stops at TTS_TOTAL_SECONDS, not 4 x 600 s per part."""
        lock, asked, cancelled = threading.Lock(), [], []

        def post(url, json=None, **kw):
            with lock:
                if "/cancel/" in url:
                    cancelled.append(url.rsplit("/", 1)[1])
                    return Answer(data={"status": "CANCELLED"})
                asked.append(f"job-{len(asked)}")
                return Answer(data={"id": asked[-1], "status": "IN_QUEUE"})

        def get(url, **kw):
            return Answer(data={"id": url.rsplit("/", 1)[1], "status": "IN_QUEUE"})

        def tts_threads():
            return [t for t in threading.enumerate() if t.name.startswith("tts")]
        progress = []
        with configured(TTS_API_BASE="https://api.runpod.ai/v2/abc123", TTS_CHUNK_CHARS=300,
                        TTS_TOTAL_SECONDS=1.5), \
                mock.patch.object(tts, "POLL_SECONDS", 0.05), \
                mock.patch.object(tts.requests, "post", side_effect=post), \
                mock.patch.object(tts.requests, "get", side_effect=get), \
                mock.patch.object(tts, "join") as join:
            started = time.time()
            with self.assertRaises(tts.TtsError) as ctx:
                tts.synthesize(SCRIPT, self.dir, on_progress=lambda d, t: progress.append(d))
            took = time.time() - started
            # The parts still running see the narration given up and cancel their jobs;
            # none may outlive the stubs.
            until = time.time() + 10
            while time.time() < until and (tts_threads() or sorted(cancelled) != sorted(asked)):
                time.sleep(0.02)
        self.assertEqual(tts_threads(), [])
        join.assert_not_called()
        self.assertLess(took, 5.0)
        self.assertIn("did not finish the narration in time", str(ctx.exception))
        self.assertIn(f"0 of {len(tts.chunk_script(SCRIPT, 300))} parts", str(ctx.exception))
        self.assertIn("TTS_TOTAL_SECONDS", str(ctx.exception))
        self.assertNotIn("abc123", str(ctx.exception))
        self.assertEqual(progress, [])
        self.assertTrue(asked)
        self.assertLessEqual(len(asked), 4)                           # TTS_WORKERS at once, nothing queued after
        self.assertEqual(sorted(cancelled), sorted(asked))            # no GPU job is left behind
        self.assertNotIn("tts.seconds", costs.summary(0)["units"])

    def test_the_health_check_says_what_voice_is_ready_but_not_where_or_the_key(self):
        with configured(TTS_API_BASE="https://api.runpod.ai/v2/abc123"):
            got = tts.status()
        self.assertEqual(got, {"configured": True, "mode": "runpod", "model": "kokoro", "voice": "af_heart",
                               "key": True, "cloning": False})
        self.assertNotIn("abc123", str(got))
        self.assertNotIn("k-test-123", str(got))


class Join(unittest.TestCase):
    """The join with ffmpeg stubbed: what it is asked to do, in which order."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.calls, self.listing = [], []

    def run_ffmpeg(self, argv, timeout):
        self.calls.append(list(argv))
        if "concat" in argv:
            with open(argv[argv.index("-i") + 1], encoding="utf-8") as f:
                self.listing = f.read().splitlines()
        return subprocess.CompletedProcess(argv, 0, "", "")

    def join(self, parts, loud, **kw):
        dest = os.path.join(self.dir, "narration.mp3")
        with configured(**kw), mock.patch.object(tts, "_run", side_effect=self.run_ffmpeg), \
                mock.patch.object(tts, "_loudness", side_effect=loud), \
                mock.patch.object(tts, "_seconds", return_value=61.0):
            return tts.join(parts, dest)

    def test_the_parts_are_joined_in_order_with_a_breath_between_them(self):
        parts = [os.path.join(self.dir, f"part-{i:03d}.flac") for i in range(3)]
        out = self.join(parts, [{"lufs": -24.5, "tp": -9.0}, {"lufs": -20.0, "tp": -4.5}])
        evened = self.calls[:3]
        self.assertEqual([c[c.index("-i") + 1] for c in evened], parts)            # each part, in script order
        self.assertTrue(all(f"aresample={tts.JOIN_RATE}" in c[c.index("-af") + 1] for c in evened))
        self.assertTrue(all("channel_layouts=mono" in c[c.index("-af") + 1] for c in evened))
        self.assertEqual(["apad=pad_dur=0.300" in c[c.index("-af") + 1] for c in evened], [True, True, False])
        stem = os.path.join(self.dir, "narration").replace("\\", "/")
        self.assertEqual(self.listing, [f"file '{stem}.part{i:03d}.wav'" for i in range(3)])   # the join's own order
        self.assertEqual(self.calls[3][self.calls[3].index("-f") + 1], "concat")
        self.assertEqual(out["parts"], 3)
        self.assertEqual(out["seconds"], 61.0)

    def test_the_narration_is_brought_to_the_workers_voice_level_with_one_steady_gain(self):
        out = self.join(["a.flac", "b.flac"], [{"lufs": -24.5, "tp": -9.0}, {"lufs": -20.05, "tp": -4.6}])
        write = self.calls[-1]
        self.assertEqual(write[write.index("-af") + 1], "volume=4.50dB")           # -24.5 -> -20, nothing else
        self.assertEqual(write[write.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(len(self.calls), 4)                                       # 2 parts, the join, ONE write
        self.assertEqual((out["targetLufs"], out["gainDb"], out["lufs"], out["sourceLufs"]),
                         (sfxplan.VOICE_LUFS_DEFAULT, 4.5, -20.05, -24.5))
        out = self.join(["a.flac"], [{"lufs": -16.0, "tp": -2.0}, {"lufs": -23.0, "tp": -9.0}], TTS_LUFS=-23.0)
        self.assertEqual(self.calls[-1][self.calls[-1].index("-af") + 1], "volume=-7.00dB")   # a job's own target

    def test_a_file_the_encoder_wrote_too_quiet_is_written_once_more(self):
        out = self.join(["a.flac"], [{"lufs": -24.5, "tp": -9.0}, {"lufs": -20.5, "tp": -5.0},
                                     {"lufs": -20.0, "tp": -4.5}])
        writes = [c[c.index("-af") + 1] for c in self.calls if "libmp3lame" in c]
        self.assertEqual(writes, ["volume=4.50dB", "volume=5.00dB"])
        self.assertEqual((out["gainDb"], out["lufs"]), (5.0, -20.0))

    def test_the_gain_never_lifts_a_peak_into_clipping_and_silence_is_left_alone(self):
        self.assertEqual(tts.steady_gain(-30.0, -4.0, -20.0), 3.0)                 # held by the peak, not +10
        self.assertEqual(tts.steady_gain(-18.0, -1.0, -20.0), -2.0)
        self.assertEqual(tts.steady_gain(None, None, -20.0), 0.0)
        self.assertEqual(tts.steady_gain(-200.0, -200.0, -20.0), 0.0)
        out = self.join(["a.flac"], [{"lufs": None, "tp": None}, {"lufs": None, "tp": None}])
        self.assertEqual(out["gainDb"], 0.0)
        self.assertEqual(len([c for c in self.calls if "libmp3lame" in c]), 1)

    def test_an_ffmpeg_failure_is_a_plain_error_and_leaves_nothing_behind(self):
        def broken(argv, timeout):
            return subprocess.CompletedProcess(argv, 1, "", "Invalid data found when processing input")
        with configured(), mock.patch.object(tts, "_run", side_effect=broken):
            with self.assertRaises(tts.TtsError) as ctx:
                tts.join(["a.flac"], os.path.join(self.dir, "narration.mp3"))
        self.assertIn("read part 1", str(ctx.exception))
        self.assertEqual(os.listdir(self.dir), [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class RealJoin(unittest.TestCase):
    """The same join with the real ffmpeg, on generated tones (no network)."""

    def test_three_parts_become_one_narration_at_the_voice_level(self):
        from src import voicepolish
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        parts = []
        for name, hz, seconds, rate, ch, db in (("a.flac", 220, 3.0, 24000, 1, 6), ("b.flac", 330, 2.0, 24000, 1, -4),
                                                ("c.wav", 440, 1.5, 22050, 2, 0)):
            path = os.path.join(d, name)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"sine=frequency={hz}:duration={seconds}:sample_rate={rate}", "-af", f"volume={db}dB",
                            "-ac", str(ch), path], check=True)
            parts.append(path)
        with configured():
            out = tts.join(parts, os.path.join(d, "narration.mp3"))
        info = voicepolish.probe(out["path"])
        self.assertEqual((info["codec"], info["rate"], info["channels"]), ("mp3", 44100, 1))
        self.assertAlmostEqual(info["seconds"], 3.0 + 2.0 + 1.5 + 2 * 0.3, delta=0.15)     # the parts and two breaths
        self.assertAlmostEqual(voicepolish.loudness(out["path"])["lufs"], sfxplan.VOICE_LUFS_DEFAULT, delta=0.5)
        self.assertAlmostEqual(out["lufs"], sfxplan.VOICE_LUFS_DEFAULT, delta=0.5)
        self.assertEqual(sorted(os.listdir(d)), ["a.flac", "b.flac", "c.wav", "narration.mp3"])


def yt(vid: str, start: float) -> MediaAsset:
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                      local_path=f"/w/{vid}_{int(start)}.mp4", moment_key=f"yt:{vid}@{int(start // 8)}",
                      moment={"start": float(start)})


BRIEF = {"kind": "explainer", "summary": "", "event": "Lake Mead drops", "year": 2026, "recent": False,
         "places": ["Lake Mead"], "people": [], "hookBeats": [0], "cast": [], "sections": []}


class Stop(Exception):
    pass


class PipelineSwitch(unittest.TestCase):
    """handler.do_plan: a script and no voice-over -> the narration is made first, then nothing changes."""

    def setUp(self):
        import handler
        self.handler = handler
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.steps = steps = []

        class Recorder(handler.Reporter):
            def __call__(self, step, progress=None, **kw):
                steps.append(step)
                return super().__call__(step, progress, **kw)
        self.report = Recorder("")

    def synthesize(self, script, work, opts=None, on_progress=None):
        self.asked = {"script": script, "opts": opts}
        os.makedirs(work, exist_ok=True)
        path = os.path.join(work, "narration.mp3")
        with open(path, "wb") as f:
            f.write(b"ID3made")
        for done in (1, 2):
            on_progress(done, 2)
        return {"path": path, "text": "Lake Mead is falling. Nobody knows why.", "seconds": 1200.0, "chars": 39,
                "parts": 2, "voice": opts["voice"], "model": opts["model"], "speed": opts["speed"],
                "cloned": False, "lufs": -20.0, "gainDb": 1.5, "peakDb": -4.0, "retries": 0, "gpuSeconds": 21.0,
                "tookSeconds": 30.0, "mode": "runpod"}

    def test_a_script_only_job_gets_its_narration_made_stored_and_handed_on_as_a_normal_audio_url(self):
        h = self.handler
        inp = {"script": "[MUSIC]\nLake Mead is falling. Nobody knows why.", "project_id": "proj-1",
               "_job_id": "job-1", "tts_voice": "am_michael"}
        seen = {}

        def transcribe_words(path, language=None, on_progress=None):
            with open(path, "rb") as f:
                seen["audio"] = (path, f.read())
            raise Stop()
        with configured(), mock.patch.object(h.tts, "synthesize", side_effect=self.synthesize), \
                mock.patch.object(h.r2, "enabled", return_value=True), \
                mock.patch.object(h.r2, "upload", return_value="https://pub.example/projects/proj-1/audio/narration-abc.mp3") as up, \
                mock.patch.object(h.storage, "patch_project") as patch, \
                mock.patch.object(h.storage, "download", side_effect=AssertionError("nothing to download")), \
                mock.patch.object(h.storage, "resolve_audio", side_effect=AssertionError("nothing to resolve")), \
                mock.patch.object(h.renderer, "probe_duration", return_value=1200.0), \
                mock.patch.object(h.transcribe, "transcribe_words", side_effect=transcribe_words):
            with self.assertRaises(Stop):
                h.do_plan(inp, self.work, self.report)
        self.assertEqual(self.asked["script"], "[MUSIC]\nLake Mead is falling. Nobody knows why.")
        self.assertEqual(self.asked["opts"]["voice"], "am_michael")
        # Whisper reads the made file, from the place a downloaded narration lands.
        self.assertEqual(seen["audio"], (os.path.join(self.work, "narration.mp3"), b"ID3made"))
        self.assertEqual(inp["audio_url"], "https://pub.example/projects/proj-1/audio/narration-abc.mp3")
        self.assertEqual(inp["script"], "Lake Mead is falling. Nobody knows why.")   # the captions: as voiced
        key = up.call_args.args[1]
        self.assertRegex(key, r"^projects/proj-1/audio/narration-[0-9a-f]{12}\.mp3$")   # link-only, in the project
        self.assertEqual(up.call_args.kwargs["content_type"], "audio/mpeg")
        patch.assert_called_once_with("proj-1", {"audio_url": inp["audio_url"]})     # the app's row learns the link
        self.assertEqual(self.steps[0], "Making the narration (free voice)")
        self.assertIn("Making the narration (free voice): part 2 of 2", self.steps)
        self.assertNotIn("Downloading narration", self.steps)
        self.assertEqual(self.steps[-1], "Aligning narration")

    def test_the_timeline_carries_the_stored_narration_and_says_how_it_was_made(self):
        h = self.handler
        segs = [Segment(f"line {i}", s, s + 5) for i, s in enumerate((0, 5, 10))]
        shots = [{"query": f"Lake Mead {i}", "visualType": "footage", "subject": "Lake Mead", "subjectType": "place",
                  "intent": "Lake Mead", "fallbacks": []} for i in range(3)]
        seen = {}

        def build(segments, shots_, assets, **kw):
            seen.update(kw)
            raise Stop()
        inp = {"script": "Lake Mead is falling. Nobody knows why.", "project_id": "", "_job_id": "job-2"}
        url = "https://pub.example/jobs/job-2/audio/narration-abc.mp3"
        with contextlib.ExitStack() as stack:
            for patch in (
                    configured(), mock.patch.object(h.tts, "synthesize", side_effect=self.synthesize),
                    mock.patch.object(h.r2, "enabled", return_value=True),
                    mock.patch.object(h.r2, "upload", return_value=url),
                    mock.patch.object(h.renderer, "probe_duration", return_value=15.0),
                    mock.patch.object(h.transcribe, "transcribe_words", return_value=[object()]),
                    mock.patch.object(h.transcribe, "segment_words", return_value=segs),
                    mock.patch.object(h.director, "story_brief", return_value=dict(BRIEF)),
                    mock.patch.object(h.director, "plan", return_value=(shots, "ai", [])),
                    mock.patch.object(h.library.Library, "load", return_value=None),
                    mock.patch.object(h.fanout, "enabled_for", return_value=False),
                    mock.patch.object(pools, "source_by_subject", return_value={}),
                    mock.patch.object(pools, "fill_from_reserve", return_value={}),
                    mock.patch.object(media, "source_many",
                                      return_value=[yt(f"VIDEO00000{k}", 10.0) for k in range(3)]),
                    mock.patch.object(media, "rescue_fill", return_value={}),
                    mock.patch.object(h.gapfill, "fill_empty", return_value={}),
                    mock.patch.object(h.timeline, "build", side_effect=build),
                    mock.patch.object(config, "UPSCALE_ENABLED", False),
                    mock.patch.object(config, "ALLOW_VERTICAL", False),
                    mock.patch.object(config, "SUBJECT_POOLS", True)):
                stack.enter_context(patch)
            align = stack.enter_context(
                mock.patch.object(h.transcribe, "align_to_script", side_effect=lambda s, script: s))
            try:
                with self.assertRaises(Stop):
                    h.do_plan(inp, self.work, self.report)
            finally:
                media.set_youtube_only(False)
                h.vision.set_story({})
        self.assertEqual(seen["audio_url"], url)                                    # a normal narration link
        self.assertEqual(seen["narration_path"], os.path.join(self.work, "narration.mp3"))
        self.assertEqual(seen["audio_duration"], 15.0)
        self.assertEqual(align.call_args.args[1], "Lake Mead is falling. Nobody knows why.")
        doc = {"meta": {"audioSource": url, "narration": {"source": "tts", "voice": "af_heart", "seconds": 1200.0}}}
        self.assertEqual(h._narration_fields(doc), {"narration": doc["meta"]["narration"], "audio_url": url})
        self.assertEqual(h._narration_fields({"meta": {"audioSource": url}}), {})    # an uploaded voice-over

    def test_without_the_free_voice_a_script_only_job_fails_exactly_as_before(self):
        h = self.handler
        inp = {"script": "Lake Mead is falling.", "project_id": "proj-1", "_job_id": "job-1"}
        with configured(TTS_API_BASE=""), mock.patch.object(h.tts.requests, "post") as post, \
                mock.patch.object(h.tts, "synthesize", side_effect=AssertionError("the free voice is off")), \
                mock.patch.object(h.tts, "options", side_effect=AssertionError("the free voice is off")), \
                mock.patch.object(h.storage, "patch_project") as patch, \
                mock.patch.object(h.events, "phase") as phase:
            with self.assertRaises(ValueError) as ctx:
                h.do_plan(dict(inp), self.work, self.report)
        # The base worker's own error, type and words, before anything else happened.
        self.assertEqual(type(ctx.exception), ValueError)
        self.assertEqual(str(ctx.exception), "audio_url is required (upload a voiceover or generate TTS first)")
        post.assert_not_called()
        patch.assert_not_called()
        phase.assert_not_called()
        self.assertEqual(self.steps, [])                                             # no "Making the narration"
        self.assertEqual(os.listdir(self.work), [])
        with configured():
            with self.assertRaises(ValueError) as ctx:                               # no script either: as before
                h.do_plan({"project_id": ""}, self.work, self.report)
        self.assertIn("audio_url is required", str(ctx.exception))

    def test_a_job_with_a_voice_over_never_touches_the_free_voice(self):
        h = self.handler
        with configured(), mock.patch.object(h.tts, "synthesize", side_effect=AssertionError("not asked for")), \
                mock.patch.object(h.storage, "resolve_audio", return_value="https://x/vo.mp3"), \
                mock.patch.object(h.storage, "download", return_value="/w/vo.mp3") as download, \
                mock.patch.object(h.renderer, "probe_duration", return_value=30.0), \
                mock.patch.object(h.transcribe, "transcribe_words", side_effect=Stop()):
            with self.assertRaises(Stop):
                h.do_plan({"audio_url": "vo.mp3", "script": "Lake Mead is falling.", "project_id": ""},
                          self.work, self.report)
        download.assert_called_once()
        self.assertEqual(self.steps[0], "Downloading narration")

    def test_where_the_narration_is_kept(self):
        h = self.handler
        local = os.path.join(self.work, "narration.mp3")
        with open(local, "wb") as f:
            f.write(b"ID3")
        inp = {"project_id": "proj-1", "_job_id": "job-1"}
        # Cloudflare only (the default): an R2 failure is an error, never the app's storage.
        with mock.patch.object(h.r2, "enabled", return_value=True), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(h.r2, "upload", side_effect=RuntimeError("R2 upload failed")), \
                mock.patch.object(h.storage, "broker_upload") as broker:
            with self.assertRaises(RuntimeError):
                h._store_narration(local, ".mp3", inp)
        broker.assert_not_called()
        # No R2: the app's storage, inside the project's folder.
        with mock.patch.object(h.r2, "enabled", return_value=False), \
                mock.patch.object(h.storage, "broker_enabled", return_value=True), \
                mock.patch.object(h.storage, "broker_upload", return_value="https://sb.example/signed") as broker:
            self.assertEqual(h._store_narration(local, ".mp3", inp), "https://sb.example/signed")
        self.assertEqual(broker.call_args.args[:5], (local, config.MEDIA_BUCKET, "projects/proj-1/audio/narration.mp3",
                                                     "proj-1", "job-1"))
        # No storage at all (a local run): the file stays where it is.
        with mock.patch.object(h.r2, "enabled", return_value=False), \
                mock.patch.object(h.storage, "broker_enabled", return_value=False), \
                mock.patch.object(config, "SUPABASE_SERVICE_KEY", ""):
            self.assertEqual(h._store_narration(local, ".mp3", inp), "")

    def test_the_progress_line_belongs_to_the_narration_phase(self):
        h = self.handler
        rep = h.Reporter("")
        rep("Making the narration (free voice): part 3 of 12", 3)
        self.assertEqual(rep._phase, "narration")
        self.assertEqual(h._AGENT_BY_PHASE[rep._phase], "voice")


if __name__ == "__main__":
    unittest.main()
