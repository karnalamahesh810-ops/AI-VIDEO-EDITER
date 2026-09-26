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


    def test_many_gaps_go_back_out_across_workers_without_used_clips(self):
        remote = {str(i): {"kind": "video", "source": "youtube",
                           "url": f"https://www.youtube.com/watch?v=vid{i:08d}",
                           "remote_url": f"https://s/{i}", "storage_path": f"x/{i:04d}.mp4"}
                  for i in (3, 4, 5)}
        payloads = []
        ids = iter(["part-a", "part-b", "r2-1", "r2-2"])
        statuses = {
            "part-a": {"status": "COMPLETED", "output": {"assets": remote}},
            "part-b": {"status": "FAILED", "output": {"error": "boom"}},
            "r2-1": {"status": "COMPLETED", "output": {"assets": {"7": dict(remote["3"], url="https://www.youtube.com/watch?v=new00000007")}}},
            "r2-2": {"status": "COMPLETED", "output": {"assets": {"8": dict(remote["3"], url="https://www.youtube.com/watch?v=new00000008")}}},
        }

        def submit(payload):
            payloads.append(payload)
            return next(ids)

        def download(url, path):
            with open(path, "wb") as fh:
                fh.write(b"x")
            return path

        with mock.patch.object(config, "FANOUT_PARTS", 3),                 mock.patch.object(config, "FANOUT_REFILL_MIN", 2),                 mock.patch.object(config, "FANOUT_TIMEOUT_SECONDS", 60),                 mock.patch.object(fanout, "_submit", submit),                 mock.patch.object(fanout, "_status", lambda jid: statuses[jid]),                 mock.patch.object(fanout, "_cancel", self.cancelled.append),                 mock.patch.object(fanout.storage, "download", download),                 mock.patch.object(fanout.time, "sleep", lambda s: None):
            out = fanout.source(self.jobs, [], {}, parent_job_id="p", project_id="x",
                                bucket="b", work=self.work, flags={},
                                report=lambda *a, **k: None, local=self._local)
        self.assertTrue(all(a is not None for a in out))
        round2 = [p for p in payloads if p["jobs"][0]["index"] in (7, 8)]
        self.assertEqual(len(round2), 2)                      # gaps went back out
        self.assertIn("yt:vid00000003", round2[0]["exclude"])   # told what is in use
        self.assertIn([6], self.local_calls)                  # one gap part done here
        self.assertEqual(media.LAST_STATS["fanout"]["rounds"], 2)


    def test_ai_image_cap_is_shared_across_parts(self):
        payloads = []
        ids = iter(["part-a", "part-b"])

        def submit(payload):
            payloads.append(payload)
            return next(ids)
        done = {"status": "COMPLETED", "output": {"assets": {}}}
        with mock.patch.object(config, "FANOUT_PARTS", 3),                 mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 9),                 mock.patch.object(config, "FANOUT_REFILL_MIN", 99),                 mock.patch.object(config, "FANOUT_TIMEOUT_SECONDS", 60),                 mock.patch.object(fanout, "_submit", submit),                 mock.patch.object(fanout, "_status", lambda jid: done),                 mock.patch.object(fanout, "_cancel", lambda jid: None),                 mock.patch.object(fanout.time, "sleep", lambda s: None):
            fanout.source(self.jobs, [], {}, parent_job_id="p", project_id="x", bucket="b",
                          work=self.work, flags={}, report=lambda *a, **k: None, local=self._local)
        self.assertEqual([p["image_budget"] for p in payloads], [3, 3])
        media.limit_generation(3)
        with mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 9):
            media.limit_generation(3)
            self.assertEqual(media.generated_count(), 6)   # 3 of 9 left here


class YouTubeGate(unittest.TestCase):
    def test_job_stops_before_spending_when_youtube_refuses_everything(self):
        import handler
        blocked = [{"route": "direct", "ok": False, "seconds": 1, "why": "bot check"}]
        with mock.patch.object(config, "REQUIRE_YOUTUBE", True),                 mock.patch.object(handler.media, "probe_youtube", return_value=blocked):
            with self.assertRaises(RuntimeError) as ctx:
                handler._require_youtube()
        self.assertIn("Nothing was spent", str(ctx.exception))
        ok = [{"route": "direct", "ok": False, "seconds": 1, "why": "bot check"},
              {"route": "proxy#1", "ok": True, "seconds": 2, "why": ""}]
        with mock.patch.object(config, "REQUIRE_YOUTUBE", True),                 mock.patch.object(handler.media, "probe_youtube", return_value=ok):
            handler._require_youtube()


class FanoutRender(unittest.TestCase):
    def test_chunks_cover_every_frame_once(self):
        with mock.patch.object(config, "FANOUT_RENDER_CHUNK_SECONDS", 90):
            ranges = fanout.chunks(30 * 60 * 22, 30, 9)
        self.assertEqual(len(ranges), 9)
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], 30 * 60 * 22 - 1)
        for (a, b), (c, _) in zip(ranges, ranges[1:]):
            self.assertEqual(c, b + 1)
        # Even a short render fills every worker slot.
        short = fanout.chunks(30 * 60, 30, 9)
        self.assertEqual(len(short), 9)
        self.assertEqual((short[0][0], short[-1][1]), (0, 1799))
        self.assertEqual(fanout.chunks(5, 30, 9), [(i, i) for i in range(5)])

    def test_lost_chunk_is_rendered_here_and_audio_rendered_once(self):
        work = tempfile.mkdtemp()
        calls = []

        def render_local(frames, path, muted, codec):
            calls.append((tuple(frames) if frames else None, muted, codec))
            with open(path, "wb") as fh:
                fh.write(b"x")

        ids = iter(["c2", "c1"])      # the one remote chunk is the one that fails

        def download(url, path):
            with open(path, "wb") as fh:
                fh.write(b"x")
        statuses = {"c1": {"status": "COMPLETED", "output": {"url": "https://s/c1"}},
                    "c2": {"status": "FAILED", "output": {"error": "gpu gone"}}}
        doc = {"fps": 30, "durationInFrames": 30 * 270}
        with mock.patch.object(config, "FANOUT_PARTS", 2),                 mock.patch.object(config, "FANOUT_RENDER_CHUNK_SECONDS", 90),                 mock.patch.object(fanout, "_submit", lambda p: next(ids)),                 mock.patch.object(fanout, "_status", lambda jid: statuses[jid]),                 mock.patch.object(fanout, "_cancel", lambda jid: None),                 mock.patch.object(fanout.storage, "download", download),                 mock.patch.object(fanout.subprocess, "run", lambda *a, **k: None),                 mock.patch.object(fanout.time, "sleep", lambda s: None):
            fanout.render(doc, os.path.join(work, "final.mp4"), parent_job_id="p",
                          project_id="x", bucket="b", work=work,
                          report=lambda *a, **k: None, render_local=render_local)
        self.assertIn(((0, 4049), True, None), calls)          # its own chunk, silent
        self.assertIn(((4050, 8099), True, None), calls)       # the failed chunk, here
        self.assertEqual([c for c in calls if c[2] == "aac"], [(None, False, "aac")])
        self.assertEqual(media.LAST_STATS["render_fanout"]["rendered_here_after"], 1)


if __name__ == "__main__":
    unittest.main()
