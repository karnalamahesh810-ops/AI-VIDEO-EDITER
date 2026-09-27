import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from src import media, ytdlp


class UsableTitle(unittest.TestCase):
    def test_one_check_for_sellers_talking_heads_and_vertical(self):
        self.assertTrue(media._usable_title("Lake Mead aerial drone footage", "c", 1.78))
        self.assertFalse(media._usable_title("Lake Mead | Podcast episode 12", "c", 1.78))
        self.assertFalse(media._usable_title("Lake Mead aerial", "c", 0.56))
        self.assertFalse(media._usable_title("Lake Mead 4K stock footage - Pond5", "Pond5", 1.78))
        self.assertTrue(media._usable_title("Lake Mead aerial", "", 0.0))    # unknown aspect passes


class JobEpoch(unittest.TestCase):
    def test_a_download_finishing_after_its_job_ended_is_discarded(self):
        d = tempfile.mkdtemp()
        made = {}

        def fake_run(cmd, **kw):
            out = os.path.join(d, "yt_VIDEO000000_1000_7000_abc.mp4")
            with open(out, "wb") as fh:
                fh.write(b"x" * 4096)
            made["path"] = out
            ytdlp.EPOCH[0] += 1                        # the next job started meanwhile

            class P:
                returncode, stdout, stderr = 0, out + "\n", ""
            return P()
        with mock.patch.object(ytdlp.subprocess, "run", fake_run), \
                mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                mock.patch.object(ytdlp, "playable_video", return_value=True):
            got = ytdlp._yt_fetch("VIDEO000000", d, 1.0, 7.0)
        self.assertEqual(got, "")
        self.assertFalse(os.path.exists(made["path"]))

    def test_reset_moves_the_epoch(self):
        before = ytdlp.EPOCH[0]
        media.reset_cache()
        self.assertEqual(ytdlp.EPOCH[0], before + 1)


class DrainPools(unittest.TestCase):
    def test_tracked_pools_are_waited_for_a_bounded_time(self):
        release = threading.Event()
        pool = media._new_pool(1)
        pool.submit(release.wait, 5.0)
        t0 = time.time()
        busy = media.drain_pools(timeout=0.2)
        self.assertEqual(busy, 1)
        self.assertLess(time.time() - t0, 1.5)
        release.set()
        self.assertEqual(media.drain_pools(timeout=0.2), 0)     # nothing tracked any more

    def test_finished_pools_drain_at_once(self):
        pool = media._new_pool(2)
        f = pool.submit(lambda: 1)
        self.assertEqual(f.result(), 1)
        self.assertEqual(media.drain_pools(timeout=1.0), 0)


if __name__ == "__main__":
    unittest.main()
