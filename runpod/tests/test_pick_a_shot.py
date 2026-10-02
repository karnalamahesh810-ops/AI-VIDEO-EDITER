"""
Pick-a-shot (the owner, 2026-10-02): "if I click on the clip I need to have
three options where I can switch". The judge already downloads and scores
several clips a scene and keeps the best; now the best PICK_A_SHOT_CHOICES
runner-ups keep their files, are published beside the winner (clip,
thumbnail, preview) and their links go on the scene's alternatives - the
app's plan store makes them the editor's instant choices. No new search, no
new AI call: storage only.
"""
import os
import tempfile
import unittest
from unittest import mock

import handler
from src import config, library, media


def _asset(url, score, path):
    a = media.MediaAsset(kind="video", source="youtube", url=url, local_path=path)
    a.relevance_score = score
    a.quality = 0.8
    return a


class RunnerUpsKeepTheirFiles(unittest.TestCase):
    def test_the_best_three_runner_ups_keep_their_files_the_rest_go(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [os.path.join(d, f"c{i}.mp4") for i in range(6)]
            for p in paths:
                open(p, "wb").write(b"x")
            passed = [_asset(f"https://y/{i}", 0.95 - i * 0.05, p) for i, p in enumerate(paths)]
            with mock.patch.object(config, "PICK_A_SHOT", True), mock.patch.object(config, "PICK_A_SHOT_CHOICES", 3), \
                    mock.patch.object(config, "CLIP_LIBRARY_MIN_SCORE", 2.0):
                win = media._best_of(passed)
            self.assertIs(win, passed[0])
            kept = [a for a in win.alternatives if a.get("localPath")]
            self.assertEqual(len(kept), 3)
            self.assertTrue(all(os.path.isfile(a["localPath"]) for a in kept))
            self.assertFalse(os.path.exists(paths[5]))          # the fourth runner-up's file went

    def test_off_nothing_changes(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [os.path.join(d, f"c{i}.mp4") for i in range(3)]
            for p in paths:
                open(p, "wb").write(b"x")
            passed = [_asset(f"https://y/{i}", 0.9 - i * 0.1, p) for i, p in enumerate(paths)]
            with mock.patch.object(config, "PICK_A_SHOT", False), mock.patch.object(config, "CLIP_LIBRARY_MIN_SCORE", 2.0), \
                    mock.patch.dict(media._LIBRARY_KEEP, {"on": False}):
                win = media._best_of(passed)
            self.assertFalse(any(a.get("localPath") for a in win.alternatives))


class ChoicesArePublished(unittest.TestCase):
    def test_each_scenes_runner_ups_get_media_links_and_no_path_reaches_the_timeline(self):
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = os.path.join(d, "a.mp4"), os.path.join(d, "b.mp4")
            open(p1, "wb").write(b"x"); open(p2, "wb").write(b"x")
            doc = {"scenes": [
                {"id": "s1", "semanticMetadata": {"alternatives": [
                    {"assetId": "yt:a", "url": "https://y/a", "localPath": p1},
                    {"assetId": "yt:b", "url": "https://y/b", "localPath": p2},
                    {"assetId": "yt:c", "url": "https://y/c"}]}},
                {"id": "s2", "semanticMetadata": {"alternatives": []}},
            ]}

            def fake_publish(cands, project_id, bucket, job_id, scene_id, work):
                for n, c in enumerate(cands, 1):
                    c["media"] = {"type": "video", "url": f"https://r2/{scene_id}_alt{n}.mp4",
                                  "thumbnail": f"https://r2/{scene_id}_alt{n}.jpg"}
            with mock.patch.object(config, "PICK_A_SHOT", True), mock.patch.object(config, "PICK_A_SHOT_CHOICES", 3), \
                    mock.patch.object(handler, "_publish_alternatives", side_effect=fake_publish):
                n = handler._publish_choices(doc, "proj", "bucket", "job", d, lambda *a, **k: None)
            self.assertEqual(n, 2)
            alts = doc["scenes"][0]["semanticMetadata"]["alternatives"]
            self.assertEqual(alts[0]["media"]["url"], "https://r2/s1_alt1.mp4")
            self.assertEqual(alts[1]["media"]["thumbnail"], "https://r2/s1_alt2.jpg")
            self.assertNotIn("media", alts[2])                   # no file: no link, but the title stays
            library._strip_local_alternatives(doc)
            self.assertFalse(any("localPath" in a for a in alts))

    def test_off_publishes_nothing(self):
        doc = {"scenes": [{"id": "s1", "semanticMetadata": {"alternatives": [{"localPath": __file__}]}}]}
        with mock.patch.object(config, "PICK_A_SHOT", False), \
                mock.patch.object(handler, "_publish_alternatives") as pub:
            self.assertEqual(handler._publish_choices(doc, "p", "b", "j", ".", lambda *a, **k: None), 0)
        pub.assert_not_called()


if __name__ == "__main__":
    unittest.main()
