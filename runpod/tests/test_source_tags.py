"""
On-screen sources (src/sources.py, the src-tag look, config.SOURCE_TAGS): a line that states a fact and NAMES
its source gets "SOURCE: USBR, 2024" in a low corner - and only such a line.

  * detection: attributions name a source ("according to the Bureau of Reclamation", "USGS data shows", "a 2024
    NOAA report found", "researchers at the University of Arizona found", "published in Nature"); "experts say",
    an agency doing something, a person, a compact, a figure with no source do not; the year only when said of
    the source (or given by the brief's own list); "British Geological Survey" is not the USGS;
  * the planner: flag off changes nothing (and a script that names nothing plans the same with it on); a tag
    lands on the name as it is said, about 3 s, never in the first 5 s, one per 30 s, never while another graphic
    is up, never on an animation scene, silent, no treatment of its own, and never changes the other overlays;
  * the look: registered "autoPick": false, silent, drawn by the renderer;
  * settle: a face under the tag's corner moves it to the other corner or leaves it out; a scene that became a
    full-screen graphic loses its tag; faces are read from media.focus or found in the file.
"""
import json
import os
import unittest
from unittest import mock

from src import config, sources as S, templates, timeline, treatments
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS = 30
SECS = 5.0

CITED = [
    ("According to the Bureau of Reclamation, Lake Mead has dropped 170 feet since 2000.", "USBR", None, "Bureau"),
    ("USGS data shows the river has lost 20 percent of its flow.", "USGS", None, "USGS"),
    ("A 2024 NOAA report found that the drought is the worst in 1,200 years.", "NOAA", 2024, "NOAA"),
    ("According to the U.S. Geological Survey, the aquifer is falling.", "USGS", None, "Geological"),
    ("According to data from the U.S. Drought Monitor, 80 percent of the state is dry.", "U.S. DROUGHT MONITOR", None,
     "Drought"),
    ("Researchers at the University of Arizona found that the trees are dying.", "UNIVERSITY OF ARIZONA", None,
     "University"),
    ("The Pacific Institute estimates that 40 million people depend on the river.", "PACIFIC INSTITUTE", None, "Pacific"),
    ("A study published in Nature found the megadrought is the worst in 1,200 years.", "NATURE", None, "Nature"),
    ("A 2021 study by the Scripps Institution of Oceanography put the odds at one in two.",
     "SCRIPPS INSTITUTION OF OCEANOGRAPHY", 2021, "Scripps"),
    ("The National Weather Service said gusts could reach 60 miles per hour.", "NWS", None, "National"),
    ("NOAA's own records show the storm was the strongest since 1935.", "NOAA", None, "NOAA"),
    ("Figures from the Southern Nevada Water Authority show use fell by a quarter.", "SNWA", None, "Southern"),
    ("As reported by Reuters, the deal collapsed.", "REUTERS", None, "Reuters"),
    ("The Bureau of Reclamation projects that the lake will fall another 30 feet.", "USBR", None, "Bureau"),
    ("according to U.S.G.S. data, the flow is down a fifth.", "USGS", None, "U.S.G.S."),
    ("The numbers come from a 2023 report by the Environmental Protection Agency.", "EPA", 2023, "Environmental"),
    ("The Bureau of Reclamation's 24-month study showed the lake at dead pool by 2025.", "USBR", None, "Bureau"),
    ("But the Imperial Irrigation District says it holds the oldest rights on the river.",
     "IMPERIAL IRRIGATION DISTRICT", None, "Imperial"),
    ("According to the British Geological Survey, the quake was a 5.1.", "BRITISH GEOLOGICAL SURVEY", None, "British"),
    ("According to a 2019 study in the journal Geology, the canyon is younger.", "GEOLOGY", 2019, "Geology"),
    ("The New York Times reported that the wells had run dry.", "THE NEW YORK TIMES", None, "New"),
    ("According to NOAA's 2023 outlook, the snowpack will melt early.", "NOAA", 2023, "NOAA"),
]
NOT_CITED = [
    "Lake Mead has dropped 170 feet since 2000.",                       # a figure with no named source
    "The Bureau of Reclamation built Hoover Dam in 1936.",              # an agency doing something
    "According to experts, the lake could be empty by 2030.",           # nobody named
    "Studies show the river is shrinking.",
    "According to officials, the dam is safe.",
    "NASA launched the satellite in 2002.",
    "Bureau of Reclamation projects supply water to 31 million people.",   # "projects" the noun
    "According to the Colorado River Compact, each basin gets 7.5 million acre-feet.",
    "According to John Fleck, the river is overallocated.",             # a person: the person looks' business
    "Who knows what the science will say.",
    "The water is released by the Bureau of Reclamation every spring.",
    "More than 2000 people work at the plant.",
    "Scientists say the snowpack is the lowest on record.",
    "The Biden Administration said it would act.",
    "According to legend, the canyon was carved by a giant.",
    "Nature always finds a way.",                                       # the word, not the journal
    "The Geological Survey office in Denver closed in 2019.",
    "",
]


class Detection(unittest.TestCase):
    def test_a_named_source_is_found_with_its_tag_year_and_word(self):
        for text, tag, year, key in CITED:
            got = S.find(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got["name"], tag, text)
            self.assertEqual(got["year"], year, text)
            self.assertEqual(got["key"], key, text)
            self.assertEqual(text[got["start"]:got["start"] + len(key)], key, text)

    def test_no_source_no_tag(self):
        for text in NOT_CITED:
            self.assertIsNone(S.find(text), text)

    def test_the_year_is_never_a_count(self):
        got = S.find("More than 2000 measurements from the USGS show the drop.")
        self.assertIsNotNone(got)
        self.assertIsNone(got["year"])
        got = S.find("In 2022, the Bureau of Reclamation's study showed the lake at dead pool.")
        self.assertIsNotNone(got)
        self.assertIsNone(got["year"])             # the year is not said of the study

    def test_the_label_reads_as_on_screen(self):
        self.assertEqual(S.label(S.find("A 2024 NOAA report found it.")), "SOURCE: NOAA, 2024")
        self.assertEqual(S.label(S.find("According to NOAA, it is so.")), "SOURCE: NOAA")

    def test_a_name_that_runs_into_the_next_line_is_this_lines(self):
        got = S.find("That is according to the Bureau of", after="Reclamation, which runs the dam.")
        self.assertIsNotNone(got)
        self.assertEqual(got["name"], "USBR")
        self.assertEqual(got["key"], "Bureau")
        # a source named in the NEXT line is that line's tag, not this one's
        self.assertIsNone(S.find("The lake is low.", after="According to the Bureau of Reclamation, it is."))
        self.assertIsNone(S.find("The lake is low", after="According to the Bureau of Reclamation, it is."))

    def test_the_briefs_own_list_adds_a_name_and_a_year_but_never_a_tag_by_itself(self):
        listed = S.brief_sources({"sources": ["Glen Canyon Institute", {"name": "Bureau of Reclamation", "year": 2026},
                                              "Pacific Institute, 2021", 42, {"publisher": "Reuters"}]})
        self.assertEqual([e["tag"] for e in listed], ["GLEN CANYON INSTITUTE", "USBR", "PACIFIC INSTITUTE", "REUTERS"])
        self.assertEqual([e["year"] for e in listed], [None, 2026, 2021, None])
        # a listed name the line cites (no built-in entry, no org word needed)
        got = S.find("According to Glen Canyon Institute, the lake could be drained.", listed=listed)
        self.assertEqual((got["name"], got["year"], got["listed"]), ("GLEN CANYON INSTITUTE", None, True))
        # the list's year for a built-in source the line names without a year ...
        got = S.find("According to the Bureau of Reclamation, the lake is low.", listed=listed)
        self.assertEqual((got["name"], got["year"], got["listed"]), ("USBR", 2026, True))
        # ... never over a year the line says itself
        got = S.find("A 2019 Bureau of Reclamation report said so.", listed=listed)
        self.assertEqual(got["year"], 2019)
        # and no tag for a line that names nothing, whatever the list says
        self.assertIsNone(S.find("The lake is low.", listed=listed))
        self.assertIsNone(S.find("Glen Canyon Institute is based in Utah.", listed=listed))

    def test_everyday_words_are_journals_only_where_something_was_published(self):
        self.assertEqual(S.find("The paper appeared in Science in 2021.")["name"], "SCIENCE")
        self.assertEqual(S.find("The paper appeared in Science in 2021.")["year"], 2021)
        self.assertIsNone(S.find("According to science, the water is wet."))
        self.assertIsNone(S.find("Science says the water is wet."))


# --------------------------------------------------------------------------- the planner
def _seg(i, text):
    words = [Word(text=w, start=i * SECS + j * 0.3, end=i * SECS + j * 0.3 + 0.25) for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * SECS, end=(i + 1) * SECS, words=words)


def _scenes(n_lines, animation=()):
    n = int(SECS * FPS)
    out = []
    for i in range(n_lines):
        media = {"type": "animation"} if i in animation else \
            {"type": "video", "url": f"https://x/{i}.mp4", "thumbnail": f"https://x/{i}.jpg"}
        out.append({"id": f"s{i}", "startFrame": i * n, "durationInFrames": n, "media": media,
                    "transition": "none", "motion": "none", "effect": "none"})
    return out


def _plan(lines, brief=None, animation=(), density=None, reserved=None):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    n = int(SECS * FPS)
    brief = brief or {"kind": "explainer", "hookBeats": [], "sections": []}
    shots = [{"subject": "water"} for _ in lines]
    with mock.patch.object(config, "GRAPHICS_DENSITY", density or config.GRAPHICS_DENSITY):
        return treatments.plan(segs, shots, _scenes(len(lines), animation), FPS, len(lines) * n, brief,
                               treatments.pack_for(brief, "documentary"), timeline._OVERLAY_SECONDS, reserved=reserved)


def _bare(lines, **kw):
    """The plan with no other graphic at all (every beat left plain): the tag's own rules, on their own."""
    def plain(self, i, seg):
        self.treatments.append(self._entry(self.scenes[i], [], i))
    with mock.patch.object(treatments._Planner, "_beat", plain):
        return _plan(lines, **kw)


def tags(plan):
    return [o for o in plan["overlays"] if o.get("template") == S.LOOK]


def _dump(plan):
    return json.dumps(plan, sort_keys=True, default=str)


PLAIN = "Plain words about the water here."
USBR = "According to the Bureau of Reclamation the lake is at its lowest since it was filled."
USGS = "USGS data shows the river has lost a fifth of its flow."
NOAA = "A 2024 NOAA report found the drought is the worst in twelve centuries."


class ThePlanner(unittest.TestCase):
    def test_flag_is_off_by_default_and_overridable(self):
        self.assertFalse(config.SOURCE_TAGS)
        import handler
        for key in ("SOURCE_TAGS", "SOURCE_TAG_GAP", "SOURCE_TAG_FIRST_SECONDS", "SOURCE_TAG_SECONDS"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
        prev = handler._apply_config({"SOURCE_TAGS": "true", "SOURCE_TAG_GAP": "20"})
        try:
            self.assertTrue(config.SOURCE_TAGS)
            self.assertEqual(config.SOURCE_TAG_GAP, 20.0)
        finally:
            handler._restore_config(prev)
        self.assertFalse(config.SOURCE_TAGS)

    def test_flag_off_changes_nothing(self):
        lines = [PLAIN, PLAIN, USBR, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", False):
            off = _plan(lines)
        self.assertEqual(tags(off), [])
        self.assertNotIn("sources", off)
        # a script that names nothing is planned the same with the flag on
        with mock.patch.object(config, "SOURCE_TAGS", True):
            plain_on = _plan([PLAIN] * 8)
        with mock.patch.object(config, "SOURCE_TAGS", False):
            plain_off = _plan([PLAIN] * 8)
        self.assertEqual(_dump(plain_on), _dump(plain_off))

    def test_the_tag_is_added_without_moving_any_other_graphic(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True):
            on = _plan(lines)
        with mock.patch.object(config, "SOURCE_TAGS", False):
            off = _plan(lines)
        got = tags(on)
        self.assertEqual(len(got), 1, [(o.get("template"), o["startFrame"]) for o in on["overlays"]])
        others = [o for o in on["overlays"] if o.get("template") != S.LOOK]
        self.assertEqual(json.dumps(others, sort_keys=True), json.dumps(off["overlays"], sort_keys=True))
        self.assertEqual(json.dumps(on["sfx"], sort_keys=True), json.dumps(off["sfx"], sort_keys=True))   # silent
        self.assertEqual(on["treatments"], off["treatments"])                                           # no line's own
        self.assertEqual([r["text"] for r in on["sources"]], ["SOURCE: USGS"])
        # and nothing lands on another graphic (one at a time, with a breath between)
        spans = sorted((o["startFrame"], o["startFrame"] + o["durationInFrames"]) for o in on["overlays"])
        for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            self.assertLess(a1 + treatments.BREATH * FPS - 1, b0 + 1e-6, spans)

    def test_lands_on_the_name_as_said_for_three_seconds_with_the_year_said(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, NOAA, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True):
            got = tags(_bare(lines))
        self.assertEqual(len(got), 2)
        # "USGS" opens line 5 at 25.0 s: in on the word (PRE_ROLL early at most), about 3 s, low left, no sound
        first = got[0]
        self.assertEqual(first["type"], "motion")
        self.assertEqual(first["variant"], "src-tag")
        self.assertEqual((first["text"], first["label"], first.get("subtitle")), ("USGS", "Source", None))
        self.assertGreaterEqual(first["startFrame"] / FPS, 25.0 - treatments.PRE_ROLL_FRAMES / FPS - 1e-6)
        self.assertLess(first["startFrame"] / FPS, 25.6)
        self.assertAlmostEqual(first["durationInFrames"] / FPS, config.SOURCE_TAG_SECONDS, delta=0.05)
        self.assertEqual(first["align"], "left")
        self.assertNotIn("sfx", first)
        # "NOAA" is the 3rd word of line 13 (65.6 s): in on it, the year it said; the audit row says which words
        second = got[1]
        self.assertEqual((second["text"], second["subtitle"]), ("NOAA", "2024"))
        word = 13 * SECS + 2 * 0.3
        self.assertGreaterEqual(second["startFrame"] / FPS, word - treatments.PRE_ROLL_FRAMES / FPS - 1e-6)
        self.assertLess(second["startFrame"] / FPS, word + 0.3)
        with mock.patch.object(config, "SOURCE_TAGS", True):
            plan = _bare(lines)
        self.assertEqual([r["text"] for r in plan["sources"]], ["SOURCE: USGS", "SOURCE: NOAA, 2024"])
        self.assertEqual((plan["sources"][1]["said"], plan["sources"][1]["line"]), ("NOAA", 13))

    def test_never_in_the_first_seconds_and_one_per_gap(self):
        lines = [USGS, PLAIN, NOAA, PLAIN, PLAIN, PLAIN, USBR, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN]
        # named at 0.0 s (USGS: too early), 10.6 s (NOAA), 30.9 s (Bureau) and 70.0 s (USGS)
        with mock.patch.object(config, "SOURCE_TAGS", True):
            starts = [o["startFrame"] / FPS for o in tags(_bare(lines))]
        self.assertTrue(all(s >= config.SOURCE_TAG_FIRST_SECONDS for s in starts), starts)
        self.assertEqual(len(starts), 2, starts)
        for got, want in zip(starts, [10.6 - treatments.PRE_ROLL_FRAMES / FPS, 70.0]):
            self.assertAlmostEqual(got, want, delta=0.5 / FPS)
        with mock.patch.object(config, "SOURCE_TAGS", True), mock.patch.object(config, "SOURCE_TAG_GAP", 10.0):
            more = [o["startFrame"] / FPS for o in tags(_bare(lines))]
        self.assertEqual(len(more), 3, more)
        with mock.patch.object(config, "SOURCE_TAGS", True), mock.patch.object(config, "SOURCE_TAG_FIRST_SECONDS", 0.0), \
                mock.patch.object(config, "SOURCE_TAG_GAP", 10.0):
            early = [o["startFrame"] / FPS for o in tags(_bare(lines))]
        self.assertEqual(early[0], 0.0)

    def test_never_on_an_animation_scene_or_in_a_news_compilation(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True):
            self.assertEqual(tags(_plan(lines, animation=(5,))), [])
            self.assertEqual(tags(_plan(lines, density="minimal")), [])
            self.assertEqual(len(tags(_plan(lines))), 1)

    def test_the_tag_waits_for_a_free_screen_and_is_left_out_when_it_cannot_be_read(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True):
            # the job's title card holds 24.5 - 26.5 s: the tag at 25 s would land on it
            held = _bare(lines, reserved=[(24.5, 26.5)])
            # a card from 26 s: the tag is cut to the breath before it, so it lasts only 0.7 s: left out
            short = _bare(lines, reserved=[(26.0, 28.0)])
            # a card from 27.5 s: the tag gives way to it, 2.2 s on screen
            cut = _bare(lines, reserved=[(27.5, 29.0)])
        self.assertEqual(tags(held), [])
        self.assertEqual(tags(short), [])
        got = tags(cut)
        self.assertEqual(len(got), 1)
        self.assertLessEqual((got[0]["startFrame"] + got[0]["durationInFrames"]) / FPS, 27.5 - treatments.BREATH + 1e-6)
        self.assertGreaterEqual(got[0]["durationInFrames"] / FPS, treatments.SOURCE_TAG_LEAST - 0.05)

    def test_the_brand_watermarks_corner_is_left_to_it(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True), treatments.keep_clear("bottom-left"):
            self.assertEqual(tags(_plan(lines))[0]["align"], "right")

    def test_a_brand_kit_that_lists_its_looks_decides(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True):
            with templates.only({"TEXT_KICKER_V1"}):
                self.assertEqual(tags(_bare(lines)), [])          # left out of the kit: no tag
            with templates.only({"TEXT_KICKER_V1", S.LOOK}):
                self.assertEqual(len(tags(_bare(lines))), 1)
            with mock.patch.object(templates, "BANNED", templates.BANNED | {S.LOOK}):
                self.assertEqual(tags(_bare(lines)), [])          # the owner's ban

    def test_the_overlay_passes_the_documents_validation_and_the_doc_carries_the_audit(self):
        lines = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, USGS, PLAIN, PLAIN]
        with mock.patch.object(config, "SOURCE_TAGS", True):
            plan = _plan(lines)
        total = len(lines) * int(SECS * FPS)
        for i, ov in enumerate(plan["overlays"]):
            timeline._validate_overlay(ov, i, total)
        self.assertEqual(plan["sources"][0]["text"], "SOURCE: USGS")


class TheLook(unittest.TestCase):
    def test_registered_silent_and_never_picked_on_its_own(self):
        t = templates.get(S.LOOK)
        self.assertIsNotNone(t)
        self.assertFalse(templates.auto_pick(t))
        self.assertEqual(t["kind"], "tag")
        self.assertEqual(t["defaults"]["sounds"], [])
        self.assertEqual(t["defaults"]["sfx"]["name"], "none")
        self.assertIn("align", t["props"])
        self.assertNotIn(S.LOOK, [x["id"] for x in templates.for_cue("source")])
        self.assertFalse(treatments.auto_ok(S.LOOK))

    def test_the_renderer_draws_it(self):
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        with open(os.path.join(ROOT, "remotion", "src", "components", "lib", "LibSourceTag.tsx"), encoding="utf-8") as fh:
            lib = fh.read()
        self.assertIn('"src-tag"', index)
        self.assertIn('"src-tag": SourceTag', lib)
        self.assertNotIn("Math.random", lib)                # a frame is a pure function of its number
        self.assertIn("CaptionsOn", lib)                    # clear of the captions when they are on
        with open(os.path.join(ROOT, "remotion", "src", "Main.tsx"), encoding="utf-8") as fh:
            self.assertIn("CaptionsOn.Provider", fh.read())


# --------------------------------------------------------------------------- never over a face
def _doc(tag_align="left", face=None, focus=None, animation=False, reframe=None, watermark=""):
    n = int(SECS * FPS)
    media = {"type": "animation"} if animation else {"type": "video", "url": "/work/clip.mp4"}
    if focus is not None:
        media["focus"] = focus
    if reframe is not None:
        media["reframe"] = reframe
    doc = {"fps": FPS, "width": 1920, "height": 1080,
           "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": n, "media": {"type": "video", "url": "/work/a.mp4"}},
                      {"id": "s1", "startFrame": n, "durationInFrames": n, "media": media}],
           "overlays": [{"type": "motion", "template": "TEXT_KICKER_V1", "startFrame": 10, "durationInFrames": 60},
                        {"type": "motion", "template": S.LOOK, "variant": "src-tag", "text": "USGS", "label": "Source",
                         "align": tag_align, "startFrame": n + 15, "durationInFrames": 90}],
           "meta": {"overlayCount": 2}}
    if watermark:
        doc["brand"] = {"watermark": {"position": watermark}}
    return doc, (lambda scene, fps: face)


class Settle(unittest.TestCase):
    def test_nothing_to_do_without_a_tag(self):
        doc = {"fps": 30, "scenes": [], "overlays": [{"type": "motion", "template": "TEXT_KICKER_V1"}]}
        self.assertEqual(S.settle(doc, look=None), {})

    def test_a_face_under_the_corner_moves_the_tag_to_the_other_corner(self):
        # a face low left of the picture (source shares), found in the file
        doc, look = _doc(face={"boxes": [[0.1, 0.7, 0.15, 0.25]], "aspect": 16 / 9})
        stats = S.settle(doc, look=look)
        self.assertEqual((stats["moved"], stats["dropped"]), (1, 0))
        self.assertEqual(doc["overlays"][1]["align"], "right")
        # a face top right: the left corner is clear, nothing moves
        doc, look = _doc(face={"boxes": [[0.7, 0.05, 0.15, 0.25]], "aspect": 16 / 9})
        stats = S.settle(doc, look=look)
        self.assertEqual((stats["moved"], stats["dropped"]), (0, 0))
        self.assertEqual(doc["overlays"][1]["align"], "left")

    def test_faces_in_both_corners_or_the_watermarks_corner_leave_the_tag_out(self):
        doc, look = _doc(face={"boxes": [[0.1, 0.7, 0.15, 0.25], [0.75, 0.7, 0.15, 0.25]], "aspect": 16 / 9})
        stats = S.settle(doc, look=look)
        self.assertEqual((stats["moved"], stats["dropped"]), (0, 1))
        self.assertEqual([o["template"] for o in doc["overlays"]], ["TEXT_KICKER_V1"])
        self.assertEqual(doc["meta"]["overlayCount"], 1)
        doc, look = _doc(face={"boxes": [[0.1, 0.7, 0.15, 0.25]], "aspect": 16 / 9}, watermark="bottom-right")
        self.assertEqual(S.settle(doc, look=look)["dropped"], 1)

    def test_smart_reframings_own_reading_is_trusted(self):
        # the focus says: faces looked for, none found - the file is not opened again
        doc, _look = _doc(focus={"kind": "none", "faces": 0})
        never = mock.Mock(side_effect=AssertionError("looked at the file"))
        self.assertEqual(S.settle(doc, look=never)["moved"], 0)
        # a face it found low left, in source shares of a 4:3 picture cover-fitted to 16:9
        doc, _look = _doc(focus={"kind": "face", "faces": 1, "faceBoxes": [[0.1, 0.7, 0.15, 0.2]], "aspect": 4 / 3})
        self.assertEqual(S.settle(doc, look=never)["moved"], 1)
        self.assertEqual(doc["overlays"][1]["align"], "right")

    def test_a_planned_push_toward_a_face_counts_where_the_face_ends_up(self):
        # a face at mid-height on the left; the push zooms the top-left of the picture, which takes it down
        # into the tag's corner
        focus = {"kind": "face", "faces": 1, "faceBoxes": [[0.08, 0.5, 0.1, 0.15]], "aspect": 16 / 9}
        view = {"from": {"x": 0, "y": 0, "w": 1, "h": 1}, "to": {"x": 0.0, "y": 0.0, "w": 0.6, "h": 0.6}}
        doc, _look = _doc(focus=focus, reframe=view)
        self.assertEqual(S.settle(doc, look=None)["moved"], 1)
        doc, _look = _doc(focus=focus)
        self.assertEqual(S.settle(doc, look=None)["moved"], 0)

    def test_the_tags_own_width_and_the_captions_decide_what_it_covers(self):
        # a face low down at a third of the width: clear of a short tag, under a long one
        face = {"boxes": [[0.30, 0.78, 0.08, 0.14]], "aspect": 16 / 9}
        doc, look = _doc(face=face)
        self.assertEqual(S.settle(doc, look=look)["moved"], 0)
        doc, look = _doc(face=face)
        doc["overlays"][1]["text"] = "SCRIPPS INSTITUTION OF OCEANOGRAPHY"
        self.assertEqual(S.settle(doc, look=look)["moved"], 1)
        # captions on: the tag stands on the caption strip, so a face in the bottom strip is no longer under it ...
        low = {"boxes": [[0.06, 0.88, 0.06, 0.1]], "aspect": 16 / 9}
        doc, look = _doc(face=low)
        self.assertEqual(S.settle(doc, look=look)["moved"], 1)
        doc, look = _doc(face=low)
        doc["captions"] = {"enabled": True}
        self.assertEqual(S.settle(doc, look=look)["moved"], 0)
        # ... and one just above the strip is
        doc, look = _doc(face={"boxes": [[0.06, 0.66, 0.06, 0.08]], "aspect": 16 / 9})
        doc["captions"] = {"enabled": True}
        self.assertEqual(S.settle(doc, look=look)["moved"], 1)
        # the zone grows with the words and keeps the side margin
        short, long_ = S.zone("left", "SOURCE: USGS"), S.zone("left", "SOURCE: " + "X" * 60)
        self.assertLess(short[2], long_[2])
        self.assertLessEqual(long_[2], S.MARGIN_X + S.ROOM + S.AIR + 1e-9)
        right = S.zone("right", "SOURCE: USGS")
        self.assertAlmostEqual(1.0 - right[2], S.MARGIN_X - S.AIR)

    def test_a_scene_that_became_a_full_screen_graphic_loses_its_tag(self):
        doc, _look = _doc(animation=True)
        stats = S.settle(doc, look=None)
        self.assertEqual(stats["dropped"], 1)
        self.assertEqual(len(doc["overlays"]), 1)

    def test_a_picture_that_cannot_be_looked_at_keeps_the_tag_and_says_so(self):
        doc, _look = _doc()
        stats = S.settle(doc, look=lambda scene, fps: None)
        self.assertEqual((stats["moved"], stats["dropped"], stats["unchecked"]), (0, 0, 1))
        stats = S.settle(doc, look=mock.Mock(side_effect=RuntimeError("boom")))
        self.assertIn("error", stats)
        self.assertEqual(len(doc["overlays"]), 2)


if __name__ == "__main__":
    unittest.main()
