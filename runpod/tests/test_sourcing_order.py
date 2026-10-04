"""
The order a still line asks its sources in (src/providers.py, media.source_for_segment).

Measured 2026-10-04 on Yellowstone searches (free sources, the worker's own size,
real-detail and AI checks): usable pictures - Wikimedia Commons 23 of 30, the web
search 24 of 54, Yandex 21 of 80, Openverse 0 of 24 (Flickr's 1024 px copies).
Commons answered none of 16 hard lines' own long wordings but 7-10 of their short
fallback wordings - which a still line reached only after its first wording had
walked every source, YouTube for stills included (the Yellowstone re-cut: 140
YouTube sections for 10 clip pieces).

COMMONS_BEFORE_YANDEX, OPENVERSE_WHEN_SHARP and STILLS_ALL_WORDINGS_FIRST switch
each part; off, the old order.
"""
import unittest
from unittest import mock

from src import config, media, providers
from src.media import MediaAsset
from src.providers import SourceContext

ON = dict(COMMONS_BEFORE_YANDEX=True, OPENVERSE_WHEN_SHARP=False, STILLS_ALL_WORDINGS_FIRST=True)
OLD = dict(COMMONS_BEFORE_YANDEX=False, OPENVERSE_WHEN_SHARP=True, STILLS_ALL_WORDINGS_FIRST=False)


def names(ctx):
    return [p.name for p in providers.ordered(ctx)]


class TheOrder(unittest.TestCase):
    def test_commons_is_asked_before_yandex(self):
        ctx = SourceContext("q", 6.0, "/w", visual_type="image", allow_youtube=True)
        with mock.patch.multiple(config, **ON):
            order = names(ctx)
        self.assertLess(order.index("web_images"), order.index("wikimedia_images"))
        self.assertLess(order.index("wikimedia_images"), order.index("yandex_images"))
        with mock.patch.multiple(config, **OLD):
            self.assertLess(names(ctx).index("yandex_images"), names(ctx).index("wikimedia_images"))

    def test_openverse_is_off_while_pictures_must_be_sharp(self):
        ctx = SourceContext("q", 6.0, "/w", visual_type="image")
        with mock.patch.multiple(config, PICTURE_SHARPNESS_CHECK=True, **ON):
            self.assertNotIn("openverse", names(ctx))
            self.assertFalse(media.openverse_on())
        with mock.patch.multiple(config, PICTURE_SHARPNESS_CHECK=False, **ON):
            self.assertIn("openverse", names(ctx))                 # no real-detail check: its copies may do
        with mock.patch.multiple(config, PICTURE_SHARPNESS_CHECK=True, **OLD):
            self.assertIn("openverse", names(ctx))

    def test_a_sequences_picture_pool_leaves_openverse_out_too(self):
        asked = []

        def cached(fn, q, cache_key="", key=""):
            asked.append(fn.__name__)
            return []
        with mock.patch.multiple(config, PICTURE_SHARPNESS_CHECK=True, **ON), \
                mock.patch.object(media, "_cached_search", side_effect=cached):
            media._image_pool(["Old Faithful"], "", "", 2, "geyser", "", set(), "/w")
        self.assertEqual(asked, ["search_wikimedia", "search_web_images"])

    def test_each_stage_of_a_still_line_is_its_own_part_of_the_list(self):
        with mock.patch.multiple(config, ALLOW_DAILYMOTION=True, PREFER_GENERATED_IMAGES=False, **ON):
            ctx = lambda stage: SourceContext("q", 6.0, "/w", visual_type="image", allow_youtube=True, stage=stage)
            self.assertEqual(names(ctx("footage")), ["youtube_for_stills", "dailymotion_for_stills"])
            self.assertEqual(names(ctx("generated")), ["generated_last"])
            pictures = names(ctx("pictures"))
            self.assertIn("web_images", pictures)
            self.assertFalse({"youtube_for_stills", "dailymotion_for_stills", "generated_last"} & set(pictures))
            self.assertEqual(names(ctx(None))[-3:], ["youtube_for_stills", "dailymotion_for_stills", "generated_last"])


class EveryWordingFirst(unittest.TestCase):
    """source_for_segment for a still line: every wording's pictures, then footage, then one illustration."""

    def _run(self, flags, found=None, visual_type="image", **kw):
        calls = []

        def one(query, seconds, work_dir, stage=None, **k):
            calls.append((stage, query))
            return found(stage, query) if found else None
        with mock.patch.multiple(config, PREFER_GENERATED_IMAGES=False, **flags), \
                mock.patch.object(media, "_source_one", side_effect=one), \
                mock.patch.object(media, "_count_photo"):
            got = media.source_for_segment("Biscuit Basin hydrothermal explosion plume footage", 5.0, "/w",
                                           visual_type=visual_type,
                                           fallbacks=["Biscuit Basin eruption column", "Biscuit Basin"], **kw)
        return got, calls

    def test_pictures_for_every_wording_before_any_footage_stands_in(self):
        _got, calls = self._run(ON)
        stages = [s for s, _q in calls]
        first_footage = stages.index("footage")
        self.assertEqual(set(stages[:first_footage]), {"pictures"})
        wordings = [q for s, q in calls if s == "pictures"]
        self.assertEqual(wordings[:3], ["Biscuit Basin hydrothermal explosion plume footage",
                                        "Biscuit Basin eruption column", "Biscuit Basin"])
        self.assertEqual([q for s, q in calls if s == "footage"], wordings)    # each wording again, for footage
        self.assertEqual(calls[-1], ("generated", "Biscuit Basin hydrothermal explosion plume footage"))
        self.assertEqual(stages.count("generated"), 1)                          # one illustration, last

    def test_a_short_wordings_picture_wins_before_youtube_is_asked(self):
        picture = MediaAsset(kind="image", source="wikimedia", url="https://upload.wikimedia.org/a.jpg")
        got, calls = self._run(ON, found=lambda stage, q: picture if (stage, q) == ("pictures", "Biscuit Basin")
                               else None)
        self.assertIs(got, picture)
        self.assertNotIn("footage", [s for s, _q in calls])

    def test_off_each_wording_walks_the_whole_list_in_turn(self):
        _got, calls = self._run(OLD)
        self.assertEqual([s for s, _q in calls], [None, None, None] + [None] * (len(calls) - 3))
        self.assertEqual([q for _s, q in calls][:3], ["Biscuit Basin hydrothermal explosion plume footage",
                                                     "Biscuit Basin eruption column", "Biscuit Basin"])

    def test_footage_lines_and_youtube_only_jobs_keep_their_order(self):
        _got, calls = self._run(ON, visual_type="footage")
        self.assertEqual({s for s, _q in calls}, {None})
        with mock.patch.object(media, "youtube_only", return_value=True):
            _got, calls = self._run(ON)
        self.assertEqual({s for s, _q in calls}, {None})

    def test_with_illustrations_asked_first_there_is_no_second_one_at_the_end(self):
        calls = []

        def one(query, seconds, work_dir, stage=None, **k):
            calls.append(stage)
            return None
        with mock.patch.multiple(config, PREFER_GENERATED_IMAGES=True, **ON), \
                mock.patch.object(media, "_source_one", side_effect=one):
            media.source_for_segment("q", 5.0, "/w", visual_type="image", fallbacks=["r"])
        self.assertNotIn("generated", calls)

    def test_through_the_registry_youtube_waits_for_every_wording(self):
        """The real walk: no picture for the long wording, one for the short - YouTube never asked."""
        yt = []
        picture = MediaAsset(kind="image", source="web_image", url="https://img.example/basin.jpg")

        def pick(found, used, query, work_dir, intent="", context=""):
            return picture if query == "Biscuit Basin" else None

        def cached(fn, query, cache_key="", key=""):
            return [picture]
        with mock.patch.multiple(config, ALLOW_DAILYMOTION=False, PREFER_GENERATED_IMAGES=False, **ON), \
                mock.patch.object(media, "_cached_search", side_effect=cached), \
                mock.patch.object(media, "_pick_unused", side_effect=pick), \
                mock.patch.object(media, "youtube_clip", side_effect=lambda *a, **k: yt.append(a[0]) or None), \
                mock.patch.object(media, "_count_photo"):
            got = media.source_for_segment("Biscuit Basin plume animation footage", 5.0, "/w",
                                           visual_type="image", allow_youtube=True,
                                           fallbacks=["Biscuit Basin"])
        self.assertIs(got, picture)
        self.assertEqual(yt, [])
        with mock.patch.multiple(config, ALLOW_DAILYMOTION=False, PREFER_GENERATED_IMAGES=False, **OLD), \
                mock.patch.object(media, "_cached_search", side_effect=cached), \
                mock.patch.object(media, "_pick_unused", side_effect=pick), \
                mock.patch.object(media, "youtube_clip", side_effect=lambda *a, **k: yt.append(a[0]) or None), \
                mock.patch.object(media, "_count_photo"):
            got = media.source_for_segment("Biscuit Basin plume animation footage", 5.0, "/w",
                                           visual_type="image", allow_youtube=True,
                                           fallbacks=["Biscuit Basin"])
        self.assertIs(got, picture)
        self.assertEqual(yt, ["Biscuit Basin plume animation footage"])        # the old walk asked it first


if __name__ == "__main__":
    unittest.main()
