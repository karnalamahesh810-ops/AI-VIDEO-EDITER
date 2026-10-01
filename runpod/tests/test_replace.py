import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import handler
from src import config, fanout, media


def _doc():
    return {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 540, "audio": {"url": "a"},
            "meta": {"story": {"kind": "weather", "event": "Lake Mead drought", "year": 2026,
                               "recent": True, "places": ["Nevada"]}},
            "scenes": [
                {"id": "s0000", "startFrame": 0, "durationInFrames": 180, "text": "Lake Mead has fallen.",
                 "media": {"type": "video", "url": "https://x/a.mp4", "source": "youtube"},
                 "semanticMetadata": {"assetId": "yt:AAAAAAAAAAA", "intent": "Lake Mead aerial",
                                      "sceneIntent": {"entities": ["Lake Mead"], "locations": ["Nevada"],
                                                      "specificity": "event", "time_context": "current"}}},
                {"id": "s0001", "startFrame": 180, "durationInFrames": 180, "text": "Boat ramps end in gravel.",
                 "media": {"type": "video", "url": "https://x/b.mp4", "source": "youtube"},
                 "semanticMetadata": {"assetId": "yt:BBBBBBBBBBB"}},
                {"id": "s0002", "startFrame": 360, "durationInFrames": 180, "text": "Las Vegas draws its water.",
                 "media": {"type": "color"}, "semanticMetadata": {}},
            ]}


def _asset(d, n_alts=4):
    p = os.path.join(d, "yt_WINNER00000_10_7.mp4")
    open(p, "wb").write(b"x" * 10)
    a = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=WINNER00000&t=10",
                         local_path=p, duration=7.0, attribution="YouTube: winner",
                         content_description="Lake Mead shoreline aerial", relevance_score=0.9, quality=0.8,
                         final_score=0.85, specificity="event", moment={"start": 10.0, "clean": True})
    for i in range(n_alts):
        lp = os.path.join(d, f"yt_ALT{i}00000000_5_7.mp4"[:24] + ".mp4")
        open(lp, "wb").write(b"y")
        a.alternatives.append({"assetId": f"yt:ALT{i}", "url": f"https://www.youtube.com/watch?v=ALT{i}",
                               "title": f"alt {i}", "score": 0.8 - i * 0.05, "quality": 0.7,
                               "finalScore": 0.7 - i * 0.05, "specificity": "location",
                               "description": "d", "source": "youtube", "localPath": lp, "moment": {}})
    return a


class ReplaceClip(unittest.TestCase):
    def test_returns_ranked_choices_and_excludes_rejected_and_used_clips(self):
        d = tempfile.mkdtemp()
        seen = {}

        def fake_source(query, seconds, work, **kw):
            seen.update(kw, query=query, seconds=seconds)
            seen["best_of"] = config.JUDGE_BEST_OF
            seen["keep"] = media._KEEP_ALT_FILES.get()
            return _asset(d)
        before = config.JUDGE_BEST_OF
        with mock.patch.object(media, "source_for_segment", fake_source), \
                mock.patch.object(media, "reset_cache"), \
                mock.patch.object(handler.vision, "set_story"):
            doc, cands = handler.do_resource(
                {"timeline": _doc(), "scene_index": 0, "exclude": ["yt:REJECTED000"], "count": 5,
                 "publish_media": False}, d, lambda *a, **k: None)
        self.assertEqual(config.JUDGE_BEST_OF, before)              # overrides restored
        self.assertEqual(seen["best_of"], 5)
        self.assertTrue(seen["keep"])
        self.assertEqual(seen["used"], {"yt:AAAAAAAAAAA", "yt:BBBBBBBBBBB", "yt:REJECTED000"})
        self.assertEqual(seen["scene_intent"]["entities"], ["Lake Mead"])
        self.assertTrue(seen["fallbacks"])                            # the intent's expanded searches
        self.assertEqual(len(cands), 5)
        self.assertTrue(cands[0]["winner"] and cands[0]["assetId"] == "yt:WINNER00000")
        self.assertEqual([c["rank"] for c in cands], [1, 2, 3, 4, 5])
        self.assertFalse(any("localPath" in c for c in cands))
        sem = doc["scenes"][0]["semanticMetadata"]
        self.assertEqual(sem["assetId"], "yt:WINNER00000")
        self.assertEqual(sem["specificity"], "event")
        self.assertEqual(len(sem["alternatives"]), 4)
        self.assertEqual(doc["scenes"][0]["media"]["url"], cands[0]["media"]["url"])

    def test_regenerate_plans_the_beat_again_from_the_story(self):
        d = tempfile.mkdtemp()
        seen = {}

        def fake_ai_pass(segments, title, shots, report=None, brief=None):
            shots[0]["query"] = "Lake Mead low water 2026 aerial"
            shots[0]["intent"] = "Lake Mead 2026 low water aerial footage"
            shots[0]["subject"] = "Lake Mead"
            shots[0]["entity"] = "natural-feature"
            shots[0]["sceneIntent"] = {"entities": ["Lake Mead"], "locations": ["Nevada"], "event_type": "drought",
                                       "visual_subjects": ["low water"], "desired_shots": ["aerial"],
                                       "time_context": "current", "specificity": "event", "generic_ok": False}
            return 1, []

        def fake_source(query, seconds, work, **kw):
            seen.update(kw, query=query)
            return _asset(d, 1)
        with mock.patch.object(handler.director, "is_configured", return_value=True), \
                mock.patch.object(handler.director, "_ai_pass", fake_ai_pass), \
                mock.patch.object(media, "source_for_segment", fake_source), \
                mock.patch.object(media, "reset_cache"), \
                mock.patch.object(handler.vision, "set_story"):
            doc, cands = handler.do_resource(
                {"timeline": _doc(), "scene_index": 0, "mode": "regenerate", "publish_media": False,
                 "title": "Lake Mead"}, d, lambda *a, **k: None)
        # anchor_to_story may re-order the words around the place and year.
        self.assertIn("Lake Mead", seen["query"])
        self.assertIn("low water", seen["query"])
        self.assertEqual(seen["scene_intent"]["visual_subjects"], ["low water"])
        self.assertEqual(doc["scenes"][0]["query"], seen["query"])
        self.assertEqual(len(cands), 2)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
    def test_the_new_clip_keeps_its_measured_length(self):
        # A build records each clip's length (clipSeconds); a replacement had
        # none, so the renderer played a clip shorter than its scene at 1x and
        # it froze on its last frame (measured, src/quality.py).
        d = tempfile.mkdtemp()
        p = os.path.join(d, "yt_SHORTCLIP01_10_4.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=4",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p], check=True)
        a = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=SHORTCLIP01&t=10",
                             local_path=p, duration=7.0)
        with mock.patch.object(media, "source_for_segment", return_value=a), \
                mock.patch.object(media, "reset_cache"), mock.patch.object(handler.vision, "set_story"), \
                mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False):
            doc, _cands = handler.do_resource({"timeline": _doc(), "scene_index": 1, "publish_media": False},
                                              d, lambda *a, **k: None)
        # The file's own 4 s, not the 7 s it was cut for.
        self.assertAlmostEqual(doc["scenes"][1]["media"]["clipSeconds"], 4.0, delta=0.05)


class PartialRerender(unittest.TestCase):
    def _render(self, doc, work, previous, calls, downloads):
        def render_local(frames, path, muted, codec):
            calls.append(tuple(frames) if frames else None)
            with open(path, "wb") as fh:
                fh.write(b"x")

        def download(url, path):
            downloads.append(url)
            with open(path, "wb") as fh:
                fh.write(b"old")
        uploads = []
        with mock.patch.object(config, "FANOUT_PARTS", 2), \
                mock.patch.object(fanout, "_submit", lambda p: "j"), \
                mock.patch.object(fanout, "_status", lambda jid: {"status": "FAILED", "output": {}}), \
                mock.patch.object(fanout, "_cancel", lambda jid: None), \
                mock.patch.object(fanout.storage, "broker_enabled", return_value=True), \
                mock.patch.object(fanout.storage, "broker_read_url", lambda b, p, pr, j: f"https://s/{p}"), \
                mock.patch.object(fanout.storage, "broker_upload",
                                  side_effect=lambda local, b, obj, pr, j, read_ttl=60: uploads.append(obj) or "u"), \
                mock.patch.object(fanout.storage, "download", download), \
                mock.patch.object(fanout.subprocess, "run", lambda *a, **k: None), \
                mock.patch.object(fanout.renderer, "finalize", lambda *a, **k: {}), \
                mock.patch.object(fanout.time, "sleep", lambda s: None):
            fanout.render(doc, os.path.join(work, "final.mp4"), parent_job_id="p1", project_id="x",
                          bucket="b", work=work, report=lambda *a, **k: None,
                          render_local=render_local, previous=previous)
        return media.LAST_STATS["render_manifest"], uploads

    def test_only_the_chunk_whose_scenes_changed_is_rendered_again(self):
        work = tempfile.mkdtemp()
        doc = _doc()
        calls, downloads = [], []
        manifest, uploads = self._render(doc, work, None, calls, downloads)
        self.assertEqual(len(manifest["chunks"]), 2)
        self.assertEqual(sorted(c for c in calls if c), [(0, 269), (270, 539)])   # both chunks
        self.assertIn(None, calls)                                                # and the audio pass
        self.assertTrue(all(c.get("storage") for c in manifest["chunks"]))
        self.assertEqual(manifest["reused"], 0)

        # Replace the last scene's clip: only the second chunk changes.
        doc2 = _doc()
        doc2["scenes"][2]["media"] = {"type": "video", "url": "https://x/new.mp4?token=1",
                                      "storage": {"bucket": "b", "path": "projects/x/media/s0002.mp4"}}
        calls2, downloads2 = [], []
        manifest2, _ = self._render(doc2, tempfile.mkdtemp(), manifest, calls2, downloads2)
        self.assertEqual(sorted(c for c in calls2 if c), [(270, 539)])
        self.assertEqual(len(downloads2), 1)
        self.assertEqual(manifest2["reused"], 1)
        self.assertEqual(manifest2["chunks"][0]["hash"], manifest["chunks"][0]["hash"])
        self.assertNotEqual(manifest2["chunks"][1]["hash"], manifest["chunks"][1]["hash"])

    def test_a_resigned_url_is_not_a_change_but_new_timing_is(self):
        doc = _doc()
        h = fanout.chunk_hash(doc, 0, 269)
        doc["scenes"][0]["media"]["url"] = "https://x/a.mp4?token=other"
        self.assertEqual(fanout.chunk_hash(doc, 0, 269), h)
        doc["scenes"][0]["durationInFrames"] = 150
        self.assertNotEqual(fanout.chunk_hash(doc, 0, 269), h)


if __name__ == "__main__":
    unittest.main()
