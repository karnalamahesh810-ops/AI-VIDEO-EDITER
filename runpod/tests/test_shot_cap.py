"""
No shot stays on screen longer than 7 seconds (src/shotcap.py; the owner, 2026-10-04:
"some of the clips are playing more than seven seconds on the timeline, fix that issue").

Measured on his Lake Mead video: 132 of 240 shots ran past 7 s - the scene cutter's
own ceiling is 9 s, and 24 shots held over an empty line averaged 11.3 s (up to 16.8 s).

  A. the cut: before the shots are planned a beat longer than SHOT_MAX_SECONDS becomes
     2+ shots on word boundaries (a sentence end, a comma, a breath first; never inside
     a name or after "the"), the brief's beat numbers follow, shorter beats are untouched;
  B. the flag: 0 leaves every beat, every hold and every search exactly as before; one
     job or a video style may set its own; nothing above 12 s anywhere;
  C. holds: a neighbouring shot is held over an empty line only within the cap and never
     slowed to stretch; otherwise a pick-a-shot runner-up of a shot beside it (never a
     file or moment the video shows, never a clip too short), then the ladder, then a card;
  D. graphics and animation scenes keep their own lengths; the report in doc.meta.shotCap;
  E. a whole plan: no shot over the cap, nothing shown twice.
Offline: every source, download and probe is mocked.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import handler
from src import config, gapfill, hookboost, shotcap, styles, timeline
from src.media import MediaAsset
from src.transcribe import Segment, Word, screen_lengths, segment_words

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
EMPTY = {"type": "color", "url": "", "source": "none"}
GLUE = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "and"}


def words_of(text, start, pace=0.34):
    """Evenly spaced words; a comma breathes a little, a full stop more."""
    out, t = [], float(start)
    for tok in text.split():
        out.append(Word(text=tok, start=round(t, 3), end=round(t + pace * 0.85, 3)))
        t += pace + (0.12 if tok.endswith(",") else 0.0) + (0.3 if tok.endswith((".", "?", "!")) else 0.0)
    return out


def beat(text, start, seconds=None, pace=0.34):
    words = words_of(text, start, pace)
    end = start + seconds if seconds else round(words[-1].end + 0.25, 3)
    return Segment(text=text, start=float(start), end=float(end), words=words)


def story(lines, start=0.0):
    """Consecutive beats from [(text, seconds)], each starting where the one before ends."""
    segs, t = [], float(start)
    for text, seconds in lines:
        s = beat(text, t, seconds)
        segs.append(s)
        t = s.end
    return segs


def fixture(name):
    with open(os.path.join(HERE, "fixtures", f"words_{name}.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    return [Word(t, s, e) for t, s, e in d["words"]], float(d["duration"])


def cap(seconds=7.0, **over):
    """Patch the cap (and any other setting); the cutter's defaults unless said otherwise."""
    base = {"SHOT_MAX_SECONDS": float(seconds), "MIN_SCENE_SECONDS": 5.0, "CUT_LEAD_SECONDS": 0.0}
    base.update(over)
    return mock.patch.multiple(config, **base)


SENTENCE = ("The reservoirs that fed Austin have dropped to a fraction of their size. "
            "Now the cracked mud stretches for miles across the valley floor today.", 8.9)
COMMA = ("The reservoirs that fed Austin have dropped to a fraction of their size, "
         "and the cracked mud now stretches for miles across the dry valley.", 8.8)
NAMES = ("Officials in the city of San Antonio said the Edwards Aquifer near New Braunfels "
         "dropped again this week by several feet overall", 8.4)
SHORT = ("Wells are failing across the Hill Country every week.", 4.0)
VERY_LONG = ("The river that once filled the canyon has slowed to a trickle, and the towns that grew along "
             "its banks are trucking in water every morning, while the farms downstream leave their fields "
             "dry, and the ranchers sell their herds, and nobody knows when the rain will come back again.", 19.5)


# --------------------------------------------------------------------------- A. the cut
class CuttingALongBeat(unittest.TestCase):
    def setUp(self):
        self.segs = story([SHORT, SENTENCE, SHORT, COMMA, NAMES, SHORT, VERY_LONG, SHORT])

    def split(self, segs=None, **over):
        segs = segs if segs is not None else self.segs
        with cap(**over):
            return shotcap.split_long(segs, until=segs[-1].end)

    def test_a_beat_over_the_cap_becomes_two_or_more_shots_within_it(self):
        out, parents, info = self.split()
        self.assertGreater(len(out), len(self.segs))
        lengths = screen_lengths(out, 0.0, self.segs[-1].end)
        self.assertLessEqual(max(lengths), 7.0 + 1e-6, lengths)
        self.assertGreaterEqual(min(lengths), 2.5 - 1e-6, lengths)          # nothing flashes by
        for idx, seg in enumerate(self.segs):
            pieces = [p for p, par in zip(out, parents) if par == idx]
            if seg.duration <= 7.0:
                self.assertEqual(len(pieces), 1)
                self.assertIs(pieces[0], seg, idx)                          # a shorter beat: the same object
            else:
                self.assertGreaterEqual(len(pieces), 2, idx)
        self.assertEqual((info["before"]["over"], info["planned"]["over"], info["cut"]), (4, 0, 4))
        self.assertEqual(info["shotsAdded"], len(out) - len(self.segs))
        self.assertAlmostEqual(info["before"]["longest"], 19.5, places=1)

    def test_the_pieces_tile_the_beat_every_cut_on_a_word_start_no_one_word_shot(self):
        out, parents, _ = self.split()
        self.assertEqual([w for s in out for w in s.words], [w for s in self.segs for w in s.words])
        for a, b in zip(out, out[1:]):
            self.assertLessEqual(a.end, b.start + 1e-6)                     # in order, never overlapping
        for p, par in zip(out, parents):
            self.assertGreaterEqual(len(p.words), 2, p.text)
            self.assertEqual(p.text.split(), [w.text for w in p.words])     # each piece says its own words
            if p is not self.segs[par] and p.words[0] is not self.segs[par].words[0]:
                self.assertAlmostEqual(p.start, p.words[0].start, places=6)

    def test_the_cut_lands_on_the_sentence_end_then_the_comma(self):
        _, _, info = self.split()
        by_beat = {s["beat"]: s for s in info["examples"]}
        self.assertEqual(by_beat[1]["cutBefore"], ["Now"])                  # "...of their size. | Now the cracked mud"
        self.assertEqual(by_beat[3]["cutBefore"], ["and"])                  # "...of their size, | and the cracked mud"

    def test_never_inside_a_name_or_after_a_glue_word(self):
        out, parents, info = self.split()
        cut = {s["beat"]: s for s in info["examples"]}[4]["cutBefore"]
        self.assertEqual(len(cut), 1)
        self.assertNotIn(cut[0], ("Antonio", "Aquifer", "Braunfels", "of"))
        first = [p for p, par in zip(out, parents) if par == 4][0]
        self.assertNotIn(first.words[-1].text.lower(), GLUE)                # never "...near the | New Braunfels"

    def test_a_very_long_beat_gets_as_many_shots_as_it_needs(self):
        out, parents, _ = self.split()
        pieces = [p for p, par in zip(out, parents) if par == 6]
        # 19.5 s under a 7 s cap: three even shots would cut inside a clause, four end on its commas.
        self.assertEqual(len(pieces), 4)
        ends = [p.words[-1].text for p in pieces[:-1]]
        self.assertTrue(all(t.endswith(",") for t in ends), ends)           # each at a clause end
        lengths = screen_lengths(out, 0.0, self.segs[-1].end)
        mine = [x for x, par in zip(lengths, parents) if par == 6]
        self.assertLessEqual(max(mine), 7.0 + 1e-6, mine)
        self.assertAlmostEqual(sum(mine), 19.5, places=6)

    def test_the_brief_and_the_focus_follow_the_new_beats(self):
        brief = {"hookBeats": [0, 1], "sections": [{"from": 0, "to": 1}, {"from": 2, "to": 7}]}
        with cap():
            out, focus, info = shotcap.prepare(self.segs, brief, {1: {"subject": "Austin"}, 5: {"subject": "x"}},
                                               until=self.segs[-1].end)
        self.assertEqual(brief["hookBeats"], [0, 1, 2])                     # beat 1 is now beats 1-2
        self.assertEqual(brief["sections"], [{"from": 0, "to": 2}, {"from": 3, "to": len(out) - 1}])
        self.assertEqual(focus[1], {"subject": "Austin"})                   # on the first piece of its beat
        self.assertIn({"subject": "x"}, focus.values())
        self.assertEqual(shotcap.LAST["cut"], info["cut"])

    def test_the_real_narrations_keep_their_good_cuts(self):
        # Whisper timings of two benchmark narrations, cut by the default 5/7/9 s rhythm.
        for name in ("new_mexico_flash_flood", "lake_mead"):
            words, dur = fixture(name)
            segs = segment_words(words, origin=0.0, until=dur)
            before = screen_lengths(segs, 0.0, dur)
            self.assertGreater(max(before), 7.0, name)                      # the cutter's own ceiling is 9 s
            with cap():
                out, _, info = shotcap.prepare(segs, {}, {}, until=dur)
            after = screen_lengths(out, 0.0, dur)
            self.assertLessEqual(max(after), 7.0 + 1e-6, (name, after))
            self.assertEqual(info["planned"]["over"], 0)
            self.assertEqual([w for s in out for w in s.words], words)
            ends = [s.words[-1].text for s in out[:-1]]
            good = sum(1 for t in ends if t.rstrip("\"')").endswith((".", "!", "?", ",", ";", ":")))
            self.assertGreaterEqual(good / len(ends), 0.8, (name, ends))    # lowering the cutter's ceiling: 0.44-0.75

    def test_a_cut_follows_the_styles_lead_before_a_sentence(self):
        segs = story([SENTENCE, SHORT])
        with cap(CUT_LEAD_SECONDS=0.14):
            out, _, _ = shotcap.split_long(segs, until=segs[-1].end)
        second = out[1]
        self.assertEqual(second.words[0].text, "Now")
        self.assertAlmostEqual(second.start, second.words[0].start - 0.14, places=6)   # in the breath before it
        self.assertGreaterEqual(second.start, out[0].words[-1].end)

    def test_a_beat_whose_words_leave_no_cut_is_left_whole_and_reported(self):
        lone = Segment(text="Silence.", start=0.0, end=0.6, words=[Word("Silence.", 0.0, 0.6)])
        segs = [lone, beat(SHORT[0], 9.0, 4.0)]                             # one word, then 9 s of nothing
        with cap():
            out, _, info = shotcap.prepare(segs, {}, {}, until=13.0)
        self.assertIs(out, segs)
        self.assertEqual((info["before"]["over"], info["planned"]["over"], info["cut"]), (1, 1, 0))


# --------------------------------------------------------------------------- B. the flag
class TheFlag(unittest.TestCase):
    def test_on_at_seven_seconds_by_default(self):
        self.assertEqual(config.SHOT_MAX_SECONDS, 7.0)
        self.assertEqual(shotcap.limit(), 7.0)
        self.assertIn("SHOT_MAX_SECONDS", handler.CONFIG_OVERRIDABLE)

    def test_zero_leaves_the_beats_the_brief_and_the_focus_alone(self):
        segs = story([SENTENCE, SHORT, VERY_LONG])
        brief = {"hookBeats": [0], "sections": [{"from": 0, "to": 2}]}
        with cap(0):
            out, focus, info = shotcap.prepare(segs, brief, {2: {"subject": "x"}}, until=segs[-1].end)
            self.assertFalse(shotcap.enabled())
            self.assertEqual(shotcap.hold_rates(), (config.HOLD_MIN_RATE, 0.6))    # the old slow-down ladder
            self.assertEqual(shotcap.room({"durationInFrames": 900}, FPS, float("inf")), float("inf"))
            self.assertEqual(shotcap.over_cap({"fps": FPS, "scenes": [scene(0, photo("/w/a.jpg"), 0, 30)]}), [])
        self.assertIs(out, segs)
        self.assertEqual((focus, info), ({2: {"subject": "x"}}, {}))
        self.assertEqual(brief, {"hookBeats": [0], "sections": [{"from": 0, "to": 2}]})

    def test_one_job_sets_its_own_and_it_is_put_back(self):
        before = config.SHOT_MAX_SECONDS
        previous = handler._apply_config({"SHOT_MAX_SECONDS": "5.5"})
        try:
            self.assertEqual(shotcap.limit(), 5.5)
        finally:
            handler._restore_config(previous)
        self.assertEqual(config.SHOT_MAX_SECONDS, before)

    def test_nothing_above_twelve_seconds_anywhere(self):
        for asked, got in ((30.0, 12.0), (12.0, 12.0), (9.0, 9.0), (1.0, 3.0), (0.0, 0.0), (-4.0, 0.0)):
            with mock.patch.object(config, "SHOT_MAX_SECONDS", asked):
                self.assertEqual(shotcap.limit(), got, asked)
        for name in styles.STYLES:
            inp = {"video_style": name}
            styles.apply(inp)
            with mock.patch.object(config, "SHOT_MAX_SECONDS",
                                   float(inp["config"].get("SHOT_MAX_SECONDS", config.SHOT_MAX_SECONDS))):
                self.assertLessEqual(shotcap.limit(), 12.0, name)
                self.assertGreater(shotcap.limit(), 0.0, name)              # no style switches the rule off

    def test_a_style_sets_its_own_and_the_jobs_override_wins(self):
        # The measured news styles keep their own 7 s rule whatever the default becomes.
        for name in ("news_compilation", "nature_weather"):
            self.assertEqual(styles.STYLES[name]["config"]["SHOT_MAX_SECONDS"], 7.0, name)
        inp = {"video_style": "news_compilation"}
        styles.apply(inp)
        with mock.patch.object(config, "SHOT_MAX_SECONDS", 10.0):           # a looser default
            previous = handler._apply_config(inp["config"])
            try:
                self.assertEqual(shotcap.limit(), 7.0)
            finally:
                handler._restore_config(previous)
        own = {"video_style": "news_compilation", "config": {"SHOT_MAX_SECONDS": 6}}
        styles.apply(own)
        self.assertEqual(own["config"]["SHOT_MAX_SECONDS"], 6)
        # A style without its own follows the default, even where its cutter runs to 10 s.
        self.assertNotIn("SHOT_MAX_SECONDS", styles.STYLES["history"]["config"])
        self.assertEqual(styles.STYLES["history"]["config"]["MAX_SCENE_SECONDS"], 10.0)


# --------------------------------------------------------------------------- C. holds
def scene(i, media_, start, seconds, **sem):
    return {"id": f"s{i:04d}", "startFrame": int(round(start * FPS)), "durationInFrames": int(round(seconds * FPS)),
            "text": f"line {i} of the story", "media": dict(media_), "visualType": "footage",
            "semanticMetadata": dict(sem), "words": []}


def photo(url):
    return {"type": "image", "url": url, "source": "wikimedia"}


def clip(url, seconds):
    return {"type": "video", "url": url, "source": "youtube", "clipSeconds": seconds}


def doc_of(*specs):
    """A timeline of consecutive scenes from (media, seconds[, semanticMetadata])."""
    scenes, t = [], 0.0
    for i, spec in enumerate(specs):
        media_, seconds = spec[0], spec[1]
        scenes.append(scene(i, media_, t, seconds, **(spec[2] if len(spec) > 2 else {})))
        t += seconds
    return {"fps": FPS, "overlays": [], "scenes": scenes, "meta": {}}


def seconds_of(doc):
    return [round(s["durationInFrames"] / FPS, 2) for s in doc["scenes"]]


def quiet():
    """No planner graphic, no hook: the hold is what is under test."""
    return mock.patch.multiple(config, ANIMATION_FILL=False, HOOK_SECONDS=0.0)


def runner_up(vid, start, path="", seconds=7.0, score=0.8, **more):
    """A pick-a-shot runner-up as media._best_of leaves it on the winner (its file kept)."""
    alt = {"assetId": f"yt:{vid}@{int(start // 8)}", "url": f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
           "title": "a runner-up", "score": score, "quality": 0.7, "finalScore": None, "specificity": "location",
           "moment": {"start": float(start)}, "description": "a wide view of the dry lake bed", "source": "youtube"}
    if path:
        alt["localPath"] = path
    if seconds:
        alt["seconds"] = seconds
    alt.update(more)
    return alt


class Holds(unittest.TestCase):
    def setUp(self):
        gapfill.reset()
        shotcap.reset()
        self.work = tempfile.mkdtemp()
        self.addCleanup(gapfill.reset)
        self.addCleanup(shotcap.reset)
        p = mock.patch.object(shotcap, "_probe", return_value=0.0)          # never ffprobe in a test
        p.start()
        self.addCleanup(p.stop)

    def file(self, name):
        path = os.path.join(self.work, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        return path

    def test_a_hold_within_the_cap_is_still_made(self):
        doc = doc_of((photo("/w/a.jpg"), 3.0), (EMPTY, 3.0), (photo("/w/b.jpg"), 3.0))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["held"], 1)
        self.assertEqual(seconds_of(doc), [4.5, 4.5])
        self.assertEqual(shotcap.SWAPS.get("held"), 1)

    def test_a_hold_fills_each_neighbour_to_the_cap_and_no_further(self):
        doc = doc_of((photo("/w/a.jpg"), 5.0), (EMPTY, 3.0), (photo("/w/b.jpg"), 6.0))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["held"], 1)
        self.assertEqual(seconds_of(doc), [7.0, 7.0])
        a, b = doc["scenes"]
        self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])     # still tiles the narration

    def test_a_hold_past_the_cap_beats_a_text_card_but_never_past_twelve_seconds(self):
        # The owner would rather see a real picture a little longer than a text card: when nothing
        # fresh is found, the shot beside the line is held past the cap - each shot at most 12 s.
        def make(gap=6.0):
            return doc_of((photo("/w/a.jpg"), 5.0), (EMPTY, gap), (photo("/w/b.jpg"), 5.0))
        old = make()
        with cap(0), quiet():
            self.assertEqual(gapfill.hold_or_animate(old)["held"], 1)
        self.assertEqual(seconds_of(old), [8.0, 8.0])                       # before: two 8 s shots
        doc = make()
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["long"], got["card"]), (1, 1, 0))   # no text card
        self.assertEqual(seconds_of(doc), [8.0, 8.0])                       # split between both: neither past 12 s
        self.assertEqual([o["seconds"] for o in shotcap.over_cap(doc)], [8.0, 8.0])
        self.assertTrue(all(o["held"] for o in shotcap.over_cap(doc)))
        self.assertIn("past 7 s", doc["scenes"][0]["reviewReason"])
        self.assertEqual(doc["overlays"], [])
        self.assertEqual((shotcap.SWAPS.get("refused"), shotcap.SWAPS.get("long"), shotcap.SWAPS.get("card")),
                         (1, 1, None))
        # 15 s of narration between two 5 s photos: they can take 14 s of it at most without a shot past
        # 12 s - its line as text.
        shotcap.reset()
        far = make(15.0)
        with cap(), quiet():
            got = gapfill.hold_or_animate(far)
        self.assertEqual((got["held"], got["card"]), (0, 1))
        self.assertEqual(seconds_of(far), [5.0, 15.0, 5.0])
        self.assertEqual([o["type"] for o in far["overlays"]], ["highlight"])
        self.assertEqual((shotcap.SWAPS.get("refused"), shotcap.SWAPS.get("card")), (1, 1))

    def test_a_clip_held_past_the_cap_plays_at_real_speed_only(self):
        # A clip may run past the cap only on footage it really has; a clip without it is never slowed.
        doc = doc_of((clip("/w/a.mp4", 9.0), 5.0), (EMPTY, 4.0), (clip("/w/b.mp4", 3.5), 3.0))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got.get("long"), got["card"]), (1, 1, 0))
        self.assertEqual(seconds_of(doc), [8.5, 3.5])                       # 9 s of footage, 0.5 s of footage
        for sc in doc["scenes"]:
            self.assertGreaterEqual(sc["media"]["clipSeconds"], sc["durationInFrames"] / FPS)
        bare = doc_of((clip("/w/a.mp4", 5.5), 5.0), (EMPTY, 4.0), (clip("/w/b.mp4", 3.5), 3.0))
        with cap(), quiet():
            got = gapfill.hold_or_animate(bare)
        self.assertEqual((got["held"], got["card"]), (0, 1))                # 1 s of footage for a 4 s line: text
        self.assertEqual(seconds_of(bare), [5.0, 4.0, 3.0])

    def test_a_run_of_empty_lines_is_held_only_as_far_as_twelve_seconds_allow(self):
        doc = doc_of((photo("/w/a.jpg"), 4.0), (EMPTY, 4.0), (EMPTY, 4.0), (EMPTY, 4.0), (photo("/w/b.jpg"), 4.0))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertLessEqual(max(s for s, sc in zip(seconds_of(doc), doc["scenes"]) if shotcap.is_shot(sc)), 12.0)
        self.assertEqual(got["held"] + got["card"], 3)
        self.assertEqual(got["card"], 0)                                    # every line on a real picture
        self.assertEqual(sum(seconds_of(doc)), 20.0)                        # the narration is still tiled
        with cap(0), quiet():
            old = doc_of((photo("/w/a.jpg"), 4.0), (EMPTY, 4.0), (EMPTY, 4.0), (EMPTY, 4.0), (photo("/w/b.jpg"), 4.0))
            gapfill.hold_or_animate(old)
        self.assertEqual(max(seconds_of(old)), 14.0)                        # before: one photo for 14 s
        # Six empty lines between two photos: 24 s cannot be covered by two shots of 12 s at most.
        many = doc_of((photo("/w/a.jpg"), 4.0), *[(EMPTY, 4.0)] * 6, (photo("/w/b.jpg"), 4.0))
        with cap(), quiet():
            got = gapfill.hold_or_animate(many)
        self.assertLessEqual(max(seconds_of(many)), 12.0)
        self.assertEqual((got["held"], got["card"]), (4, 2))

    def test_a_clip_is_never_slowed_to_stretch_over_a_line(self):
        def make():
            return doc_of((clip("/w/a.mp4", 3.5), 3.0), (EMPTY, 3.0), (clip("/w/b.mp4", 3.5), 3.0))
        old = make()
        with cap(0), quiet():
            self.assertEqual(gapfill.hold_or_animate(old)["held"], 1)       # before: both clips at 0.78x
        self.assertEqual(seconds_of(old), [4.5, 4.5])
        doc = make()
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["card"]), (0, 1))
        self.assertEqual(seconds_of(doc), [3.0, 3.0, 3.0])
        for sc in (doc["scenes"][0], doc["scenes"][2]):                     # every clip covers its scene at real speed
            self.assertGreaterEqual(sc["media"]["clipSeconds"], sc["durationInFrames"] / FPS)
        # ...and a clip with real footage to spare still covers the line.
        long = doc_of((clip("/w/a.mp4", 6.0), 3.0), (EMPTY, 3.0), (clip("/w/b.mp4", 6.0), 3.0))
        with cap(), quiet():
            self.assertEqual(gapfill.hold_or_animate(long)["held"], 1)
        self.assertEqual(seconds_of(long), [4.5, 4.5])

    def test_a_runner_up_of_the_shot_beside_it_stands_in(self):
        alt = runner_up("ALT00000001", 30, self.file("alt1.mp4"))
        other = runner_up("ALT00000002", 50, self.file("alt2.mp4"), score=0.6)
        doc = doc_of((photo("/w/a.jpg"), 6.0, {"assetId": "wikimedia:a", "alternatives": [other, alt]}),
                     (EMPTY, 5.0), (photo("/w/b.jpg"), 6.0, {"assetId": "wikimedia:b"}))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["card"], got["alternative"]), (0, 0, 1))
        s = doc["scenes"][1]
        self.assertEqual(s["media"], {"type": "video", "url": alt["localPath"], "source": "youtube",   # the best-scored
                                      "attribution": "a runner-up", "clipSeconds": 7.0,
                                      # what a found clip's media carries (MediaAsset.to_scene_media)
                                      "license": shotcap.UNVERIFIED, "relevanceScore": 0.8, "qualityScore": 0.7,
                                      "contentDescription": "a wide view of the dry lake bed"})
        sem = s["semanticMetadata"]
        self.assertEqual((sem["assetId"], sem["sourceUrl"], sem["moment"]),
                         ("yt:ALT00000001@3", "https://www.youtube.com/watch?v=ALT00000001&t=30", {"start": 30.0}))
        self.assertEqual(sem["shotCap"], {"from": "s0000", "how": "alternative"})
        self.assertTrue(s["reviewRequired"])
        self.assertIn("7 s", s["reviewReason"])
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["alternatives"], [other])   # no longer a choice there
        self.assertEqual(seconds_of(doc), [6.0, 5.0, 6.0])
        self.assertEqual(gapfill.find_repeats(doc), [])
        self.assertEqual(doc["overlays"], [])
        self.assertEqual(shotcap.SWAPS.get("alternative"), 1)

    def test_never_a_file_or_a_moment_the_video_already_shows(self):
        shown = self.file("shown.mp4")
        same_file = runner_up("ALT00000001", 30, shown)                                  # scene 3 shows this file
        same_video = runner_up("NEXT0000001", 200, self.file("m.mp4"))                   # scene 2's source video
        near_moment = runner_up("FAR00000001", 20, self.file("n.mp4"))                   # 10 s from scene 3's moment
        # (Clips with no footage to spare on either side: no hold past the cap either - the card is what is left.)
        doc = doc_of((clip("/w/a.mp4", 6.0), 6.0, {"assetId": "yt:AAAAAAAAAAA@1", "moment": {"start": 10.0},
                                                   "alternatives": [same_file, same_video, near_moment]}),
                     (EMPTY, 5.0),
                     (clip("/w/next.mp4", 6.5), 6.0, {"assetId": "yt:NEXT0000001@1", "moment": {"start": 10.0},
                                                      "sourceUrl": "https://www.youtube.com/watch?v=NEXT0000001&t=10"}),
                     (clip(shown, 6.5), 6.0, {"assetId": "yt:FAR00000001@3", "moment": {"start": 30.0},
                                              "sourceUrl": "https://www.youtube.com/watch?v=FAR00000001&t=30"}))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got.get("alternative", 0), got["card"]), (0, 1))
        self.assertEqual(doc["scenes"][1]["media"]["type"], "color")
        self.assertEqual(len(doc["scenes"][0]["semanticMetadata"]["alternatives"]), 3)   # all still choices there
        self.assertEqual(gapfill.find_repeats(doc), [])

    def test_a_runner_up_whose_video_the_variety_rules_forbid_is_passed_over(self):
        # media.may_place: the runner-up's video already plays MAX_MOMENTS_PER_VIDEO times in the video.
        alt = runner_up("BUSY0000001", 300, self.file("busy.mp4"))
        def make():
            return doc_of((clip("/w/a.mp4", 6.0), 6.0, {"alternatives": [alt]}), (EMPTY, 5.0),
                          (clip("/w/b.mp4", 6.0), 6.0), (clip("/w/c.mp4", 6.0), 6.0),
                          (clip("/w/busy.mp4", 6.0), 6.0, {"assetId": "yt:BUSY0000001@1", "moment": {"start": 10.0},
                                                           "sourceUrl": "https://www.youtube.com/watch?v=BUSY0000001&t=10"}))
        doc = make()
        with cap(MAX_MOMENTS_PER_VIDEO=1), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got.get("alternative", 0), got["card"]), (0, 1))
        doc = make()
        with cap(MAX_MOMENTS_PER_VIDEO=2, SAME_VIDEO_GAP_SECONDS=0.0), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got.get("alternative", 0), got["card"]), (1, 0))

    def test_a_runner_up_too_short_for_the_line_is_not_slowed_to_fit(self):
        short = runner_up("ALT00000001", 30, self.file("s.mp4"), seconds=3.0)
        still = runner_up("", 0, self.file("p.jpg"), seconds=0, score=0.5,
                          assetId="web_image:https://x/p.jpg", url="https://x/p.jpg", moment={})
        doc = doc_of((photo("/w/a.jpg"), 6.0, {"alternatives": [short]}), (EMPTY, 5.0),
                     (photo("/w/b.jpg"), 6.0, {"alternatives": [still]}))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got["alternative"], 1)
        self.assertEqual(doc["scenes"][1]["media"]["type"], "image")                     # the photo holds any length
        self.assertEqual(doc["scenes"][1]["media"]["url"], still["localPath"])
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["alternatives"], [short])

    def test_a_published_runner_up_is_taken_only_when_it_still_loads(self):
        def make():
            alt = runner_up("PUB00000001", 40, seconds=6.0)
            alt["media"] = {"type": "video", "url": "https://r2.example/alts/s0000_alt1.mp4", "storage": "r2:x",
                            "thumbnail": "https://r2.example/thumbs/s0000_alt1.jpg"}
            return doc_of((photo("https://r2.example/a.jpg"), 6.0, {"alternatives": [alt]}), (EMPTY, 5.0),
                          (photo("https://r2.example/b.jpg"), 6.0))
        doc = make()
        with cap(), quiet(), mock.patch.object(shotcap, "_reach", return_value=True) as reach:
            got = gapfill.hold_or_animate(doc, laddered=True)
        self.assertEqual(got["alternative"], 1)
        reach.assert_called_once_with("https://r2.example/alts/s0000_alt1.mp4", "video")
        m = doc["scenes"][1]["media"]
        self.assertEqual((m["url"], m["clipSeconds"], m["thumbnail"]),
                         ("https://r2.example/alts/s0000_alt1.mp4", 6.0, "https://r2.example/thumbs/s0000_alt1.jpg"))
        gone = make()
        with cap(), quiet(), mock.patch.object(shotcap, "_reach", return_value=False):
            got = gapfill.hold_or_animate(gone, laddered=True)
        self.assertEqual((got.get("alternative", 0), got.get("long", 0), got["card"]), (0, 1, 0))  # the photos held instead
        self.assertNotIn("https://r2.example/alts/s0000_alt1.mp4", [s["media"]["url"] for s in gone["scenes"]])

    def test_a_runner_up_comes_from_at_most_two_scenes_away(self):
        far = runner_up("ALT00000001", 30, self.file("far.mp4"))
        doc = doc_of((photo("/w/a.jpg"), 6.5, {"alternatives": [far]}), (photo("/w/b.jpg"), 6.5),
                     (photo("/w/c.jpg"), 6.5), (EMPTY, 5.0), (photo("/w/d.jpg"), 6.5))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got.get("alternative", 0), got.get("long", 0), got["card"]), (0, 1, 0))  # held instead
        self.assertNotIn(far["localPath"], [s["media"]["url"] for s in doc["scenes"]])

    def _moment_mocks(self, fetch, clip_seconds=None):
        from src import ledger, media
        return [mock.patch.object(media, "fetch_clean_clip", side_effect=fetch),
                mock.patch.object(media, "_asset_ok", return_value=(True, "")),
                mock.patch.object(media, "motion_rejects", return_value=""),
                mock.patch.object(media, "slop_reason", return_value=""),
                mock.patch.object(ledger, "moment_used", return_value=False),
                mock.patch.object(timeline, "_clip_seconds",
                                  side_effect=clip_seconds or (lambda a: float(a.duration or 0)))]

    def test_another_moment_of_the_clip_beside_it_thirty_seconds_on(self):
        calls = []

        def fetch(vid, work, at, need, title=""):
            calls.append((vid, round(at, 1), round(need, 2), title))
            p = os.path.join(work, f"m{len(calls)}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p, True, 0
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(3)], self.work)
        doc = doc_of((clip("/w/a.mp4", 6.5), 6.0, {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0},
                                                 "sourceUrl": "https://www.youtube.com/watch?v=LEFT0000001&t=40"}),
                     (EMPTY, 5.0),
                     (clip("/w/b.mp4", 6.5), 6.0, {"assetId": "yt:RIGHT000001@1", "moment": {"start": 10.0},
                                                 "sourceUrl": "https://www.youtube.com/watch?v=RIGHT000001&t=10"}))
        doc["scenes"][0]["media"]["attribution"] = "YouTube: the dry lake"
        patches = self._moment_mocks(fetch)
        with cap(), quiet(), mock.patch.object(gapfill, "fill_empty", return_value={}) as ladder:
            for p in patches:
                p.start()
            try:
                got = gapfill.hold_or_animate(doc, laddered=True)
            finally:
                for p in patches:
                    p.stop()
        ladder.assert_not_called()
        self.assertEqual((got["held"], got["card"], got["moment"]), (0, 0, 1))
        # 40 s + the 6 s shown + the 30 s gap, as long as the line plus the usual pad, the clip's own title.
        self.assertEqual(calls, [("LEFT0000001", 76.0, 5.5, "YouTube: the dry lake")])
        s = doc["scenes"][1]
        self.assertEqual((s["media"]["type"], s["media"]["url"], s["media"]["clipSeconds"]), ("video", calls and
                         os.path.join(self.work, "m1.mp4"), 5.5))
        sem = s["semanticMetadata"]
        self.assertEqual(sem["assetId"], "yt:LEFT0000001@9")
        self.assertEqual(sem["moment"]["start"], 76.0)
        self.assertTrue(sem["moment"]["chain"])                             # the clip before plays on: allowed next to it
        self.assertEqual(sem["shotCap"], {"from": "s0000", "how": "moment"})
        self.assertIn("Another moment", s["reviewReason"])
        self.assertEqual(gapfill.find_repeats(doc), [])
        self.assertEqual(seconds_of(doc), [6.0, 5.0, 6.0])
        self.assertIn("filled 1 scenes from other moments", gapfill.summary(got))

    def test_a_moment_the_video_shows_or_an_earlier_video_used_is_passed_over(self):
        from src import ledger
        calls = []

        def fetch(vid, work, at, need, title=""):
            calls.append((vid, round(at, 1)))
            p = os.path.join(work, f"m{len(calls)}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p, True, 0
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(4)], self.work)
        # The left clip's video shows again two scenes on, exactly where "30 s on" would land.
        doc = doc_of((clip("/w/a.mp4", 6.5), 6.0, {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0},
                                                 "sourceUrl": "https://www.youtube.com/watch?v=LEFT0000001&t=40"}),
                     (EMPTY, 5.0),
                     (photo("/w/p.jpg"), 6.0),
                     (clip("/w/c.mp4", 6.5), 6.0, {"assetId": "yt:LEFT0000001@9", "moment": {"start": 76.0},
                                                 "sourceUrl": "https://www.youtube.com/watch?v=LEFT0000001&t=76"}))
        patches = self._moment_mocks(fetch)
        with cap(), quiet():
            for p in patches:
                p.start()
            try:
                with mock.patch.object(ledger, "moment_used", side_effect=lambda vid, a, b: a < 10):
                    got = gapfill.hold_or_animate(doc, laddered=True)
            finally:
                for p in patches:
                    p.stop()
        # Not 76 s (shown), not 4.5 s before (an earlier video used it): the photo beside it is held instead.
        self.assertEqual(calls, [])
        self.assertEqual((got.get("moment", 0), got.get("long", 0), got["card"]), (0, 1, 0))

    def test_another_moment_is_fetched_only_where_the_job_may_search(self):
        def make():
            # (A clip with no footage to spare after the line: not held past the cap either.)
            return doc_of((clip("/w/a.mp4", 6.5), 6.0, {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0}}),
                          (EMPTY, 5.0), (clip("/w/b.mp4", 6.0), 6.0))
        fetch = mock.Mock(side_effect=AssertionError("fetched"))
        patches = self._moment_mocks(fetch)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with cap(), quiet():
            gapfill.reset()                                                 # no plan of its own: a render job
            self.assertEqual(gapfill.hold_or_animate(make(), laddered=True)["card"], 1)
            gapfill.remember([{"index": i, "start": 6.0 * i} for i in range(3)], self.work)
            self.assertEqual(gapfill.hold_or_animate(make(), laddered=True, search=False)["card"], 1)
        fetch.assert_not_called()

    def test_the_ladder_runs_where_it_has_not_just_run_and_before_the_card(self):
        def make():
            return doc_of((photo("/w/a.jpg"), 6.0), (EMPTY, 5.0), (photo("/w/b.jpg"), 6.0))
        calls = []

        def ladder(jobs, results, work, **kw):
            calls.append(list(kw["indices"]))
            for i in kw["indices"]:
                results[i] = MediaAsset(kind="image", source="web_image", url=f"https://x/found{i}.jpg",
                                        local_path=os.path.join(work, f"found{i}.jpg"),
                                        review_reason="A picture found when the footage search ran out of time")
            return {}
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(3)], self.work)
        doc = make()
        with cap(), quiet(), mock.patch.object(gapfill, "fill_empty", side_effect=ladder):
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(calls, [[1]])
        self.assertEqual((got["ladder"], got.get("long", 0), got["card"]), (1, 0, 0))   # a fresh picture first
        self.assertEqual(doc["scenes"][1]["media"]["type"], "image")
        self.assertEqual(seconds_of(doc), [6.0, 5.0, 6.0])
        self.assertIn("filled 1 scenes from ladder", gapfill.summary(got))
        # The caller has just run the ladder for these lines: not again (the photos are held instead).
        # (A Mock, not an exception: _instead_of_hold catches whatever the ladder raises.)
        doc = make()
        with cap(), quiet(), mock.patch.object(gapfill, "fill_empty", return_value={}) as again:
            got = gapfill.hold_or_animate(doc, laddered=True)
        again.assert_not_called()
        self.assertEqual((got.get("long", 0), got["card"]), (1, 0))
        # A job with no plan of its own (a render of the editor's timeline) never searches.
        gapfill.reset()
        doc = make()
        with cap(), quiet(), mock.patch.object(gapfill, "fill_empty", return_value={}) as searched:
            self.assertEqual(gapfill.hold_or_animate(doc).get("long", 0), 1)
        searched.assert_not_called()

    def test_the_quality_gates_repair_keeps_the_cap_and_says_what_it_did(self):
        # Before the render a scene's picture turns out broken: a render-only job may not search,
        # so the repair used to hold the neighbours over the line (here: two 8.5 s shots).
        from src import quality
        alt = runner_up("PUB00000001", 40, seconds=6.0)
        alt["media"] = {"type": "video", "url": "https://r2.example/alts/s0000_alt1.mp4"}
        doc = doc_of((photo("https://r2.example/a.jpg"), 6.0, {"alternatives": [alt]}),
                     (clip("https://r2.example/broken.mp4", 5.5), 5.0, {"assetId": "yt:BROKEN00001@1"}),
                     # (Clips with no footage to spare around the second line: nothing to hold there at all.)
                     (clip("https://r2.example/b.mp4", 6.0), 6.0, {"assetId": "yt:BBBBBBBBBBB@1"}),
                     (clip("https://r2.example/gone.mp4", 5.5), 5.0, {"assetId": "yt:GONE0000001@1"}),
                     (clip("https://r2.example/c.mp4", 6.0), 6.0, {"assetId": "yt:CCCCCCCCCCC@1"}))
        quality.reset()
        self.addCleanup(quality.reset)
        with cap(), quiet(), mock.patch.object(shotcap, "_reach", return_value=True), \
                mock.patch.object(quality.events, "emit"):
            gate = quality.Gate(doc, self.work)
            n = gate._replace({1: ("broken", "the clip cannot be decoded"), 3: ("unreachable", "404")},
                              "before the render")
        self.assertEqual(n, 2)
        self.assertEqual(len(doc["scenes"]), 5)                             # nothing merged into a long shot
        self.assertEqual(shotcap.over_cap(doc), [])
        how = {r["scene"]: r["how"] for r in gate.repairs}
        self.assertEqual(how, {"s0001": "a runner-up clip of the line beside it",
                               "s0003": "its line as a full-screen text graphic"})
        self.assertEqual((gate.fixed["replaced"], gate.fixed["text"], gate.unresolved), (1, 1, []))
        self.assertEqual(doc["scenes"][1]["media"]["url"], "https://r2.example/alts/s0000_alt1.mp4")
        self.assertEqual(doc["scenes"][3]["media"]["type"], "animation")    # the line as text, never an empty scene

    def test_the_quality_gates_repair_holds_a_picture_past_the_cap_before_a_text_graphic(self):
        from src import quality
        doc = doc_of((photo("https://r2.example/a.jpg"), 6.0),
                     (clip("https://r2.example/gone.mp4", 5.5), 5.0, {"assetId": "yt:GONE0000001@1"}),
                     (photo("https://r2.example/b.jpg"), 6.0))
        quality.reset()
        self.addCleanup(quality.reset)
        with cap(), quiet(), mock.patch.object(quality.events, "emit"):
            gate = quality.Gate(doc, self.work)
            gate._replace({1: ("unreachable", "404")}, "before the render")
        self.assertEqual([r["how"] for r in gate.repairs], ["held over by its neighbouring shots"])
        self.assertEqual((gate.fixed["held"], gate.fixed["text"]), (1, 0))
        self.assertEqual(seconds_of(doc), [8.5, 8.5])                       # past 7 s, never past 12 s
        self.assertEqual(doc["overlays"], [])

    def test_a_render_that_may_search_fetches_another_moment_into_its_own_work_dir(self):
        from src import quality
        calls = []

        def fetch(vid, work, at, need, title=""):
            calls.append((vid, work, round(at, 1)))
            p = os.path.join(work, "m.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p, True, 0
        doc = doc_of((clip("https://r2.example/a.mp4", 6.5), 6.0,
                      {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0},
                       "sourceUrl": "https://www.youtube.com/watch?v=LEFT0000001&t=40"}),
                     (clip("https://r2.example/broken.mp4", 5.5), 5.0, {"assetId": "yt:BROKEN00001@1"}),
                     (photo("https://r2.example/b.jpg"), 6.0))
        quality.reset()
        self.addCleanup(quality.reset)
        gapfill.reset()                                                     # no plan of its own
        patches = self._moment_mocks(fetch)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with cap(), quiet(), mock.patch.object(quality.events, "emit"), \
                mock.patch.object(quality, "CONTEXT", {"ladder": True}), \
                mock.patch.object(gapfill, "fill_empty", return_value={}):  # the gate's own ladder finds nothing
            gate = quality.Gate(doc, self.work)
            gate._replace({1: ("broken", "the clip cannot be decoded")}, "before the render")
        self.assertEqual(calls, [("LEFT0000001", self.work, 76.0)])
        self.assertEqual([r["how"] for r in gate.repairs], ["another moment of the clip beside it"])
        self.assertEqual(gate.fixed["replaced"], 1)
        self.assertEqual(shotcap.over_cap(doc), [])
        # A render that may not search gets the text card instead - and never calls YouTube. (A clip with no
        # footage to spare after the line: no hold past the cap either.)
        again = doc_of((clip("https://r2.example/a.mp4", 6.5), 6.0,
                        {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0}}),
                       (clip("https://r2.example/broken.mp4", 5.5), 5.0), (clip("https://r2.example/b.mp4", 6.0), 6.0))
        with cap(), quiet(), mock.patch.object(quality.events, "emit"), mock.patch.object(quality, "CONTEXT", {}):
            gate = quality.Gate(again, self.work)
            gate._replace({1: ("broken", "the clip cannot be decoded")}, "before the render")
        self.assertEqual(len(calls), 1)
        self.assertEqual([r["how"] for r in gate.repairs], ["its line as a full-screen text graphic"])

    def test_its_own_runner_up_comes_first_and_its_other_choices_stay(self):
        # A scene whose clip broke or repeated keeps the choices its own search made: clips the
        # judge approved for this very line, ahead of a better-scored one of the line beside it.
        own = runner_up("OWN00000001", 30, self.file("own1.mp4"), seconds=6.0, score=0.7)
        own2 = runner_up("OWN00000002", 90, self.file("own2.mp4"), seconds=6.0, score=0.6)
        beside = runner_up("BESIDE00001", 30, self.file("beside.mp4"), seconds=6.0, score=0.95)
        doc = doc_of((photo("/w/a.jpg"), 6.0, {"assetId": "wikimedia:a", "alternatives": [beside]}),
                     (EMPTY, 5.0, {"alternatives": [own2, own]}),
                     (photo("/w/b.jpg"), 6.0, {"assetId": "wikimedia:b"}))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["card"], got["alternative"]), (0, 0, 1))
        s = doc["scenes"][1]
        self.assertEqual(s["media"]["url"], own["localPath"])
        self.assertEqual(s["semanticMetadata"]["alternatives"], [own2])          # its other choice stays
        self.assertEqual(s["semanticMetadata"]["shotCap"], {"from": "s0001", "how": "alternative"})
        self.assertIn("for this line", s["reviewReason"])
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["alternatives"], [beside])
        self.assertEqual(gapfill.find_repeats(doc), [])

    def test_the_quality_gate_never_takes_a_failed_source_again(self):
        # The clip broke; its own best runner-up is another moment of the same source video,
        # which the gate has banned (every moment of a failed source): the next choice instead.
        from src import quality
        same_source = runner_up("BROKEN00001", 200, seconds=6.0, score=0.9)
        same_source["media"] = {"type": "video", "url": "https://r2.example/alts/s0001_alt1.mp4"}
        other = runner_up("OTHER000001", 40, seconds=6.0, score=0.5)
        other["media"] = {"type": "video", "url": "https://r2.example/alts/s0001_alt2.mp4"}
        doc = doc_of((photo("https://r2.example/a.jpg"), 6.0),
                     (clip("https://r2.example/broken.mp4", 5.5), 5.0,
                      {"assetId": "yt:BROKEN00001@1", "moment": {"start": 10.0}, "alternatives": [same_source, other]}),
                     (photo("https://r2.example/b.jpg"), 6.0))
        quality.reset()
        self.addCleanup(quality.reset)
        with cap(), quiet(), mock.patch.object(shotcap, "_reach", return_value=True), \
                mock.patch.object(quality.events, "emit"):
            gate = quality.Gate(doc, self.work)
            gate._replace({1: ("broken", "the clip cannot be decoded")}, "before the render")
        self.assertEqual(doc["scenes"][1]["media"]["url"], "https://r2.example/alts/s0001_alt2.mp4")
        self.assertEqual([r["how"] for r in gate.repairs], ["a runner-up clip of its own line"])
        self.assertEqual(gate.fixed["replaced"], 1)

    def test_a_moment_too_short_for_its_scene_is_never_slowed_to_fit(self):
        # 30 s after the clip beside it the source video is nearly over: that cut comes out 2 s
        # long for a 5 s line; the moment before it is whole. Only the one taken is framed.
        from src import upscale
        calls = []

        def fetch(vid, work, at, need, title=""):
            calls.append(round(at, 1))
            p = os.path.join(work, f"m{len(calls)}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p, True, 0
        lengths = {"m1.mp4": 2.0, "m2.mp4": 5.5}
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(3)], self.work)
        doc = doc_of((clip("/w/a.mp4", 6.5), 6.0, {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0},
                                                 "sourceUrl": "https://www.youtube.com/watch?v=LEFT0000001&t=40"}),
                     (EMPTY, 5.0), (photo("/w/b.jpg"), 6.0))
        patches = self._moment_mocks(fetch, clip_seconds=lambda a: lengths[os.path.basename(a.local_path)])
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with cap(ALLOW_VERTICAL=True), quiet(), mock.patch.object(upscale, "frame_vertical") as framed:
            got = gapfill.hold_or_animate(doc, laddered=True)
        self.assertEqual(calls, [76.0, 4.5])                                # after it first, then before it
        self.assertEqual((got["moment"], got["card"]), (1, 0))
        m = doc["scenes"][1]["media"]
        self.assertEqual((m["url"], m["clipSeconds"]), (os.path.join(self.work, "m2.mp4"), 5.5))
        framed.assert_called_once_with(os.path.join(self.work, "m2.mp4"))
        self.assertEqual(gapfill.find_repeats(doc), [])

    def test_several_lines_fetch_their_moments_at_once_and_none_repeats(self):
        # Three lines, each beside its own YouTube clip: fetched together (a barrier only
        # three fetches in flight at once can pass), each put on its own line.
        import threading
        barrier = threading.Barrier(3, timeout=10)

        def fetch(vid, work, at, need, title=""):
            barrier.wait()
            p = os.path.join(work, f"{vid}_{int(at)}.mp4")
            with open(p, "wb") as fh:
                fh.write(b"x")
            return p, True, 0
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(9)], self.work)
        specs = []
        for n, vid in enumerate(("AAAAAAAAAA1", "BBBBBBBBBB2", "CCCCCCCCCC3")):
            specs += [(clip(f"/w/{vid}.mp4", 6.5), 6.0, {"assetId": f"yt:{vid}@5", "moment": {"start": 40.0},
                                                      "sourceUrl": f"https://www.youtube.com/watch?v={vid}&t=40"}),
                      (EMPTY, 5.0), (photo(f"/w/p{n}.jpg"), 6.0)]
        doc = doc_of(*specs)
        patches = self._moment_mocks(fetch)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc, laddered=True)
        self.assertEqual((got["moment"], got["card"]), (3, 0))
        urls = [s["media"]["url"] for s in doc["scenes"]]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(gapfill.find_repeats(doc), [])
        self.assertEqual(shotcap.SWAPS.get("moment"), 3)

    def test_a_vertical_runner_up_is_framed_only_where_the_style_allows_vertical(self):
        from src import upscale
        for allow in (True, False):
            alt = runner_up("ALT00000001", 30, self.file(f"v{allow}.mp4"))
            doc = doc_of((photo("/w/a.jpg"), 6.0, {"alternatives": [alt]}), (EMPTY, 5.0), (photo("/w/b.jpg"), 6.0))
            with cap(ALLOW_VERTICAL=allow), quiet(), mock.patch.object(upscale, "frame_vertical") as framed:
                self.assertEqual(gapfill.hold_or_animate(doc)["alternative"], 1)
            if allow:
                framed.assert_called_once_with(alt["localPath"])            # on its blurred copy, as the plan's own
            else:
                framed.assert_not_called()

    def test_a_render_chunk_draws_only_what_every_machine_would(self):
        # fresh=False (handler: a render chunk): no runner-up and no other moment - their checks go over the
        # network, and one machine could take one where another could not. The hold past the cap stays.
        alt = runner_up("PUB00000001", 40, seconds=6.0)
        alt["media"] = {"type": "video", "url": "https://r2.example/alts/s0000_alt1.mp4"}
        doc = doc_of((clip("https://r2.example/a.mp4", 6.0), 6.0, {"alternatives": [alt]}), (EMPTY, 5.0),
                     (photo("https://r2.example/b.jpg"), 6.0))
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(3)], self.work)
        with cap(), quiet(), mock.patch.object(shotcap, "_reach", return_value=True) as reach, \
                mock.patch.object(shotcap, "other_moments", return_value={}) as moments, \
                mock.patch.object(gapfill, "fill_empty", return_value={}) as ladder:
            got = handler._fill_missing_media(doc, fresh=False)
        for m in (reach, moments, ladder):
            m.assert_not_called()
        self.assertEqual(got, 1)
        self.assertEqual(seconds_of(doc), [6.0, 11.0])                      # the photo, held past the cap
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["alternatives"], [alt])

    def test_the_fill_before_the_render_never_runs_the_ladder_again(self):
        # The plan's ladder has run for every line still empty (do_plan, then the check before publishing):
        # handler._fill_missing_media never searches a third time - as before the shot cap.
        doc = doc_of((clip("/w/a.mp4", 6.0), 6.0), (EMPTY, 5.0), (clip("/w/b.mp4", 6.0), 6.0))
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(3)], self.work)
        with cap(), quiet(), mock.patch.object(gapfill, "fill_empty", return_value={}) as ladder, \
                mock.patch.object(shotcap, "other_moments", return_value={}) as moments:
            self.assertEqual(handler._fill_missing_media(doc), 1)
        ladder.assert_not_called()
        moments.assert_called_once()                                        # (free: another moment is still tried)
        self.assertEqual(doc["overlays"][0]["type"], "highlight")           # no footage to spare: its line as text

    def test_a_moment_that_failed_is_never_fetched_again_in_the_same_job(self):
        # The last resort runs several times a job (the plan, the check before publishing, the build's
        # render copy): a moment whose download failed is not asked for again.
        calls = []

        def fetch(vid, work, at, need, title=""):
            calls.append(round(at, 1))
            return "", True, 0                                              # the download fails

        def make():
            return doc_of((clip("/w/a.mp4", 6.5), 6.0, {"assetId": "yt:LEFT0000001@5", "moment": {"start": 40.0},
                                                     "sourceUrl": "https://www.youtube.com/watch?v=LEFT0000001&t=40"}),
                          (EMPTY, 5.0), (clip("/w/b.mp4", 6.0), 6.0))
        gapfill.remember([{"index": i, "query": f"q{i}", "start": 6.0 * i} for i in range(3)], self.work)
        patches = self._moment_mocks(fetch)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with cap(), quiet():
            gapfill.hold_or_animate(make(), laddered=True)
            gapfill.hold_or_animate(make(), laddered=True)
        self.assertEqual(calls, [76.0, 4.5])                                # each moment asked for once
        shotcap.reset()                                                     # a new job asks again
        with cap(), quiet():
            gapfill.hold_or_animate(make(), laddered=True)
        self.assertEqual(calls, [76.0, 4.5, 76.0, 4.5])

    def test_a_fresh_shot_clears_what_the_cap_put_on_its_scene(self):
        s = scene(0, EMPTY, 0.0, 5.0, shotCap={"from": "s0001", "how": "alternative"})
        gapfill.apply_asset(s, MediaAsset(kind="image", source="wikimedia", url="https://x/p.jpg",
                                          local_path="/w/p.jpg"))
        self.assertNotIn("shotCap", s["semanticMetadata"])

    def test_zero_leaves_every_hold_exactly_as_before(self):
        alt = runner_up("ALT00000001", 30, self.file("alt.mp4"))
        doc = doc_of((photo("/w/a.jpg"), 6.0, {"alternatives": [alt]}), (EMPTY, 6.0),
                     (clip("/w/b.mp4", 6.5), 6.0), (EMPTY, 3.0), (clip("/w/c.mp4", 3.5), 3.0))
        with cap(0), quiet(), mock.patch.object(gapfill, "fill_empty", side_effect=AssertionError("searched")):
            got = gapfill.hold_or_animate(doc)
        self.assertEqual(got, {"graphic": 0, "held": 2, "card": 0, "hook": 0})           # the same keys as ever
        # Worked by hand from the rule as it was (and checked against the code before this change on
        # 3,000 random timelines): the last line is split 45/45 frames between clips slowed to 0.6x,
        # then the photo takes 176 frames of the first line and the clip 4 (0.85x): 11.87 s, 7.63 s, 4.5 s.
        self.assertEqual([s["durationInFrames"] for s in doc["scenes"]], [356, 229, 135])
        self.assertEqual([s["startFrame"] for s in doc["scenes"]], [0, 356, 585])
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["alternatives"], [alt])
        self.assertEqual(doc["scenes"][0]["semanticMetadata"]["heldOver"], ["s0001"])
        self.assertEqual(shotcap.SWAPS, {})

    def test_the_hook_boosters_hold_keeps_the_cap_too(self):
        segs = story([("Texas is running out of water, and the state is out of time to fix it today.", 7.0),
                      SHORT, SHORT])
        with mock.patch.multiple(config, HOOK_BOOST=True, HOOK_BOOST_MAX_SHOT=4.0, HOOK_BOOST_MIN_SHOT=3.0):
            cut, parents, info = hookboost.split_opening(segs)
        first = [i for i, par in enumerate(parents) if par == 0]
        self.assertEqual(len(first), 2)
        shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None} for i in range(len(cut))]

        def built(spare):
            """The cut opening, its second shot under the relevance gate; each clip `spare` s longer than its shot."""
            assets = [MediaAsset(kind="video", source="youtube", local_path=f"/tmp/sc/{i}.mp4",
                                 url=f"https://www.youtube.com/watch?v=VID{i:08d}&t=10",
                                 duration=float(cut[i].duration) + spare,
                                 relevance_score=0.5 if i == first[1] else 0.9, quality=0.7)
                      for i in range(len(cut))]
            with mock.patch.object(config, "TREATMENTS", False), mock.patch.object(config, "TRANSITION_PACK", False):
                return timeline.build(cut, shots, assets, audio_url="file:///tmp/vo.mp3",
                                      audio_duration=cut[-1].end, inp={"voice_lufs": -20.0, "fps": FPS})
        with mock.patch.multiple(config, HOOK_BOOST=True, SHOT_MAX_SECONDS=0.0):
            self.assertEqual(hookboost.settle(built(1.5), info)["held"], 1)     # before: the good clip slowed to 0.6x
        with mock.patch.multiple(config, HOOK_BOOST=True, SHOT_MAX_SECONDS=7.0):
            doc = built(1.5)
            self.assertEqual(hookboost.settle(doc, info)["held"], 0)            # now: never slowed to stretch
            self.assertEqual(len(doc["scenes"]), len(cut))
            # A clip with the footage to cover the whole 7 s beat at real speed still takes it...
            self.assertEqual(hookboost.settle(built(4.0), info)["held"], 1)
        with mock.patch.multiple(config, HOOK_BOOST=True, SHOT_MAX_SECONDS=6.0):
            self.assertEqual(hookboost.settle(built(4.0), info)["held"], 0)     # ...but never past the cap


# --------------------------------------------------------------------------- C2. a runner-up of the same sentence first
class RunnerUpsFirst(unittest.TestCase):
    """shotcap.runner_ups_first: after the footage search, before the ladder (handler.do_plan)."""

    def setUp(self):
        gapfill.reset()
        shotcap.reset()
        self.work = tempfile.mkdtemp()
        self.addCleanup(gapfill.reset)
        self.addCleanup(shotcap.reset)
        p = mock.patch.object(shotcap, "_probe", return_value=0.0)          # never ffprobe in a test
        p.start()
        self.addCleanup(p.stop)

    def file(self, name):
        path = os.path.join(self.work, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        return path

    @staticmethod
    def jobs(*seconds):
        out, t = [], 0.0
        for i, s in enumerate(seconds):
            out.append({"index": i, "query": f"q{i}", "intent": f"line {i}", "start": t, "seconds": s})
            t += s
        return out

    def clip_asset(self, vid, start, alts=(), license="Creative Commons Attribution (CC BY)"):
        return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t={int(start)}",
                          local_path=self.file(f"{vid}.mp4"), duration=7.0, license=license,
                          moment={"start": float(start)}, alternatives=list(alts))

    def test_a_piece_that_found_nothing_takes_its_siblings_runner_up(self):
        # Beat 1 was cut into pieces 1 and 2; piece 2 found nothing. A clip the judge approved for
        # piece 1 - the other half of the same sentence - goes on it before any ladder picture.
        alt = runner_up("SIBLING0001", 120, self.file("sib.mp4"), seconds=6.0, score=0.8)
        jobs = self.jobs(4.0, 5.0, 5.0, 4.0)
        results = [self.clip_asset("AAAAAAAAAAA", 10), self.clip_asset("BBBBBBBBBBB", 40, [alt]), None,
                   self.clip_asset("CCCCCCCCCCC", 10)]
        with cap():
            got = shotcap.runner_ups_first(jobs, results, {"parents": [0, 1, 1, 2]})
        self.assertEqual(got, {"own": 0, "sibling": 1})
        a = results[2]
        self.assertEqual((a.kind, a.local_path, a.url, a.identity),
                         ("video", alt["localPath"], alt["url"], alt["assetId"]))     # the id it was judged as
        self.assertEqual((a.duration, a.relevance_score, a.moment), (6.0, 0.8, {"start": 120.0}))
        self.assertEqual(a.license, "Creative Commons Attribution (CC BY)")    # the donor's own search terms
        self.assertTrue(a.review_required)
        self.assertIn("other part of this sentence", a.review_reason)
        self.assertEqual(results[1].alternatives, [])                       # no longer a choice there
        self.assertEqual(shotcap.SWAPS.get("first"), 1)

    def test_its_own_runner_up_comes_before_a_siblings(self):
        # Its own clip broke a variety rule (media.hold_violations): the runner-ups its search judged
        # for this very line come first, ahead of a better-scored one of the other piece.
        own = runner_up("OWN00000001", 60, self.file("own.mp4"), seconds=6.0, score=0.6)
        sib = runner_up("SIBLING0001", 120, self.file("sib.mp4"), seconds=6.0, score=0.9)
        held = {1: (self.clip_asset("HELD0000001", 10, [own]), "a repeated video", "soft")}
        results = [self.clip_asset("BBBBBBBBBBB", 40, [sib]), None]
        with cap():
            got = shotcap.runner_ups_first(self.jobs(5.0, 5.0), results, {"parents": [0, 0]}, held=held)
        self.assertEqual(got, {"own": 1, "sibling": 0})
        self.assertEqual(results[1].local_path, own["localPath"])
        self.assertIn("for this line", results[1].review_reason)
        self.assertEqual(results[0].alternatives, [sib])

    def test_a_runner_up_of_another_sentence_is_left_for_later(self):
        # Only the line's own sentence goes before the ladder; the shot beside it from another beat is
        # one of the last resort's choices (gapfill.hold_or_animate, alternative_for).
        alt = runner_up("OTHER000001", 120, self.file("o.mp4"), seconds=6.0)
        results = [self.clip_asset("AAAAAAAAAAA", 10, [alt]), None, self.clip_asset("CCCCCCCCCCC", 10)]
        with cap():
            got = shotcap.runner_ups_first(self.jobs(4.0, 5.0, 4.0), results, {"parents": [0, 1, 2]})
        self.assertEqual(got, {"own": 0, "sibling": 0})
        self.assertIsNone(results[1])
        self.assertEqual(results[0].alternatives, [alt])

    def test_never_too_short_never_a_file_this_machine_lacks_never_a_repeat(self):
        short = runner_up("SHORT000001", 60, self.file("short.mp4"), seconds=3.0)            # 3 s for a 5 s line
        remote = runner_up("REMOTE00001", 60, "/part-worker/work/alt_1.mp4", seconds=8.0)    # a fan-out part's disk
        next_video = runner_up("CCCCCCCCCCC", 200, self.file("c2.mp4"), seconds=8.0)          # the next line's video
        results = [self.clip_asset("AAAAAAAAAAA", 10),
                   self.clip_asset("BBBBBBBBBBB", 40, [short, remote, next_video]), None,
                   self.clip_asset("CCCCCCCCCCC", 10)]
        with cap():
            got = shotcap.runner_ups_first(self.jobs(4.0, 5.0, 5.0, 4.0), results, {"parents": [0, 1, 1, 2]})
        self.assertEqual(got, {"own": 0, "sibling": 0})
        self.assertIsNone(results[2])
        self.assertEqual(len(results[1].alternatives), 3)                   # all still the editor's choices

    def test_a_video_already_at_its_limit_is_passed_over(self):
        # media.may_place: at most MAX_MOMENTS_PER_VIDEO scenes of one video.
        alt = runner_up("AAAAAAAAAAA", 300, self.file("a2.mp4"), seconds=6.0)
        results = [self.clip_asset("AAAAAAAAAAA", 10), self.clip_asset("BBBBBBBBBBB", 40, [alt]), None]
        with cap(MAX_MOMENTS_PER_VIDEO=1):
            got = shotcap.runner_ups_first(self.jobs(30.0, 5.0, 5.0), results, {"parents": [0, 1, 1]})
        self.assertEqual(got["sibling"], 0)
        with cap(MAX_MOMENTS_PER_VIDEO=4, SAME_VIDEO_GAP_SECONDS=0.0):
            got = shotcap.runner_ups_first(self.jobs(30.0, 5.0, 5.0), results, {"parents": [0, 1, 1]})
        self.assertEqual(got["sibling"], 1)

    def test_off_nothing_changes(self):
        alt = runner_up("SIBLING0001", 120, self.file("sib.mp4"), seconds=6.0)
        results = [self.clip_asset("BBBBBBBBBBB", 40, [alt]), None]
        with cap(0):
            self.assertEqual(shotcap.runner_ups_first(self.jobs(5.0, 5.0), results, {"parents": [0, 0]}),
                             {"own": 0, "sibling": 0})
        self.assertIsNone(results[1])
        self.assertEqual(results[0].alternatives, [alt])


class LadderSpeed(unittest.TestCase):
    """With the cap on, the fallback ladder never puts a clip on a line it would have to be slowed to fill."""

    def setUp(self):
        gapfill.reset()
        self.addCleanup(gapfill.reset)
        self.work = tempfile.mkdtemp()

    def run_ladder(self, seconds):
        lib_clip = MediaAsset(kind="video", source="youtube", url="https://www.youtube.com/watch?v=LIB00000001&t=5",
                              local_path=os.path.join(self.work, "lib.mp4"), duration=3.0)
        still = MediaAsset(kind="image", source="web_image", url="https://x/p.jpg",
                           local_path=os.path.join(self.work, "p.jpg"))
        results = {}
        jobs = [{"index": 0, "query": "the dry lake", "start": 0.0, "seconds": 5.0, "visual_type": "footage"}]
        from src import packs
        with cap(seconds), mock.patch.object(packs, "usable", return_value=False), \
                mock.patch.object(gapfill, "_from_library", return_value=lib_clip), \
                mock.patch.object(gapfill, "_from_reserve", return_value=None), \
                mock.patch.object(gapfill, "_from_still", return_value=still), \
                mock.patch.object(timeline, "_clip_seconds", side_effect=lambda a: float(a.duration or 0)):
            got = gapfill.fill_empty(jobs, results, self.work, library=object(), indices=[0], label="test")
        return results[0], got

    def test_a_clip_too_short_for_its_line_goes_to_the_next_step(self):
        asset, got = self.run_ladder(7.0)
        self.assertEqual((asset.kind, got["library"], got["still"]), ("image", 0, 1))   # 3 s for 5 s: never slowed
        asset, got = self.run_ladder(0.0)
        self.assertEqual((asset.kind, got["library"]), ("video", 1))                    # off: as before (0.6x)


# --------------------------------------------------------------------------- D. graphics keep their length; the report
class GraphicsAndTheReport(unittest.TestCase):
    def setUp(self):
        shotcap.reset()
        self.addCleanup(shotcap.reset)

    def test_graphics_and_animation_scenes_keep_their_own_lengths(self):
        doc = doc_of((photo("/w/a.jpg"), 6.0), ({"type": "animation", "url": "", "source": "template"}, 9.5),
                     (photo("/w/b.jpg"), 6.0), (clip("/w/c.mp4", 9.0), 8.5))
        doc["scenes"][1]["visualType"] = "animation"
        doc["scenes"][1]["animation"] = {"type": "number-roll"}
        with cap():
            over = shotcap.over_cap(doc)
            self.assertFalse(shotcap.is_shot(doc["scenes"][1]))
        self.assertEqual(over, [{"scene": "s0003", "seconds": 8.5, "held": False}])     # only the footage

    def test_an_animation_is_never_held_over_a_line(self):
        doc = doc_of(({"type": "animation", "url": "", "source": "template"}, 4.0), (EMPTY, 3.0),
                     (clip("/w/b.mp4", 6.5), 6.5))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["card"]), (0, 1))
        self.assertEqual(seconds_of(doc), [4.0, 3.0, 6.5])
        # Beside a photo the line goes to the photo (held past the cap, up to 12 s), never to the graphic.
        doc = doc_of(({"type": "animation", "url": "", "source": "template"}, 4.0), (EMPTY, 3.0),
                     (photo("/w/b.jpg"), 6.5))
        with cap(), quiet():
            got = gapfill.hold_or_animate(doc)
        self.assertEqual((got["held"], got["long"], got["card"]), (1, 1, 0))
        self.assertEqual(seconds_of(doc), [4.0, 9.5])

    def test_a_frame_or_two_of_rounding_is_not_a_long_shot(self):
        doc = doc_of((photo("/w/a.jpg"), 7.0), (photo("/w/b.jpg"), 7.0))
        doc["scenes"][0]["durationInFrames"] += 2
        doc["scenes"][1]["durationInFrames"] += 3
        with cap():
            self.assertEqual([o["scene"] for o in shotcap.over_cap(doc)], ["s0001"])

    def test_the_report_says_what_was_cut_and_what_replaced_a_hold(self):
        segs = story([SHORT, SENTENCE, SHORT, COMMA])
        with cap():
            _, _, info = shotcap.prepare(segs, {}, {}, until=segs[-1].end)
            doc = doc_of((photo("/w/a.jpg"), 5.0), (EMPTY, 6.0), (photo("/w/b.jpg"), 5.0),
                         (clip("/w/c.mp4", 5.0), 5.0), (EMPTY, 4.0), (clip("/w/d.mp4", 5.0), 5.0))
            with quiet():
                gapfill.hold_or_animate(doc)
            rep = shotcap.report(doc, info)
        self.assertEqual((rep["seconds"], rep["enabled"]), (7.0, True))
        self.assertEqual((rep["before"]["over"], rep["planned"]["over"], rep["cut"], rep["shotsAdded"]), (2, 0, 2, 2))
        self.assertEqual(rep["before"]["share"], 0.5)
        # The photos are held past the cap (8 s each) instead of a text card; the clips have no footage to spare.
        self.assertEqual((rep["after"]["shots"], rep["after"]["over"], rep["after"]["longest"]), (4, 2, 8.0))
        self.assertEqual(rep["holds"], {"held": 0, "refused": 2, "alternative": 0, "moment": 0, "ladder": 0,
                                        "long": 1, "card": 1})
        self.assertEqual(rep["runnerUpsFirst"], 0)
        self.assertEqual(rep["left"], [{"scene": "s0000", "seconds": 8.0, "held": True},
                                       {"scene": "s0002", "seconds": 8.0, "held": True}])
        self.assertEqual(len(rep["examples"]), 2)
        self.assertNotIn("parents", rep)
        json.dumps(rep)                                                     # goes into the saved timeline
        with cap(0):
            self.assertEqual(shotcap.report(doc, info), {"seconds": 0.0, "enabled": False})

    def test_the_report_keeps_a_dozen_examples_however_many_cuts(self):
        segs = story([SENTENCE] * 30)
        with cap():
            _, _, info = shotcap.prepare(segs, {}, {}, until=segs[-1].end)
        self.assertEqual((info["cut"], len(info["examples"])), (30, 12))


# --------------------------------------------------------------------------- E. a whole plan
class _Built(Exception):
    pass


BRIEF = {"kind": "explainer", "summary": "", "event": "Texas drought", "year": 2026, "recent": False,
         "places": ["Texas"], "people": [], "hookBeats": [0], "cast": [], "sections": []}


class AWholePlan(unittest.TestCase):
    LINES = [SHORT, SENTENCE, SHORT, COMMA, NAMES, SHORT, VERY_LONG, SHORT, SENTENCE, SHORT]

    def setUp(self):
        gapfill.reset()
        shotcap.reset()
        self.addCleanup(gapfill.reset)
        self.addCleanup(shotcap.reset)
        self.segs = story(self.LINES)
        self.total = self.segs[-1].end

    def plan(self, seconds, empty=(), alts=None):
        """
        handler.do_plan up to the timeline, offline: (beats planned, the footage search's lines, assets).
        `alts`: {line: runner-ups} - that line's search found a clip with these pick-a-shot runner-ups.
        """
        seen = {}

        def director_plan(segments, **kw):
            seen["segments"] = segments
            return ([{"query": f"q{i}", "visualType": "footage", "overlay": None} for i in range(len(segments))],
                    "ai", [])

        def found(i):
            if i in (alts or {}):
                return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=WIN{i:08d}&t=10",
                                  local_path=f"/w/c{i}.mp4", duration=9.0, moment={"start": 10.0},
                                  alternatives=list(alts[i]))
            return MediaAsset(kind="image", source="wikimedia", url=f"https://x/p{i}.jpg", local_path=f"/w/p{i}.jpg")

        def source_many(jobs_, work, **kw):
            seen["jobs"] = sorted(jobs_, key=lambda j: j["index"])
            return [None if j["index"] in empty else found(j["index"]) for j in seen["jobs"]]

        def ladder(jobs_, results, work, **kw):
            seen["ladder"] = [k for k, a in enumerate(results) if a is None]      # the lines it was asked for
            return {"asked": len(seen["ladder"]), "left": len(seen["ladder"])}

        def build(segments, shots_, assets, **kw):
            seen["shots"], seen["assets"] = shots_, list(assets)
            raise _Built()
        with mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"), \
                mock.patch.object(handler.storage, "download", return_value="/w/vo.mp3"), \
                mock.patch.object(handler.renderer, "probe_duration", return_value=self.total), \
                mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]), \
                mock.patch.object(handler.transcribe, "segment_words", return_value=self.segs), \
                mock.patch.object(handler.director, "story_brief", return_value=json.loads(json.dumps(BRIEF))), \
                mock.patch.object(handler.director, "plan", side_effect=director_plan), \
                mock.patch.object(handler.library.Library, "load", return_value=None), \
                mock.patch.object(handler.fanout, "enabled_for", return_value=False), \
                mock.patch.object(handler.pools, "source_by_subject", return_value={}), \
                mock.patch.object(handler.media, "source_many", side_effect=source_many), \
                mock.patch.object(handler.media, "rescue_fill", return_value={}), \
                mock.patch.object(handler.gapfill, "fill_empty", side_effect=ladder), \
                mock.patch.object(handler.timeline, "build", side_effect=build), \
                mock.patch.multiple(config, UPSCALE_ENABLED=False, ALLOW_VERTICAL=False, SUBJECT_POOLS=True,
                                    MENTION_CUTS=False, HOOK_BOOST=False, SHOT_MAX_SECONDS=float(seconds),
                                    MIN_SCENE_SECONDS=5.0, CUT_LEAD_SECONDS=0.0):
            with self.assertRaises(_Built):
                handler.do_plan({"audio_url": "vo.mp3", "project_id": ""}, tempfile.mkdtemp(), handler.Reporter(""))
        handler.vision.set_story({})
        return seen

    def finish(self, seen, seconds):
        """The timeline as do_plan builds it, the last resort, and the report."""
        with mock.patch.multiple(config, TREATMENTS=False, TRANSITION_PACK=False, ANIMATION_FILL=False,
                                 HOOK_SECONDS=0.0, SHOT_MAX_SECONDS=float(seconds)):
            doc = timeline.build(seen["segments"], seen["shots"], seen["assets"], audio_url="file:///tmp/vo.mp3",
                                 audio_duration=self.total, inp={"voice_lufs": -20.0, "fps": FPS})
            last = gapfill.hold_or_animate(doc, laddered=True)
            return doc, last, shotcap.report(doc)

    def test_zero_plans_the_same_beats_and_asks_for_the_same_clips(self):
        seen = self.plan(0)
        self.assertIs(seen["segments"], self.segs)                          # the very beats the cutter made
        self.assertEqual([j["seconds"] for j in seen["jobs"]], [s.duration for s in self.segs])
        doc, _, rep = self.finish(seen, 0)
        self.assertEqual(rep, {"seconds": 0.0, "enabled": False})
        self.assertEqual(len(doc["scenes"]), len(self.segs))
        self.assertEqual(max(seconds_of(doc)), 19.5)

    def test_no_shot_runs_past_the_cap_and_nothing_is_shown_twice(self):
        before = self.plan(0)
        old, _, _ = self.finish(before, 0)
        seen = self.plan(7)
        self.assertGreater(len(seen["segments"]), len(self.segs))
        self.assertEqual(len(seen["jobs"]), len(seen["segments"]))          # every piece is searched for on its own
        self.assertLessEqual(max(j["seconds"] for j in seen["jobs"]), 7.0 + 1e-6)
        doc, last, rep = self.finish(seen, 7)
        over_before = [s for s in seconds_of(old) if s > 7.0]
        self.assertEqual((len(over_before), max(over_before)), (5, 19.5))   # 5 of 10 shots, up to 19.5 s
        self.assertEqual(shotcap.over_cap(doc), [])
        self.assertLessEqual(max(seconds_of(doc)), 7.0 + 2 / FPS)
        self.assertEqual((rep["before"]["over"], rep["cut"], rep["after"]["over"]), (5, 5, 0))
        files = [s["media"]["url"] for s in doc["scenes"]]
        self.assertEqual(len(files), len(set(files)))                       # each shot its own picture
        self.assertEqual(gapfill.find_repeats(doc), [])
        for a, b in zip(doc["scenes"], doc["scenes"][1:]):                  # the narration is still tiled
            self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
        self.assertEqual([w["text"] for s in doc["scenes"] for w in s["words"]],
                         [w.text for s in self.segs for w in s.words])

    def test_each_clip_is_found_for_the_time_its_shot_is_on_screen(self):
        # Beats with a pause after them: on screen until the next line's first word.
        self.segs = [Segment(text=s.text, start=s.start, end=s.words[-1].end, words=s.words) for s in self.segs]
        seen = self.plan(7)
        on_screen = shotcap.screen_seconds(seen["segments"], self.total)
        for j, seg, shown in zip(seen["jobs"], seen["segments"], on_screen):
            self.assertGreaterEqual(j["seconds"], seg.duration - 1e-6)
            self.assertAlmostEqual(j["seconds"], max(shown, seg.duration), places=6)
            self.assertLessEqual(j["seconds"], 7.0 + 1e-6)
        old = self.plan(0)
        self.assertEqual([j["seconds"] for j in old["jobs"]], [s.duration for s in self.segs])

    def test_a_beat_its_words_cannot_cut_asks_for_its_whole_time_on_screen(self):
        # One word, then ten seconds before the next line: no cut keeps it within the cap, and
        # its clip must still play at real speed (it used to be asked for at most 7 s, then slowed).
        t = self.total
        lone = Segment(text="Silence.", start=t + 0.5, end=t + 1.1, words=[Word("Silence.", t + 0.5, t + 1.1)])
        after = beat(SHORT[0], t + 10.5, SHORT[1])
        self.segs = self.segs + [lone, after]
        self.total = after.end
        seen = self.plan(7)
        k = next(n for n, s in enumerate(seen["segments"]) if s.text == "Silence.")
        self.assertAlmostEqual(seen["jobs"][k]["seconds"], 10.0, places=6)

    def test_a_piece_that_found_nothing_takes_a_runner_up_of_its_sentence_before_the_ladder(self):
        # SENTENCE (line 1, 8.9 s) is cut into pieces 1 and 2. Piece 1's search found a clip with a
        # pick-a-shot runner-up on this disk (media._best_of: localPath); piece 2 found nothing.
        work = tempfile.mkdtemp()
        path = os.path.join(work, "yt_SIBLING0001_120000_9000.mp4")
        with open(path, "wb") as fh:
            fh.write(b"x")
        alt = runner_up("SIBLING0001", 120, path, seconds=9.0)
        with mock.patch.object(shotcap, "_probe", return_value=0.0):
            seen = self.plan(7, empty={2}, alts={1: [alt]})
        segs = seen["segments"]
        self.assertIs(segs[1].words[0], self.segs[1].words[0])              # pieces 1 and 2: one sentence
        self.assertIs(segs[2].words[-1], self.segs[1].words[-1])
        got = seen["assets"][2]
        self.assertEqual((got.local_path, got.identity), (path, alt["assetId"]))
        self.assertEqual(seen["assets"][1].alternatives, [])               # taken off piece 1's choices
        self.assertNotIn(2, seen.get("ladder", []))                         # the ladder was never asked for it
        # Off: the line goes to the ladder as before.
        shotcap.reset()
        old = self.plan(0, empty={1}, alts={0: [dict(alt)]})
        self.assertEqual(old["ladder"], [1])
        self.assertIsNone(old["assets"][1])

    def test_lines_nothing_was_found_for_never_make_a_shot_past_twelve_seconds(self):
        empty = {2, 6, 7, 11}
        seen = self.plan(7, empty=empty)
        doc, last, rep = self.finish(seen, 7)
        self.assertLessEqual(max(seconds_of(doc)), 12.0 + 2 / FPS)
        # Every shot over the cap is one held over a line nothing was found for - and no text card,
        # with a photo beside every empty line.
        self.assertTrue(all(o["held"] for o in shotcap.over_cap(doc)))
        self.assertEqual((last["held"], last["card"]), (len(empty), 0))
        self.assertEqual(rep["after"]["over"], len(shotcap.over_cap(doc)))
        self.assertEqual(rep["holds"]["held"] + rep["holds"]["long"], last["held"])
        # Before: the same empty lines, held however long it took.
        shotcap.reset()
        old_seen = self.plan(0, empty={1, 3, 6})
        old, _, _ = self.finish(old_seen, 0)
        self.assertGreater(max(seconds_of(old)), 12.0)


if __name__ == "__main__":
    unittest.main()
