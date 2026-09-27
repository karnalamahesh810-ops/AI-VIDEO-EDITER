import time
import unittest
from unittest import mock

from src import config, director
from src.transcribe import Segment


class PlanBatchesInParallel(unittest.TestCase):
    def test_batches_run_side_by_side_and_each_fills_only_its_own_beats(self):
        n = director._BATCH * 3
        segments = [Segment(text=f"line {i}", start=i * 3.0, end=i * 3.0 + 3.0) for i in range(n)]
        shots = [{"query": f"rule {i}", "fallbacks": [], "prompt": "", "intent": "", "subject": "",
                  "subjectType": "", "visualType": "footage"} for i in range(n)]
        calls = []

        def fake_chat(system, payload, timeout=120, errors=None, **kw):
            calls.append(time.time())
            time.sleep(0.3)
            return {"shots": [{"index": b["index"], "query": f"ai {b['index']}", "subject": "Lake Mead",
                               "intent": "x", "subjectType": "place"} for b in payload["beats"]]}
        with mock.patch.object(director, "_chat_json", fake_chat), \
                mock.patch.object(config, "PLAN_PARALLEL", 3), \
                mock.patch.object(director.vision, "out_of_credits", return_value=False):
            t = time.time()
            enriched, warnings = director._ai_pass(segments, "t", shots, brief={"kind": "news"})
            took = time.time() - t
        self.assertEqual(enriched, n)
        self.assertEqual(warnings, [])
        self.assertEqual(len(calls), 3)
        self.assertLess(took, 0.75, f"batches ran sequentially ({took:.2f}s)")
        self.assertTrue(all(shots[i]["query"].startswith("Lake Mead") for i in range(n)))


if __name__ == "__main__":
    unittest.main()
