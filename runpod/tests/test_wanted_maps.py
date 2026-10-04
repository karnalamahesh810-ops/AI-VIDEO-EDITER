"""
A line that asks for a map or a diagram accepts a real one (the coordinator, 2026-10-05).

Scene intents carry no visual type of their own, so a line whose wanted shots say
"Idaho map", "state outlines", "cross-section graphic" or "comparison graphic" was
treated like any other: the AI filter turned its maps down as TV weather maps and
read its diagrams as illustrations, the local model turned them down as slides -
8 of the Yellowstone re-cut's 16 hardest still lines (2026-10-04) were such lines,
while the web search held the real figures (NPS/USGS ash map, a USGS report figure,
a NOAA aerosol diagram). Such a line now lets them through to the vision judge,
which is told a real published map or diagram is the shot and still decides; every
other line keeps every rejection.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src import media, slop, vision

MAP_LINE = {"desired_shots": ["map"], "visual_subjects": ["Idaho map", "hotspot track dots"]}
OUTLINE_LINE = {"desired_shots": ["satellite"], "visual_subjects": ["state outlines", "highlighted region"]}
DIAGRAM_LINE = {"desired_shots": ["news", "detail"], "visual_subjects": ["layered earth cross-section"]}
GRAPHIC_LINE = {"visual_subjects": ["comparison graphic", "percentage markers"]}
PLAIN_LINE = {"desired_shots": ["news", "aerial"], "visual_subjects": ["gas plume rising", "seismograph screen",
                                                                       "a photograph of the crater"]}


def _with_intent(si):
    token = media._SCENE_INTENT.set(si)
    return lambda: media._SCENE_INTENT.reset(token)


class WhatTheLineWants(unittest.TestCase):
    def test_the_wanted_shots_and_subjects_name_a_map_or_a_diagram(self):
        self.assertEqual(media.wanted_kind(MAP_LINE), "map")
        self.assertEqual(media.wanted_kind(OUTLINE_LINE), "map")
        self.assertEqual(media.wanted_kind(DIAGRAM_LINE), "chart")
        self.assertEqual(media.wanted_kind(GRAPHIC_LINE), "chart")
        self.assertEqual(media.wanted_kind({"visual_subjects": ["bar chart of the melt"]}), "chart")
        self.assertEqual(media.wanted_kind({"visual_subjects": ["cross section of the reservoir"]}), "chart")

    def test_other_lines_want_nothing_special(self):
        self.assertEqual(media.wanted_kind(PLAIN_LINE), "")      # "seismograph", "photograph" are not graphs
        self.assertEqual(media.wanted_kind({}), "")
        self.assertEqual(media.wanted_kind(None), "")
        token = media._SCENE_INTENT.set(None)
        try:
            self.assertEqual(media.wanted_kind(), "")
        finally:
            media._SCENE_INTENT.reset(token)

    def test_a_visual_type_of_its_own_still_leads(self):
        self.assertEqual(media.wanted_kind({"visualType": "document", "desired_shots": ["map"]}), "document")


class TheFiltersBothWays(unittest.TestCase):
    """slop_reason: a TV-map or 'painted' reading is waived for a map / diagram line only."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="maps_")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.path = os.path.join(self.work, "figure.jpg")
        with open(self.path, "wb") as fh:
            fh.write(b"\xff\xd8\xff" + b"x" * 64)

    def _reason(self, si, verdict):
        def check_file(path, kind="video", allow_people=False, allow_maps=False, footage=True):
            if verdict == "tvmap":
                return "" if allow_maps else "a TV weather map or live-stream screen"
            return verdict
        undo = _with_intent(si)
        try:
            with mock.patch.object(slop, "enabled", return_value=True), \
                    mock.patch.object(slop, "metadata_reason", return_value=""), \
                    mock.patch.object(slop, "check_file", side_effect=check_file):
                return media.slop_reason(self.path, "Figure 3 | blog.example.com", "https://blog.example.com/f.jpg")
        finally:
            undo()

    def test_a_map_line_lets_a_map_through(self):
        self.assertEqual(self._reason(MAP_LINE, "tvmap"), "")
        self.assertEqual(self._reason(OUTLINE_LINE, "tvmap"), "")

    def test_any_other_line_still_turns_a_tv_map_down(self):
        self.assertEqual(self._reason(PLAIN_LINE, "tvmap"), "a TV weather map or live-stream screen")
        self.assertEqual(self._reason({}, "tvmap"), "a TV weather map or live-stream screen")

    def test_a_diagram_line_lets_a_drawn_figure_through(self):
        self.assertEqual(self._reason(DIAGRAM_LINE, "an AI-generated or painted picture (0.71)"), "")
        self.assertEqual(self._reason(GRAPHIC_LINE, "an AI-generated or painted picture (0.66)"), "")

    def test_any_other_line_still_turns_a_painted_picture_down(self):
        self.assertEqual(self._reason(PLAIN_LINE, "an AI-generated or painted picture (0.71)"),
                         "an AI-generated or painted picture (0.71)")

    def test_content_credentials_saying_generated_turn_it_down_on_every_line(self):
        why = "an AI-generated picture (content credentials: trainedAlgorithmicMedia)"
        self.assertEqual(self._reason(DIAGRAM_LINE, why), why)
        self.assertEqual(self._reason(MAP_LINE, why), why)

    def test_a_studio_stays_out_on_a_map_line(self):
        self.assertEqual(self._reason(MAP_LINE, "a TV studio, presenter or talking head"),
                         "a TV studio, presenter or talking head")

    def test_the_local_model_is_told_what_the_line_wants(self):
        seen = []

        def check(path, intent, subject_type="", subject="", wants=""):
            seen.append(wants)
            return None
        for si in (MAP_LINE, DIAGRAM_LINE, PLAIN_LINE):
            undo = _with_intent(si)
            try:
                with mock.patch.object(media.config, "LOCAL_VISION_ENABLED", True), \
                        mock.patch.object(media._localvision, "available", return_value=True), \
                        mock.patch.object(media._localvision, "check", side_effect=check):
                    media._local_check(self.path, "the hotspot track across Idaho")
            finally:
                undo()
        self.assertEqual(seen, ["map", "chart", ""])

    def test_the_local_model_lets_a_slide_like_figure_through_only_for_such_a_line(self):
        from src import localvision
        slideish = {"photo": 0.02, "person": 0.0, "slide": 0.9, "text": 0.04, "map": 0.02, "chart": 0.02,
                    "logo": 0.0, "render": 0.0}                                      # over the 0.80 share
        self.assertEqual(localvision._reject_reason(slideish, "place", "chart"), "")
        self.assertEqual(localvision._reject_reason(slideish, "place", ""), "a presentation slide")


class TheJudgeIsTold(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="judge_")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.path = os.path.join(self.work, "figure.jpg")
        with open(self.path, "wb") as fh:
            fh.write(b"\xff\xd8\xff" + b"figure" * 32)
        self.asked = []
        verdict = {"description": "a USGS map", "score": 0.82, "quality": 0.7, "has_text_or_watermark": False,
                   "is_talking_head": False, "ai_generated": False, "studio": False, "specificity": "location"}

        def ask(messages, max_tokens, accept=None):
            self.asked.append(messages[1]["content"][0]["text"])
            return json.dumps(verdict), "stub-model"
        for p in (mock.patch.object(vision, "enabled", return_value=True),
                  mock.patch.object(vision, "sample_frames", return_value=["aGk="]),
                  mock.patch.object(vision, "_ask", side_effect=ask),
                  mock.patch.dict(vision._CACHE, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_a_map_or_diagram_line_reads_that_a_published_one_is_the_shot(self):
        vision.judge(self.path, "Snake River Plain hotspot track map", "", wants="map")
        vision.judge(self.path, "Yellowstone magma reservoir cross-section", "", wants="chart")
        self.assertIn("WANTED: the line asks for a map.", self.asked[0])
        self.assertIn("a chart, a diagram or a cross-section", self.asked[1])
        for text in self.asked:
            self.assertIn("TV weather map or forecast graphic (studio)", text)      # still rejected
            self.assertIn("presentation slide", text)

    def test_any_other_line_reads_no_such_thing(self):
        vision.judge(self.path, "Mary Bay crater from the air", "")
        vision.judge(self.path, "Mary Bay crater from the air", "", wants="document")
        self.assertEqual(len(self.asked), 1)                                         # same key: one verdict
        self.assertNotIn("WANTED", self.asked[0])

    def test_a_verdict_for_a_map_line_is_not_reused_for_a_plain_one(self):
        vision.judge(self.path, "Idaho", "", wants="map")
        vision.judge(self.path, "Idaho", "")
        self.assertEqual(len(self.asked), 2)

    def test_the_gate_passes_what_the_line_wants_only_for_such_a_line(self):
        seen = []

        def judge(path, intent, context, event=False, scene=None, **kw):
            seen.append(kw.get("wants", ""))
            return None
        for si in (MAP_LINE, DIAGRAM_LINE, PLAIN_LINE):
            undo = _with_intent(si)
            try:
                with mock.patch.object(media, "slop_reason", return_value=""), \
                        mock.patch.object(media, "_local_check", return_value=None), \
                        mock.patch.object(media.vision, "judge", side_effect=judge), \
                        mock.patch.object(media.config, "ACCEPT_UNJUDGED", True):
                    media._judge_gate(self.path, "the line", "", "label")
            finally:
                undo()
        self.assertEqual(seen, ["map", "chart", ""])

    def test_the_judges_hard_rejects_still_stand(self):
        v = {"description": "", "score": 0.9, "quality": 0.8, "has_text_or_watermark": False,
             "is_talking_head": False, "ai_generated": False, "studio": True}
        self.assertFalse(vision.acceptable(v))                                      # a TV weather map: studio
        v.update(studio=False, ai_generated=True)
        self.assertFalse(vision.acceptable(v))


if __name__ == "__main__":
    unittest.main()
