"""
Pictures for scenes the footage search could not fill (the Mount Rainier video,
2026-10-02: 166 picture downloads failed - sites answering 403 or an HTML page,
one news site timing out three tries at a time - and 97 scenes were left with
no picture). A site that refused twice is not asked again for a while; the
ladder's picture rung tries more pictures and a second search wording.
"""
import os
import tempfile
import time
import unittest
from unittest import mock

import requests

from src import gapfill, imagefix, storage, ytdlp
from src.storage import StorageError


class SitesThatRefuse(unittest.TestCase):
    def setUp(self):
        imagefix._HOST_FAILS.clear()

    def tearDown(self):
        imagefix._HOST_FAILS.clear()

    def test_two_refusals_and_the_site_is_skipped(self):
        url = "https://www.thenewstribune.com/a.jpg"
        self.assertFalse(imagefix.host_refused(url))
        imagefix._note_refusal(url, "403 Client Error: Forbidden")
        self.assertFalse(imagefix.host_refused(url))
        imagefix._note_refusal("https://www.thenewstribune.com/b.jpg", "download returned an HTML error page")
        self.assertTrue(imagefix.host_refused("https://www.thenewstribune.com/c.jpg"))
        self.assertFalse(imagefix.host_refused("https://other.example.com/c.jpg"))

    def test_a_missing_picture_is_not_a_refusal(self):
        url = "https://cdn.example.com/gone.jpg"
        for _ in range(3):
            imagefix._note_refusal(url, "404 Client Error: Not Found")
        self.assertFalse(imagefix.host_refused(url))

    def test_wikimedia_is_never_skipped(self):
        url = "https://upload.wikimedia.org/x.jpg"
        for _ in range(3):
            imagefix._note_refusal(url, "429 Too Many Requests")
        self.assertFalse(imagefix.host_refused(url))

    def test_the_site_is_asked_again_later(self):
        url = "https://slow.example.com/a.jpg"
        imagefix._HOST_FAILS["slow.example.com"] = (2, time.time() - imagefix.HOST_FAILS_SECONDS - 1)
        self.assertFalse(imagefix.host_refused(url))

    def test_fetch_counts_a_failed_download_and_then_refuses_at_once(self):
        url = "https://refuser.example.com/p.jpg"
        with mock.patch.object(imagefix, "_fetch_raw", side_effect=StorageError("403 Client Error: Forbidden")) as raw:
            for _ in range(2):
                with self.assertRaises(StorageError):
                    imagefix.fetch(url, "C:/nonexistent/p.jpg")
            with self.assertRaises(StorageError):
                imagefix.fetch(url, "C:/nonexistent/p.jpg")
        self.assertEqual(raw.call_count, 2)          # the third never reached the site

    def test_a_rate_limit_is_not_a_refusal(self):
        # 2026-10-04: Flickr answered 429 twice and seven good pictures on it were skipped for 30 minutes.
        url = "https://live.staticflickr.com/65535/a_b.jpg"
        for _ in range(3):
            imagefix._note_refusal(url, "download failed after 1 attempt(s): 429 Client Error: Too Many Requests")
        self.assertFalse(imagefix.host_refused(url))

    def test_a_download_cut_by_the_scenes_own_stop_is_not_a_refusal(self):
        url = "https://news.example.com/a.jpg"
        for _ in range(3):
            imagefix._note_refusal(url, f"picture download failed: {storage.STOPPED}: the time for it is up")
        self.assertFalse(imagefix.host_refused(url))


class SharedHosts(unittest.TestCase):
    """A host serving many sites' or people's pictures: refusals count against one site's part of it."""

    def setUp(self):
        imagefix._HOST_FAILS.clear()

    def tearDown(self):
        imagefix._HOST_FAILS.clear()

    def _refuse(self, *urls):
        for u in urls:
            imagefix._note_refusal(u, "download failed after 1 attempt(s): 403 Client Error: Forbidden")

    def test_two_refusals_for_one_wordpress_site_leave_the_others_on_jetpack_alone(self):
        self._refuse("https://i0.wp.com/www.site-a.com/wp-content/a.jpg",
                     "https://i0.wp.com/www.site-a.com/wp-content/b.jpg")
        self.assertTrue(imagefix.host_refused("https://i0.wp.com/www.site-a.com/wp-content/c.jpg"))
        self.assertFalse(imagefix.host_refused("https://i0.wp.com/www.site-b.com/wp-content/c.jpg"))

    def test_on_pinterest_or_flickr_each_picture_is_its_own(self):
        pin = "https://i.pinimg.com/originals/fe/b3/a5/feb3a511b2338c4e.jpg"
        self._refuse(pin, pin)
        self.assertTrue(imagefix.host_refused(pin))
        self.assertFalse(imagefix.host_refused("https://i.pinimg.com/originals/aa/bb/cc/other.jpg"))
        flickr = "https://farm66.staticflickr.com/65535/53879128333_a4f6c98be9_o.jpg"   # by the family's name
        self._refuse(flickr, flickr)
        self.assertTrue(imagefix.host_refused(flickr))
        self.assertFalse(imagefix.host_refused("https://farm66.staticflickr.com/65535/1_2_o.jpg"))

    def test_a_squarespace_site_is_its_content_id(self):
        self._refuse("https://images.squarespace-cdn.com/content/v1/5a1b2c/1.jpg",
                     "https://images.squarespace-cdn.com/content/v1/5a1b2c/2.jpg")
        self.assertTrue(imagefix.host_refused("https://images.squarespace-cdn.com/content/v1/5a1b2c/3.jpg"))
        self.assertFalse(imagefix.host_refused("https://images.squarespace-cdn.com/content/v1/9z8y7x/3.jpg"))

    def test_a_shared_host_refusing_every_part_is_skipped_as_a_whole(self):
        for n in range(imagefix.SHARED_FAILS_MAX - 1):
            self._refuse(f"https://i.pinimg.com/originals/{n:02d}/x/y/p.jpg")
        self.assertFalse(imagefix.host_refused("https://i.pinimg.com/originals/zz/x/y/new.jpg"))
        self._refuse("https://i.pinimg.com/originals/99/x/y/p.jpg")
        self.assertTrue(imagefix.host_refused("https://i.pinimg.com/originals/zz/x/y/new.jpg"))

    def test_an_ordinary_site_is_still_one_host(self):
        self._refuse("https://www.nps.gov/articles/a.jpg", "https://www.nps.gov/media/b.jpg")
        self.assertTrue(imagefix.host_refused("https://www.nps.gov/images/c.jpg"))

    def test_a_shared_hosts_part_is_asked_again_later(self):
        url = "https://i0.wp.com/www.site-a.com/a.jpg"
        self._refuse(url, url)
        for key in list(imagefix._HOST_FAILS):
            n, _t = imagefix._HOST_FAILS[key]
            imagefix._HOST_FAILS[key] = (n, time.time() - imagefix.HOST_FAILS_SECONDS - 1)
        self.assertFalse(imagefix.host_refused(url))


class TriesThatCanStillHelp(unittest.TestCase):
    """imagefix._fetch_raw: each try only while it can still change the answer (measured 2026-10-04)."""

    def setUp(self):
        imagefix._HOST_FAILS.clear()
        self.work = tempfile.mkdtemp()
        self.calls = []

    def tearDown(self):
        imagefix._HOST_FAILS.clear()

    def _answer(self, code: int):
        """storage.download as it fails on an HTTP answer: its cause carries the response."""
        def fake(url, dest, timeout=180, headers=None, proxy="", attempts=3, **bounds):
            self.calls.append(("route" if proxy else "browser" if headers else "plain", bounds))
            try:
                raise requests.HTTPError(f"{code} Client Error", response=_resp(code))
            except requests.HTTPError as e:
                raise StorageError(f"download failed after 1 attempt(s): {e}") from e
        return fake

    def _fetch(self, code: int, route: str = "http://proxy.example:1"):
        with mock.patch.object(imagefix, "download", side_effect=self._answer(code)), \
                mock.patch.object(imagefix, "_residential_route", return_value=route), \
                mock.patch.object(imagefix, "_og_image", return_value=""), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=RuntimeError(f"HTTP {code}")) as cffi:
            with self.assertRaises(StorageError):
                imagefix._fetch_raw("https://cdn.example.com/gone.jpg", os.path.join(self.work, "p.jpg"), "")
        return [c[0] for c in self.calls], cffi.call_count

    def test_a_picture_gone_for_the_plain_and_the_browser_ask_is_final(self):
        tries, cffi = self._fetch(404)
        self.assertEqual(tries, ["plain", "browser"])                # no route, no Chrome fingerprint
        self.assertEqual(cffi, 0)

    def test_a_refusal_still_gets_every_try(self):
        tries, cffi = self._fetch(403)
        self.assertEqual(tries, ["plain", "browser", "route"])
        self.assertEqual(cffi, 1)

    def test_every_try_is_bounded_and_hears_the_scenes_stop(self):
        self._fetch(403)
        for _name, bounds in self.calls:
            self.assertGreater(bounds["max_seconds"], 0)
            self.assertLessEqual(bounds["connect_timeout"], 20)
            self.assertTrue(callable(bounds["stop"]))

    def test_no_try_once_the_scenes_time_is_up(self):
        token = ytdlp.STOP.set((None, time.time() - 1))
        try:
            with mock.patch.object(imagefix, "_residential_route", return_value="http://proxy.example:1"), \
                    mock.patch.object(imagefix, "_curl_cffi_get") as cffi, \
                    mock.patch.object(storage.requests, "get", side_effect=AssertionError("never asked")):
                with self.assertRaises(StorageError) as got:
                    imagefix.fetch("https://news.example.com/late.jpg", os.path.join(self.work, "late.jpg"))
        finally:
            ytdlp.STOP.reset(token)
        self.assertIn(storage.STOPPED, str(got.exception))
        cffi.assert_not_called()
        self.assertFalse(imagefix.host_refused("https://news.example.com/other.jpg"))
        imagefix._note_refusal("https://news.example.com/x.jpg", "403")
        self.assertFalse(imagefix.host_refused("https://news.example.com/other.jpg"))   # the stop never counted


def _resp(code: int) -> requests.Response:
    r = requests.Response()
    r.status_code = code
    return r


class _Slow:
    """A streamed answer that sends a small chunk every `gap` seconds, forever (a trickling host)."""

    def __init__(self, gap: float):
        self.gap = gap
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg"}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        while True:
            time.sleep(self.gap)
            yield b"\xff" * 512

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BoundedDownloads(unittest.TestCase):
    def test_a_trickling_host_is_cut_at_the_transfer_cap_and_not_asked_again(self):
        asked = []

        def get(*a, **kw):
            asked.append(kw.get("timeout"))
            return _Slow(0.02)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(storage.requests, "get", side_effect=get):
            t0 = time.time()
            with self.assertRaises(StorageError) as got:
                storage.download("https://slow.example.com/a.jpg", os.path.join(d, "a.jpg"), timeout=20,
                                 attempts=3, connect_timeout=7, max_seconds=0.3)
            self.assertLess(time.time() - t0, 3.0)
            self.assertEqual(os.listdir(d), [])                       # no partial file left
        self.assertIn("longer than", str(got.exception))
        self.assertEqual(asked, [(7, 20)])                            # one try: retrying cannot help

    def test_the_callers_stop_ends_a_transfer_in_flight(self):
        stop_at = time.time() + 0.2
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(storage.requests, "get", side_effect=lambda *a, **kw: _Slow(0.02)):
            with self.assertRaises(StorageError) as got:
                storage.download("https://slow.example.com/a.jpg", os.path.join(d, "a.jpg"),
                                 stop=lambda: time.time() > stop_at)
        self.assertIn(storage.STOPPED, str(got.exception))

    def test_without_bounds_a_download_is_unchanged(self):
        class _Done(_Slow):
            def iter_content(self, chunk_size=1):
                self.size = chunk_size
                yield b"\xff\xd8\xff" + b"x" * 100
        answer = _Done(0)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(storage.requests, "get", side_effect=lambda *a, **kw: answer) as get:
            out = storage.download("https://x.example.com/a.jpg", os.path.join(d, "a.jpg"))
            self.assertTrue(os.path.isfile(out))
        self.assertEqual(get.call_args.kwargs["timeout"], (20, 180))
        self.assertEqual(answer.size, 1 << 20)


class TheLadderPictureRung(unittest.TestCase):
    def test_a_second_search_wording_when_the_first_finds_nothing(self):
        job = {"index": 3, "query": "Nisqually Glacier dust cloud aerial", "start": 10.0, "subject": "Mount Rainier"}
        asked = []

        def still_for(job_, i, query, intent, used, work, stop, *mods):
            asked.append(query)
            return "picture" if query == "Nisqually Glacier dust cloud aerial" else None

        with mock.patch.object(gapfill, "_still_for", side_effect=still_for), \
                mock.patch.object(gapfill, "_names", return_value=["Mount Rainier"]):
            got = gapfill._from_still(job, gapfill.Used(), "C:/tmp", time.time() + 60, allow_generated=False)
        self.assertEqual(got, "picture")
        self.assertEqual(asked, ["Mount Rainier", "Nisqually Glacier dust cloud aerial"])

    def test_more_pictures_are_tried_per_search(self):
        self.assertGreaterEqual(gapfill.STILL_TRIES, 10)


if __name__ == "__main__":
    unittest.main()
