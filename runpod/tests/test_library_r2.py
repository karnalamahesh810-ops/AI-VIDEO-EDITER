"""
The footage library on Cloudflare R2 (src/libstore.py, src/library.py,
src/r2.py) and scene media on R2 (handler._put_scene_file): the storage
layout, every rule of the quality gate, the maintenance pass that moves old
rows or marks them removed, the ranking for the story, and the publish path.
No network: R2, the broker and downloads are mocked.
"""
import datetime
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from src import config, library, libstore, r2, storage

R2ON = dict(R2_ACCOUNT_ID="acct123", R2_ACCESS_KEY_ID="AKID", R2_SECRET_ACCESS_KEY="secret",
            R2_BUCKET="thumbgenius-videos", R2_PUBLIC_BASE="https://pub-v.r2.dev",
            R2_LIBRARY_BUCKET="thumbgenius-library", R2_LIBRARY_PUBLIC_BASE="https://pub-lib.r2.dev",
            R2_LIBRARY_PREFIX="")
FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
H, W = libstore.H, libstore.W


def rgb(gray):
    g = np.clip(gray, 0, 255).astype(np.uint8)
    return np.stack([g, g, g], axis=-1)


def texture(seed=0, w=1400):
    r = np.random.default_rng(seed)
    small = r.integers(30, 230, (H // 4 + 1, w // 4 + 1)).astype(np.float32)
    return np.kron(small, np.ones((4, 4), np.float32))[:H, :w]


def pan(n=8, step=12, seed=0):
    """A textured scene the camera pans across: moving, sharp, no text."""
    t = texture(seed)
    return [t[:, i * step:i * step + W].copy() for i in range(n)]


GOOD_PROBE = {"width": 1920, "height": 1080, "seconds": 6.0, "codec": "h264", "ok": True}
# Real dHashes are 64-bit: small ints would sit a few bits from anything.
HA, HB, HC, HP = 0x0123456789ABCDEF, 0xFEDCBA9876543210, 0x0F1E2D3C4B5A6978, 0x5A5A5A5AA5A5A5A5


def judge(grays, probe=None, clip=None, known=None, kind="video", subject="Lake Mead", event=""):
    with mock.patch.object(libstore, "tools", return_value=True), \
            mock.patch.object(libstore, "probe", return_value=dict(probe or GOOD_PROBE)), \
            mock.patch.object(libstore, "frames", return_value=[rgb(g) for g in grays]), \
            mock.patch.object(libstore, "clip_facts", return_value=clip), \
            mock.patch("src.filters.text_page_still", return_value=False):
        return libstore.check("/x.mp4" if kind == "video" else "/x.jpg", kind=kind, subject=subject,
                              event=event, known=known)


def make_clip(path, source, seconds, size=None):
    src = source if size is None else f"{source}=s={size}:rate=15"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", str(seconds), "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", path], check=True, capture_output=True)
    return path


# --------------------------------------------------------------------------- #
# R2 helpers
# --------------------------------------------------------------------------- #

class R2Buckets(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(config, **R2ON)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_library_bucket_is_its_own_box(self):
        self.assertTrue(r2.library_enabled())
        with mock.patch.object(config, "R2_LIBRARY_PUBLIC_BASE", ""):
            self.assertFalse(r2.library_enabled())
            self.assertTrue(r2.enabled())                  # finished videos are unaffected
        ok = mock.Mock(status_code=200, text="")
        with mock.patch.object(r2.requests, "put", return_value=ok) as put:
            url = r2.upload_bytes(b"{}", "embeddings/a.json", bucket="thumbgenius-library",
                                  base="https://pub-lib.r2.dev", cache_control="public, max-age=60")
        self.assertEqual(url, "https://pub-lib.r2.dev/embeddings/a.json")
        self.assertTrue(put.call_args.args[0].startswith("https://acct123.r2.cloudflarestorage.com/thumbgenius-library/"))
        auth = put.call_args.kwargs["headers"]["Authorization"]
        self.assertIn("cache-control;content-length;content-type;host", auth)   # the cache header is signed

    def test_signature_path_names_the_bucket(self):
        when = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
        a = r2._auth_headers("PUT", "k.mp4", {}, "UNSIGNED-PAYLOAD", when, bucket="thumbgenius-library")
        b = r2._auth_headers("PUT", "k.mp4", {}, "UNSIGNED-PAYLOAD", when)
        self.assertNotEqual(a["Authorization"], b["Authorization"])
        q1 = r2._auth_headers("GET", "", {}, "x", when, query={"prefix": "clips/", "list-type": "2"})
        q2 = r2._auth_headers("GET", "", {}, "x", when, query={"list-type": "2", "prefix": "clips/"})
        self.assertEqual(q1, q2)                                    # the query is canonicalised (sorted)
        self.assertEqual(r2._query_string({"prefix": "clips/a b", "list-type": "2"}), "list-type=2&prefix=clips%2Fa%20b")

    def test_tokened_names_are_unguessable_and_keep_the_extension(self):
        a, b = r2.tokened("projects/p/media/s0001.mp4"), r2.tokened("projects/p/media/s0001.mp4")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^projects/p/media/s0001-[0-9a-f]{12}\.mp4$")
        self.assertEqual(r2.content_type("x.jpg"), "image/jpeg")
        self.assertEqual(r2.content_type("x.mp4"), "video/mp4")

    def test_head_and_list(self):
        with mock.patch.object(r2.requests, "head", return_value=mock.Mock(status_code=404)):
            self.assertIsNone(r2.head("nope", bucket="thumbgenius-library"))
        found = mock.Mock(status_code=200, headers={"Content-Length": "522", "ETag": 'W/"abc"', "Content-Type": "application/json"})
        with mock.patch.object(r2.requests, "head", return_value=found) as h:
            self.assertEqual(r2.head("k", bucket="thumbgenius-library"), {"size": 522, "etag": "abc", "type": "application/json"})
        self.assertEqual(h.call_args.kwargs["headers"]["Accept-Encoding"], "identity")
        xml = (b'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
               b'<IsTruncated>false</IsTruncated><Contents><Key>clips/a.mp4</Key><Size>10</Size></Contents>'
               b'<Contents><Key>clips/b.mp4</Key><Size>20</Size></Contents></ListBucketResult>')
        with mock.patch.object(r2.requests, "get", return_value=mock.Mock(status_code=200, content=xml)) as g:
            self.assertEqual(r2.list_keys("clips/", bucket="thumbgenius-library"),
                             [{"key": "clips/a.mp4", "size": 10}, {"key": "clips/b.mp4", "size": 20}])
        self.assertIn("/thumbgenius-library/?list-type=2", g.call_args.args[0])


# --------------------------------------------------------------------------- #
# Layout and fingerprints
# --------------------------------------------------------------------------- #

class Layout(unittest.TestCase):
    def test_keys_are_stable_per_asset_and_keyed_by_the_secret(self):
        with mock.patch.multiple(config, **R2ON):
            a = libstore.key_for("clips", "yt:abc@2", ".mp4")
            self.assertEqual(a, libstore.key_for("clips", "yt:abc@2", ".mp4"))       # a re-run overwrites
            self.assertRegex(a, r"^clips/yt_abc_2-[0-9a-f]{10}\.mp4$")
            self.assertNotEqual(a, libstore.key_for("clips", "yt:abd@2", ".mp4"))
            with mock.patch.object(config, "R2_SECRET_ACCESS_KEY", "other"):
                self.assertNotEqual(a, libstore.key_for("clips", "yt:abc@2", ".mp4"))
            with mock.patch.object(config, "R2_LIBRARY_PREFIX", "library/"):
                self.assertTrue(libstore.key_for("thumbs", "yt:abc@2", ".jpg").startswith("library/thumbs/yt_abc_2-"))
            self.assertEqual(libstore.bucket_ref(), "r2:thumbgenius-library")
            self.assertEqual(libstore.url_for("r2:thumbgenius-library", "clips/a.mp4"), "https://pub-lib.r2.dev/clips/a.mp4")
            self.assertEqual(libstore.url_for("r2:thumbgenius-videos", "projects/x.mp4"), "https://pub-v.r2.dev/projects/x.mp4")
            self.assertEqual(libstore.url_for("r2:someone-else", "a.mp4"), "")
            self.assertEqual(libstore.url_for("video-media", "library/clips/a.mp4"), "")
            self.assertEqual(libstore.url_for("", "https://x/y.mp4"), "https://x/y.mp4")

    def test_dhash_duplicates_and_flat_frames(self):
        a = pan()[0]
        noisy = a + np.random.default_rng(3).normal(0, 3, a.shape)
        other = texture(seed=9)[:, :W]
        ha, hn, ho = libstore.dhash(a), libstore.dhash(noisy), libstore.dhash(other)
        self.assertLessEqual(libstore.hamming(ha, hn), 10)
        self.assertGreater(libstore.hamming(ha, ho), 20)
        self.assertIsNone(libstore.dhash(np.full((H, W), 120.0)))              # a flat frame hashes to noise
        self.assertEqual(libstore.duplicate_of([ha, ha, None], {"x": [hn, ho]}), "x")
        self.assertEqual(libstore.duplicate_of([ha, ho, ho], {"x": [ha]}), "")   # one frame alike is not a duplicate
        self.assertEqual(libstore.duplicate_of([ha], {"x": [hn]}), "x")          # a photo has one hash
        self.assertEqual(libstore.duplicate_of([None, None], {"x": [ha]}), "")
        self.assertEqual(libstore.parse_hashes(libstore.hex_hashes([ha, None])), [ha, None])

    def test_probe_applies_rotation(self):
        out = '{"streams":[{"width":1920,"height":1080,"codec_name":"h264","side_data_list":[{"rotation":-90}]}],"format":{"duration":"5.5"}}'
        with mock.patch.object(libstore.subprocess, "run", return_value=mock.Mock(stdout=out)):
            self.assertEqual(libstore.probe("/v.mp4"), {"width": 1080, "height": 1920, "seconds": 5.5,
                                                         "codec": "h264", "ok": True})


# --------------------------------------------------------------------------- #
# The quality gate, rule by rule
# --------------------------------------------------------------------------- #

class Gate(unittest.TestCase):
    def test_a_good_clip_passes_and_keeps_its_measures(self):
        v = judge(pan())
        self.assertTrue(v.ok, v.reasons)
        self.assertTrue(v.checked)
        self.assertEqual(len(v.hashes), 3)
        s = v.summary()
        self.assertEqual((s["width"], s["height"], s["seconds"]), (1920, 1080, 6.0))
        self.assertIn("sharpness", s)

    def test_short(self):
        self.assertIn("too short (2.0s)", judge(pan(), probe=dict(GOOD_PROBE, seconds=2.0)).reasons)

    def test_below_720p(self):
        self.assertEqual(judge(pan(), probe=dict(GOOD_PROBE, width=854, height=480)).reasons, ["below 720p (854x480)"])
        self.assertTrue(judge(pan(), probe=dict(GOOD_PROBE, width=1280, height=720)).ok)

    def test_vertical(self):
        self.assertEqual(judge(pan(), probe=dict(GOOD_PROBE, width=1080, height=1920)).reasons,
                         ["vertical or square (1080x1920)"])

    def test_unreadable(self):
        self.assertEqual(judge(pan(), probe=dict(GOOD_PROBE, ok=False)).reasons, ["unreadable file"])

    def test_mostly_black(self):
        dark = [f * 0.05 for f in pan()]
        self.assertIn("mostly black", judge(dark).reasons)

    def test_frozen(self):
        self.assertIn("frozen frame", judge([pan()[0]] * 8).reasons)

    def test_slideshow_of_stills(self):
        a, b = pan()[0], texture(seed=7)[:, :W]
        self.assertIn("slideshow of stills", judge([a] * 4 + [b] * 4).reasons)

    def test_letterbox_and_pillarbox(self):
        boxed = []
        for f in pan():
            f = f.copy()
            f[:34, :] = 0
            f[-34:, :] = 0
            boxed.append(f)
        self.assertIn("letterboxed (black bars)", judge(boxed).reasons)
        pillared = []
        for f in pan():
            f = f.copy()
            f[:, :60] = 0
            f[:, -60:] = 0
            pillared.append(f)
        self.assertIn("pillarboxed (black bars)", judge(pillared).reasons)
        thin = []
        for f in pan():
            f = f.copy()
            f[:4, :] = 0
            thin.append(f)
        self.assertTrue(judge(thin).ok)                         # a thin line is not a letterbox

    def test_soft(self):
        soft = [np.tile(np.linspace(60 + i, 180 + i, W, dtype=np.float32), (H, 1)) for i in range(0, 16, 2)]
        self.assertTrue(any(r.startswith("soft or blurry") for r in judge(soft).reasons))

    def test_burned_in_graphics_on_a_moving_shot(self):
        banner = texture(seed=11)[:, :W]
        frames = []
        for f in pan():
            f = f.copy()
            f[H - 80:, :] = banner[H - 80:, :]                  # a static graphic over the bottom 36%
            frames.append(f)
        v = judge(frames)
        self.assertTrue(any(r.startswith("burned-in text or graphics") for r in v.reasons), v.reasons)
        self.assertGreater(v.measures["graphics"], 0.25)

    def test_text_lines_on_a_still_camera(self):
        base = np.full((H, W), 90.0, dtype=np.float32) + np.random.default_rng(2).normal(0, 1.0, (H, W))
        text = base.copy()
        strokes = (np.arange(W) % 6 < 2)
        for y in range(10, 210, 22):                            # nine lines of static text
            text[y:y + 8, strokes] = 235.0
        frames = [text + np.random.default_rng(i).normal(0, 1.5, (H, W)) + (i % 2) * 3 for i in range(8)]
        self.assertGreater(libstore.text_bands(frames), 0.25)
        facade = base.copy()
        facade[20:200, strokes] = 235.0                          # one tall textured block: windows, not text
        self.assertEqual(libstore.text_bands([facade] * 4), 0.0)
        self.assertEqual(libstore.text_bands(pan()), 0.0)        # moving footage has no static strokes

    def test_framed_vertical_composite(self):
        frames = []
        for i, f in enumerate(pan(step=6)):
            side = np.tile(np.linspace(60, 68, W, dtype=np.float32), (H, 1)) + i * 0.4   # blurred fill
            side[:, 110:290] = 150.0 + (f[:, 110:290] - 30.0) * 0.3                   # the sharp band
            frames.append(side)
        self.assertTrue(libstore.framed(frames))
        self.assertIn("vertical video framed on a blurred copy", judge(frames).reasons)
        self.assertFalse(libstore.framed(pan()))

    def test_clip_relevance_and_text_classes(self):
        classes = {"photo": 0.9, "person": 0.02, "slide": 0.02, "text": 0.02, "map": 0, "chart": 0, "logo": 0, "render": 0.04}
        off = judge(pan(), clip={"embedding": [0.1] * 4, "relevance": 0.15, "classes": classes})
        self.assertTrue(any(r.startswith("does not show its subject") for r in off.reasons))
        self.assertEqual(off.embedding, [0.1] * 4)
        on = judge(pan(), clip={"embedding": [0.1] * 4, "relevance": 0.27, "classes": classes})
        self.assertTrue(on.ok)
        self.assertEqual(on.summary()["clipRelevance"], 0.27)
        slide = dict(classes, photo=0.3, slide=0.4, text=0.25)
        self.assertIn("mostly text or a slide", judge(pan(), clip={"embedding": None, "relevance": 0.3, "classes": slide}).reasons)

    def test_duplicate_of_a_kept_clip(self):
        frames = pan()
        sig = libstore.signature([libstore._gray(rgb(f)) for f in frames])
        v = judge(frames, known={"yt:kept@1": sig})
        self.assertEqual(v.reasons, ["duplicate of yt:kept@1"])
        self.assertTrue(judge(frames, known={"yt:other@1": libstore.signature(pan(seed=5))}).ok)

    def test_photo_rules(self):
        photo = [pan()[0]]
        self.assertTrue(judge(photo, kind="image", probe=dict(GOOD_PROBE, width=2000, height=1300, seconds=0)).ok)
        small = judge(photo, kind="image", probe=dict(GOOD_PROBE, width=1000, height=700, seconds=0))
        self.assertEqual(small.reasons, ["small photo (1000x700)"])
        with mock.patch.object(libstore, "tools", return_value=True), \
                mock.patch.object(libstore, "probe", return_value=dict(GOOD_PROBE, width=2000, height=1300)), \
                mock.patch.object(libstore, "frames", return_value=[rgb(photo[0])]), \
                mock.patch.object(libstore, "clip_facts", return_value=None), \
                mock.patch("src.filters.text_page_still", return_value=True):
            self.assertIn("a page of text or a slide", libstore.check("/p.jpg", kind="image").reasons)

    def test_missing_tools_never_remove_anything(self):
        with mock.patch.object(libstore, "tools", return_value=False):
            v = libstore.check("/x.mp4")
        self.assertTrue(v.ok)
        self.assertFalse(v.checked)

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_real_files_through_ffmpeg(self):
        d = tempfile.mkdtemp()
        try:
            good = make_clip(os.path.join(d, "good.mp4"), "mandelbrot", 3.5, "1280x720")
            v = libstore.check(good, clip=False)
            self.assertTrue(v.ok, v.reasons)
            self.assertEqual((v.width, v.height), (1280, 720))
            self.assertEqual(libstore.check(make_clip(os.path.join(d, "s.mp4"), "mandelbrot", 3.5, "640x360"),
                                            clip=False).reasons, ["below 720p (640x360)"])
            self.assertEqual(libstore.check(make_clip(os.path.join(d, "t.mp4"), "mandelbrot", 2, "1280x720"),
                                            clip=False).reasons, ["too short (2.0s)"])
            black = libstore.check(make_clip(os.path.join(d, "b.mp4"), "color=c=black:s=1280x720:r=15", 3.5),
                                   clip=False)
            self.assertIn("mostly black", black.reasons)
            # The exact composite upscale.frame_vertical makes of a phone clip.
            from src import upscale
            vert = make_clip(os.path.join(d, "v.mp4"), "mandelbrot", 3.5, "720x1280")
            self.assertTrue(upscale.frame_vertical(vert))
            self.assertIn("vertical video framed on a blurred copy", libstore.check(vert, clip=False).reasons)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Keeping one item on R2
# --------------------------------------------------------------------------- #

class Store(unittest.TestCase):
    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_clip_thumbnail_and_embedding_sidecar(self):
        d = tempfile.mkdtemp()
        try:
            clip = make_clip(os.path.join(d, "c.mp4"), "mandelbrot", 3.5, "1280x720")
            v = libstore.Verdict(checked=True, width=1280, height=720, seconds=3.5, hashes=[1, None, 3],
                                 embedding=[0.5, 0.5], relevance=0.3)
            puts, jsons = [], []
            with mock.patch.multiple(config, **R2ON), \
                    mock.patch.object(r2, "upload", side_effect=lambda path, key, **kw: puts.append((key, kw)) or f"https://pub-lib.r2.dev/{key}"), \
                    mock.patch.object(r2, "upload_bytes", side_effect=lambda data, key, **kw: jsons.append((key, data)) or f"https://pub-lib.r2.dev/{key}"):
                fields = libstore.store(clip, "yt:abc@2", "video", v, {"subject": "Lake Mead"})
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(fields["storage_bucket"], "r2:thumbgenius-library")
        self.assertRegex(fields["storage_path"], r"^clips/yt_abc_2-[0-9a-f]{10}\.mp4$")
        self.assertRegex(fields["thumbnail_path"], r"^thumbs/yt_abc_2-[0-9a-f]{10}\.jpg$")
        a = fields["analysis"]
        self.assertEqual(a["publicUrl"], "https://pub-lib.r2.dev/" + fields["storage_path"])
        self.assertRegex(a["embeddingKey"], r"^embeddings/yt_abc_2-[0-9a-f]{10}\.json$")
        self.assertEqual(a["phash"], ["0000000000000001", None, "0000000000000003"])
        self.assertEqual(a["clipRelevance"], 0.3)
        self.assertEqual([p[1]["bucket"] for p in puts], ["thumbgenius-library"] * 2)
        self.assertEqual([p[1]["content_type"] for p in puts], ["video/mp4", "image/jpeg"])
        self.assertEqual(puts[0][1]["cache_control"], r2.IMMUTABLE)
        import json as _json
        side = _json.loads(jsons[0][1])
        self.assertEqual((side["id"], side["model"], side["dim"], side["subject"]),
                         ("yt:abc@2", libstore.MODEL, 2, "Lake Mead"))


# --------------------------------------------------------------------------- #
# The Library on R2
# --------------------------------------------------------------------------- #

def r2row(i, subject="Lake Mead", **extra):
    row = {"asset_id": f"yt:r2vid{i:05d}@1", "storage_bucket": "r2:thumbgenius-library",
           "storage_path": f"clips/yt_r2vid{i:05d}_1-0123456789.mp4", "thumbnail_path": f"thumbs/yt_r2vid{i:05d}_1-0123456789.jpg",
           "readUrl": "https://pub-lib.r2.dev/should-not-matter", "subject": subject,
           "subject_key": library._key(subject), "entities": [subject], "locations": [], "description": f"r2 {i}",
           "relevance": 0.9, "quality": 0.8, "seconds": 6.0, "kind": "video", "source": "youtube",
           "source_url": f"https://www.youtube.com/watch?v=r2vid{i:05d}", "usage_count": 0, "saved": True,
           "analysis": {"attribution": "YouTube: y", "license": "unverified", "reviewRequired": True,
                        "phash": ["00000000000000ff", None, None], "embeddingKey": f"embeddings/e{i}.json"}}
    row.update(extra)
    return row


def oldrow(i, subject="Lake Mead", **extra):
    row = {"asset_id": f"yt:oldvid{i:04d}@3", "storage_bucket": "video-media",
           "storage_path": f"library/clips/yt_oldvid{i:04d}_3.mp4", "readUrl": f"https://signed/{i}",
           "subject": subject, "subject_key": library._key(subject), "entities": [subject], "locations": [],
           "description": f"old {i}", "relevance": 0.9, "quality": 0.7, "seconds": 6.0, "kind": "video",
           "source_url": "https://www.youtube.com/watch?v=x", "usage_count": i, "saved": True,
           "analysis": {"attribution": "YouTube: x", "license": "unverified", "reviewRequired": True, "keepMe": 1}}
    row.update(extra)
    return row


def loaded(rows):
    library._MAINT.update(thread=None, stop=None, result=None, lib=None)
    with mock.patch.object(config, "CLIP_LIBRARY", True), \
            mock.patch.object(storage, "broker_enabled", return_value=True), \
            mock.patch.object(storage, "broker_library_query", return_value={"ok": True, "rows": rows}), \
            mock.patch.object(libstore, "warm", return_value=False):
        return library.Library.load("proj", "job")


class Rows(unittest.TestCase):
    def test_r2_rows_read_from_the_public_domain(self):
        with mock.patch.multiple(config, **R2ON):
            lib = loaded([r2row(1)])
        e = lib.entries[0]
        self.assertEqual(e["read_url"], "https://pub-lib.r2.dev/clips/yt_r2vid00001_1-0123456789.mp4")
        self.assertEqual(e["thumb_url"], "https://pub-lib.r2.dev/thumbs/yt_r2vid00001_1-0123456789.jpg")
        self.assertEqual(e["phash"], [255, None, None])
        # A worker without the library's public base uses the row's own public URL, then the broker's.
        row = r2row(2, analysis={"publicUrl": "https://pub-lib.r2.dev/from-row.mp4"})
        self.assertEqual(library._from_row(row)["read_url"], "https://pub-lib.r2.dev/from-row.mp4")
        self.assertEqual(library._from_row(r2row(3))["read_url"], "https://pub-lib.r2.dev/should-not-matter")
        # A row saved from the app with a full link (R2 scene media) is read from it.
        self.assertEqual(library._from_row(oldrow(1, storage_bucket=None, storage_path="https://pub-v.r2.dev/p.mp4"))["read_url"],
                         "https://pub-v.r2.dev/p.mp4")

    def test_fetch_of_an_r2_clip_needs_no_broker(self):
        with mock.patch.multiple(config, **R2ON):
            lib = loaded([r2row(1)])
            d = tempfile.mkdtemp()
            with mock.patch.object(storage, "broker_read_url", side_effect=AssertionError("no broker for R2")), \
                    mock.patch.object(storage, "download", side_effect=lambda url, path, **kw: open(path, "wb").close()) as dl, \
                    mock.patch.object(library.media, "playable_video", return_value=True), \
                    mock.patch.object(libstore, "check", side_effect=AssertionError("an R2 clip was checked when kept")):
                asset = lib.fetch(lib.entries[0], d, 6.0, {"intent": "the lake"})
        self.assertEqual(dl.call_args.args[0], "https://pub-lib.r2.dev/clips/yt_r2vid00001_1-0123456789.mp4")
        self.assertEqual(asset.moment_key, "yt:r2vid00001@1")
        self.assertEqual(asset.source, "youtube")
        self.assertEqual(lib.used, {"yt:r2vid00001@1"})

    def test_a_bad_old_clip_is_caught_when_fetched_and_marked_removed(self):
        with mock.patch.multiple(config, **R2ON):
            lib = loaded([oldrow(1), r2row(1)])
            bad = libstore.Verdict(checked=True, width=640, height=360)
            bad.bad("below 720p (640x360)")
            d = tempfile.mkdtemp()
            with mock.patch.object(storage, "download", side_effect=lambda url, path, **kw: open(path, "wb").close()), \
                    mock.patch.object(library.media, "playable_video", return_value=True), \
                    mock.patch.object(libstore, "check", return_value=bad) as chk:
                self.assertIsNone(lib.fetch(lib.entries[0], d, 6.0, {}))
            self.assertEqual(chk.call_args.kwargs["known"], {"yt:r2vid00001@1": [255, None, None]})
            self.assertFalse(lib.entries[0]["saved"])
            self.assertEqual(lib.find("Lake Mead", n=5)[0]["id"], "yt:r2vid00001@1")     # never found again
            with mock.patch.object(config, "CLIP_LIBRARY", True), \
                    mock.patch.object(storage, "broker_enabled", return_value=True), \
                    mock.patch.object(storage, "broker_library_upsert", return_value={"ok": True}) as ups:
                self.assertTrue(lib.save())
        row = ups.call_args.args[2][0]
        self.assertEqual((row["asset_id"], row["saved"]), ("yt:oldvid0001@3", False))
        self.assertEqual(row["analysis"]["removedReason"], "below 720p (640x360)")
        self.assertEqual(row["analysis"]["keepMe"], 1)                      # the old analysis is kept
        self.assertEqual(row["analysis"]["removedBy"], "library-check")
        self.assertEqual(lib.pending, {})


class FindForTheStory(unittest.TestCase):
    def test_place_and_event_matches_come_first(self):
        lib = library.Library("p", "j")
        lib.entries = [library._from_row(r) for r in (
            oldrow(1, relevance=0.99),
            oldrow(2, relevance=0.85, locations=["Clark County, Nevada"], event="drought / reservoir decline"),
            oldrow(3, relevance=0.9, event="record low water"))]
        story = {"kind": "explainer", "places": ["Nevada"], "event": "Lake Mead drought", "year": 2019}
        self.assertEqual([e["id"] for e in lib.find("Lake Mead", n=3, story=story)],
                         ["yt:oldvid0002@3", "yt:oldvid0001@3", "yt:oldvid0003@3"])
        # Without a story: by relevance, as before.
        self.assertEqual([e["id"] for e in lib.find("Lake Mead", n=3, story={})][0], "yt:oldvid0001@3")

    def test_current_news_prefers_fresh_clips_and_never_another_years(self):
        today = datetime.date.today()
        fresh = (today - datetime.timedelta(days=2)).isoformat()
        old = (today - datetime.timedelta(days=200)).isoformat()
        lib = library.Library("p", "j")
        lib.entries = [library._from_row(r) for r in (
            oldrow(1, relevance=0.99, created_at=old + " 10:00:00+00"),
            oldrow(2, relevance=0.85, created_at=fresh + " 10:00:00+00"),
            oldrow(3, relevance=0.99, time_context=f"july {today.year - 3}", created_at=fresh + " 10:00:00+00"))]
        story = {"kind": "news", "places": [], "event": "", "year": today.year}
        got = [e["id"] for e in lib.find("Lake Mead", n=3, story=story)]
        self.assertEqual(got, ["yt:oldvid0002@3", "yt:oldvid0001@3"])          # fresh first; the other year's never
        history = {"kind": "history", "year": 1936}
        self.assertEqual(len(lib.find("Lake Mead", n=3, story=history)), 3)     # a history story takes any year

    def test_images_are_found_only_when_asked_for(self):
        lib = library.Library("p", "j")
        lib.entries = [library._from_row(r) for r in (oldrow(1, kind="image"), oldrow(2))]
        self.assertEqual([e["id"] for e in lib.find("Lake Mead", n=3)], ["yt:oldvid0002@3"])
        self.assertEqual([e["id"] for e in lib.find("Lake Mead", n=3, kind="image")], ["yt:oldvid0001@3"])


class Search(unittest.TestCase):
    def test_semantic_search_over_the_sidecars(self):
        lib = library.Library("p", "j")
        with mock.patch.multiple(config, **R2ON):
            lib.entries = [library._from_row(r2row(1)), library._from_row(r2row(2, subject="Hoover Dam"))]
        sidecars = {"embeddings/e1.json": [1.0, 0.0], "embeddings/e2.json": [0.0, 1.0]}

        def get(url, timeout=0):
            key = url.split("r2.dev/", 1)[1]
            return mock.Mock(status_code=200, json=lambda: {"embedding": sidecars[key]})
        fake_lv = mock.Mock(available=lambda: True, embed_texts=lambda texts: np.array([[0.1, 0.9], [0.0, 1.0]]))
        with mock.patch.multiple(config, **R2ON), mock.patch.object(library.requests, "get", side_effect=get), \
                mock.patch.dict("sys.modules", {"src.localvision": fake_lv}), \
                mock.patch("src.localvision", fake_lv, create=True):
            got = lib.search("the dam wall", n=2)
        self.assertEqual([e["id"] for _s, e in got], ["yt:r2vid00002@1", "yt:r2vid00001@1"])


# --------------------------------------------------------------------------- #
# Keeping a job's clips and photos on R2
# --------------------------------------------------------------------------- #

def scene(i, path, kind="video", source="youtube", score=0.9, **media):
    return {"id": f"s{i}", "durationInFrames": 180,
            "media": {"type": kind, "source": source, "url": path, "attribution": "t", **media},
            "semanticMetadata": {"assetId": f"yt:new{i}@1", "sourceUrl": f"https://www.youtube.com/watch?v=new{i}",
                                 "subject": "Lake Mead", "contentDescription": "aerial", "relevanceScore": score,
                                 "sceneIntent": {"entities": ["Lake Mead"], "locations": ["Nevada"],
                                                 "event_type": "drought", "time_context": "2026"}}}


class RecordOnR2(unittest.TestCase):
    def test_clips_and_photos_are_gated_deduplicated_and_kept_on_r2(self):
        d = tempfile.mkdtemp()
        files = []
        for n in range(6):
            p = os.path.join(d, f"f{n}{'.jpg' if n in (3, 4) else '.mp4'}")
            open(p, "wb").close()
            files.append(p)
        doc = {"fps": 30, "scenes": [
            scene(0, files[0]),                                       # good clip
            scene(1, files[1]),                                       # fails the gate
            scene(2, files[2]),                                       # the same shot as clip 0
            scene(3, files[3], kind="image", source="web_image"),     # good photo
            scene(4, files[4], kind="image", source="generated"),     # never a generated image
            scene(5, files[5], score=0.5),                            # under the floor, never judged
        ]}
        ok0 = libstore.Verdict(checked=True, width=1920, height=1080, seconds=6.0, hashes=[HA, HB, HC], relevance=0.3)
        bad = libstore.Verdict(checked=True, width=640, height=360, seconds=6.0)
        bad.bad("below 720p (640x360)")
        twin = libstore.Verdict(checked=True, width=1920, height=1080, seconds=6.0, hashes=[HA, HB, HC])
        photo = libstore.Verdict(kind="image", checked=True, width=2400, height=1600, hashes=[HP])
        by_path = {files[0]: ok0, files[1]: bad, files[2]: twin, files[3]: photo}
        stored = []

        def store(path, ident, kind, v, meta=None, deadline=0.0):
            stored.append((ident, kind, meta))
            key = f"{'images' if kind == 'image' else 'clips'}/{ident}.x"
            return {"storage_bucket": "r2:thumbgenius-library", "storage_path": key, "thumbnail_path": f"thumbs/{ident}.jpg",
                    "analysis": {"publicUrl": f"https://pub-lib.r2.dev/{key}", "embeddingKey": f"embeddings/{ident}.json",
                                 "phash": libstore.hex_hashes(v.hashes)}}
        def check(path, **kw):
            if path == files[2]:
                time.sleep(0.3)          # the twin is judged after the clip it repeats
            return by_path[path]
        lib = library.Library("proj", "job")
        lib.loaded = lib.db = True
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "broker_upload", side_effect=AssertionError("no app storage on R2")), \
                mock.patch.object(libstore, "check", side_effect=check) as chk, \
                mock.patch.object(libstore, "store", side_effect=store), \
                mock.patch.object(libstore, "warm", return_value=True):
            self.assertEqual(lib.record_from_doc(doc), 2)
            with mock.patch.object(storage, "broker_library_upsert", return_value={"ok": True}) as ups:
                self.assertTrue(lib.save())
        self.assertEqual(sorted(p for p in (c.args[0] for c in chk.call_args_list)), sorted(files[:4]))
        self.assertEqual(sorted(i for i, _k, _m in stored), ["yt:new0@1", "yt:new3@1"])
        self.assertEqual(lib.rejected, {"below 720p": 1, "duplicate": 1})
        rows = {r["asset_id"]: r for r in ups.call_args.args[2]}
        clip, pic = rows["yt:new0@1"], rows["yt:new3@1"]
        self.assertEqual((clip["storage_bucket"], clip["storage_path"], clip["kind"]),
                         ("r2:thumbgenius-library", "clips/yt:new0@1.x", "video"))
        self.assertEqual((clip["width"], clip["height"], clip["seconds"]), (1920, 1080, 6.0))
        self.assertEqual(clip["thumbnail_path"], "thumbs/yt:new0@1.jpg")
        self.assertEqual(clip["analysis"]["embeddingKey"], "embeddings/yt:new0@1.json")
        self.assertIn("savedAt", clip["analysis"])
        self.assertEqual((clip["entities"], clip["locations"], clip["event"]), (["Lake Mead"], ["Nevada"], "drought"))
        self.assertEqual((pic["kind"], pic["source"], pic["storage_path"]), ("image", "web_image", "images/yt:new3@1.x"))


# --------------------------------------------------------------------------- #
# Maintenance: old rows to R2, bad ones out
# --------------------------------------------------------------------------- #

class Maintain(unittest.TestCase):
    def rows(self):
        return [oldrow(5), oldrow(4), oldrow(3), oldrow(2, saved=False), r2row(1), oldrow(1, kind="upload")]

    def run_pass(self, lib, verdicts, dry_run=False, **kw):
        stored, upserts = [], []

        def store(path, ident, kind, v, meta=None, deadline=0.0):
            stored.append(ident)
            return {"storage_bucket": "r2:thumbgenius-library", "storage_path": f"clips/{ident}.mp4",
                    "thumbnail_path": f"thumbs/{ident}.jpg",
                    "analysis": {"publicUrl": f"https://pub-lib.r2.dev/clips/{ident}.mp4", "phash": ["01", None, None]}}
        with mock.patch.multiple(config, **R2ON), \
                mock.patch.object(storage, "download", side_effect=lambda url, path, **k: open(path, "wb").close()), \
                mock.patch.object(storage, "broker_library_upsert", side_effect=lambda p, j, rows: upserts.extend(rows) or {"ok": True}), \
                mock.patch.object(libstore, "tools", return_value=True), \
                mock.patch.object(libstore, "warm", return_value=True), \
                mock.patch.object(libstore, "check", side_effect=lambda path, **k: verdicts[os.path.basename(path)]), \
                mock.patch.object(libstore, "store", side_effect=store):
            stats = lib.maintain(dry_run=dry_run, **kw)
        return stats, stored, upserts

    def verdicts(self):
        good = libstore.Verdict(checked=True, width=1920, height=1080, seconds=6.5, hashes=[HA, HB, HC], relevance=0.28)
        bad = libstore.Verdict(checked=True, width=320, height=240, seconds=6.0)
        bad.bad("below 720p (320x240)")
        twin = libstore.Verdict(checked=True, width=1920, height=1080, seconds=6.0, hashes=[HA, HB, HC])
        return {"m_yt_oldvid0005_3.mp4": good, "m_yt_oldvid0004_3.mp4": bad, "m_yt_oldvid0003_3.mp4": twin}

    def test_good_rows_move_to_r2_and_bad_ones_are_marked_removed(self):
        with mock.patch.multiple(config, **R2ON):
            lib = loaded(self.rows())
        stats, stored, upserts = self.run_pass(lib, self.verdicts(), parallel=1)
        self.assertEqual((stats["legacy"], stats["checked"], stats["moved"], stats["removed"], stats["failed"]),
                         (3, 3, 1, 2, 0))
        self.assertEqual(stats["reasons"], {"below 720p": 1, "duplicate": 1})
        self.assertEqual(stored, ["yt:oldvid0005@3"])                       # the most used first; its twin removed
        rows = {r["asset_id"]: r for r in upserts}
        moved = rows["yt:oldvid0005@3"]
        self.assertEqual((moved["storage_bucket"], moved["storage_path"], moved["width"], moved["seconds"]),
                         ("r2:thumbgenius-library", "clips/yt:oldvid0005@3.mp4", 1920, 6.5))
        self.assertEqual(moved["analysis"]["migratedFrom"], {"bucket": "video-media", "path": "library/clips/yt_oldvid0005_3.mp4"})
        self.assertEqual(moved["analysis"]["keepMe"], 1)
        self.assertNotIn("saved", moved)
        self.assertEqual(rows["yt:oldvid0004@3"]["saved"], False)
        self.assertEqual(rows["yt:oldvid0003@3"]["analysis"]["removedReason"], "duplicate of yt:oldvid0005@3")
        self.assertNotIn("yt:oldvid0002@3", rows)                           # already removed: left alone
        self.assertNotIn("yt:oldvid0001@3", rows)                           # the user's upload: left alone
        e = {x["id"]: x for x in lib.entries}
        self.assertEqual(e["yt:oldvid0005@3"]["read_url"], "https://pub-lib.r2.dev/clips/yt:oldvid0005@3.mp4")
        self.assertFalse(e["yt:oldvid0004@3"]["saved"])
        # Idempotent: a second pass has nothing to do.
        again, stored2, upserts2 = self.run_pass(lib, self.verdicts())
        self.assertEqual((again["legacy"], stored2, upserts2), (0, [], []))

    def test_dry_run_writes_nothing(self):
        with mock.patch.multiple(config, **R2ON):
            lib = loaded(self.rows())
        stats, stored, upserts = self.run_pass(lib, self.verdicts(), dry_run=True, parallel=1)
        self.assertEqual((stats["checked"], stats["moved"], stats["removed"]), (3, 1, 2))
        self.assertEqual((stored, upserts), ([], []))
        self.assertTrue(all(e.get("saved", True) for e in lib.entries if e["id"] != "yt:oldvid0002@3"))
        self.assertEqual(len(stats["verdicts"]), 3)

    def test_bounded_by_count_and_time(self):
        with mock.patch.multiple(config, **R2ON):
            lib = loaded(self.rows())
        stats, _s, _u = self.run_pass(lib, self.verdicts(), max_items=1)
        self.assertEqual((stats["checked"], stats["left"]), (1, 2))
        with mock.patch.multiple(config, **R2ON):
            lib = loaded(self.rows())
        stats, _s, _u = self.run_pass(lib, self.verdicts(), seconds=0)
        self.assertEqual(stats["checked"], 0)

    def test_needs_r2_unless_a_dry_run(self):
        lib = loaded(self.rows())
        with mock.patch.object(config, "R2_LIBRARY_BUCKET", ""):
            self.assertEqual(lib.maintain()["note"], "R2 library bucket not configured")

    def test_a_clip_the_owner_restored_is_moved_not_removed(self):
        rows = [oldrow(5, analysis={"restoredAt": "2026-09-30T10:00:00Z", "lastRemovedReason": "below 720p"})]
        with mock.patch.multiple(config, **R2ON):
            lib = loaded(rows)
        bad = libstore.Verdict(checked=True, width=640, height=360, seconds=6.0, hashes=[HA, HB, HC])
        bad.bad("below 720p (640x360)")
        stats, stored, upserts = self.run_pass(lib, {"m_yt_oldvid0005_3.mp4": bad})
        self.assertEqual((stats["removed"], stats["moved"], stats["kept_by_owner"]), (0, 1, 1))
        self.assertEqual(stored, ["yt:oldvid0005@3"])
        self.assertNotIn("saved", upserts[0])
        self.assertEqual(upserts[0]["analysis"]["restoredAt"], "2026-09-30T10:00:00Z")
        # Nor is it caught when a job fetches it.
        with mock.patch.multiple(config, **R2ON):
            lib = loaded(rows)
            d = tempfile.mkdtemp()
            with mock.patch.object(storage, "download", side_effect=lambda url, path, **kw: open(path, "wb").close()), \
                    mock.patch.object(library.media, "playable_video", return_value=True), \
                    mock.patch.object(libstore, "check", side_effect=AssertionError("re-judged a restored clip")):
                self.assertIsNotNone(lib.fetch(lib.entries[0], d, 6.0, {}))

    def test_the_job_uses_the_rows_its_pass_loaded(self):
        library._MAINT.update(thread=None, stop=None, result=None, lib=None)
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(config, "LIBRARY_MAINTENANCE", True), \
                mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "broker_library_query", return_value={"ok": True, "rows": self.rows()}) as q, \
                mock.patch.object(library.Library, "maintain", lambda self, **kw: {"checked": 0}), \
                mock.patch.object(libstore, "warm", return_value=False):
            self.assertTrue(library.start_maintenance("proj", "job"))
            library._MAINT["thread"].join(5)
            lib = library.Library.load("proj", "job")
            self.assertEqual(q.call_count, 1)                                   # one query for both
            self.assertEqual(len(lib.entries), 6)
            other = library.Library.load("proj", "job")                         # adopted once only
            self.assertEqual(q.call_count, 2)
            self.assertEqual(len(other.entries), 6)
        library._MAINT.update(thread=None, stop=None, result=None, lib=None)

    def test_old_rows_beyond_the_first_window_are_listed_for_the_pass(self):
        lib = library.Library("proj", "job")
        lib.entries = [library._from_row(r2row(i)) for i in range(3)]
        with mock.patch.object(library, "QUERY_LIMIT", 3), \
                mock.patch.object(storage, "broker_library_query",
                                  return_value={"ok": True, "rows": [r2row(1), oldrow(7), oldrow(8)]}) as q:
            self.assertEqual(lib._load_legacy(), 2)
        self.assertEqual(q.call_args.kwargs["legacy"], True)
        self.assertEqual(len(lib.entries), 5)
        small = library.Library("proj", "job")
        small.entries = [library._from_row(r2row(1))]
        with mock.patch.object(storage, "broker_library_query", side_effect=AssertionError("not needed")):
            self.assertEqual(small._load_legacy(), 0)

    def test_background_pass_per_job(self):
        started = threading.Event()

        def fake_maintain(self, **kw):
            started.set()
            return {"checked": 2, "stop_given": kw.get("stop") is not None}
        library._MAINT.update(thread=None, stop=None, result=None)
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "CLIP_LIBRARY", True), \
                mock.patch.object(config, "LIBRARY_MAINTENANCE", True), \
                mock.patch.object(storage, "broker_enabled", return_value=True), \
                mock.patch.object(storage, "broker_library_query", return_value={"ok": True, "rows": self.rows()}), \
                mock.patch.object(library.Library, "maintain", fake_maintain):
            self.assertTrue(library.start_maintenance("proj", "job"))
            self.assertTrue(started.wait(5))
            self.assertEqual(library.wait_maintenance(), {"checked": 2, "stop_given": True})
            with mock.patch.object(config, "LIBRARY_MAINTENANCE", False):
                self.assertFalse(library.start_maintenance("proj", "job"))
        with mock.patch.object(config, "R2_LIBRARY_BUCKET", ""):
            self.assertFalse(library.start_maintenance("proj", "job"))
        library._MAINT.update(thread=None, stop=None, result=None, lib=None)


# --------------------------------------------------------------------------- #
# Scene media on R2 (handler)
# --------------------------------------------------------------------------- #

class SceneMediaOnR2(unittest.TestCase):
    def setUp(self):
        import handler
        self.handler = handler

    def doc(self, d):
        clip = os.path.join(d, "s0.mp4")
        open(clip, "wb").close()
        return {"meta": {"warnings": []}, "scenes": [
            {"id": "s0", "media": {"type": "video", "url": clip, "source": "youtube",
                                   "storage": {"bucket": "video-media", "path": "projects/p/media/old.mp4"},
                                   "thumbStorage": {"bucket": "video-media", "path": "projects/p/thumbs/old.jpg"}}}]}

    def test_published_to_r2_with_public_links_and_no_storage_refs(self):
        h, d = self.handler, tempfile.mkdtemp()
        doc = self.doc(d)
        thumb, prev = os.path.join(d, "t.jpg"), os.path.join(d, "p.mp4")
        open(thumb, "wb").close()
        open(prev, "wb").close()
        keys = []

        def upload(path, key, **kw):
            keys.append((key, kw["content_type"], kw.get("bucket", "")))
            return f"https://pub-v.r2.dev/{key}"
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_SCENE_MEDIA", True), \
                mock.patch.object(h.r2, "upload", side_effect=upload), \
                mock.patch.object(h.storage, "broker_upload", side_effect=AssertionError("app storage used")), \
                mock.patch.object(h, "_thumbnail", return_value=thumb), \
                mock.patch.object(h, "_preview_proxy", return_value=prev):
            self.assertEqual(h.publish_media(doc, "p", "video-media", lambda *a, **k: None, job_id="j"), 1)
        m = doc["scenes"][0]["media"]
        self.assertRegex(m["url"], r"^https://pub-v\.r2\.dev/projects/p/media/s0-[0-9a-f]{12}\.mp4$")
        self.assertRegex(m["thumbnail"], r"^https://pub-v\.r2\.dev/projects/p/thumbs/s0-[0-9a-f]{12}\.jpg$")
        self.assertRegex(m["previewUrl"], r"^https://pub-v\.r2\.dev/projects/p/preview/s0-[0-9a-f]{12}\.mp4$")
        for key in ("storage", "thumbStorage", "previewStorage"):
            self.assertNotIn(key, m)                                        # nothing for the app to re-sign
        self.assertEqual([k[1] for k in keys], ["video/mp4", "image/jpeg", "video/mp4"])
        self.assertEqual({k[2] for k in keys}, {""})                         # the videos bucket, not the library's

    def test_falls_back_to_app_storage_when_r2_refuses(self):
        h, d = self.handler, tempfile.mkdtemp()
        doc = self.doc(d)
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_SCENE_MEDIA", True), \
                mock.patch.object(h.r2, "upload", side_effect=RuntimeError("R2 upload failed: HTTP 403")), \
                mock.patch.object(h.storage, "broker_enabled", return_value=True), \
                mock.patch.object(h.storage, "broker_upload", return_value="https://signed/new") as up, \
                mock.patch.object(h, "_thumbnail", return_value=""), \
                mock.patch.object(h, "_preview_proxy", return_value=""):
            h.publish_media(doc, "p", "video-media", lambda *a, **k: None, job_id="j")
        m = doc["scenes"][0]["media"]
        self.assertEqual(m["url"], "https://signed/new")
        self.assertEqual(m["storage"], {"bucket": "video-media", "path": "projects/p/media/s0.mp4"})
        self.assertNotIn("thumbStorage", m)                                  # the stale reference is gone
        self.assertEqual(up.call_args.args[2], "projects/p/media/s0.mp4")

    def test_off_switch_keeps_the_app_storage(self):
        h, d = self.handler, tempfile.mkdtemp()
        doc = self.doc(d)
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_SCENE_MEDIA", False), \
                mock.patch.object(h.r2, "upload", side_effect=AssertionError("R2 used")), \
                mock.patch.object(h.storage, "broker_enabled", return_value=True), \
                mock.patch.object(h.storage, "broker_upload", return_value="https://signed/x"), \
                mock.patch.object(h, "_thumbnail", return_value=""), \
                mock.patch.object(h, "_preview_proxy", return_value=""):
            h.publish_media(doc, "p", "video-media", lambda *a, **k: None, job_id="j")
        self.assertEqual(doc["scenes"][0]["media"]["storage"]["path"], "projects/p/media/s0.mp4")

    def test_replace_clip_choices_go_to_r2(self):
        h, d = self.handler, tempfile.mkdtemp()
        alt = os.path.join(d, "alt.mp4")
        open(alt, "wb").close()
        cands = [{"rank": 2, "localPath": alt, "media": {"storage": {"bucket": "video-media", "path": "old"}}}]
        with mock.patch.multiple(config, **R2ON), mock.patch.object(config, "R2_SCENE_MEDIA", True), \
                mock.patch.object(h.r2, "upload", side_effect=lambda path, key, **kw: f"https://pub-v.r2.dev/{key}"), \
                mock.patch.object(h, "_thumbnail", return_value=""), \
                mock.patch.object(h, "_preview_proxy", return_value=""):
            h._publish_alternatives(cands, "p", "video-media", "j", "s3", d)
        m = cands[0]["media"]
        self.assertRegex(m["url"], r"^https://pub-v\.r2\.dev/projects/p/alts/s3_alt1-[0-9a-f]{12}\.mp4$")
        self.assertNotIn("storage", m)
        self.assertEqual(m["type"], "video")

    def test_render_leaves_r2_links_alone(self):
        h = self.handler
        doc = {"audio": {"url": "https://pub-v.r2.dev/a.mp3"},
               "scenes": [{"media": {"type": "video", "url": "https://pub-v.r2.dev/projects/p/media/s0-abc.mp4",
                                     "thumbnail": "https://pub-v.r2.dev/projects/p/thumbs/s0-abc.jpg"}}]}
        with mock.patch.object(config, "SUPABASE_URL", "https://x.supabase.co"), \
                mock.patch.object(h.storage, "signed_url", side_effect=AssertionError("re-signed an R2 link")):
            h._sign_supabase_urls(doc)
        self.assertEqual(doc["scenes"][0]["media"]["url"], "https://pub-v.r2.dev/projects/p/media/s0-abc.mp4")
        self.assertTrue(h._all_remote(doc))


if __name__ == "__main__":
    unittest.main()
