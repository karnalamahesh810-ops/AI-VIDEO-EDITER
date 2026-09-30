"""No reuse across videos (src/ledger.py, the owner 2026-09-30: "the same clip
was literally used in the previous video"). R2 is mocked throughout."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from src import config, ledger, library, libstore, media, pools, r2, storage

R2ON = {"R2_ACCOUNT_ID": "acc", "R2_ACCESS_KEY_ID": "key", "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET": "thumbgenius-videos", "R2_PUBLIC_BASE": "https://pub-videos.r2.dev",
        "R2_LIBRARY_BUCKET": "thumbgenius-library", "R2_LIBRARY_PUBLIC_BASE": "https://pub-lib.r2.dev",
        "R2_LIBRARY_PREFIX": ""}
VID = "abcdefghijk"


def scene(i, kind="video", source="youtube", url="", start=None, seconds=6.0, aid="", photo_path=""):
    sem = {"sourceUrl": url, "assetId": aid, "provider": source}
    if start is not None:
        sem["moment"] = {"start": start}
    return {"id": f"s{i}", "startFrame": int(i * 180), "durationInFrames": int(seconds * 30),
            "media": {"type": kind, "source": source, "url": photo_path or f"https://pub/{i}.mp4"},
            "semanticMetadata": sem}


class FakeBucket:
    """An in-memory R2 library bucket: get_bytes / list_keys / upload_bytes."""

    def __init__(self, files=None, slow=None):
        self.files = dict(files or {})
        self.slow = set(slow or ())
        self.puts = []

    def get_bytes(self, key, bucket="", timeout=60):
        if key in self.slow:
            time.sleep(2.0)
        data = self.files.get(key)
        return data if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode())

    def list_keys(self, prefix="", bucket="", limit=10000):
        return [{"key": k, "size": 1} for k in sorted(self.files) if k.startswith(prefix)]

    def upload_bytes(self, data, key, **kw):
        self.puts.append((key, json.loads(data.decode())))
        self.files[key] = data
        return f"https://pub-lib.r2.dev/{key}"

    def patches(self):
        return [mock.patch.multiple(config, **R2ON),
                mock.patch.object(r2, "get_bytes", side_effect=self.get_bytes),
                mock.patch.object(r2, "list_keys", side_effect=self.list_keys),
                mock.patch.object(r2, "upload_bytes", side_effect=self.upload_bytes)]


def record(job, project, items, days_ago=1):
    return {"v": 1, "job": job, "project": project, "ts": int(time.time() - days_ago * 86400), "items": items}


class Base(unittest.TestCase):
    def setUp(self):
        ledger.use(ledger.Ledger())
        self.addCleanup(lambda: ledger.use(ledger.Ledger()))


class WhatAVideoRecords(Base):
    def test_moments_pages_photos_and_asset_ids(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        from PIL import Image
        photo = os.path.join(d, "p.jpg")
        Image.linear_gradient("L").resize((320, 200)).convert("RGB").save(photo)
        doc = {"fps": 30, "scenes": [
            scene(0, url=f"https://www.youtube.com/watch?v={VID}&t=95", start=95.0, aid=f"yt:{VID}@11"),
            scene(1, url=f"https://www.youtube.com/watch?v={VID}&t=40", aid=f"yt:{VID}"),       # start from t=
            scene(2, source="dailymotion", url="https://www.dailymotion.com/video/x8abc", start=12.0,
                  aid="dailymotion:https://www.dailymotion.com/video/x8abc"),
            scene(3, kind="image", source="web_image", url="https://news.example.com/img/flood-960x540.jpg?w=960",
                  aid="web_image:https://news.example.com/img/flood-960x540.jpg", photo_path=photo),
            scene(4, source="generated", url="", aid="generated:/tmp/x.png"),
            scene(5, source="noaa_goes", url="https://cdn.star.nesdis.noaa.gov/loop.mp4"),
            {"id": "s6", "startFrame": 1080, "durationInFrames": 90, "media": {"type": "animation", "url": ""}},
        ]}
        items = ledger.items_from_doc(doc)
        yt = [i for i in items if i["k"] == "yt"]
        self.assertEqual([(i["id"], i["s"], i["e"]) for i in yt], [(VID, 95.0, 101.0), (VID, 40.0, 46.0)])
        self.assertEqual(yt[0]["a"], f"yt:{VID}@11")
        page = next(i for i in items if i["k"] == "url")
        self.assertEqual((page["u"], page["s"]), ("dailymotion.com/video/x8abc", 12.0))
        pic = next(i for i in items if i["k"] == "photo")
        self.assertEqual(pic["u"], "news.example.com/img/flood-960x540.jpg")
        self.assertEqual(len(pic["h"]), 16)
        self.assertEqual(len(items), 4)          # no generated picture, satellite loop or animation

    def test_the_url_and_id_helpers(self):
        self.assertEqual(ledger.youtube_id("https://youtu.be/abcdefghijk?t=3"), VID)
        self.assertEqual(ledger.youtube_id("yt:abcdefghijk@4"), VID)
        self.assertEqual(ledger.url_start("https://www.youtube.com/watch?v=abcdefghijk&t=1m35s"), 95.0)
        self.assertEqual(ledger.url_start("https://www.youtube.com/watch?v=abcdefghijk&t=95"), 95.0)
        self.assertEqual(ledger.norm_url("https://www.Facebook.com/watch/?v=123&ref=x"), "facebook.com/watch?v=123")
        self.assertEqual(ledger.norm_url("https://upload.wikimedia.org/a/b/thumb/960px-File.jpg"),
                         "upload.wikimedia.org/a/b/thumb/File.jpg")


class TheRule(Base):
    def setUp(self):
        super().setUp()
        led = ledger.Ledger(project_id="p-now", days=120, gap=30)
        led.add_record(record("j1", "p-old", [{"k": "yt", "id": VID, "s": 100.0, "e": 106.0},
                                             {"k": "yt", "id": "zzzzzzzzzzz"},              # range unknown
                                             {"k": "url", "u": "dailymotion.com/video/x8abc", "s": 10.0, "e": 16.0},
                                             {"k": "photo", "u": "news.example.com/a.jpg", "h": "00ff00ff00ff00ff"},
                                             {"k": "lib", "a": "yt:qqqqqqqqqqq@3"}]))
        led.add_record(record("j2", "p-now", [{"k": "yt", "id": "ownprojectv", "s": 0.0, "e": 9.0}]))
        led.add_record(record("j3", "p-older", [{"k": "yt", "id": "oldvideo000", "s": 0.0, "e": 9.0}],
                              days_ago=200))
        ledger.use(led, "job-now", "p-now")

    def test_a_used_moment_and_its_neighbourhood_are_out(self):
        self.assertTrue(ledger.moment_used(VID, 103.0, 109.0))          # overlaps
        self.assertTrue(ledger.moment_used(VID, 120.0, 126.0))          # 14 s after: within the 30 s gap
        self.assertTrue(ledger.moment_used(VID, 60.0, 71.0))            # ends 29 s before it
        self.assertFalse(ledger.moment_used(VID, 140.0, 146.0))         # another moment of the report
        self.assertFalse(ledger.moment_used(VID, 20.0, 26.0))
        self.assertTrue(ledger.moment_used("zzzzzzzzzzz", 500.0, 506.0))   # an unknown range blocks the video

    def test_a_project_never_blocks_itself_and_old_videos_expire(self):
        self.assertFalse(ledger.moment_used("ownprojectv", 0.0, 6.0))
        self.assertFalse(ledger.moment_used("oldvideo000", 0.0, 6.0))    # 200 days ago, window 120

    def test_other_pages_photos_and_library_clips(self):
        self.assertTrue(ledger.url_used("https://www.dailymotion.com/video/x8abc", 20.0, 26.0))
        self.assertFalse(ledger.url_used("https://www.dailymotion.com/video/x8abc", 80.0, 86.0))
        self.assertTrue(ledger.photo_used("https://news.example.com/a.jpg?w=1200"))
        self.assertTrue(ledger.photo_used("", 0x00ff00ff00ff00fe))      # 1 bit off: a resized copy
        self.assertFalse(ledger.photo_used("", 0xff00ff00ff00ff00))
        self.assertTrue(ledger.library_used({"id": "yt:qqqqqqqqqqq@3"}))
        self.assertTrue(ledger.library_used({"id": "yt:abcdefghijk@13", "seconds": 6,
                                             "url": f"https://www.youtube.com/watch?v={VID}&t=104"}))
        self.assertFalse(ledger.library_used({"id": "yt:abcdefghijk@30", "seconds": 6,
                                              "url": f"https://www.youtube.com/watch?v={VID}&t=240"}))
        self.assertGreaterEqual(ledger.stats()["skipped"]["moment"], 0)

    def test_zero_days_turns_it_off(self):
        with mock.patch.object(config, "CROSS_VIDEO_REUSE_DAYS", 0):
            self.assertFalse(ledger.moment_used(VID, 103.0, 109.0))
            self.assertFalse(ledger.photo_used("https://news.example.com/a.jpg"))


class ReadingAndWriting(Base):
    def run_with(self, bucket, fn):
        ps = bucket.patches()
        for p in ps:
            p.start()
        try:
            return fn()
        finally:
            for p in reversed(ps):
                p.stop()

    def test_the_index_and_the_job_files_it_does_not_hold(self):
        bucket = FakeBucket({
            "ledger/index.json": {"v": 1, "jobs": ["j1"], "items": [
                {"k": "yt", "id": VID, "s": 100.0, "e": 106.0, "ts": int(time.time()), "p": "p-old", "j": "j1"}]},
            "ledger/jobs/j1.json": record("j1", "p-old", [{"k": "yt", "id": "shouldnotread", "s": 0, "e": 5}]),
            "ledger/jobs/j2.json": record("j2", "p-old", [{"k": "yt", "id": "secondvideo", "s": 50.0, "e": 55.0}]),
            "ledger/jobs/bad.json": b"{not json",
        })

        def go():
            self.assertTrue(ledger.start_loading("job-now", "p-now"))
            led = ledger.current()
            self.assertTrue(led.moment_used(VID, 101, 104))
            self.assertTrue(led.moment_used("secondvideo", 52, 58))
            self.assertFalse(led.moment_used("shouldnotread", 0, 5))      # the index already holds j1
            self.assertEqual(led.jobs, {"j1", "j2"})
        self.run_with(bucket, go)

    def test_a_missing_ledger_is_empty_and_a_slow_one_is_time_boxed(self):
        def go():
            self.assertTrue(ledger.start_loading("job-now", "p-now"))
            self.assertEqual(ledger.current().items, 0)
        self.run_with(FakeBucket(), go)
        slow = FakeBucket({"ledger/jobs/j9.json": record("j9", "p", [{"k": "yt", "id": VID, "s": 0, "e": 5}])},
                          slow={"ledger/jobs/j9.json"})

        def go_slow():
            with mock.patch.object(config, "LEDGER_LOAD_SECONDS", 0.3):
                t = time.time()
                ledger.start_loading("job-now", "p-now")
                ledger.current()
                self.assertLess(time.time() - t, 1.5)                   # sourcing did not wait for it
                # The read goes on in the background and still lands.
                self.assertTrue(ledger._STATE["done"].wait(5))
                self.assertTrue(ledger.current().moment_used(VID, 0, 5))
        self.run_with(slow, go_slow)

    def test_off_without_the_library_bucket(self):
        with mock.patch.object(config, "R2_LIBRARY_BUCKET", ""):
            self.assertFalse(ledger.start_loading("j", "p"))
            self.assertEqual(ledger.current().items, 0)

    def test_a_finished_video_writes_its_file_and_compacts_the_index(self):
        bucket = FakeBucket({f"ledger/jobs/old{n}.json": record(f"old{n}", "p-old",
                                                                [{"k": "yt", "id": f"video{n:06d}", "s": 1, "e": 5}])
                             for n in range(3)})
        doc = {"fps": 30, "meta": {"videoStyle": "nature_weather", "story": {"event": "2026 Texas floods"}},
               "scenes": [scene(0, url=f"https://www.youtube.com/watch?v={VID}&t=95", start=95.0,
                                aid=f"yt:{VID}@11")]}

        def go():
            with mock.patch.object(config, "LEDGER_COMPACT_EVERY", 3):
                ledger.start_loading("job-now", "p-now")
                ledger.current()
                self.assertEqual(ledger.note(doc), 1)
                self.assertTrue(ledger.save("job-now", "p-now"))
            keys = [k for k, _v in bucket.puts]
            self.assertEqual(keys, ["ledger/jobs/job-now.json", "ledger/index.json"])
            rec = bucket.puts[0][1]
            self.assertEqual((rec["job"], rec["project"], rec["style"]), ("job-now", "p-now", "nature_weather"))
            self.assertEqual(rec["items"][0]["id"], VID)
            index = bucket.puts[1][1]
            self.assertEqual(set(index["jobs"]), {"old0", "old1", "old2", "job-now"})
            self.assertEqual(len(index["items"]), 4)
            self.assertTrue(all("ts" in i and "p" in i for i in index["items"]))
        self.run_with(bucket, go)

    def test_saving_never_fails_a_video(self):
        bucket = FakeBucket()

        def boom(*a, **k):
            raise RuntimeError("R2 down")

        def go():
            ledger.start_loading("job-now", "p-now")
            ledger.note({"fps": 30, "scenes": [scene(0, url=f"https://youtu.be/{VID}", start=5.0)]})
            with mock.patch.object(r2, "upload_bytes", side_effect=boom):
                self.assertFalse(ledger.save("job-now", "p-now"))
        self.run_with(bucket, go)


class SourcingSkipsWhatWasShown(Base):
    def setUp(self):
        super().setUp()
        led = ledger.Ledger(project_id="p-now", days=120, gap=30)
        led.add_record(record("j1", "p-old", [{"k": "yt", "id": VID, "s": 100.0, "e": 106.0},
                                             {"k": "photo", "u": "news.example.com/a.jpg"}]))
        ledger.use(led, "job-now", "p-now")

    def test_the_pools_drop_a_used_moment_and_keep_the_rest_of_the_video(self):
        rated = [{"start": 102.0, "score": 0.9, "description": "used"},
                 {"start": 300.0, "score": 0.85, "description": "fresh"}]
        jobs = [{"index": 0, "seconds": 5.0, "start": 0.0, "context": "x"},
                {"index": 1, "seconds": 5.0, "start": 200.0, "context": "y"}]
        cand = {"id": VID, "title": "Flooding video", "duration": 600}
        with mock.patch.object(pools, "candidates", return_value=[cand]), \
                mock.patch.object(pools, "rate_video", return_value=rated), \
                mock.patch.object(pools, "subject_story", return_value={"is_event": False, "kind": "", "event": "",
                                                                        "year": None, "window": "", "recency": "",
                                                                        "word": ""}), \
                mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 0):
            plan, spare = pools.plan_subject("Dallas", jobs, False, set(), lambda k: True)
        starts = [m["start"] for _j, _c, m in plan] + [m["start"] for _c, m in spare]
        self.assertEqual(starts, [300.0])

    def test_the_per_scene_search_skips_a_used_moment(self):
        row = mock.Mock(id=VID, title="Dallas flooding video", channel="", aspect=1.78, metadata=0.8, parts={})
        row.row.return_value = {"id": VID, "title": row.title, "duration": 600, "aspect": 1.78, "channel": ""}
        pool = mock.Mock()
        pool.ranked.return_value = [row]
        pool.__len__ = lambda self: 1
        pool.searches = 1
        fetched = []
        with mock.patch.object(media.candidates, "CandidatePool", return_value=pool), \
                mock.patch.object(media, "_yt_candidates_cached", return_value=[]), \
                mock.patch.object(media, "_plan_grabs", return_value=[(row.row.return_value, 101.0, None)]), \
                mock.patch.object(media, "fetch_clean_clip", side_effect=lambda *a, **k: fetched.append(a) or ("", True, 0)), \
                mock.patch.object(media, "_refine_moment", side_effect=lambda r, m, *a: m):
            got = media._youtube_pool("Dallas flooding", tempfile.gettempdir(), 5.0, 30.0, False, 0, set(),
                                      "flooded Dallas street", "", "Dallas", [("Dallas flooding", "plain", False)])
        self.assertIsNone(got)
        self.assertEqual(fetched, [])                              # never downloaded

    def test_a_shown_photo_is_not_picked_again(self):
        used = media.MediaAsset(kind="image", source="web_image", url="https://news.example.com/a.jpg?w=800")
        fresh = media.MediaAsset(kind="image", source="web_image", url="https://news.example.com/b.jpg")
        seen = []

        def download(c, q, w):
            seen.append(c.url)
            return None
        with mock.patch.object(media, "_download", side_effect=download):
            media._pick_unused([used, fresh], set(), "q", tempfile.gettempdir())
        self.assertEqual(seen, ["https://news.example.com/b.jpg"])

    def test_the_library_never_serves_a_shown_clip(self):
        lib = library.Library("p-now", "job-now")
        lib.entries = [
            {"id": f"yt:{VID}@12", "kind": "video", "subject": "Dallas", "subject_key": "dallas", "saved": True,
             "relevance": 0.9, "url": f"https://www.youtube.com/watch?v={VID}&t=100", "seconds": 6},
            {"id": f"yt:{VID}@40", "kind": "video", "subject": "Dallas", "subject_key": "dallas", "saved": True,
             "relevance": 0.9, "url": f"https://www.youtube.com/watch?v={VID}&t=320", "seconds": 6}]
        found = lib.find("Dallas", n=5, story={})
        self.assertEqual([e["id"] for e in found], [f"yt:{VID}@40"])


class TheLibraryKeepsWhatWasNotShown(Base):
    def test_runner_ups_and_spare_moments_are_kept_instead_of_the_shown_clips(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        shown = os.path.join(d, "shown.mp4")
        alt_ok = os.path.join(d, "alt_ok.mp4")
        alt_near = os.path.join(d, "alt_near.mp4")
        spare_file = os.path.join(d, "spare.mp4")
        for p in (shown, alt_ok, alt_near, spare_file):
            open(p, "wb").close()
        doc = {"fps": 30, "scenes": [{
            "id": "s0", "startFrame": 0, "durationInFrames": 180,
            "media": {"type": "video", "source": "youtube", "url": shown},
            "semanticMetadata": {
                "assetId": f"yt:{VID}", "sourceUrl": f"https://www.youtube.com/watch?v={VID}&t=100",
                "moment": {"start": 100.0}, "subject": "Dallas", "relevanceScore": 0.95,
                "sceneIntent": {"entities": ["Dallas"], "locations": ["Dallas, Texas"], "event_type": "flooding"},
                "alternatives": [
                    {"assetId": "yt:otherclip01", "url": "https://www.youtube.com/watch?v=otherclip01&t=40",
                     "moment": {"start": 40.0}, "score": 0.9, "title": "Dallas flood", "source": "youtube",
                     "localPath": alt_ok},
                    {"assetId": f"yt:{VID}", "url": f"https://www.youtube.com/watch?v={VID}&t=110",
                     "moment": {"start": 110.0}, "score": 0.9, "title": "same report", "source": "youtube",
                     "localPath": alt_near}]}}]}
        spare = [{"key": "dallas", "name": "Dallas", "cand": {"id": "sparevideo1", "title": "Dallas storm"},
                  "moment": {"start": 60.0, "score": 0.88, "description": "street under water"},
                  "meta": {"seconds": 6.5, "scene_intent": None, "event_window": "year"}}]
        checked, stored = [], []

        def check(path, **kw):
            checked.append(path)
            return libstore.Verdict(checked=True, width=1920, height=1080, seconds=6.0,
                                    hashes=[(0xFFFF << (16 * (len(checked) % 4))) & (2 ** 64 - 1)])

        def store(path, ident, kind, v, meta=None, deadline=0.0):
            stored.append(ident)
            return {"storage_bucket": "r2:thumbgenius-library", "storage_path": f"clips/{ident}.mp4",
                    "thumbnail_path": None, "analysis": {"publicUrl": f"https://pub-lib.r2.dev/clips/{ident}.mp4"}}
        lib = library.Library("proj", "job")
        lib.loaded = lib.db = True
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(pools, "spare_moments", return_value=spare), \
                mock.patch.object(media, "fetch_clean_clip", return_value=(spare_file, True, 0)) as fetch, \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(libstore, "check", side_effect=check), \
                mock.patch.object(libstore, "store", side_effect=store), \
                mock.patch.object(libstore, "warm", return_value=True):
            self.assertEqual(lib.record_from_doc(doc), 2)
        # The shown clip is not kept; the runner-up 10 s from it is not either.
        self.assertEqual(sorted(stored), sorted(["yt:otherclip01@5", "yt:sparevideo1@7"]))
        self.assertNotIn(shown, checked)
        self.assertEqual(fetch.call_args.args[:2], ("sparevideo1", media._WORK["dir"] or tempfile.gettempdir()))
        # No local path goes into the saved timeline.
        self.assertTrue(all("localPath" not in a for a in doc["scenes"][0]["semanticMetadata"]["alternatives"]))


if __name__ == "__main__":
    unittest.main()
