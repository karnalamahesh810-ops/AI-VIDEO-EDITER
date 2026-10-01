"""The overlay sound planner (src/sfxplan.py): on the hit, under the voice, sparse, varied."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src import sfxplan

FILES = {  # name: (duration s, peak s)
    "whoosh": (2.3, 0.7), "whoosh-soft": (1.1, 0.4), "swipe": (0.44, 0.2),
    "impact": (2.4, 0.6), "boom-soft": (1.7, 0.3), "click": (0.11, 0.0), "tick": (0.09, 0.0),
    "keys": (5.0, 0.4), "count-tick": (1.32, 0.96), "pop": (0.48, 0.03), "marker": (0.7, 0.16),
}
# At the assumed voice (sfxplan.VOICE_LUFS_DEFAULT) against the -20 LUFS sound set:
# 10 ** ((voice - dB under + 20) / 20).
AT = {d: round(10 ** ((sfxplan.VOICE_LUFS_DEFAULT - d - sfxplan.SFX_REF_LUFS) / 20), 3) for d in (5, 6, 7, 9, 10)}


def T(tid, sfx="whoosh", emphasis="medium", cues=(), component="motion", **defaults):
    return {"id": tid, "component": component, "cues": list(cues), "emphasis": emphasis,
            "defaults": {"duration": 3.0, "sfx": {"name": sfx, "volume": 0.3}, **defaults}}


REG = {t["id"]: t for t in [
    T("LOOK_A", "whoosh", sfxAt=12),
    T("LOOK_B", "whoosh"),
    T("LOOK_HIGH", "impact", emphasis="high"),
    T("LOOK_LOW", "pop", emphasis="low"),
    T("TYPE_LOOK", "none", types=True),
    T("TEXT_TYPEWRITER_V1", "typewriter", component="typewriter"),
    T("TEXT_MEMO_V1", "typewriter", component="memo-box"),
    T("TEXT_BAR_TITLE_V1", "typewriter", component="bar-title"),
    T("KICKER", "typewriter", types=False),
    T("DATE_LOOK", "impact", cues=["date"], emphasis="high", sfxAt=20),
    dict(T("LIB_DT_DATE_SLAM", "boom-soft", cues=["date"], emphasis="high", sfxAt=18), category="TIMELINES"),
    dict(T("TL_CLOCK_LOOK", "marker", cues=["time-of-day"], sfxAt=10), category="TIMELINES"),
    T("COUNT_LOOK", "pop", cues=["percent"]),
    T("COUNT_HIT", "pop", cues=["big-number"], sfxAt=45),
    T("COUNT_CLICK_IN", "click", cues=["big-number"], sfxAt=6, types=False),
    T("SILENT", "none"),
    T("MISSING", "no-such-sound"),
    T("LIB_CC_TICK_BARS", "pop"), T("LIB_BM_STATE_CALLOUT", "map-whoosh"),
    T("LIB_SP_STATEMENT_CARD", "paper"), T("LIB_PS_PERCENT_RING", "pop"),
]}


def ov(tid, start, frames=90, **kw):
    return {"template": tid, "startFrame": start, "durationInFrames": frames, **kw}


class SfxPlanTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in FILES:
            open(os.path.join(self.dir, f"{name}.mp3"), "wb").close()
        with open(os.path.join(self.dir, "sfx_meta.json"), "w", encoding="utf-8") as fh:
            json.dump({n: {"duration": d, "peak": p} for n, (d, p) in FILES.items()}, fh)
        self.patches = [mock.patch.object(sfxplan, "SFX_DIR", self.dir),
                        # The renderer's copy of the meta stays out of these hermetic tests.
                        mock.patch.object(sfxplan, "DATA_META", os.path.join(self.dir, "no-such-meta.json")),
                        mock.patch.object(sfxplan.templates, "get", lambda tid: REG.get(tid or ""))]
        for p in self.patches:
            p.start()
        sfxplan.reload()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        sfxplan.reload()
        shutil.rmtree(self.dir, ignore_errors=True)

    def remove(self, *names):
        for n in names:
            os.remove(os.path.join(self.dir, f"{n}.mp3"))


class Alignment(SfxPlanTest):
    def test_the_peak_lands_on_the_looks_hit(self):
        [s] = sfxplan.plan([ov("LOOK_A", 300)], 30, 1.0)
        # hit = 300 + sfxAt 12; whoosh peaks 0.7 s (21 frames) in. The sound
        # never starts before its look: it starts with it and skips the head
        # of the file, so the peak still lands on frame 312.
        self.assertEqual((s["name"], s["startFrame"], s["trimFrames"]), ("whoosh", 300, 9))
        self.assertEqual(s["startFrame"] - s["trimFrames"] + 21, 312)
        self.assertEqual(s["durationFrames"], 69)          # the whole file: it ends inside the look
        # A look shorter than its sound: the sound is over when the look leaves
        # (the renderer fades a cut sound over its last frames), never ringing past it.
        [s] = sfxplan.plan([ov("LOOK_A", 300, frames=30)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 9 + 30)
        self.assertEqual(s["startFrame"] - s["trimFrames"] + s["durationFrames"], 300 + 30)
        self.assertEqual(s["kind"], "overlay")
        self.assertEqual(set(s), {"name", "startFrame", "volume", "durationFrames", "kind", "trimFrames"})

    def test_frames_scale_with_the_frame_rate(self):
        [s] = sfxplan.plan([ov("LOOK_A", 600)], 60, 1.0)
        self.assertEqual((s["startFrame"], s["trimFrames"]), (600, 18))      # peak on 624

    def test_no_sfx_at_means_the_entrance_and_never_before_the_look(self):
        [s] = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0)
        # No hit frame: the entrance lands ~8 frames in; peak (21) on 308.
        self.assertEqual((s["startFrame"], s["trimFrames"]), (300, 13))
        [s] = sfxplan.plan([ov("LOOK_B", 5)], 30, 1.0)
        self.assertEqual(s["startFrame"], 5)

    def test_an_overlay_can_carry_its_own_hit_frame(self):
        [s] = sfxplan.plan([ov("LOOK_B", 300, sfxAt=30)], 30, 1.0)
        self.assertEqual(s["startFrame"], 300 + 30 - 21)             # late enough: no trim
        self.assertNotIn("trimFrames", s)

    def test_exports(self):
        self.assertEqual(sfxplan.peak_frames("whoosh", 30), 21)
        self.assertEqual(sfxplan.peak_frames("whoosh", 60), 42)
        self.assertTrue(sfxplan.exists("keys"))
        self.assertFalse(sfxplan.exists("no-such-sound"))
        self.assertFalse(sfxplan.exists("none"))
        self.assertFalse(sfxplan.exists("../keys"))


class Typing(SfxPlanTest):
    def test_keys_run_exactly_while_the_text_types(self):
        text = "Where did the water go?"                  # 23 chars <= 48: 2 frames a character
        [s] = sfxplan.plan([ov("TYPE_LOOK", 100, 200, text=text)], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("keys", 106, 46))
        self.assertEqual(s["volume"], AT[10])                # a typing loop sits ~10 dB under the voice

    def test_long_text_types_one_frame_a_character_and_is_capped(self):
        text = "x" * 60
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 400, text=text)], 30, 1.0)
        self.assertEqual((s["startFrame"], s["durationFrames"]), (6, 60))
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 900, text="y" * 400)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 180)          # 6 s cap
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 900, text="y" * 20)], 60, 1.0)
        self.assertEqual((s["startFrame"], s["durationFrames"]), (12, 80))

    def test_typing_stops_when_the_look_leaves(self):
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 30, text="z" * 40)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 24)
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 5, text="z")], 30, 1.0), [])
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="  ")], 30, 1.0), [])

    def test_a_typing_look_with_a_silent_registry_sound_still_types_aloud(self):
        # The planner may leave the resolved default {"name": "none"} on the overlay.
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc", sfx={"name": "none", "volume": 0.0})], 30, 1.0)
        self.assertEqual(s["name"], "keys")
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc", sfx="none")], 30, 1.0), [])

    def test_the_typewriter_template_types_even_without_the_flag(self):
        [s] = sfxplan.plan([ov("TEXT_TYPEWRITER_V1", 0, 90, text="Why?")], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("keys", 6, 8))

    def test_fixed_window_typing_looks_stop_when_their_text_is_typed(self):
        # MemoBox types frames 6-42 and BarTitle 9-42 at 30 fps whatever the
        # text length; the keys must not clack on after the last letter.
        for text in ("THE DAM WAS NEVER BUILT FOR THIS FLOOD", "x" * 48, "y" * 120):
            for tid, first in (("TEXT_MEMO_V1", 6), ("TEXT_BAR_TITLE_V1", 9)):
                [s] = sfxplan.plan([ov(tid, 0, 180, text=text)], 30, 1.0)
                self.assertEqual(s["startFrame"], first, (tid, text))
                self.assertLessEqual(s["startFrame"] + s["durationFrames"], 42, (tid, text))
        [s] = sfxplan.plan([ov("TEXT_MEMO_V1", 0, 360, text="x" * 48)], 60, 1.0)
        self.assertLessEqual(s["startFrame"] + s["durationFrames"], 84)
        # Still never past the look's own end.
        [s] = sfxplan.plan([ov("TEXT_MEMO_V1", 0, 20, text="x" * 48)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 14)

    def test_a_look_that_does_not_type_never_clacks(self):
        [s] = sfxplan.plan([ov("KICKER", 0, 90, text="LAKE MEAD")], 30, 1.0)
        self.assertEqual(s["name"], "click")

    def test_the_old_typing_file_stands_in_for_keys(self):
        self.remove("keys")
        open(os.path.join(self.dir, "typewriter.mp3"), "wb").close()
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc")], 30, 1.0)
        self.assertEqual(s["name"], "typewriter")
        os.remove(os.path.join(self.dir, "typewriter.mp3"))
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc")], 30, 1.0), [])


class Counting(SfxPlanTest):
    def test_a_number_that_counts_ticks_for_the_count(self):
        [s] = sfxplan.plan([ov("COUNT_LOOK", 300, value=22, suffix="%")], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("count-tick", 306, 39))

    def test_the_count_ends_on_the_hit(self):
        [s] = sfxplan.plan([ov("COUNT_HIT", 300, value=1200)], 30, 1.0)
        self.assertEqual((s["startFrame"], s["durationFrames"]), (306, 39))

    def test_an_entrance_hit_before_the_count_starts_the_count_on_it(self):
        # The corner stat clicks in at frame 6 (sfxAt), then counts 8-44: the
        # ticks run with the count, not as a blip before it.
        [s] = sfxplan.plan([ov("COUNT_CLICK_IN", 300, 135, value=42)], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("count-tick", 306, 39))

    def test_no_value_or_no_tick_file_keeps_the_looks_own_sound(self):
        [s] = sfxplan.plan([ov("COUNT_LOOK", 300)], 30, 1.0)
        self.assertEqual(s["name"], "pop")
        self.remove("count-tick")
        [s] = sfxplan.plan([ov("COUNT_LOOK", 300, value=22)], 30, 1.0)
        self.assertEqual(s["name"], "pop")


class Volume(SfxPlanTest):
    """The owner (2026-09-30): the sounds were far too low; set them against the voice, never above it."""

    def test_levels_sit_under_the_voice_by_kind_and_scale_with_the_pack(self):
        got = {s["name"]: s["volume"] for s in sfxplan.plan(
            [ov("LOOK_HIGH", 0), ov("LOOK_B", 300), ov("KICKER", 600, text="A"),
             ov("TYPE_LOOK", 900, text="abc")], 30, 1.0)}
        # Hits 6 dB under the voice, clicks 7, whooshes 9, typing 10 (the owner, 2026-10-01: never over the voice).
        self.assertEqual(got, {"impact": AT[6], "whoosh": AT[9], "click": AT[7], "keys": AT[10]})
        half = sfxplan.plan([ov("LOOK_B", 300)], 30, 0.5)
        self.assertEqual(half[0]["volume"], round(AT[9] * 0.5, 3))
        # Nothing like the old 0.09-0.135: every planned sound is within reach of the voice.
        self.assertTrue(all(v >= 0.3 for v in got.values()), got)

    def test_the_levels_follow_the_measured_voice(self):
        quiet = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0, voice_lufs=-24.0)[0]["volume"]
        normal = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0, voice_lufs=-16.0)[0]["volume"]
        self.assertAlmostEqual(normal / quiet, 10 ** (8 / 20), places=2)      # 8 dB quieter voice, 8 dB quieter sound
        # A loud voice never pushes a sound past the renderer's 1.0.
        loud = sfxplan.plan([ov("LOOK_HIGH", 0)], 30, 1.0, voice_lufs=-8.0)[0]["volume"]
        self.assertLessEqual(loud, 1.0)
        # Unknown or absurd levels fall back to the assumed voice.
        self.assertEqual(sfxplan.voice_level(None), sfxplan.VOICE_LUFS_DEFAULT)
        self.assertEqual(sfxplan.voice_level("x"), sfxplan.VOICE_LUFS_DEFAULT)
        self.assertEqual(sfxplan.voice_level(3.0), sfxplan.VOICE_LUFS_DEFAULT)

    def test_never_louder_than_the_cap(self):
        loud = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_B", 400, sfxVolume=1.0)], 30, 3.0)
        top = round(sfxplan.cap(), 3)
        self.assertTrue(all(s["volume"] <= top for s in loud), loud)
        self.assertEqual(loud[1]["volume"], top)           # the editor's 100% comes back to the cap
        self.assertEqual(top, AT[sfxplan.CAP_UNDER_DB])    # the cap is the hits' level: 6 dB under the voice
        # An editor's quieter choice stands as set.
        [s] = sfxplan.plan([ov("LOOK_B", 400, sfxVolume=0.2)], 30, 1.0)
        self.assertEqual(s["volume"], 0.2)
        # clamp() also lowers the ceiling for a master sfxVolume above 1.
        self.assertAlmostEqual(sfxplan.clamp(1.0, None, 2.0), sfxplan.cap() / 2)
        self.assertEqual(sfxplan.clamp(-1), 0.0)

    def test_a_category_in_the_meta_sets_the_level(self):
        open(os.path.join(self.dir, "shimmer-new.mp3"), "wb").close()
        with open(os.path.join(self.dir, "sfx_meta.json"), "w", encoding="utf-8") as fh:
            json.dump({**{n: {"duration": d, "peak": p} for n, (d, p) in FILES.items()},
                       "shimmer-new": {"duration": 1.0, "peak": 0.2, "category": "shimmer"},
                       "whoosh": {"duration": 2.3, "peak": 0.7, "category": "impact"}}, fh)
        sfxplan.reload()
        self.assertEqual(sfxplan.category("shimmer-new"), "shimmer")
        self.assertEqual(round(sfxplan.level("shimmer-new"), 3), AT[9])
        self.assertEqual(round(sfxplan.level("whoosh"), 3), AT[6])           # the meta beats the name
        self.assertEqual(sfxplan.category("keys"), "typing")                 # no category: the name decides
        self.assertEqual(round(sfxplan.level("no-such-sound"), 3), AT[6])    # unknown: 6 dB under

    def test_the_renderer_copy_of_the_meta_fills_in_a_category(self):
        data = os.path.join(self.dir, "data_meta.json")
        with open(data, "w", encoding="utf-8") as fh:
            json.dump({"pop": {"duration": 9.0, "peak": 9.0, "category": "impact"}}, fh)
        with mock.patch.object(sfxplan, "DATA_META", data):
            sfxplan.reload()
            self.assertEqual(sfxplan.category("pop"), "impact")
            self.assertEqual(sfxplan.duration_frames("pop", 30), 15)        # the sound folder's own numbers win
        sfxplan.reload()

    def test_zero_intensity_is_silence(self):
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0)], 30, 0.0), [])


class FollowsTheLook(SfxPlanTest):
    """The owner (2026-09-30): a sound starts with its look, peaks on its hit, is over when it leaves."""

    def test_a_look_cut_short_before_its_hit_is_silent(self):
        self.assertEqual(sfxplan.plan([ov("LOOK_A", 300, frames=12)], 30, 1.0), [])      # hit at 12: never shown
        self.assertEqual(sfxplan.plan([ov("LOOK_A", 300, frames=15)], 30, 1.0), [])      # 3 frames of it: no
        [s] = sfxplan.plan([ov("LOOK_A", 300, frames=20)], 30, 1.0)
        self.assertLessEqual(s["startFrame"] + s["durationFrames"] - s.get("trimFrames", 0), 320)

    def test_no_sound_rings_past_its_look(self):
        looks = [ov("LOOK_HIGH", 0, 25), ov("TYPE_LOOK", 300, 20, text="z" * 40),
                 ov("COUNT_LOOK", 600, 30, value=22), ov("LOOK_B", 900, 40)]
        for s, o in zip(sfxplan.plan(looks, 30, 1.0), looks):
            end = s["startFrame"] + s["durationFrames"] - s.get("trimFrames", 0)
            self.assertGreaterEqual(s["startFrame"], o["startFrame"], s)
            self.assertLessEqual(end, o["startFrame"] + o["durationInFrames"], s)

    def test_two_looks_landing_together_get_one_sound_the_stronger(self):
        out = sfxplan.plan([ov("LOOK_LOW", 0, 200), ov("LOOK_HIGH", 12, 200)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact"])
        # Even two protected looks: a typed line and a date 0.3 s apart sound once.
        out = sfxplan.plan([ov("TYPE_LOOK", 0, 60, text="Gone."), ov("LIB_DT_DATE_SLAM", 9, 60, text="MAY 5")],
                           30, 1.0)
        self.assertEqual(len(out), 1)
        # 0.6 s apart they are two moments.
        out = sfxplan.plan([ov("TYPE_LOOK", 0, 16, text="Gone."), ov("LIB_DT_DATE_SLAM", 18, 60, text="MAY 5")],
                           30, 1.0)
        self.assertEqual(len(out), 2)


class Dates(SfxPlanTest):
    """The owner (2026-10-01): a date sounds like its digits - one soft tick, never a punch or a hit."""

    def setUp(self):
        super().setUp()
        open(os.path.join(self.dir, "hit-deep.mp3"), "wb").close()
        with open(os.path.join(self.dir, "sfx_meta.json"), "w", encoding="utf-8") as fh:
            json.dump({**{n: {"duration": d, "peak": p} for n, (d, p) in FILES.items()},
                       "hit-deep": {"duration": 2.3, "peak": 0.02}}, fh)
        sfxplan.reload()

    def test_every_date_ticks_softly_and_never_hits(self):
        looks = [ov("LIB_DT_DATE_SLAM", 300 * k, 90, text="SEPTEMBER 15") for k in range(4)]
        out = sfxplan.plan(looks, 30, 1.0)
        # The tick's first stand-in that ships here ("tick"), never the deep hit beside it, however often dates come.
        self.assertEqual(sfxplan.date_sound(), "tick")
        self.assertEqual([s["name"] for s in out], ["tick"] * 4)
        self.assertTrue(all(s["volume"] == AT[7] for s in out), out)       # the ticks' level, 7 dB under the voice
        # On the look's hit (sfxAt 18), played whole however short it is.
        self.assertEqual(out[0]["startFrame"], 18)
        self.assertEqual(out[0]["durationFrames"], sfxplan.duration_frames("tick"))

    def test_a_clock_keeps_its_own_sound_and_an_editor_pick_wins(self):
        [s] = sfxplan.plan([ov("TL_CLOCK_LOOK", 0, 90, text="3:45 PM")], 30, 1.0)
        self.assertEqual(s["name"], "marker")
        [s] = sfxplan.plan([ov("LIB_DT_DATE_SLAM", 0, 90, text="MAY 5", sfx="pop")], 30, 1.0)
        self.assertEqual(s["name"], "pop")

    def test_what_is_a_calendar_date(self):
        self.assertTrue(sfxplan.is_calendar_date(REG["LIB_DT_DATE_SLAM"]))
        self.assertFalse(sfxplan.is_calendar_date(REG["TL_CLOCK_LOOK"]))
        self.assertFalse(sfxplan.is_calendar_date(REG["DATE_LOOK"]))        # not a date family look
        self.assertFalse(sfxplan.is_calendar_date({"id": "LIB_FX_FILM_BURN", "category": "TRANSITIONS",
                                                   "cues": ["archive", "date"]}))


class Spacing(SfxPlanTest):
    def test_one_sound_per_six_seconds_the_stronger_look_winning(self):
        out = sfxplan.plan([ov("LOOK_LOW", 0), ov("LOOK_HIGH", 60), ov("LOOK_B", 120)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact"])
        out = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_A", 60)], 30, 1.0)   # equal emphasis: first stays
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["startFrame"], 0)
        out = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_B", 180)], 30, 1.0)
        self.assertEqual(len(out), 2)

    def test_typing_and_dates_alone_on_screen_always_keep_their_sound(self):
        out = sfxplan.plan([ov("LOOK_HIGH", 0, 60), ov("TYPE_LOOK", 70, 60, text="Gone."),
                            ov("DATE_LOOK", 140, 60, text="SEPTEMBER 25, 2026")], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact", "keys", "boom-soft"])
        # The date's impact peak (0.3 s boom-soft after variation) lands on its sfxAt.
        self.assertEqual(out[2]["startFrame"], 140 + 20 - 9)

    def test_but_not_when_another_look_shares_the_screen(self):
        out = sfxplan.plan([ov("LOOK_HIGH", 0, 200), ov("TYPE_LOOK", 70, 60, text="Gone.")], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact"])

    def test_a_protected_sound_is_never_displaced(self):
        out = sfxplan.plan([ov("TYPE_LOOK", 0, 60, text="Gone."), ov("LOOK_HIGH", 90, 60)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["keys"])


class Choice(SfxPlanTest):
    def test_looks_with_their_own_sounds_are_skipped(self):
        for tid in ("LIB_CC_TICK_BARS", "LIB_BM_STATE_CALLOUT", "LIB_SP_STATEMENT_CARD", "LIB_PS_PERCENT_RING"):
            self.assertEqual(sfxplan.plan([ov(tid, 0, value=40)], 30, 1.0), [], tid)

    def test_silent_missing_and_unknown(self):
        self.assertEqual(sfxplan.plan([ov("SILENT", 0), ov("MISSING", 300), ov("NOPE", 600),
                                       {"type": "map", "startFrame": 900}], 30, 1.0), [])

    def test_editor_overrides(self):
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0, sfx="none")], 30, 1.0), [])
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0, sfx={"name": "none", "volume": 0})], 30, 1.0), [])
        [s] = sfxplan.plan([ov("LOOK_B", 300, sfx="marker")], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"]), ("marker", 300 + 8 - 5))
        [s] = sfxplan.plan([ov("LOOK_B", 300, sfx={"name": "whoosh", "volume": 0.3})], 30, 1.0)
        self.assertEqual(s["name"], "whoosh")               # the resolved default is not an override
        [s] = sfxplan.plan([ov("TYPE_LOOK", 300, sfx="swipe", text="abc")], 30, 1.0)
        self.assertEqual(s["name"], "swipe")                # an explicit sound beats typing
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0, sfx="no-such-sound")], 30, 1.0), [])

    def test_a_repeated_sound_alternates_with_its_siblings(self):
        out = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_B", 200), ov("LOOK_B", 400), ov("LOOK_B", 1300)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["whoosh", "whoosh-soft", "swipe", "whoosh"])

    def test_quiet_packs_start_soft(self):
        [s] = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0, style="cinematic")
        self.assertEqual(s["name"], "whoosh-soft")

    def test_missing_meta_is_tolerated(self):
        os.remove(os.path.join(self.dir, "sfx_meta.json"))
        sfxplan.reload()
        [s] = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0)
        self.assertEqual((s["startFrame"], s["trimFrames"]), (300, 13))   # measured peak of the original whoosh
        self.assertEqual(sfxplan.peak_frames("swipe", 30), 0)
        self.assertEqual(sfxplan.duration_frames("swipe", 30), 90)

    def test_output_is_sorted(self):
        out = sfxplan.plan([ov("LOOK_B", 900), ov("LOOK_HIGH", 0), ov("TYPE_LOOK", 400, text="abc")], 30, 1.0)
        self.assertEqual([s["startFrame"] for s in out], sorted(s["startFrame"] for s in out))


class RealFolder(unittest.TestCase):
    def test_every_sound_the_planner_names_ships(self):
        names = {sfxplan.TYPING_SOUND, sfxplan.COUNT_SOUND, sfxplan.NOT_TYPING_SOUND}
        names |= set(sfxplan.VARIANTS) | {v for vs in sfxplan.VARIANTS.values() for v in vs}
        missing = sorted(n for n in names if not sfxplan.exists(n))
        self.assertEqual(missing, [])

    # The real looks carry their sounds built in (registry defaults.sounds, played
    # by the renderer's LookSounds): no timeline row; the schedule is sfxplan's twin.
    def test_the_real_memo_and_bar_title_keys_end_with_their_typing(self):
        for tid in ("TEXT_MEMO_V1", "TEXT_BAR_TITLE_V1"):
            ovs = [{"template": tid, "startFrame": 0, "durationInFrames": 180,
                    "text": "THE DAM WAS NEVER BUILT FOR THIS FLOOD"}]
            self.assertEqual(sfxplan.plan(ovs, 30, 1.0), [], tid)
            [s] = [s for s in sfxplan.doc_look_sounds({"fps": 30, "overlays": ovs, "lookSounds": {}})
                   if s["name"] in sfxplan.TYPING_TAKES]
            self.assertGreaterEqual(s["startFrame"], 6)
            self.assertLessEqual(s["startFrame"] + s["frames"], 42, tid)      # the rebuilt looks type to 42

    def test_the_real_corner_stat_ticks_with_its_count(self):
        ovs = [{"template": "LIB_CT_CORNER_STAT", "startFrame": 300, "durationInFrames": 135, "value": 42}]
        self.assertEqual(sfxplan.plan(ovs, 30, 1.0), [])
        sounds = {s["name"]: s for s in sfxplan.doc_look_sounds({"fps": 30, "overlays": ovs, "lookSounds": {}})}
        roll, final = sounds["count-roll"], sounds["count-final"]
        # CornerStat counts on frames 8-40 and lands on 40 (LibCountPro: ramp(frame, 8, 32), LAND = 40).
        self.assertEqual((roll["name"], final["name"]), ("count-roll", "count-final"))
        self.assertEqual(roll["startFrame"], 308)
        self.assertEqual(roll["startFrame"] + roll["frames"], 340)
        peak = sfxplan._peak("count-final", 30)
        self.assertEqual(final["startFrame"] + peak, 340)


if __name__ == "__main__":
    unittest.main()


class OwnerSounds(unittest.TestCase):
    """The owner's own keyboard and glitch recordings (real sound folder)."""

    def test_typing_looks_take_the_owner_keyboards_in_turn(self):
        from src import templates
        typing = [t["id"] for t in templates.all_templates()
                  if any(c.get("kind") == "typing" for c in (t.get("defaults") or {}).get("sounds") or [])][:1]
        self.assertTrue(typing)
        ovs = [{"template": typing[0], "startFrame": 300 * i, "durationInFrames": 240, "text": "The water kept falling"}
               for i in range(3)]
        self.assertEqual(sfxplan.plan(ovs, 30, 1.0), [])
        names = [s["name"] for s in sfxplan.doc_look_sounds({"fps": 30, "overlays": ovs, "lookSounds": {}})]
        self.assertEqual(names[:3], ["keys-type", "keys-laptop", "keys-mech"])

    def test_the_files_are_there_and_measured(self):
        import json
        meta = json.load(open("remotion/public/sfx/sfx_meta.json", encoding="utf-8"))
        for name in ("keys-mech", "keys-type", "glitch-pro"):
            self.assertTrue(sfxplan.exists(name), name)
            self.assertIn(name, meta)
        main = open("remotion/src/Main.tsx", encoding="utf-8").read()
        self.assertIn('"keys-mech", "keys-type"', main)


class DeepHit(unittest.TestCase):
    def test_impacts_lead_with_the_owners_deep_hit(self):
        from src import templates
        # A look the designer's map leaves alone keeps the planner's rule: an impact is the deep hit.
        design = templates.get("CMP_VERSUS_V1")["defaults"]["sounds"]
        self.assertEqual(design, [{"name": "hit-deep", "at": 8, "alt": ["impact"]}])
        ovs = [{"template": "CMP_VERSUS_V1", "startFrame": 300, "durationInFrames": 150, "text": "x"}]
        self.assertEqual(sfxplan.plan(ovs, 30, 1.0), [])
        [s] = sfxplan.doc_look_sounds({"fps": 30, "overlays": ovs, "lookSounds": {}})
        self.assertEqual(s["name"], "hit-deep")
        # A date lands on a soft digital tick, never the deep hit (the owner, 2026-10-01: no punch sound).
        self.assertEqual(sfxplan.DATE_SOUND, "letter-tick")
        self.assertEqual(sfxplan.date_sound(), "letter-tick")
        self.assertIsNone(sfxplan.resolve_sound("date-slam"))
        self.assertIn("hit-deep", open("remotion/public/sfx/sfx_meta.json", encoding="utf-8").read())
