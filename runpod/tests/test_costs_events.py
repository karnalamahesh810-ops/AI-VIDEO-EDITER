import unittest
from unittest import mock

from src import costs, events


class LedgerTests(unittest.TestCase):
    def tearDown(self):
        costs.use_serverless()
        costs.reset()

    def test_units_are_priced_by_category_from_the_table(self):
        # The app's table (the job input's prices) sets what it may; the machine's rate and the retired
        # SERP call are the worker's own (costs._WORKER_OWNED): its $0.000136 a second and $0.0015 a call
        # were not what anything was billed.
        costs.reset({"vision.judge": 1.0, "kie.credit": 0.01, "runpod.worker_second": 0.001, "serp.call": 0.002})
        for _ in range(10):
            costs.record("vision.judge")
        costs.record("llm.director_call", 2)
        costs.record("serp.call", 3)
        costs.record("proxy.bytes", 2e9)
        costs.absorb({"units": {"vision.judge": 5, "proxy.bytes": 1e9}, "worker_seconds": 100})
        s = costs.summary(worker_seconds=50)
        self.assertAlmostEqual(s["vision"], 15 * 1.0 * 0.01)
        self.assertAlmostEqual(s["llm"], 2 * 1.0 * 0.01)
        self.assertEqual(s["serp"], 0.0)                       # no provider charges a SERP call now
        self.assertAlmostEqual(s["runpod"], round(150 * 0.576 / 3600, 4))      # a serverless worker's $0.576/h
        self.assertEqual(s["machine"], "serverless")
        self.assertEqual(s["machine_usd_per_hour"], 0.576)
        self.assertEqual(s["proxy"], 0.0)                      # ISP proxies are flat rate by default
        self.assertEqual(s["worker_seconds"], 150.0)
        self.assertEqual(s["children"], 1)
        self.assertEqual(s["units"]["vision.judge"], 15)
        self.assertEqual(s["units"]["serp.call"], 3)           # still counted
        self.assertAlmostEqual(s["credits_estimated"], 17.0)
        self.assertAlmostEqual(s["total"], s["vision"] + s["llm"] + s["serp"] + s["runpod"])

    def test_the_environment_still_sets_the_workers_own_prices(self):
        with mock.patch.dict("os.environ", {"PRICES": '{"runpod.worker_second": 0.001, "serp.call": 0.002}'}):
            costs.reset({"runpod.worker_second": 0.5})         # the table still cannot
            costs.record("serp.call", 3)
            s = costs.summary(worker_seconds=100)
        self.assertAlmostEqual(s["runpod"], 0.1)
        self.assertAlmostEqual(s["serp"], 0.006)

    def test_measured_credits_come_from_the_balance_delta(self):
        costs.reset()
        with mock.patch.object(costs, "kie_balance", side_effect=[1100.0, 1093.5]):
            costs.measure_start()
            costs.measure_end()
        s = costs.summary(1.0)
        self.assertEqual(s["credits_measured"], 6.5)
        self.assertAlmostEqual(s["measured_ai_usd"], 6.5 * 0.005)

    def test_bad_price_values_and_missing_keys_are_ignored(self):
        costs.reset({"vision.judge": "not a number", "made.up": 3})
        costs.record("vision.judge")
        self.assertEqual(costs.LEDGER.prices["vision.judge"], costs.DEFAULT_PRICES["vision.judge"])
        self.assertEqual(costs.LEDGER.prices["made.up"], 3.0)


class EventTests(unittest.TestCase):
    def test_phases_are_timed_failures_counted_and_children_absorbed(self):
        events.start_job("j1", "p1")
        # time() is read once by phase(), once per emitted event, once by summary().
        with mock.patch.object(events.time, "time",
                               side_effect=[100.0, 100.0, 103.0, 103.0, 103.0, 104.0, 104.0, 110.0]):
            events.phase("transcribe")
            events.phase("source")
            events.emit("source", "download_failed", level="warning", provider="youtube",
                        failure="MEDIA_UNAVAILABLE", scene=3, data={"video": "x"})
            events.emit("source", "download_ok", provider="youtube", scene=3)
            events.absorb({"stage_seconds": {"source": 40.0}, "failures_by_class": {"NETWORK_TIMEOUT": 2}})
            s = events.summary()
        self.assertAlmostEqual(s["stage_seconds"]["source"], 7.0)
        self.assertEqual(s["failures_by_class"], {"MEDIA_UNAVAILABLE": 1, "NETWORK_TIMEOUT": 2})
        self.assertEqual(s["providers"]["youtube"], {"failed": 1, "ok": 1})
        self.assertAlmostEqual(s["stage_seconds"]["transcribe"], 3.0)
        self.assertEqual(s["child_stage_seconds"], {"source": 40.0})
        self.assertEqual(s["recent"][-1]["scene_index"], 3)
        self.assertNotIn("job_id", s["recent"][-1])

    def test_flush_sends_once_and_a_dead_sink_is_not_retried(self):
        events.start_job("j2", "p2")
        events.emit("plan", "start")
        sent = []
        self.assertEqual(events.flush(lambda p, j, b: sent.append((p, j, len(b)))), 1)
        self.assertEqual(sent, [("p2", "j2", 1)])
        self.assertEqual(events.flush(lambda p, j, b: sent.append(1)), 0)      # nothing new
        events.emit("plan", "end")

        def dead(p, j, b):
            raise RuntimeError("no")
        self.assertEqual(events.flush(dead), 0)
        events.emit("plan", "again")
        self.assertEqual(events.flush(lambda p, j, b: sent.append(1)), 0)       # sink marked down


if __name__ == "__main__":
    unittest.main()
