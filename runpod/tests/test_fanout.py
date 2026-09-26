import os
import tempfile
import unittest
from unittest import mock

from src import config, fanout, media


def _asset(i: int, url: str = "") -> media.MediaAsset:
    return media.MediaAsset(kind="video", source="youtube",
                            url=url or f"https://www.youtube.com/watch?v=vid{i:08d}")


class FanoutSource(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.jobs = [{"index": i, "query": f"q{i}"} for i in range(9)]
        self.cancelled = []
        self.local_calls = []

    def _local(self, some, exclude):
        self.local_calls.append(sorted(j["index"] for j in some))
        return [_asset(j["index"]) for j in sorted(some, key=lambda j: j["index"])]

    def _run(self, statuses):
        ids = iter(["part-a", "part-b"])

        def status(jid):
            return statuses[jid]()

        def download(url, path):
            with open(path, "wb") as fh:
                fh.write(b"x")
            return path

        with mock.patch.object(config, "FANOUT_PARTS", 3), \
                mock.patch.object(config, "FANOUT_TIMEOUT_SECONDS", 60), \
                mock.patch.object(fanout, "_submit", lambda payload: next(ids)), \
                mock.patch.object(fanout, "_status", status), \
                mock.patch.object(fanout, "_cancel", self.cancelled.append), \
                mock.patch.object(fanout.storage, "download", download), \
                mock.patch.object(fanout.time, "sleep", lambda s: None):
            return fanout.source(self.jobs, [], {}, parent_job_id="p", project_id="x",
                                 bucket="b", work=self.work, flags={},
                                 report=lambda *a, **k: None, local=self._local)

    def test_parent_sources_its_own_part_and_steals_a_queued_one(self):
        remote = {str(i): {"kind": "video", "source": "youtube",
                           "url": f"https://www.youtube.com/watch?v=vid{i:08d}",
                           "remote_url": f"https://s/{i}", "storage_path": f"x/{i:04d}.mp4"}
                  for i in (3, 4, 5)}
        out = self._run({
            "part-a": lambda: {"status": "COMPLETED", "output": {"assets": remote}},
            "part-b": lambda: {"status": "IN_QUEUE"},
        })
        self.assertTrue(all(a is not None for a in out))
        self.assertIn([0, 1, 2], self.local_calls)       # its own part
        self.assertIn([6, 7, 8], self.local_calls)       # the part no machine started
        self.assertEqual(self.cancelled, ["part-b"])
        self.assertTrue(os.path.isfile(out[4].local_path))
        self.assertEqual(media.LAST_STATS["fanout"]["stolen_back"], 1)

    def test_cross_part_repeat_is_resourced(self):
        same = "https://www.youtube.com/watch?v=vid00000000"
        remote = {str(i): {"kind": "video", "source": "youtube", "url": same if i == 3 else
                           f"https://www.youtube.com/watch?v=vid{i:08d}",
                           "remote_url": f"https://s/{i}", "storage_path": f"x/{i:04d}.mp4"}
                  for i in (3, 4, 5)}
        rest = {str(i): dict(remote["4"], url=f"https://www.youtube.com/watch?v=vid{i:08d}")
                for i in (6, 7, 8)}
        out = self._run({
            "part-a": lambda: {"status": "COMPLETED", "output": {"assets": remote}},
            "part-b": lambda: {"status": "COMPLETED", "output": {"assets": rest}},
        })
        self.assertEqual(self.local_calls[-1], [3])     # scene 3 repeated scene 0's clip
        self.assertEqual(len({a.identity for a in out}), len(out))


if __name__ == "__main__":
    unittest.main()
