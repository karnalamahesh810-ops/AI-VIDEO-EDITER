"""
The app's pods go when their job is over (scripts/pod_job.py, scripts/start_pod.sh, 2026-10-06).

Plan pods sat EXITED in the account instead of deleting themselves. The
handler's own queued "editing" write landed first; the app's broker takes a
pod's writes only while the row says "rendering", so it refused the pod's
final writes; the pod retried them for 15 minutes (billed) and, as the write
never landed, only stopped. A failed job was only stopped too (for its log),
and a pod whose pod_job.py died early sat there running. Now a plan's final
state is the pod's own write ("editing" with the timeline), every app pod is
deleted once its result is written - finished or failed - a result the
database would not take is written again while the pod stays (at most
POD_STAY_MAX_SECONDS, then a copy goes to R2), and start_pod.sh deletes a pod
its job left behind.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time as real_time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import handler  # noqa: E402
import pod_job  # noqa: E402

TIMELINE = {"fps": 30, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 90}], "meta": {}}


class Fields(unittest.TestCase):
    def test_a_plan_is_a_timeline_to_edit_never_done(self):
        fields, big = pod_job.result_fields("plan", {"ok": True, "action": "plan", "timeline": TIMELINE})
        self.assertEqual(fields, {"status": "editing", "progress": 100, "current_step": "Storyboard ready"})
        self.assertEqual(big, {"scene_data": TIMELINE})
        fields, big = pod_job.result_fields("plan", {"ok": True, "action": "plan"})
        self.assertEqual((fields["status"], fields["error_message"], big), ("failed", "The job returned no timeline.", {}))

    def test_a_build_is_done_with_its_video(self):
        out = {"ok": True, "action": "build", "timeline": TIMELINE, "video_url": "https://v/f.mp4",
               "object_path": "projects/p1/f.mp4", "duration": 720.92, "render_manifest": {"chunks": []}}
        fields, big = pod_job.result_fields("build", out)
        self.assertEqual((fields["status"], fields["video_url"], fields["duration_seconds"]),
                         ("done", "https://v/f.mp4", 721))
        self.assertEqual(set(big), {"scene_data", "render_manifest"})

    def test_a_failure_is_failed_but_a_failed_new_shot_leaves_the_project_editing(self):
        fields, big = pod_job.result_fields("build", {"ok": False, "error": "no footage"})
        self.assertEqual((fields["status"], fields["error_message"], big), ("failed", "no footage", {}))
        out = handler.resource_failed({"scene_index": 2}, "no usable media found for 'flood' - try different wording")
        fields, big = pod_job.result_fields("resource", {"ok": False, **out["result"]})
        self.assertEqual(fields["status"], "editing")
        self.assertEqual(fields["current_step"], "No new shot for scene 3")
        self.assertIn("no usable media found", fields["error_message"])


class Clock:
    """time for pod_job: sleeping moves the clock, nothing waits."""

    def __init__(self):
        self.now = 1_000_000.0
        self.slept = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept += seconds
        self.now += seconds

    strftime = staticmethod(real_time.strftime)
    gmtime = staticmethod(real_time.gmtime)


class Pod(unittest.TestCase):
    """pod_job.main end to end with the handler, the app's broker and RunPod faked."""

    def _run(self, out, action="build", accept=None, kept=False, load=None, env=None):
        clock = Clock()
        writes = []

        def broker_patch(pid, job, fields):
            writes.append((clock.now, dict(fields)))
            return True if accept is None else bool(accept(clock.now - 1_000_000.0, fields))
        keep = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, keep, True)
        if kept:
            open(os.path.join(keep, "final.mp4"), "wb").close()
        job = {"id": "pod-x", "input": {"action": action, "project_id": "p1"}}
        vals = {"POD_MAX_SECONDS": "0", "POD_EXIT": "terminate", "POD_FETCH_TOKEN": "", "POD_STAY_MAX_SECONDS": "5400"}
        vals.update(env or {})
        with mock.patch.object(pod_job, "load_job", side_effect=load or (lambda: job)), \
                mock.patch.object(pod_job.handler, "handler", return_value=out) as run, \
                mock.patch.object(pod_job, "save_adhoc_result", return_value="") as saved, \
                mock.patch.object(pod_job, "_cancel_chunks"), \
                mock.patch.object(pod_job, "price_this_pod"), \
                mock.patch.object(pod_job, "stop_this_pod") as stop, \
                mock.patch.object(pod_job.storage, "broker_enabled", return_value=True), \
                mock.patch.object(pod_job.storage, "_broker_patch", side_effect=broker_patch), \
                mock.patch.object(pod_job.config, "RENDER_KEEP_DIR", keep), \
                mock.patch.object(pod_job, "time", clock), \
                mock.patch.dict(os.environ, vals, clear=False):
            pod_job.main()
        return {"writes": writes, "stop": stop, "saved": saved, "clock": clock, "run": run}

    def test_a_plan_pod_writes_its_timeline_as_editing_and_is_deleted(self):
        got = self._run({"ok": True, "action": "plan", "timeline": TIMELINE}, action="plan")
        self.assertEqual([w for _t, w in got["writes"]],
                         [{"scene_data": TIMELINE},
                          {"status": "editing", "progress": 100, "current_step": "Storyboard ready"}])
        got["stop"].assert_called_once_with(terminate=True)
        self.assertEqual(got["clock"].slept, 0)                       # no billed tail
        self.assertTrue(got["run"].call_args.args[0]["input"]["_caller_writes_result"])

    def test_a_failed_build_pod_is_deleted_once_its_failure_is_written(self):
        got = self._run({"ok": False, "error": "no footage"})
        self.assertEqual([w["status"] for _t, w in got["writes"]], ["failed"])
        got["stop"].assert_called_once_with(terminate=True)          # was: only stopped, left EXITED
        self.assertEqual(got["clock"].slept, 0)

    def test_a_done_build_pod_is_deleted(self):
        out = {"ok": True, "action": "build", "timeline": TIMELINE, "video_url": "https://v/f.mp4", "duration": 60}
        got = self._run(out, kept=True)
        self.assertEqual([w.get("status") for _t, w in got["writes"]], [None, "done"])
        got["stop"].assert_called_once_with(terminate=True)
        self.assertEqual(got["clock"].slept, 0)

    def test_a_result_the_database_would_not_take_is_written_again_then_the_pod_goes(self):
        # The app's database is down for 25 minutes after the plan finished.
        got = self._run({"ok": True, "action": "plan", "timeline": TIMELINE}, action="plan",
                        accept=lambda t, f: t >= 1500)
        self.assertEqual([w for _t, w in got["writes"][-2:]],
                         [{"scene_data": TIMELINE},
                          {"status": "editing", "progress": 100, "current_step": "Storyboard ready"}])
        self.assertLess(got["clock"].now - 1_000_000.0, 1500 + 2 * pod_job.STAY_RETRY_SECONDS)
        got["saved"].assert_not_called()
        got["stop"].assert_called_once_with(terminate=True)

    def test_a_plans_status_waits_for_its_timeline(self):
        # The timeline write fails for 17 minutes while small writes go through: "editing" over the
        # old (empty) timeline would show a finished, empty storyboard and close the row to the pod.
        got = self._run({"ok": True, "action": "plan", "timeline": TIMELINE}, action="plan",
                        accept=lambda t, f: "scene_data" not in f or t >= 1000)
        first_ok = next(t for t, w in got["writes"] if "scene_data" in w and t - 1_000_000.0 >= 1000)
        self.assertFalse([w for t, w in got["writes"] if "status" in w and t < first_ok])
        self.assertEqual(got["writes"][-1][1]["status"], "editing")
        got["saved"].assert_not_called()
        got["stop"].assert_called_once_with(terminate=True)

    def test_a_builds_video_link_goes_in_and_a_timeline_that_did_not_is_kept_in_r2(self):
        out = {"ok": True, "action": "build", "timeline": TIMELINE, "video_url": "https://v/f.mp4", "duration": 60}
        got = self._run(out, kept=True, accept=lambda t, f: "scene_data" not in f)
        self.assertEqual(got["writes"][-1][1]["status"], "done")
        self.assertEqual(got["saved"].call_args.kwargs.get("project_id"), "p1")
        got["stop"].assert_called_once_with(terminate=True)

    def test_a_result_never_taken_is_kept_in_r2_and_the_pod_still_goes(self):
        got = self._run({"ok": True, "action": "plan", "timeline": TIMELINE}, action="plan", accept=lambda t, f: False)
        self.assertGreaterEqual(got["clock"].now - 1_000_000.0, 5400)
        self.assertLess(got["clock"].now - 1_000_000.0, 300 + 600 + 5400 + 30)
        self.assertEqual(got["saved"].call_args.kwargs.get("project_id"), "p1")
        got["stop"].assert_called_once_with(terminate=True)

    def test_a_render_that_could_not_be_saved_stays_up_at_most_its_limit_then_goes(self):
        got = self._run({"ok": False, "error": "upload failed"}, kept=True)
        failed = got["writes"][0][1]
        self.assertEqual(failed["status"], "failed")
        self.assertIn("kept on the pod", failed["error_message"])
        self.assertEqual(len(got["writes"]), 1)                       # a failure is not written again
        self.assertGreaterEqual(got["clock"].slept, 5400)             # the owner's rule: up while the video is not safe
        got["stop"].assert_called_once_with(terminate=True)

    def test_a_pod_that_cannot_load_its_job_is_deleted(self):
        def broken():
            raise RuntimeError("could not load the job from JOB_URL (HTTP 403)")
        got = self._run({}, load=broken)
        got["stop"].assert_called_once_with(terminate=True)
        got["run"].assert_not_called()

    def test_a_pod_started_by_hand_is_only_stopped(self):
        got = self._run({"ok": False, "error": "no footage"}, env={"POD_EXIT": ""})
        got["stop"].assert_called_once_with(terminate=False)


class HandlerLeavesThePlanToThePod(unittest.TestCase):
    def _plan(self, caller_writes):
        written = []
        doc = {"fps": 30, "scenes": [], "meta": {}}
        inp = {"action": "plan", "project_id": "p1", "allow_youtube": False, "publish_media": False}
        if caller_writes:
            inp["_caller_writes_result"] = True
        with mock.patch.object(handler, "_require_ai_credit"), \
                mock.patch.object(handler, "do_plan", return_value=doc), \
                mock.patch.object(handler, "_sanitize_videos"), mock.patch.object(handler, "_no_repeats"), \
                mock.patch.object(handler, "_hook_check"), mock.patch.object(handler, "_keep_in_library"), \
                mock.patch.object(handler.ledger, "note"), mock.patch.object(handler.ledger, "save") as saved, \
                mock.patch.object(handler.ledger, "start_loading"), \
                mock.patch.object(handler.library, "start_maintenance"), \
                mock.patch.object(handler.media, "proxy_snapshot", return_value={}), \
                mock.patch.object(handler.storage, "patch_project",
                                  side_effect=lambda pid, fields, wait=False: written.append(dict(fields)) or True):
            out = handler.handler({"id": "pod-x", "input": inp})
        self.assertTrue(out["ok"], out)
        saved.assert_called_once()                                    # the cross-video ledger, either way
        return [w.get("status") for w in written if w.get("status")]

    def test_on_a_pod_the_handler_writes_no_final_status(self):
        self.assertEqual(self._plan(caller_writes=True), ["rendering"])

    def test_on_serverless_it_still_does(self):
        self.assertEqual(self._plan(caller_writes=False), ["rendering", "editing"])


class StartScript(unittest.TestCase):
    PATH = os.path.join(ROOT, "scripts", "start_pod.sh")

    def test_a_pod_its_job_left_behind_is_deleted_by_the_start_script(self):
        with open(self.PATH, encoding="utf-8") as fh:
            text = fh.read()
        after = text[text.index("scripts/pod_job.py"):]
        self.assertIn('"${POD_EXIT:-}" = "terminate"', after)
        self.assertIn('-X DELETE -H "Authorization: Bearer $key"', after)
        self.assertIn('"https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID"', after)
        self.assertNotIn("echo \"$key", text)                         # the key is never printed
        for line in (ln for ln in text.splitlines() if "curl" in ln and "rest.runpod.io" in ln or "-X " in ln):
            self.assertNotIn(" -v", line)                              # a verbose curl prints its headers
            self.assertNotIn("--verbose", line)

    @unittest.skipUnless(shutil.which("sh"), "needs a POSIX shell")
    def test_the_start_script_parses(self):
        p = subprocess.run(["sh", "-n", self.PATH], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
