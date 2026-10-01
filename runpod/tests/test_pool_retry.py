"""Subject pools cover more lines (src/pools.py; the Lake Powell job, 2026-10-01: 29 of 86).

A pooled line whose moment failed (no download, burned-in text, a still, AI)
used to fall to the slow per-scene search while its subject's other approved
moments sat unused; and a subject's videos were rated strictly one by one."""
import threading
import time
import unittest
from unittest import mock

from src import config, media, pools


def job(i, subject, start):
    return {"index": i, "query": subject, "seconds": 7.0, "visual_type": "footage", "subject": subject,
            "subject_type": "place", "context": f"line {i}", "intent": subject, "start": start}


def asset(cand, m):
    return media.MediaAsset(kind="video", source="youtube",
                            url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(m['start'])}",
                            local_path=f"/w/{cand['id']}_{int(m['start'])}.mp4",
                            moment_key=f"yt:{cand['id']}@{int(m['start'] // 10)}")


CANDS = {"Lake Mead": [{"id": "AAAAAAAAAAA", "title": "Lake Mead drone 4k"},
                       {"id": "BBBBBBBBBBB", "title": "Lake Mead documentary"}]}
RATED = {"AAAAAAAAAAA": [{"start": 10.0, "score": 0.9, "description": "shore"},
                         {"start": 300.0, "score": 0.9, "description": "ring"}],
         "BBBBBBBBBBB": [{"start": 100.0, "score": 0.9, "description": "ramp"},
                         {"start": 400.0, "score": 0.9, "description": "dam"}]}


class RetryFailedMoments(unittest.TestCase):
    def _run(self, jobs, fail):
        fetched = []

        def fetch(job_, cand, m, work, require_cc, subject, library=None):
            fetched.append((job_["index"], cand["id"], m["start"]))
            return None if (cand["id"], m["start"]) in fail else asset(cand, m)
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: CANDS.get(s, [])), \
                mock.patch.object(pools, "rate_video", lambda c, s, ctx, sec, **kw: RATED[c["id"]]), \
                mock.patch.object(pools, "_fetch", fetch), \
                mock.patch.object(config, "POOL_MIN_SCENES", 2), \
                mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2), \
                mock.patch.object(config, "SAME_VIDEO_GAP_SECONDS", 120.0):
            got = pools.source_by_subject(jobs, "/w")
        return got, fetched, dict(media.LAST_STATS.get("pools") or {})

    def tearDown(self):
        with pools._RESERVE_LOCK:
            pools._RESERVE.clear()

    def test_a_failed_moment_is_replaced_by_the_subjects_next_approved_one(self):
        jobs = [job(0, "Lake Mead", 0.0), job(1, "Lake Mead", 200.0), job(2, "Lake Mead", 400.0)]
        got, fetched, stats = self._run(jobs, fail={("AAAAAAAAAAA", 10.0)})
        self.assertEqual(sorted(got), [0, 1, 2])                        # line 0 is not left to per-scene search
        self.assertIn("BBBBBBBBBBB&t=400", got[0].url)                  # the spare, under the variety rules
        self.assertEqual(len({a.identity for a in got.values()}), 3)    # never the same moment twice
        self.assertEqual((stats["retried"], stats["retry_filled"]), (1, 1))
        with pools._RESERVE_LOCK:
            self.assertEqual(pools._RESERVE, [])                         # the spare was used, not kept

    def test_a_spare_the_variety_rules_refuse_is_not_used(self):
        # Line 0 plays at 300 s, 100 s from video B's moment on line 2 (400 s): never within 120 s.
        jobs = [job(0, "Lake Mead", 300.0), job(1, "Lake Mead", 600.0), job(2, "Lake Mead", 400.0)]
        got, fetched, stats = self._run(jobs, fail={("AAAAAAAAAAA", 10.0)})
        self.assertNotIn(0, got)
        self.assertEqual(stats.get("retry_filled", 0), 0)
        self.assertEqual([f for f in fetched if f[0] == 0], [(0, "AAAAAAAAAAA", 10.0)])

    def test_off_means_off(self):
        jobs = [job(0, "Lake Mead", 0.0), job(1, "Lake Mead", 200.0), job(2, "Lake Mead", 400.0)]
        with mock.patch.object(config, "POOL_RETRY_MOMENTS", 0):
            got, _f, _s = self._run(jobs, fail={("AAAAAAAAAAA", 10.0)})
        self.assertNotIn(0, got)


class RatedAFewAtOnce(unittest.TestCase):
    def _plan(self, parallel):
        cands = [{"id": f"VIDEO{k:06d}", "title": f"Lake Mead {k}"} for k in range(5)]
        busy, peak, lock = [0], [0], threading.Lock()

        def rate(c, s, ctx, sec, **kw):
            with lock:
                busy[0] += 1
                peak[0] = max(peak[0], busy[0])
            time.sleep(0.15)
            with lock:
                busy[0] -= 1
            k = int(c["id"][-1])
            return [{"start": 20.0 + 200 * k, "score": 0.9, "description": f"m{k}"}]
        jobs = [job(i, "Lake Mead", 300.0 * i) for i in range(5)]
        claimed = set()

        def claim(key):
            if key in claimed:
                return False
            claimed.add(key)
            return True
        with mock.patch.object(pools, "candidates", lambda s, cc, skip, **kw: cands), \
                mock.patch.object(pools, "rate_video", rate), \
                mock.patch.object(config, "POOL_RATE_PARALLEL", parallel), \
                mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2), \
                mock.patch.object(config, "SAME_VIDEO_GAP_SECONDS", 120.0):
            t0 = time.time()
            plan, spare = pools.plan_subject("Lake Mead", jobs, False, set(), claim)
            took = time.time() - t0
        return [(j["index"], c["id"], m["start"]) for j, c, m in plan], peak[0], took

    def test_the_same_plan_in_less_time(self):
        one_by_one, peak1, t1 = self._plan(1)
        batched, peak3, t3 = self._plan(3)
        self.assertEqual(batched, one_by_one)                            # rank order kept
        self.assertEqual((peak1, peak3), (1, 3))
        self.assertLess(t3, t1)


if __name__ == "__main__":
    unittest.main()
