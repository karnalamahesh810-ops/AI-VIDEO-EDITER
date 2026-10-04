"""
Re-cutting the long shots of a sourced timeline (src/recut.py, handler action
"recut"). The owner, 2026-10-04: "some of the clips run more than seven
seconds" - two finished videos had 79 and 100 such shots, up to 33 s.

A long scene is cut on its words into pieces of 2.5-7 s that tile its frames
exactly; the first piece keeps the scene's own shot, the others get its
runner-ups, another moment of its own video or a fresh search; a piece nothing
is found for goes back into its neighbour. A dry run writes nothing; an apply
keeps the old timeline on R2 first and writes the project once.

Offline: R2 is a dict, every search, download and judgement is a stub, files
are small text files ("clip|name|seconds", "photo|name").
"""
import copy
import json
import math
import os
import random
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import (config, events, gapfill, grade, ledger, media, r2, recut, shotcap, storage,  # noqa: E402
                 timeline, upscale, ytdlp)

PID = "9c467873-42fb-46c9-8486-7870aac89314"
JOB = "job-recut-1"
BASE = "https://pub-test.r2.dev"
BUCKET = "videos"


# --------------------------------------------------------------------------- #
# Timelines
# --------------------------------------------------------------------------- #

def spoken(text: str, t0: float, t1: float, pause_after=()) -> list:
    """Word timings for `text` spoken evenly from t0 to t1; `pause_after` (word index -> s) adds a breath."""
    toks = text.split()
    extra = sum(pause_after.values()) if isinstance(pause_after, dict) else 0.0
    step = (t1 - t0 - extra) / max(1, len(toks))
    out, t = [], t0
    for k, w in enumerate(toks):
        out.append({"text": w, "start": round(t, 3), "end": round(t + 0.85 * step, 3)})
        t += step + (pause_after.get(k, 0.0) if isinstance(pause_after, dict) else 0.0)
    return out


LINE = ("The reservoir is falling faster than anyone planned. Boats sit on dry mud, and the marina has closed "
        "for good. Nobody knows when the water will come back to this valley again.")


def url(folder: str, name: str) -> str:
    return f"{BASE}/projects/{PID}/{folder}/{name}"


def clip_scene(n: int, start: int, frames: int, fps: int, text: str = LINE, vid: str = None, at: float = 100.0,
               clip: float = None, **extra) -> dict:
    vid = vid or f"V{n:010d}"
    t0, t1 = start / fps, (start + frames) / fps
    s = {"id": f"s{n:04d}", "startFrame": start, "durationInFrames": frames, "text": text,
         "words": spoken(text, t0 + 0.05, t1 - 0.05), "visualType": "footage", "query": "Lake Powell boats",
         "media": {"type": "video", "url": url("media", f"s{n:04d}-aaaaaaaaaaaa.mp4"), "source": "youtube",
                   "license": "unverified — you must hold the rights", "attribution": f"YouTube: clip {n}",
                   "thumbnail": url("thumbs", f"s{n:04d}-aaaaaaaaaaaa.jpg"),
                   "previewUrl": url("preview", f"s{n:04d}-aaaaaaaaaaaa.mp4"),
                   "clipSeconds": round(clip if clip is not None else frames / fps + 0.4, 2),
                   "tone": {"l": 0.4, "lo": 0.1, "hi": 0.9, "s": 0.2, "rg": 1.0, "bg": 1.0, "v": 1}},
         "motion": "none", "effect": "color-shift", "frame": "full", "treatment": "film", "transition": "none",
         "visualTreatment": {"template": "LIB_DT_LETTER_DROP", "transitionIn": "none"},
         "reviewRequired": True, "reviewReason": "Licence unverified — confirm you hold the rights",
         "semanticMetadata": {"intent": "boats stranded on the dry lake bed", "searchQuery": "Lake Powell boats",
                              "subject": "Lake Powell", "subjectType": "place", "eventWindow": "",
                              "sceneIntent": {"entities": ["Lake Powell"], "locations": ["Utah"],
                                              "visual_subjects": ["boats on mud"], "specificity": "location"},
                              "assetId": f"yt:{vid}", "provider": "youtube",
                              "sourceUrl": f"https://www.youtube.com/watch?v={vid}&t={int(at)}",
                              "moment": {"start": at, "clean": True}, "alternatives": []}}
    s.update(extra)
    return s


def photo_scene(n: int, start: int, frames: int, fps: int, text: str = LINE, **extra) -> dict:
    s = clip_scene(n, start, frames, fps, text)
    s["visualType"] = "image"
    s["motion"] = "push-offcenter"
    s["media"] = {"type": "image", "url": url("media", f"s{n:04d}-bbbbbbbbbbbb.jpg"), "source": "web_image",
                  "license": "unverified — you must hold the rights", "thumbnail": url("thumbs", f"s{n:04d}.jpg")}
    s["semanticMetadata"].update(assetId=f"web_image:https://img.example/{n}.jpg",
                                 sourceUrl=f"https://img.example/{n}.jpg", provider="web_image", moment={})
    s.update(extra)
    return s


def anim_scene(n: int, start: int, frames: int, fps: int, text: str = "Forty feet below full pool.") -> dict:
    t0, t1 = start / fps, (start + frames) / fps
    return {"id": f"s{n:04d}", "startFrame": start, "durationInFrames": frames, "text": text,
            "words": spoken(text, t0 + 0.05, t1 - 0.05), "visualType": "animation",
            "media": {"type": "animation", "url": "", "source": "template"},
            "animation": {"type": "stat", "template": "LIB_STAT", "text": "40 FT"}, "motion": "none",
            "transition": "none", "semanticMetadata": {}}


def empty_scene(n: int, start: int, frames: int, fps: int, text: str = LINE) -> dict:
    s = clip_scene(n, start, frames, fps, text)
    s["media"] = {"type": "color", "url": "", "source": "none"}
    s["semanticMetadata"].update(assetId="", sourceUrl="", moment={}, provider="")
    s["reviewReason"] = "No media found for this beat"
    return s


def doc_of(scenes: list, fps: int, overlays=None) -> dict:
    total = sum(s["durationInFrames"] for s in scenes)
    return {"schemaVersion": 2, "fps": fps, "width": 1920, "height": 1080, "durationInFrames": total,
            "audio": {"url": "https://app.example/vo.mp3", "volume": 1.0},
            "bgm": {"url": "bgm://investigative", "genre": "investigative", "volume": 0.14},
            "music": {"duck": 0.55, "sections": [{"mood": "investigative", "startFrame": 0, "endFrame": total}]},
            "captions": {"enabled": True, "position": "bottom", "accent": "#FFD400", "fontFamily": "Inter"},
            "scenes": scenes, "overlays": list(overlays or []),
            "sfx": [{"name": "whoosh-soft", "startFrame": scenes[1]["startFrame"] - 10 if len(scenes) > 1 else 5,
                     "volume": 0.3, "durationFrames": 40, "kind": "transition"}],
            "sfxVolume": 1.0, "sfxEnabled": True, "lookSounds": {"intensity": 0.9},
            "ambience": {"enabled": True, "beds": [{"name": "wind-soft", "startFrame": 0, "durationInFrames": total}]},
            "meta": {"sceneCount": len(scenes), "videoStyle": "", "warnings": [], "cutsPerMinute": 10.0,
                     "story": {"kind": "news", "event": "Lake Powell falling", "places": ["Utah"]},
                     "voiceLufs": -18.0}}


def lay_out(makers: list, fps: int) -> list:
    """[(maker, seconds, kwargs)] -> scenes laid end to end from frame 0."""
    out, at = [], 0
    for n, (make, secs, kw) in enumerate(makers):
        frames = int(round(secs * fps))
        out.append(make(n, at, frames, fps, **kw))
        at += frames
    return out


def sound_and_graphics(doc: dict) -> dict:
    return json.loads(json.dumps({k: v for k, v in doc.items() if k not in ("scenes", "meta")}, sort_keys=True))


# --------------------------------------------------------------------------- #
# The fakes
# --------------------------------------------------------------------------- #

def _fields(path: str) -> list:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace").split("|")


class Store:
    def __init__(self):
        self.objects, self.order = {}, []

    def head(self, k, bucket=""):
        return None if (bucket or BUCKET, k) not in self.objects else {"size": 1, "etag": "", "type": ""}

    def upload(self, path, k, content_type="video/mp4", deadline=0.0, bucket="", base="", cache_control=""):
        with open(path, "rb") as fh:
            self.objects[(bucket or BUCKET, k)] = fh.read()
        self.order.append(("upload", k))
        return f"{BASE}/{k}"

    def upload_bytes(self, data, k, content_type="application/json", deadline=0.0, bucket="", base="",
                     cache_control=""):
        self.objects[(bucket or BUCKET, k)] = data
        self.order.append(("bytes", k))
        return f"{BASE}/{k}"


class Bench(unittest.TestCase):
    """Everything a re-cut touches, faked."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="recut_test_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.r2 = Store()
        self.calls = []                 # every fetch, search and judgement, in order
        self.searches = []
        self.found_for = None           # (context, visual type, n) -> what a search gives (None: nothing)
        self.judge_keep = True
        self.dead = set()               # YouTube ids that no longer download
        self.lengths = {}               # YouTube id -> its length (s)
        self.written = []
        self.lock = threading.Lock()
        events.start_job("job-recut-test", "")

        def patch(obj, name, value):
            p = mock.patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)

        for name, value in (("R2_ACCOUNT_ID", "acct"), ("R2_ACCESS_KEY_ID", "id"), ("R2_SECRET_ACCESS_KEY", "s"),
                            ("R2_BUCKET", BUCKET), ("R2_PUBLIC_BASE", BASE), ("UPSCALE_ENABLED", False),
                            ("ALLOW_VERTICAL", False), ("SUPABASE_SERVICE_KEY", "service"),
                            ("SUPABASE_URL", "https://app.example"), ("STORAGE_BROKER_URL", ""),
                            ("SOURCE_WORKERS", 4), ("HOOK_SECONDS", 0.0), ("STILL_MOTION", ""),
                            ("FALLBACK_MOMENT_GAP_SECONDS", 30.0), ("PICK_A_SHOT", False)):
            patch(config, name, value)
        patch(r2, "head", self.r2.head)
        patch(r2, "upload", self.r2.upload)
        patch(r2, "upload_bytes", self.r2.upload_bytes)
        patch(r2, "delete", mock.Mock(side_effect=AssertionError("a re-cut never deletes")))
        patch(storage, "patch_project", mock.Mock(side_effect=self._patch_project))
        patch(media, "reset_cache", lambda: None)
        patch(media, "fetch_clean_clip", self._clean_clip)
        patch(media, "source_for_segment", self._search)
        patch(media, "judge_clip", self._judge)
        patch(media, "_yt_info", lambda vid, timeout=60: ({"duration": self.lengths.get(vid, 3600)}, ""))
        patch(media, "_asset_ok", lambda a: (True, ""))
        patch(media, "motion_rejects", lambda p: "")
        patch(media, "slop_reason", lambda p, label="", source_url="": "")
        patch(media, "_photo_seen_before", lambda p: False)
        patch(timeline, "_clip_seconds", self._clip_seconds)
        patch(grade, "measure", lambda m, timeout=20.0: None)
        patch(upscale, "upscale_assets", lambda assets, deadline_seconds=0.0: {"queued": 0})
        patch(ledger, "moment_used", lambda vid, a=None, b=None: False)
        patch(ledger, "photo_used", lambda u="", h=None: False)
        patch(ledger, "note", mock.Mock(return_value=0))
        patch(ledger, "save", mock.Mock(return_value=True))
        patch(ledger, "start_loading", mock.Mock(return_value=False))
        patch(shotcap, "_reach", lambda u, want: True)
        patch(shotcap, "_probe", lambda src: 0.0)
        patch(handler, "_thumbnail", lambda path, work, tag: "")
        patch(handler, "_preview_proxy", lambda path, work, tag: "")
        patch(handler, "_require_youtube", lambda: None)
        patch(handler, "_require_ai_credit", lambda: None)

    # ---- the fakes ---------------------------------------------------------
    def _write(self, name: str, data: str) -> str:
        with self.lock:
            path = os.path.join(self.work, f"{len(os.listdir(self.work))}_{name}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data)
        return path

    def _patch_project(self, project_id, fields, wait=False):
        self.written.append((project_id, dict(fields)))
        self.r2.order.append(("project", ",".join(sorted(fields))))
        return True

    def _clean_clip(self, vid, out_dir, start, need, title=""):
        with self.lock:
            self.calls.append(("clean", vid, round(start, 1), round(need, 2)))
        if vid in self.dead:
            return "", True, 0
        return self._write(f"yt_{vid}.mp4", f"clip|yt:{vid}@{start}|{round(need + 0.5, 2)}"), True, 0

    def _clip_seconds(self, asset):
        path = getattr(asset, "local_path", "") or ""
        if path and os.path.isfile(path):
            f = _fields(path)
            if f[0] == "clip":
                return float(f[2])
            return 0.0
        return float(getattr(asset, "duration", 0) or 0)

    def _judge(self, path, job, label="", source_url=""):
        with self.lock:
            self.calls.append(("judge", _fields(path)[1], job.get("context", "")[:30]))
        keep = self.judge_keep(path, job) if callable(self.judge_keep) else self.judge_keep
        return keep, ({"score": 0.81, "quality": 0.7, "description": "boats on a dry lake bed", "model": "stub",
                       "specificity": "location"} if keep else {"score": 0.3})

    def _search(self, query, seconds, work_dir, *, visual_type="footage", nth=0, used=None, fallbacks=None,
                prompt="", allow_youtube=None, allow_stock=None, require_cc=None, intent="", context="",
                subject_type="", subject="", event_window="", scene_intent=None, hook=False, recency=""):
        with self.lock:
            n = len(self.searches)
            self.searches.append({"query": query, "seconds": seconds, "visual_type": visual_type, "nth": nth,
                                  "used": set(used or ()), "fallbacks": list(fallbacks or []), "intent": intent,
                                  "context": context, "subject": subject, "scene_intent": scene_intent,
                                  "recency": recency})
            self.calls.append(("search", context[:30]))
        if self.found_for is not None:
            got = self.found_for(context, visual_type, n, seconds, used)
            if got is not None or self.found_for:
                return got
        return self.fresh(visual_type, n, seconds, used)

    def fresh(self, visual_type: str, n: int, seconds: float, used=None):
        """A new clip or picture nobody shows (the provider skips what `used` holds)."""
        while True:
            if visual_type == "image":
                a = media.MediaAsset(kind="image", source="web_image", url=f"https://img.example/new{n}.jpg",
                                     attribution="A photo", license="unverified — you must hold the rights",
                                     relevance_score=0.77, quality=0.6, content_description="a dry marina")
            else:
                vid = f"F{n:010d}"
                a = media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t=10",
                                     duration=seconds, attribution="YouTube: drone", relevance_score=0.79,
                                     license="unverified — you must hold the rights", moment={"start": 10.0},
                                     review_required=True, review_reason="Licence unverified — confirm you hold the rights")
            if used is None or a.identity not in used:
                break
            n += 1000
        if a.kind == "image":
            a.local_path = self._write(f"photo{n}.jpg", f"photo|{a.url}|0")
        else:
            a.local_path = self._write(f"yt_F{n}.mp4", f"clip|{a.identity}|{round(seconds + 0.5, 2)}")
        return a

    # ---- helpers -----------------------------------------------------------
    def publish(self, doc: dict) -> int:
        """handler.publish_media as far as a re-cut needs it: local files to R2 links."""
        n = 0
        for s in doc["scenes"]:
            m = s.get("media") or {}
            u = str(m.get("url") or "")
            if u and not u.startswith("http") and os.path.isfile(u):
                k = f"projects/{PID}/media/{s['id']}-tok{len(self.r2.objects)}{os.path.splitext(u)[1]}"
                m["url"] = self.r2.upload(u, k)
                m["thumbnail"] = f"{BASE}/projects/{PID}/thumbs/{s['id']}.jpg"
                n += 1
        return n

    def run_recut(self, doc: dict, apply: bool = True, **inp) -> dict:
        return recut.run({"project_id": PID, "_job_id": JOB, "apply": apply, **inp}, doc, self.work,
                         publish=self.publish if apply else None)


# --------------------------------------------------------------------------- #
class Cutting(unittest.TestCase):
    """The plan: cut on words, within 2.5-7 s, tiling the scene's frames exactly."""

    def plan_one(self, scene: dict, fps: int, **kw):
        doc = doc_of([scene], fps, **kw)
        plans, left, counts = recut.plan_doc(doc)
        return plans, left, counts

    def test_a_long_shot_is_cut_on_word_starts_within_the_limits(self):
        for fps in (30, 60):
            s = clip_scene(0, 0, 20 * fps, fps)
            plans, left, _ = self.plan_one(s, fps)
            self.assertEqual(left, [])
            (p,) = plans
            self.assertGreaterEqual(len(p.pieces), 3)
            starts = {int(round(w["start"] * fps)) for w in s["words"]}
            for c in p.pieces:
                self.assertLessEqual(c.frames, 7 * fps)
                self.assertGreaterEqual(c.frames, int(math.ceil(2.5 * fps)))
            for c in p.pieces[1:]:
                self.assertIn(c.start, starts)                                  # every cut on a word's start

    def test_the_pieces_tile_the_scene_exactly_at_30_and_60_fps(self):
        for fps in (30, 60):
            for secs in (7.6, 8.0, 9.97, 12.34, 14.0, 17.5, 21.0, 26.66, 33.0):
                start = 1234 if fps == 60 else 617
                frames = int(round(secs * fps))
                s = clip_scene(3, start, frames, fps)
                plans, left, _ = self.plan_one(s, fps)
                self.assertEqual(len(plans), 1, (fps, secs, left))
                pieces = plans[0].pieces
                self.assertEqual(pieces[0].start, start)
                self.assertEqual(pieces[-1].end, start + frames)
                for a, b in zip(pieces, pieces[1:]):
                    self.assertEqual(a.end, b.start)                           # no gap, no overlap
                self.assertEqual(sum(p.frames for p in pieces), frames)
                self.assertTrue(all(2.5 * fps - 1e-6 <= p.frames <= 7 * fps for p in pieces), (fps, secs))

    def test_each_piece_gets_its_own_words_and_text(self):
        fps = 60
        s = clip_scene(0, 600, 18 * fps, fps)
        (p,), _, _ = self.plan_one(s, fps)
        self.assertEqual([w for c in p.pieces for w in c.words], s["words"])
        self.assertEqual(" ".join(c.text for c in p.pieces), s["text"])
        for c in p.pieces:
            self.assertEqual(c.text, " ".join(w["text"] for w in c.words))
            for w in c.words:                                                    # each word inside its piece
                self.assertGreaterEqual(int(round(w["start"] * fps)), c.start)
                self.assertLess(int(round(w["start"] * fps)), c.end)

    def test_a_line_whose_words_split_a_number_keeps_its_own_text(self):
        # The transcript writes "7" ".3" where the line says "7.3" (Yellowstone s0120, s0182; Lake Powell
        # s0091, 2026-10-04): the pieces share the line itself, cut where each one's first word begins in it -
        # never "7 .3" or "13 ,800" in the saved text.
        fps = 60
        text = ("Then the earth tore open. A magnitude 7.3 earthquake ripped through the region, one of the "
                "most powerful ever recorded in the Rocky Mountains, about 13,800 feet up.")
        spoken_as = text.replace("7.3", "7 .3").replace("13,800", "13 ,800")
        for secs in (14.0, 22.0):
            s = clip_scene(0, 0, int(secs * fps), fps, text=text)
            s["words"] = spoken(spoken_as, 0.05, secs - 0.05)
            (p,), _, _ = self.plan_one(s, fps)
            self.assertGreaterEqual(len(p.pieces), 2)
            self.assertEqual(" ".join(c.text for c in p.pieces), text)
            for c in p.pieces:
                first = c.words[0]["text"].strip(recut._EDGE).lower()
                self.assertTrue(c.text.lower().lstrip(recut._EDGE).startswith(first), (c.text, first))

    def test_a_line_the_owner_rewrote_keeps_his_words_not_the_transcript(self):
        # The editor changes a scene's text without its words: the pieces share his line, nothing of it lost.
        fps = 60
        s = clip_scene(0, 0, 16 * fps, fps)
        s["text"] = "My own rewrite of this line, shorter than what was said."
        (p,), _, _ = self.plan_one(s, fps)
        self.assertGreaterEqual(len(p.pieces), 2)
        self.assertEqual(" ".join(t for t in (c.text for c in p.pieces) if t), s["text"])
        # A scene with no line at all gets its words (a number the transcript split joined again).
        s = clip_scene(0, 0, 16 * fps, fps, text=LINE + " It fell 13,800 feet.")
        s["words"] = spoken((LINE + " It fell 13,800 feet.").replace("13,800", "13 ,800"), 0.05, 15.95)
        s["text"] = ""
        (p,), _, _ = self.plan_one(s, fps)
        joined = " ".join(c.text for c in p.pieces)
        self.assertIn("13,800", joined)
        self.assertEqual(joined, LINE + " It fell 13,800 feet.")

    def test_a_sentence_end_beats_a_comma_and_a_comma_beats_a_plain_word(self):
        fps = 30
        # 10 s, cut once: "... calm. Then ..." (a sentence end) sits as near the middle as a comma.
        text = "one two three four five six seven calm. Then eight nine ten eleven, twelve more words here now"
        s = clip_scene(0, 0, 10 * fps, fps, text=text)
        (p,), _, _ = self.plan_one(s, fps)
        self.assertEqual(p.cut_before, ["Then"])
        text = "one two three four five six seven eight nine, ten eleven twelve thirteen fourteen fifteen sixteen end"
        s = clip_scene(0, 0, 10 * fps, fps, text=text)
        (p,), _, _ = self.plan_one(s, fps)
        self.assertEqual(p.cut_before, ["ten"])
        # No punctuation: the widest breath near the middle.
        text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
        s = clip_scene(0, 0, 10 * fps, fps, text=text)
        s["words"] = spoken(text, 0.05, 9.95, pause_after={7: 0.8})
        (p,), _, _ = self.plan_one(s, fps)
        self.assertEqual(p.cut_before, ["nine"])

    def test_only_a_shot_over_the_cap_plus_half_a_second_is_cut(self):
        fps = 60
        for secs, cut in ((7.5, False), (7.6, True)):
            s = clip_scene(0, 0, int(round(secs * fps)), fps)
            plans, left, counts = self.plan_one(s, fps)
            self.assertEqual(bool(plans), cut, secs)
            self.assertEqual(counts["long"], int(cut))
        (p,), _, _ = self.plan_one(clip_scene(0, 0, int(7.6 * fps), fps), fps)
        self.assertEqual(len(p.pieces), 2)

    def test_a_33_second_shot_becomes_five_or_more_pieces_none_over_seven_seconds(self):
        fps = 60
        text = " ".join([LINE] * 3)
        (p,), _, _ = self.plan_one(clip_scene(0, 0, 33 * fps, fps, text=text), fps)
        self.assertGreaterEqual(len(p.pieces), 5)
        self.assertTrue(all(c.frames <= 7 * fps for c in p.pieces))

    def test_graphics_flashes_and_wordless_shots_keep_their_length_and_say_why(self):
        fps = 30
        scenes = lay_out([(anim_scene, 12.0, {}), (clip_scene, 12.0, {"text": "", "words": []}),
                          (clip_scene, 9.0, {"teaser": True}), (clip_scene, 6.0, {})], fps)
        plans, left, counts = recut.plan_doc(doc_of(scenes, fps))
        self.assertEqual(plans, [])
        self.assertEqual([r["why"] for r in left], ["a graphic or animation keeps its own length",
                                                    "it has no word timings to cut on", "a cold-open flash"])
        self.assertEqual(counts["longByKind"], {"other": 2, "video": 1})

    def test_a_graphic_on_the_picture_stays_over_the_scenes_own_clip(self):
        fps = 60
        s = clip_scene(0, 0, 16 * fps, fps)
        mark = {"type": "motion", "template": "LIB_VM_ARROW", "startFrame": 5 * fps, "durationInFrames": 3 * fps,
                "anchor": {"x": 0.4, "y": 0.5}}
        (p,), _, _ = self.plan_one(s, fps, overlays=[mark])
        self.assertGreaterEqual(p.pieces[1].start, 8 * fps)                      # the arrow ends inside piece 1
        late = dict(mark, startFrame=12 * fps, durationInFrames=3 * fps)         # it points until too late
        plans, left, _ = self.plan_one(s, fps, overlays=[late])
        self.assertEqual(plans, [])
        self.assertEqual(left[0]["why"], "a graphic points into its picture until too late to cut it")

    def test_the_new_pieces_are_named_after_the_scene_and_never_twice(self):
        fps = 30
        scenes = lay_out([(clip_scene, 20.0, {})], fps)
        scenes.append(dict(clip_scene(1, scenes[0]["durationInFrames"], 90, fps), id="s0000-b"))  # taken already
        doc = doc_of(scenes, fps)
        plans, _, _ = recut.plan_doc(doc)
        shots = {(0, c.k): recut.Found(how="search", cover=math.inf, k=c.k,
                                       media={"type": "image", "url": f"{BASE}/x{c.k}.jpg"})
                 for c in plans[0].pieces[1:]}
        new, marks, _gave, _segs = recut.assemble(doc, plans, shots)
        ids = [s["id"] for s in new]
        self.assertEqual(ids[:3], ["s0000", "s0000-c", "s0000-d"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_fingerprint_is_the_database_query_s_string(self):
        doc = doc_of(lay_out([(clip_scene, 8.0, {}), (empty_scene, 4.0, {})], 30), 30)
        want = "|".join(f"{(s.get('media') or {}).get('url') or ''}:{s.get('durationInFrames')}" for s in doc["scenes"])
        import hashlib
        self.assertEqual(recut.fingerprint(doc), hashlib.sha256(want.encode("utf-8")).hexdigest())


# --------------------------------------------------------------------------- #
class Ladder(Bench):
    """What each new piece gets: runner-ups, another moment of its own video, a fresh search - never a repeat."""

    def test_the_first_piece_keeps_the_scene_own_shot_and_the_cut_inside_a_line_is_plain(self):
        fps = 60
        scenes = lay_out([(clip_scene, 6.0, {}), (clip_scene, 11.0, {"transition": "pack:mlt5",
                                                                     "transitionGain": 0.42})], fps)
        doc = doc_of(scenes, fps)
        before = copy.deepcopy(doc)
        out = self.run_recut(doc)
        self.assertTrue(out["written"], out)
        new = self.written[-1][1]["scene_data"]["scenes"]
        self.assertEqual([s["id"] for s in new], ["s0000", "s0001", "s0001-b"])
        first, piece = new[1], new[2]
        self.assertEqual(first["media"], before["scenes"][1]["media"])          # the same file, the same in-point
        self.assertEqual((first["transition"], first["transitionGain"]), ("pack:mlt5", 0.42))
        self.assertEqual(first["visualTreatment"], before["scenes"][1]["visualTreatment"])
        self.assertEqual(piece["transition"], "none")                           # a plain cut: no transition sound
        self.assertNotIn("transitionGain", piece)
        self.assertNotIn("visualTreatment", piece)
        self.assertEqual(first["durationInFrames"] + piece["durationInFrames"], 11 * fps)
        self.assertEqual(doc, before)                                            # the input is never changed

    def test_a_shot_of_exactly_twice_the_cap_needs_three_pieces_unless_a_word_starts_at_the_cap(self):
        fps = 60
        (p,), _, _ = recut.plan_doc(doc_of([clip_scene(0, 0, 14 * fps, fps)], fps))
        self.assertEqual(len(p.pieces), 3)                                       # 7 s is the most, not about 7 s
        s = clip_scene(0, 0, 14 * fps, fps, text="one two three four. five six seven eight")
        s["words"] = [{"text": w, "start": t, "end": t + 1.0} for w, t in
                      zip(s["text"].split(), (0.1, 2.0, 4.0, 5.5, 7.0, 9.0, 10.5, 12.5))]
        (p,), _, _ = recut.plan_doc(doc_of([s], fps))
        self.assertEqual([c.frames for c in p.pieces], [7 * fps, 7 * fps])

    def test_a_published_runner_up_comes_first_and_leaves_the_scenes_choices(self):
        fps = 30
        scenes = lay_out([(clip_scene, 11.0, {})], fps)
        (p,), _, _ = recut.plan_doc(doc_of(copy.deepcopy(scenes), fps))
        self.assertEqual(len(p.pieces), 2)
        alt_media = {"type": "video", "url": url("alts", "s0000_alt1-cccccccccccc.mp4"),
                     "thumbnail": url("thumbs", "s0000_alt1.jpg"), "clipSeconds": 9.0}
        scenes[0]["semanticMetadata"]["alternatives"] = [
            {"assetId": "yt:RRRRRRRRRRR", "url": "https://www.youtube.com/watch?v=RRRRRRRRRRR&t=40", "score": 0.74,
             "title": "YouTube: runner-up", "source": "youtube", "moment": {"start": 40.0}, "media": alt_media},
            {"assetId": "yt:QQQQQQQQQQQ", "url": "https://www.youtube.com/watch?v=QQQQQQQQQQQ&t=5", "score": 0.7,
             "source": "youtube", "moment": {"start": 5.0}}]
        out = self.run_recut(doc_of(scenes, fps))
        new = self.written[-1][1]["scene_data"]["scenes"]
        self.assertEqual(new[1]["media"]["url"], alt_media["url"])              # nothing fetched, nothing searched
        self.assertEqual([c for c in self.calls if c[0] != "judge"], [])
        self.assertEqual(new[1]["semanticMetadata"]["assetId"], "yt:RRRRRRRRRRR")
        self.assertEqual(new[1]["semanticMetadata"]["recut"], {"from": "s0000", "how": "runner-up"})
        self.assertEqual([a["assetId"] for a in new[0]["semanticMetadata"]["alternatives"]], ["yt:QQQQQQQQQQQ"])
        self.assertEqual(out["totals"]["by"], {"runner-up": 1})

    def test_a_runner_up_with_no_saved_copy_is_fetched_from_its_approved_moment(self):
        fps = 30
        scenes = lay_out([(clip_scene, 11.0, {})], fps)
        scenes[0]["semanticMetadata"]["alternatives"] = [
            {"assetId": "yt:RRRRRRRRRRR", "url": "https://www.youtube.com/watch?v=RRRRRRRRRRR&t=40", "score": 0.74,
             "quality": 0.6, "title": "YouTube: runner-up", "source": "youtube", "moment": {"start": 40.5},
             "description": "the dry marina"}]
        out = self.run_recut(doc_of(scenes, fps))
        self.assertEqual([c[:3] for c in self.calls], [("clean", "RRRRRRRRRRR", 40.5)])   # never judged again
        piece = self.written[-1][1]["scene_data"]["scenes"][1]
        sem = piece["semanticMetadata"]
        self.assertEqual((sem["relevanceScore"], sem["contentDescription"]), (0.74, "the dry marina"))
        self.assertTrue(sem["sourceUrl"].startswith("https://www.youtube.com/watch?v=RRRRRRRRRRR"))
        self.assertEqual(out["totals"]["by"], {"runner-up": 1})
        self.assertEqual(self.written[-1][1]["scene_data"]["scenes"][0]["semanticMetadata"]["alternatives"], [])

    def test_then_another_moment_of_the_scenes_own_video_thirty_seconds_on(self):
        fps = 60
        scenes = lay_out([(clip_scene, 12.0, {"vid": "AAAAAAAAAAA", "at": 100.0, "clip": 12.4})], fps)
        (p,), _, _ = recut.plan_doc(doc_of(copy.deepcopy(scenes), fps))
        self.assertEqual(len(p.pieces), 2)
        out = self.run_recut(doc_of(scenes, fps))
        piece = self.written[-1][1]["scene_data"]["scenes"][1]
        secs = piece["durationInFrames"] / fps
        # As long as the line's longest piece and half a second: it could stand in for the other piece.
        need = round(max(c.frames for c in p.pieces) / fps + 0.5, 2)
        self.assertEqual(self.calls[0], ("clean", "AAAAAAAAAAA", round(100.0 + 12.4 + 30.0, 1), need))
        self.assertEqual(self.calls[1][0], "judge")                             # judged like a pool's moment
        self.assertEqual(self.searches, [])
        sem = piece["semanticMetadata"]
        self.assertEqual((sem["moment"]["start"], sem["moment"]["chain"]), (142.4, True))
        self.assertTrue(sem["sourceUrl"].startswith("https://www.youtube.com/watch?v=AAAAAAAAAAA&t=142"))
        self.assertEqual(sem["contentDescription"], "boats on a dry lake bed")
        self.assertEqual(out["totals"]["by"], {"moment": 1})
        self.assertGreaterEqual(piece["media"]["clipSeconds"], secs)            # never slowed to fill

    def test_a_moment_too_near_another_use_of_the_video_is_passed_over(self):
        fps = 30
        scenes = lay_out([(clip_scene, 12.0, {"vid": "AAAAAAAAAAA", "at": 100.0, "clip": 12.4}),
                          (clip_scene, 5.0, {}), (clip_scene, 5.0, {}),
                          (clip_scene, 5.0, {"vid": "AAAAAAAAAAA", "at": 150.0})], fps)
        self.run_recut(doc_of(scenes, fps))
        fetched = [c[2] for c in self.calls if c[0] == "clean"]
        self.assertNotIn(142.4, fetched)                                         # 7.6 s from the scene at 150 s
        self.assertTrue(all(abs(at - 150.0) >= 30 and abs(at - 100.0) >= 30 for at in fetched), fetched)

    def test_one_other_moment_per_scene_then_fresh_searches_with_the_pieces_own_words(self):
        fps = 60
        text = " ".join([LINE] * 2)
        scenes = lay_out([(clip_scene, 24.0, {"text": text}), (photo_scene, 5.0, {})], fps)
        doc = doc_of(scenes, fps)
        plans, _, _ = recut.plan_doc(doc)
        out = self.run_recut(doc)
        self.assertEqual(sum(1 for c in self.calls if c[0] == "clean"), 1)
        texts = [c.text for c in plans[0].pieces[2:]]
        self.assertEqual(sorted(s["context"] for s in self.searches), sorted(texts))
        for s in self.searches:
            self.assertEqual((s["query"], s["visual_type"]), ("Lake Powell boats", "footage"))
            self.assertEqual(s["intent"], "boats stranded on the dry lake bed")
            self.assertIn("Lake Powell boats on mud", s["fallbacks"])            # the scene intent's queries
            # Never a source the video shows: every scene's asset and source video.
            self.assertTrue({"yt:V0000000000", "web_image:https://img.example/1.jpg"} <= s["used"])
        self.assertEqual(out["totals"]["by"], {"moment": 1, "search": len(texts)})

    def test_a_still_gets_a_fresh_picture_search(self):
        fps = 30
        scenes = lay_out([(photo_scene, 11.0, {})], fps)
        out = self.run_recut(doc_of(scenes, fps))
        self.assertEqual([s["visual_type"] for s in self.searches], ["image"])
        piece = self.written[-1][1]["scene_data"]["scenes"][1]
        self.assertEqual(piece["media"]["type"], "image")
        self.assertNotEqual(piece["motion"], scenes[0]["motion"])                # consecutive stills never match
        self.assertEqual(out["totals"]["by"], {"picture": 1})
        self.assertIsInstance(out["stageSeconds"], dict)                        # where the sourcing time went
        self.assertIn("search", out["totals"]["rungSeconds"])
        self.assertIn("search", next(r for r in out["rows"] if r["result"] == "new")["spent"])

    def test_two_pieces_never_take_one_shot_and_nothing_repeats(self):
        fps = 30
        text = " ".join([LINE] * 2)
        scenes = lay_out([(clip_scene, 24.0, {"text": text, "semanticMetadata": {}})], fps)   # no moment
        same = {}

        def found(context, vt, n, seconds, used):
            if "dup" not in same:
                same["dup"] = self.fresh(vt, 7, seconds)
            a = copy.copy(same["dup"])
            return a if a.identity not in used else self.fresh(vt, n + 50, seconds, used)
        self.found_for = found
        self.run_recut(doc_of(scenes, fps))
        new = self.written[-1][1]["scene_data"]
        ids = [(s.get("semanticMetadata") or {}).get("assetId") for s in new["scenes"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(gapfill.find_repeats(new), [])

    def test_a_piece_nothing_was_found_for_goes_back_into_its_neighbour(self):
        fps = 60
        text = " ".join([LINE] * 2)
        scenes = lay_out([(clip_scene, 6.0, {}), (clip_scene, 24.0, {"text": text, "semanticMetadata": {}}),
                          (clip_scene, 6.0, {})], fps)
        doc = doc_of(scenes, fps)
        before = sound_and_graphics(doc)
        plans, _, _ = recut.plan_doc(doc)
        missing = plans[0].pieces[2].text
        self.found_for = lambda context, vt, n, seconds, used: (
            None if context == missing else self.fresh(vt, n, seconds, used))
        out = self.run_recut(doc)
        new = self.written[-1][1]["scene_data"]
        self.assertEqual(len(new["scenes"]), 3 + len(plans[0].pieces) - 2)
        for s in new["scenes"]:                                                   # never an empty piece...
            self.assertIn(s["media"]["type"], ("video", "image"))
            if s["media"]["type"] == "video":                                    # ...nor a slowed clip
                self.assertGreaterEqual(s["media"]["clipSeconds"] * fps + recut.TOL, s["durationInFrames"])
        self.assertEqual(sound_and_graphics(new), before)                        # ...nor a text card
        row = next(r for r in out["rows"] if r["result"] == "merged")
        self.assertEqual(row["why"], "nothing usable was found")
        self.assertEqual(out["totals"]["mergedBack"], 1)
        timeline.validate(copy.deepcopy(new), require_media=True)

    def test_how_a_scene_settles_when_a_piece_has_nothing(self):
        def seg(a, b, how, cover, k):
            return recut.Seg(a, b, [{"text": str(k), "start": a / 30, "end": a / 30 + 0.2}], [str(k)],
                             recut.Found(how=how, cover=cover, k=k) if how else None, [k])

        own = math.inf
        # A still holds as long as it is shown: the piece after it joins it.
        segs, gave = recut.settle([seg(0, 210, "original", own, 0), seg(210, 420, "picture", math.inf, 1),
                                   seg(420, 630, "", 0, 2)])
        self.assertEqual([(s.start, s.end, s.ks) for s in segs], [(0, 210, [0]), (210, 630, [1, 2])])
        self.assertEqual(gave, [])
        # A clip that covers its own time only moves on to the last piece; the scene's own shot takes its place.
        segs, gave = recut.settle([seg(0, 210, "original", own, 0), seg(210, 420, "search", 230, 1),
                                   seg(420, 630, "", 0, 2)])
        self.assertEqual([(s.start, s.end, s.ks, s.found.k) for s in segs], [(0, 420, [0, 1], 0), (420, 630, [2], 1)])
        self.assertEqual([w["text"] for w in segs[1].words], ["2"])               # the words go with the time
        self.assertEqual(gave, [])
        # Too short even for that: it gives its shot up and the scene stays longer on its own shot.
        segs, gave = recut.settle([seg(0, 210, "original", own, 0), seg(210, 420, "search", 215, 1),
                                   seg(420, 660, "", 0, 2)])
        self.assertEqual([(s.start, s.end) for s in segs], [(0, 660)])
        self.assertEqual(gave, [(1, "its clip is too short for the time left beside it")])
        # Fewer long shots first: the scene's own shot taking the empty piece would run over the limit,
        # the next shot starting earlier does not.
        segs, gave = recut.settle([seg(0, 300, "original", own, 0), seg(300, 400, "", 0, 1),
                                   seg(400, 600, "search", 420, 2), seg(600, 800, "search", 210, 3)], 350)
        self.assertEqual([(s.start, s.end, s.found.k) for s in segs], [(0, 300, 0), (300, 600, 2), (600, 800, 3)])
        self.assertEqual(gave, [])
        segs, _gave = recut.settle([seg(0, 300, "original", own, 0), seg(300, 400, "", 0, 1),
                                    seg(400, 600, "search", 420, 2), seg(600, 800, "search", 210, 3)])
        self.assertEqual([(s.start, s.end, s.found.k) for s in segs], [(0, 400, 0), (400, 600, 2), (600, 800, 3)])
        # The first piece of an empty scene with nothing: the piece after it starts earlier when it can.
        segs, gave = recut.settle([seg(0, 150, "", 0, 0), seg(150, 300, "picture", math.inf, 1)])
        self.assertEqual([(s.start, s.end, s.ks) for s in segs], [(0, 300, [0, 1])])
        # An empty scene nothing was found for stays one piece without a shot (the quality check's).
        segs, gave = recut.settle([seg(0, 150, "", 0, 0), seg(150, 300, "", 0, 1)])
        self.assertEqual([(s.start, s.end, s.found) for s in segs], [(0, 300, None)])

    def test_an_ai_made_picture_is_never_used(self):
        fps = 30
        scenes = lay_out([(photo_scene, 11.0, {})], fps)

        def found(context, vt, n, seconds, used):
            a = self.fresh(vt, n, seconds)
            a.source = "generated"
            return a
        self.found_for = found
        out = self.run_recut(doc_of(scenes, fps))
        self.assertEqual(out["written"], False)
        self.assertEqual(out["writeError"], "no new shot was found: nothing changed")
        self.assertEqual(self.written, [])

    def test_an_empty_scene_is_filled_and_left_as_it_was_when_nothing_is_found(self):
        fps = 30
        scenes = lay_out([(clip_scene, 5.0, {}), (empty_scene, 6.0, {}), (empty_scene, 12.0, {})], fps)
        doc = doc_of(scenes, fps)
        plans, _, _ = recut.plan_doc(doc)
        self.assertEqual([len(p.pieces) for p in plans], [1, 2])                # a long empty scene is cut too
        out = self.run_recut(doc)
        new = self.written[-1][1]["scene_data"]["scenes"]
        self.assertEqual([recut.kind_of(s) for s in new], ["video", "video", "video", "video"])
        self.assertEqual([s["id"] for s in new], ["s0000", "s0001", "s0002", "s0002-b"])   # filled in place
        self.assertEqual(new[2]["transition"], scenes[2]["transition"])
        self.assertEqual(out["totals"]["emptyFilled"], 2)
        self.assertEqual(out["totals"]["newShots"], 3)
        self.written.clear()
        self.found_for = lambda *a: None
        out = self.run_recut(doc_of(lay_out([(clip_scene, 5.0, {}), (empty_scene, 6.0, {})], fps), fps),
                             _job_id="job-recut-2")
        self.assertEqual((out["written"], self.written), (False, []))          # left for the render's quality check

    def test_the_time_box_stops_what_is_still_in_flight(self):
        fps = 30
        text = " ".join([LINE] * 2)
        scenes = lay_out([(clip_scene, 24.0, {"text": text, "semanticMetadata": {}})], fps)
        doc = doc_of(scenes, fps)
        plans, _, _ = recut.plan_doc(doc)
        slow = plans[0].pieces[1].text

        def found(context, vt, n, seconds, used):
            if context == slow:
                while not ytdlp.stopped():                                       # a download that hangs
                    time.sleep(0.02)
            return self.fresh(vt, n, seconds, used)
        self.found_for = found
        finder = recut.Finder(doc, plans, self.work, workers=4, deadline=time.time() + 1.0)
        t0 = time.time()
        got = finder.run()
        self.assertLess(time.time() - t0, 6.0)
        self.assertNotIn((0, 1), got)
        self.assertIn((0, 1), finder.late)
        self.assertEqual(len(got), len(plans[0].pieces) - 2)

    def test_a_piece_stuck_past_its_own_share_is_not_waited_for(self):
        # The Yellowstone re-cut's pass 2 (2026-10-04): 51 of 52 pieces in at 925 s, then 1,100 s more
        # waiting for one piece held inside a call that never looked at its stop.
        fps = 30
        text = " ".join([LINE] * 2)
        scenes = lay_out([(clip_scene, 24.0, {"text": text, "semanticMetadata": {}})], fps)
        doc = doc_of(scenes, fps)
        plans, _, _ = recut.plan_doc(doc)
        self.assertGreaterEqual(len(plans[0].needs()), 3)          # more pieces than threads: each has a share
        slow = plans[0].pieces[1].text
        release = threading.Event()

        def found(context, vt, n, seconds, used):
            if context == slow:
                release.wait(30)                                     # deaf to the stop, like a stalled download
            return self.fresh(vt, n, seconds, used)
        self.found_for = found
        for name, value in (("SCENE_SECONDS_MIN", 0.4), ("SCENE_SECONDS_MAX", 0.4)):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(recut, "STRAGGLER_GRACE", 0.4)
        p.start()
        self.addCleanup(p.stop)
        finder = recut.Finder(doc, plans, self.work, workers=2, deadline=time.time() + 60.0)
        t0 = time.time()
        try:
            got = finder.run()
            took = time.time() - t0
        finally:
            release.set()
            media.drain_pools(5.0)
        self.assertLess(took, 8.0)                                   # not the 60 s box
        self.assertNotIn((0, 1), got)
        self.assertIn((0, 1), finder.late)
        self.assertEqual(set(finder.stuck), {(0, 1)})
        self.assertEqual(finder.stuck[(0, 1)][1], "search")         # the rung it was held in
        self.assertTrue(any("not waited for" in n for n in finder.notes[(0, 1)]), finder.notes[(0, 1)])
        self.assertEqual(len(got), len(plans[0].needs()) - 1)       # every other piece kept its shot
        for key in got:
            self.assertIn("search", finder.took[key])                # seconds per rung, for the job result

    def test_pieces_without_a_share_of_their_own_are_waited_for_until_the_box(self):
        fps = 30
        text = " ".join([LINE] * 2)
        scenes = lay_out([(clip_scene, 24.0, {"text": text, "semanticMetadata": {}})], fps)
        doc = doc_of(scenes, fps)
        plans, _, _ = recut.plan_doc(doc)
        slow = plans[0].pieces[1].text
        release = threading.Event()

        def found(context, vt, n, seconds, used):
            if context == slow:
                release.wait(1.5)                                    # slow, but in by the end of the box
            return self.fresh(vt, n, seconds, used)
        self.found_for = found
        p = mock.patch.object(recut, "STRAGGLER_GRACE", 0.1)
        p.start()
        self.addCleanup(p.stop)
        finder = recut.Finder(doc, plans, self.work, workers=8, deadline=time.time() + 30.0)
        got = finder.run()
        self.assertEqual(finder.share, 0.0)                          # fewer pieces than threads
        self.assertIn((0, 1), got)
        self.assertEqual(finder.stuck, {})

    def test_the_sound_the_graphics_and_the_music_never_change(self):
        fps = 60
        mark = {"type": "motion", "template": "LIB_VM_ARROW", "startFrame": 60, "durationInFrames": 90,
                "anchor": {"x": 0.5, "y": 0.5}}
        scenes = lay_out([(clip_scene, 9.0, {}), (photo_scene, 15.0, {}), (clip_scene, 20.0, {})], fps)
        doc = doc_of(scenes, fps, overlays=[mark, {"type": "stat", "text": "40 FT", "value": 40, "startFrame": 700,
                                                   "durationInFrames": 200}])
        before = sound_and_graphics(doc)
        self.run_recut(doc)
        new = self.written[-1][1]["scene_data"]
        self.assertEqual(sound_and_graphics(new), before)
        self.assertEqual(new["durationInFrames"], doc["durationInFrames"])
        self.assertEqual(sum(s["durationInFrames"] for s in new["scenes"]), doc["durationInFrames"])
        # No new cut gets a transition sound: the planner's rule finds none at a plain cut.
        plain = [s for s in new["scenes"] if "-" in s["id"]]
        self.assertTrue(plain)
        self.assertEqual(timeline.plan_transition_sfx(plain, fps, []), [])


# --------------------------------------------------------------------------- #
class DryRunAndApply(Bench):
    def job(self, **inp) -> dict:
        return {"id": JOB, "input": {"action": "recut", "project_id": PID, **inp}}

    def test_a_dry_run_changes_nothing_anywhere_and_pays_for_nothing(self):
        fps = 60
        doc = doc_of(lay_out([(clip_scene, 11.0, {}), (photo_scene, 9.0, {}), (anim_scene, 10.0, {}),
                              (empty_scene, 4.0, {})], fps), fps)
        before = copy.deepcopy(doc)
        with mock.patch.object(handler.storage, "broker_events", side_effect=AssertionError("no event to the app")):
            out = handler.handler(self.job(timeline=doc))
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["action"], out["dry_run"]), ("recut", True))
        self.assertEqual(self.r2.objects, {})                                    # no R2 write
        storage.patch_project.assert_not_called()                                # not even "rendering"
        self.assertEqual(self.calls, [])                                         # no fetch, search or judgement
        ledger.start_loading.assert_not_called()
        self.assertEqual(doc, before)
        self.assertEqual((out["long"], out["cut"], out["newPieces"]), (3, 2, 3))
        rows = {r["scene"]: r for r in out["plan"]}
        row = rows["s0000"]
        self.assertEqual(len(row["pieces"]), 2)
        self.assertAlmostEqual(sum(row["pieces"]), 11.0, places=2)
        self.assertTrue(all(2.5 <= x <= 7.0 for x in row["pieces"]))
        self.assertEqual(row["cutAt"], [int(round(row["pieces"][0] * fps))])     # the cut point, in frames
        self.assertEqual(len(row["cutBefore"]), 1)
        self.assertEqual(rows["s0003"]["kind"], "empty")
        self.assertEqual(out["stayLong"], {"count": 1, "why": {"a graphic or animation keeps its own length": 1}})
        self.assertEqual(out["estimate"]["ladder"], {"runnerUps": 0, "moments": 1, "searches": 1, "pictures": 1})
        self.assertIn("costs", out)
        self.assertEqual(out["fingerprint"], recut.fingerprint(before))

    def test_an_apply_keeps_the_old_timeline_first_and_writes_the_project_once(self):
        fps = 30
        doc = doc_of(lay_out([(clip_scene, 14.0, {}), (photo_scene, 9.0, {})], fps), fps)
        before = copy.deepcopy(doc)
        out = handler.handler(self.job(timeline=doc, apply=True, seconds=600))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["written"], out)
        backup = f"projects/{PID}/backups/scene_data-{JOB}.json"
        self.assertEqual(out["backup"], backup)
        self.assertEqual(json.loads(self.r2.objects[(BUCKET, backup)].decode("utf-8")), before)
        self.assertEqual(out["recutKey"], f"projects/{PID}/backups/scene_data-{JOB}-recut.json")
        kinds = [k for k, _key in self.r2.order]
        self.assertEqual(kinds[0], "bytes")                                      # the backup before anything else
        self.assertEqual(kinds[-1], "project")                                   # the project last, once
        self.assertEqual(len(self.written), 1)
        fields = self.written[0][1]
        self.assertEqual({k: fields[k] for k in ("status", "current_step", "progress")},
                         {"status": "editing", "current_step": "Long shots re-cut", "progress": 100})
        new = fields["scene_data"]
        self.assertEqual(json.loads(self.r2.objects[(BUCKET, out["recutKey"])].decode("utf-8")), new)
        for s in new["scenes"]:                                                  # every link a saved one
            self.assertTrue(s["media"]["url"].startswith(BASE), s["media"]["url"])
        self.assertEqual(new["meta"]["sceneCount"], len(new["scenes"]))
        self.assertEqual(new["meta"]["recut"]["backup"], backup)
        self.assertEqual(out["fingerprintAfter"], recut.fingerprint(new))
        self.assertEqual(out["timeline"], new)
        ledger.save.assert_called_once_with(JOB, PID)                            # its new shots, like a build
        timeline.validate(copy.deepcopy(new), require_media=True)

    def test_the_new_shots_runner_ups_are_saved_as_choices_and_no_file_path_is_kept(self):
        fps = 30
        doc = doc_of(lay_out([(photo_scene, 9.0, {})], fps), fps)

        def found(context, vt, n, seconds, used):
            a = self.fresh(vt, n, seconds, used)
            a.alternatives = [{"assetId": "web_image:https://img.example/alt.jpg", "url": "https://img.example/alt.jpg",
                               "localPath": self._write("alt.jpg", "photo|alt|0"), "score": 0.6, "source": "web_image"}]
            return a
        self.found_for = found
        with mock.patch.object(config, "PICK_A_SHOT", True):
            out = handler.handler(self.job(timeline=doc, apply=True))
        self.assertTrue(out["written"], out)
        new = self.written[-1][1]["scene_data"]
        alt = new["scenes"][1]["semanticMetadata"]["alternatives"][0]
        self.assertTrue(alt["media"]["url"].startswith(f"{BASE}/projects/{PID}/alts/s0000-b_alt1"), alt)
        self.assertNotIn("localPath", json.dumps(new))
        self.assertFalse(any(str(s["media"]["url"]).startswith(self.work) for s in new["scenes"]))

    def test_through_the_broker_it_waits_for_the_project_to_be_handed_over(self):
        fps = 30
        doc = doc_of(lay_out([(clip_scene, 14.0, {})], fps), fps)
        answers = [False, False, True, True]

        def patch_project(project_id, fields, wait=False):
            self.written.append((project_id, dict(fields)))
            return answers.pop(0)
        storage.patch_project.side_effect = patch_project
        said = []

        class Say:
            extra = {}

            def __call__(self, step, pct=None, **kw):
                said.append(step)
        say = Say()
        with mock.patch.object(config, "STORAGE_BROKER_URL", "https://broker.example"), \
                mock.patch.object(config, "SUPABASE_SERVICE_KEY", ""), \
                mock.patch.object(storage, "CURRENT_JOB", [JOB]), mock.patch.object(recut, "POLL", 0.0):
            out = recut.run({"project_id": PID, "_job_id": JOB, "apply": True}, doc, self.work, say,
                            publish=self.publish)
        self.assertTrue(out["written"], out)
        self.assertEqual([sorted(f) for _p, f in self.written],
                         [["current_step"], ["current_step"], ["current_step"],
                          ["current_step", "progress", "scene_data", "status"]])  # asked, then one write
        self.assertIn("Waiting for the project to be handed to this job", said)
        self.assertEqual(say.extra["awaitHandover"]["job"], JOB)

    def test_not_handed_over_in_time_writes_nothing_and_says_where_the_timeline_is(self):
        fps = 30
        doc = doc_of(lay_out([(clip_scene, 14.0, {})], fps), fps)
        storage.patch_project.side_effect = lambda p, f, wait=False: self.written.append(dict(f)) and False
        with mock.patch.object(config, "STORAGE_BROKER_URL", "https://broker.example"), \
                mock.patch.object(config, "SUPABASE_SERVICE_KEY", ""), \
                mock.patch.object(storage, "CURRENT_JOB", [JOB]):
            out = recut.run({"project_id": PID, "_job_id": JOB, "apply": True, "write_wait": 0}, doc, self.work,
                            publish=self.publish)
        self.assertFalse(out["written"])
        self.assertIn("was not handed to this job", out["writeError"])
        self.assertTrue(all("scene_data" not in f for f in self.written))
        self.assertIn((BUCKET, out["recutKey"]), self.r2.objects)                # kept to apply later
        ledger.save.assert_not_called()

    def test_a_crash_writes_nothing_to_the_project(self):
        fps = 30
        doc = doc_of(lay_out([(clip_scene, 14.0, {})], fps), fps)
        with mock.patch.object(handler, "publish_media", side_effect=RuntimeError("R2 is down")):
            out = handler.handler(self.job(timeline=doc, apply=True))
        self.assertFalse(out["ok"])
        self.assertIn("R2 is down", out["error"])
        self.assertEqual(self.written, [])                                       # never "failed", never half-written
        with mock.patch.object(recut.Finder, "run", side_effect=RuntimeError("broke mid-search")):
            out = handler.handler(self.job(timeline=doc, apply=True))
        self.assertFalse(out["ok"])
        self.assertEqual(self.written, [])

    def test_a_timeline_that_changed_since_it_was_checked_is_refused(self):
        fps = 30
        doc = doc_of(lay_out([(clip_scene, 14.0, {})], fps), fps)
        out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint="0" * 64))
        self.assertFalse(out["ok"])
        self.assertIn("is not the one expected", out["error"])
        self.assertEqual((self.r2.objects, self.written), ({}, []))

    def test_a_shot_that_cannot_be_saved_goes_back_into_its_neighbour(self):
        fps = 30
        doc = doc_of(lay_out([(clip_scene, 14.0, {})], fps), fps)

        def publish(d):
            return 0                                                             # every upload refused
        out = recut.run({"project_id": PID, "_job_id": JOB, "apply": True}, doc, self.work, publish=publish)
        self.assertFalse(out["written"])
        self.assertEqual(self.written, [])
        self.assertEqual(out["writeError"], "no new shot could be saved: nothing changed")
        self.assertTrue(all(r["result"] == "merged" and r["why"] == "its file could not be saved"
                            for r in out["rows"]), out["rows"])


# --------------------------------------------------------------------------- #
def yellowstone_like(fps: int = 60, seed: int = 9) -> dict:
    """
    A timeline shaped like the owner's Yellowstone plan (9c467873, measured
    2026-10-04): 201 scenes at 60 fps, 100 over 7.5 s (41 clips, 55 stills, 4
    graphics) up to 33 s, 6 empty scenes; captions' words for every scene; a
    mark on a clip, looks, sounds at the cuts, music and ambience.
    """
    rng = random.Random(seed)
    kinds = ["clip"] * 41 + ["image"] * 55 + ["anim"] * 4
    longs = [(k, round(rng.uniform(7.6, 19.0), 2)) for k in kinds]
    longs[3] = ("clip", 33.0)
    longs[50] = ("image", 26.4)
    shorts = [("empty", round(rng.uniform(3.0, 7.0), 2)) for _ in range(6)]
    shorts += [("clip", round(rng.uniform(2.6, 7.4), 2)) for _ in range(60)]
    shorts += [("image", round(rng.uniform(2.6, 7.4), 2)) for _ in range(35)]
    order = longs + shorts
    rng.shuffle(order)
    order.insert(0, order.pop(next(k for k, (kind, _s) in enumerate(order) if kind == "clip")))
    vocab = ("geyser basin steam rises over the caldera while bison graze near the river and visitors watch "
             "from the boardwalk as the ground shifts beneath them every year").split()
    scenes, at, n = [], 0, 0
    for kind, secs in order:
        frames = int(round(secs * fps))
        words_n = max(3, int(secs * 2.6))
        toks = []
        for k in range(words_n):
            w = rng.choice(vocab)
            if k == words_n - 1 or rng.random() < 0.08:
                w += "."
            elif rng.random() < 0.1:
                w += ","
            toks.append(w.capitalize() if not toks or toks[-1].endswith(".") else w)
        text = " ".join(toks)
        maker = {"clip": clip_scene, "image": photo_scene, "anim": anim_scene, "empty": empty_scene}[kind]
        s = maker(n, at, frames, fps, text=text)
        if kind == "clip" and rng.random() < 0.2:
            s["transition"] = "crossfade"
        if kind in ("clip", "image") and rng.random() < 0.08:
            s["transition"], s["transitionGain"] = "pack:mlt5", 0.4
        scenes.append(s)
        at += frames
        n += 1
    first_clip = next(s for s in scenes if s["media"]["type"] == "video" and s["durationInFrames"] > 9 * fps)
    first_clip["semanticMetadata"]["alternatives"] = [
        {"assetId": "yt:ALTALTALTAL", "url": "https://www.youtube.com/watch?v=ALTALTALTAL&t=12", "score": 0.7,
         "source": "youtube", "moment": {"start": 12.0}, "title": "YouTube: runner-up"}]
    mark_on = next(s for s in scenes if s["media"]["type"] == "video" and s["durationInFrames"] > 12 * fps)
    overlays = [{"type": "motion", "template": "LIB_VM_ARROW", "startFrame": mark_on["startFrame"] + 2 * fps,
                 "durationInFrames": 3 * fps, "anchor": {"x": 0.3, "y": 0.6}}]
    for k in range(1, 12):
        overlays.append({"type": "stat", "template": "LIB_CO_MEASURE_LINE", "text": f"{k * 10} FT", "value": k * 10,
                         "startFrame": k * at // 13, "durationInFrames": 240})
    doc = doc_of(scenes, fps, overlays=overlays)
    doc["sfx"] = [{"name": "whoosh-soft", "startFrame": s["startFrame"] - 12, "volume": 0.25, "durationFrames": 50,
                   "kind": "transition"} for s in scenes[1:] if s["transition"] not in ("none", "crossfade")]
    doc["music"]["sections"] = [{"mood": "investigative", "startFrame": 0, "endFrame": at // 2},
                                {"mood": "suspense", "startFrame": at // 2, "endFrame": at}]
    return doc


class Replay(Bench):
    """A whole Yellowstone-shaped timeline, planned and applied with stubbed sourcing."""

    def test_the_plan_of_a_yellowstone_shaped_timeline(self):
        doc = yellowstone_like()
        fps = doc["fps"]
        plans, left, counts = recut.plan_doc(doc)
        self.assertEqual((counts["scenes"], counts["long"], counts["empty"]), (201, 100, 6))
        self.assertEqual(counts["longByKind"], {"video": 41, "image": 55, "other": 4})
        self.assertEqual(counts["longest"], 33.0)
        self.assertEqual(sum(1 for p in plans if p.kind == "empty"), 6)
        self.assertGreaterEqual(counts["cut"], 92)                               # all but a handful (the mark, the words)
        self.assertTrue(100 <= counts["newPieces"] <= 170, counts)
        for p in plans:
            self.assertEqual(sum(c.frames for c in p.pieces), p.end - p.start)
            if len(p.pieces) > 1:
                self.assertTrue(all(2.5 * fps - 1e-6 <= c.frames <= 7 * fps for c in p.pieces), p.id)
        self.assertEqual(len(left), 100 - counts["cut"])

    def test_an_apply_on_a_yellowstone_shaped_timeline(self):
        doc = yellowstone_like()
        fps = doc["fps"]
        before = copy.deepcopy(doc)
        words_before = [w for s in doc["scenes"] for w in s["words"]]

        def found(context, vt, n, seconds, used):
            if n % 6 == 5:
                return None                                                      # some searches find nothing
            return self.fresh(vt, n, seconds, used)
        self.found_for = found
        self.judge_keep = lambda path, job: hash(path) % 4 != 0                  # the judge turns some moments down
        out = self.run_recut(doc, seconds=900)
        self.assertTrue(out["written"], out.get("writeError"))
        new = self.written[-1][1]["scene_data"]
        t = out["totals"]
        self.assertEqual(t["scenesAfter"], 201 + t["newShots"] - t["emptyFilled"])   # an empty scene filled in place
        self.assertGreater(t["newShots"], 60)
        self.assertEqual(len(new["scenes"]), t["scenesAfter"])
        timeline.validate(copy.deepcopy(new), require_media=False)               # tiles the narration exactly
        self.assertEqual(sound_and_graphics(new), sound_and_graphics(before))
        self.assertEqual([w for s in new["scenes"] for w in s["words"]], words_before)  # every word, once, in order
        ids = [s["id"] for s in new["scenes"]]
        self.assertEqual(len(ids), len(set(ids)))
        marks = [None if "-" not in s["id"] and not (s.get("semanticMetadata") or {}).get("recut") else 1
                 for s in new["scenes"]]
        self.assertEqual(recut.repeats(new["scenes"], marks, fps), [])            # no new shot repeats anything
        long_after = [s for s in new["scenes"] if recut.kind_of(s) in ("video", "image")
                      and s["durationInFrames"] > 7.5 * fps]
        self.assertEqual(len(long_after), t["longAfter"])
        self.assertEqual(out["stayLong"]["count"], len(out["left"]))
        self.assertLess(t["longAfter"], 40)
        for s in new["scenes"]:
            if (s.get("semanticMetadata") or {}).get("recut"):
                self.assertEqual(s["transition"] if "-" in s["id"] else "none", "none")
                if s["media"]["type"] == "video":
                    self.assertGreaterEqual(s["media"]["clipSeconds"] * fps + recut.TOL, s["durationInFrames"])
        self.assertNotEqual(out["fingerprintAfter"], out["fingerprint"])
        self.assertEqual(doc, before)


if __name__ == "__main__":
    unittest.main()
