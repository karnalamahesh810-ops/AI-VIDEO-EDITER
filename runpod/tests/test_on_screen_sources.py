"""
On-screen sources across every niche (docs/on-screen-sources.md; src/sources.py, treatments._source_tags).

The narration samples below are written for this test (no model call): history, finance, tech, science, true
crime, sports and health, never only water and weather. They check:

  * a tag only for a source the narration NAMES, or for a fact of the script's own research that the line states
    (the same figure, about the same thing) - never a guessed source: a figure with nobody named gets nothing;
  * the research path: the organisation of the fact's own source, its date's year, never a "medium" fact, never a
    web address, a year alone needs more shared words than a figure, one tag per fact;
  * the planner on whole scripts with every other graphic planned: never in the first 5 s (the hook), at most one
    per SOURCE_TAG_GAP (45 s), 3-5 s on screen, never before its word, never while another graphic is up (it lands
    as the fact's own number look leaves, or is left out), always one of the allowed labels;
  * the switches: ON_SCREEN_SOURCES or SOURCE_TAGS turn it on, a job's {"on_screen_sources": false} turns it off.
"""
import unittest
from unittest import mock

from src import config, sources as S, treatments
from tests.test_source_tags import FPS, PLAIN, SECS, _bare, _plan, tags

# (niche, line, the tag it must read) - the source is named by the narration itself.
NAMED = [
    ("history", "According to the National Archives, more than 16 million Americans served in the war.",
     "SOURCE: NATIONAL ARCHIVES"),
    ("history", "A 2019 study published in Nature found the city was abandoned within a decade.",
     "SOURCE: NATURE, 2019"),
    ("history", "Records from the Library of Congress show the map was drawn in 1507.",
     "SOURCE: LIBRARY OF CONGRESS"),
    ("finance", "According to the Federal Reserve, household debt reached 17 trillion dollars.",
     "SOURCE: FEDERAL RESERVE"),
    ("finance", "The SEC said the firm hid 4 billion dollars in losses.", "SOURCE: SEC"),
    ("finance", "A 2023 Goldman Sachs report estimated that 300 million jobs could be exposed.",
     "SOURCE: GOLDMAN SACHS, 2023"),
    ("tech", "According to Gartner, shipments fell 9 percent in the third quarter.", "SOURCE: GARTNER"),
    ("tech", "Data from Counterpoint Research shows the phone sold 20 million units.",
     "SOURCE: COUNTERPOINT RESEARCH"),
    ("tech", "Researchers at Stanford University found the model memorised its training data.",
     "SOURCE: STANFORD UNIVERSITY"),
    ("science", "NASA says the asteroid will pass within 19,000 miles of Earth.", "SOURCE: NASA"),
    ("science", "According to the European Space Agency, the probe travelled 6 billion kilometres.", "SOURCE: ESA"),
    ("science", "A paper in the journal Cell found the protein doubles the cell's lifespan.", "SOURCE: CELL"),
    ("true crime", "According to the FBI, the gang stole 70 million dollars in four years.", "SOURCE: FBI"),
    ("true crime", "The Bureau of Justice Statistics reported that 1 in 3 cases goes unsolved.",
     "SOURCE: BUREAU OF JUSTICE STATISTICS"),
    ("true crime", "As reported by the Associated Press, the jury deliberated for nine days.", "SOURCE: AP"),
    ("sports", "According to ESPN, the contract is worth 700 million dollars.", "SOURCE: ESPN"),
    ("sports", "Guinness World Records confirmed the jump at 8.95 metres.", "SOURCE: GUINNESS WORLD RECORDS"),
    ("sports", "Figures from the NCAA show only 2 percent of players turn professional.", "SOURCE: NCAA"),
    ("health", "According to the CDC, 38 million Americans have diabetes.", "SOURCE: CDC"),
    ("health", "A 2022 study in the New England Journal of Medicine found the drug cut deaths by a third.",
     "SOURCE: NEJM, 2022"),
    ("health", "The World Health Organization estimates that 1.3 billion adults are inactive.", "SOURCE: WHO"),
]

# Facts and figures with nobody named: never a tag, whatever the niche.
UNNAMED = [
    "More than 16 million Americans served in the war.",
    "Experts say the empire fell within a decade.",
    "Household debt reached 17 trillion dollars last year.",
    "Analysts believe the stock could double.",
    "Shipments fell 9 percent in the third quarter.",
    "Studies show screens change how children sleep.",
    "The asteroid will pass within 19,000 miles of Earth.",
    "Scientists say the universe is 13.8 billion years old.",
    "The gang stole 70 million dollars in four years.",
    "According to police, the suspect fled on foot.",
    "Investigators found the car three miles away.",
    "The contract is worth 700 million dollars.",
    "According to fans, it was the greatest game ever played.",
    "Doctors say the drug cut deaths by a third.",
    "38 million Americans have diabetes.",
    "The FBI arrested him at the border in 1998.",           # an agency doing something, not being cited
    "Gartner Smith, a farmer, grew the biggest pumpkin.",    # the word, not the firm
    "The NBA Finals drew 12 million viewers.",               # the league as a subject of the sentence, no attribution
]

# The script's own research (the app's script writer v2 shape): facts and their sources.
RESEARCH = {
    "facts": [
        {"id": "F1", "text": "The Great Fire of London destroyed 13,200 houses in 1666", "number": "13,200",
         "when": "1666", "source": "S1", "confidence": "high"},
        {"id": "F2", "text": "Apple sold 231 million iPhones worldwide in fiscal 2023", "number": "231 million",
         "source": "S2", "confidence": "high"},
        {"id": "F3", "text": "Violent crime in the United States fell 3 percent in 2023", "number": "3%",
         "source": "S3", "confidence": "medium"},                    # the fact check was not sure: never cited
        {"id": "F4", "text": "The marathon world record is 2 hours 35 seconds, set in Chicago", "number": "2:00:35",
         "source": "S4", "confidence": "high"},
        {"id": "F5", "text": "Adults who walk 7,000 steps a day have a 50 percent lower risk of early death",
         "number": "7,000", "source": "S5", "confidence": "high"},
        {"id": "F6", "text": "The Voyager 1 probe launched in 1977 from Cape Canaveral", "when": "1977",
         "source": "S6", "confidence": "high"},
        {"id": "F7", "text": "Bitcoin's supply is capped at 21 million coins", "number": "21 million",
         "source": "S7", "confidence": "high"},                       # its source is a web address: no name
        {"id": "F8", "text": "Global smartphone shipments reached 1.17 billion units", "number": "1.17 billion",
         "source": "U.S. Census Bureau", "confidence": "high"},       # an organisation written on the fact
    ],
    "sources": [
        {"id": "S1", "title": "The Great Fire", "org": "Museum of London", "url": "https://x", "date": "2016-09-02"},
        {"id": "S2", "title": "Annual report", "org": "Apple", "url": "https://x", "date": "2023-11-03"},
        {"id": "S3", "title": "Crime in the U.S.", "org": "Federal Bureau of Investigation", "url": "https://x"},
        {"id": "S4", "title": "Records", "org": "World Athletics", "url": "https://x", "date": "2023"},
        {"id": "S5", "title": "Daily steps and mortality", "org": "The Lancet Public Health", "url": "https://x",
         "date": "2022-03-02"},
        {"id": "S6", "title": "Voyager", "org": "NASA Jet Propulsion Laboratory", "url": "https://x",
         "date": "2099-01-01"},                                       # a date still to come: no year
        {"id": "S7", "title": "Bitcoin FAQ", "org": "bitcoin.org", "url": "https://bitcoin.org"},
    ],
}


class NamedSourcesInEveryNiche(unittest.TestCase):
    def test_a_named_source_reads_as_said_in_every_niche(self):
        niches = set()
        for niche, line, want in NAMED:
            got = S.find(line)
            self.assertIsNotNone(got, line)
            self.assertEqual(S.label(got), want, line)
            # the word it lands on is in the line, where the name is said
            self.assertEqual(line[got["start"]:got["start"] + len(got["key"])], got["key"], line)
            niches.add(niche)
        self.assertGreaterEqual(len(niches), 7)

    def test_nobody_named_no_tag(self):
        for line in UNNAMED:
            self.assertIsNone(S.find(line), line)
            self.assertIsNone(S.match_research(line, []), line)


class TheScriptsResearch(unittest.TestCase):
    def setUp(self):
        self.r = S.research_from(RESEARCH)
        self.facts = self.r["facts"]

    def test_only_sure_facts_with_a_named_source_are_kept(self):
        ids = [f["id"] for f in self.facts]
        self.assertEqual(ids, ["F1", "F2", "F4", "F5", "F6", "F8"])     # F3 medium, F7 a web address
        by = {f["id"]: f for f in self.facts}
        self.assertEqual((by["F1"]["name"], by["F1"]["year"]), ("MUSEUM OF LONDON", 2016))
        self.assertEqual((by["F5"]["name"], by["F5"]["year"]), ("LANCET PUBLIC HEALTH", 2022))
        self.assertEqual((by["F6"]["name"], by["F6"]["year"]), ("NASA JET PROPULSION LABORATORY", None))
        self.assertEqual(by["F8"]["name"], "U.S. CENSUS BUREAU")       # the short form of a known body

    def test_a_line_stating_a_researched_fact_gets_its_source_on_the_figure(self):
        cases = [
            ("The fire tore through the city and destroyed 13,200 houses.", "SOURCE: MUSEUM OF LONDON, 2016", "13,200"),
            ("That year Apple sold 231 million iPhones.", "SOURCE: APPLE, 2023", "231"),
            ("Walk just 7,000 steps a day and your risk of early death drops sharply.",
             "SOURCE: LANCET PUBLIC HEALTH, 2022", "7,000"),
            # rounded as a narration rounds it: 230 million is the 231 million fact
            ("Apple moved about 230 million iPhones that year.", "SOURCE: APPLE, 2023", "230"),
            # a year needs three shared words: probe, launched, Voyager
            ("The Voyager probe launched in 1977 and never came back.", "SOURCE: NASA JET PROPULSION LABORATORY",
             "1977"),
            # said in words
            ("Apple sold two hundred thirty-one million iPhones that year.", "SOURCE: APPLE, 2023", "two"),
        ]
        for line, want, key in cases:
            got = S.match_research(line, self.facts)
            self.assertIsNotNone(got, line)
            self.assertEqual(S.label(got), want, line)
            self.assertEqual(got["key"], key, line)
            self.assertEqual(got["how"], "research")
            self.assertEqual(line[got["start"]:got["start"] + len(key)], key, line)

    def test_never_a_source_for_a_fact_the_line_does_not_state(self):
        for line in [
            "Violent crime fell 3 percent in 2023.",                  # F3 is medium: never cited
            "Bitcoin's supply is capped at 21 million coins.",        # F7's source is only an address
            "The stadium holds 13,200 fans.",                         # the same figure about something else
            "Apple sold 300 million iPhones.",                        # the same thing, another figure
            "In 1977 disco ruled the radio.",                         # a year alone, nothing shared
            "Voyager launched in 1977.",                              # a year with only two shared words
            "The houses burned for days.",                            # the words, no figure
            "",
        ]:
            self.assertIsNone(S.match_research(line, self.facts), line)

    def test_one_tag_per_fact(self):
        line = "The fire destroyed 13,200 houses."
        got = S.match_research(line, self.facts)
        self.assertIsNotNone(got)
        self.assertIsNone(S.match_research(line, self.facts, used={got["id"]}))

    def test_a_named_source_wins_over_the_research(self):
        S.use_research({"research": RESEARCH})
        try:
            lines = [PLAIN] * 6 + ["According to the BBC, the fire destroyed 13,200 houses in four days."] + [PLAIN] * 4
            with mock.patch.object(config, "SOURCE_TAGS", True):
                plan = _bare(lines)
        finally:
            S.use_research(None)
        self.assertEqual([r["text"] for r in plan["sources"]], ["SOURCE: BBC"])

    def test_the_research_never_reaches_the_story_brief(self):
        S.use_research({"research": RESEARCH})
        try:
            self.assertEqual(len(S.research()["facts"]), 6)
        finally:
            S.use_research(None)
        self.assertEqual(S.research(), {"facts": [], "listed": []})
        S.use_research({"script_research": RESEARCH})
        try:
            self.assertEqual(len(S.research()["facts"]), 6)
        finally:
            S.use_research(None)
        for junk in (None, {}, {"research": "text"}, {"research": {"facts": "x", "sources": 3}}):
            self.assertEqual(S.use_research(junk), 0)


# --------------------------------------------------------------------------- whole scripts, every graphic planned
SCRIPTS = {
    "history": [
        "In the summer of 1666, a small bakery fire changed London forever.",
        "Within hours the flames had jumped from street to street.",
        "The fire burned for four days and the city could do nothing.",
        "When it was over, the old city was gone.",
        "According to the Museum of London, the fire destroyed 13,200 houses.",
        "Eighty-seven churches were lost, including old St Paul's.",
        "Yet the official death toll was just six people.",
        "Historians have argued about that number ever since.",
        "The rebuilding took more than fifty years.",
        "A 2019 study published in Nature found that the ash layer was thicker than anyone thought.",
        "And the city that rose from it was made of brick and stone.",
        "Some say that was the fire's only gift.",
        "Records from the National Archives show the king paid for much of it himself.",
        "London would never burn like that again.",
    ],
    "finance": [
        "This is the story of the biggest fraud Wall Street never saw coming.",
        "For years the fund reported smooth, steady returns.",
        "Investors poured in money from all over the world.",
        "Nobody asked how the numbers could be so perfect.",
        "According to the SEC, the fund had lost 4 billion dollars by 2008.",
        "The founder kept paying old investors with new money.",
        "When the market crashed, the money ran out.",
        "He confessed to his sons in December.",
        "The losses touched thousands of families.",
        "A 2010 report by the Government Accountability Office found the warnings had been ignored six times.",
        "Regulators promised it would never happen again.",
        "But the same pattern keeps coming back.",
        "Investors still chase returns that look too good to be true.",
        "And that is exactly what fraudsters count on.",
    ],
    "tech": [
        "One phone changed everything about how we live.",
        "Before it, phones had keyboards and tiny screens.",
        "After it, every company copied the same design.",
        "The first model was slow and expensive.",
        "But people lined up for days to buy one.",
        "According to Counterpoint Research, the phone sold 20 million units in its first year.",
        "Rivals laughed at it at first.",
        "Within five years most of them were gone.",
        "The app store turned it into a computer in every pocket.",
        "Researchers at Stanford University found that people check their phones 96 times a day.",
        "That habit built a trillion dollar industry.",
        "And it started with one keynote.",
        "Today the phone is the center of modern life.",
        "Whether that is good for us is another question.",
    ],
    "true crime": [
        "On a quiet night in 1990, two men walked into a museum dressed as police.",
        "The guards let them in without a second thought.",
        "Eighty-one minutes later, the men walked out with thirteen works of art.",
        "The frames were left hanging empty on the walls.",
        "According to the FBI, the stolen art is worth 500 million dollars.",
        "It remains the largest property theft in history.",
        "The museum still offers a reward for any information.",
        "Detectives followed hundreds of leads over the years.",
        "Every one of them went cold.",
        "As reported by the Associated Press, two suspects died before they could be charged.",
        "The empty frames still hang there today.",
        "Waiting for paintings that may never come home.",
        "Someone out there knows where they are.",
        "And they have kept that secret for over thirty years.",
    ],
    "sports": [
        "He was cut from his high school team.",
        "Coaches said he was too small to make it.",
        "He spent every morning in the gym before school.",
        "By his senior year, nobody could guard him.",
        "Figures from the NCAA show only 2 percent of college players turn professional.",
        "He was one of them.",
        "His rookie season broke three team records.",
        "Fans packed arenas just to watch him warm up.",
        "Then came the injury that nearly ended it all.",
        "According to ESPN, his comeback contract was worth 700 million dollars.",
        "Critics said he would never be the same.",
        "He proved every one of them wrong.",
        "Today his jersey hangs from the rafters.",
        "And kids still practice his moves on playgrounds.",
    ],
    "health": [
        "There is one habit that could add years to your life.",
        "It costs nothing and you can start today.",
        "Most people still ignore it.",
        "It is not a diet and it is not a pill.",
        "According to the CDC, 38 million Americans have diabetes.",
        "Many of them could lower their risk with one simple change.",
        "That change is walking.",
        "Not running, not lifting, just walking.",
        "Doctors have known this for decades.",
        "A 2022 study in the New England Journal of Medicine found daily walkers lived longer.",
        "The benefits start after just a few weeks.",
        "Your heart, your brain and your mood all improve.",
        "So tomorrow, take the stairs.",
        "Your future self will thank you.",
    ],
}


def _allowed(lines):
    """The labels a script may show: a source each line names (find), else none."""
    out = set()
    for i, line in enumerate(lines):
        got = S.find(line, lines[i + 1] if i + 1 < len(lines) else "")
        if got:
            out.add(S.label(got))
    return out


class WholeScripts(unittest.TestCase):
    def _check(self, niche, plan, lines, allowed):
        got = tags(plan)
        starts = sorted(o["startFrame"] / FPS for o in got)
        for o in got:
            label = S.label({"name": o["text"], "year": o.get("subtitle")})
            self.assertIn(label, allowed, (niche, label))                       # never invented
            at, dur = o["startFrame"] / FPS, o["durationInFrames"] / FPS
            self.assertGreaterEqual(at, config.SOURCE_TAG_FIRST_SECONDS, niche)  # never in the hook
            self.assertGreaterEqual(dur, treatments.SOURCE_TAG_LEAST - 0.05, niche)   # 3-5 s on screen
            self.assertLessEqual(dur, 5.0 + 1e-6, niche)
        for a, b in zip(starts, starts[1:]):
            self.assertGreaterEqual(b - a, config.SOURCE_TAG_GAP - 1e-6, niche)  # one per 45 s
        # never with another graphic on screen, a breath between
        spans = sorted((o["startFrame"], o["startFrame"] + o["durationInFrames"]) for o in plan["overlays"])
        for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0, (niche, spans))
        # never before its word: the audit row says when the source (or the figure) was said
        for row, o in zip(plan.get("sources") or [], sorted(got, key=lambda o: o["startFrame"])):
            said = row.get("saidAt")
            if said is not None:
                self.assertGreaterEqual(row["at"], said - 1e-6, niche)
                self.assertLessEqual(row["at"] - said, config.SOURCE_TAG_FOLLOW_SECONDS + 1e-6, niche)
        return got

    def test_every_niche_plans_by_the_rules_with_every_other_graphic(self):
        placed = {}
        for niche, lines in SCRIPTS.items():
            with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
                plan = _plan(lines)
            placed[niche] = len(self._check(niche, plan, lines, _allowed(lines)))
        # the 70 s scripts name two or three sources each: at least one tag lands in every niche, never more than
        # the 45 s spacing allows
        for niche, n in placed.items():
            self.assertGreaterEqual(n, 1, (niche, placed))
            self.assertLessEqual(n, 2, (niche, placed))

    def test_the_rules_on_their_own(self):
        for niche, lines in SCRIPTS.items():
            with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
                plan = _bare(lines)
            got = self._check(niche, plan, lines, _allowed(lines))
            self.assertGreaterEqual(len(got), 1, niche)
            # with the screen free, each lands on the name as it is said
            for row in plan["sources"]:
                self.assertNotIn("afterGraphic", row, niche)

    def test_a_source_named_in_the_hook_is_never_tagged(self):
        lines = ["According to the FBI, the gang stole 70 million dollars.", PLAIN, PLAIN, PLAIN]
        with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
            self.assertEqual(tags(_bare(lines)), [])
            self.assertEqual(tags(_plan(lines)), [])

    def test_a_script_that_names_nobody_gets_no_tag(self):
        lines = [PLAIN] * 2 + UNNAMED
        with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
            self.assertEqual(tags(_plan(lines)), [])
            self.assertEqual(tags(_bare(lines)), [])

    def test_the_research_tags_a_line_that_states_its_fact(self):
        lines = [PLAIN] * 4 + ["The fire tore through the city and destroyed 13,200 houses."] + [PLAIN] * 6
        S.use_research({"research": RESEARCH})
        try:
            with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
                bare = _bare(lines)
                full = _plan(lines)
        finally:
            S.use_research(None)
        got = tags(bare)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["text"], got[0]["subtitle"]), ("MUSEUM OF LONDON", "2016"))
        # in on the figure as it is said ("13,200" is the 8th word of line 4)
        word = 4 * SECS + 7 * 0.3
        self.assertGreaterEqual(got[0]["startFrame"] / FPS, word - treatments.PRE_ROLL_FRAMES / FPS - 1e-6)
        self.assertLess(got[0]["startFrame"] / FPS, word + 0.3)
        self.assertEqual(bare["sources"][0]["how"], "research")
        self.assertIn("13,200 houses", bare["sources"][0]["fact"])
        # with the figure's own number look on screen, the tag follows it - or is left out - never on top of it
        self._check("research", full, lines, {"SOURCE: MUSEUM OF LONDON, 2016"})
        # and without the research the same script has no tag at all
        with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
            self.assertEqual(tags(_bare(lines)), [])


class TheSwitches(unittest.TestCase):
    def test_either_flag_turns_it_on_both_off_by_default(self):
        self.assertFalse(config.ON_SCREEN_SOURCES)
        self.assertFalse(config.SOURCE_TAGS)
        self.assertFalse(S.enabled())
        with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
            self.assertTrue(S.enabled())
        with mock.patch.object(config, "SOURCE_TAGS", True):
            self.assertTrue(S.enabled())
        self.assertEqual(config.SOURCE_TAG_GAP, 45.0)
        self.assertEqual(config.SOURCE_TAG_FIRST_SECONDS, 5.0)
        self.assertTrue(3.0 <= config.SOURCE_TAG_SECONDS <= 5.0)

    def test_flag_off_plans_nothing(self):
        lines = SCRIPTS["finance"]
        self.assertEqual(tags(_plan(lines)), [])

    def test_the_jobs_own_field_wins(self):
        import handler
        self.assertIn("ON_SCREEN_SOURCES", handler.CONFIG_OVERRIDABLE)
        self.assertIn("SOURCE_TAG_FOLLOW_SECONDS", handler.CONFIG_OVERRIDABLE)
        # false: off whatever the job's config says
        inp = {"on_screen_sources": False, "config": {"ON_SCREEN_SOURCES": True, "AUTO_MAPS": True}}
        self.assertIs(S.fold_job_switch(inp), False)
        self.assertEqual(inp["config"], {"ON_SCREEN_SOURCES": False, "SOURCE_TAGS": False, "AUTO_MAPS": True})
        with mock.patch.object(config, "ON_SCREEN_SOURCES", True):
            prev = handler._apply_config(inp["config"])
            try:
                self.assertFalse(S.enabled())
            finally:
                handler._restore_config(prev)
            self.assertTrue(S.enabled())
        # true: on for this job
        inp = {"on_screen_sources": "true"}
        self.assertIs(S.fold_job_switch(inp), True)
        prev = handler._apply_config(inp["config"])
        try:
            self.assertTrue(S.enabled())
        finally:
            handler._restore_config(prev)
        self.assertFalse(S.enabled())
        # no field: the flags decide, the config is left as it was
        inp = {"config": {"X": 1}}
        self.assertIsNone(S.fold_job_switch(inp))
        self.assertEqual(inp, {"config": {"X": 1}})
        self.assertIsNone(S.fold_job_switch({"on_screen_sources": None}))


if __name__ == "__main__":
    unittest.main()
