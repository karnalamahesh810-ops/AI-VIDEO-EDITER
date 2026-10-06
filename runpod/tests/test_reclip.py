"""
Re-clipping a made timeline (src/reclip.py, handler action "reclip"). The owner, 2026-10-06, on the Obama
video (70bc06d2: 29 clips in 192 scenes, the first minute almost without one, 11 empty spots as text): the
opening must be clips, every empty scene a clip, pictures replaced by good clips wherever one exists.

The plan: the opening's non-clips, then the empty or text-filled scenes, then the weakest pictures (never a
document's scan, a named person's portrait or a planner's graphic). The search: the clip-first search,
judged. An empty line nothing is found for gets the no-text last resort. A dry run writes nothing; an apply
needs expect_fingerprint, keeps the old timeline on R2 first and writes the project once.

Offline: the fakes of tests/test_recut.py (R2 is a dict, every search and judgement a stub).
"""
import copy
import json
import os
import unittest
from unittest import mock

import handler
from src import config, gapfill, media, reclip, recut, storage
from tests.test_recut import (BASE, BUCKET, JOB, PID, Bench, anim_scene, clip_scene, doc_of, empty_scene,
                              lay_out, photo_scene)


def filler_scene(n, start, frames, fps, text="It was the worst year on record."):
    s = empty_scene(n, start, frames, fps, text)
    s["reviewReason"] = "No usable clip found — the line is shown as text; use Find footage to add one"
    return s


def graphic_filler(n, start, frames, fps, text="Forty feet below full pool."):
    s = anim_scene(n, start, frames, fps, text)
    s["reviewReason"] = "No footage found — a motion graphic fills this beat (keep it or replace the clip)"
    return s


def person_photo(n, start, frames, fps, **kw):
    s = photo_scene(n, start, frames, fps, **kw)
    s["semanticMetadata"].update(subject="Malik Obama", subjectType="person")
    return s


def document_photo(n, start, frames, fps, **kw):
    s = photo_scene(n, start, frames, fps, **kw)
    s["semanticMetadata"].update(subject="IRS letter", subjectType="document")
    return s


def weak_photo(n, start, frames, fps, **kw):
    s = photo_scene(n, start, frames, fps, **kw)
    s["reviewReason"] = "Picture found in the last pass without an AI check - make sure it fits"
    s["semanticMetadata"]["judgedBy"] = "none"
    return s


def judged_photo(n, start, frames, fps, score=0.9, **kw):
    s = photo_scene(n, start, frames, fps, **kw)
    s["semanticMetadata"]["relevanceScore"] = score
    s["reviewReason"] = "Web image: licence unverified"
    return s


class Plan(unittest.TestCase):
    FPS = 30

    def doc(self):
        return doc_of(lay_out([
            (photo_scene, 4.0, {}),          # 0  0-4 s   the opening: a picture
            (filler_scene, 4.0, {}),         # 1  4-8 s   the opening: its line shown as text
            (clip_scene, 4.0, {}),           # 2  8-12 s  a clip: stays
            (judged_photo, 4.0, {}),         # 3  12-16 s a judged picture (0.9)
            (person_photo, 4.0, {}),         # 4  a named person's portrait: stays
            (document_photo, 4.0, {}),       # 5  a document's scan: stays
            (graphic_filler, 4.0, {}),       # 6  the last resort's graphic: re-clipped
            (anim_scene, 4.0, {}),           # 7  a planner's own graphic: stays
            (weak_photo, 4.0, {}),           # 8  a picture nothing judged
            (empty_scene, 4.0, {}),          # 9  empty
        ], self.FPS), self.FPS)

    def test_the_opening_then_the_empty_and_text_scenes_then_the_weakest_pictures(self):
        with mock.patch.object(config, "HOOK_SECONDS", 10.0):
            targets = reclip.plan_targets(self.doc())
        self.assertEqual([(t["index"], t["tier"]) for t in targets],
                         [(0, 0), (1, 0), (6, 1), (9, 1), (8, 2), (3, 2)])
        kinds = {t["index"]: t["kind"] for t in targets}
        self.assertEqual((kinds[1], kinds[6], kinds[9]), ("filler", "filler", "empty"))
        with mock.patch.object(config, "HOOK_SECONDS", 10.0):
            self.assertEqual([t["index"] for t in reclip.plan_targets(self.doc(), pictures=False)], [0, 1, 6, 9])
            self.assertEqual([t["index"] for t in reclip.plan_targets(self.doc(), limit=3)], [0, 1, 6])

    def test_a_portrait_in_the_opening_is_re_clipped_a_document_never(self):
        doc = doc_of(lay_out([(person_photo, 4.0, {}), (document_photo, 4.0, {})], self.FPS), self.FPS)
        with mock.patch.object(config, "HOOK_SECONDS", 60.0):
            self.assertEqual([t["index"] for t in reclip.plan_targets(doc)], [0])

    def test_counts_by_scene_by_time_and_in_the_opening(self):
        with mock.patch.object(config, "HOOK_SECONDS", 10.0):
            c = reclip.counts_of(self.doc())
        self.assertEqual((c["scenes"], c["clips"], c["pictures"], c["fillers"]), (10, 1, 5, 3))
        self.assertEqual((c["hookScenes"], c["hookClips"]), (3, 1))
        self.assertAlmostEqual(c["clipTimeShare"], 0.1, places=2)


class Action(Bench):
    FPS = 30

    def setUp(self):
        super().setUp()
        p = mock.patch.object(config, "HOOK_SECONDS", 10.0)
        p.start()
        self.addCleanup(p.stop)

    def _search(self, query, seconds, work_dir, **kw):
        with self.lock:
            n = len(self.searches)
            self.searches.append(dict(kw, query=query, seconds=seconds))
            self.calls.append(("search", (kw.get("context") or "")[:30]))
        used = kw.get("used")
        if self.found_for is not None:
            return self.found_for(kw.get("context") or "", kw.get("visual_type"), n, seconds, used)
        return self.fresh("footage", n, seconds, used)

    def doc(self):
        return doc_of(lay_out([(photo_scene, 4.0, {}), (filler_scene, 4.0, {}), (clip_scene, 4.0, {}),
                               (weak_photo, 4.0, {}), (person_photo, 4.0, {}), (empty_scene, 4.0, {}),
                               (photo_scene, 4.0, {})], self.FPS), self.FPS)

    def job(self, **inp):
        return {"id": JOB, "input": {"action": "reclip", "project_id": PID, **inp}}

    def test_a_dry_run_changes_nothing_and_pays_for_nothing(self):
        doc = self.doc()
        before = copy.deepcopy(doc)
        with mock.patch.object(handler.storage, "broker_events", side_effect=AssertionError("no event to the app")):
            out = handler.handler(self.job(timeline=doc))
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["action"], out["dry_run"]), ("reclip", True))
        self.assertEqual(self.r2.objects, {})
        storage.patch_project.assert_not_called()
        self.assertEqual(self.calls, [])
        self.assertEqual(doc, before)
        self.assertEqual(out["fingerprint"], recut.fingerprint(before))
        self.assertEqual([r["index"] for r in out["plan"]], [0, 1, 5, 3, 6])
        est = out["estimate"]
        self.assertEqual((est["targets"], est["fillers"]), (5, 2))
        self.assertGreater(est["usd"], 0)
        self.assertEqual(out["before"]["clips"], 1)

    def test_the_free_probe_counts_usable_candidates_per_scene(self):
        rows = [{"id": "NEWVIDEO001", "duration": 300.0, "title": "Lake Powell drone 4k", "channel": "", "aspect": 0},
                {"id": "NEWVIDEO002", "duration": 300.0, "title": "Lake Powell boats", "channel": "", "aspect": 0},
                {"id": "V0000000002", "duration": 300.0, "title": "already shown", "channel": "", "aspect": 0}]
        with mock.patch.object(media, "_yt_candidates", return_value=rows) as flat:
            out = reclip.run({"project_id": PID, "probe": True}, self.doc(), self.work)
        self.assertEqual(out["probe"], {"asked": 5, "answered": 5, "own": 5, "rung": 0, "none": 0,
                                        "withCandidates": 5})
        self.assertEqual(flat.call_count, 5)                      # a wider rung only where the own wording had none
        self.assertTrue(all(c.args[0].startswith("ytsearch12:") for c in flat.call_args_list))
        self.assertEqual(out["estimate"]["hitRate"], 0.75)
        # Titles that do not name the line's subject: the first wider rung is asked.
        other = [dict(r, title="Cooking show") for r in rows]
        with mock.patch.object(media, "_yt_candidates", return_value=other) as flat:
            out = reclip.run({"project_id": PID, "probe": True}, self.doc(), self.work)
        self.assertEqual((out["probe"]["own"], out["probe"]["none"]), (0, 5))
        self.assertEqual(flat.call_count, 10)

    def test_an_apply_needs_the_fingerprint(self):
        out = handler.handler(self.job(timeline=self.doc(), apply=True))
        self.assertFalse(out["ok"])
        self.assertIn("expect_fingerprint", out["error"])
        self.assertEqual(self.r2.objects, {})
        storage.patch_project.assert_not_called()

    def test_an_apply_puts_judged_clips_on_the_opening_the_empty_lines_and_the_pictures(self):
        doc = self.doc()
        before = copy.deepcopy(doc)
        out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["written"], out)
        self.assertEqual(out["found"], {"clips": 5, "moments": 0, "pictures": 0})
        backup = f"projects/{PID}/backups/scene_data-{JOB}.json"
        self.assertEqual(json.loads(self.r2.objects[(BUCKET, backup)].decode("utf-8")), before)
        self.assertEqual([k for k, _key in self.r2.order][0], "bytes")          # the backup first
        self.assertEqual(len(self.written), 1)
        fields = self.written[0][1]
        self.assertEqual((fields["status"], fields["current_step"]), ("editing", "Clips added"))
        new = fields["scene_data"]
        types = [s["media"]["type"] for s in new["scenes"]]
        self.assertEqual(types, ["video", "video", "video", "video", "image", "video", "video"])
        self.assertEqual(new["scenes"][4], before["scenes"][4])                   # the portrait stays
        for k in (0, 1, 3, 5, 6):
            s = new["scenes"][k]
            self.assertTrue(s["media"]["url"].startswith(BASE), s["media"]["url"])
            self.assertEqual(s["motion"], "none")
            self.assertEqual(s["semanticMetadata"]["reclip"]["how"], "clip")
            self.assertEqual((s["startFrame"], s["durationInFrames"], s["text"]),
                             (before["scenes"][k]["startFrame"], before["scenes"][k]["durationInFrames"],
                              before["scenes"][k]["text"]))                        # the line's words and timing
        clips = [s["semanticMetadata"]["assetId"] for s in new["scenes"] if s["media"]["type"] == "video"]
        self.assertEqual(len(clips), len(set(clips)))                             # never one clip twice
        for s in self.searches:
            self.assertTrue(s["clips_only"])
            self.assertIn("yt:V0000000002", s["used"])                            # never the video already shown
        self.assertEqual(out["after"]["clips"], 6)
        self.assertEqual(out["after"]["hookClips"], 3)
        self.assertEqual(new["meta"]["reclip"]["before"]["clips"], 1)
        self.assertEqual(out["fingerprintAfter"], recut.fingerprint(new))
        self.assertEqual({k: new[k] for k in new if k not in ("scenes", "meta")},
                         {k: before[k] for k in before if k not in ("scenes", "meta")})

    def test_an_empty_line_nothing_is_found_for_never_becomes_a_text_card(self):
        doc = self.doc()

        def found(context, vt, n, seconds, used):
            if context.startswith("It was the worst year"):
                return None                                   # the text-filled opening line: nothing found
            return self.fresh("footage", n, seconds, used)
        self.found_for = found
        with mock.patch.object(gapfill, "_from_moment", return_value=None), \
                mock.patch.object(gapfill, "_from_still", return_value=None):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["written"], out)
        new = self.written[-1][1]["scene_data"]
        self.assertFalse(any(ov.get("type") == "highlight" for ov in new.get("overlays") or []))
        self.assertFalse(any(reclip.kind_of(s) in ("empty", "filler") for s in new["scenes"]))
        self.assertEqual(out["lastResort"].get("card", 0), 0)
        self.assertEqual(new["durationInFrames"], doc["durationInFrames"])

    def test_two_lines_never_take_the_same_clip(self):
        doc = self.doc()
        same = media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=SAMESAMESAM&t=10",
                                duration=5.0, attribution="YouTube", relevance_score=0.8, moment={"start": 10.0},
                                license="unverified — you must hold the rights")

        def found(context, vt, n, seconds, used):
            if "yt:SAMESAMESAM" in (used or set()):
                return None
            a = copy.deepcopy(same)
            a.local_path = self._write(f"yt_SAME{n}.mp4", f"clip|yt:SAMESAMESAM@10|{seconds + 0.5}")
            return a
        self.found_for = found
        with mock.patch.object(config, "SOURCE_WORKERS", 1), \
                mock.patch.object(gapfill, "_from_moment", return_value=None), \
                mock.patch.object(gapfill, "_from_still", return_value=None):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertEqual(out["found"]["clips"], 1)


if __name__ == "__main__":
    unittest.main()
