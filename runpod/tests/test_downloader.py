"""Downloader runtime and failed-cache regressions; no live network."""
import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from src import media


class Downloader(unittest.TestCase):
    def test_runtime_and_network_limits_apply_to_search_and_fetch(self):
        result = SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(media.subprocess, 'run', return_value=result) as run:
            media._yt_candidates('ytsearch1:lake', False)
            media._yt_fetch('abc', '/tmp', 2, 3)
        def last(cmd, opt):   # yt-dlp keeps the last value of a repeated option
            return cmd[len(cmd) - 1 - cmd[::-1].index(opt) + 1]
        search, fetch = (c.args[0] for c in run.call_args_list[:2])
        for cmd in (search, fetch):
            self.assertEqual(last(cmd, '--js-runtimes'), 'node')
            self.assertIn('--ignore-config', cmd)
        self.assertEqual(last(search, '--retries'), '2')
        # A download through a flaky residential IP gets more tries.
        self.assertEqual(last(fetch, '--retries'), '5')

    def test_ffmpeg_gets_the_proxy_explicitly_for_https_streams(self):
        args = media._yt_network_args("http://u:p@proxy.example:8080")
        self.assertIn("--proxy", args)
        self.assertEqual(args[args.index("--downloader-args") + 1],
                         "ffmpeg_i:-http_proxy http://u:p@proxy.example:8080")
        self.assertNotIn("--downloader-args", media._yt_network_args(""))

    def test_failed_download_never_returns_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'yt_abc_2000_3000.mp4')
            with open(path, 'wb') as fh:
                fh.write(b'old incomplete output')
            result = SimpleNamespace(returncode=1, stdout=path, stderr='failed')
            with patch.object(media.subprocess, 'run', return_value=result):
                self.assertEqual(media._yt_fetch('abc', folder, 2, 3), '')

    def test_ranges_have_distinct_output_names(self):
        result = SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(media.subprocess, 'run', return_value=result) as run:
            media._yt_fetch('abc', '/tmp', 2, 3)
            media._yt_fetch('abc', '/tmp', 8, 3)
        names = [c.args[0][c.args[0].index('-o') + 1] for c in run.call_args_list]
        self.assertNotEqual(*names)
