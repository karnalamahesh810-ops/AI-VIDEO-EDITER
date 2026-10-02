"""
Niche footage packs (src/packs.py, src/packbuild.py, scripts/build_pack.py).

The owner's rules (2026-10-01): no empty scenes, every clip fits its own line,
never the same clip twice - in a video or in his recent ones. A pack is a
shelf of pre-checked clips on R2; the fallback ladder's first rung takes one
whose picture fits a scene the footage search left empty.

Offline: CLIP is a stub (five axes: drought, dam, storm, city, other), every
manifest and download is a fake, nothing touches R2 or the network.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, filters, gapfill, ledger, media, packs, quality, storage  # noqa: E402
from src.media import MediaAsset  # noqa: E402

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

# --------------------------------------------------------------------------- #
# A CLIP that knows five things
# --------------------------------------------------------------------------- #

AXES = {"drought": 0, "dam": 1, "storm": 2, "city": 3}      # axis 4 = anything else


def unit(*pairs) -> np.ndarray:
    v = np.zeros(5, dtype=np.float32)
    for axis, weight in pairs:
        v[axis] = weight
    return v / np.linalg.norm(v)


class FakeClip:
    """localvision as far as packs reads it: text -> the axes whose words it contains."""

    def available(self):
        return True

    def embed_texts(self, texts):
        rows = []
        for t in texts:
            v = np.zeros(5, dtype=np.float32)
            for word, axis in AXES.items():
                if word in t.lower():
                    v[axis] = 1.0
            if not v.any():
                v[4] = 1.0
            rows.append(v / np.linalg.norm(v))
        return np.stack(rows)


def entry(n, vec, niche="water", topics=("drought",), source="nasa", klass="pd", seconds=7.0, src=None,
          start=None, **kw) -> packs.Entry:
    """A pack entry: its own file, and (by default) its own source video."""
    src = src or f"{source}-SRC{n:03d}"
    start = float(10 * n if start is None else start)
    e = packs.Entry(id=f"{src}@{int(start)}", niche=niche, url=f"https://packs.example/{niche}/clips/{src}-{int(start)}.mp4",
                    seconds=seconds, width=1920, height=1080, topics=list(topics), source=source,
                    license={"pd": "Public domain (NASA)", "cc0": "CC0", "cc-by": "CC BY 4.0",
                             "cc-by-sa": "CC BY-SA 4.0", "unverified": "unverified"}[klass],
                    license_class=klass, attribution=f"Author {n} - Title {n}", source_url=f"https://images.nasa.gov/details/{src}",
                    start=start, title=f"Title {n}", vec=np.asarray(vec, dtype=np.float32))
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def shelf(entries, niche="water") -> packs.Pack:
    return packs.Pack.from_manifest(niche, packs.manifest(niche, entries))


class Shelves:
    """packs.load/available/_clip patched: the given niches' packs exist, CLIP is the stub."""

    def __init__(self, **by_niche):
        self.by_niche = by_niche
        self.patches = []

    def __enter__(self):
        self.patches = [
            mock.patch.object(packs, "available", return_value=True),
            mock.patch.object(packs, "load", side_effect=lambda n, refresh=False: self.by_niche.get(n)),
            mock.patch.object(packs, "_clip", return_value=FakeClip()),
            mock.patch.object(ledger, "pack_used", return_value=False),
        ]
        for p in self.patches:
            p.start()
        packs.reset()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        packs.reset()
        return False


def fake_download(url, dest, timeout=0, headers=None):
    with open(dest, "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypisom" + bytes(3000))
    return dest


def playable_everything():
    return mock.patch.multiple(filters, playable_video=mock.DEFAULT)


# --------------------------------------------------------------------------- #
# Which niches a story is about
# --------------------------------------------------------------------------- #

class NicheDetection(unittest.TestCase):
    def test_a_lake_powell_video_reads_water_and_nature(self):
        got = packs.detect_niches("Lake Powell is dying", "Lake Powell drops to a record low",
                                  "The reservoir behind Glen Canyon Dam has lost half its water in the drought",
                                  "Lake Powell Glen Canyon")
        self.assertEqual(got[0], "water")
        self.assertIn("nature", got)

    def test_the_style_names_its_niches_and_a_stray_word_brings_no_shelf(self):
        self.assertEqual(packs.detect_niches("A quiet evening", style="nature_weather"), ["weather", "nature"])
        got = packs.detect_niches("Drought, reservoirs, canals and irrigation across the city")
        self.assertEqual(got, ["water"])                       # "city" alone is under 40% of water's hits
        self.assertEqual(packs.detect_niches("A history of the printing press"), [])

    def test_words_meet_in_every_form(self):
        self.assertIn("fire", packs.detect_niches("Wildfires and firefighters on the ridge"))
        self.assertIn("weather", packs.detect_niches("The flooded streets and a hurricane's storm surge"))
        self.assertIn("earth", packs.detect_niches("A magnitude 7 earthquake and the aftershocks"))

    def test_every_niche_has_topics_with_prompts_and_searches(self):
        self.assertEqual(sorted(packs.NICHES), ["cities", "earth", "fire", "nature", "water", "weather"])
        for niche in packs.NICHES.values():
            self.assertGreaterEqual(len(niche.topics), 4, niche.name)
            for t in niche.topics:
                self.assertTrue(t.prompts and t.queries, (niche.name, t.name))
        names = [t.name for t in packs.NICHES["water"].topics]
        for want in ("drought", "reservoirs", "dams", "low lake levels", "bathtub rings", "dry riverbeds", "canals",
                     "aqueducts", "irrigation", "water towers", "desalination"):
            self.assertIn(want, names)

    def test_a_job_keeps_its_niches_and_a_line_adds_its_own(self):
        packs.reset()
        got = packs.use_job(title="Lake Powell", brief={"event": "Lake Powell drops", "places": ["Lake Powell"],
                                                          "summary": "The reservoir and the drought."})
        self.assertIn("water", got)
        job = {"index": 3, "intent": "a violent thunderstorm and lightning over the lake"}
        self.assertEqual(packs.niches_for(job)[0], "water")
        self.assertIn("weather", packs.niches_for(job))
        with mock.patch.object(config, "PACKS_NICHES", "fire, nonsense"):
            self.assertEqual(packs.niches_for(job), ["fire"])           # the job's own choice wins
        packs.reset()
        self.assertEqual(packs.niches_for({"index": 0}), [])


# --------------------------------------------------------------------------- #
# The manifest
# --------------------------------------------------------------------------- #

class Manifest(unittest.TestCase):
    def test_a_manifest_round_trips_with_compact_embeddings(self):
        e = entry(1, unit((0, 1.0), (1, 0.2)), topics=("drought", "dry riverbeds"), klass="cc-by",
                  phash=["00ff00ff00ff00ff", None], checks={"ok": True, "sharpness": 31.2})
        text = json.dumps(packs.manifest("water", [e], sources={"nasa:SRC001": {"kept": 1}}))
        data = json.loads(text)
        self.assertEqual((data["niche"], data["count"], data["dim"], data["model"]),
                         ("water", 1, 5, packs.MODEL))
        row = data["entries"][0]
        for key in ("id", "url", "niche", "topics", "seconds", "width", "height", "source", "license", "licenseClass",
                    "attribution", "sourceUrl", "embedding", "checks", "phash"):
            self.assertIn(key, row)
        self.assertLess(len(row["embedding"]), 20)                      # 5 float16 numbers, base64
        back = packs.Pack.from_manifest("water", data)
        got = back.entries[0]
        self.assertEqual((got.id, got.topics, got.license_class, got.attribution, got.checks["sharpness"]),
                         (e.id, ["drought", "dry riverbeds"], "cc-by", e.attribution, 31.2))
        self.assertTrue(np.allclose(got.vec, e.vec, atol=1e-3))
        self.assertEqual(back.dim, 5)
        self.assertEqual(data["sources"], {"nasa:SRC001": {"kept": 1}})

    def test_rows_that_cannot_be_used_are_left_out_not_fatal(self):
        good = entry(1, unit((0, 1.0))).to_dict()
        data = {"entries": [good, {"id": "x"}, dict(good, id="y", embedding="not base64!"), "junk",
                            dict(good, id="z", url="")]}
        pack = packs.Pack.from_manifest("water", data)
        self.assertEqual([e.id for e in pack.entries], [good["id"]])
        wrong_dim = dict(good, id="w", embedding=packs.encode_vec(np.ones(3, dtype=np.float32)))
        pack = packs.Pack.from_manifest("water", {"entries": [good, wrong_dim]})
        self.assertEqual((len(pack.entries), pack.dropped), (1, 1))     # one dimension per shelf

    def test_the_asset_id_the_video_and_the_moment_link(self):
        e = entry(2, unit((0, 1.0)), src="nasa-GSFC_Drought", start=45)
        self.assertEqual(e.asset_id, "pack:water:nasa-GSFC_Drought@45")
        self.assertEqual(e.video, "pack:water:nasa-GSFC_Drought")
        self.assertEqual(e.moment_url, "https://images.nasa.gov/details/nasa-GSFC_Drought?t=45")
        lib = entry(3, unit((0, 1.0)), source="library", source_url="https://www.youtube.com/watch?v=ABCDEFGHIJK&t=35")
        self.assertEqual(lib.moment_url, "https://www.youtube.com/watch?v=ABCDEFGHIJK&t=35")
        # gapfill reads a pack clip as a moment of its source video, like a YouTube video's
        self.assertEqual(gapfill._video_of(e.asset_id, e.moment_url), "pack:water:nasa-GSFC_Drought")
        self.assertEqual(gapfill._video_of(lib.asset_id, lib.moment_url), "yt:ABCDEFGHIJK")

    def test_the_manifest_is_read_by_its_public_link_once_and_a_miss_is_remembered(self):
        packs.clear_cache()
        e = entry(1, unit((0, 1.0)))
        body = packs.manifest("water", [e])
        calls = []

        def get(url, timeout=0, headers=None):
            calls.append(url)
            return mock.Mock(status_code=200, json=lambda: body, raise_for_status=lambda: None)

        with mock.patch.multiple(config, PACKS_PUBLIC_BASE="https://pub-1.r2.dev/", PACKS_DIR="", R2_LIBRARY_PREFIX="",
                                 PACKS_PREFIX="packs/"), \
                mock.patch.object(packs.requests, "get", side_effect=get):
            threads = [threading.Thread(target=packs.load, args=("water",)) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            pack = packs.load("water")
            self.assertEqual(len(pack.entries), 1)
            self.assertEqual(calls, ["https://pub-1.r2.dev/packs/water/index.json"])      # one request, six askers
            miss = mock.Mock(status_code=404)
            with mock.patch.object(packs.requests, "get", return_value=miss) as g:
                self.assertIsNone(packs.load("fire"))
                self.assertIsNone(packs.load("fire"))
                self.assertEqual(g.call_count, 1)
            with mock.patch.object(packs.requests, "get", side_effect=OSError("down")):
                self.assertIsNone(packs.load("earth"))                                   # never raises
            self.assertIsNone(packs.load("nonsense"))
        packs.clear_cache()

    def test_nothing_is_read_without_a_public_domain(self):
        packs.clear_cache()
        with mock.patch.multiple(config, PACKS_PUBLIC_BASE="", R2_LIBRARY_PUBLIC_BASE="", PACKS_DIR=""):
            self.assertFalse(packs.available())
            self.assertIsNone(packs.load("water"))
            self.assertEqual(packs.manifest_url("water"), "")

    def test_a_local_folder_is_read_instead_when_asked(self):
        packs.clear_cache()
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "water"))
        with open(os.path.join(d, "water", "index.json"), "w", encoding="utf-8") as fh:
            json.dump(packs.manifest("water", [entry(1, unit((0, 1.0)))]), fh)
        with mock.patch.multiple(config, PACKS_DIR=d, PACKS_PUBLIC_BASE=""):
            self.assertEqual(len(packs.load("water").entries), 1)
        packs.clear_cache()
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# find(): the clips that fit a line, never one that does not
# --------------------------------------------------------------------------- #

class Find(unittest.TestCase):
    def setUp(self):
        self.drought = entry(1, unit((0, 1.0), (4, 0.3)), topics=("drought",))
        self.dam = entry(2, unit((1, 1.0), (4, 0.3)), topics=("dams",))
        self.mixed = entry(3, unit((0, 0.7), (1, 0.7)), topics=("reservoirs",))
        self.storm = entry(4, unit((2, 1.0)), niche="weather", topics=("storm clouds",))
        self.water = shelf([self.drought, self.dam, self.mixed])
        self.weather = shelf([self.storm], "weather")

    def test_the_best_fit_comes_first_and_a_clip_that_does_not_fit_is_never_returned(self):
        with Shelves(water=self.water, weather=self.weather):
            hits = packs.find("a drought across the land", ["water"], n=5, min_similarity=0.3)
            self.assertEqual([h.entry.id for h in hits], [self.drought.id, self.mixed.id])
            self.assertGreater(hits[0].similarity, hits[1].similarity)
            self.assertNotIn(self.dam.id, [h.entry.id for h in hits])              # below the floor: never
            # a line about nothing the shelf has: nothing, however empty the scene is
            self.assertEqual(packs.find("a quiet street at dawn", ["water"], min_similarity=0.35), [])
            # the floor is the config's unless given
            with mock.patch.object(config, "PACKS_MIN_SIMILARITY", 0.9):
                self.assertEqual([h.entry.id for h in packs.find("a drought", ["water"])], [self.drought.id])
                self.assertEqual([h.entry.id for h in packs.find("a dam and a drought", ["water"])], [self.mixed.id])

    def test_several_shelves_are_searched_and_unknown_or_missing_ones_skipped(self):
        with Shelves(water=self.water, weather=self.weather):
            hits = packs.find(["a storm over the land", "a drought"], ["water", "weather", "fire", "nonsense"],
                              min_similarity=0.5)
            self.assertEqual({h.entry.niche for h in hits}, {"water", "weather"})
            self.assertEqual(packs.find("a storm", [], min_similarity=0.5), [])
            self.assertEqual(packs.find("", ["water"]), [])

    def test_without_the_local_model_or_a_shelf_nothing_is_found(self):
        with Shelves(water=self.water), mock.patch.object(packs, "_clip", return_value=None):
            self.assertEqual(packs.find("a drought", ["water"], min_similarity=0.1), [])
        with Shelves():
            self.assertEqual(packs.find("a drought", ["water"], min_similarity=0.1), [])

    def test_topic_words_only_break_ties_never_let_a_clip_under_the_floor_in(self):
        twin_a = entry(5, unit((0, 1.0)), topics=("canals",))
        twin_b = entry(6, unit((0, 1.0)), topics=("drought",))
        with Shelves(water=shelf([twin_a, twin_b])):
            hits = packs.find("a drought", ["water"], min_similarity=0.5)
            self.assertEqual(hits[0].entry.id, twin_b.id)                         # its topic is the line's word
            self.assertAlmostEqual(hits[0].similarity, hits[1].similarity, places=4)
            self.assertGreater(hits[0].score, hits[1].score)
            # a word match on a clip that does not fit stays out
            self.assertEqual(packs.find("a drought", ["water"], min_similarity=1.1), [])

    def test_a_clip_must_be_long_enough_for_its_scene(self):
        short = entry(7, unit((0, 1.0)), seconds=2.0)
        longer = entry(8, unit((0, 1.0), (4, 0.1)), seconds=8.0)
        with Shelves(water=shelf([short, longer])):
            hits = packs.find("a drought", ["water"], seconds=6.0, min_similarity=0.5)
            self.assertEqual([h.entry.id for h in hits], [longer.id])             # 2 s / 0.6 < 6 s: it would freeze
            hits = packs.find("a drought", ["water"], seconds=3.0, min_similarity=0.5)
            self.assertEqual({h.entry.id for h in hits}, {short.id, longer.id})

    def test_licences_are_kept_apart_and_a_claim_free_job_takes_no_unverified_clip(self):
        pd = entry(1, unit((0, 1.0)), klass="pd")
        by = entry(2, unit((0, 1.0)), klass="cc-by")
        lib = entry(3, unit((0, 1.0)), klass="unverified", source="library")
        with Shelves(water=shelf([pd, by, lib])):
            got = {h.entry.license_class for h in packs.find("a drought", ["water"], min_similarity=0.5, n=9)}
            self.assertEqual(got, {"pd", "cc-by", "unverified"})
            got = {h.entry.license_class for h in packs.find("a drought", ["water"], min_similarity=0.5, n=9,
                                                             require_cc=True)}
            self.assertEqual(got, {"pd", "cc-by"})
            with mock.patch.object(config, "PACKS_LICENSES", "pd,cc0"):
                got = {h.entry.license_class for h in packs.find("a drought", ["water"], min_similarity=0.5, n=9)}
            self.assertEqual(got, {"pd"})                                         # nothing to credit

    def test_the_lines_description_comes_from_the_planners_intent_first(self):
        job = {"intent": "Lake Mead 2026 exposed shoreline", "query": "lake mead low", "subject": "Lake Mead",
               "context": "The reservoir has dropped nearly 150 feet since the year 2000. " * 6,
               "scene_intent": {"visual_subjects": ["bathtub ring", "dry docks", "a third"]}}
        got = packs.line_texts(job)
        self.assertEqual(got[0], "Lake Mead 2026 exposed shoreline")
        self.assertIn("bathtub ring", got)
        self.assertLessEqual(len(got), 5)
        self.assertTrue(all(len(t) <= 200 for t in got))


# --------------------------------------------------------------------------- #
# Never the same clip twice: in the video, or in the owner's recent ones
# --------------------------------------------------------------------------- #

class NoRepeats(unittest.TestCase):
    def test_the_video_never_shows_a_file_or_a_neighbouring_moment_of_one_source_twice(self):
        a = entry(1, unit((0, 1.0)), src="nasa-AAA", start=10)
        a_near = entry(2, unit((0, 1.0), (4, 0.05)), src="nasa-AAA", start=25)       # 15 s on: the same moment
        a_far = entry(3, unit((0, 1.0), (4, 0.1)), src="nasa-AAA", start=100)        # far enough
        b = entry(4, unit((0, 1.0), (4, 0.2)), src="nasa-BBB", start=5)
        used = gapfill.Used()
        used.add(0, packs.shot_of(a))
        with Shelves(water=shelf([a, a_near, a_far, b])):
            ids = lambda index: [h.entry.id for h in packs.find("a drought", ["water"], used, index=index,
                                                                n=9, min_similarity=0.5)]
            self.assertNotIn(a.id, ids(5))                                           # the same file
            self.assertNotIn(a_near.id, ids(5))                                      # the same moment of its source
            self.assertEqual(ids(5), [a_far.id, b.id])                               # a far moment and another source
            self.assertEqual(ids(1), [b.id])                                         # next scene: not even a far moment
            self.assertIn(a.id, ids(0))                                              # scene 0's own claim is its own

    def test_claims_are_exclusive_between_scenes_filling_at_once(self):
        e = entry(1, unit((0, 1.0)))
        used = gapfill.Used()
        shot = packs.shot_of(e)
        self.assertTrue(used.claim(0, shot))
        self.assertFalse(used.claim(3, packs.shot_of(e)))

    def test_a_clip_an_earlier_video_showed_is_never_offered(self):
        shown = entry(1, unit((0, 1.0)), src="nasa-SHOWN", start=20)
        same_source = entry(2, unit((0, 1.0), (4, 0.1)), src="nasa-SHOWN", start=30)   # 10 s from the shown moment
        other_source = entry(3, unit((0, 1.0), (4, 0.2)), src="nasa-OTHER", start=20)
        led = ledger.Ledger()
        led.add({"k": "url", "u": ledger.norm_url(shown.moment_url), "s": 20.0, "e": 27.0, "a": shown.asset_id})
        ledger.use(led)
        patches = [mock.patch.object(packs, "available", return_value=True),
                   mock.patch.object(packs, "load", return_value=shelf([shown, same_source, other_source])),
                   mock.patch.object(packs, "_clip", return_value=FakeClip())]
        for p in patches:
            p.start()
        try:
            got = [h.entry.id for h in packs.find("a drought", ["water"], n=9, min_similarity=0.5)]
            self.assertEqual(got, [other_source.id])                                 # asset id and moment both kept out
            self.assertEqual(led.skipped["pack"], 2)
            with mock.patch.object(config, "CROSS_VIDEO_REUSE_DAYS", 0):             # the rule off: all three
                got = [h.entry.id for h in packs.find("a drought", ["water"], n=9, min_similarity=0.5)]
            self.assertEqual(len(got), 3)
            got = [h.entry.id for h in packs.find("a drought", ["water"], n=9, min_similarity=0.5, cross_video=False)]
            self.assertEqual(len(got), 3)
        finally:
            for p in reversed(patches):
                p.stop()
            ledger.use(ledger.Ledger())

    def test_a_pack_clip_on_the_timeline_is_recorded_for_the_next_video_and_seen_as_a_repeat(self):
        e = entry(1, unit((0, 1.0)), src="nasa-DRY", start=40)
        asset = MediaAsset(kind="video", source="nasa", url=e.moment_url, local_path="/w/pack_x.mp4", moment_key=e.asset_id,
                           moment={"start": 40.0})
        scene = lambda i, with_asset: {
            "id": f"s{i:04d}", "startFrame": i * 90, "durationInFrames": 90,
            "media": dict(with_asset.to_scene_media(), clipSeconds=6.0),
            "semanticMetadata": {"assetId": with_asset.identity, "sourceUrl": with_asset.url,
                                 "moment": dict(with_asset.moment), "provider": "nasa"}}
        doc = {"fps": 30, "scenes": [scene(0, asset), scene(4, asset)]}
        items = ledger.items_from_doc(doc)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["k"], items[0]["a"], items[0]["s"]), ("url", e.asset_id, 40.0))
        led = ledger.Ledger()
        for it in items:
            led.add(it)
        self.assertTrue(led.asset_used(e.asset_id))
        self.assertTrue(led.url_used(e.moment_url, 40.0, 46.0))
        self.assertTrue(led.url_used(e.moment_url, 55.0, 61.0))                       # within CROSS_VIDEO_GAP_SECONDS
        self.assertFalse(led.url_used(e.moment_url, 400.0, 406.0))                    # another moment of the source
        self.assertEqual([i for i, _w in gapfill.find_repeats(doc)], [1])             # the second scene repeats the first


# --------------------------------------------------------------------------- #
# The fallback ladder's first rung
# --------------------------------------------------------------------------- #

class _FakeLibrary:
    """library.Library's find/fetch over a few entries."""

    def __init__(self, entries, work):
        self.entries = [dict(e, kind="video", saved=True, relevance=0.9) for e in entries]
        self.used = set()
        self.work = work

    def find(self, subject, exclude=None, n=1, kind="video", **kw):
        key = " ".join(subject.lower().split())
        return [e for e in self.entries if e["subject_key"] == key and e["id"] not in (exclude or set())][:n]

    def fetch(self, entry, work, seconds, job):
        self.used.add(entry["id"])
        return MediaAsset(kind="video", source="youtube", url=entry["url"], local_path=os.path.join(work, "lib.mp4"),
                          moment_key=entry["id"], relevance_score=0.9)


def job(i, **kw):
    base = {"index": i, "query": "drought", "seconds": 4.0, "start": i * 4.0, "visual_type": "footage",
            "subject": "Lake Powell", "subject_type": "place", "intent": "a severe drought", "context": f"line {i}",
            "hook": False}
    base.update(kw)
    return base


class Rung(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        gapfill.reset()
        self.patches = [mock.patch.object(storage, "download", side_effect=fake_download),
                        mock.patch.object(filters, "playable_video", return_value=True),
                        mock.patch.object(config, "FALLBACK_PARALLEL", 1),
                        mock.patch.object(config, "IMAGE_MAX_PER_VIDEO", 0),
                        mock.patch.object(media, "_cached_search", return_value=[]),
                        mock.patch.object(media, "youtube_only", return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.work, ignore_errors=True)
        gapfill.reset()

    def test_the_pack_is_asked_first_and_the_summary_counts_it(self):
        pack_clip = entry(1, unit((0, 1.0)), topics=("drought",))
        lib = _FakeLibrary([{"id": "yt:LIBRARY0001@4", "url": "https://www.youtube.com/watch?v=LIBRARY0001&t=35",
                             "read_url": "https://r2/lib.mp4", "subject_key": "lake powell"}], self.work)
        jobs = [job(0), job(1, intent="a crowded city street", query="city", subject_type="object")]
        results = [None, None]
        with Shelves(water=shelf([pack_clip])):
            packs.use_job(title="Lake Powell drought", brief={"event": "drought", "places": ["Lake Powell"]})
            got = gapfill.fill_empty(jobs, results, self.work, library=lib)
        self.assertEqual((got["pack"], got["library"], got["left"]), (1, 1, 0))
        first, second = results
        self.assertEqual(first.moment_key, pack_clip.asset_id)                    # the pack, not the library
        self.assertEqual(first.source, "nasa")
        self.assertTrue(os.path.isfile(first.local_path))
        self.assertEqual(os.path.dirname(first.local_path), self.work)
        self.assertEqual(second.moment_key, "yt:LIBRARY0001@4")                   # nothing in the pack fits a city street
        self.assertEqual(lib.used, {"yt:LIBRARY0001@4"})
        self.assertIn("filled 2 scenes from packs/library", gapfill.summary(got))
        self.assertTrue(first.review_required)
        self.assertIn("niche footage pack", first.review_reason)
        self.assertEqual(first.attribution, "Author 1 - Title 1")
        self.assertEqual(first.license, "Public domain (NASA)")
        self.assertEqual(first.moment, {"start": 10.0, "pack": "water"})
        self.assertTrue(0.55 <= first.relevance_score <= 1.0)

    def test_a_pack_clip_is_used_once_across_scenes_and_the_next_scene_falls_through(self):
        only = entry(1, unit((0, 1.0)))
        lib = _FakeLibrary([{"id": "yt:LIBRARY0001@4", "url": "https://www.youtube.com/watch?v=LIBRARY0001&t=35",
                             "read_url": "https://r2/lib.mp4", "subject_key": "lake powell"}], self.work)
        jobs = [job(0), job(2)]
        results = [None, None, None]
        with Shelves(water=shelf([only])):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = gapfill.fill_empty(jobs, results, self.work, library=lib, indices=[0, 2])
        self.assertEqual((got["pack"], got["library"]), (1, 1))
        self.assertEqual(sorted(a.moment_key for a in results if a), sorted([only.asset_id, "yt:LIBRARY0001@4"]))

    def test_a_failed_download_gives_the_claim_back_and_the_next_clip_is_tried(self):
        bad = entry(1, unit((0, 1.0)), src="nasa-BAD")
        good = entry(2, unit((0, 1.0), (4, 0.2)), src="nasa-GOOD")

        def download(url, dest, timeout=0, headers=None):
            if "nasa-BAD" in url:
                raise RuntimeError("404")
            return fake_download(url, dest)
        results = [None]
        with Shelves(water=shelf([bad, good])), mock.patch.object(storage, "download", side_effect=download):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = gapfill.fill_empty([job(0)], results, self.work)
        self.assertEqual(got["pack"], 1)
        self.assertEqual(results[0].moment_key, good.asset_id)

    def test_a_line_that_names_its_place_and_has_a_library_clip_of_it_goes_to_the_library(self):
        pack_clip = entry(1, unit((0, 1.0)))
        lib = _FakeLibrary([{"id": "yt:POWELL000001@4", "url": "https://www.youtube.com/watch?v=POWELL000001&t=35",
                             "read_url": "https://r2/powell.mp4", "subject_key": "lake powell"}], self.work)
        specific = job(0, scene_intent={"specificity": "location", "generic_ok": False, "locations": ["Lake Powell"]})
        generic = job(1, scene_intent={"specificity": "generic", "generic_ok": True})
        results = [None, None]
        with Shelves(water=shelf([pack_clip, entry(2, unit((0, 1.0), (4, 0.1)), src="nasa-TWO")])):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = gapfill.fill_empty([specific, generic], results, self.work, library=lib)
        self.assertEqual((got["pack"], got["library"]), (1, 1))
        self.assertTrue(results[0].moment_key.startswith("yt:POWELL"))            # the place itself, not a general clip
        self.assertTrue(results[1].moment_key.startswith("pack:"))

    def test_a_line_that_names_its_place_needs_a_closer_fit(self):
        close = entry(1, unit((0, 1.0), (4, 0.55)))                                # cosine ~0.88
        specific = job(0, scene_intent={"specificity": "event", "generic_ok": False})
        with Shelves(water=shelf([close])), mock.patch.multiple(config, PACKS_MIN_SIMILARITY=0.8,
                                                                  PACKS_SPECIFIC_EXTRA=0.1):
            packs.use_job(title="drought", brief={"event": "drought"})
            self.assertAlmostEqual(packs.threshold(specific), 0.9)
            self.assertAlmostEqual(packs.threshold(job(0)), 0.8)
            results = [None, None]
            got = gapfill.fill_empty([specific, job(1)], results, self.work)
        self.assertIsNone(results[0])                                               # 0.88 < 0.8 + 0.1
        self.assertIsNotNone(results[1])
        self.assertEqual((got["pack"], got["left"]), (1, 1))

    def test_the_rung_stands_aside_for_people_graphics_youtube_only_and_the_flag(self):
        e = entry(1, unit((0, 1.0)))
        with Shelves(water=shelf([e])):
            packs.use_job(title="drought", brief={"event": "drought"})
            for j in (job(0, subject_type="person"), job(0, visual_type="map")):
                self.assertFalse(packs.usable(j), j)
            self.assertTrue(packs.usable(job(0)))
            self.assertFalse(packs.usable(job(0), youtube_only=True))
            with mock.patch.object(config, "PACKS_FILL", False):
                self.assertFalse(packs.usable(job(0)))
                results = [None]
                got = gapfill.fill_empty([job(0)], results, self.work)
                self.assertEqual(got["pack"], 0)
            with mock.patch.object(media, "youtube_only", return_value=True):
                results = [None]
                got = gapfill.fill_empty([job(0)], results, self.work)
                self.assertEqual(got["pack"], 0)                                    # the user's choice of sources

    def test_licence_notes_ride_on_the_clip_and_a_claim_free_job_takes_none_unverified(self):
        by = entry(1, unit((0, 1.0)), klass="cc-by-sa", license_url="https://creativecommons.org/licenses/by-sa/4.0/")
        lib = entry(2, unit((0, 1.0)), klass="unverified", source="library", src="lib-x")
        results = [None]
        with Shelves(water=shelf([by])):
            packs.use_job(title="drought", brief={"event": "drought"})
            gapfill.fill_empty([job(0)], results, self.work)
        self.assertIn("CC BY-SA", results[0].review_reason)
        self.assertEqual(results[0].license, "CC BY-SA 4.0")
        results = [None]
        with Shelves(water=shelf([lib])):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = gapfill.fill_empty([job(0)], results, self.work, require_cc=True)
            self.assertEqual(got["pack"], 0)
            got = gapfill.fill_empty([job(0)], results, self.work, require_cc=False)
            self.assertEqual(got["pack"], 1)
            self.assertIn("licence unverified", results[0].review_reason)

    def test_nothing_is_read_and_nothing_changes_without_a_shelf(self):
        lib = _FakeLibrary([{"id": "yt:LIBRARY0001@4", "url": "https://www.youtube.com/watch?v=LIBRARY0001&t=35",
                             "read_url": "https://r2/lib.mp4", "subject_key": "lake powell"}], self.work)
        results = [None]
        with mock.patch.object(packs, "available", return_value=False), \
                mock.patch.object(packs, "load", side_effect=AssertionError("no shelf to read")):
            got = gapfill.fill_empty([job(0)], results, self.work, library=lib)
        self.assertEqual((got["pack"], got["library"]), (0, 1))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class QualityGate(unittest.TestCase):
    """A broken scene found at render time is repaired from the pack too (src/quality.py)."""

    @classmethod
    def setUpClass(cls):
        from tests import test_quality as tq
        cls.tq = tq
        tq.setUpModule()
        cls.clip = tq._clip("pack4.mp4", 4.0)

    @classmethod
    def tearDownClass(cls):
        cls.tq.tearDownModule()

    def test_an_empty_scene_in_the_render_copy_gets_a_pack_clip_and_the_report_says_so(self):
        tq = self.tq
        e = entry(1, unit((0, 1.0)), seconds=4.0)
        doc = tq.doc_of([tq.scene(0, tq.video(self.clip, 4.0)), tq.scene(1, dict(tq.EMPTY)),
                         tq.scene(2, tq.video(tq._clip("pack3.mp4", 3.0), 3.0))])
        doc["scenes"][1]["semanticMetadata"].update(subject="Lake Powell", subjectType="place",
                                                    intent="a severe drought", searchQuery="drought")
        work = tempfile.mkdtemp()

        def download(url, dest, timeout=0, headers=None):
            shutil.copyfile(self.clip, dest)
            return dest
        with Shelves(water=shelf([e])), tq._offline_quality(), tq._Ctx(ladder=True), \
                mock.patch.object(storage, "download", side_effect=download), \
                mock.patch.object(media, "youtube_only", return_value=False), \
                mock.patch.object(config, "FALLBACK_PARALLEL", 1):
            packs.use_job(title="drought", brief={"event": "drought"})
            gate = quality.Gate(doc, work)
            gate.before_render()
            report = gate.finish()
        s = doc["scenes"][1]
        self.assertEqual(s["media"]["type"], "video")
        self.assertEqual(s["semanticMetadata"]["assetId"], e.asset_id)
        self.assertEqual(s["semanticMetadata"]["moment"]["start"], 10.0)
        self.assertIn("pack_", os.path.basename(s["media"]["url"]))
        self.assertEqual([r["how"] for r in report["repairs"]], ["a niche pack clip"])
        self.assertEqual(report["fixed"]["replaced"], 1)
        self.assertEqual(gapfill.find_repeats(doc), [])
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- #
# PACKS_FIRST: pack clips before any search, for the lines they fit best
# --------------------------------------------------------------------------- #

class FirstPass(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.patches = [mock.patch.object(storage, "download", side_effect=fake_download),
                        mock.patch.object(filters, "playable_video", return_value=True),
                        mock.patch.object(media, "youtube_only", return_value=False),
                        mock.patch.object(config, "PACKS_FIRST", True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.work, ignore_errors=True)

    def _shelf(self, n=6):
        return shelf([entry(k, unit((0, 1.0), (4, 0.02 * k)), src=f"nasa-S{k}") for k in range(n)])

    def test_it_does_nothing_unless_switched_on(self):
        with Shelves(water=self._shelf()), mock.patch.object(config, "PACKS_FIRST", False):
            packs.use_job(title="drought", brief={"event": "drought"})
            self.assertEqual(packs.first_pass([job(5)], self.work), {})
        with mock.patch.object(packs, "available", return_value=False):
            self.assertEqual(packs.first_pass([job(5)], self.work), {})

    def test_it_takes_only_lines_a_pack_fits_never_the_hook_a_person_or_an_exact_place(self):
        jobs = [job(0, hook=True), job(1), job(2, subject_type="person"),
                job(3, scene_intent={"specificity": "event", "generic_ok": False}),
                job(4, intent="a crowded city street", query="city"), job(5), job(6), job(7)]
        with Shelves(water=self._shelf(8)), mock.patch.object(config, "PACKS_FIRST_MAX_SHARE", 0.5):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = packs.first_pass(jobs, self.work)
        self.assertEqual(sorted(got), [1, 5, 6, 7])                                # not 0 (hook), 2, 3 or 4 (a city street)
        self.assertTrue(all(a.moment_key.startswith("pack:water:") for a in got.values()))
        self.assertEqual(len({a.moment_key for a in got.values()}), len(got))         # no clip twice

    def test_it_takes_at_most_its_share_of_the_video_the_best_fits_first(self):
        jobs = [job(i) for i in range(1, 11)]
        jobs[2]["intent"] = jobs[2]["query"] = "a drought and a dam"                 # a weaker fit than a plain drought
        with Shelves(water=self._shelf(10)), mock.patch.object(config, "PACKS_FIRST_MAX_SHARE", 0.3):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = packs.first_pass(jobs, self.work)
        self.assertEqual(len(got), 3)
        self.assertNotIn(3, got)

    def test_a_clean_licence_needs_no_review_and_a_credit_does(self):
        jobs = [job(1), job(5)]
        pd = entry(1, unit((0, 1.0)), src="nasa-PD")
        by = entry(2, unit((0, 1.0), (4, 0.1)), src="wm-BY", klass="cc-by", source="wikimedia")
        with Shelves(water=shelf([pd, by])), mock.patch.object(config, "PACKS_FIRST_MAX_SHARE", 1.0):
            packs.use_job(title="drought", brief={"event": "drought"})
            got = packs.first_pass(jobs, self.work)
        by_class = {a.moment_key: a for a in got.values()}
        self.assertFalse(by_class[pd.asset_id].review_required)
        self.assertTrue(by_class[by.asset_id].review_required)
        self.assertIn("credit", by_class[by.asset_id].review_reason)

    def test_do_plan_leaves_the_taken_lines_out_of_every_search(self):
        segs, shots = _plan(10)
        e = [entry(k, unit((0, 1.0), (4, 0.02 * k)), src=f"nasa-S{k}") for k in range(1, 4)]
        seen = {}

        def source_many(jobs_, work, **kw):
            seen["asked"] = sorted(j["index"] for j in jobs_)             # numbered 0..n-1 again (handler.local)
            return [MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=SRCH{j['index']:07d}",
                               local_path=f"/w/s{j['index']}.mp4", moment_key=f"yt:SRCH{j['index']:07d}@1")
                    for j in sorted(jobs_, key=lambda j: j["index"])]

        def build(segments, shots_, assets, **kw):
            seen["assets"] = list(assets)
            raise _Built()
        with Shelves(water=shelf(e)), \
                mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"), \
                mock.patch.object(handler.storage, "download", side_effect=fake_download), \
                mock.patch.object(handler.renderer, "probe_duration", return_value=30.0), \
                mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]), \
                mock.patch.object(handler.transcribe, "segment_words", return_value=segs), \
                mock.patch.object(handler.director, "story_brief", return_value=dict(BRIEF)), \
                mock.patch.object(handler.director, "plan", return_value=(shots, "ai", [])), \
                mock.patch.object(handler.library.Library, "load", return_value=None), \
                mock.patch.object(handler.fanout, "enabled_for", return_value=False), \
                mock.patch.object(handler.pools, "source_by_subject", return_value={}), \
                mock.patch.object(handler.media, "source_many", side_effect=source_many), \
                mock.patch.object(handler.media, "rescue_fill", return_value={}), \
                mock.patch.object(handler.timeline, "build", side_effect=build), \
                mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False), \
                mock.patch.object(config, "SUBJECT_POOLS", True), mock.patch.object(config, "HOOK_SECONDS", 6.0), \
                mock.patch.object(config, "PACKS_FIRST_MAX_SHARE", 0.5):
            with self.assertRaises(_Built):
                handler.do_plan({"audio_url": "vo.mp3", "project_id": "", "video_style": ""}, self.work,
                                handler.Reporter(""))
            niches = list(packs.JOB.get("niches") or [])
        handler.vision.set_story({})
        assets = seen["assets"]
        packed = [i for i, a in enumerate(assets) if a is not None and a.moment_key.startswith("pack:")]
        self.assertEqual(len(packed), 3)
        self.assertTrue(all(i >= 2 for i in packed))                                 # never the hook (the first 6 s)
        self.assertEqual(len(seen["asked"]), 7)                                      # the other lines, and only those
        self.assertTrue(all(a is not None for a in assets))
        self.assertEqual(sum(1 for a in assets if a.moment_key.startswith("yt:SRCH")), 7)
        self.assertIn("water", niches)                                               # read off the story
        gapfill.reset()


class _Built(Exception):
    pass


BRIEF = {"kind": "explainer", "summary": "The reservoir and the drought", "event": "Lake Powell drought", "year": 2026,
         "recent": False, "places": ["Lake Powell"], "people": [], "hookBeats": [0], "cast": [], "sections": []}


def _plan(n):
    from src.transcribe import Segment, Word
    segs, shots = [], []
    for i in range(n):
        words = [Word(text=w, start=i * 3.0 + k * 0.4, end=i * 3.0 + k * 0.4 + 0.3)
                 for k, w in enumerate(f"A severe drought line number {i}".split())]
        segs.append(Segment(text=f"A severe drought line number {i}", start=i * 3.0, end=(i + 1) * 3.0, words=words))
        shots.append({"query": "drought", "visualType": "footage", "subject": "Lake Powell", "subjectType": "place",
                      "intent": "a severe drought", "overlay": None})
    return segs, shots


# --------------------------------------------------------------------------- #
# Switches
# --------------------------------------------------------------------------- #

class Switches(unittest.TestCase):
    def test_defaults_the_gap_rung_on_and_pack_first_off(self):
        self.assertTrue(config.PACKS_FILL)
        self.assertFalse(config.PACKS_FIRST)
        self.assertEqual(config.PACKS_NICHES, "")

    def test_a_job_may_set_them_for_itself(self):
        for key in ("PACKS_FILL", "PACKS_FIRST", "PACKS_NICHES", "PACKS_MIN_SIMILARITY", "PACKS_FIRST_MIN_SIMILARITY",
                    "PACKS_FIRST_MAX_SHARE", "PACKS_LICENSES"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE, key)
        prev = handler._apply_config({"PACKS_FIRST": "1", "PACKS_NICHES": "water,nature", "PACKS_MIN_SIMILARITY": "0.3"})
        try:
            self.assertTrue(config.PACKS_FIRST)
            self.assertEqual(packs.forced_niches(), ["water", "nature"])
            self.assertEqual(config.PACKS_MIN_SIMILARITY, 0.3)
        finally:
            handler._restore_config(prev)
        self.assertFalse(config.PACKS_FIRST)


if __name__ == "__main__":
    unittest.main()
