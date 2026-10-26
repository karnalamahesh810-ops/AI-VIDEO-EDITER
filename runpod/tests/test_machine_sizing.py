"""
Sourcing sized to the machine (src/machine.py) and the fast-sourcing option (src/fanout.py fold_fast_sourcing,
fast_deadline, source_parts). The Hoover Dam pod build (2026-10-26) ran the app's 32-core settings on 16 cores.
No network, no subprocess.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import config, fanout, machine, ytdlp  # noqa: E402


class Cpus(unittest.TestCase):
    def test_smallest_of_quota_affinity_and_host(self):
        with mock.patch.object(config, "MACHINE_CPUS", 0), \
                mock.patch.object(machine.os, "cpu_count", return_value=128), \
                mock.patch.object(machine, "cgroup_cpus", return_value=16.0):
            if hasattr(machine.os, "sched_getaffinity"):
                with mock.patch.object(machine.os, "sched_getaffinity", return_value=set(range(64))):
                    self.assertEqual(machine.cpus(), 16)
            else:
                self.assertEqual(machine.cpus(), 16)

    def test_forced(self):
        with mock.patch.object(config, "MACHINE_CPUS", 6):
            self.assertEqual(machine.cpus(), 6)

    def test_quota_parsing(self):
        reads = {"/sys/fs/cgroup/cpu.max": "1600000 100000"}
        with mock.patch.object(machine, "_read", side_effect=lambda p: reads.get(p, "")):
            self.assertEqual(machine.cgroup_cpus(), 16.0)
        reads = {"/sys/fs/cgroup/cpu.max": "max 100000"}
        with mock.patch.object(machine, "_read", side_effect=lambda p: reads.get(p, "")):
            self.assertEqual(machine.cgroup_cpus(), 0.0)
        with mock.patch.object(machine, "_read", return_value=""):
            self.assertEqual(machine.cgroup_cpus(), 0.0)


class EncodeThreads(unittest.TestCase):
    def test_x264_decides_by_default(self):
        # Measured on the 16-core pod: x264's own threads had the best throughput (machine.encode_threads).
        with mock.patch.object(config, "DOWNLOAD_THREADS", 0):
            self.assertEqual(machine.encode_threads(), 0)
            self.assertNotIn("-threads", ytdlp._encode_args(audio=False, hero=False))

    def test_forced(self):
        with mock.patch.object(config, "DOWNLOAD_THREADS", 2):
            self.assertEqual(machine.encode_threads(), 2)
            args = ytdlp._encode_args(audio=False, hero=False)
        self.assertIn("-threads 2", args)
        self.assertIn("-preset", args)               # the encode itself unchanged
        self.assertIn("-crf", args)


class SourceWorkers(unittest.TestCase):
    def test_no_clamp_by_default(self):
        with mock.patch.object(config, "SOURCE_WORKERS_PER_CPU", 0.0):
            self.assertEqual(machine.source_workers(28), 28)

    def test_clamped_to_the_cores(self):
        with mock.patch.object(config, "SOURCE_WORKERS_PER_CPU", 1.25), \
                mock.patch.object(machine, "cpus", return_value=16):
            self.assertEqual(machine.source_workers(28), 20)
            self.assertEqual(machine.source_workers(12), 12)


class Sampler(unittest.TestCase):
    def test_summary_from_samples(self):
        s = machine.Sampler(every=1.0)
        s.busy = [50.0, 95.0, 100.0, 20.0]
        s.mem = [10.0, 3.5, 8.0]
        s.procs["ffmpeg"] = [4, 16, 9]
        s.started = 1.0
        s.ended = 21.0
        out = s.summary()
        self.assertEqual(out["samples"], 4)
        self.assertEqual(out["cpuBusyPct"]["max"], 100.0)
        self.assertEqual(out["cpuBusyPct"]["share90Plus"], 0.5)
        self.assertEqual(out["memFreeGb"]["min"], 3.5)
        self.assertEqual(out["processes"]["ffmpeg"]["max"], 16)

    def test_no_counters_no_summary(self):
        self.assertEqual(machine.Sampler(every=1.0).summary(), {})

    def test_start_stop_never_raises(self):
        s = machine.Sampler(every=1.0).start()
        s.stop()
        self.assertIsInstance(s.summary(), dict)


class NetworkQueueStats(unittest.TestCase):
    def test_waits_counted_by_kind(self):
        q = ytdlp.Slots(1)
        self.assertTrue(q.acquire(ytdlp.DOWNLOAD))
        q.release()
        self.assertTrue(q.acquire(ytdlp.SEARCH))
        self.assertFalse(q.acquire(ytdlp.METADATA, give_up=lambda: True))
        q.release()
        st = q.stats()
        self.assertEqual(st["download"]["n"], 1)
        self.assertEqual(st["search"]["n"], 1)
        self.assertEqual(st["metadata"]["gaveUp"], 1)
        self.assertEqual(st["peakBusy"], 1)
        q.reset_stats()
        self.assertNotIn("download", q.stats())


class FastSourcing(unittest.TestCase):
    def test_off_unless_asked(self):
        inp = {"action": "build"}
        self.assertEqual(fanout.fold_fast_sourcing(inp), 0)
        self.assertNotIn("config", inp)
        for no in (False, 0, "0", "false", "off", None, 1):
            self.assertEqual(fanout.fast_parts({"fast_sourcing": no}), 0, no)

    def test_true_is_the_default_parts_and_one_round(self):
        inp = {"action": "build", "fast_sourcing": True, "config": {"CLIPS_FIRST": 1}}
        with mock.patch.object(config, "FAST_SOURCING_PARTS", 4):
            self.assertEqual(fanout.fold_fast_sourcing(inp), 4)
        self.assertEqual(inp["config"]["BUILD_FANOUT"], "1")
        self.assertEqual(inp["config"]["SOURCE_PARTS"], "4")
        self.assertEqual(inp["config"]["SOURCE_PART_ROUNDS"], "1")
        self.assertEqual(inp["config"]["CLIPS_FIRST"], 1)          # the job's own overrides kept

    def test_number_capped_and_switch_off(self):
        with mock.patch.object(config, "FAST_SOURCING_MAX_PARTS", 6):
            self.assertEqual(fanout.fast_parts({"fast_sourcing": 3}), 3)
            self.assertEqual(fanout.fast_parts({"fast_sourcing": 40}), 6)
        with mock.patch.object(config, "FAST_SOURCING", False):
            self.assertEqual(fanout.fast_parts({"fast_sourcing": True}), 0)

    def test_only_plans_and_builds(self):
        inp = {"action": "render", "fast_sourcing": True}
        self.assertEqual(fanout.fold_fast_sourcing(inp), 0)
        self.assertNotIn("config", inp)

    def test_parts_never_touch_the_render_chunk_cap(self):
        with mock.patch.object(config, "FANOUT_PARTS", 1), mock.patch.object(config, "SOURCE_PARTS", 4):
            self.assertEqual(fanout.source_parts(), 4)
        with mock.patch.object(config, "FANOUT_PARTS", 10), mock.patch.object(config, "SOURCE_PARTS", 0):
            self.assertEqual(fanout.source_parts(), 10)

    def test_deadline_is_the_share_of_lines(self):
        with mock.patch.multiple(config, SINGLE_PASS1_PER_SCENE=12.0, SINGLE_TAIL_SECONDS=600.0,
                                 FAST_SOURCING_MIN_SECONDS=900.0, SOURCE_BUDGET_BASE_SECONDS=180.0,
                                 SOURCE_BUDGET_PER_SCENE=20.0, SOURCE_BUDGET_MAX_SECONDS=2400.0,
                                 SOURCE_BUDGET_MAX_PER_SCENE=18.0, SOURCE_BUDGET_CEILING_SECONDS=5400.0):
            self.assertEqual(fanout.fast_deadline(200, 4), 1200.0)      # 200 / 4 x 12 + 600
            self.assertEqual(fanout.fast_deadline(40, 4), 900.0)        # the floor
            self.assertLessEqual(fanout.fast_deadline(2000, 2), fanout.source_budget(2000))
            # Far shorter than the same video's one-machine deadline.
            self.assertLess(fanout.fast_deadline(200, 4), fanout.single_machine_deadline(200))

    def test_readiness_counts_the_jobs_parts(self):
        with mock.patch.object(config, "FANOUT_PARTS", 1), mock.patch.object(config, "SOURCE_PARTS", 0):
            self.assertIn("worker_slots_must_be_at_least_2", fanout.readiness(50)["missing"])
        with mock.patch.object(config, "FANOUT_PARTS", 1), mock.patch.object(config, "SOURCE_PARTS", 4):
            self.assertNotIn("worker_slots_must_be_at_least_2", fanout.readiness(50)["missing"])


if __name__ == "__main__":
    unittest.main()


class TidyIntermediate(unittest.TestCase):
    """A section cut again at once by tidy_clip is fetched near-lossless and cheap (DOWNLOAD_TIDY_FAST)."""

    def args(self, tidy, audio=False, hero=False, on=True):
        token = ytdlp.TIDY_INTERMEDIATE.set(tidy)
        try:
            with mock.patch.multiple(config, DOWNLOAD_TIDY_FAST=on, DOWNLOAD_TIDY_PRESET="ultrafast",
                                     DOWNLOAD_TIDY_CRF=12, DOWNLOAD_CRF=16, DOWNLOAD_PRESET="medium",
                                     DOWNLOAD_THREADS=0):
                return ytdlp._encode_args(audio=audio, hero=hero)
        finally:
            ytdlp.TIDY_INTERMEDIATE.reset(token)

    def test_tidied_section_is_the_fast_intermediate(self):
        a = self.args(True)
        self.assertIn("-preset ultrafast", a)
        self.assertIn("-crf 12", a)
        self.assertIn("-pix_fmt yuv420p", a)

    def test_everything_else_keeps_the_medium_encode(self):
        for kw in ({"tidy": False}, {"tidy": True, "audio": True}, {"tidy": True, "hero": True},
                   {"tidy": True, "on": False}):
            a = self.args(**kw)
            self.assertIn("-preset medium", a, kw)
            self.assertIn("-crf 16", a, kw)

    def test_fetch_clean_clip_marks_only_its_own_download(self):
        from src import media
        seen = []

        def fake_retry(vid, out_dir, start, seconds, title=""):
            seen.append(ytdlp.TIDY_INTERMEDIATE.get())
            return ""
        with mock.patch.object(media, "_yt_fetch_retry", fake_retry), \
                mock.patch.multiple(config, CLEAN_CUTS=True, CUT_MARGIN_SECONDS=2.0):
            self.assertEqual(media.fetch_clean_clip("abcdefghijk", ".", 10.0, 5.0), ("", True, 0))
        with mock.patch.object(media, "_yt_fetch_retry", fake_retry), \
                mock.patch.multiple(config, CLEAN_CUTS=False):
            media.fetch_clean_clip("abcdefghijk", ".", 10.0, 5.0)
        self.assertEqual(seen, [True, False])            # no cut after it: the medium encode
        self.assertFalse(ytdlp.TIDY_INTERMEDIATE.get())  # put back


class RemoteSpares(unittest.TestCase):
    """A part's spares reach the parent's bank without their files and are fetched only when tried."""

    def setUp(self):
        from src import spares
        self.spares = spares
        spares.reset()

    def tearDown(self):
        self.spares.reset()

    def test_export_add_and_lazy_fetch(self):
        import tempfile
        sp = self.spares
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "yt_abcdefghijk_12000_9000_ff00aa.mp4")
            with open(src, "wb") as fh:
                fh.write(b"x" * 2000)
            verdict = {"description": "Hoover Dam spillway water rushing", "quality": 0.8, "score": 0.7}
            with mock.patch.object(config, "SPARE_BANK", True):
                self.assertTrue(sp.record(src, verdict, label="YouTube: Hoover Dam flood"))
                with mock.patch("src.filters._video_seconds", return_value=8.5):
                    out = sp.export()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["vid"], "abcdefghijk")
            self.assertEqual(out[0]["seconds"], 8.5)
            self.assertNotIn("path", out[0])
            sp.reset()
            with mock.patch.object(config, "SPARE_BANK", True):
                self.assertEqual(sp.add_remote(out), 1)
                self.assertEqual(sp.add_remote(out), 0)            # once
                job = {"index": 3, "context": "the Hoover Dam spillway", "subject": "Hoover Dam", "place": ""}
                got = sp.candidates(job)
            self.assertEqual(len(got), 1)
            self.assertTrue(got[0]["remote"])
            self.assertEqual(got[0]["path"], "")
            fetched = os.path.join(d, "f.mp4")
            with open(fetched, "wb") as fh:
                fh.write(b"y")
            from src import media
            with mock.patch.object(media, "fetch_clean_clip", return_value=(fetched, True, 0)) as fc:
                self.assertEqual(sp.fetch_remote(got[0], d), fetched)
                fc.assert_called_once()
                self.assertEqual(fc.call_args[0][0], "abcdefghijk")
                self.assertEqual(fc.call_args[0][3], 8.5)
                self.assertEqual(sp.fetch_remote(dict(got[0], path=fetched), d), fetched)   # not again
            self.assertEqual(sp.stats().get("remoteFetched"), 1)

    def test_bad_entries_ignored(self):
        with mock.patch.object(config, "SPARE_BANK", True):
            self.assertEqual(self.spares.add_remote([{"key": "x", "kind": "video"}, "junk", {"kind": "image"}]), 0)
            self.assertEqual(self.spares.add_remote(None), 0)
