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


class Rig(Bench):
    """The re-cut bench with a re-clip job, its stub search and the saved clips the check reads."""
    FPS = 30

    def setUp(self):
        super().setUp()
        p = mock.patch.object(config, "HOOK_SECONDS", 10.0)
        p.start()
        self.addCleanup(p.stop)

        def fetch(url, path, **kw):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"clip|{url}|4.4")
            return path
        p = mock.patch.object(reclip.storage, "download", side_effect=fetch)
        p.start()
        self.addCleanup(p.stop)
        # YouTube's free search (the apply's probe): one title naming the line's subject, unless a test says
        # otherwise (self.flat_rows).
        self.flat_rows = [{"id": "PROBEROW001", "duration": 300.0, "title": "Lake Powell boats drone",
                           "channel": "", "aspect": 0}]
        p = mock.patch.object(media, "_yt_candidates",
                              side_effect=lambda *a, **k: copy.deepcopy(self.flat_rows))
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


class Action(Rig):
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
        # The clip and the four pictures nothing judged are counted for the check; the clip (scene 2) and the
        # portrait (scene 4) - not targets yet, their titles do not name their line - as likely new targets.
        self.assertEqual((est["targets"], est["fillers"], est["checks"], est["likelyTurnedDown"]), (7, 4, 5, 2))
        self.assertEqual(out["unchecked"], 5)
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
        self.assertEqual({k: out["found"][k] for k in ("clips", "moments", "pictures")},
                         {"clips": 5, "moments": 0, "pictures": 0})
        self.assertEqual(out["checked"], {"asked": 5, "answered": 5, "kept": 5, "turnedDown": 0})
        backup = f"projects/{PID}/backups/scene_data-{JOB}.json"
        self.assertEqual(json.loads(self.r2.objects[(BUCKET, backup)].decode("utf-8")), before)
        self.assertEqual([k for k, _key in self.r2.order][0], "bytes")          # the backup first
        self.assertEqual(len(self.written), 1)
        fields = self.written[0][1]
        self.assertEqual((fields["status"], fields["current_step"]), ("editing", "Clips added"))
        new = fields["scene_data"]
        types = [s["media"]["type"] for s in new["scenes"]]
        self.assertEqual(types, ["video", "video", "video", "video", "image", "video", "video"])
        # The portrait stays (the check kept it: its record now carries the judge's verdict).
        kept = copy.deepcopy(new["scenes"][4])
        self.assertEqual(kept["semanticMetadata"].pop("relevanceScore"), 0.81)
        for k in ("qualityScore", "contentDescription", "judgedBy"):
            kept["semanticMetadata"].pop(k, None)
        self.assertEqual(kept, before["scenes"][4])
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



def music_clip(n, start, frames, fps, **kw):
    s = clip_scene(n, start, frames, fps, **kw)
    s["media"]["attribution"] = "YouTube: Meek Mill - Early Mornings (Official Video)"
    s["semanticMetadata"]["relevanceScore"] = 0.8
    s["semanticMetadata"]["judgedBy"] = "frames"
    return s


def judged_clip(n, start, frames, fps, **kw):
    s = clip_scene(n, start, frames, fps, **kw)
    s["semanticMetadata"]["relevanceScore"] = 0.85
    s["semanticMetadata"]["judgedBy"] = "frames"
    return s


class Cleaner(Rig):
    """The second ask (2026-10-06): music videos and clips nobody judged replaced, and never a burnt budget."""

    def setUp(self):
        super().setUp()
        from src import topics
        topics.set_story({"summary": "Lake Powell is draining and the marinas are closing"}, "Lake Powell")
        self.addCleanup(topics.set_story, {}, "")

    def test_a_music_video_in_a_story_not_about_music_is_replaced(self):
        doc = doc_of(lay_out([(judged_clip, 4.0, {}), (music_clip, 4.0, {}), (judged_clip, 4.0, {})], self.FPS),
                     self.FPS)
        with mock.patch.object(config, "HOOK_SECONDS", 10.0):
            targets = reclip.plan_targets(doc)
        self.assertEqual([(t["index"], t["kind"], t["tier"]) for t in targets], [(1, "bad", 0)])
        self.assertIn("music", targets[0]["why"])
        out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["written"], out)
        new = self.written[-1][1]["scene_data"]
        self.assertNotIn("Official Video", new["scenes"][1]["media"].get("attribution") or "")
        self.assertEqual(new["scenes"][1]["semanticMetadata"]["reclip"]["how"], "clip")

    def test_a_music_video_nothing_replaces_still_goes(self):
        doc = doc_of(lay_out([(judged_clip, 4.0, {}), (music_clip, 4.0, {}), (judged_clip, 4.0, {})], self.FPS),
                     self.FPS)
        self.found_for = lambda context, vt, n, seconds, used: None
        with mock.patch.object(gapfill, "_from_moment", return_value=None), \
                mock.patch.object(gapfill, "_from_still", return_value=None):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["written"], out)
        new = self.written[-1][1]["scene_data"]
        self.assertFalse(any("Official Video" in str((s.get("media") or {}).get("attribution") or "")
                             for s in new["scenes"]))
        self.assertFalse(any(reclip.kind_of(s) == "empty" for s in new["scenes"]))   # never a scene left empty

    def test_a_story_about_the_musician_keeps_it(self):
        from src import topics
        topics.set_story({"summary": "Meek Mill: how a Philadelphia rapper became a voice for reform"}, "Meek Mill")
        doc = doc_of(lay_out([(judged_clip, 4.0, {}), (music_clip, 4.0, {})], self.FPS), self.FPS)
        self.assertEqual(reclip.plan_targets(doc, pictures=False), [])

    def test_a_clip_nobody_judged_is_checked_and_replaced_when_turned_down(self):
        doc = doc_of(lay_out([(judged_clip, 4.0, {}), (clip_scene, 4.0, {}), (judged_clip, 4.0, {}),
                              (clip_scene, 4.0, {})], self.FPS), self.FPS)

        def judge(path, job):
            # The check reads the saved copies (stub "clip|<url>|..."): scene 1's is turned down, scene 3's kept.
            with open(path, encoding="utf-8") as fh:
                return "s0001" not in fh.read()
        self.judge_keep = judge
        out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["written"], out)
        self.assertEqual(out["checked"], {"asked": 2, "answered": 2, "kept": 1, "turnedDown": 1})
        new = self.written[-1][1]["scene_data"]
        self.assertEqual(new["scenes"][1]["semanticMetadata"]["reclip"]["how"], "clip")
        self.assertEqual(new["scenes"][3]["semanticMetadata"]["relevanceScore"], 0.81)      # its verdict recorded
        self.assertEqual(new["scenes"][3]["semanticMetadata"]["judgedBy"], "frames")
        self.assertEqual(new["scenes"][3]["media"]["url"], doc["scenes"][3]["media"]["url"])

    def test_no_paid_step_past_the_budget(self):
        doc = self.doc()
        out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                       budget_usd=0.01, check=False))
        self.assertEqual(self.searches, [])                       # not one search was paid for
        self.assertTrue(out["budget"]["stopped"])
        self.assertGreater(out["unpaid"], 0)
        if out.get("written"):
            new = self.written[-1][1]["scene_data"]
            self.assertFalse(any(reclip.kind_of(s) == "empty" for s in new["scenes"]))

    def test_another_moment_of_a_clip_the_video_shows_is_taken(self):
        # The moment step claims that moment only: its video is on the timeline already.
        doc = doc_of(lay_out([(judged_clip, 4.0, {}), (empty_scene, 4.0, {}), (judged_clip, 4.0, {})], self.FPS),
                     self.FPS)
        moment = media.MediaAsset(kind="video", source="youtube",
                                  url="https://www.youtube.com/watch?v=V0000000000&t=160", duration=5.0,
                                  attribution="YouTube: clip 0", relevance_score=0.8, moment={"start": 160.0},
                                  moment_key="yt:V0000000000@16", license="unverified — you must hold the rights")
        moment.local_path = self._write("yt_moment.mp4", "clip|yt:V0000000000@160|4.5")
        with mock.patch.object(gapfill, "_from_moment", return_value=moment):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                           check=False))
        self.assertEqual(out["found"]["moments"], 1)
        self.assertEqual(self.searches, [])                       # before any fresh search

    def test_a_published_runner_up_costs_nothing(self):
        doc = doc_of(lay_out([(photo_scene, 4.0, {}), (judged_clip, 4.0, {})], self.FPS), self.FPS)
        doc["scenes"][0]["semanticMetadata"]["alternatives"] = [{
            "assetId": "yt:RUNNERUP001@1", "url": "https://www.youtube.com/watch?v=RUNNERUP001&t=12",
            "title": "Lake Powell houseboats", "score": 0.82, "quality": 0.7, "description": "boats on mud",
            "source": "youtube", "moment": {"start": 12.0}, "seconds": 6.0,
            "media": {"type": "video", "url": BASE + "/projects/x/choices/a.mp4", "source": "youtube"}}]
        with mock.patch.object(config, "HOOK_SECONDS", 10.0):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                           check=False))
        self.assertEqual(out["found"]["runnerUps"], 1)
        self.assertEqual(self.searches, [])
        new = self.written[-1][1]["scene_data"]
        self.assertEqual(new["scenes"][0]["media"]["url"], BASE + "/projects/x/choices/a.mp4")
        self.assertEqual(new["scenes"][0]["semanticMetadata"]["relevanceScore"], 0.82)

    def test_a_data_look_nothing_replaces_stays_and_cards_over_new_shots_go(self):
        doc = doc_of(lay_out([(filler_scene, 4.0, {}), (graphic_filler, 4.0, {}), (judged_clip, 4.0, {})], self.FPS),
                     self.FPS)
        doc["overlays"] = [{"type": "highlight", "text": "worst year", "startFrame": 0,
                            "durationInFrames": doc["scenes"][0]["durationInFrames"]}]

        def found(context, vt, n, seconds, used):
            return None if context.startswith("Forty feet") else self.fresh("footage", n, seconds, used)
        self.found_for = found
        with mock.patch.object(gapfill, "_from_moment", return_value=None), \
                mock.patch.object(gapfill, "_from_still", return_value=None):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                           check=False))
        self.assertTrue(out["written"], out)
        new = self.written[-1][1]["scene_data"]
        self.assertEqual(new["scenes"][1]["animation"], doc["scenes"][1]["animation"])   # the data look stays
        self.assertEqual(new["scenes"][0]["media"]["type"], "video")
        self.assertFalse(any(ov.get("type") == "highlight" for ov in new.get("overlays") or []))  # frame 0 too



class AfterTheObamaApply(Rig):
    """2026-10-07: the Obama apply found 8 clips for 110 lines, cleared 30 shots the check turned down (holds over
    23 lines, 8 text cards) and left no record of why. A turned-down shot nothing replaces stays; a line YouTube's
    free search names nothing for gets no paid search; every target says what was tried; a trial writes nothing."""

    def test_a_turned_down_shot_nothing_replaces_stays_marked_for_review(self):
        doc = doc_of(lay_out([(judged_clip, 4.0, {}), (clip_scene, 4.0, {}), (judged_clip, 4.0, {})], self.FPS),
                     self.FPS)
        self.judge_keep = False                                 # the check turns scene 1's clip down
        self.found_for = lambda context, vt, n, seconds, used: None
        with mock.patch.object(gapfill, "_from_moment", return_value=None), \
                mock.patch.object(gapfill, "_from_still", return_value=None):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc)))
        self.assertTrue(out["written"], out)
        self.assertEqual(out["keptTurnedDown"], 1)
        new = self.written[-1][1]["scene_data"]
        self.assertEqual(len(new["scenes"]), 3)                                    # no line held away
        self.assertEqual(new["scenes"][1]["media"]["url"], doc["scenes"][1]["media"]["url"])
        self.assertTrue(new["scenes"][1]["reviewRequired"])
        self.assertIn("turned this shot down", new["scenes"][1]["reviewReason"])
        self.assertEqual(new["scenes"][1]["semanticMetadata"]["relevanceScore"], 0.3)
        self.assertFalse(any(ov.get("type") == "highlight" for ov in new.get("overlays") or []))

    def test_a_line_no_youtube_title_names_gets_no_paid_search(self):
        doc = self.doc()
        self.flat_rows = [{"id": "OTHERVIDEO1", "duration": 300.0, "title": "Cooking show", "channel": "",
                           "aspect": 0}]
        with mock.patch.object(gapfill, "_from_moment", return_value=None) as moment, \
                mock.patch.object(gapfill, "_from_still", return_value=None):
            out = handler.handler(self.job(timeline=doc, apply=True, expect_fingerprint=recut.fingerprint(doc),
                                           check=False))
        self.assertEqual(self.searches, [])                     # not one paid search
        self.assertEqual(out["noCandidates"], 5)
        self.assertTrue(moment.called)                          # the cheap steps still ran
        self.assertEqual(out["why"]["skippedNoCandidates"], 5)
        rows = next(iter(out["trace"].values()))
        self.assertTrue(any(r.get("step") == "search" and "skipped" in r.get("why", "") for r in rows))

    def test_a_trial_writes_nothing_and_says_what_it_would_get(self):
        doc = self.doc()
        out = handler.handler(self.job(timeline=doc, trial=True, only=[0, 5], check=False))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["trial"])
        self.assertEqual(self.r2.objects, {})
        storage.patch_project.assert_not_called()
        self.assertEqual([r["index"] for r in out["plan"]], [0, 5])
        self.assertEqual(sorted(s["index"] for s in out["foundShots"]), [0, 5])
        self.assertTrue(all(s["how"] == "clip" for s in out["foundShots"]))
        self.assertEqual(out["budget"]["capUsd"], reclip.TRIAL_BUDGET_USD)
        self.assertNotIn("timeline", out)

    def test_the_why_summary_counts_the_traces(self):
        traces = {1: [{"step": "search", "candidates": 12, "usable": 3, "scouts": 2},
                      {"step": "scout", "kept": 2, "of": 2},
                      {"step": "download", "why": "download failed"},
                      {"step": "filter", "why": "low detail: about 496x279 real of 1280x720"},
                      {"step": "judge", "keep": False, "score": 0.3, "why": ""},
                      {"step": "judge", "keep": False, "score": 0.6, "why": ""},
                      {"step": "judge", "keep": False, "score": 0.8, "why": "talking head"},
                      {"step": "judge", "keep": True, "score": 0.8}],
                  2: [{"step": "search", "why": "skipped: no YouTube title names this line (the free probe)"}]}
        w = reclip.why_summary(traces)
        self.assertEqual((w["searches"], w["scouted"], w["downloadsFailed"], w["judged"], w["passed"]),
                         (1, 2, 1, 4, 1))
        self.assertEqual(w["filtered"], {"low detail": 1})
        self.assertEqual(w["nearMisses"], 1)
        self.assertEqual(w["turnedDown"]["talking head"], 1)
        self.assertEqual(w["skippedNoCandidates"], 1)

    def test_the_estimate_gives_both_ends(self):
        targets = reclip.plan_targets(self.doc())
        est = reclip.estimate(targets, 16, {"answered": 5, "own": 5, "rung": 0, "none": 0, "withCandidates": 5})
        self.assertLess(est["expectedClipsLow"], est["expectedClips"])
        self.assertEqual(est["expectedClipsLow"], round(len(targets) * reclip.PASS_LOW))


    def test_a_reclips_searches_are_narrower_and_the_config_comes_back(self):
        seen = []

        def found(context, vt, n, seconds, used):
            seen.append((config.CLIP_WORDINGS, config.CLIP_OTHER_WORDINGS, config.SCENE_SECONDS_MAX))
            return self.fresh("footage", n, seconds, used)
        self.found_for = found
        before = (config.CLIP_WORDINGS, config.CLIP_OTHER_WORDINGS, config.SCENE_SECONDS_MAX)
        doc = self.doc()
        handler.handler(self.job(timeline=doc, trial=True, only=[0], check=False))
        self.assertEqual(seen, [(2, 0, 180.0)])
        self.assertEqual((config.CLIP_WORDINGS, config.CLIP_OTHER_WORDINGS, config.SCENE_SECONDS_MAX), before)
        seen.clear()
        handler.handler(self.job(timeline=doc, trial=True, only=[0], check=False, config={"CLIP_WORDINGS": 3}))
        self.assertEqual(seen[0][0], 3)                            # the job's own config wins


    def test_a_trials_small_cap_searches_every_line(self):
        doc = self.doc()
        out = handler.handler(self.job(timeline=doc, trial=True, only=[0, 1, 3, 5], check=False, budget_usd=0.10))
        self.assertEqual(len(self.searches), 4)              # a trial keeps nothing back for a save
        self.assertFalse(out["budget"]["stopped"])


if __name__ == "__main__":
    unittest.main()
