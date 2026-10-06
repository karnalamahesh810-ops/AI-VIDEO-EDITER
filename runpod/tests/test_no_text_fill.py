"""
Never a text card as filler (config.NO_TEXT_FILL; the owner, 2026-10-06: a text animation on an empty spot
is "not great"). An empty line gets, after the shot cap's holds and fresh shots: a data look of its figure,
the shot beside it held to the ceiling, another moment of any clip the video shows, a still beside it held
up to NO_TEXT_HOLD_MAX - a text card only when the video has nothing at all to show. The ladder's own rung
before its picture is another moment of a clip the video shows, judged as "shows the line's subject".

Offline: every fetch and judgement is a stub; files are tiny.
"""
import os
import tempfile
import unittest
from unittest import mock

from src import config, gapfill, media, quality, shotcap

FPS = 30


def scene(n, start, secs, media_dict, **kw):
    s = {"id": f"s{n}", "startFrame": int(start * FPS), "durationInFrames": int(secs * FPS),
         "text": kw.pop("text", f"line {n} about the dam"), "media": media_dict, "motion": "none",
         "semanticMetadata": kw.pop("sem", {"subject": "Hoover Dam", "subjectType": "place"}),
         "visualType": kw.pop("visualType", "footage")}
    s.update(kw)
    return s


def photo(url):
    return {"type": "image", "url": url, "source": "web_image"}


def clip(url, secs=None):
    m = {"type": "video", "url": url, "source": "youtube"}
    if secs is not None:
        m["clipSeconds"] = secs
    return m


EMPTY = {"type": "color", "url": "", "source": "none"}


def doc_of(*scenes):
    return {"fps": FPS, "overlays": [], "scenes": list(scenes), "meta": {}}


def lay(*items):
    out, at = [], 0.0
    for n, (m, secs) in enumerate(items):
        out.append(scene(n, at, secs, dict(m)))
        at += secs
    return doc_of(*out)


def quiet(**more):
    base = dict(ANIMATION_FILL=False, HOOK_SECONDS=0.0, NO_TEXT_FILL=True, NO_TEXT_HOLD_MAX=18.0,
                SHOT_MAX_SECONDS=7.0, FALLBACK_MOMENTS=True)
    base.update(more)
    return mock.patch.multiple(config, **base)


class TheLastResort(unittest.TestCase):
    def setUp(self):
        gapfill.reset()
        shotcap.reset()
        self.addCleanup(gapfill.reset)
        self.addCleanup(shotcap.reset)
        p = mock.patch.object(shotcap, "_probe", return_value=0.0)
        p.start()
        self.addCleanup(p.stop)

    def test_a_still_beside_the_line_holds_past_the_ceiling_instead_of_a_text_card(self):
        doc = lay((photo("/w/a.jpg"), 6.0), (EMPTY, 8.0), (clip("/w/b.mp4", 6.0), 6.0))
        with quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["card"], 0)
        self.assertEqual(doc["overlays"], [])
        self.assertEqual(len(doc["scenes"]), 2)
        self.assertLessEqual(doc["scenes"][0]["durationInFrames"] / FPS, 18.0)
        self.assertEqual(doc["scenes"][1]["durationInFrames"] / FPS, 6.0)     # the clip is never stretched

    def test_off_the_same_line_is_a_text_card_as_before(self):
        doc = lay((photo("/w/a.jpg"), 6.0), (EMPTY, 8.0), (clip("/w/b.mp4", 6.0), 6.0))
        with quiet(NO_TEXT_FILL=False):
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["card"], 1)
        self.assertEqual(doc["overlays"][0]["type"], "highlight")

    def test_never_past_the_longest_still_hold_and_never_a_slowed_clip(self):
        doc = lay((photo("/w/a.jpg"), 12.0), (EMPTY, 9.0), (clip("/w/b.mp4", 6.0), 6.0))
        with quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["card"], 1)                       # 12 + 9 s would pass 18 s: nothing else to show
        self.assertEqual([round(s["durationInFrames"] / FPS, 1) for s in doc["scenes"]], [12.0, 9.0, 6.0])

    def test_a_figure_gets_its_data_look_after_the_holds_never_before_them(self):
        doc = lay((clip("/w/a.mp4", 3.0), 3.0), (EMPTY, 5.0), (clip("/w/b.mp4", 3.0), 3.0))
        anim = {"type": "stat", "template": "KT_NUMBER", "value": 40}
        with quiet(), mock.patch.object(gapfill, "graphic_for", return_value=anim) as g:
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["graphic"], 1)
        self.assertEqual(doc["scenes"][1]["animation"], anim)
        self.assertIn("data look", doc["scenes"][1]["reviewReason"])
        g.assert_called()
        # A line its neighbours can hold within the cap keeps the footage: no graphic first.
        doc = lay((clip("/w/a.mp4", 9.0), 3.0), (EMPTY, 2.0), (clip("/w/b.mp4", 9.0), 3.0))
        with quiet(), mock.patch.object(gapfill, "graphic_for", return_value=anim) as g:
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["graphic"]), (1, 0))
        g.assert_not_called()

    def test_with_a_work_dir_another_moment_of_any_clip_comes_before_any_hold_past_the_ceiling(self):
        work = tempfile.mkdtemp()
        # Clips beside the line that cannot be held (each file just covers its own scene); the one two
        # scenes away gives another moment (a clip on the very next scene never does: its video twice).
        doc = lay((clip("https://r2/a.mp4", 3.0), 3.0), (clip("https://r2/b.mp4", 3.0), 3.0), (EMPTY, 6.0),
                  (clip("https://r2/c.mp4", 3.0), 3.0))
        for k, vid in ((0, "AAAAAAAAAAA"), (1, "BBBBBBBBBBB"), (3, "CCCCCCCCCCC")):
            doc["scenes"][k]["semanticMetadata"].update(assetId=f"yt:{vid}", moment={"start": 100.0},
                                                       sourceUrl=f"https://www.youtube.com/watch?v={vid}&t=100")
        fetched = []

        def fetch(vid, out, at, need, title=""):
            path = os.path.join(out, f"{vid}_{int(at)}.mp4")
            open(path, "wb").write(b"x")
            fetched.append((vid, at))
            return path, True, 0
        with quiet(), mock.patch.object(media, "fetch_clean_clip", side_effect=fetch), \
                mock.patch.object(media, "_asset_ok_for", return_value=(True, "")), \
                mock.patch.object(media, "motion_rejects", return_value=""), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(gapfill, "_too_short", return_value=False), \
                mock.patch.object(media.ledger, "moment_used", return_value=False), \
                mock.patch.object(shotcap, "find_moment", return_value=None), \
                mock.patch.object(media, "judge_clip", side_effect=AssertionError("the last resort is not judged")):
            got = gapfill.hold_or_animate(doc, search=True, work=work, laddered=True)
        self.assertEqual((got["card"], got.get("moment")), (0, 1))
        self.assertEqual(doc["scenes"][2]["media"]["type"], "video")
        self.assertIn("nothing checked it", doc["scenes"][2]["reviewReason"])
        self.assertEqual({vid for vid, _at in fetched}, {"AAAAAAAAAAA"})
        self.assertGreaterEqual(abs(fetched[0][1] - 100.0), 30.0)            # never the moment the video shows


class TheMomentRung(unittest.TestCase):
    """gapfill._from_moment: another moment of a clip the video shows, the line's own subject first, judged."""

    def setUp(self):
        self.work = tempfile.mkdtemp()

    def _fetch(self, vid, out, at, need, title=""):
        path = os.path.join(out, f"{vid}_{int(at)}.mp4")
        open(path, "wb").write(b"x")
        return path, True, 0

    def _run(self, donors, judge, job=None, used=None):
        job = job or {"index": 5, "start": 50.0, "seconds": 4.0, "subject": "Hoover Dam", "query": "Hoover Dam",
                      "intent": "the dam's spillway", "context": "the spillway roared"}
        seen = []

        def j(path, jb, label="", source_url=""):
            seen.append((os.path.basename(path), media._RUNG.get()))
            return judge(path)
        with mock.patch.object(media, "fetch_clean_clip", side_effect=self._fetch), \
                mock.patch.object(media, "_asset_ok_for", return_value=(True, "")), \
                mock.patch.object(media, "motion_rejects", return_value=""), \
                mock.patch.object(media, "slop_reason", return_value=""), \
                mock.patch.object(gapfill, "_too_short", return_value=False), \
                mock.patch.object(media.ledger, "moment_used", return_value=False), \
                mock.patch.object(media, "judge_clip", side_effect=j):
            got = gapfill._from_moment(job, used or gapfill.Used(), self.work, 1e12, donors)
        return got, seen

    def test_the_lines_own_subject_first_judged_as_shows_that_subject(self):
        donors = [{"index": 4, "vid": "NEARBYOTHER", "start": 60.0, "subject": "Lake Mead", "title": "lake"},
                  {"index": 20, "vid": "FARSAMESUBJ", "start": 200.0, "subject": "Hoover Dam", "title": "dam"}]
        got, seen = self._run(donors, lambda p: (True, {"score": 0.8, "description": "the dam"}))
        self.assertTrue(got.url.startswith("https://www.youtube.com/watch?v=FARSAMESUBJ"))
        self.assertEqual(seen[0][1], {"label": "Hoover Dam"})
        self.assertEqual(got.relevance_score, 0.8)
        self.assertTrue(got.review_required)

    def test_a_turned_down_moment_tries_the_next_within_the_judge_cap(self):
        donors = [{"index": 1, "vid": "AAAAAAAAAAA", "start": 100.0, "subject": "Hoover Dam", "title": "dam"}]
        calls = []

        def judge(path):
            calls.append(path)
            return (len(calls) >= 3), {"score": 0.8}
        got, _seen = self._run(donors, judge)
        self.assertIsNotNone(got)
        self.assertEqual(len(calls), 3)
        got, _seen = self._run(donors, lambda p: (False, {"score": 0.3}))
        self.assertIsNone(got)

    def test_never_its_video_on_the_next_scene_nor_a_moment_another_scene_shows(self):
        used = gapfill.Used()
        used.add(4, gapfill.Shot(video="yt:AAAAAAAAAAA", start=100.0, at=40.0))
        donors = [{"index": 4, "vid": "AAAAAAAAAAA", "start": 100.0, "subject": "Hoover Dam", "title": "dam"}]
        got, _seen = self._run(donors, lambda p: (True, {"score": 0.8}), used=used)
        self.assertIsNone(got)                     # scene 4 is next to scene 5: the same video would play twice
        used = gapfill.Used()
        used.add(1, gapfill.Shot(video="yt:AAAAAAAAAAA", start=100.0, at=-150.0))
        donors = [{"index": 1, "vid": "AAAAAAAAAAA", "start": 100.0, "subject": "Hoover Dam", "title": "dam"}]
        got, _seen = self._run(donors, lambda p: (True, {"score": 0.8}), used=used)
        self.assertGreaterEqual(abs(got.moment["start"] - 100.0), 30.0)

    def test_the_variety_rules_hold_for_a_judged_moment(self):
        # Its video plays 40 s before this line (under SAME_VIDEO_GAP_SECONDS), or twice already
        # (MAX_MOMENTS_PER_VIDEO): another moment of it would look like the same shot again.
        donors = [{"index": 1, "vid": "AAAAAAAAAAA", "start": 100.0, "subject": "Hoover Dam", "title": "dam"}]
        with mock.patch.multiple(config, SAME_VIDEO_GAP_SECONDS=120.0, MAX_MOMENTS_PER_VIDEO=2):
            used = gapfill.Used()
            used.add(1, gapfill.Shot(video="yt:AAAAAAAAAAA", start=100.0, at=10.0))
            got, _seen = self._run(donors, lambda p: (True, {"score": 0.8}), used=used)
            self.assertIsNone(got)
            used = gapfill.Used()
            used.add(1, gapfill.Shot(video="yt:AAAAAAAAAAA", start=100.0, at=-400.0))
            used.add(9, gapfill.Shot(video="yt:AAAAAAAAAAA", start=300.0, at=400.0))
            got, _seen = self._run(donors, lambda p: (True, {"score": 0.8}), used=used)
            self.assertIsNone(got)
            used = gapfill.Used()
            used.add(1, gapfill.Shot(video="yt:AAAAAAAAAAA", start=100.0, at=-400.0))
            got, _seen = self._run(donors, lambda p: (True, {"score": 0.8}), used=used)
            self.assertIsNotNone(got)

    def test_the_ladder_asks_it_before_its_picture(self):
        order = []
        jobs = [{"index": 0, "query": "q", "seconds": 4.0, "start": 0.0, "visual_type": "footage"},
                {"index": 1, "query": "q", "seconds": 4.0, "start": 4.0, "visual_type": "footage"}]
        results = [media.MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=AAAAAAAAAAA",
                                    moment={"start": 100.0}), None]
        with mock.patch.multiple(config, FALLBACK_MOMENTS=True, FALLBACK_STILLS=True, FALLBACK_FILL=True), \
                mock.patch.object(gapfill, "_from_library", side_effect=lambda *a, **k: order.append("library")), \
                mock.patch.object(gapfill, "_from_reserve", side_effect=lambda *a, **k: order.append("reserve")), \
                mock.patch.object(gapfill, "_from_moment",
                                  side_effect=lambda job, used, work, stop, donors, **k: order.append(
                                      ("moment", [d["vid"] for d in donors]))), \
                mock.patch.object(gapfill, "_from_still", side_effect=lambda *a, **k: order.append("still")), \
                mock.patch("src.packs.usable", return_value=False):
            gapfill.fill_empty(jobs, results, self.work)
        self.assertEqual(order, ["library", "reserve", ("moment", ["AAAAAAAAAAA"]), "still"])


class PlacedPictures(unittest.TestCase):
    def test_a_picture_placed_after_the_plan_gets_a_push_in(self):
        s = scene(0, 0.0, 4.0, dict(EMPTY))
        a = media.MediaAsset(kind="image", source="web_image", url="https://img.example/a.jpg", local_path="/w/a.jpg")
        with mock.patch.multiple(config, NO_TEXT_FILL=True, STILL_MOTION=""):
            gapfill.apply_asset(s, a)
        self.assertEqual(s["motion"], "zoom-in")
        s = scene(0, 0.0, 4.0, dict(EMPTY))
        with mock.patch.multiple(config, NO_TEXT_FILL=True, STILL_MOTION="none"):
            gapfill.apply_asset(s, a)
        self.assertEqual(s["motion"], "none")                       # a style that holds stills still


class TheGate(unittest.TestCase):
    def test_the_gates_last_step_keeps_a_still_beside_it_on_screen_without_removing_a_scene(self):
        doc = lay((photo("https://r2/a.jpg"), 4.0), (EMPTY, 3.0), (clip("https://r2/b.mp4", 3.0), 3.0))
        doc["overlays"] = [{"type": "highlight", "text": "line 1", "startFrame": 4 * FPS, "durationInFrames": 3 * FPS}]
        gate = quality.Gate.__new__(quality.Gate)
        gate.doc = doc
        gate.fixed = quality.Counter()
        with mock.patch.multiple(config, NO_TEXT_FILL=True, STILL_MOTION=""):
            texts = gate.no_empty_scenes()
        self.assertEqual(texts, [])
        self.assertEqual(len(doc["scenes"]), 3)
        self.assertEqual(doc["scenes"][1]["media"]["url"], "https://r2/a.jpg")
        self.assertEqual(doc["scenes"][1]["motion"], "zoom-in")             # a slow push-in, never frozen
        self.assertEqual(doc["scenes"][1]["semanticMetadata"]["borrowedFrom"], "s0")
        self.assertEqual(doc["overlays"], [])                               # the text card over it is gone
        self.assertEqual((gate.fixed["held"], gate.borrowed), (1, {"s1"}))
        doc = lay((clip("https://r2/a.mp4", 4.0), 4.0), (EMPTY, 3.0))
        gate.doc = doc
        with mock.patch.multiple(config, NO_TEXT_FILL=True):
            self.assertEqual(gate.no_empty_scenes(), ["s1"])           # nothing still beside it: its line as text


class BorrowedStills(unittest.TestCase):
    def test_never_a_chain_of_one_picture_down_empty_lines(self):
        doc = lay((photo("https://r2/a.jpg"), 4.0), (EMPTY, 3.0), (EMPTY, 3.0), (EMPTY, 3.0))
        with mock.patch.multiple(config, NO_TEXT_FILL=True, NO_TEXT_HOLD_MAX=18.0):
            got = [gapfill.borrow_still(doc, s) for s in list(doc["scenes"][1:])]
        self.assertEqual(got, [True, False, False])           # the second empty line never borrows a borrowed one

    def test_the_neighbour_under_the_hold_cap_first(self):
        doc = lay((photo("https://r2/long.jpg"), 16.0), (EMPTY, 4.0), (photo("https://r2/short.jpg"), 3.0))
        with mock.patch.multiple(config, NO_TEXT_FILL=True, NO_TEXT_HOLD_MAX=18.0):
            self.assertTrue(gapfill.borrow_still(doc, doc["scenes"][1]))
        self.assertEqual(doc["scenes"][1]["media"]["url"], "https://r2/short.jpg")     # 7 s, not 20 s


class TheFirstLineAsText(unittest.TestCase):
    def test_the_card_over_the_videos_first_line_goes_when_the_line_becomes_text(self):
        # 2026-10-07, the Obama render: the check before the render showed the empty first line as its text
        # look but kept the card the last resort had laid over it (frame 0 was read as -1: "0 or -1") - the
        # opening sentence showed twice in the video's first seconds.
        doc = lay((EMPTY, 6.0), (clip("/w/b.mp4", 6.0), 6.0), (EMPTY, 4.0))
        first, last = doc["scenes"][0], doc["scenes"][2]
        card = lambda s: {"type": "highlight", "text": s["text"], "startFrame": s["startFrame"],  # noqa: E731
                          "durationInFrames": s["durationInFrames"]}
        date = {"type": "motion", "template": "KT_DATE", "startFrame": 27, "durationInFrames": 150}
        doc["overlays"] = [card(first), date, card(last)]
        quality.text_scene(doc, first)
        self.assertEqual(first["media"]["type"], "animation")
        self.assertEqual(doc["overlays"], [date, card(last)])        # its own card only; the date look stays
        quality.text_scene(doc, last)
        self.assertEqual(doc["overlays"], [date])


if __name__ == "__main__":
    unittest.main()
