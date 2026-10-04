"""
Cloudflare-only storage (R2_ONLY) and the links that get SAVED.

storage.broker_upload returns a PRESIGNED R2 link under R2_ONLY: it lives 7
days at most. That is right for what is fetched and forgotten (a part's clip,
a render chunk) and wrong for anything written into the timeline (scene_data)
or the library: with no storage reference nothing can re-sign it, so a saved
video's scenes would go dark a week later. What is saved must be the public
R2 link (r2.public_url), which never expires.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, library, r2, storage  # noqa: E402

R2ON = {"R2_ACCOUNT_ID": "acct", "R2_ACCESS_KEY_ID": "AK", "R2_SECRET_ACCESS_KEY": "SK",
        "R2_BUCKET": "thumbgenius-videos", "R2_PUBLIC_BASE": "https://pub-v.r2.dev"}
PRESIGNED = "https://acct.r2.cloudflarestorage.com/thumbgenius-videos/x?X-Amz-Signature=abc&X-Amz-Expires=604800"


def _expiring(value) -> bool:
    return isinstance(value, str) and ("X-Amz-" in value or "token=" in value)


def _walk(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    else:
        yield node


class SceneMedia(unittest.TestCase):
    def _doc(self, d):
        clip = os.path.join(d, "s0.mp4")
        open(clip, "wb").close()
        return {"meta": {"warnings": []}, "scenes": [
            {"id": "s0", "media": {"type": "video", "url": clip, "source": "youtube"}}]}

    def _publish(self, scene_media_flag):
        d = tempfile.mkdtemp()
        doc = self._doc(d)
        thumb, prev = os.path.join(d, "t.jpg"), os.path.join(d, "p.mp4")
        open(thumb, "wb").close()
        open(prev, "wb").close()
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(config, "R2_SCENE_MEDIA", scene_media_flag), \
                mock.patch.object(r2, "_put"), \
                mock.patch.object(r2, "presign", return_value=PRESIGNED) as presign, \
                mock.patch.object(storage, "_broker", side_effect=AssertionError("the app's storage was used")), \
                mock.patch.object(handler, "_thumbnail", return_value=thumb), \
                mock.patch.object(handler, "_preview_proxy", return_value=prev):
            n = handler.publish_media(doc, "p", "video-media", lambda *a, **k: None, job_id="j")
        return n, doc, presign

    def test_no_expiring_link_is_saved_in_the_timeline_even_with_the_scene_media_flag_off(self):
        # 704c854: R2_SCENE_MEDIA off + R2_ONLY sent scene files through storage.broker_upload,
        # whose presigned link (7 days at most) was written into scene_data with nothing to re-sign it.
        for flag in (True, False):
            n, doc, presign = self._publish(flag)
            self.assertEqual(n, 1)
            m = doc["scenes"][0]["media"]
            for field in ("url", "thumbnail", "previewUrl"):
                self.assertRegex(m[field], r"^https://pub-v\.r2\.dev/projects/p/(media|thumbs|preview)/s0-[0-9a-f]{12}\.",
                                 f"R2_SCENE_MEDIA={flag}: {field}")
            self.assertFalse([v for v in _walk(doc) if _expiring(v)], f"R2_SCENE_MEDIA={flag}")
            for key in ("storage", "thumbStorage", "previewStorage"):
                self.assertNotIn(key, m)
            presign.assert_not_called()

    def test_the_editors_choices_and_split_pictures_keep_permanent_links_too(self):
        d = tempfile.mkdtemp()
        alt = os.path.join(d, "alt.mp4")
        open(alt, "wb").close()
        cands = [{"rank": 2, "localPath": alt, "media": {}}]
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(config, "R2_SCENE_MEDIA", False), mock.patch.object(r2, "_put"), \
                mock.patch.object(r2, "presign", return_value=PRESIGNED), \
                mock.patch.object(handler, "_thumbnail", return_value=""), \
                mock.patch.object(handler, "_preview_proxy", return_value=""):
            handler._publish_alternatives(cands, "p", "video-media", "j", "s3", d)
            self.assertTrue(handler._scene_media_on_r2())
            url, ref = handler._put_scene_file(alt, "projects/p/split_left.jpg", "video-media", "p", "j")
        self.assertRegex(cands[0]["media"]["url"], r"^https://pub-v\.r2\.dev/projects/p/alts/")
        self.assertRegex(url, r"^https://pub-v\.r2\.dev/projects/p/split_left-[0-9a-f]{12}\.jpg$")
        self.assertIsNone(ref)

    def test_cloudflare_only_still_fails_loudly_instead_of_using_the_apps_storage(self):
        d = tempfile.mkdtemp()
        clip = os.path.join(d, "a.mp4")
        open(clip, "wb").close()
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(config, "R2_SCENE_MEDIA", False), \
                mock.patch.object(r2, "upload", side_effect=RuntimeError("R2 upload failed: HTTP 403")), \
                mock.patch.object(storage, "_broker", side_effect=AssertionError("the app's storage was used")), \
                mock.patch.object(storage, "upload_to_supabase", side_effect=AssertionError("the app's storage")):
            with self.assertRaises(RuntimeError):
                handler._put_scene_file(clip, "projects/p/media/a.mp4", "video-media", "p", "j")

    def test_without_cloudflare_only_the_flag_still_means_the_apps_storage(self):
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", False), \
                mock.patch.object(config, "R2_SCENE_MEDIA", False):
            self.assertFalse(handler._scene_media_on_r2())
        with mock.patch.multiple(config, **{**R2ON, "R2_BUCKET": ""}), mock.patch.object(config, "R2_ONLY", True):
            self.assertFalse(handler._scene_media_on_r2())           # R2 not configured: nothing changes


class TemporaryLinks(unittest.TestCase):
    def test_a_parts_clip_and_a_chunk_may_use_a_presigned_link_they_are_fetched_and_forgotten(self):
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(r2, "_put") as put:
            url = storage.broker_upload(__file__, "video-media", "projects/p/parts/j/0004.mp4", "p", "j",
                                        read_ttl=60 * 60 * 6)
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn("X-Amz-Expires=21600", url)
        self.assertEqual(put.call_args.args[0], "projects/p/parts/j/0004.mp4")

    def test_a_presigned_link_is_never_asked_to_outlive_seven_days(self):
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(r2, "_put"):
            url = storage.broker_upload(__file__, "video-media", "projects/p/x.mp4", "p", "j",
                                        read_ttl=60 * 60 * 24 * 30)
        self.assertIn("X-Amz-Expires=604800", url)


class FinalVideo(unittest.TestCase):
    def test_the_finished_video_gets_the_public_link_and_ignores_a_supabase_upload_url(self):
        work = tempfile.mkdtemp()
        doc = {"fps": 30, "width": 640, "height": 360, "durationInFrames": 90, "scenes": [], "overlays": [],
               "audio": None, "bgm": None, "meta": {"sceneCount": 0}}

        def fake_render(d, path, **kw):
            with open(path, "wb") as fh:
                fh.write(b"v")
            if kw.get("audio_to"):
                with open(kw["audio_to"], "wb") as fh:
                    fh.write(b"RIFF")
            return path

        def fake_finalize(video, audio, out, **kw):
            with open(out, "wb") as fh:
                fh.write(b"final")
            return {}
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(config, "QUALITY_GATE", False), mock.patch.object(config, "POD_RENDER_FANOUT", False), \
                mock.patch.object(r2, "_put") as put, \
                mock.patch.object(storage, "upload_to_signed_url", side_effect=AssertionError("Supabase upload")), \
                mock.patch.object(storage, "_broker", side_effect=AssertionError("the app's storage was used")), \
                mock.patch.object(handler.timeline, "validate"), mock.patch.object(handler.timeline, "relevel_to_voice"), \
                mock.patch.object(handler.voicepolish, "for_render", return_value={}), \
                mock.patch.object(handler.grade, "prepare", return_value={}), \
                mock.patch.object(handler.renderer, "render", side_effect=fake_render), \
                mock.patch.object(handler.renderer, "finalize", side_effect=fake_finalize), \
                mock.patch.object(handler, "_keep_render"):
            out = handler.do_render(doc, {"project_id": "p", "_job_id": "j", "upload_url": "https://sb/upload?token=x",
                                          "public_url": "https://sb/public/a.mp4", "video_path": "a.mp4"},
                                    work, lambda *a, **k: None)
        self.assertEqual(out["uploadedVia"], "r2")
        self.assertRegex(out["video_url"], r"^https://pub-v\.r2\.dev/projects/p/final-\d+-[0-9a-f]{12}\.mp4$")
        self.assertFalse(_expiring(out["video_url"]))
        self.assertEqual(out["bucket"], "r2:thumbgenius-videos")
        self.assertTrue(put.call_args.args[0].startswith("projects/p/final-"))


class LibraryWithoutItsOwnBucket(unittest.TestCase):
    def test_a_clip_kept_in_the_videos_bucket_says_so_and_keeps_a_permanent_link(self):
        d = tempfile.mkdtemp()
        good = os.path.join(d, "a.mp4")
        with open(good, "wb") as fh:
            fh.write(b"x" * 10)
        doc = {"fps": 30, "scenes": [
            {"id": "s0", "durationInFrames": 180, "media": {"type": "video", "source": "youtube", "url": good},
             "semanticMetadata": {"assetId": "yt:abc@2", "sourceUrl": "https://www.youtube.com/watch?v=abc",
                                  "subject": "Lake Mead", "contentDescription": "aerial", "relevanceScore": 0.9}}]}
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_ONLY", True), \
                mock.patch.object(config, "R2_LIBRARY_BUCKET", ""), mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(library.storage, "broker_enabled", return_value=True), \
                mock.patch.object(library.storage, "broker_library_query", return_value={"ok": True, "rows": []}), \
                mock.patch.object(library.storage, "broker_upload", side_effect=AssertionError("a presigned link")), \
                mock.patch.object(r2, "_put") as put, \
                mock.patch.object(library.storage, "broker_library_upsert", return_value={"ok": True}) as ups:
            lib = library.Library.load("p", "j")
            self.assertEqual(lib.record_from_doc(doc), 1)
            self.assertTrue(lib.save())
        row = ups.call_args.args[2][0]
        # The row names the store the file is really in, and the key is link-only.
        self.assertEqual(row["storage_bucket"], "r2:thumbgenius-videos")
        self.assertRegex(row["storage_path"], r"^library/clips/yt_abc_2-[0-9a-f]{12}\.mp4$")
        self.assertEqual(put.call_args.args[0], row["storage_path"])
        entry = lib.entries[-1]
        self.assertEqual(entry["read_url"], "https://pub-v.r2.dev/" + row["storage_path"])
        self.assertFalse([v for v in _walk(row) if _expiring(v)])
        # A later job reads it back by its public link.
        with mock.patch.multiple(config, **R2ON):
            again = library._from_row({"asset_id": "yt:abc@2", "storage_bucket": row["storage_bucket"],
                                       "storage_path": row["storage_path"], "readUrl": ""})
        self.assertEqual(again["read_url"], "https://pub-v.r2.dev/" + row["storage_path"])


if __name__ == "__main__":
    unittest.main()
