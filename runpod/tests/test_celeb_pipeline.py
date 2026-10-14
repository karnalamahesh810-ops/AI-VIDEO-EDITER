"""The celeb compilation style inside the worker's normal actions (src/celeb/pipeline.py, handler.py). Offline."""
import os
import unittest
from unittest import mock

os.environ.setdefault("SKIP_DOTENV", "1")

from src import styles  # noqa: E402
from src.celeb import pipeline, reel, script, speakers  # noqa: E402


def _timeline():
    tl = reel.Timeline()
    tl.total = 30.0
    tl.cuts = [0.0, 4.0, 10.0]
    tl.captions = [(4.2, 5.0, "I'M SPIDER-MAN.", speakers.COLOURS[0]),
                   (5.1, 6.0, "NO WAY.", speakers.COLOURS[1])]
    tl.marks = [reel.Mark("name", 4.5, 1.9, "TOM HOLLAND", "left")]
    tl.clip_spans = [(4.0, 14.0)]
    tl.log = [{"video": "c00", "url": "", "in": 17.0, "out": 27.0, "at": 4.0}]
    return tl


class StyleRouting(unittest.TestCase):
    def test_style_and_aliases(self):
        self.assertEqual(styles.resolve("celeb_compilation"), "celeb_compilation")
        self.assertEqual(styles.resolve("Celeb"), "celeb_compilation")
        self.assertTrue(pipeline.is_celeb({"video_style": "celeb_compilation"}))
        self.assertTrue(pipeline.is_celeb({"action": "render", "timeline": {"celeb": {}}}))
        self.assertFalse(pipeline.is_celeb({"video_style": "documentary"}))

    def test_block_key_wins_over_url(self):
        b = script.parse("[CLIP: url=https://youtu.be/QteOt8XAbIY start=1:07.4 end=1:27.4]")[0]
        self.assertEqual(b.video_id, "QteOt8XAbIY")
        b.key = "c00"
        self.assertEqual(b.video_id, "c00")
        self.assertEqual(b.youtube_id, "QteOt8XAbIY")


class Document(unittest.TestCase):
    def test_captions_rights_and_round_trip(self):
        tl = _timeline()
        found = [{"key": "c00", "video": "QteOt8XAbIY", "title": "Gag Reel", "channel": "Sony", "at0": 50.4,
                  "dur": 41.0, "path": "x.mp4"}]
        doc = pipeline.document({"title": "Bloopers"}, tl, found, [], {}, {"base": "https://r2/base.mp4"}, "script")
        c = doc["celeb"]
        self.assertEqual(doc["meta"]["videoStyle"], "celeb_compilation")
        self.assertEqual(doc["scenes"], [])
        self.assertEqual([x["color"] for x in c["captions"]], ["yellow", "white"])
        self.assertEqual(c["rights"][0]["in"], 67.4)          # the window's start + the clip's in-point
        self.assertEqual(c["rights"][0]["out"], 77.4)
        self.assertEqual(c["rights"][0]["url"], "https://www.youtube.com/watch?v=QteOt8XAbIY")
        # the editor flips the second line to green: the render reads it back as green
        c["captions"][1]["color"] = "green"
        back = pipeline._timeline_from(doc)
        self.assertEqual(back.captions[1][3][:3], tuple(speakers.COLOURS[2])[:3])
        self.assertEqual(back.marks[0].text, "TOM HOLLAND")
        self.assertEqual(back.total, 30.0)

    def test_featured_colour_option(self):
        self.assertEqual(pipeline.featured_colour({}), "yellow")
        self.assertEqual(pipeline.featured_colour({"celeb_featured_colour": "White"}), "white")
        self.assertEqual(pipeline.featured_colour({"celeb_featured_colour": "green"}), "yellow")
        doc = pipeline.document({"celeb_featured_colour": "white"}, _timeline(), [], [], {}, {}, "")
        self.assertEqual(doc["celeb"]["featured_colour"], "white")

    def test_unknown_colour_is_first_voice(self):
        self.assertEqual(pipeline.colour_name((1, 2, 3, 255)), "yellow")
        self.assertEqual(pipeline.colour_rgba("nope")[:3], tuple(speakers.COLOURS[0])[:3])


class Handler(unittest.TestCase):
    def test_build_goes_through_the_celeb_path_without_ai_checks(self):
        import handler
        doc = {"scenes": [], "meta": {"videoStyle": "celeb_compilation"}, "celeb": {"duration": 30.0}}
        with mock.patch.object(handler.celeb_pipeline, "run", return_value=(doc, "final.mp4", 30.0)) as run, \
                mock.patch.object(handler, "deliver_video", return_value={"video_url": "https://v", "duration": 30.0}), \
                mock.patch.object(handler, "_require_youtube") as yt, \
                mock.patch.object(handler, "_require_ai_credit") as ai, \
                mock.patch.object(handler, "_require_openrouter_credit") as orc:
            out = handler.handler({"id": "t1", "input": {"action": "build", "video_style": "celeb_compilation",
                                                         "script": "[CLIP: Tom | \"hi\" | Kimmel]"}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["video_url"], "https://v")
        self.assertEqual(out["timeline"]["meta"]["videoStyle"], "celeb_compilation")
        run.assert_called_once()
        yt.assert_called_once()
        ai.assert_not_called()
        orc.assert_not_called()

    def test_render_of_a_celeb_document(self):
        import handler
        doc = {"scenes": [], "meta": {"videoStyle": "celeb_compilation"}, "celeb": {"duration": 30.0}}
        with mock.patch.object(handler.celeb_pipeline, "run", return_value=(doc, "final.mp4", 30.0)) as run, \
                mock.patch.object(handler, "deliver_video", return_value={"video_url": "https://v", "duration": 30.0}), \
                mock.patch.object(handler, "_require_youtube") as yt:
            out = handler.handler({"id": "t2", "input": {"action": "render", "timeline": doc}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(run.call_args[0][0], "render")
        yt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
