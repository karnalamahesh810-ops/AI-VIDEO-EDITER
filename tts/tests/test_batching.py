"""Batching of several parts on one worker (no GPU, no model: a fake model stands in)."""
import queue
import threading
import time
import unittest

import numpy as np

import engine
import engine_qwen


class FakeModel:
    """generate_voice_clone stand-in: a piece of 0.4 s per word; texts containing 'BAD' come out empty."""

    def __init__(self):
        self.calls = []

    def create_voice_clone_prompt(self, ref_audio, ref_text, x_vector_only_mode):
        return [("prompt", ref_audio)]

    def generate_voice_clone(self, text, language, voice_clone_prompt, **p):
        self.calls.append({"n": len(text), "params": dict(p), "prompts": list(voice_clone_prompt)})
        sr = 24000
        wavs = []
        for t in text:
            n = 0 if "BAD" in t else int(sr * 0.4 * len(t.split()))
            w = np.zeros(n, np.float32)
            if n:
                w[::50] = 0.5  # sound, so trim() keeps it
            wavs.append(w)
        return wavs, sr


def host_with_fake():
    h = engine_qwen.QwenHost("cpu", want_asr=False)
    h.model = FakeModel()
    h.ref_texts = {"v1": "reference words", "v2": "other reference"}
    return h


def task(texts, voice="v1", seed=7, **kw):
    t = {"op": "part", "voice_key": voice, "ref_path": f"/tmp/{voice}.wav", "ref_text": "ref", "texts": texts,
         "params": {}, "seed": seed, "validate": False, "max_attempts": 3, "lang": "en"}
    t.update(kw)
    return t


class RunParts(unittest.TestCase):
    def setUp(self):
        self._seed = engine_qwen.seed_all
        engine_qwen.seed_all = lambda s: None

    def tearDown(self):
        engine_qwen.seed_all = self._seed

    def test_parts_share_one_batch_and_come_back_in_order(self):
        h = host_with_fake()
        a = task(["one two three", "four five"])
        b = task(["six seven eight nine", "ten", "eleven twelve"], voice="v2")
        ra, rb = h.run_parts([a, b])
        self.assertEqual(len(h.model.calls), 1)
        self.assertEqual(h.model.calls[0]["n"], 5)
        self.assertEqual(len(ra["wavs"]), 2)
        self.assertEqual(len(rb["wavs"]), 3)
        # each piece kept its own length (0.4 s a word) and its own voice prompt
        self.assertAlmostEqual(len(rb["wavs"][0]) / 24000, 1.6, delta=0.15)
        self.assertEqual([p[1] for p in h.model.calls[0]["prompts"]], ["/tmp/v1.wav"] * 2 + ["/tmp/v2.wav"] * 3)
        self.assertEqual(ra["batch_parts"], 2)
        self.assertEqual(ra["batch_pieces"], 5)

    def test_one_part_is_the_same_as_before(self):
        h = host_with_fake()
        r = h.run_part(task(["one two three", "four five"]))
        self.assertEqual(len(h.model.calls), 1)
        self.assertEqual(r["attempts"], [1, 1])

    def test_only_bad_pieces_are_made_again(self):
        h = host_with_fake()
        ra, rb = h.run_parts([task(["fine words here", "BAD piece"]), task(["also fine"])])
        self.assertEqual([c["n"] for c in h.model.calls], [3, 1, 1])  # rounds 2 and 3: the bad piece only
        self.assertEqual(ra["attempts"], [1, 3])
        self.assertEqual(rb["attempts"], [1])

    def test_different_settings_never_share_a_batch(self):
        h = host_with_fake()
        a = task(["one two"])
        b = task(["three four"], params={"temperature": 0.7})
        h.run_parts([a, b])
        self.assertEqual(sorted(c["n"] for c in h.model.calls), [1, 1])
        temps = sorted(c["params"]["temperature"] for c in h.model.calls)
        self.assertEqual(temps, [0.7, 0.9])

    def test_batch_cap_slices_a_long_list(self):
        h = host_with_fake()
        old = engine_qwen.MAX_BATCH
        engine_qwen.MAX_BATCH = 4
        try:
            r = h.run_parts([task([f"word {i}" for i in range(6)]), task([f"more {i}" for i in range(3)])])
        finally:
            engine_qwen.MAX_BATCH = old
        self.assertEqual([c["n"] for c in h.model.calls], [4, 4, 1])
        self.assertEqual(len(r[0]["wavs"]) + len(r[1]["wavs"]), 9)


    def test_out_of_memory_halves_the_batch(self):
        h = host_with_fake()
        real = h.model.generate_voice_clone

        def gen(text, language, voice_clone_prompt, **p):
            if len(text) > 3:
                raise MemoryError("CUDA out of memory")
            return real(text, language, voice_clone_prompt, **p)

        h.model.generate_voice_clone = gen
        h.model.calls = []
        r = h.run_parts([task([f"word {i}" for i in range(8)])])
        self.assertEqual(len(r[0]["wavs"]), 8)
        self.assertTrue(all(len(w) > 0 for w in r[0]["wavs"]))
        self.assertLessEqual(h.max_batch(), 4)
        self.assertTrue(all(c["n"] <= 3 for c in h.model.calls))

    def test_batch_size_follows_the_card(self):
        self.assertEqual(engine_qwen.auto_max_batch(16.0), 96)
        self.assertEqual(engine_qwen.auto_max_batch(24.0), 160)
        self.assertEqual(engine_qwen.auto_max_batch(48.0), 256)


class Gather(unittest.TestCase):
    def test_parts_waiting_together_are_gathered(self):
        q = queue.Queue()
        for i in range(2, 5):
            q.put((i, {"op": "part", "texts": ["a", "b"]}))
        batch, rest = engine._gather_parts(q, (1, {"op": "part", "texts": ["a"]}), [])
        self.assertEqual([t for t, _ in batch], [1, 2, 3, 4])
        self.assertEqual(rest, [])

    def test_other_tasks_keep_their_place(self):
        q = queue.Queue()
        q.put((2, {"op": "part", "texts": ["a"]}))
        q.put((3, {"op": "similarity"}))
        q.put((4, {"op": "part", "texts": ["a"]}))
        batch, rest = engine._gather_parts(q, (1, {"op": "part", "texts": ["a"]}), [])
        self.assertEqual([t for t, _ in batch], [1, 2])
        self.assertEqual([t for t, _ in rest], [3])
        self.assertEqual(q.get_nowait()[0], 4)  # still queued, picked up next

    def test_piece_cap(self):
        q = queue.Queue()
        for i in range(2, 10):
            q.put((i, {"op": "part", "texts": ["x"] * 40}))
        old = engine.GATHER_MAX_PIECES
        engine.GATHER_MAX_PIECES = 96
        try:
            batch, _ = engine._gather_parts(q, (1, {"op": "part", "texts": ["x"] * 40}), [])
        finally:
            engine.GATHER_MAX_PIECES = old
        self.assertEqual(len(batch), 3)  # 40 + 40 + 40 >= 96: stop gathering


class AliveProc:
    def is_alive(self):
        return True


class PoolRouting(unittest.TestCase):
    def test_concurrent_callers_get_their_own_answers(self):
        pool = engine.ReplicaPool(1, device="cpu", want_asr=False, preload=None)
        pool.procs = [AliveProc()]
        pool.tasks = queue.Queue()
        pool.results = queue.Queue()
        stop = threading.Event()

        def replica():  # answers in reverse order of arrival, batched like the real one
            while not stop.is_set():
                try:
                    items = [pool.tasks.get(timeout=0.2)]
                except queue.Empty:
                    continue
                time.sleep(0.2)
                while True:
                    try:
                        items.append(pool.tasks.get_nowait())
                    except queue.Empty:
                        break
                for tid, t in reversed(items):
                    pool.results.put(("done", tid, {"echo": t["texts"][0]}))

        th = threading.Thread(target=replica, daemon=True)
        th.start()
        got = {}

        def caller(i):
            got[i] = pool.run([{"op": "part", "texts": [f"job{i}"]}], timeout_s=20)[0]["echo"]

        cs = [threading.Thread(target=caller, args=(i,)) for i in range(6)]
        for c in cs:
            c.start()
        for c in cs:
            c.join(30)
        stop.set()
        self.assertEqual(got, {i: f"job{i}" for i in range(6)})

    def test_a_failure_reaches_only_its_caller(self):
        pool = engine.ReplicaPool(1, device="cpu", want_asr=False, preload=None)
        pool.procs = [AliveProc()]
        pool.tasks = queue.Queue()
        pool.results = queue.Queue()

        def replica():
            for _ in range(2):
                tid, t = pool.tasks.get(timeout=5)
                if t["texts"][0] == "bad":
                    pool.results.put(("fail", tid, "RuntimeError: boom"))
                else:
                    pool.results.put(("done", tid, {"ok": True}))

        threading.Thread(target=replica, daemon=True).start()
        out = {}

        def caller(name):
            try:
                out[name] = pool.run([{"op": "part", "texts": [name]}], timeout_s=20)[0]
            except RuntimeError as e:
                out[name] = str(e)

        cs = [threading.Thread(target=caller, args=(n,)) for n in ("bad", "good")]
        for c in cs:
            c.start()
        for c in cs:
            c.join(30)
        self.assertIn("boom", out["bad"])
        self.assertEqual(out["good"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
