"""Cloudflare R2 for finished videos (src/r2.py)."""
import datetime
import os
import tempfile
import unittest
from unittest import mock

from src import config, r2


class R2Test(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(config, R2_ACCOUNT_ID="acct123", R2_ACCESS_KEY_ID="AKID",
                                     R2_SECRET_ACCESS_KEY="secret", R2_BUCKET="videos",
                                     R2_PUBLIC_BASE="https://pub-x.r2.dev/")
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_enabled_only_when_fully_configured(self):
        self.assertTrue(r2.enabled())
        with mock.patch.object(config, "R2_PUBLIC_BASE", ""):
            self.assertFalse(r2.enabled())

    def test_signature_is_stable_and_scoped(self):
        when = datetime.datetime(2026, 9, 29, 12, 0, 0, tzinfo=datetime.timezone.utc)
        a = r2._auth_headers("PUT", "projects/p/final.mp4", {"content-type": "video/mp4"}, "UNSIGNED-PAYLOAD", when)
        b = r2._auth_headers("PUT", "projects/p/final.mp4", {"content-type": "video/mp4"}, "UNSIGNED-PAYLOAD", when)
        self.assertEqual(a, b)
        self.assertIn("Credential=AKID/20260929/auto/s3/aws4_request", a["Authorization"])
        self.assertIn("SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date", a["Authorization"])
        self.assertEqual(a["x-amz-date"], "20260929T120000Z")
        c = r2._auth_headers("PUT", "projects/p/other.mp4", {"content-type": "video/mp4"}, "UNSIGNED-PAYLOAD", when)
        self.assertNotEqual(a["Authorization"], c["Authorization"])

    def test_upload_retries_a_server_error_then_returns_the_public_url(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x" * 1000)
            bad, good = mock.Mock(status_code=503, text="busy"), mock.Mock(status_code=200, text="")
            with mock.patch.object(r2.requests, "put", side_effect=[bad, good]) as put, \
                    mock.patch.object(r2.time, "sleep"):
                url = r2.upload(p, "projects/p/final 1.mp4")
        self.assertEqual(url, "https://pub-x.r2.dev/projects/p/final%201.mp4")
        self.assertEqual(put.call_count, 2)
        self.assertTrue(put.call_args.args[0].startswith("https://acct123.r2.cloudflarestorage.com/videos/"))

    def test_a_refusal_is_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.mp4")
            open(p, "wb").write(b"x")
            with mock.patch.object(r2.requests, "put", return_value=mock.Mock(status_code=403, text="denied")) as put:
                with self.assertRaises(RuntimeError):
                    r2.upload(p, "k.mp4")
        self.assertEqual(put.call_count, 1)


if __name__ == "__main__":
    unittest.main()
