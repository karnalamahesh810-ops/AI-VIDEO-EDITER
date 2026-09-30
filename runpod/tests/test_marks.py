"""
Marks that point at something - only where it is worth it (src/marks.py).

The owner (2026-09-30): a red arrow / circle on a clip only when the line
points at something visible and vision finds it; a photo look that points
never points at a random spot.
"""
import os
import tempfile
import unittest
from unittest import mock

from src import config, marks

FPS = 30


def _file(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, b"x")
    os.close(fd)
    return path


def scene(i, start_s, dur_s, text, kind="video", url="", words=None, **media):
    m = {"type": kind, "url": url, **media}
    return {"id": f"s{i}", "startFrame": int(start_s * FPS), "durationInFrames": int(dur_s * FPS),
            "text": text, "media": m, "words": words or [], "semanticMetadata": {"subject": "Hoover Dam"}}


ANCHOR = {"x": 0.6, "y": 0.4, "r": 0.2, "w": 0.3, "h": 0.25, "confidence": 0.9}


class WhatIsPointedAt(unittest.TestCase):
    def test_pointing_lines(self):
        self.assertEqual(marks._what_from("You can see the water line on the dam wall."), "water line")
        self.assertEqual(marks._what_from("Look at this bridge as the river rises."), "bridge")
        self.assertEqual(marks._what_from("Notice the cracks running down the spillway."), "cracks")
        self.assertEqual(marks._what_from("That levee failed on Tuesday."), "levee")

    def test_lines_that_point_at_nothing(self):
        for text in ("This year was the driest on record.", "You can see why officials worry.",
                     "The storm moved north overnight.", "Look at it."):
            self.assertEqual(marks._what_from(text), "", text)


class VideoMarks(unittest.TestCase):
    def setUp(self):
        self.clip = _file(".mp4")
        self.addCleanup(os.remove, self.clip)

    def doc(self, scenes, overlays=None):
        return {"fps": FPS, "scenes": scenes, "overlays": list(overlays or []), "sfx": [],
                "meta": {"voiceLufs": -16.0}}

    def test_a_mark_lands_on_the_pointing_words_where_vision_finds_the_thing(self):
        words = [{"text": w, "start": 10.0 + 0.3 * k, "end": 10.25 + 0.3 * k}
                 for k, w in enumerate("And you can see the water line on the dam".split())]
        d = self.doc([scene(0, 0, 10, "The lake keeps falling."),
                      scene(1, 10, 6, "And you can see the water line on the dam", url=self.clip, words=words)])
        find = mock.Mock(return_value=dict(ANCHOR))
        frame_at = mock.Mock(return_value="b64")
        stats = marks.place_video_marks(d, find, frame_at)
        self.assertEqual(stats["videoMarks"], 1)
        ov = d["overlays"][0]
        self.assertIn(ov["template"], marks.VIDEO_MARKS)
        self.assertEqual(ov["anchor"], ANCHOR)
        self.assertEqual(ov["durationInFrames"], int(marks.MARK_SECONDS * FPS))
        # On the words "you can see" (word 1 at 10.3 s), at most 2 frames early.
        self.assertEqual(ov["startFrame"], int(round(10.3 * FPS)) - 2)
        self.assertEqual(find.call_args[0][1], "water line")
        # The mark's sound is built into the look (registry defaults.sounds,
        # played by the renderer's LookSounds), so no timeline row is added.
        from src import sfxplan, templates
        self.assertTrue(sfxplan.has_builtin_sound(templates.get(ov["template"])))
        self.assertEqual(d["sfx"], [])

    def test_no_mark_when_vision_does_not_find_it(self):
        d = self.doc([scene(0, 0, 6, "Look at this bridge", url=self.clip)])
        stats = marks.place_video_marks(d, mock.Mock(return_value=None), mock.Mock(return_value="b64"))
        self.assertEqual(stats["videoMarks"], 0)
        self.assertEqual(d["overlays"], [])
        self.assertEqual(d["sfx"], [])

    def test_no_mark_over_another_graphic(self):
        busy = {"template": "LIB_ED_TYPE_CLEAN", "startFrame": 0, "durationInFrames": 6 * FPS}
        d = self.doc([scene(0, 0, 6, "Look at this bridge", url=self.clip)], [busy])
        find = mock.Mock(return_value=dict(ANCHOR))
        marks.place_video_marks(d, find, mock.Mock(return_value="b64"))
        self.assertEqual(d["overlays"], [busy])
        find.assert_not_called()

    def test_capped_and_spaced(self):
        scenes = [scene(i, i * 6, 6, "Look at this bridge", url=self.clip) for i in range(40)]
        d = self.doc(scenes)
        with mock.patch.object(config, "MARKS_MAX", 3), mock.patch.object(config, "MARKS_GAP_SECONDS", 60.0):
            marks.place_video_marks(d, mock.Mock(return_value=dict(ANCHOR)), mock.Mock(return_value="b64"))
        starts = [o["startFrame"] for o in d["overlays"]]
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(b - a >= 60 * FPS for a, b in zip(starts, starts[1:])))

    def test_stills_and_remote_clips_get_no_video_mark(self):
        d = self.doc([scene(0, 0, 6, "Look at this bridge", kind="image", url=self.clip),
                      scene(1, 6, 6, "Look at this bridge", url="https://example.com/a.mp4")])
        find = mock.Mock(return_value=dict(ANCHOR))
        marks.place_video_marks(d, find, mock.Mock(return_value="b64"))
        find.assert_not_called()

    def test_a_slowed_clip_is_looked_at_where_it_really_is(self):
        # A 3 s clip in a 6 s scene plays at 0.6x... max(0.6, 3/6) = 0.6.
        d = self.doc([scene(0, 0, 6, "Look at this bridge", url=self.clip, clipSeconds=3.0)])
        frame_at = mock.Mock(return_value="b64")
        marks.place_video_marks(d, mock.Mock(return_value=dict(ANCHOR)), frame_at)
        ov = d["overlays"][0]
        hit = 14   # LIB_VM_ARROW's sfxAt at 30 fps
        expected = (ov["startFrame"] + hit) / FPS * 0.6
        self.assertAlmostEqual(frame_at.call_args[0][1], expected, places=3)


class PhotoAnchors(unittest.TestCase):
    def setUp(self):
        self.still = _file(".jpg")
        self.addCleanup(os.remove, self.still)

    def test_a_pointing_photo_look_gets_its_spot(self):
        ov = {"template": "LIB_PE_RED_ARROW", "startFrame": 0, "durationInFrames": 120, "text": "SPILLWAY"}
        d = {"fps": FPS, "scenes": [scene(0, 0, 6, "The spillway sat dry.", kind="image", url=self.still)],
             "overlays": [ov]}
        stats = marks.place_photo_anchors(d, mock.Mock(return_value=dict(ANCHOR)))
        self.assertEqual(stats["photoAnchored"], 1)
        self.assertEqual(ov["anchor"], ANCHOR)
        self.assertEqual(ov["template"], "LIB_PE_RED_ARROW")

    def test_a_pointing_look_with_no_spot_is_swapped_never_pointing_at_nothing(self):
        ov = {"template": "LIB_PE_RED_ARROW", "startFrame": 30, "durationInFrames": 120, "text": "SPILLWAY"}
        d = {"fps": FPS, "scenes": [scene(0, 0, 6, "The spillway sat dry.", kind="image", url=self.still)],
             "overlays": [ov]}
        stats = marks.place_photo_anchors(d, mock.Mock(return_value=None))
        self.assertEqual(stats["photoSwapped"], 1)
        self.assertEqual(ov["template"], marks.PHOTO_FALLBACK)
        self.assertNotIn("anchor", ov)
        self.assertEqual((ov["startFrame"], ov["durationInFrames"]), (30, 120))

    def test_a_detail_look_keeps_its_default_spot(self):
        ov = {"template": "LIB_PE_MAGNIFY", "startFrame": 0, "durationInFrames": 120, "text": "GAUGE"}
        d = {"fps": FPS, "scenes": [scene(0, 0, 6, "The gauge read 3,520 feet.", kind="image", url=self.still)],
             "overlays": [ov]}
        stats = marks.place_photo_anchors(d, mock.Mock(return_value=None))
        self.assertEqual(stats["photoSwapped"], 0)
        self.assertEqual(ov["template"], "LIB_PE_MAGNIFY")


class NeverFails(unittest.TestCase):
    def test_place_swallows_errors(self):
        with mock.patch.object(marks, "place_photo_anchors", side_effect=RuntimeError("boom")), \
                mock.patch.object(marks, "place_video_marks", side_effect=RuntimeError("boom")):
            self.assertEqual(marks.place({"fps": 30, "scenes": [], "overlays": []}), {})

    def test_switch_off(self):
        with mock.patch.object(config, "MARKS_ENABLED", False):
            self.assertEqual(marks.place({"fps": 30, "scenes": [], "overlays": []}), {})


if __name__ == "__main__":
    unittest.main()
