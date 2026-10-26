"""Round 2 of the Hoover Dam fixes (2026-10-26): what slipped past the slop filter and the judge, AI fill on news,
date looks in one place, looks that end at their cut. Cases are the video's own titles and the judge's own words."""
import unittest
from unittest import mock

from src import config, slipcheck, vision


class Titles(unittest.TestCase):
    def test_hypotheticals_and_cgi_explainers_are_turned_down(self):
        for t in ("What Happens If Hoover Dam Breaks? (The Flood Is Only the Beginning)",
                  "The First 24 Hours After Hoover Dam Fails - Hour By Hour",
                  "Hoover Dam: The Untold Story of How It Was Built | America's Engineering Marvel",
                  "Hoover Dam: How Water Ate a 45-Foot Hole the Size of a House!",
                  "Lake Mead 3D animation of the drought"):
            self.assertTrue(slipcheck.title_flaw(t), t)

    def test_real_footage_titles_stay(self):
        for t in ("Historic San Juan River Flooding in Shiprock, New Mexico (Drone Footage)",
                  "[RAW VIDEO] Heavy flood waters move through near Hotel Rio",
                  "Storm Rachel brings flooding, debris and downed power lines to Las Vegas",
                  "What's REALLY Inside Hoover Dam? 500ft Down on the Official USBR Tour! 4K Adventure 2026",
                  "Hoover Dam rafting tours offer rare view from the river",
                  "Lake Mead DROPS To 26% - Water So LOW A Sunken Highway Is REAPPEARING"):
            self.assertEqual(slipcheck.title_flaw(t), "", t)

    def test_a_line_about_a_simulation_may_take_one(self):
        self.assertEqual(slipcheck.title_flaw("Dam break simulation", "a simulation of a dam break"), "")

    def test_off_switch(self):
        with mock.patch.object(config, "SLIP_CHECKS", False):
            self.assertEqual(slipcheck.title_flaw("What Happens If Hoover Dam Breaks?"), "")


class TheJudgesOwnWords(unittest.TestCase):
    def test_an_animation_is_a_render_on_any_line_but_a_map_or_chart(self):
        d = "An animation of Lake Mead and Hoover Dam with an overlay showing \"Operating Elevations\""
        self.assertIn("render", slipcheck.description_flaw(d, "clip", news=True))
        self.assertIn("render", slipcheck.description_flaw(d, "clip", news=False))
        self.assertEqual(slipcheck.description_flaw(d, "clip", wants="chart", news=True), "")

    def test_a_creators_overlay_on_a_news_clip_but_a_stations_banner_stays(self):
        self.assertIn("creator", slipcheck.description_flaw(
            "A wide view of a lake with a bathtub ring, with a graphic overlay.", "clip", news=True))
        self.assertIn("creator", slipcheck.description_flaw(
            "The power plant interior with an American flag and a banner \"The Hoover Dam underground tour\".",
            "clip", news=True))
        self.assertEqual(slipcheck.description_flaw(
            "Rain on a car windshield with a news overlay that says \"LAS VEGAS FLASH FLOODING\".", "clip", news=True), "")
        self.assertEqual(slipcheck.description_flaw(
            "Floodwater on a street with a news chyron \"FLOODING FORCES EVACUATIONS\".", "clip", news=True), "")

    def test_on_a_strict_line_the_second_look_decides_a_clips_overlay(self):
        self.assertEqual(slipcheck.description_flaw("Underwater cameras with text overlays and a date stamp", "clip",
                                                    news=False), "")

    def test_pictures_that_are_screen_grabs_collages_or_mockups(self):
        self.assertIn("TV frame", slipcheck.description_flaw(
            "Heavy rain on a street, with a news chyron \"HEAVY RAINS TRIGGER FLASH FLOODING\".", "picture"))
        self.assertTrue(slipcheck.description_flaw(
            "Two split-screen comparisons show Lake Mead before and after an inflow of water.", "picture"))
        self.assertTrue(slipcheck.description_flaw("Lake Mead before and after, side by side.", "picture"))
        self.assertIn("mock-up", slipcheck.description_flaw(
            "A person holds a tablet displaying a document titled \"BUREAU OF RECLAMATION\".", "picture",
            subject_type="document"))
        self.assertEqual(slipcheck.description_flaw(
            "A close-up shot shows a page of typewritten text with three punched holes.", "picture",
            subject_type="document"), "")
        self.assertEqual(slipcheck.description_flaw(
            "An aerial shot of Hoover Dam and the low water level of Lake Mead.", "picture"), "")


class Banners(unittest.TestCase):
    def test_a_banner_naming_another_state(self):
        with mock.patch("src.media.title_conflict", lambda t, c: "another state" if "California" in t else ""):
            self.assertIn("banner", slipcheck.screen_text_conflict("Powerful waves batter Southern California coast",
                                                                   "Las Vegas Strip flooding, Nevada"))
            self.assertEqual(slipcheck.screen_text_conflict("Storm Rachel floods roads near Strip",
                                                            "Las Vegas Strip flooding, Nevada"), "")

    def test_the_judge_reads_the_banner(self):
        got = vision._parse('{"description": "x", "score": 0.8, "screen_text": "  POWERFUL WAVES   BATTER  "}') \
            if hasattr(vision, "_parse") else None
        if got is not None:
            self.assertEqual(got["screen_text"], "POWERFUL WAVES BATTER")
        self.assertIn('"screen_text": str', vision._SYSTEM)


class WhoseLogo(unittest.TestCase):
    def test_stations_agencies_and_channel_numbers_are_broadcasters(self):
        for c, t in (("FOX5 Las Vegas", ""), ("KTNV Channel 13 Las Vegas", ""), ("", "KOLD"), ("", "CBS"),
                     ("8NewsNow", ""), ("National Park Service", ""), ("", "13"), ("", "CNBC")):
            self.assertTrue(slipcheck.broadcaster(c, t), (c, t))

    def test_creators_are_not(self):
        for c, t in (("Level", ""), ("Window to the World", ""), ("Breaking Elements", "BE"), ("", "LEVEL"),
                     ("What Wild Kids", "")):
            self.assertFalse(slipcheck.broadcaster(c, t), (c, t))
        self.assertIsNone(slipcheck.broadcaster("", ""))

    def test_the_news_rule_turns_down_a_creators_furniture(self):
        def look(kind, text=""):
            return {"added": True, "items": [{"kind": kind, "where": "corner", "text": text}]}
        self.assertTrue(vision.text_check_decision(look("logo", "LEVEL"), "news"))
        self.assertTrue(vision.text_check_decision(look("logo", "window to the world"), "news", uploader="Window"))
        self.assertEqual(vision.text_check_decision(look("logo", "FOX 5"), "news"), "")
        self.assertEqual(vision.text_check_decision(look("logo", ""), "news", uploader="KTNV Channel 13"), "")
        self.assertEqual(vision.text_check_decision(look("tv_graphics", "STORM RACHEL FLOODS ROADS"), "news"), "")
        self.assertTrue(vision.text_check_decision(look("typed_text", "The Hoover Dam underground tour"), "news"))
        self.assertTrue(vision.text_check_decision(look("overlay", "OPERATING ELEVATIONS"), "news"))
        with mock.patch.object(config, "VISION_NEWS_CREATOR_MARKS", False):
            self.assertEqual(vision.text_check_decision(look("logo", "LEVEL"), "news"), "")


class AiFillOnNews(unittest.TestCase):
    def test_a_real_news_moment_never_gets_an_ai_picture(self):
        from src import aifill
        story = {"kind": "news"}
        for line in ("Video showed what appeared to be swift water rescues on the 2.15 at Charleston Boulevard.",
                     "And then came this week.", "Friday, October 23rd, in farming to New Mexico."):
            self.assertTrue(aifill.news_event_line({}, line, story), line)
        self.assertFalse(aifill.news_event_line({}, "When rain does the watering, farms order less.", story))
        self.assertFalse(aifill.news_event_line({}, "Video showed the rescue.", {"kind": "history"}))
        with mock.patch.object(config, "AI_FILL_NEWS_EVENTS", True):
            self.assertFalse(aifill.news_event_line({}, "And then came this week.", story))

    def test_every_ai_scene_is_labelled_once(self):
        from src import aifill
        doc = {"fps": 60, "overlays": [], "scenes": [
            {"id": "s0", "startFrame": 0, "durationInFrames": 300, "media": {"type": "image", "source": "web_image"}},
            {"id": "s1", "startFrame": 300, "durationInFrames": 240, "media": {"type": "image", "source": aifill.AI_SOURCE}}]}
        self.assertEqual(aifill.label_scenes(doc), 1)
        self.assertEqual(aifill.label_scenes(doc), 0)
        tag = doc["overlays"][0]
        self.assertEqual((tag["template"], tag["label"], tag["startFrame"], tag["durationInFrames"]),
                         ("LIB_SRC_TAG", "AI", 300, 240))
        self.assertIn("ILLUSTRATION", tag["text"])


class LooksEndAtCuts(unittest.TestCase):
    def test_a_number_ends_at_the_cut_when_it_has_had_time(self):
        from src import editing
        doc = {"fps": 60, "scenes": [{"startFrame": 0, "durationInFrames": 240}, {"startFrame": 240, "durationInFrames": 300},
                                     {"startFrame": 540, "durationInFrames": 300, "splitFrom": "s1"},
                                     {"startFrame": 840, "durationInFrames": 300}],
               "overlays": [{"template": "KT_NUMBER", "startFrame": 0, "durationInFrames": 270},      # cut at 4.0 s
                            {"template": "KT_DATE", "startFrame": 180, "durationInFrames": 300},      # cut after 1 s
                            {"template": "SMART_SPEC", "startFrame": 300, "durationInFrames": 300},   # a split: no cut
                            {"template": "LIB_SRC_TAG", "startFrame": 0, "durationInFrames": 600}]}
        got = editing.end_at_cuts(doc)
        self.assertEqual([o["durationInFrames"] for o in doc["overlays"]], [240, 300, 300, 600])
        self.assertEqual(got, {"crossing": 2, "ended": 1, "kept": 1})


if __name__ == "__main__":
    unittest.main()
