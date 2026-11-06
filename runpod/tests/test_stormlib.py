"""The footage library (src/stormlib.py, scripts/library_push.py) and the plan pass with it (stormdesk.finish on the pieces engine).
Offline: R2 is a dict, the text model a fake, the clips are made with ffmpeg here. Nothing is uploaded anywhere."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from src import config, srcbank, stormdesk, stormgate, stormledger, stormlib, ytdlp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("library_push", os.path.join(HERE, "scripts", "library_push.py"))
library_push = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(library_push)
DIM = 512


def unit(k):
    v = np.zeros(DIM, np.float32)
    v[k] = 1.0
    return v


_RNG = np.random.default_rng(7)


def shot_vector(k):
    """A shot about axis k, each shot its own picture (identical vectors would be look-alikes to the placement)."""
    noise = np.zeros(DIM, np.float32)
    noise[100:] = _RNG.normal(0, 1, DIM - 100)
    v = unit(k) + noise / np.linalg.norm(noise)
    return v / np.linalg.norm(v)


def fake_embed(texts):
    """A line about "flood" points along axis 1, about "dam" along axis 2; each reject label along its own."""
    out = []
    for t in texts:
        if t in stormlib.REJECT.values():
            out.append(unit(10 + list(stormlib.REJECT.values()).index(t)))
        elif "dam" in t:
            out.append(unit(2))
        else:
            out.append(unit(1))
    return np.stack(out)


def clip(path, seconds=40, sound=True):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"gradients=s=320x180:r=30:d={seconds}"]
    if sound:
        cmd += ["-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:r=48000:a=0.2", "-c:a", "aac", "-ac", "2"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", path], check=True)
    return path


def index_of(sources):
    """stormlib.Index from {id: (meta, [(a, b, axis, text, text_top, face), ...])}."""
    ids, src, emb, a, b, tx, top, fc, cat = [], [], [], [], [], [], [], [], {}
    for k, (vid, (meta, shots)) in enumerate(sources.items()):
        ids.append(vid)
        cat[vid] = {"dur": 100.0, "size": 0, "key": f"sdlib/v1/src/{vid}.mp4", **meta}
        for s in shots:
            src.append(k)
            emb.append(shot_vector(s[2]))
            a.append(s[0]), b.append(s[1]), tx.append(s[3]), top.append(s[4]), fc.append(s[5])
    return stormlib.Index(cat, ids, np.array(src, np.int32), np.stack(emb), a, b, tx, top, fc)


STATION = {"channel": "KSL News", "title": "Lake Mead water level drops"}
STATION2 = {"channel": "KTNV News", "title": "Lake Mead marina closes"}
CREATOR = {"channel": "Drone Dan", "title": "Lake Mead from the air"}


class PrivateBucket(unittest.TestCase):
    def test_off_without_a_bucket_and_off_on_a_public_one(self):
        with mock.patch.object(config, "R2_SDLIB_BUCKET", ""):
            self.assertEqual(stormlib.bucket(), "")
        with mock.patch.object(config, "R2_SDLIB_BUCKET", "thumbgenius-videos"), mock.patch.object(config, "R2_BUCKET", "thumbgenius-videos"):
            self.assertEqual(stormlib.bucket(), "")
        with mock.patch.object(config, "R2_SDLIB_BUCKET", "thumbgenius-library"), mock.patch.object(config, "R2_LIBRARY_BUCKET", "thumbgenius-library"):
            self.assertEqual(stormlib.bucket(), "")
        with mock.patch.object(config, "R2_SDLIB_BUCKET", "footage-private"), mock.patch.object(config, "R2_BUCKET", "a"), mock.patch.object(config, "R2_LIBRARY_BUCKET", "b"):
            self.assertEqual(stormlib.bucket(), "footage-private")

    def test_a_source_comes_by_a_signed_link_to_the_private_bucket(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)

        class Resp:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def iter_content(self, n):
                return [b"x" * 20000]
        with mock.patch.object(config, "R2_SDLIB_BUCKET", "footage-private"), mock.patch.object(config, "R2_BUCKET", "a"), \
                mock.patch("src.r2.presign", return_value="https://signed") as pre:
            got = stormlib.fetch_source("AAAAAAAAAAA", {"key": "sdlib/v1/src/AAAAAAAAAAA.mp4", "size": 20000}, t, get=lambda u: Resp())
        self.assertEqual(pre.call_args.kwargs["bucket"], "footage-private")
        self.assertEqual(got, os.path.join(t, "bank", "AAAAAAAAAAA.mp4"))
        self.assertEqual(os.path.getsize(got), 20000)

    def test_a_short_download_is_tried_again_and_never_kept(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)

        class Resp:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def iter_content(self, n):
                return [b"x" * 10]
        with mock.patch.object(config, "R2_SDLIB_BUCKET", "p"), mock.patch("src.r2.presign", return_value="https://signed"), mock.patch("time.sleep"):
            self.assertEqual(stormlib.fetch_source("AAAAAAAAAAA", {"size": 20000}, t, get=lambda u: Resp()), "")
        self.assertFalse(os.path.exists(os.path.join(t, "bank", "AAAAAAAAAAA.mp4")))


class WhatIsOffered(unittest.TestCase):
    def test_each_rule_of_the_kit(self):
        rx = stormdesk.place_regex({}, {"places": ["Lake Mead"]})
        banned = sorted(stormlib.bad_sources())[0]
        idx = index_of({
            "AAAAAAAAAAA": (STATION, [(10, 16, 1, 0, 0, 0),          # 0 fine
                                      (1, 7, 1, 0, 0, 0),            # 1 an opening
                                      (95, 99, 1, 0, 0, 0),          # 2 an end card
                                      (30, 31, 1, 0, 0, 0),          # 3 a sliver
                                      (40, 46, 1, 0, 0, 0.02),       # 4 a person on camera
                                      (50, 56, 1, 0.5, 0.0, 0),      # 5 text only below a station's crop: fine
                                      (60, 66, 1, 0.5, 0.5, 0),      # 6 text the crop keeps
                                      (70, 76, 1, 0, 0, 0)]),        # 7 in the ledger
            "BBBBBBBBBBB": (CREATOR, [(50, 56, 1, 0.5, 0.0, 0)]),    # 8 a creator's frame is whole: its text counts
            banned: (STATION, [(10, 16, 1, 0, 0, 0)]),               # 9 banned
            "CCCCCCCCCCC": ({"channel": "Fuel For Travel", "title": "Lake Mead vlog"}, [(10, 16, 1, 0, 0, 0)]),    # 10 personality
            "DDDDDDDDDDD": ({"channel": "KSL News", "title": "Lake Powell"}, [(10, 16, 1, 0, 0, 0)]),              # 11 another place
        })
        led = stormledger.Ledger([["AAAAAAAAAAA", 70.0, 76.0]])
        keep, free, why = stormlib.usable(idx, led, rx)
        self.assertEqual([int(i) for i in np.nonzero(keep)[0]], [0, 5])
        self.assertEqual(why["place"], 1)
        self.assertEqual(why["used_or_rejected"], 1)
        self.assertEqual(free[0], (10.3, 15.7))

    def test_the_part_of_a_shot_a_ledger_left_free(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(10, 30, 1, 0, 0, 0)])})
        keep, free, _w = stormlib.usable(idx, stormledger.Ledger([["AAAAAAAAAAA", 12.0, 20.0]]), None)
        self.assertTrue(keep[0])
        self.assertEqual(free[0], (20.0, 29.7))

    def test_a_moment_a_gate_refused_is_never_offered_again(self):
        stormlib.reset()
        self.addCleanup(stormlib.reset)
        idx = index_of({"AAAAAAAAAAA": (STATION, [(10, 16, 1, 0, 0, 0), (40, 46, 1, 0, 0, 0)])})
        stormlib.remember_bad("yt:AAAAAAAAAAA", 10.0, 15.0)
        keep, _f, _w = stormlib.usable(idx, None, None)
        self.assertEqual([int(i) for i in np.nonzero(keep)[0]], [1])

    def test_rejected_labels_beat_the_line_and_stations_rank_first(self):
        idx = index_of({"AAAAAAAAAAA": (CREATOR, [(10, 16, 1, 0, 0, 0)]), "BBBBBBBBBBB": (STATION, [(10, 16, 1, 0, 0, 0)]),
                        "CCCCCCCCCCC": (STATION, [(10, 16, 10, 0, 0, 0)])})      # an anchor at a desk
        keep, free, _w = stormlib.usable(idx, None, None)
        got = stormlib.rank(idx, [{"index": 0, "intent": "flood", "seconds": 4.0}], keep, free, fake_embed)[0]
        self.assertEqual([idx.ids[int(idx.src[i])] for i, _f in got], ["BBBBBBBBBBB", "AAAAAAAAAAA"])
        self.assertGreater(got[0][1], got[1][1])

    def test_a_shot_too_short_for_the_line_is_not_offered(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(10, 13, 1, 0, 0, 0)])})
        keep, free, _w = stormlib.usable(idx, None, None)
        self.assertEqual(stormlib.rank(idx, [{"index": 0, "intent": "flood", "seconds": 4.5}], keep, free, fake_embed)[0], [])


class Fill(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t, True)
        srcbank.reset()
        stormlib.reset()
        self.addCleanup(srcbank.reset)
        self.src = clip(os.path.join(self.t, "master.mp4"))
        self.fetched = []

    def fetch(self, vid, meta, work):
        self.fetched.append(vid)
        os.makedirs(os.path.join(work, "bank"), exist_ok=True)
        out = os.path.join(work, "bank", vid + ".mp4")
        shutil.copy(self.src, out)
        return out

    def jobs(self, n):
        return [{"index": i, "intent": "flood", "context": f"line {i}", "seconds": 3.0, "visual_type": "footage"} for i in range(n)]

    def test_lines_filled_only_placed_sources_fetched_and_a_lines_shot_is_a_bank_shot(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(5, 15, 1, 0, 0, 0), (17, 28, 1, 0, 0, 0)]),
                        "BBBBBBBBBBB": (STATION2, [(5, 15, 1, 0, 0, 0), (17, 28, 1, 0, 0, 0)]),
                        "CCCCCCCCCCC": (STATION, [(5, 15, 2, 0, 0, 0)])})        # only ever about dams: never placed, never fetched
        got = stormlib.fill(self.jobs(4), self.t, index=idx, embed=fake_embed, fetch=self.fetch)
        self.assertEqual(sorted(got), [0, 1, 2, 3])
        self.assertEqual(sorted(self.fetched), ["AAAAAAAAAAA", "BBBBBBBBBBB"])
        a = got[0]
        self.assertTrue(os.path.isfile(a.local_path))
        self.assertTrue(a.moment["bank"])
        self.assertTrue(a.pool["library"])
        self.assertEqual(a.channel in ("KSL News", "KTNV News"), True)
        self.assertEqual(stormlib.report()["filled"], 4)
        # every shot its own frames, and never the same source on two lines in a row
        ids = [got[i].url.split("v=")[1][:11] for i in range(4)]
        self.assertTrue(all(x != y for x, y in zip(ids, ids[1:])))

    def test_a_used_moment_is_not_placed(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(5, 15, 1, 0, 0, 0)]), "BBBBBBBBBBB": (STATION2, [(5, 15, 1, 0, 0, 0)])})
        led = stormledger.Ledger([["AAAAAAAAAAA", 5.0, 15.0]])
        got = stormlib.fill(self.jobs(1), self.t, index=idx, embed=fake_embed, fetch=self.fetch, led=led)
        self.assertIn("BBBBBBBBBBB", got[0].url)

    def test_a_creators_channel_stops_at_two_shots_before_anything_is_fetched(self):
        idx = index_of({"AAAAAAAAAAA": (CREATOR, [(5, 10, 1, 0, 0, 0), (20, 25, 1, 0, 0, 0), (30, 35, 1, 0, 0, 0)]),
                        "BBBBBBBBBBB": (CREATOR, [(5, 10, 1, 0, 0, 0), (20, 25, 1, 0, 0, 0)]),
                        "CCCCCCCCCCC": (STATION, [(5, 30, 2, 0, 0, 0)])})
        got = stormlib.fill(self.jobs(5), self.t, index=idx, embed=fake_embed, fetch=self.fetch)
        self.assertLessEqual(len(got), 2)

    def test_a_source_that_will_not_fetch_gives_way(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(5, 15, 1, 0, 0, 0)]), "BBBBBBBBBBB": (STATION2, [(5, 15, 1, 0, 0, 0)])})

        def fetch(vid, meta, work):
            return "" if vid == "AAAAAAAAAAA" else self.fetch(vid, meta, work)
        got = stormlib.fill(self.jobs(1), self.t, index=idx, embed=fake_embed, fetch=fetch)
        self.assertIn("BBBBBBBBBBB", got[0].url)

    def test_no_library_fills_nothing(self):
        with mock.patch.object(stormlib, "load", return_value=None):
            self.assertEqual(stormlib.fill(self.jobs(2), self.t), {})

    def test_it_never_raises(self):
        with mock.patch.object(stormlib, "load", side_effect=RuntimeError("no")):
            self.assertEqual(stormlib.fill(self.jobs(2), self.t), {})

    def test_the_bank_keeps_the_librarys_sources_in_their_place(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(5, 15, 1, 0, 0, 0)])})
        got = stormlib.fill(self.jobs(1), self.t, index=idx, embed=fake_embed, fetch=self.fetch)
        self.assertEqual(len(got), 1)
        with mock.patch.object(srcbank, "shortlist", return_value=[srcbank.Source(id="ZZZZZZZZZZZ", why="")]), \
                mock.patch.object(srcbank, "download", return_value=""):
            srcbank.build(self.jobs(6), self.t)
        self.assertEqual([s.id for s in srcbank._STATE["sources"]], ["AAAAAAAAAAA", "ZZZZZZZZZZZ"])
        self.assertEqual(srcbank.source_path("AAAAAAAAAAA"), os.path.join(self.t, "bank", "AAAAAAAAAAA.mp4"))
        self.assertEqual(srcbank._approved(), [])         # library shots stay out of the bank's paid matching

    def test_a_youtube_search_hit_the_library_holds_is_not_downloaded(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(5, 15, 1, 0, 0, 0)])})
        stormlib.fill(self.jobs(1), self.t, index=idx, embed=fake_embed, fetch=self.fetch)
        self.assertEqual(srcbank.gate({"id": "AAAAAAAAAAA", "title": "x", "channel": "y"}, set()), "already held")

    def test_the_ladders_rung_takes_an_unsure_shot_and_it_lands_on_the_scene(self):
        idx = index_of({"AAAAAAAAAAA": (STATION, [(5, 15, 3, 0, 0, 0)])})          # about neither the line nor a reject label
        with mock.patch.object(stormdesk, "JOB_LEDGER", None):
            self.assertEqual(stormlib.fill(self.jobs(1), self.t, index=idx, embed=fake_embed, fetch=self.fetch), {})
            # (A line a little nearer the shot than any reject label, far below what a first pass would accept.)
            near = lambda texts: np.stack([v if t in stormlib.REJECT.values() else (unit(3) * 0.2 + unit(1) * 0.98) for t, v in zip(texts, fake_embed(texts))])
            got = stormlib.fill_scenes(self.jobs(1), self.t, index=idx, embed=near, fetch=self.fetch)
        self.assertEqual(sorted(got), [0])
        s = {"id": "s", "startFrame": 0, "durationInFrames": 90, "media": {}}
        stormgate.apply_asset(s, got[0], "footage library")
        self.assertTrue(stormgate.has_picture(s))
        self.assertEqual(stormdesk.moment(s, 30)[0], "yt:AAAAAAAAAAA")
        self.assertAlmostEqual(stormdesk.moment(s, 30)[1], got[0].moment["start"])
        self.assertEqual(stormdesk.pause_source_ok(s["semanticMetadata"]["channel"]), True)


class Seeds(unittest.TestCase):
    def test_the_kits_lists_are_in_the_repo(self):
        self.assertGreater(len(stormlib.bad_sources()), 20)
        self.assertGreater(len(stormlib.bad_shots()), 3000)
        self.assertEqual(stormlib.station_modes()["tMsDn7NXPxA"], "news0.68@0.0")
        self.assertIsNone(stormlib.station_modes()["whKiQ25FIuE"])

    def test_a_tuned_crop_wins(self):
        s = {"media": {"type": "video", "url": "/x.mp4"}, "semanticMetadata": {"channel": "KSL News", "sourceUrl": "https://www.youtube.com/watch?v=tMsDn7NXPxA&t=1"}}
        stormdesk.set_modes({"scenes": [s]}, {})
        self.assertEqual(s["stormDesk"]["mode"], "news0.68@0.0")
        s2 = {"media": {"type": "video", "url": "/x.mp4"}, "semanticMetadata": {"channel": "KSL News", "sourceUrl": "https://www.youtube.com/watch?v=whKiQ25FIuE&t=1"}}
        stormdesk.set_modes({"scenes": [s2]}, {})
        self.assertNotIn("mode", s2["stormDesk"])


class FakeR2:
    def __init__(self):
        self.objects = {}
        self.sent = []

    def _creds(self):
        return True

    def list_keys(self, prefix="", bucket="", limit=0):
        return [{"key": k, "size": len(v)} for k, v in self.objects.items() if k.startswith(prefix)]

    def upload(self, path, key, content_type="", deadline=0.0, bucket="", base="", **k):
        self.sent.append(key)
        self.objects[key] = open(path, "rb").read()
        return ""

    def upload_bytes(self, data, key, content_type="", deadline=0.0, bucket="", base="", **k):
        self.objects[key] = data
        return ""


class Push(unittest.TestCase):
    def setUp(self):
        self.kit = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kit, True)
        for d in ("engine/index", "engine/src", "credits"):
            os.makedirs(os.path.join(self.kit, d))
        banned = sorted(stormlib.bad_sources())[0]
        rows = [("AAAAAAAAAAA", "KSL News", "Lake Mead"), ("BBBBBBBBBBB", "Fuel For Travel", "vlog"), (banned, "KSL News", "banned"),
                ("CCCCCCCCCCC", "Drone Dan", "Lake Mead air"), ("DDDDDDDDDDD", "Swenk Family", "from the kit's channels.json")]
        with open(os.path.join(self.kit, "credits", "meta_x.tsv"), "w", encoding="utf-8") as f:
            for vid, ch, title in rows:
                f.write(f"{vid}\t{ch}\t20261001\t1920x1080\t{title}\t100\n")
        for vid, _c, _t in rows + [("EEEEEEEEEEE", "", "")]:      # (one with no credit row)
            np.savez_compressed(os.path.join(self.kit, "engine", "index", vid + ".npz"), emb=np.ones((2, DIM), np.float32), text=np.zeros(2, np.float32),
                                text_top=np.zeros(2, np.float32), a=np.array([1.0, 5.0], np.float32), b=np.array([4.0, 9.0], np.float32),
                                k=np.array([0, 1], np.int32), dur=np.float32(100))
            np.save(os.path.join(self.kit, "engine", "index", vid + ".faces.npy"), np.array([0.0, 0.01], np.float32))
            with open(os.path.join(self.kit, "engine", "src", vid + ".mp4"), "wb") as f:
                f.write(b"v" * 1000)
        self.r2 = FakeR2()

    def run_push(self, upload=True, bucket="footage-private"):
        return library_push.push(self.kit, bucket, upload=upload, r2=self.r2, out=lambda *_a: None)

    def test_a_dry_run_sends_nothing(self):
        rep = self.run_push(upload=False)
        self.assertEqual(rep["sources"], 2)
        self.assertEqual(self.r2.sent, [])
        self.assertEqual(self.r2.objects, {})

    def test_banned_personality_and_uncredited_stay_behind(self):
        rows, left = library_push.plan(self.kit)
        self.assertEqual(sorted(r["id"] for r in rows), ["AAAAAAAAAAA", "CCCCCCCCCCC"])
        self.assertEqual(left["banned"], 1)
        self.assertEqual(left["personality"], 2)
        self.assertEqual(left["no credit row"], 1)

    def test_a_public_bucket_is_refused(self):
        with mock.patch.object(config, "R2_BUCKET", "thumbgenius-videos"):
            with self.assertRaises(SystemExit):
                self.run_push(bucket="thumbgenius-videos")
        self.assertEqual(self.r2.sent, [])

    def test_it_resumes_and_a_pod_reads_what_it_wrote(self):
        rep = self.run_push()
        self.assertEqual((rep["sent"], rep["skipped"]), (2, 0))
        again = self.run_push()
        self.assertEqual((again["sent"], again["skipped"]), (0, 2))
        idx = stormlib.load(lambda k: self.r2.objects.get(k))
        self.assertEqual(sorted(idx.ids), ["AAAAAAAAAAA", "CCCCCCCCCCC"])
        self.assertEqual(len(idx), 4)
        self.assertEqual(idx.emb.shape, (4, DIM))
        self.assertAlmostEqual(float(idx.face[1]), 0.01, 5)
        self.assertEqual(idx.sources["AAAAAAAAAAA"]["kind"], "station")
        self.assertEqual(idx.sources["AAAAAAAAAAA"]["key"], "sdlib/v1/src/AAAAAAAAAAA.mp4")

    def test_a_source_that_fails_stays_out_of_the_index_and_goes_next_time(self):
        real = self.r2.upload
        def flaky(path, key, **k):
            if "CCCCCCCCCCC" in key:
                raise OSError("net")
            return real(path, key, **k)
        with mock.patch.object(self.r2, "upload", side_effect=flaky):
            rep = self.run_push()
        self.assertEqual(rep["failed"], ["CCCCCCCCCCC"])
        self.assertEqual(sorted(json.loads(self.r2.objects[stormlib.CATALOG_KEY])["sources"]), ["AAAAAAAAAAA"])
        self.assertEqual(self.run_push()["sent"], 1)
        self.assertEqual(sorted(json.loads(self.r2.objects[stormlib.CATALOG_KEY])["sources"]), ["AAAAAAAAAAA", "CCCCCCCCCCC"])

    def test_the_pushed_index_has_no_key_and_no_public_link(self):
        self.run_push()
        text = self.r2.objects[stormlib.CATALOG_KEY].decode()
        self.assertNotIn("r2.dev", text)
        self.assertNotIn("X-Amz", text)


class PlanPass(unittest.TestCase):
    """stormdesk.finish on the pieces engine, on real small clips, real YuNet and whatever OCR this machine has."""

    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t, True)
        srcbank.reset()
        stormlib.reset()
        self.a = clip(os.path.join(self.t, "a.mp4"), 12, sound=False)
        self.b = clip(os.path.join(self.t, "b.mp4"), 12, sound=False)

    def scene(self, i, url, vid, ch="KSL News"):
        return {"id": f"s{i}", "startFrame": i * 90, "durationInFrames": 90, "text": f"line {i}", "visualType": "footage",
                "words": [{"text": "13", "start": i * 3.0, "end": i * 3.0 + 0.3}, {"text": "days", "start": i * 3.0 + 0.35, "end": i * 3.0 + 0.7}],
                "media": {"type": "video", "url": url, "source": "youtube", "trimStart": 0.0, "clipSeconds": 12.0,
                          "attribution": "YouTube: Lake Mead level"},
                "semanticMetadata": {"channel": ch, "sourceUrl": f"https://www.youtube.com/watch?v={vid}&t=40", "moment": {"start": 40.0 + i * 20},
                                     "assetId": f"yt:{vid}@{40 + i * 20}"}}

    def finish(self, doc, opts=None, brief=None):
        inp = {"video_style": "storm_desk", "project_id": "", "storm_desk": {"engine": "pieces", "open_clip": False, "pauses": 0, "lookalike": False, "blur_marks": False,
                                                                             "thumbnails": False, "ai_fill_empty": False, **(opts or {})}}
        with mock.patch.object(stormdesk, "_spare_pool", return_value=[]), mock.patch.object(stormlib, "load", return_value=None):
            return stormdesk.finish(doc, inp, brief if brief is not None else {"places": ["Lake Mead"]}, self.t)

    def doc(self, scenes):
        return {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": sum(s["durationInFrames"] for s in scenes), "scenes": scenes, "meta": {}, "overlays": []}

    def test_a_clean_plan_passes_and_carries_the_new_settings(self):
        d = self.doc([self.scene(0, self.a, "AAAAAAAAAAA"), self.scene(1, self.b, "BBBBBBBBBBB"), self.scene(2, self.a, "AAAAAAAAAAA")])
        rep = self.finish(d, {"stat_style": "corner_plate", "stat_size": "large", "stat_color": "#ffffff"})
        self.assertEqual(rep["errors"], [])
        self.assertEqual(rep["emptyShots"], 0)
        self.assertEqual(d["stormDesk"]["statStyle"], {"style": "corner_plate", "size": "large", "color": "#FFFFFF"})
        self.assertEqual(d["stormDesk"]["bgm"], {"lufs": -39.0, "onlyUnderVoice": True})
        self.assertEqual(d["stormDesk"]["clipSound"]["mode"], "off")
        self.assertIn("rounds", rep["shotGates"])
        self.assertEqual(rep["shotGates"]["rejected"], 0)
        self.assertFalse(d["stormDesk"]["looks"]["stamps"])
        stormgate.assert_no_empty(d)

    def test_a_wrong_place_shot_is_replaced_by_a_hold_when_nothing_else_exists(self):
        s = self.scene(1, self.b, "BBBBBBBBBBB")
        s["media"]["attribution"] = "YouTube: Lake Powell houseboats"
        d = self.doc([self.scene(0, self.a, "AAAAAAAAAAA"), s, self.scene(2, self.a, "AAAAAAAAAAA")])
        rep = self.finish(d)
        self.assertTrue(any("another place" in r["why"] for r in rep["channelRule"]))
        self.assertFalse(any("Powell" in str((x.get("media") or {}).get("attribution")) for x in d["scenes"]))
        self.assertEqual(rep["emptyShots"], 0)

    def test_a_shot_with_nothing_goes_down_the_ladder_or_the_video_fails(self):
        s = self.scene(0, "", "AAAAAAAAAAA")
        s["media"] = {}
        d = self.doc([s])
        rep = self.finish(d)
        self.assertEqual(rep["emptyShots"], 1)
        self.assertEqual(rep["emptyList"][0]["at"], 0.0)
        with self.assertRaises(stormgate.EmptyShots):
            stormgate.assert_no_empty(d)

    def test_the_remotion_path_takes_none_of_this(self):
        d = self.doc([self.scene(0, self.a, "AAAAAAAAAAA"), self.scene(1, self.b, "BBBBBBBBBBB")])
        with mock.patch.object(stormgate, "autofix", side_effect=AssertionError("gates ran")), mock.patch.object(stormgate, "ensure_media", side_effect=AssertionError("ladder ran")):
            rep = self.finish(d, {"engine": "remotion"}, brief={"places": ["Somewhere Else"]})
        self.assertNotIn("shotGates", rep)
        self.assertNotIn("emptyList", rep)


if __name__ == "__main__":
    unittest.main()
