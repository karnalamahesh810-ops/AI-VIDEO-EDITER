"""localise(): every file a render chunk downloads reaches Chrome as a served URL (2026-10-01)."""
import os
import tempfile
import unittest
from unittest import mock

from src import assetserver, fanout


def _file(root, name, data=b"x"):
    path = os.path.join(root, "media", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class Localise(unittest.TestCase):
    def test_thumbnails_animation_and_overlay_media_are_all_served(self):
        root = tempfile.mkdtemp()
        clip, still, anim, ov_thumb = (_file(root, n) for n in ("a.mp4", "a.jpg", "b.png", "c.jpg"))
        doc = {"audio": {"url": _file(root, "n.wav")}, "bgm": {"url": "bgm://suspense-v2"},
               "scenes": [{"media": {"type": "video", "url": clip, "thumbnail": still},
                           "animation": {"media": [{"type": "image", "url": anim}]}}],
               "overlays": [{"media": [{"type": "video", "url": "https://pub.example/x.mp4",
                                        "thumbnail": ov_thumb}]}],
               "words": [{"text": "url"}]}
        with assetserver.AssetServer(root) as srv:
            out = assetserver.localise(doc, srv)
            base = srv.base
        served = [out["audio"]["url"], out["scenes"][0]["media"]["url"], out["scenes"][0]["media"]["thumbnail"],
                  out["scenes"][0]["animation"]["media"][0]["url"], out["overlays"][0]["media"][0]["thumbnail"]]
        self.assertTrue(all(u.startswith(base + "/media/") for u in served), served)
        self.assertEqual(out["overlays"][0]["media"][0]["url"], "https://pub.example/x.mp4")
        self.assertEqual(out["bgm"]["url"], "bgm://suspense-v2")
        self.assertEqual(out["words"], [{"text": "url"}])

    def test_a_missing_file_is_left_for_the_renderer_to_report(self):
        root = tempfile.mkdtemp()
        doc = {"scenes": [{"media": {"type": "video", "url": "/nowhere/a.mp4", "thumbnail": "/nowhere/a.jpg"}}]}
        with assetserver.AssetServer(root) as srv:
            out = assetserver.localise(doc, srv)
        self.assertEqual(out["scenes"][0]["media"], {"type": "video", "url": "/nowhere/a.mp4",
                                                     "thumbnail": "/nowhere/a.jpg"})

    def test_what_a_chunk_downloads_is_what_chrome_is_served(self):
        # fanout._localize points the document at its downloads (a neighbour's
        # thumbnail included); localise must turn every one into a served URL.
        root = tempfile.mkdtemp()

        def fake_fetch(url, path, key="", bucket="", tries=4):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"x")
            return path
        scenes = [{"startFrame": i * 30, "durationInFrames": 30,
                   "media": {"type": "video", "url": f"https://pub.example/{i}.mp4",
                             "thumbnail": f"https://pub.example/{i}.jpg"}} for i in range(4)]
        doc = {"scenes": scenes, "overlays": [], "audio": {"url": "https://pub.example/n.wav"}}
        with mock.patch.object(fanout, "_fetch", side_effect=fake_fetch):
            fanout._localize(doc, 0, 29, root)
        self.assertTrue(os.path.isabs(doc["scenes"][1]["media"]["thumbnail"]))   # a neighbour's still
        with assetserver.AssetServer(root) as srv:
            out = assetserver.localise(doc, srv)
            base = srv.base
        local = [v for sc in out["scenes"] for v in sc["media"].values()
                 if isinstance(v, str) and not v.startswith(("http://", "https://")) and v not in ("video",)]
        self.assertEqual(local, [])
        self.assertTrue(out["scenes"][1]["media"]["thumbnail"].startswith(base + "/"))


if __name__ == "__main__":
    unittest.main()
