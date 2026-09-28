import time
import unittest
from unittest import mock

from src import config, pools, vision, ytdlp


class AttachmentLimit(unittest.TestCase):
    def setUp(self):
        vision.reset()
        self.patches = [mock.patch.object(config, "VISION_API_KEY", "k"),
                        mock.patch.object(config, "VISION_ENABLED", True),
                        mock.patch.object(config, "VISION_MODEL", "main"),
                        mock.patch.object(config, "VISION_FALLBACK_MODELS", ["backup"]),
                        mock.patch.object(config, "VISION_RETRY_WAIT", 0),
                        mock.patch.object(config, "VISION_RETRIES", 0)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        vision.reset()

    def test_a_rate_limit_message_is_not_a_verdict(self):
        def reply(text):
            r = mock.Mock(status_code=200)
            r.json.return_value = {"choices": [{"message": {"content": text}}]}
            return r

        def post(url, json=None, **kw):
            if json["model"] == "main":
                return reply("You've hit your attachment limit. Please try again later.")
            return reply('{"score": 0.9}')

        with mock.patch.object(vision.requests, "post", side_effect=post):
            self.assertEqual(vision._ask([], 100), ('{"score": 0.9}', "backup"))
        self.assertIn("rate limited", vision.stats()["recentErrors"][0])


class PoolsStopAtTheDeadline(unittest.TestCase):
    def tearDown(self):
        ytdlp.set_deadline(0.0)

    def test_no_new_subject_after_the_sourcing_deadline(self):
        jobs = [{"index": i, "subject": "Lake Powell", "query": "lake powell", "seconds": 6,
                 "visual_type": "footage"} for i in range(3)]
        ytdlp.set_deadline(time.time() - 1)
        with mock.patch.object(pools, "plan_subject") as plan:
            got = pools.source_by_subject(jobs, "/tmp", min_scenes=1)
        plan.assert_not_called()
        self.assertEqual(got, {})

    def test_a_subject_named_once_gets_no_pool_by_default(self):
        self.assertGreaterEqual(config.POOL_MIN_SCENES, 2)


class AgentProgress(unittest.TestCase):
    def test_the_reporter_names_the_agent_and_the_estimate(self):
        import handler
        r = handler.Reporter()
        r.estimate(22 * 60)
        sent = {}
        r.job = {"id": "j"}
        with mock.patch.object(handler.runpod.serverless, "progress_update",
                               side_effect=lambda job, update: sent.update(update)):
            r("Sourcing media for 167 scenes", 22, done=0, total=167)
            first = sent["phase_started_at"]
            self.assertEqual((sent["phase"], sent["agent"]), ("source", "assets"))
            self.assertEqual(sent["estimate_minutes"], [40, 65])
            r("Keeping clips for future videos", 61)          # no prefix: stays with the last agent
            self.assertEqual((sent["agent"], sent["phase_started_at"]), ("assets", first))
            r("Designing motion graphics and animations")
            self.assertEqual(sent["agent"], "motion")
            r("Balancing the sound", 90)
            self.assertEqual(sent["agent"], "editor")
        r.finish()


if __name__ == "__main__":
    unittest.main()
