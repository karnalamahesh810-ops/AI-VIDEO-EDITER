"""The Hoover Dam video fixes (2026-10-26, docs/vidfix-2026-10-26.md): clips, stills, names, text."""
import unittest
from unittest import mock

from src import config, media


class SlopChannelMemory(unittest.TestCase):
    def setUp(self):
        media.reset_cache()

    def test_ai_upload_strikes_the_channel_at_once(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            self.assertEqual(media.note_slop_channel("Disaster Daily AI", "an AI-generated or painted picture (art 0.81)"), 2)
            self.assertTrue(media.slop_channel("disaster daily ai "))
            self.assertEqual(media.SLOP_CHANNEL_STATS["struck"], 1)

    def test_a_slideshow_needs_two(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            media.note_slop_channel("Flood Slides", "a slideshow of stills")
            self.assertFalse(media.slop_channel("Flood Slides"))
            media.note_slop_channel("Flood Slides", "a still with a slow pan or zoom")
            self.assertTrue(media.slop_channel("Flood Slides"))

    def test_the_judge_saying_ai_counts(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            media.note_slop_channel("X", "", {"ai_generated": True})
            self.assertTrue(media.slop_channel("X"))

    def test_other_reasons_and_news_channels_never_strike(self):
        with mock.patch.object(media, "_story_channels", lambda: ["KTNV Channel 13 Las Vegas"]):
            for _ in range(3):
                media.note_slop_channel("KTNV Channel 13 Las Vegas", "a slideshow of stills")
                media.note_slop_channel("Some Vlogger", "burned-in text or UI")
                media.note_slop_channel("Other", "", {"has_text_or_watermark": True})
            self.assertFalse(media.slop_channel("KTNV Channel 13 Las Vegas"))
            self.assertFalse(media.slop_channel("Some Vlogger"))
            self.assertFalse(media.slop_channel("Other"))

    def test_off_switch_and_job_reset(self):
        with mock.patch.object(media, "_story_channels", lambda: []):
            media.note_slop_channel("A", "an AI-generated or painted picture")
            media.reset_cache()
            self.assertFalse(media.slop_channel("A"))
            with mock.patch.object(config, "SLOP_CHANNEL_MEMORY", False):
                media.note_slop_channel("A", "an AI-generated or painted picture")
                self.assertFalse(media.slop_channel("A"))


def _job(i, subject_type="event", loc="Lake Mead", start=None, visual="footage", tc="oct 2026"):
    return {"index": i, "seconds": 5.0, "visual_type": visual, "subject_type": subject_type,
            "subject": f"{loc} flooding", "start": i * 5.0 if start is None else start,
            "scene_intent": {"locations": [loc], "entities": [], "time_context": tc}}


def _clip(vid, start=60.0):
    return media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                            local_path=f"/w/{vid}.mp4", duration=5.5, attribution="YouTube: x",
                            moment={"start": start})


def _still(n):
    return media.MediaAsset(kind="image", source="web_image", url=f"https://e.com/{n}.jpg", local_path=f"/w/{n}.jpg")


class StillsToChains(unittest.TestCase):
    ON = dict(CLIPS_FIRST=True, CLIPS_FIRST_STILLS=True, PREFER_GENERATED_IMAGES=False, STILLS_TO_CLIPS=True,
              PERSON_CLIPS_FIRST=True, FILL_MAX_MOMENTS_PER_VIDEO=4, MAX_MOMENTS_PER_VIDEO=3)

    def _run(self, jobs, results, spare=None):
        fetched = []

        def fake_fetch(vid, out_dir, at, need, title="", least=None):
            fetched.append((vid, round(at, 1)))
            return f"/w/{vid}_{int(at)}.mp4", True, 0
        with mock.patch.multiple(config, **self.ON), \
                mock.patch.object(media, "fetch_clean_clip", fake_fetch), \
                mock.patch.object(media, "_asset_ok", lambda a: (True, "")), \
                mock.patch.object(media, "motion_rejects", lambda p: ""), \
                mock.patch.object(media, "slop_reason", lambda p, l="": ""), \
                mock.patch.object(media, "youtube_only", lambda: False), \
                mock.patch.object(media.ledger, "moment_used", lambda *a: False), \
                mock.patch("src.gapfill._from_spare", spare or (lambda *a, **k: None)):
            out = media.stills_to_chains(jobs, results, work_dir="/w", seconds=60)
        return out, fetched

    def test_a_run_of_stills_gets_clips_at_both_ends_and_no_still_follows_a_still(self):
        jobs = [_job(i) for i in range(5)]
        results = [_clip("AAAAAAAAAAA"), _still(1), _still(2), _still(3), _clip("BBBBBBBBBBB", 100.0)]
        out, fetched = self._run(jobs, results)
        self.assertEqual((out["forward"], out["backward"]), (1, 1))
        self.assertEqual([r.kind for r in results], ["video", "video", "image", "video", "video"])
        self.assertEqual(fetched[0], ("AAAAAAAAAAA", round(60 + 5.5 + media.CHAIN_SKIP_SECONDS, 1)))
        self.assertLess(fetched[1][1], 100.0)                        # the moment before the next clip
        self.assertTrue(results[1].moment["chain"] and results[1].judged_by == "chain")

    def test_people_documents_the_past_and_unrelated_lines_keep_their_picture(self):
        jobs = [_job(0), _job(1, "person"), _job(2), _job(3, "document"), _job(4),
                _job(5, tc="1936"), _job(6)]
        jobs[2]["scene_intent"]["locations"] = ["Flaming Gorge"]     # names nothing the clip's line names
        jobs[2]["subject"] = "Flaming Gorge releases"
        results = [_clip("AAAAAAAAAAA"), _still(1), _still(2), _still(3), _clip("CCCCCCCCCCC"), _still(5),
                   _clip("DDDDDDDDDDD")]
        out, _f = self._run(jobs, results)
        self.assertEqual([r.kind for r in results][1:4], ["image", "image", "image"])
        self.assertEqual(results[5].kind, "image")                  # 1936: not a modern clip
        self.assertEqual(out["eligible"], 1)

    def test_a_still_after_a_still_takes_a_spare_clip(self):
        jobs = [_job(i) for i in range(4)]
        results = [_still(0), _still(1), _still(2), _still(3)]
        spare = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=SSSSSSSSSSS",
                                 local_path="/w/s.mp4")
        calls = []

        def fake_spare(job, used, work, stop, kind="video"):
            calls.append(job["index"])
            return spare if job["index"] == 1 else None
        out, _f = self._run(jobs, results, fake_spare)
        self.assertEqual(out["spare"], 1)
        self.assertEqual(results[1].kind, "video")
        self.assertIn(1, calls)

    def test_off_switch(self):
        jobs = [_job(0), _job(1)]
        results = [_clip("AAAAAAAAAAA"), _still(1)]
        with mock.patch.object(config, "STILLS_TO_CLIPS", False):
            out = media.stills_to_chains(jobs, results, work_dir="/w")
        self.assertEqual(results[1].kind, "image")
        self.assertEqual(out["eligible"], 0)


class StillFrame(unittest.TestCase):
    def setUp(self):
        from src import stillframe
        self.sf = stillframe

    def test_a_portrait_is_a_card_never_a_crop(self):
        tall = {"w": 600, "h": 800, "lines": 600, "faces": [[0.35, 0.2, 0.3, 0.3, 0.9, 0.3]]}
        self.assertTrue(self.sf.is_portrait({"semanticMetadata": {"subjectType": "person"}}, tall))
        self.assertTrue(self.sf.is_portrait({"semanticMetadata": {"subjectType": "event"}}, tall))   # tall: a card
        wide = {"w": 1920, "h": 1080, "lines": 1080, "faces": [[0.45, 0.35, 0.1, 0.18, 0.9, 0.4]]}
        self.assertFalse(self.sf.is_portrait({"semanticMetadata": {"subjectType": "event"}}, wide))
        # 4:3 with the face near the top: the 16:9 crop takes its forehead off
        top = {"w": 1600, "h": 1200, "lines": 1200, "faces": [[0.42, 0.06, 0.16, 0.2, 0.9, 0.12]]}
        self.assertTrue(self.sf.crop_cuts_face(top))
        self.assertTrue(self.sf.is_portrait({"semanticMetadata": {}}, top))

    def test_the_card_never_outgrows_its_detail(self):
        small = {"w": 400, "h": 500, "lines": 400, "faces": []}
        c = self.sf.card_for(small, beside_name=True)
        self.assertAlmostEqual(c["max"], round(500 * 1.15 / 1080, 3), places=3)
        self.assertEqual(c["x"], self.sf.CARD_X_BESIDE_NAME)
        big = {"w": 3000, "h": 4000, "lines": 3000, "faces": []}
        self.assertEqual(self.sf.card_for(big, beside_name=False), {"max": 0.84, "x": 0.5})

    def test_moves_are_held_to_real_detail(self):
        sharp = {"w": 3840, "h": 2160, "lines": 2160, "faces": []}
        soft = {"w": 1920, "h": 1280, "lines": 800, "faces": []}      # an upscaled web picture
        self.assertEqual(self.sf.max_zoom(sharp), 1.6)
        self.assertEqual(self.sf.max_zoom(soft), 1.02)

    def test_place_writes_cards_caps_aims_and_calms(self):
        import os
        import tempfile
        d = tempfile.mkdtemp()
        paths = []
        for n in range(3):
            p = os.path.join(d, f"p{n}.jpg")
            with open(p, "wb") as fh:
                fh.write(b"x")
            paths.append(p)
        facts = {paths[0]: {"w": 500, "h": 700, "lines": 500, "faces": [[0.3, 0.2, 0.35, 0.3, 0.9, 0.3]]},
                 paths[1]: {"w": 1920, "h": 1280, "lines": 800, "faces": []},
                 paths[2]: {"w": 3840, "h": 2160, "lines": 2160, "faces": [[0.45, 0.3, 0.08, 0.15, 0.9, 0.35]]}}
        doc = {"fps": 60, "scenes": [
            {"id": "s0", "startFrame": 0, "durationInFrames": 300, "motion": "zoom-in", "frame": "full",
             "media": {"type": "image", "url": paths[0], "source": "web_image"},
             "semanticMetadata": {"subjectType": "person"}},
            {"id": "s1", "startFrame": 300, "durationInFrames": 300, "motion": "pull-back", "frame": "full",
             "media": {"type": "image", "url": paths[1], "source": "web_image"}, "semanticMetadata": {}},
            {"id": "s2", "startFrame": 600, "durationInFrames": 300, "motion": "reveal-left", "frame": "full",
             "media": {"type": "image", "url": paths[2], "source": "wikimedia"}, "semanticMetadata": {}}],
            "overlays": [{"startFrame": 10, "durationInFrames": 200, "template": "SMART_SPEC",
                          "smart": {"design": {"kind": "label"}}}]}
        with mock.patch.object(config, "STILL_MOTION_MAX_ZOOM", 1.06):
            st = self.sf.place(doc, facts_fn=facts.get)
        s0, s1, s2 = doc["scenes"]
        self.assertEqual((s0["motion"], s0["media"]["card"]["x"]), ("parallax", self.sf.CARD_X_BESIDE_NAME))
        self.assertEqual((s1["motion"], s1["media"]["maxZoom"], s1["media"]["moveMax"]), ("zoom-out", 1.02, 1.06))
        self.assertEqual(s2["motion"], "push-offcenter")                  # a reveal calmed
        self.assertEqual(s2["media"]["reframe"]["kind"], "face")
        self.assertEqual((st["cards"], st["aimed"], st["calmed"]), (1, 1, 2))


class EditingOnStills(unittest.TestCase):
    def test_no_punch_on_a_low_res_still_or_a_card(self):
        from src import editing
        low = {"frame": "full", "motion": "zoom-in", "media": {"type": "image", "maxZoom": 1.02}}
        sharp = {"frame": "full", "motion": "zoom-in", "media": {"type": "image", "maxZoom": 1.6}}
        card = {"frame": "full", "motion": "parallax", "media": {"type": "image", "card": {"max": 0.6}}}
        old_soft = {"frame": "full", "motion": "zoom-in", "media": {"type": "image"},
                    "semanticMetadata": {"scoreParts": {"magnification": 1.7}}}
        self.assertFalse(editing._punchable(low, True))
        self.assertTrue(editing._punchable(sharp, True))
        self.assertFalse(editing._punchable(card, True))
        self.assertFalse(editing._punchable(old_soft, True))
        self.assertEqual(editing.still_room(card), 1.0)
        self.assertAlmostEqual(editing.still_room(sharp), 1.6 / 1.15, places=3)


class CopiesAndPlacement(unittest.TestCase):
    def _pic(self, d, name, seed):
        import os
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (640, 360), (20 + seed * 30 % 200, 60, 90))
        dr = ImageDraw.Draw(im)
        for k in range(8):
            dr.rectangle([k * 80, (seed * 37 + k * 53) % 300, k * 80 + 40, 360], fill=((seed * 71 + k * 29) % 255, 200, 40))
        p = os.path.join(d, name)
        im.save(p, quality=90)
        return p

    def test_the_same_photo_from_another_site_is_a_repeat(self):
        import shutil
        import tempfile
        from src import gapfill
        d = tempfile.mkdtemp()
        a = self._pic(d, "a.jpg", 1)
        b = shutil.copy(a, d + "/b_other_site.jpg")
        c = self._pic(d, "c.jpg", 5)

        def sc(i, path, src):
            return {"id": f"s{i}", "startFrame": i * 300, "durationInFrames": 300,
                    "media": {"type": "image", "url": path, "source": "web_image"},
                    "semanticMetadata": {"assetId": f"web_image:{src}", "sourceUrl": src}}
        doc = {"fps": 60, "scenes": [sc(0, a, "https://one/a.jpg"), sc(1, c, "https://two/c.jpg"),
                                     sc(2, b, "https://three/a-copy.jpg")]}
        found = gapfill.find_repeats(doc)
        self.assertEqual([i for i, _w in found], [2])
        self.assertIn("copy", found[0][1])
        with mock.patch.object(config, "PICTURE_COPY_CHECK", False):
            self.assertEqual(gapfill.find_repeats(doc), [])

    def test_the_build_measures_a_local_picture(self):
        import tempfile
        from src import lookplace
        d = tempfile.mkdtemp()
        p = self._pic(d, "p.jpg", 2)
        self.assertTrue(lookplace.fetch_local(p).startswith(b"\xff\xd8"))
        self.assertEqual(lookplace._picture_url({"type": "video", "url": p}), p)      # a local file: its own frame
        self.assertEqual(lookplace._picture_url({"type": "video", "url": "https://x/a.mp4"}), "")


if __name__ == "__main__":
    unittest.main()
