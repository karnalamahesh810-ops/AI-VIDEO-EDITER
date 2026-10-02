"""
The hook booster (src/hookboost.py; the owner, 2026-10-02): the first ~30 seconds hit harder.

  A. cutting the opening: a beat longer than ~3.5 s in the first 30 s becomes 2-3
     shots of about 1.8-3 s, cut on word boundaries (never mid-word, never a
     one-word shot, a clause end or a breath before a phrase), the brief's beat
     numbers follow; later and shorter beats and a flag that is off change nothing;
  B. the hook's picks: footage with scale, people and action wins a near-tie, a
     clearly better-fitting clip always wins, and the hook prefers footage that moves;
  C. punch: a slow push on stills and static clips, a soft whoosh on the first cuts at
     the owner's sound level, no text graphic in the first five seconds unless it is
     a date or a number;
  D. the cold open (HOOK_TEASER): 2-4 one-second flashes of the most striking later
     shots under a hook first line, each shown again at its own line and nowhere else;
  E. the report in doc.meta.hookBoost, and a flag that is off leaves the document as it was.
"""
import json
import os
import unittest
from unittest import mock

import handler
from src import config, gapfill, hookboost, media, sfxplan, timeline, treatments
from src import transcribe
from src.media import MediaAsset
from src.transcribe import Segment, Word

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30


def words_of(text, start, pace=0.34):
    """Evenly spaced words; a comma breathes a little, a full stop more."""
    out, t = [], float(start)
    for tok in text.split():
        out.append(Word(text=tok, start=round(t, 3), end=round(t + pace * 0.85, 3)))
        t += pace + (0.12 if tok.endswith(",") else 0.0) + (0.3 if tok.endswith((".", "?", "!")) else 0.0)
    return out


def beat(text, start, seconds=None):
    """A beat of the narration: its words from `start`, on screen for `seconds` (else until its last word ends)."""
    words = words_of(text, start)
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


OPENING = [("Texas is running out of water, and the state is out of time to fix it.", 5.0),     # 0-5   long
           ("Short beat here now.", 2.4),                                                       # 5-7.4 short
           ("The reservoirs that fed Austin have dropped to a fraction of their size, "
            "and the cracked mud now stretches for miles.", 7.2),                               # long
           ("Wells are failing across the Hill Country every single week now.", 4.4)]           # long
SHORT = [(f"Short filler line number {n} here.", 3.0) for n in range(4)]                  # 19-31 s: nothing to cut
LATER = [("Farmers in the valley are selling their cattle because the pastures turned to dust.", 6.0),
         ("City leaders met on Tuesday to talk about rationing the supply.", 4.4)]            # from 31 s: past the opening


def plain(n=30):
    return [(f"Plain line number {i} says what happens next in the story today.", 4.0) for i in range(n)]


def video(i, rel=0.8, quality=0.7, desc="", spec="", **kw):
    return MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=VID{i:08d}&t=10",
                      local_path=f"/tmp/hb/{i}.mp4", duration=8.0, relevance_score=rel, quality=quality,
                      content_description=desc, specificity=spec, **kw)


def still(i):
    return MediaAsset(kind="image", source="wikimedia", url=f"https://x/p{i}.jpg", local_path=f"/tmp/hb/p{i}.jpg")


def build(segs, assets=None, shots=None, inp=None, treatments_on=False, pack=False):
    """timeline.build offline: fake clips, an assumed voice."""
    n = len(segs)
    assets = assets if assets is not None else [video(i) for i in range(n)]
    shots = shots if shots is not None else [{"query": f"q{i}", "visualType": "footage", "overlay": None}
                                             for i in range(n)]
    job = {"voice_lufs": -20.0, **(inp or {})}
    with mock.patch.object(config, "TREATMENTS", treatments_on), mock.patch.object(config, "TRANSITION_PACK", pack), \
            mock.patch.object(media, "motion_of", return_value=None):
        return timeline.build(segs, shots, assets, audio_url="file:///tmp/vo.mp3",
                              audio_duration=segs[-1].end + 1.0, inp=job)


def boosted(**over):
    """Patch the booster on (and any other setting)."""
    return mock.patch.multiple(config, HOOK_BOOST=True, **over)


# --------------------------------------------------------------------------- A. cutting the opening
class CuttingTheOpening(unittest.TestCase):
    def setUp(self):
        self.segs = story(OPENING + SHORT + LATER + plain(10))

    def test_flag_off_leaves_the_beats_alone(self):
        brief = {"hookBeats": [0, 1], "sections": [{"from": 0, "to": 2}]}
        with mock.patch.object(config, "HOOK_BOOST", False):
            out, focus, info = hookboost.prepare(self.segs, brief, {1: {"subject": "x"}})
        self.assertIs(out, self.segs)
        self.assertEqual((focus, info), ({1: {"subject": "x"}}, {}))
        self.assertEqual(brief, {"hookBeats": [0, 1], "sections": [{"from": 0, "to": 2}]})

    def test_a_long_opening_beat_becomes_two_or_three_shots_of_two_to_three_seconds(self):
        with boosted():
            out, parents, info = hookboost.split_opening(self.segs)
        self.assertGreater(len(out), len(self.segs))
        for idx, seg in enumerate(self.segs):
            pieces = [p for p, par in zip(out, parents) if par == idx]
            if seg.start >= 30 or seg.duration <= 3.5:
                self.assertEqual(pieces, [seg], idx)                  # later and short beats: the same object
                continue
            self.assertIn(len(pieces), (2, 3), idx)
            for p in pieces:
                self.assertGreaterEqual(p.duration, 1.8 - 1e-6, (idx, p.text))
                self.assertLessEqual(p.duration, 3.3, (idx, p.text))        # "about 3 s"
            self.assertAlmostEqual(sum(p.duration for p in pieces), seg.duration, places=6)

    def test_every_cut_is_on_a_word_start_and_no_shot_is_one_word(self):
        with boosted():
            out, parents, _ = hookboost.split_opening(self.segs)
        for idx, seg in enumerate(self.segs):
            pieces = [p for p, par in zip(out, parents) if par == idx]
            self.assertEqual([w for p in pieces for w in p.words], list(seg.words))     # every word, once, in order
            self.assertEqual(" ".join(p.text for p in pieces).split(), seg.text.split())
            self.assertEqual((pieces[0].start, pieces[-1].end), (seg.start, seg.end))
            for a, b in zip(pieces, pieces[1:]):
                self.assertEqual(a.end, b.start)                           # the visual track still tiles
                self.assertEqual(b.start, b.words[0].start)                # the cut is the next word's start
            if len(pieces) > 1:
                self.assertTrue(all(len(p.words) >= 2 for p in pieces))

    def test_a_cut_prefers_a_clause_end_to_the_middle_of_a_phrase(self):
        seg = beat("Texas is running out of water, and the state is out of time to fix it.", 0.0, 5.0)
        with boosted():
            out, _, _ = hookboost.split_opening([seg])
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0].text.endswith("water,"), out[0].text)

    def test_the_opening_gets_faster(self):
        with boosted():
            out, _, info = hookboost.split_opening(self.segs)
        self.assertEqual(info["before"]["scenes"], len([s for s in self.segs if s.start < 30]))
        self.assertGreater(info["afterPlan"]["scenes"], info["before"]["scenes"])
        self.assertLess(info["afterPlan"]["avgShotSeconds"], info["before"]["avgShotSeconds"])
        self.assertLessEqual(info["afterPlan"]["avgShotSeconds"], 3.0)
        self.assertEqual(info["shotsAdded"], len(out) - len(self.segs))

    def test_the_window_is_the_flags(self):
        with boosted(HOOK_BOOST_SECONDS=6.0):
            out, parents, _ = hookboost.split_opening(self.segs)
        self.assertEqual(len([p for p in parents if p == 2]), 1)           # the long beat at 7.4 s is outside 6 s
        self.assertGreater(len([p for p in parents if p == 0]), 1)
        self.assertEqual(len([p for p in parents if p == 3]), 1)

    def test_a_beat_without_word_timings_or_with_too_few_words_is_left_whole(self):
        bare = Segment(text="Texas is running out of water and time.", start=0.0, end=5.0, words=[])
        few = Segment(text="Water. Gone.", start=5.0, end=9.0, words=words_of("Water. Gone.", 5.0))
        with boosted():
            out, _, _ = hookboost.split_opening([bare, few])
        self.assertEqual(out, [bare, few])

    def test_the_briefs_beat_numbers_and_the_focus_follow_the_new_beats(self):
        brief = {"hookBeats": [0, 2], "sections": [{"from": 0, "to": 3}]}
        with boosted():
            _, parents, _ = hookboost.split_opening(self.segs)
            out, focus, info = hookboost.prepare(self.segs, brief, {0: {"subject": "Texas"}, 2: {"subject": "Austin"}})
        first_of = {old: parents.index(old) for old in set(parents)}
        self.assertEqual(sorted(focus), [first_of[0], first_of[2]])         # on the first piece of each beat
        self.assertEqual(focus[first_of[0]], {"subject": "Texas"})
        self.assertEqual(focus[first_of[2]], {"subject": "Austin"})
        # hookBeats 0 and 2 now name every piece of those beats; the section spans the pieces of beats 0..3.
        self.assertEqual(brief["hookBeats"], [i for i, par in enumerate(parents) if par in (0, 2)])
        self.assertEqual(brief["sections"][0], {"from": 0, "to": max(i for i, par in enumerate(parents) if par == 3)})
        self.assertGreater(len(brief["hookBeats"]), 2)

    def test_prepare_never_raises(self):
        with boosted(), mock.patch.object(hookboost, "split_opening", side_effect=RuntimeError("boom")):
            out, focus, info = hookboost.prepare(self.segs, {}, {})
        self.assertIs(out, self.segs)
        self.assertEqual(info, {})

    def test_real_narration_the_lake_mead_opening(self):
        with open(os.path.join(HERE, "fixtures", "words_lake_mead.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        words = [Word(text=t, start=s, end=e) for t, s, e in d["words"]]
        segs = transcribe.segment_words(words, origin=0.0, until=d["duration"])
        with boosted():
            out, parents, info = hookboost.split_opening(segs)
        opening = [s for s in out if s.start < 30]
        self.assertGreater(len(opening), len([s for s in segs if s.start < 30]))
        self.assertTrue(all(p.duration <= 3.3 for p in opening), [round(p.duration, 2) for p in opening])
        self.assertTrue(all(p.duration >= 1.8 - 1e-6 for p in opening))
        later = [i for i, s in enumerate(segs) if s.start >= 30]
        self.assertEqual([s for s, par in zip(out, parents) if par in later], [segs[i] for i in later])   # untouched

    def test_the_flags_can_be_set_for_one_job(self):
        for key in ("HOOK_BOOST", "HOOK_BOOST_SECONDS", "HOOK_TEASER"):
            self.assertIn(key, handler.CONFIG_OVERRIDABLE)
        before = config.HOOK_BOOST
        previous = handler._apply_config({"HOOK_BOOST": "true", "HOOK_BOOST_SECONDS": "20"})
        try:
            self.assertTrue(config.HOOK_BOOST)
            self.assertEqual(config.HOOK_BOOST_SECONDS, 20.0)
        finally:
            handler._restore_config(previous)
        self.assertEqual(config.HOOK_BOOST, before)
        self.assertFalse(config.HOOK_BOOST)                                # off unless asked for
        self.assertFalse(config.HOOK_TEASER)


# --------------------------------------------------------------------------- B. the hook's picks
class TheHooksPicks(unittest.TestCase):
    QUIET = "a quiet street with parked cars"
    BIG = "aerial view of a flooded neighborhood with rescue boats, people and debris"

    def pick(self, a, b, hook=True):
        token = media._IN_HOOK.set(hook)
        try:
            winner = media._best_of([a, b])
        finally:
            media._IN_HOOK.reset(token)
        return winner

    def test_scale_people_and_action_win_a_near_tie_in_the_hook(self):
        quiet, big = video(1, rel=0.80, desc=self.QUIET), video(2, rel=0.79, desc=self.BIG, spec="event")
        with mock.patch.object(config, "HOOK_BOOST", False):
            self.assertIs(self.pick(quiet, big), quiet)
        quiet, big = video(1, rel=0.80, desc=self.QUIET), video(2, rel=0.79, desc=self.BIG, spec="event")
        with boosted():
            self.assertIs(self.pick(quiet, big), big)

    def test_a_clearly_better_fitting_clip_still_wins(self):
        quiet, big = video(1, rel=0.95, desc=self.QUIET), video(2, rel=0.74, desc=self.BIG, spec="event")
        with boosted():
            self.assertIs(self.pick(quiet, big), quiet)

    def test_outside_the_hook_nothing_changes(self):
        quiet, big = video(1, rel=0.80, desc=self.QUIET), video(2, rel=0.79, desc=self.BIG, spec="event")
        with boosted():
            self.assertIs(self.pick(quiet, big, hook=False), quiet)

    def test_drama_counts_what_the_judge_saw(self):
        self.assertEqual(hookboost.drama(video(1, desc=self.QUIET)), 0.0)
        self.assertGreater(hookboost.drama(video(1, desc=self.BIG, spec="event")), 0.9)
        with boosted(HOOK_BOOST_DRAMA=0.05):
            self.assertAlmostEqual(hookboost.rank_bonus(video(1, desc=self.BIG, spec="event")), 0.05, places=2)
        with mock.patch.object(config, "HOOK_BOOST", False):
            self.assertEqual(hookboost.rank_bonus(video(1, desc=self.BIG)), 0.0)

    def test_the_hook_prefers_footage_that_moves_even_without_the_global_preference(self):
        token = media._IN_HOOK.set(True)
        try:
            with mock.patch.object(config, "MOTION_PREFERENCE", 0.0), mock.patch.object(config, "HOOK_BOOST", False):
                self.assertEqual(media._motion_weight(), 0.0)
            with boosted(MOTION_PREFERENCE=0.0, HOOK_BOOST_MOTION=0.04):
                self.assertAlmostEqual(media._motion_weight(), 0.08)         # doubled in the hook, as MOTION_PREFERENCE is
                moving, frozen = video(1, final_score=0.6), video(2, final_score=0.6)
                with mock.patch.object(media, "motion_of", return_value={"motion": 0.9, "static": False, "slideshow": False}):
                    media.apply_motion(moving)
                with mock.patch.object(media, "motion_of", return_value={"motion": 0.0, "static": True, "slideshow": False}):
                    media.apply_motion(frozen)
                self.assertGreater(moving.final_score, 0.6)
                self.assertLess(frozen.final_score, 0.6)
        finally:
            media._IN_HOOK.reset(token)
        with boosted():
            self.assertEqual(media._motion_weight(hook=False), 0.0)          # only the hook


# --------------------------------------------------------------------------- C. punch
class Punch(unittest.TestCase):
    def doc(self, assets=None, motion=None, **over):
        segs = story(OPENING + SHORT + LATER + plain(6))
        assets = assets or [video(i) for i in range(len(segs))]
        with boosted(**over):
            return self.build(segs, assets, motion)

    def build(self, segs, assets, motion):
        shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None} for i in range(len(segs))]
        job = {"voice_lufs": -20.0}
        with mock.patch.object(config, "TREATMENTS", False), mock.patch.object(config, "TRANSITION_PACK", False), \
                mock.patch.object(media, "motion_of", return_value=motion):
            return timeline.build(segs, shots, assets, audio_url="file:///tmp/vo.mp3",
                                  audio_duration=segs[-1].end + 1.0, inp=job)

    STATIC = {"motion": 0.05, "static": True, "slideshow": False}
    MOVING = {"motion": 0.8, "static": False, "slideshow": False}

    def test_a_static_clip_in_the_opening_gets_a_slow_push_and_a_moving_one_does_not(self):
        segs = story(OPENING + SHORT + LATER + plain(6))
        static = self.doc(motion=self.STATIC)
        moving = self.doc(motion=self.MOVING)
        for sc in static["scenes"]:
            if sc["startFrame"] / FPS < 30:
                self.assertEqual(sc["reframe"]["from"], {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, sc["id"])
                self.assertLess(sc["reframe"]["to"]["w"], 1.0)
                self.assertGreater(sc["reframe"]["to"]["w"], 0.85)             # subtle
            else:
                self.assertNotIn("reframe", sc, sc["id"])                      # later scenes untouched
        self.assertFalse([sc for sc in moving["scenes"] if "reframe" in sc])
        self.assertEqual(len(static["scenes"]), len(segs))
        self.assertGreater(static["meta"]["hookBoost"]["pushIns"]["clips"], 3)

    def test_a_still_in_the_opening_moves_even_where_the_style_holds_stills(self):
        segs = story(OPENING + SHORT + LATER + plain(6))
        assets = [still(i) if i in (0, 1, 8) else video(i) for i in range(len(segs))]
        with mock.patch.object(config, "STILL_MOTION", "none"):
            doc = self.doc(assets=assets, motion=self.MOVING)
        self.assertEqual(doc["scenes"][0]["motion"], "zoom-in")
        self.assertEqual(doc["scenes"][1]["motion"], "zoom-in")
        self.assertEqual(doc["scenes"][8]["motion"], "none")                   # past the opening: as the style says
        self.assertEqual(doc["meta"]["hookBoost"]["pushIns"]["stills"], 2)

    def test_push_in_leaves_a_scene_that_already_moves_a_graphic_and_a_flash_alone(self):
        scenes = [{"startFrame": 0, "durationInFrames": 90, "media": {"type": "image"}, "motion": "pan-left"},
                  {"startFrame": 90, "durationInFrames": 90, "media": {"type": "animation"}, "animation": {"x": 1}},
                  {"startFrame": 180, "durationInFrames": 30, "media": {"type": "video"}, "teaser": True},
                  {"startFrame": 210, "durationInFrames": 90, "media": {"type": "video"},
                   "reframe": {"from": {"x": 0, "y": 0, "w": 1, "h": 1}, "to": {"x": .1, "y": .1, "w": .8, "h": .8}}},
                  {"startFrame": 300, "durationInFrames": 20, "media": {"type": "image"}, "motion": "none"}]
        with boosted():
            stats = hookboost.push_in(scenes, [None] * 5, FPS, measure=lambda a: self.STATIC)
        self.assertEqual(stats, {"stills": 0, "clips": 0, "checked": 0})
        self.assertEqual(scenes[0]["motion"], "pan-left")
        self.assertNotIn("reframe", scenes[2])
        self.assertEqual(scenes[4]["motion"], "none")                          # under 1.2 s: no move

    def test_the_first_cuts_get_a_soft_whoosh_at_the_owners_level(self):
        doc = self.doc(motion=self.MOVING)
        cuts = [sc["startFrame"] for sc in doc["scenes"][1:4]]
        whooshes = [fx for fx in doc["sfx"] if fx["kind"] == "transition"]
        self.assertTrue(whooshes)
        self.assertLessEqual(len(whooshes), 3)
        for fx in whooshes:
            peak = timeline.sfx_meta().get(fx["name"], {}).get("peak", 0.0)
            self.assertIn(fx["startFrame"] + int(round(peak * FPS)), cuts)       # its loudest point lands on a cut
            self.assertIn(fx["name"], {n for n, _ in timeline._TRANSITION_SFX.values()})   # an existing sound
            self.assertLessEqual(fx["volume"], sfxplan.cap(doc["meta"]["voiceLufs"], fx["name"]) + 1e-9)
        # The owner's mix: the master stays 20%, and nothing is lowered or raised by the cap.
        self.assertEqual(doc["sfxVolume"], 0.4)       # the owner's level since 2026-10-02
        self.assertEqual(timeline.cap_sfx_levels(doc), 0)
        self.assertEqual(doc["meta"]["hookBoost"]["cutSounds"], 3)

    def test_without_the_flag_there_is_no_extra_whoosh_push_or_report(self):
        segs = story(OPENING + SHORT + LATER + plain(6))
        with mock.patch.object(config, "HOOK_BOOST", False):
            doc = self.build(segs, [video(i) for i in range(len(segs))], self.STATIC)
        self.assertFalse([fx for fx in doc["sfx"] if fx.get("kind") == "transition"])
        self.assertFalse([sc for sc in doc["scenes"] if "reframe" in sc or "teaser" in sc])
        self.assertNotIn("hookBoost", doc["meta"])

    def test_flag_on_but_nothing_to_do_is_the_same_document(self):
        # A window of 0 s leaves nothing to cut, push or sound: the document is the one the flag-off build makes.
        segs = story(OPENING + SHORT + LATER + plain(6))
        assets = [video(i) for i in range(len(segs))]
        with mock.patch.object(config, "HOOK_BOOST", False):
            off = self.build(segs, assets, self.STATIC)
        with boosted(HOOK_BOOST_SECONDS=0.0):
            on = self.build(segs, assets, self.STATIC)
        on["meta"].pop("hookBoost")
        self.assertEqual(json.dumps(off, sort_keys=True), json.dumps(on, sort_keys=True))

    def test_a_cut_that_already_has_its_own_sound_is_not_doubled(self):
        clip = "pack:" + sorted(timeline.pack_meta())[0]
        scenes = [{"startFrame": 0, "durationInFrames": 90, "transition": "none"},
                  {"startFrame": 90, "durationInFrames": 90, "transition": "glitch"},     # its own sound
                  {"startFrame": 180, "durationInFrames": 90, "transition": clip},       # a pack clip brings its own
                  {"startFrame": 270, "durationInFrames": 90, "transition": "none"},
                  {"startFrame": 360, "durationInFrames": 90, "transition": "none"}]
        with boosted(HOOK_BOOST_SFX_CUTS=3):
            self.assertEqual(hookboost.cut_sounds(scenes, FPS), {3: hookboost.SOFT_CUTS[2]})   # cuts 1-3 are the first three
        with boosted(HOOK_BOOST_SFX_CUTS=0):
            self.assertEqual(hookboost.cut_sounds(scenes, FPS), {})
        with mock.patch.object(config, "HOOK_BOOST", False):
            self.assertEqual(hookboost.cut_sounds(scenes, FPS), {})


class QuietScreen(unittest.TestCase):
    TEXT = {"headline", "key-phrase", "question"}

    def test_the_rule(self):
        text_look = {"category": "HEADLINES", "kind": "tag"}
        number_look = {"category": "NUMBERS", "kind": "tag"}
        with boosted(HOOK_BOOST_QUIET_SECONDS=5.0):
            self.assertTrue(hookboost.quiet(2.0, "normal", "headline", text_look, self.TEXT))
            self.assertTrue(hookboost.quiet(2.0, "director", "", text_look, self.TEXT))        # by its look alone
            self.assertTrue(hookboost.quiet(4.9, "normal", "key-phrase", number_look, self.TEXT))   # by its cue
            self.assertFalse(hookboost.quiet(2.0, "must", "headline", text_look, self.TEXT))   # a date or number to show
            self.assertFalse(hookboost.quiet(2.0, "normal", "percent", number_look, self.TEXT))
            self.assertFalse(hookboost.quiet(5.0, "normal", "headline", text_look, self.TEXT))
        with mock.patch.object(config, "HOOK_BOOST", False):
            self.assertFalse(hookboost.quiet(2.0, "normal", "headline", text_look, self.TEXT))

    REST = [("Plain words about the river and the town continue here for a while longer.", 5.0)] * 6

    def early_graphics(self, first, flag):
        """(the looks drawn in the first five seconds, how many the rule held back) for a first line."""
        from src import templates
        segs = story([(first, 5.0)] + self.REST, start=0.4)
        shots = [{"subject": "Texas Hill Country"} for _ in segs]
        brief = {"kind": "news", "hookBeats": [0], "sections": [], "places": ["Kerr County, Texas"]}
        scenes = [{"id": f"s{i}", "startFrame": int(round(s.start * FPS)),
                   "durationInFrames": int(round((s.end - s.start) * FPS)),
                   "media": {"type": "video", "url": f"https://x/{i}.mp4"}, "transition": "none"}
                  for i, s in enumerate(segs)]
        total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
        with mock.patch.object(config, "HOOK_BOOST", flag):
            hookboost.LAST.clear()
            out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, "news"),
                                  timeline._OVERLAY_SECONDS)
        early = [(templates.get(o.get("template") or "") or {}).get("category")
                 for o in out["overlays"] if o["startFrame"] / FPS < 5.0]
        return early, len(hookboost.LAST.get("quietedKeys") or ())

    def test_a_headline_question_or_quote_waits_until_after_the_first_five_seconds(self):
        for first in ("Why is the largest lake in the country disappearing?",
                      "Officials call it a once in a lifetime flood event.",
                      "Warning: the river is expected to crest tonight."):
            before, _ = self.early_graphics(first, False)
            self.assertTrue(set(before) & hookboost.TEXT_CATEGORIES, (first, before))      # drawn today ...
            after, held = self.early_graphics(first, True)
            self.assertFalse(set(after) & hookboost.TEXT_CATEGORIES, (first, after))       # ... held back with the flag
            self.assertGreater(held, 0)

    def test_a_date_the_first_line_says_is_still_shown(self):
        first = "On Wednesday, July 2, heavy rain began to fall over the Texas Hill Country."
        before, _ = self.early_graphics(first, False)
        after, _ = self.early_graphics(first, True)
        self.assertTrue(before)
        self.assertEqual(after, before)                                          # the same date graphic, untouched



# --------------------------------------------------------------------------- D. the cold open
class ColdOpen(unittest.TestCase):
    FIRST = [("What if I told you this whole town ran out of water in a single week?", 5.2)]

    def segs(self, first=None):
        return story((first or self.FIRST) + [("The story starts in a small town in the Texas Panhandle, "
                                                "where wells ran dry.", 4.8)] + plain(12) + LATER)

    def assets(self, segs):
        return [video(i, rel=0.9 if i >= 4 else 0.82, desc=("aerial view of flames and people" if i % 3 == 0 else ""))
                for i in range(len(segs))]

    def doc(self, segs=None, assets=None, **over):
        segs = segs or self.segs()
        assets = assets or self.assets(segs)
        with mock.patch.multiple(config, HOOK_TEASER=True, **over):
            return build(segs, assets), segs, assets

    def test_three_one_second_flashes_of_later_shots_open_a_hook_question(self):
        doc, segs, assets = self.doc()
        flashes = [sc for sc in doc["scenes"] if sc.get("teaser")]
        self.assertEqual(len(flashes), 3)
        self.assertEqual([sc["id"] for sc in flashes], ["s0000", "s0001", "s0002"])      # from the very start
        self.assertEqual(flashes[0]["startFrame"], 0)
        for sc in flashes:
            self.assertAlmostEqual(sc["durationInFrames"] / FPS, 1.0, delta=0.5)
        own = doc["scenes"][3]
        self.assertNotIn("teaser", own)
        self.assertGreaterEqual(own["durationInFrames"] / FPS, 1.5)                 # the line's own shot keeps its time
        self.assertEqual(own["startFrame"], flashes[-1]["startFrame"] + flashes[-1]["durationInFrames"])
        # The tiling is intact: every frame is a scene, back to back.
        for a, b in zip(doc["scenes"], doc["scenes"][1:]):
            self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
        self.assertEqual(doc["meta"]["hookBoost"]["teaser"]["firstLine"][:12], "What if I to")

    def test_each_flash_is_a_later_shot_that_shows_again_at_its_own_line_and_nowhere_else(self):
        doc, segs, assets = self.doc()
        scenes = doc["scenes"]
        flashes = [sc for sc in scenes if sc.get("teaser")]
        urls = [sc["media"]["url"] for sc in flashes]
        self.assertEqual(len(set(urls)), len(urls))                                  # three different shots
        for sc in flashes:
            own_lines = [x for x in scenes if x["media"]["url"] == sc["media"]["url"] and not x.get("teaser")]
            self.assertEqual(len(own_lines), 1, sc["media"]["url"])                  # at its own line, once
            self.assertGreater(own_lines[0]["startFrame"] / FPS, 30.0)               # a LATER shot, past the opening
        # Nothing else in the video repeats: every non-flash scene has its own file.
        files = [sc["media"]["url"] for sc in scenes if not sc.get("teaser")]
        self.assertEqual(len(files), len(set(files)))
        # The repeat checks leave the flashes out and still catch a real repeat.
        self.assertEqual(gapfill.find_repeats(doc), [])
        doc["scenes"][-1]["media"]["url"] = doc["scenes"][-3]["media"]["url"]
        self.assertTrue(gapfill.find_repeats(doc))

    def test_the_flashes_come_from_distinct_source_videos_that_pass_the_relevance_gate(self):
        segs = self.segs()
        assets = self.assets(segs)
        assets[10].relevance_score = 0.5                      # below VISION_MIN_SCORE: never flashed
        assets[11].review_required = True                     # flagged for review: never flashed
        assets[12] = video(11)                                # the same source video as scene 11's: counted once
        doc, _, _ = self.doc(segs=segs, assets=assets)
        flashed = {sc["media"]["url"] for sc in doc["scenes"] if sc.get("teaser")}
        self.assertNotIn(assets[10].local_path, flashed)
        self.assertNotIn(assets[11].local_path, flashed)
        videos = [hookboost.re.sub(r"@.*$", "", a.identity) for a in assets if a.local_path in flashed]
        self.assertEqual(len(videos), len(set(videos)))

    def test_a_first_line_that_is_no_hook_gets_no_teaser(self):
        segs = self.segs([("The reservoir sits northwest of the city and is operated by the county.", 5.2)])
        doc, _, _ = self.doc(segs=segs)
        self.assertFalse([sc for sc in doc["scenes"] if sc.get("teaser")])
        self.assertIn("not a hook", doc["meta"]["hookBoost"]["teaser"]["skipped"])
        self.assertTrue(hookboost.is_hook_line("Why is the largest lake in the country disappearing?"))
        self.assertTrue(hookboost.is_hook_line("Nobody saw the collapse coming."))
        self.assertFalse(hookboost.is_hook_line("The lake sits northwest of the city."))

    def test_fewer_than_two_qualifying_shots_or_a_first_line_too_short_gets_none(self):
        segs = self.segs()
        assets = [video(i, rel=0.5) for i in range(len(segs))]
        doc, _, _ = self.doc(segs=segs, assets=assets)
        self.assertFalse([sc for sc in doc["scenes"] if sc.get("teaser")])
        self.assertIn("fewer than two", doc["meta"]["hookBoost"]["teaser"]["skipped"])
        short = self.segs([("Why did it all dry up?", 2.2)])
        doc, _, _ = self.doc(segs=short)
        self.assertFalse([sc for sc in doc["scenes"] if sc.get("teaser")])

    def test_the_flashes_are_two_to_four_whatever_is_asked(self):
        long_line = [("What if I told you this whole town ran out of water in a single week, "
                      "and nobody outside the county ever noticed?", 7.4)]
        for asked, expected in ((1, 2), (9, 4)):
            doc, _, _ = self.doc(segs=self.segs(long_line), HOOK_TEASER_SHOTS=asked)
            self.assertEqual(len([sc for sc in doc["scenes"] if sc.get("teaser")]), expected, asked)

    def test_off_by_default_and_it_works_alongside_the_booster(self):
        segs = self.segs()
        assets = self.assets(segs)
        doc = build(segs, assets)
        self.assertFalse([sc for sc in doc["scenes"] if "teaser" in sc])
        self.assertNotIn("hookBoost", doc["meta"])
        with boosted():
            cut, _, info = hookboost.prepare(segs, {"hookBeats": [0], "sections": []}, {})
        self.assertGreater(len(cut), len(segs))
        doc, _, _ = self.doc(segs=cut, assets=self.assets(cut), HOOK_BOOST=True)
        self.assertEqual(len([sc for sc in doc["scenes"] if sc.get("teaser")]), 3)
        self.assertTrue(doc["meta"]["hookBoost"]["enabled"])

    def test_a_teaser_flash_is_not_a_second_use_for_the_clip_checks(self):
        scene = {"teaser": True, "startFrame": 0, "media": {"type": "video", "url": "/tmp/a.mp4"},
                 "semanticMetadata": {"assetId": "yt:abcdefghijk"}}
        self.assertIsNone(gapfill.Shot.of_scene(scene, FPS))
        del scene["teaser"]
        self.assertIsNotNone(gapfill.Shot.of_scene(scene, FPS))


# --------------------------------------------------------------------------- D2. never a weaker shot
class NeverAWeakerShot(unittest.TestCase):
    """A faster cut never shows a clip that fits its line worse than the gate: the good shot of the beat is held."""

    def setUp(self):
        self.segs = story(OPENING + SHORT + LATER + plain(6))
        with boosted():
            self.cut, self.parents, self.info = hookboost.split_opening(self.segs)
        self.first = [i for i, par in enumerate(self.parents) if par == 0]            # the pieces of the first beat
        self.assertGreaterEqual(len(self.first), 2)

    def doc(self, weak=(), clip=8.0, relevance=0.9):
        assets = []
        for i in range(len(self.cut)):
            a = video(i, rel=0.5 if i in weak else relevance)
            a.duration = clip
            assets.append(a)
        with boosted():
            return build(self.cut, assets)

    def test_a_shot_under_the_gate_gives_way_to_the_good_shot_beside_it(self):
        weak = self.first[1]
        doc = self.doc(weak={weak})
        n = len(doc["scenes"])
        weak_id = doc["scenes"][weak]["id"]
        keep = doc["scenes"][weak - 1]
        frames = keep["durationInFrames"] + doc["scenes"][weak]["durationInFrames"]
        words = len(keep["words"]) + len(doc["scenes"][weak]["words"])
        with boosted():
            got = hookboost.settle(doc, self.info)
        self.assertEqual(got["held"], 1)
        self.assertEqual(len(doc["scenes"]), n - 1)
        self.assertNotIn(weak_id, [sc["id"] for sc in doc["scenes"]])
        self.assertEqual(keep["durationInFrames"], frames)                          # its clip covers the beat now
        self.assertEqual(len(keep["words"]), words)                                # the words went with the frames
        self.assertIn(weak_id, keep["semanticMetadata"]["heldOver"])
        self.assertEqual(doc["meta"]["sceneCount"], n - 1)
        for a, b in zip(doc["scenes"], doc["scenes"][1:]):                          # still tiles the narration
            self.assertEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])
        self.assertFalse([sc for sc in doc["scenes"] if sc["media"].get("relevanceScore", 1) < config.VISION_MIN_SCORE])

    def test_the_sound_of_the_cut_that_is_gone_goes_with_it(self):
        weak = self.first[1]
        doc = self.doc(weak={weak})
        cut = doc["scenes"][weak]["startFrame"]
        peaks = timeline.sfx_meta()

        def at_cut(d):
            return [fx for fx in d["sfx"] if fx.get("kind") == "transition"
                    and abs(fx["startFrame"] + int(round(peaks.get(fx["name"], {}).get("peak", 0.0) * FPS)) - cut) <= 1]

        self.assertTrue(at_cut(doc))                                               # the booster's whoosh was there
        with boosted():
            hookboost.settle(doc, self.info)
        self.assertFalse(at_cut(doc))

    def test_a_beat_whose_shots_all_missed_the_gate_is_left_as_sourced(self):
        doc = self.doc(weak=set(self.first))
        before = json.dumps(doc["scenes"], sort_keys=True)
        with boosted():
            got = hookboost.settle(doc, self.info)
        self.assertEqual(got["held"], 0)
        self.assertEqual(json.dumps(doc["scenes"], sort_keys=True), before)

    def test_a_neighbour_whose_clip_is_too_short_to_cover_it_is_not_stretched(self):
        weak = self.first[1]
        doc = self.doc(weak={weak}, clip=1.2)                                        # 1.2 s of footage for a 2.5 s shot
        with boosted():
            got = hookboost.settle(doc, self.info)
        self.assertEqual(got["held"], 0)

    def test_nothing_was_cut_nothing_is_held(self):
        doc = self.doc(weak={self.first[1]})
        before = json.dumps(doc, sort_keys=True)
        self.assertEqual(hookboost.settle(doc, {}), {"beats": 0, "held": 0})
        self.assertEqual(hookboost.settle(doc, None), {"beats": 0, "held": 0})
        self.assertEqual(json.dumps(doc, sort_keys=True), before)


# --------------------------------------------------------------------------- E. the report
class TheReport(unittest.TestCase):
    def test_the_document_says_what_changed(self):
        segs = story(OPENING + SHORT + LATER + plain(6))
        brief = {"hookBeats": [0], "sections": []}
        with boosted():
            cut, _, info = hookboost.prepare(segs, brief, {})
            doc = build(cut, [video(i) for i in range(len(cut))])
        report = hookboost.merge_report(doc["meta"]["hookBoost"], info)
        self.assertTrue(report["enabled"])
        self.assertEqual(report["seconds"], 30.0)
        self.assertGreater(report["shotsAdded"], 0)
        self.assertEqual(report["beatsAfter"] - report["beatsBefore"], report["shotsAdded"])
        self.assertGreater(report["openingBefore"]["avgShotSeconds"], report["opening"]["avgShotSeconds"])
        self.assertLessEqual(report["opening"]["avgShotSeconds"], 3.0)
        self.assertEqual(report["opening"]["scenes"], info["afterPlan"]["scenes"])
        self.assertTrue(report["splits"] and {"beat", "start", "end", "pieces", "cutBefore"} <= set(report["splits"][0]))
        json.dumps(report)                                                           # it goes into the document


if __name__ == "__main__":
    unittest.main()
