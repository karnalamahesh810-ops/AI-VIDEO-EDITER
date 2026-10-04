"""
The owner's review of the Glen Canyon video (2026-09-29): 148 of 167 scenes came
back empty and were filled with ~19 repeated clips, no news footage, a
thermometer for "13 miles", a block chart labelled GLEN CANYON DAM for "75
million acre-feet", and no date card for "On the fifteenth of September".
"""
import datetime
import os
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock

from src import config, director, fanout, media, pools, storage, treatments, vision
from src.transcribe import Segment


class BrokerUploadRetries(unittest.TestCase):
    def test_a_database_outage_is_waited_out_until_the_deadline(self):
        calls = {"n": 0}

        def broker(payload, timeout=60):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise storage.StorageError("storage broker refused (403): job is not running for this project")
            return {"ok": True, "uploadUrl": "https://up", "readUrl": "https://read"}

        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker", side_effect=broker), \
                mock.patch.object(storage, "upload_to_signed_url", return_value=10), \
                mock.patch.object(storage.time, "sleep"):
            url = storage.broker_upload(__file__, "video-media", "projects/p/x.mp4", "p", "j",
                                        deadline=time.time() + 120)
        self.assertEqual(url, "https://read")

    def test_no_deadline_or_a_real_refusal_fails_at_once(self):
        with mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker", side_effect=storage.StorageError(
                    "storage broker refused (400): path must start with projects/")), \
                mock.patch.object(storage.time, "sleep") as slept:
            with self.assertRaises(storage.StorageError):
                storage.broker_upload(__file__, "video-media", "bad", "p", "j", deadline=time.time() + 120)
            with self.assertRaises(storage.StorageError):
                storage.broker_upload(__file__, "video-media", "projects/p/x", "p", "j")
        slept.assert_not_called()


class RenderChunkUploadRetries(unittest.TestCase):
    """2026-10-04: four render_chunk children rendered their frames, then lost
    them to one 60 s broker read timeout each - run_chunk passed no deadline,
    so the upload was never retried and the parent re-rendered every chunk."""

    def test_a_stalled_broker_is_retried_instead_of_losing_the_chunk(self):
        import requests
        calls = {"n": 0}

        def broker(payload, timeout=60):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=60)")
            return {"ok": True, "uploadUrl": "https://up", "readUrl": "https://read"}

        with tempfile.TemporaryDirectory() as work, \
                mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "_broker", side_effect=broker), \
                mock.patch.object(storage, "upload_to_signed_url", return_value=10), \
                mock.patch.object(storage.time, "sleep"):
            out = fanout.run_chunk({"frames": [0, 299], "chunk": 3, "project_id": "p",
                                    "parent_job_id": "j", "deadline_at": time.time() + 900},
                                   work, lambda *a: open(a[1], "wb").write(b"x"))
        self.assertEqual(out["url"], "https://read")
        self.assertEqual(calls["n"], 4)                  # two timeouts, then upload + read


class CloudflareOnlyStorage(unittest.TestCase):
    """R2_ONLY with R2 configured: files go to Cloudflare R2, never the app's storage."""

    def test_uploads_go_to_r2_and_never_touch_the_broker(self):
        from src import r2
        with mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(r2, "enabled", return_value=True), \
                mock.patch.object(r2, "upload", return_value="https://pub/x") as up, \
                mock.patch.object(r2, "presign", return_value="https://signed/x"), \
                mock.patch.object(storage, "_broker", side_effect=AssertionError("Supabase used")), \
                mock.patch.object(storage, "upload_to_supabase", side_effect=AssertionError("Supabase used")):
            url = storage.broker_upload(__file__, "video-media", "/projects/p/parts/j/render_003.mp4", "p", "j")
        self.assertEqual(url, "https://signed/x")
        self.assertEqual(up.call_args[0][1], "projects/p/parts/j/render_003.mp4")   # readable by path

    def test_reads_come_from_r2_and_old_supabase_files_stay_readable(self):
        from src import r2
        with mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(r2, "enabled", return_value=True), \
                mock.patch.object(r2, "presign", return_value="https://signed/r2"), \
                mock.patch.object(storage, "_broker", return_value={"ok": True, "readUrl": "https://supabase/old"}):
            with mock.patch.object(r2, "head", return_value={"size": 1}):
                self.assertEqual(storage.broker_read_url("b", "projects/p/a.mp4", "p", "j"), "https://signed/r2")
            with mock.patch.object(r2, "head", return_value=None):
                self.assertEqual(storage.broker_read_url("b", "projects/p/a.mp4", "p", "j"), "https://supabase/old")

    def test_without_r2_credentials_the_app_storage_still_works(self):
        from src import r2
        with mock.patch.object(config, "R2_ONLY", True), mock.patch.object(r2, "enabled", return_value=False):
            self.assertFalse(storage.r2_only())


class CloudflareHealthCheck(unittest.TestCase):
    """health's storage check is a real R2 round trip once R2 is configured."""
    VALS = {"R2_ACCOUNT_ID": "acct", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s",
            "R2_BUCKET": "videos", "R2_PUBLIC_BASE": "https://cdn.example.com", "R2_ONLY": True}

    def _fake_store(self, public_status=200):
        from src import r2
        store = {}

        def put(key, body, size, ctype, bucket, cc, deadline, reopen=None):
            store[key] = body

        def get(url, **kw):
            r = mock.Mock()
            key = url.split("?")[0].split("/videos/")[-1] if "r2.cloudflarestorage" in url else url.split(".com/")[-1]
            r.status_code = public_status if "cdn.example.com" in url else 200
            r.content = store.get(urllib.parse.unquote(key), b"")
            return r
        return r2, store, put, get

    def test_a_working_bucket_passes_every_step(self):
        r2, store, put, get = self._fake_store()
        with mock.patch.multiple(config, **self.VALS), mock.patch.object(r2, "_put", side_effect=put), \
                mock.patch.object(r2, "get_bytes", side_effect=lambda k, **kw: store.get(k)), \
                mock.patch.object(r2.requests, "get", side_effect=get), \
                mock.patch.object(r2, "delete", side_effect=lambda k: store.pop(k, None) is not None):
            out = storage.check()
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["mode"], "r2")
        self.assertEqual(set(out["steps"]), {"upload", "read", "presigned", "public", "delete"})
        self.assertFalse(store)                                              # the probe is cleaned up

    def test_a_public_domain_that_is_not_connected_is_named(self):
        r2, store, put, get = self._fake_store(public_status=404)
        with mock.patch.multiple(config, **self.VALS), mock.patch.object(r2, "_put", side_effect=put), \
                mock.patch.object(r2, "get_bytes", side_effect=lambda k, **kw: store.get(k)), \
                mock.patch.object(r2.requests, "get", side_effect=get), \
                mock.patch.object(r2, "delete", return_value=True):
            out = storage.check()
        self.assertFalse(out["ok"])
        self.assertIn("R2_PUBLIC_BASE", out["detail"])

    def test_an_endpoint_without_r2_keys_is_not_reported_ready(self):
        with mock.patch.multiple(config, **{n: "" for n in self.VALS if n != "R2_ONLY"}, R2_ONLY=True), \
                mock.patch.object(storage, "_broker", side_effect=AssertionError("Supabase checked instead")):
            out = storage.check()
        self.assertFalse(out["ok"])
        self.assertEqual(len(out["missing"]), 5)

    def test_missing_settings_are_listed_by_name_without_values(self):
        with mock.patch.multiple(config, **{**self.VALS, "R2_SECRET_ACCESS_KEY": "", "R2_PUBLIC_BASE": ""}):
            out = storage.check()
        self.assertFalse(out["ok"])
        self.assertEqual(out["missing"], ["R2_SECRET_ACCESS_KEY", "R2_PUBLIC_BASE"])
        self.assertNotIn("k", out["detail"].split())                          # no secret echoed


class LostPartClipsComeBack(unittest.TestCase):
    def tearDown(self):
        from src import ytdlp
        ytdlp.set_deadline(0.0)          # run_part sets the job's sourcing deadline

    def test_a_part_hands_back_where_a_clip_came_from_when_its_upload_fails(self):
        d = tempfile.mkdtemp()
        clip = os.path.join(d, "c.mp4")
        open(clip, "wb").write(b"x" * 100)
        asset = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=abcdefghijk&t=40",
                                 local_path=clip, duration=6.0, moment={"start": 40.0})
        inp = {"project_id": "p", "parent_job_id": "j", "jobs": [{"index": 7, "query": "q"}],
               "deadline_at": time.time() - 100}
        with mock.patch.object(storage, "broker_upload", side_effect=storage.StorageError("refused (403)")):
            out = fanout.run_part(inp, d, lambda jobs, work, seqs, ex: [asset], lambda b: None)
        self.assertEqual(out["delivered"], 0)
        self.assertEqual(out["refetch"], 1)
        rec = out["assets"]["7"]
        self.assertTrue(rec["refetch"])
        self.assertEqual(rec["moment"]["start"], 40.0)

    def test_the_parent_fetches_lost_clips_again_from_youtube(self):
        d = tempfile.mkdtemp()
        rec = {"kind": "video", "source": "youtube", "url": "https://www.youtube.com/watch?v=abcdefghijk&t=40",
               "duration": 6.0, "moment": {"start": 40.0}, "attribution": "YouTube: Lake Powell",
               "remote_url": "", "refetch": True}
        results = [None] * 3
        got_path = os.path.join(d, "yt.mp4")
        open(got_path, "wb").write(b"x")
        with mock.patch.object(media, "fetch_clean_clip", return_value=(got_path, True, 0)) as fetch:
            n = fanout.refetch_lost([(1, rec)], results, d)
        self.assertEqual(n, 1)
        self.assertEqual(results[1].local_path, got_path)
        self.assertEqual(fetch.call_args[0][0], "abcdefghijk")
        self.assertAlmostEqual(fetch.call_args[0][2], 40.0)


class UnjudgedByTitle(unittest.TestCase):
    def test_title_fits(self):
        self.assertTrue(media._title_fits("Top 10 Golf Courses in Scottsdale Arizona",
                                          "Arizona desert golf course aerial footage"))
        self.assertFalse(media._title_fits("Relaxing piano music 4K",
                                           "Arizona desert golf course aerial footage"))
        self.assertFalse(media._title_fits("", "Lake Powell"))

    def test_a_picture_is_judged_by_its_file_name_not_its_credit_line(self):
        a = media.MediaAsset(kind="image", source="wikimedia", attribution="Tuxyso", query="Glen Canyon Dam",
                             url="https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/"
                                 "Glen_Canyon_Dam_and_Lake_Powell.jpg/960px-Glen_Canyon_Dam_and_Lake_Powell.jpg")
        self.assertIn("Glen Canyon Dam and Lake Powell", media._image_label(a))
        self.assertTrue(media._title_fits(media._image_label(a), "Glen Canyon Dam aerial view Lake Powell"))
        b = media.MediaAsset(kind="image", source="wikimedia", attribution="C. S. Fly", query="Glen Canyon Dam",
                             url="https://upload.wikimedia.org/wikipedia/commons/a/ab/Apache_camp_1886.jpg")
        self.assertFalse(media._title_fits(media._image_label(b), "Glen Canyon Dam aerial view Lake Powell"))

    def test_no_verdict_keeps_a_clip_named_after_the_line_and_drops_the_rest(self):
        media.reset_cache()
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "judge", return_value=None), \
                mock.patch.object(config, "ACCEPT_UNJUDGED", False):
            keep, verdict = media._vision_gate("x.mp4", "Lake Powell houseboats marina", "", "Lake Powell houseboat marina 2026")
            self.assertTrue(keep)
            self.assertIsNone(verdict)
            keep, _ = media._vision_gate("x.mp4", "Lake Powell houseboats marina", "", "Funny cat compilation")
            self.assertFalse(keep)
        self.assertEqual(media.UNJUDGED_KEPT, {"n": 1, "rejected": 1})


class RescuePass(unittest.TestCase):
    def test_an_empty_scene_gets_the_best_titled_unused_clip_without_a_vision_call(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "r.mp4")
        open(path, "wb").write(b"x")
        jobs = [{"index": 0, "query": "Arizona golf course aerial", "seconds": 5.0, "visual_type": "footage",
                 "intent": "Arizona desert golf course aerial footage", "subject": "Arizona golf courses"}]
        results = [None]
        cands = [{"id": "aaaaaaaaaaa", "title": "Cat videos", "duration": 300.0},
                 {"id": "bbbbbbbbbbb", "title": "Arizona Golf Course Drone Tour", "duration": 240.0}]
        with mock.patch.object(config, "FRESH_MOMENTS", False), \
                mock.patch.object(media, "_yt_candidates", return_value=cands), \
                mock.patch.object(media, "fetch_clean_clip", return_value=(path, True, 0)) as fetch, \
                mock.patch.object(media._filters, "has_burned_captions", return_value=False), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(vision, "judge") as judge:
            got = media.rescue_fill(jobs, results, d)
        self.assertEqual(got["search"], 1)
        self.assertEqual(fetch.call_args[0][0], "bbbbbbbbbbb")
        self.assertTrue(results[0].review_required)
        judge.assert_not_called()

    def test_a_person_or_a_graphic_beat_is_left_alone(self):
        jobs = [{"index": 0, "query": "Jared Polis", "seconds": 5.0, "visual_type": "footage",
                 "subject_type": "person"},
                {"index": 1, "query": "map", "seconds": 5.0, "visual_type": "animation"}]
        results = [None, None]
        with mock.patch.object(config, "FRESH_MOMENTS", False), \
                mock.patch.object(media, "_yt_candidates") as search:
            media.rescue_fill(jobs, results, tempfile.mkdtemp())
        search.assert_not_called()


class ReuseComesLastAndIsCapped(unittest.TestCase):
    def test_a_shot_appears_at_most_twice(self):
        a = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=aaaaaaaaaaa",
                             local_path="/w/yt_aaaaaaaaaaa.mp4")
        jobs = [{"index": i, "subject": "Lake Powell", "subject_type": "place"} for i in range(10)]
        results = [a] + [None] * 9
        filled = media.fill_from_story(jobs, results, max_uses=2)
        self.assertEqual(filled, 1)
        self.assertEqual(sum(1 for r in results if r is not None and r.identity == a.identity), 2)

    def test_per_scene_sourcing_leaves_reuse_to_the_rescue_pass_by_default(self):
        self.assertTrue(config.RESCUE_BEFORE_REUSE)
        self.assertEqual(config.REUSE_MAX_USES, 2)


class PictureQuality(unittest.TestCase):
    """A 55 KB slide screenshot filled nine scenes of the Glen Canyon video."""

    def _img(self, w, h, kind):
        from PIL import Image, ImageDraw
        path = os.path.join(tempfile.mkdtemp(), f"{kind}.jpg")
        if kind == "slide":
            im = Image.new("RGB", (w, h), "white")
            d = ImageDraw.Draw(im)
            for row in range(8):                      # rows of letter-like strokes
                y = 60 + row * 80
                for x in range(40, w - 40, 14):
                    d.rectangle([x, y, x + 5, y + 30], fill="black")
        else:
            im = Image.new("RGB", (w, h))
            px = im.load()
            for x in range(w):
                for y in range(0, h, 2):
                    px[x, y] = (40 + x * 150 // w, 90 + y * 100 // h, 160)
                    if y + 1 < h:
                        px[x, y + 1] = px[x, y]
        im.save(path, quality=90)
        return path

    def test_a_slide_is_a_page_of_text_and_a_photo_is_not(self):
        from src import filters
        self.assertTrue(filters.text_page_still(self._img(1280, 720, "slide")))
        self.assertFalse(filters.text_page_still(self._img(1280, 720, "photo")))

    def test_a_small_picture_is_rejected_and_a_1080p_one_passes(self):
        from src import filters
        ok, why = filters.clip_quality(self._img(640, 360, "photo"))
        self.assertFalse(ok)
        self.assertIn("low resolution", why)
        self.assertTrue(filters.clip_quality(self._img(1280, 720, "photo"))[0])

    def test_a_slide_is_refused_except_for_a_document_beat(self):
        slide = media.MediaAsset(kind="image", source="web_image", url="https://x/slide.jpg",
                                 local_path=self._img(1280, 720, "slide"))
        self.assertFalse(media._asset_ok(slide)[0])
        token = media._SUBJECT_TYPE.set("document")
        try:
            self.assertTrue(media._asset_ok(slide)[0])
        finally:
            media._SUBJECT_TYPE.reset(token)


class NewsForStoriesAboutNow(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 29)

    def test_current_story(self):
        with mock.patch.object(director, "_today", return_value=self.TODAY):
            self.assertTrue(director.current_story({"kind": "history", "year": 2026}))
            self.assertTrue(director.current_story({"kind": "weather", "year": None}))
            self.assertFalse(director.current_story({"kind": "history", "year": 1922}))
            self.assertFalse(director.current_story({"kind": "science"}))

    def test_a_2026_story_labelled_history_searches_the_news(self):
        brief = {"kind": "history", "event": "", "year": 2026, "places": ["Lake Powell", "Arizona"]}
        shot = {"subject": "Lake Powell", "subjectType": "place", "visualType": "footage"}
        with mock.patch.object(director, "_today", return_value=self.TODAY), \
                mock.patch.object(config, "NEWS_FOOTAGE", True):
            got = director.news_queries(shot, "Lake Powell dropped again.", brief)
        self.assertIn("Lake Powell news 2026", got)

    def test_the_pools_search_the_news_for_a_current_story(self):
        director.LAST_STORY.clear()
        director.LAST_STORY.update({"kind": "history", "year": 2026})
        try:
            with mock.patch.object(director, "_today", return_value=self.TODAY), \
                    mock.patch.object(config, "NEWS_FOOTAGE", True):
                story = pools.subject_story([{"index": 0, "scene_intent": {"time_context": "current"}}])
        finally:
            director.LAST_STORY.clear()
        self.assertTrue(story["is_event"])


def _seg(text):
    return Segment(text, 0.0, 5.0)


class DatesAndNumbers(unittest.TestCase):
    def test_dates_as_narrators_say_them(self):
        self.assertEqual(treatments.date_in("On the fifteenth of September, the gauge read 3,510 feet.")[0],
                         "SEPTEMBER 15")
        self.assertEqual(treatments.date_in("On August 21st, the federal government handed out cuts.")[0],
                         "AUGUST 21")
        self.assertEqual(treatments.date_in("By September 15, 2026 the lake had dropped.")[0], "SEPTEMBER 15, 2026")
        self.assertEqual(treatments.date_in("The warmest March 2026 on record.")[0], "MARCH 2026")
        self.assertEqual(treatments.date_in("On the twenty-first of June it rained.")[0], "JUNE 21")
        self.assertIsNone(treatments.date_in("Lake Powell has 22 percent left."))

    def test_a_line_that_opens_on_its_date_gets_the_date_card_first(self):
        cues = treatments.cues_for(_seg("On the 15th of September, the gauge at Glen Canyon Dam read 3,510 feet."),
                                   {"subject": "Glen Canyon Dam"}, None)
        self.assertEqual(cues[0]["cue"], "date")
        self.assertEqual(cues[0]["props"]["text"], "SEPTEMBER 15")
        pack = treatments.pack_for({}, "")
        # A date is the centred VidRush date (2026-10-01), never the old letter drop picked by cue.
        moment, _year = treatments.vr_moment("On the 15th of September, the gauge at Glen Canyon Dam read 3,510 feet.")
        self.assertEqual((moment["look"], moment["props"]["text"]), (treatments.VR_HERO, "SEPTEMBER 15"))
        self.assertIsNone(treatments._template_for_cue("date", pack, set(), {}, text="On the 15th of September"))

    def test_a_metaphor_look_needs_its_subject_in_the_line(self):
        self.assertFalse(treatments.look_fits("LIB_NC_THERMOMETER", "13 miles beneath Rocky Mountain National Park"))
        self.assertTrue(treatments.look_fits("LIB_NC_THERMOMETER", "It hit 117 degrees in Phoenix"))
        self.assertTrue(treatments.look_fits("NUM_PILL_V1", "anything at all"))
        pack = treatments.pack_for({}, "")
        for _ in range(12):
            tid = treatments._template_for_cue("measurement", pack, set(), {},
                                               text="It carries water 13 miles beneath Rocky Mountain National Park")
            self.assertNotIn(tid, ("LIB_NC_THERMOMETER", "LIB_NC_STOPWATCH", "LIB_IC_POWER_BOLT",
                                   "LIB_IC_FIRE_FLICKER", "LIB_IC_FACTORY_SMOKE"))

    def test_a_figure_is_labelled_with_what_it_counts(self):
        cues = treatments.cues_for(_seg("The Upper Basin promised 75 million acre feet over any 10-year period."),
                                   {"subject": "Glen Canyon Dam"}, None)
        big = next(c for c in cues if c["cue"] == "big-number")
        self.assertEqual((big["props"]["value"], big["props"]["suffix"], big["props"]["text"]),
                         (75, "MILLION", "ACRE FEET"))


class VisionRetriesCountOnce(unittest.TestCase):
    def setUp(self):
        vision.reset()

    def tearDown(self):
        vision.reset()

    def test_a_503_burst_is_retried_and_counts_once_on_the_breaker(self):
        answers = iter([(None, True), (None, True), ("{\"score\": 0.9}", False)])
        with mock.patch.object(vision, "_ask_once", side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(config, "VISION_RETRIES", 2), \
                mock.patch.object(config, "VISION_RETRY_WAIT", 0.0), \
                mock.patch.object(vision.time, "sleep"):
            text = vision._route_call(("m", "", "", True), [], 100, time.time() + 60)
        self.assertEqual(text, "{\"score\": 0.9}")
        self.assertTrue(vision.model_available("m"))


if __name__ == "__main__":
    unittest.main()
