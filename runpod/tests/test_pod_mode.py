"""App-launched pods (scripts/pod_job.py) and the Animations choice (src/styles.py)."""
import base64
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pod_job  # noqa: E402
from src import styles  # noqa: E402


class LoadJob(unittest.TestCase):
    def test_a_job_url_is_fetched_and_pod_self_becomes_this_pods_id(self):
        job = {"id": "pod-self", "input": {"action": "build", "project_id": "p1"}}
        resp = mock.Mock(status_code=200, json=mock.Mock(return_value=job))
        with mock.patch.dict(os.environ, {"JOB_URL": "https://x/job.json", "RUNPOD_POD_ID": "abc123"}, clear=False), \
                mock.patch.object(pod_job.requests, "get", return_value=resp):
            got = pod_job.load_job()
        self.assertEqual(got["id"], "pod-abc123")
        self.assertEqual(got["input"]["project_id"], "p1")

    def test_a_slow_job_url_is_retried(self):
        job = {"id": "pod-x", "input": {}}
        bad, good = mock.Mock(status_code=503), mock.Mock(status_code=200, json=mock.Mock(return_value=job))
        with mock.patch.dict(os.environ, {"JOB_URL": "https://x/job.json"}, clear=False), \
                mock.patch.object(pod_job.requests, "get", side_effect=[bad, good]), \
                mock.patch.object(pod_job.time, "sleep"):
            self.assertEqual(pod_job.load_job()["id"], "pod-x")

    def test_job_b64_still_works(self):
        job = {"id": "pod-laptop", "input": {"action": "build"}}
        env = {"JOB_B64": base64.b64encode(json.dumps(job).encode()).decode()}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("JOB_URL", None)
            self.assertEqual(pod_job.load_job()["id"], "pod-laptop")


class Exit(unittest.TestCase):
    def test_terminate_deletes_and_stop_stops(self):
        ok = mock.Mock(status_code=200)
        with mock.patch.dict(os.environ, {"RUNPOD_POD_ID": "p9", "POD_STOP_KEY": "k"}, clear=False), \
                mock.patch.object(pod_job.requests, "delete", return_value=ok) as d, \
                mock.patch.object(pod_job.requests, "post", return_value=ok) as p:
            pod_job.stop_this_pod(terminate=True)
            pod_job.stop_this_pod()
        self.assertTrue(d.call_args.args[0].endswith("/pods/p9"))
        self.assertTrue(p.call_args.args[0].endswith("/pods/p9/stop"))


class Animations(unittest.TestCase):
    def test_animations_without_a_style_set_only_the_density(self):
        inp = {"graphics_density": "full"}
        self.assertEqual(styles.apply(inp), "")
        self.assertEqual(inp["config"], {"GRAPHICS_DENSITY": "rich"})

    def test_animations_beat_the_styles_default(self):
        inp = {"video_style": "news_compilation", "graphics_density": "normal"}
        styles.apply(inp)
        self.assertEqual(inp["config"]["GRAPHICS_DENSITY"], "normal")
        self.assertTrue(inp["config"]["ALLOW_VERTICAL"])            # the rest of the style stays
        auto = {"video_style": "news_compilation"}
        styles.apply(auto)
        self.assertEqual(auto["config"]["GRAPHICS_DENSITY"], "minimal")

    def test_auto_or_unknown_changes_nothing(self):
        for v in ("", "auto", "nonsense"):
            inp = {"graphics_density": v}
            styles.apply(inp)
            self.assertNotIn("config", inp)


if __name__ == "__main__":
    unittest.main()


class Batch(unittest.TestCase):
    """A batch on a pod (src/batch.py writes each video's row itself): the pod never stays up for a video of it
    that failed, and is deleted when the batch is over, whatever its videos' outcome."""

    def _main(self, out):
        import tempfile
        with tempfile.TemporaryDirectory() as keep:
            open(os.path.join(keep, "final.mp4"), "wb").close()       # the last video's copy, kept on the pod
            with mock.patch.object(pod_job, "load_job", return_value={"id": "pod-x", "input": {
                        "action": "batch", "jobs": [{"project_id": "p1"}, {"project_id": "p2"}]}}), \
                    mock.patch.object(pod_job.handler, "handler", return_value=out) as run, \
                    mock.patch.object(pod_job, "save_adhoc_result", return_value=""), \
                    mock.patch.object(pod_job, "_cancel_chunks"), \
                    mock.patch.object(pod_job, "stop_this_pod") as stop, \
                    mock.patch.object(pod_job.storage, "_broker_patch", side_effect=AssertionError("wrote a row")), \
                    mock.patch.object(pod_job.config, "RENDER_KEEP_DIR", keep), \
                    mock.patch.object(pod_job.time, "sleep", side_effect=AssertionError("stayed up")), \
                    mock.patch.dict(os.environ, {"POD_MAX_SECONDS": "0", "POD_EXIT": "terminate",
                                                 "POD_FETCH_TOKEN": ""}, clear=False):
                pod_job.main()
        run.assert_called_once()
        return stop

    def test_a_failed_video_of_a_batch_keeps_no_pod_up(self):
        stop = self._main({"ok": False, "action": "batch", "total": 2, "done": [{"project": "p1", "saved": True}],
                           "failed": [{"project": "p2", "error": "no footage", "saved": True}]})
        # Deleted, not left EXITED: a stopped pod keeps nothing (its disk is wiped) and sat in the account.
        stop.assert_called_once_with(terminate=True)

    def test_a_batch_with_every_video_done_and_saved_deletes_the_pod(self):
        stop = self._main({"ok": True, "action": "batch", "total": 2, "failed": [],
                           "done": [{"project": "p1", "saved": True}, {"project": "p2", "saved": True}]})
        stop.assert_called_once_with(terminate=True)


class Safety(unittest.TestCase):
    def test_a_job_that_cannot_load_stops_the_pod(self):
        with mock.patch.object(pod_job, "load_job", side_effect=RuntimeError("no job")), \
                mock.patch.object(pod_job, "stop_this_pod") as stop, \
                mock.patch.object(pod_job.handler, "handler") as run, \
                mock.patch.dict(os.environ, {"POD_MAX_SECONDS": "0"}, clear=False):
            pod_job.main()
        stop.assert_called_once()
        run.assert_not_called()
