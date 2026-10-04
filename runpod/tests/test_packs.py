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
        with Shelves(water=shelf([short, longer])), mock.patch.object(config, "SHOT_MAX_SECONDS", 0.0):
            hits = packs.find("a drought", ["water"], seconds=6.0, min_similarity=0.5)
            self.assertEqual([h.entry.id for h in hits], [longer.id])             # 2 s / 0.6 < 6 s: it would freeze
            hits = packs.find("a drought", ["water"], seconds=3.0, min_similarity=0.5)
            self.assertEqual({h.entry.id for h in hits}, {short.id, longer.id})   # (slowed to 0.67x)

    def test_with_the_shot_cap_a_clip_is_never_slowed_to_fill_its_line(self):
        # SHOT_MAX_SECONDS on (src/shotcap.py): the clip holds the line at real speed. `seconds` carries
        # the usual pad (media.SEQ_SHOT_PAD, 0.5 s) on top of the line, as packs.pick asks.
        short = entry(7, unit((0, 1.0)), seconds=2.0)
        longer = entry(8, unit((0, 1.0), (4, 0.1)), seconds=8.0)
        with Shelves(water=shelf([short, longer])), mock.patch.object(config, "SHOT_MAX_SECONDS", 7.0):
            hits = packs.find("a drought", ["water"], seconds=3.0, min_similarity=0.5)
            self.assertEqual([h.entry.id for h in hits], [longer.id])             # a 2.5 s line: 2 s would be slowed
            hits = packs.find("a drought", ["water"], seconds=2.5, min_similarity=0.5)
            self.assertEqual({h.entry.id for h in hits}, {short.id, longer.id})   # a 2 s line: real speed

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


# --------------------------------------------------------------------------- #
# Building a pack (src/packbuild.py, scripts/build_pack.py)
# --------------------------------------------------------------------------- #

from src import libstore, packbuild  # noqa: E402


class Licences(unittest.TestCase):
    """The licensing rule: only footage we may show. Each case is a real example or its shape."""

    def wm(self, slug, short, **extra):
        meta = {"License": {"value": slug}, "LicenseShortName": {"value": short},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}
        meta.update({k: {"value": v} for k, v in extra.items()})
        return packbuild.wikimedia_verdict(meta)

    def test_commons_keeps_public_domain_cc0_and_cc_by_and_drops_nc_nd_and_the_unknown(self):
        self.assertEqual(self.wm("pd", "Public domain")["class"], "pd")
        self.assertEqual(self.wm("pd", "Public Domain")["class"], "pd")
        self.assertEqual(self.wm("cc0", "CC0")["class"], "cc0")
        self.assertEqual(self.wm("cc-by-4.0", "CC BY 4.0")["class"], "cc-by")
        self.assertEqual(self.wm("cc-by-3.0", "CC BY 3.0")["class"], "cc-by")
        self.assertEqual(self.wm("cc-by-sa-4.0", "CC BY-SA 4.0")["class"], "cc-by-sa")
        self.assertEqual(self.wm("", "CC BY-SA 3.0 igo")["class"], "cc-by-sa")
        for slug, short in (("cc-by-nc-4.0", "CC BY-NC 4.0"), ("cc-by-nd-3.0", "CC BY-ND 3.0"),
                            ("cc-by-nc-sa-3.0", "CC BY-NC-SA 3.0"), ("", "GFDL 1.2"), ("", "No restrictions"),
                            ("", "")):
            v = self.wm(slug, short)
            self.assertFalse(v["ok"], (slug, short))
            self.assertTrue(v["why"])
        self.assertIn("NC", self.wm("cc-by-nc-4.0", "CC BY-NC 4.0")["why"])
        self.assertFalse(self.wm("pd", "Public domain", NonFree="true")["ok"])               # a non-free file is never kept

    def test_the_internet_archive_needs_an_explicit_public_domain_or_cc0_licence_url(self):
        self.assertEqual(packbuild.archive_verdict("https://creativecommons.org/publicdomain/mark/1.0/")["class"], "pd")
        self.assertEqual(packbuild.archive_verdict("http://creativecommons.org/publicdomain/zero/1.0/")["class"], "cc0")
        self.assertEqual(packbuild.archive_verdict("http://creativecommons.org/licenses/publicdomain/")["class"], "pd")
        for bad in (None, "", [], "https://creativecommons.org/licenses/by/4.0/",
                    "https://creativecommons.org/licenses/by-nc-nd/3.0/",
                    ["https://creativecommons.org/publicdomain/mark/1.0/", "https://creativecommons.org/licenses/by/4.0/"]):
            self.assertFalse(packbuild.archive_verdict(bad)["ok"], bad)                      # a collection name proves nothing

    def test_nasa_is_kept_unless_its_own_text_carries_a_notice_or_a_third_party_credit(self):
        ok = lambda desc, title="A title": packbuild.nasa_verdict({"title": title, "description": desc})
        self.assertTrue(ok("Drought over the west.\nCredit: NASA/JPL-Caltech")[0])
        self.assertTrue(ok("Footage of a reservoir.\nVideo credit: NASA/Ames Research Center\nA short video")[0])
        self.assertTrue(ok("Reservoirs.\nCredit: Video production and NISAR animations: NASA/JPL-Caltech; "
                           "Methane animations: NASA's Scientific Visualization Studio")[0])
        self.assertTrue(ok("A lake timelapse. Music courtesy Moby\nCredit: NASA's Goddard Space Flight Center")[0])
        self.assertTrue(ok("Music Provided by Universal Production Music: The Butterfly\nCredit: NASA/GSFC")[0])
        self.assertTrue(ok("No credit line at all, just water.")[0])
        for desc, why in (("Movie Footage courtesy of Focus Features Asteroid City\nCredit: NASA", "third-party"),
                          ("Additional imagery and footage courtesy of ISRO, U.S. National Park Service", "third-party"),
                          ("Credit: NASA/Bill Ingalls", "third-party"),
                          ("A lake. (c) 2019 Some Agency", "notice"), ("Footage © Reuters", "notice"),
                          ("This clip is copyrighted by its maker", "notice"),
                          ("Shot by a crew; licensed from Getty Images", "notice")):
            keep, reason = ok(desc)
            self.assertFalse(keep, desc)
            self.assertIn(why, reason)

    def test_only_the_three_sources_may_be_fetched(self):
        for url in ("https://images-assets.nasa.gov/video/x/x~large.mp4", "https://upload.wikimedia.org/a/b.webm",
                    "https://ia800000.us.archive.org/1/items/x/x.mp4", "https://archive.org/download/x/x.mp4"):
            self.assertEqual(packbuild.check_host(url), url)
        for url in ("https://www.youtube.com/watch?v=ABCDEFGHIJK", "https://www.shutterstock.com/x.mp4",
                    "https://evilarchive.org/x.mp4", "https://nasa.gov.evil.com/x.mp4", "file:///etc/passwd", ""):
            with self.assertRaises(ValueError):
                packbuild.check_host(url)
        self.assertEqual(packbuild.check_host("https://pub-1.r2.dev/a.mp4", extra=["pub-1.r2.dev"]),
                         "https://pub-1.r2.dev/a.mp4")


class Cutting(unittest.TestCase):
    def test_segments_are_whole_shots_of_four_to_ten_seconds_split_evenly_when_longer(self):
        got = packbuild.plan_segments(60.0, [3.0, 12.0, 14.0, 40.0], lo=4, hi=10, target=8, trim=0.25, per_source=99)
        # 0-3 s too short; 3-12 s one 8.5 s clip; 12-14 too short; 14-40 s is 25.5 s -> 4 pieces; 40-60 s 19.5 s -> 3 pieces
        self.assertEqual(len(got), 1 + 4 + 3)
        self.assertEqual(got[0], (3.25, 8.5))
        self.assertTrue(all(4 <= length <= 10 for _s, length in got))
        starts = [s for s, _l in got]
        self.assertEqual(starts, sorted(starts))
        for (s1, l1), (s2, _l2) in zip(got, got[1:]):
            self.assertLessEqual(s1 + l1, s2 + 1e-6)                                         # never overlapping

    def test_a_single_long_take_gives_a_few_clips_spread_over_the_video(self):
        got = packbuild.plan_segments(600.0, [], lo=4, hi=10, target=8, per_source=6)
        self.assertEqual(len(got), 6)
        self.assertLess(got[0][0], 10)
        self.assertGreater(got[-1][0], 560)                                                    # the whole video, not the start
        self.assertEqual(packbuild.plan_segments(3.0, [], per_source=6), [])                  # nothing usable in a 3 s file
        self.assertEqual(packbuild.plan_segments(20.0, [3.0, 6.0, 9.0, 12.0, 15.0, 18.0], per_source=6), [])  # rapid cutting

    def test_the_filter_makes_sixteen_by_nine_never_upscales_and_caps_the_frame_rate(self):
        plain = packbuild.video_filter(1920, 1080, 30)
        self.assertNotIn("crop", plain)
        self.assertIn("scale=min(1920\\,iw):-2", plain)
        self.assertIn("crop=trunc(ih*16/9/2)*2:ih", packbuild.video_filter(3840, 1920, 30))        # 2:1 data movies
        self.assertIn("crop=iw:trunc(iw*9/16/2)*2", packbuild.video_filter(1440, 1080, 30))        # 4:3
        self.assertNotIn("fps=30", plain)
        self.assertIn("fps=30", packbuild.video_filter(1920, 1080, 59.94))
        self.assertTrue(plain.endswith("format=yuv420p"))

    def test_the_nasa_file_list_gives_the_large_rendition_then_medium_never_the_master_first(self):
        urls = ["http://images-assets.nasa.gov/video/X/X~orig.mp4", "http://images-assets.nasa.gov/video/X/X~small.mp4",
                "http://images-assets.nasa.gov/video/X/X~medium.mp4", "http://images-assets.nasa.gov/video/X/X~large.mp4",
                "http://images-assets.nasa.gov/video/X/X.srt", "http://images-assets.nasa.gov/video/X/X~thumb.jpg"]
        self.assertEqual(packbuild.pick_nasa_rendition(urls), "https://images-assets.nasa.gov/video/X/X~large.mp4")
        self.assertEqual(packbuild.pick_nasa_rendition(urls[:3]), "https://images-assets.nasa.gov/video/X/X~medium.mp4")
        self.assertEqual(packbuild.pick_nasa_rendition(urls[:2]), "https://images-assets.nasa.gov/video/X/X~orig.mp4")
        self.assertEqual(packbuild.pick_nasa_rendition(["http://x.nasa.gov/a.srt"]), "")


def nasa_item(nid, title, desc, center="GSFC"):
    return {"href": f"https://images-assets.nasa.gov/video/{nid}/collection.json",
            "data": [{"nasa_id": nid, "title": title, "description": desc, "center": center, "media_type": "video",
                      "keywords": []}]}


def commons_page(title, slug, short, w=1920, h=1080, size=12_000_000, mime="video/webm", artist="<a href='/u'>Jane Doe</a>",
                 **extra):
    meta = {"License": {"value": slug}, "LicenseShortName": {"value": short},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0"},
            "Artist": {"value": artist}, "ObjectName": {"value": title},
            "ImageDescription": {"value": f"<p>{title}: drought and a reservoir</p>"}}
    meta.update({k: {"value": v} for k, v in extra.items()})
    return {"title": f"File:{title}.webm", "imageinfo": [{
        "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{title.replace(' ', '_')}.webm",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title.replace(' ', '_')}.webm",
        "size": size, "width": w, "height": h, "mime": mime, "extmetadata": meta}]}


class FakeHttp:
    """Http.get_json over canned answers: the same answer to every query, so duplicates are exercised."""

    def __init__(self, nasa=(), commons=(), archive=(), files=None):
        self.nasa, self.commons, self.archive, self.files = list(nasa), list(commons), list(archive), files or {}
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append(url)
        if url.startswith(packbuild.NASA_SEARCH):
            return {"collection": {"items": self.nasa}}
        if url.startswith(packbuild.COMMONS_API):
            return {"query": {"pages": {str(i): p for i, p in enumerate(self.commons)}}}
        if url.startswith(packbuild.ARCHIVE_SEARCH):
            return {"response": {"docs": self.archive}}
        if url in self.files:
            return self.files[url]
        raise RuntimeError(f"no answer for {url}")


def sample_http():
    return FakeHttp(
        nasa=[nasa_item("GSFC_DROUGHT_OK", "Megadroughts Projected for American West",
                        "Drought and reservoir levels across the west.\nCredit: NASA/Goddard Space Flight Center"),
              nasa_item("KSC_FOCUS", "Drought footage", "Reservoir drought.\nMovie Footage courtesy of Focus Features"),
              nasa_item("ARC_MARS", "Mars Helicopter", "A helicopter flies on Mars."),
              nasa_item("HQ_NOTICE", "Dam and reservoir", "Reservoir and dam footage (c) 2019 Some Agency")],
        commons=[commons_page("Lake Mead drought pd", "pd", "Public domain"),
                 commons_page("Reservoir cc0", "cc0", "CC0"),
                 commons_page("Dam drought by", "cc-by-4.0", "CC BY 4.0"),
                 commons_page("Drought reservoir sa", "cc-by-sa-4.0", "CC BY-SA 4.0"),
                 commons_page("Drought nc", "cc-by-nc-4.0", "CC BY-NC 4.0"),
                 commons_page("Reservoir gfdl", "", "GFDL 1.2"),
                 commons_page("Reservoir nonfree", "pd", "Public domain", NonFree="true"),
                 commons_page("Mars rover", "pd", "Public domain", ImageDescription="<p>A rover on Mars</p>"),
                 commons_page("Reservoir picture", "pd", "Public domain", mime="image/png")],
        archive=[{"identifier": "usbr_dam_film", "title": "Dam construction film", "description": "A reservoir and dam",
                  "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/", "creator": ["Bureau"]},
                 {"identifier": "prelinger_drought", "title": "Drought and water", "description": "irrigation",
                  "licenseurl": "http://creativecommons.org/publicdomain/zero/1.0/"},
                 {"identifier": "by_licensed", "title": "Reservoir by", "description": "reservoir dam",
                  "licenseurl": "https://creativecommons.org/licenses/by/4.0/"},
                 {"identifier": "prelinger_no_url", "title": "Drought film", "description": "reservoir drought"},
                 {"identifier": "coffee_ad", "title": "Folgers Coffee Commercial", "description": "coffee",
                  "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"}])


class DryRun(unittest.TestCase):
    def setUp(self):
        self.guards = [mock.patch.object(packbuild, "download_capped", side_effect=AssertionError("a dry run downloads nothing")),
                       mock.patch.object(packs.requests, "get", side_effect=AssertionError("no web here")),
                       mock.patch.object(packs, "available", return_value=False)]
        for g in self.guards:
            g.start()

    def tearDown(self):
        for g in reversed(self.guards):
            g.stop()

    def test_it_lists_what_it_would_fetch_with_the_licence_of_each_and_downloads_nothing(self):
        http = sample_http()
        out = packbuild.run("water", dry_run=True, http=http, max_clips=5)
        self.assertTrue(out["ok"] and out["dryRun"])
        self.assertEqual(out["found"]["nasa"]["found"], 4)
        self.assertEqual(out["found"]["nasa"]["licence"], 2)                              # the Focus Features credit, the notice
        self.assertEqual(out["found"]["nasa"]["off topic"], 1)                             # Mars
        self.assertEqual(out["licences"]["nasa"], {"pd": 1})
        self.assertEqual(out["found"]["wikimedia"]["licence"], 3)                         # NC, GFDL, non-free
        self.assertEqual(out["licences"]["wikimedia"], {"pd": 1, "cc0": 1, "cc-by": 1, "cc-by-sa": 1})
        self.assertEqual(out["found"]["archive"]["licence"], 2)                           # CC BY, no URL at all
        self.assertEqual(out["found"]["archive"]["off topic"], 1)                         # the coffee advertisement
        self.assertEqual(out["licences"]["archive"], {"pd": 1, "cc0": 1})                # explicit PD / CC0 only
        self.assertEqual(out["candidates"], 1 + 4 + 2)
        self.assertEqual(len(out["planned"]), out["wouldTry"])
        self.assertTrue(all(r["licenseClass"] in ("pd", "cc0", "cc-by", "cc-by-sa") for r in out["planned"]))
        self.assertEqual({r["source"] for r in out["planned"]}, {"nasa", "wikimedia", "archive"})
        self.assertNotIn("GSFC_DROUGHT_OK drought nc", json.dumps(out))
        json.dumps(out)                                                                    # a handler result: all JSON

    def test_a_credit_is_stored_for_cc_by_and_the_licence_with_it(self):
        found = packbuild.discover_wikimedia("water", sample_http())
        by = {c.source_id: c for c in found}
        cc = by["Dam drought by.webm"]
        self.assertEqual((cc.klass, cc.license, cc.license_url), ("cc-by", "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0"))
        self.assertIn("Jane Doe", cc.attribution)
        self.assertIn("CC BY 4.0", cc.attribution)
        self.assertEqual(cc.page_url, "https://commons.wikimedia.org/wiki/File:Dam_drought_by.webm")
        self.assertEqual(by["Lake Mead drought pd.webm"].klass, "pd")
        self.assertNotIn("Drought nc.webm", by)
        self.assertNotIn("Reservoir gfdl.webm", by)
        self.assertNotIn("Reservoir nonfree.webm", by)
        self.assertNotIn("Reservoir picture.webm", by)
        self.assertEqual(len(cc.topics), len(set(cc.topics)))                              # found by several searches, listed once

    def test_the_plan_spreads_over_the_topics_and_skips_what_the_pack_already_has(self):
        out = packbuild.run("water", dry_run=True, http=sample_http(), max_clips=50)
        topics = [r["topic"] for r in out["planned"]]
        self.assertEqual(topics[0], "drought")                                              # one source per topic in turn, nasa first
        self.assertEqual(out["planned"][0]["source"], "nasa")
        d = tempfile.mkdtemp()
        store = packbuild.LocalStore(d)
        store.write_manifest("water", packs.manifest("water", [entry(1, unit((0, 1.0)))],
                                                     sources={"nasa:GSFC_DROUGHT_OK": {"kept": 2}}))
        again = packbuild.run("water", dry_run=True, http=sample_http(), store=store, max_clips=50)
        self.assertEqual(again["existing"], 1)
        self.assertEqual(again["alreadyDone"], 1)
        self.assertNotIn("GSFC_DROUGHT_OK", [r["id"] for r in again["planned"]])           # resumable: a source done is skipped
        shutil.rmtree(d, ignore_errors=True)

    def test_resolve_looks_up_each_items_file_without_downloading(self):
        http = sample_http()
        http.files["https://images-assets.nasa.gov/video/GSFC_DROUGHT_OK/collection.json"] = [
            "http://images-assets.nasa.gov/video/GSFC_DROUGHT_OK/GSFC_DROUGHT_OK~orig.mp4",
            "http://images-assets.nasa.gov/video/GSFC_DROUGHT_OK/GSFC_DROUGHT_OK~large.mp4"]
        http.files["https://archive.org/metadata/usbr_dam_film"] = {"files": [
            {"name": "usbr_dam_film.mp4", "size": "30000000", "height": "480", "width": "640", "length": "300"},
            {"name": "usbr_dam_film_hd.mp4", "size": "80000000", "height": "720", "width": "1280", "length": "300"},
            {"name": "usbr_dam_film_meta.xml", "size": "100"}]}
        out = packbuild.run("water", dry_run=True, resolve=True, http=http, max_clips=60)
        rows = {r["id"]: r for r in out["planned"]}
        self.assertEqual(rows["GSFC_DROUGHT_OK"]["file"], "https://images-assets.nasa.gov/video/GSFC_DROUGHT_OK/GSFC_DROUGHT_OK~large.mp4")
        self.assertEqual(rows["usbr_dam_film"]["file"], "https://archive.org/download/usbr_dam_film/usbr_dam_film_hd.mp4")
        self.assertEqual(rows["usbr_dam_film"]["height"], 720)
        self.assertTrue(rows["Lake Mead drought pd.webm"]["file"].startswith("https://upload.wikimedia.org/"))
        self.assertEqual(rows["Lake Mead drought pd.webm"]["sizeMB"], 12.0)

    def test_an_unknown_niche_or_a_failing_search_is_an_answer_not_a_crash(self):
        self.assertFalse(packbuild.run("nonsense", dry_run=True, http=sample_http())["ok"])

        class Down:
            def get_json(self, url, params=None):
                raise RuntimeError("503")
        out = packbuild.run("water", dry_run=True, http=Down())
        self.assertTrue(out["ok"])
        self.assertEqual((out["candidates"], out["planned"]), (0, []))
        self.assertGreater(out["found"]["nasa"]["errors"], 5)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class Build(unittest.TestCase):
    """A real cut of a synthetic source video; CLIP and the library gate are stubs."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="packbuild_test_")
        cls.src = os.path.join(cls.dir, "source.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=22",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", cls.src], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="packout_")
        self.n = 0
        self.vecs = [unit((0, 1.0)), unit((0, 1.0), (4, 0.2)), unit((1, 1.0))]

        def check(path, kind="video", subject="", event="", known=None, clip=True):
            v = libstore.Verdict(kind=kind)
            v.checked = True
            info = libstore.probe(path)
            v.width, v.height, v.seconds = info["width"], info["height"], info["seconds"]
            import random
            rnd = random.Random(self.n)
            v.hashes = [rnd.getrandbits(64) for _ in range(3)]            # far apart: no duplicates
            v.embedding = [float(x) for x in self.vecs[self.n % len(self.vecs)]]
            self.n += 1
            v.measures["sharpness"] = 40.0
            return v

        def fetch(url, dest, max_bytes, timeout=0):
            shutil.copyfile(self.src, dest)
            return os.path.getsize(dest)
        self.patches = [mock.patch.object(libstore, "check", side_effect=check),
                        mock.patch.object(filters, "has_burned_captions", return_value=False),
                        mock.patch.object(packbuild, "download_capped", side_effect=fetch),
                        mock.patch.object(packs, "_clip", return_value=FakeClip()),
                        mock.patch.object(packs, "available", return_value=False),
                        mock.patch.object(config, "PACKS_SEGMENT_MIN", 4.0)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.out, ignore_errors=True)

    def http(self):
        return FakeHttp(commons=[commons_page("Lake Mead drought pd", "pd", "Public domain")])

    def test_a_build_cuts_checks_uploads_and_lists_the_clips_and_a_second_run_continues(self):
        store = packbuild.LocalStore(self.out)
        out = packbuild.run("water", sources=["wikimedia"], max_clips=2, http=self.http(), store=store, parallel=1)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["added"], out["total"], out["stoppedBy"]), (2, 2, "max_clips"))
        data = store.read_manifest("water")
        pack = packs.Pack.from_manifest("water", data)
        self.assertEqual(len(pack.entries), 2)
        e = pack.entries[0]
        self.assertEqual((e.source, e.license_class, e.topics[0], e.niche), ("wikimedia", "pd", "drought", "water"))
        self.assertTrue(e.id.startswith("wm-Lake_Mead_drought_pd_webm@"))
        self.assertTrue(os.path.isfile(e.url))                                              # a local pack: the clip is a file
        info = libstore.probe(e.url)
        self.assertEqual((info["ok"], info["width"], info["height"]), (True, 1280, 720))   # H.264, not upscaled
        self.assertGreaterEqual(info["seconds"], 4.0)
        self.assertLessEqual(info["seconds"], 10.5)
        self.assertEqual(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                         "-of", "csv=p=0", e.url], capture_output=True, text=True).stdout.strip(), "")  # no sound
        self.assertEqual(e.source_url, "https://commons.wikimedia.org/wiki/File:Lake_Mead_drought_pd.webm")
        self.assertTrue(e.thumb and os.path.isfile(e.thumb))
        self.assertEqual(len(e.phash), 3)
        self.assertEqual(e.checks["topicSim"], 1.0)
        self.assertEqual(data["sources"]["wikimedia:Lake Mead drought pd.webm"]["kept"], 2)
        # the pack works as a shelf: PACKS_DIR reads it, find() fits a drought line to it
        packs.clear_cache()
        with mock.patch.object(config, "PACKS_DIR", self.out), mock.patch.object(packs, "available", return_value=True), \
                mock.patch.object(ledger, "pack_used", return_value=False):
            hits = packs.find("a drought", ["water"], min_similarity=0.5, n=9)
        packs.clear_cache()
        self.assertEqual(len(hits), 2)
        # run again: the source is done, nothing is fetched twice, the 2 clips stay
        again = packbuild.run("water", sources=["wikimedia"], max_clips=5, http=self.http(), store=store, parallel=1)
        self.assertEqual((again["added"], again["total"], again["alreadyDone"]), (0, 2, 1))
        self.assertEqual(len(store.read_manifest("water")["entries"]), 2)

    def test_a_clip_that_fails_the_gate_or_is_not_about_the_niche_is_not_listed(self):
        self.vecs = [unit((4, 1.0)), unit((3, 1.0)), unit((0, 1.0))]                       # (gated out), a city, a drought
        real = libstore.check

        def reject_first(path, **kw):
            v = real(path, **kw)
            if self.n == 1:
                v.bad("frozen frame")
            return v
        with mock.patch.object(libstore, "check", side_effect=reject_first):
            out = packbuild.run("water", sources=["wikimedia"], max_clips=9, http=self.http(), parallel=1,
                                store=packbuild.LocalStore(self.out))
        self.assertEqual(out["added"], 1)
        self.assertEqual(out["rejected"].get("frozen frame"), 1)
        self.assertEqual(out["rejected"].get("not about the niche"), 1)                    # the city fits no water topic
        self.assertEqual(out["topics"], {"drought": 1})

    def test_a_topic_never_takes_more_than_its_quota(self):
        with mock.patch.object(config, "PACKS_TOPIC_QUOTA", 1):
            out = packbuild.run("water", sources=["wikimedia"], max_clips=9, http=self.http(), parallel=1,
                                store=packbuild.LocalStore(self.out))
        self.assertEqual(out["added"], 2)                                                    # drought once, dams once
        self.assertGreaterEqual(out["rejected"].get("topic full", 0), 1)

    def test_a_build_without_the_r2_keys_or_the_model_says_so(self):
        with mock.patch.object(r2_mod(), "library_enabled", return_value=False):
            out = packbuild.run("water", sources=["wikimedia"], http=self.http())
        self.assertFalse(out["ok"])
        self.assertIn("R2", out["error"])
        with mock.patch.object(packs, "_clip", return_value=None):
            out = packbuild.run("water", sources=["wikimedia"], http=self.http(), store=packbuild.LocalStore(self.out))
        self.assertFalse(out["ok"])
        self.assertIn("CLIP", out["error"])


def r2_mod():
    from src import r2
    return r2


class FromTheLibrary(unittest.TestCase):
    def test_unused_unshown_library_clips_are_catalogued_with_their_own_embedding_and_stay_unverified(self):
        def row(i, **kw):
            base = {"id": f"yt:LIB{i:08d}@4", "kind": "video", "saved": True, "bucket": "r2:thumbgenius-library",
                    "read_url": f"https://pub.r2.dev/clips/lib{i}.mp4", "source": "youtube", "subject": f"Lake Mead {i}",
                    "url": f"https://www.youtube.com/watch?v=LIB{i:08d}&t=35", "seconds": 6.5, "width": 1920, "height": 1080,
                    "license": "unverified - you must hold the rights", "analysis": {"embeddingKey": f"embeddings/e{i}.json",
                                                                                      "phash": ["00ff00ff00ff00ff"]}}
            base.update(kw)
            return base
        shown = row(2)
        shown["analysis"] = dict(shown["analysis"], shownIn="project-1")
        lib = type("Lib", (), {})()
        lib.entries = [row(1), shown, row(3, kind="image"), row(4, saved=False), row(5, bucket="video-media"),
                       row(6, analysis={}), row(7), row(8)]
        sidecars = {"embeddings/e1.json": [1.0, 0, 0, 0, 0], "embeddings/e7.json": [0, 0, 0, 1.0, 0],
                    "embeddings/e8.json": [0, 0, 0, 1.0, 0]}

        class H:
            def get_json(self, url, params=None):
                return {"embedding": sidecars[url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1]]}
        with mock.patch.object(libstore, "url_for", side_effect=lambda bucket, key: f"https://pub.r2.dev/{key}"), \
                mock.patch.object(packs, "_clip", return_value=FakeClip()), \
                mock.patch.object(ledger, "on", return_value=False):
            got = packbuild.library_entries("water", lib, H())
        self.assertEqual([e.id for e in got], ["lib-yt_LIB00000001_4@0"])               # not shown, not an image, not removed,
        e = got[0]                                                                          # on R2, with an embedding that fits water
        self.assertEqual((e.source, e.license_class, e.topics, e.niche), ("library", "unverified", ["drought"], "water"))
        self.assertEqual(e.url, "https://pub.r2.dev/clips/lib1.mp4")
        self.assertEqual(e.source_url, "https://www.youtube.com/watch?v=LIB00000001&t=35")
        self.assertEqual(e.asset_id, "pack:water:lib-yt_LIB00000001_4@0")
        self.assertEqual(gapfill._video_of(e.asset_id, e.moment_url), "yt:LIB00000001")     # a moment of its YouTube video


class HandlerAction(unittest.TestCase):
    def test_pack_build_is_an_action_that_touches_no_project(self):
        seen = {}

        def run(niche, **kw):
            seen.update(niche=niche, **kw)
            return {"ok": True, "niche": niche, "added": 3}
        with mock.patch.object(packbuild, "run", side_effect=run), \
                mock.patch.object(handler.storage, "patch_project", side_effect=AssertionError("no project")):
            out = handler.handler({"id": "job-pack", "input": {"action": "pack_build", "niche": "Water", "max_clips": "12",
                                                              "dry_run": True, "sources": ["nasa"]}})
        self.assertEqual((out["ok"], out["action"], out["added"]), (True, "pack_build", 3))
        self.assertEqual((seen["niche"], seen["max_clips"], seen["dry_run"], seen["sources"]), ("Water", 12, True, ["nasa"]))
        self.assertIsNone(seen["library"])
        bad = handler.handler({"id": "job-pack2", "input": {"action": "pack_build", "niche": "nonsense", "dry_run": True}})
        self.assertFalse(bad["ok"])
        self.assertIn("unknown niche", bad["error"])

    def test_the_script_lists_the_niches_and_refuses_a_library_build_without_a_library(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_pack", os.path.join(ROOT, "scripts", "build_pack.py"))
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with mock.patch("sys.stdout"):
            listed = script.main(["--list-niches"])
        self.assertIn("bathtub rings", listed["water"])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            script.main(["--niche", "water", "--sources", "library"])


if __name__ == "__main__":
    unittest.main()
