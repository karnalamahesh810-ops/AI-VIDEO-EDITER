"""
YouTube section download quality (src/ytdlp.py _fetch_cmd, DOWNLOAD_QUALITY).

A section cut at exact frames (--force-keyframes-at-cuts) is never stream-
copied by yt-dlp: ffmpeg re-encodes it. The legacy command left that to
ffmpeg's defaults (x264 crf 23) on YouTube's H.264-only pick. High mode takes
the best SDR picture in any codec (AV1 > VP9 > H.264) and re-encodes it once at
a high quality into a plain H.264 yuv420p .mp4; hero clips may come from a
>1080 stream under a bitrate cap, downscaled to 1080. No network here.
"""
import os
import shlex
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import config, ytdlp  # noqa: E402

# The command exactly as it was before DOWNLOAD_QUALITY existed (CLIP_SHARPNESS_CHECK on).
LEGACY = [
    "yt-dlp", "https://www.youtube.com/watch?v=abcdefghijk",
    "--download-sections", "*10.0-15.0", "--force-keyframes-at-cuts",
    "-f", ("bv*[height<=1080][ext=mp4][protocol^=https]/bv*[height<=1080][ext=mp4]"
           "/bv*[height<=1080]/b[height<=1080]"),
    "-S", "res:1080",
    "--no-playlist", "--no-warnings", "--merge-output-format", "mp4",
    "-o", "out.%(ext)s", "--print", "after_move:filepath",
    "--print", "before_dl:DLINFO %(duration)s|%(format_id)s",
]
LEGACY_AUDIO_FORMAT = ("bv*[height<=1080][ext=mp4][protocol^=https]+ba[ext=m4a][protocol^=https]"
                       "/bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]")


def build(quality="high", vertical=False, **kw):
    with mock.patch.multiple(config, DOWNLOAD_QUALITY=quality, ALLOW_VERTICAL=vertical,
                             CLIP_SHARPNESS_CHECK=True, DOWNLOAD_CRF=16, DOWNLOAD_PRESET="medium",
                             HERO_MAX_TBR=9000):
        return ytdlp._fetch_cmd("abcdefghijk", "out.%(ext)s", 10.0, 5.0, **kw)


def opt(cmd, name):
    return cmd[cmd.index(name) + 1]


def encode(cmd):
    """The ffmpeg output options, as yt-dlp will split them (shlex)."""
    key, _, val = opt(cmd, "--downloader-args").partition(":")
    assert key == "ffmpeg_o", key
    return shlex.split(val)


class HighFootage(unittest.TestCase):
    def setUp(self):
        self.cmd = build()
        self.fmt = opt(self.cmd, "-f")

    def test_any_codec_sdr_up_to_1080_direct_https_first(self):
        self.assertNotIn("[ext=mp4]", self.fmt)
        alts = self.fmt.split("/")
        self.assertEqual(alts[0], "bv*[height<=1080][dynamic_range=SDR][protocol^=https]")
        self.assertIn("[dynamic_range=SDR]", alts[1])
        self.assertTrue(all("height<=1080" in a for a in alts))
        self.assertNotIn("+ba", self.fmt)  # footage is silent

    def test_sort_res_then_fps_30_then_sdr_then_newest_codec(self):
        self.assertEqual(opt(self.cmd, "-S"), "res:1080,fps:30,hdr:sdr,vcodec")

    def test_one_high_quality_reencode_to_h264_yuv420p_mp4(self):
        args = encode(self.cmd)
        self.assertEqual(opt(args, "-c:v"), "libx264")
        self.assertEqual(opt(args, "-crf"), "16")
        self.assertEqual(opt(args, "-preset"), "medium")
        self.assertEqual(opt(args, "-pix_fmt"), "yuv420p")
        self.assertIn("-an", args)
        self.assertNotIn("-c:a", args)
        self.assertNotIn("-vf", args)
        # The container is mp4 even for a .webm (VP9/AV1) pick: ffmpeg keeps the
        # last -f, and the remux names the file .mp4.
        self.assertEqual(args[len(args) - 1 - args[::-1].index("-f") + 1], "mp4")
        self.assertIn("+faststart", args)
        self.assertEqual(opt(self.cmd, "--remux-video"), "mp4")
        self.assertEqual(opt(self.cmd, "--merge-output-format"), "mp4")

    def test_frame_exact_cut_and_prints_kept(self):
        self.assertIn("--force-keyframes-at-cuts", self.cmd)
        self.assertEqual(opt(self.cmd, "--download-sections"), "*10.0-15.0")
        prints = [self.cmd[i + 1] for i, c in enumerate(self.cmd) if c == "--print"]
        self.assertIn("after_move:filepath", prints)
        self.assertIn("before_dl:DLINFO %(duration)s|%(format_id)s|%(vcodec)s|%(height)s|%(tbr)s", prints)

    def test_crf_follows_config(self):
        with mock.patch.multiple(config, DOWNLOAD_QUALITY="high", DOWNLOAD_CRF=19, DOWNLOAD_PRESET="fast; rm"):
            cmd = ytdlp._fetch_cmd("abcdefghijk", "out.%(ext)s", 10.0, 5.0)
        self.assertEqual(opt(encode(cmd), "-crf"), "19")
        self.assertEqual(opt(encode(cmd), "-preset"), "fastrm")  # letters only, never a second argument

    def test_vertical_first_keeps_any_codec(self):
        fmt = opt(build(vertical=True), "-f")
        self.assertTrue(fmt.startswith("bv*[aspect_ratio<1.2][width<=1080][dynamic_range=SDR][protocol^=https]/"))
        self.assertNotIn("[ext=mp4]", fmt)
        self.assertTrue(fmt.endswith(ytdlp._HIGH_VIDEO))

    def test_network_args_merge_with_the_proxy_downloader_args(self):
        # The proxy route adds its own --downloader-args under another key
        # (ffmpeg_i); yt-dlp keeps both keys.
        net = ytdlp._yt_network_args("http://u:p@proxy.example:8080")
        keys = [c.split(":", 1)[0] for c in (self.cmd + net)
                if c.startswith("ffmpeg_")]
        self.assertEqual(sorted(keys), ["ffmpeg_i", "ffmpeg_o"])


class HighAudioAndHero(unittest.TestCase):
    def test_audio_takes_best_audio_and_aac_192k(self):
        cmd = build(audio=True)
        fmt = opt(cmd, "-f")
        self.assertNotIn("[ext=mp4]", fmt)
        self.assertNotIn("[ext=m4a]", fmt)
        self.assertTrue(fmt.startswith("bv*[height<=1080][dynamic_range=SDR][protocol^=https]+ba[protocol^=https]/"))
        args = encode(cmd)
        self.assertEqual(opt(args, "-c:a"), "aac")
        self.assertEqual(opt(args, "-b:a"), "192k")
        self.assertNotIn("-an", args)
        self.assertNotIn("-vf", args)

    def test_hero_allows_over_1080_under_a_bitrate_cap(self):
        cmd = build(hero=True)
        fmt = opt(cmd, "-f")
        first = fmt.split("/")[0]
        self.assertIn("[height>1080]", first)
        self.assertIn("[height<=2160]", first)
        self.assertIn("[tbr<9000]", first)  # strict: an unknown bitrate is not taken
        self.assertIn("[dynamic_range=SDR]", first)
        self.assertIn("+ba", first)
        # Then the ordinary <=1080 picks with sound.
        self.assertTrue(fmt.endswith(ytdlp._HIGH_WITH_AUDIO))
        self.assertEqual(opt(cmd, "-S"), "res:1440,fps:30,hdr:sdr,vcodec")

    def test_hero_cap_follows_config(self):
        with mock.patch.multiple(config, DOWNLOAD_QUALITY="high", HERO_MAX_TBR=6000):
            cmd = ytdlp._fetch_cmd("abcdefghijk", "out.%(ext)s", 10.0, 5.0, hero=True)
        self.assertIn("[tbr<6000]", opt(cmd, "-f"))

    def test_hero_downscales_to_1080_lanczos_with_sound(self):
        args = encode(build(hero=True))
        vf = opt(args, "-vf")
        self.assertTrue(vf.startswith("scale="))
        self.assertIn("flags=lanczos", vf)
        self.assertIn("1080/min(iw,ih)", vf)
        self.assertEqual(opt(args, "-c:a"), "aac")
        self.assertEqual(opt(args, "-c:v"), "libx264")
        self.assertNotIn("-an", args)

    def test_hero_scale_expression_keeps_1080_and_even_sizes(self):
        # Evaluate the scale expressions the way ffmpeg does, for a few inputs.
        def size(iw, ih):
            m = min(iw, ih)
            k = min(1, 1080 / m)
            return int(iw * k / 2) * 2, int(ih * k / 2) * 2
        self.assertEqual(size(3840, 2160), (1920, 1080))
        self.assertEqual(size(2560, 1440), (1920, 1080))
        self.assertEqual(size(1920, 1080), (1920, 1080))
        self.assertEqual(size(1080, 1920), (1080, 1920))  # vertical keeps its width
        self.assertEqual(size(1440, 2560), (1080, 1920))


class Legacy(unittest.TestCase):
    def test_legacy_is_exactly_the_old_command(self):
        self.assertEqual(build("legacy"), LEGACY)

    def test_legacy_audio_is_the_old_format(self):
        cmd = build("legacy", audio=True)
        self.assertEqual(opt(cmd, "-f"), LEGACY_AUDIO_FORMAT)
        self.assertNotIn("--downloader-args", cmd)
        self.assertNotIn("--remux-video", cmd)

    def test_legacy_hero_is_the_old_audio_command_or_footage(self):
        # Legacy knows no hero: the caller's audio flag decides, as before.
        self.assertEqual(build("legacy", hero=True), LEGACY)
        self.assertEqual(opt(build("legacy", audio=True, hero=True), "-f"), LEGACY_AUDIO_FORMAT)

    def test_unknown_value_means_high(self):
        self.assertIn("--downloader-args", build("HIGH"))
        self.assertNotIn("--downloader-args", build(" Legacy "))


class NetworkBytes(unittest.TestCase):
    def test_dlinfo_reads_old_and_new_lines(self):
        self.assertEqual(ytdlp._dlinfo("DLINFO 14.0|137\n"), (14.0, "137"))
        self.assertEqual(ytdlp._dlinfo("DLINFO 255|399|av01.0.08M.08|1080|660.402\n/x.mp4"), (255.0, "399"))
        self.assertEqual(ytdlp._dlinfo("DLINFO NA|251+400|av01|1440|2440.1"), (0.0, "251+400"))
        self.assertEqual(ytdlp._dlstats("DLINFO 255|399|av01.0.08M.08|1080|660.402"),
                         {"vcodec": "av01.0.08M.08", "height": 1080.0, "tbr": 660.402})
        self.assertEqual(ytdlp._dlstats("DLINFO 14.0|137"), {})
        self.assertEqual(ytdlp._dlstats("DLINFO 14.0|137|NA|NA|NA"), {})

    def test_estimate_from_the_stream_bitrate_not_the_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 5_000_000)  # a big re-encoded file
        try:
            got = ytdlp.network_bytes("DLINFO 255|399|av01|1080|800", 10.0, f.name)
            self.assertEqual(got, int(800 * 1000 / 8 * (10.0 + ytdlp._PREROLL_S) * ytdlp._BUSY_FACTOR))
            # No bitrate (legacy line): the file's size, as before.
            self.assertEqual(ytdlp.network_bytes("DLINFO 14.0|137", 10.0, f.name), 5_000_000)
            self.assertEqual(ytdlp.network_bytes("", 10.0, ""), 0)
        finally:
            os.unlink(f.name)

    def test_a_download_records_the_network_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "yt_abcdefghijk.mp4")
            with open(path, "wb") as fh:
                fh.write(b"y" * 4_000_000)
            done = SimpleNamespace(returncode=0, stdout=f"DLINFO 300|399|av01|1080|1000\n{path}\n", stderr="")
            with mock.patch.object(ytdlp, "_video_unavailable", return_value=False), \
                    mock.patch.object(ytdlp, "stopped", return_value=False), \
                    mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                    mock.patch.object(ytdlp, "_release_proxy"), \
                    mock.patch.object(ytdlp, "playable_video", return_value=True), \
                    mock.patch.object(ytdlp.costs, "record") as record, \
                    mock.patch.object(ytdlp.subprocess, "run", return_value=done):
                got = ytdlp._yt_fetch("abcdefghijk", d, 10.0, 6.0)
            self.assertEqual(got, path)
            record.assert_any_call("proxy.bytes", int(1000 * 1000 / 8 * (6.0 + ytdlp._PREROLL_S) * ytdlp._BUSY_FACTOR))

    def test_hero_reaches_the_command_and_survives_a_refit(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:  # asked past the end of a 14 s video
                return SimpleNamespace(returncode=1, stdout="DLINFO 14.0|400+251|av01|1440|2400\n",
                                       stderr="ERROR: Numerical result out of range")
            return SimpleNamespace(returncode=1, stdout="", stderr="x")

        with mock.patch.object(config, "DOWNLOAD_QUALITY", "high"), \
                mock.patch.object(ytdlp, "_video_unavailable", return_value=False), \
                mock.patch.object(ytdlp, "stopped", return_value=False), \
                mock.patch.object(ytdlp, "_acquire_proxy", return_value=""), \
                mock.patch.object(ytdlp, "_release_proxy"), \
                mock.patch.object(ytdlp, "_note_failure", return_value=ytdlp.FailureClass.NETWORK_TIMEOUT), \
                mock.patch.object(ytdlp.subprocess, "run", side_effect=run), \
                tempfile.TemporaryDirectory() as d:
            ytdlp._yt_fetch("HEROVIDEO01", d, 13.5, 5.0, hero=True)
        self.assertEqual(len(calls), 2)
        for cmd in calls:
            self.assertIn("[height>1080]", opt(cmd, "-f"))
            self.assertIn("-vf", encode(cmd))


if __name__ == "__main__":
    unittest.main()
