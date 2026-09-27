import os
import tempfile
import unittest
from unittest import mock

from src import config, media


def _candidates():
    return [{"id": f"vid{i}00000000"[:11], "title": f"Lake Mead aerial {i}", "duration": 300.0,
             "aspect": 1.78, "channel": "c", "url": f"https://www.youtube.com/watch?v=vid{i}00000000"[:43]}
            for i in range(1, 4)]


class BestOfN(unittest.TestCase):
    def _run(self, scores, best_of, excellent=0.9, cap=6, judged_before=0):
        d = tempfile.mkdtemp()
        fetched, verdict_iter = [], iter(scores)

        def fetch(vid, out_dir, point, grab, title):
            fetched.append(vid); p = os.path.join(d, f"yt_{vid}_{int(point)}_7.mp4")
            open(p, "wb").write(b"x" * 10); return p

        def gate(path, intent, context, label):
            s = next(verdict_iter)
            return s >= 0.7, {"score": s, "quality": 0.8, "description": f"clip {s}",
                              "has_text_or_watermark": False, "is_talking_head": False, "model": "m"}
        cands = _candidates()
        with mock.patch.object(config, "JUDGE_BEST_OF", best_of), \
                mock.patch.object(config, "EXCELLENT_SCORE", excellent), \
                mock.patch.object(config, "JUDGE_MAX_PER_SCENE", cap), \
                mock.patch.object(config, "VISION_MAX_CANDIDATES", 3), \
                mock.patch.object(media, "_story_channels", return_value=[]), \
                mock.patch.object(media, "_yt_candidates_cached", return_value=cands), \
                mock.patch.object(media, "_plan_grabs",
                                  side_effect=lambda el, grab, start, intent, ctx: [(c, 30.0, None) for c in el]), \
                mock.patch.object(media, "_yt_fetch_retry", fetch), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_vision_gate", gate):
            token = media._SCENE_JUDGED.set([judged_before])
            try:
                asset = media.youtube_clip("Lake Mead aerial", d, seconds=6.0, require_cc=False,
                                           intent="Lake Mead low water", context="x")
            finally:
                media._SCENE_JUDGED.reset(token)
        return asset, fetched, d

    def test_the_best_of_the_passing_clips_wins_and_the_rest_are_alternatives(self):
        asset, fetched, d = self._run([0.72, 0.88, 0.95], best_of=3)
        self.assertEqual(len(fetched), 3)
        self.assertAlmostEqual(asset.relevance_score, 0.95)
        self.assertEqual([a["score"] for a in asset.alternatives], [0.88, 0.72])
        self.assertTrue(os.path.exists(asset.local_path))
        self.assertEqual(len([f for f in os.listdir(d) if f.endswith(".mp4")]), 1)   # losers' files removed

    def test_best_of_two_stops_after_two_passes(self):
        asset, fetched, _ = self._run([0.72, 0.88, 0.95], best_of=2)
        self.assertEqual(len(fetched), 2)                 # the third was never judged
        self.assertAlmostEqual(asset.relevance_score, 0.88)
        self.assertEqual(len(asset.alternatives), 1)

    def test_an_excellent_clip_ends_the_search_at_once(self):
        asset, fetched, _ = self._run([0.93, 0.95, 0.99], best_of=3)
        self.assertEqual(len(fetched), 1)
        self.assertAlmostEqual(asset.relevance_score, 0.93)

    def test_a_rejected_clip_does_not_count_as_passing(self):
        asset, fetched, _ = self._run([0.4, 0.75, 0.8], best_of=2)
        self.assertEqual(len(fetched), 3)
        self.assertAlmostEqual(asset.relevance_score, 0.8)

    def test_the_per_scene_cap_stops_spending(self):
        asset, fetched, _ = self._run([0.9], best_of=2, cap=6, judged_before=6)
        self.assertIsNone(asset)
        self.assertEqual(fetched, [])


class MetadataBonus(unittest.TestCase):
    def test_titles_naming_the_entity_and_place_rank_first_on_event_scenes(self):
        si = {"entities": ["Albuquerque"], "locations": ["New Mexico"], "event_type": "flash flood",
              "visual_subjects": ["flooded streets"], "desired_shots": [], "time_context": "current",
              "specificity": "event", "generic_ok": False}
        token = media._SCENE_INTENT.set(si)
        try:
            named = media._score_candidate("Albuquerque flash flood: flooded streets aerial", 240, 1.78, 6)
            generic = media._score_candidate("Massive flooding aerial footage", 240, 1.78, 6)
        finally:
            media._SCENE_INTENT.reset(token)
        self.assertGreater(named, generic + 5)


if __name__ == "__main__":
    unittest.main()
