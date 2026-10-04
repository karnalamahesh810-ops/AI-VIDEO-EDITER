"""The voice endpoint (runpod/tts_server): its request handling with the models faked - no torch, no download.

The endpoint is its own image; this folder is not in the video worker's image, so there these tests skip.
"""
import base64
import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
import wave
from unittest import mock

import warnings

from src import config, costs, sfxplan, tts

try:
    import numpy as np
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")             # the test client's own deprecation notes
        from fastapi.testclient import TestClient
    from tts_server import engines, fetch_models, rp_handler, server
    READY = True
except ImportError:                                 # the worker image: no tts_server folder
    READY = False

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def tone(seconds=1.0, rate=24000):
    t = np.arange(int(seconds * rate)) / rate
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnframes() / w.getframerate()


@unittest.skipUnless(READY, "needs numpy, fastapi and the tts_server folder")
class Base(unittest.TestCase):
    def setUp(self):
        self.said = []

        def kokoro(text, voice, speed):
            self.said.append({"text": text, "voice": voice, "speed": speed})
            names = engines.KOKORO.resolve(voice)
            # A short line: 2 s. A long part: as long as a narrator would take (15 characters a second).
            return tone(2.0 if len(text) < 60 else len(text) / 15.0), 24000, ",".join(names)
        for target, name, value in ((engines.KOKORO, "synthesize", kokoro),
                                    (engines.KOKORO, "voices", lambda: ["af_heart", "af_bella", "am_michael",
                                                                        "am_onyx", "bm_george"])):
            p = mock.patch.object(target, name, side_effect=value)
            p.start()
            self.addCleanup(p.stop)


class Speak(Base):
    def test_a_speech_request_comes_back_as_a_complete_file_with_its_length(self):
        out = engines.speak({"model": "kokoro", "voice": "am_michael", "input": " Lake Mead is falling. ",
                             "response_format": "wav", "speed": 1.1})
        self.assertEqual(self.said, [{"text": "Lake Mead is falling.", "voice": "am_michael", "speed": 1.1}])
        self.assertEqual((out["content_type"], out["format"], out["seconds"], out["sample_rate"]),
                         ("audio/wav", "wav", 2.0, 24000))
        self.assertEqual((out["model"], out["voice"]), ("kokoro", "am_michael"))
        self.assertAlmostEqual(wav_seconds(out["audio"]), 2.0, places=3)
        self.assertGreaterEqual(out["gpu_seconds"], 0.0)

    def test_openai_names_work_and_voices_can_be_blended(self):
        self.assertEqual(engines.speak({"model": "tts-1", "voice": "onyx", "input": "Hi.",
                                        "response_format": "pcm"})["voice"], "am_onyx")
        self.assertEqual(engines.speak({"voice": "af_heart, af_bella", "input": "Hi.",
                                        "response_format": "pcm"})["voice"], "af_heart,af_bella")
        self.assertEqual(engines.speak({"input": "Hi.", "response_format": "pcm"})["voice"], engines.DEFAULT_VOICE)

    def test_what_can_never_work_is_refused_not_failed(self):
        for req, why in (({"input": "  "}, "nothing to say"),
                         ({"input": "Hi.", "model": "gpt-voice"}, "unknown model"),
                         ({"input": "Hi.", "response_format": "exe"}, "not supported"),
                         ({"input": "Hi.", "voice": "zz_nobody"}, "unknown voice"),
                         ({"input": "Hi.", "voice": "../../etc/passwd"}, "unknown voice"),
                         ({"input": "Hi.", "voice": "af_heart,af_bella,am_michael,am_onyx,bm_george"}, "at most 4"),
                         ({"input": "Hi.", "voice": "af_heart," * 5000}, "blend up to 4"),
                         ({"input": "x" * (engines.MAX_INPUT_CHARS + 1)}, "one request takes up to"),
                         ({"input": "Hi.", "reference_audio": "https://x.example/me.wav"}, "needs model 'chatterbox'"),
                         ("not a dict", "JSON object")):
            with self.assertRaises(engines.Refused, msg=str(req)[:60]) as ctx:
                engines.speak(req)
            self.assertIn(why, str(ctx.exception))

    def test_chatterbox_is_behind_its_flag(self):
        with mock.patch.dict(os.environ, {"WITH_CHATTERBOX": "0"}):
            self.assertFalse(engines.chatterbox_enabled())
            with self.assertRaises(engines.Refused) as ctx:
                engines.speak({"model": "chatterbox", "input": "Hi."})
        self.assertIn("WITH_CHATTERBOX=1", str(ctx.exception))
        # The flag alone is not enough: the weights have to be in the image.
        with mock.patch.dict(os.environ, {"WITH_CHATTERBOX": "1"}), \
                mock.patch.object(engines, "CHATTERBOX_DIR", tempfile.gettempdir()):
            self.assertFalse(engines.chatterbox_enabled())

    def test_chatterbox_gets_the_sample_its_dials_and_speed_by_time_stretch(self):
        seen = {}

        def chatterbox(text, reference, exaggeration, cfg_weight, temperature):
            seen.update(text=text, reference=reference, exaggeration=exaggeration, cfg_weight=cfg_weight,
                        temperature=temperature)
            return tone(2.0), 24000, "cloned"
        with mock.patch.object(engines, "chatterbox_enabled", return_value=True), \
                mock.patch.object(engines, "reference_file", return_value="/tmp/tts_refs/abc.wav") as ref, \
                mock.patch.object(engines.CHATTERBOX, "synthesize", side_effect=chatterbox), \
                mock.patch.object(engines, "encode", return_value=(b"audio", "audio/flac")) as enc:
            out = engines.speak({"model": "chatterbox", "input": "Hi there.", "response_format": "flac",
                                 "reference_audio": "https://x.example/me.wav", "exaggeration": 9, "speed": 1.25})
        ref.assert_called_once_with("https://x.example/me.wav")
        self.assertEqual(seen, {"text": "Hi there.", "reference": "/tmp/tts_refs/abc.wav", "exaggeration": 2.0,
                                "cfg_weight": 0.5, "temperature": 0.8})          # dials clamped / defaulted
        self.assertEqual(enc.call_args.args[2:], ("flac", 1.25))                 # speed = tempo at the encode
        self.assertEqual((out["voice"], out["model"], out["seconds"]), ("cloned", "chatterbox", 1.6))


@unittest.skipUnless(READY, "needs numpy, fastapi and the tts_server folder")
class Pieces(unittest.TestCase):
    def test_long_text_is_voiced_in_short_whole_sentences(self):
        text = " ".join(f"Sentence {i} says something plain about Dr. Smith and the U.S. dam." for i in range(20))
        pieces = engines.split_pieces(text, 150)
        self.assertTrue(all(len(p) <= 150 for p in pieces))
        self.assertTrue(all(p.startswith("Sentence") and p.endswith("dam.") for p in pieces))
        self.assertEqual(" ".join(pieces), text)

    def test_one_endless_sentence_is_cut_at_commas_then_words(self):
        text = ", ".join(["a clause about the river"] * 12) + "."
        pieces = engines.split_pieces(text, 60)
        self.assertTrue(all(len(p) <= 60 for p in pieces))
        self.assertEqual(" ".join(pieces), text)
        self.assertEqual(engines.split_pieces("x" * 100, 40), ["x" * 40, "x" * 40, "x" * 20])
        self.assertEqual(engines.split_pieces("   "), [])


@unittest.skipUnless(READY, "needs numpy, fastapi and the tts_server folder")
class Engines(unittest.TestCase):
    """The model wrappers, with torch and the models faked."""

    def setUp(self):
        fake_torch = types.ModuleType("torch")
        fake_torch.inference_mode = contextlib.nullcontext
        p = mock.patch.dict(sys.modules, {"torch": fake_torch})
        p.start()
        self.addCleanup(p.stop)

    class Tensor:
        def __init__(self, a):
            self.a = a

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.a

    def test_kokoro_reads_its_voices_from_the_image_and_its_language_from_the_voice(self):
        k = engines.Kokoro()
        k.model = object()                                          # "loaded"
        calls = []

        def pipeline(text, voice=None, speed=1, split_pattern=None):
            calls.append((text, voice, speed))
            return [types.SimpleNamespace(audio=self.Tensor(tone(0.5))), types.SimpleNamespace(audio=None),
                    types.SimpleNamespace(audio=self.Tensor(tone(0.25)))]
        k.pipelines["b"] = pipeline
        with mock.patch.object(k, "voices", return_value=["af_heart", "bm_george", "bm_fable"]), \
                mock.patch.object(engines, "KOKORO_DIR", "/opt/models/kokoro"):
            samples, rate, voice = k.synthesize("Hello.", "bm_george,fable", 0.9)
            with self.assertRaises(engines.Refused):
                k.synthesize("Hello.", "bm_nobody", 1.0)
        packs = calls[0][1].replace("\\", "/")
        self.assertEqual(packs, "/opt/models/kokoro/voices/bm_george.pt,/opt/models/kokoro/voices/bm_fable.pt")
        self.assertEqual((calls[0][0], calls[0][2], rate, voice), ("Hello.", 0.9, 24000, "bm_george,bm_fable"))
        self.assertEqual(len(samples), int(0.75 * 24000))           # the segments, joined

    def test_chatterbox_never_leaves_one_customers_voice_on_for_the_next(self):
        prepared, used = [], []

        class Model:
            sr = 24000
            conds = "built-in voice"

            def prepare_conditionals(self, path, exaggeration=0.5):
                prepared.append(path)
                self.conds = f"voice of {path}"

            def generate(inner, text, exaggeration=0.5, cfg_weight=0.5, temperature=0.8):
                used.append((inner.conds, text))
                return self.Tensor(tone(1.0))
        c = engines.Chatterbox()
        c.model, c.default_voice = Model(), "built-in voice"
        long_text = "One sentence here. " * 30                       # more than one piece
        samples, rate, voice = c.synthesize(long_text, "/refs/owner.wav", 0.5, 0.5, 0.8)
        self.assertEqual(voice, "cloned")
        self.assertGreater(len(used), 1)
        self.assertEqual({v for v, _ in used}, {"voice of /refs/owner.wav"})
        gaps = len(used) - 1
        self.assertEqual(len(samples), len(used) * 24000 + gaps * int(24000 * engines.CHATTERBOX_GAP_SECONDS))
        c.synthesize("Another part.", "/refs/owner.wav", 0.5, 0.5, 0.8)
        self.assertEqual(prepared, ["/refs/owner.wav"])              # the sample is listened to once
        used.clear()
        _, _, voice = c.synthesize("No sample this time.", "", 0.5, 0.5, 0.8)
        self.assertEqual((voice, used[0][0]), ("default", "built-in voice"))


@unittest.skipUnless(READY and HAVE_FFMPEG, "needs ffmpeg")
class Encoding(unittest.TestCase):
    def test_every_format_is_a_file_the_worker_can_measure(self):
        from src import voicepolish
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for fmt, codec in (("wav", "pcm_s16le"), ("flac", "flac"), ("mp3", "mp3"), ("opus", "opus"), ("aac", "aac")):
            data, kind = engines.encode(tone(2.0), 24000, fmt)
            path = os.path.join(d, f"speech.{fmt}")
            with open(path, "wb") as f:
                f.write(data)
            info = voicepolish.probe(path)
            self.assertEqual(info["codec"], codec, fmt)
            # The length is in the file (a bare AAC stream has no header for it: ffprobe estimates).
            self.assertAlmostEqual(info["seconds"], 2.0, delta=0.5 if fmt == "aac" else 0.1, msg=fmt)
            self.assertTrue(kind.startswith("audio/"))
        raw, _ = engines.encode(tone(1.0), 24000, "pcm")
        self.assertEqual(len(raw), 24000 * 2)
        faster, _ = engines.encode(tone(2.0), 24000, "wav", tempo=1.25)
        self.assertAlmostEqual(wav_seconds(faster), 1.6, delta=0.05)

    def test_a_voice_sample_becomes_a_clean_wav_once_and_junk_is_refused(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        sample, _ = engines.encode(tone(6.0, 44100), 44100, "mp3")
        short, _ = engines.encode(tone(1.0), 24000, "wav")
        with mock.patch.object(engines, "REFERENCE_DIR", d):
            path = engines.reference_file("data:audio/mp3;base64," + base64.b64encode(sample).decode())
            with wave.open(path, "rb") as w:
                self.assertEqual((w.getnchannels(), w.getframerate()), (1, 24000))
                self.assertAlmostEqual(w.getnframes() / w.getframerate(), 6.0, delta=0.2)
            with mock.patch.object(engines.subprocess, "run", side_effect=AssertionError("decoded twice")):
                self.assertEqual(engines.reference_file("data:audio/mp3;base64," + base64.b64encode(sample).decode()),
                                 path)
            with self.assertRaises(engines.Refused) as too_short:
                engines.reference_file(base64.b64encode(short).decode())
            with self.assertRaises(engines.Refused) as junk:
                engines.reference_file(base64.b64encode(b"this is not audio at all " * 80).decode())
            self.assertEqual(engines.reference_file(""), "")
            self.assertEqual(sorted(os.listdir(d)), [os.path.basename(path)])    # nothing half-made left behind
        self.assertIn("only 1.0 s", str(too_short.exception))
        self.assertIn("cannot be read as audio", str(junk.exception))

    def test_a_sample_that_is_a_list_of_other_files_is_never_followed(self):
        """An ffconcat "sample" naming a file on this machine: ffmpeg would read that file as the voice."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        secret, _ = engines.encode(tone(6.0), 24000, "wav")
        with open(os.path.join(d, "other-customer.wav"), "wb") as f:
            f.write(secret)
        listing = ("ffconcat version 1.0\n" + "# padding\n" * 120 + "file 'other-customer.wav'\n").encode()
        with mock.patch.object(engines, "REFERENCE_DIR", d):
            with self.assertRaises(engines.Refused) as ctx:
                engines.reference_file(base64.b64encode(listing).decode())
        self.assertIn("cannot be read as audio", str(ctx.exception))
        self.assertEqual(os.listdir(d), ["other-customer.wav"])

    def test_the_parts_of_one_narration_bring_the_same_new_sample_at_once(self):
        import threading
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        sample, _ = engines.encode(tone(6.0, 44100), 44100, "mp3")
        value = "data:audio/mp3;base64," + base64.b64encode(sample).decode()
        start, got, failed = threading.Barrier(4), [], []

        def part():
            start.wait()
            try:
                got.append(engines.reference_file(value))
            except Exception as e:  # noqa: BLE001 - collected for the assertion below
                failed.append(e)
        with mock.patch.object(engines, "REFERENCE_DIR", d):
            threads = [threading.Thread(target=part) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(failed, [])
        self.assertEqual(len(set(got)), 1)
        self.assertEqual(os.listdir(d), [os.path.basename(got[0])])            # no temp file of any part left
        with wave.open(got[0], "rb") as w:
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 6.0, delta=0.2)


class FakeGet:
    """What requests.get(..., stream=True) gives back, as much as engines._fetch reads."""

    def __init__(self, status=200, body=b"", location=""):
        self.status_code, self.body = status, body
        self.headers = {"location": location} if location else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]


def resolves_to(*addresses):
    """socket.getaddrinfo's answer for a host with these addresses."""
    import socket
    return lambda host, port, *a, **kw: [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6,
                                          "", (ip, port)) for ip in addresses]


@unittest.skipUnless(READY, "needs the tts_server folder")
class SampleLinks(unittest.TestCase):
    """A voice sample by link: the endpoint never fetches from this machine or a private network."""

    def test_a_link_to_this_machine_or_a_private_network_is_refused_unfetched(self):
        import requests
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.20", "169.254.169.254", "100.64.0.1", "::1",
                   "::ffff:127.0.0.1", "fd00::1"):
            with mock.patch.object(engines.socket, "getaddrinfo", side_effect=resolves_to("93.184.215.14", ip)), \
                    mock.patch.object(requests, "get") as get:
                with self.assertRaises(engines.Refused, msg=ip) as ctx:
                    engines._fetch("https://samples.example/me.wav")
            get.assert_not_called()
            self.assertIn("public internet address", str(ctx.exception))
        with self.assertRaises(engines.Refused):
            engines._fetch("ftp://samples.example/me.wav")

    def test_every_redirect_is_checked_again(self):
        import requests
        hosts = {"samples.example": "93.184.215.14", "inside.example": "10.1.2.3"}

        def getaddrinfo(host, port, *a, **kw):
            return resolves_to(hosts[host])(host, port)
        with mock.patch.object(engines.socket, "getaddrinfo", side_effect=getaddrinfo), \
                mock.patch.object(requests, "get", side_effect=[
                    FakeGet(302, location="http://inside.example/latest/meta-data")]) as get:
            with self.assertRaises(engines.Refused) as ctx:
                engines._fetch("https://samples.example/me.wav")
        self.assertEqual(get.call_count, 1)
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)
        self.assertIn("public internet address", str(ctx.exception))
        with mock.patch.object(engines.socket, "getaddrinfo", side_effect=getaddrinfo), \
                mock.patch.object(requests, "get", side_effect=[FakeGet(301, location="/v2/me.wav"),
                                                                FakeGet(200, body=b"RIFF" + b"\0" * 2000)]) as get:
            self.assertEqual(len(engines._fetch("https://samples.example/me.wav")), 2004)
        self.assertEqual(get.call_args.args[0], "https://samples.example/v2/me.wav")
        with mock.patch.object(engines.socket, "getaddrinfo", side_effect=getaddrinfo), \
                mock.patch.object(requests, "get", side_effect=[FakeGet(302, location="/again")] * 9):
            with self.assertRaises(engines.Refused) as ctx:
                engines._fetch("https://samples.example/me.wav")
        self.assertIn("redirects more than", str(ctx.exception))

    def test_a_busy_host_is_worth_another_try_a_missing_sample_is_not(self):
        import requests
        with mock.patch.object(engines.socket, "getaddrinfo", side_effect=resolves_to("93.184.215.14")):
            with mock.patch.object(requests, "get", return_value=FakeGet(503)):
                with self.assertRaises(RuntimeError) as busy:
                    engines._fetch("https://samples.example/me.wav")
            with mock.patch.object(requests, "get", return_value=FakeGet(404)):
                with self.assertRaises(engines.Refused) as missing:
                    engines._fetch("https://samples.example/me.wav")
            with mock.patch.object(engines, "REFERENCE_MAX_BYTES", 1000), \
                    mock.patch.object(requests, "get", return_value=FakeGet(200, body=b"x" * 5000)):
                with self.assertRaises(engines.Refused) as large:
                    engines._fetch("https://samples.example/me.wav")
        self.assertNotIsInstance(busy.exception, engines.Refused)
        self.assertIn("HTTP 503", str(busy.exception))
        self.assertIn("HTTP 404", str(missing.exception))
        self.assertIn("too large", str(large.exception))


class QueueHandler(Base):
    def test_the_audio_goes_back_base64_with_what_the_worker_counts(self):
        out = rp_handler.handler({"id": "j1", "input": {"model": "kokoro", "voice": "af_heart", "input": "Hi.",
                                                        "response_format": "wav"}})
        self.assertAlmostEqual(wav_seconds(base64.b64decode(out["audio_base64"])), 2.0, places=3)
        self.assertEqual((out["format"], out["seconds"], out["model"], out["voice"]), ("wav", 2.0, "kokoro", "af_heart"))
        self.assertNotIn("audio", out)                                # bytes cannot ride in JSON

    def test_a_refusal_completes_the_job_and_a_crash_fails_it(self):
        self.assertIn("unknown voice", rp_handler.handler({"input": {"input": "Hi.", "voice": "zz_nobody"}})["refused"])
        with mock.patch.object(engines.KOKORO, "synthesize", side_effect=RuntimeError("CUDA out of memory")):
            with self.assertRaises(RuntimeError):                     # RunPod marks it FAILED; the worker retries
                rp_handler.handler({"input": {"input": "Hi."}})

    def test_runpods_openai_route_and_the_health_action(self):
        out = rp_handler.handler({"input": {"openai_route": "/v1/audio/speech",
                                            "openai_input": {"input": "Hi.", "response_format": "pcm"}}})
        self.assertEqual(out["format"], "pcm")
        health = rp_handler.handler({"input": {"action": "health"}})
        self.assertTrue(health["ok"])
        self.assertEqual(health["engines"]["kokoro"]["voices"], 5)


class HttpServer(Base):
    def setUp(self):
        super().setUp()
        self.client = TestClient(server.app)                          # no lifespan: nothing is preloaded

    def test_the_openai_speech_route_answers_with_the_audio_itself(self):
        r = self.client.post("/v1/audio/speech", json={"model": "kokoro", "voice": "am_michael",
                                                       "input": "Lake Mead is falling.", "response_format": "wav"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "audio/wav")
        self.assertAlmostEqual(wav_seconds(r.content), 2.0, places=3)
        self.assertEqual((r.headers["x-audio-seconds"], r.headers["x-voice"]), ("2.0", "am_michael"))
        self.assertIn("x-gpu-seconds", r.headers)

    def test_errors_have_openais_shape_and_say_whose_fault_it_is(self):
        r = self.client.post("/v1/audio/speech", json={"input": "Hi.", "voice": "zz_nobody"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["type"], "invalid_request_error")
        self.assertIn("unknown voice", r.json()["error"]["message"])
        with mock.patch.object(engines.KOKORO, "synthesize", side_effect=RuntimeError("CUDA out of memory")):
            r = self.client.post("/v1/audio/speech", json={"input": "Hi."})
        self.assertEqual((r.status_code, r.json()["error"]["type"]), (500, "server_error"))
        r = self.client.post("/v1/audio/speech", content=b"not json", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)

    def test_a_body_over_the_limit_is_refused_unread(self):
        with mock.patch.object(server, "MAX_BODY_BYTES", 2000):
            r = self.client.post("/v1/audio/speech", json={"input": "Hi.", "reference_audio": "x" * 5000})
            self.assertEqual((r.status_code, r.json()["error"]["type"]), (413, "invalid_request_error"))
            self.assertEqual(self.said, [])                               # never reached the model
            r = self.client.post("/v1/audio/speech", json={"input": "Lake Mead is falling.", "response_format": "pcm"})
            self.assertEqual(r.status_code, 200)                         # a normal part is far under it
        self.assertGreaterEqual(server.MAX_BODY_BYTES, engines.REFERENCE_MAX_BYTES * 4 // 3)   # a whole sample fits

    def test_with_a_server_key_only_its_bearer_gets_speech(self):
        with mock.patch.dict(os.environ, {"TTS_SERVER_KEY": "s3cret"}):
            body = {"input": "Hi.", "response_format": "pcm"}
            self.assertEqual(self.client.post("/v1/audio/speech", json=body).status_code, 401)
            self.assertEqual(self.client.post("/v1/audio/speech", json=body,
                                              headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(self.client.post("/v1/audio/speech", json=body,
                                              headers={"Authorization": "Bearer s3cret"}).status_code, 200)
            self.assertEqual(self.client.get("/ping").status_code, 200)   # the load balancer's check stays open

    def test_health_and_the_voice_list(self):
        health = self.client.get("/health").json()
        self.assertTrue(health["ok"])
        self.assertEqual(health["engines"]["kokoro"], {"loaded": False, "voices": 5})
        self.assertIn("flac", health["formats"])
        voices = self.client.get("/v1/audio/voices").json()
        self.assertEqual(voices["voices"][0], "af_heart")
        self.assertEqual([m["id"] for m in self.client.get("/v1/models").json()["data"]], ["kokoro"])


@unittest.skipUnless(HAVE_FFMPEG, "needs ffprobe")
class WorkerToEndpoint(Base):
    """The video worker's client (src/tts.py) against this endpoint's two front doors, wired in memory."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.settings = {"TTS_API_KEY": "k", "TTS_API_MODE": "auto", "TTS_MODEL": "kokoro", "TTS_VOICE": "am_michael",
                         "TTS_SPEED": 1.0, "TTS_REFERENCE_AUDIO": "", "TTS_FIELDS": "", "TTS_EXTRA": "",
                         "TTS_FORMAT": "wav", "TTS_RETRIES": 0, "TTS_TIMEOUT": 30.0}

    class Reply:
        def __init__(self, status, data=None, content=b"", headers=None):
            self.status_code, self._data, self.content = status, data, content
            self.headers = tts.requests.structures.CaseInsensitiveDict(headers or {})
            self.text = str(data)

        def json(self):
            if self._data is None:
                raise ValueError
            return self._data

    def test_a_part_through_the_runpod_queue_handler(self):
        def runsync(url, json=None, **kw):
            self.assertTrue(url.endswith("/runsync"))
            return self.Reply(200, {"id": "sync-1", "status": "COMPLETED", "executionTime": 900,
                                    "output": rp_handler.handler({"id": "sync-1", "input": json["input"]})})
        with mock.patch.multiple(config, TTS_API_BASE="https://api.runpod.ai/v2/voice123", **self.settings), \
                mock.patch.object(tts.requests, "post", side_effect=runsync):
            got = tts.voice_part(0, 1, "Lake Mead is falling.", os.path.join(self.dir, "part-000"), tts.options())
            with self.assertRaises(tts.TtsError) as refused:
                tts.voice_part(0, 1, "Hi.", os.path.join(self.dir, "x"), {**tts.options(), "voice": "zz_nobody"})
        self.assertEqual(self.said[0], {"text": "Lake Mead is falling.", "voice": "am_michael", "speed": 1.0})
        self.assertAlmostEqual(got["seconds"], 2.0, delta=0.05)       # measured from the file that arrived
        self.assertIn("unknown voice", str(refused.exception))

    def test_a_whole_script_through_the_endpoint_is_one_narration_at_the_voice_level(self):
        from src import voicepolish
        script = " ".join(f"Sentence number {i} tells one more plain fact about the falling lake." for i in range(14))

        def runsync(url, json=None, **kw):
            return self.Reply(200, {"id": "s", "status": "COMPLETED", "executionTime": 500,
                                    "output": rp_handler.handler({"id": "s", "input": json["input"]})})
        settings = {**self.settings, "TTS_FORMAT": "flac", "TTS_CHUNK_CHARS": 300, "TTS_WORKERS": 4,
                    "TTS_GAP_SECONDS": 0.3, "TTS_LUFS": 0.0, "TTS_OUTPUT_FORMAT": "mp3", "TTS_MAX_CHARS": 120000}
        costs.reset()
        with mock.patch.multiple(config, TTS_API_BASE="https://api.runpod.ai/v2/voice123", **settings), \
                mock.patch.object(tts.requests, "post", side_effect=runsync):
            out = tts.synthesize(script, self.dir)
        parts = tts.chunk_script(script, 300)
        self.assertGreaterEqual(len(parts), 4)
        self.assertEqual(sorted(s["text"] for s in self.said), sorted(parts))      # every part asked for once
        spoken = sum(len(p) / 15.0 for p in parts) + 0.3 * (len(parts) - 1)
        info = voicepolish.probe(out["path"])
        self.assertEqual((info["codec"], info["rate"], info["channels"]), ("mp3", 44100, 1))
        self.assertAlmostEqual(info["seconds"], spoken, delta=0.4)                 # all of it, with the breaths
        self.assertAlmostEqual(voicepolish.loudness(out["path"])["lufs"], sfxplan.VOICE_LUFS_DEFAULT, delta=0.5)
        self.assertEqual((out["parts"], out["mode"], out["text"]), (len(parts), "runpod", script))
        units = costs.summary(0)["units"]
        self.assertAlmostEqual(units["tts.seconds"], out["seconds"], places=1)
        self.assertGreater(units["tts.gpu_seconds"], 0)
        self.assertEqual(os.listdir(self.dir).count("narration.mp3"), 1)

    def test_a_part_through_the_http_server(self):
        client = TestClient(server.app)

        def post(url, json=None, headers=None, **kw):
            r = client.post(url.replace("https://voice.example", ""), json=json, headers=headers)
            return self.Reply(r.status_code, r.json() if "json" in r.headers.get("content-type", "") else None,
                              r.content, dict(r.headers))
        with mock.patch.multiple(config, TTS_API_BASE="https://voice.example", **self.settings), \
                mock.patch.object(tts.requests, "post", side_effect=post):
            got = tts.voice_part(0, 1, "Lake Mead is falling.", os.path.join(self.dir, "part-000"), tts.options())
            with self.assertRaises(tts.TtsError) as refused:
                tts.voice_part(0, 1, "Hi.", os.path.join(self.dir, "x"), {**tts.options(), "voice": "zz_nobody"})
        self.assertAlmostEqual(got["seconds"], 2.0, delta=0.05)
        self.assertEqual(got["attempts"], 1)
        self.assertIn("unknown voice", str(refused.exception))


@unittest.skipUnless(READY, "needs the tts_server folder")
class Models(unittest.TestCase):
    def test_the_models_are_pinned_to_a_revision_and_chatterbox_is_only_fetched_on_request(self):
        for name, spec in fetch_models.MODELS.items():
            self.assertRegex(spec["revision"], r"^[0-9a-f]{40}$", name)       # a commit, never "main"
            self.assertTrue(set(spec["need"]) <= set(spec["files"]) | {"voices/af_heart.pt"})
        self.assertEqual(fetch_models.MODELS["kokoro"]["license"], "Apache-2.0")
        self.assertEqual(fetch_models.MODELS["chatterbox"]["license"], "MIT")
        with mock.patch.dict(os.environ, {"WITH_CHATTERBOX": "0"}):
            self.assertEqual(fetch_models.wanted(), ["kokoro"])
        with mock.patch.dict(os.environ, {"WITH_CHATTERBOX": "1"}):
            self.assertEqual(fetch_models.wanted(), ["kokoro", "chatterbox"])

    def test_the_default_voice_of_worker_and_endpoint_is_one_the_image_fetches(self):
        self.assertRegex(engines.DEFAULT_VOICE, r"^[a-z]{2}_[a-z0-9]+$")
        self.assertIn(f"voices/{engines.DEFAULT_VOICE}.pt", fetch_models.MODELS["kokoro"]["need"])


if __name__ == "__main__":
    unittest.main()
