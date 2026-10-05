"""Less work per scene for the same choice (src/media.py; the Lake Powell job, 2026-10-01).

Each scene of that news story searched 7 news channels again for every
fallback query, asked Google's video search for every rewording, searched on
after its vision budget was spent, and downloaded candidates another scene had
already found unusable - one Dailymotion section at least four times."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src import config, media
from src.media import MediaAsset


class SceneScope(unittest.TestCase):
    """A scene's own context (source_for_segment sets these)."""

    def setUp(self):
        media.reset_cache()
        self.tokens = [(media._SCENE_TRIED, media._SCENE_TRIED.set(set())),
                       (media._SCENE_JUDGED, media._SCENE_JUDGED.set([0]))]

    def tearDown(self):
        for var, token in reversed(self.tokens):
            var.reset(token)
        media.reset_cache()


class NoSearchWithoutBudget(SceneScope):
    def test_a_scene_out_of_vision_budget_does_not_search(self):
        media._SCENE_JUDGED.get()[0] = config.JUDGE_MAX_PER_SCENE
        with mock.patch.object(media, "_yt_candidates_cached", side_effect=AssertionError("must not search")), \
                mock.patch.object(media, "_channel_candidates", side_effect=AssertionError("must not search")):
            self.assertIsNone(media._youtube_pool("Lake Powell boat ramp", "/tmp", 5.0, 30.0, False, 0, set(),
                                                  "Lake Powell boat ramp", "", "Lake Powell",
                                                  [("Lake Powell boat ramp", "plain", False)]))


class NewsChannelsOncePerScene(SceneScope):
    def test_the_channel_lookup_joins_the_first_search_only(self):
        seen = []

        def pool(query, out_dir, seconds, start_at, require_cc, skip, used, intent, context, subject,
                 searches, expand=True):
            seen.append([v for _q, v, _r in searches])
            return None
        with mock.patch.object(media, "_story_channels", return_value=["@Reuters", "@AssociatedPress"]), \
                mock.patch.object(media, "_youtube_pool", side_effect=pool):
            media.youtube_clip("Lake Powell boat ramp", "/tmp", require_cc=False)
            media.youtube_clip("Lake Powell 2026 footage", "/tmp", require_cc=False)   # the next fallback
        self.assertIn("channels", seen[0])
        self.assertNotIn("channels", seen[1])


class GoogleForThePlainQuery(unittest.TestCase):
    def test_rewordings_do_not_ask_google_again(self):
        asked = []
        with mock.patch.object(media, "_yt_candidates", return_value=[]), \
                mock.patch.object(media, "_google_youtube_candidates",
                                  side_effect=lambda q: asked.append(q) or []):
            media.reset_cache()
            media._yt_candidates_cached("ytsearch20:Lake Powell drone aerial footage", False, "Lake Powell", "broll")
            media._yt_candidates_cached("ytsearch20:Lake Powell low water", False, "Lake Powell", "intent")
            media._yt_candidates_cached("ytsearch20:Lake Powell", False, "Lake Powell", "plain")
        self.assertEqual(asked, ["Lake Powell"])


class ASectionTooShortIsNotFetchedAgain(unittest.TestCase):
    """A section tidy_clip threw away (no clean start long enough for the line) is remembered by moment:
    another line asking for as much skips the download, a shorter line may still use it."""

    def setUp(self):
        media.reset_cache()
        self.addCleanup(media.reset_cache)

    def _scene(self, seconds, fetched):
        from src import ledger
        row = mock.Mock(id="SHORT000001", title="Lake Powell boat ramp", channel="", aspect=1.78, metadata=0.8,
                        parts={})
        row.row.return_value = {"id": row.id, "title": row.title, "duration": 600, "aspect": 1.78, "channel": ""}
        pool = mock.Mock()
        pool.ranked.return_value = [row]
        pool.__len__ = lambda self: 1
        pool.searches = 1

        def fetch(vid, out_dir, point, grab, title="", least=None):
            fetched.append((round(grab, 2), least))
            return "", False, 3                     # downloaded, then no clean start long enough
        tokens = [(media._SCENE_TRIED, media._SCENE_TRIED.set(set())),
                  (media._SCENE_JUDGED, media._SCENE_JUDGED.set([0]))]
        try:
            with mock.patch.object(media.candidates, "CandidatePool", return_value=pool), \
                    mock.patch.object(media, "_yt_candidates_cached", return_value=[]), \
                    mock.patch.object(media, "_plan_grabs", return_value=[(row.row.return_value, 101.0, None)]), \
                    mock.patch.object(media, "fetch_clean_clip", side_effect=fetch), \
                    mock.patch.object(media, "_refine_moment", side_effect=lambda r, m, *a: m), \
                    mock.patch.object(ledger, "moment_used", return_value=False):
                return media._youtube_pool("Lake Powell boat ramp", tempfile.gettempdir(), seconds, 30.0, False,
                                           0, set(), "Lake Powell boat ramp", "", "Lake Powell",
                                           [("Lake Powell boat ramp", "plain", False)])
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    def test_the_next_line_skips_it_a_shorter_one_may_try(self):
        fetched = []
        self.assertIsNone(self._scene(5.0, fetched))
        self.assertEqual(fetched, [(6.5, 5.5)])         # the line plays 5.5 s (its crossfade included)
        self.assertIsNone(self._scene(5.0, fetched))
        self.assertEqual(len(fetched), 1)               # not downloaded and thrown away again
        self._scene(3.0, fetched)
        self.assertEqual(fetched[-1], (4.5, 3.5))       # a shorter line may still fit
        media.reset_cache()
        self._scene(5.0, fetched)
        self.assertEqual(len(fetched), 3)               # a new job decides again


class UnusableOnceUnusableForAll(SceneScope):
    def test_what_is_remembered_and_for_how_much(self):
        media._mark_bad("yt:VIDEO000001", "yt:VIDEO000001@3", "an AI-generated or painted picture")
        media._mark_bad("yt:VIDEO000002", "yt:VIDEO000002@3", "a slideshow of stills")
        media._mark_bad("yt:VIDEO000003", "yt:VIDEO000003@3", "a TV studio, presenter or talking head")
        media._mark_bad("yt:VIDEO000004", "yt:VIDEO000004@3", "")
        self.assertTrue(media._is_bad("yt:VIDEO000001"))                 # the whole video
        self.assertFalse(media._is_bad("yt:VIDEO000002"))                # that moment only
        self.assertTrue(media._is_bad("yt:VIDEO000002@3"))
        self.assertFalse(media._is_bad("yt:VIDEO000003", "yt:VIDEO000003@3"))   # a named person's line may use it
        self.assertFalse(media._is_bad("yt:VIDEO000004", "yt:VIDEO000004@3"))
        media.reset_cache()
        self.assertFalse(media._is_bad("yt:VIDEO000001"))                # a new job decides again

    def test_a_picture_turned_down_as_ai_is_not_downloaded_again(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "a.jpg")
        # A real photo-sized picture: the checks every caller asks of it (_asset_ok) now run before the
        # judge, and a few bytes of nothing would be turned down there as unreadable.
        from PIL import Image
        Image.effect_noise((1200, 800), 60).convert("RGB").save(p, "JPEG", quality=85)
        downloads = []

        def download(candidate, query, work_dir):
            downloads.append(candidate.url)
            candidate.local_path = p
            return candidate
        cand = MediaAsset(kind="image", source="web_image", url="https://example.com/lake.jpg",
                          attribution="Lake Powell")
        with mock.patch.object(media, "_download", side_effect=download), \
                mock.patch.object(media, "slop_reason", return_value="an AI-generated or painted picture"):
            self.assertIsNone(media._pick_unused([cand], set(), "Lake Powell", d, "Lake Powell"))
            self.assertIsNone(media._pick_unused([cand], set(), "Lake Powell", d, "Lake Powell aerial"))
        self.assertEqual(downloads, ["https://example.com/lake.jpg"])

    def test_a_dailymotion_section_that_will_not_play_is_fetched_once(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        fetched = []

        def fetch(vid, out_dir, start, seconds):
            fetched.append(vid)
            p = os.path.join(d, f"dm_{vid}_{len(fetched)}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"audio only" * 500)
            return p
        rows = [{"id": "x9bad01", "title": "Lake Powell drone footage", "duration": 120.0, "aspect": 1.78}]
        with mock.patch.object(media, "_cached_search", return_value=rows), \
                mock.patch.object(media, "_dm_fetch", side_effect=fetch), \
                mock.patch.object(media, "playable_video", return_value=False), \
                mock.patch.object(media, "_vision_gate", side_effect=AssertionError("never judged")):
            self.assertIsNone(media.dailymotion_clip("Lake Powell", d, seconds=4.0, subject="Lake Powell"))
            self.assertIsNone(media.dailymotion_clip("Lake Powell boat ramp", d, seconds=4.0, subject="Lake Powell"))
        self.assertEqual(fetched, ["x9bad01"])
        self.assertEqual(os.listdir(d), [])                              # nothing left behind


if __name__ == "__main__":
    unittest.main()
