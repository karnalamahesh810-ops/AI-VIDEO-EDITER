"""Every clip and picture a finished video shows goes into the app's library (2026-10-01)."""
import unittest
from unittest import mock

from src import config, library

BASE = "https://pub-videos.example.r2.dev"
PID = "973d993c-e284-42c3-8b91-5eb285269509"


def _doc():
    def scene(i, kind="video", **m):
        media = {"type": kind, "url": f"{BASE}/projects/{PID}/media/s{i:04d}-abc.{'mp4' if kind == 'video' else 'jpg'}",
                 "thumbnail": f"{BASE}/projects/{PID}/thumbs/s{i:04d}-t.jpg", "source": "youtube",
                 "relevanceScore": 0.9, "qualityScore": 0.8, "clipSeconds": 6.0, **m}
        return {"text": f"line {i}", "query": "Lake Powell", "media": media,
                "semanticMetadata": {"searchQuery": "Lake Powell low water", "sourceUrl": f"https://youtube.com/watch?v={i}",
                                     "contentDescription": "The canyon walls with a white bathtub ring."}}
    scenes = [scene(0), scene(1, "image", source="wikipedia"), scene(2, "image", source="generated", generated=True),
              scene(3), {"text": "a card", "media": {"type": "animation", "url": ""}},
              {"text": "elsewhere", "media": {"type": "video", "url": "https://other.example/x.mp4"}}]
    scenes.append(dict(scenes[0]))              # the same file twice: one row
    return {"scenes": scenes}


class ShownRows(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(config, "R2_PUBLIC_BASE", BASE), mock.patch.object(config, "R2_BUCKET", "thumbgenius-videos")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_one_row_per_stored_file_with_its_still_and_story(self):
        rows = library.shown_rows(_doc(), PID)
        self.assertEqual([r["kind"] for r in rows], ["video", "image", "generated", "video"])
        r = rows[0]
        self.assertEqual(r["asset_id"], f"file:projects/{PID}/media/s0000-abc.mp4")
        self.assertEqual((r["storage_bucket"], r["storage_path"]), ("r2:thumbgenius-videos", f"projects/{PID}/media/s0000-abc.mp4"))
        self.assertEqual(r["thumbnail_path"], f"projects/{PID}/thumbs/s0000-t.jpg")
        self.assertEqual(r["subject"], "Lake Powell low water")
        self.assertEqual(r["subject_key"], "lake powell low water")
        self.assertTrue(r["used"] and r["saved"])
        self.assertEqual(r["analysis"]["shownIn"], PID)
        self.assertEqual(r["seconds"], 6.0)

    def test_record_sends_them_through_the_broker_and_never_fails_the_video(self):
        with mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_upsert", return_value={"upserted": 4}) as up:
            self.assertEqual(library.record_shown(_doc(), PID, "pod-x"), 4)
        self.assertEqual(up.call_args[0][:2], (PID, "pod-x"))
        with mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_upsert", side_effect=RuntimeError("403")):
            self.assertEqual(library.record_shown(_doc(), PID, "pod-x"), 0)
        with mock.patch.object(config, "LIBRARY_SHOWN", False):
            self.assertEqual(library.record_shown(_doc(), PID, "pod-x"), 0)


class NeverPickedAutomatically(unittest.TestCase):
    def test_a_shown_clip_is_not_found_for_a_new_video(self):
        lib = library.Library.__new__(library.Library)
        lib.entries = [
            {"id": "file:a.mp4", "kind": "video", "saved": True, "subject_key": "lake powell", "relevance": 0.95,
             "analysis": {"shownIn": PID}},
            {"id": "yt:b@10", "kind": "video", "saved": True, "subject_key": "lake powell", "relevance": 0.9,
             "analysis": {}},
        ]
        lib._emb = {}
        with mock.patch.object(library.ledger, "library_used", return_value=False), \
                mock.patch.object(lib, "_context", return_value={}, create=True), \
                mock.patch.object(lib, "_stale", return_value=False, create=True), \
                mock.patch.object(lib, "_hits", return_value=0, create=True), \
                mock.patch.object(lib, "_fresh", return_value=0, create=True):
            got = lib.find("Lake Powell", n=5)
        self.assertEqual([e["id"] for e in got], ["yt:b@10"])


if __name__ == "__main__":
    unittest.main()
