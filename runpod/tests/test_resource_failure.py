"""
A new shot for one scene (Replace Clip, action "resource") that cannot be found
fails that request only (2026-10-06): the job answers ok false with a plain
message - which scene, why, nothing else changed - and the project goes back to
"editing" with its timeline as it was. It used to be marked "failed" like a
broken video.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402

DOC = {"fps": 30, "meta": {}, "scenes": [
    {"id": f"s{i}", "startFrame": i * 90, "durationInFrames": 90, "text": f"line {i}", "media": {"type": "video"}}
    for i in range(3)]}


def _run(do_resource=None, credit=None, scene_index=1):
    written = []
    inp = {"action": "resource", "project_id": "p1", "timeline": DOC, "scene_index": scene_index,
           "mode": "more", "allow_youtube": False}
    with mock.patch.object(handler, "_require_ai_credit", side_effect=credit), \
            mock.patch.object(handler, "do_resource", side_effect=do_resource), \
            mock.patch.object(handler.storage, "patch_project",
                              side_effect=lambda pid, fields, wait=False: written.append(dict(fields)) or True):
        out = handler.handler({"id": "job-r", "input": inp})
    return out, [w for w in written if w.get("status")]


class FailedNewShot(unittest.TestCase):
    def test_nothing_found_fails_the_request_not_the_project(self):
        def nothing(inp, work, report):
            raise ValueError("no usable media found for 'flooded street' - try different wording")
        out, statuses = _run(nothing)
        self.assertIs(out["ok"], False)
        self.assertEqual(out["action"], "resource")
        self.assertEqual(out["scene_index"], 1)
        self.assertEqual(out["mode"], "more")
        self.assertEqual(out["project_status"], "editing")
        self.assertTrue(out["timeline_unchanged"])
        self.assertNotIn("timeline", out)                     # nothing to save over the project's
        self.assertEqual(out["error"], "Could not find a new shot for scene 2: no usable media found for "
                                       "'flooded street' - try different wording. Nothing else in the video changed.")
        self.assertIn("costs", out)
        self.assertEqual([w["status"] for w in statuses], ["rendering", "editing"])      # never "failed"
        self.assertEqual(statuses[-1], {"status": "editing", "current_step": "No new shot for scene 2",
                                        "progress": 100, "error_message": out["error"]})

    def test_a_check_that_refuses_before_the_search_is_the_same(self):
        out, statuses = _run(credit=RuntimeError("The AI account is out of credit - top it up"))
        self.assertIs(out["ok"], False)
        self.assertEqual(out["project_status"], "editing")
        self.assertIn("scene 2: The AI account is out of credit", out["error"])
        self.assertEqual(statuses[-1]["status"], "editing")

    def test_a_new_shot_found_still_saves_the_timeline(self):
        out, statuses = _run(lambda inp, work, report: (inp["timeline"], []))
        self.assertIs(out["ok"], True)
        self.assertEqual(statuses[-1]["status"], "editing")
        self.assertEqual(statuses[-1]["current_step"], "Scene re-sourced")

    def test_other_jobs_still_fail_the_project(self):
        written = []
        with mock.patch.object(handler, "_require_ai_credit"), \
                mock.patch.object(handler, "do_plan", side_effect=RuntimeError("no narration")), \
                mock.patch.object(handler.storage, "patch_project",
                                  side_effect=lambda pid, fields, wait=False: written.append(dict(fields)) or True):
            out = handler.handler({"id": "job-p", "input": {"action": "plan", "project_id": "p1",
                                                            "allow_youtube": False}})
        self.assertIs(out["ok"], False)
        self.assertNotIn("project_status", out)
        self.assertEqual([w["status"] for w in written if w.get("status")], ["rendering", "failed"])


class Message(unittest.TestCase):
    def test_says_which_scene_once(self):
        first = handler.resource_failed({"scene_index": 0}, "nothing usable.")
        self.assertEqual(first["result"]["error"], "Could not find a new shot for scene 1: nothing usable. "
                                                   "Nothing else in the video changed.")
        again = handler.resource_failed({"scene_index": 0}, first["result"]["error"])
        self.assertEqual(again["result"]["error"], first["result"]["error"])           # never wrapped twice
        self.assertEqual(handler.resource_failed({}, "x")["row"]["current_step"], "No new shot for this scene")
        self.assertIsNone(handler.resource_failed({"scene_index": True}, "x")["result"]["scene_index"])
        self.assertLessEqual(len(handler.resource_failed({"scene_index": 3}, "y" * 2000)["result"]["error"]), 800)


if __name__ == "__main__":
    unittest.main()
