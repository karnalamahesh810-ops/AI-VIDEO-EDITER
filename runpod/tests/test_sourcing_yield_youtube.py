"""
YouTube clip retries (docs/sourcing-yield-2026-10-18.md). The owner's three
renders of 2026-10-12/13: 164 "Server returned 403 Forbidden | ffmpeg exited
with code 1" (STREAM_REFUSED) and 94 "Sign in to confirm you're not a bot"
(BOT_CHECK). A refused stream is a passing session on that address: the retry
must go through another route - the manager's latency ranking handed it the
same one. Paid / members-only videos are never retried. Offline: yt-dlp is
never run (media._yt_fetch is faked).
"""
import unittest
from unittest import mock

from src import config, media, ytdlp
from src.errors import FailureClass, classify_ytdlp
from src.proxies import QUARANTINED, ProxyManager


class SampleMessages(unittest.TestCase):
    def test_the_measured_messages_classify(self):
        self.assertEqual(classify_ytdlp("ERROR: Server returned 403 Forbidden | ffmpeg exited with code 1", 1),
                         FailureClass.STREAM_REFUSED)
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: Sign in to confirm you're not a bot", 1),
                         FailureClass.BOT_CHECK)
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: This video requires payment to watch", 1),
                         FailureClass.MEDIA_UNAVAILABLE)
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: Join this channel to get access to members-only "
                                        "content like this video", 1), FailureClass.MEDIA_UNAVAILABLE)


class ManagerAvoids(unittest.TestCase):
    def test_a_retry_takes_a_route_not_yet_tried(self):
        pm = ProxyManager(["http://a", "http://b", "http://c"])
        pm.by_url["http://a"].latency_ms = 100        # the fastest: the manager's first pick
        pm.by_url["http://b"].latency_ms = 300
        pm.by_url["http://c"].latency_ms = 500
        self.assertEqual(pm.acquire(), "http://a")
        pm.release("http://a", True)
        self.assertEqual(pm.acquire(avoid={"http://a"}), "http://b")
        pm.release("http://b", True)
        self.assertEqual(pm.acquire(avoid={"http://a", "http://b"}), "http://c")

    def test_every_route_tried_falls_back_to_the_best(self):
        pm = ProxyManager(["http://a", "http://b"])
        pm.by_url["http://a"].latency_ms = 100
        pm.by_url["http://b"].latency_ms = 300
        self.assertEqual(pm.acquire(avoid={"http://a", "http://b"}), "http://a")

    def test_a_quarantined_route_never_wins_over_a_tried_healthy_one(self):
        pm = ProxyManager(["http://a", "http://b"])
        pm.by_url["http://b"].state = QUARANTINED
        pm.by_url["http://b"].quarantined_until = 9e18
        self.assertEqual(pm.acquire(avoid={"http://a"}), "http://a")


class RetriesTakeOtherRoutes(unittest.TestCase):
    def _run(self, outcomes, **flags):
        seen = []
        it = iter(outcomes)

        def fake_fetch(vid, out_dir, start, seconds):
            seen.append((set(ytdlp.AVOID_ROUTES.get()), ytdlp.RETRY_CLIENT.get(), ytdlp._client_args()))
            cls, proxy = next(it)
            if cls is None:
                media._LAST_FAILURE.set(None)
                return "/w/ok.mp4"
            media._note_failure(vid, cls, proxy)
            return ""
        patches = [mock.patch.object(media, "_yt_fetch", fake_fetch), mock.patch.object(media.time, "sleep", lambda s: None)]
        patches += [mock.patch.object(config, k, v) for k, v in flags.items()]
        for p in patches:
            p.start()
        try:
            media.reset_cache()
            path = media._yt_fetch_retry("VID0000000A", "/w", 1.0, 7.0, "t")
        finally:
            for p in reversed(patches):
                p.stop()
        return path, seen

    def test_a_refused_stream_is_retried_on_routes_not_yet_tried(self):
        path, seen = self._run([(FailureClass.STREAM_REFUSED, "http://p1"), (FailureClass.STREAM_REFUSED, "http://p2"),
                                (None, "http://p3")])
        self.assertEqual(path, "/w/ok.mp4")
        self.assertEqual([s[0] for s in seen], [set(), {"http://p1"}, {"http://p1", "http://p2"}])
        self.assertEqual(ytdlp.AVOID_ROUTES.get(), frozenset())          # nothing left behind for the next clip

    def test_a_bot_check_too_and_the_direct_route_counts(self):
        path, seen = self._run([(FailureClass.BOT_CHECK, ""), (None, "http://p1")])
        self.assertEqual(path, "/w/ok.mp4")
        self.assertEqual(seen[1][0], {""})

    def test_paid_and_members_only_are_tried_once(self):
        path, seen = self._run([(FailureClass.MEDIA_UNAVAILABLE, "http://p1"), (None, "http://p2")])
        self.assertEqual((path, len(seen)), ("", 1))

    def test_no_player_client_switch_by_default(self):
        _path, seen = self._run([(FailureClass.STREAM_REFUSED, "http://p1"), (None, "http://p2")])
        self.assertEqual([s[2] for s in seen], [[], []])

    def test_the_player_client_switch_when_set(self):
        _path, seen = self._run([(FailureClass.STREAM_REFUSED, "http://p1"), (None, "http://p2")],
                                YTDLP_RETRY_PLAYER_CLIENT="tv,web_safari; rm -rf /")
        self.assertEqual(seen[0][2], [])                                 # the first try as always
        self.assertEqual(seen[1][2], ["--extractor-args", "youtube:player_client=tv,web_safarirm-rf"])

    def test_a_timeout_retry_keeps_the_default_client(self):
        _path, seen = self._run([(FailureClass.NETWORK_TIMEOUT, "http://p1"), (None, "http://p2")],
                                YTDLP_RETRY_PLAYER_CLIENT="tv")
        self.assertEqual(seen[1][2], [])
        self.assertEqual(seen[1][0], {"http://p1"})

    def test_the_download_command_carries_the_client_only_on_such_a_retry(self):
        cmds = []

        def fake_run(cmd, **kw):
            cmds.append(cmd)

            class P:
                returncode, stdout, stderr = 1, "", "ERROR: Server returned 403 Forbidden | ffmpeg exited with code 1"
            return P()
        with mock.patch.object(ytdlp.subprocess, "run", fake_run), \
                mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                mock.patch.object(ytdlp, "_release_proxy"), \
                mock.patch.object(ytdlp.events, "emit"):
            media.reset_cache()
            ytdlp._yt_fetch("VID0000000B", "/w", 5.0, 4.0)
            token = ytdlp.RETRY_CLIENT.set("tv")
            try:
                ytdlp._yt_fetch("VID0000000B", "/w", 5.0, 4.0)
            finally:
                ytdlp.RETRY_CLIENT.reset(token)
        self.assertNotIn("--extractor-args", cmds[0])
        self.assertEqual(cmds[1][cmds[1].index("--extractor-args") + 1], "youtube:player_client=tv")

    def test_acquire_hears_the_avoid_list_only_with_the_flag(self):
        token = ytdlp.AVOID_ROUTES.set(frozenset({"http://p1"}))
        try:
            with mock.patch.object(ytdlp, "_PROXIES", ["http://p1", "http://p2"]), \
                    mock.patch.object(ytdlp.PROXY_MANAGER, "acquire", return_value="x") as acq:
                ytdlp._acquire_proxy()
                self.assertEqual(acq.call_args.kwargs.get("avoid"), frozenset({"http://p1"}))
                with mock.patch.object(config, "YTDLP_RETRY_OTHER_ROUTE", False):
                    ytdlp._acquire_proxy()
                self.assertNotIn("avoid", acq.call_args.kwargs)
        finally:
            ytdlp.AVOID_ROUTES.reset(token)


if __name__ == "__main__":
    unittest.main()
