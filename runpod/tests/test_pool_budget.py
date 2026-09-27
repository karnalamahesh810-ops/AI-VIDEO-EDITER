import os
import tempfile
import threading
import unittest
from unittest import mock

from src import config, media
from src.intent import SceneIntent

INTENT = SceneIntent(entities=["Lake Mead"], locations=["Nevada"], visual_subjects=["low water"],
                     time_context="current", specificity="location")


def _rows(ids):
    return [{"id": i, "title": f"Lake Mead low water {i}", "duration": 300, "aspect": 1.78} for i in ids]


class Budget(unittest.TestCase):
    def _clip(self, d, rows_by_variant, verdict_score=0.85, fetched=None, judged=None, scouted=None,
              budget=16, used=None):
        fetched = fetched if fetched is not None else []
        scouted = scouted if scouted is not None else []

        def cands(target, require_cc, subject="", variant=""):
            return rows_by_variant.get(variant, rows_by_variant.get("*", []))

        def scout(candidate, grab, intent, context):
            scouted.append(candidate["id"])
            media._count_judged()
            return {"start": 30.0, "score": 0.8, "description": "d", "tile": 3}

        def fetch(vid, out_dir, point, grab, title):
            fetched.append(vid); p = os.path.join(d, f"yt_{vid}_{int(point)}_7.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p

        def gate(path, intent, context, label):
            return verdict_score >= 0.7, {"score": verdict_score, "quality": 0.8, "description": "d",
                                          "has_text_or_watermark": False, "is_talking_head": False, "model": "m"}
        with mock.patch.object(config, "CANDIDATE_POOL", True), \
                mock.patch.object(config, "POOL_EXTRA_QUERIES", 0), \
                mock.patch.object(config, "JUDGE_BEST_OF", 2), \
                mock.patch.object(config, "JUDGE_MAX_PER_SCENE", budget), \
                mock.patch.object(config, "MOMENT_FINE_PASS", False), \
                mock.patch.object(media, "_story_channels", return_value=[]), \
                mock.patch.object(media, "_yt_candidates_cached", cands), \
                mock.patch.object(media, "_scout", scout), \
                mock.patch.object(media, "_yt_fetch_retry", fetch), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_vision_gate", gate), \
                mock.patch.object(config, "MOMENT_SELECTION", True), \
                mock.patch.object(media.vision, "enabled", return_value=True):
            media.set_youtube_only(True)         # no other providers (they would hit the network)
            try:
                return media.source_for_segment("Lake Mead low water", 6.0, d, used=used,
                                                fallbacks=["Lake Mead drought", "Lake Mead 2026"],
                                                intent="Lake Mead low water aerial", context="c",
                                                scene_intent=INTENT.to_dict())
            finally:
                media.set_youtube_only(False)

    def test_fallback_searches_only_scout_new_videos(self):
        d = tempfile.mkdtemp()
        scouted, fetched = [], []
        # Every search returns the same three videos; all get rejected by the judge.
        asset = self._clip(d, {"*": _rows(["A0000000000", "B0000000000", "C0000000000"])},
                           verdict_score=0.4, fetched=fetched, scouted=scouted)
        self.assertIsNone(asset)
        self.assertEqual(sorted(scouted), ["A0000000000", "B0000000000", "C0000000000"])   # each once
        self.assertEqual(sorted(fetched), ["A0000000000", "B0000000000", "C0000000000"])

    def test_a_near_miss_is_kept_as_best_available_when_nothing_passes(self):
        d = tempfile.mkdtemp()
        fetched = []
        # Every judged clip scores 0.6: under the 0.70 floor, above the soft floor.
        asset = self._clip(d, {"*": _rows(["A0000000000", "B0000000000"])}, verdict_score=0.6, fetched=fetched)
        self.assertIsNotNone(asset)
        self.assertTrue(asset.review_required)
        self.assertIn("Best available", asset.review_reason)
        self.assertAlmostEqual(asset.relevance_score, 0.6, places=2)
        self.assertTrue(os.path.isfile(asset.local_path))
        # A clear rejection never qualifies, however it scores.
        with mock.patch.object(config, "VISION_SOFT_MIN_SCORE", 0.65):
            self.assertIsNone(self._clip(tempfile.mkdtemp(), {"*": _rows(["C0000000000"])}, verdict_score=0.6))

    def test_the_budget_counts_scouting_and_stops_the_scene(self):
        d = tempfile.mkdtemp()
        scouted, fetched = [], []
        ids = [f"V{i:010d}" for i in range(12)]
        asset = self._clip(d, {"plain": _rows(ids[:6]), "broll": _rows(ids[6:])},
                           verdict_score=0.4, fetched=fetched, scouted=scouted, budget=6)
        self.assertIsNone(asset)
        # 6 calls in total: scouts plus judgements, never 12 scouts.
        self.assertLessEqual(len(scouted) + len(fetched), 6)
        self.assertGreaterEqual(len(fetched), 1)

    def test_parallel_scenes_do_not_download_the_same_video(self):
        d = tempfile.mkdtemp()
        media.reset_cache()
        fetched = []
        lock = threading.Lock()
        gate_started = threading.Event()

        def cands(target, require_cc, subject="", variant=""):
            return _rows(["SAME0000000", "OTHER000000"])

        def fetch(vid, out_dir, point, grab, title):
            with lock:
                fetched.append(vid)
            p = os.path.join(d, f"yt_{vid}_{int(point)}_7_{threading.get_ident()}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p

        def gate(path, intent, context, label):
            gate_started.set()
            gate_started.wait(1.0)
            return True, {"score": 0.95, "quality": 0.8, "description": "d",
                          "has_text_or_watermark": False, "is_talking_head": False, "model": "m"}
        results = []

        def one():
            results.append(media.source_for_segment("Lake Mead", 6.0, d, used=set(),
                                                    intent="x", context="c"))
        # Patched once, on this thread, around both workers: patches entered
        # from two threads restore each other's fakes as "the original".
        with mock.patch.object(config, "CANDIDATE_POOL", True), \
                mock.patch.object(config, "POOL_EXTRA_QUERIES", 0), \
                mock.patch.object(config, "MOMENT_FINE_PASS", False), \
                mock.patch.object(config, "MOMENT_SELECTION", False), \
                mock.patch.object(media, "_story_channels", return_value=[]), \
                mock.patch.object(media, "_yt_candidates_cached", cands), \
                mock.patch.object(media, "_yt_fetch_retry", fetch), \
                mock.patch.object(media, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_vision_gate", gate):
            media.set_youtube_only(True)
            threads = [threading.Thread(target=one) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
            media.set_youtube_only(False)
        ids = sorted(a.identity for a in results if a)
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids, ["yt:OTHER000000", "yt:SAME0000000"])   # one each, never the same twice


class ScoutMemo(unittest.TestCase):
    def test_a_video_is_scouted_once_per_intent_per_job(self):
        media.reset_cache()
        calls = []
        with mock.patch.object(media, "_yt_info", return_value=({"id": "V", "width": 1920, "height": 1080}, "")), \
                mock.patch.object(media.moments, "pick", side_effect=lambda *a, **k: calls.append(1) or {"start": 1.0, "score": 0.8, "description": "d", "tile": 1}), \
                mock.patch.object(config, "MOMENT_SELECTION", True), \
                mock.patch.object(media.vision, "enabled", return_value=True):
            a = media._scout({"id": "V00000000000"}, 7.0, "Lake Mead", "c")
            b = media._scout({"id": "V00000000000"}, 7.0, "Lake Mead", "c")
            c = media._scout({"id": "V00000000000"}, 7.0, "Hoover Dam", "c")
        self.assertEqual(len(calls), 2)
        self.assertEqual(a, b)
        self.assertIsNotNone(c)


if __name__ == "__main__":
    unittest.main()
