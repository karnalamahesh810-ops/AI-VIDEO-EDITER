"""The director's graphic proposals: dates win their beat, no retired looks,
varied text, cast roles, honest banners."""
import unittest

from src import director
from src.transcribe import Segment


def seg(text, start, end):
    return Segment(text=text, start=start, end=end)


class OpeningTitle(unittest.TestCase):
    def test_the_title_hint_is_never_cut_mid_word(self):
        title = "Lake Mead Is Running Dry And The Southwest Has No Plan For What Comes Next After The Deadline Passes"
        shot = director._rule_shot(seg("The water is going.", 0, 3), 0, title)
        text = shot["overlay"]["text"]
        self.assertEqual(shot["overlay"]["type"], "chapter")
        self.assertLessEqual(len(text), 90)
        self.assertTrue(title.startswith(text))
        self.assertEqual(title[len(text)], " ")            # cut at a word boundary

    def test_an_opening_date_line_leaves_the_beat_to_the_date_card(self):
        for line in ("On September 25, 2026, the reservoir hit a record low.",
                     "Sept. 25 was the day the gauges went quiet.",
                     "At 3:45 pm the dam operators opened the gates."):
            shot = director._rule_shot(seg(line, 0.4, 4), 0, "Lake Mead Crisis")
            self.assertIsNone(shot["overlay"], line)

    def test_text_hints_step_aside_on_any_date_line(self):
        segs = [seg("It began in March 2026, quietly.", 0, 4), seg("Nobody noticed.", 10, 12),
                seg("By July 4th the lake had dropped.", 20, 24)]
        shots = [{"overlay": {"type": "chapter", "text": "It began"}},
                 {"overlay": {"type": "callout", "text": "Nobody noticed"}},
                 {"overlay": {"type": "map", "places": ["Lake Mead"]}}]
        self.assertEqual(director.yield_to_dates(segs, shots), 1)
        self.assertIsNone(shots[0]["overlay"])
        self.assertEqual(shots[1]["overlay"]["type"], "callout")
        self.assertEqual(shots[2]["overlay"]["type"], "map")   # a map is not a text hint

    def test_cut_words(self):
        self.assertEqual(director._cut_words("alpha beta gamma", 11), "alpha beta")
        self.assertEqual(director._cut_words("alpha beta gamma", 40), "alpha beta gamma")
        self.assertEqual(director._cut_words("alpha, beta gamma", 8), "alpha")
        self.assertEqual(director._cut_words("", 5), "")
        self.assertEqual(director._cut_words(None, 5), "")


class Typewriter(unittest.TestCase):
    def test_questions_still_type(self):
        shot = director._rule_shot(seg("So where did all of the water actually go?", 30, 33), 3, "")
        self.assertEqual(shot["overlay"]["type"], "typewriter")

    def test_short_dramatic_statements_type_now_and_then(self):
        lines = ["The river was simply gone.", "Then the town went silent.", "Nothing was left.",
                 "The last boat left the marina.", "Every well was dry."]
        segs = [seg("Opening line about the lake and its long history.", 0, 4)] + \
               [seg(t, 60.0 * (i + 1), 60.0 * (i + 1) + 3) for i, t in enumerate(lines)]
        shots = [{"overlay": None} for _ in segs]
        added = director.dramatic_typewriters(segs, shots)
        typed = [i for i, s in enumerate(shots) if (s["overlay"] or {}).get("type") == "typewriter"]
        self.assertEqual(added, 3)                     # every other one, not every one
        self.assertEqual(typed, [1, 3, 5])

    def test_statements_are_spaced_and_never_long_or_numeric(self):
        segs = [seg("Opening.", 0, 2), seg("The river was simply gone.", 5, 8),
                seg("Nothing was left at all.", 9, 11), seg("Then it was gone.", 20, 22),
                seg("Over 40 homes were lost.", 90, 93),
                seg("It never came back to the valley where the old families had lived for generations.", 150, 158)]
        shots = [{"overlay": None} for _ in segs]
        director.dramatic_typewriters(segs, shots)
        typed = [i for i, s in enumerate(shots) if s["overlay"]]
        self.assertEqual(typed, [1])                   # #3 is inside the gap, #4 has a figure, #5 is long

    def test_a_line_with_a_graphic_keeps_it(self):
        segs = [seg("Opening.", 0, 2), seg("The river was simply gone.", 60, 63)]
        shots = [{"overlay": None}, {"overlay": {"type": "map", "places": ["X"]}}]
        self.assertEqual(director.dramatic_typewriters(segs, shots), 0)


class CastRoles(unittest.TestCase):
    FALLBACK = {"kind": "other", "summary": "", "event": "", "year": None, "recent": False,
                "places": [], "people": [], "hookBeats": [0], "cast": [], "sections": []}

    def test_a_cast_member_keeps_a_short_role(self):
        raw = {"cast": [{"name": "Katie Hobbs", "role": "Governor of Arizona", "aliases": ["the governor"]},
                        {"name": "John Fleck", "role": "Director of the University of New Mexico Water "
                                                        "Resources Program and author", "aliases": []},
                        {"name": "Ann", "role": 42, "aliases": []},
                        {"name": "", "role": "a stranger", "aliases": ["the man"]}]}
        out = director._validate_brief(raw, dict(self.FALLBACK), 5)
        roles = [c["role"] for c in out["cast"]]
        self.assertEqual(roles[0], "Governor of Arizona")
        self.assertLessEqual(len(roles[1]), director.CAST_ROLE_MAX)
        self.assertTrue("Director of the University of New Mexico".startswith(roles[1]) or
                        roles[1].startswith("Director of the University"))
        self.assertEqual(roles[2], "")                 # not a string
        self.assertEqual(roles[3], "")                 # nobody to caption
        self.assertIn("role", director._BRIEF_PROMPT)

    def test_the_lower_third_carries_the_role(self):
        brief = {"cast": [{"name": "Katie Hobbs", "role": "Governor of Arizona", "aliases": []}]}
        segs = [seg("x", 0, 1), seg("y", 10, 11)]
        shots = [{"subject": "Katie Hobbs", "subjectType": "person", "overlay": None},
                 {"subject": "Katie Hobbs", "subjectType": "person", "overlay": None}]
        director.name_people(segs, shots, brief)
        self.assertEqual(shots[0]["overlay"], {"type": "lower-third", "text": "Katie Hobbs",
                                               "subtitle": "Governor of Arizona"})
        self.assertIsNone(shots[1]["overlay"])

    def test_a_person_is_not_named_over_a_date(self):
        segs = [seg("On March 3, 2026, Katie Hobbs signed the order.", 0, 4), seg("She waited.", 10, 12)]
        shots = [{"subject": "Katie Hobbs", "subjectType": "person", "overlay": None},
                 {"subject": "Katie Hobbs", "subjectType": "person", "overlay": None}]
        director.name_people(segs, shots)
        self.assertIsNone(shots[0]["overlay"])
        self.assertEqual(shots[1]["overlay"]["type"], "lower-third")


class Banners(unittest.TestCase):
    def test_a_banner_without_a_variant_is_never_breaking(self):
        ov = director.validate_overlay({"type": "banner", "text": "Water cuts coming"})
        self.assertEqual(ov["variant"], "update")
        kept = director.validate_overlay({"type": "banner", "text": "x", "variant": "alert"})
        self.assertEqual(kept["variant"], "alert")

    def test_breaking_only_in_breaking_news(self):
        def shots():
            return [{"overlay": {"type": "banner", "text": "Dam spillway fails", "variant": "breaking"}},
                    {"overlay": {"type": "banner", "text": "Evacuation warning issued", "variant": "live"}},
                    {"overlay": {"type": "banner", "text": "The compact expires", "variant": "update"}}]
        history = shots()
        director.banner_variants(history, {"kind": "history", "recent": False})
        self.assertEqual([s["overlay"]["variant"] for s in history], ["update", "alert", "update"])
        news = shots()
        director.banner_variants(news, {"kind": "news", "recent": True})
        self.assertEqual([s["overlay"]["variant"] for s in news], ["breaking", "live", "update"])
        old_news = shots()
        director.banner_variants(old_news, {"kind": "news", "recent": False})
        self.assertEqual(old_news[0]["overlay"]["variant"], "update")


class PromptNeutral(unittest.TestCase):
    def test_the_prompt_no_longer_pushes_one_text_look(self):
        p = director._SYSTEM_PROMPT
        self.assertNotIn("gets a sentence-highlight", p)
        for kind in ("callout", "typewriter", "kicker", "date-stamp", "satellite-focus", "satellite-trace"):
            self.assertIn(kind, p)
        self.assertIn("satellite-focus", director.validate_overlay(
            {"type": "map", "places": ["Phoenix"], "variant": "satellite-focus"})["variant"])


if __name__ == "__main__":
    unittest.main()
