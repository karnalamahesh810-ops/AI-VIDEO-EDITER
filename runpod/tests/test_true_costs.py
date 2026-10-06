"""
The cost ledger says what a video really cost (src/costs.py, 2026-10-06).

The cost audit of 2026-10-05 found the ledger off from the RunPod bill: the
app's price table priced a serverless second at $0.000136 ($0.49/h; the bill
says $0.576/h) and a pod's seconds the same, a retired SERP call at $0.0015
(about $1 of a video that was never paid), and the helper workers of a spread
render were not in it at all. Now: the machine's own rate (a serverless worker,
or a pod at its own price, its start-up included), the render chunks' worker
time, and each AI call at its provider's price or - when the provider did not
say - its credit estimate.
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import handler  # noqa: E402
import pod_job  # noqa: E402
from src import costs, fanout  # noqa: E402
from tests.test_render_chunks import FakeWorkers, _doc  # noqa: E402
from tests.test_render_one_machine import _spread  # noqa: E402

SERVERLESS = 0.576 / 3600


class _Clean(unittest.TestCase):
    def setUp(self):
        costs.use_serverless()
        costs.reset()

    def tearDown(self):
        costs.use_serverless()
        costs.reset()


class MachineRate(_Clean):
    def test_a_serverless_worker_is_priced_at_its_real_rate_whatever_the_apps_table_says(self):
        costs.reset({"runpod.worker_second": 0.000136})          # the app's provider_prices row
        s = costs.summary(worker_seconds=3600)
        self.assertAlmostEqual(s["runpod"], 0.576)
        self.assertEqual(s["machine"], "serverless")
        self.assertEqual(s["worker_usd_per_hour"], 0.576)

    def test_a_pod_is_priced_at_its_own_price_and_its_helpers_at_a_workers(self):
        costs.use_pod(1.28, source="runpod")                      # a 32-vCPU cpu3g pod
        costs.reset()
        costs.absorb({"units": {}, "worker_seconds": 1800})       # render helpers: serverless workers
        s = costs.summary(worker_seconds=3600)
        self.assertAlmostEqual(s["runpod"], round(1.28 + 1800 * SERVERLESS, 4))
        self.assertEqual(s["machine"], "pod")
        self.assertEqual(s["machine_usd_per_hour"], 1.28)
        self.assertEqual(s["machine_price_source"], "runpod")
        self.assertEqual(s["worker_seconds"], 5400.0)

    def test_a_pod_whose_price_is_not_known_is_priced_as_a_16_vcpu_pod(self):
        costs.use_pod(None)
        costs.reset()
        s = costs.summary(worker_seconds=3600)
        self.assertAlmostEqual(s["runpod"], costs.DEFAULT_POD_USD_PER_HOUR)
        self.assertEqual(s["machine_price_source"], "default")
        for bad in (0, -1, float("nan"), "x"):
            costs.use_pod(bad)
            self.assertIsNone(costs.machine()["usd_per_hour"])

    def test_the_pods_start_up_is_charged_once_to_its_first_job(self):
        costs.use_pod(0.48, boot_seconds=120)
        costs.reset()
        self.assertEqual(costs.charge_machine_start(), 120)
        s = costs.summary(worker_seconds=600)
        self.assertEqual(s["boot_seconds"], 120.0)
        self.assertEqual(s["own_seconds"], 720.0)
        self.assertAlmostEqual(s["runpod"], round(720 * 0.48 / 3600, 4))
        costs.reset()                                             # a batch's next video
        self.assertEqual(costs.charge_machine_start(), 0)
        self.assertNotIn("boot_seconds", costs.summary(worker_seconds=600))

    def test_the_handler_charges_the_start_up_to_its_job(self):
        costs.use_pod(0.48, boot_seconds=90)
        out = handler.handler({"id": "job-h", "input": {"action": "nonsense"}})
        self.assertFalse(out["ok"])
        self.assertEqual(costs.LEDGER.boot_seconds, 90)

    def test_serp_calls_cost_nothing(self):
        costs.reset({"serp.call": 0.0015})                        # the app's table still says $0.0015
        costs.record("serp.call", 700)
        s = costs.summary(worker_seconds=0)
        self.assertEqual(s["serp"], 0.0)
        self.assertEqual(s["total"], 0.0)


class AiCalls(_Clean):
    def test_calls_a_provider_priced_count_at_that_price_and_the_rest_are_estimated(self):
        # Ten judged clips: six answered by OpenRouter with their price, four by the Kie
        # fallback (no price in its answer). The four cost credits all the same.
        costs.record("vision.judge", 10)
        for _ in range(6):
            costs.record("vision.usd", 0.001)
        s = costs.summary(worker_seconds=0)
        self.assertAlmostEqual(s["vision"], round(0.006 + 4 * 0.5 * 0.005, 4))
        self.assertTrue(s["vision_measured"])

    def test_the_planners_measured_price_is_what_the_video_cost(self):
        for usd in (0.041, 0.037, 0.044):                         # three planning calls on OpenRouter
            costs.record("llm.usd", usd)
            costs.record("llm.director_call")
        doc = {"meta": {}}
        with mock.patch.object(handler.media, "proxy_snapshot", return_value={}):
            summary = handler._finish_costs(doc, time.time())
        self.assertAlmostEqual(summary["llm"], 0.122)
        self.assertTrue(summary["llm_measured"])
        self.assertIs(doc["meta"]["costs"], summary)
        self.assertAlmostEqual(doc["meta"]["costs"]["total"],
                               sum(summary[c] for c in ("runpod", "vision", "llm", "image", "proxy", "serp",
                                                         "storage", "tts", "other")), places=4)

    def test_an_older_workers_priced_summary_still_replaces_its_estimate(self):
        # A fan-out part on an image from before priced answers were counted.
        costs.absorb({"units": {"vision.judge": 40, "vision.usd": 0.03}, "worker_seconds": 0})
        s = costs.summary(worker_seconds=0)
        self.assertAlmostEqual(s["vision"], 0.03)

    def test_a_childs_counted_answers_join_the_parents(self):
        costs.absorb({"units": {"vision.judge": 40, "vision.usd": 0.03, "vision.measured": 40}, "worker_seconds": 0})
        costs.record("vision.judge", 2)                           # the parent's two, unpriced
        s = costs.summary(worker_seconds=0)
        self.assertAlmostEqual(s["vision"], round(0.03 + 2 * 0.5 * 0.005, 4))


class Children(_Clean):
    def test_a_child_that_returned_nothing_is_still_billed_for_its_time(self):
        costs.absorb(None, billed_seconds=300)                    # a failed chunk: RunPod's executionTime
        costs.absorb({"units": {}, "worker_seconds": 50}, billed_seconds=80)    # the larger counts
        costs.absorb(None)                                        # nothing known: nothing counted
        s = costs.summary(worker_seconds=0)
        self.assertEqual(s["children"], 2)
        self.assertEqual(s["worker_seconds"], 380.0)


class _Billed(FakeWorkers):
    """The endpoint as RunPod answers it: a finished job says how long it ran, and a chunk returns its costs."""

    def status(self, jid):
        st = super().status(jid)
        if st.get("status") == "COMPLETED" and isinstance(st.get("output"), dict) and st["output"].get("ok"):
            return dict(st, executionTime=90_000,
                        output=dict(st["output"], costs={"units": {}, "worker_seconds": 80.0, "total": 0.0128}))
        if st.get("status") == "FAILED":
            return dict(st, executionTime=30_000)
        return st


class SpreadRenderChunks(_Clean):
    def test_every_helper_workers_job_is_in_the_ledger(self):
        # Four chunks: the parent draws the first, chunk 2's worker fails (30 s billed,
        # drawn again here), chunks 1 and 3 come back (90 s each, as RunPod says).
        workers = _Billed({2: "fail"})
        out, calls = _spread(_doc([150] * 16), workers)
        self.assertTrue(out.get("ok"), out)
        s = costs.summary(worker_seconds=0)
        self.assertEqual(s["children"], 3)
        self.assertEqual(s["worker_seconds"], 210.0)
        self.assertAlmostEqual(s["runpod"], round(210 * SERVERLESS, 4))
        self.assertEqual(calls["stats"]["workerSeconds"], 210.0)

    def _runner(self):
        doc = _doc([150] * 4)
        return fanout._PodRender(doc, [(0, 299), (300, 599)], fps=30, total=600, prefix="chunks/x/", tl_key="k",
                                 tl_url="u", job_id="j", work=tempfile.mkdtemp(), report=lambda *a, **k: None)

    def test_a_job_dropped_while_it_ran_is_billed_for_the_time_it_ran_once(self):
        with mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp"), \
                mock.patch.object(fanout, "_pod_cancel"):
            r = self._runner()
            c = r.chunks[1]
            c.job, c.started_at = "job-1", time.time() - 42
            with r.lock:
                r._drop_worker(c, "", cancel=True)                # the pod drew it first
                c.job = "job-1"
                r._bill(c, {"status": "COMPLETED", "executionTime": 50_000}, {"ok": True})   # never twice
                c.job, c.started_at = "job-2", 0.0
                r._drop_worker(c, "", cancel=True)                # queued, never started: cost nothing
        s = costs.summary(worker_seconds=0)
        self.assertEqual(s["children"], 1)
        self.assertAlmostEqual(s["worker_seconds"], 42.0, delta=1.0)


class PodPrice(unittest.TestCase):
    def test_the_launchers_price_wins(self):
        with mock.patch.dict(os.environ, {"POD_COST_PER_HR": "0.96"}), \
                mock.patch.object(pod_job.requests, "get", side_effect=AssertionError("not asked")):
            self.assertEqual(pod_job.pod_price(), (0.96, "POD_COST_PER_HR"))

    def test_else_the_pods_own_runpod_record(self):
        record = mock.Mock(status_code=200, json=mock.Mock(return_value={"id": "p9", "costPerHr": 1.28,
                                                                          "env": {"SECRET": "x"}}))
        with mock.patch.dict(os.environ, {"POD_COST_PER_HR": "", "RUNPOD_POD_ID": "p9", "POD_STOP_KEY": "k"}), \
                mock.patch.object(pod_job.requests, "get", return_value=record) as get:
            self.assertEqual(pod_job.pod_price(), (1.28, "runpod"))
        self.assertTrue(get.call_args.args[0].endswith("/v1/pods/p9"))

    def test_nothing_known_is_none(self):
        bad = mock.Mock(status_code=500, json=mock.Mock(return_value={}))
        with mock.patch.dict(os.environ, {"POD_COST_PER_HR": "free", "RUNPOD_POD_ID": "p9", "POD_STOP_KEY": "k"}), \
                mock.patch.object(pod_job.requests, "get", return_value=bad):
            self.assertEqual(pod_job.pod_price(), (None, ""))
        with mock.patch.dict(os.environ, {"POD_COST_PER_HR": "", "RUNPOD_POD_ID": ""}):
            self.assertEqual(pod_job.pod_price(), (None, ""))

    def test_the_pod_job_prices_its_pod_before_the_job(self):
        try:
            with mock.patch.object(pod_job, "pod_price", return_value=(0.64, "runpod")), \
                    mock.patch.object(pod_job, "container_age", return_value=75.0):
                pod_job.price_this_pod()
            m = costs.machine()
            self.assertEqual((m["kind"], m["usd_per_hour"], m["boot"]), ("pod", 0.64, 75.0))
        finally:
            costs.use_serverless()


class FailedJobsCostToo(_Clean):
    def test_a_failed_jobs_answer_carries_what_it_cost(self):
        def boom(inp, work, report):
            costs.record("vision.judge", 4)
            raise RuntimeError("no footage")
        with mock.patch.object(handler, "_require_ai_credit"), mock.patch.object(handler, "do_plan", side_effect=boom):
            out = handler.handler({"id": "job-f", "input": {"action": "plan", "allow_youtube": False}})
        self.assertFalse(out["ok"])
        self.assertIn("costs", out)
        self.assertAlmostEqual(out["costs"]["vision"], 4 * 0.5 * 0.005)


if __name__ == "__main__":
    unittest.main()
