import unittest
from unittest import mock

from src import config, media, providers
from src.providers import SourceContext


def names(ctx):
    return [p.name for p in providers.ordered(ctx)]


class Registry(unittest.TestCase):
    def test_footage_order_and_gates(self):
        with mock.patch.object(config, "ALLOW_DAILYMOTION", True), \
                mock.patch.object(config, "ALLOW_WEB_VIDEO", True), \
                mock.patch.object(config, "ALLOW_ARCHIVE_ORG", True), \
                mock.patch.object(config, "PREFER_GENERATED_IMAGES", False):
            ctx = SourceContext("q", 6.0, "/w", allow_youtube=True, allow_stock=False, require_cc=False)
            self.assertEqual(names(ctx)[:6], ["youtube", "dailymotion", "web_video", "nasa_video",
                                              "wikimedia_video", "archive_org_video"])
            self.assertNotIn("pexels_video", names(ctx))
            self.assertNotIn("generated_first", names(ctx))
            self.assertEqual(names(ctx)[-1], "generated_last")
            # Creative Commons only: the unverified-licence providers step aside.
            cc = SourceContext("q", 6.0, "/w", require_cc=True)
            self.assertEqual(names(cc)[:3], ["youtube", "nasa_video", "wikimedia_video"])
            self.assertNotIn("dailymotion", names(cc))
            # A named person never gets a generated portrait.
            person = SourceContext("q", 6.0, "/w", subject="Ann Dunham", subject_type="person")
            self.assertNotIn("generated_last", names(person))
            self.assertIn("wikipedia_article", names(person))
            # YouTube-only jobs: nothing but YouTube.
            yo = SourceContext("q", 6.0, "/w", youtube_only=True)
            self.assertEqual(names(yo), ["youtube"])
            # A job's allow-list.
            some = SourceContext("q", 6.0, "/w", enabled_names={"nasa_video", "web_images"})
            self.assertEqual(names(some), ["nasa_video", "web_images"])

    def test_stills_fall_back_to_footage_then_generation(self):
        with mock.patch.object(config, "ALLOW_DAILYMOTION", True), \
                mock.patch.object(config, "PREFER_GENERATED_IMAGES", False):
            ctx = SourceContext("q", 6.0, "/w", visual_type="image", allow_youtube=True)
            order = names(ctx)
        self.assertNotIn("youtube", order)
        self.assertIn("youtube_for_stills", order)
        self.assertLess(order.index("web_images"), order.index("youtube_for_stills"))
        self.assertEqual(order[-1], "generated_last")

    def test_source_one_walks_the_registry_and_honours_patched_media_functions(self):
        calls = []
        asset = media.MediaAsset(kind="video", source="youtube", url="u")

        def yt(*a, **k):
            calls.append("youtube"); return None

        def dm(*a, **k):
            calls.append("dailymotion"); return asset
        with mock.patch.object(config, "ALLOW_DAILYMOTION", True), \
                mock.patch.object(media, "youtube_clip", yt), \
                mock.patch.object(media, "dailymotion_clip", dm), \
                mock.patch.object(media.config, "REQUIRE_AI", False):
            got = media._source_one("Lake Mead", 6.0, "/w", allow_youtube=True, allow_stock=False,
                                    require_cc=False)
        self.assertIs(got, asset)
        self.assertEqual(calls, ["youtube", "dailymotion"])

    def test_generation_is_tried_once_when_preferred(self):
        calls = []
        with mock.patch.object(config, "PREFER_GENERATED_IMAGES", True), \
                mock.patch.object(media, "_generation_budget_left", return_value=True), \
                mock.patch.object(media, "generate_image", side_effect=lambda *a, **k: calls.append(1) or None), \
                mock.patch.object(media, "_cached_search", return_value=[]), \
                mock.patch.object(media, "youtube_clip", return_value=None), \
                mock.patch.object(media, "dailymotion_clip", return_value=None), \
                mock.patch.object(media, "web_video_clip", return_value=None):
            media._source_one("q", 6.0, "/w", allow_youtube=True, allow_stock=False, require_cc=False)
        self.assertEqual(len(calls), 1)

    def test_lambda_searches_no_longer_share_one_cache_entry(self):
        media.reset_cache()
        seen = []
        with mock.patch.object(media, "search_pexels", side_effect=lambda q, kind="video": seen.append("pexels") or []), \
                mock.patch.object(media, "search_pixabay", side_effect=lambda q, kind="video": seen.append("pixabay") or []), \
                mock.patch.object(media, "_pick_unused", return_value=None):
            ctx = SourceContext("q", 6.0, "/w", allow_stock=True)
            providers._stock("search_pexels", "video")(ctx)
            providers._stock("search_pixabay", "video")(ctx)
        self.assertEqual(seen, ["pexels", "pixabay"])
        self.assertEqual(len(providers.describe()), len(providers.REGISTRY))


if __name__ == "__main__":
    unittest.main()
