import base64
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import anchors, costs, vision


def _jpeg(w=1920, h=1080, color=(40, 110, 200)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def _size(b64: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


class FindAnchor(unittest.TestCase):
    """The vision model says where the thing is; the mark gets a point, a radius and a box, or nothing."""

    def setUp(self):
        anchors.reset()
        self.on = mock.patch.object(vision, "enabled", return_value=True)
        self.on.start()
        self.frame = _jpeg()

    def tearDown(self):
        self.on.stop()
        anchors.reset()

    def ask(self, text, model="test-model"):
        return mock.patch.object(vision, "_ask", return_value=(text, model))

    def test_a_box_becomes_a_centre_a_radius_and_a_box(self):
        with self.ask('{"found": true, "box_2d": [300, 100, 700, 200], "confidence": 0.9, "label": "tower"}') as m:
            a = anchors.find_anchor(self.frame, "the intake tower", "the intake tower still stands")
        self.assertAlmostEqual(a["x"], 0.15)
        self.assertAlmostEqual(a["y"], 0.5)
        self.assertAlmostEqual(a["w"], 0.1)
        self.assertAlmostEqual(a["h"], 0.4)
        # A circle round the 192 x 432 px box, as a share of the 1080 px side.
        self.assertAlmostEqual(a["r"], 0.5 * (192 ** 2 + 432 ** 2) ** 0.5 / 1080, places=3)
        self.assertEqual(a["confidence"], 0.9)
        m.assert_called_once()
        messages, max_tokens = m.call_args[0]
        text = " ".join(p.get("text", "") for p in messages[1]["content"] if isinstance(p, dict))
        self.assertIn("the intake tower", text)
        self.assertIn("still stands", text)
        self.assertTrue(messages[1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertLessEqual(max_tokens, 400)

    def test_an_unsure_answer_marks_nothing(self):
        with self.ask('{"found": true, "box_2d": [300, 100, 700, 200], "confidence": 0.59}'):
            self.assertIsNone(anchors.find_anchor(self.frame, "the tower"))
        anchors.reset()
        with self.ask('{"found": true, "box_2d": [300, 100, 700, 200], "confidence": 0.6}'):
            self.assertIsNotNone(anchors.find_anchor(self.frame, "the tower"))

    def test_not_found_marks_nothing(self):
        with self.ask('{"found": false, "confidence": 0}'):
            self.assertIsNone(anchors.find_anchor(self.frame, "a submarine"))

    def test_the_whole_picture_is_not_a_mark(self):
        with self.ask('{"found": true, "box_2d": [0, 0, 1000, 1000], "confidence": 0.95}'):
            self.assertIsNone(anchors.find_anchor(self.frame, "the lake"))

    def test_answers_are_cached_per_frame_and_thing(self):
        answer = '{"found": true, "box_2d": [100, 100, 300, 300], "confidence": 0.8}'
        with self.ask(answer) as m:
            first = anchors.find_anchor(self.frame, "the dam")
            again = anchors.find_anchor(self.frame, "  The   dam ")
            self.assertEqual(m.call_count, 1)
            self.assertEqual(first, again)
            anchors.find_anchor(self.frame, "the spillway")
            self.assertEqual(m.call_count, 2)
            anchors.find_anchor(_jpeg(color=(200, 40, 40)), "the dam")
            self.assertEqual(m.call_count, 3)

    def test_a_no_is_cached_too(self):
        with self.ask('{"found": false}') as m:
            anchors.find_anchor(self.frame, "a whale")
            anchors.find_anchor(self.frame, "a whale")
        self.assertEqual(m.call_count, 1)

    def test_a_failed_call_is_not_cached(self):
        with mock.patch.object(vision, "_ask", return_value=(None, "")) as m:
            self.assertIsNone(anchors.find_anchor(self.frame, "the dam"))
            self.assertIsNone(anchors.find_anchor(self.frame, "the dam"))
        self.assertEqual(m.call_count, 2)

    def test_the_call_is_counted_in_the_costs(self):
        before = costs.summary()["units"].get("vision.anchor", 0)
        with self.ask('{"found": true, "box_2d": [100, 100, 300, 300], "confidence": 0.8}'):
            anchors.find_anchor(self.frame, "the dam")
        self.assertEqual(costs.summary()["units"].get("vision.anchor", 0), before + 1)

    def test_prose_marks_nothing(self):
        with self.ask("The tower is on the left side of the picture."):
            self.assertIsNone(anchors.find_anchor(self.frame, "the tower"))

    def test_fenced_json_and_0_1_coordinates_are_read(self):
        with self.ask('```json\n{"found": true, "box_2d": [0.3, 0.1, 0.7, 0.2], "confidence": 0.85}\n```'):
            a = anchors.find_anchor(self.frame, "the tower")
        self.assertAlmostEqual(a["x"], 0.15)
        self.assertAlmostEqual(a["y"], 0.5)

    def test_a_centre_answer_is_read(self):
        with self.ask('{"x": 0.3, "y": 0.6, "w": 0.1, "h": 0.2, "confidence": 0.8}'):
            a = anchors.find_anchor(self.frame, "the pump")
        self.assertAlmostEqual(a["x"], 0.3)
        self.assertAlmostEqual(a["y"], 0.6)
        self.assertAlmostEqual(a["w"], 0.1)
        self.assertAlmostEqual(a["h"], 0.2)

    def test_vision_off_asks_nothing(self):
        with mock.patch.object(vision, "enabled", return_value=False), self.ask("{}") as m:
            self.assertIsNone(anchors.find_anchor(self.frame, "the dam"))
        m.assert_not_called()

    def test_empty_inputs_ask_nothing(self):
        with self.ask('{"found": true, "box_2d": [100, 100, 300, 300], "confidence": 0.8}') as m:
            self.assertIsNone(anchors.find_anchor("", "the dam"))
            self.assertIsNone(anchors.find_anchor(self.frame, ""))
            self.assertIsNone(anchors.find_anchor("not an image", "the dam"))
            self.assertIsNone(anchors.find_anchor(None, "the dam"))  # type: ignore[arg-type]
        m.assert_not_called()

    def test_a_file_path_and_a_data_url_are_read(self):
        answer = '{"found": true, "box_2d": [100, 100, 300, 300], "confidence": 0.8}'
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "still.jpg")
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(_jpeg(640, 360)))
            with self.ask(answer):
                self.assertIsNotNone(anchors.find_anchor(path, "the dam"))
                self.assertIsNotNone(anchors.find_anchor(f"data:image/jpeg;base64,{_jpeg(320, 180)}", "the dam"))

    def test_a_4_3_picture_is_placed_on_the_16_9_screen(self):
        # 1440 x 1080 covers 1920 x 1080: the top and bottom eighths are cut off.
        four_three = _jpeg(1440, 1080)
        with self.ask('{"found": true, "box_2d": [400, 200, 600, 300], "confidence": 0.9}'):
            a = anchors.find_anchor(four_three, "the gauge")
            self.assertAlmostEqual(a["x"], 0.25)
            self.assertAlmostEqual(a["y"], 0.5)
            self.assertAlmostEqual(a["h"], 0.2 / 0.75, places=3)
            as_is = anchors.find_anchor(four_three, "the gauge", aspect=None)
            self.assertAlmostEqual(as_is["h"], 0.2, places=3)
        anchors.reset()
        with self.ask('{"found": true, "box_2d": [20, 200, 90, 300], "confidence": 0.9}'):
            self.assertIsNone(anchors.find_anchor(four_three, "the sign at the top"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class FrameAt(unittest.TestCase):
    """A frame of a clip at a time, as the base64 JPEG find_anchor takes."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.clip = os.path.join(cls.dir, "clip.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=10",
                        "-pix_fmt", "yuv420p", cls.clip], check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_a_frame_in_the_middle(self):
        b64 = anchors.frame_at(self.clip, 1.0)
        self.assertTrue(b64)
        self.assertEqual(_size(b64), (768, 432))

    def test_past_the_end_gives_the_last_frame(self):
        self.assertTrue(anchors.frame_at(self.clip, 60))

    def test_a_bad_time_or_path_never_raises(self):
        self.assertTrue(anchors.frame_at(self.clip, "soon"))  # type: ignore[arg-type]
        self.assertTrue(anchors.frame_at(self.clip, float("nan")))
        self.assertIsNone(anchors.frame_at(os.path.join(self.dir, "missing.mp4"), 1.0))
        self.assertIsNone(anchors.frame_at("", 1.0))

    def test_a_small_clip_is_not_upscaled(self):
        small = os.path.join(self.dir, "small.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x180:rate=10",
                        "-pix_fmt", "yuv420p", small], check=True, timeout=120)
        self.assertEqual(_size(anchors.frame_at(small, 0.5)), (320, 180))

    def test_a_frame_goes_straight_into_find_anchor(self):
        anchors.reset()
        with mock.patch.object(vision, "enabled", return_value=True), \
                mock.patch.object(vision, "_ask", return_value=('{"found": true, "box_2d": [100, 100, 300, 300], '
                                                                '"confidence": 0.8}', "m")):
            a = anchors.find_anchor(anchors.frame_at(self.clip, 0.5), "the colour bars")
        self.assertAlmostEqual(a["x"], 0.2)
        anchors.reset()


if __name__ == "__main__":
    unittest.main()
