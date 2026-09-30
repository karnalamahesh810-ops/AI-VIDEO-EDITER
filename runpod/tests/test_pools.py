import unittest
from unittest import mock

from src import config, media, pools


def job(i, subject, seconds=7.0, **kw):
    return {"index": i, "query": subject, "seconds": seconds, "visual_type": "footage",
            "subject": subject, "subject_type": kw.get("subject_type", "place"),
            "context": f"line {i} about {subject}", "intent": subject}


class Grouping(unittest.TestCase):
    def test_same_subject_spelled_differently_is_one_pool(self):
        g = pools.groups([job(0, "Page, Arizona"), job(1, "Page Arizona"),
                          job(2, "The Colorado River"), job(3, "Colorado River")])
        self.assertEqual(sorted(g), ["colorado river", "page arizona"])
        self.assertEqual([j["index"] for j in g["page arizona"]], [0, 1])

    def test_people_and_stills_stay_with_per_scene_sourcing(self):
        g = pools.groups([job(0, "Barack Obama Sr", subject_type="person"),
                          dict(job(1, "Lake Mead"), visual_type="image"), job(2, "Lake Mead")])
        self.assertEqual({k: [j["index"] for j in v] for k, v in g.items()}, {"lake mead": [2]})

    def test_moments_are_spaced_and_keep_the_better_of_two_close_ones(self):
        got = pools.spaced([{"start": 10, "score": 0.8}, {"start": 12, "score": 0.95},
                            {"start": 30, "score": 0.75}], gap=8)
        self.assertEqual([(m["start"], m["score"]) for m in got], [(12, 0.95), (30, 0.75)])


class SourceBySubject(unittest.TestCase):
    def test_one_vision_call_per_video_feeds_many_lines_in_story_order(self):
        jobs = [job(i, "Lake Mead") for i in range(5)] + [job(5, "Hoover Dam")]
        cands = {"Lake Mead": [{"id": "AAAAAAAAAAA", "title": "Lake Mead drone 4k"},
                               {"id": "BBBBBBBBBBB", "title": "Lake Mead documentary"}]}
        rated = {"AAAAAAAAAAA": [{"start": 20.0, "score": 0.9, "description": "dry shore"},
                                 {"start": 60.0, "score": 0.8, "description": "dam"},
                                 {"start": 64.0, "score": 0.7, "description": "too close"}],
                 "BBBBBBBBBBB": [{"start": 100.0, "score": 0.85, "description": "ramp"},
                                 {"start": 140.0, "score": 0.9, "description": "ring"}]}
        calls = []

        def fake_rate(cand, subject, context, seconds, **kw):
            calls.append(cand["id"])
            return rated[cand["id"]]

        def fake_fetch(job_, cand, m, work, require_cc, subject, library=None):
            return media.MediaAsset(kind="video", source="youtube",
                                    url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(m['start'])}",
                                    local_path=f"/w/{cand['id']}_{int(m['start'])}.mp4",
                                    moment_key=f"yt:{cand['id']}@{int(m['start'] // 10)}")
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: cands.get(s, [])), \
                mock.patch.object(pools, "rate_video", fake_rate), \
                mock.patch.object(pools, "_fetch", fake_fetch), \
                mock.patch.object(config, "POOL_MIN_SCENES", 2):
            got = pools.source_by_subject(jobs, "/w")
        self.assertEqual(calls, ["AAAAAAAAAAA", "BBBBBBBBBBB"])      # one judgement per video
        self.assertEqual(sorted(got), [0, 1, 2, 3])                     # Hoover Dam: a one-off
        self.assertEqual([got[i].url.split("=", 1)[1] for i in range(4)],
                         ["AAAAAAAAAAA&t=20", "AAAAAAAAAAA&t=60",
                          "BBBBBBBBBBB&t=100", "BBBBBBBBBBB&t=140"])  # story order, spaced
        self.assertEqual(len({a.identity for a in got.values()}), 4)    # never the same moment
        self.assertEqual(pools.video_ids(got), {"yt:AAAAAAAAAAA", "yt:BBBBBBBBBBB"})


class Reserve(unittest.TestCase):
    # Updated for the owner's review (2026-09-30): this test used to have one
    # Lake Mead video feed three lines and a Hoover Dam video two plus a spare,
    # i.e. it encoded the old "many moments of one video" reuse. A video now
    # supplies at most MAX_MOMENTS_PER_VIDEO lines, SAME_VIDEO_GAP_SECONDS apart,
    # so the lines carry their start and the spares come from a second video.
    def test_spare_moments_fill_empty_or_repeated_lines_same_subject_first(self):
        jobs = [dict(job(0, "Lake Mead"), start=0.0), dict(job(1, "Hoover Dam"), start=30.0),
                dict(job(2, "Lake Mead"), start=60.0), dict(job(3, "Hoover Dam"), start=500.0)]
        cands = {"Lake Mead": [{"id": "AAAAAAAAAAA", "title": "Lake Mead 4k"},
                               {"id": "BBBBBBBBBBB", "title": "Lake Mead drone"}],
                 "Hoover Dam": [{"id": "HHHHHHHHHHH", "title": "Hoover Dam drone"}]}
        rated = {"AAAAAAAAAAA": [{"start": 10.0 * k, "score": 0.9, "description": f"mead {k}"} for k in (1, 2)],
                 "BBBBBBBBBBB": [{"start": 100.0 + 10 * k, "score": 0.9, "description": f"mead b{k}"} for k in (0, 1)],
                 "HHHHHHHHHHH": [{"start": 10.0 * k, "score": 0.9, "description": f"dam {k}"} for k in range(1, 4)]}

        def fake_fetch(job_, cand, m, work, require_cc, subject, library=None):
            return media.MediaAsset(kind="video", source="youtube",
                                    url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(m['start'])}",
                                    local_path="/w/x.mp4", moment_key=f"yt:{cand['id']}@{int(m['start'] // 10)}")
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: cands.get(s, [])), \
                mock.patch.object(pools, "rate_video", lambda c, s, ctx, sec, **kw: rated[c["id"]]), \
                mock.patch.object(pools, "_fetch", fake_fetch), \
                mock.patch.object(config, "POOL_MIN_SCENES", 1), \
                mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2), \
                mock.patch.object(config, "SAME_VIDEO_GAP_SECONDS", 120.0):
            got = pools.source_by_subject(jobs, "/w")
            self.assertEqual(sorted(got), [0, 1, 2, 3])
            self.assertIn("AAAAAAAAAAA", got[0].url)
            self.assertIn("BBBBBBBBBBB", got[2].url)        # 60 s after line 0: not video A again
            # Suppose per-scene sourcing later made line 2 a repeat and left line 3 empty:
            current = {0: got[0], 1: got[1]}
            extra = pools.fill_from_reserve(jobs, [2, 3], "/w", assets=current)
        self.assertEqual(sorted(extra), [2, 3])
        self.assertIn("BBBBBBBBBBB", extra[2].url)          # Lake Mead line -> a spare Lake Mead moment,
        self.assertNotIn("AAAAAAAAAAA", extra[2].url)       # never video A within 120 s of line 0
        self.assertIn("AAAAAAAAAAA", extra[3].url)          # no Hoover Dam spare: any subject's, 500 s on
        all_ids = {a.identity for a in got.values()} | {a.identity for a in extra.values()}
        self.assertEqual(len(all_ids), 6)                   # never the same moment twice

    def test_a_line_that_names_its_own_place_takes_only_that_places_spares(self):
        jobs = [dict(job(0, "Houston"), start=0.0, place="Houston"),
                dict(job(1, "Dallas"), start=300.0, place="Dallas")]
        with pools._RESERVE_LOCK:
            pools._RESERVE[:] = [("houston", {"id": "HOUSTON0001", "title": "Houston flooding"},
                                  {"start": 40.0, "score": 0.9, "description": ""})]
        try:
            with mock.patch.object(pools, "_fetch", side_effect=AssertionError("no Houston shot for Dallas")):
                self.assertEqual(pools.fill_from_reserve(jobs, [1], "/w", assets={}), {})
        finally:
            with pools._RESERVE_LOCK:
                pools._RESERVE.clear()


if __name__ == "__main__":
    unittest.main()
