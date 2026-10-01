"""
The quality gate (src/quality.py): every render is checked before a frame is
drawn, and what is wrong is repaired before anyone sees the video - then said,
in doc.meta.quality, the job result and the job's events.

Offline: the media is synthetic (ffmpeg lavfi clips, broken and tiny stills),
R2 and every web link answer through fakes, and the fallback ladder is mocked
where a test needs it to find something. Regression tests for each thing that
went wrong on 2026-10-01 are marked "Regression".
"""
import copy
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, events, gapfill, quality, r2, templates, timeline  # noqa: E402
from src.media import MediaAsset  # noqa: E402

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
MEDIA = ""          # synthetic files shared by every test (setUpModule)


def _ff(*args) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


def _clip(name: str, seconds: float, size: str = "160x90") -> str:
    path = os.path.join(MEDIA, name)
    if not os.path.isfile(path):
        _ff("-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", path)
    return path


def _still(name: str, w: int, h: int) -> str:
    path = os.path.join(MEDIA, name)
    if not os.path.isfile(path):
        _ff("-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:d=1", "-frames:v", "1", path)
    return path


def setUpModule():
    global MEDIA
    MEDIA = tempfile.mkdtemp(prefix="qa_media_")


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


def scene(i: int, media: dict, seconds: float = 3.0, fps: int = 30, **extra) -> dict:
    s = {"id": f"s{i:04d}", "startFrame": int(i * seconds * fps), "durationInFrames": int(seconds * fps),
         "text": f"Lake Powell dropped again in line {i}", "transition": "none", "motion": "none",
         "media": media, "words": [], "semanticMetadata": {"subject": "Lake Powell", "subjectType": "place"}}
    s.update(extra)
    return s


def video(url: str, clip: float = None) -> dict:
    m = {"type": "video", "url": url, "source": "youtube"}
    if clip:
        m["clipSeconds"] = clip
    return m


def image(url: str) -> dict:
    return {"type": "image", "url": url, "source": "web_image"}


EMPTY = {"type": "color", "url": "", "source": "none"}


def doc_of(scenes, fps: int = 30, narration: str = "") -> dict:
    total = sum(int(s["durationInFrames"]) for s in scenes)
    return {"fps": fps, "width": 640, "height": 360, "durationInFrames": total,
            "audio": {"url": narration or _narration(), "volume": 1}, "bgm": None,
            "captions": {"enabled": False, "position": "bottom", "accent": "#d6a83c", "fontFamily": "Inter"},
            "scenes": scenes, "overlays": [], "meta": {"warnings": []}}


def _narration() -> str:
    path = os.path.join(MEDIA, "vo.wav")
    if not os.path.isfile(path):
        if FFMPEG:
            _ff("-f", "lavfi", "-i", "sine=f=200:d=1", path)
        else:
            with open(path, "wb") as fh:
                fh.write(b"RIFF" + bytes(2000))
    return path


class Resp:
    """A requests response as far as the gate reads one."""

    def __init__(self, code=206, body=b"\x00\x00\x00\x18ftypisom" + bytes(4000), headers=None, total=None):
        self.status_code = code
        self.body = body
        self.headers = dict(headers or {})
        if total is not None:
            self.headers.setdefault("Content-Range", f"bytes 0-4095/{total}")
        self.content = body

    def iter_content(self, n):
        yield self.body[:n]

    def close(self):
        pass


def _offline_quality():
    """The gate's own settings for a test: quick, no generated pictures, no AI graphics."""
    return mock.patch.multiple(config, QUALITY_HTTP_TIMEOUT=2, QUALITY_AUDIT_SECONDS=60, ANIMATION_FILL=False,
                               QUALITY_REPAIR_GENERATED=False)


class _Ctx:
    """quality.CONTEXT for one test, cleared after."""

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        quality.set_context(**self.kw)
        return self

    def __exit__(self, *exc):
        quality.reset()
        gapfill.reset()
        return False


# --------------------------------------------------------------------------- #
# R2: signed links and our own objects
# --------------------------------------------------------------------------- #

class SignedLinks(unittest.TestCase):
    def test_the_presign_reproduces_awss_documented_example(self):
        # docs.aws.amazon.com: "Authenticating Requests: Using Query Parameters (AWS Signature Version 4)".
        url = r2._presign_url("GET", "examplebucket.s3.amazonaws.com", "/test.txt", "us-east-1",
                              "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                              datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc), 86400)
        self.assertTrue(url.endswith("X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"))
        self.assertIn("X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request", url)

    def test_our_objects_get_a_signed_s3_link_and_other_links_none(self):
        with mock.patch.multiple(config, R2_ACCOUNT_ID="acct", R2_ACCESS_KEY_ID="AK", R2_SECRET_ACCESS_KEY="SK",
                                 R2_BUCKET="videos", R2_PUBLIC_BASE="https://pub-1.r2.dev",
                                 R2_LIBRARY_BUCKET="lib", R2_LIBRARY_PUBLIC_BASE="https://pub-2.r2.dev"):
            self.assertEqual(r2.locate("https://pub-1.r2.dev/projects/p/media/s0001-ab.mp4"),
                             ("videos", "projects/p/media/s0001-ab.mp4"))
            self.assertEqual(r2.locate("https://pub-2.r2.dev/clips/a%20b.mp4?x=1"), ("lib", "clips/a b.mp4"))
            self.assertIsNone(r2.locate("https://example.org/a.mp4"))
            src = quality._probe_source("https://pub-1.r2.dev/projects/p/media/s0001-ab.mp4")
        self.assertTrue(src.startswith("https://acct.r2.cloudflarestorage.com/videos/projects/p/media/s0001-ab.mp4?"))
        self.assertIn("X-Amz-Signature=", src)          # ffprobe reads through the S3 API, not the public link


# --------------------------------------------------------------------------- #
# Can the renderer load it?
# --------------------------------------------------------------------------- #

class Reach(unittest.TestCase):
    R2 = dict(R2_ACCOUNT_ID="acct", R2_ACCESS_KEY_ID="AK", R2_SECRET_ACCESS_KEY="SK", R2_BUCKET="videos",
              R2_PUBLIC_BASE="https://pub-1.r2.dev")

    def test_our_r2_objects_are_asked_through_the_s3_api(self):
        seen = []

        def head(url, headers=None, timeout=None):
            seen.append(url)
            return Resp(200, headers={"Content-Length": "4200000", "Content-Type": "video/mp4"})
        with mock.patch.multiple(config, **self.R2), mock.patch.object(quality.requests, "head", side_effect=head), \
                mock.patch.object(quality.requests, "get", side_effect=AssertionError("not the public link")):
            got = quality.reach("https://pub-1.r2.dev/projects/p/media/s1.mp4", "video")
        self.assertTrue(got.ok)
        self.assertEqual(got.size, 4200000)
        self.assertEqual(seen, ["https://acct.r2.cloudflarestorage.com/videos/projects/p/media/s1.mp4"])

    def test_a_missing_r2_object_is_unreachable_and_a_5xx_is_asked_again(self):
        with mock.patch.multiple(config, **self.R2), \
                mock.patch.object(quality.requests, "head", return_value=Resp(404)), mock.patch.object(quality.time, "sleep"):
            got = quality.reach("https://pub-1.r2.dev/projects/p/media/s1.mp4", "video")
        self.assertFalse(got.ok)
        self.assertFalse(got.reached)
        self.assertIn("404", got.why)
        answers = [Resp(503), Resp(200, headers={"Content-Length": "90000", "Content-Type": "video/mp4"})]
        with mock.patch.multiple(config, **self.R2), \
                mock.patch.object(quality.requests, "head", side_effect=answers), mock.patch.object(quality.time, "sleep"):
            self.assertTrue(quality.reach("https://pub-1.r2.dev/projects/p/media/s1.mp4", "video").ok)

    def test_keys_that_cannot_read_the_bucket_fall_back_to_the_public_link(self):
        with mock.patch.multiple(config, **self.R2), \
                mock.patch.object(quality.requests, "head", return_value=Resp(403)), \
                mock.patch.object(quality.requests, "get", return_value=Resp(206, total=90000)) as get:
            self.assertTrue(quality.reach("https://pub-1.r2.dev/projects/p/media/s1.mp4", "video").ok)
        get.assert_called_once()

    def test_other_links_answer_a_small_range_get(self):
        with mock.patch.object(quality.requests, "get", return_value=Resp(206, total=5_000_000)) as get:
            got = quality.reach("https://cdn.example/clip.mp4", "video")
        self.assertTrue(got.ok)
        self.assertEqual(got.size, 5_000_000)
        self.assertEqual(get.call_args.kwargs["headers"]["Range"], "bytes=0-4095")

    def test_an_error_page_a_stub_and_a_404_are_not_files(self):
        page = Resp(200, body=b"<!DOCTYPE html><html>Access denied</html>", headers={"Content-Type": "text/html"})
        with mock.patch.object(quality.requests, "get", return_value=page):
            self.assertIn("web page", quality.reach("https://cdn.example/clip.mp4", "video").why)
        stub = Resp(206, body=b"\x00" * 262, total=262)            # the 262-byte empty downloads
        with mock.patch.object(quality.requests, "get", return_value=stub):
            self.assertIn("empty", quality.reach("https://cdn.example/clip.mp4", "video").why)
        with mock.patch.object(quality.requests, "get", return_value=Resp(404)) as get:
            got = quality.reach("https://cdn.example/clip.mp4", "video", tries=3)
        self.assertFalse(got.reached)
        self.assertEqual(get.call_count, 1)                         # a 4xx is an answer: never asked again

    def test_a_timeout_is_asked_again(self):
        answers = [quality.requests.Timeout(), Resp(206, total=90000)]
        with mock.patch.object(quality.requests, "get", side_effect=answers), mock.patch.object(quality.time, "sleep"):
            self.assertTrue(quality.reach("https://cdn.example/clip.mp4", "video").ok)

    def test_a_file_that_is_not_on_this_machine_is_unreachable(self):
        got = quality.reach(os.path.join(tempfile.gettempdir(), "no-such-pod", "s0003.mp4"), "video")
        self.assertFalse(got.ok)
        self.assertIn("not on this machine", got.why)
        self.assertFalse(quality.reach("blob:https://app/1234", "image").ok)
        self.assertTrue(quality.reach("data:image/png;base64,AAAA", "image").ok)


# --------------------------------------------------------------------------- #
# Clips must cover their scenes; stills must decode
# --------------------------------------------------------------------------- #

@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class Coverage(unittest.TestCase):
    def test_the_rate_rule_matches_the_renderer(self):
        self.assertEqual(quality.play_rate(0, 4.0), 1.0)            # no length in the document: 1x
        self.assertAlmostEqual(quality.play_rate(3.0, 4.0), 0.75)   # slowed just enough
        self.assertEqual(quality.play_rate(1.5, 4.0), 0.6)          # never under 0.6x
        self.assertEqual(quality.play_rate(6.0, 4.0), 1.0)

    def test_a_clip_that_would_freeze_is_retimed_or_replaced(self):
        short = _clip("short_1_5.mp4", 1.5)
        two = _clip("two.mp4", 2.0)
        four = _clip("four.mp4", 4.0)
        doc = doc_of([scene(0, video(four, 4.0)),
                      scene(1, video(short, 1.5), seconds=4.0),        # 1.5 s for 4 s: freezes 1.5 s even at 0.6x
                      scene(2, video(two), seconds=3.0)])              # no length: 1x would freeze 1 s
        for k, s in enumerate(doc["scenes"]):
            s["startFrame"] = sum(int(x["durationInFrames"]) for x in doc["scenes"][:k])
        doc["durationInFrames"] = sum(int(s["durationInFrames"]) for s in doc["scenes"])
        work = tempfile.mkdtemp()
        with _offline_quality(), _Ctx():
            gate = quality.Gate(doc, work)
            n = gate.before_render()
        self.assertEqual(n, 1)
        self.assertEqual(gate.found["short"], 1)
        self.assertEqual(gate.fixed["timing"], 1)
        s1 = next((s for s in doc["scenes"] if s["id"] == "s0001"), None)
        self.assertTrue(s1 is None or s1["media"].get("url") != short)   # held over, or a new picture
        two_scene = next(s for s in doc["scenes"] if s["id"] == "s0002")
        self.assertAlmostEqual(two_scene["media"]["clipSeconds"], 2.0, delta=0.05)   # slowed to fill, not frozen
        timeline.validate(doc, require_media=True)

    def test_the_crossfade_frames_count(self):
        clip3 = _clip("three.mp4", 3.0)
        scenes = [scene(0, video(clip3, 3.0)), scene(1, video(_clip("four.mp4", 4.0), 4.0), transition="crossfade")]
        self.assertAlmostEqual(quality.scene_need(scenes, 0, 30), 3.5)      # plays on under the dissolve
        self.assertAlmostEqual(quality.scene_need(scenes, 1, 30), 3.0)

    def test_stills_must_decode_and_not_be_tiny(self):
        page = os.path.join(MEDIA, "page.jpg")
        with open(page, "wb") as fh:
            fh.write(b"<html><body>404 Not Found</body></html>" + b" " * 3000)
        tiny = _still("tiny.png", 40, 30)
        good = _still("good.jpg", 1280, 720)
        doc = doc_of([scene(0, image(good)), scene(1, image(page)), scene(2, image(tiny)),
                      scene(3, video(_clip("four.mp4", 4.0), 4.0))])
        with _offline_quality(), _Ctx():
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertEqual((gate.found["broken"], gate.found["tiny"]), (1, 1))
        urls = [s["media"].get("url") for s in doc["scenes"]]
        self.assertIn(good, urls)
        self.assertNotIn(page, urls)
        self.assertNotIn(tiny, urls)

    def test_a_remote_still_is_fetched_once_and_the_render_reuses_that_copy(self):
        good = _still("good.jpg", 1280, 720)
        with open(good, "rb") as fh:
            body = fh.read()
        doc = doc_of([scene(0, image("https://cdn.example/photo.jpg")), scene(1, video(_clip("four.mp4", 4.0), 4.0))])
        work = tempfile.mkdtemp()
        with _offline_quality(), _Ctx(), \
                mock.patch.object(quality.requests, "get", side_effect=lambda url, **kw: Resp(200, body=body, total=len(body))):
            gate = quality.Gate(doc, work)
            gate.before_render()
        self.assertIn("https://cdn.example/photo.jpg", gate.fetched)
        with mock.patch.object(handler.storage, "download", side_effect=AssertionError("downloaded twice")):
            dropped = handler._sanitize_stills(doc, work, fetched=gate.fetched)
        self.assertEqual(dropped, 0)
        self.assertTrue(os.path.isfile(doc["scenes"][0]["media"]["url"]))


# --------------------------------------------------------------------------- #
# Repairs: the ladder, never a repeat, never an empty scene
# --------------------------------------------------------------------------- #

def _fresh(i: int) -> MediaAsset:
    """A new clip the ladder found for scene i: its own file and its own video."""
    path = os.path.join(MEDIA, f"fresh_{i:03d}.mp4")
    if not os.path.isfile(path):
        shutil.copy(_clip("four.mp4", 4.0), path)
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=FRESH{i:06d}",
                      local_path=path, moment_key=f"yt:FRESH{i:06d}@1",
                      review_reason="From the clip library - the footage search ran out of time for this line")


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class Repairs(unittest.TestCase):
    def setUp(self):
        events.start_job("qa-test", "")

    def test_regression_lake_powell_empty_end_scenes_and_repeats_are_all_replaced(self):
        # 2026-10-01: the 159-scene Lake Powell build ended with its last 23
        # scenes empty and 47 scenes repeating clips. Scaled down: 30 scenes,
        # the last 8 empty, 6 repeating earlier scenes' files.
        clips = [os.path.join(MEDIA, f"orig_{i:03d}.mp4") for i in range(16)]
        for p in clips:
            if not os.path.isfile(p):
                shutil.copy(_clip("four.mp4", 4.0), p)
        scenes = []
        for i in range(30):
            if i >= 22:
                media = dict(EMPTY)
            elif i in (16, 17, 18, 19, 20, 21):
                media = video(clips[i - 16], 4.0)                       # the same file as scene i-16
            else:
                media = video(clips[i], 4.0)
            scenes.append(scene(i, media))
        doc = doc_of(scenes)
        asked = {}

        def ladder(jobs, results, work, **kw):
            asked.update(indices=list(kw["indices"]), used=kw["used"])
            for i in kw["indices"]:
                results[i] = _fresh(i)
            return {"asked": len(kw["indices"]), "library": len(kw["indices"]), "reserve": 0, "still": 0,
                    "generated": 0, "left": 0}
        with _offline_quality(), _Ctx(ladder=True), mock.patch.object(gapfill, "fill_empty", side_effect=ladder):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            repaired = gate.before_render()
        self.assertEqual(repaired, 14)
        self.assertEqual((gate.found["empty"], gate.found["repeat"]), (8, 6))
        self.assertEqual(sorted(asked["indices"]), list(range(16, 30)))
        self.assertEqual([s for s in doc["scenes"] if gapfill._empty(s)], [])           # zero empty
        self.assertEqual(gapfill.find_repeats(doc), [])                                 # zero repeats
        timeline.validate(doc, require_media=True)
        report = gate.finish()
        self.assertEqual(report["summary"], "Quality check: 30/30 scenes OK, 14 clips replaced")
        self.assertEqual(report["fixed"]["replaced"], 14)
        self.assertTrue(all(r["how"] == "a library clip" for r in report["repairs"]))
        rows = [e for e in events._EVENTS if e["stage"] == "quality"]
        self.assertTrue(any(e["event"] == "repaired" and e.get("scene_index") == 16 for e in rows))
        self.assertEqual(rows[-1]["event"], "summary")

    def test_the_failed_shot_and_every_moment_of_its_video_are_never_taken_again(self):
        bad = "https://cdn.example/dead.mp4"
        doc = doc_of([scene(0, video(_clip("four.mp4", 4.0), 4.0)),
                      scene(1, video(bad, 4.0)),
                      scene(2, video(_clip("three.mp4", 3.0), 3.0))])
        doc["scenes"][1]["semanticMetadata"].update(assetId="yt:DEADVIDEO01@4",
                                                    sourceUrl="https://www.youtube.com/watch?v=DEADVIDEO01&t=40")
        seen = {}

        def ladder(jobs, results, work, **kw):
            used = kw["used"]
            same_video = gapfill.Shot(video="yt:DEADVIDEO01", start=400.0)     # another moment, far away
            seen["why"] = used.why_not(1, same_video)
            results[1] = _fresh(1)
            return {}
        with _offline_quality(), _Ctx(ladder=True), mock.patch.object(gapfill, "fill_empty", side_effect=ladder), \
                mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            quality.Gate(doc, tempfile.mkdtemp()).before_render()
        self.assertIn("same moment", seen["why"])
        self.assertEqual(doc["scenes"][1]["media"]["url"], _fresh(1).local_path)
        self.assertIn("quality check replaced", doc["scenes"][1]["reviewReason"])

    def test_without_the_ladder_a_broken_scene_is_held_over_or_shown_as_text_never_empty(self):
        doc = doc_of([scene(0, video(_clip("three.mp4", 3.0), 3.0)),
                      scene(1, video("https://cdn.example/dead.mp4", 3.0)),
                      scene(2, video(_fresh(300).local_path, 4.0))])
        with _offline_quality(), _Ctx(), mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertEqual([s for s in doc["scenes"] if gapfill._empty(s)], [])
        self.assertNotIn("https://cdn.example/dead.mp4", [s["media"].get("url") for s in doc["scenes"]])
        self.assertEqual(gate.fixed["held"] + gate.fixed["text"], 1)
        timeline.validate(doc, require_media=True)

    def test_a_line_with_nothing_left_becomes_a_text_graphic_not_a_card_that_fails_the_render(self):
        # gapfill's last resort leaves such a scene "color" with a text card over
        # it - and timeline.validate(require_media=True) then fails the render.
        anim = {"type": "animation", "url": "", "source": "template"}
        doc = doc_of([scene(0, dict(anim), animation={"type": "stat", "value": 3}),
                      scene(1, dict(EMPTY)),
                      scene(2, dict(anim), animation={"type": "stat", "value": 4})])
        with _offline_quality(), _Ctx():
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        s = doc["scenes"][1]
        self.assertEqual(s["media"]["type"], "animation")
        self.assertEqual(s["animation"]["template"], "TEXT_SENTENCE_HIGHLIGHT_V1")
        self.assertEqual([o for o in doc["overlays"] if o.get("type") == "highlight"], [])  # words shown once
        self.assertEqual(gate.fixed["text"], 1)
        timeline.validate(doc, require_media=True)
        self.assertIn("1 line shown as a graphic", gate.summary())


# --------------------------------------------------------------------------- #
# Regressions: overlays, thumbnails, an outage, the music
# --------------------------------------------------------------------------- #

@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class Regressions(unittest.TestCase):
    def setUp(self):
        events.start_job("qa-test", "")

    def test_regression_split_panels_never_show_an_empty_slot(self):
        # 2026-10-01, overlay 46 of the Lake Powell video: a split-panel look
        # with empty slots. A look whose pictures cannot load gets the story's
        # own pictures or goes; a split that lost a photo is its labels again.
        photo = _still("panel.jpg", 1280, 720)
        clip = _clip("four.mp4", 4.0)
        scenes = [scene(i, image(_still(f"panel_{i}.jpg", 1280, 720)) if i % 2 else video(clip if i == 0 else
                  _fresh(i).local_path, 4.0)) for i in range(6)]
        doc = doc_of(scenes)
        dead = "https://cdn.example/gone.jpg"
        triptych = next(t["id"] for t in templates.all_templates()
                        if (t.get("defaults") or {}).get("variant") == "pb-triptych")
        doc["overlays"] = [
            {"type": "motion", "template": triptych, "variant": "pb-triptych", "text": "Lake Powell",
             "startFrame": 90, "durationInFrames": 90, "media": [{"type": "image", "url": dead, "source": "web"}],
             "mediaFrom": ["s9999"]},                                          # a scene that is gone
            {"type": "split", "template": "CMP_SPLIT_V1", "text": "then and now", "startFrame": 200,
             "durationInFrames": 60, "items": [{"label": "1999"}, {"label": "2026"}],
             "media": [{"type": "image", "url": photo, "source": "web"}, {"type": "image", "url": dead,
                                                                          "source": "web"}]},
            {"type": "photo-card", "template": "PHOTO_PIP_V1", "text": "Glen Canyon Dam", "startFrame": 300,
             "durationInFrames": 60, "media": [{"type": "image", "url": dead, "source": "web"}]},
        ]
        with _offline_quality(), _Ctx(), mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        kinds = [o.get("type") for o in doc["overlays"]]
        self.assertNotIn("photo-card", kinds)                        # an empty photo window: left out
        self.assertIn("label-boxes", kinds)                          # the split shows its two labels
        for ov in doc["overlays"]:
            self.assertNotIn(dead, [m.get("url") for m in ov.get("media") or []])
            pics = quality.look_pictures(ov, doc["scenes"])
            self.assertTrue(pics is None or len(pics) >= 1, ov)      # every image look has a picture
        timeline.validate(doc, require_media=True)

    def test_regression_dead_thumbnails_never_reach_the_render_chunks(self):
        # 2026-10-01: chunk renders hit 404s on thumbnails that were files on
        # the pod, and the render fell back to one machine (45 minutes).
        clip = _clip("four.mp4", 4.0)
        scenes = [scene(i, video(clip if i == 0 else _fresh(i).local_path, 4.0)) for i in range(3)]
        scenes[0]["media"]["thumbnail"] = os.path.join(tempfile.gettempdir(), "dead-pod", "thumb_s0000.jpg")
        scenes[1]["media"]["thumbnail"] = "https://cdn.example/thumbs/s1.jpg"
        scenes[2]["media"]["thumbnail"] = _still("thumb_ok.jpg", 320, 180)
        dead = [scenes[0]["media"]["thumbnail"], scenes[1]["media"]["thumbnail"]]
        doc = doc_of(scenes)
        with _offline_quality(), _Ctx(), mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertEqual(gate.fixed["thumbnail"], 2)
        stills = [s["media"].get("thumbnail") for s in doc["scenes"]]
        self.assertFalse(set(dead) & set(stills))                       # no dead still reaches a chunk
        self.assertEqual(stills[2], _still("thumb_ok.jpg", 320, 180))
        # The clips on this disk get a real frame instead, for the looks and backdrops.
        self.assertTrue(all(isinstance(p, str) and os.path.isfile(p) for p in stills), stills)

    def test_regression_scenes_whose_upload_failed_in_an_outage_are_replaced_at_render(self):
        # Uploads failed during an app database outage: the saved timeline kept
        # files on the pod that made them. Pressing Render on another machine.
        scenes = [scene(i, video(_fresh(100 + i).local_path, 4.0)) for i in range(6)]
        for i in (2, 3, 5):
            scenes[i]["media"] = video(f"/tmp/work/pod-old/s{i:04d}.mp4", 4.0)
            scenes[i]["reviewRequired"] = True
            scenes[i]["reviewReason"] = "Media could not be saved; re-source before rendering"
        doc = doc_of(scenes)
        loads = []

        def ladder(jobs, results, work, **kw):
            for i in kw["indices"]:
                results[i] = _fresh(i)
            return {}
        with _offline_quality(), _Ctx(ladder=True, story={"kind": "explainer"},
                                      library_loader=lambda: loads.append(1) or None), \
                mock.patch.object(gapfill, "fill_empty", side_effect=ladder), \
                mock.patch("src.vision.set_story"), mock.patch("src.media.set_story_kind"):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertEqual(gate.found["unreachable"], 3)
        self.assertEqual(gate.fixed["replaced"], 3)
        self.assertEqual(loads, [1])                                   # the project's library, loaded once
        self.assertFalse(any("/tmp/work/pod-old" in s["media"]["url"] for s in doc["scenes"]))
        self.assertIn("3 clips replaced", gate.summary())

    def test_regression_a_missing_music_file_never_fails_the_render(self):
        clip = _clip("four.mp4", 4.0)
        base = [scene(0, video(clip, 4.0))]
        doc = doc_of(copy.deepcopy(base))
        doc["bgm"] = {"url": "bgm://investigative", "volume": 0.2}      # renamed bed: the renderer maps it
        with _offline_quality(), _Ctx():
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertEqual(doc["bgm"]["url"], "bgm://investigative-v5")
        self.assertEqual(gate.found["music"], 0)
        doc = doc_of(copy.deepcopy(base))
        doc["bgm"] = {"url": "bgm://documentary-12min", "volume": 0.2}  # a removed bed: its 404 failed a render
        with _offline_quality(), _Ctx():
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertTrue(quality._bgm_file(doc["bgm"]["url"][len("bgm://"):]))
        self.assertEqual(gate.fixed["music"], 1)
        doc = doc_of(copy.deepcopy(base))
        doc["bgm"] = {"url": "https://cdn.example/my-track.mp3", "volume": 0.2}
        doc["sfx"] = [{"name": "whoosh-that-was-renamed", "startFrame": 10, "volume": 0.3}]
        with _offline_quality(), _Ctx(), mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            gate = quality.Gate(doc, tempfile.mkdtemp())
            gate.before_render()
        self.assertTrue(doc["bgm"]["url"].startswith("bgm://"))
        self.assertEqual(doc["sfx"], [])
        self.assertIn("music replaced", gate.summary())

    def test_a_narration_link_that_answers_404_stops_the_render_with_the_reason(self):
        doc = doc_of([scene(0, video(_clip("four.mp4", 4.0), 4.0))], narration="https://sb.example/vo.mp3")
        with _offline_quality(), _Ctx(), mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            with self.assertRaises(quality.NarrationMissing) as ctx:
                quality.Gate(doc, tempfile.mkdtemp()).before_render()
        self.assertIn("upload the voiceover again", str(ctx.exception))


# --------------------------------------------------------------------------- #
# The handler: context, report, progress
# --------------------------------------------------------------------------- #

class HandlerWiring(unittest.TestCase):
    def test_an_editor_render_repairs_with_the_ladder_story_and_library(self):
        clip = "https://pub.example/s0.mp4"
        doc = doc_of([scene(0, video(clip, 4.0)), scene(1, dict(EMPTY))], narration="https://sb.example/vo.mp3")
        doc["meta"]["story"] = {"kind": "explainer", "event": "Lake Powell"}
        seen = {}

        def fake_render(d, inp, work, report, split=False):
            seen.update(quality.CONTEXT)
            self.assertEqual(d["scenes"][1]["media"]["type"], "color")   # the gate's to fill, ladder first
            return {"video_url": "u", "duration": 6, "quality": {"summary": "Quality check: 2/2 scenes OK",
                                                                 "repairs": [{"problem": "empty"}]}}
        with mock.patch.object(handler, "do_render", side_effect=fake_render), \
                mock.patch.object(handler, "_fill_missing_media", side_effect=AssertionError("last resort first")), \
                mock.patch.object(handler.fanout, "render_enabled", return_value=False), \
                mock.patch.object(handler.storage, "patch_project"), mock.patch.object(handler.ledger, "save"):
            out = handler.handler({"id": "job-q", "input": {"action": "render", "project_id": "p1", "timeline": doc}})
        self.assertTrue(out["ok"], out)
        self.assertTrue(seen["ladder"])
        self.assertEqual(seen["story"]["event"], "Lake Powell")
        self.assertTrue(callable(seen["library_loader"]))
        self.assertEqual(out["quality"]["summary"], "Quality check: 2/2 scenes OK")
        self.assertEqual(out["filledScenes"], 1)
        self.assertEqual(quality.CONTEXT, {})                             # nothing outlives the job

    def test_a_build_keeps_the_report_with_its_timeline(self):
        from tests.test_pipeline import build_doc
        doc = build_doc(n=2, seconds=3.0)
        seen = {}

        line = "Quality check: 2/2 scenes OK, 1 clip replaced"
        repairs = [{"scene": "s0001", "problem": "unreachable", "detail": "the link answers HTTP 404",
                    "how": "a library clip"},
                   {"scene": "s0000", "problem": "timing", "detail": "would have frozen", "how": "slowed"}]

        def fake_render(d, inp, work, report, split=False):
            seen.update(quality.CONTEXT)
            return {"video_url": "u", "duration": 6, "quality": {"summary": line, "repairs": repairs}}
        with mock.patch.object(handler, "do_plan", return_value=doc), \
                mock.patch.object(handler, "_require_youtube"), mock.patch.object(handler, "_require_ai_credit"), \
                mock.patch.object(handler, "do_render", side_effect=fake_render), \
                mock.patch.object(handler, "publish_media"), mock.patch.object(handler.storage, "patch_project"):
            out = handler.handler({"id": "job-b", "input": {"action": "build", "project_id": "p1"}})
        self.assertTrue(out["ok"], out)
        self.assertTrue(seen["plan"] and seen["ladder"])
        self.assertEqual(out["timeline"]["meta"]["quality"]["summary"], line)
        self.assertEqual(out["quality"]["summary"], line)
        saved = {s["id"]: s for s in out["timeline"]["scenes"]}
        self.assertIn("quality check replaced this scene", saved["s0001"]["reviewReason"])   # the editor sees it
        self.assertNotIn("quality check", saved["s0000"].get("reviewReason") or "")        # a retimed clip is not

    def test_the_one_liner_rides_on_every_later_progress_update(self):
        sent = []
        job = {"id": "job-p"}
        with mock.patch.object(handler.runpod.serverless, "progress_update", side_effect=lambda j, u: sent.append(u)), \
                mock.patch.object(handler.Reporter, "SERVERLESS", True):
            rep = handler.Reporter("", job=job)
            gate = quality.Gate(doc_of([scene(0, video("/x/a.mp4", 4.0))], narration="/x/vo.wav"), tempfile.mkdtemp(),
                                rep)
            line = gate.finish()["summary"]
            rep("Uploading video", 91)
            rep.finish()
        self.assertEqual(sent[-1]["quality"], line)
        self.assertEqual(sent[-1]["status"], "Uploading video")


if __name__ == "__main__":
    unittest.main()
