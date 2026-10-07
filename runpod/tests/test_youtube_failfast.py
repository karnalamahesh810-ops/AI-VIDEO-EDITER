"""YouTube download failures by class (measured 2026-10-03..07: 368 of 3,107
download tries failed - 218 googlevideo 403s, 53 sections asked past a short
video's end, 48 bot checks on one route, 46 tries at 14 paid videos): what is
the video's fault and ends at once, what is the route's and rotates, what is
neither and simply tries again. No live network."""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from src import media
from src import ytdlp
from src.errors import FailureClass, RETRY, classify_ytdlp, ytdlp_reason

_ADVICE = (". Use --cookies-from-browser or --cookies for the authentication. See  "
           "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to "
           "manually pass cookies. Also see  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-"
           "youtube-cookies  for tips on effectively exporting YouTube cookies")


def _forget():
    media.reset_cache()
    with ytdlp._FAIL_LOCK:
        ytdlp._NEVER.clear()


class Classes(unittest.TestCase):
    def test_the_videos_own_refusals_end_it(self):
        for text in ("ERROR: [youtube] kH_WG74axPo: This video requires payment to watch",
                     "ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate "
                     "for some users" + _ADVICE,
                     "ERROR: [youtube] x: Join this channel to get access to members-only content like "
                     "this video, and other exclusive perks.",
                     "ERROR: [youtube] x: This video is available to this channel's members on level: Tier 1",
                     "ERROR: [youtube] x: This live event will begin in 3 hours.",
                     "ERROR: [youtube] x: Premieres in 10 hours",
                     "ERROR: [youtube] x: This live stream recording is not available.",
                     "ERROR: [youtube] x: This video is only available to Music Premium members",
                     "ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video"
                     + _ADVICE):
            self.assertEqual(classify_ytdlp(text, 1), FailureClass.MEDIA_UNAVAILABLE, text[:60])
            self.assertEqual(RETRY[FailureClass.MEDIA_UNAVAILABLE]["retries"], 0)

    def test_a_bot_check_is_the_address_whatever_the_apostrophe(self):
        for text in ("ERROR: [youtube] x: Sign in to confirm you’re not a bot" + _ADVICE,
                     "ERROR: [youtube] x: Sign in to confirm you're not a bot" + _ADVICE,
                     "ERROR: [youtube] x: The following content is not available on this app.",
                     "ERROR: [youtube] x: YouTube is requiring a captcha challenge before playback",
                     "ERROR: Unable to download API page: HTTP Error 403: Forbidden"):
            self.assertEqual(classify_ytdlp(text, 1), FailureClass.BOT_CHECK, text[:60])
        self.assertTrue(RETRY[FailureClass.BOT_CHECK]["proxy_fault"])

    def test_a_refused_stream_is_never_the_video_and_only_slowly_the_route(self):
        text = ("[in#0 @ 000001f9d6db07c0] Error opening input: Server returned 403 Forbidden (access denied)\n"
                "Error opening input file https://rr1---sn-x.googlevideo.com/videoplayback?a=b\n"
                "Error opening input files: Server returned 403 Forbidden (access denied)\n\n"
                "ERROR: ffmpeg exited with code 1")
        self.assertEqual(classify_ytdlp(text, 1), FailureClass.STREAM_REFUSED)
        policy = RETRY[FailureClass.STREAM_REFUSED]
        self.assertEqual((policy["retries"], policy["switch"], policy["proxy_fault"]), (2, True, True))
        from src.proxies import DEGRADED, HEALTHY, QUARANTINED, ProxyManager
        pm = ProxyManager(["http://a", "http://b"])
        a = pm.by_url["http://a"]
        pm.release("http://a", False, FailureClass.STREAM_REFUSED, 500)
        self.assertEqual(a.state, HEALTHY)                  # one refused stream: still in the rotation
        pm.release("http://a", False, FailureClass.STREAM_REFUSED, 500)
        self.assertEqual(a.state, DEGRADED)
        pm.release("http://a", False, FailureClass.STREAM_REFUSED, 500)
        self.assertEqual(a.state, QUARANTINED)              # three in a row: benched like a dead route
        self.assertEqual(pm.acquire(), "http://b")

    def test_geo_rate_limit_and_the_rest(self):
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: Video unavailable. The uploader has not made this "
                                        "video available in your country", 1), FailureClass.GEO_BLOCKED)
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: This content isn't available, try again later. "
                                        "The current session has been rate-limited by YouTube for up to an hour.",
                                        1), FailureClass.RATE_LIMITED)
        self.assertEqual(classify_ytdlp("ERROR: [youtube] x: Requested format is not available", 1),
                         FailureClass.ACCESS_DENIED)
        self.assertEqual(classify_ytdlp("Numerical result out of range\nError while processing the decoded data "
                                        "for stream #0:0\n\nERROR: ffmpeg exited with code 1", 1),
                         FailureClass.FFMPEG_FAILURE)

    def test_the_reason_kept_is_the_reason_not_the_cookies_advice(self):
        got = ytdlp_reason("WARNING: x\nERROR: [youtube] abc: Sign in to confirm you’re not a bot" + _ADVICE)
        self.assertEqual(got, "ERROR: [youtube] abc: Sign in to confirm you’re not a bot")
        got = ytdlp_reason("[in#0 @ 0x1] Error opening input: Server returned 403 Forbidden (access denied)\n"
                           "Error opening input files: Server returned 403 Forbidden (access denied)\n\n"
                           "ERROR: ffmpeg exited with code 1")
        self.assertEqual(got, "Error opening input files: Server returned 403 Forbidden (access denied) | "
                              "ERROR: ffmpeg exited with code 1")
        self.assertNotIn("http", ytdlp_reason("ERROR: unable to open https://x.example/a?sig=1"))


class WhoIsToBlame(unittest.TestCase):
    def setUp(self):
        _forget()

    def tearDown(self):
        _forget()

    def test_a_bot_check_on_two_routes_never_condemns_the_video(self):
        for route in ("p1", "p2", "p3"):
            self.assertEqual(ytdlp._note_failure("VIDBOT00001", FailureClass.BOT_CHECK, route), FailureClass.BOT_CHECK)
        self.assertFalse(ytdlp._video_unavailable("VIDBOT00001"))

    def test_a_plain_refusal_or_geo_lock_on_two_routes_does(self):
        ytdlp._note_failure("VIDGEO00001", FailureClass.GEO_BLOCKED, "p1")
        self.assertFalse(ytdlp._video_unavailable("VIDGEO00001"))
        self.assertEqual(ytdlp._note_failure("VIDGEO00001", FailureClass.GEO_BLOCKED, "p2"),
                         FailureClass.MEDIA_UNAVAILABLE)
        self.assertTrue(ytdlp._video_unavailable("VIDGEO00001"))
        media.reset_cache()                     # the two-route guess is this job's only
        self.assertFalse(ytdlp._video_unavailable("VIDGEO00001"))

    def test_youtubes_own_never_outlives_the_job_on_this_worker(self):
        ytdlp._note_failure("VIDPAID0001", FailureClass.MEDIA_UNAVAILABLE, "p1",
                            "ERROR: [youtube] VIDPAID0001: This video requires payment to watch")
        media.reset_cache()                     # the next job on this worker
        self.assertTrue(ytdlp._video_unavailable("VIDPAID0001"))
        self.assertIn("requires payment", ytdlp.never_reason("VIDPAID0001"))
        with mock.patch.object(ytdlp.time, "time", return_value=time.time() + ytdlp._NEVER_TTL + 5):
            self.assertFalse(ytdlp._video_unavailable("VIDPAID0001"))

    def test_retries_by_class(self):
        def run(outcomes):
            calls = []
            it = iter(outcomes)

            def fake_fetch(vid, out_dir, start, seconds):
                cls = next(it)
                calls.append(cls)
                if cls is None:
                    media._LAST_FAILURE.set(None)
                    return "/w/ok.mp4"
                media._note_failure(vid, cls, f"p{len(calls)}")
                return ""
            with mock.patch.object(media, "_yt_fetch", fake_fetch), \
                    mock.patch.object(media.time, "sleep", lambda s: None):
                _forget()
                return media._yt_fetch_retry("VIDRETRY001", "/w", 1.0, 7.0, "t"), calls
        S, B, P = FailureClass.STREAM_REFUSED, FailureClass.BOT_CHECK, FailureClass.MEDIA_UNAVAILABLE
        self.assertEqual(run([S, S, None]), ("/w/ok.mp4", [S, S, None]))     # a refused stream: 2 more tries
        self.assertEqual(run([S, S, S, None])[0], "")
        self.assertEqual(run([B, B, None]), ("/w/ok.mp4", [B, B, None]))     # bot checks rotate on
        self.assertEqual(run([P, None]), ("", [P]))                           # paid: one try, no more


class SearchSaysNever(unittest.TestCase):
    def setUp(self):
        _forget()

    def tearDown(self):
        _forget()

    def test_live_premieres_members_and_known_refusals_never_reach_the_ranking(self):
        ytdlp._note_failure("PAIDPAID001", FailureClass.MEDIA_UNAVAILABLE, "p1", "requires payment")
        rows = [
            "GOODGOOD001\t95\thttps://www.youtube.com/watch?v=GOODGOOD001\tKTLA 5\tNA\tNA\tFlood in Los Angeles",
            "LIVELIVE001\tNA\thttps://www.youtube.com/watch?v=LIVELIVE001\tNews\tis_live\tNA\tLIVE: storm",
            "SOONSOON001\tNA\thttps://www.youtube.com/watch?v=SOONSOON001\tNews\tis_upcoming\tNA\tPremiere",
            "MEMBMEMB001\t300\thttps://www.youtube.com/watch?v=MEMBMEMB001\tCh\tNA\tsubscriber_only\tMembers",
            "PREMPREM001\t300\thttps://www.youtube.com/watch?v=PREMPREM001\tCh\tNA\tpremium_only\tPremium",
            "PAIDPAID001\t5400\thttps://www.youtube.com/watch?v=PAIDPAID001\tFilms\tNA\tNA\tThe Film",
            "WASLIVE0001\t3600\thttps://www.youtube.com/watch?v=WASLIVE0001\tNews\twas_live\tpublic\tYesterday",
            "SHORTSHORT1\t40\thttps://www.youtube.com/shorts/SHORTSHORT1\tNA\tNA\tNA\tA short\twith a tab",
        ]
        result = SimpleNamespace(returncode=0, stdout="\n".join(rows) + "\n", stderr="")
        with mock.patch.object(media.subprocess, "run", return_value=result) as run:
            got = media._yt_candidates("ytsearch20:la flood", False)
        self.assertIn("%(live_status)s\t%(availability)s", " ".join(run.call_args.args[0]))
        self.assertEqual([c["id"] for c in got], ["GOODGOOD001", "WASLIVE0001", "SHORTSHORT1"])
        self.assertEqual(got[0], {"id": "GOODGOOD001", "duration": 95.0, "aspect": 0.0,
                                  "title": "Flood in Los Angeles", "channel": "KTLA 5"})
        self.assertEqual((got[2]["aspect"], got[2]["channel"], got[2]["title"]), (9 / 16, "", "A short\twith a tab"))


class SectionInsideTheVideo(unittest.TestCase):
    def setUp(self):
        _forget()

    def tearDown(self):
        _forget()

    def test_fit_start(self):
        self.assertEqual(ytdlp.fit_start(20.0, 6.5, 14.0), 7.25)        # past the end
        self.assertEqual(ytdlp.fit_start(13.5, 6.5, 14.0), 7.25)        # its last half second
        self.assertEqual(ytdlp.fit_start(5.0, 6.5, 14.0), 5.0)          # inside: untouched
        self.assertEqual(ytdlp.fit_start(20.0, 6.5, 0.0), 20.0)         # length unknown
        self.assertEqual(ytdlp.fit_start(20.0, 30.0, 14.0), 0.0)

    def _run(self, results, start=20.0):
        calls = []
        it = iter(results)

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return next(it)
        with mock.patch.object(ytdlp.subprocess, "run", fake_run), \
                mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                mock.patch.object(ytdlp, "_release_proxy"), \
                mock.patch.object(ytdlp, "playable_video", return_value=True):
            got = ytdlp._yt_fetch("SHORTVID001", self.dir, start, 6.5)
        return got, [c[c.index("--download-sections") + 1] for c in calls]

    def test_a_start_past_a_short_videos_end_moves_inside_it_once(self):
        with tempfile.TemporaryDirectory() as self.dir:
            path = os.path.join(self.dir, "yt_SHORTVID001_ok.mp4")
            with open(path, "wb") as fh:
                fh.write(b"x" * 2048)
            erange = SimpleNamespace(returncode=1, stdout="DLINFO 14.0|137\n", stderr=(
                "Numerical result out of range\nError while processing the decoded data for stream #0:0\n\n"
                "ERROR: ffmpeg exited with code 1"))
            ok = SimpleNamespace(returncode=0, stdout=f"DLINFO 14.0|137\n{path}\n", stderr="")
            got, sections = self._run([erange, ok])
            self.assertEqual(got, path)
            self.assertEqual(sections, ["*20.0-26.5", "*7.2-13.8"])
            # The length is known now: the next ask past the end goes inside at once.
            got, sections = self._run([ok], start=30.0)
            self.assertEqual(sections, ["*7.2-13.8"])

    def test_newer_ffmpegs_wording_is_fitted_too(self):
        # ffmpeg 9 says "Could not open encoder before EOF" where 5.1 said ERANGE: the printed length decides.
        with tempfile.TemporaryDirectory() as self.dir:
            path = os.path.join(self.dir, "yt_SHORTVID001_ok.mp4")
            with open(path, "wb") as fh:
                fh.write(b"x" * 2048)
            eof = SimpleNamespace(returncode=1, stdout="DLINFO 24|137\n", stderr=(
                "[vost#0:0/libx264 @ 0x1] Could not open encoder before EOF\n"
                "ERROR: ffmpeg exited with code 4294967262"))
            ok = SimpleNamespace(returncode=0, stdout=f"DLINFO 24|137\n{path}\n", stderr="")
            got, sections = self._run([eof, ok], start=25.0)
            self.assertEqual((got, sections), (path, ["*25.0-31.5", "*17.2-23.8"]))

    def test_past_the_end_twice_is_one_fit_only(self):
        with tempfile.TemporaryDirectory() as self.dir:
            erange = SimpleNamespace(returncode=1, stdout="DLINFO 14.0|137\n",
                                     stderr="Numerical result out of range\nERROR: ffmpeg exited with code 1")
            got, sections = self._run([erange, erange])
            self.assertEqual((got, len(sections)), ("", 2))
            self.assertFalse(ytdlp._video_unavailable("SHORTVID001"))


class DownloadProbe(unittest.TestCase):
    def test_every_route_by_name_and_no_credentials(self):
        secret = "http://user:pass@isp.example:10001"

        def fake_run(cmd, **kw):
            out_dir = os.path.dirname(cmd[cmd.index("-o") + 1])
            if "--proxy" in cmd:
                return SimpleNamespace(returncode=1, stdout="DLINFO 600|137\n", stderr=(
                    f"ERROR: [youtube] x: Sign in to confirm you’re not a bot via {secret}" + _ADVICE))
            with open(os.path.join(out_dir, "probe.mp4"), "wb") as fh:
                fh.write(b"x" * 4096)
            return SimpleNamespace(returncode=0, stdout="DLINFO 600|399\n", stderr="")
        with mock.patch.object(ytdlp.config, "YTDLP_PROXIES", [secret]), \
                mock.patch.object(ytdlp.subprocess, "run", fake_run), \
                mock.patch.object(ytdlp, "playable_video", return_value=True):
            rows = ytdlp.probe_download("ka2S39HhLsM")
        self.assertEqual([(r["route"], r["ok"], r["format"]) for r in rows],
                         [("direct", True, "399"), ("proxy#1", False, "137")])
        self.assertTrue(rows[1]["why"].startswith("BOT_CHECK"))
        self.assertNotIn("pass", str(rows))
        self.assertNotIn("isp.example", str(rows))


if __name__ == "__main__":
    unittest.main()
