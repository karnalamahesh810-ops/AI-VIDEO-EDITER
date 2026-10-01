"""Every scene gets its turn (src/media.py source_many, src/ytdlp.py).

The owner's Lake Powell pod (2026-10-01): 130 scenes on 28 threads, pass 1
boxed at 1800 s. 49 scenes finished; 81 were left (53 never started) because
a scene that found nothing tried every fallback search and source (~14 min a
scene on average), and the scenes the pass gave up on kept their threads and
~370 queued requests going behind 16 network slots for the rest of the job.
"""
import os
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from src import config, media, providers, ytdlp
from src.media import MediaAsset


def _closed():
    box = ytdlp.Box()
    box.end()
    return box


class Boxes(unittest.TestCase):
    def tearDown(self):
        ytdlp.set_deadline(0.0)

    def test_a_box_shortens_and_ends(self):
        box = ytdlp.Box()
        self.assertFalse(box.closed())
        box.shorten(time.time() + 60)
        self.assertFalse(box.closed())
        box.shorten(time.time() + 120)                     # never longer
        self.assertLess(box.at, time.time() + 61)
        box.end()
        self.assertTrue(box.closed(time.time() + 0.01))

    def test_stopped_reads_the_job_the_pass_and_the_scene(self):
        self.assertFalse(ytdlp.stopped())
        for stop in ((ytdlp.Box(time.time() + 60), time.time() - 1),      # the scene's share is up
                     (_closed(), 0.0)):                                   # its pass ended
            token = ytdlp.STOP.set(stop)
            try:
                self.assertTrue(ytdlp.stopped(), stop)
            finally:
                ytdlp.STOP.reset(token)
        token = ytdlp.STOP.set((ytdlp.Box(time.time() + 60), time.time() + 60))
        try:
            self.assertFalse(ytdlp.stopped())
            ytdlp.set_deadline(time.time() - 1)                           # the job's own deadline
            self.assertTrue(ytdlp.stopped())
        finally:
            ytdlp.STOP.reset(token)

    def test_the_scenes_pool_threads_carry_its_stop(self):
        from concurrent.futures import ThreadPoolExecutor
        token = ytdlp.STOP.set((_closed(), 0.0))
        try:
            with ThreadPoolExecutor(2) as ex:
                bare = ex.submit(ytdlp.stopped).result()
                carried = ex.submit(ytdlp.with_stop(ytdlp.stopped)).result()
        finally:
            ytdlp.STOP.reset(token)
        self.assertFalse(bare)
        self.assertTrue(carried)


class StoppedSceneSpendsNothing(unittest.TestCase):
    def setUp(self):
        self.token = ytdlp.STOP.set((_closed(), 0.0))
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        ytdlp.STOP.reset(self.token)
        shutil.rmtree(self.d, True)

    def test_no_search_metadata_or_download_runs(self):
        with mock.patch.object(ytdlp.subprocess, "run", side_effect=AssertionError("must not run yt-dlp")), \
                mock.patch.object(media.subprocess, "run", side_effect=AssertionError("must not run yt-dlp")), \
                mock.patch.object(media.requests, "get", side_effect=AssertionError("must not fetch")):
            self.assertEqual(ytdlp._yt_candidates("ytsearch5:Lake Powell", False), [])
            self.assertEqual(ytdlp._yt_info("NEVERSEEN01")[0], {})
            self.assertEqual(ytdlp._yt_fetch("NEVERSEEN01", self.d, 10.0, 5.0), "")
            self.assertEqual(media._yt_fetch_retry("NEVERSEEN01", self.d, 10.0, 5.0), "")
            self.assertEqual(media._dm_fetch("x9abcde", self.d, 10.0, 5.0), "")
            self.assertEqual(media._web_fetch("https://vimeo.com/1", self.d, 10.0, 5.0), "")
            self.assertIsNone(media._download(MediaAsset(kind="image", source="web_image",
                                                         url="https://x/a.jpg"), "q", self.d))
            self.assertIsNone(media.source_for_segment("Lake Powell", 5.0, self.d))

    def test_no_more_providers(self):
        tried = []
        fake = [providers.Provider("a", "footage", "cc", lambda c: True, lambda c: tried.append("a")),
                providers.Provider("b", "footage", "cc", lambda c: True, lambda c: tried.append("b"))]
        with mock.patch.object(providers, "REGISTRY", fake):
            self.assertIsNone(providers.source_one(providers.SourceContext(query="q", seconds=5.0, work_dir=self.d)))
        self.assertEqual(tried, [])

    def test_an_answer_cut_short_is_not_cached_for_other_scenes(self):
        media.reset_cache()
        rows = [{"id": "VID00000001", "duration": 300.0, "aspect": 0.0, "title": "Lake Powell drone", "channel": ""}]
        self.assertEqual(media._yt_candidates_cached("ytsearch20:Lake Powell", False, "Lake Powell", "plain"), [])
        self.assertEqual(media._cached_search(lambda q: [], "Lake Powell", key="fake_source"), [])
        ytdlp.STOP.set(None)                                    # another scene, with time left
        with mock.patch.object(media, "_yt_candidates", return_value=rows), \
                mock.patch.object(media, "_google_youtube_candidates", return_value=[]):
            got = media._yt_candidates_cached("ytsearch20:Lake Powell", False, "Lake Powell", "plain")
        self.assertEqual([c["id"] for c in got], ["VID00000001"])
        self.assertEqual(media._cached_search(lambda q: ["found"], "Lake Powell", key="fake_source"), ["found"])
        media.reset_cache()


class NetworkSlots(unittest.TestCase):
    def test_a_waiting_download_goes_before_a_waiting_search(self):
        slots = ytdlp.Slots(1)
        self.assertTrue(slots.acquire(ytdlp.SEARCH))
        order = []

        def take(priority, name):
            slots.acquire(priority)
            order.append(name)
            slots.release()
        first = threading.Thread(target=take, args=(ytdlp.SEARCH, "search"))
        first.start()
        time.sleep(0.2)
        later = threading.Thread(target=take, args=(ytdlp.DOWNLOAD, "download"))
        later.start()
        time.sleep(0.2)
        slots.release()
        first.join(5)
        later.join(5)
        self.assertEqual(order, ["download", "search"])

    def test_a_stopped_scene_leaves_the_queue(self):
        slots = ytdlp.Slots(1)
        slots.acquire()
        t0 = time.time()
        self.assertFalse(slots.acquire(ytdlp.DOWNLOAD, give_up=lambda: time.time() - t0 > 0.3))
        self.assertEqual(slots.waiting(), 0)
        slots.release()
        self.assertTrue(slots.acquire(ytdlp.SEARCH))

    def test_the_route_is_claimed_once_a_slot_is_free(self):
        # Claimed while queueing, the Lake Powell proxies showed 34-59 "active"
        # requests each and the queue's wait as their latency.
        slots = ytdlp.Slots(1)
        slots.acquire()
        claimed = []
        with mock.patch.object(ytdlp, "_NET_SEM", slots), \
                mock.patch.object(ytdlp, "_acquire_proxy", side_effect=lambda *a: claimed.append(1) or ""), \
                mock.patch.object(ytdlp, "_release_proxy"), \
                mock.patch.object(ytdlp.subprocess, "run",
                                  return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            t = threading.Thread(target=ytdlp._yt_candidates, args=("ytsearch1:Lake Powell", False))
            t.start()
            time.sleep(0.3)
            self.assertEqual(claimed, [])
            slots.release()
            t.join(5)
        self.assertEqual(claimed, [1])


class DailymotionRoutes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.out = os.path.join(self.d, "dm_x9abcde_1.mp4")
        with open(self.out, "wb") as fh:
            fh.write(b"x" * 4000)

    def test_a_direct_download_claims_no_proxy(self):
        with mock.patch.object(media, "_PROXIES", ["http://p:1"]), \
                mock.patch.object(media, "_acquire_proxy") as acquire, \
                mock.patch.object(media.subprocess, "run",
                                  return_value=SimpleNamespace(returncode=0, stdout=self.out + "\n", stderr="")):
            self.assertEqual(media._dm_fetch("x9abcde", self.d, 10.0, 5.0), self.out)
        acquire.assert_not_called()

    def test_the_proxied_retry_gives_its_route_back(self):
        answers = [SimpleNamespace(returncode=1, stdout="", stderr="no video formats"),
                   SimpleNamespace(returncode=0, stdout=self.out + "\n", stderr="")]
        with mock.patch.object(media, "_PROXIES", ["http://p:1"]), \
                mock.patch.object(media, "_acquire_proxy", return_value="http://p:1") as acquire, \
                mock.patch.object(media, "_release_proxy") as release, \
                mock.patch.object(media.subprocess, "run", side_effect=answers):
            self.assertEqual(media._dm_fetch("x9abcde", self.d, 10.0, 5.0), self.out)
        self.assertEqual(acquire.call_count, 1)
        self.assertEqual(release.call_count, 1)
        self.assertTrue(release.call_args.args[1])


class FairShare(unittest.TestCase):
    def test_the_share(self):
        with mock.patch.object(config, "SCENE_SECONDS_MIN", 120), mock.patch.object(config, "SCENE_SECONDS_MAX", 300):
            self.assertEqual(media.scene_seconds(1800, 28, 130), 300)            # Lake Powell: 388 s, capped
            self.assertAlmostEqual(media.scene_seconds(1800, 28, 200), 252.0)
            self.assertEqual(media.scene_seconds(600, 8, 100), 120)              # never under the floor
            self.assertEqual(media.scene_seconds(420, 16, 10), 0.0)              # every scene starts at once
        with mock.patch.object(config, "SCENE_SECONDS_MAX", 0):
            self.assertEqual(media.scene_seconds(1800, 28, 130), 0.0)

    def _run(self, jobs, workers, **cfg):
        started, finished = [], []

        def endless(query, seconds, work_dir, **kw):
            started.append(query)
            while not ytdlp.stopped():          # a scene that finds nothing and would keep trying
                time.sleep(0.02)
            finished.append(time.time())
            return None
        patches = [mock.patch.object(media, "_source_one", side_effect=endless),
                   mock.patch.object(config, "FRESH_MOMENTS", False),
                   mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 0),
                   mock.patch("src.director.relaxed_queries", return_value=[])]
        patches += [mock.patch.object(config, k, v) for k, v in cfg.items()]
        for p in patches:
            p.start()
        try:
            media.reset_cache()
            t0 = time.time()
            media.source_many(jobs, self.d, workers=workers, refill=False)
            return started, finished, time.time() - t0
        finally:
            for p in reversed(patches):
                p.stop()

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def tearDown(self):
        ytdlp.set_deadline(0.0)

    def test_a_scene_that_finds_nothing_hands_its_thread_on(self):
        jobs = [{"index": i, "query": f"line{i}", "seconds": 3.0} for i in range(3)]
        started, _f, took = self._run(jobs, 1, SCENE_SECONDS_MIN=0.3, SCENE_SECONDS_MAX=0.3)
        self.assertEqual(sorted(started), ["line0", "line1", "line2"])    # every scene got its turn
        self.assertLess(took, 3.0)
        self.assertEqual(media.LAST_STATS["scene_seconds"], 0.3)

    def test_the_scenes_a_pass_gave_up_on_stop_with_it(self):
        ytdlp.set_deadline(time.time() + 25.6)               # the pass box: ~0.6 s
        jobs = [{"index": i, "query": f"line{i}", "seconds": 3.0} for i in range(3)]
        started, finished, took = self._run(jobs, 1, SCENE_SECONDS_MAX=0)
        t_end = time.time()
        deadline = time.time() + 3
        while not finished and time.time() < deadline:
            time.sleep(0.02)
        # Before: the first scene searched on until the job's deadline (25 s
        # here, 10 minutes on the pod) after the pass had stopped waiting.
        self.assertEqual(started, ["line0"])                 # nothing new starts once the box is shut
        self.assertTrue(finished, "the abandoned scene must stop with its pass")
        self.assertLess(finished[0] - t_end, 1.5)
        self.assertLess(media.LAST_STATS["pass1_seconds"], 2.0)


if __name__ == "__main__":
    unittest.main()
