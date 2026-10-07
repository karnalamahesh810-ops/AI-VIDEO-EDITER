"""
A re-clip never loses found work and never spends past a stop (2026-10-07, the California apply: cancelled at
the OpenRouter floor after 9 shots and its re-plan, it saved nothing; RunPod's cancel did not stop the worker,
which kept paying until the endpoint was emptied; its vision calls cost ~$0.0036 each with hedges).

  - the project is held from the start (recut.hold_project), the re-planned lines are saved at once, the
    shots found every SAVE_EVERY of them, and whatever there is when it stops; a failure hands it back;
  - a stop flag on R2 (reclip_project.py --stop), RunPod's own cancel or the OpenRouter floor stops it: no new
    paid step, the last resort never searches;
  - --save-replan writes ONLY the re-planned search fields; the "narrow" scope skips the pictures and the check;
  - the estimate gives the measured low / high range; a re-clip never hedges a vision call, and a build hedges
    only on a healthy OpenRouter account; the re-plan runs on a cheap model with thinking off.

Offline: the re-cut bench (tests/test_reclip.Rig) and stubs; nothing is paid.
"""
import copy
import time
import unittest
from unittest import mock

import handler
from src import config, credit, director, gapfill, recut, reclip, replan, storage, vision
from tests.test_recut import BUCKET, JOB, PID
from tests.test_reclip import Rig
from tests.test_replan import TITLE, broken_doc, model_shot


def writes_of(written):
    return [f for _pid, f in written]


class Saving(Rig):
    def test_found_shots_are_saved_in_batches_and_the_last_save_hands_the_project_back(self):
        doc = self.doc()
        with mock.patch.object(reclip, "SAVE_EVERY", 2), mock.patch.object(reclip, "SAVE_SECONDS", 3600.0):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["written"], out)
        saves = [f for f in writes_of(self.written) if "scene_data" in f]
        self.assertGreaterEqual(len(saves), 2)                               # a batch, then the last save
        for f in saves[:-1]:
            self.assertNotIn("status", f)                                    # still held by the job
            self.assertTrue(f["current_step"].startswith("Re-clipping:"))
        self.assertEqual((saves[-1]["status"], saves[-1]["current_step"]), ("editing", "Clips added"))
        new = saves[-1]["scene_data"]
        self.assertEqual(out["found"]["clips"], 5)
        clips = [s["semanticMetadata"]["assetId"] for s in new["scenes"] if s["media"]["type"] == "video"]
        self.assertEqual(len(clips), len(set(clips)))                        # a saved shot is never put twice
        self.assertEqual(sum(1 for s in new["scenes"] if (s["semanticMetadata"].get("reclip") or {})), 5)
        for s in new["scenes"]:
            self.assertTrue(s["media"]["url"].startswith("http"), s["media"]["url"])
        # The first batch is in the project with its files published before the last save.
        first = saves[0]["scene_data"]
        self.assertGreaterEqual(sum(1 for s in first["scenes"] if (s["semanticMetadata"].get("reclip") or {})), 2)

    def test_the_replanned_lines_are_saved_as_soon_as_they_are_planned(self):
        doc = broken_doc()
        for s in doc["scenes"]:
            s["semanticMetadata"]["sourceUrl"] = ""
        with mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "plan", return_value=([model_shot(i) for i in range(4)], "ai", [])):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["ok"], out)
        saves = [f for f in writes_of(self.written) if "scene_data" in f]
        self.assertEqual(saves[0]["current_step"], "Lines planned again: 3")
        self.assertNotIn("status", saves[0])
        for k in (0, 1, 3):
            self.assertEqual(saves[0]["scene_data"]["scenes"][k]["semanticMetadata"]["subject"],
                             "California snow survey")
        self.assertTrue(out["replanSaved"])
        self.assertEqual(saves[-1]["status"], "editing")

    def test_save_replan_writes_only_the_search_fields_and_searches_nothing(self):
        doc = broken_doc()
        before = copy.deepcopy(doc)
        with mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "plan", return_value=([model_shot(i) for i in range(4)], "ai", [])):
            out = handler.handler(self.job(timeline=doc, save_replan=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["written"], out)
        self.assertEqual(self.searches, [])
        saves = [f for f in writes_of(self.written) if "scene_data" in f]
        self.assertEqual(len(saves), 1)
        self.assertEqual((saves[0]["status"], saves[0]["current_step"]), ("editing", "Lines planned again: 3"))
        new = saves[0]["scene_data"]
        for s, old in zip(new["scenes"], before["scenes"]):
            self.assertEqual(s["media"], old["media"])
            self.assertEqual((s["startFrame"], s["durationInFrames"], s["text"]),
                             (old["startFrame"], old["durationInFrames"], old["text"]))
        self.assertEqual(new["overlays"], before["overlays"])
        self.assertEqual(out["fingerprintAfter"], recut.fingerprint(before))
        self.assertEqual(new["scenes"][1]["semanticMetadata"]["subject"], "California snow survey")
        self.assertEqual(new["scenes"][2], before["scenes"][2])

    def test_a_failure_after_the_hand_over_hands_the_project_back(self):
        doc = self.doc()
        with mock.patch.object(reclip.Finder, "run", side_effect=RuntimeError("worker lost")):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertFalse(out["ok"])
        last = writes_of(self.written)[-1]
        self.assertEqual(last["status"], "editing")
        self.assertIn("RuntimeError", last["current_step"])
        self.assertNotIn("scene_data", last)                                  # the last save stands


class Stopping(Rig):
    def test_a_stop_flag_stops_it_before_any_paid_step_and_what_must_go_still_goes(self):
        doc = self.doc()
        self.r2.objects[(BUCKET, reclip.stop_key(PID, JOB))] = b"{}"
        searched = []
        real = gapfill.hold_or_animate

        def last_resort(*a, **kw):
            searched.append(kw.get("search"))
            return real(*a, **kw)
        with mock.patch.object(gapfill, "hold_or_animate", side_effect=last_resort):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.searches, [])                                   # no search after the stop
        self.assertIn("stop was asked", out["stopped"])
        self.assertEqual(searched, [False])                                   # the last resort never searches
        self.assertEqual(writes_of(self.written)[-1]["status"], "editing")

    def test_the_floor_refuses_to_start(self):
        doc = self.doc()
        with mock.patch.object(reclip.Stopper, "credit_left", return_value=2.73):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                           floor_usd=3.0))
        self.assertFalse(out["ok"])
        self.assertIn("under the job's $3.00 floor", out["error"])
        self.assertEqual(self.written, [])
        self.assertEqual(self.r2.objects, {})                                 # not even the backup

    def test_the_floor_stops_it_midway_and_what_was_found_is_saved(self):
        doc = self.doc()
        left = iter([5.0, 5.0] + [2.9] * 50)
        n = {"searches": 0}
        real_search = self._search

        def search(*a, **kw):
            n["searches"] += 1
            return real_search(*a, **kw)
        with mock.patch.object(reclip.Stopper, "credit_left", side_effect=lambda: next(left)), \
                mock.patch.object(reclip, "FLOOR_CHECK_SECONDS", 0.0), \
                mock.patch.object(reclip.media, "source_for_segment", side_effect=search), \
                mock.patch.object(reclip, "SAVE_EVERY", 1):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                           floor_usd=3.0))
        self.assertTrue(out["ok"], out)
        self.assertIn("floor", out["stopped"])
        self.assertLess(n["searches"], 5)                                     # not every target was searched
        self.assertEqual(writes_of(self.written)[-1]["status"], "editing")    # what it found is in the project


class TheStopper(unittest.TestCase):
    def test_runpods_own_cancel_is_read_with_the_workers_key(self):
        class R:
            status_code = 200

            def json(self):
                return {"status": "CANCELLED"}
        with mock.patch.dict("os.environ", {"RUNPOD_AI_API_KEY": "k", "RUNPOD_ENDPOINT_ID": "ep"}), \
                mock.patch("requests.get", return_value=R()) as get, \
                mock.patch.object(reclip.r2, "enabled", return_value=False):
            st = reclip.Stopper(PID, "job-1")
            self.assertEqual(st.check(), "RunPod cancelled this job")
        self.assertIn("/v2/ep/status/job-1", get.call_args.args[0])

    def test_it_asks_the_network_at_most_every_half_minute(self):
        calls = []
        with mock.patch.object(reclip.Stopper, "_flag", side_effect=lambda: calls.append(1) or ""), \
                mock.patch.object(reclip.Stopper, "_cancelled", return_value=""):
            st = reclip.Stopper(PID, "job-1")
            for _ in range(5):
                self.assertEqual(st.check(), "")
        self.assertEqual(len(calls), 1)


class TheEstimate(Rig):
    def test_it_gives_the_measured_range_and_the_replan(self):
        targets = reclip.plan_targets(self.doc())
        est = reclip.estimate(targets, 16, checks=5, replan_lines=113, lines=167)
        self.assertLess(est["usdLow"], est["usd"])
        self.assertLess(est["usd"], est["usdHigh"])
        self.assertEqual(est["replanUsd"], [round(167 * reclip.REPLAN_USD_PER_LINE_LOW, 3),
                                            round(167 * reclip.REPLAN_USD_PER_LINE_HIGH, 3)])
        self.assertGreater(est["visionCallsHigh"], est["visionCalls"])
        tight = reclip.estimate(targets, 16, checks=5, budget=est["usdLow"])
        self.assertLess(tight["fits"], tight["targets"])                    # the cap is checked at the HIGH end

    def test_the_narrow_scope_skips_the_pictures_and_the_check(self):
        doc = self.doc()
        out = handler.handler(self.job(timeline=doc, scope="narrow"))
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["scope"], "narrow")
        self.assertEqual(out["estimate"]["checks"], 0)
        self.assertNotIn("2", [str(r["tier"]) for r in out["plan"]])
        full = handler.handler(self.job(timeline=self.doc()))
        self.assertGreater(full["estimate"]["checks"], 0)


class Hedging(unittest.TestCase):
    def setUp(self):
        credit.reset()
        self.addCleanup(credit.reset)

    def run_with(self, base, left, minimum=15.0):
        with mock.patch.object(config, "VISION_API_BASE", base), \
                mock.patch.object(config, "VISION_HEDGE_SECONDS", 12.0), \
                mock.patch.object(config, "VISION_HEDGE_MIN_CREDIT", minimum), \
                mock.patch.object(credit, "openrouter_left", return_value=left):
            return vision._hedge_seconds()

    def test_a_vision_call_hedges_only_on_a_healthy_openrouter_account(self):
        base = "https://openrouter.ai/api/v1"
        self.assertEqual(self.run_with(base, 40.0), 12.0)
        self.assertEqual(self.run_with(base, 2.73), 0.0)
        self.assertEqual(self.run_with(base, None), 0.0)                     # unknown: no hedge
        self.assertEqual(self.run_with("https://api.kie.ai/v1", None), 12.0)  # another provider: as before
        self.assertEqual(self.run_with(base, 2.73, minimum=0.0), 12.0)       # switched off: as before

    def test_a_reclip_never_hedges(self):
        self.assertEqual(reclip.RECLIP_CONFIG["VISION_HEDGE_SECONDS"], 0.0)

    def test_the_credit_is_read_once_and_cached(self):
        class R:
            def json(self):
                return {"data": {"total_credits": 10.0, "total_usage": 7.27}}
        with mock.patch.object(config, "VISION_API_BASE", "https://openrouter.ai/api/v1"), \
                mock.patch.object(config, "VISION_API_KEY", "k"), \
                mock.patch.object(credit.requests, "get", return_value=R()) as get:
            self.assertAlmostEqual(credit.openrouter_left(), 2.73)
            self.assertAlmostEqual(credit.openrouter_left(), 2.73)
        self.assertEqual(get.call_count, 1)


class ThePlannerForTheReplan(unittest.TestCase):
    def test_thinking_is_off_where_the_model_allows_it(self):
        self.assertEqual(director._openrouter_reasoning("google/gemini-2.5-flash", "none"), {"max_tokens": 0})
        self.assertEqual(director._openrouter_reasoning("google/gemini-3.8-flash", "none"), {"effort": "minimal"})
        self.assertEqual(director._openrouter_reasoning("openai/gpt-5-mini", "none"), {"effort": "minimal"})
        self.assertEqual(director._openrouter_reasoning("openai/gpt-5-mini", "low"), {"effort": "low"})

    def test_the_replan_runs_on_the_cheap_model_without_a_hedge_and_puts_the_directors_back(self):
        seen = {}

        def plan(segs, title, allow_maps=True):
            seen.update(model=config.DIRECTOR_MODEL, routine=config.DIRECTOR_ROUTINE_MODEL,
                        effort=config.DIRECTOR_REASONING_EFFORT, hedge=config.DIRECTOR_HEDGE_SECONDS,
                        fallbacks=list(config.DIRECTOR_FALLBACK_MODELS))
            return [model_shot(i) for i in range(len(segs))], "ai", []
        with mock.patch.object(config, "DIRECTOR_MODEL", "openai/gpt-5.2"), \
                mock.patch.object(config, "REPLAN_MODEL", "google/gemini-2.5-flash"), \
                mock.patch.object(config, "REPLAN_FALLBACK_MODELS", ["openai/gpt-5-mini"]), \
                mock.patch.object(config, "REPLAN_REASONING_EFFORT", "none"), \
                mock.patch.object(director, "is_configured", return_value=True), \
                mock.patch.object(director, "plan", side_effect=plan):
            out = replan.repair(broken_doc(), title=TITLE)
            self.assertEqual(config.DIRECTOR_MODEL, "openai/gpt-5.2")         # put back
        self.assertEqual(seen, {"model": "google/gemini-2.5-flash", "routine": "", "effort": "none", "hedge": 0.0,
                                "fallbacks": ["openai/gpt-5-mini"]})
        self.assertEqual(out["model"], "google/gemini-2.5-flash")


class TheHold(unittest.TestCase):
    def test_the_project_is_held_through_the_broker_before_anything_is_paid(self):
        answers = iter([False, False, True])
        said = []

        class Say:
            extra = {}

            def __call__(self, step, pct=None):
                said.append(step)
        say = Say()
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "CURRENT_JOB", ["job-1"]), \
                mock.patch.object(storage, "patch_project", side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(recut, "POLL", 0.0):
            self.assertEqual(recut.hold_project(PID, say, wait=60), (True, ""))
        self.assertEqual(say.extra["awaitHandover"]["job"], "job-1")
        self.assertIn("Waiting for the project to be handed to this job", said)

    def test_no_hand_over_in_time_spends_nothing(self):
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "CURRENT_JOB", ["job-1"]), \
                mock.patch.object(storage, "patch_project", return_value=False), \
                mock.patch.object(recut, "POLL", 0.01):
            held, why = recut.hold_project(PID, lambda *a, **k: None, wait=0.0)
        self.assertFalse(held)
        self.assertIn("nothing was spent or written", why)


if __name__ == "__main__":
    unittest.main()
