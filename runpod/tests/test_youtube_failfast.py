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

    def test_a_refused_stream_is_neither_the_video_nor_the_route(self):
        text = ("[in#0 @ 000001f9d6db07c0] Error opening input: Server returned 403 Forbidden (access denied)\n"
                "Error opening input file https://rr1---sn-x.googlevideo.com/videoplayback?a=b\n"
                "Error opening input files: Server returned 403 Forbidden (access denied)\n\n"
                "ERROR: ffmpeg exited with code 1")
        self.assertEqual(classify_ytdlp(text, 1), FailureClass.STREAM_REFUSED)
        policy = RETRY[FailureClass.STREAM_REFUSED]
        self.assertEqual((policy["retries"], policy["proxy_fault"]), (2, False))

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


if __name__ == "__main__":
    unittest.main()
