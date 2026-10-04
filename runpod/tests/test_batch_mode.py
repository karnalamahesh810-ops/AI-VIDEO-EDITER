"""
Batch mode (src/batch.py, the handler's action "batch"): several videos as one job, built one after another
through the same handler dispatch.

  * order: the builds run in the order given, each as a normal "build" with its own input (the batch's
    "defaults" under it), never as another action, never nested;
  * continue on failure: a failed build (a result with an error, or a build that raises) is recorded and the
    next one starts;
  * the summary: {done, failed: [{project, error}], total_cost (failed builds cost too), seconds}, the event
    batch/summary, ok only when every video is done;
  * the rows: waiting projects say "Waiting for its turn"; each video's final state is written into its project
    by the batch (the timeline first, then the status), waited for and retried;
  * parallel: never more than config.BATCH_MAX_PARALLEL (1) or IN_PROCESS (1), whatever is asked;
  * the dispatch: handler.handler hands a "batch" input to batch.run with the job's id.
"""
import unittest
from unittest import mock

from src import batch, config, events, storage


def _build_factory(log, fail=(), raise_on=(), cost=0.5):
    """A stand-in for handler.handler: records what it was given, fails or raises where told."""
    def build(job):
        inp = job["input"]
        pid = inp.get("project_id")
        log.append({"id": job["id"], "input": inp, "webhook": job.get("webhook")})
        if pid in raise_on:
            raise RuntimeError(f"crash on {pid}")
        if pid in fail:
            return {"ok": False, "error": f"no footage for {pid}", "elapsed": 1.0}
        return {"ok": True, "action": "build", "video_url": f"https://r2/{pid}.mp4", "duration": 61.4,
                "object_path": f"projects/{pid}/final.mp4", "timeline": {"scenes": [1, 2], "fps": 30},
                "render_manifest": {"chunks": 2}, "costs": {"total": cost}, "elapsed": 1.0}
    return build


JOBS = [{"project_id": "p1", "audio_url": "a1"}, {"project_id": "p2", "audio_url": "a2"},
        {"project_id": "p3", "audio_url": "a3"}]


class Running(unittest.TestCase):
    def setUp(self):
        self.patches = [mock.patch.object(storage, "patch_project", return_value=True),
                        mock.patch.object(storage, "broker_enabled", return_value=False),
                        mock.patch.object(config, "SUPABASE_URL", ""), mock.patch.object(config, "SUPABASE_SERVICE_KEY", "")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_builds_run_in_order_as_normal_builds_under_the_batch_job(self):
        log = []
        out = batch.run({"id": "batch-1", "webhook": "w", "input": {"action": "batch", "jobs": JOBS,
                                                                     "defaults": {"config": {"SOURCE_TAGS": True}, "prices": {"x": 1}}}},
                        _build_factory(log), sleep=lambda s: None)
        self.assertEqual([e["input"]["project_id"] for e in log], ["p1", "p2", "p3"])
        self.assertTrue(all(e["id"] == "batch-1" for e in log))          # the broker authorises by the batch's job
        self.assertTrue(all(e["webhook"] == "w" for e in log))
        for e in log:
            self.assertEqual(e["input"]["action"], "build")
            self.assertEqual(e["input"]["config"], {"SOURCE_TAGS": True})   # the defaults under each
            self.assertTrue(e["input"]["_caller_writes_result"])           # the batch records the final state
        # each video its own record in the cross-video ledger (the job id is shared)
        self.assertEqual([e["input"]["_ledger_job"] for e in log], ["batch-1-v1", "batch-1-v2", "batch-1-v3"])
        self.assertNotIn("_caller_writes_result", JOBS[0])                   # the caller's list is left alone
        self.assertNotIn("_ledger_job", JOBS[0])
        self.assertTrue(out["ok"])
        self.assertEqual(out["action"], "batch")
        self.assertEqual([d["project"] for d in out["done"]], ["p1", "p2", "p3"])
        self.assertEqual(out["failed"], [])
        self.assertEqual(out["total"], 3)
        self.assertAlmostEqual(out["total_cost"], 1.5)
        self.assertEqual(out["parallel"], 1)
        self.assertEqual(out["done"][0]["video_url"], "https://r2/p1.mp4")
        self.assertNotIn("timeline", str(out["done"]))                       # the result stays small

    def test_a_failure_does_not_stop_the_rest_and_is_in_the_summary(self):
        log = []
        with mock.patch.object(batch.costs, "summary", return_value={"total": 0.25}):
            out = batch.run({"id": "b", "input": {"jobs": JOBS}}, _build_factory(log, fail=("p2",), raise_on=("p1",)),
                            sleep=lambda s: None)
        self.assertEqual([e["input"]["project_id"] for e in log], ["p1", "p2", "p3"])
        self.assertFalse(out["ok"])
        self.assertNotIn("error", out)                                       # the batch itself ran
        self.assertEqual([d["project"] for d in out["done"]], ["p3"])
        self.assertEqual([(f["project"], f["error"]) for f in out["failed"]],
                         [("p1", "RuntimeError: crash on p1"), ("p2", "no footage for p2")])
        self.assertAlmostEqual(out["total_cost"], 0.25 + 0.25 + 0.5)          # failed builds cost too
        self.assertGreaterEqual(out["seconds"], 0.0)
        ev = events.summary()
        kinds = [r["event"] for r in ev["recent"] if r["stage"] == "batch"]
        self.assertEqual(kinds, ["job_failed", "job_failed", "job_done", "summary"])
        summary = [r for r in ev["recent"] if r["event"] == "summary"][0]
        self.assertIn("1 done, 2 failed of 3", summary["message"])
        self.assertEqual(summary["data"]["failed_projects"], ["p1", "p2"])

    def test_a_build_that_fails_early_is_not_charged_the_last_ones_costs(self):
        from src import costs
        costs.reset()
        costs.record("image.generate", 100)                     # what an earlier video left in the ledger: $2
        self.assertGreater(costs.summary(0.0)["total"], 1.0)

        def build(job):
            raise ValueError("bad brand kit")                    # before the handler's own cost reset
        out = batch.run({"id": "b", "input": {"jobs": JOBS[:1]}}, build, sleep=lambda s: None)
        self.assertLess(out["failed"][0]["cost"], 0.01)
        self.assertLess(out["total_cost"], 0.01)

    def test_entries_that_are_not_builds_fail_on_their_own(self):
        log = []
        out = batch.run({"id": "b", "input": {"jobs": [{"project_id": "p1"}, "nope", {"action": "batch", "jobs": []},
                                                        {"project_id": "p4", "action": "render"}]}},
                        _build_factory(log), sleep=lambda s: None)
        self.assertEqual([e["input"]["project_id"] for e in log], ["p1"])
        self.assertEqual([d["project"] for d in out["done"]], ["p1"])
        self.assertEqual([f["index"] for f in out["failed"]], [1, 2, 3])
        self.assertIn("not a build input", out["failed"][0]["error"])
        self.assertIn("builds only", out["failed"][1]["error"])
        self.assertIn("render", out["failed"][2]["error"])
        self.assertEqual(out["failed"][1]["cost"], 0.0)

    def test_an_empty_or_missing_list_is_refused(self):
        for inp in ({"action": "batch"}, {"action": "batch", "jobs": []}, {"action": "batch", "jobs": "p1"}):
            out = batch.run({"id": "b", "input": inp}, _build_factory([]))
            self.assertFalse(out["ok"])
            self.assertIn("jobs", out["error"])

    def test_waiting_projects_are_told_and_the_final_state_is_recorded(self):
        writes = []
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker_patch", side_effect=lambda pid, jid, f: writes.append((pid, jid, f)) or True):
            out = batch.run({"id": "b", "input": {"jobs": JOBS}}, _build_factory([], fail=("p2",)), sleep=lambda s: None)
        waiting = [call.args for call in storage.patch_project.call_args_list]
        self.assertEqual([(pid, f["current_step"]) for pid, f in waiting],
                         [("p2", "Waiting for its turn (video 2 of 3)"), ("p3", "Waiting for its turn (video 3 of 3)")])
        self.assertTrue(all(jid == "b" for _pid, jid, _f in writes))
        by_project = {}
        for pid, _jid, f in writes:
            by_project.setdefault(pid, []).append(f)
        # done: the timeline and the manifest first, then the small "video is ready" fields
        self.assertEqual([sorted(f) for f in by_project["p1"]],
                         [["render_manifest", "scene_data"],
                          ["completed_at", "current_step", "duration_seconds", "progress", "render_path", "status", "video_url"]])
        self.assertEqual(by_project["p1"][1]["status"], "done")
        self.assertEqual(by_project["p1"][1]["duration_seconds"], 61)          # an INTEGER column
        self.assertEqual(by_project["p1"][1]["video_url"], "https://r2/p1.mp4")
        # failed: the error, nothing big
        self.assertEqual(len(by_project["p2"]), 1)
        self.assertEqual(by_project["p2"][0]["status"], "failed")
        self.assertEqual(by_project["p2"][0]["error_message"], "no footage for p2")
        self.assertTrue(all(d["saved"] for d in out["done"]))
        self.assertTrue(out["failed"][0]["saved"])

    def test_a_write_that_keeps_failing_is_retried_then_given_up_and_said(self):
        clock = [1000.0]
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker_patch", return_value=False) as patch, \
                mock.patch.object(batch.time, "time", side_effect=lambda: clock[0]):
            def sleep(s):
                clock[0] += s
            out = batch.run({"id": "b", "input": {"jobs": JOBS[:1]}}, _build_factory([]), sleep=sleep)
        self.assertTrue(out["ok"])
        self.assertFalse(out["done"][0]["saved"])
        self.assertGreaterEqual(patch.call_count, 4)

    def test_without_a_place_to_write_nothing_waits(self):
        out = batch.run({"id": "b", "input": {"jobs": JOBS[:1]}}, _build_factory([]),
                        sleep=mock.Mock(side_effect=AssertionError("slept")))
        self.assertTrue(out["ok"])
        self.assertFalse(out["done"][0]["saved"])

    def test_a_shared_config_and_an_entrys_own_are_merged(self):
        log = []
        jobs = [{"project_id": "p1", "config": {"AUTO_MAPS": True}}, {"project_id": "p2"},
                {"project_id": "p3", "config": {"SOURCE_TAGS": False}}]
        batch.run({"id": "b", "input": {"jobs": jobs, "defaults": {"config": {"SOURCE_TAGS": True}, "style": "x"}}},
                  _build_factory(log), sleep=lambda s: None)
        self.assertEqual([e["input"]["config"] for e in log],
                         [{"SOURCE_TAGS": True, "AUTO_MAPS": True}, {"SOURCE_TAGS": True}, {"SOURCE_TAGS": False}])
        self.assertTrue(all(e["input"]["style"] == "x" for e in log))
        self.assertEqual(jobs[0]["config"], {"AUTO_MAPS": True})           # the caller's entries are left alone
        # a project, an action or a worker field is never a default
        log = []
        out = batch.run({"id": "b", "input": {"jobs": [{"audio_url": "a"}, {"project_id": "p2"}],
                                              "defaults": {"project_id": "p1", "action": "render", "_job_id": "x"}}},
                        _build_factory(log), sleep=lambda s: None)
        self.assertEqual([e["input"].get("project_id") for e in log], [None, "p2"])
        self.assertTrue(all(e["input"]["action"] == "build" and "_job_id" not in e["input"] for e in log))
        self.assertTrue(out["ok"])

    def test_the_same_project_twice_is_built_once_and_its_row_kept(self):
        log, writes = [], []
        jobs = [{"project_id": "p1"}, {"project_id": "p2"}, {"project_id": "p1", "audio_url": "again"}]
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker_patch", side_effect=lambda pid, jid, f: writes.append((pid, f)) or True):
            out = batch.run({"id": "b", "input": {"jobs": jobs}}, _build_factory(log), sleep=lambda s: None)
        self.assertEqual([e["input"]["project_id"] for e in log], ["p1", "p2"])     # never paid for twice
        self.assertEqual([(f["project"], f["index"]) for f in out["failed"]], [("p1", 2)])
        self.assertIn("already in this batch", out["failed"][0]["error"])
        # p1's row keeps what its build wrote: no "failed" over its "done"
        self.assertEqual([f.get("status") for pid, f in writes if pid == "p1" and "status" in f], ["done"])
        self.assertNotIn("saved", out["failed"][0])

    def test_a_batch_that_stops_on_its_own_error_leaves_no_project_waiting(self):
        writes, log = [], []
        real_one = batch._one

        def one(job, raw, defaults, n, total, build, sleep, seen):
            if n == 2:
                raise RuntimeError("worker state broke")
            return real_one(job, raw, defaults, n, total, build, sleep, seen)
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker_patch", side_effect=lambda pid, jid, f: writes.append((pid, f)) or True), \
                mock.patch.object(batch, "_one", side_effect=one):
            out = batch.run({"id": "b", "input": {"jobs": JOBS}}, _build_factory(log), sleep=lambda s: None)
        self.assertEqual([e["input"]["project_id"] for e in log], ["p1"])
        self.assertEqual([d["project"] for d in out["done"]], ["p1"])
        self.assertEqual([f["project"] for f in out["failed"]], ["p2", "p3"])
        self.assertTrue(all("the batch stopped" in f["error"] for f in out["failed"]))
        final = {pid: f["status"] for pid, f in writes if "status" in f}
        self.assertEqual(final, {"p1": "done", "p2": "failed", "p3": "failed"})

    def test_a_final_state_that_did_not_get_through_is_tried_again_at_the_end(self):
        clock = [1000.0]
        db = {"up": False}
        writes = []

        def patch(pid, jid, f):
            if db["up"]:
                writes.append((pid, f))
            return db["up"]

        def build(job):
            db["up"] = job["input"]["project_id"] == "p2"   # the database is back while video 2 runs
            return _build_factory([])(job)
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker_patch", side_effect=patch), \
                mock.patch.object(batch.time, "time", side_effect=lambda: clock[0]):
            def sleep(s):
                clock[0] += s
            out = batch.run({"id": "b", "input": {"jobs": JOBS[:2]}}, build, sleep=sleep)
        self.assertTrue(out["ok"])
        self.assertEqual([d["saved"] for d in out["done"]], [True, True])
        self.assertEqual([pid for pid, f in writes if f.get("status") == "done"], ["p2", "p1"])
        self.assertNotIn("_out", str(out))


class Parallel(unittest.TestCase):
    def test_never_more_than_the_machine_allows(self):
        self.assertEqual(config.BATCH_MAX_PARALLEL, 1)
        self.assertEqual(batch.parallel_for(4), 1)
        self.assertEqual(batch.parallel_for("x"), 1)
        self.assertEqual(batch.parallel_for(0), 1)
        with mock.patch.object(config, "BATCH_MAX_PARALLEL", 3):
            self.assertEqual(batch.parallel_for(4), batch.IN_PROCESS)        # one process: one build at a time
        with mock.patch.object(storage, "patch_project", return_value=True), \
                mock.patch.object(storage, "broker_enabled", return_value=False), \
                mock.patch.object(config, "SUPABASE_URL", ""):
            out = batch.run({"id": "b", "input": {"jobs": JOBS[:1], "max_parallel": 3}}, _build_factory([]))
        self.assertEqual(out["parallel"], 1)
        self.assertEqual(out["asked_parallel"], 3)


class ResultFields(unittest.TestCase):
    def test_done_and_failed_rows(self):
        small, big = batch.result_fields({"ok": True, "video_url": "u", "duration": 12.6, "object_path": "p",
                                          "timeline": {"a": 1}})
        self.assertEqual((small["status"], small["duration_seconds"], small["render_path"]), ("done", 13, "p"))
        self.assertEqual(big, {"scene_data": {"a": 1}})
        small, big = batch.result_fields({"ok": False, "error": "x" * 900})
        self.assertEqual(small["status"], "failed")
        self.assertEqual(len(small["error_message"]), 800)
        self.assertEqual(big, {})


class TheDispatch(unittest.TestCase):
    def test_the_handler_hands_a_batch_to_the_runner_with_its_job_id(self):
        import handler
        with mock.patch.object(handler.batch, "run", return_value={"ok": True, "action": "batch"}) as run:
            out = handler.handler({"id": "rp-7", "input": {"action": "Batch", "jobs": [{"project_id": "p1"}]}})
        self.assertEqual(out, {"ok": True, "action": "batch"})
        job, build = run.call_args.args
        self.assertEqual(job["id"], "rp-7")
        self.assertEqual(job["input"]["jobs"], [{"project_id": "p1"}])
        self.assertIs(build, handler.handler)
        # a batch job never touches the job-wide state a single build sets up
        self.assertNotIn("_job_id", job["input"])

    def test_a_batch_that_raises_still_answers(self):
        import handler
        with mock.patch.object(handler.batch, "run", side_effect=RuntimeError("boom")):
            out = handler.handler({"id": "rp-8", "input": {"action": "batch", "jobs": [{"project_id": "p1"}]}})
        self.assertEqual((out["ok"], out["action"]), (False, "batch"))
        self.assertIn("boom", out["error"])

    def test_a_video_of_a_batch_keeps_its_own_ledger_record(self):
        import handler
        doc = {"fps": 30, "scenes": [], "overlays": [], "meta": {"warnings": []}}
        out_render = {"video_url": "https://r2/v.mp4", "duration": 10.0, "object_path": "projects/p9/final.mp4"}

        def run(inp):
            with mock.patch.object(handler, "_require_ai_credit"), \
                    mock.patch.object(handler, "do_plan", return_value=dict(doc, meta={"warnings": []})), \
                    mock.patch.object(handler, "do_render", return_value=dict(out_render)), \
                    mock.patch.object(handler, "_keep_in_library"), \
                    mock.patch.object(handler.library, "record_shown"), \
                    mock.patch.object(handler.library, "start_maintenance"), \
                    mock.patch.object(handler.storage, "patch_project", return_value=True), \
                    mock.patch.object(handler.ledger, "start_loading") as load, \
                    mock.patch.object(handler.ledger, "save") as save:
                out = handler.handler({"id": "rp-9", "input": {"action": "build", "project_id": "p9",
                                                               "allow_youtube": False, "publish_media": False,
                                                               "_caller_writes_result": True, **inp}})
            self.assertTrue(out["ok"], out)
            return load.call_args.args[0], save.call_args.args[0]
        self.assertEqual(run({"_ledger_job": "rp-9-v2"}), ("rp-9-v2", "rp-9-v2"))
        self.assertEqual(run({}), ("rp-9", "rp-9"))                         # a single job: its job id, as before


if __name__ == "__main__":
    unittest.main()
