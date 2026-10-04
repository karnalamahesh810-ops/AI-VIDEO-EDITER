"""
Stock-agency and watermarked pictures never reach a timeline (src/stockblock.py;
the owner, 2026-10-04: "the images it is using are sometimes watermarked
images, like Getty ... Alamy ... fix that"). The names are checked before any
download on every path a picture takes; every downloaded picture's pixels are
read for an agency's credit bar (always) and stamp (on a picture about to be
kept), judged by the vision model or not; the job counts what it kept out.
"""
import dataclasses
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import handler
from src import config, fanout, gapfill, imagefix, library, libstore, localvision, media, quality, stockblock
from src.media import MediaAsset
from src.storage import StorageError

ALAMY = "https://c8.alamy.com/comp/2J7W6N8/cracked-earth-lake-mead-2J7W6N8.jpg"
GETTY = "https://media.gettyimages.com/id/75857578/photo/drought.jpg?s=1024x1024&w=gi&k=20"
PLAIN = "https://www.nps.gov/lake/learn/news/images/boulder-beach.jpg"


def photo(url, **kw):
    return MediaAsset(kind="image", source="web_image", url=url, **kw)


def picture(path, w=1300, h=900, bar=None, letterbox=False, frame=False, colour=(120, 150, 90)):
    """A test picture: a textured photo; `bar` = (height share, text) draws an agency credit bar under it."""
    im = Image.new("RGB", (w, h), colour)
    d = ImageDraw.Draw(im)
    for k in range(0, w, 37):                        # texture, so the picture is not one flat colour
        d.line([(k, 0), (k + 60, h)], fill=(colour[0] + 40, colour[1] - 30, colour[2] + 20), width=9)
    if bar:
        share, text = bar
        top = int(h * (1 - share))
        d.rectangle([0, top, w, h], fill=(1, 1, 1))
        d.text((12, top + 6), text, fill=(250, 250, 250))
        d.text((w - 240, top + 6), "Image ID: 2J7W6N8   www.alamy.com", fill=(250, 250, 250))
    if letterbox:
        d.rectangle([0, 0, w, int(h * 0.08)], fill=(1, 1, 1))
        d.rectangle([0, int(h * 0.92), w, h], fill=(1, 1, 1))
        d.text((w // 2 - 80, int(h * 0.94)), "another creator's subtitle line", fill=(250, 250, 250))
    if frame:
        d.rectangle([0, 0, w, h], outline=(255, 255, 255), width=int(h * 0.06))
        d.text((int(w * 0.1), int(h * 0.955)), "Hoover Dam, 1935 - a caption on the mount", fill=(20, 20, 20))
    im.save(path, "JPEG", quality=90)
    return path


def scaled_copy(src, dest, w):
    """The same picture at another size (the search engine's small copy, a bigger preview): its text scales too."""
    with Image.open(src) as im:
        im.convert("RGB").resize((w, round(im.size[1] * w / im.size[0])), Image.LANCZOS).save(dest, "JPEG", quality=88)
    return dest


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


class Names(unittest.TestCase):
    def test_agency_hosts_pages_thumbnails_and_nested_links(self):
        self.assertEqual(stockblock.reason(ALAMY), "a stock-agency picture (alamy)")
        self.assertEqual(stockblock.agency(GETTY), "getty")
        for url, agency in (("https://www.gettyimages.co.uk/detail/news-photo/x", "getty"),
                            ("https://editorial01.shutterstock.com/wm-preview-1500/x.jpg", "shutterstock"),
                            ("https://ak1.picdn.net/shutterstock/videos/4241831/thumb/1.jpg", "shutterstock"),
                            ("https://media.istockphoto.com/id/1711645203/photo/x.jpg", "istock"),
                            ("https://thumbs.dreamstime.com/b/x-176717925.jpg", "dreamstime"),
                            ("https://st2.depositphotos.com/1234/5678/i/950/depositphotos_56781234-stock-photo.jpg",
                             "depositphotos"), ("https://previews.123rf.com/images/x.jpg", "123rf"),
                            ("https://t3.ftcdn.net/jpg/01/23/45/67/360_F_123456789_abc.jpg", "adobe stock"),
                            ("https://stock.adobe.com/images/x/123", "adobe stock"),
                            ("https://www.alamyimages.fr/photo-image-x.html", "alamy"),
                            ("https://img.freepik.com/premium-photo/x.jpg", "freepik"),
                            ("https://static.vecteezy.com/system/resources/previews/x.jpg", "vecteezy"),
                            ("https://www.agefotostock.com/age/en/details-photo/x", "agefotostock"),
                            ("https://www.bigstockphoto.com/image-1/stock-photo-x", "bigstock"),
                            ("https://www.naturepl.com/stock-photo-x.html", "nature picture library")):
            self.assertEqual(stockblock.agency(url), agency, url)
        # the page, the search engine's small copy, a link carried in the query
        self.assertEqual(stockblock.agency("https://i.pinimg.com/736x/a.jpg", page_url="https://www.alamy.com/x.html"),
                         "alamy")
        self.assertEqual(stockblock.agency("https://cdn.example.com/a.jpg", thumbnail="https://c7.alamy.com/zooms/x.jpg"),
                         "alamy")
        self.assertEqual(stockblock.agency("https://www.alamy.com/aggregator-api/download?url=https://c8.alamy.com/comp/x.jpg"),
                         "alamy")
        self.assertEqual(stockblock.agency("https://x.example/y.jpg?src=https%3A%2F%2Fmedia.gettyimages.com%2Fa.jpg"),
                         "getty")

    def test_a_site_whose_name_only_starts_with_an_agencys_is_not_one(self):
        for url in ("https://natureplanet.org/a.jpg", "https://www.pond5ish.example/a.jpg",
                    "https://alamyfan.example/a.jpg", "https://eyeemphasis.com/a.jpg", "https://salamy.example/a.jpg"):
            self.assertEqual(stockblock.agency(url), "", url)

    def test_an_agencys_file_name_on_another_site(self):
        for url in ("https://grist.org/wp-content/uploads/2022/03/GettyImages-1325430438-1.jpg",
                    "https://res.cloudinary.com/aenetworks/image/upload/v1/gettyimages-640472731?_a=B",
                    "https://assets.newsweek.com/wp-content/uploads/2026/05/GettyImages-2272156228.jpg?w=1600",
                    "https://platform.vox.com/x/GettyImages_1486098182__1_.jpg?quality=90"):
            self.assertEqual(stockblock.agency(url), "getty", url)
        self.assertEqual(stockblock.agency("https://blog.example.com/img/iStock-1171164520.jpg"), "istock")
        self.assertEqual(stockblock.agency("https://blog.example.com/img/AdobeStock_301234.jpeg"), "adobe stock")
        self.assertEqual(stockblock.agency("https://blog.example.com/img/shutterstock_12951675b.jpg"), "shutterstock")
        self.assertEqual(stockblock.agency("https://blog.example.com/img/dreamstime_xl_1880226.jpg"), "dreamstime")
        with mock.patch.object(config, "STOCK_BLOCK_FILE_NAMES", False):
            self.assertEqual(stockblock.agency("https://grist.org/x/GettyImages-1325430438-1.jpg"), "")

    def test_title_and_credit_words(self):
        self.assertEqual(stockblock.agency("https://i.pinimg.com/a.jpg",
                                           title="St thomas lake mead hi-res stock photography and images - Alamy"), "alamy")
        self.assertEqual(stockblock.agency("https://i.pinimg.com/a.jpg", title="Boats Stock Photo - Download Image Now"),
                         "stock listing")
        self.assertEqual(stockblock.agency("https://x/a.jpg", attribution="Yandex image result — thumbs.dreamstime.com"),
                         "dreamstime")
        self.assertEqual(stockblock.agency("https://x/a.jpg", attribution="ID 123 © Name | Dreamstime.com"), "dreamstime")
        self.assertEqual(stockblock.agency("https://x/a.jpg", title="Growing Bathtub Ring Editorial Stock Photo"),
                         "stock listing")
        self.assertEqual(stockblock.agency("https://x/a.jpg", title="Lake Mead marina (for editorial use only)"),
                         "stock listing")
        self.assertEqual(stockblock.agency("https://x/a.jpg", title="Premium Photo | Aerial view of a muddy river"),
                         "freepik")
        self.assertEqual(stockblock.agency("https://x/a.jpg", title="Photo by Ethan Miller/Getty Images"), "getty")
        with mock.patch.object(config, "STOCK_BLOCK_WORDS", False):
            self.assertEqual(stockblock.agency("https://x/a.jpg", title="Boats Stock Photo - Alamy"), "")

    def test_a_free_librarys_own_titles_do_not_block_its_pictures(self):
        # Pexels and Unsplash call their own pages "Free Stock Photo": no watermark, a licence that allows use.
        self.assertEqual(stockblock.agency("https://images.pexels.com/photos/1/lake.jpeg",
                                           page_url="https://www.pexels.com/photo/lake-1/",
                                           title="Aerial View of Lake Mead · Free Stock Photo"), "")
        self.assertEqual(stockblock.agency("https://images.unsplash.com/photo-1?w=1600",
                                           title="Lake Mead | Download Free Images & Stock Photos on Unsplash"), "")
        # a named agency still blocks there, and the same words elsewhere still block
        self.assertEqual(stockblock.agency("https://images.pexels.com/photos/1/x.jpeg", title="Lake Mead - Alamy"),
                         "alamy")
        self.assertEqual(stockblock.agency("https://i.pinimg.com/736x/a.jpg", title="Lake Mead · Free Stock Photo"),
                         "stock listing")
        self.assertFalse(stockblock.free_library("https://pexels.com.evil.example/a.jpg"))

    def test_what_is_not_an_agency(self):
        self.assertEqual(stockblock.reason(PLAIN, attribution="National Park Service"), "")
        self.assertEqual(stockblock.reason("https://www.getty.edu/art/collection/x.jpg",
                                           title="J. Paul Getty Museum open content"), "")
        self.assertEqual(stockblock.reason("https://farm.example.com/livestock-123456.jpg",
                                           title="Livestock photos from the Woodstock photo fair"), "")
        self.assertEqual(stockblock.reason("https://upload.wikimedia.org/wikipedia/commons/a/ab/Hoover_Dam.jpg",
                                           attribution="Bureau of Reclamation"), "")
        self.assertEqual(stockblock.reason("https://example.com/salamy.jpg", attribution="Salamy family picnic"), "")
        self.assertEqual(stockblock.reason("https://images.pexels.com/photos/1.jpeg"), "")
        self.assertEqual(stockblock.asset_reason(MediaAsset(kind="image", source="generated", url="", local_path="x.png")),
                         "")
        with mock.patch.object(config, "STOCK_BLOCK", False):
            self.assertEqual(stockblock.reason(ALAMY), "")

    def test_assets_and_editor_choice_or_library_rows(self):
        self.assertTrue(stockblock.asset_reason(photo(ALAMY)))
        self.assertTrue(stockblock.asset_reason(photo("https://i.pinimg.com/a.jpg", page_url="https://www.alamy.com/x")))
        self.assertTrue(stockblock.asset_reason({"url": "https://x/our-copy.jpg", "sourceUrl": GETTY}))
        self.assertTrue(stockblock.asset_reason({"assetId": "a", "url": ALAMY, "title": "x", "source": "web_image"}))
        self.assertTrue(stockblock.asset_reason({"url": "https://x/a.jpg", "attribution": "Boats - Alamy Stock Photo"}))
        self.assertEqual(stockblock.asset_reason({"url": PLAIN, "title": "Boulder Beach"}), "")

    def test_every_flag_can_be_tried_on_one_job(self):
        for k in ("STOCK_BLOCK", "STOCK_BLOCK_FILE_NAMES", "STOCK_BLOCK_WORDS", "WATERMARK_CHECK",
                  "WATERMARK_CLIP_SHARE", "STOCK_GATE_REPAIR"):
            self.assertIn(k, handler.CONFIG_OVERRIDABLE)
            self.assertTrue(hasattr(config, k), k)
        self.assertTrue(config.STOCK_BLOCK and config.WATERMARK_CHECK)
        self.assertFalse(config.STOCK_GATE_REPAIR)
        self.assertEqual(config.WATERMARK_CLIP_SHARE, 0.75)


class JudgeWording(unittest.TestCase):
    """The vision judge turns down an agency's mark - and only an agency's: a caption, catalogue number or
    library stamp on an archive print, or a credit that names no agency, is not one (a "credit bar under the
    picture" on its own would also describe a museum print's label, and the verdict is a hard reject)."""

    def test_the_strict_and_the_news_judge_name_the_agency_cues_and_what_is_not_one(self):
        from src import vision
        for news in (False, True):
            with mock.patch.object(config, "NEWS_FOOTAGE", news):
                text = vision._system()
            self.assertIn("the agency's credit bar under the", text.replace("\n", " "))
            self.assertIn("Not an agency's mark: a caption, date, catalogue number or library stamp on an archive "
                          "print", text)
            self.assertIn("credit that names no agency", text)
            self.assertNotIn("or a credit bar under the picture", text)          # never any credit bar
            self.assertEqual("TV NEWS FOOTAGE IS WELCOME" in text, news)
            self.assertEqual(vision._STRICT_TEXT_RULE in text, not news)       # the news swap still matches


class EveryPath(unittest.TestCase):
    def setUp(self):
        stockblock.reset()

    def test_the_web_image_search_drops_agency_rows_and_counts_them(self):
        images = [{"imageUrl": ALAMY, "imageWidth": 1300, "imageHeight": 900, "title": "x", "link": "https://www.alamy.com/x"},
                  {"imageUrl": "https://i.pinimg.com/a.jpg", "imageWidth": 1300, "imageHeight": 900,
                   "title": "Lake Mead Stock Photo - Alamy", "link": "https://www.pinterest.com/pin/1"},
                  {"imageUrl": PLAIN, "imageWidth": 1300, "imageHeight": 900, "title": "Boulder Beach", "link": "https://www.nps.gov/x"}]
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"images": images}
        resp.raise_for_status = mock.Mock()
        with mock.patch.object(config, "ALLOW_WEB_IMAGES", True), mock.patch.object(config, "SERPER_API_KEY", "k"), \
                mock.patch.object(media.requests, "post", return_value=resp):
            found = media.search_web_images("lake mead drought", 6)
        self.assertEqual([a.url for a in found], [PLAIN])
        st = stockblock.stats()
        self.assertEqual(st["blocked"], 2)
        self.assertEqual(st["byAgency"], {"alamy": 2})
        self.assertEqual(st["byPath"], {"search": 2})

    def test_the_keyless_search_reads_past_a_page_full_of_agencies(self):
        # "Lake Mead bathtub ring" on 2026-10-04: 10 of the first 12 rows were agencies' (1 usable of 18, 6 of 35).
        rows = [{"image": f"https://c8.alamy.com/comp/X{k}/x.jpg", "width": 1300, "height": 900, "title": "x",
                 "url": "https://www.alamy.com/x"} for k in range(20)]
        rows += [{"image": f"https://www.nps.gov/lake/{k}.jpg", "width": 1300, "height": 900, "title": "Lake Mead",
                  "url": "https://www.nps.gov/lake"} for k in range(10)]
        asked = []

        class FakeDDGS:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def images(self, query, max_results=10):
                asked.append(max_results)
                return rows[:max_results]
        with mock.patch.object(config, "ALLOW_WEB_IMAGES", True), mock.patch.object(config, "SERPER_API_KEY", ""), \
                mock.patch.object(media._imagefix, "_residential_route", return_value=""), \
                mock.patch.object(media, "_next_proxy", return_value=None), \
                mock.patch("ddgs.DDGS", FakeDDGS):
            found = media.search_web_images("lake mead bathtub ring", 6)
        self.assertEqual(len(found), 6)
        self.assertTrue(all(a.url.startswith("https://www.nps.gov/") for a in found))
        self.assertGreaterEqual(asked[0], 30)
        self.assertEqual(stockblock.stats()["blocked"], 20)

    def test_the_yandex_search_uses_the_same_list(self):
        page = mock.Mock(url="https://yandex.com/images/search", text=(
            'img_url=https%3A%2F%2Fthumbs.dreamstime.com%2Fz%2Fa.jpg&x "origUrl":"https://www.nps.gov/b.jpg"'))
        with mock.patch.object(config, "ALLOW_YANDEX_IMAGES", True), \
                mock.patch.object(media.requests, "get", return_value=page), \
                mock.patch.object(media, "_next_proxy", return_value=None):
            found = media.search_yandex_images("lake mead", 8)
        self.assertEqual([a.url for a in found], ["https://www.nps.gov/b.jpg"])
        self.assertEqual(stockblock.stats()["byAgency"], {"dreamstime": 1})

    def test_a_blocked_candidate_never_downloads(self):
        with mock.patch.object(media._imagefix, "fetch") as fetch:
            self.assertIsNone(media._download(photo(ALAMY), "q", tempfile.mkdtemp()))
            self.assertIsNone(media._download(photo("https://i.pinimg.com/a.jpg", attribution="Boats - Alamy Stock Photo"),
                                              "q", tempfile.mkdtemp()))
        fetch.assert_not_called()
        self.assertEqual(stockblock.stats()["byPath"], {"download": 2})

    def test_imagefix_refuses_an_agency_address_its_page_picture_and_its_thumbnail(self):
        work = tempfile.mkdtemp()
        with mock.patch.object(imagefix, "_fetch_raw") as raw, mock.patch.object(imagefix, "download") as dl:
            with self.assertRaises(StorageError):
                imagefix.fetch(ALAMY, os.path.join(work, "a.jpg"))
            with self.assertRaises(StorageError):
                imagefix.fetch("https://cdn.example.com/b.jpg", os.path.join(work, "b.jpg"),
                               thumbnail="https://c7.alamy.com/zooms/x.jpg")
        raw.assert_not_called()
        dl.assert_not_called()
        # a web page whose og:image is an agency preview
        with mock.patch.object(imagefix, "download", side_effect=StorageError("download returned an HTML error page")), \
                mock.patch.object(imagefix, "_og_image", return_value=GETTY) as og, \
                mock.patch.object(imagefix, "_curl_cffi_get", side_effect=StorageError("no")), \
                mock.patch.object(imagefix, "_residential_route", return_value=""):
            with self.assertRaises(StorageError):
                imagefix._fetch_raw("https://news.example.com/story", os.path.join(work, "c.jpg"), "")
        og.assert_called_once()
        self.assertEqual(stockblock.stats()["byAgency"], {"alamy": 2, "getty": 1})

    def _rescue(self, cands, files, work, **patches):
        def download(c, q, w):
            c.local_path = files[c.url]
            return c
        jobs = [{"index": 0, "query": "lake mead", "seconds": 5.0, "start": 0.0, "visual_type": "image",
                 "subject": "Lake Mead", "subject_type": "place", "intent": "Lake Mead", "context": "line"}]
        results = [None]
        local_ok = patches.pop("local_ok", lambda path, intent: True)
        with mock.patch.object(config, "FRESH_MOMENTS", False), mock.patch.object(config, "ALLOW_WEB_IMAGES", True), \
                mock.patch.object(config, "RESCUE_SECONDS", 60.0), \
                mock.patch.object(media, "_cached_search", return_value=cands), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_rescue_local_ok", side_effect=local_ok), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "_photo_seen_before", return_value=False):
            media.rescue_fill(jobs, results, work)
        return results

    def test_the_rescue_pass_skips_agency_pictures_and_reads_the_pixels_of_the_rest(self):
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "stamped.jpg"), bar=(0.09, "alamy"))
        clean = picture(os.path.join(work, "clean.jpg"))
        cands = [photo(ALAMY), photo("https://blog.example.com/alamy-copy.jpg"), photo(PLAIN)]
        with mock.patch.object(localvision, "available", return_value=False), mock.patch.dict(media._BAD, clear=True):
            results = self._rescue(cands, {cands[1].url: stamped, cands[2].url: clean}, work)
            self.assertTrue(media._is_bad(cands[1].identity))          # every later scene skips it
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].url, PLAIN)
        st = stockblock.stats()
        self.assertEqual(st["byAgency"], {"alamy": 1})
        self.assertEqual(st["watermarked"], 1)
        self.assertEqual(st["byPath"], {"rescue": 2})

    def test_the_rescue_pass_reads_the_stamp_last_only_on_a_picture_it_would_keep(self):
        work = tempfile.mkdtemp()
        off = picture(os.path.join(work, "off.jpg"), colour=(90, 120, 150))       # the local check turns it down
        stamped = picture(os.path.join(work, "stamped.jpg"), colour=(150, 110, 70))
        clean = picture(os.path.join(work, "clean.jpg"))
        cands = [photo("https://blog.example.com/off.jpg"), photo("https://blog.example.com/stamped.jpg"), photo(PLAIN)]
        files = {cands[0].url: off, cands[1].url: stamped, cands[2].url: clean}
        seen = []

        def share(path):
            seen.append(os.path.basename(path))
            return 0.95 if path == stamped else 0.1
        with mock.patch.object(stockblock, "stamp_share", side_effect=share), mock.patch.dict(media._BAD, clear=True):
            results = self._rescue(cands, files, work, local_ok=lambda path, intent: path != off)
            self.assertTrue(media._is_bad(cands[1].identity))
            self.assertFalse(media._is_bad(cands[0].identity))          # off-topic for this line, not for every line
        self.assertEqual(results[0].url, PLAIN)
        self.assertEqual(seen, ["stamped.jpg", "clean.jpg"])           # never on the one already turned down
        self.assertEqual(stockblock.stats()["byMark"], {"an agency watermark stamped on the picture": 1})

    def test_the_ladders_picture_rung_skips_agency_and_known_stamped_pictures(self):
        from src import ledger, slop
        job = {"index": 2, "query": "lake mead", "start": 4.0, "subject": "Lake Mead", "intent": "Lake Mead"}
        known = photo("https://blog.example.com/known-stamped.jpg")
        cands = [photo(GETTY), known, photo(PLAIN)]
        asked = []

        def download(c, q, w):
            asked.append(c.url)
            c.local_path = "C:/tmp/none.jpg"
            return c
        with mock.patch.dict(media._BAD, {known.identity: "an agency watermark stamped on the picture"}), \
                mock.patch.object(media, "_cached_search", return_value=cands), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media, "judge_clip", return_value=(True, None)), \
                mock.patch.object(ledger, "photo_used", return_value=False):
            got = gapfill._still_for(job, 2, "lake mead", "Lake Mead", gapfill.Used(), "C:/tmp", 1e12,
                                     imagefix, ledger, media, slop)
        self.assertEqual(asked, [PLAIN])
        self.assertIs(got.url, PLAIN)
        self.assertEqual(stockblock.stats()["byPath"], {"ladder": 1})

    def test_the_ladder_remembers_a_picture_its_gate_found_stamped(self):
        from src import ledger, slop
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "stamped.jpg"), bar=(0.09, "alamy"))
        job = {"index": 1, "query": "lake mead", "start": 2.0, "subject": "Lake Mead", "intent": "Lake Mead"}
        cand = photo("https://blog.example.com/copy.jpg")

        def download(c, q, w):
            c.local_path = stamped
            return c
        with mock.patch.dict(media._BAD, clear=True), \
                mock.patch.object(media, "_cached_search", return_value=[cand]), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_asset_ok", return_value=(True, "")), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(localvision, "available", return_value=False), \
                mock.patch.object(ledger, "photo_used", return_value=False):
            got = gapfill._still_for(job, 1, "lake mead", "Lake Mead", gapfill.Used(), work, 1e12,
                                     imagefix, ledger, media, slop)
            self.assertIsNone(got)
            self.assertTrue(media._is_bad(cand.identity))

    def test_the_overlay_photos_skip_agency_pictures_and_read_the_pixels(self):
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "stamped.jpg"), bar=(0.09, "alamy"))
        clean = picture(os.path.join(work, "clean.jpg"))
        found = [photo(ALAMY), photo("https://blog.example.com/alamy-copy.jpg"), photo(PLAIN)]
        content = {found[1].url: read(stamped), found[2].url: read(clean)}
        asked = []

        def get(url, **kw):
            asked.append(url)
            return mock.Mock(status_code=200, content=content[url])
        doc = {"fps": 30, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 150, "text": "x",
                                      "media": {"type": "video", "url": "u"}, "semanticMetadata": {"subject": "Lake Mead"}}],
               "overlays": [{"type": "label-boxes", "items": [{"label": "Before"}, {"label": "After"}],
                             "startFrame": 10, "durationInFrames": 90}]}
        with mock.patch.object(config, "SPLIT_IMAGES", True), \
                mock.patch.object(media, "search_web_images", return_value=found), \
                mock.patch.object(localvision, "available", return_value=False), \
                mock.patch("requests.get", side_effect=get):
            n = handler._bind_split_images(doc, tempfile.mkdtemp(), lambda local, name: f"https://store/{name}")
        self.assertEqual(n, 1)
        self.assertEqual(sorted(set(asked)), sorted({found[1].url, found[2].url}))      # never the Alamy address
        self.assertEqual(stockblock.stats()["byPath"]["overlay"], 3)                   # 1 by name, 2 by its bar

    def test_the_best_of_never_offers_an_agency_picture_as_a_choice(self):
        winner = photo(PLAIN, relevance_score=0.9)
        loser = photo(ALAMY, relevance_score=0.8)
        other = photo("https://www.usgs.gov/a.jpg", relevance_score=0.7)
        got = media._best_of([winner, loser, other])
        self.assertIs(got, winner)
        self.assertEqual([a["url"] for a in got.alternatives], [other.url])

    def test_the_library_never_hands_out_an_agency_picture_saved_earlier(self):
        lib = library.Library.__new__(library.Library)
        lib.entries = [
            {"id": "a", "kind": "image", "subject_key": library._key("Lake Mead"), "relevance": 0.9, "saved": True,
             "url": ALAMY, "attribution": "", "analysis": {}, "entities": [], "locations": []},
            {"id": "b", "kind": "image", "subject_key": library._key("Lake Mead"), "relevance": 0.8, "saved": True,
             "url": PLAIN, "attribution": "National Park Service", "analysis": {}, "entities": [], "locations": []}]
        lib._emb = {}
        lib.story = None
        with mock.patch.object(library.ledger, "library_used", return_value=False), \
                mock.patch.object(library.Library, "_context", return_value={}), \
                mock.patch.object(library.Library, "_stale", return_value=False), \
                mock.patch.object(library.Library, "_hits", return_value=0), \
                mock.patch.object(library.Library, "_fresh", return_value=0.0):
            hits = lib.find("Lake Mead", n=5, kind="image", min_score=0.5)
        self.assertEqual([e["id"] for e in hits], ["b"])

    def test_a_library_picture_fetched_with_a_bar_leaves_the_library(self):
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "src.jpg"), bar=(0.09, "alamy"))
        lib = library.Library("p", "j")
        entry = {"id": "img:copy", "kind": "image", "read_url": "https://signed/1", "saved": True,
                 "attribution": "Lake Mead", "url": "https://blog.example.com/copy.jpg"}
        lib.entries = [entry]
        with mock.patch.object(library.storage, "download", side_effect=lambda url, path: shutil.copy(stamped, path)), \
                mock.patch.object(library.media, "slop_reason", return_value=""), \
                mock.patch.object(localvision, "available", return_value=False):
            self.assertIsNone(lib.fetch(entry, work, 5.0, {"intent": "the lake"}))
        self.assertFalse(entry["saved"])
        self.assertIn("img:copy", lib.pending)

    def test_an_image_look_never_places_a_stamped_library_picture(self):
        from src import treatments
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "stamped.jpg"), bar=(0.09, "alamy"))
        clean = picture(os.path.join(work, "clean.jpg"))
        files = {"https://signed/a": stamped, "https://signed/b": clean}
        entries = [{"id": f"img:{k}", "kind": "image", "read_url": f"https://signed/{k}", "attribution": "NPS"}
                   for k in "abc"]

        def download(url, path):
            if url not in files:
                raise StorageError("gone")
            return shutil.copy(files[url], path)
        lib = library.Library("p", "j")
        with mock.patch.object(library.storage, "download", side_effect=download), \
                mock.patch.object(localvision, "available", return_value=False):
            got = lib.unstamped(entries)
            self.assertEqual([e["id"] for e in got], ["img:b", "img:c"])    # c could not be read: it stays
            self.assertFalse(entries[0]["saved"])
            self.assertIn("img:a", lib.pending)                             # out of the library, reversibly
            with mock.patch.object(library.Library, "find", return_value=[dict(e) for e in entries]):
                media_ = treatments._library_pictures(lib, "Lake Mead", 3)
        self.assertEqual([m["url"] for m in media_], ["https://signed/b", "https://signed/c"])
        with mock.patch.object(config, "WATERMARK_CHECK", False):
            self.assertEqual(len(lib.unstamped(entries)), 3)

    def test_the_library_check_turns_down_a_saved_comp_by_its_bar(self):
        import numpy as np
        work = tempfile.mkdtemp()
        comp = picture(os.path.join(work, "comp.jpg"), 2000, 1300, bar=(0.09, "alamy"))
        clean = picture(os.path.join(work, "clean.jpg"), 2000, 1300)
        probe = {"width": 2000, "height": 1300, "seconds": 0.0, "codec": "mjpeg", "ok": True}

        def check(path):
            with Image.open(path) as im:
                frame = np.asarray(im.convert("RGB"))
            with mock.patch.object(libstore, "tools", return_value=True), \
                    mock.patch.object(libstore, "probe", return_value=dict(probe)), \
                    mock.patch.object(libstore, "frames", return_value=[frame]), \
                    mock.patch.object(libstore, "clip_facts", return_value=None), \
                    mock.patch("src.filters.text_page_still", return_value=False):
                return libstore.check(path, kind="image")
        self.assertTrue(any(r.startswith("an agency credit bar") for r in check(comp).reasons))
        self.assertFalse(any(r.startswith("an agency credit bar") for r in check(clean).reasons))

    def test_the_vision_gate_reads_the_bar_before_any_model_and_when_none_answers(self):
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "stamped.jpg"), bar=(0.09, "alamy"))
        clean = picture(os.path.join(work, "clean.jpg"))
        with mock.patch.object(media.vision, "judge", return_value=None) as judge, \
                mock.patch.object(media.vision, "enabled", return_value=True), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(media, "_local_check", return_value=None), \
                mock.patch.object(localvision, "available", return_value=False), \
                mock.patch.object(config, "ACCEPT_UNJUDGED", True):
            keep, verdict = media._vision_gate(stamped, "Lake Mead", "", "alamy copy")
            self.assertFalse(keep)
            judge.assert_not_called()                      # rejected before any model
            keep, _v = media._vision_gate(clean, "Lake Mead", "", "boulder beach")
            self.assertTrue(keep)                          # unjudged (models busy) but its pixels are clean
            judge.assert_called_once()
        st = stockblock.stats()
        self.assertEqual(st["watermarked"], 1)
        self.assertEqual(st["pixels"]["barChecked"], 2)
        self.assertEqual(st["byMark"], {"an agency credit bar along the bottom edge": 1})

    def test_the_gate_reads_the_stamp_only_on_a_picture_about_to_be_kept(self):
        work = tempfile.mkdtemp()
        p = picture(os.path.join(work, "p.jpg"))
        with mock.patch.object(stockblock, "stamp_share", return_value=0.95) as share:
            with mock.patch.object(media, "_judge_gate", return_value=(False, None)):
                self.assertEqual(media._vision_gate(p, "Lake Mead", "", "x"), (False, None))
            share.assert_not_called()                       # the judge turned it down: no stamp check
            with mock.patch.object(media, "_judge_gate", return_value=(True, {"score": 0.9})):
                media._GATE_SLOP.set("")
                self.assertEqual(media._vision_gate(p, "Lake Mead", "", "x"), (False, None))
                self.assertTrue(media._GATE_SLOP.get().startswith("an agency watermark"))
                with mock.patch.object(config, "WATERMARK_CLIP_SHARE", 0.0):
                    self.assertEqual(media._vision_gate(p, "Lake Mead", "", "x"), (True, {"score": 0.9}))
        share.assert_called_once()                          # the second picture read was the cached one
        self.assertEqual(stockblock.stats()["byPath"], {"gate": 1})

    def test_a_stamped_picture_is_remembered_and_never_downloaded_again(self):
        work = tempfile.mkdtemp()
        stamped = picture(os.path.join(work, "stamped.jpg"), bar=(0.09, "alamy"))
        cand = photo("https://blog.example.com/copy.jpg")
        downloads = []

        def download(c, q, w):
            downloads.append(c.url)
            c.local_path = stamped
            return c
        with mock.patch.dict(media._BAD, clear=True), \
                mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "_photo_seen_before", return_value=False), \
                mock.patch.object(media.ledger, "photo_used", return_value=False), \
                mock.patch.object(localvision, "available", return_value=False):
            self.assertIsNone(media._pick_unused([cand], set(), "q", work, intent="Lake Mead"))
            self.assertIsNone(media._pick_unused([dataclasses.replace(cand)], set(), "q", work, intent="Lake Mead"))
        self.assertEqual(downloads, [cand.url])             # the next scene skipped it before downloading

    def test_the_quality_gate_can_replace_an_agency_picture_on_an_older_timeline(self):
        doc = {"fps": 30, "scenes": [
            {"id": "s0", "startFrame": 0, "durationInFrames": 90, "text": "a",
             "media": {"type": "image", "url": "https://pub.r2.dev/p/media/s0.jpg", "source": "web_image",
                       "attribution": "Cracked earth - Alamy Stock Photo"},
             "semanticMetadata": {"sourceUrl": ALAMY}},
            {"id": "s1", "startFrame": 90, "durationInFrames": 90, "text": "b",
             "media": {"type": "image", "url": "https://pub.r2.dev/p/media/s1.jpg", "source": "web_image"},
             "semanticMetadata": {"sourceUrl": PLAIN}}]}
        gate = quality.Gate(doc, tempfile.mkdtemp())
        with mock.patch.object(quality.gapfill, "find_repeats", return_value=[]):
            with mock.patch.object(config, "STOCK_GATE_REPAIR", False):
                self.assertEqual(gate._scene_problems({}), {})
            with mock.patch.object(config, "STOCK_GATE_REPAIR", True):
                problems = gate._scene_problems({})
        self.assertEqual(list(problems), [0])
        self.assertEqual(problems[0], ("stock", "a stock-agency picture (alamy)"))


class Counts(unittest.TestCase):
    def setUp(self):
        stockblock.reset()

    def test_a_parts_count_joins_the_jobs(self):
        stockblock.note("a stock-agency picture (alamy)", "search", key="u1")
        stockblock.note("a stock-agency picture (alamy)", "search", key="u1")       # the same picture, once
        stockblock.merge({"blocked": 3, "byAgency": {"getty": 2, "alamy": 1}, "byPath": {"search": 3},
                          "watermarked": 1, "byMark": {"an agency credit bar along the bottom edge": 1},
                          "pixels": {"barChecked": 40, "stampChecked": 12}, "pixelSeconds": 9.31})
        st = stockblock.stats()
        self.assertEqual(st["blocked"], 4)
        self.assertEqual(st["byAgency"], {"alamy": 2, "getty": 2})
        self.assertEqual(st["watermarked"], 1)
        self.assertEqual(st["pixels"], {"barChecked": 40, "stampChecked": 12})
        self.assertEqual(st["pixelSeconds"], 9.3)
        stockblock.reset()
        self.assertEqual(stockblock.stats(), {"blocked": 0, "watermarked": 0})

    def test_the_fan_out_parent_adds_each_parts_count_to_the_jobs(self):
        stockblock.note("a stock-agency picture (alamy)", "search", key="parent-1")
        work = tempfile.mkdtemp()
        jobs = [{"index": i, "query": f"q{i}"} for i in range(9)]

        def assets(ids):
            return {str(i): {"kind": "video", "source": "youtube", "url": f"https://www.youtube.com/watch?v=vid{i:08d}",
                             "remote_url": f"https://s/{i}", "storage_path": f"x/{i:04d}.mp4"} for i in ids}
        statuses = {
            "part-a": {"status": "COMPLETED", "output": {"assets": assets((3, 4, 5)), "stockBlocked": {
                "blocked": 2, "byAgency": {"getty": 2}, "byPath": {"search": 2}}}},
            "part-b": {"status": "COMPLETED", "output": {"assets": assets((6, 7, 8)), "stockBlocked": {
                "blocked": 0, "watermarked": 1, "byMark": {"an agency credit bar along the bottom edge": 1}}}},
        }
        ids = iter(["part-a", "part-b"])

        def local(some, exclude):
            return [MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=vid{j['index']:08d}")
                    for j in sorted(some, key=lambda j: j["index"])]

        def download(url, path):
            with open(path, "wb") as fh:
                fh.write(b"x")
            return path
        with mock.patch.object(config, "FANOUT_PARTS", 3), \
                mock.patch.object(config, "FANOUT_TIMEOUT_SECONDS", 60), \
                mock.patch.object(fanout, "_submit", lambda payload: next(ids)), \
                mock.patch.object(fanout, "_status", lambda jid: statuses[jid]), \
                mock.patch.object(fanout, "_cancel", lambda jid: None), \
                mock.patch.object(fanout.storage, "download", download), \
                mock.patch.object(fanout.time, "sleep", lambda s: None):
            out = fanout.source(jobs, [], {}, parent_job_id="p", project_id="x", bucket="b", work=work, flags={},
                                report=lambda *a, **k: None, local=local)
        self.assertTrue(all(a is not None for a in out))
        st = stockblock.stats()
        self.assertEqual(st["blocked"], 3)
        self.assertEqual(st["byAgency"], {"alamy": 1, "getty": 2})
        self.assertEqual(st["watermarked"], 1)


class Pixels(unittest.TestCase):
    def setUp(self):
        stockblock.reset()

    def test_the_credit_bar_is_seen_on_a_comp_and_on_its_small_copy(self):
        work = tempfile.mkdtemp()
        comp = picture(os.path.join(work, "comp.jpg"), 1300, 900, bar=(0.09, "alamy"))
        for p in (comp, scaled_copy(comp, os.path.join(work, "big.jpg"), 1920),
                  scaled_copy(comp, os.path.join(work, "thumb.jpg"), 474)):
            bar = stockblock.credit_bar(p)
            self.assertIsNotNone(bar, p)
            self.assertAlmostEqual(bar["height"], 0.09, delta=0.02)
            self.assertTrue(stockblock.watermark_reason(p, stamp=False).startswith("an agency credit bar"))
        white = picture(os.path.join(work, "white.jpg"))
        with Image.open(white) as im:
            im = im.convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([0, int(900 * 0.93), 1300, 900], fill=(255, 255, 255))
        d.text((500, int(900 * 0.945)), "www.shutterstock.com  ·  710916592", fill=(40, 40, 40))
        im.save(white, "JPEG", quality=90)
        self.assertIsNotNone(stockblock.credit_bar(white))

    def test_a_plain_photo_a_letterbox_and_a_mounted_print_are_not_bars(self):
        work = tempfile.mkdtemp()
        self.assertIsNone(stockblock.credit_bar(picture(os.path.join(work, "plain.jpg"))))
        self.assertIsNone(stockblock.credit_bar(picture(os.path.join(work, "night.jpg"), colour=(8, 9, 12))))
        self.assertIsNone(stockblock.credit_bar(picture(os.path.join(work, "letterbox.jpg"), letterbox=True)))
        self.assertIsNone(stockblock.credit_bar(picture(os.path.join(work, "print.jpg"), frame=True)))
        with mock.patch.object(localvision, "available", return_value=False):
            self.assertEqual(stockblock.watermark_reason(picture(os.path.join(work, "plain2.jpg"))), "")
            self.assertIsNone(stockblock.stamp_share(os.path.join(work, "plain2.jpg")))

    def test_the_check_is_off_by_flag_and_never_for_a_clip_or_a_missing_file(self):
        work = tempfile.mkdtemp()
        p = picture(os.path.join(work, "bar.jpg"), bar=(0.09, "alamy"))
        with mock.patch.object(config, "WATERMARK_CHECK", False):
            self.assertEqual(stockblock.watermark_reason(p), "")
        self.assertEqual(stockblock.watermark_reason(os.path.join(work, "missing.jpg")), "")
        self.assertEqual(media.watermark_reason(os.path.join(work, "clip.mp4")), "")
        with mock.patch.object(stockblock, "stamp_share", return_value=0.99) as share, \
                mock.patch.object(config, "WATERMARK_CLIP_SHARE", 0.0):
            self.assertEqual(stockblock.watermark_reason(picture(os.path.join(work, "p.jpg")), bar=False), "")
        share.assert_not_called()                           # 0 = the stamp check off

    def test_a_picture_is_read_once_however_many_copies_of_it(self):
        work = tempfile.mkdtemp()
        a = picture(os.path.join(work, "a.jpg"))
        b = os.path.join(work, "b.jpg")
        shutil.copy(a, b)
        with mock.patch.object(stockblock, "stamp_share", return_value=0.1) as share:
            self.assertEqual(stockblock.watermark_reason(a), "")
            self.assertEqual(stockblock.watermark_reason(b), "")
        share.assert_called_once()
        st = stockblock.stats()
        self.assertEqual(st["pixels"], {"barChecked": 1, "stampChecked": 1})
        self.assertIn("pixelSeconds", st)
        stockblock.reset()
        with mock.patch.object(stockblock, "stamp_share", return_value=0.1) as share:
            stockblock.watermark_reason(a)
        share.assert_called_once()                          # a new job reads it again

    def test_the_stamp_share_reads_tiles_of_the_picture_at_full_size(self):
        import numpy as np
        work = tempfile.mkdtemp()
        p = picture(os.path.join(work, "p.jpg"), 1300, 900)
        calls = []

        def embed_images(tiles):
            calls.append([t.size for t in tiles])
            return np.eye(len(tiles), 512, dtype=np.float32)

        def embed_texts(texts):
            # the first stamp prompt reads the first tile only
            out = np.zeros((len(texts), 512), np.float32)
            out[0, 0] = 1.0
            return out
        with mock.patch.object(localvision, "available", return_value=True), \
                mock.patch.object(localvision, "embed_images", side_effect=embed_images), \
                mock.patch.object(localvision, "embed_texts", side_effect=embed_texts):
            share = stockblock.stamp_share(p)
            with mock.patch.object(config, "WATERMARK_CLIP_SHARE", 0.75):
                why = stockblock.watermark_reason(p)
        # Six square tiles cut from the FULL-size picture (450 px of it each, twice the
        # detail the whole picture gets at the model's 224 px), and the whole picture.
        with Image.open(p) as im:
            cut = [t.size for t in stockblock._tiles(im.convert("RGB"))]
        self.assertEqual(cut[0], (1300, 900))
        self.assertTrue(all(abs(w - 450) <= 1 and abs(h - 450) <= 1 for w, h in cut[1:]))
        # ... handed to the model already at its input size (the slow resize outside its slots)
        seen = calls[0]
        self.assertEqual(len(seen), 7)
        self.assertEqual(seen[0], (324, 224))
        self.assertTrue(all(s == (224, 224) for s in seen[1:]))
        self.assertGreaterEqual(share, 0.99)
        self.assertTrue(why.startswith("an agency watermark stamped on the picture"))

    def test_documents_and_archive_prints_have_plain_prompts_of_their_own(self):
        for p in ("a document", "a page of handwriting", "a scanned document", "an archive photograph with a caption"):
            self.assertIn(p, stockblock.PLAIN_PROMPTS)
        self.assertFalse(set(stockblock.PLAIN_PROMPTS) & set(stockblock.STAMP_PROMPTS))

    @unittest.skipUnless(localvision.available(), "the local CLIP model is not installed here")
    def test_with_the_real_model_a_plain_picture_passes(self):
        work = tempfile.mkdtemp()
        share = stockblock.stamp_share(picture(os.path.join(work, "p.jpg")))
        self.assertIsNotNone(share)
        self.assertLess(share, config.WATERMARK_CLIP_SHARE)


if __name__ == "__main__":
    unittest.main()
