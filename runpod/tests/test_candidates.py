import os
import tempfile
import unittest
from unittest import mock

from src import candidates, config, media
from src.candidates import Candidate, CandidatePool, final_score, metadata_score, reuse_penalty
from src.intent import SceneIntent

ALBQ = SceneIntent(entities=["Albuquerque"], locations=["New Mexico"], event_type="flash flood",
                   visual_subjects=["flooded streets"], desired_shots=["aerial"],
                   time_context="current", specificity="event", generic_ok=False)


def cand(title, **kw):
    base = dict(provider="youtube", id=title[:11].replace(" ", "_"), title=title, seconds=240.0, aspect=1.78)
    base.update(kw)
    return Candidate(**base)


class MetadataScoring(unittest.TestCase):
    def test_event_place_then_state_then_generic(self):
        with mock.patch("src.intent._today") as today:
            today.return_value.year = 2026
            q = "Albuquerque flash flood aerial"
            s_event, _ = metadata_score(cand("Albuquerque flash flooding 2026 drone footage"), ALBQ, q, 6)
            s_state, _ = metadata_score(cand("New Mexico flooding aerial"), ALBQ, q, 6)
            s_generic, _ = metadata_score(cand("Massive flooding caught on camera"), ALBQ, q, 6)
            s_talk, _ = metadata_score(cand("Albuquerque flood explained | podcast"), ALBQ, q, 6)
        self.assertGreater(s_event, s_state)
        self.assertGreater(s_state, s_generic)
        self.assertGreater(s_event, s_talk)

    def test_weights_come_from_config_and_normalise(self):
        with mock.patch.object(config, "META_WEIGHTS", {"entity": 10, "semantic": 0}):
            w = candidates.meta_weights()
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertGreater(w["entity"], w["location"] * 5)
        self.assertEqual(w["semantic"], 0.0)

    def test_news_stories_weight_recency_and_place_higher(self):
        base = candidates.final_weights("")
        news = candidates.final_weights("weather")
        self.assertGreater(news["recency"], base["recency"])
        self.assertGreater(news["entity_location"], base["entity_location"])
        self.assertAlmostEqual(sum(news.values()), 1.0)


class Pool(unittest.TestCase):
    def test_dedupes_across_searches_and_skips_used_videos(self):
        pool = CandidatePool(ALBQ, "Albuquerque flash flood", 6.0, used={"yt:USED0000000"})
        rows1 = [{"id": "A0000000000", "title": "Albuquerque flooding drone", "duration": 200, "aspect": 1.78},
                 {"id": "USED0000000", "title": "Albuquerque flooding drone 2", "duration": 200, "aspect": 1.78}]
        rows2 = [{"id": "A0000000000", "title": "Albuquerque flooding drone", "duration": 200, "aspect": 1.78},
                 {"id": "B0000000000", "title": "flood", "duration": 200, "aspect": 1.78, "via": "google"}]
        self.assertEqual(pool.add(rows1, variant="plain"), 1)
        self.assertEqual(pool.add(rows2, variant="intent"), 1)
        self.assertEqual(len(pool), 2)
        self.assertEqual(pool.searches, 2)
        self.assertEqual(pool.ranked()[0].id, "A0000000000")
        self.assertEqual(pool.items["youtube:B0000000000"].via, "google")
        self.assertEqual(pool.summary()["candidates"], 2)


class FinalScore(unittest.TestCase):
    def test_visual_leads_and_specific_beats_generic_and_reuse_costs(self):
        parts = {"semantic": 0.8, "entity": 1.0, "location": 1.0, "event_time": 1.0, "source": 0.5}
        s_event, _ = final_score(0.85, 0.8, 0.9, parts, "event", "weather")
        s_generic, _ = final_score(0.85, 0.8, 0.9, parts, "generic", "weather")
        s_better_visual, _ = final_score(0.95, 0.8, 0.9, parts, "generic", "weather")
        self.assertGreater(s_event, s_generic)
        self.assertGreater(s_better_visual, s_generic)
        penalised, p = final_score(0.85, 0.8, 0.9, parts, "event", "weather",
                                   penalty=reuse_penalty("yt:X", "c", used={"yt:X"}))
        self.assertAlmostEqual(s_event - penalised, 0.15, places=6)
        self.assertEqual(p["penalty"], -0.15)
        self.assertEqual(reuse_penalty("yt:X", "chan", recent={"yt:X"}, used_channels={"chan"}), -0.35)


class PoolInYoutubeClip(unittest.TestCase):
    def test_gathers_across_variants_and_intent_queries_and_picks_the_best_final_score(self):
        d = tempfile.mkdtemp()
        searched, fetched = [], []
        rows = {
            "plain": [{"id": "GENERIC0000", "title": "Flooding aerial footage", "duration": 300, "aspect": 1.78}],
            "broll": [{"id": "GENERIC0000", "title": "Flooding aerial footage", "duration": 300, "aspect": 1.78}],
            "intent": [{"id": "ALBQ0000000", "title": "Albuquerque flash flood 2026 drone", "duration": 300, "aspect": 1.78,
                        "channel": "KOB4"}],
        }

        def cands(target, require_cc, subject="", variant=""):
            searched.append(variant)
            return rows.get(variant, [])

        def fetch(vid, out_dir, point, grab, title):
            fetched.append(vid); p = os.path.join(d, f"yt_{vid}_{int(point)}_7.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x" * 10)
            return p

        verdicts = {"GENERIC0000": 0.86, "ALBQ0000000": 0.84}

        def gate(path, intent, context, label):
            vid = os.path.basename(path)[3:14]
            return True, {"score": verdicts[vid], "quality": 0.8, "description": "d",
                          "has_text_or_watermark": False, "is_talking_head": False, "model": "m",
                          "specificity": "event" if vid.startswith("ALBQ") else "generic"}
        with mock.patch.object(config, "CANDIDATE_POOL", True), \
                mock.patch.object(config, "POOL_EXTRA_QUERIES", 2), \
                mock.patch.object(config, "JUDGE_BEST_OF", 2), \
                mock.patch.object(config, "VISION_MAX_CANDIDATES", 3), \
                mock.patch.object(media, "_story_channels", return_value=[]), \
                mock.patch.object(media, "_yt_candidates_cached", cands), \
                mock.patch.object(media, "_plan_grabs",
                                  side_effect=lambda el, grab, start, intent, ctx: [(c, 30.0, {"score": 0.8}) for c in el]), \
                mock.patch.object(media, "_yt_fetch_retry", fetch), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_vision_gate", gate), \
                mock.patch("src.intent._today") as today:
            today.return_value.year = 2026
            media.set_story_kind("weather")
            t1 = media._SCENE_INTENT.set(ALBQ.to_dict()); t2 = media._SCENE_JUDGED.set([0])
            try:
                asset = media.youtube_clip("Albuquerque flash flood aerial", d, seconds=6.0, require_cc=False,
                                           intent="Albuquerque flooding 2026", context="Flash flooding hit Albuquerque")
            finally:
                media._SCENE_JUDGED.reset(t2); media._SCENE_INTENT.reset(t1); media.set_story_kind("")
        self.assertIn("intent", searched)                      # the expanded searches ran
        self.assertGreaterEqual(searched.count("intent"), 1)
        self.assertEqual(sorted(set(fetched)), ["ALBQ0000000", "GENERIC0000"])
        # The event-specific Albuquerque clip wins on the combined score although
        # the generic flood scored a little higher on visual match alone.
        self.assertEqual(asset.identity, "yt:ALBQ0000000")
        self.assertTrue(asset.url.startswith("https://www.youtube.com/watch?v=ALBQ0000000"))
        self.assertIsNotNone(asset.final_score)
        self.assertEqual(len(asset.alternatives), 1)
        self.assertEqual(asset.alternatives[0]["assetId"], "yt:GENERIC0000")
        self.assertEqual(asset.pool["candidates"], 2)


if __name__ == "__main__":
    unittest.main()
