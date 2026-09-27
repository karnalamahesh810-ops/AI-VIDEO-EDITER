import unittest
from unittest import mock

import handler
from src import config, pools
from src.media import MediaAsset


def asset(ident, i=0):
    a = MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={ident}",
                   local_path=f"/tmp/{ident}_{i}.mp4")
    a.moment_key = f"yt:{ident}@{i}"
    return a


class SourceWithPools(unittest.TestCase):
    def _jobs(self, n=4):
        return [{"index": i, "query": f"q{i}", "seconds": 5.0, "subject": "Lake Mead"} for i in range(n)]

    def test_pools_then_scenes_then_spare_moments_aligned_by_index(self):
        jobs = self._jobs()
        pooled = {1: asset("POOL0000001", 1)}
        calls = {}

        def rest_fn(rest, taken):
            calls["rest"] = [j["index"] for j in rest]
            calls["taken"] = set(taken)
            return [asset("SCENE000000", 0), None, asset("SCENE000000", 0)]   # index 3 repeats index 0

        with mock.patch.object(config, "SUBJECT_POOLS", True), \
                mock.patch.object(pools, "source_by_subject", return_value=pooled) as sbs, \
                mock.patch.object(pools, "fill_from_reserve", return_value={2: asset("SPARE000002", 2), 3: asset("SPARE000003", 3)}) as ffr:
            got, pl = handler._source_with_pools(jobs, "/w", require_cc=False, exclude={"yt:OLD00000000"}, source_rest=rest_fn)
        self.assertEqual(calls["rest"], [0, 2, 3])
        self.assertIn("yt:OLD00000000", calls["taken"])                     # the parent's exclusions travel
        self.assertIn(pooled[1].identity, calls["taken"])                   # so do the pool's clips
        self.assertIn("yt:POOL0000001", calls["taken"])                     # ... and the pool videos themselves
        self.assertEqual([a.identity if a else None for a in got],
                         [asset("SCENE000000", 0).identity, pooled[1].identity, "yt:SPARE000002@2", "yt:SPARE000003@3"])
        self.assertEqual(ffr.call_args.args[1], [2, 3])                     # the empty one and the repeat
        self.assertEqual(pl, pooled)
        self.assertEqual(sbs.call_args.kwargs["require_cc"], False)

    def test_without_pools_it_is_plain_per_scene_sourcing(self):
        jobs = self._jobs(2)
        with mock.patch.object(config, "SUBJECT_POOLS", False), \
                mock.patch.object(pools, "source_by_subject", side_effect=AssertionError("no pools")):
            got, pl = handler._source_with_pools(jobs, "/w", require_cc=False, exclude=set(),
                                                 source_rest=lambda rest, taken: [asset("A0000000000"), asset("B0000000000")])
        self.assertEqual([a.identity for a in got], ["yt:A0000000000@0", "yt:B0000000000@0"])
        self.assertEqual(pl, {})

    def test_flag_defaults_on(self):
        self.assertTrue(config.POOLS_IN_PARTS)


if __name__ == "__main__":
    unittest.main()
