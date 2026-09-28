import json
import os
import tempfile
import unittest
from unittest import mock

from src import config, library, media, pools


def _entry(i, subject="Lake Mead", rel=0.9):
    return {"id": f"yt:vid{i:08d}@3", "path": f"library/clips/yt_vid{i:08d}_3.mp4", "subject": subject,
            "subject_key": library._key(subject), "description": f"clip {i}", "relevance": rel,
            "quality": 0.7, "seconds": 6.0, "url": f"https://www.youtube.com/watch?v=vid{i:08d}",
            "attribution": "YouTube: x", "license": "unverified", "review_required": True}


# An app built before the library table: the broker rejects the action.
NO_TABLE = library.storage.StorageError("storage broker refused (400): unknown action library_query")


def _row(i, subject="Lake Mead", rel=0.9, **extra):
    row = {"asset_id": f"yt:vid{i:08d}@3", "storage_bucket": "video-media",
           "storage_path": f"library/clips/yt_vid{i:08d}_3.mp4", "readUrl": f"https://signed/{i}",
           "subject": subject, "subject_key": library._key(subject), "entities": [subject], "locations": [],
           "description": f"row {i}", "relevance": rel, "quality": 0.7, "seconds": 6.0, "kind": "video",
           "source_url": f"https://www.youtube.com/watch?v=vid{i:08d}", "usage_count": i, "saved": True,
           "analysis": {"attribution": "YouTube: x", "license": "unverified", "reviewRequired": True}}
    row.update(extra)
    return row


class Table(unittest.TestCase):
    """The footage_library table is the catalogue when the app has it."""

    def _lib(self, rows):
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_query", return_value={"ok": True, "rows": rows}) as q, \
                mock.patch.object(library.storage, "broker_read_url", side_effect=AssertionError("index must not be read")):
            lib = library.Library.load("p", "j")
        self.assertEqual(q.call_args.args[:2], ("p", "j"))
        return lib

    def test_rows_load_and_match_by_subject_or_entity(self):
        lib = self._lib([_row(1, rel=0.8), _row(2, rel=0.95), _row(3, "Hoover Dam", entities=["Hoover Dam", "Lake Mead"]),
                         _row(4, kind="image"), _row(5, saved=False), {"no": "asset id"}])
        self.assertTrue(lib.db and lib.loaded and not lib.unreadable)
        self.assertEqual(len(lib.entries), 5)
        got = [e["id"] for e in lib.find("Lake Mead", n=5)]
        # Own subject first by relevance, then the row that only names it as an entity; images and unsaved rows never.
        self.assertEqual(got, ["yt:vid00000002@3", "yt:vid00000001@3", "yt:vid00000003@3"])
        self.assertEqual(lib.entries[0]["read_url"], "https://signed/1")
        self.assertEqual(lib.entries[0]["attribution"], "YouTube: x")

    def test_fetch_uses_the_signed_url_and_marks_the_clip_used(self):
        lib = self._lib([_row(1)])
        d = tempfile.mkdtemp()
        with mock.patch.object(library.storage, "download", side_effect=lambda url, path: open(path, "wb").write(b"x")) as dl, \
                mock.patch.object(library.media, "playable_video", return_value=True):
            asset = lib.fetch(lib.entries[0], d, 6.0, {"intent": "the lake"})
        self.assertEqual(dl.call_args.args[0], "https://signed/1")
        self.assertEqual(asset.moment_key, "yt:vid00000001@3")
        self.assertEqual(lib.used, {"yt:vid00000001@3"})

    def test_save_upserts_new_rows_and_usage_marks(self):
        lib = self._lib([_row(1)])
        lib.used.add("yt:vid00000001@3")
        d = tempfile.mkdtemp()
        good = os.path.join(d, "a.mp4"); open(good, "wb").write(b"x" * 10)
        doc = {"fps": 30, "scenes": [
            {"id": "s0", "durationInFrames": 180, "media": {"type": "video", "source": "youtube", "url": good},
             "semanticMetadata": {"assetId": "yt:abc@2", "sourceUrl": "https://www.youtube.com/watch?v=abc",
                                  "subject": "Lake Mead", "contentDescription": "aerial", "relevanceScore": 0.9,
                                  "sceneIntent": {"entities": ["Lake Mead"], "locations": ["Nevada"],
                                                  "event_type": "drought", "time_context": "2026"}}}]}
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_upload", return_value="u") as up, \
                mock.patch.object(library.storage, "broker_library_upsert", return_value={"ok": True, "upserted": 2}) as ups:
            self.assertEqual(lib.record_from_doc(doc), 1)
            self.assertTrue(lib.save())
        self.assertEqual(up.call_args.args[2], "library/clips/yt_abc_2.mp4")
        rows = ups.call_args.args[2]
        self.assertEqual([r["asset_id"] for r in rows], ["yt:abc@2", "yt:vid00000001@3"])
        new = rows[0]
        self.assertEqual((new["storage_path"], new["kind"], new["saved"]), ("library/clips/yt_abc_2.mp4", "video", True))
        self.assertEqual((new["entities"], new["locations"], new["event"], new["time_context"]),
                         (["Lake Mead"], ["Nevada"], "drought", "2026"))
        self.assertEqual(rows[1], {"asset_id": "yt:vid00000001@3", "used": True})

    def test_a_used_clip_is_marked_even_when_nothing_new_was_added(self):
        lib = self._lib([_row(1)])
        lib.used.add("yt:vid00000001@3")
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_upsert", return_value={"ok": True}) as ups:
            self.assertEqual(lib.record_from_doc({"fps": 30, "scenes": []}), 0)
            self.assertTrue(lib.save())
        self.assertEqual(ups.call_args.args[2], [{"asset_id": "yt:vid00000001@3", "used": True}])


class Find(unittest.TestCase):
    def test_same_subject_best_first_and_used_excluded(self):
        lib = library.Library("p", "j")
        lib.entries = [_entry(1, rel=0.8), _entry(2, rel=0.95), _entry(3, "Hoover Dam"), _entry(4, rel=0.5)]
        got = lib.find("The Lake Mead", n=3)
        self.assertEqual([e["id"] for e in got], ["yt:vid00000002@3", "yt:vid00000001@3"])  # 0.5 below floor
        self.assertEqual([e["id"] for e in lib.find("Lake Mead", exclude={"yt:vid00000002@3"}, n=1)],
                         ["yt:vid00000001@3"])


class Record(unittest.TestCase):
    def test_good_local_youtube_clips_are_uploaded_and_indexed(self):
        d = tempfile.mkdtemp()
        good = os.path.join(d, "a.mp4"); open(good, "wb").write(b"x" * 10)
        doc = {"fps": 30, "scenes": [
            {"id": "s0", "durationInFrames": 180, "media": {"type": "video", "source": "youtube", "url": good,
                                                             "attribution": "YouTube: t"},
             "semanticMetadata": {"assetId": "yt:abc@2", "sourceUrl": "https://www.youtube.com/watch?v=abc",
                                  "subject": "Lake Mead", "contentDescription": "aerial", "relevanceScore": 0.9}},
            {"id": "s1", "durationInFrames": 180, "media": {"type": "video", "source": "youtube", "url": good},
             "semanticMetadata": {"assetId": "yt:low@1", "subject": "Lake Mead", "relevanceScore": 0.6}},
            {"id": "s2", "durationInFrames": 180, "media": {"type": "video", "source": "youtube", "url": "https://remote/x.mp4"},
             "semanticMetadata": {"assetId": "yt:rem@1", "subject": "Lake Mead", "relevanceScore": 0.9}},
        ]}
        uploads = []
        lib = library.Library("p", "j", "video-media")
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_upload", side_effect=lambda *a, **k: uploads.append(a[2]) or "u"):
            self.assertEqual(lib.record_from_doc(doc), 1)          # low score and remote skipped
            self.assertTrue(lib.save())
        self.assertEqual(uploads[0], "library/clips/yt_abc_2.mp4")
        self.assertEqual(uploads[1], library.INDEX_PATH)
        self.assertEqual(lib.entries[0]["subject_key"], "lake mead")
        self.assertEqual(lib.entries[0]["url"], "https://www.youtube.com/watch?v=abc")

    def test_unavailable_library_is_empty_and_harmless(self):
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_query", side_effect=NO_TABLE), \
                mock.patch.object(library.storage, "broker_read_url", side_effect=RuntimeError("no")):
            lib = library.Library.load("p", "j")
        self.assertEqual(lib.entries, [])
        self.assertEqual(lib.find("Lake Mead"), [])
        self.assertTrue(lib.unreadable)
        lib.added = 1
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_upload", side_effect=AssertionError("must not overwrite")):
            self.assertFalse(lib.save())                          # an unreadable index is never replaced

    def test_missing_index_is_the_first_video_not_an_error(self):
        err = library.storage.StorageError("storage broker refused (500): Object not found")
        with mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_query", side_effect=NO_TABLE), \
                mock.patch.object(library.storage, "broker_read_url", side_effect=err):
            lib = library.Library.load("p", "j")
        self.assertTrue(lib.loaded)
        self.assertFalse(lib.unreadable)
        self.assertEqual(lib.entries, [])


class PoolsUseLibrary(unittest.TestCase):
    def test_library_clips_fill_a_subject_before_youtube_is_searched(self):
        lib = library.Library("p", "j"); lib.entries = [_entry(1), _entry(2)]
        jobs = [{"index": i, "query": "Lake Mead", "seconds": 6.0, "visual_type": "footage",
                 "subject": "Lake Mead", "subject_type": "place", "context": "x", "intent": "x"} for i in range(3)]
        searched = []

        def cands(subject, cc, skip, **kw):
            searched.append(subject); return [{"id": "NEWNEWNEWNE", "title": "Lake Mead 4k"}]

        def fetch_lib(entry, work, seconds, job):
            return media.MediaAsset(kind="video", source="youtube", url=entry["url"], local_path="/w/l.mp4", moment_key=entry["id"])

        def fake_fetch(job_, cand, m, work, require_cc, subject, library=None):
            if cand.get("_library") is not None:
                return library.fetch(cand["_library"], work, 6.0, job_)
            return media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={cand['id']}&t=9",
                                    local_path="/w/n.mp4", moment_key=f"yt:{cand['id']}@0")
        with mock.patch.object(pools, "candidates", cands), \
                mock.patch.object(pools, "rate_video", lambda c, s, ctx, sec, **kw: [{"start": 9.0, "score": 0.9, "description": "d"}]), \
                mock.patch.object(pools, "_fetch", fake_fetch), \
                mock.patch.object(lib, "fetch", fetch_lib), \
                mock.patch.object(config, "POOL_MIN_SCENES", 1):
            got = pools.source_by_subject(jobs, "/w", library=lib)
        self.assertEqual(sorted(got), [0, 1, 2])
        self.assertEqual([got[i].identity for i in (0, 1)], ["yt:vid00000001@3", "yt:vid00000002@3"])  # library first
        self.assertEqual(got[2].identity, "yt:NEWNEWNEWNE@0")                                          # YouTube for the rest
        self.assertEqual(searched, ["Lake Mead"])


if __name__ == "__main__":
    unittest.main()
