"""
Restore / repair missing media (src/restore.py, handler action restore_media).

On 2026-10-04 the Cloudflare R2 folders of two of the owner's projects were
deleted by hand; their timelines still pointed at the old links. A restore
puts each missing file back under the SAME link: the copy a plan's part
sourced when it is the timeline's shot, else the shot fetched again from its
source, then the editor's thumbnail and preview; what cannot be restored is
listed. It never changes the timeline, never writes the project, never
deletes and never overwrites.

Offline: R2 is a dict, the app's storage and the web are dicts, YouTube and
the picture fetch are stubs that write small text files ("clip|name|seconds|
tone"), and reading a file's length, tone and hash is parsing that text. One
class runs the real tone check on real files when ffmpeg is installed.
"""
import copy
import json
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
from src import config, events, grade, imagefix, ledger, media, r2, restore, storage, upscale, ytdlp  # noqa: E402
from src.errors import FailureClass  # noqa: E402

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
PID = "15eb0bc3-0031-424e-a731-48b68cbe7eed"
OTHER = "99999999-0000-4000-8000-000000000000"
BASE = "https://pub-test.r2.dev"
LIB_BASE = "https://pub-lib.r2.dev"
BUCKET = "videos"
PLAN = "plan-job-1"

TONES = {
    "A": {"l": 0.14, "lo": 0.045, "hi": 0.565, "s": 0.046, "rg": 1.272, "bg": 0.93, "v": 1},
    "B": {"l": 0.41, "lo": 0.10, "hi": 0.90, "s": 0.21, "rg": 0.95, "bg": 1.10, "v": 1},
    "C": {"l": 0.188, "lo": 0.034, "hi": 0.406, "s": 0.263, "rg": 2.449, "bg": 0.713, "v": 1},
}


def url(folder: str, name: str, project: str = PID) -> str:
    return f"{BASE}/projects/{project}/{folder}/{name}"


def key(folder: str, name: str, project: str = PID) -> str:
    return f"projects/{project}/{folder}/{name}"


def clip_scene(n: int, token: str = "aaaaaaaaaaaa", vid: str = "AAAAAAAAAAA", start=476.7, clip=7.77,
               clean=True, tone="A", **sem) -> dict:
    moment = {} if start is None else {"start": start, **({"clean": True, "cuts": 0} if clean else {})}
    return {"id": f"s{n:04d}", "startFrame": n * 240, "durationInFrames": 240, "text": "line",
            "media": {"type": "video", "url": url("media", f"s{n:04d}-{token}.mp4"), "source": "youtube",
                      "thumbnail": url("thumbs", f"s{n:04d}-{token}.jpg"),
                      "previewUrl": url("preview", f"s{n:04d}-{token}.mp4"),
                      **({"clipSeconds": clip} if clip else {}), **({"tone": TONES[tone]} if tone else {})},
            "semanticMetadata": {"provider": "youtube", "assetId": f"yt:{vid}@47",
                                 "sourceUrl": f"https://www.youtube.com/watch?v={vid}&t={int(start or 0)}",
                                 "moment": moment, **sem}}


def photo_scene(n: int, token: str = "bbbbbbbbbbbb", src: str = "https://example.org/dam.jpg", tone="C",
                provider: str = "web_image") -> dict:
    return {"id": f"s{n:04d}", "startFrame": n * 240, "durationInFrames": 240, "text": "line",
            "media": {"type": "image", "url": url("media", f"s{n:04d}-{token}.jpg"), "source": provider,
                      "thumbnail": url("thumbs", f"s{n:04d}-{token}.jpg"), **({"tone": TONES[tone]} if tone else {})},
            "semanticMetadata": {"provider": provider, "assetId": f"{provider}:{src}", "sourceUrl": src}}


def timeline(*scenes, overlays=None, style: str = "") -> dict:
    return {"fps": 30, "width": 1920, "height": 1080, "scenes": list(scenes), "overlays": list(overlays or []),
            "meta": {"videoStyle": style}}


def clip_file(name: str, seconds: float, tone: str = "A") -> bytes:
    return f"clip|{name}|{seconds}|{tone}".encode()


def photo_file(name: str, phash: int = 0, tone: str = "C") -> bytes:
    return f"photo|{name}|{phash:016x}|{tone}".encode()


def _fields(path: str) -> list:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace").split("|")


class Store:
    """Cloudflare R2 as far as a restore reads and writes it."""

    def __init__(self):
        self.objects, self.puts, self.heads = {}, [], []
        self.head_errors, self.list_fails = set(), False

    def put(self, k: str, data: bytes = b"x", bucket: str = BUCKET) -> None:
        self.objects[(bucket, k)] = data

    def list_keys(self, prefix="", bucket="", limit=10000):
        if self.list_fails:
            raise RuntimeError("R2 list: HTTP 500")
        b = bucket or BUCKET
        return [{"key": k, "size": len(v)} for (bb, k), v in sorted(self.objects.items())
                if bb == b and k.startswith(prefix)][:limit]

    def head(self, k, bucket=""):
        self.heads.append(k)
        if k in self.head_errors:
            raise RuntimeError(f"R2 HEAD {k}: HTTP 500")
        v = self.objects.get((bucket or BUCKET, k))
        return None if v is None else {"size": len(v), "etag": "", "type": ""}

    def upload(self, path, k, content_type="video/mp4", deadline=0.0, bucket="", base="", cache_control=""):
        with open(path, "rb") as fh:
            data = fh.read()
        self.objects[(bucket or BUCKET, k)] = data
        self.puts.append({"key": k, "bucket": bucket or BUCKET, "type": content_type, "cache": cache_control,
                          "data": data})
        return f"{BASE}/{k}"

    def get_object(self, bucket, k, dest):
        data = self.objects.get((bucket, k))
        if data is None:
            raise RuntimeError(f"R2 GET {k}: HTTP 404")
        with open(dest, "wb") as fh:
            fh.write(data)
        return dest

    def keys_put(self) -> list:
        return sorted(p["key"] for p in self.puts)


class Bench(unittest.TestCase):
    """Everything a restore touches, faked: R2, the app's storage, YouTube, the web."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="restore_test_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.r2 = Store()
        self.web = {}                   # a read link -> the bytes it gives (the app's storage, a picture's site)
        self.dead = set()               # YouTube ids / picture addresses that no longer answer
        self.calls = []                 # every fetch from a source, in order
        self.polished = []
        self.clip_tone = {}             # YouTube id -> the tone of what it gives now
        events.start_job("job-restore", "")

        def patch(obj, name, value):
            p = mock.patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)

        for name, value in (("R2_ACCOUNT_ID", "acct"), ("R2_ACCESS_KEY_ID", "id"), ("R2_SECRET_ACCESS_KEY", "s"),
                            ("R2_BUCKET", BUCKET), ("R2_PUBLIC_BASE", BASE), ("R2_LIBRARY_BUCKET", "library"),
                            ("R2_LIBRARY_PUBLIC_BASE", LIB_BASE), ("UPSCALE_ENABLED", True),
                            ("ALLOW_VERTICAL", False), ("SUPABASE_SERVICE_KEY", ""), ("SUPABASE_URL", ""),
                            ("STORAGE_BROKER_URL", ""), ("RESTORE_UNVERIFIED", False)):
            patch(config, name, value)
        for name in ("list_keys", "head", "upload"):
            patch(r2, name, getattr(self.r2, name))
        patch(r2, "delete", mock.Mock(side_effect=AssertionError("a restore never deletes")))
        patch(r2, "upload_bytes", mock.Mock(side_effect=AssertionError("a restore uploads files only")))
        patch(restore, "_get_object", self.r2.get_object)
        patch(storage, "download", self._download)
        patch(storage, "patch_project", mock.Mock(side_effect=AssertionError("the project is never written")))
        patch(restore, "_plays", lambda p: _fields(p)[0] == "clip")
        patch(restore, "_clip_seconds", lambda p: float(_fields(p)[2]) if _fields(p)[0] == "clip" else 0.0)
        patch(restore, "_is_picture", lambda p: _fields(p)[0] == "photo")
        patch(restore, "_measure_tone", lambda link, p: TONES.get(_fields(p)[3]))
        patch(ledger, "photo_hash", lambda p: int(_fields(p)[2], 16) if _fields(p)[0] == "photo" else None)
        patch(ledger, "_get_json", lambda k, timeout=20: None)
        patch(media, "reset_cache", lambda: None)
        patch(media, "fetch_clean_clip", self._clean_clip)
        patch(media, "_yt_fetch_retry", self._plain_clip)
        patch(media, "_dm_fetch", self._dm_clip)
        patch(media, "_web_fetch", self._web_clip)
        patch(imagefix, "fetch", self._picture)
        patch(restore.filters, "trim_clip", self._trim)
        for name in ("frame_vertical", "upscale_clip", "upscale_image"):
            patch(upscale, name, self._polisher(name))

    # ---- the fakes ---------------------------------------------------------
    def _write(self, path: str, data: bytes) -> str:
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _download(self, link, dest, timeout=180, headers=None, proxy="", attempts=3):
        self.calls.append(("download", link))
        if link not in self.web:
            raise storage.StorageError("download failed after 1 attempt(s): 404")
        return self._write(dest, self.web[link])

    def _clean_clip(self, vid, out_dir, start, need, title=""):
        self.calls.append(("clean", vid, start, round(need, 2)))
        if vid in self.dead:
            ytdlp._LAST_FAILURE.set((FailureClass.MEDIA_UNAVAILABLE, ""))
            return "", True, 0
        path = os.path.join(out_dir, f"yt_{vid}_{len(self.calls)}.mp4")
        return self._write(path, clip_file(f"yt:{vid}@{start}", round(need + 0.5, 2), self.clip_tone.get(vid, "A"))), True, 0

    def _plain_clip(self, vid, out_dir, start, seconds, title=""):
        self.calls.append(("plain", vid, start, round(seconds, 2)))
        if vid in self.dead:
            ytdlp._LAST_FAILURE.set((FailureClass.ACCESS_DENIED, ""))
            return ""
        got = self.short.get(vid, seconds) if hasattr(self, "short") else seconds
        return self._write(os.path.join(out_dir, f"yt_{vid}_{len(self.calls)}.mp4"), clip_file(f"yt:{vid}@{start}", got))

    def _dm_clip(self, vid, out_dir, start, seconds, timeout=240):
        self.calls.append(("dailymotion", vid, start, round(seconds, 2)))
        return self._write(os.path.join(out_dir, f"dm_{vid}.mp4"), clip_file(f"dm:{vid}", seconds))

    def _web_clip(self, link, out_dir, start, seconds, timeout=240):
        self.calls.append(("web", link, start, round(seconds, 2)))
        return "" if link in self.dead else self._write(os.path.join(out_dir, "web.mp4"), clip_file(link, seconds))

    def _picture(self, link, dest, page_url="", thumbnail=""):
        self.calls.append(("picture", link, page_url, thumbnail))
        if link in self.dead:
            raise storage.StorageError("picture download failed: 404 Client Error")
        return self._write(dest, photo_file(link))

    def _trim(self, path, offset, seconds, timeout=180):
        self.calls.append(("trim", round(offset, 2), round(seconds, 2)))
        name = _fields(path)[1]
        return self._write(path + ".cut.mp4", clip_file(name, seconds))

    def _polisher(self, name):
        def run(path, *a, **k):
            self.polished.append((name, os.path.basename(path)))
            return name in getattr(self, "polish_does", ())
        return run

    # ---- helpers -----------------------------------------------------------
    def part(self, name: str, data: bytes, job: str = PLAN) -> dict:
        """A copy in the app's storage, as scripts/restore_project.py hands it over."""
        path = f"projects/{PID}/parts/{job}/{name}"
        link = f"https://app.supabase.co/storage/v1/object/sign/video-media/{path}?token=t"
        self.web[link] = data
        return {"path": path, "url": link}

    def run_restore(self, doc: dict, **inp) -> dict:
        self.thumbs = []

        def thumb(path, work, tag):
            self.thumbs.append(("thumbnail", _fields(path)[1]))
            return self._write(os.path.join(work, f"thumb_{tag}.jpg"), b"thumb of " + _fields(path)[1].encode())

        def prev(path, work, tag):
            if _fields(path)[0] != "clip":
                return ""
            self.thumbs.append(("preview", _fields(path)[1]))
            return self._write(os.path.join(work, f"preview_{tag}.mp4"), b"preview of " + _fields(path)[1].encode())
        return restore.run({"project_id": PID, "_job_id": "job-restore", **inp}, doc, self.work,
                           thumbnail=thumb, preview=prev)

    def fetches(self) -> list:
        return [c for c in self.calls if c[0] in ("clean", "plain", "dailymotion", "web", "picture")]


# --------------------------------------------------------------------------- #
class Inventory(Bench):
    def test_every_file_of_ours_once_with_what_is_known_about_its_shot(self):
        clip = clip_scene(0)
        photo = photo_scene(1)
        old = {"id": "s0002", "durationInFrames": 90, "media": {"type": "image", "url": "https://app.supabase.co/x.jpg?token=1"}}
        graphic = {"id": "s0003", "durationInFrames": 90, "media": {"type": "animation", "url": ""},
                   "animation": {"media": [{"type": "image", "url": url("overlay", "003-cccccccccccc.jpg")}]}}
        photo["semanticMetadata"]["alternatives"] = [{"media": {"type": "video", "url": url("alts", "s0001_alt1-dddddddddddd.mp4")}}]
        doc = timeline(clip, photo, old, graphic, overlays=[
            {"type": "split", "template": "CMP_SPLIT_V1", "media": [
                {"type": "image", "url": url("split", "014_0-eeeeeeeeeeee.jpg"), "source": "web"},
                {"type": "image", "url": url("split", "014_1-ffffffffffff.jpg"), "source": "web"}]},
            {"type": "photo-card", "template": "PHOTO_PIP_V1", "media": [dict(photo["media"])]},      # the scene's own picture
            {"type": "motion", "template": "LIB_PX_POSTCARD", "mediaFrom": ["s0001"]}])
        links, stats = restore.inventory(doc)
        by_key = {l.key: l for l in links}
        self.assertEqual(stats, {"scenes": 3, "other_links": 1})                     # the old app-storage link is not ours
        self.assertEqual(len(links), 6)
        c = by_key[key("media", "s0000-aaaaaaaaaaaa.mp4")]
        self.assertEqual((c.role, c.kind, c.number, c.index, c.ext), ("scene", "video", 0, 0, ".mp4"))
        self.assertEqual((c.start, c.clean, c.clip_seconds, c.scene_seconds, c.want), (476.7, True, 7.77, 8.0, 7.77))
        self.assertEqual(c.thumb, (BUCKET, key("thumbs", "s0000-aaaaaaaaaaaa.jpg")))
        self.assertEqual(c.preview, (BUCKET, key("preview", "s0000-aaaaaaaaaaaa.mp4")))
        self.assertEqual(c.tone, TONES["A"])
        p = by_key[key("media", "s0001-bbbbbbbbbbbb.jpg")]
        self.assertEqual((p.role, p.source_url, p.provider, p.preview), ("scene", "https://example.org/dam.jpg", "web_image", None))
        self.assertEqual(p.also, ["graphic 2 (PHOTO_PIP_V1)"])                       # the card borrows it: one file
        self.assertEqual(by_key[key("split", "014_0-eeeeeeeeeeee.jpg")].label, "graphic 1 (CMP_SPLIT_V1)")
        self.assertEqual(by_key[key("overlay", "003-cccccccccccc.jpg")].role, "look")
        self.assertEqual(by_key[key("alts", "s0001_alt1-dddddddddddd.mp4")].role, "choice")

    def test_the_moment_falls_back_to_the_t_of_the_source_address(self):
        s = clip_scene(4, start=None)
        s["semanticMetadata"]["sourceUrl"] = "https://www.youtube.com/watch?v=AAAAAAAAAAA&t=95"
        link = restore.inventory(timeline(s))[0][0]
        self.assertEqual((link.start, link.clean), (95.0, False))
        s["semanticMetadata"]["sourceUrl"] = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
        link = restore.inventory(timeline(s))[0][0]
        self.assertIsNone(link.start)
        self.assertEqual(restore.origin(link), ("", "the moment of YouTube video AAAAAAAAAAA was not recorded"))

    def test_a_clip_without_a_recorded_length_is_asked_for_its_scene_plus_a_margin(self):
        link = restore.inventory(timeline(clip_scene(0, clip=None)))[0][0]
        self.assertEqual(link.want, 9.5)


# --------------------------------------------------------------------------- #
class OrderOfSources(Bench):
    def test_a_part_that_is_the_timelines_shot_is_copied_back_and_nothing_is_fetched(self):
        doc = timeline(clip_scene(0), photo_scene(1))
        parts = [self.part("0000.mp4", clip_file("part0", 7.8, "A")), self.part("0001.jpg", photo_file("part1", tone="C"))]
        out = self.run_restore(doc, parts=parts)
        self.assertEqual((out["restored_from_copy"], out["refetched"], out["failed"]), (2, 0, 0))
        self.assertEqual(self.fetches(), [])                                         # no source was asked
        self.assertEqual(self.r2.objects[(BUCKET, key("media", "s0000-aaaaaaaaaaaa.mp4"))], clip_file("part0", 7.8, "A"))
        self.assertEqual(self.r2.objects[(BUCKET, key("media", "s0001-bbbbbbbbbbbb.jpg"))], photo_file("part1", tone="C"))
        self.assertEqual([r["did"] for r in out["rows"]], ["copy", "copy"])
        self.assertIn("projects/%s/parts/%s/0000.mp4" % (PID, PLAN), out["rows"][0]["from"])

    def test_a_part_of_another_length_is_another_shot_and_the_source_is_asked(self):
        doc = timeline(clip_scene(0))
        out = self.run_restore(doc, parts=[self.part("0000.mp4", clip_file("an earlier pick", 6.4, "A"))])
        self.assertEqual((out["restored_from_copy"], out["refetched"], out["failed"]), (0, 1, 0))
        # Cut clean like the plan: it asked for `need` and kept need + 0.5, at the same start.
        self.assertEqual(self.fetches(), [("clean", "AAAAAAAAAAA", 476.7, 7.27)])
        self.assertEqual(self.r2.objects[(BUCKET, key("media", "s0000-aaaaaaaaaaaa.mp4"))],
                         clip_file("yt:AAAAAAAAAAA@476.7", 7.77))
        self.assertEqual(self.polished, [("upscale_clip", os.path.basename(self.polished[0][1]))])    # only the fetched file

    def test_a_part_of_the_right_length_but_other_colours_is_another_shot(self):
        # The rescue pass replaced the part's pick with a clip of the very same length
        # (both are cut to need + 0.5): only the tone the plan measured tells them apart.
        doc = timeline(clip_scene(0, tone="A"))
        out = self.run_restore(doc, parts=[self.part("0000.mp4", clip_file("the replaced pick", 7.77, "B"))])
        self.assertEqual((out["restored_from_copy"], out["refetched"]), (0, 1))
        self.assertIn("another shot", out["rows"][0].get("note", ""))

    def test_the_newest_matching_copy_of_several_plan_jobs_is_used(self):
        doc = timeline(clip_scene(0))
        parts = [self.part("0000.mp4", clip_file("an older plan", 5.0), job="plan-old"),
                 self.part("0000.mp4", clip_file("this plan", 7.77), job=PLAN)]
        out = self.run_restore(doc, parts=parts)
        self.assertEqual(out["restored_from_copy"], 1)
        self.assertEqual(_fields_of(self.r2.objects[(BUCKET, key("media", "s0000-aaaaaaaaaaaa.mp4"))])[1], "this plan")

    def test_a_youtube_clip_the_plan_did_not_cut_clean_is_the_plain_section(self):
        out = self.run_restore(timeline(clip_scene(0, clean=False, clip=6.4)))
        self.assertEqual(self.fetches(), [("plain", "AAAAAAAAAAA", 476.7, 6.4)])
        self.assertEqual(out["refetched"], 1)

    def test_a_longer_download_is_cut_to_the_length_the_timeline_plays(self):
        self.short = {"AAAAAAAAAAA": 9.0}
        self.run_restore(timeline(clip_scene(0, clean=False, clip=6.4)))
        self.assertIn(("trim", 0.0, 6.4), self.calls)
        self.assertEqual(float(_fields_of(self.r2.objects[(BUCKET, key("media", "s0000-aaaaaaaaaaaa.mp4"))])[2]), 6.4)

    def test_a_picture_comes_again_through_the_picture_fetch(self):
        out = self.run_restore(timeline(photo_scene(1, src="https://example.org/dam.jpg")))
        self.assertEqual(self.fetches(), [("picture", "https://example.org/dam.jpg", "", "")])
        self.assertEqual((out["refetched"], out["failed"]), (1, 0))
        self.assertEqual(self.polished[0][0], "upscale_image")                       # small photos upscaled as the plan does

    def test_dailymotion_a_page_and_a_direct_file(self):
        dm = clip_scene(0, clean=False, clip=5.0)
        dm["semanticMetadata"].update(provider="dailymotion", assetId="dailymotion:x", sourceUrl="https://www.dailymotion.com/video/x8abc12",
                                      moment={"start": 12.0})
        page = clip_scene(1, token="111111111111", clean=False, clip=5.0)
        page["semanticMetadata"].update(provider="web_video", assetId="web_video:x", sourceUrl="https://news.example.com/flood-video",
                                        moment={"start": 3.0})
        nasa = clip_scene(2, token="222222222222", clean=False, clip=12.0, start=None)
        nasa["semanticMetadata"].update(provider="nasa", assetId="nasa:x", sourceUrl="https://images-assets.nasa.gov/video/x/x~orig.mp4", moment={})
        self.web["https://images-assets.nasa.gov/video/x/x~orig.mp4"] = clip_file("nasa", 12.0)
        out = self.run_restore(timeline(dm, page, nasa), parallel=1)
        self.assertEqual(out["refetched"], 3)
        self.assertEqual(self.fetches(), [("dailymotion", "x8abc12", 12.0, 5.0), ("web", "https://news.example.com/flood-video", 3.0, 5.0)])
        self.assertIn(("download", "https://images-assets.nasa.gov/video/x/x~orig.mp4"), self.calls)

    def test_copies_only_when_re_fetching_is_switched_off(self):
        out = self.run_restore(timeline(clip_scene(0)), refetch=False)
        self.assertEqual((out["refetched"], out["failed"], self.fetches()), (0, 1, []))


def _fields_of(data: bytes) -> list:
    return data.decode().split("|")


# --------------------------------------------------------------------------- #
class Checked(Bench):
    def test_a_photo_without_a_tone_is_checked_against_the_plans_ledger_hash(self):
        doc = timeline(photo_scene(1, tone=None))
        aid = doc["scenes"][0]["semanticMetadata"]["assetId"]
        record = {"items": [{"k": "photo", "u": "example.org/dam.jpg", "h": f"{0xF0F0:016x}", "a": aid}]}
        with mock.patch.object(ledger, "_get_json", lambda k, timeout=20: record if PLAN in k else None), \
                mock.patch.object(r2, "library_enabled", lambda: True):
            out = self.run_restore(doc, parts=[self.part("0001.jpg", photo_file("the plan's picture", 0xF0F1, tone="B"))])
            self.assertEqual((out["restored_from_copy"], self.fetches()), (1, []))    # 1 bit apart: the same picture
            self.r2.objects.clear()
            out = self.run_restore(doc, parts=[self.part("0001.jpg", photo_file("another picture", 0x0F0F00FF))])
        self.assertEqual((out["restored_from_copy"], out["refetched"]), (0, 1))

    def test_a_copy_that_cannot_be_checked_is_not_used_unless_allowed(self):
        doc = timeline(photo_scene(1, tone=None))
        self.dead.add("https://example.org/dam.jpg")
        part = self.part("0001.jpg", photo_file("maybe an earlier pick"))
        out = self.run_restore(doc, parts=[part])
        self.assertEqual((out["restored_from_copy"], out["failed"]), (0, 1))
        self.assertIn("could not be checked", out["failures"][0]["reason"])
        self.assertIn("allow_unverified", out["failures"][0]["reason"])
        self.assertEqual(self.r2.puts, [])
        out = self.run_restore(doc, parts=[part], allow_unverified=True)
        self.assertEqual((out["restored_from_copy"], out["failed"]), (1, 0))
        self.assertIn("(not checked)", out["rows"][0]["from"])

    def test_a_clip_without_a_tone_is_the_timelines_when_its_length_matches(self):
        out = self.run_restore(timeline(clip_scene(0, tone=None)), parts=[self.part("0000.mp4", clip_file("part", 7.70))])
        self.assertEqual((out["restored_from_copy"], self.fetches()), (1, []))

    def test_a_copy_that_does_not_play_or_is_no_picture_is_never_used(self):
        doc = timeline(clip_scene(0), photo_scene(1))
        out = self.run_restore(doc, parts=[self.part("0000.mp4", b"<html>|x|0|A"), self.part("0001.jpg", b"<html>|x|0|C")])
        self.assertEqual((out["restored_from_copy"], out["refetched"]), (0, 2))

    def test_tones_agree_within_what_re_encoding_moves_and_no_further(self):
        a = TONES["C"]
        self.assertTrue(restore.same_tone(a, dict(a, l=a["l"] + 0.02, hi=a["hi"] - 0.05, rg=a["rg"] * 1.04)))
        self.assertFalse(restore.same_tone(a, dict(a, l=a["l"] + 0.05)))
        self.assertFalse(restore.same_tone(a, dict(a, rg=a["rg"] * 1.12)))
        self.assertFalse(restore.same_tone(TONES["A"], TONES["B"]))


# --------------------------------------------------------------------------- #
class SameKey(Bench):
    def test_every_file_goes_back_under_the_link_the_timeline_already_has(self):
        doc = timeline(clip_scene(0), photo_scene(1))
        before = copy.deepcopy(doc)
        out = self.run_restore(doc, parts=[self.part("0000.mp4", clip_file("part0", 7.77))])
        self.assertEqual(doc, before)                                                # the timeline is not touched
        self.assertEqual(self.r2.keys_put(), sorted([
            key("media", "s0000-aaaaaaaaaaaa.mp4"), key("thumbs", "s0000-aaaaaaaaaaaa.jpg"),
            key("preview", "s0000-aaaaaaaaaaaa.mp4"),
            key("media", "s0001-bbbbbbbbbbbb.jpg"), key("thumbs", "s0001-bbbbbbbbbbbb.jpg")]))
        by_key = {p["key"]: p for p in self.r2.puts}
        self.assertEqual({p["bucket"] for p in self.r2.puts}, {BUCKET})
        self.assertEqual({p["cache"] for p in self.r2.puts}, {r2.IMMUTABLE})
        self.assertEqual(by_key[key("media", "s0000-aaaaaaaaaaaa.mp4")]["type"], "video/mp4")
        self.assertEqual(by_key[key("media", "s0001-bbbbbbbbbbbb.jpg")]["type"], "image/jpeg")
        self.assertEqual(by_key[key("thumbs", "s0000-aaaaaaaaaaaa.jpg")]["data"], b"thumb of part0")
        self.assertEqual(by_key[key("preview", "s0000-aaaaaaaaaaaa.mp4")]["data"], b"preview of part0")
        self.assertEqual((out["thumbnails"], out["previews"]), (2, 1))
        self.assertEqual(os.listdir(self.work), [])                                  # no work file left behind
        r2.delete.assert_not_called()

    def test_a_file_of_another_project_or_the_library_is_never_written(self):
        borrowed = photo_scene(1)
        borrowed["media"]["url"] = url("media", "s0001-bbbbbbbbbbbb.jpg", project=OTHER)
        borrowed["media"]["thumbnail"] = url("thumbs", "s0001-bbbbbbbbbbbb.jpg", project=OTHER)
        lib = photo_scene(2, token="cccccccccccc")
        lib["media"]["url"] = f"{LIB_BASE}/photos/lib1.jpg"
        lib["media"].pop("thumbnail")
        out = self.run_restore(timeline(borrowed, lib))
        self.assertEqual((out["missing"], out["failed"], self.r2.puts, self.fetches()), (2, 2, [], []))
        self.assertTrue(all("not this project's own file" in f["reason"] for f in out["failures"]))

    def test_a_key_that_could_resolve_outside_the_projects_folder_is_never_written(self):
        # "projects/<pid>/../<other>/..." names another folder once a client
        # resolves the dots: refused like any other foreign file.
        for bad in (f"projects/{PID}/../{OTHER}/media/s0001-bbbbbbbbbbbb.jpg",
                    f"projects/{PID}/./media/s0001-bbbbbbbbbbbb.jpg",
                    f"projects/{PID}//media/s0001-bbbbbbbbbbbb.jpg",
                    f"projects/{PID}/media\\s0001-bbbbbbbbbbbb.jpg",
                    f"projects/{PID}/"):
            self.assertFalse(restore._ours(PID, (config.R2_BUCKET, bad)), bad)
        self.assertFalse(restore._ours("", (config.R2_BUCKET, "projects//media/a.jpg")))
        self.assertTrue(restore._ours(PID, (config.R2_BUCKET, f"projects/{PID}/media/s0001-bbbbbbbbbbbb.jpg")))
        dotted = photo_scene(1)
        dotted["media"]["url"] = f"{BASE}/projects/{PID}/../{OTHER}/media/s0001-bbbbbbbbbbbb.jpg"
        dotted["media"].pop("thumbnail", None)
        out = self.run_restore(timeline(dotted))
        self.assertEqual((out["failed"], self.r2.puts), (1, []))
        self.assertIn("not this project's own file", out["failures"][0]["reason"])

    def test_a_shared_picture_is_restored_once_for_all_the_scenes_that_show_it(self):
        a, b = photo_scene(1), photo_scene(2)
        b["media"] = dict(a["media"])
        out = self.run_restore(timeline(a, b))
        self.assertEqual((out["links"], out["refetched"], len(self.fetches())), (1, 1, 1))
        self.assertEqual(out["rows"][0]["also"], ["s0002"])


# --------------------------------------------------------------------------- #
class DryRun(Bench):
    def test_a_dry_run_says_what_it_would_do_and_changes_nothing(self):
        gen = photo_scene(3, token="333333333333", provider="generated")
        doc = timeline(clip_scene(0), photo_scene(1), clip_scene(2, token="222222222222", vid="BBBBBBBBBBB"), gen,
                       overlays=[{"type": "split", "template": "CMP_SPLIT_V1",
                                  "media": [{"type": "image", "url": url("split", "014_0-eeeeeeeeeeee.jpg"), "source": "web"}]}])
        self.r2.put(key("media", "s0002-222222222222.mp4"))                         # still there; its small copies are not
        with mock.patch.object(storage, "download", side_effect=AssertionError("a dry run downloads nothing")):
            out = self.run_restore(doc, dry_run=True, parts=[self.part("0000.mp4", clip_file("part0", 7.77))])
        self.assertTrue(out["ok"] and out["dry_run"])
        self.assertEqual((self.r2.puts, self.fetches(), self.thumbs), ([], [], []))
        self.assertEqual(out["would"], {"copy": 1, "refetch": 1, "none": 2, "thumbnails": 4, "previews": 2})
        self.assertEqual((out["links"], out["present"], out["missing"]), (5, 1, 4))
        self.assertEqual((out["restored_from_copy"], out["refetched"], out["failed"]), (0, 0, 0))
        rows = {r["scene"]: r for r in out["rows"]}
        self.assertEqual(rows["s0000"]["did"], "copy")
        self.assertIn("else fetched again from YouTube AAAAAAAAAAA from 476.7 s for 7.8 s", rows["s0000"]["note"])
        self.assertEqual((rows["s0001"]["did"], rows["s0001"]["from"]), ("refetch", "its own address https://example.org/dam.jpg"))
        self.assertEqual((rows["s0003"]["did"], rows["s0003"]["reason"]), ("none", restore.NO_ORIGIN["generated"]))
        self.assertIn("no copy and where it came from was not recorded", rows["graphic 1 (CMP_SPLIT_V1)"]["reason"])
        self.assertEqual(events.summary()["recent"][-1]["event"], "dry_run")


# --------------------------------------------------------------------------- #
class Resume(Bench):
    def test_a_second_run_restores_only_what_is_still_missing(self):
        doc = timeline(clip_scene(0), photo_scene(1))
        self.dead.add("https://example.org/dam.jpg")                                 # the picture's site is down today
        first = self.run_restore(doc)
        self.assertEqual((first["refetched"], first["failed"]), (1, 1))
        puts, self.calls = len(self.r2.puts), []
        self.dead.clear()                                                            # ...and back the next day
        second = self.run_restore(doc)
        self.assertEqual((second["present"], second["missing"], second["refetched"], second["failed"]), (1, 1, 1, 0))
        self.assertEqual(self.fetches(), [("picture", "https://example.org/dam.jpg", "", "")])    # the clip was not fetched again
        self.assertEqual(len(self.r2.puts) - puts, 2)                                # the picture and its thumbnail
        self.calls = []
        third = self.run_restore(doc)
        self.assertEqual((third["missing"], third["rows"], self.calls, len(self.r2.puts) - puts), (0, [], [], 2))

    def test_only_the_small_copies_are_made_again_when_the_file_itself_is_there(self):
        doc = timeline(clip_scene(0))
        self.r2.put(key("media", "s0000-aaaaaaaaaaaa.mp4"), clip_file("the stored clip", 7.77))
        self.r2.put(key("thumbs", "s0000-aaaaaaaaaaaa.jpg"), b"the old thumbnail")
        out = self.run_restore(doc)
        self.assertEqual((out["missing"], out["previews"], out["thumbnails"], self.fetches()), (0, 1, 0, []))
        self.assertEqual(self.r2.keys_put(), [key("preview", "s0000-aaaaaaaaaaaa.mp4")])
        self.assertEqual(self.r2.objects[(BUCKET, key("preview", "s0000-aaaaaaaaaaaa.mp4"))], b"preview of the stored clip")
        self.assertEqual(self.r2.objects[(BUCKET, key("thumbs", "s0000-aaaaaaaaaaaa.jpg"))], b"the old thumbnail")
        self.assertEqual(out["rows"][0]["did"], "present")

    def test_a_file_that_appeared_meanwhile_is_not_overwritten(self):
        doc = timeline(photo_scene(1))
        real_fetch = self._picture

        def slow_fetch(link, dest, page_url="", thumbnail=""):
            self.r2.put(key("media", "s0001-bbbbbbbbbbbb.jpg"), b"restored by another run")
            return real_fetch(link, dest, page_url, thumbnail)
        with mock.patch.object(imagefix, "fetch", slow_fetch):
            out = self.run_restore(doc)
        self.assertEqual(self.r2.objects[(BUCKET, key("media", "s0001-bbbbbbbbbbbb.jpg"))], b"restored by another run")
        self.assertEqual((out["refetched"], out["failed"], out["rows"][0]["did"]), (0, 0, "present"))

    def test_a_file_storage_cannot_answer_for_is_left_alone(self):
        doc = timeline(photo_scene(1))
        self.r2.list_fails = True                                                    # no listing: each file is asked for
        self.r2.head_errors.add(key("media", "s0001-bbbbbbbbbbbb.jpg"))
        self.r2.put(key("thumbs", "s0001-bbbbbbbbbbbb.jpg"))
        out = self.run_restore(doc)
        self.assertEqual((out["unchecked"], out["missing"], out["rows"], self.r2.puts, self.fetches()), (1, 0, [], [], []))

    def test_parts_still_in_r2_are_found_by_the_listing(self):
        doc = timeline(clip_scene(0))
        self.r2.put(key("parts", f"{PLAN}/0000.mp4"), clip_file("the part in R2", 7.77))
        self.r2.put(key("parts", f"{PLAN}/render_000.mp4"), b"a render chunk, not a scene file")
        out = self.run_restore(doc)
        self.assertEqual((out["restored_from_copy"], self.fetches()), (1, []))
        self.assertEqual(self.r2.objects[(BUCKET, key("media", "s0000-aaaaaaaaaaaa.mp4"))], clip_file("the part in R2", 7.77))
        self.assertEqual(self.r2.objects[(BUCKET, key("parts", f"{PLAN}/0000.mp4"))], clip_file("the part in R2", 7.77))


# --------------------------------------------------------------------------- #
class Failures(Bench):
    def test_what_cannot_be_restored_is_listed_with_its_reason_in_timeline_order(self):
        self.dead.update({"BBBBBBBBBBB", "https://example.org/gone.jpg"})
        doc = timeline(clip_scene(0),
                       clip_scene(1, token="111111111111", vid="BBBBBBBBBBB"),
                       photo_scene(2, token="222222222222", src="https://example.org/gone.jpg"),
                       photo_scene(3, token="333333333333", provider="generated"),
                       photo_scene(4, token="444444444444", provider="noaa_goes"),
                       overlays=[{"type": "split", "template": "CMP_SPLIT_V1",
                                  "media": [{"type": "image", "url": url("split", "014_0-eeeeeeeeeeee.jpg"), "source": "web"}]}])
        out = self.run_restore(doc)
        self.assertEqual((out["refetched"], out["failed"], out["missing"]), (1, 5, 6))
        self.assertEqual([f["scene"] for f in out["failures"]],
                         ["s0001", "s0002", "s0003", "s0004", "graphic 1 (CMP_SPLIT_V1)"])
        why = {f["scene"]: f["reason"] for f in out["failures"]}
        self.assertEqual(why["s0001"], "YouTube did not give the clip again (MEDIA_UNAVAILABLE)")
        self.assertIn("its site no longer gives the picture", why["s0002"])
        self.assertEqual(why["s0003"], restore.NO_ORIGIN["generated"])
        self.assertEqual(why["s0004"], restore.NO_ORIGIN["noaa_goes"])
        self.assertIn("where it came from was not recorded", why["graphic 1 (CMP_SPLIT_V1)"])
        # Nothing was stored for them: the render's quality check finds and repairs those scenes.
        self.assertEqual(self.r2.keys_put(), sorted([key("media", "s0000-aaaaaaaaaaaa.mp4"),
                                                     key("thumbs", "s0000-aaaaaaaaaaaa.jpg"),
                                                     key("preview", "s0000-aaaaaaaaaaaa.mp4")]))
        log = events.summary()["recent"]
        self.assertEqual(sum(1 for e in log if e["event"] == "not_restored"), 5)
        last = log[-1]
        self.assertEqual((last["stage"], last["event"], last["level"]), ("restore", "summary", "warning"))
        self.assertEqual({k: last["data"][k] for k in ("restored_from_copy", "refetched", "failed")},
                         {"restored_from_copy": 0, "refetched": 1, "failed": 5})
        self.assertIn("seconds", last["data"])

    def test_a_source_that_gives_far_too_little_is_not_stored(self):
        self.short = {"AAAAAAAAAAA": 2.0}
        out = self.run_restore(timeline(clip_scene(0, clean=False, clip=6.4)))
        self.assertEqual((out["failed"], self.r2.puts), (1, []))
        self.assertEqual(out["failures"][0]["reason"], "its source only gave 2.0 s of the 6.4 s clip")

    def test_past_the_time_box_nothing_more_is_started_and_the_next_run_goes_on(self):
        doc = timeline(clip_scene(0), photo_scene(1))
        with mock.patch.object(restore.time, "time", side_effect=_clock(step=400.0)):
            out = self.run_restore(doc, seconds=300)
        self.assertTrue(out["timed_out"])
        self.assertEqual((out["failed"], self.r2.puts, self.fetches()), (2, [], []))
        self.assertTrue(all("time ran out" in f["reason"] for f in out["failures"]))
        self.assertEqual(ytdlp.DEADLINE[0], 0.0)                                     # the download deadline is put back
        again = self.run_restore(doc)
        self.assertEqual((again["refetched"], again["failed"]), (2, 0))

    def test_a_failed_upload_is_a_failure_of_that_file_only(self):
        doc = timeline(clip_scene(0), photo_scene(1))
        real = self.r2.upload

        def upload(path, k, **kw):
            if k.endswith(".mp4") and "/media/" in k:
                raise RuntimeError("R2 upload failed after 3 attempt(s): HTTP 503")
            return real(path, k, **kw)
        with mock.patch.object(r2, "upload", upload):
            out = self.run_restore(doc, parallel=1)
        self.assertEqual((out["refetched"], out["failed"]), (1, 1))
        self.assertIn("R2 upload failed", out["failures"][0]["reason"])
        self.assertNotIn((BUCKET, key("thumbs", "s0000-aaaaaaaaaaaa.jpg")), self.r2.objects)   # no thumbnail of a file that is not there

    def test_it_refuses_to_run_without_r2_or_a_project(self):
        with self.assertRaisesRegex(ValueError, "project_id"):
            restore.run({"project_id": "../x"}, timeline(clip_scene(0)), self.work)
        with mock.patch.object(config, "R2_BUCKET", ""):
            with self.assertRaisesRegex(ValueError, "R2 is not configured"):
                self.run_restore(timeline(clip_scene(0)))


def _clock(step: float):
    """time.time() that jumps `step` seconds on every call."""
    now = [1_800_000_000.0]

    def tick():
        now[0] += step
        return now[0]
    return tick


# --------------------------------------------------------------------------- #
class PartsLookup(Bench):
    def test_given_copies_by_path_or_by_name_and_only_scene_files(self):
        p = restore.Parts(PID, given=[{"path": f"projects/{PID}/parts/{PLAN}/0007.mp4", "url": "https://a/1"},
                                      {"path": f"projects/{PID}/parts/{PLAN}/render_003.mp4", "url": "https://a/2"},
                                      {"path": f"projects/{PID}/parts/{PLAN}/0008.jpg", "url": "not a link"}])
        self.assertEqual(sorted(p.by_name), ["0007.mp4"])
        self.assertEqual(p.plan_jobs(), [PLAN])
        q = restore.Parts(PID, given={"0007.MP4": "https://a/1"})
        link = restore.inventory(timeline(clip_scene(7)))[0][0]
        self.assertEqual([c["url"] for c in q.candidates(link)], ["https://a/1"])
        self.assertEqual(q.candidates(restore.inventory(timeline(photo_scene(7)))[0][0]), [])   # a .jpg is not the .mp4 part

    def test_the_apps_storage_is_asked_through_the_broker_for_the_named_plan_jobs(self):
        asked = []

        def read_url(bucket, path, project_id, job_id, read_ttl=3600):
            asked.append((bucket, path, project_id, job_id))
            if path.endswith("0000.mp4"):
                return "https://app.supabase.co/signed/0000"
            raise storage.StorageError("storage broker refused (500): Object not found")
        self.web["https://app.supabase.co/signed/0000"] = clip_file("the broker's copy", 7.77)
        doc = timeline(clip_scene(0), photo_scene(1))
        with mock.patch.object(config, "STORAGE_BROKER_URL", "https://app/functions/v1/worker-storage"), \
                mock.patch.object(storage, "broker_read_url", read_url):
            out = self.run_restore(doc, plan_jobs=[PLAN], parallel=1)
        self.assertEqual(sorted(asked), [("video-media", f"projects/{PID}/parts/{PLAN}/0000.mp4", PID, "job-restore"),
                                         ("video-media", f"projects/{PID}/parts/{PLAN}/0001.jpg", PID, "job-restore")])
        self.assertEqual((out["restored_from_copy"], out["refetched"]), (1, 1))      # no part for the photo: its source

    def test_a_refusing_broker_is_asked_once_not_once_per_scene(self):
        asked = []

        def read_url(bucket, path, project_id, job_id, read_ttl=3600):
            asked.append(path)
            raise storage.StorageError("storage broker refused (403): job is not running for this project")
        doc = timeline(*[clip_scene(n, token=f"{n:012d}") for n in range(12)])
        with mock.patch.object(config, "STORAGE_BROKER_URL", "https://app/functions/v1/worker-storage"), \
                mock.patch.object(storage, "broker_read_url", read_url):
            out = self.run_restore(doc, plan_jobs=[PLAN], parallel=1)
        self.assertEqual(len(asked), 1)
        self.assertEqual((out["refetched"], out["failed"]), (12, 0))                 # every shot from its source instead

    def test_without_a_broker_or_a_key_the_apps_storage_is_not_asked(self):
        p = restore.Parts(PID, plan_jobs=[PLAN])
        self.assertEqual(p.candidates(restore.inventory(timeline(clip_scene(0)))[0][0]), [])
        self.assertIn("no way to read", p.refused)


# --------------------------------------------------------------------------- #
class Polish(Bench):
    def link(self, scene):
        return restore.inventory(timeline(scene))[0][0]

    def test_a_restored_file_is_polished_as_the_plan_polishes_a_chosen_file(self):
        path = self._write(os.path.join(self.work, "x.mp4"), clip_file("x", 5))
        self.polish_does = ("upscale_clip", "upscale_image")
        self.assertEqual(restore.polish(self.link(clip_scene(0)), path), "upscaled")
        self.assertEqual([p[0] for p in self.polished], ["upscale_clip"])            # landscape style: no framing asked
        self.polished.clear()
        self.polish_does = ("frame_vertical",)
        with mock.patch.object(config, "ALLOW_VERTICAL", True):
            self.assertEqual(restore.polish(self.link(clip_scene(0)), path), "framed")
        self.assertEqual([p[0] for p in self.polished], ["frame_vertical"])          # framed: not sharpened as well
        self.polished.clear()
        self.polish_does = ("upscale_image",)
        self.assertEqual(restore.polish(self.link(photo_scene(1)), path), "upscaled")

    def test_archive_film_generated_pictures_and_graphics_are_left_as_they_are(self):
        path = self._write(os.path.join(self.work, "x.mp4"), clip_file("x", 5))
        film = clip_scene(0)
        film["semanticMetadata"]["provider"] = "archive_org"
        self.assertEqual(restore.polish(self.link(film), path), "")
        self.assertEqual(restore.polish(self.link(photo_scene(1, provider="generated")), path), "")
        look = restore.Link(bucket=BUCKET, key=key("split", "014_0-e.jpg"), kind="image", role="look", label="graphic 1")
        self.assertEqual(restore.polish(look, path), "")
        with mock.patch.object(config, "UPSCALE_ENABLED", False):
            self.assertEqual(restore.polish(self.link(clip_scene(0)), path), "")
        self.assertEqual(self.polished, [])


# --------------------------------------------------------------------------- #
class Timeline(Bench):
    def test_the_saved_document_from_the_input_a_link_or_an_r2_key(self):
        doc = timeline(clip_scene(0))
        self.assertIs(restore.load_timeline({"timeline": doc}), doc)
        payload = json.dumps({"input": {"action": "render", "timeline": doc}}).encode()

        class Reply:
            status_code, content = 200, payload
        with mock.patch.object(restore.requests, "get", return_value=Reply()) as get:
            got = restore.load_timeline({"timeline_url": "https://app.supabase.co/storage/v1/object/sign/video-media/jobs/p/j.json?token=t"})
        self.assertEqual(got, doc)                                                   # the render payload the app keeps
        self.assertEqual(get.call_count, 1)
        with mock.patch.object(r2, "get_bytes", return_value=json.dumps(doc).encode()) as get_bytes:
            self.assertEqual(restore.load_timeline({"timeline_key": "pod/x/timeline.json"}), doc)
            self.assertEqual(restore.load_timeline({"timeline_url": f"{BASE}/pod/x/timeline.json"}), doc)
        self.assertEqual(get_bytes.call_args_list[1].args[0], "pod/x/timeline.json")  # our own link: through the S3 API

    def test_no_timeline_is_said_plainly(self):
        with self.assertRaisesRegex(ValueError, "needs the saved timeline"):
            restore.load_timeline({"project_id": PID})
        with self.assertRaisesRegex(ValueError, "no scenes"):
            restore.load_timeline({"timeline": {"scenes": []}})

        class Gone:
            status_code, content = 403, b""
        with mock.patch.object(restore.requests, "get", return_value=Gone()):
            with self.assertRaisesRegex(ValueError, "HTTP 403"):
                restore.load_timeline({"timeline_url": "https://app.supabase.co/expired"})


# --------------------------------------------------------------------------- #
class HandlerAction(Bench):
    def job(self, **inp) -> dict:
        return {"id": "job-restore-1", "input": {"action": "restore_media", "project_id": PID, **inp}}

    def test_restore_media_is_an_action_that_never_writes_the_project(self):
        doc = timeline(clip_scene(0), photo_scene(1), style="news_compilation")
        seen = {}
        real_run = restore.run

        def run(inp, d, work, report=None, thumbnail=None, preview=None):
            seen.update(vertical=config.ALLOW_VERTICAL, thumbnail=thumbnail, preview=preview,
                        project=report.project_id, job=inp.get("_job_id"))
            return real_run(inp, d, work, report, thumbnail=lambda p, w, t: "", preview=lambda p, w, t: "")
        with mock.patch.object(restore, "run", run), \
                mock.patch.object(handler.storage, "broker_events", side_effect=AssertionError("no event reaches the app")):
            out = handler.handler(self.job(timeline=doc))
        self.assertEqual((out["ok"], out["action"]), (True, "restore_media"))
        self.assertEqual({k: out[k] for k in ("restored_from_copy", "refetched", "failed")},
                         {"restored_from_copy": 0, "refetched": 2, "failed": 0})
        self.assertIsInstance(out["seconds"], float)
        last = out["events"]["recent"][-1]                                           # the event: in the result's own log
        self.assertEqual((last["stage"], last["event"], last["data"]["refetched"]), ("restore", "summary", 2))
        # The style the timeline was planned with was in force (its vertical clips are framed), and is put back.
        self.assertEqual((seen["vertical"], config.ALLOW_VERTICAL), (True, False))
        self.assertEqual((seen["thumbnail"], seen["preview"]), (handler._thumbnail, handler._preview_proxy))
        self.assertEqual((seen["project"], seen["job"]), ("", "job-restore-1"))      # progress to the job's status only
        handler.storage.patch_project.assert_not_called()

    def test_a_restore_that_cannot_start_reports_it_and_leaves_the_project_alone(self):
        out = handler.handler(self.job())
        self.assertEqual((out["ok"], out["action"]), (False, "restore_media"))
        self.assertIn("needs the saved timeline", out["error"])
        handler.storage.patch_project.assert_not_called()

    def test_whatever_breaks_around_a_restore_never_marks_the_project_failed(self):
        # An error outside restore.run (here: the phase line itself) reaches the
        # handler's catch-all, which marks a build or render failed - never a restore.
        real_phase = handler.events.phase

        def phase(name):
            if name == "restore":
                raise RuntimeError("broke before the restore started")
            return real_phase(name)
        with mock.patch.object(handler.events, "phase", side_effect=phase):
            out = handler.handler(self.job(timeline=timeline(clip_scene(0))))
        self.assertFalse(out["ok"])
        self.assertIn("broke before the restore started", out["error"])
        handler.storage.patch_project.assert_not_called()

    def test_a_dry_run_through_the_handler(self):
        out = handler.handler(self.job(timeline=timeline(clip_scene(0)), dry_run=True))
        self.assertEqual((out["ok"], out["dry_run"], out["would"]["refetch"], self.r2.puts), (True, True, 1, []))


# --------------------------------------------------------------------------- #
class WhatPlansRecordForALaterRestore(Bench):
    """The deleted projects' contrast pictures had no copy and no recorded address: new plans keep it."""

    def test_a_contrast_pictures_address_is_kept_on_the_look_and_a_restore_fetches_it_again(self):
        from tests.test_split_images import doc_with, jpeg_bytes
        doc = doc_with([{"label": "Solid ground"}, {"label": "Submerged mud"}])
        queries = []

        def search(q, limit=6, full_screen=True):
            queries.append(q)
            return [media.MediaAsset(kind="image", source="web", url=f"https://img/{len(queries)}.jpg")]
        stored = {}

        def put(local, name):
            stored[name] = local
            return url(name.split("/")[0], name.split("/")[1].replace(".jpg", "-abcdefabcdef.jpg"))
        resp = mock.Mock(status_code=200, content=jpeg_bytes())
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", side_effect=search), \
                mock.patch("requests.get", return_value=resp):
            self.assertEqual(handler._bind_split_images(doc, self.work, put), 1)
        ov = doc["overlays"][0]
        self.assertEqual([m["sourceUrl"] for m in ov["media"]], ["https://img/1.jpg", "https://img/2.jpg"])
        self.assertEqual([m["source"] for m in ov["media"]], ["web", "web"])
        # Years later the files are gone: the look's pictures come again from those addresses, unpolished.
        shutil.rmtree(self.work)
        os.makedirs(self.work)
        out = self.run_restore(timeline(clip_scene(0), overlays=[ov]), refetch=True)
        self.assertEqual((out["refetched"], out["failed"]), (3, 0))
        self.assertEqual([c[1] for c in self.fetches() if c[0] == "picture"], ["https://img/1.jpg", "https://img/2.jpg"])
        self.assertIn(key("split", "000_0-abcdefabcdef.jpg"), self.r2.keys_put())
        self.assertEqual([p[0] for p in self.polished], ["upscale_clip"])             # the scene's clip only

    def test_a_web_pictures_page_and_small_copy_are_kept_on_the_scene_and_used_to_fetch_it_again(self):
        from tests.test_pipeline import simple_plan
        from src import timeline as tl_mod
        segments, shots, assets = simple_plan(2)
        assets[0] = media.MediaAsset(kind="image", source="web_image", url="https://host.example/a.jpg",
                                     local_path="file:///tmp/a.jpg", page_url="https://host.example/page",
                                     thumbnail="https://duckduckgo.example/small.jpg")
        doc = tl_mod.build(segments, shots, assets, audio_url="file:///tmp/vo.mp3", audio_duration=6.0, inp={})
        sem = [s["semanticMetadata"] for s in doc["scenes"]]
        self.assertEqual((sem[0]["pageUrl"], sem[0]["sourceThumbnail"]),
                         ("https://host.example/page", "https://duckduckgo.example/small.jpg"))
        self.assertNotIn("pageUrl", sem[1])                                          # a clip has none: nothing added
        scene = photo_scene(1, src="https://host.example/a.jpg")
        scene["semanticMetadata"].update(pageUrl="https://host.example/page", sourceThumbnail="https://duckduckgo.example/small.jpg")
        self.run_restore(timeline(scene))
        self.assertEqual(self.fetches(), [("picture", "https://host.example/a.jpg", "https://host.example/page",
                                           "https://duckduckgo.example/small.jpg")])


# --------------------------------------------------------------------------- #
@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class RealFiles(unittest.TestCase):
    """The tone check on real files: the plan's own measurement tells a shot from another."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="restore_real_")

        def clip(name, source, crf="23", scale="640:360"):
            path = os.path.join(cls.dir, name)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", "4", "-vf", f"scale={scale}",
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", crf, "-pix_fmt", "yuv420p", path],
                           check=True, capture_output=True, timeout=120)
            return path
        cls.a = clip("a.mp4", "testsrc2=size=640x360:rate=30")
        cls.a_again = clip("a_again.mp4", "testsrc2=size=640x360:rate=30", crf="30", scale="1280:720")   # re-encoded, upscaled
        cls.b = clip("b.mp4", "mandelbrot=size=640x360:rate=30")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def link(self, path) -> restore.Link:
        seconds = restore._clip_seconds(path)
        tone = grade.measure({"type": "video", "url": path, "clipSeconds": round(seconds, 2)})
        return restore.Link(bucket=BUCKET, key=key("media", "s0000-a.mp4"), kind="video", role="scene", label="s0000",
                            clip_seconds=round(seconds, 2), tone=tone)

    def test_a_re_encoded_copy_of_the_shot_is_the_shot_and_another_clip_is_not(self):
        link = self.link(self.a)
        self.assertTrue(grade._valid_tone(link.tone))
        self.assertEqual(restore.readable(link, self.a_again), "")
        self.assertEqual(restore.same_shot(link, self.a_again, {})[0], True)
        self.assertEqual(restore.readable(link, self.b), "")                         # the very same length...
        same, why = restore.same_shot(link, self.b, {})
        self.assertEqual((same, why), (False, "another shot (its colours are not the ones the plan measured)"))

    def test_a_file_that_is_not_a_clip_is_not_readable(self):
        junk = os.path.join(self.dir, "junk.mp4")
        with open(junk, "wb") as fh:
            fh.write(b"<html>not a video</html>" * 200)
        self.assertEqual(restore.readable(self.link(self.a), junk), "the copy does not play")
        self.assertEqual(restore.readable(restore.Link(bucket=BUCKET, key="k.jpg", kind="image", role="scene", label="s"), junk),
                         "the copy is not a picture")


if __name__ == "__main__":
    unittest.main()
