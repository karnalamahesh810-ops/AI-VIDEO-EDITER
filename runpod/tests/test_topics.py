"""
Topic-aware music / rap / smoking filters (src/topics.py; the owner, 2026-10-06: rapper and music-video clips and
people smoking in a story about a politician's brothers - "we don't want those clips in our videos" - and then:
not a global ban, other users make videos ABOUT music and rappers).

A story and a line not about music, nightlife, smoking, drugs or drinking turn such a candidate down at search time
by its title, channel or YouTube category, and the vision judge's music_or_vice answer turns a downloaded one down
(remembered for the job). A story about a rapper keeps them - judged for relevance like any clip.

Offline: every model answer is a stub.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from src import config, gapfill, hookcheck, media, topics, vision

WATER = {"summary": "California's reservoirs are draining and these cities could run short of water first",
         "kind": "explainer", "people": []}
POLITICS = {"summary": "Why Barack Obama's half-brothers resented him: a family split between Kenya and America",
            "kind": "biography", "people": ["Barack Obama", "Malik Obama"]}
RAPPER = {"summary": "How a Compton rapper became the biggest name in hip-hop", "kind": "biography",
          "cast": [{"name": "Kendrick Lamar", "role": "Rapper"}]}

MUSIC_TITLES = ["Kendrick Lamar - Not Like Us (Official Music Video)", "Drake - God's Plan (Lyrics)",
                "Sunset Drive ft. Lil Baby", "Big Sean (Official Audio)", "Lil Wayne Freestyle",
                "SomeArtist - Diss Track", "Mask Off (Remix)", "Obama meets the rapper on stage"]


class Story(unittest.TestCase):
    def tearDown(self):
        topics.set_story({}, "")

    def test_a_water_or_politics_story_turns_music_videos_down_by_title(self):
        for brief, title in ((WATER, "California's Water Clock"), (POLITICS, "Why Obama's Brothers Hated Him")):
            topics.set_story(brief, title)
            for t in MUSIC_TITLES:
                self.assertTrue(topics.off_topic_title(t, "", line="Malik moved back to Kenya"), t)
                self.assertFalse(media._usable_title(t, "", 1.78, "Malik moved back to Kenya"), t)
            self.assertFalse(media._usable_title("Song", "SomeArtistVEVO", 1.78, "Lake Oroville"))

    def test_a_story_about_a_rapper_keeps_them(self):
        topics.set_story(RAPPER, "How Kendrick Won")
        for t in MUSIC_TITLES:
            self.assertEqual(topics.off_topic_title(t, "", line="He grew up in Compton"), "", t)
            self.assertTrue(media._usable_title(t, "", 1.78, "He grew up in Compton"), t)

    def test_a_line_about_music_keeps_them_in_any_story(self):
        topics.set_story(POLITICS, "Why Obama's Brothers Hated Him")
        self.assertEqual(topics.off_topic_title(MUSIC_TITLES[0], "", line="Obama's summer playlist and the songs "
                                                                             "he loved"), "")

    def test_ordinary_titles_are_never_music(self):
        topics.set_story(WATER, "California's Water Clock")
        for t in ("24 ft. seas batter the coast", "Men's 100m Freestyle Final | Tokyo 2020",
                  "Lake Oroville drone footage 2026", "BMX freestyle at the skate park"):
            self.assertEqual(topics.music_title(t), "", t)
            self.assertTrue(media._usable_title(t, "", 1.78, "the reservoir"), t)
        # YouTube's Music category: a performance is turned down, a scenery film set to music is footage.
        self.assertTrue(topics.music_title("Live at Wembley", "", ["Music"]))
        self.assertEqual(topics.music_title("Lake Mead 4K drone footage", "Relaxing Music", ["Music"]), "")

    def test_the_vice_topics(self):
        topics.set_story(WATER, "California's Water Clock")
        self.assertFalse(topics.allows_vice("drinking water shortages in Fresno"))
        self.assertFalse(topics.allows_vice("drinking-water wells run dry"))
        self.assertFalse(topics.allows_vice("wildfire smoke over the valley"))
        topics.set_story(POLITICS, "Why Obama's Brothers Hated Him")
        self.assertTrue(topics.allows_vice("his father was a heavy drinker"))
        self.assertTrue(topics.allows_vice("Obama quit smoking in 2010"))
        self.assertFalse(topics.allows_vice("Malik lives in Kogelo"))
        self.assertFalse(topics.allows_music("his rap sheet grew"))

    def test_a_scene_already_on_a_timeline(self):
        topics.set_story(POLITICS, "")
        self.assertTrue(topics.scene_reason("A rapper performs on stage with dancers", "Malik moved to Kenya"))
        self.assertTrue(topics.scene_reason("A man smoking a cigarette on a porch", "Malik moved to Kenya"))
        self.assertEqual(topics.scene_reason("A man smoking a cigarette on a porch", "his father, a heavy smoker"),
                         "")
        self.assertEqual(topics.scene_reason("A village road in western Kenya", "Malik moved to Kenya"), "")
        topics.set_story(RAPPER, "")
        self.assertEqual(topics.scene_reason("A rapper performs on stage", "his first big show"), "")


class TheMetadata(unittest.TestCase):
    def tearDown(self):
        topics.set_story({}, "")

    def test_the_music_category_is_read_before_scouting(self):
        info = {"title": "Concert", "width": 1920, "height": 1080, "duration": 300, "categories": ["Music"]}
        topics.set_story(WATER, "")
        self.assertIn("music video", media.meta_reject(info, line="Lake Oroville is half empty"))
        topics.set_story(RAPPER, "")
        self.assertEqual(media.meta_reject(info, line="his first big show"), "")


class TheJudge(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.path = os.path.join(self.work, "clip.mp4")
        open(self.path, "wb").write(b"clip")
        vision._CACHE.clear()

    def tearDown(self):
        topics.set_story({}, "")
        vision.set_story({})
        vision._CACHE.clear()

    def verdict(self, **kw):
        v = {"score": 0.8, "quality": 0.8, "has_text_or_watermark": False, "is_talking_head": False,
             "ai_generated": False, "studio": False, "music_or_vice": True, "description": "a rapper on stage",
             "specificity": "generic"}
        v.update(kw)
        return v

    def test_the_prompt_says_off_story_only_when_the_story_is_not_about_it(self):
        sent = []

        def ask(messages, max_tokens, accept=None):
            sent.append(" ".join(p.get("text", "") for p in messages[1]["content"] if isinstance(p, dict)))
            return json.dumps(self.verdict()), "test-model"
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "sample_frames", return_value=["AAAA"]), \
                mock.patch.object(vision, "_ask", side_effect=ask):
            vision.set_story(WATER)
            got = vision.judge(self.path, "the reservoir's bathtub ring", "Lake Oroville dropped 40 feet")
            self.assertTrue(got["music_or_vice"])
            self.assertIn("OFF-STORY", sent[-1])
            vision.set_story(RAPPER)
            vision.judge(self.path, "the rapper's first big show", "his first big show")
            self.assertNotIn("OFF-STORY", sent[-1])

    def test_acceptable_turns_it_down_unless_the_topic_allows_it(self):
        v = self.verdict()
        self.assertFalse(vision.acceptable(v))
        self.assertTrue(vision.acceptable(v, allow_vice=True))
        self.assertFalse(vision.acceptable(self.verdict(score=0.3), allow_vice=True))      # relevance stays strict

    def gate(self, story, intent, context):
        topics.set_story(story, "")
        with mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "_local_check", return_value=None), \
                mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "judge", return_value=self.verdict()), \
                mock.patch.multiple(config, JUDGE_MEMORY=True):
            media._GATE_SLOP.set("")
            keep, verdict = media._judge_gate(self.path, intent, context, "a clip")
            return keep, verdict, media._GATE_SLOP.get()

    def test_the_gate_in_a_water_story_rejects_and_remembers(self):
        keep, verdict, why = self.gate(WATER, "the reservoir's bathtub ring", "Lake Oroville dropped 40 feet")
        self.assertFalse(keep)
        self.assertTrue(verdict["off_topic"])                          # never the "best available" either
        self.assertIn("music, club or smoking", why)                    # remembered for the whole job
        self.assertTrue(why.startswith(media._LINE_FREE))

    def test_the_gate_in_a_rapper_story_keeps_a_relevant_one(self):
        keep, verdict, why = self.gate(RAPPER, "the rapper performing his breakout single", "his first big show")
        self.assertTrue(keep)
        self.assertFalse(verdict.get("off_topic"))
        self.assertEqual(why, "")

    def test_the_hook_check_says_why(self):
        topics.set_story(POLITICS, "")
        with mock.patch.object(hookcheck, "enabled", return_value=True), \
                mock.patch.object(hookcheck, "spent", return_value=False), \
                mock.patch.object(hookcheck, "_reserve", return_value=True), \
                mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "judge", return_value=self.verdict()):
            keep, verdict = hookcheck.judge(self.path, {"intent": "Malik in Kogelo", "context": "Malik lives in Kogelo",
                                                        "seconds": 4.0})
        self.assertFalse(keep)
        self.assertTrue(verdict["off_topic"])
        self.assertFalse(hookcheck.soft(verdict))
        self.assertIn("music, club or smoking", hookcheck.why(verdict))


class TheDonors(unittest.TestCase):
    def tearDown(self):
        topics.set_story({}, "")

    def test_no_other_moment_of_a_music_video(self):
        topics.set_story(POLITICS, "")

        def s(n, title, desc):
            return {"id": f"s{n}", "text": "Malik moved back to Kenya", "startFrame": n * 90, "durationInFrames": 90,
                    "media": {"type": "video", "url": f"https://r2/{n}.mp4", "attribution": f"YouTube: {title}"},
                    "semanticMetadata": {"assetId": f"yt:VID{n:08d}", "moment": {"start": 60.0},
                                         "sourceUrl": f"https://www.youtube.com/watch?v=VID{n:08d}&t=60",
                                         "contentDescription": desc}}
        doc = {"fps": 30, "scenes": [s(0, "Kogelo village road", "a dirt road in a village"),
                                     s(1, "Song ft. Somebody", "a rapper performing in a club")]}
        self.assertEqual([d["vid"] for d in gapfill.donors_from_doc(doc)], ["VID00000000"])


if __name__ == "__main__":
    unittest.main()
