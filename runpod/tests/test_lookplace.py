"""The KT looks' place on their picture (src/lookplace.py): a soft panel over a busy picture, the calm side."""
import io
import random
import unittest

from PIL import Image, ImageDraw

from src import lookplace


def _jpeg(busy_left: bool, busy_right: bool) -> bytes:
    im = Image.new("RGB", (640, 360), (90, 120, 150))
    d = ImageDraw.Draw(im)
    rnd = random.Random(7)
    for x0, on in ((0, busy_left), (352, busy_right)):
        if on:          # map-like lettering and lines
            for _ in range(4000):
                x, y = x0 + rnd.randint(0, 280), rnd.randint(0, 350)
                d.line((x, y, x + rnd.randint(2, 14), y + rnd.randint(-6, 6)), fill=(250, 250, 250), width=1)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _doc(media):
    scenes = [{"id": "s0", "startFrame": 0, "durationInFrames": 300, "media": media}]
    ovs = [{"template": "KT_NUMBER", "variant": "kt-number", "value": 15, "startFrame": 10, "durationInFrames": 135},
           {"template": "KT_DATE", "variant": "kt-date", "text": "August 21", "startFrame": 160, "durationInFrames": 126}]
    return ovs, scenes


class Place(unittest.TestCase):
    def test_a_busy_corner_gets_the_panel_and_the_calm_side(self):
        pics = {"https://x/busy-left.jpg": _jpeg(True, False)}
        ovs, scenes = _doc({"type": "image", "url": "https://x/busy-left.jpg"})
        rep = lookplace.place(ovs, scenes, fetch=pics.get)
        self.assertEqual(ovs[0].get("backing"), "panel")
        self.assertEqual(ovs[0].get("zone"), "right-panel")
        self.assertEqual(ovs[1].get("zone"), "upper-right")
        self.assertEqual(rep["measured"], 2)

    def test_a_calm_picture_keeps_the_home_place(self):
        pics = {"https://x/calm.jpg": _jpeg(False, False)}
        ovs, scenes = _doc({"type": "image", "url": "https://x/calm.jpg"})
        lookplace.place(ovs, scenes, fetch=pics.get)
        self.assertFalse([o for o in ovs if o.get("backing") or o.get("zone")])

    def test_busy_everywhere_is_a_panel_at_home(self):
        pics = {"https://x/busy.jpg": _jpeg(True, True)}
        ovs, scenes = _doc({"type": "image", "url": "https://x/busy.jpg"})
        lookplace.place(ovs, scenes, fetch=pics.get)
        self.assertEqual(ovs[0].get("backing"), "panel")
        self.assertIsNone(ovs[0].get("zone"))

    def test_the_vision_data_wins_and_nothing_is_fetched(self):
        ovs, scenes = _doc({"type": "video", "url": "https://x/c.mp4", "focus": {"busy": 0.8}})
        lookplace.place(ovs, scenes, fetch=lambda u: self.fail(u))
        self.assertEqual(ovs[0].get("backing"), "panel")

    def test_an_unread_picture_or_a_placed_look_is_left_alone(self):
        ovs, scenes = _doc({"type": "image", "url": "https://x/gone.jpg"})
        ovs[1]["zone"] = "upper-left"
        rep = lookplace.place(ovs, scenes, fetch=lambda u: None)
        self.assertFalse(ovs[0].get("backing"))
        self.assertEqual(ovs[1]["zone"], "upper-left")
        self.assertEqual(rep["unmeasured"], 1)


class Captions(unittest.TestCase):
    def test_the_planners_bracketed_note_is_not_drawn(self):
        from src import datalooks
        self.assertEqual(datalooks.caption_clean("Hoover Dam outlet works (river releases)"), "Hoover Dam outlet works")
        self.assertEqual(datalooks.caption_clean("Savings account deposit vs missed paycheck (metaphor)"),
                         "Savings account deposit vs missed paycheck")
        self.assertIsNone(datalooks.caption_clean("Lake Mead"))
        self.assertIsNone(datalooks.caption_clean("(1970)"))
        doc = {"fps": 30, "durationInFrames": 600, "scenes": [{"startFrame": 0, "durationInFrames": 600}],
               "overlays": [{"template": "LIB_PA_TILT_CARD", "type": "motion", "text": "Hoover Dam outlet works (river releases)",
                             "startFrame": 30, "durationInFrames": 150}]}
        datalooks.finish(doc, plan_data=False)
        self.assertEqual(doc["overlays"][0]["text"], "Hoover Dam outlet works")


if __name__ == "__main__":
    unittest.main()
