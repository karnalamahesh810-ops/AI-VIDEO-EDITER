import time
import unittest
from unittest import mock

import handler


class LogTailInStatus(unittest.TestCase):
    def test_status_carries_recent_lines_and_refreshes_while_a_phase_runs(self):
        pushes = []
        with mock.patch.object(handler.runpod.serverless, "progress_update",
                               side_effect=lambda job, u: pushes.append(u)), \
                mock.patch.object(handler.Reporter, "HEARTBEAT", 0.05):
            rep = handler.Reporter("", job={"id": "j1"})
            rep("Finding footage by subject", 22)
            self.assertEqual(pushes[-1]["status"], "Finding footage by subject")
            self.assertTrue(any("Finding footage by subject" in l for l in pushes[-1]["recent"]))
            n = len(pushes)
            print("[pools] Lake Mead: 6 videos, 14 moments", flush=True)
            time.sleep(0.3)
            rep.finish()
        self.assertGreater(len(pushes), n, "no heartbeat refresh after new log lines")
        self.assertTrue(any("14 moments" in l for l in pushes[-1]["recent"]))
        self.assertIn("elapsed", pushes[-1])
        # Nothing new printed -> no extra pushes (the heartbeat is quiet).
        quiet = len(pushes)
        time.sleep(0.15)
        self.assertEqual(len(pushes), quiet)


if __name__ == "__main__":
    unittest.main()
