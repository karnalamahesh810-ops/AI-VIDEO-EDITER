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

from src import config, gapfill, hookcheck, media, reclip, topics, vision

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


class SmokeIsNotSmoking(unittest.TestCase):
    """2026-10-08: the Obama video's Huruma (Nairobi) aerial, which the judge described as "a large, smoking garbage
    dump", was read as a smoking scene (the bare word "smoking") and re-clipped away as off the story. A smoking
    scene is a person seen smoking or vaping, taking drugs or drinking alcohol - said outright."""

    # Real descriptions and titles from saved timelines (Obama 70bc06d2, California c4db28b3, the Yellowstone and
    # Lake Mead projects): smoke from fires, dumps, volcanoes, industry; pipes; a drink from a can.
    RECORDED_NOT_VICE = [
        "An aerial view shows a large, smoking garbage dump next to a road, some buildings, and a body of water.",
        "Burning barricade and smoke on a street in Nairobi, Kenya.",
        "Aerial view of Huruma, Nairobi, showing densely packed buildings and smoke.",
        "A man walks past a burned-out car on a city street in daylight, with smoke rising in the background.",
        "A crowd of people, some in uniform, stand on and around the wreckage of a plane amidst smoke and debris.",
        "Security forces deploying tear gas during anti-government protests in Huruma.",
        "Aerial shot of industrial area with smoke in Southern California",
        "An aerial view of Mount St. Helens with smoke rising from its crater.",
        "People walk on a boardwalk while a large plume of black smoke rises from a geyser in Yellowstone National Park.",
        "People watching the massive hydrothermal explosion and black smoke.",
        "Two images show a man with a beard and glasses, dressed in winter clothing, either eating chips or drinking "
        "from a can, while a smaller inset image shows a woman's headshot.",
        "A close-up shot of an exposed water intake pipe in a body of water, with rock walls and a visible 'bathtub "
        "ring' above.",
        "Ashfall Fossil Beds – Smokey Da Van — https://smokeydavan.com/2023/07/16/ashfall-fossil-beds/",
        "YouTube: Phantom 3 Pro aerial footage of Huruma Slum in Nairobi, Kenya",
    ]
    # Phrasings a judge writes that only look like a vice.
    WORDS_NOT_VICE = [
        "Women smoking fish over an open fire at a market in Kisumu", "Smoked fish for sale at a roadside stall",
        "Factory chimneys smoking over the city", "Smoking ruins of a building after the fire",
        "The volcano smokes above the village", "A smoking pot of stew over an open fire",
        "a joint press conference by the two presidents", "A joint session of Congress", "Joint Base Andrews",
        "A blunt statement from the minister", "Weeds grow on the dry lake bed", "People drinking water from a tap",
        "A plumber holding a pipe under a sink", "Workers rolling steel pipes", "A cigar-shaped cloud over the lake",
        "Cigarette butts litter the beach", "Drunk driving crash on the interstate", "Smoking gun: the memo",
        "Residents smoke out a beehive", "Tobacco fields in Kentucky", "Expansion joints on a bridge",
    ]
    VICE = [
        "A man smoking a cigarette on a porch", "A young man smokes a cigarette outside a shop in Nairobi.",
        "A woman vaping in a car", "Two men pass a joint behind a shop", "A teenager smoking weed in a park",
        "A man lights a cigar.", "Close-up of hands rolling a blunt.", "A group of friends drinking beer at a bar",
        "A man drinks a glass of whiskey", "People snorting cocaine in a club bathroom",
        "A drunk man stumbles down the street", "A man smoking on a balcony", "Youths smoke outside a shop",
        "People smoking shisha at a lounge", "He puffs on his pipe by the fire", "A cigarette burns in an ashtray",
        "Soldiers sit smoking cigarettes", "students vaping behind the school",
    ]
    LINE = "George was photographed outside his home in Huruma, Nairobi"

    def setUp(self):
        topics.set_story(POLITICS, "Why Obama's Brothers Hated Him")

    def tearDown(self):
        topics.set_story({}, "")

    def test_smoke_from_things_is_not_a_smoking_scene(self):
        for text in self.RECORDED_NOT_VICE + self.WORDS_NOT_VICE:
            self.assertFalse(topics.vice_scene(text), text)
            self.assertEqual(topics.scene_reason(text, self.LINE), "", text)

    def test_a_person_smoking_drinking_or_on_drugs_still_is(self):
        for text in self.VICE:
            self.assertTrue(topics.vice_scene(text), text)
            self.assertEqual(topics.scene_reason(text, self.LINE), "a smoking, drugs or drinking scene", text)
        # ...unless the story or the line is about it.
        self.assertEqual(topics.scene_reason(self.VICE[0], "his father was a chain smoker"), "")

    def test_the_huruma_clip_is_not_re_clipped_away(self):
        # Scene s0176 at 828.6 s of the Obama timeline, as saved (obama_current_0af17d2f).
        scene = {"id": "s0176", "text": "In 2012, he was on film saying he had not received it.",
                 "startFrame": 24858, "durationInFrames": 130,
                 "media": {"type": "video", "url": "https://r2/huruma.mp4", "source": "youtube",
                           "attribution": "YouTube: Phantom 3 Pro aerial footage of Huruma Slum in Nairobi, Kenya"},
                 "semanticMetadata": {"intent": "George Obama in Huruma, Nairobi",
                                      "contentDescription": "An aerial view shows a large, smoking garbage dump next "
                                                            "to a road, some buildings, and a body of water."}}
        self.assertEqual(reclip.off_story(scene), "")

    def test_music_videos_stay_off_the_story(self):
        # The rap videos the 2026-10-07 scans found in the California and Obama timelines.
        for title in ("Lil Baby - In A Minute (Official Video)", "Meek Mill - Early Mornings (Official Video)",
                      "B Flow - DEAR MAMA [Chilling with Obama] (Official Video)"):
            scene = {"id": "s1", "text": "Malik moved back to Kenya", "startFrame": 0, "durationInFrames": 90,
                     "media": {"type": "video", "url": "https://r2/x.mp4", "attribution": f"YouTube: {title}"},
                     "semanticMetadata": {"contentDescription": ""}}
            self.assertEqual(reclip.off_story(scene), "a music performance or music video", title)


class TheJudgesVice(unittest.TestCase):
    """The judge names what it saw ("vice"); its music_or_vice stands only with a music video or performance, a club,
    a person smoking or vaping, drugs or alcohol - smoke from a fire is "none", whatever the boolean says."""

    BASE = ('{"description": "%s", "score": 0.7, "quality": 0.8, "has_text_or_watermark": false, '
            '"is_talking_head": false, "ai_generated": false, "studio": false, "specificity": "location", %s}')

    def parse(self, description, tail):
        return vision._parse(self.BASE % (description, tail))

    def test_smoke_from_a_dump_is_no_vice(self):
        dump = "An aerial view shows a large, smoking garbage dump next to a road."
        for tail in ('"music_or_vice": true, "vice": "none"', '"music_or_vice": true, "vice": "smoke from a fire"',
                     '"music_or_vice": "true", "vice": "None"', '"music_or_vice": false, "vice": "smoking"'):
            got = self.parse(dump, tail)
            self.assertFalse(got["music_or_vice"], tail)
            self.assertTrue(vision.acceptable(got), tail)

    def test_a_named_vice_turns_it_down(self):
        for kind in vision.VICE_KINDS + ("music video", "cigarette", "drinking alcohol"):
            got = self.parse("a man smokes a cigarette on a porch", f'"music_or_vice": true, "vice": "{kind}"')
            self.assertTrue(got["music_or_vice"], kind)
            self.assertIn(got["vice"], vision.VICE_KINDS)
            self.assertFalse(vision.acceptable(got), kind)
            self.assertTrue(vision.acceptable(got, allow_vice=True), kind)

    def test_an_answer_without_a_kind_keeps_its_boolean(self):
        self.assertTrue(self.parse("a rapper on stage", '"music_or_vice": true')["music_or_vice"])
        self.assertFalse(self.parse("a village road", '"music_or_vice": false')["music_or_vice"])

    def test_the_prompt_asks_for_a_person_and_the_kind(self):
        self.assertIn('"vice": "music"|"club"|"smoking"|"drugs"|"alcohol"|"none"', vision._SYSTEM)
        self.assertIn("a person smoking or vaping (a cigarette, cigar, pipe, joint or vape at their lips or in "
                      "their hand)", vision._SYSTEM)
        self.assertIn("smoke from a fire, burning rubbish or tyres, a dump, cooking, a chimney or factory, vehicle "
                      "exhaust, tear gas, a wildfire or a volcano is false", vision._SYSTEM)
        self.assertIn("nor is smoke from a fire, a dump, a chimney, a factory, traffic or tear gas",
                      vision._OFF_STORY_RULE)
        for news in (False, True):
            with mock.patch.multiple(config, NEWS_FOOTAGE=news):
                self.assertIn('"vice":', vision._system())


class PoliticsFootage(unittest.TestCase):
    """2026-10-07: the Obama re-clip's opening (two lines about the 2016 Las Vegas debate) had no candidate left:
    every "... Presidential Debate" upload was turned away on its title, and the judge was asked whether a
    convention stage was a "concert stage" or a "party scene"."""

    def test_a_word_the_line_itself_uses_is_not_disqualifying(self):
        title = "Third Presidential Debate: Clinton vs Trump (Full Debate)"
        self.assertTrue(media._talking_head(title))
        self.assertFalse(media._talking_head(title, "the same best man sat in a debate hall in Las Vegas"))
        self.assertFalse(media._usable_title(title, "NBC News", 1.78, "the hall"))
        self.assertTrue(media._usable_title(title, "NBC News", 1.78, "a debate hall in Las Vegas"))
        self.assertTrue(media._talking_head("Lake Mead reaction", "the newspaper said"))     # whole words only

    def test_a_named_persons_own_appearances_on_a_line_about_them(self):
        tok = media._SUBJECT_TYPE.set("person")
        try:
            self.assertFalse(media._talking_head("Malik Obama speaks out about his brother"))
            self.assertFalse(media._talking_head("Malik Obama interview on Fox"))
            self.assertTrue(media._talking_head("Malik Obama reaction video"))               # a creator's reaction
        finally:
            media._SUBJECT_TYPE.reset(tok)
        self.assertTrue(media._talking_head("Malik Obama speaks out about his brother"))

    def test_the_judge_is_told_a_rally_or_a_convention_is_not_a_party_scene(self):
        self.assertIn("political rally, convention, debate, speech, hearing, ceremony, wedding or state dinner is false",
                      vision._SYSTEM)
        self.assertIn("political rally, convention, debate, speech or ceremony is not such a shot",
                      vision._OFF_STORY_RULE)


if __name__ == "__main__":
    unittest.main()
