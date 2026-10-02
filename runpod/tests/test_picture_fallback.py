"""
Pictures for scenes the footage search could not fill (the Mount Rainier video,
2026-10-02: 166 picture downloads failed - sites answering 403 or an HTML page,
one news site timing out three tries at a time - and 97 scenes were left with
no picture). A site that refused twice is not asked again for a while; the
ladder's picture rung tries more pictures and a second search wording.
"""
import time
import unittest
from unittest import mock

from src import gapfill, imagefix
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
