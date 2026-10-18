"""
Picture download yield (docs/sourcing-yield-2026-10-18.md). The owner's three
renders of 2026-10-12/13 failed ~1,000 downloads; the picture classes were:
Yandex 404 216, Yandex "400 Use thumbnail sizes" 144, web "not a photo (svg)"
149, web 404 81 / 403 62 / proxy-side 48 / timeouts 22. Offline: no request
leaves the machine (storage.requests.get or imagefix.download are faked).
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import requests

from src import config, imagefix, media, storage
from src.storage import NotAPhoto, StorageError


def _jpeg(path: str) -> str:
    from PIL import Image
    Image.new("RGB", (64, 48), (120, 90, 60)).save(path, "JPEG")
    return path


def _http_error(code: int, reason: str = "") -> StorageError:
    """storage.download's error for an HTTP answer: the cause carries the response."""
    resp = requests.Response()
    resp.status_code = code
    resp.reason = reason
    try:
        raise requests.HTTPError(f"{code} Client Error: {reason}", response=resp)
    except requests.HTTPError as e:
        try:
            raise StorageError(f"download failed after 1 attempt(s): {e}") from e
        except StorageError as wrapped:
            return wrapped


class _Answer:
    """A streamed answer with a Content-Type and a small body."""

    def __init__(self, content_type: str, body: bytes = b"<svg xmlns='http://www.w3.org/2000/svg'/>"):
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.body = body
        self.read = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        self.read = True
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Clean(unittest.TestCase):
    def setUp(self):
        imagefix._HOST_FAILS.clear()
        self.work = tempfile.mkdtemp()

    def tearDown(self):
        imagefix._HOST_FAILS.clear()


class SvgIsNeverDownloaded(_Clean):
    def test_links_that_say_svg(self):
        for url in ("https://a.example/logo.svg", "https://a.example/LOGO.SVG?v=3", "https://a.example/m.svgz",
                    "https://cdn.example/img?id=4&format=svg", "https://cdn.example/img?fm=svg&w=800",
                    "https://a.example/flag%2Esvg", "data:image/svg+xml;base64,PHN2Zz4="):
            self.assertEqual(imagefix.not_a_photo_url(url), "svg", url)

    def test_photos_and_svg_renderings_are_photos(self):
        for url in ("https://upload.wikimedia.org/thumb/a/ab/Map.svg/1920px-Map.svg.png",
                    "https://a.example/photo.jpg", "https://a.example/svg-tutorial/photo.webp",
                    "https://a.example/img?format=jpg", "data:image/jpeg;base64,AAAA", ""):
            self.assertEqual(imagefix.not_a_photo_url(url), "", url)

    def test_fetch_refuses_an_svg_link_without_asking_the_site(self):
        with mock.patch.object(storage.requests, "get", side_effect=AssertionError("never asked")):
            with self.assertRaises(NotAPhoto) as got:
                imagefix.fetch("https://a.example/seal.svg", os.path.join(self.work, "s.jpg"))
        self.assertIn("not a photo (svg)", str(got.exception))
        self.assertFalse(imagefix.host_refused("https://a.example/other.jpg"))

    def test_the_flag_off_asks_as_before(self):
        with mock.patch.object(config, "PICTURE_SKIP_SVG", False), \
                mock.patch.object(imagefix, "_fetch_raw", side_effect=StorageError("x")) as raw:
            with self.assertRaises(StorageError):
                imagefix.fetch("https://a.example/seal.svg", os.path.join(self.work, "s.jpg"))
        raw.assert_called_once()

    def test_an_svg_answer_ends_at_the_headers_with_one_request(self):
        answer = _Answer("image/svg+xml; charset=utf-8")
        with mock.patch.object(storage.requests, "get", return_value=answer) as get:
            with self.assertRaises(NotAPhoto) as got:
                storage.download("https://a.example/pic", os.path.join(self.work, "p.jpg"),
                                 attempts=3, refuse_types=("image/svg+xml",))
        self.assertEqual(get.call_count, 1)
        self.assertFalse(answer.read)                          # no body read
        self.assertEqual(os.listdir(self.work), [])
        self.assertIn("not a photo (svg)", str(got.exception))

    def test_an_svg_answer_gets_no_browser_fingerprint_or_route_try(self):
        with mock.patch.object(storage.requests, "get", return_value=_Answer("image/svg+xml")) as get, \
                mock.patch.object(imagefix, "_curl_cffi_get") as cffi, \
                mock.patch.object(imagefix, "_residential_route", return_value="http://proxy.example:1"):
            with self.assertRaises(NotAPhoto):
                imagefix.fetch("https://a.example/pic?id=1", os.path.join(self.work, "p.jpg"),
                               alternates=["https://b.example/pic.jpg"])
        self.assertEqual(get.call_count, 1)
        cffi.assert_not_called()
        self.assertFalse(imagefix.host_refused("https://a.example/x.jpg"))

    def test_web_search_leaves_svg_results_out(self):
        rows = [("https://a.example/logo.svg", 3000, 2000, "logo", "https://a.example/", ""),
                ("https://a.example/photo.jpg", 3000, 2000, "photo", "https://a.example/", "")]
        no_search = mock.Mock(DDGS=mock.Mock(side_effect=AssertionError("no live search in tests")))
        with mock.patch.object(config, "SERPER_API_KEY", ""), \
                mock.patch.object(config, "SERPAPI_API_KEY", ""), \
                mock.patch.object(config, "PICTURE_SHARPNESS_CHECK", True), \
                mock.patch.dict("sys.modules", {"ddgs": no_search}), \
                mock.patch.object(media, "_sized_image_rows", return_value=rows):
            got = media.search_web_images("anything", limit=1)
        self.assertEqual([a.url for a in got], ["https://a.example/photo.jpg"])


# A Yandex results page laid out like the real one: each result's record in the
# page state, the original's link (origUrl), its size, Yandex's thumbnail, the
# page it is on and its duplicates on other sites.
_ITEM = {
    "id": "a1", "origUrl": "https://news.example.com/2026/flood.jpg", "origWidth": 2400, "origHeight": 1350,
    "image": "//avatars.mds.yandex.net/i?id=abc123-images-thumbs&n=13",
    "snippet": {"title": "Flood {live}", "url": "https://news.example.com/2026/flood-story"},
    "viewerData": {"dups": [
        {"url": "https://small.example.org/flood_s.jpg", "w": 640, "h": 360},
        {"url": "https://mirror.example.net/flood.jpg", "w": 2400, "h": 1350},
        {"url": "https://www.alamy.com/comp/flood.jpg", "w": 2400, "h": 1350},
    ]},
}
_ITEM2 = {"id": "b2", "origUrl": "https://avatars.mds.yandex.net/get-images-cbir/1234/AbCd", "origWidth": 1920,
          "origHeight": 1080}
_C = {"separators": (",", ":")}           # compact, as the page sends it
_PAGE = ('<html><script>window.__STATE__ = {"serp":{"items":[' + json.dumps(_ITEM, **_C) + "," + json.dumps(_ITEM2, **_C)
         + ']}};</script><a href="/images/search?img_url=https%3A%2F%2Fother.example%2Fx.jpg&pos=3">x</a></html>')


class YandexResults(_Clean):
    def test_each_results_record_is_read(self):
        got = media._yandex_details(_PAGE)
        rec = got["https://news.example.com/2026/flood.jpg"]
        self.assertEqual((rec["w"], rec["h"]), (2400, 1350))
        self.assertEqual(rec["page"], "https://news.example.com/2026/flood-story")
        self.assertEqual(rec["thumb"], "https://avatars.mds.yandex.net/i?id=abc123-images-thumbs&n=13")
        # Biggest duplicate first; the small one after it.
        self.assertEqual(rec["alts"][0], "https://mirror.example.net/flood.jpg")
        self.assertIn("https://small.example.org/flood_s.jpg", rec["alts"])

    def test_an_unreadable_page_gives_nothing_and_never_raises(self):
        self.assertEqual(media._yandex_details('{"origUrl":"https://x.example/a.jpg", broken'), {})
        self.assertEqual(media._yandex_details(""), {})

    def test_search_carries_size_page_thumbnail_and_duplicates(self):
        resp = mock.Mock(text=_PAGE, url="https://yandex.com/images/search?text=x")
        with mock.patch.object(media.requests, "get", return_value=resp), \
                mock.patch.object(media, "_next_proxy", return_value=""):
            got = media.search_yandex_images("flood", limit=8)
        by = {a.url: a for a in got}
        a = by["https://news.example.com/2026/flood.jpg"]
        self.assertEqual((a.width, a.height), (2400, 1350))
        self.assertEqual(a.page_url, "https://news.example.com/2026/flood-story")
        self.assertTrue(a.thumbnail.startswith("https://avatars.mds.yandex.net/i?id="))
        self.assertEqual(a.alt_urls[0], "https://mirror.example.net/flood.jpg")
        self.assertFalse(any("alamy" in u for u in a.alt_urls))        # a stock agency's copy never
        # A Yandex-hosted original without its size gets one.
        self.assertIn("https://avatars.mds.yandex.net/get-images-cbir/1234/AbCd/orig", by)
        self.assertIn("https://other.example/x.jpg", by)                # img_url links still used

    def test_the_flag_off_keeps_links_only(self):
        resp = mock.Mock(text=_PAGE, url="https://yandex.com/images/search?text=x")
        with mock.patch.object(config, "YANDEX_RESULT_DETAILS", False), \
                mock.patch.object(media.requests, "get", return_value=resp), \
                mock.patch.object(media, "_next_proxy", return_value=""):
            got = media.search_yandex_images("flood", limit=8)
        self.assertTrue(all(not a.alt_urls and not a.page_url for a in got))
        self.assertIn("https://avatars.mds.yandex.net/get-images-cbir/1234/AbCd", {a.url for a in got})


class YandexSizes(_Clean):
    def test_a_link_without_a_size_gets_one(self):
        self.assertEqual(imagefix.yandex_sized("https://avatars.mds.yandex.net/get-images-cbir/1/AbC"),
                         "https://avatars.mds.yandex.net/get-images-cbir/1/AbC/orig")
        self.assertEqual(imagefix.yandex_sized("https://avatars.mds.yandex.net/i?id=abc-images-thumbs"),
                         "https://avatars.mds.yandex.net/i?id=abc-images-thumbs&n=13")
        for same in ("https://avatars.mds.yandex.net/get-zen_doc/1/pub_x/scale_1200",
                     "https://avatars.mds.yandex.net/i?id=abc&n=33", "https://news.example.com/get-x/1/2"):
            self.assertEqual(imagefix.yandex_sized(same), same)

    def test_size_variants_after_a_400(self):
        self.assertEqual(imagefix.yandex_size_variants(
            "https://avatars.mds.yandex.net/get-zen_doc/1/pub_x/smart_crop_516x290"),
            ["https://avatars.mds.yandex.net/get-zen_doc/1/pub_x/orig"])
        self.assertEqual(imagefix.yandex_size_variants("https://avatars.mds.yandex.net/get-a/1/b/orig"), [])
        self.assertEqual(imagefix.yandex_size_variants("https://news.example.com/a.jpg"), [])

    def test_a_400_for_its_size_is_fetched_again_at_the_original_size(self):
        url = "https://avatars.mds.yandex.net/get-zen_doc/1/pub_x/smart_crop_516x290"
        asked = []

        def fake(u, dest, timeout=180, headers=None, proxy="", attempts=3, **kw):
            asked.append((u, bool(headers), proxy))
            if u.endswith("/orig"):
                return _jpeg(dest)
            raise _http_error(400, "Use thumbnail sizes like 'orig'")
        with mock.patch.object(imagefix, "download", side_effect=fake), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=AssertionError("not for a 400")), \
                mock.patch.object(imagefix, "_residential_route", return_value="http://proxy.example:1"):
            out = imagefix.fetch(url, os.path.join(self.work, "y.jpg"))
        self.assertTrue(os.path.isfile(out))
        self.assertEqual([a[0] for a in asked], [url, url, url.rsplit("/", 1)[0] + "/orig"])
        self.assertFalse(any(a[2] for a in asked))                     # no residential try for a 400
        self.assertFalse(imagefix.host_refused(url))                   # the host is not "refusing"
        imagefix._note_refusal(url, "400 Client Error")
        imagefix._note_refusal(url, "400 Client Error")
        self.assertFalse(imagefix.host_refused(url))


class OtherCopies(_Clean):
    def _fetch(self, gone_hosts, alternates, **flags):
        asked = []

        def fake(u, dest, timeout=180, headers=None, proxy="", attempts=3, **kw):
            asked.append(u)
            if any(h in u for h in gone_hosts):
                raise _http_error(404, "Not Found")
            return _jpeg(dest)
        with mock.patch.multiple(config, **flags) if flags else mock.patch.object(config, "PICTURE_ALTERNATES", True), \
                mock.patch.object(imagefix, "download", side_effect=fake), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=AssertionError("not for a 404")), \
                mock.patch.object(imagefix, "_residential_route", return_value="http://proxy.example:1"):
            try:
                return imagefix.fetch("https://gone.example/a.jpg", os.path.join(self.work, "a.jpg"),
                                      alternates=alternates), asked
            except StorageError as e:
                return e, asked

    def test_a_404_original_comes_from_its_duplicate(self):
        out, asked = self._fetch(["gone.example"], ["https://mirror.example.net/a.jpg"])
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(asked, ["https://gone.example/a.jpg", "https://gone.example/a.jpg",
                                 "https://mirror.example.net/a.jpg"])

    def test_at_most_the_configured_copies_are_asked_and_gone_ones_once(self):
        alts = [f"https://gone.example{n}.org/a.jpg" for n in range(5)]
        out, asked = self._fetch(["gone.example"], alts, PICTURE_ALTERNATES=True, PICTURE_ALTERNATES_MAX=2)
        self.assertIsInstance(out, StorageError)
        self.assertEqual(asked[2:], alts[:2])                          # one ask each: a 404 is final there too

    def test_no_copies_without_the_flag(self):
        out, asked = self._fetch(["gone.example"], ["https://mirror.example.net/a.jpg"], PICTURE_ALTERNATES=False)
        self.assertIsInstance(out, StorageError)
        self.assertEqual(len(asked), 2)

    def test_a_skipped_site_still_gets_its_copies(self):
        for _ in range(imagefix.HOST_FAILS_MAX):
            imagefix._note_refusal("https://gone.example/x.jpg", "403 Client Error")
        out, asked = self._fetch([], ["https://mirror.example.net/a.jpg"])
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(asked, ["https://mirror.example.net/a.jpg"])


class SecondRoute(_Clean):
    """The residential try fails on the route itself: once more through a different route."""

    def _run(self, route_error):
        asked = []

        def fake(u, dest, timeout=180, headers=None, proxy="", attempts=3, **kw):
            asked.append(proxy)
            if not proxy:
                raise _http_error(403, "Forbidden")                  # the datacenter address refused
            if proxy == "http://p1.example:1":
                raise route_error
            return _jpeg(dest)
        with mock.patch.object(config, "IMAGE_PROXIES", ["http://p1.example:1", "http://p2.example:2"]), \
                mock.patch.object(imagefix, "_ROUTE_TURN", [0]), \
                mock.patch.object(imagefix, "download", side_effect=fake), \
                mock.patch.object(imagefix, "_og_image", return_value=""), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=RuntimeError("HTTP 403")):
            try:
                return imagefix._fetch_raw("https://news.example.com/a.jpg", os.path.join(self.work, "a.jpg"), ""), \
                    [p for p in asked if p]
            except StorageError as e:
                return e, [p for p in asked if p]

    def _wrapped(self, cause: Exception) -> StorageError:
        try:
            raise StorageError(f"download failed after 1 attempt(s): {cause}") from cause
        except StorageError as e:
            return e

    def test_a_proxy_error_or_timeout_gets_another_route(self):
        for err in (self._wrapped(requests.exceptions.ProxyError("Unable to connect to proxy")),
                    self._wrapped(requests.exceptions.ReadTimeout("Read timed out")),
                    self._wrapped(StorageError("download returned an HTML error page (200)")),
                    _http_error(422, "Unprocessable Entity"), _http_error(502, "Bad Gateway")):
            out, routes = self._run(err)
            self.assertTrue(os.path.isfile(out), str(err))
            self.assertEqual(routes, ["http://p1.example:1", "http://p2.example:2"])

    def test_the_origins_own_answer_through_a_home_address_is_final(self):
        for code in (400, 403, 404, 410, 429):
            out, routes = self._run(_http_error(code))
            self.assertIsInstance(out, StorageError, code)
            self.assertEqual(routes, ["http://p1.example:1"], code)

    def test_one_route_only_and_the_flag(self):
        err = self._wrapped(requests.exceptions.ProxyError("Unable to connect to proxy"))
        with mock.patch.object(config, "PICTURE_SECOND_ROUTE", False):
            out, routes = self._run(err)
        self.assertEqual(routes, ["http://p1.example:1"])
        self.assertEqual(imagefix._other_route.__name__, "_other_route")
        with mock.patch.object(config, "IMAGE_PROXIES", ["http://p1.example:1"]):
            self.assertEqual(imagefix._other_route("http://p1.example:1"), "")


class BadRequestIsFinal(_Clean):
    def test_a_400_for_the_plain_and_the_browser_ask_is_final(self):
        asked = []

        def fake(u, dest, timeout=180, headers=None, proxy="", attempts=3, **kw):
            asked.append("route" if proxy else "browser" if headers else "plain")
            raise _http_error(400, "Bad Request")
        with mock.patch.object(imagefix, "download", side_effect=fake), \
                mock.patch.object(imagefix, "_og_image", return_value=""), \
                mock.patch.object(imagefix, "_residential_route", return_value="http://proxy.example:1"), \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=RuntimeError("HTTP 400")) as cffi:
            with self.assertRaises(StorageError):
                imagefix._fetch_raw("https://cdn.example.com/bad", os.path.join(self.work, "p.jpg"), "")
            self.assertEqual(asked, ["plain", "browser"])
            self.assertEqual(cffi.call_count, 0)
            asked.clear()
            with mock.patch.object(config, "PICTURE_BAD_REQUEST_FINAL", False):
                with self.assertRaises(StorageError):
                    imagefix._fetch_raw("https://cdn.example.com/bad", os.path.join(self.work, "p.jpg"), "")
            self.assertEqual(asked, ["plain", "browser", "route"])     # as before


class MediaPassesTheCopies(unittest.TestCase):
    def test_download_hands_the_duplicates_to_the_fetcher(self):
        asset = media.MediaAsset(kind="image", source="yandex_image", url="https://x.example/a.jpg",
                                 alt_urls=["https://y.example/a.jpg"])
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(media._imagefix, "fetch", return_value=os.path.join(d, "a.jpg")) as f:
            media._download(asset, "q", d)
        self.assertEqual(f.call_args.kwargs["alternates"], ["https://y.example/a.jpg"])


if __name__ == "__main__":
    unittest.main()
