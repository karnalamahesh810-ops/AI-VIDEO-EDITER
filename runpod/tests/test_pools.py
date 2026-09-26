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

        def fake_rate(cand, subject, context, seconds):
            calls.append(cand["id"])
            return rated[cand["id"]]

        def fake_fetch(job_, cand, m, work, require_cc, subject):
            return media.MediaAsset(kind="video", source="youtube",
                                    url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(m['start'])}",
                                    local_path=f"/w/{cand['id']}_{int(m['start'])}.mp4",
                                    moment_key=f"yt:{cand['id']}@{int(m['start'] // 10)}")
        with mock.patch.object(pools, "candidates", lambda s, cc, skip: cands.get(s, [])), \
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


if __name__ == "__main__":
    unittest.main()
