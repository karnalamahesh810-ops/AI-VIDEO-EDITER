import unittest
from unittest import mock

from src import errors, media, proxies
from src.errors import FailureClass, classify_exception, classify_ytdlp
from src.proxies import DEGRADED, HEALTHY, QUARANTINED, RECOVERING, ProxyManager


class Classify(unittest.TestCase):
    def test_ytdlp_messages(self):
        # The address, never the video (tests/test_youtube_failfast.py).
        self.assertEqual(classify_ytdlp("ERROR: Sign in to confirm you're not a bot", 1), FailureClass.BOT_CHECK)
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: Video unavailable", 1), FailureClass.MEDIA_UNAVAILABLE)
        self.assertEqual(classify_ytdlp("ERROR: Private video. Sign in if you've been granted access", 1),
                         FailureClass.MEDIA_UNAVAILABLE)
        self.assertEqual(classify_ytdlp("HTTP Error 429: Too Many Requests", 1), FailureClass.RATE_LIMITED)
        self.assertEqual(classify_ytdlp("Unable to connect to proxy", 1), FailureClass.PROXY_FAILURE)
        self.assertEqual(classify_ytdlp("ERROR: ffmpeg exited with code 1", 1), FailureClass.FFMPEG_FAILURE)
        self.assertEqual(classify_ytdlp("", 1, timed_out=True), FailureClass.NETWORK_TIMEOUT)
        self.assertEqual(classify_ytdlp("", 0, empty=True), FailureClass.INVALID_MEDIA)
        self.assertEqual(classify_ytdlp("", None, missing=True), FailureClass.PROVIDER_UNAVAILABLE)
        self.assertEqual(classify_ytdlp("something odd", 1), FailureClass.UNKNOWN)

    def test_provider_exceptions(self):
        import requests
        self.assertEqual(classify_exception(requests.exceptions.ReadTimeout("t")), FailureClass.NETWORK_TIMEOUT)
        self.assertEqual(classify_exception(RuntimeError("HTTP 429 slow down")), FailureClass.RATE_LIMITED)
        self.assertEqual(classify_exception(RuntimeError("403 Forbidden")), FailureClass.ACCESS_DENIED)
        self.assertEqual(classify_exception(RuntimeError("502 bad gateway")), FailureClass.PROVIDER_UNAVAILABLE)
        self.assertEqual(classify_exception(ValueError("bad json")), FailureClass.INVALID_MEDIA)


class Manager(unittest.TestCase):
    def test_states_move_healthy_degraded_quarantined_recovering_healthy(self):
        pm = ProxyManager(["http://a", "http://b"], quarantine_base=100, quarantine_max=800)
        a = pm.by_url["http://a"]
        pm.release("http://a", False, FailureClass.PROXY_FAILURE, 900)
        self.assertEqual(a.state, HEALTHY)
        pm.release("http://a", False, FailureClass.NETWORK_TIMEOUT, 900)
        self.assertEqual(a.state, DEGRADED)
        pm.release("http://a", False, FailureClass.ACCESS_DENIED, 900)
        self.assertEqual(a.state, QUARANTINED)
        self.assertEqual(a.quarantines, 1)
        self.assertEqual(a.last_failure_type, "ACCESS_DENIED")
        # Quarantined routes are not picked while another is healthy.
        self.assertEqual(pm.acquire(), "http://b")
        # After the quarantine the route is recovering: one success restores it.
        with mock.patch.object(proxies.time, "time", return_value=a.quarantined_until + 1):
            pm.snapshot()
            self.assertEqual(a.state, RECOVERING)
            pm.release("http://a", True, None, 300)
            self.assertEqual(a.state, HEALTHY)
        self.assertEqual(a.success_rate, 0.25)

    def test_video_faults_do_not_count_and_quarantine_backs_off(self):
        pm = ProxyManager(["http://a"], quarantine_base=100, quarantine_max=250)
        a = pm.by_url["http://a"]
        for cls in (FailureClass.MEDIA_UNAVAILABLE, FailureClass.FFMPEG_FAILURE, FailureClass.PROVIDER_UNAVAILABLE):
            pm.release("http://a", False, cls, 100)
        self.assertEqual((a.state, a.failures), (HEALTHY, 0))
        pm.release("http://a", False, FailureClass.RATE_LIMITED, 100)      # straight to quarantine
        self.assertEqual(a.state, QUARANTINED)
        first = a.quarantined_until
        with mock.patch.object(proxies.time, "time", return_value=first + 1):
            pm.snapshot()                                                  # recovering
            pm.release("http://a", False, FailureClass.PROXY_FAILURE, 100)  # fails its trial
        self.assertEqual(a.state, QUARANTINED)
        self.assertEqual(a.quarantines, 2)
        self.assertGreater(a.quarantined_until - (first + 1), 150)         # doubled, capped at 250

    def test_pick_prefers_idle_fast_healthy_routes_and_never_prints_urls(self):
        pm = ProxyManager(["http://slow", "http://fast"], direct=False)
        pm.release("http://slow", True, None, 900)
        pm.release("http://fast", True, None, 200)
        self.assertEqual(pm.acquire(), "http://fast")          # fast, idle
        self.assertEqual(pm.acquire(), "http://slow")          # fast is busy now
        snap = pm.snapshot()
        self.assertEqual([r["proxy_id"] for r in snap], ["proxy_01", "proxy_02"])
        self.assertNotIn("http", str(snap))
        self.assertEqual(snap[1]["active_jobs"], 1)
        self.assertEqual(snap[1]["domains"]["youtube.com"]["ok"], 1)


class OneRefusalDoesNotSideline(unittest.TestCase):
    """The Lake Powell pod (2026-10-01): 11 of 17 proxies degraded at 97-99% success,
    never picked again while 4 healthy ones carried all of YouTube."""

    def _pm(self):
        pm = ProxyManager(["http://a", "http://b", "http://c"], direct=False)
        for url in ("http://a", "http://b"):
            for _ in range(20):
                pm.release(url, True, None, 300)
        pm.release("http://b", False, FailureClass.ACCESS_DENIED, 300)     # one refusal after 20 successes
        for _ in range(2):
            pm.release("http://c", True, None, 300)
        pm.release("http://c", False, FailureClass.ACCESS_DENIED, 300)     # one refusal, little record
        return pm

    def test_a_clean_record_keeps_the_route_in_rotation(self):
        pm = self._pm()
        self.assertEqual((pm.by_url["http://b"].state, pm.by_url["http://c"].state), (DEGRADED, DEGRADED))
        picks = [pm.acquire() for _ in range(4)]
        self.assertEqual(picks[0], "http://a")                 # an idle healthy route first
        self.assertIn("http://b", picks)                       # then b shares the load
        self.assertNotIn("http://c", picks[:3])                # c, with no record, only when a and b are busy

    def test_two_refusals_in_a_row_still_quarantine(self):
        pm = self._pm()
        pm.release("http://b", False, FailureClass.ACCESS_DENIED, 300)
        self.assertEqual(pm.by_url["http://b"].state, QUARANTINED)
        self.assertNotIn("http://b", [pm.acquire() for _ in range(3)])

    def test_three_successes_restore_it(self):
        pm = self._pm()
        for _ in range(3):
            pm.release("http://b", True, None, 300)
        self.assertEqual(pm.by_url["http://b"].state, HEALTHY)


class RetryPolicy(unittest.TestCase):
    def _run(self, outcomes, video="VID00000001"):
        calls = []
        it = iter(outcomes)

        def fake_fetch(vid, out_dir, start, seconds):
            cls, proxy = next(it)
            calls.append(cls)
            if cls is None:
                media._LAST_FAILURE.set(None)
                return "/w/ok.mp4"
            media._note_failure(vid, cls, proxy)
            return ""
        with mock.patch.object(media, "_yt_fetch", fake_fetch), \
                mock.patch.object(media.time, "sleep", lambda s: None):
            media.reset_cache()
            return media._yt_fetch_retry(video, "/w", 1.0, 7.0, "t"), calls

    def test_unavailable_video_is_not_retried(self):
        path, calls = self._run([(FailureClass.MEDIA_UNAVAILABLE, "p1"), (None, "p2")])
        self.assertEqual((path, len(calls)), ("", 1))

    def test_timeouts_retry_on_other_routes_then_succeed(self):
        path, calls = self._run([(FailureClass.NETWORK_TIMEOUT, "p1"), (FailureClass.PROXY_FAILURE, "p2"), (None, "p3")])
        self.assertEqual((path, len(calls)), ("/w/ok.mp4", 3))

    def test_refused_on_two_routes_means_the_video_not_the_proxies(self):
        path, calls = self._run([(FailureClass.ACCESS_DENIED, "p1"), (FailureClass.ACCESS_DENIED, "p2"), (None, "p3")])
        self.assertEqual((path, len(calls)), ("", 2))
        self.assertTrue(media._video_unavailable("VID00000001"))
        self.assertEqual(media._LAST_FAILURE.get()[0], FailureClass.MEDIA_UNAVAILABLE)

    def test_metadata_uses_the_full_network_arguments(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd

            class P:
                returncode, stdout, stderr = 0, "{}", ""
            return P()
        with mock.patch.object(media._ytdlp.subprocess, "run", fake_run), \
                mock.patch.object(media._ytdlp, "_acquire_proxy", return_value="http://p"), \
                mock.patch.object(media._ytdlp, "_release_proxy"):
            media.reset_cache()
            media._yt_info("VID00000002")
        for arg in media._yt_network_args("http://p"):
            self.assertIn(arg, seen["cmd"])


if __name__ == "__main__":
    unittest.main()
