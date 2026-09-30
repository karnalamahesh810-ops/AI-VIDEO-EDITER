"""Cut on names (src/mentions.py): the person is on screen WHILE the name is said."""
import copy
import dataclasses
import os
import unittest
from unittest import mock

from src import config, director, mentions, timeline
from src.transcribe import Segment, Word, align_to_script, segment_words


def timed(text: str, start: float = 0.0, step: float = 0.5) -> Segment:
    """A beat whose words start every `step` seconds (each lasting 90% of it)."""
    words, t = [], start
    for token in text.split():
        words.append(Word(token, round(t, 3), round(t + step * 0.9, 3)))
        t += step
    return Segment(text=text, start=start, end=round(t - step * 0.1, 3), words=words)


def words_from(text: str, wps: float = 2.6, start: float = 0.0):
    """Fake whisper output, as in test_pipeline: a pause after each sentence."""
    out, t = [], start
    for token in text.split():
        end = t + 1.0 / wps
        out.append(Word(text=token, start=round(t, 3), end=round(end, 3)))
        t = end + (0.35 if token[-1:] in ".!?" else 0.02)
    return out


def news_brief(**kw) -> dict:
    brief = {"kind": "news", "event": "2026 Arizona groundwater cuts", "year": 2026, "recent": True,
             "places": ["Phoenix, Arizona", "Lake Mead"], "people": ["Katie Hobbs", "Doug Burgum"],
             "cast": [{"name": "Katie Hobbs", "role": "Governor of Arizona", "aliases": ["the governor"]},
                      {"name": "Doug Burgum", "role": "Interior Secretary", "aliases": []}],
             "hookBeats": [0], "sections": []}
    brief.update(kw)
    return brief


# Katie at 4.5 s of a 9.45 s beat.
MID = "The state water board met on Monday and then Katie Hobbs said the wells would be closed for good."


class Base(unittest.TestCase):
    def setUp(self):
        # The default GoMotion rhythm: no piece under 2.5 s.
        for key, value in (("MIN_SCENE_SECONDS", 5.0), ("TARGET_SCENE_SECONDS", 7.0),
                           ("MAX_SCENE_SECONDS", 9.0)):
            p = mock.patch.object(config, key, value)
            p.start()
            self.addCleanup(p.stop)
        on = mock.patch.object(config, "MENTION_CUTS", True)
        on.start()
        self.addCleanup(on.stop)


class SplitRules(Base):
    def test_the_beat_is_cut_on_the_first_word_of_the_name(self):
        seg = timed(MID)
        original = copy.deepcopy(seg)
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(len(out), 2)
        head, tail = out
        self.assertEqual(head.text, "The state water board met on Monday and then")
        self.assertEqual(tail.text, "Katie Hobbs said the wells would be closed for good.")
        # The cut is the moment "Katie" starts: head ends and tail starts there.
        self.assertEqual(tail.start, seg.words[9].start)
        self.assertEqual(head.end, tail.start)
        self.assertEqual((head.start, tail.end), (seg.start, seg.end))
        self.assertEqual(head.words + tail.words, seg.words)
        self.assertEqual(tail.words[0].text, "Katie")
        self.assertEqual(focus, {1: {"subject": "Katie Hobbs", "subjectType": "person",
                                     "role": "Governor of Arizona", "aliases": ["the governor", "hobbs"],
                                     "said": 0.0, "via": "cut"}})
        self.assertEqual(seg, original)                  # the input beat is untouched

    def test_split_at_mentions_returns_the_beats(self):
        out = mentions.split_at_mentions([timed(MID)], news_brief())
        self.assertEqual([s.text[:5] for s in out], ["The s", "Katie"])

    def test_the_cut_takes_the_title_and_its_place_with_the_name(self):
        out = mentions.split_at_mentions([timed(
            "The state water board met on Monday and then Governor Katie Hobbs said the wells would close.")],
            news_brief())
        self.assertTrue(out[1].text.startswith("Governor Katie Hobbs"), out[1].text)
        self.assertEqual(out[1].start, 4.5)
        out = mentions.split_at_mentions([timed(
            "The water board met on Monday before Arizona Governor Katie Hobbs said the wells would close for good.")],
            news_brief(places=["Arizona"]))
        self.assertTrue(out[1].text.startswith("Arizona Governor Katie Hobbs"), out[1].text)
        found = mentions.find_mentions(timed("Farms in Arizona, Governor Katie Hobbs said, would get help."),
                                       news_brief(places=["Arizona"]))
        # A place in its own clause stays a place mention.
        self.assertEqual([(m.name, m.kind) for m in found], [("Arizona", "place"), ("Katie Hobbs", "person")])

    def test_no_split_when_the_name_opens_the_beat(self):
        seg = timed("Katie Hobbs said on Monday that the state would close the wells for good.")
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], seg)
        self.assertEqual(focus[0]["subject"], "Katie Hobbs")
        self.assertEqual(focus[0]["via"], "opening")

    def test_head_minimum(self):
        # "Katie" at 1.0 s: too early to cut, so the whole beat opens with her.
        seg = timed("On Monday Katie Hobbs said the state would close every well in the basin for good.")
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(len(out), 1)
        self.assertEqual(focus[0]["via"], "opening")
        with mock.patch.object(config, "MIN_SCENE_SECONDS", 1.4):         # half = 0.7 s: min_head rules
            self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 1)
            self.assertEqual(len(mentions.split_at_mentions([seg], news_brief(), min_head=0.8)), 2)

    def test_never_a_piece_under_half_the_minimum_scene(self):
        # "Katie" at 2.0 s: past min_head (1.2 s) but under MIN_SCENE_SECONDS / 2.
        seg = timed("Early on Monday morning Katie Hobbs said the state would close every well in the basin.")
        self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 1)
        with mock.patch.object(config, "MIN_SCENE_SECONDS", 1.4):
            self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 2)
        with mock.patch.object(config, "MIN_SCENE_SECONDS", 10.0):          # half = 5 s
            self.assertEqual(len(mentions.split_at_mentions([timed(MID)], news_brief())), 1)
        # Wherever the name falls, no piece is ever shorter than the floor.
        filler = "the water board met again on a hot and dry day while farmers waited outside in line".split()
        splits = 0
        for k in range(len(filler)):
            text = " ".join(filler[:k] + ["Katie", "Hobbs"] + filler[k:]) + "."
            out = mentions.split_at_mentions([timed(text)], news_brief())
            splits += len(out) - 1
            for s in out:
                self.assertGreaterEqual(s.duration, 2.5 - 1e-6, (k, s.text))
        self.assertGreater(splits, 0)

    def test_tail_minimum(self):
        # "Katie" at 6.0 s of 8.45 s: 2.45 s after it.
        seg = timed("The state water board met on Monday and closed the wells before Katie Hobbs spoke to reporters.")
        self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 1)          # 2.45 < 2.5
        with mock.patch.object(config, "MIN_SCENE_SECONDS", 1.4):
            self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 2)      # 2.45 >= 2.0
            self.assertEqual(len(mentions.split_at_mentions([seg], news_brief(), min_tail=3.0)), 1)
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(focus, {})       # said at 6 s: the beat does not open with her

    def test_aliases_name_the_cast_member(self):
        brief = {"kind": "biography", "people": [], "places": [],
                 "cast": [{"name": "Barack Obama Sr.", "role": "Obama's father",
                           "aliases": ["his father", "he", "him"]}]}
        seg = timed("He was one year old when his father left Hawaii for Harvard in the fall of 1962.")
        out, _, focus = mentions.plan_mentions([seg], brief)
        self.assertEqual(out[1].text, "his father left Hawaii for Harvard in the fall of 1962.")
        self.assertEqual(focus, {1: dict(focus[1], subject="Barack Obama Sr.", via="cut")})
        # "He" is not a usable alias: the opening pronoun names nobody.
        self.assertNotIn(0, focus)

    def test_possessives(self):
        brief = {"kind": "news", "people": ["Greg Abbott"], "places": [], "cast": []}
        for name in ("Abbott's", "Abbott’s", "Greg Abbott's"):
            text = f"Farmers across the valley waited for weeks until {name} office finally answered their letters."
            out = mentions.split_at_mentions([timed(text)], brief)
            self.assertEqual(len(out), 2, name)
            self.assertTrue(out[1].text.startswith(name.split()[0]), out[1].text)

    def test_whole_words_and_capitals(self):
        brief = news_brief()
        def names(text):
            return [m.name for m in mentions.find_mentions(timed(text), brief)]
        self.assertEqual(names("They drove on to Hobbsville before dark."), [])
        self.assertEqual(names("The hobbs were empty."), [])              # a lone surname needs its capital
        self.assertEqual(names("Reporters asked Hobbs about it."), ["Katie Hobbs"])
        self.assertEqual(names("reporters asked katie hobbs about it."), ["Katie Hobbs"])   # a full name: any case
        self.assertEqual(names("REPORTERS ASKED KATIE HOBBS ABOUT IT."), ["Katie Hobbs"])
        self.assertEqual(names("Then the governor spoke."), ["Katie Hobbs"])
        self.assertEqual(names("Sen. Mark Kelly and Hobbs spoke."), ["Katie Hobbs"])

    def test_a_name_inside_a_place_is_not_the_person(self):
        brief = {"kind": "history", "people": ["John Wesley Powell", "Herbert Hoover"], "places": [], "cast": []}
        def names(text):
            return [m.name for m in mentions.find_mentions(timed(text), brief)]
        self.assertEqual(names("Boats crowded the ramps at Lake Powell all summer."), [])
        self.assertEqual(names("Water poured over Hoover Dam that spring."), [])
        self.assertEqual(names("The survey Powell led in 1869 mapped the canyon."), ["John Wesley Powell"])
        self.assertEqual(names("In 1869 Powell's boats set out."), ["John Wesley Powell"])

    def test_a_surname_two_people_share_is_nobody(self):
        brief = {"kind": "biography", "people": ["Barack Obama", "Barack Obama Sr."], "places": [], "cast": []}
        def names(text):
            return [m.name for m in mentions.find_mentions(timed(text), brief)]
        self.assertEqual(names("Years later Obama came back."), [])
        self.assertEqual(names("Years later Barack Obama came back."), ["Barack Obama"])
        self.assertEqual(names("Years later Barack Obama Sr. came back."), ["Barack Obama Sr."])

    def test_middle_initial_and_title_open_the_mention(self):
        brief = {"kind": "history", "people": ["John Kennedy"], "places": [], "cast": []}
        seg = timed("The whole crowd fell silent when President John F. Kennedy stepped up to the podium to speak.")
        out = mentions.split_at_mentions([seg], brief)
        self.assertEqual(out[1].text, "President John F. Kennedy stepped up to the podium to speak.")

    def test_only_one_split_per_beat(self):
        seg = timed("The board met on Monday and then Katie Hobbs said that Doug Burgum had "
                    "rejected the plan outright last week.")
        out = mentions.split_at_mentions([seg], news_brief())
        self.assertEqual(len(out), 2)
        self.assertTrue(out[1].text.startswith("Katie Hobbs said that Doug Burgum"))

    def test_second_person_when_the_first_opens_the_beat(self):
        seg = timed("Katie Hobbs said on Monday that the plan Doug Burgum announced would not survive in court.")
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual([s.text for s in out], ["Katie Hobbs said on Monday that the plan",
                                                "Doug Burgum announced would not survive in court."])
        self.assertEqual((focus[0]["subject"], focus[0]["via"]), ("Katie Hobbs", "opening"))
        self.assertEqual((focus[1]["subject"], focus[1]["via"]), ("Doug Burgum", "cut"))

    def test_the_same_person_again_is_not_a_cut(self):
        seg = timed("Katie Hobbs said on Monday that the plan would fail and Hobbs added that the state would sue.")
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(len(out), 1)
        self.assertEqual(list(focus), [0])

    def test_a_second_place_is_cut_at(self):
        seg = timed("Water released from Lake Mead travels for days before it finally reaches "
                    "Phoenix and the farms around it.")
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(out[1].text, "Phoenix and the farms around it.")
        self.assertEqual(focus, {1: dict(focus[1], subject="Phoenix, Arizona", subjectType="place", via="cut")})

    def test_one_place_or_one_area_is_not_a_cut(self):
        seg = timed("Water levels at Lake Mead fell again this week and the marinas closed their boat ramps early.")
        self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 1)
        seg = timed("Floodwater reached Davenport on Monday and spread across the rest of Iowa "
                    "by Friday night and into the weekend.")
        brief = news_brief(places=["Davenport, Iowa", "Iowa"], people=[], cast=[])
        self.assertEqual(len(mentions.split_at_mentions([seg], brief)), 1)

    def test_people_come_before_places(self):
        seg = timed("Water released from Lake Mead reached Phoenix on Monday before Katie Hobbs said "
                    "the canal would close.")
        out = mentions.split_at_mentions([seg], news_brief())
        self.assertTrue(out[1].text.startswith("Katie Hobbs"), out[1].text)

    def test_beats_without_word_timings_are_left_whole(self):
        seg = Segment(text=MID, start=0.0, end=9.45)
        out, _, focus = mentions.plan_mentions([seg], news_brief())
        self.assertEqual(out, [seg])
        self.assertEqual(focus, {})
        opens = Segment(text="Katie Hobbs said on Monday that the state would close the wells.", start=0.0, end=7.0)
        out, _, focus = mentions.plan_mentions([opens], news_brief())
        self.assertEqual((len(out), focus[0]["subject"]), (1, "Katie Hobbs"))

    def test_script_text_is_split_on_the_words_whisper_heard(self):
        heard = timed(MID.replace("Hobbs", "Hobs"))
        seg = Segment(text=MID, start=heard.start, end=heard.end, words=heard.words)
        out = mentions.split_at_mentions([seg], news_brief())
        self.assertEqual(out[1].text, "Katie Hobbs said the wells would be closed for good.")   # the script's words
        self.assertEqual(out[1].words[1].text, "Hobs")                                        # whisper's timing
        self.assertEqual(out[1].start, 4.5)
        # A script word the narrator skipped does not move the cut.
        seg = Segment(text=MID.replace("Monday", "Monday morning"), start=heard.start, end=heard.end,
                      words=timed(MID).words)
        out = mentions.split_at_mentions([seg], news_brief())
        self.assertEqual((out[1].start, out[1].words[0].text), (4.5, "Katie"))

    def test_other_segment_fields_are_kept(self):
        @dataclasses.dataclass
        class Spoken(Segment):
            speaker: str = "narrator"
        base = timed(MID)
        seg = Spoken(text=base.text, start=base.start, end=base.end, words=base.words, speaker="Ann")
        out = mentions.split_at_mentions([seg], news_brief())
        self.assertEqual([(type(s), s.speaker) for s in out], [(Spoken, "Ann")] * 2)

    def test_a_brief_without_people_or_places_changes_nothing(self):
        segs = [timed(MID)]
        for brief in ({}, None, {"cast": [{"name": "", "aliases": ["the pilot"]}]},
                      {"people": ["Bureau of Reclamation"], "cast": "x"}):
            out, parents, focus = mentions.plan_mentions(segs, brief)
            self.assertEqual((out, parents, focus), (segs, [0], {}))


class TrailingNames(Base):
    NARRATION = ("The wells outside Willcox started to fail in the spring of this year. "
                 "Farmers watched the water table drop by several feet in a matter of weeks, and then "
                 "Governor Katie Hobbs ordered a stop to every new well in the basin. "
                 "The order landed hard on the families who had farmed that valley for generations. "
                 "Many of them had already sold their cattle and fallowed half of their land.")

    def test_a_name_in_the_last_seconds_opens_the_next_beat(self):
        segs = segment_words(words_from(self.NARRATION))
        # The clause segmenter ends a beat on "...Governor Katie Hobbs ordered a stop".
        self.assertTrue(segs[1].text.endswith("Governor Katie Hobbs ordered a stop"))
        out, parents, focus = mentions.plan_mentions(segs, news_brief(places=[]))
        self.assertEqual([s.text for s in out], [
            segs[0].text,
            "Farmers watched the water table drop by several feet in a matter of weeks, and then",
            "Governor Katie Hobbs ordered a stop to every new well in the basin.",
            "The order landed hard on the families who had farmed that valley for generations.",
            segs[3].text])
        governor = next(w for w in segs[1].words if w.text == "Governor")
        self.assertEqual((out[1].end, out[2].start), (governor.start, governor.start))
        self.assertEqual(parents, [0, 1, 2, 2, 3])
        self.assertEqual(list(focus), [2])
        self.assertEqual((focus[2]["subject"], focus[2]["via"]), ("Katie Hobbs", "moved"))
        # Every word is still said once, in order, and nothing is shorter than the floor.
        self.assertEqual([w for s in out for w in s.words], [w for s in segs for w in s.words])
        self.assertTrue(all(s.duration >= 2.5 for s in out))

    def test_the_moved_beat_keeps_the_scripts_words(self):
        heard = self.NARRATION.replace("Hobbs", "Hobs").replace("fallowed", "followed")
        segs = align_to_script(segment_words(words_from(heard)), self.NARRATION)
        out = mentions.split_at_mentions(segs, news_brief(places=[]))
        self.assertEqual(out[2].text, "Governor Katie Hobbs ordered a stop to every new well in the basin.")
        self.assertEqual(" ".join(s.text for s in out), " ".join(s.text for s in segs))

    def test_the_last_beat_has_nowhere_to_move_its_name(self):
        seg = timed("The state water board met on Monday and closed the wells before Katie Hobbs spoke to reporters.")
        self.assertEqual(len(mentions.split_at_mentions([seg], news_brief())), 1)

    # "Katie" at 5.5 s of a 6.95 s beat.
    ARRIVES = "The crews worked through the night on the levee and then Katie Hobbs arrived"

    def test_a_long_moved_stretch_is_cut_at_a_clause_end(self):
        nxt = timed("to walk the levee with the crews, and to promise the state would pay for every single "
                    "sandbag used this week.", start=7.0)
        out, _, focus = mentions.plan_mentions([timed(self.ARRIVES), nxt], news_brief())
        self.assertEqual([s.text for s in out], [
            "The crews worked through the night on the levee and then",
            "Katie Hobbs arrived to walk the levee with the crews,",
            "and to promise the state would pay for every single sandbag used this week."])
        self.assertTrue(all(2.5 <= s.duration <= config.MAX_SCENE_SECONDS + 0.6 for s in out))
        self.assertEqual((focus[1]["subject"], focus[1]["via"]), ("Katie Hobbs", "moved"))

    def test_a_name_never_moves_into_a_beat_that_opens_on_one(self):
        segs = [timed(self.ARRIVES), timed("Doug Burgum met her at the levee and promised federal money "
                                           "for every sandbag.", start=7.0)]
        out, _, focus = mentions.plan_mentions(segs, news_brief())
        self.assertEqual(out, segs)
        self.assertEqual({i: f["subject"] for i, f in focus.items()}, {1: "Doug Burgum"})

    def test_a_split_comes_before_a_move(self):
        # Moving "Barack Obama Senior" out first would leave no room to cut at "Ann Dunham".
        brief = {"kind": "biography", "people": [], "places": [], "cast": [
            {"name": "Barack Obama", "role": "", "aliases": []},
            {"name": "Ann Dunham", "role": "Obama's mother", "aliases": []},
            {"name": "Barack Obama Sr.", "role": "Obama's father", "aliases": ["his father"]}]}
        segs = [timed("Barack Obama was born in Honolulu in August nineteen sixty-one, the son of Ann Dunham "
                      "from Kansas and Barack Obama Senior,"),
                timed("a student from Kenya. His parents separated when he was two, and his father returned "
                      "to Africa.", start=10.5)]
        out, parents, focus = mentions.plan_mentions(segs, brief)
        self.assertEqual([s.text for s in out], [
            "Barack Obama was born in Honolulu in August nineteen sixty-one, the son of",
            "Ann Dunham from Kansas and",
            "Barack Obama Senior, a student from Kenya.",
            "His parents separated when he was two, and his father returned to Africa."])
        self.assertEqual(parents, [0, 0, 1, 1])
        self.assertEqual([(focus[i]["subject"], focus[i]["via"]) for i in sorted(focus)],
                         [("Barack Obama", "opening"), ("Ann Dunham", "cut"), ("Barack Obama Sr.", "moved")])


class BriefBeats(Base):
    def test_remap_brief(self):
        brief = {"hookBeats": [0, 1], "sections": [{"from": 0, "to": 1}, {"from": 2, "to": 2}]}
        hooks = brief["hookBeats"]
        mentions.remap_brief(brief, [0, 1, 1, 2])
        self.assertEqual(brief["hookBeats"], [0, 1, 2])
        self.assertIs(brief["hookBeats"], hooks)          # in place: every holder of the brief sees it
        self.assertEqual(brief["sections"], [{"from": 0, "to": 2}, {"from": 3, "to": 3}])

    def test_prepare_moves_the_brief_onto_the_new_beats(self):
        segs = [timed("Water levels at Lake Mead fell again this week and the marinas closed early."),
                timed(MID, start=10.0),
                timed("Farmers in the valley said they had already sold most of their cattle.", start=20.0)]
        brief = news_brief(hookBeats=[0, 1], sections=[{"from": 0, "to": 1, "footage": ["a"]},
                                                       {"from": 2, "to": 2, "footage": ["b"]}])
        out, focus = mentions.prepare(segs, brief)
        self.assertEqual(len(out), 4)
        self.assertEqual(brief["hookBeats"], [0, 1, 2])
        self.assertEqual([(s["from"], s["to"]) for s in brief["sections"]], [(0, 2), (3, 3)])
        self.assertEqual(list(focus), [2])
        self.assertEqual(mentions.LAST_STATS["person_cuts"], 1)

    def test_the_switch_turns_it_off(self):
        segs = [timed(MID)]
        brief = news_brief(hookBeats=[0])
        # config.MENTION_CUTS (per job via CONFIG_OVERRIDABLE, or the environment at start)
        with mock.patch.object(config, "MENTION_CUTS", False):
            self.assertEqual(mentions.prepare(segs, brief), (segs, {}))
        self.assertEqual(brief["hookBeats"], [0])

    def test_prepare_never_raises(self):
        segs = [timed(MID)]
        with mock.patch.object(mentions, "plan_mentions", side_effect=RuntimeError("boom")):
            self.assertEqual(mentions.prepare(segs, news_brief()), (segs, {}))


def _shot(subject, stype="place", vtype="footage", query="q", **kw):
    return {"subject": subject, "subjectType": stype, "visualType": vtype, "query": query,
            "intent": f"{subject} footage", "fallbacks": [], "overlay": None, **kw}


class ApplyFocus(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(config, "NEWS_FOOTAGE", True)
        p.start()
        self.addCleanup(p.stop)
        self.brief = news_brief()
        self.segs, self.focus = mentions.prepare([timed(MID)], self.brief)

    def test_the_beat_that_opens_with_a_name_shows_that_person(self):
        shots = [_shot("Arizona water board"),
                 _shot("Willcox basin wells", "object", query="Willcox basin groundwater wells aerial 2026",
                       entity="object", anchor=False)]
        self.assertEqual(mentions.apply_focus(shots, self.segs, self.focus, self.brief), 1)
        shot = shots[1]
        self.assertEqual((shot["subject"], shot["subjectType"]), ("Katie Hobbs", "person"))
        # A news story: their interview on the story's topic, as the director asks for a person.
        self.assertEqual(shot["query"], "Katie Hobbs interview Arizona groundwater cuts")
        self.assertIn("Katie Hobbs (Governor of Arizona)", shot["intent"])
        self.assertEqual(shot["sceneIntent"]["entities"], ["Katie Hobbs"])
        self.assertTrue(shot["fallbacks"])
        self.assertTrue(all("Hobbs" in q for q in shot["fallbacks"]), shot["fallbacks"])
        self.assertEqual(shot["fallbacks"][-1], "Katie Hobbs")
        self.assertIn("Katie Hobbs Willcox basin groundwater wells aerial 2026", shot["fallbacks"])
        self.assertTrue(shot["newsQueries"])
        self.assertEqual(shot["mention"], {"name": "Katie Hobbs", "type": "person", "via": "cut",
                                           "was": "Willcox basin wells"})
        self.assertEqual(shots[0]["subject"], "Arizona water board")      # not in focus: untouched

    def test_a_still_searches_their_photograph(self):
        brief = {"kind": "biography", "year": 1971, "people": [], "places": [],
                 "cast": [{"name": "Barack Obama Sr.", "role": "Obama's father", "aliases": ["his father"]}],
                 "sections": [{"from": 0, "to": 5, "when": "1962", "where": "Honolulu", "footage": ["x"]}]}
        segs, focus = mentions.prepare(
            [timed("He was one year old when his father left Hawaii for Harvard in the fall of 1962.")], brief)
        shots = [_shot("Honolulu"), _shot("Harvard Yard", vtype="image")]
        mentions.apply_focus(shots, segs, focus, brief)
        self.assertEqual(shots[1]["query"], "Barack Obama Sr. 1962 archival photo")
        self.assertEqual(shots[1]["visualType"], "image")
        self.assertIn("1962", shots[1]["intent"])
        self.assertEqual(shots[1]["sceneIntent"]["specificity"], "generic")
        self.assertEqual(shots[1]["sceneIntent"]["locations"], [])

    def test_a_shot_already_about_them_is_kept(self):
        shots = [_shot("Arizona water board"), _shot("Governor Katie Hobbs", "person", query="Hobbs press")]
        before = copy.deepcopy(shots)
        self.assertEqual(mentions.apply_focus(shots, self.segs, self.focus, self.brief), 0)
        self.assertEqual(shots, before)
        shots = [_shot("Arizona water board"), _shot("Hobbs", "", query="Hobbs signing")]
        self.assertEqual(mentions.apply_focus(shots, self.segs, self.focus, self.brief), 1)
        self.assertEqual((shots[1]["subjectType"], shots[1]["query"]), ("person", "Hobbs signing"))

    def test_a_caption_naming_someone_else_moves_to_them(self):
        tag = {"type": "lower-third", "text": "Doug Burgum", "subtitle": "Interior Secretary"}
        shots = [_shot("Arizona water board"), _shot("Burgum letter", "document", overlay=dict(tag)),
                 _shot("Doug Burgum", "person")]
        mentions.apply_focus(shots, self.segs, self.focus, self.brief)
        self.assertIsNone(shots[1]["overlay"])                  # never his name over her face
        self.assertEqual(shots[2]["overlay"], tag)             # his introduction, on his own beat

    def test_a_place_cut_shows_the_place(self):
        brief = news_brief()
        segs, focus = mentions.prepare([timed(
            "Water released from Lake Mead travels for days before it finally reaches Phoenix and the farms "
            "around it.")], brief)
        shots = [_shot("Lake Mead"), _shot("Central Arizona Project canal", query="CAP canal aerial")]
        self.assertEqual(mentions.apply_focus(shots, segs, focus, brief), 1)
        self.assertEqual((shots[1]["subject"], shots[1]["subjectType"]), ("Phoenix, Arizona", "place"))
        self.assertEqual(shots[1]["query"], "Phoenix Arizona aerial footage 2026")
        self.assertIn("Phoenix CAP canal aerial", shots[1]["fallbacks"])
        self.assertEqual(shots[1]["sceneIntent"]["entities"], ["Phoenix, Arizona"])
        shots = [_shot("Lake Mead"), _shot("Phoenix")]
        self.assertEqual(mentions.apply_focus(shots, segs, focus, brief), 0)

    def test_a_failure_keeps_the_directors_shot(self):
        shots = [_shot("Arizona water board"), _shot("Willcox basin wells", "object")]
        before = copy.deepcopy(shots)
        with mock.patch.object(director, "prefer_interviews", side_effect=RuntimeError("boom")):
            self.assertEqual(mentions.apply_focus(shots, self.segs, self.focus, self.brief), 0)
        self.assertEqual(shots, before)

    def test_focus_past_the_shots_is_ignored(self):
        self.assertEqual(mentions.apply_focus([_shot("x")], self.segs, {5: self.focus[1]}, self.brief), 0)
        self.assertEqual(mentions.apply_focus([], [], {}, None), 0)


class EndToEnd(Base):
    """Narration -> beats -> prepare -> the rule planner -> apply_focus -> timeline cut frames."""

    def setUp(self):
        super().setUp()
        saved = dict(director.LAST_STORY)
        self.addCleanup(lambda: (director.LAST_STORY.clear(), director.LAST_STORY.update(saved)))

    def test_the_cut_lands_on_the_name_and_the_shot_is_the_person(self):
        narration = ("Crews at Lake Mead measured the water again on Monday. The reading was the lowest since the "
                     "reservoir was filled, and within hours of the reading being published Governor Katie Hobbs "
                     "called the numbers a warning for every city in the state. Farmers across the valley said "
                     "they had already cut their planting in half this spring.")
        words = words_from(narration)
        segs = segment_words(words)
        # The clause segmenter puts her name 3.2 s into a 8.9 s beat.
        self.assertIn("published Governor Katie Hobbs called", segs[1].text)
        brief = news_brief(places=["Lake Mead"], hookBeats=[0], sections=[])
        out, focus = mentions.prepare(segs, brief)
        self.assertEqual(len(out), len(segs) + 1)
        governor = next(w for w in words if w.text == "Governor")
        i = next(k for k, s in enumerate(out) if s.text.startswith("Governor Katie Hobbs"))
        self.assertEqual(out[i].start, governor.start)
        self.assertEqual(focus[i]["subject"], "Katie Hobbs")
        with mock.patch.object(director, "is_configured", return_value=False):
            shots, _, _ = director.plan(out, title="Lake Mead", allow_maps=False, brief=brief)
        # Whatever the planner chose for that beat, it now shows her.
        shots[i].update(subject="Lake Mead", subjectType="place", query="Lake Mead low water aerial")
        mentions.apply_focus(shots, out, focus, brief)
        self.assertEqual((shots[i]["subject"], shots[i]["subjectType"]), ("Katie Hobbs", "person"))
        self.assertTrue(shots[i]["query"].startswith("Katie Hobbs"))
        # The render cuts on the frame the name starts.
        fps = 30
        bounds = timeline._scene_bounds(out, fps, int(round(out[-1].end * fps)) + 1)
        self.assertEqual(bounds[i], int(round(governor.start * fps)))


if __name__ == "__main__":
    unittest.main()
