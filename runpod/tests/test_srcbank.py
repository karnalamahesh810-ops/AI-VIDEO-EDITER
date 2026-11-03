"""The source bank (src/srcbank.py) and the original-source gate for every style: offline, no network, no model.
Searches, downloads, reviews and the matching model are stubbed; ffmpeg makes one small synthetic source."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from src import config, gapfill, media, srcbank, stormdesk

HAVE_FFMPEG = bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


def job(i, text, seconds=4.0, place="Las Vegas", subject="flooding", query="", vt="footage", st="place"):
    return {"index": i, "query": query or f"{place} {subject}", "seconds": seconds, "start": 5.0 * i,
            "visual_type": vt, "fallbacks": [], "prompt": "", "intent": text, "subject_type": st,
            "subject": subject, "place": place, "event_window": "", "recency": "", "scene_intent": None,
            "hook": i == 0, "context": text}


class _On(unittest.TestCase):
    """SOURCE_BANK and ORIGINALS_ONLY on, a clean bank state, no ledger, no R2."""

    def setUp(self):
        self._p = [mock.patch.object(config, "SOURCE_BANK", True),
                   mock.patch.object(config, "ORIGINALS_ONLY", True),
                   mock.patch.object(config, "SOURCE_BANK_CACHE", False),
                   mock.patch.object(config, "CHANNEL_MAX_SHARE", 0.0)]
        for p in self._p:
            p.start()
        srcbank.reset()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()
        srcbank.reset()


def piece(src, n, a, b, take=None, te=None, ok=True, desc="flooded street with cars", q=0.8, vec=None):
    p = srcbank.Piece(src=src, n=n, start=a, end=b, take=take if take is not None else n,
                      take_end=te if te is not None else b, ok=ok, desc=desc, quality=q)
    p.vec = vec
    return p


def bank_with(sources):
    """Install sources (list of (Source, [Piece])) as the bank's state."""
    st = srcbank._STATE
    st["sources"] = []
    for k, (s, ps) in enumerate(sources):
        for p in ps:
            p.src = k
        s.pieces = ps
        st["sources"].append(s)
    return [p for s in st["sources"] for p in s.pieces]


class Compilation(unittest.TestCase):
    def test_titles(self):
        yes = ["Top 10 Floods Caught On Camera", "FLASH FLOOD COMPILATION 2026", "Best of storm chasing 2025",
               "Most Insane Floods Ever Caught On Camera", "25 Craziest Moments Caught On Camera",
               "Hurricane montage"]
        no = ["NEW MASSIVE Floods Just SLAMMED Las Vegas", "Flooding caught on camera in Henderson",
              "Heavy rain, flooding and hail hit parts of Las Vegas valley", "Lake Mead rises for the 10th day",
              "Top Gun Maverick premiere", "Why the dam matters"]
        for t in yes:
            self.assertTrue(stormdesk.compilation_title(t), t)
        for t in no:
            self.assertFalse(stormdesk.compilation_title(t), t)


class OriginalsEveryStyle(unittest.TestCase):
    def test_blocklist_for_any_style(self):
        with mock.patch.object(config, "ORIGINALS_ONLY", True):
            names = stormdesk.blocklist({"video_style": "documentary"})
        self.assertIn("Desert Rat Explorations", names)
        self.assertIn("TERRA DOSSIER", names)
        self.assertIn(stormdesk.AGGREGATORS, names)
        with mock.patch.object(config, "ORIGINALS_ONLY", False):
            self.assertEqual(stormdesk.blocklist({"video_style": "documentary"}), [])

    def test_own_channel_allowed(self):
        with mock.patch.object(config, "ORIGINALS_ONLY", True):
            names = stormdesk.blocklist({"video_style": "documentary", "channel_title": "Weather Watch USA"})
        self.assertEqual(stormdesk.blocked("Weather Watch USA", "x", names), "")
        self.assertTrue(stormdesk.blocked("Storm-HQ", "x", names))

    def test_usable_title_rejects_compilations(self):
        with mock.patch.object(config, "ORIGINALS_ONLY", True):
            self.assertFalse(media._usable_title("Flood compilation from Las Vegas", "Some Channel", 1.78))
        with mock.patch.object(config, "ORIGINALS_ONLY", False):
            self.assertTrue(media._usable_title("Flood compilation from Las Vegas", "Some Channel", 1.78))

    def test_description_credit_is_a_reupload_for_any_style(self):
        info = {"title": "Las Vegas flood", "channel": "Random Clips", "width": 1920, "height": 1080,
                "description": "Video credit: KTNV. No copyright infringement intended."}
        media.set_blocked_channels(["x"])
        try:
            with mock.patch.object(config, "ORIGINALS_ONLY", True), mock.patch.object(config, "FIELD_FOOTAGE_ONLY", False):
                self.assertIn("re-upload", media.meta_reject(info, "Las Vegas flood"))
        finally:
            media.set_blocked_channels([])


class Queries(_On):
    def test_event_story_round_robin(self):
        lines = [job(0, "a", place="Las Vegas"), job(1, "b", place="Las Vegas"), job(2, "c", place="Lake Mead"),
                 job(3, "d", place="Henderson", query="Henderson flooding rescue")]
        story = {"is_event": True, "year": 2026, "word": "flooding", "recency": "month"}
        with mock.patch.object(config, "ALLOW_VERTICAL", True):
            qs = srcbank.queries(lines, story, 40)
        texts = [q for q, _v, _r in qs]
        # every topic's first search comes before any topic's second
        firsts = texts[:3]
        self.assertEqual({t.split(" flooding")[0] for t in firsts}, {"Las Vegas", "Lake Mead", "Henderson"})
        self.assertTrue(any(t.endswith("#shorts") for t in texts))
        self.assertIn("Henderson flooding rescue", texts)
        self.assertEqual(len(srcbank.queries(lines, story, 5)), 5)

    def test_general_story(self):
        lines = [job(0, "a", place="", subject="Hoover Dam"), job(1, "b", place="", subject="Hoover Dam")]
        qs = srcbank.queries(lines, {"is_event": False}, 10)
        self.assertEqual(qs[0][0], "Hoover Dam footage")
        self.assertTrue(all(r == "" for _q, _v, r in qs))


class Gate(_On):
    def test_gate(self):
        places = {"nevada"}
        ok = {"id": "a" * 11, "title": "Flooding near Stewart and Pecos", "channel": "News 3 Las Vegas",
              "duration": 120}
        self.assertEqual(srcbank.gate(ok, places, "Las Vegas"), "")
        self.assertEqual(srcbank.gate(dict(ok, title="Top 10 floods caught on camera"), places), "compilation")
        self.assertEqual(srcbank.gate(dict(ok, channel="Storm-HQ"), places), "re-upload channel")
        self.assertEqual(srcbank.gate(dict(ok, channel="WBFF FOX45 Baltimore", title="Flooding"), places),
                         "a station from another place")
        self.assertEqual(srcbank.gate(dict(ok, duration=3600), places), "too long")
        with mock.patch.object(config, "ALLOW_VERTICAL", False):
            self.assertEqual(srcbank.gate(dict(ok, aspect=9 / 16), places), "vertical")
        with mock.patch.object(config, "ALLOW_VERTICAL", True):
            self.assertEqual(srcbank.gate(dict(ok, aspect=9 / 16), places), "")

    def test_shortlist_merges_ranks_and_caps_channels(self):
        lines = [job(i, "flood", place="Las Vegas") for i in range(6)]

        def search(q, variant, recency, cc):
            rows = [{"id": f"st{k:09d}", "title": f"Las Vegas flooding report {k}", "channel": "News 3 Las Vegas",
                     "duration": 90} for k in range(6)]
            rows.append({"id": "re000000001", "title": "Las Vegas flood", "channel": "Storm-HQ", "duration": 90})
            rows.append({"id": "cr000000001", "title": "My video of the Las Vegas flood", "channel": "Joe Smith",
                         "duration": 40})
            return rows

        with mock.patch.object(config, "SOURCE_BANK_PER_CHANNEL", 3):
            got = srcbank.shortlist(lines, {"is_event": True, "word": "flooding", "year": 2026}, False,
                                    search=search)
        ids = [s.id for s in got]
        self.assertNotIn("re000000001", ids)
        self.assertIn("cr000000001", ids)
        self.assertEqual(sum(1 for s in got if s.channel == "News 3 Las Vegas"), 3)
        self.assertEqual(srcbank._STATE["rejects"]["re-upload channel"], 1)


class Pieces(unittest.TestCase):
    def test_takes_split_and_short_shots_dropped(self):
        s = srcbank.Source(id="x" * 11)
        ps = srcbank.pieces_from_cuts(s, [4.0, 4.8, 20.0], 30.0)
        # 0.3-4.0 (one piece), 4.0-4.8 dropped (short), 4.8-20.0 -> 3 pieces, 20.0-29.7 -> 2 pieces
        self.assertEqual(len(ps), 6)
        self.assertEqual([p.n for p in ps], list(range(1, 7)))
        self.assertTrue(all(p.end - p.start >= 1.2 for p in ps))
        long_take = [p for p in ps if p.take == ps[1].take]
        self.assertEqual(len(long_take), 3)
        self.assertTrue(all(p.take_end == 20.0 for p in long_take))

    def test_piece_cap(self):
        s = srcbank.Source(id="y" * 11)
        with mock.patch.object(config, "SOURCE_BANK_MAX_PIECES", 10):
            ps = srcbank.pieces_from_cuts(s, [], 600.0)
        self.assertEqual(len(ps), 10)
        self.assertGreater(ps[-1].start, 500)


class Review(unittest.TestCase):
    def test_parse(self):
        s = srcbank.Source(id="z" * 11, title="t", channel="c")
        s.pieces = [piece(-1, 1, 0, 4, ok=None, desc=""), piece(-1, 2, 4, 8, ok=None, desc=""),
                    piece(-1, 3, 8, 12, ok=None, desc="")]
        raw = ('```json\n{"compilation": false, "shots": [{"n": 1, "ok": true, "d": "cars in floodwater", "q": 0.9},'
               ' {"n": 2, "ok": false, "why": "anchor"}]}\n```')
        with mock.patch.object(srcbank, "_sheet_images", return_value=["AAAA"]):
            self.assertTrue(srcbank.review(s, "story", ask=lambda m: raw))
        self.assertTrue(s.pieces[0].ok)
        self.assertEqual(s.pieces[0].desc, "cars in floodwater")
        self.assertFalse(s.pieces[1].ok)
        self.assertEqual(s.pieces[1].why, "anchor")
        self.assertFalse(s.pieces[2].ok)              # never answered: never placed
        self.assertEqual(s.pieces[2].why, "unanswered")

    def test_no_answer(self):
        s = srcbank.Source(id="z" * 11)
        s.pieces = [piece(-1, 1, 0, 4, ok=None)]
        with mock.patch.object(srcbank, "_sheet_images", return_value=["AAAA"]):
            self.assertFalse(srcbank.review(s, "", ask=lambda m: None))

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
    def test_sheet_images(self):
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "f.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=256x144",
                            "-frames:v", "1", f], check=True)
            ps = [piece(-1, n, 0, 1) for n in range(1, 8)]
            for p in ps:
                p.frame = f
            imgs = srcbank._sheet_images(ps)
            self.assertEqual(len(imgs), 2)            # 6 a grid
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Matching(_On):
    def test_model_ranks_then_words(self):
        s = srcbank.Source(id="a" * 11, title="Henderson flooding rescue", channel="News 3 Las Vegas")
        pieces = bank_with([(s, [piece(0, 1, 0, 5, desc="firefighters rescue a driver"),
                                  piece(0, 2, 5, 10, desc="hail on a car roof")])])
        lines = [job(0, "Firefighters pulled a driver from the water"), job(1, "Then the hail came")]
        raw = '{"lines": [{"i": 0, "shots": [["0.1", 0.9]]}]}'
        got = srcbank.match(lines, pieces, "story", ask=lambda m: raw)
        self.assertEqual(got[0][0], ("0.1", 0.9))
        self.assertTrue(any(pid == "0.2" for pid, _s in got[1]))     # word overlap: "hail"

    def test_unknown_ids_ignored(self):
        s = srcbank.Source(id="a" * 11, title="t", channel="c")
        pieces = bank_with([(s, [piece(0, 1, 0, 5)])])
        got = srcbank.match([job(0, "x")], pieces, "", ask=lambda m: '{"lines": [{"i": 0, "shots": [["9.9", 1]]}]}')
        self.assertFalse(any(pid == "9.9" for pid, _s in got[0]))


class Placement(_On):
    def _two_sources(self, vec=False):
        a = srcbank.Source(id="A" * 11, title="Las Vegas flood", channel="News 3 Las Vegas")
        b = srcbank.Source(id="B" * 11, title="Las Vegas flood video", channel="Joe Smith")
        pa = [piece(0, k, 10.0 * k, 10.0 * k + 6, vec=(np.eye(8)[k % 8] if vec else None)) for k in range(1, 7)]
        pb = [piece(1, k, 10.0 * k, 10.0 * k + 6, vec=(np.eye(8)[(k + 3) % 8] if vec else None)) for k in range(1, 7)]
        return bank_with([(a, pa), (b, pb)])

    def test_never_same_source_twice_in_a_row(self):
        pieces = self._two_sources()
        lines = [job(i, "flood") for i in range(6)]
        srcbank._STATE["total"] = 600.0
        ranks = {j["index"]: [(p.pid, 0.9) for p in pieces] for j in lines}
        got = srcbank.place(lines, ranks, pieces)
        self.assertEqual(len(got), 6)
        order = [srcbank._STATE["sources"][got[i][0].src].id for i in range(6)]
        self.assertTrue(all(order[k] != order[k + 1] for k in range(5)), order)

    def test_share_cap_and_relax(self):
        pieces = self._two_sources()
        lines = [job(i, "flood", seconds=4.0) for i in range(8)]
        srcbank._STATE["total"] = 100.0              # caps: max(12, 8) = 12 s a source -> 2 shots of 4.3 s each
        ranks = {j["index"]: [(p.pid, 0.9) for p in pieces] for j in lines}
        got = srcbank.place(lines, ranks, pieces)
        per = {}
        for i, (p, a, b, f) in got.items():
            per[p.src] = per.get(p.src, 0.0) + (b - a)
        self.assertTrue(all(v <= 12.0 + 1e-6 for v in per.values()), per)
        self.assertEqual(len(got), 4)

    def test_no_moment_twice(self):
        s = srcbank.Source(id="C" * 11, title="t", channel="c")
        one = piece(0, 1, 0.0, 30.0, take=1, te=30.0)
        pieces = bank_with([(s, [one])])
        srcbank._STATE["total"] = 1000.0
        srcbank._STATE["used"] = {s.id: [(0.12, 5.0)]}
        lines = [job(0, "x")]
        self.assertEqual(srcbank.place(lines, {0: [(one.pid, 0.9)]}, pieces), {})

    def test_lookalike_skipped(self):
        v = np.ones(8) / np.sqrt(8)
        a = srcbank.Source(id="D" * 11, title="t", channel="c1")
        b = srcbank.Source(id="E" * 11, title="t", channel="c2")
        pa, pb = piece(0, 1, 0, 6, vec=v), piece(1, 1, 0, 6, vec=v)
        pieces = bank_with([(a, [pa]), (b, [pb])])
        srcbank._STATE["total"] = 1000.0
        lines = [job(0, "x"), job(1, "y")]
        got = srcbank.place(lines, {0: [(pa.pid, 0.9)], 1: [(pb.pid, 0.9)]}, pieces)
        self.assertEqual(list(got), [0])
        self.assertEqual(srcbank._STATE["stats"]["lookalikeSkipped"], 1)

    def test_archive_ranks_below_fresh_in_a_story_about_now(self):
        fresh = srcbank.Source(id="F" * 11, title="t", channel="c1")
        old = srcbank.Source(id="G" * 11, title="t", channel="c2", archive=True)
        pf, po = piece(0, 1, 0, 6), piece(1, 1, 0, 6)
        pieces = bank_with([(fresh, [pf]), (old, [po])])
        srcbank._STATE["total"] = 1000.0
        srcbank._STATE["story"] = {"is_event": True}
        got = srcbank.place([job(0, "x")], {0: [(po.pid, 0.9), (pf.pid, 0.8)]}, pieces)
        self.assertIs(got[0][0], pf)

    def test_floor(self):
        s = srcbank.Source(id="H" * 11, title="t", channel="c")
        p = piece(0, 1, 0, 6)
        pieces = bank_with([(s, [p])])
        srcbank._STATE["total"] = 1000.0
        self.assertEqual(srcbank.place([job(0, "x")], {0: [(p.pid, 0.2)]}, pieces), {})

    def test_ledger_moment_skipped(self):
        s = srcbank.Source(id="I" * 11, title="t", channel="c")
        p = piece(0, 1, 0, 6)
        pieces = bank_with([(s, [p])])
        srcbank._STATE["total"] = 1000.0
        from src import ledger
        with mock.patch.object(ledger, "on", return_value=True), \
                mock.patch.object(ledger, "moment_used", return_value=True):
            self.assertEqual(srcbank.place([job(0, "x")], {0: [(p.pid, 0.9)]}, pieces), {})


class EndToEnd(_On):
    """fill() with every network and model step stubbed: lines filled, assets shaped for the timeline."""

    def test_fill(self):
        work = tempfile.mkdtemp()
        try:
            lines = [job(i, f"line {i} about the flooded street", seconds=3.5) for i in range(10)]

            def search(q, v, r, cc):
                return [{"id": f"vid{k:08d}", "title": f"Las Vegas flooding street {k}", "channel": f"Creator {k}",
                         "duration": 120} for k in range(4)]

            def fake_download(src, w):
                src.upload_date = "20261030"
                return os.path.join(w, f"{src.id}.mp4")

            def fake_scan(src, folder):
                return srcbank.pieces_from_cuts(src, [12.0 * k for k in range(1, 10)], 120.0)

            def fake_review(src, story_line="", ask=None):
                for p in src.pieces:
                    p.ok, p.desc, p.quality = True, "flooded street", 0.8
                return True

            def fake_cut(p, a, b, j):
                return srcbank.asset_for(p, a, b, j, os.path.join(work, f"cut_{p.pid}_{a}.mp4"))

            with mock.patch.object(srcbank, "download", side_effect=fake_download), \
                    mock.patch.object(srcbank, "scan", side_effect=fake_scan), \
                    mock.patch.object(srcbank, "review", side_effect=fake_review), \
                    mock.patch.object(srcbank, "cut", side_effect=fake_cut), \
                    mock.patch.object(srcbank, "_embed"), \
                    mock.patch.object(config, "SOURCE_BANK_MODEL_MATCH", False):
                got = srcbank.fill(lines, work, story_line="Las Vegas floods", search=search)
            self.assertEqual(len(got), 10)
            a = got[0]
            self.assertEqual(a.kind, "video")
            self.assertTrue(a.moment["bank"])
            self.assertIn("end", a.moment)
            self.assertEqual(a.judged_by, "sheet")
            self.assertTrue(a.moment_key.startswith("yt:vid"))
            idents = [x.identity for x in got.values()]
            self.assertEqual(len(idents), len(set(idents)))
            st = srcbank.stats()
            self.assertEqual(st["filled"], 10)
            self.assertEqual(st["sources"], 4)
            self.assertGreaterEqual(st["sourcesUsed"], 2)
            self.assertEqual(len(srcbank.ids()), 4)
            # consecutive lines never share a source
            vids = [got[i].moment_key.split("@")[0] for i in range(10)]
            self.assertTrue(all(vids[k] != vids[k + 1] for k in range(9)))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_bank_failure_never_fails_the_video(self):
        with mock.patch.object(srcbank, "build", side_effect=RuntimeError("boom")):
            self.assertEqual(srcbank.fill([job(0, "x")], tempfile.gettempdir()), {})
        self.assertIn("boom", srcbank.stats()["error"])

    def test_fill_gaps_uses_unused_shots_and_respects_neighbours(self):
        a = srcbank.Source(id="J" * 11, title="Las Vegas flood", channel="c1")
        b = srcbank.Source(id="K" * 11, title="Las Vegas flood", channel="c2")
        pieces = bank_with([(a, [piece(0, 1, 0, 6), piece(0, 2, 10, 16)]), (b, [piece(1, 1, 0, 6)])])
        srcbank._STATE["total"] = 1000.0
        jobs = [job(i, "flood") for i in range(3)]
        neighbour = media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={'J' * 11}&t=50",
                                     moment_key=f"yt:{'J' * 11}@50", moment={"start": 50.0})
        results = [neighbour, None, None]

        def fake_cut(p, a_, b_, j):
            return srcbank.asset_for(p, a_, b_, j, f"/tmp/{p.pid}.mp4")

        with mock.patch.object(srcbank, "cut", side_effect=fake_cut), \
                mock.patch.object(config, "SOURCE_BANK_MODEL_MATCH", False):
            got = srcbank.fill_gaps(jobs, results)
        self.assertEqual(sorted(got), [1, 2])
        self.assertEqual(got[1].moment_key.split("@")[0], f"yt:{'K' * 11}")     # not next to J
        self.assertEqual(srcbank.stats()["gapFilled"], 2)


class RepeatRules(unittest.TestCase):
    def _bank(self, vid, a, b):
        return media.MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(a)}",
                                local_path=f"/tmp/{vid}_{a}.mp4", moment_key=f"yt:{vid}@b{int(a * 10)}",
                                moment={"start": a, "end": b, "bank": True})

    def test_bank_ranges(self):
        vid = "L" * 11
        u = gapfill.Used()
        u.add(0, gapfill.Shot.of_asset(self._bank(vid, 10.0, 14.0)))
        # a distinct moment 6 s later, two lines away: not a repeat (the old 30 s rule would say it is)
        self.assertEqual(u.why_not(2, gapfill.Shot.of_asset(self._bank(vid, 20.0, 24.0))), "")
        # overlapping: the same moment
        self.assertTrue(u.why_not(2, gapfill.Shot.of_asset(self._bank(vid, 13.0, 17.0))))
        # the next line: never the same source
        self.assertTrue(u.why_not(1, gapfill.Shot.of_asset(self._bank(vid, 40.0, 44.0))))

    def test_variety_exempts_bank_moments(self):
        vid = "M" * 11
        jobs = [{"index": i, "start": 6.0 * i, "seconds": 4.0} for i in range(6)]
        results = [self._bank(vid, 10.0 * i, 10.0 * i + 4) if i % 2 == 0 else
                   self._bank("N" * 11, 10.0 * i, 10.0 * i + 4) for i in range(6)]
        with mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2), \
                mock.patch.object(config, "SAME_VIDEO_GAP_SECONDS", 120.0), \
                mock.patch.object(config, "CHANNEL_MAX_SHARE", 0.0):
            out = media.variety_violations(jobs, results)
        self.assertEqual(out, {})
        plain = [media.MediaAsset(kind="video", source="youtube",
                                  url=f"https://www.youtube.com/watch?v={vid}&t={10 * i}",
                                  moment={"start": 10.0 * i}) for i in range(6)]
        with mock.patch.object(config, "MAX_MOMENTS_PER_VIDEO", 2), \
                mock.patch.object(config, "SAME_VIDEO_GAP_SECONDS", 120.0), \
                mock.patch.object(config, "CHANNEL_MAX_SHARE", 0.0):
            self.assertTrue(media.variety_violations(jobs, plain))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg")
class Scan(unittest.TestCase):
    def test_scan_finds_the_cuts(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "src.mp4")
            # three 3-second shots of different colours (hard cuts at 3 s and 6 s)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=3",
                            "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=3", "-f", "lavfi", "-i",
                            "testsrc=s=320x180:d=3", "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
                            "-r", "30", "-pix_fmt", "yuv420p", path], check=True)
            s = srcbank.Source(id="O" * 11, path=path)
            ps = srcbank.scan(s, d)
            self.assertEqual(len(ps), 3, [(p.start, p.end) for p in ps])
            self.assertAlmostEqual(ps[1].start, 3.0, delta=0.2)
            self.assertTrue(all(os.path.exists(p.frame) for p in ps))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
