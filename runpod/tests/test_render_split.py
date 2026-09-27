import unittest
from unittest import mock

import handler
from src import config


class EditorRenderSplits(unittest.TestCase):
    def test_the_render_action_splits_across_workers_when_it_can(self):
        doc = {"fps": 30, "scenes": [], "overlays": []}
        seen = {}

        def fake_do_render(d, inp, work, report, split=False):
            seen["split"] = split
            return {"video_url": "u", "duration_seconds": 1}
        with mock.patch.object(handler, "do_render", side_effect=fake_do_render), \
                mock.patch.object(handler.fanout, "render_enabled", return_value=True), \
                mock.patch.object(handler.storage, "patch_project"), \
                mock.patch.object(handler, "_fill_missing_media", return_value=0):
            out = handler.handler({"id": "job-1", "input": {"action": "render", "project_id": "p1", "timeline": doc}})
        self.assertTrue(seen.get("split"), out)


class Preflight(unittest.TestCase):
    def test_unreadable_clips_are_replaced_before_rendering(self):
        doc = {"fps": 30, "meta": {}, "scenes": [
            {"id": "s0", "startFrame": 0, "durationInFrames": 90, "text": "a",
             "media": {"type": "video", "url": "https://ok/a.mp4", "source": "youtube"}},
            {"id": "s1", "startFrame": 90, "durationInFrames": 90, "text": "b",
             "media": {"type": "video", "url": "https://broken/b.mp4", "source": "youtube"}},
            {"id": "s2", "startFrame": 180, "durationInFrames": 90, "text": "c",
             "media": {"type": "animation", "url": "", "source": "template"}}]}

        def get(url, **kw):
            r = mock.Mock()
            r.status_code = 500 if "broken" in url else 206
            return r
        with mock.patch("requests.get", side_effect=get), \
                mock.patch.object(config, "ANIMATION_FILL", False):
            n = handler._preflight_media(doc)
        self.assertEqual(n, 1)
        self.assertEqual(doc["scenes"][0]["media"]["url"], "https://ok/a.mp4")
        self.assertNotEqual(doc["scenes"][1]["media"].get("url"), "https://broken/b.mp4")
        self.assertTrue(doc["scenes"][1]["reviewRequired"])


if __name__ == "__main__":
    unittest.main()
