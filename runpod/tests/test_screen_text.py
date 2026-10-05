"""
The words on screen and how long the graphics stay (the owner, 2026-10-05: "sometimes it's saying
some random words ... sometimes the text is super long"; "maps, document animations only stay a
short time and then skip").

  - src/screentext.py: every text, caption, document and list look shows the narration's own words -
    a name, a figure with its unit, a date, a key phrase of two to six words - never a filler word, a
    fragment or a long line (cases are real overlays from the Glen Canyon and Yellowstone timelines);
  - src/treatments.py: each kind of look keeps its least time on screen (FAMILY_LEAST, a text or
    number look LANDED_HOLD after it lands) and is never cut short by the next graphic - it is left
    out instead, and an optional look never runs into a must-show date or figure still to come.
"""
import json
import os
import unittest

from src import gapfill, screentext as st, templates, timeline, treatments
from src.transcribe import Segment, Word

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30


def real_timeline():
    """The Glen Canyon test video's lines, word timings, media kinds and shot subjects."""
    with open(os.path.join(HERE, "fixtures", "timeline_glen_canyon.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    segs, scenes, shots = [], [], []
    for s in doc["scenes"]:
        ws = [Word(t, a, b) for t, a, b in s["words"]]
        if not ws:
            continue
        segs.append(Segment(s["text"], ws[0].start, ws[-1].end, ws))
        kind = s["media"] or "video"
        scenes.append({"id": s["id"], "startFrame": s["startFrame"], "durationInFrames": s["durationInFrames"],
                       "media": {"type": kind, "url": f"https://x/{s['id']}.{'jpg' if kind == 'image' else 'mp4'}"},
                       "transition": "none", "motion": "none", "effect": "none"})
        shots.append({"subject": s["subject"], "subjectType": s["subjectType"]})
    return segs, scenes, shots, int(doc["durationInFrames"])


def plan_real():
    segs, scenes, shots, total = real_timeline()
    brief = {"kind": "explainer", "hookBeats": [], "sections": [], "subject": "Lake Powell"}
    return segs, treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, "documentary"),
                                 timeline._OVERLAY_SECONDS)


class Headlines(unittest.TestCase):
    """Real overlays, the line they stood on, and what they show now."""

    def test_filler_words_and_fragments_never_stand(self):
        cases = [
            ("biggest", "The biggest snow melt in living memory was pouring down the Colorado River,"),
            ("concrete", "The water was tearing through the concrete lining of the tunnel."),
            ("BLUE WATER THE", "and unable to look at that blue water the same way again."),
            ("THE DANGER HERE ISNT ALWAYS THE", "The danger here isn't always the eruption itself."),
            ("That's", "That's the part that kills."),
            ("isn't", "The supervolcano isn't the real danger."),
            ("symptom", "The swelling is a symptom, not a cause."),
            ("THE POSTCARD", "Start with the postcard."),
        ]
        for text, line in cases:
            self.assertEqual(st.headline(text, line), "", (text, line))

    def test_names_figures_and_key_phrases_stand_as_said(self):
        cases = [
            ("Snake River", "It followed the Snake River plain east.", "Snake River"),
            ("MUSIC TEMPLE", "so beautifully that he named it Music Temple.", "MUSIC TEMPLE"),
            ("Bolted on extra height", "They went up onto the gates and bolted on extra height.", "Bolted on extra height"),
            ("not overdue", "Yellowstone is not overdue.", "Not overdue"),
            ("Without any warning", "It could happen without any warning at all.", "Without any warning"),
            (". The super volcano is real", "And the headlines say it plainly. The super volcano is real.",
             "The super volcano is real"),
        ]
        for text, line, want in cases:
            self.assertEqual(st.headline(text, line), want, (text, line))

    def test_a_long_line_is_cut_to_its_key_phrase_or_left_out(self):
        self.assertEqual(st.headline("AROUND IT. HORSES CAME TO DRINK", "A water hole with grass around it. "
                                     "Horses came to drink."), "HORSES CAME TO DRINK")
        self.assertEqual(st.headline("OR MONTHS OR YEARS OF WARNING SIGNS",
                                     "It could come with weeks or months or years of warning signs."),
                         "MONTHS OR YEARS OF WARNING SIGNS")
        line = "It threw out something like 2,450 cubic kilometers of rock and ash."
        self.assertEqual(st.sentence(line, line), "2,450 cubic kilometers")
        for text in ("BLUE WATER THE SAME WAY AGAIN AND AGAIN", "LAKE POWELL LOW WATER EXPOSING PREVIOUSLY SUBMERGED"):
            got = st.headline(text, "Lake Powell low water exposing previously submerged terrain is everywhere, "
                                    "blue water the same way again and again.")
            self.assertLessEqual(len(got), st.HEAD_CHARS, got)
            self.assertLessEqual(len(st.tokens(got)), st.HEAD_WORDS, got)

    def test_a_typed_line_is_a_whole_clause(self):
        self.assertEqual(st.sentence("When is the next one?", "So when is the next one?"), "When is the next one?")
        self.assertEqual(st.sentence("That�s the part that kills", "That’s the part that kills."),
                         "That’s the part that kills")
        self.assertEqual(st.sentence("The last lava flow at Yellowstone was around 70,000 years ago",
                                     "The last lava flow at Yellowstone was around 70,000 years ago."),
                         "The last lava flow at Yellowstone was around 70,000 years ago")
        # it stopped mid-thought: only the key phrase may stand, never the fragment
        got = st.sentence("And the calm reassurances both tend to skip",
                          "And the calm reassurances both tend to skip the part that matters.")
        self.assertNotIn("skip", got.lower())

    def test_typing_artefacts_are_repaired(self):
        self.assertEqual(st.repair("Thatâ€™s it"), "That’s it")
        self.assertEqual(st.repair(". The super volcano"), "The super volcano")
        ovs = [{"text": "That�s the part", "label": "  , HEADLINE"}]
        self.assertEqual(st.audit(ovs), 2)
        self.assertEqual((ovs[0]["text"], ovs[0]["label"]), ("That’s the part", "HEADLINE"))


class PhotoCaptions(unittest.TestCase):
    def test_the_caption_is_the_name_the_line_says_never_the_search_subject(self):
        cases = [
            ("Lake Powell (postcard view)", "If you've seen a photo of Lake Powell, you know the look.", "Lake Powell"),
            ("Yellowstone Caldera (northwest Wyoming)", "This is Yellowstone. Under it sits a volcano.", "Yellowstone"),
            ("Bureau of Reclamation Lake Powell data and satellite imagery",
             "the bureau of reclamation data, the satellite images and the stories", "Bureau of Reclamation"),
            ("LAKE POWELL TOURISM PHOTOGRAPHY",
             "It's one of the most photographed lakes in America, and for millions of people", ""),
            ("Lake Powell low water exposing previously submerged terrain",
             "The thing that's been hidden isn't sitting on the bottom of the lake.", ""),
        ]
        for subject, line, want in cases:
            self.assertEqual(st.photo_caption(subject, line), want, subject)

    def test_list_rows_the_narration_never_said_take_the_look_out(self):
        self.assertIsNone(st.items([{"label": "Boat ramps closed"}, {"label": "Hydropower at risk"}],
                                   "A water hole with grass around it. Horses came to drink."))
        rows = st.items([{"label": "SOLID ROCK = FAST"}, {"label": "MOLTEN ROCK = SLOW"}],
                        "Waves move fast through solid rock and slow through molten rock.")
        self.assertEqual(len(rows), 2)
        self.assertEqual(st.items([{"label": "2022", "value": 3}, {"label": "2023", "value": 4}], "nothing"),
                         [{"label": "2022", "value": 3}, {"label": "2023", "value": 4}])

    def test_clean_props_by_kind_of_look(self):
        word_look = templates.get("LIB_ED_WORD_BY_WORD")
        line = "The biggest snow melt in living memory was pouring down the Colorado River,"
        self.assertIsNone(st.clean_props(word_look, "key-phrase", {"text": "biggest"}, line))
        got = st.clean_props(word_look, "key-phrase", {"text": "COLORADO RIVER", "_key": "Colorado"}, line)
        self.assertEqual(got["text"], "COLORADO RIVER")
        photo = templates.get("LIB_PE_PUNCH_IN")
        got = st.clean_props(photo, "photo", {"text": "LAKE POWELL (POSTCARD VIEW)"},
                             "If you've seen a photo of Lake Powell, you know the look.")
        self.assertEqual(got["text"], "LAKE POWELL")
        got = st.clean_props(photo, "photo", {"text": "LAKE POWELL TOURISM PHOTOGRAPHY"}, "It's one of America's lakes.")
        self.assertNotIn("text", got)
        # a figure's words are its own: never touched here
        count = templates.get("LIB_BT_COUNT")
        self.assertEqual(st.clean_props(count, "big-number", {"value": 12, "text": "YEARS"}, "12 years later")["text"],
                         "YEARS")


class Warnings(unittest.TestCase):
    def test_a_warning_label_is_the_alarm_words_phrase(self):
        cases = [("Officials issued an emergency warning for every marina on the lake.", "EMERGENCY WARNING"),
                 ("Evacuation orders were issued for three counties.", "EVACUATION ORDERS"),
                 ("The lake is nearing dead pool.", "DEAD POOL"),
                 ("A flash flood warning is in effect.", "FLASH FLOOD WARNING"),
                 ("Warning: the river will crest tonight.", "THE RIVER WILL CREST TONIGHT"),
                 ("The danger here isn't always the eruption itself.", "")]
        for line, want in cases:
            self.assertEqual(treatments._warn_phrase(line, treatments._WARN.search(line)), want, line)

    def test_a_term_is_kept_as_said(self):
        cues = treatments._text_cues("Officials call it a once in a lifetime flood event.", None, {}, set())
        term = next(c for c in cues if c["cue"] == "term")
        self.assertEqual(term["props"]["text"].lower(), "once in a lifetime")


class RealPlan(unittest.TestCase):
    """The real planner on the real Glen Canyon narration (no director hints, offline)."""

    @classmethod
    def setUpClass(cls):
        cls.segs, cls.out = plan_real()
        cls.words = sorted((w.start, w.end, w.text) for s in cls.segs for w in s.words)

    def test_every_word_on_screen_is_said_near_its_graphic_and_short(self):
        ovs = self.out["overlays"]
        self.assertGreaterEqual(len(ovs), 10)
        for o in ovs:
            t = templates.get(o.get("template") or "") or {}
            a = o["startFrame"] / FPS
            near = " ".join(w for s, e, w in self.words if e > a - 3 and s < a + o["durationInFrames"] / FPS + 1)
            v = o.get("text")
            if not isinstance(v, str) or not v.strip() or t.get("category") in ("NUMBERS", "TIMELINES"):
                continue
            self.assertGreaterEqual(st.said_share(v, near), 0.99, (o["template"], v, near[:120]))
            words = len(st.tokens(v))
            limit = st.SENTENCE_WORDS if templates.types(t) or t.get("category") == "QUOTES" else st.HEAD_WORDS
            self.assertLessEqual(words, limit, (o["template"], v))

    def test_no_photo_caption_is_a_search_subject(self):
        for o in self.out["overlays"]:
            t = templates.get(o.get("template") or "") or {}
            if t.get("category") == "IMAGES" and o.get("text"):
                self.assertLessEqual(len(o["text"]), st.CAPTION_CHARS, o)
                self.assertNotIn("(", o["text"])

    def test_each_look_keeps_its_time_and_none_overlap(self):
        ovs = sorted(self.out["overlays"], key=lambda o: o["startFrame"])
        for o in ovs:
            t = templates.get(o.get("template") or "") or {}
            least = treatments.animation_seconds(t)
            self.assertGreaterEqual(o["durationInFrames"] / FPS, least - treatments.SHORT_BY - 1 / FPS,
                                    (o["template"], treatments.look_family(t)))
            fam = treatments.look_family(t)
            if fam in treatments.FAMILY_LEAST:
                self.assertGreaterEqual(o["durationInFrames"] / FPS, treatments.FAMILY_LEAST[fam] - 1 / FPS, o)
        for a, b in zip(ovs, ovs[1:]):
            self.assertLessEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"], (a["template"], b["template"]))


class LeastTimes(unittest.TestCase):
    def test_families(self):
        fam = lambda tid: treatments.look_family(templates.get(tid))
        self.assertEqual(fam("LIB_PE_PUNCH_IN"), "photo")
        self.assertEqual(fam("DOC_PAPER_V1"), "document")
        self.assertEqual(fam("MAP_LOCATION_PULSE_V1"), "map")
        self.assertEqual(fam("LIB_BT_COUNT"), "number")
        self.assertEqual(fam("LIB_ED_WORD_BY_WORD"), "text")
        self.assertEqual(fam("LIB_VR_DATE_HERO"), "date")

    def test_least_seconds_by_family(self):
        for tid in ("LIB_PE_PUNCH_IN", "DOC_PAPER_V1", "MAP_LOCATION_PULSE_V1"):
            self.assertGreaterEqual(treatments.animation_seconds(templates.get(tid)), 4.5, tid)
        for t in templates.all_templates():
            fam = treatments.look_family(t)
            least = treatments.animation_seconds(t)
            if fam in treatments.FAMILY_LEAST:
                self.assertGreaterEqual(least, treatments.FAMILY_LEAST[fam], t["id"])
            elif fam in treatments.LANDED_FAMILIES:
                at = (t.get("defaults") or {}).get("sfxAt")
                hit = float(at if at is not None else treatments.ENTRANCE_FRAMES)
                self.assertGreaterEqual(least + 1e-9, hit / 30 + treatments.LANDED_HOLD, t["id"])

    def test_no_room_means_no_look_never_a_cut_one(self):
        # A photo look before a clear figure said 2 s later: the figure lands on its word and the photo
        # look is not cut short under its least time (it is left out, or ends before the figure).
        segs = [Segment("Lake Powell sits behind Glen Canyon Dam.", 0.0, 2.0,
                        [Word("Lake", 0.0, 0.3), Word("Powell", 0.3, 0.7), Word("sits", 0.7, 1.0),
                         Word("behind", 1.0, 1.3), Word("Glen", 1.3, 1.5), Word("Canyon", 1.5, 1.8),
                         Word("Dam.", 1.8, 2.0)]),
                Segment("It holds 24 million acre-feet of water.", 2.0, 6.0,
                        [Word("It", 2.0, 2.2), Word("holds", 2.2, 2.6), Word("24", 2.6, 3.0),
                         Word("million", 3.0, 3.4), Word("acre-feet", 3.4, 4.0), Word("of", 4.0, 4.2),
                         Word("water.", 4.2, 6.0)]),
                Segment("Plain words about the water here and the town.", 6.0, 12.0,
                        [Word("Plain", 6.0, 6.5), Word("words", 6.5, 7.0), Word("town.", 7.0, 12.0)])]
        scenes = [{"id": f"s{i}", "startFrame": int(s.start * FPS), "durationInFrames": int((s.end - s.start) * FPS),
                   "media": {"type": "image" if i == 0 else "video", "url": f"https://x/{i}.jpg"},
                   "transition": "none"} for i, s in enumerate(segs)]
        shots = [{"subject": "Lake Powell", "subjectType": "place"}, {"subject": "x"}, {"subject": "x"}]
        brief = {"kind": "explainer", "hookBeats": [], "sections": []}
        out = treatments.plan(segs, shots, scenes, FPS, 360, brief, treatments.pack_for(brief), timeline._OVERLAY_SECONDS)
        figs = [o for o in out["overlays"] if o.get("value") == 24.0]
        self.assertTrue(figs, out["overlays"])
        for o in out["overlays"]:
            t = templates.get(o.get("template") or "") or {}
            self.assertGreaterEqual(o["durationInFrames"] / FPS, treatments.animation_seconds(t) - 0.05, o["template"])
            if o is not figs[0]:
                self.assertLessEqual(o["startFrame"] + o["durationInFrames"], figs[0]["startFrame"] + 1, o["template"])


class TextCards(unittest.TestCase):
    def test_a_lines_card_is_laid_once(self):
        doc = {"overlays": []}
        s = {"text": "The line with no clip.", "startFrame": 30, "durationInFrames": 90}
        gapfill._card(doc, dict(s))
        gapfill._card(doc, dict(s))
        self.assertEqual(len(doc["overlays"]), 1)
        two = {"overlays": [{"type": "highlight", "text": "x", "startFrame": 1, "durationInFrames": 9}] * 2,
               "durationInFrames": 300}
        timeline.drop_invalid_overlays(two)
        self.assertEqual(len(two["overlays"]), 1)


if __name__ == "__main__":
    unittest.main()
